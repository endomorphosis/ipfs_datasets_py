"""Regression coverage for packet-003093 modal family cue policy."""

from __future__ import annotations

import os
from typing import Any, Dict, List

os.environ.setdefault("IPFS_DATASETS_PY_MINIMAL_IMPORTS", "1")
os.environ.setdefault("IPFS_DATASETS_AUTO_INSTALL", "false")
os.environ.setdefault("IPFS_KIT_AUTO_INSTALL_DEPS", "0")

import ipfs_datasets_py.logic.modal.compiler as modal_compiler_module  # noqa: E402
from ipfs_datasets_py.logic.modal.compiler import (  # noqa: E402
    DeterministicModalCompiler,
    ModalCompilerConfig,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_registry import (  # noqa: E402
    COMPILER_AMBIGUITY_PACKET_003093_FAMILY_PAIRS,
    ModalLogicFamily,
    compiler_ambiguity_policy_targets,
    compiler_refined_modal_family_cue_margin_buffer,
    compiler_required_adaptive_ambiguity_targets,
    compiler_weak_typed_self_family_cue_margin_buffer,
    is_compiler_ambiguity_policy_pair,
    is_compiler_required_adaptive_ambiguity_pair,
    is_priority_signal_free_adaptive_ambiguity_pair,
    is_signal_free_adaptive_ambiguity_pair,
    priority_signal_free_adaptive_ambiguity_targets,
    signal_free_adaptive_ambiguity_targets,
    supports_signal_free_adaptive_ambiguity_pair,
)


def _ranking_for_outvote(
    *,
    predicted_family: str,
    target_family: str,
    family_margin: float,
) -> List[Dict[str, Any]]:
    predicted_share = 0.7
    target_share = predicted_share + family_margin
    return [
        {
            "family": predicted_family,
            "count": 1,
            "logit": 1.3,
            "share_raw": predicted_share,
            "share": predicted_share,
            "source": "logit_softmax_fallback",
        },
        {
            "family": target_family,
            "count": 1,
            "logit": 1.1,
            "share_raw": target_share,
            "share": target_share,
            "source": "logit_softmax_fallback",
        },
    ]


def _ranking_for_weak_self_margin(
    *,
    predicted_family: str,
    target_family: str,
    family_margin: float,
) -> List[Dict[str, Any]]:
    assert target_family == predicted_family
    predicted_share = 0.449276775148
    duplicate_share = predicted_share + family_margin
    return [
        {
            "family": predicted_family,
            "count": 1,
            "logit": 1.3,
            "share_raw": predicted_share,
            "share": predicted_share,
            "source": "logit_softmax_fallback",
        },
        {
            "family": predicted_family,
            "count": 1,
            "logit": 1.1,
            "share_raw": duplicate_share,
            "share": duplicate_share,
            "source": "logit_softmax_fallback",
        },
    ]


def test_packet_003093_family_pairs_are_registered() -> None:
    expected_pairs = (
        (
            ModalLogicFamily.DEONTIC.value,
            ModalLogicFamily.DEONTIC.value,
        ),
        (
            ModalLogicFamily.FRAME.value,
            ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ),
        (
            ModalLogicFamily.FRAME.value,
            ModalLogicFamily.DEONTIC.value,
        ),
    )

    assert COMPILER_AMBIGUITY_PACKET_003093_FAMILY_PAIRS == expected_pairs
    for predicted_family, target_family in expected_pairs:
        assert target_family in compiler_ambiguity_policy_targets(predicted_family)
        assert target_family in compiler_required_adaptive_ambiguity_targets(
            predicted_family
        )
        assert target_family in signal_free_adaptive_ambiguity_targets(
            predicted_family
        )
        assert target_family in priority_signal_free_adaptive_ambiguity_targets(
            predicted_family
        )
        assert is_compiler_ambiguity_policy_pair(predicted_family, target_family)
        assert is_compiler_required_adaptive_ambiguity_pair(
            predicted_family,
            target_family,
        )
        assert is_signal_free_adaptive_ambiguity_pair(
            predicted_family,
            target_family,
        )
        assert is_priority_signal_free_adaptive_ambiguity_pair(
            predicted_family,
            target_family,
        )
        assert supports_signal_free_adaptive_ambiguity_pair(
            predicted_family,
            target_family,
        )


def test_packet_003093_refined_buffers_cover_evidence_margins() -> None:
    assert (
        compiler_refined_modal_family_cue_margin_buffer(
            ModalLogicFamily.FRAME.value,
            ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        )
        >= 1.03
    )
    assert (
        compiler_refined_modal_family_cue_margin_buffer(
            ModalLogicFamily.FRAME.value,
            ModalLogicFamily.DEONTIC.value,
        )
        >= 1.02
    )
    assert (
        compiler_refined_modal_family_cue_margin_buffer(
            ModalLogicFamily.DEONTIC.value,
            ModalLogicFamily.DEONTIC.value,
        )
        + compiler_weak_typed_self_family_cue_margin_buffer(
            ModalLogicFamily.DEONTIC.value,
            ModalLogicFamily.DEONTIC.value,
        )
        >= 0.385866873598
    )


def test_compiler_exposes_packet_003093_explicit_adaptive_ambiguities(
    monkeypatch,
) -> None:
    cases = (
        {
            "predicted_family": ModalLogicFamily.FRAME.value,
            "target_family": ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
            "family_margin": -0.766765436928,
            "expected_type": "adaptive_frame_conditional_normative_outvoted_margin_low",
            "ranking_factory": _ranking_for_outvote,
        },
        {
            "predicted_family": ModalLogicFamily.FRAME.value,
            "target_family": ModalLogicFamily.DEONTIC.value,
            "family_margin": -0.017322315373,
            "expected_type": "adaptive_frame_deontic_outvoted_margin_low",
            "ranking_factory": _ranking_for_outvote,
        },
        {
            "predicted_family": ModalLogicFamily.DEONTIC.value,
            "target_family": ModalLogicFamily.DEONTIC.value,
            "family_margin": 0.195866873598,
            "expected_type": "adaptive_deontic_deontic_contested_margin_low",
            "ranking_factory": _ranking_for_weak_self_margin,
        },
    )
    monkeypatch.setattr(
        modal_compiler_module,
        "ranked_modal_families",
        lambda _encoding: [],
    )
    monkeypatch.setattr(
        modal_compiler_module,
        "modal_ambiguity_signals",
        lambda _encoding: {},
    )

    for case in cases:
        compiler = DeterministicModalCompiler(
            config=ModalCompilerConfig(parser_backend="regex")
        )
        predicted_family = str(case["predicted_family"])
        target_family = str(case["target_family"])
        family_margin = float(case["family_margin"])
        ranking = case["ranking_factory"](
            predicted_family=predicted_family,
            target_family=target_family,
            family_margin=family_margin,
        )
        compiler._adaptive_family_ranking_from_logits = (  # type: ignore[method-assign]
            lambda _encoding, ranking=ranking: list(ranking)
        )

        result = compiler.compile(
            "An officer shall provide supplies subject to this section.",
            document_id=f"compiler-ambiguity-packet-003093-{predicted_family}",
        )
        ambiguity = next(
            (
                item
                for item in result.ambiguities
                if item.ambiguity_type == case["expected_type"]
                and item.metadata.get("predicted_family") == predicted_family
                and item.metadata.get("target_family") == target_family
            ),
            None,
        )

        assert ambiguity is not None, [item.to_dict() for item in result.ambiguities]
        assert ambiguity.metadata.get("is_compiler_ambiguity_bundle_pair") is True
        assert ambiguity.metadata.get("ambiguity_policy_bundle") == "compiler_ambiguity"
        assert ambiguity.metadata.get("is_explicit_adaptive_ambiguity") is True
        assert ambiguity.metadata.get("explicit_ambiguity_type") == case["expected_type"]
        assert (
            abs(float(ambiguity.metadata.get("family_margin_raw", 0.0)) - family_margin)
            <= 1e-12
        )
