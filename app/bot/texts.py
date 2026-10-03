"""Every text the user sees lives here (TZ 0.5).

Plain constants are ready-to-send strings; functions build texts with values.
Anything that comes from users (names, comments, reasons) must go through `esc()`.
"""

from datetime import date, datetime
from decimal import Decimal
from html import escape
from zoneinfo import ZoneInfo

from app.db.models import Client, Operation, User, UserStatus
from app.domain.currency import HOME_CURRENCY, Currency
from app.domain.dates import format_date, format_datetime, format_short_date
from app.domain.day_report import DayReport
from app.domain.entries import Book, OperationType
from app.domain.errors import ConversionProblem, InsufficientBalance, NumberProblem
from app.domain.money import format_amount, format_money, format_rate, format_signed
from app.domain.warnings import RecordWarning, WarningKind


def esc(value: object) -> str:
    return escape(str(value), quote=False)


# --- Commands -------------------------------------------------------------------------------

CMD_START = "Открыть главное меню"
CMD_MENU = "Главное меню"
CMD_CANCEL = "Прервать текущее действие"

# --- Main menu (TZ 13.2) --------------------------------------------------------------------

PANEL_GREETING = "Здравствуйте! Кнопки разделов всегда под рукой — на панели внизу экрана."
SECTION_SOON = "Этот раздел появится в следующем обновлении бота."

BTN_EXCHANGE = "Обмен"
BTN_TO_PAY = "Ждут выдачи"
BTN_TO_RECEIVE = "Ждут оплаты"
BTN_LOANS = "Долги в сомах"
BTN_CLIENTS = "Клиенты"
BTN_BALANCES = "Балансы"
BTN_REPORTS = "Отчёты"
BTN_CLOSE_DAY = "Закрыть день"
BTN_SETTINGS = "Настройки"


def main_menu(day_number: int) -> str:
    return f"День №{day_number}. Выберите действие:"


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


def step_text(title: str, lines: list[str], question: str, problem: str | None = None) -> str:
    """A scenario step: what is known so far, the problem with the last input, the question."""
    parts = ["\n".join([title, *lines])]
    if problem:
        parts.append(problem)
    parts.append(f"<b>{question}</b>")
    return "\n\n".join(parts)


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


# --- Clients (TZ 13.6) -------------------------------------------------------------------------

CLIENTS_TITLE = "<b>Клиенты</b>"
CLIENTS_EMPTY = "Клиентов пока нет. Нажмите «Добавить», чтобы создать первого."

BTN_FIND = "Найти"
BTN_NEW_CLIENT = "Новый клиент"
BTN_EDIT = "Изменить"
BTN_EDIT_NAME = "Имя"
BTN_EDIT_COMMENT = "Комментарий"
BTN_CLEAR_COMMENT = "Удалить комментарий"
BTN_SKIP = "Пропустить"
BTN_ALL_CLIENTS = "‹ Все клиенты"
BTN_OPEN_CLIENT = "Открыть клиента"
BTN_HISTORY = "История записей"
BTN_STATEMENT = "Выписка"
NO_OBLIGATIONS = "Обязательств нет"

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


def client_line(name: str) -> str:
    return f"Клиент: {esc(name)}"


def client_added(name: str) -> str:
    return f"Клиент «{esc(name)}» добавлен."


def client_card(client: Client, obligations: dict[tuple[Book, Currency], Decimal]) -> str:
    """TZ 13.6: zero lines are not shown; with nothing at all, «Обязательств нет»."""
    head = [f"<b>{esc(client.name)}</b>"]
    if client.comment:
        head.append(f"Комментарий: {esc(client.comment)}")
    blocks = ["\n".join(head)]
    exchange = [
        f"{currency}: {owe_text(amount)}"
        for (book, currency), amount in obligations.items()
        if book == Book.EXCHANGE and amount != 0
    ]
    if exchange:
        blocks.append("\n".join(["По обменам:", *exchange]))
    loan = obligations.get((Book.LOAN, HOME_CURRENCY), Decimal(0))
    if loan != 0:
        blocks.append(f"Долг в сомах: {owe_text(loan)}")
    if len(blocks) == 1:
        blocks.append(NO_OBLIGATIONS)
    return "\n\n".join(blocks)


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


# --- Numbers (TZ 4.2, 4.3) -------------------------------------------------------------------

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
        "По этому курсу вторая сумма получается равной нулю. Проверьте сумму или курс "
        "и введите курс ещё раз:"
    ),
    ConversionProblem.TOO_LARGE: (
        "По этому курсу вторая сумма получается слишком большой. Проверьте сумму или курс "
        "и введите курс ещё раз:"
    ),
}

# --- Balances and obligations (TZ 6, 13.1, 13.7) -----------------------------------------------

CASH_NAME = "Наличка"
BTN_DAY_RECORDS = "Записи дня"
BTN_ADJUST = "Корректировка"
RECORD_NOT_SAVED = "Запись не сохранена."


def balance_name(currency: Currency) -> str:
    """ "Баланс USD" / "Наличка" (TZ 3: the som cash)."""
    return CASH_NAME if currency == HOME_CURRENCY else f"Баланс {currency}"


def balance_line(currency: Currency, value: Decimal) -> str:
    """ "Баланс RUB: 88 500" / "Наличка: 913 000 KGS"."""
    if currency == HOME_CURRENCY:
        return f"{CASH_NAME}: {format_money(value, currency)}"
    return f"{balance_name(currency)}: {format_amount(value)}"


def balances_screen(day_number: int, balances: dict[Currency, Decimal]) -> str:
    lines = [f"<b>Балансы · день №{day_number}</b>"]
    for currency, value in balances.items():
        if currency == HOME_CURRENCY:
            lines.append(f"{CASH_NAME}: {format_money(value, currency)}")
        else:
            lines.append(f"{currency}: {format_amount(value)}")
    return "\n".join(lines)


def owe_text(amount: Decimal) -> str:
    """ "должен нам 5 000" / "мы должны 1 000": the sign of an obligation in words."""
    if amount > 0:
        return f"должен нам {format_amount(amount)}"
    return f"мы должны {format_amount(-amount)}"


def obligation_line(name: str, book: Book, currency: Currency, amount: Decimal) -> str:
    """Names are never declined (TZ 13.1): "Азамат: мы должны 1 000 USD"."""
    suffix = " (долг в сомах)" if book == Book.LOAN else ""
    if amount > 0:
        return f"{esc(name)}: должен нам {format_money(amount, currency)}{suffix}"
    if amount < 0:
        return f"{esc(name)}: мы должны {format_money(-amount, currency)}{suffix}"
    if book == Book.LOAN:
        return f"{esc(name)}: долга в сомах нет"
    return f"{esc(name)}: обязательств в {currency} нет"


def insufficient_balance(error: InsufficientBalance) -> str:
    """TZ 6.5: "Недостаточно денег. / Баланс USD: 10 000 / Нужно: 20 000"."""
    return (
        "Недостаточно денег.\n"
        f"{balance_name(error.currency)}: {format_amount(error.available)}\n"
        f"Нужно: {format_amount(error.required)}"
    )


def insufficient_balance_not_saved(error: InsufficientBalance) -> str:
    return f"{insufficient_balance(error)}\n{RECORD_NOT_SAVED}"


def record_saved(number: int) -> str:
    return f"Запись №{number} сохранена."


# --- Opening balances (TZ 9, 13.11) ------------------------------------------------------------

BTN_OPENING = "Начальные балансы"
BTN_ENTER = "Внести"
BTN_SAVE = "Сохранить"
BTN_DONT_SAVE = "Не сохранять"
OPENING_TITLE = "<b>Начальные балансы</b>"
OPENING_ENTER_HINT = "Внесите деньги, которые есть на начало работы, по каждой валюте."
OPENING_FIX_HINT = (
    "Пока не закрыт первый день, ошибку можно исправить: отменить запись и внести заново."
)
OPENING_FROZEN = "Первый день закрыт: начальные балансы больше не меняются."
OPENING_ALL_ENTERED = "Начальные балансы внесены по всем валютам."
ASK_OPENING_CURRENCY = "Какую валюту вносите?"


def opening_screen(baseline: dict[Currency, Decimal], frozen: bool, all_entered: bool) -> str:
    lines = [OPENING_TITLE]
    for currency, value in baseline.items():
        if currency == HOME_CURRENCY:
            lines.append(f"{CASH_NAME}: {format_money(value, currency)}")
        else:
            lines.append(f"{currency}: {format_amount(value)}")
    if frozen:
        hint = OPENING_FROZEN
    elif all_entered:
        hint = f"{OPENING_ALL_ENTERED} {OPENING_FIX_HINT}"
    else:
        hint = f"{OPENING_ENTER_HINT} {OPENING_FIX_HINT}"
    return "\n".join([*lines, "", hint])


def ask_opening_amount(currency: Currency) -> str:
    return f"<b>Начальный баланс {currency}</b>\nСколько {currency} на начало работы?"


def confirm_opening(currency: Currency, amount: Decimal, balance: Decimal) -> str:
    return "\n".join(
        [
            "<b>Проверьте начальный баланс</b>",
            f"Валюта: {currency}",
            f"Сумма: {format_money(amount, currency)}",
            "",
            "<b>После сохранения:</b>",
            balance_line(currency, balance),
        ]
    )


def opening_exists(currency: Currency) -> str:
    return (
        f"Начальный баланс {currency} уже внесён. Чтобы исправить его, отмените ту запись "
        "и внесите заново."
    )


# --- Exchange (TZ 6.4, 13.3) -------------------------------------------------------------------

EXCHANGE_TITLE = "<b>Обмен</b>"
ASK_GIVE_CURRENCY = "Что клиент отдаёт?"
ASK_GET_CURRENCY = "Что клиент получает?"
BTN_ENTER_GET_AMOUNT = "Ввести сумму, которую получает"
BTN_ENTER_GIVE_AMOUNT = "Ввести сумму, которую отдаёт"
ASK_MODE = "Как проходит обмен?"
BTN_MODE_NOW = "Сразу: получили и выдали"
BTN_MODE_RECEIVED = "Получили, выдадим позже"
BTN_MODE_PAID = "Выдали, получим позже"
BTN_MODE_LATER = "Обе стороны позже"
NOTHING_TO_EXCHANGE = (
    "Одна валюта, одинаковые суммы и обе стороны сразу: записывать нечего. "
    "Измените сумму или выберите другой вариант."
)
BTN_EDIT_AMOUNT = "Изменить сумму"
BTN_COMMENT = "Комментарий"
BTN_SET_CLIENT = "Указать клиента"
ASK_EXCHANGE_COMMENT = "Напишите комментарий к обмену:"
NO_CLIENT = "без имени"


def ask_give_amount(currency: Currency) -> str:
    return f"Сколько клиент отдаёт ({currency})?"


def ask_get_amount(currency: Currency) -> str:
    return f"Сколько клиент получает ({currency})?"


def btn_last_rate(rate: Decimal) -> str:
    return f"Последний курс: {format_rate(rate)}"


def exchange_line(
    give_currency: Currency | None,
    give_amount: Decimal | None,
    get_currency: Currency | None,
    get_amount: Decimal | None,
) -> str:
    """ "88 500 RUB → 1 000 USD"; a part not known yet shows as a currency or "…"."""

    def side(currency: Currency | None, amount: Decimal | None) -> str:
        if currency is None:
            return "…"
        return format_money(amount, currency) if amount is not None else str(currency)

    return f"{side(give_currency, give_amount)} → {side(get_currency, get_amount)}"


def exchange_step(line: str, question: str, problem: str | None = None) -> str:
    return step_text(EXCHANGE_TITLE, [line], question, problem)


def give_status(received_now: bool) -> str:
    return "получено" if received_now else "получим позже"


def get_status(paid_now: bool) -> str:
    return "выдано" if paid_now else "выдадим позже"


def confirm_exchange(
    *,
    client_name: str | None,
    give_currency: Currency,
    give_amount: Decimal,
    get_currency: Currency,
    get_amount: Decimal,
    received_now: bool,
    paid_now: bool,
    rate_line: str | None,
    comment: str | None,
    after: list[str],
) -> str:
    """TZ 13.3 step 7."""
    lines = [
        "<b>Проверьте обмен</b>",
        f"Клиент: {esc(client_name) if client_name else NO_CLIENT}",
        f"Клиент отдаёт: {format_money(give_amount, give_currency)} — {give_status(received_now)}",
        f"Клиент получает: {format_money(get_amount, get_currency)} — {get_status(paid_now)}",
    ]
    if rate_line:
        lines.append(f"Курс: {rate_line}")
    if comment:
        lines.append(f"Комментарий: {esc(comment)}")
    lines += ["", "<b>После сохранения:</b>", *after]
    return "\n".join(lines)


def ask_edit_amount(currency: Currency, gets: bool) -> str:
    who = "получает" if gets else "отдаёт"
    return f"Сколько клиент {who} ({currency})? Введите новую сумму:"


# --- Warnings (TZ 6.6) --------------------------------------------------------------------------


def warning_text(warning: RecordWarning, currency: Currency) -> str:
    excess = format_money(warning.excess, currency) if warning.excess is not None else ""
    match warning.kind:
        case WarningKind.NOTHING_WE_OWE:
            return (
                f"Внимание: мы ничего не должны клиенту в {currency}. "
                "Вся сумма станет долгом клиента перед нами."
            )
        case WarningKind.MORE_THAN_WE_OWE:
            return (
                "Внимание: сумма больше нашего долга. "
                f"Лишние {excess} станут долгом клиента перед нами."
            )
        case WarningKind.NOTHING_OWED_TO_US:
            return (
                f"Внимание: клиент ничего не должен нам в {currency}. "
                "Вся сумма станет нашим долгом перед ним."
            )
        case WarningKind.MORE_THAN_OWED:
            return (
                "Внимание: сумма больше долга клиента. "
                f"Лишние {excess} станут нашим долгом перед ним."
            )


def btn_whole_amount(amount: Decimal, currency: Currency) -> str:
    """ "Всю сумму: 1 000 USD": the amount that settles the obligation."""
    return f"Всю сумму: {format_money(amount, currency)}"


# --- «Ждут выдачи» and «Ждут оплаты» (TZ 13.4) ---------------------------------------------------

TO_PAY_TITLE = "<b>Ждут выдачи</b>"
TO_RECEIVE_TITLE = "<b>Ждут оплаты</b>"
TO_PAY_EMPTY = "Сейчас никто не ждёт выдачи."
TO_RECEIVE_EMPTY = "Сейчас никто не должен нам по обменам."
TO_PAY_HINT = "Нажмите на строку, чтобы выдать."
TO_RECEIVE_HINT = "Нажмите на строку, чтобы получить."
PAYOUT_TITLE = "<b>Выдача по обмену</b>"
RECEIPT_TITLE = "<b>Получение по обмену</b>"
BTN_GIVE_OUT = "Выдать"
BTN_TAKE_IN = "Получить"
ASK_SETTLE_CURRENCY = "В какой валюте?"


def waiting_list(paying: bool, totals: dict[Currency, Decimal]) -> str:
    """The title and the total of every currency above the rows (TZ 13.4)."""
    title = TO_PAY_TITLE if paying else TO_RECEIVE_TITLE
    if not totals:
        return f"{title}\n{TO_PAY_EMPTY if paying else TO_RECEIVE_EMPTY}"
    lines = [title, "Итого:"]
    lines += [f"{currency}: {format_amount(total)}" for currency, total in totals.items()]
    return "\n".join([*lines, "", TO_PAY_HINT if paying else TO_RECEIVE_HINT])


def waiting_button(name: str, amount: Decimal, currency: Currency) -> str:
    """ "Азамат · 1 000 USD" (button texts are not HTML)."""
    return f"{name} · {format_money(amount, currency)}"


def settle_currency_button(currency: Currency, obligation: Decimal) -> str:
    """ "USD · мы должны 1 000" / "RUB · должен нам 5 000" / "EUR"."""
    return f"{currency} · {owe_text(obligation)}" if obligation != 0 else str(currency)


def ask_settle_amount(paying: bool, client_name: str, currency: Currency) -> str:
    """Names are not declined (TZ 13.1): "Сколько выдаём клиенту Азамат (USD)?"."""
    if paying:
        return f"Сколько выдаём клиенту {esc(client_name)} ({currency})?"
    return f"Сколько получаем от клиента {esc(client_name)} ({currency})?"


def confirm_settlement(
    paying: bool,
    client_name: str,
    amount: Decimal,
    currency: Currency,
    after: list[str],
    warning: str | None,
) -> str:
    """TZ 13.4 step 2: the new balance and obligation, the warnings of 6.6 in bold."""
    lines = [
        "<b>Проверьте выдачу</b>" if paying else "<b>Проверьте получение</b>",
        client_line(client_name),
        f"{'Выдаём' if paying else 'Получаем'}: {format_money(amount, currency)}",
        "",
        "<b>После сохранения:</b>",
        *after,
    ]
    if warning:
        lines += ["", f"<b>{warning}</b>"]
    return "\n".join(lines)


# --- Som loans (TZ 13.5) -------------------------------------------------------------------------

LOANS_TITLE = "<b>Долги в сомах</b>"
BTN_LOAN_GIVE = "Выдал в долг"
BTN_LOAN_REPAY_IN = "Мне вернули"
BTN_LOAN_TAKE = "Взял в долг"
BTN_LOAN_REPAY_OUT = "Я вернул"
BTN_WHO_OWES = "Кто кому должен"
LOAN_LABEL = {
    OperationType.LOAN_GIVE: BTN_LOAN_GIVE,
    OperationType.LOAN_REPAY_IN: BTN_LOAN_REPAY_IN,
    OperationType.LOAN_TAKE: BTN_LOAN_TAKE,
    OperationType.LOAN_REPAY_OUT: BTN_LOAN_REPAY_OUT,
}
ASK_LOAN_AMOUNT = "Сколько сомов?"
ASK_RECORD_COMMENT = "Добавьте комментарий к записи или нажмите «Пропустить»:"
OWED_TO_US = "Нам должны:"
WE_OWE = "Мы должны:"
NO_LOAN_DEBTS = "Долгов в сомах нет."


def loans_screen() -> str:
    return f"{LOANS_TITLE}\n\nВыберите действие:"


def loan_title(op_type: OperationType, client_name: str | None = None) -> str:
    """ "<b>Выдал в долг: Бекзат</b>"."""
    if client_name is None:
        return f"<b>{LOAN_LABEL[op_type]}</b>"
    return f"<b>{LOAN_LABEL[op_type]}: {esc(client_name)}</b>"


def loan_amount_line(amount: Decimal) -> str:
    return f"Сумма: {format_money(amount, HOME_CURRENCY)}"


def confirm_loan(
    op_type: OperationType,
    client_name: str,
    amount: Decimal,
    comment: str | None,
    after: list[str],
    warning: str | None,
) -> str:
    """TZ 13.5 step 5."""
    lines = [
        "<b>Проверьте запись</b>",
        f"{LOAN_LABEL[op_type]}: {esc(client_name)}",
        loan_amount_line(amount),
    ]
    if comment:
        lines.append(f"Комментарий: {esc(comment)}")
    lines += ["", "<b>После сохранения:</b>", *after]
    if warning:
        lines += ["", f"<b>{warning}</b>"]
    return "\n".join(lines)


def loan_debts_page(
    items: list[tuple[str, Decimal]], owed_total: Decimal, owing_total: Decimal
) -> str:
    """«Кто кому должен» of som loans (TZ 13.5): both totals and one page of the two lists.

    `items` are (name, obligation): above zero the client owes us.
    """
    title = f"{LOANS_TITLE} · {BTN_WHO_OWES.lower()}"
    if not items:
        return f"{title}\n{NO_LOAN_DEBTS}"
    lines = [
        title,
        f"Итого нам должны: {format_money(owed_total, HOME_CURRENCY)}",
        f"Итого мы должны: {format_money(owing_total, HOME_CURRENCY)}",
    ]
    section: bool | None = None
    for name, amount in items:
        owed = amount > 0
        if owed != section:
            lines += ["", f"<b>{OWED_TO_US if owed else WE_OWE}</b>"]
            section = owed
        lines.append(f"{esc(name)} — {format_amount(abs(amount))}")
    return "\n".join(lines)


# --- Records: card, lists, cancellation (TZ 11, 13.7, 13.8) ---------------------------------------

TYPE_LABEL = {
    OperationType.EXCHANGE: "Обмен",
    OperationType.EXCHANGE_PAYOUT: "Выдача по обмену",
    OperationType.EXCHANGE_RECEIPT: "Получение по обмену",
    **LOAN_LABEL,
    OperationType.ADJUSTMENT: "Корректировка",
    OperationType.OPENING: "Начальный баланс",
}
BTN_OPEN_RECORD = "Открыть запись"
BTN_CANCEL_RECORD = "Отменить запись"
BTN_CLIENT = "Клиент"
BTN_CONFIRM_CANCEL = "Да, отменить"
RECORD_NOT_FOUND = "Запись не найдена."
RECORD_NOT_CANCELLED = "Запись не отменена."
ASK_CANCEL_REASON = "Напишите причину отмены:"
REASON_EMPTY = "Причина не может быть пустой. Напишите причину:"
ALREADY_REVERSED = "Эта запись уже отменена."
CANNOT_REVERSE_REVERSAL = "Отмену отменить нельзя. Если запись отменили зря, внесите её заново."
CANNOT_REVERSE_ADJUSTMENT = "Корректировку отменить нельзя: внесите встречную корректировку."
ONLY_AUTHOR_CAN_CANCEL = "Отменить запись может только тот, кто её внёс."
DAY_RECORDS_EMPTY = "Записей за день пока нет."
HISTORY_EMPTY = "Записей пока нет."
CANCELLED_MARK = "отменена"


def reversal_mark(original_id: int) -> str:
    """The status of a cancelling record (TZ 11): "отмена записи №16"."""
    return f"отмена записи №{original_id}"


def _money_of(operation: Operation) -> str:
    """ "88 500 RUB → 1 000 USD" / "5 000 KGS" / "−500 USD" (an adjustment has a sign)."""
    if operation.type == OperationType.EXCHANGE:
        assert operation.give_amount is not None and operation.give_currency is not None
        assert operation.get_amount is not None and operation.get_currency is not None
        give = format_money(operation.give_amount, operation.give_currency)
        return f"{give} → {format_money(operation.get_amount, operation.get_currency)}"
    assert operation.amount is not None and operation.currency is not None
    if operation.type == OperationType.ADJUSTMENT:
        return f"{format_signed(operation.amount)} {operation.currency}"
    return format_money(operation.amount, operation.currency)


def record_summary(operation: Operation, client_name: str | None, with_client: bool = True) -> str:
    """ "Обмен · Азамат · 88 500 RUB → 1 000 USD" (button texts are not HTML: no escaping)."""
    parts = [TYPE_LABEL[operation.type]]
    if with_client and (client_name is not None or operation.type == OperationType.EXCHANGE):
        parts.append(client_name or NO_CLIENT)
    parts.append(_money_of(operation))
    return " · ".join(parts)


def _status_suffix(operation: Operation, reversed_by: int | None) -> str:
    if operation.reversal_of_id is not None:
        return f" · {reversal_mark(operation.reversal_of_id)}"
    return f" · {CANCELLED_MARK}" if reversed_by is not None else ""


def record_button(operation: Operation, client_name: str | None, reversed_by: int | None) -> str:
    """A row of «Записи дня»: "№15 · Обмен · Азамат · 88 500 RUB → 1 000 USD · отменена"."""
    summary = record_summary(operation, client_name)
    return f"№{operation.id} · {summary}{_status_suffix(operation, reversed_by)}"


def history_button(operation: Operation, reversed_by: int | None, zone: ZoneInfo) -> str:
    """A row of the history of a client: "№15 · 02.10 · Обмен · 88 500 RUB → 1 000 USD"."""
    day = format_short_date(operation.created_at.astimezone(zone).date())
    summary = record_summary(operation, None, with_client=False)
    return f"№{operation.id} · {day} · {summary}{_status_suffix(operation, reversed_by)}"


def day_records_title(day_number: int, total: int) -> str:
    title = f"<b>Записи дня №{day_number}</b>"
    return f"{title}\n{DAY_RECORDS_EMPTY}" if total == 0 else f"{title}\nВсего: {total}"


def history_title(client_name: str, total: int) -> str:
    title = f"<b>История записей: {esc(client_name)}</b>"
    return f"{title}\n{HISTORY_EMPTY}" if total == 0 else f"{title}\nВсего: {total}"


def record_body(operation: Operation) -> list[str]:
    """The client and the money of a record; `operation.client` must be loaded."""
    client = operation.client.name if operation.client is not None else None
    if operation.type == OperationType.EXCHANGE:
        assert operation.give_amount is not None and operation.give_currency is not None
        assert operation.get_amount is not None and operation.get_currency is not None
        assert operation.received_now is not None and operation.paid_now is not None
        give = format_money(operation.give_amount, operation.give_currency)
        get = format_money(operation.get_amount, operation.get_currency)
        lines = [
            f"Клиент: {esc(client) if client else NO_CLIENT}",
            f"Клиент отдаёт: {give} — {give_status(operation.received_now)}",
            f"Клиент получает: {get} — {get_status(operation.paid_now)}",
        ]
        if operation.rate is not None:
            assert operation.rate_base is not None and operation.rate_quote is not None
            lines.append(
                f"Курс: {rate_text(operation.rate, operation.rate_base, operation.rate_quote)}"
            )
    else:
        lines = [client_line(client)] if client is not None else []
        lines.append(f"Сумма: {_money_of(operation)}")
    if operation.comment:
        lines.append(f"Комментарий: {esc(operation.comment)}")
    if operation.reason:
        lines.append(f"Причина: {esc(operation.reason)}")
    return lines


def record_card(operation: Operation, reversal: Operation | None, zone: ZoneInfo) -> str:
    """TZ 13.8. `operation.client` and `operation.author` must be loaded."""
    lines = [
        f"<b>Запись №{operation.id} · {TYPE_LABEL[operation.type]} · день №{operation.day_id}</b>",
        *record_body(operation),
        f"Автор: {esc(user_name(operation.author))} · "
        f"{format_datetime(operation.created_at, zone)}",
    ]
    if operation.reversal_of_id is not None:
        lines.append(
            f"Статус: {reversal_mark(operation.reversal_of_id)} "
            f"(причина: {esc(operation.reversal_reason)})"
        )
    if reversal is not None:
        lines.append(
            f"Статус: отменена записью №{reversal.id} (причина: {esc(reversal.reversal_reason)})"
        )
    return "\n".join(lines)


def cancel_title(operation: Operation) -> str:
    """ "<b>Отмена записи №16</b>" and what the record is."""
    client = operation.client.name if operation.client is not None else None
    return f"<b>Отмена записи №{operation.id}</b>\n{esc(record_summary(operation, client))}"


def confirm_cancel(operation: Operation, reason: str, after: list[str]) -> str:
    """TZ 11.3: balances and obligations as they will be after the cancellation."""
    client = operation.client.name if operation.client is not None else None
    return "\n".join(
        [
            f"<b>Отменить запись №{operation.id}?</b>",
            esc(record_summary(operation, client)),
            f"Причина: {esc(reason)}",
            "",
            "<b>После отмены:</b>",
            *after,
        ]
    )


def record_cancelled(original_id: int, reversal_id: int) -> str:
    return f"Запись №{original_id} отменена записью №{reversal_id}."


def insufficient_balance_not_cancelled(error: InsufficientBalance) -> str:
    return f"{insufficient_balance(error)}\n{RECORD_NOT_CANCELLED}"


def helper_cancelled_notice(helper: User, operation: Operation, reason: str) -> str:
    """To every owner (TZ 11.7, 13.11). `operation.client` must be loaded."""
    client = operation.client.name if operation.client is not None else None
    return "\n".join(
        [
            "<b>Помощник отменил запись</b>",
            f"Кто: {esc(user_name_with_username(helper))}",
            f"Запись №{operation.id}: {esc(record_summary(operation, client))}",
            f"Причина: {esc(reason)}",
        ]
    )


# --- Adjustment of a balance (TZ 10, 13.7) --------------------------------------------------------

ADJUST_TITLE = "<b>Корректировка</b>"
ASK_ADJUST_CURRENCY = "Какой баланс исправить?"
ASK_ADJUST_DIRECTION = "Добавить или убрать?"
BTN_ADJUST_ADD = "Добавить"
BTN_ADJUST_REMOVE = "Убрать"
ASK_ADJUST_REASON = "Напишите причину корректировки:"


def adjust_title(currency: Currency) -> str:
    return f"<b>Корректировка · {currency}</b>"


def ask_adjust_amount(currency: Currency, adding: bool) -> str:
    return f"Сколько {'добавить' if adding else 'убрать'} ({currency})?"


def adjust_change(amount: Decimal, currency: Currency) -> str:
    """ "Изменение: −500 USD"."""
    return f"Изменение: {format_signed(amount)} {currency}"


def confirm_adjustment(amount: Decimal, currency: Currency, reason: str, after: list[str]) -> str:
    return "\n".join(
        [
            "<b>Проверьте корректировку</b>",
            adjust_change(amount, currency),
            f"Причина: {esc(reason)}",
            "",
            "<b>После сохранения:</b>",
            *after,
        ]
    )


# --- Reports, the preliminary report, closing and the archive (TZ 7.2, 8, 13.9, 13.10) ----------

REPORTS_TITLE = "<b>Отчёты</b>"
BTN_PRELIMINARY = "Предварительный отчёт"
BTN_ARCHIVE = "Архив закрытых дней"
BTN_JOURNAL = "Журнал записей"
BTN_MOVEMENT = "Движение балансов"
BTN_STATEMENT_REPORT = "Выписка по клиенту"
BTN_EXCEL = "Excel"
BTN_PDF = "PDF"
BTN_CHANGE_RATES = "Изменить курсы"
BTN_DONT_CLOSE = "Не закрывать"
ARCHIVE_TITLE = "<b>Архив закрытых дней</b>"
ARCHIVE_EMPTY = "Закрытых дней пока нет."
NEGATIVE_SURPLUS = "Внимание: излишки отрицательные. Проверьте записи и курсы."
DAY_NOT_CLOSED = "День не закрыт."
CHOOSE_FORMAT = "Выберите формат файла:"
REPORT_SENT = "Файл отчёта отправлен."
NEW_RATES_NEEDED = "Пока вы вводили курсы, появились записи в других валютах."
REPORT_FILE_FAILED = "Не получилось отправить файл отчёта. Попробуйте ещё раз."


def btn_close_day(number: int) -> str:
    return f"Закрыть день №{number}"


def btn_previous_rate(rate: Decimal) -> str:
    return f"Как в прошлый раз: {format_rate(rate)}"


def som_word(value: Decimal) -> str:
    """ "сом" / "сома" / "сомов" after a number: "+1 315 сомов", "+1 053,50 сома"."""
    if value != value.to_integral_value():
        return "сома"
    number = abs(int(value))
    if number % 10 == 1 and number % 100 != 11:
        return "сом"
    if 2 <= number % 10 <= 4 and not 12 <= number % 100 <= 14:
        return "сома"
    return "сомов"


def closing_title(day_number: int) -> str:
    return f"<b>Закрытие дня №{day_number}</b>"


def preliminary_step_title(day_number: int) -> str:
    return f"<b>{BTN_PRELIMINARY} · день №{day_number}</b>"


def preliminary_title(day_number: int, moment: datetime) -> str:
    """TZ 8.3: «Предварительный отчёт · день №N · 02.10.2026 14:20»."""
    return f"Предварительный отчёт · день №{day_number} · {moment:%d.%m.%Y %H:%M}"


def check_title(day_number: int) -> str:
    return f"День №{day_number} — проверка перед закрытием"


def rates_entered(rates: dict[Currency, Decimal]) -> str | None:
    """ "Курсы: USD 87,65, RUB 0,991" — what is entered so far."""
    if not rates:
        return None
    return "Курсы: " + ", ".join(f"{c} {format_rate(rate)}" for c, rate in rates.items())


def ask_report_rate(currency: Currency) -> str:
    return rate_question(currency, HOME_CURRENCY)


def day_check(title: str, report: DayReport) -> str:
    """The key numbers of the day report (TZ 13.9): the check before closing, the preliminary
    report in the chat."""
    lines = [f"<b>{esc(title)}</b>"]
    for line in report.lines:
        if line.currency == HOME_CURRENCY:
            if line.owed_to_us or line.we_owe:
                lines.append(
                    f"{KGS_OF_EXCHANGES}: {format_amount(line.owed_to_us)} − "
                    f"{format_amount(line.we_owe)} = {format_amount(line.position)}"
                )
        elif line.rate is not None:
            assert line.cash is not None
            lines.append(
                f"{line.currency}: {format_amount(line.cash)} + {format_amount(line.owed_to_us)}"
                f" − {format_amount(line.we_owe)} = {format_amount(line.position)}"
                f" × {format_rate(line.rate)} = {format_amount(line.kgs)}"
            )
    lines += [
        f"{CASH_NAME}: {format_amount(report.cash_kgs)}",
        f"Долги в сомах: нам {format_amount(report.loans_owed_to_us_total)}, "
        f"мы {format_amount(report.loans_we_owe_total)}",
        "",
        f"Итог: {format_amount(report.total)}",
        f"Начальная точка: {format_amount(report.baseline_total)}",
        f"Излишки: {format_signed(report.surplus)}",
        f"Изменение за день: {format_signed(report.change)}",
    ]
    if report.surplus < 0:
        lines += ["", f"<b>{NEGATIVE_SURPLUS}</b>"]
    return "\n".join(lines)


def day_closed(day_number: int, surplus: Decimal, next_day: int) -> str:
    """TZ 7.2 step 6: «День №N закрыт. Излишки: +1 053,50 сома. Начат день №N+1.»"""
    return (
        f"День №{day_number} закрыт. Излишки: {format_signed(surplus)} {som_word(surplus)}. "
        f"Начат день №{next_day}."
    )


def day_closed_notice(day_number: int, surplus: Decimal, next_day: int, closer: User) -> str:
    """To the other owners and to the group: the same, and who closed the day."""
    closed = day_closed(day_number, surplus, next_day)
    return f"{closed}\nЗакрыл: {esc(user_name_with_username(closer))}"


def day_already_closed(day_number: int) -> str:
    return f"День №{day_number} уже закрыт."


def archive_button(day_number: int, closed_on: date, surplus: Decimal) -> str:
    """ "День №3 · 02.10.2026 · +1 315"."""
    return f"День №{day_number} · {format_date(closed_on)} · {format_signed(surplus)}"


def archive_day(day_number: int, closed_on: date, report: DayReport) -> str:
    """A closed day of the archive: the numbers of its snapshot."""
    numbers = day_check(day_report_title(day_number, closed_on), report)
    return f"{numbers}\n\n{CHOOSE_FORMAT}"


# --- Choosing a client inside a scenario (TZ 13.3 step 6, 13.5) --------------------------------

CLIENT_QUESTION = "Клиент?"
CHOOSE_CLIENT_HINT = "Выберите клиента из недавних или напишите часть имени для поиска."
NO_CLIENTS_YET = "Клиентов пока нет. Нажмите «Новый клиент»."
ASK_NEW_CLIENT_NAME = "Введите имя нового клиента:"


def client_step(title: str, has_clients: bool) -> str:
    hint = CHOOSE_CLIENT_HINT if has_clients else NO_CLIENTS_YET
    return f"{title}\n\n<b>{CLIENT_QUESTION}</b>\n{hint}"


# --- Group chat (GROUP_CHAT_ID; customer's request, kept for version 2) ------------------


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


def group_record_notice(operation: Operation, after: list[str], zone: ZoneInfo) -> str:
    """A new record or a cancellation with the balances and obligations it changed.

    `operation.client` and `operation.author` must be loaded.
    """
    if operation.reversal_of_id is not None:
        client = operation.client.name if operation.client is not None else None
        lines = [
            f"<b>Новая запись №{operation.id} · {reversal_mark(operation.reversal_of_id)}</b>",
            esc(record_summary(operation, client)),
            f"Причина: {esc(operation.reversal_reason)}",
        ]
        heading = "<b>После отмены:</b>"
    else:
        lines = [
            f"<b>Новая запись №{operation.id} · {TYPE_LABEL[operation.type]}</b>",
            *record_body(operation),
        ]
        heading = "<b>После записи:</b>"
    lines.append(
        f"Автор: {esc(user_name_with_username(operation.author))} · "
        f"{format_datetime(operation.created_at, zone)}"
    )
    return "\n".join([*lines, "", heading, *after])


# --- Report files (TZ 8.4, 14) ---------------------------------------------------------------

KGS_OF_EXCHANGES = "KGS (обмены)"
NO_DASH = "—"
REPORT_TOTAL = "Итого"
DAY_REPORT_SHEET = "Отчёт"
EXCHANGES_SHEET = "Обмены"
DAY_RECORDS_SHEET = "Записи дня"
BLOCK_CURRENCIES = "Валюты"
BLOCK_CASH = "Наличка"
BLOCK_LOANS = "Долги в сомах"
BLOCK_RESULT = "Результат"
BLOCK_EXCHANGES = "Обязательства по обменам"
BLOCK_RECORDS = "Записи дня"
CURRENCY_COLUMNS = (
    "Валюта",
    "Баланс",
    "Нам должны",
    "Мы должны",
    "Остаток",
    "Курс",
    "В сомах",
)
CURRENCIES_TOTAL = "Итого по валютам"
NAME_COLUMNS = ("Имя", "Сумма")
EXCHANGE_COLUMNS = ("Валюта", "Кто кому", "Имя", "Сумма")
RESULT_COLUMNS = ("Строка", "Значение")
RESULT_TOTAL = "Итог"
RESULT_BASELINE = "Начальная точка"
RESULT_SURPLUS = "Излишки"
RESULT_CHANGE = "Изменение за день"
NOBODY_OWES = "Нет"
JOURNAL_COLUMNS = (
    "№",
    "День",
    "Время",
    "Тип",
    "Клиент",
    "Отдаёт клиент",
    "Получает клиент",
    "Курс",
    "Исполнение",
    "Сумма",
    "Комментарий или причина",
    "Автор",
    "Статус",
)
NO_RECORDS = "Записей нет"
EXECUTION = {
    (True, True): "сразу",
    (True, False): "получено, выдача позже",
    (False, True): "выдано, оплата позже",
    (False, False): "обе стороны позже",
}


def report_generated_line(moment: datetime) -> str:
    return f"Сформирован: {moment:%d.%m.%Y %H:%M}"


def report_author_line(name: str) -> str:
    return f"Сформировал: {name}"


def report_page(number: int, total: int) -> str:
    return f"Страница {number} из {total}"


def day_report_title(day_number: int, closed_on: date) -> str:
    return f"Отчёт дня №{day_number} · {format_date(closed_on)}"


def closed_by_line(name: str, moment: datetime) -> str:
    return f"Закрыл: {name} · {moment:%d.%m.%Y %H:%M}"


def baseline_line(currency: Currency, base: Decimal, rate: Decimal) -> str:
    """ "USD: 10 000 × 87,65" (a part of «Начальная точка»); som without a rate."""
    if currency == HOME_CURRENCY:
        return f"{currency}: {format_amount(base)}"
    return f"{currency}: {format_amount(base)} × {format_rate(rate)}"


def owed_to_us_title(currency: Currency | None = None) -> str:
    return f"{currency} · нам должны" if currency else "Нам должны"


def we_owe_title(currency: Currency | None = None) -> str:
    return f"{currency} · мы должны" if currency else "Мы должны"


def journal_status(reversed_by: int | None, reversal_of: int | None, reason: str | None) -> str:
    """TZ 14.3: empty, «отменена записью №M» or «отмена записи №N (причина)»."""
    if reversal_of is not None:
        return f"{reversal_mark(reversal_of)} ({reason})"
    if reversed_by is not None:
        return f"отменена записью №{reversed_by}"
    return ""


def day_report_file_name(day_number: int, closed_on: date, extension: str) -> str:
    """ "Отчёт_дня_15_2026-10-02.xlsx" (TZ 14)."""
    return f"Отчёт_дня_{day_number}_{closed_on:%Y-%m-%d}.{extension}"


def preliminary_file_name(day_number: int, moment: datetime, extension: str) -> str:
    """ "Предварительный_отчёт_день_15_2026-10-02_1420.xlsx" (docs/decisions.md, 21)."""
    return f"Предварительный_отчёт_день_{day_number}_{moment:%Y-%m-%d_%H%M}.{extension}"
