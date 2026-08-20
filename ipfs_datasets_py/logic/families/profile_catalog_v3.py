"""Wave-2 profile catalog publication (``LogicProfileCatalog@3`` / LFP2-044).

Every executable Wave-2 profile publishes:

* stable feature identities
* explicit lifecycle disposition (declaration-only vs executable)
* deterministic resource limits
* representative fixture obligations (positive / negative / ambiguous /
  adversarial / round-trip / resource)

Registry/profile presence alone never implies prover executability.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any, ClassVar, Final

from ipfs_datasets_py.logic.families.registry_v3 import (
    DEFAULT_REGISTRY_V3,
    FamilyLifecycleDisposition,
    LogicFamilyRegistryV3,
    REGISTRY_V3_GOAL_ID,
    REGISTRY_V3_TASK_ID,
    WAVE2_FAMILY_TASK_IDS,
)

# ---------------------------------------------------------------------------
# Interface / schema identities
# ---------------------------------------------------------------------------

LOGIC_PROFILE_CATALOG_V3_INTERFACE: Final = "LogicProfileCatalog@3"
LOGIC_PROFILE_CATALOG_V3_SCHEMA: Final = "logic-profile-catalog/v3"
PROFILE_CATALOG_ENTRY_V3_SCHEMA: Final = "logic-profile-catalog-entry/v3"
RESOURCE_LIMITS_V3_SCHEMA: Final = "logic-profile-resource-limits/v3"
PROFILE_CATALOG_V3_MODULE_VERSION: Final = "3.0.0"

PROFILE_CATALOG_V3_TASK_ID: Final = REGISTRY_V3_TASK_ID
PROFILE_CATALOG_V3_GOAL_ID: Final = REGISTRY_V3_GOAL_ID

REQUIRED_FIXTURE_KINDS: Final[tuple[str, ...]] = (
    "positive",
    "negative",
    "ambiguous",
    "adversarial",
    "round_trip",
    "resource",
)

DEFAULT_EXECUTABLE_FEATURES: Final[tuple[str, ...]] = (
    "parse",
    "print",
    "source_map",
)


class ProfileDisposition(StrEnum):
    """Executable vs declaration-only posture for a profile."""

    DECLARATION_ONLY = "declaration_only"
    PARSE_PRINT = "parse_print"
    EVALUATE = "evaluate"
    CONTROLLED_EXECUTABLE = "controlled_executable"


class ProfileCatalogV3Error(ValueError):
    """Raised when the Wave-2 profile catalog is malformed."""


class DuplicateProfileCatalogV3Error(ProfileCatalogV3Error):
    """Raised when a profile id collides."""


class UnknownProfileCatalogV3Error(ProfileCatalogV3Error, KeyError):
    """Raised when a profile id is not registered."""


def _text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ProfileCatalogV3Error(
            f"{field_name} must be a non-empty trimmed string"
        )
    if "\x00" in value:
        raise ProfileCatalogV3Error(f"{field_name} must not contain NUL bytes")
    return value


def _identifier(value: object, field_name: str) -> str:
    result = _text(value, field_name)
    if any(character.isspace() for character in result):
        raise ProfileCatalogV3Error(
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
            raise ProfileCatalogV3Error(f"{field_name} must be a sequence of strings")
        items = tuple(_identifier(item, f"{field_name} item") for item in value)
        if len(set(items)) != len(items):
            raise ProfileCatalogV3Error(f"{field_name} must not contain duplicates")
    if not items and not allow_empty:
        raise ProfileCatalogV3Error(f"{field_name} must not be empty")
    return items


def _positive_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ProfileCatalogV3Error(f"{field_name} must be a positive integer")
    return value


# ---------------------------------------------------------------------------
# Resource limits (deterministic)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ProfileResourceLimits:
    """Deterministic parser/resource limits for one profile."""

    max_input_bytes: int = 65_536
    max_tokens: int = 16_384
    max_depth: int = 128
    max_diagnostics: int = 1_024
    max_time_ms: int = 5_000
    max_memory_bytes: int = 32 * 1024 * 1024
    max_nesting_bomb_depth: int = 64
    schema_version: str = RESOURCE_LIMITS_V3_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "max_input_bytes",
            _positive_int(self.max_input_bytes, "max_input_bytes"),
        )
        object.__setattr__(
            self, "max_tokens", _positive_int(self.max_tokens, "max_tokens")
        )
        object.__setattr__(
            self, "max_depth", _positive_int(self.max_depth, "max_depth")
        )
        object.__setattr__(
            self,
            "max_diagnostics",
            _positive_int(self.max_diagnostics, "max_diagnostics"),
        )
        object.__setattr__(
            self, "max_time_ms", _positive_int(self.max_time_ms, "max_time_ms")
        )
        object.__setattr__(
            self,
            "max_memory_bytes",
            _positive_int(self.max_memory_bytes, "max_memory_bytes"),
        )
        object.__setattr__(
            self,
            "max_nesting_bomb_depth",
            _positive_int(self.max_nesting_bomb_depth, "max_nesting_bomb_depth"),
        )
        if self.schema_version != RESOURCE_LIMITS_V3_SCHEMA:
            raise ProfileCatalogV3Error(
                f"unsupported ProfileResourceLimits schema {self.schema_version!r}"
            )
        if self.max_nesting_bomb_depth > self.max_depth:
            raise ProfileCatalogV3Error(
                "max_nesting_bomb_depth must not exceed max_depth"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_depth": self.max_depth,
            "max_diagnostics": self.max_diagnostics,
            "max_input_bytes": self.max_input_bytes,
            "max_memory_bytes": self.max_memory_bytes,
            "max_nesting_bomb_depth": self.max_nesting_bomb_depth,
            "max_time_ms": self.max_time_ms,
            "max_tokens": self.max_tokens,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ProfileResourceLimits":
        if not isinstance(value, Mapping):
            raise ProfileCatalogV3Error("ProfileResourceLimits must be a mapping")
        return cls(
            max_input_bytes=int(value.get("max_input_bytes", 65_536)),
            max_tokens=int(value.get("max_tokens", 16_384)),
            max_depth=int(value.get("max_depth", 128)),
            max_diagnostics=int(value.get("max_diagnostics", 1_024)),
            max_time_ms=int(value.get("max_time_ms", 5_000)),
            max_memory_bytes=int(value.get("max_memory_bytes", 32 * 1024 * 1024)),
            max_nesting_bomb_depth=int(value.get("max_nesting_bomb_depth", 64)),
            schema_version=str(
                value.get("schema_version") or RESOURCE_LIMITS_V3_SCHEMA
            ),
        )


DEFAULT_RESOURCE_LIMITS: Final = ProfileResourceLimits()
TIGHT_RESOURCE_LIMITS: Final = ProfileResourceLimits(
    max_input_bytes=8_192,
    max_tokens=2_048,
    max_depth=64,
    max_diagnostics=256,
    max_time_ms=2_000,
    max_memory_bytes=8 * 1024 * 1024,
    max_nesting_bomb_depth=32,
)
FIELD_RESOURCE_LIMITS: Final = ProfileResourceLimits(
    max_input_bytes=32_768,
    max_tokens=8_192,
    max_depth=96,
    max_diagnostics=512,
    max_time_ms=3_000,
    max_memory_bytes=16 * 1024 * 1024,
    max_nesting_bomb_depth=48,
)


# ---------------------------------------------------------------------------
# Profile catalog entry
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ProfileCatalogEntryV3:
    """One Wave-2 profile with features, disposition, limits, and fixtures."""

    profile_id: str
    family_id: str
    task_id: str
    disposition: ProfileDisposition | str
    feature_ids: tuple[str, ...]
    executable_features: tuple[str, ...]
    resource_limits: ProfileResourceLimits = field(
        default_factory=lambda: DEFAULT_RESOURCE_LIMITS
    )
    fixture_kinds: tuple[str, ...] = REQUIRED_FIXTURE_KINDS
    notation_id: str = ""
    authority_ceiling: str = "advisory"
    parser_module: str = ""
    description: str = ""
    semantic_payload: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = PROFILE_CATALOG_ENTRY_V3_SCHEMA

    interface: ClassVar[str] = LOGIC_PROFILE_CATALOG_V3_INTERFACE

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "profile_id", _identifier(self.profile_id, "profile_id")
        )
        object.__setattr__(
            self, "family_id", _identifier(self.family_id, "family_id")
        )
        object.__setattr__(self, "task_id", _identifier(self.task_id, "task_id"))

        disposition = self.disposition
        if not isinstance(disposition, ProfileDisposition):
            try:
                disposition = ProfileDisposition(str(disposition))
            except ValueError as error:
                raise ProfileCatalogV3Error(
                    f"unknown profile disposition {self.disposition!r}"
                ) from error
        object.__setattr__(self, "disposition", disposition)

        features = _string_tuple(self.feature_ids, "feature_ids", allow_empty=False)
        if "parse" not in features and disposition is not ProfileDisposition.DECLARATION_ONLY:
            raise ProfileCatalogV3Error(
                f"profile {self.profile_id!r} must declare the parse feature "
                "unless declaration_only"
            )
        object.__setattr__(self, "feature_ids", features)

        executable = _string_tuple(
            self.executable_features, "executable_features"
        )
        unknown = sorted(set(executable) - set(features))
        if unknown:
            raise ProfileCatalogV3Error(
                f"profile {self.profile_id!r} executable_features not in "
                f"feature_ids: {', '.join(unknown)}"
            )
        object.__setattr__(self, "executable_features", executable)

        if disposition is ProfileDisposition.DECLARATION_ONLY and executable:
            raise ProfileCatalogV3Error(
                f"declaration_only profile {self.profile_id!r} cannot claim "
                "executable_features; registry presence never implies "
                "executability"
            )
        if (
            disposition is not ProfileDisposition.DECLARATION_ONLY
            and not executable
        ):
            raise ProfileCatalogV3Error(
                f"executable disposition profile {self.profile_id!r} must list "
                "executable_features"
            )

        if not isinstance(self.resource_limits, ProfileResourceLimits):
            raise ProfileCatalogV3Error(
                "resource_limits must be ProfileResourceLimits"
            )

        fixtures = _string_tuple(self.fixture_kinds, "fixture_kinds", allow_empty=False)
        if disposition is not ProfileDisposition.DECLARATION_ONLY:
            missing = sorted(set(REQUIRED_FIXTURE_KINDS) - set(fixtures))
            if missing:
                raise ProfileCatalogV3Error(
                    f"executable profile {self.profile_id!r} missing required "
                    f"fixture kinds: {', '.join(missing)}"
                )
        object.__setattr__(self, "fixture_kinds", fixtures)

        if self.notation_id:
            object.__setattr__(
                self, "notation_id", _identifier(self.notation_id, "notation_id")
            )
        object.__setattr__(
            self,
            "authority_ceiling",
            _identifier(self.authority_ceiling, "authority_ceiling"),
        )
        if self.parser_module:
            object.__setattr__(
                self, "parser_module", _text(self.parser_module, "parser_module")
            )
        object.__setattr__(
            self,
            "semantic_payload",
            MappingProxyType(dict(self.semantic_payload or {})),
        )
        if self.schema_version != PROFILE_CATALOG_ENTRY_V3_SCHEMA:
            raise ProfileCatalogV3Error(
                f"unsupported ProfileCatalogEntryV3 schema {self.schema_version!r}"
            )

    @property
    def is_declaration_only(self) -> bool:
        return self.disposition is ProfileDisposition.DECLARATION_ONLY

    @property
    def is_executable(self) -> bool:
        return (
            self.disposition is not ProfileDisposition.DECLARATION_ONLY
            and bool(self.executable_features)
        )

    def feature_is_executable(self, feature_id: str) -> bool:
        return self.is_executable and feature_id in self.executable_features

    def to_dict(self) -> dict[str, Any]:
        disposition = (
            self.disposition.value
            if isinstance(self.disposition, ProfileDisposition)
            else str(self.disposition)
        )
        return {
            "authority_ceiling": self.authority_ceiling,
            "description": self.description,
            "disposition": disposition,
            "executable_features": list(self.executable_features),
            "family_id": self.family_id,
            "feature_ids": list(self.feature_ids),
            "fixture_kinds": list(self.fixture_kinds),
            "is_declaration_only": self.is_declaration_only,
            "is_executable": self.is_executable,
            "notation_id": self.notation_id,
            "parser_module": self.parser_module,
            "profile_id": self.profile_id,
            "resource_limits": self.resource_limits.to_dict(),
            "schema_version": self.schema_version,
            "semantic_payload": dict(self.semantic_payload),
            "task_id": self.task_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ProfileCatalogEntryV3":
        if not isinstance(value, Mapping):
            raise ProfileCatalogV3Error("ProfileCatalogEntryV3 must be a mapping")
        limits_raw = value.get("resource_limits") or {}
        return cls(
            profile_id=str(value.get("profile_id") or ""),
            family_id=str(value.get("family_id") or ""),
            task_id=str(value.get("task_id") or ""),
            disposition=str(value.get("disposition") or ""),
            feature_ids=tuple(value.get("feature_ids") or ()),
            executable_features=tuple(value.get("executable_features") or ()),
            resource_limits=(
                limits_raw
                if isinstance(limits_raw, ProfileResourceLimits)
                else ProfileResourceLimits.from_dict(
                    limits_raw if isinstance(limits_raw, Mapping) else {}
                )
            ),
            fixture_kinds=tuple(value.get("fixture_kinds") or REQUIRED_FIXTURE_KINDS),
            notation_id=str(value.get("notation_id") or ""),
            authority_ceiling=str(value.get("authority_ceiling") or "advisory"),
            parser_module=str(value.get("parser_module") or ""),
            description=str(value.get("description") or ""),
            semantic_payload=(
                dict(value.get("semantic_payload") or {})
                if isinstance(value.get("semantic_payload"), Mapping)
                else {}
            ),
            schema_version=str(
                value.get("schema_version") or PROFILE_CATALOG_ENTRY_V3_SCHEMA
            ),
        )


# ---------------------------------------------------------------------------
# Seed profiles
# ---------------------------------------------------------------------------


def _profile(
    profile_id: str,
    family_id: str,
    task_id: str,
    *,
    disposition: ProfileDisposition = ProfileDisposition.PARSE_PRINT,
    features: Sequence[str] = ("parse", "print", "elaborate", "source_map"),
    executable_features: Sequence[str] = DEFAULT_EXECUTABLE_FEATURES,
    limits: ProfileResourceLimits = DEFAULT_RESOURCE_LIMITS,
    fixture_kinds: Sequence[str] = REQUIRED_FIXTURE_KINDS,
    notation_id: str = "",
    authority_ceiling: str = "advisory",
    parser_module: str = "",
    description: str = "",
    semantic_payload: Mapping[str, Any] | None = None,
) -> ProfileCatalogEntryV3:
    return ProfileCatalogEntryV3(
        profile_id=profile_id,
        family_id=family_id,
        task_id=task_id,
        disposition=disposition,
        feature_ids=tuple(features),
        executable_features=tuple(executable_features),
        resource_limits=limits,
        fixture_kinds=tuple(fixture_kinds),
        notation_id=notation_id,
        authority_ceiling=authority_ceiling,
        parser_module=parser_module,
        description=description,
        semantic_payload=dict(semantic_payload or {}),
    )


def _seed_wave2_profiles() -> tuple[ProfileCatalogEntryV3, ...]:
    eval_features = ("parse", "print", "elaborate", "source_map", "evaluate")
    eval_exec = ("parse", "print", "source_map", "evaluate")

    return (
        # LFP2-037 normative
        _profile(
            "normative_dyadic",
            "deontic",
            "LFP2-037",
            disposition=ProfileDisposition.EVALUATE,
            features=eval_features,
            executable_features=eval_exec,
            notation_id="canonical_normative_v2",
            authority_ceiling="bounded",
            parser_module="ipfs_datasets_py.logic.parsers.normative_v2",
            description="Dyadic / conditional norms",
            semantic_payload={"semantics": "dyadic"},
        ),
        _profile(
            "normative_defeasible",
            "deontic",
            "LFP2-037",
            disposition=ProfileDisposition.EVALUATE,
            features=eval_features,
            executable_features=eval_exec,
            notation_id="canonical_normative_v2",
            authority_ceiling="bounded",
            parser_module="ipfs_datasets_py.logic.parsers.normative_v2",
            description="Defeasible norms with exceptions",
            semantic_payload={"semantics": "defeasible"},
        ),
        _profile(
            "normative_prioritized",
            "deontic",
            "LFP2-037",
            disposition=ProfileDisposition.EVALUATE,
            features=eval_features,
            executable_features=eval_exec,
            notation_id="canonical_normative_v2",
            authority_ceiling="bounded",
            parser_module="ipfs_datasets_py.logic.parsers.normative_v2",
            description="Priority-resolved norm conflicts",
            semantic_payload={"semantics": "prioritized"},
        ),
        _profile(
            "normative_contrary_to_duty",
            "deontic",
            "LFP2-037",
            disposition=ProfileDisposition.EVALUATE,
            features=eval_features,
            executable_features=eval_exec,
            notation_id="canonical_normative_v2",
            authority_ceiling="bounded",
            parser_module="ipfs_datasets_py.logic.parsers.normative_v2",
            description="Contrary-to-duty / reparation structures",
            semantic_payload={"semantics": "contrary_to_duty"},
        ),
        # LFP2-038 argumentation
        _profile(
            "argumentation_grounded",
            "argumentation",
            "LFP2-038",
            disposition=ProfileDisposition.EVALUATE,
            features=eval_features,
            executable_features=eval_exec,
            limits=TIGHT_RESOURCE_LIMITS,
            notation_id="canonical_argumentation",
            parser_module="ipfs_datasets_py.logic.parsers.argumentation",
            semantic_payload={"semantics": "grounded"},
        ),
        _profile(
            "argumentation_preferred",
            "argumentation",
            "LFP2-038",
            disposition=ProfileDisposition.EVALUATE,
            features=eval_features,
            executable_features=eval_exec,
            limits=TIGHT_RESOURCE_LIMITS,
            notation_id="canonical_argumentation",
            parser_module="ipfs_datasets_py.logic.parsers.argumentation",
            semantic_payload={"semantics": "preferred"},
        ),
        _profile(
            "argumentation_complete",
            "argumentation",
            "LFP2-038",
            disposition=ProfileDisposition.EVALUATE,
            features=eval_features,
            executable_features=eval_exec,
            limits=TIGHT_RESOURCE_LIMITS,
            notation_id="canonical_argumentation",
            parser_module="ipfs_datasets_py.logic.parsers.argumentation",
            semantic_payload={"semantics": "complete"},
        ),
        _profile(
            "argumentation_stable",
            "argumentation",
            "LFP2-038",
            disposition=ProfileDisposition.EVALUATE,
            features=eval_features,
            executable_features=eval_exec,
            limits=TIGHT_RESOURCE_LIMITS,
            notation_id="canonical_argumentation",
            parser_module="ipfs_datasets_py.logic.parsers.argumentation",
            semantic_payload={"semantics": "stable"},
        ),
        _profile(
            "nonmonotonic_defeasible",
            "nonmonotonic_logic",
            "LFP2-038",
            disposition=ProfileDisposition.EVALUATE,
            features=eval_features,
            executable_features=eval_exec,
            limits=TIGHT_RESOURCE_LIMITS,
            notation_id="canonical_argumentation",
            parser_module="ipfs_datasets_py.logic.parsers.argumentation",
            semantic_payload={"semantics": "defeasible"},
        ),
        # LFP2-039 description logic
        _profile(
            "dl_alc",
            "description_logic",
            "LFP2-039",
            notation_id="canonical_description_logic",
            parser_module="ipfs_datasets_py.logic.parsers.description_logic",
            semantic_payload={"expressivity": "alc", "world": "open_world"},
        ),
        _profile(
            "dl_alcq",
            "description_logic",
            "LFP2-039",
            notation_id="canonical_description_logic",
            parser_module="ipfs_datasets_py.logic.parsers.description_logic",
            semantic_payload={"expressivity": "alcq", "world": "open_world"},
        ),
        _profile(
            "dl_el",
            "description_logic",
            "LFP2-039",
            notation_id="canonical_description_logic",
            parser_module="ipfs_datasets_py.logic.parsers.description_logic",
            semantic_payload={"expressivity": "el", "world": "open_world"},
        ),
        _profile(
            "ontology_legal_alcq",
            "description_logic",
            "LFP2-039",
            notation_id="canonical_description_logic",
            parser_module="ipfs_datasets_py.logic.parsers.description_logic",
            semantic_payload={"domain": "legal", "expressivity": "alcq"},
        ),
        _profile(
            "ontology_ui_alc",
            "description_logic",
            "LFP2-039",
            notation_id="canonical_description_logic",
            parser_module="ipfs_datasets_py.logic.parsers.description_logic",
            semantic_payload={"domain": "ui", "expressivity": "alc"},
        ),
        _profile(
            "ontology_intent_alc",
            "description_logic",
            "LFP2-039",
            notation_id="canonical_description_logic",
            parser_module="ipfs_datasets_py.logic.parsers.description_logic",
            semantic_payload={"domain": "intent", "expressivity": "alc"},
        ),
        _profile(
            "ontology_kg_alcq",
            "description_logic",
            "LFP2-039",
            notation_id="canonical_description_logic",
            parser_module="ipfs_datasets_py.logic.parsers.description_logic",
            semantic_payload={"domain": "knowledge_graph", "expressivity": "alcq"},
        ),
        # LFP2-040 agency
        _profile(
            "bdi_default",
            "bdi",
            "LFP2-040",
            notation_id="canonical_agency",
            parser_module="ipfs_datasets_py.logic.parsers.agency",
            semantic_payload={"family": "bdi", "frame": "kd45"},
        ),
        _profile(
            "epistemic_temporal_default",
            "epistemic_temporal",
            "LFP2-040",
            notation_id="canonical_agency",
            parser_module="ipfs_datasets_py.logic.parsers.agency",
            semantic_payload={"family": "epistemic_temporal", "frame": "s5"},
        ),
        _profile(
            "agency_default",
            "agency",
            "LFP2-040",
            notation_id="canonical_agency",
            parser_module="ipfs_datasets_py.logic.parsers.agency",
            semantic_payload={"family": "agency", "frame": "d"},
        ),
        _profile(
            "intention_agency_default",
            "intention_agency",
            "LFP2-040",
            notation_id="canonical_agency",
            parser_module="ipfs_datasets_py.logic.parsers.agency",
            semantic_payload={"family": "intention", "frame": "d"},
        ),
        # LFP2-041 fixed-point / mu-calculus
        _profile(
            "mu_calculus_guarded",
            "mu_calculus",
            "LFP2-041",
            notation_id="canonical_mu_calculus",
            authority_ceiling="bounded",
            parser_module="ipfs_datasets_py.logic.parsers.fixed_point",
            semantic_payload={
                "surface": "mu_calculus",
                "executable_support": False,
                "lifecycle": "parse_print",
            },
        ),
        _profile(
            "ctl_star_fragment_to_mu",
            "mu_calculus",
            "LFP2-041",
            notation_id="canonical_mu_calculus",
            authority_ceiling="bounded",
            parser_module="ipfs_datasets_py.logic.parsers.fixed_point",
            semantic_payload={
                "surface": "ctl_star_fragment",
                "executable_support": False,
            },
        ),
        _profile(
            "mixed_mu_ctl",
            "mu_calculus",
            "LFP2-041",
            notation_id="canonical_mu_calculus",
            authority_ceiling="bounded",
            parser_module="ipfs_datasets_py.logic.parsers.fixed_point",
            semantic_payload={"surface": "mixed", "executable_support": False},
        ),
        _profile(
            "mu_calculus_declaration_only",
            "mu_calculus",
            "LFP2-041",
            disposition=ProfileDisposition.DECLARATION_ONLY,
            features=("parse", "print"),
            executable_features=(),
            fixture_kinds=("positive", "negative"),
            notation_id="canonical_mu_calculus",
            authority_ceiling="none",
            parser_module="ipfs_datasets_py.logic.parsers.fixed_point",
            description="Declaration-only; never grants model-check executability",
            semantic_payload={
                "lifecycle": "declaration_only",
                "executable_support": False,
            },
        ),
        # LFP2-042 finite field
        _profile(
            "finite_field_bn254",
            "finite_field_constraint",
            "LFP2-042",
            limits=FIELD_RESOURCE_LIMITS,
            notation_id="canonical_finite_field_constraint",
            authority_ceiling="bounded",
            parser_module="ipfs_datasets_py.logic.parsers.finite_field",
            semantic_payload={"system": "field", "field": "bn254"},
        ),
        _profile(
            "bitvector_fixed",
            "finite_field_constraint",
            "LFP2-042",
            limits=FIELD_RESOURCE_LIMITS,
            notation_id="canonical_finite_field_constraint",
            authority_ceiling="bounded",
            parser_module="ipfs_datasets_py.logic.parsers.finite_field",
            semantic_payload={"system": "bitvector", "bit_width": 32},
        ),
        _profile(
            "r1cs_field",
            "finite_field_constraint",
            "LFP2-042",
            limits=FIELD_RESOURCE_LIMITS,
            notation_id="canonical_finite_field_constraint",
            authority_ceiling="bounded",
            parser_module="ipfs_datasets_py.logic.parsers.finite_field",
            semantic_payload={"system": "r1cs"},
        ),
        _profile(
            "plonk_field",
            "finite_field_constraint",
            "LFP2-042",
            limits=FIELD_RESOURCE_LIMITS,
            notation_id="canonical_finite_field_constraint",
            authority_ceiling="bounded",
            parser_module="ipfs_datasets_py.logic.parsers.finite_field",
            semantic_payload={"system": "plonk"},
        ),
        _profile(
            "finite_field_constraint_mixed",
            "finite_field_constraint",
            "LFP2-042",
            limits=FIELD_RESOURCE_LIMITS,
            notation_id="canonical_finite_field_constraint",
            authority_ceiling="bounded",
            parser_module="ipfs_datasets_py.logic.parsers.finite_field",
            semantic_payload={"system": "mixed"},
        ),
        # LFP2-043 session/process
        _profile(
            "linear_default",
            "linear_logic",
            "LFP2-043",
            notation_id="canonical_session_process",
            parser_module="ipfs_datasets_py.logic.parsers.session_process",
            semantic_payload={"family": "linear", "linearity": "strict"},
        ),
        _profile(
            "session_default",
            "session_process",
            "LFP2-043",
            notation_id="canonical_session_process",
            parser_module="ipfs_datasets_py.logic.parsers.session_process",
            semantic_payload={"family": "session", "duality": True},
        ),
        _profile(
            "process_default",
            "process_calculus",
            "LFP2-043",
            notation_id="canonical_session_process",
            parser_module="ipfs_datasets_py.logic.parsers.session_process",
            semantic_payload={"family": "process", "progress_model": "fair"},
        ),
        _profile(
            "relational_refinement_default",
            "refinement",
            "LFP2-043",
            notation_id="canonical_session_process",
            parser_module="ipfs_datasets_py.logic.parsers.session_process",
            semantic_payload={
                "family": "relational_refinement",
                "direction": "forward",
            },
        ),
    )


# ---------------------------------------------------------------------------
# Catalog
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LogicProfileCatalogV3:
    """Sealed Wave-2 profile catalog (``LogicProfileCatalog@3``)."""

    entries: tuple[ProfileCatalogEntryV3, ...]
    version: str = PROFILE_CATALOG_V3_MODULE_VERSION
    task_id: str = PROFILE_CATALOG_V3_TASK_ID
    goal_id: str = PROFILE_CATALOG_V3_GOAL_ID
    schema_version: str = LOGIC_PROFILE_CATALOG_V3_SCHEMA

    interface: ClassVar[str] = LOGIC_PROFILE_CATALOG_V3_INTERFACE

    def __post_init__(self) -> None:
        if not self.entries:
            raise ProfileCatalogV3Error(
                "LogicProfileCatalogV3 requires at least one entry"
            )
        seen: set[str] = set()
        for entry in self.entries:
            if not isinstance(entry, ProfileCatalogEntryV3):
                raise ProfileCatalogV3Error(
                    "entries must be ProfileCatalogEntryV3 instances"
                )
            if entry.profile_id in seen:
                raise DuplicateProfileCatalogV3Error(
                    f"duplicate profile {entry.profile_id!r}"
                )
            seen.add(entry.profile_id)
            if entry.task_id not in WAVE2_FAMILY_TASK_IDS:
                raise ProfileCatalogV3Error(
                    f"profile {entry.profile_id!r} has unexpected task "
                    f"{entry.task_id!r}"
                )
        ordered = tuple(sorted(self.entries, key=lambda item: item.profile_id))
        object.__setattr__(self, "entries", ordered)
        object.__setattr__(self, "version", _text(self.version, "version"))
        object.__setattr__(self, "task_id", _identifier(self.task_id, "task_id"))
        object.__setattr__(self, "goal_id", _identifier(self.goal_id, "goal_id"))
        if self.schema_version != LOGIC_PROFILE_CATALOG_V3_SCHEMA:
            raise ProfileCatalogV3Error(
                f"unsupported LogicProfileCatalogV3 schema {self.schema_version!r}"
            )

    @property
    def profile_ids(self) -> tuple[str, ...]:
        return tuple(entry.profile_id for entry in self.entries)

    @property
    def executable_profile_ids(self) -> tuple[str, ...]:
        return tuple(
            entry.profile_id for entry in self.entries if entry.is_executable
        )

    @property
    def declaration_only_profile_ids(self) -> tuple[str, ...]:
        return tuple(
            entry.profile_id for entry in self.entries if entry.is_declaration_only
        )

    def get(self, profile_id: str) -> ProfileCatalogEntryV3:
        key = _identifier(profile_id, "profile_id")
        for entry in self.entries:
            if entry.profile_id == key:
                return entry
        raise UnknownProfileCatalogV3Error(f"unknown profile {key!r}")

    def profiles_for_family(self, family_id: str) -> tuple[ProfileCatalogEntryV3, ...]:
        key = _identifier(family_id, "family_id")
        return tuple(entry for entry in self.entries if entry.family_id == key)

    def profiles_for_task(self, task_id: str) -> tuple[ProfileCatalogEntryV3, ...]:
        key = _identifier(task_id, "task_id")
        return tuple(entry for entry in self.entries if entry.task_id == key)

    def presence_implies_executability(self) -> bool:
        return False

    def validate_against_registry(
        self,
        registry: LogicFamilyRegistryV3 | None = None,
    ) -> None:
        """Every family-task profile must match the registry publication."""

        reg = registry if registry is not None else DEFAULT_REGISTRY_V3
        published_profiles: set[str] = set()
        for family_entry in reg.entries:
            for profile_id in family_entry.profile_ids:
                published_profiles.add(profile_id)
                if profile_id not in self:
                    raise ProfileCatalogV3Error(
                        f"registry family {family_entry.family_id!r} profile "
                        f"{profile_id!r} missing from profile catalog"
                    )
                catalog_entry = self.get(profile_id)
                if catalog_entry.family_id != family_entry.family_id:
                    # nonmonotonic_defeasible is shared across nonmonotonic and
                    # defeasible families in the registry publication.
                    if profile_id != "nonmonotonic_defeasible":
                        raise ProfileCatalogV3Error(
                            f"profile {profile_id!r} family mismatch: catalog "
                            f"{catalog_entry.family_id!r} vs registry "
                            f"{family_entry.family_id!r}"
                        )
                if catalog_entry.task_id != family_entry.task_id:
                    raise ProfileCatalogV3Error(
                        f"profile {profile_id!r} task mismatch: catalog "
                        f"{catalog_entry.task_id!r} vs registry "
                        f"{family_entry.task_id!r}"
                    )
                # Disposition compatibility: declaration_only family cannot
                # host executable profiles.
                if (
                    family_entry.disposition
                    is FamilyLifecycleDisposition.DECLARATION_ONLY
                    and catalog_entry.is_executable
                ):
                    raise ProfileCatalogV3Error(
                        f"declaration_only family {family_entry.family_id!r} "
                        f"cannot host executable profile {profile_id!r}"
                    )

        # Every executable catalog profile must appear in some registry entry.
        for entry in self.entries:
            if entry.profile_id not in published_profiles:
                # Allow profiles that refine shared families (none currently).
                if entry.family_id not in reg:
                    raise ProfileCatalogV3Error(
                        f"profile {entry.profile_id!r} family "
                        f"{entry.family_id!r} not published in registry"
                    )

        # Executable profiles require deterministic resource limits and fixtures.
        for entry in self.entries:
            if not entry.is_executable:
                continue
            limits = entry.resource_limits
            if limits.max_input_bytes < 1 or limits.max_time_ms < 1:
                raise ProfileCatalogV3Error(
                    f"executable profile {entry.profile_id!r} has invalid "
                    "resource limits"
                )
            missing = sorted(set(REQUIRED_FIXTURE_KINDS) - set(entry.fixture_kinds))
            if missing:
                raise ProfileCatalogV3Error(
                    f"executable profile {entry.profile_id!r} missing fixture "
                    f"kinds: {', '.join(missing)}"
                )

    def __contains__(self, profile_id: object) -> bool:
        if not isinstance(profile_id, str):
            return False
        return profile_id in set(self.profile_ids)

    def __iter__(self) -> Iterator[ProfileCatalogEntryV3]:
        return iter(self.entries)

    def __len__(self) -> int:
        return len(self.entries)

    def to_dict(self) -> dict[str, Any]:
        return {
            "declaration_only_profile_ids": list(self.declaration_only_profile_ids),
            "entries": [entry.to_dict() for entry in self.entries],
            "executable_profile_ids": list(self.executable_profile_ids),
            "goal_id": self.goal_id,
            "interface": self.interface,
            "presence_implies_executability": self.presence_implies_executability(),
            "profile_ids": list(self.profile_ids),
            "required_fixture_kinds": list(REQUIRED_FIXTURE_KINDS),
            "schema_version": self.schema_version,
            "task_id": self.task_id,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "LogicProfileCatalogV3":
        if not isinstance(value, Mapping):
            raise ProfileCatalogV3Error("LogicProfileCatalogV3 must be a mapping")
        raw = value.get("entries") or ()
        entries = tuple(
            item
            if isinstance(item, ProfileCatalogEntryV3)
            else ProfileCatalogEntryV3.from_dict(item)
            for item in raw
        )
        return cls(
            entries=entries,
            version=str(value.get("version") or PROFILE_CATALOG_V3_MODULE_VERSION),
            task_id=str(value.get("task_id") or PROFILE_CATALOG_V3_TASK_ID),
            goal_id=str(value.get("goal_id") or PROFILE_CATALOG_V3_GOAL_ID),
            schema_version=str(
                value.get("schema_version") or LOGIC_PROFILE_CATALOG_V3_SCHEMA
            ),
        )


def build_default_profile_catalog_v3(
    *,
    validate: bool = True,
    registry: LogicFamilyRegistryV3 | None = None,
) -> LogicProfileCatalogV3:
    """Build the sealed Wave-2 profile catalog."""

    catalog = LogicProfileCatalogV3(entries=_seed_wave2_profiles())
    if validate:
        catalog.validate_against_registry(registry)
    return catalog


DEFAULT_PROFILE_CATALOG_V3: Final = build_default_profile_catalog_v3(validate=True)

WAVE2_PUBLISHED_PROFILE_IDS: Final[frozenset[str]] = frozenset(
    DEFAULT_PROFILE_CATALOG_V3.profile_ids
)
WAVE2_EXECUTABLE_PROFILE_IDS: Final[frozenset[str]] = frozenset(
    DEFAULT_PROFILE_CATALOG_V3.executable_profile_ids
)


__all__ = [
    "DEFAULT_EXECUTABLE_FEATURES",
    "DEFAULT_PROFILE_CATALOG_V3",
    "DEFAULT_RESOURCE_LIMITS",
    "DuplicateProfileCatalogV3Error",
    "FIELD_RESOURCE_LIMITS",
    "LOGIC_PROFILE_CATALOG_V3_INTERFACE",
    "LOGIC_PROFILE_CATALOG_V3_SCHEMA",
    "LogicProfileCatalogV3",
    "PROFILE_CATALOG_ENTRY_V3_SCHEMA",
    "PROFILE_CATALOG_V3_GOAL_ID",
    "PROFILE_CATALOG_V3_MODULE_VERSION",
    "PROFILE_CATALOG_V3_TASK_ID",
    "ProfileCatalogEntryV3",
    "ProfileCatalogV3Error",
    "ProfileDisposition",
    "ProfileResourceLimits",
    "REQUIRED_FIXTURE_KINDS",
    "RESOURCE_LIMITS_V3_SCHEMA",
    "TIGHT_RESOURCE_LIMITS",
    "UnknownProfileCatalogV3Error",
    "WAVE2_EXECUTABLE_PROFILE_IDS",
    "WAVE2_PUBLISHED_PROFILE_IDS",
    "build_default_profile_catalog_v3",
]
