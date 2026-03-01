from __future__ import annotations

from ipfs_datasets_py.processors.legal_data.reasoner.optimizer_policy import build_optimizer_onoff_benchmark


def _report(
    *,
    semantic: float,
    keyphrase: float,
    enum_ok: float,
    relation: float,
    success_rate: float,
    success_count: float,
    orphan_rate: float,
    rel_artifact_rate: float,
    orphan_total: float,
    rel_artifact_total: float,
) -> dict:
    return {
        "summary": {
            "semantic_similarity_final_decoded_mean": semantic,
            "final_decoded_keyphrase_retention_mean": keyphrase,
            "final_decoded_enumeration_integrity_mean": enum_ok,
            "flogic_relation_coverage_mean": relation,
            "hybrid_ir_success_rate": success_rate,
            "hybrid_ir_success_count": success_count,
            "final_decoded_orphan_terminal_rate": orphan_rate,
            "final_decoded_relative_clause_artifact_rate": rel_artifact_rate,
            "final_decoded_orphan_terminal_count_total": orphan_total,
            "final_decoded_relative_clause_artifact_count_total": rel_artifact_total,
        }
    }


def test_optimizer_benchmark_counts_improvements_and_regressions() -> None:
    off_report = _report(
        semantic=0.90,
        keyphrase=0.80,
        enum_ok=0.70,
        relation=0.60,
        success_rate=0.90,
        success_count=9,
        orphan_rate=0.03,
        rel_artifact_rate=0.02,
        orphan_total=3,
        rel_artifact_total=2,
    )
    on_report = _report(
        semantic=0.92,
        keyphrase=0.81,
        enum_ok=0.71,
        relation=0.61,
        success_rate=0.91,
        success_count=10,
        orphan_rate=0.02,
        rel_artifact_rate=0.03,
        orphan_total=2,
        rel_artifact_total=3,
    )

    out = build_optimizer_onoff_benchmark(off_report, on_report)

    assert out["summary"]["metric_count"] == 10
    assert out["summary"]["improvement_count"] == 8
    assert out["summary"]["regression_count"] == 2
    assert out["summary"]["missing_count"] == 0
    assert out["summary"]["net_score"] == 6
    assert out["summary"]["semantic_gain"] == 0.02


def test_optimizer_benchmark_marks_missing_metrics() -> None:
    off_report = {"summary": {"semantic_similarity_final_decoded_mean": 0.90}}
    on_report = {"summary": {"semantic_similarity_final_decoded_mean": 0.91}}

    out = build_optimizer_onoff_benchmark(off_report, on_report)

    assert out["summary"]["metric_count"] == 10
    assert out["summary"]["improvement_count"] == 1
    assert out["summary"]["missing_count"] == 9
