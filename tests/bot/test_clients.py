"""Clients section through the bot UI (TZ 13.6)."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import texts
from app.db.models import Client, User
from tests.bot.harness import UserClient
from tests.factories import make_client, make_loan

MENU = texts.main_menu(1)


async def open_clients(client: UserClient) -> None:
    await client.send("/menu")
    await client.click(texts.BTN_CLIENTS)


async def add_client(client: UserClient, name: str, comment: str | None = None) -> None:
    await open_clients(client)
    await client.click(texts.BTN_ADD)
    await client.send(name)
    if comment is None:
        await client.click(texts.BTN_SKIP)
    else:
        await client.send(comment)


async def owner_user(session: AsyncSession) -> User:
    owner = await session.scalar(select(User).where(User.role == "owner"))
    assert owner is not None
    return owner


async def test_empty_list(owner_client: UserClient) -> None:
    await open_clients(owner_client)

    assert owner_client.last.text == f"Клиенты\n{texts.CLIENTS_EMPTY}"
    assert owner_client.last.button_texts == [texts.BTN_FIND, texts.BTN_ADD, texts.BTN_HOME]


async def test_add_client_and_open_card(owner_client: UserClient) -> None:
    await add_client(owner_client, "  Иван  ", "сосед, г. Бишкек")

    result, menu = owner_client.bot_messages[-2:]
    assert result.text == "Клиент «Иван» добавлен."
    assert menu.text == MENU
    await owner_client.click(texts.BTN_OPEN_CLIENT)
    assert owner_client.last.text == "Иван\nКомментарий: сосед, г. Бишкек"
    assert owner_client.last.button_texts == [
        texts.BTN_EDIT,
        texts.BTN_DELETE,
        texts.BTN_ALL_CLIENTS,
        texts.BTN_HOME,
    ]


async def test_duplicate_name_asks_for_clarification(owner_client: UserClient) -> None:
    await add_client(owner_client, "Иван")
    await open_clients(owner_client)
    await owner_client.click(texts.BTN_ADD)

    await owner_client.send("иван")

    assert owner_client.last.text == (
        "Клиент «Иван» уже есть. Добавьте уточнение, например «Иван (Ош)» или «Иван Петров»."
    )
    await owner_client.send("Иван (Ош)")
    await owner_client.click(texts.BTN_SKIP)
    assert owner_client.bot_messages[-2].text == "Клиент «Иван (Ош)» добавлен."


async def test_back_from_comment_to_name(owner_client: UserClient) -> None:
    await open_clients(owner_client)
    await owner_client.click(texts.BTN_ADD)
    await owner_client.send("Иван")
    await owner_client.click(texts.BTN_BACK)
    assert owner_client.last.text == texts.ASK_CLIENT_NAME

    await owner_client.send("Азамат")
    await owner_client.click(texts.BTN_SKIP)
    assert owner_client.bot_messages[-2].text == "Клиент «Азамат» добавлен."


async def test_user_data_is_escaped(owner_client: UserClient) -> None:
    # The fake Telegram rejects broken HTML exactly like the real one.
    await add_client(owner_client, "<b>A&B</b>", "x < y & z")
    await owner_client.click(texts.BTN_OPEN_CLIENT)

    assert owner_client.last.text.startswith("<b>A&B</b>\nКомментарий: x < y & z")


async def test_search(owner_client: UserClient, session: AsyncSession) -> None:
    owner = await owner_user(session)
    for name in ("Иван", "Иван (Ош)", "Бекзат"):
        await make_client(session, owner, name)
    await open_clients(owner_client)
    await owner_client.click(texts.BTN_FIND)

    await owner_client.send("ИВ")
    assert owner_client.last.text.startswith("Найдено по запросу «ИВ»: 2.")
    assert owner_client.last.button_texts[:2] == ["Иван", "Иван (Ош)"]

    await owner_client.send("ноль")
    assert owner_client.last.text.startswith("По запросу «ноль» никого не нашлось.")


async def test_client_with_records_has_no_delete_button(
    owner_client: UserClient, session: AsyncSession
) -> None:
    owner = await owner_user(session)
    ivan = await make_client(session, owner, "Иван", comment="сосед, г. Бишкек")
    await make_loan(session, owner, ivan, "1000")
    await open_clients(owner_client)

    await owner_client.click("Иван")

    assert owner_client.last.text == "Иван\nКомментарий: сосед, г. Бишкек"
    assert texts.BTN_DELETE not in owner_client.last.button_texts


async def test_rename_and_edit_comment(owner_client: UserClient, session: AsyncSession) -> None:
    owner = await owner_user(session)
    await make_client(session, owner, "Иван", comment="старый")
    await make_client(session, owner, "Азамат")
    await open_clients(owner_client)
    await owner_client.click("Иван")
    await owner_client.click(texts.BTN_EDIT)
    await owner_client.click(texts.BTN_EDIT_NAME)

    await owner_client.send("азамат")
    assert owner_client.last.text.startswith("Клиент «Азамат» уже есть.")
    await owner_client.send("Иван Петров")
    assert owner_client.bot_messages[-2].text == "Имя клиента изменено: «Иван Петров»."

    await owner_client.click(texts.BTN_OPEN_CLIENT)
    await owner_client.click(texts.BTN_EDIT)
    await owner_client.click(texts.BTN_EDIT_COMMENT)
    assert owner_client.last.text == "Введите новый комментарий:\n\nСейчас: старый"
    await owner_client.click(texts.BTN_CLEAR_COMMENT)
    assert owner_client.bot_messages[-2].text == texts.COMMENT_REMOVED

    stored = await session.scalar(select(Client).where(Client.name == "Иван Петров"))
    assert stored is not None
    await session.refresh(stored)
    assert stored.comment is None


async def test_delete_client_without_records(
    owner_client: UserClient, session: AsyncSession
) -> None:
    owner = await owner_user(session)
    await make_client(session, owner, "Ошибка")
    await open_clients(owner_client)
    await owner_client.click("Ошибка")
    await owner_client.click(texts.BTN_DELETE)
    assert owner_client.last.text == "Удалить клиента «Ошибка»?"

    await owner_client.click(texts.BTN_CONFIRM_DELETE)

    assert owner_client.bot_messages[-2].text == "Клиент «Ошибка» удалён."
    assert await session.scalar(select(Client)) is None


async def test_pagination(owner_client: UserClient, session: AsyncSession) -> None:
    owner = await owner_user(session)
    for number in range(1, 13):
        await make_client(session, owner, f"Клиент {number:02d}")
    await open_clients(owner_client)

    assert owner_client.last.buttons[10] == ["1/2", texts.BTN_NEXT_PAGE]
    await owner_client.click(texts.BTN_NEXT_PAGE)
    assert owner_client.last.button_texts[:3] == ["Клиент 11", "Клиент 12", texts.BTN_PREV_PAGE]


async def test_search_buttons_become_stale_after_leaving(
    owner_client: UserClient, session: AsyncSession
) -> None:
    owner = await owner_user(session)
    for number in range(1, 13):
        await make_client(session, owner, f"Клиент {number:02d}")
    await open_clients(owner_client)
    await owner_client.click(texts.BTN_FIND)
    await owner_client.send("клиент")
    results = owner_client.last
    data = results.callback_data(texts.BTN_NEXT_PAGE)
    assert data is not None

    await owner_client.send("/menu")
    assert results.markup is None  # leaving the scenario removes its buttons
    answer = await owner_client.press(data, results)  # a tap that raced the removal

    assert answer.text == texts.STALE_ACTION
