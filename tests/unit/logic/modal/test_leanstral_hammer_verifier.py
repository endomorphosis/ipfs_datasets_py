"""Tests for Leanstral drafted-candidate hammer verification."""

from __future__ import annotations

from ipfs_datasets_py.logic.integration.reasoning.hammer import (
    CallableHammerBackendRunner,
    HammerBackendResult,
    HammerBackendStatus,
    HammerVerification,
)
from ipfs_datasets_py.logic.integration.reasoning.legal_ir_hammer import LegalIRHammerConfig
from ipfs_datasets_py.logic.modal import (
    LEANSTRAL_HAMMER_VERIFIER_SCHEMA_VERSION,
    LEANSTRAL_PROPOSAL_SCHEMA_VERSION,
    LegalIRLeanTask,
    LeanstralHammerVerifierConfig,
    LeanstralProposal,
    verify_leanstral_hammer_candidates,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_samples import (
    LegalSample,
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

    report = verify_leanstral_hammer_candidates(
        task,
        proposal,
        sample_or_document=sample,
        config=LeanstralHammerVerifierConfig(
            hammer_config=LegalIRHammerConfig(max_premises=32, timeout_seconds=1)
        ),
        backends=[_proved_backend()],
    )
    payload = report.to_dict()

    assert payload["schema_version"] == LEANSTRAL_HAMMER_VERIFIER_SCHEMA_VERSION
    assert report.accepted is True
    assert report.trusted is True
    assert report.trusted_candidate_count == 1
    assert report.candidate_results[0].hammer_report.proved_count == 1
    assert report.candidate_results[0].verified_guidance


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

