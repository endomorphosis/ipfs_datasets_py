"""Packet-001865 regressions for compiler adaptive ambiguity policy coverage."""

from __future__ import annotations

import os
from typing import Dict, List

import pytest

os.environ.setdefault("IPFS_DATASETS_PY_MINIMAL_IMPORTS", "1")
os.environ.setdefault("IPFS_DATASETS_AUTO_INSTALL", "false")
os.environ.setdefault("IPFS_KIT_AUTO_INSTALL_DEPS", "0")

import ipfs_datasets_py.logic.modal.compiler as modal_compiler_module  # noqa: E402
from ipfs_datasets_py.logic.modal.compiler import (  # noqa: E402
    DeterministicModalCompiler,
    ModalCompilationAmbiguity,
    ModalCompilationResult,
    ModalCompilerConfig,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_registry import (  # noqa: E402
    ModalLogicFamily,
    is_compiler_ambiguity_policy_pair,
    is_compiler_required_adaptive_ambiguity_pair,
)


def _adaptive_explicit_ambiguity_from_source(
    result: ModalCompilationResult,
    *,
    predicted_family: str,
    target_family: str,
    predicted_family_source: str,
) -> ModalCompilationAmbiguity | None:
    matches = [
        ambiguity
        for ambiguity in result.ambiguities
        if ambiguity.ambiguity_type.startswith("adaptive_")
        and ambiguity.ambiguity_type != "adaptive_family_margin_low"
        and ambiguity.metadata.get("predicted_family") == predicted_family
        and ambiguity.metadata.get("target_family") == target_family
        and ambiguity.metadata.get("adaptive_predicted_family_source")
        == predicted_family_source
    ]
    return matches[0] if matches else None


def _ranking_for_margin(
    *,
    predicted_family: str,
    target_family: str,
    family_margin: float,
) -> List[Dict[str, float | int | str]]:
    predicted_share = max(0.75, abs(family_margin) + 0.1)
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


def test_modal_registry_packet_001865_pairs_are_compiler_policy_pairs() -> None:
    policy_pairs = (
        (ModalLogicFamily.DEONTIC.value, ModalLogicFamily.CONDITIONAL_NORMATIVE.value),
        (ModalLogicFamily.TEMPORAL.value, ModalLogicFamily.DEONTIC.value),
        (ModalLogicFamily.TEMPORAL.value, ModalLogicFamily.FRAME.value),
    )
    for predicted_family, target_family in policy_pairs:
        assert is_compiler_ambiguity_policy_pair(predicted_family, target_family)
        assert is_compiler_required_adaptive_ambiguity_pair(
            predicted_family,
            target_family,
        )


@pytest.mark.parametrize(
    (
        "sample_id",
        "predicted_family",
        "target_family",
        "family_margin",
        "priority",
        "expected_type",
    ),
    (
        (
            "us-code-2-5606-0280fb6382160f04",
            ModalLogicFamily.DEONTIC.value,
            ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
            -0.546819025444,
            0.696819025444,
            "adaptive_deontic_conditional_normative_outvoted_margin_low",
        ),
        (
            "us-code-5-4121-4246110a3f504a2f",
            ModalLogicFamily.TEMPORAL.value,
            ModalLogicFamily.DEONTIC.value,
            -0.21580077643,
            0.36580077643,
            "adaptive_temporal_deontic_outvoted_margin_low",
        ),
        (
            "us-code-38-530-cbdcc465efb01c46",
            ModalLogicFamily.TEMPORAL.value,
            ModalLogicFamily.FRAME.value,
            -0.711031930223,
            0.861031930223,
            "adaptive_temporal_frame_outvoted_margin_low",
        ),
    ),
)
def test_compiler_exposes_packet_001865_explicit_compiler_ambiguity(
    monkeypatch,
    sample_id: str,
    predicted_family: str,
    target_family: str,
    family_margin: float,
    priority: float,
    expected_type: str,
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
    ranking = _ranking_for_margin(
        predicted_family=predicted_family,
        target_family=target_family,
        family_margin=family_margin,
    )
    compiler._adaptive_family_ranking_from_logits = (  # type: ignore[method-assign]
        lambda _encoding, ranking=ranking: list(ranking)
    )

    result = compiler.compile(
        "Within 30 days as provided by statute, the Secretary shall act.",
        document_id=f"packet-001865-{sample_id}",
    )
    ambiguity = _adaptive_explicit_ambiguity_from_source(
        result,
        predicted_family=predicted_family,
        target_family=target_family,
        predicted_family_source="adaptive_logits_fallback",
    )
    assert ambiguity is not None, sample_id
    assert ambiguity.ambiguity_type == expected_type
    assert ambiguity.severity == "requires_rule"
    assert ambiguity.metadata.get("explicit_ambiguity_type") == expected_type
    assert ambiguity.metadata.get("is_explicit_adaptive_ambiguity") is True
    assert ambiguity.metadata.get("is_compiler_ambiguity_bundle_pair") is True
    assert ambiguity.metadata.get("ambiguity_policy_bundle") == "compiler_ambiguity"
    assert ambiguity.metadata.get("is_compiler_required_policy_pair") is True
    assert (
        ambiguity.metadata.get("effective_compiler_ambiguity_policy_pair")
        == f"{predicted_family}->{target_family}"
    )
    assert (
        abs(float(ambiguity.metadata.get("family_margin_raw", 0.0)) - family_margin)
        <= 1e-12
    )
    assert abs(float(ambiguity.metadata.get("priority", 0.0)) - priority) <= 1e-12
    assert abs(float(ambiguity.metadata.get("adaptive_priority", 0.0)) - priority) <= (
        1e-12
    )
