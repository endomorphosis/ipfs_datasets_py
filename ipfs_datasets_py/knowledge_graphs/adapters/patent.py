"""Deterministic patent-law and prosecution knowledge graph projection (PATLAW-091).

Projects verified patent authorities and public prosecution events into a
source-linked, disclosure-preserving graph:

* Entity kinds: authority, edition, section, amendment, effective_interval,
  family, application, publication, patent, claim, office_action, rejection,
  response, citation, classification, examiner, applicant, legal_authority.
* Provenance-bound edges for priority, continuation, amendment, rejection,
  examiner, applicant, and legal-authority relations (plus citations and
  claim dependency).
* LLM-proposed edges are admitted only as unverified candidates and may never
  claim source authority.
* Projection is pure and deterministic: same case input always yields the same
  sorted node/edge set and digest.
* Every node and source-derived edge joins to at least one source CID (and
  optional exact span). Edge endpoints are validated to exist.

This module is the projection adapter only. It does not perform network I/O,
embedding, or index builds (those belong to PATLAW-092+).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from hashlib import sha256
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final, Iterable, Mapping, Sequence

from ipfs_datasets_py.knowledge_graphs.core.graph_engine import GraphEngine
from ipfs_datasets_py.knowledge_graphs.migration.formats import (
    GraphData,
    NodeData,
    RelationshipData,
)
from ipfs_datasets_py.processors.domains.patent.retrieval_contracts import (
    RETRIEVAL_CONTRACTS_SCHEMA_VERSION,
    AuthorityClaim,
    DisclosureClass,
    EdgeKind,
    EdgeProvenance,
    GraphEdge,
    SourceLink,
    SourceSpan,
    assert_authority_claim_allowed,
    is_private_disclosure,
    requires_quarantine,
)

# ---------------------------------------------------------------------------
# Schema pins
# ---------------------------------------------------------------------------

PROJECTION_SCHEMA_VERSION: Final = "patent.graph.projection.v1"
CASE_SCHEMA_VERSION: Final = "patent.graph.case.v1"
NODE_SCHEMA: Final = "patent.graph.node@1"
ADAPTER_INTERFACE: Final = "PatentGraphProjection@1"

# Node kinds required by PATLAW-091 effects / acceptance.
NODE_KINDS: Final[frozenset[str]] = frozenset(
    {
        "authority",
        "edition",
        "section",
        "amendment",
        "effective_interval",
        "family",
        "application",
        "publication",
        "patent",
        "claim",
        "office_action",
        "rejection",
        "response",
        "citation",
        "classification",
        "examiner",
        "applicant",
        "legal_authority",
    }
)

# Canonical edge relation names used in case recipes and projection metadata.
# Relations that map onto retrieval_contracts.EdgeKind use that enum value as
# the GraphEngine relationship type; others use a stable UPPER_SNAKE name.
RELATION_TO_EDGE_KIND: Final[Mapping[str, EdgeKind]] = MappingProxyType(
    {
        "priority": EdgeKind.PRIORITY,
        "continuation": EdgeKind.CONTINUATION,
        "amends": EdgeKind.AMENDS,
        "amendment": EdgeKind.AMENDS,
        "rejects": EdgeKind.REJECTS,
        "rejection": EdgeKind.REJECTS,
        "responds_to": EdgeKind.RESPONDS_TO,
        "response": EdgeKind.RESPONDS_TO,
        "references_authority": EdgeKind.REFERENCES_AUTHORITY,
        "legal_authority": EdgeKind.REFERENCES_AUTHORITY,
        "cites": EdgeKind.CITES,
        "citation": EdgeKind.CITES,
        "classifies": EdgeKind.CLASSIFIES,
        "classification": EdgeKind.CLASSIFIES,
        "depends_on": EdgeKind.DEPENDS_ON,
        "supersedes": EdgeKind.SUPERSEDES,
        # Examiner / applicant are first-class disclosure-preserving edges but
        # are not in EdgeKind; they project as OTHER with explicit relation.
        "examiner": EdgeKind.OTHER,
        "examined_by": EdgeKind.OTHER,
        "has_examiner": EdgeKind.OTHER,
        "applicant": EdgeKind.OTHER,
        "filed_by": EdgeKind.OTHER,
        "has_applicant": EdgeKind.OTHER,
        "member_of": EdgeKind.OTHER,
        "has_claim": EdgeKind.OTHER,
        "has_document": EdgeKind.OTHER,
        "has_publication": EdgeKind.OTHER,
        "grants": EdgeKind.OTHER,
        "office_action": EdgeKind.OTHER,
        "effective_during": EdgeKind.OTHER,
        "in_edition": EdgeKind.OTHER,
        "has_section": EdgeKind.OTHER,
        "other": EdgeKind.OTHER,
    }
)

# Relations whose disclosure must be preserved (never upgraded to a more public
# class than either endpoint).
DISCLOSURE_SENSITIVE_RELATIONS: Final[frozenset[str]] = frozenset(
    {
        "priority",
        "continuation",
        "amends",
        "amendment",
        "rejects",
        "rejection",
        "examiner",
        "examined_by",
        "has_examiner",
        "applicant",
        "filed_by",
        "has_applicant",
        "legal_authority",
        "references_authority",
    }
)

_DISCLOSURE_RANK: Final[Mapping[DisclosureClass, int]] = MappingProxyType(
    {
        DisclosureClass.PUBLIC_OFFICIAL: 10,
        DisclosureClass.PUBLIC_USER: 20,
        DisclosureClass.RESTRICTED_EXPORT_REVIEW: 50,
        DisclosureClass.CONFIDENTIAL_APPLICATION: 60,
        DisclosureClass.PRIVILEGED_WORK_PRODUCT: 70,
        DisclosureClass.CREDENTIAL_OR_PAYMENT: 80,
        DisclosureClass.UNKNOWN: 100,
    }
)

_PUBLIC_DISCLOSURE_ALIASES: Final[Mapping[str, DisclosureClass]] = MappingProxyType(
    {
        "public_official": DisclosureClass.PUBLIC_OFFICIAL,
        "public_user": DisclosureClass.PUBLIC_USER,
        "confidential_application": DisclosureClass.CONFIDENTIAL_APPLICATION,
        "privileged_work_product": DisclosureClass.PRIVILEGED_WORK_PRODUCT,
        "restricted_export_review": DisclosureClass.RESTRICTED_EXPORT_REVIEW,
        "credential_or_payment": DisclosureClass.CREDENTIAL_OR_PAYMENT,
        "unknown": DisclosureClass.UNKNOWN,
        # Legacy / model aliases from public-patent models
        "public": DisclosureClass.PUBLIC_OFFICIAL,
        "official": DisclosureClass.PUBLIC_OFFICIAL,
    }
)

_LLM_PROVENANCE_MARKERS: Final[frozenset[str]] = frozenset(
    {
        "llm",
        "llm_proposed",
        "model",
        "model_candidate",
        "candidate",
        "generated",
        "inferred",
        "enrichment",
        "graphrag",
        "unverified",
    }
)


class PatentGraphAdapterError(ValueError):
    """Raised when a patent graph case or projection is invalid."""


class MissingEndpointError(PatentGraphAdapterError):
    """Raised when an edge references a node that was not projected."""


class MissingSourceLinkError(PatentGraphAdapterError):
    """Raised when a node or source-derived edge lacks source CID/span linkage."""


class DisclosureUpgradeError(PatentGraphAdapterError):
    """Raised when an edge would upgrade disclosure relative to its endpoints."""


class CandidateAuthorityError(PatentGraphAdapterError):
    """Raised when an LLM/candidate edge claims source authority."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def canonical_json(value: Any) -> str:
    """Deterministic compact JSON with sorted keys (stable across runs)."""
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def content_digest(value: Any) -> str:
    """Return a tagged SHA-256 of a canonical JSON value."""
    return f"sha256:{sha256(canonical_json(value).encode('utf-8')).hexdigest()}"


def _require_mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise PatentGraphAdapterError(
            f"{label} must be a mapping, got {type(value).__name__}"
        )
    return value


def _require_str(value: Any, field: str, *, max_len: int = 4096) -> str:
    if not isinstance(value, str):
        raise PatentGraphAdapterError(
            f"{field} must be str, got {type(value).__name__}"
        )
    text = value.strip()
    if not text:
        raise PatentGraphAdapterError(f"{field} must be non-empty")
    if len(text) > max_len:
        raise PatentGraphAdapterError(f"{field} exceeds max length {max_len}")
    return text


def _optional_str(value: Any, field: str, *, max_len: int = 4096) -> str | None:
    if value is None:
        return None
    return _require_str(value, field, max_len=max_len)


def _coerce_disclosure(value: Any) -> DisclosureClass:
    if isinstance(value, DisclosureClass):
        return value
    if isinstance(value, Enum) and hasattr(value, "value"):
        value = value.value
    if not isinstance(value, str):
        raise PatentGraphAdapterError(
            f"disclosure must be str or DisclosureClass, got {type(value).__name__}"
        )
    key = value.strip().lower().replace("-", "_").replace(" ", "_")
    if key in _PUBLIC_DISCLOSURE_ALIASES:
        return _PUBLIC_DISCLOSURE_ALIASES[key]
    try:
        return DisclosureClass(value.strip())
    except ValueError as exc:
        raise PatentGraphAdapterError(
            f"unknown disclosure classification: {value!r}"
        ) from exc


def _more_restrictive_disclosure(
    left: DisclosureClass, right: DisclosureClass
) -> DisclosureClass:
    """Return the more restrictive (higher rank) of two disclosure classes."""
    if _DISCLOSURE_RANK[left] >= _DISCLOSURE_RANK[right]:
        return left
    return right


def _parse_source_link(raw: Any, *, field: str) -> SourceLink:
    if isinstance(raw, SourceLink):
        return raw
    raw = _require_mapping(raw, field)
    span_raw = raw.get("span")
    span: SourceSpan | None
    if span_raw is None:
        span = None
    elif isinstance(span_raw, SourceSpan):
        span = span_raw
    elif isinstance(span_raw, Mapping):
        span = SourceSpan.from_dict(span_raw)
    else:
        raise PatentGraphAdapterError(f"{field}.span must be a mapping or null")
    try:
        return SourceLink(
            source_cid=raw.get("source_cid", ""),
            artifact_id=raw.get("artifact_id", ""),
            span=span,
            source_receipt_id=raw.get("source_receipt_id"),
            authority_tier=raw.get("authority_tier"),
        )
    except (TypeError, ValueError) as exc:
        raise PatentGraphAdapterError(f"invalid source link at {field}: {exc}") from exc


def _parse_source_links(
    raw: Any, *, field: str, require_nonempty: bool = True
) -> tuple[SourceLink, ...]:
    if raw is None:
        links: list[SourceLink] = []
    elif isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)):
        links = [
            _parse_source_link(item, field=f"{field}[{i}]")
            for i, item in enumerate(raw)
        ]
    else:
        raise PatentGraphAdapterError(f"{field} must be a sequence of source links")
    if require_nonempty and not links:
        raise MissingSourceLinkError(f"{field} must contain at least one source link")
    # Stable order by (source_cid, artifact_id, span start/end)
    links_sorted = sorted(
        links,
        key=lambda link: (
            link.source_cid,
            link.artifact_id,
            -1 if link.span is None else link.span.start,
            -1 if link.span is None else link.span.end,
            link.span.unit if link.span is not None else "",
        ),
    )
    return tuple(links_sorted)


def _normalize_relation(value: Any) -> str:
    text = _require_str(value, "relation", max_len=64).lower().replace("-", "_")
    text = text.replace(" ", "_")
    if text not in RELATION_TO_EDGE_KIND:
        raise PatentGraphAdapterError(
            f"unsupported edge relation {text!r}; known: "
            f"{', '.join(sorted(RELATION_TO_EDGE_KIND))}"
        )
    return text


def _edge_kind_for(relation: str) -> EdgeKind:
    return RELATION_TO_EDGE_KIND[relation]


def _relationship_type(relation: str, kind: EdgeKind) -> str:
    """GraphEngine relationship type: EdgeKind value or stable relation name."""
    if kind is EdgeKind.OTHER:
        return relation.upper()
    return kind.value.upper()


def _is_llm_or_candidate_provenance(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, EdgeProvenance):
        return value is EdgeProvenance.CANDIDATE
    text = str(value).strip().lower().replace("-", "_").replace(" ", "_")
    return text in _LLM_PROVENANCE_MARKERS


def _coerce_edge_provenance(
    raw: Any, *, is_candidate_channel: bool
) -> EdgeProvenance:
    if is_candidate_channel or _is_llm_or_candidate_provenance(raw):
        return EdgeProvenance.CANDIDATE
    if raw is None or raw == "" or raw is EdgeProvenance.SOURCE_DERIVED:
        return EdgeProvenance.SOURCE_DERIVED
    if isinstance(raw, EdgeProvenance):
        if raw is EdgeProvenance.GENERATED_SUMMARY:
            # Generated summaries are not edges; treat as non-source candidate.
            return EdgeProvenance.CANDIDATE
        return raw
    text = str(raw).strip().lower().replace("-", "_")
    if text in {"source", "source_derived", "derived", "official", "verified"}:
        return EdgeProvenance.SOURCE_DERIVED
    if text in {"generated_summary", "summary"}:
        return EdgeProvenance.CANDIDATE
    if text in _LLM_PROVENANCE_MARKERS:
        return EdgeProvenance.CANDIDATE
    raise PatentGraphAdapterError(f"unsupported edge provenance: {raw!r}")


def _stable_node_id(entity_id: str, kind: str) -> str:
    """Return a deterministic, identifier-safe node id."""
    entity_id = _require_str(entity_id, "entity_id", max_len=256)
    kind = _require_str(kind, "kind", max_len=64)
    # Prefer caller-provided ids that already look like graph node ids.
    if entity_id.startswith("node:"):
        return entity_id
    # Keep colon/slash-safe public-patent style ids readable.
    safe = entity_id.replace(" ", "_")
    return f"node:{kind}:{safe}"


def _stable_edge_id(
    *,
    relation: str,
    subject_id: str,
    object_id: str,
    provenance: EdgeProvenance,
    source_links: Sequence[SourceLink],
    metadata: Mapping[str, str],
) -> str:
    payload = {
        "metadata": dict(metadata),
        "object_id": object_id,
        "provenance": provenance.value,
        "relation": relation,
        "source_links": [link.to_dict() for link in source_links],
        "subject_id": subject_id,
    }
    digest = sha256(canonical_json(payload).encode("utf-8")).hexdigest()[:24]
    return f"edge:{relation}:{digest}"


# ---------------------------------------------------------------------------
# Projection records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PatentGraphNode:
    """Source-linked projected graph node for patent/prosecution ontology."""

    node_id: str
    kind: str
    label: str
    source_links: tuple[SourceLink, ...]
    disclosure: DisclosureClass
    tenant_id: str
    properties: Mapping[str, str] = MappingProxyType({})
    effective_from_utc: str | None = None
    effective_to_utc: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "node_id", _require_str(self.node_id, "node_id", max_len=256)
        )
        kind = _require_str(self.kind, "kind", max_len=64).lower().replace("-", "_")
        if kind not in NODE_KINDS:
            raise PatentGraphAdapterError(
                f"unknown node kind {kind!r}; known: {', '.join(sorted(NODE_KINDS))}"
            )
        object.__setattr__(self, "kind", kind)
        object.__setattr__(
            self, "label", _require_str(self.label, "label", max_len=2048)
        )
        links = _parse_source_links(
            self.source_links, field="source_links", require_nonempty=True
        )
        object.__setattr__(self, "source_links", links)
        disclosure = _coerce_disclosure(self.disclosure)
        if requires_quarantine(disclosure):
            raise PatentGraphAdapterError(
                f"node {self.node_id!r} has unknown disclosure; quarantine required"
            )
        object.__setattr__(self, "disclosure", disclosure)
        object.__setattr__(
            self, "tenant_id", _require_str(self.tenant_id, "tenant_id", max_len=128)
        )
        props: dict[str, str] = {}
        if self.properties is None:
            pass
        elif isinstance(self.properties, Mapping):
            for key, value in self.properties.items():
                k = _require_str(key, "properties.key", max_len=128)
                props[k] = _require_str(value, f"properties[{k}]", max_len=8192)
        else:
            raise PatentGraphAdapterError("properties must be a mapping")
        object.__setattr__(
            self, "properties", MappingProxyType(dict(sorted(props.items())))
        )
        object.__setattr__(
            self,
            "effective_from_utc",
            _optional_str(self.effective_from_utc, "effective_from_utc", max_len=64),
        )
        object.__setattr__(
            self,
            "effective_to_utc",
            _optional_str(self.effective_to_utc, "effective_to_utc", max_len=64),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "disclosure": self.disclosure.value,
            "effective_from_utc": self.effective_from_utc,
            "effective_to_utc": self.effective_to_utc,
            "kind": self.kind,
            "label": self.label,
            "node_id": self.node_id,
            "properties": dict(self.properties),
            "schema": NODE_SCHEMA,
            "source_links": [link.to_dict() for link in self.source_links],
            "tenant_id": self.tenant_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "PatentGraphNode":
        value = _require_mapping(value, "PatentGraphNode")
        return cls(
            node_id=value.get("node_id", ""),
            kind=value.get("kind", ""),
            label=value.get("label", ""),
            source_links=tuple(value.get("source_links") or ()),
            disclosure=value.get("disclosure", DisclosureClass.UNKNOWN.value),
            tenant_id=value.get("tenant_id", ""),
            properties=value.get("properties") or {},
            effective_from_utc=value.get("effective_from_utc"),
            effective_to_utc=value.get("effective_to_utc"),
        )


@dataclass(frozen=True, slots=True)
class PatentGraphProjection:
    """Immutable, deterministic projection result."""

    schema_version: str
    case_id: str
    tenant_id: str
    nodes: tuple[PatentGraphNode, ...]
    edges: tuple[GraphEdge, ...]
    projection_digest: str
    candidate_edge_ids: tuple[str, ...] = ()
    metadata: Mapping[str, str] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _require_str(self.schema_version, "schema_version", max_len=64),
        )
        if self.schema_version != PROJECTION_SCHEMA_VERSION:
            raise PatentGraphAdapterError(
                f"schema_version must be {PROJECTION_SCHEMA_VERSION}, "
                f"got {self.schema_version!r}"
            )
        object.__setattr__(
            self, "case_id", _require_str(self.case_id, "case_id", max_len=256)
        )
        object.__setattr__(
            self, "tenant_id", _require_str(self.tenant_id, "tenant_id", max_len=128)
        )
        if not isinstance(self.nodes, Sequence) or isinstance(
            self.nodes, (str, bytes)
        ):
            raise PatentGraphAdapterError("nodes must be a sequence")
        if not isinstance(self.edges, Sequence) or isinstance(
            self.edges, (str, bytes)
        ):
            raise PatentGraphAdapterError("edges must be a sequence")
        node_ids = {n.node_id for n in self.nodes}
        if len(node_ids) != len(self.nodes):
            raise PatentGraphAdapterError("duplicate node_id in projection")
        for edge in self.edges:
            if not isinstance(edge, GraphEdge):
                raise PatentGraphAdapterError("edges must be GraphEdge instances")
            if edge.subject_id not in node_ids:
                raise MissingEndpointError(
                    f"edge {edge.edge_id!r} subject {edge.subject_id!r} missing"
                )
            if edge.object_id not in node_ids:
                raise MissingEndpointError(
                    f"edge {edge.edge_id!r} object {edge.object_id!r} missing"
                )
        object.__setattr__(
            self,
            "projection_digest",
            _require_str(self.projection_digest, "projection_digest", max_len=80),
        )
        object.__setattr__(
            self,
            "candidate_edge_ids",
            tuple(
                _require_str(x, f"candidate_edge_ids[{i}]", max_len=256)
                for i, x in enumerate(self.candidate_edge_ids or ())
            ),
        )
        meta: dict[str, str] = {}
        if self.metadata:
            for key, value in self.metadata.items():
                k = _require_str(key, "metadata.key", max_len=128)
                meta[k] = _require_str(value, f"metadata[{k}]", max_len=2048)
        object.__setattr__(
            self, "metadata", MappingProxyType(dict(sorted(meta.items())))
        )

    def node_by_id(self) -> Mapping[str, PatentGraphNode]:
        return {node.node_id: node for node in self.nodes}

    def source_derived_edges(self) -> tuple[GraphEdge, ...]:
        return tuple(
            e for e in self.edges if e.provenance is EdgeProvenance.SOURCE_DERIVED
        )

    def candidate_edges(self) -> tuple[GraphEdge, ...]:
        return tuple(
            e for e in self.edges if e.provenance is EdgeProvenance.CANDIDATE
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_edge_ids": list(self.candidate_edge_ids),
            "case_id": self.case_id,
            "edges": [edge.to_dict() for edge in self.edges],
            "metadata": dict(self.metadata),
            "nodes": [node.to_dict() for node in self.nodes],
            "projection_digest": self.projection_digest,
            "schema_version": self.schema_version,
            "tenant_id": self.tenant_id,
        }

    def to_graph_data(self) -> GraphData:
        """Convert to migration ``GraphData`` for GraphEngine import."""
        nodes: list[NodeData] = []
        for node in self.nodes:
            props: dict[str, Any] = {
                "kind": node.kind,
                "label": node.label,
                "disclosure": node.disclosure.value,
                "tenant_id": node.tenant_id,
                "source_links": [link.to_dict() for link in node.source_links],
                "source_cid": node.source_links[0].source_cid,
            }
            if node.effective_from_utc is not None:
                props["effective_from_utc"] = node.effective_from_utc
            if node.effective_to_utc is not None:
                props["effective_to_utc"] = node.effective_to_utc
            props.update(dict(node.properties))
            nodes.append(
                NodeData(
                    id=node.node_id,
                    labels=[node.kind, "PatentGraphNode"],
                    properties=props,
                )
            )
        relationships: list[RelationshipData] = []
        for edge in self.edges:
            relation = edge.metadata.get("relation", edge.kind.value)
            rel_type = _relationship_type(relation, edge.kind)
            props: dict[str, Any] = {
                "authority_claim": edge.authority_claim.value,
                "disclosure": edge.disclosure.value,
                "edge_id": edge.edge_id,
                "kind": edge.kind.value,
                "provenance": edge.provenance.value,
                "relation": relation,
                "source_links": [link.to_dict() for link in edge.source_links],
                "tenant_id": edge.tenant_id,
                "weight": edge.weight,
                "verified": edge.provenance is EdgeProvenance.SOURCE_DERIVED
                and edge.authority_claim is AuthorityClaim.SOURCE_BOUND,
            }
            if edge.source_links:
                props["source_cid"] = edge.source_links[0].source_cid
            if edge.effective_from_utc is not None:
                props["effective_from_utc"] = edge.effective_from_utc
            if edge.effective_to_utc is not None:
                props["effective_to_utc"] = edge.effective_to_utc
            for key, value in edge.metadata.items():
                if key not in props:
                    props[key] = value
            relationships.append(
                RelationshipData(
                    id=edge.edge_id,
                    type=rel_type,
                    start_node=edge.subject_id,
                    end_node=edge.object_id,
                    properties=props,
                )
            )
        # Deterministic order already enforced on projection.
        return GraphData(nodes=list(nodes), relationships=list(relationships))

    def load_into_engine(
        self,
        engine: GraphEngine | None = None,
        *,
        preserve_ids: bool = True,
    ) -> tuple[GraphEngine, dict[str, int]]:
        """Import this projection into a GraphEngine (creating one if needed)."""
        if engine is None:
            engine = GraphEngine()
        report = engine.import_graph_data(
            self.to_graph_data(),
            preserve_ids=preserve_ids,
            skip_duplicates=True,
        )
        return engine, report


# ---------------------------------------------------------------------------
# Projector
# ---------------------------------------------------------------------------


class PatentGraphProjector:
    """Deterministic projector from a prosecution case recipe to a graph.

    Case recipe shape (``CASE_SCHEMA_VERSION``)::

        {
          "schema_version": "patent.graph.case.v1",
          "case_id": "...",
          "tenant_id": "tenant-public",
          "entities": [
            {
              "id": "app-1",
              "kind": "application",
              "label": "16/123,456",
              "disclosure": "public_official",
              "source_links": [{"source_cid": "...", "artifact_id": "...",
                               "span": {"start": 0, "end": 10}}],
              "properties": {...}
            }
          ],
          "edges": [
            {
              "subject": "app-1",
              "object": "parent-1",
              "relation": "priority",
              "source_links": [...],
              "provenance": "source_derived"   # optional
            }
          ],
          "candidate_edges": [
            {
              "subject": "claim-1",
              "object": "citation-x",
              "relation": "cites",
              "provenance": "llm_proposed"
            }
          ]
        }
    """

    def __init__(self, *, default_tenant_id: str = "tenant-public") -> None:
        self.default_tenant_id = _require_str(
            default_tenant_id, "default_tenant_id", max_len=128
        )

    def project(self, case: Mapping[str, Any]) -> PatentGraphProjection:
        """Project *case* into a deterministic ``PatentGraphProjection``."""
        case = _require_mapping(case, "case")
        schema = _optional_str(case.get("schema_version"), "schema_version")
        if schema is not None and schema != CASE_SCHEMA_VERSION:
            raise PatentGraphAdapterError(
                f"case schema_version must be {CASE_SCHEMA_VERSION}, got {schema!r}"
            )
        case_id = _require_str(case.get("case_id", ""), "case_id", max_len=256)
        tenant_id = _optional_str(case.get("tenant_id"), "tenant_id", max_len=128)
        if tenant_id is None:
            tenant_id = self.default_tenant_id

        entities_raw = case.get("entities") or ()
        if not isinstance(entities_raw, Sequence) or isinstance(
            entities_raw, (str, bytes)
        ):
            raise PatentGraphAdapterError("entities must be a sequence")
        if not entities_raw:
            raise PatentGraphAdapterError("entities must be non-empty")

        nodes_by_local: dict[str, PatentGraphNode] = {}
        for i, raw in enumerate(entities_raw):
            node = self._project_entity(
                raw, tenant_id=tenant_id, field=f"entities[{i}]"
            )
            local_id = _require_str(
                _require_mapping(raw, f"entities[{i}]").get("id", ""),
                f"entities[{i}].id",
                max_len=256,
            )
            if local_id in nodes_by_local:
                raise PatentGraphAdapterError(
                    f"duplicate entity id {local_id!r} in case {case_id!r}"
                )
            # Also index by projected node_id for edges that reference either form.
            nodes_by_local[local_id] = node
            nodes_by_local[node.node_id] = node

        # Deduplicate projected nodes by node_id while preserving insertion order
        # of first-seen entity.
        seen_node_ids: set[str] = set()
        ordered_nodes: list[PatentGraphNode] = []
        for i, raw in enumerate(entities_raw):
            local_id = _require_str(
                _require_mapping(raw, f"entities[{i}]").get("id", ""),
                f"entities[{i}].id",
                max_len=256,
            )
            node = nodes_by_local[local_id]
            if node.node_id in seen_node_ids:
                continue
            seen_node_ids.add(node.node_id)
            ordered_nodes.append(node)

        edges: list[GraphEdge] = []
        candidate_ids: list[str] = []

        for i, raw in enumerate(case.get("edges") or ()):
            edge = self._project_edge(
                raw,
                nodes_by_local=nodes_by_local,
                tenant_id=tenant_id,
                is_candidate_channel=False,
                field=f"edges[{i}]",
            )
            edges.append(edge)

        for i, raw in enumerate(case.get("candidate_edges") or ()):
            edge = self._project_edge(
                raw,
                nodes_by_local=nodes_by_local,
                tenant_id=tenant_id,
                is_candidate_channel=True,
                field=f"candidate_edges[{i}]",
            )
            edges.append(edge)
            candidate_ids.append(edge.edge_id)

        # Deterministic sort: nodes by node_id, edges by edge_id.
        ordered_nodes.sort(key=lambda n: n.node_id)
        edges.sort(key=lambda e: e.edge_id)
        candidate_ids = sorted(set(candidate_ids))

        # Final endpoint existence check (also enforced in PatentGraphProjection).
        node_ids = {n.node_id for n in ordered_nodes}
        for edge in edges:
            if edge.subject_id not in node_ids or edge.object_id not in node_ids:
                raise MissingEndpointError(
                    f"edge {edge.edge_id!r} endpoints not fully projected"
                )
            # Every source-derived edge must retain source links.
            if (
                edge.provenance is EdgeProvenance.SOURCE_DERIVED
                and not edge.source_links
            ):
                raise MissingSourceLinkError(
                    f"source-derived edge {edge.edge_id!r} missing source links"
                )
            # Candidates never claim source authority.
            if edge.provenance is EdgeProvenance.CANDIDATE:
                if edge.authority_claim is AuthorityClaim.SOURCE_BOUND:
                    raise CandidateAuthorityError(
                        f"candidate edge {edge.edge_id!r} claims source authority"
                    )

        meta_raw = case.get("metadata") or {}
        metadata: dict[str, str] = {}
        if isinstance(meta_raw, Mapping):
            for key, value in meta_raw.items():
                metadata[str(key)] = str(value)

        body = {
            "candidate_edge_ids": candidate_ids,
            "case_id": case_id,
            "edges": [e.to_dict() for e in edges],
            "metadata": metadata,
            "nodes": [n.to_dict() for n in ordered_nodes],
            "schema_version": PROJECTION_SCHEMA_VERSION,
            "tenant_id": tenant_id,
        }
        digest = content_digest(body)
        return PatentGraphProjection(
            schema_version=PROJECTION_SCHEMA_VERSION,
            case_id=case_id,
            tenant_id=tenant_id,
            nodes=tuple(ordered_nodes),
            edges=tuple(edges),
            projection_digest=digest,
            candidate_edge_ids=tuple(candidate_ids),
            metadata=metadata,
        )

    def _project_entity(
        self,
        raw: Any,
        *,
        tenant_id: str,
        field: str,
    ) -> PatentGraphNode:
        raw = _require_mapping(raw, field)
        local_id = _require_str(raw.get("id", ""), f"{field}.id", max_len=256)
        kind = _require_str(raw.get("kind", ""), f"{field}.kind", max_len=64)
        kind = kind.lower().replace("-", "_")
        if kind not in NODE_KINDS:
            raise PatentGraphAdapterError(
                f"{field}.kind unknown {kind!r}; known: "
                f"{', '.join(sorted(NODE_KINDS))}"
            )
        label = _optional_str(raw.get("label"), f"{field}.label", max_len=2048)
        if label is None:
            label = local_id
        disclosure = _coerce_disclosure(
            raw.get("disclosure", DisclosureClass.PUBLIC_OFFICIAL.value)
        )
        if requires_quarantine(disclosure):
            raise PatentGraphAdapterError(
                f"{field} has unknown disclosure; quarantine required before projection"
            )
        entity_tenant = _optional_str(
            raw.get("tenant_id"), f"{field}.tenant_id", max_len=128
        )
        source_links = _parse_source_links(
            raw.get("source_links"),
            field=f"{field}.source_links",
            require_nonempty=True,
        )
        props_raw = raw.get("properties") or {}
        properties: dict[str, str] = {}
        if isinstance(props_raw, Mapping):
            for key, value in props_raw.items():
                properties[str(key)] = str(value)
        # Carry common identity fields into properties when present.
        for key in (
            "application_number",
            "patent_number",
            "publication_number",
            "claim_number",
            "section",
            "edition",
            "cpc",
            "ipc",
            "event_code",
            "basis",
            "citation_kind",
            "cited_id",
        ):
            if key in raw and raw[key] is not None and key not in properties:
                properties[key] = str(raw[key])

        return PatentGraphNode(
            node_id=_stable_node_id(local_id, kind),
            kind=kind,
            label=label,
            source_links=source_links,
            disclosure=disclosure,
            tenant_id=entity_tenant or tenant_id,
            properties=properties,
            effective_from_utc=raw.get("effective_from_utc"),
            effective_to_utc=raw.get("effective_to_utc"),
        )

    def _resolve_node_id(
        self,
        ref: Any,
        *,
        nodes_by_local: Mapping[str, PatentGraphNode],
        field: str,
    ) -> str:
        text = _require_str(ref, field, max_len=256)
        if text in nodes_by_local:
            return nodes_by_local[text].node_id
        # Allow full node ids that already match projected nodes.
        if text.startswith("node:") and text in {
            n.node_id for n in nodes_by_local.values()
        }:
            return text
        raise MissingEndpointError(f"{field} references unknown entity {text!r}")

    def _project_edge(
        self,
        raw: Any,
        *,
        nodes_by_local: Mapping[str, PatentGraphNode],
        tenant_id: str,
        is_candidate_channel: bool,
        field: str,
    ) -> GraphEdge:
        raw = _require_mapping(raw, field)
        subject_id = self._resolve_node_id(
            raw.get("subject") or raw.get("subject_id") or raw.get("from"),
            nodes_by_local=nodes_by_local,
            field=f"{field}.subject",
        )
        object_id = self._resolve_node_id(
            raw.get("object") or raw.get("object_id") or raw.get("to"),
            nodes_by_local=nodes_by_local,
            field=f"{field}.object",
        )
        relation = _normalize_relation(
            raw.get("relation") or raw.get("kind") or raw.get("type") or "other"
        )
        kind = _edge_kind_for(relation)
        provenance = _coerce_edge_provenance(
            raw.get("provenance"), is_candidate_channel=is_candidate_channel
        )

        subject = nodes_by_local[subject_id] if subject_id in nodes_by_local else None
        if subject is None:
            # Map by projected id
            for node in nodes_by_local.values():
                if node.node_id == subject_id:
                    subject = node
                    break
        object_node = nodes_by_local[object_id] if object_id in nodes_by_local else None
        if object_node is None:
            for node in nodes_by_local.values():
                if node.node_id == object_id:
                    object_node = node
                    break
        if subject is None or object_node is None:
            raise MissingEndpointError(f"{field} endpoints not fully resolved")

        # Disclosure: never upgrade above either endpoint for sensitive relations;
        # always take the more restrictive of endpoints + declared edge disclosure.
        declared = raw.get("disclosure")
        if declared is None:
            edge_disclosure = _more_restrictive_disclosure(
                subject.disclosure, object_node.disclosure
            )
        else:
            edge_disclosure = _coerce_disclosure(declared)
            endpoint_floor = _more_restrictive_disclosure(
                subject.disclosure, object_node.disclosure
            )
            if (
                relation in DISCLOSURE_SENSITIVE_RELATIONS
                and _DISCLOSURE_RANK[edge_disclosure] < _DISCLOSURE_RANK[endpoint_floor]
            ):
                raise DisclosureUpgradeError(
                    f"{field} disclosure {edge_disclosure.value!r} upgrades "
                    f"endpoint floor {endpoint_floor.value!r} for relation {relation!r}"
                )
            # Always clamp to at least as restrictive as endpoints.
            edge_disclosure = _more_restrictive_disclosure(
                edge_disclosure, endpoint_floor
            )

        if requires_quarantine(edge_disclosure):
            raise PatentGraphAdapterError(
                f"{field} has unknown disclosure; quarantine required"
            )

        # Source links: required for source-derived; optional for candidates.
        if provenance is EdgeProvenance.SOURCE_DERIVED:
            source_links = _parse_source_links(
                raw.get("source_links"),
                field=f"{field}.source_links",
                require_nonempty=True,
            )
            authority_claim = AuthorityClaim.SOURCE_BOUND
            if raw.get("authority_claim") is not None:
                try:
                    authority_claim = assert_authority_claim_allowed(
                        provenance, raw.get("authority_claim")
                    )
                except Exception as exc:  # SourceAuthorityClaimError inherits ValueError
                    raise CandidateAuthorityError(str(exc)) from exc
        else:
            source_links = _parse_source_links(
                raw.get("source_links") or (),
                field=f"{field}.source_links",
                require_nonempty=False,
            )
            # LLM-proposed / candidate edges remain unverified.
            authority_claim = AuthorityClaim.REVIEW_ONLY
            if raw.get("authority_claim") is not None:
                try:
                    authority_claim = assert_authority_claim_allowed(
                        provenance, raw.get("authority_claim")
                    )
                except Exception as exc:
                    raise CandidateAuthorityError(str(exc)) from exc
            if authority_claim is AuthorityClaim.SOURCE_BOUND:
                raise CandidateAuthorityError(
                    f"{field}: candidate/LLM edges cannot claim source authority"
                )

        meta: dict[str, str] = {"relation": relation}
        props_raw = raw.get("metadata") or raw.get("properties") or {}
        if isinstance(props_raw, Mapping):
            for key, value in props_raw.items():
                meta[str(key)] = str(value)
        if provenance is EdgeProvenance.CANDIDATE:
            meta.setdefault("verification_status", "unverified")
            meta.setdefault("candidate", "true")

        edge_tenant = _optional_str(
            raw.get("tenant_id"), f"{field}.tenant_id", max_len=128
        )
        weight = raw.get("weight", 1.0)
        try:
            weight_f = float(weight)
        except (TypeError, ValueError) as exc:
            raise PatentGraphAdapterError(f"{field}.weight must be a number") from exc

        edge_id_raw = _optional_str(raw.get("edge_id") or raw.get("id"), f"{field}.id")
        if edge_id_raw is None:
            edge_id = _stable_edge_id(
                relation=relation,
                subject_id=subject_id,
                object_id=object_id,
                provenance=provenance,
                source_links=source_links,
                metadata=meta,
            )
        else:
            edge_id = edge_id_raw

        try:
            return GraphEdge(
                schema_version=RETRIEVAL_CONTRACTS_SCHEMA_VERSION,
                edge_id=edge_id,
                subject_id=subject_id,
                object_id=object_id,
                kind=kind,
                provenance=provenance,
                authority_claim=authority_claim,
                source_links=source_links,
                disclosure=edge_disclosure,
                tenant_id=edge_tenant or tenant_id,
                weight=weight_f,
                effective_from_utc=raw.get("effective_from_utc"),
                effective_to_utc=raw.get("effective_to_utc"),
                metadata=meta,
            )
        except Exception as exc:
            raise PatentGraphAdapterError(f"{field}: invalid GraphEdge: {exc}") from exc


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def project_patent_graph(
    case: Mapping[str, Any],
    *,
    default_tenant_id: str = "tenant-public",
) -> PatentGraphProjection:
    """Project a prosecution case mapping into a deterministic graph."""
    return PatentGraphProjector(default_tenant_id=default_tenant_id).project(case)


def project_patent_graph_from_path(
    path: str | Path,
    *,
    default_tenant_id: str = "tenant-public",
) -> PatentGraphProjection:
    """Load a JSON case recipe from *path* and project it."""
    case_path = Path(path)
    try:
        payload = json.loads(case_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise PatentGraphAdapterError(f"failed to read case file: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise PatentGraphAdapterError(f"invalid case JSON: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise PatentGraphAdapterError("case file root must be a JSON object")
    # Golden fixtures may wrap the case under a "case" key with expected outputs.
    if "entities" not in payload and isinstance(payload.get("case"), Mapping):
        payload = payload["case"]
    return project_patent_graph(payload, default_tenant_id=default_tenant_id)


def load_golden_prosecution_case(
    path: str | Path | None = None,
) -> Mapping[str, Any]:
    """Load the golden prosecution case fixture (recipe + optional expected)."""
    if path is None:
        # tests/fixtures/patent/graph/golden_prosecution_case.json relative to repo
        repo_root = Path(__file__).resolve().parents[3]
        path = (
            repo_root
            / "tests"
            / "fixtures"
            / "patent"
            / "graph"
            / "golden_prosecution_case.json"
        )
    case_path = Path(path)
    payload = json.loads(case_path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise PatentGraphAdapterError("golden fixture root must be a JSON object")
    return payload


def project_golden_prosecution_case(
    path: str | Path | None = None,
) -> PatentGraphProjection:
    """Project the golden prosecution case fixture."""
    payload = load_golden_prosecution_case(path)
    case = payload.get("case", payload)
    if not isinstance(case, Mapping):
        raise PatentGraphAdapterError("golden fixture case must be a mapping")
    return project_patent_graph(case)


def assert_projection_invariants(projection: PatentGraphProjection) -> None:
    """Fail closed if projection violates PATLAW-091 acceptance rules."""
    if not projection.nodes:
        raise PatentGraphAdapterError("projection has no nodes")
    node_ids = {n.node_id for n in projection.nodes}
    for node in projection.nodes:
        if not node.source_links:
            raise MissingSourceLinkError(
                f"node {node.node_id!r} missing source CID/span linkage"
            )
        for link in node.source_links:
            if not link.source_cid:
                raise MissingSourceLinkError(
                    f"node {node.node_id!r} source link missing source_cid"
                )
    for edge in projection.edges:
        if edge.subject_id not in node_ids or edge.object_id not in node_ids:
            raise MissingEndpointError(
                f"edge {edge.edge_id!r} endpoints not both present"
            )
        if edge.provenance is EdgeProvenance.SOURCE_DERIVED:
            if not edge.source_links:
                raise MissingSourceLinkError(
                    f"source-derived edge {edge.edge_id!r} missing source links"
                )
            for link in edge.source_links:
                if not link.source_cid:
                    raise MissingSourceLinkError(
                        f"edge {edge.edge_id!r} source link missing source_cid"
                    )
        if edge.provenance is EdgeProvenance.CANDIDATE:
            if edge.authority_claim is AuthorityClaim.SOURCE_BOUND:
                raise CandidateAuthorityError(
                    f"candidate edge {edge.edge_id!r} claims source authority"
                )
            status = edge.metadata.get("verification_status", "unverified")
            if status not in {"unverified", "candidate", "review_only"}:
                raise CandidateAuthorityError(
                    f"candidate edge {edge.edge_id!r} has unexpected "
                    f"verification_status={status!r}"
                )
    # Digest recomputation
    body = {
        "candidate_edge_ids": list(projection.candidate_edge_ids),
        "case_id": projection.case_id,
        "edges": [e.to_dict() for e in projection.edges],
        "metadata": dict(projection.metadata),
        "nodes": [n.to_dict() for n in projection.nodes],
        "schema_version": projection.schema_version,
        "tenant_id": projection.tenant_id,
    }
    expected = content_digest(body)
    if expected != projection.projection_digest:
        raise PatentGraphAdapterError(
            "projection_digest does not match canonical body"
        )


def ontology_node_kinds() -> frozenset[str]:
    """Return the frozen set of patent/prosecution node kinds."""
    return NODE_KINDS


def ontology_relations() -> frozenset[str]:
    """Return the frozen set of supported edge relation names."""
    return frozenset(RELATION_TO_EDGE_KIND.keys())


__all__ = [
    "ADAPTER_INTERFACE",
    "CASE_SCHEMA_VERSION",
    "DISCLOSURE_SENSITIVE_RELATIONS",
    "NODE_KINDS",
    "NODE_SCHEMA",
    "PROJECTION_SCHEMA_VERSION",
    "RELATION_TO_EDGE_KIND",
    "CandidateAuthorityError",
    "DisclosureUpgradeError",
    "MissingEndpointError",
    "MissingSourceLinkError",
    "PatentGraphAdapterError",
    "PatentGraphNode",
    "PatentGraphProjection",
    "PatentGraphProjector",
    "assert_projection_invariants",
    "canonical_json",
    "content_digest",
    "load_golden_prosecution_case",
    "ontology_node_kinds",
    "ontology_relations",
    "project_golden_prosecution_case",
    "project_patent_graph",
    "project_patent_graph_from_path",
]
