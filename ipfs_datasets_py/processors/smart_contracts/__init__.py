"""Bounded smart-contract processor core (CRYPTOIR-G200).

Importing this package does **not**:

* open network sockets;
* resolve secrets;
* auto-install dependencies;
* register live artifact providers; or
* expose private-key, signing, or broadcast surfaces.

Acquisition capability is explicit and separately injected from parsing and
analysis via :class:`ArtifactProvider`, :class:`ContractParser`, and
:class:`ContractAnalyzer`.
"""

from __future__ import annotations

from .canonical import (
    CANONICAL_IDENTITY_VERSION,
    CanonicalEncodingError,
    canonical_json,
    canonical_json_bytes,
    content_digest,
    deterministic_id,
    format_datetime,
    freeze_json,
    thaw_json,
)
from .errors import (
    AcquisitionError,
    ArtifactInconsistentError,
    ArtifactPoisonedError,
    ArtifactStaleError,
    ArtifactUnavailableError,
    DeadlineExceededError,
    InvalidRequestError,
    OperationCancelledError,
    ProviderError,
    ResourceLimitError,
    SecretResolutionError,
    SigningForbiddenError,
    SmartContractProcessorError,
    UnsupportedCapabilityError,
)
from .models import (
    ACQUISITION_REQUEST_SCHEMA_VERSION,
    ACQUISITION_RESULT_SCHEMA_VERSION,
    ARTIFACT_REF_SCHEMA_VERSION,
    CHAIN_REF_SCHEMA_VERSION,
    AcquisitionBounds,
    AcquisitionProvenance,
    AcquisitionStatus,
    ArtifactKind,
    ArtifactRef,
    ChainRef,
    ContractAcquisitionRequest,
    ContractAcquisitionResult,
    ProviderPolicy,
    ProviderTrustMode,
    assert_no_signing_surface,
    ensure_secret_safe,
    error_result,
    unavailable_result,
)
from .protocols import (
    ACQUISITION_CAPABILITIES,
    ANALYZE_CAPABILITIES,
    PARSE_CAPABILITIES,
    AnalysisReceipt,
    ArtifactProvider,
    CancellationToken,
    Capabilities,
    Capability,
    ContractAnalyzer,
    ContractParser,
    OperationContext,
    ParsedArtifact,
    RequestLimits,
    SmartContractProcessor,
    enforce_batch_limits,
    reject_signing_surface,
)

__all__ = [
    # Canonical
    "CANONICAL_IDENTITY_VERSION",
    "CanonicalEncodingError",
    "canonical_json",
    "canonical_json_bytes",
    "content_digest",
    "deterministic_id",
    "format_datetime",
    "freeze_json",
    "thaw_json",
    # Errors
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
    # Models
    "ACQUISITION_REQUEST_SCHEMA_VERSION",
    "ACQUISITION_RESULT_SCHEMA_VERSION",
    "ARTIFACT_REF_SCHEMA_VERSION",
    "CHAIN_REF_SCHEMA_VERSION",
    "AcquisitionBounds",
    "AcquisitionProvenance",
    "AcquisitionStatus",
    "ArtifactKind",
    "ArtifactRef",
    "ChainRef",
    "ContractAcquisitionRequest",
    "ContractAcquisitionResult",
    "ProviderPolicy",
    "ProviderTrustMode",
    "assert_no_signing_surface",
    "ensure_secret_safe",
    "error_result",
    "unavailable_result",
    # Protocols
    "ACQUISITION_CAPABILITIES",
    "ANALYZE_CAPABILITIES",
    "PARSE_CAPABILITIES",
    "AnalysisReceipt",
    "ArtifactProvider",
    "CancellationToken",
    "Capabilities",
    "Capability",
    "ContractAnalyzer",
    "ContractParser",
    "OperationContext",
    "ParsedArtifact",
    "RequestLimits",
    "SmartContractProcessor",
    "enforce_batch_limits",
    "reject_signing_surface",
]
