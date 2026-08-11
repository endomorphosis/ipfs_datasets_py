"""Closed, deterministic records for the incremental semantic index.

This module intentionally contains value objects only.  It is the durable
boundary between extraction, graph construction, invalidation, and storage;
all records therefore have closed schemas and canonical collection ordering.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import posixpath
import unicodedata
from typing import Any, ClassVar, Iterable, Mapping, Sequence

from ipfs_datasets_py.logic.software_contracts.content import (
    cid_for_structured,
    validate_cid,
    validate_structured_value,
)


SEMANTIC_INDEX_SCHEMA = "ipfs-datasets.software-contracts.semantic-index@1"
SOURCE_SPAN_SCHEMA = "ipfs-datasets.software-contracts.semantic-source-span@1"
ARTIFACT_SCHEMA = "ipfs-datasets.software-contracts.semantic-artifact@1"
SYMBOL_SCHEMA = "ipfs-datasets.software-contracts.semantic-symbol@1"
EDGE_SCHEMA = "ipfs-datasets.software-contracts.semantic-edge@1"
STATE_SCHEMA = "ipfs-datasets.software-contracts.semantic-repository-state@1"
DELTA_SCHEMA = "ipfs-datasets.software-contracts.semantic-repository-delta@1"
OBLIGATION_SCHEMA = "ipfs-datasets.software-contracts.semantic-obligation@1"
PLAN_SCHEMA = "ipfs-datasets.software-contracts.semantic-invalidation-plan@1"
SYMBOL_EXPLANATION_SCHEMA = "ipfs-datasets.software-contracts.semantic-symbol-explanation@1"
IMPACT_EXPLANATION_SCHEMA = "ipfs-datasets.software-contracts.semantic-impact-explanation@1"


class SemanticIndexModelError(ValueError):
    """Raised when a semantic-index durable record is malformed."""


class AnalysisConfidence(str, Enum):
    EXACT = "exact"
    CONSERVATIVE = "conservative"
    HEURISTIC = "heuristic"
    OPAQUE = "opaque"


class SymbolKind(str, Enum):
    MODULE = "module"
    CLASS = "class"
    FUNCTION = "function"
    ASYNC_FUNCTION = "async_function"
    METHOD = "method"
    PROPERTY = "property"
    VARIABLE = "variable"
    CONSTANT = "constant"
    PARAMETER = "parameter"
    TYPE_ALIAS = "type_alias"
    DATACLASS = "dataclass"
    TYPED_DICT = "typed_dict"
    ENUM = "enum"
    TEST = "test"
    FIXTURE = "fixture"
    ARTIFACT = "artifact"
    UNKNOWN = "unknown"


class RelationType(str, Enum):
    IMPORTS = "imports"
    CALLS = "calls"
    INHERITS = "inherits"
    IMPLEMENTS = "implements"
    READS_STATE = "reads_state"
    WRITES_STATE = "writes_state"
    RAISES = "raises"
    CATCHES = "catches"
    SERIALIZES = "serializes"
    DESERIALIZES = "deserializes"
    VALIDATES = "validates"
    TESTED_BY = "tested_by"
    USES_FIXTURE = "uses_fixture"
    CONFIGURED_BY = "configured_by"
    GENERATED_FROM = "generated_from"
    PROOF_DEPENDS_ON = "proof_depends_on"


def _text(value: Any, name: str, *, empty: bool = False) -> str:
    if type(value) is not str or (not empty and not value):
        raise SemanticIndexModelError(f"{name} must be a nonempty string")
    if value != value.strip() or unicodedata.normalize("NFC", value) != value:
        raise SemanticIndexModelError(f"{name} must be trimmed NFC text")
    if len(value) > 16_384 or any(not char.isprintable() for char in value):
        raise SemanticIndexModelError(f"{name} contains invalid text")
    return value


def _path(value: Any, name: str = "path") -> str:
    text = _text(value, name)
    normalized = posixpath.normpath(text.replace("\\", "/"))
    if normalized in {".", ".."} or normalized.startswith("../") or normalized.startswith("/"):
        raise SemanticIndexModelError(f"{name} must be a repository-relative path")
    return normalized


def _enum(value: Any, enum_type: type[Enum], name: str) -> str:
    try:
        return enum_type(value).value
    except (TypeError, ValueError) as exc:
        raise SemanticIndexModelError(f"{name} has unsupported value {value!r}") from exc


def _cid(value: Any, name: str) -> str:
    try:
        return validate_cid(value)
    except Exception as exc:
        raise SemanticIndexModelError(f"{name} must be a valid CID") from exc


def _mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise SemanticIndexModelError(f"{name} must be a mapping")
    result = dict(value)
    try:
        validate_structured_value(result)
    except Exception as exc:
        raise SemanticIndexModelError(f"{name} must be strict DAG-JSON") from exc
    return result


def _closed(data: Mapping[str, Any], fields: frozenset[str], name: str) -> dict[str, Any]:
    if not isinstance(data, Mapping):
        raise SemanticIndexModelError(f"{name} must be a mapping")
    actual = set(data)
    if actual != fields:
        raise SemanticIndexModelError(
            f"{name} fields must be exactly {sorted(fields)}, got {sorted(actual)}"
        )
    return dict(data)


def _unique_sorted(values: Iterable[str], name: str) -> tuple[str, ...]:
    ordered = tuple(sorted(_text(value, name) for value in values))
    if len(ordered) != len(set(ordered)):
        raise SemanticIndexModelError(f"{name} must not contain duplicates")
    return ordered


@dataclass(frozen=True, slots=True)
class SourceSpan:
    path: str
    start_line: int
    start_column: int
    end_line: int
    end_column: int

    _FIELDS: ClassVar[frozenset[str]] = frozenset({"schema", "path", "start_line", "start_column", "end_line", "end_column"})

    def __post_init__(self) -> None:
        object.__setattr__(self, "path", _path(self.path))
        for name in ("start_line", "start_column", "end_line", "end_column"):
            value = getattr(self, name)
            if type(value) is not int or value < 0:
                raise SemanticIndexModelError(f"{name} must be a nonnegative integer")
        if (self.end_line, self.end_column) < (self.start_line, self.start_column):
            raise SemanticIndexModelError("source span end must not precede start")

    def to_dict(self) -> dict[str, Any]:
        return {"schema": SOURCE_SPAN_SCHEMA, "path": self.path, "start_line": self.start_line, "start_column": self.start_column, "end_line": self.end_line, "end_column": self.end_column}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SourceSpan":
        value = _closed(data, cls._FIELDS, cls.__name__)
        if value.pop("schema") != SOURCE_SPAN_SCHEMA:
            raise SemanticIndexModelError("unsupported SourceSpan schema")
        return cls(**value)


@dataclass(frozen=True, slots=True)
class ArtifactRecord:
    artifact_id: str
    kind: str
    path: str
    source_cid: str | None = None
    confidence: AnalysisConfidence | str = AnalysisConfidence.EXACT
    metadata: Mapping[str, Any] = field(default_factory=dict)

    _FIELDS: ClassVar[frozenset[str]] = frozenset({"schema", "artifact_id", "kind", "path", "source_cid", "confidence", "metadata"})

    def __post_init__(self) -> None:
        object.__setattr__(self, "artifact_id", _text(self.artifact_id, "artifact_id"))
        object.__setattr__(self, "kind", _text(self.kind, "kind"))
        object.__setattr__(self, "path", _path(self.path))
        if self.source_cid is not None:
            object.__setattr__(self, "source_cid", _cid(self.source_cid, "source_cid"))
        object.__setattr__(self, "confidence", _enum(self.confidence, AnalysisConfidence, "confidence"))
        object.__setattr__(self, "metadata", _mapping(self.metadata, "metadata"))

    def to_dict(self) -> dict[str, Any]:
        return {"schema": ARTIFACT_SCHEMA, "artifact_id": self.artifact_id, "kind": self.kind, "path": self.path, "source_cid": self.source_cid, "confidence": self.confidence, "metadata": dict(sorted(self.metadata.items()))}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ArtifactRecord":
        value = _closed(data, cls._FIELDS, cls.__name__)
        if value.pop("schema") != ARTIFACT_SCHEMA:
            raise SemanticIndexModelError("unsupported ArtifactRecord schema")
        return cls(**value)


@dataclass(frozen=True, slots=True)
class SymbolRecord:
    stable_id: str
    version_cid: str
    repository_id: str
    language: str
    module_path: str
    qualified_name: str
    kind: SymbolKind | str
    namespace: str
    source_cid: str | None = None
    span: SourceSpan | None = None
    confidence: AnalysisConfidence | str = AnalysisConfidence.EXACT
    signature: Mapping[str, Any] = field(default_factory=dict)
    decorators: Sequence[str] = ()
    annotations: Mapping[str, Any] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    _FIELDS: ClassVar[frozenset[str]] = frozenset({"schema", "stable_id", "version_cid", "repository_id", "language", "module_path", "qualified_name", "kind", "namespace", "source_cid", "span", "confidence", "signature", "decorators", "annotations", "metadata"})

    def __post_init__(self) -> None:
        for name in ("stable_id", "version_cid"):
            object.__setattr__(self, name, _cid(getattr(self, name), name))
        object.__setattr__(self, "repository_id", _text(self.repository_id, "repository_id"))
        object.__setattr__(self, "language", _text(self.language, "language"))
        object.__setattr__(self, "module_path", _path(self.module_path, "module_path"))
        object.__setattr__(self, "qualified_name", _text(self.qualified_name, "qualified_name"))
        object.__setattr__(self, "kind", _enum(self.kind, SymbolKind, "kind"))
        object.__setattr__(self, "namespace", _text(self.namespace, "namespace"))
        if self.source_cid is not None:
            object.__setattr__(self, "source_cid", _cid(self.source_cid, "source_cid"))
        if self.span is not None and not isinstance(self.span, SourceSpan):
            raise SemanticIndexModelError("span must be a SourceSpan or None")
        object.__setattr__(self, "confidence", _enum(self.confidence, AnalysisConfidence, "confidence"))
        object.__setattr__(self, "signature", _mapping(self.signature, "signature"))
        object.__setattr__(self, "decorators", _unique_sorted(self.decorators, "decorator"))
        object.__setattr__(self, "annotations", _mapping(self.annotations, "annotations"))
        object.__setattr__(self, "metadata", _mapping(self.metadata, "metadata"))

    def to_dict(self) -> dict[str, Any]:
        return {"schema": SYMBOL_SCHEMA, "stable_id": self.stable_id, "version_cid": self.version_cid, "repository_id": self.repository_id, "language": self.language, "module_path": self.module_path, "qualified_name": self.qualified_name, "kind": self.kind, "namespace": self.namespace, "source_cid": self.source_cid, "span": None if self.span is None else self.span.to_dict(), "confidence": self.confidence, "signature": dict(sorted(self.signature.items())), "decorators": list(self.decorators), "annotations": dict(sorted(self.annotations.items())), "metadata": dict(sorted(self.metadata.items()))}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SymbolRecord":
        value = _closed(data, cls._FIELDS, cls.__name__)
        if value.pop("schema") != SYMBOL_SCHEMA:
            raise SemanticIndexModelError("unsupported SymbolRecord schema")
        if value["span"] is not None:
            value["span"] = SourceSpan.from_dict(value["span"])
        return cls(**value)


@dataclass(frozen=True, slots=True)
class DependencyEdge:
    source_id: str
    target_id: str
    relation: RelationType | str
    extraction_method: str
    confidence: AnalysisConfidence | str
    extractor_version: str
    span: SourceSpan | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    _FIELDS: ClassVar[frozenset[str]] = frozenset({"schema", "edge_id", "source_id", "target_id", "relation", "extraction_method", "confidence", "extractor_version", "span", "metadata"})

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_id", _text(self.source_id, "source_id"))
        object.__setattr__(self, "target_id", _text(self.target_id, "target_id"))
        object.__setattr__(self, "relation", _enum(self.relation, RelationType, "relation"))
        object.__setattr__(self, "extraction_method", _text(self.extraction_method, "extraction_method"))
        object.__setattr__(self, "confidence", _enum(self.confidence, AnalysisConfidence, "confidence"))
        object.__setattr__(self, "extractor_version", _text(self.extractor_version, "extractor_version"))
        if self.span is not None and not isinstance(self.span, SourceSpan):
            raise SemanticIndexModelError("span must be a SourceSpan or None")
        object.__setattr__(self, "metadata", _mapping(self.metadata, "metadata"))

    @property
    def edge_id(self) -> str:
        return cid_for_structured(self.identity_payload())

    def identity_payload(self) -> dict[str, Any]:
        return {"schema": EDGE_SCHEMA, "source_id": self.source_id, "target_id": self.target_id, "relation": self.relation, "extraction_method": self.extraction_method, "confidence": self.confidence, "extractor_version": self.extractor_version, "span": None if self.span is None else self.span.to_dict(), "metadata": dict(sorted(self.metadata.items()))}

    def to_dict(self) -> dict[str, Any]:
        value = self.identity_payload()
        value["edge_id"] = self.edge_id
        return value

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "DependencyEdge":
        value = _closed(data, cls._FIELDS, cls.__name__)
        edge_id = value.pop("edge_id")
        if value.pop("schema") != EDGE_SCHEMA:
            raise SemanticIndexModelError("unsupported DependencyEdge schema")
        if value["span"] is not None:
            value["span"] = SourceSpan.from_dict(value["span"])
        result = cls(**value)
        if edge_id != result.edge_id:
            raise SemanticIndexModelError("DependencyEdge edge_id does not verify")
        return result


def _sorted_records(values: Iterable[Any], attribute: str, name: str) -> tuple[Any, ...]:
    result = tuple(sorted(values, key=lambda item: getattr(item, attribute)))
    if len({getattr(item, attribute) for item in result}) != len(result):
        raise SemanticIndexModelError(f"{name} must not contain duplicate {attribute}s")
    return result


@dataclass(frozen=True, slots=True)
class RepositoryState:
    repository_id: str
    symbols: Sequence[SymbolRecord] = ()
    artifacts: Sequence[ArtifactRecord] = ()
    edges: Sequence[DependencyEdge] = ()
    extractor_name: str = "semantic-index"
    extractor_version: str = "1"
    schema: str = SEMANTIC_INDEX_SCHEMA

    _FIELDS: ClassVar[frozenset[str]] = frozenset({"schema", "repository_id", "symbols", "artifacts", "edges", "extractor_name", "extractor_version", "state_cid"})

    def __post_init__(self) -> None:
        object.__setattr__(self, "repository_id", _text(self.repository_id, "repository_id"))
        if self.schema != SEMANTIC_INDEX_SCHEMA:
            raise SemanticIndexModelError("unsupported RepositoryState schema")
        object.__setattr__(self, "extractor_name", _text(self.extractor_name, "extractor_name"))
        object.__setattr__(self, "extractor_version", _text(self.extractor_version, "extractor_version"))
        if any(not isinstance(item, SymbolRecord) for item in self.symbols): raise SemanticIndexModelError("symbols must be SymbolRecords")
        if any(not isinstance(item, ArtifactRecord) for item in self.artifacts): raise SemanticIndexModelError("artifacts must be ArtifactRecords")
        if any(not isinstance(item, DependencyEdge) for item in self.edges): raise SemanticIndexModelError("edges must be DependencyEdges")
        object.__setattr__(self, "symbols", _sorted_records(self.symbols, "stable_id", "symbols"))
        object.__setattr__(self, "artifacts", _sorted_records(self.artifacts, "artifact_id", "artifacts"))
        object.__setattr__(self, "edges", _sorted_records(self.edges, "edge_id", "edges"))

    def identity_payload(self) -> dict[str, Any]:
        return {"schema": STATE_SCHEMA, "repository_id": self.repository_id, "symbols": [item.to_dict() for item in self.symbols], "artifacts": [item.to_dict() for item in self.artifacts], "edges": [item.to_dict() for item in self.edges], "extractor_name": self.extractor_name, "extractor_version": self.extractor_version, "semantic_index_schema": self.schema}

    @property
    def state_cid(self) -> str: return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        return {"schema": self.schema, "repository_id": self.repository_id, "symbols": [item.to_dict() for item in self.symbols], "artifacts": [item.to_dict() for item in self.artifacts], "edges": [item.to_dict() for item in self.edges], "extractor_name": self.extractor_name, "extractor_version": self.extractor_version, "state_cid": self.state_cid}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RepositoryState":
        value = _closed(data, cls._FIELDS, cls.__name__)
        state_cid = value.pop("state_cid")
        value["symbols"] = tuple(SymbolRecord.from_dict(item) for item in value["symbols"])
        value["artifacts"] = tuple(ArtifactRecord.from_dict(item) for item in value["artifacts"])
        value["edges"] = tuple(DependencyEdge.from_dict(item) for item in value["edges"])
        result = cls(**value)
        if state_cid != result.state_cid: raise SemanticIndexModelError("RepositoryState state_cid does not verify")
        return result


@dataclass(frozen=True, slots=True)
class RepositoryStateDelta:
    previous_state_cid: str
    current_state_cid: str
    added_symbol_ids: Sequence[str] = ()
    deleted_symbol_ids: Sequence[str] = ()
    modified_symbol_ids: Sequence[str] = ()
    unchanged_symbol_ids: Sequence[str] = ()
    rename_candidates: Sequence[Mapping[str, Any]] = ()
    added_artifact_ids: Sequence[str] = ()
    deleted_artifact_ids: Sequence[str] = ()
    modified_artifact_ids: Sequence[str] = ()
    added_edge_ids: Sequence[str] = ()
    deleted_edge_ids: Sequence[str] = ()

    _FIELDS: ClassVar[frozenset[str]] = frozenset({"schema", "previous_state_cid", "current_state_cid", "added_symbol_ids", "deleted_symbol_ids", "modified_symbol_ids", "unchanged_symbol_ids", "rename_candidates", "added_artifact_ids", "deleted_artifact_ids", "modified_artifact_ids", "added_edge_ids", "deleted_edge_ids", "delta_cid"})

    def __post_init__(self) -> None:
        object.__setattr__(self, "previous_state_cid", _cid(self.previous_state_cid, "previous_state_cid")); object.__setattr__(self, "current_state_cid", _cid(self.current_state_cid, "current_state_cid"))
        for name in ("added_symbol_ids", "deleted_symbol_ids", "modified_symbol_ids", "unchanged_symbol_ids", "added_artifact_ids", "deleted_artifact_ids", "modified_artifact_ids", "added_edge_ids", "deleted_edge_ids"):
            object.__setattr__(self, name, _unique_sorted(getattr(self, name), name))
        candidates = tuple(sorted((_mapping(item, "rename_candidate") for item in self.rename_candidates), key=cid_for_structured))
        object.__setattr__(self, "rename_candidates", candidates)

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": DELTA_SCHEMA,
            "previous_state_cid": self.previous_state_cid,
            "current_state_cid": self.current_state_cid,
            "added_symbol_ids": list(self.added_symbol_ids),
            "deleted_symbol_ids": list(self.deleted_symbol_ids),
            "modified_symbol_ids": list(self.modified_symbol_ids),
            "unchanged_symbol_ids": list(self.unchanged_symbol_ids),
            "rename_candidates": list(self.rename_candidates),
            "added_artifact_ids": list(self.added_artifact_ids),
            "deleted_artifact_ids": list(self.deleted_artifact_ids),
            "modified_artifact_ids": list(self.modified_artifact_ids),
            "added_edge_ids": list(self.added_edge_ids),
            "deleted_edge_ids": list(self.deleted_edge_ids),
        }

    @property
    def delta_cid(self) -> str: return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        value = self.identity_payload(); value["delta_cid"] = self.delta_cid; return value

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RepositoryStateDelta":
        value = _closed(data, cls._FIELDS, cls.__name__); claimed = value.pop("delta_cid")
        if value.pop("schema") != DELTA_SCHEMA:
            raise SemanticIndexModelError("unsupported RepositoryStateDelta schema")
        result = cls(**value)
        if claimed != result.delta_cid: raise SemanticIndexModelError("RepositoryStateDelta delta_cid does not verify")
        return result


@dataclass(frozen=True, slots=True)
class InvalidationObligation:
    subject_id: str
    reason_code: str
    remediation_kind: str
    confidence: AnalysisConfidence | str
    old_identity: str | None = None
    new_identity: str | None = None
    supporting_edge_ids: Sequence[str] = ()
    details: Mapping[str, Any] = field(default_factory=dict)

    _FIELDS: ClassVar[frozenset[str]] = frozenset({"schema", "obligation_id", "subject_id", "reason_code", "remediation_kind", "confidence", "old_identity", "new_identity", "supporting_edge_ids", "details"})

    def __post_init__(self) -> None:
        for name in ("subject_id", "reason_code", "remediation_kind"): object.__setattr__(self, name, _text(getattr(self, name), name))
        object.__setattr__(self, "confidence", _enum(self.confidence, AnalysisConfidence, "confidence"))
        for name in ("old_identity", "new_identity"):
            if getattr(self, name) is not None: object.__setattr__(self, name, _text(getattr(self, name), name))
        object.__setattr__(self, "supporting_edge_ids", _unique_sorted(self.supporting_edge_ids, "supporting_edge_id")); object.__setattr__(self, "details", _mapping(self.details, "details"))

    @property
    def obligation_id(self) -> str: return cid_for_structured(self.identity_payload())
    def identity_payload(self) -> dict[str, Any]: return {"schema": OBLIGATION_SCHEMA, "subject_id": self.subject_id, "reason_code": self.reason_code, "remediation_kind": self.remediation_kind, "confidence": self.confidence, "old_identity": self.old_identity, "new_identity": self.new_identity, "supporting_edge_ids": list(self.supporting_edge_ids), "details": dict(sorted(self.details.items()))}
    def to_dict(self) -> dict[str, Any]: value = self.identity_payload(); value["obligation_id"] = self.obligation_id; return value
    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "InvalidationObligation":
        value = _closed(data, cls._FIELDS, cls.__name__); claimed = value.pop("obligation_id")
        if value.pop("schema") != OBLIGATION_SCHEMA: raise SemanticIndexModelError("unsupported InvalidationObligation schema")
        result = cls(**value)
        if claimed != result.obligation_id: raise SemanticIndexModelError("InvalidationObligation obligation_id does not verify")
        return result


@dataclass(frozen=True, slots=True)
class InvalidationPlan:
    previous_state_cid: str
    current_state_cid: str
    obligations: Sequence[InvalidationObligation] = ()

    _FIELDS: ClassVar[frozenset[str]] = frozenset({"schema", "previous_state_cid", "current_state_cid", "obligations", "plan_cid"})
    def __post_init__(self) -> None:
        object.__setattr__(self, "previous_state_cid", _cid(self.previous_state_cid, "previous_state_cid")); object.__setattr__(self, "current_state_cid", _cid(self.current_state_cid, "current_state_cid"))
        if any(not isinstance(item, InvalidationObligation) for item in self.obligations): raise SemanticIndexModelError("obligations must be InvalidationObligations")
        object.__setattr__(self, "obligations", _sorted_records(self.obligations, "obligation_id", "obligations"))
    def identity_payload(self) -> dict[str, Any]: return {"schema": PLAN_SCHEMA, "previous_state_cid": self.previous_state_cid, "current_state_cid": self.current_state_cid, "obligations": [item.to_dict() for item in self.obligations]}
    @property
    def plan_cid(self) -> str: return cid_for_structured(self.identity_payload())
    def to_dict(self) -> dict[str, Any]: value = self.identity_payload(); value["plan_cid"] = self.plan_cid; return value
    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "InvalidationPlan":
        value = _closed(data, cls._FIELDS, cls.__name__); claimed = value.pop("plan_cid")
        if value.pop("schema") != PLAN_SCHEMA: raise SemanticIndexModelError("unsupported InvalidationPlan schema")
        value["obligations"] = tuple(InvalidationObligation.from_dict(item) for item in value["obligations"]); result = cls(**value)
        if claimed != result.plan_cid: raise SemanticIndexModelError("InvalidationPlan plan_cid does not verify")
        return result


@dataclass(frozen=True, slots=True)
class SymbolExplanation:
    symbol_id: str
    state_cid: str
    symbol: SymbolRecord
    outgoing_edges: Sequence[DependencyEdge] = ()
    incoming_edges: Sequence[DependencyEdge] = ()
    limitations: Sequence[str] = ()
    _FIELDS: ClassVar[frozenset[str]] = frozenset({"schema", "symbol_id", "state_cid", "symbol", "outgoing_edges", "incoming_edges", "limitations"})
    def __post_init__(self) -> None:
        object.__setattr__(self, "symbol_id", _text(self.symbol_id, "symbol_id")); object.__setattr__(self, "state_cid", _cid(self.state_cid, "state_cid"))
        if not isinstance(self.symbol, SymbolRecord) or self.symbol.stable_id != self.symbol_id: raise SemanticIndexModelError("symbol must match symbol_id")
        if any(not isinstance(item, DependencyEdge) for item in (*self.outgoing_edges, *self.incoming_edges)): raise SemanticIndexModelError("explanation edges must be DependencyEdges")
        object.__setattr__(self, "outgoing_edges", _sorted_records(self.outgoing_edges, "edge_id", "outgoing_edges")); object.__setattr__(self, "incoming_edges", _sorted_records(self.incoming_edges, "edge_id", "incoming_edges")); object.__setattr__(self, "limitations", _unique_sorted(self.limitations, "limitation"))
    def to_dict(self) -> dict[str, Any]: return {"schema": SYMBOL_EXPLANATION_SCHEMA, "symbol_id": self.symbol_id, "state_cid": self.state_cid, "symbol": self.symbol.to_dict(), "outgoing_edges": [item.to_dict() for item in self.outgoing_edges], "incoming_edges": [item.to_dict() for item in self.incoming_edges], "limitations": list(self.limitations)}
    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SymbolExplanation":
        value = _closed(data, cls._FIELDS, cls.__name__)
        if value.pop("schema") != SYMBOL_EXPLANATION_SCHEMA: raise SemanticIndexModelError("unsupported SymbolExplanation schema")
        value["symbol"] = SymbolRecord.from_dict(value["symbol"]); value["outgoing_edges"] = tuple(DependencyEdge.from_dict(item) for item in value["outgoing_edges"]); value["incoming_edges"] = tuple(DependencyEdge.from_dict(item) for item in value["incoming_edges"]); return cls(**value)


@dataclass(frozen=True, slots=True)
class ImpactExplanation:
    state_cid: str
    changed_symbol_ids: Sequence[str]
    obligations: Sequence[InvalidationObligation] = ()
    traversed_edge_ids: Sequence[str] = ()
    limitations: Sequence[str] = ()
    _FIELDS: ClassVar[frozenset[str]] = frozenset({"schema", "state_cid", "changed_symbol_ids", "obligations", "traversed_edge_ids", "limitations"})
    def __post_init__(self) -> None:
        object.__setattr__(self, "state_cid", _cid(self.state_cid, "state_cid")); object.__setattr__(self, "changed_symbol_ids", _unique_sorted(self.changed_symbol_ids, "changed_symbol_id")); object.__setattr__(self, "traversed_edge_ids", _unique_sorted(self.traversed_edge_ids, "traversed_edge_id")); object.__setattr__(self, "limitations", _unique_sorted(self.limitations, "limitation"))
        if any(not isinstance(item, InvalidationObligation) for item in self.obligations): raise SemanticIndexModelError("obligations must be InvalidationObligations")
        object.__setattr__(self, "obligations", _sorted_records(self.obligations, "obligation_id", "obligations"))
    def to_dict(self) -> dict[str, Any]: return {"schema": IMPACT_EXPLANATION_SCHEMA, "state_cid": self.state_cid, "changed_symbol_ids": list(self.changed_symbol_ids), "obligations": [item.to_dict() for item in self.obligations], "traversed_edge_ids": list(self.traversed_edge_ids), "limitations": list(self.limitations)}
    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ImpactExplanation":
        value = _closed(data, cls._FIELDS, cls.__name__)
        if value.pop("schema") != IMPACT_EXPLANATION_SCHEMA: raise SemanticIndexModelError("unsupported ImpactExplanation schema")
        value["obligations"] = tuple(InvalidationObligation.from_dict(item) for item in value["obligations"]); return cls(**value)
