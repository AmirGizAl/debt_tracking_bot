"""In-process Telegram for handler tests.

`FakeTelegram` replaces the HTTP session of aiogram's Bot. It answers API calls from memory,
keeps the text and buttons of every message and enforces the Telegram rules that broke
earlier bots in production: 64-byte callback data, 4096-character texts, strict HTML
("can't parse entities"), "message is not modified", answering a callback query twice.

`UserClient` plays a Telegram user: sends texts and presses buttons by their labels. Updates
go through the real Dispatcher, middlewares, FSM storage and database.
"""

import html
import itertools
import json
import re
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from aiogram import Bot, Dispatcher
from aiogram.client.session.base import BaseSession
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.methods import (
    AnswerCallbackQuery,
    DeleteWebhook,
    EditMessageReplyMarkup,
    EditMessageText,
    GetMe,
    SendChatAction,
    SendDocument,
    SendMessage,
    SetMyCommands,
    TelegramMethod,
)
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    Chat,
    Document,
    InlineKeyboardMarkup,
    Message,
    TelegramObject,
    Update,
)
from aiogram.types import User as TgUser

BOT_TOKEN = "123456789:AAFakeTokenForTestsOnly_abcdefghijk"
BOT_USER = TgUser(id=123456789, is_bot=True, first_name="Учёт долгов", username="debt_test_bot")

MAX_TEXT = 4096
MAX_CALLBACK_DATA = 64
ALLOWED_TAGS = {
    "a", "b", "blockquote", "code", "del", "em", "i", "ins", "pre", "s", "span", "strike",
    "strong", "tg-spoiler", "u",
}  # fmt: skip
TAG_RE = re.compile(r"<(/?)([a-z-]+)(\s[^<>]*)?>")
ENTITY_RE = re.compile(r"&(lt|gt|amp|quot|#\d+|#x[0-9a-fA-F]+);")
STRIP_TAGS_RE = re.compile(r"<[^<>]+>")


def check_html(method: TelegramMethod[Any], text: str) -> None:
    """Raise like Telegram does for HTML it cannot parse."""

    def fail(reason: str) -> None:
        raise TelegramBadRequest(method, f"Bad Request: can't parse entities: {reason}")

    stack: list[str] = []
    position = 0
    while position < len(text):
        char = text[position]
        if char == "<":
            match = TAG_RE.match(text, position)
            if match is None:
                fail(f"unescaped '<' at {position}")
                return
            closing, tag = match.group(1), match.group(2)
            if tag not in ALLOWED_TAGS:
                fail(f"unsupported tag <{tag}>")
            if closing:
                if not stack or stack.pop() != tag:
                    fail(f"unmatched </{tag}>")
            else:
                stack.append(tag)
            position = match.end()
            continue
        if char == ">":
            fail(f"unescaped '>' at {position}")
        if char == "&":
            match = ENTITY_RE.match(text, position)
            if match is None:
                fail(f"unescaped '&' at {position}")
                return
            position = match.end()
            continue
        position += 1
    if stack:
        fail(f"unclosed <{stack[-1]}>")


def plain(text: str) -> str:
    return html.unescape(STRIP_TAGS_RE.sub("", text))


def readable(text: str) -> str:
    """No-break spaces become plain ones to keep assertions readable."""
    return text.replace("\u00a0", " ")


@dataclass
class FakeMessage:
    chat_id: int
    message_id: int
    from_bot: bool
    html: str = ""
    markup: InlineKeyboardMarkup | None = None
    document_name: str | None = None
    document_data: bytes | None = None

    @property
    def text(self) -> str:
        """Visible text with plain spaces (see `readable`)."""
        return readable(plain(self.html))

    @property
    def buttons(self) -> list[list[str]]:
        if self.markup is None:
            return []
        return [[readable(button.text) for button in row] for row in self.markup.inline_keyboard]

    @property
    def button_texts(self) -> list[str]:
        return [text for row in self.buttons for text in row]

    def callback_data(self, button_text: str) -> str | None:
        if self.markup is None:
            return None
        for row in self.markup.inline_keyboard:
            for button in row:
                if readable(button.text) == button_text:
                    return button.callback_data
        return None

    def as_message(self, sender: TgUser) -> Message:
        return Message(
            message_id=self.message_id,
            date=datetime.now(UTC),
            chat=Chat(id=self.chat_id, type="private"),
            from_user=BOT_USER if self.from_bot else sender,
            text=self.text or None,
            reply_markup=self.markup,
        )


class FakeTelegram(BaseSession):
    def __init__(self) -> None:
        super().__init__()
        self.requests: list[TelegramMethod[Any]] = []
        self.messages: dict[tuple[int, int], FakeMessage] = {}
        self.history: dict[int, list[FakeMessage]] = defaultdict(list)
        self.callback_answers: dict[str, AnswerCallbackQuery] = {}
        self.chat_actions: list[SendChatAction] = []
        self.unreachable_chats: set[int] = set()
        # The message a user is looking at: the newest sent one or the one whose text was
        # just edited (removing buttons alone does not count).
        self.last_shown: dict[int, FakeMessage] = {}
        self._message_ids: dict[int, itertools.count[int]] = defaultdict(lambda: itertools.count(1))

    def next_message_id(self, chat_id: int) -> int:
        return next(self._message_ids[chat_id])

    def add(self, message: FakeMessage) -> FakeMessage:
        self.messages[(message.chat_id, message.message_id)] = message
        self.history[message.chat_id].append(message)
        if message.from_bot:
            self.last_shown[message.chat_id] = message
        return message

    async def close(self) -> None:
        return None

    async def stream_content(self, *args: Any, **kwargs: Any) -> Any:  # pragma: no cover
        raise NotImplementedError

    async def make_request(
        self,
        bot: Bot,
        method: TelegramMethod[Any],
        timeout: int | None = None,  # noqa: ASYNC109 (BaseSession interface)
    ) -> Any:
        self.requests.append(method)
        handler = getattr(self, f"_do_{type(method).__name__}", None)
        if handler is None:  # pragma: no cover
            raise NotImplementedError(f"FakeTelegram does not support {type(method).__name__}")
        result = handler(method)
        if isinstance(result, TelegramObject):
            result.as_(bot)
        return result

    # --- validation -----------------------------------------------------------------------

    def _check_chat(self, method: TelegramMethod[Any], chat_id: int | str) -> int:
        if int(chat_id) in self.unreachable_chats:
            raise TelegramForbiddenError(method, "Forbidden: bot can't initiate conversation")
        return int(chat_id)

    @staticmethod
    def _check_text(method: TelegramMethod[Any], text: str) -> None:
        check_html(method, text)
        visible = plain(text)
        if not visible.strip():
            raise TelegramBadRequest(method, "Bad Request: message text is empty")
        if len(visible) > MAX_TEXT:
            raise TelegramBadRequest(method, "Bad Request: message is too long")

    @staticmethod
    def _check_markup(method: TelegramMethod[Any], markup: Any) -> InlineKeyboardMarkup | None:
        if markup is None:
            return None
        assert isinstance(markup, InlineKeyboardMarkup), f"unexpected markup {markup!r}"
        for row in markup.inline_keyboard:
            for button in row:
                data = button.callback_data or ""
                if len(data.encode()) > MAX_CALLBACK_DATA:
                    raise TelegramBadRequest(method, f"Bad Request: BUTTON_DATA_INVALID {data!r}")
                if not button.text.strip():
                    raise TelegramBadRequest(method, "Bad Request: empty button text")
        return markup

    def _existing(self, method: TelegramMethod[Any], chat_id: Any, message_id: Any) -> FakeMessage:
        message = self.messages.get((int(chat_id), int(message_id)))
        if message is None or not message.from_bot:
            raise TelegramBadRequest(method, "Bad Request: message to edit not found")
        return message

    @staticmethod
    def _as_telegram(message: FakeMessage) -> Message:
        return message.as_message(BOT_USER)

    # --- methods ----------------------------------------------------------------------------

    def _do_SendMessage(self, method: SendMessage) -> Message:
        chat_id = self._check_chat(method, method.chat_id)
        self._check_text(method, method.text)
        markup = self._check_markup(method, method.reply_markup)
        message = self.add(
            FakeMessage(
                chat_id=chat_id,
                message_id=self.next_message_id(chat_id),
                from_bot=True,
                html=method.text,
                markup=markup,
            )
        )
        return self._as_telegram(message)

    def _do_EditMessageText(self, method: EditMessageText) -> Message:
        message = self._existing(method, method.chat_id, method.message_id)
        self._check_text(method, method.text)
        markup = self._check_markup(method, method.reply_markup)
        if message.html == method.text and message.markup == markup:
            raise TelegramBadRequest(method, "Bad Request: message is not modified")
        message.html = method.text
        message.markup = markup
        self.last_shown[message.chat_id] = message
        return self._as_telegram(message)

    def _do_EditMessageReplyMarkup(self, method: EditMessageReplyMarkup) -> Message:
        message = self._existing(method, method.chat_id, method.message_id)
        markup = self._check_markup(method, method.reply_markup)
        if message.markup == markup:
            raise TelegramBadRequest(method, "Bad Request: message is not modified")
        message.markup = markup
        return self._as_telegram(message)

    def _do_AnswerCallbackQuery(self, method: AnswerCallbackQuery) -> bool:
        if method.callback_query_id in self.callback_answers:
            raise TelegramBadRequest(method, "Bad Request: query is too old or already answered")
        self.callback_answers[method.callback_query_id] = method
        return True

    def _do_SendDocument(self, method: SendDocument) -> Message:
        chat_id = self._check_chat(method, method.chat_id)
        document = method.document
        assert isinstance(document, BufferedInputFile), f"unexpected document {document!r}"
        if method.caption:
            self._check_text(method, method.caption)
        message = self.add(
            FakeMessage(
                chat_id=chat_id,
                message_id=self.next_message_id(chat_id),
                from_bot=True,
                html=method.caption or "",
                document_name=document.filename,
                document_data=document.data,
            )
        )
        result = self._as_telegram(message)
        return result.model_copy(
            update={
                "document": Document(
                    file_id=f"file-{message.message_id}",
                    file_unique_id=f"unique-{message.message_id}",
                    file_name=document.filename,
                )
            }
        )

    def _do_SendChatAction(self, method: SendChatAction) -> bool:
        self.chat_actions.append(method)
        return True

    def _do_DeleteWebhook(self, method: DeleteWebhook) -> bool:
        return True

    def _do_SetMyCommands(self, method: SetMyCommands) -> bool:
        return True

    def _do_GetMe(self, method: GetMe) -> TgUser:
        return BOT_USER


class JsonMemoryStorage(MemoryStorage):
    """MemoryStorage that stores data the way RedisStorage does: through JSON.

    Keeps a Decimal/date/UUID put into FSM data from passing tests and failing in production.
    """

    async def set_data(self, key: StorageKey, data: Mapping[str, Any]) -> None:
        await super().set_data(key, json.loads(json.dumps(dict(data))))


class Harness:
    def __init__(self, dispatcher: Dispatcher, bot: Bot, telegram: FakeTelegram) -> None:
        self.dispatcher = dispatcher
        self.bot = bot
        self.telegram = telegram
        self._update_ids = itertools.count(1)
        self._callback_ids = itertools.count(1)

    def user(
        self,
        telegram_id: int,
        *,
        username: str | None = None,
        first_name: str = "Тест",
        last_name: str | None = None,
    ) -> "UserClient":
        tg_user = TgUser(
            id=telegram_id,
            is_bot=False,
            first_name=first_name,
            last_name=last_name,
            username=username,
        )
        return UserClient(self, tg_user)

    async def feed(self, update: Update) -> None:
        await self.dispatcher.feed_update(self.bot, update)

    def next_update_id(self) -> int:
        return next(self._update_ids)

    def next_callback_id(self) -> str:
        return str(next(self._callback_ids))


class UserClient:
    def __init__(self, harness: Harness, tg_user: TgUser) -> None:
        self.harness = harness
        self.tg_user = tg_user
        self.chat_id = tg_user.id

    @property
    def telegram(self) -> FakeTelegram:
        return self.harness.telegram

    # --- actions ----------------------------------------------------------------------------

    async def send(
        self, text: str | None = None, *, chat_type: str = "private", **fields: Any
    ) -> None:
        message_id = self.telegram.next_message_id(self.chat_id)
        self.telegram.add(
            FakeMessage(
                chat_id=self.chat_id,
                message_id=message_id,
                from_bot=False,
                html=html.escape(text or ""),
            )
        )
        message = Message(
            message_id=message_id,
            date=datetime.now(UTC),
            chat=Chat(id=self.chat_id, type=chat_type),
            from_user=self.tg_user,
            text=text,
            **fields,
        )
        await self.harness.feed(Update(update_id=self.harness.next_update_id(), message=message))

    async def press(self, data: str, message: FakeMessage) -> AnswerCallbackQuery:
        """Press a button with raw callback data on `message`; returns the callback answer."""
        callback_id = self.harness.next_callback_id()
        callback = CallbackQuery(
            id=callback_id,
            from_user=self.tg_user,
            chat_instance="test-chat",
            message=message.as_message(self.tg_user),
            data=data,
        )
        await self.harness.feed(
            Update(update_id=self.harness.next_update_id(), callback_query=callback)
        )
        answer = self.telegram.callback_answers.get(callback_id)
        assert answer is not None, f"callback {data!r} was not answered (endless spinner)"
        return answer

    async def click(self, button_text: str, *, message: FakeMessage | None = None) -> str | None:
        """Press the button labelled `button_text` on `message` (default: the newest message
        that has such a button). Returns the popup text shown by the bot, if any."""
        target = message or self.message_with_button(button_text)
        data = target.callback_data(button_text)
        assert data is not None, f"no button {button_text!r} in {target.buttons}"
        answer = await self.press(data, target)
        return answer.text

    # --- inspection -------------------------------------------------------------------------

    @property
    def bot_messages(self) -> list[FakeMessage]:
        return [message for message in self.telegram.history[self.chat_id] if message.from_bot]

    @property
    def last(self) -> FakeMessage:
        """What the user looks at: the newest bot message or the one just edited."""
        message = self.telegram.last_shown.get(self.chat_id)
        assert message is not None, "the bot has not sent anything to this chat"
        return message

    def mark(self) -> int:
        return len(self.telegram.history[self.chat_id])

    def since(self, mark: int) -> list[FakeMessage]:
        return [m for m in self.telegram.history[self.chat_id][mark:] if m.from_bot]

    def message_with_button(self, button_text: str) -> FakeMessage:
        for message in reversed(self.bot_messages):
            if button_text in message.button_texts:
                return message
        raise AssertionError(
            f"no message with button {button_text!r}; last buttons: {self.last.buttons}"
        )
