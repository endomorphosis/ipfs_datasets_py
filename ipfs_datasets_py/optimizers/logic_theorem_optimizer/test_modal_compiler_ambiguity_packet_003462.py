"""Packet-003462 regressions for compiler ambiguity policy evidence margins."""

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
    is_compiler_ambiguity_policy_pair,
    is_compiler_required_adaptive_ambiguity_pair,
    is_priority_signal_free_adaptive_ambiguity_pair,
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
) -> List[Dict[str, float | int | str]]:
    predicted_share = max(0.7, abs(family_margin) + 0.1)
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
        {
            "family": ModalLogicFamily.ALETHIC.value,
            "count": 0,
            "logit": 0.8,
            "share_raw": max(0.0, min(predicted_share, target_share) / 2.0),
            "share": max(0.0, min(predicted_share, target_share) / 2.0),
            "source": "logit_softmax_fallback",
        },
    ]


def test_modal_registry_packet_003462_family_pairs_are_supported_by_ambiguity_policy() -> None:
    policy_pairs = (
        (
            ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
            ModalLogicFamily.TEMPORAL.value,
        ),
        (
            ModalLogicFamily.DEONTIC.value,
            ModalLogicFamily.FRAME.value,
        ),
        (
            ModalLogicFamily.DEONTIC.value,
            ModalLogicFamily.TEMPORAL.value,
        ),
        (
            ModalLogicFamily.TEMPORAL.value,
            ModalLogicFamily.DEONTIC.value,
        ),
    )

    for predicted_family, target_family in policy_pairs:
        assert is_priority_signal_free_adaptive_ambiguity_pair(
            predicted_family,
            target_family,
        )
        assert is_compiler_required_adaptive_ambiguity_pair(
            predicted_family,
            target_family,
        )
        assert is_compiler_ambiguity_policy_pair(
            predicted_family,
            target_family,
        )
        assert supports_signal_free_adaptive_ambiguity_pair(
            predicted_family,
            target_family,
        )


def test_compiler_preserves_packet_003462_compiler_ambiguity_policy_evidence_margins() -> None:
    cases = (
        {
            "sample_id": "us-code-50-4322.-17f59a0eaa130956",
            "predicted_family": ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
            "target_family": ModalLogicFamily.TEMPORAL.value,
            "family_margin": -0.330476546328,
            "priority": 0.480476546328,
            "expected_type": "adaptive_conditional_normative_temporal_outvoted_margin_low",
        },
        {
            "sample_id": "us-code-42-1437bbb-d5809f20e8f79e29",
            "predicted_family": ModalLogicFamily.DEONTIC.value,
            "target_family": ModalLogicFamily.FRAME.value,
            "family_margin": -0.861954516768,
            "priority": 1.011954516768,
            "expected_type": "adaptive_deontic_frame_outvoted_margin_low",
        },
        {
            "sample_id": "us-code-16-539-561759b886decfc2",
            "predicted_family": ModalLogicFamily.DEONTIC.value,
            "target_family": ModalLogicFamily.TEMPORAL.value,
            "family_margin": -0.501385954482,
            "priority": 0.651385954482,
            "expected_type": "adaptive_deontic_temporal_outvoted_margin_low",
        },
        {
            "sample_id": "us-code-20-128-5d737a0dda2a1bf4",
            "predicted_family": ModalLogicFamily.TEMPORAL.value,
            "target_family": ModalLogicFamily.DEONTIC.value,
            "family_margin": -0.05050266875,
            "priority": 0.20050266875,
            "expected_type": "adaptive_temporal_deontic_outvoted_margin_low",
        },
    )

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
        )

        def _mock_adaptive_family_ranking_from_logits(
            _encoding,
            *,
            ranking_payload: List[Dict[str, float | int | str]] = ranking,
        ) -> List[Dict[str, float | int | str]]:
            return list(ranking_payload)

        compiler._adaptive_family_ranking_from_logits = _mock_adaptive_family_ranking_from_logits  # type: ignore[method-assign]

        result = compiler.compile(
            "Within 30 days the Secretary shall submit the report as provided by statute.",
            document_id=f"compiler-ambiguity-packet-003462-{case['sample_id']}",
        )

        ambiguity = _adaptive_explicit_ambiguity_from_source(
            result,
            predicted_family=predicted_family,
            target_family=target_family,
            predicted_family_source="adaptive_logits",
        )
        assert ambiguity is not None, str(case["sample_id"])
        assert ambiguity.ambiguity_type == str(case["expected_type"])
        assert ambiguity.severity == "requires_rule"
        assert ambiguity.metadata.get("is_compiler_ambiguity_bundle_pair") is True
        assert ambiguity.metadata.get("ambiguity_policy_bundle") == "compiler_ambiguity"
        assert ambiguity.metadata.get("is_priority_policy_pair") is True
        assert ambiguity.metadata.get("is_compiler_required_policy_pair") is True
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
