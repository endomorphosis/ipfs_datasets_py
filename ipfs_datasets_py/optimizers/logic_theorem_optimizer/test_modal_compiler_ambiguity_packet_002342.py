"""Packet-002342 regressions for refined modal family cue-policy coverage."""

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
    COMPILER_REFINED_PACKET_002342_FAMILY_PAIRS,
    ModalLogicFamily,
    compiler_refined_modal_family_cue_margin_buffer,
    is_compiler_ambiguity_policy_pair,
    is_compiler_required_adaptive_ambiguity_pair,
    is_priority_signal_free_adaptive_ambiguity_pair,
    supports_signal_free_adaptive_ambiguity_pair,
)


def _adaptive_explicit_ambiguity(
    result: Any,
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
) -> List[Dict[str, float | int | str]]:
    predicted_share = 0.70
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
            "share_raw": predicted_share + family_margin,
            "share": predicted_share + family_margin,
            "source": "logit_softmax_fallback",
        },
    ]


def test_modal_registry_packet_002342_refined_pairs_are_supported() -> None:
    expected_pairs = (
        (ModalLogicFamily.CONDITIONAL_NORMATIVE.value, ModalLogicFamily.TEMPORAL.value),
        (ModalLogicFamily.DEONTIC.value, ModalLogicFamily.CONDITIONAL_NORMATIVE.value),
        (ModalLogicFamily.FRAME.value, ModalLogicFamily.CONDITIONAL_NORMATIVE.value),
        (ModalLogicFamily.FRAME.value, ModalLogicFamily.DEONTIC.value),
        (ModalLogicFamily.FRAME.value, ModalLogicFamily.DOXASTIC.value),
        (ModalLogicFamily.FRAME.value, ModalLogicFamily.EPISTEMIC.value),
    )

    assert COMPILER_REFINED_PACKET_002342_FAMILY_PAIRS == expected_pairs
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


def test_compiler_preserves_packet_002342_refined_family_policy_margins() -> None:
    evidence_cases = (
        {
            "sample_id": "us-code-42-300w-491151ad99c4802d",
            "predicted_family": ModalLogicFamily.FRAME.value,
            "target_family": ModalLogicFamily.EPISTEMIC.value,
            "family_margin": -0.391562521661,
            "expected_type": "adaptive_frame_epistemic_outvoted_margin_low",
        },
        {
            "sample_id": "us-code-36-152701-65df5670d2363d8e",
            "predicted_family": ModalLogicFamily.FRAME.value,
            "target_family": ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
            "family_margin": -0.790591170428,
            "expected_type": "adaptive_frame_conditional_normative_outvoted_margin_low",
        },
        {
            "sample_id": "us-code-22-3641-437cbd773f731bc9",
            "predicted_family": ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
            "target_family": ModalLogicFamily.TEMPORAL.value,
            "family_margin": -0.307927092019,
            "expected_type": "adaptive_conditional_normative_temporal_outvoted_margin_low",
        },
        {
            "sample_id": "us-code-22-2282-88c492933876610f",
            "predicted_family": ModalLogicFamily.FRAME.value,
            "target_family": ModalLogicFamily.DEONTIC.value,
            "family_margin": -0.544300137206,
            "expected_type": "adaptive_frame_deontic_outvoted_margin_low",
        },
        {
            "sample_id": "us-code-38-5121A-2501998d196b05b6",
            "predicted_family": ModalLogicFamily.DEONTIC.value,
            "target_family": ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
            "family_margin": -0.157814961331,
            "expected_type": "adaptive_deontic_conditional_normative_outvoted_margin_low",
        },
        {
            "sample_id": "us-code-48-2191.-bfdc57b607a664b4",
            "predicted_family": ModalLogicFamily.FRAME.value,
            "target_family": ModalLogicFamily.DOXASTIC.value,
            "family_margin": -0.930554827613,
            "expected_type": "adaptive_frame_doxastic_outvoted_margin_low",
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
            "Subject to this section, the Secretary shall determine findings within 30 days.",
            document_id=f"compiler-ambiguity-packet-002342-{case['sample_id']}",
        )
        ambiguity = _adaptive_explicit_ambiguity(
            result,
            predicted_family=predicted_family,
            target_family=target_family,
        )
        assert ambiguity is not None, case["sample_id"]
        assert ambiguity.ambiguity_type == str(case["expected_type"])
        assert ambiguity.metadata.get("is_compiler_ambiguity_bundle_pair") is True
        assert ambiguity.metadata.get("ambiguity_policy_bundle") == "compiler_ambiguity"
        assert ambiguity.metadata.get("is_compiler_required_policy_pair") is True
        assert ambiguity.metadata.get("is_priority_policy_pair") is True
        assert (
            abs(float(ambiguity.metadata.get("family_margin_raw", 0.0)) - family_margin)
            <= 1e-12
        )
