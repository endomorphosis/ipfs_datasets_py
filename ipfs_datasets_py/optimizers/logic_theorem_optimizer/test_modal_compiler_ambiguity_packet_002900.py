"""Packet-002900 regressions for modal compiler ambiguity policy pairs."""

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
    COMPILER_AMBIGUITY_PACKET_002900_FAMILY_PAIRS,
    ModalLogicFamily,
    compiler_ambiguity_policy_targets,
    is_compiler_ambiguity_policy_pair,
    supports_signal_free_adaptive_ambiguity_pair,
)


def _adaptive_explicit_ambiguity(
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
        resolved_runner_up_family = runner_up_family or ModalLogicFamily.FRAME.value
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


def test_modal_registry_packet_002900_family_pairs_are_supported() -> None:
    for predicted_family, target_family in COMPILER_AMBIGUITY_PACKET_002900_FAMILY_PAIRS:
        assert is_compiler_ambiguity_policy_pair(predicted_family, target_family)
        assert target_family in compiler_ambiguity_policy_targets(predicted_family)
        assert supports_signal_free_adaptive_ambiguity_pair(
            predicted_family,
            target_family,
        )


def test_compiler_preserves_packet_002900_explicit_ambiguity_policy_pairs() -> None:
    evidence_cases = (
        {
            "sample_id": "us-code-42-227a-a16b62fa71839117",
            "predicted_family": ModalLogicFamily.FRAME.value,
            "target_family": ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
            "family_margin": -0.950590416189,
            "expected_type": "adaptive_frame_conditional_normative_outvoted_margin_low",
            "severity": "requires_rule",
            "text": (
                "Editorial notes describe appropriations available for research "
                "grants under this section if the Service approves the grant."
            ),
        },
        {
            "sample_id": "us-code-10-713-830ede108c3e3f19",
            "predicted_family": ModalLogicFamily.FRAME.value,
            "target_family": ModalLogicFamily.DEONTIC.value,
            "family_margin": -0.824658344854,
            "expected_type": "adaptive_frame_deontic_outvoted_margin_low",
            "severity": "requires_rule",
            "text": (
                "Under this section, the Secretary shall assign officers to "
                "perform the required duty."
            ),
        },
        {
            "sample_id": "us-code-25-3601-5d8804c2cf479098",
            "predicted_family": ModalLogicFamily.FRAME.value,
            "target_family": ModalLogicFamily.EPISTEMIC.value,
            "family_margin": -0.160449242336,
            "expected_type": "adaptive_frame_epistemic_outvoted_margin_low",
            "severity": "requires_rule",
            "text": (
                "The findings under this chapter determine whether the program "
                "may be continued."
            ),
        },
        {
            "sample_id": "us-code-22-3408-8f50b1253e6d2124",
            "predicted_family": ModalLogicFamily.TEMPORAL.value,
            "target_family": ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
            "family_margin": -0.248328610178,
            "expected_type": "adaptive_temporal_conditional_normative_outvoted_margin_low",
            "severity": "requires_rule",
            "text": (
                "After the agreement is submitted, assistance may be furnished "
                "if the President determines that conditions are met."
            ),
        },
        {
            "sample_id": "us-code-36-150511-23be63be9c3cb86a",
            "predicted_family": ModalLogicFamily.DEONTIC.value,
            "target_family": ModalLogicFamily.FRAME.value,
            "family_margin": -0.414312804762,
            "expected_type": "adaptive_deontic_frame_outvoted_margin_low",
            "severity": "requires_rule",
            "text": (
                "The corporation shall maintain records under this chapter and "
                "within the purposes of its charter."
            ),
        },
        {
            "sample_id": "us-code-42-6953-284ec1c5c8efab9c",
            "predicted_family": ModalLogicFamily.DEONTIC.value,
            "target_family": ModalLogicFamily.DEONTIC.value,
            "family_margin": 0.087015109937,
            "expected_type": "adaptive_deontic_deontic_contested_margin_low",
            "severity": "review",
            "runner_up_family": ModalLogicFamily.FRAME.value,
            "text": (
                "The Administrator shall promulgate regulations under this "
                "section for the program."
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
            document_id=f"compiler-ambiguity-packet-002900-{case['sample_id']}",
        )
        ambiguity = _adaptive_explicit_ambiguity(
            result,
            predicted_family=predicted_family,
            target_family=target_family,
        )
        assert ambiguity is not None, case["sample_id"]
        assert ambiguity.ambiguity_type == case["expected_type"]
        assert ambiguity.severity == case["severity"]
        assert ambiguity.metadata.get("is_compiler_ambiguity_bundle_pair") is True
        assert ambiguity.metadata.get("ambiguity_policy_bundle") == "compiler_ambiguity"
        assert ambiguity.metadata.get("is_explicit_adaptive_ambiguity") is True
        assert (
            abs(float(ambiguity.metadata.get("family_margin_raw", 0.0)) - family_margin)
            <= 1e-12
        )
