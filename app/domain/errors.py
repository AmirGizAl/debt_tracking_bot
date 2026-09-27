"""Domain exceptions. Services raise them, bot handlers translate them into texts (TZ 14.1)."""

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


class InvalidDate(DomainError):
    pass


class FutureDate(DomainError):
    pass


class TextTooLong(DomainError):
    def __init__(self, limit: int) -> None:
        super().__init__(f"longer than {limit}")
        self.limit = limit


class EmptyText(DomainError):
    pass


class InvalidOperationData(DomainError):
    """A draft that breaks the record rules (should never come from the bot UI)."""


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


# --- money -----------------------------------------------------------------------------------


class InsufficientCash(DomainError):
    def __init__(self, currency: Currency, available: Decimal, required: Decimal) -> None:
        super().__init__(f"{currency}: available {available}, required {required}")
        self.currency = currency
        self.available = available
        self.required = required


class OperationNotFound(NotFound):
    pass


class AlreadyReversed(DomainError):
    pass


class CannotReverseReversal(DomainError):
    pass
