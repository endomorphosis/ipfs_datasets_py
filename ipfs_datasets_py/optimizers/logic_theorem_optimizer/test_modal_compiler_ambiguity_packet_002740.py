"""Packet-002740 regressions for compiler adaptive ambiguity policy margins."""

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
    ModalLogicFamily,
    is_compiler_ambiguity_policy_pair,
    is_compiler_required_adaptive_ambiguity_pair,
    is_priority_signal_free_adaptive_ambiguity_pair,
    supports_signal_free_adaptive_ambiguity_pair,
)


def _adaptive_explicit_ambiguity_from_adaptive_logits_fallback(
    result: Any,
    *,
    predicted_family: str,
    target_family: str,
):
    for ambiguity in result.ambiguities:
        if not ambiguity.ambiguity_type.startswith("adaptive_"):
            continue
        if ambiguity.ambiguity_type == "adaptive_family_margin_low":
            continue
        if (
            ambiguity.metadata.get("adaptive_predicted_family_source")
            != "adaptive_logits_fallback"
        ):
            continue
        if ambiguity.metadata.get("predicted_family") != predicted_family:
            continue
        if ambiguity.metadata.get("target_family") != target_family:
            continue
        return ambiguity
    return None


def _adaptive_ranking_for_margin(
    *,
    predicted_family: str,
    target_family: str,
    family_margin: float,
    runner_up_family: str | None = None,
) -> List[Dict[str, float | int | str]]:
    if predicted_family == target_family:
        resolved_runner_up_family = runner_up_family or ModalLogicFamily.TEMPORAL.value
        if resolved_runner_up_family == predicted_family:
            resolved_runner_up_family = ModalLogicFamily.FRAME.value
        predicted_share = (1.0 + family_margin) / 2.0
        runner_up_share = predicted_share - family_margin
        return [
            {
                "family": predicted_family,
                "count": 0,
                "logit": 1.3,
                "share_raw": predicted_share,
                "share": predicted_share,
                "source": "logit_softmax_fallback",
            },
            {
                "family": resolved_runner_up_family,
                "count": 0,
                "logit": 1.2,
                "share_raw": runner_up_share,
                "share": runner_up_share,
                "source": "logit_softmax_fallback",
            },
        ]

    predicted_share = 0.70
    target_share = predicted_share + family_margin
    return [
        {
            "family": predicted_family,
            "count": 0,
            "logit": 1.3,
            "share_raw": predicted_share,
            "share": predicted_share,
            "source": "logit_softmax_fallback",
        },
        {
            "family": target_family,
            "count": 0,
            "logit": 1.1,
            "share_raw": target_share,
            "share": target_share,
            "source": "logit_softmax_fallback",
        },
    ]


def test_modal_registry_packet_002740_policy_pairs_are_supported() -> None:
    family_pairs = (
        (ModalLogicFamily.TEMPORAL.value, ModalLogicFamily.DEONTIC.value),
        (ModalLogicFamily.DEONTIC.value, ModalLogicFamily.DEONTIC.value),
        (ModalLogicFamily.DEONTIC.value, ModalLogicFamily.TEMPORAL.value),
        (ModalLogicFamily.CONDITIONAL_NORMATIVE.value, ModalLogicFamily.DEONTIC.value),
        (ModalLogicFamily.DEONTIC.value, ModalLogicFamily.FRAME.value),
    )

    for predicted_family, target_family in family_pairs:
        assert is_compiler_ambiguity_policy_pair(predicted_family, target_family)
        assert is_compiler_required_adaptive_ambiguity_pair(
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


def test_compiler_preserves_packet_002740_adaptive_ambiguity_margins(monkeypatch) -> None:
    cases = (
        {
            "sample_id": "us-code-25-500-3b722cd5f1157e80",
            "predicted_family": ModalLogicFamily.TEMPORAL.value,
            "target_family": ModalLogicFamily.DEONTIC.value,
            "family_margin": -0.374634878144,
            "priority": 0.524634878144,
            "severity": "requires_rule",
            "expected_type": "adaptive_temporal_deontic_outvoted_margin_low",
        },
        {
            "sample_id": "us-code-43-390h-7e797be64a6c5396",
            "predicted_family": ModalLogicFamily.TEMPORAL.value,
            "target_family": ModalLogicFamily.DEONTIC.value,
            "family_margin": -0.258798110324,
            "priority": 0.408798110324,
            "severity": "requires_rule",
            "expected_type": "adaptive_temporal_deontic_outvoted_margin_low",
        },
        {
            "sample_id": "us-code-22-5858-a94f14ede6acb24e",
            "predicted_family": ModalLogicFamily.DEONTIC.value,
            "target_family": ModalLogicFamily.TEMPORAL.value,
            "family_margin": -0.31349783657,
            "priority": 0.46349783657,
            "severity": "requires_rule",
            "expected_type": "adaptive_deontic_temporal_outvoted_margin_low",
        },
        {
            "sample_id": "us-code-15-9025-3af200223662a56a",
            "predicted_family": ModalLogicFamily.DEONTIC.value,
            "target_family": ModalLogicFamily.DEONTIC.value,
            "family_margin": 0.000130980298,
            "priority": 0.149869019702,
            "severity": "review",
            "expected_type": "adaptive_deontic_deontic_contested_margin_low",
            "runner_up_family": ModalLogicFamily.TEMPORAL.value,
        },
        {
            "sample_id": "us-code-42-6316.-e2abfc568bbb0e12",
            "predicted_family": ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
            "target_family": ModalLogicFamily.DEONTIC.value,
            "family_margin": -0.080733386303,
            "priority": 0.230733386303,
            "severity": "requires_rule",
            "expected_type": "adaptive_conditional_normative_deontic_outvoted_margin_low",
        },
        {
            "sample_id": "us-code-40-8103-3d3203e69bc40a43",
            "predicted_family": ModalLogicFamily.TEMPORAL.value,
            "target_family": ModalLogicFamily.DEONTIC.value,
            "family_margin": -0.275745284499,
            "priority": 0.425745284499,
            "severity": "requires_rule",
            "expected_type": "adaptive_temporal_deontic_outvoted_margin_low",
        },
        {
            "sample_id": "us-code-54-101332.-dc6a4d6abc3477ac",
            "predicted_family": ModalLogicFamily.DEONTIC.value,
            "target_family": ModalLogicFamily.FRAME.value,
            "family_margin": -0.492458749889,
            "priority": 0.642458749889,
            "severity": "requires_rule",
            "expected_type": "adaptive_deontic_frame_outvoted_margin_low",
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
        expected_priority = float(case["priority"])
        ranking = _adaptive_ranking_for_margin(
            predicted_family=predicted_family,
            target_family=target_family,
            family_margin=family_margin,
            runner_up_family=(
                str(case["runner_up_family"])
                if case.get("runner_up_family") is not None
                else None
            ),
        )
        compiler._adaptive_family_ranking_from_logits = (  # type: ignore[method-assign]
            lambda _encoding, ranking=ranking: list(ranking)
        )

        result = compiler.compile(
            "As provided in section 3, the Secretary shall act by June 1, 2030.",
            document_id=f"compiler-ambiguity-packet-002740-{case['sample_id']}",
        )
        ambiguity = _adaptive_explicit_ambiguity_from_adaptive_logits_fallback(
            result,
            predicted_family=predicted_family,
            target_family=target_family,
        )
        assert ambiguity is not None, case["sample_id"]
        assert ambiguity.ambiguity_type == str(case["expected_type"])
        assert ambiguity.severity == str(case["severity"])
        assert ambiguity.metadata.get("is_explicit_adaptive_ambiguity") is True
        assert ambiguity.metadata.get("is_compiler_ambiguity_bundle_pair") is True
        assert ambiguity.metadata.get("ambiguity_policy_bundle") == "compiler_ambiguity"
        assert ambiguity.metadata.get("is_compiler_required_policy_pair") is True
        assert (
            abs(float(ambiguity.metadata.get("family_margin_raw", 0.0)) - family_margin)
            <= 1e-12
        )
        assert (
            abs(float(ambiguity.metadata.get("priority", 0.0)) - expected_priority)
            <= 1e-12
        )
        assert (
            abs(float(ambiguity.metadata.get("adaptive_priority", 0.0)) - expected_priority)
            <= 1e-12
        )
