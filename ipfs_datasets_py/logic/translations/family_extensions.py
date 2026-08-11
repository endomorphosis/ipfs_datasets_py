"""Wave-2 family extension translation routes (LFP2-044).

``FamilyRoutePublication@1`` fragment: reviewed family-to-family and
family-to-provider translation routes for Wave-2 expansion families.

Every admitted route is:

* **reviewed** — explicit route id and owner task
* **feature-compatible** — required source features ⊆ published features
* **loss/authority receipted** — explicit preservation, loss ids, authority ceiling

Registry presence alone never makes a route executable.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any, ClassVar, Final

from ipfs_datasets_py.logic.families.profile_catalog_v3 import (
    DEFAULT_PROFILE_CATALOG_V3,
    LogicProfileCatalogV3,
)
from ipfs_datasets_py.logic.families.registry_v3 import (
    DEFAULT_REGISTRY_V3,
    LogicFamilyRegistryV3,
    REGISTRY_V3_GOAL_ID,
    REGISTRY_V3_TASK_ID,
)

# ---------------------------------------------------------------------------
# Interface / schema
# ---------------------------------------------------------------------------

FAMILY_ROUTE_PUBLICATION_INTERFACE: Final = "FamilyRoutePublication@1"
FAMILY_EXTENSION_ROUTES_INTERFACE: Final = "FamilyExtensionRoutes@1"
FAMILY_EXTENSION_ROUTE_SCHEMA: Final = "logic-family-extension-route/v1"
FAMILY_EXTENSION_CATALOG_SCHEMA: Final = "logic-family-extension-catalog/v1"
LOSS_RECEIPT_SCHEMA: Final = "logic-family-extension-loss-receipt/v1"
FAMILY_EXTENSIONS_MODULE_VERSION: Final = "1.0.0"

FAMILY_EXTENSIONS_TASK_ID: Final = REGISTRY_V3_TASK_ID
FAMILY_EXTENSIONS_GOAL_ID: Final = REGISTRY_V3_GOAL_ID


class RouteKind(StrEnum):
    """Target class for a family extension route."""

    FAMILY = "family"
    PROVIDER = "provider"
    DOMAIN_OVERLAY = "domain_overlay"


class RouteDisposition(StrEnum):
    """Whether the route may be dispatched."""

    DECLARATION_ONLY = "declaration_only"
    ADMITTED = "admitted"
    FEATURE_GATED = "feature_gated"


class PreservationKind(StrEnum):
    """Coarse preservation claim for an extension route."""

    LOSSLESS = "lossless"
    SOUND_OVER = "sound_over_approximation"
    SOUND_UNDER = "sound_under_approximation"
    EQUISATISFIABLE = "equisatisfiable"
    BOUNDED = "bounded"
    HEURISTIC = "heuristic"


class FamilyExtensionError(ValueError):
    """Raised when a family extension route is invalid."""


class DuplicateFamilyExtensionError(FamilyExtensionError):
    """Raised when a route id collides."""


class UnknownFamilyExtensionError(FamilyExtensionError, KeyError):
    """Raised when a route cannot be resolved."""


def _text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise FamilyExtensionError(
            f"{field_name} must be a non-empty trimmed string"
        )
    if "\x00" in value:
        raise FamilyExtensionError(f"{field_name} must not contain NUL bytes")
    return value


def _identifier(value: object, field_name: str) -> str:
    result = _text(value, field_name)
    if any(character.isspace() for character in result):
        raise FamilyExtensionError(
            f"{field_name} must not contain whitespace; got {result!r}"
        )
    return result


def _string_tuple(
    value: Sequence[str] | None,
    field_name: str,
    *,
    allow_empty: bool = True,
) -> tuple[str, ...]:
    if value is None:
        items: tuple[str, ...] = ()
    else:
        if isinstance(value, (str, bytes, bytearray)) or not isinstance(
            value, Sequence
        ):
            raise FamilyExtensionError(f"{field_name} must be a sequence of strings")
        items = tuple(_identifier(item, f"{field_name} item") for item in value)
        if len(set(items)) != len(items):
            raise FamilyExtensionError(f"{field_name} must not contain duplicates")
    if not items and not allow_empty:
        raise FamilyExtensionError(f"{field_name} must not be empty")
    return items


# ---------------------------------------------------------------------------
# Loss / authority receipt
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ExtensionLossReceipt:
    """Explicit loss and authority receipt for one extension route."""

    receipt_id: str
    preservation: PreservationKind | str
    authority_ceiling: str
    lost_features: tuple[str, ...] = ()
    lost_properties: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = ()
    notes: str = ""
    schema_version: str = LOSS_RECEIPT_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "receipt_id", _identifier(self.receipt_id, "receipt_id")
        )
        preservation = self.preservation
        if not isinstance(preservation, PreservationKind):
            try:
                preservation = PreservationKind(str(preservation))
            except ValueError as error:
                raise FamilyExtensionError(
                    f"unknown preservation {self.preservation!r}"
                ) from error
        object.__setattr__(self, "preservation", preservation)
        object.__setattr__(
            self,
            "authority_ceiling",
            _identifier(self.authority_ceiling, "authority_ceiling"),
        )
        object.__setattr__(
            self, "lost_features", _string_tuple(self.lost_features, "lost_features")
        )
        object.__setattr__(
            self,
            "lost_properties",
            _string_tuple(self.lost_properties, "lost_properties"),
        )
        object.__setattr__(
            self, "assumptions", _string_tuple(self.assumptions, "assumptions")
        )
        if self.schema_version != LOSS_RECEIPT_SCHEMA:
            raise FamilyExtensionError(
                f"unsupported ExtensionLossReceipt schema {self.schema_version!r}"
            )
        if (
            preservation is PreservationKind.LOSSLESS
            and (self.lost_features or self.lost_properties)
        ):
            raise FamilyExtensionError(
                f"lossless receipt {self.receipt_id!r} cannot declare losses"
            )

    def to_dict(self) -> dict[str, Any]:
        preservation = (
            self.preservation.value
            if isinstance(self.preservation, PreservationKind)
            else str(self.preservation)
        )
        return {
            "assumptions": list(self.assumptions),
            "authority_ceiling": self.authority_ceiling,
            "lost_features": list(self.lost_features),
            "lost_properties": list(self.lost_properties),
            "notes": self.notes,
            "preservation": preservation,
            "receipt_id": self.receipt_id,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ExtensionLossReceipt":
        if not isinstance(value, Mapping):
            raise FamilyExtensionError("ExtensionLossReceipt must be a mapping")
        return cls(
            receipt_id=str(value.get("receipt_id") or ""),
            preservation=str(value.get("preservation") or ""),
            authority_ceiling=str(value.get("authority_ceiling") or "none"),
            lost_features=tuple(value.get("lost_features") or ()),
            lost_properties=tuple(value.get("lost_properties") or ()),
            assumptions=tuple(value.get("assumptions") or ()),
            notes=str(value.get("notes") or ""),
            schema_version=str(value.get("schema_version") or LOSS_RECEIPT_SCHEMA),
        )


# ---------------------------------------------------------------------------
# Route descriptor
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FamilyExtensionRoute:
    """One reviewed Wave-2 family extension route."""

    route_id: str
    source_family_id: str
    source_profile_id: str
    target_id: str
    route_kind: RouteKind | str
    disposition: RouteDisposition | str
    required_features: tuple[str, ...]
    loss_receipt: ExtensionLossReceipt
    owner_task_id: str = FAMILY_EXTENSIONS_TASK_ID
    reviewed: bool = True
    notes: str = ""
    schema_version: str = FAMILY_EXTENSION_ROUTE_SCHEMA

    interface: ClassVar[str] = FAMILY_EXTENSION_ROUTES_INTERFACE

    def __post_init__(self) -> None:
        object.__setattr__(self, "route_id", _identifier(self.route_id, "route_id"))
        object.__setattr__(
            self,
            "source_family_id",
            _identifier(self.source_family_id, "source_family_id"),
        )
        object.__setattr__(
            self,
            "source_profile_id",
            _identifier(self.source_profile_id, "source_profile_id"),
        )
        object.__setattr__(self, "target_id", _identifier(self.target_id, "target_id"))

        route_kind = self.route_kind
        if not isinstance(route_kind, RouteKind):
            try:
                route_kind = RouteKind(str(route_kind))
            except ValueError as error:
                raise FamilyExtensionError(
                    f"unknown route_kind {self.route_kind!r}"
                ) from error
        object.__setattr__(self, "route_kind", route_kind)

        disposition = self.disposition
        if not isinstance(disposition, RouteDisposition):
            try:
                disposition = RouteDisposition(str(disposition))
            except ValueError as error:
                raise FamilyExtensionError(
                    f"unknown route disposition {self.disposition!r}"
                ) from error
        object.__setattr__(self, "disposition", disposition)

        object.__setattr__(
            self,
            "required_features",
            _string_tuple(self.required_features, "required_features"),
        )
        if not isinstance(self.loss_receipt, ExtensionLossReceipt):
            raise FamilyExtensionError("loss_receipt is required")
        object.__setattr__(
            self, "owner_task_id", _identifier(self.owner_task_id, "owner_task_id")
        )
        if not isinstance(self.reviewed, bool):
            raise FamilyExtensionError("reviewed must be a boolean")
        if not self.reviewed:
            raise FamilyExtensionError(
                f"route {self.route_id!r} must be reviewed before publication"
            )
        if self.schema_version != FAMILY_EXTENSION_ROUTE_SCHEMA:
            raise FamilyExtensionError(
                f"unsupported FamilyExtensionRoute schema {self.schema_version!r}"
            )

    @property
    def is_executable(self) -> bool:
        """True only when admitted and not declaration-only."""

        return self.disposition is RouteDisposition.ADMITTED

    def to_dict(self) -> dict[str, Any]:
        return {
            "disposition": (
                self.disposition.value
                if isinstance(self.disposition, RouteDisposition)
                else str(self.disposition)
            ),
            "is_executable": self.is_executable,
            "loss_receipt": self.loss_receipt.to_dict(),
            "notes": self.notes,
            "owner_task_id": self.owner_task_id,
            "required_features": list(self.required_features),
            "reviewed": self.reviewed,
            "route_id": self.route_id,
            "route_kind": (
                self.route_kind.value
                if isinstance(self.route_kind, RouteKind)
                else str(self.route_kind)
            ),
            "schema_version": self.schema_version,
            "source_family_id": self.source_family_id,
            "source_profile_id": self.source_profile_id,
            "target_id": self.target_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "FamilyExtensionRoute":
        if not isinstance(value, Mapping):
            raise FamilyExtensionError("FamilyExtensionRoute must be a mapping")
        receipt_raw = value.get("loss_receipt") or {}
        return cls(
            route_id=str(value.get("route_id") or ""),
            source_family_id=str(value.get("source_family_id") or ""),
            source_profile_id=str(value.get("source_profile_id") or ""),
            target_id=str(value.get("target_id") or ""),
            route_kind=str(value.get("route_kind") or ""),
            disposition=str(value.get("disposition") or ""),
            required_features=tuple(value.get("required_features") or ()),
            loss_receipt=(
                receipt_raw
                if isinstance(receipt_raw, ExtensionLossReceipt)
                else ExtensionLossReceipt.from_dict(
                    receipt_raw if isinstance(receipt_raw, Mapping) else {}
                )
            ),
            owner_task_id=str(
                value.get("owner_task_id") or FAMILY_EXTENSIONS_TASK_ID
            ),
            reviewed=bool(value.get("reviewed", True)),
            notes=str(value.get("notes") or ""),
            schema_version=str(
                value.get("schema_version") or FAMILY_EXTENSION_ROUTE_SCHEMA
            ),
        )


def _receipt(
    receipt_id: str,
    preservation: PreservationKind,
    authority: str,
    *,
    lost_features: Sequence[str] = (),
    lost_properties: Sequence[str] = (),
    assumptions: Sequence[str] = (),
    notes: str = "",
) -> ExtensionLossReceipt:
    return ExtensionLossReceipt(
        receipt_id=receipt_id,
        preservation=preservation,
        authority_ceiling=authority,
        lost_features=tuple(lost_features),
        lost_properties=tuple(lost_properties),
        assumptions=tuple(assumptions),
        notes=notes,
    )


def _route(
    route_id: str,
    source_family: str,
    source_profile: str,
    target: str,
    *,
    route_kind: RouteKind,
    disposition: RouteDisposition,
    required_features: Sequence[str],
    receipt: ExtensionLossReceipt,
    notes: str = "",
) -> FamilyExtensionRoute:
    return FamilyExtensionRoute(
        route_id=route_id,
        source_family_id=source_family,
        source_profile_id=source_profile,
        target_id=target,
        route_kind=route_kind,
        disposition=disposition,
        required_features=tuple(required_features),
        loss_receipt=receipt,
        notes=notes,
    )


def _seed_extension_routes() -> tuple[FamilyExtensionRoute, ...]:
    """Reviewed Wave-2 family-to-family / provider / overlay routes."""

    parse_print = ("parse", "print")
    parse_eval = ("parse", "print", "evaluate")

    return (
        # Normative → deontic monadic / FOL views
        _route(
            "ext:normative_dyadic_to_deontic_monadic",
            "deontic",
            "normative_dyadic",
            "deontic",
            route_kind=RouteKind.FAMILY,
            disposition=RouteDisposition.FEATURE_GATED,
            required_features=parse_print,
            receipt=_receipt(
                "loss:normative_dyadic_to_monadic",
                PreservationKind.SOUND_OVER,
                "advisory",
                lost_features=("evaluate",),
                lost_properties=("conditional_norm",),
                assumptions=("drop_condition_to_monadic_obligation",),
                notes="Dyadic condition is over-approximated away.",
            ),
        ),
        _route(
            "ext:normative_prioritized_to_authorization",
            "deontic",
            "normative_prioritized",
            "authorization",
            route_kind=RouteKind.FAMILY,
            disposition=RouteDisposition.FEATURE_GATED,
            required_features=parse_print,
            receipt=_receipt(
                "loss:normative_prioritized_to_authorization",
                PreservationKind.BOUNDED,
                "bounded",
                lost_properties=("contrary_to_duty", "defeasible_exception"),
                assumptions=("priority_as_policy_order",),
            ),
        ),
        # Argumentation → rule / datalog views
        _route(
            "ext:argumentation_grounded_to_datalog",
            "argumentation",
            "argumentation_grounded",
            "datalog",
            route_kind=RouteKind.FAMILY,
            disposition=RouteDisposition.FEATURE_GATED,
            required_features=parse_print,
            receipt=_receipt(
                "loss:argumentation_grounded_to_datalog",
                PreservationKind.SOUND_UNDER,
                "advisory",
                lost_properties=("undecided_label", "multi_extension"),
                assumptions=("grounded_as_least_fixed_point",),
            ),
        ),
        _route(
            "ext:nonmonotonic_defeasible_to_rules",
            "nonmonotonic_logic",
            "nonmonotonic_defeasible",
            "datalog",
            route_kind=RouteKind.FAMILY,
            disposition=RouteDisposition.FEATURE_GATED,
            required_features=parse_print,
            receipt=_receipt(
                "loss:nonmonotonic_defeasible_to_rules",
                PreservationKind.HEURISTIC,
                "none",
                lost_properties=("defeasible_priority",),
                assumptions=("strict_rules_only",),
            ),
        ),
        # Description logic → frame / FOL
        _route(
            "ext:dl_alc_to_first_order",
            "description_logic",
            "dl_alc",
            "first_order",
            route_kind=RouteKind.FAMILY,
            disposition=RouteDisposition.FEATURE_GATED,
            required_features=parse_print,
            receipt=_receipt(
                "loss:dl_alc_to_first_order",
                PreservationKind.EQUISATISFIABLE,
                "advisory",
                assumptions=("standard_translation", "open_world"),
                notes="Never claims complete OWL.",
            ),
        ),
        _route(
            "ext:ontology_legal_to_frame_logic",
            "description_logic",
            "ontology_legal_alcq",
            "frame_logic",
            route_kind=RouteKind.FAMILY,
            disposition=RouteDisposition.FEATURE_GATED,
            required_features=parse_print,
            receipt=_receipt(
                "loss:ontology_legal_to_frame_logic",
                PreservationKind.SOUND_OVER,
                "advisory",
                lost_properties=("qualified_number_restriction",),
                assumptions=("frame_as_concept_role_view",),
            ),
        ),
        # Agency / BDI → modal / DCEC hooks
        _route(
            "ext:bdi_to_doxastic_modal",
            "bdi",
            "bdi_default",
            "modal",
            route_kind=RouteKind.FAMILY,
            disposition=RouteDisposition.FEATURE_GATED,
            required_features=parse_print,
            receipt=_receipt(
                "loss:bdi_to_doxastic_modal",
                PreservationKind.SOUND_OVER,
                "advisory",
                lost_properties=("intention", "desire"),
                assumptions=("belief_as_kd45_box", "not_dcec"),
            ),
        ),
        _route(
            "ext:epistemic_temporal_to_temporal",
            "epistemic_temporal",
            "epistemic_temporal_default",
            "temporal",
            route_kind=RouteKind.FAMILY,
            disposition=RouteDisposition.FEATURE_GATED,
            required_features=parse_print,
            receipt=_receipt(
                "loss:epistemic_temporal_to_temporal",
                PreservationKind.BOUNDED,
                "bounded",
                lost_properties=("agent_index", "knowledge_operator"),
                assumptions=("drop_epistemic_modalities",),
            ),
        ),
        _route(
            "ext:agency_to_dcec_importer",
            "agency",
            "agency_default",
            "dcec",
            route_kind=RouteKind.FAMILY,
            disposition=RouteDisposition.DECLARATION_ONLY,
            required_features=parse_print,
            receipt=_receipt(
                "loss:agency_to_dcec_importer",
                PreservationKind.HEURISTIC,
                "none",
                assumptions=("explicit_dcec_importer_hook_required",),
                notes="BDI/agency never silently become DCEC.",
            ),
        ),
        # Mu-calculus → temporal / transition systems
        _route(
            "ext:mu_calculus_to_temporal",
            "mu_calculus",
            "mu_calculus_guarded",
            "temporal",
            route_kind=RouteKind.FAMILY,
            disposition=RouteDisposition.FEATURE_GATED,
            required_features=parse_print,
            receipt=_receipt(
                "loss:mu_calculus_to_temporal",
                PreservationKind.BOUNDED,
                "bounded",
                lost_properties=("greatest_fixed_point", "alternation"),
                assumptions=("guarded_fragment", "finite_alternation"),
            ),
        ),
        _route(
            "ext:ctl_star_fragment_to_transition_system",
            "mu_calculus",
            "ctl_star_fragment_to_mu",
            "transition_system",
            route_kind=RouteKind.FAMILY,
            disposition=RouteDisposition.FEATURE_GATED,
            required_features=parse_print,
            receipt=_receipt(
                "loss:ctl_star_fragment_to_transition_system",
                PreservationKind.SOUND_OVER,
                "bounded",
                lost_properties=("full_ctl_star",),
                assumptions=("state_formula_fragment_only",),
            ),
        ),
        _route(
            "ext:mu_declaration_only_blocks_model_check",
            "mu_calculus",
            "mu_calculus_declaration_only",
            "model_check",
            route_kind=RouteKind.PROVIDER,
            disposition=RouteDisposition.DECLARATION_ONLY,
            required_features=(),
            receipt=_receipt(
                "loss:mu_declaration_only_blocks_model_check",
                PreservationKind.HEURISTIC,
                "none",
                assumptions=("declaration_never_implies_executable_support",),
            ),
            notes="Presence never authorizes model-check execution.",
        ),
        # Finite-field → SMT / never ZK authority
        _route(
            "ext:finite_field_to_smt_z3",
            "finite_field_constraint",
            "finite_field_bn254",
            "z3",
            route_kind=RouteKind.PROVIDER,
            disposition=RouteDisposition.FEATURE_GATED,
            required_features=parse_print,
            receipt=_receipt(
                "loss:finite_field_to_smt_z3",
                PreservationKind.EQUISATISFIABLE,
                "bounded",
                assumptions=("modular_arithmetic_encoding",),
                notes="SMT evidence is not ZK proof authority.",
            ),
        ),
        _route(
            "ext:r1cs_to_smt_cvc5",
            "finite_field_constraint",
            "r1cs_field",
            "cvc5",
            route_kind=RouteKind.PROVIDER,
            disposition=RouteDisposition.FEATURE_GATED,
            required_features=parse_print,
            receipt=_receipt(
                "loss:r1cs_to_smt_cvc5",
                PreservationKind.BOUNDED,
                "bounded",
                lost_properties=("zk_proof",),
                assumptions=("circuit_as_polynomial_constraints",),
            ),
        ),
        _route(
            "ext:plonk_blocks_zk_authority",
            "finite_field_constraint",
            "plonk_field",
            "zk_proof_authority",
            route_kind=RouteKind.PROVIDER,
            disposition=RouteDisposition.DECLARATION_ONLY,
            required_features=parse_print,
            receipt=_receipt(
                "loss:plonk_blocks_zk_authority",
                PreservationKind.HEURISTIC,
                "none",
                assumptions=("constraint_syntax_is_not_proof",),
                notes="Simulated/arithmetic evidence cannot become ZK authority.",
            ),
        ),
        # Session/process → protocol / concurrency / refinement
        _route(
            "ext:session_to_protocol",
            "session_process",
            "session_default",
            "cryptographic_protocol",
            route_kind=RouteKind.FAMILY,
            disposition=RouteDisposition.FEATURE_GATED,
            required_features=parse_print,
            receipt=_receipt(
                "loss:session_to_protocol",
                PreservationKind.SOUND_OVER,
                "advisory",
                lost_properties=("linear_resource",),
                assumptions=("session_as_protocol_role",),
            ),
        ),
        _route(
            "ext:process_to_concurrency",
            "process_calculus",
            "process_default",
            "concurrency",
            route_kind=RouteKind.FAMILY,
            disposition=RouteDisposition.FEATURE_GATED,
            required_features=parse_print,
            receipt=_receipt(
                "loss:process_to_concurrency",
                PreservationKind.BOUNDED,
                "bounded",
                assumptions=("fair_progress_model",),
            ),
        ),
        _route(
            "ext:linear_to_separation",
            "linear_logic",
            "linear_default",
            "separation_logic",
            route_kind=RouteKind.FAMILY,
            disposition=RouteDisposition.FEATURE_GATED,
            required_features=parse_print,
            receipt=_receipt(
                "loss:linear_to_separation",
                PreservationKind.SOUND_UNDER,
                "advisory",
                lost_properties=("ofcourse_modality",),
                assumptions=("strict_linearity", "no_resource_duplication"),
            ),
        ),
        _route(
            "ext:refinement_to_program",
            "refinement",
            "relational_refinement_default",
            "program",
            route_kind=RouteKind.FAMILY,
            disposition=RouteDisposition.FEATURE_GATED,
            required_features=parse_print,
            receipt=_receipt(
                "loss:refinement_to_program",
                PreservationKind.BOUNDED,
                "bounded",
                assumptions=("forward_refinement_direction",),
            ),
        ),
        # Domain-overlay stubs receipted here; concrete bindings in
        # domain_family_bindings_v2.
        _route(
            "ext:normative_to_legal_overlay",
            "deontic",
            "normative_defeasible",
            "legal_ir",
            route_kind=RouteKind.DOMAIN_OVERLAY,
            disposition=RouteDisposition.ADMITTED,
            required_features=parse_eval,
            receipt=_receipt(
                "loss:normative_to_legal_overlay",
                PreservationKind.BOUNDED,
                "bounded",
                assumptions=("legal_defeasibility_axis_explicit",),
            ),
        ),
        _route(
            "ext:argumentation_to_legal_overlay",
            "argumentation",
            "argumentation_preferred",
            "legal_ir",
            route_kind=RouteKind.DOMAIN_OVERLAY,
            disposition=RouteDisposition.ADMITTED,
            required_features=parse_eval,
            receipt=_receipt(
                "loss:argumentation_to_legal_overlay",
                PreservationKind.BOUNDED,
                "advisory",
                assumptions=("multi_extension_preserved",),
            ),
        ),
        _route(
            "ext:dl_to_legal_overlay",
            "description_logic",
            "ontology_legal_alcq",
            "legal_ir",
            route_kind=RouteKind.DOMAIN_OVERLAY,
            disposition=RouteDisposition.ADMITTED,
            required_features=parse_print,
            receipt=_receipt(
                "loss:dl_to_legal_overlay",
                PreservationKind.SOUND_OVER,
                "advisory",
                assumptions=("open_world_legal_ontology",),
            ),
        ),
        _route(
            "ext:bdi_to_intent_overlay",
            "bdi",
            "bdi_default",
            "intent_ir",
            route_kind=RouteKind.DOMAIN_OVERLAY,
            disposition=RouteDisposition.ADMITTED,
            required_features=parse_print,
            receipt=_receipt(
                "loss:bdi_to_intent_overlay",
                PreservationKind.BOUNDED,
                "advisory",
                assumptions=("goal_desire_intention_axes", "not_advisor_confidence"),
            ),
        ),
        _route(
            "ext:agency_to_intent_overlay",
            "agency",
            "agency_default",
            "intent_ir",
            route_kind=RouteKind.DOMAIN_OVERLAY,
            disposition=RouteDisposition.ADMITTED,
            required_features=parse_print,
            receipt=_receipt(
                "loss:agency_to_intent_overlay",
                PreservationKind.BOUNDED,
                "advisory",
                assumptions=("agent_action_goal_indices",),
            ),
        ),
        _route(
            "ext:finite_field_to_crypto_overlay",
            "finite_field_constraint",
            "finite_field_constraint_mixed",
            "crypto_ir",
            route_kind=RouteKind.DOMAIN_OVERLAY,
            disposition=RouteDisposition.ADMITTED,
            required_features=parse_print,
            receipt=_receipt(
                "loss:finite_field_to_crypto_overlay",
                PreservationKind.BOUNDED,
                "bounded",
                lost_properties=("zk_proof",),
                assumptions=("modulus_range_bitwidth_explicit",),
            ),
        ),
        _route(
            "ext:session_to_software_overlay",
            "session_process",
            "session_default",
            "software_verification",
            route_kind=RouteKind.DOMAIN_OVERLAY,
            disposition=RouteDisposition.ADMITTED,
            required_features=parse_print,
            receipt=_receipt(
                "loss:session_to_software_overlay",
                PreservationKind.BOUNDED,
                "advisory",
                assumptions=("duality_progress_refinement_checked",),
            ),
        ),
        _route(
            "ext:process_to_software_overlay",
            "process_calculus",
            "process_default",
            "software_verification",
            route_kind=RouteKind.DOMAIN_OVERLAY,
            disposition=RouteDisposition.ADMITTED,
            required_features=parse_print,
            receipt=_receipt(
                "loss:process_to_software_overlay",
                PreservationKind.BOUNDED,
                "advisory",
                assumptions=("fair_progress_model", "process_scope"),
            ),
        ),
    )


# ---------------------------------------------------------------------------
# Catalog
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FamilyExtensionRouteCatalog:
    """Sealed catalog of reviewed Wave-2 family extension routes."""

    routes: tuple[FamilyExtensionRoute, ...]
    version: str = FAMILY_EXTENSIONS_MODULE_VERSION
    task_id: str = FAMILY_EXTENSIONS_TASK_ID
    goal_id: str = FAMILY_EXTENSIONS_GOAL_ID
    schema_version: str = FAMILY_EXTENSION_CATALOG_SCHEMA

    interface: ClassVar[str] = FAMILY_EXTENSION_ROUTES_INTERFACE
    publication_interface: ClassVar[str] = FAMILY_ROUTE_PUBLICATION_INTERFACE

    def __post_init__(self) -> None:
        if not self.routes:
            raise FamilyExtensionError(
                "FamilyExtensionRouteCatalog requires at least one route"
            )
        seen: set[str] = set()
        for route in self.routes:
            if not isinstance(route, FamilyExtensionRoute):
                raise FamilyExtensionError(
                    "routes must be FamilyExtensionRoute instances"
                )
            if route.route_id in seen:
                raise DuplicateFamilyExtensionError(
                    f"duplicate route {route.route_id!r}"
                )
            seen.add(route.route_id)
        ordered = tuple(sorted(self.routes, key=lambda item: item.route_id))
        object.__setattr__(self, "routes", ordered)
        object.__setattr__(self, "version", _text(self.version, "version"))
        object.__setattr__(self, "task_id", _identifier(self.task_id, "task_id"))
        object.__setattr__(self, "goal_id", _identifier(self.goal_id, "goal_id"))
        if self.schema_version != FAMILY_EXTENSION_CATALOG_SCHEMA:
            raise FamilyExtensionError(
                f"unsupported catalog schema {self.schema_version!r}"
            )

    @property
    def route_ids(self) -> tuple[str, ...]:
        return tuple(route.route_id for route in self.routes)

    @property
    def admitted_route_ids(self) -> tuple[str, ...]:
        return tuple(
            route.route_id
            for route in self.routes
            if route.disposition is RouteDisposition.ADMITTED
        )

    def get(self, route_id: str) -> FamilyExtensionRoute:
        key = _identifier(route_id, "route_id")
        for route in self.routes:
            if route.route_id == key:
                return route
        raise UnknownFamilyExtensionError(f"unknown route {key!r}")

    def routes_for_source(self, family_id: str) -> tuple[FamilyExtensionRoute, ...]:
        key = _identifier(family_id, "family_id")
        return tuple(
            route for route in self.routes if route.source_family_id == key
        )

    def routes_for_kind(self, kind: RouteKind | str) -> tuple[FamilyExtensionRoute, ...]:
        selected = kind if isinstance(kind, RouteKind) else RouteKind(str(kind))
        return tuple(route for route in self.routes if route.route_kind is selected)

    def presence_implies_executability(self) -> bool:
        return False

    def validate_feature_compatibility(
        self,
        *,
        registry: LogicFamilyRegistryV3 | None = None,
        profiles: LogicProfileCatalogV3 | None = None,
    ) -> None:
        """Every admitted/feature-gated route must be feature-compatible."""

        reg = registry if registry is not None else DEFAULT_REGISTRY_V3
        cat = profiles if profiles is not None else DEFAULT_PROFILE_CATALOG_V3

        for route in self.routes:
            if route.source_family_id not in reg:
                raise FamilyExtensionError(
                    f"route {route.route_id!r} source family "
                    f"{route.source_family_id!r} is not published"
                )
            if route.source_profile_id not in cat:
                raise FamilyExtensionError(
                    f"route {route.route_id!r} source profile "
                    f"{route.source_profile_id!r} is not published"
                )
            profile = cat.get(route.source_profile_id)
            family = reg.get(route.source_family_id)

            # Profile must belong to the source family (shared-profile exception).
            if (
                profile.family_id != route.source_family_id
                and route.source_profile_id != "nonmonotonic_defeasible"
            ):
                raise FamilyExtensionError(
                    f"route {route.route_id!r} profile/family mismatch"
                )

            required = set(route.required_features)
            available = set(profile.feature_ids) | set(family.feature_ids)
            missing = sorted(required - available)
            if missing and route.disposition is not RouteDisposition.DECLARATION_ONLY:
                raise FamilyExtensionError(
                    f"route {route.route_id!r} requires features not published: "
                    + ", ".join(missing)
                )

            # Declaration-only profiles cannot host admitted executable routes.
            if profile.is_declaration_only and route.is_executable:
                raise FamilyExtensionError(
                    f"declaration_only profile {profile.profile_id!r} cannot "
                    f"host admitted route {route.route_id!r}"
                )

            # Every non-declaration route must carry a loss/authority receipt.
            if not route.loss_receipt.receipt_id:
                raise FamilyExtensionError(
                    f"route {route.route_id!r} missing loss receipt id"
                )
            if not route.loss_receipt.authority_ceiling:
                raise FamilyExtensionError(
                    f"route {route.route_id!r} missing authority ceiling"
                )

    def __contains__(self, route_id: object) -> bool:
        if not isinstance(route_id, str):
            return False
        return route_id in set(self.route_ids)

    def __iter__(self) -> Iterator[FamilyExtensionRoute]:
        return iter(self.routes)

    def __len__(self) -> int:
        return len(self.routes)

    def to_dict(self) -> dict[str, Any]:
        return {
            "admitted_route_ids": list(self.admitted_route_ids),
            "goal_id": self.goal_id,
            "interface": self.interface,
            "presence_implies_executability": self.presence_implies_executability(),
            "publication_interface": self.publication_interface,
            "route_ids": list(self.route_ids),
            "routes": [route.to_dict() for route in self.routes],
            "schema_version": self.schema_version,
            "task_id": self.task_id,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "FamilyExtensionRouteCatalog":
        if not isinstance(value, Mapping):
            raise FamilyExtensionError(
                "FamilyExtensionRouteCatalog must be a mapping"
            )
        raw = value.get("routes") or ()
        routes = tuple(
            item
            if isinstance(item, FamilyExtensionRoute)
            else FamilyExtensionRoute.from_dict(item)
            for item in raw
        )
        return cls(
            routes=routes,
            version=str(value.get("version") or FAMILY_EXTENSIONS_MODULE_VERSION),
            task_id=str(value.get("task_id") or FAMILY_EXTENSIONS_TASK_ID),
            goal_id=str(value.get("goal_id") or FAMILY_EXTENSIONS_GOAL_ID),
            schema_version=str(
                value.get("schema_version") or FAMILY_EXTENSION_CATALOG_SCHEMA
            ),
        )


def build_default_family_extension_routes(
    *,
    validate: bool = True,
) -> FamilyExtensionRouteCatalog:
    catalog = FamilyExtensionRouteCatalog(routes=_seed_extension_routes())
    if validate:
        catalog.validate_feature_compatibility()
    return catalog


DEFAULT_FAMILY_EXTENSION_ROUTES: Final = build_default_family_extension_routes(
    validate=True
)

# Alias used by FamilyRoutePublication@1 consumers.
FamilyRoutePublication = FamilyExtensionRouteCatalog


__all__ = [
    "DEFAULT_FAMILY_EXTENSION_ROUTES",
    "DuplicateFamilyExtensionError",
    "ExtensionLossReceipt",
    "FAMILY_EXTENSIONS_GOAL_ID",
    "FAMILY_EXTENSIONS_MODULE_VERSION",
    "FAMILY_EXTENSIONS_TASK_ID",
    "FAMILY_EXTENSION_CATALOG_SCHEMA",
    "FAMILY_EXTENSION_ROUTES_INTERFACE",
    "FAMILY_EXTENSION_ROUTE_SCHEMA",
    "FAMILY_ROUTE_PUBLICATION_INTERFACE",
    "FamilyExtensionError",
    "FamilyExtensionRoute",
    "FamilyExtensionRouteCatalog",
    "FamilyRoutePublication",
    "LOSS_RECEIPT_SCHEMA",
    "PreservationKind",
    "RouteDisposition",
    "RouteKind",
    "UnknownFamilyExtensionError",
    "build_default_family_extension_routes",
]
