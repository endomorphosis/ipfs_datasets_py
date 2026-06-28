"""Packet-001104 regressions for compiler ambiguity evidence margins."""

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
    COMPILER_AMBIGUITY_PACKET_001104_FAMILY_PAIRS,
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
):
    if predicted_family == target_family:
        runner_up_family = ModalLogicFamily.DEONTIC.value
        if runner_up_family == predicted_family:
            runner_up_family = ModalLogicFamily.FRAME.value
        predicted_share = (1.0 + family_margin) / 2.0
        target_share = predicted_share - family_margin
        target_family = runner_up_family
    else:
        predicted_share = 0.7
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


def _adaptive_explicit_ambiguity_from_adaptive_logits(
    result,
    *,
    predicted_family: str,
    target_family: str,
):
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


def test_modal_registry_packet_001104_family_pairs_are_supported() -> None:
    for predicted_family, target_family in COMPILER_AMBIGUITY_PACKET_001104_FAMILY_PAIRS:
        assert is_compiler_ambiguity_policy_pair(predicted_family, target_family)
        assert target_family in compiler_ambiguity_policy_targets(predicted_family)
        assert supports_signal_free_adaptive_ambiguity_pair(
            predicted_family,
            target_family,
        )


def test_compiler_preserves_packet_001104_compiler_ambiguity_evidence_margins() -> None:
    evidence_cases = (
        {
            "sample_id": "us-code-20-3922-c155da50ac2aa5ec",
            "predicted_family": ModalLogicFamily.FRAME.value,
            "target_family": ModalLogicFamily.DEONTIC.value,
            "family_margin": -0.666988601718,
            "expected_type": "adaptive_frame_deontic_outvoted_margin_low",
        },
        {
            "sample_id": "us-code-7-1012-edf3305162377a2a",
            "predicted_family": ModalLogicFamily.FRAME.value,
            "target_family": ModalLogicFamily.TEMPORAL.value,
            "family_margin": -0.268116371696,
            "expected_type": "adaptive_frame_temporal_outvoted_margin_low",
        },
        {
            "sample_id": "us-code-12-2147-a344e811e0974a4c",
            "predicted_family": ModalLogicFamily.TEMPORAL.value,
            "target_family": ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
            "family_margin": -0.210062852337,
            "expected_type": "adaptive_temporal_conditional_normative_outvoted_margin_low",
        },
        {
            "sample_id": "us-code-20-1070c-1-e88d40ae81dcd708",
            "predicted_family": ModalLogicFamily.FRAME.value,
            "target_family": ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
            "family_margin": -0.556507800051,
            "expected_type": "adaptive_frame_conditional_normative_outvoted_margin_low",
        },
        {
            "sample_id": "us-code-5-5706a-175cddb2f1f3180f",
            "predicted_family": ModalLogicFamily.DEONTIC.value,
            "target_family": ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
            "family_margin": -0.357337312839,
            "expected_type": "adaptive_deontic_conditional_normative_outvoted_margin_low",
        },
        {
            "sample_id": "us-code-22-937-53570d85375ba9d8",
            "predicted_family": ModalLogicFamily.TEMPORAL.value,
            "target_family": ModalLogicFamily.DYNAMIC.value,
            "family_margin": -0.27052136268,
            "expected_type": "adaptive_temporal_dynamic_outvoted_margin_low",
        },
    )

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
        )

        def _mock_adaptive_family_ranking_from_logits(_encoding, *, ranking=ranking):
            return list(ranking)

        compiler._adaptive_family_ranking_from_logits = _mock_adaptive_family_ranking_from_logits  # type: ignore[method-assign]

        result = compiler.compile(
            (
                "Within 30 days the Secretary shall issue the required report "
                "subject to this section."
            ),
            document_id=f"compiler-ambiguity-packet-001104-{case['sample_id']}",
        )
        ambiguity = _adaptive_explicit_ambiguity_from_adaptive_logits(
            result,
            predicted_family=predicted_family,
            target_family=target_family,
        )
        expected_priority = abs(family_margin) + 0.15

        assert ambiguity is not None, case["sample_id"]
        assert ambiguity.ambiguity_type == case["expected_type"]
        assert ambiguity.severity == "requires_rule"
        assert ambiguity.metadata.get("is_compiler_ambiguity_bundle_pair") is True
        assert ambiguity.metadata.get("ambiguity_policy_bundle") == "compiler_ambiguity"
        assert ambiguity.metadata.get("adaptive_margin_direction") == "outvoted"
        assert ambiguity.metadata.get("is_explicit_adaptive_ambiguity") is True
        assert (
            abs(float(ambiguity.metadata.get("family_margin_raw", 0.0)) - family_margin)
            <= 1e-12
        )
        assert (
            abs(float(ambiguity.metadata.get("priority", 0.0)) - expected_priority)
            <= 1e-12
        )
