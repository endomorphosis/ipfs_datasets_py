"""Packet-000931 regressions for compiler adaptive ambiguity policy coverage."""

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
    compiler_refined_modal_family_cue_margin_buffer,
    is_compiler_ambiguity_policy_pair,
    supports_signal_free_adaptive_ambiguity_pair,
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
    if predicted_family == target_family:
        predicted_share = (1.0 + family_margin) / 2.0
        runner_up_share = predicted_share - family_margin
        runner_up_family = (
            ModalLogicFamily.TEMPORAL.value
            if predicted_family != ModalLogicFamily.TEMPORAL.value
            else ModalLogicFamily.DEONTIC.value
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


def test_packet_000931_family_pairs_use_refined_compiler_ambiguity_margin_buffer() -> None:
    policy_pairs = (
        (ModalLogicFamily.CONDITIONAL_NORMATIVE.value, ModalLogicFamily.DEONTIC.value),
        (ModalLogicFamily.CONDITIONAL_NORMATIVE.value, ModalLogicFamily.FRAME.value),
        (ModalLogicFamily.DEONTIC.value, ModalLogicFamily.CONDITIONAL_NORMATIVE.value),
        (ModalLogicFamily.DEONTIC.value, ModalLogicFamily.DEONTIC.value),
        (ModalLogicFamily.DEONTIC.value, ModalLogicFamily.TEMPORAL.value),
        (ModalLogicFamily.TEMPORAL.value, ModalLogicFamily.DEONTIC.value),
        (ModalLogicFamily.TEMPORAL.value, ModalLogicFamily.FRAME.value),
    )
    for predicted_family, target_family in policy_pairs:
        assert is_compiler_ambiguity_policy_pair(predicted_family, target_family)
        assert supports_signal_free_adaptive_ambiguity_pair(
            predicted_family,
            target_family,
        )
        assert (
            abs(
                compiler_refined_modal_family_cue_margin_buffer(
                    predicted_family,
                    target_family,
                )
                - 0.0015
            )
            <= 1e-12
        )


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
            "us-code-38-1963-480447f25c4486c0",
            ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
            ModalLogicFamily.FRAME.value,
            -0.543903632242,
            0.693903632242,
            "adaptive_conditional_normative_frame_outvoted_margin_low",
            "requires_rule",
        ),
        (
            "us-code-5-5949-dd3f26ccb60a94da",
            ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
            ModalLogicFamily.DEONTIC.value,
            -0.256919980329,
            0.406919980329,
            "adaptive_conditional_normative_deontic_outvoted_margin_low",
            "requires_rule",
        ),
        (
            "us-code-22-9689-9fe82fd8c5961c3e",
            ModalLogicFamily.DEONTIC.value,
            ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
            -0.02746129981,
            0.17746129981,
            "adaptive_deontic_conditional_normative_outvoted_margin_low",
            "requires_rule",
        ),
        (
            "us-code-20-1068a-fb1a67342132b5db",
            ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
            ModalLogicFamily.FRAME.value,
            -0.430630958619,
            0.580630958619,
            "adaptive_conditional_normative_frame_outvoted_margin_low",
            "requires_rule",
        ),
        (
            "us-code-7-80-215828b26515af23",
            ModalLogicFamily.DEONTIC.value,
            ModalLogicFamily.TEMPORAL.value,
            -0.227514404314,
            0.377514404314,
            "adaptive_deontic_temporal_outvoted_margin_low",
            "requires_rule",
        ),
        (
            "us-code-29-52-debd6bf49a917f44",
            ModalLogicFamily.DEONTIC.value,
            ModalLogicFamily.DEONTIC.value,
            0.135130635165,
            0.014869364835,
            "adaptive_deontic_deontic_contested_margin_low",
            "review",
        ),
        (
            "us-code-29-1150-8923dc27f9f7f3d6",
            ModalLogicFamily.TEMPORAL.value,
            ModalLogicFamily.DEONTIC.value,
            -0.204202581166,
            0.354202581166,
            "adaptive_temporal_deontic_outvoted_margin_low",
            "requires_rule",
        ),
        (
            "us-code-25-1300h-3-259e36c7e802ffdb",
            ModalLogicFamily.TEMPORAL.value,
            ModalLogicFamily.FRAME.value,
            -0.081139848584,
            0.231139848584,
            "adaptive_temporal_frame_outvoted_margin_low",
            "requires_rule",
        ),
    ),
)
def test_compiler_exposes_packet_000931_explicit_compiler_ambiguity(
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
    ranking = _ranking_for_margin(
        predicted_family=predicted_family,
        target_family=target_family,
        family_margin=family_margin,
    )
    compiler._adaptive_family_ranking_from_logits = (  # type: ignore[method-assign]
        lambda _encoding, ranking=ranking: list(ranking)
    )

    result = compiler.compile(
        "As provided in section 3, the Secretary shall act by June 1, 2030.",
        document_id=f"packet-000931-{sample_id}",
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
    assert (
        abs(float(ambiguity.metadata.get("priority", 0.0)) - priority)
        <= 1e-12
    )
    assert (
        abs(float(ambiguity.metadata.get("adaptive_priority", 0.0)) - priority)
        <= 1e-12
    )
    assert (
        abs(
            float(
                ambiguity.metadata.get(
                    "adaptive_effective_family_margin_threshold",
                    0.0,
                )
            )
            - 0.1515
        )
        <= 1e-12
    )
    assert (
        abs(float(ambiguity.metadata.get("adaptive_pair_margin_buffer", 0.0)) - 0.0015)
        <= 1e-12
    )
