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
    COMPILER_AMBIGUITY_PACKET_000164_FAMILY_PAIRS,
    COMPILER_AMBIGUITY_PACKET_001623_FAMILY_PAIRS,
    ModalLogicFamily,
    compiler_ambiguity_policy_targets,
    compiler_required_adaptive_ambiguity_targets,
    is_compiler_ambiguity_policy_pair,
    is_compiler_required_adaptive_ambiguity_pair,
    is_priority_signal_free_adaptive_ambiguity_pair,
    priority_signal_free_adaptive_ambiguity_targets,
    signal_free_adaptive_ambiguity_targets,
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


def test_packet_000164_pairs_are_explicit_compiler_ambiguity_policy_entries() -> None:
    expected_pairs = {
        (ModalLogicFamily.DEONTIC.value, ModalLogicFamily.DEONTIC.value),
        (
            ModalLogicFamily.FRAME.value,
            ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ),
        (ModalLogicFamily.FRAME.value, ModalLogicFamily.DEONTIC.value),
        (ModalLogicFamily.FRAME.value, ModalLogicFamily.EPISTEMIC.value),
        (ModalLogicFamily.FRAME.value, ModalLogicFamily.TEMPORAL.value),
    }

    assert set(COMPILER_AMBIGUITY_PACKET_000164_FAMILY_PAIRS) == expected_pairs
    for predicted_family, target_family in expected_pairs:
        assert target_family in compiler_ambiguity_policy_targets(predicted_family)
        assert is_compiler_ambiguity_policy_pair(predicted_family, target_family)
        assert supports_signal_free_adaptive_ambiguity_pair(
            predicted_family,
            target_family,
        )


def test_packet_001623_pairs_are_explicit_compiler_ambiguity_policy_entries() -> None:
    expected_pairs = {
        (
            ModalLogicFamily.DEONTIC.value,
            ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        ),
        (ModalLogicFamily.DEONTIC.value, ModalLogicFamily.DEONTIC.value),
        (ModalLogicFamily.DEONTIC.value, ModalLogicFamily.TEMPORAL.value),
        (ModalLogicFamily.FRAME.value, ModalLogicFamily.DEONTIC.value),
        (ModalLogicFamily.FRAME.value, ModalLogicFamily.TEMPORAL.value),
        (ModalLogicFamily.TEMPORAL.value, ModalLogicFamily.DEONTIC.value),
    }

    assert set(COMPILER_AMBIGUITY_PACKET_001623_FAMILY_PAIRS) == expected_pairs
    for predicted_family, target_family in expected_pairs:
        assert target_family in compiler_ambiguity_policy_targets(predicted_family)
        assert target_family in compiler_required_adaptive_ambiguity_targets(
            predicted_family
        )
        assert target_family in signal_free_adaptive_ambiguity_targets(
            predicted_family
        )
        assert target_family in priority_signal_free_adaptive_ambiguity_targets(
            predicted_family
        )
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


def test_frame_policy_ambiguity_canonicalizes_namespaced_family_tokens(
    monkeypatch,
) -> None:
    compiler = DeterministicModalCompiler(
        config=ModalCompilerConfig(parser_backend="regex")
    )
    monkeypatch.setattr(
        modal_compiler_module,
        "ranked_modal_families",
        lambda _encoding: [
            {
                "family": "modal.registry:frame",
                "count": 0,
                "logit": 1.3,
                "share_raw": 0.7,
                "share": 0.7,
                "source": "test",
            },
            {
                "family": "cue/deontic",
                "count": 0,
                "logit": 1.2,
                "share_raw": 0.69,
                "share": 0.69,
                "source": "test",
            },
        ],
    )
    monkeypatch.setattr(
        modal_compiler_module,
        "modal_ambiguity_signals",
        lambda _encoding: {"has_deontic_scope": True},
    )

    result = compiler.compile(
        "If a vessel is operated in violation of this chapter, the owner is liable.",
        document_id="packet-000164-frame-policy-canonical-family",
    )

    ambiguity = next(
        (
            item
            for item in result.ambiguities
            if item.ambiguity_type == "frame_deontic_family_outvoted"
        ),
        None,
    )
    assert ambiguity is not None
    assert ambiguity.candidate_ids == [
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.DEONTIC.value,
    ]
    assert ambiguity.metadata["is_compiler_ambiguity_bundle_pair"] is True
    assert ambiguity.metadata["ambiguity_policy_bundle"] == "compiler_ambiguity"
    assert ambiguity.metadata["compiler_ambiguity_policy_pair"] == "frame->deontic"
    assert ambiguity.metadata["family_margin"] == -0.01


def test_deontic_policy_ambiguity_uses_family_evidence_without_signal(
    monkeypatch,
) -> None:
    compiler = DeterministicModalCompiler(
        config=ModalCompilerConfig(parser_backend="regex")
    )
    monkeypatch.setattr(
        modal_compiler_module,
        "modal_ambiguity_signals",
        lambda _encoding: {"has_deontic_scope": False, "has_deontic_cue": False},
    )
    ranking = _ranking_for_margin(
        predicted_family=ModalLogicFamily.TEMPORAL.value,
        target_family=ModalLogicFamily.DEONTIC.value,
        family_margin=-0.01,
    )

    ambiguities = compiler._deontic_scope_target_family_ambiguities(
        object(),
        ranking=ranking,
        family_shares={
            ModalLogicFamily.TEMPORAL.value: 0.7,
            ModalLogicFamily.DEONTIC.value: 0.69,
        },
    )

    assert len(ambiguities) == 1
    ambiguity = ambiguities[0]
    assert ambiguity.ambiguity_type == "deontic_scope_family_outvoted"
    assert ambiguity.candidate_ids == [
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ]
    assert ambiguity.metadata["is_compiler_ambiguity_bundle_pair"] is True
    assert ambiguity.metadata["ambiguity_policy_bundle"] == "compiler_ambiguity"
    assert ambiguity.metadata["compiler_ambiguity_policy_pair"] == "temporal->deontic"
    assert ambiguity.metadata["policy_pair_family_evidence"] is True
    assert ambiguity.metadata["family_margin"] == -0.01


def test_temporal_deontic_policy_ambiguity_uses_family_evidence_without_signal(
    monkeypatch,
) -> None:
    compiler = DeterministicModalCompiler(
        config=ModalCompilerConfig(parser_backend="regex")
    )
    monkeypatch.setattr(
        modal_compiler_module,
        "modal_ambiguity_signals",
        lambda _encoding: {"has_deontic_scope": False, "has_deontic_cue": False},
    )
    ranking = _ranking_for_margin(
        predicted_family=ModalLogicFamily.TEMPORAL.value,
        target_family=ModalLogicFamily.DEONTIC.value,
        family_margin=-0.01,
    )

    ambiguities = compiler._temporal_deontic_scope_family_ambiguities(
        object(),
        ranking=ranking,
        family_shares={
            ModalLogicFamily.TEMPORAL.value: 0.7,
            ModalLogicFamily.DEONTIC.value: 0.69,
        },
    )

    assert len(ambiguities) == 1
    ambiguity = ambiguities[0]
    assert ambiguity.ambiguity_type == "temporal_deontic_scope_family_outvoted"
    assert ambiguity.candidate_ids == [
        ModalLogicFamily.TEMPORAL.value,
        ModalLogicFamily.DEONTIC.value,
    ]
    assert ambiguity.metadata["is_compiler_ambiguity_bundle_pair"] is True
    assert ambiguity.metadata["ambiguity_policy_bundle"] == "compiler_ambiguity"
    assert ambiguity.metadata["compiler_ambiguity_policy_pair"] == "temporal->deontic"
    assert ambiguity.metadata["policy_pair_family_evidence"] is True
    assert ambiguity.metadata["family_margin"] == -0.01


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


def test_compiler_exposes_frame_policy_conditional_normative_scope_ambiguity(
    monkeypatch,
) -> None:
    compiler = DeterministicModalCompiler(
        config=ModalCompilerConfig(parser_backend="regex")
    )
    ranking = _ranking_for_margin(
        predicted_family=ModalLogicFamily.FRAME.value,
        target_family=ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
        family_margin=-0.411941176091,
    )
    monkeypatch.setattr(
        modal_compiler_module,
        "ranked_modal_families",
        lambda _encoding, ranking=ranking: list(ranking),
    )
    monkeypatch.setattr(
        modal_compiler_module,
        "modal_ambiguity_signals",
        lambda _encoding: {"has_condition_or_exception_scope": True},
    )

    result = compiler.compile(
        "Except as provided in subsection (b), the eligible institution may apply.",
        document_id="packet-000122-frame-conditional-normative",
    )
    ambiguity = next(
        (
            candidate
            for candidate in result.ambiguities
            if candidate.ambiguity_type
            == "frame_conditional_normative_family_outvoted"
        ),
        None,
    )

    assert ambiguity is not None
    assert ambiguity.severity == "requires_rule"
    assert ambiguity.candidate_ids == [
        ModalLogicFamily.FRAME.value,
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
    ]
    assert ambiguity.metadata.get("is_compiler_ambiguity_bundle_pair") is True
    assert ambiguity.metadata.get("ambiguity_policy_bundle") == "compiler_ambiguity"
    assert (
        ambiguity.metadata.get("compiler_ambiguity_policy_pair")
        == "frame->conditional_normative"
    )
    assert ambiguity.metadata.get("target_family") == (
        ModalLogicFamily.CONDITIONAL_NORMATIVE.value
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
            "us-code-42-13431.-84ac79e2afc504da",
            ModalLogicFamily.DEONTIC.value,
            ModalLogicFamily.DEONTIC.value,
            0.073523213548,
            0.076476786452,
            "adaptive_deontic_deontic_contested_margin_low",
            "review",
        ),
        (
            "us-code-38-2108-955affeffdfda19c",
            ModalLogicFamily.DEONTIC.value,
            ModalLogicFamily.FRAME.value,
            -0.268692982202,
            0.418692982202,
            "adaptive_deontic_frame_outvoted_margin_low",
            "requires_rule",
        ),
    ),
)
def test_compiler_exposes_explicit_ambiguity_for_packet_000258_adaptive_margins(
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
        "The Secretary shall conduct a program under this section.",
        document_id=f"packet-000258-{sample_id}",
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
        document_id=f"packet-002568-{sample_id}",
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
            "us-code-7-5203-b522c0d6ad7a11aa",
            ModalLogicFamily.FRAME.value,
            ModalLogicFamily.TEMPORAL.value,
            -0.313603835283,
            0.463603835283,
            "adaptive_frame_temporal_outvoted_margin_low",
            "requires_rule",
        ),
        (
            "us-code-42-64a-to-64c-92c6a496a40db68f",
            ModalLogicFamily.TEMPORAL.value,
            ModalLogicFamily.TEMPORAL.value,
            0.081722083969,
            0.068277916031,
            "adaptive_temporal_temporal_contested_margin_low",
            "review",
        ),
        (
            "us-code-25-1147-f5bef9a6ca4f493d",
            ModalLogicFamily.FRAME.value,
            ModalLogicFamily.DEONTIC.value,
            -0.106206383221,
            0.256206383221,
            "adaptive_frame_deontic_outvoted_margin_low",
            "requires_rule",
        ),
        (
            "us-code-7-7917-03031f76e7a6c28c",
            ModalLogicFamily.DEONTIC.value,
            ModalLogicFamily.FRAME.value,
            -0.118239387019,
            0.268239387019,
            "adaptive_deontic_frame_outvoted_margin_low",
            "requires_rule",
        ),
    ),
)
def test_compiler_exposes_explicit_ambiguity_for_packet_008598_adaptive_margins(
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
        document_id=f"packet-008598-{sample_id}",
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
            "us-code-42-19154.-632426c408ee8e0d",
            ModalLogicFamily.DEONTIC.value,
            ModalLogicFamily.TEMPORAL.value,
            -0.574287979927,
            0.724287979927,
            "adaptive_deontic_temporal_outvoted_margin_low",
        ),
        (
            "us-code-20-77b-007f3d328fa51fb4",
            ModalLogicFamily.DEONTIC.value,
            ModalLogicFamily.TEMPORAL.value,
            -0.369860347604,
            0.519860347604,
            "adaptive_deontic_temporal_outvoted_margin_low",
        ),
        (
            "us-code-6-1119-96acf5c627297669",
            ModalLogicFamily.FRAME.value,
            ModalLogicFamily.CONDITIONAL_NORMATIVE.value,
            -0.665875609456,
            0.815875609456,
            "adaptive_frame_conditional_normative_outvoted_margin_low",
        ),
    ),
)
def test_compiler_exposes_packet_001314_policy_pair_adaptive_ambiguity(
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
        "The Secretary shall act not later than June 1, 2030.",
        document_id=f"packet-001314-{sample_id}",
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
    assert ambiguity.metadata.get("explicit_ambiguity_type") == expected_type
    assert (
        abs(float(ambiguity.metadata.get("family_margin_raw", 0.0)) - family_margin)
        <= 1e-12
    )
    assert abs(float(ambiguity.metadata.get("priority", 0.0)) - priority) <= 1e-12
    assert abs(float(ambiguity.metadata.get("adaptive_priority", 0.0)) - priority) <= (
        1e-12
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
            "us-code-42-9126.-ae799f62909a6b9e",
            ModalLogicFamily.DEONTIC.value,
            ModalLogicFamily.DEONTIC.value,
            0.013923525308,
            0.136076474692,
            "adaptive_deontic_deontic_contested_margin_low",
            "review",
        ),
        (
            "us-code-50-3369c.-3175f8ba39d9c91d",
            ModalLogicFamily.DEONTIC.value,
            ModalLogicFamily.TEMPORAL.value,
            -0.07918836289,
            0.22918836289,
            "adaptive_deontic_temporal_outvoted_margin_low",
            "requires_rule",
        ),
    ),
)
def test_compiler_exposes_packet_000661_deontic_adaptive_ambiguity(
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
        "The Secretary shall notify the committees not later than 48 hours.",
        document_id=f"packet-000661-{sample_id}",
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
