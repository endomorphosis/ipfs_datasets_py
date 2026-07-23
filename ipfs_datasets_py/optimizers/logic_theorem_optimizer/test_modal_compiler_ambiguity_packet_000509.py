"""Packet-000509 regressions for temporal compiler ambiguity policy pairs."""

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
    compiler_refined_modal_family_cue_margin_buffer,
    is_compiler_ambiguity_policy_pair,
    is_compiler_required_adaptive_ambiguity_pair,
    is_priority_signal_free_adaptive_ambiguity_pair,
    supports_signal_free_adaptive_ambiguity_pair,
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


def test_packet_000509_temporal_policy_pairs_are_supported_across_compiler_ambiguity_policies() -> None:
    temporal_family = ModalLogicFamily.TEMPORAL.value
    target_families = (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ModalLogicFamily.DEONTIC.value,
        ModalLogicFamily.FRAME.value,
    )

    for target_family in target_families:
        assert is_priority_signal_free_adaptive_ambiguity_pair(
            temporal_family,
            target_family,
        )
        assert is_compiler_required_adaptive_ambiguity_pair(
            temporal_family,
            target_family,
        )
        assert is_compiler_ambiguity_policy_pair(
            temporal_family,
            target_family,
        )
        assert supports_signal_free_adaptive_ambiguity_pair(
            temporal_family,
            target_family,
        )
        assert (
            compiler_refined_modal_family_cue_margin_buffer(
                temporal_family,
                target_family,
            )
            > 0.0
        )


@pytest.mark.parametrize(
    (
        "sample_id",
        "target_family",
        "family_margin",
        "priority",
    ),
    (
        (
            "us-code-34-10721-5d8a8dcccaa6e6bc",
            ModalLogicFamily.DEONTIC.value,
            -0.68687061271,
            0.83687061271,
        ),
        (
            "us-code-2-130-b8497891c0fc291f",
            ModalLogicFamily.DEONTIC.value,
            -0.431473348286,
            0.581473348286,
        ),
        (
            "us-code-25-651-fe2f7195a298274b",
            ModalLogicFamily.FRAME.value,
            -0.081139848584,
            0.231139848584,
        ),
        (
            "us-code-2-126-96f413a3d3ed419f",
            ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
            -0.290136385068,
            0.440136385068,
        ),
    ),
)
def test_compiler_exposes_explicit_ambiguity_for_packet_000509_temporal_margins(
    monkeypatch: pytest.MonkeyPatch,
    sample_id: str,
    target_family: str,
    family_margin: float,
    priority: float,
) -> None:
    predicted_family = ModalLogicFamily.TEMPORAL.value
    expected_type = (
        f"adaptive_{predicted_family}_{target_family}_outvoted_margin_low"
    )

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
        document_id=f"compiler-ambiguity-packet-000509-{sample_id}",
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
    assert ambiguity.metadata.get("is_compiler_ambiguity_bundle_pair") is True
    assert ambiguity.metadata.get("ambiguity_policy_bundle") == "compiler_ambiguity"
    assert ambiguity.metadata.get("adaptive_policy_pair") == (
        f"{predicted_family}->{target_family}"
    )
    assert ambiguity.metadata.get("explicit_ambiguity_type") == expected_type
    assert (
        abs(float(ambiguity.metadata.get("family_margin_raw", 0.0)) - family_margin)
        <= 1e-12
    )
    assert abs(float(ambiguity.metadata.get("priority", 0.0)) - priority) <= 1e-12
    assert abs(float(ambiguity.metadata.get("adaptive_priority", 0.0)) - priority) <= (
        1e-12
    )
