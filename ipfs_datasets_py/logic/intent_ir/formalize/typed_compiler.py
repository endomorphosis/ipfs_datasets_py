"""Migrate intent_ir skill-prompt views to canonical typed logic (LFP-036).

Interface: ``IntentFormalizationCompiler@2``

Skill, prompt, and MCP Intent IR views emit typed formalization routes onto
sealed family / profile / property / view-role namespaces:

* Typed facts, guards, effects → ``first_order``
* Skill goals / intentions (BDI) → ``intention_agency``
* Norms (permissions, obligations, prohibitions) → ``deontic``
* Dynamic / Hoare skill effects → ``program`` (profile ``dynamic_hoare``)
* Workflow control → ``temporal`` (profile ``workflow_temporal``)
* Tool / resource permissions → ``authorization``
* Safety / liveness → property kinds under ``temporal`` (never families)
* Verification conditions → view role ``verification_condition`` (never a family)

Authority rules (fail-closed):

* Prompt-derived formulas are candidates until deterministic parse, typecheck,
  and verification receipts exist.
* Tool authority never follows confidence alone — permissions require grounded
  authorization evidence independent of stated confidence scores.
* Safety and liveness remain property kinds; VC remains a view role.
* Routes alone never mint theorem authority.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, ClassVar, Final

from ipfs_datasets_py.logic.backends.results import ResultAuthority
from ipfs_datasets_py.logic.families.models import EvidenceAuthority, SupportLevel
from ipfs_datasets_py.logic.families.registry import (
    DEFAULT_REGISTRY,
    FOUNDATION_FAMILY_IDS,
)
from ipfs_datasets_py.logic.ir_core.claims import stable_digest


# ---------------------------------------------------------------------------
# Interface / schema identities
# ---------------------------------------------------------------------------

INTENT_FORMALIZATION_COMPILER_INTERFACE: Final = "IntentFormalizationCompiler@2"
INTENT_FORMALIZATION_COMPILER_VERSION: Final = "2.0.0"
INTENT_LOGIC_ROUTE_SCHEMA: Final = "intent-logic-route/v1"
INTENT_ROUTE_RECEIPT_SCHEMA: Final = "intent-logic-route-receipt/v1"
INTENT_PARSE_ELABORATE_SCHEMA: Final = "intent-parse-elaborate-receipt/v1"
INTENT_FORMULA_CANDIDATE_SCHEMA: Final = "intent-formula-candidate/v1"
INTENT_TOOL_AUTHORITY_SCHEMA: Final = "intent-tool-authority-receipt/v1"
INTENT_TYPED_COMPILER_MODULE_VERSION: Final = "1.0.0"

INTENT_IR_TYPED_COMPILER_PRODUCER_ID: Final = "intent-ir-typed-compiler"
INTENT_IR_TYPED_DOMAIN: Final = "intent"
INTENT_IR_DOMAIN_ID: Final = "intent_ir"

# Stable diagnostic codes.
CODE_UNKNOWN_VIEW: Final = "intent.unknown_view"
CODE_OPERATION_AS_FAMILY: Final = "intent.operation_role_as_family"
CODE_PROPERTY_AS_FAMILY: Final = "intent.property_as_family"
CODE_UNSUPPORTED: Final = "intent.unsupported"
CODE_PARSE_REQUIRED: Final = "intent.parse_typecheck_required"
CODE_PARSE_FAILED: Final = "intent.parse_typecheck_failed"
CODE_CANDIDATE_ONLY: Final = "intent.prompt_derived_candidate"
CODE_TOOL_CONFIDENCE: Final = "intent.tool_authority_not_from_confidence"
CODE_AUTHORITY_PROMOTION: Final = "intent.authority_promotion_rejected"
CODE_FREE_FORM_FAMILY: Final = "intent.free_form_family"
CODE_MALFORMED: Final = "intent.malformed_input"
CODE_ROUTE: Final = "intent.route_error"
CODE_LEGACY_ALIAS: Final = "intent.legacy_alias"

_ALL_CODES: Final[frozenset[str]] = frozenset(
    {
        CODE_UNKNOWN_VIEW,
        CODE_OPERATION_AS_FAMILY,
        CODE_PROPERTY_AS_FAMILY,
        CODE_UNSUPPORTED,
        CODE_PARSE_REQUIRED,
        CODE_PARSE_FAILED,
        CODE_CANDIDATE_ONLY,
        CODE_TOOL_CONFIDENCE,
        CODE_AUTHORITY_PROMOTION,
        CODE_FREE_FORM_FAMILY,
        CODE_MALFORMED,
        CODE_ROUTE,
        CODE_LEGACY_ALIAS,
    }
)

# Labels that must never be promoted to semantic families.
NEVER_FAMILY_OPERATION_ROLES: Final[frozenset[str]] = frozenset(
    {
        "verification_condition",
        "graph_projection",
        "proof_translation",
        "structural_round_trip",
        "round_trip",
        "decompiler",
        "external_provers",
        "prover_router",
        "prover",
    }
)

# Property kinds — not families (plan alias migration).
NEVER_FAMILY_PROPERTY_KINDS: Final[frozenset[str]] = frozenset(
    {
        "safety",
        "liveness",
        "safety_liveness",
        "invariant",
        "validity",
        "reachability",
    }
)

# Evidence-subset backends from LFP-036.
INTENT_EVIDENCE_BACKENDS: Final[tuple[str, ...]] = (
    "z3",
    "cvc5",
    "vampire",
    "eprover",
    "tla_tlc",
    "apalache",
    "datalog_secpal",
    "runtime_mtl",
    "lean",
    "rocq",
    "isabelle",
)

# Wave-4 / future families that must never be implied by intent routes.
FUTURE_UNSUPPORTED_FAMILY_CLAIMS: Final[frozenset[str]] = frozenset(
    {
        "probabilistic",
        "fuzzy_weighted",
        "fuzzy",
        "finite_field_constraint",
        "finite_field",
        "zk",
        "zkp",
        "zero_knowledge",
        "argumentation",
        "situation_calculus",
        "defeasible_logic",
        "nonmonotonic_logic",
        "description_logic",
        "dependent_type",
        "relevance_paraconsistent",
    }
)

# Source markers that force candidate-only status until parse/typecheck/verify.
PROMPT_DERIVED_SOURCE_KINDS: Final[frozenset[str]] = frozenset(
    {
        "prompt",
        "prompt_derived",
        "prompt_extraction",
        "nl_prompt",
        "skill_prompt",
        "llm_extracted",
        "natural_language",
        "free_text",
        "inferred",
        "candidate",
        "advisor",
    }
)

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class RouteNamespace(StrEnum):
    """Namespace role of an intent logic route target."""

    FAMILY = "family"
    PROFILE = "profile"
    PROPERTY = "property"
    VIEW_ROLE = "view_role"
    DECLARATION_ONLY = "declaration_only"


class RouteDisposition(StrEnum):
    """How an intent view is admitted into the typed matrix."""

    NATIVE = "native"
    TYPED = "typed"
    DECLARATION_ONLY = "declaration_only"
    UNSUPPORTED = "unsupported"
    BOUNDED = "bounded"
    ADVISORY = "advisory"
    OPERATION = "operation"
    PROPERTY = "property"


class ProofAuthorityRole(StrEnum):
    """What a route may claim about proof without verification receipts."""

    NONE = "none"
    CANDIDATE = "candidate"
    DECLARATION = "declaration"
    BOUNDED = "bounded"
    ADVISORY = "advisory"
    # Kernel/backend only — never assigned by the route catalog alone.
    OFFICIAL = "official"


class FormulaStatus(StrEnum):
    """Lifecycle status of a prompt/skill-derived formula."""

    CANDIDATE = "candidate"
    PARSED = "parsed"
    TYPECHECKED = "typechecked"
    VERIFIED = "verified"
    REJECTED = "rejected"


class ParseElaborateStage(StrEnum):
    """Stages of the mandatory parse → typecheck → verify pipeline."""

    ADMITTED = "admitted"
    PARSED = "parsed"
    TYPECHECKED = "typechecked"
    READY_TO_VERIFY = "ready_to_verify"
    VERIFIED = "verified"
    REJECTED = "rejected"


class AuthorityLane(StrEnum):
    """Closed authority lanes for intent formalization."""

    PROOF = "proof"
    MODEL = "model"
    MONITOR = "monitor"
    AUTHORIZATION = "authorization"
    CANDIDATE = "candidate"
    NONE = "none"


class ToolAuthorityBasis(StrEnum):
    """Closed bases that may grant tool/resource authority."""

    GROUNDED_PERMISSION = "grounded_permission"
    AUTHORIZATION_RECEIPT = "authorization_receipt"
    DECLARED_POLICY = "declared_policy"
    # Explicitly insufficient alone:
    CONFIDENCE_SCORE = "confidence_score"
    NONE = "none"


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class IntentTypedCompilerError(ValueError):
    """Raised when an intent typed route request is invalid."""

    def __init__(
        self,
        message: str,
        *,
        code: str = CODE_ROUTE,
        path: str = "",
    ) -> None:
        super().__init__(message)
        self.code = code if code in _ALL_CODES else CODE_ROUTE
        self.path = path


class OperationRoleAsFamilyError(IntentTypedCompilerError):
    """Raised when an operation/view role is offered as a semantic family."""

    def __init__(self, label: str, *, path: str = "logic_family") -> None:
        super().__init__(
            f"operation/view role {label!r} must never route as a semantic family",
            code=CODE_OPERATION_AS_FAMILY,
            path=path,
        )
        self.label = label


class PropertyAsFamilyError(IntentTypedCompilerError):
    """Raised when a property kind is offered as a semantic family."""

    def __init__(self, label: str, *, path: str = "logic_family") -> None:
        super().__init__(
            f"property kind {label!r} must never route as a semantic family",
            code=CODE_PROPERTY_AS_FAMILY,
            path=path,
        )
        self.label = label


class AuthorityPromotionError(IntentTypedCompilerError):
    """Raised when a route attempts to exceed its declared authority ceiling."""

    def __init__(self, message: str, *, path: str = "authority") -> None:
        super().__init__(message, code=CODE_AUTHORITY_PROMOTION, path=path)


class ParseTypecheckRequiredError(IntentTypedCompilerError):
    """Raised when verification is attempted without parse/typecheck receipts."""

    def __init__(self, message: str = "", *, path: str = "pipeline") -> None:
        super().__init__(
            message
            or (
                "prompt-derived formulas remain candidates until deterministic "
                "parsing, typechecking, and verification"
            ),
            code=CODE_PARSE_REQUIRED,
            path=path,
        )


class ToolAuthorityFromConfidenceError(IntentTypedCompilerError):
    """Raised when tool authority is claimed from confidence alone."""

    def __init__(self, message: str = "", *, path: str = "tool_authority") -> None:
        super().__init__(
            message
            or "tool authority never follows confidence alone",
            code=CODE_TOOL_CONFIDENCE,
            path=path,
        )


class FreeFormFamilyError(IntentTypedCompilerError):
    """Raised when free-form family labels are offered as typed inputs."""

    def __init__(self, label: str, *, path: str = "logic_family") -> None:
        super().__init__(
            f"free-form family label {label!r} is rejected; use a canonical family",
            code=CODE_FREE_FORM_FAMILY,
            path=path,
        )
        self.label = label


# ---------------------------------------------------------------------------
# Route catalog records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class IntentLogicRoute:
    """One typed intent view → canonical namespace route."""

    route_id: str
    view_id: str
    view_name: str
    namespace: RouteNamespace
    disposition: RouteDisposition
    family_id: str = ""
    profile_id: str = ""
    property_id: str = ""
    view_role_id: str = ""
    target_component: str = ""
    description: str = ""
    aliases: tuple[str, ...] = ()
    preservation_rules: tuple[str, ...] = ()
    backend_ids: tuple[str, ...] = ()
    authority_lane: AuthorityLane = AuthorityLane.CANDIDATE
    support_level: SupportLevel = SupportLevel.NATIVE
    evidence_authority: EvidenceAuthority = EvidenceAuthority.NONE
    proof_authority: ProofAuthorityRole = ProofAuthorityRole.NONE
    result_authority_ceiling: ResultAuthority = ResultAuthority.CANDIDATE
    requires_parse_typecheck: bool = True
    prompt_derived_is_candidate: bool = True
    schema_version: str = INTENT_LOGIC_ROUTE_SCHEMA

    def __post_init__(self) -> None:
        if not self.route_id or not _ID_RE.fullmatch(self.route_id):
            raise IntentTypedCompilerError(
                f"route_id must be a stable identifier; got {self.route_id!r}",
                code=CODE_MALFORMED,
                path="route_id",
            )
        if not self.view_id or not _ID_RE.fullmatch(self.view_id):
            raise IntentTypedCompilerError(
                f"view_id must be a stable identifier; got {self.view_id!r}",
                code=CODE_MALFORMED,
                path="view_id",
            )
        if not isinstance(self.namespace, RouteNamespace):
            object.__setattr__(
                self, "namespace", RouteNamespace(str(self.namespace))
            )
        if not isinstance(self.disposition, RouteDisposition):
            object.__setattr__(
                self, "disposition", RouteDisposition(str(self.disposition))
            )
        if not isinstance(self.authority_lane, AuthorityLane):
            object.__setattr__(
                self, "authority_lane", AuthorityLane(str(self.authority_lane))
            )
        if not isinstance(self.support_level, SupportLevel):
            object.__setattr__(
                self, "support_level", SupportLevel(str(self.support_level))
            )
        if not isinstance(self.evidence_authority, EvidenceAuthority):
            object.__setattr__(
                self,
                "evidence_authority",
                EvidenceAuthority(str(self.evidence_authority)),
            )
        if not isinstance(self.proof_authority, ProofAuthorityRole):
            object.__setattr__(
                self,
                "proof_authority",
                ProofAuthorityRole(str(self.proof_authority)),
            )
        if not isinstance(self.result_authority_ceiling, ResultAuthority):
            object.__setattr__(
                self,
                "result_authority_ceiling",
                ResultAuthority(str(self.result_authority_ceiling)),
            )
        self._validate_namespace_consistency()

    def _validate_namespace_consistency(self) -> None:
        if self.namespace is RouteNamespace.VIEW_ROLE:
            if not self.view_role_id:
                raise IntentTypedCompilerError(
                    f"view-role route {self.route_id!r} requires view_role_id",
                    code=CODE_MALFORMED,
                    path="view_role_id",
                )
            if self.family_id:
                raise IntentTypedCompilerError(
                    f"view-role route {self.route_id!r} must not set family_id "
                    f"(got {self.family_id!r}); operation roles are not families",
                    code=CODE_OPERATION_AS_FAMILY,
                    path="family_id",
                )
            if self.disposition is not RouteDisposition.OPERATION:
                raise IntentTypedCompilerError(
                    f"view-role route {self.route_id!r} must have operation disposition",
                    code=CODE_MALFORMED,
                    path="disposition",
                )
            if self.proof_authority is ProofAuthorityRole.OFFICIAL:
                raise IntentTypedCompilerError(
                    f"view-role route {self.route_id!r} cannot claim official proof",
                    code=CODE_AUTHORITY_PROMOTION,
                    path="proof_authority",
                )
            return

        if self.namespace is RouteNamespace.PROPERTY:
            if not self.property_id:
                raise IntentTypedCompilerError(
                    f"property route {self.route_id!r} requires property_id",
                    code=CODE_MALFORMED,
                    path="property_id",
                )
            if self.property_id in NEVER_FAMILY_OPERATION_ROLES:
                raise OperationRoleAsFamilyError(self.property_id)
            if self.property_id in FOUNDATION_FAMILY_IDS:
                raise PropertyAsFamilyError(self.property_id)
            if self.disposition not in {
                RouteDisposition.PROPERTY,
                RouteDisposition.TYPED,
                RouteDisposition.BOUNDED,
            }:
                raise IntentTypedCompilerError(
                    f"property route {self.route_id!r} has invalid disposition",
                    code=CODE_MALFORMED,
                    path="disposition",
                )
            if self.proof_authority is ProofAuthorityRole.OFFICIAL:
                raise IntentTypedCompilerError(
                    f"property route {self.route_id!r} cannot claim official proof",
                    code=CODE_AUTHORITY_PROMOTION,
                    path="proof_authority",
                )
            return

        if self.namespace is RouteNamespace.FAMILY:
            if not self.family_id:
                raise IntentTypedCompilerError(
                    f"family route {self.route_id!r} requires family_id",
                    code=CODE_MALFORMED,
                    path="family_id",
                )
            if self.family_id in NEVER_FAMILY_OPERATION_ROLES:
                raise OperationRoleAsFamilyError(self.family_id)
            if self.family_id in NEVER_FAMILY_PROPERTY_KINDS:
                raise PropertyAsFamilyError(self.family_id)
            if self.family_id not in DEFAULT_REGISTRY.families:
                raise FreeFormFamilyError(self.family_id)
            return

        if self.namespace is RouteNamespace.PROFILE:
            if not self.family_id or not self.profile_id:
                raise IntentTypedCompilerError(
                    f"profile route {self.route_id!r} requires family_id and profile_id",
                    code=CODE_MALFORMED,
                    path="profile_id",
                )
            if self.family_id in NEVER_FAMILY_OPERATION_ROLES:
                raise OperationRoleAsFamilyError(self.family_id)
            if self.family_id in NEVER_FAMILY_PROPERTY_KINDS:
                raise PropertyAsFamilyError(self.family_id)
            if self.family_id not in DEFAULT_REGISTRY.families:
                raise FreeFormFamilyError(self.family_id)
            return

        if self.namespace is RouteNamespace.DECLARATION_ONLY:
            if not self.family_id:
                raise IntentTypedCompilerError(
                    f"declaration-only route {self.route_id!r} requires family_id",
                    code=CODE_MALFORMED,
                    path="family_id",
                )
            if self.family_id in NEVER_FAMILY_OPERATION_ROLES:
                raise OperationRoleAsFamilyError(self.family_id)
            if self.family_id not in DEFAULT_REGISTRY.families:
                raise FreeFormFamilyError(self.family_id)
            if self.disposition not in {
                RouteDisposition.DECLARATION_ONLY,
                RouteDisposition.UNSUPPORTED,
            }:
                raise IntentTypedCompilerError(
                    f"declaration-only route {self.route_id!r} has invalid disposition",
                    code=CODE_MALFORMED,
                    path="disposition",
                )
            if self.proof_authority is ProofAuthorityRole.OFFICIAL:
                raise IntentTypedCompilerError(
                    f"declaration-only route {self.route_id!r} cannot claim official proof",
                    code=CODE_AUTHORITY_PROMOTION,
                    path="proof_authority",
                )

    @property
    def is_semantic_family(self) -> bool:
        return self.namespace in {
            RouteNamespace.FAMILY,
            RouteNamespace.PROFILE,
        } and self.disposition not in {
            RouteDisposition.DECLARATION_ONLY,
            RouteDisposition.UNSUPPORTED,
            RouteDisposition.OPERATION,
            RouteDisposition.PROPERTY,
        }

    @property
    def is_operation_role(self) -> bool:
        return self.namespace is RouteNamespace.VIEW_ROLE

    @property
    def is_property_kind(self) -> bool:
        return self.namespace is RouteNamespace.PROPERTY

    @property
    def is_declaration_only(self) -> bool:
        return self.disposition is RouteDisposition.DECLARATION_ONLY or (
            self.namespace is RouteNamespace.DECLARATION_ONLY
        )

    @property
    def is_admitted(self) -> bool:
        return self.disposition not in {
            RouteDisposition.UNSUPPORTED,
            RouteDisposition.DECLARATION_ONLY,
        } and self.support_level is not SupportLevel.UNSUPPORTED

    @property
    def may_emit_proof(self) -> bool:
        return self.proof_authority is ProofAuthorityRole.OFFICIAL

    def to_dict(self) -> dict[str, Any]:
        return {
            "aliases": list(self.aliases),
            "authority_lane": self.authority_lane.value,
            "backend_ids": list(self.backend_ids),
            "description": self.description,
            "disposition": self.disposition.value,
            "evidence_authority": self.evidence_authority.value,
            "family_id": self.family_id,
            "is_admitted": self.is_admitted,
            "is_operation_role": self.is_operation_role,
            "is_property_kind": self.is_property_kind,
            "is_semantic_family": self.is_semantic_family,
            "namespace": self.namespace.value,
            "preservation_rules": list(self.preservation_rules),
            "profile_id": self.profile_id,
            "prompt_derived_is_candidate": self.prompt_derived_is_candidate,
            "proof_authority": self.proof_authority.value,
            "property_id": self.property_id,
            "requires_parse_typecheck": self.requires_parse_typecheck,
            "result_authority_ceiling": self.result_authority_ceiling.value,
            "route_id": self.route_id,
            "schema_version": self.schema_version,
            "support_level": self.support_level.value,
            "target_component": self.target_component,
            "view_id": self.view_id,
            "view_name": self.view_name,
            "view_role_id": self.view_role_id,
        }


def _route(
    *,
    route_id: str,
    view_id: str,
    view_name: str,
    namespace: RouteNamespace,
    disposition: RouteDisposition,
    family_id: str = "",
    profile_id: str = "",
    property_id: str = "",
    view_role_id: str = "",
    target_component: str = "",
    description: str = "",
    aliases: tuple[str, ...] = (),
    preservation_rules: tuple[str, ...] = (),
    backend_ids: tuple[str, ...] = (),
    authority_lane: AuthorityLane = AuthorityLane.CANDIDATE,
    support_level: SupportLevel = SupportLevel.NATIVE,
    evidence_authority: EvidenceAuthority = EvidenceAuthority.NONE,
    proof_authority: ProofAuthorityRole = ProofAuthorityRole.NONE,
    result_authority_ceiling: ResultAuthority = ResultAuthority.CANDIDATE,
    requires_parse_typecheck: bool = True,
    prompt_derived_is_candidate: bool = True,
) -> IntentLogicRoute:
    return IntentLogicRoute(
        route_id=route_id,
        view_id=view_id,
        view_name=view_name,
        namespace=namespace,
        disposition=disposition,
        family_id=family_id,
        profile_id=profile_id,
        property_id=property_id,
        view_role_id=view_role_id,
        target_component=target_component,
        description=description,
        aliases=aliases,
        preservation_rules=preservation_rules,
        backend_ids=backend_ids,
        authority_lane=authority_lane,
        support_level=support_level,
        evidence_authority=evidence_authority,
        proof_authority=proof_authority,
        result_authority_ceiling=result_authority_ceiling,
        requires_parse_typecheck=requires_parse_typecheck,
        prompt_derived_is_candidate=prompt_derived_is_candidate,
    )


# Canonical intent skill-prompt view routes aligned with the capability matrix.
_INTENT_LOGIC_ROUTES: Final[tuple[IntentLogicRoute, ...]] = (
    # --- Typed facts / guards / effects ------------------------------------
    _route(
        route_id="intent-route/facts/v1",
        view_id="intent-ir-view/facts/v1",
        view_name="facts",
        namespace=RouteNamespace.FAMILY,
        disposition=RouteDisposition.TYPED,
        family_id="first_order",
        profile_id="default",
        target_component="intent.facts",
        description="Typed Intent entities, predicates, and action facts.",
        aliases=(
            "facts",
            "typed_facts",
            "typed_first_order",
            "first_order",
            "fol",
            "intent-ir-view/facts/v1",
        ),
        preservation_rules=(
            "predicate_signature",
            "entity_identity",
            "source_grounding",
        ),
        backend_ids=("z3", "cvc5", "vampire", "eprover"),
        authority_lane=AuthorityLane.PROOF,
        support_level=SupportLevel.NATIVE,
        evidence_authority=EvidenceAuthority.INDEPENDENTLY_CHECKABLE,
        proof_authority=ProofAuthorityRole.CANDIDATE,
        result_authority_ceiling=ResultAuthority.SATISFIABILITY,
    ),
    _route(
        route_id="intent-route/guards-effects/v1",
        view_id="intent-ir-view/guards-effects/v1",
        view_name="guards_effects",
        namespace=RouteNamespace.PROFILE,
        disposition=RouteDisposition.TYPED,
        family_id="first_order",
        profile_id="guards_effects",
        target_component="intent.guards_effects",
        description="Typed guards and effects as first-order predicates.",
        aliases=(
            "guards",
            "effects",
            "guards_effects",
            "guard",
            "effect",
            "intent-ir-view/guards-effects/v1",
        ),
        preservation_rules=(
            "guard_polarity",
            "effect_polarity",
            "predicate_signature",
            "source_grounding",
        ),
        backend_ids=("z3", "cvc5"),
        authority_lane=AuthorityLane.PROOF,
        support_level=SupportLevel.NATIVE,
        evidence_authority=EvidenceAuthority.INDEPENDENTLY_CHECKABLE,
        proof_authority=ProofAuthorityRole.CANDIDATE,
        result_authority_ceiling=ResultAuthority.SATISFIABILITY,
    ),
    # --- Skill goals / intentions (BDI) ------------------------------------
    _route(
        route_id="intent-route/skill-goals/v1",
        view_id="intent-ir-view/skill-goals/v1",
        view_name="skill_goals",
        namespace=RouteNamespace.PROFILE,
        disposition=RouteDisposition.TYPED,
        family_id="intention_agency",
        profile_id="skill_goals",
        target_component="intent.skill_goals",
        description="Skill goals under intention/agency (BDI) family.",
        aliases=(
            "skill_goals",
            "goals",
            "skill_goal",
            "intent-ir-view/skill-goals/v1",
        ),
        preservation_rules=(
            "goal_identity",
            "agent_identity",
            "intention_force",
            "source_grounding",
        ),
        backend_ids=("z3", "cvc5", "lean", "rocq", "isabelle"),
        authority_lane=AuthorityLane.PROOF,
        support_level=SupportLevel.NATIVE,
        evidence_authority=EvidenceAuthority.INDEPENDENTLY_CHECKABLE,
        proof_authority=ProofAuthorityRole.CANDIDATE,
        result_authority_ceiling=ResultAuthority.CANDIDATE,
    ),
    _route(
        route_id="intent-route/intentions/v1",
        view_id="intent-ir-view/intention-deontic/v1",
        view_name="intentions",
        namespace=RouteNamespace.FAMILY,
        disposition=RouteDisposition.TYPED,
        family_id="intention_agency",
        profile_id="default",
        target_component="intent.intentions",
        description="Intentions and agency modalities from Intent IR.",
        aliases=(
            "intentions",
            "intention",
            "bdi",
            "intention_agency",
            "agency",
            "intent-ir-view/intention-deontic/v1",
        ),
        preservation_rules=(
            "intention_force",
            "agent_identity",
            "modality_polarity",
            "source_grounding",
        ),
        backend_ids=("z3", "cvc5", "lean", "rocq", "isabelle"),
        authority_lane=AuthorityLane.PROOF,
        support_level=SupportLevel.NATIVE,
        evidence_authority=EvidenceAuthority.INDEPENDENTLY_CHECKABLE,
        proof_authority=ProofAuthorityRole.CANDIDATE,
        result_authority_ceiling=ResultAuthority.CANDIDATE,
    ),
    # --- Norms (deontic) ----------------------------------------------------
    _route(
        route_id="intent-route/norms/v1",
        view_id="intent-ir-view/intention-deontic/v1",
        view_name="norms",
        namespace=RouteNamespace.FAMILY,
        disposition=RouteDisposition.TYPED,
        family_id="deontic",
        profile_id="default",
        target_component="intent.norms",
        description="Deontic norms: permissions, obligations, prohibitions.",
        aliases=(
            "norms",
            "deontic",
            "permissions",
            "obligations",
            "prohibitions",
            "requirements",
            "modality",
            "intention_deontic",
        ),
        preservation_rules=(
            "operator_force",
            "norm_polarity",
            "actor_identity",
            "action_identity",
            "source_grounding",
        ),
        backend_ids=("z3", "cvc5", "datalog_secpal"),
        authority_lane=AuthorityLane.PROOF,
        support_level=SupportLevel.NATIVE,
        evidence_authority=EvidenceAuthority.INDEPENDENTLY_CHECKABLE,
        proof_authority=ProofAuthorityRole.CANDIDATE,
        result_authority_ceiling=ResultAuthority.CANDIDATE,
    ),
    # --- Dynamic / Hoare skill effects -------------------------------------
    _route(
        route_id="intent-route/action-hoare/v1",
        view_id="intent-ir-view/action-hoare/v1",
        view_name="action_hoare",
        namespace=RouteNamespace.PROFILE,
        disposition=RouteDisposition.TYPED,
        family_id="program",
        profile_id="dynamic_hoare",
        target_component="intent.action_hoare",
        description="Actions with preconditions, effects, and Hoare triples.",
        aliases=(
            "action_hoare",
            "actions",
            "hoare",
            "dynamic_hoare",
            "dynamic",
            "hoare_logic",
            "dynamic_logic",
            "intent-ir-view/action-hoare/v1",
        ),
        preservation_rules=(
            "precondition_polarity",
            "postcondition_polarity",
            "action_identity",
            "frame_conditions",
            "source_grounding",
        ),
        backend_ids=("z3", "cvc5", "lean", "rocq", "isabelle"),
        authority_lane=AuthorityLane.PROOF,
        support_level=SupportLevel.NATIVE,
        evidence_authority=EvidenceAuthority.INDEPENDENTLY_CHECKABLE,
        proof_authority=ProofAuthorityRole.CANDIDATE,
        result_authority_ceiling=ResultAuthority.CANDIDATE,
    ),
    # --- Workflow temporal --------------------------------------------------
    _route(
        route_id="intent-route/workflow-temporal/v1",
        view_id="intent-ir-view/workflow-temporal/v1",
        view_name="workflows",
        namespace=RouteNamespace.PROFILE,
        disposition=RouteDisposition.TYPED,
        family_id="temporal",
        profile_id="workflow_temporal",
        target_component="intent.workflows",
        description="Workflow control: sequencing, branching, retry, concurrency.",
        aliases=(
            "workflows",
            "workflow",
            "workflow_temporal",
            "control_flow",
            "control_edge",
            "intent-ir-view/workflow-temporal/v1",
        ),
        preservation_rules=(
            "edge_direction",
            "temporal_operator",
            "trace_model",
            "source_grounding",
        ),
        backend_ids=("tla_tlc", "apalache", "runtime_mtl"),
        authority_lane=AuthorityLane.MODEL,
        support_level=SupportLevel.NATIVE,
        evidence_authority=EvidenceAuthority.BOUNDED,
        proof_authority=ProofAuthorityRole.BOUNDED,
        result_authority_ceiling=ResultAuthority.MODEL_CHECK,
    ),
    # --- Tool / resource authorization -------------------------------------
    _route(
        route_id="intent-route/tool-permissions/v1",
        view_id="intent-ir-view/tool-permissions/v1",
        view_name="tool_permissions",
        namespace=RouteNamespace.PROFILE,
        disposition=RouteDisposition.TYPED,
        family_id="authorization",
        profile_id="tool_permissions",
        target_component="intent.tool_permissions",
        description=(
            "Tool and resource permissions under authorization. "
            "Authority never follows confidence alone."
        ),
        aliases=(
            "tool_permissions",
            "tool_permission",
            "tool_flow",
            "tool_authorization",
            "resource_permissions",
            "authorization",
            "secpal",
            "intent-ir-view/tool-permissions/v1",
        ),
        preservation_rules=(
            "principal_identity",
            "action_identity",
            "resource_identity",
            "effect_polarity",
            "delegation_scope",
            "grounded_permission_required",
        ),
        backend_ids=("datalog_secpal", "z3"),
        authority_lane=AuthorityLane.AUTHORIZATION,
        support_level=SupportLevel.NATIVE,
        evidence_authority=EvidenceAuthority.INDEPENDENTLY_CHECKABLE,
        proof_authority=ProofAuthorityRole.BOUNDED,
        result_authority_ceiling=ResultAuthority.AUTHORIZATION,
    ),
    # --- Safety / liveness as property kinds --------------------------------
    _route(
        route_id="intent-route/safety/v1",
        view_id="intent-ir-view/invariant/v1",
        view_name="safety",
        namespace=RouteNamespace.PROPERTY,
        disposition=RouteDisposition.PROPERTY,
        family_id="temporal",
        profile_id="safety",
        property_id="safety",
        target_component="intent.safety",
        description=(
            "Safety is a property kind under temporal, never a semantic family. "
            "Legacy logic_family='safety' dual-reads here."
        ),
        aliases=(
            "safety",
            "safety_property",
            "invariant",
            "invariants",
            "intent-ir-view/invariant/v1",
        ),
        preservation_rules=(
            "invariant_polarity",
            "bad_state_exclusion",
            "source_grounding",
        ),
        backend_ids=("tla_tlc", "apalache", "z3"),
        authority_lane=AuthorityLane.MODEL,
        support_level=SupportLevel.TRANSLATED,
        evidence_authority=EvidenceAuthority.BOUNDED,
        proof_authority=ProofAuthorityRole.BOUNDED,
        result_authority_ceiling=ResultAuthority.MODEL_CHECK,
    ),
    _route(
        route_id="intent-route/liveness/v1",
        view_id="intent-ir-view/failure/v1",
        view_name="liveness",
        namespace=RouteNamespace.PROPERTY,
        disposition=RouteDisposition.PROPERTY,
        family_id="temporal",
        profile_id="liveness",
        property_id="liveness",
        target_component="intent.liveness",
        description=(
            "Liveness is a property kind under temporal, never a semantic family. "
            "Legacy logic_family='safety_liveness' dual-reads to property kinds."
        ),
        aliases=(
            "liveness",
            "liveness_property",
            "safety_liveness",
            "failure",
            "intent-ir-view/failure/v1",
        ),
        preservation_rules=(
            "progress_condition",
            "fairness_constraint",
            "source_grounding",
        ),
        backend_ids=("tla_tlc", "apalache", "runtime_mtl"),
        authority_lane=AuthorityLane.MODEL,
        support_level=SupportLevel.TRANSLATED,
        evidence_authority=EvidenceAuthority.BOUNDED,
        proof_authority=ProofAuthorityRole.BOUNDED,
        result_authority_ceiling=ResultAuthority.MODEL_CHECK,
    ),
    # --- Verification condition view role -----------------------------------
    _route(
        route_id="intent-route/verification-condition-role/v1",
        view_id="intent-ir-view/verification/v1",
        view_name="verification_condition",
        namespace=RouteNamespace.VIEW_ROLE,
        disposition=RouteDisposition.OPERATION,
        view_role_id="verification_condition",
        target_component="intent.verification_condition",
        description=(
            "Verification-condition obligation/view role — never a semantic family. "
            "Use facts/first_order or action_hoare/program routes for family targets."
        ),
        aliases=(
            "verification_condition",
            "verification",
            "vc",
            "vc_role",
            "obligation",
            "proof_obligation",
            "intent-ir-view/verification/v1",
        ),
        preservation_rules=(
            "obligation_identity",
            "assumption_set",
            "source_grounding",
        ),
        backend_ids=(),
        authority_lane=AuthorityLane.NONE,
        support_level=SupportLevel.TRANSLATED,
        evidence_authority=EvidenceAuthority.NONE,
        proof_authority=ProofAuthorityRole.NONE,
        result_authority_ceiling=ResultAuthority.CANDIDATE,
        requires_parse_typecheck=False,
    ),
    # --- Graph projection / proof translation view roles --------------------
    _route(
        route_id="intent-route/graph-projection/v1",
        view_id="intent-ir-view/graph-projection/v1",
        view_name="graph_projection",
        namespace=RouteNamespace.VIEW_ROLE,
        disposition=RouteDisposition.OPERATION,
        view_role_id="graph_projection",
        target_component="intent.graph_projection",
        description="Graph projection operation/view role — never a semantic family.",
        aliases=(
            "graph_projection",
            "knowledge_graph",
            "knowledge_graphs",
        ),
        preservation_rules=(
            "endpoint_identity",
            "edge_direction",
            "provenance_identity",
        ),
        backend_ids=(),
        authority_lane=AuthorityLane.NONE,
        support_level=SupportLevel.TRANSLATED,
        evidence_authority=EvidenceAuthority.NONE,
        proof_authority=ProofAuthorityRole.NONE,
        result_authority_ceiling=ResultAuthority.CANDIDATE,
        requires_parse_typecheck=False,
    ),
    _route(
        route_id="intent-route/proof-translation/v1",
        view_id="intent-ir-view/proof-translation/v1",
        view_name="proof_translation",
        namespace=RouteNamespace.VIEW_ROLE,
        disposition=RouteDisposition.OPERATION,
        view_role_id="proof_translation",
        target_component="intent.proof_translation",
        description="Proof translation operation/view role — never a semantic family.",
        aliases=(
            "proof_translation",
            "external_provers",
            "prover_router",
        ),
        preservation_rules=(
            "input_formula_id",
            "route_status",
            "trust_boundary",
        ),
        backend_ids=(),
        authority_lane=AuthorityLane.NONE,
        support_level=SupportLevel.TRANSLATED,
        evidence_authority=EvidenceAuthority.NONE,
        proof_authority=ProofAuthorityRole.NONE,
        result_authority_ceiling=ResultAuthority.CANDIDATE,
        requires_parse_typecheck=False,
    ),
    # --- Runtime monitor lane -----------------------------------------------
    _route(
        route_id="intent-route/runtime-monitor/v1",
        view_id="intent-ir-view/workflow-temporal/v1",
        view_name="runtime_monitor",
        namespace=RouteNamespace.PROFILE,
        disposition=RouteDisposition.BOUNDED,
        family_id="temporal",
        profile_id="runtime_mtl",
        target_component="intent.runtime_monitor",
        description="Finite-trace metric-temporal runtime monitor lane for Intent IR.",
        aliases=(
            "runtime_monitor",
            "runtime_mtl",
            "monitor",
            "runtime",
        ),
        preservation_rules=(
            "finite_trace",
            "metric_bound",
            "observation_identity",
        ),
        backend_ids=("runtime_mtl",),
        authority_lane=AuthorityLane.MONITOR,
        support_level=SupportLevel.TRANSLATED,
        evidence_authority=EvidenceAuthority.BOUNDED,
        proof_authority=ProofAuthorityRole.BOUNDED,
        result_authority_ceiling=ResultAuthority.MONITOR,
    ),
)


def _route_specificity(route: IntentLogicRoute) -> int:
    """Higher is more specific (profiles beat bare families; roles are exact)."""

    if route.namespace is RouteNamespace.VIEW_ROLE:
        return 40
    if route.namespace is RouteNamespace.PROPERTY:
        return 30
    if route.namespace is RouteNamespace.PROFILE:
        return 20
    if route.namespace is RouteNamespace.DECLARATION_ONLY:
        return 15
    if route.namespace is RouteNamespace.FAMILY:
        return 10
    return 0


def _build_route_index(
    routes: Sequence[IntentLogicRoute],
) -> dict[str, IntentLogicRoute]:
    index: dict[str, IntentLogicRoute] = {}
    for route in routes:
        primary_keys = {
            route.route_id,
            route.view_id,
            route.view_name,
            route.profile_id,
            route.property_id,
            route.view_role_id,
            route.target_component,
            *route.aliases,
        }
        secondary_keys: set[str] = set()
        if route.namespace in {
            RouteNamespace.FAMILY,
            RouteNamespace.DECLARATION_ONLY,
        } and route.family_id:
            secondary_keys.add(route.family_id)

        for key in primary_keys | secondary_keys:
            normalized = _normalize_label(key)
            if not normalized:
                continue
            existing = index.get(normalized)
            if existing is None:
                index[normalized] = route
                continue
            if existing.route_id == route.route_id:
                continue
            if key in secondary_keys and key not in primary_keys:
                continue
            if _route_specificity(route) > _route_specificity(existing):
                index[normalized] = route
    return index


def _normalize_label(value: object) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return ""
    text = text.replace("-", "_").replace(" ", "_")
    text = text.replace(".", "_")
    text = text.replace("/", "_")
    while "__" in text:
        text = text.replace("__", "_")
    return text.strip("_")


INTENT_LOGIC_ROUTE_CATALOG: Final[tuple[IntentLogicRoute, ...]] = (
    _INTENT_LOGIC_ROUTES
)
_ROUTE_BY_LABEL: Final[dict[str, IntentLogicRoute]] = _build_route_index(
    INTENT_LOGIC_ROUTE_CATALOG
)

# Primary admitted semantic views required by LFP-036 effects.
ADMITTED_INTENT_VIEW_NAMES: Final[tuple[str, ...]] = (
    "facts",
    "skill_goals",
    "guards_effects",
    "norms",
    "intentions",
    "action_hoare",
    "workflows",
    "tool_permissions",
    "safety",
    "liveness",
)


# ---------------------------------------------------------------------------
# Formula candidate lifecycle
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FormulaCandidate:
    """A formula that remains a candidate until parse/typecheck/verify."""

    formula_id: str
    status: FormulaStatus
    source_kind: str = "declaration"
    prompt_derived: bool = False
    parsed: bool = False
    typechecked: bool = False
    verified: bool = False
    confidence: float | None = None
    diagnostics: tuple[str, ...] = ()
    schema_version: str = INTENT_FORMULA_CANDIDATE_SCHEMA

    def __post_init__(self) -> None:
        if not self.formula_id:
            raise IntentTypedCompilerError(
                "formula_id must be non-empty",
                code=CODE_MALFORMED,
                path="formula_id",
            )
        if not isinstance(self.status, FormulaStatus):
            object.__setattr__(self, "status", FormulaStatus(str(self.status)))
        # Prompt-derived without full pipeline stays candidate.
        if self.prompt_derived and not (self.parsed and self.typechecked and self.verified):
            if self.status is FormulaStatus.VERIFIED:
                object.__setattr__(self, "status", FormulaStatus.CANDIDATE)
                object.__setattr__(self, "verified", False)
        if self.confidence is not None:
            conf = float(self.confidence)
            if conf < 0.0 or conf > 1.0:
                raise IntentTypedCompilerError(
                    f"confidence must be in [0,1]; got {conf}",
                    code=CODE_MALFORMED,
                    path="confidence",
                )
            object.__setattr__(self, "confidence", conf)

    @property
    def is_candidate(self) -> bool:
        return self.status is FormulaStatus.CANDIDATE or (
            self.prompt_derived and not self.verified
        )

    @property
    def may_claim_verified(self) -> bool:
        return (
            self.parsed
            and self.typechecked
            and self.verified
            and self.status is FormulaStatus.VERIFIED
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "confidence": self.confidence,
            "diagnostics": list(self.diagnostics),
            "formula_id": self.formula_id,
            "is_candidate": self.is_candidate,
            "may_claim_verified": self.may_claim_verified,
            "parsed": self.parsed,
            "prompt_derived": self.prompt_derived,
            "schema_version": self.schema_version,
            "source_kind": self.source_kind,
            "status": self.status.value,
            "typechecked": self.typechecked,
            "verified": self.verified,
        }


def _is_prompt_derived_source(source_kind: object) -> bool:
    normalized = _normalize_label(source_kind)
    if not normalized:
        return False
    if normalized in PROMPT_DERIVED_SOURCE_KINDS:
        return True
    return any(marker in normalized for marker in PROMPT_DERIVED_SOURCE_KINDS)


def classify_formula_candidate(
    formula: Mapping[str, Any] | Any,
    *,
    default_source_kind: str = "declaration",
) -> FormulaCandidate:
    """Classify a formula as candidate or advanced based on source + receipts."""

    if isinstance(formula, Mapping):
        payload = dict(formula)
    else:
        payload = {
            "formula_id": getattr(formula, "formula_id", "") or str(formula),
            "source_kind": getattr(formula, "source_kind", default_source_kind),
        }

    formula_id = str(payload.get("formula_id") or payload.get("id") or "")
    if not formula_id:
        formula_id = f"formula:{stable_digest(payload)[:16]}"

    source_kind = str(
        payload.get("source_kind")
        or payload.get("source")
        or payload.get("derivation")
        or default_source_kind
    )
    prompt_derived = bool(payload.get("prompt_derived", False)) or _is_prompt_derived_source(
        source_kind
    )
    if bool(payload.get("inferred", False)) or bool(payload.get("llm_extracted", False)):
        prompt_derived = True

    parsed = bool(payload.get("parsed", False))
    typechecked = bool(payload.get("typechecked", False))
    verified = bool(payload.get("verified", False))
    confidence = payload.get("confidence")
    if confidence is not None:
        try:
            confidence = float(confidence)
        except (TypeError, ValueError):
            confidence = None

    diagnostics: list[str] = []
    if prompt_derived:
        diagnostics.append(CODE_CANDIDATE_ONLY)

    if payload.get("rejected") or payload.get("unsupported"):
        status = FormulaStatus.REJECTED
        diagnostics.append(CODE_PARSE_FAILED)
    elif verified and parsed and typechecked and not prompt_derived:
        status = FormulaStatus.VERIFIED
    elif verified and parsed and typechecked and prompt_derived:
        # Even prompt-derived may advance once full deterministic pipeline runs.
        status = FormulaStatus.VERIFIED
        diagnostics = [d for d in diagnostics if d != CODE_CANDIDATE_ONLY]
    elif typechecked and parsed:
        status = FormulaStatus.TYPECHECKED
    elif parsed:
        status = FormulaStatus.PARSED
    else:
        status = FormulaStatus.CANDIDATE
        if prompt_derived and CODE_CANDIDATE_ONLY not in diagnostics:
            diagnostics.append(CODE_CANDIDATE_ONLY)

    # Prompt-derived without verification remains candidate regardless of confidence.
    if prompt_derived and not (parsed and typechecked and verified):
        status = FormulaStatus.CANDIDATE
        verified = False
        if CODE_CANDIDATE_ONLY not in diagnostics:
            diagnostics.append(CODE_CANDIDATE_ONLY)

    return FormulaCandidate(
        formula_id=formula_id,
        status=status,
        source_kind=source_kind,
        prompt_derived=prompt_derived,
        parsed=parsed,
        typechecked=typechecked,
        verified=verified if status is FormulaStatus.VERIFIED else False,
        confidence=confidence,
        diagnostics=tuple(diagnostics),
    )


# ---------------------------------------------------------------------------
# Tool authority (never from confidence alone)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ToolAuthorityReceipt:
    """Receipt deciding whether tool/resource authority is granted."""

    receipt_id: str
    tool_id: str
    granted: bool
    basis: ToolAuthorityBasis
    confidence: float | None = None
    grounded_permission: bool = False
    authorization_receipt_id: str = ""
    policy_id: str = ""
    diagnostics: tuple[str, ...] = ()
    schema_version: str = INTENT_TOOL_AUTHORITY_SCHEMA

    def __post_init__(self) -> None:
        if not isinstance(self.basis, ToolAuthorityBasis):
            object.__setattr__(self, "basis", ToolAuthorityBasis(str(self.basis)))
        if not self.receipt_id:
            digest = stable_digest(
                {
                    "tool_id": self.tool_id,
                    "basis": self.basis.value,
                    "granted": self.granted,
                }
            )
            object.__setattr__(
                self, "receipt_id", f"receipt:intent-tool-auth:{digest[:24]}"
            )
        # Fail closed: confidence alone can never grant.
        if self.basis is ToolAuthorityBasis.CONFIDENCE_SCORE and self.granted:
            object.__setattr__(self, "granted", False)
            diags = list(self.diagnostics)
            if CODE_TOOL_CONFIDENCE not in diags:
                diags.append(CODE_TOOL_CONFIDENCE)
            object.__setattr__(self, "diagnostics", tuple(diags))
        if self.confidence is not None:
            conf = float(self.confidence)
            if conf < 0.0 or conf > 1.0:
                raise IntentTypedCompilerError(
                    f"confidence must be in [0,1]; got {conf}",
                    code=CODE_MALFORMED,
                    path="confidence",
                )
            object.__setattr__(self, "confidence", conf)

    def to_dict(self) -> dict[str, Any]:
        return {
            "authorization_receipt_id": self.authorization_receipt_id,
            "basis": self.basis.value,
            "confidence": self.confidence,
            "diagnostics": list(self.diagnostics),
            "granted": self.granted,
            "grounded_permission": self.grounded_permission,
            "policy_id": self.policy_id,
            "receipt_id": self.receipt_id,
            "schema_version": self.schema_version,
            "tool_id": self.tool_id,
        }


def decide_tool_authority(
    *,
    tool_id: str,
    confidence: float | None = None,
    grounded_permission: bool = False,
    authorization_receipt_id: str = "",
    policy_id: str = "",
    claimed_authority: bool = False,
) -> ToolAuthorityReceipt:
    """Decide tool authority; confidence alone is never sufficient.

    Tool authority requires at least one of:
    * grounded_permission (source-grounded declared permission)
    * non-empty authorization_receipt_id
    * non-empty policy_id (declared policy binding)

    High confidence without any of the above is rejected fail-closed.
    """

    if not tool_id or not str(tool_id).strip():
        raise IntentTypedCompilerError(
            "tool_id must be non-empty",
            code=CODE_MALFORMED,
            path="tool_id",
        )
    tool_id = str(tool_id).strip()
    diagnostics: list[str] = []

    if grounded_permission:
        basis = ToolAuthorityBasis.GROUNDED_PERMISSION
        granted = True
    elif authorization_receipt_id:
        basis = ToolAuthorityBasis.AUTHORIZATION_RECEIPT
        granted = True
    elif policy_id:
        basis = ToolAuthorityBasis.DECLARED_POLICY
        granted = True
    elif confidence is not None or claimed_authority:
        basis = ToolAuthorityBasis.CONFIDENCE_SCORE
        granted = False
        diagnostics.append(CODE_TOOL_CONFIDENCE)
        if claimed_authority:
            raise ToolAuthorityFromConfidenceError(
                f"tool {tool_id!r} authority cannot follow confidence alone"
                + (
                    f" (confidence={confidence})"
                    if confidence is not None
                    else ""
                ),
            )
    else:
        basis = ToolAuthorityBasis.NONE
        granted = False

    return ToolAuthorityReceipt(
        receipt_id="",
        tool_id=tool_id,
        granted=granted,
        basis=basis,
        confidence=confidence,
        grounded_permission=grounded_permission,
        authorization_receipt_id=str(authorization_receipt_id or ""),
        policy_id=str(policy_id or ""),
        diagnostics=tuple(diagnostics),
    )


def reject_tool_authority_from_confidence(
    *,
    tool_id: str = "tool",
    confidence: float = 1.0,
) -> None:
    """Fail closed when tool authority is claimed from confidence alone."""

    decide_tool_authority(
        tool_id=tool_id,
        confidence=confidence,
        claimed_authority=True,
    )


# ---------------------------------------------------------------------------
# Parse / typecheck pipeline
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ParseTypecheckReceipt:
    """Receipt proving parse+typecheck completed before verification."""

    receipt_id: str
    route_id: str
    stage: ParseElaborateStage
    ok: bool
    parsed: bool
    typechecked: bool
    ready_to_verify: bool
    diagnostics: tuple[str, ...] = ()
    source_kind: str = "declaration"
    formula_count: int = 0
    candidate_count: int = 0
    prompt_derived_count: int = 0
    unsupported_constructs: tuple[str, ...] = ()
    candidates: tuple[FormulaCandidate, ...] = ()
    schema_version: str = INTENT_PARSE_ELABORATE_SCHEMA

    def __post_init__(self) -> None:
        if not isinstance(self.stage, ParseElaborateStage):
            object.__setattr__(self, "stage", ParseElaborateStage(str(self.stage)))
        if not self.receipt_id:
            digest = stable_digest(
                {
                    "route_id": self.route_id,
                    "stage": self.stage.value,
                    "ok": self.ok,
                }
            )
            object.__setattr__(
                self, "receipt_id", f"receipt:intent-parse:{digest[:24]}"
            )
        if self.ready_to_verify and not (self.parsed and self.typechecked and self.ok):
            object.__setattr__(self, "ready_to_verify", False)
        if self.ok and self.parsed and self.typechecked:
            if self.stage not in {
                ParseElaborateStage.TYPECHECKED,
                ParseElaborateStage.READY_TO_VERIFY,
                ParseElaborateStage.VERIFIED,
            }:
                object.__setattr__(
                    self, "stage", ParseElaborateStage.READY_TO_VERIFY
                )

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_count": self.candidate_count,
            "candidates": [item.to_dict() for item in self.candidates],
            "diagnostics": list(self.diagnostics),
            "formula_count": self.formula_count,
            "ok": self.ok,
            "parsed": self.parsed,
            "prompt_derived_count": self.prompt_derived_count,
            "ready_to_verify": self.ready_to_verify,
            "receipt_id": self.receipt_id,
            "route_id": self.route_id,
            "schema_version": self.schema_version,
            "source_kind": self.source_kind,
            "stage": self.stage.value,
            "typechecked": self.typechecked,
            "unsupported_constructs": list(self.unsupported_constructs),
        }


def parse_and_typecheck(
    route: IntentLogicRoute,
    *,
    formulas: Sequence[Mapping[str, Any] | Any] = (),
    source_kind: str = "declaration",
    fail_on_unsupported: bool = True,
) -> ParseTypecheckReceipt:
    """Run deterministic parse+typecheck; prompt-derived stay candidates."""

    diagnostics: list[str] = []
    unsupported: list[str] = []
    candidates: list[FormulaCandidate] = []
    formula_list = list(formulas) if formulas else []

    if not formula_list:
        # Empty declaration is admissible: parse/typecheck vacuously succeed.
        return ParseTypecheckReceipt(
            receipt_id="",
            route_id=route.route_id,
            stage=ParseElaborateStage.READY_TO_VERIFY,
            ok=True,
            parsed=True,
            typechecked=True,
            ready_to_verify=True,
            diagnostics=(),
            source_kind=source_kind,
            formula_count=0,
            candidate_count=0,
            prompt_derived_count=0,
            unsupported_constructs=(),
            candidates=(),
        )

    for item in formula_list:
        candidate = classify_formula_candidate(
            item, default_source_kind=source_kind
        )
        candidates.append(candidate)
        if isinstance(item, Mapping):
            if item.get("unsupported"):
                construct = str(item.get("construct") or item.get("formula_id") or "unknown")
                unsupported.append(construct)
            # Structured formulas without explicit parse flags are treated as
            # declaration-structured (already "parsed" for typed lowering).
            if not candidate.prompt_derived and not candidate.parsed:
                # Re-classify as parsed+typechecked for structured declarations.
                candidates[-1] = FormulaCandidate(
                    formula_id=candidate.formula_id,
                    status=FormulaStatus.TYPECHECKED,
                    source_kind=candidate.source_kind,
                    prompt_derived=False,
                    parsed=True,
                    typechecked=True,
                    verified=False,
                    confidence=candidate.confidence,
                    diagnostics=candidate.diagnostics,
                )

    prompt_derived_count = sum(1 for c in candidates if c.prompt_derived)
    candidate_count = sum(1 for c in candidates if c.is_candidate)

    if unsupported and fail_on_unsupported:
        diagnostics.append(CODE_PARSE_FAILED)
        return ParseTypecheckReceipt(
            receipt_id="",
            route_id=route.route_id,
            stage=ParseElaborateStage.REJECTED,
            ok=False,
            parsed=False,
            typechecked=False,
            ready_to_verify=False,
            diagnostics=tuple(diagnostics),
            source_kind=source_kind,
            formula_count=len(candidates),
            candidate_count=candidate_count,
            prompt_derived_count=prompt_derived_count,
            unsupported_constructs=tuple(unsupported),
            candidates=tuple(candidates),
        )

    if unsupported:
        diagnostics.append(CODE_PARSE_FAILED)

    # Prompt-derived formulas without parse/typecheck keep the pipeline in
    # candidate stage for those items, but do not block declaration-side parse.
    all_prompt_unparsed = bool(candidates) and all(
        c.prompt_derived and not (c.parsed and c.typechecked) for c in candidates
    )
    if all_prompt_unparsed:
        diagnostics.append(CODE_CANDIDATE_ONLY)
        return ParseTypecheckReceipt(
            receipt_id="",
            route_id=route.route_id,
            stage=ParseElaborateStage.ADMITTED,
            ok=True,
            parsed=False,
            typechecked=False,
            ready_to_verify=False,
            diagnostics=tuple(diagnostics),
            source_kind=source_kind,
            formula_count=len(candidates),
            candidate_count=candidate_count,
            prompt_derived_count=prompt_derived_count,
            unsupported_constructs=tuple(unsupported),
            candidates=tuple(candidates),
        )

    # Mixed or structured: parse/typecheck succeed for ready items.
    parsed = all(
        (not c.prompt_derived) or c.parsed or c.status is FormulaStatus.REJECTED
        for c in candidates
    ) or any(c.parsed or not c.prompt_derived for c in candidates)
    typechecked = any(
        c.typechecked or (not c.prompt_derived and c.status is not FormulaStatus.REJECTED)
        for c in candidates
    )
    # For structured declarations, treat as fully typechecked when no failures.
    if not any(c.prompt_derived and not (c.parsed and c.typechecked) for c in candidates):
        parsed = True
        typechecked = True

    ready = parsed and typechecked and not (unsupported and fail_on_unsupported)
    if prompt_derived_count and any(
        c.prompt_derived and not c.may_claim_verified for c in candidates
    ):
        diagnostics.append(CODE_CANDIDATE_ONLY)

    stage = (
        ParseElaborateStage.READY_TO_VERIFY
        if ready
        else ParseElaborateStage.PARSED
        if parsed
        else ParseElaborateStage.ADMITTED
    )
    return ParseTypecheckReceipt(
        receipt_id="",
        route_id=route.route_id,
        stage=stage,
        ok=True if not unsupported or not fail_on_unsupported else False,
        parsed=parsed,
        typechecked=typechecked,
        ready_to_verify=ready,
        diagnostics=tuple(dict.fromkeys(diagnostics)),
        source_kind=source_kind,
        formula_count=len(candidates),
        candidate_count=candidate_count,
        prompt_derived_count=prompt_derived_count,
        unsupported_constructs=tuple(unsupported),
        candidates=tuple(candidates),
    )


def assert_ready_to_verify(receipt: ParseTypecheckReceipt) -> None:
    """Fail closed when verification is attempted without parse/typecheck."""

    if not receipt.ready_to_verify or not receipt.ok:
        raise ParseTypecheckRequiredError(
            f"route {receipt.route_id!r} is not ready to verify "
            f"(stage={receipt.stage.value}, parsed={receipt.parsed}, "
            f"typechecked={receipt.typechecked})"
        )


# ---------------------------------------------------------------------------
# Route resolution
# ---------------------------------------------------------------------------


def is_never_family_label(label: object) -> bool:
    """Return True when *label* is an operation/view role, never a family."""

    normalized = _normalize_label(label)
    if not normalized:
        return False
    if normalized in NEVER_FAMILY_OPERATION_ROLES:
        return True
    # Allow suffix matches for intent-ir-view/verification/v1 style ids.
    for role in NEVER_FAMILY_OPERATION_ROLES:
        if role in normalized or normalized.endswith(role):
            return True
    # Catalog aliases (obligation, vc_role, …) resolve to view-role routes.
    route = _ROUTE_BY_LABEL.get(normalized)
    if route is not None and route.is_operation_role:
        return True
    return False


def is_never_family_property(label: object) -> bool:
    """Return True when *label* is a property kind, never a family."""

    normalized = _normalize_label(label)
    if not normalized:
        return False
    if normalized in NEVER_FAMILY_PROPERTY_KINDS:
        return True
    for prop in NEVER_FAMILY_PROPERTY_KINDS:
        if normalized == prop or normalized.endswith(f"_{prop}"):
            return True
    route = _ROUTE_BY_LABEL.get(normalized)
    if route is not None and route.is_property_kind:
        return True
    return False


def reject_operation_role_as_family(label: object) -> None:
    """Raise when an operation/view role is offered as a semantic family."""

    if is_never_family_label(label):
        raise OperationRoleAsFamilyError(str(label))


def reject_property_as_family(label: object) -> None:
    """Raise when a property kind is offered as a semantic family."""

    if is_never_family_property(label):
        raise PropertyAsFamilyError(str(label))


def resolve_intent_route(label: object) -> IntentLogicRoute:
    """Resolve a view/family/property/role label to a sealed intent route."""

    if label is None:
        raise IntentTypedCompilerError(
            "route label is required",
            code=CODE_MALFORMED,
            path="label",
        )
    normalized = _normalize_label(label)
    if not normalized:
        raise IntentTypedCompilerError(
            "route label is required",
            code=CODE_MALFORMED,
            path="label",
        )

    # Future/wave-4 claims fail closed as unsupported.
    if normalized in FUTURE_UNSUPPORTED_FAMILY_CLAIMS or any(
        claim in normalized for claim in FUTURE_UNSUPPORTED_FAMILY_CLAIMS
    ):
        raise IntentTypedCompilerError(
            f"future/unsupported family claim {label!r} is not admitted for Intent IR",
            code=CODE_UNSUPPORTED,
            path="label",
        )

    route = _ROUTE_BY_LABEL.get(normalized)
    if route is not None:
        return route

    # Soft alias: intent_ir_view_X_v1 style after slash normalization.
    alt = normalized.replace("intent_ir_view_", "intent-ir-view/")
    if alt != normalized:
        route = _ROUTE_BY_LABEL.get(_normalize_label(alt))
        if route is not None:
            return route

    raise IntentTypedCompilerError(
        f"unknown intent view/route label {label!r}",
        code=CODE_UNKNOWN_VIEW,
        path="label",
    )


def intent_logic_routes() -> tuple[IntentLogicRoute, ...]:
    """Return the sealed intent logic route catalog."""

    return INTENT_LOGIC_ROUTE_CATALOG


# ---------------------------------------------------------------------------
# Route receipt
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class IntentRouteReceipt:
    """Receipt for one typed intent view routing decision."""

    receipt_id: str
    route: IntentLogicRoute
    authority_ceiling: ResultAuthority
    diagnostics: tuple[str, ...] = ()
    parse_typecheck: ParseTypecheckReceipt | None = None
    tool_authority: ToolAuthorityReceipt | None = None
    lowered: bool = False
    schema_version: str = INTENT_ROUTE_RECEIPT_SCHEMA

    def __post_init__(self) -> None:
        if not isinstance(self.authority_ceiling, ResultAuthority):
            object.__setattr__(
                self,
                "authority_ceiling",
                ResultAuthority(str(self.authority_ceiling)),
            )
        if not self.receipt_id:
            digest = stable_digest(
                {
                    "route_id": self.route.route_id,
                    "ceiling": self.authority_ceiling.value,
                }
            )
            object.__setattr__(
                self, "receipt_id", f"receipt:intent-route:{digest[:24]}"
            )

    @property
    def is_proof(self) -> bool:
        return False  # Routes alone never mint proof.

    @property
    def is_ready_to_verify(self) -> bool:
        if self.parse_typecheck is None:
            return not self.route.requires_parse_typecheck
        return self.parse_typecheck.ready_to_verify

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority_ceiling": self.authority_ceiling.value,
            "diagnostics": list(self.diagnostics),
            "is_proof": self.is_proof,
            "is_ready_to_verify": self.is_ready_to_verify,
            "lowered": self.lowered,
            "parse_typecheck": (
                self.parse_typecheck.to_dict() if self.parse_typecheck else None
            ),
            "receipt_id": self.receipt_id,
            "route": self.route.to_dict(),
            "schema_version": self.schema_version,
            "tool_authority": (
                self.tool_authority.to_dict() if self.tool_authority else None
            ),
        }


def enforce_authority_ceiling(
    route: IntentLogicRoute,
    claimed: ResultAuthority | str | None,
) -> ResultAuthority:
    """Clamp or reject authority claims that exceed the route ceiling."""

    if claimed is None:
        return route.result_authority_ceiling
    if isinstance(claimed, ResultAuthority):
        claimed_auth = claimed
    else:
        try:
            claimed_auth = ResultAuthority(str(claimed))
        except (TypeError, ValueError) as exc:
            raise IntentTypedCompilerError(
                f"unknown result authority {claimed!r}",
                code=CODE_MALFORMED,
                path="authority",
            ) from exc

    if route.is_operation_role and claimed_auth is ResultAuthority.THEOREM:
        raise AuthorityPromotionError(
            f"operation role {route.view_role_id!r} cannot claim theorem authority"
        )

    if route.is_property_kind and claimed_auth is ResultAuthority.THEOREM:
        raise AuthorityPromotionError(
            f"property kind {route.property_id!r} cannot claim theorem authority "
            "from the route alone"
        )

    if (
        claimed_auth is ResultAuthority.THEOREM
        and route.proof_authority is not ProofAuthorityRole.OFFICIAL
    ):
        raise AuthorityPromotionError(
            f"route {route.route_id!r} authority ceiling is "
            f"{route.result_authority_ceiling.value}; theorem is not permitted"
        )

    return claimed_auth


def route_intent_view(
    label: object,
    *,
    formulas: Sequence[Mapping[str, Any] | Any] = (),
    source_kind: str = "declaration",
    claimed_authority: object = None,
    tool_id: str = "",
    tool_confidence: float | None = None,
    grounded_permission: bool = False,
    authorization_receipt_id: str = "",
    policy_id: str = "",
    fail_on_unsupported: bool = True,
) -> IntentRouteReceipt:
    """Route an intent view label and attach parse/typecheck + tool authority."""

    route = resolve_intent_route(label)
    diagnostics: list[str] = []

    if route.is_operation_role:
        diagnostics.append(CODE_OPERATION_AS_FAMILY.replace("_as_family", "_not_family"))
        # Use a stable diagnostic that tests can assert on.
        diagnostics.append("intent.view_role_not_family")
    if route.is_property_kind:
        diagnostics.append("intent.property_not_family")

    ceiling = enforce_authority_ceiling(
        route,
        claimed_authority if claimed_authority is not None else None,
    )

    parse_receipt: ParseTypecheckReceipt | None = None
    if route.requires_parse_typecheck or formulas:
        parse_receipt = parse_and_typecheck(
            route,
            formulas=formulas,
            source_kind=source_kind,
            fail_on_unsupported=fail_on_unsupported,
        )
        diagnostics.extend(parse_receipt.diagnostics)

    tool_receipt: ToolAuthorityReceipt | None = None
    if tool_id or route.view_name == "tool_permissions":
        effective_tool = tool_id or "tool:unspecified"
        try:
            tool_receipt = decide_tool_authority(
                tool_id=effective_tool,
                confidence=tool_confidence,
                grounded_permission=grounded_permission,
                authorization_receipt_id=authorization_receipt_id,
                policy_id=policy_id,
                claimed_authority=False,
            )
        except ToolAuthorityFromConfidenceError:
            raise
        if tool_receipt.diagnostics:
            diagnostics.extend(tool_receipt.diagnostics)

    return IntentRouteReceipt(
        receipt_id="",
        route=route,
        authority_ceiling=ceiling,
        diagnostics=tuple(dict.fromkeys(diagnostics)),
        parse_typecheck=parse_receipt,
        tool_authority=tool_receipt,
        lowered=False,
    )


# ---------------------------------------------------------------------------
# Compiler (IntentFormalizationCompiler@2)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class IntentFormalizationCompiler:
    """Route intent_ir skill-prompt views onto canonical typed logic.

    Interface: ``IntentFormalizationCompiler@2``.

    This is the typed migration surface for LFP-036.  The v1 syntactic
    compiler in :mod:`.compiler` remains available for dual-read; this
    compiler owns namespace separation for skill goals, tool permissions,
    guards/effects, norms, intentions, workflows, safety/liveness properties,
    and verification-condition view roles.
    """

    INTERFACE: ClassVar[str] = INTENT_FORMALIZATION_COMPILER_INTERFACE
    VERSION: ClassVar[str] = INTENT_FORMALIZATION_COMPILER_VERSION

    producer_id: str = INTENT_IR_TYPED_COMPILER_PRODUCER_ID
    domain: str = INTENT_IR_TYPED_DOMAIN
    domain_id: str = INTENT_IR_DOMAIN_ID

    def __post_init__(self) -> None:
        if not _ID_RE.fullmatch(self.producer_id):
            raise IntentTypedCompilerError(
                "producer_id must be a stable shared identifier",
                code=CODE_MALFORMED,
                path="producer_id",
            )

    @property
    def interface(self) -> str:
        return self.INTERFACE

    @property
    def version(self) -> str:
        return self.VERSION

    def known_routes(self) -> tuple[str, ...]:
        return tuple(route.route_id for route in INTENT_LOGIC_ROUTE_CATALOG)

    def known_views(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(route.view_name for route in INTENT_LOGIC_ROUTE_CATALOG))

    @property
    def routes(self) -> tuple[IntentLogicRoute, ...]:
        return INTENT_LOGIC_ROUTE_CATALOG

    def typed_family_routes(self) -> tuple[IntentLogicRoute, ...]:
        return tuple(route for route in INTENT_LOGIC_ROUTE_CATALOG if route.is_semantic_family)

    def property_routes(self) -> tuple[IntentLogicRoute, ...]:
        return tuple(route for route in INTENT_LOGIC_ROUTE_CATALOG if route.is_property_kind)

    def operation_role_routes(self) -> tuple[IntentLogicRoute, ...]:
        return tuple(route for route in INTENT_LOGIC_ROUTE_CATALOG if route.is_operation_role)

    def resolve(self, label: object) -> IntentLogicRoute:
        return resolve_intent_route(label)

    def route_for(self, label: object) -> IntentLogicRoute:
        return resolve_intent_route(label)

    def route_view(
        self,
        label: object,
        *,
        formulas: Sequence[Mapping[str, Any] | Any] = (),
        source_kind: str = "declaration",
        claimed_authority: object = None,
        tool_id: str = "",
        tool_confidence: float | None = None,
        grounded_permission: bool = False,
        authorization_receipt_id: str = "",
        policy_id: str = "",
        fail_on_unsupported: bool = True,
    ) -> IntentRouteReceipt:
        return route_intent_view(
            label,
            formulas=formulas,
            source_kind=source_kind,
            claimed_authority=claimed_authority,
            tool_id=tool_id,
            tool_confidence=tool_confidence,
            grounded_permission=grounded_permission,
            authorization_receipt_id=authorization_receipt_id,
            policy_id=policy_id,
            fail_on_unsupported=fail_on_unsupported,
        )

    def parse_and_typecheck(
        self,
        label: object,
        *,
        formulas: Sequence[Mapping[str, Any] | Any] = (),
        source_kind: str = "declaration",
        fail_on_unsupported: bool = True,
    ) -> ParseTypecheckReceipt:
        route = resolve_intent_route(label)
        return parse_and_typecheck(
            route,
            formulas=formulas,
            source_kind=source_kind,
            fail_on_unsupported=fail_on_unsupported,
        )

    def lower_view(
        self,
        label: object,
        *,
        formulas: Sequence[Mapping[str, Any] | Any] = (),
        source_kind: str = "declaration",
        fail_on_unsupported: bool = True,
    ) -> IntentRouteReceipt:
        """Lower a view only after successful parse/typecheck when required."""

        route = resolve_intent_route(label)
        pe = parse_and_typecheck(
            route,
            formulas=formulas,
            source_kind=source_kind,
            fail_on_unsupported=fail_on_unsupported,
        )
        if route.requires_parse_typecheck:
            assert_ready_to_verify(pe)
        ceiling = enforce_authority_ceiling(route, None)
        return IntentRouteReceipt(
            receipt_id="",
            route=route,
            authority_ceiling=ceiling,
            diagnostics=tuple(pe.diagnostics),
            parse_typecheck=pe,
            lowered=True,
        )

    def decide_tool_authority(
        self,
        *,
        tool_id: str,
        confidence: float | None = None,
        grounded_permission: bool = False,
        authorization_receipt_id: str = "",
        policy_id: str = "",
        claimed_authority: bool = False,
    ) -> ToolAuthorityReceipt:
        return decide_tool_authority(
            tool_id=tool_id,
            confidence=confidence,
            grounded_permission=grounded_permission,
            authorization_receipt_id=authorization_receipt_id,
            policy_id=policy_id,
            claimed_authority=claimed_authority,
        )

    def classify_formula(
        self,
        formula: Mapping[str, Any] | Any,
        *,
        default_source_kind: str = "declaration",
    ) -> FormulaCandidate:
        return classify_formula_candidate(
            formula, default_source_kind=default_source_kind
        )

    def assert_operations_are_not_families(
        self, labels: Sequence[object] | None = None
    ) -> None:
        """Fail closed if any operation-role label is claimed as a family."""

        if labels is None:
            labels = (
                "verification_condition",
                "graph_projection",
                "proof_translation",
            )
        for label in labels:
            reject_operation_role_as_family(label)

    def assert_properties_are_not_families(
        self, labels: Sequence[object] | None = None
    ) -> None:
        """Fail closed if any property-kind label is claimed as a family."""

        if labels is None:
            labels = ("safety", "liveness", "safety_liveness")
        for label in labels:
            reject_property_as_family(label)

    def assert_admitted_views_parse_before_verify(self) -> None:
        for name in ADMITTED_INTENT_VIEW_NAMES:
            route = resolve_intent_route(name)
            if not route.requires_parse_typecheck:
                continue
            pe = parse_and_typecheck(route)
            if not pe.ready_to_verify:
                raise ParseTypecheckRequiredError(
                    f"admitted view {name!r} failed vacuous parse/typecheck"
                )

    def catalog_manifest(self) -> dict[str, Any]:
        return {
            "admitted_view_names": list(ADMITTED_INTENT_VIEW_NAMES),
            "domain": self.domain,
            "domain_id": self.domain_id,
            "evidence_backends": list(INTENT_EVIDENCE_BACKENDS),
            "interface": self.interface,
            "module_version": INTENT_TYPED_COMPILER_MODULE_VERSION,
            "never_family_operation_roles": sorted(NEVER_FAMILY_OPERATION_ROLES),
            "never_family_property_kinds": sorted(NEVER_FAMILY_PROPERTY_KINDS),
            "prompt_derived_source_kinds": sorted(PROMPT_DERIVED_SOURCE_KINDS),
            "route_count": len(INTENT_LOGIC_ROUTE_CATALOG),
            "routes": [route.to_dict() for route in INTENT_LOGIC_ROUTE_CATALOG],
            "version": self.version,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "domain": self.domain,
            "domain_id": self.domain_id,
            "interface": self.interface,
            "never_family_operation_roles": sorted(NEVER_FAMILY_OPERATION_ROLES),
            "never_family_property_kinds": sorted(NEVER_FAMILY_PROPERTY_KINDS),
            "producer_id": self.producer_id,
            "prompt_derived_is_candidate_until_verified": True,
            "tool_authority_follows_confidence_alone": False,
            "version": self.version,
        }


# Public aliases matching sibling domain adapters.
IntentFormalizationCompilerV2 = IntentFormalizationCompiler


__all__ = [
    "ADMITTED_INTENT_VIEW_NAMES",
    "AuthorityLane",
    "AuthorityPromotionError",
    "FORMULA_STATUS_CANDIDATE",
    "FormulaCandidate",
    "FormulaStatus",
    "FreeFormFamilyError",
    "FUTURE_UNSUPPORTED_FAMILY_CLAIMS",
    "INTENT_EVIDENCE_BACKENDS",
    "INTENT_FORMALIZATION_COMPILER_INTERFACE",
    "INTENT_FORMALIZATION_COMPILER_VERSION",
    "INTENT_LOGIC_ROUTE_CATALOG",
    "INTENT_IR_DOMAIN_ID",
    "IntentFormalizationCompiler",
    "IntentFormalizationCompilerV2",
    "IntentLogicRoute",
    "IntentRouteReceipt",
    "IntentTypedCompilerError",
    "NEVER_FAMILY_OPERATION_ROLES",
    "NEVER_FAMILY_PROPERTY_KINDS",
    "OperationRoleAsFamilyError",
    "PROMPT_DERIVED_SOURCE_KINDS",
    "ParseElaborateStage",
    "ParseTypecheckReceipt",
    "ParseTypecheckRequiredError",
    "ProofAuthorityRole",
    "PropertyAsFamilyError",
    "RouteDisposition",
    "RouteNamespace",
    "ToolAuthorityBasis",
    "ToolAuthorityFromConfidenceError",
    "ToolAuthorityReceipt",
    "assert_ready_to_verify",
    "classify_formula_candidate",
    "decide_tool_authority",
    "enforce_authority_ceiling",
    "intent_logic_routes",
    "is_never_family_label",
    "is_never_family_property",
    "parse_and_typecheck",
    "reject_operation_role_as_family",
    "reject_property_as_family",
    "reject_tool_authority_from_confidence",
    "resolve_intent_route",
    "route_intent_view",
]

# Convenience constant used by some test styles.
FORMULA_STATUS_CANDIDATE: Final = FormulaStatus.CANDIDATE
