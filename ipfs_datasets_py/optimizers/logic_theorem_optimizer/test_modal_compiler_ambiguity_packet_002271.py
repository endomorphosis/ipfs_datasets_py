"""Packet-002271 regressions for compiler ambiguity-policy evidence margins."""

from __future__ import annotations

import os
from typing import Any

os.environ.setdefault("IPFS_DATASETS_PY_MINIMAL_IMPORTS", "1")
os.environ.setdefault("IPFS_DATASETS_AUTO_INSTALL", "false")
os.environ.setdefault("IPFS_KIT_AUTO_INSTALL_DEPS", "0")

from ipfs_datasets_py.logic.modal.compiler import (  # noqa: E402
    DeterministicModalCompiler,
    ModalCompilerConfig,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_registry import (  # noqa: E402
    COMPILER_AMBIGUITY_PACKET_002271_FAMILY_PAIRS,
    ModalLogicFamily,
    compiler_ambiguity_policy_targets,
    is_compiler_ambiguity_policy_pair,
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
):
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
                "logit": 1.1,
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


def test_packet_002271_family_pairs_are_registered_for_explicit_ambiguity() -> None:
    for predicted_family, target_family in COMPILER_AMBIGUITY_PACKET_002271_FAMILY_PAIRS:
        assert is_compiler_ambiguity_policy_pair(predicted_family, target_family)
        assert target_family in compiler_ambiguity_policy_targets(predicted_family)
        assert supports_signal_free_adaptive_ambiguity_pair(
            predicted_family,
            target_family,
        )


def test_compiler_preserves_packet_002271_compiler_ambiguity_margins() -> None:
    evidence_cases = (
        {
            "sample_id": "us-code-16-824n-106bf88fbcd982a8",
            "predicted_family": ModalLogicFamily.FRAME.value,
            "target_family": ModalLogicFamily.FRAME.value,
            "family_margin": 0.101427472304,
            "priority": 0.048572527696,
            "severity": "review",
            "expected_type": "adaptive_frame_frame_contested_margin_low",
            "runner_up_family": ModalLogicFamily.TEMPORAL.value,
            "text": "Transfer of title; power development; authority under this chapter applies.",
        },
        {
            "sample_id": "us-code-16-81a-529677c6b36e9218",
            "predicted_family": ModalLogicFamily.FRAME.value,
            "target_family": ModalLogicFamily.DEONTIC.value,
            "family_margin": -0.616820170643,
            "priority": 0.766820170643,
            "severity": "requires_rule",
            "expected_type": "adaptive_frame_deontic_outvoted_margin_low",
            "text": "The Secretary shall administer this program under section 3 of this title.",
        },
        {
            "sample_id": "us-code-34-10307-3d13e651f2feb776",
            "predicted_family": ModalLogicFamily.DEONTIC.value,
            "target_family": ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
            "family_margin": -0.349781009517,
            "priority": 0.499781009517,
            "severity": "requires_rule",
            "expected_type": "adaptive_deontic_conditional_normative_outvoted_margin_low",
            "text": "The Secretary shall provide assistance if the applicant qualifies.",
        },
        {
            "sample_id": "us-code-42-300ff-3412beb4917e69a9",
            "predicted_family": ModalLogicFamily.TEMPORAL.value,
            "target_family": ModalLogicFamily.DEONTIC.value,
            "family_margin": -0.597370535952,
            "priority": 0.747370535952,
            "severity": "requires_rule",
            "expected_type": "adaptive_temporal_deontic_outvoted_margin_low",
            "text": "For fiscal year 2030, the Secretary shall make grants.",
        },
        {
            "sample_id": "us-code-31-5320-8d29c892844d49f9",
            "predicted_family": ModalLogicFamily.FRAME.value,
            "target_family": ModalLogicFamily.DOXASTIC.value,
            "family_margin": -0.54905495867,
            "priority": 0.69905495867,
            "severity": "requires_rule",
            "expected_type": "adaptive_frame_doxastic_outvoted_margin_low",
            "text": "A person with intent to defraud acts under the authority of this section.",
        },
        {
            "sample_id": "us-code-43-3005.-cd8c18d446d25239",
            "predicted_family": ModalLogicFamily.FRAME.value,
            "target_family": ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
            "family_margin": -0.361898612569,
            "priority": 0.511898612569,
            "severity": "requires_rule",
            "expected_type": "adaptive_frame_conditional_normative_outvoted_margin_low",
            "text": "As provided in section 3, this authority applies.",
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
            document_id=f"compiler-ambiguity-packet-002271-{case['sample_id']}",
        )
        ambiguity = _adaptive_explicit_ambiguity_from_source(
            result,
            predicted_family=predicted_family,
            target_family=target_family,
            predicted_family_source="adaptive_logits",
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
