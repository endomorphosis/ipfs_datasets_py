"""Build complete ContextCoverageManifest from verified views (SCG-011).

Pure, deterministic coverage inventory over a pre-verified ContextPack plus
semantic-state/index observations. This module never rescans a repository,
never invents graph edges, and never materializes missing source.

Normative rules:

* Every exclusion carries one closed reason, confidence, token cost, and
  graph/state binding.
* Heuristic irrelevance cannot exclude a critical dependency (fail closed).
* Exact / sufficient representations stay unexpanded: the builder attributes
  what verified views already contain and does not force raw expansion of
  exact capsules or exact raw spans that are already included.
* Identical verified inputs yield identical ``manifest_cid`` identities.
* Canonical identity uses ``software_contracts.content`` only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
import re
import unicodedata
from typing import Any, ClassVar, Final, Iterable, Mapping, Sequence

from ipfs_datasets_py.logic.software_contracts.content import (
    cid_for_structured,
    validate_cid,
    validate_structured_value,
)
from ipfs_datasets_py.logic.software_contracts.semantic_governor.audit_contracts import (
    BASIS_POINTS,
    CONTEXT_COVERAGE_MANIFEST_INTERFACE,
    MAX_EXCLUSIONS,
    MAX_GAPS,
    MAX_INCLUSIONS,
    MAX_PATH_NODES,
    MAX_TARGET_SYMBOLS,
    MAX_TOKEN_COST,
    AuditContractError,
    ContextCoverageManifest,
    CoverageGap,
    CoverageGapKind,
    CoveredArtifactKind,
    ExcludedArtifactRecord,
    ExclusionReason,
    GraphPath,
    IncludedArtifactRecord,
    InclusionKind,
    SourceSpan,
)
from ipfs_datasets_py.logic.software_contracts.semantic_governor.base import (
    AssumptionKind,
    ArtifactProvenance,
    AuthoritySource,
    ExecutionMode,
    GeneratorIdentity,
    GovernorArtifactHeader,
    GovernorAssumption,
    GovernorTerminalStatus,
    SemanticGovernorBaseError,
    reject_private_and_model_authority,
)

# ---------------------------------------------------------------------------
# Interface / schema constants
# ---------------------------------------------------------------------------

BUILD_CONTEXT_COVERAGE_MANIFEST_INTERFACE: Final[str] = (
    "build_context_coverage_manifest@1"
)
COVERAGE_BUILDER_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.semantic-governor-coverage-builder@1"
)
VERIFIED_COVERAGE_VIEW_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.semantic-governor-verified-coverage-view@1"
)
COVERAGE_INCLUSION_VIEW_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.semantic-governor-coverage-inclusion-view@1"
)
COVERAGE_EXCLUSION_VIEW_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.semantic-governor-coverage-exclusion-view@1"
)
COVERAGE_GAP_VIEW_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.semantic-governor-coverage-gap-view@1"
)

GENERATOR_ID: Final[str] = "coverage_builder"
GENERATOR_VERSION: Final[str] = "1.0.0"
PRODUCER_ID: Final[str] = "semantic_governor"
PRODUCER_VERSION: Final[str] = "1"
TOOL_ID: Final[str] = "coverage.v1"

MAX_TEXT_CHARS: Final[int] = 16_384
MAX_CID_LIST: Final[int] = 4_096
MAX_OPAQUE_DEPS: Final[int] = 4_096
MAX_ASSUMPTIONS: Final[int] = 512

# Closed analysis-confidence ranks (datasets taxonomy). Lower is better.
class AnalysisConfidenceRank(str, Enum):
    EXACT = "exact"
    CONSERVATIVE = "conservative"
    HEURISTIC = "heuristic"
    OPAQUE = "opaque"


_CONFIDENCE_RANK: Final[dict[str, int]] = {
    AnalysisConfidenceRank.EXACT.value: 0,
    AnalysisConfidenceRank.CONSERVATIVE.value: 1,
    AnalysisConfidenceRank.HEURISTIC.value: 2,
    AnalysisConfidenceRank.OPAQUE.value: 3,
}

_DEFAULT_CONFIDENCE_BP: Final[dict[str, int]] = {
    AnalysisConfidenceRank.EXACT.value: BASIS_POINTS,
    AnalysisConfidenceRank.CONSERVATIVE.value: 8_000,
    AnalysisConfidenceRank.HEURISTIC.value: 5_000,
    AnalysisConfidenceRank.OPAQUE.value: 2_000,
}

# Exclusion reasons that claim graph/cone proof and therefore require
# non-heuristic confidence when the excluded artifact is critical.
_PROOF_STYLE_EXCLUSION_REASONS: Final[frozenset[str]] = frozenset(
    {
        ExclusionReason.PROVEN_UNRELATED_BY_DEPENDENCY_GRAPH.value,
        ExclusionReason.OUTSIDE_AFFECTED_INVALIDATION_CONE.value,
    }
)

# Substitution / structural reasons admitted for critical exclusions only
# when confidence is exact or conservative (never heuristic/opaque).
_STRUCTURAL_EXCLUSION_REASONS: Final[frozenset[str]] = frozenset(
    {
        ExclusionReason.EXACT_CAPSULE_SUBSTITUTED.value,
        ExclusionReason.CONSERVATIVE_CAPSULE_SUBSTITUTED.value,
        ExclusionReason.GENERATED_FROM_INCLUDED_AUTHORITATIVE_SCHEMA.value,
        ExclusionReason.VERIFIED_IMMUTABLE_DEPENDENCY.value,
        ExclusionReason.DUPLICATE_REPRESENTATION.value,
        ExclusionReason.BUDGET_EXCEEDED_ESCALATION_REQUIRED.value,
    }
)

# Non-closed / heuristic exclusion labels that must always reject.
_HEURISTIC_EXCLUSION_LABELS: Final[frozenset[str]] = frozenset(
    {
        "heuristic",
        "heuristic_irrelevance",
        "heuristic_unrelated",
        "looks_irrelevant",
        "looks_unrelated",
        "probably_unrelated",
        "inferred_unrelated",
        "model_guessed_unrelated",
        "llm_irrelevance",
        "vibes",
        "assumed_unrelated",
    }
)

_TOKEN_RE: Final[re.Pattern[str]] = re.compile(r"^[a-z][a-z0-9_.:/+-]{0,127}$")
_REPO_PATH_RE: Final[re.Pattern[str]] = re.compile(
    r"^(?:[A-Za-z0-9_./@+-][A-Za-z0-9_./@+-]{0,1022})$"
)

# Exact inclusion kinds that must remain unexpanded when confidence is exact.
_EXACT_INCLUSION_KINDS: Final[frozenset[str]] = frozenset(
    {
        InclusionKind.RAW_SOURCE.value,
        InclusionKind.EXACT_CAPSULE.value,
    }
)


class CoverageBuilderError(SemanticGovernorBaseError):
    """Raised when coverage-manifest construction fails closed."""


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _text(value: Any, name: str, *, empty: bool = False) -> str:
    if type(value) is not str or (not empty and not value):
        raise CoverageBuilderError(f"{name} must be a nonempty string")
    if value != value.strip() or unicodedata.normalize("NFC", value) != value:
        raise CoverageBuilderError(f"{name} must be trimmed NFC text")
    if len(value) > MAX_TEXT_CHARS or any(not char.isprintable() for char in value):
        raise CoverageBuilderError(f"{name} contains invalid text")
    return value


def _optional_text(value: Any, name: str) -> str | None:
    if value is None:
        return None
    return _text(value, name)


def _token(value: Any, name: str) -> str:
    text = _text(value, name)
    if _TOKEN_RE.fullmatch(text) is None:
        raise CoverageBuilderError(
            f"{name} must be a lowercase token matching {_TOKEN_RE.pattern}"
        )
    return text


def _cid(value: Any, name: str) -> str:
    try:
        return validate_cid(value)
    except Exception as exc:
        raise CoverageBuilderError(f"{name} must be a valid CID") from exc


def _optional_cid(value: Any, name: str) -> str | None:
    if value is None:
        return None
    return _cid(value, name)


def _bool(value: Any, name: str) -> bool:
    if type(value) is not bool:
        raise CoverageBuilderError(f"{name} must be a boolean")
    return value


def _nonneg_int(value: Any, name: str) -> int:
    if type(value) is not int or isinstance(value, bool) or value < 0:
        raise CoverageBuilderError(f"{name} must be a nonnegative integer")
    return value


def _token_cost(value: Any, name: str) -> int:
    cost = _nonneg_int(value, name)
    if cost > MAX_TOKEN_COST:
        raise CoverageBuilderError(f"{name} exceeds maximum token cost")
    return cost


def _basis_points(value: Any, name: str) -> int:
    bp = _nonneg_int(value, name)
    if bp > BASIS_POINTS:
        raise CoverageBuilderError(f"{name} must be in 0..{BASIS_POINTS}")
    return bp


def _enum(value: Any, enum_type: type[Enum], name: str) -> str:
    try:
        return enum_type(value).value
    except (TypeError, ValueError) as exc:
        raise CoverageBuilderError(f"{name} has unsupported value {value!r}") from exc


def _repo_path(value: Any, name: str) -> str:
    text = _text(value, name)
    if text.startswith("/") or text.startswith("\\"):
        raise CoverageBuilderError(f"{name} must be a relative repository path")
    if ".." in text.split("/"):
        raise CoverageBuilderError(f"{name} rejects parent traversal")
    if _REPO_PATH_RE.fullmatch(text) is None:
        raise CoverageBuilderError(f"{name} is not a valid relative repository path")
    return text


def _freeze_structured(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {key: _freeze_structured(item) for key, item in value.items()}
        )
    if isinstance(value, list):
        return tuple(_freeze_structured(item) for item in value)
    return value


def _thaw_structured(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw_structured(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_structured(item) for item in value]
    return value


def _require_structured(value: Any, name: str) -> Any:
    thawed = _thaw_structured(value)
    try:
        validate_structured_value(thawed, path=name)
    except Exception as exc:
        raise CoverageBuilderError(
            f"{name} must be strict DAG-JSON without floats or host types"
        ) from exc
    reject_private_and_model_authority(thawed, path=name)
    return thawed


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise CoverageBuilderError(f"{name} must be a mapping")
    return _freeze_structured(_require_structured(dict(value), name))


def _unique_sorted_tokens(
    values: Iterable[Any],
    name: str,
    *,
    max_items: int,
) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple)):
        raise CoverageBuilderError(f"{name} must be a list")
    ordered = tuple(sorted(_token(value, name) for value in values))
    if len(ordered) > max_items:
        raise CoverageBuilderError(f"{name} exceeds maximum length")
    if len(ordered) != len(set(ordered)):
        raise CoverageBuilderError(f"{name} must not contain duplicates")
    return ordered


def _unique_sorted_cids(values: Iterable[Any], name: str) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple)):
        raise CoverageBuilderError(f"{name} must be a list")
    ordered = tuple(sorted(_cid(value, name) for value in values))
    if len(ordered) > MAX_CID_LIST:
        raise CoverageBuilderError(f"{name} exceeds maximum length")
    if len(ordered) != len(set(ordered)):
        raise CoverageBuilderError(f"{name} must not contain duplicates")
    return ordered


def _normalize_graph_path(
    value: GraphPath | Mapping[str, Any],
    name: str = "dependency_path",
) -> GraphPath:
    if isinstance(value, GraphPath):
        return value
    if isinstance(value, Mapping):
        if "schema" in value:
            try:
                return GraphPath.from_dict(value)
            except AuditContractError as exc:
                raise CoverageBuilderError(str(exc)) from exc
        try:
            return GraphPath(
                nodes=value.get("nodes", ()),
                edge_relation=value.get("edge_relation", "depends_on"),
            )
        except AuditContractError as exc:
            raise CoverageBuilderError(str(exc)) from exc
    raise CoverageBuilderError(f"{name} must be GraphPath or mapping")


def _normalize_optional_graph_path(
    value: GraphPath | Mapping[str, Any] | None,
    name: str = "dependency_path",
) -> GraphPath | None:
    if value is None:
        return None
    return _normalize_graph_path(value, name)


def _normalize_optional_span(
    value: SourceSpan | Mapping[str, Any] | None,
    name: str = "source_span",
) -> SourceSpan | None:
    if value is None:
        return None
    if isinstance(value, SourceSpan):
        return value
    if isinstance(value, Mapping):
        try:
            if "schema" in value:
                return SourceSpan.from_dict(value)
            return SourceSpan(
                path=value.get("path", ""),
                start_line=value.get("start_line", 1),
                end_line=value.get("end_line", 1),
                start_col=value.get("start_col", 1),
                end_col=value.get("end_col", 1),
            )
        except AuditContractError as exc:
            raise CoverageBuilderError(str(exc)) from exc
    raise CoverageBuilderError(f"{name} must be SourceSpan, mapping, or null")


def _confidence_class(value: Any, name: str = "confidence") -> str:
    text = _text(value, name).lower()
    if text not in _CONFIDENCE_RANK:
        raise CoverageBuilderError(
            f"{name} must be one of {sorted(_CONFIDENCE_RANK)}; got {value!r}"
        )
    return text


def _confidence_bp_for(confidence: str, explicit: Any | None) -> int:
    if explicit is None:
        return _DEFAULT_CONFIDENCE_BP[confidence]
    return _basis_points(explicit, "confidence_bp")


# ---------------------------------------------------------------------------
# Verified view records (inputs)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CoverageInclusionView:
    """One verified inclusion already present in the ContextPack / state view."""

    artifact_id: str
    artifact_kind: CoveredArtifactKind | str
    inclusion_kind: InclusionKind | str
    token_cost: int
    confidence: str = AnalysisConfidenceRank.EXACT.value
    confidence_bp: int | None = None
    symbol_id: str | None = None
    path: str | None = None
    artifact_cid: str | None = None
    dependency_path: GraphPath | Mapping[str, Any] | None = None
    source_span: SourceSpan | Mapping[str, Any] | None = None
    notes: str | None = None
    # When true, this inclusion is a target/edit/test exact span that must
    # never be expanded or substituted away by the coverage builder.
    exact_required: bool = False

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "artifact_id",
            "artifact_kind",
            "inclusion_kind",
            "token_cost",
            "confidence",
            "confidence_bp",
            "symbol_id",
            "path",
            "artifact_cid",
            "dependency_path",
            "source_span",
            "notes",
            "exact_required",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "artifact_id", _token(self.artifact_id, "artifact_id"))
        object.__setattr__(
            self,
            "artifact_kind",
            _enum(self.artifact_kind, CoveredArtifactKind, "artifact_kind"),
        )
        object.__setattr__(
            self,
            "inclusion_kind",
            _enum(self.inclusion_kind, InclusionKind, "inclusion_kind"),
        )
        object.__setattr__(self, "token_cost", _token_cost(self.token_cost, "token_cost"))
        confidence = _confidence_class(self.confidence, "confidence")
        object.__setattr__(self, "confidence", confidence)
        object.__setattr__(
            self,
            "confidence_bp",
            _confidence_bp_for(confidence, self.confidence_bp),
        )
        if self.symbol_id is not None:
            object.__setattr__(self, "symbol_id", _token(self.symbol_id, "symbol_id"))
        if self.path is not None:
            object.__setattr__(self, "path", _repo_path(self.path, "path"))
        object.__setattr__(
            self, "artifact_cid", _optional_cid(self.artifact_cid, "artifact_cid")
        )
        object.__setattr__(
            self,
            "dependency_path",
            _normalize_optional_graph_path(self.dependency_path, "dependency_path"),
        )
        object.__setattr__(
            self,
            "source_span",
            _normalize_optional_span(self.source_span, "source_span"),
        )
        object.__setattr__(self, "notes", _optional_text(self.notes, "notes"))
        object.__setattr__(
            self, "exact_required", _bool(self.exact_required, "exact_required")
        )
        # Exact-required spans must be raw_source with exact confidence.
        if self.exact_required:
            if self.inclusion_kind != InclusionKind.RAW_SOURCE.value:
                raise CoverageBuilderError(
                    "exact_required inclusions must use inclusion_kind raw_source"
                )
            if self.confidence != AnalysisConfidenceRank.EXACT.value:
                raise CoverageBuilderError(
                    "exact_required inclusions must have exact confidence"
                )

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": COVERAGE_INCLUSION_VIEW_SCHEMA,
            "artifact_id": self.artifact_id,
            "artifact_kind": self.artifact_kind,
            "inclusion_kind": self.inclusion_kind,
            "token_cost": self.token_cost,
            "confidence": self.confidence,
            "confidence_bp": self.confidence_bp,
            "symbol_id": self.symbol_id,
            "path": self.path,
            "artifact_cid": self.artifact_cid,
            "dependency_path": (
                None
                if self.dependency_path is None
                else self.dependency_path.identity_payload()
            ),
            "source_span": (
                None if self.source_span is None else self.source_span.identity_payload()
            ),
            "notes": self.notes,
            "exact_required": self.exact_required,
        }

    def to_dict(self) -> dict[str, Any]:
        return self.identity_payload()

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "CoverageInclusionView":
        if not isinstance(data, Mapping):
            raise CoverageBuilderError("CoverageInclusionView must be a mapping")
        payload = dict(data)
        schema = payload.pop("schema", COVERAGE_INCLUSION_VIEW_SCHEMA)
        if schema != COVERAGE_INCLUSION_VIEW_SCHEMA:
            raise CoverageBuilderError(
                "unsupported CoverageInclusionView schema version"
            )
        return cls(**payload)


@dataclass(frozen=True, slots=True)
class CoverageExclusionView:
    """One candidate exclusion observed from pack + verified state views."""

    artifact_id: str
    artifact_kind: CoveredArtifactKind | str
    exclusion_reason: str
    token_cost: int
    confidence: str = AnalysisConfidenceRank.EXACT.value
    confidence_bp: int | None = None
    symbol_id: str | None = None
    path: str | None = None
    artifact_cid: str | None = None
    dependency_path: GraphPath | Mapping[str, Any] | None = None
    source_span: SourceSpan | Mapping[str, Any] | None = None
    repository_state_cid: str | None = None
    substituted_by_artifact_id: str | None = None
    critical: bool = False
    notes: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "artifact_id", _token(self.artifact_id, "artifact_id"))
        object.__setattr__(
            self,
            "artifact_kind",
            _enum(self.artifact_kind, CoveredArtifactKind, "artifact_kind"),
        )
        # Keep raw reason string for heuristic rejection before closed enum.
        if self.exclusion_reason is None or self.exclusion_reason == "":
            raise CoverageBuilderError(
                "exclusion_reason is required and must not be empty"
            )
        if type(self.exclusion_reason) is not str:
            raise CoverageBuilderError("exclusion_reason must be a string")
        reason = self.exclusion_reason.strip()
        if reason != self.exclusion_reason or unicodedata.normalize("NFC", reason) != reason:
            raise CoverageBuilderError("exclusion_reason must be trimmed NFC text")
        object.__setattr__(self, "exclusion_reason", reason)
        object.__setattr__(self, "token_cost", _token_cost(self.token_cost, "token_cost"))
        confidence = _confidence_class(self.confidence, "confidence")
        object.__setattr__(self, "confidence", confidence)
        object.__setattr__(
            self,
            "confidence_bp",
            _confidence_bp_for(confidence, self.confidence_bp),
        )
        if self.symbol_id is not None:
            object.__setattr__(self, "symbol_id", _token(self.symbol_id, "symbol_id"))
        if self.path is not None:
            object.__setattr__(self, "path", _repo_path(self.path, "path"))
        object.__setattr__(
            self, "artifact_cid", _optional_cid(self.artifact_cid, "artifact_cid")
        )
        object.__setattr__(
            self,
            "dependency_path",
            _normalize_optional_graph_path(self.dependency_path, "dependency_path"),
        )
        object.__setattr__(
            self,
            "source_span",
            _normalize_optional_span(self.source_span, "source_span"),
        )
        object.__setattr__(
            self,
            "repository_state_cid",
            _optional_cid(self.repository_state_cid, "repository_state_cid"),
        )
        if self.substituted_by_artifact_id is not None:
            object.__setattr__(
                self,
                "substituted_by_artifact_id",
                _token(self.substituted_by_artifact_id, "substituted_by_artifact_id"),
            )
        object.__setattr__(self, "critical", _bool(self.critical, "critical"))
        object.__setattr__(self, "notes", _optional_text(self.notes, "notes"))

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": COVERAGE_EXCLUSION_VIEW_SCHEMA,
            "artifact_id": self.artifact_id,
            "artifact_kind": self.artifact_kind,
            "exclusion_reason": self.exclusion_reason,
            "token_cost": self.token_cost,
            "confidence": self.confidence,
            "confidence_bp": self.confidence_bp,
            "symbol_id": self.symbol_id,
            "path": self.path,
            "artifact_cid": self.artifact_cid,
            "dependency_path": (
                None
                if self.dependency_path is None
                else self.dependency_path.identity_payload()
            ),
            "source_span": (
                None if self.source_span is None else self.source_span.identity_payload()
            ),
            "repository_state_cid": self.repository_state_cid,
            "substituted_by_artifact_id": self.substituted_by_artifact_id,
            "critical": self.critical,
            "notes": self.notes,
        }

    def to_dict(self) -> dict[str, Any]:
        return self.identity_payload()

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "CoverageExclusionView":
        if not isinstance(data, Mapping):
            raise CoverageBuilderError("CoverageExclusionView must be a mapping")
        payload = dict(data)
        schema = payload.pop("schema", COVERAGE_EXCLUSION_VIEW_SCHEMA)
        if schema != COVERAGE_EXCLUSION_VIEW_SCHEMA:
            raise CoverageBuilderError(
                "unsupported CoverageExclusionView schema version"
            )
        return cls(**payload)


@dataclass(frozen=True, slots=True)
class CoverageGapView:
    """One known coverage gap already visible on the verified views."""

    gap_id: str
    gap_kind: CoverageGapKind | str
    description: str
    artifact_id: str | None = None
    path: str | None = None
    critical: bool = False
    supporting_cids: Sequence[str] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "gap_id", _token(self.gap_id, "gap_id"))
        object.__setattr__(
            self, "gap_kind", _enum(self.gap_kind, CoverageGapKind, "gap_kind")
        )
        object.__setattr__(self, "description", _text(self.description, "description"))
        if self.artifact_id is not None:
            object.__setattr__(
                self, "artifact_id", _token(self.artifact_id, "artifact_id")
            )
        if self.path is not None:
            object.__setattr__(self, "path", _repo_path(self.path, "path"))
        object.__setattr__(self, "critical", _bool(self.critical, "critical"))
        object.__setattr__(
            self,
            "supporting_cids",
            _unique_sorted_cids(list(self.supporting_cids), "supporting_cids"),
        )

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": COVERAGE_GAP_VIEW_SCHEMA,
            "gap_id": self.gap_id,
            "gap_kind": self.gap_kind,
            "description": self.description,
            "artifact_id": self.artifact_id,
            "path": self.path,
            "critical": self.critical,
            "supporting_cids": list(self.supporting_cids),
        }

    def to_dict(self) -> dict[str, Any]:
        return self.identity_payload()

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "CoverageGapView":
        if not isinstance(data, Mapping):
            raise CoverageBuilderError("CoverageGapView must be a mapping")
        payload = dict(data)
        schema = payload.pop("schema", COVERAGE_GAP_VIEW_SCHEMA)
        if schema != COVERAGE_GAP_VIEW_SCHEMA:
            raise CoverageBuilderError("unsupported CoverageGapView schema version")
        return cls(**payload)


@dataclass(frozen=True, slots=True)
class VerifiedCoverageView:
    """Verified ContextPack + semantic-state/index observations for coverage.

    Callers must supply already-verified facts. This record does not open
    storage, rescan trees, or invent missing edges/source.
    """

    repository_state_cid: str
    context_pack_cid: str
    verification_bundle_cid: str
    target_symbol_ids: Sequence[str]
    inclusions: Sequence[CoverageInclusionView | Mapping[str, Any]]
    exclusions: Sequence[CoverageExclusionView | Mapping[str, Any]] = ()
    context_budget_tokens: int = 0
    minimum_safe_tokens: int | None = None
    known_gaps: Sequence[CoverageGapView | Mapping[str, Any]] = ()
    opaque_dependency_ids: Sequence[str] = ()
    dependency_paths: Sequence[GraphPath | Mapping[str, Any]] = ()
    policy_cid: str | None = None
    assumption_statements: Sequence[str] = ()
    notes: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    # When true, every target_symbol_id must appear on at least one inclusion.
    require_target_inclusions: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "repository_state_cid",
            _cid(self.repository_state_cid, "repository_state_cid"),
        )
        object.__setattr__(
            self, "context_pack_cid", _cid(self.context_pack_cid, "context_pack_cid")
        )
        object.__setattr__(
            self,
            "verification_bundle_cid",
            _cid(self.verification_bundle_cid, "verification_bundle_cid"),
        )
        targets = _unique_sorted_tokens(
            list(self.target_symbol_ids),
            "target_symbol_ids",
            max_items=MAX_TARGET_SYMBOLS,
        )
        if not targets:
            raise CoverageBuilderError("target_symbol_ids must not be empty")
        object.__setattr__(self, "target_symbol_ids", targets)

        if not isinstance(self.inclusions, (list, tuple)):
            raise CoverageBuilderError("inclusions must be a list")
        if len(self.inclusions) > MAX_INCLUSIONS:
            raise CoverageBuilderError("inclusions exceeds maximum length")
        if not self.inclusions:
            raise CoverageBuilderError("inclusions must not be empty")
        inclusions = tuple(
            sorted(
                (_normalize_inclusion_view(item) for item in self.inclusions),
                key=lambda item: item.artifact_id,
            )
        )
        inclusion_ids = [item.artifact_id for item in inclusions]
        if len(inclusion_ids) != len(set(inclusion_ids)):
            raise CoverageBuilderError(
                "inclusions must not contain duplicate artifact_id"
            )
        object.__setattr__(self, "inclusions", inclusions)

        if not isinstance(self.exclusions, (list, tuple)):
            raise CoverageBuilderError("exclusions must be a list")
        if len(self.exclusions) > MAX_EXCLUSIONS:
            raise CoverageBuilderError("exclusions exceeds maximum length")
        exclusions = tuple(
            sorted(
                (_normalize_exclusion_view(item) for item in self.exclusions),
                key=lambda item: item.artifact_id,
            )
        )
        exclusion_ids = [item.artifact_id for item in exclusions]
        if len(exclusion_ids) != len(set(exclusion_ids)):
            raise CoverageBuilderError(
                "exclusions must not contain duplicate artifact_id"
            )
        # Inclusion and exclusion artifact ids must be disjoint.
        overlap = set(inclusion_ids) & set(exclusion_ids)
        if overlap:
            raise CoverageBuilderError(
                "artifact_id cannot be both included and excluded: "
                f"{sorted(overlap)[0]!r}"
            )
        object.__setattr__(self, "exclusions", exclusions)

        if not isinstance(self.known_gaps, (list, tuple)):
            raise CoverageBuilderError("known_gaps must be a list")
        if len(self.known_gaps) > MAX_GAPS:
            raise CoverageBuilderError("known_gaps exceeds maximum length")
        gaps = tuple(
            sorted(
                (_normalize_gap_view(item) for item in self.known_gaps),
                key=lambda gap: gap.gap_id,
            )
        )
        gap_ids = [gap.gap_id for gap in gaps]
        if len(gap_ids) != len(set(gap_ids)):
            raise CoverageBuilderError("known_gaps must not contain duplicate gap_id")
        object.__setattr__(self, "known_gaps", gaps)

        object.__setattr__(
            self,
            "opaque_dependency_ids",
            _unique_sorted_tokens(
                list(self.opaque_dependency_ids),
                "opaque_dependency_ids",
                max_items=MAX_OPAQUE_DEPS,
            ),
        )

        if not isinstance(self.dependency_paths, (list, tuple)):
            raise CoverageBuilderError("dependency_paths must be a list")
        if len(self.dependency_paths) > MAX_PATH_NODES:
            raise CoverageBuilderError("dependency_paths exceeds maximum length")
        paths = tuple(
            sorted(
                (
                    _normalize_graph_path(item, "dependency_paths")
                    for item in self.dependency_paths
                ),
                key=lambda path: (path.edge_relation, tuple(path.nodes)),
            )
        )
        object.__setattr__(self, "dependency_paths", paths)

        budget = _token_cost(self.context_budget_tokens, "context_budget_tokens")
        object.__setattr__(self, "context_budget_tokens", budget)
        if self.minimum_safe_tokens is not None:
            object.__setattr__(
                self,
                "minimum_safe_tokens",
                _token_cost(self.minimum_safe_tokens, "minimum_safe_tokens"),
            )
        object.__setattr__(self, "policy_cid", _optional_cid(self.policy_cid, "policy_cid"))

        if not isinstance(self.assumption_statements, (list, tuple)):
            raise CoverageBuilderError("assumption_statements must be a list")
        if len(self.assumption_statements) > MAX_ASSUMPTIONS:
            raise CoverageBuilderError("assumption_statements exceeds maximum length")
        statements = tuple(
            _text(item, "assumption_statements") for item in self.assumption_statements
        )
        object.__setattr__(self, "assumption_statements", statements)
        object.__setattr__(self, "notes", _optional_text(self.notes, "notes"))
        object.__setattr__(self, "metadata", _mapping(self.metadata, "metadata"))
        object.__setattr__(
            self,
            "require_target_inclusions",
            _bool(self.require_target_inclusions, "require_target_inclusions"),
        )

        if self.require_target_inclusions:
            covered_symbols = {
                item.symbol_id for item in inclusions if item.symbol_id is not None
            }
            missing = [sym for sym in targets if sym not in covered_symbols]
            if missing:
                raise CoverageBuilderError(
                    "every target_symbol_id must appear on an inclusion; "
                    f"missing {missing[0]!r}"
                )

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": VERIFIED_COVERAGE_VIEW_SCHEMA,
            "repository_state_cid": self.repository_state_cid,
            "context_pack_cid": self.context_pack_cid,
            "verification_bundle_cid": self.verification_bundle_cid,
            "target_symbol_ids": list(self.target_symbol_ids),
            "inclusions": [item.identity_payload() for item in self.inclusions],
            "exclusions": [item.identity_payload() for item in self.exclusions],
            "context_budget_tokens": self.context_budget_tokens,
            "minimum_safe_tokens": self.minimum_safe_tokens,
            "known_gaps": [item.identity_payload() for item in self.known_gaps],
            "opaque_dependency_ids": list(self.opaque_dependency_ids),
            "dependency_paths": [
                item.identity_payload() for item in self.dependency_paths
            ],
            "policy_cid": self.policy_cid,
            "assumption_statements": list(self.assumption_statements),
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
            "require_target_inclusions": self.require_target_inclusions,
        }

    @property
    def view_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        payload = self.identity_payload()
        payload["view_cid"] = self.view_cid
        return payload


def _normalize_inclusion_view(
    value: CoverageInclusionView | Mapping[str, Any],
) -> CoverageInclusionView:
    if isinstance(value, CoverageInclusionView):
        return value
    if isinstance(value, Mapping):
        if value.get("schema") == COVERAGE_INCLUSION_VIEW_SCHEMA:
            return CoverageInclusionView.from_dict(value)
        return CoverageInclusionView(
            artifact_id=value.get("artifact_id", ""),
            artifact_kind=value.get("artifact_kind", ""),
            inclusion_kind=value.get("inclusion_kind", ""),
            token_cost=value.get("token_cost", 0),
            confidence=value.get("confidence", AnalysisConfidenceRank.EXACT.value),
            confidence_bp=value.get("confidence_bp"),
            symbol_id=value.get("symbol_id"),
            path=value.get("path"),
            artifact_cid=value.get("artifact_cid"),
            dependency_path=value.get("dependency_path"),
            source_span=value.get("source_span"),
            notes=value.get("notes"),
            exact_required=value.get("exact_required", False),
        )
    raise CoverageBuilderError(
        "inclusions entries must be CoverageInclusionView or mapping"
    )


def _normalize_exclusion_view(
    value: CoverageExclusionView | Mapping[str, Any],
) -> CoverageExclusionView:
    if isinstance(value, CoverageExclusionView):
        return value
    if isinstance(value, Mapping):
        if value.get("schema") == COVERAGE_EXCLUSION_VIEW_SCHEMA:
            return CoverageExclusionView.from_dict(value)
        if "exclusion_reason" not in value or value.get("exclusion_reason") in (
            None,
            "",
        ):
            raise CoverageBuilderError(
                "exclusion_reason is required and must not be empty"
            )
        return CoverageExclusionView(
            artifact_id=value.get("artifact_id", ""),
            artifact_kind=value.get("artifact_kind", ""),
            exclusion_reason=value["exclusion_reason"],
            token_cost=value.get("token_cost", 0),
            confidence=value.get("confidence", AnalysisConfidenceRank.EXACT.value),
            confidence_bp=value.get("confidence_bp"),
            symbol_id=value.get("symbol_id"),
            path=value.get("path"),
            artifact_cid=value.get("artifact_cid"),
            dependency_path=value.get("dependency_path"),
            source_span=value.get("source_span"),
            repository_state_cid=value.get("repository_state_cid"),
            substituted_by_artifact_id=value.get("substituted_by_artifact_id"),
            critical=value.get("critical", False),
            notes=value.get("notes"),
        )
    raise CoverageBuilderError(
        "exclusions entries must be CoverageExclusionView or mapping"
    )


def _normalize_gap_view(
    value: CoverageGapView | Mapping[str, Any],
) -> CoverageGapView:
    if isinstance(value, CoverageGapView):
        return value
    if isinstance(value, Mapping):
        if value.get("schema") == COVERAGE_GAP_VIEW_SCHEMA:
            return CoverageGapView.from_dict(value)
        return CoverageGapView(
            gap_id=value.get("gap_id", ""),
            gap_kind=value.get("gap_kind", ""),
            description=value.get("description", ""),
            artifact_id=value.get("artifact_id"),
            path=value.get("path"),
            critical=value.get("critical", False),
            supporting_cids=value.get("supporting_cids", ()),
        )
    raise CoverageBuilderError("known_gaps entries must be CoverageGapView or mapping")


# ---------------------------------------------------------------------------
# Exclusion admission (critical heuristic rejection)
# ---------------------------------------------------------------------------


def _is_heuristic_exclusion_label(reason: str) -> bool:
    lowered = reason.lower().strip()
    if lowered in _HEURISTIC_EXCLUSION_LABELS:
        return True
    if "heuristic" in lowered:
        return True
    if lowered.startswith("looks_") or lowered.startswith("probably_"):
        return True
    return False


def assert_exclusion_admissible(exclusion: CoverageExclusionView) -> str:
    """Validate one exclusion candidate; return the closed reason value.

    Critical heuristic exclusion always rejects. Proof-style reasons on
    critical artifacts require exact confidence. Structural substitutions on
    critical artifacts require exact or conservative confidence.
    """

    reason = exclusion.exclusion_reason
    if _is_heuristic_exclusion_label(reason):
        raise CoverageBuilderError(
            "critical heuristic exclusion rejects: "
            f"exclusion_reason {reason!r} is not an admitted closed reason"
            if exclusion.critical
            else f"heuristic exclusion reason {reason!r} is not admitted"
        )

    try:
        closed = ExclusionReason(reason).value
    except ValueError as exc:
        raise CoverageBuilderError(
            f"exclusion_reason has unsupported value {reason!r}"
        ) from exc

    confidence = exclusion.confidence
    critical = exclusion.critical

    if critical and confidence in {
        AnalysisConfidenceRank.HEURISTIC.value,
        AnalysisConfidenceRank.OPAQUE.value,
    }:
        raise CoverageBuilderError(
            "critical heuristic exclusion rejects: critical dependency "
            f"{exclusion.artifact_id!r} cannot be excluded under "
            f"{confidence} confidence"
        )

    if critical and closed in _PROOF_STYLE_EXCLUSION_REASONS:
        if confidence != AnalysisConfidenceRank.EXACT.value:
            raise CoverageBuilderError(
                "critical heuristic exclusion rejects: proof-style reason "
                f"{closed!r} on critical dependency requires exact confidence"
            )
        if exclusion.confidence_bp < BASIS_POINTS:
            raise CoverageBuilderError(
                "critical heuristic exclusion rejects: proof-style reason "
                f"{closed!r} on critical dependency requires full confidence_bp"
            )
        if exclusion.dependency_path is None:
            raise CoverageBuilderError(
                "critical proof-style exclusion requires dependency_path binding"
            )

    if critical and closed in _STRUCTURAL_EXCLUSION_REASONS:
        if confidence not in {
            AnalysisConfidenceRank.EXACT.value,
            AnalysisConfidenceRank.CONSERVATIVE.value,
        }:
            raise CoverageBuilderError(
                "critical heuristic exclusion rejects: structural reason "
                f"{closed!r} requires exact or conservative confidence"
            )

    if closed in {
        ExclusionReason.EXACT_CAPSULE_SUBSTITUTED.value,
        ExclusionReason.CONSERVATIVE_CAPSULE_SUBSTITUTED.value,
    }:
        if exclusion.substituted_by_artifact_id is None:
            raise CoverageBuilderError(
                f"exclusion_reason {closed!r} requires substituted_by_artifact_id"
            )

    if (
        exclusion.dependency_path is None
        and exclusion.repository_state_cid is None
    ):
        raise CoverageBuilderError(
            "exclusion must be graph/state bound via dependency_path "
            "or repository_state_cid"
        )

    return closed


# ---------------------------------------------------------------------------
# Manifest construction helpers
# ---------------------------------------------------------------------------


def _sort_inclusions(
    items: Sequence[CoverageInclusionView],
) -> tuple[CoverageInclusionView, ...]:
    return tuple(sorted(items, key=lambda item: item.artifact_id))


def _sort_exclusions(
    items: Sequence[CoverageExclusionView],
) -> tuple[CoverageExclusionView, ...]:
    return tuple(sorted(items, key=lambda item: item.artifact_id))


def _sort_paths(paths: Sequence[GraphPath]) -> tuple[GraphPath, ...]:
    return tuple(
        sorted(
            paths,
            key=lambda path: (path.edge_relation, tuple(path.nodes)),
        )
    )


def _to_included_record(view: CoverageInclusionView) -> IncludedArtifactRecord:
    try:
        return IncludedArtifactRecord(
            artifact_id=view.artifact_id,
            artifact_kind=view.artifact_kind,
            inclusion_kind=view.inclusion_kind,
            token_cost=view.token_cost,
            symbol_id=view.symbol_id,
            path=view.path,
            artifact_cid=view.artifact_cid,
            confidence_bp=view.confidence_bp,
            dependency_path=view.dependency_path,
            source_span=view.source_span,
            notes=view.notes,
        )
    except AuditContractError as exc:
        raise CoverageBuilderError(str(exc)) from exc


def _to_excluded_record(
    view: CoverageExclusionView,
    closed_reason: str,
    *,
    repository_state_cid: str,
) -> ExcludedArtifactRecord:
    state_cid = view.repository_state_cid or repository_state_cid
    try:
        return ExcludedArtifactRecord(
            artifact_id=view.artifact_id,
            artifact_kind=view.artifact_kind,
            exclusion_reason=closed_reason,
            token_cost=view.token_cost,
            confidence_bp=view.confidence_bp,
            symbol_id=view.symbol_id,
            path=view.path,
            artifact_cid=view.artifact_cid,
            dependency_path=view.dependency_path,
            source_span=view.source_span,
            repository_state_cid=state_cid,
            substituted_by_artifact_id=view.substituted_by_artifact_id,
            critical=view.critical,
            notes=view.notes,
        )
    except AuditContractError as exc:
        raise CoverageBuilderError(str(exc)) from exc


def _to_gap_record(view: CoverageGapView) -> CoverageGap:
    try:
        return CoverageGap(
            gap_id=view.gap_id,
            gap_kind=view.gap_kind,
            description=view.description,
            artifact_id=view.artifact_id,
            path=view.path,
            critical=view.critical,
            supporting_cids=view.supporting_cids,
        )
    except AuditContractError as exc:
        raise CoverageBuilderError(str(exc)) from exc


def _derive_opaque_gaps(
    opaque_ids: Sequence[str],
    existing_gap_ids: set[str],
) -> list[CoverageGap]:
    gaps: list[CoverageGap] = []
    for dep_id in opaque_ids:
        gap_id = f"opaque_{dep_id}"
        # gap_id must be a valid token; opaque ids already are tokens.
        if gap_id in existing_gap_ids:
            continue
        if len(gap_id) > 128:
            # Keep token length within validator bounds.
            gap_id = f"opaque_{cid_for_structured({'d': dep_id})[:24]}"
        gaps.append(
            CoverageGap(
                gap_id=gap_id,
                gap_kind=CoverageGapKind.OPAQUE_DEPENDENCY,
                description=f"Opaque dependency {dep_id} remains unexpanded",
                artifact_id=dep_id,
                critical=True,
            )
        )
        existing_gap_ids.add(gap_id)
    return gaps


def _derive_budget_gaps(
    exclusions: Sequence[ExcludedArtifactRecord],
    existing_gap_ids: set[str],
) -> list[CoverageGap]:
    gaps: list[CoverageGap] = []
    for item in exclusions:
        if item.exclusion_reason != (
            ExclusionReason.BUDGET_EXCEEDED_ESCALATION_REQUIRED.value
        ):
            continue
        gap_id = f"budget_{item.artifact_id}"
        if gap_id in existing_gap_ids:
            continue
        gaps.append(
            CoverageGap(
                gap_id=gap_id,
                gap_kind=CoverageGapKind.BUDGET_TRUNCATION,
                description=(
                    f"Artifact {item.artifact_id} excluded by budget overflow; "
                    "escalation required"
                ),
                artifact_id=item.artifact_id,
                path=item.path,
                critical=item.critical,
            )
        )
        existing_gap_ids.add(gap_id)
    return gaps


def _compute_minimum_safe_tokens(
    inclusions: Sequence[IncludedArtifactRecord],
    *,
    declared: int | None,
    budget: int,
) -> int:
    """Minimum-safe estimate: exact-required + exact raw/capsule costs.

    Does not invent additional expansion cost. Sufficient exact contexts
    remain unexpanded — their existing token costs are the safe baseline.
    """

    if declared is not None:
        if declared > budget:
            raise CoverageBuilderError(
                "minimum_safe_tokens must not exceed context_budget_tokens"
            )
        return declared

    # Exact raw/capsule inclusions define the unexpanded safe floor.
    safe = 0
    for item in inclusions:
        if item.inclusion_kind in _EXACT_INCLUSION_KINDS:
            safe += item.token_cost
        elif item.inclusion_kind == InclusionKind.CONSERVATIVE_CAPSULE.value:
            # Conservative still counts toward minimum-safe baseline.
            safe += item.token_cost
    if safe > budget:
        raise CoverageBuilderError(
            "derived minimum_safe_tokens exceeds context_budget_tokens"
        )
    return safe


def _build_header(
    view: VerifiedCoverageView,
    *,
    terminal_status: str,
    input_cids: Sequence[str],
    assumptions: Sequence[GovernorAssumption],
) -> GovernorArtifactHeader:
    generator = GeneratorIdentity(
        generator_id=GENERATOR_ID,
        generator_version=GENERATOR_VERSION,
        interface_id=BUILD_CONTEXT_COVERAGE_MANIFEST_INTERFACE,
    )
    provenance = ArtifactProvenance(
        producer_id=PRODUCER_ID,
        producer_version=PRODUCER_VERSION,
        execution_mode=ExecutionMode.LIVE,
        authority_source=AuthoritySource.DETERMINISTIC,
        input_cids=tuple(sorted(set(input_cids))),
        tool_ids=(TOOL_ID,),
        policy_cid=view.policy_cid,
        notes=None,
    )
    try:
        return GovernorArtifactHeader(
            artifact_kind="context_coverage_manifest",
            repository_state_cid=view.repository_state_cid,
            context_pack_cid=view.context_pack_cid,
            verification_bundle_cid=view.verification_bundle_cid,
            generator=generator,
            provenance=provenance,
            terminal_status=terminal_status,
            assumptions=assumptions,
            metadata={
                "builder_schema": COVERAGE_BUILDER_SCHEMA,
                "interface_id": BUILD_CONTEXT_COVERAGE_MANIFEST_INTERFACE,
            },
        )
    except SemanticGovernorBaseError as exc:
        raise CoverageBuilderError(str(exc)) from exc


def _build_assumptions(
    view: VerifiedCoverageView,
    *,
    inclusions: Sequence[IncludedArtifactRecord],
    exclusions: Sequence[ExcludedArtifactRecord],
) -> tuple[GovernorAssumption, ...]:
    assumptions: list[GovernorAssumption] = [
        GovernorAssumption(
            assumption_id="coverage_closed",
            kind=AssumptionKind.COVERAGE,
            statement=(
                "Coverage inventory attributes only verified ContextPack and "
                "semantic-state observations; no edges or source were invented"
            ),
            supporting_cids=(view.context_pack_cid, view.repository_state_cid),
        ),
        GovernorAssumption(
            assumption_id="exact_contexts_unexpanded",
            kind=AssumptionKind.COVERAGE,
            statement=(
                "Exact and sufficient included contexts remain unexpanded; "
                "coverage does not force raw expansion of exact representations"
            ),
            supporting_cids=(view.context_pack_cid,),
        ),
    ]
    if exclusions:
        assumptions.append(
            GovernorAssumption(
                assumption_id="exclusions_closed",
                kind=AssumptionKind.EXCLUSION,
                statement=(
                    "Every exclusion carries a closed reason, confidence, cost, "
                    "and graph/state binding; critical heuristic exclusions reject"
                ),
                supporting_cids=(view.repository_state_cid,),
            )
        )
    exact_capsules = sum(
        1
        for item in inclusions
        if item.inclusion_kind == InclusionKind.EXACT_CAPSULE.value
    )
    if exact_capsules:
        assumptions.append(
            GovernorAssumption(
                assumption_id="exact_capsule_substitution",
                kind=AssumptionKind.CONFIDENCE,
                statement=(
                    f"{exact_capsules} exact capsule inclusion(s) substitute "
                    "raw dependency code without expansion"
                ),
                supporting_cids=(view.context_pack_cid,),
            )
        )
    for index, statement in enumerate(view.assumption_statements):
        assumptions.append(
            GovernorAssumption(
                assumption_id=f"view_assumption_{index:04d}",
                kind=AssumptionKind.OTHER,
                statement=statement,
                supporting_cids=(view.context_pack_cid,),
            )
        )
    return tuple(sorted(assumptions, key=lambda item: item.assumption_id))


def _assert_exact_contexts_unexpanded(
    inclusions: Sequence[CoverageInclusionView],
) -> None:
    """Guard: exact_required and exact inclusions are left as provided.

    The builder never rewrites inclusion_kind or invents additional raw
    expansions for already-sufficient exact contexts. This function documents
    and asserts that invariant over the input view.
    """

    for item in inclusions:
        if item.exact_required and item.inclusion_kind != InclusionKind.RAW_SOURCE.value:
            raise CoverageBuilderError(
                "exact_required context must remain raw_source (unexpanded)"
            )
        if (
            item.confidence == AnalysisConfidenceRank.EXACT.value
            and item.inclusion_kind == InclusionKind.EXACT_CAPSULE.value
        ):
            # Exact capsule stays exact_capsule — never silently upgraded to
            # a forced raw expansion by the coverage builder.
            continue
        if (
            item.confidence == AnalysisConfidenceRank.EXACT.value
            and item.inclusion_kind == InclusionKind.RAW_SOURCE.value
        ):
            continue


def _manifest_id_for(view: VerifiedCoverageView) -> str:
    """Deterministic short manifest id derived from the verified view identity."""

    digest = view.view_cid
    # Keep a stable lowercase token prefix + content suffix.
    suffix = digest[-24:] if len(digest) >= 24 else digest
    # CID alphabet is already lowercase base32-ish; ensure token compliance.
    cleaned = re.sub(r"[^a-z0-9_.:/+-]", "", suffix.lower())
    if not cleaned or not cleaned[0].isalpha():
        cleaned = f"m{cleaned}" if cleaned else "m0"
    return f"manifest_{cleaned}"[:128]


# ---------------------------------------------------------------------------
# Public builder
# ---------------------------------------------------------------------------


def build_context_coverage_manifest(
    view: VerifiedCoverageView | Mapping[str, Any],
    *,
    manifest_id: str | None = None,
    terminal_status: GovernorTerminalStatus | str = GovernorTerminalStatus.COMPLETE,
) -> ContextCoverageManifest:
    """Build a complete ``ContextCoverageManifest`` from verified views.

    Parameters
    ----------
    view:
        A :class:`VerifiedCoverageView` (or mapping) that already joins the
        ContextPack with verified semantic-state/index observations. The
        builder does not rescan, invent edges, or fetch missing source.
    manifest_id:
        Optional explicit manifest id. When omitted, a deterministic id is
        derived from the view identity.
    terminal_status:
        Closed terminal status for the durable header (default ``complete``).

    Returns
    -------
    ContextCoverageManifest
        Fully attributed, totals-consistent, content-addressed coverage
        inventory. Identical inputs yield identical ``manifest_cid``.

    Raises
    ------
    CoverageBuilderError
        On critical heuristic exclusion, missing bindings, inconsistent
        budgets, or other fail-closed validation failures.
    """

    if isinstance(view, Mapping):
        # Accept claim-bearing or claim-free mappings.
        payload = dict(view)
        payload.pop("view_cid", None)
        if "schema" not in payload:
            payload = {**payload, "schema": VERIFIED_COVERAGE_VIEW_SCHEMA}
        # Reconstruct via field kwargs without requiring schema key on dataclass.
        schema = payload.pop("schema", VERIFIED_COVERAGE_VIEW_SCHEMA)
        if schema != VERIFIED_COVERAGE_VIEW_SCHEMA:
            raise CoverageBuilderError(
                "unsupported VerifiedCoverageView schema version"
            )
        view = VerifiedCoverageView(**payload)
    elif not isinstance(view, VerifiedCoverageView):
        raise CoverageBuilderError(
            "view must be a VerifiedCoverageView or mapping"
        )

    _assert_exact_contexts_unexpanded(view.inclusions)

    # --- Inclusions: preserve exact contexts, attribute as given ----------
    sorted_inclusions = _sort_inclusions(view.inclusions)
    inclusion_records = tuple(_to_included_record(item) for item in sorted_inclusions)

    # --- Exclusions: admit only closed non-heuristic reasons --------------
    sorted_exclusions = _sort_exclusions(view.exclusions)
    exclusion_records: list[ExcludedArtifactRecord] = []
    for item in sorted_exclusions:
        closed = assert_exclusion_admissible(item)
        exclusion_records.append(
            _to_excluded_record(
                item,
                closed,
                repository_state_cid=view.repository_state_cid,
            )
        )
    exclusion_records_t = tuple(exclusion_records)

    # --- Gaps: carry known gaps + derived opaque/budget markers -----------
    gap_records = [_to_gap_record(item) for item in view.known_gaps]
    gap_ids = {gap.gap_id for gap in gap_records}
    gap_records.extend(_derive_opaque_gaps(view.opaque_dependency_ids, gap_ids))
    gap_records.extend(_derive_budget_gaps(exclusion_records_t, gap_ids))
    gap_records_t = tuple(sorted(gap_records, key=lambda gap: gap.gap_id))

    # --- Dependency paths (verified only; never invented) -----------------
    paths = _sort_paths(view.dependency_paths)

    # --- Totals -----------------------------------------------------------
    total_included = sum(item.token_cost for item in inclusion_records)
    total_excluded = sum(item.token_cost for item in exclusion_records_t)
    raw_count = sum(
        1
        for item in inclusion_records
        if item.inclusion_kind == InclusionKind.RAW_SOURCE.value
    )
    capsule_count = sum(
        1
        for item in inclusion_records
        if item.inclusion_kind
        in {
            InclusionKind.EXACT_CAPSULE.value,
            InclusionKind.CONSERVATIVE_CAPSULE.value,
        }
    )
    budget = view.context_budget_tokens
    if total_included > budget:
        raise CoverageBuilderError(
            "total_included_tokens must not exceed context_budget_tokens; "
            f"included={total_included} budget={budget}"
        )
    minimum_safe = _compute_minimum_safe_tokens(
        inclusion_records,
        declared=view.minimum_safe_tokens,
        budget=budget,
    )

    # --- Header / assumptions --------------------------------------------
    assumptions = _build_assumptions(
        view, inclusions=inclusion_records, exclusions=exclusion_records_t
    )
    input_cids = [
        view.repository_state_cid,
        view.context_pack_cid,
        view.verification_bundle_cid,
        view.view_cid,
    ]
    if view.policy_cid is not None:
        input_cids.append(view.policy_cid)
    header = _build_header(
        view,
        terminal_status=(
            terminal_status.value
            if isinstance(terminal_status, GovernorTerminalStatus)
            else str(terminal_status)
        ),
        input_cids=input_cids,
        assumptions=assumptions,
    )

    mid = (
        _token(manifest_id, "manifest_id")
        if manifest_id is not None
        else _manifest_id_for(view)
    )

    metadata = {
        "builder_schema": COVERAGE_BUILDER_SCHEMA,
        "view_cid": view.view_cid,
        "exact_required_count": sum(
            1 for item in sorted_inclusions if item.exact_required
        ),
        "opaque_dependency_count": len(view.opaque_dependency_ids),
    }
    # Merge caller metadata without allowing private / model authority keys.
    for key, value in _thaw_structured(view.metadata).items():
        if key in metadata:
            continue
        metadata[key] = value

    try:
        manifest = ContextCoverageManifest(
            header=header,
            manifest_id=mid,
            target_symbol_ids=view.target_symbol_ids,
            inclusions=inclusion_records,
            exclusions=exclusion_records_t,
            context_budget_tokens=budget,
            minimum_safe_tokens=minimum_safe,
            total_included_tokens=total_included,
            total_excluded_tokens=total_excluded,
            raw_inclusion_count=raw_count,
            capsule_inclusion_count=capsule_count,
            exclusion_count=len(exclusion_records_t),
            known_gaps=gap_records_t,
            opaque_dependency_ids=view.opaque_dependency_ids,
            dependency_paths=paths,
            policy_cid=view.policy_cid,
            notes=view.notes,
            metadata=metadata,
        )
    except AuditContractError as exc:
        raise CoverageBuilderError(str(exc)) from exc

    return manifest


def coverage_builder_interface_id() -> str:
    """Return the versioned public interface pin for this builder."""

    return BUILD_CONTEXT_COVERAGE_MANIFEST_INTERFACE


def admitted_exclusion_reasons() -> tuple[str, ...]:
    """Return the closed exclusion-reason vocabulary admitted by the builder."""

    return tuple(item.value for item in ExclusionReason)


def heuristic_exclusion_labels() -> tuple[str, ...]:
    """Return non-admitted heuristic exclusion labels (for tests / docs)."""

    return tuple(sorted(_HEURISTIC_EXCLUSION_LABELS))


__all__ = [
    "BUILD_CONTEXT_COVERAGE_MANIFEST_INTERFACE",
    "COVERAGE_BUILDER_SCHEMA",
    "COVERAGE_EXCLUSION_VIEW_SCHEMA",
    "COVERAGE_GAP_VIEW_SCHEMA",
    "COVERAGE_INCLUSION_VIEW_SCHEMA",
    "GENERATOR_ID",
    "GENERATOR_VERSION",
    "VERIFIED_COVERAGE_VIEW_SCHEMA",
    "AnalysisConfidenceRank",
    "CoverageBuilderError",
    "CoverageExclusionView",
    "CoverageGapView",
    "CoverageInclusionView",
    "VerifiedCoverageView",
    "admitted_exclusion_reasons",
    "assert_exclusion_admissible",
    "build_context_coverage_manifest",
    "coverage_builder_interface_id",
    "heuristic_exclusion_labels",
]
