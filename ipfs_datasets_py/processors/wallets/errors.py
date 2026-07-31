"""Dependency-free exceptions shared by wallet processor boundaries.

Exception messages in this module are deliberately safe for logs.  In
particular, callers must never include a resolved secret in an exception.
"""

from __future__ import annotations


class WalletProcessorError(Exception):
    """Base class for failures at a wallet processor boundary."""


class InvalidRequestError(WalletProcessorError, ValueError):
    """A request is malformed or is not explicitly bounded."""


class UnsupportedCapabilityError(WalletProcessorError):
    """A provider cannot perform a requested read operation."""


class OperationCancelledError(WalletProcessorError):
    """Cooperative cancellation was requested."""


class DeadlineExceededError(WalletProcessorError, TimeoutError):
    """An operation attempted work after its deadline."""


class ResourceLimitError(WalletProcessorError):
    """A response or operation exceeded a declared resource bound."""


class ProviderError(WalletProcessorError):
    """A read-only wallet or ledger provider failed."""


class NormalizationError(WalletProcessorError):
    """A chain-native value could not be normalized safely."""


class CheckpointError(WalletProcessorError):
    """A checkpoint load or compare-and-set operation failed."""


class DatasetSinkError(WalletProcessorError):
    """A dataset write, commit, or abort operation failed."""


class ExportError(WalletProcessorError):
    """A bounded wallet data export failed."""


class SecretResolutionError(WalletProcessorError):
    """A secret reference could not be resolved without exposing its value."""


__all__ = [
    "CheckpointError",
    "DatasetSinkError",
    "DeadlineExceededError",
    "ExportError",
    "InvalidRequestError",
    "NormalizationError",
    "OperationCancelledError",
    "ProviderError",
    "ResourceLimitError",
    "SecretResolutionError",
    "UnsupportedCapabilityError",
    "WalletProcessorError",
]
