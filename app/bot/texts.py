"""Every text the user sees lives here (TZ 0.4).

Plain constants are ready-to-send strings; functions build texts with values.
Anything that comes from users (names, comments, reasons) must go through `esc()`.
"""

from datetime import date, datetime
from decimal import Decimal
from html import escape
from zoneinfo import ZoneInfo

from app.db.models import CashAdjustment, Client, Operation, User, UserStatus
from app.domain.currency import HOME_CURRENCY, Currency
from app.domain.dates import format_date, format_datetime, format_short_date
from app.domain.errors import ConversionProblem, InsufficientCash, NumberProblem
from app.domain.money import format_amount, format_money, format_rate, format_signed
from app.domain.operations import OperationType, RepayWarning, WarningKind


def esc(value: object) -> str:
    return escape(str(value), quote=False)


# --- Commands -------------------------------------------------------------------------------

CMD_START = "Открыть главное меню"
CMD_MENU = "Главное меню"
CMD_CANCEL = "Прервать текущее действие"

# --- Main menu ------------------------------------------------------------------------------

MAIN_MENU = "Выберите действие:"
PANEL_GREETING = "Здравствуйте! Кнопки разделов всегда под рукой — на панели внизу экрана."

BTN_LEND = "Выдал в долг"
BTN_REPAY_IN = "Мне вернули"
BTN_BORROW = "Взял в долг"
BTN_REPAY_OUT = "Я вернул"
BTN_CLIENTS = "Клиенты"
BTN_CASH = "Касса"
BTN_REPORTS = "Отчёты"
BTN_SETTINGS = "Настройки"

# --- Common buttons and answers -------------------------------------------------------------

BTN_BACK = "‹ Назад"
BTN_HOME = "В меню"
BTN_PREV_PAGE = "‹"
BTN_NEXT_PAGE = "›"

STALE_ACTION = "Это действие устарело"
ACTION_CANCELLED = "Действие отменено."
PERMISSION_DENIED = "Недостаточно прав для этого действия."
UNEXPECTED_INPUT = "Не понял сообщение. Воспользуйтесь кнопками выше или нажмите /menu."
UNEXPECTED_ERROR = "Произошла ошибка. Попробуйте ещё раз или нажмите /menu."

# --- Access ---------------------------------------------------------------------------------

NO_ACCESS = "У вас нет доступа к этому боту."
NO_ACCESS_NO_USERNAME = (
    "Если владелец добавил вас, установите имя пользователя в настройках Telegram "
    "и снова нажмите /start."
)


def no_access(has_username: bool) -> str:
    if has_username:
        return NO_ACCESS
    return f"{NO_ACCESS}\n{NO_ACCESS_NO_USERNAME}"


# --- Users ----------------------------------------------------------------------------------

DELETED_SUFFIX = " (удалён)"


def user_name(user: User) -> str:
    """Name for "Автор: …" and reports: full name, else @username; deleted users are marked."""
    if user.full_name:
        name = user.full_name
    elif user.username:
        name = f"@{user.username}"
    else:
        name = f"ID {user.telegram_id}"
    if user.status == UserStatus.DELETED:
        name += DELETED_SUFFIX
    return name


def user_name_with_username(user: User) -> str:
    """ "Айгуль (@aigul_k)" for notifications."""
    if user.full_name and user.username:
        return f"{user.full_name} (@{user.username})"
    return user_name(user)


# --- Settings: helpers ----------------------------------------------------------------------

SETTINGS_TITLE = "<b>Настройки</b>"
BTN_HELPERS = "Помощники"
BTN_ADD = "Добавить"
BTN_DELETE = "Удалить"
BTN_CONFIRM_DELETE = "Да, удалить"

HELPERS_TITLE = "<b>Помощники</b>"
HELPERS_EMPTY = "Помощников пока нет. Нажмите «Добавить», чтобы пригласить человека."
ASK_HELPER_USERNAME = "Напишите никнейм помощника в Телеграме, например @aigul_k"
INVALID_USERNAME = (
    "Никнейм должен состоять из 5–32 латинских букв, цифр или знака _, например @aigul_k. "
    "Попробуйте ещё раз:"
)
USERNAME_ALREADY_ADDED = "Этот никнейм уже добавлен"
CANNOT_DELETE_OWNER = "Владельца удалить нельзя."

HELPER_STATUS = {
    UserStatus.ACTIVE: "активен",
    UserStatus.PENDING: "ожидает входа",
    UserStatus.DELETED: "удалён",
}


def helper_added(username: str) -> str:
    return f"Помощник @{esc(username)} добавлен. Попросите его открыть бота и нажать «Старт»."


def helper_button(helper: User) -> str:
    return f"{user_name_with_username(helper)} · {HELPER_STATUS[helper.status]}"


def helper_card(helper: User, added_on: date) -> str:
    return "\n".join(
        [
            "<b>Помощник</b>",
            f"Имя: {esc(helper.full_name or '—')}",
            f"Никнейм: @{esc(helper.username)}",
            f"Статус: {HELPER_STATUS[helper.status]}",
            f"Добавлен: {format_date(added_on)}",
        ]
    )


def confirm_delete_helper(helper: User) -> str:
    return (
        f"Удалить помощника @{esc(helper.username)}? Доступ пропадёт сразу, его записи сохранятся."
    )


def helper_deleted(helper: User) -> str:
    return f"Помощник @{esc(helper.username)} удалён."


def helper_activated_notice(helper: User) -> str:
    return f"Новый помощник в боте: {esc(user_name_with_username(helper))}."


# --- Balances (TZ 7.2) ----------------------------------------------------------------------


def balance_line(name: str, balance: Decimal, currency: Currency) -> str:
    """ "Азамат должен вам: 1 000 USD" / "Бекзат: вы должны 50 000 RUB" / "…: долга в USD нет"."""
    if balance > 0:
        return f"{esc(name)} должен вам: {format_money(balance, currency)}"
    if balance < 0:
        return f"{esc(name)}: вы должны {format_money(-balance, currency)}"
    return f"{esc(name)}: долга в {currency} нет"


def debt_phrase(balance: Decimal) -> str:
    """For the client card: "должен вам 700" / "вы должны 20 000"."""
    if balance > 0:
        return f"должен вам {format_amount(balance)}"
    return f"вы должны {format_amount(-balance)}"


# --- Clients (TZ 10, 12.6) ------------------------------------------------------------------

CLIENTS_TITLE = "<b>Клиенты</b>"
CLIENTS_EMPTY = "Клиентов пока нет. Нажмите «Добавить», чтобы создать первого."
NO_DEBTS = "Долгов нет"

BTN_FIND = "Найти"
BTN_NEW_CLIENT = "Новый клиент"
BTN_HISTORY = "История записей"
BTN_STATEMENT = "Выписка за период"
BTN_EDIT = "Изменить"
BTN_EDIT_NAME = "Имя"
BTN_EDIT_COMMENT = "Комментарий"
BTN_CLEAR_COMMENT = "Удалить комментарий"
BTN_SKIP = "Пропустить"
BTN_ALL_CLIENTS = "‹ Все клиенты"
BTN_OPEN_CLIENT = "Открыть клиента"

ASK_SEARCH = "Введите часть имени клиента:"
ASK_CLIENT_NAME = "Введите имя клиента:"
ASK_CLIENT_COMMENT = (
    "Добавьте комментарий к клиенту (телефон, город, чей знакомый) или нажмите «Пропустить»:"
)
CLIENT_NAME_EMPTY = "Имя не может быть пустым. Введите имя клиента:"
CLIENT_NAME_TOO_LONG = "Имя слишком длинное, нужно не больше 100 символов. Введите имя короче:"
CLIENT_HAS_OPERATIONS = "У клиента есть записи, поэтому удалить его нельзя."
CLIENT_NOT_FOUND = "Клиент не найден: возможно, его уже удалили."
COMMENT_SAVED = "Комментарий сохранён."
COMMENT_REMOVED = "Комментарий удалён."


def comment_too_long(limit: int) -> str:
    return f"Комментарий слишком длинный, нужно не больше {limit} символов. Сократите его:"


def duplicate_client(name: str) -> str:
    name = esc(name)
    return (
        f"Клиент «{name}» уже есть. Добавьте уточнение, например «{name} (Ош)» или «{name} Петров»."
    )


def search_results(query: str, total: int) -> str:
    if total == 0:
        return f"По запросу «{esc(query)}» никого не нашлось. Введите другую часть имени:"
    return (
        f"Найдено по запросу «{esc(query)}»: {total}. Выберите клиента или введите другой запрос:"
    )


def client_added(name: str) -> str:
    return f"Клиент «{esc(name)}» добавлен."


def client_card(client: Client, balances: dict[Currency, Decimal]) -> str:
    lines = [f"<b>{esc(client.name)}</b>"]
    if client.comment:
        lines.append(f"Комментарий: {esc(client.comment)}")
    lines.append("")
    debts = [(currency, balance) for currency, balance in balances.items() if balance != 0]
    if debts:
        lines.append("<b>Долги:</b>")
        lines.extend(f"{currency}: {debt_phrase(balance)}" for currency, balance in debts)
    else:
        lines.append(NO_DEBTS)
    return "\n".join(lines)


def edit_client(name: str) -> str:
    return f"Что изменить у клиента «{esc(name)}»?"


def ask_new_name(name: str) -> str:
    return f"Введите новое имя для клиента «{esc(name)}»:"


def ask_new_comment(current: str | None) -> str:
    text = "Введите новый комментарий:"
    if current:
        text += f"\n\nСейчас: {esc(current)}"
    return text


def client_renamed(name: str) -> str:
    return f"Имя клиента изменено: «{esc(name)}»."


def confirm_delete_client(name: str) -> str:
    return f"Удалить клиента «{esc(name)}»?"


def client_deleted(name: str) -> str:
    return f"Клиент «{esc(name)}» удалён."


# --- Rates (TZ 4.5) -------------------------------------------------------------------------


def rate_question(base: Currency, quote: Currency) -> str:
    """ "Сколько сомов за 1 USD?" / "Сколько RUB за 1 EUR?"."""
    quote_name = "сомов" if quote == HOME_CURRENCY else quote
    return f"Сколько {quote_name} за 1 {base}?"


def rate_text(rate: Decimal, base: Currency, quote: Currency) -> str:
    """ "1 USD = 87,5 KGS"."""
    return f"1 {base} = {format_rate(rate)} {quote}"


# --- Records: common (TZ 7, 12.2-12.4) ------------------------------------------------------

TYPE_LABEL = {
    OperationType.LEND: "Выдал в долг",
    OperationType.REPAY_IN: "Мне вернули",
    OperationType.BORROW: "Взял в долг",
    OperationType.REPAY_OUT: "Я вернул",
}

CLIENT_QUESTION = {
    OperationType.LEND: "Кому выдаёте в долг?",
    OperationType.REPAY_IN: "Кто вернул долг?",
    OperationType.BORROW: "У кого берёте в долг?",
    OperationType.REPAY_OUT: "Кому возвращаете долг?",
}

CHOOSE_CLIENT_HINT = "Выберите клиента из недавних или напишите часть имени для поиска."
NO_CLIENTS_YET = "Клиентов пока нет. Нажмите «Новый клиент»."
ASK_NEW_CLIENT_NAME = "Введите имя нового клиента:"
ASK_CURRENCY = "В какой валюте?"
ASK_DEBT_CURRENCY = "Какой долг закрывается?"
ASK_PAY_CURRENCY = "В какой валюте оплата?"
BTN_SAME_CURRENCY = "В этой же валюте"
BTN_OTHER_CURRENCY = "В другой валюте"
BTN_SAVE = "Сохранить"
BTN_DONT_SAVE = "Не сохранять"
BTN_OPEN_RECORD = "Открыть запись"

ASK_RECORD_COMMENT = "Добавьте комментарий к записи или нажмите «Пропустить»:"
RECORD_NOT_SAVED = "Запись не сохранена."

PAY_MODE_QUESTION = {
    OperationType.REPAY_IN: "В какой валюте вам вернули деньги?",
    OperationType.REPAY_OUT: "В какой валюте вы отдаёте деньги?",
}

AMOUNT_ERRORS = {
    NumberProblem.FORMAT: (
        "Не получилось прочитать сумму. Введите число, например 1000, 1 000 или 1 000,50:"
    ),
    NumberProblem.PRECISION: (
        "После запятой можно указать не больше двух знаков, например 1 000,50. "
        "Введите сумму ещё раз:"
    ),
    NumberProblem.NOT_POSITIVE: "Сумма должна быть больше нуля. Введите сумму ещё раз:",
    NumberProblem.TOO_LARGE: (
        "Сумма слишком большая: не больше 999 999 999 999,99. Введите сумму ещё раз:"
    ),
}

RATE_ERRORS = {
    NumberProblem.FORMAT: "Не получилось прочитать курс. Введите число, например 87,5:",
    NumberProblem.PRECISION: (
        "У курса можно указать не больше шести знаков после запятой. Введите курс ещё раз:"
    ),
    NumberProblem.NOT_POSITIVE: "Курс должен быть больше нуля. Введите курс ещё раз:",
    NumberProblem.TOO_LARGE: "Курс слишком большой. Введите курс ещё раз:",
}

CONVERSION_ERRORS = {
    ConversionProblem.ZERO: (
        "С долга спишется 0 — проверьте сумму или курс. Введите курс ещё раз или вернитесь к сумме:"
    ),
    ConversionProblem.TOO_LARGE: (
        "С долга спишется слишком большая сумма — проверьте сумму или курс. Введите курс ещё раз:"
    ),
}


def record_header(op_type: OperationType, client_name: str) -> str:
    """ "Выдал в долг: Азамат"."""
    return f"{TYPE_LABEL[op_type]}: {esc(client_name)}"


def client_step(op_type: OperationType, has_clients: bool) -> str:
    hint = CHOOSE_CLIENT_HINT if has_clients else NO_CLIENTS_YET
    return f"<b>{CLIENT_QUESTION[op_type]}</b>\n{hint}"


def currency_step(op_type: OperationType, client_name: str) -> str:
    return f"{record_header(op_type, client_name)}\n\n{ASK_CURRENCY}"


def debts_block(balances: dict[Currency, Decimal]) -> str:
    debts = [(currency, balance) for currency, balance in balances.items() if balance != 0]
    if not debts:
        return NO_DEBTS
    lines = ["<b>Долги:</b>"]
    lines.extend(f"{currency}: {debt_phrase(balance)}" for currency, balance in debts)
    return "\n".join(lines)


def debt_currency_step(
    op_type: OperationType, client_name: str, balances: dict[Currency, Decimal]
) -> str:
    return "\n\n".join(
        [record_header(op_type, client_name), debts_block(balances), ASK_DEBT_CURRENCY]
    )


def debt_currency_button(currency: Currency, balance: Decimal) -> str:
    """ "USD · должен 600" / "RUB · вы должны 30 000" / "KGS" (TZ 12.4)."""
    if balance > 0:
        return f"{currency} · должен {format_amount(balance)}"
    if balance < 0:
        return f"{currency} · вы должны {format_amount(-balance)}"
    return str(currency)


def pay_mode_step(op_type: OperationType, client_name: str, debt_currency: Currency) -> str:
    return (
        f"{record_header(op_type, client_name)}\nДолг в {debt_currency}.\n\n"
        f"{PAY_MODE_QUESTION[op_type]}"
    )


def amount_step(
    op_type: OperationType,
    client_name: str,
    currency: Currency,
    debt_currency: Currency,
    available: Decimal | None,
    problem: str | None = None,
) -> str:
    """Amount prompt; `problem` (wrong input, not enough cash) replaces the question."""
    lines = [record_header(op_type, client_name)]
    if currency != debt_currency:
        lines.append(f"Долг в {debt_currency}, оплата в {currency}.")
    if problem is not None:
        return "\n".join([*lines, "", problem])
    if available is not None:
        lines.append(f"В кассе: {format_money(available, currency)}")
    lines += ["", f"Введите сумму в {currency}:"]
    return "\n".join(lines)


def insufficient_cash(error: InsufficientCash) -> str:
    """TZ 7.4, without the last line."""
    return (
        "<b>Недостаточно денег в кассе.</b>\n"
        f"В кассе: {format_money(error.available, error.currency)}\n"
        f"Нужно: {format_money(error.required, error.currency)}"
    )


def insufficient_cash_plain(error: InsufficientCash) -> str:
    """For popups, which show text without HTML."""
    return (
        "Недостаточно денег в кассе.\n"
        f"В кассе: {format_money(error.available, error.currency)}\n"
        f"Нужно: {format_money(error.required, error.currency)}"
    )


def insufficient_cash_retry(error: InsufficientCash) -> str:
    return f"{insufficient_cash(error)}\nВведите другую сумму:"


def insufficient_cash_not_saved(error: InsufficientCash) -> str:
    return f"{insufficient_cash(error)}\n{RECORD_NOT_SAVED}"


def warning_text(warning: RepayWarning, currency: Currency) -> str:
    """TZ 7.5."""
    excess = format_money(warning.excess, currency) if warning.excess is not None else ""
    match warning.kind:
        case WarningKind.NOTHING_OWED_TO_YOU:
            return (
                f"Внимание: клиент ничего не должен вам в {currency}. "
                "Вся сумма станет вашим долгом перед ним."
            )
        case WarningKind.OVERPAID_TO_YOU:
            return (
                f"Внимание: сумма больше долга. Лишние {excess} станут вашим долгом перед клиентом."
            )
        case WarningKind.NOTHING_YOU_OWE:
            return (
                f"Внимание: вы ничего не должны клиенту в {currency}. "
                "Вся сумма станет долгом клиента перед вами."
            )
        case WarningKind.OVERPAID_BY_YOU:
            return (
                "Внимание: сумма больше вашего долга. "
                f"Лишние {excess} станут долгом клиента перед вами."
            )


def amount_lines(
    op_type: OperationType,
    debt_amount: Decimal,
    debt_currency: Currency,
    cash_amount: Decimal,
    cash_currency: Currency,
    rate: Decimal | None,
    rate_base: Currency | None,
    rate_quote: Currency | None,
) -> list[str]:
    """ "Сумма: …" or, for a payment in another currency, "Получено / Курс / Закрывает долг"."""
    if cash_currency == debt_currency:
        return [f"Сумма: {format_money(cash_amount, cash_currency)}"]
    assert rate is not None and rate_base is not None and rate_quote is not None
    if op_type == OperationType.REPAY_OUT:
        paid_label, covers_label = "Отдано", "Закрывает ваш долг"
    else:
        paid_label, covers_label = "Получено", "Закрывает долг"
    return [
        f"{paid_label}: {format_money(cash_amount, cash_currency)}",
        f"Курс: {rate_text(rate, rate_base, rate_quote)}",
        f"{covers_label}: {format_money(debt_amount, debt_currency)}",
    ]


def confirm_record(
    op_type: OperationType,
    client_name: str,
    amounts: list[str],
    op_date: date,
    comment: str | None,
    balance_before: Decimal,
    balance_after: Decimal,
    debt_currency: Currency,
    cash_after: Decimal,
    cash_currency: Currency,
    warning: RepayWarning | None,
) -> str:
    lines = ["<b>Проверьте запись</b>", record_header(op_type, client_name), *amounts]
    lines.append(f"Дата: {format_date(op_date)}")
    if comment:
        lines.append(f"Комментарий: {esc(comment)}")
    lines += [
        "",
        # The debt the record starts from, so it is clear what a repayment closes.
        "<b>Сейчас:</b>",
        balance_line(client_name, balance_before, debt_currency),
        "",
        "<b>После сохранения:</b>",
        balance_line(client_name, balance_after, debt_currency),
        cash_line(cash_currency, cash_after),
    ]
    if warning is not None:
        lines += ["", f"<b>{warning_text(warning, debt_currency)}</b>"]
    return "\n".join(lines)


def record_saved(number: int) -> str:
    return f"Запись №{number} сохранена."


# --- Cash (TZ 12.7) -------------------------------------------------------------------------

CASH_TITLE = "<b>Касса</b>"
BTN_MOVEMENTS = "Движение денег"
BTN_ADJUST = "Корректировка"
BTN_CASH_BACK = "‹ Касса"
MOVEMENTS_TITLE = "<b>Движение денег</b>"
MOVEMENTS_EMPTY = "Записей пока нет."
BTN_ADD_MONEY = "Добавить"
BTN_REMOVE_MONEY = "Убрать"
ASK_ADJUST_CURRENCY = "<b>Корректировка кассы</b>\nВыберите валюту:"
ASK_ADJUST_REASON = "Напишите причину, например «Остаток на начало работы» или «Личные расходы»:"
REASON_EMPTY = "Причина обязательна. Напишите её:"
ADJUSTMENT_SAVED = "Корректировка сохранена."
BUTTON_TEXT_MAX = 40


def _short(text: str, limit: int = BUTTON_TEXT_MAX) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def cash_screen(balances: dict[Currency, Decimal]) -> str:
    lines = [CASH_TITLE]
    lines.extend(f"{currency}: {format_amount(value)}" for currency, value in balances.items())
    return "\n".join(lines)


def cash_line(currency: Currency, value: Decimal) -> str:
    """ "В кассе USD: 9 000"."""
    return f"В кассе {currency}: {format_amount(value)}"


def record_label(op_type: OperationType, reversal_of_id: int | None) -> str:
    return f"Отмена №{reversal_of_id}" if reversal_of_id is not None else TYPE_LABEL[op_type]


def movement_button(
    *,
    is_adjustment: bool,
    item_id: int,
    day: date,
    currency: Currency,
    amount: Decimal,
    op_type: OperationType | None,
    title: str,
    reversal_of_id: int | None,
    reversed_by_id: int | None,
) -> str:
    """ "№15 · 25.09 · Мне вернули · Тимур · +1 000 USD" / "Корр. · 27.09 · −500 USD · Причина"."""
    money = f"{format_signed(amount)} {currency}"
    if is_adjustment:
        return f"Корр. · {format_short_date(day)} · {money} · {_short(title, 24)}"
    assert op_type is not None
    text = (
        f"№{item_id} · {format_short_date(day)} · {record_label(op_type, reversal_of_id)}"
        f" · {_short(title, 20)} · {money}"
    )
    return f"{text} · отменена" if reversed_by_id is not None else text


def adjustment_popup(adjustment: CashAdjustment, zone: ZoneInfo) -> str:
    """Alert text (Telegram allows up to 200 characters)."""
    text = (
        f"Корректировка · {format_date(adjustment.adj_date)}\n"
        f"{format_signed(adjustment.amount)} {adjustment.currency}\n"
        f"Причина: {_short(adjustment.reason, 80)}\n"
        f"Внёс: {_short(user_name(adjustment.author), 30)} · "
        f"{format_datetime(adjustment.created_at, zone)}"
    )
    return text[:200]


def ask_adjust_direction(currency: Currency, available: Decimal) -> str:
    return (
        f"<b>Корректировка кассы {currency}</b>\nСейчас в кассе: "
        f"{format_money(available, currency)}\n\nДобавить деньги или убрать?"
    )


def ask_adjust_amount(currency: Currency, adding: bool) -> str:
    action = "добавить" if adding else "убрать"
    return f"<b>Корректировка кассы {currency}</b>\nСколько {action}? Введите сумму в {currency}:"


def adjust_amount_problem(currency: Currency, problem: str) -> str:
    return f"<b>Корректировка кассы {currency}</b>\n\n{problem}"


def confirm_adjustment(
    currency: Currency, amount: Decimal, reason: str, cash_after: Decimal
) -> str:
    return "\n".join(
        [
            "<b>Проверьте корректировку</b>",
            f"Касса: {currency}",
            f"Изменение: {format_signed(amount)} {currency}",
            f"Причина: {esc(reason)}",
            "",
            "<b>После сохранения:</b>",
            cash_line(currency, cash_after),
        ]
    )


def adjustment_saved(currency: Currency, cash_after: Decimal) -> str:
    return f"{ADJUSTMENT_SAVED}\n{cash_line(currency, cash_after)}"


# --- Record card and history (TZ 12.5, 12.6) ------------------------------------------------

BTN_CANCEL_RECORD = "Отменить запись"
BTN_CLIENT = "Клиент"
BTN_CONFIRM_CANCEL = "Да, отменить"
RECORD_NOT_FOUND = "Запись не найдена."
HISTORY_EMPTY = "Записей пока нет."
ASK_CANCEL_REASON = "Напишите причину отмены:"
ALREADY_REVERSED = "Эта запись уже отменена."
CANNOT_REVERSE_REVERSAL = "Отмену отменить нельзя. Если запись отменили зря, внесите её заново."
ONLY_AUTHOR_CAN_CANCEL = "Отменить запись может только тот, кто её внёс."


def history_title(client_name: str) -> str:
    return f"<b>История записей: {esc(client_name)}</b>"


def history_button(
    *,
    item_id: int,
    op_type: OperationType,
    op_date: date,
    debt_amount: Decimal,
    debt_currency: Currency,
    reversal_of_id: int | None,
    reversed_by_id: int | None,
) -> str:
    """ "№15 · 25.09 · Мне вернули · 1 000 USD" (+ " · отменена")."""
    text = (
        f"№{item_id} · {format_short_date(op_date)} · {record_label(op_type, reversal_of_id)}"
        f" · {format_money(debt_amount, debt_currency)}"
    )
    return f"{text} · отменена" if reversed_by_id is not None else text


def record_amount_lines(operation: Operation) -> list[str]:
    return amount_lines(
        operation.type,
        operation.debt_amount,
        operation.debt_currency,
        operation.cash_amount,
        operation.cash_currency,
        operation.rate,
        operation.rate_base,
        operation.rate_quote,
    )


def record_card(operation: Operation, reversal: Operation | None, zone: ZoneInfo) -> str:
    """TZ 12.5. `operation.client` and `operation.author` must be loaded."""
    if operation.reversal_of_id is not None:
        title = f"<b>Запись №{operation.id} · Отмена записи №{operation.reversal_of_id}</b>"
    else:
        title = f"<b>Запись №{operation.id} · {TYPE_LABEL[operation.type]}</b>"
    lines = [title, f"Клиент: {esc(operation.client.name)}", *record_amount_lines(operation)]
    lines.append(f"Дата: {format_date(operation.op_date)}")
    if operation.comment:
        lines.append(f"Комментарий: {esc(operation.comment)}")
    lines.append(
        f"Автор: {esc(user_name(operation.author))} · "
        f"внесено {format_datetime(operation.created_at, zone)}"
    )
    if operation.reversal_reason is not None:
        lines.append(f"Причина: {esc(operation.reversal_reason)}")
    if reversal is not None:
        lines.append(
            f"Статус: отменена записью №{reversal.id} (причина: {esc(reversal.reversal_reason)})"
        )
    return "\n".join(lines)


def confirm_cancel(
    operation: Operation, reason: str, balance_after: Decimal, cash_after: Decimal
) -> str:
    """TZ 8.3."""
    return "\n".join(
        [
            f"<b>Отменить запись №{operation.id}?</b>",
            record_header(operation.type, operation.client.name),
            *record_amount_lines(operation),
            f"Причина: {esc(reason)}",
            "",
            "<b>После отмены:</b>",
            balance_line(operation.client.name, balance_after, operation.debt_currency),
            cash_line(operation.cash_currency, cash_after),
        ]
    )


def record_cancelled(number: int, client_name: str, balance: Decimal, currency: Currency) -> str:
    return f"Запись №{number} отменена.\n{balance_line(client_name, balance, currency)}"


def record_summary(operation: Operation) -> str:
    """ "Мне вернули · Тимур · 1 000 USD" (with the payment for another currency)."""
    money = format_money(operation.debt_amount, operation.debt_currency)
    if operation.cash_currency != operation.debt_currency:
        money = f"{format_money(operation.cash_amount, operation.cash_currency)} → {money}"
    return f"{TYPE_LABEL[operation.type]} · {esc(operation.client.name)} · {money}"


def helper_cancelled_notice(helper: User, operation: Operation, reason: str) -> str:
    """TZ 12.10."""
    return "\n".join(
        [
            "<b>Помощник отменил запись</b>",
            f"Кто: {esc(user_name_with_username(helper))}",
            f"Запись №{operation.id}: {record_summary(operation)}",
            f"Причина: {esc(reason)}",
        ]
    )


# --- Group chat (GROUP_CHAT_ID; customer's request of 28.09.2026) ---------------------------


def _made_by(author: User, created_at: datetime, zone: ZoneInfo) -> str:
    return (
        f"Автор: {esc(user_name_with_username(author))} · "
        f"внесено {format_datetime(created_at, zone)}"
    )


def group_record_notice(
    operation: Operation, balance: Decimal, cash_after: Decimal, zone: ZoneInfo
) -> str:
    """A new record or a reversal. `operation.client` and `operation.author` must be loaded."""
    if operation.reversal_of_id is not None:
        lines = [
            f"<b>Новая запись №{operation.id} · Отмена записи №{operation.reversal_of_id}</b>",
            record_summary(operation),
            f"Причина: {esc(operation.reversal_reason)}",
        ]
        after = "<b>После отмены:</b>"
    else:
        lines = [
            f"<b>Новая запись №{operation.id} · {TYPE_LABEL[operation.type]}</b>",
            f"Клиент: {esc(operation.client.name)}",
            *record_amount_lines(operation),
        ]
        if operation.comment:
            lines.append(f"Комментарий: {esc(operation.comment)}")
        after = "<b>После записи:</b>"
    lines += [
        _made_by(operation.author, operation.created_at, zone),
        "",
        after,
        balance_line(operation.client.name, balance, operation.debt_currency),
        cash_line(operation.cash_currency, cash_after),
    ]
    return "\n".join(lines)


def group_adjustment_notice(adjustment: CashAdjustment, cash_after: Decimal, zone: ZoneInfo) -> str:
    """`adjustment.author` must be loaded."""
    return "\n".join(
        [
            f"<b>Корректировка кассы {adjustment.currency}</b>",
            f"Изменение: {format_signed(adjustment.amount)} {adjustment.currency}",
            f"Причина: {esc(adjustment.reason)}",
            _made_by(adjustment.author, adjustment.created_at, zone),
            "",
            "<b>После корректировки:</b>",
            cash_line(adjustment.currency, cash_after),
        ]
    )


def bot_added_to_group(title: str | None, chat_id: int, connected: bool) -> str:
    """To the owner, who has just added the bot to a group."""
    name = f"«{esc(title)}»" if title else str(chat_id)
    if connected:
        return f"Бот добавлен в группу {name}. Уведомления о записях будут приходить туда."
    return (
        f"Бот добавлен в группу {name}. Чтобы он публиковал туда уведомления о записях, "
        f"укажите в файле .env строку\n<code>GROUP_CHAT_ID={chat_id}</code>\n"
        "и перезапустите бота."
    )


# --- Reports (TZ 12.8, 13) ------------------------------------------------------------------

REPORTS_TITLE = "Какой отчёт нужен?"
BTN_REPORT_SUMMARY = "Общая сводка"
BTN_REPORT_DEBTS = "Кто кому должен"
BTN_REPORT_RECORDS = "Все записи за период"
BTN_REPORT_CASH = "Движение кассы"
BTN_REPORT_STATEMENT = "Выписка по клиенту"
BTN_PERIOD_TODAY = "Сегодня"
BTN_PERIOD_WEEK = "Неделя"
BTN_PERIOD_MONTH = "Месяц"
BTN_PERIOD_YEAR = "Год"
BTN_ALL_TIME = "Всё время"
BTN_EXCEL = "Excel"
BTN_PDF = "PDF"

ASK_FORMAT = "В каком виде прислать?"
ASK_PERIOD = "За какой период?"
RATES_INTRO = "Укажите курсы для пересчёта кассы в сомы."
STATEMENT_CLIENT_QUESTION = "По какому клиенту нужна выписка?"
STATEMENT_NO_CLIENTS = "Клиентов пока нет."

REPORT_TITLES = {
    "summary": "Общая сводка",
    "debts": "Кто кому должен",
    "records": "Все записи за период",
    "cash": "Движение кассы",
    "statement": "Выписка по клиенту",
}

REPORT_FILE_PREFIXES = {
    "summary": "Общая_сводка",
    "debts": "Кто_кому_должен",
    "records": "Все_записи",
    "cash": "Движение_кассы",
    "statement": "Выписка",
}


def ask_rate_for_summary(currency: Currency) -> str:
    return f"{RATES_INTRO}\n<b>{rate_question(currency, HOME_CURRENCY)}</b>"


def report_step(title: str, question: str) -> str:
    return f"<b>{esc(title)}</b>\n{question}"


# --- Report files (TZ 13) -------------------------------------------------------------------

REPORT_ALL_TIME = "всё время"
REPORT_FILE_ALL_TIME = "всё_время"
REPORT_FILE_OPEN_START = "начало"
REPORT_FILE_OPEN_END = "сегодня"
REPORT_FILE_CLIENT_FALLBACK = "клиент"

REPORT_TOTAL = "Итого"
REPORT_TOTAL_BY_CURRENCY = "Итого по валюте"
REPORT_OWED_TO_YOU = "Вам должны"
REPORT_YOU_OWE = "Вы должны"
REPORT_NO_DEBTS = "Долгов нет"
REPORT_NO_RECORDS = "Записей нет"
REPORT_NO_RECORDS_IN_PERIOD = "Записей за период нет"
REPORT_NO_MOVEMENTS = "Движений нет"
REPORT_OPENING = "Остаток на начало"
REPORT_CLOSING = "Остаток на конец"
REPORT_ADJUSTMENT_NUMBER = "корр."
REPORT_NO_DEBT_PHRASE = "долга нет"

SUMMARY_SHEET_BY_CURRENCY = "Касса и долги"
SUMMARY_SHEET_IN_KGS = "Касса в сомах"
SUMMARY_TITLE_BY_CURRENCY = "Касса и долги по валютам"
SUMMARY_TITLE_IN_KGS = "Касса в пересчёте на сомы"
SUMMARY_COLUMNS = ("Валюта", "В кассе", "Вам должны", "Вы должны", "Разница")
SUMMARY_KGS_COLUMNS = ("Валюта", "Остаток в кассе", "Курс, сомов за 1", "В сомах")

DEBTS_COLUMNS = ("Валюта", "Клиент", "Сумма")

RECORDS_SHEET = "Записи"
RECORDS_PDF_COLUMNS = (
    "№",
    "Дата",
    "Операция",
    "Клиент",
    "Сумма долга",
    "Оплата",
    "Курс",
    "Комментарий",
    "Автор",
    "Внесено",
    "Статус",
)
RECORDS_XLSX_COLUMNS = (
    "№",
    "Дата",
    "Операция",
    "Клиент",
    "Сумма долга",
    "Валюта долга",
    "Оплата",
    "Валюта оплаты",
    "Курс",
    "Комментарий",
    "Автор",
    "Внесено",
    "Статус",
)

CASH_REPORT_SHEET = "Движение кассы"
CASH_REPORT_COLUMNS = ("Дата", "№", "Описание", "Приход", "Расход", "Остаток")

STATEMENT_SHEET = "Выписка"
STATEMENT_COLUMNS = ("Дата", "№", "Операция", "Изменение долга", "Оплата", "Баланс после")


def report_period_line(label: str) -> str:
    return f"Период: {label}"


def report_generated_line(moment: datetime) -> str:
    return f"Сформирован: {moment:%d.%m.%Y %H:%M}"


def report_author_line(name: str) -> str:
    return f"Сформировал: {name}"


def report_client_line(name: str) -> str:
    return f"Клиент: {name}"


def report_currency_line(currency: Currency) -> str:
    return f"Валюта: {currency}"


def report_page(number: int, total: int) -> str:
    return f"Страница {number} из {total}"


def debts_pdf_columns(currency: Currency) -> tuple[str, str]:
    return "Клиент", f"Сумма, {currency}"


def report_money_line(label: str, amount: str) -> str:
    """ "Остаток на начало: 9 000 USD"."""
    return f"{label}: {amount}"


def reversal_label(original_number: int) -> str:
    return f"Отмена записи №{original_number}"


def status_cancelled_by(reversal_number: int) -> str:
    return f"отменена записью №{reversal_number}"


def status_reversal_of(original_number: int, reason: str | None) -> str:
    return f"отмена записи №{original_number} ({reason})"


def movement_description(label: str, detail: str) -> str:
    """ "Выдал в долг — Азамат" / "Корректировка — Личные расходы"."""
    return f"{label} — {detail}"


ADJUSTMENT_LABEL = "Корректировка"


def statement_payment(paid: str, rate: str) -> str:
    return f"{paid}, курс {rate}"


def balance_phrase(balance: Decimal, currency: Currency) -> str:
    """ "должен вам 600 USD" / "вы должны 3 000 RUB" / "долга нет"."""
    if balance == 0:
        return REPORT_NO_DEBT_PHRASE
    if balance > 0:
        return f"должен вам {format_money(balance, currency)}"
    return f"вы должны {format_money(-balance, currency)}"


# --- Record scenario details ------------------------------------------------------------------


def debt_in(currency: Currency) -> str:
    return f"Долг в {currency}."


def payment_context(paid: str, debt_currency: Currency) -> str:
    return f"Оплата: {paid}, долг в {debt_currency}."
