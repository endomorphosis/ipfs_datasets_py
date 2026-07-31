"""Dependency-free exceptions shared by smart-contract processor boundaries.

Exception messages in this module are deliberately safe for logs.  Callers must
never include a resolved secret, private key, or signing material in an
exception message.
"""

from __future__ import annotations


class SmartContractProcessorError(Exception):
    """Base class for failures at a smart-contract processor boundary."""


class InvalidRequestError(SmartContractProcessorError, ValueError):
    """A request is malformed or is not explicitly bounded."""


class UnsupportedCapabilityError(SmartContractProcessorError):
    """A provider or processor cannot perform a requested operation."""


class OperationCancelledError(SmartContractProcessorError):
    """Cooperative cancellation was requested."""


class DeadlineExceededError(SmartContractProcessorError, TimeoutError):
    """An operation attempted work after its deadline."""


class ResourceLimitError(SmartContractProcessorError):
    """A response or operation exceeded a declared resource bound."""


class ProviderError(SmartContractProcessorError):
    """A read-only artifact provider failed."""


class AcquisitionError(SmartContractProcessorError):
    """Bounded artifact acquisition failed without a structured result."""


class ArtifactUnavailableError(AcquisitionError):
    """The requested artifact could not be located."""


class ArtifactInconsistentError(AcquisitionError):
    """Providers disagree or artifact components conflict."""


class ArtifactPoisonedError(AcquisitionError):
    """Artifact bytes or provenance failed integrity checks."""


class ArtifactStaleError(AcquisitionError):
    """Artifact evidence is older than the request freshness policy."""


class SigningForbiddenError(SmartContractProcessorError):
    """Signing, private-key, or broadcast surfaces are forbidden on this boundary."""


class SecretResolutionError(SmartContractProcessorError):
    """A secret reference could not be resolved without exposing its value."""


__all__ = [
    "AcquisitionError",
    "ArtifactInconsistentError",
    "ArtifactPoisonedError",
    "ArtifactStaleError",
    "ArtifactUnavailableError",
    "DeadlineExceededError",
    "InvalidRequestError",
    "OperationCancelledError",
    "ProviderError",
    "ResourceLimitError",
    "SecretResolutionError",
    "SigningForbiddenError",
    "SmartContractProcessorError",
    "UnsupportedCapabilityError",
]
