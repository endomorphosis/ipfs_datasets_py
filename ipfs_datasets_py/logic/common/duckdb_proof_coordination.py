"""Fenced single-flight proof coordination (DQK-027).

Adapts the formal-verification cache and supervisor distributed single-flight
patterns into a common coordinator over :mod:`duckdb_proof_store`:

* **Fenced claims** — unguessable claim IDs plus a monotonic fence generation
  so only one valid producer may publish per proof key at a time.
* **Dual TTL / negative caching** — conclusive outcomes use the positive TTL;
  ``unknown`` / ``error`` (and non-conclusive statuses) use the negative TTL
  already enforced by the unified proof store.
* **Invalidation** — clears store authority, active claims, and flight
  rendezvous outcomes; appends an invalidation record.
* **Attempt records** — durable, append-only produce attempts for audit and
  recovery without granting duplicate authority.
* **Stale-publication rejection** — expired, superseded, foreign, or released
  fences cannot write authority.

Importing this module is inert: no DuckDB, network, or filesystem I/O.  A live
connection may be injected later; the default coordinator is process-local and
composes a :class:`DuckDBProofStore`.
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
    DEFAULT_NEGATIVE_TTL_SECONDS,
    DEFAULT_POSITIVE_TTL_SECONDS,
    CacheLookupReason,
    CachePolarity,
    VerificationCacheEntry,
    VerificationCacheKey,
    VerificationCacheLookup,
)
from ..backends.results import TypedBackendResult
from .duckdb_proof_store import (
    DuckDBProofStore,
    ProofOutcomeKind,
    UnifiedProofEntry,
    UnifiedProofKey,
    build_duckdb_proof_store,
    polarity_for_outcome,
)

# ---------------------------------------------------------------------------
# Schema / interface pins
# ---------------------------------------------------------------------------

DUCKDB_PROOF_COORDINATION_INTERFACE: Final = "DuckDBProofCoordination@1"
DUCKDB_PROOF_COORDINATION_SCHEMA_VERSION: Final = "duckdb-proof-coordination/v1"
PROOF_FLIGHT_OUTCOME_SCHEMA: Final = "duckdb-proof-flight-outcome/v1"
PROOF_ATTEMPT_RECORD_SCHEMA: Final = "duckdb-proof-attempt-record/v1"
PROOF_INVALIDATION_RECORD_SCHEMA: Final = "duckdb-proof-invalidation-record/v1"

DEFAULT_LEASE_SECONDS: Final = 300.0  # 5 minutes (matches formal-verification cache)
DEFAULT_WAIT_TIMEOUT_SECONDS: Final = 600.0
DEFAULT_OUTCOME_TTL_SECONDS: Final = 60.0
DEFAULT_POLL_INTERVAL_SECONDS: Final = 0.02
DEFAULT_MAX_ATTEMPTS_RETAINED: Final = 256

# Catalog tables owned/extended by the coordinator (proofs catalog family).
COORDINATION_CATALOG_TABLES: Final[tuple[str, ...]] = (
    "singleflight_claims",
    "proof_flight_outcomes",
    "proof_attempt_records",
    "invalidations",
)

COORDINATION_CATALOG_DDL: Final[str] = """
CREATE TABLE IF NOT EXISTS singleflight_claims (
    key_digest VARCHAR PRIMARY KEY,
    claim_id VARCHAR NOT NULL,
    owner_id VARCHAR NOT NULL,
    fence_token VARCHAR NOT NULL,
    claimed_at DOUBLE NOT NULL,
    expires_at DOUBLE NOT NULL,
    status VARCHAR NOT NULL
);

CREATE TABLE IF NOT EXISTS proof_flight_outcomes (
    key_digest VARCHAR PRIMARY KEY,
    fence_token VARCHAR NOT NULL,
    status VARCHAR NOT NULL,
    polarity VARCHAR NOT NULL,
    outcome_kind VARCHAR NOT NULL,
    entry_digest VARCHAR NOT NULL,
    error_reason VARCHAR NOT NULL,
    created_at DOUBLE NOT NULL,
    expires_at DOUBLE NOT NULL
);

CREATE TABLE IF NOT EXISTS proof_attempt_records (
    attempt_id VARCHAR PRIMARY KEY,
    key_digest VARCHAR NOT NULL,
    claim_id VARCHAR NOT NULL,
    owner_id VARCHAR NOT NULL,
    fence_token VARCHAR NOT NULL,
    status VARCHAR NOT NULL,
    started_at DOUBLE NOT NULL,
    finished_at DOUBLE NOT NULL,
    outcome_kind VARCHAR NOT NULL,
    polarity VARCHAR NOT NULL,
    error_reason VARCHAR NOT NULL,
    entry_digest VARCHAR NOT NULL
);

CREATE TABLE IF NOT EXISTS invalidations (
    invalidation_id VARCHAR PRIMARY KEY,
    key_digest VARCHAR NOT NULL,
    reason VARCHAR NOT NULL,
    created_at DOUBLE NOT NULL,
    actor_id VARCHAR NOT NULL
);
""".strip()


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ProofCoordinationError(RuntimeError):
    """Base failure for fenced proof single-flight coordination."""


class StaleFenceError(ProofCoordinationError):
    """A released, expired, superseded, or foreign fence attempted mutation."""


class ExpiredFenceError(StaleFenceError):
    """Publication or heartbeat used a fence whose lease has expired."""


class ProofCoordinationTimeout(ProofCoordinationError, TimeoutError):
    """A waiter or producer deadline elapsed without a usable outcome."""


class ProofCoordinationCancelled(ProofCoordinationError):
    """A member stopped waiting without cancelling an in-flight producer."""


class ProofCoordinationExecutionError(ProofCoordinationError):
    """A leader published one bounded, fail-closed execution failure."""

    def __init__(
        self,
        reason_code: str,
        *,
        outcome: "ProofFlightOutcome | None" = None,
    ) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code
        self.outcome = outcome


# ---------------------------------------------------------------------------
# Closed vocabularies
# ---------------------------------------------------------------------------


class ClaimStatus(StrEnum):
    """Lifecycle of a single-flight claim row."""

    CLAIMED = "claimed"
    COMPLETED = "completed"
    RELEASED = "released"
    EXPIRED = "expired"
    SUPERSEDED = "superseded"


class AttemptStatus(StrEnum):
    """Lifecycle of one producer attempt record."""

    STARTED = "started"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    SUPERSEDED = "superseded"


class FlightOutcomeStatus(StrEnum):
    """Rendezvous channel status (coordination only; not proof authority)."""

    OK = "ok"
    ERROR = "error"


# ---------------------------------------------------------------------------
# Records
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
        raise ProofCoordinationError(
            f"{field_name} must be {qualifier}non-empty trimmed string without NUL"
        )
    return value


def _positive_number(value: object, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise ProofCoordinationError(f"{field_name} must be a positive number")
    return float(value)


def _non_negative_number(value: object, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        raise ProofCoordinationError(f"{field_name} must be a non-negative number")
    return float(value)


def _key_digest(key: UnifiedProofKey | VerificationCacheKey | str) -> str:
    if isinstance(key, str):
        digest = key.strip()
        if not digest:
            raise ProofCoordinationError("key_digest must be a non-empty string")
        return digest
    if isinstance(key, UnifiedProofKey):
        return key.digest
    if isinstance(key, VerificationCacheKey):
        return key.digest
    raise ProofCoordinationError(
        "key must be a UnifiedProofKey, VerificationCacheKey, or digest string"
    )


def _enum(value: object, enum_type: type[Any], field_name: str) -> Any:
    try:
        return value if isinstance(value, enum_type) else enum_type(value)
    except (TypeError, ValueError) as error:
        choices = ", ".join(repr(item.value) for item in enum_type)
        raise ProofCoordinationError(
            f"{field_name} must be one of {choices}"
        ) from error


def _cancelled(cancel_event: Any) -> bool:
    if cancel_event is None:
        return False
    is_set = getattr(cancel_event, "is_set", None)
    if not callable(is_set):
        raise ProofCoordinationError("cancel_event must provide is_set()")
    return bool(is_set())


def negative_cache_ttl_for(
    *,
    outcome: ProofOutcomeKind | str | None,
    polarity: CachePolarity | str | None,
    positive_ttl_seconds: float,
    negative_ttl_seconds: float,
) -> float:
    """Return the dual-TTL policy value for a publication.

    Conclusive ``proof`` / ``counterexample`` outcomes use the positive TTL.
    Non-conclusive ``unknown`` / ``error`` and any negative polarity use the
    (strictly shorter when configured) negative TTL.
    """

    if polarity is not None:
        resolved_polarity = _enum(polarity, CachePolarity, "polarity")
        if resolved_polarity is CachePolarity.NEGATIVE:
            return float(negative_ttl_seconds)
    if outcome is not None:
        return (
            float(negative_ttl_seconds)
            if polarity_for_outcome(outcome) is CachePolarity.NEGATIVE
            else float(positive_ttl_seconds)
        )
    return float(positive_ttl_seconds)


@dataclass(frozen=True, slots=True)
class ProofFenceClaim:
    """One fenced single-flight generation for a proof key.

    Owners receive a secret ``claim_id`` (publication token).  Followers see
    the same fence generation but an empty claim ID so they cannot publish.
    """

    key_digest: str
    claim_id: str
    owner_id: str
    fence_token: int
    claimed_at: float
    expires_at: float
    acquired: bool
    status: ClaimStatus = ClaimStatus.CLAIMED
    completed: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "key_digest", _text(self.key_digest, "key_digest"))
        object.__setattr__(
            self,
            "claim_id",
            _text(self.claim_id, "claim_id", optional=not self.acquired),
        )
        object.__setattr__(self, "owner_id", _text(self.owner_id, "owner_id"))
        if (
            isinstance(self.fence_token, bool)
            or not isinstance(self.fence_token, int)
            or self.fence_token < 1
        ):
            raise ProofCoordinationError("fence_token must be a positive integer")
        object.__setattr__(
            self, "claimed_at", _non_negative_number(self.claimed_at, "claimed_at")
        )
        object.__setattr__(
            self, "expires_at", _non_negative_number(self.expires_at, "expires_at")
        )
        object.__setattr__(
            self, "status", _enum(self.status, ClaimStatus, "status")
        )
        if self.acquired and not self.claim_id:
            raise ProofCoordinationError("acquired claims require a claim_id")
        if not self.acquired and self.claim_id:
            # Followers must never receive the unguessable publication token.
            object.__setattr__(self, "claim_id", "")

    @property
    def is_owner(self) -> bool:
        return self.acquired

    @property
    def is_leader(self) -> bool:
        return self.acquired

    def is_expired(self, *, now: float | None = None) -> bool:
        current = time.time() if now is None else float(now)
        return current >= self.expires_at

    def to_dict(self) -> dict[str, Any]:
        return {
            "key_digest": self.key_digest,
            "claim_id": self.claim_id if self.acquired else "",
            "owner_id": self.owner_id,
            "fence_token": self.fence_token,
            "claimed_at": self.claimed_at,
            "expires_at": self.expires_at,
            "acquired": self.acquired,
            "status": self.status.value,
            "completed": self.completed,
        }

    def public_projection(self) -> dict[str, Any]:
        """Follower-safe projection without the publication token."""

        payload = self.to_dict()
        payload["claim_id"] = ""
        payload["acquired"] = False
        return payload


@dataclass(frozen=True, slots=True)
class ProofAttemptRecord:
    """Append-only record of one producer attempt under a fence generation."""

    attempt_id: str
    key_digest: str
    claim_id: str
    owner_id: str
    fence_token: int
    status: AttemptStatus
    started_at: float
    finished_at: float | None = None
    outcome_kind: str = ""
    polarity: str = ""
    error_reason: str = ""
    entry_digest: str = ""
    schema_version: str = PROOF_ATTEMPT_RECORD_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(self, "attempt_id", _text(self.attempt_id, "attempt_id"))
        object.__setattr__(self, "key_digest", _text(self.key_digest, "key_digest"))
        object.__setattr__(
            self, "claim_id", _text(self.claim_id, "claim_id", optional=True)
        )
        object.__setattr__(self, "owner_id", _text(self.owner_id, "owner_id"))
        if (
            isinstance(self.fence_token, bool)
            or not isinstance(self.fence_token, int)
            or self.fence_token < 1
        ):
            raise ProofCoordinationError("fence_token must be a positive integer")
        object.__setattr__(
            self, "status", _enum(self.status, AttemptStatus, "status")
        )
        object.__setattr__(
            self, "started_at", _non_negative_number(self.started_at, "started_at")
        )
        if self.finished_at is not None:
            object.__setattr__(
                self,
                "finished_at",
                _non_negative_number(self.finished_at, "finished_at"),
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "attempt_id": self.attempt_id,
            "key_digest": self.key_digest,
            "claim_id": self.claim_id,
            "owner_id": self.owner_id,
            "fence_token": self.fence_token,
            "status": self.status.value,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "outcome_kind": self.outcome_kind,
            "polarity": self.polarity,
            "error_reason": self.error_reason,
            "entry_digest": self.entry_digest,
        }


@dataclass(frozen=True, slots=True)
class ProofInvalidationRecord:
    """Append-only invalidation event for a proof key."""

    invalidation_id: str
    key_digest: str
    reason: str
    created_at: float
    actor_id: str = ""
    schema_version: str = PROOF_INVALIDATION_RECORD_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "invalidation_id", _text(self.invalidation_id, "invalidation_id")
        )
        object.__setattr__(self, "key_digest", _text(self.key_digest, "key_digest"))
        object.__setattr__(self, "reason", _text(self.reason, "reason"))
        object.__setattr__(
            self, "created_at", _non_negative_number(self.created_at, "created_at")
        )
        object.__setattr__(
            self, "actor_id", _text(self.actor_id, "actor_id", optional=True)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "invalidation_id": self.invalidation_id,
            "key_digest": self.key_digest,
            "reason": self.reason,
            "created_at": self.created_at,
            "actor_id": self.actor_id,
        }


@dataclass(frozen=True, slots=True)
class ProofFlightOutcome:
    """Bounded rendezvous result shared with waiters (not proof authority)."""

    key_digest: str
    fence_token: int
    status: FlightOutcomeStatus
    polarity: CachePolarity
    outcome_kind: str
    entry_digest: str
    error_reason: str
    created_at: float
    expires_at: float
    schema_version: str = PROOF_FLIGHT_OUTCOME_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(self, "key_digest", _text(self.key_digest, "key_digest"))
        if (
            isinstance(self.fence_token, bool)
            or not isinstance(self.fence_token, int)
            or self.fence_token < 1
        ):
            raise ProofCoordinationError("fence_token must be a positive integer")
        object.__setattr__(
            self, "status", _enum(self.status, FlightOutcomeStatus, "status")
        )
        object.__setattr__(
            self, "polarity", _enum(self.polarity, CachePolarity, "polarity")
        )
        object.__setattr__(
            self, "created_at", _non_negative_number(self.created_at, "created_at")
        )
        object.__setattr__(
            self, "expires_at", _non_negative_number(self.expires_at, "expires_at")
        )

    @property
    def successful(self) -> bool:
        return self.status is FlightOutcomeStatus.OK

    def is_expired(self, *, now: float | None = None) -> bool:
        current = time.time() if now is None else float(now)
        return current >= self.expires_at

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "key_digest": self.key_digest,
            "fence_token": self.fence_token,
            "status": self.status.value,
            "polarity": self.polarity.value,
            "outcome_kind": self.outcome_kind,
            "entry_digest": self.entry_digest,
            "error_reason": self.error_reason,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
        }


@dataclass(frozen=True, slots=True)
class ProofCoordinationResult:
    """Member projection after coordinate / get_or_compute."""

    lookup: VerificationCacheLookup
    claim: ProofFenceClaim | None
    attempt: ProofAttemptRecord | None
    produced: bool
    shared: bool
    fence_token: int

    @property
    def usable(self) -> bool:
        return self.lookup.usable

    @property
    def entry(self) -> VerificationCacheEntry | None:
        return self.lookup.entry

    def to_dict(self) -> dict[str, Any]:
        return {
            "produced": self.produced,
            "shared": self.shared,
            "fence_token": self.fence_token,
            "usable": self.usable,
            "lookup_reason": self.lookup.reason.value
            if hasattr(self.lookup.reason, "value")
            else str(self.lookup.reason),
            "key_digest": self.lookup.key_digest,
            "claim": None if self.claim is None else self.claim.to_dict(),
            "attempt": None if self.attempt is None else self.attempt.to_dict(),
        }


@dataclass
class _ClaimRow:
    key_digest: str
    claim_id: str
    owner_id: str
    fence_token: int
    claimed_at: float
    expires_at: float
    status: ClaimStatus
    # Generation counter retained even after release so takeovers advance.
    generation: int


@dataclass
class _InternalFlightOutcome:
    key_digest: str
    fence_token: int
    status: FlightOutcomeStatus
    polarity: CachePolarity
    outcome_kind: str
    entry_digest: str
    error_reason: str
    created_at: float
    expires_at: float
    entry: UnifiedProofEntry | None = None


# ---------------------------------------------------------------------------
# Coordinator
# ---------------------------------------------------------------------------


class DuckDBProofCoordinator:
    """Fenced single-flight coordinator over a unified proof store.

    Exactly one non-expired claim owner may publish authority for a proof key.
    Waiters observe the same fence generation; if the owner crashes or the
    lease expires without a publication, a waiter may take over with a new
    fence.  Expired or superseded fences are rejected fail-closed.
    """

    def __init__(
        self,
        store: DuckDBProofStore | None = None,
        *,
        lease_seconds: float = DEFAULT_LEASE_SECONDS,
        wait_timeout_seconds: float = DEFAULT_WAIT_TIMEOUT_SECONDS,
        outcome_ttl_seconds: float = DEFAULT_OUTCOME_TTL_SECONDS,
        poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS,
        positive_ttl_seconds: float | None = None,
        negative_ttl_seconds: float | None = None,
        max_attempts_retained: int = DEFAULT_MAX_ATTEMPTS_RETAINED,
        clock: Callable[[], float] | None = None,
        connection: Any | None = None,
    ) -> None:
        self.lease_seconds = _positive_number(lease_seconds, "lease_seconds")
        self.wait_timeout_seconds = _positive_number(
            wait_timeout_seconds, "wait_timeout_seconds"
        )
        self.outcome_ttl_seconds = _positive_number(
            outcome_ttl_seconds, "outcome_ttl_seconds"
        )
        self.poll_interval_seconds = _positive_number(
            poll_interval_seconds, "poll_interval_seconds"
        )
        if (
            isinstance(max_attempts_retained, bool)
            or not isinstance(max_attempts_retained, int)
            or max_attempts_retained < 1
        ):
            raise ProofCoordinationError("max_attempts_retained must be a positive int")
        self.max_attempts_retained = max_attempts_retained
        self._clock = clock or time.time
        self._lock = threading.RLock()
        self._connection = connection

        # Validate dual-TTL policy before constructing or accepting a store so
        # inverted configurations fail closed at the coordinator boundary.
        resolved_positive = (
            DEFAULT_POSITIVE_TTL_SECONDS
            if positive_ttl_seconds is None
            else float(positive_ttl_seconds)
        )
        resolved_negative = (
            DEFAULT_NEGATIVE_TTL_SECONDS
            if negative_ttl_seconds is None
            else float(negative_ttl_seconds)
        )
        if resolved_positive < 0 or resolved_negative < 0:
            raise ProofCoordinationError("TTL values must be non-negative")
        if resolved_negative > resolved_positive and resolved_positive > 0:
            raise ProofCoordinationError(
                "negative_ttl_seconds cannot exceed positive_ttl_seconds"
            )

        if store is None:
            store = build_duckdb_proof_store(
                positive_ttl_seconds=resolved_positive,
                negative_ttl_seconds=resolved_negative,
                connection=connection,
            )
        elif not isinstance(store, DuckDBProofStore):
            raise TypeError("store must be a DuckDBProofStore")
        self.store = store
        self.positive_ttl_seconds = (
            float(positive_ttl_seconds)
            if positive_ttl_seconds is not None
            else float(store.positive_ttl_seconds)
        )
        self.negative_ttl_seconds = (
            float(negative_ttl_seconds)
            if negative_ttl_seconds is not None
            else float(store.negative_ttl_seconds)
        )

        self._claims: dict[str, _ClaimRow] = {}
        self._outcomes: dict[str, _InternalFlightOutcome] = {}
        self._attempts: dict[str, list[ProofAttemptRecord]] = {}
        self._invalidations: list[ProofInvalidationRecord] = []
        self._stats = {
            "acquires": 0,
            "follower_joins": 0,
            "takeovers": 0,
            "publications": 0,
            "stale_rejections": 0,
            "expired_rejections": 0,
            "single_flight_waits": 0,
            "invalidations": 0,
            "attempts": 0,
            "heartbeats": 0,
            "releases": 0,
        }

        if connection is not None:
            self.install_schema(connection)

    # -- identity -----------------------------------------------------------

    @property
    def interface(self) -> str:
        return DUCKDB_PROOF_COORDINATION_INTERFACE

    @property
    def schema_version(self) -> str:
        return DUCKDB_PROOF_COORDINATION_SCHEMA_VERSION

    def catalog_tables(self) -> tuple[str, ...]:
        return COORDINATION_CATALOG_TABLES

    @staticmethod
    def install_schema(connection: Any) -> None:
        """Apply coordination DDL when a DuckDB connection is provided."""

        execute = getattr(connection, "execute", None)
        executescript = getattr(connection, "executescript", None)
        if callable(executescript):
            executescript(COORDINATION_CATALOG_DDL)
            return
        if not callable(execute):
            raise ProofCoordinationError(
                "connection must provide execute() or executescript()"
            )
        for statement in COORDINATION_CATALOG_DDL.split(";"):
            sql = statement.strip()
            if sql:
                execute(sql)

    def stats(self) -> Mapping[str, int]:
        with self._lock:
            return MappingProxyType(dict(self._stats))

    def _now(self) -> float:
        return float(self._clock())

    @staticmethod
    def _owner_id(owner_id: str | None) -> str:
        owner = (
            owner_id
            or f"pid:{os.getpid()}:thread:{threading.get_ident()}"
        ).strip()
        if not owner or len(owner.encode("utf-8")) > 1_024:
            raise ProofCoordinationError("owner_id must be nonempty and bounded")
        return owner

    def _resolve_store_key(
        self, key: UnifiedProofKey | VerificationCacheKey | str
    ) -> UnifiedProofKey | VerificationCacheKey | str:
        return key

    # -- claim lifecycle ----------------------------------------------------

    def acquire(
        self,
        key: UnifiedProofKey | VerificationCacheKey | str,
        *,
        owner_id: str | None = None,
        lease_seconds: float | None = None,
        now: float | None = None,
    ) -> ProofFenceClaim:
        """Acquire leadership for ``key`` or join the current generation."""

        digest = _key_digest(key)
        owner = self._owner_id(owner_id)
        duration = (
            self.lease_seconds if lease_seconds is None else float(lease_seconds)
        )
        _positive_number(duration, "lease_seconds")
        current = self._now() if now is None else float(now)

        with self._lock:
            outcome = self._outcomes.get(digest)
            if outcome is not None and outcome.expires_at > current:
                # Completed generation is a follower rendezvous — no recompute.
                return ProofFenceClaim(
                    key_digest=digest,
                    claim_id="",
                    owner_id=outcome.entry_digest or "completed-outcome",
                    fence_token=outcome.fence_token,
                    claimed_at=outcome.created_at,
                    expires_at=outcome.expires_at,
                    acquired=False,
                    status=ClaimStatus.COMPLETED,
                    completed=True,
                )

            row = self._claims.get(digest)
            if row is not None and row.expires_at > current:
                self._stats["follower_joins"] += 1
                return ProofFenceClaim(
                    key_digest=digest,
                    claim_id="",
                    owner_id=row.owner_id,
                    fence_token=row.fence_token,
                    claimed_at=row.claimed_at,
                    expires_at=row.expires_at,
                    acquired=False,
                    status=row.status,
                    completed=False,
                )

            prior_generation = row.generation if row is not None else 0
            if row is not None and row.expires_at <= current:
                self._stats["takeovers"] += 1
            fence = prior_generation + 1
            claim_id = secrets.token_hex(32)
            expires = current + duration
            self._claims[digest] = _ClaimRow(
                key_digest=digest,
                claim_id=claim_id,
                owner_id=owner,
                fence_token=fence,
                claimed_at=current,
                expires_at=expires,
                status=ClaimStatus.CLAIMED,
                generation=fence,
            )
            # Older generation outcomes must never satisfy a new computation.
            self._outcomes.pop(digest, None)
            self._stats["acquires"] += 1
            return ProofFenceClaim(
                key_digest=digest,
                claim_id=claim_id,
                owner_id=owner,
                fence_token=fence,
                claimed_at=current,
                expires_at=expires,
                acquired=True,
                status=ClaimStatus.CLAIMED,
                completed=False,
            )

    acquire_lease = acquire
    claim = acquire

    def heartbeat(
        self,
        claim: ProofFenceClaim,
        *,
        lease_seconds: float | None = None,
        now: float | None = None,
    ) -> ProofFenceClaim:
        """Extend a live owner lease; reject expired or foreign fences."""

        if not isinstance(claim, ProofFenceClaim):
            raise TypeError("claim must be a ProofFenceClaim")
        if not claim.acquired or not claim.claim_id:
            raise StaleFenceError("only the current claim owner may heartbeat")
        duration = (
            self.lease_seconds if lease_seconds is None else float(lease_seconds)
        )
        _positive_number(duration, "lease_seconds")
        current = self._now() if now is None else float(now)
        expires = current + duration

        with self._lock:
            row = self._claims.get(claim.key_digest)
            if (
                row is None
                or row.claim_id != claim.claim_id
                or row.owner_id != claim.owner_id
                or row.fence_token != claim.fence_token
                or row.status is not ClaimStatus.CLAIMED
            ):
                self._stats["stale_rejections"] += 1
                raise StaleFenceError("proof claim is stale or fenced")
            if row.expires_at <= current:
                row.status = ClaimStatus.EXPIRED
                self._stats["expired_rejections"] += 1
                raise ExpiredFenceError("proof claim lease has expired")
            row.expires_at = expires
            self._stats["heartbeats"] += 1
            return ProofFenceClaim(
                key_digest=row.key_digest,
                claim_id=row.claim_id,
                owner_id=row.owner_id,
                fence_token=row.fence_token,
                claimed_at=row.claimed_at,
                expires_at=row.expires_at,
                acquired=True,
                status=row.status,
                completed=False,
            )

    renew = heartbeat
    renew_lease = heartbeat

    def release(
        self,
        claim: ProofFenceClaim,
        *,
        now: float | None = None,
    ) -> bool:
        """Release ownership without publishing (crash-safe for waiters)."""

        if not isinstance(claim, ProofFenceClaim):
            raise TypeError("claim must be a ProofFenceClaim")
        if not claim.acquired or not claim.claim_id:
            return False
        current = self._now() if now is None else float(now)
        with self._lock:
            row = self._claims.get(claim.key_digest)
            if (
                row is None
                or row.claim_id != claim.claim_id
                or row.fence_token != claim.fence_token
            ):
                return False
            # Mark expired/released so waiters may take over; retain generation.
            if row.expires_at <= current:
                row.status = ClaimStatus.EXPIRED
            else:
                row.status = ClaimStatus.RELEASED
            row.expires_at = min(row.expires_at, current)
            self._stats["releases"] += 1
            return True

    release_lease = release

    def get_claim(
        self,
        key: UnifiedProofKey | VerificationCacheKey | str,
        *,
        now: float | None = None,
    ) -> ProofFenceClaim | None:
        digest = _key_digest(key)
        current = self._now() if now is None else float(now)
        with self._lock:
            row = self._claims.get(digest)
            if row is None:
                return None
            active = row.expires_at > current and row.status is ClaimStatus.CLAIMED
            return ProofFenceClaim(
                key_digest=row.key_digest,
                claim_id="" if not active else "",  # never leak claim_id via get
                owner_id=row.owner_id,
                fence_token=row.fence_token,
                claimed_at=row.claimed_at,
                expires_at=row.expires_at,
                acquired=False,
                status=row.status if active else (
                    ClaimStatus.EXPIRED
                    if row.expires_at <= current
                    else row.status
                ),
                completed=False,
            )

    def _require_live_owner(
        self,
        claim: ProofFenceClaim,
        *,
        now: float,
        action: str,
    ) -> _ClaimRow:
        if not claim.acquired or not claim.claim_id:
            self._stats["stale_rejections"] += 1
            raise StaleFenceError(f"only the current claim owner may {action}")
        row = self._claims.get(claim.key_digest)
        if (
            row is None
            or row.claim_id != claim.claim_id
            or row.owner_id != claim.owner_id
            or row.fence_token != claim.fence_token
            or row.status is not ClaimStatus.CLAIMED
        ):
            self._stats["stale_rejections"] += 1
            raise StaleFenceError(
                f"cannot {action} from a stale, released, or foreign fence"
            )
        if row.expires_at <= now:
            row.status = ClaimStatus.EXPIRED
            self._stats["expired_rejections"] += 1
            raise ExpiredFenceError(
                f"cannot {action} from an expired fence"
            )
        return row

    # -- attempt records ----------------------------------------------------

    def _append_attempt(self, record: ProofAttemptRecord) -> ProofAttemptRecord:
        bucket = self._attempts.setdefault(record.key_digest, [])
        bucket.append(record)
        overflow = len(bucket) - self.max_attempts_retained
        if overflow > 0:
            del bucket[:overflow]
        self._stats["attempts"] += 1
        return record

    def begin_attempt(
        self,
        claim: ProofFenceClaim,
        *,
        now: float | None = None,
    ) -> ProofAttemptRecord:
        """Record that a fenced owner began producing for its claim."""

        current = self._now() if now is None else float(now)
        with self._lock:
            self._require_live_owner(claim, now=current, action="begin an attempt")
            record = ProofAttemptRecord(
                attempt_id=f"attempt:{uuid.uuid4().hex}",
                key_digest=claim.key_digest,
                claim_id=claim.claim_id,
                owner_id=claim.owner_id,
                fence_token=claim.fence_token,
                status=AttemptStatus.STARTED,
                started_at=current,
            )
            return self._append_attempt(record)

    def complete_attempt(
        self,
        attempt: ProofAttemptRecord,
        *,
        status: AttemptStatus | str,
        outcome_kind: str = "",
        polarity: CachePolarity | str | None = None,
        error_reason: str = "",
        entry_digest: str = "",
        now: float | None = None,
    ) -> ProofAttemptRecord:
        """Terminalise an attempt record (append-only: write a successor)."""

        terminal = _enum(status, AttemptStatus, "status")
        if terminal is AttemptStatus.STARTED:
            raise ProofCoordinationError("complete_attempt requires a terminal status")
        current = self._now() if now is None else float(now)
        polarity_value = ""
        if polarity is not None:
            polarity_value = _enum(polarity, CachePolarity, "polarity").value
        finished = ProofAttemptRecord(
            attempt_id=attempt.attempt_id,
            key_digest=attempt.key_digest,
            claim_id=attempt.claim_id,
            owner_id=attempt.owner_id,
            fence_token=attempt.fence_token,
            status=terminal,
            started_at=attempt.started_at,
            finished_at=current,
            outcome_kind=str(outcome_kind or ""),
            polarity=polarity_value,
            error_reason=str(error_reason or ""),
            entry_digest=str(entry_digest or ""),
        )
        with self._lock:
            bucket = self._attempts.setdefault(attempt.key_digest, [])
            # Replace the open STARTED row with the terminal one (same attempt_id).
            replaced = False
            for index, existing in enumerate(bucket):
                if (
                    existing.attempt_id == attempt.attempt_id
                    and existing.status is AttemptStatus.STARTED
                ):
                    bucket[index] = finished
                    replaced = True
                    break
            if not replaced:
                bucket.append(finished)
                overflow = len(bucket) - self.max_attempts_retained
                if overflow > 0:
                    del bucket[:overflow]
            return finished

    def list_attempts(
        self,
        key: UnifiedProofKey | VerificationCacheKey | str,
    ) -> tuple[ProofAttemptRecord, ...]:
        digest = _key_digest(key)
        with self._lock:
            return tuple(self._attempts.get(digest, ()))

    # -- publish / dual TTL -------------------------------------------------

    def _coerce_entry(
        self,
        key: UnifiedProofKey | VerificationCacheKey | str,
        value: UnifiedProofEntry | VerificationCacheEntry | TypedBackendResult,
        *,
        now: float,
    ) -> UnifiedProofEntry:
        if isinstance(value, UnifiedProofEntry):
            entry = value.verify_integrity()
            if isinstance(key, UnifiedProofKey) and entry.key.digest != key.digest:
                raise ProofCoordinationError(
                    "producer entry key does not match requested key"
                )
            if isinstance(key, str) and entry.key.digest != key:
                raise ProofCoordinationError(
                    "producer entry key digest does not match requested key"
                )
            return entry
        if isinstance(value, VerificationCacheEntry):
            if isinstance(key, UnifiedProofKey):
                return UnifiedProofEntry.from_verification_cache_entry(
                    value, key=key
                )
            return UnifiedProofEntry.from_verification_cache_entry(value)
        if isinstance(value, TypedBackendResult):
            if not isinstance(key, UnifiedProofKey):
                raise ProofCoordinationError(
                    "publishing a TypedBackendResult requires a UnifiedProofKey"
                )
            return UnifiedProofEntry.from_typed_result(
                key, value, created_at=now
            )
        raise ProofCoordinationError(
            "publish value must be UnifiedProofEntry, VerificationCacheEntry, "
            "or TypedBackendResult"
        )

    def publish(
        self,
        claim: ProofFenceClaim,
        value: UnifiedProofEntry | VerificationCacheEntry | TypedBackendResult,
        *,
        key: UnifiedProofKey | VerificationCacheKey | str | None = None,
        now: float | None = None,
        outcome_ttl_seconds: float | None = None,
    ) -> VerificationCacheLookup:
        """Publish authority under a live fence; reject expired/stale fences.

        Dual-TTL negative caching is applied by the backing store via the
        entry polarity.  The flight outcome channel uses a short rendezvous
        TTL so waiters observe completion without re-granting authority.
        """

        if not isinstance(claim, ProofFenceClaim):
            raise TypeError("claim must be a ProofFenceClaim")
        current = self._now() if now is None else float(now)
        ttl = (
            self.outcome_ttl_seconds
            if outcome_ttl_seconds is None
            else float(outcome_ttl_seconds)
        )
        _positive_number(ttl, "outcome_ttl_seconds")

        publish_key: UnifiedProofKey | VerificationCacheKey | str
        if key is not None:
            publish_key = key
        elif isinstance(value, UnifiedProofEntry):
            publish_key = value.key
        elif isinstance(value, VerificationCacheEntry):
            publish_key = value.key
        else:
            raise ProofCoordinationError(
                "key is required when publishing a TypedBackendResult"
            )

        with self._lock:
            self._require_live_owner(claim, now=current, action="publish")
            # Re-check digest binding under the claim.
            digest = _key_digest(publish_key)
            if digest != claim.key_digest and not isinstance(
                publish_key, VerificationCacheKey
            ):
                # Unified keys must match exactly; verification keys may map.
                if isinstance(publish_key, UnifiedProofKey):
                    raise ProofCoordinationError(
                        "publish key does not match the claim key"
                    )

            entry = self._coerce_entry(publish_key, value, now=current)
            # Prefer the unified digest from the entry for authority.
            if entry.key.digest != claim.key_digest:
                # Allow verification-key based claims only when the store maps them.
                # For coordination, claim key is the authority identity.
                if claim.key_digest not in (
                    entry.key.digest,
                    entry.key.to_verification_cache_key().digest,
                ):
                    raise ProofCoordinationError(
                        "entry key is not bound to the claim fence"
                    )

            # Negative caching policy: polarity already encodes dual TTL.
            # Re-assert closed policy here for coordinator-level observability.
            _ = negative_cache_ttl_for(
                outcome=entry.outcome,
                polarity=entry.polarity,
                positive_ttl_seconds=self.positive_ttl_seconds,
                negative_ttl_seconds=self.negative_ttl_seconds,
            )

            stored = self.store.put(entry, now=current)
            outcome = _InternalFlightOutcome(
                key_digest=claim.key_digest,
                fence_token=claim.fence_token,
                status=FlightOutcomeStatus.OK,
                polarity=entry.polarity,
                outcome_kind=(
                    entry.outcome.value
                    if hasattr(entry.outcome, "value")
                    else str(entry.outcome)
                ),
                entry_digest=entry.entry_digest,
                error_reason="",
                created_at=current,
                expires_at=current + ttl,
                entry=entry,
            )
            self._outcomes[claim.key_digest] = outcome
            row = self._claims[claim.key_digest]
            row.status = ClaimStatus.COMPLETED
            row.expires_at = current  # free the key; outcome is the rendezvous
            self._stats["publications"] += 1
            return stored

    def publish_error(
        self,
        claim: ProofFenceClaim,
        *,
        reason_code: str = "single_flight_execution_failed",
        now: float | None = None,
        outcome_ttl_seconds: float | None = None,
    ) -> ProofFlightOutcome:
        """Publish a fail-closed error outcome without granting proof authority."""

        if not isinstance(claim, ProofFenceClaim):
            raise TypeError("claim must be a ProofFenceClaim")
        reason = _text(reason_code, "reason_code")
        current = self._now() if now is None else float(now)
        ttl = (
            self.outcome_ttl_seconds
            if outcome_ttl_seconds is None
            else float(outcome_ttl_seconds)
        )
        _positive_number(ttl, "outcome_ttl_seconds")
        with self._lock:
            self._require_live_owner(claim, now=current, action="publish an error")
            outcome = _InternalFlightOutcome(
                key_digest=claim.key_digest,
                fence_token=claim.fence_token,
                status=FlightOutcomeStatus.ERROR,
                polarity=CachePolarity.NEGATIVE,
                outcome_kind=ProofOutcomeKind.ERROR.value,
                entry_digest="",
                error_reason=reason,
                created_at=current,
                expires_at=current + ttl,
                entry=None,
            )
            self._outcomes[claim.key_digest] = outcome
            row = self._claims[claim.key_digest]
            row.status = ClaimStatus.COMPLETED
            row.expires_at = current
            self._stats["publications"] += 1
            return ProofFlightOutcome(
                key_digest=outcome.key_digest,
                fence_token=outcome.fence_token,
                status=outcome.status,
                polarity=outcome.polarity,
                outcome_kind=outcome.outcome_kind,
                entry_digest=outcome.entry_digest,
                error_reason=outcome.error_reason,
                created_at=outcome.created_at,
                expires_at=outcome.expires_at,
            )

    def read_outcome(
        self,
        key: UnifiedProofKey | VerificationCacheKey | str,
        *,
        fence_token: int | None = None,
        now: float | None = None,
    ) -> ProofFlightOutcome | None:
        digest = _key_digest(key)
        current = self._now() if now is None else float(now)
        with self._lock:
            outcome = self._outcomes.get(digest)
            if outcome is None or outcome.expires_at <= current:
                return None
            if fence_token is not None and outcome.fence_token != fence_token:
                return None
            return ProofFlightOutcome(
                key_digest=outcome.key_digest,
                fence_token=outcome.fence_token,
                status=outcome.status,
                polarity=outcome.polarity,
                outcome_kind=outcome.outcome_kind,
                entry_digest=outcome.entry_digest,
                error_reason=outcome.error_reason,
                created_at=outcome.created_at,
                expires_at=outcome.expires_at,
            )

    def _generation_active(
        self,
        claim: ProofFenceClaim,
        *,
        now: float | None = None,
    ) -> bool:
        current = self._now() if now is None else float(now)
        with self._lock:
            row = self._claims.get(claim.key_digest)
            return bool(
                row is not None
                and row.fence_token == claim.fence_token
                and row.status is ClaimStatus.CLAIMED
                and row.expires_at > current
            )

    # -- invalidation -------------------------------------------------------

    def invalidate(
        self,
        key: UnifiedProofKey | VerificationCacheKey | str,
        *,
        reason: str = "manual_invalidation",
        actor_id: str = "",
        now: float | None = None,
    ) -> ProofInvalidationRecord:
        """Invalidate store authority, active claim, and flight outcome."""

        digest = _key_digest(key)
        reason_text = _text(reason, "reason")
        actor = _text(actor_id, "actor_id", optional=True)
        current = self._now() if now is None else float(now)

        # Best-effort store invalidation (accepts unified or verification keys).
        try:
            if isinstance(key, str):
                # Build a synthetic lookup by scanning store via protocol if needed.
                # Direct digest invalidation through store when possible.
                removed = False
                with self.store._lock:  # noqa: SLF001 — coordinator owns the store
                    entry = self.store._entries.pop(digest, None)  # noqa: SLF001
                    if entry is not None:
                        vdigest = entry.key.to_verification_cache_key().digest
                        self.store._verification_index.pop(vdigest, None)  # noqa: SLF001
                        self.store._stats["evictions"] += 1  # noqa: SLF001
                        removed = True
                _ = removed
            else:
                self.store.invalidate(key)
        except Exception:
            # Invalidation of coordination state must still proceed.
            pass

        with self._lock:
            row = self._claims.get(digest)
            if row is not None:
                row.status = ClaimStatus.SUPERSEDED
                row.expires_at = min(row.expires_at, current)
            self._outcomes.pop(digest, None)
            # Supersede open attempts.
            open_attempts = self._attempts.get(digest, [])
            for index, attempt in enumerate(list(open_attempts)):
                if attempt.status is AttemptStatus.STARTED:
                    open_attempts[index] = ProofAttemptRecord(
                        attempt_id=attempt.attempt_id,
                        key_digest=attempt.key_digest,
                        claim_id=attempt.claim_id,
                        owner_id=attempt.owner_id,
                        fence_token=attempt.fence_token,
                        status=AttemptStatus.SUPERSEDED,
                        started_at=attempt.started_at,
                        finished_at=current,
                        outcome_kind=attempt.outcome_kind,
                        polarity=attempt.polarity,
                        error_reason="invalidated",
                        entry_digest=attempt.entry_digest,
                    )
            record = ProofInvalidationRecord(
                invalidation_id=f"invalidation:{uuid.uuid4().hex}",
                key_digest=digest,
                reason=reason_text,
                created_at=current,
                actor_id=actor,
            )
            self._invalidations.append(record)
            self._stats["invalidations"] += 1
            return record

    def list_invalidations(
        self,
        key: UnifiedProofKey | VerificationCacheKey | str | None = None,
    ) -> tuple[ProofInvalidationRecord, ...]:
        with self._lock:
            if key is None:
                return tuple(self._invalidations)
            digest = _key_digest(key)
            return tuple(
                item for item in self._invalidations if item.key_digest == digest
            )

    # -- coordinate / get_or_compute ----------------------------------------

    def wait_for_outcome(
        self,
        claim: ProofFenceClaim,
        *,
        timeout_seconds: float | None = None,
        cancel_event: Any = None,
        deadline_monotonic: float | None = None,
        now: float | None = None,
    ) -> ProofFlightOutcome | None:
        """Poll the rendezvous channel until outcome, takeover, or timeout."""

        timeout = (
            self.wait_timeout_seconds
            if timeout_seconds is None
            else float(timeout_seconds)
        )
        _positive_number(timeout, "timeout_seconds")
        member_deadline = time.monotonic() + timeout
        if deadline_monotonic is not None:
            member_deadline = min(member_deadline, float(deadline_monotonic))

        while True:
            if _cancelled(cancel_event):
                raise ProofCoordinationCancelled("single_flight_member_cancelled")
            remaining = member_deadline - time.monotonic()
            if remaining <= 0:
                raise ProofCoordinationTimeout("single_flight_member_deadline")
            outcome = self.read_outcome(
                claim.key_digest,
                fence_token=claim.fence_token,
                now=now,
            )
            if outcome is not None:
                return outcome
            if not self._generation_active(claim, now=now):
                return None
            time.sleep(min(self.poll_interval_seconds, remaining))

    def coordinate(
        self,
        key: UnifiedProofKey,
        producer: Callable[
            [], UnifiedProofEntry | VerificationCacheEntry | TypedBackendResult
        ],
        *,
        owner_id: str | None = None,
        lease_seconds: float | None = None,
        timeout_seconds: float | None = None,
        deadline_monotonic: float | None = None,
        cancel_event: Any = None,
        outcome_ttl_seconds: float | None = None,
        now: float | None = None,
    ) -> ProofCoordinationResult:
        """Single-flight: one fenced producer; waiters share the outcome.

        Cache hits short-circuit without claiming.  On producer crash (lease
        expiry without publish), waiters re-acquire with a new fence and at
        most one valid publisher emerges.
        """

        if not isinstance(key, UnifiedProofKey):
            raise TypeError("coordinate requires a UnifiedProofKey")
        if not callable(producer):
            raise TypeError("producer must be callable")

        timeout = (
            self.wait_timeout_seconds
            if timeout_seconds is None
            else float(timeout_seconds)
        )
        _positive_number(timeout, "timeout_seconds")
        duration = (
            self.lease_seconds if lease_seconds is None else float(lease_seconds)
        )
        _positive_number(duration, "lease_seconds")
        member_deadline = time.monotonic() + timeout
        if deadline_monotonic is not None:
            member_deadline = min(member_deadline, float(deadline_monotonic))

        # Fast path: usable authority already present.
        existing = self.store.lookup(key, now=now)
        if existing.usable:
            return ProofCoordinationResult(
                lookup=existing,
                claim=None,
                attempt=None,
                produced=False,
                shared=False,
                fence_token=0,
            )

        while True:
            if _cancelled(cancel_event):
                raise ProofCoordinationCancelled("single_flight_member_cancelled")
            if time.monotonic() >= member_deadline:
                raise ProofCoordinationTimeout("single_flight_member_deadline")

            claim = self.acquire(
                key,
                owner_id=owner_id,
                lease_seconds=duration,
                now=now,
            )

            if not claim.acquired:
                self._stats["single_flight_waits"] += 1
                if claim.completed:
                    # Rendezvous on a completed generation.
                    outcome = self.read_outcome(
                        claim.key_digest,
                        fence_token=claim.fence_token,
                        now=now,
                    )
                    if outcome is not None and outcome.successful:
                        hit = self.store.lookup(key, now=now)
                        if hit.usable:
                            return ProofCoordinationResult(
                                lookup=VerificationCacheLookup(
                                    entry=hit.entry,
                                    hit=True,
                                    usable=True,
                                    reason=CacheLookupReason.SINGLE_FLIGHT_SHARED,
                                    key_digest=key.digest,
                                    age_seconds=hit.age_seconds,
                                    single_flight_shared=True,
                                ),
                                claim=claim,
                                attempt=None,
                                produced=False,
                                shared=True,
                                fence_token=claim.fence_token,
                            )
                    if outcome is not None and not outcome.successful:
                        raise ProofCoordinationExecutionError(
                            outcome.error_reason or "single_flight_execution_failed",
                            outcome=outcome,
                        )
                    # Fall through to re-acquire if outcome vanished.
                    continue

                outcome = self.wait_for_outcome(
                    claim,
                    timeout_seconds=max(
                        self.poll_interval_seconds,
                        member_deadline - time.monotonic(),
                    ),
                    cancel_event=cancel_event,
                    deadline_monotonic=member_deadline,
                    now=now,
                )
                if outcome is None:
                    # Producer crashed / released — loop to take over.
                    continue
                if not outcome.successful:
                    raise ProofCoordinationExecutionError(
                        outcome.error_reason or "single_flight_execution_failed",
                        outcome=outcome,
                    )
                hit = self.store.lookup(key, now=now)
                if not hit.usable:
                    # Authority missing despite ok outcome: treat as miss and retry.
                    continue
                return ProofCoordinationResult(
                    lookup=VerificationCacheLookup(
                        entry=hit.entry,
                        hit=True,
                        usable=True,
                        reason=CacheLookupReason.SINGLE_FLIGHT_SHARED,
                        key_digest=key.digest,
                        age_seconds=hit.age_seconds,
                        single_flight_shared=True,
                    ),
                    claim=claim,
                    attempt=None,
                    produced=False,
                    shared=True,
                    fence_token=claim.fence_token,
                )

            # Owner path.
            if _cancelled(cancel_event):
                self.release(claim, now=now)
                raise ProofCoordinationCancelled("single_flight_member_cancelled")
            if time.monotonic() >= member_deadline:
                self.release(claim, now=now)
                raise ProofCoordinationTimeout("single_flight_member_deadline")

            attempt = self.begin_attempt(claim, now=now)
            heartbeat_stop = threading.Event()
            heartbeat_failures: list[BaseException] = []

            def maintain_lease() -> None:
                interval = max(0.01, duration / 3.0)
                while not heartbeat_stop.wait(interval):
                    try:
                        self.heartbeat(claim, lease_seconds=duration)
                    except BaseException as exc:  # noqa: BLE001 — surface via leader
                        heartbeat_failures.append(exc)
                        return

            heartbeat_thread = threading.Thread(
                target=maintain_lease,
                name=f"proof-coord-heartbeat-{claim.fence_token}",
                daemon=True,
            )
            heartbeat_thread.start()
            try:
                produced = producer()
                heartbeat_stop.set()
                heartbeat_thread.join(timeout=duration)
                if heartbeat_failures:
                    raise StaleFenceError(
                        "single-flight lease heartbeat was fenced"
                    ) from heartbeat_failures[0]
                stored = self.publish(
                    claim,
                    produced,
                    key=key,
                    now=now,
                    outcome_ttl_seconds=outcome_ttl_seconds,
                )
                entry = self._coerce_entry(key, produced, now=self._now() if now is None else float(now))
                finished = self.complete_attempt(
                    attempt,
                    status=AttemptStatus.SUCCEEDED,
                    outcome_kind=(
                        entry.outcome.value
                        if hasattr(entry.outcome, "value")
                        else str(entry.outcome)
                    ),
                    polarity=entry.polarity,
                    entry_digest=entry.entry_digest,
                    now=now,
                )
                return ProofCoordinationResult(
                    lookup=stored,
                    claim=claim,
                    attempt=finished,
                    produced=True,
                    shared=False,
                    fence_token=claim.fence_token,
                )
            except (
                StaleFenceError,
                ExpiredFenceError,
                ProofCoordinationCancelled,
                ProofCoordinationTimeout,
            ):
                heartbeat_stop.set()
                heartbeat_thread.join(timeout=duration)
                self.complete_attempt(
                    attempt,
                    status=AttemptStatus.FAILED,
                    error_reason="fence_or_deadline",
                    now=now,
                )
                try:
                    self.release(claim, now=now)
                except Exception:
                    pass
                raise
            except BaseException as exc:
                heartbeat_stop.set()
                heartbeat_thread.join(timeout=duration)
                cancelled = type(exc).__name__ in {
                    "CancelledError",
                    "GeneratorExit",
                    "KeyboardInterrupt",
                }
                reason = (
                    "single_flight_cancelled"
                    if cancelled
                    else "single_flight_execution_failed"
                )
                self.complete_attempt(
                    attempt,
                    status=(
                        AttemptStatus.CANCELLED
                        if cancelled
                        else AttemptStatus.FAILED
                    ),
                    error_reason=reason,
                    now=now,
                )
                try:
                    self.publish_error(
                        claim,
                        reason_code=reason,
                        now=now,
                        outcome_ttl_seconds=outcome_ttl_seconds,
                    )
                except BaseException:
                    # Preserve the leader's original failure.  Waiters take over
                    # after the fenced/expired lease when an error cannot publish.
                    try:
                        self.release(claim, now=now)
                    except Exception:
                        pass
                raise
            finally:
                heartbeat_stop.set()
                if heartbeat_thread.is_alive():
                    heartbeat_thread.join(timeout=duration)

    get_or_compute = coordinate
    single_flight = coordinate
    execute_single_flight = coordinate


def build_duckdb_proof_coordinator(
    store: DuckDBProofStore | None = None,
    **kwargs: Any,
) -> DuckDBProofCoordinator:
    """Construct a :class:`DuckDBProofCoordinator` with standard defaults."""

    return DuckDBProofCoordinator(store, **kwargs)


__all__ = [
    "COORDINATION_CATALOG_DDL",
    "COORDINATION_CATALOG_TABLES",
    "DEFAULT_LEASE_SECONDS",
    "DEFAULT_OUTCOME_TTL_SECONDS",
    "DEFAULT_POLL_INTERVAL_SECONDS",
    "DEFAULT_WAIT_TIMEOUT_SECONDS",
    "DUCKDB_PROOF_COORDINATION_INTERFACE",
    "DUCKDB_PROOF_COORDINATION_SCHEMA_VERSION",
    "AttemptStatus",
    "ClaimStatus",
    "DuckDBProofCoordinator",
    "ExpiredFenceError",
    "FlightOutcomeStatus",
    "PROOF_ATTEMPT_RECORD_SCHEMA",
    "PROOF_FLIGHT_OUTCOME_SCHEMA",
    "PROOF_INVALIDATION_RECORD_SCHEMA",
    "ProofAttemptRecord",
    "ProofCoordinationCancelled",
    "ProofCoordinationError",
    "ProofCoordinationExecutionError",
    "ProofCoordinationResult",
    "ProofCoordinationTimeout",
    "ProofFenceClaim",
    "ProofFlightOutcome",
    "ProofInvalidationRecord",
    "StaleFenceError",
    "build_duckdb_proof_coordinator",
    "negative_cache_ttl_for",
]
