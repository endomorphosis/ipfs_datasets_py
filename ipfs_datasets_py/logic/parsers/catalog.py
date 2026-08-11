"""Lazy parser descriptor catalog (``LogicParserCatalog@1`` / LFP-040).

Every individual family frontend contributes an **inert local descriptor** —
notation/profile keys and metadata only.  This catalog projects those local
contributions into one sealed, side-effect-free view.

Guarantees:

* Descriptors never edit a shared :class:`LogicParserRegistry` or family registry.
* Construction never imports family parser implementations, installers, solvers,
  network clients, subprocesses, or models.
* The final projection rejects duplicate descriptor IDs, duplicate exact keys,
  eager implementation bindings, and unknown family references.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, ClassVar, Final

from ipfs_datasets_py.logic.families.registry import (
    BASELINE_FAMILY_IDS,
    DEFAULT_REGISTRY,
    LogicFamilyRegistry,
)
from ipfs_datasets_py.logic.syntax_core.registry import (
    LOGIC_PARSER_DESCRIPTOR_INTERFACE,
    LogicParserDescriptor,
    ParserKey,
)


LOGIC_PARSER_CATALOG_INTERFACE: Final = "LogicParserCatalog@1"
LOGIC_PARSER_CATALOG_SCHEMA_VERSION: Final = "logic-parser-catalog/v1"
LOGIC_PARSER_CATALOG_VERSION: Final = "1.0.0"
CATALOG_TASK_ID: Final = "LFP-040"
CATALOG_GOAL_ID: Final = "LFP-G080"

# Module stems under ``ipfs_datasets_py.logic.parsers`` that own a frontend.
# Adapters/joins (classical_adapters, runtime_mtl_adapter, kernel_targets) are
# route surfaces, not notation parsers; they are excluded from the catalog.
PARSER_CONTRIBUTION_MODULES: Final[tuple[str, ...]] = (
    "event_calculus",
    "flogic",
    "fol",
    "hyper",
    "legacy_modal",
    "modal",
    "program",
    "protocol",
    "resource",
    "rules",
    "smtlib",
    "state",
    "tamarin",
    "temporal",
    "tptp",
)


class ParserCatalogError(ValueError):
    """Raised when the parser catalog is malformed or contradictory."""


class DuplicateParserCatalogEntryError(ParserCatalogError):
    """Raised when a descriptor id or exact key is contributed twice."""


class EagerParserCatalogEntryError(ParserCatalogError):
    """Raised when a contribution tries to bind an implementation eagerly."""


class UnknownParserCatalogEntryError(ParserCatalogError):
    """Raised when a contribution references an unknown family or module."""


def _text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ParserCatalogError(f"{field_name} must be a non-empty trimmed string")
    if "\x00" in value:
        raise ParserCatalogError(f"{field_name} must not contain NUL bytes")
    return value


def _identifier(value: object, field_name: str) -> str:
    result = _text(value, field_name)
    if any(character.isspace() for character in result):
        raise ParserCatalogError(
            f"{field_name} must not contain whitespace; got {result!r}"
        )
    return result


def _family_value(family_id: object) -> str:
    """Project a family identity to its canonical string value."""

    if family_id is None:
        raise ParserCatalogError("family_id is required for catalog contributions")
    if hasattr(family_id, "value"):
        return _identifier(getattr(family_id, "value"), "family_id")
    if isinstance(family_id, Mapping):
        return _identifier(family_id.get("value") or family_id.get("id"), "family_id")
    return _identifier(family_id, "family_id")


# ---------------------------------------------------------------------------
# Local inert contributions (one per individual parser module)
# ---------------------------------------------------------------------------

# Specs are pure data.  ``implementation`` is a dotted path *label* only —
# never imported by this module.  Each entry is the local descriptor the
# named parser module contributes without mutating a shared registry.
_LOCAL_PARSER_CONTRIBUTIONS: Final[tuple[dict[str, Any], ...]] = (
    {
        "module": "fol",
        "descriptor_id": "parser:local:canonical-fol",
        "notation_id": "canonical_fol",
        "notation_version": "1.0.0",
        "semantic_profile_id": "classical",
        "family_id": "first_order",
        "features": ("elaborate", "parse", "print"),
        "implementation": "ipfs_datasets_py.logic.parsers.fol:CanonicalFOLParser",
    },
    {
        "module": "smtlib",
        "descriptor_id": "parser:local:smtlib2",
        "notation_id": "smtlib2",
        "notation_version": "2.6.0",
        "semantic_profile_id": "smt_core",
        "family_id": "first_order",
        "features": ("parse", "print"),
        "implementation": "ipfs_datasets_py.logic.parsers.smtlib:SMTLIB2Parser",
    },
    {
        "module": "tptp",
        "descriptor_id": "parser:local:tptp",
        "notation_id": "tptp",
        "notation_version": "7.0.0",
        "semantic_profile_id": "fof",
        "family_id": "first_order",
        "features": ("parse", "print"),
        "implementation": "ipfs_datasets_py.logic.parsers.tptp:TPTPParser",
    },
    {
        "module": "rules",
        "descriptor_id": "parser:local:rules",
        "notation_id": "datalog_rules",
        "notation_version": "1.0.0",
        "semantic_profile_id": "horn",
        "family_id": "datalog",
        "features": ("parse", "print"),
        "implementation": "ipfs_datasets_py.logic.parsers.rules:RuleParser",
    },
    {
        "module": "rules",
        "descriptor_id": "parser:local:secpal",
        "notation_id": "datalog_rules",
        "notation_version": "1.0.0",
        "semantic_profile_id": "secpal",
        "family_id": "authorization",
        "features": ("parse", "print"),
        "implementation": "ipfs_datasets_py.logic.parsers.rules:SecPALParser",
    },
    {
        "module": "flogic",
        "descriptor_id": "parser:local:flogic",
        "notation_id": "flogic",
        "notation_version": "1.0.0",
        "semantic_profile_id": "frame_core",
        "family_id": "frame_logic",
        "features": ("parse", "print"),
        "implementation": "ipfs_datasets_py.logic.parsers.flogic:FLogicParser",
    },
    {
        "module": "modal",
        "descriptor_id": "parser:local:modal",
        "notation_id": "canonical_modal",
        "notation_version": "1.0.0",
        "semantic_profile_id": "kripke_k",
        "family_id": "modal",
        "features": ("parse", "print"),
        "implementation": "ipfs_datasets_py.logic.parsers.modal:ModalParser",
    },
    {
        "module": "modal",
        "descriptor_id": "parser:local:deontic",
        "notation_id": "canonical_modal",
        "notation_version": "1.0.0",
        "semantic_profile_id": "normative_monadic",
        "family_id": "deontic",
        "features": ("parse", "print"),
        "implementation": "ipfs_datasets_py.logic.parsers.modal:NormativeParser",
    },
    {
        "module": "modal",
        "descriptor_id": "parser:local:epistemic",
        "notation_id": "canonical_modal",
        "notation_version": "1.0.0",
        "semantic_profile_id": "epistemic",
        "family_id": "epistemic",
        "features": ("parse", "print"),
        "implementation": "ipfs_datasets_py.logic.parsers.modal:CognitiveParser",
    },
    {
        "module": "temporal",
        "descriptor_id": "parser:local:temporal",
        "notation_id": "canonical_temporal",
        "notation_version": "1.0.0",
        "semantic_profile_id": "ltl",
        "family_id": "temporal",
        "features": ("parse", "print"),
        "implementation": "ipfs_datasets_py.logic.parsers.temporal:TemporalParser",
    },
    {
        "module": "state",
        "descriptor_id": "parser:local:state",
        "notation_id": "canonical_state_property",
        "notation_version": "1.0.0",
        "semantic_profile_id": "tla_controlled",
        "family_id": "transition_system",
        "features": ("parse", "print"),
        "implementation": "ipfs_datasets_py.logic.parsers.state:StatePropertyParser",
    },
    {
        "module": "hyper",
        "descriptor_id": "parser:local:hyperltl",
        "notation_id": "canonical_hyperltl",
        "notation_version": "1.0.0",
        "semantic_profile_id": "hyperltl",
        "family_id": "hyperproperty",
        "features": ("parse", "print"),
        "implementation": "ipfs_datasets_py.logic.parsers.hyper:HyperLTLParser",
    },
    {
        "module": "protocol",
        "descriptor_id": "parser:local:symbolic-protocol",
        "notation_id": "symbolic_protocol",
        "notation_version": "1.0.0",
        "semantic_profile_id": "applied_pi_controlled",
        "family_id": "cryptographic_protocol",
        "features": ("parse", "print"),
        "implementation": (
            "ipfs_datasets_py.logic.parsers.protocol:SymbolicProtocolParser"
        ),
    },
    {
        "module": "tamarin",
        "descriptor_id": "parser:local:tamarin",
        "notation_id": "tamarin_spthy",
        "notation_version": "1.0.0",
        "semantic_profile_id": "multiset_rewriting_controlled",
        "family_id": "cryptographic_protocol",
        "features": ("parse", "print"),
        "implementation": "ipfs_datasets_py.logic.parsers.tamarin:TamarinParser",
    },
    {
        "module": "program",
        "descriptor_id": "parser:local:program",
        "notation_id": "canonical_program_logic",
        "notation_version": "1.0.0",
        "semantic_profile_id": "dynamic_hoare",
        "family_id": "program",
        "features": ("parse", "print"),
        "implementation": "ipfs_datasets_py.logic.parsers.program:ProgramLogicParser",
    },
    {
        "module": "resource",
        "descriptor_id": "parser:local:resource",
        "notation_id": "canonical_resource_logic",
        "notation_version": "1.0.0",
        "semantic_profile_id": "separation",
        "family_id": "separation_logic",
        "features": ("parse", "print"),
        "implementation": "ipfs_datasets_py.logic.parsers.resource:ResourceLogicParser",
    },
    {
        "module": "event_calculus",
        "descriptor_id": "parser:local:event-calculus",
        "notation_id": "canonical_event_calculus",
        "notation_version": "1.0.0",
        "semantic_profile_id": "event_calculus",
        "family_id": "event_calculus",
        "features": ("parse", "print"),
        "implementation": (
            "ipfs_datasets_py.logic.parsers.event_calculus:EventCalculusParser"
        ),
    },
    {
        "module": "legacy_modal",
        "descriptor_id": "parser:local:legacy-tdfol",
        "notation_id": "legacy_tdfol",
        "notation_version": "1.0.0",
        "semantic_profile_id": "tdfol_import",
        "family_id": "tdfol",
        "features": ("parse",),
        "implementation": (
            "ipfs_datasets_py.logic.parsers.legacy_modal:LegacyTDFOLImporter"
        ),
    },
    {
        "module": "legacy_modal",
        "descriptor_id": "parser:local:legacy-dcec",
        "notation_id": "legacy_dcec",
        "notation_version": "1.0.0",
        "semantic_profile_id": "dcec_import",
        "family_id": "dcec",
        "features": ("parse",),
        "implementation": (
            "ipfs_datasets_py.logic.parsers.legacy_modal:LegacyDCECImporter"
        ),
    },
)


@dataclass(frozen=True, slots=True)
class LocalParserContribution:
    """One inert local descriptor contribution from an individual parser module.

    Interface contribution shape for LFP-040.  Construction never loads the
    implementation named by ``implementation``.
    """

    module: str
    descriptor: LogicParserDescriptor

    def __post_init__(self) -> None:
        object.__setattr__(self, "module", _identifier(self.module, "module"))
        if self.module not in set(PARSER_CONTRIBUTION_MODULES):
            raise UnknownParserCatalogEntryError(
                f"unknown parser contribution module {self.module!r}"
            )
        if not isinstance(self.descriptor, LogicParserDescriptor):
            raise TypeError("descriptor must be a LogicParserDescriptor")
        metadata = self.descriptor.metadata
        if not isinstance(metadata, Mapping) or metadata.get("inert") is not True:
            raise EagerParserCatalogEntryError(
                f"descriptor {self.descriptor.descriptor_id!r} is not inert"
            )
        if metadata.get("lazy") is not True:
            raise EagerParserCatalogEntryError(
                f"descriptor {self.descriptor.descriptor_id!r} is not lazy"
            )
        if metadata.get("eager") is True:
            raise EagerParserCatalogEntryError(
                f"descriptor {self.descriptor.descriptor_id!r} is marked eager"
            )
        if metadata.get("factory_bound") is True or metadata.get("bound") is True:
            raise EagerParserCatalogEntryError(
                f"descriptor {self.descriptor.descriptor_id!r} binds a factory eagerly"
            )

    @property
    def descriptor_id(self) -> str:
        return self.descriptor.descriptor_id

    @property
    def family_id(self) -> str:
        return _family_value(self.descriptor.family_id)

    def to_dict(self) -> dict[str, Any]:
        return {
            "descriptor": self.descriptor.to_dict(),
            "module": self.module,
        }


def _build_contribution(spec: Mapping[str, Any]) -> LocalParserContribution:
    features = tuple(spec.get("features") or ())
    module = str(spec["module"])
    descriptor = LogicParserDescriptor(
        descriptor_id=str(spec["descriptor_id"]),
        key=ParserKey(
            notation_id=str(spec["notation_id"]),
            notation_version=str(spec["notation_version"]),
            semantic_profile_id=str(spec["semantic_profile_id"]),
        ),
        family_id=str(spec["family_id"]),
        features=features,
        implementation=str(spec["implementation"]),
        metadata={
            "contribution_module": module,
            "eager": False,
            "inert": True,
            "lazy": True,
            "publication": LOGIC_PARSER_CATALOG_INTERFACE,
            "shared_registry_mutated": False,
            "task_id": CATALOG_TASK_ID,
        },
    )
    return LocalParserContribution(module=module, descriptor=descriptor)


def collect_local_parser_contributions() -> tuple[LocalParserContribution, ...]:
    """Return inert local contributions without importing family modules."""

    items = [_build_contribution(spec) for spec in _LOCAL_PARSER_CONTRIBUTIONS]
    return tuple(sorted(items, key=lambda item: item.descriptor_id))


@dataclass(frozen=True, slots=True)
class LogicParserCatalog:
    """Sealed projection of inert local parser descriptors.

    Interface: ``LogicParserCatalog@1``.

    The catalog is a pure aggregation surface.  It never registers descriptors
    into a shared :class:`LogicParserRegistry` and never resolves
    implementation callables.
    """

    INTERFACE: ClassVar[str] = LOGIC_PARSER_CATALOG_INTERFACE

    contributions: tuple[LocalParserContribution, ...] = field(
        default_factory=collect_local_parser_contributions
    )
    schema_version: str = LOGIC_PARSER_CATALOG_SCHEMA_VERSION
    version: str = LOGIC_PARSER_CATALOG_VERSION
    task_id: str = CATALOG_TASK_ID
    goal_id: str = CATALOG_GOAL_ID

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )
        if self.schema_version != LOGIC_PARSER_CATALOG_SCHEMA_VERSION:
            raise ParserCatalogError(
                f"unsupported parser catalog schema: {self.schema_version!r}"
            )
        object.__setattr__(self, "version", _text(self.version, "version"))
        object.__setattr__(self, "task_id", _text(self.task_id, "task_id"))
        object.__setattr__(self, "goal_id", _text(self.goal_id, "goal_id"))

        if isinstance(self.contributions, (str, bytes, bytearray)) or not isinstance(
            self.contributions, Sequence
        ):
            raise ParserCatalogError("contributions must be a sequence")

        normalized: list[LocalParserContribution] = []
        for item in self.contributions:
            if isinstance(item, LocalParserContribution):
                normalized.append(item)
            elif isinstance(item, Mapping):
                descriptor_payload = item.get("descriptor")
                if not isinstance(descriptor_payload, Mapping):
                    raise ParserCatalogError(
                        "contribution.descriptor must be a mapping"
                    )
                normalized.append(
                    LocalParserContribution(
                        module=str(item.get("module") or ""),
                        descriptor=LogicParserDescriptor.from_dict(descriptor_payload),
                    )
                )
            else:
                raise ParserCatalogError(
                    "contributions must be LocalParserContribution values"
                )

        ordered = tuple(sorted(normalized, key=lambda item: item.descriptor_id))
        self._reject_duplicates(ordered)
        self._reject_unknown_families(ordered)
        object.__setattr__(self, "contributions", ordered)

    @staticmethod
    def _reject_duplicates(
        contributions: Sequence[LocalParserContribution],
    ) -> None:
        ids = [item.descriptor_id for item in contributions]
        if len(ids) != len(set(ids)):
            seen: set[str] = set()
            for descriptor_id in ids:
                if descriptor_id in seen:
                    raise DuplicateParserCatalogEntryError(
                        f"duplicate parser descriptor id {descriptor_id!r}"
                    )
                seen.add(descriptor_id)
        keys = [item.descriptor.key.as_tuple for item in contributions]
        if len(keys) != len(set(keys)):
            seen_keys: set[tuple[str, str, str]] = set()
            for key in keys:
                if key in seen_keys:
                    raise DuplicateParserCatalogEntryError(
                        f"duplicate parser key {key!r}"
                    )
                seen_keys.add(key)

    @staticmethod
    def _reject_unknown_families(
        contributions: Sequence[LocalParserContribution],
        *,
        registry: LogicFamilyRegistry | None = None,
    ) -> None:
        allowed = set(BASELINE_FAMILY_IDS)
        if registry is not None:
            allowed |= set(registry.families)
        else:
            allowed |= set(DEFAULT_REGISTRY.families)
        for item in contributions:
            family_id = item.family_id
            if family_id not in allowed:
                raise UnknownParserCatalogEntryError(
                    f"descriptor {item.descriptor_id!r} references unknown family "
                    f"{family_id!r}"
                )

    def __iter__(self) -> Iterator[LocalParserContribution]:
        return iter(self.contributions)

    def __len__(self) -> int:
        return len(self.contributions)

    def __contains__(self, descriptor_id: object) -> bool:
        if not isinstance(descriptor_id, str):
            return False
        return descriptor_id in self.descriptor_ids

    @property
    def descriptors(self) -> tuple[LogicParserDescriptor, ...]:
        return tuple(item.descriptor for item in self.contributions)

    @property
    def descriptor_ids(self) -> tuple[str, ...]:
        return tuple(item.descriptor_id for item in self.contributions)

    @property
    def modules(self) -> tuple[str, ...]:
        return tuple(sorted({item.module for item in self.contributions}))

    @property
    def by_id(self) -> Mapping[str, LogicParserDescriptor]:
        return MappingProxyType(
            {item.descriptor_id: item.descriptor for item in self.contributions}
        )

    @property
    def by_key(self) -> Mapping[tuple[str, str, str], LogicParserDescriptor]:
        return MappingProxyType(
            {item.descriptor.key.as_tuple: item.descriptor for item in self.contributions}
        )

    def get(self, descriptor_id: str) -> LogicParserDescriptor:
        try:
            return self.by_id[descriptor_id]
        except KeyError as error:
            raise UnknownParserCatalogEntryError(
                f"unknown parser descriptor {descriptor_id!r}"
            ) from error

    def is_inert(self) -> bool:
        """Return True when every contribution is publication-only."""

        return all(
            isinstance(item.descriptor.metadata, Mapping)
            and item.descriptor.metadata.get("inert") is True
            and item.descriptor.metadata.get("lazy") is True
            and item.descriptor.metadata.get("eager") is not True
            and item.descriptor.metadata.get("shared_registry_mutated") is not True
            for item in self.contributions
        )

    def is_eager(self) -> bool:
        """Return True when any contribution claims eager binding."""

        return not self.is_inert()

    def mutates_shared_registry(self) -> bool:
        """Catalog projection never mutates a shared registry."""

        return False

    def validate_closure(
        self,
        *,
        registry: LogicFamilyRegistry | None = None,
        required_modules: Sequence[str] | None = None,
    ) -> None:
        """Reject duplicate/eager/unknown entries and unexplained module gaps."""

        if not self.is_inert():
            raise EagerParserCatalogEntryError(
                "parser catalog contains eager or non-inert entries"
            )
        self._reject_duplicates(self.contributions)
        self._reject_unknown_families(self.contributions, registry=registry)
        expected_modules = (
            tuple(required_modules)
            if required_modules is not None
            else PARSER_CONTRIBUTION_MODULES
        )
        missing = sorted(set(expected_modules) - set(self.modules))
        if missing:
            raise UnknownParserCatalogEntryError(
                f"parser catalog missing contributions for modules: "
                f"{', '.join(missing)}"
            )
        unknown_modules = sorted(set(self.modules) - set(PARSER_CONTRIBUTION_MODULES))
        if unknown_modules:
            raise UnknownParserCatalogEntryError(
                f"parser catalog has unknown modules: {', '.join(unknown_modules)}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "contributions": [item.to_dict() for item in self.contributions],
            "descriptor_ids": list(self.descriptor_ids),
            "goal_id": self.goal_id,
            "interface": self.INTERFACE,
            "modules": list(self.modules),
            "mutates_shared_registry": self.mutates_shared_registry(),
            "schema_version": self.schema_version,
            "task_id": self.task_id,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "LogicParserCatalog":
        if not isinstance(value, Mapping):
            raise TypeError("parser catalog must be a mapping")
        interface = value.get("interface", LOGIC_PARSER_CATALOG_INTERFACE)
        if interface != LOGIC_PARSER_CATALOG_INTERFACE:
            raise ParserCatalogError(
                f"unknown parser catalog interface: {interface!r}"
            )
        return cls(
            contributions=tuple(value.get("contributions") or ()),
            schema_version=str(
                value.get("schema_version") or LOGIC_PARSER_CATALOG_SCHEMA_VERSION
            ),
            version=str(value.get("version") or LOGIC_PARSER_CATALOG_VERSION),
            task_id=str(value.get("task_id") or CATALOG_TASK_ID),
            goal_id=str(value.get("goal_id") or CATALOG_GOAL_ID),
        )


def build_parser_catalog(
    *,
    contributions: Iterable[LocalParserContribution] | None = None,
    validate: bool = True,
    registry: LogicFamilyRegistry | None = None,
) -> LogicParserCatalog:
    """Build the sealed LFP-040 parser catalog projection."""

    if contributions is None:
        catalog = LogicParserCatalog()
    else:
        catalog = LogicParserCatalog(contributions=tuple(contributions))
    if validate:
        catalog.validate_closure(registry=registry)
    return catalog


DEFAULT_PARSER_CATALOG: Final[LogicParserCatalog] = build_parser_catalog(validate=True)


__all__ = [
    "CATALOG_GOAL_ID",
    "CATALOG_TASK_ID",
    "DEFAULT_PARSER_CATALOG",
    "DuplicateParserCatalogEntryError",
    "EagerParserCatalogEntryError",
    "LOGIC_PARSER_CATALOG_INTERFACE",
    "LOGIC_PARSER_CATALOG_SCHEMA_VERSION",
    "LOGIC_PARSER_CATALOG_VERSION",
    "LOGIC_PARSER_DESCRIPTOR_INTERFACE",
    "LocalParserContribution",
    "LogicParserCatalog",
    "PARSER_CONTRIBUTION_MODULES",
    "ParserCatalogError",
    "UnknownParserCatalogEntryError",
    "build_parser_catalog",
    "collect_local_parser_contributions",
]
