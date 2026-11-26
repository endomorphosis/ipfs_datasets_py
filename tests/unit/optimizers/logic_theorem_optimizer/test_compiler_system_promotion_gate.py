"""Final compiler-system promotion gate for Hammer/Leanstral LegalIR rollout."""

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
    COMPILER_SYSTEM_PROMOTION_SCHEMA_VERSION,
    COMPILER_SYSTEM_REQUIRED_CONFORMANCE_CAPABILITIES,
    COMPILER_SYSTEM_REQUIRED_DOMAINS,
    EXTERNAL_VALIDITY_BINDING_FIELDS,
    EXTERNAL_VALIDITY_PROMOTION_SCHEMA_VERSION,
    STAGED_ROLLOUT_SCHEMA_VERSION,
    compiler_system_promotion_gate,
    render_compiler_system_promotion_report,
)


ROOT = Path(__file__).resolve().parents[4]
COMMON_BINDINGS = {
    "compiler_commit": "compiler-system-unit",
    "fixed_canary_id": "fixed-canary-system-unit",
    "promotion_id": "promotion-system-unit",
    "source_export_id": "learned-export-system-unit",
    "split_manifest_digest": "sha256:" + "b" * 64,
}


def _bind(packet: dict[str, Any]) -> dict[str, Any]:
    result = dict(COMMON_BINDINGS)
    result.update(packet)
    return result


def _accepted_staged_decision() -> dict[str, Any]:
    return {
        "accepted": True,
        "failures": [],
        "metrics": {
            "completed_stages": [
                "short_smoke",
                "one_hour_hparam",
                "eight_hour_canary",
                "twenty_four_hour_production",
            ],
            "rollback_evidence": {
                "twenty_four_hour_production": {
                    "artifact_path": "workspace/rollout/production/rollback.json",
                    "baseline_revision": "baseline-system-unit",
                    "restorable": True,
                    "sha256": "c" * 64,
                }
            },
            "schema_version": STAGED_ROLLOUT_SCHEMA_VERSION,
        },
        "schema_version": STAGED_ROLLOUT_SCHEMA_VERSION,
        "warnings": [],
    }


def _accepted_external_validity_decision() -> dict[str, Any]:
    return {
        "accepted": True,
        "failures": [],
        "metrics": {
            "domain_status": {
                "external_benchmark_scores": True,
                "fuzzing": True,
                "hard_negatives": True,
                "leak_free_splits": True,
                "multi_seed_statistics": True,
                "poisoning_defenses": True,
                "rollback_readiness": True,
                "schema_compatibility": True,
                "semantic_metrics": True,
                "typed_decoding": True,
                "uncertainty": True,
            },
            "evidence_complete": True,
            "evidence_domains": {
                "rollback_readiness": {
                    "accepted": True,
                    "disable_action": "remove_promoted_compiler_system",
                    "rollback_id": "rollback-system-unit",
                    "restorable": True,
                    "schema_version": "legal-ir-drift-monitor-v1",
                }
            },
            "schema_version": EXTERNAL_VALIDITY_PROMOTION_SCHEMA_VERSION,
        },
        "schema_version": EXTERNAL_VALIDITY_PROMOTION_SCHEMA_VERSION,
        "warnings": [],
    }


def _complete_evidence() -> dict[str, Any]:
    capabilities = {
        capability: {"status": "passed"}
        for capability in COMPILER_SYSTEM_REQUIRED_CONFORMANCE_CAPABILITIES
    }
    return {
        **COMMON_BINDINGS,
        "evidence_bindings": dict(COMMON_BINDINGS),
        "external_validity": _accepted_external_validity_decision(),
        "schema_version": COMPILER_SYSTEM_PROMOTION_SCHEMA_VERSION,
        "staged_rollout": _accepted_staged_decision(),
        "evidence": {
            "apis": _bind(
                {
                    "cli_api_parity": True,
                    "daemon_free": True,
                    "schema_version": "legal-ir-compiler-api-v1",
                }
            ),
            "ambiguity": _bind(
                {
                    "all_resolved": True,
                    "learned_label_allowed": False,
                    "schema_version": "legal-ir-ambiguity-v1",
                    "unresolved_ambiguity_count": 0,
                }
            ),
            "backend_conformance": _bind(
                {
                    "promotion_allowed": True,
                    "schema_version": "legal-ir-backend-conformance-v1",
                }
            ),
            "citations": _bind(
                {
                    "resolved": True,
                    "schema_version": "legal-ir-citation-linker-v1",
                    "unresolved_citation_count": 0,
                }
            ),
            "compiler_source_maps": _bind(
                {
                    "schema_version": "legal-ir-source-map-v1",
                    "source_map_validation": {"valid": True},
                    "traceability_complete": True,
                }
            ),
            "conformance_evidence": _bind(
                {
                    "capabilities": capabilities,
                    "conformance_suite_passed": True,
                    "report_path": (
                        "docs/implementation/reports/LEGAL_IR_COMPILER_CONFORMANCE_REPORT.md"
                    ),
                }
            ),
            "diagnostics": _bind(
                {
                    "error_count": 0,
                    "lsp_ready": True,
                    "schema_version": "legal-ir-diagnostics-v1",
                }
            ),
            "evaluation_integrity": _bind(
                {
                    "fixed_canary": True,
                    "leak_free_splits": True,
                    "multi_seed": True,
                    "schema_version": "legal-ir-evaluation-integrity-v1",
                }
            ),
            "incremental_compilation": _bind(
                {
                    "cache_correct": True,
                    "invalidation_valid": True,
                    "schema_version": "legal-ir-incremental-compiler-v1",
                }
            ),
            "interoperability": _bind(
                {
                    "loss_markers_explicit": True,
                    "round_trip_conformant": True,
                    "schema_version": "legal-ir-interop-v1",
                    "unsupported_diagnostics_explicit": True,
                }
            ),
            "pass_management": _bind(
                {
                    "deterministic_order": True,
                    "schema_version": "legal-ir-pass-manager-v1",
                    "source_map_preserved": True,
                }
            ),
            "proof_carrying_artifacts": _bind(
                {
                    "native_reconstruction_verified": True,
                    "proof_checked": True,
                    "schema_version": "legal-ir-proof-carrying-artifact-v1",
                    "trusted": True,
                    "valid": True,
                }
            ),
            "reproducible_builds": _bind(
                {
                    "build_digest": "sha256:" + "d" * 64,
                    "deterministic": True,
                    "reproducible": True,
                    "schema_version": "legal-ir-build-manifest-v1",
                }
            ),
            "rollback_readiness": _bind(
                {
                    "disable_action": "remove_promoted_compiler_system",
                    "restorable": True,
                    "rollback_id": "rollback-system-unit",
                    "schema_version": "legal-ir-drift-monitor-v1",
                }
            ),
            "semantic_diffs": _bind(
                {
                    "available": True,
                    "classified": True,
                    "schema_version": "legal-ir-semantic-diff-v1",
                    "unclassified_change_count": 0,
                }
            ),
            "symbols": _bind(
                {
                    "resolved": True,
                    "schema_version": "legal-ir-symbol-table-v1",
                    "unresolved_symbol_count": 0,
                }
            ),
            "temporal_authority": _bind(
                {
                    "authority_complete": True,
                    "open_conflict_count": 0,
                    "schema_version": "legal-ir-temporal-authority-v1",
                }
            ),
        },
    }


def test_compiler_system_gate_accepts_complete_bound_evidence() -> None:
    result = compiler_system_promotion_gate(_complete_evidence())

    assert result.accepted is True
    assert result.failures == []
    assert result.metrics["evidence_complete"] is True
    assert set(result.metrics["domain_status"]) == set(COMPILER_SYSTEM_REQUIRED_DOMAINS)
    assert result.metrics["domain_status"]["proof_carrying_artifacts"] is True
    for field in EXTERNAL_VALIDITY_BINDING_FIELDS:
        assert result.metrics["bindings"][field]["canonical"] == COMMON_BINDINGS[field]


def test_compiler_system_gate_fails_closed_on_missing_domain() -> None:
    evidence = _complete_evidence()
    evidence["evidence"].pop("proof_carrying_artifacts")

    result = compiler_system_promotion_gate(evidence)

    assert result.accepted is False
    assert "compiler_system_evidence_missing:proof_carrying_artifacts" in result.failures
    assert result.metrics["domain_status"]["proof_carrying_artifacts"] is False


def test_compiler_system_gate_rejects_backend_block_and_conformance_gap() -> None:
    evidence = _complete_evidence()
    evidence["evidence"]["backend_conformance"]["promotion_allowed"] = False
    evidence["evidence"]["conformance_evidence"]["capabilities"].pop("semantic diff")
    evidence["evidence"]["conformance_evidence"].pop("report_path")

    result = compiler_system_promotion_gate(evidence)

    assert result.accepted is False
    assert "backend_conformance:promotion_allowed_false" in result.failures
    assert "backend_conformance:promotion_not_allowed" in result.failures
    assert "conformance_evidence:capability_missing:semantic diff" in result.failures


def test_compiler_system_report_renderer_lists_all_domains() -> None:
    result = compiler_system_promotion_gate(_complete_evidence())
    markdown = render_compiler_system_promotion_report(result)

    assert "Decision: `accepted`" in markdown
    assert "Rollback ready: `True`" in markdown
    for domain in COMPILER_SYSTEM_REQUIRED_DOMAINS:
        assert f"`{domain}`" in markdown


def test_compiler_system_gate_cli_writes_decision_and_report(tmp_path: Path) -> None:
    evidence_path = tmp_path / "compiler-system.json"
    decision_path = tmp_path / "decision.json"
    report_path = tmp_path / "promotion.md"
    evidence_path.write_text(json.dumps(_complete_evidence()), encoding="utf-8")

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.ops.legal_ir.hammer_leanstral_rollout_gate",
            "compiler-system-promotion-gate",
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
    assert decision["schema_version"] == COMPILER_SYSTEM_PROMOTION_SCHEMA_VERSION
    assert "Decision: `accepted`" in report_path.read_text(encoding="utf-8")


def _make_external_subgate_input(*, current):
    from tests.unit.optimizers.logic_theorem_optimizer.test_external_validity_promotion_gate import (
        _complete_evidence as complete_external_evidence,
    )

    evidence = complete_external_evidence()
    if current:
        evidence["evidence_bindings"].update(COMMON_BINDINGS)
        for packet in evidence["evidence"].values():
            packet.update(COMMON_BINDINGS)
    return evidence


def _save_external_subgate_decision(raw, tmp_path, capsys):
    from hashlib import sha256
    from scripts.ops.legal_ir.hammer_leanstral_rollout_gate import main

    input_path = tmp_path / "external-input.json"
    decision_path = tmp_path / "external-decision.json"
    encoded = json.dumps(raw).encode("utf-8")
    input_path.write_bytes(encoded)
    assert main([
        "external-validity-gate", "--evidence-path", str(input_path),
        "--evidence-output", str(decision_path),
    ]) == 0
    decision = json.loads(decision_path.read_text(encoding="utf-8"))
    assert json.loads(capsys.readouterr().out) == decision
    assert decision["evidence_sha256"] == sha256(encoded).hexdigest()
    assert decision["accepted"] is True
    assert all(
        decision["metrics"]["bindings"][key]["canonical"] == raw["evidence_bindings"][key]
        for key in EXTERNAL_VALIDITY_BINDING_FIELDS
    )
    return decision


@pytest.mark.parametrize("source", ("saved", "raw", "paired", "saved-with-current-labels"))
@pytest.mark.parametrize("stale", (False, True))
def test_compiler_system_checks_external_result_bindings(source, stale, tmp_path, capsys) -> None:
    evidence = _complete_evidence()
    raw = _make_external_subgate_input(current=not stale)
    if source == "raw":
        evidence["external_validity"] = raw
    else:
        saved = _save_external_subgate_decision(raw, tmp_path, capsys)
        if source == "saved-with-current-labels":
            saved.update(COMMON_BINDINGS)
        evidence["external_validity"] = saved
        if source == "paired":
            evidence["external_validity_evidence"] = raw
    result = compiler_system_promotion_gate(evidence)

    assert result.accepted is not stale
    if stale:
        for field in EXTERNAL_VALIDITY_BINDING_FIELDS:
            assert any(
                failure.startswith(f"external_validity_binding_mismatch:{field}:")
                for failure in result.failures
            )
    else:
        assert result.failures == []


def test_compiler_system_replays_raw_external_evidence_beside_an_accepted_decision(tmp_path, capsys) -> None:
    from scripts.ops.legal_ir.hammer_leanstral_rollout_gate import external_validity_promotion_gate

    evidence = _complete_evidence()
    raw = _make_external_subgate_input(current=True)
    evidence["external_validity"] = _save_external_subgate_decision(raw, tmp_path, capsys)
    raw["evidence"]["external_benchmark_scores"]["external_validity"].update(
        external_validity_score=0.5, failed_packet_ids=["fixture-rejected-packet"],
    )
    assert external_validity_promotion_gate(raw).accepted is False
    evidence["external_validity_evidence"] = raw

    result = compiler_system_promotion_gate(evidence)
    assert result.accepted is False
    assert any("fixture-rejected-packet" in failure for failure in result.failures)


@pytest.mark.parametrize("hidden_failure", (False, True))
def test_compiler_system_replays_real_external_benchmark_report(tmp_path, capsys, hidden_failure) -> None:
    from tests.unit.optimizers.logic_theorem_optimizer.test_external_validity_promotion_gate import (
        _actual_external_benchmark_report,
    )

    raw = _make_external_subgate_input(current=True)
    benchmark = _actual_external_benchmark_report()
    assert benchmark["accepted"] is True
    external = benchmark["external_validity"]
    assert external["packet_count"] == external["accepted_packet_count"] == len(external["packet_results"]) == 2
    raw["evidence"]["external_benchmark_scores"] = _bind(benchmark)
    evidence = _complete_evidence()
    evidence["external_validity"] = _save_external_subgate_decision(raw, tmp_path, capsys)
    if hidden_failure:
        external["packet_results"][1].update(
            accepted=False, status="failed", block_reasons=["fixture_source_mismatch"],
        )
    evidence["external_validity_evidence"] = raw

    result = compiler_system_promotion_gate(evidence)
    assert result.accepted is not hidden_failure
    scores = result.metrics["external_validity"]["evidence_domains"]["external_benchmark_scores"]
    assert scores["packet_count"] == 2
    if hidden_failure:
        assert scores["external_validity_score"] == 0.5
        assert "external_validity:external_benchmark_scores:packet_summary_mismatch" in result.failures
    else:
        assert scores["external_validity_score"] == 1.0
        assert result.failures == []


@pytest.mark.parametrize("evaluation", ["plain", "observation-alias", "unmeasured-arguments", "subset"])
def test_compiler_replays_selected_benchmark_semantic_coverage(evaluation):
    from dataclasses import replace
    from hashlib import sha256

    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_external_benchmark import (
        evaluate_external_legal_expert_benchmark,
        load_external_expert_benchmark_packets,
    )

    first, second = load_external_expert_benchmark_packets(
        ROOT / "tests" / "fixtures" / "legal_ir" / "external_expert_benchmark.jsonl")
    if evaluation == "unmeasured-arguments":
        reference = first.to_dict()["reference_ir"]
        reference["rules"][0]["arguments"] = ["agency", "notice"]
        first = replace(first, reference_ir=reference)
    selected = (first, second)
    digest_payload = json.dumps([packet.digest for packet in selected], separators=(",", ":")).encode()
    selected_population = {
        "benchmark_digest": "sha256:" + sha256(digest_payload).hexdigest(),
        "packet_ids": [packet.packet_id for packet in selected],
    }

    executed = selected[:1] if evaluation == "subset" else selected
    predictions = []
    for packet in executed:
        candidate = packet.to_dict()["reference_ir"]
        if evaluation == "observation-alias" and packet is first:
            candidate.update(candidate.pop("round_trip"))
        predictions.append({
            "packet_id": packet.packet_id,
            "packet_digest": packet.digest,
            "candidate_ir": candidate,
            "predicted_ir_families": list(packet.expected_ir_families),
            "citations": [citation.citation for citation in packet.citations],
            "proof_obligation_ids": list(packet.required_proof_obligation_ids),
            "decompiled_text": packet.decompiler_expectations.expected_reading,
            "round_trip_success": True,
        })
    benchmark = evaluate_external_legal_expert_benchmark(executed, predictions).to_dict()
    expect_complete = evaluation != "unmeasured-arguments"
    first_row = benchmark["external_validity"]["packet_results"][0]
    assert first_row["detail"]["semantic_equivalence"]["complete"] is expect_complete
    assert first_row["scores"]["semantic_equivalence"] == (1.0 if expect_complete else 0.0)
    assert benchmark["accepted"] is expect_complete

    raw = _make_external_subgate_input(current=True)
    raw["expected_external_benchmark"] = selected_population
    raw["evidence"]["external_benchmark_scores"] = _bind(benchmark)
    evidence = _complete_evidence()
    evidence.pop("external_validity")
    evidence["external_validity_evidence"] = raw
    gate = compiler_system_promotion_gate(evidence)
    result = gate.metrics["external_validity"]["evidence_domains"]["external_benchmark_scores"]
    assert result["packet_results_reconciled"] is True
    assert result["selected_population_reconciled"] is (evaluation != "subset")
    assert result["packet_count"] == len(executed)
    assert gate.accepted is (evaluation in {"plain", "observation-alias"}), gate.to_dict()
    if evaluation == "unmeasured-arguments":
        assert result["failed_packet_ids"] == [first.packet_id]
        assert result["external_validity_score"] == 0.5
    elif evaluation == "subset":
        assert "external_validity:external_benchmark_scores:selected_population_mismatch" in gate.failures


@pytest.mark.parametrize("alias", ["external_validity", "external_validity_evidence"])
@pytest.mark.parametrize("mode", ["nested-only", "matching-saved", "conflicting-saved"])
def test_compiler_replays_nested_external_gate_evidence(alias, mode, tmp_path, capsys):
    from tests.unit.optimizers.logic_theorem_optimizer.test_external_validity_promotion_gate import (
        _actual_external_benchmark_report,
    )
    from scripts.ops.legal_ir.hammer_leanstral_rollout_gate import external_validity_promotion_gate

    raw = _make_external_subgate_input(current=True)
    producer_report = _actual_external_benchmark_report()
    rows = producer_report["external_validity"]["packet_results"]
    assert producer_report["accepted"] is True and len(rows) == 2
    raw["expected_external_benchmark"] = {
        "benchmark_digest": producer_report["benchmark_digest"],
        "packet_ids": [row["packet_id"] for row in rows],
    }
    raw["evidence"]["external_benchmark_scores"] = _bind(producer_report)

    evidence = _complete_evidence()
    if mode == "nested-only":
        del evidence["external_validity"]
    else:
        evidence["external_validity"] = _save_external_subgate_decision(raw, tmp_path, capsys)
    if mode == "conflicting-saved":
        raw["expected_external_benchmark"]["packet_ids"].reverse()

    expected_acceptance = mode != "conflicting-saved"
    assert external_validity_promotion_gate(raw).accepted is expected_acceptance
    evidence["evidence"][alias] = raw
    decision = compiler_system_promotion_gate(evidence)

    assert decision.accepted is expected_acceptance, decision.failures
    if expected_acceptance:
        assert decision.failures == []
        scores = decision.metrics["external_validity"]["evidence_domains"]["external_benchmark_scores"]
        assert scores["selected_population_reconciled"] is True
    else:
        assert "external_validity:external_validity_inputs_disagree" in decision.failures
        assert "external_validity:external_benchmark_scores:selected_population_mismatch" in decision.failures


def test_compiler_keeps_legacy_nested_external_domain_status(tmp_path, capsys):
    raw = _make_external_subgate_input(current=True)
    evidence = _complete_evidence()
    evidence["external_validity"] = _save_external_subgate_decision(raw, tmp_path, capsys)
    evidence["evidence"]["external_validity"] = {"accepted": True}
    decision = compiler_system_promotion_gate(evidence)
    assert decision.accepted and decision.failures == []


@pytest.mark.parametrize(
    "case",
    ["matching", "different-clean-manifest", "detached-declared-digest", "no-declared-digest",
     "leak-hidden-by-compact-pass", "outer-guard-blocks", "nested-guard-blocks",
     "null-manifest", "invalid-manifest-schema"],
)
def test_compiler_binds_split_manifest_actually_validated(case):
    from dataclasses import replace

    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_eval_splits import (
        HOLDOUT_SPLIT,
        REPRESENTATION_PROMOTION_OPERATION,
        TRAIN_SPLIT,
        build_legal_ir_eval_splits,
    )

    def split_examples(prefix, *, shared_text=False):
        records = []
        for suffix in ("a", "b"):
            text_suffix = "shared" if shared_text else suffix
            records.append({
                "sample_id": f"{prefix}-{suffix}",
                "source_document_id": f"{prefix}-{suffix}",
                "source": "fictional-split-fixture",
                "citation": f"test-{prefix}-{suffix}",
                "jurisdiction": "fixture-jurisdiction",
                "statute_family": "fixture-procedure",
                "span_start": 0,
                "span_end": 44,
                "effective_date": "2020-01-01",
                "text": f"Fictional reference {prefix} {text_suffix} clause.",
            })
        return records

    selected = build_legal_ir_eval_splits(split_examples("selected"))
    actual = selected
    if case == "different-clean-manifest":
        actual = build_legal_ir_eval_splits(split_examples("different"))
        assert actual.digest != selected.digest
    elif case == "leak-hidden-by-compact-pass":
        source_group = build_legal_ir_eval_splits(split_examples("shared", shared_text=True))
        actual = replace(source_group, assignments={"shared-a": TRAIN_SPLIT, "shared-b": HOLDOUT_SPLIT})
        selected = actual
    assert actual.guard_result().passed is (case != "leak-hidden-by-compact-pass")

    def bind_selected_digest(value):
        if isinstance(value, dict):
            if "split_manifest_digest" in value:
                value["split_manifest_digest"] = selected.digest
            for field in value.values():
                bind_selected_digest(field)

    external = _make_external_subgate_input(current=True)
    evidence = _complete_evidence()
    for envelope in (external, evidence):
        bind_selected_digest(envelope)
        assert envelope["evidence_bindings"]["split_manifest_digest"] == selected.digest

    nested = actual.to_dict(include_digest=case != "no-declared-digest")
    split_packet = external["evidence"]["leak_free_splits"]
    blocked_guard = {
        "passed": True, "violations": [], "blocked_operations": [REPRESENTATION_PROMOTION_OPERATION],
    }
    if case == "detached-declared-digest":
        nested["split_manifest_digest"] = "sha256:" + "f" * 64
    elif case == "leak-hidden-by-compact-pass":
        # Both carried guards say pass, although the changed assignment actually leaks.
        passing_guard = {"passed": True, "violations": [], "blocked_operations": []}
        split_packet["legal_ir_split_guard"] = passing_guard
        nested["legal_ir_split_guard"] = passing_guard
    elif case == "outer-guard-blocks":
        split_packet["legal_ir_split_guard"] = blocked_guard
    elif case == "nested-guard-blocks":
        nested["legal_ir_split_guard"] = blocked_guard
    elif case == "null-manifest":
        nested = None
    elif case == "invalid-manifest-schema":
        nested["schema_version"] = "invalid-fixture-split-schema"

    split_packet["legal_ir_split_manifest"] = nested
    evidence["external_validity"] = external
    result = compiler_system_promotion_gate(evidence)
    should_pass = case in ("matching", "no-declared-digest")
    assert result.accepted is should_pass, result.failures
    external_metrics = result.metrics["external_validity"]
    details = external_metrics["evidence_domains"]["leak_free_splits"]
    if case in ("null-manifest", "invalid-manifest-schema"):
        assert "external_validity:leak_free_splits:split_manifest_invalid" in result.failures
        assert "validated_split_manifest_digest" not in details
        return

    actual_digest = "sha256:" + actual.digest.removeprefix("sha256:")
    assert details["validated_split_manifest_digest"] == actual.digest
    assert external_metrics["bindings"]["split_manifest_digest"]["sources"]["validated_split_manifest"] == actual_digest
    if should_pass:
        assert result.failures == [] and details["split_guard"]["passed"] is True
        assert result.metrics["bindings"]["split_manifest_digest"]["canonical"] == actual_digest
    elif case == "different-clean-manifest":
        assert details["split_guard"]["passed"] is True
        assert any(
            failure.startswith("external_validity:external_validity_binding_mismatch:split_manifest_digest:")
            for failure in result.failures
        )
    elif case == "detached-declared-digest":
        assert "external_validity:leak_free_splits:declared_split_manifest_digest_mismatch" in result.failures
    else:
        assert "external_validity:leak_free_splits:representation_promotion_blocked" in result.failures
        if case == "leak-hidden-by-compact-pass":
            assert details["split_guard"]["violations"]
