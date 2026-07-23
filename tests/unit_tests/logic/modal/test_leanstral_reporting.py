"""Tests for Leanstral verified-audit rule-gap reporting."""

from __future__ import annotations

import json

from ipfs_datasets_py.logic.modal import (
    LEANSTRAL_AUDIT_RESPONSE_SCHEMA_VERSION,
    LEANSTRAL_PATCH_FEEDBACK_REPORT_SCHEMA_VERSION,
    LEANSTRAL_RULE_GAP_REPORT_SCHEMA_VERSION,
    LeanstralAuditResponse,
    LeanstralAuditValidation,
    LeanstralAuditVerificationResult,
    LeanstralRuleGapReportConfig,
    LeanstralVerificationOutcome,
    aggregate_verified_audits,
    build_leanstral_patch_feedback_report,
    leanstral_rule_gap_report_to_json,
    leanstral_patch_feedback_report_to_json,
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
            verified_by=("leanstral-audit-schema-v2",),
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


def test_report_collapses_family_preservation_paraphrases() -> None:
    frame_shift = _response(
        request_id="leanstral-audit-frame-shift",
        missing_semantic_rule={
            "description": (
                "The decompiler must preserve the conditional_normative family, "
                "but it currently emits frame output."
            )
        },
        affected_ir_families=["conditional_normative", "frame"],
        counterexample={
            "example_id": "family-frame",
            "expected": "Preserve conditional_normative source classification.",
            "observed": "Predicted frame.",
        },
    )
    deontic_shift = _response(
        request_id="leanstral-audit-deontic-shift",
        missing_semantic_rule={
            "description": (
                "Round-trip decompilation does not preserve the source legal IR "
                "family classification and maps it to deontic."
            )
        },
        affected_ir_families=["decompiler", "conditional_normative", "deontic"],
        counterexample={
            "example_id": "family-deontic",
            "expected": "The source family is conditional_normative.",
            "observed": "The decompiler emits deontic.",
        },
    )

    report = aggregate_verified_audits(
        [
            (frame_shift, _verification(frame_shift)),
            (deontic_shift, _verification(deontic_shift)),
        ]
    )

    assert len(report.gaps) == 1
    gap = report.gaps[0]
    assert gap.normalized_rule_key == (
        "round_trip_family_preservation_conditional_normative"
    )
    assert gap.affected_ir_families == (
        "conditional_normative",
        "frame",
        "deontic",
    )
    assert len(gap.supporting_evidence) == 2


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


def test_report_aliases_tdfol_roundtrip_surface_and_preserves_metric_attribution() -> None:
    response = _response(
        counterexample={
            "evidence_id": "packet-1",
            "expected": "Preserve conditional_normative source family.",
            "observed": "Round-trip emitted a TDFOL frame-family projection.",
        },
        missing_semantic_rule={
            "description": (
                "Decompiler round-trip must preserve frame-family and LegalIR "
                "family classification before TDFOL proof routing."
            )
        },
        affected_ir_families=["conditional_normative", "tdfol", "frame"],
        proposed_compiler_surface=[
            {
                "component": "TDFOL.prover",
                "operation": "preserve decompiler round-trip family",
            }
        ],
    )
    report = aggregate_verified_audits(
        [
            {
                "request": {
                    "evidence": {
                        "referenced_examples": [
                            {
                                "compiler_decompiler_metrics": {
                                    "compiler_ir_ce": 2.1,
                                    "compiler_ir_cosine_similarity": 0.18,
                                },
                                "evidence_id": "packet-1",
                                "sample_id": "sample-1",
                            }
                        ]
                    }
                },
                "response": response,
                "verification": _verification(response),
            }
        ]
    )

    assert len(report.gaps) == 1
    gap = report.gaps[0]
    assert gap.target_component == "modal.ir_decompiler"
    attribution = gap.validation_set["metric_attribution"]
    assert attribution["status"] == "pre_patch_observed"
    assert attribution["pre_patch_metrics"]["compiler_ir_ce"] == 2.1
    hints = synthesis_hints_from_leanstral_rule_gap_report(report)
    assert hints[0].evidence["pre_patch_metrics"]["compiler_ir_ce"] == 2.1


def test_report_keeps_direct_tdfol_prover_work_on_tdfol_surface() -> None:
    response = _response(
        missing_semantic_rule={
            "rule_id": "tdfol_quantifier_scope",
            "description": "TDFOL prover parse loses first-order quantifier scope.",
        },
        affected_ir_families=["tdfol", "first_order"],
        proposed_compiler_surface=[
            {
                "component": "TDFOL.prover",
                "operation": "repair quantifier scope parse",
            }
        ],
    )

    report = aggregate_verified_audits([(response, _verification(response))])

    assert len(report.gaps) == 1
    gap = report.gaps[0]
    assert gap.target_component == "TDFOL.prover"
    assert gap.action == "repair_tdfol_bridge_parse_and_proof_gate"
    assert gap.validation_set["target_file_lane"] == "tdfol_prover"
    assert "tdfol_parse_failure_ratio" in gap.validation_set["held_out_compiler_ir_metrics"]


def test_report_maps_event_calculus_to_cec_native_surface() -> None:
    response = _response(
        missing_semantic_rule={
            "rule_id": "cec_event_interval",
            "description": "Event calculus projection drops the terminating interval.",
        },
        affected_ir_families=["CEC", "event_calculus"],
        proposed_compiler_surface=[
            {
                "component": "event calculus",
                "operation": "repair DCEC event interval projection",
            }
        ],
    )

    report = aggregate_verified_audits([(response, _verification(response))])

    assert len(report.gaps) == 1
    gap = report.gaps[0]
    assert gap.target_component == "CEC.native"
    assert gap.action == "repair_cec_dcec_bridge_projection"
    assert gap.validation_set["target_file_lane"] == "cec_native"
    assert "event_interval_preserved" in gap.validation_set["formal_validity_checks"]


def test_report_maps_zero_knowledge_attestation_to_zkp_circuit_surface() -> None:
    response = _response(
        missing_semantic_rule={
            "rule_id": "zkp_attestation_binding",
            "description": "Zero knowledge attestation circuit omits the source hash binding.",
        },
        affected_ir_families=["zkp", "tdfol"],
        proposed_compiler_surface=[
            {
                "component": "zero knowledge circuits",
                "operation": "repair attestation circuit binding",
            }
        ],
    )

    report = aggregate_verified_audits([(response, _verification(response))])

    assert len(report.gaps) == 1
    gap = report.gaps[0]
    assert gap.target_component == "zkp.circuits"
    assert gap.action == "repair_zkp_attestation_bridge"
    assert gap.validation_set["target_file_lane"] == "zkp_circuits"
    assert "zkp_attestation_failure_ratio" in gap.validation_set["held_out_compiler_ir_metrics"]


def test_rule_gap_report_projects_to_synthesis_hints_and_json() -> None:
    response = _response(
        drafted_logic_candidates=[
            {
                "logic_family": "deontic",
                "candidate": "obligation(agency, notify(applicant)) unless emergency_review",
                "proof_obligation_id": "PO-modal-001",
                "compiler_surface": "modal.ir_decompiler",
                "confidence": 0.73,
            }
        ]
    )
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
    assert parsed["gaps"][0]["supporting_evidence"][0][
        "drafted_logic_candidates"
    ][0]["guidance_only"] is True
    assert hints[0].evidence["leanstral_guidance_mode"] == (
        "draft_logic_guidance_only"
    )
    assert hints[0].evidence["leanstral_drafted_logic_candidates"][0][
        "candidate"
    ].startswith("obligation")


def _patch_result(todo_id: str, *, status: str, metadata: dict) -> dict:
    return {
        "action": "add_deterministic_parser_rule",
        "loss_name": "leanstral_verified_rule_gap",
        "metadata": {
            "allowed_paths": ["ipfs_datasets_py/logic/modal/compiler.py"],
            "audit_request_ids": ["leanstral-audit-1"],
            "audit_response_hashes": ["response-hash-1"],
            "evidence_ids": ["leanstral-evidence-1"],
            "leanstral_gap_id": "gap-modal-cue",
            "leanstral_local_verifiers": ["local-lean"],
            "leanstral_projection": True,
            "leanstral_verified": True,
            "normalized_rule_key": "modal_cue:shall",
            "owned_ast_scope": "compiler_parser",
            "program_synthesis_scope": "compiler_parser",
            "proof_ids": ["PO-1", "modal_operator_preserved"],
            "semantic_bundle_key": "leanstral-rule-gap:modal-cue-shall",
            "target_component": "modal.compiler",
            "target_metrics": ["modal_ir_formula_recall"],
            "validation_commands": ["python -m pytest -q tests/unit_tests/logic/modal/test_modal_codec.py"],
            **metadata,
        },
        "status": status,
        "todo_id": todo_id,
    }


def test_patch_feedback_journals_lineage_and_retains_verified_compiler_targets() -> None:
    result = _patch_result(
        "todo-accepted",
        status="completed",
        metadata={
            "completed_codex_exec_status": "succeeded",
            "completed_patch_status": "applied_to_main",
            "completed_validation_report": {
                "main_apply_validation_status": "passed",
                "metric_deltas": {"modal_ir_formula_recall": 0.04},
                "post_patch_metrics": {"modal_ir_formula_recall": 0.54},
                "target_metric_status": "improved",
            },
            "leanstral_metric_attribution": {
                "pre_patch_metrics": {"modal_ir_formula_recall": 0.5},
                "schema_version": "legal-ir-leanstral-metric-attribution-v1",
                "status": "pre_patch_observed",
            },
            "leanstral_drafted_logic_candidates": [
                {
                    "candidate": "obligation(agency, disclose(record))",
                    "guidance_only": True,
                    "intended_use": "guidance_only",
                    "logic_family": "deontic",
                    "proof_obligation_id": "PO-1",
                }
            ],
            "validation_gate": {"accepted": True},
        },
    )

    report = build_leanstral_patch_feedback_report([result])
    encoded = leanstral_patch_feedback_report_to_json(report)
    parsed = json.loads(encoded)

    assert report.schema_version == LEANSTRAL_PATCH_FEEDBACK_REPORT_SCHEMA_VERSION
    assert parsed["outcome_counts"]["accepted_improvement"] == 1
    outcome = report.outcomes[0]
    assert outcome.lineage.audit_request_ids == ("leanstral-audit-1",)
    assert outcome.lineage.audit_response_hashes == ("response-hash-1",)
    assert outcome.lineage.todo_id == "todo-accepted"
    assert outcome.lineage.patch_status == "applied_to_main"
    assert outcome.metric_deltas["modal_ir_formula_recall"] == 0.04
    assert outcome.compiler_target is not None
    assert outcome.compiler_target["verified_compiler_rule"] is True
    assert outcome.compiler_target["write_to_autoencoder_weights"] is False
    assert outcome.compiler_target["metric_attribution"]["pre_patch_metrics"][
        "modal_ir_formula_recall"
    ] == 0.5
    assert outcome.compiler_target["metric_attribution"]["post_patch_metrics"][
        "modal_ir_formula_recall"
    ] == 0.54
    assert outcome.compiler_target["leanstral_guidance_mode"] == (
        "draft_logic_guidance_only"
    )
    assert outcome.compiler_target["leanstral_drafted_logic_candidates"][0][
        "candidate"
    ].startswith("obligation")
    assert outcome.compiler_target["leanstral_drafted_logic_candidates"][0][
        "guidance_only"
    ] is True
    assert report.compiler_targets_for_autoencoder_evaluation


def test_patch_feedback_classifies_regressions_unsupported_operational_and_stale() -> None:
    regression = _patch_result(
        "todo-regression",
        status="failed_validation",
        metadata={
            "failed_validation_patch_status": "applied_to_main",
            "failed_validation_reason": "target_metric_regression",
            "failed_validation_report": {
                "regressed_metrics": ["modal_ir_formula_recall"],
                "target_metric_status": "regressed",
            },
        },
    )
    unsupported = _patch_result(
        "todo-unsupported",
        status="failed_validation",
        metadata={
            "failed_validation_patch_status": "applied_to_main",
            "failed_validation_reason": "program_synthesis_validation_rejected",
            "failed_validation_report": {"main_apply_validation_status": "failed"},
        },
    )
    operational = _patch_result(
        "todo-operational",
        status="pending",
        metadata={
            "last_transient_codex_exec_status": "transient_failure",
            "last_transient_patch_status": "awaiting_codex_changes",
        },
    )
    stale = _patch_result(
        "todo-stale",
        status="stale",
        metadata={"leanstral_stale_evidence": True},
    )

    report = build_leanstral_patch_feedback_report(
        [regression, unsupported, operational, stale],
        suppression_threshold=2,
    )

    assert [outcome.outcome for outcome in report.outcomes] == [
        "quality_regression",
        "unsupported_hypothesis",
        "operational_failure",
        "stale_evidence",
    ]
    assert report.suppressed_feature_clusters == (
        "leanstral-rule-gap:modal-cue-shall",
    )
    assert report.compiler_targets_for_autoencoder_evaluation == ()
