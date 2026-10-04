"""Exceptions for the data wallet package."""


class DataWalletError(Exception):
    """Base exception for data wallet failures."""


class AccessDeniedError(DataWalletError):
    """Raised when a principal is not authorized for a wallet operation."""


class ApprovalRequiredError(AccessDeniedError):
    """Raised when a wallet operation requires threshold approval."""


class DecryptionError(DataWalletError):
    """Raised when encrypted wallet data cannot be decrypted."""


class GrantError(DataWalletError):
    """Raised when a grant cannot be created or used."""


class MissingRecordError(DataWalletError):
    """Raised when a requested wallet record does not exist."""
