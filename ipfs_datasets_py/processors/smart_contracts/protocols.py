"""Read-only, dependency-light protocols for smart-contract processors.

This module intentionally imports only the Python standard library and
package-local ``errors`` / ``models`` modules.  Importing it does not discover
plugins, resolve secrets, load optional dependencies, create clients, or
perform I/O.

**Acquisition is explicit and separately injected** from parsing and analysis.
:class:`ArtifactProvider` is the sole acquisition capability surface.
:class:`ContractParser` and :class:`ContractAnalyzer` are independent
protocols that must be constructed and injected separately.  A
:class:`SmartContractProcessor` may hold zero or more of these capabilities,
but acquisition never implies parse or analyze authority.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from types import MappingProxyType
from typing import Protocol, runtime_checkable

from .errors import (
    DeadlineExceededError,
    InvalidRequestError,
    OperationCancelledError,
    ResourceLimitError,
    SigningForbiddenError,
)
from .models import (
    ContractAcquisitionRequest,
    ContractAcquisitionResult,
)


def _positive_int(value: int, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise InvalidRequestError(f"{name} must be a positive integer")


class Capability(StrEnum):
    """Read-only features a provider or processor can explicitly advertise.

    Acquisition capabilities are distinct from parse and analyze so injection
    remains explicit and non-interchangeable.
    """

    # Acquisition lane (ArtifactProvider)
    ACQUIRE_BYTECODE = "acquire_bytecode"
    ACQUIRE_CREATION_BYTECODE = "acquire_creation_bytecode"
    ACQUIRE_PROGRAM = "acquire_program"
    ACQUIRE_SCRIPT = "acquire_script"
    ACQUIRE_SOURCE = "acquire_source"
    ACQUIRE_ABI = "acquire_abi"
    ACQUIRE_IDL = "acquire_idl"
    ACQUIRE_METADATA = "acquire_metadata"
    ACQUIRE_BUILD_MANIFEST = "acquire_build_manifest"
    ACQUIRE_VERIFICATION_DOCUMENT = "acquire_verification_document"
    ACQUIRE_STATE_SNAPSHOT = "acquire_state_snapshot"
    # Parse lane (ContractParser) — not acquisition
    PARSE_ARTIFACT = "parse_artifact"
    # Analyze lane (ContractAnalyzer) — not acquisition
    ANALYZE_ARTIFACT = "analyze_artifact"
    # Shared operational
    CAPABILITY_DISCOVERY = "capability_discovery"
    CODE_EPOCH = "code_epoch"
    FINALITY = "finality"


ACQUISITION_CAPABILITIES: frozenset[Capability] = frozenset(
    {
        Capability.ACQUIRE_BYTECODE,
        Capability.ACQUIRE_CREATION_BYTECODE,
        Capability.ACQUIRE_PROGRAM,
        Capability.ACQUIRE_SCRIPT,
        Capability.ACQUIRE_SOURCE,
        Capability.ACQUIRE_ABI,
        Capability.ACQUIRE_IDL,
        Capability.ACQUIRE_METADATA,
        Capability.ACQUIRE_BUILD_MANIFEST,
        Capability.ACQUIRE_VERIFICATION_DOCUMENT,
        Capability.ACQUIRE_STATE_SNAPSHOT,
    }
)

PARSE_CAPABILITIES: frozenset[Capability] = frozenset({Capability.PARSE_ARTIFACT})
ANALYZE_CAPABILITIES: frozenset[Capability] = frozenset(
    {Capability.ANALYZE_ARTIFACT}
)


@dataclass(frozen=True, slots=True)
class Capabilities:
    """Immutable, inspectable capabilities for a concrete implementation."""

    provider: str
    chain_namespaces: frozenset[str] = field(default_factory=frozenset)
    features: frozenset[Capability] = field(default_factory=frozenset)
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.provider.strip():
            raise InvalidRequestError("provider must not be empty")
        if any(not namespace.strip() for namespace in self.chain_namespaces):
            raise InvalidRequestError("chain namespaces must not be empty")
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))

    def supports(self, capability: Capability) -> bool:
        """Return whether *capability* was explicitly advertised."""

        return capability in self.features

    def acquisition_features(self) -> frozenset[Capability]:
        """Return only acquisition-lane capabilities."""

        return frozenset(self.features & ACQUISITION_CAPABILITIES)

    def parse_features(self) -> frozenset[Capability]:
        """Return only parse-lane capabilities."""

        return frozenset(self.features & PARSE_CAPABILITIES)

    def analyze_features(self) -> frozenset[Capability]:
        """Return only analyze-lane capabilities."""

        return frozenset(self.features & ANALYZE_CAPABILITIES)


@dataclass(frozen=True, slots=True)
class RequestLimits:
    """Hard per-operation limits; all values are required and finite."""

    max_items: int = 64
    max_requests: int = 32
    max_response_bytes: int = 16 * 1024 * 1024
    max_depth: int = 8

    def __post_init__(self) -> None:
        _positive_int(self.max_items, "max_items")
        _positive_int(self.max_requests, "max_requests")
        _positive_int(self.max_response_bytes, "max_response_bytes")
        _positive_int(self.max_depth, "max_depth")


@runtime_checkable
class CancellationToken(Protocol):
    """Minimal cooperative-cancellation signal supplied by the caller."""

    @property
    def cancelled(self) -> bool:
        """Whether the caller has requested cancellation."""

        ...


@dataclass(frozen=True, slots=True)
class OperationContext:
    """Cancellation, deadline, and resource budget for one operation."""

    request_id: str
    limits: RequestLimits = field(default_factory=RequestLimits)
    deadline: datetime | None = None
    cancellation: CancellationToken | None = None

    def __post_init__(self) -> None:
        if not self.request_id.strip():
            raise InvalidRequestError("request_id must not be empty")
        if self.deadline is not None:
            if self.deadline.tzinfo is None or self.deadline.utcoffset() is None:
                raise InvalidRequestError("deadline must be timezone-aware")

    def remaining_seconds(
        self,
        *,
        now: Callable[[], datetime] | None = None,
    ) -> float | None:
        """Return the non-negative deadline budget, or ``None`` if unlimited."""

        if self.deadline is None:
            return None
        current = (now or (lambda: datetime.now(timezone.utc)))()
        if current.tzinfo is None or current.utcoffset() is None:
            raise InvalidRequestError("clock must return a timezone-aware datetime")
        return max(0.0, (self.deadline - current).total_seconds())

    def check_active(
        self,
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        """Fail before I/O if cancellation or the deadline forbids more work."""

        if self.cancellation is not None and self.cancellation.cancelled:
            raise OperationCancelledError(
                f"operation {self.request_id!r} was cancelled"
            )
        remaining = self.remaining_seconds(now=now)
        if remaining is not None and remaining <= 0:
            raise DeadlineExceededError(
                f"operation {self.request_id!r} exceeded its deadline"
            )


@dataclass(frozen=True, slots=True)
class ParsedArtifact:
    """Opaque parse product; never elevates acquisition authority."""

    artifact_digest: str
    representation: str
    payload: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.artifact_digest.strip():
            raise InvalidRequestError("artifact_digest must not be empty")
        if not self.representation.strip():
            raise InvalidRequestError("representation must not be empty")
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))


@dataclass(frozen=True, slots=True)
class AnalysisReceipt:
    """Opaque analysis product; never elevates acquisition authority."""

    subject_digest: str
    verdict: str
    notes: tuple[str, ...] = ()
    payload: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.subject_digest.strip():
            raise InvalidRequestError("subject_digest must not be empty")
        if not self.verdict.strip():
            raise InvalidRequestError("verdict must not be empty")
        object.__setattr__(self, "notes", tuple(self.notes))
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))


@runtime_checkable
class ArtifactProvider(Protocol):
    """Bounded, read-only acquisition capability for contract artifacts.

    Implementations must not parse or analyze artifacts unless those
    capabilities are separately injected elsewhere.  This protocol is the
    sole acquisition SPI.
    """

    @property
    def capabilities(self) -> Capabilities:
        """Read-only provider capability declaration (acquisition lane)."""

        ...

    async def acquire(
        self,
        request: ContractAcquisitionRequest,
        *,
        context: OperationContext,
    ) -> ContractAcquisitionResult:
        """Acquire artifacts under the request bounds and provider policy."""

        ...


@runtime_checkable
class ContractParser(Protocol):
    """Pure parse capability; separately injected from acquisition."""

    @property
    def capabilities(self) -> Capabilities:
        """Parse-lane capability declaration."""

        ...

    def parse(
        self,
        artifacts: Sequence[object],
        *,
        context: OperationContext,
    ) -> Sequence[ParsedArtifact]:
        """Parse a bounded artifact batch without performing network I/O."""

        ...


@runtime_checkable
class ContractAnalyzer(Protocol):
    """Analysis capability; separately injected from acquisition and parsing."""

    @property
    def capabilities(self) -> Capabilities:
        """Analyze-lane capability declaration."""

        ...

    def analyze(
        self,
        subjects: Sequence[object],
        *,
        context: OperationContext,
    ) -> Sequence[AnalysisReceipt]:
        """Analyze a bounded subject batch without performing network I/O."""

        ...


@runtime_checkable
class SmartContractProcessor(Protocol):
    """Top-level processor with explicitly injected capability lanes.

    Acquisition, parsing, and analysis are non-interchangeable.  A processor
    may expose acquisition alone; parse/analyze remain optional and are never
    implied by acquisition capability advertisement.
    """

    @property
    def capabilities(self) -> Capabilities:
        """Aggregate declared capabilities across injected lanes."""

        ...

    @property
    def artifact_provider(self) -> ArtifactProvider | None:
        """Injected acquisition capability, or ``None`` if not configured."""

        ...

    @property
    def parser(self) -> ContractParser | None:
        """Injected parse capability, or ``None`` if not configured."""

        ...

    @property
    def analyzer(self) -> ContractAnalyzer | None:
        """Injected analyze capability, or ``None`` if not configured."""

        ...

    async def acquire(
        self,
        request: ContractAcquisitionRequest,
        *,
        context: OperationContext,
    ) -> ContractAcquisitionResult:
        """Delegate to the injected :class:`ArtifactProvider` only."""

        ...


def enforce_batch_limits(
    *,
    item_count: int,
    response_bytes: int,
    limits: RequestLimits,
) -> None:
    """Raise when a batch alone violates the declared operation limits."""

    if item_count > limits.max_items:
        raise ResourceLimitError(
            f"batch contains {item_count} items; limit is {limits.max_items}"
        )
    if response_bytes > limits.max_response_bytes:
        raise ResourceLimitError("batch response bytes exceed max_response_bytes")


def reject_signing_surface(name: str) -> None:
    """Fail closed if a caller attempts to attach a signing/broadcast surface."""

    raise SigningForbiddenError(
        f"smart-contract processor forbids signing surface {name!r}"
    )


__all__ = [
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
