"""Exceptions for document wallet operations."""

from __future__ import annotations


class DocumentWalletError(Exception):
    """Base class for document wallet failures."""


class WalletNotFoundError(DocumentWalletError):
    """Raised when a wallet cannot be found."""


class DocumentNotFoundError(DocumentWalletError):
    """Raised when a document cannot be found."""


class AuthorizationError(DocumentWalletError):
    """Raised when a principal is not allowed to perform an operation."""


class KeyUnwrapError(DocumentWalletError):
    """Raised when no usable document key can be unwrapped."""


class StorageError(DocumentWalletError):
    """Raised when a storage adapter cannot complete an operation."""


class ManifestIntegrityError(DocumentWalletError):
    """Raised when manifest or payload integrity checks fail."""

