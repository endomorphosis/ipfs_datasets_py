"""Production knowledge-graph snapshot builder for the public legal corpus (PATLAW-173).

Projects an admitted public patent-law / regulations corpus into a
content-addressed knowledge graph suitable for Hub packaging:

* Nodes for documents, source roots, families, sections, authority kinds, and
  citations — each joined to source CIDs / receipts.
* Source-derived edges for edition membership, family membership, section
  attachment, classification, cross-authority references, and edition
  supersession.
* Authority edges always cite exact source spans and source receipts.
* Zero-orphan verification: every edge endpoint must exist in the node set.
* Deterministic snapshot roots for a pinned corpus root + graph schema version.
* Private / mixed / unreviewed inputs fail closed before any staging.

This module does not upload to Hugging Face. Default mode is dry-run
(in-memory only); ``stage=True`` writes local artifacts only.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
import hashlib
import json
import os
from pathlib import Path
import re
from types import MappingProxyType
from typing import Any, Final, Optional, Union

from ....logic.ir_core.identity import cid_v1_from_digest
from .public_legal_corpus_materializer import (
    DOCUMENTS_FILENAME as CORPUS_DOCUMENTS_FILENAME,
    MANIFEST_FILENAME as CORPUS_MANIFEST_FILENAME,
    SCHEMA_VERSION as CORPUS_SCHEMA_VERSION,
    PrivateOrMixedInputError,
    PublicLegalCorpusError,
    PublicLegalCorpusMaterialization,
    PublicLegalCorpusMaterializer,
    PublicLegalDocument,
    SchemaValidationError as CorpusSchemaValidationError,
    SourceFamily,
    SourceRootBinding,
    UnreviewedRightsError,
    assert_public_only_documents,
    build_default_public_legal_recipe,
    content_cid_of as corpus_content_cid_of,
    content_digest_of as corpus_content_digest_of,
    load_manifest as load_corpus_manifest,
)
from .retrieval_contracts import (
    RETRIEVAL_CONTRACTS_SCHEMA_VERSION,
    AuthorityClaim,
    DisclosureClass,
    EdgeKind,
    EdgeProvenance,
    GraphEdge,
    SourceLink,
    SourceSpan,
    assert_authority_claim_allowed,
    claims_source_authority,
    is_private_disclosure,
)

# ---------------------------------------------------------------------------
# Schema / interface pins
# ---------------------------------------------------------------------------

SCHEMA_VERSION: Final = "patent.public_legal_graph.v1"
GRAPH_SCHEMA_VERSION: Final = "patent.public_legal.knowledge_graph.v1"
INTERFACE: Final = "PublicLegalGraphBuilder@1"
PRODUCER: Final = "producer:public-legal-graph-builder"
CONFIG_ID: Final = "config:public-legal-graph/v1"
TASK_ID: Final = "PATLAW-173"
GOAL_ID: Final = "PATLAW-G211"
CODE_VERSION: Final = "1.0.0"
TENANT_PUBLIC: Final = "tenant-public"
PARTITION_PUBLIC: Final = "public"

NODE_SCHEMA: Final = "patent.public_legal.graph.node@1"
EDGE_SCHEMA: Final = "patent.public_legal.graph.edge@1"
JSONLD_CONTEXT_VERSION: Final = "patent.public_legal.graph.jsonld.v1"

NODES_FILENAME: Final = "graph-nodes.jsonl"
EDGES_FILENAME: Final = "graph-edges.jsonl"
JSONLD_FILENAME: Final = "graph.jsonld"
SNAPSHOT_FILENAME: Final = "public-legal-knowledge-graph.snapshot.json"
RECEIPT_FILENAME: Final = "graph-build-receipt.json"
GRAPH_ROOT_FILENAME: Final = "graph-root.json"

PathLike = Union[str, Path]
JsonMapping = Mapping[str, Any]

_FILE_MODE: Final = 0o600
_DIR_MODE: Final = 0o700

# Closed set of node kinds projected from the public legal corpus.
NODE_KINDS: Final[frozenset[str]] = frozenset(
    {
        "document",
        "source_root",
        "family",
        "section",
        "authority",
        "citation",
    }
)

# Relations projected by this builder (stable string names).
GRAPH_RELATIONS: Final[tuple[str, ...]] = (
    "in_edition",
    "member_of",
    "has_section",
    "classifies",
    "has_citation",
    "references_authority",
    "supersedes",
)

# Relations that are treated as *authority* edges and therefore must cite
# exact source spans and source receipts (fail-closed).
AUTHORITY_RELATIONS: Final[frozenset[str]] = frozenset(
    {
        "classifies",
        "references_authority",
        "supersedes",
        "has_citation",
    }
)

RELATION_TO_EDGE_KIND: Final[Mapping[str, EdgeKind]] = MappingProxyType(
    {
        "in_edition": EdgeKind.OTHER,
        "member_of": EdgeKind.OTHER,
        "has_section": EdgeKind.OTHER,
        "classifies": EdgeKind.CLASSIFIES,
        "has_citation": EdgeKind.REFERENCES_AUTHORITY,
        "references_authority": EdgeKind.REFERENCES_AUTHORITY,
        "supersedes": EdgeKind.SUPERSEDES,
    }
)

# Family pairs that may emit supersedes edges when section_id matches.
_SUPERSEDE_FAMILY_GROUPS: Final[tuple[frozenset[str], ...]] = (
    frozenset({"ecfr", "cfr"}),
    frozenset({"uscode"}),
    frozenset({"mpep"}),
    frozenset({"guidance"}),
    frozenset({"public_law"}),
    frozenset({"federal_register"}),
)

# Citation mention patterns used for cross-authority references.
_CITATION_PATTERNS: Final[tuple[tuple[str, re.Pattern[str]], ...]] = (
    (
        "usc",
        re.compile(
            r"\b(?P<title>\d+)\s*U\.?\s*S\.?\s*C\.?\s*§?\s*(?P<section>[\dA-Za-z.\-]+)",
            re.IGNORECASE,
        ),
    ),
    (
        "cfr",
        re.compile(
            r"\b(?P<title>\d+)\s*C\.?\s*F\.?\s*R\.?\s*§?\s*(?P<section>[\dA-Za-z.\-]+)",
            re.IGNORECASE,
        ),
    ),
    (
        "mpep",
        re.compile(
            r"\bMPEP\s*§?\s*(?P<section>[\dA-Za-z.\-]+)",
            re.IGNORECASE,
        ),
    ),
)

# Fields stripped from content digests so wall-clock metadata cannot drift CIDs.
_NON_CONTENT_SNAPSHOT_KEYS: Final[frozenset[str]] = frozenset(
    {
        "staged_at_utc",
        "notes",
        "output_dir",
        "mode",
    }
)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class PublicLegalGraphError(ValueError):
    """Base error for public legal knowledge-graph builds."""

    code: str = "public_legal_graph_error"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "kind": "error", "message": str(self)}


class OrphanEdgeError(PublicLegalGraphError):
    """Raised when an edge references a missing node endpoint."""

    code = "orphan_edge"


class MissingAuthoritySpanError(PublicLegalGraphError):
    """Raised when an authority edge lacks a source span or receipt."""

    code = "missing_authority_span"


class GraphIntegrityError(PublicLegalGraphError):
    """Raised when digests, counts, or CID joins fail integrity checks."""

    code = "graph_integrity"


class GraphSchemaValidationError(PublicLegalGraphError):
    """Raised when a node/edge descriptor fails structural validation."""

    code = "schema_validation"


class PrivateGraphInputError(PublicLegalGraphError, PrivateOrMixedInputError):
    """Raised when private/mixed disclosure material enters the graph builder."""

    code = "private_or_mixed_input"


# ---------------------------------------------------------------------------
# Enums / helpers
# ---------------------------------------------------------------------------


class BuildMode(str, Enum):
    """Whether the build only materializes in memory or stages to disk."""

    DRY_RUN = "dry_run"
    STAGE = "stage"


def canonical_json(value: Any) -> str:
    """Deterministic JSON encoding for content addressing and equality."""
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def content_digest_of(value: Any) -> str:
    """SHA-256 hex of the canonical JSON encoding of *value*."""
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def content_cid_of(value: Any) -> str:
    """CIDv1 (dag-pb / sha2-256) of the canonical JSON encoding of *value*."""
    digest = hashlib.sha256(canonical_json(value).encode("utf-8")).digest()
    return cid_v1_from_digest(digest)


def content_cid_of_bytes(payload: bytes) -> str:
    """CIDv1 of raw *payload* bytes."""
    if not isinstance(payload, (bytes, bytearray)):
        raise TypeError("payload must be bytes")
    return cid_v1_from_digest(hashlib.sha256(bytes(payload)).digest())


def _require_str(value: Any, name: str, *, maximum: int = 4096) -> str:
    if not isinstance(value, str) or not value.strip():
        raise GraphSchemaValidationError(f"{name} must be a non-empty string")
    text = value.strip()
    if "\x00" in text:
        raise GraphSchemaValidationError(f"{name} must not contain NUL")
    if len(text) > maximum:
        raise GraphSchemaValidationError(f"{name} exceeds max length {maximum}")
    return text


def _optional_str(value: Any, name: str, *, maximum: int = 4096) -> str:
    if value is None or value == "":
        return ""
    return _require_str(value, name, maximum=maximum)


def _ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path, _DIR_MODE)
    except OSError:
        pass
    return path


def _atomic_write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    try:
        with open(tmp, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
        try:
            os.chmod(path, _FILE_MODE)
        except OSError:
            pass
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


def _atomic_write_text(path: Path, text: str) -> None:
    _atomic_write_bytes(path, text.encode("utf-8"))


def _safe_node_id(kind: str, local: str) -> str:
    kind = _require_str(kind, "kind", maximum=64).lower().replace("-", "_")
    local = _require_str(local, "local", maximum=200)
    # Collapse whitespace; keep stable punctuation for citations/ids.
    local = re.sub(r"\s+", "_", local.strip())
    return f"node:{kind}:{local}"


def _safe_edge_id(relation: str, subject_id: str, object_id: str) -> str:
    relation = _require_str(relation, "relation", maximum=64).lower().replace("-", "_")
    # Digest long endpoint ids to keep edge_id within identifier limits.
    subj_key = subject_id if len(subject_id) <= 80 else content_digest_of(subject_id)[:16]
    obj_key = object_id if len(object_id) <= 80 else content_digest_of(object_id)[:16]
    edge_id = f"edge:{relation}:{subj_key}:{obj_key}"
    if len(edge_id) > 240:
        edge_id = f"edge:{relation}:{content_digest_of([relation, subject_id, object_id])[:32]}"
    return edge_id


def _receipt_id_for_document(doc: PublicLegalDocument) -> str:
    return f"receipt:{doc.document_cid}"


def _receipt_id_for_root(root: SourceRootBinding) -> str:
    return f"receipt:root:{root.root_cid}"


def _coerce_disclosure(value: Any) -> DisclosureClass:
    if isinstance(value, DisclosureClass):
        disc = value
    else:
        text = str(value or "").strip().lower().replace("-", "_")
        aliases = {
            "public": DisclosureClass.PUBLIC_OFFICIAL.value,
            "official": DisclosureClass.PUBLIC_OFFICIAL.value,
            "public_official": DisclosureClass.PUBLIC_OFFICIAL.value,
            "public_user": DisclosureClass.PUBLIC_USER.value,
        }
        text = aliases.get(text, text)
        try:
            disc = DisclosureClass(text)
        except ValueError as exc:
            raise PrivateGraphInputError(
                f"unknown disclosure classification: {value!r}"
            ) from exc
    if is_private_disclosure(disc) or disc is DisclosureClass.UNKNOWN:
        raise PrivateGraphInputError(
            f"disclosure {disc.value!r} cannot enter the public legal graph"
        )
    return disc


def _full_text_span(text: str) -> SourceSpan:
    end = len(text) if isinstance(text, str) else 0
    return SourceSpan(start=0, end=end, unit="char")


def _title_or_citation_span(doc: PublicLegalDocument) -> SourceSpan:
    """Prefer a span over the citation string when it appears in the body."""
    body = doc.text or ""
    needle = (doc.citation or "").strip()
    if needle and needle in body:
        start = body.index(needle)
        return SourceSpan(start=start, end=start + len(needle), unit="char")
    title = (doc.title or "").strip()
    if title and title in body:
        start = body.index(title)
        return SourceSpan(start=start, end=start + len(title), unit="char")
    # Fall back to a bounded prefix of the authoritative text.
    end = min(len(body), max(32, len(needle) or 64))
    return SourceSpan(start=0, end=end, unit="char")


def _normalize_citation_key(citation: str) -> str:
    text = re.sub(r"\s+", " ", (citation or "").strip().lower())
    text = text.replace("u.s.c.", "usc").replace("c.f.r.", "cfr")
    text = text.replace("§", " ").replace(".", " ")
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text or "unknown-citation"


def _document_source_link(
    doc: PublicLegalDocument,
    *,
    span: SourceSpan | None = None,
) -> SourceLink:
    return SourceLink(
        source_cid=doc.source_cid,
        artifact_id=f"artifact:{doc.record_id}",
        span=span if span is not None else _title_or_citation_span(doc),
        source_receipt_id=_receipt_id_for_document(doc),
        authority_tier="public-official",
    )


def _root_source_link(root: SourceRootBinding) -> SourceLink:
    return SourceLink(
        source_cid=root.root_cid,
        artifact_id=f"artifact:root:{root.source_id}",
        span=SourceSpan(start=0, end=len(root.source_id), unit="char"),
        source_receipt_id=_receipt_id_for_root(root),
        authority_tier="public-official",
    )


# ---------------------------------------------------------------------------
# Graph node / counts / snapshot records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PublicLegalGraphNode:
    """Source-linked projected graph node for the public legal corpus."""

    node_id: str
    kind: str
    label: str
    source_links: tuple[SourceLink, ...]
    disclosure: DisclosureClass
    tenant_id: str = TENANT_PUBLIC
    document_id: str = ""
    jsonld_id: str = ""
    properties: Mapping[str, str] = field(default_factory=dict)
    effective_from_utc: str = ""
    effective_to_utc: str = ""
    content_digest: str = ""

    def __post_init__(self) -> None:
        node_id = _require_str(self.node_id, "node_id", maximum=256)
        kind = _require_str(self.kind, "kind", maximum=64).lower().replace("-", "_")
        if kind not in NODE_KINDS:
            raise GraphSchemaValidationError(
                f"unknown node kind {kind!r}; known: {', '.join(sorted(NODE_KINDS))}"
            )
        label = _require_str(self.label, "label", maximum=2048)
        if not self.source_links:
            raise GraphSchemaValidationError(
                f"node {node_id!r} requires at least one source link"
            )
        links: list[SourceLink] = []
        for i, raw in enumerate(self.source_links):
            if isinstance(raw, SourceLink):
                links.append(raw)
            elif isinstance(raw, Mapping):
                links.append(SourceLink.from_dict(raw))
            else:
                raise GraphSchemaValidationError(
                    f"source_links[{i}] must be SourceLink or mapping"
                )
        links_t = tuple(links)
        disclosure = _coerce_disclosure(self.disclosure)
        tenant_id = _require_str(self.tenant_id or TENANT_PUBLIC, "tenant_id", maximum=128)
        document_id = _optional_str(self.document_id, "document_id", maximum=256)
        jsonld_id = _optional_str(self.jsonld_id, "jsonld_id", maximum=512)
        if not jsonld_id:
            jsonld_id = f"urn:patlaw:graph:{node_id}"
        props: dict[str, str] = {}
        for key, value in dict(self.properties or {}).items():
            k = _require_str(str(key), "properties.key", maximum=128)
            props[k] = _require_str(str(value), f"properties[{k}]", maximum=8192)
        props_frozen = MappingProxyType(dict(sorted(props.items())))
        effective_from = _optional_str(
            self.effective_from_utc, "effective_from_utc", maximum=64
        )
        effective_to = _optional_str(
            self.effective_to_utc, "effective_to_utc", maximum=64
        )

        body = {
            "disclosure": disclosure.value,
            "document_id": document_id,
            "effective_from_utc": effective_from,
            "effective_to_utc": effective_to,
            "jsonld_id": jsonld_id,
            "kind": kind,
            "label": label,
            "node_id": node_id,
            "properties": dict(props_frozen),
            "schema": NODE_SCHEMA,
            "source_links": [link.to_dict() for link in links_t],
            "tenant_id": tenant_id,
        }
        digest = content_digest_of(body)
        if self.content_digest and self.content_digest != digest:
            raise GraphIntegrityError(
                f"content_digest mismatch for node {node_id!r}"
            )

        object.__setattr__(self, "node_id", node_id)
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "label", label)
        object.__setattr__(self, "source_links", links_t)
        object.__setattr__(self, "disclosure", disclosure)
        object.__setattr__(self, "tenant_id", tenant_id)
        object.__setattr__(self, "document_id", document_id)
        object.__setattr__(self, "jsonld_id", jsonld_id)
        object.__setattr__(self, "properties", props_frozen)
        object.__setattr__(self, "effective_from_utc", effective_from)
        object.__setattr__(self, "effective_to_utc", effective_to)
        object.__setattr__(self, "content_digest", digest)

    @property
    def source_cid(self) -> str:
        return self.source_links[0].source_cid

    def to_dict(self) -> dict[str, Any]:
        return {
            "content_digest": self.content_digest,
            "disclosure": self.disclosure.value,
            "document_id": self.document_id,
            "effective_from_utc": self.effective_from_utc or None,
            "effective_to_utc": self.effective_to_utc or None,
            "jsonld_id": self.jsonld_id,
            "kind": self.kind,
            "label": self.label,
            "node_id": self.node_id,
            "properties": dict(self.properties),
            "schema": NODE_SCHEMA,
            "source_cid": self.source_cid,
            "source_links": [link.to_dict() for link in self.source_links],
            "tenant_id": self.tenant_id,
        }

    def to_hub_row(self) -> dict[str, Any]:
        """Compact row aligned with Hub ``graph_nodes`` config features."""
        return {
            "jsonld_id": self.jsonld_id,
            "kind": self.kind,
            "label": self.label,
            "node_id": self.node_id,
            "source_cid": self.source_cid,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "PublicLegalGraphNode":
        if not isinstance(value, Mapping):
            raise GraphSchemaValidationError("node must be a mapping")
        return cls(
            node_id=str(value.get("node_id") or ""),
            kind=str(value.get("kind") or ""),
            label=str(value.get("label") or ""),
            source_links=tuple(value.get("source_links") or ()),
            disclosure=value.get("disclosure", DisclosureClass.PUBLIC_OFFICIAL.value),
            tenant_id=str(value.get("tenant_id") or TENANT_PUBLIC),
            document_id=str(value.get("document_id") or ""),
            jsonld_id=str(value.get("jsonld_id") or ""),
            properties=dict(value.get("properties") or {}),
            effective_from_utc=str(value.get("effective_from_utc") or ""),
            effective_to_utc=str(value.get("effective_to_utc") or ""),
            content_digest=str(value.get("content_digest") or ""),
        )


@dataclass(frozen=True, slots=True)
class PublicLegalGraphCounts:
    """Aggregate counts bound into the graph snapshot receipt."""

    nodes: int
    edges: int
    authority_edges: int
    documents: int
    by_node_kind: Mapping[str, int]
    by_edge_relation: Mapping[str, int]
    by_family: Mapping[str, int]

    def __post_init__(self) -> None:
        for name in ("nodes", "edges", "authority_edges", "documents"):
            value = getattr(self, name)
            if type(value) is not int or value < 0:
                raise GraphSchemaValidationError(f"{name} must be non-negative int")
        object.__setattr__(
            self, "by_node_kind", MappingProxyType(dict(self.by_node_kind or {}))
        )
        object.__setattr__(
            self,
            "by_edge_relation",
            MappingProxyType(dict(self.by_edge_relation or {})),
        )
        object.__setattr__(
            self, "by_family", MappingProxyType(dict(self.by_family or {}))
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority_edges": self.authority_edges,
            "by_edge_relation": dict(self.by_edge_relation),
            "by_family": dict(self.by_family),
            "by_node_kind": dict(self.by_node_kind),
            "documents": self.documents,
            "edges": self.edges,
            "nodes": self.nodes,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "PublicLegalGraphCounts":
        if not isinstance(value, Mapping):
            raise GraphSchemaValidationError("counts must be a mapping")
        return cls(
            nodes=int(value.get("nodes") or 0),
            edges=int(value.get("edges") or 0),
            authority_edges=int(value.get("authority_edges") or 0),
            documents=int(value.get("documents") or 0),
            by_node_kind=dict(value.get("by_node_kind") or {}),
            by_edge_relation=dict(value.get("by_edge_relation") or {}),
            by_family=dict(value.get("by_family") or {}),
        )


@dataclass(frozen=True, slots=True)
class PublicLegalGraphSnapshot:
    """Content-addressed knowledge-graph snapshot receipt for Hub packaging.

    Binds the pinned public corpus root, graph schema version, node/edge
    artifact digests, and zero-orphan / authority-span gate results.
    """

    schema_version: str
    interface: str
    task_id: str
    goal_id: str
    producer: str
    config_id: str
    code_version: str
    graph_schema_version: str
    partition: str
    tenant_id: str
    corpus_root_cid: str
    corpus_digest_sha256: str
    corpus_schema_version: str
    graph_root_cid: str
    graph_digest_sha256: str
    nodes_cid: str
    edges_cid: str
    jsonld_cid: str
    counts: PublicLegalGraphCounts
    orphan_check: str
    authority_span_check: str
    document_joins: tuple[Mapping[str, Any], ...] = ()
    source_root_cids: Mapping[str, str] = field(default_factory=dict)
    identity: Mapping[str, str] = field(default_factory=dict)
    mode: str = BuildMode.DRY_RUN.value
    notes: str = ""
    staged_at_utc: str = ""

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise GraphSchemaValidationError(
                f"schema_version must be {SCHEMA_VERSION}, got {self.schema_version!r}"
            )
        if self.graph_schema_version != GRAPH_SCHEMA_VERSION:
            raise GraphSchemaValidationError(
                f"graph_schema_version must be {GRAPH_SCHEMA_VERSION}, "
                f"got {self.graph_schema_version!r}"
            )
        if self.partition != PARTITION_PUBLIC:
            raise PrivateGraphInputError(
                f"public legal graph requires partition={PARTITION_PUBLIC!r}"
            )
        if self.orphan_check != "pass":
            raise GraphIntegrityError(
                f"orphan_check must be 'pass', got {self.orphan_check!r}"
            )
        if self.authority_span_check != "pass":
            raise GraphIntegrityError(
                f"authority_span_check must be 'pass', got {self.authority_span_check!r}"
            )
        if not isinstance(self.counts, PublicLegalGraphCounts):
            raise GraphSchemaValidationError("counts must be PublicLegalGraphCounts")
        object.__setattr__(
            self,
            "document_joins",
            tuple(dict(item) for item in (self.document_joins or ())),
        )
        object.__setattr__(
            self,
            "source_root_cids",
            MappingProxyType(dict(self.source_root_cids or {})),
        )
        object.__setattr__(
            self, "identity", MappingProxyType(dict(self.identity or {}))
        )

    def _content_body(self) -> dict[str, Any]:
        body = {
            "authority_span_check": self.authority_span_check,
            "code_version": self.code_version,
            "config_id": self.config_id,
            "corpus_digest_sha256": self.corpus_digest_sha256,
            "corpus_root_cid": self.corpus_root_cid,
            "corpus_schema_version": self.corpus_schema_version,
            "counts": self.counts.to_dict(),
            "document_joins": list(self.document_joins),
            "edges_cid": self.edges_cid,
            "goal_id": self.goal_id,
            "graph_digest_sha256": self.graph_digest_sha256,
            "graph_root_cid": self.graph_root_cid,
            "graph_schema_version": self.graph_schema_version,
            "identity": dict(self.identity),
            "interface": self.interface,
            "jsonld_cid": self.jsonld_cid,
            "nodes_cid": self.nodes_cid,
            "orphan_check": self.orphan_check,
            "partition": self.partition,
            "producer": self.producer,
            "schema_version": self.schema_version,
            "source_root_cids": dict(self.source_root_cids),
            "task_id": self.task_id,
            "tenant_id": self.tenant_id,
        }
        return body

    def to_dict(self) -> dict[str, Any]:
        body = self._content_body()
        body["mode"] = self.mode
        body["notes"] = self.notes
        body["staged_at_utc"] = self.staged_at_utc
        return body

    def to_canonical_json(self) -> str:
        return canonical_json(self._content_body())

    def recompute_graph_root(self) -> tuple[str, str]:
        """Return (digest, cid) of the content body excluding self-pin fields.

        The stored ``graph_root_cid`` / ``graph_digest_sha256`` are computed
        over nodes+edges+jsonld+corpus pins by the builder, not over this
        receipt. This helper digests the receipt content body for equality.
        """
        payload = {
            key: value
            for key, value in self._content_body().items()
            if key not in {"graph_root_cid", "graph_digest_sha256"}
        }
        digest = content_digest_of(payload)
        return digest, content_cid_of(payload)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "PublicLegalGraphSnapshot":
        if not isinstance(value, Mapping):
            raise GraphSchemaValidationError("snapshot must be a mapping")
        counts_raw = value.get("counts") or {}
        counts = (
            counts_raw
            if isinstance(counts_raw, PublicLegalGraphCounts)
            else PublicLegalGraphCounts.from_dict(counts_raw)
        )
        return cls(
            schema_version=str(value.get("schema_version") or SCHEMA_VERSION),
            interface=str(value.get("interface") or INTERFACE),
            task_id=str(value.get("task_id") or TASK_ID),
            goal_id=str(value.get("goal_id") or GOAL_ID),
            producer=str(value.get("producer") or PRODUCER),
            config_id=str(value.get("config_id") or CONFIG_ID),
            code_version=str(value.get("code_version") or CODE_VERSION),
            graph_schema_version=str(
                value.get("graph_schema_version") or GRAPH_SCHEMA_VERSION
            ),
            partition=str(value.get("partition") or PARTITION_PUBLIC),
            tenant_id=str(value.get("tenant_id") or TENANT_PUBLIC),
            corpus_root_cid=str(value.get("corpus_root_cid") or ""),
            corpus_digest_sha256=str(value.get("corpus_digest_sha256") or ""),
            corpus_schema_version=str(
                value.get("corpus_schema_version") or CORPUS_SCHEMA_VERSION
            ),
            graph_root_cid=str(value.get("graph_root_cid") or ""),
            graph_digest_sha256=str(value.get("graph_digest_sha256") or ""),
            nodes_cid=str(value.get("nodes_cid") or ""),
            edges_cid=str(value.get("edges_cid") or ""),
            jsonld_cid=str(value.get("jsonld_cid") or ""),
            counts=counts,
            orphan_check=str(value.get("orphan_check") or "pass"),
            authority_span_check=str(value.get("authority_span_check") or "pass"),
            document_joins=tuple(value.get("document_joins") or ()),
            source_root_cids=dict(value.get("source_root_cids") or {}),
            identity=dict(value.get("identity") or {}),
            mode=str(value.get("mode") or BuildMode.DRY_RUN.value),
            notes=str(value.get("notes") or ""),
            staged_at_utc=str(value.get("staged_at_utc") or ""),
        )


@dataclass(frozen=True, slots=True)
class PublicLegalGraphBuild:
    """Full graph build result: nodes, edges, JSON-LD, and snapshot receipt."""

    nodes: tuple[PublicLegalGraphNode, ...]
    edges: tuple[GraphEdge, ...]
    jsonld: Mapping[str, Any]
    snapshot: PublicLegalGraphSnapshot
    mode: BuildMode = BuildMode.DRY_RUN
    output_dir: Optional[str] = None
    corpus_root_cid: str = ""

    def __post_init__(self) -> None:
        if len(self.nodes) != self.snapshot.counts.nodes:
            raise GraphIntegrityError("node count does not match snapshot counts")
        if len(self.edges) != self.snapshot.counts.edges:
            raise GraphIntegrityError("edge count does not match snapshot counts")
        node_ids = {n.node_id for n in self.nodes}
        if len(node_ids) != len(self.nodes):
            raise GraphIntegrityError("duplicate node_id in graph build")
        for edge in self.edges:
            if edge.subject_id not in node_ids or edge.object_id not in node_ids:
                raise OrphanEdgeError(
                    f"edge {edge.edge_id!r} has orphan endpoint "
                    f"({edge.subject_id!r} -> {edge.object_id!r})"
                )
        object.__setattr__(self, "jsonld", MappingProxyType(dict(self.jsonld or {})))
        if not self.corpus_root_cid:
            object.__setattr__(self, "corpus_root_cid", self.snapshot.corpus_root_cid)

    @property
    def graph_root_cid(self) -> str:
        return self.snapshot.graph_root_cid

    @property
    def graph_digest_sha256(self) -> str:
        return self.snapshot.graph_digest_sha256

    def to_dict(self) -> dict[str, Any]:
        return {
            "corpus_root_cid": self.corpus_root_cid,
            "edges": [edge.to_dict() for edge in self.edges],
            "graph_digest_sha256": self.graph_digest_sha256,
            "graph_root_cid": self.graph_root_cid,
            "jsonld": dict(self.jsonld),
            "mode": self.mode.value if isinstance(self.mode, BuildMode) else str(self.mode),
            "nodes": [node.to_dict() for node in self.nodes],
            "output_dir": self.output_dir,
            "snapshot": self.snapshot.to_dict(),
        }

    def to_canonical_bytes(self) -> bytes:
        """Content-address payload excluding staging presentation noise."""
        payload = {
            "edges": [edge.to_dict() for edge in self.edges],
            "graph_schema_version": GRAPH_SCHEMA_VERSION,
            "jsonld": dict(self.jsonld),
            "nodes": [node.to_dict() for node in self.nodes],
            "snapshot": self.snapshot._content_body(),
        }
        return canonical_json(payload).encode("utf-8")


# ---------------------------------------------------------------------------
# Verification gates
# ---------------------------------------------------------------------------


def is_authority_edge(edge: GraphEdge) -> bool:
    """Return True when *edge* is treated as an authority edge."""
    relation = str(edge.metadata.get("relation") or edge.kind.value)
    if relation in AUTHORITY_RELATIONS:
        return True
    if edge.kind in {
        EdgeKind.REFERENCES_AUTHORITY,
        EdgeKind.CLASSIFIES,
        EdgeKind.SUPERSEDES,
    }:
        return True
    if (
        edge.provenance is EdgeProvenance.SOURCE_DERIVED
        and edge.authority_claim is AuthorityClaim.SOURCE_BOUND
        and claims_source_authority(edge.authority_claim)
    ):
        # Structural membership edges are source-bound but not "authority"
        # edges for the span/receipt gate — only AUTHORITY_RELATIONS qualify
        # beyond kind checks above.
        return relation in AUTHORITY_RELATIONS
    return False


def verify_no_orphan_edges(
    nodes: Sequence[PublicLegalGraphNode],
    edges: Sequence[GraphEdge],
) -> None:
    """Fail closed if any edge endpoint is missing from *nodes*."""
    node_ids = {node.node_id for node in nodes}
    orphans: list[str] = []
    for edge in edges:
        missing: list[str] = []
        if edge.subject_id not in node_ids:
            missing.append(f"subject={edge.subject_id!r}")
        if edge.object_id not in node_ids:
            missing.append(f"object={edge.object_id!r}")
        if missing:
            orphans.append(f"{edge.edge_id}: {', '.join(missing)}")
    if orphans:
        preview = "; ".join(orphans[:8])
        raise OrphanEdgeError(
            f"orphan edges detected ({len(orphans)}): {preview}"
        )


def verify_authority_edges_cite_spans(
    edges: Sequence[GraphEdge],
) -> None:
    """Fail closed if any authority edge lacks a source span or receipt."""
    failures: list[str] = []
    for edge in edges:
        if not is_authority_edge(edge):
            continue
        if edge.provenance is not EdgeProvenance.SOURCE_DERIVED:
            failures.append(
                f"{edge.edge_id}: authority edge must be source_derived "
                f"(got {edge.provenance.value})"
            )
            continue
        if not edge.source_links:
            failures.append(f"{edge.edge_id}: missing source_links")
            continue
        has_span = any(link.span is not None for link in edge.source_links)
        has_receipt = any(
            bool(link.source_receipt_id) for link in edge.source_links
        )
        if not has_span:
            failures.append(f"{edge.edge_id}: missing source span")
        if not has_receipt:
            failures.append(f"{edge.edge_id}: missing source receipt")
    if failures:
        preview = "; ".join(failures[:8])
        raise MissingAuthoritySpanError(
            f"authority edge span/receipt check failed ({len(failures)}): {preview}"
        )


def verify_graph_invariants(
    nodes: Sequence[PublicLegalGraphNode],
    edges: Sequence[GraphEdge],
) -> dict[str, Any]:
    """Run orphan + authority-span gates; return a compact receipt fragment."""
    verify_no_orphan_edges(nodes, edges)
    verify_authority_edges_cite_spans(edges)
    authority_count = sum(1 for e in edges if is_authority_edge(e))
    return {
        "authority_edges": authority_count,
        "authority_span_check": "pass",
        "edges": len(edges),
        "nodes": len(nodes),
        "orphan_check": "pass",
    }


# ---------------------------------------------------------------------------
# JSON-LD projection
# ---------------------------------------------------------------------------


def build_jsonld_document(
    nodes: Sequence[PublicLegalGraphNode],
    edges: Sequence[GraphEdge],
    *,
    corpus_root_cid: str,
    graph_root_cid: str,
    graph_schema_version: str = GRAPH_SCHEMA_VERSION,
) -> dict[str, Any]:
    """Build a deterministic JSON-LD document for Hub packaging."""
    node_entries: list[dict[str, Any]] = []
    for node in sorted(nodes, key=lambda n: n.node_id):
        entry: dict[str, Any] = {
            "@id": node.jsonld_id,
            "@type": f"patlaw:{_pascal_kind(node.kind)}",
            "kind": node.kind,
            "label": node.label,
            "node_id": node.node_id,
            "source_cid": node.source_cid,
            "disclosure": node.disclosure.value,
        }
        if node.document_id:
            entry["document_id"] = node.document_id
        if node.properties:
            entry["properties"] = dict(node.properties)
        node_entries.append(entry)

    edge_entries: list[dict[str, Any]] = []
    node_jsonld = {n.node_id: n.jsonld_id for n in nodes}
    for edge in sorted(edges, key=lambda e: e.edge_id):
        relation = str(edge.metadata.get("relation") or edge.kind.value)
        source_cid = (
            edge.source_links[0].source_cid if edge.source_links else ""
        )
        span = None
        receipt = None
        if edge.source_links:
            span = (
                edge.source_links[0].span.to_dict()
                if edge.source_links[0].span is not None
                else None
            )
            receipt = edge.source_links[0].source_receipt_id
        edge_entries.append(
            {
                "@id": f"urn:patlaw:edge:{edge.edge_id}",
                "@type": "patlaw:GraphEdge",
                "authority_claim": edge.authority_claim.value,
                "edge_id": edge.edge_id,
                "object": node_jsonld.get(edge.object_id, edge.object_id),
                "object_id": edge.object_id,
                "provenance": edge.provenance.value,
                "relation": relation,
                "source_cid": source_cid,
                "source_receipt_id": receipt,
                "span": span,
                "subject": node_jsonld.get(edge.subject_id, edge.subject_id),
                "subject_id": edge.subject_id,
            }
        )

    return {
        "@context": {
            "@vocab": "https://patent-legal.ipfs-accelerate.local/ns/",
            "patlaw": "https://patent-legal.ipfs-accelerate.local/ns/",
            "corpus_root_cid": "patlaw:corpus_root_cid",
            "graph_root_cid": "patlaw:graph_root_cid",
            "graph_schema_version": "patlaw:graph_schema_version",
            "label": "http://www.w3.org/2000/01/rdf-schema#label",
        },
        "@graph": node_entries + edge_entries,
        "corpus_root_cid": corpus_root_cid,
        "graph_root_cid": graph_root_cid,
        "graph_schema_version": graph_schema_version,
        "jsonld_context_version": JSONLD_CONTEXT_VERSION,
        "schema_version": SCHEMA_VERSION,
    }


def _pascal_kind(kind: str) -> str:
    return "".join(part.capitalize() for part in kind.split("_") if part) or "Node"


# ---------------------------------------------------------------------------
# Projection core
# ---------------------------------------------------------------------------


def _make_edge(
    *,
    relation: str,
    subject_id: str,
    object_id: str,
    source_links: Sequence[SourceLink],
    disclosure: DisclosureClass = DisclosureClass.PUBLIC_OFFICIAL,
    tenant_id: str = TENANT_PUBLIC,
    authority_claim: AuthorityClaim = AuthorityClaim.SOURCE_BOUND,
    provenance: EdgeProvenance = EdgeProvenance.SOURCE_DERIVED,
    weight: float = 1.0,
    effective_from_utc: str | None = None,
    effective_to_utc: str | None = None,
    metadata: Mapping[str, str] | None = None,
) -> GraphEdge:
    relation_n = _require_str(relation, "relation", maximum=64).lower().replace("-", "_")
    if relation_n not in RELATION_TO_EDGE_KIND:
        raise GraphSchemaValidationError(f"unsupported relation {relation_n!r}")
    kind = RELATION_TO_EDGE_KIND[relation_n]
    claim = assert_authority_claim_allowed(provenance, authority_claim)
    meta = {"relation": relation_n}
    if metadata:
        for key, value in metadata.items():
            meta[str(key)] = str(value)
    return GraphEdge(
        schema_version=RETRIEVAL_CONTRACTS_SCHEMA_VERSION,
        edge_id=_safe_edge_id(relation_n, subject_id, object_id),
        subject_id=subject_id,
        object_id=object_id,
        kind=kind,
        provenance=provenance,
        authority_claim=claim,
        source_links=tuple(source_links),
        disclosure=disclosure,
        tenant_id=tenant_id,
        weight=weight,
        effective_from_utc=_as_iso_utc(effective_from_utc),
        effective_to_utc=_as_iso_utc(effective_to_utc),
        metadata=meta,
    )


def _project_document_node(doc: PublicLegalDocument) -> PublicLegalGraphNode:
    span = _full_text_span(doc.text)
    link = _document_source_link(doc, span=span)
    props = {
        "authority_claim": doc.authority_claim.value,
        "authority_kind": doc.authority_kind,
        "citation": doc.citation,
        "family": doc.family.value,
        "record_id": doc.record_id,
        "source_root_id": doc.source_root_id,
    }
    if doc.section_id:
        props["section_id"] = doc.section_id
    if doc.current_through:
        props["current_through"] = doc.current_through
    return PublicLegalGraphNode(
        node_id=_safe_node_id("document", doc.record_id),
        kind="document",
        label=doc.title or doc.citation or doc.record_id,
        source_links=(link,),
        disclosure=_coerce_disclosure(doc.classification),
        tenant_id=TENANT_PUBLIC,
        document_id=doc.record_id,
        properties=props,
        effective_from_utc=doc.effective_start or "",
        effective_to_utc=doc.effective_end or "",
    )


def _project_source_root_node(root: SourceRootBinding) -> PublicLegalGraphNode:
    link = _root_source_link(root)
    return PublicLegalGraphNode(
        node_id=_safe_node_id("source_root", root.source_id),
        kind="source_root",
        label=root.source_id,
        source_links=(link,),
        disclosure=DisclosureClass.PUBLIC_OFFICIAL,
        tenant_id=TENANT_PUBLIC,
        properties={
            "current_through": root.current_through,
            "family": root.family.value,
            "source_id": root.source_id,
            "source_revision": root.source_revision,
            "source_uri": root.source_uri,
        },
    )


def _project_family_node(
    family: SourceFamily | str,
    *,
    anchor: PublicLegalDocument,
) -> PublicLegalGraphNode:
    fam = family.value if isinstance(family, SourceFamily) else str(family)
    link = _document_source_link(anchor, span=_title_or_citation_span(anchor))
    return PublicLegalGraphNode(
        node_id=_safe_node_id("family", fam),
        kind="family",
        label=fam,
        source_links=(link,),
        disclosure=DisclosureClass.PUBLIC_OFFICIAL,
        tenant_id=TENANT_PUBLIC,
        properties={"family": fam},
    )


def _project_section_node(
    section_id: str,
    *,
    family: str,
    anchor: PublicLegalDocument,
) -> PublicLegalGraphNode:
    local = f"{family}:{section_id}"
    # Prefer a span over the section id token when present in the body.
    body = anchor.text or ""
    if section_id and section_id in body:
        start = body.index(section_id)
        span = SourceSpan(start=start, end=start + len(section_id), unit="char")
    else:
        span = _title_or_citation_span(anchor)
    link = _document_source_link(anchor, span=span)
    return PublicLegalGraphNode(
        node_id=_safe_node_id("section", local),
        kind="section",
        label=f"{family} § {section_id}",
        source_links=(link,),
        disclosure=DisclosureClass.PUBLIC_OFFICIAL,
        tenant_id=TENANT_PUBLIC,
        document_id=anchor.record_id,
        properties={"family": family, "section_id": section_id},
    )


def _project_authority_node(
    authority_kind: str,
    *,
    anchor: PublicLegalDocument,
) -> PublicLegalGraphNode:
    link = _document_source_link(anchor, span=_title_or_citation_span(anchor))
    return PublicLegalGraphNode(
        node_id=_safe_node_id("authority", authority_kind),
        kind="authority",
        label=authority_kind,
        source_links=(link,),
        disclosure=DisclosureClass.PUBLIC_OFFICIAL,
        tenant_id=TENANT_PUBLIC,
        properties={"authority_kind": authority_kind},
    )


def _project_citation_node(
    citation: str,
    *,
    anchor: PublicLegalDocument,
    span: SourceSpan | None = None,
) -> PublicLegalGraphNode:
    key = _normalize_citation_key(citation)
    link = _document_source_link(
        anchor, span=span if span is not None else _title_or_citation_span(anchor)
    )
    return PublicLegalGraphNode(
        node_id=_safe_node_id("citation", key),
        kind="citation",
        label=citation,
        source_links=(link,),
        disclosure=DisclosureClass.PUBLIC_OFFICIAL,
        tenant_id=TENANT_PUBLIC,
        document_id=anchor.record_id,
        properties={
            "citation": citation,
            "citation_key": key,
        },
    )


def _find_citation_mentions(text: str) -> list[tuple[str, int, int, str]]:
    """Return (family_hint, start, end, normalized_label) mentions in *text*."""
    found: list[tuple[str, int, int, str]] = []
    seen_spans: set[tuple[int, int]] = set()
    for family_hint, pattern in _CITATION_PATTERNS:
        for match in pattern.finditer(text or ""):
            span_key = (match.start(), match.end())
            if span_key in seen_spans:
                continue
            seen_spans.add(span_key)
            if family_hint == "mpep":
                section = match.group("section")
                label = f"MPEP § {section}"
            else:
                title = match.group("title")
                section = match.group("section")
                if family_hint == "usc":
                    label = f"{title} U.S.C. § {section}"
                else:
                    label = f"{title} C.F.R. § {section}"
            found.append((family_hint, match.start(), match.end(), label))
    found.sort(key=lambda item: (item[1], item[2], item[3]))
    return found


def _citation_matches_document(label: str, doc: PublicLegalDocument) -> bool:
    """Heuristic match between a text mention and a corpus document citation."""
    left = _normalize_citation_key(label)
    right = _normalize_citation_key(doc.citation)
    if not left or not right:
        return False
    if left == right:
        return True
    # Compare core tokens (title + section digits).
    left_parts = [p for p in left.split("-") if p]
    right_parts = [p for p in right.split("-") if p]
    if len(left_parts) >= 2 and len(right_parts) >= 2:
        # e.g. 35-usc-101 vs usc-35-101 / 35-u-s-c-101
        left_digits = [p for p in left_parts if p.isdigit() or re.match(r"^\d", p)]
        right_digits = [p for p in right_parts if p.isdigit() or re.match(r"^\d", p)]
        if left_digits and right_digits and left_digits == right_digits:
            left_has_usc = "usc" in left_parts or "u" in left_parts
            right_has_usc = "usc" in right_parts or "u" in right_parts
            left_has_cfr = "cfr" in left_parts or "c" in left_parts
            right_has_cfr = "cfr" in right_parts or "c" in right_parts
            left_has_mpep = "mpep" in left_parts
            right_has_mpep = "mpep" in right_parts
            if left_has_usc and right_has_usc:
                return True
            if left_has_cfr and right_has_cfr:
                return True
            if left_has_mpep and right_has_mpep:
                return True
    # Section id exact membership.
    if doc.section_id:
        sec = _normalize_citation_key(doc.section_id)
        if sec and sec in left.split("-"):
            fam = doc.family.value
            if fam in {"uscode", "usc"} and ("usc" in left or "u-s-c" in left):
                return True
            if fam in {"ecfr", "cfr"} and ("cfr" in left or "c-f-r" in left):
                return True
            if fam == "mpep" and "mpep" in left:
                return True
    return False


def _through_key(value: str) -> str:
    """Sortable key for current_through dates (YYYY-MM-DD prefix)."""
    text = (value or "").strip()
    if len(text) >= 10 and text[4] == "-" and text[7] == "-":
        return text[:10]
    return text


_DATE_ONLY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _as_iso_utc(value: str | None) -> str | None:
    """Coerce YYYY-MM-DD (or empty) into an ISO-8601 UTC timestamp for GraphEdge."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if _DATE_ONLY_RE.fullmatch(text):
        return f"{text}T00:00:00Z"
    return text


def project_public_legal_graph(
    documents: Sequence[PublicLegalDocument],
    source_roots: Sequence[SourceRootBinding],
    *,
    tenant_id: str = TENANT_PUBLIC,
) -> tuple[tuple[PublicLegalGraphNode, ...], tuple[GraphEdge, ...]]:
    """Project corpus documents + roots into sorted graph nodes and edges."""
    if not documents:
        raise GraphSchemaValidationError("at least one document is required")
    if not source_roots:
        raise GraphSchemaValidationError("at least one source root is required")

    assert_public_only_documents(documents)
    docs = tuple(sorted(documents, key=lambda d: d.record_id))
    roots = tuple(sorted(source_roots, key=lambda r: r.source_id))
    root_by_id = {r.source_id: r for r in roots}

    nodes_by_id: dict[str, PublicLegalGraphNode] = {}
    edges_by_id: dict[str, GraphEdge] = {}

    def add_node(node: PublicLegalGraphNode) -> PublicLegalGraphNode:
        existing = nodes_by_id.get(node.node_id)
        if existing is None:
            nodes_by_id[node.node_id] = node
            return node
        # Prefer the first inserted node (deterministic by insertion order of
        # sorted documents/roots). Receipts already bound.
        return existing

    def add_edge(edge: GraphEdge) -> None:
        # Endpoints must already exist — fail closed rather than drop.
        if edge.subject_id not in nodes_by_id or edge.object_id not in nodes_by_id:
            raise OrphanEdgeError(
                f"refusing to add orphan edge {edge.edge_id!r}: "
                f"{edge.subject_id!r} -> {edge.object_id!r}"
            )
        # Last write wins only if identical edge_id; prefer first for stability.
        if edge.edge_id not in edges_by_id:
            edges_by_id[edge.edge_id] = edge

    # Source-root nodes.
    for root in roots:
        add_node(_project_source_root_node(root))

    # Document nodes + structural edges.
    for doc in docs:
        if doc.source_root_id not in root_by_id:
            raise GraphSchemaValidationError(
                f"document {doc.record_id!r} references unknown source root "
                f"{doc.source_root_id!r}"
            )
        root = root_by_id[doc.source_root_id]
        doc_node = add_node(_project_document_node(doc))
        family_node = add_node(_project_family_node(doc.family, anchor=doc))
        authority_node = add_node(
            _project_authority_node(doc.authority_kind, anchor=doc)
        )
        citation_node = add_node(
            _project_citation_node(doc.citation, anchor=doc)
        )

        structural_link = _document_source_link(
            doc, span=_title_or_citation_span(doc)
        )
        # document → source_root (edition membership; structural, not authority)
        add_edge(
            _make_edge(
                relation="in_edition",
                subject_id=doc_node.node_id,
                object_id=_safe_node_id("source_root", root.source_id),
                source_links=(structural_link,),
                disclosure=_coerce_disclosure(doc.classification),
                tenant_id=tenant_id,
                authority_claim=AuthorityClaim.SOURCE_BOUND,
                effective_from_utc=doc.effective_start or None,
                effective_to_utc=doc.effective_end or None,
            )
        )
        # document → family
        add_edge(
            _make_edge(
                relation="member_of",
                subject_id=doc_node.node_id,
                object_id=family_node.node_id,
                source_links=(structural_link,),
                disclosure=_coerce_disclosure(doc.classification),
                tenant_id=tenant_id,
            )
        )
        # document → authority kind (authority edge: span + receipt required)
        add_edge(
            _make_edge(
                relation="classifies",
                subject_id=doc_node.node_id,
                object_id=authority_node.node_id,
                source_links=(structural_link,),
                disclosure=_coerce_disclosure(doc.classification),
                tenant_id=tenant_id,
                authority_claim=doc.authority_claim,
            )
        )
        # document → citation label (authority edge)
        add_edge(
            _make_edge(
                relation="has_citation",
                subject_id=doc_node.node_id,
                object_id=citation_node.node_id,
                source_links=(structural_link,),
                disclosure=_coerce_disclosure(doc.classification),
                tenant_id=tenant_id,
                authority_claim=AuthorityClaim.SOURCE_BOUND,
            )
        )
        if doc.section_id:
            section_node = add_node(
                _project_section_node(
                    doc.section_id, family=doc.family.value, anchor=doc
                )
            )
            add_edge(
                _make_edge(
                    relation="has_section",
                    subject_id=doc_node.node_id,
                    object_id=section_node.node_id,
                    source_links=(
                        _document_source_link(
                            doc,
                            span=(
                                SourceSpan(
                                    start=doc.text.index(doc.section_id),
                                    end=doc.text.index(doc.section_id)
                                    + len(doc.section_id),
                                    unit="char",
                                )
                                if doc.section_id in (doc.text or "")
                                else _title_or_citation_span(doc)
                            ),
                        ),
                    ),
                    disclosure=_coerce_disclosure(doc.classification),
                    tenant_id=tenant_id,
                )
            )

    # Cross-document / text-derived authority references.
    for doc in docs:
        doc_node_id = _safe_node_id("document", doc.record_id)
        mentions = _find_citation_mentions(doc.text)
        for _family_hint, start, end, label in mentions:
            span = SourceSpan(start=start, end=end, unit="char")
            link = _document_source_link(doc, span=span)
            # Always attach a citation node for the mention.
            cite_node = add_node(
                _project_citation_node(label, anchor=doc, span=span)
            )
            add_edge(
                _make_edge(
                    relation="references_authority",
                    subject_id=doc_node_id,
                    object_id=cite_node.node_id,
                    source_links=(link,),
                    disclosure=_coerce_disclosure(doc.classification),
                    tenant_id=tenant_id,
                    authority_claim=AuthorityClaim.SOURCE_BOUND,
                    metadata={"mention": label[:128]},
                )
            )
            # When the mention resolves to another corpus document, also link
            # document → document as references_authority.
            for other in docs:
                if other.record_id == doc.record_id:
                    continue
                if _citation_matches_document(label, other):
                    other_id = _safe_node_id("document", other.record_id)
                    add_edge(
                        _make_edge(
                            relation="references_authority",
                            subject_id=doc_node_id,
                            object_id=other_id,
                            source_links=(link,),
                            disclosure=_coerce_disclosure(doc.classification),
                            tenant_id=tenant_id,
                            authority_claim=AuthorityClaim.SOURCE_BOUND,
                            metadata={
                                "mention": label[:128],
                                "resolved_record_id": other.record_id,
                            },
                        )
                    )

    # Supersedes edges for same section within a family group, ordered by
    # current_through (newer supersedes older).
    section_groups: dict[tuple[str, str], list[PublicLegalDocument]] = defaultdict(list)
    for doc in docs:
        if not doc.section_id:
            continue
        group_key = None
        for group in _SUPERSEDE_FAMILY_GROUPS:
            if doc.family.value in group:
                # Use a stable group label (sorted join) so ecfr/cfr share a bucket.
                group_key = ("/".join(sorted(group)), doc.section_id)
                break
        if group_key is None:
            group_key = (doc.family.value, doc.section_id)
        section_groups[group_key].append(doc)

    for _key, group_docs in sorted(section_groups.items(), key=lambda kv: kv[0]):
        ordered = sorted(
            group_docs,
            key=lambda d: (_through_key(d.current_through), d.record_id),
        )
        for older, newer in zip(ordered, ordered[1:]):
            if older.record_id == newer.record_id:
                continue
            if _through_key(newer.current_through) <= _through_key(older.current_through):
                # No temporal ordering signal; skip rather than invent.
                if newer.current_through == older.current_through:
                    continue
            # Span/receipt from the newer document's citation binding.
            link = _document_source_link(newer, span=_title_or_citation_span(newer))
            add_edge(
                _make_edge(
                    relation="supersedes",
                    subject_id=_safe_node_id("document", newer.record_id),
                    object_id=_safe_node_id("document", older.record_id),
                    source_links=(link,),
                    disclosure=_coerce_disclosure(newer.classification),
                    tenant_id=tenant_id,
                    authority_claim=AuthorityClaim.SOURCE_BOUND,
                    metadata={
                        "newer_through": newer.current_through,
                        "older_through": older.current_through,
                        "section_id": newer.section_id or older.section_id,
                    },
                )
            )

    nodes = tuple(sorted(nodes_by_id.values(), key=lambda n: n.node_id))
    edges = tuple(sorted(edges_by_id.values(), key=lambda e: e.edge_id))
    verify_graph_invariants(nodes, edges)
    return nodes, edges


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------


@dataclass
class PublicLegalGraphBuilder:
    """Build a deterministic public legal knowledge-graph snapshot.

    Parameters
    ----------
    tenant_id:
        Tenant partition for all projected nodes/edges (default public).
    code_version:
        Builder code pin bound into the snapshot receipt.
    """

    tenant_id: str = TENANT_PUBLIC
    code_version: str = CODE_VERSION

    def build_from_materialization(
        self,
        materialization: PublicLegalCorpusMaterialization,
        *,
        stage: bool = False,
        output_dir: PathLike | None = None,
        notes: str = "",
    ) -> PublicLegalGraphBuild:
        """Build a graph snapshot from an admitted public corpus materialization."""
        if not isinstance(materialization, PublicLegalCorpusMaterialization):
            raise GraphSchemaValidationError(
                "materialization must be PublicLegalCorpusMaterialization"
            )
        if materialization.manifest.partition != PARTITION_PUBLIC:
            raise PrivateGraphInputError(
                "graph builder only accepts public corpus materializations"
            )
        assert_public_only_documents(materialization.documents)
        return self._build(
            documents=materialization.documents,
            source_roots=materialization.manifest.source_roots,
            corpus_root_cid=materialization.corpus_root_cid,
            corpus_digest_sha256=materialization.corpus_digest_sha256,
            corpus_schema_version=materialization.manifest.schema_version,
            document_joins=tuple(materialization.manifest.document_joins),
            source_root_cids={
                root.source_id: root.root_cid
                for root in materialization.manifest.source_roots
            },
            stage=stage,
            output_dir=output_dir,
            notes=notes,
        )

    def build_from_recipe(
        self,
        recipe: Mapping[str, Any] | None = None,
        *,
        require_all_families: bool = True,
        stage: bool = False,
        output_dir: PathLike | None = None,
        notes: str = "",
    ) -> PublicLegalGraphBuild:
        """Materialize a public corpus from *recipe* then build the graph."""
        if recipe is None:
            recipe = build_default_public_legal_recipe()
        materializer = PublicLegalCorpusMaterializer(
            require_all_families=require_all_families
        )
        materialization = materializer.materialize_from_recipe(recipe)
        return self.build_from_materialization(
            materialization,
            stage=stage,
            output_dir=output_dir,
            notes=notes or str(recipe.get("notes") or ""),
        )

    def build_from_corpus_dir(
        self,
        corpus_dir: PathLike,
        *,
        stage: bool = False,
        output_dir: PathLike | None = None,
        notes: str = "",
    ) -> PublicLegalGraphBuild:
        """Load a staged public corpus directory and build the graph."""
        root = Path(corpus_dir)
        manifest_path = root / CORPUS_MANIFEST_FILENAME
        documents_path = root / CORPUS_DOCUMENTS_FILENAME
        if not manifest_path.is_file():
            raise PublicLegalGraphError(
                f"corpus manifest not found: {manifest_path}",
                code="missing_corpus_manifest",
            )
        if not documents_path.is_file():
            raise PublicLegalGraphError(
                f"corpus documents not found: {documents_path}",
                code="missing_corpus_documents",
            )
        try:
            manifest = load_corpus_manifest(manifest_path)
        except PublicLegalCorpusError as exc:
            raise PublicLegalGraphError(str(exc), code=getattr(exc, "code", None)) from exc

        docs_raw = documents_path.read_text(encoding="utf-8").strip()
        documents: list[PublicLegalDocument] = []
        if docs_raw:
            # Support JSONL or a JSON array.
            if docs_raw.startswith("["):
                payload = json.loads(docs_raw)
                if not isinstance(payload, list):
                    raise GraphSchemaValidationError("documents JSON must be an array")
                rows = payload
            else:
                rows = []
                for line_no, line in enumerate(docs_raw.splitlines(), start=1):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rows.append(json.loads(line))
                    except json.JSONDecodeError as exc:
                        raise GraphSchemaValidationError(
                            f"invalid documents JSONL line {line_no}: {exc}"
                        ) from exc
            for index, row in enumerate(rows):
                if not isinstance(row, Mapping):
                    raise GraphSchemaValidationError(
                        f"documents[{index}] must be an object"
                    )
                try:
                    documents.append(PublicLegalDocument.from_dict(row))
                except (
                    PrivateOrMixedInputError,
                    UnreviewedRightsError,
                    PublicLegalCorpusError,
                    CorpusSchemaValidationError,
                ):
                    raise
                except Exception as exc:
                    raise GraphSchemaValidationError(
                        f"documents[{index}] is invalid: {exc}"
                    ) from exc

        admitted = tuple(sorted(documents, key=lambda d: d.record_id))
        assert_public_only_documents(admitted)
        if manifest.partition != PARTITION_PUBLIC:
            raise PrivateGraphInputError(
                "graph builder only accepts public corpus materializations"
            )
        return self._build(
            documents=admitted,
            source_roots=manifest.source_roots,
            corpus_root_cid=manifest.corpus_root_cid,
            corpus_digest_sha256=manifest.corpus_digest_sha256,
            corpus_schema_version=manifest.schema_version,
            document_joins=tuple(manifest.document_joins),
            source_root_cids={
                root.source_id: root.root_cid for root in manifest.source_roots
            },
            stage=stage,
            output_dir=output_dir,
            notes=notes,
        )

    def build(
        self,
        *,
        documents: Sequence[PublicLegalDocument | Mapping[str, Any]],
        source_roots: Sequence[SourceRootBinding | Mapping[str, Any]],
        corpus_root_cid: str = "",
        corpus_digest_sha256: str = "",
        stage: bool = False,
        output_dir: PathLike | None = None,
        notes: str = "",
    ) -> PublicLegalGraphBuild:
        """Build from explicit document/root sequences (advanced API)."""
        roots = tuple(
            sorted(
                (
                    r
                    if isinstance(r, SourceRootBinding)
                    else SourceRootBinding.from_dict(r)
                    for r in source_roots
                ),
                key=lambda r: r.source_id,
            )
        )
        root_by_id = {r.source_id: r for r in roots}
        admitted: list[PublicLegalDocument] = []
        for index, raw in enumerate(documents):
            if isinstance(raw, PublicLegalDocument):
                doc = raw
            elif isinstance(raw, Mapping):
                source_root_id = str(
                    raw.get("source_root_id") or raw.get("source_id") or ""
                )
                default_through = ""
                if source_root_id in root_by_id:
                    default_through = root_by_id[source_root_id].current_through
                doc = PublicLegalDocument.from_dict(
                    raw,
                    default_source_root_id=source_root_id,
                    default_current_through=default_through,
                )
            else:
                raise GraphSchemaValidationError(
                    f"documents[{index}] must be PublicLegalDocument or mapping"
                )
            admitted.append(doc)
        admitted_t = tuple(sorted(admitted, key=lambda d: d.record_id))
        assert_public_only_documents(admitted_t)

        # When corpus pins are omitted, derive a stable pin from admitted inputs.
        if not corpus_root_cid or not corpus_digest_sha256:
            pin_body = {
                "documents": [d.to_dict() for d in admitted_t],
                "source_roots": [r.to_dict() for r in roots],
            }
            corpus_digest_sha256 = corpus_content_digest_of(pin_body)
            corpus_root_cid = corpus_content_cid_of(pin_body)

        joins = tuple(doc.to_index_join() for doc in admitted_t)
        return self._build(
            documents=admitted_t,
            source_roots=roots,
            corpus_root_cid=corpus_root_cid,
            corpus_digest_sha256=corpus_digest_sha256,
            corpus_schema_version=CORPUS_SCHEMA_VERSION,
            document_joins=joins,
            source_root_cids={r.source_id: r.root_cid for r in roots},
            stage=stage,
            output_dir=output_dir,
            notes=notes,
        )

    def _build(
        self,
        *,
        documents: Sequence[PublicLegalDocument],
        source_roots: Sequence[SourceRootBinding],
        corpus_root_cid: str,
        corpus_digest_sha256: str,
        corpus_schema_version: str,
        document_joins: Sequence[Mapping[str, Any]],
        source_root_cids: Mapping[str, str],
        stage: bool,
        output_dir: PathLike | None,
        notes: str,
    ) -> PublicLegalGraphBuild:
        nodes, edges = project_public_legal_graph(
            documents,
            source_roots,
            tenant_id=self.tenant_id,
        )
        gate = verify_graph_invariants(nodes, edges)

        by_kind = Counter(n.kind for n in nodes)
        by_relation = Counter(
            str(e.metadata.get("relation") or e.kind.value) for e in edges
        )
        by_family = Counter(d.family.value for d in documents)
        counts = PublicLegalGraphCounts(
            nodes=len(nodes),
            edges=len(edges),
            authority_edges=int(gate["authority_edges"]),
            documents=len(documents),
            by_node_kind=dict(sorted(by_kind.items())),
            by_edge_relation=dict(sorted(by_relation.items())),
            by_family=dict(sorted(by_family.items())),
        )

        nodes_payload = [n.to_dict() for n in nodes]
        edges_payload = [e.to_dict() for e in edges]
        nodes_cid = content_cid_of(nodes_payload)
        edges_cid = content_cid_of(edges_payload)

        # Graph root binds corpus pin + schema + node/edge payloads (no wall clock).
        graph_identity_body = {
            "corpus_digest_sha256": corpus_digest_sha256,
            "corpus_root_cid": corpus_root_cid,
            "edges": edges_payload,
            "graph_schema_version": GRAPH_SCHEMA_VERSION,
            "nodes": nodes_payload,
            "schema_version": SCHEMA_VERSION,
        }
        graph_digest = content_digest_of(graph_identity_body)
        graph_root_cid = content_cid_of(graph_identity_body)

        jsonld = build_jsonld_document(
            nodes,
            edges,
            corpus_root_cid=corpus_root_cid,
            graph_root_cid=graph_root_cid,
            graph_schema_version=GRAPH_SCHEMA_VERSION,
        )
        jsonld_cid = content_cid_of(jsonld)

        mode = BuildMode.STAGE if stage else BuildMode.DRY_RUN
        snapshot = PublicLegalGraphSnapshot(
            schema_version=SCHEMA_VERSION,
            interface=INTERFACE,
            task_id=TASK_ID,
            goal_id=GOAL_ID,
            producer=PRODUCER,
            config_id=CONFIG_ID,
            code_version=self.code_version,
            graph_schema_version=GRAPH_SCHEMA_VERSION,
            partition=PARTITION_PUBLIC,
            tenant_id=self.tenant_id,
            corpus_root_cid=corpus_root_cid,
            corpus_digest_sha256=corpus_digest_sha256,
            corpus_schema_version=corpus_schema_version,
            graph_root_cid=graph_root_cid,
            graph_digest_sha256=graph_digest,
            nodes_cid=nodes_cid,
            edges_cid=edges_cid,
            jsonld_cid=jsonld_cid,
            counts=counts,
            orphan_check="pass",
            authority_span_check="pass",
            document_joins=tuple(document_joins),
            source_root_cids=dict(source_root_cids),
            identity={
                "code_version": self.code_version,
                "config_id": CONFIG_ID,
                "graph_schema_version": GRAPH_SCHEMA_VERSION,
                "interface": INTERFACE,
                "producer": PRODUCER,
                "schema_version": SCHEMA_VERSION,
                "task_id": TASK_ID,
            },
            mode=mode.value,
            notes=str(notes or ""),
            staged_at_utc="",
        )

        result = PublicLegalGraphBuild(
            nodes=nodes,
            edges=edges,
            jsonld=jsonld,
            snapshot=snapshot,
            mode=mode,
            output_dir=None,
            corpus_root_cid=corpus_root_cid,
        )

        if stage:
            if output_dir is None:
                raise PublicLegalGraphError(
                    "output_dir is required when stage=True",
                    code="missing_output_dir",
                )
            return self.stage(result, output_dir=output_dir)
        return result

    def stage(
        self,
        result: PublicLegalGraphBuild,
        *,
        output_dir: PathLike,
    ) -> PublicLegalGraphBuild:
        """Write nodes, edges, JSON-LD, snapshot, and receipt under *output_dir*."""
        out = _ensure_dir(Path(output_dir))
        # Fail closed if private somehow slipped through before write.
        for node in result.nodes:
            _coerce_disclosure(node.disclosure)
        verify_graph_invariants(result.nodes, result.edges)

        nodes_path = out / NODES_FILENAME
        edges_path = out / EDGES_FILENAME
        jsonld_path = out / JSONLD_FILENAME
        snapshot_path = out / SNAPSHOT_FILENAME
        receipt_path = out / RECEIPT_FILENAME
        root_path = out / GRAPH_ROOT_FILENAME

        nodes_lines = (
            "\n".join(canonical_json(n.to_dict()) for n in result.nodes) + "\n"
            if result.nodes
            else ""
        )
        edges_lines = (
            "\n".join(canonical_json(e.to_dict()) for e in result.edges) + "\n"
            if result.edges
            else ""
        )
        _atomic_write_text(nodes_path, nodes_lines)
        _atomic_write_text(edges_path, edges_lines)
        _atomic_write_text(
            jsonld_path,
            canonical_json(dict(result.jsonld)) + "\n",
        )

        staged_snapshot = PublicLegalGraphSnapshot.from_dict(
            {
                **result.snapshot.to_dict(),
                "mode": BuildMode.STAGE.value,
                "staged_at_utc": "",  # non-content; keep empty for determinism
            }
        )
        _atomic_write_text(
            snapshot_path, staged_snapshot.to_canonical_json() + "\n"
        )

        receipt = validate_graph_build(result)
        _atomic_write_text(receipt_path, canonical_json(receipt) + "\n")
        _atomic_write_text(
            root_path,
            canonical_json(
                {
                    "corpus_root_cid": result.corpus_root_cid,
                    "graph_digest_sha256": result.graph_digest_sha256,
                    "graph_root_cid": result.graph_root_cid,
                    "graph_schema_version": GRAPH_SCHEMA_VERSION,
                    "schema_version": SCHEMA_VERSION,
                    "task_id": TASK_ID,
                }
            )
            + "\n",
        )

        return PublicLegalGraphBuild(
            nodes=result.nodes,
            edges=result.edges,
            jsonld=result.jsonld,
            snapshot=staged_snapshot,
            mode=BuildMode.STAGE,
            output_dir=str(out),
            corpus_root_cid=result.corpus_root_cid,
        )


# ---------------------------------------------------------------------------
# Load / validate / convenience
# ---------------------------------------------------------------------------


def load_snapshot(path: PathLike) -> PublicLegalGraphSnapshot:
    """Load a staged knowledge-graph snapshot receipt."""
    text = Path(path).read_text(encoding="utf-8")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise GraphSchemaValidationError(f"invalid snapshot JSON: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise GraphSchemaValidationError("snapshot JSON must be an object")
    return PublicLegalGraphSnapshot.from_dict(payload)


def validate_graph_build(result: PublicLegalGraphBuild) -> dict[str, Any]:
    """Validate invariants and return a content-stable build receipt."""
    gate = verify_graph_invariants(result.nodes, result.edges)
    # Recompute graph root and confirm pin match.
    nodes_payload = [n.to_dict() for n in result.nodes]
    edges_payload = [e.to_dict() for e in result.edges]
    identity_body = {
        "corpus_digest_sha256": result.snapshot.corpus_digest_sha256,
        "corpus_root_cid": result.snapshot.corpus_root_cid,
        "edges": edges_payload,
        "graph_schema_version": GRAPH_SCHEMA_VERSION,
        "nodes": nodes_payload,
        "schema_version": SCHEMA_VERSION,
    }
    expected_digest = content_digest_of(identity_body)
    expected_cid = content_cid_of(identity_body)
    if expected_digest != result.graph_digest_sha256:
        raise GraphIntegrityError("graph_digest_sha256 mismatch on validation")
    if expected_cid != result.graph_root_cid:
        raise GraphIntegrityError("graph_root_cid mismatch on validation")
    if result.snapshot.nodes_cid != content_cid_of(nodes_payload):
        raise GraphIntegrityError("nodes_cid mismatch on validation")
    if result.snapshot.edges_cid != content_cid_of(edges_payload):
        raise GraphIntegrityError("edges_cid mismatch on validation")
    if result.snapshot.jsonld_cid != content_cid_of(dict(result.jsonld)):
        raise GraphIntegrityError("jsonld_cid mismatch on validation")

    # Second build from the same snapshot corpus pins must match when rebuilt
    # externally; here we prove internal self-consistency.
    return {
        "authority_edges": gate["authority_edges"],
        "authority_span_check": "pass",
        "corpus_root_cid": result.corpus_root_cid,
        "document_count": result.snapshot.counts.documents,
        "edge_count": len(result.edges),
        "graph_digest_sha256": result.graph_digest_sha256,
        "graph_root_cid": result.graph_root_cid,
        "graph_schema_version": GRAPH_SCHEMA_VERSION,
        "node_count": len(result.nodes),
        "ok": True,
        "orphan_check": "pass",
        "schema_version": SCHEMA_VERSION,
        "stable": True,
        "task_id": TASK_ID,
    }


def builds_are_byte_identical(
    left: PublicLegalGraphBuild, right: PublicLegalGraphBuild
) -> bool:
    """Return True when two builds share identical content-address payloads."""
    return left.to_canonical_bytes() == right.to_canonical_bytes()


def build_public_legal_knowledge_graph(
    *,
    recipe: Mapping[str, Any] | None = None,
    materialization: PublicLegalCorpusMaterialization | None = None,
    require_all_families: bool = True,
    stage: bool = False,
    output_dir: PathLike | None = None,
) -> PublicLegalGraphBuild:
    """Convenience entrypoint used by ops scripts and tests."""
    builder = PublicLegalGraphBuilder()
    if materialization is not None:
        return builder.build_from_materialization(
            materialization, stage=stage, output_dir=output_dir
        )
    return builder.build_from_recipe(
        recipe,
        require_all_families=require_all_families,
        stage=stage,
        output_dir=output_dir,
    )


__all__ = [
    "AUTHORITY_RELATIONS",
    "CODE_VERSION",
    "CONFIG_ID",
    "EDGES_FILENAME",
    "GOAL_ID",
    "GRAPH_RELATIONS",
    "GRAPH_ROOT_FILENAME",
    "GRAPH_SCHEMA_VERSION",
    "INTERFACE",
    "JSONLD_FILENAME",
    "NODE_KINDS",
    "NODES_FILENAME",
    "PRODUCER",
    "RECEIPT_FILENAME",
    "SCHEMA_VERSION",
    "SNAPSHOT_FILENAME",
    "TASK_ID",
    "TENANT_PUBLIC",
    "BuildMode",
    "GraphIntegrityError",
    "GraphSchemaValidationError",
    "MissingAuthoritySpanError",
    "OrphanEdgeError",
    "PrivateGraphInputError",
    "PublicLegalGraphBuild",
    "PublicLegalGraphBuilder",
    "PublicLegalGraphCounts",
    "PublicLegalGraphError",
    "PublicLegalGraphNode",
    "PublicLegalGraphSnapshot",
    "build_jsonld_document",
    "build_public_legal_knowledge_graph",
    "builds_are_byte_identical",
    "canonical_json",
    "content_cid_of",
    "content_digest_of",
    "is_authority_edge",
    "load_snapshot",
    "project_public_legal_graph",
    "validate_graph_build",
    "verify_authority_edges_cite_spans",
    "verify_graph_invariants",
    "verify_no_orphan_edges",
]
