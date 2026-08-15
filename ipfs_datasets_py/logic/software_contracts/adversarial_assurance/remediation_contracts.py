"""Candidate remediation and evaluation models (AAE-011).

Defines closed, versioned durable models for candidate tests, proof
obligations, policy constraints, analyzer rules, gap remediation plans,
and held-out remediation evaluation reports.

Authority rules (normative):

* Canonical bytes / CIDv1 come only from ``software_contracts.content``.
* Records are recursively immutable, closed to unknown fields, and restricted
  to strict DAG-JSON types admitted by content identity (no floats, no host
  objects, no repr fallbacks).
* Stored CIDs are verified by decode-and-recompute, never trusted alone.
* Candidate tests bind requirement provenance and intended behavior; they must
  not merely freeze the current implementation.
* Proof candidates bind proposition, assumptions, modeled/excluded state,
  source/interface connection, prover, expected counterexample, practical
  nonvacuity condition, and risk.
* Model drafts begin as ``heuristic_candidate`` and cannot self-promote.
* Evaluations encode regression and overconstraint outcomes explicitly.
* Private material, model-written authority, and host fallbacks are rejected.
* Unknown enums / statuses fail closed.
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
from ipfs_datasets_py.logic.software_contracts.adversarial_assurance.common import (
    AssuranceArtifactHeader,
    AssuranceBaseError,
    reject_private_model_authority_and_host_fallbacks,
)

# ---------------------------------------------------------------------------
# Schema / interface constants (normative)
# ---------------------------------------------------------------------------

CANDIDATE_TEST_SPECIFICATION_INTERFACE: Final[str] = "CandidateTestSpecification@1"
CANDIDATE_TEST_SPECIFICATION_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.adversarial-assurance-candidate-test-specification@1"
)
CANDIDATE_PROOF_OBLIGATION_INTERFACE: Final[str] = "CandidateProofObligation@1"
CANDIDATE_PROOF_OBLIGATION_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.adversarial-assurance-candidate-proof-obligation@1"
)
CANDIDATE_POLICY_CONSTRAINT_INTERFACE: Final[str] = "CandidatePolicyConstraint@1"
CANDIDATE_POLICY_CONSTRAINT_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.adversarial-assurance-candidate-policy-constraint@1"
)
CANDIDATE_ANALYZER_RULE_INTERFACE: Final[str] = "CandidateAnalyzerRule@1"
CANDIDATE_ANALYZER_RULE_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.adversarial-assurance-candidate-analyzer-rule@1"
)
GAP_REMEDIATION_PLAN_INTERFACE: Final[str] = "GapRemediationPlan@1"
GAP_REMEDIATION_PLAN_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.adversarial-assurance-gap-remediation-plan@1"
)
REMEDIATION_EVALUATION_REPORT_INTERFACE: Final[str] = "RemediationEvaluationReport@1"
REMEDIATION_EVALUATION_REPORT_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.adversarial-assurance-remediation-evaluation-report@1"
)
REQUIREMENT_PROVENANCE_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.adversarial-assurance-requirement-provenance@1"
)
NONVACUITY_CONDITION_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.adversarial-assurance-nonvacuity-condition@1"
)
PARTITION_EVALUATION_EVIDENCE_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.adversarial-assurance-partition-evaluation-evidence@1"
)

MAX_TEXT_CHARS: Final[int] = 16_384
MAX_CID_LIST: Final[int] = 4_096
MAX_ID_LIST: Final[int] = 4_096
MAX_TOKEN_LIST: Final[int] = 256
MAX_ASSUMPTIONS: Final[int] = 256
MAX_OBSERVATION_POINTS: Final[int] = 256
MAX_FIXTURES: Final[int] = 256
MAX_PARTITIONS: Final[int] = 32
MAX_CANDIDATES: Final[int] = 1_024
MAX_GAPS: Final[int] = 1_024
MAX_REVISION: Final[int] = 2**63 - 1
MAX_COST_BP: Final[int] = 1_000_000
MAX_PATH_CHARS: Final[int] = 1_024

_TOKEN_RE: Final[re.Pattern[str]] = re.compile(r"^[a-z][a-z0-9_.:/+-]{0,127}$")
_VERSION_RE: Final[re.Pattern[str]] = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,63}$"
)
_SYMBOL_ID_RE: Final[re.Pattern[str]] = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9_.:/+@#$-]{0,511}$"
)
_REPO_PATH_RE: Final[re.Pattern[str]] = re.compile(
    r"^(?:[A-Za-z0-9_./@+-][A-Za-z0-9_./@+-]{0,1022})$"
)

# Draft statuses that model-generated content may occupy without evaluation.
_MODEL_ADMITTED_DRAFT_STATUSES: Final[frozenset[str]] = frozenset(
    {"heuristic_candidate"}
)

# Draft statuses that require a bound evaluation report CID (no self-promotion).
_EVALUATION_REQUIRED_DRAFT_STATUSES: Final[frozenset[str]] = frozenset(
    {
        "requirement_grounded",
        "evaluation_qualified",
        "promotion_ready",
    }
)


class RemediationContractError(AssuranceBaseError):
    """Raised when a remediation contract record is malformed or unsafe."""


# ---------------------------------------------------------------------------
# Closed enumerations — candidate kinds and draft lifecycle (plan §10)
# ---------------------------------------------------------------------------


class CandidateKind(str, Enum):
    """Allowed remediation candidate types (plan §10)."""

    ADDITIONAL_TEST = "additional_test"
    STRONGER_TEST = "stronger_test"
    PROPERTY_TEST = "property_test"
    PROOF_OBLIGATION = "proof_obligation"
    PRECONDITION = "precondition"
    POSTCONDITION = "postcondition"
    POLICY_CONSTRAINT = "policy_constraint"
    STATE_MACHINE_INVARIANT = "state_machine_invariant"
    DEPENDENCY_EDGE = "dependency_edge"
    INVALIDATION_RULE = "invalidation_rule"
    CAPSULE_FIELD = "capsule_field"
    MANIFEST_REQUIREMENT = "manifest_requirement"
    FULL_SUITE_FALLBACK = "full_suite_fallback"


class CandidateDraftStatus(str, Enum):
    """Lifecycle of a remediation candidate draft.

    Model drafts begin as ``heuristic_candidate`` and cannot self-promote.
    Advancement beyond heuristic requires bound evaluation evidence.
    """

    HEURISTIC_CANDIDATE = "heuristic_candidate"
    REQUIREMENT_GROUNDED = "requirement_grounded"
    EVALUATION_QUALIFIED = "evaluation_qualified"
    PROMOTION_READY = "promotion_ready"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


class RemediationRiskClass(str, Enum):
    """Closed risk classes bound into remediation candidates and plans."""

    CRITICAL_SECURITY = "critical_security"
    AUTHORIZATION = "authorization"
    DURABILITY = "durability"
    FINANCIAL_LEGAL = "financial_legal"
    DISTRIBUTED_TRANSITION = "distributed_transition"
    PROOF_RECEIPT_TRUST = "proof_receipt_trust"
    CRITICAL_INVARIANT = "critical_invariant"
    HIGH = "high"
    MEDIUM = "medium"
    LOCAL_BUG = "local_bug"
    LOW = "low"


class MutationClassToken(str, Enum):
    """Closed mutation-class tokens a candidate test is expected to kill."""

    CONTROL_FLOW = "control_flow"
    DATA_SCHEMA = "data_schema"
    INTERFACE_CONTRACT = "interface_contract"
    SIDE_EFFECT = "side_effect"
    ERROR_RETRY = "error_retry"
    AUTHORIZATION_POLICY = "authorization_policy"
    STATE_DISTRIBUTED = "state_distributed"
    STORAGE_DURABILITY = "storage_durability"
    TEST_PROOF = "test_proof"
    SEMANTIC_COMPRESSION = "semantic_compression"
    GUI_ACTION_BINDING = "gui_action_binding"


class RemediationPlanStatus(str, Enum):
    """Closed lifecycle statuses for a gap remediation plan."""

    DRAFT = "draft"
    EVALUATION_PENDING = "evaluation_pending"
    EVALUATED = "evaluated"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


class EvaluationPartition(str, Enum):
    """Deterministic mutant evaluation partitions (plan §10)."""

    UNMUTATED = "unmutated"
    DIAGNOSIS = "diagnosis"
    DEVELOPMENT = "development"
    HELD_OUT = "held_out"
    UNRELATED = "unrelated"
    PERFORMANCE_COST = "performance_cost"
    FALSE_POSITIVE = "false_positive"
    OVERCONSTRAINT = "overconstraint"
    REGRESSION = "regression"
    SAFETY = "safety"


class EvaluationVerdict(str, Enum):
    """Closed overall verdict for a remediation evaluation report."""

    QUALIFIED = "qualified"
    REJECTED = "rejected"
    REGRESSION = "regression"
    OVERCONSTRAINT = "overconstraint"
    OVERFIT = "overfit"
    FLAKY = "flaky"
    COST_EXCEEDED = "cost_exceeded"
    SAFETY_WEAKENED = "safety_weakened"
    INCONCLUSIVE = "inconclusive"
    HUMAN_REVIEW_REQUIRED = "human_review_required"


class RejectionReason(str, Enum):
    """Closed rejection reasons for failed remediation evaluations."""

    REGRESSION = "regression"
    OVERCONSTRAINT = "overconstraint"
    OVERFIT_IMPLEMENTATION_ASSERTION = "overfit_implementation_assertion"
    FLAKE = "flake"
    MOCK_BYPASS = "mock_bypass"
    SAFETY_WEAKENING = "safety_weakening"
    IMPOSSIBLE_CORRECT_BEHAVIOR = "impossible_correct_behavior"
    UNAPPROVED_COST_INCREASE = "unapproved_cost_increase"
    MISSING_REQUIREMENT_PROVENANCE = "missing_requirement_provenance"
    MISSING_NONVACUITY = "missing_nonvacuity"
    SELF_PROMOTION = "self_promotion"
    HELD_OUT_FAILURE = "held_out_failure"
    FALSE_POSITIVE = "false_positive"
    UNRELATED_BEHAVIOR_BROKEN = "unrelated_behavior_broken"
    DIAGNOSIS_NOT_KILLED = "diagnosis_not_killed"
    UNMUTATED_SUITE_FAILED = "unmutated_suite_failed"


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _text(value: Any, name: str, *, empty: bool = False, maximum: int = MAX_TEXT_CHARS) -> str:
    if type(value) is not str or (not empty and not value):
        raise RemediationContractError(f"{name} must be a nonempty string")
    if value != value.strip() or unicodedata.normalize("NFC", value) != value:
        raise RemediationContractError(f"{name} must be trimmed NFC text")
    if len(value) > maximum or any(not char.isprintable() for char in value):
        raise RemediationContractError(f"{name} contains invalid text")
    return value


def _optional_text(
    value: Any,
    name: str,
    *,
    maximum: int = MAX_TEXT_CHARS,
) -> str | None:
    if value is None:
        return None
    return _text(value, name, maximum=maximum)


def _enum(value: Any, enum_type: type[Enum], name: str) -> str:
    try:
        return enum_type(value).value
    except (TypeError, ValueError) as exc:
        raise RemediationContractError(
            f"{name} has unsupported value {value!r}"
        ) from exc


def _cid(value: Any, name: str) -> str:
    try:
        return validate_cid(value)
    except Exception as exc:
        raise RemediationContractError(f"{name} must be a valid CID") from exc


def _optional_cid(value: Any, name: str) -> str | None:
    if value is None:
        return None
    return _cid(value, name)


def _token(value: Any, name: str) -> str:
    text = _text(value, name)
    if _TOKEN_RE.fullmatch(text) is None:
        raise RemediationContractError(
            f"{name} must be a lowercase token matching {_TOKEN_RE.pattern}"
        )
    return text


def _version(value: Any, name: str) -> str:
    text = _text(value, name)
    if _VERSION_RE.fullmatch(text) is None:
        raise RemediationContractError(
            f"{name} must be a version token matching {_VERSION_RE.pattern}"
        )
    return text


def _symbol_id(value: Any, name: str) -> str:
    text = _text(value, name)
    if _SYMBOL_ID_RE.fullmatch(text) is None:
        raise RemediationContractError(
            f"{name} must be a symbol identity matching {_SYMBOL_ID_RE.pattern}"
        )
    return text


def _repo_path(value: Any, name: str) -> str:
    text = _text(value, name)
    if len(text) > MAX_PATH_CHARS:
        raise RemediationContractError(f"{name} exceeds maximum path length")
    if text.startswith("/") or text.startswith("\\"):
        raise RemediationContractError(f"{name} rejects absolute paths")
    if ".." in text.split("/"):
        raise RemediationContractError(f"{name} rejects parent-directory traversal")
    if _REPO_PATH_RE.fullmatch(text) is None:
        raise RemediationContractError(f"{name} must be a relative repository path")
    return text


def _optional_repo_path(value: Any, name: str) -> str | None:
    if value is None:
        return None
    return _repo_path(value, name)


def _nonneg_int(value: Any, name: str, *, maximum: int = MAX_REVISION) -> int:
    if type(value) is not int or isinstance(value, bool) or value < 0:
        raise RemediationContractError(f"{name} must be a nonnegative integer")
    if value > maximum:
        raise RemediationContractError(f"{name} exceeds maximum")
    return value


def _bool(value: Any, name: str) -> bool:
    if type(value) is not bool:
        raise RemediationContractError(f"{name} must be a boolean")
    return value


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
        raise RemediationContractError(f"{name} must be a mapping")
    actual = set(data)
    if actual != fields:
        raise RemediationContractError(
            f"{name} fields must be exactly {sorted(fields)}, got {sorted(actual)}"
        )
    return dict(data)


def _require_structured(value: Any, name: str) -> Any:
    thawed = _thaw_structured(value)
    try:
        validate_structured_value(thawed, path=name)
    except Exception as exc:
        raise RemediationContractError(
            f"{name} must be strict DAG-JSON without floats or host types"
        ) from exc
    try:
        reject_private_model_authority_and_host_fallbacks(thawed, path=name)
    except AssuranceBaseError as exc:
        raise RemediationContractError(str(exc)) from exc
    return thawed


def _mapping(value: Any, name: str, *, frozen: bool = True) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise RemediationContractError(f"{name} must be a mapping")
    result = _require_structured(dict(value), name)
    return _freeze_structured(result) if frozen else result


def _unique_sorted_cids(values: Iterable[Any], name: str) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple)):
        raise RemediationContractError(f"{name} must be a list")
    ordered = tuple(sorted(_cid(value, name) for value in values))
    if len(ordered) > MAX_CID_LIST:
        raise RemediationContractError(f"{name} exceeds maximum length")
    if len(ordered) != len(set(ordered)):
        raise RemediationContractError(f"{name} must not contain duplicates")
    return ordered


def _unique_sorted_tokens(
    values: Iterable[Any],
    name: str,
    *,
    maximum: int = MAX_TOKEN_LIST,
) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple)):
        raise RemediationContractError(f"{name} must be a list")
    ordered = tuple(sorted(_token(value, name) for value in values))
    if len(ordered) > maximum:
        raise RemediationContractError(f"{name} exceeds maximum length")
    if len(ordered) != len(set(ordered)):
        raise RemediationContractError(f"{name} must not contain duplicates")
    return ordered


def _unique_sorted_symbol_ids(values: Iterable[Any], name: str) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple)):
        raise RemediationContractError(f"{name} must be a list")
    ordered = tuple(sorted(_symbol_id(value, name) for value in values))
    if len(ordered) > MAX_ID_LIST:
        raise RemediationContractError(f"{name} exceeds maximum length")
    if len(ordered) != len(set(ordered)):
        raise RemediationContractError(f"{name} must not contain duplicates")
    return ordered


def _unique_sorted_enums(
    values: Iterable[Any],
    enum_type: type[Enum],
    name: str,
    *,
    maximum: int = MAX_TOKEN_LIST,
) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple)):
        raise RemediationContractError(f"{name} must be a list")
    ordered = tuple(sorted(_enum(value, enum_type, name) for value in values))
    if len(ordered) > maximum:
        raise RemediationContractError(f"{name} exceeds maximum length")
    if len(ordered) != len(set(ordered)):
        raise RemediationContractError(f"{name} must not contain duplicates")
    return ordered


def _unique_sorted_texts(
    values: Iterable[Any],
    name: str,
    *,
    maximum: int = MAX_TOKEN_LIST,
) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple)):
        raise RemediationContractError(f"{name} must be a list")
    ordered = tuple(sorted(_text(value, name) for value in values))
    if len(ordered) > maximum:
        raise RemediationContractError(f"{name} exceeds maximum length")
    if len(ordered) != len(set(ordered)):
        raise RemediationContractError(f"{name} must not contain duplicates")
    return ordered


def _header(value: Any, name: str = "header") -> AssuranceArtifactHeader:
    if isinstance(value, AssuranceArtifactHeader):
        return value
    if isinstance(value, Mapping):
        try:
            return AssuranceArtifactHeader.from_dict(value)
        except AssuranceBaseError as exc:
            raise RemediationContractError(str(exc)) from exc
    raise RemediationContractError(f"{name} must be AssuranceArtifactHeader or mapping")


def _normalize_draft_status(
    draft_status: Any,
    evaluation_report_cid: Any,
    name: str = "draft_status",
) -> tuple[str, str | None]:
    """Normalize draft status; block model self-promotion without evaluation."""

    status = _enum(draft_status, CandidateDraftStatus, name)
    eval_cid = _optional_cid(evaluation_report_cid, "evaluation_report_cid")
    if status in _EVALUATION_REQUIRED_DRAFT_STATUSES and eval_cid is None:
        raise RemediationContractError(
            f"{name}={status!r} requires evaluation_report_cid; "
            "model drafts cannot self-promote beyond heuristic_candidate"
        )
    if status in _MODEL_ADMITTED_DRAFT_STATUSES and eval_cid is not None:
        raise RemediationContractError(
            f"{name}={status!r} must not claim evaluation_report_cid"
        )
    return status, eval_cid


# ---------------------------------------------------------------------------
# Nested: RequirementProvenance
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RequirementProvenance:
    """Requirement grounding for a remediation candidate.

    Candidate tests and other candidates must bind intended behavior to a
    requirement identity rather than merely freeze the current implementation.
    """

    requirement_id: str
    intended_behavior: str
    source_id: str
    requirement_cid: str | None = None
    source_path: str | None = None
    notes: str | None = None

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "requirement_id",
            "intended_behavior",
            "source_id",
            "requirement_cid",
            "source_path",
            "notes",
            "provenance_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "requirement_id", _token(self.requirement_id, "requirement_id")
        )
        object.__setattr__(
            self,
            "intended_behavior",
            _text(self.intended_behavior, "intended_behavior"),
        )
        object.__setattr__(self, "source_id", _token(self.source_id, "source_id"))
        object.__setattr__(
            self,
            "requirement_cid",
            _optional_cid(self.requirement_cid, "requirement_cid"),
        )
        object.__setattr__(
            self, "source_path", _optional_repo_path(self.source_path, "source_path")
        )
        object.__setattr__(self, "notes", _optional_text(self.notes, "notes"))

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": REQUIREMENT_PROVENANCE_SCHEMA,
            "requirement_id": self.requirement_id,
            "intended_behavior": self.intended_behavior,
            "source_id": self.source_id,
            "requirement_cid": self.requirement_cid,
            "source_path": self.source_path,
            "notes": self.notes,
        }

    @property
    def provenance_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        value = self.identity_payload()
        value["provenance_cid"] = self.provenance_cid
        return value

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RequirementProvenance":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("provenance_cid")
        if payload.pop("schema") != REQUIREMENT_PROVENANCE_SCHEMA:
            raise RemediationContractError(
                "unsupported RequirementProvenance schema version"
            )
        result = cls(
            requirement_id=payload["requirement_id"],
            intended_behavior=payload["intended_behavior"],
            source_id=payload["source_id"],
            requirement_cid=payload["requirement_cid"],
            source_path=payload["source_path"],
            notes=payload["notes"],
        )
        if claimed != result.provenance_cid:
            raise RemediationContractError(
                "RequirementProvenance provenance_cid identity mismatch"
            )
        return result


def _normalize_requirement_provenance(
    value: Any,
    name: str = "requirement_provenance",
) -> RequirementProvenance:
    if isinstance(value, RequirementProvenance):
        return value
    if isinstance(value, Mapping):
        return RequirementProvenance.from_dict(value)
    raise RemediationContractError(
        f"{name} must be RequirementProvenance or mapping"
    )


def _normalize_requirement_provenances(
    values: Any,
    name: str = "requirement_provenances",
) -> tuple[RequirementProvenance, ...]:
    if not isinstance(values, (list, tuple)):
        raise RemediationContractError(f"{name} must be a list")
    if not values:
        raise RemediationContractError(
            f"{name} must not be empty; candidates bind requirement provenance"
        )
    if len(values) > MAX_TOKEN_LIST:
        raise RemediationContractError(f"{name} exceeds maximum length")
    ordered = tuple(_normalize_requirement_provenance(item, name) for item in values)
    cids = [item.provenance_cid for item in ordered]
    if len(cids) != len(set(cids)):
        raise RemediationContractError(f"{name} must not contain duplicates")
    return ordered


# ---------------------------------------------------------------------------
# Nested: NonvacuityCondition
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class NonvacuityCondition:
    """Practical nonvacuity condition for a proof candidate.

    Proof obligations must state a satisfiable practical condition that
    prevents unsatisfiable antecedents and silent vacuous success.
    """

    condition_id: str
    statement: str
    assumes_satisfiable: bool = True
    excludes_unsatisfiable_antecedent: bool = True
    notes: str | None = None

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "condition_id",
            "statement",
            "assumes_satisfiable",
            "excludes_unsatisfiable_antecedent",
            "notes",
            "condition_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "condition_id", _token(self.condition_id, "condition_id")
        )
        object.__setattr__(self, "statement", _text(self.statement, "statement"))
        assumes = _bool(self.assumes_satisfiable, "assumes_satisfiable")
        excludes = _bool(
            self.excludes_unsatisfiable_antecedent,
            "excludes_unsatisfiable_antecedent",
        )
        if not assumes:
            raise RemediationContractError(
                "nonvacuity condition must assume_satisfiable=true"
            )
        if not excludes:
            raise RemediationContractError(
                "nonvacuity condition must exclude unsatisfiable antecedents"
            )
        object.__setattr__(self, "assumes_satisfiable", assumes)
        object.__setattr__(self, "excludes_unsatisfiable_antecedent", excludes)
        object.__setattr__(self, "notes", _optional_text(self.notes, "notes"))

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": NONVACUITY_CONDITION_SCHEMA,
            "condition_id": self.condition_id,
            "statement": self.statement,
            "assumes_satisfiable": self.assumes_satisfiable,
            "excludes_unsatisfiable_antecedent": self.excludes_unsatisfiable_antecedent,
            "notes": self.notes,
        }

    @property
    def condition_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        value = self.identity_payload()
        value["condition_cid"] = self.condition_cid
        return value

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "NonvacuityCondition":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("condition_cid")
        if payload.pop("schema") != NONVACUITY_CONDITION_SCHEMA:
            raise RemediationContractError(
                "unsupported NonvacuityCondition schema version"
            )
        result = cls(
            condition_id=payload["condition_id"],
            statement=payload["statement"],
            assumes_satisfiable=payload["assumes_satisfiable"],
            excludes_unsatisfiable_antecedent=payload[
                "excludes_unsatisfiable_antecedent"
            ],
            notes=payload["notes"],
        )
        if claimed != result.condition_cid:
            raise RemediationContractError(
                "NonvacuityCondition condition_cid identity mismatch"
            )
        return result


def _normalize_nonvacuity(
    value: Any,
    name: str = "nonvacuity_condition",
) -> NonvacuityCondition:
    if isinstance(value, NonvacuityCondition):
        return value
    if isinstance(value, Mapping):
        return NonvacuityCondition.from_dict(value)
    raise RemediationContractError(
        f"{name} must be NonvacuityCondition or mapping"
    )


# ---------------------------------------------------------------------------
# Nested: PartitionEvaluationEvidence
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PartitionEvaluationEvidence:
    """Evidence for one evaluation partition of a remediation candidate."""

    partition: EvaluationPartition | str
    passed: bool
    evidence_cids: Sequence[str] = ()
    mutant_ids: Sequence[str] = ()
    killed_count: int = 0
    survived_count: int = 0
    notes: str | None = None

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "partition",
            "passed",
            "evidence_cids",
            "mutant_ids",
            "killed_count",
            "survived_count",
            "notes",
            "evidence_binding_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "partition",
            _enum(self.partition, EvaluationPartition, "partition"),
        )
        object.__setattr__(self, "passed", _bool(self.passed, "passed"))
        object.__setattr__(
            self,
            "evidence_cids",
            _unique_sorted_cids(list(self.evidence_cids), "evidence_cids"),
        )
        object.__setattr__(
            self,
            "mutant_ids",
            _unique_sorted_tokens(list(self.mutant_ids), "mutant_ids"),
        )
        object.__setattr__(
            self,
            "killed_count",
            _nonneg_int(self.killed_count, "killed_count"),
        )
        object.__setattr__(
            self,
            "survived_count",
            _nonneg_int(self.survived_count, "survived_count"),
        )
        object.__setattr__(self, "notes", _optional_text(self.notes, "notes"))

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": PARTITION_EVALUATION_EVIDENCE_SCHEMA,
            "partition": self.partition,
            "passed": self.passed,
            "evidence_cids": list(self.evidence_cids),
            "mutant_ids": list(self.mutant_ids),
            "killed_count": self.killed_count,
            "survived_count": self.survived_count,
            "notes": self.notes,
        }

    @property
    def evidence_binding_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        value = self.identity_payload()
        value["evidence_binding_cid"] = self.evidence_binding_cid
        return value

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "PartitionEvaluationEvidence":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("evidence_binding_cid")
        if payload.pop("schema") != PARTITION_EVALUATION_EVIDENCE_SCHEMA:
            raise RemediationContractError(
                "unsupported PartitionEvaluationEvidence schema version"
            )
        result = cls(
            partition=payload["partition"],
            passed=payload["passed"],
            evidence_cids=payload["evidence_cids"],
            mutant_ids=payload["mutant_ids"],
            killed_count=payload["killed_count"],
            survived_count=payload["survived_count"],
            notes=payload["notes"],
        )
        if claimed != result.evidence_binding_cid:
            raise RemediationContractError(
                "PartitionEvaluationEvidence evidence_binding_cid identity mismatch"
            )
        return result


def _normalize_partition_evidence(
    value: Any,
    name: str = "partition_evidence",
) -> PartitionEvaluationEvidence:
    if isinstance(value, PartitionEvaluationEvidence):
        return value
    if isinstance(value, Mapping):
        return PartitionEvaluationEvidence.from_dict(value)
    raise RemediationContractError(
        f"{name} must be PartitionEvaluationEvidence or mapping"
    )


def _normalize_partition_evidence_list(
    values: Any,
    name: str = "partition_evidence",
) -> tuple[PartitionEvaluationEvidence, ...]:
    if not isinstance(values, (list, tuple)):
        raise RemediationContractError(f"{name} must be a list")
    if len(values) > MAX_PARTITIONS:
        raise RemediationContractError(f"{name} exceeds maximum length")
    ordered = tuple(_normalize_partition_evidence(item, name) for item in values)
    partitions = [item.partition for item in ordered]
    if len(partitions) != len(set(partitions)):
        raise RemediationContractError(f"{name} partitions must be unique")
    return ordered


# ---------------------------------------------------------------------------
# CandidateTestSpecification
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CandidateTestSpecification:
    """Requirement-grounded candidate test specification.

    Interface: ``CandidateTestSpecification@1``

    Binds intended behavior, source/symbol identities, setup/input/
    observation/fixtures, killed mutation classes, and requirement
    provenance. Must not merely freeze the current implementation.
    Model drafts begin as ``heuristic_candidate``.
    """

    header: AssuranceArtifactHeader
    candidate_id: str
    candidate_kind: CandidateKind | str
    draft_status: CandidateDraftStatus | str
    intended_behavior: str
    symbol_ids: Sequence[str]
    setup_description: str
    observation_description: str
    killed_mutation_classes: Sequence[MutationClassToken | str]
    requirement_provenances: Sequence[RequirementProvenance | Mapping[str, Any]]
    risk_class: RemediationRiskClass | str
    freezes_implementation: bool = False
    input_cid: str | None = None
    fixture_ids: Sequence[str] = ()
    observation_points: Sequence[str] = ()
    source_path: str | None = None
    gap_cids: Sequence[str] = ()
    survivor_report_cids: Sequence[str] = ()
    evaluation_report_cid: str | None = None
    notes: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "interface_id",
            "header",
            "candidate_id",
            "candidate_kind",
            "draft_status",
            "intended_behavior",
            "symbol_ids",
            "setup_description",
            "observation_description",
            "killed_mutation_classes",
            "requirement_provenances",
            "risk_class",
            "freezes_implementation",
            "input_cid",
            "fixture_ids",
            "observation_points",
            "source_path",
            "gap_cids",
            "survivor_report_cids",
            "evaluation_report_cid",
            "notes",
            "metadata",
            "candidate_cid",
        }
    )

    _ALLOWED_KINDS: ClassVar[frozenset[str]] = frozenset(
        {
            CandidateKind.ADDITIONAL_TEST.value,
            CandidateKind.STRONGER_TEST.value,
            CandidateKind.PROPERTY_TEST.value,
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "header", _header(self.header))
        if self.header.artifact_kind != "candidate_test_specification":
            raise RemediationContractError(
                "header.artifact_kind must be candidate_test_specification"
            )
        object.__setattr__(
            self, "candidate_id", _token(self.candidate_id, "candidate_id")
        )
        kind = _enum(self.candidate_kind, CandidateKind, "candidate_kind")
        if kind not in self._ALLOWED_KINDS:
            raise RemediationContractError(
                f"candidate_kind {kind!r} is not a test candidate kind"
            )
        object.__setattr__(self, "candidate_kind", kind)
        status, eval_cid = _normalize_draft_status(
            self.draft_status, self.evaluation_report_cid
        )
        object.__setattr__(self, "draft_status", status)
        object.__setattr__(self, "evaluation_report_cid", eval_cid)
        object.__setattr__(
            self, "intended_behavior", _text(self.intended_behavior, "intended_behavior")
        )
        symbols = _unique_sorted_symbol_ids(list(self.symbol_ids), "symbol_ids")
        if not symbols:
            raise RemediationContractError("symbol_ids must not be empty")
        object.__setattr__(self, "symbol_ids", symbols)
        object.__setattr__(
            self, "setup_description", _text(self.setup_description, "setup_description")
        )
        object.__setattr__(
            self,
            "observation_description",
            _text(self.observation_description, "observation_description"),
        )
        killed = _unique_sorted_enums(
            list(self.killed_mutation_classes),
            MutationClassToken,
            "killed_mutation_classes",
        )
        if not killed:
            raise RemediationContractError(
                "killed_mutation_classes must not be empty"
            )
        object.__setattr__(self, "killed_mutation_classes", killed)
        provenances = _normalize_requirement_provenances(
            list(self.requirement_provenances), "requirement_provenances"
        )
        # Intended behavior must agree with at least one requirement provenance.
        if not any(
            item.intended_behavior == self.intended_behavior for item in provenances
        ):
            raise RemediationContractError(
                "intended_behavior must match a requirement_provenances entry"
            )
        object.__setattr__(self, "requirement_provenances", provenances)
        object.__setattr__(
            self,
            "risk_class",
            _enum(self.risk_class, RemediationRiskClass, "risk_class"),
        )
        freezes = _bool(self.freezes_implementation, "freezes_implementation")
        if freezes:
            raise RemediationContractError(
                "candidate tests must not merely freeze the current implementation"
            )
        object.__setattr__(self, "freezes_implementation", freezes)
        object.__setattr__(
            self, "input_cid", _optional_cid(self.input_cid, "input_cid")
        )
        object.__setattr__(
            self,
            "fixture_ids",
            _unique_sorted_tokens(
                list(self.fixture_ids), "fixture_ids", maximum=MAX_FIXTURES
            ),
        )
        object.__setattr__(
            self,
            "observation_points",
            _unique_sorted_tokens(
                list(self.observation_points),
                "observation_points",
                maximum=MAX_OBSERVATION_POINTS,
            ),
        )
        object.__setattr__(
            self, "source_path", _optional_repo_path(self.source_path, "source_path")
        )
        object.__setattr__(
            self,
            "gap_cids",
            _unique_sorted_cids(list(self.gap_cids), "gap_cids"),
        )
        object.__setattr__(
            self,
            "survivor_report_cids",
            _unique_sorted_cids(
                list(self.survivor_report_cids), "survivor_report_cids"
            ),
        )
        object.__setattr__(self, "notes", _optional_text(self.notes, "notes"))
        object.__setattr__(self, "metadata", _mapping(self.metadata, "metadata"))

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": CANDIDATE_TEST_SPECIFICATION_SCHEMA,
            "interface_id": CANDIDATE_TEST_SPECIFICATION_INTERFACE,
            "header": self.header.identity_payload(),
            "candidate_id": self.candidate_id,
            "candidate_kind": self.candidate_kind,
            "draft_status": self.draft_status,
            "intended_behavior": self.intended_behavior,
            "symbol_ids": list(self.symbol_ids),
            "setup_description": self.setup_description,
            "observation_description": self.observation_description,
            "killed_mutation_classes": list(self.killed_mutation_classes),
            "requirement_provenances": [
                item.identity_payload() for item in self.requirement_provenances
            ],
            "risk_class": self.risk_class,
            "freezes_implementation": self.freezes_implementation,
            "input_cid": self.input_cid,
            "fixture_ids": list(self.fixture_ids),
            "observation_points": list(self.observation_points),
            "source_path": self.source_path,
            "gap_cids": list(self.gap_cids),
            "survivor_report_cids": list(self.survivor_report_cids),
            "evaluation_report_cid": self.evaluation_report_cid,
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
        }

    @property
    def candidate_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def is_model_draft(self) -> bool:
        """Return True when this record is still a model heuristic draft."""

        return self.draft_status == CandidateDraftStatus.HEURISTIC_CANDIDATE.value

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": CANDIDATE_TEST_SPECIFICATION_SCHEMA,
            "interface_id": CANDIDATE_TEST_SPECIFICATION_INTERFACE,
            "header": self.header.to_dict(),
            "candidate_id": self.candidate_id,
            "candidate_kind": self.candidate_kind,
            "draft_status": self.draft_status,
            "intended_behavior": self.intended_behavior,
            "symbol_ids": list(self.symbol_ids),
            "setup_description": self.setup_description,
            "observation_description": self.observation_description,
            "killed_mutation_classes": list(self.killed_mutation_classes),
            "requirement_provenances": [
                item.to_dict() for item in self.requirement_provenances
            ],
            "risk_class": self.risk_class,
            "freezes_implementation": self.freezes_implementation,
            "input_cid": self.input_cid,
            "fixture_ids": list(self.fixture_ids),
            "observation_points": list(self.observation_points),
            "source_path": self.source_path,
            "gap_cids": list(self.gap_cids),
            "survivor_report_cids": list(self.survivor_report_cids),
            "evaluation_report_cid": self.evaluation_report_cid,
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
            "candidate_cid": self.candidate_cid,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "CandidateTestSpecification":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("candidate_cid")
        if payload.pop("schema") != CANDIDATE_TEST_SPECIFICATION_SCHEMA:
            raise RemediationContractError(
                "unsupported CandidateTestSpecification schema version"
            )
        if payload.pop("interface_id") != CANDIDATE_TEST_SPECIFICATION_INTERFACE:
            raise RemediationContractError(
                "unsupported CandidateTestSpecification interface_id"
            )
        result = cls(
            header=payload["header"],
            candidate_id=payload["candidate_id"],
            candidate_kind=payload["candidate_kind"],
            draft_status=payload["draft_status"],
            intended_behavior=payload["intended_behavior"],
            symbol_ids=payload["symbol_ids"],
            setup_description=payload["setup_description"],
            observation_description=payload["observation_description"],
            killed_mutation_classes=payload["killed_mutation_classes"],
            requirement_provenances=payload["requirement_provenances"],
            risk_class=payload["risk_class"],
            freezes_implementation=payload["freezes_implementation"],
            input_cid=payload["input_cid"],
            fixture_ids=payload["fixture_ids"],
            observation_points=payload["observation_points"],
            source_path=payload["source_path"],
            gap_cids=payload["gap_cids"],
            survivor_report_cids=payload["survivor_report_cids"],
            evaluation_report_cid=payload["evaluation_report_cid"],
            notes=payload["notes"],
            metadata=payload["metadata"],
        )
        if claimed != result.candidate_cid:
            raise RemediationContractError(
                "CandidateTestSpecification candidate_cid identity mismatch"
            )
        return result


# ---------------------------------------------------------------------------
# CandidateProofObligation
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CandidateProofObligation:
    """Candidate proof obligation with nonvacuity and source connection.

    Interface: ``CandidateProofObligation@1``

    Binds proposition, assumptions, modeled/excluded state, source/interface
    connection, prover, expected counterexample, practical nonvacuity
    condition, and risk. Model drafts begin as ``heuristic_candidate``.
    """

    header: AssuranceArtifactHeader
    candidate_id: str
    draft_status: CandidateDraftStatus | str
    proposition: str
    assumptions: Sequence[str]
    modeled_state_ids: Sequence[str]
    excluded_state_ids: Sequence[str]
    source_connection: str
    interface_connection: str
    prover_id: str
    expected_counterexample: str
    nonvacuity_condition: NonvacuityCondition | Mapping[str, Any]
    risk_class: RemediationRiskClass | str
    requirement_provenances: Sequence[RequirementProvenance | Mapping[str, Any]]
    symbol_ids: Sequence[str]
    gap_cids: Sequence[str] = ()
    evaluation_report_cid: str | None = None
    notes: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "interface_id",
            "header",
            "candidate_id",
            "draft_status",
            "proposition",
            "assumptions",
            "modeled_state_ids",
            "excluded_state_ids",
            "source_connection",
            "interface_connection",
            "prover_id",
            "expected_counterexample",
            "nonvacuity_condition",
            "risk_class",
            "requirement_provenances",
            "symbol_ids",
            "gap_cids",
            "evaluation_report_cid",
            "notes",
            "metadata",
            "candidate_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "header", _header(self.header))
        if self.header.artifact_kind != "candidate_proof_obligation":
            raise RemediationContractError(
                "header.artifact_kind must be candidate_proof_obligation"
            )
        object.__setattr__(
            self, "candidate_id", _token(self.candidate_id, "candidate_id")
        )
        status, eval_cid = _normalize_draft_status(
            self.draft_status, self.evaluation_report_cid
        )
        object.__setattr__(self, "draft_status", status)
        object.__setattr__(self, "evaluation_report_cid", eval_cid)
        object.__setattr__(
            self, "proposition", _text(self.proposition, "proposition")
        )
        assumptions = _unique_sorted_texts(
            list(self.assumptions), "assumptions", maximum=MAX_ASSUMPTIONS
        )
        if not assumptions:
            raise RemediationContractError(
                "assumptions must not be empty; proof obligations bind assumptions"
            )
        object.__setattr__(self, "assumptions", assumptions)
        modeled = _unique_sorted_tokens(
            list(self.modeled_state_ids), "modeled_state_ids"
        )
        excluded = _unique_sorted_tokens(
            list(self.excluded_state_ids), "excluded_state_ids"
        )
        if set(modeled) & set(excluded):
            raise RemediationContractError(
                "modeled_state_ids and excluded_state_ids must be disjoint"
            )
        object.__setattr__(self, "modeled_state_ids", modeled)
        object.__setattr__(self, "excluded_state_ids", excluded)
        object.__setattr__(
            self,
            "source_connection",
            _text(self.source_connection, "source_connection"),
        )
        object.__setattr__(
            self,
            "interface_connection",
            _text(self.interface_connection, "interface_connection"),
        )
        object.__setattr__(self, "prover_id", _token(self.prover_id, "prover_id"))
        object.__setattr__(
            self,
            "expected_counterexample",
            _text(self.expected_counterexample, "expected_counterexample"),
        )
        nonvacuity = _normalize_nonvacuity(self.nonvacuity_condition)
        object.__setattr__(self, "nonvacuity_condition", nonvacuity)
        object.__setattr__(
            self,
            "risk_class",
            _enum(self.risk_class, RemediationRiskClass, "risk_class"),
        )
        provenances = _normalize_requirement_provenances(
            list(self.requirement_provenances), "requirement_provenances"
        )
        object.__setattr__(self, "requirement_provenances", provenances)
        symbols = _unique_sorted_symbol_ids(list(self.symbol_ids), "symbol_ids")
        if not symbols:
            raise RemediationContractError("symbol_ids must not be empty")
        object.__setattr__(self, "symbol_ids", symbols)
        object.__setattr__(
            self, "gap_cids", _unique_sorted_cids(list(self.gap_cids), "gap_cids")
        )
        object.__setattr__(self, "notes", _optional_text(self.notes, "notes"))
        object.__setattr__(self, "metadata", _mapping(self.metadata, "metadata"))

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": CANDIDATE_PROOF_OBLIGATION_SCHEMA,
            "interface_id": CANDIDATE_PROOF_OBLIGATION_INTERFACE,
            "header": self.header.identity_payload(),
            "candidate_id": self.candidate_id,
            "draft_status": self.draft_status,
            "proposition": self.proposition,
            "assumptions": list(self.assumptions),
            "modeled_state_ids": list(self.modeled_state_ids),
            "excluded_state_ids": list(self.excluded_state_ids),
            "source_connection": self.source_connection,
            "interface_connection": self.interface_connection,
            "prover_id": self.prover_id,
            "expected_counterexample": self.expected_counterexample,
            "nonvacuity_condition": self.nonvacuity_condition.identity_payload(),
            "risk_class": self.risk_class,
            "requirement_provenances": [
                item.identity_payload() for item in self.requirement_provenances
            ],
            "symbol_ids": list(self.symbol_ids),
            "gap_cids": list(self.gap_cids),
            "evaluation_report_cid": self.evaluation_report_cid,
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
        }

    @property
    def candidate_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def is_model_draft(self) -> bool:
        return self.draft_status == CandidateDraftStatus.HEURISTIC_CANDIDATE.value

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": CANDIDATE_PROOF_OBLIGATION_SCHEMA,
            "interface_id": CANDIDATE_PROOF_OBLIGATION_INTERFACE,
            "header": self.header.to_dict(),
            "candidate_id": self.candidate_id,
            "draft_status": self.draft_status,
            "proposition": self.proposition,
            "assumptions": list(self.assumptions),
            "modeled_state_ids": list(self.modeled_state_ids),
            "excluded_state_ids": list(self.excluded_state_ids),
            "source_connection": self.source_connection,
            "interface_connection": self.interface_connection,
            "prover_id": self.prover_id,
            "expected_counterexample": self.expected_counterexample,
            "nonvacuity_condition": self.nonvacuity_condition.to_dict(),
            "risk_class": self.risk_class,
            "requirement_provenances": [
                item.to_dict() for item in self.requirement_provenances
            ],
            "symbol_ids": list(self.symbol_ids),
            "gap_cids": list(self.gap_cids),
            "evaluation_report_cid": self.evaluation_report_cid,
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
            "candidate_cid": self.candidate_cid,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "CandidateProofObligation":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("candidate_cid")
        if payload.pop("schema") != CANDIDATE_PROOF_OBLIGATION_SCHEMA:
            raise RemediationContractError(
                "unsupported CandidateProofObligation schema version"
            )
        if payload.pop("interface_id") != CANDIDATE_PROOF_OBLIGATION_INTERFACE:
            raise RemediationContractError(
                "unsupported CandidateProofObligation interface_id"
            )
        result = cls(
            header=payload["header"],
            candidate_id=payload["candidate_id"],
            draft_status=payload["draft_status"],
            proposition=payload["proposition"],
            assumptions=payload["assumptions"],
            modeled_state_ids=payload["modeled_state_ids"],
            excluded_state_ids=payload["excluded_state_ids"],
            source_connection=payload["source_connection"],
            interface_connection=payload["interface_connection"],
            prover_id=payload["prover_id"],
            expected_counterexample=payload["expected_counterexample"],
            nonvacuity_condition=payload["nonvacuity_condition"],
            risk_class=payload["risk_class"],
            requirement_provenances=payload["requirement_provenances"],
            symbol_ids=payload["symbol_ids"],
            gap_cids=payload["gap_cids"],
            evaluation_report_cid=payload["evaluation_report_cid"],
            notes=payload["notes"],
            metadata=payload["metadata"],
        )
        if claimed != result.candidate_cid:
            raise RemediationContractError(
                "CandidateProofObligation candidate_cid identity mismatch"
            )
        return result


# ---------------------------------------------------------------------------
# CandidatePolicyConstraint
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CandidatePolicyConstraint:
    """Candidate policy constraint for gap remediation.

    Interface: ``CandidatePolicyConstraint@1``

    Model drafts begin as ``heuristic_candidate`` and cannot self-promote.
    """

    header: AssuranceArtifactHeader
    candidate_id: str
    draft_status: CandidateDraftStatus | str
    constraint_statement: str
    policy_surface_id: str
    symbol_ids: Sequence[str]
    requirement_provenances: Sequence[RequirementProvenance | Mapping[str, Any]]
    risk_class: RemediationRiskClass | str
    default_deny: bool = True
    gap_cids: Sequence[str] = ()
    evaluation_report_cid: str | None = None
    notes: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "interface_id",
            "header",
            "candidate_id",
            "draft_status",
            "constraint_statement",
            "policy_surface_id",
            "symbol_ids",
            "requirement_provenances",
            "risk_class",
            "default_deny",
            "gap_cids",
            "evaluation_report_cid",
            "notes",
            "metadata",
            "candidate_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "header", _header(self.header))
        if self.header.artifact_kind != "candidate_policy_constraint":
            raise RemediationContractError(
                "header.artifact_kind must be candidate_policy_constraint"
            )
        object.__setattr__(
            self, "candidate_id", _token(self.candidate_id, "candidate_id")
        )
        status, eval_cid = _normalize_draft_status(
            self.draft_status, self.evaluation_report_cid
        )
        object.__setattr__(self, "draft_status", status)
        object.__setattr__(self, "evaluation_report_cid", eval_cid)
        object.__setattr__(
            self,
            "constraint_statement",
            _text(self.constraint_statement, "constraint_statement"),
        )
        object.__setattr__(
            self,
            "policy_surface_id",
            _token(self.policy_surface_id, "policy_surface_id"),
        )
        symbols = _unique_sorted_symbol_ids(list(self.symbol_ids), "symbol_ids")
        if not symbols:
            raise RemediationContractError("symbol_ids must not be empty")
        object.__setattr__(self, "symbol_ids", symbols)
        provenances = _normalize_requirement_provenances(
            list(self.requirement_provenances), "requirement_provenances"
        )
        object.__setattr__(self, "requirement_provenances", provenances)
        object.__setattr__(
            self,
            "risk_class",
            _enum(self.risk_class, RemediationRiskClass, "risk_class"),
        )
        object.__setattr__(
            self, "default_deny", _bool(self.default_deny, "default_deny")
        )
        object.__setattr__(
            self, "gap_cids", _unique_sorted_cids(list(self.gap_cids), "gap_cids")
        )
        object.__setattr__(self, "notes", _optional_text(self.notes, "notes"))
        object.__setattr__(self, "metadata", _mapping(self.metadata, "metadata"))

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": CANDIDATE_POLICY_CONSTRAINT_SCHEMA,
            "interface_id": CANDIDATE_POLICY_CONSTRAINT_INTERFACE,
            "header": self.header.identity_payload(),
            "candidate_id": self.candidate_id,
            "draft_status": self.draft_status,
            "constraint_statement": self.constraint_statement,
            "policy_surface_id": self.policy_surface_id,
            "symbol_ids": list(self.symbol_ids),
            "requirement_provenances": [
                item.identity_payload() for item in self.requirement_provenances
            ],
            "risk_class": self.risk_class,
            "default_deny": self.default_deny,
            "gap_cids": list(self.gap_cids),
            "evaluation_report_cid": self.evaluation_report_cid,
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
        }

    @property
    def candidate_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def is_model_draft(self) -> bool:
        return self.draft_status == CandidateDraftStatus.HEURISTIC_CANDIDATE.value

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": CANDIDATE_POLICY_CONSTRAINT_SCHEMA,
            "interface_id": CANDIDATE_POLICY_CONSTRAINT_INTERFACE,
            "header": self.header.to_dict(),
            "candidate_id": self.candidate_id,
            "draft_status": self.draft_status,
            "constraint_statement": self.constraint_statement,
            "policy_surface_id": self.policy_surface_id,
            "symbol_ids": list(self.symbol_ids),
            "requirement_provenances": [
                item.to_dict() for item in self.requirement_provenances
            ],
            "risk_class": self.risk_class,
            "default_deny": self.default_deny,
            "gap_cids": list(self.gap_cids),
            "evaluation_report_cid": self.evaluation_report_cid,
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
            "candidate_cid": self.candidate_cid,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "CandidatePolicyConstraint":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("candidate_cid")
        if payload.pop("schema") != CANDIDATE_POLICY_CONSTRAINT_SCHEMA:
            raise RemediationContractError(
                "unsupported CandidatePolicyConstraint schema version"
            )
        if payload.pop("interface_id") != CANDIDATE_POLICY_CONSTRAINT_INTERFACE:
            raise RemediationContractError(
                "unsupported CandidatePolicyConstraint interface_id"
            )
        result = cls(
            header=payload["header"],
            candidate_id=payload["candidate_id"],
            draft_status=payload["draft_status"],
            constraint_statement=payload["constraint_statement"],
            policy_surface_id=payload["policy_surface_id"],
            symbol_ids=payload["symbol_ids"],
            requirement_provenances=payload["requirement_provenances"],
            risk_class=payload["risk_class"],
            default_deny=payload["default_deny"],
            gap_cids=payload["gap_cids"],
            evaluation_report_cid=payload["evaluation_report_cid"],
            notes=payload["notes"],
            metadata=payload["metadata"],
        )
        if claimed != result.candidate_cid:
            raise RemediationContractError(
                "CandidatePolicyConstraint candidate_cid identity mismatch"
            )
        return result


# ---------------------------------------------------------------------------
# CandidateAnalyzerRule
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CandidateAnalyzerRule:
    """Candidate static/dynamic analyzer rule for gap remediation.

    Interface: ``CandidateAnalyzerRule@1``

    Model drafts begin as ``heuristic_candidate`` and cannot self-promote.
    """

    header: AssuranceArtifactHeader
    candidate_id: str
    draft_status: CandidateDraftStatus | str
    rule_statement: str
    analyzer_id: str
    symbol_ids: Sequence[str]
    killed_mutation_classes: Sequence[MutationClassToken | str]
    requirement_provenances: Sequence[RequirementProvenance | Mapping[str, Any]]
    risk_class: RemediationRiskClass | str
    gap_cids: Sequence[str] = ()
    evaluation_report_cid: str | None = None
    notes: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "interface_id",
            "header",
            "candidate_id",
            "draft_status",
            "rule_statement",
            "analyzer_id",
            "symbol_ids",
            "killed_mutation_classes",
            "requirement_provenances",
            "risk_class",
            "gap_cids",
            "evaluation_report_cid",
            "notes",
            "metadata",
            "candidate_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "header", _header(self.header))
        if self.header.artifact_kind != "candidate_analyzer_rule":
            raise RemediationContractError(
                "header.artifact_kind must be candidate_analyzer_rule"
            )
        object.__setattr__(
            self, "candidate_id", _token(self.candidate_id, "candidate_id")
        )
        status, eval_cid = _normalize_draft_status(
            self.draft_status, self.evaluation_report_cid
        )
        object.__setattr__(self, "draft_status", status)
        object.__setattr__(self, "evaluation_report_cid", eval_cid)
        object.__setattr__(
            self, "rule_statement", _text(self.rule_statement, "rule_statement")
        )
        object.__setattr__(
            self, "analyzer_id", _token(self.analyzer_id, "analyzer_id")
        )
        symbols = _unique_sorted_symbol_ids(list(self.symbol_ids), "symbol_ids")
        if not symbols:
            raise RemediationContractError("symbol_ids must not be empty")
        object.__setattr__(self, "symbol_ids", symbols)
        killed = _unique_sorted_enums(
            list(self.killed_mutation_classes),
            MutationClassToken,
            "killed_mutation_classes",
        )
        if not killed:
            raise RemediationContractError(
                "killed_mutation_classes must not be empty"
            )
        object.__setattr__(self, "killed_mutation_classes", killed)
        provenances = _normalize_requirement_provenances(
            list(self.requirement_provenances), "requirement_provenances"
        )
        object.__setattr__(self, "requirement_provenances", provenances)
        object.__setattr__(
            self,
            "risk_class",
            _enum(self.risk_class, RemediationRiskClass, "risk_class"),
        )
        object.__setattr__(
            self, "gap_cids", _unique_sorted_cids(list(self.gap_cids), "gap_cids")
        )
        object.__setattr__(self, "notes", _optional_text(self.notes, "notes"))
        object.__setattr__(self, "metadata", _mapping(self.metadata, "metadata"))

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": CANDIDATE_ANALYZER_RULE_SCHEMA,
            "interface_id": CANDIDATE_ANALYZER_RULE_INTERFACE,
            "header": self.header.identity_payload(),
            "candidate_id": self.candidate_id,
            "draft_status": self.draft_status,
            "rule_statement": self.rule_statement,
            "analyzer_id": self.analyzer_id,
            "symbol_ids": list(self.symbol_ids),
            "killed_mutation_classes": list(self.killed_mutation_classes),
            "requirement_provenances": [
                item.identity_payload() for item in self.requirement_provenances
            ],
            "risk_class": self.risk_class,
            "gap_cids": list(self.gap_cids),
            "evaluation_report_cid": self.evaluation_report_cid,
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
        }

    @property
    def candidate_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def is_model_draft(self) -> bool:
        return self.draft_status == CandidateDraftStatus.HEURISTIC_CANDIDATE.value

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": CANDIDATE_ANALYZER_RULE_SCHEMA,
            "interface_id": CANDIDATE_ANALYZER_RULE_INTERFACE,
            "header": self.header.to_dict(),
            "candidate_id": self.candidate_id,
            "draft_status": self.draft_status,
            "rule_statement": self.rule_statement,
            "analyzer_id": self.analyzer_id,
            "symbol_ids": list(self.symbol_ids),
            "killed_mutation_classes": list(self.killed_mutation_classes),
            "requirement_provenances": [
                item.to_dict() for item in self.requirement_provenances
            ],
            "risk_class": self.risk_class,
            "gap_cids": list(self.gap_cids),
            "evaluation_report_cid": self.evaluation_report_cid,
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
            "candidate_cid": self.candidate_cid,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "CandidateAnalyzerRule":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("candidate_cid")
        if payload.pop("schema") != CANDIDATE_ANALYZER_RULE_SCHEMA:
            raise RemediationContractError(
                "unsupported CandidateAnalyzerRule schema version"
            )
        if payload.pop("interface_id") != CANDIDATE_ANALYZER_RULE_INTERFACE:
            raise RemediationContractError(
                "unsupported CandidateAnalyzerRule interface_id"
            )
        result = cls(
            header=payload["header"],
            candidate_id=payload["candidate_id"],
            draft_status=payload["draft_status"],
            rule_statement=payload["rule_statement"],
            analyzer_id=payload["analyzer_id"],
            symbol_ids=payload["symbol_ids"],
            killed_mutation_classes=payload["killed_mutation_classes"],
            requirement_provenances=payload["requirement_provenances"],
            risk_class=payload["risk_class"],
            gap_cids=payload["gap_cids"],
            evaluation_report_cid=payload["evaluation_report_cid"],
            notes=payload["notes"],
            metadata=payload["metadata"],
        )
        if claimed != result.candidate_cid:
            raise RemediationContractError(
                "CandidateAnalyzerRule candidate_cid identity mismatch"
            )
        return result


# ---------------------------------------------------------------------------
# GapRemediationPlan
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class GapRemediationPlan:
    """Plan binding candidate remediations to diagnosed assurance gaps.

    Interface: ``GapRemediationPlan@1``

    Collects candidate test/proof/policy/analyzer CIDs against gap CIDs with
    a closed plan status. Held-out evaluation is required before promotion.
    """

    header: AssuranceArtifactHeader
    plan_id: str
    plan_status: RemediationPlanStatus | str
    summary: str
    gap_cids: Sequence[str]
    candidate_test_cids: Sequence[str] = ()
    candidate_proof_cids: Sequence[str] = ()
    candidate_policy_cids: Sequence[str] = ()
    candidate_analyzer_cids: Sequence[str] = ()
    requires_held_out_evaluation: bool = True
    evaluation_report_cid: str | None = None
    notes: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "interface_id",
            "header",
            "plan_id",
            "plan_status",
            "summary",
            "gap_cids",
            "candidate_test_cids",
            "candidate_proof_cids",
            "candidate_policy_cids",
            "candidate_analyzer_cids",
            "requires_held_out_evaluation",
            "evaluation_report_cid",
            "notes",
            "metadata",
            "plan_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "header", _header(self.header))
        if self.header.artifact_kind != "gap_remediation_plan":
            raise RemediationContractError(
                "header.artifact_kind must be gap_remediation_plan"
            )
        object.__setattr__(self, "plan_id", _token(self.plan_id, "plan_id"))
        status = _enum(self.plan_status, RemediationPlanStatus, "plan_status")
        object.__setattr__(self, "plan_status", status)
        object.__setattr__(self, "summary", _text(self.summary, "summary"))
        gaps = _unique_sorted_cids(list(self.gap_cids), "gap_cids")
        if not gaps:
            raise RemediationContractError("gap_cids must not be empty")
        if len(gaps) > MAX_GAPS:
            raise RemediationContractError("gap_cids exceeds maximum length")
        object.__setattr__(self, "gap_cids", gaps)
        tests = _unique_sorted_cids(
            list(self.candidate_test_cids), "candidate_test_cids"
        )
        proofs = _unique_sorted_cids(
            list(self.candidate_proof_cids), "candidate_proof_cids"
        )
        policies = _unique_sorted_cids(
            list(self.candidate_policy_cids), "candidate_policy_cids"
        )
        analyzers = _unique_sorted_cids(
            list(self.candidate_analyzer_cids), "candidate_analyzer_cids"
        )
        total = len(tests) + len(proofs) + len(policies) + len(analyzers)
        if total == 0:
            raise RemediationContractError(
                "plan must bind at least one candidate remediation"
            )
        if total > MAX_CANDIDATES:
            raise RemediationContractError(
                "total candidate CIDs exceed maximum"
            )
        object.__setattr__(self, "candidate_test_cids", tests)
        object.__setattr__(self, "candidate_proof_cids", proofs)
        object.__setattr__(self, "candidate_policy_cids", policies)
        object.__setattr__(self, "candidate_analyzer_cids", analyzers)
        requires_held_out = _bool(
            self.requires_held_out_evaluation, "requires_held_out_evaluation"
        )
        if not requires_held_out:
            raise RemediationContractError(
                "requires_held_out_evaluation must be true"
            )
        object.__setattr__(self, "requires_held_out_evaluation", requires_held_out)
        eval_cid = _optional_cid(
            self.evaluation_report_cid, "evaluation_report_cid"
        )
        if status == RemediationPlanStatus.EVALUATED.value and eval_cid is None:
            raise RemediationContractError(
                "plan_status evaluated requires evaluation_report_cid"
            )
        object.__setattr__(self, "evaluation_report_cid", eval_cid)
        object.__setattr__(self, "notes", _optional_text(self.notes, "notes"))
        object.__setattr__(self, "metadata", _mapping(self.metadata, "metadata"))

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": GAP_REMEDIATION_PLAN_SCHEMA,
            "interface_id": GAP_REMEDIATION_PLAN_INTERFACE,
            "header": self.header.identity_payload(),
            "plan_id": self.plan_id,
            "plan_status": self.plan_status,
            "summary": self.summary,
            "gap_cids": list(self.gap_cids),
            "candidate_test_cids": list(self.candidate_test_cids),
            "candidate_proof_cids": list(self.candidate_proof_cids),
            "candidate_policy_cids": list(self.candidate_policy_cids),
            "candidate_analyzer_cids": list(self.candidate_analyzer_cids),
            "requires_held_out_evaluation": self.requires_held_out_evaluation,
            "evaluation_report_cid": self.evaluation_report_cid,
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
        }

    @property
    def plan_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": GAP_REMEDIATION_PLAN_SCHEMA,
            "interface_id": GAP_REMEDIATION_PLAN_INTERFACE,
            "header": self.header.to_dict(),
            "plan_id": self.plan_id,
            "plan_status": self.plan_status,
            "summary": self.summary,
            "gap_cids": list(self.gap_cids),
            "candidate_test_cids": list(self.candidate_test_cids),
            "candidate_proof_cids": list(self.candidate_proof_cids),
            "candidate_policy_cids": list(self.candidate_policy_cids),
            "candidate_analyzer_cids": list(self.candidate_analyzer_cids),
            "requires_held_out_evaluation": self.requires_held_out_evaluation,
            "evaluation_report_cid": self.evaluation_report_cid,
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
            "plan_cid": self.plan_cid,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "GapRemediationPlan":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("plan_cid")
        if payload.pop("schema") != GAP_REMEDIATION_PLAN_SCHEMA:
            raise RemediationContractError(
                "unsupported GapRemediationPlan schema version"
            )
        if payload.pop("interface_id") != GAP_REMEDIATION_PLAN_INTERFACE:
            raise RemediationContractError(
                "unsupported GapRemediationPlan interface_id"
            )
        result = cls(
            header=payload["header"],
            plan_id=payload["plan_id"],
            plan_status=payload["plan_status"],
            summary=payload["summary"],
            gap_cids=payload["gap_cids"],
            candidate_test_cids=payload["candidate_test_cids"],
            candidate_proof_cids=payload["candidate_proof_cids"],
            candidate_policy_cids=payload["candidate_policy_cids"],
            candidate_analyzer_cids=payload["candidate_analyzer_cids"],
            requires_held_out_evaluation=payload["requires_held_out_evaluation"],
            evaluation_report_cid=payload["evaluation_report_cid"],
            notes=payload["notes"],
            metadata=payload["metadata"],
        )
        if claimed != result.plan_cid:
            raise RemediationContractError(
                "GapRemediationPlan plan_cid identity mismatch"
            )
        return result


# ---------------------------------------------------------------------------
# RemediationEvaluationReport
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RemediationEvaluationReport:
    """Held-out remediation evaluation with regression and overconstraint.

    Interface: ``RemediationEvaluationReport@1``

    Encodes evaluation across unmutated, diagnosis, development, held-out,
    unrelated, performance/cost, false-positive, overconstraint, regression,
    and safety partitions. Explicitly records regression and overconstraint
    flags; rejects self-authorization of promotion.
    """

    header: AssuranceArtifactHeader
    report_id: str
    plan_cid: str
    candidate_cids: Sequence[str]
    verdict: EvaluationVerdict | str
    partition_evidence: Sequence[PartitionEvaluationEvidence | Mapping[str, Any]]
    regression_detected: bool
    overconstraint_detected: bool
    false_positive_detected: bool
    unmutated_suite_passed: bool
    diagnosis_killed: bool
    development_killed: bool
    held_out_killed: bool
    unrelated_behavior_preserved: bool
    safety_preserved: bool
    cost_delta_basis_points: int = 0
    rejection_reasons: Sequence[RejectionReason | str] = ()
    notes: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "interface_id",
            "header",
            "report_id",
            "plan_cid",
            "candidate_cids",
            "verdict",
            "partition_evidence",
            "regression_detected",
            "overconstraint_detected",
            "false_positive_detected",
            "unmutated_suite_passed",
            "diagnosis_killed",
            "development_killed",
            "held_out_killed",
            "unrelated_behavior_preserved",
            "safety_preserved",
            "cost_delta_basis_points",
            "rejection_reasons",
            "notes",
            "metadata",
            "report_cid",
        }
    )

    # Partitions that every evaluation report must encode.
    _REQUIRED_PARTITIONS: ClassVar[frozenset[str]] = frozenset(
        {
            EvaluationPartition.REGRESSION.value,
            EvaluationPartition.OVERCONSTRAINT.value,
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "header", _header(self.header))
        if self.header.artifact_kind != "remediation_evaluation_report":
            raise RemediationContractError(
                "header.artifact_kind must be remediation_evaluation_report"
            )
        object.__setattr__(self, "report_id", _token(self.report_id, "report_id"))
        object.__setattr__(self, "plan_cid", _cid(self.plan_cid, "plan_cid"))
        candidates = _unique_sorted_cids(
            list(self.candidate_cids), "candidate_cids"
        )
        if not candidates:
            raise RemediationContractError("candidate_cids must not be empty")
        object.__setattr__(self, "candidate_cids", candidates)
        verdict = _enum(self.verdict, EvaluationVerdict, "verdict")
        object.__setattr__(self, "verdict", verdict)
        evidence = _normalize_partition_evidence_list(
            list(self.partition_evidence), "partition_evidence"
        )
        if not evidence:
            raise RemediationContractError("partition_evidence must not be empty")
        present = {item.partition for item in evidence}
        missing = self._REQUIRED_PARTITIONS - present
        if missing:
            raise RemediationContractError(
                "partition_evidence must encode regression and overconstraint; "
                f"missing {sorted(missing)}"
            )
        object.__setattr__(self, "partition_evidence", evidence)
        regression = _bool(self.regression_detected, "regression_detected")
        overconstraint = _bool(
            self.overconstraint_detected, "overconstraint_detected"
        )
        false_positive = _bool(
            self.false_positive_detected, "false_positive_detected"
        )
        object.__setattr__(self, "regression_detected", regression)
        object.__setattr__(self, "overconstraint_detected", overconstraint)
        object.__setattr__(self, "false_positive_detected", false_positive)
        object.__setattr__(
            self,
            "unmutated_suite_passed",
            _bool(self.unmutated_suite_passed, "unmutated_suite_passed"),
        )
        object.__setattr__(
            self, "diagnosis_killed", _bool(self.diagnosis_killed, "diagnosis_killed")
        )
        object.__setattr__(
            self,
            "development_killed",
            _bool(self.development_killed, "development_killed"),
        )
        object.__setattr__(
            self, "held_out_killed", _bool(self.held_out_killed, "held_out_killed")
        )
        object.__setattr__(
            self,
            "unrelated_behavior_preserved",
            _bool(
                self.unrelated_behavior_preserved, "unrelated_behavior_preserved"
            ),
        )
        object.__setattr__(
            self, "safety_preserved", _bool(self.safety_preserved, "safety_preserved")
        )
        object.__setattr__(
            self,
            "cost_delta_basis_points",
            _nonneg_int(
                self.cost_delta_basis_points,
                "cost_delta_basis_points",
                maximum=MAX_COST_BP,
            ),
        )
        reasons = _unique_sorted_enums(
            list(self.rejection_reasons),
            RejectionReason,
            "rejection_reasons",
        )
        if verdict == EvaluationVerdict.QUALIFIED.value:
            if reasons:
                raise RemediationContractError(
                    "qualified verdict must not carry rejection_reasons"
                )
            if regression:
                raise RemediationContractError(
                    "qualified verdict forbids regression_detected=true"
                )
            if overconstraint:
                raise RemediationContractError(
                    "qualified verdict forbids overconstraint_detected=true"
                )
            if false_positive:
                raise RemediationContractError(
                    "qualified verdict forbids false_positive_detected=true"
                )
            if not self.unmutated_suite_passed:
                raise RemediationContractError(
                    "qualified verdict requires unmutated_suite_passed=true"
                )
            if not self.diagnosis_killed:
                raise RemediationContractError(
                    "qualified verdict requires diagnosis_killed=true"
                )
            if not self.held_out_killed:
                raise RemediationContractError(
                    "qualified verdict requires held_out_killed=true"
                )
            if not self.unrelated_behavior_preserved:
                raise RemediationContractError(
                    "qualified verdict requires unrelated_behavior_preserved=true"
                )
            if not self.safety_preserved:
                raise RemediationContractError(
                    "qualified verdict requires safety_preserved=true"
                )
        else:
            if not reasons:
                raise RemediationContractError(
                    "non-qualified verdict requires nonempty rejection_reasons"
                )
            if regression and RejectionReason.REGRESSION.value not in reasons:
                raise RemediationContractError(
                    "regression_detected requires rejection_reasons to include regression"
                )
            if (
                overconstraint
                and RejectionReason.OVERCONSTRAINT.value not in reasons
            ):
                raise RemediationContractError(
                    "overconstraint_detected requires rejection_reasons "
                    "to include overconstraint"
                )
        object.__setattr__(self, "rejection_reasons", reasons)
        object.__setattr__(self, "notes", _optional_text(self.notes, "notes"))
        object.__setattr__(self, "metadata", _mapping(self.metadata, "metadata"))

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": REMEDIATION_EVALUATION_REPORT_SCHEMA,
            "interface_id": REMEDIATION_EVALUATION_REPORT_INTERFACE,
            "header": self.header.identity_payload(),
            "report_id": self.report_id,
            "plan_cid": self.plan_cid,
            "candidate_cids": list(self.candidate_cids),
            "verdict": self.verdict,
            "partition_evidence": [
                item.identity_payload() for item in self.partition_evidence
            ],
            "regression_detected": self.regression_detected,
            "overconstraint_detected": self.overconstraint_detected,
            "false_positive_detected": self.false_positive_detected,
            "unmutated_suite_passed": self.unmutated_suite_passed,
            "diagnosis_killed": self.diagnosis_killed,
            "development_killed": self.development_killed,
            "held_out_killed": self.held_out_killed,
            "unrelated_behavior_preserved": self.unrelated_behavior_preserved,
            "safety_preserved": self.safety_preserved,
            "cost_delta_basis_points": self.cost_delta_basis_points,
            "rejection_reasons": list(self.rejection_reasons),
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
        }

    @property
    def report_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": REMEDIATION_EVALUATION_REPORT_SCHEMA,
            "interface_id": REMEDIATION_EVALUATION_REPORT_INTERFACE,
            "header": self.header.to_dict(),
            "report_id": self.report_id,
            "plan_cid": self.plan_cid,
            "candidate_cids": list(self.candidate_cids),
            "verdict": self.verdict,
            "partition_evidence": [
                item.to_dict() for item in self.partition_evidence
            ],
            "regression_detected": self.regression_detected,
            "overconstraint_detected": self.overconstraint_detected,
            "false_positive_detected": self.false_positive_detected,
            "unmutated_suite_passed": self.unmutated_suite_passed,
            "diagnosis_killed": self.diagnosis_killed,
            "development_killed": self.development_killed,
            "held_out_killed": self.held_out_killed,
            "unrelated_behavior_preserved": self.unrelated_behavior_preserved,
            "safety_preserved": self.safety_preserved,
            "cost_delta_basis_points": self.cost_delta_basis_points,
            "rejection_reasons": list(self.rejection_reasons),
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
            "report_cid": self.report_cid,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RemediationEvaluationReport":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("report_cid")
        if payload.pop("schema") != REMEDIATION_EVALUATION_REPORT_SCHEMA:
            raise RemediationContractError(
                "unsupported RemediationEvaluationReport schema version"
            )
        if payload.pop("interface_id") != REMEDIATION_EVALUATION_REPORT_INTERFACE:
            raise RemediationContractError(
                "unsupported RemediationEvaluationReport interface_id"
            )
        result = cls(
            header=payload["header"],
            report_id=payload["report_id"],
            plan_cid=payload["plan_cid"],
            candidate_cids=payload["candidate_cids"],
            verdict=payload["verdict"],
            partition_evidence=payload["partition_evidence"],
            regression_detected=payload["regression_detected"],
            overconstraint_detected=payload["overconstraint_detected"],
            false_positive_detected=payload["false_positive_detected"],
            unmutated_suite_passed=payload["unmutated_suite_passed"],
            diagnosis_killed=payload["diagnosis_killed"],
            development_killed=payload["development_killed"],
            held_out_killed=payload["held_out_killed"],
            unrelated_behavior_preserved=payload["unrelated_behavior_preserved"],
            safety_preserved=payload["safety_preserved"],
            cost_delta_basis_points=payload["cost_delta_basis_points"],
            rejection_reasons=payload["rejection_reasons"],
            notes=payload["notes"],
            metadata=payload["metadata"],
        )
        if claimed != result.report_cid:
            raise RemediationContractError(
                "RemediationEvaluationReport report_cid identity mismatch"
            )
        return result


# ---------------------------------------------------------------------------
# Vocabulary helpers and identity verification
# ---------------------------------------------------------------------------


def candidate_kinds() -> tuple[str, ...]:
    """Return the closed candidate-kind vocabulary in declaration order."""

    return tuple(item.value for item in CandidateKind)


def candidate_draft_statuses() -> tuple[str, ...]:
    """Return the closed candidate draft-status vocabulary in declaration order."""

    return tuple(item.value for item in CandidateDraftStatus)


def remediation_risk_classes() -> tuple[str, ...]:
    """Return the closed remediation risk-class vocabulary in declaration order."""

    return tuple(item.value for item in RemediationRiskClass)


def mutation_class_tokens() -> tuple[str, ...]:
    """Return the closed mutation-class token vocabulary in declaration order."""

    return tuple(item.value for item in MutationClassToken)


def remediation_plan_statuses() -> tuple[str, ...]:
    """Return the closed remediation plan-status vocabulary in declaration order."""

    return tuple(item.value for item in RemediationPlanStatus)


def evaluation_partitions() -> tuple[str, ...]:
    """Return the closed evaluation-partition vocabulary in declaration order."""

    return tuple(item.value for item in EvaluationPartition)


def evaluation_verdicts() -> tuple[str, ...]:
    """Return the closed evaluation-verdict vocabulary in declaration order."""

    return tuple(item.value for item in EvaluationVerdict)


def rejection_reasons() -> tuple[str, ...]:
    """Return the closed rejection-reason vocabulary in declaration order."""

    return tuple(item.value for item in RejectionReason)


def verify_candidate_test_identity(
    candidate: CandidateTestSpecification | Mapping[str, Any],
) -> str:
    """Recompute and return the candidate-test CID; raise on forged input."""

    if isinstance(candidate, CandidateTestSpecification):
        sealed = candidate
    elif isinstance(candidate, Mapping):
        sealed = CandidateTestSpecification.from_dict(candidate)
    else:
        raise RemediationContractError(
            "candidate must be CandidateTestSpecification or mapping"
        )
    if not sealed.requirement_provenances:
        raise RemediationContractError(
            "candidate tests must bind requirement provenance"
        )
    recomputed = cid_for_structured(sealed.identity_payload())
    if recomputed != sealed.candidate_cid:
        raise RemediationContractError(
            "candidate_cid identity mismatch with recomputed identity"
        )
    return recomputed


def verify_candidate_proof_identity(
    candidate: CandidateProofObligation | Mapping[str, Any],
) -> str:
    """Recompute and return the proof-candidate CID; require nonvacuity."""

    if isinstance(candidate, CandidateProofObligation):
        sealed = candidate
    elif isinstance(candidate, Mapping):
        sealed = CandidateProofObligation.from_dict(candidate)
    else:
        raise RemediationContractError(
            "candidate must be CandidateProofObligation or mapping"
        )
    if not sealed.assumptions:
        raise RemediationContractError(
            "proof obligations must include assumptions"
        )
    if not sealed.source_connection:
        raise RemediationContractError(
            "proof obligations must include source connection"
        )
    if not sealed.nonvacuity_condition.assumes_satisfiable:
        raise RemediationContractError(
            "proof obligations must include practical nonvacuity"
        )
    recomputed = cid_for_structured(sealed.identity_payload())
    if recomputed != sealed.candidate_cid:
        raise RemediationContractError(
            "candidate_cid identity mismatch with recomputed identity"
        )
    return recomputed


def verify_candidate_policy_identity(
    candidate: CandidatePolicyConstraint | Mapping[str, Any],
) -> str:
    """Recompute and return the policy-candidate CID; raise on forged input."""

    if isinstance(candidate, CandidatePolicyConstraint):
        sealed = candidate
    elif isinstance(candidate, Mapping):
        sealed = CandidatePolicyConstraint.from_dict(candidate)
    else:
        raise RemediationContractError(
            "candidate must be CandidatePolicyConstraint or mapping"
        )
    recomputed = cid_for_structured(sealed.identity_payload())
    if recomputed != sealed.candidate_cid:
        raise RemediationContractError(
            "candidate_cid identity mismatch with recomputed identity"
        )
    return recomputed


def verify_candidate_analyzer_identity(
    candidate: CandidateAnalyzerRule | Mapping[str, Any],
) -> str:
    """Recompute and return the analyzer-candidate CID; raise on forged input."""

    if isinstance(candidate, CandidateAnalyzerRule):
        sealed = candidate
    elif isinstance(candidate, Mapping):
        sealed = CandidateAnalyzerRule.from_dict(candidate)
    else:
        raise RemediationContractError(
            "candidate must be CandidateAnalyzerRule or mapping"
        )
    recomputed = cid_for_structured(sealed.identity_payload())
    if recomputed != sealed.candidate_cid:
        raise RemediationContractError(
            "candidate_cid identity mismatch with recomputed identity"
        )
    return recomputed


def verify_plan_identity(
    plan: GapRemediationPlan | Mapping[str, Any],
) -> str:
    """Recompute and return the plan CID; raise on forged input."""

    if isinstance(plan, GapRemediationPlan):
        sealed = plan
    elif isinstance(plan, Mapping):
        sealed = GapRemediationPlan.from_dict(plan)
    else:
        raise RemediationContractError(
            "plan must be GapRemediationPlan or mapping"
        )
    recomputed = cid_for_structured(sealed.identity_payload())
    if recomputed != sealed.plan_cid:
        raise RemediationContractError(
            "plan_cid identity mismatch with recomputed identity"
        )
    return recomputed


def verify_evaluation_report_identity(
    report: RemediationEvaluationReport | Mapping[str, Any],
) -> str:
    """Recompute and return the evaluation-report CID; require regression/overconstraint encoding."""

    if isinstance(report, RemediationEvaluationReport):
        sealed = report
    elif isinstance(report, Mapping):
        sealed = RemediationEvaluationReport.from_dict(report)
    else:
        raise RemediationContractError(
            "report must be RemediationEvaluationReport or mapping"
        )
    partitions = {item.partition for item in sealed.partition_evidence}
    if EvaluationPartition.REGRESSION.value not in partitions:
        raise RemediationContractError(
            "evaluation must encode regression partition evidence"
        )
    if EvaluationPartition.OVERCONSTRAINT.value not in partitions:
        raise RemediationContractError(
            "evaluation must encode overconstraint partition evidence"
        )
    recomputed = cid_for_structured(sealed.identity_payload())
    if recomputed != sealed.report_cid:
        raise RemediationContractError(
            "report_cid identity mismatch with recomputed identity"
        )
    return recomputed


__all__ = [
    "CANDIDATE_ANALYZER_RULE_INTERFACE",
    "CANDIDATE_ANALYZER_RULE_SCHEMA",
    "CANDIDATE_POLICY_CONSTRAINT_INTERFACE",
    "CANDIDATE_POLICY_CONSTRAINT_SCHEMA",
    "CANDIDATE_PROOF_OBLIGATION_INTERFACE",
    "CANDIDATE_PROOF_OBLIGATION_SCHEMA",
    "CANDIDATE_TEST_SPECIFICATION_INTERFACE",
    "CANDIDATE_TEST_SPECIFICATION_SCHEMA",
    "GAP_REMEDIATION_PLAN_INTERFACE",
    "GAP_REMEDIATION_PLAN_SCHEMA",
    "NONVACUITY_CONDITION_SCHEMA",
    "PARTITION_EVALUATION_EVIDENCE_SCHEMA",
    "REMEDIATION_EVALUATION_REPORT_INTERFACE",
    "REMEDIATION_EVALUATION_REPORT_SCHEMA",
    "REQUIREMENT_PROVENANCE_SCHEMA",
    "CandidateAnalyzerRule",
    "CandidateDraftStatus",
    "CandidateKind",
    "CandidatePolicyConstraint",
    "CandidateProofObligation",
    "CandidateTestSpecification",
    "EvaluationPartition",
    "EvaluationVerdict",
    "GapRemediationPlan",
    "MutationClassToken",
    "NonvacuityCondition",
    "PartitionEvaluationEvidence",
    "RejectionReason",
    "RemediationContractError",
    "RemediationEvaluationReport",
    "RemediationPlanStatus",
    "RemediationRiskClass",
    "RequirementProvenance",
    "candidate_draft_statuses",
    "candidate_kinds",
    "evaluation_partitions",
    "evaluation_verdicts",
    "mutation_class_tokens",
    "rejection_reasons",
    "remediation_plan_statuses",
    "remediation_risk_classes",
    "verify_candidate_analyzer_identity",
    "verify_candidate_policy_identity",
    "verify_candidate_proof_identity",
    "verify_candidate_test_identity",
    "verify_evaluation_report_identity",
    "verify_plan_identity",
]
