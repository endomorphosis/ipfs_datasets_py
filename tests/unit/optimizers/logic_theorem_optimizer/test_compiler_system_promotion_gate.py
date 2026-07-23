"""Final compiler-system promotion gate for Hammer/Leanstral LegalIR rollout."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

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
                        "docs/implementation/reports/"
                        "LEGAL_IR_COMPILER_CONFORMANCE_REPORT.md"
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
            str(ROOT / "scripts/ops/legal_ir/hammer_leanstral_rollout_gate.py"),
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
