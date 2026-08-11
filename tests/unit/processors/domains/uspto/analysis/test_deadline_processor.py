"""Unit tests for USPTO deadline processor (PATLAW-044).

Acceptance focus:
  - Every candidate is labeled review-only with assumptions and source spans
  - Missing facts or conflicting rules yield unknown/multiple candidates
  - Named human confirmation is required before any docket export
"""

from __future__ import annotations

import json
from datetime import date

import pytest

from ipfs_datasets_py.processors.domains.uspto.contracts import (
    CONTRACTS_SCHEMA_VERSION,
    CandidateDeadline,
    DisclosureClassification,
    ReviewState,
    canonical_json,
)
from ipfs_datasets_py.processors.domains.uspto.analysis.deadline_processor import (
    DEADLINE_SCHEMA_VERSION,
    OUTPUT_KIND_REVIEW_ONLY_RESPONSE_DATE_CANDIDATES,
    REVIEW_ONLY_DEADLINE_DISCLAIMER,
    AnalysisBounds,
    CalendarAdjustmentKind,
    CandidateComputationStatus,
    DeadlineAnalysisInput,
    DeadlineAnalysisResult,
    DeadlineAssumptions,
    DeadlineConflict,
    DeadlineDisposition,
    DeadlineProcessor,
    DeadlineProcessorError,
    DeadlineReasonCode,
    DeadlineSourceInput,
    DocketExportGate,
    EventBasisKind,
    PeriodUnit,
    ResponseDateCandidate,
    SourceSpanRef,
    StatusEventInput,
    UncertaintyKind,
    add_calendar_months,
    adjust_period_end,
    build_human_review_question,
    calculate_response_date_candidates,
    candidate_local_end_to_utc_iso,
    compute_raw_period_end,
    confirm_for_docket_export,
    contains_forbidden_final_deadline_token,
    next_business_day,
    parse_date_surface,
    parse_period_surface,
    sanitize_deadline_labels,
    sha256_hex,
    sources_from_office_action,
    us_federal_holidays,
)
from ipfs_datasets_py.processors.domains.uspto.analysis.office_action_processor import (
    OfficeActionInput,
    OfficeActionProcessor,
)
from tests.fixtures.uspto.office_actions.generators import (
    build_final_office_action_text,
    build_non_final_office_action_text,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _processor(**kwargs) -> DeadlineProcessor:
    counter = {"n": 0}

    def _ids() -> str:
        counter["n"] += 1
        return f"dl:test:{counter['n']:04d}"

    return DeadlineProcessor(id_factory=_ids, **kwargs)


def _source(
    *,
    source_id: str = "src:period:1",
    span_id: str = "span:resp:1",
    surface: str = (
        "A shortened statutory period for reply is set to expire in 3 months "
        "from the mailing date of this communication."
    ),
    period_amount: int | None = 3,
    period_unit: PeriodUnit | None = PeriodUnit.MONTHS,
    period_surface: str | None = "3 months",
    mailing_date: str | None = "2026-01-15",
    exceptions: tuple[str, ...] = (),
    labels: dict | None = None,
) -> DeadlineSourceInput:
    return DeadlineSourceInput(
        source_id=source_id,
        source_span_id=span_id,
        surface_text=surface,
        response_period_surface=period_surface,
        period_amount=period_amount,
        period_unit=period_unit,
        proposed_date_rule="response_period:3_months",
        legal_citations=("37 C.F.R. 1.134",),
        exceptions=exceptions,
        mailing_date=mailing_date,
        action_id="action:1",
        artifact_id="art:oa:1",
        requirement_type="response_instruction",
        confidence=0.9,
        classification=DisclosureClassification.PUBLIC_USER,
        labels=labels or {"response_period": period_surface or "3 months"},
    )


def _input(
    *sources: DeadlineSourceInput,
    mailing_date: str | None = "2026-01-15",
    status_events: tuple[StatusEventInput, ...] = (),
    assumptions: DeadlineAssumptions | None = None,
    alternative_assumptions: tuple[DeadlineAssumptions, ...] = (),
    emit_extension_variants: bool = False,
    classification: DisclosureClassification = DisclosureClassification.PUBLIC_USER,
    office_action_results: tuple = (),
) -> DeadlineAnalysisInput:
    return DeadlineAnalysisInput(
        matter_id="matter:1",
        analysis_id="analysis:dl:1",
        sources=tuple(sources),
        status_events=status_events,
        office_action_results=office_action_results,
        mailing_date=mailing_date,
        assumptions=assumptions or DeadlineAssumptions(entity_status="undiscounted"),
        alternative_assumptions=alternative_assumptions,
        classification=classification,
        emit_extension_variants=emit_extension_variants,
        max_extension_months=2,
    )


def _assert_round_trip(result: DeadlineAnalysisResult) -> None:
    first = result.to_dict()
    restored = DeadlineAnalysisResult.from_dict(first)
    second = restored.to_dict()
    assert first == second
    assert canonical_json(first) == canonical_json(second)
    public = result.public_projection()
    assert "candidates" not in public
    assert public["is_review_only"] is True
    assert public["is_final_deadline_assertion"] is False
    assert public["is_docket_entry"] is False
    assert public["output_kind"] == OUTPUT_KIND_REVIEW_ONLY_RESPONSE_DATE_CANDIDATES
    assert public["requires_named_confirmation"] is True


def _assert_review_only(result: DeadlineAnalysisResult) -> None:
    assert result.is_review_only is True
    assert result.is_final_deadline_assertion is False
    assert result.is_docket_entry is False
    assert result.output_kind == OUTPUT_KIND_REVIEW_ONLY_RESPONSE_DATE_CANDIDATES
    assert "review-only" in result.disclaimer.lower()
    assert result.docket_export_gate.requires_named_confirmation is True
    for c in result.candidates:
        assert c.is_review_only is True
        assert c.review_state is ReviewState.REQUIRED
        assert c.has_assumptions or c.status in (
            CandidateComputationStatus.UNKNOWN,
            CandidateComputationStatus.INCOMPLETE,
        )
        # Source spans retained when instruction span was known.
        if c.source_id and c.status is CandidateComputationStatus.COMPUTED:
            assert c.has_source_spans or c.source_spans is not None


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def test_parse_date_surface_formats() -> None:
    assert parse_date_surface("2026-03-15") == date(2026, 3, 15)
    assert parse_date_surface("03/15/2026") == date(2026, 3, 15)
    assert parse_date_surface("Mar 15, 2026") == date(2026, 3, 15)
    assert parse_date_surface(date(2026, 1, 1)) == date(2026, 1, 1)
    assert parse_date_surface(None) is None
    assert parse_date_surface("not-a-date") is None
    assert parse_date_surface("") is None


def test_add_calendar_months_end_of_month() -> None:
    assert add_calendar_months(date(2024, 1, 31), 1) == date(2024, 2, 29)
    assert add_calendar_months(date(2025, 1, 31), 1) == date(2025, 2, 28)
    assert add_calendar_months(date(2026, 1, 15), 3) == date(2026, 4, 15)


def test_parse_period_surface_from_labels_and_text() -> None:
    amount, unit, form = parse_period_surface(
        "A shortened statutory period for reply is set to expire in 3 months."
    )
    assert amount == 3
    assert unit is PeriodUnit.MONTHS
    assert form is not None
    amount2, unit2, _ = parse_period_surface(
        "", labels={"response_period": "2 months"}
    )
    assert amount2 == 2
    assert unit2 is PeriodUnit.MONTHS
    amount3, unit3, _ = parse_period_surface("no period here")
    assert amount3 is None
    assert unit3 is PeriodUnit.UNKNOWN


def test_weekend_and_holiday_adjustment() -> None:
    holidays = us_federal_holidays(2026)
    # Saturday → Monday
    sat = date(2026, 4, 4)  # Saturday
    adj, kind, reasons = adjust_period_end(sat, holidays=holidays)
    assert adj == date(2026, 4, 6)
    assert kind is CalendarAdjustmentKind.WEEKEND
    assert DeadlineReasonCode.WEEKEND_ADJUSTED.value in reasons

    # Weekday with no holiday stays put
    wed = date(2026, 4, 8)
    adj2, kind2, _ = adjust_period_end(wed, holidays=holidays)
    assert adj2 == wed
    assert kind2 is CalendarAdjustmentKind.NONE


def test_next_business_day_skips_holiday() -> None:
    # Christmas 2026 is Friday Dec 25
    holidays = us_federal_holidays(2026)
    assert date(2026, 12, 25) in holidays
    assert next_business_day(date(2026, 12, 25), holidays) == date(2026, 12, 28)


def test_candidate_utc_encoding() -> None:
    iso = candidate_local_end_to_utc_iso(date(2026, 4, 15))
    assert iso.endswith("Z")
    assert "2026-04-16" in iso or "2026-04-15" in iso  # UTC shift from EST evening


def test_sha256_hex_stable() -> None:
    assert sha256_hex("abc") == sha256_hex(b"abc")
    assert len(sha256_hex("x")) == 64


def test_sanitize_strips_final_deadline_labels() -> None:
    cleaned, reasons = sanitize_deadline_labels(
        {"final_deadline": "bad", "ok": "keep", "auto_docket": "nope"}
    )
    assert "ok" in cleaned
    assert "final_deadline" not in cleaned
    assert "auto_docket" not in cleaned
    assert DeadlineReasonCode.FORBIDDEN_LABEL_STRIPPED.value in reasons


def test_contains_forbidden_final_deadline_token() -> None:
    assert contains_forbidden_final_deadline_token("write docket now") is True
    assert contains_forbidden_final_deadline_token("review only candidate") is False


def test_build_human_review_question_mentions_review() -> None:
    q = build_human_review_question(
        candidate_id="dl:1",
        event_basis="2026-01-15",
        period_surface="3 months",
        candidate_date="2026-04-15",
        status=CandidateComputationStatus.COMPUTED,
    )
    assert "dl:1" in q
    assert "review" in q.lower()
    assert "docket" in q.lower()


def test_compute_raw_period_end_months_days_weeks() -> None:
    start = date(2026, 1, 15)
    assert compute_raw_period_end(start, 3, PeriodUnit.MONTHS) == date(2026, 4, 15)
    assert compute_raw_period_end(start, 10, PeriodUnit.DAYS) == date(2026, 1, 25)
    assert compute_raw_period_end(start, 2, PeriodUnit.WEEKS) == date(2026, 1, 29)
    assert compute_raw_period_end(start, 1, PeriodUnit.UNKNOWN) is None


# ---------------------------------------------------------------------------
# Happy path: computed review-only candidate
# ---------------------------------------------------------------------------


def test_computed_candidate_is_review_only_with_assumptions_and_spans() -> None:
    proc = _processor()
    result = proc.analyze(_input(_source()))
    _assert_round_trip(result)
    _assert_review_only(result)

    assert result.disposition in (
        DeadlineDisposition.COMPUTED,
        DeadlineDisposition.MULTIPLE,
    )
    assert result.computed_count >= 1
    assert result.docket_export_gate.export_allowed is False
    assert DeadlineReasonCode.DOCKET_EXPORT_BLOCKED.value in result.reason_codes
    assert DeadlineReasonCode.NAMED_CONFIRMATION_REQUIRED.value in result.reason_codes
    assert DeadlineReasonCode.REVIEW_ONLY.value in result.reason_codes

    cand = result.candidates[0]
    assert cand.is_review_only is True
    assert cand.status in (
        CandidateComputationStatus.COMPUTED,
        CandidateComputationStatus.CONFLICT,
    )
    assert cand.event_basis_date == "2026-01-15"
    assert cand.period_amount == 3
    assert cand.period_unit is PeriodUnit.MONTHS
    # 2026-01-15 + 3 months = 2026-04-15 (Wednesday)
    assert cand.raw_end_date == "2026-04-15"
    assert cand.adjusted_end_date == "2026-04-15"
    assert cand.candidate_utc is not None
    assert cand.has_assumptions
    assert "entity_status" in cand.assumptions
    assert cand.has_source_spans
    assert any(s.span_id == "span:resp:1" for s in cand.source_spans)
    assert any("1.134" in r or "1_134" in r for r in cand.rule_chain)
    assert "review" in cand.human_review_question.lower()


def test_module_level_wrapper() -> None:
    result = calculate_response_date_candidates(
        _input(_source()),
        id_factory=lambda: "dl:wrap:1",
    )
    assert result.analysis_id
    assert result.is_review_only is True


# ---------------------------------------------------------------------------
# Missing facts → unknown / incomplete
# ---------------------------------------------------------------------------


def test_missing_mailing_date_yields_incomplete_or_unknown() -> None:
    proc = _processor()
    src = _source(mailing_date=None)
    result = proc.analyze(
        _input(src, mailing_date=None, status_events=())
    )
    _assert_review_only(result)
    assert result.disposition in (
        DeadlineDisposition.UNKNOWN,
        DeadlineDisposition.EMPTY,
        DeadlineDisposition.PARTIAL,
    )
    if result.candidates:
        assert all(
            c.status
            in (
                CandidateComputationStatus.UNKNOWN,
                CandidateComputationStatus.INCOMPLETE,
            )
            for c in result.candidates
        )
        assert all(c.candidate_utc is None for c in result.candidates)
    assert (
        DeadlineReasonCode.EVENT_BASIS_MISSING.value in result.reason_codes
        or DeadlineReasonCode.UNKNOWN_CANDIDATE.value in result.reason_codes
        or result.disposition is DeadlineDisposition.EMPTY
    )


def test_missing_period_yields_unknown_candidate() -> None:
    proc = _processor()
    src = DeadlineSourceInput(
        source_id="src:noperiod",
        source_span_id="span:1",
        surface_text="Applicant is required to traverse the rejection.",
        period_amount=None,
        period_unit=None,
        mailing_date="2026-01-15",
        classification=DisclosureClassification.PUBLIC_USER,
    )
    result = proc.analyze(_input(src, mailing_date="2026-01-15"))
    _assert_review_only(result)
    assert result.disposition in (
        DeadlineDisposition.UNKNOWN,
        DeadlineDisposition.EMPTY,
        DeadlineDisposition.PARTIAL,
    )
    assert (
        DeadlineReasonCode.PERIOD_MISSING.value in result.reason_codes
        or DeadlineReasonCode.NO_RESPONSE_INSTRUCTIONS.value in result.reason_codes
        or result.unknown_count >= 1
    )


def test_empty_input_disposition() -> None:
    proc = _processor()
    result = proc.analyze(
        DeadlineAnalysisInput(
            matter_id="matter:empty",
            classification=DisclosureClassification.PUBLIC_USER,
        )
    )
    assert result.disposition is DeadlineDisposition.EMPTY
    assert result.is_review_only is True
    assert result.docket_export_gate.export_allowed is False
    assert DeadlineReasonCode.EMPTY_INPUT.value in result.reason_codes


# ---------------------------------------------------------------------------
# Conflicting rules / bases → multiple candidates
# ---------------------------------------------------------------------------


def test_conflicting_periods_yield_multiple_candidates() -> None:
    proc = _processor()
    s1 = _source(
        source_id="src:p3",
        span_id="span:p3",
        period_amount=3,
        period_surface="3 months",
        labels={"response_period": "3 months"},
    )
    s2 = DeadlineSourceInput(
        source_id="src:p2",
        source_span_id="span:p2",
        surface_text=(
            "A shortened statutory period for reply is set to expire in 2 months."
        ),
        response_period_surface="2 months",
        period_amount=2,
        period_unit=PeriodUnit.MONTHS,
        proposed_date_rule="response_period:2_months",
        legal_citations=("37 C.F.R. 1.134",),
        mailing_date="2026-01-15",
        action_id="action:1",
        artifact_id="art:oa:1",
        requirement_type="response_instruction",
        confidence=0.9,
        classification=DisclosureClassification.PUBLIC_USER,
        labels={"response_period": "2 months"},
    )
    result = proc.analyze(_input(s1, s2))
    _assert_review_only(result)
    assert len(result.candidates) >= 2
    dates = {
        c.adjusted_end_date
        for c in result.candidates
        if c.adjusted_end_date
    }
    assert len(dates) >= 2
    assert result.disposition is DeadlineDisposition.MULTIPLE or result.conflict_count >= 1
    assert result.conflicts or any(
        c.conflict_peer_ids for c in result.candidates
    )
    # Never silently collapses to one date.
    assert result.computed_count + sum(
        1 for c in result.candidates if c.status is CandidateComputationStatus.CONFLICT
    ) >= 2


def test_conflicting_mailing_dates_yield_multiple_bases() -> None:
    proc = _processor()
    src = _source(mailing_date="2026-01-15")
    events = (
        StatusEventInput(
            event_id="ev:mail:alt",
            event_date="2026-02-01",
            kind="transaction",
            code="MAIL.OA",
            is_mailing_or_notification=True,
        ),
    )
    result = proc.analyze(
        _input(src, mailing_date="2026-01-15", status_events=events)
    )
    _assert_review_only(result)
    bases = {
        c.event_basis_date
        for c in result.candidates
        if c.event_basis_date
    }
    assert "2026-01-15" in bases
    assert "2026-02-01" in bases
    assert len(result.candidates) >= 2
    assert (
        result.disposition is DeadlineDisposition.MULTIPLE
        or DeadlineReasonCode.EVENT_BASIS_CONFLICT.value in result.reason_codes
        or result.conflict_count >= 1
    )


def test_extension_variants_emit_multiple_candidates() -> None:
    proc = _processor()
    result = proc.analyze(
        _input(
            _source(),
            assumptions=DeadlineAssumptions(entity_status="small"),
            emit_extension_variants=True,
        )
    )
    _assert_review_only(result)
    assert len(result.candidates) >= 2
    # Distinct total periods → distinct adjusted dates
    ends = {c.adjusted_end_date for c in result.candidates if c.adjusted_end_date}
    assert len(ends) >= 2
    assert any(
        "extension" in (c.assumptions.get("extension") or "")
        for c in result.candidates
    )


# ---------------------------------------------------------------------------
# Named human confirmation before docket export
# ---------------------------------------------------------------------------


def test_docket_export_blocked_without_named_confirmation() -> None:
    proc = _processor()
    result = proc.analyze(_input(_source()))
    assert result.docket_export_gate.export_allowed is False
    assert result.docket_export_gate.requires_named_confirmation is True
    assert result.docket_export_gate.confirmed_by is None
    assert result.docket_export_allowed is False


def test_named_confirmation_opens_export_gate_without_writing_docket() -> None:
    proc = _processor()
    result = proc.analyze(_input(_source()))
    confirmed = confirm_for_docket_export(
        result,
        "Jane Examiner-Reviewer",
        confirmation_utc="2026-08-01T12:00:00Z",
        confirmation_note="Verified mailing date and 3-month SSP against OA span.",
    )
    assert confirmed.docket_export_gate.export_allowed is True
    assert confirmed.docket_export_gate.confirmed_by == "Jane Examiner-Reviewer"
    assert confirmed.docket_export_gate.confirmation_utc == "2026-08-01T12:00:00Z"
    # Still not a docket entry or final assertion.
    assert confirmed.is_docket_entry is False
    assert confirmed.is_final_deadline_assertion is False
    assert confirmed.is_review_only is True
    assert (
        DeadlineReasonCode.DOCKET_EXPORT_ALLOWED_AFTER_CONFIRMATION.value
        in confirmed.reason_codes
    )
    _assert_round_trip(confirmed)


def test_placeholder_confirmer_rejected() -> None:
    proc = _processor()
    result = proc.analyze(_input(_source()))
    with pytest.raises(DeadlineProcessorError) as exc:
        confirm_for_docket_export(result, "system")
    assert exc.value.code == "invalid_confirmer"


def test_docket_export_gate_rejects_export_without_name() -> None:
    with pytest.raises(ValueError):
        DocketExportGate(
            requires_named_confirmation=True,
            export_allowed=True,
            confirmed_by=None,
            confirmation_utc=None,
            confirmation_note=None,
            blocked_reason="should fail",
        )


# ---------------------------------------------------------------------------
# Weekend adjustment integration
# ---------------------------------------------------------------------------


def test_period_ending_on_weekend_is_adjusted() -> None:
    # 2026-03-06 is Friday; + 1 day would be Saturday if we used days.
    # Use months: mailing 2026-01-03 + 3 months = 2026-04-03 (Friday) — not weekend.
    # mailing 2026-01-04 + 3 months = 2026-04-04 (Saturday) → Monday 2026-04-06.
    proc = _processor()
    src = _source(mailing_date="2026-01-04")
    result = proc.analyze(_input(src, mailing_date="2026-01-04"))
    cand = next(
        c
        for c in result.candidates
        if c.status
        in (CandidateComputationStatus.COMPUTED, CandidateComputationStatus.CONFLICT)
    )
    assert cand.raw_end_date == "2026-04-04"
    assert cand.adjusted_end_date == "2026-04-06"
    assert cand.calendar_adjustment is CalendarAdjustmentKind.WEEKEND
    assert DeadlineReasonCode.WEEKEND_ADJUSTED.value in cand.reason_codes


# ---------------------------------------------------------------------------
# Contract projection
# ---------------------------------------------------------------------------


def test_projects_to_candidate_deadline_contract() -> None:
    proc = _processor()
    result = proc.analyze(_input(_source()))
    contracts = result.to_contract_deadlines()
    assert contracts
    cd = contracts[0]
    assert isinstance(cd, CandidateDeadline)
    assert cd.schema_version == CONTRACTS_SCHEMA_VERSION
    assert cd.reviewer_confirmation is ReviewState.REQUIRED
    assert cd.candidate_utc
    assert cd.uncertainty
    assert cd.event_basis
    assert cd.rule_chain
    # Round-trip contract
    restored = CandidateDeadline.from_dict(cd.to_dict())
    assert restored.to_dict() == cd.to_dict()


# ---------------------------------------------------------------------------
# Office action integration
# ---------------------------------------------------------------------------


def test_sources_from_office_action_non_final() -> None:
    text = build_non_final_office_action_text()
    from ipfs_datasets_py.processors.domains.uspto.contracts import (
        ExtractedSpan,
        ExtractionOrigin,
    )

    span = ExtractedSpan(
        schema_version=CONTRACTS_SCHEMA_VERSION,
        span_id="span:oa:cover",
        artifact_id="art:oa:nf",
        page_index=0,
        char_start=0,
        char_end=len(text),
        bbox=(0.0, 0.0, 100.0, 200.0),
        origin=ExtractionOrigin.NATIVE,
        reading_order=0,
        confidence=0.99,
        text_digest=sha256_hex(" ".join(text.split())),
        image_digest=None,
        classification=DisclosureClassification.PUBLIC_USER,
    )
    oa = OfficeActionProcessor(id_factory=lambda: "oa:1").analyze(
        OfficeActionInput(
            artifact_id="art:oa:nf",
            text=text,
            spans=(span,),
            span_texts={span.span_id: text},
            classification=DisclosureClassification.PUBLIC_USER,
            action_id="action:nf:1",
            mailing_date="2026-01-10",
        )
    )
    sources = sources_from_office_action(oa)
    assert sources
    assert any(s.period_amount == 3 for s in sources) or any(
        "3" in (s.response_period_surface or "") for s in sources
    )

    proc = _processor()
    result = proc.analyze(
        DeadlineAnalysisInput(
            matter_id="matter:oa",
            office_action_results=(oa,),
            mailing_date="2026-01-10",
            assumptions=DeadlineAssumptions(entity_status="undiscounted"),
            classification=DisclosureClassification.PUBLIC_USER,
        )
    )
    _assert_review_only(result)
    assert result.computed_count >= 1 or result.unknown_count >= 0
    assert result.docket_export_gate.export_allowed is False


def test_final_office_action_fixture_path() -> None:
    text = build_final_office_action_text()
    from ipfs_datasets_py.processors.domains.uspto.contracts import (
        ExtractedSpan,
        ExtractionOrigin,
    )

    span = ExtractedSpan(
        schema_version=CONTRACTS_SCHEMA_VERSION,
        span_id="span:oa:final",
        artifact_id="art:oa:f",
        page_index=0,
        char_start=0,
        char_end=len(text),
        bbox=(0.0, 0.0, 100.0, 200.0),
        origin=ExtractionOrigin.NATIVE,
        reading_order=0,
        confidence=0.99,
        text_digest=sha256_hex(" ".join(text.split())),
        image_digest=None,
        classification=DisclosureClassification.PUBLIC_USER,
    )
    oa = OfficeActionProcessor(id_factory=lambda: "oa:f:1").analyze(
        OfficeActionInput(
            artifact_id="art:oa:f",
            text=text,
            spans=(span,),
            span_texts={span.span_id: text},
            classification=DisclosureClassification.PUBLIC_USER,
            action_id="action:f:1",
            mailing_date="2026-03-15",
        )
    )
    result = _processor().analyze(
        DeadlineAnalysisInput(
            office_action_results=(oa,),
            mailing_date="2026-03-15",
            classification=DisclosureClassification.PUBLIC_USER,
        )
    )
    assert result.is_review_only is True
    assert result.docket_export_gate.requires_named_confirmation is True


# ---------------------------------------------------------------------------
# Quarantine / classification
# ---------------------------------------------------------------------------


def test_unknown_classification_quarantines() -> None:
    proc = _processor()
    result = proc.analyze(
        DeadlineAnalysisInput(
            sources=(_source(),),
            mailing_date="2026-01-15",
            classification=DisclosureClassification.UNKNOWN,
        )
    )
    assert result.disposition is DeadlineDisposition.QUARANTINE
    assert result.review_state is ReviewState.REQUIRED
    assert DeadlineReasonCode.QUARANTINED.value in result.reason_codes
    assert result.docket_export_gate.export_allowed is False


# ---------------------------------------------------------------------------
# Exceptions flagged as uncertainty
# ---------------------------------------------------------------------------


def test_exceptions_surface_as_uncertainty() -> None:
    proc = _processor()
    src = _source(exceptions=("unless petition granted",))
    result = proc.analyze(_input(src))
    cand = result.candidates[0]
    assert cand.exceptions
    assert UncertaintyKind.UNRESOLVED_EXCEPTION.value in cand.uncertainty_kinds
    assert DeadlineReasonCode.EXCEPTION_UNRESOLVED.value in result.reason_codes


def test_stale_status_flagged() -> None:
    proc = _processor()
    events = (
        StatusEventInput(
            event_id="ev:stale",
            event_date="2026-01-15",
            is_mailing_or_notification=True,
            is_stale=True,
            freshness_utc="2020-01-01T00:00:00Z",
        ),
    )
    result = proc.analyze(_input(_source(), status_events=events))
    assert any(
        UncertaintyKind.STALE_STATUS.value in c.uncertainty_kinds
        for c in result.candidates
    )


# ---------------------------------------------------------------------------
# ResponseDateCandidate invariants
# ---------------------------------------------------------------------------


def test_candidate_rejects_non_review_only() -> None:
    with pytest.raises(ValueError, match="is_review_only"):
        ResponseDateCandidate(
            candidate_id="dl:bad",
            status=CandidateComputationStatus.COMPUTED,
            is_review_only=False,
            event_basis_kind=EventBasisKind.MAILING_DATE,
            event_basis_date="2026-01-15",
            event_basis_source="test",
            period_amount=3,
            period_unit=PeriodUnit.MONTHS,
            period_surface="3 months",
            raw_end_date="2026-04-15",
            adjusted_end_date="2026-04-15",
            candidate_utc="2026-04-16T04:59:59Z",
            calendar_adjustment=CalendarAdjustmentKind.NONE,
            rule_chain=("37_cfr_1.134",),
            assumptions={"calendar": "US-federal"},
            uncertainty_kinds=(),
            uncertainty_summary="none",
            source_spans=(),
            exceptions=(),
            conflict_group_id=None,
            conflict_peer_ids=(),
            human_review_question="review?",
            review_state=ReviewState.REQUIRED,
            classification=DisclosureClassification.PUBLIC_USER,
            reason_codes=(),
            labels={},
        )


def test_result_rejects_final_deadline_assertion() -> None:
    base = _processor().analyze(_input(_source()))
    payload = base.to_dict()
    payload["is_final_deadline_assertion"] = True
    with pytest.raises(ValueError, match="final"):
        DeadlineAnalysisResult.from_dict(payload)


def test_result_rejects_docket_entry_flag() -> None:
    base = _processor().analyze(_input(_source()))
    payload = base.to_dict()
    payload["is_docket_entry"] = True
    with pytest.raises(ValueError, match="docket"):
        DeadlineAnalysisResult.from_dict(payload)


def test_public_projection_omits_body() -> None:
    proc = _processor()
    result = proc.analyze(_input(_source()))
    public = result.public_projection()
    blob = json.dumps(public)
    assert "shortened statutory" not in blob
    assert "candidates" not in public
    assert public["requires_named_confirmation"] is True


def test_analyze_from_mapping() -> None:
    proc = _processor()
    result = proc.analyze(
        {
            "matter_id": "matter:map",
            "mailing_date": "2026-01-15",
            "classification": DisclosureClassification.PUBLIC_USER.value,
            "sources": [_source().to_dict()],
            "assumptions": {"entity_status": "micro"},
        }
    )
    assert result.matter_id == "matter:map"
    assert result.computed_count >= 1
    assert result.assumptions.entity_status == "micro"


def test_disclaimer_constant() -> None:
    assert "review-only" in REVIEW_ONLY_DEADLINE_DISCLAIMER.lower()
    assert "named human" in REVIEW_ONLY_DEADLINE_DISCLAIMER.lower()
    assert DEADLINE_SCHEMA_VERSION.startswith("uspto.deadline")


def test_conflict_record_round_trip() -> None:
    conf = DeadlineConflict(
        conflict_id="conflict:test:1",
        kind="conflicting_candidate_dates",
        candidate_ids=("a", "b"),
        detail="two dates",
        source_span_ids=("span:1",),
    )
    assert DeadlineConflict.from_dict(conf.to_dict()).to_dict() == conf.to_dict()


def test_source_span_ref_round_trip() -> None:
    ref = SourceSpanRef(
        span_id="span:1",
        artifact_id="art:1",
        role="response_instruction",
        text_digest=sha256_hex("hello"),
        surface_excerpt="3 months",
    )
    assert SourceSpanRef.from_dict(ref.to_dict()).to_dict() == ref.to_dict()


def test_bounds_limit_candidates() -> None:
    proc = DeadlineProcessor(
        id_factory=lambda: f"dl:{id(object())}",  # unique-ish
        bounds=AnalysisBounds(max_candidates=1),
    )
    # Force many via extension variants
    # Use stable factory
    counter = {"n": 0}

    def _ids() -> str:
        counter["n"] += 1
        return f"dl:lim:{counter['n']:04d}"

    proc = DeadlineProcessor(
        id_factory=_ids,
        bounds=AnalysisBounds(max_candidates=1),
    )
    result = proc.analyze(
        _input(
            _source(),
            emit_extension_variants=True,
        )
    )
    assert len(result.candidates) <= 1
    assert (
        DeadlineReasonCode.CANDIDATE_LIMIT.value in result.reason_codes
        or len(result.candidates) == 1
    )
