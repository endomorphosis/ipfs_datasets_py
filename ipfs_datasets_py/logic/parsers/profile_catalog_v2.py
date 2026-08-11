"""Published temporal, modal, and resource profile catalog (LFP2-015).

Interfaces:

* ``LogicProfileCatalog@2`` — sealed catalog of declared semantic profiles for
  temporal, modal, resource, TDFOL, and CEC/DCEC surfaces.  Every registered
  entry publishes shared ``ParseArtifact@2`` / ``ElaborationArtifact@2``
  outputs, overloaded-operator gates, and loss-receipt policy for legacy
  approximations.

Overloaded symbols (``O``/``P``/``F``, box/diamond, ``F``/``G``/``U``/``R``,
separating ``*``, and similar collisions) never resolve by spelling alone:
callers must select a catalog profile.  Legacy approximations cannot enter the
kernel without an explicit loss receipt bound to that profile.

This module does not rewrite the individual family parsers; it owns the join
catalog that makes those profiles discoverable and registration-gated under
``SharedFrontendConformance@1``.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any, ClassVar, Final

from ipfs_datasets_py.logic.parsers.frontend_contract import (
    FRONTEND_CONTRACT_GOAL_ID,
    ExpectedDisposition,
    FeatureScopedFixture,
    FixtureKind,
    FrontendFeature,
    FrontendLimits,
    LogicFrontendDescriptor,
    PrinterContract,
    PrinterGuarantee,
    RecoveryPolicy,
    SharedFrontendConformance,
    UnsupportedBehavior,
    build_baseline_fixture_set,
    make_elaboration_artifact_output,
    make_parse_artifact_output,
    validate_frontend_descriptor,
)
from ipfs_datasets_py.logic.parsers import legacy_modal as legacy_v1
from ipfs_datasets_py.logic.parsers import modal as modal_v1
from ipfs_datasets_py.logic.parsers import resource as resource_v1
from ipfs_datasets_py.logic.parsers import temporal as temporal_v1
from ipfs_datasets_py.logic.syntax_core.artifacts_v2 import (
    ELABORATION_ARTIFACT_V2_INTERFACE,
    PARSE_ARTIFACT_V2_INTERFACE,
)
from ipfs_datasets_py.logic.syntax_core.contracts import (
    ParseLimits,
    ParseMode,
    SyntaxContractError,
)
from ipfs_datasets_py.logic.syntax_core.registry import ParserKey

# ---------------------------------------------------------------------------
# Interface / schema identities
# ---------------------------------------------------------------------------

LOGIC_PROFILE_CATALOG_V2_INTERFACE: Final = "LogicProfileCatalog@2"
LOGIC_PROFILE_CATALOG_V2_SCHEMA_VERSION: Final = "logic-profile-catalog/v2"
LOGIC_PROFILE_CATALOG_V2_MODULE_VERSION: Final = "2.0.0"
PROFILE_CATALOG_ENTRY_SCHEMA: Final = "logic-profile-catalog-entry/v2"
OVERLOADED_OPERATOR_POLICY_SCHEMA: Final = "overloaded-operator-policy/v2"
LOSS_RECEIPT_POLICY_SCHEMA: Final = "loss-receipt-policy/v2"

PROFILE_CATALOG_TASK_ID: Final = "LFP2-015"
PROFILE_CATALOG_GOAL_ID: Final = FRONTEND_CONTRACT_GOAL_ID

# Diagnostic codes for catalog admission / profile gates.
CODE_PROFILE_REQUIRED: Final = "profile_catalog.profile_required"
CODE_PROFILE_UNKNOWN: Final = "profile_catalog.profile_unknown"
CODE_OVERLOADED_OPERATOR: Final = "profile_catalog.overloaded_operator"
CODE_LOSS_RECEIPT_REQUIRED: Final = "profile_catalog.loss_receipt_required"
CODE_SHARED_ARTIFACT_REQUIRED: Final = "profile_catalog.shared_artifact_required"
CODE_DUPLICATE_PROFILE: Final = "profile_catalog.duplicate_profile"
CODE_FAMILY_MISMATCH: Final = "profile_catalog.family_mismatch"

_ALL_CATALOG_CODES: Final[frozenset[str]] = frozenset(
    {
        CODE_PROFILE_REQUIRED,
        CODE_PROFILE_UNKNOWN,
        CODE_OVERLOADED_OPERATOR,
        CODE_LOSS_RECEIPT_REQUIRED,
        CODE_SHARED_ARTIFACT_REQUIRED,
        CODE_DUPLICATE_PROFILE,
        CODE_FAMILY_MISMATCH,
    }
)

DEFAULT_PARSE_LIMITS: Final = ParseLimits(
    max_input_bytes=262_144,
    max_tokens=65_536,
    max_depth=512,
    max_diagnostics=4_096,
    max_time_ms=30_000,
    max_memory_bytes=64 * 1024 * 1024,
)
DEFAULT_FRONTEND_LIMITS: Final = FrontendLimits(
    parse_limits=DEFAULT_PARSE_LIMITS,
    max_output_bytes=262_144,
    max_print_depth=1_024,
)

# Notation ids for cataloged families.
TEMPORAL_NOTATION_ID: Final = temporal_v1.TEMPORAL_NOTATION_ID
MODAL_NOTATION_ID: Final = modal_v1.MODAL_NOTATION_ID
RESOURCE_NOTATION_ID: Final = resource_v1.RESOURCE_NOTATION_ID
TDFOL_NOTATION_ID: Final = "legacy_tdfol"
DCEC_NOTATION_ID: Final = "legacy_dcec"
LEGACY_NOTATION_VERSION: Final = "2.0.0"
FAMILY_NOTATION_VERSION: Final = "2.0.0"


# ---------------------------------------------------------------------------
# Closed vocabularies
# ---------------------------------------------------------------------------


class ProfileFamilyKind(StrEnum):
    """Family grouping for cataloged profiles (canonical family ids)."""

    TEMPORAL = "temporal"
    MODAL = "modal"
    DEONTIC = "deontic"
    EPISTEMIC = "epistemic"
    DOXASTIC = "doxastic"
    INTENTION = "intention_agency"
    RESOURCE = "separation_logic"
    SESSION = "session_process"
    REFINEMENT = "refinement"
    TDFOL = "tdfol"
    DCEC = "dcec"
    CEC = "event_calculus"


class ProfileSourceKind(StrEnum):
    """How a catalog entry is produced."""

    NATIVE = "native"
    LEGACY_IMPORT = "legacy_import"
    COMPOSITION = "composition"


class AuthorityCeilingKind(StrEnum):
    """Non-proof authority ceiling for approximations under a profile."""

    NONE = "none"
    ADVISORY = "advisory"
    BOUNDED = "bounded"
    CANDIDATE = "candidate"


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ProfileCatalogError(SyntaxContractError):
    """Raised when the profile catalog is malformed or contradictory."""


class UnknownProfileError(ProfileCatalogError):
    """Raised when a profile id is not registered."""


class ProfileRequiredError(ProfileCatalogError):
    """Raised when an overloaded operator is used without a declared profile."""


class LossReceiptRequiredError(ProfileCatalogError):
    """Raised when a legacy approximation lacks a loss receipt."""


class DuplicateProfileError(ProfileCatalogError):
    """Raised when a profile id collides in the catalog."""


# ---------------------------------------------------------------------------
# Nested policy records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class OverloadedOperatorPolicy:
    """Policy for symbols that collide across families without a profile.

    Interface fragment: ``overloaded-operator-policy/v2``.
    """

    operators: tuple[str, ...]
    requires_declared_profile: bool = True
    fail_closed_without_profile: bool = True
    candidates: tuple[str, ...] = ()
    notes: str = ""
    schema_version: str = OVERLOADED_OPERATOR_POLICY_SCHEMA

    def __post_init__(self) -> None:
        ops = tuple(
            str(item).strip()
            for item in self.operators
            if str(item).strip()
        )
        if len(ops) != len(set(ops)):
            raise ProfileCatalogError(
                "OverloadedOperatorPolicy.operators must be unique"
            )
        object.__setattr__(self, "operators", ops)
        cands = tuple(
            str(item).strip()
            for item in self.candidates
            if str(item).strip()
        )
        object.__setattr__(self, "candidates", cands)
        if not isinstance(self.requires_declared_profile, bool):
            raise ProfileCatalogError(
                "requires_declared_profile must be a boolean"
            )
        if not isinstance(self.fail_closed_without_profile, bool):
            raise ProfileCatalogError(
                "fail_closed_without_profile must be a boolean"
            )
        if self.schema_version != OVERLOADED_OPERATOR_POLICY_SCHEMA:
            raise ProfileCatalogError(
                f"unsupported OverloadedOperatorPolicy schema "
                f"{self.schema_version!r}"
            )

    def admits(self, operator: str) -> bool:
        return str(operator).strip() in self.operators

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidates": list(self.candidates),
            "fail_closed_without_profile": self.fail_closed_without_profile,
            "notes": self.notes,
            "operators": list(self.operators),
            "requires_declared_profile": self.requires_declared_profile,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "OverloadedOperatorPolicy":
        if not isinstance(value, Mapping):
            raise ProfileCatalogError(
                "OverloadedOperatorPolicy must be a mapping"
            )
        return cls(
            operators=tuple(value.get("operators") or ()),
            requires_declared_profile=bool(
                value.get("requires_declared_profile", True)
            ),
            fail_closed_without_profile=bool(
                value.get("fail_closed_without_profile", True)
            ),
            candidates=tuple(value.get("candidates") or ()),
            notes=str(value.get("notes") or ""),
            schema_version=str(
                value.get("schema_version") or OVERLOADED_OPERATOR_POLICY_SCHEMA
            ),
        )


@dataclass(frozen=True, slots=True)
class LossReceiptPolicy:
    """When and how loss receipts are required under a profile.

    Interface fragment: ``loss-receipt-policy/v2``.
    """

    required_for_legacy_approximation: bool = True
    required_for_partial_lowering: bool = True
    authority_ceiling: AuthorityCeilingKind | str = AuthorityCeilingKind.ADVISORY
    bounds_required: bool = True
    notes: str = ""
    schema_version: str = LOSS_RECEIPT_POLICY_SCHEMA

    def __post_init__(self) -> None:
        ceiling = self.authority_ceiling
        if not isinstance(ceiling, AuthorityCeilingKind):
            try:
                ceiling = AuthorityCeilingKind(str(ceiling))
            except ValueError as error:
                raise ProfileCatalogError(
                    f"unknown authority_ceiling {self.authority_ceiling!r}"
                ) from error
        object.__setattr__(self, "authority_ceiling", ceiling)
        for name in (
            "required_for_legacy_approximation",
            "required_for_partial_lowering",
            "bounds_required",
        ):
            if not isinstance(getattr(self, name), bool):
                raise ProfileCatalogError(f"{name} must be a boolean")
        if self.schema_version != LOSS_RECEIPT_POLICY_SCHEMA:
            raise ProfileCatalogError(
                f"unsupported LossReceiptPolicy schema {self.schema_version!r}"
            )

    @property
    def requires_receipt(self) -> bool:
        return (
            self.required_for_legacy_approximation
            or self.required_for_partial_lowering
        )

    def to_dict(self) -> dict[str, Any]:
        ceiling = (
            self.authority_ceiling.value
            if isinstance(self.authority_ceiling, AuthorityCeilingKind)
            else str(self.authority_ceiling)
        )
        return {
            "authority_ceiling": ceiling,
            "bounds_required": self.bounds_required,
            "notes": self.notes,
            "required_for_legacy_approximation": (
                self.required_for_legacy_approximation
            ),
            "required_for_partial_lowering": self.required_for_partial_lowering,
            "requires_receipt": self.requires_receipt,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "LossReceiptPolicy":
        if not isinstance(value, Mapping):
            raise ProfileCatalogError("LossReceiptPolicy must be a mapping")
        return cls(
            required_for_legacy_approximation=bool(
                value.get("required_for_legacy_approximation", True)
            ),
            required_for_partial_lowering=bool(
                value.get("required_for_partial_lowering", True)
            ),
            authority_ceiling=str(
                value.get("authority_ceiling")
                or AuthorityCeilingKind.ADVISORY.value
            ),
            bounds_required=bool(value.get("bounds_required", True)),
            notes=str(value.get("notes") or ""),
            schema_version=str(
                value.get("schema_version") or LOSS_RECEIPT_POLICY_SCHEMA
            ),
        )


# ---------------------------------------------------------------------------
# Catalog entry
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ProfileCatalogEntry:
    """One published profile with shared-artifact and loss-receipt gates.

    Interface fragment: ``logic-profile-catalog-entry/v2``.
    """

    profile_id: str
    family: ProfileFamilyKind | str
    notation_id: str
    notation_version: str = FAMILY_NOTATION_VERSION
    source_kind: ProfileSourceKind | str = ProfileSourceKind.NATIVE
    description: str = ""
    overloaded_operators: OverloadedOperatorPolicy = field(
        default_factory=lambda: OverloadedOperatorPolicy(operators=())
    )
    loss_receipt_policy: LossReceiptPolicy = field(
        default_factory=LossReceiptPolicy
    )
    shared_artifact_interfaces: tuple[str, ...] = (
        PARSE_ARTIFACT_V2_INTERFACE,
        ELABORATION_ARTIFACT_V2_INTERFACE,
    )
    diagnostic_codes: tuple[str, ...] = ()
    features: tuple[str, ...] = (
        FrontendFeature.PARSE.value,
        FrontendFeature.PRINT.value,
        FrontendFeature.ELABORATE.value,
        FrontendFeature.SOURCE_MAP.value,
    )
    semantic_payload: Mapping[str, Any] = field(default_factory=dict)
    unsupported_nodes: tuple[str, ...] = ()
    implementation: str = ""
    schema_version: str = PROFILE_CATALOG_ENTRY_SCHEMA

    def __post_init__(self) -> None:
        pid = str(self.profile_id or "").strip()
        if not pid or "\x00" in pid or any(ch.isspace() for ch in pid):
            raise ProfileCatalogError(
                "profile_id must be a non-empty identifier without whitespace"
            )
        object.__setattr__(self, "profile_id", pid)

        family = self.family
        if not isinstance(family, ProfileFamilyKind):
            try:
                family = ProfileFamilyKind(str(family))
            except ValueError as error:
                raise ProfileCatalogError(
                    f"unknown profile family {self.family!r}"
                ) from error
        object.__setattr__(self, "family", family)

        source = self.source_kind
        if not isinstance(source, ProfileSourceKind):
            try:
                source = ProfileSourceKind(str(source))
            except ValueError as error:
                raise ProfileCatalogError(
                    f"unknown source_kind {self.source_kind!r}"
                ) from error
        object.__setattr__(self, "source_kind", source)

        notation = str(self.notation_id or "").strip()
        if not notation:
            raise ProfileCatalogError("notation_id is required")
        object.__setattr__(self, "notation_id", notation)
        version = str(self.notation_version or "").strip()
        if not version:
            raise ProfileCatalogError("notation_version is required")
        object.__setattr__(self, "notation_version", version)

        if not isinstance(self.overloaded_operators, OverloadedOperatorPolicy):
            raise ProfileCatalogError(
                "overloaded_operators must be OverloadedOperatorPolicy"
            )
        if not isinstance(self.loss_receipt_policy, LossReceiptPolicy):
            raise ProfileCatalogError(
                "loss_receipt_policy must be LossReceiptPolicy"
            )

        artifacts = tuple(
            str(item).strip()
            for item in self.shared_artifact_interfaces
            if str(item).strip()
        )
        if PARSE_ARTIFACT_V2_INTERFACE not in artifacts:
            raise ProfileCatalogError(
                f"entry {pid!r} must declare shared artifact "
                f"{PARSE_ARTIFACT_V2_INTERFACE}"
            )
        if (
            FrontendFeature.ELABORATE.value in self.features
            and ELABORATION_ARTIFACT_V2_INTERFACE not in artifacts
        ):
            raise ProfileCatalogError(
                f"entry {pid!r} declares elaborate but omits "
                f"{ELABORATION_ARTIFACT_V2_INTERFACE}"
            )
        object.__setattr__(self, "shared_artifact_interfaces", artifacts)

        features = tuple(
            str(item).strip() for item in self.features if str(item).strip()
        )
        if FrontendFeature.PARSE.value not in features:
            raise ProfileCatalogError(
                f"entry {pid!r} must declare the parse feature"
            )
        object.__setattr__(self, "features", features)

        codes = tuple(
            sorted(
                {
                    str(item).strip()
                    for item in self.diagnostic_codes
                    if str(item).strip()
                }
            )
        )
        object.__setattr__(self, "diagnostic_codes", codes)

        unsupported = tuple(
            sorted(
                {
                    str(item).strip()
                    for item in self.unsupported_nodes
                    if str(item).strip()
                }
            )
        )
        object.__setattr__(self, "unsupported_nodes", unsupported)

        payload = dict(self.semantic_payload or {})
        object.__setattr__(self, "semantic_payload", MappingProxyType(payload))

        if self.schema_version != PROFILE_CATALOG_ENTRY_SCHEMA:
            raise ProfileCatalogError(
                f"unsupported ProfileCatalogEntry schema {self.schema_version!r}"
            )

        # Legacy approximations always require loss receipts.
        if (
            source is ProfileSourceKind.LEGACY_IMPORT
            and not self.loss_receipt_policy.required_for_legacy_approximation
        ):
            raise ProfileCatalogError(
                f"legacy-import profile {pid!r} must require loss receipts"
            )

    @property
    def family_id(self) -> str:
        return (
            self.family.value
            if isinstance(self.family, ProfileFamilyKind)
            else str(self.family)
        )

    @property
    def emits_shared_artifacts(self) -> bool:
        return (
            PARSE_ARTIFACT_V2_INTERFACE in self.shared_artifact_interfaces
        )

    @property
    def requires_loss_receipt(self) -> bool:
        return self.loss_receipt_policy.requires_receipt

    @property
    def descriptor_id(self) -> str:
        return f"frontend:{self.notation_id}:v2:{self.profile_id}"

    def requires_profile_for_operator(self, operator: str) -> bool:
        policy = self.overloaded_operators
        if not policy.admits(operator):
            return False
        return policy.requires_declared_profile

    def to_dict(self) -> dict[str, Any]:
        return {
            "description": self.description,
            "diagnostic_codes": list(self.diagnostic_codes),
            "emits_shared_artifacts": self.emits_shared_artifacts,
            "family": self.family_id,
            "features": list(self.features),
            "implementation": self.implementation,
            "loss_receipt_policy": self.loss_receipt_policy.to_dict(),
            "notation_id": self.notation_id,
            "notation_version": self.notation_version,
            "overloaded_operators": self.overloaded_operators.to_dict(),
            "profile_id": self.profile_id,
            "requires_loss_receipt": self.requires_loss_receipt,
            "schema_version": self.schema_version,
            "semantic_payload": dict(self.semantic_payload),
            "shared_artifact_interfaces": list(self.shared_artifact_interfaces),
            "source_kind": (
                self.source_kind.value
                if isinstance(self.source_kind, ProfileSourceKind)
                else str(self.source_kind)
            ),
            "unsupported_nodes": list(self.unsupported_nodes),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ProfileCatalogEntry":
        if not isinstance(value, Mapping):
            raise ProfileCatalogError("ProfileCatalogEntry must be a mapping")
        overloaded_raw = value.get("overloaded_operators") or {}
        loss_raw = value.get("loss_receipt_policy") or {}
        return cls(
            profile_id=str(value.get("profile_id") or ""),
            family=str(value.get("family") or ""),
            notation_id=str(value.get("notation_id") or ""),
            notation_version=str(
                value.get("notation_version") or FAMILY_NOTATION_VERSION
            ),
            source_kind=str(
                value.get("source_kind") or ProfileSourceKind.NATIVE.value
            ),
            description=str(value.get("description") or ""),
            overloaded_operators=OverloadedOperatorPolicy.from_dict(
                overloaded_raw if isinstance(overloaded_raw, Mapping) else {}
            ),
            loss_receipt_policy=LossReceiptPolicy.from_dict(
                loss_raw if isinstance(loss_raw, Mapping) else {}
            ),
            shared_artifact_interfaces=tuple(
                value.get("shared_artifact_interfaces")
                or (
                    PARSE_ARTIFACT_V2_INTERFACE,
                    ELABORATION_ARTIFACT_V2_INTERFACE,
                )
            ),
            diagnostic_codes=tuple(value.get("diagnostic_codes") or ()),
            features=tuple(
                value.get("features")
                or (
                    FrontendFeature.PARSE.value,
                    FrontendFeature.PRINT.value,
                    FrontendFeature.ELABORATE.value,
                    FrontendFeature.SOURCE_MAP.value,
                )
            ),
            semantic_payload=dict(value.get("semantic_payload") or {}),
            unsupported_nodes=tuple(value.get("unsupported_nodes") or ()),
            implementation=str(value.get("implementation") or ""),
            schema_version=str(
                value.get("schema_version") or PROFILE_CATALOG_ENTRY_SCHEMA
            ),
        )

    def build_frontend_descriptor(
        self,
        *,
        limits: FrontendLimits | None = None,
    ) -> LogicFrontendDescriptor:
        """Project this entry into a ``LogicFrontendDescriptor@1``."""

        bounds = limits if limits is not None else DEFAULT_FRONTEND_LIMITS
        features = self.features
        fixtures = build_baseline_fixture_set(
            features=features,
            prefix=f"profile-{self.profile_id}",
        )
        extra = (
            FeatureScopedFixture(
                fixture_id=f"fixture:profile:{self.profile_id}:overloaded",
                kind=FixtureKind.NEGATIVE,
                features=(FrontendFeature.PARSE.value,),
                expected_disposition=ExpectedDisposition.REJECT,
                description=(
                    "Overloaded operators without a declared profile fail closed."
                ),
            ),
            FeatureScopedFixture(
                fixture_id=f"fixture:profile:{self.profile_id}:loss-receipt",
                kind=FixtureKind.POSITIVE,
                features=(
                    FrontendFeature.PARSE.value,
                    FrontendFeature.ELABORATE.value,
                ),
                expected_disposition=ExpectedDisposition.ACCEPT,
                description=(
                    "Legacy approximations emit an explicit loss receipt under "
                    "the declared profile."
                ),
            ),
        )
        diagnostics = tuple(
            sorted(set(self.diagnostic_codes) | set(_ALL_CATALOG_CODES))
        )
        return LogicFrontendDescriptor(
            descriptor_id=self.descriptor_id,
            key=ParserKey(
                notation_id=self.notation_id,
                notation_version=self.notation_version,
                semantic_profile_id=self.profile_id,
            ),
            family_id=self.family_id,
            features=features,
            parse_modes=(ParseMode.STRICT,),
            limits=bounds,
            diagnostics=diagnostics,
            artifact_outputs=(
                make_parse_artifact_output(),
                make_elaboration_artifact_output(),
            ),
            fixtures=tuple(fixtures) + extra,
            recovery=RecoveryPolicy.NONE,
            printer=PrinterContract(
                guarantee=PrinterGuarantee.SEMANTIC,
                features=(FrontendFeature.PRINT.value,),
                deterministic=True,
            ),
            unsupported_behavior=UnsupportedBehavior.REJECT_WITH_DIAGNOSTIC,
            unsupported_nodes=self.unsupported_nodes
            or (
                "profile_free_overloaded_operator",
                "legacy_approximation_without_loss_receipt",
            ),
            implementation=self.implementation
            or (
                "ipfs_datasets_py.logic.parsers.profile_catalog_v2:"
                "LogicProfileCatalog"
            ),
            metadata={
                "task_id": PROFILE_CATALOG_TASK_ID,
                "goal_id": PROFILE_CATALOG_GOAL_ID,
                "source_kind": (
                    self.source_kind.value
                    if isinstance(self.source_kind, ProfileSourceKind)
                    else str(self.source_kind)
                ),
                "loss_receipt_required": self.requires_loss_receipt,
                "overloaded_operators": list(
                    self.overloaded_operators.operators
                ),
                "interfaces": {
                    "profile_catalog": LOGIC_PROFILE_CATALOG_V2_INTERFACE,
                    "parse_artifact": PARSE_ARTIFACT_V2_INTERFACE,
                    "elaboration_artifact": ELABORATION_ARTIFACT_V2_INTERFACE,
                },
                "semantic_payload": dict(self.semantic_payload),
            },
        )


# ---------------------------------------------------------------------------
# Seed catalog construction
# ---------------------------------------------------------------------------


def _temporal_overloaded() -> OverloadedOperatorPolicy:
    return OverloadedOperatorPolicy(
        operators=("F", "G", "U", "R", "X", "W", "O", "H", "Y"),
        requires_declared_profile=True,
        fail_closed_without_profile=True,
        candidates=("temporal", "deontic", "propositional"),
        notes=(
            "Classic single-letter temporal operators collide with propositions "
            "and deontic F; profile admission is mandatory."
        ),
    )


def _modal_overloaded() -> OverloadedOperatorPolicy:
    return OverloadedOperatorPolicy(
        operators=("O", "P", "F", "K", "B", "I", "box", "diamond", "[]", "<>"),
        requires_declared_profile=True,
        fail_closed_without_profile=True,
        candidates=("deontic", "epistemic", "doxastic", "intention", "alethic"),
        notes=(
            "O/P/F and box/diamond are overloaded; surface spelling never "
            "selects semantics."
        ),
    )


def _resource_overloaded() -> OverloadedOperatorPolicy:
    return OverloadedOperatorPolicy(
        operators=("*", "sep", "-*", "wand", "sepimp", "|->"),
        requires_declared_profile=True,
        fail_closed_without_profile=True,
        candidates=("separation", "classical_and", "ownership"),
        notes=(
            "Separating connectives and points-to collide with classical "
            "operators without a resource profile."
        ),
    )


def _legacy_opf_overloaded() -> OverloadedOperatorPolicy:
    return OverloadedOperatorPolicy(
        operators=("O", "P", "F"),
        requires_declared_profile=True,
        fail_closed_without_profile=True,
        candidates=("deontic", "temporal", "propositional"),
        notes="Legacy O/P/F ambiguity is resolved only under a declared profile.",
    )


def _native_loss_policy() -> LossReceiptPolicy:
    return LossReceiptPolicy(
        required_for_legacy_approximation=True,
        required_for_partial_lowering=True,
        authority_ceiling=AuthorityCeilingKind.BOUNDED,
        bounds_required=True,
        notes="Partial lowers require explicit loss receipts and bounds.",
    )


def _legacy_loss_policy() -> LossReceiptPolicy:
    return LossReceiptPolicy(
        required_for_legacy_approximation=True,
        required_for_partial_lowering=True,
        authority_ceiling=AuthorityCeilingKind.ADVISORY,
        bounds_required=True,
        notes=(
            "Legacy approximations never enter the kernel without an explicit "
            "ambiguity/loss receipt."
        ),
    )


def _entry_from_profile_dict(
    *,
    profile_id: str,
    family: ProfileFamilyKind,
    notation_id: str,
    description: str,
    overloaded: OverloadedOperatorPolicy,
    loss_policy: LossReceiptPolicy,
    semantic_payload: Mapping[str, Any],
    source_kind: ProfileSourceKind = ProfileSourceKind.NATIVE,
    diagnostic_codes: Sequence[str] = (),
    unsupported_nodes: Sequence[str] = (),
    implementation: str = "",
    features: Sequence[str] | None = None,
) -> ProfileCatalogEntry:
    return ProfileCatalogEntry(
        profile_id=profile_id,
        family=family,
        notation_id=notation_id,
        notation_version=FAMILY_NOTATION_VERSION,
        source_kind=source_kind,
        description=description,
        overloaded_operators=overloaded,
        loss_receipt_policy=loss_policy,
        diagnostic_codes=tuple(diagnostic_codes),
        features=tuple(features)
        if features is not None
        else (
            FrontendFeature.PARSE.value,
            FrontendFeature.PRINT.value,
            FrontendFeature.ELABORATE.value,
            FrontendFeature.SOURCE_MAP.value,
        ),
        semantic_payload=dict(semantic_payload),
        unsupported_nodes=tuple(unsupported_nodes),
        implementation=implementation,
    )


def build_seed_profile_entries() -> tuple[ProfileCatalogEntry, ...]:
    """Return the published temporal/modal/resource/TDFOL/DCEC seed set."""

    entries: list[ProfileCatalogEntry] = []

    # --- Temporal profiles -------------------------------------------------
    temporal_profiles = (
        (
            temporal_v1.profile_ltl(),
            "Infinite-trace discrete LTL.",
            ("unbounded_metric_interval", "path_quantifier_without_ctl"),
        ),
        (
            temporal_v1.profile_ltlf(),
            "Finite-trace discrete LTLf.",
            ("infinite_trace_assumption", "path_quantifier_without_ctl"),
        ),
        (
            temporal_v1.profile_past_ltl(),
            "Past-extended LTL with discrete time.",
            ("future_only_monitor_without_past",),
        ),
        (
            temporal_v1.profile_mtl(),
            "Metric temporal logic with explicit intervals.",
            ("unbounded_metric_interval",),
        ),
        (
            temporal_v1.profile_ctl(),
            "Branching-time CTL with path quantifiers.",
            ("linear_only_monitor",),
        ),
        (
            temporal_v1.profile_ctl_star(),
            "Branching-time CTL* with path quantifiers.",
            ("linear_only_monitor",),
        ),
    )
    for profile, description, unsupported in temporal_profiles:
        payload = (
            profile.to_dict()
            if hasattr(profile, "to_dict")
            else {"profile_id": profile.profile_id}
        )
        entries.append(
            _entry_from_profile_dict(
                profile_id=profile.profile_id,
                family=ProfileFamilyKind.TEMPORAL,
                notation_id=TEMPORAL_NOTATION_ID,
                description=description,
                overloaded=_temporal_overloaded(),
                loss_policy=_native_loss_policy(),
                semantic_payload=payload,
                diagnostic_codes=sorted(temporal_v1._ALL_TEMPORAL_CODES),
                unsupported_nodes=unsupported,
                implementation=(
                    "ipfs_datasets_py.logic.parsers.temporal:TemporalSyntax"
                ),
            )
        )

    # --- Modal / deontic / cognitive profiles ------------------------------
    modal_specs: tuple[
        tuple[Any, ProfileFamilyKind, str, tuple[str, ...]], ...
    ] = (
        (
            modal_v1.profile_k(),
            ProfileFamilyKind.MODAL,
            "Alethic Kripke frame K.",
            ("dyadic_norm", "defeasible_norm"),
        ),
        (
            modal_v1.profile_d(),
            ProfileFamilyKind.MODAL,
            "Alethic Kripke frame D (serial).",
            ("dyadic_norm", "defeasible_norm"),
        ),
        (
            modal_v1.profile_t(),
            ProfileFamilyKind.MODAL,
            "Alethic Kripke frame T (reflexive).",
            ("dyadic_norm", "defeasible_norm"),
        ),
        (
            modal_v1.profile_s4(),
            ProfileFamilyKind.MODAL,
            "Alethic Kripke frame S4.",
            ("dyadic_norm", "defeasible_norm"),
        ),
        (
            modal_v1.profile_s5(),
            ProfileFamilyKind.MODAL,
            "Alethic Kripke frame S5.",
            ("dyadic_norm", "defeasible_norm"),
        ),
        (
            modal_v1.profile_deontic(),
            ProfileFamilyKind.DEONTIC,
            "Monadic deontic O/P/F with strong permission.",
            ("dyadic_norm", "defeasible_norm"),
        ),
        (
            modal_v1.profile_epistemic(),
            ProfileFamilyKind.EPISTEMIC,
            "Epistemic agent knowledge modality.",
            ("dyadic_norm", "defeasible_norm"),
        ),
        (
            modal_v1.profile_doxastic(),
            ProfileFamilyKind.DOXASTIC,
            "Doxastic agent belief modality.",
            ("dyadic_norm", "defeasible_norm"),
        ),
        (
            modal_v1.profile_intention(),
            ProfileFamilyKind.INTENTION,
            "Intention/agency agent modality.",
            ("dyadic_norm", "defeasible_norm"),
        ),
    )
    for profile, family, description, unsupported in modal_specs:
        payload = (
            profile.to_dict()
            if hasattr(profile, "to_dict")
            else {"profile_id": profile.profile_id}
        )
        entries.append(
            _entry_from_profile_dict(
                profile_id=profile.profile_id,
                family=family,
                notation_id=MODAL_NOTATION_ID,
                description=description,
                overloaded=_modal_overloaded(),
                loss_policy=_native_loss_policy(),
                semantic_payload=payload,
                diagnostic_codes=sorted(modal_v1._ALL_MODAL_CODES),
                unsupported_nodes=unsupported,
                implementation=(
                    "ipfs_datasets_py.logic.parsers.modal:ModalSyntax"
                ),
            )
        )

    # --- Resource / session / refinement profiles --------------------------
    resource_specs: tuple[
        tuple[Any, ProfileFamilyKind, str, str, tuple[str, ...]], ...
    ] = (
        (
            resource_v1.profile_separation(),
            ProfileFamilyKind.RESOURCE,
            RESOURCE_NOTATION_ID,
            "Classical separation logic with disjoint heap algebra.",
            ("unsupported_resource_algebra", "process_operator"),
        ),
        (
            resource_v1.profile_separation(fractional=True),
            ProfileFamilyKind.RESOURCE,
            RESOURCE_NOTATION_ID,
            "Fractional-permission separation logic.",
            ("unsupported_resource_algebra",),
        ),
        (
            resource_v1.profile_ownership(),
            ProfileFamilyKind.RESOURCE,
            RESOURCE_NOTATION_ID,
            "Ownership-transfer oriented resource profile.",
            ("unsupported_resource_algebra",),
        ),
        (
            resource_v1.profile_session(),
            ProfileFamilyKind.SESSION,
            RESOURCE_NOTATION_ID,
            "Session/process channel polarity and duality.",
            ("unsupported_process_operator",),
        ),
        (
            resource_v1.profile_rely_guarantee(),
            ProfileFamilyKind.SESSION,
            RESOURCE_NOTATION_ID,
            "Rely-guarantee concurrent composition.",
            ("unsupported_concurrency_assumption",),
        ),
        (
            resource_v1.profile_refinement(),
            ProfileFamilyKind.REFINEMENT,
            RESOURCE_NOTATION_ID,
            "Two-state relational refinement obligations.",
            ("unbounded_refinement_proof",),
        ),
    )
    for profile, family, notation, description, unsupported in resource_specs:
        payload = (
            profile.to_dict()
            if hasattr(profile, "to_dict")
            else {"profile_id": profile.profile_id}
        )
        # Normalize profile ids that may contain ':' for descriptor safety.
        raw_id = str(profile.profile_id)
        safe_id = raw_id.replace(":", "_")
        entries.append(
            _entry_from_profile_dict(
                profile_id=safe_id,
                family=family,
                notation_id=notation,
                description=description,
                overloaded=_resource_overloaded(),
                loss_policy=_native_loss_policy(),
                semantic_payload={**payload, "canonical_profile_id": raw_id},
                diagnostic_codes=sorted(resource_v1._ALL_RESOURCE_CODES)
                if hasattr(resource_v1, "_ALL_RESOURCE_CODES")
                else (
                    resource_v1.CODE_PROFILE_MISMATCH,
                    resource_v1.CODE_UNSUPPORTED_ALGEBRA,
                ),
                unsupported_nodes=unsupported,
                implementation=(
                    "ipfs_datasets_py.logic.parsers.resource:ResourceLogicSyntax"
                ),
            )
        )

    # --- Legacy TDFOL / DCEC / legal import profiles -----------------------
    tdfol = legacy_v1.profile_tdfol()
    entries.append(
        _entry_from_profile_dict(
            profile_id=tdfol.profile_id,
            family=ProfileFamilyKind.TDFOL,
            notation_id=TDFOL_NOTATION_ID,
            description=(
                "Legacy temporal-deontic first-order import with explicit "
                "O/P/F ambiguity and right-associative implication receipts."
            ),
            overloaded=_legacy_opf_overloaded(),
            loss_policy=_legacy_loss_policy(),
            semantic_payload=tdfol.to_dict(),
            source_kind=ProfileSourceKind.LEGACY_IMPORT,
            diagnostic_codes=(
                legacy_v1.CODE_UNKNOWN_CHARACTER,
                legacy_v1.CODE_UNKNOWN_SORT,
                legacy_v1.CODE_OPF_AMBIGUITY,
                legacy_v1.CODE_PROFILE_REQUIRED,
                legacy_v1.CODE_LOSS,
                legacy_v1.CODE_IMPLIES_ASSOC,
            ),
            unsupported_nodes=(
                "unknown_character_silent_drop",
                "unknown_sort_silent_drop",
                "left_associative_implication",
                "profile_free_opf",
            ),
            implementation=(
                "ipfs_datasets_py.logic.parsers.legacy_import_v2:"
                "LegacyLogicBoundary"
            ),
        )
    )

    dcec = legacy_v1.profile_dcec()
    entries.append(
        _entry_from_profile_dict(
            profile_id=dcec.profile_id,
            family=ProfileFamilyKind.DCEC,
            notation_id=DCEC_NOTATION_ID,
            description=(
                "Legacy deontic cognitive event-calculus import with s-expression "
                "and event-calculus surfaces under explicit loss receipts."
            ),
            overloaded=_legacy_opf_overloaded(),
            loss_policy=_legacy_loss_policy(),
            semantic_payload=dcec.to_dict(),
            source_kind=ProfileSourceKind.LEGACY_IMPORT,
            diagnostic_codes=(
                legacy_v1.CODE_UNKNOWN_CHARACTER,
                legacy_v1.CODE_UNKNOWN_SORT,
                legacy_v1.CODE_OPF_AMBIGUITY,
                legacy_v1.CODE_PROFILE_REQUIRED,
                legacy_v1.CODE_LOSS,
                legacy_v1.CODE_UNSUPPORTED_SURFACE,
            ),
            unsupported_nodes=(
                "unknown_character_silent_drop",
                "profile_free_opf",
                "silent_sexpr_drop",
            ),
            implementation=(
                "ipfs_datasets_py.logic.parsers.legacy_import_v2:"
                "LegacyLogicBoundary"
            ),
        )
    )

    entries.append(
        _entry_from_profile_dict(
            profile_id="cec_classical_import",
            family=ProfileFamilyKind.CEC,
            notation_id=DCEC_NOTATION_ID,
            description=(
                "Classical event-calculus import profile (CEC) with loss "
                "receipts for legacy approximations."
            ),
            overloaded=_legacy_opf_overloaded(),
            loss_policy=_legacy_loss_policy(),
            semantic_payload={
                "profile_id": "cec_classical_import",
                "admit_event_calculus": True,
                "admit_cognitive": False,
            },
            source_kind=ProfileSourceKind.LEGACY_IMPORT,
            diagnostic_codes=(
                legacy_v1.CODE_UNKNOWN_CHARACTER,
                legacy_v1.CODE_PROFILE_REQUIRED,
                legacy_v1.CODE_LOSS,
            ),
            unsupported_nodes=("silent_event_calculus_drop",),
            implementation=(
                "ipfs_datasets_py.logic.parsers.legacy_import_v2:"
                "LegacyLogicBoundary"
            ),
        )
    )

    return tuple(sorted(entries, key=lambda item: item.profile_id))


# ---------------------------------------------------------------------------
# Catalog
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LogicProfileCatalog:
    """Sealed catalog of declared logic profiles (``LogicProfileCatalog@2``).

    Every registered entry emits shared artifacts; overloaded operators and
    legacy approximations require a declared profile and loss receipt.
    """

    INTERFACE: ClassVar[str] = LOGIC_PROFILE_CATALOG_V2_INTERFACE

    entries: tuple[ProfileCatalogEntry, ...] = field(
        default_factory=build_seed_profile_entries
    )
    schema_version: str = LOGIC_PROFILE_CATALOG_V2_SCHEMA_VERSION
    version: str = LOGIC_PROFILE_CATALOG_V2_MODULE_VERSION
    task_id: str = PROFILE_CATALOG_TASK_ID
    goal_id: str = PROFILE_CATALOG_GOAL_ID

    def __post_init__(self) -> None:
        items = tuple(self.entries)
        seen: set[str] = set()
        for entry in items:
            if not isinstance(entry, ProfileCatalogEntry):
                raise ProfileCatalogError(
                    "LogicProfileCatalog.entries must contain ProfileCatalogEntry"
                )
            if entry.profile_id in seen:
                raise DuplicateProfileError(
                    f"duplicate profile_id {entry.profile_id!r}"
                )
            seen.add(entry.profile_id)
            if not entry.emits_shared_artifacts:
                raise ProfileCatalogError(
                    f"profile {entry.profile_id!r} does not emit shared artifacts"
                )
        object.__setattr__(
            self,
            "entries",
            tuple(sorted(items, key=lambda item: item.profile_id)),
        )
        if self.schema_version != LOGIC_PROFILE_CATALOG_V2_SCHEMA_VERSION:
            raise ProfileCatalogError(
                f"unsupported LogicProfileCatalog schema {self.schema_version!r}"
            )

    def __len__(self) -> int:
        return len(self.entries)

    def __iter__(self) -> Iterator[ProfileCatalogEntry]:
        return iter(self.entries)

    def __contains__(self, profile_id: object) -> bool:
        return isinstance(profile_id, str) and profile_id in self.profile_ids()

    @property
    def interface(self) -> str:
        return self.INTERFACE

    def profile_ids(self) -> tuple[str, ...]:
        return tuple(entry.profile_id for entry in self.entries)

    def get(self, profile_id: str) -> ProfileCatalogEntry:
        key = str(profile_id or "").strip()
        for entry in self.entries:
            if entry.profile_id == key:
                return entry
            # Accept raw resource ids that used ':' before normalization.
            canonical = entry.semantic_payload.get("canonical_profile_id")
            if canonical is not None and str(canonical) == key:
                return entry
        raise UnknownProfileError(
            f"unknown profile {profile_id!r}; fail closed"
        )

    def require(self, profile_id: str | None) -> ProfileCatalogEntry:
        """Return the entry for *profile_id* or fail closed if absent."""

        if profile_id is None or not str(profile_id).strip():
            raise ProfileRequiredError(
                "overloaded operators and legacy approximations require a "
                "declared profile; fail closed"
            )
        return self.get(str(profile_id).strip())

    def by_family(
        self, family: ProfileFamilyKind | str
    ) -> tuple[ProfileCatalogEntry, ...]:
        fam = (
            family
            if isinstance(family, ProfileFamilyKind)
            else ProfileFamilyKind(str(family))
        )
        return tuple(entry for entry in self.entries if entry.family is fam)

    def overloaded_operator_index(self) -> Mapping[str, tuple[str, ...]]:
        """Map operator lexeme → sorted profile ids that admit it."""

        index: dict[str, list[str]] = {}
        for entry in self.entries:
            for op in entry.overloaded_operators.operators:
                index.setdefault(op, []).append(entry.profile_id)
        return MappingProxyType(
            {key: tuple(sorted(values)) for key, values in sorted(index.items())}
        )

    def require_profile_for_operator(
        self,
        operator: str,
        profile_id: str | None,
    ) -> ProfileCatalogEntry:
        """Gate an overloaded operator behind a declared catalog profile."""

        op = str(operator).strip()
        index = self.overloaded_operator_index()
        if op not in index:
            # Non-overloaded operators still require a profile when supplied.
            if profile_id is None or not str(profile_id).strip():
                raise ProfileRequiredError(
                    f"operator {op!r} requires a declared profile when used "
                    "through the profile catalog; fail closed"
                )
            return self.get(str(profile_id).strip())

        entry = self.require(profile_id)
        if not entry.requires_profile_for_operator(op):
            # Entry is registered but does not list this operator — still ok
            # if the operator is overloaded elsewhere and profile is declared.
            pass
        if entry.overloaded_operators.fail_closed_without_profile and (
            profile_id is None or not str(profile_id).strip()
        ):
            raise ProfileRequiredError(
                f"overloaded operator {op!r} requires declared profile; "
                f"candidates={list(index[op])}"
            )
        return entry

    def require_loss_receipt(
        self,
        profile_id: str,
        *,
        has_loss_receipt: bool,
        is_legacy_approximation: bool = False,
        is_partial_lowering: bool = False,
    ) -> ProfileCatalogEntry:
        """Fail closed when a required loss receipt is missing."""

        entry = self.get(profile_id)
        policy = entry.loss_receipt_policy
        needs = False
        if is_legacy_approximation and policy.required_for_legacy_approximation:
            needs = True
        if is_partial_lowering and policy.required_for_partial_lowering:
            needs = True
        if (
            entry.source_kind is ProfileSourceKind.LEGACY_IMPORT
            and policy.required_for_legacy_approximation
        ):
            needs = True
        if needs and not has_loss_receipt:
            raise LossReceiptRequiredError(
                f"profile {profile_id!r} requires an explicit loss receipt for "
                "legacy approximations / partial lowers; fail closed"
            )
        return entry

    def every_entry_emits_shared_artifacts(self) -> bool:
        return all(entry.emits_shared_artifacts for entry in self.entries)

    def every_legacy_entry_requires_loss_receipt(self) -> bool:
        return all(
            entry.requires_loss_receipt
            for entry in self.entries
            if entry.source_kind is ProfileSourceKind.LEGACY_IMPORT
        )

    def every_overloaded_operator_requires_profile(self) -> bool:
        return all(
            entry.overloaded_operators.requires_declared_profile
            for entry in self.entries
            if entry.overloaded_operators.operators
        )

    def build_descriptors(
        self,
        *,
        limits: FrontendLimits | None = None,
    ) -> tuple[LogicFrontendDescriptor, ...]:
        return tuple(
            entry.build_frontend_descriptor(limits=limits) for entry in self.entries
        )

    def register_all(
        self,
        registry: SharedFrontendConformance | None = None,
        *,
        limits: FrontendLimits | None = None,
        replace: bool = False,
    ) -> tuple[SharedFrontendConformance, tuple[LogicFrontendDescriptor, ...]]:
        """Register every catalog entry under SharedFrontendConformance@1."""

        target = registry if registry is not None else SharedFrontendConformance(
            conformance_id="conformance:logic-profile-catalog-v2"
        )
        admitted: list[LogicFrontendDescriptor] = []
        for entry in self.entries:
            descriptor = entry.build_frontend_descriptor(limits=limits)
            validate_frontend_descriptor(descriptor)
            admitted.append(target.register(descriptor, replace=replace))
        return target, tuple(admitted)

    def to_dict(self) -> dict[str, Any]:
        return {
            "entries": [entry.to_dict() for entry in self.entries],
            "goal_id": self.goal_id,
            "interface": self.INTERFACE,
            "profile_ids": list(self.profile_ids()),
            "schema_version": self.schema_version,
            "task_id": self.task_id,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "LogicProfileCatalog":
        if not isinstance(value, Mapping):
            raise ProfileCatalogError("LogicProfileCatalog must be a mapping")
        interface = value.get("interface")
        if (
            interface is not None
            and interface != LOGIC_PROFILE_CATALOG_V2_INTERFACE
        ):
            raise ProfileCatalogError(
                f"unsupported LogicProfileCatalog interface {interface!r}"
            )
        raw_entries = value.get("entries")
        if raw_entries is None:
            entries = build_seed_profile_entries()
        else:
            if not isinstance(raw_entries, Sequence) or isinstance(
                raw_entries, (str, bytes, bytearray)
            ):
                raise ProfileCatalogError("entries must be a sequence")
            entries = tuple(
                ProfileCatalogEntry.from_dict(item)
                if isinstance(item, Mapping)
                else item
                for item in raw_entries
            )
        return cls(
            entries=entries,
            schema_version=str(
                value.get("schema_version")
                or LOGIC_PROFILE_CATALOG_V2_SCHEMA_VERSION
            ),
            version=str(
                value.get("version") or LOGIC_PROFILE_CATALOG_V2_MODULE_VERSION
            ),
            task_id=str(value.get("task_id") or PROFILE_CATALOG_TASK_ID),
            goal_id=str(value.get("goal_id") or PROFILE_CATALOG_GOAL_ID),
        )


def default_profile_catalog() -> LogicProfileCatalog:
    """Return the sealed seed catalog."""

    return LogicProfileCatalog()


def register_profile_catalog(
    registry: SharedFrontendConformance | None = None,
    *,
    catalog: LogicProfileCatalog | None = None,
    limits: FrontendLimits | None = None,
) -> tuple[SharedFrontendConformance, LogicProfileCatalog]:
    """Register the profile catalog into a shared frontend conformance registry."""

    cat = catalog if catalog is not None else default_profile_catalog()
    target, _admitted = cat.register_all(registry, limits=limits)
    return target, cat


__all__ = [
    "LOGIC_PROFILE_CATALOG_V2_INTERFACE",
    "LOGIC_PROFILE_CATALOG_V2_SCHEMA_VERSION",
    "LOGIC_PROFILE_CATALOG_V2_MODULE_VERSION",
    "PROFILE_CATALOG_TASK_ID",
    "PROFILE_CATALOG_GOAL_ID",
    "PARSE_ARTIFACT_V2_INTERFACE",
    "ELABORATION_ARTIFACT_V2_INTERFACE",
    "CODE_PROFILE_REQUIRED",
    "CODE_PROFILE_UNKNOWN",
    "CODE_OVERLOADED_OPERATOR",
    "CODE_LOSS_RECEIPT_REQUIRED",
    "CODE_SHARED_ARTIFACT_REQUIRED",
    "CODE_DUPLICATE_PROFILE",
    "CODE_FAMILY_MISMATCH",
    "DEFAULT_FRONTEND_LIMITS",
    "DEFAULT_PARSE_LIMITS",
    "ProfileFamilyKind",
    "ProfileSourceKind",
    "AuthorityCeilingKind",
    "ProfileCatalogError",
    "UnknownProfileError",
    "ProfileRequiredError",
    "LossReceiptRequiredError",
    "DuplicateProfileError",
    "OverloadedOperatorPolicy",
    "LossReceiptPolicy",
    "ProfileCatalogEntry",
    "LogicProfileCatalog",
    "build_seed_profile_entries",
    "default_profile_catalog",
    "register_profile_catalog",
]
