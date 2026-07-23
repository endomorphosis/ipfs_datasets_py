"""Packet-003972 regressions for compiler adaptive ambiguity policy coverage."""

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
    runner_up_family: str | None = None,
) -> List[Dict[str, float | int | str]]:
    if predicted_family == target_family:
        resolved_runner_up_family = runner_up_family or ModalLogicFamily.TEMPORAL.value
        if resolved_runner_up_family == predicted_family:
            resolved_runner_up_family = ModalLogicFamily.DEONTIC.value
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


def test_modal_registry_packet_003972_policy_pairs_are_supported() -> None:
    policy_pairs = (
        (ModalLogicFamily.DEONTIC.value, ModalLogicFamily.DYNAMIC.value),
        (ModalLogicFamily.DEONTIC.value, ModalLogicFamily.TEMPORAL.value),
        (ModalLogicFamily.TEMPORAL.value, ModalLogicFamily.ALETHIC.value),
        (ModalLogicFamily.TEMPORAL.value, ModalLogicFamily.DEONTIC.value),
        (ModalLogicFamily.DEONTIC.value, ModalLogicFamily.DEONTIC.value),
        (ModalLogicFamily.TEMPORAL.value, ModalLogicFamily.FRAME.value),
    )

    for predicted_family, target_family in policy_pairs:
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


def test_compiler_preserves_packet_003972_explicit_ambiguity_policy_margins() -> None:
    cases = (
        {
            "sample_id": "us-code-16-1133-1f4187c608723121",
            "predicted_family": ModalLogicFamily.DEONTIC.value,
            "target_family": ModalLogicFamily.TEMPORAL.value,
            "family_margin": -0.470715592574,
            "priority": 0.620715592574,
            "severity": "requires_rule",
            "expected_type": "adaptive_deontic_temporal_outvoted_margin_low",
        },
        {
            "sample_id": "us-code-40-9104-c896eeaba5bf2b02",
            "predicted_family": ModalLogicFamily.TEMPORAL.value,
            "target_family": ModalLogicFamily.ALETHIC.value,
            "family_margin": -0.322935175245,
            "priority": 0.472935175245,
            "severity": "requires_rule",
            "expected_type": "adaptive_temporal_alethic_outvoted_margin_low",
        },
        {
            "sample_id": "us-code-7-3501-7891b5d3cc4629fd",
            "predicted_family": ModalLogicFamily.DEONTIC.value,
            "target_family": ModalLogicFamily.DYNAMIC.value,
            "family_margin": -0.487766824091,
            "priority": 0.637766824091,
            "severity": "requires_rule",
            "expected_type": "adaptive_deontic_dynamic_outvoted_margin_low",
        },
        {
            "sample_id": "us-code-33-38-46031fe43d644995",
            "predicted_family": ModalLogicFamily.DEONTIC.value,
            "target_family": ModalLogicFamily.TEMPORAL.value,
            "family_margin": -0.271152464481,
            "priority": 0.421152464481,
            "severity": "requires_rule",
            "expected_type": "adaptive_deontic_temporal_outvoted_margin_low",
        },
        {
            "sample_id": "us-code-19-95-1c0972b677ad8c2b",
            "predicted_family": ModalLogicFamily.TEMPORAL.value,
            "target_family": ModalLogicFamily.FRAME.value,
            "family_margin": -0.335957920526,
            "priority": 0.485957920526,
            "severity": "requires_rule",
            "expected_type": "adaptive_temporal_frame_outvoted_margin_low",
        },
        {
            "sample_id": "us-code-44-2501.-f083822cf660d696",
            "predicted_family": ModalLogicFamily.DEONTIC.value,
            "target_family": ModalLogicFamily.DEONTIC.value,
            "family_margin": 0.083357765252,
            "priority": 0.066642234748,
            "severity": "review",
            "expected_type": "adaptive_deontic_deontic_contested_margin_low",
            "runner_up_family": ModalLogicFamily.TEMPORAL.value,
        },
        {
            "sample_id": "us-code-15-720i-78110a08c00c249c",
            "predicted_family": ModalLogicFamily.TEMPORAL.value,
            "target_family": ModalLogicFamily.FRAME.value,
            "family_margin": -0.345999657573,
            "priority": 0.495999657573,
            "severity": "requires_rule",
            "expected_type": "adaptive_temporal_frame_outvoted_margin_low",
        },
        {
            "sample_id": "us-code-16-4015-91931e3fa81fb2b7",
            "predicted_family": ModalLogicFamily.DEONTIC.value,
            "target_family": ModalLogicFamily.DEONTIC.value,
            "family_margin": 0.139605573286,
            "priority": 0.010394426714,
            "severity": "review",
            "expected_type": "adaptive_deontic_deontic_contested_margin_low",
            "runner_up_family": ModalLogicFamily.TEMPORAL.value,
        },
    )

    for case in cases:
        compiler = DeterministicModalCompiler(
            config=ModalCompilerConfig(parser_backend="spacy")
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

        def _mock_adaptive_family_ranking_from_logits(_encoding, *, ranking=ranking):
            return list(ranking)

        compiler._adaptive_family_ranking_from_logits = _mock_adaptive_family_ranking_from_logits  # type: ignore[method-assign]

        result = compiler.compile(
            "Within 30 days after June 1, 2030, the Secretary shall act as provided by statute.",
            document_id=f"compiler-ambiguity-packet-003972-{case['sample_id']}",
        )
        ambiguity = _adaptive_explicit_ambiguity_from_source(
            result,
            predicted_family=predicted_family,
            target_family=target_family,
            predicted_family_source="adaptive_logits",
        )
        assert ambiguity is not None, case["sample_id"]
        assert ambiguity.ambiguity_type == str(case["expected_type"])
        assert ambiguity.severity == str(case["severity"])
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
