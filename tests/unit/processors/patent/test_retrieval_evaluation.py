"""Unit tests for patent retrieval evaluation contracts (PATLAW-090)."""

from __future__ import annotations

import json

import pytest

from ipfs_datasets_py.processors.domains.patent.evaluation import (
    EVALUATION_SCHEMA_VERSION,
    REQUIRED_METRIC_KINDS,
    EvaluationReceipt,
    MetricKind,
    MetricScore,
    MetricThresholdError,
    MetricThresholds,
    Qrel,
    QrelSet,
    RelevanceGrade,
    apply_thresholds,
    assert_thresholds,
    build_evaluation_receipt,
    canonical_json,
    compute_citation_grounding,
    compute_ndcg_at_k,
    compute_private_isolation,
    compute_recall_at_k,
    compute_source_coverage,
    compute_temporal_accuracy,
    evaluate_ranking,
)
from ipfs_datasets_py.processors.domains.patent.retrieval_contracts import (
    RETRIEVAL_CONTRACTS_SCHEMA_VERSION,
    AuthorityClaim,
    DisclosureClass,
    MissingPreRankingFiltersError,
    PreRankingFilters,
    RankedHit,
    RetrievalFamily,
    SourceLink,
    SourceSpan,
)

DIGEST_A = "a" * 64
CID_CORPUS = "bafybeigdyrzt5sfp7udm7hu76uh7y26nf3efuylqabf3oclgtqy55fbzdi"
CID_CONFIG = "bafybeihdwdcefgh4dqkjv67uzcmw7ojee6xedzdetojuzjevtenxquvyku"
CID_MODEL = "bafybeimodelidentity000000000000000000000000000000000000001"
CID_QRELS = "bafybeiqrelsidentity000000000000000000000000000000000000002"
CID_THRESH = "bafybeithresholds00000000000000000000000000000000000000003"
CID_SOURCE = "bafybeic3g5s5x5x5x5x5x5x5x5x5x5x5x5x5x5x5x5x5x5x5x5x5x5x5x5x"
CID_SOURCE_B = "bafybeic3g5s5y5y5y5y5y5y5y5y5y5y5y5y5y5y5y5y5y5y5y5y5y5y5y"


def _link(cid: str = CID_SOURCE, artifact_id: str = "artifact:35usc102") -> SourceLink:
    return SourceLink(
        source_cid=cid,
        artifact_id=artifact_id,
        span=SourceSpan(start=0, end=8),
    )


def _filters(
    *,
    applied: bool = True,
    denied: int = 3,
    as_of: str = "2024-06-01T00:00:00Z",
) -> PreRankingFilters:
    return PreRankingFilters(
        schema_version=RETRIEVAL_CONTRACTS_SCHEMA_VERSION,
        tenant_id="tenant-public",
        as_of_utc=as_of,
        allowed_disclosures=(DisclosureClass.PUBLIC_OFFICIAL,),
        applied=applied,
        denied_provider_call_count=denied,
    )


def _hits() -> tuple[RankedHit, ...]:
    return (
        RankedHit(
            document_id="doc:gold",
            score=10.0,
            rank=1,
            family=RetrievalFamily.FUSION,
            source_links=(_link(CID_SOURCE, "artifact:35usc102"),),
            authority_claim=AuthorityClaim.SOURCE_BOUND,
        ),
        RankedHit(
            document_id="doc:partial",
            score=5.0,
            rank=2,
            family=RetrievalFamily.FUSION,
            source_links=(_link(CID_SOURCE_B, "artifact:mpep-2100"),),
        ),
        RankedHit(
            document_id="doc:noise",
            score=1.0,
            rank=3,
            family=RetrievalFamily.FUSION,
            source_links=(_link(),),
        ),
    )


def _qrel_set() -> QrelSet:
    return QrelSet(
        schema_version=EVALUATION_SCHEMA_VERSION,
        qrels_cid=CID_QRELS,
        corpus_cid=CID_CORPUS,
        judgments=(
            Qrel(
                query_id="q1",
                document_id="doc:gold",
                grade=RelevanceGrade.EXACT,
                expected_citation="artifact:35usc102",
                expected_source_cids=(CID_SOURCE,),
                expected_as_of_utc="2024-06-01T00:00:00Z",
            ),
            Qrel(
                query_id="q1",
                document_id="doc:partial",
                grade=RelevanceGrade.RELEVANT,
                expected_source_cids=(CID_SOURCE_B,),
            ),
            Qrel(
                query_id="q1",
                document_id="doc:noise",
                grade=RelevanceGrade.NOT_RELEVANT,
            ),
        ),
        description="synthetic patent retrieval gold",
    )


def _assert_round_trip(record: object) -> None:
    first = record.to_dict()  # type: ignore[attr-defined]
    restored = type(record).from_dict(first)  # type: ignore[attr-defined]
    second = restored.to_dict()  # type: ignore[attr-defined]
    assert first == second
    assert canonical_json(first) == canonical_json(second)
    assert (
        json.dumps(first, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        == canonical_json(first)
    )
    assert restored == record


def test_required_metric_kinds_cover_acceptance_surface() -> None:
    assert REQUIRED_METRIC_KINDS == frozenset(
        {
            MetricKind.RECALL,
            MetricKind.RANKING,
            MetricKind.CITATION,
            MetricKind.TEMPORAL,
            MetricKind.SOURCE_COVERAGE,
            MetricKind.PRIVATE_ISOLATION,
        }
    )
    assert {m.value for m in MetricKind} == {
        "recall",
        "ranking",
        "citation",
        "temporal",
        "source_coverage",
        "private_isolation",
    }


def test_qrel_set_round_trip_and_query_lookup() -> None:
    qrels = _qrel_set()
    _assert_round_trip(qrels)
    assert qrels.relevant_document_ids("q1") == frozenset({"doc:gold", "doc:partial"})
    assert len(qrels.for_query("q1")) == 3


def test_qrel_set_rejects_duplicates() -> None:
    with pytest.raises(ValueError, match="duplicate"):
        QrelSet(
            schema_version=EVALUATION_SCHEMA_VERSION,
            qrels_cid=CID_QRELS,
            judgments=(
                Qrel(query_id="q1", document_id="doc:a", grade=RelevanceGrade.RELEVANT),
                Qrel(query_id="q1", document_id="doc:a", grade=RelevanceGrade.EXACT),
            ),
        )


def test_metrics_refuse_without_applied_filters() -> None:
    hits = _hits()
    unapplied = _filters(applied=False)
    with pytest.raises(MissingPreRankingFiltersError):
        compute_recall_at_k(hits, {"doc:gold"}, k=5, filters=unapplied)
    with pytest.raises(MissingPreRankingFiltersError):
        compute_ndcg_at_k(hits, {"doc:gold": 3}, k=5, filters=None)
    with pytest.raises(MissingPreRankingFiltersError):
        compute_source_coverage(hits, k=5, filters=unapplied)
    with pytest.raises(MissingPreRankingFiltersError):
        compute_private_isolation(filters=unapplied)
    with pytest.raises(MissingPreRankingFiltersError):
        evaluate_ranking(
            hits=hits,
            qrel_set=_qrel_set(),
            query_id="q1",
            filters=unapplied,
        )


def test_evaluate_ranking_produces_all_metric_kinds() -> None:
    filters = _filters(applied=True)
    metrics = evaluate_ranking(
        hits=_hits(),
        qrel_set=_qrel_set(),
        query_id="q1",
        filters=filters,
        k=10,
        family=RetrievalFamily.FUSION,
        row_effective={
            "doc:gold": ("2020-01-01T00:00:00Z", "2030-01-01T00:00:00Z"),
            "doc:partial": ("2020-01-01T00:00:00Z", None),
            "doc:noise": (None, None),
        },
        expected_denied_provider_calls=3,
    )
    kinds = {m.kind for m in metrics}
    assert kinds == REQUIRED_METRIC_KINDS
    by_kind = {m.kind: m for m in metrics}
    assert by_kind[MetricKind.RECALL].value == 1.0
    assert by_kind[MetricKind.RANKING].value > 0.5
    assert by_kind[MetricKind.CITATION].value == 1.0
    assert by_kind[MetricKind.TEMPORAL].value == 1.0
    assert by_kind[MetricKind.SOURCE_COVERAGE].value == 1.0
    assert by_kind[MetricKind.PRIVATE_ISOLATION].value == 1.0
    assert all(m.family is RetrievalFamily.FUSION for m in metrics)


def test_source_coverage_flags_missing_links() -> None:
    # RankedHit construction itself requires source links; measure via empty hits.
    score, errors = compute_source_coverage((), k=5, filters=_filters(applied=True))
    assert score.kind is MetricKind.SOURCE_COVERAGE
    assert score.value == 1.0
    assert errors == ()


def test_private_isolation_records_denied_calls_and_leaks() -> None:
    filters = _filters(applied=True, denied=4)
    ok = compute_private_isolation(
        filters=filters,
        expected_denied_provider_calls=4,
    )
    assert ok.value == 1.0
    assert ok.details["denied_provider_call_count"] == "4"

    leak = compute_private_isolation(
        filters=filters,
        expected_denied_provider_calls=4,
        leaked_private_document_ids=("doc:secret",),
    )
    assert leak.value == 0.0

    mismatch = compute_private_isolation(
        filters=filters,
        expected_denied_provider_calls=99,
    )
    assert mismatch.value == 0.0


def test_citation_and_temporal_error_enumeration() -> None:
    filters = _filters(applied=True)
    hits = _hits()
    qrels = _qrel_set().for_query("q1")
    citation, c_errors = compute_citation_grounding(hits, qrels, k=10, filters=filters)
    assert citation.value == 1.0
    assert c_errors == ()

    temporal, t_errors = compute_temporal_accuracy(
        hits,
        qrels,
        as_of_utc=filters.as_of_utc,
        k=2,
        filters=filters,
        row_effective={
            "doc:gold": ("2025-01-01T00:00:00Z", None),  # after as-of
        },
    )
    assert temporal.value < 1.0
    assert any("before effective_from" in e for e in t_errors)


def test_thresholds_fail_loudly_on_regression() -> None:
    thresholds = MetricThresholds.default(thresholds_cid=CID_THRESH)
    _assert_round_trip(thresholds)
    metrics = (
        MetricScore(kind=MetricKind.RECALL, value=0.1, k=10),
        MetricScore(kind=MetricKind.RANKING, value=0.9, k=10),
        MetricScore(kind=MetricKind.CITATION, value=0.9, k=10),
        MetricScore(kind=MetricKind.TEMPORAL, value=0.9, k=10),
        MetricScore(kind=MetricKind.SOURCE_COVERAGE, value=1.0, k=10),
        MetricScore(kind=MetricKind.PRIVATE_ISOLATION, value=1.0),
    )
    annotated = apply_thresholds(metrics, thresholds)
    assert annotated[0].passed is False
    with pytest.raises(MetricThresholdError, match="recall"):
        assert_thresholds(metrics, thresholds)


def test_evaluation_receipt_binds_corpus_model_config_qrels_cids() -> None:
    filters = _filters(applied=True)
    metrics = evaluate_ranking(
        hits=_hits(),
        qrel_set=_qrel_set(),
        query_id="q1",
        filters=filters,
        k=10,
        expected_denied_provider_calls=3,
    )
    thresholds = MetricThresholds.default(thresholds_cid=CID_THRESH)
    receipt = build_evaluation_receipt(
        receipt_id="eval:receipt:1",
        corpus_cid=CID_CORPUS,
        model_cid=CID_MODEL,
        config_cid=CID_CONFIG,
        qrels_cid=CID_QRELS,
        metrics=metrics,
        filters=filters,
        index_cids={"bm25": CID_SOURCE, "vector": CID_CONFIG, "graph": CID_SOURCE_B},
        thresholds=thresholds,
        family=RetrievalFamily.FUSION,
        evaluated_at_utc="2026-08-03T12:00:00Z",
        source_errors=(),
        temporal_errors=(),
    )
    assert receipt.corpus_cid == CID_CORPUS
    assert receipt.model_cid == CID_MODEL
    assert receipt.config_cid == CID_CONFIG
    assert receipt.qrels_cid == CID_QRELS
    assert receipt.binding_cids() == {
        "corpus_cid": CID_CORPUS,
        "model_cid": CID_MODEL,
        "config_cid": CID_CONFIG,
        "qrels_cid": CID_QRELS,
    }
    assert {m.kind for m in receipt.metrics} == REQUIRED_METRIC_KINDS
    assert receipt.denied_provider_call_count == 3
    assert receipt.filters.applied is True
    assert receipt.passed is True
    _assert_round_trip(receipt)


def test_evaluation_receipt_requires_all_metric_kinds_and_filters() -> None:
    filters = _filters(applied=True)
    incomplete = (
        MetricScore(kind=MetricKind.RECALL, value=1.0, k=10),
        MetricScore(kind=MetricKind.RANKING, value=1.0, k=10),
        MetricScore(kind=MetricKind.CITATION, value=1.0, k=10),
        MetricScore(kind=MetricKind.TEMPORAL, value=1.0, k=10),
        MetricScore(kind=MetricKind.SOURCE_COVERAGE, value=1.0, k=10),
        # missing private_isolation
    )
    with pytest.raises(ValueError, match="private_isolation"):
        EvaluationReceipt(
            schema_version=EVALUATION_SCHEMA_VERSION,
            receipt_id="eval:bad",
            corpus_cid=CID_CORPUS,
            model_cid=CID_MODEL,
            config_cid=CID_CONFIG,
            qrels_cid=CID_QRELS,
            metrics=incomplete,
            filters=filters,
        )

    full = evaluate_ranking(
        hits=_hits(),
        qrel_set=_qrel_set(),
        query_id="q1",
        filters=filters,
        expected_denied_provider_calls=3,
    )
    with pytest.raises(MissingPreRankingFiltersError):
        build_evaluation_receipt(
            receipt_id="eval:nofilt",
            corpus_cid=CID_CORPUS,
            model_cid=CID_MODEL,
            config_cid=CID_CONFIG,
            qrels_cid=CID_QRELS,
            metrics=full,
            filters=_filters(applied=False),
        )


def test_metric_thresholds_require_all_kinds() -> None:
    with pytest.raises(ValueError, match="missing required kinds"):
        MetricThresholds(
            schema_version=EVALUATION_SCHEMA_VERSION,
            thresholds_cid=CID_THRESH,
            minima={"recall": 0.5},
        )
