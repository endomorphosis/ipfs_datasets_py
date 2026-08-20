"""Plan the smallest bounded context expansion (SCG-015).

Pure, deterministic planning over an audit case and ranked omission
hypotheses under hard token / step / retry / escalation / time / spend
limits. The planner chooses raw source or stronger capsule (and related
schema/fixture/configuration/test/proof) additions by rank, evidence, and
cost, recording changed assumptions on every step.

Normative rules:

* Expanded context remains hard-bounded; plans never grow without limits.
* Impossible or unsafe budgets return a human-review plan (never unbounded
  growth and never silent model escalation as a substitute for missing
  context when omission expansion is supported).
* Omission / context expansion steps precede model-route escalation where
  supported (``context_before_model_escalation``).
* Complete affected-cone candidates are preferred over repository dumps
  (only ranked subject artifacts are admitted).
* Identical inputs yield identical ``plan_cid`` identities.
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
    MAX_EXPANSION_STEPS,
    MAX_HYPOTHESES,
    MAX_REASON_CODES,
    MAX_TOKEN_COST,
    AuditContractError,
    CompressionAuditCase,
    ContextExpansionPlan,
    ContextExpansionStep,
    ExpansionAction,
    ExpansionStepStatus,
    HypothesisCause,
    OmissionHypothesis,
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

PLAN_CONTEXT_EXPANSION_INTERFACE: Final[str] = "plan_context_expansion@1"
EXPANSION_PLANNER_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.semantic-governor-expansion-planner@1"
)
EXPANSION_PLAN_RESULT_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.semantic-governor-expansion-plan-result@1"
)
TOKEN_BUDGET_VIEW_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.semantic-governor-token-budget-view@1"
)

GENERATOR_ID: Final[str] = "expansion_planner"
GENERATOR_VERSION: Final[str] = "1.0.0"
PRODUCER_ID: Final[str] = "semantic_governor"
PRODUCER_VERSION: Final[str] = "1"
TOOL_ID: Final[str] = "expansion.v1"

MAX_TEXT_CHARS: Final[int] = 16_384
MAX_CID_LIST: Final[int] = 4_096
MAX_ASSUMPTIONS: Final[int] = 512

# Defaults for hard plan limits (override via kwargs; never unbounded).
DEFAULT_MAX_STEPS: Final[int] = 8
DEFAULT_MAX_RETRIES: Final[int] = 3
DEFAULT_MAX_ESCALATIONS: Final[int] = 1
DEFAULT_MAX_WALL_TIME_MS: Final[int] = 600_000
DEFAULT_MAX_SPEND_MICROS: Final[int] = 0

_TOKEN_RE: Final[re.Pattern[str]] = re.compile(r"^[a-z][a-z0-9_.:/+-]{0,127}$")

# Actions that expand context (precede model escalation when supported).
_CONTEXT_EXPANSION_ACTIONS: Final[frozenset[str]] = frozenset(
    {
        ExpansionAction.INCLUDE_RAW_SOURCE.value,
        ExpansionAction.STRENGTHEN_CAPSULE.value,
        ExpansionAction.INCLUDE_SCHEMA.value,
        ExpansionAction.INCLUDE_FIXTURE.value,
        ExpansionAction.INCLUDE_CONFIGURATION.value,
        ExpansionAction.INCLUDE_TEST.value,
        ExpansionAction.INCLUDE_PROOF.value,
    }
)

_ROUTE_ESCALATION_ACTIONS: Final[frozenset[str]] = frozenset(
    {
        ExpansionAction.ESCALATE_ROUTE.value,
    }
)

_HUMAN_REVIEW_ACTIONS: Final[frozenset[str]] = frozenset(
    {
        ExpansionAction.REQUEST_HUMAN_REVIEW.value,
    }
)

_NO_ACTION: Final[frozenset[str]] = frozenset(
    {
        ExpansionAction.NO_ACTION.value,
    }
)

# Causes that force human review when they appear without a viable context path.
_REVIEW_CAUSES: Final[frozenset[str]] = frozenset(
    {
        HypothesisCause.STALE_ARTIFACT.value,
        HypothesisCause.POLICY_BOUNDARY.value,
        HypothesisCause.CONFLICTING_EVIDENCE.value,
    }
)

# Reason codes admitted on planned steps (closed tokens).
_REASON_FOR_ACTION: Final[dict[str, str]] = {
    ExpansionAction.INCLUDE_RAW_SOURCE.value: "omission_repair",
    ExpansionAction.STRENGTHEN_CAPSULE.value: "strengthen_capsule",
    ExpansionAction.INCLUDE_SCHEMA.value: "include_schema",
    ExpansionAction.INCLUDE_FIXTURE.value: "include_fixture",
    ExpansionAction.INCLUDE_CONFIGURATION.value: "include_configuration",
    ExpansionAction.INCLUDE_TEST.value: "include_test",
    ExpansionAction.INCLUDE_PROOF.value: "include_proof",
    ExpansionAction.ESCALATE_ROUTE.value: "model_route_after_context",
    ExpansionAction.REQUEST_HUMAN_REVIEW.value: "human_review_required",
    ExpansionAction.NO_ACTION.value: "no_action",
}


class ExpansionPlannerError(SemanticGovernorBaseError):
    """Raised when expansion planning inputs are malformed or unsafe."""


class ExpansionDisposition(str, Enum):
    """Closed plan disposition labels (explainable, not authority)."""

    EXPAND = "expand"
    HUMAN_REVIEW = "human_review"
    ESCALATE_ONLY = "escalate_only"
    NO_ACTION = "no_action"


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _text(value: Any, name: str, *, empty: bool = False) -> str:
    if type(value) is not str or (not empty and not value):
        raise ExpansionPlannerError(f"{name} must be a nonempty string")
    if value != value.strip() or unicodedata.normalize("NFC", value) != value:
        raise ExpansionPlannerError(f"{name} must be trimmed NFC text")
    if len(value) > MAX_TEXT_CHARS or any(not char.isprintable() for char in value):
        raise ExpansionPlannerError(f"{name} contains invalid text")
    return value


def _optional_text(value: Any, name: str) -> str | None:
    if value is None:
        return None
    return _text(value, name)


def _token(value: Any, name: str) -> str:
    text = _text(value, name)
    if _TOKEN_RE.fullmatch(text) is None:
        raise ExpansionPlannerError(
            f"{name} must be a lowercase token matching {_TOKEN_RE.pattern}"
        )
    return text


def _cid(value: Any, name: str) -> str:
    try:
        return validate_cid(value)
    except Exception as exc:
        raise ExpansionPlannerError(f"{name} must be a valid CID") from exc


def _optional_cid(value: Any, name: str) -> str | None:
    if value is None:
        return None
    return _cid(value, name)


def _bool(value: Any, name: str) -> bool:
    if type(value) is not bool:
        raise ExpansionPlannerError(f"{name} must be a boolean")
    return value


def _nonneg_int(value: Any, name: str) -> int:
    if type(value) is not int or isinstance(value, bool) or value < 0:
        raise ExpansionPlannerError(f"{name} must be a nonnegative integer")
    return value


def _pos_int(value: Any, name: str) -> int:
    value = _nonneg_int(value, name)
    if value < 1:
        raise ExpansionPlannerError(f"{name} must be a positive integer")
    return value


def _token_cost(value: Any, name: str) -> int:
    cost = _nonneg_int(value, name)
    if cost > MAX_TOKEN_COST:
        raise ExpansionPlannerError(f"{name} exceeds maximum token cost")
    return cost


def _basis_points(value: Any, name: str) -> int:
    bp = _nonneg_int(value, name)
    if bp > BASIS_POINTS:
        raise ExpansionPlannerError(f"{name} must be in 0..{BASIS_POINTS}")
    return bp


def _enum(value: Any, enum_type: type[Enum], name: str) -> str:
    try:
        return enum_type(value).value
    except (TypeError, ValueError) as exc:
        raise ExpansionPlannerError(f"{name} has unsupported value {value!r}") from exc


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
        raise ExpansionPlannerError(
            f"{name} must be strict DAG-JSON without floats or host types"
        ) from exc
    try:
        reject_private_and_model_authority(thawed, path=name)
    except SemanticGovernorBaseError as exc:
        raise ExpansionPlannerError(str(exc)) from exc
    return thawed


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ExpansionPlannerError(f"{name} must be a mapping")
    return _freeze_structured(_require_structured(dict(value), name))


def _unique_sorted_tokens(
    values: Iterable[Any],
    name: str,
    *,
    max_items: int,
) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple)):
        raise ExpansionPlannerError(f"{name} must be a list")
    ordered = tuple(sorted(_token(value, name) for value in values))
    if len(ordered) > max_items:
        raise ExpansionPlannerError(f"{name} exceeds maximum length")
    if len(ordered) != len(set(ordered)):
        raise ExpansionPlannerError(f"{name} must not contain duplicates")
    return ordered


def _normalize_audit_case(
    value: CompressionAuditCase | Mapping[str, Any],
) -> CompressionAuditCase:
    if isinstance(value, CompressionAuditCase):
        return value
    if isinstance(value, Mapping):
        try:
            return CompressionAuditCase.from_dict(value)
        except AuditContractError as exc:
            raise ExpansionPlannerError(str(exc)) from exc
    raise ExpansionPlannerError(
        "audit_case must be CompressionAuditCase or mapping"
    )


def _normalize_hypothesis(
    value: OmissionHypothesis | Mapping[str, Any],
) -> OmissionHypothesis:
    if isinstance(value, OmissionHypothesis):
        return value
    if isinstance(value, Mapping):
        try:
            if "hypothesis_cid" in value and "schema" in value:
                return OmissionHypothesis.from_dict(value)
            return OmissionHypothesis(
                header=value.get("header", {}),
                hypothesis_id=value.get("hypothesis_id", ""),
                cause=value.get("cause", ""),
                subject_artifact_id=value.get("subject_artifact_id", ""),
                subject_kind=value.get("subject_kind", ""),
                rank=value.get("rank", 0),
                expected_relevance_bp=value.get("expected_relevance_bp", 0),
                inclusion_cost_tokens=value.get("inclusion_cost_tokens", 0),
                confidence_bp=value.get("confidence_bp", 0),
                expansion_action=value.get("expansion_action", ""),
                exclusion_reason=value.get("exclusion_reason"),
                capsule_class=value.get("capsule_class"),
                path=value.get("path"),
                source_span=value.get("source_span"),
                dependency_path=value.get("dependency_path"),
                supporting_evidence_cids=value.get("supporting_evidence_cids", ()),
                proposed_rule_change=value.get("proposed_rule_change"),
                notes=value.get("notes"),
                metadata=value.get("metadata", {}),
            )
        except AuditContractError as exc:
            raise ExpansionPlannerError(str(exc)) from exc
    raise ExpansionPlannerError(
        "omission_hypotheses entries must be OmissionHypothesis or mapping"
    )


def _normalize_hypotheses(
    values: Sequence[OmissionHypothesis | Mapping[str, Any]] | None,
) -> tuple[OmissionHypothesis, ...]:
    if values is None:
        return ()
    if not isinstance(values, (list, tuple)):
        raise ExpansionPlannerError("omission_hypotheses must be a list")
    if len(values) > MAX_HYPOTHESES:
        raise ExpansionPlannerError(
            f"omission_hypotheses exceeds maximum length {MAX_HYPOTHESES}"
        )
    hyps = tuple(_normalize_hypothesis(item) for item in values)
    # Stable order by declared rank, then hypothesis_id for determinism.
    ordered = tuple(sorted(hyps, key=lambda h: (h.rank, h.hypothesis_id)))
    # Ranks need not be contiguous when callers pass a subset, but duplicates
    # of the same rank+subject are rejected as ambiguous.
    seen_subjects: set[tuple[int, str]] = set()
    for hyp in ordered:
        key = (hyp.rank, hyp.subject_artifact_id)
        if key in seen_subjects:
            raise ExpansionPlannerError(
                "omission_hypotheses must not duplicate rank+subject_artifact_id"
            )
        seen_subjects.add(key)
    return ordered


# ---------------------------------------------------------------------------
# Optional budget / result envelopes
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TokenBudgetView:
    """Hard limits for a single expansion plan (datasets-owned planning view)."""

    token_budget: int
    max_steps: int = DEFAULT_MAX_STEPS
    max_retries: int = DEFAULT_MAX_RETRIES
    max_escalations: int = DEFAULT_MAX_ESCALATIONS
    max_wall_time_ms: int = DEFAULT_MAX_WALL_TIME_MS
    max_spend_micros: int = DEFAULT_MAX_SPEND_MICROS
    disclosure_blocked: bool = False
    notes: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "token_budget", _token_cost(self.token_budget, "token_budget")
        )
        max_steps = _pos_int(self.max_steps, "max_steps")
        if max_steps > MAX_EXPANSION_STEPS:
            raise ExpansionPlannerError(
                f"max_steps must be <= {MAX_EXPANSION_STEPS}"
            )
        object.__setattr__(self, "max_steps", max_steps)
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
            "disclosure_blocked",
            _bool(self.disclosure_blocked, "disclosure_blocked"),
        )
        object.__setattr__(self, "notes", _optional_text(self.notes, "notes"))
        object.__setattr__(self, "metadata", _mapping(self.metadata, "metadata"))

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": TOKEN_BUDGET_VIEW_SCHEMA,
            "token_budget": self.token_budget,
            "max_steps": self.max_steps,
            "max_retries": self.max_retries,
            "max_escalations": self.max_escalations,
            "max_wall_time_ms": self.max_wall_time_ms,
            "max_spend_micros": self.max_spend_micros,
            "disclosure_blocked": self.disclosure_blocked,
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
        }

    @property
    def view_cid(self) -> str:
        return cid_for_structured(self.identity_payload())


@dataclass(frozen=True, slots=True)
class ExpansionPlanResult:
    """Planner result: durable plan plus explainable disposition metadata.

    ``plan`` is always a valid :class:`ContextExpansionPlan` (including the
    human-review disposition). Identical inputs yield identical
    ``result_cid`` / ``plan.plan_cid``.
    """

    plan: ContextExpansionPlan
    disposition: ExpansionDisposition | str
    requires_human_review: bool
    context_before_model_escalation: bool
    selected_hypothesis_cids: Sequence[str] = ()
    skipped_hypothesis_cids: Sequence[str] = ()
    deferred_escalation_hypothesis_cids: Sequence[str] = ()
    reason_codes: Sequence[str] = ()
    notes: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "interface_id",
            "plan",
            "disposition",
            "requires_human_review",
            "context_before_model_escalation",
            "selected_hypothesis_cids",
            "skipped_hypothesis_cids",
            "deferred_escalation_hypothesis_cids",
            "reason_codes",
            "notes",
            "metadata",
            "result_cid",
        }
    )

    def __post_init__(self) -> None:
        if not isinstance(self.plan, ContextExpansionPlan):
            raise ExpansionPlannerError("plan must be a ContextExpansionPlan")
        object.__setattr__(
            self,
            "disposition",
            _enum(self.disposition, ExpansionDisposition, "disposition"),
        )
        object.__setattr__(
            self,
            "requires_human_review",
            _bool(self.requires_human_review, "requires_human_review"),
        )
        object.__setattr__(
            self,
            "context_before_model_escalation",
            _bool(
                self.context_before_model_escalation,
                "context_before_model_escalation",
            ),
        )
        object.__setattr__(
            self,
            "selected_hypothesis_cids",
            tuple(
                _cid(item, "selected_hypothesis_cids")
                for item in self.selected_hypothesis_cids
            ),
        )
        object.__setattr__(
            self,
            "skipped_hypothesis_cids",
            tuple(
                _cid(item, "skipped_hypothesis_cids")
                for item in self.skipped_hypothesis_cids
            ),
        )
        object.__setattr__(
            self,
            "deferred_escalation_hypothesis_cids",
            tuple(
                _cid(item, "deferred_escalation_hypothesis_cids")
                for item in self.deferred_escalation_hypothesis_cids
            ),
        )
        object.__setattr__(
            self,
            "reason_codes",
            _unique_sorted_tokens(
                list(self.reason_codes),
                "reason_codes",
                max_items=MAX_REASON_CODES,
            ),
        )
        object.__setattr__(self, "notes", _optional_text(self.notes, "notes"))
        object.__setattr__(self, "metadata", _mapping(self.metadata, "metadata"))

        if self.requires_human_review and self.disposition != (
            ExpansionDisposition.HUMAN_REVIEW.value
        ):
            raise ExpansionPlannerError(
                "requires_human_review requires disposition=human_review"
            )
        if (
            self.disposition == ExpansionDisposition.HUMAN_REVIEW.value
            and not self.requires_human_review
        ):
            raise ExpansionPlannerError(
                "disposition=human_review requires requires_human_review=true"
            )

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": EXPANSION_PLAN_RESULT_SCHEMA,
            "interface_id": PLAN_CONTEXT_EXPANSION_INTERFACE,
            "plan": self.plan.identity_payload(),
            "disposition": self.disposition,
            "requires_human_review": self.requires_human_review,
            "context_before_model_escalation": self.context_before_model_escalation,
            "selected_hypothesis_cids": list(self.selected_hypothesis_cids),
            "skipped_hypothesis_cids": list(self.skipped_hypothesis_cids),
            "deferred_escalation_hypothesis_cids": list(
                self.deferred_escalation_hypothesis_cids
            ),
            "reason_codes": list(self.reason_codes),
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
        }

    @property
    def result_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": EXPANSION_PLAN_RESULT_SCHEMA,
            "interface_id": PLAN_CONTEXT_EXPANSION_INTERFACE,
            "plan": self.plan.to_dict(),
            "disposition": self.disposition,
            "requires_human_review": self.requires_human_review,
            "context_before_model_escalation": self.context_before_model_escalation,
            "selected_hypothesis_cids": list(self.selected_hypothesis_cids),
            "skipped_hypothesis_cids": list(self.skipped_hypothesis_cids),
            "deferred_escalation_hypothesis_cids": list(
                self.deferred_escalation_hypothesis_cids
            ),
            "reason_codes": list(self.reason_codes),
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
            "result_cid": self.result_cid,
        }


# ---------------------------------------------------------------------------
# Header / id / step construction
# ---------------------------------------------------------------------------


def _build_plan_header(
    *,
    audit_case: CompressionAuditCase,
    terminal_status: str,
    input_cids: Sequence[str],
    assumptions: Sequence[GovernorAssumption],
    policy_cid: str | None,
) -> GovernorArtifactHeader:
    generator = GeneratorIdentity(
        generator_id=GENERATOR_ID,
        generator_version=GENERATOR_VERSION,
        interface_id=PLAN_CONTEXT_EXPANSION_INTERFACE,
    )
    provenance = ArtifactProvenance(
        producer_id=PRODUCER_ID,
        producer_version=PRODUCER_VERSION,
        execution_mode=ExecutionMode.LIVE,
        authority_source=AuthoritySource.DETERMINISTIC,
        input_cids=tuple(sorted(set(input_cids))),
        tool_ids=(TOOL_ID,),
        policy_cid=policy_cid or audit_case.policy_cid,
        notes=None,
    )
    try:
        return GovernorArtifactHeader(
            artifact_kind="context_expansion_plan",
            repository_state_cid=audit_case.header.repository_state_cid,
            context_pack_cid=audit_case.header.context_pack_cid,
            verification_bundle_cid=audit_case.header.verification_bundle_cid,
            generator=generator,
            provenance=provenance,
            terminal_status=terminal_status,
            assumptions=assumptions,
            metadata={
                "builder_schema": EXPANSION_PLANNER_SCHEMA,
                "interface_id": PLAN_CONTEXT_EXPANSION_INTERFACE,
            },
        )
    except SemanticGovernorBaseError as exc:
        raise ExpansionPlannerError(str(exc)) from exc


def _step_header(
    base: GovernorArtifactHeader,
    *,
    terminal_status: str | None = None,
) -> GovernorArtifactHeader:
    return GovernorArtifactHeader(
        artifact_kind="context_expansion_step",
        repository_state_cid=base.repository_state_cid,
        context_pack_cid=base.context_pack_cid,
        verification_bundle_cid=base.verification_bundle_cid,
        generator=base.generator,
        provenance=base.provenance,
        terminal_status=terminal_status or base.terminal_status,
        assumptions=base.assumptions,
        metadata={
            "builder_schema": EXPANSION_PLANNER_SCHEMA,
            "interface_id": PLAN_CONTEXT_EXPANSION_INTERFACE,
        },
    )


def _build_assumptions(
    *,
    audit_case: CompressionAuditCase,
    budget: TokenBudgetView,
    disposition: str,
) -> tuple[GovernorAssumption, ...]:
    assumptions: list[GovernorAssumption] = [
        GovernorAssumption(
            assumption_id="expansion_bounded",
            kind=AssumptionKind.BUDGET,
            statement=(
                "Context expansion is hard-bounded by token growth, step count, "
                "retries, escalations, wall time, and spend; unbounded growth "
                "is rejected"
            ),
            supporting_cids=(audit_case.case_cid, budget.view_cid),
        ),
        GovernorAssumption(
            assumption_id="affected_cone_only",
            kind=AssumptionKind.COVERAGE,
            statement=(
                "Expansion admits only ranked omission subjects from the "
                "affected cone; repository dump expansion is rejected"
            ),
            supporting_cids=(audit_case.case_cid,),
        ),
        GovernorAssumption(
            assumption_id="context_before_model_escalation",
            kind=AssumptionKind.ROUTE,
            statement=(
                "Where omission expansion is supported, context repair steps "
                "precede model-route escalation; escalation is never a "
                "substitute for an impossible context budget"
            ),
            supporting_cids=(audit_case.case_cid,),
        ),
    ]
    if disposition == ExpansionDisposition.HUMAN_REVIEW.value:
        assumptions.append(
            GovernorAssumption(
                assumption_id="human_review_on_unsafe_budget",
                kind=AssumptionKind.BUDGET,
                statement=(
                    "Impossible or unsafe expansion budgets require human "
                    "review rather than unbounded growth or silent escalation"
                ),
                supporting_cids=(budget.view_cid,),
            )
        )
    if budget.disclosure_blocked:
        assumptions.append(
            GovernorAssumption(
                assumption_id="disclosure_blocked_local_only",
                kind=AssumptionKind.PRIVACY,
                statement=(
                    "Disclosure policy blocks provider-bound private expansion; "
                    "human review is required for unsafe disclosure"
                ),
                supporting_cids=(budget.view_cid,),
            )
        )
    # Preserve relevant audit-case assumptions that remain stable.
    for assumption in audit_case.header.assumptions:
        if assumption.assumption_id not in {
            item.assumption_id for item in assumptions
        }:
            assumptions.append(assumption)
    return tuple(sorted(assumptions, key=lambda item: item.assumption_id))


def _plan_id_for(
    audit_case: CompressionAuditCase,
    hypotheses: Sequence[OmissionHypothesis],
    budget: TokenBudgetView,
) -> str:
    digest = cid_for_structured(
        {
            "case": audit_case.case_cid,
            "hypotheses": [hyp.hypothesis_cid for hyp in hypotheses],
            "budget": budget.view_cid,
        }
    )
    suffix = digest[-24:] if len(digest) >= 24 else digest
    cleaned = re.sub(r"[^a-z0-9_.:/+-]", "", suffix.lower())
    if not cleaned or not cleaned[0].isalpha():
        cleaned = f"p{cleaned}" if cleaned else "p0"
    return f"plan_{cleaned}"[:128]


def _step_id_for(index: int, action: str, subject: str) -> str:
    cleaned_subject = re.sub(r"[^a-z0-9_.:/+-]", "", subject.lower())
    if not cleaned_subject or not cleaned_subject[0].isalpha():
        cleaned_subject = f"a{cleaned_subject}" if cleaned_subject else "a0"
    cleaned_action = re.sub(r"[^a-z0-9_.:/+-]", "", action.lower())
    if not cleaned_action or not cleaned_action[0].isalpha():
        cleaned_action = f"x{cleaned_action}" if cleaned_action else "x0"
    return f"step_{index:04d}_{cleaned_action}_{cleaned_subject}"[:128]


def _changed_assumption_ids_for(action: str) -> tuple[str, ...]:
    base = ["expansion_bounded", "affected_cone_only"]
    if action in _CONTEXT_EXPANSION_ACTIONS:
        base.append("coverage_expanded")
    if action == ExpansionAction.ESCALATE_ROUTE.value:
        base.append("context_before_model_escalation")
    if action == ExpansionAction.REQUEST_HUMAN_REVIEW.value:
        base.append("human_review_on_unsafe_budget")
    # coverage_expanded may not exist on the plan header; still record intent.
    return tuple(sorted(set(base)))


def _build_step(
    *,
    header: GovernorArtifactHeader,
    index: int,
    action: str,
    status: str,
    token_increase: int,
    artifact_ids_added: Sequence[str],
    hypothesis: OmissionHypothesis | None,
    reason_code: str,
    notes: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> ContextExpansionStep:
    subject = (
        hypothesis.subject_artifact_id if hypothesis is not None else "none"
    )
    meta: dict[str, Any] = dict(metadata or {})
    if hypothesis is not None:
        meta.setdefault("hypothesis_id", hypothesis.hypothesis_id)
        meta.setdefault("hypothesis_rank", hypothesis.rank)
        meta.setdefault("hypothesis_cause", hypothesis.cause)
    try:
        return ContextExpansionStep(
            header=_step_header(header),
            step_id=_step_id_for(index, action, subject),
            step_index=index,
            action=action,
            status=status,
            token_increase=token_increase,
            artifact_ids_added=tuple(artifact_ids_added),
            hypothesis_cid=(
                None if hypothesis is None else hypothesis.hypothesis_cid
            ),
            reason_code=reason_code,
            prior_result_cid=None,
            new_result_cid=None,
            changed_assumption_ids=_changed_assumption_ids_for(action),
            hypothesis_supported=None,
            notes=notes,
            metadata=meta,
        )
    except AuditContractError as exc:
        raise ExpansionPlannerError(str(exc)) from exc


def _partition_hypotheses(
    hypotheses: Sequence[OmissionHypothesis],
) -> tuple[
    list[OmissionHypothesis],
    list[OmissionHypothesis],
    list[OmissionHypothesis],
    list[OmissionHypothesis],
]:
    context: list[OmissionHypothesis] = []
    escalate: list[OmissionHypothesis] = []
    review: list[OmissionHypothesis] = []
    noop: list[OmissionHypothesis] = []
    for hyp in hypotheses:
        action = hyp.expansion_action
        if action in _CONTEXT_EXPANSION_ACTIONS:
            context.append(hyp)
        elif action in _ROUTE_ESCALATION_ACTIONS:
            escalate.append(hyp)
        elif action in _HUMAN_REVIEW_ACTIONS or hyp.cause in _REVIEW_CAUSES:
            review.append(hyp)
        elif action in _NO_ACTION:
            noop.append(hyp)
        else:
            raise ExpansionPlannerError(
                f"unsupported expansion_action {action!r} on hypothesis "
                f"{hyp.hypothesis_id}"
            )
    # Preserve rank order within each partition.
    context.sort(key=lambda h: (h.rank, h.hypothesis_id))
    escalate.sort(key=lambda h: (h.rank, h.hypothesis_id))
    review.sort(key=lambda h: (h.rank, h.hypothesis_id))
    noop.sort(key=lambda h: (h.rank, h.hypothesis_id))
    return context, escalate, review, noop


def _human_review_reason(
    *,
    context_hyps: Sequence[OmissionHypothesis],
    review_hyps: Sequence[OmissionHypothesis],
    budget: TokenBudgetView,
) -> str:
    if budget.disclosure_blocked:
        return "disclosure_blocked"
    if review_hyps and not context_hyps:
        return "hypothesis_requires_human_review"
    if context_hyps and budget.token_budget == 0:
        return "unsafe_zero_budget"
    if context_hyps and context_hyps[0].inclusion_cost_tokens > budget.token_budget:
        return "budget_impossible"
    if context_hyps and budget.max_steps < 1:
        return "budget_impossible"
    return "unsafe_budget"


def _finalize_plan(
    *,
    audit_case: CompressionAuditCase,
    budget: TokenBudgetView,
    steps: Sequence[ContextExpansionStep],
    disposition: str,
    requires_human_review: bool,
    context_before_model_escalation: bool,
    selected: Sequence[OmissionHypothesis],
    skipped: Sequence[OmissionHypothesis],
    deferred_escalation: Sequence[OmissionHypothesis],
    reason_codes: Sequence[str],
    notes: str,
    omission_evidence_cid: str | None,
    plan_id: str | None,
    extra_metadata: Mapping[str, Any] | None = None,
) -> ExpansionPlanResult:
    terminal = (
        GovernorTerminalStatus.HUMAN_REVIEW_REQUIRED.value
        if requires_human_review
        else GovernorTerminalStatus.COMPLETE.value
    )
    input_cids = [audit_case.case_cid, budget.view_cid]
    for hyp in (*selected, *skipped, *deferred_escalation):
        input_cids.append(hyp.hypothesis_cid)
    if omission_evidence_cid is not None:
        input_cids.append(omission_evidence_cid)
    if audit_case.omission_evidence_cid is not None:
        input_cids.append(audit_case.omission_evidence_cid)
    if audit_case.coverage_manifest_cid is not None:
        input_cids.append(audit_case.coverage_manifest_cid)

    assumptions = _build_assumptions(
        audit_case=audit_case,
        budget=budget,
        disposition=disposition,
    )
    header = _build_plan_header(
        audit_case=audit_case,
        terminal_status=terminal,
        input_cids=input_cids,
        assumptions=assumptions,
        policy_cid=audit_case.policy_cid,
    )

    total_tokens = sum(step.token_increase for step in steps)
    # Defensive: plan contract forbids total > max_token_growth.
    if total_tokens > budget.token_budget and not requires_human_review:
        raise ExpansionPlannerError(
            "internal error: planned tokens exceed token_budget"
        )
    # Human-review plans may use zero token growth even when budget is zero.
    max_token_growth = budget.token_budget
    if requires_human_review and max_token_growth == 0:
        # ContextExpansionPlan requires max_token_growth as token cost (>=0).
        # Zero is allowed; total_token_increase must also be 0.
        max_token_growth = 0

    resolved_plan_id = plan_id or _plan_id_for(
        audit_case,
        tuple(selected) + tuple(skipped) + tuple(deferred_escalation),
        budget,
    )
    # plan_id must be a lowercase token.
    try:
        resolved_plan_id = _token(resolved_plan_id, "plan_id")
    except ExpansionPlannerError:
        resolved_plan_id = _plan_id_for(audit_case, tuple(selected), budget)

    meta: dict[str, Any] = {
        "disposition": disposition,
        "requires_human_review": requires_human_review,
        "context_before_model_escalation": context_before_model_escalation,
        "token_budget": budget.token_budget,
        "selected_count": len(selected),
        "skipped_count": len(skipped),
        "deferred_escalation_count": len(deferred_escalation),
        "reason_codes": list(sorted(set(reason_codes))),
        "budget_view_cid": budget.view_cid,
    }
    if extra_metadata:
        meta.update(dict(extra_metadata))

    try:
        plan = ContextExpansionPlan(
            header=header,
            plan_id=resolved_plan_id,
            audit_case_cid=audit_case.case_cid,
            steps=tuple(steps),
            max_steps=budget.max_steps,
            max_token_growth=max_token_growth if max_token_growth > 0 or total_tokens == 0 else total_tokens,
            total_token_increase=total_tokens,
            step_count=len(steps),
            omission_evidence_cid=(
                omission_evidence_cid
                if omission_evidence_cid is not None
                else audit_case.omission_evidence_cid
            ),
            max_retries=budget.max_retries,
            max_escalations=budget.max_escalations,
            max_wall_time_ms=budget.max_wall_time_ms,
            max_spend_micros=budget.max_spend_micros,
            notes=notes,
            metadata=meta,
        )
    except AuditContractError as exc:
        raise ExpansionPlannerError(str(exc)) from exc

    # When budget is 0 and we have zero-cost steps only, max_token_growth=0 is fine.
    # When we need growth room equal to total, ensure plan max >= total.
    if plan.total_token_increase > plan.max_token_growth:
        raise ExpansionPlannerError(
            "internal error: total_token_increase exceeds max_token_growth"
        )

    return ExpansionPlanResult(
        plan=plan,
        disposition=disposition,
        requires_human_review=requires_human_review,
        context_before_model_escalation=context_before_model_escalation,
        selected_hypothesis_cids=tuple(h.hypothesis_cid for h in selected),
        skipped_hypothesis_cids=tuple(h.hypothesis_cid for h in skipped),
        deferred_escalation_hypothesis_cids=tuple(
            h.hypothesis_cid for h in deferred_escalation
        ),
        reason_codes=tuple(sorted(set(reason_codes))),
        notes=notes,
        metadata={
            "plan_cid": plan.plan_cid,
            "step_count": plan.step_count,
            "total_token_increase": plan.total_token_increase,
        },
    )


def _human_review_result(
    *,
    audit_case: CompressionAuditCase,
    budget: TokenBudgetView,
    reason_code: str,
    context_hyps: Sequence[OmissionHypothesis],
    escalate_hyps: Sequence[OmissionHypothesis],
    review_hyps: Sequence[OmissionHypothesis],
    notes: str,
    omission_evidence_cid: str | None,
    plan_id: str | None,
    context_before_model_escalation: bool = True,
) -> ExpansionPlanResult:
    """Build a bounded human-review plan (never escalates as budget substitute)."""

    # Seed header for the review step using a temporary complete header.
    seed_assumptions = _build_assumptions(
        audit_case=audit_case,
        budget=budget,
        disposition=ExpansionDisposition.HUMAN_REVIEW.value,
    )
    seed_header = _build_plan_header(
        audit_case=audit_case,
        terminal_status=GovernorTerminalStatus.HUMAN_REVIEW_REQUIRED.value,
        input_cids=[audit_case.case_cid, budget.view_cid],
        assumptions=seed_assumptions,
        policy_cid=audit_case.policy_cid,
    )
    primary = (
        review_hyps[0]
        if review_hyps
        else (context_hyps[0] if context_hyps else None)
    )
    step = _build_step(
        header=seed_header,
        index=0,
        action=ExpansionAction.REQUEST_HUMAN_REVIEW.value,
        status=ExpansionStepStatus.PLANNED.value,
        token_increase=0,
        artifact_ids_added=(),
        hypothesis=primary,
        reason_code=reason_code,
        notes=notes,
        metadata={
            "blocked_context_count": len(context_hyps),
            "blocked_escalation_count": len(escalate_hyps),
            "review_hypothesis_count": len(review_hyps),
            "token_budget": budget.token_budget,
        },
    )
    # Escalation hypotheses are recorded as deferred / not executed when
    # context budget is impossible — never promoted ahead of context repair.
    return _finalize_plan(
        audit_case=audit_case,
        budget=budget,
        steps=(step,),
        disposition=ExpansionDisposition.HUMAN_REVIEW.value,
        requires_human_review=True,
        context_before_model_escalation=context_before_model_escalation,
        selected=(),
        skipped=tuple(context_hyps),
        deferred_escalation=tuple(escalate_hyps),
        reason_codes=(reason_code, "human_review_required"),
        notes=notes,
        omission_evidence_cid=omission_evidence_cid,
        plan_id=plan_id,
        extra_metadata={
            "escalation_suppressed_for_context_budget": bool(escalate_hyps),
        },
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def plan_context_expansion(
    audit_case: CompressionAuditCase | Mapping[str, Any],
    omission_hypotheses: Sequence[OmissionHypothesis | Mapping[str, Any]] | None,
    token_budget: int,
    *,
    max_steps: int = DEFAULT_MAX_STEPS,
    max_retries: int = DEFAULT_MAX_RETRIES,
    max_escalations: int = DEFAULT_MAX_ESCALATIONS,
    max_wall_time_ms: int = DEFAULT_MAX_WALL_TIME_MS,
    max_spend_micros: int = DEFAULT_MAX_SPEND_MICROS,
    disclosure_blocked: bool = False,
    omission_evidence_cid: str | None = None,
    plan_id: str | None = None,
    return_result: bool = False,
) -> ContextExpansionPlan | ExpansionPlanResult:
    """Plan the smallest bounded context expansion under a hard token budget.

    Parameters
    ----------
    audit_case:
        Immutable compression audit-case binding (or closed mapping).
    omission_hypotheses:
        Ranked :class:`OmissionHypothesis` sequence (or closed mappings).
        Rank 0 is best. Context-expansion actions are packed first; route
        escalation is deferred until after supported omission expansions.
    token_budget:
        Hard maximum total token growth for the plan (``max_token_growth``).
        Zero with required context expansion yields human review.
    max_steps / max_retries / max_escalations / max_wall_time_ms /
    max_spend_micros:
        Hard plan limits. ``max_steps`` is capped at ``MAX_EXPANSION_STEPS``.
    disclosure_blocked:
        When true, private raw-source expansion is unsafe and returns human
        review instead of a provider-bound expansion plan.
    omission_evidence_cid:
        Optional omission-evidence CID bound on the plan (defaults to the
        audit case binding when present).
    plan_id:
        Optional explicit plan id (must be a lowercase token).
    return_result:
        When true, return :class:`ExpansionPlanResult` with disposition
        metadata; otherwise return the durable :class:`ContextExpansionPlan`.

    Returns
    -------
    ContextExpansionPlan or ExpansionPlanResult
        Bounded plan. Impossible/unsafe budgets produce a human-review plan
        with ``request_human_review`` rather than unbounded growth.

    Raises
    ------
    ExpansionPlannerError
        On fail-closed validation failures.
    """

    case = _normalize_audit_case(audit_case)
    hyps = _normalize_hypotheses(omission_hypotheses)

    budget = TokenBudgetView(
        token_budget=_token_cost(token_budget, "token_budget"),
        max_steps=max_steps,
        max_retries=max_retries,
        max_escalations=max_escalations,
        max_wall_time_ms=max_wall_time_ms,
        max_spend_micros=max_spend_micros,
        disclosure_blocked=_bool(disclosure_blocked, "disclosure_blocked"),
    )
    evidence_cid = _optional_cid(omission_evidence_cid, "omission_evidence_cid")

    context_hyps, escalate_hyps, review_hyps, _noop = _partition_hypotheses(hyps)

    # --- Fail closed: disclosure / review-only / impossible budget ----------
    if budget.disclosure_blocked and context_hyps:
        # Raw/private expansion under blocked disclosure is unsafe.
        if any(
            hyp.expansion_action == ExpansionAction.INCLUDE_RAW_SOURCE.value
            for hyp in context_hyps
        ):
            result = _human_review_result(
                audit_case=case,
                budget=budget,
                reason_code="disclosure_blocked",
                context_hyps=context_hyps,
                escalate_hyps=escalate_hyps,
                review_hyps=review_hyps,
                notes=(
                    "Disclosure policy blocks private raw-source expansion; "
                    "human review required (unsafe budget / disclosure)"
                ),
                omission_evidence_cid=evidence_cid,
                plan_id=plan_id,
            )
            return result if return_result else result.plan

    if review_hyps and not context_hyps:
        result = _human_review_result(
            audit_case=case,
            budget=budget,
            reason_code="hypothesis_requires_human_review",
            context_hyps=context_hyps,
            escalate_hyps=escalate_hyps,
            review_hyps=review_hyps,
            notes=(
                "Ranked hypotheses require human review (stale, policy "
                "boundary, or explicit review action); no safe automatic "
                "context expansion path"
            ),
            omission_evidence_cid=evidence_cid,
            plan_id=plan_id,
        )
        return result if return_result else result.plan

    if context_hyps:
        best = context_hyps[0]
        if budget.token_budget == 0:
            result = _human_review_result(
                audit_case=case,
                budget=budget,
                reason_code="unsafe_zero_budget",
                context_hyps=context_hyps,
                escalate_hyps=escalate_hyps,
                review_hyps=review_hyps,
                notes=(
                    "Token budget is zero but omission expansion is supported; "
                    "impossible/unsafe budget returns human review (escalation "
                    "is not a substitute for context)"
                ),
                omission_evidence_cid=evidence_cid,
                plan_id=plan_id,
            )
            return result if return_result else result.plan
        if best.inclusion_cost_tokens > budget.token_budget:
            result = _human_review_result(
                audit_case=case,
                budget=budget,
                reason_code="budget_impossible",
                context_hyps=context_hyps,
                escalate_hyps=escalate_hyps,
                review_hyps=review_hyps,
                notes=(
                    "Highest-ranked omission expansion exceeds token budget; "
                    "impossible budget returns human review rather than "
                    "unbounded growth or premature model escalation"
                ),
                omission_evidence_cid=evidence_cid,
                plan_id=plan_id,
            )
            return result if return_result else result.plan

    # --- Empty inputs → no-action plan --------------------------------------
    if not context_hyps and not escalate_hyps and not review_hyps:
        seed_assumptions = _build_assumptions(
            audit_case=case,
            budget=budget,
            disposition=ExpansionDisposition.NO_ACTION.value,
        )
        seed_header = _build_plan_header(
            audit_case=case,
            terminal_status=GovernorTerminalStatus.COMPLETE.value,
            input_cids=[case.case_cid, budget.view_cid],
            assumptions=seed_assumptions,
            policy_cid=case.policy_cid,
        )
        # Zero-step plan is valid and bounded.
        result = _finalize_plan(
            audit_case=case,
            budget=budget,
            steps=(),
            disposition=ExpansionDisposition.NO_ACTION.value,
            requires_human_review=False,
            context_before_model_escalation=True,
            selected=(),
            skipped=(),
            deferred_escalation=(),
            reason_codes=("no_action",),
            notes="No omission or route hypotheses; empty bounded expansion plan",
            omission_evidence_cid=evidence_cid,
            plan_id=plan_id,
        )
        # Touch seed_header so identity inputs remain consistent if extended.
        _ = seed_header.repository_state_cid
        return result if return_result else result.plan

    # --- Pack smallest context expansions (rank order, hard bounds) ---------
    seed_assumptions = _build_assumptions(
        audit_case=case,
        budget=budget,
        disposition=ExpansionDisposition.EXPAND.value,
    )
    seed_header = _build_plan_header(
        audit_case=case,
        terminal_status=GovernorTerminalStatus.COMPLETE.value,
        input_cids=[case.case_cid, budget.view_cid]
        + [h.hypothesis_cid for h in hyps],
        assumptions=seed_assumptions,
        policy_cid=case.policy_cid,
    )

    steps: list[ContextExpansionStep] = []
    selected: list[OmissionHypothesis] = []
    skipped: list[OmissionHypothesis] = []
    spent = 0
    seen_artifacts: set[str] = set()
    reason_codes: list[str] = []

    for hyp in context_hyps:
        if len(steps) >= budget.max_steps:
            skipped.append(hyp)
            reason_codes.append("max_steps_bound")
            continue
        if hyp.subject_artifact_id in seen_artifacts:
            skipped.append(hyp)
            reason_codes.append("duplicate_subject_skipped")
            continue
        cost = hyp.inclusion_cost_tokens
        if spent + cost > budget.token_budget:
            # Greedy by rank: skip this candidate; try later cheaper ones.
            skipped.append(hyp)
            reason_codes.append("token_budget_skip")
            continue

        action = hyp.expansion_action
        reason = _REASON_FOR_ACTION.get(action, "omission_repair")
        step = _build_step(
            header=seed_header,
            index=len(steps),
            action=action,
            status=ExpansionStepStatus.PLANNED.value,
            token_increase=cost,
            artifact_ids_added=(hyp.subject_artifact_id,),
            hypothesis=hyp,
            reason_code=reason,
            notes=(
                f"Bounded context expansion for {hyp.subject_artifact_id} "
                f"(rank={hyp.rank}, cost={cost})"
            ),
            metadata={
                "expected_relevance_bp": hyp.expected_relevance_bp,
                "confidence_bp": hyp.confidence_bp,
                "path": hyp.path,
            },
        )
        steps.append(step)
        selected.append(hyp)
        seen_artifacts.add(hyp.subject_artifact_id)
        spent += cost
        reason_codes.append(reason)

    context_steps_planned = len(selected) > 0
    deferred_escalation: list[OmissionHypothesis] = []
    escalations_added = 0

    # Context before model escalation where omission expansion is supported.
    if escalate_hyps:
        if context_hyps and not context_steps_planned:
            # Supported omission path failed to pack anything despite positive
            # budget checks above — treat as unsafe and demand review rather
            # than escalating the model as a substitute.
            result = _human_review_result(
                audit_case=case,
                budget=budget,
                reason_code="context_expansion_unpacked",
                context_hyps=context_hyps,
                escalate_hyps=escalate_hyps,
                review_hyps=review_hyps,
                notes=(
                    "Omission expansion was supported but no context step could "
                    "be packed under bounds; human review required (model "
                    "escalation is not a substitute)"
                ),
                omission_evidence_cid=evidence_cid,
                plan_id=plan_id,
            )
            return result if return_result else result.plan

        for hyp in escalate_hyps:
            if escalations_added >= budget.max_escalations:
                deferred_escalation.append(hyp)
                reason_codes.append("max_escalations_bound")
                continue
            if len(steps) >= budget.max_steps:
                deferred_escalation.append(hyp)
                reason_codes.append("max_steps_bound")
                continue
            # Escalate only after all selected context steps (ordering).
            step = _build_step(
                header=seed_header,
                index=len(steps),
                action=ExpansionAction.ESCALATE_ROUTE.value,
                status=ExpansionStepStatus.PLANNED.value,
                token_increase=0,
                artifact_ids_added=(),
                hypothesis=hyp,
                reason_code=(
                    "model_route_after_context"
                    if context_steps_planned
                    else "model_route_only"
                ),
                notes=(
                    "Route escalation planned only after context expansion "
                    "steps where omission expansion was supported"
                    if context_steps_planned
                    else (
                        "Model-insufficiency route hypothesis only; no "
                        "supported omission expansion path"
                    )
                ),
                metadata={
                    "context_steps_preceding": len(
                        [s for s in steps if s.action in _CONTEXT_EXPANSION_ACTIONS]
                    ),
                    "route_hypothesis": True,
                },
            )
            steps.append(step)
            selected.append(hyp)
            escalations_added += 1
            reason_codes.append(
                "model_route_after_context"
                if context_steps_planned
                else "model_route_only"
            )

    # Explicit review hyps alongside successful context expansion: do not
    # auto-apply them as expansion; record as deferred review pressure in
    # metadata only (plan remains expandable without forcing review when
    # context path succeeded). Callers may still promote to review later.
    if review_hyps and context_steps_planned:
        reason_codes.append("review_hypotheses_deferred")
        deferred_escalation.extend(review_hyps)

    if context_steps_planned and escalations_added > 0:
        disposition = ExpansionDisposition.EXPAND.value
        # Verify ordering invariant: all context indices < first escalate.
        first_escalate = next(
            (
                i
                for i, s in enumerate(steps)
                if s.action == ExpansionAction.ESCALATE_ROUTE.value
            ),
            None,
        )
        if first_escalate is not None:
            for i, s in enumerate(steps):
                if s.action in _CONTEXT_EXPANSION_ACTIONS and i > first_escalate:
                    raise ExpansionPlannerError(
                        "internal error: context step after model escalation"
                    )
        notes = (
            "Bounded context expansion precedes model-route escalation; "
            f"{len([s for s in steps if s.action in _CONTEXT_EXPANSION_ACTIONS])} "
            f"context step(s), {escalations_added} escalation(s), "
            f"total_token_increase={spent}"
        )
    elif context_steps_planned:
        disposition = ExpansionDisposition.EXPAND.value
        notes = (
            "Smallest bounded context expansion planned from ranked omission "
            f"hypotheses; step_count={len(steps)}, total_token_increase={spent}"
        )
    elif escalations_added > 0:
        disposition = ExpansionDisposition.ESCALATE_ONLY.value
        notes = (
            "No supported omission expansion; route escalation only "
            f"({escalations_added} step(s))"
        )
    else:
        disposition = ExpansionDisposition.NO_ACTION.value
        notes = "No packable expansion steps under bounds"

    context_before = True
    if escalations_added > 0 and context_steps_planned:
        context_before = True
    elif escalations_added > 0 and not context_hyps:
        # Escalate-only is valid when omission expansion is not supported.
        context_before = True

    result = _finalize_plan(
        audit_case=case,
        budget=budget,
        steps=tuple(steps),
        disposition=disposition,
        requires_human_review=False,
        context_before_model_escalation=context_before,
        selected=tuple(selected),
        skipped=tuple(skipped),
        deferred_escalation=tuple(deferred_escalation),
        reason_codes=tuple(reason_codes) or ("no_action",),
        notes=notes,
        omission_evidence_cid=evidence_cid,
        plan_id=plan_id,
        extra_metadata={
            "context_step_count": len(
                [s for s in steps if s.action in _CONTEXT_EXPANSION_ACTIONS]
            ),
            "escalation_step_count": escalations_added,
            "spent_tokens": spent,
        },
    )

    # Final bound assertions (acceptance: expanded context remains bounded).
    plan = result.plan
    if plan.step_count > plan.max_steps:
        raise ExpansionPlannerError("plan exceeds max_steps bound")
    if plan.step_count > MAX_EXPANSION_STEPS:
        raise ExpansionPlannerError("plan exceeds absolute expansion step bound")
    if plan.total_token_increase > plan.max_token_growth:
        raise ExpansionPlannerError("plan exceeds max_token_growth bound")
    if plan.total_token_increase > budget.token_budget and budget.token_budget > 0:
        raise ExpansionPlannerError("plan exceeds token_budget")

    return result if return_result else result.plan


def plan_context_expansion_interface_id() -> str:
    """Return the versioned public interface pin for this planner."""

    return PLAN_CONTEXT_EXPANSION_INTERFACE


def context_expansion_actions() -> tuple[str, ...]:
    """Return actions that expand context (precede model escalation)."""

    return tuple(sorted(_CONTEXT_EXPANSION_ACTIONS))


def route_escalation_actions() -> tuple[str, ...]:
    """Return actions that escalate model route (after context where supported)."""

    return tuple(sorted(_ROUTE_ESCALATION_ACTIONS))


def default_expansion_limits() -> dict[str, int]:
    """Return default hard plan limits."""

    return {
        "max_steps": DEFAULT_MAX_STEPS,
        "max_retries": DEFAULT_MAX_RETRIES,
        "max_escalations": DEFAULT_MAX_ESCALATIONS,
        "max_wall_time_ms": DEFAULT_MAX_WALL_TIME_MS,
        "max_spend_micros": DEFAULT_MAX_SPEND_MICROS,
        "max_expansion_steps_absolute": MAX_EXPANSION_STEPS,
    }


__all__ = [
    "DEFAULT_MAX_ESCALATIONS",
    "DEFAULT_MAX_RETRIES",
    "DEFAULT_MAX_SPEND_MICROS",
    "DEFAULT_MAX_STEPS",
    "DEFAULT_MAX_WALL_TIME_MS",
    "EXPANSION_PLANNER_SCHEMA",
    "EXPANSION_PLAN_RESULT_SCHEMA",
    "PLAN_CONTEXT_EXPANSION_INTERFACE",
    "TOKEN_BUDGET_VIEW_SCHEMA",
    "ExpansionDisposition",
    "ExpansionPlanResult",
    "ExpansionPlannerError",
    "TokenBudgetView",
    "context_expansion_actions",
    "default_expansion_limits",
    "plan_context_expansion",
    "plan_context_expansion_interface_id",
    "route_escalation_actions",
]
