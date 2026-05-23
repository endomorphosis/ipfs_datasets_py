"""Regression tests for compiler ambiguity-policy evidence margins."""

from __future__ import annotations

from typing import Dict, List

import pytest

import ipfs_datasets_py.logic.modal.compiler as modal_compiler_module
from ipfs_datasets_py.logic.modal.compiler import (
    DeterministicModalCompiler,
    ModalCompilationAmbiguity,
    ModalCompilationResult,
    ModalCompilerConfig,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_registry import (
    ModalLogicFamily,
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
            "us-code-49-15502.-9f3ef967ecce1630",
            ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
            ModalLogicFamily.FRAME.value,
            -0.602400028887,
            0.752400028887,
            "adaptive_conditional_normative_frame_outvoted_margin_low",
            "requires_rule",
        ),
        (
            "us-code-16-760-7-1441960b588ac99e",
            ModalLogicFamily.TEMPORAL.value,
            ModalLogicFamily.DEONTIC.value,
            -0.586281164377,
            0.736281164377,
            "adaptive_temporal_deontic_outvoted_margin_low",
            "requires_rule",
        ),
        (
            "us-code-16-460iii-6-97574e080dcdcc2a",
            ModalLogicFamily.TEMPORAL.value,
            ModalLogicFamily.DEONTIC.value,
            -0.107959072818,
            0.257959072818,
            "adaptive_temporal_deontic_outvoted_margin_low",
            "requires_rule",
        ),
        (
            "us-code-16-460rrr-8-f841a83ef8f27ee6",
            ModalLogicFamily.TEMPORAL.value,
            ModalLogicFamily.DEONTIC.value,
            0.0,
            0.15,
            "adaptive_temporal_deontic_outvoted_margin_low",
            "requires_rule",
        ),
        (
            "us-code-5-5724c-8165c23b776ad4bd",
            ModalLogicFamily.TEMPORAL.value,
            ModalLogicFamily.DEONTIC.value,
            -0.016996490756,
            0.166996490756,
            "adaptive_temporal_deontic_outvoted_margin_low",
            "requires_rule",
        ),
        (
            "us-code-12-4807-618e116ed94d7678",
            ModalLogicFamily.DEONTIC.value,
            ModalLogicFamily.DEONTIC.value,
            0.022357819692,
            0.127642180308,
            "adaptive_deontic_deontic_contested_margin_low",
            "review",
        ),
        (
            "us-code-33-2253-b932190643180aef",
            ModalLogicFamily.DEONTIC.value,
            ModalLogicFamily.DEONTIC.value,
            0.095449918721,
            0.054550081279,
            "adaptive_deontic_deontic_contested_margin_low",
            "review",
        ),
        (
            "us-code-47-391.-e07c8342b5c7ad6d",
            ModalLogicFamily.TEMPORAL.value,
            ModalLogicFamily.DEONTIC.value,
            -0.735107724462,
            0.885107724462,
            "adaptive_temporal_deontic_outvoted_margin_low",
            "requires_rule",
        ),
        (
            "us-code-16-6513-ca39207d6768fcd5",
            ModalLogicFamily.DEONTIC.value,
            ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
            -0.727069472068,
            0.877069472068,
            "adaptive_deontic_conditional_normative_outvoted_margin_low",
            "requires_rule",
        ),
    ),
)
def test_compiler_exposes_explicit_ambiguity_for_packet_004467_and_004398_adaptive_margins(
    monkeypatch,
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
        document_id=f"packet-004467-{sample_id}",
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


def test_compiler_refined_pair_margin_buffer_surfaces_near_threshold_conditional_self_ambiguity(
    monkeypatch,
) -> None:
@pytest.mark.parametrize(
    ("sample_id", "target_family", "family_margin"),
    (
        (
            "us-code-16-3a-1e9742717085c4f1",
            ModalLogicFamily.FRAME.value,
            -0.294900910575,
        ),
        (
            "us-code-2-60m-96e0c4c96dfba1a9",
            ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
            -0.486729191195,
        ),
        (
            "us-code-5-112-2eb8bb8974f5068b",
            ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
            -0.679169211961,
        ),
    ),
)
def test_compiler_exposes_explicit_ambiguity_for_packet_002421_temporal_policy_pairs(
    monkeypatch,
    sample_id: str,
    target_family: str,
    family_margin: float,
) -> None:
    predicted_family = ModalLogicFamily.TEMPORAL.value
    expected_type = (
        f"adaptive_{predicted_family}_{target_family}_outvoted_margin_low"
    )
    expected_priority = abs(family_margin) + 0.15

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
            "us-code-20-1140r-f6cf10136b00f1b0",
            ModalLogicFamily.TEMPORAL.value,
            ModalLogicFamily.DEONTIC.value,
            0.0,
            0.15,
            "adaptive_temporal_deontic_outvoted_margin_low",
            "requires_rule",
        ),
        (
            "us-code-22-1094-6c1b2ce673aca247",
            ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
            ModalLogicFamily.TEMPORAL.value,
            -0.069012267961,
            0.219012267961,
            "adaptive_conditional_normative_temporal_outvoted_margin_low",
            "requires_rule",
        ),
        (
            "us-code-22-286ss-aacd07c15feae297",
            ModalLogicFamily.DEONTIC.value,
            ModalLogicFamily.DEONTIC.value,
            0.023466061084,
            0.126533938916,
            "adaptive_deontic_deontic_contested_margin_low",
            "review",
        ),
    ),
)
def test_compiler_exposes_explicit_ambiguity_for_packet_002568_adaptive_margins(
    ),
    (
        (
            "us-code-10-9432-57b4dded06dd2a68",
            ModalLogicFamily.TEMPORAL.value,
            ModalLogicFamily.DEONTIC.value,
            -0.452673072434,
            0.602673072434,
            "adaptive_temporal_deontic_outvoted_margin_low",
        ),
        (
            "us-code-15-1013-7b7f5c258b19ba20",
            ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
            ModalLogicFamily.TEMPORAL.value,
            -0.63643511235,
            0.78643511235,
            "adaptive_conditional_normative_temporal_outvoted_margin_low",
        ),
        (
            "us-code-26-24-89f03f1928d2bd08",
            ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
            ModalLogicFamily.DEONTIC.value,
            -0.162752621665,
            0.312752621665,
            "adaptive_conditional_normative_deontic_outvoted_margin_low",
        ),
    ),
)
def test_compiler_exposes_explicit_ambiguity_for_packet_004100_adaptive_margins(
    monkeypatch,
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
    family_margin = 0.150980483864
    ranking = _ranking_for_margin(
        predicted_family=ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        target_family=ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ranking = _ranking_for_margin(
        predicted_family=predicted_family,
        target_family=target_family,
        family_margin=family_margin,
    )
    compiler._adaptive_family_ranking_from_logits = (  # type: ignore[method-assign]
        lambda _encoding, ranking=ranking: list(ranking)
    )

    result = compiler.compile(
        "Provided that section 1 applies, the Secretary shall issue notice.",
        document_id="packet-000743-refined-conditional-self-margin",
    )
    ambiguity = _adaptive_explicit_ambiguity_from_source(
        result,
        predicted_family=ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        target_family=ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        predicted_family_source="adaptive_logits_fallback",
    )
    assert ambiguity is not None
    assert (
        ambiguity.ambiguity_type
        == "adaptive_conditional_normative_conditional_normative_contested_margin_low"
    )
    assert ambiguity.severity == "review"
        "As provided in section 3, the Secretary shall act by June 1, 2030.",
        document_id=f"packet-002421-{sample_id}",
        "As provided in section 3, the Secretary shall act by June 1, 2030.",
        document_id=f"packet-002568-{sample_id}",
        "As provided in section 3, the Secretary shall act by June 1, 2030.",
        document_id=f"packet-004100-{sample_id}",
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
    assert ambiguity.metadata.get("adaptive_margin_direction") == "outvoted"
    assert ambiguity.metadata.get("explicit_ambiguity_type") == expected_type
    assert ambiguity.metadata.get("adaptive_policy_pair") == (
        f"{predicted_family}->{target_family}"
    )
    assert ambiguity.severity == expected_severity
    assert ambiguity.metadata.get("is_compiler_ambiguity_bundle_pair") is True
    assert ambiguity.metadata.get("ambiguity_policy_bundle") == "compiler_ambiguity"
    assert ambiguity.metadata.get("explicit_ambiguity_type") == expected_type
    assert (
        abs(float(ambiguity.metadata.get("family_margin_raw", 0.0)) - family_margin)
        <= 1e-12
    )
    assert (
        float(ambiguity.metadata.get("adaptive_family_margin_threshold", 0.0))
        == 0.15
    )
    assert (
        float(
            ambiguity.metadata.get(
                "adaptive_effective_family_margin_threshold",
                0.0,
            )
        )
        > 0.15
    )
    assert float(ambiguity.metadata.get("adaptive_pair_margin_buffer", 0.0)) > 0.0
    assert abs(float(ambiguity.metadata.get("priority", 0.0)) - expected_priority) <= (
        1e-12
    )
    assert abs(
        float(ambiguity.metadata.get("adaptive_priority", 0.0)) - expected_priority
    ) <= (1e-12)
    assert abs(float(ambiguity.metadata.get("priority", 0.0)) - priority) <= 1e-12
    assert abs(float(ambiguity.metadata.get("adaptive_priority", 0.0)) - priority) <= (
        1e-12
    )
