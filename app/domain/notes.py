"""Free texts of records: comments and reasons (TZ 11, 12.4). Pure functions."""

from app.domain.errors import EmptyText, TextTooLong

COMMENT_MAX = 500
REASON_MAX = 500


def optional_text(raw: str | None, limit: int = COMMENT_MAX) -> str | None:
    """A comment: blank becomes None, longer than `limit` is an error."""
    text = (raw or "").strip()
    if not text:
        return None
    if len(text) > limit:
        raise TextTooLong(limit)
    return text


def required_text(raw: str | None, limit: int = REASON_MAX) -> str:
    """A reason: 1 to `limit` characters (TZ 10, 11)."""
    text = optional_text(raw, limit)
    if text is None:
        raise EmptyText()
    return text
