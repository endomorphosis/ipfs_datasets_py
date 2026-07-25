"""Deterministic projection of SkillCenter records into a corpus graph.

This is a thin data adapter: it never executes or semantically interprets
source instructions and never generates embeddings.  Source fields and
optional embedding bytes are content-addressed separately; only their
immutable addresses and digests enter the graph identity.
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
_HEADING_RE = re.compile(r"^[ \t]{0,3}(#{1,6})[ \t]+(.+?)\s*$")
_MARKDOWN_URL_RE = re.compile(r"\[[^\]\r\n]{1,512}\]\(([^)\s]+)\)")
_BARE_URL_RE = re.compile(r"https?://[^\s<>{}\[\]()\"']+")
_HEX_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class CorpusMention:
    """A caller-identified mention grounded in primary-source byte offsets."""

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
        if not isinstance(self.value, str) or not self.value.strip():
            raise CorpusGraphValidationError("CorpusMention.value must not be empty")
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
        if not isinstance(self.target_uri, str) or not self.target_uri.strip():
            raise CorpusGraphValidationError(
                "CorpusCitation.target_uri must not be empty"
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
            raise TypeError(
                "CorpusProjectionInput.record must be a SkillCenterSkillRecord"
            )
        object.__setattr__(self, "mentions", tuple(self.mentions))
        object.__setattr__(self, "citations", tuple(self.citations))
        object.__setattr__(
            self,
            "duplicate_of",
            tuple(sorted(set(str(value) for value in self.duplicate_of))),
        )


@dataclass(frozen=True, slots=True)
class CorpusNeighbor:
    """A similarity edge backed by a separately addressed embedding result."""

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
        if not math.isfinite(float(self.score)) or not 0 <= float(self.score) <= 1:
            raise CorpusGraphValidationError(
                "CorpusNeighbor.score must be finite and between zero and one"
            )
        _stored_address(self.embedding_cid, label="neighbor embedding")
        if self.embedding_digest:
            _qualified_digest(self.embedding_digest, label="embedding_digest")
        if not isinstance(self.metric, str) or not self.metric.strip():
            raise CorpusGraphValidationError("CorpusNeighbor.metric is required")


@runtime_checkable
class CorpusGraphStorage(Protocol):
    """Maintained IPLD backend operations used by the projector."""

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
    """Adapter over the current :mod:`knowledge_graphs.storage` backend."""

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
        return _stored_address(
            self.backend.store_graph(
                nodes=[node.to_dict() for node in graph.nodes],
                relationships=[edge.to_dict() for edge in graph.relationships],
                metadata={
                    "artifact_digest": graph.artifact_digest,
                    "embedding_cids": list(graph.embedding_cids),
                    "graph_digest": graph.graph_digest,
                    "graph_id": graph.graph_id,
                    "ontology_version": graph.ontology_version,
                    "projector_version": CORPUS_GRAPH_PROJECTOR_VERSION,
                    "schema_version": graph.schema_version,
                    "source_body_cids": list(graph.source_body_cids),
                    "source_digests": list(graph.source_digests),
                },
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
class _Node:
    kind: CorpusNodeKind
    source_digests: set[str]
    properties: dict[str, Any]
    source_body_cid: str = ""
    embedding_cid: str = ""


@dataclass
class _Edge:
    kind: CorpusEdgeKind
    source: str
    target: str
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
        """Return an order-independent graph containing no source bodies."""

        inputs = tuple(_input(item) for item in records)
        if not inputs:
            raise CorpusGraphValidationError("records must not be empty")
        inputs = tuple(sorted(inputs, key=lambda item: _record_key(item.record)))
        if len({_record_key(item.record) for item in inputs}) != len(inputs):
            raise CorpusGraphValidationError(
                "records contain duplicate immutable source identities"
            )

        nodes: dict[str, _Node] = {}
        edges: dict[str, _Edge] = {}
        source_addresses = dict(source_body_cids or {})
        vector_addresses = dict(embedding_cids or {})
        policies = dict(policy_decisions or {})
        lookup: dict[str, str] = {}
        skill_sources: dict[str, tuple[str, ...]] = {}
        family_groups: dict[str, str] = {}
        content_groups: dict[str, str] = {}
        explicit_duplicates: list[tuple[str, str]] = []

        for item in inputs:
            record = item.record
            _validate_record(record)
            record_key = _record_key(record)
            body_digest = _qualified_digest(
                record.content_sha256, label="content_sha256"
            )
            bundle_digest = _qualified_digest(
                record.bundle_sha256, label="bundle_sha256"
            )
            source_set = (body_digest, bundle_digest)
            primary_cid = _address_for(
                source_addresses,
                record,
                "skill_md",
                fallback=cid_v1(record.skill_md.encode()),
            )
            embedding_cid = _address_for(
                vector_addresses, record, "embedding", fallback=""
            )

            dataset_id = _id(
                "dataset-revision",
                {"dataset": record.dataset_id, "revision": record.dataset_revision},
            )
            bundle_id = _id(
                "bundle",
                {
                    "dataset": dataset_id,
                    "file": record.repository_file,
                    "digest": bundle_digest,
                },
            )
            skill_id = _id("skill", {"record": record_key})
            publisher = record.dataset_id.split("/", 1)[0]
            publisher_id = _id("publisher", {"name": publisher})
            repository_id, repository_properties = _repository(record.source_url)

            _add_node(
                nodes,
                dataset_id,
                CorpusNodeKind.DATASET_REVISION,
                (bundle_digest,),
                {"dataset_id": record.dataset_id, "revision": record.dataset_revision},
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
            _add_node(
                nodes,
                publisher_id,
                CorpusNodeKind.AUTHOR_PUBLISHER,
                (bundle_digest,),
                {"name": publisher, "role": "dataset_publisher"},
            )
            _add_edge(
                edges, CorpusEdgeKind.CONTAINS, publisher_id, dataset_id, source_set
            )
            _add_edge(
                edges, CorpusEdgeKind.CONTAINS, dataset_id, bundle_id, source_set
            )
            if repository_id:
                _add_node(
                    nodes,
                    repository_id,
                    CorpusNodeKind.REPOSITORY,
                    source_set,
                    repository_properties,
                )

            documents: dict[str, tuple[str, str, str]] = {}
            for role, body in (
                ("skill_md", record.skill_md),
                ("metadata_yaml", record.metadata_yaml),
                ("library_md", record.library_md),
            ):
                if not body:
                    continue
                digest = _qualified_digest(
                    hashlib.sha256(body.encode()).hexdigest(), label=f"{role} digest"
                )
                address = _address_for(
                    source_addresses,
                    record,
                    role,
                    fallback=(
                        primary_cid
                        if role == "skill_md"
                        else cid_v1(body.encode())
                    ),
                )
                document_id = _id(
                    "source-document",
                    {"record": record_key, "role": role, "digest": digest},
                )
                documents[role] = (document_id, digest, address)
                _add_node(
                    nodes,
                    document_id,
                    CorpusNodeKind.SOURCE_DOCUMENT,
                    (digest, bundle_digest),
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
                    source_body_cid=address,
                    embedding_cid=embedding_cid if role == "skill_md" else "",
                )
                _add_edge(
                    edges,
                    CorpusEdgeKind.CONTAINS,
                    bundle_id,
                    document_id,
                    (digest, bundle_digest),
                )
                if repository_id:
                    _add_edge(
                        edges,
                        CorpusEdgeKind.CONTAINS,
                        repository_id,
                        document_id,
                        (digest, bundle_digest),
                    )
                    _add_edge(
                        edges,
                        CorpusEdgeKind.DERIVED_FROM,
                        document_id,
                        repository_id,
                        (digest, bundle_digest),
                    )
            primary_document_id, _, _ = documents["skill_md"]

            properties = {
                "kind": record.skill_kind,
                "language": record.language,
                "primary_source_id": record.primary_source_id,
                "profile": record.profile,
                "source_type": record.source_type,
                "title": record.title,
                **_policy_properties(
                    policies.get(record_key, policies.get(record.skill_id))
                ),
            }
            if record.overall_score is not None:
                properties["overall_score"] = record.overall_score
            _add_node(
                nodes,
                skill_id,
                CorpusNodeKind.SKILL,
                source_set,
                properties,
                source_body_cid=primary_cid,
                embedding_cid=embedding_cid,
            )
            _add_edge(
                edges, CorpusEdgeKind.CONTAINS, bundle_id, skill_id, source_set
            )
            _add_edge(
                edges,
                CorpusEdgeKind.DERIVED_FROM,
                skill_id,
                primary_document_id,
                source_set,
            )
            for document_id, role_digest, _ in documents.values():
                if document_id != primary_document_id:
                    _add_edge(
                        edges,
                        CorpusEdgeKind.DERIVED_FROM,
                        skill_id,
                        document_id,
                        (role_digest, bundle_digest),
                    )

            domain = (record.domain.strip() or "unknown").casefold()
            domain_id = _id("domain", {"name": domain})
            _add_node(
                nodes,
                domain_id,
                CorpusNodeKind.DOMAIN,
                (bundle_digest,),
                {"name": domain},
            )
            _add_edge(
                edges,
                CorpusEdgeKind.HAS_DOMAIN,
                skill_id,
                domain_id,
                source_set,
            )
            license_expression = record.license_expression.strip() or "UNKNOWN"
            license_id = _id("license", {"expression": license_expression})
            _add_node(
                nodes,
                license_id,
                CorpusNodeKind.LICENSE,
                (bundle_digest,),
                {"expression": license_expression},
            )
            license_edge_properties = (
                {"license_decision": properties["license_decision"]}
                if "license_decision" in properties
                else None
            )
            _add_edge(
                edges,
                CorpusEdgeKind.HAS_LICENSE,
                skill_id,
                license_id,
                source_set,
                license_edge_properties,
            )
            _add_edge(
                edges,
                CorpusEdgeKind.HAS_LICENSE,
                primary_document_id,
                license_id,
                source_set,
                license_edge_properties,
            )

            for title, start, end, level in _sections(record.skill_md):
                section_id = _id(
                    "section",
                    {
                        "document": primary_document_id,
                        "start": start,
                        "end": end,
                    },
                )
                _add_node(
                    nodes,
                    section_id,
                    CorpusNodeKind.SECTION,
                    source_set,
                    {
                        "end_byte": end,
                        "heading_level": level,
                        "start_byte": start,
                        "title": title,
                    },
                    source_body_cid=primary_cid,
                )
                _add_edge(
                    edges,
                    CorpusEdgeKind.CONTAINS,
                    skill_id,
                    section_id,
                    source_set,
                )
                _add_edge(
                    edges,
                    CorpusEdgeKind.DERIVED_FROM,
                    section_id,
                    primary_document_id,
                    source_set,
                )
                span_id = _span_node(
                    nodes,
                    edges,
                    primary_document_id,
                    body_digest,
                    primary_cid,
                    start,
                    end,
                )
                _add_edge(
                    edges,
                    CorpusEdgeKind.CONTAINS,
                    section_id,
                    span_id,
                    source_set,
                )

            for mention in item.mentions:
                _validate_grounding(
                    mention.start_byte,
                    mention.end_byte,
                    record.skill_md,
                    label="CorpusMention",
                )
                exact = record.skill_md.encode()[
                    mention.start_byte : mention.end_byte
                ].decode("utf-8")
                if exact != mention.value:
                    raise CorpusGraphValidationError(
                        "CorpusMention.value must exactly match its source byte span"
                    )
                mention_id = _id(
                    "mention",
                    {
                        "kind": mention.kind.value,
                        "value": mention.value,
                        "document": primary_document_id,
                        "start": mention.start_byte,
                        "end": mention.end_byte,
                    },
                )
                _add_node(
                    nodes,
                    mention_id,
                    mention.kind,
                    source_set,
                    {"value": mention.value, **dict(mention.properties)},
                )
                span_id = _span_node(
                    nodes,
                    edges,
                    primary_document_id,
                    body_digest,
                    primary_cid,
                    mention.start_byte,
                    mention.end_byte,
                )
                _add_edge(
                    edges,
                    CorpusEdgeKind.MENTIONS,
                    span_id,
                    mention_id,
                    source_set,
                )

            citations = (*_citations(record.skill_md), *item.citations)
            seen_citations: set[tuple[str, int, int]] = set()
            for citation in citations:
                marker = (
                    citation.target_uri,
                    citation.start_byte,
                    citation.end_byte,
                )
                if marker in seen_citations:
                    continue
                seen_citations.add(marker)
                _validate_grounding(
                    citation.start_byte,
                    citation.end_byte,
                    record.skill_md,
                    label="CorpusCitation",
                )
                cited_value = record.skill_md.encode()[
                    citation.start_byte : citation.end_byte
                ].decode("utf-8")
                if cited_value != citation.target_uri:
                    raise CorpusGraphValidationError(
                        "CorpusCitation.target_uri must exactly match its "
                        "grounded source byte span"
                    )
                uri = _normalized_uri(citation.target_uri)
                external_digest = _digest({"source_uri": uri})
                external_id = _id("external-source-document", {"source_uri": uri})
                _add_node(
                    nodes,
                    external_id,
                    CorpusNodeKind.SOURCE_DOCUMENT,
                    (external_digest,),
                    {"external": True, "source_uri": uri},
                )
                span_id = _span_node(
                    nodes,
                    edges,
                    primary_document_id,
                    body_digest,
                    primary_cid,
                    citation.start_byte,
                    citation.end_byte,
                )
                _add_edge(
                    edges,
                    CorpusEdgeKind.CITES,
                    span_id,
                    external_id,
                    (*source_set, external_digest),
                )

            lookup[record_key] = skill_id
            if record.skill_id not in lookup:
                lookup[record.skill_id] = skill_id
            elif lookup[record.skill_id] != skill_id:
                lookup[record.skill_id] = ""
            skill_sources[skill_id] = source_set
            family_groups[skill_id] = record.primary_source_id
            content_groups[skill_id] = body_digest
            explicit_duplicates.extend(
                (skill_id, reference) for reference in item.duplicate_of
            )

        self._pair_edges(
            edges,
            skill_sources,
            family_groups,
            CorpusEdgeKind.SAME_PRIMARY_SOURCE,
        )
        self._pair_edges(
            edges, skill_sources, content_groups, CorpusEdgeKind.DUPLICATE_OF
        )
        for source, reference in explicit_duplicates:
            target = _resolve(reference, lookup)
            _add_symmetric_edge(
                edges,
                CorpusEdgeKind.DUPLICATE_OF,
                source,
                target,
                (*skill_sources[source], *skill_sources[target]),
                {"explicit": True},
            )
        for neighbor in neighbors:
            source = _resolve(neighbor.source_skill_id, lookup)
            target = _resolve(neighbor.target_skill_id, lookup)
            digests = [*skill_sources[source], *skill_sources[target]]
            if neighbor.embedding_digest:
                digests.append(neighbor.embedding_digest)
            _add_symmetric_edge(
                edges,
                CorpusEdgeKind.NEIGHBOR_OF,
                source,
                target,
                digests,
                {
                    "metric": neighbor.metric,
                    "score": float(neighbor.score),
                    "semantic_assertion": False,
                },
                embedding_cid=neighbor.embedding_cid,
            )
        return _seal(nodes, edges)

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
        """Store source/vector bytes separately and then persist the graph."""

        inputs = tuple(_input(item) for item in records)
        if not inputs:
            raise CorpusGraphValidationError("records must not be empty")
        adapter = (
            storage
            if isinstance(storage, IPLDCorpusGraphStorage)
            else IPLDCorpusGraphStorage(storage)
        )
        source_addresses: dict[str, str] = {}
        for item in sorted(inputs, key=lambda value: _record_key(value.record)):
            for role, body in (
                ("skill_md", item.record.skill_md),
                ("metadata_yaml", item.record.metadata_yaml),
                ("library_md", item.record.library_md),
            ):
                if body:
                    key = f"{_record_key(item.record)}:{role}"
                    source_addresses[key] = adapter.put_source_body(body.encode())

        vector_addresses = dict(embedding_cids or {})
        for key, payload in sorted((embeddings or {}).items()):
            if not isinstance(payload, (bytes, bytearray, memoryview)):
                raise TypeError("embedding payloads must be bytes-like")
            if key in vector_addresses:
                raise CorpusGraphValidationError(
                    f"embedding {key!r} has both bytes and an address"
                )
            vector_addresses[key] = adapter.put_embedding(bytes(payload))
        graph = self.project(
            inputs,
            policy_decisions=policy_decisions,
            source_body_cids=source_addresses,
            embedding_cids=vector_addresses,
            neighbors=neighbors,
        )
        return StoredCorpusGraph(
            graph=graph,
            graph_cid=adapter.put_graph(graph),
            source_body_cids=source_addresses,
            embedding_cids=vector_addresses,
        )

    @staticmethod
    def _pair_edges(
        edges: dict[str, _Edge],
        skill_sources: Mapping[str, tuple[str, ...]],
        groups_by_skill: Mapping[str, str],
        kind: CorpusEdgeKind,
    ) -> None:
        groups: dict[str, list[str]] = defaultdict(list)
        for skill, group in groups_by_skill.items():
            if group:
                groups[group].append(skill)
        for group, skills in sorted(groups.items()):
            skills.sort()
            for index, source in enumerate(skills):
                for target in skills[index + 1 :]:
                    _add_symmetric_edge(
                        edges,
                        kind,
                        source,
                        target,
                        (*skill_sources[source], *skill_sources[target]),
                        {"group_digest": _digest({"group": group})},
                    )


def _input(
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
    _qualified_digest(record.bundle_sha256, label="bundle_sha256")
    if record.overall_score is not None and not math.isfinite(record.overall_score):
        raise CorpusGraphValidationError("overall_score must be finite")


def _qualified_digest(value: str, *, label: str) -> str:
    if not isinstance(value, str):
        raise CorpusGraphValidationError(f"{label} must be a SHA-256 digest")
    digest = value.removeprefix("sha256:")
    if _HEX_RE.fullmatch(digest) is None:
        raise CorpusGraphValidationError(
            f"{label} must be 64 lowercase hexadecimal characters"
        )
    return f"sha256:{digest}"


def _digest(value: Mapping[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _id(namespace: str, value: Mapping[str, Any]) -> str:
    return f"intent-corpus:{namespace}:{_digest(value).removeprefix('sha256:')[:32]}"


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
        or not value
        or value.strip() != value
        or "\x00" in value
        or len(value) > 1024
    ):
        raise CorpusGraphValidationError(
            f"{label} storage must return a bounded immutable address"
        )
    return value


def _add_node(
    nodes: dict[str, _Node],
    node_id: str,
    kind: CorpusNodeKind,
    source_digests: Sequence[str],
    properties: Mapping[str, Any],
    *,
    source_body_cid: str = "",
    embedding_cid: str = "",
) -> None:
    digests = {
        _qualified_digest(value, label="node source")
        for value in source_digests
    }
    candidate = _Node(
        kind,
        digests,
        dict(properties),
        source_body_cid,
        embedding_cid,
    )
    current = nodes.get(node_id)
    if current is None:
        nodes[node_id] = candidate
    elif (
        current.kind != candidate.kind
        or current.properties != candidate.properties
        or current.source_body_cid != candidate.source_body_cid
        or current.embedding_cid != candidate.embedding_cid
    ):
        raise CorpusGraphValidationError(
            f"conflicting definitions for graph node {node_id!r}"
        )
    else:
        current.source_digests.update(digests)


def _add_edge(
    edges: dict[str, _Edge],
    kind: CorpusEdgeKind,
    source: str,
    target: str,
    source_digests: Sequence[str],
    properties: Mapping[str, Any] | None = None,
    *,
    embedding_cid: str = "",
) -> None:
    properties = dict(properties or {})
    edge_id = _id(
        "edge",
        {
            "embedding_cid": embedding_cid,
            "properties": properties,
            "source": source,
            "target": target,
            "type": kind.value,
        },
    )
    digests = {
        _qualified_digest(value, label="edge source")
        for value in source_digests
    }
    current = edges.get(edge_id)
    if current is None:
        edges[edge_id] = _Edge(
            kind, source, target, digests, properties, embedding_cid
        )
    else:
        current.source_digests.update(digests)


def _add_symmetric_edge(
    edges: dict[str, _Edge],
    kind: CorpusEdgeKind,
    source: str,
    target: str,
    source_digests: Sequence[str],
    properties: Mapping[str, Any] | None = None,
    *,
    embedding_cid: str = "",
) -> None:
    source, target = sorted((source, target))
    _add_edge(
        edges,
        kind,
        source,
        target,
        source_digests,
        properties,
        embedding_cid=embedding_cid,
    )


def _seal(
    node_builders: Mapping[str, _Node],
    edge_builders: Mapping[str, _Edge],
) -> IntentCorpusGraph:
    placeholder = "sha256:" + "0" * 64
    nodes = tuple(
        CorpusGraphNode(
            node_id=node_id,
            kind=value.kind,
            source_digests=tuple(value.source_digests),
            graph_digest=placeholder,
            properties=value.properties,
            source_body_cid=value.source_body_cid,
            embedding_cid=value.embedding_cid,
        )
        for node_id, value in sorted(node_builders.items())
    )
    edges = tuple(
        CorpusGraphEdge(
            edge_id=edge_id,
            kind=value.kind,
            source_node_id=value.source,
            target_node_id=value.target,
            source_digests=tuple(value.source_digests),
            graph_digest=placeholder,
            properties=value.properties,
            embedding_cid=value.embedding_cid,
        )
        for edge_id, value in sorted(edge_builders.items())
    )
    digest = graph_projection_digest(nodes, edges)
    return IntentCorpusGraph(
        graph_digest=digest,
        nodes=tuple(replace(node, graph_digest=digest) for node in nodes),
        relationships=tuple(replace(edge, graph_digest=digest) for edge in edges),
    ).validate()


def _repository(source_url: str) -> tuple[str, dict[str, Any]]:
    parsed = urlsplit(source_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return "", {}
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 2:
        return "", {}
    path = "/".join(parts[:2])
    uri = urlunsplit(
        (parsed.scheme.lower(), parsed.netloc.lower(), f"/{path}", "", "")
    )
    return _id("repository", {"uri": uri}), {
        "host": parsed.netloc.lower(),
        "repository_path": path,
        "source_uri": uri,
    }


def _sections(value: str) -> tuple[tuple[str, int, int, int], ...]:
    headings: list[tuple[str, int, int]] = []
    offset = 0
    for line in value.splitlines(keepends=True):
        match = _HEADING_RE.match(line.rstrip("\r\n"))
        if match:
            headings.append((match.group(2).strip()[:512], offset, len(match.group(1))))
        offset += len(line.encode())
    length = len(value.encode())
    if not headings:
        return (("document", 0, length, 0),)
    result: list[tuple[str, int, int, int]] = []
    if headings[0][1]:
        result.append(("preamble", 0, headings[0][1], 0))
    for index, (title, start, level) in enumerate(headings):
        end = headings[index + 1][1] if index + 1 < len(headings) else length
        result.append((title, start, end, level))
    return tuple(result)


def _citations(value: str) -> tuple[CorpusCitation, ...]:
    result: dict[tuple[str, int, int], CorpusCitation] = {}
    for pattern in (_MARKDOWN_URL_RE, _BARE_URL_RE):
        for match in pattern.finditer(value):
            url = match.group(1) if pattern is _MARKDOWN_URL_RE else match.group()
            url = url.rstrip(".,;:!?")
            start_char = (
                match.start(1)
                if pattern is _MARKDOWN_URL_RE
                else match.start()
            )
            start = len(value[:start_char].encode())
            end = start + len(url.encode())
            citation = CorpusCitation(url, start, end)
            result[(url, start, end)] = citation
    return tuple(result[key] for key in sorted(result))


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


def _validate_span(start: int, end: int, *, label: str) -> None:
    if (
        isinstance(start, bool)
        or isinstance(end, bool)
        or not isinstance(start, int)
        or not isinstance(end, int)
        or start < 0
        or end <= start
    ):
        raise CorpusGraphValidationError(
            f"{label} byte offsets must form a non-empty half-open span"
        )


def _validate_grounding(start: int, end: int, source: str, *, label: str) -> None:
    _validate_span(start, end, label=label)
    if end > len(source.encode()):
        raise CorpusGraphValidationError(
            f"{label} byte span exceeds the primary source body"
        )
    try:
        source.encode()[start:end].decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CorpusGraphValidationError(
            f"{label} byte span must align to UTF-8 character boundaries"
        ) from exc


def _span_node(
    nodes: dict[str, _Node],
    edges: dict[str, _Edge],
    document_id: str,
    document_digest: str,
    body_cid: str,
    start: int,
    end: int,
) -> str:
    span_id = _id(
        "source-span", {"document": document_id, "start": start, "end": end}
    )
    _add_node(
        nodes,
        span_id,
        CorpusNodeKind.SOURCE_SPAN,
        (document_digest,),
        {"end_byte": end, "start_byte": start},
        source_body_cid=body_cid,
    )
    _add_edge(
        edges,
        CorpusEdgeKind.CONTAINS,
        document_id,
        span_id,
        (document_digest,),
    )
    return span_id


def _resolve(value: str, lookup: Mapping[str, str]) -> str:
    resolved = lookup.get(value)
    if not resolved:
        reason = "ambiguous" if value in lookup else "unknown"
        raise CorpusGraphValidationError(f"{reason} skill reference {value!r}")
    return resolved


def _policy_properties(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    payload = value.to_dict() if hasattr(value, "to_dict") else value
    if not isinstance(payload, Mapping):
        raise CorpusGraphValidationError(
            "policy decisions must be mappings or expose to_dict()"
        )
    result = {
        key: payload[key]
        for key in ("allowed_use", "policy_version", "trust_decision")
        if isinstance(payload.get(key), str) and payload[key]
    }
    license_decision = payload.get("license_decision")
    if isinstance(license_decision, Mapping):
        bounded = {
            key: license_decision[key]
            for key in ("allowed_use", "reason_code", "status")
            if isinstance(license_decision.get(key), str) and license_decision[key]
        }
        if bounded:
            result["license_decision"] = bounded
    return result


IntentCorpusGraphProjector = CorpusGraphProjector


def project_corpus_graph(
    records: Iterable[SkillCenterSkillRecord | CorpusProjectionInput],
    **kwargs: Any,
) -> IntentCorpusGraph:
    """Functional facade for :class:`CorpusGraphProjector`."""

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
