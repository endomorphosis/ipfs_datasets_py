"""Focused modal cue regressions for temporal vs conditional scope."""

from __future__ import annotations

import os

os.environ.setdefault("IPFS_DATASETS_PY_MINIMAL_IMPORTS", "1")
os.environ.setdefault("IPFS_DATASETS_AUTO_INSTALL", "false")
os.environ.setdefault("IPFS_KIT_AUTO_INSTALL_DEPS", "0")

from ipfs_datasets_py.logic.modal.compiler import (  # noqa: E402
    DeterministicModalCompiler,
    ModalCompilerConfig,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_registry import (  # noqa: E402
    COMPILER_REFINED_PACKET_002051_FAMILY_PAIRS,
    compiler_refined_modal_family_cue_margin_buffer,
    compiler_weak_typed_self_family_cue_margin_buffer,
    ModalLogicFamily,
    is_compiler_ambiguity_policy_pair,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.spacy_modal_codec import (  # noqa: E402
    ranked_modal_families,
)


def test_compiler_treats_after_application_cross_reference_as_non_temporal_scope() -> None:
    compiler = DeterministicModalCompiler(
        config=ModalCompilerConfig(parser_backend="spacy")
    )

    result = compiler.compile(
        (
            "After the application of subsection (f) and the preceding paragraphs "
            "of this subsection, as otherwise provided in this subsection, the "
            "Secretary shall issue guidance."
        ),
        document_id="compiler-ambiguity-after-application-cross-reference",
    )

    assert result.encoding is not None
    counts = result.encoding.modal_family_counts()
    assert counts.get(ModalLogicFamily.TEMPORAL.value, 0) == 0
    assert counts.get(ModalLogicFamily.CONDITIONAL_NORMATIVE.value, 0) >= 1


def test_compiler_preserves_temporal_after_date_sequence_cue() -> None:
    compiler = DeterministicModalCompiler(
        config=ModalCompilerConfig(parser_backend="spacy")
    )

    result = compiler.compile(
        "After June 1, 2030, the Secretary shall issue guidance.",
        document_id="compiler-ambiguity-after-calendar-date-temporal",
    )

    assert result.encoding is not None
    counts = result.encoding.modal_family_counts()
    assert counts.get(ModalLogicFamily.TEMPORAL.value, 0) >= 1


def test_compiler_reinforces_deontic_against_generic_frame_statutory_scope() -> None:
    compiler = DeterministicModalCompiler(
        config=ModalCompilerConfig(parser_backend="spacy")
    )

    result = compiler.compile(
        (
            "The authority of the Secretary under this section, as provided in this "
            "section, and requirements apply."
        ),
        document_id="compiler-ambiguity-frame-deontic-structural-scope",
    )

    assert result.encoding is not None
    ranking = ranked_modal_families(result.encoding)
    assert ranking
    shares = {entry["family"]: float(entry["share_raw"]) for entry in ranking}
    assert shares[ModalLogicFamily.DEONTIC.value] >= shares[ModalLogicFamily.FRAME.value]


def test_packet_002051_refined_family_pairs_are_registered() -> None:
    for predicted_family, target_family in COMPILER_REFINED_PACKET_002051_FAMILY_PAIRS:
        assert is_compiler_ambiguity_policy_pair(predicted_family, target_family)
        assert (
            compiler_refined_modal_family_cue_margin_buffer(
                predicted_family,
                target_family,
            )
            > 0.0
        )
        if predicted_family == target_family:
            assert (
                compiler_weak_typed_self_family_cue_margin_buffer(
                    predicted_family,
                    target_family,
                )
                > 0.0
            )


def test_compiler_preserves_deontic_authorized_and_directed_scope() -> None:
    compiler = DeterministicModalCompiler(
        config=ModalCompilerConfig(parser_backend="spacy")
    )

    result = compiler.compile(
        (
            "The National Science Foundation is authorized and directed to "
            "establish an Office of Small Business Research and Development "
            "under this section."
        ),
        document_id="compiler-ambiguity-frame-deontic-authorized-directed",
    )

    assert result.encoding is not None
    ranking = ranked_modal_families(result.encoding)
    assert ranking
    shares = {entry["family"]: float(entry["share_raw"]) for entry in ranking}
    assert shares[ModalLogicFamily.DEONTIC.value] > shares[ModalLogicFamily.FRAME.value]


def test_compiler_backfills_frame_share_for_statutory_temporal_scope_clause() -> None:
    compiler = DeterministicModalCompiler(
        config=ModalCompilerConfig(parser_backend="spacy")
    )

    result = compiler.compile(
        (
            "Under this chapter, this section, this subchapter, and this subtitle, "
            "after June 1, 2030, regulations apply."
        ),
        document_id="compiler-ambiguity-statutory-temporal-frame-backfill",
    )

    assert result.encoding is not None
    ranking = ranked_modal_families(result.encoding)
    assert ranking
    shares = {
        str(candidate["family"]): float(candidate.get("share_raw", candidate.get("share", 0.0)))
        for candidate in ranking
    }
    assert shares.get(ModalLogicFamily.FRAME.value, 0.0) > 0.0
    assert shares.get(ModalLogicFamily.TEMPORAL.value, 0.0) > shares.get(
        ModalLogicFamily.FRAME.value, 0.0
    )


def test_compiler_reinforces_temporal_conditional_statutory_competition() -> None:
    compiler = DeterministicModalCompiler(
        config=ModalCompilerConfig(parser_backend="spacy")
    )

    result = compiler.compile(
        (
            "For each fiscal year, the authority of the Secretary under this section, "
            "as provided in this section."
        ),
        document_id="compiler-ambiguity-temporal-conditional-statutory-scope",
    )

    assert result.encoding is not None
    ranking = ranked_modal_families(result.encoding)
    assert ranking
    shares = {entry["family"]: float(entry["share_raw"]) for entry in ranking}
    assert shares[ModalLogicFamily.CONDITIONAL_NORMATIVE.value] > shares[ModalLogicFamily.FRAME.value]
    assert shares[ModalLogicFamily.CONDITIONAL_NORMATIVE.value] >= 0.30


def test_compiler_reinforces_temporal_deontic_statutory_competition() -> None:
    compiler = DeterministicModalCompiler(
        config=ModalCompilerConfig(parser_backend="spacy")
    )

    result = compiler.compile(
        (
            "For each fiscal year, the authority of the Secretary under this section, "
            "and requirements apply."
        ),
        document_id="compiler-ambiguity-temporal-deontic-statutory-scope",
    )

    assert result.encoding is not None
    ranking = ranked_modal_families(result.encoding)
    assert ranking
    shares = {entry["family"]: float(entry["share_raw"]) for entry in ranking}
    assert shares[ModalLogicFamily.DEONTIC.value] > shares[ModalLogicFamily.FRAME.value]
    assert shares[ModalLogicFamily.DEONTIC.value] >= 0.25


def test_compiler_backfills_alethic_scope_in_frame_heavy_statutory_clauses() -> None:
    compiler = DeterministicModalCompiler(
        config=ModalCompilerConfig(parser_backend="spacy")
    )

    result = compiler.compile(
        (
            "The authority of the Secretary under this section, as provided in this "
            "section, and the agency is unable to enforce."
        ),
        document_id="compiler-ambiguity-frame-alethic-structural-scope",
    )

    assert result.encoding is not None
    ranking = ranked_modal_families(result.encoding)
    assert ranking
    shares = {entry["family"]: float(entry["share_raw"]) for entry in ranking}
    assert shares[ModalLogicFamily.ALETHIC.value] > 0.10
