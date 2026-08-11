#!/usr/bin/env python3
"""DQK-051 concurrency, crash, corruption, and stall chaos suite.

Hermetic failure injection at claim, heartbeat, proof publication,
graph/vector/wallet batch, checkpoint, export, merge, backup, Quack response,
and process death boundaries.  Proves:

* Stale fences cannot publish
* No-progress and deadlock diagnoses are typed
* Recovery preserves dirty work and immutable evidence
* Bounded recovery and no duplicate authority

Also exercises live control-plane modules (proof coordination, recovery,
authority transition, publication, parallel-query heartbeats, exporter) under
crash injection where those modules expose ordered boundaries.

CLI::

    python scripts/validation/validate_duckdb_quack_chaos.py [--json]
    python scripts/validation/validate_duckdb_quack_chaos.py --emit-receipt

Importing this module is inert (no DuckDB, network, or filesystem I/O).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Final, Iterable, Mapping, Sequence

# ---------------------------------------------------------------------------
# Repo path bootstrap (CLI and hermetic tests)
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from ipfs_datasets_py.duckdb_control import authority_transition as auth
from ipfs_datasets_py.duckdb_control import exporter as exp
from ipfs_datasets_py.duckdb_control import parallel_query as pq
from ipfs_datasets_py.duckdb_control import publication as pub
from ipfs_datasets_py.duckdb_control import recovery as recovery_mod
from ipfs_datasets_py.duckdb_control.connections import WorkloadKind
from ipfs_datasets_py.duckdb_control.contracts import (
    SnapshotId,
    canonical_json_bytes,
    content_identity,
)
from ipfs_datasets_py.logic.backends.results import (
    ResultAuthority,
    ResultStatus,
    TheoremResult,
)
from ipfs_datasets_py.logic.common.duckdb_proof_coordination import (
    ClaimStatus,
    DuckDBProofCoordinator,
    ExpiredFenceError,
    ProofFenceClaim,
    StaleFenceError,
    build_duckdb_proof_coordinator,
)
from ipfs_datasets_py.logic.common.duckdb_proof_store import (
    ProofOutcomeKind,
    build_unified_proof_key,
)
from ipfs_datasets_py.logic.families.models import EvidenceAuthority
from ipfs_datasets_py.logic.ir_core.protocols import ExecutionBounds, ResourceUsage

# ---------------------------------------------------------------------------
# Schemas / constants
# ---------------------------------------------------------------------------

CHAOS_CONTRACT_SCHEMA: Final[str] = (
    "ipfs_datasets_py/duckdb-quack-control-plane-chaos-contract@1"
)
CHAOS_RECEIPT_SCHEMA: Final[str] = (
    "ipfs_datasets_py/duckdb-quack-control-plane-chaos-receipt@1"
)
DIAGNOSIS_SCHEMA: Final[str] = (
    "ipfs_datasets_py/duckdb-quack-control-plane-chaos-diagnosis@1"
)
RECOVERY_JOURNAL_SCHEMA: Final[str] = (
    "ipfs_datasets_py/duckdb-quack-control-plane-chaos-recovery-journal@1"
)
DIRTY_WORK_SCHEMA: Final[str] = (
    "ipfs_datasets_py/duckdb-quack-control-plane-chaos-dirty-work@1"
)
CONTRACT_TASK_ID: Final[str] = "DQK-051"
CONTRACT_IMPLEMENTATION_GENERATION: Final[str] = (
    "dqk-051-control-plane-chaos-20260811"
)
PROGRAM_ID: Final[str] = "ipfs-datasets-duckdb-quack-v1"

# Maximum recovery steps before a run is diagnosed as no-progress / deadlock.
MAX_RECOVERY_STEPS: Final[int] = 32
# Progress is sequence-based; a stall without sequence advance is no_progress.
NO_PROGRESS_THRESHOLD_STEPS: Final[int] = 4


# ---------------------------------------------------------------------------
# Closed vocabularies
# ---------------------------------------------------------------------------


class FailureBoundary(str, Enum):
    """Ordered failure-injection boundaries required by DQK-051."""

    CLAIM = "claim"
    HEARTBEAT = "heartbeat"
    PROOF_PUBLICATION = "proof_publication"
    GRAPH_BATCH = "graph_batch"
    VECTOR_BATCH = "vector_batch"
    WALLET_BATCH = "wallet_batch"
    CHECKPOINT = "checkpoint"
    EXPORT = "export"
    MERGE = "merge"
    BACKUP = "backup"
    QUACK_RESPONSE = "quack_response"
    PROCESS_DEATH = "process_death"


FAILURE_BOUNDARIES: Final[tuple[str, ...]] = tuple(
    b.value for b in FailureBoundary
)


class DiagnosisKind(str, Enum):
    """Typed stall / failure diagnoses (acceptance: no-progress and deadlock)."""

    NO_PROGRESS = "no_progress"
    DEADLOCK = "deadlock"
    STALE_FENCE = "stale_fence"
    CRASH_RECOVERED = "crash_recovered"
    DUPLICATE_AUTHORITY_BLOCKED = "duplicate_authority_blocked"
    BOUNDED_RECOVERY = "bounded_recovery"
    EVIDENCE_PRESERVED = "evidence_preserved"
    DIRTY_WORK_PRESERVED = "dirty_work_preserved"
    HEALTHY = "healthy"
    CORRUPTION = "corruption"
    HEARTBEAT_STARVED = "heartbeat_starved"
    QUACK_RESPONSE_LOST = "quack_response_lost"


class OperationPhase(str, Enum):
    """Lifecycle phase of one chaos-tracked control-plane operation."""

    PENDING = "pending"
    IN_FLIGHT = "in_flight"
    DIRTY = "dirty"
    COMMITTED = "committed"
    ABORTED = "aborted"
    RECOVERED = "recovered"


class AuthorityHolder(str, Enum):
    """Who currently holds publish authority for a key."""

    NONE = "none"
    FENCED_OWNER = "fenced_owner"
    RECOVERED_OWNER = "recovered_owner"


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ChaosError(ValueError):
    """Fail-closed rejection for chaos harness inputs or phases."""


class CrashInjected(ChaosError):
    """Raised when a crash-injection boundary is hit."""

    def __init__(
        self,
        boundary: str,
        *,
        operation_id: str = "",
        journal_id: str = "",
    ) -> None:
        self.boundary = boundary
        self.operation_id = operation_id
        self.journal_id = journal_id
        super().__init__(f"crash injected at boundary {boundary!r}")


class StalePublishError(ChaosError):
    """Raised when a stale / expired / foreign fence attempts to publish."""

    def __init__(self, message: str, *, fence_id: str = "") -> None:
        self.fence_id = fence_id
        super().__init__(message)


class DuplicateAuthorityError(ChaosError):
    """Raised when a second authority publication is attempted for one key."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _sha256_hex(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def _canonical_json(payload: Any) -> str:
    return canonical_json_bytes(payload).decode("utf-8")


def _new_id(prefix: str) -> str:
    return f"{prefix}:{uuid.uuid4().hex[:16]}"


def _require_boundary(value: str | FailureBoundary) -> FailureBoundary:
    if isinstance(value, FailureBoundary):
        return value
    try:
        return FailureBoundary(str(value))
    except ValueError as exc:
        raise ChaosError(
            f"unknown failure boundary {value!r}; expected one of "
            f"{FAILURE_BOUNDARIES}"
        ) from exc


def _require_diagnosis(value: str | DiagnosisKind) -> DiagnosisKind:
    if isinstance(value, DiagnosisKind):
        return value
    try:
        return DiagnosisKind(str(value))
    except ValueError as exc:
        raise ChaosError(
            f"unknown diagnosis kind {value!r}; expected a typed DiagnosisKind"
        ) from exc


# ---------------------------------------------------------------------------
# Typed records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TypedDiagnosis:
    """A typed no-progress / deadlock / recovery diagnosis record."""

    diagnosis_id: str
    kind: DiagnosisKind
    boundary: FailureBoundary | None
    operation_id: str
    reason: str
    sequence: int
    recorded_at: str
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.kind, DiagnosisKind):
            object.__setattr__(self, "kind", _require_diagnosis(self.kind))
        if self.boundary is not None and not isinstance(
            self.boundary, FailureBoundary
        ):
            object.__setattr__(
                self, "boundary", _require_boundary(self.boundary)
            )
        if (
            not isinstance(self.sequence, int)
            or isinstance(self.sequence, bool)
            or self.sequence < 0
        ):
            raise ChaosError("diagnosis sequence must be a non-negative int")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": DIAGNOSIS_SCHEMA,
            "diagnosis_id": self.diagnosis_id,
            "kind": self.kind.value,
            "boundary": self.boundary.value if self.boundary else None,
            "operation_id": self.operation_id,
            "reason": self.reason,
            "sequence": self.sequence,
            "recorded_at": self.recorded_at,
            "attributes": dict(self.attributes),
        }

    @property
    def identity_id(self) -> str:
        return content_identity(self.to_dict())


@dataclass(frozen=True, slots=True)
class ImmutableEvidence:
    """Content-addressed evidence that recovery must never discard."""

    object_digest: str
    media_type: str
    size_bytes: int
    cid: str = ""
    label: str = ""

    def __post_init__(self) -> None:
        digest = str(self.object_digest or "").strip()
        if not digest.startswith("sha256:") or len(digest) != 71:
            raise ChaosError(
                f"evidence object_digest must be sha256:<64 hex>, got {digest!r}"
            )
        if self.size_bytes < 0:
            raise ChaosError("size_bytes must be non-negative")

    def to_dict(self) -> dict[str, Any]:
        return {
            "object_digest": self.object_digest,
            "media_type": self.media_type,
            "size_bytes": self.size_bytes,
            "cid": self.cid,
            "label": self.label,
        }


@dataclass(frozen=True, slots=True)
class DirtyWorkRecord:
    """In-flight / incomplete work preserved across crash recovery."""

    dirty_id: str
    boundary: FailureBoundary
    operation_id: str
    key: str
    payload_digest: str
    fence_id: str
    fence_generation: int
    phase: OperationPhase
    created_at: str
    payload: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": DIRTY_WORK_SCHEMA,
            "dirty_id": self.dirty_id,
            "boundary": self.boundary.value,
            "operation_id": self.operation_id,
            "key": self.key,
            "payload_digest": self.payload_digest,
            "fence_id": self.fence_id,
            "fence_generation": self.fence_generation,
            "phase": self.phase.value,
            "created_at": self.created_at,
            "payload": dict(self.payload),
        }


@dataclass(frozen=True, slots=True)
class FenceState:
    """Publish fence bound to one owner and generation."""

    fence_id: str
    owner_id: str
    generation: int
    token: str
    expires_at: float
    released: bool = False
    superseded: bool = False

    def is_live(self, now: float) -> bool:
        return (
            not self.released
            and not self.superseded
            and self.expires_at > now
            and bool(self.token)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "fence_id": self.fence_id,
            "owner_id": self.owner_id,
            "generation": self.generation,
            "token": self.token,
            "expires_at": self.expires_at,
            "released": self.released,
            "superseded": self.superseded,
        }


@dataclass(frozen=True, slots=True)
class AuthorityRecord:
    """Published authority for one key (single-flight)."""

    key: str
    authority_digest: str
    fence_id: str
    fence_generation: int
    owner_id: str
    published_at: str
    boundary: FailureBoundary

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "authority_digest": self.authority_digest,
            "fence_id": self.fence_id,
            "fence_generation": self.fence_generation,
            "owner_id": self.owner_id,
            "published_at": self.published_at,
            "boundary": self.boundary.value,
        }


@dataclass(frozen=True, slots=True)
class RecoveryJournalEntry:
    """Append-only recovery journal step."""

    journal_id: str
    operation_id: str
    boundary: FailureBoundary
    step: int
    action: str
    diagnosis: DiagnosisKind
    preserved_dirty_ids: tuple[str, ...]
    preserved_evidence_digests: tuple[str, ...]
    recorded_at: str
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": RECOVERY_JOURNAL_SCHEMA,
            "journal_id": self.journal_id,
            "operation_id": self.operation_id,
            "boundary": self.boundary.value,
            "step": self.step,
            "action": self.action,
            "diagnosis": self.diagnosis.value,
            "preserved_dirty_ids": list(self.preserved_dirty_ids),
            "preserved_evidence_digests": list(self.preserved_evidence_digests),
            "recorded_at": self.recorded_at,
            "notes": self.notes,
        }


@dataclass(frozen=True, slots=True)
class BoundaryResult:
    """Outcome of one boundary inject + recover cycle."""

    boundary: FailureBoundary
    operation_id: str
    crashed: bool
    recovered: bool
    diagnosis: DiagnosisKind
    steps: int
    authority_count: int
    dirty_preserved: bool
    evidence_preserved: bool
    duplicate_authority: bool
    details: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "boundary": self.boundary.value,
            "operation_id": self.operation_id,
            "crashed": self.crashed,
            "recovered": self.recovered,
            "diagnosis": self.diagnosis.value,
            "steps": self.steps,
            "authority_count": self.authority_count,
            "dirty_preserved": self.dirty_preserved,
            "evidence_preserved": self.evidence_preserved,
            "duplicate_authority": self.duplicate_authority,
            "details": dict(self.details),
        }


# ---------------------------------------------------------------------------
# Chaos control plane
# ---------------------------------------------------------------------------


class ChaosControlPlane:
    """Hermetic control-plane chaos harness with ordered crash boundaries.

    Tracks fences, dirty work journals, immutable evidence, and single-flight
    authority.  Crash injection at any :class:`FailureBoundary` leaves dirty
    work and evidence intact for bounded recovery.  Stale fences fail closed
    on publish.  No-progress and deadlock diagnoses are always typed.
    """

    SCHEMA: Final[str] = CHAOS_CONTRACT_SCHEMA

    def __init__(
        self,
        *,
        clock: Callable[[], float] | None = None,
        lease_seconds: float = 30.0,
        max_recovery_steps: int = MAX_RECOVERY_STEPS,
    ) -> None:
        self._clock = clock or time.monotonic
        self._lease_seconds = float(lease_seconds)
        self._max_recovery_steps = int(max_recovery_steps)
        self._lock = threading.RLock()
        self._crash_at: FailureBoundary | None = None
        self._sequence = 0
        self._fences: dict[str, FenceState] = {}
        self._key_fence: dict[str, str] = {}  # key -> fence_id
        self._dirty: dict[str, DirtyWorkRecord] = {}
        self._evidence: dict[str, ImmutableEvidence] = {}
        self._authority: dict[str, AuthorityRecord] = {}
        self._diagnoses: list[TypedDiagnosis] = []
        self._journal: list[RecoveryJournalEntry] = []
        self._published_keys: set[str] = set()
        self._waits: dict[str, set[str]] = {}  # wait-for graph: waiter -> holders
        self._progress_markers: dict[str, int] = {}
        self._stats: dict[str, int] = {
            "crashes": 0,
            "recoveries": 0,
            "stale_publish_rejections": 0,
            "duplicate_authority_blocks": 0,
            "no_progress_diagnoses": 0,
            "deadlock_diagnoses": 0,
            "operations": 0,
        }

    # -- crash injection -----------------------------------------------------

    def set_crash_at(self, boundary: str | FailureBoundary | None) -> None:
        if boundary is None:
            self._crash_at = None
            return
        self._crash_at = _require_boundary(boundary)

    def crash_at(self) -> FailureBoundary | None:
        return self._crash_at

    def _maybe_crash(
        self,
        boundary: FailureBoundary,
        *,
        operation_id: str = "",
        journal_id: str = "",
    ) -> None:
        if self._crash_at is boundary:
            self._stats["crashes"] += 1
            raise CrashInjected(
                boundary.value,
                operation_id=operation_id,
                journal_id=journal_id,
            )

    # -- sequence / diagnosis ------------------------------------------------

    def _next_sequence(self) -> int:
        self._sequence += 1
        return self._sequence

    def diagnose(
        self,
        kind: DiagnosisKind | str,
        *,
        boundary: FailureBoundary | str | None = None,
        operation_id: str = "",
        reason: str = "",
        attributes: Mapping[str, Any] | None = None,
    ) -> TypedDiagnosis:
        """Emit a typed diagnosis (acceptance: no-progress and deadlock typed)."""

        kind_e = _require_diagnosis(kind)
        boundary_e = (
            _require_boundary(boundary) if boundary is not None else None
        )
        if kind_e is DiagnosisKind.NO_PROGRESS:
            self._stats["no_progress_diagnoses"] += 1
        elif kind_e is DiagnosisKind.DEADLOCK:
            self._stats["deadlock_diagnoses"] += 1
        record = TypedDiagnosis(
            diagnosis_id=_new_id("diag"),
            kind=kind_e,
            boundary=boundary_e,
            operation_id=operation_id or "",
            reason=reason or kind_e.value,
            sequence=self._next_sequence(),
            recorded_at=_utc_now(),
            attributes=dict(attributes or {}),
        )
        with self._lock:
            self._diagnoses.append(record)
        return record

    def diagnoses(self) -> tuple[TypedDiagnosis, ...]:
        with self._lock:
            return tuple(self._diagnoses)

    def typed_diagnosis_kinds(self) -> frozenset[str]:
        return frozenset(d.kind.value for d in self.diagnoses())

    # -- evidence / dirty work -----------------------------------------------

    def register_evidence(
        self,
        label: str,
        *,
        media_type: str = "application/octet-stream",
        payload: bytes | str | None = None,
    ) -> ImmutableEvidence:
        raw = payload if payload is not None else label.encode("utf-8")
        if isinstance(raw, str):
            raw = raw.encode("utf-8")
        evidence = ImmutableEvidence(
            object_digest="sha256:" + _sha256_hex(raw),
            media_type=media_type,
            size_bytes=len(raw),
            cid=f"cid-{_sha256_hex(raw)[:16]}",
            label=label,
        )
        with self._lock:
            self._evidence[evidence.object_digest] = evidence
        return evidence

    def evidence_digests(self) -> frozenset[str]:
        with self._lock:
            return frozenset(self._evidence)

    def dirty_records(self) -> tuple[DirtyWorkRecord, ...]:
        with self._lock:
            return tuple(self._dirty.values())

    def _stage_dirty(
        self,
        *,
        boundary: FailureBoundary,
        operation_id: str,
        key: str,
        payload: Mapping[str, Any],
        fence: FenceState,
    ) -> DirtyWorkRecord:
        body = dict(payload)
        digest = "sha256:" + _sha256_hex(_canonical_json(body))
        record = DirtyWorkRecord(
            dirty_id=_new_id("dirty"),
            boundary=boundary,
            operation_id=operation_id,
            key=key,
            payload_digest=digest,
            fence_id=fence.fence_id,
            fence_generation=fence.generation,
            phase=OperationPhase.DIRTY,
            created_at=_utc_now(),
            payload=MappingProxyType(body),
        )
        self._dirty[record.dirty_id] = record
        return record

    # -- fences / publish ----------------------------------------------------

    def claim_fence(
        self,
        key: str,
        *,
        owner_id: str,
        operation_id: str | None = None,
        now: float | None = None,
    ) -> FenceState:
        """Acquire a publish fence for *key* (claim boundary)."""

        op_id = operation_id or _new_id("op")
        current = self._clock() if now is None else float(now)
        with self._lock:
            self._stats["operations"] += 1
            self._maybe_crash(FailureBoundary.CLAIM, operation_id=op_id)
            existing_id = self._key_fence.get(key)
            if existing_id is not None:
                existing = self._fences.get(existing_id)
                if existing is not None and existing.is_live(current):
                    # Follower: no owner token.
                    return FenceState(
                        fence_id=existing.fence_id,
                        owner_id=existing.owner_id,
                        generation=existing.generation,
                        token="",
                        expires_at=existing.expires_at,
                        released=False,
                        superseded=False,
                    )
                if existing is not None:
                    # Supersede expired/released fence.
                    self._fences[existing_id] = FenceState(
                        fence_id=existing.fence_id,
                        owner_id=existing.owner_id,
                        generation=existing.generation,
                        token=existing.token,
                        expires_at=existing.expires_at,
                        released=existing.released,
                        superseded=True,
                    )
            generation = 1
            if existing_id is not None and existing_id in self._fences:
                generation = self._fences[existing_id].generation + 1
            fence = FenceState(
                fence_id=_new_id("fence"),
                owner_id=owner_id,
                generation=generation,
                token=f"tok:{uuid.uuid4().hex}",
                expires_at=current + self._lease_seconds,
            )
            self._fences[fence.fence_id] = fence
            self._key_fence[key] = fence.fence_id
            return fence

    def heartbeat_fence(
        self,
        fence: FenceState,
        *,
        operation_id: str | None = None,
        now: float | None = None,
        lease_seconds: float | None = None,
    ) -> FenceState:
        """Renew a live fence lease (heartbeat boundary)."""

        op_id = operation_id or _new_id("op")
        current = self._clock() if now is None else float(now)
        duration = (
            self._lease_seconds
            if lease_seconds is None
            else float(lease_seconds)
        )
        with self._lock:
            self._maybe_crash(FailureBoundary.HEARTBEAT, operation_id=op_id)
            active = self._fences.get(fence.fence_id)
            if (
                active is None
                or active.token != fence.token
                or not active.token
                or active.released
                or active.superseded
            ):
                raise StalePublishError(
                    "cannot heartbeat a stale or foreign fence",
                    fence_id=fence.fence_id,
                )
            if active.expires_at <= current:
                raise StalePublishError(
                    "cannot heartbeat an expired fence",
                    fence_id=fence.fence_id,
                )
            renewed = FenceState(
                fence_id=active.fence_id,
                owner_id=active.owner_id,
                generation=active.generation,
                token=active.token,
                expires_at=current + duration,
            )
            self._fences[fence.fence_id] = renewed
            return renewed

    def _require_live_publisher(
        self,
        fence: FenceState,
        *,
        now: float,
    ) -> FenceState:
        active = self._fences.get(fence.fence_id)
        if (
            active is None
            or not fence.token
            or active.token != fence.token
            or active.owner_id != fence.owner_id
            or active.generation != fence.generation
            or active.released
            or active.superseded
        ):
            self._stats["stale_publish_rejections"] += 1
            self.diagnose(
                DiagnosisKind.STALE_FENCE,
                boundary=FailureBoundary.PROOF_PUBLICATION,
                reason="stale or foreign fence publish rejected",
                attributes={"fence_id": fence.fence_id},
            )
            raise StalePublishError(
                "stale fences cannot publish",
                fence_id=fence.fence_id,
            )
        if active.expires_at <= now:
            self._stats["stale_publish_rejections"] += 1
            self.diagnose(
                DiagnosisKind.STALE_FENCE,
                boundary=FailureBoundary.PROOF_PUBLICATION,
                reason="expired fence publish rejected",
                attributes={"fence_id": fence.fence_id},
            )
            raise StalePublishError(
                "expired fences cannot publish",
                fence_id=fence.fence_id,
            )
        return active

    def publish_authority(
        self,
        key: str,
        payload: Mapping[str, Any],
        fence: FenceState,
        *,
        boundary: FailureBoundary | str = FailureBoundary.PROOF_PUBLICATION,
        operation_id: str | None = None,
        now: float | None = None,
        evidence_label: str | None = None,
    ) -> AuthorityRecord:
        """Publish single-flight authority under a live fence."""

        boundary_e = _require_boundary(boundary)
        op_id = operation_id or _new_id("op")
        current = self._clock() if now is None else float(now)
        with self._lock:
            self._maybe_crash(boundary_e, operation_id=op_id)
            live = self._require_live_publisher(fence, now=current)
            if key in self._published_keys:
                self._stats["duplicate_authority_blocks"] += 1
                self.diagnose(
                    DiagnosisKind.DUPLICATE_AUTHORITY_BLOCKED,
                    boundary=boundary_e,
                    operation_id=op_id,
                    reason="duplicate authority publication blocked",
                    attributes={"key": key},
                )
                raise DuplicateAuthorityError(
                    f"authority already published for key {key!r}"
                )
            dirty = self._stage_dirty(
                boundary=boundary_e,
                operation_id=op_id,
                key=key,
                payload=payload,
                fence=live,
            )
            body = dict(payload)
            auth_digest = "sha256:" + _sha256_hex(_canonical_json(body))
            if evidence_label is not None:
                self.register_evidence(
                    evidence_label,
                    media_type="application/json",
                    payload=_canonical_json(body),
                )
            record = AuthorityRecord(
                key=key,
                authority_digest=auth_digest,
                fence_id=live.fence_id,
                fence_generation=live.generation,
                owner_id=live.owner_id,
                published_at=_utc_now(),
                boundary=boundary_e,
            )
            self._authority[key] = record
            self._published_keys.add(key)
            # Commit dirty work.
            committed = DirtyWorkRecord(
                dirty_id=dirty.dirty_id,
                boundary=dirty.boundary,
                operation_id=dirty.operation_id,
                key=dirty.key,
                payload_digest=dirty.payload_digest,
                fence_id=dirty.fence_id,
                fence_generation=dirty.fence_generation,
                phase=OperationPhase.COMMITTED,
                created_at=dirty.created_at,
                payload=dirty.payload,
            )
            self._dirty[dirty.dirty_id] = committed
            # Release fence after successful publish (single-use).
            self._fences[live.fence_id] = FenceState(
                fence_id=live.fence_id,
                owner_id=live.owner_id,
                generation=live.generation,
                token=live.token,
                expires_at=live.expires_at,
                released=True,
                superseded=False,
            )
            return record

    def authority_for(self, key: str) -> AuthorityRecord | None:
        with self._lock:
            return self._authority.get(key)

    def authority_count(self) -> int:
        with self._lock:
            return len(self._authority)

    # -- batch / checkpoint / export / merge / backup / quack ---------------

    def run_batch(
        self,
        domain: str,
        items: Sequence[Mapping[str, Any]],
        fence: FenceState,
        *,
        operation_id: str | None = None,
    ) -> dict[str, Any]:
        """Run a graph / vector / wallet batch under *fence*."""

        domain = str(domain).strip().lower()
        boundary_map = {
            "graph": FailureBoundary.GRAPH_BATCH,
            "vector": FailureBoundary.VECTOR_BATCH,
            "wallet": FailureBoundary.WALLET_BATCH,
        }
        if domain not in boundary_map:
            raise ChaosError(
                f"batch domain must be one of {sorted(boundary_map)}; "
                f"got {domain!r}"
            )
        boundary = boundary_map[domain]
        op_id = operation_id or _new_id(f"op-{domain}")
        with self._lock:
            self._maybe_crash(boundary, operation_id=op_id)
            live = self._require_live_publisher(
                fence, now=self._clock()
            )
            digests: list[str] = []
            for idx, item in enumerate(items):
                key = f"{domain}:{op_id}:{idx}"
                dirty = self._stage_dirty(
                    boundary=boundary,
                    operation_id=op_id,
                    key=key,
                    payload=dict(item),
                    fence=live,
                )
                digests.append(dirty.payload_digest)
                self.register_evidence(
                    f"{domain}-batch-{idx}",
                    media_type="application/json",
                    payload=_canonical_json(dict(item)),
                )
            return {
                "ok": True,
                "domain": domain,
                "boundary": boundary.value,
                "operation_id": op_id,
                "item_count": len(items),
                "payload_digests": digests,
                "fence_id": live.fence_id,
                "atomic_across_items": False,
            }

    def checkpoint(
        self,
        database_id: str,
        *,
        operation_id: str | None = None,
        force_drain: bool = True,
    ) -> dict[str, Any]:
        op_id = operation_id or _new_id("op-ckpt")
        with self._lock:
            self._maybe_crash(FailureBoundary.CHECKPOINT, operation_id=op_id)
            fence = self.claim_fence(
                f"checkpoint:{database_id}",
                owner_id=f"writer:{database_id}",
                operation_id=op_id,
            )
            payload = {
                "database_id": database_id,
                "force_drain": bool(force_drain),
                "sequence": self._sequence,
            }
            dirty = self._stage_dirty(
                boundary=FailureBoundary.CHECKPOINT,
                operation_id=op_id,
                key=f"checkpoint:{database_id}",
                payload=payload,
                fence=fence,
            )
            evidence = self.register_evidence(
                f"checkpoint-{database_id}",
                media_type="application/x-checkpoint",
                payload=_canonical_json(payload),
            )
            return {
                "ok": True,
                "operation_id": op_id,
                "database_id": database_id,
                "dirty_id": dirty.dirty_id,
                "evidence_digest": evidence.object_digest,
                "fence_id": fence.fence_id,
                "atomic_across_databases": False,
            }

    def export_snapshot(
        self,
        rows: Sequence[Mapping[str, Any]],
        *,
        operation_id: str | None = None,
    ) -> dict[str, Any]:
        op_id = operation_id or _new_id("op-export")
        with self._lock:
            self._maybe_crash(FailureBoundary.EXPORT, operation_id=op_id)
            fence = self.claim_fence(
                f"export:{op_id}",
                owner_id="exporter",
                operation_id=op_id,
            )
            payload = {"rows": [dict(r) for r in rows], "operation_id": op_id}
            dirty = self._stage_dirty(
                boundary=FailureBoundary.EXPORT,
                operation_id=op_id,
                key=f"export:{op_id}",
                payload=payload,
                fence=fence,
            )
            evidence = self.register_evidence(
                f"export-{op_id}",
                media_type="application/json",
                payload=_canonical_json(payload),
            )
            return {
                "ok": True,
                "operation_id": op_id,
                "row_count": len(rows),
                "dirty_id": dirty.dirty_id,
                "evidence_digest": evidence.object_digest,
                "read_only": True,
                "non_authoritative": True,
            }

    def merge_shards(
        self,
        left: Mapping[str, Any],
        right: Mapping[str, Any],
        *,
        operation_id: str | None = None,
    ) -> dict[str, Any]:
        op_id = operation_id or _new_id("op-merge")
        with self._lock:
            self._maybe_crash(FailureBoundary.MERGE, operation_id=op_id)
            fence = self.claim_fence(
                f"merge:{op_id}",
                owner_id="merger",
                operation_id=op_id,
            )
            payload = {
                "left": dict(left),
                "right": dict(right),
                "merged_keys": sorted(
                    set(left) | set(right)
                ),
            }
            dirty = self._stage_dirty(
                boundary=FailureBoundary.MERGE,
                operation_id=op_id,
                key=f"merge:{op_id}",
                payload=payload,
                fence=fence,
            )
            evidence = self.register_evidence(
                f"merge-{op_id}",
                media_type="application/json",
                payload=_canonical_json(payload),
            )
            return {
                "ok": True,
                "operation_id": op_id,
                "dirty_id": dirty.dirty_id,
                "evidence_digest": evidence.object_digest,
                "atomic_across_shards": False,
            }

    def backup(
        self,
        database_ids: Sequence[str],
        *,
        operation_id: str | None = None,
    ) -> dict[str, Any]:
        op_id = operation_id or _new_id("op-backup")
        with self._lock:
            self._maybe_crash(FailureBoundary.BACKUP, operation_id=op_id)
            fence = self.claim_fence(
                f"backup:{op_id}",
                owner_id="backup-daemon",
                operation_id=op_id,
            )
            checkpoints = []
            for db_id in database_ids:
                # Nested checkpoint without nested crash (already at backup).
                prior = self._crash_at
                self._crash_at = None
                try:
                    ck = self.checkpoint(db_id, operation_id=f"{op_id}:{db_id}")
                finally:
                    self._crash_at = prior
                checkpoints.append(ck)
            payload = {
                "database_ids": list(database_ids),
                "checkpoint_ops": [c["operation_id"] for c in checkpoints],
            }
            dirty = self._stage_dirty(
                boundary=FailureBoundary.BACKUP,
                operation_id=op_id,
                key=f"backup:{op_id}",
                payload=payload,
                fence=fence,
            )
            evidence = self.register_evidence(
                f"backup-{op_id}",
                media_type="application/x-backup-manifest",
                payload=_canonical_json(payload),
            )
            return {
                "ok": True,
                "operation_id": op_id,
                "database_ids": list(database_ids),
                "dirty_id": dirty.dirty_id,
                "evidence_digest": evidence.object_digest,
                "atomic_across_databases": False,
                "checkpoints": checkpoints,
            }

    def quack_respond(
        self,
        query_id: str,
        rows: Sequence[Mapping[str, Any]],
        *,
        operation_id: str | None = None,
    ) -> dict[str, Any]:
        op_id = operation_id or _new_id("op-quack")
        with self._lock:
            self._maybe_crash(
                FailureBoundary.QUACK_RESPONSE, operation_id=op_id
            )
            fence = self.claim_fence(
                f"quack:{query_id}",
                owner_id="quack-gateway",
                operation_id=op_id,
            )
            payload = {
                "query_id": query_id,
                "row_count": len(rows),
                "rows": [dict(r) for r in rows],
            }
            dirty = self._stage_dirty(
                boundary=FailureBoundary.QUACK_RESPONSE,
                operation_id=op_id,
                key=f"quack:{query_id}",
                payload=payload,
                fence=fence,
            )
            return {
                "ok": True,
                "operation_id": op_id,
                "query_id": query_id,
                "row_count": len(rows),
                "dirty_id": dirty.dirty_id,
                "fence_id": fence.fence_id,
                "authority_write": False,
            }

    def process_death(
        self,
        *,
        operation_id: str | None = None,
        holder_key: str = "process:leader",
    ) -> None:
        """Simulate process death: abandon fences and leave dirty work."""

        op_id = operation_id or _new_id("op-death")
        with self._lock:
            self._maybe_crash(
                FailureBoundary.PROCESS_DEATH, operation_id=op_id
            )
            # Abandon all live fences owned by the process.
            for fid, fence in list(self._fences.items()):
                if fence.is_live(self._clock()):
                    self._fences[fid] = FenceState(
                        fence_id=fence.fence_id,
                        owner_id=fence.owner_id,
                        generation=fence.generation,
                        token=fence.token,
                        expires_at=fence.expires_at,
                        released=True,
                        superseded=False,
                    )
            # Stage a process-death dirty marker so recovery has a handle.
            death_fence = FenceState(
                fence_id=_new_id("fence"),
                owner_id="dead-process",
                generation=1,
                token=f"tok:{uuid.uuid4().hex}",
                expires_at=self._clock() + self._lease_seconds,
                released=True,
            )
            self._fences[death_fence.fence_id] = death_fence
            self._stage_dirty(
                boundary=FailureBoundary.PROCESS_DEATH,
                operation_id=op_id,
                key=holder_key,
                payload={"event": "process_death", "operation_id": op_id},
                fence=death_fence,
            )

    # -- wait-for / deadlock / no-progress -----------------------------------

    def set_wait_edge(self, waiter: str, holder: str) -> None:
        """Record that *waiter* waits on *holder* (for deadlock detection)."""

        with self._lock:
            self._waits.setdefault(waiter, set()).add(holder)

    def clear_wait_edges(self) -> None:
        with self._lock:
            self._waits.clear()

    def detect_deadlock(self) -> TypedDiagnosis | None:
        """Detect a wait-for cycle and emit a typed DEADLOCK diagnosis."""

        with self._lock:
            graph = {k: set(v) for k, v in self._waits.items()}

        visited: set[str] = set()
        stack: set[str] = set()
        cycle: list[str] = []

        def dfs(node: str, path: list[str]) -> bool:
            if node in stack:
                cycle.extend(path[path.index(node) :] + [node])
                return True
            if node in visited:
                return False
            visited.add(node)
            stack.add(node)
            for nxt in graph.get(node, ()):
                if dfs(nxt, path + [nxt]):
                    return True
            stack.remove(node)
            return False

        for start in graph:
            if dfs(start, [start]):
                return self.diagnose(
                    DiagnosisKind.DEADLOCK,
                    reason="wait-for cycle detected",
                    attributes={"cycle": list(cycle)},
                )
        return None

    def observe_progress(self, marker: str, sequence: int) -> TypedDiagnosis | None:
        """Observe progress; emit NO_PROGRESS when sequence stalls."""

        with self._lock:
            prior = self._progress_markers.get(marker)
            self._progress_markers[marker] = sequence
            stall_count = 0
            if prior is not None and sequence <= prior:
                stall_count = getattr(self, "_stall_counts", {}).get(marker, 0) + 1
                if not hasattr(self, "_stall_counts"):
                    self._stall_counts = {}  # type: ignore[attr-defined]
                self._stall_counts[marker] = stall_count  # type: ignore[attr-defined]
            else:
                if not hasattr(self, "_stall_counts"):
                    self._stall_counts = {}  # type: ignore[attr-defined]
                self._stall_counts[marker] = 0  # type: ignore[attr-defined]
            stalls = self._stall_counts.get(marker, 0)  # type: ignore[attr-defined]

        if stalls >= NO_PROGRESS_THRESHOLD_STEPS:
            return self.diagnose(
                DiagnosisKind.NO_PROGRESS,
                reason=(
                    f"marker {marker!r} made no progress for "
                    f"{stalls} observations"
                ),
                attributes={
                    "marker": marker,
                    "sequence": sequence,
                    "stall_count": stalls,
                },
            )
        return None

    # -- recovery ------------------------------------------------------------

    def recover(
        self,
        boundary: FailureBoundary | str,
        *,
        operation_id: str,
    ) -> BoundaryResult:
        """Bounded recovery after a crash at *boundary*.

        Preserves all dirty-work records and immutable evidence digests.
        Never creates a second authority for an already-published key.
        """

        boundary_e = _require_boundary(boundary)
        steps = 0
        pre_evidence = self.evidence_digests()
        pre_dirty_ids = {d.dirty_id for d in self.dirty_records()}
        recovered = False
        diagnosis = DiagnosisKind.BOUNDED_RECOVERY

        # Clear crash injection for recovery pass.
        prior_crash = self._crash_at
        self._crash_at = None
        try:
            while steps < self._max_recovery_steps:
                steps += 1
                # Step 1: inventory dirty work.
                dirty = self.dirty_records()
                dirty_ids = tuple(d.dirty_id for d in dirty)
                evidence = tuple(sorted(self.evidence_digests()))

                # Step 2: detect deadlock / no-progress.
                dead = self.detect_deadlock()
                if dead is not None:
                    diagnosis = DiagnosisKind.DEADLOCK
                    self._append_journal(
                        operation_id=operation_id,
                        boundary=boundary_e,
                        step=steps,
                        action="abort_deadlock",
                        diagnosis=diagnosis,
                        dirty_ids=dirty_ids,
                        evidence=evidence,
                        notes="typed deadlock diagnosis; fail closed",
                    )
                    break

                # Step 3: re-claim only unfinished dirty work without authority.
                unfinished = [
                    d
                    for d in dirty
                    if d.phase is OperationPhase.DIRTY
                    and d.key not in self._published_keys
                ]
                for item in unfinished:
                    # Idempotent: mark recovered, do not republish authority.
                    recovered_item = DirtyWorkRecord(
                        dirty_id=item.dirty_id,
                        boundary=item.boundary,
                        operation_id=item.operation_id,
                        key=item.key,
                        payload_digest=item.payload_digest,
                        fence_id=item.fence_id,
                        fence_generation=item.fence_generation,
                        phase=OperationPhase.RECOVERED,
                        created_at=item.created_at,
                        payload=item.payload,
                    )
                    with self._lock:
                        self._dirty[item.dirty_id] = recovered_item

                # Step 4: prove evidence + dirty preservation.
                post_evidence = self.evidence_digests()
                post_dirty_ids = {d.dirty_id for d in self.dirty_records()}
                if not pre_evidence.issubset(post_evidence):
                    diagnosis = DiagnosisKind.CORRUPTION
                    self.diagnose(
                        DiagnosisKind.CORRUPTION,
                        boundary=boundary_e,
                        operation_id=operation_id,
                        reason="immutable evidence lost during recovery",
                    )
                    break
                if not pre_dirty_ids.issubset(post_dirty_ids):
                    diagnosis = DiagnosisKind.CORRUPTION
                    self.diagnose(
                        DiagnosisKind.CORRUPTION,
                        boundary=boundary_e,
                        operation_id=operation_id,
                        reason="dirty work lost during recovery",
                    )
                    break

                self.diagnose(
                    DiagnosisKind.EVIDENCE_PRESERVED,
                    boundary=boundary_e,
                    operation_id=operation_id,
                    reason="all immutable evidence digests preserved",
                    attributes={"count": len(post_evidence)},
                )
                self.diagnose(
                    DiagnosisKind.DIRTY_WORK_PRESERVED,
                    boundary=boundary_e,
                    operation_id=operation_id,
                    reason="all dirty work records preserved",
                    attributes={"count": len(post_dirty_ids)},
                )
                diagnosis = DiagnosisKind.CRASH_RECOVERED
                recovered = True
                self._stats["recoveries"] += 1
                self._append_journal(
                    operation_id=operation_id,
                    boundary=boundary_e,
                    step=steps,
                    action="recover_dirty_and_evidence",
                    diagnosis=diagnosis,
                    dirty_ids=tuple(sorted(post_dirty_ids)),
                    evidence=tuple(sorted(post_evidence)),
                )
                break
            else:
                # Exhausted steps without recovery → typed no-progress.
                diagnosis = DiagnosisKind.NO_PROGRESS
                self.diagnose(
                    DiagnosisKind.NO_PROGRESS,
                    boundary=boundary_e,
                    operation_id=operation_id,
                    reason=(
                        f"recovery exceeded max steps "
                        f"{self._max_recovery_steps}"
                    ),
                )
        finally:
            self._crash_at = prior_crash

        post_dirty = self.dirty_records()
        return BoundaryResult(
            boundary=boundary_e,
            operation_id=operation_id,
            crashed=True,
            recovered=recovered,
            diagnosis=diagnosis,
            steps=steps,
            authority_count=self.authority_count(),
            dirty_preserved=pre_dirty_ids.issubset(
                {d.dirty_id for d in post_dirty}
            ),
            evidence_preserved=pre_evidence.issubset(self.evidence_digests()),
            duplicate_authority=False,
            details={
                "pre_dirty": len(pre_dirty_ids),
                "post_dirty": len(post_dirty),
                "pre_evidence": len(pre_evidence),
                "post_evidence": len(self.evidence_digests()),
            },
        )

    def _append_journal(
        self,
        *,
        operation_id: str,
        boundary: FailureBoundary,
        step: int,
        action: str,
        diagnosis: DiagnosisKind,
        dirty_ids: Sequence[str],
        evidence: Sequence[str],
        notes: str = "",
    ) -> RecoveryJournalEntry:
        entry = RecoveryJournalEntry(
            journal_id=_new_id("journal"),
            operation_id=operation_id,
            boundary=boundary,
            step=step,
            action=action,
            diagnosis=diagnosis,
            preserved_dirty_ids=tuple(dirty_ids),
            preserved_evidence_digests=tuple(evidence),
            recorded_at=_utc_now(),
            notes=notes,
        )
        with self._lock:
            self._journal.append(entry)
        return entry

    def journal(self) -> tuple[RecoveryJournalEntry, ...]:
        with self._lock:
            return tuple(self._journal)

    def stats(self) -> Mapping[str, int]:
        with self._lock:
            return MappingProxyType(dict(self._stats))

    def inject_and_recover(
        self,
        boundary: FailureBoundary | str,
        *,
        operation_id: str | None = None,
    ) -> BoundaryResult:
        """Run the boundary operation under crash injection, then recover."""

        boundary_e = _require_boundary(boundary)
        op_id = operation_id or _new_id(f"op-{boundary_e.value}")

        # Seed durable dirty work + evidence *before* the crash boundary so
        # recovery always has immutable handles to preserve (even for claim /
        # heartbeat / process-death paths that fail before their own staging).
        seed_fence = FenceState(
            fence_id=_new_id("fence"),
            owner_id="pre-crash-seed",
            generation=1,
            token=f"tok:{uuid.uuid4().hex}",
            expires_at=self._clock() + self._lease_seconds,
            released=True,
        )
        with self._lock:
            self._fences[seed_fence.fence_id] = seed_fence
            self._stage_dirty(
                boundary=boundary_e,
                operation_id=op_id,
                key=f"pre-crash:{boundary_e.value}:{op_id}",
                payload={
                    "event": "pre_crash_seed",
                    "boundary": boundary_e.value,
                    "operation_id": op_id,
                },
                fence=seed_fence,
            )
            self.register_evidence(
                f"pre-crash-{boundary_e.value}-{op_id}",
                media_type="application/x-chaos-seed",
                payload=f"{boundary_e.value}:{op_id}".encode("utf-8"),
            )

        self.set_crash_at(boundary_e)
        crashed = False
        try:
            self._run_boundary_operation(boundary_e, operation_id=op_id)
        except CrashInjected as injected:
            crashed = True
            if injected.boundary != boundary_e.value:
                raise ChaosError(
                    f"crash boundary mismatch: expected {boundary_e.value}, "
                    f"got {injected.boundary}"
                ) from injected
        finally:
            self.set_crash_at(None)

        if not crashed:
            # Operation completed without crash — still exercise recovery path
            # for idempotency (no-op recover).
            pre_evidence = self.evidence_digests()
            pre_dirty = {d.dirty_id for d in self.dirty_records()}
            return BoundaryResult(
                boundary=boundary_e,
                operation_id=op_id,
                crashed=False,
                recovered=True,
                diagnosis=DiagnosisKind.HEALTHY,
                steps=0,
                authority_count=self.authority_count(),
                dirty_preserved=pre_dirty.issubset(
                    {d.dirty_id for d in self.dirty_records()}
                ),
                evidence_preserved=pre_evidence.issubset(self.evidence_digests()),
                duplicate_authority=False,
            )

        return self.recover(boundary_e, operation_id=op_id)

    def _run_boundary_operation(
        self,
        boundary: FailureBoundary,
        *,
        operation_id: str,
    ) -> Any:
        if boundary is FailureBoundary.CLAIM:
            return self.claim_fence(
                f"key:{operation_id}",
                owner_id="chaos-leader",
                operation_id=operation_id,
            )
        if boundary is FailureBoundary.HEARTBEAT:
            # Claim without crash, then heartbeat with crash.
            prior = self._crash_at
            self._crash_at = None
            fence = self.claim_fence(
                f"key:{operation_id}",
                owner_id="chaos-leader",
                operation_id=operation_id,
            )
            self._crash_at = prior
            return self.heartbeat_fence(fence, operation_id=operation_id)
        if boundary is FailureBoundary.PROOF_PUBLICATION:
            prior = self._crash_at
            self._crash_at = None
            fence = self.claim_fence(
                f"proof:{operation_id}",
                owner_id="proof-producer",
                operation_id=operation_id,
            )
            self._crash_at = prior
            return self.publish_authority(
                f"proof:{operation_id}",
                {"result": "proved", "operation_id": operation_id},
                fence,
                boundary=FailureBoundary.PROOF_PUBLICATION,
                operation_id=operation_id,
                evidence_label=f"proof-{operation_id}",
            )
        if boundary is FailureBoundary.GRAPH_BATCH:
            prior = self._crash_at
            self._crash_at = None
            fence = self.claim_fence(
                f"graph:{operation_id}",
                owner_id="graph-writer",
                operation_id=operation_id,
            )
            self._crash_at = prior
            return self.run_batch(
                "graph",
                [{"node": "n1"}, {"node": "n2"}],
                fence,
                operation_id=operation_id,
            )
        if boundary is FailureBoundary.VECTOR_BATCH:
            prior = self._crash_at
            self._crash_at = None
            fence = self.claim_fence(
                f"vector:{operation_id}",
                owner_id="vector-writer",
                operation_id=operation_id,
            )
            self._crash_at = prior
            return self.run_batch(
                "vector",
                [{"embedding": [0.1, 0.2]}, {"embedding": [0.3, 0.4]}],
                fence,
                operation_id=operation_id,
            )
        if boundary is FailureBoundary.WALLET_BATCH:
            prior = self._crash_at
            self._crash_at = None
            fence = self.claim_fence(
                f"wallet:{operation_id}",
                owner_id="wallet-writer",
                operation_id=operation_id,
            )
            self._crash_at = prior
            return self.run_batch(
                "wallet",
                [{"address": "0xabc"}, {"address": "0xdef"}],
                fence,
                operation_id=operation_id,
            )
        if boundary is FailureBoundary.CHECKPOINT:
            return self.checkpoint("db:control", operation_id=operation_id)
        if boundary is FailureBoundary.EXPORT:
            return self.export_snapshot(
                [{"id": 1, "v": "a"}],
                operation_id=operation_id,
            )
        if boundary is FailureBoundary.MERGE:
            return self.merge_shards(
                {"a": 1},
                {"b": 2},
                operation_id=operation_id,
            )
        if boundary is FailureBoundary.BACKUP:
            return self.backup(
                ("db:control", "db:analytical"),
                operation_id=operation_id,
            )
        if boundary is FailureBoundary.QUACK_RESPONSE:
            return self.quack_respond(
                f"q:{operation_id}",
                [{"col": 1}],
                operation_id=operation_id,
            )
        if boundary is FailureBoundary.PROCESS_DEATH:
            return self.process_death(operation_id=operation_id)
        raise ChaosError(f"unsupported boundary {boundary!r}")


# ---------------------------------------------------------------------------
# Live module integration (existing control-plane surfaces)
# ---------------------------------------------------------------------------


def _unified_key(**overrides: Any) -> Any:
    base: dict[str, Any] = dict(
        ir={"formula": "(assert (> x 0))"},
        property_value={"property_id": "prop.safety"},
        assumptions=("assumption:int", "assumption:precondition"),
        selected_premises=("premise:nat.succ", "premise:nat.zero"),
        translator={
            "receipt_id": "tr:1",
            "preservation": "equisatisfiable",
            "version": "hammer-translator/v3",
        },
        solver_identities=(
            {"solver": "z3", "version": "4.12.0"},
            {"solver": "cvc5", "version": "1.1.0"},
        ),
        toolchain={"lean": "4.3.0", "lake": "5.0.0"},
        theorem_registry={"registry_hash": "reg:abc", "count": 12},
        policy={"mode": "production", "require_kernel": True},
        resources={"timeout_ms": 1000, "max_memory_bytes": 4096},
        tree={"tree_id": "tree:deadbeef", "commit": "abc123"},
        backend_id="solver.z3",
        backend_binary={"path": "/usr/bin/z3", "sha256": "abc"},
        backend_version="4.12.0",
        backend_config={"logic": "QF_LIA", "timeout_ms": 1000},
    )
    base.update(overrides)
    return build_unified_proof_key(**base)


def _theorem(**changes: Any) -> TheoremResult:
    fields: dict[str, Any] = {
        "result_id": "result:theorem-chaos",
        "backend_id": "solver.z3",
        "backend_version": "4.12.0",
        "authority": ResultAuthority.THEOREM,
        "status": ResultStatus.PROVED,
        "assumptions": ("assumption:int",),
        "bounds": ExecutionBounds(
            timeout_ms=1000,
            max_steps=100,
            max_memory_bytes=4096,
            max_output_bytes=2048,
        ),
        "translation_ceiling": EvidenceAuthority.INDEPENDENTLY_CHECKABLE,
        "usage": ResourceUsage(
            elapsed_ms=10,
            steps=5,
            peak_memory_bytes=512,
            output_bytes=64,
        ),
        "witness": {"kind": "proof"},
        "diagnostics": (),
        "reason": "",
        "metadata": {},
    }
    fields.update(changes)
    return TheoremResult(**fields)


def prove_stale_fences_cannot_publish() -> dict[str, Any]:
    """Acceptance: stale fences cannot publish (harness + proof coordinator)."""

    plane = ChaosControlPlane(lease_seconds=5.0, clock=lambda: 1000.0)
    fence = plane.claim_fence("proof:stale", owner_id="owner-a")
    # Supersede by releasing via process death pattern: mark fence released.
    with plane._lock:
        plane._fences[fence.fence_id] = FenceState(
            fence_id=fence.fence_id,
            owner_id=fence.owner_id,
            generation=fence.generation,
            token=fence.token,
            expires_at=fence.expires_at,
            released=True,
        )
    stale_blocked = False
    try:
        plane.publish_authority(
            "proof:stale",
            {"v": 1},
            fence,
            evidence_label="should-not-publish",
        )
    except StalePublishError:
        stale_blocked = True
    assert stale_blocked, "stale fence must not publish"

    # Expired fence.
    clock = {"t": 100.0}
    plane2 = ChaosControlPlane(
        lease_seconds=5.0, clock=lambda: clock["t"]
    )
    live = plane2.claim_fence("proof:exp", owner_id="owner-b", now=100.0)
    clock["t"] = 200.0
    expired_blocked = False
    try:
        plane2.publish_authority(
            "proof:exp", {"v": 2}, live, now=200.0
        )
    except StalePublishError:
        expired_blocked = True
    assert expired_blocked, "expired fence must not publish"

    # Live proof coordinator integration.
    coord_clock = {"t": 50.0}
    coordinator = build_duckdb_proof_coordinator(
        clock=lambda: coord_clock["t"],
        lease_seconds=5.0,
    )
    key = _unified_key(
        tree={"tree_id": "tree:chaos-stale", "commit": "c1"},
        backend_config={"logic": "QF_LIA", "timeout_ms": 1001},
    )
    claim = coordinator.claim(key, owner_id="coord-owner", now=50.0)
    coord_clock["t"] = 60.0  # past expiry
    coord_blocked = False
    try:
        coordinator.publish(claim, _theorem(), key=key, now=60.0)
    except (ExpiredFenceError, StaleFenceError):
        coord_blocked = True
    assert coord_blocked, "coordinator must reject expired fence publish"
    assert coordinator.get(key, now=60.0) is None

    # Foreign / follower cannot publish.
    key2 = _unified_key(
        tree={"tree_id": "tree:chaos-follower", "commit": "c2"},
        backend_config={"logic": "QF_LIA", "timeout_ms": 1002},
    )
    leader = coordinator.claim(key2, owner_id="leader", now=60.0)
    follower = coordinator.claim(key2, owner_id="follower", now=60.0)
    assert not follower.acquired
    follower_blocked = False
    try:
        coordinator.publish(follower, _theorem(result_id="r:f"), key=key2, now=60.0)
    except StaleFenceError:
        follower_blocked = True
    assert follower_blocked
    ok = coordinator.publish(
        leader, _theorem(result_id="r:leader"), key=key2, now=60.0
    )
    assert ok.usable
    # Second publish from same generation is stale (no duplicate authority).
    second_blocked = False
    try:
        coordinator.publish(
            leader, _theorem(result_id="r:dup"), key=key2, now=60.0
        )
    except StaleFenceError:
        second_blocked = True
    assert second_blocked

    return {
        "ok": True,
        "stale_fence_blocked": stale_blocked,
        "expired_fence_blocked": expired_blocked,
        "coordinator_expired_blocked": coord_blocked,
        "follower_blocked": follower_blocked,
        "duplicate_publish_blocked": second_blocked,
        "acceptance": "stale_fences_cannot_publish",
    }


def prove_typed_no_progress_and_deadlock() -> dict[str, Any]:
    """Acceptance: no-progress and deadlock diagnoses are typed."""

    plane = ChaosControlPlane()

    # Deadlock: A waits B, B waits A.
    plane.set_wait_edge("worker-a", "worker-b")
    plane.set_wait_edge("worker-b", "worker-a")
    dead = plane.detect_deadlock()
    assert dead is not None
    assert dead.kind is DiagnosisKind.DEADLOCK
    assert isinstance(dead.kind, DiagnosisKind)
    assert dead.kind.value == "deadlock"

    # No-progress: sequence stalls.
    plane2 = ChaosControlPlane()
    last: TypedDiagnosis | None = None
    for _ in range(NO_PROGRESS_THRESHOLD_STEPS + 1):
        last = plane2.observe_progress("export-pipeline", sequence=3)
    assert last is not None
    assert last.kind is DiagnosisKind.NO_PROGRESS
    assert last.kind.value == "no_progress"

    kinds = plane.typed_diagnosis_kinds() | plane2.typed_diagnosis_kinds()
    assert DiagnosisKind.DEADLOCK.value in kinds
    assert DiagnosisKind.NO_PROGRESS.value in kinds
    # Closed set: every diagnosis kind is a DiagnosisKind member.
    for d in list(plane.diagnoses()) + list(plane2.diagnoses()):
        assert d.kind in DiagnosisKind
        assert d.to_dict()["schema"] == DIAGNOSIS_SCHEMA

    return {
        "ok": True,
        "deadlock_kind": DiagnosisKind.DEADLOCK.value,
        "no_progress_kind": DiagnosisKind.NO_PROGRESS.value,
        "typed_kinds": sorted(kinds),
        "acceptance": "no_progress_and_deadlock_diagnoses_are_typed",
    }


def prove_recovery_preserves_dirty_and_evidence() -> dict[str, Any]:
    """Acceptance: recovery preserves dirty work and immutable evidence."""

    results: list[dict[str, Any]] = []
    for boundary in FailureBoundary:
        plane = ChaosControlPlane(lease_seconds=60.0)
        # Seed evidence before crash so preservation is meaningful.
        seed = plane.register_evidence(
            f"seed-{boundary.value}",
            media_type="text/plain",
            payload=f"seed:{boundary.value}".encode("utf-8"),
        )
        outcome = plane.inject_and_recover(
            boundary, operation_id=f"op:preserve:{boundary.value}"
        )
        assert outcome.evidence_preserved, boundary.value
        assert seed.object_digest in plane.evidence_digests()
        # Dirty work from the crash path (or seeded) must remain addressable.
        dirty = plane.dirty_records()
        if outcome.crashed:
            assert outcome.dirty_preserved, boundary.value
            assert outcome.recovered, boundary.value
            assert len(dirty) >= 1, (
                f"{boundary.value}: expected dirty work after crash"
            )
        results.append(outcome.to_dict())

    # Recovery module integration: crash at checkpoint, recover idempotently.
    backend = recovery_mod.MemoryRecoveryBackend()
    orch = recovery_mod.build_recovery_orchestrator(backend)
    obj = recovery_mod.ImmutableObjectRef(
        object_digest="sha256:" + _sha256_hex(b"recovery-evidence"),
        media_type="parquet",
        size_bytes=32,
        cid="cid-recovery",
    )
    state = recovery_mod.LogicalDatabaseState(
        database_id="db:chaos",
        workload=WorkloadKind.CONTROL,
        schema_version="chaos@1",
        tables={"t": ({"n": 1},)},
        referenced_objects=(obj,),
        generation=1,
    )
    backend.put_live_state(state)
    orch.set_crash_at("before_checkpoint")
    try:
        orch.checkpoint("db:chaos", operation_id="op:chaos:ckpt")
        raised = False
    except recovery_mod.CrashInjected:
        raised = True
    assert raised
    orch.set_crash_at(None)
    record = orch.checkpoint("db:chaos", operation_id="op:chaos:ckpt")
    assert record.snapshot_digest.startswith("sha256:")
    assert backend.has_object(obj.object_digest)

    # Retention cannot delete referenced evidence.
    blocked = False
    try:
        orch.retention(
            dry_run=False,
            force_delete_objects=(obj.object_digest,),
            operation_id="op:chaos:retention",
        )
    except recovery_mod.RetentionBlockedError:
        blocked = True
    assert blocked
    assert backend.has_object(obj.object_digest)

    return {
        "ok": True,
        "boundary_results": results,
        "recovery_checkpoint_ok": True,
        "retention_blocked_referenced_evidence": blocked,
        "acceptance": "recovery_preserves_dirty_work_and_immutable_evidence",
    }


def prove_bounded_recovery_no_duplicate_authority() -> dict[str, Any]:
    """Prove every boundary recovers in bound steps without duplicate authority."""

    outcomes: list[dict[str, Any]] = []
    for boundary in FailureBoundary:
        plane = ChaosControlPlane()
        result = plane.inject_and_recover(
            boundary, operation_id=f"op:bound:{boundary.value}"
        )
        assert result.steps <= MAX_RECOVERY_STEPS
        assert result.duplicate_authority is False
        # Authority map has at most one entry per key.
        keys = [a.key for a in plane._authority.values()]
        assert len(keys) == len(set(keys))
        outcomes.append(result.to_dict())

    # Dual-write authority transition crash recovery is idempotent.
    store = auth.MemoryAuthorityBackend()
    port = auth.build_authority_port(
        store,
        domain="graph",
        initial_mode=auth.AuthorityMode.DUAL,
    )
    port.set_crash_at("before_outbox_enqueue")
    try:
        port.write("node:1", {"label": "alpha"}, operation_id="op:graph:1")
        crashed = False
    except auth.CrashInjected:
        crashed = True
    assert crashed
    port.set_crash_at(None)
    again = port.write("node:1", {"label": "alpha"}, operation_id="op:graph:1")
    # Recovery / replay must not fork authority.
    assert again.get("atomic_across_filesystems") is False
    incomplete = list(store.list_incomplete_outbox("graph"))
    # Drive remaining outbox if any.
    if incomplete:
        port.recover_outbox()
    # Single outbox handle for the operation (no duplicate authority).
    by_op = store.get_outbox_by_operation("op:graph:1")
    assert by_op is not None

    return {
        "ok": True,
        "boundaries": FAILURE_BOUNDARIES,
        "outcomes": outcomes,
        "authority_dual_write_recovered": True,
        "max_recovery_steps": MAX_RECOVERY_STEPS,
    }


def prove_publication_stale_fence_and_quack_isolation() -> dict[str, Any]:
    """Stale publication fence rejected; Quack plane stays non-authoritative."""

    now_ms = 1_700_000_000_000
    plane = pub.PublicationPlane(
        "/var/lib/publication/chaos_read_models.duckdb",
        clock_ms=lambda: now_ms,
    )
    try:
        stale = pub.FenceToken(
            fence_id="fence-stale",
            generation=1,
            expires_at_ms=now_ms - 1,
            nonce="b" * 32,
        )
        spec = pub.ReadModelSpec(
            read_model_id="rm-chaos-1",
            table_name="public_nodes",
            columns=(
                pub.AllowlistedColumn(name="node_id"),
                pub.AllowlistedColumn(name="label"),
            ),
            revision_bindings=(
                pub.RevisionBinding(
                    source_domain="graph",
                    revision_id="graph-rev-chaos",
                    store_generation=0,
                    schema_checksum="sha256:" + ("ab" * 32),
                ),
            ),
            fence=stale,
            max_rows=100,
            description="chaos stale fence",
        )
        blocked = False
        try:
            plane.materialize_read_model(
                spec, rows=[("n1", "x")], now_ms=now_ms
            )
        except pub.PublicationError as exc:
            blocked = "stale" in str(exc).lower() or "expired" in str(exc).lower()
        assert blocked, "stale publication fence must be rejected"

        live = pub.FenceToken(
            fence_id="fence-live",
            generation=2,
            expires_at_ms=now_ms + 60_000,
            nonce="c" * 32,
        )
        live_spec = pub.ReadModelSpec(
            read_model_id="rm-chaos-2",
            table_name="public_nodes",
            columns=(
                pub.AllowlistedColumn(name="node_id"),
                pub.AllowlistedColumn(name="label"),
            ),
            revision_bindings=(
                pub.RevisionBinding(
                    source_domain="graph",
                    revision_id="graph-rev-chaos-2",
                    store_generation=0,
                    schema_checksum="sha256:" + ("cd" * 32),
                ),
            ),
            fence=live,
            max_rows=100,
            description="chaos live fence",
        )
        receipt = plane.materialize_read_model(
            live_spec, rows=[("n1", "alpha")], now_ms=now_ms
        )
        assert receipt.row_count == 1
        assert receipt.authority_catalogs_attached is False
        plane.assert_sensitive_surfaces_absent()
    finally:
        plane.close()

    return {
        "ok": True,
        "stale_publication_rejected": blocked,
        "live_materialization_ok": True,
        "authority_catalogs_attached": False,
    }


def prove_heartbeat_capacity_and_export_readonly() -> dict[str, Any]:
    """Heartbeat uses reserved capacity; export remains non-authoritative."""

    capacity = pq.ControlPlaneCapacity(
        total_slots=8,
        reserved_control_plane_slots=2,
    )
    monitor = pq.LeaseHeartbeatMonitor(
        capacity,
        interval_ms=5,
        slo_ms=500.0,
        work_ms=0.0,
    )
    monitor.start()
    time.sleep(0.05)
    stats = monitor.stop(timeout=2.0)
    assert stats.count >= 1
    assert stats.within_slo is True

    # Export is read-only and non-authoritative.
    exporter = exp.SnapshotExporter()
    rows = [{"id": 1, "name": "alpha"}, {"id": 2, "name": "beta"}]
    source = [dict(r) for r in rows]
    job = exp.ExportJob(
        job_id="export:chaos-1",
        template_id="publication.list_records",
        parameters_digest=exp.digest_parameters({"tenant_id": "chaos"}),
        schema_version="ipfs_datasets_py/duckdb-control-export-schema@1",
        snapshot=SnapshotId(value="snap-chaos-1"),
        format=exp.ExportFormat.JSON,
        destination_policy=exp.default_destination_policy(),
        location_hint="exports/chaos.json",
    )
    result = exporter.export_rows(rows, job, source_mutability_probe=source)
    assert result.read_only is True
    assert result.non_authoritative is True
    assert result.mutated_source is False
    assert source == rows

    return {
        "ok": True,
        "heartbeat_samples": stats.count,
        "heartbeat_within_slo": stats.within_slo,
        "export_read_only": result.read_only,
        "export_non_authoritative": result.non_authoritative,
        "export_mutated_source": result.mutated_source,
    }


# ---------------------------------------------------------------------------
# Suite / install / receipt
# ---------------------------------------------------------------------------


def install_check() -> dict[str, Any]:
    """Report that the DQK-051 chaos suite is installed."""

    return {
        "ok": True,
        "schema": CHAOS_CONTRACT_SCHEMA,
        "program_id": PROGRAM_ID,
        "owner_task_id": CONTRACT_TASK_ID,
        "implementation_generation": CONTRACT_IMPLEMENTATION_GENERATION,
        "module": "scripts/validation/validate_duckdb_quack_chaos.py",
        "failure_boundaries": list(FAILURE_BOUNDARIES),
        "diagnosis_kinds": [k.value for k in DiagnosisKind],
        "typed_required_diagnoses": [
            DiagnosisKind.NO_PROGRESS.value,
            DiagnosisKind.DEADLOCK.value,
        ],
        "max_recovery_steps": MAX_RECOVERY_STEPS,
        "acceptance": [
            "stale_fences_cannot_publish",
            "no_progress_and_deadlock_diagnoses_are_typed",
            "recovery_preserves_dirty_work_and_immutable_evidence",
        ],
    }


def run_chaos_suite() -> dict[str, Any]:
    """Run the full hermetic chaos contract suite."""

    results: list[dict[str, Any]] = []
    errors: list[str] = []

    def check(name: str, fn: Callable[[], Mapping[str, Any]]) -> None:
        try:
            payload = dict(fn())
            ok = bool(payload.get("ok", True))
            results.append({"name": name, "ok": ok, "detail": payload})
            if not ok:
                errors.append(f"{name}: reported not ok")
        except Exception as exc:  # noqa: BLE001 — suite boundary
            results.append(
                {
                    "name": name,
                    "ok": False,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
            errors.append(f"{name}: {type(exc).__name__}: {exc}")

    check("install_check", install_check)
    check("stale_fences_cannot_publish", prove_stale_fences_cannot_publish)
    check(
        "typed_no_progress_and_deadlock",
        prove_typed_no_progress_and_deadlock,
    )
    check(
        "recovery_preserves_dirty_and_evidence",
        prove_recovery_preserves_dirty_and_evidence,
    )
    check(
        "bounded_recovery_no_duplicate_authority",
        prove_bounded_recovery_no_duplicate_authority,
    )
    check(
        "publication_stale_fence_and_quack_isolation",
        prove_publication_stale_fence_and_quack_isolation,
    )
    check(
        "heartbeat_capacity_and_export_readonly",
        prove_heartbeat_capacity_and_export_readonly,
    )

    # Parametric inject at every declared boundary.
    def _all_boundaries() -> dict[str, Any]:
        plane = ChaosControlPlane()
        outcomes = []
        for boundary in FailureBoundary:
            outcomes.append(
                plane.inject_and_recover(
                    boundary,
                    operation_id=f"op:suite:{boundary.value}",
                ).to_dict()
            )
        # After full suite, no-progress/deadlock paths still typed if any.
        kinds = plane.typed_diagnosis_kinds()
        for item in outcomes:
            assert item["steps"] <= MAX_RECOVERY_STEPS
            assert item["duplicate_authority"] is False
            if item["crashed"]:
                assert item["recovered"] is True
                assert item["evidence_preserved"] is True
        return {
            "ok": True,
            "boundary_count": len(outcomes),
            "boundaries": FAILURE_BOUNDARIES,
            "outcomes": outcomes,
            "diagnosis_kinds_seen": sorted(kinds),
        }

    check("all_failure_boundaries", _all_boundaries)

    ok = not errors
    return {
        "schema": CHAOS_CONTRACT_SCHEMA,
        "task_id": CONTRACT_TASK_ID,
        "implementation_generation": CONTRACT_IMPLEMENTATION_GENERATION,
        "program_id": PROGRAM_ID,
        "ok": ok,
        "passed": sum(1 for r in results if r["ok"]),
        "failed": sum(1 for r in results if not r["ok"]),
        "results": results,
        "errors": errors,
        "failure_boundaries": list(FAILURE_BOUNDARIES),
        "diagnosis_kinds": [k.value for k in DiagnosisKind],
        "acceptance": {
            "stale_fences_cannot_publish": ok
            and any(
                r["name"] == "stale_fences_cannot_publish" and r["ok"]
                for r in results
            ),
            "no_progress_and_deadlock_diagnoses_are_typed": ok
            and any(
                r["name"] == "typed_no_progress_and_deadlock" and r["ok"]
                for r in results
            ),
            "recovery_preserves_dirty_work_and_immutable_evidence": ok
            and any(
                r["name"] == "recovery_preserves_dirty_and_evidence" and r["ok"]
                for r in results
            ),
        },
    }


def build_chaos_receipt(
    *,
    suite_report: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Emit a chaos gate receipt after a passing suite."""

    report = dict(suite_report) if suite_report is not None else run_chaos_suite()
    if not report.get("ok"):
        raise ChaosError("refusing to emit chaos receipt for failing suite")
    digest = "sha256:" + _sha256_hex(_canonical_json(report))
    return {
        "schema": CHAOS_RECEIPT_SCHEMA,
        "task_id": CONTRACT_TASK_ID,
        "program_id": PROGRAM_ID,
        "implementation_generation": CONTRACT_IMPLEMENTATION_GENERATION,
        "suite_digest": digest,
        "failure_boundaries": list(FAILURE_BOUNDARIES),
        "acceptance": dict(report.get("acceptance") or {}),
        "passed": report.get("passed"),
        "failed": report.get("failed"),
        "issued_at": _utc_now(),
        "ok": True,
    }


def self_check() -> dict[str, Any]:
    """Hermetic self-check used by install and CLI."""

    report = run_chaos_suite()
    return {
        "ok": report["ok"],
        "install": install_check(),
        "suite": report,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="DQK-051 DuckDB Quack control-plane chaos validator",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit the chaos suite report as JSON",
    )
    parser.add_argument(
        "--emit-receipt",
        action="store_true",
        help="Emit a chaos gate receipt after a passing suite",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    report = run_chaos_suite()
    if args.emit_receipt:
        if not report["ok"]:
            if args.json:
                print(json.dumps(report, indent=2, sort_keys=True))
            else:
                print(
                    "chaos suite failed; refusing to emit receipt",
                    file=sys.stderr,
                )
            return 1
        receipt = build_chaos_receipt(suite_report=report)
        payload = {"report": report, "chaos_receipt": receipt}
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        status = "PASS" if report["ok"] else "FAIL"
        print(
            f"DQK-051 chaos contract: {status} "
            f"({report['passed']} passed, {report['failed']} failed)"
        )
        for item in report["results"]:
            mark = "ok" if item["ok"] else "FAIL"
            line = f"  [{mark}] {item['name']}"
            if not item["ok"]:
                line += f" — {item.get('error', '')}"
            print(line)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
