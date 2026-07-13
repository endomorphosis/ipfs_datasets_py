"""Tests for Leanstral verified-audit rule-gap reporting."""

from __future__ import annotations

import json

from ipfs_datasets_py.logic.modal import (
    LEANSTRAL_AUDIT_RESPONSE_SCHEMA_VERSION,
    LEANSTRAL_RULE_GAP_REPORT_SCHEMA_VERSION,
    LeanstralAuditResponse,
    LeanstralAuditValidation,
    LeanstralAuditVerificationResult,
    LeanstralRuleGapReportConfig,
    LeanstralVerificationOutcome,
    aggregate_verified_audits,
    leanstral_rule_gap_report_to_json,
    synthesis_hints_from_leanstral_rule_gap_report,
)


def _response(**overrides) -> LeanstralAuditResponse:
    payload = {
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
                "paths": [
                    "ipfs_datasets_py/logic/modal/codec.py",
                    "ipfs_datasets_py/logic/modal/decompiler.py",
                ],
                "operation": "refine exception scope extraction",
            }
        ],
        "confidence": 0.84,
        "proof_obligation_ids": ["PO-modal-001", "PO-exception-002"],
        "abstention_reason": "",
        "rationale": "The source span contains an explicit exception cue.",
    }
    payload.update(overrides)
    return LeanstralAuditResponse.from_mapping(payload)


def _verification(
    response: LeanstralAuditResponse,
    *,
    outcome: LeanstralVerificationOutcome = LeanstralVerificationOutcome.ACCEPTED,
    reasons=(),
):
    return LeanstralAuditVerificationResult(
        schema_version="legal-ir-leanstral-verifier-v1",
        outcome=outcome,
        accepted=outcome == LeanstralVerificationOutcome.ACCEPTED,
        reasons=tuple(reasons),
        audit_validation=LeanstralAuditValidation(
            accepted=True,
            verified=True,
            response_hash=response.content_hash,
            cache_key=response.request_cache_key,
            verified_by=("leanstral-audit-schema-v1",),
        ),
        response_hash=response.content_hash,
        request_id=response.request_id,
        verified_by=("lean", "fake-prover")
        if outcome == LeanstralVerificationOutcome.ACCEPTED
        else (),
    )


def test_report_collapses_duplicate_audits_and_preserves_examples() -> None:
    first = _response(request_id="leanstral-audit-1")
    second = _response(
        request_id="leanstral-audit-2",
        counterexample={
            "example_id": "ex-2",
            "source_text": "The agency must approve benefits unless a listed exclusion applies.",
            "compiler_output": "obligation(approve)",
            "expected": "obligation(approve unless exclusion)",
        },
        confidence=0.9,
    )

    report = aggregate_verified_audits(
        [(first, _verification(first)), (second, _verification(second))]
    )

    assert report.schema_version == LEANSTRAL_RULE_GAP_REPORT_SCHEMA_VERSION
    assert report.source_audit_count == 2
    assert report.accepted_supporting_audit_count == 2
    assert len(report.gaps) == 1
    gap = report.gaps[0]
    assert gap.normalized_rule_key == "deontic_exception_scope"
    assert gap.status == "accepted"
    assert gap.target_component == "modal.ir_decompiler"
    assert gap.action == "refine_semantic_decompiler_reconstruction"
    assert len(gap.supporting_evidence) == 2
    assert len(gap.validation_set["regression_examples"]) == 2
    assert "source_decompiled_text_token_loss" in gap.validation_set["held_out_compiler_ir_metrics"]
    assert "exception_scope_preserved" in gap.validation_set["formal_validity_checks"]


def test_report_retains_conflicting_verified_or_rejected_examples() -> None:
    supporting = _response(request_id="leanstral-audit-support")
    rejected_same_gap = _response(
        request_id="leanstral-audit-conflict",
        confidence=0.2,
        counterexample={
            "example_id": "ex-conflict",
            "source_text": "The verifier could not reproduce the source span.",
        },
    )

    report = aggregate_verified_audits(
        [
            (supporting, _verification(supporting)),
            (
                rejected_same_gap,
                _verification(
                    rejected_same_gap,
                    outcome=LeanstralVerificationOutcome.REJECTED,
                    reasons=("modal_ir_hash_mismatch",),
                ),
            ),
        ]
    )

    gap = report.gaps[0]
    assert len(gap.supporting_evidence) == 1
    assert len(gap.conflicting_evidence) == 1
    assert gap.conflicting_evidence[0].role == "conflicting"
    assert "modal_ir_hash_mismatch" in gap.conflicting_evidence[0].reasons


def test_report_rejects_free_form_architecture_tasks() -> None:
    architecture = _response(
        proposed_compiler_surface=[
            {
                "component": "platform architecture",
                "operation": "write an architecture roadmap for all legal IR systems",
            }
        ]
    )

    report = aggregate_verified_audits([(architecture, _verification(architecture))])

    assert report.gaps == ()
    assert len(report.rejected_audits) == 1
    assert report.rejected_audits[0].status == "rejected"
    assert report.rejected_audits[0].verification_outcome == "accepted"
    assert "free_form_architecture_task" in report.rejected_audits[0].reasons


def test_report_emits_only_deterministic_record_statuses() -> None:
    response = _response()
    allowed = {"accepted", "rejected", "unsupported", "timed-out"}

    report = aggregate_verified_audits(
        [
            (
                response,
                _verification(
                    response,
                    outcome=LeanstralVerificationOutcome.TIMED_OUT,
                    reasons=("lean_timeout",),
                ),
            )
        ]
    )

    assert report.gaps == ()
    assert report.rejected_audits[0].status == "timed-out"
    assert report.rejected_audits[0].status in allowed


def test_report_maps_each_gap_to_one_owned_surface_and_bounds_outputs() -> None:
    audits = []
    for index in range(4):
        response = _response(
            request_id=f"leanstral-audit-{index}",
            counterexample={
                "example_id": f"ex-{index}",
                "source_text": f"Source exception example {index}.",
            },
            proposed_compiler_surface=[
                {"component": "unknown.experimental.surface"},
                {"component": "modal.ir_decompiler"},
            ],
        )
        audits.append((response, _verification(response)))

    report = aggregate_verified_audits(
        audits,
        config=LeanstralRuleGapReportConfig(max_gaps=1, max_examples_per_gap=2),
    )

    assert len(report.gaps) == 1
    gap = report.gaps[0]
    assert gap.target_component == "modal.ir_decompiler"
    assert len(gap.validation_set["regression_examples"]) == 2
    assert gap.validation_set["allowed_paths"] == [
        "ipfs_datasets_py/logic/modal/codec.py",
        "ipfs_datasets_py/logic/modal/decompiler.py",
    ]


def test_rule_gap_report_projects_to_synthesis_hints_and_json() -> None:
    response = _response()
    report = aggregate_verified_audits([(response, _verification(response))])

    hints = synthesis_hints_from_leanstral_rule_gap_report(report)
    encoded = leanstral_rule_gap_report_to_json(report)
    parsed = json.loads(encoded)

    assert parsed["schema_version"] == LEANSTRAL_RULE_GAP_REPORT_SCHEMA_VERSION
    assert hints
    assert hints[0].action == "refine_semantic_decompiler_reconstruction"
    assert hints[0].target_component == "modal.ir_decompiler"
    assert hints[0].evidence["gap_id"] == report.gaps[0].gap_id
    assert hints[0].evidence["supporting_evidence_count"] == 1
