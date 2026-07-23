"""Concurrent, version-safe LegalIR evaluation by semantic family.

The trainer publishes one immutable :class:`EvaluationSnapshot`.  Evaluation
work for each semantic family may then run independently, but every shard sees
the same immutable compiler/metric artifacts and carries the complete snapshot
identity on its result.  Aggregation fails closed unless all required families
are present and all identity dimensions match.

Retries are deliberately local to a family.  A successful shard is never run
again merely because another family failed, and ``max_retries`` is a hard
per-family bound in addition to the initial attempt.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import math
import threading
import time
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field, fields, is_dataclass
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any, Final, Optional

from .snapshot_evaluator import (
    EvaluationSnapshot,
    SnapshotEvaluationResult,
    SnapshotVersions,
)


LEGAL_IR_FAMILY_EVALUATION_SCHEMA_VERSION: Final = (
    "legal-ir-family-evaluation-v1"
)
LEGAL_IR_EVALUATION_FAMILIES: Final[tuple[str, ...]] = (
    "deontic",
    "frame_logic",
    "tdfol",
    "knowledge_graphs",
    "cec",
    "external_provers",
    "decompiler",
    "temporal",
    "provenance",
)

# A descriptive alias used by callers that do not need to distinguish metric
# view families (where knowledge graphs historically used the short name kg).
LEGAL_IR_SEMANTIC_FAMILIES = LEGAL_IR_EVALUATION_FAMILIES
LEGAL_IR_FAMILY_SHARDS = LEGAL_IR_EVALUATION_FAMILIES
REQUIRED_LEGAL_IR_FAMILIES = LEGAL_IR_EVALUATION_FAMILIES

_FAMILY_ALIASES: Final = {
    "deontic": "deontic",
    "frame": "frame_logic",
    "frame_logic": "frame_logic",
    "flogic": "frame_logic",
    "tdfol": "tdfol",
    "knowledge_graph": "knowledge_graphs",
    "knowledge_graphs": "knowledge_graphs",
    "kg": "knowledge_graphs",
    "cec": "cec",
    "external_prover": "external_provers",
    "external_provers": "external_provers",
    "decompiler": "decompiler",
    "temporal": "temporal",
    "provenance": "provenance",
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical_legal_ir_evaluation_family(family: str) -> str:
    """Normalize a family name and reject families outside this evaluation set."""

    normalized = str(family or "").strip().lower().replace("-", "_")
    canonical = _FAMILY_ALIASES.get(normalized, "")
    if not canonical:
        raise ValueError(f"unsupported LegalIR evaluation family: {family!r}")
    return canonical


def _immutable(value: Any) -> Any:
    """Return an isolated recursively immutable representation of ``value``."""

    if value is None or isinstance(value, (str, bytes, bool, int, float)):
        return value
    if isinstance(value, Mapping):
        return MappingProxyType(
            {str(key): _immutable(item) for key, item in value.items()}
        )
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return tuple(_immutable(item) for item in value)
    # LegalIREvaluationArtifact and similar repository artifacts are frozen
    # dataclasses whose own post-init recursively freezes mapping fields.  A
    # frozen dataclass containing a mutable list/dict is not actually safe and
    # is rejected rather than trusted based on its outer declaration alone.
    parameters = getattr(type(value), "__dataclass_params__", None)
    if (
        is_dataclass(value)
        and parameters is not None
        and parameters.frozen
        and all(_deeply_immutable(getattr(value, item.name)) for item in fields(value))
    ):
        return value
    raise TypeError(
        "shared evaluation artifacts must be JSON-like values or frozen dataclasses; "
        f"got {type(value).__name__}"
    )


def _deeply_immutable(value: Any) -> bool:
    if value is None or isinstance(value, (str, bytes, bool, int, float)):
        return True
    if isinstance(value, tuple):
        return all(_deeply_immutable(item) for item in value)
    if isinstance(value, MappingProxyType):
        return all(
            _deeply_immutable(key) and _deeply_immutable(item)
            for key, item in value.items()
        )
    parameters = getattr(type(value), "__dataclass_params__", None)
    return bool(
        is_dataclass(value)
        and parameters is not None
        and parameters.frozen
        and all(_deeply_immutable(getattr(value, item.name)) for item in fields(value))
    )


def _artifact_tuple(artifacts: Any) -> tuple[Any, ...]:
    if artifacts is None:
        return ()
    if isinstance(artifacts, Mapping) or is_dataclass(artifacts):
        return (artifacts,)
    if isinstance(artifacts, Sequence) and not isinstance(
        artifacts, (str, bytes, bytearray)
    ):
        return tuple(artifacts)
    return (artifacts,)


def _plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_plain(item) for item in value]
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return _plain(value.to_dict())
    return value


@dataclass(frozen=True, slots=True)
class SharedEvaluationArtifacts:
    """Immutable artifacts shared by every shard for exactly one snapshot.

    Cached ``LegalIREvaluationArtifact`` instances are accepted directly.  If
    they expose a cache key, its compiler, state, and metric-schema dimensions
    are checked against the snapshot before any evaluator can consume it.
    """

    versions: SnapshotVersions
    artifacts: tuple[Any, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.versions, SnapshotVersions):
            raise TypeError("versions must be SnapshotVersions")
        frozen_artifacts = tuple(_immutable(item) for item in _artifact_tuple(self.artifacts))
        frozen_metadata = _immutable(self.metadata)
        object.__setattr__(self, "artifacts", frozen_artifacts)
        object.__setattr__(self, "metadata", frozen_metadata)
        for artifact in frozen_artifacts:
            key = getattr(artifact, "key", None)
            if key is None:
                continue
            mismatches: list[str] = []
            if getattr(key, "compiler_commit", None) != self.versions.compiler_version:
                mismatches.append("compiler_version")
            if getattr(key, "state_hash", None) != self.versions.state_version:
                mismatches.append("state_version")
            if getattr(key, "metric_schema", None) != self.versions.schema_version:
                mismatches.append("schema_version")
            if mismatches:
                raise ValueError(
                    "shared artifact does not match snapshot versions: "
                    + ", ".join(mismatches)
                )

    @classmethod
    def for_snapshot(
        cls,
        snapshot: EvaluationSnapshot,
        artifacts: Any = (),
        *,
        metadata: Optional[Mapping[str, Any]] = None,
    ) -> "SharedEvaluationArtifacts":
        if not isinstance(snapshot, EvaluationSnapshot):
            raise TypeError("snapshot must be EvaluationSnapshot")
        return cls(
            versions=snapshot.versions,
            artifacts=_artifact_tuple(artifacts),
            metadata=metadata or {},
        )

    @property
    def artifact_count(self) -> int:
        return len(self.artifacts)

    @property
    def digest(self) -> str:
        encoded = json.dumps(
            _plain(self.artifacts),
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def to_dict(self, *, include_artifacts: bool = False) -> dict[str, Any]:
        value: dict[str, Any] = {
            "artifact_count": self.artifact_count,
            "artifact_digest": self.digest,
            "metadata": _plain(self.metadata),
            "versions": self.versions.to_dict(),
        }
        if include_artifacts:
            value["artifacts"] = _plain(self.artifacts)
        return value


# Alternate word order kept as a convenient domain alias.
SharedLegalIRArtifacts = SharedEvaluationArtifacts


@dataclass(frozen=True, slots=True)
class FamilyShardRequest:
    """Inputs for one isolated family attempt."""

    family: str
    snapshot: EvaluationSnapshot
    shared_artifacts: SharedEvaluationArtifacts
    attempt: int = 1

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "family", canonical_legal_ir_evaluation_family(self.family)
        )
        if not isinstance(self.snapshot, EvaluationSnapshot):
            raise TypeError("snapshot must be EvaluationSnapshot")
        if not isinstance(self.shared_artifacts, SharedEvaluationArtifacts):
            raise TypeError("shared_artifacts must be SharedEvaluationArtifacts")
        if self.snapshot.versions != self.shared_artifacts.versions:
            raise ValueError("shared artifacts do not match the request snapshot")
        if int(self.attempt) < 1:
            raise ValueError("attempt must be at least one")

    @property
    def sequence(self) -> int:
        return self.snapshot.sequence

    @property
    def versions(self) -> SnapshotVersions:
        return self.snapshot.versions

    @property
    def artifacts(self) -> tuple[Any, ...]:
        """Short alias for callback implementations."""

        return self.shared_artifacts.artifacts


@dataclass(frozen=True, slots=True)
class FamilyShardResult:
    """Version-tagged evidence from one semantic-family shard."""

    family: str
    sequence: int
    versions: SnapshotVersions
    metrics: Mapping[str, Any] = field(default_factory=dict)
    error: str = ""
    attempt_count: int = 1
    attempt_errors: tuple[str, ...] = ()
    retryable: bool = True
    started_at: str = ""
    finished_at: str = field(default_factory=_utc_now)
    elapsed_seconds: float = 0.0

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "family", canonical_legal_ir_evaluation_family(self.family)
        )
        if int(self.sequence) < 0:
            raise ValueError("sequence must be non-negative")
        if not isinstance(self.versions, SnapshotVersions):
            raise TypeError("versions must be SnapshotVersions")
        if int(self.attempt_count) < 1:
            raise ValueError("attempt_count must be at least one")
        elapsed = float(self.elapsed_seconds)
        if not math.isfinite(elapsed) or elapsed < 0:
            raise ValueError("elapsed_seconds must be finite and non-negative")
        object.__setattr__(self, "metrics", _immutable(self.metrics))
        object.__setattr__(
            self,
            "attempt_errors",
            tuple(str(item) for item in self.attempt_errors if str(item)),
        )
        object.__setattr__(self, "elapsed_seconds", elapsed)
        if not self.error:
            object.__setattr__(self, "retryable", False)

    @property
    def succeeded(self) -> bool:
        return not self.error

    @property
    def failed(self) -> bool:
        return not self.succeeded

    @property
    def snapshot_id(self) -> str:
        return f"{self.sequence}:{self.versions.state_version}"

    @property
    def status(self) -> str:
        return "succeeded" if self.succeeded else "failed"

    def to_dict(self) -> dict[str, Any]:
        return {
            "attempt_count": self.attempt_count,
            "attempt_errors": list(self.attempt_errors),
            "elapsed_seconds": round(self.elapsed_seconds, 9),
            "error": self.error,
            "family": self.family,
            "finished_at": self.finished_at,
            "metrics": _plain(self.metrics),
            "retryable": bool(self.retryable),
            "sequence": self.sequence,
            "snapshot_id": self.snapshot_id,
            "started_at": self.started_at,
            "status": self.status,
            "versions": self.versions.to_dict(),
        }


LegalIRFamilyShardResult = FamilyShardResult


class FamilyEvaluationError(RuntimeError):
    """Base error for an aggregate that cannot be trusted."""


class IncompleteFamilyEvaluationError(FamilyEvaluationError):
    """Raised when one or more required shard results are absent or duplicated."""


class FamilySnapshotMismatchError(FamilyEvaluationError):
    """Raised when shard evidence came from different snapshots."""


@dataclass(frozen=True, slots=True)
class FamilyEvaluationAggregate:
    """Complete matching shard evidence, including explicit family failures."""

    sequence: int
    versions: SnapshotVersions
    results: Mapping[str, FamilyShardResult]
    schema_version: str = LEGAL_IR_FAMILY_EVALUATION_SCHEMA_VERSION
    finished_at: str = field(default_factory=_utc_now)

    def __post_init__(self) -> None:
        if self.schema_version != LEGAL_IR_FAMILY_EVALUATION_SCHEMA_VERSION:
            raise FamilyEvaluationError("family evaluation schema version is stale")
        raw = dict(self.results)
        actual = set(raw)
        required = set(LEGAL_IR_EVALUATION_FAMILIES)
        if actual != required:
            missing = sorted(required - actual)
            extra = sorted(actual - required)
            raise IncompleteFamilyEvaluationError(
                f"family results are incomplete (missing={missing}, extra={extra})"
            )
        ordered: dict[str, FamilyShardResult] = {}
        for family in LEGAL_IR_EVALUATION_FAMILIES:
            result = raw[family]
            if not isinstance(result, FamilyShardResult):
                raise TypeError(f"result for {family} must be FamilyShardResult")
            if result.family != family:
                raise FamilySnapshotMismatchError(
                    f"result key {family} contains family {result.family}"
                )
            mismatches = result.versions.mismatch_fields(self.versions)
            if result.sequence != self.sequence:
                mismatches = (*mismatches, "sequence")
            if mismatches:
                raise FamilySnapshotMismatchError(
                    f"{family} result does not match aggregate: {', '.join(mismatches)}"
                )
            ordered[family] = result
        object.__setattr__(self, "results", MappingProxyType(ordered))

    @property
    def complete(self) -> bool:
        return True

    @property
    def matching_snapshot(self) -> bool:
        return True

    @property
    def failures(self) -> Mapping[str, str]:
        return MappingProxyType(
            {
                family: result.error
                for family, result in self.results.items()
                if result.failed
            }
        )

    @property
    def failed_families(self) -> tuple[str, ...]:
        return tuple(
            family
            for family in LEGAL_IR_EVALUATION_FAMILIES
            if self.results[family].failed
        )

    @property
    def succeeded(self) -> bool:
        return not self.failed_families

    @property
    def status(self) -> str:
        return "succeeded" if self.succeeded else "failed"

    @property
    def macro_score(self) -> Optional[float]:
        """Return a macro score only when no failed family could be hidden."""

        if not self.succeeded:
            return None
        scores: list[float] = []
        for family in LEGAL_IR_EVALUATION_FAMILIES:
            value = self.results[family].metrics.get("score")
            if value is None:
                return None
            try:
                numeric = float(value)
            except (TypeError, ValueError):
                return None
            if not math.isfinite(numeric):
                return None
            scores.append(numeric)
        return round(sum(scores) / len(scores), 12)

    @property
    def family_metrics(self) -> Mapping[str, Mapping[str, Any]]:
        return MappingProxyType(
            {family: result.metrics for family, result in self.results.items()}
        )

    @property
    def snapshot_id(self) -> str:
        return f"{self.sequence}:{self.versions.state_version}"

    def to_dict(self) -> dict[str, Any]:
        macro = self.macro_score
        return {
            "complete": True,
            "failed_families": list(self.failed_families),
            "failure_count": len(self.failed_families),
            "failures": dict(self.failures),
            "family_count": len(self.results),
            "family_results": {
                family: self.results[family].to_dict()
                for family in LEGAL_IR_EVALUATION_FAMILIES
            },
            "finished_at": self.finished_at,
            "macro_score": macro,
            "macro_score_available": macro is not None,
            "matching_snapshot": True,
            "schema_version": self.schema_version,
            "sequence": self.sequence,
            "snapshot_id": self.snapshot_id,
            "status": self.status,
            "versions": self.versions.to_dict(),
        }


LegalIRFamilyEvaluation = FamilyEvaluationAggregate
FamilyEvaluationResult = FamilyEvaluationAggregate
LegalIRFamilyEvaluationResult = FamilyEvaluationAggregate
LegalIRFamilyShardRequest = FamilyShardRequest


FamilyEvaluatorCallback = Callable[
    ...,
    Mapping[str, Any] | FamilyShardResult | SnapshotEvaluationResult,
]
RetryPredicate = Callable[[FamilyShardResult], bool]


def aggregate_family_results(
    snapshot: EvaluationSnapshot,
    results: Mapping[str, FamilyShardResult] | Sequence[FamilyShardResult],
) -> FamilyEvaluationAggregate:
    """Aggregate only a complete set of results matching ``snapshot``."""

    if not isinstance(snapshot, EvaluationSnapshot):
        raise TypeError("snapshot must be EvaluationSnapshot")
    if isinstance(results, Mapping):
        by_family = dict(results)
    else:
        by_family: dict[str, FamilyShardResult] = {}
        for result in results:
            if result.family in by_family:
                raise IncompleteFamilyEvaluationError(
                    f"duplicate result for family {result.family}"
                )
            by_family[result.family] = result
    return FamilyEvaluationAggregate(
        sequence=snapshot.sequence,
        versions=snapshot.versions,
        results=by_family,
    )


class LegalIRFamilyEvaluator:
    """Run the complete LegalIR family set concurrently over one snapshot.

    A callback normally accepts one :class:`FamilyShardRequest`.  For easy
    integration with older call sites, callbacks accepting ``(snapshot,
    shared_artifacts)`` or ``(family, snapshot, shared_artifacts)`` are also
    supported.
    """

    def __init__(
        self,
        evaluators: Mapping[str, FamilyEvaluatorCallback] | FamilyEvaluatorCallback,
        *,
        max_retries: int = 1,
        max_workers: Optional[int] = None,
        retry_predicate: Optional[RetryPredicate] = None,
        thread_name_prefix: str = "legal-ir-family",
    ) -> None:
        if int(max_retries) < 0:
            raise ValueError("max_retries must be non-negative")
        workers = len(LEGAL_IR_EVALUATION_FAMILIES) if max_workers is None else int(max_workers)
        if workers < 1:
            raise ValueError("max_workers must be at least one")
        if callable(evaluators) and not isinstance(evaluators, Mapping):
            resolved = {family: evaluators for family in LEGAL_IR_EVALUATION_FAMILIES}
        elif isinstance(evaluators, Mapping):
            resolved: dict[str, FamilyEvaluatorCallback] = {}
            for raw_family, evaluator in evaluators.items():
                family = canonical_legal_ir_evaluation_family(raw_family)
                if family in resolved:
                    raise ValueError(f"duplicate evaluator for {family}")
                if not callable(evaluator):
                    raise TypeError(f"evaluator for {family} is not callable")
                resolved[family] = evaluator
            missing = set(LEGAL_IR_EVALUATION_FAMILIES) - set(resolved)
            extra = set(resolved) - set(LEGAL_IR_EVALUATION_FAMILIES)
            if missing or extra:
                raise ValueError(
                    "evaluators must cover every LegalIR family "
                    f"(missing={sorted(missing)}, extra={sorted(extra)})"
                )
        else:
            raise TypeError("evaluators must be a callable or family mapping")
        self._evaluators = MappingProxyType(resolved)
        self.max_retries = int(max_retries)
        self.max_workers = min(workers, len(LEGAL_IR_EVALUATION_FAMILIES))
        self.retry_predicate = retry_predicate
        self.thread_name_prefix = str(thread_name_prefix)
        self._lock = threading.Lock()
        self._stats: Counter[str] = Counter()

    @property
    def families(self) -> tuple[str, ...]:
        return LEGAL_IR_EVALUATION_FAMILIES

    def _record(self, **increments: int) -> None:
        with self._lock:
            self._stats.update(increments)

    @staticmethod
    def _invoke(evaluator: FamilyEvaluatorCallback, request: FamilyShardRequest) -> Any:
        try:
            signature = inspect.signature(evaluator)
        except (TypeError, ValueError):
            return evaluator(request)
        positional = [
            parameter
            for parameter in signature.parameters.values()
            if parameter.kind
            in (parameter.POSITIONAL_ONLY, parameter.POSITIONAL_OR_KEYWORD)
        ]
        if any(
            parameter.kind == parameter.VAR_POSITIONAL
            for parameter in signature.parameters.values()
        ):
            return evaluator(request)
        if len(positional) == 1:
            return evaluator(request)
        if len(positional) == 2:
            return evaluator(request.snapshot, request.shared_artifacts)
        if len(positional) == 3:
            return evaluator(
                request.family, request.snapshot, request.shared_artifacts
            )
        raise TypeError(
            "family evaluator must accept request, (snapshot, artifacts), or "
            "(family, snapshot, artifacts)"
        )

    @staticmethod
    def _normalize_result(
        request: FamilyShardRequest,
        raw: Any,
        *,
        started_at: str,
        elapsed_seconds: float,
    ) -> FamilyShardResult:
        if isinstance(raw, SnapshotEvaluationResult):
            raw = FamilyShardResult(
                family=request.family,
                sequence=raw.sequence,
                versions=raw.versions,
                metrics=raw.metrics,
                error=raw.error,
                retryable=bool(raw.error),
                started_at=raw.started_at or started_at,
                finished_at=raw.finished_at,
                elapsed_seconds=raw.elapsed_seconds,
            )
        if isinstance(raw, Mapping):
            raw = FamilyShardResult(
                family=request.family,
                sequence=request.sequence,
                versions=request.versions,
                metrics=raw,
                started_at=started_at,
                elapsed_seconds=elapsed_seconds,
            )
        if not isinstance(raw, FamilyShardResult):
            raise TypeError(
                "family evaluator must return a metrics mapping, "
                "FamilyShardResult, or SnapshotEvaluationResult"
            )
        mismatches = raw.versions.mismatch_fields(request.versions)
        if raw.sequence != request.sequence:
            mismatches = (*mismatches, "sequence")
        if raw.family != request.family:
            mismatches = (*mismatches, "family")
        if mismatches:
            return FamilyShardResult(
                family=request.family,
                sequence=request.sequence,
                versions=request.versions,
                error="result_identity_mismatch: " + ", ".join(mismatches),
                retryable=False,
                started_at=started_at,
                elapsed_seconds=elapsed_seconds,
            )
        return raw

    def _should_retry(self, result: FamilyShardResult) -> bool:
        if result.succeeded:
            return False
        if self.retry_predicate is not None:
            return bool(self.retry_predicate(result))
        return bool(result.retryable)

    def evaluate_family(
        self,
        family: str,
        snapshot: EvaluationSnapshot,
        shared_artifacts: SharedEvaluationArtifacts,
    ) -> FamilyShardResult:
        """Evaluate and retry one family without touching any other shard."""

        canonical = canonical_legal_ir_evaluation_family(family)
        if snapshot.versions != shared_artifacts.versions:
            raise ValueError("shared artifacts do not match snapshot")
        evaluator = self._evaluators[canonical]
        first_started_at = _utc_now()
        total_started = time.monotonic()
        errors: list[str] = []
        final: Optional[FamilyShardResult] = None
        max_attempts = self.max_retries + 1
        for attempt in range(1, max_attempts + 1):
            request = FamilyShardRequest(
                family=canonical,
                snapshot=snapshot,
                shared_artifacts=shared_artifacts,
                attempt=attempt,
            )
            attempt_started_at = _utc_now()
            attempt_started = time.monotonic()
            self._record(shard_attempts=1)
            try:
                raw = self._invoke(evaluator, request)
                current = self._normalize_result(
                    request,
                    raw,
                    started_at=attempt_started_at,
                    elapsed_seconds=max(0.0, time.monotonic() - attempt_started),
                )
            except Exception as exc:
                current = FamilyShardResult(
                    family=canonical,
                    sequence=snapshot.sequence,
                    versions=snapshot.versions,
                    error=f"{type(exc).__name__}: {exc}",
                    retryable=True,
                    started_at=attempt_started_at,
                    elapsed_seconds=max(0.0, time.monotonic() - attempt_started),
                )
            if current.failed:
                errors.append(current.error)
            final = current
            if current.succeeded or attempt >= max_attempts or not self._should_retry(current):
                break
            self._record(shard_retries=1)

        assert final is not None
        normalized = FamilyShardResult(
            family=canonical,
            sequence=snapshot.sequence,
            versions=snapshot.versions,
            metrics=final.metrics,
            error=final.error,
            attempt_count=attempt,
            attempt_errors=tuple(errors if final.failed else errors),
            retryable=final.retryable and attempt < max_attempts,
            started_at=first_started_at,
            finished_at=_utc_now(),
            elapsed_seconds=max(0.0, time.monotonic() - total_started),
        )
        self._record(
            shards_completed=1,
            shards_succeeded=int(normalized.succeeded),
            shards_failed=int(normalized.failed),
            retry_budget_exhausted=int(
                normalized.failed
                and normalized.attempt_count == max_attempts
                and final.retryable
            ),
        )
        return normalized

    def evaluate(
        self,
        snapshot: EvaluationSnapshot,
        artifacts: SharedEvaluationArtifacts | Any = (),
        *,
        artifact_metadata: Optional[Mapping[str, Any]] = None,
    ) -> FamilyEvaluationAggregate:
        """Run all family shards independently and return complete evidence."""

        if not isinstance(snapshot, EvaluationSnapshot):
            raise TypeError("snapshot must be EvaluationSnapshot")
        shared = (
            artifacts
            if isinstance(artifacts, SharedEvaluationArtifacts)
            else SharedEvaluationArtifacts.for_snapshot(
                snapshot, artifacts, metadata=artifact_metadata
            )
        )
        if shared.versions != snapshot.versions:
            raise ValueError("shared artifacts do not match snapshot")
        results: dict[str, FamilyShardResult] = {}
        with ThreadPoolExecutor(
            max_workers=self.max_workers,
            thread_name_prefix=self.thread_name_prefix,
        ) as executor:
            futures = {
                executor.submit(self.evaluate_family, family, snapshot, shared): family
                for family in LEGAL_IR_EVALUATION_FAMILIES
            }
            for future in as_completed(futures):
                family = futures[future]
                # evaluate_family converts callback exceptions.  An exception
                # here indicates a coordinator invariant and must fail closed.
                results[family] = future.result()
        aggregate = aggregate_family_results(snapshot, results)
        self._record(
            snapshots_evaluated=1,
            snapshots_succeeded=int(aggregate.succeeded),
            snapshots_failed=int(not aggregate.succeeded),
        )
        return aggregate

    run = evaluate
    evaluate_snapshot = evaluate

    def summary(self) -> dict[str, Any]:
        with self._lock:
            stats = dict(self._stats)
        return {
            "families": list(LEGAL_IR_EVALUATION_FAMILIES),
            "family_count": len(LEGAL_IR_EVALUATION_FAMILIES),
            "max_retries": self.max_retries,
            "max_attempts_per_family": self.max_retries + 1,
            "max_workers": self.max_workers,
            "retry_budget_exhausted": int(stats.get("retry_budget_exhausted", 0)),
            "schema_version": LEGAL_IR_FAMILY_EVALUATION_SCHEMA_VERSION,
            "shard_attempts": int(stats.get("shard_attempts", 0)),
            "shard_retries": int(stats.get("shard_retries", 0)),
            "shards_completed": int(stats.get("shards_completed", 0)),
            "shards_failed": int(stats.get("shards_failed", 0)),
            "shards_succeeded": int(stats.get("shards_succeeded", 0)),
            "snapshots_evaluated": int(stats.get("snapshots_evaluated", 0)),
            "snapshots_failed": int(stats.get("snapshots_failed", 0)),
            "snapshots_succeeded": int(stats.get("snapshots_succeeded", 0)),
        }


FamilyShardedEvaluator = LegalIRFamilyEvaluator
LegalIRFamilyEvaluationCoordinator = LegalIRFamilyEvaluator


__all__ = [
    "FamilyEvaluationAggregate",
    "FamilyEvaluationError",
    "FamilyEvaluationResult",
    "FamilyShardRequest",
    "FamilyShardResult",
    "FamilyShardedEvaluator",
    "FamilySnapshotMismatchError",
    "IncompleteFamilyEvaluationError",
    "LEGAL_IR_EVALUATION_FAMILIES",
    "LEGAL_IR_FAMILY_SHARDS",
    "LEGAL_IR_FAMILY_EVALUATION_SCHEMA_VERSION",
    "LEGAL_IR_SEMANTIC_FAMILIES",
    "LegalIRFamilyEvaluation",
    "LegalIRFamilyEvaluationCoordinator",
    "LegalIRFamilyEvaluationResult",
    "LegalIRFamilyEvaluator",
    "LegalIRFamilyShardResult",
    "LegalIRFamilyShardRequest",
    "REQUIRED_LEGAL_IR_FAMILIES",
    "SharedEvaluationArtifacts",
    "SharedLegalIRArtifacts",
    "aggregate_family_results",
    "canonical_legal_ir_evaluation_family",
]
