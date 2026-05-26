"""Packet-001151 regressions for compiler adaptive ambiguity exposure."""

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
    is_compiler_required_adaptive_ambiguity_pair,
    is_priority_signal_free_adaptive_ambiguity_pair,
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


def test_compiler_exposes_packet_001151_explicit_adaptive_family_ambiguities() -> None:
    cases = (
        {
            "sample_id": "us-code-42-14931.-1c951a73637b9c9a",
            "predicted_family": ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
            "target_family": ModalLogicFamily.TEMPORAL.value,
            "family_margin": -0.602520146129,
            "priority": 0.752520146129,
            "expected_type": "adaptive_conditional_normative_temporal_outvoted_margin_low",
            "expected_severity": "requires_rule",
            "runner_up_family": ModalLogicFamily.FRAME.value,
        },
        {
            "sample_id": "us-code-10-8112-7d7bba23e5caa30a",
            "predicted_family": ModalLogicFamily.TEMPORAL.value,
            "target_family": ModalLogicFamily.DEONTIC.value,
            "family_margin": -0.193227673171,
            "priority": 0.343227673171,
            "expected_type": "adaptive_temporal_deontic_outvoted_margin_low",
            "expected_severity": "requires_rule",
            "runner_up_family": ModalLogicFamily.FRAME.value,
        },
        {
            "sample_id": "us-code-36-220531-4a5ba9b0f32a6f60",
            "predicted_family": ModalLogicFamily.TEMPORAL.value,
            "target_family": ModalLogicFamily.FRAME.value,
            "family_margin": -0.411828791395,
            "priority": 0.561828791395,
            "expected_type": "adaptive_temporal_frame_outvoted_margin_low",
            "expected_severity": "requires_rule",
            "runner_up_family": ModalLogicFamily.DEONTIC.value,
        },
        {
            "sample_id": "us-code-33-569b-025723fc772bf390",
            "predicted_family": ModalLogicFamily.DEONTIC.value,
            "target_family": ModalLogicFamily.FRAME.value,
            "family_margin": -0.206770396343,
            "priority": 0.356770396343,
            "expected_type": "adaptive_deontic_frame_outvoted_margin_low",
            "expected_severity": "requires_rule",
            "runner_up_family": ModalLogicFamily.TEMPORAL.value,
        },
        {
            "sample_id": "us-code-16-459i-1-441224bf1e72b168",
            "predicted_family": ModalLogicFamily.FRAME.value,
            "target_family": ModalLogicFamily.DEONTIC.value,
            "family_margin": -0.449934584077,
            "priority": 0.599934584077,
            "expected_type": "adaptive_frame_deontic_outvoted_margin_low",
            "expected_severity": "requires_rule",
            "runner_up_family": ModalLogicFamily.TEMPORAL.value,
        },
        {
            "sample_id": "us-code-19-261-8a5466c4b19b1159",
            "predicted_family": ModalLogicFamily.FRAME.value,
            "target_family": ModalLogicFamily.TEMPORAL.value,
            "family_margin": -0.156360591701,
            "priority": 0.306360591701,
            "expected_type": "adaptive_frame_temporal_outvoted_margin_low",
            "expected_severity": "requires_rule",
            "runner_up_family": ModalLogicFamily.DEONTIC.value,
        },
        {
            "sample_id": "us-code-36-151306-7b4f2ca7d9b05837",
            "predicted_family": ModalLogicFamily.DEONTIC.value,
            "target_family": ModalLogicFamily.DEONTIC.value,
            "family_margin": 0.079547856857,
            "priority": 0.070452143143,
            "expected_type": "adaptive_deontic_deontic_contested_margin_low",
            "expected_severity": "review",
            "runner_up_family": ModalLogicFamily.TEMPORAL.value,
        },
    )

    for case in cases:
        compiler = DeterministicModalCompiler(
            config=ModalCompilerConfig(parser_backend="spacy")
        )
        predicted_family = str(case["predicted_family"])
        target_family = str(case["target_family"])
        expected_margin = float(case["family_margin"])
        expected_priority = float(case["priority"])
        expected_required = is_compiler_required_adaptive_ambiguity_pair(
            predicted_family,
            target_family,
        )
        expected_priority_pair = is_priority_signal_free_adaptive_ambiguity_pair(
            predicted_family,
            target_family,
        )
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
            "As provided in section 3, the Secretary shall act by June 1, 2030.",
            document_id=f"compiler-ambiguity-packet-001151-{case['sample_id']}",
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
            expected_required
        )
        assert ambiguity.metadata.get("is_priority_policy_pair") is bool(
            expected_priority_pair
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
