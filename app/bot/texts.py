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
from app.domain.money import format_rate


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
