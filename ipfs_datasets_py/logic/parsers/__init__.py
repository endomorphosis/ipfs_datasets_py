"""Lazy parser publication surface (``LazyParserPublication@1``).

Family frontends (FOL, SMT-LIB2, TPTP, rules, F-logic, …) register later.
This package publishes **inert local descriptors** only: notation/profile keys
and metadata that never load a parser implementation, installer, network
client, subprocess, or model at import time.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, ClassVar, Final, Iterator

from ipfs_datasets_py.logic.syntax_core.registry import (
    LOGIC_PARSER_DESCRIPTOR_INTERFACE,
    LogicParserDescriptor,
    ParserKey,
)


LAZY_PARSER_PUBLICATION_INTERFACE: Final = "LazyParserPublication@1"
LAZY_PARSER_PUBLICATION_SCHEMA_VERSION: Final = "lazy-parser-publication/v1"
PARSERS_PACKAGE_VERSION: Final = "1.0.0"

# Planned notation slots.  Descriptors are local and inert: no factory, no
# implementation import path that executes family code at publication time.
_LOCAL_DESCRIPTOR_SPECS: Final[tuple[dict[str, Any], ...]] = (
    {
        "descriptor_id": "parser:local:canonical-fol",
        "notation_id": "canonical_fol",
        "notation_version": "1.0.0",
        "semantic_profile_id": "classical",
        "family_id": "first_order",
        "features": ("parse", "print", "elaborate"),
        "implementation": "ipfs_datasets_py.logic.parsers.fol:CanonicalFOLParser",
    },
    {
        "descriptor_id": "parser:local:smtlib2",
        "notation_id": "smtlib2",
        "notation_version": "2.6.0",
        "semantic_profile_id": "smt_core",
        "family_id": "first_order",
        "features": ("parse", "print"),
        "implementation": "ipfs_datasets_py.logic.parsers.smtlib:SMTLIB2Parser",
    },
    {
        "descriptor_id": "parser:local:tptp",
        "notation_id": "tptp",
        "notation_version": "7.0.0",
        "semantic_profile_id": "fof",
        "family_id": "first_order",
        "features": ("parse", "print"),
        "implementation": "ipfs_datasets_py.logic.parsers.tptp:TPTPParser",
    },
    {
        "descriptor_id": "parser:local:rules",
        "notation_id": "datalog_rules",
        "notation_version": "1.0.0",
        "semantic_profile_id": "horn",
        "family_id": "datalog",
        "features": ("parse", "print"),
        "implementation": "ipfs_datasets_py.logic.parsers.rules:RuleParser",
    },
    {
        "descriptor_id": "parser:local:flogic",
        "notation_id": "flogic",
        "notation_version": "1.0.0",
        "semantic_profile_id": "frame_core",
        "family_id": "frame_logic",
        "features": ("parse", "print"),
        "implementation": "ipfs_datasets_py.logic.parsers.flogic:FLogicParser",
    },
)


def _build_local_descriptors() -> tuple[LogicParserDescriptor, ...]:
    """Construct inert local descriptors without importing family modules."""

    items: list[LogicParserDescriptor] = []
    for spec in _LOCAL_DESCRIPTOR_SPECS:
        items.append(
            LogicParserDescriptor(
                descriptor_id=str(spec["descriptor_id"]),
                key=ParserKey(
                    notation_id=str(spec["notation_id"]),
                    notation_version=str(spec["notation_version"]),
                    semantic_profile_id=str(spec["semantic_profile_id"]),
                ),
                family_id=str(spec["family_id"]),
                features=tuple(spec["features"]),
                # implementation is a dotted path label only; never imported here
                implementation=str(spec["implementation"]),
                metadata={
                    "inert": True,
                    "lazy": True,
                    "publication": LAZY_PARSER_PUBLICATION_INTERFACE,
                },
            )
        )
    return tuple(sorted(items, key=lambda item: item.descriptor_id))


@dataclass(frozen=True, slots=True)
class LazyParserPublication:
    """Immutable catalog of inert local parser descriptors.

    Interface: ``LazyParserPublication@1``.

    Accessing descriptors never resolves implementation callables.  Family
    modules remain unloaded until an explicit later registration binds a
    factory into a :class:`~ipfs_datasets_py.logic.syntax_core.registry.LogicParserRegistry`.
    """

    INTERFACE: ClassVar[str] = LAZY_PARSER_PUBLICATION_INTERFACE

    publication_id: str = "parsers:local"
    descriptors: tuple[LogicParserDescriptor, ...] = field(
        default_factory=_build_local_descriptors
    )
    schema_version: str = LAZY_PARSER_PUBLICATION_SCHEMA_VERSION
    package_version: str = PARSERS_PACKAGE_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.publication_id, str) or not self.publication_id.strip():
            raise ValueError("publication_id must be a non-empty string")
        normalized = tuple(
            item
            if isinstance(item, LogicParserDescriptor)
            else LogicParserDescriptor.from_dict(item)  # type: ignore[arg-type]
            for item in self.descriptors
        )
        ids = [item.descriptor_id for item in normalized]
        if len(ids) != len(set(ids)):
            raise ValueError("lazy parser descriptor IDs must be unique")
        object.__setattr__(
            self,
            "descriptors",
            tuple(sorted(normalized, key=lambda item: item.descriptor_id)),
        )
        if self.schema_version != LAZY_PARSER_PUBLICATION_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported lazy parser publication schema: {self.schema_version!r}"
            )

    def __iter__(self) -> Iterator[LogicParserDescriptor]:
        return iter(self.descriptors)

    def __len__(self) -> int:
        return len(self.descriptors)

    def __getitem__(self, descriptor_id: str) -> LogicParserDescriptor:
        for item in self.descriptors:
            if item.descriptor_id == descriptor_id:
                return item
        raise KeyError(descriptor_id)

    @property
    def descriptor_ids(self) -> tuple[str, ...]:
        return tuple(item.descriptor_id for item in self.descriptors)

    @property
    def by_key(self) -> Mapping[tuple[str, str, str], LogicParserDescriptor]:
        return MappingProxyType(
            {item.key.as_tuple: item for item in self.descriptors}
        )

    def is_inert(self) -> bool:
        """Return True when every descriptor is publication-only (no factory)."""

        return all(
            isinstance(item.metadata, Mapping)
            and item.metadata.get("inert") is True
            for item in self.descriptors
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "descriptors": [item.to_dict() for item in self.descriptors],
            "interface": self.INTERFACE,
            "package_version": self.package_version,
            "publication_id": self.publication_id,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "LazyParserPublication":
        if not isinstance(value, Mapping):
            raise TypeError("lazy parser publication must be a mapping")
        interface = value.get("interface", LAZY_PARSER_PUBLICATION_INTERFACE)
        if interface != LAZY_PARSER_PUBLICATION_INTERFACE:
            raise ValueError(
                f"unknown lazy parser publication interface: {interface!r}"
            )
        raw = value.get("descriptors", ())
        if isinstance(raw, (str, bytes, bytearray)) or not isinstance(
            raw, Sequence
        ):
            raise TypeError("descriptors must be a sequence")
        return cls(
            publication_id=str(value.get("publication_id") or "parsers:local"),
            descriptors=tuple(
                LogicParserDescriptor.from_dict(item)
                if isinstance(item, Mapping)
                else item
                for item in raw
            ),
            schema_version=str(
                value.get("schema_version")
                or LAZY_PARSER_PUBLICATION_SCHEMA_VERSION
            ),
            package_version=str(
                value.get("package_version") or PARSERS_PACKAGE_VERSION
            ),
        )


DEFAULT_LAZY_PARSER_PUBLICATION: Final = LazyParserPublication()


def local_parser_descriptors() -> tuple[LogicParserDescriptor, ...]:
    """Return the inert local descriptor catalog (no implementation load)."""

    return DEFAULT_LAZY_PARSER_PUBLICATION.descriptors


def publish_lazy_parser_catalog() -> LazyParserPublication:
    """Return the default lazy publication receipt."""

    return DEFAULT_LAZY_PARSER_PUBLICATION


__all__ = [
    "DEFAULT_LAZY_PARSER_PUBLICATION",
    "LAZY_PARSER_PUBLICATION_INTERFACE",
    "LAZY_PARSER_PUBLICATION_SCHEMA_VERSION",
    "LOGIC_PARSER_DESCRIPTOR_INTERFACE",
    "PARSERS_PACKAGE_VERSION",
    "LazyParserPublication",
    "local_parser_descriptors",
    "publish_lazy_parser_catalog",
]
