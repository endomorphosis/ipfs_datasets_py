"""Packet-001127 regressions for compiler ambiguity-policy evidence margins."""

from __future__ import annotations

import os
from typing import Any, Dict, List

os.environ.setdefault("IPFS_DATASETS_PY_MINIMAL_IMPORTS", "1")
os.environ.setdefault("IPFS_DATASETS_AUTO_INSTALL", "false")
os.environ.setdefault("IPFS_KIT_AUTO_INSTALL_DEPS", "0")

import ipfs_datasets_py.logic.modal.compiler as modal_compiler_module  # noqa: E402
from ipfs_datasets_py.logic.modal.compiler import (  # noqa: E402
    DeterministicModalCompiler,
    ModalCompilerConfig,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_registry import (  # noqa: E402
    COMPILER_AMBIGUITY_PACKET_001127_FAMILY_PAIRS,
    ModalLogicFamily,
    compiler_refined_modal_family_cue_margin_buffer,
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


def _ranking_for_margin(
    *,
    predicted_family: str,
    target_family: str,
    family_margin: float,
) -> List[Dict[str, float | int | str]]:
    if predicted_family == target_family:
        predicted_share = (1.0 + family_margin) / 2.0
        runner_up_family = (
            ModalLogicFamily.TEMPORAL.value
            if predicted_family != ModalLogicFamily.TEMPORAL.value
            else ModalLogicFamily.DEONTIC.value
        )
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
            "logit": 1.2,
            "share_raw": target_share,
            "share": target_share,
            "source": "logit_softmax_fallback",
        },
    ]


def test_modal_registry_packet_001127_family_pairs_are_policy_supported() -> None:
    for predicted_family, target_family in COMPILER_AMBIGUITY_PACKET_001127_FAMILY_PAIRS:
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


def test_packet_001127_epistemic_conditional_pair_uses_refined_margin_buffer() -> None:
    assert (
        abs(
            compiler_refined_modal_family_cue_margin_buffer(
                ModalLogicFamily.EPISTEMIC.value,
                ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
            )
            - 0.0015
        )
        <= 1e-12
    )


def test_compiler_preserves_packet_001127_compiler_ambiguity_policy_evidence_margins(
    monkeypatch,
) -> None:
    cases = (
        {
            "sample_id": "us-code-22-2621-bddcc831999f0dee",
            "predicted_family": ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
            "target_family": ModalLogicFamily.FRAME.value,
            "family_margin": -0.682903579026,
            "priority": 0.832903579026,
        },
        {
            "sample_id": "us-code-42-7671h.-4f082320f15c1ec5",
            "predicted_family": ModalLogicFamily.DEONTIC.value,
            "target_family": ModalLogicFamily.TEMPORAL.value,
            "family_margin": -0.344906579748,
            "priority": 0.494906579748,
        },
        {
            "sample_id": "us-code-38-3512-537c9f716ffad460",
            "predicted_family": ModalLogicFamily.EPISTEMIC.value,
            "target_family": ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
            "family_margin": -0.877567404854,
            "priority": 1.027567404854,
        },
        {
            "sample_id": "us-code-26-6167-8727e692837bca73",
            "predicted_family": ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
            "target_family": ModalLogicFamily.DEONTIC.value,
            "family_margin": -0.117472919393,
            "priority": 0.267472919393,
        },
        {
            "sample_id": "us-code-16-757d-a3981e13c2ae5fd8",
            "predicted_family": ModalLogicFamily.TEMPORAL.value,
            "target_family": ModalLogicFamily.DEONTIC.value,
            "family_margin": -0.481044795431,
            "priority": 0.631044795431,
        },
        {
            "sample_id": "us-code-15-8203-760534e0fd6ee623",
            "predicted_family": ModalLogicFamily.TEMPORAL.value,
            "target_family": ModalLogicFamily.TEMPORAL.value,
            "family_margin": 0.0,
            "priority": 0.15,
        },
    )
    monkeypatch.setattr(
        modal_compiler_module,
        "ranked_modal_families",
        lambda _encoding: [],
    )
    monkeypatch.setattr(
        modal_compiler_module,
        "modal_ambiguity_signals",
        lambda _encoding: {},
    )

    for case in cases:
        compiler = DeterministicModalCompiler(
            config=ModalCompilerConfig(parser_backend="regex")
        )
        predicted_family = str(case["predicted_family"])
        target_family = str(case["target_family"])
        family_margin = float(case["family_margin"])
        expected_priority = float(case["priority"])
        expected_type = (
            f"adaptive_{predicted_family}_{target_family}_outvoted_margin_low"
        )
        ranking = _ranking_for_margin(
            predicted_family=predicted_family,
            target_family=target_family,
            family_margin=family_margin,
        )

        compiler._adaptive_family_ranking_from_logits = (  # type: ignore[method-assign]
            lambda _encoding, ranking_payload=ranking: list(ranking_payload)
        )

        result = compiler.compile(
            "As provided in section 3, the Secretary shall act by June 1, 2030.",
            document_id=f"compiler-ambiguity-packet-001127-{case['sample_id']}",
        )
        ambiguity = _adaptive_explicit_ambiguity_from_source(
            result,
            predicted_family=predicted_family,
            target_family=target_family,
            predicted_family_source="adaptive_logits_fallback",
        )
        assert ambiguity is not None, case["sample_id"]
        assert ambiguity.ambiguity_type == expected_type
        assert ambiguity.severity == "requires_rule"
        assert ambiguity.metadata.get("adaptive_margin_direction") == "outvoted"
        assert ambiguity.metadata.get("is_compiler_ambiguity_bundle_pair") is True
        assert ambiguity.metadata.get("ambiguity_policy_bundle") == "compiler_ambiguity"
        assert ambiguity.metadata.get("is_priority_policy_pair") is True
        assert ambiguity.metadata.get("is_compiler_required_policy_pair") is True
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
