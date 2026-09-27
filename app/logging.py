import logging
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

LOG_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"


class ZoneFormatter(logging.Formatter):
    """Stamps records in the configured time zone regardless of the container clock."""

    def __init__(self, fmt: str, zone: ZoneInfo) -> None:
        super().__init__(fmt)
        self._zone = zone

    def formatTime(self, record: logging.LogRecord, datefmt: str | None = None) -> str:
        moment = datetime.fromtimestamp(record.created, tz=self._zone)
        if datefmt:
            return moment.strftime(datefmt)
        return f"{moment:%Y-%m-%d %H:%M:%S}.{int(record.msecs):03d}{moment:%z}"


def setup_logging(level: str, zone: ZoneInfo) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(ZoneFormatter(LOG_FORMAT, zone))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
