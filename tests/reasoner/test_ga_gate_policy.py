from __future__ import annotations

from ipfs_datasets_py.processors.legal_data.reasoner.shadow_mode import build_ga_gate_assessment


def _shadow(*, ready: bool, failures: int) -> dict:
    return {"summary": {"shadow_ready": ready, "failure_count": failures}}


def _canary(*, hybrid_enabled: bool) -> dict:
    return {"hybrid_enabled": hybrid_enabled}


def _report(*, semantic: float, keyphrase: float, enum_ok: float, relation: float, orphan: float, rel_artifact: float, blocker: bool = False) -> dict:
    return {
        "summary": {
            "semantic_similarity_final_decoded_mean": semantic,
            "final_decoded_keyphrase_retention_mean": keyphrase,
            "final_decoded_enumeration_integrity_mean": enum_ok,
            "flogic_relation_coverage_mean": relation,
            "final_decoded_orphan_terminal_rate": orphan,
            "final_decoded_relative_clause_artifact_rate": rel_artifact,
            "theorem_ingestion_blocker": blocker,
        }
    }


def test_ga_gate_ready_when_all_checks_pass() -> None:
    assessment = build_ga_gate_assessment(
        _shadow(ready=True, failures=0),
        _canary(hybrid_enabled=True),
        _report(
            semantic=0.95,
            keyphrase=0.82,
            enum_ok=0.72,
            relation=0.60,
            orphan=0.01,
            rel_artifact=0.01,
        ),
        runtime_stats={"p95_latency_ms": 1200.0, "timeout_rate": 0.0, "error_rate": 0.0},
    )

    assert assessment["summary"]["ga_ready"] is True
    assert assessment["summary"]["failure_count"] == 0


def test_ga_gate_fails_on_latency_or_quality_violations() -> None:
    assessment = build_ga_gate_assessment(
        _shadow(ready=True, failures=0),
        _canary(hybrid_enabled=True),
        _report(
            semantic=0.80,
            keyphrase=0.60,
            enum_ok=0.60,
            relation=0.40,
            orphan=0.20,
            rel_artifact=0.20,
            blocker=True,
        ),
        runtime_stats={"p95_latency_ms": 9000.0, "timeout_rate": 0.05, "error_rate": 0.05},
    )

    assert assessment["summary"]["ga_ready"] is False
    assert assessment["summary"]["failure_count"] >= 1


def test_ga_gate_can_skip_latency_when_policy_allows_missing_stats() -> None:
    assessment = build_ga_gate_assessment(
        _shadow(ready=True, failures=0),
        _canary(hybrid_enabled=True),
        _report(
            semantic=0.95,
            keyphrase=0.82,
            enum_ok=0.72,
            relation=0.60,
            orphan=0.01,
            rel_artifact=0.01,
        ),
        runtime_stats=None,
        require_latency_stats=False,
    )

    assert assessment["summary"]["ga_ready"] is True
    assert any(c.get("type") == "latency_stats_skipped" and c.get("passed") for c in assessment["checks"])
