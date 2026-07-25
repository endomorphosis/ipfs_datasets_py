"""Deterministic projection of SkillCenter records into corpus evidence graphs.

The projector consumes bounded records that have passed the source-policy
contract.  It does not execute or interpret source instructions.  Markdown
headings, safe scalar metadata, and URI citations are projected structurally;
optional mentions are explicit caller-supplied observations.

Raw source bodies, optional embeddings, and the graph document are written as
separate raw blocks through the current
``knowledge_graphs.storage.IPLDBackend`` adapter (or an injected compatible
store).  No code in this module imports the deprecated
``knowledge_graphs.ipld`` implementation.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
import hashlib
import math
import re
from typing import Any, Protocol, runtime_checkable
from urllib.parse import urlsplit, urlunsplit

from ...ir_core.canonical import canonical_json_bytes
from ...ir_core.identity import cid_v1
from ..source_adapters.policy import (
    AllowedUseDecision,
    SkillSourcePolicy,
    SkillSourcePolicyDecision,
)
from ..source_adapters.skillcenter import SkillCenterSkillRecord
from .ontology import (
    AddressedArtifact,
    CORPUS_ONTOLOGY_VERSION,
    CorpusEdgeType,
    CorpusGraphEdge,
    CorpusGraphNode,
    CorpusNodeType,
    IntentCorpusGraph,
    structural_graph_digest,
)


_ZERO_DIGEST = "sha256:" + ("0" * 64)
_HEADING_RE = re.compile(r"(?m)^(#{1,6})[ \t]+(.+?)[ \t]*$")
_URI_RE = re.compile(r"https?://[^\s<>()\[\]{}\"']+")
_SCALAR_RE = re.compile(
    r"^(?P<key>[A-Za-z_][A-Za-z0-9_-]*):[ \t]*(?P<value>.*)$",
    re.MULTILINE,
)
_TRAILING_URI_PUNCTUATION = ".,;:!?"
_MAX_EXPLICIT_ITEMS = 256
DEFAULT_MAX_RECORDS = 10_000
DEFAULT_MAX_SECTIONS_PER_RECORD = 4_096
DEFAULT_MAX_AUTO_CITATIONS_PER_RECORD = 256

_BODY_STORAGE_DECISIONS = frozenset(
    {
        AllowedUseDecision.ALLOW_TRAIN_AND_PUBLISH,
        AllowedUseDecision.ALLOW_INTERNAL_EVALUATION,
    }
)


class CorpusProjectionError(ValueError):
    """Raised when corpus evidence cannot be safely projected."""


@runtime_checkable
class ContentAddressedStore(Protocol):
    """Minimal block-store port used by the corpus projector."""

    def put_bytes(self, payload: bytes, *, media_type: str) -> str:
        """Persist exact bytes and return their immutable content address."""


class IPLDArtifactStore:
    """Small adapter around the repository's current core IPLD storage class."""

    def __init__(self, storage: Any | None = None) -> None:
        if storage is None:
            # Kept lazy so ontology-only users do not initialize optional IPFS
            # backends, and to make the current adapter easy to inject in tests.
            from ipfs_datasets_py.knowledge_graphs.storage import IPLDBackend

            storage = IPLDBackend(database="intent-corpus")
        store_method = getattr(storage, "store", None)
        if not callable(store_method):
            raise TypeError("storage must provide a callable store(bytes) method")
        self.storage = storage

    def put_bytes(self, payload: bytes, *, media_type: str) -> str:
        if not isinstance(payload, bytes):
            raise TypeError("payload must be bytes")
        if not isinstance(media_type, str) or not media_type:
            raise ValueError("media_type must not be empty")
        cid = self.storage.store(payload, pin=True, codec="raw")
        if not isinstance(cid, str) or not cid:
            raise CorpusProjectionError("IPLD storage returned an invalid CID")
        return cid


# Explicit name for callers looking for the current storage boundary.
CurrentIPLDStorageAdapter = IPLDArtifactStore


@dataclass(frozen=True, slots=True)
class CorpusMention:
    """One bounded mention observation supplied by a trusted extractor."""

    value: str
    kind: CorpusNodeType = CorpusNodeType.ENTITY_MENTION
    section_title: str = ""
    start_byte: int | None = None
    end_byte: int | None = None

    def __post_init__(self) -> None:
        value = _clean_text(self.value, "mention value")
        object.__setattr__(self, "value", value)
        object.__setattr__(
            self,
            "section_title",
            _optional_clean_text(self.section_title, "mention section_title"),
        )
        try:
            kind = (
                self.kind
                if isinstance(self.kind, CorpusNodeType)
                else CorpusNodeType(self.kind)
            )
        except (TypeError, ValueError) as exc:
            raise CorpusProjectionError("unknown mention kind") from exc
        if kind not in {
            CorpusNodeType.TOOL_MENTION,
            CorpusNodeType.ENTITY_MENTION,
            CorpusNodeType.AUTHOR_PUBLISHER,
        }:
            raise CorpusProjectionError(
                "mention kind must be tool_mention, entity_mention, "
                "or author_publisher"
            )
        object.__setattr__(self, "kind", kind)
        _validate_optional_span(self.start_byte, self.end_byte)


@dataclass(frozen=True, slots=True)
class CorpusCitation:
    """One source URI cited by a record or section."""

    uri: str
    section_title: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "uri", _normalized_http_uri(self.uri))
        object.__setattr__(
            self,
            "section_title",
            _optional_clean_text(self.section_title, "citation section_title"),
        )


@dataclass(frozen=True, slots=True)
class CorpusEvidenceRecord:
    """A SkillCenter row plus explicit bounded graph-extraction observations."""

    record: SkillCenterSkillRecord
    policy_decision: SkillSourcePolicyDecision | None = None
    embedding: tuple[float, ...] | None = None
    embedding_model: str = ""
    mentions: tuple[CorpusMention, ...] = ()
    citations: tuple[CorpusCitation, ...] = ()
    neighbor_skill_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.record, SkillCenterSkillRecord):
            raise TypeError("record must be a SkillCenterSkillRecord")
        if self.policy_decision is not None:
            if not isinstance(self.policy_decision, SkillSourcePolicyDecision):
                raise TypeError(
                    "policy_decision must be a SkillSourcePolicyDecision"
                )
            if self.policy_decision.skill_id != self.record.skill_id:
                raise CorpusProjectionError(
                    "policy_decision skill_id does not match its source record"
                )
        mentions = tuple(self.mentions)
        citations = tuple(self.citations)
        if len(mentions) > _MAX_EXPLICIT_ITEMS:
            raise CorpusProjectionError("too many explicit mentions")
        if len(citations) > _MAX_EXPLICIT_ITEMS:
            raise CorpusProjectionError("too many explicit citations")
        if len(self.neighbor_skill_ids) > _MAX_EXPLICIT_ITEMS:
            raise CorpusProjectionError("too many explicit neighbors")
        if any(not isinstance(item, CorpusMention) for item in mentions):
            raise TypeError("mentions must contain CorpusMention values")
        if any(not isinstance(item, CorpusCitation) for item in citations):
            raise TypeError("citations must contain CorpusCitation values")
        object.__setattr__(self, "mentions", mentions)
        object.__setattr__(self, "citations", citations)
        neighbors = tuple(
            sorted({_clean_text(item, "neighbor skill id") for item in self.neighbor_skill_ids})
        )
        if self.record.skill_id in neighbors:
            raise CorpusProjectionError("a record cannot be its own neighbor")
        object.__setattr__(self, "neighbor_skill_ids", neighbors)
        if self.embedding is not None:
            vector = tuple(float(item) for item in self.embedding)
            if not vector or any(not math.isfinite(item) for item in vector):
                raise CorpusProjectionError(
                    "embedding must be a non-empty finite numeric vector"
                )
            object.__setattr__(self, "embedding", vector)
            object.__setattr__(
                self,
                "embedding_model",
                _clean_text(self.embedding_model, "embedding_model"),
            )
        elif self.embedding_model:
            raise CorpusProjectionError(
                "embedding_model cannot be set without an embedding"
            )


@dataclass(frozen=True, slots=True)
class _Section:
    title: str
    level: int
    start_byte: int
    end_byte: int


@dataclass(slots=True)
class _GraphBuilder:
    nodes: dict[str, CorpusGraphNode] = field(default_factory=dict)
    edges: dict[str, CorpusGraphEdge] = field(default_factory=dict)

    def add_node(
        self,
        node_type: CorpusNodeType,
        identity: Mapping[str, Any],
        *,
        source_digest: str,
        properties: Mapping[str, Any],
    ) -> str:
        node_id = _stable_id("node", node_type.value, identity)
        node = CorpusGraphNode(
            node_id=node_id,
            node_type=node_type,
            source_digest=source_digest,
            graph_digest=_ZERO_DIGEST,
            properties=properties,
        )
        existing = self.nodes.get(node_id)
        if existing is not None and existing != node:
            raise CorpusProjectionError(f"conflicting projection for node {node_id}")
        self.nodes[node_id] = node
        return node_id

    def add_edge(
        self,
        edge_type: CorpusEdgeType,
        source: str,
        target: str,
        *,
        source_digest: str,
        properties: Mapping[str, Any] | None = None,
    ) -> str:
        edge_properties = dict(properties or {})
        edge_id = _stable_id(
            "edge",
            edge_type.value,
            {
                "properties": edge_properties,
                "source": source,
                "source_digest": source_digest,
                "target": target,
            },
        )
        edge = CorpusGraphEdge(
            edge_id=edge_id,
            edge_type=edge_type,
            source=source,
            target=target,
            source_digest=source_digest,
            graph_digest=_ZERO_DIGEST,
            properties=edge_properties,
        )
        existing = self.edges.get(edge_id)
        if existing is not None and existing != edge:
            raise CorpusProjectionError(f"conflicting projection for edge {edge_id}")
        self.edges[edge_id] = edge
        return edge_id


class CorpusProjector:
    """Project one or more policy-classified SkillCenter rows."""

    def __init__(
        self,
        store: ContentAddressedStore | None = None,
        *,
        policy: SkillSourcePolicy | None = None,
        extract_markdown_sections: bool = True,
        extract_uri_citations: bool = True,
        max_records: int = DEFAULT_MAX_RECORDS,
        max_sections_per_record: int = DEFAULT_MAX_SECTIONS_PER_RECORD,
        max_auto_citations_per_record: int = DEFAULT_MAX_AUTO_CITATIONS_PER_RECORD,
    ) -> None:
        self.store = store if store is not None else IPLDArtifactStore()
        if not isinstance(self.store, ContentAddressedStore):
            raise TypeError("store must implement put_bytes(payload, media_type=...)")
        self.policy = policy or SkillSourcePolicy()
        self.extract_markdown_sections = bool(extract_markdown_sections)
        self.extract_uri_citations = bool(extract_uri_citations)
        self.max_records = _positive_int(max_records, "max_records")
        self.max_sections_per_record = _positive_int(
            max_sections_per_record, "max_sections_per_record"
        )
        self.max_auto_citations_per_record = _positive_int(
            max_auto_citations_per_record, "max_auto_citations_per_record"
        )

    def project(
        self,
        records: (
            SkillCenterSkillRecord
            | CorpusEvidenceRecord
            | Iterable[SkillCenterSkillRecord | CorpusEvidenceRecord]
        ),
        *,
        policy_decision: SkillSourcePolicyDecision | None = None,
        embedding: Sequence[float] | None = None,
        embedding_model: str = "",
        mentions: Sequence[CorpusMention] = (),
        citations: Sequence[CorpusCitation] = (),
        neighbor_skill_ids: Sequence[str] = (),
    ) -> IntentCorpusGraph:
        """Return a deterministic evidence graph and persist separate blocks.

        The keyword observations are a convenience for a single record.  For a
        batch, wrap each row in :class:`CorpusEvidenceRecord`.
        """

        evidence = self._coerce_records(records)
        convenience_used = any(
            (
                policy_decision is not None,
                embedding is not None,
                bool(embedding_model),
                bool(mentions),
                bool(citations),
                bool(neighbor_skill_ids),
            )
        )
        if convenience_used:
            if len(evidence) != 1:
                raise CorpusProjectionError(
                    "single-record projection keywords cannot be used for a batch"
                )
            current = evidence[0]
            if current != CorpusEvidenceRecord(current.record):
                raise CorpusProjectionError(
                    "do not combine CorpusEvidenceRecord observations with "
                    "single-record projection keywords"
                )
            evidence = (
                CorpusEvidenceRecord(
                    current.record,
                    policy_decision=policy_decision,
                    embedding=None if embedding is None else tuple(embedding),
                    embedding_model=embedding_model,
                    mentions=tuple(mentions),
                    citations=tuple(citations),
                    neighbor_skill_ids=tuple(neighbor_skill_ids),
                ),
            )
        if not evidence:
            raise CorpusProjectionError("at least one source record is required")
        if len(evidence) > self.max_records:
            raise CorpusProjectionError(
                f"projection exceeds max_records={self.max_records}"
            )

        prepared = tuple(self._prepare(item) for item in evidence)
        body_storage_allowed: dict[str, bool] = {}
        for item, decision in prepared:
            digest = "sha256:" + item.record.content_sha256
            allowed = decision.allowed_use in _BODY_STORAGE_DECISIONS
            body_storage_allowed[digest] = (
                body_storage_allowed.get(digest, True) and allowed
            )
        builder = _GraphBuilder()
        source_bodies: dict[str, AddressedArtifact] = {}
        embeddings: dict[str, AddressedArtifact] = {}
        skill_nodes: dict[str, str] = {}
        skill_source_digests: dict[str, str] = {}
        primary_groups: dict[str, list[str]] = defaultdict(list)
        body_groups: dict[str, list[str]] = defaultdict(list)
        pending_blocks: dict[str, tuple[bytes, str]] = {}

        for item, decision in prepared:
            record = item.record
            source_digest = f"sha256:{record.content_sha256}"
            bundle_digest = _qualified_sha256(
                record.bundle_sha256, "record.bundle_sha256"
            )
            body = record.skill_md.encode("utf-8")
            # If identical bytes arrive under conflicting use decisions, the
            # most restrictive decision governs the shared content address.
            body_should_store = body_storage_allowed[source_digest]
            body_cid = cid_v1(body)
            if body_should_store:
                self._queue_block(
                    pending_blocks,
                    body,
                    media_type="text/markdown; charset=utf-8",
                )
            source_bodies[source_digest] = AddressedArtifact.from_bytes(
                body,
                media_type="text/markdown; charset=utf-8",
                cid=body_cid,
                stored=body_should_store,
            )

            embedding_ref: AddressedArtifact | None = None
            if item.embedding is not None:
                if not body_should_store:
                    raise CorpusProjectionError(
                        f"{record.skill_id}: policy decision "
                        f"{decision.allowed_use.value!r} does not permit embeddings"
                    )
                embedding_bytes = canonical_json_bytes(
                    {
                        "model": item.embedding_model,
                        "values": list(item.embedding),
                    }
                )
                embedding_cid = self._queue_block(
                    pending_blocks,
                    embedding_bytes,
                    media_type="application/vnd.intent-ir.embedding+json",
                )
                embedding_ref = AddressedArtifact.from_bytes(
                    embedding_bytes,
                    media_type="application/vnd.intent-ir.embedding+json",
                    cid=embedding_cid,
                )
                embeddings[embedding_ref.digest] = embedding_ref

            ids = self._project_record(
                builder,
                item,
                decision,
                source_digest=source_digest,
                bundle_digest=bundle_digest,
                body_ref=source_bodies[source_digest],
                embedding_ref=embedding_ref,
            )
            skill_nodes[record.skill_id] = ids["skill"]
            skill_source_digests[record.skill_id] = source_digest
            if record.primary_source_id:
                primary_groups[record.primary_source_id].append(ids["skill"])
            body_groups[source_digest].append(ids["skill"])

        self._add_group_edges(
            builder,
            primary_groups,
            CorpusEdgeType.SAME_PRIMARY_SOURCE,
        )
        self._add_group_edges(
            builder,
            body_groups,
            CorpusEdgeType.DUPLICATE_OF,
        )
        for item, _decision in prepared:
            source_id = skill_nodes[item.record.skill_id]
            source_digest = skill_source_digests[item.record.skill_id]
            for target_skill_id in item.neighbor_skill_ids:
                try:
                    target_id = skill_nodes[target_skill_id]
                except KeyError as exc:
                    raise CorpusProjectionError(
                        f"neighbor skill {target_skill_id!r} is not in this graph"
                    ) from exc
                # Store one canonical undirected observation.
                left, right = sorted((source_id, target_id))
                edge_digest = (
                    source_digest
                    if left == source_id
                    else skill_source_digests[target_skill_id]
                )
                builder.add_edge(
                    CorpusEdgeType.NEIGHBOR_OF,
                    left,
                    right,
                    source_digest=edge_digest,
                    properties={"symmetric": True},
                )

        unbound_nodes = tuple(sorted(builder.nodes.values(), key=lambda item: item.node_id))
        unbound_edges = tuple(sorted(builder.edges.values(), key=lambda item: item.edge_id))
        source_digests = tuple(
            sorted(
                {
                    *(node.source_digest for node in unbound_nodes),
                    *(edge.source_digest for edge in unbound_edges),
                }
            )
        )
        graph_digest = structural_graph_digest(
            unbound_nodes,
            unbound_edges,
            source_digests=source_digests,
        )
        nodes = tuple(replace(node, graph_digest=graph_digest) for node in unbound_nodes)
        edges = tuple(replace(edge, graph_digest=graph_digest) for edge in unbound_edges)
        graph = IntentCorpusGraph(
            nodes=nodes,
            edges=edges,
            graph_digest=graph_digest,
            source_digests=source_digests,
            source_bodies=tuple(
                source_bodies[key] for key in sorted(source_bodies)
            ),
            embeddings=tuple(embeddings[key] for key in sorted(embeddings)),
        )
        # Validate the entire graph, including cross-record relationships,
        # before performing storage side effects.  Blocks are content-addressed
        # and stored in CID order for deterministic fake/store observations.
        for cid in sorted(pending_blocks):
            payload, media_type = pending_blocks[cid]
            stored_cid = self._store_bytes(payload, media_type=media_type)
            if stored_cid != cid:  # pragma: no cover - guarded by _store_bytes
                raise CorpusProjectionError("queued block address changed")
        # The address preimage has an empty graph_cid, avoiding a circular CID.
        graph_cid = self._store_bytes(
            graph.canonical_bytes(),
            media_type="application/vnd.intent-ir.corpus-graph+json",
        )
        return replace(graph, graph_cid=graph_cid)

    @staticmethod
    def _queue_block(
        pending: dict[str, tuple[bytes, str]],
        payload: bytes,
        *,
        media_type: str,
    ) -> str:
        cid = cid_v1(payload)
        block = (payload, media_type)
        existing = pending.get(cid)
        if existing is not None and existing != block:
            raise CorpusProjectionError(
                "one content address was assigned conflicting block metadata"
            )
        pending[cid] = block
        return cid

    def _store_bytes(self, payload: bytes, *, media_type: str) -> str:
        cid = self.store.put_bytes(payload, media_type=media_type)
        expected = cid_v1(payload)
        if cid != expected:
            raise CorpusProjectionError(
                "content-addressed store returned an address that does not "
                "match the fixed raw CIDv1/SHA-256 profile"
            )
        return cid

    def project_record(
        self,
        record: SkillCenterSkillRecord,
        **kwargs: Any,
    ) -> IntentCorpusGraph:
        """Named single-record convenience wrapper around :meth:`project`."""

        return self.project(record, **kwargs)

    @staticmethod
    def _coerce_records(
        records: (
            SkillCenterSkillRecord
            | CorpusEvidenceRecord
            | Iterable[SkillCenterSkillRecord | CorpusEvidenceRecord]
        ),
    ) -> tuple[CorpusEvidenceRecord, ...]:
        if isinstance(records, CorpusEvidenceRecord):
            return (records,)
        if isinstance(records, SkillCenterSkillRecord):
            return (CorpusEvidenceRecord(records),)
        if isinstance(records, (str, bytes, Mapping)):
            raise TypeError(
                "records must be SkillCenterSkillRecord values, not text/mappings"
            )
        try:
            raw_items = tuple(records)
        except TypeError as exc:
            raise TypeError(
                "records must be a source record or iterable of source records"
            ) from exc
        prepared: list[CorpusEvidenceRecord] = []
        for item in raw_items:
            if isinstance(item, CorpusEvidenceRecord):
                prepared.append(item)
            elif isinstance(item, SkillCenterSkillRecord):
                prepared.append(CorpusEvidenceRecord(item))
            else:
                raise TypeError(
                    "records iterable must contain SkillCenterSkillRecord or "
                    "CorpusEvidenceRecord values"
                )
        skill_ids = [item.record.skill_id for item in prepared]
        if len(set(skill_ids)) != len(skill_ids):
            raise CorpusProjectionError("duplicate skill_id in projection batch")
        return tuple(sorted(prepared, key=lambda item: item.record.skill_id))

    def _prepare(
        self, item: CorpusEvidenceRecord
    ) -> tuple[CorpusEvidenceRecord, SkillSourcePolicyDecision]:
        evaluated = self.policy.evaluate(item.record)
        decision = item.policy_decision or evaluated
        if decision.skill_id != item.record.skill_id:
            raise CorpusProjectionError("policy decision is bound to another skill")
        if item.policy_decision is not None and decision != evaluated:
            raise CorpusProjectionError(
                "policy_decision does not match evaluation of its source record"
            )
        return item, decision

    def _project_record(
        self,
        builder: _GraphBuilder,
        item: CorpusEvidenceRecord,
        decision: SkillSourcePolicyDecision,
        *,
        source_digest: str,
        bundle_digest: str,
        body_ref: AddressedArtifact,
        embedding_ref: AddressedArtifact | None,
    ) -> dict[str, str]:
        record = item.record
        common_identity = {
            "dataset_id": record.dataset_id,
            "dataset_revision": record.dataset_revision,
            "source_digest": source_digest,
        }
        dataset = builder.add_node(
            CorpusNodeType.DATASET_REVISION,
            {
                "dataset_id": record.dataset_id,
                "dataset_revision": record.dataset_revision,
                "bundle_digest": bundle_digest,
            },
            source_digest=bundle_digest,
            properties={
                "dataset_id": record.dataset_id,
                "dataset_revision": record.dataset_revision,
            },
        )
        bundle = builder.add_node(
            CorpusNodeType.BUNDLE,
            {
                "bundle_digest": bundle_digest,
                "repository_file": record.repository_file,
            },
            source_digest=bundle_digest,
            properties={
                "bundle_digest": bundle_digest,
                "repository_file": record.repository_file,
            },
        )
        repository_uri = _repository_uri(record.source_url)
        repository = builder.add_node(
            CorpusNodeType.REPOSITORY,
            {**common_identity, "repository_uri": repository_uri},
            source_digest=source_digest,
            properties={
                "repository_uri": repository_uri,
                "source_type": record.source_type,
            },
        )
        body_properties: dict[str, Any] = {
            "body_cid": body_ref.cid,
            "body_size_bytes": body_ref.size_bytes,
            "body_stored": body_ref.stored,
            "primary_source_id": record.primary_source_id,
            "source_id": record.source_id,
            "source_uri": record.source_url,
        }
        if embedding_ref is not None:
            body_properties.update(
                {
                    "embedding_cid": embedding_ref.cid,
                    "embedding_digest": embedding_ref.digest,
                    "embedding_model": item.embedding_model,
                }
            )
        document = builder.add_node(
            CorpusNodeType.SOURCE_DOCUMENT,
            {**common_identity, "source_id": record.source_id},
            source_digest=source_digest,
            properties=body_properties,
        )
        skill = builder.add_node(
            CorpusNodeType.SKILL,
            {**common_identity, "skill_id": record.skill_id},
            source_digest=source_digest,
            properties={
                "allowed_use": decision.allowed_use.value,
                "body_cid": body_ref.cid,
                "body_stored": body_ref.stored,
                "language": record.language,
                "policy_version": decision.policy_version,
                "profile": record.profile,
                "review_status": decision.review_status.value,
                "skill_id": record.skill_id,
                "skill_kind": record.skill_kind,
                "title": record.title,
                "trust_decision": decision.trust_decision.value,
            },
        )
        license_node = builder.add_node(
            CorpusNodeType.LICENSE,
            {
                **common_identity,
                "expression": decision.license_decision.expression or "unknown",
            },
            source_digest=source_digest,
            properties={
                "allowed_use": decision.allowed_use.value,
                "expression": decision.license_decision.expression or "unknown",
                "reason_code": decision.license_decision.reason_code,
                "status": decision.license_decision.status.value,
            },
        )
        domain = builder.add_node(
            CorpusNodeType.DOMAIN,
            {**common_identity, "domain": record.domain or "unknown"},
            source_digest=source_digest,
            properties={"name": record.domain or "unknown"},
        )

        builder.add_edge(
            CorpusEdgeType.CONTAINS,
            dataset,
            bundle,
            source_digest=bundle_digest,
        )
        builder.add_edge(
            CorpusEdgeType.CONTAINS,
            bundle,
            document,
            source_digest=source_digest,
        )
        builder.add_edge(
            CorpusEdgeType.CONTAINS,
            bundle,
            skill,
            source_digest=source_digest,
        )
        builder.add_edge(
            CorpusEdgeType.CONTAINS,
            repository,
            document,
            source_digest=source_digest,
        )
        builder.add_edge(
            CorpusEdgeType.CONTAINS,
            repository,
            skill,
            source_digest=source_digest,
        )
        builder.add_edge(
            CorpusEdgeType.DERIVED_FROM,
            skill,
            document,
            source_digest=source_digest,
        )
        builder.add_edge(
            CorpusEdgeType.HAS_LICENSE,
            skill,
            license_node,
            source_digest=source_digest,
        )
        builder.add_edge(
            CorpusEdgeType.HAS_DOMAIN,
            skill,
            domain,
            source_digest=source_digest,
        )

        sections = (
            _markdown_sections(record.skill_md)
            if self.extract_markdown_sections
            else (_whole_document_section(record.skill_md, record.title),)
        )
        if len(sections) > self.max_sections_per_record:
            raise CorpusProjectionError(
                f"{record.skill_id}: section count exceeds "
                f"max_sections_per_record={self.max_sections_per_record}"
            )
        section_nodes: dict[str, str] = {}
        for index, section in enumerate(sections):
            section_node = builder.add_node(
                CorpusNodeType.SECTION,
                {
                    **common_identity,
                    "end_byte": section.end_byte,
                    "section_index": index,
                    "start_byte": section.start_byte,
                    "title": section.title,
                },
                source_digest=source_digest,
                properties={
                    "level": section.level,
                    "ordinal": index,
                    "title": section.title,
                },
            )
            span = builder.add_node(
                CorpusNodeType.SOURCE_SPAN,
                {
                    **common_identity,
                    "end_byte": section.end_byte,
                    "start_byte": section.start_byte,
                },
                source_digest=source_digest,
                properties={
                    "end_byte": section.end_byte,
                    "start_byte": section.start_byte,
                },
            )
            builder.add_edge(
                CorpusEdgeType.CONTAINS,
                skill,
                section_node,
                source_digest=source_digest,
            )
            builder.add_edge(
                CorpusEdgeType.CONTAINS,
                section_node,
                span,
                source_digest=source_digest,
            )
            section_nodes.setdefault(section.title.casefold(), section_node)

        explicit_mentions = list(item.mentions)
        for author_key in ("author", "publisher"):
            author = _metadata_scalar(record.metadata_yaml, author_key)
            if author:
                explicit_mentions.append(
                    CorpusMention(
                        author,
                        kind=CorpusNodeType.AUTHOR_PUBLISHER,
                    )
                )
        tools = (
            _metadata_scalar(record.metadata_yaml, "tools")
            or _metadata_scalar(record.metadata_yaml, "tool")
        )
        for tool in _split_scalar_list(tools):
            explicit_mentions.append(
                CorpusMention(tool, kind=CorpusNodeType.TOOL_MENTION)
            )
        if len(explicit_mentions) > _MAX_EXPLICIT_ITEMS:
            raise CorpusProjectionError(
                f"{record.skill_id}: extracted mentions exceed "
                f"{_MAX_EXPLICIT_ITEMS}"
            )
        for mention in sorted(
            set(explicit_mentions),
            key=lambda value: (
                value.kind.value,
                value.value.casefold(),
                value.section_title.casefold(),
                value.start_byte if value.start_byte is not None else -1,
            ),
        ):
            mention_node = builder.add_node(
                mention.kind,
                {
                    **common_identity,
                    "end_byte": mention.end_byte,
                    "kind": mention.kind.value,
                    "start_byte": mention.start_byte,
                    "value": mention.value,
                },
                source_digest=source_digest,
                properties={
                    "end_byte": mention.end_byte,
                    "normalized_value": mention.value.casefold(),
                    "start_byte": mention.start_byte,
                    "value": mention.value,
                },
            )
            mention_source = section_nodes.get(
                mention.section_title.casefold(), skill
            )
            builder.add_edge(
                CorpusEdgeType.MENTIONS,
                mention_source,
                mention_node,
                source_digest=source_digest,
            )

        citations = set(item.citations)
        if self.extract_uri_citations:
            automatic = _extract_http_uris(record.skill_md)
            if len(automatic) > self.max_auto_citations_per_record:
                raise CorpusProjectionError(
                    f"{record.skill_id}: URI citations exceed "
                    "max_auto_citations_per_record="
                    f"{self.max_auto_citations_per_record}"
                )
            citations.update(CorpusCitation(uri) for uri in automatic)
        for citation in sorted(
            citations, key=lambda value: (value.uri, value.section_title.casefold())
        ):
            cited = builder.add_node(
                CorpusNodeType.SOURCE_DOCUMENT,
                {
                    **common_identity,
                    "cited_uri": citation.uri,
                },
                source_digest=source_digest,
                properties={
                    "external": True,
                    "source_uri": citation.uri,
                },
            )
            citation_source = section_nodes.get(
                citation.section_title.casefold(), skill
            )
            builder.add_edge(
                CorpusEdgeType.CITES,
                citation_source,
                cited,
                source_digest=source_digest,
            )
        return {
            "bundle": bundle,
            "dataset": dataset,
            "document": document,
            "repository": repository,
            "skill": skill,
        }

    @staticmethod
    def _add_group_edges(
        builder: _GraphBuilder,
        groups: Mapping[str, list[str]],
        edge_type: CorpusEdgeType,
    ) -> None:
        for group_key in sorted(groups):
            members = sorted(set(groups[group_key]))
            if len(members) < 2:
                continue
            representative = members[0]
            for member in members[1:]:
                source_digest = builder.nodes[member].source_digest
                builder.add_edge(
                    edge_type,
                    member,
                    representative,
                    source_digest=source_digest,
                    properties={
                        (
                            "primary_source_id"
                            if edge_type is CorpusEdgeType.SAME_PRIMARY_SOURCE
                            else "content_digest"
                        ): group_key
                    },
                )


# Descriptive aliases used by planned semantic/retrieval follow-on tasks.
CorpusEvidenceProjector = CorpusProjector
IntentCorpusProjector = CorpusProjector


def project_corpus_record(
    record: SkillCenterSkillRecord,
    *,
    store: ContentAddressedStore | None = None,
    **kwargs: Any,
) -> IntentCorpusGraph:
    """Functional single-record entry point."""

    return CorpusProjector(store=store).project_record(record, **kwargs)


def _stable_id(namespace: str, kind: str, payload: Mapping[str, Any]) -> str:
    digest = hashlib.sha256(
        canonical_json_bytes(
            {
                "kind": kind,
                "namespace": namespace,
                "ontology_version": CORPUS_ONTOLOGY_VERSION,
                "payload": dict(payload),
            }
        )
    ).hexdigest()
    return f"corpus:{namespace}:{kind}:{digest}"


def _qualified_sha256(value: str, label: str) -> str:
    candidate = str(value)
    if candidate.startswith("sha256:"):
        candidate = candidate.removeprefix("sha256:")
    if not re.fullmatch(r"[0-9a-f]{64}", candidate):
        raise CorpusProjectionError(
            f"{label} must be 64 lowercase hexadecimal characters"
        )
    return f"sha256:{candidate}"


def _clean_text(value: Any, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value.strip() != value
        or "\x00" in value
    ):
        raise CorpusProjectionError(
            f"{label} must be non-empty normalized text"
        )
    return value


def _optional_clean_text(value: Any, label: str) -> str:
    if value == "":
        return ""
    return _clean_text(value, label)


def _positive_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{label} must be a positive integer")
    return value


def _validate_optional_span(start: int | None, end: int | None) -> None:
    if start is None and end is None:
        return
    if (
        isinstance(start, bool)
        or isinstance(end, bool)
        or not isinstance(start, int)
        or not isinstance(end, int)
        or start < 0
        or end <= start
    ):
        raise CorpusProjectionError(
            "mention byte offsets must be a valid half-open span"
        )


def _whole_document_section(body: str, title: str) -> _Section:
    return _Section(
        title=title or "document",
        level=0,
        start_byte=0,
        end_byte=len(body.encode("utf-8")),
    )


def _markdown_sections(body: str) -> tuple[_Section, ...]:
    matches = tuple(_HEADING_RE.finditer(body))
    if not matches:
        return (_whole_document_section(body, "document"),)
    sections: list[_Section] = []
    if matches[0].start() > 0:
        sections.append(
            _Section(
                title="preamble",
                level=0,
                start_byte=0,
                end_byte=len(body[: matches[0].start()].encode("utf-8")),
            )
        )
    for index, match in enumerate(matches):
        end_char = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        sections.append(
            _Section(
                title=match.group(2).strip(),
                level=len(match.group(1)),
                start_byte=len(body[: match.start()].encode("utf-8")),
                end_byte=len(body[:end_char].encode("utf-8")),
            )
        )
    return tuple(sections)


def _metadata_scalar(metadata_yaml: str, key: str) -> str:
    """Read a plain top-level scalar without constructing YAML objects."""

    for match in _SCALAR_RE.finditer(metadata_yaml or ""):
        if match.group("key").casefold() != key.casefold():
            continue
        value = match.group("value").strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1].strip()
        return value
    return ""


def _split_scalar_list(value: str) -> tuple[str, ...]:
    if not value:
        return ()
    unwrapped = value.strip().removeprefix("[").removesuffix("]")
    return tuple(
        sorted(
            {
                part.strip().strip("\"'")
                for part in unwrapped.split(",")
                if part.strip().strip("\"'")
            }
        )
    )


def _normalized_http_uri(value: str) -> str:
    uri = _clean_text(value, "citation uri").rstrip(_TRAILING_URI_PUNCTUATION)
    parts = urlsplit(uri)
    if parts.scheme.casefold() not in {"http", "https"} or not parts.netloc:
        raise CorpusProjectionError("citation uri must be an absolute HTTP(S) URI")
    return urlunsplit(
        (
            parts.scheme.casefold(),
            parts.netloc.casefold(),
            parts.path or "/",
            parts.query,
            "",
        )
    )


def _extract_http_uris(body: str) -> tuple[str, ...]:
    uris: set[str] = set()
    for match in _URI_RE.finditer(body):
        try:
            uris.add(_normalized_http_uri(match.group(0)))
        except CorpusProjectionError:
            continue
    return tuple(sorted(uris))


def _repository_uri(source_uri: str) -> str:
    try:
        parts = urlsplit(source_uri)
    except ValueError:
        return "source:unknown"
    if parts.scheme.casefold() not in {"http", "https"} or not parts.netloc:
        return "source:unknown"
    segments = [segment for segment in parts.path.split("/") if segment]
    if parts.netloc.casefold() in {"github.com", "www.github.com"}:
        segments = segments[:2]
    elif len(segments) > 1:
        segments = segments[:-1]
    path = "/" + "/".join(segments) if segments else "/"
    return urlunsplit(
        (parts.scheme.casefold(), parts.netloc.casefold(), path, "", "")
    )


__all__ = [
    "ContentAddressedStore",
    "CorpusCitation",
    "CorpusEvidenceProjector",
    "CorpusEvidenceRecord",
    "CorpusMention",
    "CorpusProjectionError",
    "CorpusProjector",
    "CurrentIPLDStorageAdapter",
    "DEFAULT_MAX_AUTO_CITATIONS_PER_RECORD",
    "DEFAULT_MAX_RECORDS",
    "DEFAULT_MAX_SECTIONS_PER_RECORD",
    "IPLDArtifactStore",
    "IntentCorpusProjector",
    "project_corpus_record",
]
