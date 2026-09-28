"""Builds docs/user_guide.pdf: a short guide to the bot for the customer and the helpers.

Run after changes that the users can see:  python docs/build_user_guide.py
The look follows docs/client_description.pdf (Carlito font, blue headings, screen mock-ups).
"""

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
DATE = "28 сентября 2026"

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
    "Кнопки и команды",
    "Запись долга",
    "Возврат долга",
    "Если ошиблись",
    "Клиенты и касса",
    "Отчёты",
    "Помощники и группа",
    "Частые вопросы",
]


# --- building blocks ---------------------------------------------------------------------------


def para(text: str, style: ParagraphStyle = BODY) -> Paragraph:
    return Paragraph(text, style)


def bullets(*items: str) -> list[Flowable]:
    return [Paragraph(item, BULLET, bulletText="•") for item in items]


def steps(*items: str) -> list[Flowable]:
    return [Paragraph(item, STEP, bulletText=f"{n}.") for n, item in enumerate(items, start=1)]


def section(number: int, *content: Flowable) -> KeepTogether:
    """A numbered section, kept on one page (each of them is shorter than a page)."""
    title = SECTIONS[number - 1]
    heading = Paragraph(
        f'<a name="s{number}"/><font color="#9DC3E6">{number}</font>&nbsp;&nbsp;{title}', H1
    )
    heading.outline = (f"{number}. {title}", f"outline{number}")  # type: ignore[attr-defined]
    return KeepTogether([heading, *content])


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
            text = line.strip("*")
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
        canvas.drawCentredString(self.PAD + 3.6 * mm, middle - 2.8, "УД")
        canvas.setFont(BOLD, 10)
        canvas.drawString(self.PAD + 9.5 * mm, middle + 0.6, "Учёт долгов")
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
    ["Выдал в долг", "Мне вернули"],
    ["Взял в долг", "Я вернул"],
    ["Клиенты", "Касса"],
    ["Отчёты", "Настройки"],
]

RECORD_BUTTONS = [
    ["Выдал в долг", "Вы дали человеку деньги в долг", "Клиент должен вам больше", "Денег меньше"],
    ["Мне вернули", "Человек вернул вам долг", "Клиент должен вам меньше", "Денег больше"],
    [
        "Взял в долг",
        "Вы взяли у человека деньги в долг",
        "Вы должны клиенту больше",
        "Денег больше",
    ],
    ["Я вернул", "Вы вернули человеку долг", "Вы должны клиенту меньше", "Денег меньше"],
]

REPORTS = [
    [
        "Общая сводка",
        "Касса и долги по каждой валюте, касса в пересчёте на сомы и списки «Вам должны» и "
        "«Вы должны». Бот спросит курсы валют, которые есть в кассе. Курсы нужны только для "
        "этого отчёта и нигде не сохраняются.",
    ],
    ["Все записи за период", "Все записи с суммами, курсами, авторами и отменами."],
    ["Движение кассы", "Приход, расход и остатки по каждой валюте за период."],
    [
        "Выписка по клиенту",
        "Записи одного клиента и его долг на начало и конец периода. Выписку можно открыть и "
        "из карточки клиента.",
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
            title="Бот для учёта долгов — инструкция по работе",
            subject="Инструкция для владельца и помощников",
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
        canvas.drawString(MARGIN_X, 9 * mm, "Бот для учёта долгов · инструкция по работе")
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

    columns = [[item(n) for n in range(1, 6)], [item(n) for n in range(6, 10)]]
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


def story() -> list[Flowable]:
    menu = Screen(
        [
            Message(["Здравствуйте! Кнопки разделов всегда под рукой — на панели внизу экрана."]),
            Message(["Выберите действие:"], MENU),
        ],
        panel=MENU,
    )
    confirmation = Screen(
        [
            Message(
                [
                    "**Проверьте запись",
                    "Мне вернули: Азамат",
                    "Сумма: 400 USD",
                    "Дата: 28.09.2026",
                    "",
                    "**Сейчас:",
                    "Азамат должен вам: 1 000 USD",
                    "",
                    "**После сохранения:",
                    "Азамат должен вам: 600 USD",
                    "В кассе USD: 9 400",
                ],
                [["Сохранить", "Не сохранять"], ["‹ Назад"]],
            )
        ]
    )
    questions = [
        (
            "Можно внести запись прошлой датой?",
            "Нет, запись всегда получает сегодняшнюю дату. Если нужно, укажите настоящую дату в "
            "комментарии.",
        ),
        (
            "Помощник видит «У вас нет доступа к этому боту».",
            "Проверьте, что вы добавили его имя пользователя без ошибок и что оно задано в его "
            "Телеграме. Затем пусть снова нажмёт /start.",
        ),
        (
            "Бот пишет «Недостаточно денег в кассе».",
            "Проверьте остатки в «Кассе». Если деньги на самом деле есть, внесите их "
            "корректировкой.",
        ),
        (
            "Почему запись нельзя удалить?",
            "Так история остаётся честной: ошибка исправляется отменой, и обе записи видны в "
            "отчётах.",
        ),
        ("Пропала панель с кнопками.", "Отправьте /start."),
    ]
    return [
        Spacer(1, 4 * mm),
        para("Бот для учёта долгов", TITLE),
        Spacer(1, 1.5 * mm),
        para("Инструкция по работе", SUBTITLE),
        para(f"Для владельца и помощников · {DATE}", META),
        Spacer(1, 5 * mm),
        box(
            "Коротко",
            "Бот в Телеграме ведёт учёт долгов с клиентами и кассу в пяти валютах: KGS, USD, EUR, "
            "RUB и KZT. Почти всё делается кнопками: печатать нужно только суммы, курсы, имена, "
            "комментарии и причины. Все даты и время в боте московские.",
        ),
        Spacer(1, 4 * mm),
        contents(),
        section(
            1,
            beside(
                [
                    para("Владелец", H2),
                    *steps(
                        "Откройте бота по ссылке от разработчика и нажмите «Старт». Появится "
                        "главное меню, а внизу экрана — панель с кнопками разделов.",
                        "Внесите в кассу деньги, которые есть у вас сейчас: «Касса» → "
                        "«Корректировка» → валюта → «Добавить» → сумма → причина «Остаток на "
                        "начало работы» → «Сохранить». Повторите для каждой валюты, в которой "
                        "есть деньги.",
                        "Если с ботом будут работать помощники, добавьте их (раздел 8).",
                        "Готово: можно записывать долги.",
                    ),
                    para("Помощник", H2),
                    *steps(
                        "Задайте в настройках Телеграма имя пользователя, если его ещё нет, "
                        "например @aigul_k.",
                        "Попросите владельца добавить вас по этому имени.",
                        "Откройте бота и нажмите «Старт».",
                    ),
                ],
                menu,
                "Главное меню и панель разделов",
            ),
        ),
        section(
            2,
            *bullets(
                "<b>Панель внизу экрана</b> видна всегда: с неё можно открыть любой раздел, даже "
                "посреди другого действия. Если панель пропала, отправьте /start.",
                "<b>«‹ Назад»</b> возвращает на предыдущий шаг, <b>«В меню»</b> прерывает действие "
                "без сохранения.",
                "<b>Команды:</b> /menu — главное меню, /cancel — прервать текущее действие, "
                "/start — главное меню и панель.",
                "<b>«Это действие устарело»</b> — нажата кнопка старого сообщения. Продолжайте с "
                "последнего сообщения бота.",
                "<b>Суммы</b> пишите так: 1000, 1 000 или 1 000,50 — не больше двух знаков после "
                "запятой. <b>Курс</b> — например, 87,5.",
            ),
        ),
        section(
            3,
            para("Любая запись начинается с одной из четырёх кнопок:"),
            table(
                ["Кнопка", "Когда нажимать", "Что с долгом", "Что с кассой"],
                RECORD_BUTTONS,
                [30, 60, 50, 34],
            ),
            Spacer(1, 4 * mm),
            beside(
                [
                    *steps(
                        "Нажмите кнопку записи, например «Мне вернули».",
                        "Выберите клиента из недавних или напишите часть имени для поиска. "
                        "Нового человека добавьте кнопкой «Новый клиент».",
                        "Выберите валюту. Для возврата — долг, который закрывается (раздел 4).",
                        "Напишите сумму. Для «Выдал в долг» и «Я вернул» бот сразу проверит, "
                        "хватает ли денег в кассе.",
                        "Напишите комментарий или нажмите «Пропустить».",
                        "Проверьте запись и нажмите «Сохранить».",
                    ),
                    Spacer(1, 1 * mm),
                    para(
                        "Дату выбирать не нужно: запись получает сегодняшнюю дату по московскому "
                        "времени."
                    ),
                    para(
                        "На экране проверки видно, какой долг у клиента <b>сейчас</b> и каким он "
                        "станет <b>после сохранения</b>, а также сколько денег останется в кассе."
                    ),
                ],
                confirmation,
                "Экран проверки перед сохранением",
            ),
        ),
        section(
            4,
            para(
                "Для «Мне вернули» и «Я вернул» бот показывает долги клиента и спрашивает, какой "
                "долг закрывается. Долг виден прямо на кнопке: «USD · должен 600» или «RUB · вы "
                "должны 30 000». Затем выберите, как вернули деньги:"
            ),
            *bullets(
                "<b>«В этой же валюте»</b> — дальше сумма, комментарий и проверка, как в обычной "
                "записи.",
                "<b>«В другой валюте»</b> — выберите валюту оплаты, напишите сумму оплаты и курс. "
                "Бот сам посчитает, сколько спишется с долга, и подскажет, в какую сторону вводить "
                "курс: «Сколько сомов за 1 USD?» или «Сколько RUB за 1 USD?».",
            ),
            Spacer(1, 2 * mm),
            box(
                "Пример: долг в долларах вернули сомами",
                "Азамат должен вам 600 USD и принёс 52 500 сомов по курсу 87,5. Нажмите «Мне "
                "вернули» → «Азамат» → «USD · должен 600» → «В другой валюте» → «KGS», напишите "
                "52 500, а на вопрос «Сколько сомов за 1 USD?» ответьте 87,5.",
                "На экране проверки будет «Закрывает долг: 600 USD». После сохранения долга в USD "
                "не останется, а в кассе прибавится 52 500 KGS.",
            ),
            Spacer(1, 2 * mm),
            para(
                "Если вернули больше долга или клиент ничего не был должен, бот предупредит: "
                "лишняя сумма станет долгом в обратную сторону. Такую запись всё равно можно "
                "сохранить."
            ),
        ),
        section(
            5,
            *bullets(
                "<b>До сохранения</b>: «‹ Назад» — исправить предыдущий шаг, «Не сохранять» — "
                "выйти без записи.",
                "<b>После сохранения</b> запись нельзя изменить или удалить, но можно отменить. "
                "Откройте запись кнопкой «Открыть запись» под сообщением о сохранении или через "
                "«Клиенты» → клиент → «История записей». Нажмите «Отменить запись», напишите "
                "причину и нажмите «Да, отменить». Затем внесите правильную запись.",
                "Отмена возвращает долг и кассу к прежним значениям. Обе записи остаются в истории "
                "и в отчётах, исходная — с пометкой «отменена».",
                "Отменить можно только свою запись. Отмену отменить нельзя: если отменили по "
                "ошибке, внесите запись заново.",
            ),
        ),
        section(
            6,
            para("Клиенты", H2),
            *bullets(
                "«Клиенты» — список по алфавиту и кнопки «Найти» и «Добавить».",
                "В карточке клиента — его долги по валютам и кнопки «История записей», «Выписка "
                "за период» и «Изменить». Кнопка «Удалить» есть только у клиента без записей.",
                "Имена не повторяются. Для тёзок добавьте уточнение, например «Иван (Ош)».",
            ),
            para("Касса", H2),
            *bullets(
                "«Касса» — остатки по всем пяти валютам.",
                "«Движение денег» — все записи и корректировки, новые сверху. Нажмите на строку, "
                "чтобы посмотреть подробности.",
                "«Корректировка» (только владелец) — добавить или убрать деньги без клиента, с "
                "причиной, например «Личные расходы».",
                "Касса не уходит в минус: если денег не хватает, бот покажет, сколько есть и "
                "сколько нужно, и не сохранит запись.",
            ),
        ),
        section(
            7,
            para(
                "Откройте «Отчёты», выберите отчёт, затем период и формат: Excel или PDF. Бот "
                "пришлёт готовый файл."
            ),
            table(["Отчёт", "Что внутри"], REPORTS, [42, 132]),
            Spacer(1, 3 * mm),
            para(
                "Периоды: «Сегодня», «Неделя» (последние 7 дней), «Месяц» (30 дней), «Год» "
                "(365 дней) и «Всё время». Общая сводка показывает состояние на момент "
                "формирования, период для неё не нужен."
            ),
        ),
        section(
            8,
            para("Помощники", H2),
            *bullets(
                "«Настройки» → «Помощники» → «Добавить» → имя пользователя помощника, например "
                "@aigul_k. Когда помощник нажмёт «Старт», вам придёт уведомление.",
                "Помощник вносит записи и отменяет свои, работает с клиентами, смотрит кассу и "
                "формирует отчёты. Корректировать кассу и управлять помощниками может только "
                "владелец.",
                "Закрыть доступ: «Помощники» → помощник → «Удалить» → «Да, удалить». Доступ "
                "пропадёт сразу, его записи сохранятся.",
                "Если помощник отменит запись, вам придёт уведомление с причиной.",
            ),
            para("Уведомления в группу", H2),
            *bullets(
                "Бот может публиковать в группу Телеграма новые записи, отмены, корректировки "
                "кассы и изменения в списке помощников.",
                "Чтобы подключить группу, добавьте в неё бота со своего аккаунта. Бот пришлёт вам "
                "в личные сообщения строку GROUP_CHAT_ID с номером группы — перешлите её "
                "разработчику, он подключит группу.",
                "В группе бот ничего не отвечает: работа с ботом идёт только в личных сообщениях.",
            ),
        ),
        section(9, *[para(f"<b>{question}</b><br/>{answer}") for question, answer in questions]),
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
