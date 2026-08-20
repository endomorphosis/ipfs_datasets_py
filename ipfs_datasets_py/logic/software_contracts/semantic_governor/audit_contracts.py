"""Coverage, audit, omission, expansion, and decision contracts (SCG-007).

Defines closed, versioned durable models for context coverage manifests,
sufficiency claims, exclusion records, omission hypotheses/evidence, bounded
expansion plans/steps, governor decisions, run receipts, and audit cases.

Authority rules (normative):

* Every exclusion carries one closed reason, confidence, token cost, and
  graph/state binding — missing reasons fail closed.
* Paths, source spans, dependency paths, and expansion steps are hard-bounded.
* Declared totals must equal derived sums (counts and token costs).
* A verification pass alone cannot establish sufficiency.
* Canonical identity uses ``software_contracts.content`` only.
* Strict DAG-JSON (no floats); private data and model-written authority fail
  closed.
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
from ipfs_datasets_py.logic.software_contracts.semantic_governor.base import (
    ContextSufficiencyState,
    GovernorArtifactHeader,
    SemanticGovernorBaseError,
    reject_private_and_model_authority,
)

# ---------------------------------------------------------------------------
# Schema / interface constants
# ---------------------------------------------------------------------------

EXCLUDED_ARTIFACT_RECORD_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.semantic-governor-excluded-artifact@1"
)
INCLUDED_ARTIFACT_RECORD_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.semantic-governor-included-artifact@1"
)
SOURCE_SPAN_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.semantic-governor-source-span@1"
)
GRAPH_PATH_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.semantic-governor-graph-path@1"
)
COVERAGE_GAP_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.semantic-governor-coverage-gap@1"
)

CONTEXT_COVERAGE_MANIFEST_INTERFACE: Final[str] = "ContextCoverageManifest@1"
CONTEXT_COVERAGE_MANIFEST_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.semantic-governor-context-coverage-manifest@1"
)
CONTEXT_SUFFICIENCY_CLAIM_INTERFACE: Final[str] = "ContextSufficiencyClaim@1"
CONTEXT_SUFFICIENCY_CLAIM_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.semantic-governor-context-sufficiency-claim@1"
)
OMISSION_HYPOTHESIS_INTERFACE: Final[str] = "OmissionHypothesis@1"
OMISSION_HYPOTHESIS_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.semantic-governor-omission-hypothesis@1"
)
OMISSION_EVIDENCE_INTERFACE: Final[str] = "OmissionEvidence@1"
OMISSION_EVIDENCE_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.semantic-governor-omission-evidence@1"
)
CONTEXT_EXPANSION_STEP_INTERFACE: Final[str] = "ContextExpansionStep@1"
CONTEXT_EXPANSION_STEP_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.semantic-governor-context-expansion-step@1"
)
CONTEXT_EXPANSION_PLAN_INTERFACE: Final[str] = "ContextExpansionPlan@1"
CONTEXT_EXPANSION_PLAN_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.semantic-governor-context-expansion-plan@1"
)
GOVERNOR_DECISION_INTERFACE: Final[str] = "GovernorDecision@1"
GOVERNOR_DECISION_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.semantic-governor-decision@1"
)
GOVERNOR_RUN_RECEIPT_INTERFACE: Final[str] = "GovernorRunReceipt@1"
GOVERNOR_RUN_RECEIPT_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.semantic-governor-run-receipt@1"
)
COMPRESSION_AUDIT_CASE_INTERFACE: Final[str] = "CompressionAuditCase@1"
COMPRESSION_AUDIT_CASE_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.semantic-governor-compression-audit-case@1"
)

BASIS_POINTS: Final[int] = 10_000
MAX_TEXT_CHARS: Final[int] = 16_384
MAX_CID_LIST: Final[int] = 4_096
MAX_PATH_CHARS: Final[int] = 1_024
MAX_PATH_NODES: Final[int] = 256
MAX_SPAN_LINE: Final[int] = 10_000_000
MAX_SPAN_COL: Final[int] = 1_000_000
MAX_INCLUSIONS: Final[int] = 8_192
MAX_EXCLUSIONS: Final[int] = 8_192
MAX_GAPS: Final[int] = 1_024
MAX_TARGET_SYMBOLS: Final[int] = 4_096
MAX_HYPOTHESES: Final[int] = 1_024
MAX_EXPANSION_STEPS: Final[int] = 64
MAX_EVIDENCE_BASES: Final[int] = 64
MAX_REASON_CODES: Final[int] = 256
MAX_TOKEN_COST: Final[int] = 2**31 - 1

_TOKEN_RE: Final[re.Pattern[str]] = re.compile(r"^[a-z][a-z0-9_.:/+-]{0,127}$")
_TASK_ID_RE: Final[re.Pattern[str]] = re.compile(
    r"^[A-Za-z][A-Za-z0-9_.:/+-]{0,127}$"
)
# Relative repo paths only — no absolute roots, no parent traversal.
_REPO_PATH_RE: Final[re.Pattern[str]] = re.compile(
    r"^(?:[A-Za-z0-9_./@+-][A-Za-z0-9_./@+-]{0,1022})$"
)


class AuditContractError(SemanticGovernorBaseError):
    """Raised when an audit/coverage/omission/expansion contract is unsafe."""


# ---------------------------------------------------------------------------
# Closed enumerations
# ---------------------------------------------------------------------------


class ExclusionReason(str, Enum):
    """Closed raw-exclusion reasons (plan §6). Heuristic irrelevance is not admitted."""

    EXACT_CAPSULE_SUBSTITUTED = "exact_capsule_substituted"
    CONSERVATIVE_CAPSULE_SUBSTITUTED = "conservative_capsule_substituted"
    PROVEN_UNRELATED_BY_DEPENDENCY_GRAPH = "proven_unrelated_by_dependency_graph"
    OUTSIDE_AFFECTED_INVALIDATION_CONE = "outside_affected_invalidation_cone"
    GENERATED_FROM_INCLUDED_AUTHORITATIVE_SCHEMA = (
        "generated_from_included_authoritative_schema"
    )
    VERIFIED_IMMUTABLE_DEPENDENCY = "verified_immutable_dependency"
    DUPLICATE_REPRESENTATION = "duplicate_representation"
    BUDGET_EXCEEDED_ESCALATION_REQUIRED = "budget_exceeded_escalation_required"


class InclusionKind(str, Enum):
    """How an artifact is represented inside the ContextPack."""

    RAW_SOURCE = "raw_source"
    EXACT_CAPSULE = "exact_capsule"
    CONSERVATIVE_CAPSULE = "conservative_capsule"
    PROOF = "proof"
    TEST = "test"
    SCHEMA = "schema"
    CONFIGURATION = "configuration"
    FIXTURE = "fixture"
    STATE_READ = "state_read"
    STATE_WRITE = "state_write"


class CoveredArtifactKind(str, Enum):
    """Closed kinds of coverage / omission subjects."""

    SYMBOL = "symbol"
    FILE = "file"
    SCHEMA = "schema"
    FIXTURE = "fixture"
    CONFIGURATION = "configuration"
    TEST = "test"
    PROOF_OBLIGATION = "proof_obligation"
    STATE_BINDING = "state_binding"
    DEPENDENCY_EDGE = "dependency_edge"


class SufficiencyEvidenceBasis(str, Enum):
    """Evidence bases admitted when claiming context sufficiency.

    ``verification_pass`` may be recorded but alone can never establish
    ``sufficient`` or ``sufficient_with_caveats``.
    """

    COVERAGE_MANIFEST = "coverage_manifest"
    DEPENDENCY_GRAPH = "dependency_graph"
    ACCEPTANCE_MATRIX = "acceptance_matrix"
    FRESHNESS = "freshness"
    CONFIDENCE = "confidence"
    PROOF_COVERAGE = "proof_coverage"
    TEST_COVERAGE = "test_coverage"
    CALIBRATION_HISTORY = "calibration_history"
    BUDGET = "budget"
    OPAQUE_DEPENDENCY_CHECK = "opaque_dependency_check"
    INVALIDATION_OBLIGATIONS = "invalidation_obligations"
    HUMAN_REVIEW = "human_review"
    VERIFICATION_PASS = "verification_pass"


class HypothesisCause(str, Enum):
    """Closed omission-versus-reasoning cause vocabulary."""

    OMISSION = "omission"
    MODEL_INSUFFICIENCY = "model_insufficiency"
    STALE_ARTIFACT = "stale_artifact"
    POLICY_BOUNDARY = "policy_boundary"
    BUDGET_OVERFLOW = "budget_overflow"
    CONFLICTING_EVIDENCE = "conflicting_evidence"
    UNKNOWN = "unknown"


class ExpansionAction(str, Enum):
    """Closed next actions for a ranked omission hypothesis / expansion step."""

    INCLUDE_RAW_SOURCE = "include_raw_source"
    STRENGTHEN_CAPSULE = "strengthen_capsule"
    INCLUDE_SCHEMA = "include_schema"
    INCLUDE_FIXTURE = "include_fixture"
    INCLUDE_CONFIGURATION = "include_configuration"
    INCLUDE_TEST = "include_test"
    INCLUDE_PROOF = "include_proof"
    ESCALATE_ROUTE = "escalate_route"
    REQUEST_HUMAN_REVIEW = "request_human_review"
    NO_ACTION = "no_action"


class ExpansionStepStatus(str, Enum):
    """Closed status for one expansion step."""

    PLANNED = "planned"
    APPLIED = "applied"
    SKIPPED = "skipped"
    REJECTED = "rejected"
    BUDGET_EXCEEDED = "budget_exceeded"
    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"


class DecisionAction(str, Enum):
    """Closed governor decision actions."""

    ACCEPT_COMPRESSED = "accept_compressed"
    REQUIRE_EXPANSION = "require_expansion"
    RETRY_SAME_ROUTE = "retry_same_route"
    ESCALATE_FRONTIER = "escalate_frontier"
    REQUIRE_HUMAN_REVIEW = "require_human_review"
    REJECT = "reject"
    MARK_INCONCLUSIVE = "mark_inconclusive"
    MARK_STALE = "mark_stale"
    MARK_INVALID = "mark_invalid"
    EVALUATION_FAILED = "evaluation_failed"


class RouteTier(str, Enum):
    """Closed model/route tiers for decisions and receipts."""

    DETERMINISTIC = "deterministic"
    SMALL = "small"
    MEDIUM = "medium"
    FRONTIER = "frontier"
    HUMAN = "human"


class CoverageGapKind(str, Enum):
    """Closed known-gap categories on a coverage manifest."""

    OPAQUE_DEPENDENCY = "opaque_dependency"
    DYNAMIC_IMPORT = "dynamic_import"
    UNRESOLVED_INVALIDATION = "unresolved_invalidation"
    MISSING_PROOF = "missing_proof"
    MISSING_TEST = "missing_test"
    MISSING_SCHEMA = "missing_schema"
    MISSING_FIXTURE = "missing_fixture"
    MISSING_CONFIGURATION = "missing_configuration"
    BUDGET_TRUNCATION = "budget_truncation"
    STALE_CAPSULE = "stale_capsule"
    LOW_CONFIDENCE = "low_confidence"
    UNKNOWN = "unknown"


class OmissionEvidenceKind(str, Enum):
    """Closed evidence kinds supporting an omission hypothesis."""

    COUNTEREXAMPLE = "counterexample"
    DIFFERENTIAL_OUTCOME = "differential_outcome"
    VERIFICATION_FAILURE = "verification_failure"
    SELECTED_PASS_FULL_FAIL = "selected_pass_full_fail"
    PROOF_FAILURE = "proof_failure"
    STATIC_ANALYSIS = "static_analysis"
    GRAPH_PATH = "graph_path"
    EXCLUSION_RECORD = "exclusion_record"
    EXPANSION_REPAIR = "expansion_repair"
    HUMAN_REVIEW = "human_review"


# Structural bases that may support a positive sufficiency claim.
_STRUCTURAL_SUFFICIENCY_BASES: Final[frozenset[str]] = frozenset(
    {
        SufficiencyEvidenceBasis.COVERAGE_MANIFEST.value,
        SufficiencyEvidenceBasis.DEPENDENCY_GRAPH.value,
        SufficiencyEvidenceBasis.ACCEPTANCE_MATRIX.value,
        SufficiencyEvidenceBasis.FRESHNESS.value,
        SufficiencyEvidenceBasis.CONFIDENCE.value,
        SufficiencyEvidenceBasis.PROOF_COVERAGE.value,
        SufficiencyEvidenceBasis.TEST_COVERAGE.value,
        SufficiencyEvidenceBasis.CALIBRATION_HISTORY.value,
        SufficiencyEvidenceBasis.BUDGET.value,
        SufficiencyEvidenceBasis.OPAQUE_DEPENDENCY_CHECK.value,
        SufficiencyEvidenceBasis.INVALIDATION_OBLIGATIONS.value,
        SufficiencyEvidenceBasis.HUMAN_REVIEW.value,
    }
)

_POSITIVE_SUFFICIENCY_STATES: Final[frozenset[str]] = frozenset(
    {
        ContextSufficiencyState.SUFFICIENT.value,
        ContextSufficiencyState.SUFFICIENT_WITH_CAVEATS.value,
    }
)


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _text(value: Any, name: str, *, empty: bool = False) -> str:
    if type(value) is not str or (not empty and not value):
        raise AuditContractError(f"{name} must be a nonempty string")
    if value != value.strip() or unicodedata.normalize("NFC", value) != value:
        raise AuditContractError(f"{name} must be trimmed NFC text")
    if len(value) > MAX_TEXT_CHARS or any(not char.isprintable() for char in value):
        raise AuditContractError(f"{name} contains invalid text")
    return value


def _optional_text(value: Any, name: str) -> str | None:
    if value is None:
        return None
    return _text(value, name)


def _enum(value: Any, enum_type: type[Enum], name: str) -> str:
    try:
        return enum_type(value).value
    except (TypeError, ValueError) as exc:
        raise AuditContractError(f"{name} has unsupported value {value!r}") from exc


def _cid(value: Any, name: str) -> str:
    try:
        return validate_cid(value)
    except Exception as exc:
        raise AuditContractError(f"{name} must be a valid CID") from exc


def _optional_cid(value: Any, name: str) -> str | None:
    if value is None:
        return None
    return _cid(value, name)


def _token(value: Any, name: str) -> str:
    text = _text(value, name)
    if _TOKEN_RE.fullmatch(text) is None:
        raise AuditContractError(
            f"{name} must be a lowercase token matching {_TOKEN_RE.pattern}"
        )
    return text


def _task_id(value: Any, name: str = "task_id") -> str:
    text = _text(value, name)
    if _TASK_ID_RE.fullmatch(text) is None:
        raise AuditContractError(f"{name} must match {_TASK_ID_RE.pattern}")
    return text


def _nonneg_int(value: Any, name: str) -> int:
    if type(value) is not int or isinstance(value, bool) or value < 0:
        raise AuditContractError(f"{name} must be a nonnegative integer")
    return value


def _pos_int(value: Any, name: str) -> int:
    value = _nonneg_int(value, name)
    if value < 1:
        raise AuditContractError(f"{name} must be a positive integer")
    return value


def _bool(value: Any, name: str) -> bool:
    if type(value) is not bool:
        raise AuditContractError(f"{name} must be a boolean")
    return value


def _basis_points(value: Any, name: str) -> int:
    if type(value) is not int or isinstance(value, bool):
        raise AuditContractError(
            f"{name} must be an integer basis-point ratio in [0, {BASIS_POINTS}]"
        )
    if value < 0 or value > BASIS_POINTS:
        raise AuditContractError(
            f"{name} must be an integer basis-point ratio in [0, {BASIS_POINTS}]"
        )
    return value


def _token_cost(value: Any, name: str) -> int:
    cost = _nonneg_int(value, name)
    if cost > MAX_TOKEN_COST:
        raise AuditContractError(f"{name} exceeds maximum token cost")
    return cost


def _repo_path(value: Any, name: str) -> str:
    text = _text(value, name)
    if len(text) > MAX_PATH_CHARS:
        raise AuditContractError(f"{name} exceeds maximum path length")
    if text.startswith("/") or text.startswith("\\"):
        raise AuditContractError(f"{name} must be a relative repository path")
    if text.startswith("~") or ".." in text.split("/"):
        raise AuditContractError(f"{name} rejects parent traversal or home paths")
    if "\\" in text or "\x00" in text:
        raise AuditContractError(f"{name} contains invalid path characters")
    if _REPO_PATH_RE.fullmatch(text) is None:
        raise AuditContractError(f"{name} is not a bounded relative path")
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


def _closed(data: Mapping[str, Any], fields: frozenset[str], name: str) -> dict[str, Any]:
    if not isinstance(data, Mapping):
        raise AuditContractError(f"{name} must be a mapping")
    actual = set(data)
    if actual != fields:
        raise AuditContractError(
            f"{name} fields must be exactly {sorted(fields)}, got {sorted(actual)}"
        )
    return dict(data)


def _unique_sorted_cids(values: Iterable[Any], name: str) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple)):
        raise AuditContractError(f"{name} must be a list")
    ordered = tuple(sorted(_cid(value, name) for value in values))
    if len(ordered) > MAX_CID_LIST:
        raise AuditContractError(f"{name} exceeds maximum length")
    if len(ordered) != len(set(ordered)):
        raise AuditContractError(f"{name} must not contain duplicates")
    return ordered


def _unique_sorted_tokens(values: Iterable[Any], name: str, *, max_items: int) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple)):
        raise AuditContractError(f"{name} must be a list")
    ordered = tuple(sorted(_token(value, name) for value in values))
    if len(ordered) > max_items:
        raise AuditContractError(f"{name} exceeds maximum length")
    if len(ordered) != len(set(ordered)):
        raise AuditContractError(f"{name} must not contain duplicates")
    return ordered


def _require_structured(value: Any, name: str) -> Any:
    thawed = _thaw_structured(value)
    try:
        validate_structured_value(thawed, path=name)
    except Exception as exc:
        raise AuditContractError(
            f"{name} must be strict DAG-JSON without floats or host types"
        ) from exc
    try:
        reject_private_and_model_authority(thawed, path=name)
    except SemanticGovernorBaseError as exc:
        raise AuditContractError(str(exc)) from exc
    return thawed


def _mapping(value: Any, name: str, *, frozen: bool = True) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise AuditContractError(f"{name} must be a mapping")
    result = _require_structured(dict(value), name)
    return _freeze_structured(result) if frozen else result


def _header(value: Any, name: str = "header") -> GovernorArtifactHeader:
    if isinstance(value, GovernorArtifactHeader):
        return value
    if isinstance(value, Mapping):
        try:
            return GovernorArtifactHeader.from_dict(value)
        except SemanticGovernorBaseError as exc:
            raise AuditContractError(str(exc)) from exc
    raise AuditContractError(f"{name} must be GovernorArtifactHeader or mapping")


def _enum_list(
    values: Iterable[Any],
    enum_type: type[Enum],
    name: str,
    *,
    max_items: int,
    require_nonempty: bool = False,
) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple)):
        raise AuditContractError(f"{name} must be a list")
    if len(values) > max_items:
        raise AuditContractError(f"{name} exceeds maximum length")
    ordered = tuple(sorted({_enum(item, enum_type, name) for item in values}))
    if require_nonempty and not ordered:
        raise AuditContractError(f"{name} must not be empty")
    if len(ordered) != len(set(values if isinstance(values, (list, tuple)) else ordered)):
        # Duplicates after enum normalization are fine (we unique-sorted);
        # only reject if input had more entries than unique after coerce when
        # length differs solely from duplicates — already handled by set.
        pass
    return ordered


# ---------------------------------------------------------------------------
# SourceSpan / GraphPath
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SourceSpan:
    """Bounded source location; lines/columns are 1-based inclusive ranges."""

    path: str
    start_line: int
    end_line: int
    start_col: int = 1
    end_col: int = 1

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "path",
            "start_line",
            "end_line",
            "start_col",
            "end_col",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "path", _repo_path(self.path, "path"))
        start_line = _pos_int(self.start_line, "start_line")
        end_line = _pos_int(self.end_line, "end_line")
        start_col = _pos_int(self.start_col, "start_col")
        end_col = _pos_int(self.end_col, "end_col")
        if start_line > MAX_SPAN_LINE or end_line > MAX_SPAN_LINE:
            raise AuditContractError("source span lines exceed maximum bound")
        if start_col > MAX_SPAN_COL or end_col > MAX_SPAN_COL:
            raise AuditContractError("source span columns exceed maximum bound")
        if end_line < start_line:
            raise AuditContractError("end_line must be >= start_line")
        if end_line == start_line and end_col < start_col:
            raise AuditContractError("end_col must be >= start_col on same line")
        object.__setattr__(self, "start_line", start_line)
        object.__setattr__(self, "end_line", end_line)
        object.__setattr__(self, "start_col", start_col)
        object.__setattr__(self, "end_col", end_col)

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": SOURCE_SPAN_SCHEMA,
            "path": self.path,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "start_col": self.start_col,
            "end_col": self.end_col,
        }

    def to_dict(self) -> dict[str, Any]:
        return self.identity_payload()

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SourceSpan":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        if payload.pop("schema") != SOURCE_SPAN_SCHEMA:
            raise AuditContractError("unsupported SourceSpan schema version")
        return cls(
            path=payload["path"],
            start_line=payload["start_line"],
            end_line=payload["end_line"],
            start_col=payload["start_col"],
            end_col=payload["end_col"],
        )


def _normalize_optional_span(
    value: SourceSpan | Mapping[str, Any] | None,
    name: str = "source_span",
) -> SourceSpan | None:
    if value is None:
        return None
    if isinstance(value, SourceSpan):
        return value
    if isinstance(value, Mapping):
        if "schema" in value:
            return SourceSpan.from_dict(value)
        return SourceSpan(
            path=value.get("path", ""),
            start_line=value.get("start_line", 1),
            end_line=value.get("end_line", 1),
            start_col=value.get("start_col", 1),
            end_col=value.get("end_col", 1),
        )
    raise AuditContractError(f"{name} must be SourceSpan, mapping, or null")


@dataclass(frozen=True, slots=True)
class GraphPath:
    """Bounded ordered dependency-graph path of node tokens."""

    nodes: Sequence[str]
    edge_relation: str = "depends_on"

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "nodes",
            "edge_relation",
        }
    )

    def __post_init__(self) -> None:
        if not isinstance(self.nodes, (list, tuple)):
            raise AuditContractError("nodes must be a list")
        if not self.nodes:
            raise AuditContractError("graph path nodes must not be empty")
        if len(self.nodes) > MAX_PATH_NODES:
            raise AuditContractError("graph path nodes exceed maximum bound")
        nodes = tuple(_token(node, "nodes") for node in self.nodes)
        object.__setattr__(self, "nodes", nodes)
        object.__setattr__(
            self, "edge_relation", _token(self.edge_relation, "edge_relation")
        )

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": GRAPH_PATH_SCHEMA,
            "nodes": list(self.nodes),
            "edge_relation": self.edge_relation,
        }

    def to_dict(self) -> dict[str, Any]:
        return self.identity_payload()

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "GraphPath":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        if payload.pop("schema") != GRAPH_PATH_SCHEMA:
            raise AuditContractError("unsupported GraphPath schema version")
        return cls(nodes=payload["nodes"], edge_relation=payload["edge_relation"])


def _normalize_optional_graph_path(
    value: GraphPath | Mapping[str, Any] | None,
    name: str = "dependency_path",
) -> GraphPath | None:
    if value is None:
        return None
    if isinstance(value, GraphPath):
        return value
    if isinstance(value, Mapping):
        if "schema" in value:
            return GraphPath.from_dict(value)
        return GraphPath(
            nodes=value.get("nodes", ()),
            edge_relation=value.get("edge_relation", "depends_on"),
        )
    raise AuditContractError(f"{name} must be GraphPath, mapping, or null")


def _normalize_graph_paths(
    values: Sequence[GraphPath | Mapping[str, Any]],
    name: str,
) -> tuple[GraphPath, ...]:
    if not isinstance(values, (list, tuple)):
        raise AuditContractError(f"{name} must be a list")
    if len(values) > MAX_PATH_NODES:
        raise AuditContractError(f"{name} exceeds maximum length")
    paths: list[GraphPath] = []
    for item in values:
        if isinstance(item, GraphPath):
            paths.append(item)
        elif isinstance(item, Mapping):
            if "schema" in item:
                paths.append(GraphPath.from_dict(item))
            else:
                paths.append(
                    GraphPath(
                        nodes=item.get("nodes", ()),
                        edge_relation=item.get("edge_relation", "depends_on"),
                    )
                )
        else:
            raise AuditContractError(f"{name} entries must be GraphPath or mapping")
    return tuple(paths)


# ---------------------------------------------------------------------------
# Included / Excluded artifact records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class IncludedArtifactRecord:
    """One explicit inclusion in a ContextCoverageManifest."""

    artifact_id: str
    artifact_kind: CoveredArtifactKind | str
    inclusion_kind: InclusionKind | str
    token_cost: int
    symbol_id: str | None = None
    path: str | None = None
    artifact_cid: str | None = None
    confidence_bp: int = BASIS_POINTS
    dependency_path: GraphPath | Mapping[str, Any] | None = None
    source_span: SourceSpan | Mapping[str, Any] | None = None
    notes: str | None = None

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "artifact_id",
            "artifact_kind",
            "inclusion_kind",
            "token_cost",
            "symbol_id",
            "path",
            "artifact_cid",
            "confidence_bp",
            "dependency_path",
            "source_span",
            "notes",
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
        if self.symbol_id is not None:
            object.__setattr__(self, "symbol_id", _token(self.symbol_id, "symbol_id"))
        if self.path is not None:
            object.__setattr__(self, "path", _repo_path(self.path, "path"))
        object.__setattr__(
            self, "artifact_cid", _optional_cid(self.artifact_cid, "artifact_cid")
        )
        object.__setattr__(
            self, "confidence_bp", _basis_points(self.confidence_bp, "confidence_bp")
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

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": INCLUDED_ARTIFACT_RECORD_SCHEMA,
            "artifact_id": self.artifact_id,
            "artifact_kind": self.artifact_kind,
            "inclusion_kind": self.inclusion_kind,
            "token_cost": self.token_cost,
            "symbol_id": self.symbol_id,
            "path": self.path,
            "artifact_cid": self.artifact_cid,
            "confidence_bp": self.confidence_bp,
            "dependency_path": (
                None
                if self.dependency_path is None
                else self.dependency_path.identity_payload()
            ),
            "source_span": (
                None if self.source_span is None else self.source_span.identity_payload()
            ),
            "notes": self.notes,
        }

    def to_dict(self) -> dict[str, Any]:
        return self.identity_payload()

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "IncludedArtifactRecord":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        if payload.pop("schema") != INCLUDED_ARTIFACT_RECORD_SCHEMA:
            raise AuditContractError(
                "unsupported IncludedArtifactRecord schema version"
            )
        return cls(**payload)


@dataclass(frozen=True, slots=True)
class ExcludedArtifactRecord:
    """One explicit exclusion; reason, cost, confidence, and binding are required."""

    artifact_id: str
    artifact_kind: CoveredArtifactKind | str
    exclusion_reason: ExclusionReason | str
    token_cost: int
    confidence_bp: int
    symbol_id: str | None = None
    path: str | None = None
    artifact_cid: str | None = None
    dependency_path: GraphPath | Mapping[str, Any] | None = None
    source_span: SourceSpan | Mapping[str, Any] | None = None
    repository_state_cid: str | None = None
    substituted_by_artifact_id: str | None = None
    critical: bool = False
    notes: str | None = None

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "artifact_id",
            "artifact_kind",
            "exclusion_reason",
            "token_cost",
            "confidence_bp",
            "symbol_id",
            "path",
            "artifact_cid",
            "dependency_path",
            "source_span",
            "repository_state_cid",
            "substituted_by_artifact_id",
            "critical",
            "notes",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "artifact_id", _token(self.artifact_id, "artifact_id"))
        object.__setattr__(
            self,
            "artifact_kind",
            _enum(self.artifact_kind, CoveredArtifactKind, "artifact_kind"),
        )
        # Missing / empty / unknown exclusion reasons fail closed.
        if self.exclusion_reason is None or self.exclusion_reason == "":
            raise AuditContractError("exclusion_reason is required and must not be empty")
        object.__setattr__(
            self,
            "exclusion_reason",
            _enum(self.exclusion_reason, ExclusionReason, "exclusion_reason"),
        )
        object.__setattr__(self, "token_cost", _token_cost(self.token_cost, "token_cost"))
        object.__setattr__(
            self, "confidence_bp", _basis_points(self.confidence_bp, "confidence_bp")
        )
        if self.symbol_id is not None:
            object.__setattr__(self, "symbol_id", _token(self.symbol_id, "symbol_id"))
        if self.path is not None:
            object.__setattr__(self, "path", _repo_path(self.path, "path"))
        object.__setattr__(
            self, "artifact_cid", _optional_cid(self.artifact_cid, "artifact_cid")
        )
        path = _normalize_optional_graph_path(self.dependency_path, "dependency_path")
        # Exclusions must be graph/state bound (path and/or repository state).
        state_cid = _optional_cid(self.repository_state_cid, "repository_state_cid")
        if path is None and state_cid is None:
            raise AuditContractError(
                "exclusion must be graph/state bound via dependency_path "
                "or repository_state_cid"
            )
        object.__setattr__(self, "dependency_path", path)
        object.__setattr__(self, "repository_state_cid", state_cid)
        object.__setattr__(
            self,
            "source_span",
            _normalize_optional_span(self.source_span, "source_span"),
        )
        if self.substituted_by_artifact_id is not None:
            object.__setattr__(
                self,
                "substituted_by_artifact_id",
                _token(self.substituted_by_artifact_id, "substituted_by_artifact_id"),
            )
        object.__setattr__(self, "critical", _bool(self.critical, "critical"))
        # Heuristic-style critical exclusion without high-confidence closed reason.
        if self.critical and self.exclusion_reason == (
            ExclusionReason.BUDGET_EXCEEDED_ESCALATION_REQUIRED.value
        ):
            # Allowed but must not silently claim sufficiency later.
            pass
        object.__setattr__(self, "notes", _optional_text(self.notes, "notes"))

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": EXCLUDED_ARTIFACT_RECORD_SCHEMA,
            "artifact_id": self.artifact_id,
            "artifact_kind": self.artifact_kind,
            "exclusion_reason": self.exclusion_reason,
            "token_cost": self.token_cost,
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
    def from_dict(cls, data: Mapping[str, Any]) -> "ExcludedArtifactRecord":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        if payload.pop("schema") != EXCLUDED_ARTIFACT_RECORD_SCHEMA:
            raise AuditContractError(
                "unsupported ExcludedArtifactRecord schema version"
            )
        return cls(**payload)


@dataclass(frozen=True, slots=True)
class CoverageGap:
    """One known coverage gap that blocks blind sufficiency claims."""

    gap_id: str
    gap_kind: CoverageGapKind | str
    description: str
    artifact_id: str | None = None
    path: str | None = None
    critical: bool = False
    supporting_cids: Sequence[str] = ()

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "gap_id",
            "gap_kind",
            "description",
            "artifact_id",
            "path",
            "critical",
            "supporting_cids",
        }
    )

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
            "schema": COVERAGE_GAP_SCHEMA,
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
    def from_dict(cls, data: Mapping[str, Any]) -> "CoverageGap":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        if payload.pop("schema") != COVERAGE_GAP_SCHEMA:
            raise AuditContractError("unsupported CoverageGap schema version")
        return cls(**payload)


def _normalize_inclusion(
    value: IncludedArtifactRecord | Mapping[str, Any],
) -> IncludedArtifactRecord:
    if isinstance(value, IncludedArtifactRecord):
        return value
    if isinstance(value, Mapping):
        if "schema" in value:
            return IncludedArtifactRecord.from_dict(value)
        return IncludedArtifactRecord(
            artifact_id=value.get("artifact_id", ""),
            artifact_kind=value.get("artifact_kind", ""),
            inclusion_kind=value.get("inclusion_kind", ""),
            token_cost=value.get("token_cost", 0),
            symbol_id=value.get("symbol_id"),
            path=value.get("path"),
            artifact_cid=value.get("artifact_cid"),
            confidence_bp=value.get("confidence_bp", BASIS_POINTS),
            dependency_path=value.get("dependency_path"),
            source_span=value.get("source_span"),
            notes=value.get("notes"),
        )
    raise AuditContractError(
        "inclusions entries must be IncludedArtifactRecord or mapping"
    )


def _normalize_exclusion(
    value: ExcludedArtifactRecord | Mapping[str, Any],
) -> ExcludedArtifactRecord:
    if isinstance(value, ExcludedArtifactRecord):
        return value
    if isinstance(value, Mapping):
        if "schema" in value:
            return ExcludedArtifactRecord.from_dict(value)
        # Explicitly surface missing exclusion reasons rather than defaulting.
        if "exclusion_reason" not in value or value.get("exclusion_reason") in (
            None,
            "",
        ):
            raise AuditContractError(
                "exclusion_reason is required and must not be empty"
            )
        return ExcludedArtifactRecord(
            artifact_id=value.get("artifact_id", ""),
            artifact_kind=value.get("artifact_kind", ""),
            exclusion_reason=value["exclusion_reason"],
            token_cost=value.get("token_cost", 0),
            confidence_bp=value.get("confidence_bp", 0),
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
    raise AuditContractError(
        "exclusions entries must be ExcludedArtifactRecord or mapping"
    )


def _normalize_gap(value: CoverageGap | Mapping[str, Any]) -> CoverageGap:
    if isinstance(value, CoverageGap):
        return value
    if isinstance(value, Mapping):
        if "schema" in value:
            return CoverageGap.from_dict(value)
        return CoverageGap(
            gap_id=value.get("gap_id", ""),
            gap_kind=value.get("gap_kind", ""),
            description=value.get("description", ""),
            artifact_id=value.get("artifact_id"),
            path=value.get("path"),
            critical=value.get("critical", False),
            supporting_cids=value.get("supporting_cids", ()),
        )
    raise AuditContractError("known_gaps entries must be CoverageGap or mapping")


# ---------------------------------------------------------------------------
# ContextCoverageManifest
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ContextCoverageManifest:
    """Complete coverage inventory for one ContextPack (plan §6)."""

    header: GovernorArtifactHeader
    manifest_id: str
    target_symbol_ids: Sequence[str]
    inclusions: Sequence[IncludedArtifactRecord]
    exclusions: Sequence[ExcludedArtifactRecord]
    context_budget_tokens: int
    minimum_safe_tokens: int
    total_included_tokens: int
    total_excluded_tokens: int
    raw_inclusion_count: int
    capsule_inclusion_count: int
    exclusion_count: int
    known_gaps: Sequence[CoverageGap] = ()
    opaque_dependency_ids: Sequence[str] = ()
    dependency_paths: Sequence[GraphPath] = ()
    policy_cid: str | None = None
    notes: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "interface_id",
            "header",
            "manifest_id",
            "target_symbol_ids",
            "inclusions",
            "exclusions",
            "context_budget_tokens",
            "minimum_safe_tokens",
            "total_included_tokens",
            "total_excluded_tokens",
            "raw_inclusion_count",
            "capsule_inclusion_count",
            "exclusion_count",
            "known_gaps",
            "opaque_dependency_ids",
            "dependency_paths",
            "policy_cid",
            "notes",
            "metadata",
            "manifest_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "header", _header(self.header))
        if self.header.artifact_kind != "context_coverage_manifest":
            raise AuditContractError(
                "header.artifact_kind must be context_coverage_manifest"
            )
        object.__setattr__(self, "manifest_id", _token(self.manifest_id, "manifest_id"))
        targets = _unique_sorted_tokens(
            list(self.target_symbol_ids),
            "target_symbol_ids",
            max_items=MAX_TARGET_SYMBOLS,
        )
        if not targets:
            raise AuditContractError("target_symbol_ids must not be empty")
        object.__setattr__(self, "target_symbol_ids", targets)

        if not isinstance(self.inclusions, (list, tuple)):
            raise AuditContractError("inclusions must be a list")
        if len(self.inclusions) > MAX_INCLUSIONS:
            raise AuditContractError("inclusions exceeds maximum length")
        inclusions = tuple(_normalize_inclusion(item) for item in self.inclusions)
        inclusion_ids = [item.artifact_id for item in inclusions]
        if len(inclusion_ids) != len(set(inclusion_ids)):
            raise AuditContractError("inclusions must not contain duplicate artifact_id")
        object.__setattr__(self, "inclusions", inclusions)

        if not isinstance(self.exclusions, (list, tuple)):
            raise AuditContractError("exclusions must be a list")
        if len(self.exclusions) > MAX_EXCLUSIONS:
            raise AuditContractError("exclusions exceeds maximum length")
        exclusions = tuple(_normalize_exclusion(item) for item in self.exclusions)
        exclusion_ids = [item.artifact_id for item in exclusions]
        if len(exclusion_ids) != len(set(exclusion_ids)):
            raise AuditContractError("exclusions must not contain duplicate artifact_id")
        object.__setattr__(self, "exclusions", exclusions)

        if not isinstance(self.known_gaps, (list, tuple)):
            raise AuditContractError("known_gaps must be a list")
        if len(self.known_gaps) > MAX_GAPS:
            raise AuditContractError("known_gaps exceeds maximum length")
        gaps = tuple(
            sorted(
                (_normalize_gap(item) for item in self.known_gaps),
                key=lambda gap: gap.gap_id,
            )
        )
        gap_ids = [gap.gap_id for gap in gaps]
        if len(gap_ids) != len(set(gap_ids)):
            raise AuditContractError("known_gaps must not contain duplicate gap_id")
        object.__setattr__(self, "known_gaps", gaps)

        object.__setattr__(
            self,
            "opaque_dependency_ids",
            _unique_sorted_tokens(
                list(self.opaque_dependency_ids),
                "opaque_dependency_ids",
                max_items=MAX_CID_LIST,
            ),
        )
        object.__setattr__(
            self,
            "dependency_paths",
            _normalize_graph_paths(list(self.dependency_paths), "dependency_paths"),
        )
        object.__setattr__(self, "policy_cid", _optional_cid(self.policy_cid, "policy_cid"))
        object.__setattr__(self, "notes", _optional_text(self.notes, "notes"))
        object.__setattr__(self, "metadata", _mapping(self.metadata, "metadata"))

        budget = _token_cost(self.context_budget_tokens, "context_budget_tokens")
        min_safe = _token_cost(self.minimum_safe_tokens, "minimum_safe_tokens")
        total_included = _token_cost(self.total_included_tokens, "total_included_tokens")
        total_excluded = _token_cost(self.total_excluded_tokens, "total_excluded_tokens")
        raw_count = _nonneg_int(self.raw_inclusion_count, "raw_inclusion_count")
        capsule_count = _nonneg_int(
            self.capsule_inclusion_count, "capsule_inclusion_count"
        )
        exclusion_count = _nonneg_int(self.exclusion_count, "exclusion_count")
        object.__setattr__(self, "context_budget_tokens", budget)
        object.__setattr__(self, "minimum_safe_tokens", min_safe)
        object.__setattr__(self, "total_included_tokens", total_included)
        object.__setattr__(self, "total_excluded_tokens", total_excluded)
        object.__setattr__(self, "raw_inclusion_count", raw_count)
        object.__setattr__(self, "capsule_inclusion_count", capsule_count)
        object.__setattr__(self, "exclusion_count", exclusion_count)

        # --- Consistent totals (fail closed) ---
        derived_included = sum(item.token_cost for item in inclusions)
        derived_excluded = sum(item.token_cost for item in exclusions)
        if total_included != derived_included:
            raise AuditContractError(
                "total_included_tokens must equal sum of inclusion token_cost; "
                f"declared={total_included} derived={derived_included}"
            )
        if total_excluded != derived_excluded:
            raise AuditContractError(
                "total_excluded_tokens must equal sum of exclusion token_cost; "
                f"declared={total_excluded} derived={derived_excluded}"
            )
        if exclusion_count != len(exclusions):
            raise AuditContractError(
                "exclusion_count must equal len(exclusions); "
                f"declared={exclusion_count} derived={len(exclusions)}"
            )
        derived_raw = sum(
            1
            for item in inclusions
            if item.inclusion_kind == InclusionKind.RAW_SOURCE.value
        )
        derived_capsule = sum(
            1
            for item in inclusions
            if item.inclusion_kind
            in {
                InclusionKind.EXACT_CAPSULE.value,
                InclusionKind.CONSERVATIVE_CAPSULE.value,
            }
        )
        if raw_count != derived_raw:
            raise AuditContractError(
                "raw_inclusion_count must equal raw_source inclusions; "
                f"declared={raw_count} derived={derived_raw}"
            )
        if capsule_count != derived_capsule:
            raise AuditContractError(
                "capsule_inclusion_count must equal capsule inclusions; "
                f"declared={capsule_count} derived={derived_capsule}"
            )
        if total_included > budget:
            raise AuditContractError(
                "total_included_tokens must not exceed context_budget_tokens"
            )
        if min_safe > budget:
            raise AuditContractError(
                "minimum_safe_tokens must not exceed context_budget_tokens"
            )

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": CONTEXT_COVERAGE_MANIFEST_SCHEMA,
            "interface_id": CONTEXT_COVERAGE_MANIFEST_INTERFACE,
            "header": self.header.identity_payload(),
            "manifest_id": self.manifest_id,
            "target_symbol_ids": list(self.target_symbol_ids),
            "inclusions": [item.identity_payload() for item in self.inclusions],
            "exclusions": [item.identity_payload() for item in self.exclusions],
            "context_budget_tokens": self.context_budget_tokens,
            "minimum_safe_tokens": self.minimum_safe_tokens,
            "total_included_tokens": self.total_included_tokens,
            "total_excluded_tokens": self.total_excluded_tokens,
            "raw_inclusion_count": self.raw_inclusion_count,
            "capsule_inclusion_count": self.capsule_inclusion_count,
            "exclusion_count": self.exclusion_count,
            "known_gaps": [item.identity_payload() for item in self.known_gaps],
            "opaque_dependency_ids": list(self.opaque_dependency_ids),
            "dependency_paths": [
                item.identity_payload() for item in self.dependency_paths
            ],
            "policy_cid": self.policy_cid,
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
        }

    @property
    def manifest_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        value = {
            "schema": CONTEXT_COVERAGE_MANIFEST_SCHEMA,
            "interface_id": CONTEXT_COVERAGE_MANIFEST_INTERFACE,
            "header": self.header.to_dict(),
            "manifest_id": self.manifest_id,
            "target_symbol_ids": list(self.target_symbol_ids),
            "inclusions": [item.to_dict() for item in self.inclusions],
            "exclusions": [item.to_dict() for item in self.exclusions],
            "context_budget_tokens": self.context_budget_tokens,
            "minimum_safe_tokens": self.minimum_safe_tokens,
            "total_included_tokens": self.total_included_tokens,
            "total_excluded_tokens": self.total_excluded_tokens,
            "raw_inclusion_count": self.raw_inclusion_count,
            "capsule_inclusion_count": self.capsule_inclusion_count,
            "exclusion_count": self.exclusion_count,
            "known_gaps": [item.to_dict() for item in self.known_gaps],
            "opaque_dependency_ids": list(self.opaque_dependency_ids),
            "dependency_paths": [item.to_dict() for item in self.dependency_paths],
            "policy_cid": self.policy_cid,
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
            "manifest_cid": self.manifest_cid,
        }
        return value

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ContextCoverageManifest":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("manifest_cid")
        if payload.pop("schema") != CONTEXT_COVERAGE_MANIFEST_SCHEMA:
            raise AuditContractError(
                "unsupported ContextCoverageManifest schema version"
            )
        if payload.pop("interface_id") != CONTEXT_COVERAGE_MANIFEST_INTERFACE:
            raise AuditContractError(
                "unsupported ContextCoverageManifest interface_id"
            )
        result = cls(
            header=payload["header"],
            manifest_id=payload["manifest_id"],
            target_symbol_ids=payload["target_symbol_ids"],
            inclusions=payload["inclusions"],
            exclusions=payload["exclusions"],
            context_budget_tokens=payload["context_budget_tokens"],
            minimum_safe_tokens=payload["minimum_safe_tokens"],
            total_included_tokens=payload["total_included_tokens"],
            total_excluded_tokens=payload["total_excluded_tokens"],
            raw_inclusion_count=payload["raw_inclusion_count"],
            capsule_inclusion_count=payload["capsule_inclusion_count"],
            exclusion_count=payload["exclusion_count"],
            known_gaps=payload["known_gaps"],
            opaque_dependency_ids=payload["opaque_dependency_ids"],
            dependency_paths=payload["dependency_paths"],
            policy_cid=payload["policy_cid"],
            notes=payload["notes"],
            metadata=payload["metadata"],
        )
        if claimed != result.manifest_cid:
            raise AuditContractError(
                "ContextCoverageManifest manifest_cid does not verify"
            )
        return result


# ---------------------------------------------------------------------------
# ContextSufficiencyClaim
# ---------------------------------------------------------------------------


def assert_sufficiency_not_verification_only(
    sufficiency_state: str | ContextSufficiencyState,
    evidence_bases: Sequence[str | SufficiencyEvidenceBasis],
) -> None:
    """Reject positive sufficiency supported only by verification_pass."""

    state = (
        sufficiency_state.value
        if isinstance(sufficiency_state, ContextSufficiencyState)
        else str(sufficiency_state)
    )
    state = _enum(state, ContextSufficiencyState, "sufficiency_state")
    bases = [
        item.value if isinstance(item, SufficiencyEvidenceBasis) else str(item)
        for item in evidence_bases
    ]
    bases = [_enum(item, SufficiencyEvidenceBasis, "evidence_bases") for item in bases]
    if state not in _POSITIVE_SUFFICIENCY_STATES:
        return
    if not bases:
        raise AuditContractError(
            "positive sufficiency claims require nonempty evidence_bases"
        )
    structural = [base for base in bases if base in _STRUCTURAL_SUFFICIENCY_BASES]
    if not structural:
        raise AuditContractError(
            "verification pass alone cannot establish sufficiency; "
            "require structural coverage/graph/acceptance evidence"
        )


@dataclass(frozen=True, slots=True)
class ContextSufficiencyClaim:
    """Pre-execution sufficiency judgment bound to coverage evidence."""

    header: GovernorArtifactHeader
    claim_id: str
    sufficiency_state: ContextSufficiencyState | str
    evidence_bases: Sequence[SufficiencyEvidenceBasis | str]
    coverage_manifest_cid: str
    route_tier: RouteTier | str
    task_class: str
    risk_class: str
    confidence_bp: int
    verification_passed: bool = False
    blocking_reason_codes: Sequence[str] = ()
    known_gap_ids: Sequence[str] = ()
    policy_cid: str | None = None
    notes: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "interface_id",
            "header",
            "claim_id",
            "sufficiency_state",
            "evidence_bases",
            "coverage_manifest_cid",
            "route_tier",
            "task_class",
            "risk_class",
            "confidence_bp",
            "verification_passed",
            "blocking_reason_codes",
            "known_gap_ids",
            "policy_cid",
            "notes",
            "metadata",
            "claim_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "header", _header(self.header))
        if self.header.artifact_kind != "context_sufficiency_claim":
            raise AuditContractError(
                "header.artifact_kind must be context_sufficiency_claim"
            )
        object.__setattr__(self, "claim_id", _token(self.claim_id, "claim_id"))
        state = _enum(
            self.sufficiency_state, ContextSufficiencyState, "sufficiency_state"
        )
        object.__setattr__(self, "sufficiency_state", state)
        bases = _enum_list(
            list(self.evidence_bases),
            SufficiencyEvidenceBasis,
            "evidence_bases",
            max_items=MAX_EVIDENCE_BASES,
            require_nonempty=True,
        )
        object.__setattr__(self, "evidence_bases", bases)
        assert_sufficiency_not_verification_only(state, bases)
        object.__setattr__(
            self,
            "coverage_manifest_cid",
            _cid(self.coverage_manifest_cid, "coverage_manifest_cid"),
        )
        object.__setattr__(
            self, "route_tier", _enum(self.route_tier, RouteTier, "route_tier")
        )
        object.__setattr__(self, "task_class", _token(self.task_class, "task_class"))
        object.__setattr__(self, "risk_class", _token(self.risk_class, "risk_class"))
        object.__setattr__(
            self, "confidence_bp", _basis_points(self.confidence_bp, "confidence_bp")
        )
        object.__setattr__(
            self,
            "verification_passed",
            _bool(self.verification_passed, "verification_passed"),
        )
        # verification_passed alone still cannot make positive sufficiency.
        if (
            state in _POSITIVE_SUFFICIENCY_STATES
            and self.verification_passed
            and bases == (SufficiencyEvidenceBasis.VERIFICATION_PASS.value,)
        ):
            raise AuditContractError(
                "verification pass alone cannot establish sufficiency"
            )
        object.__setattr__(
            self,
            "blocking_reason_codes",
            _unique_sorted_tokens(
                list(self.blocking_reason_codes),
                "blocking_reason_codes",
                max_items=MAX_REASON_CODES,
            ),
        )
        object.__setattr__(
            self,
            "known_gap_ids",
            _unique_sorted_tokens(
                list(self.known_gap_ids),
                "known_gap_ids",
                max_items=MAX_GAPS,
            ),
        )
        object.__setattr__(self, "policy_cid", _optional_cid(self.policy_cid, "policy_cid"))
        object.__setattr__(self, "notes", _optional_text(self.notes, "notes"))
        object.__setattr__(self, "metadata", _mapping(self.metadata, "metadata"))

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": CONTEXT_SUFFICIENCY_CLAIM_SCHEMA,
            "interface_id": CONTEXT_SUFFICIENCY_CLAIM_INTERFACE,
            "header": self.header.identity_payload(),
            "claim_id": self.claim_id,
            "sufficiency_state": self.sufficiency_state,
            "evidence_bases": list(self.evidence_bases),
            "coverage_manifest_cid": self.coverage_manifest_cid,
            "route_tier": self.route_tier,
            "task_class": self.task_class,
            "risk_class": self.risk_class,
            "confidence_bp": self.confidence_bp,
            "verification_passed": self.verification_passed,
            "blocking_reason_codes": list(self.blocking_reason_codes),
            "known_gap_ids": list(self.known_gap_ids),
            "policy_cid": self.policy_cid,
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
        }

    @property
    def claim_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": CONTEXT_SUFFICIENCY_CLAIM_SCHEMA,
            "interface_id": CONTEXT_SUFFICIENCY_CLAIM_INTERFACE,
            "header": self.header.to_dict(),
            "claim_id": self.claim_id,
            "sufficiency_state": self.sufficiency_state,
            "evidence_bases": list(self.evidence_bases),
            "coverage_manifest_cid": self.coverage_manifest_cid,
            "route_tier": self.route_tier,
            "task_class": self.task_class,
            "risk_class": self.risk_class,
            "confidence_bp": self.confidence_bp,
            "verification_passed": self.verification_passed,
            "blocking_reason_codes": list(self.blocking_reason_codes),
            "known_gap_ids": list(self.known_gap_ids),
            "policy_cid": self.policy_cid,
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
            "claim_cid": self.claim_cid,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ContextSufficiencyClaim":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("claim_cid")
        if payload.pop("schema") != CONTEXT_SUFFICIENCY_CLAIM_SCHEMA:
            raise AuditContractError(
                "unsupported ContextSufficiencyClaim schema version"
            )
        if payload.pop("interface_id") != CONTEXT_SUFFICIENCY_CLAIM_INTERFACE:
            raise AuditContractError(
                "unsupported ContextSufficiencyClaim interface_id"
            )
        result = cls(**payload)
        if claimed != result.claim_cid:
            raise AuditContractError(
                "ContextSufficiencyClaim claim_cid does not verify"
            )
        return result


# ---------------------------------------------------------------------------
# OmissionHypothesis / OmissionEvidence
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class OmissionHypothesis:
    """Ranked hypothesis that an excluded/missing artifact caused a failure."""

    header: GovernorArtifactHeader
    hypothesis_id: str
    cause: HypothesisCause | str
    subject_artifact_id: str
    subject_kind: CoveredArtifactKind | str
    rank: int
    expected_relevance_bp: int
    inclusion_cost_tokens: int
    confidence_bp: int
    expansion_action: ExpansionAction | str
    exclusion_reason: ExclusionReason | str | None = None
    capsule_class: str | None = None
    path: str | None = None
    source_span: SourceSpan | Mapping[str, Any] | None = None
    dependency_path: GraphPath | Mapping[str, Any] | None = None
    supporting_evidence_cids: Sequence[str] = ()
    proposed_rule_change: str | None = None
    notes: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "interface_id",
            "header",
            "hypothesis_id",
            "cause",
            "subject_artifact_id",
            "subject_kind",
            "rank",
            "expected_relevance_bp",
            "inclusion_cost_tokens",
            "confidence_bp",
            "expansion_action",
            "exclusion_reason",
            "capsule_class",
            "path",
            "source_span",
            "dependency_path",
            "supporting_evidence_cids",
            "proposed_rule_change",
            "notes",
            "metadata",
            "hypothesis_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "header", _header(self.header))
        if self.header.artifact_kind != "omission_hypothesis":
            raise AuditContractError(
                "header.artifact_kind must be omission_hypothesis"
            )
        object.__setattr__(
            self, "hypothesis_id", _token(self.hypothesis_id, "hypothesis_id")
        )
        object.__setattr__(self, "cause", _enum(self.cause, HypothesisCause, "cause"))
        object.__setattr__(
            self,
            "subject_artifact_id",
            _token(self.subject_artifact_id, "subject_artifact_id"),
        )
        object.__setattr__(
            self,
            "subject_kind",
            _enum(self.subject_kind, CoveredArtifactKind, "subject_kind"),
        )
        object.__setattr__(self, "rank", _nonneg_int(self.rank, "rank"))
        object.__setattr__(
            self,
            "expected_relevance_bp",
            _basis_points(self.expected_relevance_bp, "expected_relevance_bp"),
        )
        object.__setattr__(
            self,
            "inclusion_cost_tokens",
            _token_cost(self.inclusion_cost_tokens, "inclusion_cost_tokens"),
        )
        object.__setattr__(
            self, "confidence_bp", _basis_points(self.confidence_bp, "confidence_bp")
        )
        object.__setattr__(
            self,
            "expansion_action",
            _enum(self.expansion_action, ExpansionAction, "expansion_action"),
        )
        if self.exclusion_reason is not None and self.exclusion_reason != "":
            object.__setattr__(
                self,
                "exclusion_reason",
                _enum(self.exclusion_reason, ExclusionReason, "exclusion_reason"),
            )
        elif self.cause == HypothesisCause.OMISSION.value:
            raise AuditContractError(
                "omission cause requires exclusion_reason on hypothesis"
            )
        else:
            object.__setattr__(self, "exclusion_reason", None)
        if self.capsule_class is not None:
            object.__setattr__(
                self, "capsule_class", _token(self.capsule_class, "capsule_class")
            )
        if self.path is not None:
            object.__setattr__(self, "path", _repo_path(self.path, "path"))
        object.__setattr__(
            self,
            "source_span",
            _normalize_optional_span(self.source_span, "source_span"),
        )
        object.__setattr__(
            self,
            "dependency_path",
            _normalize_optional_graph_path(self.dependency_path, "dependency_path"),
        )
        object.__setattr__(
            self,
            "supporting_evidence_cids",
            _unique_sorted_cids(
                list(self.supporting_evidence_cids), "supporting_evidence_cids"
            ),
        )
        object.__setattr__(
            self,
            "proposed_rule_change",
            _optional_text(self.proposed_rule_change, "proposed_rule_change"),
        )
        object.__setattr__(self, "notes", _optional_text(self.notes, "notes"))
        object.__setattr__(self, "metadata", _mapping(self.metadata, "metadata"))

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": OMISSION_HYPOTHESIS_SCHEMA,
            "interface_id": OMISSION_HYPOTHESIS_INTERFACE,
            "header": self.header.identity_payload(),
            "hypothesis_id": self.hypothesis_id,
            "cause": self.cause,
            "subject_artifact_id": self.subject_artifact_id,
            "subject_kind": self.subject_kind,
            "rank": self.rank,
            "expected_relevance_bp": self.expected_relevance_bp,
            "inclusion_cost_tokens": self.inclusion_cost_tokens,
            "confidence_bp": self.confidence_bp,
            "expansion_action": self.expansion_action,
            "exclusion_reason": self.exclusion_reason,
            "capsule_class": self.capsule_class,
            "path": self.path,
            "source_span": (
                None if self.source_span is None else self.source_span.identity_payload()
            ),
            "dependency_path": (
                None
                if self.dependency_path is None
                else self.dependency_path.identity_payload()
            ),
            "supporting_evidence_cids": list(self.supporting_evidence_cids),
            "proposed_rule_change": self.proposed_rule_change,
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
        }

    @property
    def hypothesis_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": OMISSION_HYPOTHESIS_SCHEMA,
            "interface_id": OMISSION_HYPOTHESIS_INTERFACE,
            "header": self.header.to_dict(),
            "hypothesis_id": self.hypothesis_id,
            "cause": self.cause,
            "subject_artifact_id": self.subject_artifact_id,
            "subject_kind": self.subject_kind,
            "rank": self.rank,
            "expected_relevance_bp": self.expected_relevance_bp,
            "inclusion_cost_tokens": self.inclusion_cost_tokens,
            "confidence_bp": self.confidence_bp,
            "expansion_action": self.expansion_action,
            "exclusion_reason": self.exclusion_reason,
            "capsule_class": self.capsule_class,
            "path": self.path,
            "source_span": (
                None if self.source_span is None else self.source_span.to_dict()
            ),
            "dependency_path": (
                None
                if self.dependency_path is None
                else self.dependency_path.to_dict()
            ),
            "supporting_evidence_cids": list(self.supporting_evidence_cids),
            "proposed_rule_change": self.proposed_rule_change,
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
            "hypothesis_cid": self.hypothesis_cid,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "OmissionHypothesis":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("hypothesis_cid")
        if payload.pop("schema") != OMISSION_HYPOTHESIS_SCHEMA:
            raise AuditContractError("unsupported OmissionHypothesis schema version")
        if payload.pop("interface_id") != OMISSION_HYPOTHESIS_INTERFACE:
            raise AuditContractError("unsupported OmissionHypothesis interface_id")
        result = cls(**payload)
        if claimed != result.hypothesis_cid:
            raise AuditContractError(
                "OmissionHypothesis hypothesis_cid does not verify"
            )
        return result


@dataclass(frozen=True, slots=True)
class OmissionEvidence:
    """Evidence bundle supporting ranked omission hypotheses."""

    header: GovernorArtifactHeader
    evidence_id: str
    evidence_kind: OmissionEvidenceKind | str
    audit_case_cid: str
    hypothesis_cids: Sequence[str]
    supporting_cids: Sequence[str]
    confidence_bp: int
    differential_outcome: str | None = None
    counterexample_cid: str | None = None
    notes: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "interface_id",
            "header",
            "evidence_id",
            "evidence_kind",
            "audit_case_cid",
            "hypothesis_cids",
            "supporting_cids",
            "confidence_bp",
            "differential_outcome",
            "counterexample_cid",
            "notes",
            "metadata",
            "evidence_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "header", _header(self.header))
        if self.header.artifact_kind != "omission_evidence":
            raise AuditContractError("header.artifact_kind must be omission_evidence")
        object.__setattr__(self, "evidence_id", _token(self.evidence_id, "evidence_id"))
        object.__setattr__(
            self,
            "evidence_kind",
            _enum(self.evidence_kind, OmissionEvidenceKind, "evidence_kind"),
        )
        object.__setattr__(
            self, "audit_case_cid", _cid(self.audit_case_cid, "audit_case_cid")
        )
        hyps = _unique_sorted_cids(list(self.hypothesis_cids), "hypothesis_cids")
        if not hyps:
            raise AuditContractError("hypothesis_cids must not be empty")
        object.__setattr__(self, "hypothesis_cids", hyps)
        object.__setattr__(
            self,
            "supporting_cids",
            _unique_sorted_cids(list(self.supporting_cids), "supporting_cids"),
        )
        object.__setattr__(
            self, "confidence_bp", _basis_points(self.confidence_bp, "confidence_bp")
        )
        object.__setattr__(
            self,
            "differential_outcome",
            _optional_text(self.differential_outcome, "differential_outcome"),
        )
        object.__setattr__(
            self,
            "counterexample_cid",
            _optional_cid(self.counterexample_cid, "counterexample_cid"),
        )
        object.__setattr__(self, "notes", _optional_text(self.notes, "notes"))
        object.__setattr__(self, "metadata", _mapping(self.metadata, "metadata"))

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": OMISSION_EVIDENCE_SCHEMA,
            "interface_id": OMISSION_EVIDENCE_INTERFACE,
            "header": self.header.identity_payload(),
            "evidence_id": self.evidence_id,
            "evidence_kind": self.evidence_kind,
            "audit_case_cid": self.audit_case_cid,
            "hypothesis_cids": list(self.hypothesis_cids),
            "supporting_cids": list(self.supporting_cids),
            "confidence_bp": self.confidence_bp,
            "differential_outcome": self.differential_outcome,
            "counterexample_cid": self.counterexample_cid,
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
        }

    @property
    def evidence_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": OMISSION_EVIDENCE_SCHEMA,
            "interface_id": OMISSION_EVIDENCE_INTERFACE,
            "header": self.header.to_dict(),
            "evidence_id": self.evidence_id,
            "evidence_kind": self.evidence_kind,
            "audit_case_cid": self.audit_case_cid,
            "hypothesis_cids": list(self.hypothesis_cids),
            "supporting_cids": list(self.supporting_cids),
            "confidence_bp": self.confidence_bp,
            "differential_outcome": self.differential_outcome,
            "counterexample_cid": self.counterexample_cid,
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
            "evidence_cid": self.evidence_cid,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "OmissionEvidence":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("evidence_cid")
        if payload.pop("schema") != OMISSION_EVIDENCE_SCHEMA:
            raise AuditContractError("unsupported OmissionEvidence schema version")
        if payload.pop("interface_id") != OMISSION_EVIDENCE_INTERFACE:
            raise AuditContractError("unsupported OmissionEvidence interface_id")
        result = cls(**payload)
        if claimed != result.evidence_cid:
            raise AuditContractError("OmissionEvidence evidence_cid does not verify")
        return result


# ---------------------------------------------------------------------------
# ContextExpansionStep / ContextExpansionPlan
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ContextExpansionStep:
    """One bounded expansion step with cost and changed assumptions."""

    header: GovernorArtifactHeader
    step_id: str
    step_index: int
    action: ExpansionAction | str
    status: ExpansionStepStatus | str
    token_increase: int
    artifact_ids_added: Sequence[str]
    hypothesis_cid: str | None = None
    reason_code: str = "omission_repair"
    prior_result_cid: str | None = None
    new_result_cid: str | None = None
    changed_assumption_ids: Sequence[str] = ()
    hypothesis_supported: bool | None = None
    notes: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "interface_id",
            "header",
            "step_id",
            "step_index",
            "action",
            "status",
            "token_increase",
            "artifact_ids_added",
            "hypothesis_cid",
            "reason_code",
            "prior_result_cid",
            "new_result_cid",
            "changed_assumption_ids",
            "hypothesis_supported",
            "notes",
            "metadata",
            "step_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "header", _header(self.header))
        if self.header.artifact_kind != "context_expansion_step":
            raise AuditContractError(
                "header.artifact_kind must be context_expansion_step"
            )
        object.__setattr__(self, "step_id", _token(self.step_id, "step_id"))
        index = _nonneg_int(self.step_index, "step_index")
        if index >= MAX_EXPANSION_STEPS:
            raise AuditContractError(
                f"step_index must be < {MAX_EXPANSION_STEPS} (bounded expansion)"
            )
        object.__setattr__(self, "step_index", index)
        object.__setattr__(
            self, "action", _enum(self.action, ExpansionAction, "action")
        )
        object.__setattr__(
            self, "status", _enum(self.status, ExpansionStepStatus, "status")
        )
        object.__setattr__(
            self, "token_increase", _token_cost(self.token_increase, "token_increase")
        )
        object.__setattr__(
            self,
            "artifact_ids_added",
            _unique_sorted_tokens(
                list(self.artifact_ids_added),
                "artifact_ids_added",
                max_items=MAX_INCLUSIONS,
            ),
        )
        object.__setattr__(
            self, "hypothesis_cid", _optional_cid(self.hypothesis_cid, "hypothesis_cid")
        )
        object.__setattr__(self, "reason_code", _token(self.reason_code, "reason_code"))
        object.__setattr__(
            self,
            "prior_result_cid",
            _optional_cid(self.prior_result_cid, "prior_result_cid"),
        )
        object.__setattr__(
            self, "new_result_cid", _optional_cid(self.new_result_cid, "new_result_cid")
        )
        object.__setattr__(
            self,
            "changed_assumption_ids",
            _unique_sorted_tokens(
                list(self.changed_assumption_ids),
                "changed_assumption_ids",
                max_items=MAX_REASON_CODES,
            ),
        )
        if self.hypothesis_supported is not None:
            object.__setattr__(
                self,
                "hypothesis_supported",
                _bool(self.hypothesis_supported, "hypothesis_supported"),
            )
        object.__setattr__(self, "notes", _optional_text(self.notes, "notes"))
        object.__setattr__(self, "metadata", _mapping(self.metadata, "metadata"))

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": CONTEXT_EXPANSION_STEP_SCHEMA,
            "interface_id": CONTEXT_EXPANSION_STEP_INTERFACE,
            "header": self.header.identity_payload(),
            "step_id": self.step_id,
            "step_index": self.step_index,
            "action": self.action,
            "status": self.status,
            "token_increase": self.token_increase,
            "artifact_ids_added": list(self.artifact_ids_added),
            "hypothesis_cid": self.hypothesis_cid,
            "reason_code": self.reason_code,
            "prior_result_cid": self.prior_result_cid,
            "new_result_cid": self.new_result_cid,
            "changed_assumption_ids": list(self.changed_assumption_ids),
            "hypothesis_supported": self.hypothesis_supported,
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
        }

    @property
    def step_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": CONTEXT_EXPANSION_STEP_SCHEMA,
            "interface_id": CONTEXT_EXPANSION_STEP_INTERFACE,
            "header": self.header.to_dict(),
            "step_id": self.step_id,
            "step_index": self.step_index,
            "action": self.action,
            "status": self.status,
            "token_increase": self.token_increase,
            "artifact_ids_added": list(self.artifact_ids_added),
            "hypothesis_cid": self.hypothesis_cid,
            "reason_code": self.reason_code,
            "prior_result_cid": self.prior_result_cid,
            "new_result_cid": self.new_result_cid,
            "changed_assumption_ids": list(self.changed_assumption_ids),
            "hypothesis_supported": self.hypothesis_supported,
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
            "step_cid": self.step_cid,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ContextExpansionStep":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("step_cid")
        if payload.pop("schema") != CONTEXT_EXPANSION_STEP_SCHEMA:
            raise AuditContractError(
                "unsupported ContextExpansionStep schema version"
            )
        if payload.pop("interface_id") != CONTEXT_EXPANSION_STEP_INTERFACE:
            raise AuditContractError(
                "unsupported ContextExpansionStep interface_id"
            )
        result = cls(**payload)
        if claimed != result.step_cid:
            raise AuditContractError(
                "ContextExpansionStep step_cid does not verify"
            )
        return result


def _normalize_expansion_step(
    value: ContextExpansionStep | Mapping[str, Any],
) -> ContextExpansionStep:
    if isinstance(value, ContextExpansionStep):
        return value
    if isinstance(value, Mapping):
        if "step_cid" in value and "schema" in value:
            return ContextExpansionStep.from_dict(value)
        return ContextExpansionStep(
            header=value.get("header", {}),
            step_id=value.get("step_id", ""),
            step_index=value.get("step_index", 0),
            action=value.get("action", ""),
            status=value.get("status", ""),
            token_increase=value.get("token_increase", 0),
            artifact_ids_added=value.get("artifact_ids_added", ()),
            hypothesis_cid=value.get("hypothesis_cid"),
            reason_code=value.get("reason_code", "omission_repair"),
            prior_result_cid=value.get("prior_result_cid"),
            new_result_cid=value.get("new_result_cid"),
            changed_assumption_ids=value.get("changed_assumption_ids", ()),
            hypothesis_supported=value.get("hypothesis_supported"),
            notes=value.get("notes"),
            metadata=value.get("metadata", {}),
        )
    raise AuditContractError(
        "steps entries must be ContextExpansionStep or mapping"
    )


@dataclass(frozen=True, slots=True)
class ContextExpansionPlan:
    """Bounded expansion plan with hard step/token limits."""

    header: GovernorArtifactHeader
    plan_id: str
    audit_case_cid: str
    steps: Sequence[ContextExpansionStep]
    max_steps: int
    max_token_growth: int
    total_token_increase: int
    step_count: int
    omission_evidence_cid: str | None = None
    max_retries: int = 3
    max_escalations: int = 1
    max_wall_time_ms: int = 600_000
    max_spend_micros: int = 0
    notes: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "interface_id",
            "header",
            "plan_id",
            "audit_case_cid",
            "steps",
            "max_steps",
            "max_token_growth",
            "total_token_increase",
            "step_count",
            "omission_evidence_cid",
            "max_retries",
            "max_escalations",
            "max_wall_time_ms",
            "max_spend_micros",
            "notes",
            "metadata",
            "plan_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "header", _header(self.header))
        if self.header.artifact_kind != "context_expansion_plan":
            raise AuditContractError(
                "header.artifact_kind must be context_expansion_plan"
            )
        object.__setattr__(self, "plan_id", _token(self.plan_id, "plan_id"))
        object.__setattr__(
            self, "audit_case_cid", _cid(self.audit_case_cid, "audit_case_cid")
        )
        max_steps = _pos_int(self.max_steps, "max_steps")
        if max_steps > MAX_EXPANSION_STEPS:
            raise AuditContractError(
                f"max_steps must be <= {MAX_EXPANSION_STEPS}"
            )
        object.__setattr__(self, "max_steps", max_steps)
        object.__setattr__(
            self,
            "max_token_growth",
            _token_cost(self.max_token_growth, "max_token_growth"),
        )
        object.__setattr__(
            self, "max_retries", _nonneg_int(self.max_retries, "max_retries")
        )
        object.__setattr__(
            self,
            "max_escalations",
            _nonneg_int(self.max_escalations, "max_escalations"),
        )
        object.__setattr__(
            self,
            "max_wall_time_ms",
            _nonneg_int(self.max_wall_time_ms, "max_wall_time_ms"),
        )
        object.__setattr__(
            self,
            "max_spend_micros",
            _nonneg_int(self.max_spend_micros, "max_spend_micros"),
        )
        object.__setattr__(
            self,
            "omission_evidence_cid",
            _optional_cid(self.omission_evidence_cid, "omission_evidence_cid"),
        )
        object.__setattr__(self, "notes", _optional_text(self.notes, "notes"))
        object.__setattr__(self, "metadata", _mapping(self.metadata, "metadata"))

        if not isinstance(self.steps, (list, tuple)):
            raise AuditContractError("steps must be a list")
        if len(self.steps) > max_steps:
            raise AuditContractError(
                "steps exceed max_steps bound; expansion is unbounded"
            )
        if len(self.steps) > MAX_EXPANSION_STEPS:
            raise AuditContractError("steps exceed absolute maximum bound")
        steps = tuple(_normalize_expansion_step(item) for item in self.steps)
        step_ids = [step.step_id for step in steps]
        if len(step_ids) != len(set(step_ids)):
            raise AuditContractError("steps must not contain duplicate step_id")
        indices = [step.step_index for step in steps]
        if indices != list(range(len(steps))):
            raise AuditContractError(
                "step_index values must be contiguous from 0 without gaps"
            )
        object.__setattr__(self, "steps", steps)

        step_count = _nonneg_int(self.step_count, "step_count")
        total_increase = _token_cost(
            self.total_token_increase, "total_token_increase"
        )
        object.__setattr__(self, "step_count", step_count)
        object.__setattr__(self, "total_token_increase", total_increase)

        if step_count != len(steps):
            raise AuditContractError(
                "step_count must equal len(steps); "
                f"declared={step_count} derived={len(steps)}"
            )
        derived_tokens = sum(step.token_increase for step in steps)
        if total_increase != derived_tokens:
            raise AuditContractError(
                "total_token_increase must equal sum of step token_increase; "
                f"declared={total_increase} derived={derived_tokens}"
            )
        if total_increase > self.max_token_growth:
            raise AuditContractError(
                "total_token_increase must not exceed max_token_growth"
            )

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": CONTEXT_EXPANSION_PLAN_SCHEMA,
            "interface_id": CONTEXT_EXPANSION_PLAN_INTERFACE,
            "header": self.header.identity_payload(),
            "plan_id": self.plan_id,
            "audit_case_cid": self.audit_case_cid,
            "steps": [step.identity_payload() for step in self.steps],
            "max_steps": self.max_steps,
            "max_token_growth": self.max_token_growth,
            "total_token_increase": self.total_token_increase,
            "step_count": self.step_count,
            "omission_evidence_cid": self.omission_evidence_cid,
            "max_retries": self.max_retries,
            "max_escalations": self.max_escalations,
            "max_wall_time_ms": self.max_wall_time_ms,
            "max_spend_micros": self.max_spend_micros,
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
        }

    @property
    def plan_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": CONTEXT_EXPANSION_PLAN_SCHEMA,
            "interface_id": CONTEXT_EXPANSION_PLAN_INTERFACE,
            "header": self.header.to_dict(),
            "plan_id": self.plan_id,
            "audit_case_cid": self.audit_case_cid,
            "steps": [step.to_dict() for step in self.steps],
            "max_steps": self.max_steps,
            "max_token_growth": self.max_token_growth,
            "total_token_increase": self.total_token_increase,
            "step_count": self.step_count,
            "omission_evidence_cid": self.omission_evidence_cid,
            "max_retries": self.max_retries,
            "max_escalations": self.max_escalations,
            "max_wall_time_ms": self.max_wall_time_ms,
            "max_spend_micros": self.max_spend_micros,
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
            "plan_cid": self.plan_cid,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ContextExpansionPlan":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("plan_cid")
        if payload.pop("schema") != CONTEXT_EXPANSION_PLAN_SCHEMA:
            raise AuditContractError(
                "unsupported ContextExpansionPlan schema version"
            )
        if payload.pop("interface_id") != CONTEXT_EXPANSION_PLAN_INTERFACE:
            raise AuditContractError(
                "unsupported ContextExpansionPlan interface_id"
            )
        result = cls(**payload)
        if claimed != result.plan_cid:
            raise AuditContractError(
                "ContextExpansionPlan plan_cid does not verify"
            )
        return result


# ---------------------------------------------------------------------------
# GovernorDecision / GovernorRunReceipt / CompressionAuditCase
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class GovernorDecision:
    """Closed decision produced by the semantic governor for one task unit."""

    header: GovernorArtifactHeader
    decision_id: str
    action: DecisionAction | str
    sufficiency_state: ContextSufficiencyState | str
    route_tier: RouteTier | str
    task_class: str
    risk_class: str
    reason_codes: Sequence[str]
    coverage_manifest_cid: str | None = None
    sufficiency_claim_cid: str | None = None
    expansion_plan_cid: str | None = None
    omission_evidence_cid: str | None = None
    policy_cid: str | None = None
    requires_human_review: bool = False
    notes: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "interface_id",
            "header",
            "decision_id",
            "action",
            "sufficiency_state",
            "route_tier",
            "task_class",
            "risk_class",
            "reason_codes",
            "coverage_manifest_cid",
            "sufficiency_claim_cid",
            "expansion_plan_cid",
            "omission_evidence_cid",
            "policy_cid",
            "requires_human_review",
            "notes",
            "metadata",
            "decision_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "header", _header(self.header))
        if self.header.artifact_kind != "governor_decision":
            raise AuditContractError("header.artifact_kind must be governor_decision")
        object.__setattr__(self, "decision_id", _token(self.decision_id, "decision_id"))
        action = _enum(self.action, DecisionAction, "action")
        object.__setattr__(self, "action", action)
        state = _enum(
            self.sufficiency_state, ContextSufficiencyState, "sufficiency_state"
        )
        object.__setattr__(self, "sufficiency_state", state)
        object.__setattr__(
            self, "route_tier", _enum(self.route_tier, RouteTier, "route_tier")
        )
        object.__setattr__(self, "task_class", _token(self.task_class, "task_class"))
        object.__setattr__(self, "risk_class", _token(self.risk_class, "risk_class"))
        reasons = _unique_sorted_tokens(
            list(self.reason_codes), "reason_codes", max_items=MAX_REASON_CODES
        )
        if not reasons:
            raise AuditContractError("reason_codes must not be empty")
        object.__setattr__(self, "reason_codes", reasons)
        object.__setattr__(
            self,
            "coverage_manifest_cid",
            _optional_cid(self.coverage_manifest_cid, "coverage_manifest_cid"),
        )
        object.__setattr__(
            self,
            "sufficiency_claim_cid",
            _optional_cid(self.sufficiency_claim_cid, "sufficiency_claim_cid"),
        )
        object.__setattr__(
            self,
            "expansion_plan_cid",
            _optional_cid(self.expansion_plan_cid, "expansion_plan_cid"),
        )
        object.__setattr__(
            self,
            "omission_evidence_cid",
            _optional_cid(self.omission_evidence_cid, "omission_evidence_cid"),
        )
        object.__setattr__(self, "policy_cid", _optional_cid(self.policy_cid, "policy_cid"))
        requires_review = _bool(
            self.requires_human_review, "requires_human_review"
        )
        object.__setattr__(self, "requires_human_review", requires_review)
        if action == DecisionAction.REQUIRE_HUMAN_REVIEW.value and not requires_review:
            raise AuditContractError(
                "require_human_review action requires requires_human_review=true"
            )
        if (
            action == DecisionAction.ACCEPT_COMPRESSED.value
            and state
            not in {
                ContextSufficiencyState.SUFFICIENT.value,
                ContextSufficiencyState.SUFFICIENT_WITH_CAVEATS.value,
            }
        ):
            raise AuditContractError(
                "accept_compressed requires sufficient or sufficient_with_caveats"
            )
        if (
            action == DecisionAction.REQUIRE_EXPANSION.value
            and state != ContextSufficiencyState.EXPANSION_REQUIRED.value
        ):
            raise AuditContractError(
                "require_expansion action requires expansion_required sufficiency_state"
            )
        object.__setattr__(self, "notes", _optional_text(self.notes, "notes"))
        object.__setattr__(self, "metadata", _mapping(self.metadata, "metadata"))

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": GOVERNOR_DECISION_SCHEMA,
            "interface_id": GOVERNOR_DECISION_INTERFACE,
            "header": self.header.identity_payload(),
            "decision_id": self.decision_id,
            "action": self.action,
            "sufficiency_state": self.sufficiency_state,
            "route_tier": self.route_tier,
            "task_class": self.task_class,
            "risk_class": self.risk_class,
            "reason_codes": list(self.reason_codes),
            "coverage_manifest_cid": self.coverage_manifest_cid,
            "sufficiency_claim_cid": self.sufficiency_claim_cid,
            "expansion_plan_cid": self.expansion_plan_cid,
            "omission_evidence_cid": self.omission_evidence_cid,
            "policy_cid": self.policy_cid,
            "requires_human_review": self.requires_human_review,
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
        }

    @property
    def decision_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": GOVERNOR_DECISION_SCHEMA,
            "interface_id": GOVERNOR_DECISION_INTERFACE,
            "header": self.header.to_dict(),
            "decision_id": self.decision_id,
            "action": self.action,
            "sufficiency_state": self.sufficiency_state,
            "route_tier": self.route_tier,
            "task_class": self.task_class,
            "risk_class": self.risk_class,
            "reason_codes": list(self.reason_codes),
            "coverage_manifest_cid": self.coverage_manifest_cid,
            "sufficiency_claim_cid": self.sufficiency_claim_cid,
            "expansion_plan_cid": self.expansion_plan_cid,
            "omission_evidence_cid": self.omission_evidence_cid,
            "policy_cid": self.policy_cid,
            "requires_human_review": self.requires_human_review,
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
            "decision_cid": self.decision_cid,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "GovernorDecision":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("decision_cid")
        if payload.pop("schema") != GOVERNOR_DECISION_SCHEMA:
            raise AuditContractError("unsupported GovernorDecision schema version")
        if payload.pop("interface_id") != GOVERNOR_DECISION_INTERFACE:
            raise AuditContractError("unsupported GovernorDecision interface_id")
        result = cls(**payload)
        if claimed != result.decision_cid:
            raise AuditContractError("GovernorDecision decision_cid does not verify")
        return result


@dataclass(frozen=True, slots=True)
class GovernorRunReceipt:
    """Neutral durable run receipt payload (datasets-owned schema)."""

    header: GovernorArtifactHeader
    receipt_id: str
    task_id: str
    decision_cid: str
    route_tier: RouteTier | str
    input_tokens: int
    output_tokens: int
    verification_cost_tokens: int
    wall_time_ms: int
    spend_micros: int
    coverage_manifest_cid: str | None = None
    sufficiency_claim_cid: str | None = None
    expansion_plan_cid: str | None = None
    omission_evidence_cid: str | None = None
    shadow_result_cid: str | None = None
    differential_report_cid: str | None = None
    policy_cid: str | None = None
    notes: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "interface_id",
            "header",
            "receipt_id",
            "task_id",
            "decision_cid",
            "route_tier",
            "input_tokens",
            "output_tokens",
            "verification_cost_tokens",
            "wall_time_ms",
            "spend_micros",
            "coverage_manifest_cid",
            "sufficiency_claim_cid",
            "expansion_plan_cid",
            "omission_evidence_cid",
            "shadow_result_cid",
            "differential_report_cid",
            "policy_cid",
            "notes",
            "metadata",
            "receipt_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "header", _header(self.header))
        if self.header.artifact_kind != "governor_run_receipt":
            raise AuditContractError(
                "header.artifact_kind must be governor_run_receipt"
            )
        object.__setattr__(self, "receipt_id", _token(self.receipt_id, "receipt_id"))
        object.__setattr__(self, "task_id", _task_id(self.task_id, "task_id"))
        object.__setattr__(self, "decision_cid", _cid(self.decision_cid, "decision_cid"))
        object.__setattr__(
            self, "route_tier", _enum(self.route_tier, RouteTier, "route_tier")
        )
        for name in (
            "input_tokens",
            "output_tokens",
            "verification_cost_tokens",
            "wall_time_ms",
            "spend_micros",
        ):
            object.__setattr__(self, name, _nonneg_int(getattr(self, name), name))
        object.__setattr__(
            self,
            "coverage_manifest_cid",
            _optional_cid(self.coverage_manifest_cid, "coverage_manifest_cid"),
        )
        object.__setattr__(
            self,
            "sufficiency_claim_cid",
            _optional_cid(self.sufficiency_claim_cid, "sufficiency_claim_cid"),
        )
        object.__setattr__(
            self,
            "expansion_plan_cid",
            _optional_cid(self.expansion_plan_cid, "expansion_plan_cid"),
        )
        object.__setattr__(
            self,
            "omission_evidence_cid",
            _optional_cid(self.omission_evidence_cid, "omission_evidence_cid"),
        )
        object.__setattr__(
            self,
            "shadow_result_cid",
            _optional_cid(self.shadow_result_cid, "shadow_result_cid"),
        )
        object.__setattr__(
            self,
            "differential_report_cid",
            _optional_cid(self.differential_report_cid, "differential_report_cid"),
        )
        object.__setattr__(self, "policy_cid", _optional_cid(self.policy_cid, "policy_cid"))
        object.__setattr__(self, "notes", _optional_text(self.notes, "notes"))
        object.__setattr__(self, "metadata", _mapping(self.metadata, "metadata"))

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": GOVERNOR_RUN_RECEIPT_SCHEMA,
            "interface_id": GOVERNOR_RUN_RECEIPT_INTERFACE,
            "header": self.header.identity_payload(),
            "receipt_id": self.receipt_id,
            "task_id": self.task_id,
            "decision_cid": self.decision_cid,
            "route_tier": self.route_tier,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "verification_cost_tokens": self.verification_cost_tokens,
            "wall_time_ms": self.wall_time_ms,
            "spend_micros": self.spend_micros,
            "coverage_manifest_cid": self.coverage_manifest_cid,
            "sufficiency_claim_cid": self.sufficiency_claim_cid,
            "expansion_plan_cid": self.expansion_plan_cid,
            "omission_evidence_cid": self.omission_evidence_cid,
            "shadow_result_cid": self.shadow_result_cid,
            "differential_report_cid": self.differential_report_cid,
            "policy_cid": self.policy_cid,
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
        }

    @property
    def receipt_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": GOVERNOR_RUN_RECEIPT_SCHEMA,
            "interface_id": GOVERNOR_RUN_RECEIPT_INTERFACE,
            "header": self.header.to_dict(),
            "receipt_id": self.receipt_id,
            "task_id": self.task_id,
            "decision_cid": self.decision_cid,
            "route_tier": self.route_tier,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "verification_cost_tokens": self.verification_cost_tokens,
            "wall_time_ms": self.wall_time_ms,
            "spend_micros": self.spend_micros,
            "coverage_manifest_cid": self.coverage_manifest_cid,
            "sufficiency_claim_cid": self.sufficiency_claim_cid,
            "expansion_plan_cid": self.expansion_plan_cid,
            "omission_evidence_cid": self.omission_evidence_cid,
            "shadow_result_cid": self.shadow_result_cid,
            "differential_report_cid": self.differential_report_cid,
            "policy_cid": self.policy_cid,
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
            "receipt_cid": self.receipt_cid,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "GovernorRunReceipt":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("receipt_cid")
        if payload.pop("schema") != GOVERNOR_RUN_RECEIPT_SCHEMA:
            raise AuditContractError("unsupported GovernorRunReceipt schema version")
        if payload.pop("interface_id") != GOVERNOR_RUN_RECEIPT_INTERFACE:
            raise AuditContractError("unsupported GovernorRunReceipt interface_id")
        result = cls(**payload)
        if claimed != result.receipt_cid:
            raise AuditContractError(
                "GovernorRunReceipt receipt_cid does not verify"
            )
        return result


@dataclass(frozen=True, slots=True)
class CompressionAuditCase:
    """Immutable audit-case binding for one compression evaluation unit."""

    header: GovernorArtifactHeader
    case_id: str
    task_id: str
    task_class: str
    risk_class: str
    coverage_manifest_cid: str
    sufficiency_claim_cid: str
    decision_cid: str
    run_receipt_cid: str | None = None
    expansion_plan_cid: str | None = None
    omission_evidence_cid: str | None = None
    shadow_plan_cid: str | None = None
    shadow_result_cid: str | None = None
    differential_report_cid: str | None = None
    policy_cid: str | None = None
    benchmark_partition: str = "development"
    notes: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "interface_id",
            "header",
            "case_id",
            "task_id",
            "task_class",
            "risk_class",
            "coverage_manifest_cid",
            "sufficiency_claim_cid",
            "decision_cid",
            "run_receipt_cid",
            "expansion_plan_cid",
            "omission_evidence_cid",
            "shadow_plan_cid",
            "shadow_result_cid",
            "differential_report_cid",
            "policy_cid",
            "benchmark_partition",
            "notes",
            "metadata",
            "case_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "header", _header(self.header))
        if self.header.artifact_kind != "compression_audit_case":
            raise AuditContractError(
                "header.artifact_kind must be compression_audit_case"
            )
        object.__setattr__(self, "case_id", _token(self.case_id, "case_id"))
        object.__setattr__(self, "task_id", _task_id(self.task_id, "task_id"))
        object.__setattr__(self, "task_class", _token(self.task_class, "task_class"))
        object.__setattr__(self, "risk_class", _token(self.risk_class, "risk_class"))
        object.__setattr__(
            self,
            "coverage_manifest_cid",
            _cid(self.coverage_manifest_cid, "coverage_manifest_cid"),
        )
        object.__setattr__(
            self,
            "sufficiency_claim_cid",
            _cid(self.sufficiency_claim_cid, "sufficiency_claim_cid"),
        )
        object.__setattr__(self, "decision_cid", _cid(self.decision_cid, "decision_cid"))
        for name in (
            "run_receipt_cid",
            "expansion_plan_cid",
            "omission_evidence_cid",
            "shadow_plan_cid",
            "shadow_result_cid",
            "differential_report_cid",
            "policy_cid",
        ):
            object.__setattr__(
                self, name, _optional_cid(getattr(self, name), name)
            )
        object.__setattr__(
            self,
            "benchmark_partition",
            _token(self.benchmark_partition, "benchmark_partition"),
        )
        object.__setattr__(self, "notes", _optional_text(self.notes, "notes"))
        object.__setattr__(self, "metadata", _mapping(self.metadata, "metadata"))

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": COMPRESSION_AUDIT_CASE_SCHEMA,
            "interface_id": COMPRESSION_AUDIT_CASE_INTERFACE,
            "header": self.header.identity_payload(),
            "case_id": self.case_id,
            "task_id": self.task_id,
            "task_class": self.task_class,
            "risk_class": self.risk_class,
            "coverage_manifest_cid": self.coverage_manifest_cid,
            "sufficiency_claim_cid": self.sufficiency_claim_cid,
            "decision_cid": self.decision_cid,
            "run_receipt_cid": self.run_receipt_cid,
            "expansion_plan_cid": self.expansion_plan_cid,
            "omission_evidence_cid": self.omission_evidence_cid,
            "shadow_plan_cid": self.shadow_plan_cid,
            "shadow_result_cid": self.shadow_result_cid,
            "differential_report_cid": self.differential_report_cid,
            "policy_cid": self.policy_cid,
            "benchmark_partition": self.benchmark_partition,
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
        }

    @property
    def case_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": COMPRESSION_AUDIT_CASE_SCHEMA,
            "interface_id": COMPRESSION_AUDIT_CASE_INTERFACE,
            "header": self.header.to_dict(),
            "case_id": self.case_id,
            "task_id": self.task_id,
            "task_class": self.task_class,
            "risk_class": self.risk_class,
            "coverage_manifest_cid": self.coverage_manifest_cid,
            "sufficiency_claim_cid": self.sufficiency_claim_cid,
            "decision_cid": self.decision_cid,
            "run_receipt_cid": self.run_receipt_cid,
            "expansion_plan_cid": self.expansion_plan_cid,
            "omission_evidence_cid": self.omission_evidence_cid,
            "shadow_plan_cid": self.shadow_plan_cid,
            "shadow_result_cid": self.shadow_result_cid,
            "differential_report_cid": self.differential_report_cid,
            "policy_cid": self.policy_cid,
            "benchmark_partition": self.benchmark_partition,
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
            "case_cid": self.case_cid,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "CompressionAuditCase":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("case_cid")
        if payload.pop("schema") != COMPRESSION_AUDIT_CASE_SCHEMA:
            raise AuditContractError(
                "unsupported CompressionAuditCase schema version"
            )
        if payload.pop("interface_id") != COMPRESSION_AUDIT_CASE_INTERFACE:
            raise AuditContractError(
                "unsupported CompressionAuditCase interface_id"
            )
        result = cls(**payload)
        if claimed != result.case_cid:
            raise AuditContractError(
                "CompressionAuditCase case_cid does not verify"
            )
        return result


# ---------------------------------------------------------------------------
# Vocabulary helpers
# ---------------------------------------------------------------------------


def exclusion_reasons() -> tuple[str, ...]:
    """Return the closed exclusion-reason vocabulary in declaration order."""

    return tuple(item.value for item in ExclusionReason)


def inclusion_kinds() -> tuple[str, ...]:
    """Return the closed inclusion-kind vocabulary."""

    return tuple(item.value for item in InclusionKind)


def sufficiency_evidence_bases() -> tuple[str, ...]:
    """Return the closed sufficiency-evidence-basis vocabulary."""

    return tuple(item.value for item in SufficiencyEvidenceBasis)


def expansion_actions() -> tuple[str, ...]:
    """Return the closed expansion-action vocabulary."""

    return tuple(item.value for item in ExpansionAction)


def decision_actions() -> tuple[str, ...]:
    """Return the closed decision-action vocabulary."""

    return tuple(item.value for item in DecisionAction)


def hypothesis_causes() -> tuple[str, ...]:
    """Return the closed hypothesis-cause vocabulary."""

    return tuple(item.value for item in HypothesisCause)


def route_tiers() -> tuple[str, ...]:
    """Return the closed route-tier vocabulary."""

    return tuple(item.value for item in RouteTier)


__all__ = [
    "BASIS_POINTS",
    "COMPRESSION_AUDIT_CASE_INTERFACE",
    "COMPRESSION_AUDIT_CASE_SCHEMA",
    "CONTEXT_COVERAGE_MANIFEST_INTERFACE",
    "CONTEXT_COVERAGE_MANIFEST_SCHEMA",
    "CONTEXT_EXPANSION_PLAN_INTERFACE",
    "CONTEXT_EXPANSION_PLAN_SCHEMA",
    "CONTEXT_EXPANSION_STEP_INTERFACE",
    "CONTEXT_EXPANSION_STEP_SCHEMA",
    "CONTEXT_SUFFICIENCY_CLAIM_INTERFACE",
    "CONTEXT_SUFFICIENCY_CLAIM_SCHEMA",
    "EXCLUDED_ARTIFACT_RECORD_SCHEMA",
    "GOVERNOR_DECISION_INTERFACE",
    "GOVERNOR_DECISION_SCHEMA",
    "GOVERNOR_RUN_RECEIPT_INTERFACE",
    "GOVERNOR_RUN_RECEIPT_SCHEMA",
    "INCLUDED_ARTIFACT_RECORD_SCHEMA",
    "MAX_EXPANSION_STEPS",
    "MAX_PATH_CHARS",
    "MAX_PATH_NODES",
    "MAX_SPAN_COL",
    "MAX_SPAN_LINE",
    "OMISSION_EVIDENCE_INTERFACE",
    "OMISSION_EVIDENCE_SCHEMA",
    "OMISSION_HYPOTHESIS_INTERFACE",
    "OMISSION_HYPOTHESIS_SCHEMA",
    "AuditContractError",
    "CompressionAuditCase",
    "ContextCoverageManifest",
    "ContextExpansionPlan",
    "ContextExpansionStep",
    "ContextSufficiencyClaim",
    "CoverageGap",
    "CoverageGapKind",
    "CoveredArtifactKind",
    "DecisionAction",
    "ExcludedArtifactRecord",
    "ExclusionReason",
    "ExpansionAction",
    "ExpansionStepStatus",
    "GovernorDecision",
    "GovernorRunReceipt",
    "GraphPath",
    "HypothesisCause",
    "IncludedArtifactRecord",
    "InclusionKind",
    "OmissionEvidence",
    "OmissionEvidenceKind",
    "OmissionHypothesis",
    "RouteTier",
    "SourceSpan",
    "SufficiencyEvidenceBasis",
    "assert_sufficiency_not_verification_only",
    "decision_actions",
    "exclusion_reasons",
    "expansion_actions",
    "hypothesis_causes",
    "inclusion_kinds",
    "route_tiers",
    "sufficiency_evidence_bases",
]
