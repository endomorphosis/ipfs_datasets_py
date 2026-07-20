"""Tests for hammer guidance in Leanstral rule-gap reports."""

from __future__ import annotations

import json

from ipfs_datasets_py.logic.modal import (
    LEANSTRAL_AUDIT_RESPONSE_SCHEMA_VERSION,
    LEANSTRAL_RULE_GAP_REPORT_SCHEMA_VERSION,
    LeanstralAuditResponse,
    LeanstralAuditValidation,
    LeanstralAuditVerificationResult,
    LeanstralVerificationOutcome,
    aggregate_verified_audits,
    leanstral_rule_gap_report_to_json,
)


def _response() -> LeanstralAuditResponse:
    return LeanstralAuditResponse.from_mapping(
        {
            "schema_version": LEANSTRAL_AUDIT_RESPONSE_SCHEMA_VERSION,
            "request_id": "leanstral-audit-1",
            "request_cache_key": "a" * 64,
            "classification": "missing_semantic_rule",
            "missing_semantic_rule": {
                "rule_id": "deontic_exception_scope",
                "description": "Preserve exception clauses under obligation scope.",
            },
            "counterexample": {
                "example_id": "ex-1",
                "source_text": "The agency must notify the applicant unless emergency review applies.",
                "compiler_output": "obligation(notify)",
                "expected": "obligation(notify unless emergency_review)",
            },
            "witness": None,
            "affected_ir_families": ["deontic", "temporal"],
            "proposed_compiler_surface": [
                {
                    "component": "modal.ir_decompiler",
                    "operation": "refine exception scope extraction",
                }
            ],
            "confidence": 0.84,
            "proof_obligation_ids": ["lir-obligation-1"],
            "drafted_logic_candidates": [
                {
                    "candidate": "obligation(agency, notify_applicant) unless exception(emergency_review)",
                    "compiler_surface": "deontic.ir",
                    "confidence": 0.8,
                    "expected_failure_mode": "hammer_unproved",
                    "logic_family": "deontic",
                    "premise_hints": ["exception_scope_precedence"],
                    "proof_obligation_ids": ["lir-obligation-1"],
                    "source_copy_policy": "reject_full_span_copy",
                    "source_copy_rejected": False,
                    "target_metrics": ["compiler_ir_cross_entropy_loss"],
                    "target_view": "deontic.ir",
                }
            ],
            "abstention_reason": "",
            "rationale": "The source span contains an explicit exception cue.",
        }
    )


def _verification(response: LeanstralAuditResponse) -> LeanstralAuditVerificationResult:
    return LeanstralAuditVerificationResult(
        schema_version="legal-ir-leanstral-verifier-v1",
        outcome=LeanstralVerificationOutcome.ACCEPTED,
        accepted=True,
        reasons=(),
        audit_validation=LeanstralAuditValidation(
            accepted=True,
            verified=True,
            response_hash=response.content_hash,
            cache_key=response.request_cache_key,
            verified_by=("leanstral-audit-schema-v2",),
        ),
        response_hash=response.content_hash,
        request_id=response.request_id,
        verified_by=("lean", "hammer"),
    )


def _hammer_verification() -> dict:
    artifact = {
        "backend_statuses": {"z3": "proved"},
        "failure_reason": "",
        "goal_name": "lir-obligation-1",
        "goal_statement_hash": "abc",
        "guidance_id": "hammer-guidance-1",
        "legal_ir_view": "deontic.ir",
        "logic_family": "deontic",
        "metadata": {"obligation_kind": "exception_scope_precedence"},
        "obligation_id": "lir-obligation-1",
        "premise_views": ["deontic.ir"],
        "proof_checked": True,
        "proof_obligation_ids": ["lir-obligation-1"],
        "proved": True,
        "reconstruction_status": "verified",
        "rejection_reasons": [],
        "schema_version": "legal-ir-hammer-guidance-v1",
        "selected_premises": ["exception_scope_precedence"],
        "target_component": "deontic.ir",
        "target_metrics": ["compiler_ir_cross_entropy_loss"],
        "trusted": True,
        "winner_backend": "z3",
    }
    return {
        "accepted": True,
        "candidate_count": 1,
        "candidate_results": [
            {
                "accepted": True,
                "hammer_report": {
                    "artifacts": [artifact],
                    "metadata": {
                        "backend_health": {
                            "available_count": 1,
                            "available_routes": ["z3"],
                            "records": [{"name": "z3", "available": True}],
                            "unavailable_count": 0,
                            "unavailable_routes": [],
                        }
                    },
                    "obligation_count": 1,
                    "proof_success_rate": 1.0,
                    "proved_count": 1,
                    "trusted_count": 1,
                    "trusted_success_rate": 1.0,
                },
                "reasons": [],
                "trusted": True,
                "verified_guidance": [artifact],
            }
        ],
        "proposal_task_id": "leanstral-task-1",
        "reasons": [],
        "schema_version": "legal-ir-leanstral-hammer-verifier-v1",
        "task_id": "leanstral-task-1",
        "trusted": True,
        "trusted_candidate_count": 1,
    }


def test_rule_gap_report_retains_verified_hammer_guidance_for_codex_projection() -> None:
    response = _response()
    report = aggregate_verified_audits(
        [
            {
                "response": response,
                "verification": _verification(response),
                "hammer_verification": _hammer_verification(),
            }
        ]
    )
    parsed = json.loads(leanstral_rule_gap_report_to_json(report))
    evidence = parsed["gaps"][0]["supporting_evidence"][0]

    assert parsed["schema_version"] == LEANSTRAL_RULE_GAP_REPORT_SCHEMA_VERSION
    assert evidence["drafted_logic_candidates"][0]["premise_hints"] == [
        "exception_scope_precedence"
    ]
    assert evidence["drafted_logic_candidates"][0]["source_copy_rejected"] is False
    assert evidence["hammer_guidance_artifacts"][0]["guidance_id"] == "hammer-guidance-1"
    assert evidence["hammer_guidance_artifacts"][0]["artifact_sha256"]
    assert evidence["hammer_backend_health"]["available_routes"] == ["z3"]
    assert evidence["hammer_proof_status"]["proof_success_rate"] == 1.0
    assert evidence["hammer_reconstruction_status"]["reconstruction_statuses"] == [
        "verified"
    ]
    assert evidence["codex_projection"]["projection_source"] == "hammer_verified_guidance"
    assert evidence["codex_projection"]["target_components"] == ["deontic.ir"]
    assert evidence["codex_projection"]["target_metrics"] == [
        "compiler_ir_cross_entropy_loss"
    ]
    assert evidence["codex_projection"]["proof_obligation_ids"] == ["lir-obligation-1"]

