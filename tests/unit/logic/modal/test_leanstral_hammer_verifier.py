"""Tests for Leanstral drafted-candidate hammer verification."""

from __future__ import annotations

from ipfs_datasets_py.logic.integration.reasoning.hammer import (
    CallableHammerBackendRunner,
    HammerBackendResult,
    HammerBackendStatus,
    HammerVerification,
)
from ipfs_datasets_py.logic.integration.reasoning.legal_ir_hammer import LegalIRHammerConfig
from ipfs_datasets_py.logic.integration.reasoning.legal_ir_obligations import (
    generate_legal_ir_proof_obligations,
)
from ipfs_datasets_py.logic.modal import (
    LEANSTRAL_AUDIT_RESPONSE_SCHEMA_VERSION,
    LEANSTRAL_HAMMER_VERIFIER_SCHEMA_VERSION,
    LEANSTRAL_PROPOSAL_SCHEMA_VERSION,
    LegalIRLeanTask,
    LeanstralAuditRequest,
    LeanstralAuditResponse,
    LeanstralHammerVerifierConfig,
    LeanstralProposal,
    LeanstralVerifierConfig,
    verify_leanstral_audit_hammer_candidates,
    verify_leanstral_hammer_candidates,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_samples import (
    LegalSample,
    build_us_code_sample,
    stable_mock_embedding,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_ir import (
    ModalIRDocument,
    ModalIRFormula,
    ModalIROperator,
    ModalIRPredicate,
    ModalIRProvenance,
)


def _proved_backend(calls: list[str] | None = None):
    def _run(translation, timeout_seconds):
        if calls is not None:
            calls.append(translation.problem)
        return HammerBackendResult(
            backend="z3",
            status=HammerBackendStatus.PROVED,
            proved=True,
            elapsed_seconds=0.01,
            translation_format=translation.target_format,
            proof_trace="unsat",
            raw_output="unsat",
        )

    return CallableHammerBackendRunner("z3", "smt-lib", _run)


def _sample() -> LegalSample:
    text = "The agency shall provide notice unless emergency conditions exist within 30 days."
    modal_ir = ModalIRDocument(
        document_id="doc-1",
        source="us_code",
        normalized_text=text,
        formulas=[
            ModalIRFormula(
                formula_id="f1",
                operator=ModalIROperator(
                    family="deontic",
                    system="KD",
                    symbol="shall",
                    label="shall",
                ),
                predicate=ModalIRPredicate(
                    name="provide_notice",
                    arguments=["agency", "notice"],
                    role="obligation",
                ),
                provenance=ModalIRProvenance(
                    source_id="doc-1",
                    start_char=0,
                    end_char=len(text),
                ),
                conditions=["within 30 days"],
                exceptions=["emergency conditions exist"],
            )
        ],
    )
    return LegalSample(
        sample_id="sample-1",
        source="us_code",
        title="5",
        section="552",
        citation="5 U.S.C. 552",
        text=text,
        normalized_text=text,
        embedding_model="mock:stable-sha256",
        embedding_vector=stable_mock_embedding(text),
        modal_ir=modal_ir,
    )


def _task() -> LegalIRLeanTask:
    return LegalIRLeanTask.from_sample(
        _sample(),
        autoencoder_guidance={
            "feature_groups": {"compiler_contract": ["modal:deontic"]},
            "legal_ir_view_gap_distribution": {"deontic.ir": 0.4},
            "legal_ir_view_metrics": {"compiler_ir_cross_entropy_loss": 0.5},
            "ranked_guidance_features": [{"feature": "modal:deontic", "score": 1.0}],
            "synthesis_focus": ["legal_ir_multiview"],
        },
    )


def _proposal(task: LegalIRLeanTask, candidate_text: str, **candidate_overrides) -> LeanstralProposal:
    obligation = dict(task.proof_obligations[0])
    candidate = {
        "candidate": candidate_text,
        "compiler_surface": obligation["legal_ir_view"],
        "confidence": 0.8,
        "expected_failure_mode": "hammer_unproved",
        "logic_family": obligation["logic_family"],
        "premise_hints": obligation["premise_hints"],
        "proof_obligation_ids": [obligation["obligation_id"]],
        "source_copy_rejected": False,
        "target_view": obligation["legal_ir_view"],
    }
    candidate.update(candidate_overrides)
    return LeanstralProposal.from_mapping(
        {
            "schema_version": LEANSTRAL_PROPOSAL_SCHEMA_VERSION,
            "task_id": task.task_id,
            "target_modal_ir_hash": task.modal_ir_hash,
            "compiler_change_spec_id": task.compiler_change_spec["spec_id"],
            "proof": "by simp [wellFormed, modalityMatches, sourceProvenancePresent, String.length]",
            "drafted_logic_candidates": [candidate],
        }
    )


def test_leanstral_hammer_verifier_accepts_candidate_only_after_hammer_proof() -> None:
    sample = _sample()
    task = LegalIRLeanTask.from_sample(
        sample,
        autoencoder_guidance={
            "legal_ir_view_gap_distribution": {"deontic.ir": 0.4},
            "legal_ir_view_metrics": {"compiler_ir_cross_entropy_loss": 0.5},
            "ranked_guidance_features": [{"feature": "modal:deontic", "score": 1.0}],
            "synthesis_focus": ["legal_ir_multiview"],
        },
    )
    proposal = _proposal(
        task,
        "obligation(agency, provide_notice) unless exception(emergency)",
    )
    translated_problems: list[str] = []

    report = verify_leanstral_hammer_candidates(
        task,
        proposal,
        sample_or_document=sample,
        config=LeanstralHammerVerifierConfig(
            hammer_config=LegalIRHammerConfig(max_premises=32, timeout_seconds=1)
        ),
        backends=[_proved_backend(translated_problems)],
    )
    payload = report.to_dict()

    assert payload["schema_version"] == LEANSTRAL_HAMMER_VERIFIER_SCHEMA_VERSION
    assert report.accepted is True
    assert report.trusted is True
    assert report.trusted_candidate_count == 1
    assert report.candidate_results[0].hammer_report.proved_count == 1
    assert report.candidate_results[0].verified_guidance
    assert translated_problems
    assert (
        "; conjecture "
        in translated_problems[0]
        and "obligation(agency, provide_notice) unless exception(emergency)"
        in translated_problems[0]
    )


def test_leanstral_hammer_verifier_rejects_source_copy_before_hammer_execution() -> None:
    task = _task()
    calls: list[str] = []
    proposal = _proposal(task, task.source_span)

    report = verify_leanstral_hammer_candidates(
        task,
        proposal,
        config=LeanstralHammerVerifierConfig(
            hammer_config=LegalIRHammerConfig(max_premises=32, timeout_seconds=1)
        ),
        backends=[_proved_backend(calls)],
    )

    assert report.accepted is False
    assert report.trusted is False
    assert "drafted_logic_candidate_copies_source_span" in report.reasons
    assert report.candidate_results[0].hammer_report is None
    assert calls == []


def test_leanstral_hammer_verifier_rejects_obligation_copy_before_hammer() -> None:
    task = _task()
    calls: list[str] = []
    obligation = dict(task.proof_obligations[0])
    proposal = _proposal(task, obligation["statement"])

    report = verify_leanstral_hammer_candidates(
        task,
        proposal,
        config=LeanstralHammerVerifierConfig(
            hammer_config=LegalIRHammerConfig(
                max_premises=32,
                timeout_seconds=1,
            )
        ),
        backends=[_proved_backend(calls)],
    )

    assert report.accepted is False
    assert "drafted_logic_candidate_copies_obligation" in report.reasons
    assert report.candidate_results[0].hammer_report is None
    assert calls == []


def test_leanstral_hammer_verifier_rejects_invalid_kg_candidate_shape_before_hammer() -> None:
    task = _task()
    calls: list[str] = []
    proposal = _proposal(
        task,
        "edge(actor, agency)",
        target_view="knowledge_graphs.neo4j_compat",
        compiler_surface="knowledge_graphs.neo4j_compat",
    )

    report = verify_leanstral_hammer_candidates(
        task,
        proposal,
        config=LeanstralHammerVerifierConfig(),
        backends=[_proved_backend(calls)],
    )

    assert report.accepted is False
    assert "invalid_kg_candidate_shape" in report.reasons
    assert report.candidate_results[0].hammer_report is None
    assert calls == []


def test_leanstral_hammer_verifier_keeps_failed_reconstruction_untrusted() -> None:
    task = _task()
    proposal = _proposal(
        task,
        "obligation(agency, provide_notice) unless exception(emergency)",
    )

    def _rejecting_kernel(itp_system, proof_script, goal, selected_premises):
        return HammerVerification(
            verified=False,
            checker="fake-lean-kernel",
            error="type mismatch",
        )

    report = verify_leanstral_hammer_candidates(
        task,
        proposal,
        config=LeanstralHammerVerifierConfig(
            hammer_config=LegalIRHammerConfig(
                max_premises=32,
                timeout_seconds=1,
                verify_reconstruction=True,
                trusted_requires_reconstruction=True,
            )
        ),
        backends=[_proved_backend()],
        kernel_verifier=_rejecting_kernel,
    )

    assert report.accepted is False
    assert report.trusted is False
    assert "reconstruction_failed" in report.reasons
    assert report.candidate_results[0].verified_guidance == ()


def test_audit_candidates_are_recompiled_and_sent_through_hammer() -> None:
    sample = build_us_code_sample(
        title="5",
        section="552",
        text=(
            "The agency shall provide notice unless emergency conditions "
            "exist within 30 days."
        ),
    )
    obligation = next(
        item
        for item in generate_legal_ir_proof_obligations(sample)
        if item.metadata.get("coverage_scope") == "local_semantics"
    )
    request = LeanstralAuditRequest.build(
        evidence={
            "semantic_context": {
                "accepted": True,
                "modal_formulas": [
                    formula.to_dict() for formula in sample.modal_ir.formulas
                ],
                "proof_obligations": [
                    {**obligation.to_dict(), "verified": True}
                ],
                "sample_id": sample.sample_id,
                "schema_version": "legal-ir-leanstral-semantic-context-v1",
            }
        },
        prompt={"prompt": "audit"},
        model={"model": "Leanstral"},
        proof_obligation_ids=[obligation.obligation_id],
    )
    response = LeanstralAuditResponse.from_mapping(
        {
            "abstention_reason": "",
            "affected_ir_families": [obligation.logic_family],
            "classification": "missing_semantic_rule",
            "confidence": 0.8,
            "counterexample": {"example_id": sample.sample_id},
            "drafted_logic_candidates": [
                {
                    "candidate": (
                        "obligation(actor:clause, "
                        "action:provide_notice_unless_emergency_conditions_exist) "
                        "unless exception("
                        "condition:notice_unless_emergency_conditions_exist_within)"
                    ),
                    "compiler_surface": obligation.legal_ir_view,
                    "confidence": 0.8,
                    "contract_id": obligation.metadata["contract_id"],
                    "expected_failure_mode": "hammer_unproved",
                    "logic_family": obligation.logic_family,
                    "premise_hints": obligation.premise_hints,
                    "proof_obligation_ids": [obligation.obligation_id],
                    "repair_scope": "failed_obligation_subtree",
                    "schema_version": "legal-ir-leanstral-hammer-candidate-v1",
                    "source_copy_policy": "reject_full_span_copy",
                    "source_copy_rejected": False,
                    "target_view": obligation.legal_ir_view,
                }
            ],
            "missing_semantic_rule": {"rule_id": "exception_scope"},
            "proof_obligation_ids": [obligation.obligation_id],
            "proposed_compiler_surface": [
                {"component": obligation.legal_ir_view}
            ],
            "request_id": request.request_id,
            "schema_version": LEANSTRAL_AUDIT_RESPONSE_SCHEMA_VERSION,
            "witness": None,
        }
    )

    report = verify_leanstral_audit_hammer_candidates(
        request,
        response,
        examples=[sample],
        verifier_config=LeanstralVerifierConfig(
            canonical_recompile_backend="packet_canonical",
        ),
        config=LeanstralHammerVerifierConfig(
            hammer_config=LegalIRHammerConfig(
                max_obligations=1,
                max_premises=32,
                timeout_seconds=1,
            )
        ),
        backends=[_proved_backend()],
    )

    assert report.accepted is True
    assert report.trusted is True
    assert report.candidate_count == 1
    assert report.candidate_results[0].hammer_report.obligation_count == 1
    contract_check = next(
        check
        for check in report.candidate_results[0].deterministic_checks
        if check.checker_name == "leanstral_hammer_candidate_contract"
    )
    assert contract_check.details["grounding_match_count"] >= 2
