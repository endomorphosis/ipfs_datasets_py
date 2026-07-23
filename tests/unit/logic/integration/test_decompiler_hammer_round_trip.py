"""Tests for decompiler round-trip hammer obligations and guardrails."""

from __future__ import annotations

import pytest

from ipfs_datasets_py.logic.integration.reasoning import (
    generate_legal_ir_proof_obligations,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_samples import (
    build_us_code_sample,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder import (
    _legal_ir_objective_component,
    _source_decompiled_text_losses_from_targets,
)


def test_decompiler_round_trip_obligations_preserve_structure_not_source_text() -> None:
    sample = build_us_code_sample(
        title="5",
        section="552",
        text=(
            "The agency shall provide notice unless an exception applies before "
            "the final order."
        ),
    )

    obligations = generate_legal_ir_proof_obligations(sample)
    by_kind = {obligation.kind: obligation for obligation in obligations}

    assert "decompiler_round_trip_signature" in by_kind
    assert "decompiler_structural_summary" in by_kind
    assert "decompiler_modality_retention" in by_kind
    assert "decompiler_source_copy_guardrail" in by_kind
    assert "decompiler_exception_scope_retention" in by_kind
    assert by_kind["decompiler_structural_summary"].legal_ir_view == "modal.decompiler"
    assert "source_span_sha256" in by_kind["decompiler_source_copy_guardrail"].metadata
    for obligation in obligations:
        assert sample.text not in obligation.statement
        assert obligation.metadata.get("source_span_sha256") != sample.text


def test_source_decompiled_losses_include_round_trip_copy_guardrails() -> None:
    losses = _source_decompiled_text_losses_from_targets(
        {
            "source_copy_loss": 0.90,
            "source_decompiled_text_embedding_cosine_similarity": 0.80,
            "structural_text_reconstruction_loss": 0.30,
        }
    )

    assert losses["source_decompiled_text_embedding_cosine_loss"] == pytest.approx(0.20)
    assert losses["source_decompiled_text_token_loss"] == pytest.approx(0.30)
    assert losses["round_trip_structural_reconstruction_loss"] == pytest.approx(0.30)
    assert losses["round_trip_source_copy_guardrail_loss"] == pytest.approx(0.25)
    assert _legal_ir_objective_component(losses) > 0.0
