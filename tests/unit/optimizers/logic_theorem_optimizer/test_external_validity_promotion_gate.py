"""External-validity promotion gate for Hammer/Leanstral rollout."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from scripts.ops.legal_ir.hammer_leanstral_rollout_gate import (
    EXTERNAL_VALIDITY_PROMOTION_SCHEMA_VERSION,
    MULTI_SEED_PROMOTION_METRICS,
    MULTI_SEED_PROMOTION_SCHEMA_VERSION,
    external_validity_promotion_gate,
    render_external_validity_report,
)


ROOT = Path(__file__).resolve().parents[4]
COMMON_BINDINGS = {
    "compiler_commit": "compiler-external-validity",
    "fixed_canary_id": "fixed-canary-external-validity",
    "promotion_id": "promotion-external-validity",
    "source_export_id": "learned-export-external-validity",
    "split_manifest_digest": "sha256:" + "a" * 64,
}


def _bind(packet: dict[str, Any]) -> dict[str, Any]:
    result = dict(COMMON_BINDINGS)
    result.update(packet)
    return result


def _metric_payload(effects: tuple[float, ...] = (0.050, 0.055, 0.052, 0.058)) -> dict[str, Any]:
    seeds = (101, 103, 107, 109)
    return {
        "direction": "higher",
        "minimum_effect": 0.01,
        "seed_set": list(seeds[: len(effects)]),
        "seed_results": [
            {
                "baseline": 0.70,
                "candidate": 0.70 + effect,
                "failure_family": "none",
                "seed": seed,
            }
            for seed, effect in zip(seeds, effects)
        ],
    }


def _multi_seed_evidence() -> dict[str, Any]:
    return _bind(
        {
            "confidence_level": 0.95,
            "metrics": {metric: _metric_payload() for metric in MULTI_SEED_PROMOTION_METRICS},
            "min_seed_count": 3,
            "schema_version": MULTI_SEED_PROMOTION_SCHEMA_VERSION,
        }
    )


def _complete_evidence() -> dict[str, Any]:
    semantic_scores = {
        "counterexample_equivalence": 1.0,
        "decompiler_round_trip_preservation": 1.0,
        "graph_isomorphism": 1.0,
        "obligation_equivalence": 1.0,
        "proof_obligation_delta_score": 1.0,
        "structural_equivalence": 1.0,
        "temporal_window_agreement": 1.0,
    }
    return {
        "evidence_bindings": dict(COMMON_BINDINGS),
        "evidence": {
            "external_benchmark_scores": _bind(
                {
                    "accepted": True,
                    "external_validity": {
                        "external_validity_score": 1.0,
                        "failed_packet_ids": [],
                        "packet_count": 2,
                    },
                    "hard_guardrail": "external_benchmark_never_training_data",
                    "schema_version": "legal-ir-external-benchmark-report-v1",
                    "separate_from_internal_canary_metrics": True,
                    "status": "accepted",
                }
            ),
            "fuzzing": _bind(
                {
                    "failed_mutation_ids": [],
                    "mutation_count": 4,
                    "passed": True,
                    "schema_version": "legal-ir-metamorphic-differential-fuzzing-v1",
                    "trusted_negative_count": 2,
                }
            ),
            "hard_negatives": _bind(
                {
                    "accepted": True,
                    "false_positive_reduction": 0.12,
                    "hard_negative_guard_passed": True,
                    "negative_example_count": 8,
                    "schema_version": "legal-ir-hard-negative-effect-v1",
                    "trusted_positive_count": 5,
                    "trusted_positive_guard_passed": True,
                }
            ),
            "leak_free_splits": _bind(
                {
                    "accepted": True,
                    "leakage_count": 0,
                    "operation_allowed": True,
                    "representation_promotion_allowed": True,
                    "schema_version": "legal-ir-eval-splits-v1",
                    "violations": [],
                }
            ),
            "multi_seed_statistics": _multi_seed_evidence(),
            "poisoning_defenses": _bind(
                {
                    "accepted": True,
                    "blocks_promotion": True,
                    "blocks_training": True,
                    "hard_rule": "legal_source_text_is_data_not_instructions",
                    "poisoned_payloads_rejected": True,
                    "rejected_count": 3,
                    "schema_version": "legal-ir-premise-security-v1",
                    "tested_poisoning_families": ["prompt", "premise"],
                }
            ),
            "rollback_readiness": _bind(
                {
                    "accepted": True,
                    "hard_guardrail": "learned_guidance_is_reversible",
                    "rollback_decision": {"rollback_required": False},
                    "rollback_metadata": {
                        "disable_action": "remove_promoted_guidance_records",
                        "rollback_id": "rollback-external-validity",
                    },
                    "schema_version": "legal-ir-drift-monitor-v1",
                    "status": "stable",
                }
            ),
            "schema_compatibility": _bind(
                {
                    "compatibility": "compatible",
                    "issues": [],
                    "reusable": True,
                    "schema_version": "legal-ir-view-family-metric-v1",
                    "schema_version_id": "legal-ir-schema-evolution-v1",
                }
            ),
            "semantic_metrics": _bind(
                {
                    "accepted": True,
                    "schema_version": "legal-ir-semantic-equivalence-metrics-v1",
                    "scores": semantic_scores,
                    "status": "accepted",
                }
            ),
            "typed_decoding": _bind(
                {
                    "accepted": True,
                    "metrics": {
                        "legal_ir_grammar_rejection_count": 0,
                        "legal_ir_grammar_source_copy_placeholder_penalty": 0.0,
                        "legal_ir_grammar_syntactic_validity_success_rate": 1.0,
                    },
                    "schema_version": "legal-ir-typed-grammar-decoder-v1",
                }
            ),
            "uncertainty": _bind(
                {
                    "accepted": True,
                    "block_reasons": [],
                    "failed_families": [],
                    "promotion_allowed": True,
                    "schema_version": "legal-ir-uncertainty-v1",
                    "status": "accepted",
                    "unsupported_guidance_ids": [],
                }
            ),
        },
        "schema_version": EXTERNAL_VALIDITY_PROMOTION_SCHEMA_VERSION,
    }


def test_external_validity_gate_accepts_bound_complete_evidence() -> None:
    result = external_validity_promotion_gate(_complete_evidence())

    assert result.accepted is True
    assert result.failures == []
    assert result.metrics["evidence_complete"] is True
    assert result.metrics["domain_status"]["external_benchmark_scores"] is True
    assert result.metrics["bindings"]["promotion_id"]["canonical"] == COMMON_BINDINGS["promotion_id"]
    assert result.metrics["evidence_domains"]["multi_seed_statistics"]["metrics"]["seed_set"] == [
        "101",
        "103",
        "107",
        "109",
    ]


def test_external_validity_gate_fails_closed_on_missing_required_packets() -> None:
    evidence = _complete_evidence()
    evidence["evidence"].pop("typed_decoding")

    result = external_validity_promotion_gate(evidence)

    assert result.accepted is False
    assert "external_validity_evidence_missing:typed_decoding" in result.failures
    assert result.metrics["domain_status"]["typed_decoding"] is False


def test_external_validity_gate_rejects_inconsistent_binding_and_metric_regression() -> None:
    evidence = _complete_evidence()
    evidence["evidence"]["semantic_metrics"]["scores"].pop("graph_isomorphism")
    evidence["evidence"]["fuzzing"]["compiler_commit"] = "different-compiler"

    result = external_validity_promotion_gate(evidence)

    assert result.accepted is False
    assert "semantic_metrics:metric_missing:graph_isomorphism" in result.failures
    assert any(
        failure.startswith("external_validity_binding_mismatch:compiler_commit")
        for failure in result.failures
    )


def test_external_validity_gate_recomputes_multi_seed_statistics() -> None:
    evidence = _complete_evidence()
    evidence["evidence"]["multi_seed_statistics"]["metrics"]["learned_quality"] = _metric_payload(
        effects=(0.20,)
    )

    result = external_validity_promotion_gate(evidence)

    assert result.accepted is False
    assert (
        "multi_seed_statistics:multi_seed_metric_seed_count:learned_quality:1<3"
        in result.failures
    )


def test_external_validity_report_renderer_lists_all_domains() -> None:
    result = external_validity_promotion_gate(_complete_evidence())
    markdown = render_external_validity_report(result)

    assert "Decision: `accepted`" in markdown
    for domain in (
        "leak_free_splits",
        "semantic_metrics",
        "typed_decoding",
        "external_benchmark_scores",
        "rollback_readiness",
    ):
        assert f"`{domain}`" in markdown


def test_external_validity_cli_writes_decision_and_report(tmp_path: Path) -> None:
    evidence_path = tmp_path / "external-validity.json"
    decision_path = tmp_path / "decision.json"
    report_path = tmp_path / "report.md"
    evidence_path.write_text(json.dumps(_complete_evidence()), encoding="utf-8")

    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/ops/legal_ir/hammer_leanstral_rollout_gate.py"),
            "external-validity-gate",
            "--evidence-path",
            str(evidence_path),
            "--evidence-output",
            str(decision_path),
            "--report-output",
            str(report_path),
        ],
        check=False,
        cwd=ROOT,
        text=True,
        capture_output=True,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    decision = json.loads(decision_path.read_text(encoding="utf-8"))
    assert decision["accepted"] is True
    assert decision["schema_version"] == EXTERNAL_VALIDITY_PROMOTION_SCHEMA_VERSION
    assert "Decision: `accepted`" in report_path.read_text(encoding="utf-8")
