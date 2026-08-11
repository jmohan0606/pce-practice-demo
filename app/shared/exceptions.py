class AppError(Exception):
    """Base class for all application-raised errors (renamed from V2's IPerformError)."""


class ConfigurationError(AppError):
    pass


class ExternalServiceError(AppError):
    pass


class ValidationError(AppError):
    pass


class NotFoundError(AppError):
    pass


class IngestionCheckpointError(AppError):
    pass
