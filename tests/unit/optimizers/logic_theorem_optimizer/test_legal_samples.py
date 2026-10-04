"""Tests for deterministic U.S. Code legal sample contracts."""

from __future__ import annotations

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_samples import (
    LegalSample,
    LegalSampleValidationError,
    build_us_code_sample,
    stable_mock_embedding,
)


def test_stable_mock_embedding_is_deterministic() -> None:
    first = stable_mock_embedding("The agency must provide notice.", dimensions=4)
    second = stable_mock_embedding("The agency must provide notice.", dimensions=4)

    assert first == second
    assert len(first) == 4


def test_build_us_code_sample_includes_modal_ir_and_frame_candidates() -> None:
    sample = build_us_code_sample(
        title="5",
        section="552",
        citation="5 U.S.C. 552",
        text="The agency must provide notice and a hearing before a final order.",
    )

    assert sample.source == "us_code"
    assert sample.sample_id.startswith("us-code-5-552-")
    assert sample.modal_ir.formulas
    assert sample.frame_candidates
    assert sample.selected_frame == sample.frame_candidates[0]["frame_id"]
    assert sample.parser_trace["frame_selector"] == "bm25_v1"
    assert sample.to_json() == sample.to_json()


def test_build_us_code_sample_is_deterministic_for_normalized_text() -> None:
    first = build_us_code_sample(
        title="42",
        section="1437f",
        text="The tenant may request a housing voucher accommodation.",
    )
    second = build_us_code_sample(
        title="42",
        section="1437f",
        text=" The   tenant may request a housing voucher accommodation. ",
    )

    assert first.sample_id == second.sample_id
    assert first.embedding_vector == second.embedding_vector
    assert first.modal_ir.canonical_hash() == second.modal_ir.canonical_hash()


def test_legal_sample_validation_rejects_empty_embedding() -> None:
    sample = build_us_code_sample(
        title="5",
        section="1",
        text="The agency must act.",
    )
    corrupt = LegalSample(
        sample_id=sample.sample_id,
        source=sample.source,
        title=sample.title,
        section=sample.section,
        citation=sample.citation,
        text=sample.text,
        normalized_text=sample.normalized_text,
        embedding_model=sample.embedding_model,
        embedding_vector=[],
        modal_ir=sample.modal_ir,
        frame_candidates=sample.frame_candidates,
        selected_frame=sample.selected_frame,
    )

    with pytest.raises(LegalSampleValidationError, match="embedding_vector"):
        corrupt.validate()
