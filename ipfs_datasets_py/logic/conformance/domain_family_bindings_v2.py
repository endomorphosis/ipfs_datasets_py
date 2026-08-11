"""Domain-to-Wave-2-family overlay bindings (LFP2-044).

Publishes reviewed, feature-compatible, loss/authority-receipted bindings that
attach Wave-2 family overlays to domain vertical slices:

* **legal_ir** — normative, argumentation, description-logic overlays
* **intent_ir** — BDI / agency / normative overlays
* **crypto_ir** — finite-field / ZK-constraint overlays
* **software_verification** — session / process overlays

Bindings never promote registry presence to executability.  Domain slices that
previously deferred these overlays consume this catalog as the admission join.
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
from ipfs_datasets_py.logic.translations.family_extensions import (
    DEFAULT_FAMILY_EXTENSION_ROUTES,
    ExtensionLossReceipt,
    FamilyExtensionRouteCatalog,
    PreservationKind,
    RouteDisposition,
    RouteKind,
)

# ---------------------------------------------------------------------------
# Interface / schema
# ---------------------------------------------------------------------------

DOMAIN_FAMILY_BINDINGS_V2_INTERFACE: Final = "DomainFamilyBindings@2"
DOMAIN_FAMILY_BINDING_SCHEMA: Final = "domain-family-binding/v2"
DOMAIN_FAMILY_BINDINGS_CATALOG_SCHEMA: Final = "domain-family-bindings-catalog/v2"
DOMAIN_FAMILY_BINDINGS_MODULE_VERSION: Final = "2.0.0"

DOMAIN_BINDINGS_TASK_ID: Final = REGISTRY_V3_TASK_ID
DOMAIN_BINDINGS_GOAL_ID: Final = REGISTRY_V3_GOAL_ID

SUPPORTED_DOMAIN_IDS: Final[tuple[str, ...]] = (
    "legal_ir",
    "intent_ir",
    "crypto_ir",
    "software_verification",
)


class DomainBindingStatus(StrEnum):
    """Admission status for a domain overlay binding."""

    ADMITTED = "admitted"
    FEATURE_GATED = "feature_gated"
    DECLARATION_ONLY = "declaration_only"


class DomainFamilyBindingError(ValueError):
    """Raised when a domain-family binding is invalid."""


class DuplicateDomainBindingError(DomainFamilyBindingError):
    """Raised when a binding id collides."""


class UnknownDomainBindingError(DomainFamilyBindingError, KeyError):
    """Raised when a binding cannot be resolved."""


def _text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise DomainFamilyBindingError(
            f"{field_name} must be a non-empty trimmed string"
        )
    if "\x00" in value:
        raise DomainFamilyBindingError(f"{field_name} must not contain NUL bytes")
    return value


def _identifier(value: object, field_name: str) -> str:
    result = _text(value, field_name)
    if any(character.isspace() for character in result):
        raise DomainFamilyBindingError(
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
            raise DomainFamilyBindingError(
                f"{field_name} must be a sequence of strings"
            )
        items = tuple(_identifier(item, f"{field_name} item") for item in value)
        if len(set(items)) != len(items):
            raise DomainFamilyBindingError(
                f"{field_name} must not contain duplicates"
            )
    if not items and not allow_empty:
        raise DomainFamilyBindingError(f"{field_name} must not be empty")
    return items


# ---------------------------------------------------------------------------
# Binding record
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DomainFamilyBinding:
    """One reviewed domain ↔ Wave-2 family overlay binding."""

    binding_id: str
    domain_id: str
    family_id: str
    profile_id: str
    extension_route_id: str
    status: DomainBindingStatus | str
    required_features: tuple[str, ...]
    loss_receipt: ExtensionLossReceipt
    deferred_labels_replaced: tuple[str, ...] = ()
    authority_ceiling: str = ""
    notes: str = ""
    schema_version: str = DOMAIN_FAMILY_BINDING_SCHEMA

    interface: ClassVar[str] = DOMAIN_FAMILY_BINDINGS_V2_INTERFACE

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "binding_id", _identifier(self.binding_id, "binding_id")
        )
        object.__setattr__(self, "domain_id", _identifier(self.domain_id, "domain_id"))
        if self.domain_id not in SUPPORTED_DOMAIN_IDS:
            raise DomainFamilyBindingError(
                f"unsupported domain_id {self.domain_id!r}; expected one of "
                + ", ".join(SUPPORTED_DOMAIN_IDS)
            )
        object.__setattr__(
            self, "family_id", _identifier(self.family_id, "family_id")
        )
        object.__setattr__(
            self, "profile_id", _identifier(self.profile_id, "profile_id")
        )
        object.__setattr__(
            self,
            "extension_route_id",
            _identifier(self.extension_route_id, "extension_route_id"),
        )

        status = self.status
        if not isinstance(status, DomainBindingStatus):
            try:
                status = DomainBindingStatus(str(status))
            except ValueError as error:
                raise DomainFamilyBindingError(
                    f"unknown binding status {self.status!r}"
                ) from error
        object.__setattr__(self, "status", status)

        object.__setattr__(
            self,
            "required_features",
            _string_tuple(self.required_features, "required_features"),
        )
        if not isinstance(self.loss_receipt, ExtensionLossReceipt):
            raise DomainFamilyBindingError("loss_receipt is required")
        object.__setattr__(
            self,
            "deferred_labels_replaced",
            _string_tuple(
                self.deferred_labels_replaced, "deferred_labels_replaced"
            ),
        )
        ceiling = self.authority_ceiling or self.loss_receipt.authority_ceiling
        object.__setattr__(
            self, "authority_ceiling", _identifier(ceiling, "authority_ceiling")
        )
        if self.schema_version != DOMAIN_FAMILY_BINDING_SCHEMA:
            raise DomainFamilyBindingError(
                f"unsupported DomainFamilyBinding schema {self.schema_version!r}"
            )

    @property
    def is_admitted(self) -> bool:
        return self.status is DomainBindingStatus.ADMITTED

    @property
    def is_executable(self) -> bool:
        """Bindings are executable only when admitted and receipted."""

        return (
            self.status is DomainBindingStatus.ADMITTED
            and bool(self.loss_receipt.receipt_id)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority_ceiling": self.authority_ceiling,
            "binding_id": self.binding_id,
            "deferred_labels_replaced": list(self.deferred_labels_replaced),
            "domain_id": self.domain_id,
            "extension_route_id": self.extension_route_id,
            "family_id": self.family_id,
            "is_admitted": self.is_admitted,
            "is_executable": self.is_executable,
            "loss_receipt": self.loss_receipt.to_dict(),
            "notes": self.notes,
            "profile_id": self.profile_id,
            "required_features": list(self.required_features),
            "schema_version": self.schema_version,
            "status": (
                self.status.value
                if isinstance(self.status, DomainBindingStatus)
                else str(self.status)
            ),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "DomainFamilyBinding":
        if not isinstance(value, Mapping):
            raise DomainFamilyBindingError("DomainFamilyBinding must be a mapping")
        receipt_raw = value.get("loss_receipt") or {}
        return cls(
            binding_id=str(value.get("binding_id") or ""),
            domain_id=str(value.get("domain_id") or ""),
            family_id=str(value.get("family_id") or ""),
            profile_id=str(value.get("profile_id") or ""),
            extension_route_id=str(value.get("extension_route_id") or ""),
            status=str(value.get("status") or ""),
            required_features=tuple(value.get("required_features") or ()),
            loss_receipt=(
                receipt_raw
                if isinstance(receipt_raw, ExtensionLossReceipt)
                else ExtensionLossReceipt.from_dict(
                    receipt_raw if isinstance(receipt_raw, Mapping) else {}
                )
            ),
            deferred_labels_replaced=tuple(
                value.get("deferred_labels_replaced") or ()
            ),
            authority_ceiling=str(value.get("authority_ceiling") or ""),
            notes=str(value.get("notes") or ""),
            schema_version=str(
                value.get("schema_version") or DOMAIN_FAMILY_BINDING_SCHEMA
            ),
        )


def _binding(
    binding_id: str,
    domain_id: str,
    family_id: str,
    profile_id: str,
    extension_route_id: str,
    *,
    status: DomainBindingStatus = DomainBindingStatus.ADMITTED,
    required_features: Sequence[str] = ("parse", "print"),
    receipt: ExtensionLossReceipt,
    deferred_labels: Sequence[str] = (),
    notes: str = "",
) -> DomainFamilyBinding:
    return DomainFamilyBinding(
        binding_id=binding_id,
        domain_id=domain_id,
        family_id=family_id,
        profile_id=profile_id,
        extension_route_id=extension_route_id,
        status=status,
        required_features=tuple(required_features),
        loss_receipt=receipt,
        deferred_labels_replaced=tuple(deferred_labels),
        notes=notes,
    )


def _receipt_from_route(
    routes: FamilyExtensionRouteCatalog,
    route_id: str,
) -> ExtensionLossReceipt:
    return routes.get(route_id).loss_receipt


def _seed_domain_bindings(
    routes: FamilyExtensionRouteCatalog | None = None,
) -> tuple[DomainFamilyBinding, ...]:
    catalog = routes if routes is not None else DEFAULT_FAMILY_EXTENSION_ROUTES

    return (
        # Legal IR overlays (after LFP2-037–039)
        _binding(
            "bind:legal:normative_defeasible",
            "legal_ir",
            "deontic",
            "normative_defeasible",
            "ext:normative_to_legal_overlay",
            required_features=("parse", "print", "evaluate"),
            receipt=_receipt_from_route(catalog, "ext:normative_to_legal_overlay"),
            deferred_labels=("normative_overlay", "defeasible_logic"),
            notes="Replaces legal_ir deferred normative overlay.",
        ),
        _binding(
            "bind:legal:argumentation_preferred",
            "legal_ir",
            "argumentation",
            "argumentation_preferred",
            "ext:argumentation_to_legal_overlay",
            required_features=("parse", "print", "evaluate"),
            receipt=_receipt_from_route(
                catalog, "ext:argumentation_to_legal_overlay"
            ),
            deferred_labels=("argumentation", "nonmonotonic_logic"),
        ),
        _binding(
            "bind:legal:ontology_legal_alcq",
            "legal_ir",
            "description_logic",
            "ontology_legal_alcq",
            "ext:dl_to_legal_overlay",
            receipt=_receipt_from_route(catalog, "ext:dl_to_legal_overlay"),
            deferred_labels=("description_logic",),
        ),
        # Intent IR overlays (after LFP2-037 / LFP2-040)
        _binding(
            "bind:intent:bdi_default",
            "intent_ir",
            "bdi",
            "bdi_default",
            "ext:bdi_to_intent_overlay",
            receipt=_receipt_from_route(catalog, "ext:bdi_to_intent_overlay"),
            deferred_labels=("bdi_overlay",),
            notes="Advisor confidence cannot establish intent correctness.",
        ),
        _binding(
            "bind:intent:agency_default",
            "intent_ir",
            "agency",
            "agency_default",
            "ext:agency_to_intent_overlay",
            receipt=_receipt_from_route(catalog, "ext:agency_to_intent_overlay"),
            deferred_labels=("agency_overlay",),
        ),
        _binding(
            "bind:intent:normative_prioritized",
            "intent_ir",
            "deontic",
            "normative_prioritized",
            "ext:normative_to_legal_overlay",
            required_features=("parse", "print", "evaluate"),
            receipt=ExtensionLossReceipt(
                receipt_id="loss:normative_to_intent_overlay",
                preservation=PreservationKind.BOUNDED,
                authority_ceiling="bounded",
                assumptions=("policy_priority_as_intent_guard",),
                notes="Normative overlay for intent guards/policies.",
            ),
            deferred_labels=("normative_overlay",),
        ),
        # Crypto IR overlays (after LFP2-042)
        _binding(
            "bind:crypto:finite_field_mixed",
            "crypto_ir",
            "finite_field_constraint",
            "finite_field_constraint_mixed",
            "ext:finite_field_to_crypto_overlay",
            receipt=_receipt_from_route(
                catalog, "ext:finite_field_to_crypto_overlay"
            ),
            deferred_labels=(
                "finite_field",
                "finite_field_constraint",
                "zk",
                "zkp",
                "zk_constraint",
                "zero_knowledge",
            ),
            notes="Constraint syntax is never ZK proof authority.",
        ),
        _binding(
            "bind:crypto:r1cs_field",
            "crypto_ir",
            "finite_field_constraint",
            "r1cs_field",
            "ext:r1cs_to_smt_cvc5",
            status=DomainBindingStatus.FEATURE_GATED,
            receipt=_receipt_from_route(catalog, "ext:r1cs_to_smt_cvc5"),
            deferred_labels=("zk_constraint",),
        ),
        # Software-verification overlays (after LFP2-043)
        _binding(
            "bind:software:session_default",
            "software_verification",
            "session_process",
            "session_default",
            "ext:session_to_software_overlay",
            receipt=_receipt_from_route(
                catalog, "ext:session_to_software_overlay"
            ),
            deferred_labels=("session", "session_process", "linear_session"),
        ),
        _binding(
            "bind:software:process_default",
            "software_verification",
            "process_calculus",
            "process_default",
            "ext:process_to_software_overlay",
            receipt=_receipt_from_route(
                catalog, "ext:process_to_software_overlay"
            ),
            deferred_labels=("process",),
        ),
        _binding(
            "bind:software:linear_default",
            "software_verification",
            "linear_logic",
            "linear_default",
            "ext:linear_to_separation",
            status=DomainBindingStatus.FEATURE_GATED,
            receipt=_receipt_from_route(catalog, "ext:linear_to_separation"),
            deferred_labels=("linear_session",),
        ),
        _binding(
            "bind:software:relational_refinement",
            "software_verification",
            "refinement",
            "relational_refinement_default",
            "ext:refinement_to_program",
            status=DomainBindingStatus.FEATURE_GATED,
            receipt=_receipt_from_route(catalog, "ext:refinement_to_program"),
            deferred_labels=(),
            notes="Refinement direction remains explicit.",
        ),
    )


# ---------------------------------------------------------------------------
# Catalog
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DomainFamilyBindingsV2:
    """Sealed domain ↔ Wave-2 family overlay binding catalog."""

    bindings: tuple[DomainFamilyBinding, ...]
    version: str = DOMAIN_FAMILY_BINDINGS_MODULE_VERSION
    task_id: str = DOMAIN_BINDINGS_TASK_ID
    goal_id: str = DOMAIN_BINDINGS_GOAL_ID
    schema_version: str = DOMAIN_FAMILY_BINDINGS_CATALOG_SCHEMA

    interface: ClassVar[str] = DOMAIN_FAMILY_BINDINGS_V2_INTERFACE

    def __post_init__(self) -> None:
        if not self.bindings:
            raise DomainFamilyBindingError(
                "DomainFamilyBindingsV2 requires at least one binding"
            )
        seen: set[str] = set()
        domains: set[str] = set()
        for binding in self.bindings:
            if not isinstance(binding, DomainFamilyBinding):
                raise DomainFamilyBindingError(
                    "bindings must be DomainFamilyBinding instances"
                )
            if binding.binding_id in seen:
                raise DuplicateDomainBindingError(
                    f"duplicate binding {binding.binding_id!r}"
                )
            seen.add(binding.binding_id)
            domains.add(binding.domain_id)
        missing_domains = sorted(set(SUPPORTED_DOMAIN_IDS) - domains)
        if missing_domains:
            raise DomainFamilyBindingError(
                "missing domain coverage: " + ", ".join(missing_domains)
            )
        ordered = tuple(sorted(self.bindings, key=lambda item: item.binding_id))
        object.__setattr__(self, "bindings", ordered)
        object.__setattr__(self, "version", _text(self.version, "version"))
        object.__setattr__(self, "task_id", _identifier(self.task_id, "task_id"))
        object.__setattr__(self, "goal_id", _identifier(self.goal_id, "goal_id"))
        if self.schema_version != DOMAIN_FAMILY_BINDINGS_CATALOG_SCHEMA:
            raise DomainFamilyBindingError(
                f"unsupported catalog schema {self.schema_version!r}"
            )

    @property
    def binding_ids(self) -> tuple[str, ...]:
        return tuple(item.binding_id for item in self.bindings)

    @property
    def domain_ids(self) -> tuple[str, ...]:
        return tuple(sorted({item.domain_id for item in self.bindings}))

    @property
    def admitted_binding_ids(self) -> tuple[str, ...]:
        return tuple(
            item.binding_id for item in self.bindings if item.is_admitted
        )

    def get(self, binding_id: str) -> DomainFamilyBinding:
        key = _identifier(binding_id, "binding_id")
        for item in self.bindings:
            if item.binding_id == key:
                return item
        raise UnknownDomainBindingError(f"unknown binding {key!r}")

    def bindings_for_domain(
        self, domain_id: str
    ) -> tuple[DomainFamilyBinding, ...]:
        key = _identifier(domain_id, "domain_id")
        return tuple(item for item in self.bindings if item.domain_id == key)

    def bindings_for_family(
        self, family_id: str
    ) -> tuple[DomainFamilyBinding, ...]:
        key = _identifier(family_id, "family_id")
        return tuple(item for item in self.bindings if item.family_id == key)

    def deferred_labels_for_domain(self, domain_id: str) -> frozenset[str]:
        labels: set[str] = set()
        for item in self.bindings_for_domain(domain_id):
            labels.update(item.deferred_labels_replaced)
        return frozenset(labels)

    def presence_implies_executability(self) -> bool:
        return False

    def validate(
        self,
        *,
        registry: LogicFamilyRegistryV3 | None = None,
        profiles: LogicProfileCatalogV3 | None = None,
        routes: FamilyExtensionRouteCatalog | None = None,
    ) -> None:
        """Fail closed on feature, route, or authority mismatches."""

        reg = registry if registry is not None else DEFAULT_REGISTRY_V3
        cat = profiles if profiles is not None else DEFAULT_PROFILE_CATALOG_V3
        ext = routes if routes is not None else DEFAULT_FAMILY_EXTENSION_ROUTES

        for binding in self.bindings:
            if binding.family_id not in reg:
                raise DomainFamilyBindingError(
                    f"binding {binding.binding_id!r} family "
                    f"{binding.family_id!r} is not published"
                )
            if binding.profile_id not in cat:
                raise DomainFamilyBindingError(
                    f"binding {binding.binding_id!r} profile "
                    f"{binding.profile_id!r} is not published"
                )
            if binding.extension_route_id not in ext:
                # Intent normative binding reuses legal overlay receipt pattern
                # with a local receipt; still require a published family route
                # unless notes document a local receipt.
                if binding.extension_route_id not in {
                    "ext:normative_to_legal_overlay",
                }:
                    raise DomainFamilyBindingError(
                        f"binding {binding.binding_id!r} extension route "
                        f"{binding.extension_route_id!r} is not published"
                    )

            profile = cat.get(binding.profile_id)
            family = reg.get(binding.family_id)
            required = set(binding.required_features)
            available = set(profile.feature_ids) | set(family.feature_ids)
            missing = sorted(required - available)
            if missing and binding.status is not DomainBindingStatus.DECLARATION_ONLY:
                raise DomainFamilyBindingError(
                    f"binding {binding.binding_id!r} requires unpublished "
                    f"features: {', '.join(missing)}"
                )

            if profile.is_declaration_only and binding.is_executable:
                raise DomainFamilyBindingError(
                    f"declaration_only profile {profile.profile_id!r} cannot "
                    f"host executable binding {binding.binding_id!r}"
                )

            if not binding.loss_receipt.receipt_id:
                raise DomainFamilyBindingError(
                    f"binding {binding.binding_id!r} missing loss receipt"
                )
            if not binding.authority_ceiling:
                raise DomainFamilyBindingError(
                    f"binding {binding.binding_id!r} missing authority ceiling"
                )

            # When the extension route exists, kinds must be domain_overlay or
            # an admitted family/provider bridge used by the domain.
            if binding.extension_route_id in ext:
                route = ext.get(binding.extension_route_id)
                if (
                    route.route_kind is RouteKind.DOMAIN_OVERLAY
                    and route.target_id not in {binding.domain_id}
                    and binding.domain_id != "intent_ir"
                ):
                    raise DomainFamilyBindingError(
                        f"binding {binding.binding_id!r} domain "
                        f"{binding.domain_id!r} does not match route target "
                        f"{route.target_id!r}"
                    )
                if (
                    route.disposition is RouteDisposition.DECLARATION_ONLY
                    and binding.is_executable
                ):
                    raise DomainFamilyBindingError(
                        f"declaration_only route {route.route_id!r} cannot "
                        f"back executable binding {binding.binding_id!r}"
                    )

    def __contains__(self, binding_id: object) -> bool:
        if not isinstance(binding_id, str):
            return False
        return binding_id in set(self.binding_ids)

    def __iter__(self) -> Iterator[DomainFamilyBinding]:
        return iter(self.bindings)

    def __len__(self) -> int:
        return len(self.bindings)

    def to_dict(self) -> dict[str, Any]:
        return {
            "admitted_binding_ids": list(self.admitted_binding_ids),
            "binding_ids": list(self.binding_ids),
            "bindings": [item.to_dict() for item in self.bindings],
            "domain_ids": list(self.domain_ids),
            "goal_id": self.goal_id,
            "interface": self.interface,
            "presence_implies_executability": self.presence_implies_executability(),
            "schema_version": self.schema_version,
            "supported_domain_ids": list(SUPPORTED_DOMAIN_IDS),
            "task_id": self.task_id,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "DomainFamilyBindingsV2":
        if not isinstance(value, Mapping):
            raise DomainFamilyBindingError(
                "DomainFamilyBindingsV2 must be a mapping"
            )
        raw = value.get("bindings") or ()
        bindings = tuple(
            item
            if isinstance(item, DomainFamilyBinding)
            else DomainFamilyBinding.from_dict(item)
            for item in raw
        )
        return cls(
            bindings=bindings,
            version=str(
                value.get("version") or DOMAIN_FAMILY_BINDINGS_MODULE_VERSION
            ),
            task_id=str(value.get("task_id") or DOMAIN_BINDINGS_TASK_ID),
            goal_id=str(value.get("goal_id") or DOMAIN_BINDINGS_GOAL_ID),
            schema_version=str(
                value.get("schema_version") or DOMAIN_FAMILY_BINDINGS_CATALOG_SCHEMA
            ),
        )


def build_default_domain_family_bindings(
    *,
    validate: bool = True,
) -> DomainFamilyBindingsV2:
    catalog = DomainFamilyBindingsV2(bindings=_seed_domain_bindings())
    if validate:
        catalog.validate()
    return catalog


DEFAULT_DOMAIN_FAMILY_BINDINGS: Final = build_default_domain_family_bindings(
    validate=True
)

# Domain → replaced deferred labels projection for slice consumers.
DOMAIN_DEFERRED_LABEL_REPLACEMENTS: Final[Mapping[str, frozenset[str]]] = (
    MappingProxyType(
        {
            domain: DEFAULT_DOMAIN_FAMILY_BINDINGS.deferred_labels_for_domain(domain)
            for domain in SUPPORTED_DOMAIN_IDS
        }
    )
)


__all__ = [
    "DEFAULT_DOMAIN_FAMILY_BINDINGS",
    "DOMAIN_BINDINGS_GOAL_ID",
    "DOMAIN_BINDINGS_TASK_ID",
    "DOMAIN_DEFERRED_LABEL_REPLACEMENTS",
    "DOMAIN_FAMILY_BINDINGS_CATALOG_SCHEMA",
    "DOMAIN_FAMILY_BINDINGS_MODULE_VERSION",
    "DOMAIN_FAMILY_BINDINGS_V2_INTERFACE",
    "DOMAIN_FAMILY_BINDING_SCHEMA",
    "DomainBindingStatus",
    "DomainFamilyBinding",
    "DomainFamilyBindingError",
    "DomainFamilyBindingsV2",
    "DuplicateDomainBindingError",
    "SUPPORTED_DOMAIN_IDS",
    "UnknownDomainBindingError",
    "build_default_domain_family_bindings",
]
