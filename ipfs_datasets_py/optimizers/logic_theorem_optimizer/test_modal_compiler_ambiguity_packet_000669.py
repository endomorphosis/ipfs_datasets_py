"""Packet-000669 regressions for compiler adaptive ambiguity exposure."""

from __future__ import annotations

import os

os.environ.setdefault("IPFS_DATASETS_PY_MINIMAL_IMPORTS", "1")
os.environ.setdefault("IPFS_DATASETS_AUTO_INSTALL", "false")
os.environ.setdefault("IPFS_KIT_AUTO_INSTALL_DEPS", "0")

import pytest

import ipfs_datasets_py.logic.modal.compiler as modal_compiler_module  # noqa: E402
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


def _adaptive_ranking_for_margin(
    *,
    predicted_family: str,
    target_family: str,
    family_margin: float,
    runner_up_family: str | None = None,
):
    if predicted_family == target_family:
        resolved_runner_up = runner_up_family or ModalLogicFamily.TEMPORAL.value
        if resolved_runner_up == predicted_family:
            resolved_runner_up = ModalLogicFamily.FRAME.value
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
                "family": resolved_runner_up,
                "count": 0,
                "logit": 1.2,
                "share_raw": runner_up_share,
                "share": runner_up_share,
                "source": "logit_softmax_fallback",
            },
        ]

    predicted_share = max(0.5, abs(family_margin))
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


def test_compiler_exposes_packet_000669_explicit_adaptive_family_ambiguities(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cases = (
        {
            "sample_id": "us-code-40-15506-66374d96e275d2f7",
            "predicted_family": ModalLogicFamily.DEONTIC.value,
            "target_family": ModalLogicFamily.EPISTEMIC.value,
            "family_margin": -0.692636523859,
            "priority": 0.842636523859,
            "expected_type": "adaptive_deontic_epistemic_outvoted_margin_low",
            "expected_severity": "requires_rule",
        },
        {
            "sample_id": "us-code-42-2021j.-a4690d48700a116f",
            "predicted_family": ModalLogicFamily.DEONTIC.value,
            "target_family": ModalLogicFamily.TEMPORAL.value,
            "family_margin": -0.732647501733,
            "priority": 0.882647501733,
            "expected_type": "adaptive_deontic_temporal_outvoted_margin_low",
            "expected_severity": "requires_rule",
        },
        {
            "sample_id": "us-code-43-1544.-a54c76adf966c6dd",
            "predicted_family": ModalLogicFamily.TEMPORAL.value,
            "target_family": ModalLogicFamily.DEONTIC.value,
            "family_margin": -0.319329395492,
            "priority": 0.469329395492,
            "expected_type": "adaptive_temporal_deontic_outvoted_margin_low",
            "expected_severity": "requires_rule",
        },
        {
            "sample_id": "us-code-16-698a-1d3bc3559fc20a8f",
            "predicted_family": ModalLogicFamily.DEONTIC.value,
            "target_family": ModalLogicFamily.DEONTIC.value,
            "family_margin": 0.068363659684,
            "priority": 0.081636340316,
            "expected_type": "adaptive_deontic_deontic_contested_margin_low",
            "expected_severity": "review",
            "runner_up_family": ModalLogicFamily.TEMPORAL.value,
        },
    )

    for case in cases:
        compiler = DeterministicModalCompiler(
            config=ModalCompilerConfig(parser_backend="regex")
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

        def _mock_adaptive_family_ranking_from_logits(_encoding, *, ranking=ranking):
            return list(ranking)

        compiler._adaptive_family_ranking_from_logits = _mock_adaptive_family_ranking_from_logits  # type: ignore[method-assign]

        result = compiler.compile(
            "As provided in section 3, the Secretary shall act by June 1, 2030.",
            document_id=f"compiler-ambiguity-packet-000669-{case['sample_id']}",
        )
        ambiguity = _adaptive_explicit_ambiguity_from_source(
            result,
            predicted_family=predicted_family,
            target_family=target_family,
            predicted_family_source="adaptive_logits_fallback",
        )
        assert ambiguity is not None, case["sample_id"]
        assert ambiguity.ambiguity_type == case["expected_type"]
        assert ambiguity.severity == case["expected_severity"]
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
