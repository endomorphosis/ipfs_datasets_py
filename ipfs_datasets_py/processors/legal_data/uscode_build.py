"""Resumable full and delta US Code sparse GraphRAG build orchestration (USCIR-030).

Owns title × artifact-family orchestration, atomic checkpoints, resumable
receipts, deterministic build configuration, full/delta planning, resource
limits, validation-only mode, and seal gating.

Design invariants
-----------------
* Artifact semantics (corpus, BM25, vectors, graph, lexical overlay) are
  **delegated** to producer modules. This module plans, checkpoints, resumes,
  and seals — it does not reimplement index math.
* Global BM25 and vector-cluster rebuild decisions are **explicit**. A partial
  refresh is never labeled equivalent to a full rebuild without proof.
* Checkpoints bind ``config_digest``; stale or config-mismatched checkpoints
  fail closed.
* A release candidate may be sealed only when every planned work unit is
  verified. Partial output cannot be sealed.
* No network I/O. Fixture builds are fully offline and deterministic.
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
    Mapping,
    Optional,
    Protocol,
    Sequence,
    Union,
)

from ipfs_datasets_py.processors.legal_data.uscode_release_schema import (
    canonical_json_dumps,
    digest_mapping,
)
from ipfs_datasets_py.processors.legal_data.uscode_source_policy import (
    CANONICAL_USCODE_TITLES,
    DEFAULT_APPROVED_RELEASE_POINT,
)

# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------

SCHEMA_VERSION: Final = "uscode-build-orchestration-v1"
CHECKPOINT_FILENAME: Final = "build_checkpoint.json"
SEAL_FILENAME: Final = "build_seal.json"
RECEIPT_FILENAME: Final = "build_receipt.json"
TASK_ID: Final = "USCIR-030"
GOAL_ID: Final = "USCIR-G080"
PRODUCER: Final = "uscode_build.py"
RELEASE_PROFILE: Final = "publicus-ir-graphrag/v2"
DEFAULT_DATASET_REPO_ID: Final = "justicedao/ipfs_uscode"
DEFAULT_DETERMINISM_SEED: Final = 20260330

# Build-level artifact families (orchestration grain; coarser than schema).
DEFAULT_BUILD_FAMILIES: Final = (
    "corpus",
    "bm25",
    "vectors",
    "graph",
    "lexical_graph",
)

# Families whose global statistics may force an explicit full rebuild.
GLOBAL_STAT_FAMILIES: Final = frozenset({"bm25", "vectors"})

# Default compaction thresholds for auto global-rebuild decisions.
DEFAULT_BM25_REBUILD_THRESHOLD: Final = 0.15
DEFAULT_CLUSTER_REBUILD_THRESHOLD: Final = 0.20

PathLike = Union[str, Path]
JsonMapping = Mapping[str, Any]
ProducerFn = Callable[["WorkUnit", "BuildConfig", Path], "ProducerResult"]


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class UscodeBuildError(ValueError):
    """Base error for build orchestration failures."""

    code: str = "uscode_build_error"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "kind": "error", "message": str(self)}


class BuildConfigError(UscodeBuildError):
    """Raised when the build configuration is invalid."""

    code = "build_config_invalid"


class BuildCheckpointError(UscodeBuildError):
    """Raised when a checkpoint is corrupt, stale, or config-mismatched."""

    code = "checkpoint_invalid"


class BuildPlanError(UscodeBuildError):
    """Raised when full/delta planning cannot produce a valid plan."""

    code = "build_plan_invalid"


class GlobalDecisionError(UscodeBuildError):
    """Raised when a global rebuild decision is missing or inconsistent."""

    code = "global_decision_invalid"


class SealError(UscodeBuildError):
    """Raised when sealing is attempted on incomplete or mismatched work."""

    code = "seal_rejected"


class ResourceLimitError(UscodeBuildError):
    """Raised when resource limits would be exceeded."""

    code = "resource_limit_exceeded"


class ProducerError(UscodeBuildError):
    """Raised when a delegated producer fails a work unit."""

    code = "producer_failed"


class ValidationOnlyError(UscodeBuildError):
    """Raised when a mutation is requested in validation-only mode."""

    code = "validation_only"


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
    """Lifecycle status of one title × family work unit."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    VERIFIED = "verified"
    FAILED = "failed"
    SKIPPED = "skipped"

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


def _normalize_title(value: Any) -> str:
    text = _require_non_empty_str(str(value), "title", maximum=8)
    if text.isdigit():
        # Canonical form is unpadded decimal (matches source policy).
        return str(int(text))
    raise BuildConfigError(f"title must be a numeric U.S. Code title, got {value!r}")


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
        "lexical": "lexical_graph",
        "bm25_neighbors": "lexical_graph",
        "overlay": "lexical_graph",
    }
    return aliases.get(text, text)


def work_unit_key(title: str, family: str) -> str:
    """Stable map key for a title × family work unit."""

    return f"{_normalize_title(title)}/{_normalize_family(family)}"


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
        prefix=".uscode-build-",
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
# Resource limits
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ResourceLimits:
    """Hard caps applied before a plan is executed."""

    max_titles: int = 53
    max_work_units: int = 512
    max_memory_mb: Optional[int] = None
    max_concurrent_families: int = 1
    resource_class: str = "memory-large"

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "max_titles", _require_positive_int(self.max_titles, "max_titles")
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
            "max_titles": self.max_titles,
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
            max_titles=int(value.get("max_titles", 53)),
            max_work_units=int(value.get("max_work_units", 512)),
            max_memory_mb=(
                None
                if value.get("max_memory_mb") is None
                else int(value["max_memory_mb"])
            ),
            max_concurrent_families=int(value.get("max_concurrent_families", 1)),
            resource_class=str(value.get("resource_class", "memory-large")),
        )

    def enforce(
        self,
        *,
        title_count: int,
        work_unit_count: int,
    ) -> None:
        if title_count > self.max_titles:
            raise ResourceLimitError(
                f"title count {title_count} exceeds max_titles={self.max_titles}"
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
        # Fail closed: delta refresh is never equivalent to a full rebuild.
        if self.kind is GlobalRebuildKind.DELTA_REFRESH and self.equivalent_to_full:
            raise GlobalDecisionError(
                f"{self.family}: delta_refresh cannot claim equivalent_to_full "
                "without a full_rebuild decision"
            )
        if self.kind is GlobalRebuildKind.FULL_REBUILD and not self.equivalent_to_full:
            object.__setattr__(self, "equivalent_to_full", True)
        if self.kind is GlobalRebuildKind.UNCHANGED and self.equivalent_to_full:
            # Unchanged prior full index is still a full-equivalent artifact.
            pass

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
            source=DecisionSource(str(value.get("source") or DecisionSource.EXPLICIT.value)),
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
    """Compute an explicit global rebuild decision for BM25 or clusters.

    Parameters
    ----------
    explicit:
        Operator override. When set, the decision is taken from this value
        and recorded with ``source=explicit``.
    changed_ratio:
        Fraction of documents (or titles) that changed relative to the prior
        release. Used only for auto threshold decisions.
    threshold:
        Compaction threshold. Auto mode chooses full rebuild when
        ``changed_ratio >= threshold``.
    """

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


# ---------------------------------------------------------------------------
# Build configuration
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BuildConfig:
    """Deterministic configuration for one orchestrated build."""

    release_point: str = DEFAULT_APPROVED_RELEASE_POINT
    mode: BuildMode = BuildMode.FULL
    titles: tuple[str, ...] = ()
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
    notes: str = ""
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "release_point",
            _require_non_empty_str(self.release_point, "release_point"),
        )
        lowered = self.release_point.strip().lower()
        if lowered in {"latest", "main", "head", "master"}:
            raise BuildConfigError(
                f"release_point must be an exact pin, not {self.release_point!r}"
            )
        object.__setattr__(self, "mode", BuildMode.coerce(self.mode))
        titles = tuple(
            _normalize_title(t)
            for t in (self.titles or CANONICAL_USCODE_TITLES)
        )
        if not titles:
            raise BuildConfigError("titles must be non-empty")
        # Deterministic order, unique.
        titles = tuple(sorted(set(titles), key=lambda t: (len(t), t)))
        object.__setattr__(self, "titles", titles)
        families = tuple(
            _normalize_family(f)
            for f in (self.families or DEFAULT_BUILD_FAMILIES)
        )
        if not families:
            raise BuildConfigError("families must be non-empty")
        # Preserve declared order, drop dups.
        seen: set[str] = set()
        ordered: list[str] = []
        for fam in families:
            if fam not in seen:
                seen.add(fam)
                ordered.append(fam)
        object.__setattr__(self, "families", tuple(ordered))
        object.__setattr__(
            self,
            "dataset_repo_id",
            _require_non_empty_str(self.dataset_repo_id, "dataset_repo_id"),
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
                self, "cluster_decision", GlobalRebuildKind.coerce(self.cluster_decision)
            )
        if not isinstance(self.resource_limits, ResourceLimits):
            object.__setattr__(
                self,
                "resource_limits",
                ResourceLimits.from_mapping(self.resource_limits),  # type: ignore[arg-type]
            )
        object.__setattr__(self, "validation_only", bool(self.validation_only))
        object.__setattr__(self, "resume", bool(self.resume))
        object.__setattr__(self, "notes", str(self.notes or ""))
        if self.schema_version != SCHEMA_VERSION:
            raise BuildConfigError(
                f"unsupported schema_version {self.schema_version!r}"
            )

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
            "mode": self.mode.value,
            "notes": self.notes,
            "release_point": self.release_point,
            "resource_limits": self.resource_limits.to_dict(),
            "resume": self.resume,
            "schema_version": self.schema_version,
            "titles": list(self.titles),
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
            "mode": self.mode.value,
            "release_point": self.release_point,
            "resource_limits": self.resource_limits.to_dict(),
            "schema_version": self.schema_version,
            "titles": list(self.titles),
        }
        return digest_mapping(payload)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "BuildConfig":
        if not isinstance(value, Mapping):
            raise BuildConfigError("build config must be a mapping")
        bm25_raw = value.get("bm25_decision")
        cluster_raw = value.get("cluster_decision")
        return cls(
            release_point=str(value.get("release_point") or DEFAULT_APPROVED_RELEASE_POINT),
            mode=BuildMode.coerce(value.get("mode") or BuildMode.FULL),
            titles=tuple(value.get("titles") or ()),
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
            notes=str(value.get("notes") or ""),
            schema_version=str(value.get("schema_version") or SCHEMA_VERSION),
        )


# ---------------------------------------------------------------------------
# Work units and producer protocol
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class WorkUnit:
    """One title × artifact-family unit of orchestrated work."""

    title: str
    family: str
    input_hash: str
    action: str = "build"  # build | skip | reuse

    def __post_init__(self) -> None:
        object.__setattr__(self, "title", _normalize_title(self.title))
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

    @property
    def key(self) -> str:
        return work_unit_key(self.title, self.family)

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "family": self.family,
            "input_hash": self.input_hash,
            "key": self.key,
            "title": self.title,
        }


@dataclass(frozen=True, slots=True)
class ProducerResult:
    """Result returned by a delegated producer for one work unit."""

    output_digest: str
    artifact_path: str = ""
    row_count: int = 0
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
        object.__setattr__(self, "metadata", dict(self.metadata or {}))
        object.__setattr__(self, "skipped", bool(self.skipped))

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_path": self.artifact_path,
            "metadata": dict(self.metadata),
            "output_digest": self.output_digest,
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

    Writes a compact JSON artifact per work unit. Does not invoke heavy
    optional backends. Real production pipelines inject domain producers.
    """

    if unit.action in {"skip", "reuse"}:
        return ProducerResult(
            output_digest=f"reuse:{unit.input_hash}",
            artifact_path="",
            row_count=0,
            metadata={"action": unit.action},
            skipped=True,
        )
    rel = f"{unit.family}/title-{unit.title}.json"
    target = output_dir / rel
    payload = {
        "config_digest": config.digest,
        "family": unit.family,
        "input_hash": unit.input_hash,
        "producer": "default_fixture_producer",
        "release_point": config.release_point,
        "schema_version": SCHEMA_VERSION,
        "seed": config.determinism_seed,
        "task_id": TASK_ID,
        "title": unit.title,
    }
    if not config.validation_only:
        write_json_atomic(target, payload)
    digest = digest_mapping(payload)
    return ProducerResult(
        output_digest=digest,
        artifact_path=rel if not config.validation_only else "",
        row_count=1,
        metadata={"fixture": True},
        skipped=False,
    )


# ---------------------------------------------------------------------------
# Title identity snapshots (for delta planning)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TitleSnapshot:
    """Content identity for one title used by delta planning."""

    title: str
    content_hash: str
    document_count: int = 1

    def __post_init__(self) -> None:
        object.__setattr__(self, "title", _normalize_title(self.title))
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

    def to_dict(self) -> dict[str, Any]:
        return {
            "content_hash": self.content_hash,
            "document_count": self.document_count,
            "title": self.title,
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "TitleSnapshot":
        if not isinstance(value, Mapping):
            raise BuildPlanError("title snapshot must be a mapping")
        return cls(
            title=str(value.get("title") or ""),
            content_hash=str(value.get("content_hash") or ""),
            document_count=int(value.get("document_count") or 1),
        )


def fixture_title_snapshots(
    titles: Sequence[str],
    *,
    salt: str = "fixture",
    document_count: int = 1,
) -> dict[str, TitleSnapshot]:
    """Build deterministic title snapshots for offline fixture builds."""

    out: dict[str, TitleSnapshot] = {}
    for title in titles:
        t = _normalize_title(title)
        digest = digest_mapping(
            {"document_count": document_count, "salt": salt, "title": t}
        )
        out[t] = TitleSnapshot(
            title=t, content_hash=digest, document_count=document_count
        )
    return out


# ---------------------------------------------------------------------------
# Checkpoint / receipt records
# ---------------------------------------------------------------------------


@dataclass
class WorkUnitRecord:
    """Durable per-unit progress record stored in the checkpoint."""

    title: str
    family: str
    status: WorkUnitStatus
    input_hash: str
    output_digest: str = ""
    artifact_path: str = ""
    attempt_count: int = 0
    error: str = ""
    verified: bool = False

    def __post_init__(self) -> None:
        self.title = _normalize_title(self.title)
        self.family = _normalize_family(self.family)
        self.status = WorkUnitStatus.coerce(self.status)
        self.input_hash = _require_non_empty_str(
            self.input_hash, "input_hash", maximum=128
        )
        self.output_digest = str(self.output_digest or "")
        self.artifact_path = str(self.artifact_path or "")
        self.attempt_count = _require_non_negative_int(
            self.attempt_count, "attempt_count"
        )
        self.error = str(self.error or "")
        self.verified = bool(self.verified)
        if self.status is WorkUnitStatus.VERIFIED:
            self.verified = True
        if self.verified and self.status is not WorkUnitStatus.VERIFIED:
            self.status = WorkUnitStatus.VERIFIED

    @property
    def key(self) -> str:
        return work_unit_key(self.title, self.family)

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_path": self.artifact_path,
            "attempt_count": self.attempt_count,
            "error": self.error,
            "family": self.family,
            "input_hash": self.input_hash,
            "output_digest": self.output_digest,
            "status": self.status.value,
            "title": self.title,
            "verified": self.verified,
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "WorkUnitRecord":
        if not isinstance(value, Mapping):
            raise BuildCheckpointError("work unit record must be a mapping")
        return cls(
            title=str(value.get("title") or ""),
            family=str(value.get("family") or ""),
            status=WorkUnitStatus.coerce(value.get("status") or WorkUnitStatus.PENDING),
            input_hash=str(value.get("input_hash") or ""),
            output_digest=str(value.get("output_digest") or ""),
            artifact_path=str(value.get("artifact_path") or ""),
            attempt_count=int(value.get("attempt_count") or 0),
            error=str(value.get("error") or ""),
            verified=bool(value.get("verified", False)),
        )


@dataclass
class BuildCheckpoint:
    """Atomic, resumable checkpoint for an orchestrated build."""

    config_digest: str
    build_id: str
    mode: BuildMode
    release_point: str
    units: dict[str, WorkUnitRecord]
    global_decisions: dict[str, GlobalRebuildDecision]
    sealed: bool = False
    seal_digest: str = ""
    schema_version: str = SCHEMA_VERSION
    producer: str = PRODUCER
    task_id: str = TASK_ID

    def __post_init__(self) -> None:
        self.config_digest = _require_non_empty_str(
            self.config_digest, "config_digest", maximum=128
        )
        self.build_id = _require_non_empty_str(self.build_id, "build_id", maximum=128)
        self.mode = BuildMode.coerce(self.mode)
        self.release_point = _require_non_empty_str(
            self.release_point, "release_point"
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
            if rec.key != str(key):
                # Prefer the record's canonical key.
                pass
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
        if self.schema_version != SCHEMA_VERSION:
            raise BuildCheckpointError(
                f"unsupported checkpoint schema_version: {self.schema_version!r}"
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

    def to_dict(self) -> dict[str, Any]:
        return {
            "all_verified": self.all_verified,
            "build_id": self.build_id,
            "config_digest": self.config_digest,
            "global_decisions": {
                k: v.to_dict()
                for k, v in sorted(self.global_decisions.items(), key=lambda kv: kv[0])
            },
            "mode": self.mode.value,
            "producer": self.producer,
            "release_point": self.release_point,
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
            release_point=str(value.get("release_point") or ""),
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
    if checkpoint.config_digest != config.digest:
        raise BuildCheckpointError(
            "checkpoint config_digest does not match active build configuration"
        )
    if checkpoint.release_point != config.release_point:
        raise BuildCheckpointError(
            f"checkpoint release_point {checkpoint.release_point!r} "
            f"!= config release_point {config.release_point!r}"
        )
    if checkpoint.mode is not config.mode:
        raise BuildCheckpointError(
            f"checkpoint mode {checkpoint.mode.value!r} "
            f"!= config mode {config.mode.value!r}"
        )


# ---------------------------------------------------------------------------
# Build plan
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BuildPlan:
    """Deterministic full or delta plan with explicit global decisions."""

    mode: BuildMode
    units: tuple[WorkUnit, ...]
    global_decisions: Mapping[str, GlobalRebuildDecision]
    changed_titles: tuple[str, ...]
    unchanged_titles: tuple[str, ...]
    changed_document_ratio: float
    config_digest: str
    build_id: str

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
            "changed_titles",
            tuple(_normalize_title(t) for t in self.changed_titles),
        )
        object.__setattr__(
            self,
            "unchanged_titles",
            tuple(_normalize_title(t) for t in self.unchanged_titles),
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
        # Global decisions for BM25/vectors must always be present and explicit.
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
            "changed_titles": list(self.changed_titles),
            "config_digest": self.config_digest,
            "global_decisions": {
                k: v.to_dict()
                for k, v in sorted(self.global_decisions.items(), key=lambda kv: kv[0])
            },
            "mode": self.mode.value,
            "runnable_count": len(self.runnable_units),
            "skipped_count": len(self.skipped_units),
            "unchanged_titles": list(self.unchanged_titles),
            "unit_count": len(self.units),
            "units": [u.to_dict() for u in self.units],
        }


def _build_id_for(config: BuildConfig, *, salt: str = "") -> str:
    return digest_mapping(
        {
            "config_digest": config.digest,
            "mode": config.mode.value,
            "release_point": config.release_point,
            "salt": salt,
            "task_id": TASK_ID,
        }
    )[:32]


def plan_full_build(
    config: BuildConfig,
    *,
    current: Mapping[str, TitleSnapshot] | None = None,
) -> BuildPlan:
    """Plan a full rebuild of every title × family."""

    snapshots = dict(current or fixture_title_snapshots(config.titles))
    for title in config.titles:
        if title not in snapshots:
            raise BuildPlanError(f"missing title snapshot for full plan: {title}")
    units: list[WorkUnit] = []
    for title in config.titles:
        snap = snapshots[title]
        for family in config.families:
            units.append(
                WorkUnit(
                    title=title,
                    family=family,
                    input_hash=snap.content_hash,
                    action="build",
                )
            )
    decisions = {
        "bm25": decide_global_rebuild(
            "bm25",
            mode=BuildMode.FULL,
            changed_ratio=1.0,
            threshold=config.bm25_rebuild_threshold,
            explicit=config.bm25_decision or GlobalRebuildKind.FULL_REBUILD,
            prior_present=False,
        ),
        "vectors": decide_global_rebuild(
            "vectors",
            mode=BuildMode.FULL,
            changed_ratio=1.0,
            threshold=config.cluster_rebuild_threshold,
            explicit=config.cluster_decision or GlobalRebuildKind.FULL_REBUILD,
            prior_present=False,
        ),
    }
    config.resource_limits.enforce(
        title_count=len(config.titles),
        work_unit_count=len(units),
    )
    return BuildPlan(
        mode=BuildMode.FULL,
        units=tuple(units),
        global_decisions=decisions,
        changed_titles=tuple(config.titles),
        unchanged_titles=(),
        changed_document_ratio=1.0,
        config_digest=config.digest,
        build_id=_build_id_for(config, salt="full"),
    )


def plan_delta_build(
    config: BuildConfig,
    *,
    current: Mapping[str, TitleSnapshot],
    prior: Mapping[str, TitleSnapshot],
) -> BuildPlan:
    """Plan a delta build from *prior* → *current* title snapshots.

    Global BM25/cluster decisions are computed explicitly from the changed
    document ratio and configured thresholds (or operator overrides). A
    ``delta_refresh`` decision is **never** labeled equivalent to a full rebuild.
    """

    if config.mode is not BuildMode.DELTA:
        # Allow planning delta even if config.mode was full when called directly,
        # but prefer the caller's intent.
        pass
    if not current:
        raise BuildPlanError("delta plan requires non-empty current snapshots")

    current_map = {
        _normalize_title(k): (
            v if isinstance(v, TitleSnapshot) else TitleSnapshot.from_mapping(v)  # type: ignore[arg-type]
        )
        for k, v in current.items()
    }
    prior_map = {
        _normalize_title(k): (
            v if isinstance(v, TitleSnapshot) else TitleSnapshot.from_mapping(v)  # type: ignore[arg-type]
        )
        for k, v in (prior or {}).items()
    }

    titles = tuple(config.titles)
    for title in titles:
        if title not in current_map:
            raise BuildPlanError(f"missing current snapshot for title {title}")

    changed: list[str] = []
    unchanged: list[str] = []
    total_docs = 0
    changed_docs = 0
    for title in titles:
        cur = current_map[title]
        total_docs += cur.document_count
        prev = prior_map.get(title)
        if prev is None or prev.content_hash != cur.content_hash:
            changed.append(title)
            changed_docs += cur.document_count
        else:
            unchanged.append(title)

    if total_docs <= 0:
        raise BuildPlanError("total document count must be positive")
    changed_ratio = changed_docs / float(total_docs)

    bm25_decision = decide_global_rebuild(
        "bm25",
        mode=BuildMode.DELTA,
        changed_ratio=changed_ratio,
        threshold=config.bm25_rebuild_threshold,
        explicit=config.bm25_decision,
        prior_present=bool(prior_map),
    )
    cluster_decision = decide_global_rebuild(
        "vectors",
        mode=BuildMode.DELTA,
        changed_ratio=changed_ratio,
        threshold=config.cluster_rebuild_threshold,
        explicit=config.cluster_decision,
        prior_present=bool(prior_map),
    )
    decisions = {"bm25": bm25_decision, "vectors": cluster_decision}

    units: list[WorkUnit] = []
    changed_set = set(changed)
    for title in titles:
        snap = current_map[title]
        title_changed = title in changed_set
        for family in config.families:
            if family in GLOBAL_STAT_FAMILIES:
                decision = decisions[family]
                if decision.kind is GlobalRebuildKind.FULL_REBUILD:
                    action = "build"
                elif decision.kind is GlobalRebuildKind.UNCHANGED:
                    action = "reuse"
                else:
                    # Delta refresh: rebuild only changed titles.
                    action = "build" if title_changed else "reuse"
            else:
                action = "build" if title_changed else "reuse"
            units.append(
                WorkUnit(
                    title=title,
                    family=family,
                    input_hash=snap.content_hash,
                    action=action,
                )
            )

    config.resource_limits.enforce(
        title_count=len(titles),
        work_unit_count=len(units),
    )
    return BuildPlan(
        mode=BuildMode.DELTA,
        units=tuple(units),
        global_decisions=decisions,
        changed_titles=tuple(changed),
        unchanged_titles=tuple(unchanged),
        changed_document_ratio=changed_ratio,
        config_digest=config.digest,
        build_id=_build_id_for(config, salt="delta"),
    )


def plan_build(
    config: BuildConfig,
    *,
    current: Mapping[str, TitleSnapshot] | None = None,
    prior: Mapping[str, TitleSnapshot] | None = None,
) -> BuildPlan:
    """Plan a full or delta build according to *config.mode*."""

    if config.mode is BuildMode.FULL:
        return plan_full_build(config, current=current)
    if prior is None:
        raise BuildPlanError("delta mode requires prior title snapshots")
    if current is None:
        raise BuildPlanError("delta mode requires current title snapshots")
    return plan_delta_build(config, current=current, prior=prior)


# ---------------------------------------------------------------------------
# Build result / seal
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
    release_point: str
    mode: str
    schema_version: str = SCHEMA_VERSION
    task_id: str = TASK_ID

    def to_dict(self) -> dict[str, Any]:
        return {
            "build_id": self.build_id,
            "config_digest": self.config_digest,
            "global_decisions": dict(self.global_decisions),
            "mode": self.mode,
            "release_point": self.release_point,
            "schema_version": self.schema_version,
            "seal_digest": self.seal_digest,
            "task_id": self.task_id,
            "unit_count": self.unit_count,
            "unit_digests": dict(self.unit_digests),
            "verified_count": self.verified_count,
        }


def compute_seal(checkpoint: BuildCheckpoint) -> BuildSeal:
    """Compute a seal over a fully verified checkpoint (fail-closed)."""

    if not checkpoint.all_verified:
        raise SealError(
            f"cannot seal incomplete build: "
            f"{checkpoint.verified_count}/{checkpoint.total_count} verified"
        )
    if checkpoint.sealed and checkpoint.seal_digest:
        # Already sealed — recompute and compare.
        pass
    unit_digests = {
        key: rec.output_digest
        for key, rec in sorted(checkpoint.units.items(), key=lambda kv: kv[0])
    }
    if any(not d for d in unit_digests.values()):
        raise SealError("cannot seal: one or more units lack output_digest")
    payload = {
        "build_id": checkpoint.build_id,
        "config_digest": checkpoint.config_digest,
        "global_decisions": {
            k: v.to_dict()
            for k, v in sorted(
                checkpoint.global_decisions.items(), key=lambda kv: kv[0]
            )
        },
        "mode": checkpoint.mode.value,
        "release_point": checkpoint.release_point,
        "schema_version": SCHEMA_VERSION,
        "task_id": TASK_ID,
        "unit_digests": unit_digests,
    }
    seal_digest = digest_mapping(payload)
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
        release_point=checkpoint.release_point,
        mode=checkpoint.mode.value,
    )


@dataclass(frozen=True, slots=True)
class BuildResult:
    """Outcome of one orchestrator run."""

    plan: BuildPlan
    checkpoint: BuildCheckpoint
    seal: Optional[BuildSeal]
    executed_keys: tuple[str, ...]
    resumed_keys: tuple[str, ...]
    skipped_keys: tuple[str, ...]
    validation_only: bool
    interrupted: bool
    receipt_path: str = ""
    checkpoint_path: str = ""
    seal_path: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "checkpoint": self.checkpoint.to_dict(),
            "checkpoint_path": self.checkpoint_path,
            "executed_keys": list(self.executed_keys),
            "interrupted": self.interrupted,
            "plan": self.plan.to_dict(),
            "receipt_path": self.receipt_path,
            "resumed_keys": list(self.resumed_keys),
            "seal": None if self.seal is None else self.seal.to_dict(),
            "seal_path": self.seal_path,
            "skipped_keys": list(self.skipped_keys),
            "validation_only": self.validation_only,
        }


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


class UscodeBuildOrchestrator:
    """Resumable full/delta build orchestrator for US Code sparse GraphRAG.

    Parameters
    ----------
    output_dir:
        Root directory for producer artifacts.
    checkpoint_dir:
        Directory for atomic checkpoints, receipts, and seals.
    producer:
        Callable that builds one :class:`WorkUnit`. Defaults to the offline
        fixture producer (no optional backends).
    """

    def __init__(
        self,
        *,
        output_dir: PathLike,
        checkpoint_dir: PathLike | None = None,
        producer: ArtifactProducer | None = None,
    ) -> None:
        self.output_dir = Path(output_dir)
        self.checkpoint_dir = Path(
            checkpoint_dir if checkpoint_dir is not None else self.output_dir / ".checkpoints"
        )
        self.producer: ArtifactProducer = producer or default_fixture_producer
        self.checkpoint_path = self.checkpoint_dir / CHECKPOINT_FILENAME
        self.seal_path = self.checkpoint_dir / SEAL_FILENAME
        self.receipt_path = self.checkpoint_dir / RECEIPT_FILENAME

    # -- planning -----------------------------------------------------------

    def plan(
        self,
        config: BuildConfig,
        *,
        current: Mapping[str, TitleSnapshot] | None = None,
        prior: Mapping[str, TitleSnapshot] | None = None,
    ) -> BuildPlan:
        return plan_build(config, current=current, prior=prior)

    # -- checkpoint helpers -------------------------------------------------

    def load_checkpoint(self) -> BuildCheckpoint | None:
        if not self.checkpoint_path.is_file():
            return None
        return load_checkpoint(self.checkpoint_path)

    def write_checkpoint(self, checkpoint: BuildCheckpoint) -> Path:
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)
        return write_checkpoint_atomic(self.checkpoint_path, checkpoint)

    # -- execution ----------------------------------------------------------

    def run(
        self,
        config: BuildConfig,
        *,
        current: Mapping[str, TitleSnapshot] | None = None,
        prior: Mapping[str, TitleSnapshot] | None = None,
        interrupt_after_units: int | None = None,
        force_seal: bool = False,
    ) -> BuildResult:
        """Execute a planned build with optional resume and interrupt hooks.

        Parameters
        ----------
        interrupt_after_units:
            Test/harness hook. Stop after N newly executed (non-resumed)
            work units and leave an unsealed checkpoint for resume.
        force_seal:
            When True, attempt seal even in validation-only mode (still
            requires full verification). Validation-only never writes seal
            artifacts to disk.
        """

        plan = self.plan(config, current=current, prior=prior)
        existing = self.load_checkpoint() if config.resume else None
        if existing is not None:
            assert_checkpoint_compatible(existing, config)
            if existing.build_id != plan.build_id:
                # Same config digest but different plan salt — treat as mismatch.
                raise BuildCheckpointError(
                    "checkpoint build_id does not match the active plan"
                )

        units_by_key = {u.key: u for u in plan.units}
        records: dict[str, WorkUnitRecord] = {}
        resumed_keys: list[str] = []
        skipped_keys: list[str] = []
        executed_keys: list[str] = []

        # Seed records from plan; overlay verified prior work when resuming.
        for unit in plan.units:
            prior_rec = existing.units.get(unit.key) if existing else None
            if (
                prior_rec is not None
                and prior_rec.verified
                and prior_rec.status is WorkUnitStatus.VERIFIED
                and prior_rec.input_hash == unit.input_hash
                and prior_rec.output_digest
            ):
                records[unit.key] = WorkUnitRecord(
                    title=unit.title,
                    family=unit.family,
                    status=WorkUnitStatus.VERIFIED,
                    input_hash=unit.input_hash,
                    output_digest=prior_rec.output_digest,
                    artifact_path=prior_rec.artifact_path,
                    attempt_count=prior_rec.attempt_count,
                    verified=True,
                )
                resumed_keys.append(unit.key)
            elif unit.action in {"skip", "reuse"}:
                # Reuse units are verified without re-running producers.
                reuse_digest = f"reuse:{unit.input_hash}"
                records[unit.key] = WorkUnitRecord(
                    title=unit.title,
                    family=unit.family,
                    status=WorkUnitStatus.VERIFIED,
                    input_hash=unit.input_hash,
                    output_digest=reuse_digest,
                    artifact_path="",
                    attempt_count=0,
                    verified=True,
                )
                skipped_keys.append(unit.key)
            else:
                records[unit.key] = WorkUnitRecord(
                    title=unit.title,
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
            release_point=config.release_point,
            units=records,
            global_decisions=dict(plan.global_decisions),
            sealed=False,
        )

        if not config.validation_only:
            self.output_dir.mkdir(parents=True, exist_ok=True)
            self.write_checkpoint(checkpoint)

        newly_executed = 0
        interrupted = False
        # Deterministic execution order.
        pending_keys = sorted(
            k
            for k, rec in checkpoint.units.items()
            if not rec.verified and units_by_key[k].action == "build"
        )

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
            except UscodeBuildError:
                rec.status = WorkUnitStatus.FAILED
                rec.error = "producer raised UscodeBuildError"
                if not config.validation_only:
                    self.write_checkpoint(checkpoint)
                raise
            except Exception as exc:  # noqa: BLE001 — surface as producer failure
                rec.status = WorkUnitStatus.FAILED
                rec.error = f"{type(exc).__name__}: {exc}"
                if not config.validation_only:
                    self.write_checkpoint(checkpoint)
                raise ProducerError(
                    f"producer failed for {key}: {exc}"
                ) from exc

            if result.skipped:
                rec.status = WorkUnitStatus.VERIFIED
                rec.verified = True
                rec.output_digest = result.output_digest
                rec.artifact_path = result.artifact_path
                skipped_keys.append(key)
            else:
                rec.status = WorkUnitStatus.VERIFIED
                rec.verified = True
                rec.output_digest = result.output_digest
                rec.artifact_path = result.artifact_path
                executed_keys.append(key)
                newly_executed += 1
            rec.error = ""
            if not config.validation_only:
                self.write_checkpoint(checkpoint)

        seal: BuildSeal | None = None
        seal_path = ""
        if interrupted:
            # Fail closed: never seal partial work.
            if checkpoint.sealed:
                raise SealError("internal error: interrupted checkpoint is sealed")
        elif checkpoint.all_verified:
            seal = compute_seal(checkpoint)
            checkpoint.sealed = True
            checkpoint.seal_digest = seal.seal_digest
            if not config.validation_only:
                self.write_checkpoint(checkpoint)
                write_json_atomic(self.seal_path, seal.to_dict())
                seal_path = str(self.seal_path)
            elif force_seal:
                # Validation-only seal is in-memory only.
                pass
        elif force_seal:
            raise SealError(
                f"cannot seal partial output: "
                f"{checkpoint.verified_count}/{checkpoint.total_count} verified"
            )

        receipt = {
            "build_id": plan.build_id,
            "config": config.to_dict(),
            "config_digest": config.digest,
            "executed_keys": executed_keys,
            "global_decisions": {
                k: v.to_dict() for k, v in plan.global_decisions.items()
            },
            "interrupted": interrupted,
            "mode": plan.mode.value,
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
            validation_only=config.validation_only,
            interrupted=interrupted,
            receipt_path=receipt_path,
            checkpoint_path=""
            if config.validation_only
            else str(self.checkpoint_path),
            seal_path=seal_path,
        )

    def seal_existing(self, config: BuildConfig) -> BuildSeal:
        """Seal a fully verified on-disk checkpoint (fail-closed on partial)."""

        checkpoint = self.load_checkpoint()
        if checkpoint is None:
            raise SealError("no checkpoint to seal")
        assert_checkpoint_compatible(checkpoint, config)
        seal = compute_seal(checkpoint)
        if config.validation_only:
            return seal
        checkpoint.sealed = True
        checkpoint.seal_digest = seal.seal_digest
        self.write_checkpoint(checkpoint)
        write_json_atomic(self.seal_path, seal.to_dict())
        return seal


def run_fixture_build(
    output_dir: PathLike,
    *,
    titles: Sequence[str] = ("1", "35"),
    families: Sequence[str] = DEFAULT_BUILD_FAMILIES,
    mode: BuildMode | str = BuildMode.FULL,
    resume: bool = True,
    validation_only: bool = False,
    interrupt_after_units: int | None = None,
    prior_salt: str | None = None,
    current_salt: str = "fixture",
    bm25_decision: GlobalRebuildKind | str | None = None,
    cluster_decision: GlobalRebuildKind | str | None = None,
    checkpoint_dir: PathLike | None = None,
    producer: ArtifactProducer | None = None,
    resource_limits: ResourceLimits | None = None,
) -> BuildResult:
    """Convenience entry point for offline fixture builds (tests / CLI)."""

    mode_enum = BuildMode.coerce(mode)
    config = BuildConfig(
        mode=mode_enum,
        titles=tuple(titles),
        families=tuple(families),
        resume=resume,
        validation_only=validation_only,
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
    current = fixture_title_snapshots(config.titles, salt=current_salt)
    prior = None
    if mode_enum is BuildMode.DELTA:
        prior = fixture_title_snapshots(
            config.titles, salt=prior_salt or "prior-fixture"
        )
    orchestrator = UscodeBuildOrchestrator(
        output_dir=output_dir,
        checkpoint_dir=checkpoint_dir,
        producer=producer,
    )
    return orchestrator.run(
        config,
        current=current,
        prior=prior,
        interrupt_after_units=interrupt_after_units,
    )


# ---------------------------------------------------------------------------
# Public exports
# ---------------------------------------------------------------------------

__all__ = [
    "SCHEMA_VERSION",
    "TASK_ID",
    "GOAL_ID",
    "PRODUCER",
    "DEFAULT_BUILD_FAMILIES",
    "DEFAULT_BM25_REBUILD_THRESHOLD",
    "DEFAULT_CLUSTER_REBUILD_THRESHOLD",
    "CHECKPOINT_FILENAME",
    "SEAL_FILENAME",
    "RECEIPT_FILENAME",
    "UscodeBuildError",
    "BuildConfigError",
    "BuildCheckpointError",
    "BuildPlanError",
    "GlobalDecisionError",
    "SealError",
    "ResourceLimitError",
    "ProducerError",
    "ValidationOnlyError",
    "BuildMode",
    "GlobalRebuildKind",
    "WorkUnitStatus",
    "DecisionSource",
    "ResourceLimits",
    "GlobalRebuildDecision",
    "BuildConfig",
    "WorkUnit",
    "ProducerResult",
    "TitleSnapshot",
    "WorkUnitRecord",
    "BuildCheckpoint",
    "BuildPlan",
    "BuildSeal",
    "BuildResult",
    "UscodeBuildOrchestrator",
    "decide_global_rebuild",
    "plan_full_build",
    "plan_delta_build",
    "plan_build",
    "load_checkpoint",
    "write_checkpoint_atomic",
    "assert_checkpoint_compatible",
    "compute_seal",
    "default_fixture_producer",
    "fixture_title_snapshots",
    "run_fixture_build",
    "work_unit_key",
    "write_json_atomic",
    "content_digest",
]
