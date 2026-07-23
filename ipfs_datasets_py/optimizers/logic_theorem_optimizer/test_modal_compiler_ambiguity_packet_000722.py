"""Packet-000722 regressions for compiler ambiguity policy evidence margins."""

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
    ModalLogicFamily,
    compiler_refined_modal_family_cue_margin_buffer,
    is_compiler_ambiguity_policy_pair,
    is_compiler_required_adaptive_ambiguity_pair,
    is_priority_signal_free_adaptive_ambiguity_pair,
    supports_signal_free_adaptive_ambiguity_pair,
)


def _adaptive_explicit_ambiguity_from_source(
    result,
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


def test_modal_registry_packet_000722_policy_pairs_are_supported_and_buffered() -> None:
    expected_pairs = (
        (ModalLogicFamily.DEONTIC.value, ModalLogicFamily.TEMPORAL.value),
        (ModalLogicFamily.TEMPORAL.value, ModalLogicFamily.DEONTIC.value),
        (ModalLogicFamily.TEMPORAL.value, ModalLogicFamily.TEMPORAL.value),
        (ModalLogicFamily.DEONTIC.value, ModalLogicFamily.DEONTIC.value),
        (ModalLogicFamily.DEONTIC.value, ModalLogicFamily.FRAME.value),
        (
            ModalLogicFamily.TEMPORAL.value,
            ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ),
    )

    for predicted_family, target_family in expected_pairs:
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
        assert (
            compiler_refined_modal_family_cue_margin_buffer(
                predicted_family,
                target_family,
            )
            > 0.0
        )


def test_compiler_preserves_packet_000722_compiler_ambiguity_policy_margins() -> None:
    evidence_cases = (
        {
            "sample_id": "us-code-22-7903-0836bce5d89214fa",
            "predicted_family": ModalLogicFamily.TEMPORAL.value,
            "target_family": ModalLogicFamily.DEONTIC.value,
            "family_margin": -0.359274472987,
            "priority": 0.509274472987,
            "severity": "requires_rule",
            "expected_type": "adaptive_temporal_deontic_outvoted_margin_low",
        },
        {
            "sample_id": "us-code-42-98.-807a4baa07a51d0b",
            "predicted_family": ModalLogicFamily.TEMPORAL.value,
            "target_family": ModalLogicFamily.DEONTIC.value,
            "family_margin": -0.251611829385,
            "priority": 0.401611829385,
            "severity": "requires_rule",
            "expected_type": "adaptive_temporal_deontic_outvoted_margin_low",
        },
        {
            "sample_id": "us-code-43-647.-4d9189c681737416",
            "predicted_family": ModalLogicFamily.DEONTIC.value,
            "target_family": ModalLogicFamily.TEMPORAL.value,
            "family_margin": -0.716439040474,
            "priority": 0.866439040474,
            "severity": "requires_rule",
            "expected_type": "adaptive_deontic_temporal_outvoted_margin_low",
        },
        {
            "sample_id": "us-code-10-2308-ec903b77f86b8ae0",
            "predicted_family": ModalLogicFamily.TEMPORAL.value,
            "target_family": ModalLogicFamily.TEMPORAL.value,
            "family_margin": 0.052573259414,
            "priority": 0.097426740586,
            "severity": "review",
            "runner_up_family": ModalLogicFamily.DEONTIC.value,
            "expected_type": "adaptive_temporal_temporal_contested_margin_low",
        },
        {
            "sample_id": "us-code-7-2021-099996bd698b517d",
            "predicted_family": ModalLogicFamily.DEONTIC.value,
            "target_family": ModalLogicFamily.DEONTIC.value,
            "family_margin": 0.110551986063,
            "priority": 0.039448013937,
            "severity": "review",
            "runner_up_family": ModalLogicFamily.TEMPORAL.value,
            "expected_type": "adaptive_deontic_deontic_contested_margin_low",
        },
        {
            "sample_id": "us-code-48-1.-0ade975a44829a3e",
            "predicted_family": ModalLogicFamily.TEMPORAL.value,
            "target_family": ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
            "family_margin": -0.423783921958,
            "priority": 0.573783921958,
            "severity": "requires_rule",
            "expected_type": "adaptive_temporal_conditional_normative_outvoted_margin_low",
        },
        {
            "sample_id": "us-code-25-1685-c5fe5eded7473b6e",
            "predicted_family": ModalLogicFamily.DEONTIC.value,
            "target_family": ModalLogicFamily.FRAME.value,
            "family_margin": -0.759908166211,
            "priority": 0.909908166211,
            "severity": "requires_rule",
            "expected_type": "adaptive_deontic_frame_outvoted_margin_low",
        },
        {
            "sample_id": "us-code-42-300t-ad6146acc5f2edfa",
            "predicted_family": ModalLogicFamily.TEMPORAL.value,
            "target_family": ModalLogicFamily.DEONTIC.value,
            "family_margin": -0.112632129384,
            "priority": 0.262632129384,
            "severity": "requires_rule",
            "expected_type": "adaptive_temporal_deontic_outvoted_margin_low",
        },
    )

    expected_effective_threshold = 0.1515
    expected_pair_margin_buffer = 0.0015

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
            "As provided in section 3, the Secretary shall act by June 1, 2030.",
            document_id=f"compiler-ambiguity-packet-000722-{case['sample_id']}",
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
        assert ambiguity.metadata.get("is_explicit_adaptive_ambiguity") is True
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
                float(
                    ambiguity.metadata.get(
                        "adaptive_pair_margin_buffer",
                        0.0,
                    )
                )
                - expected_pair_margin_buffer
            )
            <= 1e-12
        )
