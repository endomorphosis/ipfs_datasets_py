"""Focused regressions for modal decompiler source-copy accounting."""

from __future__ import annotations

from ipfs_datasets_py.logic.modal import DecodedModalPhrase, DecodedModalText
from ipfs_datasets_py.logic.modal.codec import _source_span_copy_ratio


def _decoded(*phrases: DecodedModalPhrase) -> DecodedModalText:
    return DecodedModalText(
        source_id="source-copy-ratio-test",
        text=" ".join(phrase.text for phrase in phrases),
        phrases=list(phrases),
        support_span=[0, 0],
    )


def test_source_span_copy_ratio_is_one_for_source_only_reconstruction() -> None:
    decoded = _decoded(
        DecodedModalPhrase(
            text="The agency shall publish notice",
            slot="modal_source_span",
        )
    )

    assert _source_span_copy_ratio(decoded) == 1.0


def test_source_span_copy_ratio_is_zero_for_unrelated_structural_output() -> None:
    decoded = _decoded(
        DecodedModalPhrase(
            text="publish notice",
            slot="predicate",
        ),
        DecodedModalPhrase(
            text="agency",
            slot="argument_actor",
        ),
    )

    assert _source_span_copy_ratio(decoded) == 0.0


def test_source_span_copy_ratio_tracks_source_share_of_mixed_output() -> None:
    decoded = _decoded(
        DecodedModalPhrase(
            text="The agency shall publish notice",
            slot="source_context_span",
        ),
        DecodedModalPhrase(
            text="obligation publish notice agency",
            slot="typed_ir_reconstruction",
        ),
    )

    assert _source_span_copy_ratio(decoded) == round(5 / 9, 9)


def test_source_span_copy_ratio_adds_semantic_support_only_to_denominator() -> None:
    decoded = _decoded(
        DecodedModalPhrase(
            text="The agency shall publish notice",
            slot="modal_source_span",
        ),
        DecodedModalPhrase(
            text="deontic",
            slot="modal_family",
            provenance_only=True,
        ),
    )

    assert _source_span_copy_ratio(decoded) == round(5 / 6, 9)


def test_source_span_copy_ratio_excludes_provenance_only_source_diagnostics() -> None:
    decoded = _decoded(
        DecodedModalPhrase(
            text="The agency shall publish notice",
            slot="modal_source_span",
            provenance_only=True,
        )
    )

    assert _source_span_copy_ratio(decoded) == 0.0
