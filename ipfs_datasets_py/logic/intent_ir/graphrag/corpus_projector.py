"""Deterministic projection of SkillCenter records into corpus evidence.

This module handles source-level provenance only.  It does not normalize
Intent semantics, execute source instructions, generate embeddings, or treat
retrieval proximity as a semantic fact.  Source bodies and caller-supplied
embeddings are content-addressed as independent blocks; graph nodes contain
only bounded metadata and artifact references.

Persistence is optional and injected.  :class:`IPLDCorpusGraphStorage` wraps
the current :mod:`ipfs_datasets_py.knowledge_graphs.storage` backend without
depending on the legacy monolithic graph implementation.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
import hashlib
import math
import re
from typing import Any, Protocol, runtime_checkable
from urllib.parse import urlsplit, urlunsplit

from ...ir_core.canonical import canonical_json_bytes
from ...ir_core.identity import canonical_identity, cid_v1, sha256_digest
from ..source_adapters.policy import (
    AllowedUseDecision,
    SkillSourcePolicy,
    SkillSourcePolicyDecision,
)
from ..source_adapters.skillcenter import SkillCenterSkillRecord
from .ontology import (
    CORPUS_GRAPH_ONTOLOGY,
    CORPUS_GRAPH_ONTOLOGY_VERSION,
    CORPUS_GRAPH_SCHEMA_VERSION,
    CorpusEdgeType,
    CorpusGraphEdge,
    CorpusGraphNode,
    CorpusNodeType,
)


CORPUS_GRAPH_PROJECTOR_VERSION = "intent-corpus-projector/v1"
SOURCE_BODY_MEDIA_TYPE = "text/markdown; charset=utf-8"
SOURCE_METADATA_MEDIA_TYPE = "text/yaml; charset=utf-8"
EMBEDDING_MEDIA_TYPE = "application/vnd.ipfs-datasets.embedding+json"

DEFAULT_MAX_RECORDS = 10_000
DEFAULT_MAX_SECTIONS_PER_RECORD = 256
DEFAULT_MAX_MENTIONS_PER_RECORD = 256
DEFAULT_MAX_NEIGHBORS_PER_RECORD = 8
MAX_BOUNDED_TEXT_CHARS = 512

_HEADING_RE = re.compile(r"(?m)^(?P<marks>#{1,6})[ \t]+(?P<title>[^\r\n]+)")
_INLINE_CODE_RE = re.compile(r"(?<!`)`(?P<name>[A-Za-z0-9][A-Za-z0-9_.:/+-]{0,63})`(?!`)")
_MARKDOWN_LINK_RE = re.compile(
    r"\[(?P<label>[^\]\r\n]{1,128})\]\((?P<url>https?://[^)\s]{1,2048})\)"
)
_BARE_URL_RE = re.compile(r"(?<!\()https?://[^\s<>()\]]{1,2048}")
_ENTITY_MENTION_RE = re.compile(r"(?<![\w@])@(?P<name>[A-Za-z0-9][A-Za-z0-9_-]{0,63})")
_SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


class CorpusGraphProjectionError(ValueError):
    """Raised when source records cannot form a safe deterministic graph."""


@runtime_checkable
class CorpusGraphStorage(Protocol):
    """Small storage port implemented by the current IPLD adapter below."""

    def put_bytes(self, payload: bytes, *, media_type: str) -> str:
        """Store one separately addressed raw block and return its address."""

    def put_graph(
        self,
        *,
        nodes: list[dict[str, Any]],
        relationships: list[dict[str, Any]],
        metadata: dict[str, Any],
    ) -> str:
        """Store one graph root and return its IPLD address."""


class IPLDCorpusGraphStorage:
    """Adapter over ``knowledge_graphs.storage.IPLDBackend``.

    Import and backend initialization are lazy so pure projection and offline
    unit tests do not require an IPFS daemon.
    """

    def __init__(self, backend: Any | None = None, *, pin: bool = True) -> None:
        if backend is None:
            from ipfs_datasets_py.knowledge_graphs.storage import IPLDBackend

            backend = IPLDBackend(database="intent-corpus")
        if not callable(getattr(backend, "store", None)):
            raise TypeError("IPLD backend must provide store")
        if not callable(getattr(backend, "store_graph", None)):
            raise TypeError("IPLD backend must provide store_graph")
        self._backend = backend
        self._pin = bool(pin)

    def put_bytes(self, payload: bytes, *, media_type: str) -> str:
        del media_type  # Raw block media type is retained in the graph reference.
        return str(self._backend.store(payload, pin=self._pin, codec="raw"))

    def put_graph(
        self,
        *,
        nodes: list[dict[str, Any]],
        relationships: list[dict[str, Any]],
        metadata: dict[str, Any],
    ) -> str:
        return str(
            self._backend.store_graph(
                nodes=nodes,
                relationships=relationships,
                metadata=metadata,
            )
        )


@dataclass(frozen=True, slots=True)
class AddressedArtifact:
    """Reference to a body or embedding block kept outside the graph."""

    artifact_id: str
    role: str
    media_type: str
    sha256: str
    cid: str
    size_bytes: int
    source_digest: str
    stored: bool

    def __post_init__(self) -> None:
        if not self.artifact_id or not self.cid or not self.role or not self.media_type:
            raise ValueError("addressed artifact identifiers must not be empty")
        if not _SHA256_RE.fullmatch(self.sha256):
            raise ValueError("artifact sha256 must be a labeled SHA-256 digest")
        if not _SHA256_RE.fullmatch(self.source_digest):
            raise ValueError("artifact source_digest must be a labeled SHA-256 digest")
        if (
            isinstance(self.size_bytes, bool)
            or not isinstance(self.size_bytes, int)
            or self.size_bytes < 1
        ):
            raise ValueError("artifact size_bytes must be a positive integer")

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "cid": self.cid,
            "media_type": self.media_type,
            "role": self.role,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
            "source_digest": self.source_digest,
            "stored": self.stored,
        }


def _graph_identity(
    *,
    node_records: Iterable[Mapping[str, Any]],
    edge_records: Iterable[Mapping[str, Any]],
    artifacts: Iterable[AddressedArtifact],
    source_digest: str,
):
    material = {
        "artifacts": [
            artifact.to_dict()
            for artifact in sorted(artifacts, key=lambda item: item.artifact_id)
        ],
        "edges": sorted(
            (dict(item) for item in edge_records),
            key=lambda item: str(item["edge_id"]),
        ),
        "nodes": sorted(
            (dict(item) for item in node_records),
            key=lambda item: str(item["node_id"]),
        ),
        "ontology_version": CORPUS_GRAPH_ONTOLOGY_VERSION,
        "projector_version": CORPUS_GRAPH_PROJECTOR_VERSION,
        "schema_version": CORPUS_GRAPH_SCHEMA_VERSION,
        "source_digest": source_digest,
    }
    return canonical_identity(
        material,
        domain="intent-corpus-evidence-graph",
        schema_version=CORPUS_GRAPH_SCHEMA_VERSION,
    )


@dataclass(frozen=True, slots=True)
class CorpusGraphProjection(Mapping[str, Any]):
    """Immutable graph artifact returned by :class:`CorpusGraphProjector`."""

    nodes: tuple[CorpusGraphNode, ...]
    edges: tuple[CorpusGraphEdge, ...]
    artifacts: tuple[AddressedArtifact, ...]
    source_digest: str
    graph_digest: str
    graph_cid: str
    storage_cid: str = ""
    schema_version: str = CORPUS_GRAPH_SCHEMA_VERSION
    ontology_version: str = CORPUS_GRAPH_ONTOLOGY_VERSION
    projector_version: str = CORPUS_GRAPH_PROJECTOR_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != CORPUS_GRAPH_SCHEMA_VERSION:
            raise ValueError("unsupported corpus graph schema_version")
        if self.ontology_version != CORPUS_GRAPH_ONTOLOGY_VERSION:
            raise ValueError("unsupported corpus graph ontology_version")
        if not _SHA256_RE.fullmatch(self.source_digest):
            raise ValueError("source_digest must be a labeled SHA-256 digest")
        CORPUS_GRAPH_ONTOLOGY.validate(
            self.nodes, self.edges, graph_digest=self.graph_digest
        )
        identity = _graph_identity(
            node_records=(
                {
                    "node_id": item.node_id,
                    "node_type": item.node_type.value,
                    "properties": item.to_dict()["properties"],
                    "source_digests": list(item.source_digests),
                }
                for item in self.nodes
            ),
            edge_records=(
                {
                    "edge_id": item.edge_id,
                    "edge_type": item.edge_type.value,
                    "properties": item.to_dict()["properties"],
                    "source_digests": list(item.source_digests),
                    "source_node_id": item.source_node_id,
                    "target_node_id": item.target_node_id,
                }
                for item in self.edges
            ),
            artifacts=self.artifacts,
            source_digest=self.source_digest,
        )
        if identity.digest != self.graph_digest or identity.cid != self.graph_cid:
            raise ValueError("graph digest/CID does not match the graph projection")

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifacts": [item.to_dict() for item in self.artifacts],
            "edges": [item.to_dict() for item in self.edges],
            "graph_cid": self.graph_cid,
            "graph_digest": self.graph_digest,
            "nodes": [item.to_dict() for item in self.nodes],
            "ontology_version": self.ontology_version,
            "projector_version": self.projector_version,
            "schema_version": self.schema_version,
            "source_digest": self.source_digest,
            "storage_cid": self.storage_cid,
        }

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())

    def __getitem__(self, key: str) -> Any:
        return self.to_dict()[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self.to_dict())

    def __len__(self) -> int:
        return len(self.to_dict())


@dataclass(slots=True)
class _NodeDraft:
    node_id: str
    node_type: CorpusNodeType
    properties: dict[str, Any]
    source_digests: set[str]

    def identity_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "node_type": self.node_type.value,
            "properties": self.properties,
            "source_digests": sorted(self.source_digests),
        }


@dataclass(slots=True)
class _EdgeDraft:
    edge_id: str
    edge_type: CorpusEdgeType
    source_node_id: str
    target_node_id: str
    properties: dict[str, Any]
    source_digests: set[str]

    def identity_dict(self) -> dict[str, Any]:
        return {
            "edge_id": self.edge_id,
            "edge_type": self.edge_type.value,
            "properties": self.properties,
            "source_digests": sorted(self.source_digests),
            "source_node_id": self.source_node_id,
            "target_node_id": self.target_node_id,
        }


def _bounded(value: str) -> str:
    normalized = " ".join(str(value or "").split())
    return normalized[:MAX_BOUNDED_TEXT_CHARS]


def _digest(payload: bytes) -> str:
    return sha256_digest(payload)


def _aggregate_digest(digests: Iterable[str]) -> str:
    values = tuple(sorted(set(digests)))
    if not values:
        raise CorpusGraphProjectionError("a provenance binding cannot be empty")
    if len(values) == 1:
        return values[0]
    return _digest(canonical_json_bytes(list(values)))


def _stable_id(prefix: str, payload: Mapping[str, Any]) -> str:
    identity = canonical_identity(
        dict(payload),
        domain="intent-corpus-evidence-identity",
        schema_version=CORPUS_GRAPH_ONTOLOGY_VERSION,
    )
    return f"intent-corpus:{prefix}:{identity.hexdigest}"


def _safe_repository_uri(value: str) -> str:
    if not value:
        return ""
    try:
        parsed = urlsplit(value)
    except ValueError:
        return ""
    if parsed.scheme.casefold() not in {"http", "https", "hf", "ipfs"}:
        return ""
    if parsed.username is not None or parsed.password is not None:
        return ""
    try:
        port = parsed.port
    except ValueError:
        return ""
    return urlunsplit(
        (
            parsed.scheme.casefold(),
            (parsed.hostname or "").casefold()
            + (f":{port}" if port is not None else ""),
            parsed.path.rstrip("/"),
            "",
            "",
        )
    )


def _publisher_from_uri(value: str, fallback: str) -> str:
    try:
        parsed = urlsplit(value)
    except ValueError:
        return _bounded(fallback)
    parts = [part for part in parsed.path.split("/") if part]
    if parts:
        return _bounded(parts[0])
    return _bounded(parsed.hostname or fallback)


def _section_ranges(text: str, *, limit: int) -> tuple[tuple[str, int, int, int], ...]:
    matches = list(_HEADING_RE.finditer(text))
    if not matches:
        return (("document", 0, len(text), 0),)
    sections: list[tuple[str, int, int, int]] = []
    for index, match in enumerate(matches[:limit]):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        sections.append(
            (
                _bounded(match.group("title")) or "untitled",
                match.start(),
                end,
                len(match.group("marks")),
            )
        )
    return tuple(sections)


def _line_number(text: str, character_offset: int) -> int:
    return text.count("\n", 0, character_offset) + 1


def _embedding_bytes(value: bytes | bytearray | memoryview | Sequence[float]) -> bytes:
    if isinstance(value, (bytes, bytearray, memoryview)):
        payload = bytes(value)
        if not payload:
            raise CorpusGraphProjectionError("embedding bytes must not be empty")
        return payload
    if isinstance(value, (str, Mapping)) or not isinstance(value, Sequence):
        raise TypeError("embedding must be bytes-like or a finite number sequence")
    numbers: list[float] = []
    for item in value:
        try:
            number = float(item)
        except (TypeError, ValueError) as exc:
            raise CorpusGraphProjectionError(
                "embedding values must be finite numbers"
            ) from exc
        if not math.isfinite(number):
            raise CorpusGraphProjectionError(
                "embedding values must be finite numbers"
            )
        numbers.append(number)
    if not numbers:
        raise CorpusGraphProjectionError("embedding must not be empty")
    return canonical_json_bytes(numbers)


class CorpusGraphProjector:
    """Build deterministic, versioned corpus-evidence graph artifacts."""

    def __init__(
        self,
        *,
        storage: CorpusGraphStorage | Any | None = None,
        policy: SkillSourcePolicy | None = None,
        max_records: int = DEFAULT_MAX_RECORDS,
        max_sections_per_record: int = DEFAULT_MAX_SECTIONS_PER_RECORD,
        max_mentions_per_record: int = DEFAULT_MAX_MENTIONS_PER_RECORD,
        max_neighbors_per_record: int = DEFAULT_MAX_NEIGHBORS_PER_RECORD,
    ) -> None:
        for label, value in (
            ("max_records", max_records),
            ("max_sections_per_record", max_sections_per_record),
            ("max_mentions_per_record", max_mentions_per_record),
            ("max_neighbors_per_record", max_neighbors_per_record),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{label} must be a positive integer")
        if storage is not None and not isinstance(storage, CorpusGraphStorage):
            storage = IPLDCorpusGraphStorage(storage)
        self.storage = storage
        self.policy = policy or SkillSourcePolicy()
        self.max_records = max_records
        self.max_sections_per_record = max_sections_per_record
        self.max_mentions_per_record = max_mentions_per_record
        self.max_neighbors_per_record = max_neighbors_per_record

    def project(
        self,
        records: SkillCenterSkillRecord | Iterable[SkillCenterSkillRecord],
        *,
        embeddings: Mapping[
            str, bytes | bytearray | memoryview | Sequence[float]
        ]
        | None = None,
        policy_decisions: Mapping[str, SkillSourcePolicyDecision] | None = None,
        persist: bool | None = None,
    ) -> CorpusGraphProjection:
        """Project one or more records, optionally persisting separate blocks.

        Passing a configured storage adapter makes persistence the default.
        ``persist=False`` retains deterministic CIDs without performing writes.
        """

        ordered = self._coerce_records(records)
        persist = self.storage is not None if persist is None else bool(persist)
        if persist and self.storage is None:
            raise CorpusGraphProjectionError(
                "persist=True requires a CorpusGraphStorage adapter"
            )
        embedding_values = dict(embeddings or {})
        unknown_embeddings = sorted(set(embedding_values) - {r.skill_id for r in ordered})
        if unknown_embeddings:
            raise CorpusGraphProjectionError(
                "embedding supplied for unknown skill_id(s): "
                + ", ".join(unknown_embeddings)
            )

        decisions = self._policy_decisions(ordered, policy_decisions)
        nodes: dict[str, _NodeDraft] = {}
        edges: dict[str, _EdgeDraft] = {}
        artifacts: list[AddressedArtifact] = []
        skill_nodes: dict[str, str] = {}
        record_digests = {
            record.skill_id: self._record_source_digest(record) for record in ordered
        }

        for record in ordered:
            source_digest = record_digests[record.skill_id]
            decision = decisions[record.skill_id]
            body_refs = self._address_bodies(
                record,
                source_digest=source_digest,
                decision=decision,
                persist=persist,
            )
            artifacts.extend(body_refs)
            embedding_ref: AddressedArtifact | None = None
            if record.skill_id in embedding_values:
                if decision.allowed_use not in {
                    AllowedUseDecision.ALLOW_TRAIN_AND_PUBLISH,
                    AllowedUseDecision.ALLOW_INTERNAL_EVALUATION,
                }:
                    raise CorpusGraphProjectionError(
                        f"{record.skill_id}: policy does not permit embedding the source body"
                    )
                embedding_ref = self._address_artifact(
                    role="embedding",
                    payload=_embedding_bytes(embedding_values[record.skill_id]),
                    media_type=EMBEDDING_MEDIA_TYPE,
                    source_digest=source_digest,
                    persist=persist,
                )
                artifacts.append(embedding_ref)
            skill_nodes[record.skill_id] = self._project_record(
                record,
                decision=decision,
                source_digest=source_digest,
                body_refs=body_refs,
                embedding_ref=embedding_ref,
                nodes=nodes,
                edges=edges,
            )

        self._add_family_edges(
            ordered,
            record_digests=record_digests,
            skill_nodes=skill_nodes,
            edges=edges,
        )
        self._add_neighbor_edges(
            ordered,
            record_digests=record_digests,
            skill_nodes=skill_nodes,
            edges=edges,
        )

        source_digest = _aggregate_digest(record_digests.values())
        graph_identity = _graph_identity(
            node_records=(item.identity_dict() for item in nodes.values()),
            edge_records=(item.identity_dict() for item in edges.values()),
            artifacts=artifacts,
            source_digest=source_digest,
        )
        graph_digest = graph_identity.digest

        bound_nodes = tuple(
            CorpusGraphNode(
                node_id=item.node_id,
                node_type=item.node_type,
                properties=item.properties,
                source_digest=_aggregate_digest(item.source_digests),
                source_digests=tuple(item.source_digests),
                graph_digest=graph_digest,
            )
            for item in sorted(nodes.values(), key=lambda item: item.node_id)
        )
        bound_edges = tuple(
            CorpusGraphEdge(
                edge_id=item.edge_id,
                edge_type=item.edge_type,
                source_node_id=item.source_node_id,
                target_node_id=item.target_node_id,
                properties=item.properties,
                source_digest=_aggregate_digest(item.source_digests),
                source_digests=tuple(item.source_digests),
                graph_digest=graph_digest,
            )
            for item in sorted(edges.values(), key=lambda item: item.edge_id)
        )
        ordered_artifacts = tuple(
            sorted(artifacts, key=lambda item: item.artifact_id)
        )
        projection = CorpusGraphProjection(
            nodes=bound_nodes,
            edges=bound_edges,
            artifacts=ordered_artifacts,
            source_digest=source_digest,
            graph_digest=graph_digest,
            graph_cid=graph_identity.cid,
        )
        if not persist:
            return projection
        assert self.storage is not None
        storage_cid = self.storage.put_graph(
            nodes=[self._storage_node(node) for node in bound_nodes],
            relationships=[self._storage_edge(edge) for edge in bound_edges],
            metadata={
                "artifact_refs": [item.to_dict() for item in ordered_artifacts],
                "canonical_graph_cid": projection.graph_cid,
                "graph_digest": graph_digest,
                "ontology_version": CORPUS_GRAPH_ONTOLOGY_VERSION,
                "projector_version": CORPUS_GRAPH_PROJECTOR_VERSION,
                "schema_version": CORPUS_GRAPH_SCHEMA_VERSION,
                "source_digest": source_digest,
            },
        )
        return CorpusGraphProjection(
            nodes=bound_nodes,
            edges=bound_edges,
            artifacts=ordered_artifacts,
            source_digest=source_digest,
            graph_digest=graph_digest,
            graph_cid=graph_identity.cid,
            storage_cid=storage_cid,
        )

    @staticmethod
    def _record_source_digest(record: SkillCenterSkillRecord) -> str:
        """Hash source identity and field digests without embedding source bodies."""

        descriptor = {
            "bundle_sha256": record.bundle_sha256,
            "dataset_id": record.dataset_id,
            "dataset_revision": record.dataset_revision,
            "domain": record.domain,
            "language": record.language,
            "library_md_sha256": hashlib.sha256(
                record.library_md.encode("utf-8")
            ).hexdigest(),
            "metadata_yaml_sha256": hashlib.sha256(
                record.metadata_yaml.encode("utf-8")
            ).hexdigest(),
            "overall_score": record.overall_score,
            "primary_source_id": record.primary_source_id,
            "profile": record.profile,
            "repository_file": record.repository_file,
            "skill_id": record.skill_id,
            "skill_kind": record.skill_kind,
            "skill_md_sha256": record.content_sha256,
            "source_id": record.source_id,
            "source_type": record.source_type,
            "source_url_sha256": hashlib.sha256(
                record.source_url.encode("utf-8")
            ).hexdigest(),
            "source_uri": _safe_repository_uri(record.source_url),
            "title_sha256": hashlib.sha256(
                record.title.encode("utf-8")
            ).hexdigest(),
        }
        return _digest(canonical_json_bytes(descriptor))

    def _coerce_records(
        self, records: SkillCenterSkillRecord | Iterable[SkillCenterSkillRecord]
    ) -> tuple[SkillCenterSkillRecord, ...]:
        if isinstance(records, SkillCenterSkillRecord):
            values = (records,)
        else:
            try:
                values = tuple(records)
            except TypeError as exc:
                raise TypeError(
                    "records must be a SkillCenterSkillRecord or iterable of records"
                ) from exc
        if not values:
            raise CorpusGraphProjectionError("at least one source record is required")
        if len(values) > self.max_records:
            raise CorpusGraphProjectionError(
                f"record count exceeds max_records={self.max_records}"
            )
        if any(not isinstance(item, SkillCenterSkillRecord) for item in values):
            raise TypeError("every item must be a SkillCenterSkillRecord")
        skill_ids = [item.skill_id for item in values]
        duplicates = sorted(
            skill_id for skill_id in set(skill_ids) if skill_ids.count(skill_id) > 1
        )
        if duplicates:
            raise CorpusGraphProjectionError(
                "duplicate skill_id(s): " + ", ".join(duplicates)
            )
        return tuple(
            sorted(
                values,
                key=lambda item: (
                    item.dataset_id,
                    item.dataset_revision,
                    item.repository_file,
                    item.skill_id,
                ),
            )
        )

    def _policy_decisions(
        self,
        records: tuple[SkillCenterSkillRecord, ...],
        supplied: Mapping[str, SkillSourcePolicyDecision] | None,
    ) -> dict[str, SkillSourcePolicyDecision]:
        decisions = dict(supplied or {})
        unknown = sorted(set(decisions) - {record.skill_id for record in records})
        if unknown:
            raise CorpusGraphProjectionError(
                "policy decision supplied for unknown skill_id(s): "
                + ", ".join(unknown)
            )
        for record in records:
            decision = decisions.get(record.skill_id)
            if decision is None:
                decisions[record.skill_id] = self.policy.evaluate(record)
                continue
            if (
                not isinstance(decision, SkillSourcePolicyDecision)
                or decision.skill_id != record.skill_id
            ):
                raise CorpusGraphProjectionError(
                    f"{record.skill_id}: policy decision is missing or mismatched"
                )
        return decisions

    def _address_bodies(
        self,
        record: SkillCenterSkillRecord,
        *,
        source_digest: str,
        decision: SkillSourcePolicyDecision,
        persist: bool,
    ) -> tuple[AddressedArtifact, ...]:
        body_storage_allowed = decision.allowed_use in {
            AllowedUseDecision.ALLOW_TRAIN_AND_PUBLISH,
            AllowedUseDecision.ALLOW_INTERNAL_EVALUATION,
        }
        values = (
            ("skill_body", record.skill_md, SOURCE_BODY_MEDIA_TYPE),
            ("source_metadata", record.metadata_yaml, SOURCE_METADATA_MEDIA_TYPE),
            ("library_body", record.library_md, SOURCE_BODY_MEDIA_TYPE),
        )
        return tuple(
            self._address_artifact(
                role=role,
                payload=value.encode("utf-8"),
                media_type=media_type,
                source_digest=source_digest,
                persist=persist and body_storage_allowed,
            )
            for role, value, media_type in values
            if value
        )

    def _address_artifact(
        self,
        *,
        role: str,
        payload: bytes,
        media_type: str,
        source_digest: str,
        persist: bool,
    ) -> AddressedArtifact:
        digest = _digest(payload)
        computed_cid = cid_v1(payload)
        cid = computed_cid
        if persist:
            assert self.storage is not None
            cid = self.storage.put_bytes(payload, media_type=media_type)
            if not cid:
                raise CorpusGraphProjectionError(
                    "storage returned an empty content address"
                )
        return AddressedArtifact(
            artifact_id=_stable_id(
                "artifact",
                {
                    "media_type": media_type,
                    "role": role,
                    "sha256": digest,
                    "source_digest": source_digest,
                },
            ),
            role=role,
            media_type=media_type,
            sha256=digest,
            cid=cid,
            size_bytes=len(payload),
            source_digest=source_digest,
            stored=persist,
        )

    def _project_record(
        self,
        record: SkillCenterSkillRecord,
        *,
        decision: SkillSourcePolicyDecision,
        source_digest: str,
        body_refs: tuple[AddressedArtifact, ...],
        embedding_ref: AddressedArtifact | None,
        nodes: dict[str, _NodeDraft],
        edges: dict[str, _EdgeDraft],
    ) -> str:
        dataset_node = self._add_node(
            nodes,
            CorpusNodeType.DATASET_REVISION,
            {"dataset_id": record.dataset_id, "revision": record.dataset_revision},
            {
                "dataset_id": _bounded(record.dataset_id),
                "revision": _bounded(record.dataset_revision),
            },
            (source_digest,),
        )
        bundle_node = self._add_node(
            nodes,
            CorpusNodeType.BUNDLE,
            {
                "bundle_sha256": record.bundle_sha256,
                "repository_file": record.repository_file,
            },
            {
                "bundle_sha256": record.bundle_sha256,
                "repository_file": _bounded(record.repository_file),
            },
            (source_digest,),
        )
        repository_uri = _safe_repository_uri(record.source_url)
        repository_key = repository_uri or (
            record.primary_source_id or record.source_id or record.skill_id
        )
        repository_node = self._add_node(
            nodes,
            CorpusNodeType.REPOSITORY,
            {"repository_key": repository_key},
            {"repository_uri": repository_uri},
            (source_digest,),
        )
        document_node = self._add_node(
            nodes,
            CorpusNodeType.SOURCE_DOCUMENT,
            {
                "content_sha256": record.content_sha256,
                "dataset_revision": record.dataset_revision,
                "skill_id": record.skill_id,
            },
            {
                "body_refs": [item.to_dict() for item in body_refs],
                "content_sha256": record.content_sha256,
                "language": _bounded(record.language),
                "primary_source_id": _bounded(record.primary_source_id),
                "source_id": _bounded(record.source_id),
                "source_uri": repository_uri,
            },
            (source_digest,),
        )
        skill_properties: dict[str, Any] = {
            "allowed_use": decision.allowed_use.value,
            "policy_version": decision.policy_version,
            "profile": _bounded(record.profile),
            "review_status": decision.review_status.value,
            "skill_id": _bounded(record.skill_id),
            "skill_kind": _bounded(record.skill_kind),
            "trust_decision": decision.trust_decision.value,
        }
        if decision.allowed_use is not AllowedUseDecision.EXCLUDED:
            skill_properties["title"] = _bounded(record.title)
        else:
            skill_properties["title_sha256"] = hashlib.sha256(
                record.title.encode("utf-8")
            ).hexdigest()
        if record.overall_score is not None:
            skill_properties["overall_score"] = record.overall_score
        if embedding_ref is not None:
            skill_properties["embedding_ref"] = embedding_ref.to_dict()
        skill_node = self._add_node(
            nodes,
            CorpusNodeType.SKILL,
            {
                "dataset_revision": record.dataset_revision,
                "skill_id": record.skill_id,
                "source_digest": source_digest,
            },
            skill_properties,
            (source_digest,),
        )
        license_expression = (
            decision.license_decision.expression or "unresolved"
        )
        license_node = self._add_node(
            nodes,
            CorpusNodeType.LICENSE,
            {"expression": license_expression},
            {
                "allowed_use": decision.license_decision.allowed_use.value,
                "expression": _bounded(license_expression),
                "reason_code": decision.license_decision.reason_code,
                "status": decision.license_decision.status.value,
            },
            (source_digest,),
        )
        domain_node = self._add_node(
            nodes,
            CorpusNodeType.DOMAIN,
            {"domain": record.domain or "unspecified"},
            {"name": _bounded(record.domain or "unspecified")},
            (source_digest,),
        )
        publisher = _publisher_from_uri(record.source_url, record.source_type)
        publisher_node = self._add_node(
            nodes,
            CorpusNodeType.AUTHOR_PUBLISHER,
            {"publisher": publisher or "unknown"},
            {"name": publisher or "unknown", "role": "source_publisher"},
            (source_digest,),
        )

        self._add_edge(
            edges, CorpusEdgeType.CONTAINS, dataset_node, bundle_node, {}, (source_digest,)
        )
        self._add_edge(
            edges, CorpusEdgeType.CONTAINS, bundle_node, document_node, {}, (source_digest,)
        )
        self._add_edge(
            edges, CorpusEdgeType.CONTAINS, document_node, skill_node, {}, (source_digest,)
        )
        self._add_edge(
            edges,
            CorpusEdgeType.DERIVED_FROM,
            document_node,
            repository_node,
            {},
            (source_digest,),
        )
        self._add_edge(
            edges,
            CorpusEdgeType.DERIVED_FROM,
            repository_node,
            publisher_node,
            {},
            (source_digest,),
        )
        self._add_edge(
            edges, CorpusEdgeType.HAS_LICENSE, skill_node, license_node, {}, (source_digest,)
        )
        self._add_edge(
            edges, CorpusEdgeType.HAS_DOMAIN, skill_node, domain_node, {}, (source_digest,)
        )

        body_projection_allowed = decision.allowed_use in {
            AllowedUseDecision.ALLOW_TRAIN_AND_PUBLISH,
            AllowedUseDecision.ALLOW_INTERNAL_EVALUATION,
        }
        sections = (
            _section_ranges(record.skill_md, limit=self.max_sections_per_record)
            if body_projection_allowed
            else ()
        )
        for section_index, (title, start, end, level) in enumerate(sections):
            section_node = self._add_node(
                nodes,
                CorpusNodeType.SECTION,
                {
                    "document_node": document_node,
                    "end_char": end,
                    "section_index": section_index,
                    "start_char": start,
                },
                {
                    "heading": title,
                    "heading_level": level,
                    "section_index": section_index,
                },
                (source_digest,),
            )
            span_node = self._add_node(
                nodes,
                CorpusNodeType.SOURCE_SPAN,
                {
                    "document_node": document_node,
                    "end_char": end,
                    "start_char": start,
                },
                {
                    "body_artifact_id": body_refs[0].artifact_id,
                    "end_char": end,
                    "end_line": _line_number(record.skill_md, end),
                    "start_char": start,
                    "start_line": _line_number(record.skill_md, start),
                },
                (source_digest,),
            )
            self._add_edge(
                edges,
                CorpusEdgeType.CONTAINS,
                skill_node,
                section_node,
                {"order": section_index},
                (source_digest,),
            )
            self._add_edge(
                edges,
                CorpusEdgeType.CONTAINS,
                section_node,
                span_node,
                {},
                (source_digest,),
            )
            self._project_mentions(
                record.skill_md[start:end],
                record=record,
                anchor_node=section_node,
                source_digest=source_digest,
                nodes=nodes,
                edges=edges,
            )
        return skill_node

    def _project_mentions(
        self,
        section_text: str,
        *,
        record: SkillCenterSkillRecord,
        anchor_node: str,
        source_digest: str,
        nodes: dict[str, _NodeDraft],
        edges: dict[str, _EdgeDraft],
    ) -> None:
        tools = sorted(
            {match.group("name") for match in _INLINE_CODE_RE.finditer(section_text)}
        )[: self.max_mentions_per_record]
        for name in tools:
            node = self._add_node(
                nodes,
                CorpusNodeType.TOOL_MENTION,
                {"normalized_name": name.casefold()},
                {"name": name.casefold()},
                (source_digest,),
            )
            self._add_edge(
                edges,
                CorpusEdgeType.MENTIONS,
                anchor_node,
                node,
                {"mention_kind": "explicit_inline_code"},
                (source_digest,),
            )

        entities = sorted(
            {match.group("name") for match in _ENTITY_MENTION_RE.finditer(section_text)}
        )[: self.max_mentions_per_record]
        for name in entities:
            node = self._add_node(
                nodes,
                CorpusNodeType.ENTITY_MENTION,
                {"normalized_name": name.casefold()},
                {"name": name.casefold()},
                (source_digest,),
            )
            self._add_edge(
                edges,
                CorpusEdgeType.MENTIONS,
                anchor_node,
                node,
                {"mention_kind": "explicit_at_reference"},
                (source_digest,),
            )

        citations: dict[str, str] = {}
        for match in _MARKDOWN_LINK_RE.finditer(section_text):
            citations.setdefault(match.group("url"), _bounded(match.group("label")))
        for match in _BARE_URL_RE.finditer(section_text):
            citations.setdefault(match.group(0), "")
        for url, label in sorted(citations.items())[: self.max_mentions_per_record]:
            safe_uri = _safe_repository_uri(url)
            if not safe_uri:
                continue
            cited_node = self._add_node(
                nodes,
                CorpusNodeType.SOURCE_DOCUMENT,
                {"external_uri": safe_uri},
                {
                    "external": True,
                    "source_uri": safe_uri,
                },
                (source_digest,),
            )
            self._add_edge(
                edges,
                CorpusEdgeType.CITES,
                anchor_node,
                cited_node,
                {
                    "citation_kind": "markdown_or_url",
                    "citation_label": label,
                },
                (source_digest,),
            )

    def _add_family_edges(
        self,
        records: tuple[SkillCenterSkillRecord, ...],
        *,
        record_digests: Mapping[str, str],
        skill_nodes: Mapping[str, str],
        edges: dict[str, _EdgeDraft],
    ) -> None:
        primary_groups: defaultdict[str, list[SkillCenterSkillRecord]] = defaultdict(list)
        duplicate_groups: defaultdict[str, list[SkillCenterSkillRecord]] = defaultdict(list)
        for record in records:
            if record.primary_source_id:
                primary_groups[record.primary_source_id].append(record)
            duplicate_groups[record.content_sha256].append(record)
        for group in primary_groups.values():
            self._star_edges(
                group,
                edge_type=CorpusEdgeType.SAME_PRIMARY_SOURCE,
                record_digests=record_digests,
                skill_nodes=skill_nodes,
                edges=edges,
            )
        for group in duplicate_groups.values():
            self._star_edges(
                group,
                edge_type=CorpusEdgeType.DUPLICATE_OF,
                record_digests=record_digests,
                skill_nodes=skill_nodes,
                edges=edges,
            )

    def _star_edges(
        self,
        records: list[SkillCenterSkillRecord],
        *,
        edge_type: CorpusEdgeType,
        record_digests: Mapping[str, str],
        skill_nodes: Mapping[str, str],
        edges: dict[str, _EdgeDraft],
    ) -> None:
        ordered = sorted(records, key=lambda item: skill_nodes[item.skill_id])
        if len(ordered) < 2:
            return
        canonical = ordered[0]
        for record in ordered[1:]:
            self._add_edge(
                edges,
                edge_type,
                skill_nodes[record.skill_id],
                skill_nodes[canonical.skill_id],
                {"canonical": True},
                (
                    record_digests[record.skill_id],
                    record_digests[canonical.skill_id],
                ),
            )

    def _add_neighbor_edges(
        self,
        records: tuple[SkillCenterSkillRecord, ...],
        *,
        record_digests: Mapping[str, str],
        skill_nodes: Mapping[str, str],
        edges: dict[str, _EdgeDraft],
    ) -> None:
        groups: defaultdict[str, list[SkillCenterSkillRecord]] = defaultdict(list)
        for record in records:
            groups[record.domain or "unspecified"].append(record)
        for group in groups.values():
            ordered = sorted(group, key=lambda item: skill_nodes[item.skill_id])
            for index, record in enumerate(ordered):
                for neighbor in ordered[index + 1 : index + 1 + self.max_neighbors_per_record]:
                    if record.content_sha256 == neighbor.content_sha256:
                        continue
                    self._add_edge(
                        edges,
                        CorpusEdgeType.NEIGHBOR_OF,
                        skill_nodes[record.skill_id],
                        skill_nodes[neighbor.skill_id],
                        {
                            "basis": "shared_explicit_domain",
                            "retrieval_only": True,
                            "symmetric": True,
                        },
                        (
                            record_digests[record.skill_id],
                            record_digests[neighbor.skill_id],
                        ),
                    )

    @staticmethod
    def _add_node(
        nodes: dict[str, _NodeDraft],
        node_type: CorpusNodeType,
        identity: Mapping[str, Any],
        properties: Mapping[str, Any],
        source_digests: Iterable[str],
    ) -> str:
        node_id = _stable_id(
            f"node:{node_type.value}",
            {"identity": dict(identity), "node_type": node_type.value},
        )
        existing = nodes.get(node_id)
        if existing is None:
            nodes[node_id] = _NodeDraft(
                node_id=node_id,
                node_type=node_type,
                properties=dict(properties),
                source_digests=set(source_digests),
            )
        else:
            if existing.node_type is not node_type or existing.properties != dict(
                properties
            ):
                raise CorpusGraphProjectionError(
                    f"conflicting definitions for graph node {node_id}"
                )
            existing.source_digests.update(source_digests)
        return node_id

    @staticmethod
    def _add_edge(
        edges: dict[str, _EdgeDraft],
        edge_type: CorpusEdgeType,
        source_node_id: str,
        target_node_id: str,
        properties: Mapping[str, Any],
        source_digests: Iterable[str],
    ) -> str:
        edge_id = _stable_id(
            f"edge:{edge_type.value.casefold()}",
            {
                "edge_type": edge_type.value,
                "properties": dict(properties),
                "source_node_id": source_node_id,
                "target_node_id": target_node_id,
            },
        )
        existing = edges.get(edge_id)
        if existing is None:
            edges[edge_id] = _EdgeDraft(
                edge_id=edge_id,
                edge_type=edge_type,
                source_node_id=source_node_id,
                target_node_id=target_node_id,
                properties=dict(properties),
                source_digests=set(source_digests),
            )
        else:
            existing.source_digests.update(source_digests)
        return edge_id

    @staticmethod
    def _storage_node(node: CorpusGraphNode) -> dict[str, Any]:
        return {
            "id": node.node_id,
            "name": node.node_id,
            "properties": {
                **dict(node.to_dict()["properties"]),
                "graph_digest": node.graph_digest,
                "ontology_version": node.ontology_version,
                "source_digest": node.source_digest,
                "source_digests": list(node.source_digests),
            },
            "type": node.node_type.value,
        }

    @staticmethod
    def _storage_edge(edge: CorpusGraphEdge) -> dict[str, Any]:
        return {
            "id": edge.edge_id,
            "properties": {
                **dict(edge.to_dict()["properties"]),
                "graph_digest": edge.graph_digest,
                "ontology_version": edge.ontology_version,
                "source_digest": edge.source_digest,
                "source_digests": list(edge.source_digests),
            },
            "source_id": edge.source_node_id,
            "target_id": edge.target_node_id,
            "type": edge.edge_type.value,
        }


# Descriptive aliases used by the reviewed interface documents.
IntentCorpusGraph = CorpusGraphProjection
IntentCorpusGraphProjector = CorpusGraphProjector


__all__ = [
    "CORPUS_GRAPH_PROJECTOR_VERSION",
    "DEFAULT_MAX_MENTIONS_PER_RECORD",
    "DEFAULT_MAX_NEIGHBORS_PER_RECORD",
    "DEFAULT_MAX_RECORDS",
    "DEFAULT_MAX_SECTIONS_PER_RECORD",
    "EMBEDDING_MEDIA_TYPE",
    "AddressedArtifact",
    "CorpusGraphProjection",
    "CorpusGraphProjectionError",
    "CorpusGraphProjector",
    "CorpusGraphStorage",
    "IPLDCorpusGraphStorage",
    "IntentCorpusGraph",
    "IntentCorpusGraphProjector",
]
