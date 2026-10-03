"""Domain exceptions. Services raise them, bot handlers translate them into texts (TZ 15.1)."""

from decimal import Decimal
from enum import StrEnum

from app.domain.currency import Currency


class DomainError(Exception):
    """Base class for expected business-rule violations."""


class NotFound(DomainError):
    pass


class PermissionDenied(DomainError):
    pass


# --- input -----------------------------------------------------------------------------------


class NumberProblem(StrEnum):
    FORMAT = "format"
    PRECISION = "precision"
    NOT_POSITIVE = "not_positive"
    TOO_LARGE = "too_large"


class InvalidNumber(DomainError):
    def __init__(self, problem: NumberProblem) -> None:
        super().__init__(problem.value)
        self.problem = problem


class ConversionProblem(StrEnum):
    ZERO = "zero"
    TOO_LARGE = "too_large"


class InvalidConversion(DomainError):
    """Payment converted at the given rate gives 0 (or more than the maximum) of the debt."""

    def __init__(self, problem: ConversionProblem) -> None:
        super().__init__(problem.value)
        self.problem = problem


class TextTooLong(DomainError):
    def __init__(self, limit: int) -> None:
        super().__init__(f"longer than {limit}")
        self.limit = limit


class EmptyText(DomainError):
    pass


class InvalidDate(DomainError):
    """Not a date in the format ДД.ММ.ГГГГ, or no such day (31.02)."""


# --- users -----------------------------------------------------------------------------------


class InvalidUsername(DomainError):
    pass


class UsernameAlreadyAdded(DomainError):
    pass


class CannotDeleteOwner(DomainError):
    pass


class UserNotFound(NotFound):
    pass


# --- clients ---------------------------------------------------------------------------------


class InvalidClientName(DomainError):
    def __init__(self, too_long: bool) -> None:
        super().__init__("too long" if too_long else "empty")
        self.too_long = too_long


class DuplicateClientName(DomainError):
    def __init__(self, existing_name: str) -> None:
        super().__init__(existing_name)
        self.existing_name = existing_name


class ClientHasOperations(DomainError):
    pass


class ClientNotFound(NotFound):
    pass


# --- records (TZ 6, 9, 11) ---------------------------------------------------------------------


class InvalidOperationData(DomainError):
    """A record that breaks the rules of its type; the bot never builds one."""


class ClientRequired(DomainError):
    """A record with a part to be settled later needs a client (TZ 6.4)."""


class NothingToExchange(DomainError):
    """One currency, the same amount, both sides now: nothing happens (TZ 6.4)."""


class InsufficientBalance(DomainError):
    """The record would take a balance below zero (TZ 6.5)."""

    def __init__(self, currency: Currency, available: Decimal, required: Decimal) -> None:
        super().__init__(f"{currency}: available {available}, required {required}")
        self.currency = currency
        self.available = available
        self.required = required


class BaselineFrozen(DomainError):
    """Opening balances change only before the first closing of a day (TZ 9)."""


class OpeningExists(DomainError):
    """The currency already has an opening balance that is not cancelled (02.10.2026)."""

    def __init__(self, currency: Currency) -> None:
        super().__init__(str(currency))
        self.currency = currency


class OperationNotFound(NotFound):
    pass


class AlreadyReversed(DomainError):
    pass


class CannotReverseReason(StrEnum):
    REVERSAL = "reversal"  # a cancellation itself
    ADJUSTMENT = "adjustment"  # corrected by a counter-adjustment instead (TZ 10)


class CannotReverse(DomainError):
    def __init__(self, reason: CannotReverseReason) -> None:
        super().__init__(reason.value)
        self.reason = reason


class DayNotFound(NotFound):
    pass


class DayAlreadyClosed(DomainError):
    """Somebody closed this day first (TZ 7.2)."""


class MissingRate(DomainError):
    """A currency of the day report has no rate (TZ 8.2)."""

    def __init__(self, currency: Currency) -> None:
        super().__init__(str(currency))
        self.currency = currency
