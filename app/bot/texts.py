"""Every text the user sees lives here (TZ 0.5).

Plain constants are ready-to-send strings; functions build texts with values.
Anything that comes from users (names, comments, reasons) must go through `esc()`.
"""

from datetime import date, datetime
from decimal import Decimal
from html import escape

from app.db.models import Client, User, UserStatus
from app.domain.currency import HOME_CURRENCY, Currency
from app.domain.dates import format_date
from app.domain.entries import Book
from app.domain.errors import ConversionProblem, InsufficientBalance, NumberProblem
from app.domain.money import format_amount, format_money, format_rate


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


def client_card(client: Client) -> str:
    lines = [f"<b>{esc(client.name)}</b>"]
    if client.comment:
        lines.append(f"Комментарий: {esc(client.comment)}")
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


def balance_after(currency: Currency, value: Decimal) -> str:
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
            balance_after(currency, balance),
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
    parts = [f"{EXCHANGE_TITLE}\n{line}"]
    if problem:
        parts.append(problem)
    parts.append(f"<b>{question}</b>")
    return "\n\n".join(parts)


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


# --- Report files (TZ 14) -------------------------------------------------------------------


def report_generated_line(moment: datetime) -> str:
    return f"Сформирован: {moment:%d.%m.%Y %H:%M}"


def report_author_line(name: str) -> str:
    return f"Сформировал: {name}"


def report_page(number: int, total: int) -> str:
    return f"Страница {number} из {total}"
