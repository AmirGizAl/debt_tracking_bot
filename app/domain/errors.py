"""Domain exceptions. Services raise them, bot handlers translate them into texts."""


class DomainError(Exception):
    """Base class for expected business-rule violations."""


class PermissionDenied(DomainError):
    pass


class NotFound(DomainError):
    pass
