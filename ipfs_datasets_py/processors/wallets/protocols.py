"""Read-only, dependency-light contracts for wallet and public-ledger data.

This module intentionally imports only the Python standard library and
``wallets.errors``.  Importing it does not discover plugins, resolve secrets,
load optional dependencies, create clients, or perform I/O.

The protocols use opaque ``object`` records so the versioned domain models can
evolve independently.  Concrete implementations should narrow those types in
their own signatures and are expected to enforce :class:`RequestLimits` at
every I/O boundary.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Mapping, Sequence
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
)


def _positive_int(value: int, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise InvalidRequestError(f"{name} must be a positive integer")


class Capability(StrEnum):
    """Read-only features a provider or processor can explicitly advertise."""

    WALLET_HISTORY = "wallet_history"
    LEDGER_RANGE = "ledger_range"
    BALANCES = "balances"
    TOKEN_TRANSFERS = "token_transfers"
    CONTRACT_EVENTS = "contract_events"
    INTERNAL_TRANSFERS = "internal_transfers"
    RAW_PAYLOADS = "raw_payloads"
    FINALITY = "finality"
    REORG_RECOVERY = "reorg_recovery"
    DATASET_EXPORT = "dataset_export"


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


@dataclass(frozen=True, slots=True)
class RequestLimits:
    """Hard per-operation limits; all values are required and finite."""

    max_items: int = 1_000
    max_pages: int = 100
    max_requests: int = 100
    max_response_bytes: int = 16 * 1024 * 1024

    def __post_init__(self) -> None:
        _positive_int(self.max_items, "max_items")
        _positive_int(self.max_pages, "max_pages")
        _positive_int(self.max_requests, "max_requests")
        _positive_int(self.max_response_bytes, "max_response_bytes")


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
class BoundedRequest:
    """Common finite pagination/range request passed to source protocols."""

    scope: str
    context: OperationContext
    cursor: str | None = None
    start_position: int | None = None
    end_position: int | None = None
    options: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.scope.strip():
            raise InvalidRequestError("scope must not be empty")
        if self.cursor == "":
            raise InvalidRequestError("cursor must be non-empty when provided")
        for value, name in (
            (self.start_position, "start_position"),
            (self.end_position, "end_position"),
        ):
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, int) or value < 0
            ):
                raise InvalidRequestError(f"{name} must be a non-negative integer")
        if (
            self.start_position is not None
            and self.end_position is not None
            and self.start_position > self.end_position
        ):
            raise InvalidRequestError(
                "start_position must not be greater than end_position"
            )
        object.__setattr__(self, "options", MappingProxyType(dict(self.options)))


@dataclass(frozen=True, slots=True)
class RecordBatch:
    """One provider or normalized batch with accounting for bound checks."""

    records: tuple[object, ...]
    next_cursor: str | None = None
    response_bytes: int = 0

    def __post_init__(self) -> None:
        if self.next_cursor == "":
            raise InvalidRequestError("next_cursor must be non-empty when provided")
        if (
            isinstance(self.response_bytes, bool)
            or not isinstance(self.response_bytes, int)
            or self.response_bytes < 0
        ):
            raise InvalidRequestError("response_bytes must be a non-negative integer")

    def enforce(self, limits: RequestLimits) -> None:
        """Raise when this batch alone violates the declared operation limits."""

        if len(self.records) > limits.max_items:
            raise ResourceLimitError(
                f"batch contains {len(self.records)} items; limit is {limits.max_items}"
            )
        if self.response_bytes > limits.max_response_bytes:
            raise ResourceLimitError(
                "batch response bytes exceed max_response_bytes"
            )


@dataclass(frozen=True, slots=True)
class HttpRequest:
    """A fully described HTTP read with an explicit response-size ceiling."""

    method: str
    url: str
    max_response_bytes: int
    headers: Mapping[str, str] = field(default_factory=dict)
    body: bytes | None = None

    def __post_init__(self) -> None:
        method = self.method.upper()
        if method not in {"GET", "HEAD", "POST"}:
            raise InvalidRequestError("HTTP transport permits GET, HEAD, and POST")
        if not self.url.startswith(("http://", "https://")):
            raise InvalidRequestError("HTTP URL must use http or https")
        _positive_int(self.max_response_bytes, "max_response_bytes")
        object.__setattr__(self, "method", method)
        object.__setattr__(self, "headers", MappingProxyType(dict(self.headers)))


@dataclass(frozen=True, slots=True)
class HttpResponse:
    """Transport-neutral HTTP response data."""

    status: int
    headers: Mapping[str, str]
    body: bytes

    def __post_init__(self) -> None:
        if (
            isinstance(self.status, bool)
            or not isinstance(self.status, int)
            or not 100 <= self.status <= 599
        ):
            raise InvalidRequestError("HTTP status must be between 100 and 599")
        object.__setattr__(self, "headers", MappingProxyType(dict(self.headers)))


@dataclass(frozen=True, slots=True)
class SecretValue:
    """Resolved secret bytes whose representation never reveals the value."""

    value: bytes = field(repr=False)

    def __repr__(self) -> str:
        return "SecretValue(<redacted>)"

    def __str__(self) -> str:
        return "<redacted>"


@runtime_checkable
class WalletProvider(Protocol):
    """Bounded source of chain-native records for a wallet/account scope."""

    @property
    def capabilities(self) -> Capabilities:
        """Read-only provider capability declaration."""

        ...

    async def validate_address(
        self,
        address: str,
        *,
        context: OperationContext,
    ) -> object:
        """Validate and return a chain-specific normalized address value."""

        ...

    def ingest_wallet(self, request: BoundedRequest) -> AsyncIterator[RecordBatch]:
        """Stream bounded native batches; iteration is the asynchronous boundary."""

        ...


@runtime_checkable
class LedgerProvider(Protocol):
    """Bounded source of chain-native records for explicit ledger ranges."""

    @property
    def capabilities(self) -> Capabilities:
        """Read-only provider capability declaration."""

        ...

    async def ledger_head(
        self,
        *,
        context: OperationContext,
    ) -> object:
        """Return the provider's current chain-specific head reference."""

        ...

    def ingest_ledger(self, request: BoundedRequest) -> AsyncIterator[RecordBatch]:
        """Stream an explicit finite range as bounded native batches."""

        ...


@runtime_checkable
class ChainNormalizer(Protocol):
    """Pure conversion from chain-native values to versioned domain records."""

    @property
    def capabilities(self) -> Capabilities:
        """Normalization features and chain namespaces."""

        ...

    def normalize(
        self,
        records: Sequence[object],
        *,
        context: OperationContext,
    ) -> Sequence[object]:
        """Normalize a bounded batch without performing I/O."""

        ...


@runtime_checkable
class CheckpointStore(Protocol):
    """Durable checkpoint boundary with optimistic concurrency."""

    async def load(
        self,
        scope: str,
        *,
        context: OperationContext,
    ) -> object | None:
        """Load the checkpoint for an exact ingestion scope."""

        ...

    async def compare_and_set(
        self,
        scope: str,
        *,
        expected_revision: str | None,
        checkpoint: object,
        context: OperationContext,
    ) -> bool:
        """Atomically store *checkpoint* if its revision still matches."""

        ...


@runtime_checkable
class DatasetSink(Protocol):
    """Transactional streaming boundary for normalized wallet records."""

    async def write(
        self,
        batch: RecordBatch,
        *,
        context: OperationContext,
    ) -> object:
        """Stage one bounded batch and return a sink-native receipt."""

        ...

    async def commit(
        self,
        manifest: object,
        *,
        context: OperationContext,
    ) -> object:
        """Commit staged data and its final manifest atomically."""

        ...

    async def abort(
        self,
        *,
        context: OperationContext,
    ) -> None:
        """Discard or mark incomplete all uncommitted staged data."""

        ...


@runtime_checkable
class Exporter(Protocol):
    """Creates data exports through a supplied dataset sink."""

    @property
    def capabilities(self) -> Capabilities:
        """Export formats and chain namespaces."""

        ...

    async def export_wallet(
        self,
        request: BoundedRequest,
        sink: DatasetSink,
    ) -> object:
        """Export wallet data and return a versioned export receipt."""

        ...


@runtime_checkable
class HttpTransport(Protocol):
    """Injected HTTP I/O boundary; implementations enforce all request budgets."""

    async def request(
        self,
        request: HttpRequest,
        *,
        context: OperationContext,
    ) -> HttpResponse:
        """Execute one bounded request after checking cancellation/deadline."""

        ...


@runtime_checkable
class SecretResolver(Protocol):
    """Injected resolver for opaque references, never ambient credentials."""

    async def resolve(
        self,
        reference: str,
        *,
        context: OperationContext,
    ) -> SecretValue:
        """Resolve an explicit reference without logging or serializing its value."""

        ...


@runtime_checkable
class FinalityPolicy(Protocol):
    """Pure chain-specific finality and rewind policy."""

    @property
    def capabilities(self) -> Capabilities:
        """Finality/reorganization features and chain namespaces."""

        ...

    def classify(
        self,
        record: object,
        *,
        head: object,
        context: OperationContext,
    ) -> object:
        """Return a chain-specific finality state for a normalized record."""

        ...

    def rewind_position(
        self,
        checkpoint: object,
        *,
        observed_anchor: object,
        context: OperationContext,
    ) -> int | None:
        """Return the safe replay position when an anchor no longer matches."""

        ...


__all__ = [
    "BoundedRequest",
    "CancellationToken",
    "Capabilities",
    "Capability",
    "ChainNormalizer",
    "CheckpointStore",
    "DatasetSink",
    "Exporter",
    "FinalityPolicy",
    "HttpRequest",
    "HttpResponse",
    "HttpTransport",
    "LedgerProvider",
    "OperationContext",
    "RecordBatch",
    "RequestLimits",
    "SecretResolver",
    "SecretValue",
    "WalletProvider",
]
