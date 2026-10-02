"""Report data: database queries -> plain dataclasses (TZ 14).

Renderers in excel.py and pdf.py only turn these dataclasses into bytes.
Amounts stay Decimal; labels are ready-made Russian texts, so both formats agree.
"""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class ReportMeta:
    title: str
    generated_at: datetime  # aware, in the configured time zone
    generated_by: str
    scope: str | None = None  # "День №3 · 02.10.2026" or a period of dates, ready to print
