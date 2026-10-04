"""Builds docs/user_guide.pdf: a guide to the bot (version 2) for the owners and the helpers.

Run after changes that the users can see:  python docs/build_user_guide.py
The look follows docs/client_description.pdf (Carlito font, blue headings, screen mock-ups).
Every button and text quoted here must match app/bot/texts.py.
"""

import re
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import (
    BaseDocTemplate,
    Flowable,
    Frame,
    KeepTogether,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

OUTPUT = Path(__file__).with_name("user_guide.pdf")
DATE = "4 октября 2026"
BOT_NAME, BOT_INITIALS = "Учёт обменника", "УО"
GUIDE_TITLE = "Бот учёта обменника"

# Carlito (metric twin of Calibri) as in the customer description; DejaVu Sans if it is missing.
CARLITO = Path("/usr/share/fonts/truetype/crosextra")
DEJAVU = Path(__file__).resolve().parents[1] / "app" / "assets" / "fonts"
if (CARLITO / "Carlito-Regular.ttf").exists():
    FONT_FILES = {
        "Regular": CARLITO / "Carlito-Regular.ttf",
        "Bold": CARLITO / "Carlito-Bold.ttf",
        "Italic": CARLITO / "Carlito-Italic.ttf",
    }
    BASE_SIZE = 10.5
else:
    FONT_FILES = {
        "Regular": DEJAVU / "DejaVuSans.ttf",
        "Bold": DEJAVU / "DejaVuSans-Bold.ttf",
        "Italic": DEJAVU / "DejaVuSans.ttf",
    }
    BASE_SIZE = 9.5
for style_name, font_file in FONT_FILES.items():
    pdfmetrics.registerFont(TTFont(f"Guide-{style_name}", str(font_file)))
REGULAR, BOLD, ITALIC = "Guide-Regular", "Guide-Bold", "Guide-Italic"
pdfmetrics.registerFontFamily(REGULAR, normal=REGULAR, bold=BOLD, italic=ITALIC, boldItalic=BOLD)

NAVY = colors.HexColor("#1F4E79")
BLUE = colors.HexColor("#2E75B6")
TEXT = colors.HexColor("#262626")
MUTED = colors.HexColor("#7F7F7F")
BOX = colors.HexColor("#EEF4FA")
ZEBRA = colors.HexColor("#F4F7FB")
GRID = colors.HexColor("#D5DFEA")
# Telegram-like screens
TG_FRAME = colors.HexColor("#A9BBCD")
TG_HEADER = colors.HexColor("#517DA2")
TG_AVATAR = colors.HexColor("#8DB4DA")
TG_SUBTITLE = colors.HexColor("#D5E3F0")
TG_CHAT = colors.HexColor("#E4EBF2")
TG_BUBBLE_BORDER = colors.HexColor("#CAD5E1")
TG_BUTTON = colors.HexColor("#F6F9FC")
TG_BUTTON_BORDER = colors.HexColor("#B4C5D7")
TG_BUTTON_TEXT = colors.HexColor("#2B5F8F")
TG_PANEL = colors.HexColor("#D6DDE5")
TG_KEY_BORDER = colors.HexColor("#C2CCD6")
TG_PLACEHOLDER = colors.HexColor("#9AA6B2")

PAGE_WIDTH, PAGE_HEIGHT = A4
MARGIN_X, MARGIN_TOP, MARGIN_BOTTOM = 18 * mm, 16 * mm, 20 * mm
WIDTH = PAGE_WIDTH - 2 * MARGIN_X
MOCK_WIDTH = 76 * mm
GAP = 8 * mm

BODY = ParagraphStyle(
    "body", fontName=REGULAR, fontSize=BASE_SIZE, leading=BASE_SIZE * 1.36, textColor=TEXT,
    spaceAfter=4,
)  # fmt: skip
TITLE = ParagraphStyle("title", fontName=BOLD, fontSize=26, leading=31, textColor=NAVY)
SUBTITLE = ParagraphStyle("subtitle", fontName=REGULAR, fontSize=14, leading=19, textColor=BLUE)
META = ParagraphStyle("meta", fontName=REGULAR, fontSize=9.5, leading=12, textColor=MUTED)
H1 = ParagraphStyle(
    "h1", fontName=BOLD, fontSize=16, leading=20, textColor=NAVY, spaceBefore=11, spaceAfter=6,
    keepWithNext=1,
)  # fmt: skip
H2 = ParagraphStyle(
    "h2", fontName=BOLD, fontSize=BASE_SIZE + 1, leading=BASE_SIZE * 1.45, textColor=TEXT,
    spaceBefore=5, spaceAfter=3, keepWithNext=1,
)  # fmt: skip
BULLET = ParagraphStyle("bullet", parent=BODY, leftIndent=12, bulletIndent=2, spaceAfter=3)
STEP = ParagraphStyle("step", parent=BODY, leftIndent=15, bulletIndent=1, spaceAfter=3)
BOX_TITLE = ParagraphStyle("box_title", parent=BODY, fontName=BOLD, textColor=NAVY)
CELL = ParagraphStyle("cell", parent=BODY, fontSize=BASE_SIZE - 1, leading=(BASE_SIZE - 1) * 1.3)
CELL_BOLD = ParagraphStyle("cell_bold", parent=CELL, fontName=BOLD)
HEAD = ParagraphStyle("head", parent=CELL, fontName=BOLD, textColor=colors.white)
CAPTION = ParagraphStyle(
    "caption", fontName=ITALIC, fontSize=9, leading=11, textColor=MUTED, alignment=TA_CENTER
)
CONTENTS = ParagraphStyle("contents", parent=BODY, spaceAfter=1.5)

SECTIONS = [
    "Начало работы",
    "Кнопки и правила",
    "Обмен",
    "Ждут выдачи и Ждут оплаты",
    "Долги в сомах",
    "Если ошиблись",
    "Клиенты и балансы",
    "Закрытие дня и излишки",
    "Отчёты",
    "Помощники и уведомления",
    "Частые вопросы",
]
THOUSANDS = re.compile(r"(?<=\d) (?=\d{3}\b)")  # "1 000": never broken between the lines


# --- building blocks ---------------------------------------------------------------------------


def para(text: str, style: ParagraphStyle = BODY) -> Paragraph:
    return Paragraph(THOUSANDS.sub("&nbsp;", text), style)


def bullets(*items: str) -> list[Flowable]:
    return [Paragraph(THOUSANDS.sub("&nbsp;", item), BULLET, bulletText="•") for item in items]


def steps(*items: str) -> list[Flowable]:
    return [
        Paragraph(THOUSANDS.sub("&nbsp;", item), STEP, bulletText=f"{n}.")
        for n, item in enumerate(items, start=1)
    ]


def section(number: int, *content: Flowable) -> list[Flowable]:
    """A numbered section with a bookmark; the heading stays with the text after it."""
    title = SECTIONS[number - 1]
    heading = Paragraph(
        f'<a name="s{number}"/><font color="#9DC3E6">{number}</font>&nbsp;&nbsp;{title}', H1
    )
    heading.outline = (f"{number}. {title}", f"outline{number}")  # type: ignore[attr-defined]
    return [heading, *content]


def box(title: str, *texts: str) -> Table:
    """A note with a blue bar on the left, as in the customer description."""
    content: list[Flowable] = [para(title, BOX_TITLE)]
    content += [para(text) for text in texts]
    table = Table([[content]], colWidths=[WIDTH])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), BOX),
                ("LINEBEFORE", (0, 0), (0, -1), 3, BLUE),
                ("LEFTPADDING", (0, 0), (-1, -1), 10),
                ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    return table


def table(header: list[str], rows: list[list[str]], widths: list[float]) -> Table:
    data: list[list[Any]] = [[para(title, HEAD) for title in header]]
    for row in rows:
        first, *rest = row
        data.append([para(first, CELL_BOLD), *(para(cell, CELL) for cell in rest)])
    result = Table(data, colWidths=[width * mm for width in widths], repeatRows=1, hAlign="LEFT")
    style: list[tuple[Any, ...]] = [
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 1), (-1, -1), 0.5, GRID),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]
    style += [("BACKGROUND", (0, row), (-1, row), ZEBRA) for row in range(2, len(data), 2)]
    result.setStyle(TableStyle(style))
    return result


def beside(left: list[Flowable], screen: "Screen", caption: str) -> Table:
    """Text on the left, a screen mock-up with a caption on the right."""
    right: list[Flowable] = [screen, Spacer(1, 2 * mm), para(caption, CAPTION)]
    result = Table([[left, right]], colWidths=[WIDTH - MOCK_WIDTH - GAP, MOCK_WIDTH + GAP])
    result.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
                ("LEFTPADDING", (1, 0), (1, 0), GAP),
            ]
        )
    )
    return result


# --- a Telegram-like screen --------------------------------------------------------------------


@dataclass
class Message:
    lines: list[str]  # "**text**" is bold, "" is an empty line
    buttons: list[list[str]] = field(default_factory=list)


class Screen(Flowable):
    """Chat with the bot: header, messages with inline buttons and, optionally, the panel."""

    HEADER = 10.5 * mm
    PAD = 2.6 * mm
    SIZE = 8.8
    LEADING = 11.2
    BUTTON = 6.2 * mm
    SPACE = 1.4 * mm
    INPUT = 6.6 * mm
    RADIUS = 3 * mm

    def __init__(self, messages: list[Message], panel: list[list[str]] | None = None) -> None:
        super().__init__()
        self.width = MOCK_WIDTH
        self.messages = messages
        self.panel = panel or []
        self.inner = self.width - 2 * self.PAD
        self.wrapped = [self._wrap(message.lines) for message in messages]
        self.height = self._height()

    @staticmethod
    def _font(bold: bool) -> str:
        return BOLD if bold else REGULAR

    def _wrap(self, lines: list[str]) -> list[tuple[str, bool]]:
        limit = self.inner - 2 * self.PAD
        result: list[tuple[str, bool]] = []
        for line in lines:
            bold = line.startswith("**")
            text = THOUSANDS.sub("\u00a0", line.strip("*"))
            current = ""
            for word in text.split(" "):
                candidate = f"{current} {word}".strip()
                width = pdfmetrics.stringWidth(candidate, self._font(bold), self.SIZE)
                if current and width > limit:
                    result.append((current, bold))
                    current = word
                else:
                    current = candidate
            result.append((current, bold))
        return result

    def _bubble_height(self, lines: list[tuple[str, bool]]) -> float:
        return len(lines) * self.LEADING + 2 * self.PAD - 1

    def _rows_height(self, rows: list[list[str]]) -> float:
        return len(rows) * (self.BUTTON + self.SPACE)

    def _height(self) -> float:
        height = self.HEADER + self.PAD
        for lines, message in zip(self.wrapped, self.messages, strict=True):
            height += self._bubble_height(lines) + self.SPACE
            height += self._rows_height(message.buttons) + self.SPACE
        if self.panel:
            height += self.INPUT + self.PAD + self._rows_height(self.panel) + self.PAD
        return height + self.PAD

    def wrap(self, available_width: float, available_height: float) -> tuple[float, float]:
        return self.width, self.height

    def _button(self, x: float, y: float, width: float, label: str, key: bool = False) -> None:
        label = THOUSANDS.sub("\u00a0", label)
        canvas = self.canv
        canvas.setLineWidth(0.6)
        canvas.setStrokeColor(TG_KEY_BORDER if key else TG_BUTTON_BORDER)
        canvas.setFillColor(colors.white if key else TG_BUTTON)
        canvas.roundRect(x, y, width, self.BUTTON, 1.5 * mm, stroke=1, fill=1)
        canvas.setFillColor(TEXT if key else TG_BUTTON_TEXT)
        canvas.setFont(REGULAR if key else BOLD, 8.4)
        canvas.drawCentredString(x + width / 2, y + self.BUTTON / 2 - 2.9, label)

    def _rows(self, top: float, rows: list[list[str]], key: bool = False) -> float:
        for row in rows:
            width = (self.inner - (len(row) - 1) * self.SPACE) / len(row)
            top -= self.BUTTON
            for index, label in enumerate(row):
                self._button(self.PAD + index * (width + self.SPACE), top, width, label, key)
            top -= self.SPACE
        return top

    def draw(self) -> None:
        canvas = self.canv
        width, height = self.width, self.height
        panel_height = self._rows_height(self.panel) + self.PAD if self.panel else 0

        canvas.saveState()
        frame = canvas.beginPath()
        frame.roundRect(0, 0, width, height, self.RADIUS)
        canvas.clipPath(frame, stroke=0, fill=0)
        canvas.setFillColor(TG_CHAT)
        canvas.rect(0, 0, width, height, stroke=0, fill=1)
        canvas.setFillColor(TG_HEADER)
        canvas.rect(0, height - self.HEADER, width, self.HEADER, stroke=0, fill=1)
        if self.panel:
            canvas.setFillColor(TG_PANEL)
            canvas.rect(0, 0, width, panel_height + self.PAD / 2, stroke=0, fill=1)
        canvas.restoreState()
        canvas.setStrokeColor(TG_FRAME)
        canvas.setLineWidth(0.8)
        canvas.roundRect(0, 0, width, height, self.RADIUS, stroke=1, fill=0)

        middle = height - self.HEADER / 2
        canvas.setFillColor(TG_AVATAR)
        canvas.circle(self.PAD + 3.6 * mm, middle, 3.6 * mm, stroke=0, fill=1)
        canvas.setFillColor(colors.white)
        canvas.setFont(BOLD, 8)
        canvas.drawCentredString(self.PAD + 3.6 * mm, middle - 2.8, BOT_INITIALS)
        canvas.setFont(BOLD, 10)
        canvas.drawString(self.PAD + 9.5 * mm, middle + 0.6, BOT_NAME)
        canvas.setFillColor(TG_SUBTITLE)
        canvas.setFont(REGULAR, 8)
        canvas.drawString(self.PAD + 9.5 * mm, middle - 8.2, "бот")

        top = height - self.HEADER - self.PAD
        for lines, message in zip(self.wrapped, self.messages, strict=True):
            bubble_height = self._bubble_height(lines)
            text_width = max(
                pdfmetrics.stringWidth(text, self._font(bold), self.SIZE) for text, bold in lines
            )
            bubble_width = min(self.inner, text_width + 2 * self.PAD)
            canvas.setFillColor(colors.white)
            canvas.setStrokeColor(TG_BUBBLE_BORDER)
            canvas.setLineWidth(0.5)
            canvas.roundRect(
                self.PAD, top - bubble_height, bubble_width, bubble_height, 2 * mm, stroke=1, fill=1
            )
            canvas.setFillColor(TEXT)
            baseline = top - self.PAD - self.SIZE * 0.8
            for text, bold in lines:
                canvas.setFont(self._font(bold), self.SIZE)
                canvas.drawString(2 * self.PAD, baseline, text)
                baseline -= self.LEADING
            top -= bubble_height + self.SPACE
            top = self._rows(top, message.buttons) - self.SPACE

        if self.panel:
            input_top = panel_height + self.PAD / 2 + self.PAD + self.INPUT
            canvas.setFillColor(colors.white)
            canvas.setStrokeColor(TG_KEY_BORDER)
            canvas.roundRect(
                self.PAD, input_top - self.INPUT, self.inner, self.INPUT, 3 * mm, stroke=1, fill=1
            )
            canvas.setFillColor(TG_PLACEHOLDER)
            canvas.setFont(REGULAR, 8.4)
            canvas.drawString(2 * self.PAD, input_top - self.INPUT / 2 - 2.9, "Сообщение")
            self._rows(panel_height, self.panel, key=True)


MENU = [
    ["Обмен"],
    ["Ждут выдачи", "Ждут оплаты"],
    ["Долги в сомах", "Клиенты"],
    ["Балансы", "Отчёты"],
    ["Закрыть день", "Настройки"],
]

MODES = [
    ["Сразу: получили и выдали", "Мгновенный обмен", "Обе суммы сразу в балансах"],
    [
        "Получили, выдадим позже",
        "Деньги клиента уже у вас, выдача потом",
        "Клиент появится в «Ждут выдачи»",
    ],
    [
        "Выдали, получим позже",
        "Клиенту выдали, он заплатит потом",
        "Клиент появится в «Ждут оплаты»",
    ],
    ["Обе стороны позже", "Договорились, деньги потом", "Оба обязательства"],
]

LOAN_BUTTONS = [
    ["Выдал в долг", "Вы дали человеку сомы в долг", "Клиент должен вам больше", "Меньше"],
    ["Мне вернули", "Человек вернул вам долг", "Клиент должен вам меньше", "Больше"],
    ["Взял в долг", "Вы взяли у человека сомы в долг", "Вы должны клиенту больше", "Больше"],
    ["Я вернул", "Вы вернули человеку долг", "Вы должны клиенту меньше", "Меньше"],
]

REPORTS = [
    [
        "Предварительный отчёт",
        "Отчёт текущего дня по курсам, которые вы введёте. Ничего не сохраняет и день не "
        "закрывает.",
    ],
    [
        "Архив закрытых дней",
        "Отчёт любого закрытого дня ровно таким, каким он был при закрытии: «День №3 · "
        "02.10.2026 · +1 315».",
    ],
    [
        "Кто кому должен",
        "Обязательства по обменам по каждой валюте и долги в сомах на текущий момент, с итогами.",
    ],
    ["Журнал записей", "Все записи за период: суммы, курсы, авторы, комментарии и отмены."],
    ["Движение балансов", "Приход, расход и остаток по каждому балансу за период."],
    [
        "Выписка по клиенту",
        "Обязательства клиента на начало периода, каждая запись и обязательства на конец. "
        "Выписку можно открыть и из карточки клиента.",
    ],
]

# --- pages -------------------------------------------------------------------------------------


class Guide(BaseDocTemplate):
    """Pages with a footer "Страница N из M" (M comes from a first, counting pass)."""

    def __init__(self, target: str | BytesIO, total_pages: int | None) -> None:
        super().__init__(
            target,
            pagesize=A4,
            leftMargin=MARGIN_X,
            rightMargin=MARGIN_X,
            topMargin=MARGIN_TOP,
            bottomMargin=MARGIN_BOTTOM,
            title=f"{GUIDE_TITLE} — инструкция по работе",
            subject="Инструкция для владельцев и помощников",
        )
        self.total_pages = total_pages
        frame = Frame(
            MARGIN_X, MARGIN_BOTTOM, WIDTH, PAGE_HEIGHT - MARGIN_TOP - MARGIN_BOTTOM, id="text"
        )
        self.addPageTemplates(
            [
                PageTemplate(
                    id="first", frames=[frame], onPage=self._first, autoNextPageTemplate="rest"
                ),
                PageTemplate(id="rest", frames=[frame], onPage=self._footer),
            ]
        )

    def _first(self, canvas: Canvas, document: BaseDocTemplate) -> None:
        canvas.saveState()
        canvas.setFillColor(NAVY)
        canvas.rect(0, PAGE_HEIGHT - 7 * mm, PAGE_WIDTH, 7 * mm, stroke=0, fill=1)
        canvas.restoreState()
        self._footer(canvas, document)

    def _footer(self, canvas: Canvas, document: BaseDocTemplate) -> None:
        canvas.saveState()
        canvas.setStrokeColor(GRID)
        canvas.setLineWidth(0.5)
        canvas.line(MARGIN_X, 13 * mm, PAGE_WIDTH - MARGIN_X, 13 * mm)
        canvas.setFillColor(MUTED)
        canvas.setFont(REGULAR, 8.5)
        canvas.drawString(MARGIN_X, 9 * mm, f"{GUIDE_TITLE} · инструкция по работе")
        page = canvas.getPageNumber()
        number = f"Страница {page} из {self.total_pages}" if self.total_pages else f"{page}"
        canvas.drawRightString(PAGE_WIDTH - MARGIN_X, 9 * mm, number)
        canvas.restoreState()

    def afterFlowable(self, flowable: Flowable) -> None:
        outline = getattr(flowable, "outline", None)
        if outline is not None:
            title, key = outline
            self.canv.bookmarkPage(key)
            self.canv.addOutlineEntry(title, key, level=0)


def contents() -> Table:
    def item(number: int) -> Paragraph:
        return para(
            f'<a href="#s{number}" color="#1F4E79"><font color="#9DC3E6">{number}</font>'
            f"&nbsp;&nbsp;{SECTIONS[number - 1]}</a>",
            CONTENTS,
        )

    half = (len(SECTIONS) + 1) // 2
    columns = [
        [item(n) for n in range(1, half + 1)],
        [item(n) for n in range(half + 1, len(SECTIONS) + 1)],
    ]
    result = Table([columns], colWidths=[WIDTH / 2, WIDTH / 2])
    result.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    return result


# --- screens of the bot (texts as in app/bot/texts.py) -----------------------------------------


def menu_screen() -> Screen:
    return Screen(
        [
            Message(["Здравствуйте! Кнопки разделов всегда под рукой — на панели внизу экрана."]),
            Message(["День №1. Выберите действие:"], MENU),
        ],
        panel=MENU,
    )


def exchange_screen() -> Screen:
    return Screen(
        [
            Message(
                [
                    "**Проверьте обмен",
                    "Клиент: Азамат",
                    "Клиент отдаёт: 88 500 RUB — получено",
                    "Клиент получает: 1 000 USD — выдадим позже",
                    "Курс: 1 USD = 88,5 RUB",
                    "",
                    "**После сохранения:",
                    "Баланс RUB: 88 500",
                    "Азамат: мы должны 1 000 USD",
                ],
                [["Сохранить", "Не сохранять"], ["Изменить сумму", "Комментарий"], ["‹ Назад"]],
            )
        ]
    )


def payout_screen() -> Screen:
    return Screen(
        [
            Message(
                [
                    "**Выдача по обмену",
                    "Азамат: мы должны 1 000 USD",
                    "Баланс USD: 10 000",
                    "",
                    "**Сколько выдаём клиенту Азамат (USD)?",
                ],
                [["Всю сумму: 1 000 USD"], ["‹ Назад", "В меню"]],
            )
        ]
    )


def loan_screen() -> Screen:
    return Screen(
        [
            Message(
                [
                    "**Проверьте запись",
                    "Выдал в долг: Бекзат",
                    "Сумма: 50 000 KGS",
                    "",
                    "**После сохранения:",
                    "Бекзат: должен нам 50 000 KGS (долг в сомах)",
                    "Наличка: 951 000 KGS",
                ],
                [["Сохранить", "Не сохранять"], ["‹ Назад"]],
            )
        ]
    )


def record_screen() -> Screen:
    return Screen(
        [
            Message(
                [
                    "**Запись №15 · Обмен · день №3",
                    "Клиент: Азамат",
                    "Клиент отдаёт: 88 500 RUB — получено",
                    "Клиент получает: 1 000 USD — выдадим позже",
                    "Курс: 1 USD = 88,5 RUB",
                    "Автор: Айгуль · 02.10.2026 14:03",
                ],
                [["Отменить запись"], ["Клиент"], ["В меню"]],
            )
        ]
    )


def closing_screen() -> Screen:
    return Screen(
        [
            Message(
                [
                    "**День №1 — проверка перед закрытием",
                    "USD: 10 000 + 0 − 1 000 = 9 000 × 87,65 = 788 850",
                    "RUB: 88 500 + 0 − 0 = 88 500 × 0,991 = 87 703,50",
                    "Наличка: 951 000",
                    "Долги в сомах: нам 50 000, мы 0",
                    "",
                    "Итог: 1 877 553,50",
                    "Начальная точка: 1 876 500",
                    "Излишки: +1 053,50",
                    "Изменение за день: +1 053,50",
                ],
                [["Закрыть день №1"], ["Изменить курсы"], ["Не закрывать"]],
            )
        ]
    )


# --- the text ------------------------------------------------------------------------------------

QUESTIONS = [
    (
        "Можно внести запись прошлой датой или в закрытый день?",
        "Нет. Запись всегда попадает в открытый день, закрытый день не меняется. Ошибку из "
        "закрытого дня исправляют отменой записи: отмена попадёт в текущий день.",
    ),
    (
        "Помощник видит «У вас нет доступа к этому боту».",
        "Проверьте, что вы добавили его имя пользователя без ошибок и что оно задано в его "
        "Телеграме. Затем пусть снова нажмёт /start.",
    ),
    (
        "Бот пишет «Недостаточно денег».",
        "Проверьте «Балансы». Если деньги на самом деле есть, владелец вносит их корректировкой "
        "после пересчёта.",
    ),
    (
        "Почему запись нельзя удалить или изменить?",
        "Так история остаётся честной: ошибка исправляется отменой, и обе записи видны в отчётах.",
    ),
    (
        "Излишки отрицательные. Что делать?",
        "Проверьте записи дня и введённые курсы. Если ошибок нет, а денег меньше, это "
        "недостача: пересчитайте деньги и внесите корректировку.",
    ),
    ("Пропала панель с кнопками.", "Отправьте /start."),
]


def story() -> list[Flowable]:
    return [
        Spacer(1, 4 * mm),
        para(GUIDE_TITLE, TITLE),
        Spacer(1, 1.5 * mm),
        para("Инструкция по работе", SUBTITLE),
        para(f"Для владельцев и помощников · {DATE}", META),
        Spacer(1, 5 * mm),
        box(
            "Коротко",
            "Бот в Телеграме заменяет ежедневную таблицу учёта обменника: обмены валют с "
            "клиентами, балансы USD, EUR, RUB, KZT и наличку в сомах, долги в сомах. Каждый день "
            "владелец закрывает, а бот считает излишки — сколько обменник заработал — и присылает "
            "отчёт. Почти всё делается кнопками: печатать нужно только суммы, курсы, имена, "
            "комментарии и причины. Время в боте московское.",
        ),
        Spacer(1, 4 * mm),
        contents(),
        *section(
            1,
            beside(
                [
                    para("Владелец", H2),
                    *steps(
                        "Откройте бота по ссылке от разработчика и нажмите «Старт». Появится "
                        "главное меню «День №1. Выберите действие:», а внизу экрана — панель с "
                        "кнопками разделов.",
                        "Внесите начальные балансы — деньги, которые есть на начало работы: "
                        "«Настройки» → «Начальные балансы» → «Внести» → валюта → сумма → "
                        "«Сохранить». По одной записи на каждую валюту, где есть деньги.",
                        "Внесите долги, которые были до бота: «Настройки» → «Начальные долги» "
                        "→ «Внести» → клиент → валюта → кто кому должен → сумма.",
                        "Если с ботом будут работать помощники, добавьте их (раздел 10).",
                        "Готово: можно записывать обмены.",
                    ),
                    para("Помощник", H2),
                    *steps(
                        "Задайте в настройках Телеграма имя пользователя, если его ещё нет, "
                        "например @aigul_k.",
                        "Попросите владельца добавить вас по этому имени.",
                        "Откройте бота и нажмите «Старт».",
                    ),
                ],
                menu_screen(),
                "Главное меню и панель разделов у владельца",
            ),
            Spacer(1, 3 * mm),
            box(
                "Начальные балансы и начальные долги",
                "От них бот считает излишки (раздел 8): сами по себе ни балансы, ни долги на "
                "начало излишков не дают. Начальные балансы вносят и исправляют, только пока "
                "открыт день №1: ошибку исправляют отменой записи и новой записью, а после "
                "первого закрытия недостачу или излишек вносят корректировкой.",
                "Начальные долги можно внести и отменить в любой день, балансы при этом не "
                "меняются. Для долга в сомах бот спросит, это «Долг в сомах» (займ) или «По "
                "обменам». У клиента один начальный долг на каждую валюту.",
            ),
        ),
        *section(
            2,
            *bullets(
                "<b>Панель внизу экрана</b> видна всегда: с неё можно открыть любой раздел, даже "
                "посреди другого действия. Если панель пропала, отправьте /start.",
                "<b>«‹ Назад»</b> возвращает на предыдущий шаг, <b>«В меню»</b> прерывает "
                "действие без сохранения.",
                "<b>Команды:</b> /menu — главное меню, /cancel — прервать текущее действие, "
                "/start — главное меню и панель.",
                "<b>«Это действие устарело»</b> — нажата кнопка старого сообщения. Продолжайте с "
                "последнего сообщения бота.",
                "<b>Суммы</b> пишите так: 1000, 1 000 или 1 000,50 — не больше двух знаков после "
                "запятой. <b>Курс</b> — например, 87,5.",
                "<b>Рабочий день.</b> «День №N» в меню — текущий рабочий день. Все записи "
                "попадают в него, дату выбирать не нужно.",
                "<b>Деньги не уходят в минус.</b> Если денег не хватает, бот покажет, сколько "
                "есть и сколько нужно, и не сохранит запись: «Недостаточно денег. Баланс USD: "
                "10 000. Нужно: 20 000».",
                "<b>Сохранение.</b> После «Сохранить» бот пишет «Запись №N сохранена.» с кнопкой "
                "«Открыть запись» и показывает главное меню.",
            ),
        ),
        *section(
            3,
            beside(
                steps(
                    "«Обмен» → «Что клиент отдаёт?» — валюта.",
                    "«Что клиент получает?» — валюта. Можно ту же: это перевод без "
                    "конвертации, бот спросит обе суммы, разница — ваша комиссия.",
                    "Сумма, которую клиент отдаёт. Удобнее от другой суммы — нажмите «Ввести "
                    "сумму, которую получает».",
                    "Курс. Вторую сумму бот посчитает сам. Если сегодня уже был обмен этой "
                    "пары, есть кнопка «Последний курс: …».",
                    "«Как проходит обмен?» — один из четырёх вариантов (таблица ниже).",
                    "Клиент: для мгновенного обмена шаг пропускается, иначе выберите из "
                    "недавних, напишите часть имени или нажмите «Новый клиент».",
                    "Проверьте обмен и нажмите «Сохранить».",
                ),
                exchange_screen(),
                "Обмен с выдачей позже",
            ),
            Spacer(1, 3 * mm),
            KeepTogether(
                table(["Как проходит обмен", "Когда", "Что запишет бот"], MODES, [52, 66, 56])
            ),
            Spacer(1, 3 * mm),
            *bullets(
                "<b>Курс</b> бот спрашивает за 1 единицу валюты. С сомами — «Сколько сомов за "
                "1 USD?»; без сомов — за валюту, которая стоит раньше в ряду EUR, USD, RUB, KZT: "
                "«Сколько RUB за 1 USD?», «Сколько USD за 1 EUR?».",
                "<b>«Изменить сумму»</b> на экране проверки — поправить посчитанную сумму, "
                "например округлить до купюр. Курс останется таким, как введён.",
                "<b>«Комментарий»</b> — добавить пояснение. <b>«Указать клиента»</b> — у "
                "мгновенного обмена, если клиента всё же нужно записать.",
                "Если выдача сейчас, а денег не хватает, бот скажет об этом на шаге «Как "
                "проходит обмен?»: выберите выдачу позже или измените сумму.",
            ),
        ),
        *section(
            4,
            beside(
                [
                    *bullets(
                        "<b>«Ждут выдачи»</b> — кому вы ещё должны выдать деньги по обменам. "
                        "<b>«Ждут оплаты»</b> — кто ещё должен вам. Наверху итог по каждой "
                        "валюте, строки — от больших сумм к меньшим: «Азамат · 1 000 USD».",
                        "Нажмите на строку, затем «Всю сумму» или напишите часть суммы. "
                        "Проверьте и нажмите «Сохранить».",
                        "Из карточки клиента: «Выдать» или «Получить» → валюта (на кнопке "
                        "видно обязательство, например «USD · мы должны 1 000») → сумма.",
                        "Выдать больше долга или тому, кому вы ничего не должны, можно: бот "
                        "предупредит, что лишняя сумма станет долгом в обратную сторону.",
                    ),
                ],
                payout_screen(),
                "Выдача из списка «Ждут выдачи»",
            ),
            Spacer(1, 3 * mm),
            box(
                "Пример: клиент хочет сомы вместо долларов",
                "Вы должны Азамату 1 000 USD, а он хочет сомы по курсу 87,5. Сделайте обмен: "
                "клиент отдаёт USD, получает KGS, сумма 1 000, курс 87,5, «Выдали, получим "
                "позже», клиент Азамат. Долг в долларах закроется сам, из налички уйдёт "
                "87 500 KGS.",
            ),
        ),
        *section(
            5,
            para("В разделе пять кнопок: четыре записи и «Кто кому должен»."),
            table(
                ["Кнопка", "Когда нажимать", "Что с долгом", "Наличка"],
                LOAN_BUTTONS,
                [30, 62, 56, 26],
            ),
            Spacer(1, 3 * mm),
            beside(
                [
                    *steps(
                        "«Долги в сомах» → кнопка записи.",
                        "Клиент: из недавних, поиск по части имени или «Новый клиент».",
                        "Сумма в сомах. Для «Мне вернули» и «Я вернул» бот покажет текущий "
                        "долг, а если он есть, — кнопку «Всю сумму». Для «Выдал в долг» и "
                        "«Я вернул» — проверит наличку.",
                        "Комментарий или «Пропустить».",
                        "Проверьте запись и нажмите «Сохранить».",
                    ),
                    Spacer(1, 1 * mm),
                    para(
                        "«Кто кому должен» — два списка по долгам в сомах: «Нам должны» и «Мы "
                        "должны», с итогами."
                    ),
                    para(
                        "Долги в сомах и обязательства по обменам — разные вещи и друг друга не "
                        "гасят: у клиента может быть и то, и другое."
                    ),
                ],
                loan_screen(),
                "Проверка записи «Выдал в долг»",
            ),
        ),
        *section(
            6,
            beside(
                bullets(
                    "<b>До сохранения</b>: «‹ Назад» — исправить предыдущий шаг, «Не "
                    "сохранять» — выйти без записи.",
                    "<b>После сохранения</b> запись нельзя изменить или удалить, но можно "
                    "отменить. Откройте её: «Открыть запись» под сообщением о сохранении, "
                    "«Балансы» → «Записи дня» или «Клиенты» → клиент → «История записей». "
                    "Нажмите «Отменить запись», напишите причину, проверьте балансы после "
                    "отмены и нажмите «Да, отменить». Затем внесите правильную запись.",
                    "Отменить можно только свою запись. Отмену и корректировку отменить нельзя.",
                ),
                record_screen(),
                "Карточка записи",
            ),
            Spacer(1, 2 * mm),
            *bullets(
                "Отмена возвращает балансы и обязательства к прежним значениям. Обе записи "
                "остаются в истории и в отчётах: исходная — «отменена записью №M», отмена — "
                "«отмена записи №N».",
                "Отмена записи из уже закрытого дня попадает в текущий день; отчёт закрытого дня "
                "не меняется.",
                "Если отмена уменьшает баланс, а денег уже нет (например, полученные доллары "
                "выданы другому клиенту), бот скажет об этом сразу и отменить не даст.",
            ),
        ),
        *section(
            7,
            para("Клиенты", H2),
            *bullets(
                "«Клиенты» — список по алфавиту и кнопки «Найти» и «Добавить».",
                "В карточке клиента — обязательства по обменам по валютам («USD: мы должны "
                "1 000», «RUB: должен нам 5 000») и долг в сомах. Кнопки: «Выдать», «Получить», "
                "«История записей», «Выписка», «Изменить». «Удалить» есть только у клиента без "
                "записей.",
                "Имена не повторяются. Для тёзок добавьте уточнение, например «Иван (Ош)».",
            ),
            para("Балансы", H2),
            *bullets(
                "«Балансы» — деньги обменника: USD, EUR, RUB, KZT и наличка в сомах.",
                "«Записи дня» — все записи текущего дня, новые сверху. Нажмите на строку, чтобы "
                "открыть запись.",
                "«Корректировка» (только владельцы) — когда пересчёт денег показал недостачу или "
                "излишек: валюта → «Добавить» или «Убрать» → сумма → причина → «Сохранить». "
                "Корректировка меняет излишки. Отменить её нельзя: ошибку исправляют встречной "
                "корректировкой.",
            ),
        ),
        *section(
            8,
            para(
                "<b>Излишки</b> — главный показатель: сколько обменник заработал в сомах. Бот "
                "переводит в сомы по курсам дня всё, что у вас есть и что вам должны, вычитает "
                "то, что должны вы (итог), и сравнивает с начальными балансами и начальными "
                "долгами по тем же курсам (начальная точка). Ноль — ничего не заработали, плюс — "
                "заработок, минус — ошибка или недостача."
            ),
            beside(
                [
                    *steps(
                        "«Закрыть день» (только владельцы).",
                        "Курсы: «Сколько сомов за 1 USD?» — по валютам, где есть деньги, "
                        "обязательства, начальный баланс или долг. Кнопка «Как в прошлый раз» "
                        "подставит курс прошлого закрытия.",
                        "Проверьте цифры. «Изменить курсы» — ввести их заново, «Не закрывать» — "
                        "выйти.",
                        "Нажмите «Закрыть день №N».",
                    ),
                    Spacer(1, 1 * mm),
                    para(
                        "Бот сохранит отчёт дня, пришлёт всем владельцам Excel и PDF и откроет "
                        "следующий день: «День №1 закрыт. Излишки: +1 053,50 сома. Начат день "
                        "№2.» Отчёт закрытого дня больше не меняется."
                    ),
                    para(
                        "Если излишки отрицательные, бот предупредит: проверьте записи и курсы. "
                        "Закрыть день всё равно можно."
                    ),
                    para(
                        "Посмотреть цифры без закрытия: «Отчёты» → «Предварительный отчёт» — "
                        "его может взять любой пользователь в любой момент."
                    ),
                ],
                closing_screen(),
                "Проверочный экран перед закрытием",
            ),
        ),
        *section(
            9,
            para(
                "Откройте «Отчёты», выберите отчёт, затем период и формат: Excel или PDF. Бот "
                "пришлёт готовый файл, а экран останется — можно сразу взять и второй формат."
            ),
            table(["Отчёт", "Что внутри"], REPORTS, [44, 130]),
            Spacer(1, 3 * mm),
            *bullets(
                "<b>Периоды</b> журнала и движения балансов: «Текущий день», «Закрытый день» "
                "(выбор из списка) и «Период по датам» — две даты в виде 01.10.2026, обе "
                "включительно. Выписка по клиенту — за «Всё время» или «Период по датам».",
                "<b>Отчёт дня</b>: валюты (баланс, нам должны, мы должны, остаток, курс, в "
                "сомах), наличка, долги в сомах, итог, начальная точка и излишки, обязательства "
                "по именам и все записи дня. В Excel — на трёх листах.",
                "Отменённые записи и отмены в отчётах выделены серым.",
            ),
        ),
        *section(
            10,
            para("Помощники", H2),
            *bullets(
                "Помощник делает обмены, выдачи и получения, долги в сомах, работает с "
                "клиентами, видит балансы, записи и все отчёты. Корректировки, начальные "
                "балансы и долги, закрытие дня и помощники — только у владельцев.",
                "Отменить можно только свою запись — и владельцу, и помощнику.",
                "«Настройки» → «Помощники» → «Добавить» → имя пользователя помощника, например "
                "@aigul_k. Когда помощник нажмёт «Старт», владельцам придёт уведомление.",
                "Закрыть доступ: «Помощники» → помощник → «Удалить» → «Да, удалить». Доступ "
                "пропадёт сразу, его записи сохранятся.",
                "Владельцев задаёт разработчик в настройках бота; через бота их не добавить.",
            ),
            para("Уведомления", H2),
            *bullets(
                "Всем владельцам: новый помощник; отмена записи помощником — кто, какая запись, "
                "причина и кнопка «Открыть запись»; закрытие дня — излишки и файлы отчёта.",
                "В группу Телеграма бот может публиковать новые записи, отмены, корректировки, "
                "подключение и удаление помощников и итог закрытия дня. Чтобы подключить группу, "
                "добавьте в неё бота со своего аккаунта: бот пришлёт вам строку GROUP_CHAT_ID — "
                "перешлите её разработчику.",
                "В группе бот ничего не отвечает: работа с ботом идёт только в личных сообщениях.",
            ),
        ),
        *section(11, *[para(f"<b>{question}</b><br/>{answer}") for question, answer in QUESTIONS]),
    ]


def build(output: Path = OUTPUT) -> None:
    # A deferred page footer would break the links and bookmarks, so the pages are counted
    # in a first pass and the file is written in a second one.
    counting = Guide(BytesIO(), total_pages=None)
    counting.build(story())
    Guide(str(output), total_pages=counting.page).build(story())


if __name__ == "__main__":
    build()
    print(OUTPUT)
