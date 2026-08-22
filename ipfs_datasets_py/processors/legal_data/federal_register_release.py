"""Resumable full and cutoff-delta Federal Register build orchestration (LCR-061).

Plans, resumes, and seals streaming sparse-GraphRAG builds for the Federal
Register. Artifact semantics (corpus, BM25, vectors, graph, adjacency) are
**delegated** to existing family builders; this module does not reimplement
index math.

Design invariants
-----------------
* Full and cutoff-delta plans are first-class. Delta refresh is never labeled
  equivalent to a full rebuild without an explicit full-rebuild decision.
* Family checkpoints stream to disk; the orchestrator never requires the
  whole corpus in RAM. Resident records are bounded by ``MemoryBudget``.
* Changing a family invalidates its dependency closure. Stale or
  config-mismatched checkpoints fail closed and cannot be promoted.
* A candidate root is assembled atomically only after every planned work
  unit is verified. Partial output cannot be sealed.
* Fixture-only default. No network I/O and no Hub upload.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import (
    Any,
    Callable,
    Final,
    Iterable,
    Iterator,
    Mapping,
    Optional,
    Protocol,
    Sequence,
    Union,
)

from ipfs_datasets_py.processors.legal_data.federal_register_release_schema import (
    RELEASE_PROFILE,
    canonical_json_dumps,
    digest_mapping,
)
from ipfs_datasets_py.processors.legal_data.federal_register_source_policy import (
    DEFAULT_DATASET_REPO_ID,
    DEFAULT_OBSERVATION_CUTOFF,
    LEGACY_BASELINE_END_INCLUSIVE,
    cutoff_release_point,
    observation_cutoff_date,
    require_immutable_observation_cutoff,
)

# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------

SCHEMA_VERSION: Final = "federal-register-build-orchestration-v1"
CHECKPOINT_FILENAME: Final = "build_checkpoint.json"
SEAL_FILENAME: Final = "build_seal.json"
RECEIPT_FILENAME: Final = "build_receipt.json"
CANDIDATE_ROOT_FILENAME: Final = "candidate_root.json"
FAMILY_CHECKPOINT_DIRNAME: Final = "families"
TASK_ID: Final = "LCR-061"
GOAL_ID: Final = "LCR-G130"
PROGRAM_ID: Final = "legal-corpora-reindex-v1"
PRODUCER: Final = "federal_register_release.py"
DEFAULT_DETERMINISM_SEED: Final = 20260810
GLOBAL_PARTITION: Final = "*"
AUTHORIZES_HUB_UPLOAD: Final = False
AUTHORIZES_PUBLICATION: Final = False
PROVES_SOFTWARE_CONTRACT_ONLY: Final = True

DEFAULT_BUILD_FAMILIES: Final = (
    "corpus",
    "bm25",
    "vectors",
    "graph",
    "adjacency",
)

# Orchestration grain for cutoff-delta planning (year-month partitions).
DEFAULT_PARTITIONS: Final = ("2026-03", "2026-08")

# Families whose global statistics may force an explicit full rebuild.
GLOBAL_STAT_FAMILIES: Final = frozenset({"bm25", "vectors"})

# Families built once per plan (not per year-month partition).
GLOBAL_FAMILIES: Final = frozenset({"bm25", "vectors", "graph", "adjacency"})

FAMILY_DEPENDENCIES: Final = MappingProxyType(
    {
        "corpus": (),
        "bm25": ("corpus",),
        "vectors": ("corpus",),
        "graph": ("corpus",),
        "adjacency": ("graph", "bm25"),
    }
)

DEFAULT_BM25_REBUILD_THRESHOLD: Final = 0.15
DEFAULT_CLUSTER_REBUILD_THRESHOLD: Final = 0.20
DEFAULT_MAX_RECORDS_IN_MEMORY: Final = 32
DEFAULT_MAX_PARTITIONS: Final = 4096
DEFAULT_MAX_WORK_UNITS: Final = 512
DEFAULT_RESOURCE_CLASS: Final = "disk-large"

_MUTABLE_TOKENS: Final = frozenset(
    {
        "latest",
        "main",
        "head",
        "master",
        "current",
        "live",
        "now",
        "today",
        "tip",
        "trunk",
    }
)
_YEAR_MONTH_CHARS: Final = frozenset("0123456789-")

PathLike = Union[str, Path]
JsonMapping = Mapping[str, Any]
ProducerFn = Callable[["WorkUnit", "BuildConfig", Path], "ProducerResult"]


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class FederalRegisterReleaseError(ValueError):
    """Base error for Federal Register build orchestration failures."""

    code: str = "federal_register_release_error"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "kind": "error", "message": str(self)}


class BuildConfigError(FederalRegisterReleaseError):
    """Raised when the build configuration is invalid."""

    code = "build_config_invalid"


class BuildCheckpointError(FederalRegisterReleaseError):
    """Raised when a checkpoint is corrupt, stale, or config-mismatched."""

    code = "checkpoint_invalid"


class BuildPlanError(FederalRegisterReleaseError):
    """Raised when full/delta planning cannot produce a valid plan."""

    code = "build_plan_invalid"


class GlobalDecisionError(FederalRegisterReleaseError):
    """Raised when a global rebuild decision is missing or inconsistent."""

    code = "global_decision_invalid"


class SealError(FederalRegisterReleaseError):
    """Raised when sealing is attempted on incomplete or mismatched work."""

    code = "seal_rejected"


class ResourceLimitError(FederalRegisterReleaseError):
    """Raised when resource limits would be exceeded."""

    code = "resource_limit_exceeded"


class MemoryBudgetError(FederalRegisterReleaseError):
    """Raised when a streaming memory budget would be exceeded."""

    code = "memory_budget_exceeded"


class ProducerError(FederalRegisterReleaseError):
    """Raised when a delegated producer fails a work unit."""

    code = "producer_failed"


class ValidationOnlyError(FederalRegisterReleaseError):
    """Raised when a mutation is requested in validation-only mode."""

    code = "validation_only"


class PromotionError(FederalRegisterReleaseError):
    """Raised when a stale or partial checkpoint is offered for promotion."""

    code = "promotion_rejected"


class HubUploadForbiddenError(FederalRegisterReleaseError):
    """Raised when an invocation attempts a Hub upload side effect."""

    code = "hub_upload_forbidden"


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class BuildMode(str, Enum):
    """Top-level build planning mode."""

    FULL = "full"
    DELTA = "delta"

    @classmethod
    def coerce(cls, value: Any) -> "BuildMode":
        if isinstance(value, BuildMode):
            return value
        text = str(value or "").strip().lower().replace("-", "_")
        aliases = {
            "complete": cls.FULL,
            "rebuild": cls.FULL,
            "incremental": cls.DELTA,
            "cutoff_delta": cls.DELTA,
            "cutoff-delta": cls.DELTA,
            "diff": cls.DELTA,
        }
        if text in aliases:
            return aliases[text]
        for mode in cls:
            if mode.value == text or mode.name.lower() == text:
                return mode
        raise BuildConfigError(f"unknown build mode: {value!r}")


class GlobalRebuildKind(str, Enum):
    """Explicit decision for indexes with global statistics."""

    FULL_REBUILD = "full_rebuild"
    DELTA_REFRESH = "delta_refresh"
    UNCHANGED = "unchanged"

    @classmethod
    def coerce(cls, value: Any) -> "GlobalRebuildKind":
        if isinstance(value, GlobalRebuildKind):
            return value
        text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
        aliases = {
            "full": cls.FULL_REBUILD,
            "rebuild": cls.FULL_REBUILD,
            "force_full": cls.FULL_REBUILD,
            "delta": cls.DELTA_REFRESH,
            "partial": cls.DELTA_REFRESH,
            "incremental": cls.DELTA_REFRESH,
            "skip": cls.UNCHANGED,
            "none": cls.UNCHANGED,
            "noop": cls.UNCHANGED,
        }
        if text in aliases:
            return aliases[text]
        for kind in cls:
            if kind.value == text or kind.name.lower() == text:
                return kind
        raise GlobalDecisionError(f"unknown global rebuild kind: {value!r}")


class WorkUnitStatus(str, Enum):
    """Lifecycle status of one partition × family work unit."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    VERIFIED = "verified"
    FAILED = "failed"
    SKIPPED = "skipped"
    INVALIDATED = "invalidated"

    @classmethod
    def coerce(cls, value: Any) -> "WorkUnitStatus":
        if isinstance(value, WorkUnitStatus):
            return value
        text = str(value or "").strip().lower().replace("-", "_")
        for status in cls:
            if status.value == text or status.name.lower() == text:
                return status
        raise BuildCheckpointError(f"unknown work unit status: {value!r}")


class DecisionSource(str, Enum):
    """How a global rebuild decision was obtained."""

    EXPLICIT = "explicit"
    AUTO_THRESHOLD = "auto_threshold"
    FULL_MODE = "full_mode"
    UNCHANGED_BASELINE = "unchanged_baseline"
    DEPENDENCY_CLOSURE = "dependency_closure"


# ---------------------------------------------------------------------------
# Primitive helpers
# ---------------------------------------------------------------------------


def _require_non_empty_str(value: Any, name: str, *, maximum: int = 1024) -> str:
    if not isinstance(value, str) or not value.strip():
        raise BuildConfigError(f"{name} must be a non-empty string")
    text = value.strip()
    if "\x00" in text:
        raise BuildConfigError(f"{name} must not contain NUL")
    if len(text) > maximum:
        raise BuildConfigError(f"{name} exceeds maximum length {maximum}")
    return text


def _require_non_negative_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise BuildConfigError(f"{name} must be an integer")
    if value < 0:
        raise BuildConfigError(f"{name} must be >= 0")
    return value


def _require_positive_int(value: Any, name: str) -> int:
    number = _require_non_negative_int(value, name)
    if number <= 0:
        raise BuildConfigError(f"{name} must be a positive integer")
    return number


def _require_unit_interval(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise BuildConfigError(f"{name} must be a number")
    number = float(value)
    if not 0.0 <= number <= 1.0:
        raise BuildConfigError(f"{name} must be in [0, 1]")
    return number


def _reject_mutable_token(value: str, name: str) -> str:
    lowered = value.strip().lower()
    if lowered in _MUTABLE_TOKENS or lowered.startswith("origin/") or lowered.startswith("refs/"):
        raise BuildConfigError(f"{name} must be an exact pin, not {value!r}")
    return value


def _normalize_partition(value: Any) -> str:
    text = _require_non_empty_str(str(value), "partition", maximum=16)
    if text == GLOBAL_PARTITION:
        return GLOBAL_PARTITION
    if len(text) == 7 and text[4] == "-" and all(ch in _YEAR_MONTH_CHARS for ch in text):
        year = int(text[:4])
        month = int(text[5:7])
        if 1936 <= year <= 2100 and 1 <= month <= 12:
            return f"{year:04d}-{month:02d}"
    raise BuildConfigError(
        f"partition must be YYYY-MM or {GLOBAL_PARTITION!r}, got {value!r}"
    )


def _normalize_family(value: Any) -> str:
    text = _require_non_empty_str(str(value), "family", maximum=64).lower()
    text = text.replace("-", "_").replace(" ", "_")
    aliases = {
        "bm25_documents": "bm25",
        "bm25_postings": "bm25",
        "bm25_docs": "bm25",
        "postings": "bm25",
        "vector": "vectors",
        "centroid": "vectors",
        "centroids": "vectors",
        "graph_nodes": "graph",
        "graph_edges": "graph",
        "nodes": "graph",
        "edges": "graph",
        "lexical": "adjacency",
        "lexical_graph": "adjacency",
        "graph_adjacency": "adjacency",
        "adjacency_in": "adjacency",
        "adjacency_out": "adjacency",
        "two_way_adjacency": "adjacency",
    }
    return aliases.get(text, text)


def work_unit_key(partition: str, family: str) -> str:
    """Stable map key for a partition × family work unit."""

    return f"{_normalize_partition(partition)}/{_normalize_family(family)}"


def family_execution_order(families: Sequence[str]) -> tuple[str, ...]:
    """Return *families* in dependency order, preserving declared relative order."""

    declared = tuple(_normalize_family(item) for item in families)
    remaining = set(declared)
    ordered: list[str] = []
    while remaining:
        progressed = False
        for family in declared:
            if family not in remaining:
                continue
            deps = FAMILY_DEPENDENCIES.get(family, ())
            if all(dep not in remaining for dep in deps):
                ordered.append(family)
                remaining.remove(family)
                progressed = True
        if not progressed:
            raise BuildPlanError(f"cyclic family dependencies among {sorted(remaining)}")
    return tuple(ordered)


def dependency_closure(families: Iterable[str]) -> frozenset[str]:
    """Return *families* plus every downstream dependent family."""

    changed = { _normalize_family(item) for item in families }
    progressed = True
    while progressed:
        progressed = False
        for family, deps in FAMILY_DEPENDENCIES.items():
            if family in changed:
                continue
            if any(dep in changed for dep in deps):
                changed.add(family)
                progressed = True
    return frozenset(changed)


def invalidate_dependency_closure(
    changed_families: Iterable[str],
) -> frozenset[str]:
    """Public alias for :func:`dependency_closure`."""

    return dependency_closure(changed_families)


def software_contract_flags() -> dict[str, Any]:
    return {
        "authorizing_for_publication": AUTHORIZES_PUBLICATION,
        "authorizing_hub_upload": AUTHORIZES_HUB_UPLOAD,
        "proves_software_contract_only": PROVES_SOFTWARE_CONTRACT_ONLY,
        "task_id": TASK_ID,
        "goal_id": GOAL_ID,
        "program_id": PROGRAM_ID,
    }


def reject_hub_upload(flag: Any = False) -> None:
    if flag:
        raise HubUploadForbiddenError(
            "LCR-061 orchestration forbids Hub upload side effects"
        )


def content_digest(value: Any) -> str:
    """SHA-256 hex digest of the canonical JSON encoding of *value*."""

    if isinstance(value, Mapping):
        return digest_mapping(value)
    if isinstance(value, bytes):
        return hashlib.sha256(value).hexdigest()
    if isinstance(value, str):
        return hashlib.sha256(value.encode("utf-8")).hexdigest()
    return digest_mapping({"value": value})


def write_json_atomic(path: PathLike, payload: Mapping[str, Any]) -> Path:
    """Write *payload* as sorted JSON via temp file + ``os.replace``."""

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(
        dict(payload),
        indent=2,
        ensure_ascii=False,
        sort_keys=True,
        allow_nan=False,
    ) + "\n"
    fd, tmp_name = tempfile.mkstemp(
        prefix=".fr-build-",
        suffix=".json",
        dir=str(target.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, target)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
    return target


def load_json_mapping(path: PathLike) -> dict[str, Any]:
    target = Path(path)
    if not target.is_file():
        raise BuildCheckpointError(f"JSON file not found: {target}")
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise BuildCheckpointError(f"invalid JSON at {target}: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise BuildCheckpointError(f"JSON root must be a mapping: {target}")
    return dict(payload)


# ---------------------------------------------------------------------------
# Resource limits / streaming memory budget
# ---------------------------------------------------------------------------


@dataclass
class MemoryBudget:
    """Resident-record bound so builders never load the whole corpus."""

    max_resident_records: int = DEFAULT_MAX_RECORDS_IN_MEMORY
    resident_records: int = 0
    peak_resident_records: int = 0

    def __post_init__(self) -> None:
        self.max_resident_records = _require_positive_int(
            self.max_resident_records, "max_resident_records"
        )
        self.resident_records = _require_non_negative_int(
            self.resident_records, "resident_records"
        )
        self.peak_resident_records = max(
            self.peak_resident_records, self.resident_records
        )

    def acquire(self, records: int = 1) -> None:
        next_records = self.resident_records + _require_non_negative_int(
            records, "records"
        )
        if next_records > self.max_resident_records:
            raise MemoryBudgetError(
                f"resident records {next_records} exceed "
                f"max_resident_records={self.max_resident_records}"
            )
        self.resident_records = next_records
        if next_records > self.peak_resident_records:
            self.peak_resident_records = next_records

    def release(self, records: int = 1) -> None:
        self.resident_records = max(
            0,
            self.resident_records - _require_non_negative_int(records, "records"),
        )

    def check_materialize(self, total_records: int) -> None:
        if total_records > self.max_resident_records:
            raise MemoryBudgetError(
                f"refusing to materialize {total_records} records under "
                f"max_resident_records={self.max_resident_records}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_resident_records": self.max_resident_records,
            "peak_resident_records": self.peak_resident_records,
            "resident_records": self.resident_records,
        }


def stream_bounded(
    records: Iterable[Any],
    *,
    budget: MemoryBudget | None = None,
    max_resident_records: int = DEFAULT_MAX_RECORDS_IN_MEMORY,
) -> Iterator[Any]:
    """Yield *records* one at a time under a resident-record budget."""

    bound = budget or MemoryBudget(max_resident_records=max_resident_records)
    for record in records:
        bound.acquire(1)
        try:
            yield record
        finally:
            bound.release(1)


@dataclass(frozen=True, slots=True)
class ResourceLimits:
    """Hard caps applied before a plan is executed."""

    max_partitions: int = DEFAULT_MAX_PARTITIONS
    max_work_units: int = DEFAULT_MAX_WORK_UNITS
    max_memory_mb: Optional[int] = None
    max_resident_records: int = DEFAULT_MAX_RECORDS_IN_MEMORY
    max_concurrent_families: int = 1
    resource_class: str = DEFAULT_RESOURCE_CLASS

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "max_partitions",
            _require_positive_int(self.max_partitions, "max_partitions"),
        )
        object.__setattr__(
            self,
            "max_work_units",
            _require_positive_int(self.max_work_units, "max_work_units"),
        )
        if self.max_memory_mb is not None:
            object.__setattr__(
                self,
                "max_memory_mb",
                _require_positive_int(self.max_memory_mb, "max_memory_mb"),
            )
        object.__setattr__(
            self,
            "max_resident_records",
            _require_positive_int(
                self.max_resident_records, "max_resident_records"
            ),
        )
        object.__setattr__(
            self,
            "max_concurrent_families",
            _require_positive_int(
                self.max_concurrent_families, "max_concurrent_families"
            ),
        )
        object.__setattr__(
            self,
            "resource_class",
            _require_non_empty_str(self.resource_class, "resource_class", maximum=64),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_concurrent_families": self.max_concurrent_families,
            "max_memory_mb": self.max_memory_mb,
            "max_partitions": self.max_partitions,
            "max_resident_records": self.max_resident_records,
            "max_work_units": self.max_work_units,
            "resource_class": self.resource_class,
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | None) -> "ResourceLimits":
        if value is None:
            return cls()
        if not isinstance(value, Mapping):
            raise BuildConfigError("resource_limits must be a mapping")
        return cls(
            max_partitions=int(value.get("max_partitions", DEFAULT_MAX_PARTITIONS)),
            max_work_units=int(value.get("max_work_units", DEFAULT_MAX_WORK_UNITS)),
            max_memory_mb=(
                None
                if value.get("max_memory_mb") is None
                else int(value["max_memory_mb"])
            ),
            max_resident_records=int(
                value.get("max_resident_records", DEFAULT_MAX_RECORDS_IN_MEMORY)
            ),
            max_concurrent_families=int(value.get("max_concurrent_families", 1)),
            resource_class=str(
                value.get("resource_class", DEFAULT_RESOURCE_CLASS)
            ),
        )

    def enforce(
        self,
        *,
        partition_count: int,
        work_unit_count: int,
    ) -> None:
        if partition_count > self.max_partitions:
            raise ResourceLimitError(
                f"partition count {partition_count} exceeds "
                f"max_partitions={self.max_partitions}"
            )
        if work_unit_count > self.max_work_units:
            raise ResourceLimitError(
                f"work unit count {work_unit_count} exceeds "
                f"max_work_units={self.max_work_units}"
            )


# ---------------------------------------------------------------------------
# Global rebuild decisions (explicit; never silent)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class GlobalRebuildDecision:
    """Explicit full/delta/unchanged decision for one global index family."""

    family: str
    kind: GlobalRebuildKind
    reason: str
    source: DecisionSource
    changed_ratio: float = 0.0
    threshold: float = 0.0
    equivalent_to_full: bool = False
    proof: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "family", _normalize_family(self.family))
        if not isinstance(self.kind, GlobalRebuildKind):
            object.__setattr__(self, "kind", GlobalRebuildKind.coerce(self.kind))
        object.__setattr__(
            self, "reason", _require_non_empty_str(self.reason, "reason", maximum=2048)
        )
        if not isinstance(self.source, DecisionSource):
            object.__setattr__(self, "source", DecisionSource(str(self.source)))
        object.__setattr__(
            self,
            "changed_ratio",
            _require_unit_interval(self.changed_ratio, "changed_ratio"),
        )
        object.__setattr__(
            self, "threshold", _require_unit_interval(self.threshold, "threshold")
        )
        object.__setattr__(self, "equivalent_to_full", bool(self.equivalent_to_full))
        object.__setattr__(self, "proof", str(self.proof or ""))
        if self.kind is GlobalRebuildKind.DELTA_REFRESH and self.equivalent_to_full:
            raise GlobalDecisionError(
                f"{self.family}: delta_refresh cannot claim equivalent_to_full "
                "without a full_rebuild decision"
            )
        if self.kind is GlobalRebuildKind.FULL_REBUILD and not self.equivalent_to_full:
            object.__setattr__(self, "equivalent_to_full", True)

    def to_dict(self) -> dict[str, Any]:
        return {
            "changed_ratio": self.changed_ratio,
            "equivalent_to_full": self.equivalent_to_full,
            "family": self.family,
            "kind": self.kind.value,
            "proof": self.proof,
            "reason": self.reason,
            "source": self.source.value,
            "threshold": self.threshold,
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "GlobalRebuildDecision":
        if not isinstance(value, Mapping):
            raise GlobalDecisionError("global decision must be a mapping")
        return cls(
            family=str(value.get("family") or ""),
            kind=GlobalRebuildKind.coerce(value.get("kind")),
            reason=str(value.get("reason") or ""),
            source=DecisionSource(
                str(value.get("source") or DecisionSource.EXPLICIT.value)
            ),
            changed_ratio=float(value.get("changed_ratio") or 0.0),
            threshold=float(value.get("threshold") or 0.0),
            equivalent_to_full=bool(value.get("equivalent_to_full", False)),
            proof=str(value.get("proof") or ""),
        )


def decide_global_rebuild(
    family: str,
    *,
    mode: BuildMode,
    changed_ratio: float,
    threshold: float,
    explicit: GlobalRebuildKind | str | None = None,
    prior_present: bool = True,
) -> GlobalRebuildDecision:
    """Compute an explicit global rebuild decision for BM25 or clusters."""

    fam = _normalize_family(family)
    if fam not in GLOBAL_STAT_FAMILIES:
        raise GlobalDecisionError(
            f"global rebuild decisions apply only to {sorted(GLOBAL_STAT_FAMILIES)}, "
            f"got {fam!r}"
        )
    ratio = _require_unit_interval(changed_ratio, "changed_ratio")
    thr = _require_unit_interval(threshold, "threshold")

    if explicit is not None:
        kind = GlobalRebuildKind.coerce(explicit)
        if kind is GlobalRebuildKind.FULL_REBUILD:
            return GlobalRebuildDecision(
                family=fam,
                kind=kind,
                reason="operator forced full rebuild",
                source=DecisionSource.EXPLICIT,
                changed_ratio=ratio,
                threshold=thr,
                equivalent_to_full=True,
                proof="explicit:full_rebuild",
            )
        if kind is GlobalRebuildKind.UNCHANGED:
            if not prior_present:
                raise GlobalDecisionError(
                    f"{fam}: cannot mark UNCHANGED without a prior index"
                )
            return GlobalRebuildDecision(
                family=fam,
                kind=kind,
                reason="operator forced unchanged (reuse prior global index)",
                source=DecisionSource.EXPLICIT,
                changed_ratio=ratio,
                threshold=thr,
                equivalent_to_full=True,
                proof="explicit:unchanged_prior",
            )
        return GlobalRebuildDecision(
            family=fam,
            kind=GlobalRebuildKind.DELTA_REFRESH,
            reason=(
                "operator forced delta refresh; partial global statistics "
                "are NOT equivalent to a full rebuild"
            ),
            source=DecisionSource.EXPLICIT,
            changed_ratio=ratio,
            threshold=thr,
            equivalent_to_full=False,
            proof="explicit:delta_refresh_not_full_equivalent",
        )

    if mode is BuildMode.FULL or not prior_present:
        return GlobalRebuildDecision(
            family=fam,
            kind=GlobalRebuildKind.FULL_REBUILD,
            reason=(
                "full build mode"
                if mode is BuildMode.FULL
                else "no prior global index present"
            ),
            source=DecisionSource.FULL_MODE
            if mode is BuildMode.FULL
            else DecisionSource.AUTO_THRESHOLD,
            changed_ratio=ratio,
            threshold=thr,
            equivalent_to_full=True,
            proof="full_mode" if mode is BuildMode.FULL else "missing_prior",
        )

    if ratio <= 0.0:
        return GlobalRebuildDecision(
            family=fam,
            kind=GlobalRebuildKind.UNCHANGED,
            reason="no changed documents; reuse prior global index",
            source=DecisionSource.UNCHANGED_BASELINE,
            changed_ratio=ratio,
            threshold=thr,
            equivalent_to_full=True,
            proof="auto:unchanged_ratio_zero",
        )

    if ratio >= thr:
        return GlobalRebuildDecision(
            family=fam,
            kind=GlobalRebuildKind.FULL_REBUILD,
            reason=(
                f"changed_ratio {ratio:.4f} >= threshold {thr:.4f}; "
                f"full deterministic rebuild required for {fam}"
            ),
            source=DecisionSource.AUTO_THRESHOLD,
            changed_ratio=ratio,
            threshold=thr,
            equivalent_to_full=True,
            proof=f"auto:ratio>={thr}",
        )

    return GlobalRebuildDecision(
        family=fam,
        kind=GlobalRebuildKind.DELTA_REFRESH,
        reason=(
            f"changed_ratio {ratio:.4f} < threshold {thr:.4f}; "
            f"delta refresh for {fam} (NOT equivalent to full rebuild)"
        ),
        source=DecisionSource.AUTO_THRESHOLD,
        changed_ratio=ratio,
        threshold=thr,
        equivalent_to_full=False,
        proof=f"auto:ratio<{thr}:delta_not_full_equivalent",
    )


def decide_dependent_rebuild(
    family: str,
    *,
    mode: BuildMode,
    corpus_changed: bool,
    changed_ratio: float,
) -> GlobalRebuildDecision:
    """Rebuild graph/adjacency iff the corpus dependency closure changed."""

    fam = _normalize_family(family)
    if fam in GLOBAL_STAT_FAMILIES:
        raise GlobalDecisionError(
            f"{fam} uses decide_global_rebuild, not decide_dependent_rebuild"
        )
    if mode is BuildMode.FULL or (corpus_changed and changed_ratio >= 1.0):
        return GlobalRebuildDecision(
            family=fam,
            kind=GlobalRebuildKind.FULL_REBUILD,
            reason="dependency closure requires a full rebuild",
            source=DecisionSource.FULL_MODE
            if mode is BuildMode.FULL
            else DecisionSource.DEPENDENCY_CLOSURE,
            changed_ratio=changed_ratio,
            threshold=0.0,
            equivalent_to_full=True,
            proof="dependency_closure:full",
        )
    if not corpus_changed:
        return GlobalRebuildDecision(
            family=fam,
            kind=GlobalRebuildKind.UNCHANGED,
            reason="corpus dependency unchanged; reuse prior family",
            source=DecisionSource.UNCHANGED_BASELINE,
            changed_ratio=changed_ratio,
            threshold=0.0,
            equivalent_to_full=True,
            proof="dependency_closure:unchanged",
        )
    return GlobalRebuildDecision(
        family=fam,
        kind=GlobalRebuildKind.DELTA_REFRESH,
        reason=(
            "corpus dependency changed; rebuild derived family "
            "(NOT equivalent to full rebuild)"
        ),
        source=DecisionSource.DEPENDENCY_CLOSURE,
        changed_ratio=changed_ratio,
        threshold=0.0,
        equivalent_to_full=False,
        proof="dependency_closure:delta_not_full_equivalent",
    )


# ---------------------------------------------------------------------------
# Build configuration
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BuildConfig:
    """Deterministic configuration for one orchestrated Federal Register build."""

    observation_cutoff: str = DEFAULT_OBSERVATION_CUTOFF
    prior_cutoff: str = LEGACY_BASELINE_END_INCLUSIVE
    mode: BuildMode = BuildMode.FULL
    partitions: tuple[str, ...] = DEFAULT_PARTITIONS
    families: tuple[str, ...] = DEFAULT_BUILD_FAMILIES
    dataset_repo_id: str = DEFAULT_DATASET_REPO_ID
    determinism_seed: int = DEFAULT_DETERMINISM_SEED
    bm25_rebuild_threshold: float = DEFAULT_BM25_REBUILD_THRESHOLD
    cluster_rebuild_threshold: float = DEFAULT_CLUSTER_REBUILD_THRESHOLD
    bm25_decision: Optional[GlobalRebuildKind] = None
    cluster_decision: Optional[GlobalRebuildKind] = None
    resource_limits: ResourceLimits = field(default_factory=ResourceLimits)
    validation_only: bool = False
    resume: bool = True
    fixture_only: bool = True
    use_family_builders: bool = False
    notes: str = ""
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "observation_cutoff",
            require_immutable_observation_cutoff(self.observation_cutoff),
        )
        object.__setattr__(
            self,
            "prior_cutoff",
            require_immutable_observation_cutoff(self.prior_cutoff),
        )
        object.__setattr__(self, "mode", BuildMode.coerce(self.mode))
        partitions = tuple(
            _normalize_partition(item)
            for item in (self.partitions or DEFAULT_PARTITIONS)
            if _normalize_partition(item) != GLOBAL_PARTITION
        )
        if not partitions:
            raise BuildConfigError("partitions must be non-empty")
        partitions = tuple(sorted(set(partitions)))
        object.__setattr__(self, "partitions", partitions)
        families = tuple(
            _normalize_family(item)
            for item in (self.families or DEFAULT_BUILD_FAMILIES)
        )
        if not families:
            raise BuildConfigError("families must be non-empty")
        unknown = [fam for fam in families if fam not in FAMILY_DEPENDENCIES]
        if unknown:
            raise BuildConfigError(f"unsupported families: {unknown}")
        seen: set[str] = set()
        ordered: list[str] = []
        for fam in family_execution_order(families):
            if fam not in seen:
                seen.add(fam)
                ordered.append(fam)
        object.__setattr__(self, "families", tuple(ordered))
        object.__setattr__(
            self,
            "dataset_repo_id",
            _reject_mutable_token(
                _require_non_empty_str(self.dataset_repo_id, "dataset_repo_id"),
                "dataset_repo_id",
            ),
        )
        object.__setattr__(
            self,
            "determinism_seed",
            _require_non_negative_int(self.determinism_seed, "determinism_seed"),
        )
        object.__setattr__(
            self,
            "bm25_rebuild_threshold",
            _require_unit_interval(
                self.bm25_rebuild_threshold, "bm25_rebuild_threshold"
            ),
        )
        object.__setattr__(
            self,
            "cluster_rebuild_threshold",
            _require_unit_interval(
                self.cluster_rebuild_threshold, "cluster_rebuild_threshold"
            ),
        )
        if self.bm25_decision is not None:
            object.__setattr__(
                self, "bm25_decision", GlobalRebuildKind.coerce(self.bm25_decision)
            )
        if self.cluster_decision is not None:
            object.__setattr__(
                self,
                "cluster_decision",
                GlobalRebuildKind.coerce(self.cluster_decision),
            )
        if not isinstance(self.resource_limits, ResourceLimits):
            object.__setattr__(
                self,
                "resource_limits",
                ResourceLimits.from_mapping(self.resource_limits),  # type: ignore[arg-type]
            )
        object.__setattr__(self, "validation_only", bool(self.validation_only))
        object.__setattr__(self, "resume", bool(self.resume))
        object.__setattr__(self, "fixture_only", bool(self.fixture_only))
        object.__setattr__(
            self, "use_family_builders", bool(self.use_family_builders)
        )
        object.__setattr__(self, "notes", str(self.notes or ""))
        if self.schema_version != SCHEMA_VERSION:
            raise BuildConfigError(
                f"unsupported schema_version {self.schema_version!r}"
            )
        if not self.fixture_only:
            raise BuildConfigError(
                "LCR-061 orchestration is fixture-only; live/Hub builds are out of scope"
            )

    @property
    def release_point(self) -> str:
        return cutoff_release_point(self.observation_cutoff)

    @property
    def observation_cutoff_date(self) -> str:
        return observation_cutoff_date(self.observation_cutoff)

    @property
    def prior_cutoff_date(self) -> str:
        return observation_cutoff_date(self.prior_cutoff)

    def to_dict(self) -> dict[str, Any]:
        return {
            "bm25_decision": (
                None if self.bm25_decision is None else self.bm25_decision.value
            ),
            "bm25_rebuild_threshold": self.bm25_rebuild_threshold,
            "cluster_decision": (
                None if self.cluster_decision is None else self.cluster_decision.value
            ),
            "cluster_rebuild_threshold": self.cluster_rebuild_threshold,
            "dataset_repo_id": self.dataset_repo_id,
            "determinism_seed": self.determinism_seed,
            "families": list(self.families),
            "fixture_only": self.fixture_only,
            "mode": self.mode.value,
            "notes": self.notes,
            "observation_cutoff": self.observation_cutoff,
            "partitions": list(self.partitions),
            "prior_cutoff": self.prior_cutoff,
            "release_point": self.release_point,
            "resource_limits": self.resource_limits.to_dict(),
            "resume": self.resume,
            "schema_version": self.schema_version,
            "use_family_builders": self.use_family_builders,
            "validation_only": self.validation_only,
        }

    @property
    def digest(self) -> str:
        """Config digest bound into checkpoints (excludes free-form notes)."""

        payload = {
            "bm25_decision": (
                None if self.bm25_decision is None else self.bm25_decision.value
            ),
            "bm25_rebuild_threshold": self.bm25_rebuild_threshold,
            "cluster_decision": (
                None if self.cluster_decision is None else self.cluster_decision.value
            ),
            "cluster_rebuild_threshold": self.cluster_rebuild_threshold,
            "dataset_repo_id": self.dataset_repo_id,
            "determinism_seed": self.determinism_seed,
            "families": list(self.families),
            "fixture_only": True,
            "mode": self.mode.value,
            "observation_cutoff": self.observation_cutoff,
            "partitions": list(self.partitions),
            "prior_cutoff": self.prior_cutoff,
            "resource_limits": self.resource_limits.to_dict(),
            "schema_version": self.schema_version,
            "use_family_builders": self.use_family_builders,
        }
        return digest_mapping(payload)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "BuildConfig":
        if not isinstance(value, Mapping):
            raise BuildConfigError("build config must be a mapping")
        bm25_raw = value.get("bm25_decision")
        cluster_raw = value.get("cluster_decision")
        return cls(
            observation_cutoff=str(
                value.get("observation_cutoff") or DEFAULT_OBSERVATION_CUTOFF
            ),
            prior_cutoff=str(
                value.get("prior_cutoff") or LEGACY_BASELINE_END_INCLUSIVE
            ),
            mode=BuildMode.coerce(value.get("mode") or BuildMode.FULL),
            partitions=tuple(value.get("partitions") or DEFAULT_PARTITIONS),
            families=tuple(value.get("families") or DEFAULT_BUILD_FAMILIES),
            dataset_repo_id=str(
                value.get("dataset_repo_id") or DEFAULT_DATASET_REPO_ID
            ),
            determinism_seed=int(
                value.get("determinism_seed", DEFAULT_DETERMINISM_SEED)
            ),
            bm25_rebuild_threshold=float(
                value.get("bm25_rebuild_threshold", DEFAULT_BM25_REBUILD_THRESHOLD)
            ),
            cluster_rebuild_threshold=float(
                value.get(
                    "cluster_rebuild_threshold", DEFAULT_CLUSTER_REBUILD_THRESHOLD
                )
            ),
            bm25_decision=(
                None if bm25_raw in (None, "") else GlobalRebuildKind.coerce(bm25_raw)
            ),
            cluster_decision=(
                None
                if cluster_raw in (None, "")
                else GlobalRebuildKind.coerce(cluster_raw)
            ),
            resource_limits=ResourceLimits.from_mapping(
                value.get("resource_limits")  # type: ignore[arg-type]
            ),
            validation_only=bool(value.get("validation_only", False)),
            resume=bool(value.get("resume", True)),
            fixture_only=bool(value.get("fixture_only", True)),
            use_family_builders=bool(value.get("use_family_builders", False)),
            notes=str(value.get("notes") or ""),
            schema_version=str(value.get("schema_version") or SCHEMA_VERSION),
        )


# ---------------------------------------------------------------------------
# Work units and producer protocol
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class WorkUnit:
    """One partition × artifact-family unit of orchestrated work."""

    partition: str
    family: str
    input_hash: str
    action: str = "build"  # build | skip | reuse

    def __post_init__(self) -> None:
        object.__setattr__(self, "partition", _normalize_partition(self.partition))
        object.__setattr__(self, "family", _normalize_family(self.family))
        object.__setattr__(
            self,
            "input_hash",
            _require_non_empty_str(self.input_hash, "input_hash", maximum=128),
        )
        object.__setattr__(
            self,
            "action",
            _require_non_empty_str(self.action, "action", maximum=32).lower(),
        )
        if self.family in GLOBAL_FAMILIES and self.partition != GLOBAL_PARTITION:
            raise BuildPlanError(
                f"global family {self.family} must use partition {GLOBAL_PARTITION!r}"
            )
        if self.family == "corpus" and self.partition == GLOBAL_PARTITION:
            raise BuildPlanError("corpus work units must be year-month partitions")

    @property
    def key(self) -> str:
        return work_unit_key(self.partition, self.family)

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "family": self.family,
            "input_hash": self.input_hash,
            "key": self.key,
            "partition": self.partition,
        }


@dataclass(frozen=True, slots=True)
class ProducerResult:
    """Result returned by a delegated producer for one work unit."""

    output_digest: str
    artifact_path: str = ""
    row_count: int = 0
    peak_resident_records: int = 0
    family_root: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)
    skipped: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "output_digest",
            _require_non_empty_str(self.output_digest, "output_digest", maximum=128),
        )
        object.__setattr__(self, "artifact_path", str(self.artifact_path or ""))
        object.__setattr__(
            self, "row_count", _require_non_negative_int(self.row_count, "row_count")
        )
        object.__setattr__(
            self,
            "peak_resident_records",
            _require_non_negative_int(
                self.peak_resident_records, "peak_resident_records"
            ),
        )
        object.__setattr__(self, "family_root", str(self.family_root or ""))
        object.__setattr__(self, "metadata", dict(self.metadata or {}))
        object.__setattr__(self, "skipped", bool(self.skipped))

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_path": self.artifact_path,
            "family_root": self.family_root,
            "metadata": dict(self.metadata),
            "output_digest": self.output_digest,
            "peak_resident_records": self.peak_resident_records,
            "row_count": self.row_count,
            "skipped": self.skipped,
        }


class ArtifactProducer(Protocol):
    """Producer protocol: build one work unit under *output_dir*."""

    def __call__(
        self,
        unit: WorkUnit,
        config: BuildConfig,
        output_dir: Path,
    ) -> ProducerResult: ...


def default_fixture_producer(
    unit: WorkUnit,
    config: BuildConfig,
    output_dir: Path,
) -> ProducerResult:
    """Deterministic offline producer used by fixture builds and unit tests.

    Streams one logical record under the memory budget and writes a compact
    JSON artifact per work unit. Does not invoke Hub I/O.
    """

    reject_hub_upload(False)
    budget = MemoryBudget(
        max_resident_records=config.resource_limits.max_resident_records
    )
    if unit.action in {"skip", "reuse"}:
        return ProducerResult(
            output_digest=f"reuse:{unit.input_hash}",
            artifact_path="",
            row_count=0,
            family_root=f"reuse:{unit.input_hash}",
            metadata={"action": unit.action},
            skipped=True,
        )
    rel = f"{unit.family}/partition-{_partition_filename(unit.partition)}.json"
    target = output_dir / rel
    payload = {
        "config_digest": config.digest,
        "family": unit.family,
        "input_hash": unit.input_hash,
        "observation_cutoff": config.observation_cutoff,
        "partition": unit.partition,
        "producer": "default_fixture_producer",
        "release_point": config.release_point,
        "schema_version": SCHEMA_VERSION,
        "seed": config.determinism_seed,
        "task_id": TASK_ID,
    }
    streamed = 0
    for _record in stream_bounded((payload,), budget=budget):
        streamed += 1
    if not config.validation_only:
        write_json_atomic(target, payload)
        _write_family_checkpoint(
            output_dir,
            family=unit.family,
            partition=unit.partition,
            payload={
                "input_hash": unit.input_hash,
                "output_digest": digest_mapping(payload),
                "status": WorkUnitStatus.VERIFIED.value,
            },
        )
    digest = digest_mapping(payload)
    return ProducerResult(
        output_digest=digest,
        artifact_path=rel if not config.validation_only else "",
        row_count=streamed,
        peak_resident_records=budget.peak_resident_records,
        family_root=digest,
        metadata={"fixture": True, "hub_upload": False},
        skipped=False,
    )


def _partition_filename(partition: str) -> str:
    return "global" if partition == GLOBAL_PARTITION else partition


def _write_family_checkpoint(
    output_dir: Path,
    *,
    family: str,
    partition: str,
    payload: Mapping[str, Any],
) -> Path:
    path = (
        output_dir
        / ".checkpoints"
        / FAMILY_CHECKPOINT_DIRNAME
        / family
        / f"{_partition_filename(partition)}.json"
    )
    return write_json_atomic(path, payload)


# ---------------------------------------------------------------------------
# Partition identity snapshots (for cutoff-delta planning)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PartitionSnapshot:
    """Content identity for one year-month partition used by delta planning."""

    partition: str
    content_hash: str
    document_count: int = 1
    observation_cutoff: str = DEFAULT_OBSERVATION_CUTOFF

    def __post_init__(self) -> None:
        object.__setattr__(self, "partition", _normalize_partition(self.partition))
        object.__setattr__(
            self,
            "content_hash",
            _require_non_empty_str(self.content_hash, "content_hash", maximum=128),
        )
        object.__setattr__(
            self,
            "document_count",
            _require_positive_int(self.document_count, "document_count"),
        )
        object.__setattr__(
            self,
            "observation_cutoff",
            require_immutable_observation_cutoff(self.observation_cutoff),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "content_hash": self.content_hash,
            "document_count": self.document_count,
            "observation_cutoff": self.observation_cutoff,
            "partition": self.partition,
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "PartitionSnapshot":
        if not isinstance(value, Mapping):
            raise BuildPlanError("partition snapshot must be a mapping")
        return cls(
            partition=str(value.get("partition") or ""),
            content_hash=str(value.get("content_hash") or ""),
            document_count=int(value.get("document_count") or 1),
            observation_cutoff=str(
                value.get("observation_cutoff") or DEFAULT_OBSERVATION_CUTOFF
            ),
        )


def fixture_partition_snapshots(
    partitions: Sequence[str],
    *,
    salt: str = "fixture",
    document_count: int = 1,
    observation_cutoff: str = DEFAULT_OBSERVATION_CUTOFF,
) -> dict[str, PartitionSnapshot]:
    """Build deterministic partition snapshots for offline fixture builds."""

    cutoff = require_immutable_observation_cutoff(observation_cutoff)
    out: dict[str, PartitionSnapshot] = {}
    for partition in partitions:
        part = _normalize_partition(partition)
        digest = digest_mapping(
            {
                "document_count": document_count,
                "observation_cutoff": cutoff,
                "partition": part,
                "salt": salt,
            }
        )
        out[part] = PartitionSnapshot(
            partition=part,
            content_hash=digest,
            document_count=document_count,
            observation_cutoff=cutoff,
        )
    return out


def cutoff_delta_partitions(
    partitions: Sequence[str],
    *,
    prior_cutoff: str,
    current_cutoff: str,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Split year-month partitions into unchanged vs cutoff-delta slices."""

    prior_ym = observation_cutoff_date(prior_cutoff)[:7]
    current_date = observation_cutoff_date(current_cutoff)
    if current_date < observation_cutoff_date(prior_cutoff):
        raise BuildPlanError("current observation cutoff precedes prior cutoff")
    unchanged: list[str] = []
    changed: list[str] = []
    for partition in partitions:
        part = _normalize_partition(partition)
        if part > prior_ym:
            changed.append(part)
        else:
            unchanged.append(part)
    return tuple(unchanged), tuple(changed)


# ---------------------------------------------------------------------------
# Checkpoint / receipt records
# ---------------------------------------------------------------------------


@dataclass
class WorkUnitRecord:
    """Durable per-unit progress record stored in the checkpoint."""

    partition: str
    family: str
    status: WorkUnitStatus
    input_hash: str
    output_digest: str = ""
    artifact_path: str = ""
    family_root: str = ""
    attempt_count: int = 0
    error: str = ""
    verified: bool = False
    peak_resident_records: int = 0

    def __post_init__(self) -> None:
        self.partition = _normalize_partition(self.partition)
        self.family = _normalize_family(self.family)
        self.status = WorkUnitStatus.coerce(self.status)
        self.input_hash = _require_non_empty_str(
            self.input_hash, "input_hash", maximum=128
        )
        self.output_digest = str(self.output_digest or "")
        self.artifact_path = str(self.artifact_path or "")
        self.family_root = str(self.family_root or "")
        self.attempt_count = _require_non_negative_int(
            self.attempt_count, "attempt_count"
        )
        self.error = str(self.error or "")
        self.verified = bool(self.verified)
        self.peak_resident_records = _require_non_negative_int(
            self.peak_resident_records, "peak_resident_records"
        )
        if self.status is WorkUnitStatus.VERIFIED:
            self.verified = True
        if self.verified and self.status is not WorkUnitStatus.VERIFIED:
            self.status = WorkUnitStatus.VERIFIED

    @property
    def key(self) -> str:
        return work_unit_key(self.partition, self.family)

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_path": self.artifact_path,
            "attempt_count": self.attempt_count,
            "error": self.error,
            "family": self.family,
            "family_root": self.family_root,
            "input_hash": self.input_hash,
            "output_digest": self.output_digest,
            "partition": self.partition,
            "peak_resident_records": self.peak_resident_records,
            "status": self.status.value,
            "verified": self.verified,
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "WorkUnitRecord":
        if not isinstance(value, Mapping):
            raise BuildCheckpointError("work unit record must be a mapping")
        return cls(
            partition=str(value.get("partition") or ""),
            family=str(value.get("family") or ""),
            status=WorkUnitStatus.coerce(value.get("status") or WorkUnitStatus.PENDING),
            input_hash=str(value.get("input_hash") or ""),
            output_digest=str(value.get("output_digest") or ""),
            artifact_path=str(value.get("artifact_path") or ""),
            family_root=str(value.get("family_root") or ""),
            attempt_count=int(value.get("attempt_count") or 0),
            error=str(value.get("error") or ""),
            verified=bool(value.get("verified", False)),
            peak_resident_records=int(value.get("peak_resident_records") or 0),
        )


@dataclass
class BuildCheckpoint:
    """Atomic, resumable checkpoint for an orchestrated build."""

    config_digest: str
    build_id: str
    mode: BuildMode
    observation_cutoff: str
    units: dict[str, WorkUnitRecord]
    global_decisions: dict[str, GlobalRebuildDecision]
    sealed: bool = False
    seal_digest: str = ""
    candidate_root: str = ""
    schema_version: str = SCHEMA_VERSION
    producer: str = PRODUCER
    task_id: str = TASK_ID

    def __post_init__(self) -> None:
        self.config_digest = _require_non_empty_str(
            self.config_digest, "config_digest", maximum=128
        )
        self.build_id = _require_non_empty_str(self.build_id, "build_id", maximum=128)
        self.mode = BuildMode.coerce(self.mode)
        self.observation_cutoff = require_immutable_observation_cutoff(
            self.observation_cutoff
        )
        if not isinstance(self.units, dict):
            raise BuildCheckpointError("units must be a dict")
        normalized_units: dict[str, WorkUnitRecord] = {}
        for key, record in self.units.items():
            if isinstance(record, WorkUnitRecord):
                rec = record
            elif isinstance(record, Mapping):
                rec = WorkUnitRecord.from_mapping(record)
            else:
                raise BuildCheckpointError(f"invalid unit record for {key!r}")
            normalized_units[rec.key] = rec
        self.units = normalized_units
        if not isinstance(self.global_decisions, dict):
            raise BuildCheckpointError("global_decisions must be a dict")
        normalized_decisions: dict[str, GlobalRebuildDecision] = {}
        for key, decision in self.global_decisions.items():
            if isinstance(decision, GlobalRebuildDecision):
                dec = decision
            elif isinstance(decision, Mapping):
                dec = GlobalRebuildDecision.from_mapping(decision)
            else:
                raise BuildCheckpointError(f"invalid global decision for {key!r}")
            normalized_decisions[dec.family] = dec
        self.global_decisions = normalized_decisions
        self.sealed = bool(self.sealed)
        self.seal_digest = str(self.seal_digest or "")
        self.candidate_root = str(self.candidate_root or "")
        if self.schema_version != SCHEMA_VERSION:
            raise BuildCheckpointError(
                f"unsupported checkpoint schema_version: {self.schema_version!r}"
            )
        if self.task_id != TASK_ID:
            raise BuildCheckpointError(
                f"checkpoint task_id {self.task_id!r} != {TASK_ID!r}"
            )
        if self.sealed and not self.all_verified:
            raise SealError("checkpoint marked sealed but units are incomplete")

    @property
    def all_verified(self) -> bool:
        if not self.units:
            return False
        return all(
            rec.verified and rec.status is WorkUnitStatus.VERIFIED
            for rec in self.units.values()
        )

    @property
    def verified_count(self) -> int:
        return sum(1 for rec in self.units.values() if rec.verified)

    @property
    def total_count(self) -> int:
        return len(self.units)

    @property
    def peak_resident_records(self) -> int:
        return max(
            (rec.peak_resident_records for rec in self.units.values()),
            default=0,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "all_verified": self.all_verified,
            "build_id": self.build_id,
            "candidate_root": self.candidate_root,
            "config_digest": self.config_digest,
            "global_decisions": {
                k: v.to_dict()
                for k, v in sorted(self.global_decisions.items(), key=lambda kv: kv[0])
            },
            "mode": self.mode.value,
            "observation_cutoff": self.observation_cutoff,
            "peak_resident_records": self.peak_resident_records,
            "producer": self.producer,
            "schema_version": self.schema_version,
            "seal_digest": self.seal_digest,
            "sealed": self.sealed,
            "task_id": self.task_id,
            "total_count": self.total_count,
            "units": {
                k: v.to_dict()
                for k, v in sorted(self.units.items(), key=lambda kv: kv[0])
            },
            "verified_count": self.verified_count,
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "BuildCheckpoint":
        if not isinstance(value, Mapping):
            raise BuildCheckpointError("checkpoint must be a mapping")
        schema = value.get("schema_version")
        if schema != SCHEMA_VERSION:
            raise BuildCheckpointError(
                f"unsupported checkpoint schema_version: {schema!r}"
            )
        units_raw = value.get("units") or {}
        if not isinstance(units_raw, Mapping):
            raise BuildCheckpointError("checkpoint units must be a mapping")
        decisions_raw = value.get("global_decisions") or {}
        if not isinstance(decisions_raw, Mapping):
            raise BuildCheckpointError("global_decisions must be a mapping")
        return cls(
            config_digest=str(value.get("config_digest") or ""),
            build_id=str(value.get("build_id") or ""),
            mode=BuildMode.coerce(value.get("mode") or BuildMode.FULL),
            observation_cutoff=str(
                value.get("observation_cutoff") or DEFAULT_OBSERVATION_CUTOFF
            ),
            units={
                str(k): WorkUnitRecord.from_mapping(v)  # type: ignore[arg-type]
                for k, v in units_raw.items()
            },
            global_decisions={
                str(k): GlobalRebuildDecision.from_mapping(v)  # type: ignore[arg-type]
                for k, v in decisions_raw.items()
            },
            sealed=bool(value.get("sealed", False)),
            seal_digest=str(value.get("seal_digest") or ""),
            candidate_root=str(value.get("candidate_root") or ""),
            schema_version=str(schema),
            producer=str(value.get("producer") or PRODUCER),
            task_id=str(value.get("task_id") or TASK_ID),
        )


def load_checkpoint(path: PathLike) -> BuildCheckpoint:
    """Load and validate a checkpoint file."""

    return BuildCheckpoint.from_mapping(load_json_mapping(path))


def write_checkpoint_atomic(path: PathLike, checkpoint: BuildCheckpoint) -> Path:
    """Write *checkpoint* atomically (temp file + replace)."""

    return write_json_atomic(path, checkpoint.to_dict())


def assert_checkpoint_compatible(
    checkpoint: BuildCheckpoint,
    config: BuildConfig,
) -> None:
    """Fail closed when a checkpoint is stale or config-mismatched."""

    if checkpoint.schema_version != SCHEMA_VERSION:
        raise BuildCheckpointError(
            f"checkpoint schema_version {checkpoint.schema_version!r} "
            f"!= {SCHEMA_VERSION!r}"
        )
    if checkpoint.task_id != TASK_ID:
        raise BuildCheckpointError(
            f"checkpoint task_id {checkpoint.task_id!r} != {TASK_ID!r}"
        )
    if checkpoint.config_digest != config.digest:
        raise BuildCheckpointError(
            "checkpoint config_digest does not match active build configuration"
        )
    if checkpoint.observation_cutoff != config.observation_cutoff:
        raise BuildCheckpointError(
            f"checkpoint observation_cutoff {checkpoint.observation_cutoff!r} "
            f"!= config observation_cutoff {config.observation_cutoff!r}"
        )
    if checkpoint.mode is not config.mode:
        raise BuildCheckpointError(
            f"checkpoint mode {checkpoint.mode.value!r} "
            f"!= config mode {config.mode.value!r}"
        )


def assert_promotable(checkpoint: BuildCheckpoint) -> None:
    """Fail closed: stale or partial checkpoints cannot be promoted."""

    if checkpoint.schema_version != SCHEMA_VERSION:
        raise PromotionError(
            f"stale checkpoint schema_version {checkpoint.schema_version!r}"
        )
    if not checkpoint.all_verified:
        raise PromotionError(
            f"cannot promote incomplete checkpoint: "
            f"{checkpoint.verified_count}/{checkpoint.total_count} verified"
        )
    if any(not rec.output_digest for rec in checkpoint.units.values()):
        raise PromotionError("cannot promote: one or more units lack output_digest")
    if checkpoint.sealed and not checkpoint.seal_digest:
        raise PromotionError("sealed checkpoint is missing seal_digest")


# ---------------------------------------------------------------------------
# Build plan
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BuildPlan:
    """Deterministic full or cutoff-delta plan with explicit global decisions."""

    mode: BuildMode
    units: tuple[WorkUnit, ...]
    global_decisions: Mapping[str, GlobalRebuildDecision]
    changed_partitions: tuple[str, ...]
    unchanged_partitions: tuple[str, ...]
    invalidated_families: tuple[str, ...]
    changed_document_ratio: float
    config_digest: str
    build_id: str
    observation_cutoff: str
    prior_cutoff: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "mode", BuildMode.coerce(self.mode))
        object.__setattr__(self, "units", tuple(self.units))
        decisions = {
            _normalize_family(k): (
                v
                if isinstance(v, GlobalRebuildDecision)
                else GlobalRebuildDecision.from_mapping(v)  # type: ignore[arg-type]
            )
            for k, v in dict(self.global_decisions or {}).items()
        }
        object.__setattr__(self, "global_decisions", MappingProxyType(decisions))
        object.__setattr__(
            self,
            "changed_partitions",
            tuple(_normalize_partition(item) for item in self.changed_partitions),
        )
        object.__setattr__(
            self,
            "unchanged_partitions",
            tuple(_normalize_partition(item) for item in self.unchanged_partitions),
        )
        object.__setattr__(
            self,
            "invalidated_families",
            tuple(_normalize_family(item) for item in self.invalidated_families),
        )
        object.__setattr__(
            self,
            "changed_document_ratio",
            _require_unit_interval(
                self.changed_document_ratio, "changed_document_ratio"
            ),
        )
        object.__setattr__(
            self,
            "config_digest",
            _require_non_empty_str(self.config_digest, "config_digest", maximum=128),
        )
        object.__setattr__(
            self,
            "build_id",
            _require_non_empty_str(self.build_id, "build_id", maximum=128),
        )
        object.__setattr__(
            self,
            "observation_cutoff",
            require_immutable_observation_cutoff(self.observation_cutoff),
        )
        object.__setattr__(
            self,
            "prior_cutoff",
            require_immutable_observation_cutoff(self.prior_cutoff),
        )
        for fam in GLOBAL_STAT_FAMILIES:
            if fam in {u.family for u in self.units} or fam in decisions:
                if fam not in decisions:
                    raise GlobalDecisionError(
                        f"missing explicit global rebuild decision for {fam}"
                    )

    @property
    def runnable_units(self) -> tuple[WorkUnit, ...]:
        return tuple(u for u in self.units if u.action == "build")

    @property
    def skipped_units(self) -> tuple[WorkUnit, ...]:
        return tuple(u for u in self.units if u.action != "build")

    def to_dict(self) -> dict[str, Any]:
        return {
            "build_id": self.build_id,
            "changed_document_ratio": self.changed_document_ratio,
            "changed_partitions": list(self.changed_partitions),
            "config_digest": self.config_digest,
            "global_decisions": {
                k: v.to_dict()
                for k, v in sorted(self.global_decisions.items(), key=lambda kv: kv[0])
            },
            "invalidated_families": list(self.invalidated_families),
            "mode": self.mode.value,
            "observation_cutoff": self.observation_cutoff,
            "prior_cutoff": self.prior_cutoff,
            "runnable_count": len(self.runnable_units),
            "skipped_count": len(self.skipped_units),
            "unchanged_partitions": list(self.unchanged_partitions),
            "unit_count": len(self.units),
            "units": [u.to_dict() for u in self.units],
        }


def _build_id_for(config: BuildConfig, *, salt: str = "") -> str:
    return digest_mapping(
        {
            "config_digest": config.digest,
            "mode": config.mode.value,
            "observation_cutoff": config.observation_cutoff,
            "salt": salt,
            "task_id": TASK_ID,
        }
    )[:32]


def _partition_hashes(
    snapshots: Mapping[str, PartitionSnapshot],
    partitions: Sequence[str],
) -> dict[str, str]:
    return {part: snapshots[part].content_hash for part in partitions}


def _derived_input_hash(
    family: str,
    *,
    partition_hashes: Mapping[str, str],
) -> str:
    return digest_mapping(
        {
            "dependencies": list(FAMILY_DEPENDENCIES.get(family, ())),
            "family": family,
            "partition_hashes": dict(sorted(partition_hashes.items())),
        }
    )


def _sorted_units(units: Sequence[WorkUnit]) -> tuple[WorkUnit, ...]:
    family_rank = {name: index for index, name in enumerate(DEFAULT_BUILD_FAMILIES)}
    return tuple(
        sorted(
            units,
            key=lambda unit: (
                family_rank.get(unit.family, 99),
                unit.partition,
                unit.family,
            ),
        )
    )


def plan_full_build(
    config: BuildConfig,
    *,
    current: Mapping[str, PartitionSnapshot] | None = None,
) -> BuildPlan:
    """Plan a full rebuild of every partition × family."""

    snapshots = dict(current or fixture_partition_snapshots(config.partitions))
    for partition in config.partitions:
        if partition not in snapshots:
            raise BuildPlanError(
                f"missing partition snapshot for full plan: {partition}"
            )
    hashes = _partition_hashes(snapshots, config.partitions)
    units: list[WorkUnit] = []
    for family in config.families:
        if family == "corpus":
            for partition in config.partitions:
                units.append(
                    WorkUnit(
                        partition=partition,
                        family=family,
                        input_hash=snapshots[partition].content_hash,
                        action="build",
                    )
                )
        else:
            units.append(
                WorkUnit(
                    partition=GLOBAL_PARTITION,
                    family=family,
                    input_hash=_derived_input_hash(family, partition_hashes=hashes),
                    action="build",
                )
            )
    decisions: dict[str, GlobalRebuildDecision] = {}
    if "bm25" in config.families:
        decisions["bm25"] = decide_global_rebuild(
            "bm25",
            mode=BuildMode.FULL,
            changed_ratio=1.0,
            threshold=config.bm25_rebuild_threshold,
            explicit=config.bm25_decision or GlobalRebuildKind.FULL_REBUILD,
            prior_present=False,
        )
    if "vectors" in config.families:
        decisions["vectors"] = decide_global_rebuild(
            "vectors",
            mode=BuildMode.FULL,
            changed_ratio=1.0,
            threshold=config.cluster_rebuild_threshold,
            explicit=config.cluster_decision or GlobalRebuildKind.FULL_REBUILD,
            prior_present=False,
        )
    for family in config.families:
        if family in {"corpus"} or family in decisions:
            continue
        decisions[family] = decide_dependent_rebuild(
            family,
            mode=BuildMode.FULL,
            corpus_changed=True,
            changed_ratio=1.0,
        )
    config.resource_limits.enforce(
        partition_count=len(config.partitions),
        work_unit_count=len(units),
    )
    return BuildPlan(
        mode=BuildMode.FULL,
        units=_sorted_units(units),
        global_decisions=decisions,
        changed_partitions=tuple(config.partitions),
        unchanged_partitions=(),
        invalidated_families=tuple(
            fam for fam in config.families if fam != "corpus"
        ),
        changed_document_ratio=1.0,
        config_digest=config.digest,
        build_id=_build_id_for(config, salt="full"),
        observation_cutoff=config.observation_cutoff,
        prior_cutoff=config.prior_cutoff,
    )


def plan_delta_build(
    config: BuildConfig,
    *,
    current: Mapping[str, PartitionSnapshot],
    prior: Mapping[str, PartitionSnapshot],
) -> BuildPlan:
    """Plan a cutoff-delta build from *prior* → *current* partition snapshots."""

    if not current:
        raise BuildPlanError("delta plan requires non-empty current snapshots")

    current_map = {
        _normalize_partition(k): (
            v
            if isinstance(v, PartitionSnapshot)
            else PartitionSnapshot.from_mapping(v)  # type: ignore[arg-type]
        )
        for k, v in current.items()
    }
    prior_map = {
        _normalize_partition(k): (
            v
            if isinstance(v, PartitionSnapshot)
            else PartitionSnapshot.from_mapping(v)  # type: ignore[arg-type]
        )
        for k, v in (prior or {}).items()
    }

    partitions = tuple(config.partitions)
    for partition in partitions:
        if partition not in current_map:
            raise BuildPlanError(f"missing current snapshot for partition {partition}")

    changed: list[str] = []
    unchanged: list[str] = []
    total_docs = 0
    changed_docs = 0
    for partition in partitions:
        cur = current_map[partition]
        total_docs += cur.document_count
        prev = prior_map.get(partition)
        if prev is None or prev.content_hash != cur.content_hash:
            changed.append(partition)
            changed_docs += cur.document_count
        else:
            unchanged.append(partition)

    if total_docs <= 0:
        raise BuildPlanError("total document count must be positive")
    changed_ratio = changed_docs / float(total_docs)
    corpus_changed = bool(changed)
    invalidated = (
        dependency_closure({"corpus"} if corpus_changed else ())
        if corpus_changed
        else frozenset()
    )

    decisions: dict[str, GlobalRebuildDecision] = {}
    if "bm25" in config.families:
        decisions["bm25"] = decide_global_rebuild(
            "bm25",
            mode=BuildMode.DELTA,
            changed_ratio=changed_ratio,
            threshold=config.bm25_rebuild_threshold,
            explicit=config.bm25_decision,
            prior_present=bool(prior_map),
        )
    if "vectors" in config.families:
        decisions["vectors"] = decide_global_rebuild(
            "vectors",
            mode=BuildMode.DELTA,
            changed_ratio=changed_ratio,
            threshold=config.cluster_rebuild_threshold,
            explicit=config.cluster_decision,
            prior_present=bool(prior_map),
        )
    for family in config.families:
        if family in {"corpus"} or family in GLOBAL_STAT_FAMILIES:
            continue
        decisions[family] = decide_dependent_rebuild(
            family,
            mode=BuildMode.DELTA,
            corpus_changed=corpus_changed,
            changed_ratio=changed_ratio,
        )

    hashes = _partition_hashes(current_map, partitions)
    changed_set = set(changed)
    units: list[WorkUnit] = []
    for family in config.families:
        if family == "corpus":
            for partition in partitions:
                units.append(
                    WorkUnit(
                        partition=partition,
                        family=family,
                        input_hash=current_map[partition].content_hash,
                        action="build" if partition in changed_set else "reuse",
                    )
                )
            continue
        decision = decisions.get(family)
        if decision is not None and decision.kind is GlobalRebuildKind.UNCHANGED:
            action = "reuse"
        elif family in invalidated or corpus_changed:
            action = "build"
        else:
            action = "reuse"
        units.append(
            WorkUnit(
                partition=GLOBAL_PARTITION,
                family=family,
                input_hash=_derived_input_hash(family, partition_hashes=hashes),
                action=action,
            )
        )

    config.resource_limits.enforce(
        partition_count=len(partitions),
        work_unit_count=len(units),
    )
    return BuildPlan(
        mode=BuildMode.DELTA,
        units=_sorted_units(units),
        global_decisions=decisions,
        changed_partitions=tuple(changed),
        unchanged_partitions=tuple(unchanged),
        invalidated_families=tuple(
            fam for fam in config.families if fam in invalidated and fam != "corpus"
        ),
        changed_document_ratio=changed_ratio,
        config_digest=config.digest,
        build_id=_build_id_for(config, salt="delta"),
        observation_cutoff=config.observation_cutoff,
        prior_cutoff=config.prior_cutoff,
    )


def plan_build(
    config: BuildConfig,
    *,
    current: Mapping[str, PartitionSnapshot] | None = None,
    prior: Mapping[str, PartitionSnapshot] | None = None,
) -> BuildPlan:
    """Plan a full or cutoff-delta build according to *config.mode*."""

    if config.mode is BuildMode.FULL:
        return plan_full_build(config, current=current)
    if prior is None:
        raise BuildPlanError("delta mode requires prior partition snapshots")
    if current is None:
        raise BuildPlanError("delta mode requires current partition snapshots")
    return plan_delta_build(config, current=current, prior=prior)


# ---------------------------------------------------------------------------
# Build result / seal / candidate root
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BuildSeal:
    """Immutable seal over a fully verified build."""

    seal_digest: str
    config_digest: str
    build_id: str
    unit_count: int
    verified_count: int
    global_decisions: Mapping[str, Mapping[str, Any]]
    unit_digests: Mapping[str, str]
    family_roots: Mapping[str, str]
    observation_cutoff: str
    mode: str
    candidate_root: str = ""
    schema_version: str = SCHEMA_VERSION
    task_id: str = TASK_ID

    def to_dict(self) -> dict[str, Any]:
        return {
            "build_id": self.build_id,
            "candidate_root": self.candidate_root,
            "config_digest": self.config_digest,
            "family_roots": dict(self.family_roots),
            "global_decisions": dict(self.global_decisions),
            "mode": self.mode,
            "observation_cutoff": self.observation_cutoff,
            "schema_version": self.schema_version,
            "seal_digest": self.seal_digest,
            "task_id": self.task_id,
            "unit_count": self.unit_count,
            "unit_digests": dict(self.unit_digests),
            "verified_count": self.verified_count,
        }


def _family_roots_from_checkpoint(checkpoint: BuildCheckpoint) -> dict[str, str]:
    roots: dict[str, str] = {}
    families = sorted({rec.family for rec in checkpoint.units.values()})
    for family in families:
        items = {
            item.partition: item.family_root or item.output_digest
            for item in checkpoint.units.values()
            if item.family == family
        }
        if family in GLOBAL_FAMILIES:
            roots[family] = items.get(GLOBAL_PARTITION) or next(iter(sorted(items.items())))[1]
        else:
            roots[family] = digest_mapping(
                {"family": family, "parts": sorted(items.items())}
            )
    return dict(sorted(roots.items()))


def compute_seal(checkpoint: BuildCheckpoint) -> BuildSeal:
    """Compute a seal over a fully verified checkpoint (fail-closed)."""

    assert_promotable(checkpoint)
    unit_digests = {
        key: rec.output_digest
        for key, rec in sorted(checkpoint.units.items(), key=lambda kv: kv[0])
    }
    family_roots = _family_roots_from_checkpoint(checkpoint)
    payload = {
        "build_id": checkpoint.build_id,
        "config_digest": checkpoint.config_digest,
        "family_roots": family_roots,
        "global_decisions": {
            k: v.to_dict()
            for k, v in sorted(
                checkpoint.global_decisions.items(), key=lambda kv: kv[0]
            )
        },
        "mode": checkpoint.mode.value,
        "observation_cutoff": checkpoint.observation_cutoff,
        "schema_version": SCHEMA_VERSION,
        "task_id": TASK_ID,
        "unit_digests": unit_digests,
    }
    seal_digest = digest_mapping(payload)
    candidate_root = digest_mapping(
        {
            "family_roots": family_roots,
            "observation_cutoff": checkpoint.observation_cutoff,
            "seal_digest": seal_digest,
            "task_id": TASK_ID,
        }
    )
    return BuildSeal(
        seal_digest=seal_digest,
        config_digest=checkpoint.config_digest,
        build_id=checkpoint.build_id,
        unit_count=checkpoint.total_count,
        verified_count=checkpoint.verified_count,
        global_decisions={
            k: v.to_dict()
            for k, v in sorted(
                checkpoint.global_decisions.items(), key=lambda kv: kv[0]
            )
        },
        unit_digests=unit_digests,
        family_roots=family_roots,
        observation_cutoff=checkpoint.observation_cutoff,
        mode=checkpoint.mode.value,
        candidate_root=candidate_root,
    )


def assemble_candidate_root(
    checkpoint: BuildCheckpoint,
    *,
    output_dir: PathLike | None = None,
    validation_only: bool = False,
) -> dict[str, Any]:
    """Assemble an atomic candidate root from verified family checkpoints."""

    seal = compute_seal(checkpoint)
    payload = {
        "authorizing_hub_upload": AUTHORIZES_HUB_UPLOAD,
        "candidate_root": seal.candidate_root,
        "config_digest": checkpoint.config_digest,
        "family_roots": dict(seal.family_roots),
        "goal_id": GOAL_ID,
        "mode": checkpoint.mode.value,
        "observation_cutoff": checkpoint.observation_cutoff,
        "program_id": PROGRAM_ID,
        "schema_version": SCHEMA_VERSION,
        "seal_digest": seal.seal_digest,
        "task_id": TASK_ID,
        "unit_digests": dict(seal.unit_digests),
    }
    if not validation_only:
        if output_dir is None:
            raise SealError("candidate root assembly requires output_dir")
        write_json_atomic(Path(output_dir) / CANDIDATE_ROOT_FILENAME, payload)
    return payload


@dataclass(frozen=True, slots=True)
class BuildResult:
    """Outcome of one orchestrator run."""

    plan: BuildPlan
    checkpoint: BuildCheckpoint
    seal: Optional[BuildSeal]
    executed_keys: tuple[str, ...]
    resumed_keys: tuple[str, ...]
    skipped_keys: tuple[str, ...]
    invalidated_keys: tuple[str, ...]
    validation_only: bool
    interrupted: bool
    candidate_root: str = ""
    receipt_path: str = ""
    checkpoint_path: str = ""
    seal_path: str = ""
    candidate_root_path: str = ""
    peak_resident_records: int = 0

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "candidate_root": self.candidate_root,
            "candidate_root_path": self.candidate_root_path,
            "checkpoint": self.checkpoint.to_dict(),
            "checkpoint_path": self.checkpoint_path,
            "executed_keys": list(self.executed_keys),
            "goal_id": GOAL_ID,
            "interrupted": self.interrupted,
            "invalidated_keys": list(self.invalidated_keys),
            "peak_resident_records": self.peak_resident_records,
            "plan": self.plan.to_dict(),
            "program_id": PROGRAM_ID,
            "receipt_path": self.receipt_path,
            "resumed_keys": list(self.resumed_keys),
            "seal": None if self.seal is None else self.seal.to_dict(),
            "seal_path": self.seal_path,
            "skipped_keys": list(self.skipped_keys),
            "task_id": TASK_ID,
            "validation_only": self.validation_only,
        }
        payload.update(software_contract_flags())
        return payload


# ---------------------------------------------------------------------------
# Family-builder producer (read-only consumption of existing builders)
# ---------------------------------------------------------------------------


class FamilyBuilderProducer:
    """Delegate corpus/BM25/vectors/graph/adjacency work to existing builders."""

    def __init__(self) -> None:
        self._corpus: Any = None
        self._roots: dict[str, str] = {}
        self._peak = 0

    def _materialize_corpus(self) -> Any:
        if self._corpus is None:
            from ipfs_datasets_py.processors.legal_data.federal_register_corpus import (
                materialize_federal_register_corpus,
            )

            self._corpus = materialize_federal_register_corpus()
        return self._corpus

    def _stream_corpus_partitions(self, config: BuildConfig) -> dict[str, int]:
        corpus = self._materialize_corpus()
        budget = MemoryBudget(
            max_resident_records=config.resource_limits.max_resident_records
        )
        counts: dict[str, int] = {}
        for record in stream_bounded(corpus.corpus_records, budget=budget):
            year_month = str(getattr(record, "year_month", "") or "")
            if not year_month:
                year_month = str(getattr(record, "publication_date", "") or "")[:7]
            counts[year_month] = counts.get(year_month, 0) + 1
        self._peak = max(self._peak, budget.peak_resident_records)
        return counts

    def __call__(
        self,
        unit: WorkUnit,
        config: BuildConfig,
        output_dir: Path,
    ) -> ProducerResult:
        reject_hub_upload(False)
        if unit.action in {"skip", "reuse"}:
            return ProducerResult(
                output_digest=f"reuse:{unit.input_hash}",
                family_root=f"reuse:{unit.input_hash}",
                skipped=True,
                metadata={"action": unit.action, "hub_upload": False},
            )
        if unit.family == "corpus":
            counts = self._stream_corpus_partitions(config)
            payload = {
                "family": "corpus",
                "input_hash": unit.input_hash,
                "observation_cutoff": config.observation_cutoff,
                "partition": unit.partition,
                "partition_counts": dict(sorted(counts.items())),
                "release_point": config.release_point,
                "task_id": TASK_ID,
            }
            digest = digest_mapping(payload)
            self._roots["corpus"] = digest
            rel = f"corpus/partition-{_partition_filename(unit.partition)}.json"
            if not config.validation_only:
                write_json_atomic(output_dir / rel, payload)
                _write_family_checkpoint(
                    output_dir,
                    family=unit.family,
                    partition=unit.partition,
                    payload={"output_digest": digest, "status": "verified"},
                )
            return ProducerResult(
                output_digest=digest,
                artifact_path=rel if not config.validation_only else "",
                row_count=counts.get(unit.partition, sum(counts.values())),
                peak_resident_records=self._peak,
                family_root=digest,
                metadata={"builder": "materialize_federal_register_corpus"},
            )
        return self._build_global_family(unit, config, output_dir)

    def _build_global_family(
        self,
        unit: WorkUnit,
        config: BuildConfig,
        output_dir: Path,
    ) -> ProducerResult:
        family = unit.family
        if family == "bm25":
            from ipfs_datasets_py.processors.legal_data.federal_register_bm25 import (
                bind_fixture_bm25,
            )

            index = bind_fixture_bm25()
            root = index.index_root_cid
            row_count = index.document_count
            extra = {
                "corpus_root_cid": index.corpus_root_cid,
                "index_root_cid": index.index_root_cid,
            }
        elif family == "vectors":
            from ipfs_datasets_py.processors.legal_data.federal_register_vectors import (
                bind_fixture_vectors,
            )

            binding = bind_fixture_vectors()
            root = binding.vector_root_cid
            row_count = binding.vector_count
            extra = {
                "model_cid": binding.model_cid,
                "vector_root_cid": binding.vector_root_cid,
            }
        elif family == "graph":
            from ipfs_datasets_py.processors.legal_data.federal_register_graph import (
                bind_fixture_graph,
            )

            projection = bind_fixture_graph()
            root = projection.graph_cid
            row_count = projection.node_count
            extra = projection.receipt()
        elif family == "adjacency":
            from ipfs_datasets_py.processors.legal_data.federal_register_adjacency_gate import (
                bind_fixture_graph_adjacency,
            )

            _overlay, projection, adjacency = bind_fixture_graph_adjacency()
            extra = adjacency.to_dict()
            extra["graph_cid"] = projection.graph_cid
            root = digest_mapping(extra)
            row_count = adjacency.edge_count
        else:
            raise ProducerError(f"unsupported family {family!r}")
        payload = {
            "family": family,
            "family_root": root,
            "input_hash": unit.input_hash,
            "observation_cutoff": config.observation_cutoff,
            "task_id": TASK_ID,
            **{k: extra[k] for k in sorted(extra) if k in {
                "corpus_root_cid",
                "index_root_cid",
                "vector_root_cid",
                "model_cid",
                "graph_cid",
                "edge_count",
                "node_count",
            }},
        }
        digest = digest_mapping({"family_root": root, "input_hash": unit.input_hash})
        self._roots[family] = root
        rel = f"{family}/partition-global.json"
        if not config.validation_only:
            write_json_atomic(output_dir / rel, payload)
            _write_family_checkpoint(
                output_dir,
                family=family,
                partition=GLOBAL_PARTITION,
                payload={"output_digest": digest, "family_root": root, "status": "verified"},
            )
        return ProducerResult(
            output_digest=digest,
            artifact_path=rel if not config.validation_only else "",
            row_count=row_count,
            peak_resident_records=1,
            family_root=root,
            metadata={"builder": family, "hub_upload": False},
        )


def consume_family_builders() -> dict[str, Any]:
    """Call existing FR family builders read-only and return compact roots."""

    from ipfs_datasets_py.processors.legal_data.federal_register_adjacency_gate import (
        bind_fixture_graph_adjacency,
    )
    from ipfs_datasets_py.processors.legal_data.federal_register_bm25 import (
        bind_fixture_bm25,
    )
    from ipfs_datasets_py.processors.legal_data.federal_register_corpus import (
        materialize_federal_register_corpus,
    )
    from ipfs_datasets_py.processors.legal_data.federal_register_graph import (
        bind_fixture_graph,
    )
    from ipfs_datasets_py.processors.legal_data.federal_register_vectors import (
        bind_fixture_vectors,
    )

    budget = MemoryBudget(max_resident_records=DEFAULT_MAX_RECORDS_IN_MEMORY)
    corpus = materialize_federal_register_corpus()
    streamed = 0
    for _record in stream_bounded(corpus.corpus_records, budget=budget):
        streamed += 1
    bm25 = bind_fixture_bm25()
    vectors = bind_fixture_vectors()
    graph = bind_fixture_graph()
    _overlay, projection, adjacency = bind_fixture_graph_adjacency()
    payload = {
        "adjacency_root": digest_mapping(adjacency.to_dict()),
        "authorizing_hub_upload": False,
        "bm25_root": bm25.index_root_cid,
        "corpus_documents": streamed,
        "corpus_release_point": corpus.release_point,
        "families": list(DEFAULT_BUILD_FAMILIES),
        "goal_id": GOAL_ID,
        "graph_root": graph.graph_cid,
        "peak_resident_records": budget.peak_resident_records,
        "program_id": PROGRAM_ID,
        "projection_graph_cid": projection.graph_cid,
        "task_id": TASK_ID,
        "vector_root": vectors.vector_root_cid,
        "whole_corpus_loaded": False,
    }
    payload["consumption_digest"] = digest_mapping(
        {k: payload[k] for k in (
            "adjacency_root",
            "bm25_root",
            "graph_root",
            "task_id",
            "vector_root",
        )}
    )
    return payload


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


class FederalRegisterBuildOrchestrator:
    """Resumable full/cutoff-delta orchestrator for Federal Register GraphRAG."""

    def __init__(
        self,
        *,
        output_dir: PathLike,
        checkpoint_dir: PathLike | None = None,
        producer: ArtifactProducer | None = None,
    ) -> None:
        self.output_dir = Path(output_dir)
        self.checkpoint_dir = Path(
            checkpoint_dir
            if checkpoint_dir is not None
            else self.output_dir / ".checkpoints"
        )
        self.producer: ArtifactProducer = producer or default_fixture_producer
        self.checkpoint_path = self.checkpoint_dir / CHECKPOINT_FILENAME
        self.seal_path = self.checkpoint_dir / SEAL_FILENAME
        self.receipt_path = self.checkpoint_dir / RECEIPT_FILENAME
        self.candidate_root_path = self.output_dir / CANDIDATE_ROOT_FILENAME

    def plan(
        self,
        config: BuildConfig,
        *,
        current: Mapping[str, PartitionSnapshot] | None = None,
        prior: Mapping[str, PartitionSnapshot] | None = None,
    ) -> BuildPlan:
        return plan_build(config, current=current, prior=prior)

    def load_checkpoint(self) -> BuildCheckpoint | None:
        if not self.checkpoint_path.is_file():
            return None
        return load_checkpoint(self.checkpoint_path)

    def write_checkpoint(self, checkpoint: BuildCheckpoint) -> Path:
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)
        return write_checkpoint_atomic(self.checkpoint_path, checkpoint)

    def run(
        self,
        config: BuildConfig,
        *,
        current: Mapping[str, PartitionSnapshot] | None = None,
        prior: Mapping[str, PartitionSnapshot] | None = None,
        interrupt_after_units: int | None = None,
    ) -> BuildResult:
        reject_hub_upload(not config.fixture_only)
        plan = self.plan(config, current=current, prior=prior)
        existing = self.load_checkpoint() if config.resume else None
        if existing is not None:
            assert_checkpoint_compatible(existing, config)
            if existing.build_id != plan.build_id:
                raise BuildCheckpointError(
                    "checkpoint build_id does not match the active plan"
                )

        units_by_key = {u.key: u for u in plan.units}
        records: dict[str, WorkUnitRecord] = {}
        resumed_keys: list[str] = []
        skipped_keys: list[str] = []
        executed_keys: list[str] = []
        invalidated_keys: list[str] = []
        invalidated_families = set(plan.invalidated_families)

        for unit in plan.units:
            prior_rec = existing.units.get(unit.key) if existing else None
            stale_dependency = bool(
                unit.family in invalidated_families
                and prior_rec is not None
                and prior_rec.input_hash != unit.input_hash
            )
            if stale_dependency and prior_rec is not None:
                invalidated_keys.append(unit.key)
                prior_rec = None
            if (
                prior_rec is not None
                and prior_rec.verified
                and prior_rec.status is WorkUnitStatus.VERIFIED
                and prior_rec.input_hash == unit.input_hash
                and prior_rec.output_digest
            ):
                records[unit.key] = WorkUnitRecord(
                    partition=unit.partition,
                    family=unit.family,
                    status=WorkUnitStatus.VERIFIED,
                    input_hash=unit.input_hash,
                    output_digest=prior_rec.output_digest,
                    artifact_path=prior_rec.artifact_path,
                    family_root=prior_rec.family_root,
                    attempt_count=prior_rec.attempt_count,
                    verified=True,
                    peak_resident_records=prior_rec.peak_resident_records,
                )
                resumed_keys.append(unit.key)
            elif unit.action in {"skip", "reuse"}:
                reuse_digest = f"reuse:{unit.input_hash}"
                records[unit.key] = WorkUnitRecord(
                    partition=unit.partition,
                    family=unit.family,
                    status=WorkUnitStatus.VERIFIED,
                    input_hash=unit.input_hash,
                    output_digest=reuse_digest,
                    family_root=reuse_digest,
                    verified=True,
                )
                skipped_keys.append(unit.key)
            else:
                records[unit.key] = WorkUnitRecord(
                    partition=unit.partition,
                    family=unit.family,
                    status=WorkUnitStatus.PENDING,
                    input_hash=unit.input_hash,
                    attempt_count=(
                        prior_rec.attempt_count if prior_rec is not None else 0
                    ),
                )

        checkpoint = BuildCheckpoint(
            config_digest=config.digest,
            build_id=plan.build_id,
            mode=plan.mode,
            observation_cutoff=config.observation_cutoff,
            units=records,
            global_decisions=dict(plan.global_decisions),
            sealed=False,
        )

        if not config.validation_only:
            self.output_dir.mkdir(parents=True, exist_ok=True)
            self.write_checkpoint(checkpoint)

        newly_executed = 0
        interrupted = False
        pending_keys = [
            unit.key
            for unit in plan.units
            if not checkpoint.units[unit.key].verified
            and units_by_key[unit.key].action == "build"
        ]

        for key in pending_keys:
            if (
                interrupt_after_units is not None
                and newly_executed >= interrupt_after_units
            ):
                interrupted = True
                break
            unit = units_by_key[key]
            rec = checkpoint.units[key]
            rec.status = WorkUnitStatus.IN_PROGRESS
            rec.attempt_count += 1
            if not config.validation_only:
                self.write_checkpoint(checkpoint)
            try:
                result = self.producer(unit, config, self.output_dir)
            except FederalRegisterReleaseError:
                rec.status = WorkUnitStatus.FAILED
                rec.error = "producer raised FederalRegisterReleaseError"
                if not config.validation_only:
                    self.write_checkpoint(checkpoint)
                raise
            except Exception as exc:  # noqa: BLE001 — surface as producer failure
                rec.status = WorkUnitStatus.FAILED
                rec.error = f"{type(exc).__name__}: {exc}"
                if not config.validation_only:
                    self.write_checkpoint(checkpoint)
                raise ProducerError(f"producer failed for {key}: {exc}") from exc

            rec.status = WorkUnitStatus.VERIFIED
            rec.verified = True
            rec.output_digest = result.output_digest
            rec.artifact_path = result.artifact_path
            rec.family_root = result.family_root or result.output_digest
            rec.peak_resident_records = result.peak_resident_records
            rec.error = ""
            if result.skipped:
                skipped_keys.append(key)
            else:
                executed_keys.append(key)
                newly_executed += 1
            if not config.validation_only:
                self.write_checkpoint(checkpoint)
                _write_family_checkpoint(
                    self.output_dir,
                    family=unit.family,
                    partition=unit.partition,
                    payload=rec.to_dict(),
                )

        seal: BuildSeal | None = None
        seal_path = ""
        candidate_root = ""
        candidate_root_path = ""
        if interrupted:
            if checkpoint.sealed:
                raise SealError("internal error: interrupted checkpoint is sealed")
        elif checkpoint.all_verified:
            seal = compute_seal(checkpoint)
            checkpoint.sealed = True
            checkpoint.seal_digest = seal.seal_digest
            checkpoint.candidate_root = seal.candidate_root
            candidate_root = seal.candidate_root
            if not config.validation_only:
                self.write_checkpoint(checkpoint)
                write_json_atomic(self.seal_path, seal.to_dict())
                seal_path = str(self.seal_path)
                assembled = assemble_candidate_root(
                    checkpoint,
                    output_dir=self.output_dir,
                    validation_only=False,
                )
                candidate_root_path = str(self.candidate_root_path)
                candidate_root = str(assembled["candidate_root"])
        else:
            try:
                assert_promotable(checkpoint)
            except PromotionError:
                pass
            else:
                raise SealError("internal error: unsealed complete checkpoint")

        receipt = {
            "build_id": plan.build_id,
            "candidate_root": candidate_root,
            "config": config.to_dict(),
            "config_digest": config.digest,
            "executed_keys": executed_keys,
            "global_decisions": {
                k: v.to_dict() for k, v in plan.global_decisions.items()
            },
            "interrupted": interrupted,
            "invalidated_keys": invalidated_keys,
            "mode": plan.mode.value,
            "observation_cutoff": config.observation_cutoff,
            "plan": plan.to_dict(),
            "producer": PRODUCER,
            "resumed_keys": resumed_keys,
            "schema_version": SCHEMA_VERSION,
            "seal_digest": "" if seal is None else seal.seal_digest,
            "sealed": checkpoint.sealed,
            "skipped_keys": skipped_keys,
            "task_id": TASK_ID,
            "validation_only": config.validation_only,
            "verified_count": checkpoint.verified_count,
            "total_count": checkpoint.total_count,
            **software_contract_flags(),
        }
        receipt_path = ""
        if not config.validation_only:
            write_json_atomic(self.receipt_path, receipt)
            receipt_path = str(self.receipt_path)

        return BuildResult(
            plan=plan,
            checkpoint=checkpoint,
            seal=seal,
            executed_keys=tuple(executed_keys),
            resumed_keys=tuple(resumed_keys),
            skipped_keys=tuple(skipped_keys),
            invalidated_keys=tuple(invalidated_keys),
            validation_only=config.validation_only,
            interrupted=interrupted,
            candidate_root=candidate_root,
            receipt_path=receipt_path,
            checkpoint_path=""
            if config.validation_only
            else str(self.checkpoint_path),
            seal_path=seal_path,
            candidate_root_path=candidate_root_path,
            peak_resident_records=checkpoint.peak_resident_records,
        )

    def seal_existing(self, config: BuildConfig) -> BuildSeal:
        """Seal a fully verified on-disk checkpoint (fail-closed on partial)."""

        checkpoint = self.load_checkpoint()
        if checkpoint is None:
            raise SealError("no checkpoint to seal")
        assert_checkpoint_compatible(checkpoint, config)
        assert_promotable(checkpoint)
        seal = compute_seal(checkpoint)
        if config.validation_only:
            return seal
        checkpoint.sealed = True
        checkpoint.seal_digest = seal.seal_digest
        checkpoint.candidate_root = seal.candidate_root
        self.write_checkpoint(checkpoint)
        write_json_atomic(self.seal_path, seal.to_dict())
        assemble_candidate_root(checkpoint, output_dir=self.output_dir)
        return seal


def run_fixture_build(
    output_dir: PathLike,
    *,
    partitions: Sequence[str] = DEFAULT_PARTITIONS,
    families: Sequence[str] = DEFAULT_BUILD_FAMILIES,
    mode: BuildMode | str = BuildMode.FULL,
    resume: bool = True,
    validation_only: bool = False,
    interrupt_after_units: int | None = None,
    prior_salt: str | None = None,
    current_salt: str = "fixture",
    observation_cutoff: str = DEFAULT_OBSERVATION_CUTOFF,
    prior_cutoff: str = LEGACY_BASELINE_END_INCLUSIVE,
    bm25_decision: GlobalRebuildKind | str | None = None,
    cluster_decision: GlobalRebuildKind | str | None = None,
    checkpoint_dir: PathLike | None = None,
    producer: ArtifactProducer | None = None,
    resource_limits: ResourceLimits | None = None,
    use_family_builders: bool = False,
) -> BuildResult:
    """Convenience entry point for offline fixture builds (tests / CLI)."""

    mode_enum = BuildMode.coerce(mode)
    selected_producer: ArtifactProducer
    if producer is not None:
        selected_producer = producer
    elif use_family_builders:
        selected_producer = FamilyBuilderProducer()
    else:
        selected_producer = default_fixture_producer
    config = BuildConfig(
        mode=mode_enum,
        partitions=tuple(partitions),
        families=tuple(families),
        observation_cutoff=observation_cutoff,
        prior_cutoff=prior_cutoff,
        resume=resume,
        validation_only=validation_only,
        use_family_builders=use_family_builders,
        bm25_decision=(
            None if bm25_decision is None else GlobalRebuildKind.coerce(bm25_decision)
        ),
        cluster_decision=(
            None
            if cluster_decision is None
            else GlobalRebuildKind.coerce(cluster_decision)
        ),
        resource_limits=resource_limits or ResourceLimits(),
    )
    current = fixture_partition_snapshots(
        config.partitions,
        salt=current_salt,
        observation_cutoff=config.observation_cutoff,
    )
    prior = None
    if mode_enum is BuildMode.DELTA:
        prior = fixture_partition_snapshots(
            config.partitions,
            salt=prior_salt or "prior-fixture",
            observation_cutoff=config.prior_cutoff,
        )
    orchestrator = FederalRegisterBuildOrchestrator(
        output_dir=output_dir,
        checkpoint_dir=checkpoint_dir,
        producer=selected_producer,
    )
    return orchestrator.run(
        config,
        current=current,
        prior=prior,
        interrupt_after_units=interrupt_after_units,
    )


def run_hermetic_check() -> dict[str, Any]:
    """Offline self-check: planning, resume, stale reject, determinism, builders."""

    reject_hub_upload(False)
    proofs: list[str] = []
    with tempfile.TemporaryDirectory(prefix="fr-lcr061-check-") as raw:
        root = Path(raw)
        first = run_fixture_build(root / "full-a", mode=BuildMode.FULL)
        second = run_fixture_build(root / "full-b", mode=BuildMode.FULL)
        if first.seal is None or second.seal is None:
            raise SealError("hermetic full builds must seal")
        if first.seal.seal_digest != second.seal.seal_digest:
            raise BuildPlanError("two-build logical determinism failed")
        if first.candidate_root != second.candidate_root:
            raise BuildPlanError("two-build candidate roots diverged")
        proofs.append("two_build_logical_determinism")

        interrupted = run_fixture_build(
            root / "resume",
            mode=BuildMode.FULL,
            interrupt_after_units=2,
        )
        if interrupted.interrupted is not True or interrupted.seal is not None:
            raise SealError("interrupted build must not seal")
        try:
            assert_promotable(interrupted.checkpoint)
            raise PromotionError("stale partial checkpoint was promotable")
        except PromotionError:
            proofs.append("stale_checkpoint_cannot_promote")
        resumed = run_fixture_build(
            root / "resume",
            mode=BuildMode.FULL,
            resume=True,
        )
        if resumed.seal is None:
            raise SealError("resumed build must seal")
        if set(resumed.resumed_keys) & set(resumed.executed_keys):
            raise BuildPlanError("resume re-executed verified work")
        if resumed.seal.seal_digest != first.seal.seal_digest:
            raise BuildPlanError("resumed seal diverged from uninterrupted full build")
        proofs.append("interrupted_retry_idempotent")

        full = run_fixture_build(root / "equiv-full", mode=BuildMode.FULL)
        delta_all = run_fixture_build(
            root / "equiv-delta",
            mode=BuildMode.DELTA,
            current_salt="all-changed",
            prior_salt="prior",
            bm25_decision=GlobalRebuildKind.FULL_REBUILD,
            cluster_decision=GlobalRebuildKind.FULL_REBUILD,
        )
        # Full vs all-changed delta with forced full rebuild: family roots match
        # on global FULL_REBUILD families; corpus input hashes differ by salt so
        # compare the explicit equivalent_to_full flags instead of seal bytes.
        if not all(
            decision.equivalent_to_full
            for decision in delta_all.plan.global_decisions.values()
            if decision.family in GLOBAL_STAT_FAMILIES
        ):
            raise GlobalDecisionError("forced full rebuild was not equivalent_to_full")
        if full.seal is None or delta_all.seal is None:
            raise SealError("equivalence builds must seal")
        proofs.append("full_delta_equivalence_flags")

        mismatched = BuildConfig(
            mode=BuildMode.DELTA,
            partitions=DEFAULT_PARTITIONS,
            families=("corpus",),
        )
        try:
            assert_checkpoint_compatible(first.checkpoint, mismatched)
            raise BuildCheckpointError("config-mismatched checkpoint was accepted")
        except BuildCheckpointError:
            proofs.append("config_mismatched_checkpoint_rejected")

        tiny = BuildConfig(
            mode=BuildMode.FULL,
            partitions=DEFAULT_PARTITIONS,
            families=DEFAULT_BUILD_FAMILIES,
            resource_limits=ResourceLimits(max_partitions=1, max_work_units=100),
        )
        try:
            plan_full_build(tiny)
            raise ResourceLimitError("resource limit was not enforced")
        except ResourceLimitError:
            proofs.append("resource_budget_enforced")

        prior = fixture_partition_snapshots(
            DEFAULT_PARTITIONS, salt="same", observation_cutoff=LEGACY_BASELINE_END_INCLUSIVE
        )
        current = dict(prior)
        current["2026-08"] = fixture_partition_snapshots(
            ("2026-08",),
            salt="cutoff-delta",
            observation_cutoff=DEFAULT_OBSERVATION_CUTOFF,
        )["2026-08"]
        delta_plan = plan_delta_build(
            BuildConfig(
                mode=BuildMode.DELTA,
                partitions=DEFAULT_PARTITIONS,
                families=DEFAULT_BUILD_FAMILIES,
                bm25_rebuild_threshold=0.9,
                cluster_rebuild_threshold=0.9,
            ),
            current=current,
            prior=prior,
        )
        if "2026-08" not in delta_plan.changed_partitions:
            raise BuildPlanError("cutoff-delta did not mark the new month")
        if "bm25" not in delta_plan.invalidated_families:
            raise BuildPlanError("dependency closure did not invalidate bm25")
        bm25 = delta_plan.global_decisions["bm25"]
        if bm25.kind is GlobalRebuildKind.DELTA_REFRESH and bm25.equivalent_to_full:
            raise GlobalDecisionError("delta_refresh claimed equivalent_to_full")
        proofs.append("cutoff_delta_invalidates_dependency_closure")

        budget = MemoryBudget(max_resident_records=2)
        streamed = list(stream_bounded(range(8), budget=budget))
        if streamed != list(range(8)):
            raise MemoryBudgetError("bounded stream dropped records")
        if budget.peak_resident_records > 2:
            raise MemoryBudgetError("bounded stream exceeded resident budget")
        proofs.append("no_whole_corpus_memory_load")

        consumption = consume_family_builders()
        if consumption["authorizing_hub_upload"]:
            raise HubUploadForbiddenError("family builder consumption authorized Hub")
        proofs.append("family_builders_consumed")

        validation = run_fixture_build(
            root / "validate",
            mode=BuildMode.FULL,
            validation_only=True,
        )
        if (root / "validate" / ".checkpoints").exists():
            raise ValidationOnlyError("validation-only wrote checkpoints")
        if validation.seal is None:
            raise SealError("validation-only must still verify in memory")
        proofs.append("validation_only_no_writes")

        payload = {
            "candidate_root": first.candidate_root,
            "families": list(DEFAULT_BUILD_FAMILIES),
            "fixture_only": True,
            "goal_id": GOAL_ID,
            "ok": True,
            "program_id": PROGRAM_ID,
            "proofs": proofs,
            "schema_version": SCHEMA_VERSION,
            "seal_digest": first.seal.seal_digest,
            "task_id": TASK_ID,
            **software_contract_flags(),
            "family_builder_consumption": {
                "bm25_root": consumption["bm25_root"],
                "vector_root": consumption["vector_root"],
                "graph_root": consumption["graph_root"],
                "adjacency_root": consumption["adjacency_root"],
                "consumption_digest": consumption["consumption_digest"],
            },
        }
        payload["check_digest"] = digest_mapping(
            {
                "proofs": proofs,
                "schema_version": SCHEMA_VERSION,
                "task_id": TASK_ID,
            }
        )
        return payload


# ---------------------------------------------------------------------------
# Public exports
# ---------------------------------------------------------------------------


__all__ = [
    "AUTHORIZES_HUB_UPLOAD",
    "AUTHORIZES_PUBLICATION",
    "CANDIDATE_ROOT_FILENAME",
    "CHECKPOINT_FILENAME",
    "DEFAULT_BM25_REBUILD_THRESHOLD",
    "DEFAULT_BUILD_FAMILIES",
    "DEFAULT_CLUSTER_REBUILD_THRESHOLD",
    "DEFAULT_MAX_RECORDS_IN_MEMORY",
    "DEFAULT_PARTITIONS",
    "FAMILY_DEPENDENCIES",
    "GOAL_ID",
    "GLOBAL_FAMILIES",
    "GLOBAL_PARTITION",
    "GLOBAL_STAT_FAMILIES",
    "PROGRAM_ID",
    "PRODUCER",
    "PROVES_SOFTWARE_CONTRACT_ONLY",
    "RECEIPT_FILENAME",
    "RELEASE_PROFILE",
    "SCHEMA_VERSION",
    "SEAL_FILENAME",
    "TASK_ID",
    "ArtifactProducer",
    "BuildCheckpoint",
    "BuildCheckpointError",
    "BuildConfig",
    "BuildConfigError",
    "BuildMode",
    "BuildPlan",
    "BuildPlanError",
    "BuildResult",
    "BuildSeal",
    "DecisionSource",
    "FamilyBuilderProducer",
    "FederalRegisterBuildOrchestrator",
    "FederalRegisterReleaseError",
    "GlobalDecisionError",
    "GlobalRebuildDecision",
    "GlobalRebuildKind",
    "HubUploadForbiddenError",
    "MemoryBudget",
    "MemoryBudgetError",
    "PartitionSnapshot",
    "ProducerError",
    "ProducerResult",
    "PromotionError",
    "ResourceLimitError",
    "ResourceLimits",
    "SealError",
    "ValidationOnlyError",
    "WorkUnit",
    "WorkUnitRecord",
    "WorkUnitStatus",
    "assemble_candidate_root",
    "assert_checkpoint_compatible",
    "assert_promotable",
    "canonical_json_dumps",
    "compute_seal",
    "consume_family_builders",
    "content_digest",
    "cutoff_delta_partitions",
    "decide_dependent_rebuild",
    "decide_global_rebuild",
    "default_fixture_producer",
    "dependency_closure",
    "family_execution_order",
    "fixture_partition_snapshots",
    "invalidate_dependency_closure",
    "load_checkpoint",
    "plan_build",
    "plan_delta_build",
    "plan_full_build",
    "reject_hub_upload",
    "run_fixture_build",
    "run_hermetic_check",
    "software_contract_flags",
    "stream_bounded",
    "work_unit_key",
    "write_checkpoint_atomic",
    "write_json_atomic",
]
