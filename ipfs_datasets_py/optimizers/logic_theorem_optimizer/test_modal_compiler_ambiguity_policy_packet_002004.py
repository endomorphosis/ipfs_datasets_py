"""Regression coverage for packet-002004 compiler ambiguity policy evidence."""

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


def test_compiler_preserves_packet_002004_compiler_ambiguity_policy_margins() -> None:
    cases = [
        {
            "sample_id": "us-code-36-153512-d48103dbacb343e6",
            "predicted_family": ModalLogicFamily.DEONTIC.value,
            "target_family": ModalLogicFamily.TEMPORAL.value,
            "family_margin": -0.027148002684,
            "priority": 0.177148002684,
            "expected_type": "adaptive_deontic_temporal_outvoted_margin_low",
            "expected_severity": "requires_rule",
            "text": "The Secretary shall issue an annual report.",
            "runner_up_family": ModalLogicFamily.FRAME.value,
        },
        {
            "sample_id": "us-code-46-107.-c0ea6da00c23409e",
            "predicted_family": ModalLogicFamily.FRAME.value,
            "target_family": ModalLogicFamily.TEMPORAL.value,
            "family_margin": -0.605183972302,
            "priority": 0.755183972302,
            "expected_type": "adaptive_frame_temporal_outvoted_margin_low",
            "expected_severity": "requires_rule",
            "text": "As provided in section 3, this authority applies.",
            "runner_up_family": ModalLogicFamily.DEONTIC.value,
        },
        {
            "sample_id": "us-code-43-390h-7e77bcac7cd1851d",
            "predicted_family": ModalLogicFamily.DEONTIC.value,
            "target_family": ModalLogicFamily.DEONTIC.value,
            "family_margin": 0.09447114298,
            "priority": 0.05552885702,
            "expected_type": "adaptive_deontic_deontic_contested_margin_low",
            "expected_severity": "review",
            "text": "The Secretary shall submit the report.",
            "runner_up_family": ModalLogicFamily.TEMPORAL.value,
        },
        {
            "sample_id": "us-code-42-10268.-f4138775b10ab61f",
            "predicted_family": ModalLogicFamily.FRAME.value,
            "target_family": ModalLogicFamily.DEONTIC.value,
            "family_margin": -0.844981424991,
            "priority": 0.994981424991,
            "expected_type": "adaptive_frame_deontic_outvoted_margin_low",
            "expected_severity": "requires_rule",
            "text": "As provided in section 3, this authority applies.",
            "runner_up_family": ModalLogicFamily.TEMPORAL.value,
        },
        {
            "sample_id": "us-code-43-1861.-3a96d35aadfeec5b",
            "predicted_family": ModalLogicFamily.TEMPORAL.value,
            "target_family": ModalLogicFamily.DEONTIC.value,
            "family_margin": -0.303502804835,
            "priority": 0.453502804835,
            "expected_type": "adaptive_temporal_deontic_outvoted_margin_low",
            "expected_severity": "requires_rule",
            "text": "Within 30 days after June 1, 2030, publication occurs.",
            "runner_up_family": ModalLogicFamily.FRAME.value,
        },
        {
            "sample_id": "us-code-15-672-901b03284af85912",
            "predicted_family": ModalLogicFamily.TEMPORAL.value,
            "target_family": ModalLogicFamily.DEONTIC.value,
            "family_margin": -0.547780514781,
            "priority": 0.697780514781,
            "expected_type": "adaptive_temporal_deontic_outvoted_margin_low",
            "expected_severity": "requires_rule",
            "text": "Within 30 days after June 1, 2030, publication occurs.",
            "runner_up_family": ModalLogicFamily.FRAME.value,
        },
        {
            "sample_id": "us-code-19-1503a-78ddaedd664a3952",
            "predicted_family": ModalLogicFamily.TEMPORAL.value,
            "target_family": ModalLogicFamily.TEMPORAL.value,
            "family_margin": 0.076103710962,
            "priority": 0.073896289038,
            "expected_type": "adaptive_temporal_temporal_contested_margin_low",
            "expected_severity": "review",
            "text": "Within 30 days after June 1, 2030, publication occurs.",
            "runner_up_family": ModalLogicFamily.DEONTIC.value,
        },
        {
            "sample_id": "us-code-16-470l-38efb2806bedd11a",
            "predicted_family": ModalLogicFamily.FRAME.value,
            "target_family": ModalLogicFamily.FRAME.value,
            "family_margin": 0.131176293653,
            "priority": 0.018823706347,
            "expected_type": "adaptive_frame_frame_contested_margin_low",
            "expected_severity": "review",
            "text": "As provided in section 3, this authority applies.",
            "runner_up_family": ModalLogicFamily.TEMPORAL.value,
        },
    ]

    for case in cases:
        compiler = DeterministicModalCompiler(
            config=ModalCompilerConfig(parser_backend="spacy")
        )
        predicted_family = str(case["predicted_family"])
        target_family = str(case["target_family"])
        expected_margin = float(case["family_margin"])
        expected_priority = float(case["priority"])
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
            str(case["text"]),
            document_id=f"compiler-ambiguity-packet-002004-{case['sample_id']}",
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
