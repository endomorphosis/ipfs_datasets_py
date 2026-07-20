"""Regression coverage for packet-000541 modal family cue policy."""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

import os

os.environ.setdefault("IPFS_DATASETS_PY_MINIMAL_IMPORTS", "1")
os.environ.setdefault("IPFS_DATASETS_AUTO_INSTALL", "false")
os.environ.setdefault("IPFS_KIT_AUTO_INSTALL_DEPS", "0")

import ipfs_datasets_py.logic.modal.compiler as modal_compiler_module  # noqa: E402
from ipfs_datasets_py.logic.modal.compiler import (  # noqa: E402
    DeterministicModalCompiler,
    ModalCompilerConfig,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_registry import (  # noqa: E402
    COMPILER_REFINED_PACKET_000541_FAMILY_PAIRS,
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


def _ranking_for_margin(
    *,
    predicted_family: str,
    target_family: str,
    family_margin: float,
) -> List[Dict[str, Any]]:
    if predicted_family == target_family:
        predicted_share = (1.0 + family_margin) / 2.0
        runner_up_family = (
            ModalLogicFamily.DEONTIC.value
            if predicted_family != ModalLogicFamily.DEONTIC.value
            else ModalLogicFamily.TEMPORAL.value
        )
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
                "family": runner_up_family,
                "count": 1,
                "logit": 1.1,
                "share_raw": predicted_share - family_margin,
                "share": predicted_share - family_margin,
                "source": "logit_softmax_fallback",
            },
        ]

    predicted_share = 0.7
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
            "share_raw": predicted_share + family_margin,
            "share": predicted_share + family_margin,
            "source": "logit_softmax_fallback",
        },
    ]


def test_packet_000541_family_pairs_are_registered() -> None:
    expected_pairs = (
        (
            ModalLogicFamily.DEONTIC.value,
            ModalLogicFamily.DEONTIC.value,
        ),
        (
            ModalLogicFamily.DEONTIC.value,
            ModalLogicFamily.TEMPORAL.value,
        ),
        (
            ModalLogicFamily.TEMPORAL.value,
            ModalLogicFamily.TEMPORAL.value,
        ),
    )

    assert COMPILER_REFINED_PACKET_000541_FAMILY_PAIRS == expected_pairs
    for predicted_family, target_family in expected_pairs:
        assert target_family in compiler_ambiguity_policy_targets(predicted_family)
        assert target_family in compiler_required_adaptive_ambiguity_targets(
            predicted_family
        )
        assert target_family in signal_free_adaptive_ambiguity_targets(predicted_family)
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


def test_packet_000541_buffers_cover_evidence_margins() -> None:
    assert (
        compiler_refined_modal_family_cue_margin_buffer(
            ModalLogicFamily.DEONTIC.value,
            ModalLogicFamily.TEMPORAL.value,
        )
        >= 0.45
    )
    assert (
        compiler_weak_typed_self_family_cue_margin_buffer(
            ModalLogicFamily.DEONTIC.value,
            ModalLogicFamily.DEONTIC.value,
        )
        >= 0.40
    )
    assert (
        compiler_weak_typed_self_family_cue_margin_buffer(
            ModalLogicFamily.TEMPORAL.value,
            ModalLogicFamily.TEMPORAL.value,
        )
        >= 0.24
    )


def test_compiler_exposes_packet_000541_explicit_adaptive_ambiguities(
    monkeypatch,
) -> None:
    cases: Tuple[Tuple[str, str, float, str, str], ...] = (
        (
            ModalLogicFamily.DEONTIC.value,
            ModalLogicFamily.TEMPORAL.value,
            -0.174364100332,
            "adaptive_deontic_temporal_outvoted_margin_low",
            "requires_rule",
        ),
        (
            ModalLogicFamily.DEONTIC.value,
            ModalLogicFamily.DEONTIC.value,
            0.070174523897,
            "adaptive_deontic_deontic_contested_margin_low",
            "review",
        ),
        (
            ModalLogicFamily.TEMPORAL.value,
            ModalLogicFamily.TEMPORAL.value,
            0.184268362314,
            "adaptive_temporal_temporal_contested_margin_low",
            "review",
        ),
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

    for (
        predicted_family,
        target_family,
        family_margin,
        expected_type,
        expected_severity,
    ) in cases:
        compiler = DeterministicModalCompiler(
            config=ModalCompilerConfig(parser_backend="regex")
        )
        ranking = _ranking_for_margin(
            predicted_family=predicted_family,
            target_family=target_family,
            family_margin=family_margin,
        )
        compiler._adaptive_family_ranking_from_logits = (  # type: ignore[method-assign]
            lambda _encoding, ranking=ranking: list(ranking)
        )

        result = compiler.compile(
            "The Secretary shall administer the program within the fiscal year.",
            document_id=f"compiler-ambiguity-packet-000541-{predicted_family}",
        )
        ambiguity = next(
            (
                item
                for item in result.ambiguities
                if item.ambiguity_type == expected_type
                and item.metadata.get("predicted_family") == predicted_family
                and item.metadata.get("target_family") == target_family
            ),
            None,
        )

        assert ambiguity is not None, [item.to_dict() for item in result.ambiguities]
        assert ambiguity.severity == expected_severity
        assert ambiguity.metadata.get("is_compiler_ambiguity_bundle_pair") is True
        assert ambiguity.metadata.get("ambiguity_policy_bundle") == "compiler_ambiguity"
        assert ambiguity.metadata.get("is_explicit_adaptive_ambiguity") is True
        assert ambiguity.metadata.get("explicit_ambiguity_type") == expected_type
        assert (
            abs(float(ambiguity.metadata.get("family_margin_raw", 0.0)) - family_margin)
            <= 1e-12
        )
