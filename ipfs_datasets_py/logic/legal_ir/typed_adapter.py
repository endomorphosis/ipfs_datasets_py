"""Typed Legal IR formalization routes to canonical logic families (LFP-037).

Interface: ``LegalFormalizationAdapter@2``

Migrates legal_ir multi-view labels onto the sealed family / profile / view-role
namespaces:

* Conditional and defeasible norms, exceptions, and priorities → ``deontic``
* Temporal FOL → ``tdfol`` (profile ``temporal_first_order``)
* Events / fluents → ``event_calculus``
* Authorization / rules → ``authorization`` (``datalog`` / SecPAL profile)
* Frames / F-logic → ``frame_logic``
* Argumentation / description logic → explicit declaration-only disposition
* ``graph_projection``, ``proof_translation``, ``structural_round_trip`` →
  operation / view roles that **never** route as semantic families

Authority rules (fail-closed):

* Natural-language extraction is never proof authority.
* Norm conflicts and parse ambiguity are explicit records, never silently dropped.
* Declaration-only and unsupported cells cannot promote to theorem authority.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, ClassVar, Final

from ipfs_datasets_py.logic.backends.results import ResultAuthority
from ipfs_datasets_py.logic.families.models import EvidenceAuthority, SupportLevel
from ipfs_datasets_py.logic.families.registry import (
    DECLARATION_ONLY_FAMILY_IDS,
    DEFAULT_REGISTRY,
)
from ipfs_datasets_py.logic.ir_core.claims import FrozenMap, stable_digest


# ---------------------------------------------------------------------------
# Interface / schema identities
# ---------------------------------------------------------------------------

LEGAL_FORMALIZATION_ADAPTER_INTERFACE: Final = "LegalFormalizationAdapter@2"
LEGAL_FORMALIZATION_ADAPTER_VERSION: Final = "2.0.0"
LEGAL_LOGIC_ROUTE_SCHEMA: Final = "legal-logic-route/v1"
LEGAL_ROUTE_RECEIPT_SCHEMA: Final = "legal-logic-route-receipt/v1"
LEGAL_NORM_CONFLICT_SCHEMA: Final = "legal-norm-conflict/v1"
LEGAL_AMBIGUITY_SCHEMA: Final = "legal-ambiguity-record/v1"
LEGAL_TYPED_ADAPTER_MODULE_VERSION: Final = "1.0.0"

LEGAL_IR_TYPED_ADAPTER_PRODUCER_ID: Final = "legal-ir-typed-adapter"
LEGAL_IR_TYPED_DOMAIN: Final = "legal"

# Stable diagnostic codes.
CODE_UNKNOWN_VIEW: Final = "legal.unknown_view"
CODE_OPERATION_AS_FAMILY: Final = "legal.operation_role_as_family"
CODE_NL_PROOF_AUTHORITY: Final = "legal.nl_extraction_not_proof"
CODE_FREE_FORM_FAMILY: Final = "legal.free_form_family"
CODE_DECLARATION_ONLY: Final = "legal.declaration_only"
CODE_UNSUPPORTED: Final = "legal.unsupported"
CODE_NORM_CONFLICT: Final = "legal.norm_conflict"
CODE_AMBIGUITY: Final = "legal.ambiguity"
CODE_AUTHORITY_PROMOTION: Final = "legal.authority_promotion_rejected"
CODE_MALFORMED: Final = "legal.malformed_input"
CODE_ROUTE: Final = "legal.route_error"

_ALL_CODES: Final[frozenset[str]] = frozenset(
    {
        CODE_UNKNOWN_VIEW,
        CODE_OPERATION_AS_FAMILY,
        CODE_NL_PROOF_AUTHORITY,
        CODE_FREE_FORM_FAMILY,
        CODE_DECLARATION_ONLY,
        CODE_UNSUPPORTED,
        CODE_NORM_CONFLICT,
        CODE_AMBIGUITY,
        CODE_AUTHORITY_PROMOTION,
        CODE_MALFORMED,
        CODE_ROUTE,
    }
)

# Labels that must never be promoted to semantic families.
NEVER_FAMILY_OPERATION_ROLES: Final[frozenset[str]] = frozenset(
    {
        "graph_projection",
        "proof_translation",
        "structural_round_trip",
        "round_trip",
        "knowledge_graphs",
        "knowledge_graph",
        "neo4j_compat",
        "external_provers",
        "prover_router",
        "prover",
        "decompiler",
        "ir_decompiler",
    }
)

# Natural-language / free-form markers rejected as proof authority.
_NL_MARKERS: Final[tuple[str, ...]] = (
    "natural language",
    "natural_language",
    "nl_extraction",
    "nl_input",
    "free text",
    "freetext",
    "plain english",
    "please prove",
    "extracted_from_text",
    "llm_extracted",
)

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class RouteNamespace(StrEnum):
    """Namespace role of a legal logic route target."""

    FAMILY = "family"
    PROFILE = "profile"
    VIEW_ROLE = "view_role"
    PROPERTY = "property"
    DECLARATION_ONLY = "declaration_only"


class RouteDisposition(StrEnum):
    """How a legal view is admitted into the typed matrix."""

    NATIVE = "native"
    TYPED = "typed"
    DECLARATION_ONLY = "declaration_only"
    UNSUPPORTED = "unsupported"
    BOUNDED = "bounded"
    ADVISORY = "advisory"
    OPERATION = "operation"


class NormConflictKind(StrEnum):
    """Closed set of explicit norm-conflict classifications."""

    OBLIGATION_PROHIBITION = "obligation_prohibition"
    PERMISSION_PROHIBITION = "permission_prohibition"
    PRIORITY_COLLISION = "priority_collision"
    EXCEPTION_SCOPE_OVERLAP = "exception_scope_overlap"
    CONDITIONAL_INCOMPATIBILITY = "conditional_incompatibility"
    DEFEATER_CYCLE = "defeater_cycle"
    AUTHORITY_COLLISION = "authority_collision"
    TEMPORAL_WINDOW_OVERLAP = "temporal_window_overlap"
    UNSPECIFIED = "unspecified"


class AmbiguityKind(StrEnum):
    """Closed set of explicit ambiguity classifications."""

    COMPETING_PARSES = "competing_parses"
    OPERATOR_FORCE = "operator_force"
    SCOPE_BOUNDARY = "scope_boundary"
    EXCEPTION_ATTACHMENT = "exception_attachment"
    TEMPORAL_ANCHOR = "temporal_anchor"
    ROLE_TYPING = "role_typing"
    FAMILY_LABEL = "family_label"
    UNSUPPORTED_INTERPRETATION = "unsupported_interpretation"
    NATURAL_LANGUAGE = "natural_language"


class ProofAuthorityRole(StrEnum):
    """What a route may claim about proof."""

    NONE = "none"
    CANDIDATE = "candidate"
    DECLARATION = "declaration"
    BOUNDED = "bounded"
    ADVISORY = "advisory"
    # Kernel/backend only — never assigned to NL extraction or operation roles.
    OFFICIAL = "official"


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class LegalTypedAdapterError(ValueError):
    """Raised when a legal typed route request is invalid."""

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


class OperationRoleAsFamilyError(LegalTypedAdapterError):
    """Raised when an operation/view role is offered as a semantic family."""

    def __init__(self, label: str, *, path: str = "logic_family") -> None:
        super().__init__(
            f"operation/view role {label!r} must never route as a semantic family",
            code=CODE_OPERATION_AS_FAMILY,
            path=path,
        )
        self.label = label


class NaturalLanguageProofAuthorityError(LegalTypedAdapterError):
    """Raised when natural-language extraction is treated as proof authority."""

    def __init__(self, message: str = "", *, path: str = "source") -> None:
        super().__init__(
            message
            or "natural-language extraction is never proof authority",
            code=CODE_NL_PROOF_AUTHORITY,
            path=path,
        )


class AuthorityPromotionError(LegalTypedAdapterError):
    """Raised when a route attempts to exceed its declared authority ceiling."""

    def __init__(self, message: str, *, path: str = "authority") -> None:
        super().__init__(message, code=CODE_AUTHORITY_PROMOTION, path=path)


class FreeFormFamilyError(LegalTypedAdapterError):
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
class LegalLogicRoute:
    """One typed legal view → canonical namespace route."""

    route_id: str
    view_id: str
    view_name: str
    namespace: RouteNamespace
    disposition: RouteDisposition
    # Canonical family when namespace is FAMILY/PROFILE/DECLARATION_ONLY;
    # empty when the target is a pure operation/view role.
    family_id: str = ""
    profile_id: str = ""
    view_role_id: str = ""
    target_component: str = ""
    description: str = ""
    aliases: tuple[str, ...] = ()
    preservation_rules: tuple[str, ...] = ()
    support_level: SupportLevel = SupportLevel.NATIVE
    evidence_authority: EvidenceAuthority = EvidenceAuthority.NONE
    proof_authority: ProofAuthorityRole = ProofAuthorityRole.NONE
    result_authority_ceiling: ResultAuthority = ResultAuthority.CANDIDATE
    schema_version: str = LEGAL_LOGIC_ROUTE_SCHEMA

    def __post_init__(self) -> None:
        if not self.route_id or not _ID_RE.fullmatch(self.route_id):
            raise LegalTypedAdapterError(
                f"route_id must be a stable identifier; got {self.route_id!r}",
                code=CODE_MALFORMED,
                path="route_id",
            )
        if not self.view_id or not _ID_RE.fullmatch(self.view_id):
            raise LegalTypedAdapterError(
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
                raise LegalTypedAdapterError(
                    f"view-role route {self.route_id!r} requires view_role_id",
                    code=CODE_MALFORMED,
                    path="view_role_id",
                )
            # Operation/view roles never claim a semantic family id.
            if self.family_id:
                raise LegalTypedAdapterError(
                    f"view-role route {self.route_id!r} must not set family_id "
                    f"(got {self.family_id!r}); operation roles are not families",
                    code=CODE_OPERATION_AS_FAMILY,
                    path="family_id",
                )
            if self.disposition is not RouteDisposition.OPERATION:
                raise LegalTypedAdapterError(
                    f"view-role route {self.route_id!r} must have operation disposition",
                    code=CODE_MALFORMED,
                    path="disposition",
                )
            if self.proof_authority is ProofAuthorityRole.OFFICIAL:
                raise LegalTypedAdapterError(
                    f"view-role route {self.route_id!r} cannot claim official proof authority",
                    code=CODE_AUTHORITY_PROMOTION,
                    path="proof_authority",
                )
            return

        if self.namespace is RouteNamespace.FAMILY:
            if not self.family_id:
                raise LegalTypedAdapterError(
                    f"family route {self.route_id!r} requires family_id",
                    code=CODE_MALFORMED,
                    path="family_id",
                )
            if self.family_id in NEVER_FAMILY_OPERATION_ROLES:
                raise OperationRoleAsFamilyError(self.family_id)
            if self.family_id not in DEFAULT_REGISTRY.families:
                raise FreeFormFamilyError(self.family_id)
            return

        if self.namespace is RouteNamespace.PROFILE:
            if not self.family_id or not self.profile_id:
                raise LegalTypedAdapterError(
                    f"profile route {self.route_id!r} requires family_id and profile_id",
                    code=CODE_MALFORMED,
                    path="profile_id",
                )
            if self.family_id in NEVER_FAMILY_OPERATION_ROLES:
                raise OperationRoleAsFamilyError(self.family_id)
            if self.family_id not in DEFAULT_REGISTRY.families:
                raise FreeFormFamilyError(self.family_id)
            return

        if self.namespace is RouteNamespace.DECLARATION_ONLY:
            if not self.family_id:
                raise LegalTypedAdapterError(
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
                raise LegalTypedAdapterError(
                    f"declaration-only route {self.route_id!r} has invalid disposition",
                    code=CODE_MALFORMED,
                    path="disposition",
                )
            if self.proof_authority is ProofAuthorityRole.OFFICIAL:
                raise LegalTypedAdapterError(
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
        }

    @property
    def is_operation_role(self) -> bool:
        return self.namespace is RouteNamespace.VIEW_ROLE

    @property
    def is_declaration_only(self) -> bool:
        return self.disposition is RouteDisposition.DECLARATION_ONLY or (
            self.namespace is RouteNamespace.DECLARATION_ONLY
        )

    @property
    def may_emit_proof(self) -> bool:
        return self.proof_authority is ProofAuthorityRole.OFFICIAL

    def to_dict(self) -> dict[str, Any]:
        return {
            "aliases": list(self.aliases),
            "description": self.description,
            "disposition": self.disposition.value,
            "evidence_authority": self.evidence_authority.value,
            "family_id": self.family_id,
            "is_operation_role": self.is_operation_role,
            "is_semantic_family": self.is_semantic_family,
            "namespace": self.namespace.value,
            "preservation_rules": list(self.preservation_rules),
            "profile_id": self.profile_id,
            "proof_authority": self.proof_authority.value,
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
    view_role_id: str = "",
    target_component: str = "",
    description: str = "",
    aliases: tuple[str, ...] = (),
    preservation_rules: tuple[str, ...] = (),
    support_level: SupportLevel = SupportLevel.NATIVE,
    evidence_authority: EvidenceAuthority = EvidenceAuthority.NONE,
    proof_authority: ProofAuthorityRole = ProofAuthorityRole.NONE,
    result_authority_ceiling: ResultAuthority = ResultAuthority.CANDIDATE,
) -> LegalLogicRoute:
    return LegalLogicRoute(
        route_id=route_id,
        view_id=view_id,
        view_name=view_name,
        namespace=namespace,
        disposition=disposition,
        family_id=family_id,
        profile_id=profile_id,
        view_role_id=view_role_id,
        target_component=target_component,
        description=description,
        aliases=aliases,
        preservation_rules=preservation_rules,
        support_level=support_level,
        evidence_authority=evidence_authority,
        proof_authority=proof_authority,
        result_authority_ceiling=result_authority_ceiling,
    )


# Canonical legal view routes.  Operation roles deliberately leave family_id
# empty and set view_role_id so they cannot be mistaken for families.
_LEGAL_LOGIC_ROUTES: Final[tuple[LegalLogicRoute, ...]] = (
    # --- Typed foundation views -------------------------------------------
    _route(
        route_id="legal-route/deontic/v1",
        view_id="legal-ir-view/deontic/v1",
        view_name="deontic",
        namespace=RouteNamespace.FAMILY,
        disposition=RouteDisposition.TYPED,
        family_id="deontic",
        target_component="deontic.ir",
        description=(
            "Normative force, polarity, scope, conditions, and defeasible exceptions."
        ),
        aliases=(
            "deontic",
            "deontic.ir",
            "deontic_ir",
            "deontic_norms",
            "conditional_normative",
            "norm",
            "norms",
        ),
        preservation_rules=(
            "operator_force",
            "prohibition_polarity",
            "condition_scope",
            "exception_precedence",
            "priority_order",
        ),
        support_level=SupportLevel.NATIVE,
        evidence_authority=EvidenceAuthority.INDEPENDENTLY_CHECKABLE,
        proof_authority=ProofAuthorityRole.CANDIDATE,
        result_authority_ceiling=ResultAuthority.CANDIDATE,
    ),
    _route(
        route_id="legal-route/deontic-conditional/v1",
        view_id="legal-ir-view/deontic-conditional/v1",
        view_name="conditional_normative",
        namespace=RouteNamespace.PROFILE,
        disposition=RouteDisposition.TYPED,
        family_id="deontic",
        profile_id="conditional_normative",
        target_component="deontic.ir",
        description="Dyadic / conditional norms with explicit activation conditions.",
        aliases=("conditional", "dyadic_norm", "conditional_norm"),
        preservation_rules=("condition_scope", "operator_force", "exception_precedence"),
        support_level=SupportLevel.NATIVE,
        evidence_authority=EvidenceAuthority.INDEPENDENTLY_CHECKABLE,
        proof_authority=ProofAuthorityRole.CANDIDATE,
        result_authority_ceiling=ResultAuthority.CANDIDATE,
    ),
    _route(
        route_id="legal-route/deontic-defeasible/v1",
        view_id="legal-ir-view/deontic-defeasible/v1",
        view_name="defeasible_normative",
        namespace=RouteNamespace.PROFILE,
        disposition=RouteDisposition.TYPED,
        family_id="deontic",
        profile_id="defeasible_normative",
        target_component="deontic.ir",
        description=(
            "Defeasible norms with ordered exceptions and priorities under deontic; "
            "the full defeasible_logic family remains declaration-only."
        ),
        aliases=("defeasible", "defeasible_norm", "priority_norm", "exceptions"),
        preservation_rules=(
            "exception_precedence",
            "priority_order",
            "operator_force",
            "defeater_scope",
        ),
        support_level=SupportLevel.NATIVE,
        evidence_authority=EvidenceAuthority.INDEPENDENTLY_CHECKABLE,
        proof_authority=ProofAuthorityRole.CANDIDATE,
        result_authority_ceiling=ResultAuthority.CANDIDATE,
    ),
    _route(
        route_id="legal-route/tdfol/v1",
        view_id="legal-ir-view/tdfol/v1",
        view_name="tdfol",
        namespace=RouteNamespace.FAMILY,
        disposition=RouteDisposition.TYPED,
        family_id="tdfol",
        profile_id="temporal_first_order",
        target_component="TDFOL.prover",
        description="Typed first-order temporal formula with explicit time anchors.",
        aliases=(
            "tdfol",
            "TDFOL",
            "TDFOL.prover",
            "tdfol_prover",
            "temporal",
            "temporal_first_order",
            "first_order_temporal",
        ),
        preservation_rules=(
            "quantifier_scope",
            "temporal_anchor",
            "event_order",
            "deontic_force",
        ),
        support_level=SupportLevel.NATIVE,
        evidence_authority=EvidenceAuthority.INDEPENDENTLY_CHECKABLE,
        proof_authority=ProofAuthorityRole.CANDIDATE,
        result_authority_ceiling=ResultAuthority.CANDIDATE,
    ),
    _route(
        route_id="legal-route/first-order/v1",
        view_id="legal-ir-view/first-order/v1",
        view_name="first_order",
        namespace=RouteNamespace.FAMILY,
        disposition=RouteDisposition.TYPED,
        family_id="first_order",
        target_component="fol.classical",
        description="Classical first-order legal facts and predicates without temporal force.",
        aliases=("fol", "first_order", "predicate_logic"),
        preservation_rules=("quantifier_scope", "predicate_signature", "polarity"),
        support_level=SupportLevel.NATIVE,
        evidence_authority=EvidenceAuthority.INDEPENDENTLY_CHECKABLE,
        proof_authority=ProofAuthorityRole.CANDIDATE,
        result_authority_ceiling=ResultAuthority.CANDIDATE,
    ),
    _route(
        route_id="legal-route/event-calculus/v1",
        view_id="legal-ir-view/cec/v1",
        view_name="cec",
        namespace=RouteNamespace.FAMILY,
        disposition=RouteDisposition.TYPED,
        family_id="event_calculus",
        target_component="CEC.native",
        description="Event-calculus events, fluents, and lifecycle transitions.",
        aliases=(
            "cec",
            "CEC.native",
            "cec_native",
            "event_calculus",
            "event",
            "events",
            "dcec",
            "dynamic",
        ),
        preservation_rules=(
            "event_identity",
            "fluent_identity",
            "transition_direction",
            "time_anchor",
        ),
        support_level=SupportLevel.NATIVE,
        evidence_authority=EvidenceAuthority.INDEPENDENTLY_CHECKABLE,
        proof_authority=ProofAuthorityRole.CANDIDATE,
        result_authority_ceiling=ResultAuthority.CANDIDATE,
    ),
    _route(
        route_id="legal-route/frame-logic/v1",
        view_id="legal-ir-view/frame-logic/v1",
        view_name="frame_logic",
        namespace=RouteNamespace.FAMILY,
        disposition=RouteDisposition.TYPED,
        family_id="frame_logic",
        target_component="modal.frame_logic",
        description="Typed frame roles and relations shared by modal and graph views.",
        aliases=(
            "frame_logic",
            "modal.frame_logic",
            "modal_frame_logic",
            "frame-logic",
            "frame",
            "flogic",
            "f_logic",
        ),
        preservation_rules=(
            "typed_role",
            "relation_direction",
            "modal_operator",
            "exception_scope",
        ),
        support_level=SupportLevel.NATIVE,
        evidence_authority=EvidenceAuthority.ADVISORY,
        proof_authority=ProofAuthorityRole.ADVISORY,
        result_authority_ceiling=ResultAuthority.CANDIDATE,
    ),
    _route(
        route_id="legal-route/authorization/v1",
        view_id="legal-ir-view/authorization/v1",
        view_name="authorization",
        namespace=RouteNamespace.FAMILY,
        disposition=RouteDisposition.TYPED,
        family_id="authorization",
        profile_id="secpal",
        target_component="authorization.secpal",
        description="Authorization and rule policies over legal principals and actions.",
        aliases=(
            "authorization",
            "rules",
            "rule",
            "datalog",
            "secpal",
            "policy",
            "authority",
        ),
        preservation_rules=(
            "principal_identity",
            "action_identity",
            "effect_polarity",
            "delegation_scope",
        ),
        support_level=SupportLevel.NATIVE,
        evidence_authority=EvidenceAuthority.INDEPENDENTLY_CHECKABLE,
        proof_authority=ProofAuthorityRole.BOUNDED,
        result_authority_ceiling=ResultAuthority.AUTHORIZATION,
    ),
    # --- Declaration-only families ----------------------------------------
    _route(
        route_id="legal-route/argumentation/v1",
        view_id="legal-ir-view/argumentation/v1",
        view_name="argumentation",
        namespace=RouteNamespace.DECLARATION_ONLY,
        disposition=RouteDisposition.DECLARATION_ONLY,
        family_id="argumentation",
        target_component="argumentation.framework",
        description=(
            "Argumentation frameworks are declaration-only until a reviewed "
            "frontend is supplied by a refill task."
        ),
        aliases=(
            "argumentation",
            "argument",
            "arguments",
            "argumentation_framework",
            "aaf",
        ),
        preservation_rules=("attack_relation", "argument_identity"),
        support_level=SupportLevel.DECLARATION_ONLY,
        evidence_authority=EvidenceAuthority.NONE,
        proof_authority=ProofAuthorityRole.DECLARATION,
        result_authority_ceiling=ResultAuthority.CANDIDATE,
    ),
    _route(
        route_id="legal-route/description-logic/v1",
        view_id="legal-ir-view/description-logic/v1",
        view_name="description_logic",
        namespace=RouteNamespace.DECLARATION_ONLY,
        disposition=RouteDisposition.DECLARATION_ONLY,
        family_id="description_logic",
        target_component="description_logic.ontology",
        description="Description/ontology logic remains declaration-only for legal IR.",
        aliases=("description_logic", "dl", "ontology", "ontology_logic"),
        preservation_rules=("concept_identity", "role_identity"),
        support_level=SupportLevel.DECLARATION_ONLY,
        evidence_authority=EvidenceAuthority.NONE,
        proof_authority=ProofAuthorityRole.DECLARATION,
        result_authority_ceiling=ResultAuthority.CANDIDATE,
    ),
    _route(
        route_id="legal-route/defeasible-logic-family/v1",
        view_id="legal-ir-view/defeasible-logic/v1",
        view_name="defeasible_logic",
        namespace=RouteNamespace.DECLARATION_ONLY,
        disposition=RouteDisposition.DECLARATION_ONLY,
        family_id="defeasible_logic",
        target_component="defeasible_logic.family",
        description=(
            "Full defeasible_logic family is declaration-only; defeasible norms "
            "under deontic use legal-route/deontic-defeasible/v1."
        ),
        aliases=("defeasible_logic", "nonmonotonic_logic"),
        preservation_rules=("defeater_scope", "priority_order"),
        support_level=SupportLevel.DECLARATION_ONLY,
        evidence_authority=EvidenceAuthority.NONE,
        proof_authority=ProofAuthorityRole.DECLARATION,
        result_authority_ceiling=ResultAuthority.CANDIDATE,
    ),
    # --- Operation / view roles (never families) --------------------------
    _route(
        route_id="legal-route/graph-projection/v1",
        view_id="legal-ir-view/knowledge-graphs/v1",
        view_name="knowledge_graphs",
        namespace=RouteNamespace.VIEW_ROLE,
        disposition=RouteDisposition.OPERATION,
        view_role_id="graph_projection",
        target_component="knowledge_graphs.neo4j_compat",
        description=(
            "Neo4j-compatible typed graph projection — an operation/view role, "
            "never a semantic family."
        ),
        aliases=(
            "graph_projection",
            "knowledge_graphs",
            "knowledge_graphs.neo4j_compat",
            "knowledge_graphs_neo4j_compat",
            "knowledge_graph",
            "neo4j_compat",
        ),
        preservation_rules=(
            "endpoint_identity",
            "edge_direction",
            "edge_type",
            "provenance_identity",
        ),
        support_level=SupportLevel.TRANSLATED,
        evidence_authority=EvidenceAuthority.NONE,
        proof_authority=ProofAuthorityRole.NONE,
        result_authority_ceiling=ResultAuthority.CANDIDATE,
    ),
    _route(
        route_id="legal-route/proof-translation/v1",
        view_id="legal-ir-view/external-provers/v1",
        view_name="external_provers",
        namespace=RouteNamespace.VIEW_ROLE,
        disposition=RouteDisposition.OPERATION,
        view_role_id="proof_translation",
        target_component="external_provers.router",
        description=(
            "Bounded prover route / proof translation — an operation/view role, "
            "never a semantic family."
        ),
        aliases=(
            "proof_translation",
            "external_provers",
            "external_provers.router",
            "external_provers_router",
            "prover_router",
            "prover",
        ),
        preservation_rules=(
            "input_formula_id",
            "modal_operator",
            "type_encoding",
            "route_status",
            "trust_boundary",
        ),
        support_level=SupportLevel.TRANSLATED,
        evidence_authority=EvidenceAuthority.NONE,
        proof_authority=ProofAuthorityRole.NONE,
        result_authority_ceiling=ResultAuthority.CANDIDATE,
    ),
    _route(
        route_id="legal-route/structural-round-trip/v1",
        view_id="legal-ir-view/decompiler/v1",
        view_name="decompiler",
        namespace=RouteNamespace.VIEW_ROLE,
        disposition=RouteDisposition.OPERATION,
        view_role_id="structural_round_trip",
        target_component="modal.ir_decompiler",
        description=(
            "Deterministic structural round-trip decompiler — an operation/view "
            "role, never a semantic family."
        ),
        aliases=(
            "structural_round_trip",
            "round_trip",
            "decompiler",
            "modal.ir_decompiler",
            "modal.decompiler",
            "ir_decompiler",
        ),
        preservation_rules=(
            "formula_identity",
            "operator_force",
            "predicate_signature",
            "argument_roles",
            "condition_scope",
            "exception_scope",
        ),
        support_level=SupportLevel.TRANSLATED,
        evidence_authority=EvidenceAuthority.NONE,
        proof_authority=ProofAuthorityRole.NONE,
        result_authority_ceiling=ResultAuthority.CANDIDATE,
    ),
)


def _route_specificity(route: LegalLogicRoute) -> int:
    """Higher is more specific (profiles beat bare families; roles are exact)."""

    if route.namespace is RouteNamespace.VIEW_ROLE:
        return 30
    if route.namespace is RouteNamespace.PROFILE:
        return 20
    if route.namespace is RouteNamespace.DECLARATION_ONLY:
        return 15
    if route.namespace is RouteNamespace.FAMILY:
        return 10
    return 0


def _build_route_index(
    routes: Sequence[LegalLogicRoute],
) -> dict[str, LegalLogicRoute]:
    index: dict[str, LegalLogicRoute] = {}
    for route in routes:
        # Primary identity keys always win for this route.
        primary_keys = {
            route.route_id,
            route.view_id,
            route.view_name,
            route.profile_id,
            route.view_role_id,
            route.target_component,
            *route.aliases,
        }
        # Bare family_id is a secondary key: only claim it for the primary
        # family/declaration-only route, not every profile that reuses it.
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
            # Prefer the more specific route; never let a secondary family_id
            # key steal an alias owned by another route.
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
    while "__" in text:
        text = text.replace("__", "_")
    return text.strip("_")


LEGAL_LOGIC_ROUTE_CATALOG: Final[tuple[LegalLogicRoute, ...]] = _LEGAL_LOGIC_ROUTES
_ROUTE_BY_LABEL: Final[dict[str, LegalLogicRoute]] = _build_route_index(
    LEGAL_LOGIC_ROUTE_CATALOG
)


# ---------------------------------------------------------------------------
# Norm conflicts and ambiguity
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class NormConflict:
    """Explicit conflict between two (or more) normative claims."""

    conflict_id: str
    kind: NormConflictKind
    formula_ids: tuple[str, ...]
    description: str
    unresolved: bool = True
    priority_order: tuple[str, ...] = ()
    exception_ids: tuple[str, ...] = ()
    source_ref_ids: tuple[str, ...] = ()
    metadata: FrozenMap = field(default_factory=FrozenMap)
    schema_version: str = LEGAL_NORM_CONFLICT_SCHEMA

    def __post_init__(self) -> None:
        if not self.conflict_id:
            raise LegalTypedAdapterError(
                "conflict_id must be non-empty",
                code=CODE_MALFORMED,
                path="conflict_id",
            )
        if not isinstance(self.kind, NormConflictKind):
            object.__setattr__(self, "kind", NormConflictKind(str(self.kind)))
        if len(self.formula_ids) < 2:
            raise LegalTypedAdapterError(
                "norm conflict requires at least two formula_ids",
                code=CODE_NORM_CONFLICT,
                path="formula_ids",
            )
        if not isinstance(self.metadata, FrozenMap):
            object.__setattr__(self, "metadata", FrozenMap(dict(self.metadata or {})))

    @property
    def is_explicit(self) -> bool:
        return True

    def to_dict(self) -> dict[str, Any]:
        return {
            "conflict_id": self.conflict_id,
            "description": self.description,
            "exception_ids": list(self.exception_ids),
            "formula_ids": list(self.formula_ids),
            "is_explicit": True,
            "kind": self.kind.value,
            "metadata": self.metadata.to_dict(),
            "priority_order": list(self.priority_order),
            "schema_version": self.schema_version,
            "source_ref_ids": list(self.source_ref_ids),
            "unresolved": self.unresolved,
        }


@dataclass(frozen=True, slots=True)
class AmbiguityRecord:
    """Explicit ambiguity that must not be silently resolved."""

    ambiguity_id: str
    kind: AmbiguityKind
    description: str
    competing_interpretations: tuple[str, ...] = ()
    target_views: tuple[str, ...] = ()
    formula_ids: tuple[str, ...] = ()
    unresolved: bool = True
    proof_safe: bool = False
    learned_label_safe: bool = False
    source_ref_ids: tuple[str, ...] = ()
    metadata: FrozenMap = field(default_factory=FrozenMap)
    schema_version: str = LEGAL_AMBIGUITY_SCHEMA

    def __post_init__(self) -> None:
        if not self.ambiguity_id:
            raise LegalTypedAdapterError(
                "ambiguity_id must be non-empty",
                code=CODE_MALFORMED,
                path="ambiguity_id",
            )
        if not isinstance(self.kind, AmbiguityKind):
            object.__setattr__(self, "kind", AmbiguityKind(str(self.kind)))
        if not isinstance(self.metadata, FrozenMap):
            object.__setattr__(self, "metadata", FrozenMap(dict(self.metadata or {})))
        # Unresolved ambiguity is never proof-safe.
        if self.unresolved and self.proof_safe:
            object.__setattr__(self, "proof_safe", False)
        if self.kind is AmbiguityKind.NATURAL_LANGUAGE:
            object.__setattr__(self, "proof_safe", False)
            object.__setattr__(self, "learned_label_safe", False)

    @property
    def is_explicit(self) -> bool:
        return True

    def to_dict(self) -> dict[str, Any]:
        return {
            "ambiguity_id": self.ambiguity_id,
            "competing_interpretations": list(self.competing_interpretations),
            "description": self.description,
            "formula_ids": list(self.formula_ids),
            "is_explicit": True,
            "kind": self.kind.value,
            "learned_label_safe": self.learned_label_safe,
            "metadata": self.metadata.to_dict(),
            "proof_safe": self.proof_safe,
            "schema_version": self.schema_version,
            "source_ref_ids": list(self.source_ref_ids),
            "target_views": list(self.target_views),
            "unresolved": self.unresolved,
        }


@dataclass(frozen=True, slots=True)
class LegalRouteReceipt:
    """Receipt for a single legal view routing decision."""

    receipt_id: str
    route: LegalLogicRoute
    requested_label: str
    conflicts: tuple[NormConflict, ...] = ()
    ambiguities: tuple[AmbiguityRecord, ...] = ()
    diagnostics: tuple[str, ...] = ()
    nl_extraction: bool = False
    authority_ceiling: ResultAuthority = ResultAuthority.CANDIDATE
    schema_version: str = LEGAL_ROUTE_RECEIPT_SCHEMA

    def __post_init__(self) -> None:
        if not self.receipt_id:
            digest = stable_digest(
                {
                    "route_id": self.route.route_id,
                    "requested_label": self.requested_label,
                }
            )
            object.__setattr__(self, "receipt_id", f"receipt:legal-route:{digest[:24]}")
        if self.nl_extraction:
            # NL extraction can never raise the authority ceiling.
            object.__setattr__(self, "authority_ceiling", ResultAuthority.CANDIDATE)
        ceiling = self.route.result_authority_ceiling
        if not isinstance(self.authority_ceiling, ResultAuthority):
            object.__setattr__(
                self, "authority_ceiling", ResultAuthority(str(self.authority_ceiling))
            )
        # Receipt ceiling is the min of requested and route ceiling; never THEOREM
        # unless the route explicitly allows official proof (legal routes do not).
        if self.route.proof_authority is not ProofAuthorityRole.OFFICIAL:
            if self.authority_ceiling is ResultAuthority.THEOREM:
                object.__setattr__(self, "authority_ceiling", ceiling)

    @property
    def is_proof(self) -> bool:
        return False  # Legal typed routes never mint proof alone.

    @property
    def family_id(self) -> str:
        return self.route.family_id

    @property
    def is_operation_role(self) -> bool:
        return self.route.is_operation_role

    def to_dict(self) -> dict[str, Any]:
        return {
            "ambiguities": [item.to_dict() for item in self.ambiguities],
            "authority_ceiling": self.authority_ceiling.value,
            "conflicts": [item.to_dict() for item in self.conflicts],
            "diagnostics": list(self.diagnostics),
            "family_id": self.family_id,
            "is_operation_role": self.is_operation_role,
            "is_proof": False,
            "nl_extraction": self.nl_extraction,
            "receipt_id": self.receipt_id,
            "requested_label": self.requested_label,
            "route": self.route.to_dict(),
            "schema_version": self.schema_version,
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _as_mapping(value: Any, field_name: str) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return {str(key): item for key, item in value.items()}
    raise LegalTypedAdapterError(
        f"{field_name} must be a mapping",
        code=CODE_MALFORMED,
        path=field_name,
    )


def _as_sequence(value: Any, field_name: str) -> list[Any]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return list(value)
    raise LegalTypedAdapterError(
        f"{field_name} must be a sequence",
        code=CODE_MALFORMED,
        path=field_name,
    )


def _norm_type(value: object) -> str:
    text = str(value or "").strip().lower()
    mapping = {
        "o": "obligation",
        "obligation": "obligation",
        "shall": "obligation",
        "must": "obligation",
        "p": "permission",
        "permission": "permission",
        "may": "permission",
        "f": "prohibition",
        "prohibition": "prohibition",
        "shall_not": "prohibition",
        "must_not": "prohibition",
        "forbidden": "prohibition",
        "forbid": "prohibition",
    }
    return mapping.get(text, text)


def is_never_family_label(label: object) -> bool:
    """Return True when *label* is an operation/view role that is not a family."""

    normalized = _normalize_label(label)
    if not normalized:
        return False
    if normalized in {_normalize_label(item) for item in NEVER_FAMILY_OPERATION_ROLES}:
        return True
    route = _ROUTE_BY_LABEL.get(normalized)
    return route is not None and route.is_operation_role


def is_declaration_only_family(family_id: object) -> bool:
    """Return True when *family_id* is a sealed declaration-only family."""

    normalized = _normalize_label(family_id)
    return normalized in DECLARATION_ONLY_FAMILY_IDS or normalized in {
        _normalize_label(item) for item in DECLARATION_ONLY_FAMILY_IDS
    }


def reject_operation_role_as_family(
    label: object, *, path: str = "logic_family"
) -> None:
    """Fail closed when an operation role is claimed as a semantic family."""

    if is_never_family_label(label):
        raise OperationRoleAsFamilyError(str(label), path=path)


def reject_natural_language_proof_authority(
    source: object,
    *,
    path: str = "source",
    claimed_authority: object = None,
) -> None:
    """Fail closed when NL extraction is offered as proof authority."""

    text = source if isinstance(source, str) else str(source or "")
    lowered = text.lower()
    looks_like_nl = any(marker in lowered for marker in _NL_MARKERS)
    if isinstance(source, Mapping):
        kind = str(source.get("kind") or source.get("source_kind") or "").lower()
        extraction = str(
            source.get("extraction") or source.get("extraction_kind") or ""
        ).lower()
        if kind in {"natural_language", "nl", "nl_extraction", "free_text"}:
            looks_like_nl = True
        if extraction in {"natural_language", "nl", "llm", "heuristic"}:
            looks_like_nl = True
        if source.get("nl_extraction") is True:
            looks_like_nl = True
        claimed_authority = claimed_authority or source.get("authority") or source.get(
            "proof_authority"
        )

    authority_text = str(claimed_authority or "").strip().lower()
    claims_proof = authority_text in {
        "theorem",
        "proof",
        "official",
        "authoritative",
        "proved",
        ResultAuthority.THEOREM.value,
        ProofAuthorityRole.OFFICIAL.value,
        EvidenceAuthority.AUTHORITATIVE.value,
    }

    if looks_like_nl and claims_proof:
        raise NaturalLanguageProofAuthorityError(
            "natural-language extraction cannot establish proof authority",
            path=path,
        )
    if claims_proof and looks_like_nl is False and authority_text in {
        "nl_extraction",
        "natural_language",
    }:
        raise NaturalLanguageProofAuthorityError(path=path)


def looks_like_natural_language(source: object) -> bool:
    """Heuristic NL detection for authority gating (not a parser)."""

    if isinstance(source, Mapping):
        if source.get("nl_extraction") is True:
            return True
        kind = str(source.get("kind") or source.get("source_kind") or "").lower()
        if kind in {"natural_language", "nl", "nl_extraction", "free_text"}:
            return True
        text = str(source.get("text") or source.get("body") or "")
    else:
        text = str(source or "")
    lowered = text.lower()
    if any(marker in lowered for marker in _NL_MARKERS):
        return True
    # Controlled symbolic surfaces start with structure, not prose sentences.
    stripped = text.strip()
    if not stripped:
        return False
    if stripped[0] in "([{\\" or stripped.startswith(
        ("fof", "cnf", "tff", "thf", "(assert", "(set-logic", "forall", "exists")
    ):
        return False
    # Multiple prose sentences without symbolic operators → likely NL.
    if len(stripped) > 40 and " " in stripped and not any(
        token in stripped for token in ("(", ")", ":-", "->", "=>", "∧", "∨", "∀", "∃")
    ):
        if stripped[0].isalpha() and stripped.rstrip().endswith((".", "?", "!")):
            return True
    return False


def resolve_legal_route(label: object) -> LegalLogicRoute:
    """Resolve a legal view name, contract id, alias, or family label."""

    if isinstance(label, LegalLogicRoute):
        return label
    raw = str(label or "").strip()
    if not raw:
        raise LegalTypedAdapterError(
            "route label must be a non-empty string",
            code=CODE_UNKNOWN_VIEW,
            path="label",
        )
    normalized = _normalize_label(raw)
    route = _ROUTE_BY_LABEL.get(normalized)
    if route is not None:
        return route
    # Reject operation roles even when not in the catalog under a free spelling.
    if normalized in {_normalize_label(item) for item in NEVER_FAMILY_OPERATION_ROLES}:
        raise OperationRoleAsFamilyError(raw)
    raise LegalTypedAdapterError(
        f"unknown legal logic route label {raw!r}",
        code=CODE_UNKNOWN_VIEW,
        path="label",
    )


def detect_norm_conflicts(
    formulas: Sequence[Mapping[str, Any]] | Sequence[Any],
) -> tuple[NormConflict, ...]:
    """Detect explicit norm conflicts from typed formula projections.

    Conflicts are never silently dropped: every detected collision becomes an
    explicit :class:`NormConflict` record with ``unresolved=True`` unless a
    priority or exception ordering is present.
    """

    items: list[dict[str, Any]] = []
    for index, raw in enumerate(formulas):
        if isinstance(raw, Mapping):
            data = {str(k): v for k, v in raw.items()}
        else:
            data = {
                "formula_id": getattr(raw, "formula_id", f"formula:{index}"),
                "norm_type": getattr(raw, "norm_type", None)
                or getattr(raw, "force", None),
                "operator": getattr(raw, "operator", None),
                "actor": getattr(raw, "actor", None),
                "action": getattr(raw, "action", None),
                "object": getattr(raw, "object", None),
                "conditions": getattr(raw, "conditions", ()),
                "exceptions": getattr(raw, "exceptions", ()),
                "priority": getattr(raw, "priority", None),
            }
        formula_id = str(data.get("formula_id") or f"formula:{index}")
        norm = _norm_type(
            data.get("norm_type")
            or (
                data.get("operator", {}).get("symbol")
                if isinstance(data.get("operator"), Mapping)
                else data.get("operator")
            )
        )
        items.append(
            {
                "formula_id": formula_id,
                "norm_type": norm,
                "actor": str(data.get("actor") or ""),
                "action": str(data.get("action") or ""),
                "object": str(data.get("object") or data.get("governed_object") or ""),
                "conditions": tuple(
                    str(c) for c in (data.get("conditions") or ()) if c is not None
                ),
                "exceptions": tuple(
                    str(e) for e in (data.get("exceptions") or ()) if e is not None
                ),
                "priority": data.get("priority"),
            }
        )

    conflicts: list[NormConflict] = []
    for i, left in enumerate(items):
        for right in items[i + 1 :]:
            same_subject = (
                left["actor"]
                and left["actor"] == right["actor"]
                and left["action"]
                and left["action"] == right["action"]
            )
            if not same_subject:
                continue
            pair = {left["norm_type"], right["norm_type"]}
            kind: NormConflictKind | None = None
            if pair == {"obligation", "prohibition"}:
                kind = NormConflictKind.OBLIGATION_PROHIBITION
            elif pair == {"permission", "prohibition"}:
                kind = NormConflictKind.PERMISSION_PROHIBITION
            elif (
                left["norm_type"]
                and left["norm_type"] == right["norm_type"]
                and left["conditions"] != right["conditions"]
                and left["conditions"]
                and right["conditions"]
            ):
                kind = NormConflictKind.CONDITIONAL_INCOMPATIBILITY
            elif left["exceptions"] and right["exceptions"]:
                shared = set(left["exceptions"]) & set(right["exceptions"])
                if shared and left["norm_type"] != right["norm_type"]:
                    kind = NormConflictKind.EXCEPTION_SCOPE_OVERLAP
            if kind is None:
                # Priority collision: same subject, conflicting priorities.
                if (
                    left["priority"] is not None
                    and right["priority"] is not None
                    and left["priority"] == right["priority"]
                    and left["norm_type"] != right["norm_type"]
                ):
                    kind = NormConflictKind.PRIORITY_COLLISION
            if kind is None:
                continue
            formula_ids = (left["formula_id"], right["formula_id"])
            has_priority = bool(
                left.get("priority") is not None or right.get("priority") is not None
            )
            has_exceptions = bool(left["exceptions"] or right["exceptions"])
            unresolved = not (has_priority or has_exceptions)
            priority_order: tuple[str, ...] = ()
            if has_priority:
                ordered = sorted(
                    (left, right),
                    key=lambda item: (
                        item["priority"] is None,
                        item["priority"] if item["priority"] is not None else 0,
                    ),
                )
                priority_order = tuple(item["formula_id"] for item in ordered)
            conflict_id = (
                f"conflict:{kind.value}:"
                f"{stable_digest({'ids': list(formula_ids)})[:16]}"
            )
            conflicts.append(
                NormConflict(
                    conflict_id=conflict_id,
                    kind=kind,
                    formula_ids=formula_ids,
                    description=(
                        f"{kind.value} between {formula_ids[0]!r} and {formula_ids[1]!r} "
                        f"on actor={left['actor']!r} action={left['action']!r}"
                    ),
                    unresolved=unresolved,
                    priority_order=priority_order,
                    exception_ids=tuple(
                        dict.fromkeys([*left["exceptions"], *right["exceptions"]])
                    ),
                )
            )
    return tuple(conflicts)


def record_ambiguity(
    *,
    kind: AmbiguityKind | str,
    description: str,
    competing_interpretations: Sequence[str] = (),
    target_views: Sequence[str] = (),
    formula_ids: Sequence[str] = (),
    unresolved: bool = True,
    source_ref_ids: Sequence[str] = (),
    ambiguity_id: str = "",
    metadata: Mapping[str, Any] | None = None,
) -> AmbiguityRecord:
    """Build an explicit ambiguity record (never silently dropped)."""

    kind_enum = kind if isinstance(kind, AmbiguityKind) else AmbiguityKind(str(kind))
    if not ambiguity_id:
        ambiguity_id = (
            f"ambiguity:{kind_enum.value}:"
            f"{stable_digest({'description': description, 'views': list(target_views)})[:16]}"
        )
    return AmbiguityRecord(
        ambiguity_id=ambiguity_id,
        kind=kind_enum,
        description=description,
        competing_interpretations=tuple(str(item) for item in competing_interpretations),
        target_views=tuple(str(item) for item in target_views),
        formula_ids=tuple(str(item) for item in formula_ids),
        unresolved=unresolved,
        proof_safe=False if unresolved else False,
        learned_label_safe=False if unresolved else False,
        source_ref_ids=tuple(str(item) for item in source_ref_ids),
        metadata=FrozenMap(dict(metadata or {})),
    )


def enforce_authority_ceiling(
    route: LegalLogicRoute,
    claimed: ResultAuthority | str | None,
    *,
    nl_extraction: bool = False,
) -> ResultAuthority:
    """Clamp or reject authority claims that exceed the route ceiling."""

    if claimed is None:
        claimed_auth = route.result_authority_ceiling
    elif isinstance(claimed, ResultAuthority):
        claimed_auth = claimed
    else:
        try:
            claimed_auth = ResultAuthority(str(claimed))
        except (TypeError, ValueError) as exc:
            raise LegalTypedAdapterError(
                f"unknown result authority {claimed!r}",
                code=CODE_MALFORMED,
                path="authority",
            ) from exc

    if nl_extraction:
        if claimed_auth is ResultAuthority.THEOREM:
            raise NaturalLanguageProofAuthorityError(
                "natural-language extraction cannot claim theorem authority",
                path="authority",
            )
        return ResultAuthority.CANDIDATE

    if route.is_operation_role and claimed_auth is ResultAuthority.THEOREM:
        raise AuthorityPromotionError(
            f"operation role {route.view_role_id!r} cannot claim theorem authority"
        )

    if route.is_declaration_only and claimed_auth is ResultAuthority.THEOREM:
        raise AuthorityPromotionError(
            f"declaration-only family {route.family_id!r} cannot claim theorem authority"
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


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LegalFormalizationAdapter:
    """Route legal_ir views onto canonical families, profiles, and view roles.

    Interface: ``LegalFormalizationAdapter@2``.
    """

    INTERFACE: ClassVar[str] = LEGAL_FORMALIZATION_ADAPTER_INTERFACE
    VERSION: ClassVar[str] = LEGAL_FORMALIZATION_ADAPTER_VERSION

    producer_id: str = LEGAL_IR_TYPED_ADAPTER_PRODUCER_ID
    domain: str = LEGAL_IR_TYPED_DOMAIN

    def __post_init__(self) -> None:
        if not _ID_RE.fullmatch(self.producer_id):
            raise LegalTypedAdapterError(
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
        return tuple(route.route_id for route in LEGAL_LOGIC_ROUTE_CATALOG)

    def routes(self) -> tuple[LegalLogicRoute, ...]:
        return LEGAL_LOGIC_ROUTE_CATALOG

    def typed_family_routes(self) -> tuple[LegalLogicRoute, ...]:
        return tuple(
            route
            for route in LEGAL_LOGIC_ROUTE_CATALOG
            if route.is_semantic_family
        )

    def operation_role_routes(self) -> tuple[LegalLogicRoute, ...]:
        return tuple(
            route for route in LEGAL_LOGIC_ROUTE_CATALOG if route.is_operation_role
        )

    def declaration_only_routes(self) -> tuple[LegalLogicRoute, ...]:
        return tuple(
            route for route in LEGAL_LOGIC_ROUTE_CATALOG if route.is_declaration_only
        )

    def resolve(self, label: object) -> LegalLogicRoute:
        return resolve_legal_route(label)

    def route_view(
        self,
        label: object,
        *,
        formulas: Sequence[Mapping[str, Any]] | Sequence[Any] = (),
        ambiguities: Sequence[AmbiguityRecord | Mapping[str, Any]] = (),
        nl_extraction: bool = False,
        source: object = None,
        claimed_authority: object = None,
    ) -> LegalRouteReceipt:
        """Route a legal view label and attach explicit conflict/ambiguity state."""

        route = resolve_legal_route(label)
        # Operation roles are valid routes; they simply never populate family_id.
        assert not (
            route.is_operation_role and route.family_id
        ), "invariant: operation roles never carry a family_id"

        if source is not None:
            reject_natural_language_proof_authority(
                source,
                claimed_authority=claimed_authority,
            )
            if looks_like_natural_language(source):
                nl_extraction = True

        if nl_extraction:
            reject_natural_language_proof_authority(
                {"nl_extraction": True, "authority": claimed_authority or "candidate"},
                claimed_authority=claimed_authority,
            )

        ceiling = enforce_authority_ceiling(
            route,
            claimed_authority if claimed_authority is not None else None,
            nl_extraction=nl_extraction,
        )

        conflicts = detect_norm_conflicts(formulas) if formulas else ()
        ambiguity_records: list[AmbiguityRecord] = []
        for item in ambiguities:
            if isinstance(item, AmbiguityRecord):
                ambiguity_records.append(item)
            elif isinstance(item, Mapping):
                ambiguity_records.append(
                    record_ambiguity(
                        kind=str(item.get("kind") or AmbiguityKind.COMPETING_PARSES.value),
                        description=str(item.get("description") or "unspecified ambiguity"),
                        competing_interpretations=tuple(
                            item.get("competing_interpretations") or ()
                        ),
                        target_views=tuple(item.get("target_views") or ()),
                        formula_ids=tuple(item.get("formula_ids") or ()),
                        unresolved=bool(item.get("unresolved", True)),
                        source_ref_ids=tuple(item.get("source_ref_ids") or ()),
                        ambiguity_id=str(item.get("ambiguity_id") or ""),
                        metadata=dict(item.get("metadata") or {}),
                    )
                )
            else:
                raise LegalTypedAdapterError(
                    "ambiguities must be AmbiguityRecord or mappings",
                    code=CODE_MALFORMED,
                    path="ambiguities",
                )

        diagnostics: list[str] = []
        if route.is_declaration_only:
            diagnostics.append(CODE_DECLARATION_ONLY)
        if route.is_operation_role:
            diagnostics.append("legal.operation_role_not_family")
        if conflicts:
            diagnostics.append(CODE_NORM_CONFLICT)
        if ambiguity_records:
            diagnostics.append(CODE_AMBIGUITY)
        if nl_extraction:
            diagnostics.append(CODE_NL_PROOF_AUTHORITY)

        return LegalRouteReceipt(
            receipt_id="",
            route=route,
            requested_label=str(label),
            conflicts=conflicts,
            ambiguities=tuple(ambiguity_records),
            diagnostics=tuple(diagnostics),
            nl_extraction=nl_extraction,
            authority_ceiling=ceiling,
        )

    def argumentation_disposition(self) -> LegalLogicRoute:
        """Return the explicit declaration-only argumentation route."""

        return resolve_legal_route("argumentation")

    def assert_operations_are_not_families(
        self, labels: Iterable[object] | None = None
    ) -> None:
        """Fail closed if any operation-role label is claimed as a family."""

        if labels is None:
            labels = (
                "graph_projection",
                "proof_translation",
                "structural_round_trip",
            )
        for label in labels:
            reject_operation_role_as_family(label)

    def catalog_manifest(self) -> dict[str, Any]:
        """Serializable route catalog for matrix / audit consumers."""

        return {
            "adapter_version": self.VERSION,
            "declaration_only_route_ids": [
                route.route_id for route in self.declaration_only_routes()
            ],
            "domain": self.domain,
            "interface": self.INTERFACE,
            "never_family_operation_roles": sorted(NEVER_FAMILY_OPERATION_ROLES),
            "operation_role_route_ids": [
                route.route_id for route in self.operation_role_routes()
            ],
            "producer_id": self.producer_id,
            "routes": [route.to_dict() for route in self.routes()],
            "typed_family_route_ids": [
                route.route_id for route in self.typed_family_routes()
            ],
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "domain": self.domain,
            "interface": self.INTERFACE,
            "module_version": LEGAL_TYPED_ADAPTER_MODULE_VERSION,
            "producer_id": self.producer_id,
            "version": self.VERSION,
        }


# Short migration aliases.
LegalTypedAdapter = LegalFormalizationAdapter
LegalIRTypedAdapter = LegalFormalizationAdapter


def route_legal_view(
    label: object,
    **kwargs: Any,
) -> LegalRouteReceipt:
    """Module-level convenience wrapper around :meth:`LegalFormalizationAdapter.route_view`."""

    return LegalFormalizationAdapter().route_view(label, **kwargs)


def legal_logic_routes() -> tuple[LegalLogicRoute, ...]:
    """Return the sealed legal logic route catalog."""

    return LEGAL_LOGIC_ROUTE_CATALOG


__all__ = [
    "LEGAL_AMBIGUITY_SCHEMA",
    "LEGAL_FORMALIZATION_ADAPTER_INTERFACE",
    "LEGAL_FORMALIZATION_ADAPTER_VERSION",
    "LEGAL_IR_TYPED_ADAPTER_PRODUCER_ID",
    "LEGAL_IR_TYPED_DOMAIN",
    "LEGAL_LOGIC_ROUTE_CATALOG",
    "LEGAL_LOGIC_ROUTE_SCHEMA",
    "LEGAL_NORM_CONFLICT_SCHEMA",
    "LEGAL_ROUTE_RECEIPT_SCHEMA",
    "LEGAL_TYPED_ADAPTER_MODULE_VERSION",
    "NEVER_FAMILY_OPERATION_ROLES",
    "AmbiguityKind",
    "AmbiguityRecord",
    "AuthorityPromotionError",
    "FreeFormFamilyError",
    "LegalFormalizationAdapter",
    "LegalIRTypedAdapter",
    "LegalLogicRoute",
    "LegalRouteReceipt",
    "LegalTypedAdapter",
    "LegalTypedAdapterError",
    "NaturalLanguageProofAuthorityError",
    "NormConflict",
    "NormConflictKind",
    "OperationRoleAsFamilyError",
    "ProofAuthorityRole",
    "RouteDisposition",
    "RouteNamespace",
    "detect_norm_conflicts",
    "enforce_authority_ceiling",
    "is_declaration_only_family",
    "is_never_family_label",
    "legal_logic_routes",
    "looks_like_natural_language",
    "record_ambiguity",
    "reject_natural_language_proof_authority",
    "reject_operation_role_as_family",
    "resolve_legal_route",
    "route_legal_view",
]
