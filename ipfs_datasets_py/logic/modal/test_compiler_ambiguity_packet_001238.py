"""Regression coverage for packet-001238 compiler ambiguity policy pairs."""

from __future__ import annotations

import os
from typing import Any, Dict, List

os.environ.setdefault("IPFS_DATASETS_PY_MINIMAL_IMPORTS", "1")
os.environ.setdefault("IPFS_DATASETS_AUTO_INSTALL", "false")
os.environ.setdefault("IPFS_KIT_AUTO_INSTALL_DEPS", "0")

from ipfs_datasets_py.logic.modal.compiler import DeterministicModalCompiler, ModalCompilerConfig  # noqa: E402
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_registry import (  # noqa: E402
    COMPILER_AMBIGUITY_PACKET_001238_FAMILY_PAIRS,
    ModalLogicFamily,
    compiler_ambiguity_policy_targets,
    is_compiler_ambiguity_policy_pair,
    supports_signal_free_adaptive_ambiguity_pair,
)


def _adaptive_ranking_for_margin(
    *,
    predicted_family: str,
    target_family: str,
    family_margin: float,
    runner_up_family: str | None = None,
) -> List[Dict[str, Any]]:
    if predicted_family == target_family:
        resolved_runner_up_family = runner_up_family or ModalLogicFamily.DEONTIC.value
        if resolved_runner_up_family == predicted_family:
            resolved_runner_up_family = ModalLogicFamily.TEMPORAL.value
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

    predicted_share = 0.7
    target_share = predicted_share + family_margin
    if target_share < 0.0:
        predicted_share = min(0.99, abs(family_margin) + 0.05)
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


def _adaptive_explicit_ambiguity(result, *, predicted_family: str, target_family: str):
    for ambiguity in result.ambiguities:
        if not ambiguity.ambiguity_type.startswith("adaptive_"):
            continue
        if ambiguity.ambiguity_type == "adaptive_family_margin_low":
            continue
        if ambiguity.metadata.get("adaptive_predicted_family_source") != "adaptive_logits":
            continue
        if ambiguity.metadata.get("predicted_family") != predicted_family:
            continue
        if ambiguity.metadata.get("target_family") != target_family:
            continue
        return ambiguity
    return None


def test_modal_registry_packet_001238_family_pairs_are_supported() -> None:
    expected_pairs = {
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
            ModalLogicFamily.FRAME.value,
        ),
        (
            ModalLogicFamily.FRAME.value,
            ModalLogicFamily.TEMPORAL.value,
        ),
        (
            ModalLogicFamily.TEMPORAL.value,
            ModalLogicFamily.DEONTIC.value,
        ),
    }
    assert set(COMPILER_AMBIGUITY_PACKET_001238_FAMILY_PAIRS) == expected_pairs
    for predicted_family, target_family in expected_pairs:
        assert is_compiler_ambiguity_policy_pair(predicted_family, target_family)
        assert target_family in compiler_ambiguity_policy_targets(predicted_family)
        assert supports_signal_free_adaptive_ambiguity_pair(
            predicted_family,
            target_family,
        )


def test_compiler_preserves_packet_001238_explicit_ambiguity_margins() -> None:
    evidence_cases = (
        {
            "sample_id": "us-code-42-3786.-4e3f79669ae8058e",
            "predicted_family": ModalLogicFamily.FRAME.value,
            "target_family": ModalLogicFamily.TEMPORAL.value,
            "family_margin": -0.285631509352,
            "expected_type": "adaptive_frame_temporal_outvoted_margin_low",
        },
        {
            "sample_id": "us-code-21-456-0dc97b45ef6baa3c",
            "predicted_family": ModalLogicFamily.FRAME.value,
            "target_family": ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
            "family_margin": -0.216526239987,
            "expected_type": "adaptive_frame_conditional_normative_outvoted_margin_low",
        },
        {
            "sample_id": "us-code-10-2213-2c23744a34d4a65d",
            "predicted_family": ModalLogicFamily.FRAME.value,
            "target_family": ModalLogicFamily.TEMPORAL.value,
            "family_margin": -0.99465029821,
            "expected_type": "adaptive_frame_temporal_outvoted_margin_low",
        },
        {
            "sample_id": "us-code-42-1453.-88dbfe1720d66d2d",
            "predicted_family": ModalLogicFamily.FRAME.value,
            "target_family": ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
            "family_margin": -0.820784755605,
            "expected_type": "adaptive_frame_conditional_normative_outvoted_margin_low",
        },
        {
            "sample_id": "us-code-38-2107-597e0efa0888d75b",
            "predicted_family": ModalLogicFamily.TEMPORAL.value,
            "target_family": ModalLogicFamily.DEONTIC.value,
            "family_margin": -0.050264152687,
            "expected_type": "adaptive_temporal_deontic_outvoted_margin_low",
        },
        {
            "sample_id": "us-code-30-201a-e2516e8bfce3be94",
            "predicted_family": ModalLogicFamily.FRAME.value,
            "target_family": ModalLogicFamily.FRAME.value,
            "family_margin": 0.076420958448,
            "expected_type": "adaptive_frame_frame_contested_margin_low",
            "runner_up_family": ModalLogicFamily.TEMPORAL.value,
        },
        {
            "sample_id": "us-code-12-2249-905781f14e90e407",
            "predicted_family": ModalLogicFamily.DEONTIC.value,
            "target_family": ModalLogicFamily.DEONTIC.value,
            "family_margin": 0.139878221149,
            "expected_type": "adaptive_deontic_deontic_contested_margin_low",
            "runner_up_family": ModalLogicFamily.TEMPORAL.value,
        },
        {
            "sample_id": "us-code-38-3697-06ce5d6d0e3f7161",
            "predicted_family": ModalLogicFamily.FRAME.value,
            "target_family": ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
            "family_margin": -0.352566243751,
            "expected_type": "adaptive_frame_conditional_normative_outvoted_margin_low",
        },
    )

    threshold = 0.15
    for case in evidence_cases:
        compiler = DeterministicModalCompiler(
            config=ModalCompilerConfig(parser_backend="spacy")
        )
        predicted_family = str(case["predicted_family"])
        target_family = str(case["target_family"])
        family_margin = float(case["family_margin"])
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
            "The Secretary shall coordinate under this section within 30 days.",
            document_id=f"compiler-ambiguity-packet-001238-{case['sample_id']}",
        )
        ambiguity = _adaptive_explicit_ambiguity(
            result,
            predicted_family=predicted_family,
            target_family=target_family,
        )
        assert ambiguity is not None, case["sample_id"]
        assert ambiguity.ambiguity_type == case["expected_type"]
        assert ambiguity.severity == (
            "requires_rule" if family_margin < 0.0 else "review"
        )
        assert ambiguity.metadata.get("is_compiler_ambiguity_bundle_pair") is True
        assert ambiguity.metadata.get("ambiguity_policy_bundle") == "compiler_ambiguity"
        assert ambiguity.metadata.get("is_explicit_adaptive_ambiguity") is True
        assert (
            abs(float(ambiguity.metadata.get("family_margin_raw", 0.0)) - family_margin)
            <= 1e-12
        )

        expected_priority = (
            abs(family_margin) + threshold
            if family_margin <= 0.0
            else threshold - family_margin
        )
        assert (
            abs(float(ambiguity.metadata.get("priority", 0.0)) - expected_priority)
            <= 1e-12
        )
