"""Diagnose and rank omission versus reasoning hypotheses (SCG-014).

Pure, deterministic diagnosis over an audit case, repository-state view, and
dependency graph. This module never invents exclusions, never rescans a
repository, and never treats model-written reasoning text as formal evidence.

Normative rules:

* Rank evidence; never automatically blame compression without differential
  support that the expanded context repaired the failure.
* ``compressed_failed_expanded_succeeded`` yields ranked omission evidence.
* Both-context failure does **not** yield ranked omission evidence blaming
  compression.
* Evidenced model insufficiency remains a **route** hypothesis
  (``escalate_route``), not formal proof of model capability.
* Identical verified inputs yield identical diagnosis identities.
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
    MAX_EXCLUSIONS,
    MAX_HYPOTHESES,
    MAX_PATH_NODES,
    MAX_TOKEN_COST,
    AuditContractError,
    CompressionAuditCase,
    ContextCoverageManifest,
    CoveredArtifactKind,
    ExcludedArtifactRecord,
    ExclusionReason,
    ExpansionAction,
    GraphPath,
    HypothesisCause,
    OmissionEvidence,
    OmissionEvidenceKind,
    OmissionHypothesis,
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

DIAGNOSE_OMISSION_INTERFACE: Final[str] = "diagnose_omission@1"
OMISSION_DIAGNOSIS_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.semantic-governor-omission-diagnosis@1"
)
REPOSITORY_STATE_VIEW_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.semantic-governor-repository-state-view@1"
)
DEPENDENCY_GRAPH_VIEW_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.semantic-governor-dependency-graph-view@1"
)
OMISSION_CANDIDATE_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.semantic-governor-omission-candidate@1"
)

GENERATOR_ID: Final[str] = "omission_diagnoser"
GENERATOR_VERSION: Final[str] = "1.0.0"
PRODUCER_ID: Final[str] = "semantic_governor"
PRODUCER_VERSION: Final[str] = "1"
TOOL_ID: Final[str] = "omission.v1"

MAX_TEXT_CHARS: Final[int] = 16_384
MAX_CID_LIST: Final[int] = 4_096
MAX_ASSUMPTIONS: Final[int] = 512
MAX_EXPANDED_ARTIFACTS: Final[int] = 4_096
MAX_FAILURE_CIDS: Final[int] = 4_096
MAX_GRAPH_NODES: Final[int] = 8_192

_TOKEN_RE: Final[re.Pattern[str]] = re.compile(r"^[a-z][a-z0-9_.:/+-]{0,127}$")
_TASK_ID_RE: Final[re.Pattern[str]] = re.compile(
    r"^[A-Za-z][A-Za-z0-9_.:/+-]{0,127}$"
)
_REPO_PATH_RE: Final[re.Pattern[str]] = re.compile(
    r"^(?:[A-Za-z0-9_./@+-][A-Za-z0-9_./@+-]{0,1022})$"
)

# Outcomes that support ranked omission evidence (compressed inferior, expanded
# repaired). Plan §5 comparative vocabulary, datasets-owned mirror.
_OMISSION_SUPPORTING_OUTCOMES: Final[frozenset[str]] = frozenset(
    {
        "compressed_failed_expanded_succeeded",
        "expanded_better",
    }
)

# Both-context failures: never blame compression via ranked omission evidence.
_BOTH_FAIL_OUTCOMES: Final[frozenset[str]] = frozenset(
    {
        "both_failed_same_reason",
        "both_failed_different_reason",
    }
)

# Outcomes where compressed is not inferior — no omission ranking.
_NO_OMISSION_RANKING_OUTCOMES: Final[frozenset[str]] = frozenset(
    {
        "equivalent_success",
        "compressed_better",
        "compressed_succeeded_expanded_failed",
        "both_valid_different",
        "verification_inconclusive",
        "human_review_required",
    }
) | _BOTH_FAIL_OUTCOMES

# Exclusion reasons that are weak omission candidates (already claimed unrelated).
_LOW_OMISSION_REASONS: Final[frozenset[str]] = frozenset(
    {
        ExclusionReason.PROVEN_UNRELATED_BY_DEPENDENCY_GRAPH.value,
        ExclusionReason.OUTSIDE_AFFECTED_INVALIDATION_CONE.value,
        ExclusionReason.VERIFIED_IMMUTABLE_DEPENDENCY.value,
        ExclusionReason.DUPLICATE_REPRESENTATION.value,
        ExclusionReason.GENERATED_FROM_INCLUDED_AUTHORITATIVE_SCHEMA.value,
    }
)

# Relevance base by exclusion reason (basis points, before graph/critical boosts).
_REASON_RELEVANCE_BP: Final[dict[str, int]] = {
    ExclusionReason.BUDGET_EXCEEDED_ESCALATION_REQUIRED.value: 8_500,
    ExclusionReason.EXACT_CAPSULE_SUBSTITUTED.value: 7_500,
    ExclusionReason.CONSERVATIVE_CAPSULE_SUBSTITUTED.value: 7_000,
    ExclusionReason.DUPLICATE_REPRESENTATION.value: 2_000,
    ExclusionReason.GENERATED_FROM_INCLUDED_AUTHORITATIVE_SCHEMA.value: 2_500,
    ExclusionReason.VERIFIED_IMMUTABLE_DEPENDENCY.value: 1_500,
    ExclusionReason.PROVEN_UNRELATED_BY_DEPENDENCY_GRAPH.value: 500,
    ExclusionReason.OUTSIDE_AFFECTED_INVALIDATION_CONE.value: 800,
}

# Artifact-kind → default expansion action when omission is supported.
_KIND_EXPANSION_ACTION: Final[dict[str, str]] = {
    CoveredArtifactKind.SYMBOL.value: ExpansionAction.INCLUDE_RAW_SOURCE.value,
    CoveredArtifactKind.FILE.value: ExpansionAction.INCLUDE_RAW_SOURCE.value,
    CoveredArtifactKind.SCHEMA.value: ExpansionAction.INCLUDE_SCHEMA.value,
    CoveredArtifactKind.FIXTURE.value: ExpansionAction.INCLUDE_FIXTURE.value,
    CoveredArtifactKind.CONFIGURATION.value: ExpansionAction.INCLUDE_CONFIGURATION.value,
    CoveredArtifactKind.TEST.value: ExpansionAction.INCLUDE_TEST.value,
    CoveredArtifactKind.PROOF_OBLIGATION.value: ExpansionAction.INCLUDE_PROOF.value,
    CoveredArtifactKind.STATE_BINDING.value: ExpansionAction.INCLUDE_RAW_SOURCE.value,
    CoveredArtifactKind.DEPENDENCY_EDGE.value: ExpansionAction.INCLUDE_RAW_SOURCE.value,
}


class OmissionDiagnosisError(SemanticGovernorBaseError):
    """Raised when omission diagnosis fails closed."""


# ---------------------------------------------------------------------------
# Closed enumerations
# ---------------------------------------------------------------------------


class ComparativeOutcome(str, Enum):
    """Closed comparative outcomes (plan §5; datasets-owned mirror)."""

    EQUIVALENT_SUCCESS = "equivalent_success"
    COMPRESSED_BETTER = "compressed_better"
    EXPANDED_BETTER = "expanded_better"
    BOTH_VALID_DIFFERENT = "both_valid_different"
    COMPRESSED_FAILED_EXPANDED_SUCCEEDED = "compressed_failed_expanded_succeeded"
    COMPRESSED_SUCCEEDED_EXPANDED_FAILED = "compressed_succeeded_expanded_failed"
    BOTH_FAILED_SAME_REASON = "both_failed_same_reason"
    BOTH_FAILED_DIFFERENT_REASON = "both_failed_different_reason"
    VERIFICATION_INCONCLUSIVE = "verification_inconclusive"
    HUMAN_REVIEW_REQUIRED = "human_review_required"


class PrimaryDiagnosisCause(str, Enum):
    """Closed primary diagnosis labels for the result envelope."""

    OMISSION = "omission"
    MODEL_INSUFFICIENCY = "model_insufficiency"
    STALE_ARTIFACT = "stale_artifact"
    POLICY_BOUNDARY = "policy_boundary"
    BUDGET_OVERFLOW = "budget_overflow"
    CONFLICTING_EVIDENCE = "conflicting_evidence"
    UNKNOWN = "unknown"
    NONE = "none"


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _text(value: Any, name: str, *, empty: bool = False) -> str:
    if type(value) is not str or (not empty and not value):
        raise OmissionDiagnosisError(f"{name} must be a nonempty string")
    if value != value.strip() or unicodedata.normalize("NFC", value) != value:
        raise OmissionDiagnosisError(f"{name} must be trimmed NFC text")
    if len(value) > MAX_TEXT_CHARS or any(not char.isprintable() for char in value):
        raise OmissionDiagnosisError(f"{name} contains invalid text")
    return value


def _optional_text(value: Any, name: str) -> str | None:
    if value is None:
        return None
    return _text(value, name)


def _token(value: Any, name: str) -> str:
    text = _text(value, name)
    if _TOKEN_RE.fullmatch(text) is None:
        raise OmissionDiagnosisError(
            f"{name} must be a lowercase token matching {_TOKEN_RE.pattern}"
        )
    return text


def _task_id(value: Any, name: str = "task_id") -> str:
    text = _text(value, name)
    if _TASK_ID_RE.fullmatch(text) is None:
        raise OmissionDiagnosisError(f"{name} must match {_TASK_ID_RE.pattern}")
    return text


def _cid(value: Any, name: str) -> str:
    try:
        return validate_cid(value)
    except Exception as exc:
        raise OmissionDiagnosisError(f"{name} must be a valid CID") from exc


def _optional_cid(value: Any, name: str) -> str | None:
    if value is None:
        return None
    return _cid(value, name)


def _bool(value: Any, name: str) -> bool:
    if type(value) is not bool:
        raise OmissionDiagnosisError(f"{name} must be a boolean")
    return value


def _nonneg_int(value: Any, name: str) -> int:
    if type(value) is not int or isinstance(value, bool) or value < 0:
        raise OmissionDiagnosisError(f"{name} must be a nonnegative integer")
    return value


def _token_cost(value: Any, name: str) -> int:
    cost = _nonneg_int(value, name)
    if cost > MAX_TOKEN_COST:
        raise OmissionDiagnosisError(f"{name} exceeds maximum token cost")
    return cost


def _basis_points(value: Any, name: str) -> int:
    bp = _nonneg_int(value, name)
    if bp > BASIS_POINTS:
        raise OmissionDiagnosisError(f"{name} must be in 0..{BASIS_POINTS}")
    return bp


def _enum(value: Any, enum_type: type[Enum], name: str) -> str:
    try:
        return enum_type(value).value
    except (TypeError, ValueError) as exc:
        raise OmissionDiagnosisError(f"{name} has unsupported value {value!r}") from exc


def _repo_path(value: Any, name: str) -> str:
    text = _text(value, name)
    if text.startswith("/") or text.startswith("\\"):
        raise OmissionDiagnosisError(f"{name} must be a relative repository path")
    if ".." in text.split("/"):
        raise OmissionDiagnosisError(f"{name} rejects parent traversal")
    if _REPO_PATH_RE.fullmatch(text) is None:
        raise OmissionDiagnosisError(f"{name} is not a valid relative repository path")
    return text


def _optional_repo_path(value: Any, name: str) -> str | None:
    if value is None:
        return None
    return _repo_path(value, name)


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
        raise OmissionDiagnosisError(
            f"{name} must be strict DAG-JSON without floats or host types"
        ) from exc
    try:
        reject_private_and_model_authority(thawed, path=name)
    except SemanticGovernorBaseError as exc:
        raise OmissionDiagnosisError(str(exc)) from exc
    return thawed


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise OmissionDiagnosisError(f"{name} must be a mapping")
    return _freeze_structured(_require_structured(dict(value), name))


def _unique_sorted_cids(
    values: Iterable[Any],
    name: str,
    *,
    max_items: int = MAX_CID_LIST,
) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple)):
        raise OmissionDiagnosisError(f"{name} must be a list")
    ordered = tuple(sorted(_cid(value, name) for value in values))
    if len(ordered) > max_items:
        raise OmissionDiagnosisError(f"{name} exceeds maximum length")
    if len(ordered) != len(set(ordered)):
        raise OmissionDiagnosisError(f"{name} must not contain duplicates")
    return ordered


def _unique_sorted_tokens(
    values: Iterable[Any],
    name: str,
    *,
    max_items: int,
) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple)):
        raise OmissionDiagnosisError(f"{name} must be a list")
    ordered = tuple(sorted(_token(value, name) for value in values))
    if len(ordered) > max_items:
        raise OmissionDiagnosisError(f"{name} exceeds maximum length")
    if len(ordered) != len(set(ordered)):
        raise OmissionDiagnosisError(f"{name} must not contain duplicates")
    return ordered


def _normalize_graph_path(
    value: GraphPath | Mapping[str, Any],
    name: str = "dependency_path",
) -> GraphPath:
    if isinstance(value, GraphPath):
        return value
    if isinstance(value, Mapping):
        try:
            if "schema" in value:
                return GraphPath.from_dict(value)
            return GraphPath(
                nodes=value.get("nodes", ()),
                edge_relation=value.get("edge_relation", "depends_on"),
            )
        except AuditContractError as exc:
            raise OmissionDiagnosisError(str(exc)) from exc
    raise OmissionDiagnosisError(f"{name} must be GraphPath or mapping")


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
            raise OmissionDiagnosisError(str(exc)) from exc
    raise OmissionDiagnosisError(f"{name} must be SourceSpan, mapping, or null")


def _normalize_exclusion(
    value: ExcludedArtifactRecord | Mapping[str, Any],
) -> ExcludedArtifactRecord:
    if isinstance(value, ExcludedArtifactRecord):
        return value
    if isinstance(value, Mapping):
        try:
            if "schema" in value:
                return ExcludedArtifactRecord.from_dict(value)
            if "exclusion_reason" not in value or value.get("exclusion_reason") in (
                None,
                "",
            ):
                raise OmissionDiagnosisError(
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
        except AuditContractError as exc:
            raise OmissionDiagnosisError(str(exc)) from exc
    raise OmissionDiagnosisError(
        "exclusions entries must be ExcludedArtifactRecord or mapping"
    )


def _normalize_manifest(
    value: ContextCoverageManifest | Mapping[str, Any],
) -> ContextCoverageManifest:
    if isinstance(value, ContextCoverageManifest):
        return value
    if isinstance(value, Mapping):
        try:
            return ContextCoverageManifest.from_dict(value)
        except AuditContractError as exc:
            raise OmissionDiagnosisError(str(exc)) from exc
    raise OmissionDiagnosisError(
        "coverage_manifest must be ContextCoverageManifest or mapping"
    )


def _normalize_audit_case(
    value: CompressionAuditCase | Mapping[str, Any],
) -> CompressionAuditCase:
    if isinstance(value, CompressionAuditCase):
        return value
    if isinstance(value, Mapping):
        try:
            return CompressionAuditCase.from_dict(value)
        except AuditContractError as exc:
            raise OmissionDiagnosisError(str(exc)) from exc
    raise OmissionDiagnosisError(
        "audit_case must be CompressionAuditCase or mapping"
    )


# ---------------------------------------------------------------------------
# Input views
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RepositoryStateView:
    """Verified repository-state binding plus differential diagnosis inputs.

    Carries coverage exclusions, comparative outcome, and counterexample /
    minimized-failure CIDs. Bodies of private source and model reasoning are
    never admitted — only content-addressed evidence CIDs.
    """

    repository_state_cid: str
    context_pack_cid: str
    verification_bundle_cid: str
    differential_outcome: ComparativeOutcome | str
    exclusions: Sequence[ExcludedArtifactRecord | Mapping[str, Any]]
    target_symbol_ids: Sequence[str] = ()
    counterexample_cids: Sequence[str] = ()
    minimized_failure_cids: Sequence[str] = ()
    model_insufficiency_evidence_cids: Sequence[str] = ()
    expanded_artifact_ids: Sequence[str] = ()
    coverage_manifest_cid: str | None = None
    policy_cid: str | None = None
    notes: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

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
        object.__setattr__(
            self,
            "differential_outcome",
            _enum(self.differential_outcome, ComparativeOutcome, "differential_outcome"),
        )
        if not isinstance(self.exclusions, (list, tuple)):
            raise OmissionDiagnosisError("exclusions must be a list")
        if len(self.exclusions) > MAX_EXCLUSIONS:
            raise OmissionDiagnosisError("exclusions exceed maximum length")
        normalized = tuple(_normalize_exclusion(item) for item in self.exclusions)
        # Stable order by artifact_id for deterministic ranking ties.
        object.__setattr__(
            self,
            "exclusions",
            tuple(sorted(normalized, key=lambda item: item.artifact_id)),
        )
        object.__setattr__(
            self,
            "target_symbol_ids",
            _unique_sorted_tokens(
                list(self.target_symbol_ids),
                "target_symbol_ids",
                max_items=MAX_GRAPH_NODES,
            ),
        )
        object.__setattr__(
            self,
            "counterexample_cids",
            _unique_sorted_cids(
                list(self.counterexample_cids),
                "counterexample_cids",
                max_items=MAX_FAILURE_CIDS,
            ),
        )
        object.__setattr__(
            self,
            "minimized_failure_cids",
            _unique_sorted_cids(
                list(self.minimized_failure_cids),
                "minimized_failure_cids",
                max_items=MAX_FAILURE_CIDS,
            ),
        )
        object.__setattr__(
            self,
            "model_insufficiency_evidence_cids",
            _unique_sorted_cids(
                list(self.model_insufficiency_evidence_cids),
                "model_insufficiency_evidence_cids",
                max_items=MAX_FAILURE_CIDS,
            ),
        )
        object.__setattr__(
            self,
            "expanded_artifact_ids",
            _unique_sorted_tokens(
                list(self.expanded_artifact_ids),
                "expanded_artifact_ids",
                max_items=MAX_EXPANDED_ARTIFACTS,
            ),
        )
        object.__setattr__(
            self,
            "coverage_manifest_cid",
            _optional_cid(self.coverage_manifest_cid, "coverage_manifest_cid"),
        )
        object.__setattr__(
            self, "policy_cid", _optional_cid(self.policy_cid, "policy_cid")
        )
        object.__setattr__(self, "notes", _optional_text(self.notes, "notes"))
        object.__setattr__(self, "metadata", _mapping(self.metadata, "metadata"))

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": REPOSITORY_STATE_VIEW_SCHEMA,
            "repository_state_cid": self.repository_state_cid,
            "context_pack_cid": self.context_pack_cid,
            "verification_bundle_cid": self.verification_bundle_cid,
            "differential_outcome": self.differential_outcome,
            "exclusions": [item.identity_payload() for item in self.exclusions],
            "target_symbol_ids": list(self.target_symbol_ids),
            "counterexample_cids": list(self.counterexample_cids),
            "minimized_failure_cids": list(self.minimized_failure_cids),
            "model_insufficiency_evidence_cids": list(
                self.model_insufficiency_evidence_cids
            ),
            "expanded_artifact_ids": list(self.expanded_artifact_ids),
            "coverage_manifest_cid": self.coverage_manifest_cid,
            "policy_cid": self.policy_cid,
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
        }

    @property
    def view_cid(self) -> str:
        return cid_for_structured(self.identity_payload())


@dataclass(frozen=True, slots=True)
class DependencyGraphView:
    """Verified dependency-graph paths used for omission attribution.

    Paths are observations only — the diagnoser never invents edges.
    """

    repository_state_cid: str
    paths: Sequence[GraphPath | Mapping[str, Any]] = ()
    node_artifact_ids: Mapping[str, str] = field(default_factory=dict)
    notes: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "repository_state_cid",
            _cid(self.repository_state_cid, "repository_state_cid"),
        )
        if not isinstance(self.paths, (list, tuple)):
            raise OmissionDiagnosisError("paths must be a list")
        if len(self.paths) > MAX_PATH_NODES * 4:
            raise OmissionDiagnosisError("paths exceed maximum length")
        normalized_paths = tuple(
            _normalize_graph_path(item, "paths") for item in self.paths
        )
        object.__setattr__(
            self,
            "paths",
            tuple(
                sorted(
                    normalized_paths,
                    key=lambda path: (path.edge_relation, tuple(path.nodes)),
                )
            ),
        )
        if not isinstance(self.node_artifact_ids, Mapping):
            raise OmissionDiagnosisError("node_artifact_ids must be a mapping")
        bindings: dict[str, str] = {}
        for key, value in self.node_artifact_ids.items():
            node = _token(key, "node_artifact_ids")
            artifact = _token(value, "node_artifact_ids")
            bindings[node] = artifact
        if len(bindings) > MAX_GRAPH_NODES:
            raise OmissionDiagnosisError("node_artifact_ids exceeds maximum length")
        object.__setattr__(
            self,
            "node_artifact_ids",
            MappingProxyType(dict(sorted(bindings.items()))),
        )
        object.__setattr__(self, "notes", _optional_text(self.notes, "notes"))
        object.__setattr__(self, "metadata", _mapping(self.metadata, "metadata"))

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": DEPENDENCY_GRAPH_VIEW_SCHEMA,
            "repository_state_cid": self.repository_state_cid,
            "paths": [path.identity_payload() for path in self.paths],
            "node_artifact_ids": dict(self.node_artifact_ids),
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
        }

    @property
    def view_cid(self) -> str:
        return cid_for_structured(self.identity_payload())


def _normalize_repository_state(
    value: RepositoryStateView | Mapping[str, Any],
) -> RepositoryStateView:
    if isinstance(value, RepositoryStateView):
        return value
    if isinstance(value, Mapping):
        payload = dict(value)
        payload.pop("view_cid", None)
        schema = payload.pop("schema", REPOSITORY_STATE_VIEW_SCHEMA)
        if schema != REPOSITORY_STATE_VIEW_SCHEMA:
            raise OmissionDiagnosisError(
                "unsupported RepositoryStateView schema version"
            )
        return RepositoryStateView(**payload)
    raise OmissionDiagnosisError(
        "repository_state must be a RepositoryStateView or mapping"
    )


def _normalize_dependency_graph(
    value: DependencyGraphView | Mapping[str, Any],
) -> DependencyGraphView:
    if isinstance(value, DependencyGraphView):
        return value
    if isinstance(value, Mapping):
        payload = dict(value)
        payload.pop("view_cid", None)
        schema = payload.pop("schema", DEPENDENCY_GRAPH_VIEW_SCHEMA)
        if schema != DEPENDENCY_GRAPH_VIEW_SCHEMA:
            raise OmissionDiagnosisError(
                "unsupported DependencyGraphView schema version"
            )
        return DependencyGraphView(**payload)
    raise OmissionDiagnosisError(
        "dependency_graph must be a DependencyGraphView or mapping"
    )


# ---------------------------------------------------------------------------
# Ranking helpers
# ---------------------------------------------------------------------------


def _path_nodes_for_artifact(
    exclusion: ExcludedArtifactRecord,
    graph: DependencyGraphView,
) -> tuple[str, ...]:
    """Collect graph nodes that bind to this exclusion."""

    nodes: set[str] = set()
    if exclusion.dependency_path is not None:
        nodes.update(exclusion.dependency_path.nodes)
    if exclusion.symbol_id is not None:
        nodes.add(exclusion.symbol_id)
    nodes.add(exclusion.artifact_id)
    # Reverse map: artifact_id → nodes that point at it.
    for node, artifact_id in graph.node_artifact_ids.items():
        if artifact_id == exclusion.artifact_id or (
            exclusion.symbol_id is not None and artifact_id == exclusion.symbol_id
        ):
            nodes.add(node)
    return tuple(sorted(nodes))


def _min_path_distance(
    exclusion: ExcludedArtifactRecord,
    graph: DependencyGraphView,
    target_symbol_ids: Sequence[str],
) -> int | None:
    """Minimum hops from any target to this exclusion along verified paths.

    Returns ``None`` when no verified path connects the exclusion to a target.
    """

    if not target_symbol_ids:
        return None
    targets = set(target_symbol_ids)
    artifact_nodes = set(_path_nodes_for_artifact(exclusion, graph))
    best: int | None = None
    for path in graph.paths:
        nodes = list(path.nodes)
        target_indices = [i for i, node in enumerate(nodes) if node in targets]
        artifact_indices = [
            i for i, node in enumerate(nodes) if node in artifact_nodes
        ]
        if not target_indices or not artifact_indices:
            continue
        for t_i in target_indices:
            for a_i in artifact_indices:
                dist = abs(a_i - t_i)
                if best is None or dist < best:
                    best = dist
    if exclusion.dependency_path is not None:
        nodes = list(exclusion.dependency_path.nodes)
        for i, node in enumerate(nodes):
            if node in targets:
                # Distance from target at index i to last node (artifact end).
                dist = max(len(nodes) - 1 - i, 0)
                if best is None or dist < best:
                    best = dist
    return best


def _expected_relevance_bp(
    exclusion: ExcludedArtifactRecord,
    *,
    graph: DependencyGraphView,
    target_symbol_ids: Sequence[str],
    expanded_artifact_ids: frozenset[str],
    differential_outcome: str,
) -> int:
    base = _REASON_RELEVANCE_BP.get(exclusion.exclusion_reason, 4_000)
    if exclusion.critical:
        base = min(BASIS_POINTS, base + 1_500)
    if exclusion.artifact_id in expanded_artifact_ids or (
        exclusion.symbol_id is not None and exclusion.symbol_id in expanded_artifact_ids
    ):
        # Expanded run explicitly re-included this artifact and succeeded.
        base = min(BASIS_POINTS, base + 2_000)
    if differential_outcome in _OMISSION_SUPPORTING_OUTCOMES:
        dist = _min_path_distance(exclusion, graph, target_symbol_ids)
        if dist is None:
            base = max(0, base - 1_500)
        elif dist == 0:
            base = min(BASIS_POINTS, base + 1_000)
        elif dist == 1:
            base = min(BASIS_POINTS, base + 500)
        elif dist > 4:
            base = max(0, base - 500)
    if exclusion.exclusion_reason in _LOW_OMISSION_REASONS:
        # Keep low-relevance for "proven unrelated" unless expansion repaired it.
        if exclusion.artifact_id not in expanded_artifact_ids and (
            exclusion.symbol_id is None
            or exclusion.symbol_id not in expanded_artifact_ids
        ):
            base = min(base, 1_500)
    return base


def _hypothesis_confidence_bp(
    exclusion: ExcludedArtifactRecord,
    *,
    expected_relevance_bp: int,
    expanded_match: bool,
    has_counterexample: bool,
    differential_outcome: str,
) -> int:
    """Confidence that this exclusion is the omission cause — not formal proof."""

    if differential_outcome not in _OMISSION_SUPPORTING_OUTCOMES:
        return 0
    # Blend exclusion confidence with relevance; never claim certainty.
    conf = (exclusion.confidence_bp * 4 + expected_relevance_bp * 6) // 10
    if expanded_match:
        conf = min(BASIS_POINTS, conf + 1_000)
    if has_counterexample:
        conf = min(BASIS_POINTS, conf + 500)
    if exclusion.critical:
        conf = min(BASIS_POINTS, conf + 250)
    # Cap below absolute certainty — ranking is evidential, not formal.
    return min(9_500, conf)


def _expansion_action_for(
    exclusion: ExcludedArtifactRecord,
    *,
    cause: str,
) -> str:
    if cause == HypothesisCause.MODEL_INSUFFICIENCY.value:
        return ExpansionAction.ESCALATE_ROUTE.value
    if cause == HypothesisCause.STALE_ARTIFACT.value:
        return ExpansionAction.REQUEST_HUMAN_REVIEW.value
    if cause == HypothesisCause.POLICY_BOUNDARY.value:
        return ExpansionAction.REQUEST_HUMAN_REVIEW.value
    if cause == HypothesisCause.BUDGET_OVERFLOW.value:
        return ExpansionAction.INCLUDE_RAW_SOURCE.value
    if exclusion.exclusion_reason == (
        ExclusionReason.CONSERVATIVE_CAPSULE_SUBSTITUTED.value
    ):
        return ExpansionAction.STRENGTHEN_CAPSULE.value
    if exclusion.exclusion_reason == (
        ExclusionReason.EXACT_CAPSULE_SUBSTITUTED.value
    ):
        # Exact capsule that failed under differential repair → prefer raw.
        return ExpansionAction.INCLUDE_RAW_SOURCE.value
    return _KIND_EXPANSION_ACTION.get(
        exclusion.artifact_kind, ExpansionAction.INCLUDE_RAW_SOURCE.value
    )


def _capsule_class_for(exclusion: ExcludedArtifactRecord) -> str | None:
    if exclusion.exclusion_reason == ExclusionReason.EXACT_CAPSULE_SUBSTITUTED.value:
        return "exact_capsule"
    if exclusion.exclusion_reason == (
        ExclusionReason.CONSERVATIVE_CAPSULE_SUBSTITUTED.value
    ):
        return "conservative_capsule"
    if exclusion.exclusion_reason == (
        ExclusionReason.BUDGET_EXCEEDED_ESCALATION_REQUIRED.value
    ):
        return "budget_truncated"
    return None


def _proposed_rule_change(exclusion: ExcludedArtifactRecord) -> str | None:
    """Bounded declarative rule hint — never executable model text."""

    reason = exclusion.exclusion_reason
    kind = exclusion.artifact_kind
    if reason == ExclusionReason.EXACT_CAPSULE_SUBSTITUTED.value and exclusion.critical:
        return "prefer_raw_source_for_critical_exact_capsule_subjects"
    if reason == ExclusionReason.CONSERVATIVE_CAPSULE_SUBSTITUTED.value:
        return "strengthen_conservative_capsule_before_route_escalation"
    if reason == ExclusionReason.BUDGET_EXCEEDED_ESCALATION_REQUIRED.value:
        return "raise_context_budget_for_affected_cone_before_escalation"
    if kind == CoveredArtifactKind.SCHEMA.value:
        return "include_authoritative_schema_for_migration_tasks"
    if kind == CoveredArtifactKind.FIXTURE.value:
        return "include_fixture_bindings_for_test_sensitive_tasks"
    if kind == CoveredArtifactKind.CONFIGURATION.value:
        return "include_configuration_flags_for_behavior_sensitive_tasks"
    if kind == CoveredArtifactKind.TEST.value:
        return "include_selected_tests_for_acceptance_sensitive_tasks"
    if kind == CoveredArtifactKind.PROOF_OBLIGATION.value:
        return "include_proof_obligations_before_acceptance"
    return None


def _ranking_key(
    *,
    expected_relevance_bp: int,
    confidence_bp: int,
    inclusion_cost_tokens: int,
    critical: bool,
    expanded_match: bool,
    path_distance: int | None,
    artifact_id: str,
) -> tuple[Any, ...]:
    """Sort key: higher relevance/confidence first; lower cost preferred.

    Rank 0 is best. Tie-break on artifact_id for determinism.
    """

    # Negative relevance/confidence so ascending sort ranks best first.
    dist_score = path_distance if path_distance is not None else 10_000
    return (
        0 if expanded_match else 1,
        0 if critical else 1,
        -expected_relevance_bp,
        -confidence_bp,
        dist_score,
        inclusion_cost_tokens,
        artifact_id,
    )


def _cause_for_omission_candidate(
    exclusion: ExcludedArtifactRecord,
) -> str:
    if exclusion.exclusion_reason == (
        ExclusionReason.BUDGET_EXCEEDED_ESCALATION_REQUIRED.value
    ):
        return HypothesisCause.BUDGET_OVERFLOW.value
    return HypothesisCause.OMISSION.value


def _evidence_kind_for(
    *,
    has_counterexample: bool,
    differential_outcome: str,
    expanded_match_count: int,
) -> str:
    if has_counterexample:
        return OmissionEvidenceKind.COUNTEREXAMPLE.value
    if expanded_match_count > 0:
        return OmissionEvidenceKind.EXPANSION_REPAIR.value
    if differential_outcome in _OMISSION_SUPPORTING_OUTCOMES:
        return OmissionEvidenceKind.DIFFERENTIAL_OUTCOME.value
    return OmissionEvidenceKind.GRAPH_PATH.value


# ---------------------------------------------------------------------------
# Result envelope
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class OmissionDiagnosisResult:
    """Ranked omission / route hypotheses plus optional omission evidence.

    ``ranked_omission_supported`` is true only when differential evidence
    supports blaming compression (compressed fail + expanded success).
    Both-context failure never sets that flag. Model insufficiency may still
    appear as a route hypothesis without producing ranked omission evidence.
    """

    header: GovernorArtifactHeader
    diagnosis_id: str
    audit_case_cid: str
    differential_outcome: str
    primary_cause: str
    ranked_omission_supported: bool
    model_insufficiency_route_hypothesis: bool
    hypotheses: Sequence[OmissionHypothesis]
    evidence: OmissionEvidence | None
    supporting_cids: Sequence[str] = ()
    notes: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "interface_id",
            "header",
            "diagnosis_id",
            "audit_case_cid",
            "differential_outcome",
            "primary_cause",
            "ranked_omission_supported",
            "model_insufficiency_route_hypothesis",
            "hypotheses",
            "evidence",
            "supporting_cids",
            "notes",
            "metadata",
            "diagnosis_cid",
        }
    )

    def __post_init__(self) -> None:
        if not isinstance(self.header, GovernorArtifactHeader):
            raise OmissionDiagnosisError("header must be a GovernorArtifactHeader")
        if self.header.artifact_kind != "omission_diagnosis":
            raise OmissionDiagnosisError(
                "header.artifact_kind must be omission_diagnosis"
            )
        object.__setattr__(
            self, "diagnosis_id", _token(self.diagnosis_id, "diagnosis_id")
        )
        object.__setattr__(
            self, "audit_case_cid", _cid(self.audit_case_cid, "audit_case_cid")
        )
        object.__setattr__(
            self,
            "differential_outcome",
            _enum(
                self.differential_outcome,
                ComparativeOutcome,
                "differential_outcome",
            ),
        )
        object.__setattr__(
            self,
            "primary_cause",
            _enum(self.primary_cause, PrimaryDiagnosisCause, "primary_cause"),
        )
        object.__setattr__(
            self,
            "ranked_omission_supported",
            _bool(self.ranked_omission_supported, "ranked_omission_supported"),
        )
        object.__setattr__(
            self,
            "model_insufficiency_route_hypothesis",
            _bool(
                self.model_insufficiency_route_hypothesis,
                "model_insufficiency_route_hypothesis",
            ),
        )
        if not isinstance(self.hypotheses, (list, tuple)):
            raise OmissionDiagnosisError("hypotheses must be a list")
        if len(self.hypotheses) > MAX_HYPOTHESES:
            raise OmissionDiagnosisError("hypotheses exceed maximum length")
        for index, hyp in enumerate(self.hypotheses):
            if not isinstance(hyp, OmissionHypothesis):
                raise OmissionDiagnosisError(
                    f"hypotheses[{index}] must be OmissionHypothesis"
                )
        object.__setattr__(self, "hypotheses", tuple(self.hypotheses))
        if self.evidence is not None and not isinstance(self.evidence, OmissionEvidence):
            raise OmissionDiagnosisError("evidence must be OmissionEvidence or null")
        # Invariants: ranked omission evidence requires supporting outcome and
        # non-empty omission-cause hypotheses.
        if self.ranked_omission_supported:
            if self.differential_outcome not in _OMISSION_SUPPORTING_OUTCOMES:
                raise OmissionDiagnosisError(
                    "ranked_omission_supported requires compressed-fail/"
                    "expanded-success differential outcome"
                )
            if self.evidence is None:
                raise OmissionDiagnosisError(
                    "ranked_omission_supported requires omission evidence"
                )
            omission_hyps = [
                h
                for h in self.hypotheses
                if h.cause
                in {
                    HypothesisCause.OMISSION.value,
                    HypothesisCause.BUDGET_OVERFLOW.value,
                }
            ]
            if not omission_hyps:
                raise OmissionDiagnosisError(
                    "ranked_omission_supported requires omission-cause hypotheses"
                )
        else:
            if self.evidence is not None:
                raise OmissionDiagnosisError(
                    "omission evidence requires ranked_omission_supported"
                )
        if self.model_insufficiency_route_hypothesis:
            route_hyps = [
                h
                for h in self.hypotheses
                if h.cause == HypothesisCause.MODEL_INSUFFICIENCY.value
            ]
            if not route_hyps:
                raise OmissionDiagnosisError(
                    "model_insufficiency_route_hypothesis requires a "
                    "model_insufficiency hypothesis"
                )
            for hyp in route_hyps:
                if hyp.expansion_action != ExpansionAction.ESCALATE_ROUTE.value:
                    raise OmissionDiagnosisError(
                        "model insufficiency hypothesis must use escalate_route"
                    )
        # Both-fail must never claim ranked omission support.
        if (
            self.differential_outcome in _BOTH_FAIL_OUTCOMES
            and self.ranked_omission_supported
        ):
            raise OmissionDiagnosisError(
                "both-context failure must not yield ranked omission evidence"
            )
        object.__setattr__(
            self,
            "supporting_cids",
            _unique_sorted_cids(list(self.supporting_cids), "supporting_cids"),
        )
        object.__setattr__(self, "notes", _optional_text(self.notes, "notes"))
        object.__setattr__(self, "metadata", _mapping(self.metadata, "metadata"))

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": OMISSION_DIAGNOSIS_SCHEMA,
            "interface_id": DIAGNOSE_OMISSION_INTERFACE,
            "header": self.header.identity_payload(),
            "diagnosis_id": self.diagnosis_id,
            "audit_case_cid": self.audit_case_cid,
            "differential_outcome": self.differential_outcome,
            "primary_cause": self.primary_cause,
            "ranked_omission_supported": self.ranked_omission_supported,
            "model_insufficiency_route_hypothesis": (
                self.model_insufficiency_route_hypothesis
            ),
            "hypotheses": [hyp.identity_payload() for hyp in self.hypotheses],
            "evidence": (
                None if self.evidence is None else self.evidence.identity_payload()
            ),
            "supporting_cids": list(self.supporting_cids),
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
        }

    @property
    def diagnosis_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": OMISSION_DIAGNOSIS_SCHEMA,
            "interface_id": DIAGNOSE_OMISSION_INTERFACE,
            "header": self.header.to_dict(),
            "diagnosis_id": self.diagnosis_id,
            "audit_case_cid": self.audit_case_cid,
            "differential_outcome": self.differential_outcome,
            "primary_cause": self.primary_cause,
            "ranked_omission_supported": self.ranked_omission_supported,
            "model_insufficiency_route_hypothesis": (
                self.model_insufficiency_route_hypothesis
            ),
            "hypotheses": [hyp.to_dict() for hyp in self.hypotheses],
            "evidence": None if self.evidence is None else self.evidence.to_dict(),
            "supporting_cids": list(self.supporting_cids),
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
            "diagnosis_cid": self.diagnosis_cid,
        }


# ---------------------------------------------------------------------------
# Header / id construction
# ---------------------------------------------------------------------------


def _build_header(
    *,
    repository_state: RepositoryStateView,
    dependency_graph: DependencyGraphView,
    audit_case: CompressionAuditCase,
    terminal_status: str,
    input_cids: Sequence[str],
    assumptions: Sequence[GovernorAssumption],
) -> GovernorArtifactHeader:
    generator = GeneratorIdentity(
        generator_id=GENERATOR_ID,
        generator_version=GENERATOR_VERSION,
        interface_id=DIAGNOSE_OMISSION_INTERFACE,
    )
    provenance = ArtifactProvenance(
        producer_id=PRODUCER_ID,
        producer_version=PRODUCER_VERSION,
        execution_mode=ExecutionMode.LIVE,
        authority_source=AuthoritySource.DETERMINISTIC,
        input_cids=tuple(sorted(set(input_cids))),
        tool_ids=(TOOL_ID,),
        policy_cid=repository_state.policy_cid or audit_case.policy_cid,
        notes=None,
    )
    try:
        return GovernorArtifactHeader(
            artifact_kind="omission_diagnosis",
            repository_state_cid=repository_state.repository_state_cid,
            context_pack_cid=repository_state.context_pack_cid,
            verification_bundle_cid=repository_state.verification_bundle_cid,
            generator=generator,
            provenance=provenance,
            terminal_status=terminal_status,
            assumptions=assumptions,
            metadata={
                "builder_schema": OMISSION_DIAGNOSIS_SCHEMA,
                "interface_id": DIAGNOSE_OMISSION_INTERFACE,
                "dependency_graph_cid": dependency_graph.view_cid,
            },
        )
    except SemanticGovernorBaseError as exc:
        raise OmissionDiagnosisError(str(exc)) from exc


def _hypothesis_header(
    base: GovernorArtifactHeader,
) -> GovernorArtifactHeader:
    return GovernorArtifactHeader(
        artifact_kind="omission_hypothesis",
        repository_state_cid=base.repository_state_cid,
        context_pack_cid=base.context_pack_cid,
        verification_bundle_cid=base.verification_bundle_cid,
        generator=base.generator,
        provenance=base.provenance,
        terminal_status=base.terminal_status,
        assumptions=base.assumptions,
        metadata={
            "builder_schema": OMISSION_DIAGNOSIS_SCHEMA,
            "interface_id": DIAGNOSE_OMISSION_INTERFACE,
        },
    )


def _evidence_header(
    base: GovernorArtifactHeader,
) -> GovernorArtifactHeader:
    return GovernorArtifactHeader(
        artifact_kind="omission_evidence",
        repository_state_cid=base.repository_state_cid,
        context_pack_cid=base.context_pack_cid,
        verification_bundle_cid=base.verification_bundle_cid,
        generator=base.generator,
        provenance=base.provenance,
        terminal_status=base.terminal_status,
        assumptions=base.assumptions,
        metadata={
            "builder_schema": OMISSION_DIAGNOSIS_SCHEMA,
            "interface_id": DIAGNOSE_OMISSION_INTERFACE,
        },
    )


def _build_assumptions(
    repository_state: RepositoryStateView,
    dependency_graph: DependencyGraphView,
) -> tuple[GovernorAssumption, ...]:
    assumptions: list[GovernorAssumption] = [
        GovernorAssumption(
            assumption_id="diagnosis_evidence_only",
            kind=AssumptionKind.VERIFICATION,
            statement=(
                "Omission diagnosis ranks verified differential, counterexample, "
                "and coverage evidence only; model reasoning text is not formal "
                "evidence and compression is never blamed without differential support"
            ),
            supporting_cids=(
                repository_state.repository_state_cid,
                repository_state.verification_bundle_cid,
            ),
        ),
        GovernorAssumption(
            assumption_id="graph_paths_verified",
            kind=AssumptionKind.COVERAGE,
            statement=(
                "Dependency paths are verified observations; the diagnoser does "
                "not invent edges or missing source"
            ),
            supporting_cids=(
                repository_state.repository_state_cid,
                dependency_graph.view_cid,
            ),
        ),
    ]
    if repository_state.differential_outcome in _OMISSION_SUPPORTING_OUTCOMES:
        assumptions.append(
            GovernorAssumption(
                assumption_id="differential_supports_omission",
                kind=AssumptionKind.EXCLUSION,
                statement=(
                    "Compressed failure with expanded success supports ranked "
                    "omission hypotheses over excluded artifacts"
                ),
                supporting_cids=(repository_state.verification_bundle_cid,),
            )
        )
    if repository_state.differential_outcome in _BOTH_FAIL_OUTCOMES:
        assumptions.append(
            GovernorAssumption(
                assumption_id="both_fail_no_omission_blame",
                kind=AssumptionKind.ROUTE,
                statement=(
                    "Both-context failure does not yield ranked omission evidence; "
                    "evidenced model insufficiency remains a route hypothesis only"
                ),
                supporting_cids=(repository_state.verification_bundle_cid,),
            )
        )
    return tuple(sorted(assumptions, key=lambda item: item.assumption_id))


def _diagnosis_id_for(
    audit_case: CompressionAuditCase,
    repository_state: RepositoryStateView,
) -> str:
    digest = cid_for_structured(
        {
            "case": audit_case.case_cid,
            "state": repository_state.view_cid,
            "outcome": repository_state.differential_outcome,
        }
    )
    suffix = digest[-24:] if len(digest) >= 24 else digest
    cleaned = re.sub(r"[^a-z0-9_.:/+-]", "", suffix.lower())
    if not cleaned or not cleaned[0].isalpha():
        cleaned = f"d{cleaned}" if cleaned else "d0"
    return f"diagnosis_{cleaned}"[:128]


def _hypothesis_id_for(artifact_id: str, rank: int) -> str:
    cleaned = re.sub(r"[^a-z0-9_.:/+-]", "", artifact_id.lower())
    if not cleaned or not cleaned[0].isalpha():
        cleaned = f"h{cleaned}" if cleaned else "h0"
    return f"hyp_{rank:04d}_{cleaned}"[:128]


# ---------------------------------------------------------------------------
# Core diagnosis
# ---------------------------------------------------------------------------


def _build_omission_hypotheses(
    *,
    exclusions: Sequence[ExcludedArtifactRecord],
    repository_state: RepositoryStateView,
    dependency_graph: DependencyGraphView,
    header: GovernorArtifactHeader,
    supporting_evidence_cids: Sequence[str],
) -> tuple[OmissionHypothesis, ...]:
    expanded = frozenset(repository_state.expanded_artifact_ids)
    has_counterexample = bool(repository_state.counterexample_cids)
    scored: list[tuple[tuple[Any, ...], OmissionHypothesis]] = []
    hyp_header = _hypothesis_header(header)

    for exclusion in exclusions:
        relevance = _expected_relevance_bp(
            exclusion,
            graph=dependency_graph,
            target_symbol_ids=repository_state.target_symbol_ids,
            expanded_artifact_ids=expanded,
            differential_outcome=repository_state.differential_outcome,
        )
        expanded_match = exclusion.artifact_id in expanded or (
            exclusion.symbol_id is not None and exclusion.symbol_id in expanded
        )
        confidence = _hypothesis_confidence_bp(
            exclusion,
            expected_relevance_bp=relevance,
            expanded_match=expanded_match,
            has_counterexample=has_counterexample,
            differential_outcome=repository_state.differential_outcome,
        )
        # Skip vanishingly low-relevance candidates that expansion did not touch.
        if relevance < 1_000 and not expanded_match and not exclusion.critical:
            continue
        cause = _cause_for_omission_candidate(exclusion)
        action = _expansion_action_for(exclusion, cause=cause)
        path_distance = _min_path_distance(
            exclusion,
            dependency_graph,
            repository_state.target_symbol_ids,
        )
        # Temporary rank 0; reassigned after sort.
        try:
            hyp = OmissionHypothesis(
                header=hyp_header,
                hypothesis_id=_hypothesis_id_for(exclusion.artifact_id, 0),
                cause=cause,
                subject_artifact_id=exclusion.artifact_id,
                subject_kind=exclusion.artifact_kind,
                rank=0,
                expected_relevance_bp=relevance,
                inclusion_cost_tokens=exclusion.token_cost,
                confidence_bp=confidence,
                expansion_action=action,
                exclusion_reason=exclusion.exclusion_reason,
                capsule_class=_capsule_class_for(exclusion),
                path=exclusion.path,
                source_span=exclusion.source_span,
                dependency_path=exclusion.dependency_path,
                supporting_evidence_cids=supporting_evidence_cids,
                proposed_rule_change=_proposed_rule_change(exclusion),
                notes=exclusion.notes,
                metadata={
                    "critical": exclusion.critical,
                    "expanded_match": expanded_match,
                    "path_distance": path_distance if path_distance is not None else -1,
                },
            )
        except AuditContractError as exc:
            raise OmissionDiagnosisError(str(exc)) from exc
        key = _ranking_key(
            expected_relevance_bp=relevance,
            confidence_bp=confidence,
            inclusion_cost_tokens=exclusion.token_cost,
            critical=exclusion.critical,
            expanded_match=expanded_match,
            path_distance=path_distance,
            artifact_id=exclusion.artifact_id,
        )
        scored.append((key, hyp))

    scored.sort(key=lambda item: item[0])
    ranked: list[OmissionHypothesis] = []
    for rank, (_key, hyp) in enumerate(scored[:MAX_HYPOTHESES]):
        try:
            ranked.append(
                OmissionHypothesis(
                    header=hyp.header,
                    hypothesis_id=_hypothesis_id_for(hyp.subject_artifact_id, rank),
                    cause=hyp.cause,
                    subject_artifact_id=hyp.subject_artifact_id,
                    subject_kind=hyp.subject_kind,
                    rank=rank,
                    expected_relevance_bp=hyp.expected_relevance_bp,
                    inclusion_cost_tokens=hyp.inclusion_cost_tokens,
                    confidence_bp=hyp.confidence_bp,
                    expansion_action=hyp.expansion_action,
                    exclusion_reason=hyp.exclusion_reason,
                    capsule_class=hyp.capsule_class,
                    path=hyp.path,
                    source_span=hyp.source_span,
                    dependency_path=hyp.dependency_path,
                    supporting_evidence_cids=hyp.supporting_evidence_cids,
                    proposed_rule_change=hyp.proposed_rule_change,
                    notes=hyp.notes,
                    metadata=dict(hyp.metadata),
                )
            )
        except AuditContractError as exc:
            raise OmissionDiagnosisError(str(exc)) from exc
    return tuple(ranked)


def _build_model_insufficiency_hypothesis(
    *,
    header: GovernorArtifactHeader,
    supporting_evidence_cids: Sequence[str],
    rank: int,
    notes: str | None = None,
) -> OmissionHypothesis:
    """Route hypothesis only — not formal model-capability proof."""

    hyp_header = _hypothesis_header(header)
    try:
        return OmissionHypothesis(
            header=hyp_header,
            hypothesis_id=_hypothesis_id_for("model_insufficiency", rank),
            cause=HypothesisCause.MODEL_INSUFFICIENCY,
            subject_artifact_id="model_route",
            subject_kind=CoveredArtifactKind.SYMBOL,
            rank=rank,
            expected_relevance_bp=5_000,
            inclusion_cost_tokens=0,
            confidence_bp=min(8_000, 5_000 + 500 * min(len(supporting_evidence_cids), 4)),
            expansion_action=ExpansionAction.ESCALATE_ROUTE,
            exclusion_reason=None,
            capsule_class=None,
            path=None,
            source_span=None,
            dependency_path=None,
            supporting_evidence_cids=supporting_evidence_cids,
            proposed_rule_change="escalate_route_after_context_expansion_insufficient",
            notes=notes
            or (
                "Evidenced model insufficiency remains a route hypothesis; "
                "not formal proof of model capability"
            ),
            metadata={"route_hypothesis": True, "formal_evidence": False},
        )
    except AuditContractError as exc:
        raise OmissionDiagnosisError(str(exc)) from exc


def _build_omission_evidence(
    *,
    header: GovernorArtifactHeader,
    audit_case: CompressionAuditCase,
    repository_state: RepositoryStateView,
    hypotheses: Sequence[OmissionHypothesis],
    supporting_cids: Sequence[str],
    evidence_id: str,
) -> OmissionEvidence:
    expanded = frozenset(repository_state.expanded_artifact_ids)
    expanded_match_count = sum(
        1
        for hyp in hypotheses
        if hyp.subject_artifact_id in expanded
        or (isinstance(hyp.metadata, Mapping) and hyp.metadata.get("expanded_match"))
    )
    has_counterexample = bool(repository_state.counterexample_cids)
    kind = _evidence_kind_for(
        has_counterexample=has_counterexample,
        differential_outcome=repository_state.differential_outcome,
        expanded_match_count=expanded_match_count,
    )
    # Aggregate confidence: max of omission-cause hypotheses, capped.
    confidences = [
        hyp.confidence_bp
        for hyp in hypotheses
        if hyp.cause
        in {
            HypothesisCause.OMISSION.value,
            HypothesisCause.BUDGET_OVERFLOW.value,
        }
    ]
    confidence = max(confidences) if confidences else 0
    counterexample_cid = (
        repository_state.counterexample_cids[0]
        if repository_state.counterexample_cids
        else None
    )
    try:
        return OmissionEvidence(
            header=_evidence_header(header),
            evidence_id=evidence_id,
            evidence_kind=kind,
            audit_case_cid=audit_case.case_cid,
            hypothesis_cids=tuple(hyp.hypothesis_cid for hyp in hypotheses),
            supporting_cids=supporting_cids,
            confidence_bp=confidence,
            differential_outcome=repository_state.differential_outcome,
            counterexample_cid=counterexample_cid,
            notes=(
                "Ranked omission evidence from compressed-fail / expanded-success "
                "differential; model reasoning is not formal evidence"
            ),
            metadata={
                "hypothesis_count": len(hypotheses),
                "expanded_match_count": expanded_match_count,
            },
        )
    except AuditContractError as exc:
        raise OmissionDiagnosisError(str(exc)) from exc


def diagnose_omission(
    audit_case: CompressionAuditCase | Mapping[str, Any],
    repository_state: RepositoryStateView | Mapping[str, Any],
    dependency_graph: DependencyGraphView | Mapping[str, Any],
    *,
    coverage_manifest: ContextCoverageManifest | Mapping[str, Any] | None = None,
    evidence_id: str | None = None,
    terminal_status: GovernorTerminalStatus | str = GovernorTerminalStatus.COMPLETE,
) -> OmissionDiagnosisResult:
    """Diagnose and rank omission versus reasoning hypotheses.

    Parameters
    ----------
    audit_case:
        Immutable compression audit-case binding (or closed mapping).
    repository_state:
        :class:`RepositoryStateView` carrying differential outcome, exclusions,
        counterexample / minimized-failure CIDs, and expanded artifact ids.
    dependency_graph:
        :class:`DependencyGraphView` of verified paths used for attribution.
    coverage_manifest:
        Optional full coverage manifest. When provided, its exclusions are
        used if ``repository_state.exclusions`` is empty, and its CID is bound
        as supporting evidence.
    evidence_id:
        Optional explicit omission-evidence id.
    terminal_status:
        Closed terminal status for durable headers (default ``complete``).

    Returns
    -------
    OmissionDiagnosisResult
        Ranked hypotheses and optional omission evidence. Identical inputs
        yield identical ``diagnosis_cid``.

    Raises
    ------
    OmissionDiagnosisError
        On fail-closed validation or inconsistent diagnosis invariants.
    """

    case = _normalize_audit_case(audit_case)
    state = _normalize_repository_state(repository_state)
    graph = _normalize_dependency_graph(dependency_graph)

    if graph.repository_state_cid != state.repository_state_cid:
        raise OmissionDiagnosisError(
            "dependency_graph.repository_state_cid must match "
            "repository_state.repository_state_cid"
        )
    if case.header.repository_state_cid != state.repository_state_cid:
        raise OmissionDiagnosisError(
            "audit_case repository_state_cid must match repository_state"
        )

    exclusions: tuple[ExcludedArtifactRecord, ...] = state.exclusions
    manifest_cid = state.coverage_manifest_cid
    if coverage_manifest is not None:
        manifest = _normalize_manifest(coverage_manifest)
        if manifest.header.repository_state_cid != state.repository_state_cid:
            raise OmissionDiagnosisError(
                "coverage_manifest repository_state_cid must match repository_state"
            )
        if case.coverage_manifest_cid not in (None, "") and (
            manifest.manifest_cid != case.coverage_manifest_cid
        ):
            # Soft bind: if audit case names a manifest CID it must match.
            if manifest.manifest_cid != case.coverage_manifest_cid:
                raise OmissionDiagnosisError(
                    "coverage_manifest CID does not match audit_case.coverage_manifest_cid"
                )
        manifest_cid = manifest.manifest_cid
        if not exclusions:
            exclusions = tuple(
                sorted(manifest.exclusions, key=lambda item: item.artifact_id)
            )
        if not state.target_symbol_ids and manifest.target_symbol_ids:
            # Rebuild state with target symbols from the manifest for ranking.
            state = RepositoryStateView(
                repository_state_cid=state.repository_state_cid,
                context_pack_cid=state.context_pack_cid,
                verification_bundle_cid=state.verification_bundle_cid,
                differential_outcome=state.differential_outcome,
                exclusions=exclusions,
                target_symbol_ids=tuple(manifest.target_symbol_ids),
                counterexample_cids=state.counterexample_cids,
                minimized_failure_cids=state.minimized_failure_cids,
                model_insufficiency_evidence_cids=(
                    state.model_insufficiency_evidence_cids
                ),
                expanded_artifact_ids=state.expanded_artifact_ids,
                coverage_manifest_cid=manifest_cid,
                policy_cid=state.policy_cid,
                notes=state.notes,
                metadata=dict(state.metadata),
            )
        else:
            exclusions = exclusions or tuple(
                sorted(manifest.exclusions, key=lambda item: item.artifact_id)
            )

    outcome = state.differential_outcome
    status = (
        terminal_status.value
        if isinstance(terminal_status, GovernorTerminalStatus)
        else str(terminal_status)
    )

    supporting: list[str] = [
        state.view_cid,
        graph.view_cid,
        case.case_cid,
        state.verification_bundle_cid,
    ]
    if manifest_cid is not None:
        supporting.append(manifest_cid)
    supporting.extend(state.counterexample_cids)
    supporting.extend(state.minimized_failure_cids)
    supporting.extend(state.model_insufficiency_evidence_cids)
    if case.differential_report_cid is not None:
        supporting.append(case.differential_report_cid)
    supporting_cids = tuple(sorted(set(supporting)))

    assumptions = _build_assumptions(state, graph)
    header = _build_header(
        repository_state=state,
        dependency_graph=graph,
        audit_case=case,
        terminal_status=status,
        input_cids=supporting_cids,
        assumptions=assumptions,
    )
    diagnosis_id = _diagnosis_id_for(case, state)

    # --- Branch: compressed fail + expanded success → ranked omission -----
    if outcome in _OMISSION_SUPPORTING_OUTCOMES:
        if not exclusions:
            raise OmissionDiagnosisError(
                "omission-supporting differential requires at least one exclusion "
                "to rank"
            )
        omission_hyps = _build_omission_hypotheses(
            exclusions=exclusions,
            repository_state=state,
            dependency_graph=graph,
            header=header,
            supporting_evidence_cids=supporting_cids,
        )
        if not omission_hyps:
            raise OmissionDiagnosisError(
                "no rankable omission candidates under supporting differential"
            )
        # Model insufficiency is not primary when expansion repaired the failure.
        all_hyps = list(omission_hyps)
        eid = (
            _token(evidence_id, "evidence_id")
            if evidence_id is not None
            else f"evidence_{diagnosis_id}"
        )
        if len(eid) > 128:
            eid = eid[:128]
        evidence = _build_omission_evidence(
            header=header,
            audit_case=case,
            repository_state=state,
            hypotheses=omission_hyps,
            supporting_cids=supporting_cids,
            evidence_id=eid,
        )
        primary = PrimaryDiagnosisCause.OMISSION.value
        if all(
            h.cause == HypothesisCause.BUDGET_OVERFLOW.value for h in omission_hyps
        ):
            primary = PrimaryDiagnosisCause.BUDGET_OVERFLOW.value
        return OmissionDiagnosisResult(
            header=header,
            diagnosis_id=diagnosis_id,
            audit_case_cid=case.case_cid,
            differential_outcome=outcome,
            primary_cause=primary,
            ranked_omission_supported=True,
            model_insufficiency_route_hypothesis=False,
            hypotheses=tuple(all_hyps),
            evidence=evidence,
            supporting_cids=supporting_cids,
            notes=(
                "Compressed failure repaired by expanded context yields ranked "
                "omission evidence"
            ),
            metadata={
                "exclusion_count": len(exclusions),
                "hypothesis_count": len(all_hyps),
                "repository_state_view_cid": state.view_cid,
                "dependency_graph_view_cid": graph.view_cid,
            },
        )

    # --- Branch: both fail → no ranked omission evidence ------------------
    if outcome in _BOTH_FAIL_OUTCOMES:
        hyps: list[OmissionHypothesis] = []
        model_route = False
        if state.model_insufficiency_evidence_cids:
            hyps.append(
                _build_model_insufficiency_hypothesis(
                    header=header,
                    supporting_evidence_cids=tuple(
                        sorted(
                            set(
                                list(state.model_insufficiency_evidence_cids)
                                + list(state.minimized_failure_cids)
                                + list(state.counterexample_cids)
                            )
                        )
                    ),
                    rank=0,
                )
            )
            model_route = True
            primary = PrimaryDiagnosisCause.MODEL_INSUFFICIENCY.value
            notes = (
                "Both-context failure does not yield ranked omission evidence; "
                "evidenced model insufficiency remains a route hypothesis"
            )
        else:
            # No formal omission blame and no evidenced model insufficiency.
            primary = PrimaryDiagnosisCause.UNKNOWN.value
            notes = (
                "Both-context failure does not yield ranked omission evidence; "
                "no evidenced model-insufficiency CIDs supplied for route hypothesis"
            )
        return OmissionDiagnosisResult(
            header=header,
            diagnosis_id=diagnosis_id,
            audit_case_cid=case.case_cid,
            differential_outcome=outcome,
            primary_cause=primary,
            ranked_omission_supported=False,
            model_insufficiency_route_hypothesis=model_route,
            hypotheses=tuple(hyps),
            evidence=None,
            supporting_cids=supporting_cids,
            notes=notes,
            metadata={
                "exclusion_count": len(exclusions),
                "hypothesis_count": len(hyps),
                "repository_state_view_cid": state.view_cid,
                "dependency_graph_view_cid": graph.view_cid,
                "both_fail_no_omission_blame": True,
            },
        )

    # --- Branch: other outcomes — no automatic compression blame ----------
    if outcome in _NO_OMISSION_RANKING_OUTCOMES:
        primary = PrimaryDiagnosisCause.NONE.value
        hyps = []
        model_route = False
        # Still allow evidenced model insufficiency as a route hypothesis when
        # explicitly supported (e.g. verification_inconclusive with evidence).
        if state.model_insufficiency_evidence_cids and outcome in {
            ComparativeOutcome.VERIFICATION_INCONCLUSIVE.value,
            ComparativeOutcome.HUMAN_REVIEW_REQUIRED.value,
        }:
            hyps.append(
                _build_model_insufficiency_hypothesis(
                    header=header,
                    supporting_evidence_cids=tuple(
                        state.model_insufficiency_evidence_cids
                    ),
                    rank=0,
                )
            )
            model_route = True
            primary = PrimaryDiagnosisCause.MODEL_INSUFFICIENCY.value
        return OmissionDiagnosisResult(
            header=header,
            diagnosis_id=diagnosis_id,
            audit_case_cid=case.case_cid,
            differential_outcome=outcome,
            primary_cause=primary,
            ranked_omission_supported=False,
            model_insufficiency_route_hypothesis=model_route,
            hypotheses=tuple(hyps),
            evidence=None,
            supporting_cids=supporting_cids,
            notes=(
                "Differential outcome does not support ranked omission evidence; "
                "compression is not automatically blamed"
            ),
            metadata={
                "exclusion_count": len(exclusions),
                "hypothesis_count": len(hyps),
                "repository_state_view_cid": state.view_cid,
                "dependency_graph_view_cid": graph.view_cid,
            },
        )

    raise OmissionDiagnosisError(
        f"unsupported differential_outcome {outcome!r}"
    )


def diagnose_omission_interface_id() -> str:
    """Return the versioned public interface pin for this diagnoser."""

    return DIAGNOSE_OMISSION_INTERFACE


def comparative_outcomes() -> tuple[str, ...]:
    """Return the closed comparative-outcome vocabulary."""

    return tuple(item.value for item in ComparativeOutcome)


def omission_supporting_outcomes() -> tuple[str, ...]:
    """Return outcomes that yield ranked omission evidence."""

    return tuple(sorted(_OMISSION_SUPPORTING_OUTCOMES))


def both_fail_outcomes() -> tuple[str, ...]:
    """Return both-context failure outcomes (no omission blame)."""

    return tuple(sorted(_BOTH_FAIL_OUTCOMES))


__all__ = [
    "DIAGNOSE_OMISSION_INTERFACE",
    "OMISSION_DIAGNOSIS_SCHEMA",
    "ComparativeOutcome",
    "DependencyGraphView",
    "OmissionDiagnosisError",
    "OmissionDiagnosisResult",
    "PrimaryDiagnosisCause",
    "RepositoryStateView",
    "both_fail_outcomes",
    "comparative_outcomes",
    "diagnose_omission",
    "diagnose_omission_interface_id",
    "omission_supporting_outcomes",
]
