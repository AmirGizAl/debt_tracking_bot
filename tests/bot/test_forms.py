"""Scenario data in FSM: plain JSON values, restored by the types of the fields."""

import json
from dataclasses import dataclass
from decimal import Decimal

from app.bot.flows.records import StoredForm
from app.domain.currency import Currency
from app.domain.entries import OperationType


@dataclass
class Sample(StoredForm):
    request_id: str
    op_type: OperationType
    paying: bool
    client_id: int | None = None
    currency: Currency | None = None
    amount: Decimal | None = None
    comment: str | None = None


def test_round_trip_through_json() -> None:
    form = Sample(
        request_id="r-1",
        op_type=OperationType.LOAN_GIVE,
        paying=False,
        client_id=7,
        currency=Currency.KGS,
        amount=Decimal("1000.50"),
    )

    stored = json.loads(json.dumps(form.dump()))  # RedisStorage keeps JSON

    assert stored["amount"] == "1000.50"
    assert Sample.load({**stored, "screen_id": 15}) == form  # other keys are ignored


def test_missing_required_field_means_the_data_is_gone() -> None:
    assert Sample.load({"request_id": "r-1", "paying": True}) is None
    assert Sample.load({}) is None


def test_optional_fields_default_to_none() -> None:
    form = Sample.load({"request_id": "r-1", "op_type": "loan_take", "paying": True})

    assert form == Sample(request_id="r-1", op_type=OperationType.LOAN_TAKE, paying=True)
