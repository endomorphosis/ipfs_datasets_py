"""Tests for Leanstral hammer-aware drafted logic candidates."""

from __future__ import annotations

import json

from ipfs_datasets_py.logic.modal.leanstral import (
    LEANSTRAL_HAMMER_CANDIDATE_SCHEMA_VERSION,
    LEANSTRAL_PROPOSAL_SCHEMA_VERSION,
    LegalIRLeanTask,
    LeanstralProofValidation,
    LeanstralProposal,
    leanstral_draft_guidance,
    validate_leanstral_proposal,
)
from ipfs_datasets_py.logic.modal.leanstral import _leanstral_prompt
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


def _sample() -> LegalSample:
    text = "The agency shall provide notice unless emergency conditions exist."
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


def test_leanstral_prompt_exposes_legal_ir_proof_obligations_and_hammer_candidate_shape() -> None:
    task = _task()
    prompt = json.loads(_leanstral_prompt(task))
    shape = prompt["drafted_logic_candidate_shape"]

    assert prompt["task"]["proof_obligations"]
    assert shape["schema_version"] == LEANSTRAL_HAMMER_CANDIDATE_SCHEMA_VERSION
    assert shape["proof_obligation_ids"]
    assert shape["premise_hints"]
    assert shape["target_view"]
    assert shape["expected_failure_mode"]
    assert shape["source_copy_policy"] == "reject_full_span_copy"
    assert shape["source_copy_rejected"] is False


def test_leanstral_proposal_normalizes_hammer_candidate_fields_into_guidance_features() -> None:
    task = _task()
    obligation = dict(task.proof_obligations[0])
    proposal = LeanstralProposal.from_mapping(
        {
            "schema_version": LEANSTRAL_PROPOSAL_SCHEMA_VERSION,
            "task_id": task.task_id,
            "target_modal_ir_hash": task.modal_ir_hash,
            "compiler_change_spec_id": task.compiler_change_spec["spec_id"],
            "proof": "by simp [wellFormed, modalityMatches, sourceProvenancePresent, String.length]",
            "drafted_logic_candidates": [
                {
                    "candidate": "obligation(agency, provide_notice) unless exception(emergency)",
                    "compiler_surface": obligation["legal_ir_view"],
                    "confidence": "0.83",
                    "expected_failure_mode": "hammer_unproved",
                    "logic_family": obligation["logic_family"],
                    "obligation_id": obligation["obligation_id"],
                    "premise_hints": obligation["premise_hints"],
                    "source_copy_rejected": "false",
                    "target_view": obligation["legal_ir_view"],
                }
            ],
        }
    )

    candidate = proposal.drafted_logic_candidates[0]
    guidance = leanstral_draft_guidance(
        task,
        proposal,
        LeanstralProofValidation(accepted=True, proof_sha256="abc123"),
    )

    assert candidate["schema_version"] == LEANSTRAL_HAMMER_CANDIDATE_SCHEMA_VERSION
    assert candidate["proof_obligation_id"] == obligation["obligation_id"]
    assert candidate["proof_obligation_ids"] == [obligation["obligation_id"]]
    assert candidate["premise_hints"] == obligation["premise_hints"]
    assert candidate["target_view"] == obligation["legal_ir_view"]
    assert candidate["compiler_surface"] == obligation["legal_ir_view"]
    assert candidate["expected_failure_mode"] == "hammer_unproved"
    assert candidate["confidence"] == 0.83
    assert candidate["source_copy_policy"] == "reject_full_span_copy"
    assert candidate["source_copy_rejected"] is False
    assert "leanstral_hammer_obligations" in guidance.feature_groups
    assert "leanstral_hammer_target_views" in guidance.feature_groups
    assert "leanstral_hammer_premise_hints" in guidance.feature_groups


def test_leanstral_candidate_with_unknown_hammer_obligation_is_rejected_before_lean() -> None:
    task = _task()
    proposal = LeanstralProposal.from_mapping(
        {
            "schema_version": LEANSTRAL_PROPOSAL_SCHEMA_VERSION,
            "task_id": task.task_id,
            "target_modal_ir_hash": task.modal_ir_hash,
            "compiler_change_spec_id": task.compiler_change_spec["spec_id"],
            "proof": "by simp [wellFormed, modalityMatches, sourceProvenancePresent, String.length]",
            "drafted_logic_candidates": [
                {
                    "candidate": "obligation(agency, provide_notice)",
                    "compiler_surface": "deontic.ir",
                    "confidence": 0.6,
                    "expected_failure_mode": "hammer_unproved",
                    "logic_family": "deontic",
                    "proof_obligation_ids": ["lir-obligation-does-not-exist"],
                    "premise_hints": ["deontic_norm_polarity_supported"],
                    "source_copy_rejected": False,
                    "target_view": "deontic.ir",
                }
            ],
        }
    )

    validation = validate_leanstral_proposal(
        task,
        proposal,
        lean_executable="/definitely/not/lean",
    )

    assert validation.accepted is False
    assert "unknown_drafted_logic_proof_obligation_id" in validation.reasons
    assert "lean_executable_unavailable" not in validation.reasons

