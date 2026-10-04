"""The day report and the surplus (TZ 8.1, 8.4). A pure function: numbers in, report out.

For each of USD, EUR, RUB, KZT:  pos(c) = cash(c) + rec(c) − pay(c),  kgs(c) = round(pos × rate)
KGS of exchanges:               pos_kgs = rec(KGS) − pay(KGS)   (without the som cash, rate 1)
Total    = Σ kgs(c) + pos_kgs + cash(KGS) + loans owed to us − loans we owe
Baseline = Σ round(base(c) × rate(c)) + base(KGS)        (the same rates as the report)
         + Σ round(debt(c) × rate(c)) + debt(KGS)        (opening debts, agreed on 03.10.2026)
Surplus  = Total − Baseline;  Change = Surplus − Surplus of the previous closed day.

An opening debt enters both the total (through the obligations) and the baseline, so on its
own it never shows as a surplus, like an opening balance.
"""

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal, localcontext
from typing import Any

from app.domain.currency import FOREIGN_CURRENCIES, HOME_CURRENCY, Currency
from app.domain.errors import MissingRate
from app.domain.money import CENT

ZERO = Decimal("0.00")
_PRECISION = 60  # one rounding to cents, as in rates.convert


def _to_kgs(amount: Decimal, rate: Decimal) -> Decimal:
    with localcontext() as context:
        context.prec = _PRECISION
        return (amount * rate).quantize(CENT, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class Obligation:
    """One client's obligation in one currency: above zero the client owes us."""

    client: str
    currency: Currency
    amount: Decimal


@dataclass(frozen=True)
class ReportInputs:
    cash: Mapping[Currency, Decimal]
    exchange: Sequence[Obligation]  # book `exchange`, any currency
    loans: Sequence[Obligation]  # book `loan`, KGS
    baseline: Mapping[Currency, Decimal]
    # Opening debts of both books by currency: above zero the clients owe us (03.10.2026).
    debts: Mapping[Currency, Decimal] = field(default_factory=dict)


@dataclass(frozen=True)
class CurrencyLine:
    """A row of block 1. `cash` is None for «KGS (обмены)»; `rate` is None if not needed."""

    currency: Currency
    cash: Decimal | None
    owed_to_us: Decimal
    we_owe: Decimal
    position: Decimal
    rate: Decimal | None
    kgs: Decimal


@dataclass(frozen=True)
class NameLine:
    name: str
    amount: Decimal


@dataclass(frozen=True)
class BaselineLine:
    currency: Currency
    base: Decimal
    rate: Decimal
    kgs: Decimal


@dataclass(frozen=True)
class ExchangeList:
    """Block 5 for one currency: who owes us and whom we owe, largest first."""

    currency: Currency
    owed_to_us: list[NameLine]
    we_owe: list[NameLine]


@dataclass(frozen=True)
class DayReport:
    lines: list[CurrencyLine]  # USD, EUR, RUB, KZT, then «KGS (обмены)»
    currencies_total: Decimal  # «Итого по валютам»
    cash_kgs: Decimal  # block 2, «Наличка»
    loans_owed_to_us: list[NameLine]
    loans_we_owe: list[NameLine]
    total: Decimal
    baseline: list[BaselineLine]
    baseline_total: Decimal
    surplus: Decimal
    change: Decimal
    exchanges: list[ExchangeList]
    rates: dict[Currency, Decimal]
    baseline_debts: list[BaselineLine] = field(default_factory=list)  # a part of the baseline

    @property
    def loans_owed_to_us_total(self) -> Decimal:
        return sum((line.amount for line in self.loans_owed_to_us), ZERO)

    @property
    def loans_we_owe_total(self) -> Decimal:
        return sum((line.amount for line in self.loans_we_owe), ZERO)


def _split(obligations: Sequence[Obligation]) -> dict[Currency, tuple[Decimal, Decimal]]:
    """rec(c) and pay(c): sums of positive obligations and of the moduli of negative ones."""
    owed: dict[Currency, Decimal] = defaultdict(lambda: ZERO)
    owing: dict[Currency, Decimal] = defaultdict(lambda: ZERO)
    for item in obligations:
        if item.amount > 0:
            owed[item.currency] += item.amount
        else:
            owing[item.currency] -= item.amount
    return {c: (owed[c], owing[c]) for c in set(owed) | set(owing)}


def _names(obligations: Sequence[Obligation], positive: bool) -> list[NameLine]:
    lines = [
        NameLine(item.client, item.amount if positive else -item.amount)
        for item in obligations
        if (item.amount > 0) == positive and item.amount != 0
    ]
    return sorted(lines, key=lambda line: (-line.amount, line.name))


def needed_rates(inputs: ReportInputs) -> list[Currency]:
    """TZ 8.2: a rate is asked for every currency with pos(c) ≠ 0 or base(c) ≠ 0, and for the
    currencies of opening debts (03.10.2026): every line of the baseline needs its rate."""
    split = _split(inputs.exchange)
    result = []
    for currency in FOREIGN_CURRENCIES:
        rec, pay = split.get(currency, (ZERO, ZERO))
        position = inputs.cash.get(currency, ZERO) + rec - pay
        base = inputs.baseline.get(currency, ZERO)
        debt = inputs.debts.get(currency, ZERO)
        if position != 0 or base != 0 or debt != 0:
            result.append(currency)
    return result


def build_day_report(
    inputs: ReportInputs, rates: Mapping[Currency, Decimal], previous_surplus: Decimal
) -> DayReport:
    """Raises MissingRate if a needed rate is not given; other rates are ignored."""
    needed = needed_rates(inputs)
    for currency in needed:
        if rates.get(currency) is None or rates[currency] <= 0:
            raise MissingRate(currency)
    split = _split(inputs.exchange)

    lines = []
    for currency in FOREIGN_CURRENCIES:
        rec, pay = split.get(currency, (ZERO, ZERO))
        cash = inputs.cash.get(currency, ZERO)
        position = cash + rec - pay
        rate = rates[currency] if currency in needed else None
        kgs = _to_kgs(position, rate) if rate is not None else ZERO
        lines.append(CurrencyLine(currency, cash, rec, pay, position, rate, kgs))
    rec_kgs, pay_kgs = split.get(HOME_CURRENCY, (ZERO, ZERO))
    position_kgs = rec_kgs - pay_kgs
    lines.append(
        CurrencyLine(HOME_CURRENCY, None, rec_kgs, pay_kgs, position_kgs, Decimal(1), position_kgs)
    )
    currencies_total = sum((line.kgs for line in lines), ZERO)

    cash_kgs = inputs.cash.get(HOME_CURRENCY, ZERO)
    loans_owed_to_us = _names(inputs.loans, positive=True)
    loans_we_owe = _names(inputs.loans, positive=False)
    loan_rec = sum((line.amount for line in loans_owed_to_us), ZERO)
    loan_pay = sum((line.amount for line in loans_we_owe), ZERO)
    total = currencies_total + cash_kgs + loan_rec - loan_pay

    baseline = [
        BaselineLine(c, inputs.baseline[c], rates[c], _to_kgs(inputs.baseline[c], rates[c]))
        for c in FOREIGN_CURRENCIES
        if inputs.baseline.get(c, ZERO) != 0
    ]
    base_kgs = inputs.baseline.get(HOME_CURRENCY, ZERO)
    if base_kgs != 0:
        baseline.append(BaselineLine(HOME_CURRENCY, base_kgs, Decimal(1), base_kgs))
    debts = [
        BaselineLine(c, inputs.debts[c], rates[c], _to_kgs(inputs.debts[c], rates[c]))
        for c in FOREIGN_CURRENCIES
        if inputs.debts.get(c, ZERO) != 0
    ]
    debt_kgs = inputs.debts.get(HOME_CURRENCY, ZERO)
    if debt_kgs != 0:
        debts.append(BaselineLine(HOME_CURRENCY, debt_kgs, Decimal(1), debt_kgs))
    baseline_total = sum((line.kgs for line in [*baseline, *debts]), ZERO)
    surplus = total - baseline_total

    exchanges = []
    for currency in (*FOREIGN_CURRENCIES, HOME_CURRENCY):
        items = [item for item in inputs.exchange if item.currency == currency]
        owed, owing = _names(items, positive=True), _names(items, positive=False)
        if owed or owing:
            exchanges.append(ExchangeList(currency, owed, owing))

    return DayReport(
        lines=lines,
        currencies_total=currencies_total,
        cash_kgs=cash_kgs,
        loans_owed_to_us=loans_owed_to_us,
        loans_we_owe=loans_we_owe,
        total=total,
        baseline=baseline,
        baseline_total=baseline_total,
        surplus=surplus,
        change=surplus - previous_surplus,
        exchanges=exchanges,
        rates={c: rates[c] for c in needed},
        baseline_debts=debts,
    )


# --- the snapshot of a closed day (JSONB, TZ 8.5) -----------------------------------------------


def _money(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


def _dec(value: str | None) -> Decimal | None:
    return None if value is None else Decimal(value)


def _names_json(lines: list[NameLine]) -> list[dict[str, str]]:
    return [{"name": line.name, "amount": str(line.amount)} for line in lines]


def _names_from(data: list[dict[str, str]]) -> list[NameLine]:
    return [NameLine(item["name"], Decimal(item["amount"])) for item in data]


def _baseline_json(lines: list[BaselineLine]) -> list[dict[str, str]]:
    return [
        {
            "currency": str(line.currency),
            "base": str(line.base),
            "rate": str(line.rate),
            "kgs": str(line.kgs),
        }
        for line in lines
    ]


def _baseline_from(data: list[dict[str, str]]) -> list[BaselineLine]:
    return [
        BaselineLine(
            Currency(line["currency"]),
            Decimal(line["base"]),
            Decimal(line["rate"]),
            Decimal(line["kgs"]),
        )
        for line in data
    ]


def report_to_json(report: DayReport) -> dict[str, Any]:
    """Decimals as strings: JSON numbers would lose the exact cents."""
    return {
        "lines": [
            {
                "currency": str(line.currency),
                "cash": _money(line.cash),
                "owed_to_us": str(line.owed_to_us),
                "we_owe": str(line.we_owe),
                "position": str(line.position),
                "rate": _money(line.rate),
                "kgs": str(line.kgs),
            }
            for line in report.lines
        ],
        "currencies_total": str(report.currencies_total),
        "cash_kgs": str(report.cash_kgs),
        "loans_owed_to_us": _names_json(report.loans_owed_to_us),
        "loans_we_owe": _names_json(report.loans_we_owe),
        "total": str(report.total),
        "baseline": _baseline_json(report.baseline),
        "baseline_debts": _baseline_json(report.baseline_debts),
        "baseline_total": str(report.baseline_total),
        "surplus": str(report.surplus),
        "change": str(report.change),
        "exchanges": [
            {
                "currency": str(item.currency),
                "owed_to_us": _names_json(item.owed_to_us),
                "we_owe": _names_json(item.we_owe),
            }
            for item in report.exchanges
        ],
        "rates": {str(c): str(rate) for c, rate in report.rates.items()},
    }


def report_from_json(data: Mapping[str, Any]) -> DayReport:
    return DayReport(
        lines=[
            CurrencyLine(
                currency=Currency(line["currency"]),
                cash=_dec(line["cash"]),
                owed_to_us=Decimal(line["owed_to_us"]),
                we_owe=Decimal(line["we_owe"]),
                position=Decimal(line["position"]),
                rate=_dec(line["rate"]),
                kgs=Decimal(line["kgs"]),
            )
            for line in data["lines"]
        ],
        currencies_total=Decimal(data["currencies_total"]),
        cash_kgs=Decimal(data["cash_kgs"]),
        loans_owed_to_us=_names_from(data["loans_owed_to_us"]),
        loans_we_owe=_names_from(data["loans_we_owe"]),
        total=Decimal(data["total"]),
        baseline=_baseline_from(data["baseline"]),
        baseline_total=Decimal(data["baseline_total"]),
        surplus=Decimal(data["surplus"]),
        change=Decimal(data["change"]),
        exchanges=[
            ExchangeList(
                Currency(item["currency"]),
                _names_from(item["owed_to_us"]),
                _names_from(item["we_owe"]),
            )
            for item in data["exchanges"]
        ],
        rates={Currency(c): Decimal(rate) for c, rate in data["rates"].items()},
        # Snapshots made before 03.10.2026 have no opening debts.
        baseline_debts=_baseline_from(data.get("baseline_debts", [])),
    )
