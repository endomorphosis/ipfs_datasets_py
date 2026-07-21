"""Asynchronous, version-safe evaluation of immutable training snapshots.

The autoencoder trainer is the sole owner of its mutable (and possibly CUDA)
state.  This module deliberately accepts only a serialized copy of that state,
then evaluates it on a worker thread.  Results do not mutate trainer state and
cannot be promoted until the trainer presents the matching snapshot boundary.

The queue is bounded.  When it fills, an older *unevaluated* snapshot is
coalesced into the newest snapshot from the same evaluation lineage and an
explicit :class:`SnapshotDrop` is retained for telemetry.  In-flight work is
never cancelled or silently discarded.  A separate backpressure gate bounds
the age and version lag of the oldest outstanding evidence; callers invoke it
before beginning the next training step.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import threading
import time
from collections import Counter, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any, Callable, Deque, Dict, Iterable, Mapping, Optional, Sequence


SNAPSHOT_EVALUATION_SCHEMA_VERSION = "legal-ir-snapshot-evaluation-v1"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _frozen_mapping(value: Optional[Mapping[str, Any]]) -> Mapping[str, Any]:
    """Return an isolated, read-only mapping.

    ``MappingProxyType`` prevents accidental top-level mutation while the deep
    copy prevents the publisher from changing nested objects after enqueue.
    Consumers that need a mutable value should call ``copy.deepcopy(dict(x))``.
    """

    return MappingProxyType(copy.deepcopy(dict(value or {})))


@dataclass(frozen=True, slots=True)
class SnapshotVersions:
    """All version dimensions that make evaluation evidence comparable."""

    state_version: str
    compiler_version: str
    holdout_version: str
    schema_version: str = SNAPSHOT_EVALUATION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for name in (
            "state_version",
            "compiler_version",
            "holdout_version",
            "schema_version",
        ):
            if not str(getattr(self, name) or "").strip():
                raise ValueError(f"{name} must be non-empty")

    @property
    def state_hash(self) -> str:
        """Compatibility alias used by autoencoder state telemetry."""

        return self.state_version

    @property
    def compiler_commit(self) -> str:
        return self.compiler_version

    @property
    def holdout_hash(self) -> str:
        return self.holdout_version

    @property
    def metric_schema_version(self) -> str:
        return self.schema_version

    def to_dict(self) -> Dict[str, str]:
        return {
            "state_version": self.state_version,
            "compiler_version": self.compiler_version,
            "holdout_version": self.holdout_version,
            "schema_version": self.schema_version,
        }

    def mismatch_fields(self, other: "SnapshotVersions") -> tuple[str, ...]:
        return tuple(
            name
            for name in (
                "state_version",
                "compiler_version",
                "holdout_version",
                "schema_version",
            )
            if getattr(self, name) != getattr(other, name)
        )


def canonical_holdout_version(
    sample_ids: Iterable[str],
    *,
    validation_mode: str = "holdout",
) -> str:
    """Hash an ordered holdout identity without retaining sample contents."""

    payload = {
        "sample_ids": [str(sample_id) for sample_id in sample_ids],
        "validation_mode": str(validation_mode),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class EvaluationSnapshot:
    """An immutable state copy published at one trainer boundary."""

    sequence: int
    versions: SnapshotVersions
    state_payload: bytes
    metadata: Mapping[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=_utc_now)
    created_monotonic: float = field(default_factory=time.monotonic)

    def __post_init__(self) -> None:
        if int(self.sequence) < 0:
            raise ValueError("sequence must be non-negative")
        payload = bytes(self.state_payload)
        object.__setattr__(self, "state_payload", payload)
        object.__setattr__(self, "metadata", _frozen_mapping(self.metadata))
        digest = hashlib.sha256(payload).hexdigest()
        if digest != self.versions.state_version:
            raise ValueError(
                "state_payload hash does not match versions.state_version "
                f"({digest} != {self.versions.state_version})"
            )

    @classmethod
    def from_state_json(
        cls,
        state: Mapping[str, Any] | str | bytes,
        *,
        sequence: int,
        compiler_version: str,
        holdout_version: str,
        schema_version: str = SNAPSHOT_EVALUATION_SCHEMA_VERSION,
        metadata: Optional[Mapping[str, Any]] = None,
    ) -> "EvaluationSnapshot":
        if isinstance(state, bytes):
            payload = bytes(state)
        elif isinstance(state, str):
            payload = state.encode("utf-8")
        else:
            payload = json.dumps(
                copy.deepcopy(dict(state)),
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        versions = SnapshotVersions(
            state_version=hashlib.sha256(payload).hexdigest(),
            compiler_version=str(compiler_version),
            holdout_version=str(holdout_version),
            schema_version=str(schema_version),
        )
        return cls(
            sequence=int(sequence),
            versions=versions,
            state_payload=payload,
            metadata=metadata or {},
        )

    @property
    def snapshot_id(self) -> str:
        return f"{self.sequence}:{self.versions.state_version}"

    def state_json(self) -> Any:
        """Decode a fresh JSON value for an evaluator-owned state instance."""

        return json.loads(self.state_payload.decode("utf-8"))

    def to_dict(self, *, include_state: bool = False) -> Dict[str, Any]:
        value: Dict[str, Any] = {
            "created_at": self.created_at,
            "metadata": copy.deepcopy(dict(self.metadata)),
            "sequence": self.sequence,
            "snapshot_id": self.snapshot_id,
            "state_size_bytes": len(self.state_payload),
            "versions": self.versions.to_dict(),
        }
        if include_state:
            value["state"] = self.state_json()
        return value


# A concise domain alias for callers that prefer ``StateSnapshot``.
StateSnapshot = EvaluationSnapshot


@dataclass(frozen=True, slots=True)
class SnapshotEvaluationResult:
    """Evaluation evidence tagged with every input version."""

    sequence: int
    versions: SnapshotVersions
    metrics: Mapping[str, Any] = field(default_factory=dict)
    error: str = ""
    started_at: str = ""
    finished_at: str = field(default_factory=_utc_now)
    elapsed_seconds: float = 0.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "metrics", _frozen_mapping(self.metrics))
        if int(self.sequence) < 0:
            raise ValueError("sequence must be non-negative")
        if not math.isfinite(float(self.elapsed_seconds)) or self.elapsed_seconds < 0:
            raise ValueError("elapsed_seconds must be finite and non-negative")

    @property
    def succeeded(self) -> bool:
        return not self.error

    @property
    def snapshot_id(self) -> str:
        return f"{self.sequence}:{self.versions.state_version}"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "elapsed_seconds": round(float(self.elapsed_seconds), 9),
            "error": self.error,
            "finished_at": self.finished_at,
            "metrics": copy.deepcopy(dict(self.metrics)),
            "sequence": self.sequence,
            "snapshot_id": self.snapshot_id,
            "started_at": self.started_at,
            "status": "succeeded" if self.succeeded else "failed",
            "versions": self.versions.to_dict(),
        }


EvaluationResult = SnapshotEvaluationResult


@dataclass(frozen=True, slots=True)
class SnapshotShardEvidence:
    """One version-tagged shard of production snapshot evidence.

    Production evaluation is assembled from independent train, validation,
    compiler, proof, and promotion shards.  Each shard carries the full version
    tuple so aggregation cannot accidentally mix state, compiler, schema, or
    holdout evidence across snapshot boundaries.
    """

    sequence: int
    versions: SnapshotVersions
    role: str
    family: str = "all"
    metrics: Mapping[str, Any] = field(default_factory=dict)
    shard_id: str = ""
    created_at: str = field(default_factory=_utc_now)

    def __post_init__(self) -> None:
        if int(self.sequence) < 0:
            raise ValueError("sequence must be non-negative")
        role = str(self.role or "").strip()
        family = str(self.family or "all").strip() or "all"
        if not role:
            raise ValueError("role must be non-empty")
        object.__setattr__(self, "role", role)
        object.__setattr__(self, "family", family)
        object.__setattr__(self, "metrics", _frozen_mapping(self.metrics))
        if not self.shard_id:
            safe_role = role.replace(":", "_")
            safe_family = family.replace(":", "_")
            object.__setattr__(
                self,
                "shard_id",
                f"{self.sequence}:{self.versions.state_version}:{safe_role}:{safe_family}",
            )

    @property
    def snapshot_id(self) -> str:
        return f"{self.sequence}:{self.versions.state_version}"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "created_at": self.created_at,
            "family": self.family,
            "metrics": copy.deepcopy(dict(self.metrics)),
            "role": self.role,
            "sequence": self.sequence,
            "shard_id": self.shard_id,
            "snapshot_id": self.snapshot_id,
            "versions": self.versions.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class SnapshotShardAggregate:
    """Version-safe aggregate assembled from matching shard evidence only."""

    sequence: int
    versions: SnapshotVersions
    shards: tuple[SnapshotShardEvidence, ...]
    required_roles: tuple[str, ...] = ()
    required_families: tuple[str, ...] = ()
    rejected_shards: tuple[ResultRejection, ...] = ()

    @property
    def snapshot_id(self) -> str:
        return f"{self.sequence}:{self.versions.state_version}"

    @property
    def roles_present(self) -> tuple[str, ...]:
        return tuple(sorted({shard.role for shard in self.shards}))

    @property
    def families_present(self) -> tuple[str, ...]:
        return tuple(sorted({shard.family for shard in self.shards}))

    @property
    def missing_roles(self) -> tuple[str, ...]:
        present = set(self.roles_present)
        return tuple(role for role in self.required_roles if role not in present)

    @property
    def missing_families(self) -> tuple[str, ...]:
        if not self.required_families:
            return ()
        present = {
            shard.family
            for shard in self.shards
            if shard.family != "all" and shard.role in set(self.required_roles or self.roles_present)
        }
        return tuple(family for family in self.required_families if family not in present)

    @property
    def complete(self) -> bool:
        return not self.missing_roles and not self.missing_families

    def metrics_by_role(self) -> Dict[str, Dict[str, Any]]:
        grouped: Dict[str, Dict[str, Any]] = {}
        for shard in self.shards:
            grouped.setdefault(shard.role, {})[shard.family] = copy.deepcopy(
                dict(shard.metrics)
            )
        return grouped

    def to_dict(self) -> Dict[str, Any]:
        return {
            "complete": self.complete,
            "families_present": list(self.families_present),
            "metrics_by_role": self.metrics_by_role(),
            "missing_families": list(self.missing_families),
            "missing_roles": list(self.missing_roles),
            "rejected_shard_count": len(self.rejected_shards),
            "rejected_shards": [item.to_dict() for item in self.rejected_shards],
            "required_families": list(self.required_families),
            "required_roles": list(self.required_roles),
            "roles_present": list(self.roles_present),
            "sequence": self.sequence,
            "shard_count": len(self.shards),
            "shards": [shard.to_dict() for shard in self.shards],
            "snapshot_id": self.snapshot_id,
            "versions": self.versions.to_dict(),
        }


def aggregate_matching_snapshot_shards(
    shards: Iterable[SnapshotShardEvidence],
    expected_versions: SnapshotVersions,
    *,
    expected_sequence: int,
    required_roles: Sequence[str] = (),
    required_families: Sequence[str] = (),
) -> SnapshotShardAggregate:
    """Aggregate only shards matching the exact snapshot boundary.

    Mismatched shards are returned as explicit rejections.  They never
    contribute to role/family completeness or promotion metrics.
    """

    accepted: list[SnapshotShardEvidence] = []
    rejected: list[ResultRejection] = []
    for shard in shards:
        mismatch_fields = shard.versions.mismatch_fields(expected_versions)
        if shard.sequence != int(expected_sequence):
            mismatch_fields = (*mismatch_fields, "sequence")
        if mismatch_fields:
            rejected.append(
                ResultRejection(
                    snapshot_id=shard.snapshot_id,
                    reason="version_mismatch",
                    mismatch_fields=tuple(mismatch_fields),
                )
            )
            continue
        accepted.append(shard)
    return SnapshotShardAggregate(
        sequence=int(expected_sequence),
        versions=expected_versions,
        shards=tuple(accepted),
        required_roles=tuple(str(role) for role in required_roles if str(role)),
        required_families=tuple(
            str(family) for family in required_families if str(family)
        ),
        rejected_shards=tuple(rejected),
    )


@dataclass(frozen=True, slots=True)
class SnapshotDrop:
    dropped_snapshot_id: str
    dropped_sequence: int
    replacement_snapshot_id: str
    replacement_sequence: int
    reason: str = "superseded_unevaluated_snapshot"
    dropped_at: str = field(default_factory=_utc_now)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "dropped_at": self.dropped_at,
            "dropped_sequence": self.dropped_sequence,
            "dropped_snapshot_id": self.dropped_snapshot_id,
            "reason": self.reason,
            "replacement_sequence": self.replacement_sequence,
            "replacement_snapshot_id": self.replacement_snapshot_id,
        }


@dataclass(frozen=True, slots=True)
class ResultRejection:
    snapshot_id: str
    reason: str
    mismatch_fields: tuple[str, ...] = ()
    rejected_at: str = field(default_factory=_utc_now)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "mismatch_fields": list(self.mismatch_fields),
            "reason": self.reason,
            "rejected_at": self.rejected_at,
            "snapshot_id": self.snapshot_id,
        }


@dataclass(frozen=True, slots=True)
class SnapshotBoundary:
    """Token proving promotion is being considered at a trainer boundary."""

    sequence: int
    versions: SnapshotVersions

    @classmethod
    def for_snapshot(cls, snapshot: EvaluationSnapshot) -> "SnapshotBoundary":
        return cls(sequence=snapshot.sequence, versions=snapshot.versions)


@dataclass(frozen=True, slots=True)
class PromotionDecision:
    promoted: bool
    reason: str
    snapshot_id: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "promoted": self.promoted,
            "reason": self.reason,
            "snapshot_id": self.snapshot_id,
        }


class SnapshotEvaluatorClosed(RuntimeError):
    pass


class SnapshotBackpressureTimeout(TimeoutError):
    pass


class SnapshotEvaluator:
    """One-worker bounded snapshot evaluation coordinator.

    Parameters
    ----------
    evaluate:
        Called on the evaluator thread with an immutable snapshot.  It may
        return a metrics mapping or a fully tagged result (useful for remote
        evaluators).  Remote result tags are preserved so stale/mismatched
        evidence is rejected by :meth:`accept_result`.
    queue_capacity:
        Maximum number of snapshots waiting behind the one in-flight snapshot.
    max_evidence_lag:
        Maximum boundary distance between the next trainer step and the oldest
        outstanding snapshot before training is backpressured.
    max_evidence_age_seconds:
        Optional wall-clock freshness bound.  Zero disables the age guard.
    """

    def __init__(
        self,
        evaluate: Callable[[EvaluationSnapshot], Mapping[str, Any] | SnapshotEvaluationResult],
        *,
        queue_capacity: int = 2,
        max_evidence_lag: Optional[int] = None,
        max_evidence_age_seconds: float = 0.0,
        name: str = "snapshot-evaluator",
        autostart: bool = True,
    ) -> None:
        if int(queue_capacity) < 1:
            raise ValueError("queue_capacity must be at least one")
        if max_evidence_lag is not None and int(max_evidence_lag) < 1:
            raise ValueError("max_evidence_lag must be at least one")
        if float(max_evidence_age_seconds) < 0:
            raise ValueError("max_evidence_age_seconds must be non-negative")
        self._evaluate = evaluate
        self.queue_capacity = int(queue_capacity)
        self.max_evidence_lag = int(max_evidence_lag or queue_capacity + 1)
        self.max_evidence_age_seconds = float(max_evidence_age_seconds)
        self.name = str(name)
        self._condition = threading.Condition(threading.RLock())
        self._pending: Deque[EvaluationSnapshot] = deque()
        self._inflight: Optional[EvaluationSnapshot] = None
        self._results: Deque[SnapshotEvaluationResult] = deque()
        self._accepted: Dict[str, SnapshotEvaluationResult] = {}
        self._seen_snapshot_ids: set[str] = set()
        self._highest_published_sequence = -1
        self._drops: list[SnapshotDrop] = []
        self._rejections: list[ResultRejection] = []
        self._stats: Counter[str] = Counter()
        self._closed = False
        self._stop_requested = False
        self._worker: Optional[threading.Thread] = None
        if autostart:
            self.start()

    def __enter__(self) -> "SnapshotEvaluator":
        self.start()
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.close(wait=True)

    @property
    def worker(self) -> Optional[threading.Thread]:
        return self._worker

    def start(self) -> None:
        with self._condition:
            if self._closed:
                raise SnapshotEvaluatorClosed("snapshot evaluator is closed")
            if self._worker is not None and self._worker.is_alive():
                return
            self._worker = threading.Thread(
                target=self._worker_main,
                name=self.name,
                daemon=True,
            )
            self._worker.start()

    def close(self, *, wait: bool = True, cancel_pending: bool = False) -> None:
        with self._condition:
            worker = self._worker
            if cancel_pending or worker is None or not worker.is_alive():
                while self._pending:
                    snapshot = self._pending.popleft()
                    self._drops.append(
                        SnapshotDrop(
                            dropped_snapshot_id=snapshot.snapshot_id,
                            dropped_sequence=snapshot.sequence,
                            replacement_snapshot_id="",
                            replacement_sequence=-1,
                            reason="shutdown_cancelled_unevaluated_snapshot",
                        )
                    )
                    self._stats["dropped"] += 1
            self._closed = True
            self._stop_requested = True
            self._condition.notify_all()
        if wait and worker is not None and worker is not threading.current_thread():
            worker.join()

    def publish(self, snapshot: EvaluationSnapshot) -> tuple[SnapshotDrop, ...]:
        """Publish without waiting for evaluation; return explicit coalesced drops."""

        with self._condition:
            if self._closed:
                raise SnapshotEvaluatorClosed("snapshot evaluator is closed")
            if snapshot.snapshot_id in self._seen_snapshot_ids:
                self._stats["duplicate_publishes"] += 1
                return ()
            if snapshot.sequence <= self._highest_published_sequence:
                raise ValueError(
                    "snapshot sequence must increase monotonically "
                    f"({snapshot.sequence} <= {self._highest_published_sequence})"
                )

            dropped: list[SnapshotDrop] = []
            while len(self._pending) >= self.queue_capacity:
                superseded = self._coalescing_candidate(snapshot)
                self._pending.remove(superseded)
                record = SnapshotDrop(
                    dropped_snapshot_id=superseded.snapshot_id,
                    dropped_sequence=superseded.sequence,
                    replacement_snapshot_id=snapshot.snapshot_id,
                    replacement_sequence=snapshot.sequence,
                )
                self._drops.append(record)
                dropped.append(record)
                self._stats["dropped"] += 1
                self._stats["coalesced"] += 1
            self._pending.append(snapshot)
            self._seen_snapshot_ids.add(snapshot.snapshot_id)
            self._highest_published_sequence = snapshot.sequence
            self._stats["published"] += 1
            self._condition.notify_all()
            return tuple(dropped)

    # Compatibility/domain aliases used by trainer call sites.
    publish_snapshot = publish

    def _coalescing_candidate(
        self, replacement: EvaluationSnapshot
    ) -> EvaluationSnapshot:
        replacement_lineage = (
            replacement.versions.compiler_version,
            replacement.versions.holdout_version,
            replacement.versions.schema_version,
        )
        for candidate in self._pending:
            lineage = (
                candidate.versions.compiler_version,
                candidate.versions.holdout_version,
                candidate.versions.schema_version,
            )
            if lineage == replacement_lineage and candidate.sequence < replacement.sequence:
                return candidate
        # Capacity is a hard invariant even across lineage changes.  The oldest
        # unevaluated item is explicitly dropped; in-flight evidence is retained.
        return self._pending[0]

    def _worker_main(self) -> None:
        while True:
            with self._condition:
                while not self._pending and not self._stop_requested:
                    self._condition.wait()
                if not self._pending:
                    return
                snapshot = self._pending.popleft()
                self._inflight = snapshot
                self._stats["started"] += 1
                self._condition.notify_all()
            started_wall = _utc_now()
            started = time.monotonic()
            try:
                raw_result = self._evaluate(snapshot)
                if isinstance(raw_result, SnapshotEvaluationResult):
                    result = raw_result
                else:
                    result = SnapshotEvaluationResult(
                        sequence=snapshot.sequence,
                        versions=snapshot.versions,
                        metrics=dict(raw_result),
                        started_at=started_wall,
                        elapsed_seconds=max(0.0, time.monotonic() - started),
                    )
            except BaseException as exc:  # worker must convert evaluator failures to evidence
                result = SnapshotEvaluationResult(
                    sequence=snapshot.sequence,
                    versions=snapshot.versions,
                    error=f"{type(exc).__name__}: {exc}",
                    started_at=started_wall,
                    elapsed_seconds=max(0.0, time.monotonic() - started),
                )
            with self._condition:
                self._inflight = None
                self._results.append(result)
                self._stats["completed"] += 1
                if not result.succeeded:
                    self._stats["failed"] += 1
                self._condition.notify_all()

    def poll_results(self, *, limit: Optional[int] = None) -> list[SnapshotEvaluationResult]:
        with self._condition:
            count = len(self._results) if limit is None else max(0, int(limit))
            return [self._results.popleft() for _ in range(min(count, len(self._results)))]

    def wait_for_result(
        self,
        *,
        sequence: Optional[int] = None,
        timeout: Optional[float] = None,
        consume: bool = True,
    ) -> Optional[SnapshotEvaluationResult]:
        """Wait for a completed result, optionally selecting one boundary."""

        deadline = None if timeout is None else time.monotonic() + max(0.0, timeout)
        with self._condition:
            while True:
                for result in self._results:
                    if sequence is None or result.sequence == sequence:
                        if consume:
                            self._results.remove(result)
                        return result
                if self._closed and self._inflight is None and not self._pending:
                    return None
                remaining = None if deadline is None else deadline - time.monotonic()
                if remaining is not None and remaining <= 0:
                    return None
                self._condition.wait(remaining)

    def accept_result(
        self,
        result: SnapshotEvaluationResult,
        expected_versions: SnapshotVersions,
        *,
        expected_sequence: Optional[int] = None,
    ) -> bool:
        """Accept evidence only when state/compiler/holdout/schema all match."""

        mismatch_fields = result.versions.mismatch_fields(expected_versions)
        if expected_sequence is not None and result.sequence != int(expected_sequence):
            mismatch_fields = (*mismatch_fields, "sequence")
        if result.error:
            reason = "evaluation_failed"
        elif mismatch_fields:
            reason = "version_mismatch"
        else:
            reason = ""
        with self._condition:
            if reason:
                self._rejections.append(
                    ResultRejection(
                        snapshot_id=result.snapshot_id,
                        reason=reason,
                        mismatch_fields=tuple(mismatch_fields),
                    )
                )
                self._stats["rejected"] += 1
                self._stats[f"rejected_{reason}"] += 1
                return False
            self._accepted[result.snapshot_id] = result
            self._stats["accepted"] += 1
            return True

    def consider_for_promotion(
        self,
        result: SnapshotEvaluationResult,
        expected_versions: SnapshotVersions,
        *,
        at_snapshot_boundary: bool,
        expected_sequence: Optional[int] = None,
        promote: Optional[Callable[[SnapshotEvaluationResult], Any]] = None,
    ) -> PromotionDecision:
        """Convenience API that makes the promotion-boundary guard explicit."""

        if not at_snapshot_boundary:
            return PromotionDecision(False, "not_at_snapshot_boundary", result.snapshot_id)
        sequence = result.sequence if expected_sequence is None else expected_sequence
        boundary = SnapshotBoundary(int(sequence), expected_versions)
        if not self.accept_result(
            result,
            expected_versions,
            expected_sequence=boundary.sequence,
        ):
            return PromotionDecision(False, "result_not_accepted", result.snapshot_id)
        return self.promote_at_boundary(boundary, promote=promote)

    def promote_at_boundary(
        self,
        boundary: SnapshotBoundary,
        *,
        promote: Optional[Callable[[SnapshotEvaluationResult], Any]] = None,
    ) -> PromotionDecision:
        """Apply accepted evidence at exactly its matching snapshot boundary."""

        snapshot_id = f"{boundary.sequence}:{boundary.versions.state_version}"
        with self._condition:
            result = self._accepted.get(snapshot_id)
            if result is None:
                self._stats["promotion_deferred"] += 1
                return PromotionDecision(False, "matching_result_not_ready", snapshot_id)
            mismatches = result.versions.mismatch_fields(boundary.versions)
            if mismatches or result.sequence != boundary.sequence:
                self._stats["promotion_blocked"] += 1
                return PromotionDecision(False, "boundary_version_mismatch", snapshot_id)
        # Invoke user code outside the coordinator lock.
        if promote is not None:
            promote(result)
        with self._condition:
            self._accepted.pop(snapshot_id, None)
            self._stats["promoted"] += 1
            self._stats["latest_promoted_sequence"] = boundary.sequence
            self._condition.notify_all()
        return PromotionDecision(True, "promoted_at_snapshot_boundary", snapshot_id)

    def _outstanding(self) -> list[EvaluationSnapshot]:
        values = list(self._pending)
        if self._inflight is not None:
            values.append(self._inflight)
        return values

    def backpressure_reason(self, *, next_sequence: int) -> str:
        with self._condition:
            outstanding = self._outstanding()
            if not outstanding:
                return ""
            oldest = min(outstanding, key=lambda item: item.sequence)
            lag = int(next_sequence) - oldest.sequence
            if lag > self.max_evidence_lag:
                return "evidence_version_lag"
            if self.max_evidence_age_seconds > 0:
                age = max(0.0, time.monotonic() - oldest.created_monotonic)
                if age >= self.max_evidence_age_seconds:
                    return "evidence_age"
            return ""

    @property
    def backpressured(self) -> bool:
        with self._condition:
            outstanding = self._outstanding()
            if not outstanding:
                return False
            next_sequence = max(item.sequence for item in outstanding) + 1
        return bool(self.backpressure_reason(next_sequence=next_sequence))

    def wait_for_training_capacity(
        self,
        *,
        next_sequence: int,
        timeout: Optional[float] = None,
    ) -> float:
        """Pause before a trainer step when outstanding evidence would go stale.

        Returns the number of seconds spent waiting and raises
        :class:`SnapshotBackpressureTimeout` if a finite timeout expires.
        """

        deadline = None if timeout is None else time.monotonic() + max(0.0, timeout)
        started = time.monotonic()
        counted = False
        with self._condition:
            while True:
                reason = self.backpressure_reason(next_sequence=next_sequence)
                if not reason:
                    waited = max(0.0, time.monotonic() - started)
                    if counted:
                        self._stats["backpressure_waits"] += 1
                        self._stats["backpressure_wait_milliseconds"] += int(waited * 1000)
                    return waited
                counted = True
                self._stats[f"backpressure_{reason}"] += 1
                remaining = None if deadline is None else deadline - time.monotonic()
                if remaining is not None and remaining <= 0:
                    self._stats["backpressure_timeouts"] += 1
                    raise SnapshotBackpressureTimeout(
                        f"training remained backpressured by {reason} before "
                        f"snapshot {next_sequence}"
                    )
                self._condition.wait(remaining)

    # A readable trainer-side alias.
    before_training_step = wait_for_training_capacity

    @property
    def dropped_snapshots(self) -> tuple[SnapshotDrop, ...]:
        with self._condition:
            return tuple(self._drops)

    @property
    def rejected_results(self) -> tuple[ResultRejection, ...]:
        with self._condition:
            return tuple(self._rejections)

    @property
    def pending_count(self) -> int:
        with self._condition:
            return len(self._pending)

    @property
    def outstanding_count(self) -> int:
        with self._condition:
            return len(self._pending) + int(self._inflight is not None)

    def wait_until_idle(self, timeout: Optional[float] = None) -> bool:
        deadline = None if timeout is None else time.monotonic() + max(0.0, timeout)
        with self._condition:
            while self._pending or self._inflight is not None:
                remaining = None if deadline is None else deadline - time.monotonic()
                if remaining is not None and remaining <= 0:
                    return False
                self._condition.wait(remaining)
            return True

    def summary(self) -> Dict[str, Any]:
        with self._condition:
            stats = dict(self._stats)
            outstanding = self._outstanding()
            oldest_age = (
                max(0.0, time.monotonic() - min(x.created_monotonic for x in outstanding))
                if outstanding
                else 0.0
            )
            worker_alive = bool(self._worker and self._worker.is_alive())
            queue_depth = len(self._pending)
            outstanding_count = len(outstanding)
            ready_result_count = len(self._results)
            accepted_result_count = len(self._accepted)
            health = {
                "alive": worker_alive,
                "backpressured": bool(
                    outstanding
                    and self.backpressure_reason(
                        next_sequence=max(item.sequence for item in outstanding) + 1
                    )
                ),
                "closed": self._closed,
                "failed_evaluations": int(stats.get("failed", 0)),
                "healthy": (worker_alive or self._closed) and not self._stop_requested,
                "inflight": self._inflight is not None,
                "oldest_outstanding_age_seconds": round(oldest_age, 6),
                "outstanding_count": outstanding_count,
                "queue_depth": queue_depth,
                "ready_result_count": ready_result_count,
            }
            promotion_state = {
                "accepted_result_count": accepted_result_count,
                "complete": int(stats.get("promoted", 0)) > 0,
                "latest_promoted_sequence": int(
                    stats.get("latest_promoted_sequence", -1)
                ),
                "promoted_result_count": int(stats.get("promoted", 0)),
                "ready_result_count": ready_result_count,
            }
            return {
                "accepted_results": int(stats.get("accepted", 0)),
                "backpressure_timeouts": int(stats.get("backpressure_timeouts", 0)),
                "backpressure_wait_seconds": round(
                    int(stats.get("backpressure_wait_milliseconds", 0)) / 1000.0,
                    6,
                ),
                "backpressure_waits": int(stats.get("backpressure_waits", 0)),
                "closed": self._closed,
                "completed_evaluations": int(stats.get("completed", 0)),
                "dropped_work_count": len(self._drops),
                "dropped_snapshot_count": len(self._drops),
                "dropped_snapshots": [item.to_dict() for item in self._drops],
                "evaluator_health": health,
                "failed_evaluations": int(stats.get("failed", 0)),
                "inflight_snapshot_id": (
                    self._inflight.snapshot_id if self._inflight is not None else ""
                ),
                "max_evidence_age_seconds": self.max_evidence_age_seconds,
                "max_evidence_lag": self.max_evidence_lag,
                "oldest_outstanding_age_seconds": round(oldest_age, 6),
                "outstanding_count": outstanding_count,
                "pending_count": queue_depth,
                "promoted_results": int(stats.get("promoted", 0)),
                "published_snapshots": int(stats.get("published", 0)),
                "queue_depth": queue_depth,
                "queue_capacity": self.queue_capacity,
                "ready_result_count": ready_result_count,
                "rejected_result_count": len(self._rejections),
                "rejected_results": [item.to_dict() for item in self._rejections],
                "schema_version": SNAPSHOT_EVALUATION_SCHEMA_VERSION,
                "snapshot_complete_promotion_state": promotion_state,
                "staleness_seconds": round(oldest_age, 6),
                "worker_alive": worker_alive,
            }


# Names used in design notes and downstream integrations.
AsynchronousSnapshotEvaluator = SnapshotEvaluator
SnapshotEvaluationCoordinator = SnapshotEvaluator


__all__ = [
    "AsynchronousSnapshotEvaluator",
    "EvaluationResult",
    "EvaluationSnapshot",
    "PromotionDecision",
    "ResultRejection",
    "SNAPSHOT_EVALUATION_SCHEMA_VERSION",
    "SnapshotBackpressureTimeout",
    "SnapshotBoundary",
    "SnapshotDrop",
    "SnapshotEvaluationCoordinator",
    "SnapshotEvaluationResult",
    "SnapshotEvaluator",
    "SnapshotEvaluatorClosed",
    "SnapshotShardAggregate",
    "SnapshotShardEvidence",
    "SnapshotVersions",
    "StateSnapshot",
    "aggregate_matching_snapshot_shards",
    "canonical_holdout_version",
]
