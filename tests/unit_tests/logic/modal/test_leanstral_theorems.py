"""Tests for verifier-owned Lean theorem templates."""

from __future__ import annotations

import json
from dataclasses import replace

from ipfs_datasets_py.logic.modal import (
    DeterministicModalLogicCodec,
    LegalIRLeanTask,
    LeanstralProposal,
    ModalLogicCodecConfig,
    generate_legal_semantics_theorem_registry,
    validate_leanstral_proposal,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_samples import (
    build_us_code_sample,
)


def _sample():
    text = (
        "The Secretary may issue permits within 30 days, except as provided "
        "in subsection (b). No person may not transfer a permit before approval."
    )
    base = build_us_code_sample(title="42", section="100", text=text)
    result = DeterministicModalLogicCodec(
        ModalLogicCodecConfig(parser_backend="spacy", embedding_dimensions=8)
    ).encode(
        text,
        document_id=base.sample_id,
        citation=base.citation,
        source=base.source,
        source_embedding=base.embedding_vector,
    )
    return replace(
        base,
        modal_ir=result.modal_ir,
        frame_candidates=result.frame_candidates,
        selected_frame=result.selected_frame,
        losses=result.losses,
    )


def _guidance():
    return {
        "feature_groups": {"compiler_contract": ["modal:deontic"]},
        "legal_ir_view_gap_distribution": {"deontic_norms": 0.1},
        "legal_ir_view_metrics": {"cross_entropy_loss": 0.2},
        "ranked_guidance_features": [
            {"feature": "modal:deontic", "score": 1.0}
        ],
        "synthesis_focus": ["legal_ir_multiview"],
    }


def test_registry_generates_all_required_fixed_theorem_categories() -> None:
    sample = _sample()
    registry = generate_legal_semantics_theorem_registry(sample)
    payload = registry.to_dict()

    assert registry.modal_ir_hash == sample.modal_ir.canonical_hash()
    assert registry.theorem_count == len(sample.modal_ir.formulas) * 8 + 1
    assert len(payload["registry_hash"]) == 64
    assert len({theorem.theorem_id for theorem in registry.theorems}) == registry.theorem_count
    assert len({theorem.evidence_hash for theorem in registry.theorems}) == registry.theorem_count

    categories = {theorem.category for theorem in registry.theorems}
    assert categories == {
        "compiler_decompiler_round_trip",
        "exception_scope",
        "graph_endpoint_integrity",
        "modality",
        "permission",
        "prohibition",
        "source_provenance",
        "source_roles",
        "temporal_bounds",
    }
    for theorem in registry.theorems:
        assert theorem.evidence_hash in theorem.statement
        assert registry.modal_ir_hash in theorem.statement
        assert theorem.theorem_name.startswith("legal_ir_")
        assert ":" not in theorem.theorem_name
        assert "-" not in theorem.theorem_name


def test_theorem_evidence_binds_semantic_facts_without_statement_authorship() -> None:
    registry = generate_legal_semantics_theorem_registry(_sample())
    permission_theorems = [
        theorem for theorem in registry.theorems if theorem.category == "permission"
    ]
    prohibition_theorems = [
        theorem for theorem in registry.theorems if theorem.category == "prohibition"
    ]
    exception_theorems = [
        theorem for theorem in registry.theorems if theorem.category == "exception_scope"
    ]
    temporal_theorems = [
        theorem for theorem in registry.theorems if theorem.category == "temporal_bounds"
    ]
    role_theorems = [
        theorem for theorem in registry.theorems if theorem.category == "source_roles"
    ]
    graph_theorem = next(
        theorem for theorem in registry.theorems if theorem.category == "graph_endpoint_integrity"
    )

    assert any(theorem.evidence["facts"]["permissionExpected"] is True for theorem in permission_theorems)
    assert any(theorem.evidence["facts"]["prohibitionExpected"] is True for theorem in prohibition_theorems)
    assert any(theorem.evidence["facts"]["exceptionCount"] > 0 for theorem in exception_theorems)
    assert any(theorem.evidence["facts"]["temporalCount"] > 0 for theorem in temporal_theorems)
    assert any(
        theorem.evidence["facts"]["actor"] and theorem.evidence["facts"]["action"]
        for theorem in role_theorems
    )
    assert graph_theorem.evidence["facts"]["graphEndpointIntegrity"] is True

    encoded = json.dumps(registry.to_dict(), sort_keys=True)
    assert "The Secretary may issue permits" not in encoded
    assert "No person may not transfer" not in encoded


def test_registry_is_deterministic_and_changes_with_canonical_ir() -> None:
    sample = _sample()
    baseline = generate_legal_semantics_theorem_registry(sample)
    again = generate_legal_semantics_theorem_registry(sample)
    changed_base = build_us_code_sample(
        title="42",
        section="101",
        text="The Secretary may issue permits within 45 days.",
    )
    changed_result = DeterministicModalLogicCodec(
        ModalLogicCodecConfig(parser_backend="spacy", embedding_dimensions=8)
    ).encode(
        changed_base.text,
        document_id=changed_base.sample_id,
        citation=changed_base.citation,
        source=changed_base.source,
        source_embedding=changed_base.embedding_vector,
    )
    changed = replace(
        changed_base,
        modal_ir=changed_result.modal_ir,
        frame_candidates=changed_result.frame_candidates,
        selected_frame=changed_result.selected_frame,
        losses=changed_result.losses,
    )

    assert baseline.to_dict() == again.to_dict()
    assert baseline.registry_hash != generate_legal_semantics_theorem_registry(changed).registry_hash


def test_leanstral_task_carries_registry_and_accepts_only_theorem_proof_bodies() -> None:
    task = LegalIRLeanTask.from_sample(_sample(), autoencoder_guidance=_guidance())
    assert task.theorem_registry is not None
    theorem = task.theorem_registry["theorems"][0]

    accepted = validate_leanstral_proposal(
        task,
        LeanstralProposal(
            schema_version="legal-ir-leanstral-proposal-v1",
            task_id=task.task_id,
            target_modal_ir_hash=task.modal_ir_hash,
            compiler_change_spec_id=str(task.compiler_change_spec["spec_id"]),
            proof="by unfold wellFormed modalityMatches sourceProvenancePresent; decide",
            theorem_proofs={theorem["theorem_id"]: "by decide"},
        ),
    )

    assert accepted.accepted is True
    assert accepted.proof_sha256

    unknown = validate_leanstral_proposal(
        task,
        LeanstralProposal(
            schema_version="legal-ir-leanstral-proposal-v1",
            task_id=task.task_id,
            target_modal_ir_hash=task.modal_ir_hash,
            compiler_change_spec_id=str(task.compiler_change_spec["spec_id"]),
            proof="by unfold wellFormed modalityMatches sourceProvenancePresent; decide",
            theorem_proofs={"not-owned-by-verifier": "by decide"},
        ),
    )
    assert unknown.accepted is False
    assert "unknown_theorem_proof_id" in unknown.reasons


def test_leanstral_proposal_rejects_statement_override_attempts() -> None:
    task = LegalIRLeanTask.from_sample(_sample(), autoencoder_guidance=_guidance())
    proposal = LeanstralProposal.from_mapping(
        {
            "schema_version": "legal-ir-leanstral-proposal-v1",
            "task_id": task.task_id,
            "target_modal_ir_hash": task.modal_ir_hash,
            "compiler_change_spec_id": str(task.compiler_change_spec["spec_id"]),
            "proof": "by unfold wellFormed modalityMatches sourceProvenancePresent; decide",
            "theorem_statement": "theorem injected : True := by trivial",
        }
    )

    rejected = validate_leanstral_proposal(task, proposal)

    assert rejected.accepted is False
    assert "proposal_attempted_theorem_statement_override" in rejected.reasons
