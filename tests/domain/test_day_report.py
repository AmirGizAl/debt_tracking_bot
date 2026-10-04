"""The day report and the surplus (TZ 8.1, 18: domain/day_report)."""

from decimal import Decimal

import pytest

from app.domain.currency import Currency
from app.domain.day_report import (
    NameLine,
    Obligation,
    ReportInputs,
    build_day_report,
    needed_rates,
    report_from_json,
    report_to_json,
)
from app.domain.errors import MissingRate

USD, EUR, RUB, KZT, KGS = Currency.USD, Currency.EUR, Currency.RUB, Currency.KZT, Currency.KGS
D = Decimal
BASELINE = {USD: D("10000"), KGS: D("1000000")}


def inputs(
    cash: dict[Currency, Decimal],
    exchange: list[Obligation] | None = None,
    loans: list[Obligation] | None = None,
    baseline: dict[Currency, Decimal] | None = None,
    debts: dict[Currency, Decimal] | None = None,
) -> ReportInputs:
    return ReportInputs(
        cash=cash,
        exchange=exchange or [],
        loans=loans or [],
        baseline=BASELINE if baseline is None else baseline,
        debts=debts or {},
    )


DAY_1 = inputs(
    {USD: D("10000"), RUB: D("88500"), KGS: D("951000")},
    exchange=[Obligation("Азамат", USD, D("-1000"))],
    loans=[Obligation("Бекзат", KGS, D("50000"))],
)


def test_control_example_of_the_spec() -> None:
    # TZ 8.6.
    report = build_day_report(DAY_1, {USD: D("87.65"), RUB: D("0.991")}, D("0"))

    lines = {line.currency: line for line in report.lines}
    usd, rub = lines[USD], lines[RUB]
    assert (usd.cash, usd.owed_to_us, usd.we_owe, usd.position, usd.kgs) == (
        D("10000"),
        0,
        D("1000"),
        D("9000"),
        D("788850"),
    )
    assert (rub.position, rub.rate, rub.kgs) == (D("88500"), D("0.991"), D("87703.50"))
    assert (lines[EUR].rate, lines[EUR].kgs) == (None, 0)
    assert report.cash_kgs == D("951000")
    assert report.loans_owed_to_us == [NameLine("Бекзат", D("50000"))]
    assert report.total == D("1877553.50")
    assert [(b.currency, b.base, b.kgs) for b in report.baseline] == [
        (USD, D("10000"), D("876500")),
        (KGS, D("1000000"), D("1000000")),
    ]
    assert report.baseline_total == D("1876500")
    assert report.surplus == D("1053.50")
    assert report.change == D("1053.50")  # the first day: the previous surplus is 0


def test_day_2_of_the_acceptance_scenarios() -> None:
    # TZ 17.1, scenario 11: Азамат got his 1 000 USD, 2 000 USD were bought for som.
    day_2 = inputs(
        {USD: D("11000"), RUB: D("88500"), KGS: D("776000")},
        loans=[Obligation("Бекзат", KGS, D("50000"))],
    )

    report = build_day_report(day_2, {USD: D("87.70"), RUB: D("0.99")}, D("1053.50"))

    assert report.total == D("1878315")
    assert report.baseline_total == D("1877000")
    assert report.surplus == D("1315")
    assert report.change == D("261.50")


@pytest.mark.parametrize("usd_rate", ["87.65", "1", "0.000001", "123456.789"])
def test_opening_balances_alone_make_no_surplus(usd_rate: str) -> None:
    only_openings = inputs({USD: D("10000"), KGS: D("1000000")})

    report = build_day_report(only_openings, {USD: D(usd_rate)}, D("0"))

    assert report.surplus == 0
    assert report.total == report.baseline_total


def test_som_of_exchanges_is_counted_without_the_cash() -> None:
    som = inputs(
        {KGS: D("1000000")},
        exchange=[
            Obligation("Азамат", KGS, D("5000")),
            Obligation("Бекзат", KGS, D("-2000")),
        ],
        baseline={KGS: D("1000000")},
    )

    report = build_day_report(som, {}, D("0"))

    kgs = report.lines[-1]
    assert (kgs.currency, kgs.cash, kgs.owed_to_us, kgs.we_owe, kgs.rate, kgs.kgs) == (
        KGS,
        None,
        D("5000"),
        D("2000"),
        D("1"),
        D("3000"),
    )
    assert report.currencies_total == D("3000")
    assert report.surplus == D("3000")


def test_rates_are_asked_only_when_needed() -> None:
    # EUR and KZT have neither a position nor an opening balance.
    assert needed_rates(DAY_1) == [USD, RUB]
    eur_obligations_cancel_out = inputs(
        {EUR: D("100")}, exchange=[Obligation("Азамат", EUR, D("-100"))], baseline={}
    )
    assert needed_rates(eur_obligations_cancel_out) == []
    assert needed_rates(inputs({}, baseline={KZT: D("5")})) == [KZT]

    report = build_day_report(DAY_1, {USD: D("87.65"), RUB: D("0.991"), EUR: D("100")}, D("0"))
    assert report.rates == {USD: D("87.65"), RUB: D("0.991")}  # an extra rate is ignored


def test_missing_rate_is_an_error() -> None:
    with pytest.raises(MissingRate) as error:
        build_day_report(DAY_1, {USD: D("87.65")}, D("0"))
    assert error.value.currency == RUB


def test_each_line_is_rounded_before_adding() -> None:
    halves = inputs({USD: D("0.01"), EUR: D("0.01")}, baseline={})

    report = build_day_report(halves, {USD: D("0.5"), EUR: D("0.5")}, D("0"))

    assert [line.kgs for line in report.lines[:2]] == [D("0.01"), D("0.01")]
    assert report.total == D("0.02")


def test_lists_by_name_go_from_the_largest() -> None:
    many = inputs(
        {},
        exchange=[
            Obligation("Азамат", USD, D("-1000")),
            Obligation("Бекзат", USD, D("-3000")),
            Obligation("Тимур", USD, D("500")),
            Obligation("Иван", RUB, D("700")),
        ],
        loans=[Obligation("Бекзат", KGS, D("10")), Obligation("Азамат", KGS, D("20"))],
        baseline={},
    )

    report = build_day_report(many, {USD: D("1"), RUB: D("1")}, D("0"))

    usd, rub = report.exchanges
    assert usd.we_owe == [NameLine("Бекзат", D("3000")), NameLine("Азамат", D("1000"))]
    assert usd.owed_to_us == [NameLine("Тимур", D("500"))]
    assert (rub.currency, rub.owed_to_us, rub.we_owe) == (RUB, [NameLine("Иван", D("700"))], [])
    assert report.loans_owed_to_us == [NameLine("Азамат", D("20")), NameLine("Бекзат", D("10"))]
    assert report.loans_owed_to_us_total == D("30")


def test_snapshot_round_trip() -> None:
    report = build_day_report(DAY_1, {USD: D("87.65"), RUB: D("0.991")}, D("0"))

    assert report_from_json(report_to_json(report)) == report


# --- opening debts (agreed with the customer on 03.10.2026) -----------------------------------

WITH_DEBTS = inputs(
    {USD: D("10000"), KGS: D("1000000")},
    exchange=[Obligation("Азамат", USD, D("1000")), Obligation("Тимур", RUB, D("-30000"))],
    loans=[Obligation("Бекзат", KGS, D("-20000"))],
    debts={USD: D("1000"), RUB: D("-30000"), KGS: D("-20000")},
)


@pytest.mark.parametrize(("usd", "rub"), [("87.65", "0.991"), ("1", "1"), ("123.456789", "2")])
def test_opening_debts_alone_make_no_surplus(usd: str, rub: str) -> None:
    report = build_day_report(WITH_DEBTS, {USD: D(usd), RUB: D(rub)}, D("0"))

    assert report.surplus == 0
    assert report.total == report.baseline_total


def test_the_starting_point_shows_the_opening_debts() -> None:
    report = build_day_report(WITH_DEBTS, {USD: D("87.65"), RUB: D("0.991")}, D("0"))

    assert [(b.currency, b.base, b.kgs) for b in report.baseline_debts] == [
        (USD, D("1000"), D("87650")),
        (RUB, D("-30000"), D("-29730")),
        (KGS, D("-20000"), D("-20000")),  # som of both books at rate 1
    ]
    assert report.baseline_total == D("876500") + D("1000000") + D("87650") - D("29730") - 20000


def test_paid_opening_debt_keeps_the_surplus() -> None:
    # Азамат paid his 1 000 USD from before the bot: the money replaces the debt.
    paid = inputs(
        {USD: D("11000"), KGS: D("1000000")},
        debts={USD: D("1000")},
    )

    report = build_day_report(paid, {USD: D("87.65")}, D("0"))

    assert report.surplus == 0


def test_a_currency_of_an_opening_debt_needs_a_rate() -> None:
    # The KZT debt is settled by now, but the starting point still counts it.
    settled = inputs({KZT: D("500")}, baseline={}, debts={KZT: D("500")})

    assert needed_rates(settled) == [KZT]
    with pytest.raises(MissingRate):
        build_day_report(settled, {}, D("0"))


def test_snapshot_keeps_the_opening_debts() -> None:
    report = build_day_report(WITH_DEBTS, {USD: D("87.65"), RUB: D("0.991")}, D("0"))
    old_snapshot = report_to_json(report)
    del old_snapshot["baseline_debts"]  # made before 03.10.2026

    assert report_from_json(report_to_json(report)) == report
    assert report_from_json(old_snapshot).baseline_debts == []
