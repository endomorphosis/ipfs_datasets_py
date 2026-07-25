"""Deterministic projection of SkillCenter records into a corpus graph.

This module is a thin domain adapter.  It does not execute or semantically
interpret source instructions, generate embeddings, or put raw source text in
the graph.  Raw source fields and optional embedding bytes are content
addressed separately; only their immutable addresses enter the graph identity.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
import hashlib
import math
import re
from types import MappingProxyType
from typing import Any, Protocol, runtime_checkable
from urllib.parse import urlsplit, urlunsplit

from ipfs_datasets_py.knowledge_graphs.storage import IPLDBackend

from ...ir_core.canonical import canonical_json_bytes
from ...ir_core.identity import cid_v1
from ..source_adapters.skillcenter import SkillCenterSkillRecord
from .ontology import (
    CORPUS_GRAPH_SCHEMA_VERSION,
    INTENT_GRAPH_ONTOLOGY_VERSION,
    CorpusEdgeKind,
    CorpusGraphEdge,
    CorpusGraphNode,
    CorpusGraphValidationError,
    CorpusNodeKind,
    IntentCorpusGraph,
    graph_projection_digest,
)


CORPUS_GRAPH_PROJECTOR_VERSION = "intent-corpus-projector/v1"
_MARKDOWN_HEADING_RE = re.compile(r"^[ \t]{0,3}(#{1,6})[ \t]+(.+?)\s*$")
_MARKDOWN_URL_RE = re.compile(r"\[[^\]\r\n]{1,512}\]\(([^)\s]+)\)")
_BARE_URL_RE = re.compile(r"https?://[^\s<>{}\[\]()\"']+")
_HEX_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class CorpusMention:
    """A caller-identified mention grounded in the record's ``skill_md``."""

    value: str
    kind: CorpusNodeKind
    start_byte: int
    end_byte: int
    properties: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.kind not in {
            CorpusNodeKind.TOOL_MENTION,
            CorpusNodeKind.ENTITY_MENTION,
        }:
            raise CorpusGraphValidationError(
                "CorpusMention.kind must be tool_mention or entity_mention"
            )
        if (
            not isinstance(self.value, str)
            or not self.value.strip()
            or len(self.value) > 512
        ):
            raise CorpusGraphValidationError(
                "CorpusMention.value must be bounded non-empty text"
            )
        _validate_span(self.start_byte, self.end_byte, label="CorpusMention")
        object.__setattr__(
            self, "properties", MappingProxyType(dict(self.properties))
        )


@dataclass(frozen=True, slots=True)
class CorpusCitation:
    """An explicitly extracted citation grounded in source byte offsets."""

    target_uri: str
    start_byte: int
    end_byte: int

    def __post_init__(self) -> None:
        if (
            not isinstance(self.target_uri, str)
            or not self.target_uri.strip()
            or len(self.target_uri) > 4096
        ):
            raise CorpusGraphValidationError(
                "CorpusCitation.target_uri must be bounded non-empty text"
            )
        _validate_span(self.start_byte, self.end_byte, label="CorpusCitation")


@dataclass(frozen=True, slots=True)
class CorpusProjectionInput:
    """One source record plus optional deterministic extraction evidence."""

    record: SkillCenterSkillRecord
    mentions: tuple[CorpusMention, ...] = ()
    citations: tuple[CorpusCitation, ...] = ()
    duplicate_of: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.record, SkillCenterSkillRecord):
            raise TypeError("CorpusProjectionInput.record must be a SkillCenterSkillRecord")
        object.__setattr__(self, "mentions", tuple(self.mentions))
        object.__setattr__(self, "citations", tuple(self.citations))
        object.__setattr__(
            self,
            "duplicate_of",
            tuple(sorted(set(str(value) for value in self.duplicate_of))),
        )


@dataclass(frozen=True, slots=True)
class CorpusNeighbor:
    """A non-semantic similarity edge backed by an addressed embedding result."""

    source_skill_id: str
    target_skill_id: str
    score: float
    embedding_cid: str
    embedding_digest: str = ""
    metric: str = "cosine"

    def __post_init__(self) -> None:
        if (
            not self.source_skill_id
            or not self.target_skill_id
            or self.source_skill_id == self.target_skill_id
        ):
            raise CorpusGraphValidationError(
                "CorpusNeighbor requires two different skill IDs"
            )
        if not math.isfinite(float(self.score)) or not 0.0 <= float(self.score) <= 1.0:
            raise CorpusGraphValidationError(
                "CorpusNeighbor.score must be finite and between zero and one"
            )
        if not isinstance(self.embedding_cid, str) or not self.embedding_cid.strip():
            raise CorpusGraphValidationError(
                "CorpusNeighbor.embedding_cid is required"
            )
        if self.embedding_digest:
            _qualified_digest(self.embedding_digest, label="embedding_digest")
        if not isinstance(self.metric, str) or not self.metric.strip():
            raise CorpusGraphValidationError("CorpusNeighbor.metric is required")


@runtime_checkable
class CorpusGraphStorage(Protocol):
    """The maintained IPLD operations required by this projector."""

    def store(
        self,
        data: bytes | str | dict[str, Any] | list[Any],
        pin: bool | None = None,
        codec: str = "dag-json",
    ) -> str:
        ...

    def store_graph(
        self,
        nodes: list[dict[str, Any]],
        relationships: list[dict[str, Any]],
        metadata: dict[str, Any] | None = None,
    ) -> str:
        ...


class IPLDCorpusGraphStorage:
    """Small adapter over the current ``knowledge_graphs.storage`` backend."""

    def __init__(self, backend: CorpusGraphStorage | None = None) -> None:
        self.backend = backend if backend is not None else IPLDBackend(
            database="intent-corpus"
        )

    def put_source_body(self, payload: bytes) -> str:
        return _stored_address(
            self.backend.store(payload, pin=True, codec="raw"),
            label="source body",
        )

    def put_embedding(self, payload: bytes) -> str:
        return _stored_address(
            self.backend.store(payload, pin=True, codec="raw"),
            label="embedding",
        )

    def put_graph(self, graph: IntentCorpusGraph) -> str:
        graph.validate()
        metadata = {
            "artifact_digest": graph.artifact_digest,
            "embedding_cids": list(graph.embedding_cids),
            "graph_digest": graph.graph_digest,
            "graph_id": graph.graph_id,
            "ontology_version": graph.ontology_version,
            "projector_version": CORPUS_GRAPH_PROJECTOR_VERSION,
            "schema_version": graph.schema_version,
            "source_body_cids": list(graph.source_body_cids),
            "source_digests": list(graph.source_digests),
        }
        return _stored_address(
            self.backend.store_graph(
                nodes=[node.to_dict() for node in graph.nodes],
                relationships=[edge.to_dict() for edge in graph.relationships],
                metadata=metadata,
            ),
            label="corpus graph",
        )


@dataclass(frozen=True, slots=True)
class StoredCorpusGraph:
    """Receipt for separately stored sources, embeddings, and graph data."""

    graph: IntentCorpusGraph
    graph_cid: str
    source_body_cids: Mapping[str, str]
    embedding_cids: Mapping[str, str]

    def __post_init__(self) -> None:
        self.graph.validate()
        _stored_address(self.graph_cid, label="corpus graph")
        object.__setattr__(
            self,
            "source_body_cids",
            MappingProxyType(dict(sorted(self.source_body_cids.items()))),
        )
        object.__setattr__(
            self,
            "embedding_cids",
            MappingProxyType(dict(sorted(self.embedding_cids.items()))),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "embedding_cids": dict(self.embedding_cids),
            "graph_artifact_digest": self.graph.artifact_digest,
            "graph_cid": self.graph_cid,
            "graph_digest": self.graph.graph_digest,
            "source_body_cids": dict(self.source_body_cids),
        }


@dataclass
class _NodeBuilder:
    kind: CorpusNodeKind
    source_digests: set[str]
    properties: dict[str, Any]
    source_body_cid: str = ""
    embedding_cid: str = ""


@dataclass
class _EdgeBuilder:
    kind: CorpusEdgeKind
    source_node_id: str
    target_node_id: str
    source_digests: set[str]
    properties: dict[str, Any]
    embedding_cid: str = ""


class CorpusGraphProjector:
    """Project bounded SkillCenter records into ``IntentCorpusGraph@1``."""

    version = CORPUS_GRAPH_PROJECTOR_VERSION
    ontology_version = INTENT_GRAPH_ONTOLOGY_VERSION
    schema_version = CORPUS_GRAPH_SCHEMA_VERSION

    def project(
        self,
        records: Iterable[SkillCenterSkillRecord | CorpusProjectionInput],
        *,
        policy_decisions: Mapping[str, Any] | None = None,
        source_body_cids: Mapping[str, str] | None = None,
        embedding_cids: Mapping[str, str] | None = None,
        neighbors: Iterable[CorpusNeighbor] = (),
    ) -> IntentCorpusGraph:
        """Return an order-independent graph with no embedded source bodies.

        Address maps accept a globally unique record key
        (``dataset@revision/file#skill``), ``skill_id:field``, or just
        ``skill_id`` for the primary ``skill_md`` body/embedding.
        """

        inputs = tuple(_coerce_projection_input(item) for item in records)
        if not inputs:
            raise CorpusGraphValidationError("records must not be empty")
        ordered = tuple(sorted(inputs, key=lambda item: _record_key(item.record)))
        record_keys = [_record_key(item.record) for item in ordered]
        if len(set(record_keys)) != len(record_keys):
            raise CorpusGraphValidationError(
                "records contain duplicate immutable source identities"
            )
        source_addresses = dict(source_body_cids or {})
        vector_addresses = dict(embedding_cids or {})
        policy_by_id = dict(policy_decisions or {})

        nodes: dict[str, _NodeBuilder] = {}
        edges: dict[str, _EdgeBuilder] = {}
        skills_by_lookup: dict[str, str] = {}
        skill_sources: dict[str, tuple[str, ...]] = {}
        skill_primary_sources: dict[str, str] = {}
        skill_content_digests: dict[str, str] = {}
        explicit_duplicates: list[tuple[str, str]] = []

        for item in ordered:
            record = item.record
            record_key = _record_key(record)
            _validate_record(record)
            document_digest = _qualified_digest(
                record.content_sha256, label=f"{record.skill_id}.content_sha256"
            )
            bundle_digest = _qualified_digest(
                record.bundle_sha256, label=f"{record.skill_id}.bundle_sha256"
            )
            primary_body_cid = _address_for(
                source_addresses,
                record,
                "skill_md",
                fallback=cid_v1(record.skill_md.encode("utf-8")),
            )
            embedding_cid = _address_for(
                vector_addresses,
                record,
                "embedding",
                fallback="",
            )

            dataset_id = _stable_id(
                "dataset-revision",
                {
                    "dataset_id": record.dataset_id,
                    "revision": record.dataset_revision,
                },
            )
            bundle_id = _stable_id(
                "bundle",
                {
                    "dataset_revision": dataset_id,
                    "repository_file": record.repository_file,
                    "sha256": bundle_digest,
                },
            )
            skill_id = _stable_id("skill", {"source": record_key})
            primary_document_id = ""

            _add_node(
                nodes,
                dataset_id,
                CorpusNodeKind.DATASET_REVISION,
                (bundle_digest,),
                {
                    "dataset_id": record.dataset_id,
                    "revision": record.dataset_revision,
                },
            )
            _add_node(
                nodes,
                bundle_id,
                CorpusNodeKind.BUNDLE,
                (bundle_digest,),
                {
                    "dataset_id": record.dataset_id,
                    "repository_file": record.repository_file,
                },
            )
            _add_edge(
                edges,
                CorpusEdgeKind.CONTAINS,
                dataset_id,
                bundle_id,
                (bundle_digest,),
            )

            publisher_value = record.dataset_id.split("/", 1)[0]
            publisher_id = _stable_id(
                "author-publisher", {"publisher": publisher_value}
            )
            _add_node(
                nodes,
                publisher_id,
                CorpusNodeKind.AUTHOR_PUBLISHER,
                (bundle_digest,),
                {"name": publisher_value, "role": "dataset_publisher"},
            )
            _add_edge(
                edges,
                CorpusEdgeKind.CONTAINS,
                publisher_id,
                dataset_id,
                (bundle_digest,),
            )

            repository_id, repository_properties = _repository(record.source_url)
            if repository_id:
                _add_node(
                    nodes,
                    repository_id,
                    CorpusNodeKind.REPOSITORY,
                    (bundle_digest,),
                    repository_properties,
                )

            role_documents: dict[str, tuple[str, str, str]] = {}
            for role, body in (
                ("skill_md", record.skill_md),
                ("metadata_yaml", record.metadata_yaml),
                ("library_md", record.library_md),
            ):
                if not body:
                    continue
                payload = body.encode("utf-8")
                role_digest = _qualified_digest(
                    hashlib.sha256(payload).hexdigest(),
                    label=f"{record.skill_id}.{role}",
                )
                body_cid = _address_for(
                    source_addresses,
                    record,
                    role,
                    fallback=(
                        primary_body_cid if role == "skill_md" else cid_v1(payload)
                    ),
                )
                document_id = _stable_id(
                    "source-document",
                    {
                        "record": record_key,
                        "role": role,
                        "sha256": role_digest,
                    },
                )
                role_documents[role] = (document_id, role_digest, body_cid)
                if role == "skill_md":
                    primary_document_id = document_id
                _add_node(
                    nodes,
                    document_id,
                    CorpusNodeKind.SOURCE_DOCUMENT,
                    (role_digest, bundle_digest),
                    {
                        "container_file": record.repository_file,
                        "document_role": {
                            "skill_md": "primary_markdown",
                            "metadata_yaml": "metadata",
                            "library_md": "library_markdown",
                        }[role],
                        "language": record.language,
                        "source_id": record.source_id or record.skill_id,
                        "source_revision": record.dataset_revision,
                        "source_uri": record.source_url,
                    },
                    source_body_cid=body_cid,
                    embedding_cid=embedding_cid if role == "skill_md" else "",
                )
                _add_edge(
                    edges,
                    CorpusEdgeKind.CONTAINS,
                    bundle_id,
                    document_id,
                    (role_digest, bundle_digest),
                )
                if repository_id:
                    _add_edge(
                        edges,
                        CorpusEdgeKind.CONTAINS,
                        repository_id,
                        document_id,
                        (role_digest, bundle_digest),
                    )
                    _add_edge(
                        edges,
                        CorpusEdgeKind.DERIVED_FROM,
                        document_id,
                        repository_id,
                        (role_digest, bundle_digest),
                    )

            if not primary_document_id:
                raise CorpusGraphValidationError(
                    f"{record.skill_id!r} has no primary source document"
                )
            policy_properties = _bounded_policy_properties(
                policy_by_id.get(record_key, policy_by_id.get(record.skill_id))
            )
            skill_properties = {
                "kind": record.skill_kind,
                "language": record.language,
                "primary_source_id": record.primary_source_id,
                "profile": record.profile,
                "source_type": record.source_type,
                "title": record.title,
                **policy_properties,
            }
            if record.overall_score is not None:
                skill_properties["overall_score"] = record.overall_score
            _add_node(
                nodes,
                skill_id,
                CorpusNodeKind.SKILL,
                (document_digest, bundle_digest),
                skill_properties,
                source_body_cid=primary_body_cid,
                embedding_cid=embedding_cid,
            )
            _add_edge(
                edges,
                CorpusEdgeKind.CONTAINS,
                bundle_id,
                skill_id,
                (document_digest, bundle_digest),
            )
            for document_id, role_digest, _ in role_documents.values():
                _add_edge(
                    edges,
                    CorpusEdgeKind.DERIVED_FROM,
                    skill_id,
                    document_id,
                    (role_digest, bundle_digest),
                )

            domain_value = (record.domain.strip() or "unknown").casefold()
            domain_id = _stable_id("domain", {"name": domain_value})
            _add_node(
                nodes,
                domain_id,
                CorpusNodeKind.DOMAIN,
                (bundle_digest,),
                {"name": domain_value},
            )
            _add_edge(
                edges,
                CorpusEdgeKind.HAS_DOMAIN,
                skill_id,
                domain_id,
                (bundle_digest,),
            )

            license_value = record.license_expression.strip() or "UNKNOWN"
            license_id = _stable_id(
                "license", {"expression": license_value.casefold()}
            )
            license_properties = {"expression": license_value}
            _add_node(
                nodes,
                license_id,
                CorpusNodeKind.LICENSE,
                (bundle_digest,),
                license_properties,
            )
            _add_edge(
                edges,
                CorpusEdgeKind.HAS_LICENSE,
                skill_id,
                license_id,
                (bundle_digest,),
                (
                    {"license_decision": policy_properties["license_decision"]}
                    if "license_decision" in policy_properties
                    else None
                ),
            )

            for section in _markdown_sections(record.skill_md):
                section_id = _stable_id(
                    "section",
                    {
                        "document": primary_document_id,
                        "end_byte": section[2],
                        "start_byte": section[1],
                    },
                )
                span_id = _stable_id(
                    "source-span",
                    {
                        "document": primary_document_id,
                        "end_byte": section[2],
                        "start_byte": section[1],
                    },
                )
                section_properties = {
                    "end_byte": section[2],
                    "heading_level": section[3],
                    "start_byte": section[1],
                    "title": section[0],
                }
                _add_node(
                    nodes,
                    section_id,
                    CorpusNodeKind.SECTION,
                    (document_digest,),
                    section_properties,
                    source_body_cid=primary_body_cid,
                )
                _add_node(
                    nodes,
                    span_id,
                    CorpusNodeKind.SOURCE_SPAN,
                    (document_digest,),
                    {
                        "end_byte": section[2],
                        "start_byte": section[1],
                    },
                    source_body_cid=primary_body_cid,
                )
                _add_edge(
                    edges,
                    CorpusEdgeKind.CONTAINS,
                    skill_id,
                    section_id,
                    (document_digest,),
                )
                _add_edge(
                    edges,
                    CorpusEdgeKind.DERIVED_FROM,
                    section_id,
                    primary_document_id,
                    (document_digest,),
                )
                _add_edge(
                    edges,
                    CorpusEdgeKind.CONTAINS,
                    section_id,
                    span_id,
                    (document_digest,),
                )

            citations = (*_markdown_citations(record.skill_md), *item.citations)
            for citation in sorted(
                set(citations),
                key=lambda value: (
                    value.start_byte,
                    value.end_byte,
                    value.target_uri,
                ),
            ):
                _validate_grounding(
                    citation.start_byte,
                    citation.end_byte,
                    record.skill_md,
                    label="citation",
                )
                cited_bytes = record.skill_md.encode("utf-8")[
                    citation.start_byte : citation.end_byte
                ]
                try:
                    cited_value = cited_bytes.decode("utf-8")
                except UnicodeDecodeError as exc:
                    raise CorpusGraphValidationError(
                        "citation offsets must align to UTF-8 code point boundaries"
                    ) from exc
                if cited_value != citation.target_uri:
                    raise CorpusGraphValidationError(
                        "citation target_uri must exactly match its grounded span"
                    )
                span_id = _span_node(
                    nodes,
                    edges,
                    primary_document_id,
                    document_digest,
                    primary_body_cid,
                    citation.start_byte,
                    citation.end_byte,
                )
                target_uri = _normalized_uri(citation.target_uri)
                target_id = _stable_id(
                    "cited-source-document", {"uri": target_uri}
                )
                _add_node(
                    nodes,
                    target_id,
                    CorpusNodeKind.SOURCE_DOCUMENT,
                    (document_digest,),
                    {"external": True, "source_uri": target_uri},
                )
                _add_edge(
                    edges,
                    CorpusEdgeKind.CITES,
                    span_id,
                    target_id,
                    (document_digest,),
                )

            for mention in item.mentions:
                _validate_grounding(
                    mention.start_byte,
                    mention.end_byte,
                    record.skill_md,
                    label="mention",
                )
                mentioned_bytes = record.skill_md.encode("utf-8")[
                    mention.start_byte : mention.end_byte
                ]
                try:
                    mentioned_value = mentioned_bytes.decode("utf-8")
                except UnicodeDecodeError as exc:
                    raise CorpusGraphValidationError(
                        "mention offsets must align to UTF-8 code point boundaries"
                    ) from exc
                if mentioned_value != mention.value:
                    raise CorpusGraphValidationError(
                        "mention value must exactly match its grounded span"
                    )
                span_id = _span_node(
                    nodes,
                    edges,
                    primary_document_id,
                    document_digest,
                    primary_body_cid,
                    mention.start_byte,
                    mention.end_byte,
                )
                mention_id = _stable_id(
                    mention.kind.value,
                    {
                        "kind": mention.kind.value,
                        "properties": dict(mention.properties),
                        "value": mention.value.casefold(),
                    },
                )
                _add_node(
                    nodes,
                    mention_id,
                    mention.kind,
                    (document_digest,),
                    {"name": mention.value, **dict(mention.properties)},
                )
                _add_edge(
                    edges,
                    CorpusEdgeKind.MENTIONS,
                    span_id,
                    mention_id,
                    (document_digest,),
                )

            skills_by_lookup[record_key] = skill_id
            if record.skill_id not in skills_by_lookup:
                skills_by_lookup[record.skill_id] = skill_id
            else:
                # An ambiguous short ID must not resolve silently.
                skills_by_lookup[record.skill_id] = ""
            skill_sources[skill_id] = (document_digest, bundle_digest)
            skill_primary_sources[skill_id] = record.primary_source_id.strip()
            skill_content_digests[skill_id] = document_digest
            explicit_duplicates.extend(
                (skill_id, target) for target in item.duplicate_of
            )

        self._add_pair_relationships(
            edges,
            skill_sources,
            skill_primary_sources,
            CorpusEdgeKind.SAME_PRIMARY_SOURCE,
        )
        self._add_pair_relationships(
            edges,
            skill_sources,
            skill_content_digests,
            CorpusEdgeKind.DUPLICATE_OF,
        )
        for source_id, target_lookup in explicit_duplicates:
            target_id = _resolve_skill(target_lookup, skills_by_lookup)
            _add_symmetric_edge(
                edges,
                CorpusEdgeKind.DUPLICATE_OF,
                source_id,
                target_id,
                (*skill_sources[source_id], *skill_sources[target_id]),
                {"explicit": True},
            )
        for neighbor in sorted(
            neighbors,
            key=lambda item: (
                item.source_skill_id,
                item.target_skill_id,
                item.metric,
                item.score,
            ),
        ):
            source_id = _resolve_skill(neighbor.source_skill_id, skills_by_lookup)
            target_id = _resolve_skill(neighbor.target_skill_id, skills_by_lookup)
            digests = [
                *skill_sources[source_id],
                *skill_sources[target_id],
            ]
            if neighbor.embedding_digest:
                digests.append(neighbor.embedding_digest)
            _add_symmetric_edge(
                edges,
                CorpusEdgeKind.NEIGHBOR_OF,
                source_id,
                target_id,
                digests,
                {
                    "metric": neighbor.metric,
                    "score": float(neighbor.score),
                    "semantic_assertion": False,
                },
                embedding_cid=neighbor.embedding_cid,
            )

        return _seal_graph(nodes, edges)

    def project_and_store(
        self,
        records: Iterable[SkillCenterSkillRecord | CorpusProjectionInput],
        *,
        storage: IPLDCorpusGraphStorage | CorpusGraphStorage | None = None,
        embeddings: Mapping[str, bytes] | None = None,
        embedding_cids: Mapping[str, str] | None = None,
        policy_decisions: Mapping[str, Any] | None = None,
        neighbors: Iterable[CorpusNeighbor] = (),
    ) -> StoredCorpusGraph:
        """Store all source/embedding bytes separately, then store the graph."""

        inputs = tuple(_coerce_projection_input(item) for item in records)
        if not inputs:
            raise CorpusGraphValidationError("records must not be empty")
        adapter = (
            storage
            if isinstance(storage, IPLDCorpusGraphStorage)
            else IPLDCorpusGraphStorage(storage)
        )
        source_addresses: dict[str, str] = {}
        for item in sorted(inputs, key=lambda value: _record_key(value.record)):
            record = item.record
            for role, body in (
                ("skill_md", record.skill_md),
                ("metadata_yaml", record.metadata_yaml),
                ("library_md", record.library_md),
            ):
                if not body:
                    continue
                key = f"{_record_key(record)}:{role}"
                source_addresses[key] = adapter.put_source_body(
                    body.encode("utf-8")
                )

        vector_addresses = dict(embedding_cids or {})
        for key, payload in sorted((embeddings or {}).items()):
            if not isinstance(payload, (bytes, bytearray, memoryview)):
                raise TypeError("embedding payloads must be bytes-like")
            if key in vector_addresses:
                raise CorpusGraphValidationError(
                    f"embedding {key!r} has both bytes and a pre-existing address"
                )
            vector_addresses[key] = adapter.put_embedding(bytes(payload))

        graph = self.project(
            inputs,
            policy_decisions=policy_decisions,
            source_body_cids=source_addresses,
            embedding_cids=vector_addresses,
            neighbors=neighbors,
        )
        graph_cid = adapter.put_graph(graph)
        return StoredCorpusGraph(
            graph=graph,
            graph_cid=graph_cid,
            source_body_cids=source_addresses,
            embedding_cids=vector_addresses,
        )

    @staticmethod
    def _add_pair_relationships(
        edges: dict[str, _EdgeBuilder],
        skill_sources: Mapping[str, tuple[str, ...]],
        group_by_skill: Mapping[str, str],
        kind: CorpusEdgeKind,
    ) -> None:
        groups: dict[str, list[str]] = defaultdict(list)
        for skill_id, group in group_by_skill.items():
            if group:
                groups[group].append(skill_id)
        for group, skill_ids in sorted(groups.items()):
            ordered = sorted(skill_ids)
            for index, source_id in enumerate(ordered):
                for target_id in ordered[index + 1 :]:
                    _add_symmetric_edge(
                        edges,
                        kind,
                        source_id,
                        target_id,
                        (*skill_sources[source_id], *skill_sources[target_id]),
                        {"group_digest": _stable_digest({"group": group})},
                    )


def _coerce_projection_input(
    value: SkillCenterSkillRecord | CorpusProjectionInput,
) -> CorpusProjectionInput:
    if isinstance(value, CorpusProjectionInput):
        return value
    if isinstance(value, SkillCenterSkillRecord):
        return CorpusProjectionInput(record=value)
    raise TypeError(
        "records must contain SkillCenterSkillRecord or CorpusProjectionInput"
    )


def _record_key(record: SkillCenterSkillRecord) -> str:
    return (
        f"{record.dataset_id}@{record.dataset_revision}/"
        f"{record.repository_file}#{record.skill_id}"
    )


def _validate_record(record: SkillCenterSkillRecord) -> None:
    for label, value in (
        ("skill_id", record.skill_id),
        ("dataset_id", record.dataset_id),
        ("dataset_revision", record.dataset_revision),
        ("repository_file", record.repository_file),
        ("title", record.title),
        ("skill_md", record.skill_md),
    ):
        if not isinstance(value, str) or not value.strip():
            raise CorpusGraphValidationError(
                f"SkillCenter record {label} must not be empty"
            )
    actual = hashlib.sha256(record.skill_md.encode("utf-8")).hexdigest()
    if actual != record.content_sha256:
        raise CorpusGraphValidationError(
            f"{record.skill_id!r} content_sha256 does not match skill_md"
        )
    _qualified_digest(record.bundle_sha256, label="bundle_sha256")
    if record.overall_score is not None and not math.isfinite(record.overall_score):
        raise CorpusGraphValidationError("overall_score must be finite")


def _qualified_digest(value: str, *, label: str) -> str:
    if not isinstance(value, str):
        raise CorpusGraphValidationError(f"{label} must be a SHA-256 digest")
    digest = value if value.startswith("sha256:") else f"sha256:{value}"
    if _HEX_DIGEST_RE.fullmatch(digest.removeprefix("sha256:")) is None:
        raise CorpusGraphValidationError(
            f"{label} must be 64 lowercase hexadecimal characters"
        )
    return digest


def _stable_digest(value: Mapping[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _stable_id(namespace: str, value: Mapping[str, Any]) -> str:
    digest = hashlib.sha256(canonical_json_bytes(value)).hexdigest()
    return f"intent-corpus:{namespace}:{digest[:32]}"


def _address_for(
    addresses: Mapping[str, str],
    record: SkillCenterSkillRecord,
    role: str,
    *,
    fallback: str,
) -> str:
    keys = (
        f"{_record_key(record)}:{role}",
        f"{record.skill_id}:{role}",
        record.skill_id if role in {"skill_md", "embedding"} else "",
    )
    for key in keys:
        if key and key in addresses:
            return _stored_address(addresses[key], label=f"{record.skill_id}:{role}")
    return fallback


def _stored_address(value: Any, *, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or value.strip() != value
        or "\x00" in value
        or len(value) > 1024
    ):
        raise CorpusGraphValidationError(
            f"{label} storage must return a bounded immutable address"
        )
    return value


def _add_node(
    nodes: dict[str, _NodeBuilder],
    node_id: str,
    kind: CorpusNodeKind,
    source_digests: Sequence[str],
    properties: Mapping[str, Any],
    *,
    source_body_cid: str = "",
    embedding_cid: str = "",
) -> None:
    normalized = {_qualified_digest(value, label="node source") for value in source_digests}
    candidate_properties = dict(properties)
    current = nodes.get(node_id)
    if current is None:
        nodes[node_id] = _NodeBuilder(
            kind=kind,
            source_digests=normalized,
            properties=candidate_properties,
            source_body_cid=source_body_cid,
            embedding_cid=embedding_cid,
        )
        return
    if (
        current.kind is not kind
        or current.properties != candidate_properties
        or current.source_body_cid != source_body_cid
        or current.embedding_cid != embedding_cid
    ):
        raise CorpusGraphValidationError(
            f"conflicting definitions for graph node {node_id!r}"
        )
    current.source_digests.update(normalized)


def _edge_id(
    kind: CorpusEdgeKind,
    source_node_id: str,
    target_node_id: str,
    properties: Mapping[str, Any],
    embedding_cid: str,
) -> str:
    return _stable_id(
        "edge",
        {
            "embedding_cid": embedding_cid,
            "properties": dict(properties),
            "source": source_node_id,
            "target": target_node_id,
            "type": kind.value,
        },
    )


def _add_edge(
    edges: dict[str, _EdgeBuilder],
    kind: CorpusEdgeKind,
    source_node_id: str,
    target_node_id: str,
    source_digests: Sequence[str],
    properties: Mapping[str, Any] | None = None,
    *,
    embedding_cid: str = "",
) -> None:
    candidate_properties = dict(properties or {})
    edge_id = _edge_id(
        kind,
        source_node_id,
        target_node_id,
        candidate_properties,
        embedding_cid,
    )
    normalized = {_qualified_digest(value, label="edge source") for value in source_digests}
    current = edges.get(edge_id)
    if current is None:
        edges[edge_id] = _EdgeBuilder(
            kind=kind,
            source_node_id=source_node_id,
            target_node_id=target_node_id,
            source_digests=normalized,
            properties=candidate_properties,
            embedding_cid=embedding_cid,
        )
        return
    current.source_digests.update(normalized)


def _add_symmetric_edge(
    edges: dict[str, _EdgeBuilder],
    kind: CorpusEdgeKind,
    source_node_id: str,
    target_node_id: str,
    source_digests: Sequence[str],
    properties: Mapping[str, Any] | None = None,
    *,
    embedding_cid: str = "",
) -> None:
    source_node_id, target_node_id = sorted((source_node_id, target_node_id))
    _add_edge(
        edges,
        kind,
        source_node_id,
        target_node_id,
        source_digests,
        properties,
        embedding_cid=embedding_cid,
    )


def _seal_graph(
    node_builders: Mapping[str, _NodeBuilder],
    edge_builders: Mapping[str, _EdgeBuilder],
) -> IntentCorpusGraph:
    nodes = tuple(
        CorpusGraphNode(
            node_id=node_id,
            kind=builder.kind,
            source_digests=tuple(builder.source_digests),
            graph_digest="",
            properties=builder.properties,
            source_body_cid=builder.source_body_cid,
            embedding_cid=builder.embedding_cid,
        )
        for node_id, builder in sorted(node_builders.items())
    )
    relationships = tuple(
        CorpusGraphEdge(
            edge_id=edge_id,
            kind=builder.kind,
            source_node_id=builder.source_node_id,
            target_node_id=builder.target_node_id,
            source_digests=tuple(builder.source_digests),
            graph_digest="",
            properties=builder.properties,
            embedding_cid=builder.embedding_cid,
        )
        for edge_id, builder in sorted(edge_builders.items())
    )
    digest = graph_projection_digest(nodes, relationships)
    graph = IntentCorpusGraph(
        graph_digest=digest,
        nodes=tuple(replace(node, graph_digest=digest) for node in nodes),
        relationships=tuple(
            replace(edge, graph_digest=digest) for edge in relationships
        ),
    )
    return graph.validate()


def _repository(source_url: str) -> tuple[str, dict[str, Any]]:
    if not source_url:
        return "", {}
    parsed = urlsplit(source_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return "", {}
    path_parts = [part for part in parsed.path.split("/") if part]
    repository_path = "/".join(path_parts[:2])
    if not repository_path:
        return "", {}
    uri = urlunsplit(
        (
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            f"/{repository_path}",
            "",
            "",
        )
    )
    return _stable_id("repository", {"uri": uri}), {
        "host": parsed.netloc.lower(),
        "repository_path": repository_path,
        "source_uri": uri,
    }


def _markdown_sections(value: str) -> tuple[tuple[str, int, int, int], ...]:
    encoded_length = len(value.encode("utf-8"))
    headings: list[tuple[str, int, int]] = []
    byte_offset = 0
    for line in value.splitlines(keepends=True):
        match = _MARKDOWN_HEADING_RE.match(line.rstrip("\r\n"))
        if match:
            headings.append(
                (
                    match.group(2).strip()[:512],
                    byte_offset,
                    len(match.group(1)),
                )
            )
        byte_offset += len(line.encode("utf-8"))
    if not headings:
        return (("document", 0, encoded_length, 0),)
    result: list[tuple[str, int, int, int]] = []
    if headings[0][1] > 0:
        result.append(("preamble", 0, headings[0][1], 0))
    for index, (title, start_byte, level) in enumerate(headings):
        end_byte = (
            headings[index + 1][1]
            if index + 1 < len(headings)
            else encoded_length
        )
        result.append((title, start_byte, end_byte, level))
    return tuple(result)


def _markdown_citations(value: str) -> tuple[CorpusCitation, ...]:
    citations: set[CorpusCitation] = set()
    for pattern in (_MARKDOWN_URL_RE, _BARE_URL_RE):
        for match in pattern.finditer(value):
            url = match.group(1) if pattern is _MARKDOWN_URL_RE else match.group(0)
            stripped = url.rstrip(".,;:!?")
            if not stripped:
                continue
            char_start = match.start(1) if pattern is _MARKDOWN_URL_RE else match.start()
            char_end = char_start + len(stripped)
            start_byte = len(value[:char_start].encode("utf-8"))
            end_byte = len(value[:char_end].encode("utf-8"))
            citations.add(
                CorpusCitation(
                    target_uri=stripped,
                    start_byte=start_byte,
                    end_byte=end_byte,
                )
            )
    return tuple(citations)


def _normalized_uri(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise CorpusGraphValidationError(
            f"citation target must be an absolute HTTP(S) URI: {value!r}"
        )
    return urlunsplit(
        (
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            parsed.path or "/",
            parsed.query,
            "",
        )
    )


def _validate_span(start_byte: int, end_byte: int, *, label: str) -> None:
    if (
        isinstance(start_byte, bool)
        or isinstance(end_byte, bool)
        or not isinstance(start_byte, int)
        or not isinstance(end_byte, int)
        or start_byte < 0
        or end_byte <= start_byte
    ):
        raise CorpusGraphValidationError(
            f"{label} byte offsets must form a non-empty half-open span"
        )


def _validate_grounding(
    start_byte: int,
    end_byte: int,
    source: str,
    *,
    label: str,
) -> None:
    _validate_span(start_byte, end_byte, label=label)
    if end_byte > len(source.encode("utf-8")):
        raise CorpusGraphValidationError(
            f"{label} byte span exceeds the primary source body"
        )


def _span_node(
    nodes: dict[str, _NodeBuilder],
    edges: dict[str, _EdgeBuilder],
    document_id: str,
    document_digest: str,
    source_body_cid: str,
    start_byte: int,
    end_byte: int,
) -> str:
    span_id = _stable_id(
        "source-span",
        {
            "document": document_id,
            "end_byte": end_byte,
            "start_byte": start_byte,
        },
    )
    _add_node(
        nodes,
        span_id,
        CorpusNodeKind.SOURCE_SPAN,
        (document_digest,),
        {"end_byte": end_byte, "start_byte": start_byte},
        source_body_cid=source_body_cid,
    )
    _add_edge(
        edges,
        CorpusEdgeKind.CONTAINS,
        document_id,
        span_id,
        (document_digest,),
    )
    return span_id


def _resolve_skill(value: str, lookup: Mapping[str, str]) -> str:
    resolved = lookup.get(value)
    if not resolved:
        reason = "ambiguous" if value in lookup else "unknown"
        raise CorpusGraphValidationError(
            f"{reason} skill reference {value!r}"
        )
    return resolved


def _bounded_policy_properties(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    payload = value.to_dict() if hasattr(value, "to_dict") else value
    if not isinstance(payload, Mapping):
        raise CorpusGraphValidationError(
            "policy decisions must be mappings or expose to_dict()"
        )
    result: dict[str, Any] = {}
    for key in ("allowed_use", "policy_version", "trust_decision"):
        item = payload.get(key)
        if isinstance(item, str) and item:
            result[key] = item
    license_value = payload.get("license_decision")
    if isinstance(license_value, Mapping):
        bounded_license: dict[str, Any] = {}
        for key in ("allowed_use", "reason_code", "status"):
            item = license_value.get(key)
            if isinstance(item, str) and item:
                bounded_license[key] = item
        if bounded_license:
            result["license_decision"] = bounded_license
    return result


# Name used by the objective's AST query and a concise functional facade.
IntentCorpusGraphProjector = CorpusGraphProjector


def project_corpus_graph(
    records: Iterable[SkillCenterSkillRecord | CorpusProjectionInput],
    **kwargs: Any,
) -> IntentCorpusGraph:
    return CorpusGraphProjector().project(records, **kwargs)


__all__ = [
    "CORPUS_GRAPH_PROJECTOR_VERSION",
    "CorpusCitation",
    "CorpusGraphProjector",
    "CorpusGraphStorage",
    "CorpusMention",
    "CorpusNeighbor",
    "CorpusProjectionInput",
    "IPLDCorpusGraphStorage",
    "IntentCorpusGraphProjector",
    "StoredCorpusGraph",
    "project_corpus_graph",
]
