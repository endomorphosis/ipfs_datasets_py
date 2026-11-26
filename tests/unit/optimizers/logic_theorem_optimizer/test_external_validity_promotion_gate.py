"""External-validity promotion gate for Hammer/Leanstral rollout."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

_DATASETS_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(_DATASETS_ROOT))
for _name in list(sys.modules):
    if _name == "scripts" or _name.startswith("scripts."):
        sys.modules.pop(_name, None)

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
    assert (
        result.metrics["bindings"]["promotion_id"]["canonical"] == COMMON_BINDINGS["promotion_id"]
    )
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
        "multi_seed_statistics:multi_seed_metric_seed_count:learned_quality:1<3" in result.failures
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
            "-m",
            "scripts.ops.legal_ir.hammer_leanstral_rollout_gate",
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


def _actual_external_benchmark_report():
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_external_benchmark import (
        evaluate_external_legal_expert_benchmark,
        load_external_expert_benchmark_packets,
    )

    packets = load_external_expert_benchmark_packets(
        ROOT / "tests" / "fixtures" / "legal_ir" / "external_expert_benchmark.jsonl"
    )
    predictions = [
        {
            "packet_id": packet.packet_id,
            "packet_digest": packet.digest,
            "candidate_ir": packet.reference_ir,
            "predicted_ir_families": list(packet.expected_ir_families),
            "citations": [citation.citation for citation in packet.citations],
            "proof_obligation_ids": list(packet.required_proof_obligation_ids),
            "decompiled_text": packet.decompiler_expectations.expected_reading,
            "round_trip_success": True,
        }
        for packet in packets
    ]
    return evaluate_external_legal_expert_benchmark(packets, predictions).to_dict()


def test_external_validity_gate_accepts_consistent_produced_packet_rows() -> None:
    evidence = _complete_evidence()
    report = _actual_external_benchmark_report()
    assert report["accepted"] and len(report["external_validity"]["packet_results"]) == 2
    evidence["evidence"]["external_benchmark_scores"] = _bind(report)
    result = external_validity_promotion_gate(evidence)

    assert result.accepted is True
    assert result.failures == []


@pytest.mark.parametrize(
    "mutation",
    (
        "hidden-failure", "duplicate-row-identity", "nonboolean-row-acceptance",
        "contradictory-row-status", "missing-rows", "null-rows", "count-drift",
        "accepted-count-drift", "score-drift",
    ),
)
def test_external_validity_gate_refuses_inconsistent_produced_packet_rows(mutation) -> None:
    evidence = _complete_evidence()
    report = _actual_external_benchmark_report()
    external = report["external_validity"]
    rows = external["packet_results"]
    if mutation == "hidden-failure":
        rows[1].update(accepted=False, status="failed", block_reasons=["fixture_source_mismatch"])
    elif mutation == "duplicate-row-identity":
        rows[1]["packet_id"] = rows[0]["packet_id"]
    elif mutation == "nonboolean-row-acceptance":
        rows[1]["accepted"] = 1
    elif mutation == "contradictory-row-status":
        rows[1]["status"] = "failed"
    elif mutation == "missing-rows":
        del external["packet_results"]
    elif mutation == "null-rows":
        external["packet_results"] = None
    elif mutation == "count-drift":
        external["packet_count"] += 1
    elif mutation == "accepted-count-drift":
        external["accepted_packet_count"] -= 1
    else:
        external["external_validity_score"] = 1.1

    evidence["evidence"]["external_benchmark_scores"] = _bind(report)
    result = external_validity_promotion_gate(evidence)

    assert result.accepted is False
    assert result.metrics["domain_status"]["external_benchmark_scores"] is False
    assert any(
        failure.startswith("external_benchmark_scores:packet_")
        for failure in result.failures
    )


@pytest.mark.parametrize("hidden_failure", (False, True))
def test_external_validity_cli_checks_produced_packet_rows_in_process(tmp_path, capsys, hidden_failure) -> None:
    from hashlib import sha256

    from scripts.ops.legal_ir.hammer_leanstral_rollout_gate import main

    evidence = _complete_evidence()
    report = _actual_external_benchmark_report()
    external = report["external_validity"]
    assert len(external["packet_results"]) == external["accepted_packet_count"] == 2
    if hidden_failure:
        external["packet_results"][1].update(
            accepted=False, status="failed", block_reasons=["fixture_source_mismatch"],
        )
    evidence["evidence"]["external_benchmark_scores"] = _bind(report)

    evidence_path = tmp_path / "external-validity.json"
    decision_path = tmp_path / "decision.json"
    report_path = tmp_path / "report.md"
    raw_evidence = json.dumps(evidence).encode("utf-8")
    evidence_path.write_bytes(raw_evidence)
    exit_code = main([
        "external-validity-gate",
        "--evidence-path", str(evidence_path),
        "--evidence-output", str(decision_path),
        "--report-output", str(report_path),
    ])
    decision = json.loads(decision_path.read_text(encoding="utf-8"))
    assert json.loads(capsys.readouterr().out) == decision
    assert decision["evidence_sha256"] == sha256(raw_evidence).hexdigest()
    assert exit_code == int(hidden_failure)
    assert decision["accepted"] is not hidden_failure
    assert ("Decision: `blocked`" if hidden_failure else "Decision: `accepted`") in (
        report_path.read_text(encoding="utf-8")
    )
    if hidden_failure:
        assert "external_benchmark_scores:packet_summary_mismatch" in decision["failures"]


@pytest.mark.parametrize("evaluation", ["complete", "subset", "reordered"])
def test_external_validity_gate_honors_independently_selected_benchmark_population(evaluation):
    from hashlib import sha256

    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_external_benchmark import (
        evaluate_external_legal_expert_benchmark,
        load_external_expert_benchmark_packets,
    )

    selected = load_external_expert_benchmark_packets(
        ROOT / "tests" / "fixtures" / "legal_ir" / "external_expert_benchmark.jsonl")
    assert len(selected) == 2
    digest_payload = json.dumps([packet.digest for packet in selected], separators=(",", ":")).encode()
    expected = {
        "benchmark_digest": "sha256:" + sha256(digest_payload).hexdigest(),
        "packet_ids": [packet.packet_id for packet in selected],
    }
    evaluated = selected if evaluation == "complete" else (
        selected[:1] if evaluation == "subset" else tuple(reversed(selected)))
    predictions = [{
        "packet_id": packet.packet_id,
        "candidate_ir": packet.reference_ir,
        "predicted_ir_families": list(packet.expected_ir_families),
        "citations": [citation.citation for citation in packet.citations],
        "proof_obligation_ids": list(packet.required_proof_obligation_ids),
        "decompiled_text": packet.decompiler_expectations.expected_reading,
        "round_trip_success": True,
    } for packet in evaluated]
    report = evaluate_external_legal_expert_benchmark(evaluated, predictions).to_dict()
    assert report["accepted"]
    assert report["external_validity"]["packet_count"] == len(evaluated)
    evidence = _complete_evidence()
    evidence["expected_external_benchmark"] = expected
    evidence["evidence"]["external_benchmark_scores"] = _bind(report)
    result = external_validity_promotion_gate(evidence)
    assert result.accepted is (evaluation == "complete"), result.to_dict()
    check = result.metrics["evidence_domains"]["external_benchmark_scores"]
    assert check["packet_results_reconciled"] is True
    assert check["selected_population_reconciled"] is (evaluation == "complete")
    if evaluation != "complete":
        assert "external_benchmark_scores:selected_population_mismatch" in result.failures


def test_external_validity_gate_does_not_promote_unmeasured_legacy_ir() -> None:
    from dataclasses import replace

    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_external_benchmark import (
        evaluate_external_legal_expert_benchmark,
        load_external_expert_benchmark_packets,
    )

    packet = load_external_expert_benchmark_packets(
        ROOT / "tests" / "fixtures" / "legal_ir" / "external_expert_benchmark.jsonl")[0]
    reference = packet.to_dict()["reference_ir"]
    reference["rules"][0]["arguments"] = ["agency", "notice"]
    packet = replace(packet, reference_ir=reference)
    prediction = {
        "packet_id": packet.packet_id, "candidate_ir": packet.reference_ir,
        "predicted_ir_families": list(packet.expected_ir_families),
        "citations": [citation.citation for citation in packet.citations],
        "proof_obligation_ids": list(packet.required_proof_obligation_ids),
        "decompiled_text": packet.decompiler_expectations.expected_reading,
        "round_trip_success": True,
    }
    report = evaluate_external_legal_expert_benchmark([packet], [prediction]).to_dict()
    diagnostic = report["external_validity"]["packet_results"][0]["detail"]["semantic_equivalence"]
    assert diagnostic["complete"] is False
    assert set(diagnostic["missing_metrics"]) == {"structural_equivalence", "obligation_equivalence"}
    assert set(diagnostic["scores"].values()) == {1.0}
    evidence = _complete_evidence()
    evidence["evidence"]["external_benchmark_scores"] = _bind(report)
    result = external_validity_promotion_gate(evidence)
    assert not result.accepted, result.to_dict()
    assert not result.metrics["domain_status"]["external_benchmark_scores"]


@pytest.mark.parametrize("case", ["duplicate-expected-identity", "summary-without-rows"])
def test_external_validity_gate_refuses_unverifiable_selected_benchmark(case):
    evidence = _complete_evidence()
    report = _actual_external_benchmark_report()
    expected = {
        "benchmark_digest": report["benchmark_digest"],
        "packet_ids": [row["packet_id"] for row in report["external_validity"]["packet_results"]],
    }
    if case == "duplicate-expected-identity":
        expected["packet_ids"].append(expected["packet_ids"][0])
        evidence["evidence"]["external_benchmark_scores"] = _bind(report)
        expected_blocker = "external_benchmark_scores:selected_population_invalid"
    else:
        expected_blocker = "external_benchmark_scores:selected_population_unreconciled"
    evidence["expected_external_benchmark"] = expected
    result = external_validity_promotion_gate(evidence)
    assert result.accepted is False, result.to_dict()
    assert expected_blocker in result.failures
