"""Application errors translated by transport adapters."""


class DomainError(Exception):
    pass


class NotFound(DomainError):
    pass


class Invalid(DomainError):
    pass


class Conflict(DomainError):
    pass


class Unauthorized(DomainError):
    pass


class CapacityExceeded(DomainError):
    pass
