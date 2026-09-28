"""Scripted record scenarios for UI tests."""

from zoneinfo import ZoneInfo

from app.bot import texts
from app.domain.dates import format_date, today
from tests.bot.harness import UserClient

TZ = ZoneInfo("Europe/Moscow")


def today_text() -> str:
    return format_date(today(TZ))


async def begin(client: UserClient, button: str, name: str, *, new: bool = False) -> None:
    """Open a record scenario from the menu and pick (or create) the client."""
    await client.send("/menu")
    await client.click(button)
    if new:
        await client.click(texts.BTN_NEW_CLIENT)
        await client.send(name)
        await client.click(texts.BTN_SKIP)
    else:
        await client.click(name)


async def fill_rest(client: UserClient, amount: str, comment: str | None = None) -> None:
    await client.send(amount)
    await client.click(texts.BTN_TODAY)
    if comment is None:
        await client.click(texts.BTN_SKIP)
    else:
        await client.send(comment)


async def new_debt(
    client: UserClient,
    button: str,
    name: str,
    currency: str,
    amount: str,
    *,
    new: bool = False,
    comment: str | None = None,
) -> None:
    """Up to the confirmation screen of «Выдал в долг» / «Взял в долг»."""
    await begin(client, button, name, new=new)
    await client.click(currency)
    await fill_rest(client, amount, comment)


async def repay_same(
    client: UserClient, button: str, name: str, debt_button: str, amount: str
) -> None:
    """Up to the confirmation screen of a repayment in the debt currency."""
    await begin(client, button, name)
    await client.click(debt_button)
    await client.click(texts.BTN_SAME_CURRENCY)
    await fill_rest(client, amount)


async def save(client: UserClient) -> str:
    """Press «Сохранить»; returns the result message text."""
    await client.click(texts.BTN_SAVE)
    result, menu = client.bot_messages[-2:]
    assert menu.text == texts.MAIN_MENU
    return result.text
