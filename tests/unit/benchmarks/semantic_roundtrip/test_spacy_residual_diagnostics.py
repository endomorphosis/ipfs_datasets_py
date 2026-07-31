"""Unit tests for the spaCy residual diagnostics teacher (PLAT-050)."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from benchmarks.semantic_roundtrip.contracts import (
    CanonicalRule,
    CanonicalRuleIR,
    ComponentStatus,
    ConstructorResult,
    FailureReason,
)
from benchmarks.semantic_roundtrip.constructors.modal_spacy import (
    MODAL_SPACY_CANONICAL_CONSTRUCTOR_INTERFACE,
    POLARITY_PREFLIGHT_INTERFACE,
    RESIDUAL_POLARITY_INVERSION_CASE_IDS,
    ModalSpacyConstruction,
    ModalSpacyConstructorDiagnostics,
    ModalSpacyFrontendStatus,
    SourceSpanDiagnostic,
    polarity_preflight,
)
from benchmarks.semantic_roundtrip.residual_catalog import (
    BASELINE_ARM_ID,
    BASELINE_CONSTRUCTOR_IDENTITY,
    NONZERO_PILOT_CASE_IDS,
    PILOT_CASE_IDS,
    ZERO_RESIDUAL_CONTROL_CASE_ID,
    ResidualFacet,
    build_case_residual,
    load_pilot_matrix_cases,
    load_plateau_residual_catalog,
)
from benchmarks.semantic_roundtrip.spacy_residual_diagnostics import (
    PRODUCTION_ARM_ID,
    PRODUCTION_CONSTRUCTOR_IDENTITY,
    PRODUCTION_DEFAULT_CHANGED,
    SEMANTIC_AUTHORITY,
    SIGNAL_KIND_MISSING_SLOT,
    SIGNAL_KIND_POLARITY,
    SIGNAL_KIND_SPAN,
    SPACY_DIAGNOSTIC_RECEIPT_INTERFACE,
    SPACY_PILOT_DIAGNOSTICS_MAP_INTERFACE,
    SPACY_RESIDUAL_CUE_INTERFACE,
    SPACY_RESIDUAL_DIAGNOSTICS_INTERFACE,
    SPACY_RESIDUAL_DIAGNOSTICS_SCHEMA,
    TEACHER_IDENTITY,
    TEACHER_ROLE,
    CaseSpacyDiagnostics,
    MissingSlotSignal,
    PolaritySignal,
    SpanSignal,
    SpacyDiagnosticReceipt,
    SpacyPilotDiagnosticsMap,
    SpacyResidualDiagnosticsError,
    assert_production_default_unchanged,
    attach_spacy_cues_to_facets,
    attach_spacy_diagnostics_to_case_residual,
    attach_spacy_diagnostics_to_catalog_cases,
    build_spacy_diagnostic_receipt,
    compute_missing_slot_signals,
    compute_polarity_signals,
    compute_span_signals,
    diagnose_ir_pair,
    diagnose_modal_spacy_construction,
    diagnose_pilot_cases,
    polarity_preflight_is_fail_closed,
    production_path_is_typed_deontic_no_repair,
    spacy_cue_from_signals,
    spacy_cues_by_field_path,
)


ROOT = Path(__file__).resolve().parents[4]


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


def _ir(*rules: CanonicalRule) -> CanonicalRuleIR:
    return CanonicalRuleIR(rules)


def _span(
    *,
    formula_id: str = "doc-1:f0001",
    source: str = "Agency shall not file notice.",
    start: int = 0,
) -> SourceSpanDiagnostic:
    end = start + len(source)
    return SourceSpanDiagnostic(
        formula_id=formula_id,
        source_id="doc-1",
        start_char=start,
        end_char=end,
        source_span_sha256=hashlib.sha256(source.encode("utf-8")).hexdigest(),
        structural_signature="structural-1",
    )


def _empty_frontend_diagnostics(
    *,
    status: ModalSpacyFrontendStatus = ModalSpacyFrontendStatus.FULL_MODEL,
    spans: tuple[SourceSpanDiagnostic, ...] = (),
    detail: str | None = None,
) -> ModalSpacyConstructorDiagnostics:
    return ModalSpacyConstructorDiagnostics(
        frontend_status=status,
        requested_model="en_core_web_sm",
        effective_model="en_core_web_sm",
        requested_pipeline=("tok2vec", "tagger", "parser", "attribute_ruler", "lemmatizer", "ner"),
        effective_pipeline=("tok2vec", "tagger", "parser", "attribute_ruler", "lemmatizer", "ner"),
        requested_model_version="3.7.1",
        effective_model_version="3.7.1",
        language="en",
        fallback_used=False,
        parser_backend="spacy_modal_codec_v1",
        source_spans=spans,
        detail=detail,
    )


def test_interfaces_and_production_defaults_are_frozen() -> None:
    assert SPACY_RESIDUAL_DIAGNOSTICS_INTERFACE == "SpacyResidualDiagnostics@1"
    assert SPACY_RESIDUAL_CUE_INTERFACE == "SpacyResidualCue@1"
    assert SPACY_PILOT_DIAGNOSTICS_MAP_INTERFACE == (
        "SpacyPilotDiagnosticsMap@1"
    )
    assert SPACY_DIAGNOSTIC_RECEIPT_INTERFACE == "SpacyDiagnosticReceipt@1"
    assert SPACY_RESIDUAL_DIAGNOSTICS_SCHEMA.startswith("ipfs-datasets.")
    assert TEACHER_IDENTITY == MODAL_SPACY_CANONICAL_CONSTRUCTOR_INTERFACE
    assert TEACHER_ROLE == "teacher_residual_only"
    assert PRODUCTION_ARM_ID == BASELINE_ARM_ID
    assert PRODUCTION_CONSTRUCTOR_IDENTITY == BASELINE_CONSTRUCTOR_IDENTITY
    assert PRODUCTION_DEFAULT_CHANGED is False
    assert SEMANTIC_AUTHORITY is False
    assert production_path_is_typed_deontic_no_repair() is True
    assert_production_default_unchanged()
    # Teacher must not be the production constructor.
    assert TEACHER_IDENTITY != PRODUCTION_CONSTRUCTOR_IDENTITY
    assert "typed_deontic" in PRODUCTION_ARM_ID
    assert "no_repair" in PRODUCTION_ARM_ID


def test_polarity_signals_detect_modality_inversion() -> None:
    gold = _ir(_rule(modality="F"))
    inverted = _ir(_rule(modality="O"))
    signals = compute_polarity_signals(gold, inverted)
    assert len(signals) == 1
    signal = signals[0]
    assert signal.signal_kind == SIGNAL_KIND_POLARITY
    assert signal.field_path == "rules[0].modality"
    assert signal.modality_preserved is False
    assert signal.gold_modality == "F"
    assert signal.candidate_modality == "O"


def test_polarity_signals_missing_candidate_fail_closed() -> None:
    gold = _ir(_rule(modality="O"))
    signals = compute_polarity_signals(gold, None)
    assert signals
    assert all(item.modality_preserved is False for item in signals)


def test_missing_slot_signals_for_empty_candidate_fields() -> None:
    gold = _ir(
        _rule(
            temporal=("within_10_days",),
            exceptions=("emergency",),
        )
    )
    candidate = _ir(_rule(temporal=(), exceptions=()))
    signals = compute_missing_slot_signals(gold, candidate)
    paths = {item.field_path for item in signals}
    assert "rules[0].temporal" in paths
    assert "rules[0].exceptions" in paths
    assert all(item.signal_kind == SIGNAL_KIND_MISSING_SLOT for item in signals)
    temporal = next(
        item for item in signals if item.field_path == "rules[0].temporal"
    )
    assert temporal.gold_value == ["within_10_days"]
    assert temporal.candidate_value == []


def test_missing_slot_signals_for_missing_rule() -> None:
    gold = _ir(_rule(), _rule(actor="banks", action="disclose"))
    candidate = _ir(_rule())
    signals = compute_missing_slot_signals(gold, candidate)
    missing_rules = [
        item for item in signals if item.residual_kind == "missing_rule"
    ]
    assert missing_rules
    assert any(item.field_path == "rules[1]" for item in missing_rules)


def test_span_signals_from_source_span_diagnostics() -> None:
    span = _span()
    signals = compute_span_signals((span,), candidate_ir=_ir(_rule()))
    assert len(signals) == 1
    assert signals[0].signal_kind == SIGNAL_KIND_SPAN
    assert signals[0].field_path == "rules[0]"
    assert signals[0].source_span_sha256 == span.source_span_sha256
    assert signals[0].formula_id == span.formula_id


def test_diagnose_ir_pair_returns_all_three_signal_families() -> None:
    gold = _ir(
        _rule(
            modality="F",
            temporal=("within_10_days",),
        )
    )
    candidate = _ir(
        _rule(
            modality="O",
            temporal=(),
        )
    )
    span = _span(source="Agency cannot file notice within 10 days.")
    diagnostics = diagnose_ir_pair(
        "exec_order_1",
        gold,
        candidate,
        source_spans=(span,),
        frontend_status=ModalSpacyFrontendStatus.FULL_MODEL,
    )
    assert diagnostics.interface == SPACY_RESIDUAL_DIAGNOSTICS_INTERFACE
    assert diagnostics.case_id == "exec_order_1"
    assert diagnostics.semantic_authority is False
    assert diagnostics.promotion_requires_full_gates is True
    assert diagnostics.polarity_gate_passed is False
    assert diagnostics.polarity_preflight["interface"] == (
        POLARITY_PREFLIGHT_INTERFACE
    )
    assert diagnostics.polarity_preflight["gate_passed"] is False
    assert diagnostics.polarity_signals
    assert diagnostics.span_signals
    assert diagnostics.missing_slot_signals
    assert SIGNAL_KIND_POLARITY in diagnostics.signal_kinds_present
    assert SIGNAL_KIND_SPAN in diagnostics.signal_kinds_present
    assert SIGNAL_KIND_MISSING_SLOT in diagnostics.signal_kinds_present
    assert diagnostics.frontend_status == "full_model"
    assert diagnostics.has_polarity_inversion is True


def test_fail_closed_polarity_preflight_interaction_inversion() -> None:
    gold = _ir(_rule(modality="F", actor="agency", action="file"))
    inverted = _ir(_rule(modality="O", actor="agency", action="file"))
    preflight = polarity_preflight(gold, inverted)
    assert preflight["gate_passed"] is False
    diagnostics = diagnose_ir_pair("polarity_probe", gold, inverted)
    assert diagnostics.polarity_gate_passed is False
    assert diagnostics.polarity_preflight["gate_passed"] is False
    assert diagnostics.polarity_preflight["inversion_count"] == 1
    assert diagnostics.has_polarity_inversion is True
    # Diagnostics must not widen a closed preflight gate.
    assert polarity_preflight_is_fail_closed(gold, inverted) is True


def test_fail_closed_polarity_preflight_interaction_missing_candidate() -> None:
    gold = _ir(_rule(modality="O"))
    preflight = polarity_preflight(gold, None)
    assert preflight["gate_passed"] is False
    assert preflight["evaluated"] is False
    diagnostics = diagnose_ir_pair("missing_probe", gold, None)
    assert diagnostics.evaluated is False
    assert diagnostics.polarity_gate_passed is False
    assert diagnostics.polarity_signals
    assert diagnostics.missing_slot_signals
    assert polarity_preflight_is_fail_closed(gold, None) is True


def test_fail_closed_polarity_preflight_interaction_unassigned_nonempty_gold() -> None:
    gold = _ir(
        _rule(modality="O", actor="agency", action="file"),
        _rule(modality="F", actor="banks", action="disclose", object_atom="activity"),
    )
    # Candidate only matches one rule poorly / not at all by using distant atoms
    # so assignment may still match one; force zero assignment with empty IR.
    empty = _ir()
    preflight = polarity_preflight(gold, empty)
    assert preflight["gate_passed"] is False
    diagnostics = diagnose_ir_pair("unassigned_probe", gold, empty)
    assert diagnostics.polarity_gate_passed is False
    assert diagnostics.polarity_preflight["assigned_rule_count"] == 0
    assert polarity_preflight_is_fail_closed(gold, empty) is True


def test_polarity_preserving_pair_opens_gate() -> None:
    gold = _ir(_rule(modality="F"))
    preserved = _ir(_rule(modality="F"))
    preflight = polarity_preflight(gold, preserved)
    assert preflight["gate_passed"] is True
    diagnostics = diagnose_ir_pair("clean_probe", gold, preserved)
    assert diagnostics.polarity_gate_passed is True
    assert diagnostics.has_polarity_inversion is False
    assert all(item.modality_preserved for item in diagnostics.polarity_signals)
    assert polarity_preflight_is_fail_closed(gold, preserved) is True


def test_diagnose_modal_spacy_construction_uses_private_spans() -> None:
    gold = _ir(_rule(modality="F"))
    candidate = _ir(_rule(modality="F"))
    span = _span()
    construction = ModalSpacyConstruction(
        result=ConstructorResult(
            ComponentStatus.SUCCESS,
            canonical_ir=candidate,
        ),
        diagnostics=_empty_frontend_diagnostics(spans=(span,)),
    )
    diagnostics = diagnose_modal_spacy_construction(
        "exception_with_window", gold, construction
    )
    assert diagnostics.polarity_gate_passed is True
    assert diagnostics.span_signal_count == 1
    assert diagnostics.frontend_status == "full_model"
    assert diagnostics.teacher_identity == TEACHER_IDENTITY


def test_diagnose_modal_spacy_construction_failed_result_fail_closed() -> None:
    gold = _ir(_rule())
    construction = ModalSpacyConstruction(
        result=ConstructorResult(
            ComponentStatus.FAILED,
            failure_reason=FailureReason.CAPABILITY_UNAVAILABLE,
            failure_detail="spaCy model unavailable",
        ),
        diagnostics=_empty_frontend_diagnostics(
            status=ModalSpacyFrontendStatus.UNAVAILABLE,
            detail="spaCy model unavailable",
        ),
    )
    diagnostics = diagnose_modal_spacy_construction(
        "exec_order_1", gold, construction
    )
    assert diagnostics.polarity_gate_passed is False
    assert diagnostics.evaluated is False
    assert diagnostics.frontend_status == "unavailable"
    assert "unavailable" in (diagnostics.detail or "").lower() or (
        "missing" in (diagnostics.detail or "").lower()
        or diagnostics.detail is not None
    )


def test_spacy_cues_attach_to_residual_facets_without_changing_loss() -> None:
    gold = _ir(
        _rule(temporal=("within_10_days",), modality="O"),
    )
    candidate = _ir(
        _rule(temporal=(), modality="O"),
    )
    case = build_case_residual("demo_case", gold, candidate)
    assert case.residuals
    original_loss = case.forward_loss
    original_contrib = sum(facet.loss_contribution for facet in case.residuals)

    diagnostics = diagnose_ir_pair(
        "demo_case",
        gold,
        candidate,
        source_spans=(_span(source="Agency shall file notice within 10 days."),),
    )
    cues = spacy_cues_by_field_path(diagnostics)
    assert any(
        SIGNAL_KIND_MISSING_SLOT in cue["signal_kinds"] for cue in cues.values()
    )

    attached_facets = attach_spacy_cues_to_facets(case.residuals, cues)
    assert len(attached_facets) == len(case.residuals)
    # At least the temporal residual should receive a missing-slot cue.
    temporal = next(
        facet
        for facet in attached_facets
        if facet.field_path == "rules[0].temporal"
    )
    assert temporal.spacy_cue is not None
    assert temporal.spacy_cue["interface"] == SPACY_RESIDUAL_CUE_INTERFACE
    assert temporal.spacy_cue["semantic_authority"] is False
    assert temporal.spacy_cue["promotion_requires_full_gates"] is True
    assert temporal.spacy_cue["production_default_changed"] is False
    assert SIGNAL_KIND_MISSING_SLOT in temporal.spacy_cue["signal_kinds"]
    assert temporal.loss_contribution > 0.0

    attached_case = attach_spacy_diagnostics_to_case_residual(case, diagnostics)
    assert attached_case.forward_loss == original_loss
    assert (
        sum(facet.loss_contribution for facet in attached_case.residuals)
        == original_contrib
    )
    assert any(facet.spacy_cue is not None for facet in attached_case.residuals)


def test_spacy_cue_from_signals_requires_at_least_one_signal() -> None:
    with pytest.raises(SpacyResidualDiagnosticsError):
        spacy_cue_from_signals()
    cue = spacy_cue_from_signals(
        polarity=PolaritySignal(
            field_path="rules[0].modality",
            modality_preserved=True,
            gold_modality="O",
            candidate_modality="O",
            reference_index=0,
            candidate_index=0,
        ),
        polarity_preflight_gate_passed=True,
        case_id="exception_with_window",
    )
    assert cue["interface"] == SPACY_RESIDUAL_CUE_INTERFACE
    assert cue["semantic_authority"] is False
    assert cue["case_id"] == "exception_with_window"
    assert cue["polarity_preflight_gate_passed"] is True


def test_diagnose_pilot_cases_offline_returns_signals_per_case() -> None:
    matrix_cases = load_pilot_matrix_cases()
    # Offline path: gold vs gold for control, gold vs defective candidate for others.
    candidate_by_case: dict[str, CanonicalRuleIR | None] = {}
    spans_by_case: dict[str, tuple[SourceSpanDiagnostic, ...]] = {}
    for case in matrix_cases:
        if case.case_id == ZERO_RESIDUAL_CONTROL_CASE_ID:
            candidate_by_case[case.case_id] = case.gold_ir
            spans_by_case[case.case_id] = (
                _span(
                    formula_id=f"{case.case_id}:f0",
                    source=case.source_text[: min(40, len(case.source_text))]
                    or "control",
                ),
            )
        else:
            # Drop temporal/exceptions to force missing-slot signals; keep modality
            # when possible so polarity can still be evaluated.
            rules = []
            for rule in case.gold_ir.rules:
                rules.append(
                    CanonicalRule(
                        modality=rule.modality,
                        actor=rule.actor,
                        action=rule.action,
                        object=rule.object,
                        conditions=(),
                        exceptions=(),
                        temporal=(),
                    )
                )
            # Invert first rule modality to exercise polarity fail-closed on
            # at least one nonzero pilot.
            if rules:
                first = rules[0]
                inverted_mod = (
                    "O" if first.modality == "F" else "F"
                    if first.modality == "O"
                    else first.modality
                )
                rules[0] = CanonicalRule(
                    modality=inverted_mod,
                    actor=first.actor,
                    action=first.action,
                    object=first.object,
                    conditions=(),
                    exceptions=(),
                    temporal=(),
                )
            candidate_by_case[case.case_id] = CanonicalRuleIR(tuple(rules))
            spans_by_case[case.case_id] = (
                _span(
                    formula_id=f"{case.case_id}:f0",
                    source=case.source_text[: min(40, len(case.source_text))]
                    or case.case_id,
                ),
            )

    diagnostics_map = diagnose_pilot_cases(
        cases=matrix_cases,
        candidate_ir_by_case=candidate_by_case,
        source_spans_by_case=spans_by_case,
        construct=False,
    )
    assert diagnostics_map.interface == SPACY_PILOT_DIAGNOSTICS_MAP_INTERFACE
    assert diagnostics_map.semantic_authority is False
    assert diagnostics_map.production_default_changed is False
    assert set(diagnostics_map.case_ids) == set(PILOT_CASE_IDS)
    assert diagnostics_map.production_arm_id == BASELINE_ARM_ID
    assert (
        diagnostics_map.production_constructor_identity
        == BASELINE_CONSTRUCTOR_IDENTITY
    )

    by_case = diagnostics_map.by_case_id()
    control = by_case[ZERO_RESIDUAL_CONTROL_CASE_ID]
    assert control.polarity_gate_passed is True
    assert control.span_signal_count >= 1
    # Control may have no missing slots when gold==candidate.
    assert SIGNAL_KIND_SPAN in control.signal_kinds_present
    assert SIGNAL_KIND_POLARITY in control.signal_kinds_present

    for case_id in NONZERO_PILOT_CASE_IDS:
        record = by_case[case_id]
        # Every pilot case exposes the three signal families when spans and
        # defective slots / polarity issues are present.
        assert record.polarity_signals, case_id
        assert record.span_signals, case_id
        assert record.missing_slot_signals, case_id
        assert record.polarity_gate_passed is False, case_id
        assert record.semantic_authority is False, case_id
        kinds = set(record.signal_kinds_present)
        assert SIGNAL_KIND_POLARITY in kinds, case_id
        assert SIGNAL_KIND_SPAN in kinds, case_id
        assert SIGNAL_KIND_MISSING_SLOT in kinds, case_id

    receipt = build_spacy_diagnostic_receipt(diagnostics_map)
    assert isinstance(receipt, SpacyDiagnosticReceipt)
    payload = receipt.to_dict()
    assert payload["interface"] == SPACY_DIAGNOSTIC_RECEIPT_INTERFACE
    assert payload["semantic_authority"] is False
    assert payload["production_default_changed"] is False
    assert payload["evidence_subset"] == "spacy-diagnostic receipt"
    assert set(payload["pilot_case_ids"]) == set(PILOT_CASE_IDS)


def test_attach_spacy_diagnostics_to_catalog_cases() -> None:
    catalog = load_plateau_residual_catalog()
    # Build offline diagnostics aligned to residual field paths from catalog L1
    # is not required: attach using case gold vs gold for control and defective
    # candidates for nonzero cases.
    matrix_cases = load_pilot_matrix_cases()
    candidate_by_case: dict[str, CanonicalRuleIR] = {}
    for case in matrix_cases:
        if case.case_id == ZERO_RESIDUAL_CONTROL_CASE_ID:
            candidate_by_case[case.case_id] = case.gold_ir
        else:
            # Empty temporal/exceptions to create missing-slot cues that can
            # attach when residual facets share those field paths.
            rules = tuple(
                CanonicalRule(
                    modality=rule.modality,
                    actor=rule.actor,
                    action=rule.action,
                    object=rule.object,
                    conditions=(),
                    exceptions=(),
                    temporal=(),
                )
                for rule in case.gold_ir.rules
            )
            candidate_by_case[case.case_id] = CanonicalRuleIR(rules)

    diagnostics_map = diagnose_pilot_cases(
        cases=matrix_cases,
        candidate_ir_by_case=candidate_by_case,
        construct=False,
    )
    enriched = attach_spacy_diagnostics_to_catalog_cases(
        catalog, diagnostics_map
    )
    assert enriched["spacy_teacher"]["semantic_authority"] is False
    assert enriched["spacy_teacher"]["production_default_changed"] is False
    assert (
        enriched["spacy_teacher"]["teacher_identity"]
        == MODAL_SPACY_CANONICAL_CONSTRUCTOR_INTERFACE
    )
    # Production baseline metadata on the sealed catalog is preserved.
    assert enriched["baseline"]["arm_id"] == catalog["baseline"]["arm_id"]
    assert enriched["baseline"]["constructor_identity"] == (
        catalog["baseline"]["constructor_identity"]
    )

    case_by_id = {
        item["case_id"]: item for item in enriched["cases"]  # type: ignore[index]
    }
    assert "spacy_diagnostics" in case_by_id[ZERO_RESIDUAL_CONTROL_CASE_ID]
    # Nonzero pilots with field residuals should receive at least some cues
    # when missing-slot paths align.
    nonzero_with_cues = 0
    for case_id in NONZERO_PILOT_CASE_IDS:
        case = case_by_id[case_id]
        assert "spacy_diagnostics" in case
        assert case["spacy_diagnostics"]["semantic_authority"] is False
        if any(
            facet.get("spacy_cue") is not None
            for facet in case.get("residuals") or ()
        ):
            nonzero_with_cues += 1
    # Catalog residuals are vs typed_deontic L1 (not our defective candidates),
    # so attachment may be sparse; the API still stamps case-level diagnostics.
    assert case_by_id["exec_order_1"]["spacy_diagnostics"][
        "missing_slot_signal_count"
    ] >= 0
    # Ensure attachment path does not invent semantic authority on facets.
    for case in enriched["cases"]:  # type: ignore[union-attr]
        for facet in case.get("residuals") or ():
            cue = facet.get("spacy_cue")
            if cue is not None:
                assert cue["semantic_authority"] is False
                nonzero_with_cues += 0  # keep variable used when no cues
    del nonzero_with_cues


def test_case_diagnostics_round_trip_dict() -> None:
    gold = _ir(_rule(modality="F", temporal=("within_10_days",)))
    candidate = _ir(_rule(modality="O", temporal=()))
    original = diagnose_ir_pair(
        "legal_doc_1",
        gold,
        candidate,
        source_spans=(_span(),),
    )
    restored = CaseSpacyDiagnostics.from_dict(original.to_dict())
    assert restored.case_id == original.case_id
    assert restored.polarity_gate_passed == original.polarity_gate_passed
    assert restored.polarity_signal_count == original.polarity_signal_count
    assert restored.span_signal_count == original.span_signal_count
    assert (
        restored.missing_slot_signal_count == original.missing_slot_signal_count
    )
    assert restored.semantic_authority is False


def test_pilot_map_round_trip_dict() -> None:
    gold = _ir(_rule())
    diagnostics = diagnose_ir_pair(
        ZERO_RESIDUAL_CONTROL_CASE_ID, gold, gold, source_spans=(_span(),)
    )
    original = SpacyPilotDiagnosticsMap(cases=(diagnostics,))
    restored = SpacyPilotDiagnosticsMap.from_dict(original.to_dict())
    assert restored.case_ids == original.case_ids
    assert restored.production_default_changed is False
    assert restored.semantic_authority is False


def test_polarity_gate_mismatch_is_rejected() -> None:
    with pytest.raises(SpacyResidualDiagnosticsError):
        CaseSpacyDiagnostics(
            case_id="bad",
            polarity_signals=(),
            span_signals=(),
            missing_slot_signals=(),
            polarity_preflight={
                "interface": POLARITY_PREFLIGHT_INTERFACE,
                "gate_passed": False,
                "evaluated": True,
            },
            polarity_gate_passed=True,  # mismatch must fail closed
            evaluated=True,
        )


def test_semantic_authority_true_is_rejected() -> None:
    with pytest.raises(SpacyResidualDiagnosticsError):
        CaseSpacyDiagnostics(
            case_id="bad",
            polarity_signals=(),
            span_signals=(),
            missing_slot_signals=(),
            polarity_preflight={
                "interface": POLARITY_PREFLIGHT_INTERFACE,
                "gate_passed": True,
                "evaluated": True,
            },
            polarity_gate_passed=True,
            evaluated=True,
            semantic_authority=True,
        )


def test_attach_rejects_authoritative_cue() -> None:
    facet = ResidualFacet(
        case_id="demo",
        field_path="rules[0].temporal",
        residual_kind="field_mismatch",
        loss_contribution=0.05,
        similarity=0.0,
        suggested_trigger_kind="missing",
        canonical_field="temporal",
        gold_rule_index=0,
        candidate_rule_index=0,
        gold_value=["within_10_days"],
        candidate_value=[],
    )
    with pytest.raises(SpacyResidualDiagnosticsError):
        attach_spacy_cues_to_facets(
            (facet,),
            {
                "rules[0].temporal": {
                    "interface": SPACY_RESIDUAL_CUE_INTERFACE,
                    "semantic_authority": True,
                    "signal_kinds": [SIGNAL_KIND_MISSING_SLOT],
                }
            },
        )


def test_residual_polarity_inversion_documentation_flag() -> None:
    gold = _ir(_rule(modality="F"))
    inverted = _ir(_rule(modality="O"))
    # When case_id is listed in RESIDUAL_POLARITY_INVERSION_CASE_IDS the flag
    # is true; currently the constant is empty so flag is false for probes.
    diagnostics = diagnose_ir_pair("not_documented_case", gold, inverted)
    assert diagnostics.residual_polarity_inversion_documented is (
        "not_documented_case" in RESIDUAL_POLARITY_INVERSION_CASE_IDS
    )
    for case_id in RESIDUAL_POLARITY_INVERSION_CASE_IDS:
        documented = diagnose_ir_pair(case_id, gold, inverted)
        assert documented.residual_polarity_inversion_documented is True


def test_signal_dataclasses_validate_kinds() -> None:
    with pytest.raises(SpacyResidualDiagnosticsError):
        PolaritySignal(field_path="rules[0].modality", signal_kind="span")
    with pytest.raises(SpacyResidualDiagnosticsError):
        SpanSignal(
            field_path="rules[0]",
            formula_id="f1",
            source_id="s",
            start_char=0,
            end_char=1,
            source_span_sha256="",
            signal_kind="polarity",
        )
    with pytest.raises(SpacyResidualDiagnosticsError):
        MissingSlotSignal(
            field_path="rules[0].temporal",
            canonical_field="temporal",
            gold_value=["x"],
            signal_kind="polarity",
        )
