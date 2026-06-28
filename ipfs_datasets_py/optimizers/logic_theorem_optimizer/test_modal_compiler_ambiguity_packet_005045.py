"""Packet-005045 regressions for compiler ambiguity policy coverage."""

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
    COMPILER_AMBIGUITY_PACKET_005045_FAMILY_PAIRS,
    ModalLogicFamily,
    compiler_ambiguity_policy_targets,
    is_compiler_ambiguity_policy_pair,
    supports_signal_free_adaptive_ambiguity_pair,
)


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


def _adaptive_ranking_for_margin(
    *,
    predicted_family: str,
    target_family: str,
    family_margin: float,
    runner_up_family: str | None = None,
):
    if predicted_family == target_family:
        resolved_runner_up_family = runner_up_family or ModalLogicFamily.DEONTIC.value
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


def test_modal_registry_packet_005045_family_pairs_are_supported() -> None:
    for predicted_family, target_family in COMPILER_AMBIGUITY_PACKET_005045_FAMILY_PAIRS:
        assert is_compiler_ambiguity_policy_pair(predicted_family, target_family)
        assert target_family in compiler_ambiguity_policy_targets(predicted_family)
        assert supports_signal_free_adaptive_ambiguity_pair(
            predicted_family,
            target_family,
        )


def test_compiler_preserves_packet_005045_compiler_ambiguity_evidence_margins() -> None:
    cases = (
        {
            "sample_id": "us-code-26-684-ae8dac0ff39ff35c",
            "predicted_family": ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
            "target_family": ModalLogicFamily.DYNAMIC.value,
            "family_margin": -0.241945338059,
            "priority": 0.391945338059,
            "expected_type": "adaptive_conditional_normative_dynamic_outvoted_margin_low",
            "text": (
                "If a person files a return, the Secretary may prescribe the "
                "action to be taken under this section."
            ),
        },
        {
            "sample_id": "us-code-22-286r-a9d10b5f552f8c09",
            "predicted_family": ModalLogicFamily.FRAME.value,
            "target_family": ModalLogicFamily.DEONTIC.value,
            "family_margin": -0.957033577295,
            "priority": 1.107033577295,
            "expected_type": "adaptive_frame_deontic_outvoted_margin_low",
            "text": (
                "Under this subsection, the Secretary shall establish the "
                "terms and conditions for assistance."
            ),
        },
        {
            "sample_id": "us-code-28-254-149b58892f4445f8",
            "predicted_family": ModalLogicFamily.FRAME.value,
            "target_family": ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
            "family_margin": -0.697922526995,
            "priority": 0.847922526995,
            "expected_type": (
                "adaptive_frame_conditional_normative_outvoted_margin_low"
            ),
            "text": (
                "In the case of an assigned judge, the court shall proceed "
                "under the applicable rules."
            ),
        },
        {
            "sample_id": "us-code-43-391.-71f445203b1b61ac",
            "predicted_family": ModalLogicFamily.TEMPORAL.value,
            "target_family": ModalLogicFamily.TEMPORAL.value,
            "family_margin": 0.029972869945,
            "priority": 0.120027130055,
            "expected_type": "adaptive_temporal_temporal_contested_margin_low",
            "runner_up_family": ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
            "expected_effective_pair": "temporal->conditional_normative",
            "text": (
                "Within 30 days after submission, the Secretary shall publish "
                "the decision."
            ),
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
            str(case["text"]),
            document_id=f"compiler-ambiguity-packet-005045-{case['sample_id']}",
        )
        ambiguity = _adaptive_explicit_ambiguity_from_adaptive_logits(
            result,
            predicted_family=predicted_family,
            target_family=target_family,
        )

        assert ambiguity is not None, case["sample_id"]
        assert ambiguity.ambiguity_type == case["expected_type"]
        assert ambiguity.metadata.get("is_compiler_ambiguity_bundle_pair") is True
        assert ambiguity.metadata.get("ambiguity_policy_bundle") == "compiler_ambiguity"
        expected_effective_pair = str(
            case.get(
                "expected_effective_pair",
                f"{predicted_family}->{target_family}",
            )
        )
        assert ambiguity.metadata.get("effective_compiler_ambiguity_policy_pair") == (
            expected_effective_pair
        )
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
