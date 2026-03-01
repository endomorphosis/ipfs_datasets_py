from __future__ import annotations

from ipfs_datasets_py.processors.legal_data.reasoner.shadow_mode import build_shadow_mode_audit


def _report(*, segment_count: int, semantic_mean: float, orphan_rate: float, rel_artifact_rate: float, records_origin: str) -> dict:
    return {
        "summary": {
            "segment_count": segment_count,
            "semantic_similarity_final_decoded_mean": semantic_mean,
            "final_decoded_keyphrase_retention_mean": 0.80,
            "final_decoded_enumeration_integrity_mean": 0.80,
            "flogic_relation_coverage_mean": 0.60,
            "hybrid_ir_success_rate": 0.95,
            "final_decoded_orphan_terminal_rate": orphan_rate,
            "final_decoded_relative_clause_artifact_rate": rel_artifact_rate,
        },
        "records": [
            {"final_decoded_text_origin": records_origin},
            {"final_decoded_text_origin": records_origin},
        ],
    }


def test_build_shadow_mode_audit_shadow_ready_when_checks_pass() -> None:
    baseline = _report(
        segment_count=10,
        semantic_mean=0.94,
        orphan_rate=0.01,
        rel_artifact_rate=0.01,
        records_origin="baseline",
    )
    candidate = _report(
        segment_count=10,
        semantic_mean=0.95,
        orphan_rate=0.02,
        rel_artifact_rate=0.02,
        records_origin="hybrid",
    )

    audit = build_shadow_mode_audit(baseline, candidate)

    assert audit["summary"]["shadow_ready"] is True
    assert audit["summary"]["failure_count"] == 0
    assert audit["origin_counts"]["baseline"]["baseline"] == 2
    assert audit["origin_counts"]["candidate"]["hybrid"] == 2


def test_build_shadow_mode_audit_reports_failures_for_regressions() -> None:
    baseline = _report(
        segment_count=10,
        semantic_mean=0.94,
        orphan_rate=0.01,
        rel_artifact_rate=0.01,
        records_origin="baseline",
    )
    candidate = _report(
        segment_count=9,
        semantic_mean=0.70,
        orphan_rate=0.20,
        rel_artifact_rate=0.20,
        records_origin="hybrid",
    )

    audit = build_shadow_mode_audit(baseline, candidate)

    assert audit["summary"]["shadow_ready"] is False
    assert audit["summary"]["failure_count"] >= 1
    assert any(check["type"] == "segment_count_match" and not check["passed"] for check in audit["checks"])
