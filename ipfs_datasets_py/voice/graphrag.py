"""Deterministic GraphRAG ingestion and safe response-plan retrieval for Abby.

This module turns canonical Abby voice v2 rows into a content-addressed graph
and a dependency-free hybrid retrieval index.  Retrieved templates are plans,
not answers: example response slot values are never considered current facts.
Every placeholder in a returned plan is bound from a caller-supplied,
CID-bearing evidence record from the current retrieval turn.

Heavy GraphRAG collaborators are optional and injected.  Importing this module
does not construct a model, open a network connection, or initialize IPFS.
"""

from __future__ import annotations

import asyncio
import base64
import inspect
import json
import math
import re
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from hashlib import sha256
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, ClassVar

from .schema import (
    AbbyVoiceAudio,
    AbbyVoiceDatasetBundle,
    AbbyVoiceProvenance,
    AbbyVoiceResponse,
    AbbyVoiceTemplate,
    validate_bundle,
)

if TYPE_CHECKING:
    # These imports document and type the production integration boundaries
    # without making the offline voice index import optional-heavy modules.
    from ..ml.llm.llm_graphrag import GraphRAGLLMProcessor
    from ..processors.storage.ipld.knowledge_graph import IPLDKnowledgeGraph
    from ..vector_stores.ipld_vector_store import IPLDVectorStore


GRAPHRAG_INDEX_SCHEMA_VERSION = "abby_voice_graphrag_v1"
_TOKEN_RE = re.compile(r"[a-z0-9]+")
_SAFE_SLOT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")
_VECTOR_DIMENSIONS = 256
_STOPWORDS = frozenset(
    {
        "a",
        "about",
        "am",
        "and",
        "are",
        "can",
        "do",
        "for",
        "help",
        "i",
        "in",
        "is",
        "me",
        "my",
        "need",
        "of",
        "or",
        "the",
        "to",
        "with",
        "you",
    }
)


class GraphRAGIngestionError(ValueError):
    """Raised when rows cannot form one safe, referentially valid index."""


class UnsafeSlotBindingError(ValueError):
    """Raised when supplied current evidence is malformed or cannot be cited."""


def _plain_json_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _plain_json_value(item)
            for key, item in value.items()
        }
    if isinstance(value, list | tuple):
        return [_plain_json_value(item) for item in value]
    if isinstance(value, set | frozenset):
        return [
            _plain_json_value(item)
            for item in sorted(value, key=lambda item: repr(item))
        ]
    return value


def _json_safe(value: Any) -> Any:
    """Return a deterministic JSON-safe copy or raise a useful error."""

    try:
        return json.loads(
            json.dumps(
                _plain_json_value(value),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(f"value is not canonical JSON: {exc}") from exc


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        _json_safe(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _content_cid(value: Any) -> str:
    """Return a valid CIDv1/raw/sha2-256 for canonical JSON bytes."""

    digest = sha256(_canonical_json(value)).digest()
    cid_bytes = b"\x01\x55\x12\x20" + digest
    encoded = base64.b32encode(cid_bytes).decode("ascii").lower().rstrip("=")
    return "b" + encoded


def _validate_probability(name: str, value: float) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a finite number between 0 and 1") from exc
    if not math.isfinite(result) or not 0.0 <= result <= 1.0:
        raise ValueError(f"{name} must be a finite number between 0 and 1")
    return result


def _tokens(text: str) -> tuple[str, ...]:
    return tuple(
        token
        for token in _TOKEN_RE.findall(str(text or "").lower().replace("_", " "))
        if token not in _STOPWORDS
    )


def _sparse_vector(text: str, dimensions: int = _VECTOR_DIMENSIONS) -> tuple[float, ...]:
    """Build a deterministic signed hashed-token vector."""

    values = [0.0] * dimensions
    for token, count in Counter(_tokens(text)).items():
        digest = sha256(token.encode("utf-8")).digest()
        bucket = int.from_bytes(digest[:4], "big") % dimensions
        sign = 1.0 if digest[4] & 1 else -1.0
        values[bucket] += sign * (1.0 + math.log(float(count)))
    norm = math.sqrt(sum(value * value for value in values))
    if norm:
        values = [value / norm for value in values]
    return tuple(values)


def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right) or not left:
        return 0.0
    left_norm = math.sqrt(sum(float(value) ** 2 for value in left))
    right_norm = math.sqrt(sum(float(value) ** 2 for value in right))
    if not left_norm or not right_norm:
        return 0.0
    score = sum(float(a) * float(b) for a, b in zip(left, right))
    return max(0.0, min(1.0, score / (left_norm * right_norm)))


def _token_cosine(left: Sequence[str], right: Sequence[str]) -> float:
    left_counts = Counter(left)
    right_counts = Counter(right)
    if not left_counts or not right_counts:
        return 0.0
    numerator = sum(
        left_counts[token] * right_counts[token] for token in left_counts.keys() & right_counts.keys()
    )
    left_norm = math.sqrt(sum(count * count for count in left_counts.values()))
    right_norm = math.sqrt(sum(count * count for count in right_counts.values()))
    return numerator / (left_norm * right_norm)


def _normalized_phrase(text: str) -> str:
    return " ".join(_tokens(text))


def _mapping(value: Mapping[str, Any] | None) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _sync_result(value: Any) -> Any:
    """Resolve an optional collaborator awaitable at the synchronous boundary."""

    if not inspect.isawaitable(value):
        return value
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(value)
    if inspect.iscoroutine(value):
        value.close()
    raise RuntimeError(
        "an asynchronous GraphRAG collaborator cannot be used from the synchronous "
        "voice provider while an event loop is running"
    )


def _call_supported(function: Callable[..., Any], first_arg: Any, **kwargs: Any) -> Any:
    try:
        signature = inspect.signature(function)
        accepts_kwargs = any(
            item.kind == inspect.Parameter.VAR_KEYWORD
            for item in signature.parameters.values()
        )
        selected = (
            kwargs
            if accepts_kwargs
            else {key: value for key, value in kwargs.items() if key in signature.parameters}
        )
    except (TypeError, ValueError):
        selected = kwargs
    return _sync_result(function(first_arg, **selected))


@dataclass(frozen=True, slots=True)
class EvidenceRecord:
    """Current cited evidence used to bind response-plan slots."""

    source_id: str
    cid: str
    uri: str | None = None
    text: str | None = None
    facts: Mapping[str, Any] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        source_id = str(self.source_id or "").strip()
        cid = str(self.cid or "").strip()
        if not source_id:
            raise UnsafeSlotBindingError("current evidence source_id must be non-empty")
        if not cid:
            raise UnsafeSlotBindingError(
                f"current evidence {source_id!r} must include a source CID"
            )
        if not isinstance(self.facts, Mapping):
            raise UnsafeSlotBindingError(
                f"current evidence {source_id!r} facts must be a mapping"
            )
        facts: dict[str, Any] = {}
        for raw_name, raw_value in self.facts.items():
            name = str(raw_name or "").strip()
            if not name or not _SAFE_SLOT_RE.fullmatch(name):
                raise UnsafeSlotBindingError(
                    f"current evidence {source_id!r} has invalid fact name {raw_name!r}"
                )
            safe_value = _json_safe(raw_value)
            if safe_value is None or isinstance(safe_value, dict | list):
                raise UnsafeSlotBindingError(
                    f"current evidence {source_id!r} fact {name!r} must be a "
                    "non-null JSON scalar"
                )
            facts[name] = safe_value
        metadata = _json_safe(dict(self.metadata or {}))
        object.__setattr__(self, "source_id", source_id)
        object.__setattr__(self, "cid", cid)
        object.__setattr__(self, "uri", str(self.uri).strip() if self.uri else f"ipfs://{cid}")
        object.__setattr__(self, "text", str(self.text).strip() if self.text else None)
        object.__setattr__(self, "facts", MappingProxyType(facts))
        object.__setattr__(self, "metadata", MappingProxyType(metadata))

    @classmethod
    def from_mapping(
        cls, value: Mapping[str, Any], *, default_id: str | None = None
    ) -> EvidenceRecord:
        if not isinstance(value, Mapping):
            raise UnsafeSlotBindingError("current evidence entries must be mappings")
        source_id = value.get("source_id") or value.get("id") or default_id
        cid = value.get("cid") or value.get("source_cid")
        metadata = _mapping(value.get("metadata"))
        for key, item in value.items():
            if key not in {
                "source_id",
                "id",
                "cid",
                "source_cid",
                "uri",
                "text",
                "excerpt",
                "facts",
                "metadata",
            }:
                metadata.setdefault(str(key), item)
        raw_facts = value.get("facts", {})
        if raw_facts is None:
            raw_facts = {}
        if not isinstance(raw_facts, Mapping):
            raise UnsafeSlotBindingError(
                f"current evidence {str(source_id or '')!r} facts must be a mapping"
            )
        return cls(
            source_id=str(source_id or ""),
            cid=str(cid or ""),
            uri=str(value["uri"]) if value.get("uri") is not None else None,
            text=str(value.get("text") or value.get("excerpt") or "") or None,
            facts=raw_facts,
            metadata=metadata,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "cid": self.cid,
            "uri": self.uri,
            "text": self.text,
            "facts": _json_safe(self.facts),
            "metadata": _json_safe(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class GraphNode:
    """One deterministic node in the template-intent-evidence graph."""

    node_id: str
    kind: str
    label: str
    properties: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "properties", MappingProxyType(_json_safe(dict(self.properties or {})))
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.node_id,
            "kind": self.kind,
            "label": self.label,
            "properties": _json_safe(self.properties),
        }


@dataclass(frozen=True, slots=True)
class GraphEdge:
    """One deterministic typed edge in the template graph."""

    edge_id: str
    kind: str
    source: str
    target: str
    properties: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "properties", MappingProxyType(_json_safe(dict(self.properties or {})))
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.edge_id,
            "kind": self.kind,
            "source": self.source,
            "target": self.target,
            "properties": _json_safe(self.properties),
        }


@dataclass(frozen=True, slots=True)
class TemplateGraphSnapshot:
    """Content-addressed, JSON-safe view of the current graph."""

    nodes: tuple[GraphNode, ...]
    edges: tuple[GraphEdge, ...]
    graph_cid: str
    schema_version: str = GRAPHRAG_INDEX_SCHEMA_VERSION

    @classmethod
    def build(
        cls, nodes: Iterable[GraphNode], edges: Iterable[GraphEdge]
    ) -> TemplateGraphSnapshot:
        sorted_nodes = tuple(sorted(nodes, key=lambda item: item.node_id))
        sorted_edges = tuple(sorted(edges, key=lambda item: item.edge_id))
        content = {
            "schema_version": GRAPHRAG_INDEX_SCHEMA_VERSION,
            "nodes": [item.to_dict() for item in sorted_nodes],
            "edges": [item.to_dict() for item in sorted_edges],
        }
        return cls(
            nodes=sorted_nodes,
            edges=sorted_edges,
            graph_cid=_content_cid(content),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "graph_cid": self.graph_cid,
            "nodes": [item.to_dict() for item in self.nodes],
            "edges": [item.to_dict() for item in self.edges],
        }


@dataclass(frozen=True, slots=True)
class IngestionReceipt:
    """Auditable result of one atomic local index update."""

    index_cid: str
    graph_cid: str
    added_templates: int
    added_responses: int
    added_audio: int
    added_provenance: int
    duplicate_rows: int
    node_count: int
    edge_count: int
    published_graph_nodes: int = 0
    published_graph_edges: int = 0
    published_vectors: int = 0
    external_graph_root_cid: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "index_cid": self.index_cid,
            "graph_cid": self.graph_cid,
            "added_templates": self.added_templates,
            "added_responses": self.added_responses,
            "added_audio": self.added_audio,
            "added_provenance": self.added_provenance,
            "duplicate_rows": self.duplicate_rows,
            "node_count": self.node_count,
            "edge_count": self.edge_count,
            "published_graph_nodes": self.published_graph_nodes,
            "published_graph_edges": self.published_graph_edges,
            "published_vectors": self.published_vectors,
            "external_graph_root_cid": self.external_graph_root_cid,
        }


@dataclass(frozen=True, slots=True)
class TemplateMatch:
    """One hybrid retrieval candidate before current-evidence binding."""

    template: AbbyVoiceTemplate
    confidence: float
    lexical_score: float
    vector_score: float
    graph_score: float
    exact_intent: bool
    index_cid: str
    graph_cid: str
    matched_response_ids: tuple[str, ...] = ()
    audio_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "template_id": self.template.template_id,
            "intent": self.template.intent,
            "locale": self.template.locale,
            "confidence": self.confidence,
            "scores": {
                "lexical": self.lexical_score,
                "vector": self.vector_score,
                "graph": self.graph_score,
            },
            "exact_intent": self.exact_intent,
            "index_cid": self.index_cid,
            "graph_cid": self.graph_cid,
            "matched_response_ids": list(self.matched_response_ids),
            "audio_ids": list(self.audio_ids),
            "source_cids": list(self.template.source_cids),
            "provenance_ids": list(self.template.provenance_ids),
        }


@dataclass(frozen=True, slots=True)
class _EmbeddingDocument:
    """Minimal shape accepted by the current injected IPLDVectorStore API."""

    id: str
    text: str
    vector: tuple[float, ...]
    metadata: Mapping[str, Any]

    @property
    def chunk_id(self) -> str:
        return self.id

    @property
    def content(self) -> str:
        return self.text

    @property
    def embedding(self) -> tuple[float, ...]:
        return self.vector


def _node_id(kind: str, identity: str) -> str:
    return f"{kind}:{identity}"


def _edge(
    kind: str,
    source: str,
    target: str,
    properties: Mapping[str, Any] | None = None,
) -> GraphEdge:
    safe_properties = _json_safe(dict(properties or {}))
    identity = _content_cid(
        {
            "kind": kind,
            "properties": safe_properties,
            "source": source,
            "target": target,
        }
    )
    return GraphEdge(
        edge_id=f"edge:{identity}",
        kind=kind,
        source=source,
        target=target,
        properties=safe_properties,
    )


def _merge_rows(
    existing: Sequence[Any],
    incoming: Iterable[Any],
    *,
    id_attribute: str,
    kind: str,
) -> tuple[tuple[Any, ...], int, int]:
    by_id = {getattr(row, id_attribute): row for row in existing}
    added = 0
    duplicates = 0
    for row in incoming:
        identity = getattr(row, id_attribute)
        previous = by_id.get(identity)
        if previous is not None:
            if previous != row:
                raise GraphRAGIngestionError(
                    f"conflicting {kind} rows share ID {identity!r}"
                )
            duplicates += 1
            continue
        by_id[identity] = row
        added += 1
    return tuple(sorted(by_id.values(), key=lambda row: getattr(row, id_attribute))), added, duplicates


def _coerce_bundle(
    *,
    templates: Iterable[Mapping[str, Any] | AbbyVoiceTemplate] = (),
    responses: Iterable[Mapping[str, Any] | AbbyVoiceResponse] = (),
    audio: Iterable[Mapping[str, Any] | AbbyVoiceAudio] = (),
    provenance: Iterable[Mapping[str, Any] | AbbyVoiceProvenance] = (),
) -> AbbyVoiceDatasetBundle:
    # Local references are validated after these rows are merged with the
    # index's existing rows.
    return validate_bundle(
        templates=templates,
        responses=responses,
        audio=audio,
        provenance=provenance,
        require_references=False,
    )


def _build_graph(bundle: AbbyVoiceDatasetBundle) -> TemplateGraphSnapshot:
    nodes: dict[str, GraphNode] = {}
    edges: dict[str, GraphEdge] = {}

    def add_node(node: GraphNode) -> None:
        previous = nodes.get(node.node_id)
        if previous is not None and previous != node:
            raise GraphRAGIngestionError(f"conflicting graph node {node.node_id!r}")
        nodes[node.node_id] = node

    def add_edge(edge: GraphEdge) -> None:
        edges[edge.edge_id] = edge

    source_cids = {
        cid
        for row in (*bundle.templates, *bundle.responses, *bundle.audio, *bundle.provenance)
        for cid in row.source_cids
    }
    source_cids.update(
        cid for response in bundle.responses for cid in response.slot_source_cids
    )
    for cid in sorted(source_cids):
        add_node(
            GraphNode(
                _node_id("evidence", cid),
                "evidence",
                cid,
                {"cid": cid, "facts_persisted": False},
            )
        )

    for template in bundle.templates:
        intent_id = _node_id("intent", f"{template.locale}:{template.intent}")
        template_id = _node_id("template", template.template_id)
        add_node(
            GraphNode(
                intent_id,
                "intent",
                template.intent,
                {"intent": template.intent, "locale": template.locale},
            )
        )
        add_node(
            GraphNode(
                template_id,
                "template",
                template.template_id,
                {
                    "content_sha256": template.content_sha256,
                    "factual_slot_names": list(template.factual_slot_names),
                    "locale": template.locale,
                    "provenance_ids": list(template.provenance_ids),
                    "required_slot_names": list(template.required_slot_names),
                    "safety_labels": list(template.safety_labels),
                    "source_cids": list(template.source_cids),
                    "spoken_template": template.spoken_template,
                    "template_text": template.template_text,
                },
            )
        )
        add_edge(_edge("ROUTES_TO", intent_id, template_id))
        for slot_name in template.slot_names:
            slot_id = _node_id("slot", f"{template.template_id}:{slot_name}")
            add_node(
                GraphNode(
                    slot_id,
                    "slot",
                    slot_name,
                    {
                        "factual": slot_name in template.factual_slot_names,
                        "required": slot_name in template.required_slot_names,
                        "template_id": template.template_id,
                    },
                )
            )
            add_edge(
                _edge(
                    "DECLARES_SLOT",
                    template_id,
                    slot_id,
                    {
                        "factual": slot_name in template.factual_slot_names,
                        "required": slot_name in template.required_slot_names,
                    },
                )
            )
            for cid in template.source_cids:
                add_edge(
                    _edge(
                        "REQUIRES_EVIDENCE",
                        slot_id,
                        _node_id("evidence", cid),
                        {"current_fact_required": True},
                    )
                )
        for cid in template.source_cids:
            add_edge(
                _edge(
                    "SUPPORTED_BY",
                    template_id,
                    _node_id("evidence", cid),
                    {"link_only": True},
                )
            )

    for response in bundle.responses:
        response_id = _node_id("response", response.response_id)
        add_node(
            GraphNode(
                response_id,
                "response",
                response.response_id,
                {
                    "historical_example": True,
                    "intent": response.intent,
                    "locale": response.locale,
                    "location_tags": list(response.location_tags),
                    "route_labels": list(response.route_labels),
                    "service_tags": list(response.service_tags),
                    "utterance": response.utterance,
                },
            )
        )
        if response.template_id:
            template_id = _node_id("template", response.template_id)
            add_edge(
                _edge(
                    "INSTANCE_OF",
                    response_id,
                    template_id,
                    {"slot_values_are_historical": True},
                )
            )
        if response.intent:
            intent_id = _node_id("intent", f"{response.locale}:{response.intent}")
            if intent_id not in nodes:
                add_node(
                    GraphNode(
                        intent_id,
                        "intent",
                        response.intent,
                        {"intent": response.intent, "locale": response.locale},
                    )
                )
            add_edge(_edge("EXAMPLE_OF", response_id, intent_id))
        for audio_id in response.audio_ids:
            add_edge(_edge("HAS_AUDIO", response_id, _node_id("audio", audio_id)))
        for slot_name, cid in zip(response.slot_names, response.slot_source_cids):
            if response.template_id:
                slot_id = _node_id("slot", f"{response.template_id}:{slot_name}")
                add_edge(
                    _edge(
                        "HISTORICAL_BINDING",
                        response_id,
                        slot_id,
                        {"value_indexed_as_fact": False},
                    )
                )
                add_edge(
                    _edge(
                        "HISTORICALLY_CITED",
                        slot_id,
                        _node_id("evidence", cid),
                        {"current_fact_required": True},
                    )
                )
        for cid in response.source_cids:
            add_edge(
                _edge(
                    "CITES",
                    response_id,
                    _node_id("evidence", cid),
                    {"historical_example": True},
                )
            )

    for asset in bundle.audio:
        audio_id = _node_id("audio", asset.audio_id)
        add_node(
            GraphNode(
                audio_id,
                "audio",
                asset.audio_id,
                {
                    "content_sha256": asset.content_sha256,
                    "ipfs_cid": asset.ipfs_cid,
                    "locale": asset.locale,
                    "segment_kind": asset.segment_kind,
                    "text_sha256": asset.text_sha256,
                    "uri": asset.uri,
                },
            )
        )
        if asset.template_id:
            add_edge(
                _edge("HAS_AUDIO", _node_id("template", asset.template_id), audio_id)
            )
        if asset.response_id:
            add_edge(
                _edge("HAS_AUDIO", _node_id("response", asset.response_id), audio_id)
            )
        for cid in asset.source_cids:
            add_edge(
                _edge("CITES", audio_id, _node_id("evidence", cid), {"asset": True})
            )

    known_subjects = {
        row.ID_FIELD + ":" + getattr(row, row.ID_FIELD): _node_id(
            row.ID_FIELD.removesuffix("_id"), getattr(row, row.ID_FIELD)
        )
        for row in (*bundle.templates, *bundle.responses, *bundle.audio)
    }
    for record in bundle.provenance:
        provenance_id = _node_id("provenance", record.provenance_id)
        add_node(
            GraphNode(
                provenance_id,
                "provenance",
                record.provenance_id,
                {
                    "source_revision": record.source_revision,
                    "source_sha256": record.source_sha256,
                    "source_uri": record.source_uri,
                    "subject_id": record.subject_id,
                    "subject_schema_version": record.subject_schema_version,
                    "transformation_name": record.transformation_name,
                    "transformation_version": record.transformation_version,
                },
            )
        )
        subject_key = {
            "abby_voice_template_v2": "template_id",
            "abby_voice_response_v2": "response_id",
            "abby_voice_audio_v2": "audio_id",
        }.get(record.subject_schema_version)
        if subject_key:
            target = known_subjects.get(f"{subject_key}:{record.subject_id}")
            if target:
                add_edge(_edge("DESCRIBES", provenance_id, target))
        for cid in record.source_cids:
            add_edge(
                _edge(
                    "DERIVED_FROM",
                    provenance_id,
                    _node_id("evidence", cid),
                )
            )
        for parent_id in record.parent_provenance_ids:
            add_edge(
                _edge(
                    "DERIVED_FROM_PROVENANCE",
                    provenance_id,
                    _node_id("provenance", parent_id),
                )
            )

    return TemplateGraphSnapshot.build(nodes.values(), edges.values())


class SlottedResponseIndex:
    """Canonical response-frame graph plus deterministic hybrid retriever.

    ``IPLDKnowledgeGraph``, ``IPLDVectorStore``, and ``GraphRAGLLMProcessor``
    integrations are accepted structurally through injected collaborators.
    The built-in graph and sparse vector index remain the authoritative,
    reproducible offline representation.
    """

    schema_version: ClassVar[str] = GRAPHRAG_INDEX_SCHEMA_VERSION

    def __init__(
        self,
        *,
        lexical_weight: float = 0.45,
        vector_weight: float = 0.35,
        graph_weight: float = 0.20,
        embedder: Callable[[str], Sequence[float]] | None = None,
        vector_store: IPLDVectorStore | Any | None = None,
        knowledge_graph: IPLDKnowledgeGraph | Any | None = None,
        graphrag_processor: GraphRAGLLMProcessor | Any | None = None,
    ) -> None:
        raw_weights = (
            _validate_probability("lexical_weight", lexical_weight),
            _validate_probability("vector_weight", vector_weight),
            _validate_probability("graph_weight", graph_weight),
        )
        total = sum(raw_weights)
        if total <= 0:
            raise ValueError("at least one retrieval weight must be greater than zero")
        self.lexical_weight, self.vector_weight, self.graph_weight = (
            value / total for value in raw_weights
        )
        self.embedder = embedder
        self.vector_store = vector_store
        self.knowledge_graph = knowledge_graph
        self.graphrag_processor = graphrag_processor
        self._bundle = AbbyVoiceDatasetBundle()
        self._graph = TemplateGraphSnapshot.build((), ())
        self._documents: dict[str, str] = {}
        self._vectors: dict[str, tuple[float, ...]] = {}
        self._published_node_ids: set[str] = set()
        self._published_edge_ids: set[str] = set()
        self._published_vector_ids: set[str] = set()
        self._last_collaborator_errors: tuple[str, ...] = ()

    @classmethod
    def from_rows(
        cls,
        *,
        templates: Iterable[Mapping[str, Any] | AbbyVoiceTemplate],
        responses: Iterable[Mapping[str, Any] | AbbyVoiceResponse] = (),
        audio: Iterable[Mapping[str, Any] | AbbyVoiceAudio] = (),
        provenance: Iterable[Mapping[str, Any] | AbbyVoiceProvenance] = (),
        **kwargs: Any,
    ) -> SlottedResponseIndex:
        index = cls(**kwargs)
        index.ingest(
            templates=templates,
            responses=responses,
            audio=audio,
            provenance=provenance,
        )
        return index

    @property
    def bundle(self) -> AbbyVoiceDatasetBundle:
        return self._bundle

    @property
    def graph(self) -> TemplateGraphSnapshot:
        return self._graph

    @property
    def graph_cid(self) -> str:
        return self._graph.graph_cid

    @property
    def index_cid(self) -> str:
        return _content_cid(self._index_content())

    @property
    def last_collaborator_errors(self) -> tuple[str, ...]:
        """Privacy-safe collaborator error types from the most recent search."""

        return self._last_collaborator_errors

    def _index_content(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "weights": {
                "graph": self.graph_weight,
                "lexical": self.lexical_weight,
                "vector": self.vector_weight,
            },
            "graph_cid": self.graph_cid,
            "templates": [row.to_dict() for row in self._bundle.templates],
            "responses": [row.to_dict() for row in self._bundle.responses],
            "audio": [row.to_dict() for row in self._bundle.audio],
            "provenance": [row.to_dict() for row in self._bundle.provenance],
        }

    def to_dict(self) -> dict[str, Any]:
        result = self._index_content()
        result["index_cid"] = self.index_cid
        result["graph"] = self.graph.to_dict()
        return result

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> SlottedResponseIndex:
        if not isinstance(value, Mapping):
            raise GraphRAGIngestionError("serialized GraphRAG index must be a mapping")
        if value.get("schema_version") != GRAPHRAG_INDEX_SCHEMA_VERSION:
            raise GraphRAGIngestionError(
                f"schema_version must equal {GRAPHRAG_INDEX_SCHEMA_VERSION!r}"
            )
        weights = value.get("weights")
        if not isinstance(weights, Mapping):
            raise GraphRAGIngestionError("serialized GraphRAG index weights are missing")
        index = cls(
            lexical_weight=weights.get("lexical", 0.45),
            vector_weight=weights.get("vector", 0.35),
            graph_weight=weights.get("graph", 0.20),
        )
        index.ingest(
            templates=value.get("templates") or (),
            responses=value.get("responses") or (),
            audio=value.get("audio") or (),
            provenance=value.get("provenance") or (),
            publish=False,
        )
        claimed_index_cid = value.get("index_cid")
        if claimed_index_cid and claimed_index_cid != index.index_cid:
            raise GraphRAGIngestionError("serialized index_cid does not match its content")
        claimed_graph_cid = value.get("graph_cid")
        if claimed_graph_cid and claimed_graph_cid != index.graph_cid:
            raise GraphRAGIngestionError("serialized graph_cid does not match its content")
        serialized_graph = value.get("graph")
        if serialized_graph is not None and serialized_graph != index.graph.to_dict():
            raise GraphRAGIngestionError(
                "serialized graph snapshot does not match canonical rows"
            )
        return index

    def ingest_records(
        self,
        records: Iterable[
            Mapping[str, Any]
            | AbbyVoiceTemplate
            | AbbyVoiceResponse
            | AbbyVoiceAudio
            | AbbyVoiceProvenance
        ],
        *,
        publish: bool = True,
    ) -> IngestionReceipt:
        grouped: dict[type[Any], list[Any]] = {
            AbbyVoiceTemplate: [],
            AbbyVoiceResponse: [],
            AbbyVoiceAudio: [],
            AbbyVoiceProvenance: [],
        }
        for record in records:
            if isinstance(record, Mapping):
                version = record.get("schema_version")
                target = {
                    "abby_voice_template_v2": AbbyVoiceTemplate,
                    "abby_voice_response_v2": AbbyVoiceResponse,
                    "abby_voice_audio_v2": AbbyVoiceAudio,
                    "abby_voice_provenance_v2": AbbyVoiceProvenance,
                }.get(str(version))
                if target is None:
                    raise GraphRAGIngestionError(
                        f"unsupported canonical record schema_version {version!r}"
                    )
            else:
                target = type(record)
            if target not in grouped:
                raise GraphRAGIngestionError(
                    f"unsupported GraphRAG record type {target.__name__}"
                )
            grouped[target].append(record)
        return self.ingest(
            templates=grouped[AbbyVoiceTemplate],
            responses=grouped[AbbyVoiceResponse],
            audio=grouped[AbbyVoiceAudio],
            provenance=grouped[AbbyVoiceProvenance],
            publish=publish,
        )

    def ingest(
        self,
        *,
        templates: Iterable[Mapping[str, Any] | AbbyVoiceTemplate] = (),
        responses: Iterable[Mapping[str, Any] | AbbyVoiceResponse] = (),
        audio: Iterable[Mapping[str, Any] | AbbyVoiceAudio] = (),
        provenance: Iterable[Mapping[str, Any] | AbbyVoiceProvenance] = (),
        publish: bool = True,
    ) -> IngestionReceipt:
        incoming = _coerce_bundle(
            templates=templates,
            responses=responses,
            audio=audio,
            provenance=provenance,
        )
        merged_templates, added_templates, duplicate_templates = _merge_rows(
            self._bundle.templates,
            incoming.templates,
            id_attribute="template_id",
            kind="template",
        )
        merged_responses, added_responses, duplicate_responses = _merge_rows(
            self._bundle.responses,
            incoming.responses,
            id_attribute="response_id",
            kind="response",
        )
        merged_audio, added_audio, duplicate_audio = _merge_rows(
            self._bundle.audio,
            incoming.audio,
            id_attribute="audio_id",
            kind="audio",
        )
        merged_provenance, added_provenance, duplicate_provenance = _merge_rows(
            self._bundle.provenance,
            incoming.provenance,
            id_attribute="provenance_id",
            kind="provenance",
        )
        try:
            staged_bundle = validate_bundle(
                templates=merged_templates,
                responses=merged_responses,
                audio=merged_audio,
                provenance=merged_provenance,
            )
        except ValueError as exc:
            raise GraphRAGIngestionError(str(exc)) from exc

        for template in staged_bundle.templates:
            if template.slot_names and not template.source_cids:
                raise GraphRAGIngestionError(
                    f"slotted template {template.template_id!r} must declare source_cids; "
                    "historical response values are not grounding"
                )

        staged_graph = _build_graph(staged_bundle)
        staged_documents, staged_vectors = self._build_documents(staged_bundle)
        published_nodes = 0
        published_edges = 0
        published_vectors = 0
        external_root = None
        if publish:
            published_nodes, published_edges, external_root = self._publish_graph(
                staged_graph
            )
            published_vectors = self._publish_vectors(
                staged_bundle, staged_documents, staged_vectors
            )

        self._bundle = staged_bundle
        self._graph = staged_graph
        self._documents = staged_documents
        self._vectors = staged_vectors
        return IngestionReceipt(
            index_cid=self.index_cid,
            graph_cid=self.graph_cid,
            added_templates=added_templates,
            added_responses=added_responses,
            added_audio=added_audio,
            added_provenance=added_provenance,
            duplicate_rows=(
                duplicate_templates
                + duplicate_responses
                + duplicate_audio
                + duplicate_provenance
            ),
            node_count=len(self.graph.nodes),
            edge_count=len(self.graph.edges),
            published_graph_nodes=published_nodes,
            published_graph_edges=published_edges,
            published_vectors=published_vectors,
            external_graph_root_cid=external_root,
        )

    def _build_documents(
        self, bundle: AbbyVoiceDatasetBundle
    ) -> tuple[dict[str, str], dict[str, tuple[float, ...]]]:
        responses_by_template: dict[str, list[AbbyVoiceResponse]] = {}
        for response in bundle.responses:
            if response.template_id:
                responses_by_template.setdefault(response.template_id, []).append(response)
        documents: dict[str, str] = {}
        vectors: dict[str, tuple[float, ...]] = {}
        for template in bundle.templates:
            examples = responses_by_template.get(template.template_id, [])
            text = " ".join(
                part
                for part in (
                    template.intent.replace("_", " "),
                    template.template_text,
                    template.spoken_template or "",
                    " ".join(template.safety_labels),
                    " ".join(
                        item.utterance or ""
                        for item in sorted(examples, key=lambda row: row.response_id)
                    ),
                    " ".join(
                        label
                        for item in examples
                        for label in (
                            *item.route_labels,
                            *item.service_tags,
                            *item.location_tags,
                        )
                    ),
                )
                if part
            )
            documents[template.template_id] = text
            vectors[template.template_id] = self._embed(text)
        return documents, vectors

    def _embed(self, text: str) -> tuple[float, ...]:
        if self.embedder is None:
            return _sparse_vector(text)
        raw = _sync_result(self.embedder(text))
        if isinstance(raw, str | bytes) or not isinstance(raw, Sequence):
            raise ValueError("embedder must return a finite numeric sequence")
        vector = tuple(float(value) for value in raw)
        if not vector or any(not math.isfinite(value) for value in vector):
            raise ValueError("embedder must return a non-empty finite numeric sequence")
        return vector

    def _publish_graph(
        self, snapshot: TemplateGraphSnapshot
    ) -> tuple[int, int, str | None]:
        if self.knowledge_graph is None:
            return 0, 0, None
        add_entity = getattr(self.knowledge_graph, "add_entity", None)
        add_relationship = getattr(self.knowledge_graph, "add_relationship", None)
        if not callable(add_entity) or not callable(add_relationship):
            raise GraphRAGIngestionError(
                "injected IPLDKnowledgeGraph must expose add_entity and add_relationship"
            )
        nodes_added = 0
        edges_added = 0
        try:
            for node in snapshot.nodes:
                if node.node_id in self._published_node_ids:
                    continue
                _sync_result(
                    add_entity(
                        entity_type=node.kind,
                        name=node.label,
                        entity_id=node.node_id,
                        properties=_json_safe(node.properties),
                    )
                )
                self._published_node_ids.add(node.node_id)
                nodes_added += 1
            for edge in snapshot.edges:
                if edge.edge_id in self._published_edge_ids:
                    continue
                _sync_result(
                    add_relationship(
                        relationship_type=edge.kind,
                        source=edge.source,
                        target=edge.target,
                        relationship_id=edge.edge_id,
                        properties=_json_safe(edge.properties),
                    )
                )
                self._published_edge_ids.add(edge.edge_id)
                edges_added += 1
        except Exception as exc:
            raise GraphRAGIngestionError(
                f"injected IPLDKnowledgeGraph publication failed: {type(exc).__name__}: {exc}"
            ) from exc
        root = getattr(self.knowledge_graph, "root_cid", None)
        return nodes_added, edges_added, str(root) if root else None

    def _publish_vectors(
        self,
        bundle: AbbyVoiceDatasetBundle,
        documents: Mapping[str, str],
        vectors: Mapping[str, tuple[float, ...]],
    ) -> int:
        if self.vector_store is None:
            return 0
        templates = {
            row.template_id: row
            for row in bundle.templates
            if row.template_id not in self._published_vector_ids
        }
        if not templates:
            return 0
        payloads = [
            _EmbeddingDocument(
                id=template_id,
                text=documents[template_id],
                vector=vectors[template_id],
                metadata={
                    "template_id": template_id,
                    "intent": templates[template_id].intent,
                    "locale": templates[template_id].locale,
                    "source_cids": list(templates[template_id].source_cids),
                },
            )
            for template_id in sorted(templates)
        ]
        try:
            for method_name in ("upsert_documents", "add_documents", "add_embeddings"):
                method = getattr(self.vector_store, method_name, None)
                if not callable(method):
                    continue
                if method_name == "add_embeddings":
                    collection_exists = getattr(self.vector_store, "collection_exists", None)
                    create_collection = getattr(self.vector_store, "create_collection", None)
                    if callable(collection_exists) and callable(create_collection):
                        if not _sync_result(collection_exists()):
                            _sync_result(
                                create_collection(dimension=len(payloads[0].vector))
                            )
                _sync_result(method(payloads))
                self._published_vector_ids.update(templates)
                return len(payloads)
        except Exception as exc:
            raise GraphRAGIngestionError(
                f"injected IPLDVectorStore publication failed: {type(exc).__name__}: {exc}"
            ) from exc
        raise GraphRAGIngestionError(
            "injected IPLDVectorStore must expose upsert_documents, add_documents, "
            "or add_embeddings"
        )

    def _query_variants(self, query: str) -> tuple[str, ...]:
        variants = [query]
        if self.graphrag_processor is None:
            return tuple(variants)
        for method_name in ("expand_query", "enhance_query"):
            method = getattr(self.graphrag_processor, method_name, None)
            if not callable(method):
                continue
            try:
                raw = _call_supported(method, query)
            except Exception:
                return tuple(variants)
            candidates: list[Any] = []
            if isinstance(raw, str):
                candidates = [raw]
            elif isinstance(raw, Mapping):
                raw_keywords = raw.get("keywords")
                keywords = (
                    raw_keywords
                    if isinstance(raw_keywords, Sequence)
                    and not isinstance(raw_keywords, str | bytes)
                    else ()
                )
                candidates = [
                    raw.get("expanded_query"),
                    raw.get("query"),
                    *keywords,
                ]
            elif isinstance(raw, Sequence) and not isinstance(raw, str | bytes):
                candidates = list(raw)
            for candidate in candidates:
                if isinstance(candidate, str) and candidate.strip():
                    variants.append(candidate.strip())
            break
        return tuple(dict.fromkeys(variants))

    def _external_vector_scores(
        self, query: str, *, max_results: int
    ) -> tuple[dict[str, float], str | None]:
        if self.vector_store is None:
            return {}, None
        search = getattr(self.vector_store, "search", None)
        if not callable(search):
            return {}, "TypeError"
        try:
            raw = _call_supported(
                search,
                self._embed(query),
                top_k=max_results,
                max_results=max_results,
            )
            if isinstance(raw, Mapping):
                raw_results = (
                    raw.get("results")
                    or raw.get("items")
                    or raw.get("matches")
                    or ()
                )
            else:
                raw_results = raw or ()
            if isinstance(raw_results, str | bytes) or not isinstance(
                raw_results, Sequence
            ):
                return {}, "ValueError"
            scores: dict[str, float] = {}
            for result in raw_results:
                if isinstance(result, Mapping):
                    metadata = _mapping(result.get("metadata"))
                    template_id = (
                        result.get("template_id")
                        or metadata.get("template_id")
                        or result.get("chunk_id")
                        or result.get("id")
                    )
                    raw_score = result.get("score", result.get("similarity", 0.0))
                else:
                    metadata = _mapping(getattr(result, "metadata", None))
                    template_id = (
                        metadata.get("template_id")
                        or getattr(result, "chunk_id", None)
                        or getattr(result, "id", None)
                    )
                    raw_score = getattr(result, "score", 0.0)
                if template_id is None:
                    continue
                score = max(0.0, min(1.0, float(raw_score)))
                key = str(template_id)
                scores[key] = max(scores.get(key, 0.0), score)
            return scores, None
        except Exception as exc:
            return {}, type(exc).__name__

    def search(
        self,
        query: str,
        *,
        locale: str | None = None,
        intent: str | None = None,
        current_source_cids: Iterable[str] = (),
        max_results: int = 5,
        minimum_score: float = 0.0,
    ) -> tuple[TemplateMatch, ...]:
        query = str(query or "").strip()
        if not query:
            raise ValueError("GraphRAG query must be non-empty")
        if isinstance(max_results, bool) or not isinstance(max_results, int) or max_results <= 0:
            raise ValueError("max_results must be a positive integer")
        minimum_score = _validate_probability("minimum_score", minimum_score)
        requested_locale = str(locale).strip().lower() if locale else None
        requested_intent = str(intent).strip() if intent else None
        current_cids = {str(cid).strip() for cid in current_source_cids if str(cid).strip()}
        query_variants = self._query_variants(query)
        query_vectors = {
            variant: self._embed(variant) for variant in query_variants
        }
        external_scores, collaborator_error = self._external_vector_scores(
            query, max_results=max(max_results * 4, 20)
        )
        self._last_collaborator_errors = (
            (collaborator_error,) if collaborator_error else ()
        )

        responses_by_template: dict[str, list[AbbyVoiceResponse]] = {}
        audio_by_template: dict[str, set[str]] = {}
        for response in self._bundle.responses:
            if response.template_id:
                responses_by_template.setdefault(response.template_id, []).append(response)
                audio_by_template.setdefault(response.template_id, set()).update(
                    response.audio_ids
                )
        for asset in self._bundle.audio:
            if asset.template_id:
                audio_by_template.setdefault(asset.template_id, set()).add(asset.audio_id)

        matches: list[TemplateMatch] = []
        for template in self._bundle.templates:
            if requested_locale and template.locale.lower() != requested_locale:
                continue
            if requested_intent and template.intent != requested_intent:
                continue
            document = self._documents[template.template_id]
            lexical_score = max(
                _token_cosine(_tokens(variant), _tokens(document))
                for variant in query_variants
            )
            local_vector_score = max(
                _cosine(query_vectors[variant], self._vectors[template.template_id])
                for variant in query_variants
            )
            vector_score = max(
                local_vector_score,
                external_scores.get(template.template_id, 0.0),
            )
            normalized_intent = _normalized_phrase(template.intent)
            exact_intent = any(
                _normalized_phrase(variant) == normalized_intent
                for variant in query_variants
            ) or requested_intent == template.intent
            intent_score = max(
                _token_cosine(_tokens(variant), _tokens(template.intent))
                for variant in query_variants
            )
            example_score = 0.0
            examples = responses_by_template.get(template.template_id, [])
            if examples:
                example_score = max(
                    _token_cosine(_tokens(variant), _tokens(response.utterance or ""))
                    for variant in query_variants
                    for response in examples
                )
            evidence_score = (
                len(set(template.source_cids) & current_cids)
                / len(template.source_cids)
                if template.source_cids
                else 0.0
            )
            graph_score = min(
                1.0,
                0.7 * max(intent_score, example_score, 1.0 if exact_intent else 0.0)
                + 0.3 * evidence_score,
            )
            confidence = (
                self.lexical_weight * lexical_score
                + self.vector_weight * vector_score
                + self.graph_weight * graph_score
            )
            if exact_intent:
                confidence = max(confidence, 0.95)
            confidence = max(0.0, min(1.0, confidence))
            if confidence < minimum_score or confidence <= 0.0:
                continue
            matches.append(
                TemplateMatch(
                    template=template,
                    confidence=confidence,
                    lexical_score=lexical_score,
                    vector_score=vector_score,
                    graph_score=graph_score,
                    exact_intent=exact_intent,
                    index_cid=self.index_cid,
                    graph_cid=self.graph_cid,
                    matched_response_ids=tuple(
                        sorted(response.response_id for response in examples)
                    ),
                    audio_ids=tuple(
                        sorted(audio_by_template.get(template.template_id, ()))
                    ),
                )
            )
        matches.sort(key=lambda item: (-item.confidence, item.template.template_id))
        return tuple(matches[:max_results])


def _normalize_current_evidence(
    grounding: Mapping[str, Any] | Sequence[Mapping[str, Any]] | None,
) -> tuple[EvidenceRecord, ...]:
    if grounding is None:
        return ()
    raw: Any = grounding
    if isinstance(grounding, Mapping):
        wrapper_key = next(
            (
                key
                for key in ("current_evidence", "evidence", "sources")
                if key in grounding
            ),
            None,
        )
        if wrapper_key is not None:
            raw = grounding[wrapper_key]
        elif any(
            key in grounding
            for key in ("source_id", "id", "cid", "source_cid", "facts")
        ):
            raw = (grounding,)
        elif grounding:
            raw = grounding
        else:
            return ()
    records: list[EvidenceRecord] = []
    if isinstance(raw, Mapping):
        for source_id, value in raw.items():
            if not isinstance(value, Mapping):
                raise UnsafeSlotBindingError(
                    f"current evidence {source_id!r} must be a mapping"
                )
            records.append(EvidenceRecord.from_mapping(value, default_id=str(source_id)))
    elif isinstance(raw, Sequence) and not isinstance(raw, str | bytes):
        for value in raw:
            if not isinstance(value, Mapping):
                raise UnsafeSlotBindingError("current evidence entries must be mappings")
            records.append(EvidenceRecord.from_mapping(value))
    else:
        raise UnsafeSlotBindingError(
            "grounding must contain a mapping or sequence of current evidence"
        )
    by_id: dict[str, EvidenceRecord] = {}
    for record in records:
        previous = by_id.get(record.source_id)
        if previous is not None and previous != record:
            raise UnsafeSlotBindingError(
                f"conflicting current evidence shares source_id {record.source_id!r}"
            )
        by_id[record.source_id] = record
    return tuple(sorted(by_id.values(), key=lambda item: item.source_id))


def _bind_template(
    match: TemplateMatch, evidence: Sequence[EvidenceRecord]
) -> dict[str, Any] | None:
    template = match.template
    if not template.slot_names:
        used_evidence: tuple[EvidenceRecord, ...] = ()
        slots: list[dict[str, Any]] = []
    else:
        allowed = [
            record for record in evidence if record.cid in set(template.source_cids)
        ]
        if not allowed:
            return None
        slots = []
        used_by_id: dict[str, EvidenceRecord] = {}
        for slot_name in template.slot_names:
            fact_records = [record for record in allowed if slot_name in record.facts]
            if not fact_records:
                return None
            by_value: dict[bytes, list[EvidenceRecord]] = {}
            values: dict[bytes, Any] = {}
            for record in fact_records:
                key = _canonical_json(record.facts[slot_name])
                by_value.setdefault(key, []).append(record)
                values[key] = record.facts[slot_name]
            # Conflicting current sources are not resolved by arbitrary rank.
            if len(by_value) != 1:
                return None
            value_key = next(iter(by_value))
            if not str(values[value_key]).strip():
                return None
            supporting = sorted(by_value[value_key], key=lambda item: item.source_id)
            for record in supporting:
                used_by_id[record.source_id] = record
            slots.append(
                {
                    "name": slot_name,
                    "value": _json_safe(values[value_key]),
                    "source_ids": [record.source_id for record in supporting],
                }
            )
        used_evidence = tuple(
            used_by_id[source_id] for source_id in sorted(used_by_id)
        )

    return {
        "template_id": template.template_id,
        "template": template.spoken_template or template.template_text,
        "slots": slots,
        "sources": [record.to_dict() for record in used_evidence],
        "confidence": match.confidence,
        "intent": template.intent,
        "metadata": {
            "response_plan_only": True,
            "retrieval": "hybrid",
            "scores": {
                "lexical": match.lexical_score,
                "vector": match.vector_score,
                "graph": match.graph_score,
            },
            "exact_intent": match.exact_intent,
            "index_cid": match.index_cid,
            "graph_cid": match.graph_cid,
            "template_content_sha256": template.content_sha256,
            "template_source_cids": list(template.source_cids),
            "provenance_ids": list(template.provenance_ids),
            "matched_response_ids": list(match.matched_response_ids),
            "audio_ids": list(match.audio_ids),
            "historical_example_values_used_as_facts": False,
        },
    }


class GraphRAGVoiceTemplateProvider:
    """Router-compatible provider returning safely grounded response plans."""

    provider_name = "ipfs-datasets-graphrag"

    def __init__(
        self,
        index: SlottedResponseIndex,
        *,
        minimum_confidence: float = 0.35,
    ) -> None:
        if not isinstance(index, SlottedResponseIndex):
            raise TypeError("index must be a SlottedResponseIndex")
        self.index = index
        self.minimum_confidence = _validate_probability(
            "minimum_confidence", minimum_confidence
        )

    @classmethod
    def from_rows(
        cls,
        *,
        templates: Iterable[Mapping[str, Any] | AbbyVoiceTemplate],
        responses: Iterable[Mapping[str, Any] | AbbyVoiceResponse] = (),
        audio: Iterable[Mapping[str, Any] | AbbyVoiceAudio] = (),
        provenance: Iterable[Mapping[str, Any] | AbbyVoiceProvenance] = (),
        minimum_confidence: float = 0.35,
        **index_kwargs: Any,
    ) -> GraphRAGVoiceTemplateProvider:
        return cls(
            SlottedResponseIndex.from_rows(
                templates=templates,
                responses=responses,
                audio=audio,
                provenance=provenance,
                **index_kwargs,
            ),
            minimum_confidence=minimum_confidence,
        )

    def retrieve_candidates(
        self,
        transcript: str,
        *,
        context: Mapping[str, Any] | None = None,
        language: str | None = None,
        locale: str | None = None,
        grounding: Mapping[str, Any] | Sequence[Mapping[str, Any]] | None = None,
        max_results: int = 5,
    ) -> tuple[dict[str, Any], ...]:
        if (
            isinstance(max_results, bool)
            or not isinstance(max_results, int)
            or max_results <= 0
        ):
            raise ValueError("max_results must be a positive integer")
        current_evidence = _normalize_current_evidence(grounding)
        context_map = _mapping(context)
        explicit_intent = context_map.get("intent")
        matches = self.index.search(
            transcript,
            locale=locale or language,
            intent=str(explicit_intent) if explicit_intent else None,
            current_source_cids=(record.cid for record in current_evidence),
            max_results=max(max_results * 4, 20),
            minimum_score=self.minimum_confidence,
        )
        plans = [
            plan
            for match in matches
            if (plan := _bind_template(match, current_evidence)) is not None
        ]
        return tuple(plans[:max_results])

    def retrieve(
        self,
        transcript: str,
        *,
        context: Mapping[str, Any] | None = None,
        language: str | None = None,
        locale: str | None = None,
        grounding: Mapping[str, Any] | Sequence[Mapping[str, Any]] | None = None,
        max_results: int = 5,
    ) -> dict[str, Any] | None:
        plans = self.retrieve_candidates(
            transcript,
            context=context,
            language=language,
            locale=locale,
            grounding=grounding,
            max_results=max_results,
        )
        return plans[0] if plans else None

    # The accelerator-side lazy adapter checks these names before ``retrieve``.
    def retrieve_voice_template(self, transcript: str, **kwargs: Any) -> dict[str, Any] | None:
        return self.retrieve(transcript, **kwargs)

    def retrieve_template(self, transcript: str, **kwargs: Any) -> dict[str, Any] | None:
        return self.retrieve(transcript, **kwargs)


__all__ = [
    "GRAPHRAG_INDEX_SCHEMA_VERSION",
    "EvidenceRecord",
    "GraphEdge",
    "GraphNode",
    "GraphRAGIngestionError",
    "GraphRAGVoiceTemplateProvider",
    "IngestionReceipt",
    "SlottedResponseIndex",
    "TemplateGraphSnapshot",
    "TemplateMatch",
    "UnsafeSlotBindingError",
]
