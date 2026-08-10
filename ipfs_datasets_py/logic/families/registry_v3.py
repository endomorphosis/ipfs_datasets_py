"""Wave-2 family registry publication (``LogicFamilyRegistry@3`` / LFP2-044).

Publishes exact registry entries for every Wave-2 family task (LFP2-037 through
LFP2-043).  Registry presence is **never** executability: each entry carries an
explicit lifecycle disposition, executable feature set, and authority ceiling.

This module is side-effect free.  It does not import parser implementations,
installers, solvers, or process runners.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any, ClassVar, Final

from ipfs_datasets_py.logic.families.registry import (
    BASELINE_FAMILY_IDS,
    DEFAULT_REGISTRY,
    DECLARATION_ONLY_FAMILY_IDS,
    FOUNDATION_FAMILY_IDS,
    PLANNED_EXTENSION_FAMILY_IDS,
    REGISTRY_INTERFACE as REGISTRY_V2_INTERFACE,
    REGISTRY_VERSION as REGISTRY_V2_VERSION,
    LogicFamilyRegistry,
)

# ---------------------------------------------------------------------------
# Interface / schema identities
# ---------------------------------------------------------------------------

LOGIC_FAMILY_REGISTRY_V3_INTERFACE: Final = "LogicFamilyRegistry@3"
LOGIC_FAMILY_REGISTRY_V3_SCHEMA: Final = "logic-family-registry/v3"
FAMILY_PUBLICATION_ENTRY_SCHEMA: Final = "logic-family-publication-entry/v3"
REGISTRY_V3_MODULE_VERSION: Final = "3.0.0"

REGISTRY_V3_TASK_ID: Final = "LFP2-044"
REGISTRY_V3_GOAL_ID: Final = "LFP2-G080"

# Wave-2 family-expansion tasks that must appear exactly once.
WAVE2_FAMILY_TASK_IDS: Final[tuple[str, ...]] = (
    "LFP2-037",
    "LFP2-038",
    "LFP2-039",
    "LFP2-040",
    "LFP2-041",
    "LFP2-042",
    "LFP2-043",
)


class FamilyLifecycleDisposition(StrEnum):
    """Lifecycle disposition for a published family entry.

    Registry presence alone never implies executability.  Only
    ``parse_print`` and ``controlled_executable`` may claim executable
    features, and only when those features are listed explicitly.
    """

    DECLARATION_ONLY = "declaration_only"
    PARSE_PRINT = "parse_print"
    CONTROLLED_EXECUTABLE = "controlled_executable"


class FamilyPublicationError(ValueError):
    """Raised when the Wave-2 family registry publication is invalid."""


class DuplicateFamilyPublicationError(FamilyPublicationError):
    """Raised when a family or task id collides in the publication set."""


class UnknownFamilyPublicationError(FamilyPublicationError, KeyError):
    """Raised when a published family or task cannot be resolved."""


def _text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise FamilyPublicationError(
            f"{field_name} must be a non-empty trimmed string"
        )
    if "\x00" in value:
        raise FamilyPublicationError(f"{field_name} must not contain NUL bytes")
    return value


def _identifier(value: object, field_name: str) -> str:
    result = _text(value, field_name)
    if any(character.isspace() for character in result):
        raise FamilyPublicationError(
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
            raise FamilyPublicationError(f"{field_name} must be a sequence of strings")
        items = tuple(_identifier(item, f"{field_name} item") for item in value)
        if len(set(items)) != len(items):
            raise FamilyPublicationError(f"{field_name} must not contain duplicates")
    if not items and not allow_empty:
        raise FamilyPublicationError(f"{field_name} must not be empty")
    return items


# ---------------------------------------------------------------------------
# Publication entry
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FamilyPublicationEntry:
    """Exact registry publication for one Wave-2 family identity.

    Interface fragment: ``logic-family-publication-entry/v3``.
    """

    family_id: str
    task_id: str
    name: str
    disposition: FamilyLifecycleDisposition | str
    profile_ids: tuple[str, ...]
    feature_ids: tuple[str, ...] = ()
    executable_features: tuple[str, ...] = ()
    parser_module: str = ""
    notation_id: str = ""
    semantic_identity: str = ""
    authority_ceiling: str = "advisory"
    aliases: tuple[str, ...] = ()
    baseline_family_ids: tuple[str, ...] = ()
    notes: str = ""
    schema_version: str = FAMILY_PUBLICATION_ENTRY_SCHEMA

    interface: ClassVar[str] = LOGIC_FAMILY_REGISTRY_V3_INTERFACE

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "family_id", _identifier(self.family_id, "family_id")
        )
        object.__setattr__(self, "task_id", _identifier(self.task_id, "task_id"))
        object.__setattr__(self, "name", _text(self.name, "name"))

        disposition = self.disposition
        if not isinstance(disposition, FamilyLifecycleDisposition):
            try:
                disposition = FamilyLifecycleDisposition(str(disposition))
            except ValueError as error:
                raise FamilyPublicationError(
                    f"unknown disposition {self.disposition!r}"
                ) from error
        object.__setattr__(self, "disposition", disposition)

        profiles = _string_tuple(self.profile_ids, "profile_ids", allow_empty=False)
        object.__setattr__(self, "profile_ids", profiles)

        features = _string_tuple(self.feature_ids, "feature_ids")
        object.__setattr__(self, "feature_ids", features)

        executable = _string_tuple(self.executable_features, "executable_features")
        unknown_exec = sorted(set(executable) - set(features))
        if unknown_exec:
            raise FamilyPublicationError(
                f"family {self.family_id!r} executable_features not in "
                f"feature_ids: {', '.join(unknown_exec)}"
            )
        object.__setattr__(self, "executable_features", executable)

        if disposition is FamilyLifecycleDisposition.DECLARATION_ONLY:
            if executable:
                raise FamilyPublicationError(
                    f"declaration_only family {self.family_id!r} cannot claim "
                    "executable_features; registry presence never implies "
                    "executability"
                )
        elif disposition is FamilyLifecycleDisposition.PARSE_PRINT:
            if "parse" not in features:
                raise FamilyPublicationError(
                    f"parse_print family {self.family_id!r} must declare "
                    "the parse feature"
                )
            if executable and not set(executable) <= {"parse", "print", "elaborate", "source_map", "evaluate"}:
                raise FamilyPublicationError(
                    f"parse_print family {self.family_id!r} executable features "
                    "must stay within parse/print/elaborate/source_map/evaluate"
                )
        elif disposition is FamilyLifecycleDisposition.CONTROLLED_EXECUTABLE:
            if not executable:
                raise FamilyPublicationError(
                    f"controlled_executable family {self.family_id!r} must list "
                    "explicit executable_features"
                )

        if self.parser_module:
            object.__setattr__(
                self, "parser_module", _text(self.parser_module, "parser_module")
            )
        if self.notation_id:
            object.__setattr__(
                self, "notation_id", _identifier(self.notation_id, "notation_id")
            )
        if not self.semantic_identity:
            object.__setattr__(
                self,
                "semantic_identity",
                f"logic-family/{self.family_id}/v3",
            )
        else:
            object.__setattr__(
                self,
                "semantic_identity",
                _text(self.semantic_identity, "semantic_identity"),
            )
        object.__setattr__(
            self,
            "authority_ceiling",
            _identifier(self.authority_ceiling, "authority_ceiling"),
        )
        object.__setattr__(self, "aliases", _string_tuple(self.aliases, "aliases"))
        object.__setattr__(
            self,
            "baseline_family_ids",
            _string_tuple(self.baseline_family_ids, "baseline_family_ids"),
        )
        if self.schema_version != FAMILY_PUBLICATION_ENTRY_SCHEMA:
            raise FamilyPublicationError(
                f"unsupported FamilyPublicationEntry schema "
                f"{self.schema_version!r}"
            )

    @property
    def is_declaration_only(self) -> bool:
        return self.disposition is FamilyLifecycleDisposition.DECLARATION_ONLY

    @property
    def is_executable(self) -> bool:
        """True only when disposition and explicit features authorize execution.

        Registry presence alone is never enough.
        """

        if self.disposition is FamilyLifecycleDisposition.DECLARATION_ONLY:
            return False
        return bool(self.executable_features)

    def claims_feature(self, feature_id: str) -> bool:
        return feature_id in self.feature_ids

    def feature_is_executable(self, feature_id: str) -> bool:
        return self.is_executable and feature_id in self.executable_features

    def to_dict(self) -> dict[str, Any]:
        disposition = (
            self.disposition.value
            if isinstance(self.disposition, FamilyLifecycleDisposition)
            else str(self.disposition)
        )
        return {
            "aliases": list(self.aliases),
            "authority_ceiling": self.authority_ceiling,
            "baseline_family_ids": list(self.baseline_family_ids),
            "disposition": disposition,
            "executable_features": list(self.executable_features),
            "family_id": self.family_id,
            "feature_ids": list(self.feature_ids),
            "is_declaration_only": self.is_declaration_only,
            "is_executable": self.is_executable,
            "name": self.name,
            "notation_id": self.notation_id,
            "notes": self.notes,
            "parser_module": self.parser_module,
            "profile_ids": list(self.profile_ids),
            "schema_version": self.schema_version,
            "semantic_identity": self.semantic_identity,
            "task_id": self.task_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "FamilyPublicationEntry":
        if not isinstance(value, Mapping):
            raise FamilyPublicationError("FamilyPublicationEntry must be a mapping")
        return cls(
            family_id=str(value.get("family_id") or ""),
            task_id=str(value.get("task_id") or ""),
            name=str(value.get("name") or ""),
            disposition=str(value.get("disposition") or ""),
            profile_ids=tuple(value.get("profile_ids") or ()),
            feature_ids=tuple(value.get("feature_ids") or ()),
            executable_features=tuple(value.get("executable_features") or ()),
            parser_module=str(value.get("parser_module") or ""),
            notation_id=str(value.get("notation_id") or ""),
            semantic_identity=str(value.get("semantic_identity") or ""),
            authority_ceiling=str(value.get("authority_ceiling") or "advisory"),
            aliases=tuple(value.get("aliases") or ()),
            baseline_family_ids=tuple(value.get("baseline_family_ids") or ()),
            notes=str(value.get("notes") or ""),
            schema_version=str(
                value.get("schema_version") or FAMILY_PUBLICATION_ENTRY_SCHEMA
            ),
        )


# ---------------------------------------------------------------------------
# Seed publication set (exact Wave-2 family tasks)
# ---------------------------------------------------------------------------

_PARSE_PRINT_FEATURES: Final[tuple[str, ...]] = (
    "parse",
    "print",
    "elaborate",
    "source_map",
)
_PARSE_PRINT_EXECUTABLE: Final[tuple[str, ...]] = ("parse", "print", "source_map")
_EVAL_FEATURES: Final[tuple[str, ...]] = (
    "parse",
    "print",
    "elaborate",
    "source_map",
    "evaluate",
)
_EVAL_EXECUTABLE: Final[tuple[str, ...]] = (
    "parse",
    "print",
    "source_map",
    "evaluate",
)


def _entry(
    family_id: str,
    task_id: str,
    name: str,
    *,
    disposition: FamilyLifecycleDisposition,
    profile_ids: Sequence[str],
    parser_module: str,
    notation_id: str,
    features: Sequence[str] = _PARSE_PRINT_FEATURES,
    executable_features: Sequence[str] = _PARSE_PRINT_EXECUTABLE,
    authority_ceiling: str = "advisory",
    aliases: Sequence[str] = (),
    baseline_family_ids: Sequence[str] = (),
    notes: str = "",
) -> FamilyPublicationEntry:
    return FamilyPublicationEntry(
        family_id=family_id,
        task_id=task_id,
        name=name,
        disposition=disposition,
        profile_ids=tuple(profile_ids),
        feature_ids=tuple(features),
        executable_features=tuple(executable_features),
        parser_module=parser_module,
        notation_id=notation_id,
        authority_ceiling=authority_ceiling,
        aliases=tuple(aliases),
        baseline_family_ids=tuple(baseline_family_ids),
        notes=notes,
    )


def _seed_wave2_family_entries() -> tuple[FamilyPublicationEntry, ...]:
    """Exact registry entries for LFP2-037 through LFP2-043."""

    return (
        # LFP2-037 — normative (family identity remains deontic)
        _entry(
            "deontic",
            "LFP2-037",
            "Normative / deontic logic (Wave-2 profiles)",
            disposition=FamilyLifecycleDisposition.PARSE_PRINT,
            profile_ids=(
                "normative_dyadic",
                "normative_defeasible",
                "normative_prioritized",
                "normative_contrary_to_duty",
            ),
            parser_module="ipfs_datasets_py.logic.parsers.normative_v2",
            notation_id="canonical_normative_v2",
            features=_EVAL_FEATURES,
            executable_features=_EVAL_EXECUTABLE,
            authority_ceiling="bounded",
            baseline_family_ids=("deontic",),
            notes="Named normative profiles; never classical entailment.",
        ),
        # LFP2-038 — argumentation / nonmonotonic / defeasible
        _entry(
            "argumentation",
            "LFP2-038",
            "Argumentation frameworks",
            disposition=FamilyLifecycleDisposition.PARSE_PRINT,
            profile_ids=(
                "argumentation_grounded",
                "argumentation_preferred",
                "argumentation_complete",
                "argumentation_stable",
            ),
            parser_module="ipfs_datasets_py.logic.parsers.argumentation",
            notation_id="canonical_argumentation",
            features=_EVAL_FEATURES,
            executable_features=_EVAL_EXECUTABLE,
            authority_ceiling="advisory",
            baseline_family_ids=("argumentation",),
            notes="Undecided and multi-extension outcomes preserved.",
        ),
        _entry(
            "nonmonotonic_logic",
            "LFP2-038",
            "Nonmonotonic logic",
            disposition=FamilyLifecycleDisposition.PARSE_PRINT,
            profile_ids=("nonmonotonic_defeasible",),
            parser_module="ipfs_datasets_py.logic.parsers.argumentation",
            notation_id="canonical_argumentation",
            features=_EVAL_FEATURES,
            executable_features=_EVAL_EXECUTABLE,
            authority_ceiling="advisory",
            baseline_family_ids=("nonmonotonic_logic",),
        ),
        _entry(
            "defeasible_logic",
            "LFP2-038",
            "Defeasible logic",
            disposition=FamilyLifecycleDisposition.PARSE_PRINT,
            profile_ids=("nonmonotonic_defeasible",),
            parser_module="ipfs_datasets_py.logic.parsers.argumentation",
            notation_id="canonical_argumentation",
            features=_EVAL_FEATURES,
            executable_features=_EVAL_EXECUTABLE,
            authority_ceiling="advisory",
            baseline_family_ids=("defeasible_logic",),
        ),
        # LFP2-039 — description logic / ontology
        _entry(
            "description_logic",
            "LFP2-039",
            "Description logic and ontology profiles",
            disposition=FamilyLifecycleDisposition.PARSE_PRINT,
            profile_ids=(
                "dl_alc",
                "dl_alcq",
                "dl_el",
                "ontology_legal_alcq",
                "ontology_ui_alc",
                "ontology_intent_alc",
                "ontology_kg_alcq",
            ),
            parser_module="ipfs_datasets_py.logic.parsers.description_logic",
            notation_id="canonical_description_logic",
            authority_ceiling="advisory",
            aliases=("dl", "ontology_logic"),
            baseline_family_ids=("description_logic",),
            notes="Open-world; unsupported OWL fails closed without FOL collapse.",
        ),
        # LFP2-040 — BDI / epistemic-temporal / agency / intention
        _entry(
            "bdi",
            "LFP2-040",
            "Belief-desire-intention logic",
            disposition=FamilyLifecycleDisposition.PARSE_PRINT,
            profile_ids=("bdi_default",),
            parser_module="ipfs_datasets_py.logic.parsers.agency",
            notation_id="canonical_agency",
            authority_ceiling="advisory",
            baseline_family_ids=("intention_agency", "doxastic"),
            notes="BDI is never conflated with DCEC.",
        ),
        _entry(
            "epistemic_temporal",
            "LFP2-040",
            "Epistemic-temporal logic",
            disposition=FamilyLifecycleDisposition.PARSE_PRINT,
            profile_ids=("epistemic_temporal_default",),
            parser_module="ipfs_datasets_py.logic.parsers.agency",
            notation_id="canonical_agency",
            authority_ceiling="advisory",
            baseline_family_ids=("epistemic", "temporal"),
        ),
        _entry(
            "agency",
            "LFP2-040",
            "Agency and action logic",
            disposition=FamilyLifecycleDisposition.PARSE_PRINT,
            profile_ids=("agency_default",),
            parser_module="ipfs_datasets_py.logic.parsers.agency",
            notation_id="canonical_agency",
            authority_ceiling="advisory",
            baseline_family_ids=("intention_agency",),
        ),
        _entry(
            "intention_agency",
            "LFP2-040",
            "Intention and agency logic",
            disposition=FamilyLifecycleDisposition.PARSE_PRINT,
            profile_ids=("intention_agency_default",),
            parser_module="ipfs_datasets_py.logic.parsers.agency",
            notation_id="canonical_agency",
            authority_ceiling="advisory",
            aliases=("agency_logic",),
            baseline_family_ids=("intention_agency",),
        ),
        # LFP2-041 — mu-calculus / fixed-point
        _entry(
            "mu_calculus",
            "LFP2-041",
            "Modal mu-calculus and controlled CTL-star lowering",
            disposition=FamilyLifecycleDisposition.PARSE_PRINT,
            profile_ids=(
                "mu_calculus_guarded",
                "ctl_star_fragment_to_mu",
                "mixed_mu_ctl",
                "mu_calculus_declaration_only",
            ),
            parser_module="ipfs_datasets_py.logic.parsers.fixed_point",
            notation_id="canonical_mu_calculus",
            features=_PARSE_PRINT_FEATURES,
            # Default executable features are parse/print only; model-check
            # requires controlled_executable profile opt-in.
            executable_features=_PARSE_PRINT_EXECUTABLE,
            authority_ceiling="bounded",
            baseline_family_ids=("mu_calculus", "temporal"),
            notes=(
                "Declaration never implies executable model-check support; "
                "profiles default executable_support=False."
            ),
        ),
        # LFP2-042 — finite-field / bitvector / ZK constraint
        _entry(
            "finite_field_constraint",
            "LFP2-042",
            "Finite-field, bitvector, and ZK constraint logic",
            disposition=FamilyLifecycleDisposition.PARSE_PRINT,
            profile_ids=(
                "finite_field_bn254",
                "bitvector_fixed",
                "r1cs_field",
                "plonk_field",
                "finite_field_constraint_mixed",
            ),
            parser_module="ipfs_datasets_py.logic.parsers.finite_field",
            notation_id="canonical_finite_field_constraint",
            authority_ceiling="bounded",
            aliases=("ffc", "finite_field"),
            baseline_family_ids=("finite_field_constraint", "first_order"),
            notes=(
                "Arithmetic/SMT evidence cannot become ZK proof authority."
            ),
        ),
        # LFP2-043 — linear / session / process / refinement
        _entry(
            "linear_logic",
            "LFP2-043",
            "Linear resource logic",
            disposition=FamilyLifecycleDisposition.PARSE_PRINT,
            profile_ids=("linear_default",),
            parser_module="ipfs_datasets_py.logic.parsers.session_process",
            notation_id="canonical_session_process",
            authority_ceiling="advisory",
            baseline_family_ids=("separation_logic",),
        ),
        _entry(
            "session_process",
            "LFP2-043",
            "Session and process logic",
            disposition=FamilyLifecycleDisposition.PARSE_PRINT,
            profile_ids=("session_default",),
            parser_module="ipfs_datasets_py.logic.parsers.session_process",
            notation_id="canonical_session_process",
            authority_ceiling="advisory",
            aliases=("session_types", "process_logic"),
            baseline_family_ids=("session_process",),
        ),
        _entry(
            "process_calculus",
            "LFP2-043",
            "Process calculus",
            disposition=FamilyLifecycleDisposition.PARSE_PRINT,
            profile_ids=("process_default",),
            parser_module="ipfs_datasets_py.logic.parsers.session_process",
            notation_id="canonical_session_process",
            authority_ceiling="advisory",
            baseline_family_ids=("session_process", "concurrency"),
        ),
        _entry(
            "refinement",
            "LFP2-043",
            "Relational refinement logic",
            disposition=FamilyLifecycleDisposition.PARSE_PRINT,
            profile_ids=("relational_refinement_default",),
            parser_module="ipfs_datasets_py.logic.parsers.session_process",
            notation_id="canonical_session_process",
            authority_ceiling="advisory",
            baseline_family_ids=("refinement",),
        ),
    )


# ---------------------------------------------------------------------------
# Registry catalog
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LogicFamilyRegistryV3:
    """Sealed Wave-2 family registry publication (``LogicFamilyRegistry@3``).

    Composes baseline :class:`LogicFamilyRegistry` identities with exact
    Wave-2 family publication entries.  Presence in this catalog never
    authorizes prover execution.
    """

    entries: tuple[FamilyPublicationEntry, ...]
    baseline_registry_version: str = REGISTRY_V2_VERSION
    baseline_registry_interface: str = REGISTRY_V2_INTERFACE
    version: str = REGISTRY_V3_MODULE_VERSION
    task_id: str = REGISTRY_V3_TASK_ID
    goal_id: str = REGISTRY_V3_GOAL_ID
    schema_version: str = LOGIC_FAMILY_REGISTRY_V3_SCHEMA

    interface: ClassVar[str] = LOGIC_FAMILY_REGISTRY_V3_INTERFACE

    def __post_init__(self) -> None:
        if not self.entries:
            raise FamilyPublicationError(
                "LogicFamilyRegistryV3 requires at least one publication entry"
            )
        seen_families: dict[str, str] = {}
        task_coverage: set[str] = set()
        for entry in self.entries:
            if not isinstance(entry, FamilyPublicationEntry):
                raise FamilyPublicationError(
                    "entries must be FamilyPublicationEntry instances"
                )
            if entry.family_id in seen_families:
                raise DuplicateFamilyPublicationError(
                    f"duplicate family publication {entry.family_id!r}"
                )
            seen_families[entry.family_id] = entry.task_id
            task_coverage.add(entry.task_id)

        missing_tasks = sorted(set(WAVE2_FAMILY_TASK_IDS) - task_coverage)
        if missing_tasks:
            raise FamilyPublicationError(
                "missing exact registry entries for family tasks: "
                + ", ".join(missing_tasks)
            )
        extra_tasks = sorted(task_coverage - set(WAVE2_FAMILY_TASK_IDS))
        if extra_tasks:
            raise FamilyPublicationError(
                "unexpected family task ids outside Wave-2 set: "
                + ", ".join(extra_tasks)
            )

        # Stable order by family_id.
        ordered = tuple(sorted(self.entries, key=lambda item: item.family_id))
        object.__setattr__(self, "entries", ordered)
        object.__setattr__(self, "version", _text(self.version, "version"))
        object.__setattr__(self, "task_id", _identifier(self.task_id, "task_id"))
        object.__setattr__(self, "goal_id", _identifier(self.goal_id, "goal_id"))
        if self.schema_version != LOGIC_FAMILY_REGISTRY_V3_SCHEMA:
            raise FamilyPublicationError(
                f"unsupported LogicFamilyRegistryV3 schema {self.schema_version!r}"
            )

    @property
    def family_ids(self) -> tuple[str, ...]:
        return tuple(entry.family_id for entry in self.entries)

    @property
    def task_ids(self) -> tuple[str, ...]:
        return tuple(sorted({entry.task_id for entry in self.entries}))

    @property
    def executable_family_ids(self) -> tuple[str, ...]:
        return tuple(
            entry.family_id for entry in self.entries if entry.is_executable
        )

    @property
    def declaration_only_family_ids(self) -> tuple[str, ...]:
        return tuple(
            entry.family_id for entry in self.entries if entry.is_declaration_only
        )

    def get(self, family_id: str) -> FamilyPublicationEntry:
        key = _identifier(family_id, "family_id")
        for entry in self.entries:
            if entry.family_id == key:
                return entry
        raise UnknownFamilyPublicationError(f"unknown family publication {key!r}")

    def get_by_task(self, task_id: str) -> tuple[FamilyPublicationEntry, ...]:
        key = _identifier(task_id, "task_id")
        matches = tuple(entry for entry in self.entries if entry.task_id == key)
        if not matches:
            raise UnknownFamilyPublicationError(
                f"no family publication for task {key!r}"
            )
        return matches

    def profiles_for(self, family_id: str) -> tuple[str, ...]:
        return self.get(family_id).profile_ids

    def claims_executability(self, family_id: str) -> bool:
        """Registry presence alone never implies executability."""

        try:
            return self.get(family_id).is_executable
        except FamilyPublicationError:
            return False

    def presence_implies_executability(self) -> bool:
        """Hard-zero safety floor: always False for this catalog."""

        return False

    def __contains__(self, family_id: object) -> bool:
        if not isinstance(family_id, str):
            return False
        return family_id in set(self.family_ids)

    def __iter__(self) -> Iterator[FamilyPublicationEntry]:
        return iter(self.entries)

    def __len__(self) -> int:
        return len(self.entries)

    def validate_against_baseline(
        self,
        registry: LogicFamilyRegistry | None = None,
    ) -> None:
        """Fail closed if a Wave-2 entry contradicts baseline taxonomy rules."""

        baseline = registry if registry is not None else DEFAULT_REGISTRY
        for entry in self.entries:
            for baseline_id in entry.baseline_family_ids:
                if baseline_id not in BASELINE_FAMILY_IDS and baseline_id not in baseline:
                    # Allow new Wave-2 family ids that refine planned extensions.
                    if baseline_id not in {
                        "bdi",
                        "agency",
                        "epistemic_temporal",
                        "linear_logic",
                        "process_calculus",
                        "concurrency",
                    }:
                        raise FamilyPublicationError(
                            f"family {entry.family_id!r} references unknown "
                            f"baseline family {baseline_id!r}"
                        )
            # Declaration-only baseline families may be promoted to parse_print
            # only when explicit executable features are listed and disposition
            # is not declaration_only.
            if (
                entry.family_id in DECLARATION_ONLY_FAMILY_IDS
                and entry.is_declaration_only is False
                and not entry.executable_features
                and entry.disposition
                is not FamilyLifecycleDisposition.DECLARATION_ONLY
            ):
                raise FamilyPublicationError(
                    f"promoted declaration-only baseline family "
                    f"{entry.family_id!r} must list executable_features or "
                    "remain declaration_only"
                )

    def to_dict(self) -> dict[str, Any]:
        return {
            "baseline_registry_interface": self.baseline_registry_interface,
            "baseline_registry_version": self.baseline_registry_version,
            "declaration_only_family_ids": list(self.declaration_only_family_ids),
            "entries": [entry.to_dict() for entry in self.entries],
            "executable_family_ids": list(self.executable_family_ids),
            "family_ids": list(self.family_ids),
            "goal_id": self.goal_id,
            "interface": self.interface,
            "presence_implies_executability": self.presence_implies_executability(),
            "schema_version": self.schema_version,
            "task_id": self.task_id,
            "task_ids": list(self.task_ids),
            "version": self.version,
            "wave2_family_task_ids": list(WAVE2_FAMILY_TASK_IDS),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "LogicFamilyRegistryV3":
        if not isinstance(value, Mapping):
            raise FamilyPublicationError("LogicFamilyRegistryV3 must be a mapping")
        raw_entries = value.get("entries") or ()
        entries = tuple(
            item
            if isinstance(item, FamilyPublicationEntry)
            else FamilyPublicationEntry.from_dict(item)
            for item in raw_entries
        )
        return cls(
            entries=entries,
            baseline_registry_version=str(
                value.get("baseline_registry_version") or REGISTRY_V2_VERSION
            ),
            baseline_registry_interface=str(
                value.get("baseline_registry_interface") or REGISTRY_V2_INTERFACE
            ),
            version=str(value.get("version") or REGISTRY_V3_MODULE_VERSION),
            task_id=str(value.get("task_id") or REGISTRY_V3_TASK_ID),
            goal_id=str(value.get("goal_id") or REGISTRY_V3_GOAL_ID),
            schema_version=str(
                value.get("schema_version") or LOGIC_FAMILY_REGISTRY_V3_SCHEMA
            ),
        )


def build_default_registry_v3(
    *,
    validate: bool = True,
) -> LogicFamilyRegistryV3:
    """Build the sealed Wave-2 family registry publication."""

    catalog = LogicFamilyRegistryV3(entries=_seed_wave2_family_entries())
    if validate:
        catalog.validate_against_baseline()
    return catalog


DEFAULT_REGISTRY_V3: Final = build_default_registry_v3(validate=True)

# Convenience projections.
WAVE2_PUBLISHED_FAMILY_IDS: Final[frozenset[str]] = frozenset(
    DEFAULT_REGISTRY_V3.family_ids
)
WAVE2_EXECUTABLE_FAMILY_IDS: Final[frozenset[str]] = frozenset(
    DEFAULT_REGISTRY_V3.executable_family_ids
)
WAVE2_FAMILY_TASK_TO_FAMILIES: Final[Mapping[str, tuple[str, ...]]] = MappingProxyType(
    {
        task_id: tuple(
            entry.family_id
            for entry in DEFAULT_REGISTRY_V3.entries
            if entry.task_id == task_id
        )
        for task_id in WAVE2_FAMILY_TASK_IDS
    }
)


__all__ = [
    "DEFAULT_REGISTRY_V3",
    "DECLARATION_ONLY_FAMILY_IDS",
    "DuplicateFamilyPublicationError",
    "FAMILY_PUBLICATION_ENTRY_SCHEMA",
    "FOUNDATION_FAMILY_IDS",
    "FamilyLifecycleDisposition",
    "FamilyPublicationEntry",
    "FamilyPublicationError",
    "LOGIC_FAMILY_REGISTRY_V3_INTERFACE",
    "LOGIC_FAMILY_REGISTRY_V3_SCHEMA",
    "LogicFamilyRegistryV3",
    "PLANNED_EXTENSION_FAMILY_IDS",
    "REGISTRY_V3_GOAL_ID",
    "REGISTRY_V3_MODULE_VERSION",
    "REGISTRY_V3_TASK_ID",
    "UnknownFamilyPublicationError",
    "WAVE2_EXECUTABLE_FAMILY_IDS",
    "WAVE2_FAMILY_TASK_IDS",
    "WAVE2_FAMILY_TASK_TO_FAMILIES",
    "WAVE2_PUBLISHED_FAMILY_IDS",
    "build_default_registry_v3",
]
