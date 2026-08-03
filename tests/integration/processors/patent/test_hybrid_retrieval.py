"""Integration tests for hybrid BM25 + vector + graph fusion (PATLAW-092)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.domains.patent.hybrid_retrieval import (
    HYBRID_RETRIEVAL_SCHEMA_VERSION,
    HybridSearchRequest,
    PatentHybridRetriever,
    PrivateRouteIsolationError,
    apply_pre_ranking_filters,
    assert_all_hits_join_source_cid,
    hybrid_search,
)
from ipfs_datasets_py.processors.domains.patent.indexing import (
    DEFAULT_EMBEDDING_CONFIG_CID,
    EmbeddingCallLedger,
    PatentIndexDocument,
    build_patent_indexes,
    default_embedding_identity,
    legal_tokens_present,
    tokenize_patent_text,
)
from ipfs_datasets_py.processors.domains.patent.retrieval_contracts import (
    RETRIEVAL_CONTRACTS_SCHEMA_VERSION,
    DisclosureClass,
    EmbeddingIdentity,
    FusionWeights,
    MissingPreRankingFiltersError,
    PreRankingFilters,
    RetrievalFamily,
    canonical_json,
)

FIXTURE_PATH = (
    Path(__file__).resolve().parents[3]
    / "fixtures"
    / "patent"
    / "retrieval"
    / "golden_case.json"
)


def _load_golden() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _filters_from_golden(data: dict, *, applied: bool = True) -> PreRankingFilters:
    return PreRankingFilters(
        schema_version=RETRIEVAL_CONTRACTS_SCHEMA_VERSION,
        tenant_id=data["tenant_id"],
        as_of_utc=data["as_of_utc"],
        allowed_disclosures=tuple(data["allowed_disclosures"]),
        applied=applied,
        filter_receipt_id="filter:golden",
    )


def _bundle_from_golden(data: dict | None = None):
    data = data or _load_golden()
    docs = [PatentIndexDocument.from_dict(d) for d in data["documents"]]
    filters = _filters_from_golden(data, applied=True)
    emb_cfg = data.get("embedding") or {}
    embedding = default_embedding_identity(
        config_cid=data.get("config_cid") or DEFAULT_EMBEDDING_CONFIG_CID,
        model_cid=data.get("model_cid"),
        dimension=int(emb_cfg.get("dimension") or 256),
        provider=str(emb_cfg.get("provider") or "local_hash"),
        model_id=str(emb_cfg.get("model_id") or "hashed-term-patent-v1"),
        model_version=str(emb_cfg.get("model_version") or "1.0.0"),
        backend=str(emb_cfg.get("backend") or "pinned"),
    )
    return build_patent_indexes(
        docs,
        filters=filters,
        edges=data.get("edges") or [],
        embedding=embedding,
        corpus_cid=data["corpus_cid"],
        allow_remote=False,
    ), data


def test_hybrid_retrieval_filters_first_and_fuses_families() -> None:
    bundle, data = _bundle_from_golden()
    query = data["queries"][0]
    filters = _filters_from_golden(data, applied=True)

    # Unapplied filters must fail closed before scoring.
    with pytest.raises(MissingPreRankingFiltersError):
        hybrid_search(
            query["query"],
            bundle,
            filters=_filters_from_golden(data, applied=False),
            query_id=query["query_id"],
        )

    result = hybrid_search(
        query["query"],
        bundle,
        filters=filters,
        query_id=query["query_id"],
        top_k=5,
        fusion_weights=FusionWeights(bm25=1.0, vector=1.0, graph=0.5),
    )
    assert result.schema_version == HYBRID_RETRIEVAL_SCHEMA_VERSION
    assert result.fusion.filters.applied is True
    assert result.fusion.fused_hits
    assert result.fusion.fused_hits[0].family is RetrievalFamily.FUSION
    assert result.fusion.fused_hits[0].document_id == query["expected_top_document_id"]
    assert result.bm25_backend == "fielded_bm25"
    # Embedding provider/model/config recorded on the result surface.
    emb = result.vector_embedding
    assert emb["provider"]
    assert emb["model_id"]
    assert emb["config_cid"] == data["config_cid"]
    assert emb.get("model_cid") == data["model_cid"]
    # Every family + fused hit joins to a source CID.
    assert_all_hits_join_source_cid(result)
    for hit in result.fusion.fused_hits:
        assert hit.source_links[0].source_cid
    # Fusion binds corpus/config/index CIDs.
    assert result.fusion.corpus_cid == data["corpus_cid"]
    assert result.fusion.config_cid == data["config_cid"]
    assert "bm25" in result.fusion.index_cids
    assert "vector" in result.fusion.index_cids
    assert "graph" in result.fusion.index_cids


def test_hybrid_legal_tokens_drive_bm25_ranking() -> None:
    bundle, data = _bundle_from_golden()
    query = data["queries"][0]
    tokens = tokenize_patent_text(query["query"])
    protected = legal_tokens_present(query["query"])
    assert protected
    for token in protected:
        assert token in tokens

    retriever = PatentHybridRetriever(bundle)
    result = retriever.search(
        HybridSearchRequest(
            query_id=query["query_id"],
            query=query["query"],
            filters=_filters_from_golden(data, applied=True),
            top_k=5,
        )
    )
    assert result.fusion.bm25_hits
    assert result.fusion.bm25_hits[0].document_id == query["expected_top_document_id"]
    # Graph expansion should surface the cited network patent via the edge.
    graph_ids = {h.document_id for h in result.fusion.graph_hits}
    assert "doc:patent-encode" in graph_ids or "doc:patent-network" in graph_ids


def test_hybrid_repeat_search_identical() -> None:
    bundle, data = _bundle_from_golden()
    query = data["queries"][0]
    filters = _filters_from_golden(data, applied=True)
    request = HybridSearchRequest(
        query_id=query["query_id"],
        query=query["query"],
        filters=filters,
        top_k=5,
        fusion_weights=FusionWeights(bm25=1.0, vector=0.8, graph=0.5),
    )
    retriever = PatentHybridRetriever(bundle)
    first = retriever.search(request)
    second = retriever.search(request)
    assert canonical_json(first.fusion.to_dict()) == canonical_json(
        second.fusion.to_dict()
    )
    assert first.denied_provider_call_count == second.denied_provider_call_count


def test_hybrid_excludes_private_and_future_rows() -> None:
    bundle, data = _bundle_from_golden()
    # Index build already filtered; ensure private/future never appear in hits.
    result = hybrid_search(
        "method claim patent",
        bundle,
        filters=_filters_from_golden(data, applied=True),
        query_id="q-broad",
        top_k=10,
    )
    all_ids = {
        h.document_id
        for family in (
            result.fusion.bm25_hits,
            result.fusion.vector_hits,
            result.fusion.graph_hits,
            result.fusion.fused_hits,
        )
        for h in family
    }
    assert "doc:private-draft" not in all_ids
    assert "doc:future-rule" not in all_ids
    assert all_ids <= {"doc:patent-encode", "doc:patent-network"}


def test_denied_private_query_route_zero_remote_embedding_calls() -> None:
    bundle, data = _bundle_from_golden()
    remote_calls = {"n": 0}

    def remote_embedder(texts):
        remote_calls["n"] += len(list(texts))
        dim = bundle.vector.embedding.dimension
        return [[0.01] * dim for _ in texts], {
            "backend": "embeddings_router",
            "provider": "openai",
        }

    # Rebuild with a remote-capable identity so denial path is meaningful.
    docs = [PatentIndexDocument.from_dict(d) for d in data["documents"]]
    remote_identity = EmbeddingIdentity(
        schema_version=RETRIEVAL_CONTRACTS_SCHEMA_VERSION,
        provider="openai",
        model_id="text-embedding-3-small",
        model_version="1",
        dimension=64,
        config_cid=data["config_cid"],
        model_cid=data["model_cid"],
        backend="embeddings_router",
    )
    ledger = EmbeddingCallLedger()
    private_filters = PreRankingFilters(
        schema_version=RETRIEVAL_CONTRACTS_SCHEMA_VERSION,
        tenant_id=data["tenant_id"],
        as_of_utc=data["as_of_utc"],
        allowed_disclosures=(
            DisclosureClass.PUBLIC_OFFICIAL,
            DisclosureClass.PUBLIC_USER,
            DisclosureClass.CONFIDENTIAL_APPLICATION,
        ),
        applied=True,
        filter_receipt_id="filter:private-query",
    )
    bundle_remote = build_patent_indexes(
        docs,
        filters=private_filters,
        edges=data.get("edges") or [],
        embedding=remote_identity,
        corpus_cid=data["corpus_cid"],
        allow_remote=True,
        remote_embedder=remote_embedder,
        ledger=ledger,
    )
    # Build may have called remote for public docs only.
    build_remote = remote_calls["n"]
    assert ledger.denied_remote_count >= 1  # private draft denied at build

    retriever = PatentHybridRetriever(
        bundle_remote, remote_embedder=remote_embedder
    )
    # Query over private disclosure must not add remote calls.
    before = remote_calls["n"]
    result = retriever.search(
        HybridSearchRequest(
            query_id="q-private",
            query="secret claim language",
            filters=private_filters,
            top_k=5,
            allow_remote_embeddings=True,
            query_disclosure=DisclosureClass.CONFIDENTIAL_APPLICATION,
        )
    )
    after = remote_calls["n"]
    assert after == before, "denied private query route must make zero remote embedding calls"
    assert result.remote_embedding_calls == 0
    assert result.denied_provider_call_count >= 1
    # Embedding identity still recorded.
    assert result.vector_embedding["provider"] == "openai"
    assert result.vector_embedding["config_cid"] == data["config_cid"]
    assert_all_hits_join_source_cid(result)
    # Sanity: build remote count unchanged by search.
    assert build_remote == before


def test_retriever_from_documents_end_to_end() -> None:
    data = _load_golden()
    docs = [PatentIndexDocument.from_dict(d) for d in data["documents"]]
    filters = _filters_from_golden(data, applied=False)
    # from_documents should apply filters during build.
    retriever = PatentHybridRetriever.from_documents(
        docs,
        filters=filters,
        edges=data.get("edges") or [],
        corpus_cid=data["corpus_cid"],
    )
    applied = apply_pre_ranking_filters(filters)
    result = retriever.search_query(
        data["queries"][0]["query"],
        query_id=data["queries"][0]["query_id"],
        filters=applied,
        top_k=3,
    )
    assert result.fusion.fused_hits
    assert result.fusion.fused_hits[0].document_id == data["queries"][0][
        "expected_top_document_id"
    ]
    assert retriever.embedding_identity.provider
    assert retriever.embedding_identity.model_id
    assert retriever.embedding_identity.config_cid


def test_bundle_repeat_build_matches_for_hybrid() -> None:
    data = _load_golden()
    a, _ = _bundle_from_golden(data)
    b, _ = _bundle_from_golden(data)
    assert a.bundle_digest == b.bundle_digest
    r1 = hybrid_search(
        data["queries"][0]["query"],
        a,
        filters=_filters_from_golden(data, applied=True),
        query_id="q-rep",
    )
    r2 = hybrid_search(
        data["queries"][0]["query"],
        b,
        filters=_filters_from_golden(data, applied=True),
        query_id="q-rep",
    )
    assert [h.document_id for h in r1.fusion.fused_hits] == [
        h.document_id for h in r2.fusion.fused_hits
    ]
