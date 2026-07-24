"""Integration of current failure-branch sanitization with rule-gap re-audit."""

from __future__ import annotations

import json
from pathlib import Path

from ipfs_datasets_py.logic.integration.reasoning.legal_ir_hammer import (
    LEGAL_IR_HAMMER_REPORT_SCHEMA_VERSION,
)
from ipfs_datasets_py.logic.integration.reasoning.legal_ir_hammer_translation import (
    LEGAL_IR_HAMMER_RECONSTRUCTION_RECEIPT_SCHEMA_VERSION,
)
from ipfs_datasets_py.logic.modal.leanstral import (
    LEANSTRAL_HAMMER_CANDIDATE_SCHEMA_VERSION,
    LegalIRLeanTask,
    build_leanstral_failure_branch_prompt,
)
from ipfs_datasets_py.logic.modal.leanstral_verifier import (
    LEANSTRAL_HAMMER_VERIFIER_SCHEMA_VERSION,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.leanstral_rule_gap_reaudit import (
    LeanstralRuleGapReauditPolicy,
    build_current_rule_gap_evidence,
    canonical_historical_rule_gap_report_paths,
    reaudit_leanstral_rule_gaps,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_samples import (
    LegalSample,
    stable_mock_embedding,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_ir import (
    ModalIRDocument,
    ModalIRFormula,
    ModalIRFrameLogic,
    ModalIROperator,
    ModalIRPredicate,
    ModalIRProvenance,
)


REPO_ROOT = Path(__file__).resolve().parents[4]
HISTORICAL_REPORTS = canonical_historical_rule_gap_report_paths(
    REPO_ROOT / "workspace" / "leanstral-smoke"
)


def _frame_task() -> LegalIRLeanTask:
    text = "The agency shall classify each notice as an official filing."
    document = ModalIRDocument(
        document_id="frame-reaudit-document",
        source="us_code",
        normalized_text=text,
        formulas=[
            ModalIRFormula(
                formula_id="frame-f1",
                operator=ModalIROperator(
                    family="deontic",
                    system="KD",
                    symbol="shall",
                    label="shall",
                ),
                predicate=ModalIRPredicate(
                    name="classify",
                    arguments=["agency", "notice", "official_filing"],
                    role="obligation",
                ),
                provenance=ModalIRProvenance(
                    source_id="frame-reaudit-document",
                    start_char=0,
                    end_char=len(text),
                ),
            )
        ],
        frame_logic=ModalIRFrameLogic.from_triples(
            [
                {
                    "subject": "agency",
                    "predicate": "classifies",
                    "object": "notice",
                },
                {
                    "subject": "notice",
                    "predicate": "instanceOf",
                    "object": "official_filing",
                },
            ],
            selected_frame="legal_filing",
        ),
    )
    sample = LegalSample(
        sample_id=document.document_id,
        source="us_code",
        title="5",
        section="100",
        citation="5 U.S.C. 100",
        text=text,
        normalized_text=text,
        embedding_model="mock:stable-sha256",
        embedding_vector=stable_mock_embedding(text),
        modal_ir=document,
    )
    return LegalIRLeanTask.from_sample(
        sample,
        autoencoder_guidance={
            "legal_ir_view_gap_distribution": {"modal.frame_logic": 0.4},
            "synthesis_focus": ["audit_frame_logic_terms"],
        },
    )


def _frame_obligation(task: LegalIRLeanTask) -> dict:
    return next(
        dict(item)
        for item in task.proof_obligations
        if dict(item).get("metadata", {}).get("contract_id")
        == "legal-ir-view/frame-logic/v1"
    )


def _hammer_verification(candidate: dict, obligation_id: str) -> dict:
    return {
        "accepted": True,
        "candidate_count": 1,
        "candidate_results": [
            {
                "accepted": True,
                "candidate": candidate,
                "candidate_index": 1,
                "deterministic_checks": [
                    {
                        "checker_name": name,
                        "details": {},
                        "elapsed_seconds": 0.001,
                        "error_message": "",
                        "route_available": True,
                        "status": "accepted",
                        "theorem_valid": True,
                        "timeout_seconds": 1.0,
                    }
                    for name in ("syntax", "contract", "provenance", "graph")
                ],
                "hammer_report": {
                    "artifacts": [
                        {
                            "obligation_id": obligation_id,
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
                            "obligation_id": obligation_id,
                            "receipt_id": "frame-current-reconstruction",
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
        "proposal_task_id": "fresh-frame-proposal",
        "reasons": [],
        "schema_version": LEANSTRAL_HAMMER_VERIFIER_SCHEMA_VERSION,
        "task_id": "fresh-frame-task",
        "trusted": True,
        "trusted_candidate_count": 1,
    }


def test_current_sanitizer_and_trusted_hammer_receipts_are_required_end_to_end() -> None:
    policy = LeanstralRuleGapReauditPolicy.canonical()
    baseline = reaudit_leanstral_rule_gaps(HISTORICAL_REPORTS, policy=policy)
    task = _frame_task()
    obligation = _frame_obligation(task)
    obligation_id = str(obligation["obligation_id"])
    failures = [
        {
            "failure_reason": "unproved",
            "obligation_id": obligation_id,
            "proved": False,
            "trusted": False,
        }
    ]
    prompt = json.loads(build_leanstral_failure_branch_prompt(task, failures))
    response = prompt["response_shape"]
    candidate = response["candidates"][0]
    assert candidate["schema_version"] == LEANSTRAL_HAMMER_CANDIDATE_SCHEMA_VERSION
    assert candidate["compiler_surface"] == "modal.frame_logic"
    assert candidate["logic_family"] == "frame_logic"
    candidate["candidate"] = prompt["failed_obligation_subtrees"][0][
        "candidate_language"
    ][
        "grounded_candidate_seed"
    ]
    candidate["confidence"] = 0.75

    evidence = build_current_rule_gap_evidence(
        task,
        response,
        failures,
        _hammer_verification(candidate, obligation_id),
        audit_run_id="fresh-frame-integration",
        gap_identity_id=str(baseline["target_gap_identity_id"]),
    )
    report = reaudit_leanstral_rule_gaps(
        HISTORICAL_REPORTS,
        fresh_evidence=evidence,
        policy=policy,
    )

    assert evidence["candidate_sanitization"]["accepted"] is True
    assert report["decision"] == "accepted"
    assert report["selected_guidance"]["target_component"] == "modal.frame_logic"
    assert report["selected_guidance"]["target_family"] == "frame_logic"
    assert report["selected_guidance"]["proof_obligation_ids"] == [obligation_id]
    assert report["selected_guidance"]["influence"] == policy.max_guidance_influence
    assert candidate["candidate"] not in json.dumps(report, sort_keys=True)


def test_current_helper_preserves_sanitizer_rejection_as_zero_influence() -> None:
    policy = LeanstralRuleGapReauditPolicy.canonical()
    baseline = reaudit_leanstral_rule_gaps(HISTORICAL_REPORTS, policy=policy)
    task = _frame_task()
    obligation = _frame_obligation(task)
    obligation_id = str(obligation["obligation_id"])
    failures = [{"obligation_id": obligation_id, "proved": False, "trusted": False}]
    response = json.loads(build_leanstral_failure_branch_prompt(task, failures))[
        "response_shape"
    ]
    response["candidates"][0]["candidate"] = "by simp [frame_terms_preserved]"
    response["candidates"][0]["confidence"] = 0.9

    evidence = build_current_rule_gap_evidence(
        task,
        response,
        failures,
        _hammer_verification(response["candidates"][0], obligation_id),
        audit_run_id="fresh-frame-rejected",
        gap_identity_id=str(baseline["target_gap_identity_id"]),
    )
    report = reaudit_leanstral_rule_gaps(
        HISTORICAL_REPORTS,
        fresh_evidence=evidence,
        policy=policy,
    )

    assert evidence["candidate_sanitization"]["accepted"] is False
    assert report["decision"] == "rejected"
    assert report["selected_guidance"]["influence"] == 0.0
    assert "by simp" not in json.dumps(report, sort_keys=True)
