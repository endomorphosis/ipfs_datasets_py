"""Contract tests for StageMetrics@1 constructor-only research scoring."""

from __future__ import annotations

import pytest

from benchmarks.semantic_roundtrip.contracts import (
    CanonicalRule,
    CanonicalRuleIR,
    ContractError,
)
from benchmarks.semantic_roundtrip.metrics import compare_semantic_ir
from benchmarks.semantic_roundtrip.stage_metrics import (
    PROMOTION_FULL_GATE_IDS,
    PROMOTION_POLICY_NOTE,
    PROMOTION_REQUIRES_FULL_GATES,
    STAGE_CONSTRUCTOR_ONLY,
    STAGE_METRICS_INTERFACE,
    STAGE_METRICS_SCHEMA,
    ConstructorOnlyStageMetrics,
    compute_constructor_only_metrics,
    constructor_only_metrics_from_matrix_record,
    export_constructor_only_stage_metrics,
)


def _rule(
    *,
    modality: str = "O",
    actor: str = "agency",
    action: str = "file",
    object_atom: str = "notice",
    conditions: tuple[str, ...] = (),
    exceptions: tuple[str, ...] = (),
    temporal: tuple[str, ...] = (),
) -> CanonicalRule:
    return CanonicalRule(
        modality=modality,
        actor=actor,
        action=action,
        object=object_atom,
        conditions=conditions,
        exceptions=exceptions,
        temporal=temporal,
    )


def _gold_exception_window() -> CanonicalRuleIR:
    return CanonicalRuleIR(
        (
            _rule(
                modality="O",
                actor="company_a",
                action="submit",
                object_atom="backup_report",
                exceptions=("emergency",),
                temporal=("within_10_days",),
            ),
        )
    )


def test_stage_metrics_interface_and_promotion_policy_are_frozen() -> None:
    assert STAGE_METRICS_INTERFACE == "StageMetrics@1"
    assert STAGE_CONSTRUCTOR_ONLY == "constructor_only"
    assert STAGE_METRICS_SCHEMA.startswith("ipfs-datasets.")
    assert PROMOTION_REQUIRES_FULL_GATES is True
    assert PROMOTION_FULL_GATE_IDS == (
        "full_coverage",
        "source_copy_exclusion",
        "polarity_preservation",
    )
    assert "promotion still requires full gates" in PROMOTION_POLICY_NOTE.lower()
    assert "full_coverage" in PROMOTION_POLICY_NOTE


def test_constructor_only_metrics_report_forward_loss_and_facet_survival() -> None:
    gold = _gold_exception_window()
    l1 = CanonicalRuleIR(
        (
            _rule(
                modality="O",
                actor="company_a",
                action="submit",
                object_atom="backup_report",
                exceptions=("emergency",),
                temporal=("within_10_days",),
            ),
        )
    )
    metrics = compute_constructor_only_metrics(gold, l1)
    payload = metrics.to_dict()

    assert payload["interface"] == STAGE_METRICS_INTERFACE
    assert payload["stage"] == STAGE_CONSTRUCTOR_ONLY
    assert payload["forward_loss"] == 0.0
    assert payload["semantic_score"] == 1.0
    assert payload["modality_survival"] == 1.0
    assert payload["conditions_survival"] == 1.0
    assert payload["exceptions_survival"] == 1.0
    assert payload["temporal_survival"] == 1.0
    assert payload["polarity_preserved"] is True
    assert payload["polarity_inversion_count"] == 0
    assert payload["promotion_requires_full_gates"] is True
    assert payload["promotion_full_gate_ids"] == list(PROMOTION_FULL_GATE_IDS)
    assert "full gates" in payload["promotion_policy_note"].lower()


def test_constructor_only_polarity_inversion_is_diagnosed_not_promotable() -> None:
    gold = CanonicalRuleIR((_rule(modality="F"),))
    inverted = CanonicalRuleIR((_rule(modality="O"),))
    metrics = compute_constructor_only_metrics(gold, inverted)

    assert metrics.evaluated is True
    assert metrics.polarity_preserved is False
    assert metrics.polarity_inversion_count == 1
    assert metrics.modality_survival == 0.0
    assert metrics.forward_loss > 0.0
    assert metrics.promotion_requires_full_gates is True
    # Research score exists, but promotion policy remains fail-closed.
    assert metrics.to_dict()["promotion_requires_full_gates"] is True


def test_constructor_only_missing_l1_fails_closed() -> None:
    gold = _gold_exception_window()
    metrics = compute_constructor_only_metrics(gold, None)
    assert metrics.evaluated is False
    assert metrics.forward_loss == 1.0
    assert metrics.modality_survival == 0.0
    assert metrics.conditions_survival == 0.0
    assert metrics.exceptions_survival == 0.0
    assert metrics.temporal_survival == 0.0
    assert metrics.polarity_preserved is False
    assert metrics.promotion_requires_full_gates is True


def test_constructor_only_partial_facet_survival() -> None:
    gold = _gold_exception_window()
    # Same roles/modality; drop exception and temporal survival.
    l1 = CanonicalRuleIR(
        (
            _rule(
                modality="O",
                actor="company_a",
                action="submit",
                object_atom="backup_report",
                exceptions=(),
                temporal=(),
            ),
        )
    )
    metrics = compute_constructor_only_metrics(gold, l1)
    assert metrics.modality_survival == 1.0
    assert metrics.exceptions_survival == 0.0
    assert metrics.temporal_survival == 0.0
    assert metrics.forward_loss > 0.0
    assert metrics.polarity_preserved is True


def test_export_from_matrix_record_forward_comparison() -> None:
    gold = _gold_exception_window()
    l1 = gold
    comparison = compare_semantic_ir(gold, l1)
    record = {
        "case_id": "exception_with_window",
        "cell_id": "modal_spacy__deterministic",
        "record_cid": "baguqeeratestconstructoronly0001",
        "losses": {
            "forward": comparison["semantic_loss"],
            "cycle": 0.0,
            "end_to_end": 0.0,
            "primary": 0.0,
        },
        "artifacts": {"l1": l1.to_dict(), "l2": None, "t1": None},
        "diagnostics": {
            "semantic_comparisons": {
                "forward_gold_to_l1": comparison,
            },
            "gates": {
                "full_coverage": True,
                "source_copy_exclusion": True,
                "polarity_preservation": True,
                "selection_eligible": True,
            },
        },
    }
    metrics = constructor_only_metrics_from_matrix_record(record)
    assert metrics.stage == STAGE_CONSTRUCTOR_ONLY
    assert metrics.forward_loss == float(comparison["semantic_loss"])
    assert metrics.modality_survival == 1.0
    assert metrics.exceptions_survival == 1.0
    assert metrics.temporal_survival == 1.0
    assert metrics.promotion_requires_full_gates is True

    exported = export_constructor_only_stage_metrics([record])
    assert len(exported) == 1
    assert exported[0]["case_id"] == "exception_with_window"
    assert exported[0]["cell_id"] == "modal_spacy__deterministic"
    assert exported[0]["stage"] == STAGE_CONSTRUCTOR_ONLY
    assert exported[0]["promotion_requires_full_gates"] is True
    assert exported[0]["forward_loss"] == metrics.forward_loss


def test_export_from_matrix_record_falls_back_to_artifacts_and_gold() -> None:
    gold = CanonicalRuleIR((_rule(modality="F"),))
    l1 = CanonicalRuleIR((_rule(modality="F"),))
    record = {
        "case_id": "prohibition_case",
        "cell_id": "modal_spacy__deterministic",
        "artifacts": {"l1": l1.to_dict()},
        "diagnostics": {},
        "losses": {},
    }
    metrics = constructor_only_metrics_from_matrix_record(
        record, gold_ir=gold
    )
    assert metrics.forward_loss == 0.0
    assert metrics.polarity_preserved is True
    assert metrics.modality_survival == 1.0

    exported = export_constructor_only_stage_metrics(
        [record],
        gold_ir_by_case={"prohibition_case": gold},
    )
    assert exported[0]["polarity_preserved"] is True


def test_matrix_export_without_comparison_or_gold_fails_closed() -> None:
    record = {
        "case_id": "orphan",
        "artifacts": {"l1": _gold_exception_window().to_dict()},
        "diagnostics": {},
    }
    with pytest.raises(ContractError, match="gold_ir"):
        constructor_only_metrics_from_matrix_record(record)


def test_constructor_only_metrics_reject_promotion_flag_override() -> None:
    with pytest.raises(ContractError, match="promotion_requires_full_gates"):
        ConstructorOnlyStageMetrics(
            stage=STAGE_CONSTRUCTOR_ONLY,
            forward_loss=0.0,
            modality_survival=1.0,
            conditions_survival=1.0,
            exceptions_survival=1.0,
            temporal_survival=1.0,
            semantic_score=1.0,
            polarity_preserved=True,
            polarity_inversion_count=0,
            matched_rule_count=1,
            reference_rule_count=1,
            candidate_rule_count=1,
            evaluated=True,
            promotion_requires_full_gates=False,  # type: ignore[arg-type]
        )


def test_polarity_inversion_fixture_exports_nonzero_forward_loss() -> None:
    """Fail-closed polarity inversion fixtures remain diagnosable in stage metrics."""

    gold = CanonicalRuleIR(
        (
            _rule(modality="F", action="disclose", object_atom="notice"),
            _rule(modality="O", action="file", object_atom="order"),
        )
    )
    inverted = CanonicalRuleIR(
        (
            _rule(modality="O", action="disclose", object_atom="notice"),
            _rule(modality="O", action="file", object_atom="order"),
        )
    )
    metrics = compute_constructor_only_metrics(gold, inverted)
    assert metrics.polarity_preserved is False
    assert metrics.polarity_inversion_count == 1
    assert 0.0 < metrics.modality_survival < 1.0
    assert metrics.forward_loss > 0.0
    assert metrics.promotion_requires_full_gates is True

    comparison = compare_semantic_ir(gold, inverted)
    record = {
        "case_id": "polarity_inversion_fixture",
        "cell_id": "research__constructor_only",
        "losses": {"forward": comparison["semantic_loss"]},
        "diagnostics": {
            "semantic_comparisons": {"forward_gold_to_l1": comparison}
        },
    }
    exported = constructor_only_metrics_from_matrix_record(record).to_dict()
    assert exported["polarity_preserved"] is False
    assert exported["polarity_inversion_count"] == 1
    assert exported["promotion_requires_full_gates"] is True
    assert exported["stage"] == STAGE_CONSTRUCTOR_ONLY
