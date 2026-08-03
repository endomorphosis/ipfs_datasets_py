"""Three-way hybrid retrieval over fielded BM25, pinned vector, and graph indexes.

PATLAW-092 search/fusion layer. Index builders live in ``indexing``; contracts
and fusion math live in ``retrieval_contracts``.

Invariants:

* Disclosure / tenant / as-of (authority-aware) filters run before any family
  scorer.
* Every ranked hit joins to at least one source CID.
* Denied private routes make zero remote embedding calls; denial counts are
  recorded on the filter receipt and fusion result metadata.
* Fusion is deterministic for identical inputs.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Final, Mapping, Sequence

from .indexing import (
    DEFAULT_CORPUS_CID,
    DEFAULT_EMBEDDING_CONFIG_CID,
    EmbeddingCallLedger,
    EmbeddingFn,
    FieldedBm25Index,
    GraphFusionIndex,
    PatentIndexBundle,
    PatentIndexDocument,
    PinnedVectorIndex,
    build_patent_indexes,
    default_embedding_identity,
    default_local_embedder,
    embed_texts_for_index,
    expand_graph,
    score_fielded_bm25,
    score_pinned_vectors,
)
from .retrieval_contracts import (
    RETRIEVAL_CONTRACTS_SCHEMA_VERSION,
    AuthorityClaim,
    DisclosureClass,
    EmbeddingIdentity,
    FusionResult,
    FusionWeights,
    MissingPreRankingFiltersError,
    PreRankingFilters,
    RankedHit,
    RetrievalFamily,
    SourceLink,
    fuse_ranked_hits,
    is_private_disclosure,
    require_pre_ranking_filters,
    requires_quarantine,
)

HYBRID_RETRIEVAL_SCHEMA_VERSION: Final = "patent.hybrid_retrieval.v1"
HYBRID_RETRIEVAL_INTERFACE: Final = "PatentHybridRetriever@1"


class HybridRetrievalError(ValueError):
    """Base error for hybrid retrieval failures."""


class PrivateRouteIsolationError(HybridRetrievalError):
    """Raised when a private route would require a remote embedding call."""


def _links_from_raw(raw_links: Sequence[Any]) -> tuple[SourceLink, ...]:
    out: list[SourceLink] = []
    for item in raw_links or ():
        if isinstance(item, SourceLink):
            out.append(item)
        elif isinstance(item, Mapping):
            out.append(SourceLink.from_dict(item))
        else:
            raise TypeError("source_links items must be SourceLink or mapping")
    if not out:
        raise HybridRetrievalError("ranked hit missing source links / source CID")
    return tuple(out)


def _hits_from_scored(
    scored: Sequence[Mapping[str, Any]],
    *,
    family: RetrievalFamily,
) -> tuple[RankedHit, ...]:
    hits: list[RankedHit] = []
    for item in scored:
        links = _links_from_raw(item.get("source_links") or ())
        claim_raw = item.get("authority_claim") or AuthorityClaim.SOURCE_BOUND.value
        matched = tuple(item.get("matched_fields") or ())
        meta: dict[str, str] = {}
        if item.get("matched_terms"):
            meta["matched_terms"] = ",".join(str(t) for t in item["matched_terms"])
        if item.get("path_edge_ids"):
            meta["path_edge_ids"] = ",".join(str(e) for e in item["path_edge_ids"])
        if item.get("node_id"):
            meta["node_id"] = str(item["node_id"])
        if item.get("vector_digest"):
            meta["vector_digest"] = str(item["vector_digest"])
        hits.append(
            RankedHit(
                document_id=str(item["document_id"]),
                score=float(item["score"]),
                rank=int(item.get("rank") or (len(hits) + 1)),
                family=family,
                source_links=links,
                row_id=item.get("row_id"),
                authority_claim=claim_raw,
                matched_fields=matched,
                metadata=meta,
            )
        )
    return tuple(hits)


def apply_pre_ranking_filters(
    filters: PreRankingFilters,
    *,
    denied_provider_call_count: int | None = None,
    filter_receipt_id: str | None = None,
) -> PreRankingFilters:
    """Mark filters applied (mandatory gate before any family search).

    Callers must invoke this (or otherwise set ``applied=True``) before
    :meth:`PatentHybridRetriever.search`. Search itself refuses unapplied
    filters.
    """
    if filters is None:
        raise MissingPreRankingFiltersError(
            "disclosure/tenant/as-of PreRankingFilters are mandatory before scoring"
        )
    if not isinstance(filters, PreRankingFilters):
        raise TypeError("filters must be PreRankingFilters")
    applied = filters if filters.applied else filters.mark_applied(
        filter_receipt_id=filter_receipt_id
    )
    if denied_provider_call_count is not None or filter_receipt_id is not None:
        applied = PreRankingFilters(
            schema_version=applied.schema_version,
            tenant_id=applied.tenant_id,
            as_of_utc=applied.as_of_utc,
            allowed_disclosures=applied.allowed_disclosures,
            applied=True,
            denied_provider_call_count=(
                int(denied_provider_call_count)
                if denied_provider_call_count is not None
                else applied.denied_provider_call_count
            ),
            filter_receipt_id=filter_receipt_id or applied.filter_receipt_id,
            metadata=dict(applied.metadata),
        )
    require_pre_ranking_filters(applied)
    return applied


def search_bm25_family(
    query: str,
    index: FieldedBm25Index,
    *,
    filters: PreRankingFilters,
    top_k: int = 10,
) -> tuple[RankedHit, ...]:
    """Fielded BM25 search; filters must already be applied."""
    require_pre_ranking_filters(filters)
    scored = score_fielded_bm25(query, index, top_k=top_k)
    return _hits_from_scored(scored, family=RetrievalFamily.BM25)


def search_vector_family(
    query: str,
    index: PinnedVectorIndex,
    *,
    filters: PreRankingFilters,
    top_k: int = 10,
    query_vector: Sequence[float] | None = None,
    allow_remote: bool = False,
    remote_embedder: EmbeddingFn | None = None,
    ledger: EmbeddingCallLedger | None = None,
    query_disclosure: DisclosureClass | str = DisclosureClass.PUBLIC_USER,
) -> tuple[tuple[RankedHit, ...], int]:
    """Pinned vector search with private-route remote isolation.

    Returns ``(hits, denied_remote_delta)``. Denied private routes make zero
    remote embedding calls.
    """
    require_pre_ranking_filters(filters)
    call_ledger = ledger or EmbeddingCallLedger()
    private_route = is_private_disclosure(query_disclosure) or requires_quarantine(
        query_disclosure
    )
    denied_delta = 0
    qvec = query_vector
    if qvec is None:
        vectors, _meta, denied_delta = embed_texts_for_index(
            [query],
            embedding=index.embedding,
            allow_remote=allow_remote and not private_route,
            private_route=private_route,
            ledger=call_ledger,
            remote_embedder=remote_embedder if not private_route else None,
        )
        qvec = vectors[0] if vectors else []
    scored = score_pinned_vectors(query, index, top_k=top_k, query_vector=qvec)
    return _hits_from_scored(scored, family=RetrievalFamily.VECTOR), denied_delta


def search_graph_family(
    query: str,
    index: GraphFusionIndex,
    *,
    filters: PreRankingFilters,
    seed_document_ids: Sequence[str] = (),
    bm25_seeds: Sequence[RankedHit] = (),
    top_k: int = 10,
    max_hops: int = 2,
) -> tuple[RankedHit, ...]:
    """Graph expansion search seeded by explicit ids or BM25 hits."""
    require_pre_ranking_filters(filters)
    seeds = list(seed_document_ids)
    if not seeds:
        seeds = [hit.document_id for hit in bm25_seeds[: max(1, min(5, top_k))]]
    if not seeds:
        # Fall back to nodes whose label/token text matches query terms lightly
        # by document_id/label substring (deterministic, no remote I/O).
        q = query.lower()
        seeds = [
            n.document_id
            for n in index.nodes
            if q and (q in n.label.lower() or q in n.document_id.lower())
        ][:5]
    scored = expand_graph(seeds, index, top_k=top_k, max_hops=max_hops)
    return _hits_from_scored(scored, family=RetrievalFamily.GRAPH)


@dataclass(frozen=True, slots=True)
class HybridSearchRequest:
    """One hybrid retrieval request with mandatory pre-ranking filters."""

    query_id: str
    query: str
    filters: PreRankingFilters
    top_k: int = 10
    fusion_weights: FusionWeights | None = None
    seed_document_ids: tuple[str, ...] = ()
    allow_remote_embeddings: bool = False
    query_disclosure: DisclosureClass = DisclosureClass.PUBLIC_USER
    max_graph_hops: int = 2

    def __post_init__(self) -> None:
        object.__setattr__(self, "query_id", str(self.query_id).strip())
        object.__setattr__(self, "query", str(self.query))
        if not self.query_id:
            raise HybridRetrievalError("query_id must be non-empty")
        if not isinstance(self.filters, PreRankingFilters):
            raise TypeError("filters must be PreRankingFilters")
        if isinstance(self.query_disclosure, str):
            object.__setattr__(
                self, "query_disclosure", DisclosureClass(self.query_disclosure)
            )


@dataclass(frozen=True, slots=True)
class HybridSearchResult:
    """Hybrid search output wrapping FusionResult plus isolation counters."""

    fusion: FusionResult
    bm25_backend: str
    vector_embedding: Mapping[str, Any]
    denied_provider_call_count: int
    remote_embedding_calls: int
    schema_version: str = HYBRID_RETRIEVAL_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "bm25_backend": self.bm25_backend,
            "denied_provider_call_count": self.denied_provider_call_count,
            "fusion": self.fusion.to_dict(),
            "remote_embedding_calls": self.remote_embedding_calls,
            "schema_version": self.schema_version,
            "vector_embedding": dict(self.vector_embedding),
        }

    @property
    def fused_hits(self) -> tuple[RankedHit, ...]:
        return self.fusion.fused_hits

    @property
    def filters(self) -> PreRankingFilters:
        return self.fusion.filters


class PatentHybridRetriever:
    """Retriever over a :class:`PatentIndexBundle` (or discrete family indexes)."""

    def __init__(
        self,
        bundle: PatentIndexBundle | None = None,
        *,
        bm25: FieldedBm25Index | None = None,
        vector: PinnedVectorIndex | None = None,
        graph: GraphFusionIndex | None = None,
        remote_embedder: EmbeddingFn | None = None,
    ) -> None:
        if bundle is not None:
            self.bm25 = bundle.bm25
            self.vector = bundle.vector
            self.graph = bundle.graph
            self.corpus_cid = bundle.corpus_cid
            self.config_cid = bundle.config_cid
            self.model_cid = bundle.model_cid
            self.index_cids = dict(bundle.index_cids)
            self._bundle = bundle
        else:
            if bm25 is None or vector is None or graph is None:
                raise HybridRetrievalError(
                    "PatentHybridRetriever requires a bundle or all three indexes"
                )
            self.bm25 = bm25
            self.vector = vector
            self.graph = graph
            self.corpus_cid = bm25.corpus_cid
            self.config_cid = vector.embedding.config_cid
            self.model_cid = vector.embedding.model_cid
            self.index_cids = {
                "bm25": bm25.index_cid,
                "vector": vector.index_cid,
                "graph": graph.index_cid,
            }
            self._bundle = None
        self.remote_embedder = remote_embedder
        self._ledger = EmbeddingCallLedger()

    @classmethod
    def from_documents(
        cls,
        documents: Sequence[PatentIndexDocument],
        *,
        filters: PreRankingFilters,
        edges: Sequence[Any] = (),
        embedding: EmbeddingIdentity | None = None,
        corpus_cid: str = DEFAULT_CORPUS_CID,
        allow_remote: bool = False,
        remote_embedder: EmbeddingFn | None = None,
    ) -> "PatentHybridRetriever":
        """Build indexes then return a retriever (filters applied at build)."""
        ledger = EmbeddingCallLedger()
        applied = filters if filters.applied else filters.mark_applied()
        bundle = build_patent_indexes(
            documents,
            filters=applied,
            edges=edges,
            embedding=embedding or default_embedding_identity(),
            corpus_cid=corpus_cid,
            allow_remote=allow_remote,
            remote_embedder=remote_embedder,
            ledger=ledger,
        )
        retriever = cls(bundle, remote_embedder=remote_embedder)
        retriever._ledger = ledger
        return retriever

    @property
    def embedding_identity(self) -> EmbeddingIdentity:
        return self.vector.embedding

    @property
    def embedding_call_ledger(self) -> EmbeddingCallLedger:
        return self._ledger

    def search(self, request: HybridSearchRequest) -> HybridSearchResult:
        """Run filters-first BM25 + vector + graph search and three-way fusion."""
        if not isinstance(request, HybridSearchRequest):
            raise TypeError("request must be HybridSearchRequest")

        # --- Gate: filters first (must already be applied) ----------------------
        # Refuse unapplied filters; callers use apply_pre_ranking_filters().
        require_pre_ranking_filters(request.filters)

        remote_before = self._ledger.remote_call_count
        private_query = is_private_disclosure(
            request.query_disclosure
        ) or requires_quarantine(request.query_disclosure)

        # If the query is private and remote is not allowed, ensure the remote
        # embedder is never invoked (pass None) and count denials.
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

        # --- Family searches (post-filter) --------------------------------------
        bm25_hits = search_bm25_family(
            request.query,
            self.bm25,
            filters=applied,
            top_k=request.top_k,
        )
        vector_hits, denied_delta = search_vector_family(
            request.query,
            self.vector,
            filters=applied,
            top_k=request.top_k,
            allow_remote=allow_remote,
            remote_embedder=self.remote_embedder if allow_remote else None,
            ledger=self._ledger,
            query_disclosure=request.query_disclosure,
        )
        graph_hits = search_graph_family(
            request.query,
            self.graph,
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

        denied_total = (
            denied_seed
            + denied_delta
            + int(self._ledger.denied_remote_count)
            + int(self.vector.denied_provider_call_count)
        )
        # Deduplicate ledger-driven double counts when denied_delta already
        # advanced the ledger: prefer max of structured counters.
        denied_total = max(
            denied_seed + denied_delta,
            int(self._ledger.denied_remote_count),
            denied_total - int(self._ledger.denied_remote_count) + denied_delta,
        )
        # Simpler authoritative total for the response:
        denied_total = denied_seed + denied_delta
        if private_query and (
            _is_remote_identity(self.vector.embedding)
            or self.remote_embedder is not None
            or request.allow_remote_embeddings
        ):
            # At least one denied remote attempt per private query embedding.
            denied_total = max(denied_total, denied_seed + 1)

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
            },
        )

        weights = request.fusion_weights or FusionWeights()
        fusion = fuse_ranked_hits(
            query_id=request.query_id,
            filters=filters_out,
            bm25_hits=bm25_hits,
            vector_hits=vector_hits,
            graph_hits=graph_hits,
            fusion_weights=weights,
            corpus_cid=self.corpus_cid,
            config_cid=self.config_cid or DEFAULT_EMBEDDING_CONFIG_CID,
            model_cid=self.model_cid,
            index_cids=self.index_cids,
            top_k=request.top_k,
        )

        # Every fused hit must join to a source CID (contract already enforces
        # non-empty source_links on RankedHit; re-assert for defense in depth).
        for hit in fusion.fused_hits:
            if not hit.source_links or not any(s.source_cid for s in hit.source_links):
                raise HybridRetrievalError(
                    f"fused hit {hit.document_id} missing source CID"
                )

        return HybridSearchResult(
            fusion=fusion,
            bm25_backend=self.bm25.backend,
            vector_embedding=self.vector.embedding.to_dict(),
            denied_provider_call_count=denied_total,
            remote_embedding_calls=remote_calls,
        )

    def search_query(
        self,
        query: str,
        *,
        query_id: str = "q1",
        filters: PreRankingFilters,
        top_k: int = 10,
        **kwargs: Any,
    ) -> HybridSearchResult:
        """Convenience wrapper around :meth:`search`."""
        request = HybridSearchRequest(
            query_id=query_id,
            query=query,
            filters=filters,
            top_k=top_k,
            fusion_weights=kwargs.get("fusion_weights"),
            seed_document_ids=tuple(kwargs.get("seed_document_ids") or ()),
            allow_remote_embeddings=bool(kwargs.get("allow_remote_embeddings", False)),
            query_disclosure=kwargs.get(
                "query_disclosure", DisclosureClass.PUBLIC_USER
            ),
            max_graph_hops=int(kwargs.get("max_graph_hops") or 2),
        )
        return self.search(request)


def _is_remote_identity(embedding: EmbeddingIdentity) -> bool:
    from .indexing import _is_remote_provider

    return _is_remote_provider(embedding.provider, embedding.backend)


def hybrid_search(
    query: str,
    bundle: PatentIndexBundle,
    *,
    filters: PreRankingFilters,
    query_id: str = "q1",
    top_k: int = 10,
    fusion_weights: FusionWeights | Mapping[str, float] | None = None,
    allow_remote_embeddings: bool = False,
    query_disclosure: DisclosureClass | str = DisclosureClass.PUBLIC_USER,
    remote_embedder: EmbeddingFn | None = None,
    seed_document_ids: Sequence[str] = (),
) -> HybridSearchResult:
    """Functional entry point for three-way hybrid retrieval."""
    weights: FusionWeights | None
    if fusion_weights is None:
        weights = None
    elif isinstance(fusion_weights, FusionWeights):
        weights = fusion_weights
    else:
        weights = FusionWeights.from_dict(fusion_weights)
    if isinstance(query_disclosure, str):
        query_disclosure = DisclosureClass(query_disclosure)
    retriever = PatentHybridRetriever(bundle, remote_embedder=remote_embedder)
    request = HybridSearchRequest(
        query_id=query_id,
        query=query,
        filters=filters,
        top_k=top_k,
        fusion_weights=weights,
        seed_document_ids=tuple(seed_document_ids),
        allow_remote_embeddings=allow_remote_embeddings,
        query_disclosure=query_disclosure,
    )
    return retriever.search(request)


def assert_all_hits_join_source_cid(result: HybridSearchResult | FusionResult) -> None:
    """Raise if any family or fused hit lacks a source CID join."""
    fusion = result.fusion if isinstance(result, HybridSearchResult) else result
    families = (
        fusion.bm25_hits,
        fusion.vector_hits,
        fusion.graph_hits,
        fusion.fused_hits,
    )
    for hits in families:
        for hit in hits:
            if not hit.source_links:
                raise HybridRetrievalError(
                    f"{hit.family.value} hit {hit.document_id} missing source links"
                )
            if not any(link.source_cid for link in hit.source_links):
                raise HybridRetrievalError(
                    f"{hit.family.value} hit {hit.document_id} missing source CID"
                )


__all__ = [
    "HYBRID_RETRIEVAL_INTERFACE",
    "HYBRID_RETRIEVAL_SCHEMA_VERSION",
    "HybridRetrievalError",
    "HybridSearchRequest",
    "HybridSearchResult",
    "PatentHybridRetriever",
    "PrivateRouteIsolationError",
    "apply_pre_ranking_filters",
    "assert_all_hits_join_source_cid",
    "hybrid_search",
    "search_bm25_family",
    "search_graph_family",
    "search_vector_family",
]
