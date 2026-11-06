class DomainError(Exception):
    """Base for expected business errors (safe to show to users in a friendly form)."""


class InsufficientFunds(DomainError):
    pass


class NoFreeAmount(DomainError):
    pass


class AlreadyReviewed(DomainError):
    pass


class NotFound(DomainError):
    pass
