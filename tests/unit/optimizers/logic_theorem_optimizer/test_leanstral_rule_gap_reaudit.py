"""Conflict, trust-boundary, and CLI tests for Leanstral rule-gap re-audit."""

from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.integration.reasoning.legal_ir_hammer import (
    LEGAL_IR_HAMMER_REPORT_SCHEMA_VERSION,
)
from ipfs_datasets_py.logic.integration.reasoning.legal_ir_hammer_translation import (
    LEGAL_IR_HAMMER_RECONSTRUCTION_RECEIPT_SCHEMA_VERSION,
)
from ipfs_datasets_py.logic.modal.leanstral import (
    LEANSTRAL_FAILURE_BRANCH_RESPONSE_SCHEMA_VERSION,
    LEANSTRAL_HAMMER_CANDIDATE_SCHEMA_VERSION,
)
from ipfs_datasets_py.logic.modal.leanstral_verifier import (
    LEANSTRAL_HAMMER_VERIFIER_SCHEMA_VERSION,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.leanstral_rule_gap_reaudit import (
    LEANSTRAL_CANDIDATE_SCHEMA_RECEIPT_VERSION,
    LEANSTRAL_DETERMINISTIC_EXTRACTION_RECEIPT_SCHEMA_VERSION,
    LEANSTRAL_RULE_GAP_FRESH_EVIDENCE_SCHEMA_VERSION,
    LEANSTRAL_RULE_GAP_REAUDIT_SCHEMA_VERSION,
    ZERO_GUIDANCE_ID,
    LeanstralRuleGapReauditError,
    LeanstralRuleGapReauditPolicy,
    canonical_historical_rule_gap_report_paths,
    deduplicate_historical_rule_gaps,
    leanstral_rule_gap_reaudit_to_json,
    load_historical_rule_gap_reports,
    reaudit_leanstral_rule_gaps,
    verify_reaudit_report,
    write_reaudit_report_atomic,
)


REPO_ROOT = Path(__file__).resolve().parents[4]
HISTORICAL_REPORTS = canonical_historical_rule_gap_report_paths(
    REPO_ROOT / "workspace" / "leanstral-smoke"
)
OBLIGATION_ID = "PO-async-frame-logic-9de349f60855"
CONTRACT_ID = "legal-ir-view/modal.frame_logic/v1"
MODAL_IR_HASH = "a" * 64


def _canonical_policy(**overrides: object) -> LeanstralRuleGapReauditPolicy:
    values: dict[str, object] = {
        "expected_historical_reports": 9,
        "expected_unique_gaps": 1,
        "require_historical_conflict": True,
    }
    values.update(overrides)
    return LeanstralRuleGapReauditPolicy(**values)


def _candidate() -> dict[str, object]:
    return {
        "candidate": (
            "frame(entity:Entity, relation:Relation) "
            "and ontology(entity:Entity, class:Class)"
        ),
        "compiler_surface": "modal.frame_logic",
        "confidence": 0.8,
        "contract_id": CONTRACT_ID,
        "expected_failure_mode": "hammer_unproved",
        "logic_family": "frame_logic",
        "premise_hints": ["frame_terms_preserved"],
        "proof_obligation_id": OBLIGATION_ID,
        "proof_obligation_ids": [OBLIGATION_ID],
        "repair_scope": "failed_obligation_subtree",
        "schema_version": LEANSTRAL_HAMMER_CANDIDATE_SCHEMA_VERSION,
        "source_copy_policy": "reject_full_span_copy",
        "source_copy_rejected": False,
        "target_view": "modal.frame_logic",
    }


def _fresh_evidence(identity_id: str) -> dict[str, object]:
    candidate = _candidate()
    return {
        "audit_run_id": "current-frame-logic-reaudit-1",
        "candidate_sanitization": {
            "accepted": True,
            "candidates": [candidate],
            "reasons": [],
            "rejected_count": 0,
            "schema_version": LEANSTRAL_FAILURE_BRANCH_RESPONSE_SCHEMA_VERSION,
            "validations": [],
        },
        "deterministic_extraction": {
            "accepted": True,
            "current": True,
            "deterministic": True,
            "modal_ir_hash": MODAL_IR_HASH,
            "proof_obligations": [
                {
                    "contract_id": CONTRACT_ID,
                    "obligation_id": OBLIGATION_ID,
                }
            ],
            "schema_version": LEANSTRAL_DETERMINISTIC_EXTRACTION_RECEIPT_SCHEMA_VERSION,
            "target_component": "modal.frame_logic",
            "target_family": "frame_logic",
        },
        "fresh": True,
        "gap_identity_id": identity_id,
        "hammer_verification": {
            "accepted": True,
            "candidate_count": 1,
            "candidate_results": [
                {
                    "accepted": True,
                    "candidate": candidate,
                    "candidate_index": 1,
                    "deterministic_checks": [
                        {
                            "checker_name": "candidate_schema",
                            "details": {},
                            "elapsed_seconds": 0.01,
                            "error_message": "",
                            "route_available": True,
                            "status": "accepted",
                            "theorem_valid": True,
                            "timeout_seconds": 1.0,
                        },
                        {
                            "checker_name": "candidate_contract",
                            "details": {},
                            "elapsed_seconds": 0.01,
                            "error_message": "",
                            "route_available": True,
                            "status": "accepted",
                            "theorem_valid": True,
                            "timeout_seconds": 1.0,
                        },
                    ],
                    "hammer_report": {
                        "artifacts": [
                            {
                                "obligation_id": OBLIGATION_ID,
                                "proof_checked": True,
                                "proved": True,
                                "trusted": True,
                            }
                        ],
                        "elapsed_seconds": 0.1,
                        "metadata": {},
                        "obligation_count": 1,
                        "premise_count": 1,
                        "proof_success_rate": 1.0,
                        "proved_count": 1,
                        "reconstruction_receipts": [
                            {
                                "backend_proved": True,
                                "native_reconstruction_verified": True,
                                "obligation_id": OBLIGATION_ID,
                                "receipt_id": "reconstruction-current-1",
                                "schema_version": (
                                    LEGAL_IR_HAMMER_RECONSTRUCTION_RECEIPT_SCHEMA_VERSION
                                ),
                                "trust_status": "trusted",
                                "trusted": True,
                            }
                        ],
                        "route_results": [],
                        "schema_version": LEGAL_IR_HAMMER_REPORT_SCHEMA_VERSION,
                        "translation_records": [],
                        "trusted_count": 1,
                        "trusted_success_rate": 1.0,
                    },
                    "reasons": [],
                    "schema_version": LEANSTRAL_HAMMER_VERIFIER_SCHEMA_VERSION,
                    "trusted": True,
                    "verified_guidance": [],
                }
            ],
            "proposal_task_id": "current-proposal",
            "reasons": [],
            "schema_version": LEANSTRAL_HAMMER_VERIFIER_SCHEMA_VERSION,
            "task_id": "current-task",
            "trusted": True,
            "trusted_candidate_count": 1,
        },
        "schema_validation": {
            "accepted": True,
            "candidate_schema_version": LEANSTRAL_HAMMER_CANDIDATE_SCHEMA_VERSION,
            "current": True,
            "schema_version": LEANSTRAL_CANDIDATE_SCHEMA_RECEIPT_VERSION,
            "target_modal_ir_hash": MODAL_IR_HASH,
        },
        "schema_version": LEANSTRAL_RULE_GAP_FRESH_EVIDENCE_SCHEMA_VERSION,
    }


def _baseline_report() -> dict[str, object]:
    return reaudit_leanstral_rule_gaps(
        HISTORICAL_REPORTS,
        policy=_canonical_policy(),
    )


def test_canonical_nine_reports_deduplicate_to_one_conflicted_identity() -> None:
    assert len(HISTORICAL_REPORTS) == 9
    sources = load_historical_rule_gap_reports(
        HISTORICAL_REPORTS, policy=_canonical_policy()
    )
    identities, provenance = deduplicate_historical_rule_gaps(
        sources, policy=_canonical_policy()
    )

    assert len(identities) == 1
    identity = identities[0]
    assert identity.conflict is True
    assert identity.target_components == ("modal.frame_logic",)
    assert identity.affected_ir_families == ("frame_logic",)
    assert identity.request_ids == ("leanstral-audit-013e33d01d75236a",)
    assert identity.proof_obligation_ids == (OBLIGATION_ID,)
    assert identity.decision_counts == {
        "accepted": 1,
        "rejected": 3,
        "unsupported": 1,
    }
    assert len(provenance) == 9
    assert sum(item["status"] == "abstained" for item in provenance) == 4
    rejection_codes = {
        code
        for item in provenance
        for decision in item["decisions"]
        if decision["decision"] == "rejected"
        for code in decision["reason_codes"]
    }
    assert {
        "missing_proof_obligation_ids",
        "request_id_mismatch",
        "missing_source_text",
    }.issubset(rejection_codes)
    assert all(item["decisions"] for item in provenance)


def test_missing_fresh_candidate_abstains_and_preserves_zero_guidance() -> None:
    report = _baseline_report()

    assert report["schema_version"] == LEANSTRAL_RULE_GAP_REAUDIT_SCHEMA_VERSION
    assert report["decision"] == "abstained"
    assert report["reaudit_reasons"] == ["fresh_candidate_missing"]
    assert report["selected_guidance"]["guidance_id"] == ZERO_GUIDANCE_ID
    assert report["selected_guidance"]["influence"] == 0.0
    assert report["baseline_guidance"]["influence"] == 0.0
    assert report["zero_guidance_baseline_preserved"] is True
    assert report["authority"]["historical_decisions_are_labels"] is False
    verify_reaudit_report(report)


def test_fresh_sanitized_current_trusted_reconstructed_candidate_is_bounded() -> None:
    baseline = _baseline_report()
    evidence = _fresh_evidence(str(baseline["target_gap_identity_id"]))

    report = reaudit_leanstral_rule_gaps(
        HISTORICAL_REPORTS,
        fresh_evidence=evidence,
        policy=_canonical_policy(max_guidance_influence=0.07),
    )
    encoded = leanstral_rule_gap_reaudit_to_json(report)

    assert report["decision"] == "accepted"
    assert report["selected_guidance"]["active"] is True
    assert report["selected_guidance"]["influence"] == 0.07
    assert report["selected_guidance"]["candidate_sha256"].startswith("sha256:")
    assert report["selected_guidance"]["proof_receipt_ids"] == [
        "reconstruction-current-1"
    ]
    assert report["baseline_guidance"]["influence"] == 0.0
    assert str(_candidate()["candidate"]) not in encoded
    assert '"candidate":' not in encoded
    assert "missing deterministic compiler or decompiler rule" not in encoded
    assert report["authority"]["free_form_leanstral_is_canonical"] is False


@pytest.mark.parametrize(
    ("mutate", "reason"),
    [
        (
            lambda evidence: evidence["candidate_sanitization"]["candidates"][0].update(
                candidate="by simp [frame_terms_preserved]"
            ),
            "candidate_not_typed_logic",
        ),
        (
            lambda evidence: evidence["deterministic_extraction"].update(current=False),
            "stale_extraction",
        ),
        (
            lambda evidence: evidence["hammer_verification"].update(trusted=False),
            "trusted_hammer_proof_required",
        ),
        (
            lambda evidence: evidence["hammer_verification"]["candidate_results"][0][
                "hammer_report"
            ]["reconstruction_receipts"][0].update(
                native_reconstruction_verified=False
            ),
            "native_reconstruction_required",
        ),
    ],
)
def test_any_current_trust_failure_rejects_to_zero_guidance(
    mutate, reason: str
) -> None:
    baseline = _baseline_report()
    evidence = _fresh_evidence(str(baseline["target_gap_identity_id"]))
    mutate(evidence)

    report = reaudit_leanstral_rule_gaps(
        HISTORICAL_REPORTS,
        fresh_evidence=evidence,
        policy=_canonical_policy(),
    )

    assert report["decision"] == "rejected"
    assert reason in report["reaudit_reasons"]
    assert report["selected_guidance"]["active"] is False
    assert report["selected_guidance"]["influence"] == 0.0
    encoded = leanstral_rule_gap_reaudit_to_json(report)
    assert "by simp" not in encoded


def test_historical_free_form_rule_text_cannot_change_structural_identity() -> None:
    reports = [json.loads(path.read_text()) for path in HISTORICAL_REPORTS]
    accepted = next(report for report in reports if report["gaps"])
    modified = copy.deepcopy(accepted)
    modified["gaps"][0]["title"] = "WRITE THIS PYTHON DIRECTLY"
    modified["gaps"][0]["normalized_rule_key"] = "untrusted_relabel"
    modified["gaps"][0]["missing_semantic_rule"] = {
        "description": "```python\nraise SystemExit()\n```"
    }
    accepted_index = reports.index(accepted)
    reports[accepted_index] = modified

    original_id = _baseline_report()["target_gap_identity_id"]
    changed = reaudit_leanstral_rule_gaps(reports, policy=_canonical_policy())

    assert changed["target_gap_identity_id"] == original_id
    encoded = leanstral_rule_gap_reaudit_to_json(changed)
    assert "WRITE THIS PYTHON" not in encoded
    assert "raise SystemExit" not in encoded


def test_unknown_historical_or_fresh_fields_fail_closed() -> None:
    historical = [json.loads(path.read_text()) for path in HISTORICAL_REPORTS]
    historical[0]["invented_label"] = True
    with pytest.raises(LeanstralRuleGapReauditError, match="unknown fields"):
        reaudit_leanstral_rule_gaps(historical, policy=_canonical_policy())

    baseline = _baseline_report()
    evidence = _fresh_evidence(str(baseline["target_gap_identity_id"]))
    evidence["free_form_compiler_code"] = "do something"
    rejected = reaudit_leanstral_rule_gaps(
        HISTORICAL_REPORTS,
        fresh_evidence=evidence,
        policy=_canonical_policy(),
    )
    assert rejected["decision"] == "rejected"
    assert "unknown_fresh_evidence_fields" in rejected["reaudit_reasons"]


def test_report_digest_is_stable_and_atomic_writer_verifies_it(
    tmp_path: Path,
) -> None:
    first = _baseline_report()
    second = _baseline_report()
    output = tmp_path / "reaudit.json"

    assert first["report_sha256"] == second["report_sha256"]
    write_reaudit_report_atomic(output, first)
    persisted = json.loads(output.read_text())
    verify_reaudit_report(persisted)

    persisted["decision"] = "accepted"
    with pytest.raises(LeanstralRuleGapReauditError, match="digest mismatch"):
        verify_reaudit_report(persisted)


def test_cli_discovers_canonical_history_and_emits_abstention(
    tmp_path: Path,
) -> None:
    output = tmp_path / "reaudit.json"
    script = REPO_ROOT / "scripts" / "ops" / "legal_ir" / "reaudit_leanstral_rule_gaps.py"
    completed = subprocess.run(
        [
            sys.executable,
            str(script),
            "--reports-root",
            str(REPO_ROOT / "workspace" / "leanstral-smoke"),
            "--output",
            str(output),
        ],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert completed.returncode == 0, completed.stderr
    assert "decision=abstained" in completed.stdout
    report = json.loads(output.read_text())
    assert report["historical_report_count"] == 9
    assert report["historical_unique_gap_count"] == 1
    assert report["selected_guidance"]["influence"] == 0.0
