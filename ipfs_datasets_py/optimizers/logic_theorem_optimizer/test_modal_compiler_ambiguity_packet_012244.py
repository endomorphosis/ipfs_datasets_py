"""Packet-012244 regressions for compiler ambiguity policy margins."""

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
    COMPILER_AMBIGUITY_PACKET_012244_FAMILY_PAIRS,
    ModalLogicFamily,
    compiler_ambiguity_policy_targets,
    is_compiler_ambiguity_policy_pair,
    supports_signal_free_adaptive_ambiguity_pair,
)


def _adaptive_explicit_ambiguity_from_logits(
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


def test_modal_registry_packet_012244_family_pairs_are_supported() -> None:
    expected_pairs = (
        (
            ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
            ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ),
        (
            ModalLogicFamily.DEONTIC.value,
            ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ),
        (
            ModalLogicFamily.DEONTIC.value,
            ModalLogicFamily.DEONTIC.value,
        ),
        (
            ModalLogicFamily.FRAME.value,
            ModalLogicFamily.DEONTIC.value,
        ),
        (
            ModalLogicFamily.TEMPORAL.value,
            ModalLogicFamily.DEONTIC.value,
        ),
        (
            ModalLogicFamily.TEMPORAL.value,
            ModalLogicFamily.TEMPORAL.value,
        ),
    )
    assert COMPILER_AMBIGUITY_PACKET_012244_FAMILY_PAIRS == expected_pairs
    for predicted_family, target_family in expected_pairs:
        assert is_compiler_ambiguity_policy_pair(predicted_family, target_family)
        assert target_family in compiler_ambiguity_policy_targets(predicted_family)
        assert supports_signal_free_adaptive_ambiguity_pair(
            predicted_family,
            target_family,
        )


def test_compiler_exposes_packet_012244_explicit_adaptive_ambiguities() -> None:
    evidence_cases = (
        {
            "sample_id": "us-code-2-1534-97599ca2edf9c41f",
            "predicted_family": ModalLogicFamily.FRAME.value,
            "target_family": ModalLogicFamily.DEONTIC.value,
            "family_margin": -0.337296111773,
            "expected_type": "adaptive_frame_deontic_outvoted_margin_low",
            "severity": "requires_rule",
            "text": (
                "The committee has authority under this section and shall submit "
                "a report."
            ),
        },
        {
            "sample_id": "us-code-22-4083a-d3f4aee930be80fb",
            "predicted_family": ModalLogicFamily.TEMPORAL.value,
            "target_family": ModalLogicFamily.TEMPORAL.value,
            "family_margin": 0.110736027385,
            "expected_type": "adaptive_temporal_temporal_contested_margin_low",
            "severity": "review",
            "runner_up_family": ModalLogicFamily.DEONTIC.value,
            "text": "Within 30 days, the Secretary shall provide notice.",
        },
        {
            "sample_id": "us-code-26-1397-4b1d16d852e5fabe",
            "predicted_family": ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
            "target_family": ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
            "family_margin": 0.136101013634,
            "expected_type": (
                "adaptive_conditional_normative_conditional_normative_"
                "contested_margin_low"
            ),
            "severity": "review",
            "runner_up_family": ModalLogicFamily.DEONTIC.value,
            "text": (
                "If the application is complete, the Secretary shall approve it "
                "subject to this section."
            ),
        },
        {
            "sample_id": "us-code-7-7425-da5f781347ad7465",
            "predicted_family": ModalLogicFamily.DEONTIC.value,
            "target_family": ModalLogicFamily.DEONTIC.value,
            "family_margin": 0.092411474027,
            "expected_type": "adaptive_deontic_deontic_contested_margin_low",
            "severity": "review",
            "runner_up_family": ModalLogicFamily.TEMPORAL.value,
            "text": "The Secretary shall issue regulations within 180 days.",
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
            document_id=f"compiler-ambiguity-packet-012244-{case['sample_id']}",
        )
        ambiguity = _adaptive_explicit_ambiguity_from_logits(
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
        expected_priority = (
            abs(family_margin) + 0.15
            if family_margin <= 0.0
            else 0.15 - family_margin
        )
        assert (
            abs(float(ambiguity.metadata.get("priority", 0.0)) - expected_priority)
            <= 1e-12
        )
