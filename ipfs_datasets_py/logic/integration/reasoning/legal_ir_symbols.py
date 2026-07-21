"""Scoped LegalIR symbol tables and definition resolution.

LegalIR lowering needs stable identifiers for legal concepts while preserving
the legal source that introduced them.  This module keeps that contract
explicit: definitions, aliases, and references are scoped; every resolution is
recorded; and unresolved or ambiguous references are diagnostics instead of
implicit guesses.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Final

from .legal_ir_source_maps import (
    LegalIRFactTrace,
    LegalIRProvenanceSpan,
    LegalIRSourceMap,
    LegalIRSourceMapIssue,
    LegalIRSourceMapTransform,
    trace_legal_ir_fact,
)


LEGAL_IR_SYMBOL_TABLE_SCHEMA_VERSION: Final = "legal-ir-symbol-table-v1"

_WORD_RE = re.compile(r"[A-Za-z0-9]+")


class LegalIRScopeKind(str, Enum):
    """Symbol resolution scope categories ordered by containment."""

    GLOBAL = "global"
    DOCUMENT = "document"
    SECTION = "section"
    SUBSECTION = "subsection"
    FORMULA = "formula"
    CLAUSE = "clause"


class LegalIRSymbolKind(str, Enum):
    """Typed legal symbols that downstream compilers must not conflate."""

    DEFINED_TERM = "defined_term"
    ACTOR = "actor"
    AUTHORITY = "authority"
    EXCEPTION = "exception"
    CONDITION = "condition"
    DOCUMENT = "document"
    SECTION = "section"
    FORMULA = "formula"
    RULE = "rule"
    UNKNOWN = "unknown"


class LegalIRResolutionStatus(str, Enum):
    """Deterministic outcome for one reference."""

    RESOLVED = "resolved"
    UNRESOLVED = "unresolved"
    AMBIGUOUS = "ambiguous"


class LegalIRSymbolDiagnosticType(str, Enum):
    """Typed symbol-table diagnostics emitted by resolution and validation."""

    UNRESOLVED_SYMBOL = "unresolved_symbol"
    AMBIGUOUS_SYMBOL = "ambiguous_symbol"
    ALIAS_TARGET_UNRESOLVED = "alias_target_unresolved"
    ALIAS_CYCLE = "alias_cycle"
    DUPLICATE_SYMBOL_ID = "duplicate_symbol_id"
    DUPLICATE_SCOPE_ID = "duplicate_scope_id"
    DUPLICATE_REFERENCE_ID = "duplicate_reference_id"
    SCOPE_MISSING = "scope_missing"
    SCOPE_PARENT_MISSING = "scope_parent_missing"
    SYMBOL_SCOPE_MISSING = "symbol_scope_missing"
    REFERENCE_SCOPE_MISSING = "reference_scope_missing"
    SOURCE_PROVENANCE_MISSING = "source_provenance_missing"
    SOURCE_PROVENANCE_UNTRACEABLE = "source_provenance_untraceable"
    RESOLUTION_TARGET_MISSING = "resolution_target_missing"
    RESOLUTION_DIAGNOSTIC_MISSING = "resolution_diagnostic_missing"


@dataclass(frozen=True)
class LegalIRSymbolScope:
    """One lexical/legal scope in which definitions may shadow parents."""

    scope_id: str
    scope_kind: LegalIRScopeKind
    parent_scope_id: str = ""
    document_id: str = ""
    citation: str = ""
    source_node_ids: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "citation": self.citation,
            "document_id": self.document_id,
            "metadata": _canonical_json_value(self.metadata),
            "parent_scope_id": self.parent_scope_id,
            "scope_id": self.scope_id,
            "scope_kind": self.scope_kind.value,
            "source_node_ids": list(self.source_node_ids),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "LegalIRSymbolScope":
        return cls(
            scope_id=str(data.get("scope_id") or ""),
            scope_kind=_scope_kind(data.get("scope_kind")),
            parent_scope_id=str(data.get("parent_scope_id") or ""),
            document_id=str(data.get("document_id") or ""),
            citation=str(data.get("citation") or ""),
            source_node_ids=tuple(_unique(_strings(data.get("source_node_ids", ())))),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass(frozen=True)
class LegalIRSymbolDefinition:
    """A legal symbol introduced in a specific scope."""

    symbol_id: str
    name: str
    symbol_kind: LegalIRSymbolKind
    scope_id: str
    document_id: str = ""
    normalized_name: str = ""
    source_node_ids: tuple[str, ...] = ()
    span_ids: tuple[str, ...] = ()
    aliases: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def key(self) -> tuple[str, LegalIRSymbolKind]:
        return (self.normalized_name or normalize_legal_symbol_name(self.name), self.symbol_kind)

    def to_dict(self) -> dict[str, Any]:
        return {
            "aliases": list(self.aliases),
            "document_id": self.document_id,
            "metadata": _canonical_json_value(self.metadata),
            "name": self.name,
            "normalized_name": self.normalized_name or normalize_legal_symbol_name(self.name),
            "scope_id": self.scope_id,
            "source_node_ids": list(self.source_node_ids),
            "span_ids": list(self.span_ids),
            "symbol_id": self.symbol_id,
            "symbol_kind": self.symbol_kind.value,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "LegalIRSymbolDefinition":
        return cls(
            symbol_id=str(data.get("symbol_id") or ""),
            name=str(data.get("name") or data.get("term") or ""),
            symbol_kind=_symbol_kind(data.get("symbol_kind") or data.get("kind")),
            scope_id=str(data.get("scope_id") or ""),
            document_id=str(data.get("document_id") or ""),
            normalized_name=str(data.get("normalized_name") or ""),
            source_node_ids=tuple(_unique(_strings(data.get("source_node_ids", ())))),
            span_ids=tuple(_unique(_strings(data.get("span_ids", ())))),
            aliases=tuple(_unique(normalize_legal_symbol_name(item) for item in _strings(data.get("aliases", ())))),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass(frozen=True)
class LegalIRSymbolAlias:
    """A scoped alternate name for another symbol or definition name."""

    alias_id: str
    alias: str
    scope_id: str
    symbol_kind: LegalIRSymbolKind = LegalIRSymbolKind.UNKNOWN
    normalized_alias: str = ""
    target_symbol_id: str = ""
    target_name: str = ""
    target_document_id: str = ""
    target_scope_id: str = ""
    document_id: str = ""
    source_node_ids: tuple[str, ...] = ()
    span_ids: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "alias": self.alias,
            "alias_id": self.alias_id,
            "document_id": self.document_id,
            "metadata": _canonical_json_value(self.metadata),
            "normalized_alias": self.normalized_alias or normalize_legal_symbol_name(self.alias),
            "scope_id": self.scope_id,
            "source_node_ids": list(self.source_node_ids),
            "span_ids": list(self.span_ids),
            "symbol_kind": self.symbol_kind.value,
            "target_document_id": self.target_document_id,
            "target_name": self.target_name,
            "target_scope_id": self.target_scope_id,
            "target_symbol_id": self.target_symbol_id,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "LegalIRSymbolAlias":
        return cls(
            alias_id=str(data.get("alias_id") or ""),
            alias=str(data.get("alias") or data.get("name") or ""),
            scope_id=str(data.get("scope_id") or ""),
            symbol_kind=_symbol_kind(data.get("symbol_kind") or data.get("kind")),
            normalized_alias=str(data.get("normalized_alias") or ""),
            target_symbol_id=str(data.get("target_symbol_id") or ""),
            target_name=str(data.get("target_name") or data.get("target") or ""),
            target_document_id=str(data.get("target_document_id") or ""),
            target_scope_id=str(data.get("target_scope_id") or ""),
            document_id=str(data.get("document_id") or ""),
            source_node_ids=tuple(_unique(_strings(data.get("source_node_ids", ())))),
            span_ids=tuple(_unique(_strings(data.get("span_ids", ())))),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass(frozen=True)
class LegalIRSymbolReference:
    """A use-site that must resolve to a typed definition."""

    reference_id: str
    name: str
    symbol_kind: LegalIRSymbolKind
    scope_id: str
    document_id: str = ""
    normalized_name: str = ""
    explicit_target_document_id: str = ""
    explicit_scope_id: str = ""
    source_node_ids: tuple[str, ...] = ()
    span_ids: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "document_id": self.document_id,
            "explicit_scope_id": self.explicit_scope_id,
            "explicit_target_document_id": self.explicit_target_document_id,
            "metadata": _canonical_json_value(self.metadata),
            "name": self.name,
            "normalized_name": self.normalized_name or normalize_legal_symbol_name(self.name),
            "reference_id": self.reference_id,
            "scope_id": self.scope_id,
            "source_node_ids": list(self.source_node_ids),
            "span_ids": list(self.span_ids),
            "symbol_kind": self.symbol_kind.value,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "LegalIRSymbolReference":
        return cls(
            reference_id=str(data.get("reference_id") or ""),
            name=str(data.get("name") or data.get("term") or data.get("ref") or ""),
            symbol_kind=_symbol_kind(data.get("symbol_kind") or data.get("kind")),
            scope_id=str(data.get("scope_id") or ""),
            document_id=str(data.get("document_id") or ""),
            normalized_name=str(data.get("normalized_name") or ""),
            explicit_target_document_id=str(data.get("explicit_target_document_id") or data.get("target_document_id") or ""),
            explicit_scope_id=str(data.get("explicit_scope_id") or data.get("target_scope_id") or ""),
            source_node_ids=tuple(_unique(_strings(data.get("source_node_ids", ())))),
            span_ids=tuple(_unique(_strings(data.get("span_ids", ())))),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass(frozen=True)
class LegalIRSymbolDiagnostic:
    """One typed symbol-table diagnostic with provenance identifiers."""

    diagnostic_type: LegalIRSymbolDiagnosticType
    message: str
    severity: str = "error"
    reference_id: str = ""
    symbol_ids: tuple[str, ...] = ()
    alias_ids: tuple[str, ...] = ()
    scope_id: str = ""
    document_id: str = ""
    source_node_ids: tuple[str, ...] = ()
    source_span_ids: tuple[str, ...] = ()
    field_path: str = ""

    @property
    def code(self) -> str:
        return self.diagnostic_type.value

    def to_dict(self) -> dict[str, Any]:
        return {
            "alias_ids": list(self.alias_ids),
            "code": self.code,
            "diagnostic_type": self.diagnostic_type.value,
            "document_id": self.document_id,
            "field_path": self.field_path,
            "message": self.message,
            "reference_id": self.reference_id,
            "scope_id": self.scope_id,
            "severity": self.severity,
            "source_node_ids": list(self.source_node_ids),
            "source_span_ids": list(self.source_span_ids),
            "symbol_ids": list(self.symbol_ids),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "LegalIRSymbolDiagnostic":
        return cls(
            diagnostic_type=_diagnostic_type(data.get("diagnostic_type") or data.get("code")),
            message=str(data.get("message") or ""),
            severity=str(data.get("severity") or "error"),
            reference_id=str(data.get("reference_id") or ""),
            symbol_ids=tuple(_unique(_strings(data.get("symbol_ids", ())))),
            alias_ids=tuple(_unique(_strings(data.get("alias_ids", ())))),
            scope_id=str(data.get("scope_id") or ""),
            document_id=str(data.get("document_id") or ""),
            source_node_ids=tuple(_unique(_strings(data.get("source_node_ids", ())))),
            source_span_ids=tuple(_unique(_strings(data.get("source_span_ids", ())))),
            field_path=str(data.get("field_path") or ""),
        )


@dataclass(frozen=True)
class LegalIRSymbolResolution:
    """Recorded resolution result for one reference."""

    reference_id: str
    status: LegalIRResolutionStatus
    symbol_ids: tuple[str, ...] = ()
    alias_ids: tuple[str, ...] = ()
    scope_path: tuple[str, ...] = ()
    diagnostics: tuple[LegalIRSymbolDiagnostic, ...] = ()
    source_traces: tuple[LegalIRFactTrace, ...] = ()

    @property
    def resolved(self) -> bool:
        return self.status is LegalIRResolutionStatus.RESOLVED and len(self.symbol_ids) == 1

    @property
    def diagnostic_types(self) -> tuple[LegalIRSymbolDiagnosticType, ...]:
        return tuple(issue.diagnostic_type for issue in self.diagnostics)

    def to_dict(self) -> dict[str, Any]:
        return {
            "alias_ids": list(self.alias_ids),
            "diagnostic_types": [item.value for item in self.diagnostic_types],
            "diagnostics": [issue.to_dict() for issue in self.diagnostics],
            "reference_id": self.reference_id,
            "resolved": self.resolved,
            "scope_path": list(self.scope_path),
            "source_traces": [trace.to_dict() for trace in self.source_traces],
            "status": self.status.value,
            "symbol_ids": list(self.symbol_ids),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "LegalIRSymbolResolution":
        return cls(
            reference_id=str(data.get("reference_id") or ""),
            status=_resolution_status(data.get("status")),
            symbol_ids=tuple(_unique(_strings(data.get("symbol_ids", ())))),
            alias_ids=tuple(_unique(_strings(data.get("alias_ids", ())))),
            scope_path=tuple(_unique(_strings(data.get("scope_path", ())))),
            diagnostics=tuple(
                LegalIRSymbolDiagnostic.from_dict(_mapping(item))
                for item in data.get("diagnostics", []) or []
            ),
            source_traces=tuple(
                _fact_trace_from_dict(_mapping(item))
                for item in data.get("source_traces", []) or []
            ),
        )


@dataclass(frozen=True)
class LegalIRSymbolTableValidationResult:
    """Validation result for a complete LegalIR symbol table."""

    symbol_table_id: str
    scope_count: int
    definition_count: int
    alias_count: int
    reference_count: int
    resolved_count: int
    diagnostics: tuple[LegalIRSymbolDiagnostic, ...] = ()
    schema_version: str = LEGAL_IR_SYMBOL_TABLE_SCHEMA_VERSION

    @property
    def valid(self) -> bool:
        return not any(issue.severity == "error" for issue in self.diagnostics)

    def to_dict(self) -> dict[str, Any]:
        return {
            "alias_count": int(self.alias_count),
            "definition_count": int(self.definition_count),
            "diagnostics": [issue.to_dict() for issue in self.diagnostics],
            "reference_count": int(self.reference_count),
            "resolved_count": int(self.resolved_count),
            "schema_version": self.schema_version,
            "scope_count": int(self.scope_count),
            "symbol_table_id": self.symbol_table_id,
            "valid": self.valid,
        }


@dataclass(frozen=True)
class LegalIRSymbolTable:
    """Immutable scoped table for definitions, aliases, and references."""

    symbol_table_id: str
    scopes: tuple[LegalIRSymbolScope, ...]
    definitions: tuple[LegalIRSymbolDefinition, ...]
    aliases: tuple[LegalIRSymbolAlias, ...] = ()
    references: tuple[LegalIRSymbolReference, ...] = ()
    resolutions: tuple[LegalIRSymbolResolution, ...] = ()
    diagnostics: tuple[LegalIRSymbolDiagnostic, ...] = ()
    source_map_id: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = LEGAL_IR_SYMBOL_TABLE_SCHEMA_VERSION

    @property
    def scope_by_id(self) -> Mapping[str, LegalIRSymbolScope]:
        return {scope.scope_id: scope for scope in self.scopes}

    @property
    def definition_by_id(self) -> Mapping[str, LegalIRSymbolDefinition]:
        return {definition.symbol_id: definition for definition in self.definitions}

    @property
    def alias_by_id(self) -> Mapping[str, LegalIRSymbolAlias]:
        return {alias.alias_id: alias for alias in self.aliases}

    @property
    def reference_by_id(self) -> Mapping[str, LegalIRSymbolReference]:
        return {reference.reference_id: reference for reference in self.references}

    @property
    def resolution_by_reference_id(self) -> Mapping[str, LegalIRSymbolResolution]:
        return {resolution.reference_id: resolution for resolution in self.resolutions}

    @property
    def unresolved_references(self) -> tuple[LegalIRSymbolReference, ...]:
        resolutions = self.resolution_by_reference_id
        return tuple(
            reference
            for reference in self.references
            if resolutions.get(reference.reference_id, LegalIRSymbolResolution(reference.reference_id, LegalIRResolutionStatus.UNRESOLVED)).status
            is LegalIRResolutionStatus.UNRESOLVED
        )

    @property
    def ambiguous_references(self) -> tuple[LegalIRSymbolReference, ...]:
        resolutions = self.resolution_by_reference_id
        return tuple(
            reference
            for reference in self.references
            if resolutions.get(reference.reference_id, LegalIRSymbolResolution(reference.reference_id, LegalIRResolutionStatus.UNRESOLVED)).status
            is LegalIRResolutionStatus.AMBIGUOUS
        )

    @property
    def resolved(self) -> bool:
        return not self.unresolved_references and not self.ambiguous_references

    def to_dict(self) -> dict[str, Any]:
        return {
            "aliases": [alias.to_dict() for alias in self.aliases],
            "definitions": [definition.to_dict() for definition in self.definitions],
            "diagnostics": [issue.to_dict() for issue in self.diagnostics],
            "metadata": _canonical_json_value(self.metadata),
            "references": [reference.to_dict() for reference in self.references],
            "resolutions": [resolution.to_dict() for resolution in self.resolutions],
            "schema_version": self.schema_version,
            "scopes": [scope.to_dict() for scope in self.scopes],
            "source_map_id": self.source_map_id,
            "symbol_table_id": self.symbol_table_id,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "LegalIRSymbolTable":
        return cls(
            symbol_table_id=str(data.get("symbol_table_id") or ""),
            scopes=tuple(
                LegalIRSymbolScope.from_dict(_mapping(item))
                for item in data.get("scopes", []) or []
            ),
            definitions=tuple(
                LegalIRSymbolDefinition.from_dict(_mapping(item))
                for item in data.get("definitions", []) or []
            ),
            aliases=tuple(
                LegalIRSymbolAlias.from_dict(_mapping(item))
                for item in data.get("aliases", []) or []
            ),
            references=tuple(
                LegalIRSymbolReference.from_dict(_mapping(item))
                for item in data.get("references", []) or []
            ),
            resolutions=tuple(
                LegalIRSymbolResolution.from_dict(_mapping(item))
                for item in data.get("resolutions", []) or []
            ),
            diagnostics=tuple(
                LegalIRSymbolDiagnostic.from_dict(_mapping(item))
                for item in data.get("diagnostics", []) or []
            ),
            source_map_id=str(data.get("source_map_id") or ""),
            metadata=dict(data.get("metadata") or {}),
            schema_version=str(data.get("schema_version") or LEGAL_IR_SYMBOL_TABLE_SCHEMA_VERSION),
        )


class LegalIRSymbolTableBuilder:
    """Mutable builder that resolves references deterministically."""

    def __init__(
        self,
        *,
        symbol_table_id: str = "",
        source_map: LegalIRSourceMap | Mapping[str, Any] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        self.symbol_table_id = symbol_table_id
        self.source_map = _source_map(source_map) if source_map is not None else None
        self.metadata = dict(metadata or {})
        self._scopes: dict[str, LegalIRSymbolScope] = {}
        self._definitions: dict[str, LegalIRSymbolDefinition] = {}
        self._aliases: dict[str, LegalIRSymbolAlias] = {}
        self._references: dict[str, LegalIRSymbolReference] = {}
        self._diagnostics: list[LegalIRSymbolDiagnostic] = []
        self.add_scope("global", LegalIRScopeKind.GLOBAL)

    def add_scope(
        self,
        scope_id: str,
        scope_kind: LegalIRScopeKind | str,
        *,
        parent_scope_id: str = "",
        document_id: str = "",
        citation: str = "",
        source_node_ids: Sequence[str] = (),
        metadata: Mapping[str, Any] | None = None,
    ) -> LegalIRSymbolScope:
        scope = LegalIRSymbolScope(
            scope_id=str(scope_id or ""),
            scope_kind=_scope_kind(scope_kind),
            parent_scope_id=str(parent_scope_id or ""),
            document_id=str(document_id or ""),
            citation=str(citation or ""),
            source_node_ids=tuple(_unique(_strings(source_node_ids))),
            metadata=dict(metadata or {}),
        )
        self._scopes[scope.scope_id] = scope
        return scope

    def add_document_scope(
        self,
        document_id: str,
        *,
        citation: str = "",
        parent_scope_id: str = "global",
        source_node_ids: Sequence[str] = (),
    ) -> LegalIRSymbolScope:
        return self.add_scope(
            f"document:{document_id}",
            LegalIRScopeKind.DOCUMENT,
            parent_scope_id=parent_scope_id,
            document_id=document_id,
            citation=citation,
            source_node_ids=source_node_ids,
        )

    def add_definition(
        self,
        name: str,
        symbol_kind: LegalIRSymbolKind | str,
        *,
        symbol_id: str = "",
        scope_id: str = "global",
        document_id: str = "",
        aliases: Sequence[str] = (),
        source_node_ids: Sequence[str] = (),
        span_ids: Sequence[str] = (),
        metadata: Mapping[str, Any] | None = None,
    ) -> LegalIRSymbolDefinition:
        kind = _symbol_kind(symbol_kind)
        normalized_name = normalize_legal_symbol_name(name)
        payload = {
            "document_id": document_id,
            "kind": kind.value,
            "name": normalized_name,
            "scope_id": scope_id,
        }
        definition = LegalIRSymbolDefinition(
            symbol_id=str(symbol_id or f"lir-symbol-{_stable_hash(payload)[:24]}"),
            name=str(name or ""),
            symbol_kind=kind,
            scope_id=str(scope_id or "global"),
            document_id=str(document_id or ""),
            normalized_name=normalized_name,
            source_node_ids=tuple(_unique(_strings(source_node_ids))),
            span_ids=tuple(_unique(_strings(span_ids))),
            aliases=tuple(_unique(normalize_legal_symbol_name(alias) for alias in _strings(aliases))),
            metadata=dict(metadata or {}),
        )
        self._definitions[definition.symbol_id] = definition
        for alias in aliases:
            self.add_alias(
                alias,
                target_symbol_id=definition.symbol_id,
                symbol_kind=kind,
                scope_id=scope_id,
                document_id=document_id,
                source_node_ids=source_node_ids,
                span_ids=span_ids,
                metadata={"definition_alias": True},
            )
        return definition

    def add_alias(
        self,
        alias: str,
        *,
        target_symbol_id: str = "",
        target_name: str = "",
        target_document_id: str = "",
        target_scope_id: str = "",
        alias_id: str = "",
        symbol_kind: LegalIRSymbolKind | str = LegalIRSymbolKind.UNKNOWN,
        scope_id: str = "global",
        document_id: str = "",
        source_node_ids: Sequence[str] = (),
        span_ids: Sequence[str] = (),
        metadata: Mapping[str, Any] | None = None,
    ) -> LegalIRSymbolAlias:
        kind = _symbol_kind(symbol_kind)
        normalized_alias = normalize_legal_symbol_name(alias)
        payload = {
            "alias": normalized_alias,
            "document_id": document_id,
            "kind": kind.value,
            "scope_id": scope_id,
            "target_name": normalize_legal_symbol_name(target_name),
            "target_scope_id": target_scope_id,
            "target_symbol_id": target_symbol_id,
        }
        record = LegalIRSymbolAlias(
            alias_id=str(alias_id or f"lir-alias-{_stable_hash(payload)[:24]}"),
            alias=str(alias or ""),
            scope_id=str(scope_id or "global"),
            symbol_kind=kind,
            normalized_alias=normalized_alias,
            target_symbol_id=str(target_symbol_id or ""),
            target_name=str(target_name or ""),
            target_document_id=str(target_document_id or ""),
            target_scope_id=str(target_scope_id or ""),
            document_id=str(document_id or ""),
            source_node_ids=tuple(_unique(_strings(source_node_ids))),
            span_ids=tuple(_unique(_strings(span_ids))),
            metadata=dict(metadata or {}),
        )
        self._aliases[record.alias_id] = record
        return record

    def add_reference(
        self,
        name: str,
        symbol_kind: LegalIRSymbolKind | str,
        *,
        reference_id: str = "",
        scope_id: str = "global",
        document_id: str = "",
        explicit_target_document_id: str = "",
        explicit_scope_id: str = "",
        source_node_ids: Sequence[str] = (),
        span_ids: Sequence[str] = (),
        metadata: Mapping[str, Any] | None = None,
    ) -> LegalIRSymbolReference:
        kind = _symbol_kind(symbol_kind)
        normalized_name = normalize_legal_symbol_name(name)
        payload = {
            "document_id": document_id,
            "kind": kind.value,
            "name": normalized_name,
            "scope_id": scope_id,
            "target_document_id": explicit_target_document_id,
        }
        reference = LegalIRSymbolReference(
            reference_id=str(reference_id or f"lir-reference-{_stable_hash(payload)[:24]}"),
            name=str(name or ""),
            symbol_kind=kind,
            scope_id=str(scope_id or "global"),
            document_id=str(document_id or ""),
            normalized_name=normalized_name,
            explicit_target_document_id=str(explicit_target_document_id or ""),
            explicit_scope_id=str(explicit_scope_id or ""),
            source_node_ids=tuple(_unique(_strings(source_node_ids))),
            span_ids=tuple(_unique(_strings(span_ids))),
            metadata=dict(metadata or {}),
        )
        self._references[reference.reference_id] = reference
        return reference

    def resolve_reference(
        self,
        reference: LegalIRSymbolReference | str,
        *,
        external_symbol_tables: Sequence[LegalIRSymbolTable | Mapping[str, Any]] = (),
    ) -> LegalIRSymbolResolution:
        ref = (
            self._references[str(reference)]
            if isinstance(reference, str)
            else reference
        )
        table = self.to_symbol_table(resolve=False)
        return _resolve_reference(
            table,
            ref,
            external_symbol_tables=external_symbol_tables,
            source_map=self.source_map,
        )

    def to_symbol_table(
        self,
        *,
        resolve: bool = True,
        external_symbol_tables: Sequence[LegalIRSymbolTable | Mapping[str, Any]] = (),
    ) -> LegalIRSymbolTable:
        table_id = self.symbol_table_id or "lir-symbol-table-" + _stable_hash(
            {
                "aliases": sorted(self._aliases),
                "definitions": sorted(self._definitions),
                "references": sorted(self._references),
                "scopes": sorted(self._scopes),
            }
        )[:24]
        base = LegalIRSymbolTable(
            symbol_table_id=table_id,
            scopes=tuple(self._scopes[key] for key in sorted(self._scopes)),
            definitions=tuple(self._definitions[key] for key in sorted(self._definitions)),
            aliases=tuple(self._aliases[key] for key in sorted(self._aliases)),
            references=tuple(self._references[key] for key in sorted(self._references)),
            resolutions=(),
            diagnostics=tuple(_dedupe_diagnostics(self._diagnostics)),
            source_map_id=self.source_map.source_map_id if self.source_map is not None else "",
            metadata=dict(self.metadata),
        )
        if not resolve:
            return base
        resolutions = tuple(
            _resolve_reference(
                base,
                reference,
                external_symbol_tables=external_symbol_tables,
                source_map=self.source_map,
            )
            for reference in base.references
        )
        diagnostics = tuple(
            _dedupe_diagnostics(
                (
                    *base.diagnostics,
                    *(diagnostic for resolution in resolutions for diagnostic in resolution.diagnostics),
                )
            )
        )
        return LegalIRSymbolTable(
            symbol_table_id=base.symbol_table_id,
            scopes=base.scopes,
            definitions=base.definitions,
            aliases=base.aliases,
            references=base.references,
            resolutions=resolutions,
            diagnostics=diagnostics,
            source_map_id=base.source_map_id,
            metadata=base.metadata,
        )


def normalize_legal_symbol_name(name: Any) -> str:
    """Return a stable lookup key for legal terms without retaining source text."""

    words = _WORD_RE.findall(str(name or "").lower())
    return " ".join(words)


def build_legal_ir_symbol_table(
    document_or_sample: Mapping[str, Any] | Any,
    *,
    source_map: LegalIRSourceMap | Mapping[str, Any] | None = None,
    external_symbol_tables: Sequence[LegalIRSymbolTable | Mapping[str, Any]] = (),
) -> LegalIRSymbolTable:
    """Build a scoped symbol table from common LegalIR document shapes."""

    sample = _payload_mapping(document_or_sample)
    document = _mapping(sample.get("modal_ir") or sample.get("document") or sample)
    document_id = str(document.get("document_id") or sample.get("document_id") or sample.get("sample_id") or "legal-ir-document")
    citation = str(document.get("citation") or sample.get("citation") or "")
    builder = LegalIRSymbolTableBuilder(
        source_map=source_map,
        metadata={"builder": "build_legal_ir_symbol_table"},
    )
    document_scope = builder.add_document_scope(document_id, citation=citation)

    for item in _sequence(document.get("defined_terms") or document.get("definitions")):
        payload = _definition_payload(item)
        if not payload:
            continue
        scope_id = str(payload.get("scope_id") or document_scope.scope_id)
        builder.add_definition(
            str(payload.get("name") or payload.get("term") or payload.get("symbol") or ""),
            _symbol_kind(payload.get("symbol_kind") or payload.get("kind") or LegalIRSymbolKind.DEFINED_TERM),
            symbol_id=str(payload.get("symbol_id") or ""),
            scope_id=scope_id,
            document_id=str(payload.get("document_id") or document_id),
            aliases=_strings(payload.get("aliases", ())),
            source_node_ids=_source_node_ids(payload),
            span_ids=_strings(payload.get("span_ids", ())),
            metadata={key: value for key, value in payload.items() if key not in {"name", "term", "symbol", "aliases"}},
        )

    for field_name, kind in (
        ("actors", LegalIRSymbolKind.ACTOR),
        ("authorities", LegalIRSymbolKind.AUTHORITY),
        ("exceptions", LegalIRSymbolKind.EXCEPTION),
        ("conditions", LegalIRSymbolKind.CONDITION),
    ):
        for item in _sequence(document.get(field_name)):
            payload = _definition_payload(item)
            name = str(payload.get("name") or payload.get("term") or payload.get("symbol") or item or "")
            if name:
                builder.add_definition(
                    name,
                    kind,
                    symbol_id=str(payload.get("symbol_id") or ""),
                    scope_id=str(payload.get("scope_id") or document_scope.scope_id),
                    document_id=str(payload.get("document_id") or document_id),
                    aliases=_strings(payload.get("aliases", ())),
                    source_node_ids=_source_node_ids(payload),
                    span_ids=_strings(payload.get("span_ids", ())),
                    metadata={"field": field_name},
                )

    for item in _sequence(document.get("aliases")):
        payload = _mapping(item)
        builder.add_alias(
            str(payload.get("alias") or payload.get("name") or ""),
            target_symbol_id=str(payload.get("target_symbol_id") or ""),
            target_name=str(payload.get("target_name") or payload.get("target") or ""),
            target_document_id=str(payload.get("target_document_id") or ""),
            target_scope_id=str(payload.get("target_scope_id") or ""),
            symbol_kind=_symbol_kind(payload.get("symbol_kind") or payload.get("kind")),
            scope_id=str(payload.get("scope_id") or document_scope.scope_id),
            document_id=str(payload.get("document_id") or document_id),
            source_node_ids=_source_node_ids(payload),
            span_ids=_strings(payload.get("span_ids", ())),
        )

    for index, formula in enumerate(_sequence(document.get("formulas")), start=1):
        formula_payload = _mapping(formula)
        formula_id = str(formula_payload.get("formula_id") or f"formula-{index}")
        formula_scope = builder.add_scope(
            f"formula:{formula_id}",
            LegalIRScopeKind.FORMULA,
            parent_scope_id=document_scope.scope_id,
            document_id=document_id,
            citation=citation,
            source_node_ids=(formula_id,),
            metadata={"formula_id": formula_id},
        )
        for field_name, kind in (
            ("exceptions", LegalIRSymbolKind.EXCEPTION),
            ("conditions", LegalIRSymbolKind.CONDITION),
        ):
            for ordinal, item in enumerate(_sequence(formula_payload.get(field_name)), start=1):
                payload = _definition_payload(item)
                name = str(payload.get("name") or payload.get("term") or payload.get("symbol") or item or "")
                if name:
                    builder.add_definition(
                        name,
                        kind,
                        symbol_id=str(payload.get("symbol_id") or f"{formula_id}:{field_name}:{ordinal}"),
                        scope_id=formula_scope.scope_id,
                        document_id=document_id,
                        source_node_ids=_source_node_ids(payload) or (formula_id,),
                        span_ids=_strings(payload.get("span_ids", ())),
                        metadata={"field": field_name, "formula_id": formula_id},
                    )
        for field_name, kind in (
            ("actor", LegalIRSymbolKind.ACTOR),
            ("authority", LegalIRSymbolKind.AUTHORITY),
        ):
            name = str(formula_payload.get(field_name) or "")
            if name:
                builder.add_reference(
                    name,
                    kind,
                    reference_id=f"{formula_id}:{field_name}",
                    scope_id=formula_scope.scope_id,
                    document_id=document_id,
                    source_node_ids=(formula_id,),
                    metadata={"field": field_name, "formula_id": formula_id},
                )

    for item in _sequence(document.get("references")):
        payload = _mapping(item)
        builder.add_reference(
            str(payload.get("name") or payload.get("term") or payload.get("ref") or ""),
            _symbol_kind(payload.get("symbol_kind") or payload.get("kind")),
            reference_id=str(payload.get("reference_id") or ""),
            scope_id=str(payload.get("scope_id") or document_scope.scope_id),
            document_id=str(payload.get("document_id") or document_id),
            explicit_target_document_id=str(payload.get("explicit_target_document_id") or payload.get("target_document_id") or ""),
            explicit_scope_id=str(payload.get("explicit_scope_id") or payload.get("target_scope_id") or ""),
            source_node_ids=_source_node_ids(payload),
            span_ids=_strings(payload.get("span_ids", ())),
            metadata={key: value for key, value in payload.items() if key not in {"name", "term", "ref"}},
        )

    return builder.to_symbol_table(external_symbol_tables=external_symbol_tables)


def resolve_legal_ir_symbol(
    symbol_table: LegalIRSymbolTable | Mapping[str, Any],
    reference: LegalIRSymbolReference | str,
    *,
    external_symbol_tables: Sequence[LegalIRSymbolTable | Mapping[str, Any]] = (),
    source_map: LegalIRSourceMap | Mapping[str, Any] | None = None,
) -> LegalIRSymbolResolution:
    """Resolve one LegalIR reference and return a typed outcome."""

    table = _symbol_table(symbol_table)
    ref = table.reference_by_id[str(reference)] if isinstance(reference, str) else reference
    return _resolve_reference(
        table,
        ref,
        external_symbol_tables=external_symbol_tables,
        source_map=_source_map(source_map) if source_map is not None else None,
    )


def validate_legal_ir_symbol_table(
    symbol_table: LegalIRSymbolTable | Mapping[str, Any],
    *,
    source_map: LegalIRSourceMap | Mapping[str, Any] | None = None,
    external_symbol_tables: Sequence[LegalIRSymbolTable | Mapping[str, Any]] = (),
) -> LegalIRSymbolTableValidationResult:
    """Validate scopes, symbol references, diagnostics, and provenance."""

    table = _symbol_table(symbol_table)
    resolved_source_map = _source_map(source_map) if source_map is not None else None
    external_tables = tuple(_symbol_table(item) for item in external_symbol_tables)
    diagnostics: list[LegalIRSymbolDiagnostic] = list(table.diagnostics)
    scopes = table.scope_by_id
    definitions = table.definition_by_id
    references = table.reference_by_id

    _duplicate_diagnostic("scope", [scope.scope_id for scope in table.scopes], diagnostics, LegalIRSymbolDiagnosticType.DUPLICATE_SCOPE_ID)
    _duplicate_diagnostic("symbol", [definition.symbol_id for definition in table.definitions], diagnostics, LegalIRSymbolDiagnosticType.DUPLICATE_SYMBOL_ID)
    _duplicate_diagnostic("reference", [reference.reference_id for reference in table.references], diagnostics, LegalIRSymbolDiagnosticType.DUPLICATE_REFERENCE_ID)

    for scope in table.scopes:
        if not scope.scope_id:
            diagnostics.append(_diagnostic(LegalIRSymbolDiagnosticType.SCOPE_MISSING, "Scope has no ID.", scope_id=scope.scope_id))
        if scope.parent_scope_id and scope.parent_scope_id not in scopes:
            diagnostics.append(_diagnostic(LegalIRSymbolDiagnosticType.SCOPE_PARENT_MISSING, "Scope parent is missing.", scope_id=scope.scope_id, field_path=f"scopes.{scope.scope_id}.parent_scope_id"))
    for definition in table.definitions:
        if definition.scope_id not in scopes:
            diagnostics.append(_diagnostic(LegalIRSymbolDiagnosticType.SYMBOL_SCOPE_MISSING, "Symbol definition references a missing scope.", symbol_ids=(definition.symbol_id,), scope_id=definition.scope_id))
        _append_provenance_diagnostics(diagnostics, definition.source_node_ids, resolved_source_map, symbol_ids=(definition.symbol_id,), scope_id=definition.scope_id)
    for alias in table.aliases:
        if alias.scope_id not in scopes:
            diagnostics.append(_diagnostic(LegalIRSymbolDiagnosticType.SYMBOL_SCOPE_MISSING, "Alias references a missing scope.", alias_ids=(alias.alias_id,), scope_id=alias.scope_id))
        if alias.target_symbol_id and alias.target_symbol_id not in definitions:
            diagnostics.append(_diagnostic(LegalIRSymbolDiagnosticType.ALIAS_TARGET_UNRESOLVED, "Alias target symbol is missing.", alias_ids=(alias.alias_id,), symbol_ids=(alias.target_symbol_id,), scope_id=alias.scope_id))
        _append_provenance_diagnostics(diagnostics, alias.source_node_ids, resolved_source_map, alias_ids=(alias.alias_id,), scope_id=alias.scope_id)
    for reference in table.references:
        if reference.scope_id not in scopes:
            diagnostics.append(_diagnostic(LegalIRSymbolDiagnosticType.REFERENCE_SCOPE_MISSING, "Reference uses a missing scope.", reference_id=reference.reference_id, scope_id=reference.scope_id))
        _append_provenance_diagnostics(diagnostics, reference.source_node_ids, resolved_source_map, reference_id=reference.reference_id, scope_id=reference.scope_id)

    for resolution in table.resolutions:
        if resolution.reference_id not in references:
            diagnostics.append(_diagnostic(LegalIRSymbolDiagnosticType.RESOLUTION_TARGET_MISSING, "Resolution references a missing reference.", reference_id=resolution.reference_id))
        for symbol_id in resolution.symbol_ids:
            if symbol_id not in definitions and not _external_definition_exists(symbol_id, external_tables):
                diagnostics.append(_diagnostic(LegalIRSymbolDiagnosticType.RESOLUTION_TARGET_MISSING, "Resolution points at a missing symbol.", reference_id=resolution.reference_id, symbol_ids=(symbol_id,)))
        if resolution.status is not LegalIRResolutionStatus.RESOLVED and not resolution.diagnostics:
            diagnostics.append(_diagnostic(LegalIRSymbolDiagnosticType.RESOLUTION_DIAGNOSTIC_MISSING, "Non-resolved resolution lacks diagnostics.", reference_id=resolution.reference_id))

    diagnostics = list(_dedupe_diagnostics(diagnostics))
    return LegalIRSymbolTableValidationResult(
        symbol_table_id=table.symbol_table_id,
        scope_count=len(table.scopes),
        definition_count=len(table.definitions),
        alias_count=len(table.aliases),
        reference_count=len(table.references),
        resolved_count=sum(1 for resolution in table.resolutions if resolution.resolved),
        diagnostics=tuple(diagnostics),
    )


def assert_legal_ir_symbols_resolved(
    symbol_table: LegalIRSymbolTable | Mapping[str, Any],
) -> LegalIRSymbolTable:
    """Return a table or raise if any reference is unresolved or ambiguous."""

    table = _symbol_table(symbol_table)
    if table.unresolved_references or table.ambiguous_references:
        codes = ",".join(issue.code for issue in table.diagnostics) or "unresolved_symbols"
        raise ValueError(f"LegalIR symbols are not fully resolved: {codes}")
    return table


def merge_legal_ir_symbol_tables(
    symbol_tables: Sequence[LegalIRSymbolTable | Mapping[str, Any]],
    *,
    symbol_table_id: str = "",
) -> LegalIRSymbolTable:
    """Merge tables for cross-document resolution without rewriting IDs."""

    tables = tuple(_symbol_table(table) for table in symbol_tables)
    return LegalIRSymbolTable(
        symbol_table_id=symbol_table_id or "lir-symbol-table-" + _stable_hash([table.symbol_table_id for table in tables])[:24],
        scopes=tuple(_unique_records(scope for table in tables for scope in table.scopes)),
        definitions=tuple(_unique_records(definition for table in tables for definition in table.definitions)),
        aliases=tuple(_unique_records(alias for table in tables for alias in table.aliases)),
        references=tuple(_unique_records(reference for table in tables for reference in table.references)),
        resolutions=tuple(_unique_records(resolution for table in tables for resolution in table.resolutions)),
        diagnostics=tuple(_dedupe_diagnostics(issue for table in tables for issue in table.diagnostics)),
        source_map_id=",".join(_unique(table.source_map_id for table in tables if table.source_map_id)),
        metadata={"merged_symbol_table_ids": [table.symbol_table_id for table in tables]},
    )


def _resolve_reference(
    table: LegalIRSymbolTable,
    reference: LegalIRSymbolReference,
    *,
    external_symbol_tables: Sequence[LegalIRSymbolTable | Mapping[str, Any]] = (),
    source_map: LegalIRSourceMap | None = None,
) -> LegalIRSymbolResolution:
    external_tables = tuple(_symbol_table(item) for item in external_symbol_tables)
    normalized = reference.normalized_name or normalize_legal_symbol_name(reference.name)
    scope_path = _scope_path(table, reference.scope_id, explicit_scope_id=reference.explicit_scope_id)
    candidates: list[tuple[LegalIRSymbolDefinition, tuple[str, ...]]] = []
    diagnostics: list[LegalIRSymbolDiagnostic] = []

    for scope_id in scope_path:
        local = _definition_candidates(table, normalized, reference.symbol_kind, scope_id, reference.explicit_target_document_id)
        alias_candidates, alias_diagnostics = _alias_candidates(
            table,
            normalized,
            reference.symbol_kind,
            scope_id,
            reference.explicit_target_document_id,
            external_tables=external_tables,
        )
        diagnostics.extend(alias_diagnostics)
        if local or alias_candidates:
            candidates.extend((definition, ()) for definition in local)
            candidates.extend(alias_candidates)
            break

    if not candidates and reference.explicit_target_document_id:
        candidates.extend(
            (definition, ())
            for definition in table.definitions
            if _matches_definition(
                definition,
                normalized,
                reference.symbol_kind,
                document_id=reference.explicit_target_document_id,
            )
        )
        for external in external_tables:
            candidates.extend(
                (definition, ())
                for definition in external.definitions
                if _matches_definition(
                    definition,
                    normalized,
                    reference.symbol_kind,
                    document_id=reference.explicit_target_document_id,
                )
            )
            alias_candidates, alias_diagnostics = _alias_candidates(
                external,
                normalized,
                reference.symbol_kind,
                reference.explicit_scope_id or f"document:{reference.explicit_target_document_id}",
                reference.explicit_target_document_id,
                external_tables=external_tables,
            )
            candidates.extend(alias_candidates)
            diagnostics.extend(alias_diagnostics)

    collapsed = _collapse_candidates(candidates)
    source_traces = _source_traces_for_reference(source_map, reference, collapsed)
    source_node_ids = tuple(
        _unique(
            (
                *reference.source_node_ids,
                *(node_id for definition in collapsed for node_id in definition.source_node_ids),
            )
        )
    )
    source_span_ids = tuple(
        _unique(
            (
                *reference.span_ids,
                *(span_id for definition in collapsed for span_id in definition.span_ids),
                *(span.span_id for trace in source_traces for span in trace.source_spans),
            )
        )
    )

    if not collapsed:
        diagnostics.append(
            _diagnostic(
                LegalIRSymbolDiagnosticType.UNRESOLVED_SYMBOL,
                f"Reference {reference.reference_id!r} does not resolve to a {reference.symbol_kind.value} definition.",
                reference_id=reference.reference_id,
                scope_id=reference.scope_id,
                document_id=reference.document_id,
                source_node_ids=source_node_ids,
                source_span_ids=source_span_ids,
            )
        )
        return LegalIRSymbolResolution(
            reference_id=reference.reference_id,
            status=LegalIRResolutionStatus.UNRESOLVED,
            scope_path=scope_path,
            diagnostics=tuple(_dedupe_diagnostics(diagnostics)),
            source_traces=source_traces,
        )

    if len(collapsed) > 1:
        diagnostics.append(
            _diagnostic(
                LegalIRSymbolDiagnosticType.AMBIGUOUS_SYMBOL,
                f"Reference {reference.reference_id!r} resolves to multiple {reference.symbol_kind.value} definitions.",
                reference_id=reference.reference_id,
                symbol_ids=tuple(definition.symbol_id for definition in collapsed),
                alias_ids=tuple(_unique(alias_id for _, alias_ids in candidates for alias_id in alias_ids)),
                scope_id=reference.scope_id,
                document_id=reference.document_id,
                source_node_ids=source_node_ids,
                source_span_ids=source_span_ids,
            )
        )
        return LegalIRSymbolResolution(
            reference_id=reference.reference_id,
            status=LegalIRResolutionStatus.AMBIGUOUS,
            symbol_ids=tuple(definition.symbol_id for definition in collapsed),
            alias_ids=tuple(_unique(alias_id for _, alias_ids in candidates for alias_id in alias_ids)),
            scope_path=scope_path,
            diagnostics=tuple(_dedupe_diagnostics(diagnostics)),
            source_traces=source_traces,
        )

    return LegalIRSymbolResolution(
        reference_id=reference.reference_id,
        status=LegalIRResolutionStatus.RESOLVED,
        symbol_ids=(collapsed[0].symbol_id,),
        alias_ids=tuple(_unique(alias_id for _, alias_ids in candidates for alias_id in alias_ids)),
        scope_path=scope_path,
        diagnostics=tuple(_dedupe_diagnostics(diagnostics)),
        source_traces=source_traces,
    )


def _definition_candidates(
    table: LegalIRSymbolTable,
    normalized_name: str,
    kind: LegalIRSymbolKind,
    scope_id: str,
    document_id: str = "",
) -> tuple[LegalIRSymbolDefinition, ...]:
    return tuple(
        definition
        for definition in table.definitions
        if _matches_definition(definition, normalized_name, kind, document_id=document_id)
        and definition.scope_id == scope_id
    )


def _matches_definition(
    definition: LegalIRSymbolDefinition,
    normalized_name: str,
    kind: LegalIRSymbolKind,
    *,
    document_id: str = "",
) -> bool:
    if kind is not LegalIRSymbolKind.UNKNOWN and definition.symbol_kind not in {kind, LegalIRSymbolKind.UNKNOWN}:
        return False
    if document_id and definition.document_id != document_id:
        return False
    return normalized_name in {definition.normalized_name or normalize_legal_symbol_name(definition.name), *definition.aliases}


def _alias_candidates(
    table: LegalIRSymbolTable,
    normalized_name: str,
    kind: LegalIRSymbolKind,
    scope_id: str,
    document_id: str = "",
    *,
    external_tables: Sequence[LegalIRSymbolTable] = (),
) -> tuple[tuple[LegalIRSymbolDefinition, tuple[str, ...]], tuple[LegalIRSymbolDiagnostic, ...]]:
    candidates: list[tuple[LegalIRSymbolDefinition, tuple[str, ...]]] = []
    diagnostics: list[LegalIRSymbolDiagnostic] = []
    for alias in table.aliases:
        if alias.scope_id != scope_id:
            continue
        if (alias.normalized_alias or normalize_legal_symbol_name(alias.alias)) != normalized_name:
            continue
        if kind is not LegalIRSymbolKind.UNKNOWN and alias.symbol_kind not in {kind, LegalIRSymbolKind.UNKNOWN}:
            continue
        if document_id and alias.document_id and alias.document_id != document_id:
            continue
        resolved, alias_diagnostics = _resolve_alias(table, alias, kind, external_tables=external_tables)
        diagnostics.extend(alias_diagnostics)
        candidates.extend((definition, alias_path) for definition, alias_path in resolved)
    return tuple(candidates), tuple(_dedupe_diagnostics(diagnostics))


def _resolve_alias(
    table: LegalIRSymbolTable,
    alias: LegalIRSymbolAlias,
    kind: LegalIRSymbolKind,
    *,
    external_tables: Sequence[LegalIRSymbolTable],
    stack: tuple[str, ...] = (),
) -> tuple[tuple[tuple[LegalIRSymbolDefinition, tuple[str, ...]], ...], tuple[LegalIRSymbolDiagnostic, ...]]:
    if alias.alias_id in stack:
        return (), (
            _diagnostic(
                LegalIRSymbolDiagnosticType.ALIAS_CYCLE,
                "Alias resolution cycle detected.",
                alias_ids=(*stack, alias.alias_id),
                scope_id=alias.scope_id,
                document_id=alias.document_id,
                source_node_ids=alias.source_node_ids,
                source_span_ids=alias.span_ids,
            ),
        )
    if alias.target_symbol_id:
        definition = table.definition_by_id.get(alias.target_symbol_id) or _external_definition(alias.target_symbol_id, external_tables)
        if definition is None:
            return (), (
                _diagnostic(
                    LegalIRSymbolDiagnosticType.ALIAS_TARGET_UNRESOLVED,
                    "Alias target symbol is missing.",
                    alias_ids=(alias.alias_id,),
                    symbol_ids=(alias.target_symbol_id,),
                    scope_id=alias.scope_id,
                    document_id=alias.document_id,
                    source_node_ids=alias.source_node_ids,
                    source_span_ids=alias.span_ids,
                ),
            )
        return ((definition, (*stack, alias.alias_id)),), ()

    target = normalize_legal_symbol_name(alias.target_name)
    if not target:
        return (), (
            _diagnostic(
                LegalIRSymbolDiagnosticType.ALIAS_TARGET_UNRESOLVED,
                "Alias has no resolvable target.",
                alias_ids=(alias.alias_id,),
                scope_id=alias.scope_id,
                document_id=alias.document_id,
                source_node_ids=alias.source_node_ids,
                source_span_ids=alias.span_ids,
            ),
        )

    scope_path = _scope_path(table, alias.scope_id, explicit_scope_id=alias.target_scope_id)
    candidates: list[tuple[LegalIRSymbolDefinition, tuple[str, ...]]] = []
    diagnostics: list[LegalIRSymbolDiagnostic] = []
    for scope_id in scope_path:
        local = _definition_candidates(table, target, kind, scope_id, alias.target_document_id)
        if local:
            candidates.extend((definition, (*stack, alias.alias_id)) for definition in local)
            break
        nested_aliases = tuple(
            item
            for item in table.aliases
            if item.scope_id == scope_id
            and (item.normalized_alias or normalize_legal_symbol_name(item.alias)) == target
        )
        if nested_aliases:
            for nested in nested_aliases:
                resolved, alias_diagnostics = _resolve_alias(
                    table,
                    nested,
                    kind,
                    external_tables=external_tables,
                    stack=(*stack, alias.alias_id),
                )
                candidates.extend(resolved)
                diagnostics.extend(alias_diagnostics)
            break
    if not candidates and alias.target_document_id:
        for external in external_tables:
            candidates.extend(
                (definition, (*stack, alias.alias_id))
                for definition in external.definitions
                if _matches_definition(definition, target, kind, document_id=alias.target_document_id)
            )
    if not candidates:
        diagnostics.append(
            _diagnostic(
                LegalIRSymbolDiagnosticType.ALIAS_TARGET_UNRESOLVED,
                "Alias target name did not resolve.",
                alias_ids=(alias.alias_id,),
                scope_id=alias.scope_id,
                document_id=alias.document_id,
                source_node_ids=alias.source_node_ids,
                source_span_ids=alias.span_ids,
            )
        )
    return tuple(candidates), tuple(_dedupe_diagnostics(diagnostics))


def _scope_path(
    table: LegalIRSymbolTable,
    scope_id: str,
    *,
    explicit_scope_id: str = "",
) -> tuple[str, ...]:
    scopes = table.scope_by_id
    current = explicit_scope_id or scope_id or "global"
    path: list[str] = []
    seen: set[str] = set()
    while current and current not in seen:
        seen.add(current)
        path.append(current)
        current = scopes.get(current, LegalIRSymbolScope("", LegalIRScopeKind.GLOBAL)).parent_scope_id
    if "global" not in path and "global" in scopes:
        path.append("global")
    return tuple(path)


def _collapse_candidates(
    candidates: Sequence[tuple[LegalIRSymbolDefinition, tuple[str, ...]]],
) -> tuple[LegalIRSymbolDefinition, ...]:
    by_id: dict[str, LegalIRSymbolDefinition] = {}
    for definition, _ in candidates:
        by_id[definition.symbol_id] = definition
    return tuple(by_id[key] for key in sorted(by_id))


def _source_traces_for_reference(
    source_map: LegalIRSourceMap | None,
    reference: LegalIRSymbolReference,
    definitions: Sequence[LegalIRSymbolDefinition],
) -> tuple[LegalIRFactTrace, ...]:
    if source_map is None:
        return ()
    traces: list[LegalIRFactTrace] = []
    for node_id in _unique(
        (
            *reference.source_node_ids,
            *(node_id for definition in definitions for node_id in definition.source_node_ids),
        )
    ):
        trace = trace_legal_ir_fact(source_map, node_id)
        if trace.found:
            traces.append(trace)
    return tuple(traces)


def _append_provenance_diagnostics(
    diagnostics: list[LegalIRSymbolDiagnostic],
    source_node_ids: Sequence[str],
    source_map: LegalIRSourceMap | None,
    *,
    reference_id: str = "",
    symbol_ids: Sequence[str] = (),
    alias_ids: Sequence[str] = (),
    scope_id: str = "",
) -> None:
    if not source_node_ids:
        diagnostics.append(
            _diagnostic(
                LegalIRSymbolDiagnosticType.SOURCE_PROVENANCE_MISSING,
                "Symbol-table entry has no source-map node provenance.",
                reference_id=reference_id,
                symbol_ids=tuple(_strings(symbol_ids)),
                alias_ids=tuple(_strings(alias_ids)),
                scope_id=scope_id,
                severity="warning",
            )
        )
        return
    if source_map is None:
        return
    for node_id in _unique(_strings(source_node_ids)):
        trace = trace_legal_ir_fact(source_map, node_id)
        if not trace.traceable:
            diagnostics.append(
                _diagnostic(
                    LegalIRSymbolDiagnosticType.SOURCE_PROVENANCE_UNTRACEABLE,
                    "Symbol-table source-map provenance is not traceable.",
                    reference_id=reference_id,
                    symbol_ids=tuple(_strings(symbol_ids)),
                    alias_ids=tuple(_strings(alias_ids)),
                    scope_id=scope_id,
                    source_node_ids=(node_id,),
                    severity="error",
                )
            )


def _source_map(value: LegalIRSourceMap | Mapping[str, Any]) -> LegalIRSourceMap:
    return value if isinstance(value, LegalIRSourceMap) else LegalIRSourceMap.from_dict(_mapping(value))


def _symbol_table(value: LegalIRSymbolTable | Mapping[str, Any]) -> LegalIRSymbolTable:
    return value if isinstance(value, LegalIRSymbolTable) else LegalIRSymbolTable.from_dict(_mapping(value))


def _definition_payload(item: Any) -> dict[str, Any]:
    if isinstance(item, Mapping):
        return dict(item)
    if isinstance(item, str):
        return {"name": item}
    return _payload_mapping(item)


def _payload_mapping(value: Mapping[str, Any] | Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        try:
            converted = to_dict()
            if isinstance(converted, Mapping):
                return dict(converted)
        except (TypeError, ValueError):
            return {}
    return {}


def _source_node_ids(payload: Mapping[str, Any]) -> tuple[str, ...]:
    ids: list[str] = []
    for key in ("source_node_id", "node_id", "formula_id", "source_node_ids", "provenance_ids"):
        ids.extend(_strings(payload.get(key, ())))
    return tuple(_unique(ids))


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _sequence(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray, str)):
        return list(value)
    return [value]


def _strings(value: Any) -> list[str]:
    return [str(item) for item in _sequence(value) if str(item or "")]


def _unique(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(str(value) for value in values if str(value or "")))


def _unique_records(values: Iterable[Any]) -> tuple[Any, ...]:
    by_key: dict[str, Any] = {}
    for value in values:
        key = str(
            getattr(value, "scope_id", "")
            or getattr(value, "symbol_id", "")
            or getattr(value, "alias_id", "")
            or getattr(value, "reference_id", "")
            or _stable_hash(getattr(value, "to_dict", lambda: str(value))())
        )
        by_key[key] = value
    return tuple(by_key[key] for key in sorted(by_key))


def _stable_json(value: Any) -> str:
    return json.dumps(value, default=str, ensure_ascii=True, separators=(",", ":"), sort_keys=True)


def _stable_hash(value: Any) -> str:
    return hashlib.sha256(_stable_json(value).encode("utf-8")).hexdigest()


def _canonical_json_value(value: Any) -> Any:
    return json.loads(_stable_json(value))


def _scope_kind(value: Any) -> LegalIRScopeKind:
    try:
        return value if isinstance(value, LegalIRScopeKind) else LegalIRScopeKind(str(value or "global"))
    except ValueError:
        return LegalIRScopeKind.GLOBAL


def _symbol_kind(value: Any) -> LegalIRSymbolKind:
    try:
        return value if isinstance(value, LegalIRSymbolKind) else LegalIRSymbolKind(str(value or "unknown"))
    except ValueError:
        aliases = {
            "definition": LegalIRSymbolKind.DEFINED_TERM,
            "defined": LegalIRSymbolKind.DEFINED_TERM,
            "term": LegalIRSymbolKind.DEFINED_TERM,
            "person": LegalIRSymbolKind.ACTOR,
            "party": LegalIRSymbolKind.ACTOR,
            "agency": LegalIRSymbolKind.ACTOR,
            "jurisdiction": LegalIRSymbolKind.AUTHORITY,
            "deadline": LegalIRSymbolKind.CONDITION,
        }
        return aliases.get(str(value or "").lower(), LegalIRSymbolKind.UNKNOWN)


def _resolution_status(value: Any) -> LegalIRResolutionStatus:
    try:
        return value if isinstance(value, LegalIRResolutionStatus) else LegalIRResolutionStatus(str(value or "unresolved"))
    except ValueError:
        return LegalIRResolutionStatus.UNRESOLVED


def _diagnostic_type(value: Any) -> LegalIRSymbolDiagnosticType:
    try:
        return value if isinstance(value, LegalIRSymbolDiagnosticType) else LegalIRSymbolDiagnosticType(str(value or "unresolved_symbol"))
    except ValueError:
        return LegalIRSymbolDiagnosticType.UNRESOLVED_SYMBOL


def _diagnostic(
    diagnostic_type: LegalIRSymbolDiagnosticType,
    message: str,
    *,
    severity: str = "error",
    reference_id: str = "",
    symbol_ids: Sequence[str] = (),
    alias_ids: Sequence[str] = (),
    scope_id: str = "",
    document_id: str = "",
    source_node_ids: Sequence[str] = (),
    source_span_ids: Sequence[str] = (),
    field_path: str = "",
) -> LegalIRSymbolDiagnostic:
    return LegalIRSymbolDiagnostic(
        diagnostic_type=diagnostic_type,
        message=message,
        severity=severity,
        reference_id=reference_id,
        symbol_ids=tuple(_unique(_strings(symbol_ids))),
        alias_ids=tuple(_unique(_strings(alias_ids))),
        scope_id=scope_id,
        document_id=document_id,
        source_node_ids=tuple(_unique(_strings(source_node_ids))),
        source_span_ids=tuple(_unique(_strings(source_span_ids))),
        field_path=field_path,
    )


def _dedupe_diagnostics(diagnostics: Iterable[LegalIRSymbolDiagnostic]) -> tuple[LegalIRSymbolDiagnostic, ...]:
    return tuple(
        {
            (
                item.diagnostic_type.value,
                item.reference_id,
                item.symbol_ids,
                item.alias_ids,
                item.scope_id,
                item.field_path,
                item.message,
                item.severity,
            ): item
            for item in diagnostics
        }.values()
    )


def _duplicate_diagnostic(
    kind: str,
    ids: Sequence[str],
    diagnostics: list[LegalIRSymbolDiagnostic],
    diagnostic_type: LegalIRSymbolDiagnosticType,
) -> None:
    seen: set[str] = set()
    for item in ids:
        if item in seen:
            diagnostics.append(_diagnostic(diagnostic_type, f"Duplicate {kind} ID {item!r}.", field_path=kind))
        seen.add(item)


def _external_definition(
    symbol_id: str,
    tables: Sequence[LegalIRSymbolTable],
) -> LegalIRSymbolDefinition | None:
    for table in tables:
        definition = table.definition_by_id.get(symbol_id)
        if definition is not None:
            return definition
    return None


def _external_definition_exists(symbol_id: str, tables: Sequence[LegalIRSymbolTable]) -> bool:
    return _external_definition(symbol_id, tables) is not None


def _fact_trace_from_dict(data: Mapping[str, Any]) -> LegalIRFactTrace:
    return LegalIRFactTrace(
        fact_id=str(data.get("fact_id") or ""),
        found=bool(data.get("found")),
        derived=bool(data.get("derived")),
        source_spans=tuple(
            LegalIRProvenanceSpan.from_dict(_mapping(item))
            for item in data.get("source_spans", []) or []
        ),
        transformation_steps=tuple(
            LegalIRSourceMapTransform.from_dict(_mapping(item))
            for item in data.get("transformation_steps", []) or []
        ),
        visited_node_ids=tuple(_unique(_strings(data.get("visited_node_ids", ())))),
        issues=tuple(
            LegalIRSourceMapIssue(
                code=str(_mapping(item).get("code") or ""),
                message=str(_mapping(item).get("message") or ""),
                field_path=str(_mapping(item).get("field_path") or ""),
                severity=str(_mapping(item).get("severity") or "error"),
            )
            for item in data.get("issues", []) or []
        ),
    )


__all__ = [
    "LEGAL_IR_SYMBOL_TABLE_SCHEMA_VERSION",
    "LegalIRResolutionStatus",
    "LegalIRScopeKind",
    "LegalIRSymbolAlias",
    "LegalIRSymbolDefinition",
    "LegalIRSymbolDiagnostic",
    "LegalIRSymbolDiagnosticType",
    "LegalIRSymbolKind",
    "LegalIRSymbolReference",
    "LegalIRSymbolResolution",
    "LegalIRSymbolScope",
    "LegalIRSymbolTable",
    "LegalIRSymbolTableBuilder",
    "LegalIRSymbolTableValidationResult",
    "assert_legal_ir_symbols_resolved",
    "build_legal_ir_symbol_table",
    "merge_legal_ir_symbol_tables",
    "normalize_legal_symbol_name",
    "resolve_legal_ir_symbol",
    "validate_legal_ir_symbol_table",
]
