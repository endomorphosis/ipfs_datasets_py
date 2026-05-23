"""Regression coverage for packet-001792 compiler ambiguity policy evidence."""

from __future__ import annotations

import os
from typing import Any, Dict, List

os.environ.setdefault("IPFS_DATASETS_PY_MINIMAL_IMPORTS", "1")
os.environ.setdefault("IPFS_DATASETS_AUTO_INSTALL", "false")
os.environ.setdefault("IPFS_KIT_AUTO_INSTALL_DEPS", "0")

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


def _adaptive_explicit_ambiguity_from_source(
    result: Any,
    *,
    predicted_family: str,
    target_family: str,
    predicted_family_source: str,
):
    for ambiguity in result.ambiguities:
        if not ambiguity.ambiguity_type.startswith("adaptive_"):
            continue
        if ambiguity.ambiguity_type == "adaptive_family_margin_low":
            continue
        if ambiguity.metadata.get("adaptive_predicted_family_source") != predicted_family_source:
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
    runner_up_family: str,
) -> List[Dict[str, float | int | str]]:
    if predicted_family == target_family:
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
                "family": runner_up_family,
                "count": 0,
                "logit": 1.1,
                "share_raw": runner_up_share,
                "share": runner_up_share,
                "source": "logit_softmax_fallback",
            },
        ]

    predicted_share = (1.0 - family_margin) / 2.0
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


def test_modal_registry_packet_001792_policy_pairs_are_supported() -> None:
    cases = (
        {
            "predicted_family": ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
            "target_family": ModalLogicFamily.EPISTEMIC.value,
            "expected_required": False,
            "expected_priority": False,
        },
        {
            "predicted_family": ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
            "target_family": ModalLogicFamily.TEMPORAL.value,
            "expected_required": True,
            "expected_priority": True,
        },
        {
            "predicted_family": ModalLogicFamily.DEONTIC.value,
            "target_family": ModalLogicFamily.DEONTIC.value,
            "expected_required": True,
            "expected_priority": True,
        },
        {
            "predicted_family": ModalLogicFamily.TEMPORAL.value,
            "target_family": ModalLogicFamily.DEONTIC.value,
            "expected_required": True,
            "expected_priority": True,
        },
        {
            "predicted_family": ModalLogicFamily.TEMPORAL.value,
            "target_family": ModalLogicFamily.FRAME.value,
            "expected_required": True,
            "expected_priority": True,
        },
    )

    for case in cases:
        predicted_family = str(case["predicted_family"])
        target_family = str(case["target_family"])
        assert is_compiler_ambiguity_policy_pair(predicted_family, target_family)
        assert supports_signal_free_adaptive_ambiguity_pair(
            predicted_family,
            target_family,
        )
        assert is_compiler_required_adaptive_ambiguity_pair(
            predicted_family,
            target_family,
        ) is bool(case["expected_required"])
        assert is_priority_signal_free_adaptive_ambiguity_pair(
            predicted_family,
            target_family,
        ) is bool(case["expected_priority"])


def test_compiler_preserves_packet_001792_compiler_ambiguity_policy_margins() -> None:
    cases = [
        {
            "sample_id": "us-code-26-36A-10954a4e36c10322",
            "predicted_family": ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
            "target_family": ModalLogicFamily.TEMPORAL.value,
            "family_margin": -0.530872190568,
            "priority": 0.680872190568,
            "expected_type": "adaptive_conditional_normative_temporal_outvoted_margin_low",
            "expected_severity": "requires_rule",
            "runner_up_family": ModalLogicFamily.FRAME.value,
            "expected_required": True,
            "expected_priority": True,
        },
        {
            "sample_id": "us-code-42-14401.-0b0bdc6b9bf890ca",
            "predicted_family": ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
            "target_family": ModalLogicFamily.EPISTEMIC.value,
            "family_margin": -0.39873926939,
            "priority": 0.54873926939,
            "expected_type": "adaptive_conditional_normative_epistemic_outvoted_margin_low",
            "expected_severity": "requires_rule",
            "runner_up_family": ModalLogicFamily.FRAME.value,
            "expected_required": False,
            "expected_priority": False,
        },
        {
            "sample_id": "us-code-21-1708a-2a7f7a75f419c130",
            "predicted_family": ModalLogicFamily.TEMPORAL.value,
            "target_family": ModalLogicFamily.DEONTIC.value,
            "family_margin": -0.401400440413,
            "priority": 0.551400440413,
            "expected_type": "adaptive_temporal_deontic_outvoted_margin_low",
            "expected_severity": "requires_rule",
            "runner_up_family": ModalLogicFamily.FRAME.value,
            "expected_required": True,
            "expected_priority": True,
        },
        {
            "sample_id": "us-code-12-2128-5613a60d898de249",
            "predicted_family": ModalLogicFamily.DEONTIC.value,
            "target_family": ModalLogicFamily.DEONTIC.value,
            "family_margin": 0.084713159195,
            "priority": 0.065286840805,
            "expected_type": "adaptive_deontic_deontic_contested_margin_low",
            "expected_severity": "review",
            "runner_up_family": ModalLogicFamily.TEMPORAL.value,
            "expected_required": True,
            "expected_priority": True,
        },
        {
            "sample_id": "us-code-52-20705.-d41ef3d65b4e95c4",
            "predicted_family": ModalLogicFamily.TEMPORAL.value,
            "target_family": ModalLogicFamily.FRAME.value,
            "family_margin": -0.503240849757,
            "priority": 0.653240849757,
            "expected_type": "adaptive_temporal_frame_outvoted_margin_low",
            "expected_severity": "requires_rule",
            "runner_up_family": ModalLogicFamily.DEONTIC.value,
            "expected_required": True,
            "expected_priority": True,
        },
    ]

    for case in cases:
        compiler = DeterministicModalCompiler(
            config=ModalCompilerConfig(parser_backend="spacy")
        )
        predicted_family = str(case["predicted_family"])
        target_family = str(case["target_family"])
        expected_margin = float(case["family_margin"])
        expected_priority = float(case["priority"])
        ranking = _adaptive_ranking_for_margin(
            predicted_family=predicted_family,
            target_family=target_family,
            family_margin=expected_margin,
            runner_up_family=str(case["runner_up_family"]),
        )

        def _mock_adaptive_family_ranking_from_logits(
            _encoding,
            *,
            ranking_payload: List[Dict[str, float | int | str]] = ranking,
        ) -> List[Dict[str, float | int | str]]:
            return list(ranking_payload)

        compiler._adaptive_family_ranking_from_logits = _mock_adaptive_family_ranking_from_logits  # type: ignore[method-assign]

        result = compiler.compile(
            "Within 30 days after June 1, 2030, the Secretary shall issue guidance if eligible.",
            document_id=f"compiler-ambiguity-packet-001792-{case['sample_id']}",
        )

        ambiguity = _adaptive_explicit_ambiguity_from_source(
            result,
            predicted_family=predicted_family,
            target_family=target_family,
            predicted_family_source="adaptive_logits",
        )
        assert ambiguity is not None, str(case["sample_id"])
        assert ambiguity.ambiguity_type == str(case["expected_type"])
        assert ambiguity.severity == str(case["expected_severity"])
        assert ambiguity.metadata.get("is_compiler_ambiguity_bundle_pair") is True
        assert ambiguity.metadata.get("ambiguity_policy_bundle") == "compiler_ambiguity"
        assert ambiguity.metadata.get("is_compiler_required_policy_pair") is bool(
            case["expected_required"]
        )
        assert ambiguity.metadata.get("is_priority_policy_pair") is bool(
            case["expected_priority"]
        )
        assert (
            abs(
                float(ambiguity.metadata.get("family_margin_raw", 0.0))
                - expected_margin
            )
            <= 1e-12
        )
        assert (
            abs(
                float(ambiguity.metadata.get("priority", 0.0))
                - expected_priority
            )
            <= 1e-12
        )
        assert (
            abs(
                float(ambiguity.metadata.get("adaptive_priority", 0.0))
                - expected_priority
            )
            <= 1e-12
        )
