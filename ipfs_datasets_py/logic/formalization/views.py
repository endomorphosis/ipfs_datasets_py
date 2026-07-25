"""Typed, domain-neutral formal views and their registry.

View identifiers are exact, versioned contracts.  This module deliberately
does not carry the historical aliases of any domain; adapters may add
compatibility mappings when those domains are integrated.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Final

from ipfs_datasets_py.logic.ir_core.claims import (
    FrozenJSON,
    FrozenMap,
    freeze_json,
    thaw_json,
)
from ipfs_datasets_py.logic.ir_core.identity import (
    CanonicalIdentity,
    canonical_identity,
)

from .samples import (
    FormalizationValidationError,
    _identifier,
    _mapping,
    _reject_unknown,
    _sequence,
    _text,
    _unique_identifiers,
)


FORMALIZATION_VIEW_SCHEMA_VERSION: Final = "formalization-view/v1"
FORMALIZATION_VIEW_REGISTRY_SCHEMA_VERSION: Final = (
    "formalization-view-registry/v1"
)
FORMAL_SYMBOL_TABLE_SCHEMA_VERSION: Final = "formal-symbol-table/v1"
FORMAL_FORMULA_SCHEMA_VERSION: Final = "formal-formula/v1"
FORMAL_CROSS_VIEW_LINK_SCHEMA_VERSION: Final = "formal-cross-view-link/v1"


class CrossViewRelation(str, Enum):
    """Declared semantic relationship between formulas in different views."""

    EQUIVALENT = "equivalent"
    LOWERS_TO = "lowers_to"
    REFINES = "refines"
    ABSTRACTS = "abstracts"
    PRESERVES = "preserves"
    CONTRADICTS = "contradicts"
    CORRESPONDS_TO = "corresponds_to"


@dataclass(frozen=True, slots=True)
class FormalizationView:
    """A registered output representation and its required capabilities."""

    view_id: str
    logic_family: str
    description: str = ""
    formula_schema: str = FORMAL_FORMULA_SCHEMA_VERSION
    capabilities: tuple[str, ...] = ()
    metadata: FrozenMap = field(default_factory=FrozenMap)
    schema_version: str = FORMALIZATION_VIEW_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "view_id", _identifier(self.view_id, "view_id"))
        object.__setattr__(
            self, "logic_family", _identifier(self.logic_family, "logic_family")
        )
        if not isinstance(self.description, str):
            raise FormalizationValidationError("description must be a string")
        object.__setattr__(
            self,
            "formula_schema",
            _identifier(self.formula_schema, "formula_schema"),
        )
        object.__setattr__(
            self,
            "capabilities",
            _unique_identifiers(self.capabilities, "capabilities"),
        )
        object.__setattr__(
            self,
            "metadata",
            self.metadata
            if isinstance(self.metadata, FrozenMap)
            else FrozenMap(_mapping(self.metadata, "metadata")),
        )
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )
        if self.schema_version != FORMALIZATION_VIEW_SCHEMA_VERSION:
            raise FormalizationValidationError(
                f"unsupported formalization view schema: {self.schema_version!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "capabilities": list(self.capabilities),
            "description": self.description,
            "formula_schema": self.formula_schema,
            "logic_family": self.logic_family,
            "metadata": self.metadata.to_dict(),
            "schema_version": self.schema_version,
            "view_id": self.view_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "FormalizationView":
        value = _mapping(value, "formalization view")
        _reject_unknown(
            value,
            frozenset(
                {
                    "capabilities",
                    "description",
                    "formula_schema",
                    "logic_family",
                    "metadata",
                    "schema_version",
                    "view_id",
                }
            ),
            "formalization view",
        )
        return cls(
            view_id=value.get("view_id", ""),
            logic_family=value.get("logic_family", ""),
            description=value.get("description", ""),
            formula_schema=value.get(
                "formula_schema", FORMAL_FORMULA_SCHEMA_VERSION
            ),
            capabilities=tuple(
                _sequence(value.get("capabilities", ()), "capabilities")
            ),
            metadata=FrozenMap(_mapping(value.get("metadata", {}), "metadata")),
            schema_version=value.get(
                "schema_version", FORMALIZATION_VIEW_SCHEMA_VERSION
            ),
        )


class ViewRegistry(Mapping[str, FormalizationView]):
    """Immutable registry with exact-ID resolution and stable identity."""

    __slots__ = ("_ordered", "_by_id", "registry_id", "schema_version")

    def __init__(
        self,
        views: Sequence[FormalizationView],
        *,
        registry_id: str = "formalization-views",
        schema_version: str = FORMALIZATION_VIEW_REGISTRY_SCHEMA_VERSION,
    ) -> None:
        if isinstance(views, (str, bytes, bytearray)):
            raise FormalizationValidationError("views must be a sequence")
        self.registry_id = _identifier(registry_id, "registry_id")
        self.schema_version = _text(schema_version, "schema_version")
        if self.schema_version != FORMALIZATION_VIEW_REGISTRY_SCHEMA_VERSION:
            raise FormalizationValidationError(
                f"unsupported view registry schema: {self.schema_version!r}"
            )
        normalized = tuple(
            item
            if isinstance(item, FormalizationView)
            else FormalizationView.from_dict(_mapping(item, "view"))
            for item in views
        )
        if not normalized:
            raise FormalizationValidationError(
                "view registry must contain at least one view"
            )
        by_id = {item.view_id: item for item in normalized}
        if len(by_id) != len(normalized):
            raise FormalizationValidationError("view IDs must be unique")
        self._ordered = tuple(sorted(normalized, key=lambda item: item.view_id))
        self._by_id = MappingProxyType(by_id)

    def __getitem__(self, view_id: str) -> FormalizationView:
        try:
            return self._by_id[view_id]
        except KeyError:
            raise KeyError(view_id) from None

    def __iter__(self) -> Iterator[str]:
        return (item.view_id for item in self._ordered)

    def __len__(self) -> int:
        return len(self._ordered)

    def resolve(self, view_id: str) -> FormalizationView:
        """Resolve one exact canonical view ID."""

        return self[view_id]

    @property
    def views(self) -> tuple[FormalizationView, ...]:
        return self._ordered

    @property
    def view_ids(self) -> tuple[str, ...]:
        return tuple(item.view_id for item in self._ordered)

    def to_dict(self) -> dict[str, Any]:
        return {
            "registry_id": self.registry_id,
            "schema_version": self.schema_version,
            "views": [item.to_dict() for item in self._ordered],
        }

    def manifest(self) -> dict[str, Any]:
        result = self.to_dict()
        result["registry_identity"] = self.identity.to_dict()
        result["view_count"] = len(self)
        result["view_ids"] = list(self.view_ids)
        return result

    def to_json(self) -> str:
        return canonical_view_registry_json(self)

    @property
    def identity(self) -> CanonicalIdentity:
        return canonical_identity(
            self.to_dict(),
            domain="formalization-view-registry",
            schema_version=self.schema_version,
            collection_semantics={
                "/views": "set-like",
                "/views/*/capabilities": "set-like",
            },
        )

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ViewRegistry":
        value = _mapping(value, "view registry")
        _reject_unknown(
            value,
            frozenset({"registry_id", "schema_version", "views"}),
            "view registry",
        )
        return cls(
            tuple(
                FormalizationView.from_dict(_mapping(item, "view"))
                for item in _sequence(value.get("views", ()), "views")
            ),
            registry_id=value.get("registry_id", ""),
            schema_version=value.get(
                "schema_version", FORMALIZATION_VIEW_REGISTRY_SCHEMA_VERSION
            ),
        )

    @classmethod
    def from_json(cls, value: str | bytes | bytearray) -> "ViewRegistry":
        try:
            decoded = json.loads(value)
        except (TypeError, ValueError, UnicodeDecodeError) as exc:
            raise FormalizationValidationError(
                "view registry must be valid JSON"
            ) from exc
        return cls.from_dict(_mapping(decoded, "view registry"))


@dataclass(frozen=True, slots=True)
class FormalSymbol:
    """One typed symbol used by emitted formulas."""

    symbol_id: str
    name: str
    kind: str
    sort: str = "untyped"
    source_ref_ids: tuple[str, ...] = ()
    span_ids: tuple[str, ...] = ()
    metadata: FrozenMap = field(default_factory=FrozenMap)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "symbol_id", _identifier(self.symbol_id, "symbol_id")
        )
        object.__setattr__(self, "name", _text(self.name, "symbol name"))
        object.__setattr__(self, "kind", _identifier(self.kind, "symbol kind"))
        object.__setattr__(self, "sort", _identifier(self.sort, "symbol sort"))
        object.__setattr__(
            self,
            "source_ref_ids",
            _unique_identifiers(self.source_ref_ids, "source_ref_ids"),
        )
        object.__setattr__(
            self, "span_ids", _unique_identifiers(self.span_ids, "span_ids")
        )
        if not self.source_ref_ids and not self.span_ids:
            raise FormalizationValidationError(
                f"symbol {self.symbol_id!r} must be source-grounded"
            )
        object.__setattr__(
            self,
            "metadata",
            self.metadata
            if isinstance(self.metadata, FrozenMap)
            else FrozenMap(_mapping(self.metadata, "metadata")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "metadata": self.metadata.to_dict(),
            "name": self.name,
            "sort": self.sort,
            "source_ref_ids": list(self.source_ref_ids),
            "span_ids": list(self.span_ids),
            "symbol_id": self.symbol_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "FormalSymbol":
        value = _mapping(value, "formal symbol")
        _reject_unknown(
            value,
            frozenset(
                {
                    "kind",
                    "metadata",
                    "name",
                    "sort",
                    "source_ref_ids",
                    "span_ids",
                    "symbol_id",
                }
            ),
            "formal symbol",
        )
        return cls(
            symbol_id=value.get("symbol_id", ""),
            name=value.get("name", ""),
            kind=value.get("kind", ""),
            sort=value.get("sort", "untyped"),
            source_ref_ids=tuple(
                _sequence(value.get("source_ref_ids", ()), "source_ref_ids")
            ),
            span_ids=tuple(_sequence(value.get("span_ids", ()), "span_ids")),
            metadata=FrozenMap(_mapping(value.get("metadata", {}), "metadata")),
        )


@dataclass(frozen=True, slots=True)
class SymbolTable:
    """Deterministically ordered collection of grounded formal symbols."""

    table_id: str
    symbols: tuple[FormalSymbol, ...]
    metadata: FrozenMap = field(default_factory=FrozenMap)
    schema_version: str = FORMAL_SYMBOL_TABLE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "table_id", _identifier(self.table_id, "table_id"))
        normalized = tuple(
            item
            if isinstance(item, FormalSymbol)
            else FormalSymbol.from_dict(_mapping(item, "symbol"))
            for item in self.symbols
        )
        identifiers = [item.symbol_id for item in normalized]
        if len(identifiers) != len(set(identifiers)):
            raise FormalizationValidationError("symbol IDs must be unique")
        object.__setattr__(
            self, "symbols", tuple(sorted(normalized, key=lambda item: item.symbol_id))
        )
        object.__setattr__(
            self,
            "metadata",
            self.metadata
            if isinstance(self.metadata, FrozenMap)
            else FrozenMap(_mapping(self.metadata, "metadata")),
        )
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )
        if self.schema_version != FORMAL_SYMBOL_TABLE_SCHEMA_VERSION:
            raise FormalizationValidationError(
                f"unsupported symbol table schema: {self.schema_version!r}"
            )

    def __getitem__(self, symbol_id: str) -> FormalSymbol:
        for symbol in self.symbols:
            if symbol.symbol_id == symbol_id:
                return symbol
        raise KeyError(symbol_id)

    @property
    def symbol_ids(self) -> tuple[str, ...]:
        return tuple(item.symbol_id for item in self.symbols)

    def to_dict(self) -> dict[str, Any]:
        return {
            "metadata": self.metadata.to_dict(),
            "schema_version": self.schema_version,
            "symbols": [item.to_dict() for item in self.symbols],
            "table_id": self.table_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SymbolTable":
        value = _mapping(value, "symbol table")
        _reject_unknown(
            value,
            frozenset({"metadata", "schema_version", "symbols", "table_id"}),
            "symbol table",
        )
        return cls(
            table_id=value.get("table_id", ""),
            symbols=tuple(
                FormalSymbol.from_dict(_mapping(item, "symbol"))
                for item in _sequence(value.get("symbols", ()), "symbols")
            ),
            metadata=FrozenMap(_mapping(value.get("metadata", {}), "metadata")),
            schema_version=value.get(
                "schema_version", FORMAL_SYMBOL_TABLE_SCHEMA_VERSION
            ),
        )


@dataclass(frozen=True, slots=True)
class FormalFormula:
    """One source-grounded formula in a registered formal view."""

    formula_id: str
    view_id: str
    expression: FrozenJSON
    symbol_ids: tuple[str, ...] = ()
    source_ref_ids: tuple[str, ...] = ()
    span_ids: tuple[str, ...] = ()
    assumption_ids: tuple[str, ...] = ()
    input_node_ids: tuple[str, ...] = ()
    opaque: bool = False
    metadata: FrozenMap = field(default_factory=FrozenMap)
    schema_version: str = FORMAL_FORMULA_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "formula_id", _identifier(self.formula_id, "formula_id")
        )
        object.__setattr__(self, "view_id", _identifier(self.view_id, "view_id"))
        expression = freeze_json(self.expression)
        if expression is None or (isinstance(expression, str) and not expression.strip()):
            raise FormalizationValidationError("formula expression must not be empty")
        object.__setattr__(self, "expression", expression)
        for name in (
            "symbol_ids",
            "source_ref_ids",
            "span_ids",
            "assumption_ids",
            "input_node_ids",
        ):
            object.__setattr__(
                self,
                name,
                _unique_identifiers(getattr(self, name), name),
            )
        if not self.source_ref_ids and not self.span_ids:
            raise FormalizationValidationError(
                f"formula {self.formula_id!r} must be source-grounded"
            )
        if not isinstance(self.opaque, bool):
            raise FormalizationValidationError("opaque must be a boolean")
        object.__setattr__(
            self,
            "metadata",
            self.metadata
            if isinstance(self.metadata, FrozenMap)
            else FrozenMap(_mapping(self.metadata, "metadata")),
        )
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )
        if self.schema_version != FORMAL_FORMULA_SCHEMA_VERSION:
            raise FormalizationValidationError(
                f"unsupported formula schema: {self.schema_version!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "assumption_ids": list(self.assumption_ids),
            "expression": thaw_json(self.expression),
            "formula_id": self.formula_id,
            "input_node_ids": list(self.input_node_ids),
            "metadata": self.metadata.to_dict(),
            "opaque": self.opaque,
            "schema_version": self.schema_version,
            "source_ref_ids": list(self.source_ref_ids),
            "span_ids": list(self.span_ids),
            "symbol_ids": list(self.symbol_ids),
            "view_id": self.view_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "FormalFormula":
        value = _mapping(value, "formal formula")
        _reject_unknown(
            value,
            frozenset(
                {
                    "assumption_ids",
                    "expression",
                    "formula_id",
                    "input_node_ids",
                    "metadata",
                    "opaque",
                    "schema_version",
                    "source_ref_ids",
                    "span_ids",
                    "symbol_ids",
                    "view_id",
                }
            ),
            "formal formula",
        )
        return cls(
            formula_id=value.get("formula_id", ""),
            view_id=value.get("view_id", ""),
            expression=value.get("expression"),
            symbol_ids=tuple(
                _sequence(value.get("symbol_ids", ()), "symbol_ids")
            ),
            source_ref_ids=tuple(
                _sequence(value.get("source_ref_ids", ()), "source_ref_ids")
            ),
            span_ids=tuple(_sequence(value.get("span_ids", ()), "span_ids")),
            assumption_ids=tuple(
                _sequence(value.get("assumption_ids", ()), "assumption_ids")
            ),
            input_node_ids=tuple(
                _sequence(value.get("input_node_ids", ()), "input_node_ids")
            ),
            opaque=value.get("opaque", False),
            metadata=FrozenMap(_mapping(value.get("metadata", {}), "metadata")),
            schema_version=value.get("schema_version", FORMAL_FORMULA_SCHEMA_VERSION),
        )


@dataclass(frozen=True, slots=True)
class CrossViewLink:
    """A typed semantic link between two emitted formulas."""

    link_id: str
    source_formula_id: str
    target_formula_id: str
    relation: CrossViewRelation
    preserved_properties: tuple[str, ...] = ()
    source_ref_ids: tuple[str, ...] = ()
    span_ids: tuple[str, ...] = ()
    metadata: FrozenMap = field(default_factory=FrozenMap)
    schema_version: str = FORMAL_CROSS_VIEW_LINK_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "link_id", _identifier(self.link_id, "link_id"))
        object.__setattr__(
            self,
            "source_formula_id",
            _identifier(self.source_formula_id, "source_formula_id"),
        )
        object.__setattr__(
            self,
            "target_formula_id",
            _identifier(self.target_formula_id, "target_formula_id"),
        )
        if self.source_formula_id == self.target_formula_id:
            raise FormalizationValidationError(
                "cross-view link endpoints must be different formulas"
            )
        try:
            relation = (
                self.relation
                if isinstance(self.relation, CrossViewRelation)
                else CrossViewRelation(self.relation)
            )
        except (TypeError, ValueError) as exc:
            raise FormalizationValidationError(
                f"unknown cross-view relation: {self.relation!r}"
            ) from exc
        object.__setattr__(self, "relation", relation)
        object.__setattr__(
            self,
            "preserved_properties",
            _unique_identifiers(
                self.preserved_properties, "preserved_properties"
            ),
        )
        object.__setattr__(
            self,
            "source_ref_ids",
            _unique_identifiers(self.source_ref_ids, "source_ref_ids"),
        )
        object.__setattr__(
            self, "span_ids", _unique_identifiers(self.span_ids, "span_ids")
        )
        object.__setattr__(
            self,
            "metadata",
            self.metadata
            if isinstance(self.metadata, FrozenMap)
            else FrozenMap(_mapping(self.metadata, "metadata")),
        )
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )
        if self.schema_version != FORMAL_CROSS_VIEW_LINK_SCHEMA_VERSION:
            raise FormalizationValidationError(
                f"unsupported cross-view link schema: {self.schema_version!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "link_id": self.link_id,
            "metadata": self.metadata.to_dict(),
            "preserved_properties": list(self.preserved_properties),
            "relation": self.relation.value,
            "schema_version": self.schema_version,
            "source_formula_id": self.source_formula_id,
            "source_ref_ids": list(self.source_ref_ids),
            "span_ids": list(self.span_ids),
            "target_formula_id": self.target_formula_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CrossViewLink":
        value = _mapping(value, "cross-view link")
        _reject_unknown(
            value,
            frozenset(
                {
                    "link_id",
                    "metadata",
                    "preserved_properties",
                    "relation",
                    "schema_version",
                    "source_formula_id",
                    "source_ref_ids",
                    "span_ids",
                    "target_formula_id",
                }
            ),
            "cross-view link",
        )
        return cls(
            link_id=value.get("link_id", ""),
            source_formula_id=value.get("source_formula_id", ""),
            target_formula_id=value.get("target_formula_id", ""),
            relation=value.get("relation", ""),
            preserved_properties=tuple(
                _sequence(
                    value.get("preserved_properties", ()), "preserved_properties"
                )
            ),
            source_ref_ids=tuple(
                _sequence(value.get("source_ref_ids", ()), "source_ref_ids")
            ),
            span_ids=tuple(_sequence(value.get("span_ids", ()), "span_ids")),
            metadata=FrozenMap(_mapping(value.get("metadata", {}), "metadata")),
            schema_version=value.get(
                "schema_version", FORMAL_CROSS_VIEW_LINK_SCHEMA_VERSION
            ),
        )


def validate_view_artifacts(
    *,
    registry: ViewRegistry,
    symbol_table: SymbolTable,
    formulas: Sequence[FormalFormula],
    links: Sequence[CrossViewLink] = (),
    source_ref_ids: Sequence[str] = (),
    span_ids: Sequence[str] = (),
    assumption_ids: Sequence[str] = (),
) -> None:
    """Validate registry, symbol, formula, link, source, and assumption closure."""

    formula_ids = [item.formula_id for item in formulas]
    if len(formula_ids) != len(set(formula_ids)):
        raise FormalizationValidationError("formula IDs must be unique")
    link_ids = [item.link_id for item in links]
    if len(link_ids) != len(set(link_ids)):
        raise FormalizationValidationError("cross-view link IDs must be unique")
    symbols = set(symbol_table.symbol_ids)
    formula_by_id = {item.formula_id: item for item in formulas}
    known_sources = set(source_ref_ids)
    known_spans = set(span_ids)
    known_assumptions = set(assumption_ids)

    for item in symbol_table.symbols:
        _require_known(item.source_ref_ids, known_sources, f"symbol {item.symbol_id}")
        _require_known(item.span_ids, known_spans, f"symbol {item.symbol_id} spans")
    for formula in formulas:
        if formula.view_id not in registry:
            raise FormalizationValidationError(
                f"formula {formula.formula_id!r} references unknown view "
                f"{formula.view_id!r}"
            )
        _require_known(
            formula.symbol_ids, symbols, f"formula {formula.formula_id} symbols"
        )
        _require_known(
            formula.source_ref_ids,
            known_sources,
            f"formula {formula.formula_id} sources",
        )
        _require_known(
            formula.span_ids, known_spans, f"formula {formula.formula_id} spans"
        )
        _require_known(
            formula.assumption_ids,
            known_assumptions,
            f"formula {formula.formula_id} assumptions",
        )
    for link in links:
        _require_known(
            (link.source_formula_id, link.target_formula_id),
            set(formula_by_id),
            f"cross-view link {link.link_id} formulas",
        )
        source_view = formula_by_id[link.source_formula_id].view_id
        target_view = formula_by_id[link.target_formula_id].view_id
        if source_view == target_view:
            raise FormalizationValidationError(
                f"cross-view link {link.link_id!r} endpoints use the same view"
            )
        _require_known(
            link.source_ref_ids,
            known_sources,
            f"cross-view link {link.link_id} sources",
        )
        _require_known(
            link.span_ids, known_spans, f"cross-view link {link.link_id} spans"
        )


def _require_known(
    values: Sequence[str], known: set[str], field_name: str
) -> None:
    unknown = set(values) - known
    if unknown:
        raise FormalizationValidationError(
            f"{field_name} references unknown identifiers: "
            + ", ".join(sorted(unknown))
        )


def canonical_view_registry_json(registry: ViewRegistry) -> str:
    return json.dumps(
        registry.to_dict(),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    )


__all__ = [
    "FORMALIZATION_VIEW_SCHEMA_VERSION",
    "FORMALIZATION_VIEW_REGISTRY_SCHEMA_VERSION",
    "FORMAL_SYMBOL_TABLE_SCHEMA_VERSION",
    "FORMAL_FORMULA_SCHEMA_VERSION",
    "FORMAL_CROSS_VIEW_LINK_SCHEMA_VERSION",
    "CrossViewLink",
    "CrossViewRelation",
    "FormalFormula",
    "FormalSymbol",
    "FormalizationView",
    "SymbolTable",
    "ViewRegistry",
    "canonical_view_registry_json",
    "validate_view_artifacts",
]
