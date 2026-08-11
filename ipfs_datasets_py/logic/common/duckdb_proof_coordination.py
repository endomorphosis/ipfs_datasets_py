"""Fenced single-flight proof coordinator (DQK-027).

Adapts formal-verification and evidence-store single-flight patterns into a
common coordinator layered on :class:`~.duckdb_proof_store.DuckDBProofStore`:

* **Fenced single-flight claims** — at most one valid producer publishes per
  proof key.  Concurrent identical work coalesces behind one claim.
* **Dual TTL / negative caching** — conclusive proof and counterexample
  outcomes use the positive TTL; unknown and error outcomes use the shorter
  negative TTL and never promote into positive authority.
* **Invalidation** — explicit key invalidation drops cached authority and any
  active claim so the next producer restarts cleanly.
* **Attempt records** — every claim generation leaves an auditable attempt
  (running / succeeded / failed / abandoned / superseded).
* **Stale-publication rejection** — a publisher whose fence has expired,
  been released, or been superseded cannot write authority.

Importing this module is inert: no DuckDB, network, or filesystem I/O.  The
default coordinator is process-local and thread-safe.  An optional DuckDB
connection may install the proofs-catalog ``singleflight_claims`` /
``invalidations`` tables declared by DQK-025.

Waiters recover after a producer crash without duplicate authority: when the
leader's fence expires or is abandoned, exactly one waiter may acquire the
next fence generation, and only the current unexpired fence may publish.
"""

from __future__ import annotations

import os
import secrets
import threading
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Final

from ..backends.cache_protocol import (
    DEFAULT_MAX_ENTRIES,
    DEFAULT_NEGATIVE_TTL_SECONDS,
    DEFAULT_POSITIVE_TTL_SECONDS,
    VERIFICATION_CACHE_PROTOCOL_INTERFACE,
    CacheLookupReason,
    CachePolarity,
    VerificationCacheEntry,
    VerificationCacheKey,
    VerificationCacheLookup,
)
from ..backends.results import TypedBackendResult
from ..families.models import EvidenceAuthority
from .duckdb_proof_store import (
    DUCKDB_PROOF_STORE_INTERFACE,
    PROOFS_CATALOG_DDL,
    PROOFS_CATALOG_TABLES,
    DuckDBProofStore,
    DuckDBProofStoreError,
    ProofOutcomeKind,
    ProofTrustLevel,
    UnifiedProofEntry,
    UnifiedProofKey,
    build_duckdb_proof_store,
    outcome_kind_for_status,
    polarity_for_outcome,
    proof_store_content_digest,
)

# ---------------------------------------------------------------------------
# Schema / interface pins
# ---------------------------------------------------------------------------

DUCKDB_PROOF_COORDINATION_INTERFACE: Final = "DuckDBProofCoordination@1"
DUCKDB_PROOF_COORDINATION_SCHEMA_VERSION: Final = "duckdb-proof-coordination/v1"
PROOF_FENCE_CLAIM_SCHEMA_VERSION: Final = "proof-fence-claim/v1"
PROOF_ATTEMPT_RECORD_SCHEMA_VERSION: Final = "proof-attempt-record/v1"
PROOF_INVALIDATION_SCHEMA_VERSION: Final = "proof-invalidation/v1"

DEFAULT_LEASE_SECONDS: Final = 300.0  # 5 minutes
DEFAULT_WAIT_TIMEOUT_SECONDS: Final = 600.0  # 10 minutes
DEFAULT_POLL_INTERVAL_SECONDS: Final = 0.01
DEFAULT_OUTCOME_HANDOFF_SECONDS: Final = 60.0

# Catalog tables owned or projected by coordination (subset of proofs catalog).
COORDINATION_CATALOG_TABLES: Final[tuple[str, ...]] = (
    "singleflight_claims",
    "invalidations",
    "access_statistics",
)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class DuckDBProofCoordinationError(ValueError):
    """Raised when a coordination claim, attempt, or policy is invalid."""


class StaleFenceError(DuckDBProofCoordinationError):
    """Raised when a released, expired, superseded, or foreign fence mutates."""


class ExpiredFenceError(StaleFenceError):
    """Raised specifically when a fence lease has expired before publish."""


class ProofCoordinationTimeout(DuckDBProofCoordinationError, TimeoutError):
    """Raised when a waiter cannot observe a terminal outcome in time."""


class ProofCoordinationExecutionError(DuckDBProofCoordinationError):
    """Raised when a leader published a fail-closed execution error outcome."""

    def __init__(
        self,
        reason_code: str,
        *,
        attempt: "ProofAttemptRecord | None" = None,
    ) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code
        self.attempt = attempt


# ---------------------------------------------------------------------------
# Closed vocabularies
# ---------------------------------------------------------------------------


class ClaimStatus(StrEnum):
    """Lifecycle of one fenced single-flight claim generation."""

    CLAIMED = "claimed"
    PUBLISHED = "published"
    RELEASED = "released"
    EXPIRED = "expired"
    SUPERSEDED = "superseded"


class AttemptStatus(StrEnum):
    """Terminal and in-progress states for a producer attempt record."""

    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    ABANDONED = "abandoned"
    SUPERSEDED = "superseded"


class CoordinationRole(StrEnum):
    """How the caller obtained a coordinated result."""

    CACHE_HIT = "cache_hit"
    PRODUCER = "producer"
    WAITER = "waiter"
    RECOVERED_PRODUCER = "recovered_producer"


class InvalidationReason(StrEnum):
    """Closed reasons recorded on explicit invalidation."""

    EXPLICIT = "explicit"
    AUTHORITY_CHANGE = "authority_change"
    POLICY = "policy"
    TAMPER = "tamper"
    REVOCATION = "revocation"
    SUPERSEDED = "superseded"
    EXPIRED = "expired"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _text(value: object, field_name: str, *, optional: bool = False) -> str:
    if optional and value == "":
        return ""
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or "\x00" in value
    ):
        qualifier = "an empty or " if optional else "a "
        raise DuckDBProofCoordinationError(
            f"{field_name} must be {qualifier}non-empty trimmed string without NUL"
        )
    return value


def _enum(value: object, enum_type: type[Any], field_name: str) -> Any:
    try:
        return value if isinstance(value, enum_type) else enum_type(value)
    except (TypeError, ValueError) as error:
        choices = ", ".join(repr(item.value) for item in enum_type)
        raise DuckDBProofCoordinationError(
            f"{field_name} must be one of {choices}"
        ) from error


def _finite_number(value: object, field_name: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise DuckDBProofCoordinationError(f"{field_name} must be a finite number")
    number = float(value)
    if number != number or number in (float("inf"), float("-inf")):
        raise DuckDBProofCoordinationError(f"{field_name} must be a finite number")
    return number


def _positive_duration(value: object, field_name: str) -> float:
    number = _finite_number(value, field_name)
    if number <= 0:
        raise DuckDBProofCoordinationError(f"{field_name} must be positive")
    return number


def _non_negative_duration(value: object, field_name: str) -> float:
    number = _finite_number(value, field_name)
    if number < 0:
        raise DuckDBProofCoordinationError(f"{field_name} must be non-negative")
    return number


def _key_digest(key: UnifiedProofKey | VerificationCacheKey | str) -> str:
    if isinstance(key, str):
        return _text(key, "key_digest")
    if isinstance(key, UnifiedProofKey):
        return key.require_all_dimensions().digest
    if isinstance(key, VerificationCacheKey):
        return key.digest
    raise TypeError(
        "key must be a UnifiedProofKey, VerificationCacheKey, or key digest string"
    )


def _default_owner_id() -> str:
    return f"pid:{os.getpid()}:thread:{threading.get_ident()}"


def _new_claim_id() -> str:
    return f"claim:{uuid.uuid4().hex}"


def _new_attempt_id() -> str:
    return f"attempt:{uuid.uuid4().hex}"


def _new_fence_token() -> str:
    # Unguessable opaque token; generation is tracked separately as fence_generation.
    return f"fence:{secrets.token_hex(16)}"


def _new_invalidation_id() -> str:
    return f"invalidation:{uuid.uuid4().hex}"


# ---------------------------------------------------------------------------
# Claim / attempt / invalidation records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ProofFenceClaim:
    """One fenced single-flight generation for a proof key.

    Only a claim with ``acquired=True`` and a still-valid lease may publish.
    Followers receive ``acquired=False`` and must wait or recover after expiry.
    """

    key_digest: str
    claim_id: str
    owner_id: str
    fence_token: str
    fence_generation: int
    claimed_at: float
    expires_at: float
    status: ClaimStatus
    acquired: bool
    schema_version: str = PROOF_FENCE_CLAIM_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "key_digest", _text(self.key_digest, "key_digest")
        )
        object.__setattr__(self, "claim_id", _text(self.claim_id, "claim_id"))
        object.__setattr__(self, "owner_id", _text(self.owner_id, "owner_id"))
        if not isinstance(self.acquired, bool):
            raise DuckDBProofCoordinationError("acquired must be a boolean")
        # Followers deliberately omit the owner publication token.
        object.__setattr__(
            self,
            "fence_token",
            _text(self.fence_token, "fence_token", optional=not self.acquired),
        )
        if (
            isinstance(self.fence_generation, bool)
            or not isinstance(self.fence_generation, int)
            or self.fence_generation < 1
        ):
            raise DuckDBProofCoordinationError(
                "fence_generation must be a positive integer"
            )
        object.__setattr__(
            self, "claimed_at", _finite_number(self.claimed_at, "claimed_at")
        )
        object.__setattr__(
            self, "expires_at", _finite_number(self.expires_at, "expires_at")
        )
        if self.expires_at < self.claimed_at:
            raise DuckDBProofCoordinationError(
                "expires_at must be >= claimed_at"
            )
        object.__setattr__(
            self, "status", _enum(self.status, ClaimStatus, "status")
        )
        object.__setattr__(
            self,
            "schema_version",
            _text(self.schema_version, "schema_version"),
        )
        if self.schema_version != PROOF_FENCE_CLAIM_SCHEMA_VERSION:
            raise DuckDBProofCoordinationError(
                f"unsupported claim schema: {self.schema_version!r}"
            )

    @property
    def is_leader(self) -> bool:
        return self.acquired

    def is_expired(self, *, now: float | None = None) -> bool:
        current = time.time() if now is None else float(now)
        return current >= self.expires_at

    def remaining_seconds(self, *, now: float | None = None) -> float:
        current = time.time() if now is None else float(now)
        return max(0.0, self.expires_at - current)

    def to_dict(self) -> dict[str, Any]:
        return {
            "acquired": self.acquired,
            "claim_id": self.claim_id,
            "claimed_at": self.claimed_at,
            "expires_at": self.expires_at,
            "fence_generation": self.fence_generation,
            "fence_token": self.fence_token,
            "key_digest": self.key_digest,
            "owner_id": self.owner_id,
            "schema_version": self.schema_version,
            "status": self.status.value,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ProofFenceClaim:
        if not isinstance(value, Mapping):
            raise DuckDBProofCoordinationError("claim must be a mapping")
        return cls(
            key_digest=str(value.get("key_digest") or ""),
            claim_id=str(value.get("claim_id") or ""),
            owner_id=str(value.get("owner_id") or ""),
            fence_token=str(value.get("fence_token") or ""),
            fence_generation=int(value.get("fence_generation") or 0),
            claimed_at=float(value.get("claimed_at") or 0.0),
            expires_at=float(value.get("expires_at") or 0.0),
            status=value.get("status", ClaimStatus.CLAIMED.value),
            acquired=bool(value.get("acquired", False)),
            schema_version=str(
                value.get("schema_version") or PROOF_FENCE_CLAIM_SCHEMA_VERSION
            ),
        )


@dataclass(frozen=True, slots=True)
class ProofAttemptRecord:
    """Auditable record of one producer attempt under a fence generation."""

    attempt_id: str
    key_digest: str
    claim_id: str
    fence_token: str
    fence_generation: int
    owner_id: str
    status: AttemptStatus
    started_at: float
    finished_at: float | None = None
    outcome_digest: str = ""
    entry_digest: str = ""
    polarity: CachePolarity | None = None
    error_reason: str = ""
    schema_version: str = PROOF_ATTEMPT_RECORD_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "attempt_id", _text(self.attempt_id, "attempt_id")
        )
        object.__setattr__(
            self, "key_digest", _text(self.key_digest, "key_digest")
        )
        object.__setattr__(self, "claim_id", _text(self.claim_id, "claim_id"))
        object.__setattr__(
            self, "fence_token", _text(self.fence_token, "fence_token")
        )
        if (
            isinstance(self.fence_generation, bool)
            or not isinstance(self.fence_generation, int)
            or self.fence_generation < 1
        ):
            raise DuckDBProofCoordinationError(
                "fence_generation must be a positive integer"
            )
        object.__setattr__(self, "owner_id", _text(self.owner_id, "owner_id"))
        object.__setattr__(
            self, "status", _enum(self.status, AttemptStatus, "status")
        )
        object.__setattr__(
            self, "started_at", _finite_number(self.started_at, "started_at")
        )
        if self.finished_at is not None:
            object.__setattr__(
                self,
                "finished_at",
                _finite_number(self.finished_at, "finished_at"),
            )
        object.__setattr__(
            self,
            "outcome_digest",
            _text(self.outcome_digest, "outcome_digest", optional=True),
        )
        object.__setattr__(
            self,
            "entry_digest",
            _text(self.entry_digest, "entry_digest", optional=True),
        )
        if self.polarity is not None:
            object.__setattr__(
                self,
                "polarity",
                _enum(self.polarity, CachePolarity, "polarity"),
            )
        object.__setattr__(
            self,
            "error_reason",
            _text(self.error_reason, "error_reason", optional=True),
        )
        object.__setattr__(
            self,
            "schema_version",
            _text(self.schema_version, "schema_version"),
        )
        if self.schema_version != PROOF_ATTEMPT_RECORD_SCHEMA_VERSION:
            raise DuckDBProofCoordinationError(
                f"unsupported attempt schema: {self.schema_version!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "attempt_id": self.attempt_id,
            "claim_id": self.claim_id,
            "entry_digest": self.entry_digest,
            "error_reason": self.error_reason,
            "fence_generation": self.fence_generation,
            "fence_token": self.fence_token,
            "finished_at": self.finished_at,
            "key_digest": self.key_digest,
            "outcome_digest": self.outcome_digest,
            "owner_id": self.owner_id,
            "polarity": None if self.polarity is None else self.polarity.value,
            "schema_version": self.schema_version,
            "started_at": self.started_at,
            "status": self.status.value,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ProofAttemptRecord:
        if not isinstance(value, Mapping):
            raise DuckDBProofCoordinationError("attempt record must be a mapping")
        polarity = value.get("polarity")
        finished = value.get("finished_at")
        return cls(
            attempt_id=str(value.get("attempt_id") or ""),
            key_digest=str(value.get("key_digest") or ""),
            claim_id=str(value.get("claim_id") or ""),
            fence_token=str(value.get("fence_token") or ""),
            fence_generation=int(value.get("fence_generation") or 0),
            owner_id=str(value.get("owner_id") or ""),
            status=value.get("status", AttemptStatus.RUNNING.value),
            started_at=float(value.get("started_at") or 0.0),
            finished_at=None if finished is None else float(finished),
            outcome_digest=str(value.get("outcome_digest") or ""),
            entry_digest=str(value.get("entry_digest") or ""),
            polarity=None if polarity in (None, "") else polarity,
            error_reason=str(value.get("error_reason") or ""),
            schema_version=str(
                value.get("schema_version")
                or PROOF_ATTEMPT_RECORD_SCHEMA_VERSION
            ),
        )


@dataclass(frozen=True, slots=True)
class ProofInvalidationRecord:
    """Record that authority for a key was explicitly dropped."""

    invalidation_id: str
    key_digest: str
    reason: InvalidationReason
    created_at: float
    actor_id: str
    schema_version: str = PROOF_INVALIDATION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "invalidation_id",
            _text(self.invalidation_id, "invalidation_id"),
        )
        object.__setattr__(
            self, "key_digest", _text(self.key_digest, "key_digest")
        )
        object.__setattr__(
            self, "reason", _enum(self.reason, InvalidationReason, "reason")
        )
        object.__setattr__(
            self, "created_at", _finite_number(self.created_at, "created_at")
        )
        object.__setattr__(self, "actor_id", _text(self.actor_id, "actor_id"))
        object.__setattr__(
            self,
            "schema_version",
            _text(self.schema_version, "schema_version"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "actor_id": self.actor_id,
            "created_at": self.created_at,
            "invalidation_id": self.invalidation_id,
            "key_digest": self.key_digest,
            "reason": self.reason.value,
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True, slots=True)
class CoordinationResult:
    """Projection of a coordinated get-or-compute outcome."""

    lookup: VerificationCacheLookup
    role: CoordinationRole
    claim: ProofFenceClaim | None = None
    attempt: ProofAttemptRecord | None = None
    single_flight_shared: bool = False
    recovered: bool = False

    @property
    def usable(self) -> bool:
        return bool(self.lookup.usable)

    @property
    def hit(self) -> bool:
        return bool(self.lookup.hit)

    @property
    def entry(self) -> VerificationCacheEntry | None:
        return self.lookup.entry

    @property
    def key_digest(self) -> str:
        return self.lookup.key_digest

    def to_dict(self) -> dict[str, Any]:
        return {
            "attempt": None if self.attempt is None else self.attempt.to_dict(),
            "claim": None if self.claim is None else self.claim.to_dict(),
            "hit": self.hit,
            "key_digest": self.key_digest,
            "lookup_reason": self.lookup.reason.value
            if hasattr(self.lookup.reason, "value")
            else str(self.lookup.reason),
            "recovered": self.recovered,
            "role": self.role.value,
            "single_flight_shared": self.single_flight_shared,
            "usable": self.usable,
        }


# ---------------------------------------------------------------------------
# Internal flight state
# ---------------------------------------------------------------------------


@dataclass
class _FlightState:
    """Mutable rendezvous for one active fence generation."""

    claim: ProofFenceClaim
    attempt: ProofAttemptRecord
    event: threading.Event = field(default_factory=threading.Event)
    entry: UnifiedProofEntry | None = None
    error: BaseException | None = None
    published: bool = False
    waiter_count: int = 0


# ---------------------------------------------------------------------------
# Coordinator
# ---------------------------------------------------------------------------


class DuckDBProofCoordinator:
    """Fenced single-flight coordinator over a unified proof store.

    Authority publication requires a current, unexpired fence.  Waiters that
    observe a producer crash (abandoned or expired fence) re-enter claim
    acquisition so exactly one recovered producer may publish; prior fences
    are rejected if they attempt a late publication.
    """

    def __init__(
        self,
        store: DuckDBProofStore | None = None,
        *,
        max_entries: int = DEFAULT_MAX_ENTRIES,
        positive_ttl_seconds: float = DEFAULT_POSITIVE_TTL_SECONDS,
        negative_ttl_seconds: float = DEFAULT_NEGATIVE_TTL_SECONDS,
        lease_seconds: float = DEFAULT_LEASE_SECONDS,
        wait_timeout_seconds: float = DEFAULT_WAIT_TIMEOUT_SECONDS,
        poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS,
        outcome_handoff_seconds: float = DEFAULT_OUTCOME_HANDOFF_SECONDS,
        connection: Any | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.lease_seconds = _positive_duration(lease_seconds, "lease_seconds")
        self.wait_timeout_seconds = _positive_duration(
            wait_timeout_seconds, "wait_timeout_seconds"
        )
        self.poll_interval_seconds = _positive_duration(
            poll_interval_seconds, "poll_interval_seconds"
        )
        self.outcome_handoff_seconds = _positive_duration(
            outcome_handoff_seconds, "outcome_handoff_seconds"
        )
        if negative_ttl_seconds > positive_ttl_seconds and positive_ttl_seconds > 0:
            raise DuckDBProofCoordinationError(
                "negative_ttl_seconds cannot exceed positive_ttl_seconds"
            )
        self.positive_ttl_seconds = _non_negative_duration(
            positive_ttl_seconds, "positive_ttl_seconds"
        )
        self.negative_ttl_seconds = _non_negative_duration(
            negative_ttl_seconds, "negative_ttl_seconds"
        )
        self._clock = clock or time.time
        self._lock = threading.RLock()
        self._store = store or build_duckdb_proof_store(
            max_entries=max_entries,
            positive_ttl_seconds=self.positive_ttl_seconds,
            negative_ttl_seconds=self.negative_ttl_seconds,
            connection=connection,
        )
        # Active claim per key_digest (only current generation).
        self._claims: dict[str, ProofFenceClaim] = {}
        # Generation counters per key.
        self._generations: dict[str, int] = {}
        # Flight rendezvous keyed by key_digest for the active generation.
        self._flights: dict[str, _FlightState] = {}
        # Append-only attempt history (bounded by store max_entries * 4).
        self._attempts: list[ProofAttemptRecord] = []
        self._invalidations: list[ProofInvalidationRecord] = []
        # Brief handoff of published outcomes so late waiters share without
        # re-producing; not an authority root (store remains authoritative).
        self._handoffs: dict[str, tuple[float, UnifiedProofEntry | None, BaseException | None, int]] = {}
        self._stats = {
            "claims_acquired": 0,
            "claims_followed": 0,
            "claims_expired": 0,
            "claims_abandoned": 0,
            "publications": 0,
            "stale_rejections": 0,
            "expired_rejections": 0,
            "waiter_recoveries": 0,
            "single_flight_waits": 0,
            "invalidations": 0,
            "negative_publications": 0,
            "positive_publications": 0,
            "producer_failures": 0,
        }
        if connection is not None:
            self.install_schema(connection)

    # -- identity ------------------------------------------------------------

    @property
    def interface(self) -> str:
        return DUCKDB_PROOF_COORDINATION_INTERFACE

    @property
    def schema_version(self) -> str:
        return DUCKDB_PROOF_COORDINATION_SCHEMA_VERSION

    @property
    def store(self) -> DuckDBProofStore:
        return self._store

    @property
    def store_interface(self) -> str:
        return DUCKDB_PROOF_STORE_INTERFACE

    @property
    def cache_interface(self) -> str:
        return VERIFICATION_CACHE_PROTOCOL_INTERFACE

    def now(self) -> float:
        return float(self._clock())

    @staticmethod
    def install_schema(connection: Any) -> None:
        """Apply proofs-catalog DDL (includes singleflight_claims)."""

        DuckDBProofStore.install_schema(connection)

    def catalog_tables(self) -> tuple[str, ...]:
        return PROOFS_CATALOG_TABLES

    def coordination_tables(self) -> tuple[str, ...]:
        return COORDINATION_CATALOG_TABLES

    def stats(self) -> Mapping[str, int]:
        with self._lock:
            store_stats = self._store.stats()
            return MappingProxyType(
                {
                    **self._stats,
                    "active_claims": len(self._claims),
                    "active_flights": len(self._flights),
                    "attempt_records": len(self._attempts),
                    "invalidation_records": len(self._invalidations),
                    "store_size": int(store_stats.get("size") or 0),
                    "store_hits": int(store_stats.get("hits") or 0),
                    "store_misses": int(store_stats.get("misses") or 0),
                }
            )

    # -- dual TTL policy -----------------------------------------------------

    def ttl_for_polarity(self, polarity: CachePolarity | str) -> float:
        """Return the dual-TTL policy duration for a cache polarity."""

        resolved = _enum(polarity, CachePolarity, "polarity")
        if resolved is CachePolarity.NEGATIVE:
            return self.negative_ttl_seconds
        return self.positive_ttl_seconds

    def ttl_for_outcome(self, outcome: ProofOutcomeKind | str) -> float:
        return self.ttl_for_polarity(polarity_for_outcome(outcome))

    def ttl_for_entry(
        self, entry: UnifiedProofEntry | VerificationCacheEntry
    ) -> float:
        if isinstance(entry, UnifiedProofEntry):
            return self.ttl_for_polarity(entry.polarity)
        if isinstance(entry, VerificationCacheEntry):
            return self.ttl_for_polarity(entry.polarity)
        raise TypeError("entry must be UnifiedProofEntry or VerificationCacheEntry")

    def negative_cache_policy(self) -> Mapping[str, Any]:
        """Describe the dual-TTL negative caching policy (immutable)."""

        return MappingProxyType(
            {
                "positive_ttl_seconds": self.positive_ttl_seconds,
                "negative_ttl_seconds": self.negative_ttl_seconds,
                "negative_outcomes": (
                    ProofOutcomeKind.UNKNOWN.value,
                    ProofOutcomeKind.ERROR.value,
                ),
                "positive_outcomes": (
                    ProofOutcomeKind.PROOF.value,
                    ProofOutcomeKind.COUNTEREXAMPLE.value,
                ),
                "policy": (
                    "unknown and error outcomes use negative_ttl_seconds and "
                    "never promote into positive authority; proof and "
                    "counterexample use positive_ttl_seconds"
                ),
            }
        )

    # -- key resolution ------------------------------------------------------

    def _resolve_key(
        self, key: UnifiedProofKey | VerificationCacheKey
    ) -> UnifiedProofKey:
        if isinstance(key, UnifiedProofKey):
            return key.require_all_dimensions()
        if isinstance(key, VerificationCacheKey):
            return self._store._resolve_unified_key(key)
        raise TypeError("key must be a UnifiedProofKey or VerificationCacheKey")

    def _digest(
        self, key: UnifiedProofKey | VerificationCacheKey | str
    ) -> str:
        if isinstance(key, str):
            return _text(key, "key_digest")
        return self._resolve_key(key).digest

    # -- claim lifecycle -----------------------------------------------------

    def _expire_claim_locked(
        self, key_digest: str, *, now: float, reason: ClaimStatus
    ) -> None:
        claim = self._claims.get(key_digest)
        if claim is None:
            return
        if claim.status is ClaimStatus.CLAIMED and claim.expires_at <= now:
            expired = ProofFenceClaim(
                key_digest=claim.key_digest,
                claim_id=claim.claim_id,
                owner_id=claim.owner_id,
                fence_token=claim.fence_token,
                fence_generation=claim.fence_generation,
                claimed_at=claim.claimed_at,
                expires_at=claim.expires_at,
                status=ClaimStatus.EXPIRED,
                acquired=False,
            )
            self._claims[key_digest] = expired
            self._stats["claims_expired"] += 1
            flight = self._flights.get(key_digest)
            if flight is not None and flight.claim.fence_token == claim.fence_token:
                self._finalize_attempt_locked(
                    flight.attempt,
                    status=AttemptStatus.ABANDONED,
                    finished_at=now,
                    error_reason="fence_expired",
                )
                flight.event.set()
                self._flights.pop(key_digest, None)
            # Drop from active claims so a new generation may acquire.
            self._claims.pop(key_digest, None)
            return
        if reason is ClaimStatus.SUPERSEDED and claim.status is ClaimStatus.CLAIMED:
            self._claims[key_digest] = ProofFenceClaim(
                key_digest=claim.key_digest,
                claim_id=claim.claim_id,
                owner_id=claim.owner_id,
                fence_token=claim.fence_token,
                fence_generation=claim.fence_generation,
                claimed_at=claim.claimed_at,
                expires_at=claim.expires_at,
                status=ClaimStatus.SUPERSEDED,
                acquired=False,
            )

    def _active_claim_locked(
        self, key_digest: str, *, now: float
    ) -> ProofFenceClaim | None:
        claim = self._claims.get(key_digest)
        if claim is None:
            return None
        if claim.status is ClaimStatus.CLAIMED and claim.expires_at > now:
            return claim
        if claim.status is ClaimStatus.CLAIMED and claim.expires_at <= now:
            self._expire_claim_locked(
                key_digest, now=now, reason=ClaimStatus.EXPIRED
            )
            return None
        # Terminal statuses free the key for a new generation.
        if claim.status in {
            ClaimStatus.PUBLISHED,
            ClaimStatus.RELEASED,
            ClaimStatus.EXPIRED,
            ClaimStatus.SUPERSEDED,
        }:
            # Keep handoff window for published outcomes; drop claim slot.
            if claim.status is not ClaimStatus.PUBLISHED or (
                claim.expires_at <= now
            ):
                self._claims.pop(key_digest, None)
            elif claim.status is ClaimStatus.PUBLISHED:
                # Published claim remains only as a follower-visible marker
                # until handoff TTL; not re-acquirable as a producer.
                return claim
        return None

    def claim(
        self,
        key: UnifiedProofKey | VerificationCacheKey | str,
        *,
        owner_id: str | None = None,
        lease_seconds: float | None = None,
        now: float | None = None,
    ) -> ProofFenceClaim:
        """Acquire a fenced claim or join as a follower of the current owner.

        When a completed publication is still within the handoff window, a
        follower claim is returned so waiters observe the shared outcome
        without starting a second producer.
        """

        key_digest = self._digest(key)
        owner = _text(owner_id or _default_owner_id(), "owner_id")
        duration = (
            self.lease_seconds
            if lease_seconds is None
            else _positive_duration(lease_seconds, "lease_seconds")
        )
        current = self.now() if now is None else float(now)

        with self._lock:
            # Prefer a usable store hit path is handled by get_or_compute; claim
            # itself is pure coordination.
            active = self._active_claim_locked(key_digest, now=current)
            if active is not None and active.status is ClaimStatus.CLAIMED:
                self._stats["claims_followed"] += 1
                return ProofFenceClaim(
                    key_digest=active.key_digest,
                    claim_id=active.claim_id,
                    owner_id=active.owner_id,
                    fence_token="",  # followers never receive owner token
                    fence_generation=active.fence_generation,
                    claimed_at=active.claimed_at,
                    expires_at=active.expires_at,
                    status=ClaimStatus.CLAIMED,
                    acquired=False,
                )
            if active is not None and active.status is ClaimStatus.PUBLISHED:
                handoff = self._handoffs.get(key_digest)
                if handoff is not None and handoff[0] > current:
                    self._stats["claims_followed"] += 1
                    return ProofFenceClaim(
                        key_digest=active.key_digest,
                        claim_id=active.claim_id,
                        owner_id=active.owner_id,
                        fence_token="",
                        fence_generation=active.fence_generation,
                        claimed_at=active.claimed_at,
                        expires_at=handoff[0],
                        status=ClaimStatus.PUBLISHED,
                        acquired=False,
                    )
                self._claims.pop(key_digest, None)
                self._handoffs.pop(key_digest, None)

            generation = self._generations.get(key_digest, 0) + 1
            self._generations[key_digest] = generation
            fence_token = _new_fence_token()
            claim_id = _new_claim_id()
            acquired = ProofFenceClaim(
                key_digest=key_digest,
                claim_id=claim_id,
                owner_id=owner,
                fence_token=fence_token,
                fence_generation=generation,
                claimed_at=current,
                expires_at=current + duration,
                status=ClaimStatus.CLAIMED,
                acquired=True,
            )
            self._claims[key_digest] = acquired
            attempt = ProofAttemptRecord(
                attempt_id=_new_attempt_id(),
                key_digest=key_digest,
                claim_id=claim_id,
                fence_token=fence_token,
                fence_generation=generation,
                owner_id=owner,
                status=AttemptStatus.RUNNING,
                started_at=current,
            )
            self._attempts.append(attempt)
            self._trim_attempts_locked()
            self._flights[key_digest] = _FlightState(
                claim=acquired, attempt=attempt
            )
            self._stats["claims_acquired"] += 1
            return acquired

    acquire = claim
    acquire_lease = claim

    def renew(
        self,
        claim: ProofFenceClaim,
        *,
        lease_seconds: float | None = None,
        now: float | None = None,
    ) -> ProofFenceClaim:
        """Extend a currently owned unexpired fence lease."""

        if not isinstance(claim, ProofFenceClaim):
            raise TypeError("claim must be a ProofFenceClaim")
        if not claim.acquired or not claim.fence_token:
            raise StaleFenceError("only the current claim owner may renew")
        duration = (
            self.lease_seconds
            if lease_seconds is None
            else _positive_duration(lease_seconds, "lease_seconds")
        )
        current = self.now() if now is None else float(now)
        with self._lock:
            active = self._claims.get(claim.key_digest)
            if (
                active is None
                or active.status is not ClaimStatus.CLAIMED
                or active.fence_token != claim.fence_token
                or active.fence_generation != claim.fence_generation
                or active.owner_id != claim.owner_id
                or active.claim_id != claim.claim_id
            ):
                self._stats["stale_rejections"] += 1
                raise StaleFenceError(
                    "claim fence is stale, released, or superseded"
                )
            if active.expires_at <= current:
                self._expire_claim_locked(
                    claim.key_digest, now=current, reason=ClaimStatus.EXPIRED
                )
                self._stats["expired_rejections"] += 1
                raise ExpiredFenceError("claim fence has expired")
            renewed = ProofFenceClaim(
                key_digest=active.key_digest,
                claim_id=active.claim_id,
                owner_id=active.owner_id,
                fence_token=active.fence_token,
                fence_generation=active.fence_generation,
                claimed_at=active.claimed_at,
                expires_at=current + duration,
                status=ClaimStatus.CLAIMED,
                acquired=True,
            )
            self._claims[claim.key_digest] = renewed
            flight = self._flights.get(claim.key_digest)
            if flight is not None and flight.claim.fence_token == renewed.fence_token:
                flight.claim = renewed
            return renewed

    heartbeat = renew
    renew_lease = renew

    def release(
        self,
        claim: ProofFenceClaim,
        *,
        now: float | None = None,
        abandon: bool = False,
    ) -> bool:
        """Release an owned claim without publishing authority.

        When ``abandon`` is true (or the claim is still running), waiters are
        woken so they may recover by acquiring a new fence generation.
        """

        if not isinstance(claim, ProofFenceClaim):
            raise TypeError("claim must be a ProofFenceClaim")
        if not claim.acquired or not claim.fence_token:
            return False
        current = self.now() if now is None else float(now)
        with self._lock:
            active = self._claims.get(claim.key_digest)
            if (
                active is None
                or active.fence_token != claim.fence_token
                or active.fence_generation != claim.fence_generation
                or active.claim_id != claim.claim_id
            ):
                return False
            if active.status is ClaimStatus.PUBLISHED:
                # Publication already terminalized the claim.
                return False
            released = ProofFenceClaim(
                key_digest=active.key_digest,
                claim_id=active.claim_id,
                owner_id=active.owner_id,
                fence_token=active.fence_token,
                fence_generation=active.fence_generation,
                claimed_at=active.claimed_at,
                expires_at=active.expires_at,
                status=ClaimStatus.RELEASED,
                acquired=False,
            )
            self._claims.pop(claim.key_digest, None)
            flight = self._flights.pop(claim.key_digest, None)
            if flight is not None:
                self._finalize_attempt_locked(
                    flight.attempt,
                    status=AttemptStatus.ABANDONED,
                    finished_at=current,
                    error_reason="claim_released" if not abandon else "producer_abandoned",
                )
                # Do not set flight.error — waiters recover by re-claiming
                # rather than inheriting a crash as shared authority.
                flight.event.set()
            self._stats["claims_abandoned"] += 1
            # Record released snapshot only for audit via attempt status.
            _ = released
            return True

    release_lease = release

    def abandon(
        self,
        claim: ProofFenceClaim,
        *,
        now: float | None = None,
    ) -> bool:
        """Simulate producer crash: drop the fence and wake waiters to recover."""

        return self.release(claim, now=now, abandon=True)

    def _require_live_owner_locked(
        self,
        claim: ProofFenceClaim,
        *,
        now: float,
    ) -> ProofFenceClaim:
        if not claim.acquired or not claim.fence_token:
            self._stats["stale_rejections"] += 1
            raise StaleFenceError("only the current claim owner may publish")
        active = self._claims.get(claim.key_digest)
        if (
            active is None
            or active.status is not ClaimStatus.CLAIMED
            or active.fence_token != claim.fence_token
            or active.fence_generation != claim.fence_generation
            or active.owner_id != claim.owner_id
            or active.claim_id != claim.claim_id
        ):
            self._stats["stale_rejections"] += 1
            raise StaleFenceError(
                "cannot publish from a stale, released, or foreign fence"
            )
        if active.expires_at <= now:
            self._expire_claim_locked(
                claim.key_digest, now=now, reason=ClaimStatus.EXPIRED
            )
            self._stats["expired_rejections"] += 1
            raise ExpiredFenceError(
                "cannot publish from an expired fence"
            )
        return active

    # -- publication ---------------------------------------------------------

    def _coerce_entry(
        self,
        key: UnifiedProofKey,
        produced: UnifiedProofEntry | VerificationCacheEntry | TypedBackendResult,
        *,
        now: float,
    ) -> UnifiedProofEntry:
        if isinstance(produced, TypedBackendResult):
            return UnifiedProofEntry.from_typed_result(
                key, produced, created_at=now
            )
        if isinstance(produced, VerificationCacheEntry):
            return UnifiedProofEntry.from_verification_cache_entry(
                produced, key=key
            )
        if isinstance(produced, UnifiedProofEntry):
            if produced.key.digest != key.digest:
                raise DuckDBProofCoordinationError(
                    "producer entry key does not match requested key"
                )
            return produced.verify_integrity()
        raise DuckDBProofCoordinationError(
            "producer must return UnifiedProofEntry, "
            "VerificationCacheEntry, or TypedBackendResult"
        )

    def publish(
        self,
        claim: ProofFenceClaim,
        entry: UnifiedProofEntry | VerificationCacheEntry | TypedBackendResult,
        *,
        key: UnifiedProofKey | VerificationCacheKey | None = None,
        now: float | None = None,
    ) -> CoordinationResult:
        """Publish authority under a live fence; reject stale/expired fences.

        Dual-TTL negative caching is applied by the underlying store based on
        outcome polarity.  Negative outcomes never become positive authority.
        """

        if not isinstance(claim, ProofFenceClaim):
            raise TypeError("claim must be a ProofFenceClaim")
        current = self.now() if now is None else float(now)

        if key is None:
            # Resolve from store secondary index or require UnifiedProofKey path
            # via entry.
            if isinstance(entry, UnifiedProofEntry):
                unified = entry.key
            elif isinstance(entry, VerificationCacheEntry):
                unified = self._store._resolve_unified_key(entry.key)
            elif isinstance(entry, TypedBackendResult):
                raise DuckDBProofCoordinationError(
                    "key is required when publishing a TypedBackendResult"
                )
            else:
                raise DuckDBProofCoordinationError(
                    "entry must be UnifiedProofEntry, VerificationCacheEntry, "
                    "or TypedBackendResult"
                )
        else:
            unified = self._resolve_key(key)

        if unified.digest != claim.key_digest:
            raise DuckDBProofCoordinationError(
                "publication key digest does not match claim key_digest"
            )

        with self._lock:
            active = self._require_live_owner_locked(claim, now=current)
            unified_entry = self._coerce_entry(unified, entry, now=current)
            # Negative caching policy: polarity is derived from outcome; refuse
            # to store an entry whose polarity contradicts the dual-TTL policy.
            expected_polarity = polarity_for_outcome(unified_entry.outcome)
            if unified_entry.polarity is not expected_polarity:
                raise DuckDBProofCoordinationError(
                    f"entry polarity {unified_entry.polarity.value!r} contradicts "
                    f"outcome {unified_entry.outcome.value!r}"
                )
            stored = self._store.put(unified_entry, now=current)
            # Handoff window is measured from publication time.  When a caller
            # injects a logical clock that is behind wall-clock claim time, keep
            # expires_at >= claimed_at without extending the window indefinitely.
            handoff_expires = current + self.outcome_handoff_seconds
            if handoff_expires < active.claimed_at:
                handoff_expires = active.claimed_at + self.outcome_handoff_seconds
            published_claim = ProofFenceClaim(
                key_digest=active.key_digest,
                claim_id=active.claim_id,
                owner_id=active.owner_id,
                fence_token=active.fence_token,
                fence_generation=active.fence_generation,
                claimed_at=min(active.claimed_at, current),
                expires_at=handoff_expires,
                status=ClaimStatus.PUBLISHED,
                acquired=False,
            )
            self._claims[claim.key_digest] = published_claim
            flight = self._flights.get(claim.key_digest)
            attempt = flight.attempt if flight is not None else None
            if attempt is not None:
                attempt = self._finalize_attempt_locked(
                    attempt,
                    status=AttemptStatus.SUCCEEDED,
                    finished_at=current,
                    outcome_digest=proof_store_content_digest(
                        unified_entry.identity_payload()
                    ),
                    entry_digest=unified_entry.entry_digest,
                    polarity=unified_entry.polarity,
                )
            if flight is not None:
                flight.entry = unified_entry
                flight.published = True
                flight.claim = published_claim
                flight.event.set()
                self._flights.pop(claim.key_digest, None)
            self._handoffs[claim.key_digest] = (
                handoff_expires,
                unified_entry,
                None,
                published_claim.fence_generation,
            )
            self._stats["publications"] += 1
            if unified_entry.polarity is CachePolarity.NEGATIVE:
                self._stats["negative_publications"] += 1
            else:
                self._stats["positive_publications"] += 1
            return CoordinationResult(
                lookup=stored,
                role=CoordinationRole.PRODUCER,
                claim=published_claim,
                attempt=attempt,
                single_flight_shared=False,
                recovered=False,
            )

    def publish_error(
        self,
        claim: ProofFenceClaim,
        *,
        reason_code: str = "producer_failed",
        now: float | None = None,
    ) -> None:
        """Publish a fail-closed execution error to waiters without store authority.

        Errors are coordination outcomes only; they do not write proof-store
        authority.  Waiters either observe the error or recover if the fence
        is released without an error handoff.
        """

        if not isinstance(claim, ProofFenceClaim):
            raise TypeError("claim must be a ProofFenceClaim")
        reason = _text(reason_code, "reason_code")
        current = self.now() if now is None else float(now)
        with self._lock:
            active = self._require_live_owner_locked(claim, now=current)
            flight = self._flights.get(claim.key_digest)
            error = ProofCoordinationExecutionError(reason)
            if flight is not None:
                flight.error = error
                attempt = self._finalize_attempt_locked(
                    flight.attempt,
                    status=AttemptStatus.FAILED,
                    finished_at=current,
                    error_reason=reason,
                )
                error.attempt = attempt
                flight.event.set()
                self._flights.pop(claim.key_digest, None)
            else:
                self._finalize_orphan_attempt_locked(
                    claim, status=AttemptStatus.FAILED, finished_at=current, error_reason=reason
                )
            self._claims.pop(claim.key_digest, None)
            self._handoffs[claim.key_digest] = (
                current + self.outcome_handoff_seconds,
                None,
                error,
                active.fence_generation,
            )
            self._stats["producer_failures"] += 1

    # -- attempt records -----------------------------------------------------

    def _finalize_attempt_locked(
        self,
        attempt: ProofAttemptRecord,
        *,
        status: AttemptStatus,
        finished_at: float,
        outcome_digest: str = "",
        entry_digest: str = "",
        polarity: CachePolarity | None = None,
        error_reason: str = "",
    ) -> ProofAttemptRecord:
        finalized = ProofAttemptRecord(
            attempt_id=attempt.attempt_id,
            key_digest=attempt.key_digest,
            claim_id=attempt.claim_id,
            fence_token=attempt.fence_token,
            fence_generation=attempt.fence_generation,
            owner_id=attempt.owner_id,
            status=status,
            started_at=attempt.started_at,
            finished_at=finished_at,
            outcome_digest=outcome_digest or attempt.outcome_digest,
            entry_digest=entry_digest or attempt.entry_digest,
            polarity=polarity if polarity is not None else attempt.polarity,
            error_reason=error_reason or attempt.error_reason,
        )
        # Replace in-place in history.
        for index, existing in enumerate(self._attempts):
            if existing.attempt_id == attempt.attempt_id:
                self._attempts[index] = finalized
                break
        else:
            self._attempts.append(finalized)
        self._trim_attempts_locked()
        return finalized

    def _finalize_orphan_attempt_locked(
        self,
        claim: ProofFenceClaim,
        *,
        status: AttemptStatus,
        finished_at: float,
        error_reason: str,
    ) -> ProofAttemptRecord:
        record = ProofAttemptRecord(
            attempt_id=_new_attempt_id(),
            key_digest=claim.key_digest,
            claim_id=claim.claim_id,
            fence_token=claim.fence_token,
            fence_generation=claim.fence_generation,
            owner_id=claim.owner_id,
            status=status,
            started_at=claim.claimed_at,
            finished_at=finished_at,
            error_reason=error_reason,
        )
        self._attempts.append(record)
        self._trim_attempts_locked()
        return record

    def _trim_attempts_locked(self) -> None:
        limit = max(64, self._store.max_entries * 4)
        if len(self._attempts) > limit:
            self._attempts = self._attempts[-limit:]

    def attempt_records(
        self,
        key: UnifiedProofKey | VerificationCacheKey | str | None = None,
    ) -> tuple[ProofAttemptRecord, ...]:
        """Return attempt history, optionally filtered by proof key."""

        with self._lock:
            if key is None:
                return tuple(self._attempts)
            digest = self._digest(key)
            return tuple(
                item for item in self._attempts if item.key_digest == digest
            )

    def active_claim(
        self,
        key: UnifiedProofKey | VerificationCacheKey | str,
        *,
        now: float | None = None,
    ) -> ProofFenceClaim | None:
        current = self.now() if now is None else float(now)
        with self._lock:
            return self._active_claim_locked(self._digest(key), now=current)

    # -- invalidation --------------------------------------------------------

    def invalidate(
        self,
        key: UnifiedProofKey | VerificationCacheKey | str,
        *,
        reason: InvalidationReason | str = InvalidationReason.EXPLICIT,
        actor_id: str | None = None,
        now: float | None = None,
    ) -> bool:
        """Drop cached authority and any active claim for ``key``."""

        resolved_reason = _enum(reason, InvalidationReason, "reason")
        actor = _text(actor_id or _default_owner_id(), "actor_id")
        current = self.now() if now is None else float(now)

        if isinstance(key, str):
            key_digest = _text(key, "key_digest")
            store_removed = False
            # Best-effort: walk store via digest only when key objects given.
        else:
            unified = self._resolve_key(key)
            key_digest = unified.digest
            store_removed = self._store.invalidate(unified)

        with self._lock:
            claim = self._claims.pop(key_digest, None)
            flight = self._flights.pop(key_digest, None)
            self._handoffs.pop(key_digest, None)
            if flight is not None:
                self._finalize_attempt_locked(
                    flight.attempt,
                    status=AttemptStatus.SUPERSEDED,
                    finished_at=current,
                    error_reason="invalidated",
                )
                flight.event.set()
            elif claim is not None and claim.status is ClaimStatus.CLAIMED:
                self._finalize_orphan_attempt_locked(
                    claim,
                    status=AttemptStatus.SUPERSEDED,
                    finished_at=current,
                    error_reason="invalidated",
                )
            record = ProofInvalidationRecord(
                invalidation_id=_new_invalidation_id(),
                key_digest=key_digest,
                reason=resolved_reason,
                created_at=current,
                actor_id=actor,
            )
            self._invalidations.append(record)
            if len(self._invalidations) > max(64, self._store.max_entries):
                self._invalidations = self._invalidations[
                    -max(64, self._store.max_entries) :
                ]
            self._stats["invalidations"] += 1
            return store_removed or claim is not None

    def invalidation_records(
        self,
        key: UnifiedProofKey | VerificationCacheKey | str | None = None,
    ) -> tuple[ProofInvalidationRecord, ...]:
        with self._lock:
            if key is None:
                return tuple(self._invalidations)
            digest = self._digest(key)
            return tuple(
                item for item in self._invalidations if item.key_digest == digest
            )

    # -- lookup / get_or_compute ---------------------------------------------

    def lookup(
        self,
        key: UnifiedProofKey | VerificationCacheKey,
        *,
        max_trust_level: ProofTrustLevel | str | None = None,
        max_evidence_authority: EvidenceAuthority | str | None = None,
        now: float | None = None,
    ) -> VerificationCacheLookup:
        """Lookup through the store dual-TTL policy (no claim required)."""

        return self._store.lookup(
            key,
            max_trust_level=max_trust_level,
            max_evidence_authority=max_evidence_authority,
            now=now,
        )

    def get(
        self,
        key: UnifiedProofKey | VerificationCacheKey,
        *,
        max_trust_level: ProofTrustLevel | str | None = None,
        now: float | None = None,
    ) -> UnifiedProofEntry | None:
        return self._store.get(key, max_trust_level=max_trust_level, now=now)

    def get_or_compute(
        self,
        key: UnifiedProofKey | VerificationCacheKey,
        producer: Callable[
            [], UnifiedProofEntry | VerificationCacheEntry | TypedBackendResult
        ],
        *,
        owner_id: str | None = None,
        lease_seconds: float | None = None,
        wait_timeout_seconds: float | None = None,
        max_trust_level: ProofTrustLevel | str | None = None,
        max_evidence_authority: EvidenceAuthority | str | None = None,
        now: float | None = None,
    ) -> CoordinationResult:
        """Lookup, or fenced single-flight compute and store on miss.

        Concurrent callers with the same proof key wait on one producer.
        If the producer crashes (abandon / lease expiry) without publishing,
        waiters recover by acquiring a new fence generation so at most one
        valid producer publishes and no duplicate authority is introduced.
        """

        if not callable(producer):
            raise TypeError("producer must be callable")
        unified = self._resolve_key(key)
        wait_bound = (
            self.wait_timeout_seconds
            if wait_timeout_seconds is None
            else _positive_duration(wait_timeout_seconds, "wait_timeout_seconds")
        )
        deadline = time.monotonic() + wait_bound
        recovered = False

        while True:
            if time.monotonic() >= deadline:
                raise ProofCoordinationTimeout(
                    "timed out waiting for fenced proof production"
                )

            # Fast path: usable store hit.
            existing = self.lookup(
                unified,
                max_trust_level=max_trust_level,
                max_evidence_authority=max_evidence_authority,
                now=now,
            )
            if existing.usable:
                return CoordinationResult(
                    lookup=existing,
                    role=CoordinationRole.CACHE_HIT,
                    claim=None,
                    attempt=None,
                    single_flight_shared=False,
                    recovered=False,
                )

            claim = self.claim(
                unified,
                owner_id=owner_id,
                lease_seconds=lease_seconds,
                now=now,
            )

            if claim.acquired:
                role = (
                    CoordinationRole.RECOVERED_PRODUCER
                    if recovered
                    else CoordinationRole.PRODUCER
                )
                try:
                    produced = producer()
                    result = self.publish(
                        claim, produced, key=unified, now=now
                    )
                    return CoordinationResult(
                        lookup=result.lookup,
                        role=role,
                        claim=result.claim,
                        attempt=result.attempt,
                        single_flight_shared=False,
                        recovered=recovered,
                    )
                except StaleFenceError:
                    # Heartbeat/expiry lost the fence; retry as recovery.
                    recovered = True
                    continue
                except BaseException as error:
                    # Try to signal waiters; if fence already dead they recover.
                    try:
                        if isinstance(error, (KeyboardInterrupt, SystemExit, GeneratorExit)):
                            self.abandon(claim, now=now)
                        else:
                            try:
                                self.publish_error(
                                    claim,
                                    reason_code=type(error).__name__,
                                    now=now,
                                )
                            except StaleFenceError:
                                self.abandon(claim, now=now)
                    except StaleFenceError:
                        pass
                    raise
                finally:
                    # Ensure claim does not linger if publish path skipped.
                    with self._lock:
                        active = self._claims.get(unified.digest)
                        if (
                            active is not None
                            and active.fence_token == claim.fence_token
                            and active.status is ClaimStatus.CLAIMED
                        ):
                            self.release(claim, now=now, abandon=True)

            # Follower path: wait on flight or published handoff.
            self._stats["single_flight_waits"] += 1
            observed_generation = claim.fence_generation
            while time.monotonic() < deadline:
                # Store may have been filled by the leader.
                hit = self.lookup(
                    unified,
                    max_trust_level=max_trust_level,
                    max_evidence_authority=max_evidence_authority,
                    now=now,
                )
                if hit.usable:
                    return CoordinationResult(
                        lookup=hit,
                        role=CoordinationRole.WAITER,
                        claim=claim,
                        attempt=None,
                        single_flight_shared=True,
                        recovered=False,
                    )

                with self._lock:
                    handoff = self._handoffs.get(unified.digest)
                    flight = self._flights.get(unified.digest)
                    active = self._claims.get(unified.digest)
                    current = self.now() if now is None else float(now)

                    if handoff is not None and handoff[3] == observed_generation:
                        expires_at, entry, error, _generation = handoff
                        if expires_at > current:
                            if error is not None:
                                raise error
                            if entry is not None:
                                evaluated = self._store._evaluate_entry(
                                    entry,
                                    unified,
                                    max_trust_level=(
                                        None
                                        if max_trust_level is None
                                        else _enum(
                                            max_trust_level,
                                            ProofTrustLevel,
                                            "max_trust_level",
                                        )
                                    ),
                                    now=current,
                                    single_flight_shared=True,
                                )
                                if evaluated.usable:
                                    return CoordinationResult(
                                        lookup=evaluated,
                                        role=CoordinationRole.WAITER,
                                        claim=claim,
                                        attempt=None,
                                        single_flight_shared=True,
                                        recovered=False,
                                    )

                    # Producer still running under same generation?
                    if (
                        flight is not None
                        and flight.claim.fence_generation == observed_generation
                        and flight.claim.status is ClaimStatus.CLAIMED
                        and flight.claim.expires_at > current
                    ):
                        flight.waiter_count += 1
                        event = flight.event
                    else:
                        # Fence gone / expired / superseded — recover.
                        if (
                            active is None
                            or active.fence_generation != observed_generation
                            or active.status
                            in {
                                ClaimStatus.RELEASED,
                                ClaimStatus.EXPIRED,
                                ClaimStatus.SUPERSEDED,
                            }
                            or (
                                active.status is ClaimStatus.CLAIMED
                                and active.expires_at <= current
                            )
                        ):
                            self._stats["waiter_recoveries"] += 1
                            recovered = True
                            event = None
                        else:
                            event = None

                if event is not None:
                    remaining = max(0.0, deadline - time.monotonic())
                    event.wait(
                        timeout=min(self.poll_interval_seconds * 10, remaining)
                    )
                    continue

                if recovered:
                    break  # re-enter claim acquisition
                time.sleep(self.poll_interval_seconds)

            if not recovered and time.monotonic() >= deadline:
                raise ProofCoordinationTimeout(
                    "timed out waiting for fenced proof production"
                )

    single_flight = get_or_compute
    execute = get_or_compute

    def clear(self) -> None:
        """Drop all coordination state and clear the underlying store."""

        with self._lock:
            for flight in self._flights.values():
                flight.event.set()
            self._flights.clear()
            self._claims.clear()
            self._handoffs.clear()
            self._attempts.clear()
            self._invalidations.clear()
            self._generations.clear()
            self._store.clear()


def build_duckdb_proof_coordinator(
    store: DuckDBProofStore | None = None,
    **kwargs: Any,
) -> DuckDBProofCoordinator:
    """Construct a :class:`DuckDBProofCoordinator` with standard defaults."""

    return DuckDBProofCoordinator(store=store, **kwargs)


__all__ = [
    "AttemptStatus",
    "COORDINATION_CATALOG_TABLES",
    "ClaimStatus",
    "CoordinationResult",
    "CoordinationRole",
    "DEFAULT_LEASE_SECONDS",
    "DEFAULT_OUTCOME_HANDOFF_SECONDS",
    "DEFAULT_POLL_INTERVAL_SECONDS",
    "DEFAULT_WAIT_TIMEOUT_SECONDS",
    "DUCKDB_PROOF_COORDINATION_INTERFACE",
    "DUCKDB_PROOF_COORDINATION_SCHEMA_VERSION",
    "DuckDBProofCoordinationError",
    "DuckDBProofCoordinator",
    "ExpiredFenceError",
    "InvalidationReason",
    "PROOF_ATTEMPT_RECORD_SCHEMA_VERSION",
    "PROOF_FENCE_CLAIM_SCHEMA_VERSION",
    "PROOF_INVALIDATION_SCHEMA_VERSION",
    "ProofAttemptRecord",
    "ProofCoordinationExecutionError",
    "ProofCoordinationTimeout",
    "ProofFenceClaim",
    "ProofInvalidationRecord",
    "StaleFenceError",
    "build_duckdb_proof_coordinator",
]
