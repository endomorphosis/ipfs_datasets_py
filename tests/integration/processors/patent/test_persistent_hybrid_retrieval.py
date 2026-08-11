"""Integration tests for explainable hybrid retrieval + real-corpus eval (PATLAW-147).

Acceptance coverage
-------------------
* Versioned thresholds fail on intentionally degraded retrieval
* Each result exposes source spans and score contributions
* Receipts bind snapshot / model / config / qrels
* Isolation tests count zero denied calls/results (public local path)
* Missing source coverage is reported rather than scored as searched
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.domains.patent.evaluation import (
    EVALUATION_SCHEMA_VERSION,
    REQUIRED_METRIC_KINDS,
    MetricKind,
    MetricThresholdError,
    MetricThresholds,
)
from ipfs_datasets_py.processors.domains.patent.hybrid_retrieval_v2 import (
    HYBRID_RETRIEVAL_V2_INTERFACE,
    HYBRID_RETRIEVAL_V2_SCHEMA_VERSION,
    ComponentWeights,
    HybridRetrievalV2,
    HybridSearchRequestV2,
    ScoreComponent,
    SnapshotBinding,
    assert_explainable_hits,
    degrade_ranking,
    hybrid_search_v2,
)
from ipfs_datasets_py.processors.domains.patent.index_store import PatentIndexStore
from ipfs_datasets_py.processors.domains.patent.indexing import (
    PatentIndexDocument,
    build_patent_indexes,
    default_embedding_identity,
)
from ipfs_datasets_py.processors.domains.patent.index_snapshot_contracts import (
    PartitionClass,
)
from ipfs_datasets_py.processors.domains.patent.persistent_index_builder import (
    PersistentIndexBuilder,
)
from ipfs_datasets_py.processors.domains.patent.retrieval_contracts import (
    RETRIEVAL_CONTRACTS_SCHEMA_VERSION,
    DisclosureClass,
    EmbeddingIdentity,
    MissingPreRankingFiltersError,
    PreRankingFilters,
    RetrievalFamily,
    is_private_disclosure,
)
from ipfs_datasets_py.processors.domains.patent.retrieval_evaluation_v2 import (
    DEFAULT_QRELS_V2_CID,
    DEFAULT_THRESHOLDS_V2_CID,
    FIXTURE_V2_SCHEMA_VERSION,
    RETRIEVAL_EVAL_V2_SCHEMA_VERSION,
    PatentRetrievalEvaluatorV2,
    SourceCoverageStatus,
    build_bundle_from_gold_corpus,
    build_source_coverage_report,
    default_fixture_v2_path,
    evaluate_hybrid_v2_against_qrels,
    load_evaluation_fixture_v2,
    load_qrel_set_v2,
)
from ipfs_datasets_py.processors.domains.patent.retrieval_eval import (
    row_effective_from_documents,
)

FIXTURE_DIR = (
    Path(__file__).resolve().parents[3] / "fixtures" / "patent" / "retrieval"
)
QRELS_V2_PATH = FIXTURE_DIR / "qrels_v2.json"
GOLDEN_PATH = FIXTURE_DIR / "golden_case.json"

CID_CORPUS = "bafybeigdyrzt5sfp7udm7hu76uh7y26nf3efuylqabf3oclgtqy55fbzdi"
CID_CONFIG = "bafybeihdwdcefgh4dqkjv67uzcmw7ojee6xedzdetojuzjevtenxquvyku"
CID_MODEL = "bafybeimodelidentity000000000000000000000000000000000000001"
TENANT = "tenant-public"
CREATED = "2024-06-01T00:00:00Z"
SOURCE_VERSION = "v2024.1"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _filters_from_gold(
    data: dict, *, applied: bool = True, denied: int = 0
) -> PreRankingFilters:
    return PreRankingFilters(
        schema_version=RETRIEVAL_CONTRACTS_SCHEMA_VERSION,
        tenant_id=data["tenant_id"],
        as_of_utc=data["as_of_utc"],
        allowed_disclosures=tuple(data["allowed_disclosures"]),
        applied=applied,
        denied_provider_call_count=denied,
        filter_receipt_id="filter:persistent-hybrid-v2",
    )


def _load_gold() -> dict:
    return json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))


def _docs_from_gold(data: dict | None = None) -> list[PatentIndexDocument]:
    data = data or _load_gold()
    return [PatentIndexDocument.from_dict(d) for d in data["documents"]]


def _build_persistent_retriever(
    tmp_path: Path,
    *,
    data: dict | None = None,
) -> tuple[HybridRetrievalV2, dict, object]:
    """Build a durable snapshot then return a HybridRetrievalV2 bound to it."""
    data = data or _load_gold()
    docs = _docs_from_gold(data)
    # Persist only public-partition documents (private docs need encryption keys
    # and must not collapse into the public snapshot root).
    public_docs = [
        d for d in docs if not is_private_disclosure(d.disclosure)
    ]
    filters = _filters_from_gold(data, applied=True)

    store = PatentIndexStore.open_for_tenant(tmp_path / "index-store", TENANT)
    builder = PersistentIndexBuilder(
        store,
        shard_size=2,
        default_source_version=SOURCE_VERSION,
        created_utc=CREATED,
    )
    build = builder.build_full(
        public_docs,
        filters=filters,
        snapshot_id="snap:hybrid-v2",
        corpus_cid=data["corpus_cid"],
        corpus_version="corpus-2024.06",
        config_cid=data["config_cid"],
        partition=PartitionClass.PUBLIC,
        edges=data.get("edges") or [],
    )
    assert build.incomplete is False
    assert build.root_cid

    emb_cfg = data.get("embedding") or {}
    embedding = default_embedding_identity(
        config_cid=data.get("config_cid") or CID_CONFIG,
        model_cid=data.get("model_cid") or CID_MODEL,
        dimension=int(emb_cfg.get("dimension") or 256),
        provider=str(emb_cfg.get("provider") or "local_hash"),
        model_id=str(emb_cfg.get("model_id") or "hashed-term-patent-v1"),
        model_version=str(emb_cfg.get("model_version") or "1.0.0"),
        backend=str(emb_cfg.get("backend") or "pinned"),
    )
    # Searchable materialization remains the in-memory bundle projected from
    # the same admitted documents that were persisted (snapshot binds identity).
    bundle = build_patent_indexes(
        docs,
        filters=filters,
        edges=data.get("edges") or [],
        embedding=embedding,
        corpus_cid=data["corpus_cid"],
        allow_remote=False,
    )
    binding = SnapshotBinding(
        snapshot_cid=build.root_cid,
        corpus_cid=data["corpus_cid"],
        model_cid=str(data.get("model_cid") or CID_MODEL),
        config_cid=str(data.get("config_cid") or CID_CONFIG),
        index_cids=dict(bundle.index_cids),
        logical_root_cid=build.logical_root_cid,
        model_pin="local-hashed-term-projection@1.0.0",
    )
    retriever = HybridRetrievalV2(bundle, binding=binding)
    return retriever, data, build


# ---------------------------------------------------------------------------
# Fixture load
# ---------------------------------------------------------------------------


def test_qrels_v2_fixture_loads_and_binds_corpus() -> None:
    fixture = load_evaluation_fixture_v2(QRELS_V2_PATH)
    assert fixture.schema_version == FIXTURE_V2_SCHEMA_VERSION
    assert fixture.qrel_set.qrels_cid == DEFAULT_QRELS_V2_CID
    gold = _load_gold()
    assert fixture.qrel_set.corpus_cid == gold["corpus_cid"]
    assert fixture.thresholds.thresholds_cid == DEFAULT_THRESHOLDS_V2_CID
    assert set(fixture.thresholds.minima) >= {m.value for m in REQUIRED_METRIC_KINDS}
    assert fixture.private_document_ids == ("doc:private-draft",)
    assert "foreign_patent_office" in fixture.unsearched_sources
    assert "non_patent_literature" in fixture.unsearched_sources
    assert any(q["query_id"] == "q-prior-art-102" for q in fixture.queries)
    qrels = load_qrel_set_v2(QRELS_V2_PATH)
    assert qrels.qrels_cid == fixture.qrel_set.qrels_cid
    assert qrels.relevant_document_ids("q-prior-art-102") == frozenset(
        {"doc:patent-encode", "doc:patent-network"}
    )
    assert default_fixture_v2_path().name == "qrels_v2.json"


# ---------------------------------------------------------------------------
# Persistent hybrid search: spans + contributions
# ---------------------------------------------------------------------------


def test_persistent_hybrid_exposes_source_spans_and_score_contributions(
    tmp_path: Path,
) -> None:
    retriever, data, build = _build_persistent_retriever(tmp_path)
    filters = _filters_from_gold(data, applied=True)
    query = data["queries"][0]

    # Unapplied filters fail closed before scoring.
    with pytest.raises(MissingPreRankingFiltersError):
        retriever.search(
            HybridSearchRequestV2(
                query_id=query["query_id"],
                query=query["query"],
                filters=_filters_from_gold(data, applied=False),
            )
        )

    result = retriever.search(
        HybridSearchRequestV2(
            query_id=query["query_id"],
            query=query["query"],
            filters=filters,
            top_k=5,
            component_weights=ComponentWeights(
                bm25=1.0, vector=1.0, graph=0.5, cpc=0.15, ipc=0.15
            ),
            unsearched_sources=("foreign_patent_office", "non_patent_literature"),
        )
    )
    assert result.schema_version == HYBRID_RETRIEVAL_V2_SCHEMA_VERSION
    assert result.filters.applied is True
    assert result.hits
    assert result.hits[0].document_id == query["expected_top_document_id"]
    assert result.binding.snapshot_cid == build.root_cid
    assert result.binding.corpus_cid == data["corpus_cid"]
    assert result.binding.model_cid == data["model_cid"]
    assert result.binding.config_cid == data["config_cid"]
    assert result.unsearched_sources == (
        "foreign_patent_office",
        "non_patent_literature",
    )

    assert_explainable_hits(result)
    for hit in result.hits:
        # Source spans required on every hit.
        assert hit.source_spans
        for span in hit.source_spans:
            assert span.source_cid
            assert span.artifact_id
            assert span.span is not None
            assert span.span.end >= span.span.start
        # Score contributions required on every hit.
        assert hit.score_contributions
        components = {c.component for c in hit.score_contributions}
        # Primary families should appear for the gold hit.
        assert components & {
            ScoreComponent.BM25,
            ScoreComponent.VECTOR,
            ScoreComponent.GRAPH,
        }
        for contrib in hit.score_contributions:
            assert contrib.weight >= 0.0
            assert contrib.normalized_score >= 0.0
            # contribution == weight * normalized (within float tolerance)
            assert abs(contrib.contribution - contrib.weight * contrib.normalized_score) < 1e-9
        # Contribution map surface.
        assert hit.contribution_map

    # Gold hit should surface CPC field contribution for G06F16/00 query.
    top = result.hits[0]
    assert top.document_id == "doc:patent-encode"
    top_components = {c.component for c in top.score_contributions}
    assert ScoreComponent.CPC in top_components or "cpc" in {
        f.lower() for f in top.matched_fields
    }


def test_hybrid_search_v2_functional_entry(tmp_path: Path) -> None:
    retriever, data, _build = _build_persistent_retriever(tmp_path)
    filters = _filters_from_gold(data, applied=True)
    query = data["queries"][0]
    result = hybrid_search_v2(
        query["query"],
        retriever.bundle,
        filters=filters,
        query_id=query["query_id"],
        top_k=5,
        snapshot_cid=retriever.snapshot_cid,
    )
    assert result.schema_version == HYBRID_RETRIEVAL_V2_SCHEMA_VERSION
    assert result.hits
    assert_explainable_hits(result)


# ---------------------------------------------------------------------------
# Evaluation against qrels_v2
# ---------------------------------------------------------------------------


def test_evaluate_persistent_hybrid_against_qrels_v2(tmp_path: Path) -> None:
    fixture = load_evaluation_fixture_v2(QRELS_V2_PATH)
    retriever, data, build = _build_persistent_retriever(tmp_path)
    filters = _filters_from_gold(data, applied=True)
    docs = _docs_from_gold(data)
    row_effective = row_effective_from_documents(docs)

    evaluator = PatentRetrievalEvaluatorV2(fixture, fail_loudly=True)
    query = fixture.queries[0]
    result = evaluator.evaluate_query(
        query_id=query["query_id"],
        query=query["query"],
        retriever=retriever,
        filters=filters,
        row_effective=row_effective,
        check_reproducibility=True,
        evaluated_at_utc="2026-08-03T12:00:00Z",
    )

    assert result.schema_version == RETRIEVAL_EVAL_V2_SCHEMA_VERSION
    assert result.passed is True
    assert result.reproducible is True
    assert result.latency.passed is True
    assert result.fused.family is RetrievalFamily.FUSION
    assert result.fused.hit_document_ids[0] == "doc:patent-encode"

    for family in (
        RetrievalFamily.BM25,
        RetrievalFamily.VECTOR,
        RetrievalFamily.GRAPH,
        RetrievalFamily.FUSION,
    ):
        if family is RetrievalFamily.FUSION:
            fam = result.fused
        else:
            fam = result.family_results[family.value]
        assert fam.passed is True
        kinds = {m.kind for m in fam.metrics}
        assert kinds == REQUIRED_METRIC_KINDS
        assert fam.receipt is not None
        assert fam.receipt.passed is True
        assert isinstance(fam.source_errors, tuple)
        assert isinstance(fam.temporal_errors, tuple)
        assert isinstance(fam.citation_errors, tuple)
        assert "doc:private-draft" not in fam.hit_document_ids
        assert "doc:future-rule" not in fam.hit_document_ids

    # Snapshot binding on result + receipt.
    assert result.binding.snapshot_cid == build.root_cid
    receipt = result.receipt(RetrievalFamily.FUSION)
    assert receipt.snapshot_cid == build.root_cid
    assert receipt.corpus_cid == data["corpus_cid"]
    assert receipt.model_cid == data["model_cid"]
    assert receipt.config_cid == data["config_cid"]
    assert receipt.qrels_cid == fixture.qrel_set.qrels_cid
    assert receipt.binding_cids() == {
        "snapshot_cid": build.root_cid,
        "corpus_cid": data["corpus_cid"],
        "model_cid": data["model_cid"],
        "config_cid": data["config_cid"],
        "qrels_cid": fixture.qrel_set.qrels_cid,
    }
    assert result.binding_cids()["snapshot_cid"] == build.root_cid
    assert result.binding_cids()["qrels_cid"] == DEFAULT_QRELS_V2_CID


def test_receipt_binds_snapshot_model_config_qrels(tmp_path: Path) -> None:
    fixture = load_evaluation_fixture_v2(QRELS_V2_PATH)
    retriever, data, build = _build_persistent_retriever(tmp_path)
    filters = _filters_from_gold(data, applied=True)
    result = evaluate_hybrid_v2_against_qrels(
        retriever=retriever,
        qrel_set=fixture,
        query_id=fixture.queries[0]["query_id"],
        query=fixture.queries[0]["query"],
        filters=filters,
        row_effective=row_effective_from_documents(_docs_from_gold(data)),
        check_reproducibility=False,
    )
    receipt = result.receipt()
    assert receipt.snapshot_cid == build.root_cid
    assert receipt.model_cid == data["model_cid"]
    assert receipt.config_cid == data["config_cid"]
    assert receipt.qrels_cid == DEFAULT_QRELS_V2_CID
    assert "bm25" in receipt.index_cids
    assert "vector" in receipt.index_cids
    assert "graph" in receipt.index_cids


# ---------------------------------------------------------------------------
# Versioned thresholds fail on intentionally degraded retrieval
# ---------------------------------------------------------------------------


def test_versioned_thresholds_fail_on_degraded_retrieval(tmp_path: Path) -> None:
    fixture = load_evaluation_fixture_v2(QRELS_V2_PATH)
    retriever, data, _build = _build_persistent_retriever(tmp_path)
    filters = _filters_from_gold(data, applied=True)
    query = fixture.queries[0]

    search = retriever.search(
        HybridSearchRequestV2(
            query_id=query["query_id"],
            query=query["query"],
            filters=filters,
            top_k=5,
        )
    )
    assert search.hits

    evaluator = PatentRetrievalEvaluatorV2(fixture, fail_loudly=True)
    with pytest.raises(MetricThresholdError):
        evaluator.evaluate_degraded(
            search,
            query_id=query["query_id"],
            drop_top_n=1,
            row_effective=row_effective_from_documents(_docs_from_gold(data)),
        )

    # Direct degrade_ranking also tanks recall under harsh thresholds.
    degraded = degrade_ranking(search.hits, drop_top_n=2, reverse=True)
    harsh = MetricThresholds(
        schema_version=EVALUATION_SCHEMA_VERSION,
        thresholds_cid=DEFAULT_THRESHOLDS_V2_CID,
        minima={
            MetricKind.RECALL.value: 1.0,
            MetricKind.RANKING.value: 1.0,
            MetricKind.CITATION.value: 1.0,
            MetricKind.TEMPORAL.value: 1.0,
            MetricKind.SOURCE_COVERAGE.value: 1.0,
            MetricKind.PRIVATE_ISOLATION.value: 1.0,
        },
        k=1,
    )
    soft = PatentRetrievalEvaluatorV2(
        fixture, thresholds=harsh, fail_loudly=False
    )
    from ipfs_datasets_py.processors.domains.patent.retrieval_evaluation_v2 import (
        build_family_evaluation_v2,
    )

    fam = build_family_evaluation_v2(
        hits=degraded,
        qrel_set=fixture.qrel_set,
        query_id=query["query_id"],
        filters=search.filters,
        family=RetrievalFamily.FUSION,
        binding=search.binding,
        thresholds=harsh,
        k=1,
        private_document_ids=fixture.private_document_ids,
        expected_denied_provider_calls=search.denied_provider_call_count,
        fail_loudly=False,
    )
    assert fam.passed is False
    recall = next(m for m in fam.metrics if m.kind is MetricKind.RECALL)
    assert recall.passed is False
    assert recall.value < 1.0
    # Soft evaluator still constructs without raising.
    assert soft.fail_loudly is False


# ---------------------------------------------------------------------------
# Isolation: zero denied calls/results on public local path
# ---------------------------------------------------------------------------


def test_isolation_zero_denied_calls_and_results_on_public_path(
    tmp_path: Path,
) -> None:
    fixture = load_evaluation_fixture_v2(QRELS_V2_PATH)
    retriever, data, _build = _build_persistent_retriever(tmp_path)
    filters = _filters_from_gold(data, applied=True, denied=0)
    query = fixture.queries[0]

    search = retriever.search(
        HybridSearchRequestV2(
            query_id=query["query_id"],
            query=query["query"],
            filters=filters,
            top_k=5,
            allow_remote_embeddings=False,
            query_disclosure=DisclosureClass.PUBLIC_USER,
        )
    )
    # Public local path: zero denials, zero remote calls, zero denied results.
    assert search.denied_provider_call_count == 0
    assert search.remote_embedding_calls == 0
    assert search.denied_result_count == 0

    evaluator = PatentRetrievalEvaluatorV2(fixture, fail_loudly=True)
    result = evaluator.evaluate_search_result(
        search,
        row_effective=row_effective_from_documents(_docs_from_gold(data)),
        expected_denied_provider_calls=0,
    )
    assert result.denied_provider_call_count == 0
    assert result.denied_result_count == 0
    assert result.remote_embedding_calls == 0
    isolation = next(
        m for m in result.fused.metrics if m.kind is MetricKind.PRIVATE_ISOLATION
    )
    assert isolation.value == 1.0
    assert isolation.details["denied_provider_call_count"] == "0"
    assert result.fused.receipt is not None
    assert result.fused.receipt.denied_provider_call_count == 0
    assert result.fused.receipt.denied_result_count == 0


def test_private_route_denies_remote_with_zero_remote_results(tmp_path: Path) -> None:
    data = _load_gold()
    docs = _docs_from_gold(data)
    remote_calls = {"n": 0}

    def remote_embedder(texts):
        remote_calls["n"] += len(list(texts))
        return [[0.01] * 64 for _ in texts], {
            "backend": "embeddings_router",
            "provider": "openai",
        }

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
        filter_receipt_id="filter:private-hybrid-v2",
    )
    bundle = build_patent_indexes(
        docs,
        filters=private_filters,
        edges=data.get("edges") or [],
        embedding=remote_identity,
        corpus_cid=data["corpus_cid"],
        allow_remote=True,
        remote_embedder=remote_embedder,
    )
    binding = SnapshotBinding(
        snapshot_cid="bafybeisnapprivatehybridv2test00000000000000000000000001",
        corpus_cid=data["corpus_cid"],
        model_cid=data["model_cid"],
        config_cid=data["config_cid"],
        index_cids=dict(bundle.index_cids),
    )
    retriever = HybridRetrievalV2(
        bundle, binding=binding, remote_embedder=remote_embedder
    )
    before = remote_calls["n"]
    search = retriever.search(
        HybridSearchRequestV2(
            query_id="q-private",
            query="secret claim language",
            filters=private_filters,
            top_k=5,
            allow_remote_embeddings=True,
            query_disclosure=DisclosureClass.CONFIDENTIAL_APPLICATION,
        )
    )
    assert remote_calls["n"] == before
    assert search.remote_embedding_calls == 0
    assert search.denied_provider_call_count >= 1
    # Denied remote path yields zero results from the denied provider.
    assert search.denied_result_count == 0


# ---------------------------------------------------------------------------
# Missing source coverage reported, not scored as searched
# ---------------------------------------------------------------------------


def test_missing_source_coverage_reported_not_scored_as_searched(
    tmp_path: Path,
) -> None:
    fixture = load_evaluation_fixture_v2(QRELS_V2_PATH)
    retriever, data, _build = _build_persistent_retriever(tmp_path)
    filters = _filters_from_gold(data, applied=True)
    query = fixture.queries[0]

    search = retriever.search(
        HybridSearchRequestV2(
            query_id=query["query_id"],
            query=query["query"],
            filters=filters,
            top_k=5,
            unsearched_sources=fixture.unsearched_sources,
        )
    )
    evaluator = PatentRetrievalEvaluatorV2(fixture, fail_loudly=True)
    result = evaluator.evaluate_search_result(
        search,
        row_effective=row_effective_from_documents(_docs_from_gold(data)),
    )
    report = result.source_coverage_report
    assert report is not None

    # Foreign / NPL declared unsearched — never appear as searched.
    not_searched = set(report.not_searched_source_ids)
    assert "foreign_patent_office" in not_searched
    assert "non_patent_literature" in not_searched
    for sid in ("foreign_patent_office", "non_patent_literature"):
        assert sid not in report.searched_source_ids
        items = [i for i in report.items if i.source_id == sid]
        assert items
        assert items[0].status in {
            SourceCoverageStatus.UNSEARCHED_DECLARED,
            SourceCoverageStatus.NOT_SEARCHED,
        }
        assert items[0].scored_as_searched is False

    # Hit-level source coverage remains a separate metric (top-k joins).
    assert 0.0 <= report.hit_source_coverage <= 1.0
    source_cov = next(
        m for m in result.fused.metrics if m.kind is MetricKind.SOURCE_COVERAGE
    )
    assert source_cov.value == 1.0  # all hits have source CIDs

    # Standalone report builder also refuses double-counting.
    standalone = build_source_coverage_report(
        search.hits,
        k=10,
        expected_source_cids=[
            "bafybeic3g5s5x5x5x5x5x5x5x5x5x5x5x5x5x5x5x5x5x5x5x5x5x5x5x5x"
        ],
        unsearched_sources=("foreign_patent_office",),
        declared_sources=fixture.declared_sources,
    )
    assert "foreign_patent_office" in standalone.not_searched_source_ids
    assert "foreign_patent_office" not in standalone.searched_source_ids


# ---------------------------------------------------------------------------
# Schema / interface pins
# ---------------------------------------------------------------------------


def test_schema_pins() -> None:
    assert HYBRID_RETRIEVAL_V2_SCHEMA_VERSION == "patent.hybrid_retrieval.v2"
    assert HYBRID_RETRIEVAL_V2_INTERFACE == "HybridRetrievalV2@1"
    assert RETRIEVAL_EVAL_V2_SCHEMA_VERSION == "patent.retrieval.eval.v2"
    assert FIXTURE_V2_SCHEMA_VERSION == "patent.retrieval.eval.fixture.v2"
    assert QRELS_V2_PATH.is_file()


def test_build_bundle_from_gold_corpus_helper() -> None:
    bundle, data = build_bundle_from_gold_corpus(GOLDEN_PATH)
    assert bundle.corpus_cid == data["corpus_cid"]
    assert bundle.bm25.documents
    filters = _filters_from_gold(data, applied=True)
    retriever = HybridRetrievalV2.from_bundle(
        bundle, snapshot_cid="bafybeisnapfromgold00000000000000000000000000000000001"
    )
    result = retriever.search_query(
        data["queries"][0]["query"],
        query_id=data["queries"][0]["query_id"],
        filters=filters,
        top_k=3,
    )
    assert result.hits
    assert_explainable_hits(result)
