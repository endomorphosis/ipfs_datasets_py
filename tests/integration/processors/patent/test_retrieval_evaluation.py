"""Integration tests for patent retrieval evaluation harness (PATLAW-093)."""

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
from ipfs_datasets_py.processors.domains.patent.hybrid_retrieval import (
    HybridSearchRequest,
    PatentHybridRetriever,
)
from ipfs_datasets_py.processors.domains.patent.indexing import (
    PatentIndexDocument,
    build_patent_indexes,
    default_embedding_identity,
)
from ipfs_datasets_py.processors.domains.patent.retrieval_contracts import (
    RETRIEVAL_CONTRACTS_SCHEMA_VERSION,
    DisclosureClass,
    MissingPreRankingFiltersError,
    PreRankingFilters,
    RetrievalFamily,
    canonical_json,
)
from ipfs_datasets_py.processors.domains.patent.retrieval_eval import (
    DEFAULT_QRELS_CID,
    DEFAULT_THRESHOLDS_CID,
    FIXTURE_SCHEMA_VERSION,
    RETRIEVAL_EVAL_SCHEMA_VERSION,
    LatencyEnvelopeError,
    LatencyMeasurement,
    PatentRetrievalEvaluator,
    assert_latency_envelope,
    build_bundle_from_gold_corpus,
    build_family_evaluation,
    default_fixture_path,
    evaluate_hybrid_against_qrels,
    load_evaluation_fixture,
    load_qrel_set,
    ranking_digest,
    row_effective_from_documents,
    score_family_ranking,
)

FIXTURE_DIR = (
    Path(__file__).resolve().parents[3] / "fixtures" / "patent" / "retrieval"
)
QRELS_PATH = FIXTURE_DIR / "qrels.json"
GOLDEN_PATH = FIXTURE_DIR / "golden_case.json"


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
        filter_receipt_id="filter:eval-integration",
    )


def test_qrels_fixture_loads_and_binds_corpus() -> None:
    fixture = load_evaluation_fixture(QRELS_PATH)
    assert fixture.schema_version == FIXTURE_SCHEMA_VERSION
    assert fixture.qrel_set.qrels_cid == DEFAULT_QRELS_CID
    assert fixture.qrel_set.corpus_cid is not None
    gold = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    assert fixture.qrel_set.corpus_cid == gold["corpus_cid"]
    assert fixture.thresholds.thresholds_cid == DEFAULT_THRESHOLDS_CID
    assert set(fixture.thresholds.minima) >= {m.value for m in REQUIRED_METRIC_KINDS}
    assert fixture.private_document_ids == ("doc:private-draft",)
    assert any(q["query_id"] == "q-prior-art-102" for q in fixture.queries)
    # Bare QrelSet path also works.
    qrels = load_qrel_set(QRELS_PATH)
    assert qrels.qrels_cid == fixture.qrel_set.qrels_cid
    assert qrels.relevant_document_ids("q-prior-art-102") == frozenset(
        {"doc:patent-encode", "doc:patent-network"}
    )
    assert default_fixture_path().name == "qrels.json"


def test_evaluate_each_family_and_fused_against_qrels() -> None:
    fixture = load_evaluation_fixture(QRELS_PATH)
    bundle, data = build_bundle_from_gold_corpus(GOLDEN_PATH)
    filters = _filters_from_gold(data, applied=True)
    docs = [PatentIndexDocument.from_dict(d) for d in data["documents"]]
    row_effective = row_effective_from_documents(docs)

    evaluator = PatentRetrievalEvaluator(fixture, fail_loudly=True)
    query = fixture.queries[0]
    result = evaluator.evaluate_query(
        query_id=query["query_id"],
        query=query["query"],
        bundle=bundle,
        filters=filters,
        row_effective=row_effective,
        check_reproducibility=True,
        evaluated_at_utc="2026-08-03T12:00:00Z",
    )

    assert result.schema_version == RETRIEVAL_EVAL_SCHEMA_VERSION
    assert result.passed is True
    assert result.reproducible is True
    assert result.latency.passed is True
    assert result.fused.family is RetrievalFamily.FUSION
    assert result.fused.hit_document_ids[0] == "doc:patent-encode"
    # Each family + fused measured.
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
        # Source/time errors enumerated (may be empty when clean).
        assert isinstance(fam.source_errors, tuple)
        assert isinstance(fam.temporal_errors, tuple)
        assert isinstance(fam.citation_errors, tuple)
        # Isolation records denied provider-call counts.
        assert fam.denied_provider_call_count == result.denied_provider_call_count
        assert (
            fam.receipt.denied_provider_call_count
            == result.denied_provider_call_count
        )
        isolation = next(
            m for m in fam.metrics if m.kind is MetricKind.PRIVATE_ISOLATION
        )
        assert isolation.details["denied_provider_call_count"] == str(
            result.denied_provider_call_count
        )
        assert "doc:private-draft" not in fam.hit_document_ids
        assert "doc:future-rule" not in fam.hit_document_ids


def test_receipt_binds_corpus_index_model_config_qrels_cids() -> None:
    fixture = load_evaluation_fixture(QRELS_PATH)
    bundle, data = build_bundle_from_gold_corpus(GOLDEN_PATH)
    filters = _filters_from_gold(data, applied=True)
    evaluator = PatentRetrievalEvaluator(fixture)
    query = fixture.queries[0]
    result = evaluator.evaluate_query(
        query_id=query["query_id"],
        query=query["query"],
        bundle=bundle,
        filters=filters,
        row_effective=row_effective_from_documents(
            [PatentIndexDocument.from_dict(d) for d in data["documents"]]
        ),
    )
    receipt = result.receipt(RetrievalFamily.FUSION)
    assert receipt.corpus_cid == data["corpus_cid"]
    assert receipt.model_cid == data["model_cid"]
    assert receipt.config_cid == data["config_cid"]
    assert receipt.qrels_cid == fixture.qrel_set.qrels_cid
    assert receipt.binding_cids() == {
        "corpus_cid": data["corpus_cid"],
        "model_cid": data["model_cid"],
        "config_cid": data["config_cid"],
        "qrels_cid": fixture.qrel_set.qrels_cid,
    }
    # Index family CIDs bound on the receipt.
    assert "bm25" in receipt.index_cids
    assert "vector" in receipt.index_cids
    assert "graph" in receipt.index_cids
    assert receipt.index_cids == dict(bundle.index_cids)
    assert result.binding_cids["qrels_cid"] == DEFAULT_QRELS_CID
    # Round-trip stability of receipt payload.
    assert EvaluationReceipt_round_trip(receipt)


def EvaluationReceipt_round_trip(receipt) -> bool:
    from ipfs_datasets_py.processors.domains.patent.evaluation import (
        EvaluationReceipt,
    )

    restored = EvaluationReceipt.from_dict(receipt.to_dict())
    assert canonical_json(receipt.to_dict()) == canonical_json(restored.to_dict())
    return True


def test_versioned_thresholds_fail_loudly_on_regression() -> None:
    fixture = load_evaluation_fixture(QRELS_PATH)
    bundle, data = build_bundle_from_gold_corpus(GOLDEN_PATH)
    filters = _filters_from_gold(data, applied=True)
    # Impossible recall floor forces a loud regression failure.
    harsh = MetricThresholds(
        schema_version=EVALUATION_SCHEMA_VERSION,
        thresholds_cid=DEFAULT_THRESHOLDS_CID,
        minima={
            MetricKind.RECALL.value: 1.0,
            MetricKind.RANKING.value: 1.0,
            MetricKind.CITATION.value: 1.0,
            MetricKind.TEMPORAL.value: 1.0,
            MetricKind.SOURCE_COVERAGE.value: 1.0,
            MetricKind.PRIVATE_ISOLATION.value: 1.0,
        },
        k=1,  # only top-1; network relevant doc will tank recall when both required
    )
    # With k=1 and two relevant docs, fused recall is 0.5 < 1.0.
    evaluator = PatentRetrievalEvaluator(
        fixture, thresholds=harsh, fail_loudly=True
    )
    query = fixture.queries[0]
    with pytest.raises(MetricThresholdError, match="recall|threshold|regression"):
        evaluator.evaluate_query(
            query_id=query["query_id"],
            query=query["query"],
            bundle=bundle,
            filters=filters,
            top_k=1,
            check_reproducibility=False,
            row_effective=row_effective_from_documents(
                [PatentIndexDocument.from_dict(d) for d in data["documents"]]
            ),
        )

    # Soft mode annotates pass/fail without raising on metric values, but still
    # returns structured failures.
    soft = PatentRetrievalEvaluator(
        fixture, thresholds=harsh, fail_loudly=False
    )
    soft_result = soft.evaluate_query(
        query_id=query["query_id"],
        query=query["query"],
        bundle=bundle,
        filters=filters,
        top_k=1,
        check_reproducibility=False,
        row_effective=row_effective_from_documents(
            [PatentIndexDocument.from_dict(d) for d in data["documents"]]
        ),
    )
    assert soft_result.fused.passed is False
    assert soft_result.passed is False
    recall = next(
        m for m in soft_result.fused.metrics if m.kind is MetricKind.RECALL
    )
    assert recall.passed is False
    assert recall.value < 1.0


def test_source_and_temporal_errors_are_enumerated() -> None:
    fixture = load_evaluation_fixture(QRELS_PATH)
    bundle, data = build_bundle_from_gold_corpus(GOLDEN_PATH)
    filters = _filters_from_gold(data, applied=True)
    retriever = PatentHybridRetriever(bundle)
    query = fixture.queries[0]
    search = retriever.search(
        HybridSearchRequest(
            query_id=query["query_id"],
            query=query["query"],
            filters=filters,
            top_k=5,
        )
    )
    # Intentionally wrong effective interval for the gold hit.
    bad_effective = {
        "doc:patent-encode": ("2025-01-01T00:00:00Z", None),
        "doc:patent-network": ("2019-01-01T00:00:00Z", None),
    }
    metrics, source_errors, temporal_errors, citation_errors = score_family_ranking(
        hits=search.fused_hits,
        qrel_set=fixture.qrel_set,
        query_id=query["query_id"],
        filters=search.filters,
        family=RetrievalFamily.FUSION,
        k=10,
        row_effective=bad_effective,
        private_document_ids=fixture.private_document_ids,
        expected_denied_provider_calls=search.denied_provider_call_count,
    )
    assert {m.kind for m in metrics} == REQUIRED_METRIC_KINDS
    assert any("before effective_from" in e for e in temporal_errors)
    # Source errors are a tuple (possibly empty when links are present).
    assert isinstance(source_errors, tuple)
    assert isinstance(citation_errors, tuple)
    temporal = next(m for m in metrics if m.kind is MetricKind.TEMPORAL)
    assert temporal.value < 1.0


def test_isolation_records_denied_provider_call_counts() -> None:
    fixture = load_evaluation_fixture(QRELS_PATH)
    gold = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    docs = [PatentIndexDocument.from_dict(d) for d in gold["documents"]]
    remote_calls = {"n": 0}

    def remote_embedder(texts):
        remote_calls["n"] += len(list(texts))
        return [[0.01] * 64 for _ in texts], {
            "backend": "embeddings_router",
            "provider": "openai",
        }

    from ipfs_datasets_py.processors.domains.patent.retrieval_contracts import (
        EmbeddingIdentity,
    )

    remote_identity = EmbeddingIdentity(
        schema_version=RETRIEVAL_CONTRACTS_SCHEMA_VERSION,
        provider="openai",
        model_id="text-embedding-3-small",
        model_version="1",
        dimension=64,
        config_cid=gold["config_cid"],
        model_cid=gold["model_cid"],
        backend="embeddings_router",
    )
    private_filters = PreRankingFilters(
        schema_version=RETRIEVAL_CONTRACTS_SCHEMA_VERSION,
        tenant_id=gold["tenant_id"],
        as_of_utc=gold["as_of_utc"],
        allowed_disclosures=(
            DisclosureClass.PUBLIC_OFFICIAL,
            DisclosureClass.PUBLIC_USER,
            DisclosureClass.CONFIDENTIAL_APPLICATION,
        ),
        applied=True,
        filter_receipt_id="filter:private-eval",
    )
    bundle = build_patent_indexes(
        docs,
        filters=private_filters,
        edges=gold.get("edges") or [],
        embedding=remote_identity,
        corpus_cid=gold["corpus_cid"],
        allow_remote=True,
        remote_embedder=remote_embedder,
    )
    retriever = PatentHybridRetriever(bundle, remote_embedder=remote_embedder)
    before = remote_calls["n"]
    search = retriever.search(
        HybridSearchRequest(
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

    # Evaluate isolation surface against the private query ranking.
    # Use soft thresholds only on isolation-relevant kinds via full suite at 0.
    soft_thresholds = MetricThresholds(
        schema_version=EVALUATION_SCHEMA_VERSION,
        thresholds_cid=DEFAULT_THRESHOLDS_CID,
        minima={
            MetricKind.RECALL.value: 0.0,
            MetricKind.RANKING.value: 0.0,
            MetricKind.CITATION.value: 0.0,
            MetricKind.TEMPORAL.value: 0.0,
            MetricKind.SOURCE_COVERAGE.value: 0.0,
            MetricKind.PRIVATE_ISOLATION.value: 1.0,
        },
        k=10,
    )
    # Synthetic qrels for the private query id so evaluate_ranking can run.
    from ipfs_datasets_py.processors.domains.patent.evaluation import (
        Qrel,
        QrelSet,
        RelevanceGrade,
    )

    private_qrels = QrelSet(
        schema_version=EVALUATION_SCHEMA_VERSION,
        qrels_cid=DEFAULT_QRELS_CID,
        corpus_cid=gold["corpus_cid"],
        judgments=(
            Qrel(
                query_id="q-private",
                document_id="doc:private-draft",
                grade=RelevanceGrade.NOT_RELEVANT,
            ),
            Qrel(
                query_id="q-private",
                document_id="doc:patent-encode",
                grade=RelevanceGrade.PARTIAL,
            ),
        ),
    )
    # Under private-allowed filters, confidential docs are in-scope (not leaks).
    # Isolation still records denied remote provider-call counts for the route.
    fam = build_family_evaluation(
        hits=search.fused_hits,
        qrel_set=private_qrels,
        query_id="q-private",
        filters=search.filters,
        family=RetrievalFamily.FUSION,
        corpus_cid=gold["corpus_cid"],
        model_cid=gold["model_cid"],
        config_cid=gold["config_cid"],
        index_cids=dict(bundle.index_cids),
        thresholds=soft_thresholds,
        private_document_ids=(),
        expected_denied_provider_calls=search.denied_provider_call_count,
        fail_loudly=True,
    )
    assert fam.denied_provider_call_count >= 1
    assert fam.receipt is not None
    assert fam.receipt.denied_provider_call_count >= 1
    isolation = next(
        m for m in fam.metrics if m.kind is MetricKind.PRIVATE_ISOLATION
    )
    assert isolation.value == 1.0
    assert isolation.details["denied_provider_call_count"] == str(
        search.denied_provider_call_count
    )
    assert isolation.details["expected_denied_provider_calls"] == str(
        search.denied_provider_call_count
    )
    # Zero remote embedding calls on the denied private query route.
    assert search.remote_embedding_calls == 0


def test_filters_required_before_evaluation() -> None:
    fixture = load_evaluation_fixture(QRELS_PATH)
    bundle, data = build_bundle_from_gold_corpus(GOLDEN_PATH)
    unapplied = _filters_from_gold(data, applied=False)
    evaluator = PatentRetrievalEvaluator(fixture)
    query = fixture.queries[0]
    with pytest.raises(MissingPreRankingFiltersError):
        evaluator.evaluate_query(
            query_id=query["query_id"],
            query=query["query"],
            bundle=bundle,
            filters=unapplied,
            check_reproducibility=False,
        )


def test_latency_envelope_fails_loudly() -> None:
    measurement = LatencyMeasurement(
        elapsed_ms=50_000.0, max_ms=1_000.0, label="search:q1"
    )
    assert measurement.passed is False
    with pytest.raises(LatencyEnvelopeError, match="latency envelope"):
        assert_latency_envelope(measurement)
    ok = LatencyMeasurement(elapsed_ms=5.0, max_ms=1_000.0, label="search:q1")
    assert assert_latency_envelope(ok) is ok


def test_reproducibility_digest_stable_across_runs() -> None:
    fixture = load_evaluation_fixture(QRELS_PATH)
    bundle, data = build_bundle_from_gold_corpus(GOLDEN_PATH)
    filters = _filters_from_gold(data, applied=True)
    retriever = PatentHybridRetriever(bundle)
    query = fixture.queries[0]
    request = HybridSearchRequest(
        query_id=query["query_id"],
        query=query["query"],
        filters=filters,
        top_k=5,
    )
    a = retriever.search(request)
    b = retriever.search(request)
    assert ranking_digest(a.fused_hits) == ranking_digest(b.fused_hits)
    assert canonical_json(a.fusion.to_dict()) == canonical_json(b.fusion.to_dict())


def test_evaluate_hybrid_against_qrels_entrypoint() -> None:
    fixture = load_evaluation_fixture(QRELS_PATH)
    bundle, data = build_bundle_from_gold_corpus(GOLDEN_PATH)
    query = fixture.queries[0]
    result = evaluate_hybrid_against_qrels(
        bundle=bundle,
        qrel_set=fixture,
        query_id=query["query_id"],
        query=query["query"],
        filters=_filters_from_gold(data, applied=True),
        row_effective=row_effective_from_documents(
            [PatentIndexDocument.from_dict(d) for d in data["documents"]]
        ),
    )
    assert result.passed is True
    assert result.fused.receipt is not None
    assert result.denied_provider_call_count == result.fused.receipt.denied_provider_call_count


def test_functional_gold_path_matches_fixture_queries() -> None:
    """End-to-end: packaged fixture + gold corpus pass versioned thresholds."""
    results = PatentRetrievalEvaluator.from_fixture_path(QRELS_PATH).evaluate_fixture_queries(
        bundle=build_bundle_from_gold_corpus(GOLDEN_PATH)[0],
        filters=_filters_from_gold(
            json.loads(GOLDEN_PATH.read_text(encoding="utf-8")), applied=True
        ),
    )
    assert len(results) == 1
    assert results[0].passed is True
    assert results[0].fused.receipt is not None
    assert results[0].fused.receipt.thresholds_cid == DEFAULT_THRESHOLDS_CID
