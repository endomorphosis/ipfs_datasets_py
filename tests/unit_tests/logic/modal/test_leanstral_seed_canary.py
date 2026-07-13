"""Tests for the Leanstral five-task paired seed canary."""

from __future__ import annotations

import json
import importlib.util
import sys
from pathlib import Path

_SCRIPT_PATH = (
    Path(__file__).resolve().parents[4]
    / "scripts/ops/legal_ir/run_leanstral_seed_canary.py"
)
_SPEC = importlib.util.spec_from_file_location("run_leanstral_seed_canary", _SCRIPT_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_canary = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _canary
_SPEC.loader.exec_module(_canary)

SeedCanaryConfig = _canary.SeedCanaryConfig
PairedEvaluationMetrics = _canary.PairedEvaluationMetrics
build_dry_run_fixture_records = _canary.build_dry_run_fixture_records
compare_metrics = _canary.compare_metrics
render_markdown_report = _canary.render_markdown_report
run_seed_canary = _canary.run_seed_canary
write_markdown_report = _canary.write_markdown_report


def _records(count: int = 8):
    return build_dry_run_fixture_records(count=count)


def test_seed_canary_dry_run_selects_at_most_five_verified_tasks_without_mutation() -> None:
    result = run_seed_canary(
        _records(12),
        config=SeedCanaryConfig(dry_run=True, max_todos=99),
    )

    assert result.selected_task_count == 5
    assert result.verified_task_count == 5
    assert result.seeded_task_count == 0
    assert result.dry_run_no_mutation["queue_append_count"] == 0
    assert result.dry_run_no_mutation["source_mutation_count"] == 0
    assert result.promotion_allowed is False
    assert "dry_run_no_production_promotion" in result.promotion_blockers
    assert result.throughput_materially_improved is False
    assert result.throughput_improvement == 0.0
    assert result.projected_throughput_improvement > 0.0
    assert "no_real_evidence_records" in result.promotion_blockers
    assert "no_provider_or_verified_cache_evidence" in result.promotion_blockers
    assert "no_verifier_evidence" in result.promotion_blockers
    assert "no_seeded_tasks" in result.promotion_blockers
    assert "no_observed_paired_metrics" in result.promotion_blockers
    assert result.evidence_provenance_summary["synthetic_fixture_record_count"] > 0
    assert result.paired_metrics_provenance_summary["observed_improvement_task_count"] == 0
    assert result.paired_metrics_provenance_summary["synthetic_projection_task_count"] == 5
    assert not result.hard_guardrail_regressions


def test_seed_canary_report_contains_promotion_and_rollback_sections(tmp_path) -> None:
    result = run_seed_canary(
        _records(6),
        config=SeedCanaryConfig(dry_run=True, max_todos=3),
    )

    report = render_markdown_report(result)
    path = write_markdown_report(result, tmp_path / "seed.md")

    assert path.read_text(encoding="utf-8") == report
    for section in (
        "## Seeded Task Limit",
        "## Paired Evaluation Metrics",
        "## Evidence Provenance",
        "## Paired Metrics Provenance",
        "## Hard Guardrails",
        "## Throughput Decision",
        "## Task-To-Accepted-Patch Rate",
        "## Cycle Time",
        "## State-To-Patch Lag",
        "## Rollback Commands",
    ):
        assert section in report
    assert '"schema_version": "legal-ir-leanstral-seed-canary-v1"' in report
    assert "non-production dry run" in report


def test_seed_canary_blocks_promotion_when_hard_guardrail_regresses() -> None:
    records = _records(5)
    for record in records:
        record["leanstral_metrics"] = {
            "compiler_ir_cross_entropy": 0.9,
            "compiler_ir_cosine": 0.7,
            "learned_ir_view_cross_entropy": 0.8,
            "learned_ir_view_cosine": 0.72,
            "proof_validity": 1.0,
            "graph_validity": 1.0,
            "anti_copy_penalty": 0.05,
            "validation_rejection_rate": 0.4,
            "task_to_accepted_patch_rate": 0.4,
            "cycle_time_seconds": 5000.0,
            "state_to_patch_lag": 6.0,
        }
        record["control_metrics"] = {
            "compiler_ir_cross_entropy": 0.4,
            "compiler_ir_cosine": 0.9,
            "learned_ir_view_cross_entropy": 0.35,
            "learned_ir_view_cosine": 0.91,
            "proof_validity": 1.0,
            "graph_validity": 1.0,
            "anti_copy_penalty": 0.01,
            "validation_rejection_rate": 0.1,
            "task_to_accepted_patch_rate": 0.6,
            "cycle_time_seconds": 2000.0,
            "state_to_patch_lag": 2.0,
        }

    result = run_seed_canary(
        records,
        config=SeedCanaryConfig(dry_run=True, max_todos=5),
    )

    assert "compiler_ir_cross_entropy" in result.hard_guardrail_regressions
    assert "anti_copy_penalty" in result.hard_guardrail_regressions
    assert "compiler_ir_cross_entropy_regressed" in result.promotion_blockers
    assert result.throughput_materially_improved is False
    assert result.promotion_allowed is False


def test_seed_canary_requires_material_throughput_improvement() -> None:
    records = _records(5)
    for record in records:
        record["leanstral_metrics"] = {
            "compiler_ir_cross_entropy": 0.39,
            "compiler_ir_cosine": 0.91,
            "learned_ir_view_cross_entropy": 0.34,
            "learned_ir_view_cosine": 0.92,
            "proof_validity": 1.0,
            "graph_validity": 1.0,
            "anti_copy_penalty": 0.009,
            "validation_rejection_rate": 0.09,
            "task_to_accepted_patch_rate": 0.61,
            "cycle_time_seconds": 1980.0,
            "state_to_patch_lag": 1.98,
        }
        record["control_metrics"] = {
            "compiler_ir_cross_entropy": 0.4,
            "compiler_ir_cosine": 0.9,
            "learned_ir_view_cross_entropy": 0.35,
            "learned_ir_view_cosine": 0.91,
            "proof_validity": 1.0,
            "graph_validity": 1.0,
            "anti_copy_penalty": 0.01,
            "validation_rejection_rate": 0.1,
            "task_to_accepted_patch_rate": 0.6,
            "cycle_time_seconds": 2000.0,
            "state_to_patch_lag": 2.0,
        }

    result = run_seed_canary(
        records,
        config=SeedCanaryConfig(
            dry_run=True,
            max_todos=5,
            material_throughput_improvement=0.15,
        ),
    )

    assert not result.hard_guardrail_regressions
    assert result.throughput_materially_improved is False
    assert "compiler_development_throughput_not_materially_improved" in result.promotion_blockers
    assert result.paired_metrics_provenance_summary["observed_improvement_task_count"] == 0


def test_metric_comparison_uses_directional_guardrails() -> None:
    leanstral = PairedEvaluationMetrics(
        compiler_ir_cross_entropy=0.2,
        compiler_ir_cosine=0.95,
        learned_ir_view_cross_entropy=0.3,
        learned_ir_view_cosine=0.94,
        proof_validity=1.0,
        graph_validity=1.0,
        anti_copy_penalty=0.01,
        validation_rejection_rate=0.05,
        task_to_accepted_patch_rate=0.8,
        cycle_time_seconds=1000.0,
        state_to_patch_lag=1.0,
    )
    control = PairedEvaluationMetrics(
        compiler_ir_cross_entropy=0.4,
        compiler_ir_cosine=0.9,
        learned_ir_view_cross_entropy=0.5,
        learned_ir_view_cosine=0.88,
        proof_validity=1.0,
        graph_validity=1.0,
        anti_copy_penalty=0.02,
        validation_rejection_rate=0.1,
        task_to_accepted_patch_rate=0.5,
        cycle_time_seconds=2000.0,
        state_to_patch_lag=2.0,
    )

    comparisons = compare_metrics(leanstral, control)

    assert comparisons["compiler_ir_cross_entropy"].improved is True
    assert comparisons["compiler_ir_cosine"].improved is True
    assert comparisons["cycle_time_seconds"].relative_improvement == 0.5
    assert not any(comparison.regressed for comparison in comparisons.values())


def test_seed_canary_result_is_json_ready() -> None:
    result = run_seed_canary(
        _records(4),
        config=SeedCanaryConfig(dry_run=True, max_todos=4),
    )

    encoded = json.dumps(result.to_dict(), sort_keys=True)
    decoded = json.loads(encoded)

    assert decoded["selected_task_count"] == 4
    assert decoded["verified_task_count"] == 4
    assert decoded["aggregate_comparisons"]["compiler_ir_cross_entropy"]["regressed"] is False
    assert decoded["paired_metrics_provenance_summary"]["synthetic_metrics_reported_as_observed"] is False
