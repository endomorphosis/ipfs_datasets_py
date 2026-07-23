"""Packet-002859 regressions for compiler ambiguity family-pair evidence."""

from __future__ import annotations

import os
from typing import Any, Dict, List

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
                "logit": 1.1,
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
            "us-code-42-300t-a12137ca04a25790",
            ModalLogicFamily.TEMPORAL.value,
            ModalLogicFamily.DEONTIC.value,
            -0.451594083711,
            0.601594083711,
            "adaptive_temporal_deontic_outvoted_margin_low",
            "requires_rule",
        ),
        (
            "us-code-39-2402-c4e8eecc315471eb",
            ModalLogicFamily.FRAME.value,
            ModalLogicFamily.DEONTIC.value,
            -0.338076145856,
            0.488076145856,
            "adaptive_frame_deontic_outvoted_margin_low",
            "requires_rule",
        ),
        (
            "us-code-10-2551-9d8aba2a96c24595",
            ModalLogicFamily.FRAME.value,
            ModalLogicFamily.TEMPORAL.value,
            -0.259977551422,
            0.409977551422,
            "adaptive_frame_temporal_outvoted_margin_low",
            "requires_rule",
        ),
        (
            "us-code-12-4744-e1e1006dbde6a5f7",
            ModalLogicFamily.DEONTIC.value,
            ModalLogicFamily.DEONTIC.value,
            0.055552164994,
            0.094447835006,
            "adaptive_deontic_deontic_contested_margin_low",
            "review",
        ),
    ),
)
def test_compiler_preserves_packet_002859_family_pair_margins(
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
    ranking = _adaptive_ranking_for_margin(
        predicted_family=predicted_family,
        target_family=target_family,
        family_margin=family_margin,
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
    compiler._adaptive_family_ranking_from_logits = (  # type: ignore[method-assign]
        lambda _encoding, ranking_payload=ranking: list(ranking_payload)
    )

    result = compiler.compile(
        "As provided in section 3, the Secretary shall act by June 1, 2030.",
        document_id=f"compiler-ambiguity-packet-002859-{sample_id}",
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
    assert (
        abs(float(ambiguity.metadata.get("family_margin_raw", 0.0)) - family_margin)
        <= 1e-12
    )
    assert abs(float(ambiguity.metadata.get("priority", 0.0)) - priority) <= 1e-12
    assert (
        abs(float(ambiguity.metadata.get("adaptive_priority", 0.0)) - priority)
        <= 1e-12
    )
