"""End-to-end Intent IR domain logic slice (``IntentLogicSlice@2``).

Connects admitted Intent IR base goals, guards, workflows, and policy views
through a single typed vertical path:

    typed origin → semantics → translation → request → result → replay
    → authority lineage

Base routes admitted here (Wave-2, before LFP2-044 overlays):

* typed intent facts (first-order)
* skill effects (dynamic / Hoare under ``program``)
* prompt-derived candidates (never proof from confidence alone)
* skill goals under existing intention paths
* guards / effects under first-order
* workflow temporal control
* tool authorization / invocation constraints
* deontic / modal policy views
* safety and liveness as **property kinds** under temporal
* verification conditions as a **view role** (never a family)

Every admitted route carries source-span-to-result lineage.  Source grounding,
tool authority, bound, policy authority, and advisor-scope assumptions are
explicit.  Advisor confidence cannot establish intent correctness.

Normative and full BDI/agency overlays attach only in LFP2-044 after LFP2-037
and LFP2-040.  Hermetic fixtures supply provider execution and replay without
requiring live provers.  Tool absence remains an availability result, not a
mock proof.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any, ClassVar, Final

from ipfs_datasets_py.logic.backends.artifacts_v2 import (
    CompiledLogicArtifact,
    ParsedTargetArtifact,
    admit_compiled_target,
    admit_parsed_result,
)
from ipfs_datasets_py.logic.backends.evidence_v2 import (
    EvidenceReplayReceipt,
    ExecutionOutcome,
    ExecutionRecordKind,
    ProviderExecutionReceiptV2,
    ReplayDisposition,
)
from ipfs_datasets_py.logic.backends.requests_v2 import (
    BackendRequestV2,
    LogicObligationV2,
    RequestAuthorityCeiling,
    RequestBounds,
)
from ipfs_datasets_py.logic.backends.results import ResultAuthority
from ipfs_datasets_py.logic.families.namespaces import (
    LogicIdentity,
    encoding_id,
    evidence_id,
    notation_id,
    property_id,
    provider_id,
    view_id,
)
from ipfs_datasets_py.logic.formalization.artifacts_v3 import (
    DomainLogicSliceV2,
)
from ipfs_datasets_py.logic.intent_ir.formalize.typed_compiler import (
    INTENT_IR_DOMAIN_ID,
    NEVER_FAMILY_OPERATION_ROLES,
    NEVER_FAMILY_PROPERTY_KINDS,
    FormulaStatus,
    IntentFormalizationCompiler,
    OperationRoleAsFamilyError,
    PropertyAsFamilyError,
    ToolAuthorityFromConfidenceError,
    classify_formula_candidate,
    is_never_family_label,
    is_never_family_property,
    reject_operation_role_as_family,
    reject_property_as_family,
    reject_tool_authority_from_confidence,
    resolve_intent_route,
)
from ipfs_datasets_py.logic.syntax_core.ast import TypedExpression, mk_extension
from ipfs_datasets_py.logic.syntax_core.contracts import (
    SourceDocument,
    SourceMap,
    SourceMapEntry,
    SourceRange,
    content_sha256,
    canonical_json_bytes,
)
from ipfs_datasets_py.logic.syntax_core.signatures import LogicSignature
from ipfs_datasets_py.logic.translations.catalog import (
    LogicTranslationGraph,
    build_logic_translation_graph,
)
from ipfs_datasets_py.logic.translations.policy_modal import (
    build_policy_modal_translation_edges,
)
from ipfs_datasets_py.logic.translations.program import (
    build_program_translation_edges,
)
from ipfs_datasets_py.logic.translations.state_temporal import (
    build_state_temporal_edges,
)

# ---------------------------------------------------------------------------
# Interface / schema identities
# ---------------------------------------------------------------------------

INTENT_LOGIC_SLICE_INTERFACE: Final = "IntentLogicSlice@2"
INTENT_LOGIC_SLICE_SCHEMA: Final = "intent-logic-slice/v2"
INTENT_LOGIC_SLICE_VERSION: Final = "2.0.0"
OBLIGATION_LINEAGE_SCHEMA: Final = "intent-obligation-lineage/v2"
DOMAIN_ID: Final = INTENT_IR_DOMAIN_ID

# Required lineage stages for every admitted route (acceptance criterion).
LINEAGE_STAGES: Final[tuple[str, ...]] = (
    "typed_origin",
    "semantics",
    "translation",
    "request",
    "result",
    "replay",
    "authority_lineage",
)

# Explicit assumption categories required by LFP2-024 acceptance.
ASSUMPTION_CATEGORIES: Final[tuple[str, ...]] = (
    "source_grounding",
    "tool_authority",
    "bound",
    "policy_authority",
    "advisor_scope",
)

# Evidence subset named by the backlog task (must appear in supported kinds).
EVIDENCE_SUBSET: Final[tuple[str, ...]] = (
    "intent",
    "skill",
    "prompt",
    "goal",
    "guard",
    "workflow",
    "authorization",
    "policy",
)

# Property kinds that must never become families on intent slices.
PROPERTY_KIND_ROUTE_KINDS: Final[frozenset[str]] = frozenset(
    {
        "safety",
        "liveness",
    }
)

# View roles that must never become families on intent slices.
VIEW_ROLE_ROUTE_KINDS: Final[frozenset[str]] = frozenset(
    {
        "verification_condition",
    }
)

# Deferred overlays / non-family roles (LFP2-044 after LFP2-037 / LFP2-040).
DEFERRED_ROUTE_KINDS: Final[frozenset[str]] = frozenset(
    {
        "bdi_overlay",
        "agency_overlay",
        "normative_overlay",
        "argumentation",
        "description_logic",
        "free_form",
        "boolean_receipt",
        "graph_projection",
        "proof_translation",
        "structural_round_trip",
    }
)


class IntentSliceError(ValueError):
    """Raised when an Intent IR logic slice cannot be admitted."""


class ObligationLineageError(IntentSliceError):
    """Raised when required lineage stages are missing or inconsistent."""


class UnsupportedRouteError(IntentSliceError):
    """Raised for routes outside the admitted Intent IR set."""


class AdvisorConfidenceAsCorrectnessError(IntentSliceError):
    """Raised when advisor confidence is offered as intent correctness."""


class IntentRouteKind(StrEnum):
    """Admitted Intent IR route classes connected end to end by this slice."""

    INTENT = "intent"
    SKILL = "skill"
    PROMPT = "prompt"
    GOAL = "goal"
    GUARD = "guard"
    WORKFLOW = "workflow"
    AUTHORIZATION = "authorization"
    POLICY = "policy"
    SAFETY = "safety"
    LIVENESS = "liveness"
    VERIFICATION_CONDITION = "verification_condition"


SUPPORTED_ROUTE_KINDS: Final[tuple[IntentRouteKind, ...]] = (
    IntentRouteKind.INTENT,
    IntentRouteKind.SKILL,
    IntentRouteKind.PROMPT,
    IntentRouteKind.GOAL,
    IntentRouteKind.GUARD,
    IntentRouteKind.WORKFLOW,
    IntentRouteKind.AUTHORIZATION,
    IntentRouteKind.POLICY,
    IntentRouteKind.SAFETY,
    IntentRouteKind.LIVENESS,
    IntentRouteKind.VERIFICATION_CONDITION,
)


class IntentRouteNamespace(StrEnum):
    """Semantic role of an intent slice route (mirrors typed-compiler namespaces)."""

    FAMILY = "family"
    PROFILE = "profile"
    PROPERTY = "property"
    VIEW_ROLE = "view_role"


@dataclass(frozen=True, slots=True)
class ExplicitAssumptions:
    """Closed assumption axes required for every admitted intent route.

    Empty tuples are allowed only when the axis is not applicable; the
    descriptor still declares the axis so omission is never silent.
    """

    source_grounding: tuple[str, ...]
    tool_authority: tuple[str, ...]
    bound: tuple[str, ...]
    policy_authority: tuple[str, ...]
    advisor_scope: tuple[str, ...]

    def all_ids(self) -> tuple[str, ...]:
        """Flatten unique assumption ids in stable category order."""

        ordered: list[str] = []
        seen: set[str] = set()
        for group in (
            self.source_grounding,
            self.tool_authority,
            self.bound,
            self.policy_authority,
            self.advisor_scope,
        ):
            for item in group:
                if item not in seen:
                    seen.add(item)
                    ordered.append(item)
        return tuple(ordered)

    def to_dict(self) -> dict[str, Any]:
        return {
            "advisor_scope": list(self.advisor_scope),
            "bound": list(self.bound),
            "policy_authority": list(self.policy_authority),
            "source_grounding": list(self.source_grounding),
            "tool_authority": list(self.tool_authority),
        }


@dataclass(frozen=True, slots=True)
class ObligationRouteDescriptor:
    """Static routing metadata for one admitted Intent IR route class."""

    kind: IntentRouteKind
    family_id: str
    profile_id: str
    property_name: str
    view_name: str
    notation_name: str
    encoding_name: str
    evidence_name: str
    provider_name: str
    authority_ceiling: RequestAuthorityCeiling
    result_authority: ResultAuthority
    translation_edge_id: str
    translation_family: str
    compiler_id: str
    result_kind: str
    statement: str
    target_text: str
    result_output: str
    assumptions: ExplicitAssumptions
    route_namespace: IntentRouteNamespace = IntentRouteNamespace.PROFILE
    intent_view_name: str = ""
    features: tuple[str, ...] = ()
    notes: str = ""
    intent_route_id: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.kind, IntentRouteKind):
            object.__setattr__(self, "kind", IntentRouteKind(self.kind))
        if not isinstance(self.authority_ceiling, RequestAuthorityCeiling):
            object.__setattr__(
                self,
                "authority_ceiling",
                RequestAuthorityCeiling(self.authority_ceiling),
            )
        if not isinstance(self.result_authority, ResultAuthority):
            object.__setattr__(
                self, "result_authority", ResultAuthority(self.result_authority)
            )
        if not isinstance(self.route_namespace, IntentRouteNamespace):
            object.__setattr__(
                self,
                "route_namespace",
                IntentRouteNamespace(self.route_namespace),
            )
        if not isinstance(self.assumptions, ExplicitAssumptions):
            raise IntentSliceError(
                f"route {self.kind.value!r} requires ExplicitAssumptions"
            )
        for axis in ASSUMPTION_CATEGORIES:
            if not hasattr(self.assumptions, axis):
                raise IntentSliceError(
                    f"route {self.kind.value!r} missing assumption axis {axis!r}"
                )
        # Fail closed: property and view-role kinds keep their namespaces.
        if self.kind.value in PROPERTY_KIND_ROUTE_KINDS:
            if self.route_namespace is not IntentRouteNamespace.PROPERTY:
                raise IntentSliceError(
                    f"route {self.kind.value!r} must remain a property kind"
                )
            if self.property_name not in PROPERTY_KIND_ROUTE_KINDS:
                raise IntentSliceError(
                    f"property route {self.kind.value!r} requires matching property_name"
                )
        if self.kind.value in VIEW_ROLE_ROUTE_KINDS:
            if self.route_namespace is not IntentRouteNamespace.VIEW_ROLE:
                raise IntentSliceError(
                    f"route {self.kind.value!r} must remain a view role"
                )
            if self.view_name != "verification_condition":
                raise IntentSliceError(
                    f"view-role route {self.kind.value!r} requires "
                    "view_name='verification_condition'"
                )
            if self.family_id in NEVER_FAMILY_OPERATION_ROLES:
                raise IntentSliceError(
                    f"view-role route {self.kind.value!r} must not use a "
                    "view-role label as family_id"
                )

    @property
    def assumption_ids(self) -> tuple[str, ...]:
        return self.assumptions.all_ids()

    @property
    def is_property_kind(self) -> bool:
        return self.route_namespace is IntentRouteNamespace.PROPERTY

    @property
    def is_view_role(self) -> bool:
        return self.route_namespace is IntentRouteNamespace.VIEW_ROLE

    @property
    def is_semantic_family(self) -> bool:
        return self.route_namespace in {
            IntentRouteNamespace.FAMILY,
            IntentRouteNamespace.PROFILE,
        }


def default_obligation_routes() -> Mapping[
    IntentRouteKind, ObligationRouteDescriptor
]:
    """Return the sealed admitted-route table for Intent IR."""

    advisor_candidate = (
        "assumption:advisor_candidate_only",
        "assumption:advisor_confidence_not_correctness",
    )
    rows: tuple[ObligationRouteDescriptor, ...] = (
        ObligationRouteDescriptor(
            kind=IntentRouteKind.INTENT,
            family_id="first_order",
            profile_id="default",
            property_name="validity",
            view_name="facts",
            notation_name="intent_facts",
            encoding_name="smtlib2",
            evidence_name="model",
            provider_name="z3",
            authority_ceiling=RequestAuthorityCeiling.SATISFIABILITY,
            result_authority=ResultAuthority.SATISFIABILITY,
            translation_edge_id="vc_to_smt",
            translation_family="program",
            compiler_id="intent.facts.smtlib2",
            result_kind="satisfiability.unsat",
            statement=(
                "Discharge typed Intent IR facts under first-order signature "
                "and source-grounded entity/predicate identity."
            ),
            target_text="(assert (not intent_fact_goal))",
            result_output="unsat",
            assumptions=ExplicitAssumptions(
                source_grounding=(
                    "assumption:source_grounding",
                    "assumption:entity_identity",
                    "assumption:predicate_signature",
                ),
                tool_authority=(),
                bound=("bound:quantifier_instantiations",),
                policy_authority=(),
                advisor_scope=advisor_candidate,
            ),
            route_namespace=IntentRouteNamespace.FAMILY,
            intent_view_name="facts",
            features=("intent_ir.intent", "first_order.facts"),
            notes="Typed intent facts never weaken to free-form family labels.",
            intent_route_id="intent-route/facts/v1",
        ),
        ObligationRouteDescriptor(
            kind=IntentRouteKind.SKILL,
            family_id="program",
            profile_id="dynamic_hoare",
            property_name="partial_correctness",
            view_name="action_hoare",
            notation_name="hoare_action_contract",
            encoding_name="smtlib2",
            evidence_name="model",
            provider_name="z3",
            authority_ceiling=RequestAuthorityCeiling.CANDIDATE,
            result_authority=ResultAuthority.CANDIDATE,
            translation_edge_id="program_to_smt",
            translation_family="program",
            compiler_id="intent.skill.program_smt",
            result_kind="candidate.partial_correctness",
            statement=(
                "Check skill action effects as dynamic/Hoare contracts with "
                "explicit preconditions, postconditions, and frame conditions."
            ),
            target_text="(assert (not skill_postcondition))",
            result_output="candidate",
            assumptions=ExplicitAssumptions(
                source_grounding=(
                    "assumption:source_grounding",
                    "assumption:action_identity",
                    "assumption:frame_conditions",
                ),
                tool_authority=(),
                bound=("bound:program_steps",),
                policy_authority=(),
                advisor_scope=advisor_candidate,
            ),
            route_namespace=IntentRouteNamespace.PROFILE,
            intent_view_name="action_hoare",
            features=("intent_ir.skill", "program.dynamic_hoare"),
            notes="Skill effects lower through program→SMT edges.",
            intent_route_id="intent-route/action-hoare/v1",
        ),
        ObligationRouteDescriptor(
            kind=IntentRouteKind.PROMPT,
            family_id="first_order",
            profile_id="default",
            property_name="validity",
            view_name="facts",
            notation_name="prompt_candidate",
            encoding_name="smtlib2",
            evidence_name="candidate",
            provider_name="z3",
            authority_ceiling=RequestAuthorityCeiling.CANDIDATE,
            result_authority=ResultAuthority.CANDIDATE,
            translation_edge_id="vc_to_smt",
            translation_family="program",
            compiler_id="intent.prompt.candidate",
            result_kind="candidate.prompt_derived",
            statement=(
                "Admit prompt-derived Intent formulas only as candidates until "
                "deterministic parse, typecheck, and verification receipts exist."
            ),
            target_text="(assert (not prompt_candidate))",
            result_output="candidate",
            assumptions=ExplicitAssumptions(
                source_grounding=(
                    "assumption:prompt_derived",
                    "assumption:source_grounding_required",
                    "assumption:parse_typecheck_required",
                ),
                tool_authority=(),
                bound=(),
                policy_authority=(),
                advisor_scope=(
                    "assumption:advisor_candidate_only",
                    "assumption:advisor_confidence_not_correctness",
                    "assumption:prompt_confidence_not_correctness",
                ),
            ),
            route_namespace=IntentRouteNamespace.FAMILY,
            intent_view_name="facts",
            features=("intent_ir.prompt", "first_order.candidate"),
            notes=(
                "Prompt confidence and advisor scores never establish intent "
                "correctness."
            ),
            intent_route_id="intent-route/facts/v1",
        ),
        ObligationRouteDescriptor(
            kind=IntentRouteKind.GOAL,
            family_id="intention_agency",
            profile_id="skill_goals",
            property_name="goal_satisfaction",
            view_name="skill_goals",
            notation_name="skill_goal",
            encoding_name="smtlib2",
            evidence_name="candidate",
            provider_name="z3",
            authority_ceiling=RequestAuthorityCeiling.CANDIDATE,
            result_authority=ResultAuthority.CANDIDATE,
            translation_edge_id="intention_to_fol_reified",
            translation_family="policy_modal",
            compiler_id="intent.goal.intention_fol",
            result_kind="candidate.goal",
            statement=(
                "Type skill goals under intention/agency identity with explicit "
                "agent, goal, and intention-force assumptions."
            ),
            target_text="(assert (not skill_goal_holds))",
            result_output="candidate",
            assumptions=ExplicitAssumptions(
                source_grounding=(
                    "assumption:source_grounding",
                    "assumption:goal_identity",
                    "assumption:agent_identity",
                    "assumption:intention_force",
                ),
                tool_authority=(),
                bound=(),
                policy_authority=(),
                advisor_scope=advisor_candidate,
            ),
            route_namespace=IntentRouteNamespace.PROFILE,
            intent_view_name="skill_goals",
            features=("intent_ir.goal", "intention_agency.skill_goals"),
            notes=(
                "Full BDI/agency overlays remain deferred to LFP2-044; base "
                "goal routes use existing intention paths only."
            ),
            intent_route_id="intent-route/skill-goals/v1",
        ),
        ObligationRouteDescriptor(
            kind=IntentRouteKind.GUARD,
            family_id="first_order",
            profile_id="guards_effects",
            property_name="guard",
            view_name="guards_effects",
            notation_name="guard_predicate",
            encoding_name="smtlib2",
            evidence_name="model",
            provider_name="z3",
            authority_ceiling=RequestAuthorityCeiling.SATISFIABILITY,
            result_authority=ResultAuthority.SATISFIABILITY,
            translation_edge_id="vc_to_smt",
            translation_family="program",
            compiler_id="intent.guard.smtlib2",
            result_kind="satisfiability.unsat",
            statement=(
                "Check typed Intent guards and effects as first-order "
                "predicates with explicit polarity and source grounding."
            ),
            target_text="(assert (not guard_holds))",
            result_output="unsat",
            assumptions=ExplicitAssumptions(
                source_grounding=(
                    "assumption:source_grounding",
                    "assumption:guard_polarity",
                    "assumption:effect_polarity",
                    "assumption:predicate_signature",
                ),
                tool_authority=(),
                bound=("bound:quantifier_instantiations",),
                policy_authority=(),
                advisor_scope=advisor_candidate,
            ),
            route_namespace=IntentRouteNamespace.PROFILE,
            intent_view_name="guards_effects",
            features=("intent_ir.guard", "first_order.guards_effects"),
            notes="Guards never promote advisor confidence to correctness.",
            intent_route_id="intent-route/guards-effects/v1",
        ),
        ObligationRouteDescriptor(
            kind=IntentRouteKind.WORKFLOW,
            family_id="temporal",
            profile_id="workflow_temporal",
            property_name="ordering",
            view_name="workflows",
            notation_name="workflow_temporal",
            encoding_name="tla_plus",
            evidence_name="bounded",
            provider_name="tla_tlc",
            authority_ceiling=RequestAuthorityCeiling.BOUNDED,
            result_authority=ResultAuthority.MODEL_CHECK,
            translation_edge_id="temporal_ltl_to_tla_plus",
            translation_family="state_temporal",
            compiler_id="intent.workflow.tla_plus",
            result_kind="model_check.satisfied",
            statement=(
                "Model-check workflow sequencing, branching, retry, and "
                "concurrency under explicit trace bounds and fairness."
            ),
            target_text="[] workflow_ordered",
            result_output="satisfied",
            assumptions=ExplicitAssumptions(
                source_grounding=(
                    "assumption:source_grounding",
                    "assumption:edge_direction",
                    "assumption:temporal_operator",
                ),
                tool_authority=(),
                bound=(
                    "bound:trace_length",
                    "bound:bound_depth",
                    "assumption:trace_model",
                    "assumption:fairness_constraint",
                ),
                policy_authority=(),
                advisor_scope=advisor_candidate,
            ),
            route_namespace=IntentRouteNamespace.PROFILE,
            intent_view_name="workflows",
            features=("intent_ir.workflow", "temporal.workflow_temporal"),
            notes="Workflow bounds and fairness cannot be omitted.",
            intent_route_id="intent-route/workflow-temporal/v1",
        ),
        ObligationRouteDescriptor(
            kind=IntentRouteKind.AUTHORIZATION,
            family_id="authorization",
            profile_id="tool_permissions",
            property_name="authorization",
            view_name="tool_permissions",
            notation_name="tool_permission",
            encoding_name="datalog",
            evidence_name="authorization",
            provider_name="datalog_secpal",
            authority_ceiling=RequestAuthorityCeiling.AUTHORIZATION,
            result_authority=ResultAuthority.AUTHORIZATION,
            translation_edge_id="authorization_to_secpal",
            translation_family="policy_modal",
            compiler_id="intent.authorization.secpal",
            result_kind="authorization.allow",
            statement=(
                "Evaluate tool and resource permissions under grounded "
                "authorization evidence; confidence alone never grants authority."
            ),
            target_text="says(Admin, can(Agent, invoke(Tool)))",
            result_output="allow",
            assumptions=ExplicitAssumptions(
                source_grounding=(
                    "assumption:source_grounding",
                    "assumption:principal_identity",
                    "assumption:resource_identity",
                ),
                tool_authority=(
                    "assumption:grounded_permission_required",
                    "assumption:tool_authority_not_from_confidence",
                    "assumption:delegation_scope",
                    "assumption:action_identity",
                ),
                bound=(),
                policy_authority=(
                    "assumption:policy_authority_bound",
                    "assumption:effect_polarity",
                ),
                advisor_scope=advisor_candidate,
            ),
            route_namespace=IntentRouteNamespace.PROFILE,
            intent_view_name="tool_permissions",
            features=("intent_ir.authorization", "authorization.tool_permissions"),
            notes="Tool authority never follows confidence alone.",
            intent_route_id="intent-route/tool-permissions/v1",
        ),
        ObligationRouteDescriptor(
            kind=IntentRouteKind.POLICY,
            family_id="deontic",
            profile_id="default",
            property_name="obligation",
            view_name="norms",
            notation_name="deontic_norm",
            encoding_name="smtlib2",
            evidence_name="candidate",
            provider_name="z3",
            authority_ceiling=RequestAuthorityCeiling.CANDIDATE,
            result_authority=ResultAuthority.CANDIDATE,
            translation_edge_id="deontic_to_fol_reified",
            translation_family="policy_modal",
            compiler_id="intent.policy.deontic_fol",
            result_kind="candidate.norm",
            statement=(
                "Type Intent policy/modal norms (permissions, obligations, "
                "prohibitions) through existing deontic reification."
            ),
            target_text="(assert (not O(agent, action)))",
            result_output="candidate",
            assumptions=ExplicitAssumptions(
                source_grounding=(
                    "assumption:source_grounding",
                    "assumption:actor_identity",
                    "assumption:action_identity",
                    "assumption:operator_force",
                    "assumption:norm_polarity",
                ),
                tool_authority=(),
                bound=(),
                policy_authority=(
                    "assumption:policy_authority_bound",
                    "assumption:world_policy",
                ),
                advisor_scope=advisor_candidate,
            ),
            route_namespace=IntentRouteNamespace.FAMILY,
            intent_view_name="norms",
            features=("intent_ir.policy", "deontic.norms"),
            notes=(
                "Prioritized normative overlays beyond base deontic attach in "
                "LFP2-044 after LFP2-037."
            ),
            intent_route_id="intent-route/norms/v1",
        ),
        ObligationRouteDescriptor(
            kind=IntentRouteKind.SAFETY,
            family_id="temporal",
            profile_id="safety",
            property_name="safety",
            view_name="safety",
            notation_name="safety_invariant",
            encoding_name="tla_plus",
            evidence_name="bounded",
            provider_name="tla_tlc",
            authority_ceiling=RequestAuthorityCeiling.BOUNDED,
            result_authority=ResultAuthority.MODEL_CHECK,
            translation_edge_id="temporal_ltl_to_tla_plus",
            translation_family="state_temporal",
            compiler_id="intent.safety.tla_plus",
            result_kind="model_check.satisfied",
            statement=(
                "Check Intent safety as a temporal property kind (never a "
                "semantic family) under explicit bounds."
            ),
            target_text="[] intent_safe",
            result_output="satisfied",
            assumptions=ExplicitAssumptions(
                source_grounding=(
                    "assumption:source_grounding",
                    "assumption:invariant_polarity",
                    "assumption:bad_state_exclusion",
                ),
                tool_authority=(),
                bound=(
                    "bound:trace_length",
                    "bound:bound_depth",
                ),
                policy_authority=(),
                advisor_scope=advisor_candidate,
            ),
            route_namespace=IntentRouteNamespace.PROPERTY,
            intent_view_name="safety",
            features=("intent_ir.safety", "temporal.safety"),
            notes="Safety remains a property kind under temporal, never a family.",
            intent_route_id="intent-route/safety/v1",
        ),
        ObligationRouteDescriptor(
            kind=IntentRouteKind.LIVENESS,
            family_id="temporal",
            profile_id="liveness",
            property_name="liveness",
            view_name="liveness",
            notation_name="liveness_progress",
            encoding_name="runtime_mtl",
            evidence_name="trace",
            provider_name="runtime_mtl",
            authority_ceiling=RequestAuthorityCeiling.FINITE_TRACE,
            result_authority=ResultAuthority.MONITOR,
            translation_edge_id="temporal_mtl_to_runtime_mtl",
            translation_family="state_temporal",
            compiler_id="intent.liveness.runtime_mtl",
            result_kind="monitor.progress",
            statement=(
                "Check Intent liveness as a temporal property kind (never a "
                "semantic family) under fairness and finite-trace bounds."
            ),
            target_text="<> intent_progress",
            result_output="progress",
            assumptions=ExplicitAssumptions(
                source_grounding=(
                    "assumption:source_grounding",
                    "assumption:progress_condition",
                    "assumption:fairness_constraint",
                ),
                tool_authority=(),
                bound=(
                    "bound:trace_length",
                    "assumption:finite_trace",
                ),
                policy_authority=(),
                advisor_scope=advisor_candidate,
            ),
            route_namespace=IntentRouteNamespace.PROPERTY,
            intent_view_name="liveness",
            features=("intent_ir.liveness", "temporal.liveness"),
            notes="Liveness remains a property kind under temporal, never a family.",
            intent_route_id="intent-route/liveness/v1",
        ),
        ObligationRouteDescriptor(
            kind=IntentRouteKind.VERIFICATION_CONDITION,
            # Underlying typed family for expression identity only; VC itself
            # remains a view role and must never appear as family_id.
            family_id="program",
            profile_id="dynamic_hoare",
            property_name="validity",
            view_name="verification_condition",
            notation_name="vc_surface",
            encoding_name="smtlib2",
            evidence_name="candidate",
            provider_name="z3",
            authority_ceiling=RequestAuthorityCeiling.CANDIDATE,
            result_authority=ResultAuthority.CANDIDATE,
            translation_edge_id="vc_to_smt",
            translation_family="program",
            compiler_id="intent.vc.smtlib2",
            result_kind="candidate.vc",
            statement=(
                "Materialize Intent verification-condition obligations as a "
                "view role (never a semantic family)."
            ),
            target_text="(assert (not intent_vc))",
            result_output="candidate",
            assumptions=ExplicitAssumptions(
                source_grounding=(
                    "assumption:source_grounding",
                    "assumption:obligation_identity",
                    "assumption:assumption_set",
                ),
                tool_authority=(),
                bound=("bound:vc_depth",),
                policy_authority=(),
                advisor_scope=advisor_candidate,
            ),
            route_namespace=IntentRouteNamespace.VIEW_ROLE,
            intent_view_name="verification_condition",
            features=(
                "intent_ir.verification_condition",
                "program.verification_condition",
            ),
            notes="VC is a view role, never a family.",
            intent_route_id="intent-route/verification-condition-role/v1",
        ),
    )
    return MappingProxyType({item.kind: item for item in rows})


# ---------------------------------------------------------------------------
# Lineage records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TypedOriginLineage:
    """Exact source and typed-expression identity for one route."""

    document_id: str
    source_digest: str
    expression_id: str
    expression_digest: str
    domain_slice_id: str
    domain_slice_digest: str
    route_kind: str
    source_range: SourceRange | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "document_id": self.document_id,
            "domain_slice_digest": self.domain_slice_digest,
            "domain_slice_id": self.domain_slice_id,
            "expression_digest": self.expression_digest,
            "expression_id": self.expression_id,
            "route_kind": self.route_kind,
            "source_digest": self.source_digest,
            "source_range": None
            if self.source_range is None
            else self.source_range.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class SemanticsLineage:
    """Typed semantic namespaces for one route."""

    family: str
    profile: str
    property: str
    view: str
    notation: str
    features: tuple[str, ...]
    assumption_ids: tuple[str, ...]
    statement: str
    assumptions: ExplicitAssumptions
    route_namespace: str
    is_property_kind: bool
    is_view_role: bool
    is_semantic_family: bool
    domain: str = DOMAIN_ID
    intent_route_id: str = ""
    intent_view_name: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "assumption_ids": list(self.assumption_ids),
            "assumptions": self.assumptions.to_dict(),
            "domain": self.domain,
            "family": self.family,
            "features": list(self.features),
            "intent_route_id": self.intent_route_id,
            "intent_view_name": self.intent_view_name,
            "is_property_kind": self.is_property_kind,
            "is_semantic_family": self.is_semantic_family,
            "is_view_role": self.is_view_role,
            "notation": self.notation,
            "profile": self.profile,
            "property": self.property,
            "route_namespace": self.route_namespace,
            "statement": self.statement,
            "view": self.view,
        }


@dataclass(frozen=True, slots=True)
class TranslationLineage:
    """Reviewed translation edge binding for one route."""

    edge_id: str
    family_key: str
    source_family_id: str
    target_family_id: str
    preservation: str
    authority_ceiling: str
    compiler_id: str
    content_id: str
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority_ceiling": self.authority_ceiling,
            "compiler_id": self.compiler_id,
            "content_id": self.content_id,
            "description": self.description,
            "edge_id": self.edge_id,
            "family_key": self.family_key,
            "preservation": self.preservation,
            "source_family_id": self.source_family_id,
            "target_family_id": self.target_family_id,
        }


@dataclass(frozen=True, slots=True)
class RequestLineage:
    """BackendRequest@2 / LogicObligation@2 identities."""

    obligation_id: str
    obligation_digest: str
    request_id: str
    request_digest: str
    encoding: str
    evidence_kind: str
    provider: str
    authority_ceiling: str
    bounds: Mapping[str, int]

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority_ceiling": self.authority_ceiling,
            "bounds": dict(self.bounds),
            "encoding": self.encoding,
            "evidence_kind": self.evidence_kind,
            "obligation_digest": self.obligation_digest,
            "obligation_id": self.obligation_id,
            "provider": self.provider,
            "request_digest": self.request_digest,
            "request_id": self.request_id,
        }


@dataclass(frozen=True, slots=True)
class ResultLineage:
    """Compiled/parsed result identities and authority."""

    compiled_artifact_id: str
    compiled_artifact_digest: str
    parsed_artifact_id: str
    parsed_artifact_digest: str
    result_kind: str
    result_authority: str
    output_digest: str
    result_digest: str
    decoded_evidence_digest: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "compiled_artifact_digest": self.compiled_artifact_digest,
            "compiled_artifact_id": self.compiled_artifact_id,
            "decoded_evidence_digest": self.decoded_evidence_digest,
            "output_digest": self.output_digest,
            "parsed_artifact_digest": self.parsed_artifact_digest,
            "parsed_artifact_id": self.parsed_artifact_id,
            "result_authority": self.result_authority,
            "result_digest": self.result_digest,
            "result_kind": self.result_kind,
        }


@dataclass(frozen=True, slots=True)
class ReplayLineage:
    """Execution and evidence-replay receipt identities."""

    execution_receipt_id: str
    execution_receipt_digest: str
    replay_receipt_id: str
    replay_receipt_digest: str
    record_kind: str
    disposition: str
    replay_claimed: bool
    match_digest: str
    launch_id: str
    tool_id: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "disposition": self.disposition,
            "execution_receipt_digest": self.execution_receipt_digest,
            "execution_receipt_id": self.execution_receipt_id,
            "launch_id": self.launch_id,
            "match_digest": self.match_digest,
            "record_kind": self.record_kind,
            "replay_claimed": self.replay_claimed,
            "replay_receipt_digest": self.replay_receipt_digest,
            "replay_receipt_id": self.replay_receipt_id,
            "tool_id": self.tool_id,
        }


@dataclass(frozen=True, slots=True)
class AuthorityStage:
    """One stage in the ordered authority lineage chain."""

    stage: str
    identity: str
    digest: str
    authority_ceiling: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority_ceiling": self.authority_ceiling,
            "digest": self.digest,
            "identity": self.identity,
            "stage": self.stage,
        }


@dataclass(frozen=True, slots=True)
class AuthorityLineage:
    """Ordered authority chain from origin through replay."""

    stages: tuple[AuthorityStage, ...]
    terminal_authority: str
    never_upgrades: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "never_upgrades": self.never_upgrades,
            "stages": [item.to_dict() for item in self.stages],
            "terminal_authority": self.terminal_authority,
        }


@dataclass(frozen=True, slots=True)
class ObligationLineageBundle:
    """Complete end-to-end lineage for one admitted intent route."""

    obligation_kind: IntentRouteKind | str
    typed_origin: TypedOriginLineage
    semantics: SemanticsLineage
    translation: TranslationLineage
    request: RequestLineage
    result: ResultLineage
    replay: ReplayLineage
    authority_lineage: AuthorityLineage
    domain_slice: DomainLogicSliceV2
    obligation: LogicObligationV2
    backend_request: BackendRequestV2
    compiled: CompiledLogicArtifact
    parsed: ParsedTargetArtifact
    execution: ProviderExecutionReceiptV2
    replay_receipt: EvidenceReplayReceipt
    expression: TypedExpression
    document: SourceDocument
    content_digest: str = ""
    schema_version: str = OBLIGATION_LINEAGE_SCHEMA
    notes: str = ""

    interface: ClassVar[str] = INTENT_LOGIC_SLICE_INTERFACE

    def __post_init__(self) -> None:
        if not isinstance(self.obligation_kind, IntentRouteKind):
            object.__setattr__(
                self,
                "obligation_kind",
                IntentRouteKind(self.obligation_kind),
            )
        if self.schema_version != OBLIGATION_LINEAGE_SCHEMA:
            raise ObligationLineageError(
                f"unsupported obligation lineage schema {self.schema_version!r}"
            )
        missing = [
            stage
            for stage in LINEAGE_STAGES
            if getattr(self, stage if stage != "typed_origin" else "typed_origin")
            is None
        ]
        if missing:
            raise ObligationLineageError(
                f"obligation lineage missing stages: {', '.join(missing)}"
            )
        content = content_sha256(canonical_json_bytes(self._identity_payload()))
        if self.content_digest:
            if self.content_digest != content:
                raise ObligationLineageError(
                    "content_digest does not match obligation lineage payload"
                )
            object.__setattr__(self, "content_digest", self.content_digest)
        else:
            object.__setattr__(self, "content_digest", content)

    def _identity_payload(self) -> dict[str, Any]:
        return {
            "authority_lineage": self.authority_lineage.to_dict(),
            "interface": self.interface,
            "notes": self.notes,
            "obligation_kind": self.obligation_kind.value,
            "replay": self.replay.to_dict(),
            "request": self.request.to_dict(),
            "result": self.result.to_dict(),
            "schema_version": self.schema_version,
            "semantics": self.semantics.to_dict(),
            "translation": self.translation.to_dict(),
            "typed_origin": self.typed_origin.to_dict(),
        }

    def require_complete_lineage(self) -> "ObligationLineageBundle":
        """Fail closed when any required lineage stage is empty or unbound."""

        stages = {
            "typed_origin": self.typed_origin,
            "semantics": self.semantics,
            "translation": self.translation,
            "request": self.request,
            "result": self.result,
            "replay": self.replay,
            "authority_lineage": self.authority_lineage,
        }
        for name, value in stages.items():
            if value is None:
                raise ObligationLineageError(f"missing lineage stage {name!r}")
        if not self.typed_origin.source_digest or not self.typed_origin.expression_digest:
            raise ObligationLineageError(
                "typed origin requires source_digest and expression_digest"
            )
        if self.typed_origin.source_range is None:
            raise ObligationLineageError(
                "typed origin requires source_range for source-span-to-result lineage"
            )
        if not self.translation.edge_id or not self.translation.content_id:
            raise ObligationLineageError(
                "translation lineage requires edge_id and content_id"
            )
        if not self.request.request_digest or not self.request.obligation_digest:
            raise ObligationLineageError(
                "request lineage requires request and obligation digests"
            )
        if not self.result.parsed_artifact_digest:
            raise ObligationLineageError(
                "result lineage requires parsed artifact digest"
            )
        if not self.replay.replay_receipt_digest:
            raise ObligationLineageError(
                "replay lineage requires replay receipt digest"
            )
        if len(self.authority_lineage.stages) < len(LINEAGE_STAGES):
            raise ObligationLineageError(
                "authority lineage must cover every required stage"
            )
        stage_names = tuple(item.stage for item in self.authority_lineage.stages)
        for required in LINEAGE_STAGES:
            if required not in stage_names:
                raise ObligationLineageError(
                    f"authority lineage missing stage {required!r}"
                )
        if self.backend_request.source_digest != self.typed_origin.source_digest:
            raise ObligationLineageError(
                "backend request source_digest diverged from typed origin"
            )
        if self.backend_request.expression_digest != self.typed_origin.expression_digest:
            raise ObligationLineageError(
                "backend request expression_digest diverged from typed origin"
            )
        if self.execution.request_digest != self.backend_request.content_digest:
            raise ObligationLineageError(
                "execution receipt request_digest diverged from backend request"
            )
        if self.replay_receipt.execution_receipt_digest != self.execution.content_digest:
            raise ObligationLineageError(
                "replay receipt is not bound to the execution receipt"
            )
        assumptions = self.semantics.assumptions
        for axis in ASSUMPTION_CATEGORIES:
            if not hasattr(assumptions, axis):
                raise ObligationLineageError(
                    f"semantics missing explicit assumption axis {axis!r}"
                )
        # Acceptance: safety/liveness remain properties; VC remains a view role.
        kind = self.obligation_kind.value
        if kind in PROPERTY_KIND_ROUTE_KINDS:
            if not self.semantics.is_property_kind:
                raise ObligationLineageError(
                    f"{kind!r} must remain a property kind on the slice"
                )
            if self.semantics.is_semantic_family:
                raise ObligationLineageError(
                    f"{kind!r} must not be admitted as a semantic family"
                )
            if self.semantics.property != kind:
                raise ObligationLineageError(
                    f"property route {kind!r} property mismatch"
                )
        if kind in VIEW_ROLE_ROUTE_KINDS:
            if not self.semantics.is_view_role:
                raise ObligationLineageError(
                    f"{kind!r} must remain a view role on the slice"
                )
            if self.semantics.is_semantic_family:
                raise ObligationLineageError(
                    f"{kind!r} must not be admitted as a semantic family"
                )
            if self.semantics.view != "verification_condition":
                raise ObligationLineageError(
                    "verification_condition view role requires matching view"
                )
            if self.semantics.family in NEVER_FAMILY_OPERATION_ROLES:
                raise ObligationLineageError(
                    "verification_condition must not use a view-role label as family"
                )
        # Advisor confidence cannot establish intent correctness.
        advisor_ids = assumptions.advisor_scope
        if not any(
            "confidence_not_correctness" in item or "candidate_only" in item
            for item in advisor_ids
        ):
            raise ObligationLineageError(
                "advisor_scope must declare that confidence cannot establish "
                "intent correctness"
            )
        return self

    def to_dict(self) -> dict[str, Any]:
        payload = self._identity_payload()
        payload["content_digest"] = self.content_digest
        payload["domain_slice_id"] = self.domain_slice.slice_id
        payload["expression_id"] = self.expression.expression_id
        payload["request_id"] = self.backend_request.request_id
        return payload


@dataclass(frozen=True, slots=True)
class IntentLogicSlice:
    """Compose admitted Intent IR routes end to end.

    Interface: ``IntentLogicSlice@2``.
    """

    INTERFACE: ClassVar[str] = INTENT_LOGIC_SLICE_INTERFACE
    VERSION: ClassVar[str] = INTENT_LOGIC_SLICE_VERSION
    SCHEMA_VERSION: ClassVar[str] = INTENT_LOGIC_SLICE_SCHEMA

    routes: Mapping[IntentRouteKind, ObligationRouteDescriptor] = field(
        default_factory=default_obligation_routes
    )
    translation_graph: LogicTranslationGraph | None = None
    bounds: RequestBounds | None = None
    formalization_compiler: IntentFormalizationCompiler | None = None

    def __post_init__(self) -> None:
        routes = dict(self.routes)
        expected = set(SUPPORTED_ROUTE_KINDS)
        known = set(routes)
        if known != expected:
            missing = sorted(item.value for item in expected - known)
            extra = sorted(
                item.value if isinstance(item, IntentRouteKind) else str(item)
                for item in known - expected
            )
            raise IntentSliceError(
                f"route table must cover every admitted intent route; "
                f"missing={missing} extra={extra}"
            )
        object.__setattr__(self, "routes", MappingProxyType(routes))
        if self.bounds is None:
            object.__setattr__(self, "bounds", RequestBounds.default())
        if self.formalization_compiler is None:
            object.__setattr__(
                self, "formalization_compiler", IntentFormalizationCompiler()
            )

    @property
    def interface(self) -> str:
        return self.INTERFACE

    @property
    def domain_id(self) -> str:
        return DOMAIN_ID

    def supported_obligation_kinds(self) -> tuple[str, ...]:
        return tuple(item.value for item in SUPPORTED_ROUTE_KINDS)

    def supported_route_kinds(self) -> tuple[str, ...]:
        return self.supported_obligation_kinds()

    def deferred_route_kinds(self) -> tuple[str, ...]:
        return tuple(sorted(DEFERRED_ROUTE_KINDS))

    def evidence_subset(self) -> tuple[str, ...]:
        return EVIDENCE_SUBSET

    def route_for(
        self, kind: IntentRouteKind | str
    ) -> ObligationRouteDescriptor:
        resolved = self._coerce_kind(kind)
        try:
            return self.routes[resolved]
        except KeyError as error:
            raise UnsupportedRouteError(
                f"unsupported intent route kind {resolved.value!r}"
            ) from error

    def connect_obligation(
        self,
        kind: IntentRouteKind | str,
        *,
        source_text: str | None = None,
    ) -> ObligationLineageBundle:
        """Connect one admitted route through the full lineage chain."""

        resolved = self._coerce_kind(kind)
        if resolved.value in DEFERRED_ROUTE_KINDS:
            raise UnsupportedRouteError(
                f"route {resolved.value!r} is deferred/unsupported for "
                "executable IntentLogicSlice@2"
            )
        route = self.route_for(resolved)
        self._assert_namespace_invariants(route)

        # Cross-check formalization compiler admission for the intent view.
        intent_view = route.intent_view_name or route.view_name
        intent_route = resolve_intent_route(intent_view)
        if intent_route.is_admitted is False and not route.is_view_role:
            raise UnsupportedRouteError(
                f"intent formalization route {intent_view!r} is not admitted"
            )
        if route.is_property_kind:
            if not intent_route.is_property_kind:
                raise IntentSliceError(
                    f"property route {resolved.value!r} must resolve as a "
                    "property kind in the formalization compiler"
                )
            if intent_route.property_id != route.property_name:
                raise IntentSliceError(
                    f"property route {resolved.value!r} property_id mismatch"
                )
        if route.is_view_role:
            if not intent_route.is_operation_role:
                raise IntentSliceError(
                    f"view-role route {resolved.value!r} must resolve as a "
                    "view role in the formalization compiler"
                )
            if intent_route.view_role_id != "verification_condition":
                raise IntentSliceError(
                    f"view-role route {resolved.value!r} view_role_id mismatch"
                )
            if intent_route.family_id:
                raise IntentSliceError(
                    "verification_condition formalization route must not set family_id"
                )

        text = source_text or self._default_source_text(route)
        document = SourceDocument.from_text(
            f"doc:intent:{resolved.value}",
            text,
            encoding="utf-8",
        )
        expression = self._build_expression(route, document)
        source_range = SourceRange(start=0, end=document.byte_length)
        domain_slice = DomainLogicSliceV2.from_typed_expression(
            expression,
            slice_id=f"slice:intent:{resolved.value}",
            domain=DOMAIN_ID,
            document_id=document.document_id,
            source_digest=document.content_digest,
            property=property_id(route.property_name),
            view=view_id(route.view_name),
            notation=notation_id(route.notation_name),
            source_range=source_range,
            features=route.features,
            assumption_ids=route.assumption_ids,
            metadata={
                "obligation_kind": resolved.value,
                "intent_route_id": route.intent_route_id or intent_route.route_id,
                "route_namespace": route.route_namespace.value,
                "is_property_kind": route.is_property_kind,
                "is_view_role": route.is_view_role,
                "slice_interface": self.INTERFACE,
            },
        )
        domain_slice.require_admitted()
        domain_slice.validate_against(document=document, expression=expression)

        translation = self._resolve_translation(route)
        bounds = self.bounds if self.bounds is not None else RequestBounds.default()
        obligation = LogicObligationV2.from_slice(
            domain_slice,
            obligation_id=f"obl:intent:{resolved.value}",
            statement=route.statement,
            encoding=encoding_id(route.encoding_name),
            evidence_kind=evidence_id(route.evidence_name),
            bounds=bounds,
            authority_ceiling=route.authority_ceiling,
            metadata={
                "obligation_kind": resolved.value,
                "translation_edge_id": route.translation_edge_id,
                "route_namespace": route.route_namespace.value,
            },
        )
        request = BackendRequestV2.from_obligation(
            obligation,
            request_id=f"req:intent:{resolved.value}",
            requested_provider=provider_id(route.provider_name),
            metadata={
                "obligation_kind": resolved.value,
                "hermetic": True,
            },
        )
        source_map = SourceMap(
            map_id=f"map:intent:{resolved.value}",
            document_id=document.document_id,
            entries=(
                SourceMapEntry(
                    entry_id=f"map:entry:intent:{resolved.value}",
                    range=source_range,
                    role="obligation",
                ),
            ),
        )
        compiled = admit_compiled_target(
            request,
            artifact_id=f"compiled:intent:{resolved.value}",
            compiler_id=route.compiler_id,
            target_text=route.target_text,
            source_map=source_map,
            assumption_ids=route.assumption_ids,
            loss_ids=self._loss_ids_for(route),
            toolchain_id=f"toolchain:hermetic:{route.provider_name}",
            metadata={"hermetic_fixture": True, "obligation_kind": resolved.value},
        )
        evidence_digest = content_sha256(
            canonical_json_bytes(
                {
                    "kind": resolved.value,
                    "output": route.result_output,
                    "request_digest": request.content_digest,
                }
            )
        )
        parsed = admit_parsed_result(
            compiled,
            artifact_id=f"parsed:intent:{resolved.value}",
            provider=provider_id(route.provider_name),
            result_kind=route.result_kind,
            output_text=route.result_output,
            decoded_evidence_digest=evidence_digest,
            evidence_kind=evidence_id(route.evidence_name),
            metadata={"hermetic_fixture": True},
        )
        execution = ProviderExecutionReceiptV2.from_parsed_target(
            parsed,
            receipt_id=f"exec:intent:{resolved.value}",
            launch_id=f"launch:hermetic:{route.provider_name}:{resolved.value}",
            tool_id=f"tool:hermetic:{route.provider_name}",
            bounds=bounds,
            record_kind=ExecutionRecordKind.HERMETIC_FIXTURE,
            execution_claimed=True,
            outcome=ExecutionOutcome.SUCCEEDED,
            exit_code=0,
            duration_ms=1,
            toolchain_id=f"toolchain:hermetic:{route.provider_name}",
            metadata={"hermetic_fixture": True},
        )
        match_digest = content_sha256(
            canonical_json_bytes(
                {
                    "execution_digest": execution.content_digest,
                    "output_digest": parsed.output_digest,
                    "result_digest": parsed.result_digest,
                }
            )
        )
        replay_receipt = EvidenceReplayReceipt.from_execution(
            execution,
            receipt_id=f"replay:intent:{resolved.value}",
            disposition=ReplayDisposition.REPLAYED,
            replay_claimed=True,
            match_digest=match_digest,
            decoded_evidence_digest=parsed.decoded_evidence_digest,
            reason="hermetic fixture replay matched execution identities",
            metadata={"hermetic_fixture": True},
        )

        typed_origin = TypedOriginLineage(
            document_id=document.document_id,
            source_digest=document.content_digest,
            expression_id=expression.expression_id,
            expression_digest=expression.content_digest,
            domain_slice_id=domain_slice.slice_id,
            domain_slice_digest=domain_slice.content_digest,
            route_kind=route.kind.value,
            source_range=source_range,
        )
        semantics = SemanticsLineage(
            family=_identity_value(domain_slice.family),
            profile=_identity_value(domain_slice.profile),
            property=_identity_value(domain_slice.property),
            view=_identity_value(domain_slice.view),
            notation=_identity_value(domain_slice.notation),
            features=tuple(domain_slice.features),
            assumption_ids=tuple(domain_slice.assumption_ids),
            statement=route.statement,
            assumptions=route.assumptions,
            route_namespace=route.route_namespace.value,
            is_property_kind=route.is_property_kind,
            is_view_role=route.is_view_role,
            is_semantic_family=route.is_semantic_family,
            intent_route_id=route.intent_route_id or intent_route.route_id,
            intent_view_name=intent_view,
        )
        request_lineage = RequestLineage(
            obligation_id=obligation.obligation_id,
            obligation_digest=obligation.content_digest,
            request_id=request.request_id,
            request_digest=request.content_digest,
            encoding=_identity_value(request.encoding),
            evidence_kind=_identity_value(request.evidence_kind),
            provider=route.provider_name,
            authority_ceiling=route.authority_ceiling.value,
            bounds={
                "timeout_ms": bounds.timeout_ms,
                "max_steps": bounds.max_steps,
                "max_memory_bytes": bounds.max_memory_bytes,
                "max_output_bytes": bounds.max_output_bytes,
            },
        )
        result_lineage = ResultLineage(
            compiled_artifact_id=compiled.artifact_id,
            compiled_artifact_digest=compiled.content_digest,
            parsed_artifact_id=parsed.artifact_id,
            parsed_artifact_digest=parsed.content_digest,
            result_kind=route.result_kind,
            result_authority=route.result_authority.value,
            output_digest=parsed.output_digest,
            result_digest=parsed.result_digest,
            decoded_evidence_digest=parsed.decoded_evidence_digest,
        )
        replay_lineage = ReplayLineage(
            execution_receipt_id=execution.receipt_id,
            execution_receipt_digest=execution.content_digest,
            replay_receipt_id=replay_receipt.receipt_id,
            replay_receipt_digest=replay_receipt.content_digest,
            record_kind=ExecutionRecordKind.HERMETIC_FIXTURE.value,
            disposition=ReplayDisposition.REPLAYED.value,
            replay_claimed=True,
            match_digest=match_digest,
            launch_id=execution.launch_id,
            tool_id=execution.tool_id,
        )
        translation_digest = (
            translation.content_id
            if _is_sha256_hex(translation.content_id)
            else content_sha256(
                translation.content_id.encode("utf-8", errors="surrogatepass")
            )
        )
        authority = AuthorityLineage(
            stages=(
                AuthorityStage(
                    "typed_origin",
                    domain_slice.slice_id,
                    domain_slice.content_digest,
                    route.authority_ceiling.value,
                ),
                AuthorityStage(
                    "semantics",
                    f"semantics:{resolved.value}",
                    content_sha256(canonical_json_bytes(semantics.to_dict())),
                    route.authority_ceiling.value,
                ),
                AuthorityStage(
                    "translation",
                    translation.edge_id,
                    translation_digest,
                    translation.authority_ceiling,
                ),
                AuthorityStage(
                    "request",
                    request.request_id,
                    request.content_digest,
                    route.authority_ceiling.value,
                ),
                AuthorityStage(
                    "result",
                    parsed.artifact_id,
                    parsed.content_digest,
                    route.authority_ceiling.value,
                ),
                AuthorityStage(
                    "replay",
                    replay_receipt.receipt_id,
                    replay_receipt.content_digest,
                    route.authority_ceiling.value,
                ),
                AuthorityStage(
                    "authority_lineage",
                    f"authority:{resolved.value}",
                    content_sha256(
                        canonical_json_bytes(
                            {
                                "kind": resolved.value,
                                "terminal": route.authority_ceiling.value,
                            }
                        )
                    ),
                    route.authority_ceiling.value,
                ),
            ),
            terminal_authority=route.authority_ceiling.value,
            never_upgrades=True,
        )

        bundle = ObligationLineageBundle(
            obligation_kind=resolved,
            typed_origin=typed_origin,
            semantics=semantics,
            translation=translation,
            request=request_lineage,
            result=result_lineage,
            replay=replay_lineage,
            authority_lineage=authority,
            domain_slice=domain_slice,
            obligation=obligation,
            backend_request=request,
            compiled=compiled,
            parsed=parsed,
            execution=execution,
            replay_receipt=replay_receipt,
            expression=expression,
            document=document,
            notes=route.notes,
        )
        return bundle.require_complete_lineage()

    def connect_route(
        self,
        kind: IntentRouteKind | str,
        *,
        source_text: str | None = None,
    ) -> ObligationLineageBundle:
        """Alias for :meth:`connect_obligation` (route-oriented naming)."""

        return self.connect_obligation(kind, source_text=source_text)

    def connect_all(
        self,
        kinds: Sequence[IntentRouteKind | str] | None = None,
    ) -> tuple[ObligationLineageBundle, ...]:
        """Connect every admitted route (or an explicit subset)."""

        if kinds is None:
            selected = SUPPORTED_ROUTE_KINDS
        else:
            selected = tuple(self._coerce_kind(item) for item in kinds)
        return tuple(self.connect_obligation(kind) for kind in selected)

    def validate_all(
        self,
        bundles: Sequence[ObligationLineageBundle] | None = None,
    ) -> Mapping[str, str]:
        """Validate complete lineage for each admitted route.

        Returns a mapping of route kind → content digest.
        """

        items = bundles if bundles is not None else self.connect_all()
        seen: set[str] = set()
        digests: dict[str, str] = {}
        for bundle in items:
            complete = bundle.require_complete_lineage()
            kind = complete.obligation_kind.value
            if kind in seen:
                raise ObligationLineageError(
                    f"duplicate route kind in validation set: {kind}"
                )
            seen.add(kind)
            digests[kind] = complete.content_digest
        missing = [
            kind.value
            for kind in SUPPORTED_ROUTE_KINDS
            if kind.value not in digests
        ]
        if bundles is None and missing:
            raise ObligationLineageError(
                f"validation set missing admitted routes: {', '.join(missing)}"
            )
        return MappingProxyType(digests)

    def reject_advisor_confidence_as_correctness(
        self,
        *,
        confidence: float = 1.0,
        claimed_correct: bool = True,
        source_kind: str = "advisor",
    ) -> None:
        """Fail closed when advisor confidence claims intent correctness.

        Advisor output is always candidate-scoped.  A high confidence score,
        even 1.0, cannot establish that an intent formula is correct.
        """

        if not claimed_correct:
            return
        candidate = classify_formula_candidate(
            {
                "formula_id": "f:advisor:confidence",
                "source_kind": source_kind,
                "confidence": confidence,
                "verified": True,  # attempted promotion
                "parsed": False,
                "typechecked": False,
            }
        )
        if candidate.may_claim_verified or candidate.status is FormulaStatus.VERIFIED:
            raise AdvisorConfidenceAsCorrectnessError(
                "advisor confidence cannot establish intent correctness"
            )
        if candidate.is_candidate is False:
            raise AdvisorConfidenceAsCorrectnessError(
                "advisor-derived formulas must remain candidates without "
                "deterministic parse/typecheck/verify receipts"
            )
        # Also reject tool authority from confidence alone.
        try:
            reject_tool_authority_from_confidence(
                tool_id="advisor_tool",
                confidence=confidence,
            )
        except ToolAuthorityFromConfidenceError as error:
            raise AdvisorConfidenceAsCorrectnessError(str(error)) from error
        raise AdvisorConfidenceAsCorrectnessError(
            f"advisor confidence={confidence} cannot establish intent correctness"
        )

    def reject_property_as_family(self, label: str) -> None:
        """Fail closed when safety/liveness are offered as families."""

        reject_property_as_family(label)

    def reject_view_role_as_family(self, label: str) -> None:
        """Fail closed when VC / other view roles are offered as families."""

        reject_operation_role_as_family(label)

    def to_dict(self) -> dict[str, Any]:
        return {
            "advisor_confidence_establishes_correctness": False,
            "assumption_categories": list(ASSUMPTION_CATEGORIES),
            "deferred_route_kinds": list(self.deferred_route_kinds()),
            "domain_id": self.domain_id,
            "evidence_subset": list(self.evidence_subset()),
            "interface": self.INTERFACE,
            "property_kind_routes": sorted(PROPERTY_KIND_ROUTE_KINDS),
            "schema_version": self.SCHEMA_VERSION,
            "supported_route_kinds": list(self.supported_route_kinds()),
            "version": self.VERSION,
            "view_role_routes": sorted(VIEW_ROLE_ROUTE_KINDS),
            "weakens_to_free_form": False,
        }

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _coerce_kind(self, kind: IntentRouteKind | str) -> IntentRouteKind:
        if isinstance(kind, IntentRouteKind):
            return kind
        token = str(kind).strip().lower().replace("-", "_").replace(" ", "_")
        aliases = {
            "facts": IntentRouteKind.INTENT,
            "typed_facts": IntentRouteKind.INTENT,
            "skill_effects": IntentRouteKind.SKILL,
            "action_hoare": IntentRouteKind.SKILL,
            "skill_prompt": IntentRouteKind.PROMPT,
            "prompt_derived": IntentRouteKind.PROMPT,
            "skill_goals": IntentRouteKind.GOAL,
            "goals": IntentRouteKind.GOAL,
            "guards": IntentRouteKind.GUARD,
            "guards_effects": IntentRouteKind.GUARD,
            "effects": IntentRouteKind.GUARD,
            "workflows": IntentRouteKind.WORKFLOW,
            "workflow_temporal": IntentRouteKind.WORKFLOW,
            "tool_permissions": IntentRouteKind.AUTHORIZATION,
            "tool_permission": IntentRouteKind.AUTHORIZATION,
            "tool_authorization": IntentRouteKind.AUTHORIZATION,
            "norms": IntentRouteKind.POLICY,
            "deontic": IntentRouteKind.POLICY,
            "modal_policy": IntentRouteKind.POLICY,
            "vc": IntentRouteKind.VERIFICATION_CONDITION,
            "verification": IntentRouteKind.VERIFICATION_CONDITION,
            "obligation": IntentRouteKind.VERIFICATION_CONDITION,
        }
        if token in DEFERRED_ROUTE_KINDS:
            raise UnsupportedRouteError(
                f"route {token!r} is deferred/unsupported for "
                "executable IntentLogicSlice@2"
            )
        if token in aliases:
            return aliases[token]
        try:
            return IntentRouteKind(token)
        except ValueError as error:
            raise UnsupportedRouteError(
                f"unsupported intent route kind {token!r}; supported="
                f"{list(self.supported_route_kinds())}"
            ) from error

    def _assert_namespace_invariants(
        self, route: ObligationRouteDescriptor
    ) -> None:
        if route.is_property_kind:
            if route.property_name in NEVER_FAMILY_PROPERTY_KINDS:
                # Expected — property kinds stay properties.
                pass
            if is_never_family_property(route.kind.value) is False:
                raise IntentSliceError(
                    f"property route {route.kind.value!r} missing from "
                    "NEVER_FAMILY_PROPERTY_KINDS"
                )
            if route.family_id in NEVER_FAMILY_PROPERTY_KINDS:
                raise PropertyAsFamilyError(route.family_id)
        if route.is_view_role:
            if is_never_family_label(route.view_name) is False:
                raise IntentSliceError(
                    f"view-role route {route.kind.value!r} missing from "
                    "NEVER_FAMILY_OPERATION_ROLES"
                )
            if route.family_id in NEVER_FAMILY_OPERATION_ROLES:
                raise OperationRoleAsFamilyError(route.family_id)

    def _default_source_text(self, route: ObligationRouteDescriptor) -> str:
        assumptions = route.assumptions.to_dict()
        return (
            f"# intent_ir route: {route.kind.value}\n"
            f"# family: {route.family_id} profile: {route.profile_id}\n"
            f"# namespace: {route.route_namespace.value}\n"
            f"# statement: {route.statement}\n"
            f"# source_grounding: {','.join(assumptions['source_grounding']) or 'n/a'}\n"
            f"# tool_authority: {','.join(assumptions['tool_authority']) or 'n/a'}\n"
            f"# bound: {','.join(assumptions['bound']) or 'n/a'}\n"
            f"# policy_authority: {','.join(assumptions['policy_authority']) or 'n/a'}\n"
            f"# advisor_scope: {','.join(assumptions['advisor_scope']) or 'n/a'}\n"
            f"route {route.kind.value} {{\n"
            f"  property = {route.property_name};\n"
            f"  view = {route.view_name};\n"
            f"  edge = {route.translation_edge_id};\n"
            f"}}\n"
        )

    def _build_expression(
        self,
        route: ObligationRouteDescriptor,
        document: SourceDocument,
    ) -> TypedExpression:
        """Build a typed-expression origin bound to the intent route namespaces."""

        signature = LogicSignature(
            signature_id=f"sig:intent:slice:{route.kind.value}",
            family=route.family_id,
            profile=route.profile_id,
            sorts=(),
            symbols=(),
            features=route.features,
            metadata={
                "domain": DOMAIN_ID,
                "kind": route.kind.value,
                "route_namespace": route.route_namespace.value,
                "slice": self.INTERFACE,
            },
        )
        payload_schema = "intent_ir.slice_expression/v2"
        payload = {
            "assumptions": route.assumptions.to_dict(),
            "domain": DOMAIN_ID,
            "is_property_kind": route.is_property_kind,
            "is_view_role": route.is_view_role,
            "kind": route.kind.value,
            "obligation_kind": route.kind.value,
            "route_namespace": route.route_namespace.value,
            "schema_version": payload_schema,
            "intent_route_id": route.intent_route_id,
            "slice_interface": self.INTERFACE,
            "source_digest": document.content_digest,
            "source_document_id": document.document_id,
            "statement": route.statement,
            "translation_edge_id": route.translation_edge_id,
        }
        root = mk_extension(
            f"node:intent:slice:{route.kind.value}",
            family=route.family_id,
            profile=route.profile_id,
            features=route.features,
            payload_schema=payload_schema,
            payload=payload,
            children=(),
        )
        return TypedExpression(
            expression_id=f"expr:intent:slice:{route.kind.value}",
            root=root,
            signature=signature,
            family=route.family_id,
            profile=route.profile_id,
            range=SourceRange(start=0, end=document.byte_length),
            elaborate_on_init=False,
            metadata={
                "domain": DOMAIN_ID,
                "obligation_kind": route.kind.value,
                "route_namespace": route.route_namespace.value,
                "slice": self.INTERFACE,
            },
        )

    def _resolve_translation(
        self, route: ObligationRouteDescriptor
    ) -> TranslationLineage:
        edge_id = route.translation_edge_id
        family_key = route.translation_family
        edge = self._lookup_translation_edge(edge_id, family_key)
        contract = getattr(edge, "contract", None)
        if contract is None:
            raise ObligationLineageError(
                f"translation edge {edge_id!r} lacks a TranslationContract"
            )
        source_family = getattr(contract.source, "family_id", "") or ""
        target_family = getattr(contract.target, "family_id", "") or ""
        preservation = contract.preservation
        preservation_value = (
            preservation.value if hasattr(preservation, "value") else str(preservation)
        )
        authority = contract.authority_ceiling
        authority_value = (
            authority.value if hasattr(authority, "value") else str(authority)
        )
        content_id = (
            getattr(edge, "content_id", None)
            or getattr(edge, "edge_content_id", None)
            or getattr(contract, "contract_content_id", None)
            or getattr(contract, "content_id", None)
            or edge_id
        )
        if callable(content_id):
            content_id = content_id()
        compiler = route.compiler_id
        identities = getattr(contract, "identities", None)
        if identities is not None:
            compiler = (
                getattr(identities, "compiler_identity", None)
                or getattr(identities, "compiler_id", None)
                or compiler
            )
        return TranslationLineage(
            edge_id=edge_id,
            family_key=family_key,
            source_family_id=str(source_family),
            target_family_id=str(target_family),
            preservation=preservation_value,
            authority_ceiling=authority_value,
            compiler_id=str(compiler),
            content_id=str(content_id),
            description=str(getattr(contract, "description", "") or route.notes),
        )

    def _lookup_translation_edge(self, edge_id: str, family_key: str) -> Any:
        if family_key == "program":
            for edge in build_program_translation_edges():
                if edge.edge_id == edge_id:
                    return edge
        if family_key == "state_temporal":
            catalog = build_state_temporal_edges()
            for edge in catalog.edges:
                if edge.edge_id == edge_id:
                    return edge
        if family_key == "policy_modal":
            catalog = build_policy_modal_translation_edges()
            for edge in catalog.edges:
                if edge.edge_id == edge_id:
                    return edge
        graph = self.translation_graph
        if graph is None:
            try:
                graph = build_logic_translation_graph()
            except Exception:
                graph = None
        if graph is not None:
            contracts = getattr(graph, "contracts", ()) or ()
            if callable(contracts):
                contracts = contracts()
            for contract in contracts:
                contract_id = getattr(contract, "contract_id", None)
                if contract_id == edge_id:
                    return type(
                        "EdgeProxy",
                        (),
                        {
                            "edge_id": edge_id,
                            "contract": contract,
                            "content_id": getattr(
                                contract, "contract_content_id", edge_id
                            ),
                        },
                    )()
        raise ObligationLineageError(
            f"translation edge {edge_id!r} not found in family {family_key!r}"
        )

    def _loss_ids_for(self, route: ObligationRouteDescriptor) -> tuple[str, ...]:
        if route.kind is IntentRouteKind.WORKFLOW:
            return ("loss.bounded_trace",)
        if route.kind is IntentRouteKind.SAFETY:
            return ("loss.bounded_trace",)
        if route.kind is IntentRouteKind.LIVENESS:
            return ("loss.finite_trace", "loss.fairness_restriction")
        if route.kind is IntentRouteKind.GOAL:
            return ("loss.intention_reification",)
        if route.kind is IntentRouteKind.POLICY:
            return ("loss.deontic_reification",)
        if route.kind is IntentRouteKind.SKILL:
            return ("loss.frame_approximation",)
        if route.kind is IntentRouteKind.PROMPT:
            return ("loss.prompt_candidate_only",)
        if route.kind is IntentRouteKind.VERIFICATION_CONDITION:
            return ("loss.vc_view_role",)
        return ()


def _identity_value(identity: LogicIdentity | Mapping[str, Any] | str | Any) -> str:
    if isinstance(identity, LogicIdentity):
        return identity.value
    if isinstance(identity, Mapping):
        return str(identity.get("value") or identity.get("id") or "")
    if hasattr(identity, "value") and not isinstance(identity, str):
        return str(getattr(identity, "value"))
    return str(identity)


def _is_sha256_hex(value: str) -> bool:
    if not isinstance(value, str) or len(value) != 64:
        return False
    try:
        int(value, 16)
    except ValueError:
        return False
    return True


def connect_intent_route(
    kind: IntentRouteKind | str,
    *,
    source_text: str | None = None,
) -> ObligationLineageBundle:
    """Module-level helper for :meth:`IntentLogicSlice.connect_route`."""

    return IntentLogicSlice().connect_route(kind, source_text=source_text)


def connect_intent_obligation(
    kind: IntentRouteKind | str,
    *,
    source_text: str | None = None,
) -> ObligationLineageBundle:
    """Alias matching sibling domain helper naming."""

    return connect_intent_route(kind, source_text=source_text)


def connect_all_intent_routes() -> tuple[ObligationLineageBundle, ...]:
    """Connect every admitted Intent IR route end to end."""

    return IntentLogicSlice().connect_all()


def validate_intent_logic_slice() -> Mapping[str, str]:
    """Validate complete lineage for every admitted route."""

    return IntentLogicSlice().validate_all()


def reject_advisor_confidence_as_correctness(
    *,
    confidence: float = 1.0,
    claimed_correct: bool = True,
    source_kind: str = "advisor",
) -> None:
    """Module-level helper for advisor-confidence fail-closed checks."""

    IntentLogicSlice().reject_advisor_confidence_as_correctness(
        confidence=confidence,
        claimed_correct=claimed_correct,
        source_kind=source_kind,
    )


__all__ = [
    "ASSUMPTION_CATEGORIES",
    "DEFERRED_ROUTE_KINDS",
    "DOMAIN_ID",
    "EVIDENCE_SUBSET",
    "INTENT_LOGIC_SLICE_INTERFACE",
    "INTENT_LOGIC_SLICE_SCHEMA",
    "INTENT_LOGIC_SLICE_VERSION",
    "LINEAGE_STAGES",
    "OBLIGATION_LINEAGE_SCHEMA",
    "PROPERTY_KIND_ROUTE_KINDS",
    "SUPPORTED_ROUTE_KINDS",
    "VIEW_ROLE_ROUTE_KINDS",
    "AdvisorConfidenceAsCorrectnessError",
    "AuthorityLineage",
    "AuthorityStage",
    "ExplicitAssumptions",
    "IntentLogicSlice",
    "IntentRouteKind",
    "IntentRouteNamespace",
    "IntentSliceError",
    "ObligationLineageBundle",
    "ObligationLineageError",
    "ObligationRouteDescriptor",
    "ReplayLineage",
    "RequestLineage",
    "ResultLineage",
    "SemanticsLineage",
    "TranslationLineage",
    "TypedOriginLineage",
    "UnsupportedRouteError",
    "connect_all_intent_routes",
    "connect_intent_obligation",
    "connect_intent_route",
    "default_obligation_routes",
    "reject_advisor_confidence_as_correctness",
    "validate_intent_logic_slice",
]
