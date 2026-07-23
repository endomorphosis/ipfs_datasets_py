"""Regression coverage for packet-004771 adaptive compiler ambiguity margins."""

from __future__ import annotations

import os
from typing import Dict, List

import pytest

import ipfs_datasets_py.logic.modal.compiler as modal_compiler_module
from ipfs_datasets_py.logic.modal.compiler import (
    DeterministicModalCompiler,
    ModalCompilationResult,
    ModalCompilerConfig,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_registry import (
    ModalLogicFamily,
)

os.environ.setdefault("IPFS_DATASETS_PY_MINIMAL_IMPORTS", "1")
os.environ.setdefault("IPFS_DATASETS_AUTO_INSTALL", "false")
os.environ.setdefault("IPFS_KIT_AUTO_INSTALL_DEPS", "0")


def _adaptive_explicit_ambiguity_from_source(
    result: ModalCompilationResult,
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
    if predicted_family == target_family:
        predicted_share = (1.0 + family_margin) / 2.0
        runner_up_share = predicted_share - family_margin
        runner_up_family = (
            ModalLogicFamily.DEONTIC.value
            if predicted_family != ModalLogicFamily.DEONTIC.value
            else ModalLogicFamily.TEMPORAL.value
        )
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


@pytest.mark.parametrize(
    (
        "sample_id",
        "predicted_family",
        "target_family",
        "family_margin",
        "priority",
        "expected_type",
        "expected_severity",
    ),
    (
        (
            "us-code-2-61k-8d8f1f15dc7f1291",
            ModalLogicFamily.TEMPORAL.value,
            ModalLogicFamily.DEONTIC.value,
            -0.214706242679,
            0.364706242679,
            "adaptive_temporal_deontic_outvoted_margin_low",
            "requires_rule",
        ),
        (
            "us-code-26-3131-ac6b744db1d972d3",
            ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
            ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
            0.003581739814,
            0.146418260186,
            "adaptive_conditional_normative_conditional_normative_contested_margin_low",
            "review",
        ),
        (
            "us-code-7-3508-cdda5e8da016da61",
            ModalLogicFamily.TEMPORAL.value,
            ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
            -0.327803207468,
            0.477803207468,
            "adaptive_temporal_conditional_normative_outvoted_margin_low",
            "requires_rule",
        ),
    ),
)
def test_compiler_preserves_packet_004771_adaptive_ambiguity_policy_margins(
    monkeypatch: pytest.MonkeyPatch,
    sample_id: str,
    predicted_family: str,
    target_family: str,
    family_margin: float,
    priority: float,
    expected_type: str,
    expected_severity: str,
) -> None:
    compiler = DeterministicModalCompiler(
        config=ModalCompilerConfig(parser_backend="regex")
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
    ranking = _adaptive_ranking_for_margin(
        predicted_family=predicted_family,
        target_family=target_family,
        family_margin=family_margin,
    )
    compiler._adaptive_family_ranking_from_logits = (  # type: ignore[method-assign]
        lambda _encoding, ranking=ranking: list(ranking)
    )

    result = compiler.compile(
        "As provided in section 3, the Secretary shall act by June 1, 2030.",
        document_id=f"compiler-ambiguity-packet-004771-{sample_id}",
    )
    ambiguity = _adaptive_explicit_ambiguity_from_source(
        result,
        predicted_family=predicted_family,
        target_family=target_family,
        predicted_family_source="adaptive_logits_fallback",
    )

    assert ambiguity is not None, sample_id
    assert ambiguity.ambiguity_type == expected_type
    assert ambiguity.severity == expected_severity
    assert ambiguity.metadata.get("is_compiler_ambiguity_bundle_pair") is True
    assert ambiguity.metadata.get("ambiguity_policy_bundle") == "compiler_ambiguity"
    assert ambiguity.metadata.get("explicit_ambiguity_type") == expected_type
    assert (
        abs(float(ambiguity.metadata.get("family_margin_raw", 0.0)) - family_margin)
        <= 1e-12
    )
    assert abs(float(ambiguity.metadata.get("priority", 0.0)) - priority) <= 1e-12
    assert abs(float(ambiguity.metadata.get("adaptive_priority", 0.0)) - priority) <= (
        1e-12
    )
