import pytest

from app.domain.errors import EmptyText, TextTooLong
from app.domain.notes import optional_text, required_text


def test_optional_text() -> None:
    assert optional_text("  на ремонт  ") == "на ремонт"
    assert optional_text("   ") is None
    assert optional_text(None) is None
    with pytest.raises(TextTooLong):
        optional_text("я" * 501)


def test_required_text() -> None:
    assert required_text(" ошибка в сумме ") == "ошибка в сумме"
    with pytest.raises(EmptyText):
        required_text("  ")
    with pytest.raises(TextTooLong):
        required_text("я" * 501)
