"""Every text the user sees lives here (TZ 0.4).

Plain constants are ready-to-send strings; functions build texts with values.
Anything that comes from users (names, comments, reasons) must go through `esc()`.
"""

from datetime import date
from decimal import Decimal
from html import escape

from app.db.models import Client, User, UserStatus
from app.domain.currency import HOME_CURRENCY, Currency
from app.domain.dates import format_date
from app.domain.errors import ConversionProblem, InsufficientCash, NumberProblem
from app.domain.money import format_amount, format_money, format_rate
from app.domain.operations import OperationType, RepayWarning, WarningKind


def esc(value: object) -> str:
    return escape(str(value), quote=False)


# --- Commands -------------------------------------------------------------------------------

CMD_START = "Открыть главное меню"
CMD_MENU = "Главное меню"
CMD_CANCEL = "Прервать текущее действие"

# --- Main menu ------------------------------------------------------------------------------

MAIN_MENU = "Выберите действие:"

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
NOT_IMPLEMENTED = "Раздел пока в разработке."
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
BTN_TODAY = "Сегодня"
BTN_YESTERDAY = "Вчера"
BTN_OTHER_DATE = "Другая дата"
BTN_SAVE = "Сохранить"
BTN_DONT_SAVE = "Не сохранять"
BTN_OPEN_RECORD = "Открыть запись"

ASK_CUSTOM_DATE = "Введите дату в формате ДД.ММ.ГГГГ или ДД.ММ (тогда год текущий):"
INVALID_DATE = "Не получилось распознать дату. Введите её как ДД.ММ.ГГГГ, например 25.09.2026:"
FUTURE_DATE = "Дата не может быть в будущем. Введите другую дату:"
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


def insufficient_cash_retry(error: InsufficientCash) -> str:
    return f"{insufficient_cash(error)}\nВведите другую сумму:"


def insufficient_cash_not_saved(error: InsufficientCash) -> str:
    return f"{insufficient_cash(error)}\n{RECORD_NOT_SAVED}"


def date_step(header: str) -> str:
    return f"{header}\n\nДата записи?"


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
        "<b>После сохранения:</b>",
        balance_line(client_name, balance_after, debt_currency),
        f"В кассе {cash_currency}: {format_amount(cash_after)}",
    ]
    if warning is not None:
        lines += ["", f"<b>{warning_text(warning, debt_currency)}</b>"]
    return "\n".join(lines)


def record_saved(number: int) -> str:
    return f"Запись №{number} сохранена."
