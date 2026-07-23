"""Packet-003275 regressions for compiler ambiguity policy evidence margins."""

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
    COMPILER_AMBIGUITY_PACKET_003275_FAMILY_PAIRS,
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


def test_modal_registry_packet_003275_family_pairs_are_supported() -> None:
    for predicted_family, target_family in COMPILER_AMBIGUITY_PACKET_003275_FAMILY_PAIRS:
        assert is_compiler_ambiguity_policy_pair(predicted_family, target_family)
        assert target_family in compiler_ambiguity_policy_targets(predicted_family)
        assert supports_signal_free_adaptive_ambiguity_pair(
            predicted_family,
            target_family,
        )


def test_compiler_preserves_packet_003275_compiler_ambiguity_evidence_margins() -> None:
    evidence_cases = (
        {
            "sample_id": "us-code-36-80106-cb7ae5515f33774c",
            "predicted_family": ModalLogicFamily.TEMPORAL.value,
            "target_family": ModalLogicFamily.DEONTIC.value,
            "family_margin": -0.401737275787,
            "priority": 0.551737275787,
            "severity": "requires_rule",
            "expected_type": "adaptive_temporal_deontic_outvoted_margin_low",
            "expected_effective_threshold": 0.1515,
            "expected_pair_buffer": 0.0015,
            "text": (
                "Within 30 days after enactment, the Secretary shall provide "
                "the required notice under this section."
            ),
        },
        {
            "sample_id": "us-code-48-1398.-ba1f68c351e01688",
            "predicted_family": ModalLogicFamily.TEMPORAL.value,
            "target_family": ModalLogicFamily.FRAME.value,
            "family_margin": -0.056860653465,
            "priority": 0.206860653465,
            "severity": "requires_rule",
            "expected_type": "adaptive_temporal_frame_outvoted_margin_low",
            "expected_effective_threshold": 0.1515,
            "expected_pair_buffer": 0.0015,
            "text": (
                "Within the district boundaries, the Secretary shall act under "
                "this section."
            ),
        },
        {
            "sample_id": "us-code-42-1396r-8ca1c32fe259da1a",
            "predicted_family": ModalLogicFamily.EPISTEMIC.value,
            "target_family": ModalLogicFamily.DEONTIC.value,
            "family_margin": -0.999993243246,
            "priority": 1.149993243246,
            "severity": "requires_rule",
            "expected_type": "adaptive_epistemic_deontic_outvoted_margin_low",
            "expected_effective_threshold": 0.15,
            "expected_pair_buffer": 0.0,
            "text": (
                "The agency may determine whether payment is available under "
                "this section."
            ),
        },
        {
            "sample_id": "us-code-2-46f-1-b790635993472104",
            "predicted_family": ModalLogicFamily.TEMPORAL.value,
            "target_family": ModalLogicFamily.TEMPORAL.value,
            "family_margin": 0.022902795066,
            "priority": 0.127097204934,
            "severity": "review",
            "expected_type": "adaptive_temporal_temporal_contested_margin_low",
            "expected_effective_threshold": 0.1515,
            "expected_pair_buffer": 0.0015,
            "runner_up_family": ModalLogicFamily.DEONTIC.value,
            "text": (
                "Within 90 days after submission, the Secretary shall publish "
                "the report."
            ),
        },
    )

    for case in evidence_cases:
        compiler = DeterministicModalCompiler(
            config=ModalCompilerConfig(parser_backend="spacy")
        )
        predicted_family = str(case["predicted_family"])
        target_family = str(case["target_family"])
        family_margin = float(case["family_margin"])
        expected_priority = float(case["priority"])
        expected_effective_threshold = float(case["expected_effective_threshold"])
        expected_pair_buffer = float(case["expected_pair_buffer"])
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
            document_id=f"compiler-ambiguity-packet-003275-{case['sample_id']}",
        )
        ambiguity = _adaptive_explicit_ambiguity_from_adaptive_logits(
            result,
            predicted_family=predicted_family,
            target_family=target_family,
        )
        assert ambiguity is not None, case["sample_id"]
        assert ambiguity.ambiguity_type == case["expected_type"]
        assert ambiguity.severity == case["severity"]
        assert ambiguity.metadata.get("is_compiler_ambiguity_bundle_pair") is True
        assert ambiguity.metadata.get("ambiguity_policy_bundle") == "compiler_ambiguity"
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
        assert (
            abs(
                float(
                    ambiguity.metadata.get(
                        "adaptive_effective_family_margin_threshold",
                        0.0,
                    )
                )
                - expected_effective_threshold
            )
            <= 1e-12
        )
        assert (
            abs(
                float(ambiguity.metadata.get("adaptive_pair_margin_buffer", 0.0))
                - expected_pair_buffer
            )
            <= 1e-12
        )
