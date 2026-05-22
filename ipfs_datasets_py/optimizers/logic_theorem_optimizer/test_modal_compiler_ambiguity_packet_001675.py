"""Regression coverage for compiler_ambiguity packet-001675 evidence margins."""

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


def test_compiler_preserves_packet_001675_compiler_ambiguity_policy_evidence_margins() -> None:
    cases = [
        {
            "sample_id": "us-code-10-9833-94c4a688f2dcb5c5",
            "predicted_family": ModalLogicFamily.FRAME.value,
            "target_family": ModalLogicFamily.FRAME.value,
            "expected_margin": 0.131176293653,
            "expected_priority": 0.018823706347,
            "runner_up_family": ModalLogicFamily.DEONTIC.value,
            "expected_type": "adaptive_frame_frame_contested_margin_low",
            "expected_severity": "review",
        },
        {
            "sample_id": "us-code-25-976-beaf15a054199393",
            "predicted_family": ModalLogicFamily.FRAME.value,
            "target_family": ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
            "expected_margin": -0.518545682385,
            "expected_priority": 0.668545682385,
            "expected_type": "adaptive_frame_conditional_normative_outvoted_margin_low",
            "expected_severity": "requires_rule",
        },
        {
            "sample_id": "us-code-42-4854b.-7f81f300a94a487a",
            "predicted_family": ModalLogicFamily.FRAME.value,
            "target_family": ModalLogicFamily.DEONTIC.value,
            "expected_margin": -0.859636584896,
            "expected_priority": 1.009636584896,
            "expected_type": "adaptive_frame_deontic_outvoted_margin_low",
            "expected_severity": "requires_rule",
        },
        {
            "sample_id": "us-code-4-102-a36dfe9d59745b40",
            "predicted_family": ModalLogicFamily.DEONTIC.value,
            "target_family": ModalLogicFamily.TEMPORAL.value,
            "expected_margin": -0.282845835886,
            "expected_priority": 0.432845835886,
            "expected_type": "adaptive_deontic_temporal_outvoted_margin_low",
            "expected_severity": "requires_rule",
        },
        {
            "sample_id": "us-code-18-434-73a8791832c2bd2a",
            "predicted_family": ModalLogicFamily.TEMPORAL.value,
            "target_family": ModalLogicFamily.TEMPORAL.value,
            "expected_margin": 0.086704107661,
            "expected_priority": 0.063295892339,
            "runner_up_family": ModalLogicFamily.DEONTIC.value,
            "expected_type": "adaptive_temporal_temporal_contested_margin_low",
            "expected_severity": "review",
        },
        {
            "sample_id": "us-code-15-3704b-1-ac0f33536b44f240",
            "predicted_family": ModalLogicFamily.TEMPORAL.value,
            "target_family": ModalLogicFamily.DEONTIC.value,
            "expected_margin": -0.242697072762,
            "expected_priority": 0.392697072762,
            "expected_type": "adaptive_temporal_deontic_outvoted_margin_low",
            "expected_severity": "requires_rule",
        },
        {
            "sample_id": "us-code-16-573-c69d5c806363843f",
            "predicted_family": ModalLogicFamily.FRAME.value,
            "target_family": ModalLogicFamily.FRAME.value,
            "expected_margin": 0.131176293653,
            "expected_priority": 0.018823706347,
            "runner_up_family": ModalLogicFamily.DEONTIC.value,
            "expected_type": "adaptive_frame_frame_contested_margin_low",
            "expected_severity": "review",
        },
        {
            "sample_id": "us-code-10-2666-f3d1e40e558d2682",
            "predicted_family": ModalLogicFamily.FRAME.value,
            "target_family": ModalLogicFamily.FRAME.value,
            "expected_margin": 0.131176293653,
            "expected_priority": 0.018823706347,
            "runner_up_family": ModalLogicFamily.DEONTIC.value,
            "expected_type": "adaptive_frame_frame_contested_margin_low",
            "expected_severity": "review",
        },
    ]

    for case in cases:
        compiler = DeterministicModalCompiler(
            config=ModalCompilerConfig(parser_backend="spacy")
        )
        predicted_family = str(case["predicted_family"])
        target_family = str(case["target_family"])
        expected_margin = float(case["expected_margin"])
        expected_priority = float(case["expected_priority"])

        if predicted_family == target_family:
            predicted_share = (1.0 + expected_margin) / 2.0
            runner_up_family = str(
                case.get("runner_up_family", ModalLogicFamily.DEONTIC.value)
            )
            if runner_up_family == predicted_family:
                runner_up_family = ModalLogicFamily.FRAME.value
            runner_up_share = predicted_share - expected_margin
            ranking = [
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
                    "logit": 1.2,
                    "share_raw": runner_up_share,
                    "share": runner_up_share,
                    "source": "logit_softmax_fallback",
                },
            ]
        else:
            predicted_share = 1.0
            target_share = predicted_share + expected_margin
            ranking = [
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

        def _mock_adaptive_family_ranking_from_logits(_encoding, *, ranking=ranking):
            return ranking

        compiler._adaptive_family_ranking_from_logits = _mock_adaptive_family_ranking_from_logits  # type: ignore[method-assign]

        result = compiler.compile(
            "As provided in section 3, the Secretary shall act by June 1, 2030.",
            document_id=f"compiler-ambiguity-packet-001675-{case['sample_id']}",
        )

        ambiguity = _adaptive_explicit_ambiguity_from_source(
            result,
            predicted_family=predicted_family,
            target_family=target_family,
            predicted_family_source="adaptive_logits",
        )
        assert ambiguity is not None, case["sample_id"]
        assert ambiguity.ambiguity_type == case["expected_type"]
        assert ambiguity.severity == case["expected_severity"]
        assert ambiguity.metadata.get("is_compiler_ambiguity_bundle_pair") is True
        assert ambiguity.metadata.get("ambiguity_policy_bundle") == "compiler_ambiguity"
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
