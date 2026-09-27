"""Every text the user sees lives here (TZ 0.4).

Plain constants are ready-to-send strings; functions build texts with values.
Anything that comes from users (names, comments, reasons) must go through `esc()`.
"""

from datetime import date
from html import escape

from app.db.models import User, UserStatus
from app.domain.dates import format_date


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
