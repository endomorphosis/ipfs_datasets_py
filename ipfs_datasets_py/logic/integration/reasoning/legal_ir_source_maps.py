"""Lossless source maps and provenance spans for LegalIR artifacts.

Most LegalIR payloads intentionally carry only stable identifiers so training,
Hammer, and diagnostics do not copy legal source text.  This module is the
separate lossless provenance ledger: it keeps source documents and normalized
spans, records compiler/decompiler/proof transformations, and lets source-free
artifacts prove that each emitted fact is either traceable to a source span or
explicitly marked as derived.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any, Final


LEGAL_IR_SOURCE_MAP_SCHEMA_VERSION: Final = "legal-ir-source-map-v1"

_TOKEN_RE = re.compile(r"\S+")
_ID_KEYS = frozenset(
    {
        "candidate_id",
        "decompiler_repair_id",
        "diagnostic_id",
        "distillation_id",
        "fact_id",
        "formula_id",
        "frame_id",
        "graph_id",
        "guidance_id",
        "input_formula_id",
        "issue_id",
        "node_id",
        "obligation_id",
        "promotion_id",
        "receipt_id",
        "record_id",
        "repair_id",
        "route_id",
        "source_export_id",
        "telemetry_id",
        "todo_id",
        "translation_id",
    }
)
_ID_LIST_KEYS = frozenset(
    {
        "derived_from_node_ids",
        "diagnostic_ids",
        "emitted_fact_ids",
        "formula_ids",
        "input_node_ids",
        "node_ids",
        "obligation_ids",
        "output_node_ids",
        "proof_receipt_ids",
        "provenance_ids",
        "receipt_ids",
        "source_node_ids",
        "translation_record_ids",
    }
)
_NON_FACT_ID_KEYS = frozenset(
    {
        "cache_key",
        "checker",
        "compiler_commit",
        "contract_id",
        "schema_version",
        "schema_version_id",
        "source_document_id",
        "source_map_id",
        "span_id",
        "transform_id",
        "transformation_step_id",
    }
)


class LegalIRTransformationKind(str, Enum):
    """Stable categories for source-map transformation edges."""

    COMPILER = "compiler"
    DECOMPILER = "decompiler"
    HAMMER = "hammer"
    LEARNED_GUIDANCE = "learned_guidance"
    DIAGNOSTIC = "diagnostic"
    NORMALIZATION = "normalization"
    SOURCE = "source"
    DERIVED = "derived"


@dataclass(frozen=True)
class LegalIRTokenSpan:
    """Inclusive-exclusive token offsets in a source document."""

    start_token: int
    end_token: int

    def to_dict(self) -> dict[str, int]:
        return {
            "end_token": int(self.end_token),
            "start_token": int(self.start_token),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | Sequence[int]) -> "LegalIRTokenSpan":
        if isinstance(data, Sequence) and not isinstance(data, (bytes, bytearray, str, Mapping)):
            values = list(data)
            return cls(int(values[0] if values else 0), int(values[1] if len(values) > 1 else 0))
        return cls(
            start_token=int(_get(data, "start_token", _get(data, "start", 0)) or 0),
            end_token=int(_get(data, "end_token", _get(data, "end", 0)) or 0),
        )


@dataclass(frozen=True)
class LegalIRSourceDocument:
    """One normalized source document retained by the lossless source map."""

    source_document_id: str
    normalized_text: str
    citation: str
    source_uri: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def normalized_text_sha256(self) -> str:
        return _content_hash(self.normalized_text)

    def to_dict(self) -> dict[str, Any]:
        return {
            "citation": self.citation,
            "metadata": _canonical_json_value(self.metadata),
            "normalized_text": self.normalized_text,
            "normalized_text_sha256": self.normalized_text_sha256,
            "source_document": self.source_document_id,
            "source_document_id": self.source_document_id,
            "source_uri": self.source_uri,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "LegalIRSourceDocument":
        return cls(
            source_document_id=str(
                data.get("source_document_id") or data.get("source_document") or ""
            ),
            normalized_text=str(data.get("normalized_text") or ""),
            citation=str(data.get("citation") or ""),
            source_uri=str(data.get("source_uri") or ""),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass(frozen=True)
class LegalIRProvenanceSpan:
    """Lossless source span attached to one or more LegalIR nodes."""

    span_id: str
    source_document_id: str
    citation: str
    start_offset: int
    end_offset: int
    token_span: LegalIRTokenSpan
    normalized_text: str
    transformation_step_id: str
    decompiler_attribution: str = "not_decompiled"
    source_uri: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def normalized_text_sha256(self) -> str:
        return _content_hash(self.normalized_text)

    def to_dict(self) -> dict[str, Any]:
        return {
            "citation": self.citation,
            "decompiler_attribution": self.decompiler_attribution,
            "end_offset": int(self.end_offset),
            "metadata": _canonical_json_value(self.metadata),
            "normalized_text": self.normalized_text,
            "normalized_text_sha256": self.normalized_text_sha256,
            "offset": {"end": int(self.end_offset), "start": int(self.start_offset)},
            "source_document": self.source_document_id,
            "source_document_id": self.source_document_id,
            "source_uri": self.source_uri,
            "span_id": self.span_id,
            "start_offset": int(self.start_offset),
            "token_span": self.token_span.to_dict(),
            "transformation_step": self.transformation_step_id,
            "transformation_step_id": self.transformation_step_id,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "LegalIRProvenanceSpan":
        offset = _mapping(data.get("offset"))
        return cls(
            span_id=str(data.get("span_id") or ""),
            source_document_id=str(
                data.get("source_document_id") or data.get("source_document") or ""
            ),
            citation=str(data.get("citation") or ""),
            start_offset=int(data.get("start_offset", offset.get("start", 0)) or 0),
            end_offset=int(data.get("end_offset", offset.get("end", 0)) or 0),
            token_span=LegalIRTokenSpan.from_dict(_mapping(data.get("token_span"))),
            normalized_text=str(data.get("normalized_text") or ""),
            transformation_step_id=str(
                data.get("transformation_step_id")
                or data.get("transformation_step")
                or ""
            ),
            decompiler_attribution=str(data.get("decompiler_attribution") or "not_decompiled"),
            source_uri=str(data.get("source_uri") or ""),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass(frozen=True)
class LegalIRSourceMapNode:
    """One emitted LegalIR fact or artifact node."""

    node_id: str
    node_kind: str
    span_ids: tuple[str, ...] = ()
    derived_from_node_ids: tuple[str, ...] = ()
    transform_ids: tuple[str, ...] = ()
    emitted_fact: str = ""
    transformation_step_id: str = ""
    decompiler_attribution: str = "not_decompiled"
    derived: bool = False
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def trace_mode(self) -> str:
        return "derived" if self.derived else "source"

    def to_dict(self) -> dict[str, Any]:
        return {
            "decompiler_attribution": self.decompiler_attribution,
            "derived": bool(self.derived),
            "derived_from_node_ids": list(self.derived_from_node_ids),
            "emitted_fact": self.emitted_fact,
            "metadata": _canonical_json_value(self.metadata),
            "node_id": self.node_id,
            "node_kind": self.node_kind,
            "span_ids": list(self.span_ids),
            "trace_mode": self.trace_mode,
            "transform_ids": list(self.transform_ids),
            "transformation_step": self.transformation_step_id,
            "transformation_step_id": self.transformation_step_id,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "LegalIRSourceMapNode":
        return cls(
            node_id=str(data.get("node_id") or ""),
            node_kind=str(data.get("node_kind") or data.get("kind") or ""),
            span_ids=tuple(_strings(data.get("span_ids", ()))),
            derived_from_node_ids=tuple(_strings(data.get("derived_from_node_ids", ()))),
            transform_ids=tuple(_strings(data.get("transform_ids", ()))),
            emitted_fact=str(data.get("emitted_fact") or ""),
            transformation_step_id=str(
                data.get("transformation_step_id")
                or data.get("transformation_step")
                or ""
            ),
            decompiler_attribution=str(data.get("decompiler_attribution") or "not_decompiled"),
            derived=bool(data.get("derived")),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass(frozen=True)
class LegalIRSourceMapTransform:
    """A provenance-preserving transform edge between source-map nodes."""

    transform_id: str
    transformation_step: str
    transform_kind: LegalIRTransformationKind
    input_node_ids: tuple[str, ...]
    output_node_ids: tuple[str, ...]
    input_span_ids: tuple[str, ...] = ()
    output_span_ids: tuple[str, ...] = ()
    decompiler_attribution: str = "not_decompiled"
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def many_to_one(self) -> bool:
        return len(self.input_node_ids) > 1 and len(self.output_node_ids) == 1

    @property
    def one_to_many(self) -> bool:
        return len(self.input_node_ids) == 1 and len(self.output_node_ids) > 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "decompiler_attribution": self.decompiler_attribution,
            "input_node_ids": list(self.input_node_ids),
            "input_span_ids": list(self.input_span_ids),
            "many_to_one": self.many_to_one,
            "metadata": _canonical_json_value(self.metadata),
            "one_to_many": self.one_to_many,
            "output_node_ids": list(self.output_node_ids),
            "output_span_ids": list(self.output_span_ids),
            "transform_id": self.transform_id,
            "transform_kind": self.transform_kind.value,
            "transformation_step": self.transformation_step,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "LegalIRSourceMapTransform":
        try:
            kind = LegalIRTransformationKind(str(data.get("transform_kind") or ""))
        except ValueError:
            kind = LegalIRTransformationKind.DERIVED
        return cls(
            transform_id=str(data.get("transform_id") or ""),
            transformation_step=str(data.get("transformation_step") or ""),
            transform_kind=kind,
            input_node_ids=tuple(_strings(data.get("input_node_ids", ()))),
            output_node_ids=tuple(_strings(data.get("output_node_ids", ()))),
            input_span_ids=tuple(_strings(data.get("input_span_ids", ()))),
            output_span_ids=tuple(_strings(data.get("output_span_ids", ()))),
            decompiler_attribution=str(data.get("decompiler_attribution") or "not_decompiled"),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass(frozen=True)
class LegalIRSourceMapIssue:
    """One deterministic source-map validation or traceability issue."""

    code: str
    message: str
    field_path: str = ""
    severity: str = "error"

    def to_dict(self) -> dict[str, str]:
        return {
            "code": self.code,
            "field_path": self.field_path,
            "message": self.message,
            "severity": self.severity,
        }


@dataclass(frozen=True)
class LegalIRFactTrace:
    """Recursive trace for one emitted fact."""

    fact_id: str
    found: bool
    derived: bool
    source_spans: tuple[LegalIRProvenanceSpan, ...] = ()
    transformation_steps: tuple[LegalIRSourceMapTransform, ...] = ()
    visited_node_ids: tuple[str, ...] = ()
    issues: tuple[LegalIRSourceMapIssue, ...] = ()

    @property
    def traceable(self) -> bool:
        if not self.found:
            return False
        if any(issue.severity == "error" for issue in self.issues):
            return False
        return bool(self.source_spans) or self.derived

    def to_dict(self) -> dict[str, Any]:
        return {
            "derived": self.derived,
            "fact_id": self.fact_id,
            "found": self.found,
            "issues": [issue.to_dict() for issue in self.issues],
            "source_span_ids": [span.span_id for span in self.source_spans],
            "source_spans": [span.to_dict() for span in self.source_spans],
            "traceable": self.traceable,
            "transformation_steps": [step.to_dict() for step in self.transformation_steps],
            "visited_node_ids": list(self.visited_node_ids),
        }


@dataclass(frozen=True)
class LegalIRSourceMapValidationResult:
    """Validation result for a complete source-map graph."""

    source_map_id: str
    node_count: int
    span_count: int
    transform_count: int
    issues: tuple[LegalIRSourceMapIssue, ...] = ()
    schema_version: str = LEGAL_IR_SOURCE_MAP_SCHEMA_VERSION

    @property
    def valid(self) -> bool:
        return not any(issue.severity == "error" for issue in self.issues)

    def to_dict(self) -> dict[str, Any]:
        return {
            "issues": [issue.to_dict() for issue in self.issues],
            "node_count": int(self.node_count),
            "schema_version": self.schema_version,
            "source_map_id": self.source_map_id,
            "span_count": int(self.span_count),
            "transform_count": int(self.transform_count),
            "valid": self.valid,
        }


@dataclass(frozen=True)
class LegalIRArtifactTraceability:
    """Traceability binding between one artifact and a source map."""

    artifact_id: str
    artifact_kind: str
    emitted_fact_ids: tuple[str, ...]
    traceable_fact_ids: tuple[str, ...]
    derived_fact_ids: tuple[str, ...]
    missing_fact_ids: tuple[str, ...]
    issues: tuple[LegalIRSourceMapIssue, ...] = ()
    schema_version: str = LEGAL_IR_SOURCE_MAP_SCHEMA_VERSION

    @property
    def traceable(self) -> bool:
        return bool(self.emitted_fact_ids) and not self.missing_fact_ids and not any(
            issue.severity == "error" for issue in self.issues
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "artifact_kind": self.artifact_kind,
            "derived_fact_ids": list(self.derived_fact_ids),
            "emitted_fact_ids": list(self.emitted_fact_ids),
            "issues": [issue.to_dict() for issue in self.issues],
            "missing_fact_ids": list(self.missing_fact_ids),
            "schema_version": self.schema_version,
            "traceable": self.traceable,
            "traceable_fact_ids": list(self.traceable_fact_ids),
        }


@dataclass(frozen=True)
class LegalIRSourceMap:
    """Immutable, lossless LegalIR provenance graph."""

    source_map_id: str
    sources: tuple[LegalIRSourceDocument, ...]
    spans: tuple[LegalIRProvenanceSpan, ...]
    nodes: tuple[LegalIRSourceMapNode, ...]
    transforms: tuple[LegalIRSourceMapTransform, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = LEGAL_IR_SOURCE_MAP_SCHEMA_VERSION

    @property
    def source_by_id(self) -> Mapping[str, LegalIRSourceDocument]:
        return {source.source_document_id: source for source in self.sources}

    @property
    def span_by_id(self) -> Mapping[str, LegalIRProvenanceSpan]:
        return {span.span_id: span for span in self.spans}

    @property
    def node_by_id(self) -> Mapping[str, LegalIRSourceMapNode]:
        return {node.node_id: node for node in self.nodes}

    @property
    def transform_by_id(self) -> Mapping[str, LegalIRSourceMapTransform]:
        return {transform.transform_id: transform for transform in self.transforms}

    def to_dict(self) -> dict[str, Any]:
        return {
            "metadata": _canonical_json_value(self.metadata),
            "nodes": [node.to_dict() for node in self.nodes],
            "schema_version": self.schema_version,
            "source_map_id": self.source_map_id,
            "sources": [source.to_dict() for source in self.sources],
            "spans": [span.to_dict() for span in self.spans],
            "transforms": [transform.to_dict() for transform in self.transforms],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "LegalIRSourceMap":
        return cls(
            source_map_id=str(data.get("source_map_id") or ""),
            sources=tuple(
                LegalIRSourceDocument.from_dict(_mapping(item))
                for item in data.get("sources", []) or []
            ),
            spans=tuple(
                LegalIRProvenanceSpan.from_dict(_mapping(item))
                for item in data.get("spans", []) or []
            ),
            nodes=tuple(
                LegalIRSourceMapNode.from_dict(_mapping(item))
                for item in data.get("nodes", []) or []
            ),
            transforms=tuple(
                LegalIRSourceMapTransform.from_dict(_mapping(item))
                for item in data.get("transforms", []) or []
            ),
            metadata=dict(data.get("metadata") or {}),
            schema_version=str(data.get("schema_version") or LEGAL_IR_SOURCE_MAP_SCHEMA_VERSION),
        )


class LegalIRSourceMapBuilder:
    """Mutable builder for a deterministic source-map graph."""

    def __init__(self, *, source_map_id: str = "", metadata: Mapping[str, Any] | None = None) -> None:
        self.source_map_id = source_map_id
        self.metadata = dict(metadata or {})
        self._sources: dict[str, LegalIRSourceDocument] = {}
        self._spans: dict[str, LegalIRProvenanceSpan] = {}
        self._nodes: dict[str, LegalIRSourceMapNode] = {}
        self._transforms: dict[str, LegalIRSourceMapTransform] = {}

    def has_node(self, node_id: str) -> bool:
        return str(node_id or "") in self._nodes

    def add_source_document(
        self,
        source_document_id: str,
        normalized_text: str,
        *,
        citation: str = "",
        source_uri: str = "",
        metadata: Mapping[str, Any] | None = None,
    ) -> LegalIRSourceDocument:
        source = LegalIRSourceDocument(
            source_document_id=str(source_document_id or ""),
            normalized_text=str(normalized_text or ""),
            citation=str(citation or ""),
            source_uri=str(source_uri or ""),
            metadata=dict(metadata or {}),
        )
        self._sources[source.source_document_id] = source
        return source

    def add_span(
        self,
        source_document_id: str,
        start_offset: int,
        end_offset: int,
        *,
        citation: str = "",
        token_span: LegalIRTokenSpan | Mapping[str, Any] | Sequence[int] | None = None,
        normalized_text: str = "",
        transformation_step_id: str = "source_ingest",
        decompiler_attribution: str = "not_decompiled",
        source_uri: str = "",
        metadata: Mapping[str, Any] | None = None,
        span_id: str = "",
    ) -> LegalIRProvenanceSpan:
        source = self._sources.get(str(source_document_id or ""))
        start = max(0, int(start_offset or 0))
        end = max(start, int(end_offset or 0))
        if not normalized_text and source is not None:
            normalized_text = source.normalized_text[start:end]
        if token_span is None:
            token_span = _token_span_for_offsets(source.normalized_text if source else normalized_text, start, end)
        resolved_token_span = (
            token_span
            if isinstance(token_span, LegalIRTokenSpan)
            else LegalIRTokenSpan.from_dict(token_span or {})
        )
        resolved_citation = str(citation or (source.citation if source is not None else ""))
        resolved_source_uri = str(source_uri or (source.source_uri if source is not None else ""))
        payload = {
            "citation": resolved_citation,
            "end_offset": end,
            "normalized_text": normalized_text,
            "source_document_id": source_document_id,
            "start_offset": start,
            "token_span": resolved_token_span.to_dict(),
            "transformation_step_id": transformation_step_id,
        }
        span = LegalIRProvenanceSpan(
            span_id=span_id or "lir-span-" + _stable_hash(payload)[:24],
            source_document_id=str(source_document_id or ""),
            citation=resolved_citation,
            start_offset=start,
            end_offset=end,
            token_span=resolved_token_span,
            normalized_text=str(normalized_text or ""),
            transformation_step_id=str(transformation_step_id or ""),
            decompiler_attribution=str(decompiler_attribution or "not_decompiled"),
            source_uri=resolved_source_uri,
            metadata=dict(metadata or {}),
        )
        self._spans[span.span_id] = span
        return span

    def add_node(
        self,
        node_id: str,
        *,
        node_kind: str,
        span_ids: Sequence[str] = (),
        derived_from_node_ids: Sequence[str] = (),
        transform_ids: Sequence[str] = (),
        emitted_fact: str = "",
        transformation_step_id: str = "",
        decompiler_attribution: str = "not_decompiled",
        derived: bool = False,
        metadata: Mapping[str, Any] | None = None,
    ) -> LegalIRSourceMapNode:
        node = LegalIRSourceMapNode(
            node_id=str(node_id or ""),
            node_kind=str(node_kind or ""),
            span_ids=tuple(_unique(_strings(span_ids))),
            derived_from_node_ids=tuple(_unique(_strings(derived_from_node_ids))),
            transform_ids=tuple(_unique(_strings(transform_ids))),
            emitted_fact=str(emitted_fact or ""),
            transformation_step_id=str(transformation_step_id or ""),
            decompiler_attribution=str(decompiler_attribution or "not_decompiled"),
            derived=bool(derived),
            metadata=dict(metadata or {}),
        )
        self._nodes[node.node_id] = node
        return node

    def add_transform(
        self,
        transformation_step: str,
        transform_kind: LegalIRTransformationKind | str,
        *,
        input_node_ids: Sequence[str],
        output_node_ids: Sequence[str],
        input_span_ids: Sequence[str] = (),
        output_span_ids: Sequence[str] = (),
        decompiler_attribution: str = "not_decompiled",
        metadata: Mapping[str, Any] | None = None,
        transform_id: str = "",
    ) -> LegalIRSourceMapTransform:
        try:
            kind = (
                transform_kind
                if isinstance(transform_kind, LegalIRTransformationKind)
                else LegalIRTransformationKind(str(transform_kind or ""))
            )
        except ValueError:
            kind = LegalIRTransformationKind.DERIVED
        inputs = tuple(_unique(_strings(input_node_ids)))
        outputs = tuple(_unique(_strings(output_node_ids)))
        in_spans = tuple(_unique(_strings(input_span_ids))) or tuple(
            _unique(span for node_id in inputs for span in self._nodes.get(node_id, LegalIRSourceMapNode(node_id, "")).span_ids)
        )
        out_spans = tuple(_unique(_strings(output_span_ids)))
        payload = {
            "input_node_ids": inputs,
            "input_span_ids": in_spans,
            "output_node_ids": outputs,
            "output_span_ids": out_spans,
            "transform_kind": kind.value,
            "transformation_step": transformation_step,
        }
        transform = LegalIRSourceMapTransform(
            transform_id=transform_id or "lir-transform-" + _stable_hash(payload)[:24],
            transformation_step=str(transformation_step or ""),
            transform_kind=kind,
            input_node_ids=inputs,
            output_node_ids=outputs,
            input_span_ids=in_spans,
            output_span_ids=out_spans,
            decompiler_attribution=str(decompiler_attribution or "not_decompiled"),
            metadata=dict(metadata or {}),
        )
        self._transforms[transform.transform_id] = transform
        for node_id in (*inputs, *outputs):
            node = self._nodes.get(node_id)
            if node is not None and transform.transform_id not in node.transform_ids:
                self._nodes[node_id] = replace(
                    node,
                    transform_ids=tuple(_unique((*node.transform_ids, transform.transform_id))),
                )
        return transform

    def add_derived_node(
        self,
        node_id: str,
        *,
        node_kind: str,
        derived_from_node_ids: Sequence[str],
        transformation_step: str,
        transform_kind: LegalIRTransformationKind | str = LegalIRTransformationKind.DERIVED,
        emitted_fact: str = "",
        decompiler_attribution: str = "not_decompiled",
        metadata: Mapping[str, Any] | None = None,
    ) -> LegalIRSourceMapNode:
        node = self.add_node(
            node_id,
            node_kind=node_kind,
            derived_from_node_ids=derived_from_node_ids,
            emitted_fact=emitted_fact,
            transformation_step_id=transformation_step,
            decompiler_attribution=decompiler_attribution,
            derived=True,
            metadata=metadata,
        )
        transform = self.add_transform(
            transformation_step,
            transform_kind,
            input_node_ids=derived_from_node_ids,
            output_node_ids=(node.node_id,),
            decompiler_attribution=decompiler_attribution,
            metadata={"derived": True},
        )
        self._nodes[node.node_id] = replace(
            node,
            transform_ids=tuple(_unique((*node.transform_ids, transform.transform_id))),
        )
        return self._nodes[node.node_id]

    def to_source_map(self) -> LegalIRSourceMap:
        source_map_id = self.source_map_id or "lir-source-map-" + _stable_hash(
            {
                "nodes": sorted(self._nodes),
                "sources": sorted(self._sources),
                "spans": sorted(self._spans),
                "transforms": sorted(self._transforms),
            }
        )[:24]
        return LegalIRSourceMap(
            source_map_id=source_map_id,
            sources=tuple(self._sources[key] for key in sorted(self._sources)),
            spans=tuple(self._spans[key] for key in sorted(self._spans)),
            nodes=tuple(self._nodes[key] for key in sorted(self._nodes)),
            transforms=tuple(self._transforms[key] for key in sorted(self._transforms)),
            metadata=dict(self.metadata),
        )


def build_legal_ir_source_map(sample_or_document: Any) -> LegalIRSourceMap:
    """Build source-map nodes for formula-level compiler output in a sample."""

    document = _document(sample_or_document)
    sample = _mapping(sample_or_document)
    document_payload = _mapping(document)
    source_document_id = str(
        document_payload.get("document_id")
        or sample.get("document_id")
        or sample.get("sample_id")
        or "legal-ir-source"
    )
    normalized_text = str(
        document_payload.get("normalized_text")
        or sample.get("normalized_text")
        or sample.get("text")
        or ""
    )
    citation = str(document_payload.get("citation") or sample.get("citation") or "")
    builder = LegalIRSourceMapBuilder(metadata={"builder": "build_legal_ir_source_map"})
    builder.add_source_document(source_document_id, normalized_text, citation=citation)
    for index, formula in enumerate(_sequence(document_payload.get("formulas")), start=1):
        payload = _mapping(formula)
        formula_id = str(payload.get("formula_id") or f"formula-{index}")
        provenance = _mapping(payload.get("provenance"))
        start = int(provenance.get("start_char", provenance.get("start_offset", 0)) or 0)
        end = int(
            provenance.get(
                "end_char",
                provenance.get("end_offset", len(normalized_text) if normalized_text else start),
            )
            or start
        )
        span = builder.add_span(
            str(provenance.get("source_document_id") or provenance.get("source_id") or source_document_id),
            start,
            end,
            citation=str(provenance.get("citation") or citation),
            transformation_step_id=str(provenance.get("transformation_step") or "compiler.source_span"),
            decompiler_attribution=str(provenance.get("decompiler_attribution") or "not_decompiled"),
            metadata={"formula_id": formula_id},
        )
        builder.add_node(
            formula_id,
            node_kind="compiler_formula",
            span_ids=(span.span_id,),
            emitted_fact=formula_id,
            transformation_step_id="compiler.emit_formula",
            decompiler_attribution=str(provenance.get("decompiler_attribution") or "not_decompiled"),
            metadata={"formula_index": index},
        )
    return builder.to_source_map()


def record_legal_ir_artifact_provenance(
    builder: LegalIRSourceMapBuilder,
    artifact: Mapping[str, Any] | Any,
    *,
    artifact_kind: str = "",
    emitted_fact_ids: Sequence[str] | None = None,
) -> tuple[str, ...]:
    """Record derived nodes for source-free compiler/decompiler/proof artifacts."""

    payload = _payload_mapping(artifact)
    kind = str(artifact_kind or _artifact_kind(payload) or "artifact")

    if "translation_records" in payload or "reconstruction_receipts" in payload or "artifacts" in payload:
        recorded: list[str] = []
        for key, child_kind in (
            ("translation_records", "hammer_translation"),
            ("reconstruction_receipts", "hammer_receipt"),
            ("artifacts", "hammer_guidance"),
            ("route_results", "hammer_route"),
        ):
            for item in _sequence(payload.get(key)):
                recorded.extend(
                    record_legal_ir_artifact_provenance(
                        builder,
                        item,
                        artifact_kind=child_kind,
                    )
                )
        return tuple(_unique(recorded))

    fact_ids = tuple(_unique(_strings(emitted_fact_ids or ()))) or _primary_artifact_ids(payload)
    parent_ids = tuple(
        node_id for node_id in _artifact_parent_ids(payload) if builder.has_node(node_id)
    )
    if not fact_ids:
        return ()
    if not parent_ids:
        for fact_id in fact_ids:
            if not builder.has_node(fact_id):
                builder.add_node(
                    fact_id,
                    node_kind=kind,
                    derived=True,
                    emitted_fact=fact_id,
                    transformation_step_id=f"{kind}.mark_derived",
                    decompiler_attribution=_decompiler_attribution(payload),
                    metadata={"artifact_trace_mode": "derived_without_source_parent"},
                )
        return fact_ids

    for fact_id in fact_ids:
        if not builder.has_node(fact_id):
            builder.add_node(
                fact_id,
                node_kind=kind,
                derived_from_node_ids=parent_ids,
                derived=True,
                emitted_fact=fact_id,
                transformation_step_id=f"{kind}.emit",
                decompiler_attribution=_decompiler_attribution(payload),
                metadata={"artifact_kind": kind},
            )
    builder.add_transform(
        f"{kind}.emit",
        _transform_kind_for_artifact(kind),
        input_node_ids=parent_ids,
        output_node_ids=fact_ids,
        decompiler_attribution=_decompiler_attribution(payload),
        metadata={"artifact_id": _artifact_id(payload), "artifact_kind": kind},
    )
    return fact_ids


def validate_legal_ir_source_map(source_map: LegalIRSourceMap | Mapping[str, Any]) -> LegalIRSourceMapValidationResult:
    """Validate source documents, spans, nodes, transform edges, and traces."""

    source_map = _source_map(source_map)
    issues: list[LegalIRSourceMapIssue] = []
    sources = source_map.source_by_id
    spans = source_map.span_by_id
    nodes = source_map.node_by_id
    transforms = source_map.transform_by_id
    _duplicate_issues("sources", [source.source_document_id for source in source_map.sources], issues)
    _duplicate_issues("spans", [span.span_id for span in source_map.spans], issues)
    _duplicate_issues("nodes", [node.node_id for node in source_map.nodes], issues)
    _duplicate_issues("transforms", [transform.transform_id for transform in source_map.transforms], issues)

    for source in source_map.sources:
        if not source.source_document_id:
            issues.append(_issue("source_document_missing", "Source document has no ID.", "sources.source_document_id"))
        if not source.normalized_text:
            issues.append(_issue("source_normalized_text_missing", "Source document has no normalized text.", f"sources.{source.source_document_id}.normalized_text"))

    for span in source_map.spans:
        path = f"spans.{span.span_id}"
        source = sources.get(span.source_document_id)
        if source is None:
            issues.append(_issue("span_source_missing", "Span references an unknown source document.", f"{path}.source_document_id"))
        if not span.citation:
            issues.append(_issue("span_citation_missing", "Span does not preserve a citation.", f"{path}.citation"))
        if not span.normalized_text:
            issues.append(_issue("span_normalized_text_missing", "Span does not preserve normalized text.", f"{path}.normalized_text"))
        if span.end_offset < span.start_offset:
            issues.append(_issue("span_offsets_invalid", "Span end offset precedes start offset.", f"{path}.offset"))
        if span.token_span.end_token < span.token_span.start_token:
            issues.append(_issue("span_token_offsets_invalid", "Token span end precedes start.", f"{path}.token_span"))
        if not span.transformation_step_id:
            issues.append(_issue("span_transformation_step_missing", "Span has no transformation step.", f"{path}.transformation_step_id"))
        if not span.decompiler_attribution:
            issues.append(_issue("span_decompiler_attribution_missing", "Span has no decompiler attribution marker.", f"{path}.decompiler_attribution"))
        if source is not None and span.end_offset <= len(source.normalized_text):
            expected = source.normalized_text[span.start_offset : span.end_offset]
            if expected != span.normalized_text:
                issues.append(_issue("span_text_mismatch", "Span normalized text does not match source offsets.", f"{path}.normalized_text"))

    for node in source_map.nodes:
        path = f"nodes.{node.node_id}"
        if not node.node_id:
            issues.append(_issue("node_id_missing", "Node has no ID.", path))
        if not node.decompiler_attribution:
            issues.append(_issue("node_decompiler_attribution_missing", "Node has no decompiler attribution marker.", f"{path}.decompiler_attribution"))
        for span_id in node.span_ids:
            if span_id not in spans:
                issues.append(_issue("node_span_missing", "Node references an unknown span.", f"{path}.span_ids"))
        for parent_id in node.derived_from_node_ids:
            if parent_id not in nodes:
                issues.append(_issue("node_parent_missing", "Node references an unknown parent node.", f"{path}.derived_from_node_ids"))
        for transform_id in node.transform_ids:
            if transform_id not in transforms:
                issues.append(_issue("node_transform_missing", "Node references an unknown transform.", f"{path}.transform_ids"))
        if not node.span_ids and not node.derived:
            issues.append(_issue("node_origin_missing", "Node has no source span and is not marked derived.", path))
        if (
            node.derived
            and not node.span_ids
            and not node.derived_from_node_ids
            and not node.transform_ids
            and not node.transformation_step_id
        ):
            issues.append(_issue("derived_node_explanation_missing", "Derived node has no parent or transform explanation.", path))

    for transform in source_map.transforms:
        path = f"transforms.{transform.transform_id}"
        if not transform.transformation_step:
            issues.append(_issue("transform_step_missing", "Transform has no transformation step.", f"{path}.transformation_step"))
        if not transform.output_node_ids:
            issues.append(_issue("transform_outputs_missing", "Transform has no output nodes.", f"{path}.output_node_ids"))
        for node_id in (*transform.input_node_ids, *transform.output_node_ids):
            if node_id not in nodes:
                issues.append(_issue("transform_node_missing", "Transform references an unknown node.", path))
        for span_id in (*transform.input_span_ids, *transform.output_span_ids):
            if span_id not in spans:
                issues.append(_issue("transform_span_missing", "Transform references an unknown span.", path))

    for node in source_map.nodes:
        trace = trace_legal_ir_fact(source_map, node.node_id)
        if not trace.traceable:
            issues.extend(
                trace.issues
                or (
                    _issue(
                        "node_not_traceable",
                        "Node cannot be traced to a source span or a derived marker.",
                        f"nodes.{node.node_id}",
                    ),
                )
            )

    return LegalIRSourceMapValidationResult(
        source_map_id=source_map.source_map_id,
        node_count=len(source_map.nodes),
        span_count=len(source_map.spans),
        transform_count=len(source_map.transforms),
        issues=tuple(_dedupe_issues(issues)),
    )


def trace_legal_ir_fact(source_map: LegalIRSourceMap | Mapping[str, Any], fact_id: str) -> LegalIRFactTrace:
    """Trace one emitted fact recursively through the source-map graph."""

    source_map = _source_map(source_map)
    spans = source_map.span_by_id
    nodes = source_map.node_by_id
    transforms = source_map.transform_by_id
    fact = str(fact_id or "")
    if fact not in nodes:
        return LegalIRFactTrace(
            fact_id=fact,
            found=False,
            derived=False,
            issues=(
                _issue(
                    "fact_not_in_source_map",
                    f"Fact {fact!r} is absent from the LegalIR source map.",
                    "fact_id",
                ),
            ),
        )

    span_ids: list[str] = []
    transform_ids: list[str] = []
    visited: list[str] = []
    issues: list[LegalIRSourceMapIssue] = []
    derived = False

    def visit(node_id: str, stack: tuple[str, ...] = ()) -> None:
        nonlocal derived
        if node_id in stack:
            issues.append(_issue("source_map_cycle", "Source-map derivation cycle detected.", f"nodes.{node_id}"))
            return
        node = nodes.get(node_id)
        if node is None:
            issues.append(_issue("trace_parent_missing", "Trace parent is missing.", f"nodes.{node_id}"))
            return
        visited.append(node_id)
        derived = derived or node.derived
        span_ids.extend(node.span_ids)
        transform_ids.extend(node.transform_ids)
        for transform_id in node.transform_ids:
            transform = transforms.get(transform_id)
            if transform is not None:
                span_ids.extend(transform.input_span_ids)
                span_ids.extend(transform.output_span_ids)
                if node_id in transform.output_node_ids:
                    for parent_id in transform.input_node_ids:
                        if parent_id != node_id:
                            visit(parent_id, (*stack, node_id))
        for parent_id in node.derived_from_node_ids:
            visit(parent_id, (*stack, node_id))

    visit(fact)
    source_spans = tuple(spans[span_id] for span_id in _unique(span_ids) if span_id in spans)
    steps = tuple(transforms[transform_id] for transform_id in _unique(transform_ids) if transform_id in transforms)
    if not source_spans and not derived:
        issues.append(
            _issue(
                "trace_origin_missing",
                "Fact has no source span and is not marked derived.",
                f"nodes.{fact}",
            )
        )
    return LegalIRFactTrace(
        fact_id=fact,
        found=True,
        derived=derived,
        source_spans=source_spans,
        transformation_steps=steps,
        visited_node_ids=tuple(_unique(visited)),
        issues=tuple(_dedupe_issues(issues)),
    )


def extract_legal_ir_emitted_fact_ids(
    artifact: Mapping[str, Any] | Any,
    *,
    artifact_kind: str = "",
) -> tuple[str, ...]:
    """Return stable fact IDs emitted or referenced by a LegalIR artifact."""

    payload = _payload_mapping(artifact)
    explicit = _strings(payload.get("emitted_fact_ids", ()))
    if explicit:
        return tuple(_unique(explicit))
    if artifact_kind:
        primary = _primary_artifact_ids(payload)
        if primary:
            return primary
    ids: list[str] = []
    _collect_ids(payload, ids)
    return tuple(_unique(ids))


def bind_legal_ir_artifact_source_map(
    artifact: Mapping[str, Any] | Any,
    source_map: LegalIRSourceMap | Mapping[str, Any],
    *,
    artifact_kind: str = "",
    emitted_fact_ids: Sequence[str] | None = None,
) -> LegalIRArtifactTraceability:
    """Prove artifact facts are traceable to source or explicitly derived."""

    source_map = _source_map(source_map)
    payload = _payload_mapping(artifact)
    facts = tuple(_unique(_strings(emitted_fact_ids or ()))) or extract_legal_ir_emitted_fact_ids(
        payload,
        artifact_kind=artifact_kind,
    )
    traceable: list[str] = []
    derived: list[str] = []
    missing: list[str] = []
    issues: list[LegalIRSourceMapIssue] = []
    for fact_id in facts:
        trace = trace_legal_ir_fact(source_map, fact_id)
        if trace.traceable:
            traceable.append(fact_id)
            if trace.derived:
                derived.append(fact_id)
        else:
            missing.append(fact_id)
            issues.extend(trace.issues)
    if not facts:
        issues.append(
            _issue(
                "artifact_fact_ids_missing",
                "Artifact has no emitted fact IDs to bind to the LegalIR source map.",
                "artifact",
            )
        )
    return LegalIRArtifactTraceability(
        artifact_id=_artifact_id(payload),
        artifact_kind=str(artifact_kind or _artifact_kind(payload) or ""),
        emitted_fact_ids=facts,
        traceable_fact_ids=tuple(_unique(traceable)),
        derived_fact_ids=tuple(_unique(derived)),
        missing_fact_ids=tuple(_unique(missing)),
        issues=tuple(_dedupe_issues(issues)),
    )


def assert_legal_ir_artifact_traceable(
    artifact: Mapping[str, Any] | Any,
    source_map: LegalIRSourceMap | Mapping[str, Any],
    *,
    artifact_kind: str = "",
    emitted_fact_ids: Sequence[str] | None = None,
) -> LegalIRArtifactTraceability:
    """Return traceability or raise for artifacts with unexplainable facts."""

    binding = bind_legal_ir_artifact_source_map(
        artifact,
        source_map,
        artifact_kind=artifact_kind,
        emitted_fact_ids=emitted_fact_ids,
    )
    if not binding.traceable:
        codes = ",".join(issue.code for issue in binding.issues) or "untraceable"
        raise ValueError(f"LegalIR artifact is not source-map traceable: {codes}")
    return binding


def _source_map(value: LegalIRSourceMap | Mapping[str, Any]) -> LegalIRSourceMap:
    return value if isinstance(value, LegalIRSourceMap) else LegalIRSourceMap.from_dict(_mapping(value))


def _document(sample_or_document: Any) -> Any:
    if isinstance(sample_or_document, Mapping):
        return sample_or_document.get("modal_ir", sample_or_document)
    return getattr(sample_or_document, "modal_ir", sample_or_document)


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


def _get(value: Any, key: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(key, default)
    return getattr(value, key, default)


def _unique(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(str(value) for value in values if str(value or "")))


def _stable_json(value: Any) -> str:
    return json.dumps(
        value,
        default=str,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )


def _stable_hash(value: Any) -> str:
    return hashlib.sha256(_stable_json(value).encode("utf-8")).hexdigest()


def _content_hash(value: str) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()


def _canonical_json_value(value: Any) -> Any:
    return json.loads(_stable_json(value))


def _token_span_for_offsets(text: str, start_offset: int, end_offset: int) -> LegalIRTokenSpan:
    tokens = list(_TOKEN_RE.finditer(str(text or "")))
    if not tokens:
        return LegalIRTokenSpan(0, 0)
    selected = [
        index
        for index, match in enumerate(tokens)
        if match.end() > start_offset and match.start() < end_offset
    ]
    if not selected:
        insertion = sum(1 for match in tokens if match.end() <= start_offset)
        return LegalIRTokenSpan(insertion, insertion)
    return LegalIRTokenSpan(selected[0], selected[-1] + 1)


def _duplicate_issues(kind: str, ids: Sequence[str], issues: list[LegalIRSourceMapIssue]) -> None:
    seen: set[str] = set()
    for item in ids:
        if item in seen:
            issues.append(_issue("duplicate_source_map_id", f"Duplicate {kind} ID {item!r}.", kind))
        seen.add(item)


def _issue(code: str, message: str, field_path: str = "", severity: str = "error") -> LegalIRSourceMapIssue:
    return LegalIRSourceMapIssue(code=code, message=message, field_path=field_path, severity=severity)


def _dedupe_issues(issues: Iterable[LegalIRSourceMapIssue]) -> tuple[LegalIRSourceMapIssue, ...]:
    return tuple({(issue.code, issue.field_path, issue.message, issue.severity): issue for issue in issues}.values())


def _artifact_id(payload: Mapping[str, Any]) -> str:
    for key in (
        "receipt_id",
        "translation_id",
        "guidance_id",
        "diagnostic_id",
        "issue_id",
        "obligation_id",
        "record_id",
        "frame_id",
        "formula_id",
        "source_map_id",
    ):
        value = str(payload.get(key) or "")
        if value:
            return value
    return ""


def _artifact_kind(payload: Mapping[str, Any]) -> str:
    schema = str(payload.get("schema_version") or "")
    if "hammer" in schema:
        return "hammer"
    if "learned-guidance" in schema or payload.get("guidance_id"):
        return "learned_guidance"
    if payload.get("diagnostic_id") or payload.get("issue_id"):
        return "diagnostic"
    if payload.get("decompiler_attribution") or payload.get("source_contract_id"):
        return "decompiler"
    if payload.get("formula_id") or payload.get("frame_id"):
        return "compiler"
    return "artifact"


def _primary_artifact_ids(payload: Mapping[str, Any]) -> tuple[str, ...]:
    ids = []
    for key in (
        "translation_id",
        "receipt_id",
        "guidance_id",
        "diagnostic_id",
        "issue_id",
        "route_id",
        "record_id",
        "obligation_id",
        "frame_id",
        "formula_id",
    ):
        value = str(payload.get(key) or "")
        if value:
            ids.append(value)
    return tuple(_unique(ids))


def _artifact_parent_ids(payload: Mapping[str, Any]) -> tuple[str, ...]:
    ids: list[str] = []
    for key in (
        "input_formula_id",
        "formula_id",
        "obligation_id",
        "source_formula_id",
        "source_node_id",
        "source_export_id",
        "parent_id",
        "node_id",
    ):
        value = str(payload.get(key) or "")
        if value and value not in _primary_artifact_ids(payload):
            ids.append(value)
    for key in (
        "derived_from_node_ids",
        "input_node_ids",
        "proof_receipt_ids",
        "provenance_ids",
        "receipt_ids",
        "source_node_ids",
        "translation_record_ids",
    ):
        ids.extend(_strings(payload.get(key, ())))
    metadata = _mapping(payload.get("metadata"))
    for key in ("formula_id", "input_formula_id", "obligation_id", "source_node_id"):
        value = str(metadata.get(key) or "")
        if value:
            ids.append(value)
    return tuple(_unique(ids))


def _decompiler_attribution(payload: Mapping[str, Any]) -> str:
    return str(
        payload.get("decompiler_attribution")
        or _mapping(payload.get("metadata")).get("decompiler_attribution")
        or ("decompiler" if payload.get("source_contract_id") else "not_decompiled")
    )


def _transform_kind_for_artifact(kind: str) -> LegalIRTransformationKind:
    normalized = str(kind or "").lower()
    if "decompiler" in normalized:
        return LegalIRTransformationKind.DECOMPILER
    if "hammer" in normalized or "receipt" in normalized or "translation" in normalized:
        return LegalIRTransformationKind.HAMMER
    if "guidance" in normalized or "learned" in normalized:
        return LegalIRTransformationKind.LEARNED_GUIDANCE
    if "diagnostic" in normalized or "issue" in normalized:
        return LegalIRTransformationKind.DIAGNOSTIC
    if "compiler" in normalized or "formula" in normalized or "frame" in normalized:
        return LegalIRTransformationKind.COMPILER
    return LegalIRTransformationKind.DERIVED


def _collect_ids(value: Any, ids: list[str]) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = str(key)
            if normalized in _NON_FACT_ID_KEYS:
                continue
            if normalized in _ID_KEYS:
                ids.extend(_strings(item))
            elif normalized in _ID_LIST_KEYS:
                ids.extend(_strings(item))
            elif isinstance(item, (Mapping, list, tuple)):
                _collect_ids(item, ids)
    elif isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray, str)):
        for item in value:
            _collect_ids(item, ids)


__all__ = [
    "LEGAL_IR_SOURCE_MAP_SCHEMA_VERSION",
    "LegalIRArtifactTraceability",
    "LegalIRFactTrace",
    "LegalIRProvenanceSpan",
    "LegalIRSourceDocument",
    "LegalIRSourceMap",
    "LegalIRSourceMapBuilder",
    "LegalIRSourceMapIssue",
    "LegalIRSourceMapNode",
    "LegalIRSourceMapTransform",
    "LegalIRSourceMapValidationResult",
    "LegalIRTokenSpan",
    "LegalIRTransformationKind",
    "assert_legal_ir_artifact_traceable",
    "bind_legal_ir_artifact_source_map",
    "build_legal_ir_source_map",
    "extract_legal_ir_emitted_fact_ids",
    "record_legal_ir_artifact_provenance",
    "trace_legal_ir_fact",
    "validate_legal_ir_source_map",
]
