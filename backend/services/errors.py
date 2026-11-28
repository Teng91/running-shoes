"""Application errors translated by transport adapters."""


class DomainError(Exception):
    pass


class NotFound(DomainError):
    pass


class Invalid(DomainError):
    pass


class Unprocessable(DomainError):
    """A well-formed value that breaks a rule only the account can decide, such as its today (SPEC-147)."""


class Conflict(DomainError):
    pass


class Unauthorized(DomainError):
    pass


class CapacityExceeded(DomainError):
    pass
