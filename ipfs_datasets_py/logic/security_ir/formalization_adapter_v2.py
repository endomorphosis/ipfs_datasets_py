"""Typed Security IR formalization routes to canonical logic (LFP-034).

Interface: ``SecurityFormalizationAdapter@2``

Migrates security_ir multi-view labels onto sealed family / profile / property /
view-role namespaces:

* Threat models → ``transition_system`` (profile ``threat_model``)
* Authorization / SecPAL / policy → ``authorization`` (profile ``secpal``) and
  deontic authorization-policy profile
* Verification conditions / claims → ``first_order`` / ``horn_chc`` profiles;
  ``verification_condition`` itself is an obligation/view role, never a family
* State machines → ``transition_system``
* Temporal properties → ``temporal`` (profile ``ltl``)
* Protocols → ``cryptographic_protocol``
* Noninterference → property/profile under ``hyperproperty``
* Separation / concurrency → ``separation_logic`` / ``concurrency``

Authority rules (fail-closed):

* Every admitted view must parse and elaborate **before** lowering.
* Unsupported cells are explicit records, never silent success.
* Proof / model-check / monitor authority is bounded by translation receipts
  and backend receipts; routes alone never mint theorem authority.
* Dual-read with :mod:`.formalization_adapter` (v1); this module is the typed
  route surface for the migration.
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
    FOUNDATION_FAMILY_IDS,
)
from ipfs_datasets_py.logic.ir_core.claims import FrozenMap, stable_digest


# ---------------------------------------------------------------------------
# Interface / schema identities
# ---------------------------------------------------------------------------

SECURITY_FORMALIZATION_ADAPTER_INTERFACE: Final = "SecurityFormalizationAdapter@2"
SECURITY_FORMALIZATION_ADAPTER_VERSION: Final = "2.0.0"
SECURITY_LOGIC_ROUTE_SCHEMA: Final = "security-logic-route/v1"
SECURITY_ROUTE_RECEIPT_SCHEMA: Final = "security-logic-route-receipt/v1"
SECURITY_PARSE_ELABORATE_SCHEMA: Final = "security-parse-elaborate-receipt/v1"
SECURITY_TRANSLATION_RECEIPT_SCHEMA: Final = "security-translation-receipt/v1"
SECURITY_BACKEND_RECEIPT_SCHEMA: Final = "security-backend-receipt/v1"
SECURITY_UNSUPPORTED_CELL_SCHEMA: Final = "security-unsupported-cell/v1"
SECURITY_TYPED_ADAPTER_MODULE_VERSION: Final = "1.0.0"

SECURITY_IR_TYPED_ADAPTER_PRODUCER_ID: Final = "security-ir-typed-adapter"
SECURITY_IR_TYPED_DOMAIN: Final = "security"
SECURITY_IR_DOMAIN_ID: Final = "security_ir"

# Stable diagnostic codes.
CODE_UNKNOWN_VIEW: Final = "security.unknown_view"
CODE_OPERATION_AS_FAMILY: Final = "security.operation_role_as_family"
CODE_PROPERTY_AS_FAMILY: Final = "security.property_as_family"
CODE_UNSUPPORTED: Final = "security.unsupported"
CODE_UNSUPPORTED_CELL: Final = "security.unsupported_cell"
CODE_PARSE_REQUIRED: Final = "security.parse_elaborate_required"
CODE_PARSE_FAILED: Final = "security.parse_elaborate_failed"
CODE_LOWER_BEFORE_PARSE: Final = "security.lower_before_parse_rejected"
CODE_AUTHORITY_PROMOTION: Final = "security.authority_promotion_rejected"
CODE_AUTHORITY_BOUND: Final = "security.authority_bounded_by_receipts"
CODE_FREE_FORM_FAMILY: Final = "security.free_form_family"
CODE_MALFORMED: Final = "security.malformed_input"
CODE_ROUTE: Final = "security.route_error"
CODE_LEGACY_ALIAS: Final = "security.legacy_alias"
CODE_BACKEND_MISSING: Final = "security.backend_receipt_required"
CODE_TRANSLATION_MISSING: Final = "security.translation_receipt_required"

_ALL_CODES: Final[frozenset[str]] = frozenset(
    {
        CODE_UNKNOWN_VIEW,
        CODE_OPERATION_AS_FAMILY,
        CODE_PROPERTY_AS_FAMILY,
        CODE_UNSUPPORTED,
        CODE_UNSUPPORTED_CELL,
        CODE_PARSE_REQUIRED,
        CODE_PARSE_FAILED,
        CODE_LOWER_BEFORE_PARSE,
        CODE_AUTHORITY_PROMOTION,
        CODE_AUTHORITY_BOUND,
        CODE_FREE_FORM_FAMILY,
        CODE_MALFORMED,
        CODE_ROUTE,
        CODE_LEGACY_ALIAS,
        CODE_BACKEND_MISSING,
        CODE_TRANSLATION_MISSING,
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
        "noninterference",
        "information_flow",
        "validity",
        "secrecy",
        "authentication",
    }
)

# Evidence-subset backend identifiers from LFP-034.
SECURITY_EVIDENCE_BACKENDS: Final[tuple[str, ...]] = (
    "z3",
    "cvc5",
    "tla_tlc",
    "apalache",
    "datalog_secpal",
    "proverif",
    "tamarin",
    "hyperltl_autohyper_mchyper",
    "vampire",
    "eprover",
    "lean",
    "rocq",
    "isabelle",
    "runtime_mtl",
)

# Wave-4 / future families that must never be implied by security routes.
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

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class RouteNamespace(StrEnum):
    """Namespace role of a security logic route target."""

    FAMILY = "family"
    PROFILE = "profile"
    PROPERTY = "property"
    VIEW_ROLE = "view_role"
    DECLARATION_ONLY = "declaration_only"


class RouteDisposition(StrEnum):
    """How a security view is admitted into the typed matrix."""

    NATIVE = "native"
    TYPED = "typed"
    DECLARATION_ONLY = "declaration_only"
    UNSUPPORTED = "unsupported"
    BOUNDED = "bounded"
    ADVISORY = "advisory"
    OPERATION = "operation"
    PROPERTY = "property"


class ProofAuthorityRole(StrEnum):
    """What a route may claim about proof without backend/kernel receipts."""

    NONE = "none"
    CANDIDATE = "candidate"
    DECLARATION = "declaration"
    BOUNDED = "bounded"
    ADVISORY = "advisory"
    # Kernel/backend only — never assigned by the route catalog alone.
    OFFICIAL = "official"


class AuthorityLane(StrEnum):
    """Closed authority lanes for proof / model / monitor bounding."""

    PROOF = "proof"
    MODEL = "model"
    MONITOR = "monitor"
    AUTHORIZATION = "authorization"
    PROTOCOL = "protocol"
    HYPERPROPERTY = "hyperproperty"
    CANDIDATE = "candidate"
    NONE = "none"


class ParseElaborateStage(StrEnum):
    """Stages of the mandatory parse → elaborate → lower pipeline."""

    ADMITTED = "admitted"
    PARSED = "parsed"
    ELABORATED = "elaborated"
    READY_TO_LOWER = "ready_to_lower"
    LOWERED = "lowered"
    REJECTED = "rejected"


class UnsupportedCellKind(StrEnum):
    """Closed set of explicit unsupported-cell classifications."""

    FUTURE_FAMILY = "future_family"
    MISSING_FRONTEND = "missing_frontend"
    MISSING_BACKEND = "missing_backend"
    MISSING_PROFILE = "missing_profile"
    PROPERTY_WITHOUT_FAMILY = "property_without_family"
    OPERATION_AS_FAMILY = "operation_as_family"
    FREE_FORM_LABEL = "free_form_label"
    LEGACY_UNMAPPED = "legacy_unmapped"
    AUTHORITY_UNAVAILABLE = "authority_unavailable"
    UNSPECIFIED = "unspecified"


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class SecurityTypedAdapterError(ValueError):
    """Raised when a security typed route request is invalid."""

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


class OperationRoleAsFamilyError(SecurityTypedAdapterError):
    """Raised when an operation/view role is offered as a semantic family."""

    def __init__(self, label: str, *, path: str = "logic_family") -> None:
        super().__init__(
            f"operation/view role {label!r} must never route as a semantic family",
            code=CODE_OPERATION_AS_FAMILY,
            path=path,
        )
        self.label = label


class PropertyAsFamilyError(SecurityTypedAdapterError):
    """Raised when a property kind is offered as a semantic family."""

    def __init__(self, label: str, *, path: str = "logic_family") -> None:
        super().__init__(
            f"property kind {label!r} must never route as a semantic family",
            code=CODE_PROPERTY_AS_FAMILY,
            path=path,
        )
        self.label = label


class AuthorityPromotionError(SecurityTypedAdapterError):
    """Raised when a route attempts to exceed its declared authority ceiling."""

    def __init__(self, message: str, *, path: str = "authority") -> None:
        super().__init__(message, code=CODE_AUTHORITY_PROMOTION, path=path)


class ParseElaborateRequiredError(SecurityTypedAdapterError):
    """Raised when lowering is attempted without a successful parse/elaborate."""

    def __init__(self, message: str = "", *, path: str = "pipeline") -> None:
        super().__init__(
            message
            or "admitted security views must parse and elaborate before lowering",
            code=CODE_LOWER_BEFORE_PARSE,
            path=path,
        )


class FreeFormFamilyError(SecurityTypedAdapterError):
    """Raised when free-form family labels are offered as typed inputs."""

    def __init__(self, label: str, *, path: str = "logic_family") -> None:
        super().__init__(
            f"free-form family label {label!r} is rejected; use a canonical family",
            code=CODE_FREE_FORM_FAMILY,
            path=path,
        )
        self.label = label


class UnsupportedCellError(SecurityTypedAdapterError):
    """Raised when an explicit unsupported cell is treated as admitted support."""

    def __init__(self, message: str, *, path: str = "cell") -> None:
        super().__init__(message, code=CODE_UNSUPPORTED_CELL, path=path)


# ---------------------------------------------------------------------------
# Route catalog records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SecurityLogicRoute:
    """One typed security view → canonical namespace route."""

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
    requires_parse_elaborate: bool = True
    schema_version: str = SECURITY_LOGIC_ROUTE_SCHEMA

    def __post_init__(self) -> None:
        if not self.route_id or not _ID_RE.fullmatch(self.route_id):
            raise SecurityTypedAdapterError(
                f"route_id must be a stable identifier; got {self.route_id!r}",
                code=CODE_MALFORMED,
                path="route_id",
            )
        if not self.view_id or not _ID_RE.fullmatch(self.view_id):
            raise SecurityTypedAdapterError(
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
                raise SecurityTypedAdapterError(
                    f"view-role route {self.route_id!r} requires view_role_id",
                    code=CODE_MALFORMED,
                    path="view_role_id",
                )
            if self.family_id:
                raise SecurityTypedAdapterError(
                    f"view-role route {self.route_id!r} must not set family_id "
                    f"(got {self.family_id!r}); operation roles are not families",
                    code=CODE_OPERATION_AS_FAMILY,
                    path="family_id",
                )
            if self.disposition is not RouteDisposition.OPERATION:
                raise SecurityTypedAdapterError(
                    f"view-role route {self.route_id!r} must have operation disposition",
                    code=CODE_MALFORMED,
                    path="disposition",
                )
            if self.proof_authority is ProofAuthorityRole.OFFICIAL:
                raise SecurityTypedAdapterError(
                    f"view-role route {self.route_id!r} cannot claim official proof",
                    code=CODE_AUTHORITY_PROMOTION,
                    path="proof_authority",
                )
            return

        if self.namespace is RouteNamespace.PROPERTY:
            if not self.property_id:
                raise SecurityTypedAdapterError(
                    f"property route {self.route_id!r} requires property_id",
                    code=CODE_MALFORMED,
                    path="property_id",
                )
            if self.property_id in NEVER_FAMILY_OPERATION_ROLES:
                raise OperationRoleAsFamilyError(self.property_id)
            # Property routes may name a host family (e.g. hyperproperty) but
            # the property_id itself is never a family id.
            if self.property_id in FOUNDATION_FAMILY_IDS:
                raise PropertyAsFamilyError(self.property_id)
            if self.disposition not in {
                RouteDisposition.PROPERTY,
                RouteDisposition.TYPED,
                RouteDisposition.BOUNDED,
            }:
                raise SecurityTypedAdapterError(
                    f"property route {self.route_id!r} has invalid disposition",
                    code=CODE_MALFORMED,
                    path="disposition",
                )
            if self.proof_authority is ProofAuthorityRole.OFFICIAL:
                raise SecurityTypedAdapterError(
                    f"property route {self.route_id!r} cannot claim official proof",
                    code=CODE_AUTHORITY_PROMOTION,
                    path="proof_authority",
                )
            return

        if self.namespace is RouteNamespace.FAMILY:
            if not self.family_id:
                raise SecurityTypedAdapterError(
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
                raise SecurityTypedAdapterError(
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
                raise SecurityTypedAdapterError(
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
                raise SecurityTypedAdapterError(
                    f"declaration-only route {self.route_id!r} has invalid disposition",
                    code=CODE_MALFORMED,
                    path="disposition",
                )
            if self.proof_authority is ProofAuthorityRole.OFFICIAL:
                raise SecurityTypedAdapterError(
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
            "proof_authority": self.proof_authority.value,
            "property_id": self.property_id,
            "requires_parse_elaborate": self.requires_parse_elaborate,
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
    requires_parse_elaborate: bool = True,
) -> SecurityLogicRoute:
    return SecurityLogicRoute(
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
        requires_parse_elaborate=requires_parse_elaborate,
    )


# Canonical security view routes aligned with the capability matrix.
_SECURITY_LOGIC_ROUTES: Final[tuple[SecurityLogicRoute, ...]] = (
    # --- Threat model -------------------------------------------------------
    _route(
        route_id="security-route/threat/v1",
        view_id="security-ir-view/threat/v1",
        view_name="threat",
        namespace=RouteNamespace.PROFILE,
        disposition=RouteDisposition.TYPED,
        family_id="transition_system",
        profile_id="threat_model",
        target_component="security.threat_model",
        description="Threat-model transition obligations from Security IR.",
        aliases=(
            "threat",
            "threat_model",
            "threat-model",
            "security-ir-view/threat/v1",
        ),
        preservation_rules=(
            "attacker_identity",
            "assumption_polarity",
            "environment_boundary",
            "source_grounding",
        ),
        backend_ids=("tla_tlc", "apalache", "z3"),
        authority_lane=AuthorityLane.MODEL,
        support_level=SupportLevel.NATIVE,
        evidence_authority=EvidenceAuthority.BOUNDED,
        proof_authority=ProofAuthorityRole.BOUNDED,
        result_authority_ceiling=ResultAuthority.MODEL_CHECK,
    ),
    # --- Authorization / policy ---------------------------------------------
    _route(
        route_id="security-route/authorization/v1",
        view_id="security-ir-view/policy/v1",
        view_name="authorization",
        namespace=RouteNamespace.PROFILE,
        disposition=RouteDisposition.TYPED,
        family_id="authorization",
        profile_id="secpal",
        target_component="authorization.secpal",
        description="SecPAL/Datalog authorization projection of Security IR policy.",
        aliases=(
            "authorization",
            "secpal",
            "datalog_secpal",
            "policy_authorization",
            "security-ir-view/policy/v1",
        ),
        preservation_rules=(
            "principal_identity",
            "action_identity",
            "effect_polarity",
            "delegation_scope",
            "world_policy",
        ),
        backend_ids=("datalog_secpal", "z3"),
        authority_lane=AuthorityLane.AUTHORIZATION,
        support_level=SupportLevel.NATIVE,
        evidence_authority=EvidenceAuthority.INDEPENDENTLY_CHECKABLE,
        proof_authority=ProofAuthorityRole.BOUNDED,
        result_authority_ceiling=ResultAuthority.AUTHORIZATION,
    ),
    _route(
        route_id="security-route/policy-deontic/v1",
        view_id="security-ir-view/policy/v1",
        view_name="policy",
        namespace=RouteNamespace.PROFILE,
        disposition=RouteDisposition.TYPED,
        family_id="deontic",
        profile_id="authorization_policy",
        target_component="security.policy",
        description="Policy and authorization norms from Security IR.",
        aliases=(
            "policy",
            "authorization_policy",
            "deontic_policy",
            "allow_deny",
        ),
        preservation_rules=(
            "operator_force",
            "effect_polarity",
            "principal_identity",
            "action_identity",
        ),
        backend_ids=("datalog_secpal", "z3", "cvc5"),
        authority_lane=AuthorityLane.AUTHORIZATION,
        support_level=SupportLevel.NATIVE,
        evidence_authority=EvidenceAuthority.INDEPENDENTLY_CHECKABLE,
        proof_authority=ProofAuthorityRole.BOUNDED,
        result_authority_ceiling=ResultAuthority.AUTHORIZATION,
    ),
    # --- State / transition -------------------------------------------------
    _route(
        route_id="security-route/transition/v1",
        view_id="security-ir-view/transition/v1",
        view_name="state",
        namespace=RouteNamespace.FAMILY,
        disposition=RouteDisposition.TYPED,
        family_id="transition_system",
        profile_id="default",
        target_component="security.transition",
        description="State-transition formalization of Security IR.",
        aliases=(
            "state",
            "transition",
            "state_machine",
            "state_transition",
            "transition_system",
            "security-ir-view/transition/v1",
        ),
        preservation_rules=(
            "state_identity",
            "transition_direction",
            "guard_polarity",
            "source_grounding",
        ),
        backend_ids=("tla_tlc", "apalache", "z3"),
        authority_lane=AuthorityLane.MODEL,
        support_level=SupportLevel.NATIVE,
        evidence_authority=EvidenceAuthority.BOUNDED,
        proof_authority=ProofAuthorityRole.BOUNDED,
        result_authority_ceiling=ResultAuthority.MODEL_CHECK,
    ),
    # --- Temporal -----------------------------------------------------------
    _route(
        route_id="security-route/temporal/v1",
        view_id="security-ir-view/transition/v1",
        view_name="temporal",
        namespace=RouteNamespace.PROFILE,
        disposition=RouteDisposition.TYPED,
        family_id="temporal",
        profile_id="ltl",
        target_component="security.temporal",
        description="Temporal threat/transition properties for Security IR.",
        aliases=(
            "temporal",
            "ltl",
            "temporal_property",
            "tla_plus",
        ),
        preservation_rules=(
            "temporal_operator",
            "trace_model",
            "fairness_constraint",
            "bound_depth",
        ),
        backend_ids=("tla_tlc", "apalache", "runtime_mtl"),
        authority_lane=AuthorityLane.MODEL,
        support_level=SupportLevel.NATIVE,
        evidence_authority=EvidenceAuthority.BOUNDED,
        proof_authority=ProofAuthorityRole.BOUNDED,
        result_authority_ceiling=ResultAuthority.MODEL_CHECK,
    ),
    # --- Verification conditions / claims -----------------------------------
    _route(
        route_id="security-route/claim-fol/v1",
        view_id="security-ir-view/claim/v1",
        view_name="claim",
        namespace=RouteNamespace.PROFILE,
        disposition=RouteDisposition.TYPED,
        family_id="first_order",
        profile_id="verification_condition",
        target_component="security.claim",
        description="Verification-condition claims from Security IR (FOL).",
        aliases=(
            "claim",
            "vc",
            "verification_conditions",
            "smt",
            "smt_lib",
            "smtlib2",
            "fol",
            "first_order",
            "security-ir-view/claim/v1",
        ),
        preservation_rules=(
            "quantifier_scope",
            "predicate_signature",
            "polarity",
            "obligation_identity",
        ),
        backend_ids=("z3", "cvc5", "vampire", "eprover", "lean", "rocq", "isabelle"),
        authority_lane=AuthorityLane.PROOF,
        support_level=SupportLevel.NATIVE,
        evidence_authority=EvidenceAuthority.INDEPENDENTLY_CHECKABLE,
        proof_authority=ProofAuthorityRole.CANDIDATE,
        result_authority_ceiling=ResultAuthority.SATISFIABILITY,
    ),
    _route(
        route_id="security-route/claim-chc/v1",
        view_id="security-ir-view/claim/v1",
        view_name="chc_vc",
        namespace=RouteNamespace.PROFILE,
        disposition=RouteDisposition.TYPED,
        family_id="horn_chc",
        profile_id="chc_vc",
        target_component="security.claim.chc",
        description="CHC-style verification conditions for Security IR claims.",
        aliases=(
            "chc",
            "chc_vc",
            "horn_chc",
            "horn",
        ),
        preservation_rules=(
            "horn_clause_shape",
            "predicate_signature",
            "obligation_identity",
        ),
        backend_ids=("z3", "cvc5"),
        authority_lane=AuthorityLane.PROOF,
        support_level=SupportLevel.NATIVE,
        evidence_authority=EvidenceAuthority.INDEPENDENTLY_CHECKABLE,
        proof_authority=ProofAuthorityRole.CANDIDATE,
        result_authority_ceiling=ResultAuthority.SATISFIABILITY,
    ),
    # --- Protocol -----------------------------------------------------------
    _route(
        route_id="security-route/protocol/v1",
        view_id="security-ir-view/protocol/v1",
        view_name="protocol",
        namespace=RouteNamespace.FAMILY,
        disposition=RouteDisposition.TYPED,
        family_id="cryptographic_protocol",
        profile_id="default",
        target_component="security.protocol",
        description="Protocol obligations declared for Security IR.",
        aliases=(
            "protocol",
            "cryptographic_protocol",
            "proverif",
            "tamarin",
            "symbolic_protocol",
            "security-ir-view/protocol/v1",
        ),
        preservation_rules=(
            "role_identity",
            "channel_identity",
            "attacker_model",
            "equational_theory",
            "correspondence_claim",
        ),
        backend_ids=("proverif", "tamarin"),
        authority_lane=AuthorityLane.PROTOCOL,
        support_level=SupportLevel.NATIVE,
        evidence_authority=EvidenceAuthority.BOUNDED,
        proof_authority=ProofAuthorityRole.BOUNDED,
        result_authority_ceiling=ResultAuthority.PROTOCOL,
    ),
    # --- Hyperproperty / noninterference ------------------------------------
    _route(
        route_id="security-route/hyperproperty/v1",
        view_id="security-ir-view/hyperproperty/v1",
        view_name="hyperproperty",
        namespace=RouteNamespace.FAMILY,
        disposition=RouteDisposition.TYPED,
        family_id="hyperproperty",
        profile_id="default",
        target_component="security.hyperproperty",
        description="Hyperproperty views for Security IR.",
        aliases=(
            "hyperproperty",
            "hyperltl",
            "security-ir-view/hyperproperty/v1",
        ),
        preservation_rules=(
            "hypertrace_quantifier",
            "alternation_bound",
            "trace_identity",
        ),
        backend_ids=("hyperltl_autohyper_mchyper",),
        authority_lane=AuthorityLane.HYPERPROPERTY,
        support_level=SupportLevel.NATIVE,
        evidence_authority=EvidenceAuthority.BOUNDED,
        proof_authority=ProofAuthorityRole.BOUNDED,
        result_authority_ceiling=ResultAuthority.HYPERPROPERTY,
    ),
    _route(
        route_id="security-route/noninterference/v1",
        view_id="security-ir-view/hyperproperty/v1",
        view_name="noninterference",
        namespace=RouteNamespace.PROPERTY,
        disposition=RouteDisposition.PROPERTY,
        family_id="hyperproperty",
        profile_id="noninterference",
        property_id="noninterference",
        target_component="security.noninterference",
        description=(
            "Noninterference is a property/profile kind under hyperproperty, "
            "never a semantic family."
        ),
        aliases=(
            "noninterference",
            "non_interference",
            "information_flow",
            "info_flow",
        ),
        preservation_rules=(
            "high_low_partition",
            "hypertrace_quantifier",
            "observation_equivalence",
        ),
        backend_ids=("hyperltl_autohyper_mchyper",),
        authority_lane=AuthorityLane.HYPERPROPERTY,
        support_level=SupportLevel.TRANSLATED,
        evidence_authority=EvidenceAuthority.BOUNDED,
        proof_authority=ProofAuthorityRole.BOUNDED,
        result_authority_ceiling=ResultAuthority.HYPERPROPERTY,
    ),
    # --- Separation ---------------------------------------------------------
    _route(
        route_id="security-route/separation/v1",
        view_id="security-ir-view/separation/v1",
        view_name="separation",
        namespace=RouteNamespace.FAMILY,
        disposition=RouteDisposition.TYPED,
        family_id="separation_logic",
        profile_id="default",
        target_component="security.separation",
        description="Separation/resource obligations for Security IR.",
        aliases=(
            "separation",
            "separation_logic",
            "resource",
            "security-ir-view/separation/v1",
        ),
        preservation_rules=(
            "heap_partition",
            "resource_identity",
            "frame_rule",
        ),
        backend_ids=("lean", "rocq", "isabelle", "z3"),
        authority_lane=AuthorityLane.PROOF,
        support_level=SupportLevel.NATIVE,
        evidence_authority=EvidenceAuthority.INDEPENDENTLY_CHECKABLE,
        proof_authority=ProofAuthorityRole.CANDIDATE,
        result_authority_ceiling=ResultAuthority.CANDIDATE,
    ),
    # --- Concurrency --------------------------------------------------------
    _route(
        route_id="security-route/concurrency/v1",
        view_id="security-ir-view/concurrency/v1",
        view_name="concurrency",
        namespace=RouteNamespace.FAMILY,
        disposition=RouteDisposition.TYPED,
        family_id="concurrency",
        profile_id="default",
        target_component="security.concurrency",
        description="Concurrency obligations for Security IR.",
        aliases=(
            "concurrency",
            "rely_guarantee",
            "concurrent",
            "security-ir-view/concurrency/v1",
        ),
        preservation_rules=(
            "thread_identity",
            "rely_guarantee",
            "interference_freedom",
        ),
        backend_ids=("lean", "rocq", "isabelle", "tla_tlc"),
        authority_lane=AuthorityLane.PROOF,
        support_level=SupportLevel.NATIVE,
        evidence_authority=EvidenceAuthority.INDEPENDENTLY_CHECKABLE,
        proof_authority=ProofAuthorityRole.CANDIDATE,
        result_authority_ceiling=ResultAuthority.CANDIDATE,
    ),
    # --- Monitor lane (runtime MTL over temporal) ---------------------------
    _route(
        route_id="security-route/runtime-monitor/v1",
        view_id="security-ir-view/transition/v1",
        view_name="runtime_monitor",
        namespace=RouteNamespace.PROFILE,
        disposition=RouteDisposition.BOUNDED,
        family_id="temporal",
        profile_id="runtime_mtl",
        target_component="security.runtime_monitor",
        description=(
            "Finite-trace metric-temporal runtime monitor lane for Security IR."
        ),
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
    # --- Operation / view roles (never families) ----------------------------
    _route(
        route_id="security-route/verification-condition-role/v1",
        view_id="security-ir-view/claim/v1",
        view_name="verification_condition",
        namespace=RouteNamespace.VIEW_ROLE,
        disposition=RouteDisposition.OPERATION,
        view_role_id="verification_condition",
        target_component="security.verification_condition",
        description=(
            "Verification-condition obligation/view role — never a semantic family. "
            "Use claim/first_order or claim/horn_chc routes for family targets."
        ),
        aliases=(
            "verification_condition",
            "vc_role",
            "obligation",
            "proof_obligation",
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
        requires_parse_elaborate=False,
    ),
    _route(
        route_id="security-route/graph-projection/v1",
        view_id="security-ir-view/graph-projection/v1",
        view_name="graph_projection",
        namespace=RouteNamespace.VIEW_ROLE,
        disposition=RouteDisposition.OPERATION,
        view_role_id="graph_projection",
        target_component="security.graph_projection",
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
        requires_parse_elaborate=False,
    ),
    _route(
        route_id="security-route/proof-translation/v1",
        view_id="security-ir-view/proof-translation/v1",
        view_name="proof_translation",
        namespace=RouteNamespace.VIEW_ROLE,
        disposition=RouteDisposition.OPERATION,
        view_role_id="proof_translation",
        target_component="security.proof_translation",
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
        requires_parse_elaborate=False,
    ),
    # --- Explicit property kinds (safety / liveness) ------------------------
    _route(
        route_id="security-route/safety/v1",
        view_id="security-ir-view/transition/v1",
        view_name="safety",
        namespace=RouteNamespace.PROPERTY,
        disposition=RouteDisposition.PROPERTY,
        family_id="temporal",
        profile_id="safety",
        property_id="safety",
        target_component="security.safety",
        description="Safety is a property kind under temporal/transition, never a family.",
        aliases=("safety", "safety_property"),
        preservation_rules=("invariant_polarity", "bad_state_exclusion"),
        backend_ids=("tla_tlc", "apalache", "z3"),
        authority_lane=AuthorityLane.MODEL,
        support_level=SupportLevel.TRANSLATED,
        evidence_authority=EvidenceAuthority.BOUNDED,
        proof_authority=ProofAuthorityRole.BOUNDED,
        result_authority_ceiling=ResultAuthority.MODEL_CHECK,
    ),
    _route(
        route_id="security-route/liveness/v1",
        view_id="security-ir-view/transition/v1",
        view_name="liveness",
        namespace=RouteNamespace.PROPERTY,
        disposition=RouteDisposition.PROPERTY,
        family_id="temporal",
        profile_id="liveness",
        property_id="liveness",
        target_component="security.liveness",
        description="Liveness is a property kind under temporal, never a family.",
        aliases=("liveness", "liveness_property"),
        preservation_rules=("progress_condition", "fairness_constraint"),
        backend_ids=("tla_tlc", "apalache", "runtime_mtl"),
        authority_lane=AuthorityLane.MODEL,
        support_level=SupportLevel.TRANSLATED,
        evidence_authority=EvidenceAuthority.BOUNDED,
        proof_authority=ProofAuthorityRole.BOUNDED,
        result_authority_ceiling=ResultAuthority.MODEL_CHECK,
    ),
)


def _route_specificity(route: SecurityLogicRoute) -> int:
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
    routes: Sequence[SecurityLogicRoute],
) -> dict[str, SecurityLogicRoute]:
    index: dict[str, SecurityLogicRoute] = {}
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


SECURITY_LOGIC_ROUTE_CATALOG: Final[tuple[SecurityLogicRoute, ...]] = (
    _SECURITY_LOGIC_ROUTES
)
_ROUTE_BY_LABEL: Final[dict[str, SecurityLogicRoute]] = _build_route_index(
    SECURITY_LOGIC_ROUTE_CATALOG
)

# Primary admitted semantic views required by LFP-034 effects.
ADMITTED_SECURITY_VIEW_NAMES: Final[tuple[str, ...]] = (
    "threat",
    "authorization",
    "claim",
    "state",
    "temporal",
    "protocol",
    "noninterference",
    "separation",
    "concurrency",
)


# ---------------------------------------------------------------------------
# Explicit unsupported cells
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class UnsupportedCell:
    """Explicit unsupported matrix cell — never silent success."""

    cell_id: str
    kind: UnsupportedCellKind
    label: str
    description: str
    family_id: str = ""
    profile_id: str = ""
    view_id: str = ""
    backend_id: str = ""
    reason_code: str = CODE_UNSUPPORTED
    is_explicit: bool = True
    may_claim_support: bool = False
    metadata: FrozenMap = field(default_factory=FrozenMap)
    schema_version: str = SECURITY_UNSUPPORTED_CELL_SCHEMA

    def __post_init__(self) -> None:
        if not self.cell_id:
            raise SecurityTypedAdapterError(
                "cell_id must be non-empty",
                code=CODE_MALFORMED,
                path="cell_id",
            )
        if not isinstance(self.kind, UnsupportedCellKind):
            object.__setattr__(self, "kind", UnsupportedCellKind(str(self.kind)))
        if not isinstance(self.metadata, FrozenMap):
            object.__setattr__(
                self, "metadata", FrozenMap(dict(self.metadata or {}))
            )
        # Unsupported cells can never claim support.
        if self.may_claim_support:
            object.__setattr__(self, "may_claim_support", False)
        if not self.is_explicit:
            object.__setattr__(self, "is_explicit", True)

    def to_dict(self) -> dict[str, Any]:
        return {
            "backend_id": self.backend_id,
            "cell_id": self.cell_id,
            "description": self.description,
            "family_id": self.family_id,
            "is_explicit": True,
            "kind": self.kind.value,
            "label": self.label,
            "may_claim_support": False,
            "metadata": self.metadata.to_dict(),
            "profile_id": self.profile_id,
            "reason_code": self.reason_code,
            "schema_version": self.schema_version,
            "view_id": self.view_id,
        }


def record_unsupported_cell(
    *,
    kind: UnsupportedCellKind | str,
    label: str,
    description: str,
    family_id: str = "",
    profile_id: str = "",
    view_id: str = "",
    backend_id: str = "",
    reason_code: str = CODE_UNSUPPORTED,
    cell_id: str = "",
    metadata: Mapping[str, Any] | None = None,
) -> UnsupportedCell:
    """Build an explicit unsupported-cell record."""

    kind_enum = (
        kind if isinstance(kind, UnsupportedCellKind) else UnsupportedCellKind(str(kind))
    )
    if not cell_id:
        cell_id = (
            f"unsupported:{kind_enum.value}:"
            f"{stable_digest({'label': label, 'family': family_id})[:16]}"
        )
    return UnsupportedCell(
        cell_id=cell_id,
        kind=kind_enum,
        label=label,
        description=description,
        family_id=family_id,
        profile_id=profile_id,
        view_id=view_id,
        backend_id=backend_id,
        reason_code=reason_code,
        metadata=FrozenMap(dict(metadata or {})),
    )


def default_unsupported_cells() -> tuple[UnsupportedCell, ...]:
    """Sealed explicit unsupported cells for future / unmapped security labels."""

    cells: list[UnsupportedCell] = []
    for label in sorted(FUTURE_UNSUPPORTED_FAMILY_CLAIMS):
        cells.append(
            record_unsupported_cell(
                kind=UnsupportedCellKind.FUTURE_FAMILY,
                label=label,
                description=(
                    f"Future/declaration-only family {label!r} is not admitted "
                    "for Security IR typed routes."
                ),
                family_id=label if label in DECLARATION_ONLY_FAMILY_IDS else "",
                reason_code=CODE_UNSUPPORTED,
            )
        )
    cells.append(
        record_unsupported_cell(
            kind=UnsupportedCellKind.MISSING_FRONTEND,
            label="probabilistic_threat",
            description=(
                "Probabilistic threat models remain unsupported until a reviewed "
                "frontend and profile exist."
            ),
            reason_code=CODE_UNSUPPORTED,
        )
    )
    cells.append(
        record_unsupported_cell(
            kind=UnsupportedCellKind.MISSING_BACKEND,
            label="unbounded_hyperproperty",
            description=(
                "Unbounded hyperproperty checking without tool/bound profile is "
                "an explicit unsupported cell."
            ),
            family_id="hyperproperty",
            reason_code=CODE_UNSUPPORTED,
        )
    )
    return tuple(cells)


# ---------------------------------------------------------------------------
# Parse / elaborate / lower pipeline
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ParseElaborateReceipt:
    """Receipt proving parse+elaborate completed before lowering."""

    receipt_id: str
    route_id: str
    stage: ParseElaborateStage
    ok: bool
    parsed: bool
    elaborated: bool
    ready_to_lower: bool
    diagnostics: tuple[str, ...] = ()
    source_kind: str = "declaration"
    formula_count: int = 0
    unsupported_constructs: tuple[str, ...] = ()
    schema_version: str = SECURITY_PARSE_ELABORATE_SCHEMA

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
                self, "receipt_id", f"receipt:security-parse:{digest[:24]}"
            )
        # Invariants: ready_to_lower requires both parse and elaborate.
        if self.ready_to_lower and not (self.parsed and self.elaborated and self.ok):
            object.__setattr__(self, "ready_to_lower", False)
        if self.ok and self.parsed and self.elaborated:
            if self.stage not in {
                ParseElaborateStage.ELABORATED,
                ParseElaborateStage.READY_TO_LOWER,
                ParseElaborateStage.LOWERED,
            }:
                object.__setattr__(
                    self, "stage", ParseElaborateStage.READY_TO_LOWER
                )
                object.__setattr__(self, "ready_to_lower", True)

    def to_dict(self) -> dict[str, Any]:
        return {
            "diagnostics": list(self.diagnostics),
            "elaborated": self.elaborated,
            "formula_count": self.formula_count,
            "ok": self.ok,
            "parsed": self.parsed,
            "ready_to_lower": self.ready_to_lower,
            "receipt_id": self.receipt_id,
            "route_id": self.route_id,
            "schema_version": self.schema_version,
            "source_kind": self.source_kind,
            "stage": self.stage.value,
            "unsupported_constructs": list(self.unsupported_constructs),
        }


def parse_and_elaborate(
    route: SecurityLogicRoute,
    *,
    source: object = None,
    formulas: Sequence[Mapping[str, Any]] | Sequence[Any] = (),
    fail_on_unsupported: bool = True,
) -> ParseElaborateReceipt:
    """Parse and elaborate a security view payload before any lowering.

    Admitted semantic routes require a successful parse+elaborate receipt.
    Operation/view roles may skip elaboration (they are not family targets).
    """

    if route.is_operation_role or not route.requires_parse_elaborate:
        return ParseElaborateReceipt(
            receipt_id="",
            route_id=route.route_id,
            stage=ParseElaborateStage.READY_TO_LOWER,
            ok=True,
            parsed=True,
            elaborated=True,
            ready_to_lower=True,
            diagnostics=("security.operation_role_no_family_elaboration",),
            source_kind="operation",
            formula_count=0,
        )

    if route.disposition is RouteDisposition.UNSUPPORTED or (
        route.support_level is SupportLevel.UNSUPPORTED
    ):
        return ParseElaborateReceipt(
            receipt_id="",
            route_id=route.route_id,
            stage=ParseElaborateStage.REJECTED,
            ok=False,
            parsed=False,
            elaborated=False,
            ready_to_lower=False,
            diagnostics=(CODE_UNSUPPORTED,),
            source_kind="unsupported",
        )

    # Typed declaration surface: accept structured formula maps or empty
    # declaration-only admission (catalog route exists and is well-formed).
    formula_items: list[dict[str, Any]] = []
    unsupported: list[str] = []
    diagnostics: list[str] = []

    for index, raw in enumerate(formulas):
        if isinstance(raw, Mapping):
            data = {str(k): v for k, v in raw.items()}
        else:
            data = {
                "formula_id": getattr(raw, "formula_id", f"formula:{index}"),
                "kind": getattr(raw, "kind", None),
            }
        formula_id = str(data.get("formula_id") or f"formula:{index}")
        if data.get("unsupported") is True or data.get("disposition") == "unsupported":
            construct = str(data.get("construct") or data.get("kind") or formula_id)
            unsupported.append(construct)
            continue
        # Free-form family labels inside formulas are explicit unsupported constructs.
        embedded_family = str(data.get("logic_family") or data.get("family_id") or "")
        if embedded_family:
            normalized = _normalize_label(embedded_family)
            if normalized in {_normalize_label(x) for x in FUTURE_UNSUPPORTED_FAMILY_CLAIMS}:
                unsupported.append(embedded_family)
                continue
            if (
                normalized
                and normalized not in DEFAULT_REGISTRY.families
                and normalized not in NEVER_FAMILY_PROPERTY_KINDS
                and normalized not in NEVER_FAMILY_OPERATION_ROLES
            ):
                unsupported.append(embedded_family)
                continue
        formula_items.append(data)

    if unsupported and fail_on_unsupported:
        diagnostics.append(CODE_UNSUPPORTED)
        return ParseElaborateReceipt(
            receipt_id="",
            route_id=route.route_id,
            stage=ParseElaborateStage.REJECTED,
            ok=False,
            parsed=True,
            elaborated=False,
            ready_to_lower=False,
            diagnostics=tuple(diagnostics),
            source_kind=_source_kind(source),
            formula_count=len(formula_items),
            unsupported_constructs=tuple(dict.fromkeys(unsupported)),
        )

    if unsupported:
        diagnostics.append(CODE_UNSUPPORTED)

    # Empty formulas: catalog admission still parses/elaborates the view
    # declaration itself (typed empty theory).
    diagnostics.append(CODE_PARSE_REQUIRED.replace("required", "ok"))
    return ParseElaborateReceipt(
        receipt_id="",
        route_id=route.route_id,
        stage=ParseElaborateStage.READY_TO_LOWER,
        ok=True,
        parsed=True,
        elaborated=True,
        ready_to_lower=True,
        diagnostics=tuple(diagnostics) or ("security.parse_elaborate_ok",),
        source_kind=_source_kind(source),
        formula_count=len(formula_items),
        unsupported_constructs=tuple(dict.fromkeys(unsupported)),
    )


def _source_kind(source: object) -> str:
    if source is None:
        return "declaration"
    if isinstance(source, Mapping):
        return str(source.get("kind") or source.get("source_kind") or "mapping")
    if isinstance(source, str):
        return "text"
    return type(source).__name__


def assert_ready_to_lower(receipt: ParseElaborateReceipt) -> None:
    """Fail closed if lowering is attempted without successful parse/elaborate."""

    if not receipt.ok or not receipt.parsed or not receipt.elaborated:
        raise ParseElaborateRequiredError(
            f"route {receipt.route_id!r} is not ready to lower "
            f"(stage={receipt.stage.value}, ok={receipt.ok}, "
            f"parsed={receipt.parsed}, elaborated={receipt.elaborated})"
        )
    if not receipt.ready_to_lower:
        raise ParseElaborateRequiredError(
            f"route {receipt.route_id!r} parse/elaborate receipt is not ready_to_lower"
        )


# ---------------------------------------------------------------------------
# Translation and backend receipts (authority bounds)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TranslationReceipt:
    """Bounds authority that may emerge from a translation edge."""

    receipt_id: str
    route_id: str
    source_family_id: str
    target_family_id: str
    preservation: str
    proof_safe: bool
    counterexample_safe: bool
    authority_ceiling: ResultAuthority
    assumptions: tuple[str, ...] = ()
    unsupported_nodes: tuple[str, ...] = ()
    schema_version: str = SECURITY_TRANSLATION_RECEIPT_SCHEMA

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
                    "route_id": self.route_id,
                    "source": self.source_family_id,
                    "target": self.target_family_id,
                }
            )
            object.__setattr__(
                self, "receipt_id", f"receipt:security-translation:{digest[:24]}"
            )
        # Silent drops are forbidden: if unsupported nodes exist, proof_safe
        # cannot remain true without an explicit non-empty assumption list.
        if self.unsupported_nodes and self.proof_safe and not self.assumptions:
            object.__setattr__(self, "proof_safe", False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "assumptions": list(self.assumptions),
            "authority_ceiling": self.authority_ceiling.value,
            "counterexample_safe": self.counterexample_safe,
            "preservation": self.preservation,
            "proof_safe": self.proof_safe,
            "receipt_id": self.receipt_id,
            "route_id": self.route_id,
            "schema_version": self.schema_version,
            "source_family_id": self.source_family_id,
            "target_family_id": self.target_family_id,
            "unsupported_nodes": list(self.unsupported_nodes),
        }


@dataclass(frozen=True, slots=True)
class BackendReceipt:
    """Bounds authority that may emerge from a concrete backend execution."""

    receipt_id: str
    backend_id: str
    route_id: str
    authority: ResultAuthority
    authority_lane: AuthorityLane
    status: str = "not_executed"
    bound_profile: str = ""
    tool_version: str = ""
    schema_version: str = SECURITY_BACKEND_RECEIPT_SCHEMA

    def __post_init__(self) -> None:
        if not isinstance(self.authority, ResultAuthority):
            object.__setattr__(self, "authority", ResultAuthority(str(self.authority)))
        if not isinstance(self.authority_lane, AuthorityLane):
            object.__setattr__(
                self, "authority_lane", AuthorityLane(str(self.authority_lane))
            )
        if not self.receipt_id:
            digest = stable_digest(
                {
                    "backend_id": self.backend_id,
                    "route_id": self.route_id,
                    "authority": self.authority.value,
                }
            )
            object.__setattr__(
                self, "receipt_id", f"receipt:security-backend:{digest[:24]}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority": self.authority.value,
            "authority_lane": self.authority_lane.value,
            "backend_id": self.backend_id,
            "bound_profile": self.bound_profile,
            "receipt_id": self.receipt_id,
            "route_id": self.route_id,
            "schema_version": self.schema_version,
            "status": self.status,
            "tool_version": self.tool_version,
        }


# Backend → default ResultAuthority for evidence-subset tools.
_BACKEND_AUTHORITY: Final[dict[str, ResultAuthority]] = {
    "z3": ResultAuthority.SATISFIABILITY,
    "cvc5": ResultAuthority.SATISFIABILITY,
    "tla_tlc": ResultAuthority.MODEL_CHECK,
    "apalache": ResultAuthority.MODEL_CHECK,
    "datalog_secpal": ResultAuthority.AUTHORIZATION,
    "proverif": ResultAuthority.PROTOCOL,
    "tamarin": ResultAuthority.PROTOCOL,
    "hyperltl_autohyper_mchyper": ResultAuthority.HYPERPROPERTY,
    "vampire": ResultAuthority.CANDIDATE,
    "eprover": ResultAuthority.CANDIDATE,
    "lean": ResultAuthority.THEOREM,
    "rocq": ResultAuthority.THEOREM,
    "isabelle": ResultAuthority.THEOREM,
    "runtime_mtl": ResultAuthority.MONITOR,
}

_BACKEND_LANE: Final[dict[str, AuthorityLane]] = {
    "z3": AuthorityLane.PROOF,
    "cvc5": AuthorityLane.PROOF,
    "tla_tlc": AuthorityLane.MODEL,
    "apalache": AuthorityLane.MODEL,
    "datalog_secpal": AuthorityLane.AUTHORIZATION,
    "proverif": AuthorityLane.PROTOCOL,
    "tamarin": AuthorityLane.PROTOCOL,
    "hyperltl_autohyper_mchyper": AuthorityLane.HYPERPROPERTY,
    "vampire": AuthorityLane.CANDIDATE,
    "eprover": AuthorityLane.CANDIDATE,
    "lean": AuthorityLane.PROOF,
    "rocq": AuthorityLane.PROOF,
    "isabelle": AuthorityLane.PROOF,
    "runtime_mtl": AuthorityLane.MONITOR,
}


def backend_default_authority(backend_id: str) -> ResultAuthority:
    """Return the sealed default authority for an evidence-subset backend."""

    key = str(backend_id or "").strip()
    if key not in _BACKEND_AUTHORITY:
        raise SecurityTypedAdapterError(
            f"unknown security evidence backend {backend_id!r}",
            code=CODE_BACKEND_MISSING,
            path="backend_id",
        )
    return _BACKEND_AUTHORITY[key]


def issue_translation_receipt(
    route: SecurityLogicRoute,
    *,
    target_family_id: str = "",
    preservation: str = "equisatisfiable",
    proof_safe: bool = False,
    counterexample_safe: bool = False,
    assumptions: Sequence[str] = (),
    unsupported_nodes: Sequence[str] = (),
    authority_ceiling: ResultAuthority | str | None = None,
) -> TranslationReceipt:
    """Issue a translation receipt that upper-bounds route authority."""

    target = target_family_id or route.family_id
    if authority_ceiling is None:
        ceiling = route.result_authority_ceiling
    elif isinstance(authority_ceiling, ResultAuthority):
        ceiling = authority_ceiling
    else:
        ceiling = ResultAuthority(str(authority_ceiling))

    # Translation cannot raise authority above the route ceiling.
    ceiling = _min_authority(ceiling, route.result_authority_ceiling)
    return TranslationReceipt(
        receipt_id="",
        route_id=route.route_id,
        source_family_id=route.family_id or route.view_role_id or route.property_id,
        target_family_id=target,
        preservation=preservation,
        proof_safe=proof_safe and not unsupported_nodes,
        counterexample_safe=counterexample_safe,
        authority_ceiling=ceiling,
        assumptions=tuple(str(a) for a in assumptions),
        unsupported_nodes=tuple(str(n) for n in unsupported_nodes),
    )


def issue_backend_receipt(
    route: SecurityLogicRoute,
    backend_id: str,
    *,
    status: str = "not_executed",
    bound_profile: str = "",
    tool_version: str = "",
    authority: ResultAuthority | str | None = None,
) -> BackendReceipt:
    """Issue a backend receipt bounded by backend defaults and the route ceiling."""

    if backend_id not in route.backend_ids and backend_id not in SECURITY_EVIDENCE_BACKENDS:
        raise SecurityTypedAdapterError(
            f"backend {backend_id!r} is not an admitted security evidence backend",
            code=CODE_BACKEND_MISSING,
            path="backend_id",
        )
    default_auth = backend_default_authority(backend_id)
    if authority is None:
        claimed = default_auth
    elif isinstance(authority, ResultAuthority):
        claimed = authority
    else:
        claimed = ResultAuthority(str(authority))

    # Backend cannot promote above its sealed default or the route ceiling.
    bounded = _min_authority(claimed, default_auth)
    bounded = _min_authority(bounded, route.result_authority_ceiling)
    # Kernel backends may report THEOREM only when the route lane is PROOF and
    # the route ceiling is not strictly lower; routes that cap at CANDIDATE stay
    # capped even if the backend is a kernel.
    if (
        bounded is ResultAuthority.THEOREM
        and route.proof_authority is not ProofAuthorityRole.OFFICIAL
        and route.result_authority_ceiling is not ResultAuthority.THEOREM
    ):
        bounded = route.result_authority_ceiling

    return BackendReceipt(
        receipt_id="",
        backend_id=backend_id,
        route_id=route.route_id,
        authority=bounded,
        authority_lane=_BACKEND_LANE.get(backend_id, route.authority_lane),
        status=status,
        bound_profile=bound_profile or route.profile_id,
        tool_version=tool_version,
    )


# Partial order used only for fail-closed authority clamping (not interchange).
_AUTHORITY_RANK: Final[dict[ResultAuthority, int]] = {
    ResultAuthority.CANDIDATE: 1,
    ResultAuthority.ATTESTATION: 2,
    ResultAuthority.RECONSTRUCTION: 3,
    ResultAuthority.MONITOR: 4,
    ResultAuthority.AUTHORIZATION: 5,
    ResultAuthority.PROTOCOL: 6,
    ResultAuthority.HYPERPROPERTY: 7,
    ResultAuthority.SATISFIABILITY: 8,
    ResultAuthority.MODEL_CHECK: 8,
    ResultAuthority.THEOREM: 10,
}


def _authority_rank(authority: ResultAuthority) -> int:
    return _AUTHORITY_RANK.get(authority, 1)


def _min_authority(left: ResultAuthority, right: ResultAuthority) -> ResultAuthority:
    """Return the lower of two authorities (fail-closed ceiling)."""

    if _authority_rank(left) <= _authority_rank(right):
        return left
    return right


def bound_authority(
    route: SecurityLogicRoute,
    *,
    claimed: ResultAuthority | str | None = None,
    translation: TranslationReceipt | None = None,
    backend: BackendReceipt | None = None,
) -> ResultAuthority:
    """Bound claimed authority by route, translation, and backend receipts.

    Proof / model / monitor authority is never higher than the weakest of:
    route ceiling, translation receipt ceiling (when present), and backend
    receipt authority (when present).  Official theorem requires a kernel
    backend receipt whose authority is THEOREM and a route that permits it.
    """

    if claimed is None:
        claimed_auth = route.result_authority_ceiling
    elif isinstance(claimed, ResultAuthority):
        claimed_auth = claimed
    else:
        try:
            claimed_auth = ResultAuthority(str(claimed))
        except (TypeError, ValueError) as exc:
            raise SecurityTypedAdapterError(
                f"unknown result authority {claimed!r}",
                code=CODE_MALFORMED,
                path="authority",
            ) from exc

    ceiling = route.result_authority_ceiling

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
        and backend is None
    ):
        raise AuthorityPromotionError(
            f"route {route.route_id!r} cannot claim theorem without a kernel "
            "backend receipt; authority is bounded by translation and backend receipts"
        )

    result = _min_authority(claimed_auth, ceiling)

    if translation is not None:
        result = _min_authority(result, translation.authority_ceiling)
        if translation.route_id != route.route_id:
            raise SecurityTypedAdapterError(
                "translation receipt route_id does not match route",
                code=CODE_TRANSLATION_MISSING,
                path="translation",
            )

    if backend is not None:
        if backend.route_id != route.route_id:
            raise SecurityTypedAdapterError(
                "backend receipt route_id does not match route",
                code=CODE_BACKEND_MISSING,
                path="backend",
            )
        result = _min_authority(result, backend.authority)
        # Theorem requires a kernel backend receipt that still carries THEOREM
        # after route-ceiling clamping.  Lower backend authority fail-closed
        # clamps the claim rather than silently promoting.
        if (
            claimed_auth is ResultAuthority.THEOREM
            and backend.authority is not ResultAuthority.THEOREM
        ):
            # Clamp: theorem claim is bounded down to the backend receipt.
            result = backend.authority
        if (
            claimed_auth is ResultAuthority.THEOREM
            and backend.authority is ResultAuthority.THEOREM
            and route.result_authority_ceiling is not ResultAuthority.THEOREM
            and route.proof_authority is not ProofAuthorityRole.OFFICIAL
        ):
            # Route ceiling still wins — candidate/separations stay candidate.
            result = route.result_authority_ceiling

    return result


# ---------------------------------------------------------------------------
# Route receipt
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SecurityRouteReceipt:
    """Receipt for a single security view routing decision."""

    receipt_id: str
    route: SecurityLogicRoute
    requested_label: str
    parse_elaborate: ParseElaborateReceipt | None = None
    translation: TranslationReceipt | None = None
    backend: BackendReceipt | None = None
    unsupported_cells: tuple[UnsupportedCell, ...] = ()
    diagnostics: tuple[str, ...] = ()
    authority_ceiling: ResultAuthority = ResultAuthority.CANDIDATE
    lowered: bool = False
    schema_version: str = SECURITY_ROUTE_RECEIPT_SCHEMA

    def __post_init__(self) -> None:
        if not self.receipt_id:
            digest = stable_digest(
                {
                    "route_id": self.route.route_id,
                    "requested_label": self.requested_label,
                }
            )
            object.__setattr__(
                self, "receipt_id", f"receipt:security-route:{digest[:24]}"
            )
        if not isinstance(self.authority_ceiling, ResultAuthority):
            object.__setattr__(
                self,
                "authority_ceiling",
                ResultAuthority(str(self.authority_ceiling)),
            )
        # Never THEOREM from the route alone.
        if (
            self.authority_ceiling is ResultAuthority.THEOREM
            and self.route.proof_authority is not ProofAuthorityRole.OFFICIAL
            and (
                self.backend is None
                or self.backend.authority is not ResultAuthority.THEOREM
            )
        ):
            object.__setattr__(
                self, "authority_ceiling", self.route.result_authority_ceiling
            )
        # Lowering requires parse/elaborate readiness for admitted views.
        if self.lowered:
            if self.route.requires_parse_elaborate:
                if self.parse_elaborate is None or not self.parse_elaborate.ready_to_lower:
                    raise ParseElaborateRequiredError(
                        f"cannot mark lowered without ready parse/elaborate for "
                        f"{self.route.route_id!r}"
                    )

    @property
    def is_proof(self) -> bool:
        return False  # Typed routes alone never mint proof.

    @property
    def family_id(self) -> str:
        return self.route.family_id

    @property
    def is_operation_role(self) -> bool:
        return self.route.is_operation_role

    @property
    def is_ready_to_lower(self) -> bool:
        if not self.route.requires_parse_elaborate:
            return True
        return bool(
            self.parse_elaborate is not None and self.parse_elaborate.ready_to_lower
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority_ceiling": self.authority_ceiling.value,
            "backend": self.backend.to_dict() if self.backend else None,
            "diagnostics": list(self.diagnostics),
            "family_id": self.family_id,
            "is_operation_role": self.is_operation_role,
            "is_proof": False,
            "is_ready_to_lower": self.is_ready_to_lower,
            "lowered": self.lowered,
            "parse_elaborate": (
                self.parse_elaborate.to_dict() if self.parse_elaborate else None
            ),
            "receipt_id": self.receipt_id,
            "requested_label": self.requested_label,
            "route": self.route.to_dict(),
            "schema_version": self.schema_version,
            "translation": self.translation.to_dict() if self.translation else None,
            "unsupported_cells": [cell.to_dict() for cell in self.unsupported_cells],
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def is_never_family_label(label: object) -> bool:
    """Return True when *label* is an operation/view role that is not a family."""

    normalized = _normalize_label(label)
    if not normalized:
        return False
    if normalized in {_normalize_label(item) for item in NEVER_FAMILY_OPERATION_ROLES}:
        return True
    route = _ROUTE_BY_LABEL.get(normalized)
    return route is not None and route.is_operation_role


def is_never_family_property(label: object) -> bool:
    """Return True when *label* is a property kind that is not a family."""

    normalized = _normalize_label(label)
    if not normalized:
        return False
    if normalized in {_normalize_label(item) for item in NEVER_FAMILY_PROPERTY_KINDS}:
        return True
    route = _ROUTE_BY_LABEL.get(normalized)
    return route is not None and route.is_property_kind


def reject_operation_role_as_family(
    label: object, *, path: str = "logic_family"
) -> None:
    """Fail closed when an operation role is claimed as a semantic family."""

    if is_never_family_label(label):
        raise OperationRoleAsFamilyError(str(label), path=path)


def reject_property_as_family(
    label: object, *, path: str = "logic_family"
) -> None:
    """Fail closed when a property kind is claimed as a semantic family."""

    if is_never_family_property(label):
        # Allow resolving property routes; reject only bare "as family" claims
        # when the caller uses the helper intentionally.
        raise PropertyAsFamilyError(str(label), path=path)


def resolve_security_route(label: object) -> SecurityLogicRoute:
    """Resolve a security view name, contract id, alias, or family label."""

    if isinstance(label, SecurityLogicRoute):
        return label
    raw = str(label or "").strip()
    if not raw:
        raise SecurityTypedAdapterError(
            "route label must be a non-empty string",
            code=CODE_UNKNOWN_VIEW,
            path="label",
        )
    normalized = _normalize_label(raw)

    # Future / unsupported families fail closed as explicit unsupported cells.
    if normalized in {_normalize_label(x) for x in FUTURE_UNSUPPORTED_FAMILY_CLAIMS}:
        raise UnsupportedCellError(
            f"label {raw!r} is an explicit unsupported security cell",
            path="label",
        )

    route = _ROUTE_BY_LABEL.get(normalized)
    if route is not None:
        return route

    # Reject bare operation-role spellings even when not indexed under a free form.
    if normalized in {_normalize_label(item) for item in NEVER_FAMILY_OPERATION_ROLES}:
        raise OperationRoleAsFamilyError(raw)

    raise SecurityTypedAdapterError(
        f"unknown security logic route label {raw!r}",
        code=CODE_UNKNOWN_VIEW,
        path="label",
    )


def enforce_authority_ceiling(
    route: SecurityLogicRoute,
    claimed: ResultAuthority | str | None,
    *,
    translation: TranslationReceipt | None = None,
    backend: BackendReceipt | None = None,
) -> ResultAuthority:
    """Clamp or reject authority claims that exceed the route/receipt ceiling."""

    return bound_authority(
        route,
        claimed=claimed,
        translation=translation,
        backend=backend,
    )


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SecurityFormalizationAdapter:
    """Route security_ir views onto canonical families, profiles, properties, and roles.

    Interface: ``SecurityFormalizationAdapter@2``.
    """

    INTERFACE: ClassVar[str] = SECURITY_FORMALIZATION_ADAPTER_INTERFACE
    VERSION: ClassVar[str] = SECURITY_FORMALIZATION_ADAPTER_VERSION

    producer_id: str = SECURITY_IR_TYPED_ADAPTER_PRODUCER_ID
    domain: str = SECURITY_IR_TYPED_DOMAIN
    domain_id: str = SECURITY_IR_DOMAIN_ID

    def __post_init__(self) -> None:
        if not _ID_RE.fullmatch(self.producer_id):
            raise SecurityTypedAdapterError(
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
        return tuple(route.route_id for route in SECURITY_LOGIC_ROUTE_CATALOG)

    def routes(self) -> tuple[SecurityLogicRoute, ...]:
        return SECURITY_LOGIC_ROUTE_CATALOG

    def admitted_routes(self) -> tuple[SecurityLogicRoute, ...]:
        return tuple(
            route for route in SECURITY_LOGIC_ROUTE_CATALOG if route.is_admitted
        )

    def typed_family_routes(self) -> tuple[SecurityLogicRoute, ...]:
        return tuple(
            route
            for route in SECURITY_LOGIC_ROUTE_CATALOG
            if route.is_semantic_family
        )

    def operation_role_routes(self) -> tuple[SecurityLogicRoute, ...]:
        return tuple(
            route for route in SECURITY_LOGIC_ROUTE_CATALOG if route.is_operation_role
        )

    def property_routes(self) -> tuple[SecurityLogicRoute, ...]:
        return tuple(
            route for route in SECURITY_LOGIC_ROUTE_CATALOG if route.is_property_kind
        )

    def declaration_only_routes(self) -> tuple[SecurityLogicRoute, ...]:
        return tuple(
            route for route in SECURITY_LOGIC_ROUTE_CATALOG if route.is_declaration_only
        )

    def resolve(self, label: object) -> SecurityLogicRoute:
        return resolve_security_route(label)

    def parse_and_elaborate(
        self,
        label: object,
        *,
        source: object = None,
        formulas: Sequence[Mapping[str, Any]] | Sequence[Any] = (),
        fail_on_unsupported: bool = True,
    ) -> ParseElaborateReceipt:
        """Parse and elaborate an admitted security view before lowering."""

        route = resolve_security_route(label)
        return parse_and_elaborate(
            route,
            source=source,
            formulas=formulas,
            fail_on_unsupported=fail_on_unsupported,
        )

    def route_view(
        self,
        label: object,
        *,
        formulas: Sequence[Mapping[str, Any]] | Sequence[Any] = (),
        source: object = None,
        claimed_authority: object = None,
        backend_id: str = "",
        lower: bool = False,
        fail_on_unsupported: bool = True,
        include_unsupported_catalog: bool = False,
    ) -> SecurityRouteReceipt:
        """Route a security view, parse/elaborate, and optionally lower.

        Every admitted semantic view is parse/elaborated before lowering.
        Unsupported cells are attached explicitly when requested or when the
        input mentions unsupported constructs.
        """

        route = resolve_security_route(label)
        assert not (
            route.is_operation_role and route.family_id
        ), "invariant: operation roles never carry a family_id"

        pe = parse_and_elaborate(
            route,
            source=source,
            formulas=formulas,
            fail_on_unsupported=fail_on_unsupported,
        )

        translation: TranslationReceipt | None = None
        backend: BackendReceipt | None = None
        diagnostics: list[str] = list(pe.diagnostics)

        if route.is_operation_role:
            diagnostics.append("security.operation_role_not_family")
        if route.is_property_kind:
            diagnostics.append("security.property_not_family")
        if route.is_declaration_only:
            diagnostics.append(CODE_UNSUPPORTED)

        if pe.ok and (
            route.is_semantic_family
            or route.is_property_kind
            or (route.family_id and not route.is_operation_role)
        ):
            translation = issue_translation_receipt(route)
            diagnostics.append(CODE_AUTHORITY_BOUND)

        if backend_id:
            if not pe.ready_to_lower and route.requires_parse_elaborate:
                raise ParseElaborateRequiredError(
                    f"cannot attach backend {backend_id!r} before parse/elaborate "
                    f"for {route.route_id!r}"
                )
            backend = issue_backend_receipt(route, backend_id)

        ceiling = enforce_authority_ceiling(
            route,
            claimed_authority if claimed_authority is not None else None,
            translation=translation,
            backend=backend,
        )

        unsupported: list[UnsupportedCell] = []
        if include_unsupported_catalog:
            unsupported.extend(default_unsupported_cells())
        for construct in pe.unsupported_constructs:
            unsupported.append(
                record_unsupported_cell(
                    kind=UnsupportedCellKind.FREE_FORM_LABEL,
                    label=construct,
                    description=f"unsupported construct {construct!r} in security view",
                    family_id=route.family_id,
                    view_id=route.view_id,
                )
            )

        if lower:
            assert_ready_to_lower(pe)
            diagnostics.append("security.lowered_after_parse_elaborate")

        return SecurityRouteReceipt(
            receipt_id="",
            route=route,
            requested_label=str(label),
            parse_elaborate=pe,
            translation=translation,
            backend=backend,
            unsupported_cells=tuple(unsupported),
            diagnostics=tuple(dict.fromkeys(diagnostics)),
            authority_ceiling=ceiling,
            lowered=lower,
        )

    def lower_view(
        self,
        label: object,
        *,
        formulas: Sequence[Mapping[str, Any]] | Sequence[Any] = (),
        source: object = None,
        backend_id: str = "",
        claimed_authority: object = None,
    ) -> SecurityRouteReceipt:
        """Lower a view only after successful parse and elaborate."""

        return self.route_view(
            label,
            formulas=formulas,
            source=source,
            backend_id=backend_id,
            claimed_authority=claimed_authority,
            lower=True,
        )

    def assert_operations_are_not_families(
        self, labels: Iterable[object] | None = None
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
        self, labels: Iterable[object] | None = None
    ) -> None:
        """Fail closed if property kinds are claimed as families."""

        if labels is None:
            labels = ("safety", "liveness", "noninterference")
        for label in labels:
            reject_property_as_family(label)

    def assert_admitted_views_parse_before_lower(self) -> None:
        """Verify every admitted semantic view can parse/elaborate empty theory."""

        for name in ADMITTED_SECURITY_VIEW_NAMES:
            route = resolve_security_route(name)
            if not route.requires_parse_elaborate:
                continue
            pe = parse_and_elaborate(route)
            if not pe.ready_to_lower:
                raise ParseElaborateRequiredError(
                    f"admitted view {name!r} failed parse/elaborate gate"
                )

    def catalog_manifest(self) -> dict[str, Any]:
        """Serializable route catalog for matrix / audit consumers."""

        return {
            "adapter_version": self.VERSION,
            "admitted_view_names": list(ADMITTED_SECURITY_VIEW_NAMES),
            "declaration_only_route_ids": [
                route.route_id for route in self.declaration_only_routes()
            ],
            "domain": self.domain,
            "domain_id": self.domain_id,
            "evidence_backends": list(SECURITY_EVIDENCE_BACKENDS),
            "interface": self.INTERFACE,
            "never_family_operation_roles": sorted(NEVER_FAMILY_OPERATION_ROLES),
            "never_family_property_kinds": sorted(NEVER_FAMILY_PROPERTY_KINDS),
            "operation_role_route_ids": [
                route.route_id for route in self.operation_role_routes()
            ],
            "producer_id": self.producer_id,
            "property_route_ids": [
                route.route_id for route in self.property_routes()
            ],
            "routes": [route.to_dict() for route in self.routes()],
            "typed_family_route_ids": [
                route.route_id for route in self.typed_family_routes()
            ],
            "unsupported_cells": [
                cell.to_dict() for cell in default_unsupported_cells()
            ],
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "domain": self.domain,
            "domain_id": self.domain_id,
            "interface": self.INTERFACE,
            "module_version": SECURITY_TYPED_ADAPTER_MODULE_VERSION,
            "producer_id": self.producer_id,
            "version": self.VERSION,
        }


# Short migration aliases.
SecurityTypedAdapter = SecurityFormalizationAdapter
SecurityIRTypedAdapter = SecurityFormalizationAdapter


def route_security_view(
    label: object,
    **kwargs: Any,
) -> SecurityRouteReceipt:
    """Module-level convenience wrapper around :meth:`SecurityFormalizationAdapter.route_view`."""

    return SecurityFormalizationAdapter().route_view(label, **kwargs)


def security_logic_routes() -> tuple[SecurityLogicRoute, ...]:
    """Return the sealed security logic route catalog."""

    return SECURITY_LOGIC_ROUTE_CATALOG


__all__ = [
    "ADMITTED_SECURITY_VIEW_NAMES",
    "FUTURE_UNSUPPORTED_FAMILY_CLAIMS",
    "NEVER_FAMILY_OPERATION_ROLES",
    "NEVER_FAMILY_PROPERTY_KINDS",
    "SECURITY_BACKEND_RECEIPT_SCHEMA",
    "SECURITY_EVIDENCE_BACKENDS",
    "SECURITY_FORMALIZATION_ADAPTER_INTERFACE",
    "SECURITY_FORMALIZATION_ADAPTER_VERSION",
    "SECURITY_IR_DOMAIN_ID",
    "SECURITY_IR_TYPED_ADAPTER_PRODUCER_ID",
    "SECURITY_IR_TYPED_DOMAIN",
    "SECURITY_LOGIC_ROUTE_CATALOG",
    "SECURITY_LOGIC_ROUTE_SCHEMA",
    "SECURITY_PARSE_ELABORATE_SCHEMA",
    "SECURITY_ROUTE_RECEIPT_SCHEMA",
    "SECURITY_TRANSLATION_RECEIPT_SCHEMA",
    "SECURITY_TYPED_ADAPTER_MODULE_VERSION",
    "SECURITY_UNSUPPORTED_CELL_SCHEMA",
    "AuthorityLane",
    "AuthorityPromotionError",
    "BackendReceipt",
    "FreeFormFamilyError",
    "OperationRoleAsFamilyError",
    "ParseElaborateRequiredError",
    "ParseElaborateReceipt",
    "ParseElaborateStage",
    "ProofAuthorityRole",
    "PropertyAsFamilyError",
    "RouteDisposition",
    "RouteNamespace",
    "SecurityFormalizationAdapter",
    "SecurityIRTypedAdapter",
    "SecurityLogicRoute",
    "SecurityRouteReceipt",
    "SecurityTypedAdapter",
    "SecurityTypedAdapterError",
    "TranslationReceipt",
    "UnsupportedCell",
    "UnsupportedCellError",
    "UnsupportedCellKind",
    "assert_ready_to_lower",
    "backend_default_authority",
    "bound_authority",
    "default_unsupported_cells",
    "enforce_authority_ceiling",
    "is_never_family_label",
    "is_never_family_property",
    "issue_backend_receipt",
    "issue_translation_receipt",
    "parse_and_elaborate",
    "record_unsupported_cell",
    "reject_operation_role_as_family",
    "reject_property_as_family",
    "resolve_security_route",
    "route_security_view",
    "security_logic_routes",
]
