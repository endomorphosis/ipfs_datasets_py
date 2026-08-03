"""Explainable hybrid retrieval over persistent BM25 / vector / graph indexes.

PATLAW-147 production fusion layer (v2). Builds on v1 family scorers and
contracts while adding:

* Per-component score contributions (BM25, dense vector, graph, CPC, IPC,
  citation, family-path signals)
* Exact source spans on every ranked hit
* Snapshot / model / config identity binding on every result
* Mandatory tenant / disclosure / as-of filters before any scorer
* Private-route remote isolation (zero remote embedding calls on denial)

Generated graph edges and candidate summaries never claim source authority.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Any, Final, Mapping, Sequence

from .hybrid_retrieval import (
    HybridSearchRequest,
    PatentHybridRetriever,
    PrivateRouteIsolationError,
    apply_pre_ranking_filters,
    hybrid_search,
    search_bm25_family,
    search_graph_family,
    search_vector_family,
)
from .indexing import (
    DEFAULT_CORPUS_CID,
    DEFAULT_EMBEDDING_CONFIG_CID,
    EmbeddingCallLedger,
    EmbeddingFn,
    PatentIndexBundle,
    PatentIndexDocument,
    build_patent_indexes,
    default_embedding_identity,
    score_fielded_bm25,
)
from .retrieval_contracts import (
    RETRIEVAL_CONTRACTS_SCHEMA_VERSION,
    AuthorityClaim,
    DisclosureClass,
    EmbeddingIdentity,
    FusionWeights,
    MissingPreRankingFiltersError,
    PreRankingFilters,
    RankedHit,
    RetrievalFamily,
    SourceLink,
    SourceSpan,
    fuse_ranked_hits,
    is_private_disclosure,
    require_pre_ranking_filters,
    requires_quarantine,
)

# ---------------------------------------------------------------------------
# Schema / interface pins
# ---------------------------------------------------------------------------

HYBRID_RETRIEVAL_V2_SCHEMA_VERSION: Final = "patent.hybrid_retrieval.v2"
HYBRID_RETRIEVAL_V2_INTERFACE: Final = "HybridRetrievalV2@1"
HYBRID_RETRIEVAL_V2_CODE_VERSION: Final = "1.0.0"

DEFAULT_SNAPSHOT_CID: Final = (
    "bafybeisnapshothybridv2placeholder00000000000000000000001"
)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class HybridRetrievalV2Error(ValueError):
    """Base error for explainable hybrid retrieval failures."""


class MissingSourceSpanError(HybridRetrievalV2Error):
    """Raised when a hit cannot expose a source span join."""


class ComponentWeightError(HybridRetrievalV2Error):
    """Raised when component fusion weights are invalid."""


# ---------------------------------------------------------------------------
# Component contributions
# ---------------------------------------------------------------------------


class ScoreComponent(str, Enum):
    """Named fusion components exposed on every explainable hit."""

    BM25 = "bm25"
    VECTOR = "vector"
    GRAPH = "graph"
    CPC = "cpc"
    IPC = "ipc"
    CITATION = "citation"
    FAMILY = "family"


# Field names that map to dedicated contribution channels (not elevated
# authority — they remain lexical/graph signals under source-bound hits).
_FIELD_COMPONENT_MAP: Final[Mapping[str, ScoreComponent]] = MappingProxyType(
    {
        "cpc": ScoreComponent.CPC,
        "ipc": ScoreComponent.IPC,
        "citations": ScoreComponent.CITATION,
    }
)

# Graph edge kinds that contribute a family/citation path signal.
_FAMILY_EDGE_KINDS: Final[frozenset[str]] = frozenset(
    {
        "continuation",
        "priority",
        "cites",
        "family",
        "same_family",
    }
)


@dataclass(frozen=True, slots=True)
class ComponentWeights:
    """Relative weights for explainable multi-component fusion.

    Primary families (bm25/vector/graph) drive the fused ranking. CPC, IPC,
    citation, and family are *explanatory* boosts derived from matched fields
    and graph path metadata; they refine contributions without elevating
    generated edges to authority.
    """

    bm25: float = 1.0
    vector: float = 1.0
    graph: float = 0.5
    cpc: float = 0.15
    ipc: float = 0.15
    citation: float = 0.2
    family: float = 0.15

    def __post_init__(self) -> None:
        for name in (
            "bm25",
            "vector",
            "graph",
            "cpc",
            "ipc",
            "citation",
            "family",
        ):
            value = float(getattr(self, name))
            if value < 0.0:
                raise ComponentWeightError(f"{name} weight must be non-negative")
            object.__setattr__(self, name, value)
        primary = self.bm25 + self.vector + self.graph
        if primary <= 0.0:
            raise ComponentWeightError(
                "at least one of bm25/vector/graph weights must be > 0"
            )

    def primary_fusion_weights(self) -> FusionWeights:
        return FusionWeights(bm25=self.bm25, vector=self.vector, graph=self.graph)

    def weight_for(self, component: ScoreComponent | str) -> float:
        key = (
            component.value
            if isinstance(component, ScoreComponent)
            else str(component).strip().lower()
        )
        try:
            return float(getattr(self, key))
        except AttributeError as exc:
            raise ComponentWeightError(f"unknown component {key!r}") from exc

    def to_dict(self) -> dict[str, float]:
        return {
            "bm25": self.bm25,
            "citation": self.citation,
            "cpc": self.cpc,
            "family": self.family,
            "graph": self.graph,
            "ipc": self.ipc,
            "vector": self.vector,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any] | None) -> "ComponentWeights":
        if value is None:
            return cls()
        if not isinstance(value, Mapping):
            raise TypeError("ComponentWeights payload must be a mapping")
        return cls(
            bm25=float(value.get("bm25", 1.0)),
            vector=float(value.get("vector", 1.0)),
            graph=float(value.get("graph", 0.5)),
            cpc=float(value.get("cpc", 0.15)),
            ipc=float(value.get("ipc", 0.15)),
            citation=float(value.get("citation", 0.2)),
            family=float(value.get("family", 0.15)),
        )

    @classmethod
    def from_fusion_weights(
        cls, weights: FusionWeights | Mapping[str, float] | None
    ) -> "ComponentWeights":
        if weights is None:
            return cls()
        if isinstance(weights, FusionWeights):
            return cls(bm25=weights.bm25, vector=weights.vector, graph=weights.graph)
        return cls.from_dict(weights)


@dataclass(frozen=True, slots=True)
class ScoreContribution:
    """One component's raw / normalized / weighted contribution to a hit."""

    component: ScoreComponent
    raw_score: float
    normalized_score: float
    weight: float
    contribution: float
    detail: str = ""

    def __post_init__(self) -> None:
        if isinstance(self.component, ScoreComponent):
            component = self.component
        else:
            component = ScoreComponent(str(self.component).strip().lower())
        object.__setattr__(self, "component", component)
        object.__setattr__(self, "raw_score", float(self.raw_score))
        object.__setattr__(self, "normalized_score", float(self.normalized_score))
        object.__setattr__(self, "weight", float(self.weight))
        object.__setattr__(self, "contribution", float(self.contribution))
        object.__setattr__(self, "detail", str(self.detail or ""))

    def to_dict(self) -> dict[str, Any]:
        return {
            "component": self.component.value,
            "contribution": self.contribution,
            "detail": self.detail,
            "normalized_score": self.normalized_score,
            "raw_score": self.raw_score,
            "weight": self.weight,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ScoreContribution":
        if not isinstance(value, Mapping):
            raise TypeError("ScoreContribution payload must be a mapping")
        return cls(
            component=ScoreComponent(str(value.get("component") or "bm25")),
            raw_score=float(value.get("raw_score") or 0.0),
            normalized_score=float(value.get("normalized_score") or 0.0),
            weight=float(value.get("weight") or 0.0),
            contribution=float(value.get("contribution") or 0.0),
            detail=str(value.get("detail") or ""),
        )


@dataclass(frozen=True, slots=True)
class ExposedSourceSpan:
    """Exact source join + span exposed on a retrieval hit."""

    source_cid: str
    artifact_id: str
    span: SourceSpan
    authority_tier: str | None = None
    source_version: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_cid", str(self.source_cid).strip())
        object.__setattr__(self, "artifact_id", str(self.artifact_id).strip())
        if not self.source_cid:
            raise MissingSourceSpanError("source_cid must be non-empty")
        if not self.artifact_id:
            raise MissingSourceSpanError("artifact_id must be non-empty")
        if not isinstance(self.span, SourceSpan):
            if isinstance(self.span, Mapping):
                object.__setattr__(self, "span", SourceSpan.from_dict(self.span))
            else:
                raise TypeError("span must be SourceSpan or mapping")
        object.__setattr__(
            self,
            "authority_tier",
            None if self.authority_tier is None else str(self.authority_tier),
        )
        object.__setattr__(
            self,
            "source_version",
            None if self.source_version is None else str(self.source_version),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "authority_tier": self.authority_tier,
            "source_cid": self.source_cid,
            "source_version": self.source_version,
            "span": self.span.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ExposedSourceSpan":
        if not isinstance(value, Mapping):
            raise TypeError("ExposedSourceSpan payload must be a mapping")
        span_raw = value.get("span")
        if span_raw is None:
            raise MissingSourceSpanError("ExposedSourceSpan requires span")
        return cls(
            source_cid=str(value.get("source_cid") or ""),
            artifact_id=str(value.get("artifact_id") or ""),
            span=SourceSpan.from_dict(span_raw)
            if isinstance(span_raw, Mapping)
            else span_raw,
            authority_tier=value.get("authority_tier"),
            source_version=value.get("source_version"),
        )

    @classmethod
    def from_source_link(
        cls,
        link: SourceLink | Mapping[str, Any],
        *,
        source_version: str | None = None,
        default_span: SourceSpan | None = None,
    ) -> "ExposedSourceSpan":
        if isinstance(link, Mapping):
            link = SourceLink.from_dict(link)
        if not isinstance(link, SourceLink):
            raise TypeError("link must be SourceLink or mapping")
        span = link.span
        if span is None:
            span = default_span or SourceSpan(start=0, end=0, unit="char")
        return cls(
            source_cid=link.source_cid,
            artifact_id=link.artifact_id,
            span=span,
            authority_tier=link.authority_tier,
            source_version=source_version,
        )


@dataclass(frozen=True, slots=True)
class ExplainableHit:
    """Ranked hit with component contributions and exact source spans."""

    document_id: str
    score: float
    rank: int
    family: RetrievalFamily
    source_spans: tuple[ExposedSourceSpan, ...]
    score_contributions: tuple[ScoreContribution, ...]
    source_links: tuple[SourceLink, ...]
    authority_claim: AuthorityClaim = AuthorityClaim.SOURCE_BOUND
    matched_fields: tuple[str, ...] = ()
    row_id: str | None = None
    metadata: Mapping[str, str] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(self, "document_id", str(self.document_id).strip())
        if not self.document_id:
            raise HybridRetrievalV2Error("document_id must be non-empty")
        object.__setattr__(self, "score", float(self.score))
        object.__setattr__(self, "rank", int(self.rank))
        if self.rank < 1:
            raise HybridRetrievalV2Error("rank must be >= 1")
        if isinstance(self.family, str):
            object.__setattr__(self, "family", RetrievalFamily(self.family))
        if isinstance(self.authority_claim, str):
            object.__setattr__(
                self, "authority_claim", AuthorityClaim(self.authority_claim)
            )
        spans = tuple(self.source_spans)
        if not spans:
            raise MissingSourceSpanError(
                f"hit {self.document_id!r} missing source spans"
            )
        object.__setattr__(self, "source_spans", spans)
        contribs = tuple(self.score_contributions)
        object.__setattr__(self, "score_contributions", contribs)
        links = tuple(self.source_links)
        if not links:
            raise HybridRetrievalV2Error(
                f"hit {self.document_id!r} missing source links"
            )
        object.__setattr__(self, "source_links", links)
        object.__setattr__(self, "matched_fields", tuple(self.matched_fields))
        object.__setattr__(
            self,
            "metadata",
            MappingProxyType({str(k): str(v) for k, v in dict(self.metadata).items()}),
        )

    @property
    def contribution_map(self) -> Mapping[str, float]:
        return MappingProxyType(
            {c.component.value: c.contribution for c in self.score_contributions}
        )

    def to_ranked_hit(self) -> RankedHit:
        """Project to a v1 :class:`RankedHit` for evaluation compatibility."""
        meta = dict(self.metadata)
        # Encode contributions for consumers that only see RankedHit metadata.
        for contrib in self.score_contributions:
            meta[f"contrib_{contrib.component.value}"] = f"{contrib.contribution:.12g}"
            meta[f"raw_{contrib.component.value}"] = f"{contrib.raw_score:.12g}"
        meta["explainable"] = "1"
        return RankedHit(
            document_id=self.document_id,
            score=self.score,
            rank=self.rank,
            family=self.family,
            source_links=self.source_links,
            row_id=self.row_id,
            authority_claim=self.authority_claim,
            matched_fields=self.matched_fields,
            metadata=meta,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority_claim": self.authority_claim.value,
            "document_id": self.document_id,
            "family": self.family.value,
            "matched_fields": list(self.matched_fields),
            "metadata": dict(self.metadata),
            "rank": self.rank,
            "row_id": self.row_id,
            "score": self.score,
            "score_contributions": [c.to_dict() for c in self.score_contributions],
            "source_links": [link.to_dict() for link in self.source_links],
            "source_spans": [s.to_dict() for s in self.source_spans],
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ExplainableHit":
        if not isinstance(value, Mapping):
            raise TypeError("ExplainableHit payload must be a mapping")
        spans = tuple(
            ExposedSourceSpan.from_dict(s) for s in (value.get("source_spans") or ())
        )
        contribs = tuple(
            ScoreContribution.from_dict(c)
            for c in (value.get("score_contributions") or ())
        )
        links = tuple(
            SourceLink.from_dict(link) if isinstance(link, Mapping) else link
            for link in (value.get("source_links") or ())
        )
        return cls(
            document_id=str(value.get("document_id") or ""),
            score=float(value.get("score") or 0.0),
            rank=int(value.get("rank") or 1),
            family=RetrievalFamily(str(value.get("family") or "fusion")),
            source_spans=spans,
            score_contributions=contribs,
            source_links=links,
            authority_claim=value.get(
                "authority_claim", AuthorityClaim.SOURCE_BOUND.value
            ),
            matched_fields=tuple(value.get("matched_fields") or ()),
            row_id=value.get("row_id"),
            metadata=value.get("metadata") or {},
        )


@dataclass(frozen=True, slots=True)
class SnapshotBinding:
    """Identity pins bound into every v2 search result / evaluation receipt."""

    snapshot_cid: str
    corpus_cid: str
    model_cid: str
    config_cid: str
    index_cids: Mapping[str, str] = MappingProxyType({})
    logical_root_cid: str | None = None
    model_pin: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "snapshot_cid", str(self.snapshot_cid).strip())
        object.__setattr__(self, "corpus_cid", str(self.corpus_cid).strip())
        object.__setattr__(self, "model_cid", str(self.model_cid).strip())
        object.__setattr__(self, "config_cid", str(self.config_cid).strip())
        for name in ("snapshot_cid", "corpus_cid", "model_cid", "config_cid"):
            if not getattr(self, name):
                raise HybridRetrievalV2Error(f"{name} must be non-empty")
        object.__setattr__(
            self,
            "index_cids",
            MappingProxyType(
                {str(k): str(v) for k, v in sorted(dict(self.index_cids).items())}
            ),
        )
        object.__setattr__(
            self,
            "logical_root_cid",
            None if self.logical_root_cid is None else str(self.logical_root_cid),
        )
        object.__setattr__(
            self,
            "model_pin",
            None if self.model_pin is None else str(self.model_pin),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "config_cid": self.config_cid,
            "corpus_cid": self.corpus_cid,
            "index_cids": dict(self.index_cids),
            "logical_root_cid": self.logical_root_cid,
            "model_cid": self.model_cid,
            "model_pin": self.model_pin,
            "snapshot_cid": self.snapshot_cid,
        }

    def binding_cids(self) -> Mapping[str, str]:
        return MappingProxyType(
            {
                "snapshot_cid": self.snapshot_cid,
                "corpus_cid": self.corpus_cid,
                "model_cid": self.model_cid,
                "config_cid": self.config_cid,
            }
        )

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SnapshotBinding":
        if not isinstance(value, Mapping):
            raise TypeError("SnapshotBinding payload must be a mapping")
        return cls(
            snapshot_cid=str(value.get("snapshot_cid") or ""),
            corpus_cid=str(value.get("corpus_cid") or ""),
            model_cid=str(value.get("model_cid") or ""),
            config_cid=str(value.get("config_cid") or ""),
            index_cids=value.get("index_cids") or {},
            logical_root_cid=value.get("logical_root_cid"),
            model_pin=value.get("model_pin"),
        )


@dataclass(frozen=True, slots=True)
class HybridSearchRequestV2:
    """Explainable hybrid retrieval request with mandatory filters."""

    query_id: str
    query: str
    filters: PreRankingFilters
    top_k: int = 10
    component_weights: ComponentWeights | None = None
    seed_document_ids: tuple[str, ...] = ()
    allow_remote_embeddings: bool = False
    query_disclosure: DisclosureClass = DisclosureClass.PUBLIC_USER
    max_graph_hops: int = 2
    # Declared sources that were *not* searched (reported, never scored as searched).
    unsearched_sources: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "query_id", str(self.query_id).strip())
        object.__setattr__(self, "query", str(self.query))
        if not self.query_id:
            raise HybridRetrievalV2Error("query_id must be non-empty")
        if not isinstance(self.filters, PreRankingFilters):
            raise TypeError("filters must be PreRankingFilters")
        if isinstance(self.query_disclosure, str):
            object.__setattr__(
                self, "query_disclosure", DisclosureClass(self.query_disclosure)
            )
        if self.component_weights is not None and not isinstance(
            self.component_weights, ComponentWeights
        ):
            if isinstance(self.component_weights, Mapping):
                object.__setattr__(
                    self,
                    "component_weights",
                    ComponentWeights.from_dict(self.component_weights),
                )
            else:
                raise TypeError("component_weights must be ComponentWeights or mapping")
        object.__setattr__(self, "seed_document_ids", tuple(self.seed_document_ids))
        object.__setattr__(
            self,
            "unsearched_sources",
            tuple(str(s).strip() for s in self.unsearched_sources if str(s).strip()),
        )
        object.__setattr__(self, "top_k", int(self.top_k))
        if self.top_k < 1:
            raise HybridRetrievalV2Error("top_k must be >= 1")


@dataclass(frozen=True, slots=True)
class HybridSearchResultV2:
    """Explainable hybrid search output with isolation counters and binding."""

    schema_version: str
    query_id: str
    query: str
    filters: PreRankingFilters
    hits: tuple[ExplainableHit, ...]
    bm25_hits: tuple[ExplainableHit, ...]
    vector_hits: tuple[ExplainableHit, ...]
    graph_hits: tuple[ExplainableHit, ...]
    component_weights: ComponentWeights
    binding: SnapshotBinding
    denied_provider_call_count: int
    remote_embedding_calls: int
    denied_result_count: int
    unsearched_sources: tuple[str, ...]
    bm25_backend: str
    vector_embedding: Mapping[str, Any]
    ranking_digest: str
    metadata: Mapping[str, str] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "schema_version", str(self.schema_version or HYBRID_RETRIEVAL_V2_SCHEMA_VERSION)
        )
        object.__setattr__(self, "query_id", str(self.query_id))
        object.__setattr__(self, "query", str(self.query))
        require_pre_ranking_filters(self.filters)
        object.__setattr__(self, "hits", tuple(self.hits))
        object.__setattr__(self, "bm25_hits", tuple(self.bm25_hits))
        object.__setattr__(self, "vector_hits", tuple(self.vector_hits))
        object.__setattr__(self, "graph_hits", tuple(self.graph_hits))
        object.__setattr__(
            self, "denied_provider_call_count", int(self.denied_provider_call_count)
        )
        object.__setattr__(
            self, "remote_embedding_calls", int(self.remote_embedding_calls)
        )
        object.__setattr__(self, "denied_result_count", int(self.denied_result_count))
        object.__setattr__(
            self, "unsearched_sources", tuple(self.unsearched_sources)
        )
        object.__setattr__(
            self,
            "vector_embedding",
            MappingProxyType(dict(self.vector_embedding)),
        )
        object.__setattr__(
            self,
            "metadata",
            MappingProxyType({str(k): str(v) for k, v in dict(self.metadata).items()}),
        )

    @property
    def fused_hits(self) -> tuple[ExplainableHit, ...]:
        return self.hits

    def to_ranked_hits(self, family: RetrievalFamily | str = RetrievalFamily.FUSION) -> tuple[RankedHit, ...]:
        if isinstance(family, str):
            family = RetrievalFamily(family)
        if family is RetrievalFamily.FUSION:
            source = self.hits
        elif family is RetrievalFamily.BM25:
            source = self.bm25_hits
        elif family is RetrievalFamily.VECTOR:
            source = self.vector_hits
        elif family is RetrievalFamily.GRAPH:
            source = self.graph_hits
        else:
            raise HybridRetrievalV2Error(f"unsupported family {family!r}")
        return tuple(h.to_ranked_hit() for h in source)

    def to_dict(self) -> dict[str, Any]:
        return {
            "binding": self.binding.to_dict(),
            "bm25_backend": self.bm25_backend,
            "bm25_hits": [h.to_dict() for h in self.bm25_hits],
            "component_weights": self.component_weights.to_dict(),
            "denied_provider_call_count": self.denied_provider_call_count,
            "denied_result_count": self.denied_result_count,
            "filters": self.filters.to_dict(),
            "graph_hits": [h.to_dict() for h in self.graph_hits],
            "hits": [h.to_dict() for h in self.hits],
            "metadata": dict(self.metadata),
            "query": self.query,
            "query_id": self.query_id,
            "ranking_digest": self.ranking_digest,
            "remote_embedding_calls": self.remote_embedding_calls,
            "schema_version": self.schema_version,
            "unsearched_sources": list(self.unsearched_sources),
            "vector_embedding": dict(self.vector_embedding),
            "vector_hits": [h.to_dict() for h in self.vector_hits],
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _normalize_scores(scores: Mapping[str, float]) -> dict[str, float]:
    if not scores:
        return {}
    values = list(scores.values())
    lo, hi = min(values), max(values)
    span = hi - lo
    if span <= 0.0:
        return {doc: 1.0 for doc in scores}
    return {doc: (score - lo) / span for doc, score in scores.items()}


def _spans_from_links(
    links: Sequence[SourceLink | Mapping[str, Any]],
    *,
    source_version: str | None = None,
) -> tuple[ExposedSourceSpan, ...]:
    out: list[ExposedSourceSpan] = []
    for link in links:
        out.append(
            ExposedSourceSpan.from_source_link(link, source_version=source_version)
        )
    if not out:
        raise MissingSourceSpanError("source links empty; cannot expose spans")
    return tuple(out)


def _links_from_hit(hit: RankedHit) -> tuple[SourceLink, ...]:
    return tuple(hit.source_links)


def ranking_digest_v2(hits: Sequence[ExplainableHit]) -> str:
    """Deterministic digest of explainable ranking (score + contributions + spans)."""
    payload = [
        {
            "contributions": {
                c.component.value: round(c.contribution, 12)
                for c in sorted(h.score_contributions, key=lambda x: x.component.value)
            },
            "document_id": h.document_id,
            "family": h.family.value,
            "rank": h.rank,
            "score": round(float(h.score), 12),
            "source_cids": sorted({s.source_cid for s in h.source_spans}),
            "spans": [
                {
                    "artifact_id": s.artifact_id,
                    "end": s.span.end,
                    "source_cid": s.source_cid,
                    "start": s.span.start,
                    "unit": s.span.unit,
                }
                for s in sorted(
                    h.source_spans, key=lambda x: (x.source_cid, x.artifact_id)
                )
            ],
        }
        for h in sorted(hits, key=lambda x: (x.rank, x.document_id))
    ]
    # Local canonicalization to avoid a circular import dependency on evaluation.
    blob = _canonical_json(payload).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def _canonical_json(value: Any) -> str:
    import json

    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _field_boosts_from_bm25(
    query: str,
    bundle: PatentIndexBundle,
) -> dict[str, dict[str, float]]:
    """Per-document raw boosts for CPC / IPC / citation matched fields."""
    scored = score_fielded_bm25(query, bundle.bm25, top_k=max(50, len(bundle.bm25.documents)))
    out: dict[str, dict[str, float]] = {}
    for item in scored:
        doc_id = str(item["document_id"])
        matched = {str(f) for f in (item.get("matched_fields") or ())}
        total = float(item.get("score") or 0.0)
        if total <= 0.0:
            continue
        # Allocate a proportional slice of BM25 score to specialty fields when present.
        specialty = matched & set(_FIELD_COMPONENT_MAP)
        if not specialty:
            continue
        share = total / float(len(specialty))
        bucket = out.setdefault(doc_id, {})
        for field in specialty:
            component = _FIELD_COMPONENT_MAP[field]
            bucket[component.value] = bucket.get(component.value, 0.0) + share
    return out


def _family_boosts_from_graph(
    graph_hits: Sequence[RankedHit],
) -> dict[str, float]:
    """Detect family/citation path signals from graph hit metadata."""
    boosts: dict[str, float] = {}
    for hit in graph_hits:
        edge_ids = str(hit.metadata.get("path_edge_ids") or "")
        # Graph expansion always implies a path; treat as family-path signal.
        raw = float(hit.score)
        if raw <= 0.0:
            continue
        # Slightly amplify when edge metadata mentions family/citation kinds.
        kind_hint = edge_ids.lower()
        multiplier = 1.0
        for kind in _FAMILY_EDGE_KINDS:
            if kind in kind_hint:
                multiplier = 1.25
                break
        # Also inspect matched fields if present.
        for field in hit.matched_fields:
            if str(field).lower() in _FAMILY_EDGE_KINDS or str(field).lower() == "citations":
                multiplier = max(multiplier, 1.15)
        boosts[hit.document_id] = max(boosts.get(hit.document_id, 0.0), raw * multiplier)
    return boosts


def _hit_index(hits: Sequence[RankedHit]) -> dict[str, RankedHit]:
    return {h.document_id: h for h in hits}


def _build_explainable_family_hits(
    hits: Sequence[RankedHit],
    *,
    family: RetrievalFamily,
    component: ScoreComponent,
    weight: float,
) -> tuple[ExplainableHit, ...]:
    norms = _normalize_scores({h.document_id: h.score for h in hits})
    out: list[ExplainableHit] = []
    for hit in sorted(hits, key=lambda h: (h.rank, h.document_id)):
        norm = norms.get(hit.document_id, 0.0)
        contrib = ScoreContribution(
            component=component,
            raw_score=float(hit.score),
            normalized_score=norm,
            weight=weight,
            contribution=weight * norm,
            detail=f"{family.value}_family",
        )
        spans = _spans_from_links(hit.source_links)
        out.append(
            ExplainableHit(
                document_id=hit.document_id,
                score=float(hit.score),
                rank=int(hit.rank),
                family=family,
                source_spans=spans,
                score_contributions=(contrib,),
                source_links=hit.source_links,
                authority_claim=hit.authority_claim,
                matched_fields=hit.matched_fields,
                row_id=hit.row_id,
                metadata=dict(hit.metadata),
            )
        )
    return tuple(out)


def fuse_explainable(
    *,
    query_id: str,
    query: str,
    filters: PreRankingFilters,
    bm25_hits: Sequence[RankedHit],
    vector_hits: Sequence[RankedHit],
    graph_hits: Sequence[RankedHit],
    component_weights: ComponentWeights,
    binding: SnapshotBinding,
    field_boosts: Mapping[str, Mapping[str, float]] | None = None,
    family_boosts: Mapping[str, float] | None = None,
    top_k: int = 10,
) -> tuple[ExplainableHit, ...]:
    """Fuse families with explanatory specialty contributions.

    Primary ranking uses weighted min-max normalized BM25/vector/graph scores
    (identical to v1 fusion). Specialty components (CPC/IPC/citation/family)
    add weighted normalized contributions for explanation and mild re-rank
    refinement without claiming source authority on generated edges.
    """
    require_pre_ranking_filters(filters)
    weights = component_weights
    bm25_raw = {h.document_id: float(h.score) for h in bm25_hits}
    vector_raw = {h.document_id: float(h.score) for h in vector_hits}
    graph_raw = {h.document_id: float(h.score) for h in graph_hits}
    bm25_n = _normalize_scores(bm25_raw)
    vector_n = _normalize_scores(vector_raw)
    graph_n = _normalize_scores(graph_raw)

    field_boosts = dict(field_boosts or {})
    family_boosts = dict(family_boosts or {})

    # Specialty raw maps.
    cpc_raw: dict[str, float] = {}
    ipc_raw: dict[str, float] = {}
    citation_raw: dict[str, float] = {}
    for doc_id, boosts in field_boosts.items():
        if "cpc" in boosts:
            cpc_raw[doc_id] = float(boosts["cpc"])
        if "ipc" in boosts:
            ipc_raw[doc_id] = float(boosts["ipc"])
        if "citation" in boosts:
            citation_raw[doc_id] = float(boosts["citation"])
    family_raw = {doc: float(v) for doc, v in family_boosts.items()}

    cpc_n = _normalize_scores(cpc_raw)
    ipc_n = _normalize_scores(ipc_raw)
    citation_n = _normalize_scores(citation_raw)
    family_n = _normalize_scores(family_raw)

    docs = (
        set(bm25_n)
        | set(vector_n)
        | set(graph_n)
        | set(cpc_n)
        | set(ipc_n)
        | set(citation_n)
        | set(family_n)
    )

    # Prefer source links / authority from BM25 → vector → graph order.
    link_bank: dict[str, tuple[SourceLink, ...]] = {}
    claim_bank: dict[str, AuthorityClaim] = {}
    matched_bank: dict[str, tuple[str, ...]] = {}
    meta_bank: dict[str, dict[str, str]] = {}
    row_bank: dict[str, str | None] = {}
    for family_hits in (bm25_hits, vector_hits, graph_hits):
        for hit in family_hits:
            link_bank.setdefault(hit.document_id, hit.source_links)
            claim_bank.setdefault(hit.document_id, hit.authority_claim)
            matched_bank.setdefault(hit.document_id, hit.matched_fields)
            meta_bank.setdefault(hit.document_id, dict(hit.metadata))
            row_bank.setdefault(hit.document_id, hit.row_id)

    combined: list[tuple[str, float, tuple[ScoreContribution, ...]]] = []
    for doc in docs:
        contributions: list[ScoreContribution] = []
        for component, raw_map, norm_map in (
            (ScoreComponent.BM25, bm25_raw, bm25_n),
            (ScoreComponent.VECTOR, vector_raw, vector_n),
            (ScoreComponent.GRAPH, graph_raw, graph_n),
            (ScoreComponent.CPC, cpc_raw, cpc_n),
            (ScoreComponent.IPC, ipc_raw, ipc_n),
            (ScoreComponent.CITATION, citation_raw, citation_n),
            (ScoreComponent.FAMILY, family_raw, family_n),
        ):
            raw = float(raw_map.get(doc, 0.0))
            norm = float(norm_map.get(doc, 0.0))
            w = weights.weight_for(component)
            if raw == 0.0 and norm == 0.0:
                continue
            contributions.append(
                ScoreContribution(
                    component=component,
                    raw_score=raw,
                    normalized_score=norm,
                    weight=w,
                    contribution=w * norm,
                    detail=f"component={component.value}",
                )
            )
        # Primary score matches v1 fusion (specialty components are explanatory
        # and mild re-rank only — scale specialty total by a fixed fraction so
        # they cannot dominate source-bound primary families).
        primary = (
            weights.bm25 * bm25_n.get(doc, 0.0)
            + weights.vector * vector_n.get(doc, 0.0)
            + weights.graph * graph_n.get(doc, 0.0)
        )
        specialty = (
            weights.cpc * cpc_n.get(doc, 0.0)
            + weights.ipc * ipc_n.get(doc, 0.0)
            + weights.citation * citation_n.get(doc, 0.0)
            + weights.family * family_n.get(doc, 0.0)
        )
        # Cap specialty influence at 15% of the primary scale.
        score = primary + 0.15 * specialty
        if not contributions:
            continue
        combined.append((doc, score, tuple(contributions)))

    combined.sort(key=lambda item: (-item[1], item[0]))
    fused: list[ExplainableHit] = []
    for rank, (doc, score, contributions) in enumerate(combined[:top_k], start=1):
        links = link_bank.get(doc)
        if not links:
            # Specialty-only docs without family hits cannot join a source CID.
            raise MissingSourceSpanError(
                f"fused document {doc!r} has no source-linked family hit"
            )
        spans = _spans_from_links(links)
        fused.append(
            ExplainableHit(
                document_id=doc,
                score=score,
                rank=rank,
                family=RetrievalFamily.FUSION,
                source_spans=spans,
                score_contributions=contributions,
                source_links=links,
                authority_claim=claim_bank.get(doc, AuthorityClaim.SOURCE_BOUND),
                matched_fields=matched_bank.get(doc, ()),
                row_id=row_bank.get(doc),
                metadata={
                    **meta_bank.get(doc, {}),
                    "snapshot_cid": binding.snapshot_cid,
                    "query_id": query_id,
                },
            )
        )
    return tuple(fused)


# ---------------------------------------------------------------------------
# Retriever
# ---------------------------------------------------------------------------


class HybridRetrievalV2:
    """Explainable hybrid retriever over a :class:`PatentIndexBundle`.

    Designed for persistent-index workflows: construct from a bundle produced
    by the in-memory builders (or projected from a durable snapshot) and bind
    snapshot / model / config identities into every result.
    """

    def __init__(
        self,
        bundle: PatentIndexBundle,
        *,
        binding: SnapshotBinding | None = None,
        remote_embedder: EmbeddingFn | None = None,
        default_weights: ComponentWeights | None = None,
        source_versions: Mapping[str, str] | None = None,
    ) -> None:
        if not isinstance(bundle, PatentIndexBundle):
            raise TypeError("bundle must be PatentIndexBundle")
        self._bundle = bundle
        self._v1 = PatentHybridRetriever(bundle, remote_embedder=remote_embedder)
        self._ledger = EmbeddingCallLedger()
        self._v1._ledger = self._ledger
        self.remote_embedder = remote_embedder
        self.default_weights = default_weights or ComponentWeights()
        self._source_versions = {
            str(k): str(v) for k, v in dict(source_versions or {}).items()
        }

        model_cid = (
            bundle.model_cid
            or bundle.vector.embedding.model_cid
            or DEFAULT_EMBEDDING_CONFIG_CID
        )
        config_cid = (
            bundle.config_cid
            or bundle.vector.embedding.config_cid
            or DEFAULT_EMBEDDING_CONFIG_CID
        )
        if binding is None:
            binding = SnapshotBinding(
                snapshot_cid=DEFAULT_SNAPSHOT_CID,
                corpus_cid=bundle.corpus_cid or DEFAULT_CORPUS_CID,
                model_cid=str(model_cid),
                config_cid=str(config_cid),
                index_cids=dict(bundle.index_cids),
            )
        elif not isinstance(binding, SnapshotBinding):
            raise TypeError("binding must be SnapshotBinding")
        self.binding = binding

    @classmethod
    def from_documents(
        cls,
        documents: Sequence[PatentIndexDocument],
        *,
        filters: PreRankingFilters,
        edges: Sequence[Any] = (),
        embedding: EmbeddingIdentity | None = None,
        corpus_cid: str = DEFAULT_CORPUS_CID,
        snapshot_cid: str = DEFAULT_SNAPSHOT_CID,
        allow_remote: bool = False,
        remote_embedder: EmbeddingFn | None = None,
        component_weights: ComponentWeights | None = None,
        logical_root_cid: str | None = None,
        model_pin: str | None = None,
    ) -> "HybridRetrievalV2":
        """Build indexes from documents then return an explainable retriever."""
        applied = filters if filters.applied else filters.mark_applied()
        emb = embedding or default_embedding_identity()
        bundle = build_patent_indexes(
            documents,
            filters=applied,
            edges=edges,
            embedding=emb,
            corpus_cid=corpus_cid,
            allow_remote=allow_remote,
            remote_embedder=remote_embedder,
        )
        binding = SnapshotBinding(
            snapshot_cid=snapshot_cid,
            corpus_cid=bundle.corpus_cid,
            model_cid=str(bundle.model_cid or emb.model_cid or DEFAULT_EMBEDDING_CONFIG_CID),
            config_cid=str(bundle.config_cid or emb.config_cid or DEFAULT_EMBEDDING_CONFIG_CID),
            index_cids=dict(bundle.index_cids),
            logical_root_cid=logical_root_cid,
            model_pin=model_pin,
        )
        source_versions: dict[str, str] = {}
        for doc in documents:
            for link in doc.source_links:
                ver = (doc.metadata or {}).get("source_version")
                if ver:
                    source_versions[link.source_cid] = str(ver)
        return cls(
            bundle,
            binding=binding,
            remote_embedder=remote_embedder,
            default_weights=component_weights,
            source_versions=source_versions,
        )

    @classmethod
    def from_bundle(
        cls,
        bundle: PatentIndexBundle,
        *,
        snapshot_cid: str | None = None,
        logical_root_cid: str | None = None,
        model_pin: str | None = None,
        **kwargs: Any,
    ) -> "HybridRetrievalV2":
        model_cid = (
            bundle.model_cid
            or bundle.vector.embedding.model_cid
            or DEFAULT_EMBEDDING_CONFIG_CID
        )
        config_cid = (
            bundle.config_cid
            or bundle.vector.embedding.config_cid
            or DEFAULT_EMBEDDING_CONFIG_CID
        )
        binding = SnapshotBinding(
            snapshot_cid=snapshot_cid or DEFAULT_SNAPSHOT_CID,
            corpus_cid=bundle.corpus_cid or DEFAULT_CORPUS_CID,
            model_cid=str(model_cid),
            config_cid=str(config_cid),
            index_cids=dict(bundle.index_cids),
            logical_root_cid=logical_root_cid,
            model_pin=model_pin,
        )
        return cls(bundle, binding=binding, **kwargs)

    @property
    def bundle(self) -> PatentIndexBundle:
        return self._bundle

    @property
    def corpus_cid(self) -> str:
        return self.binding.corpus_cid

    @property
    def model_cid(self) -> str:
        return self.binding.model_cid

    @property
    def config_cid(self) -> str:
        return self.binding.config_cid

    @property
    def snapshot_cid(self) -> str:
        return self.binding.snapshot_cid

    @property
    def index_cids(self) -> Mapping[str, str]:
        return self.binding.index_cids

    @property
    def embedding_identity(self) -> EmbeddingIdentity:
        return self._bundle.vector.embedding

    @property
    def embedding_call_ledger(self) -> EmbeddingCallLedger:
        return self._ledger

    def search(self, request: HybridSearchRequestV2) -> HybridSearchResultV2:
        """Run filters-first explainable BM25 + vector + graph fusion."""
        if not isinstance(request, HybridSearchRequestV2):
            raise TypeError("request must be HybridSearchRequestV2")
        require_pre_ranking_filters(request.filters)

        weights = request.component_weights or self.default_weights
        private_query = is_private_disclosure(
            request.query_disclosure
        ) or requires_quarantine(request.query_disclosure)

        remote_before = self._ledger.remote_call_count
        allow_remote = bool(request.allow_remote_embeddings) and not private_query
        denied_seed = int(request.filters.denied_provider_call_count or 0)

        applied = PreRankingFilters(
            schema_version=request.filters.schema_version,
            tenant_id=request.filters.tenant_id,
            as_of_utc=request.filters.as_of_utc,
            allowed_disclosures=request.filters.allowed_disclosures,
            applied=True,
            denied_provider_call_count=denied_seed,
            filter_receipt_id=(
                request.filters.filter_receipt_id or f"filter:{request.query_id}"
            ),
            metadata=dict(request.filters.metadata),
        )

        bm25_hits = search_bm25_family(
            request.query,
            self._bundle.bm25,
            filters=applied,
            top_k=request.top_k,
        )
        vector_hits, denied_delta = search_vector_family(
            request.query,
            self._bundle.vector,
            filters=applied,
            top_k=request.top_k,
            allow_remote=allow_remote,
            remote_embedder=self.remote_embedder if allow_remote else None,
            ledger=self._ledger,
            query_disclosure=request.query_disclosure,
        )
        graph_hits = search_graph_family(
            request.query,
            self._bundle.graph,
            filters=applied,
            seed_document_ids=request.seed_document_ids,
            bm25_seeds=bm25_hits,
            top_k=request.top_k,
            max_hops=request.max_graph_hops,
        )

        remote_after = self._ledger.remote_call_count
        remote_calls = remote_after - remote_before
        if private_query and remote_calls > 0:
            raise PrivateRouteIsolationError(
                f"private/denied route made {remote_calls} remote embedding call(s)"
            )

        denied_total = denied_seed + int(denied_delta)
        if private_query and (
            _is_remote_identity(self._bundle.vector.embedding)
            or self.remote_embedder is not None
            or request.allow_remote_embeddings
        ):
            denied_total = max(denied_total, denied_seed + 1)

        # Denied results: hits that would have required a denied remote path.
        # Public local-only routes report zero.
        denied_result_count = 0
        if private_query and denied_total > denied_seed:
            denied_result_count = 0  # no results delivered from denied remote

        filters_out = PreRankingFilters(
            schema_version=applied.schema_version,
            tenant_id=applied.tenant_id,
            as_of_utc=applied.as_of_utc,
            allowed_disclosures=applied.allowed_disclosures,
            applied=True,
            denied_provider_call_count=denied_total,
            filter_receipt_id=applied.filter_receipt_id,
            metadata={
                **dict(applied.metadata),
                "query_disclosure": request.query_disclosure.value,
                "remote_embedding_calls": str(remote_calls),
                "snapshot_cid": self.binding.snapshot_cid,
            },
        )

        field_boosts = _field_boosts_from_bm25(request.query, self._bundle)
        family_boosts = _family_boosts_from_graph(graph_hits)

        explainable_bm25 = _build_explainable_family_hits(
            bm25_hits,
            family=RetrievalFamily.BM25,
            component=ScoreComponent.BM25,
            weight=weights.bm25,
        )
        explainable_vector = _build_explainable_family_hits(
            vector_hits,
            family=RetrievalFamily.VECTOR,
            component=ScoreComponent.VECTOR,
            weight=weights.vector,
        )
        explainable_graph = _build_explainable_family_hits(
            graph_hits,
            family=RetrievalFamily.GRAPH,
            component=ScoreComponent.GRAPH,
            weight=weights.graph,
        )

        fused = fuse_explainable(
            query_id=request.query_id,
            query=request.query,
            filters=filters_out,
            bm25_hits=bm25_hits,
            vector_hits=vector_hits,
            graph_hits=graph_hits,
            component_weights=weights,
            binding=self.binding,
            field_boosts=field_boosts,
            family_boosts=family_boosts,
            top_k=request.top_k,
        )

        # Annotate source versions when known.
        if self._source_versions:
            fused = tuple(
                ExplainableHit(
                    document_id=h.document_id,
                    score=h.score,
                    rank=h.rank,
                    family=h.family,
                    source_spans=tuple(
                        ExposedSourceSpan(
                            source_cid=s.source_cid,
                            artifact_id=s.artifact_id,
                            span=s.span,
                            authority_tier=s.authority_tier,
                            source_version=s.source_version
                            or self._source_versions.get(s.source_cid),
                        )
                        for s in h.source_spans
                    ),
                    score_contributions=h.score_contributions,
                    source_links=h.source_links,
                    authority_claim=h.authority_claim,
                    matched_fields=h.matched_fields,
                    row_id=h.row_id,
                    metadata=dict(h.metadata),
                )
                for h in fused
            )

        # Defense in depth: every fused hit must expose spans + contributions.
        for hit in fused:
            if not hit.source_spans:
                raise MissingSourceSpanError(
                    f"fused hit {hit.document_id} missing source spans"
                )
            if not hit.score_contributions:
                raise HybridRetrievalV2Error(
                    f"fused hit {hit.document_id} missing score contributions"
                )
            if not any(s.source_cid for s in hit.source_spans):
                raise MissingSourceSpanError(
                    f"fused hit {hit.document_id} missing source CID on spans"
                )

        digest = ranking_digest_v2(fused)
        return HybridSearchResultV2(
            schema_version=HYBRID_RETRIEVAL_V2_SCHEMA_VERSION,
            query_id=request.query_id,
            query=request.query,
            filters=filters_out,
            hits=fused,
            bm25_hits=explainable_bm25,
            vector_hits=explainable_vector,
            graph_hits=explainable_graph,
            component_weights=weights,
            binding=self.binding,
            denied_provider_call_count=denied_total,
            remote_embedding_calls=remote_calls,
            denied_result_count=denied_result_count,
            unsearched_sources=request.unsearched_sources,
            bm25_backend=self._bundle.bm25.backend,
            vector_embedding=self._bundle.vector.embedding.to_dict(),
            ranking_digest=digest,
            metadata={
                "interface": HYBRID_RETRIEVAL_V2_INTERFACE,
                "code_version": HYBRID_RETRIEVAL_V2_CODE_VERSION,
            },
        )

    def search_query(
        self,
        query: str,
        *,
        query_id: str = "q1",
        filters: PreRankingFilters,
        top_k: int = 10,
        **kwargs: Any,
    ) -> HybridSearchResultV2:
        request = HybridSearchRequestV2(
            query_id=query_id,
            query=query,
            filters=filters,
            top_k=top_k,
            component_weights=kwargs.get("component_weights"),
            seed_document_ids=tuple(kwargs.get("seed_document_ids") or ()),
            allow_remote_embeddings=bool(kwargs.get("allow_remote_embeddings", False)),
            query_disclosure=kwargs.get(
                "query_disclosure", DisclosureClass.PUBLIC_USER
            ),
            max_graph_hops=int(kwargs.get("max_graph_hops") or 2),
            unsearched_sources=tuple(kwargs.get("unsearched_sources") or ()),
        )
        return self.search(request)


def _is_remote_identity(embedding: EmbeddingIdentity) -> bool:
    from .indexing import _is_remote_provider

    return _is_remote_provider(embedding.provider, embedding.backend)


def hybrid_search_v2(
    query: str,
    bundle: PatentIndexBundle,
    *,
    filters: PreRankingFilters,
    query_id: str = "q1",
    top_k: int = 10,
    component_weights: ComponentWeights | Mapping[str, float] | None = None,
    snapshot_cid: str | None = None,
    allow_remote_embeddings: bool = False,
    query_disclosure: DisclosureClass | str = DisclosureClass.PUBLIC_USER,
    remote_embedder: EmbeddingFn | None = None,
    seed_document_ids: Sequence[str] = (),
    unsearched_sources: Sequence[str] = (),
) -> HybridSearchResultV2:
    """Functional entry point for explainable hybrid retrieval."""
    weights: ComponentWeights | None
    if component_weights is None:
        weights = None
    elif isinstance(component_weights, ComponentWeights):
        weights = component_weights
    else:
        weights = ComponentWeights.from_dict(component_weights)
    if isinstance(query_disclosure, str):
        query_disclosure = DisclosureClass(query_disclosure)
    retriever = HybridRetrievalV2.from_bundle(
        bundle,
        snapshot_cid=snapshot_cid,
        remote_embedder=remote_embedder,
        default_weights=weights,
    )
    request = HybridSearchRequestV2(
        query_id=query_id,
        query=query,
        filters=filters,
        top_k=top_k,
        component_weights=weights,
        seed_document_ids=tuple(seed_document_ids),
        allow_remote_embeddings=allow_remote_embeddings,
        query_disclosure=query_disclosure,
        unsearched_sources=tuple(unsearched_sources),
    )
    return retriever.search(request)


def assert_explainable_hits(result: HybridSearchResultV2) -> None:
    """Raise if any fused hit lacks source spans or score contributions."""
    if not result.hits:
        return
    for hit in result.hits:
        if not hit.source_spans:
            raise MissingSourceSpanError(
                f"hit {hit.document_id} missing source spans"
            )
        if not any(s.span is not None for s in hit.source_spans):
            raise MissingSourceSpanError(
                f"hit {hit.document_id} missing span geometry"
            )
        if not hit.score_contributions:
            raise HybridRetrievalV2Error(
                f"hit {hit.document_id} missing score contributions"
            )
        total = sum(c.contribution for c in hit.score_contributions)
        if total < 0.0:
            raise HybridRetrievalV2Error(
                f"hit {hit.document_id} has negative total contribution"
            )


def degrade_ranking(
    hits: Sequence[ExplainableHit],
    *,
    drop_top_n: int = 1,
    reverse: bool = True,
) -> tuple[ExplainableHit, ...]:
    """Intentionally degrade a ranking for threshold regression tests.

    Drops the top-N hits and optionally reverses the remainder so versioned
    thresholds fail loudly on the degraded retrieval.
    """
    ordered = sorted(hits, key=lambda h: (h.rank, h.document_id))
    rest = list(ordered[max(0, int(drop_top_n)) :])
    if reverse:
        rest = list(reversed(rest))
    out: list[ExplainableHit] = []
    for rank, hit in enumerate(rest, start=1):
        out.append(
            ExplainableHit(
                document_id=hit.document_id,
                score=float(hit.score) * 0.01,  # collapse scores
                rank=rank,
                family=hit.family,
                source_spans=hit.source_spans,
                score_contributions=hit.score_contributions,
                source_links=hit.source_links,
                authority_claim=hit.authority_claim,
                matched_fields=hit.matched_fields,
                row_id=hit.row_id,
                metadata={**dict(hit.metadata), "degraded": "1"},
            )
        )
    return tuple(out)


# Re-export filter helper for callers that only import v2.
__all__ = [
    "HYBRID_RETRIEVAL_V2_CODE_VERSION",
    "HYBRID_RETRIEVAL_V2_INTERFACE",
    "HYBRID_RETRIEVAL_V2_SCHEMA_VERSION",
    "ComponentWeightError",
    "ComponentWeights",
    "DEFAULT_SNAPSHOT_CID",
    "ExplainableHit",
    "ExposedSourceSpan",
    "HybridRetrievalV2",
    "HybridRetrievalV2Error",
    "HybridSearchRequestV2",
    "HybridSearchResultV2",
    "MissingSourceSpanError",
    "ScoreComponent",
    "ScoreContribution",
    "SnapshotBinding",
    "apply_pre_ranking_filters",
    "assert_explainable_hits",
    "degrade_ranking",
    "fuse_explainable",
    "hybrid_search_v2",
    "ranking_digest_v2",
]
