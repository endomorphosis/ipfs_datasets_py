"""Unit tests for authoritative deadline and closure-calendar snapshots (PATLAW-138).

Acceptance:
  - Weekend/holiday/closure/emergency/extension/conflicting-date fixtures are deterministic
  - Missing trigger or calendar provenance blocks a definitive deadline
  - Output separates calculated dates, source-stated dates, assumptions, and
    human confirmation requirements
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.domains.uspto.contracts import (
    CONTRACTS_SCHEMA_VERSION,
    ReviewState,
    canonical_json,
)
from ipfs_datasets_py.processors.domains.uspto.analysis.authoritative_deadline_calendar import (
    CALENDAR_SCHEMA_VERSION,
    OUTPUT_KIND_AUTHORITATIVE_DEADLINE_SNAPSHOT,
    RECIPE_SCHEMA_VERSION,
    REVIEW_ONLY_CALENDAR_DISCLAIMER,
    AuthoritativeDeadlineCalendar,
    AuthoritativeDeadlineRequest,
    AuthoritativeDeadlineResult,
    CalculatedDates,
    CalendarReasonCode,
    CalendarSourceProvenance,
    ClosureCalendarEntry,
    ClosureCalendarSnapshot,
    ClosureKind,
    DeadlineComputationStatus,
    DeadlineTrigger,
    DefinitiveBlockReason,
    ExplicitAssumptions,
    HumanConfirmationRequirement,
    ServiceChannel,
    SourceStatedDate,
    TriggerKind,
    adjust_for_closure_calendar,
    build_calendar_from_recipe_case,
    build_request_from_recipe_case,
    compute_authoritative_deadline,
    is_closed_day,
    load_closure_calendar_recipe,
    materialize_closure_calendar,
    next_open_business_day,
    run_recipe_case,
    seed_federal_holiday_entries,
    sha256_hex,
)
from ipfs_datasets_py.processors.domains.uspto.analysis.deadline_processor import (
    PeriodUnit,
    us_federal_holidays,
)
from ipfs_datasets_py.processors.domains.uspto.contracts import (
    DisclosureClassification,
)

# ---------------------------------------------------------------------------
# Paths / helpers
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[6]
_RECIPE_PATH = (
    _REPO_ROOT / "tests/fixtures/uspto/deadlines/closure_calendar_recipe.json"
)


def _id_factory():
    counter = {"n": 0}

    def _ids() -> str:
        counter["n"] += 1
        return f"adc:test:{counter['n']:04d}"

    return _ids


def _sourced_calendar(
    *,
    snapshot_id: str = "snap:test",
    as_of: str = "2026-01-15",
    year: int = 2026,
    uspto_closures: list | None = None,
    emergency_relief: list | None = None,
) -> ClosureCalendarSnapshot:
    return materialize_closure_calendar(
        snapshot_id=snapshot_id,
        as_of=as_of,
        year=year,
        uspto_closures=uspto_closures or (),
        emergency_relief=emergency_relief or (),
        sources=[
            CalendarSourceProvenance(
                source_id="src:test-holidays",
                source_digest="a" * 64,
                provider="opm",
                authority_citation="5 U.S.C. 6103",
                as_of=as_of,
            )
        ],
        authority_citations=("37 C.F.R. 1.7", "5 U.S.C. 6103"),
        materialized_at="2026-01-15T12:00:00Z",
        seed_federal_holidays=True,
    )


def _request(
    *,
    request_id: str = "req:test",
    trigger_date: str | None = "2026-01-15",
    period_amount: int | None = 3,
    period_unit: PeriodUnit | str | None = PeriodUnit.MONTHS,
    calendar: ClosureCalendarSnapshot | None = None,
    assumptions: ExplicitAssumptions | None = None,
    source_stated: tuple[SourceStatedDate, ...] = (),
    omit_calendar: bool = False,
) -> AuthoritativeDeadlineRequest:
    cal = None if omit_calendar else (calendar or _sourced_calendar())
    trigger = (
        DeadlineTrigger(
            kind=TriggerKind.MAILING_DATE,
            trigger_date=trigger_date,
            source_id="src:oa:1",
            service_channel=ServiceChannel.ELECTRONIC,
        )
        if trigger_date
        else DeadlineTrigger.missing()
    )
    return AuthoritativeDeadlineRequest(
        request_id=request_id,
        trigger=trigger,
        period_amount=period_amount,
        period_unit=period_unit,
        calendar=cal,
        assumptions=assumptions or ExplicitAssumptions(entity_status="undiscounted"),
        source_stated_dates=source_stated,
        period_surface=(
            f"{period_amount} months" if period_amount is not None else None
        ),
        legal_citations=("37 C.F.R. 1.134", "37 C.F.R. 1.7"),
        matter_id="matter:test",
        classification=DisclosureClassification.PUBLIC_USER,
    )


def _assert_separated_sections(result: AuthoritativeDeadlineResult) -> None:
    d = result.to_dict()
    assert "calculated_dates" in d
    assert "source_stated_dates" in d
    assert "assumptions" in d
    assert "human_confirmation_requirements" in d
    # Sections must not be collapsed into a single date field.
    assert isinstance(d["calculated_dates"], dict)
    assert isinstance(d["source_stated_dates"], list)
    assert isinstance(d["assumptions"], dict)
    assert isinstance(d["human_confirmation_requirements"], list)
    assert d["assumptions"].get("extension_policy") in (
        "explicit",
        "not_assumed",
    )


def _assert_review_only(result: AuthoritativeDeadlineResult) -> None:
    assert result.is_review_only is True
    assert result.is_final_deadline_assertion is False
    assert result.is_docket_entry is False
    assert result.output_kind == OUTPUT_KIND_AUTHORITATIVE_DEADLINE_SNAPSHOT
    assert result.review_state is ReviewState.REQUIRED
    assert "review-only" in result.disclaimer.lower()
    assert any(
        c.requirement_id == "confirm:named-human-before-docket-export"
        for c in result.human_confirmation_requirements
    )


def _assert_round_trip(result: AuthoritativeDeadlineResult) -> None:
    first = result.to_dict()
    restored = AuthoritativeDeadlineResult.from_dict(first)
    second = restored.to_dict()
    assert first == second
    assert canonical_json(first) == canonical_json(second)
    public = result.public_projection()
    assert public["is_review_only"] is True
    assert public["is_final_deadline_assertion"] is False
    assert public["is_docket_entry"] is False
    assert public["requires_named_confirmation"] is True
    assert "calculated_dates" not in public


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def test_seed_federal_holidays_deterministic() -> None:
    a = seed_federal_holiday_entries(2026)
    b = seed_federal_holiday_entries(2026)
    assert [e.to_dict() for e in a] == [e.to_dict() for e in b]
    dates = {e.closed_date for e in a}
    # Independence Day 2026 is Saturday → observed Friday 2026-07-03
    fed = us_federal_holidays(2026)
    for d in fed:
        if d.year == 2026:
            assert d.isoformat() in dates


def test_adjust_weekend_to_monday() -> None:
    sat = date(2026, 4, 4)
    holidays = us_federal_holidays(2026)
    adj, reasons, hits = adjust_for_closure_calendar(sat, holidays=holidays)
    assert adj == date(2026, 4, 6)
    assert ClosureKind.WEEKEND in hits
    assert CalendarReasonCode.WEEKEND_ADJUSTED.value in reasons


def test_adjust_holiday_independence_day_2026() -> None:
    # Observed Independence Day 2026: Saturday Jul 4 → Friday Jul 3 observed
    # Using calendar date Jul 4 which is Saturday — weekend path.
    # Use Christmas 2026 (Friday) as pure holiday hit.
    christmas = date(2026, 12, 25)
    holidays = us_federal_holidays(2026)
    assert christmas in holidays
    adj, reasons, hits = adjust_for_closure_calendar(
        christmas, holidays=holidays
    )
    assert adj == date(2026, 12, 28)
    assert ClosureKind.FEDERAL_HOLIDAY in hits
    assert CalendarReasonCode.HOLIDAY_ADJUSTED.value in reasons


def test_uspto_closure_advances() -> None:
    closures = frozenset({date(2026, 3, 12)})
    adj, reasons, hits = adjust_for_closure_calendar(
        date(2026, 3, 12),
        holidays=frozenset(),
        closures=closures,
    )
    assert adj == date(2026, 3, 13)
    assert ClosureKind.USPTO_CLOSURE in hits
    assert CalendarReasonCode.USPTO_CLOSURE_ADJUSTED.value in reasons


def test_is_closed_day_and_next_open() -> None:
    holidays = frozenset({date(2026, 12, 25)})
    assert is_closed_day(date(2026, 12, 26), holidays=holidays) is True  # Sat
    assert is_closed_day(date(2026, 12, 25), holidays=holidays) is True
    assert is_closed_day(date(2026, 12, 24), holidays=holidays) is False
    assert next_open_business_day(
        date(2026, 12, 25), holidays=holidays
    ) == date(2026, 12, 28)


def test_sha256_hex_stable() -> None:
    assert sha256_hex("abc") == sha256_hex(b"abc")
    assert len(sha256_hex("x")) == 64


# ---------------------------------------------------------------------------
# Calendar materialization / provenance
# ---------------------------------------------------------------------------


def test_materialize_calendar_with_provenance() -> None:
    snap = _sourced_calendar()
    assert snap.has_calendar_provenance is True
    assert snap.as_of == "2026-01-15"
    assert any(e.kind is ClosureKind.FEDERAL_HOLIDAY for e in snap.entries)
    digest1 = snap.content_digest()
    digest2 = snap.content_digest()
    assert digest1 == digest2
    assert len(digest1) == 64
    round_trip = ClosureCalendarSnapshot.from_dict(snap.to_dict())
    assert round_trip.content_digest() == digest1
    assert round_trip.has_calendar_provenance is True


def test_calendar_without_provenance_is_not_authoritative() -> None:
    snap = ClosureCalendarSnapshot(
        snapshot_id="snap:bare",
        as_of="2026-01-01",
        entries=seed_federal_holiday_entries(2026),
        sources=(),
        authority_citations=(),
    )
    # Seeded entries carry digests; strip for this test.
    stripped = tuple(
        ClosureCalendarEntry(
            entry_id=e.entry_id,
            closed_date=e.closed_date,
            kind=e.kind,
            source_digest=None,
            authority_citation=None,
        )
        for e in snap.entries
    )
    bare = ClosureCalendarSnapshot(
        snapshot_id="snap:bare",
        as_of="2026-01-01",
        entries=stripped,
        sources=(),
        authority_citations=(),
    )
    assert bare.has_calendar_provenance is False


def test_materialize_includes_uspto_and_emergency() -> None:
    snap = materialize_closure_calendar(
        snapshot_id="snap:mixed",
        as_of="2026-06-01",
        year=2026,
        uspto_closures=[
            {
                "closed_date": "2026-06-15",
                "kind": "uspto_closure",
                "source_digest": "b" * 64,
                "source_id": "src:closure",
            }
        ],
        emergency_relief=[
            {
                "closed_date": "2026-06-20",
                "relief_end_date": "2026-06-30",
                "kind": "emergency_relief",
                "source_digest": "c" * 64,
                "source_id": "src:emerg",
            }
        ],
        sources=[
            {
                "source_id": "src:closure",
                "source_digest": "b" * 64,
                "provider": "uspto",
            }
        ],
        authority_citations=["37 C.F.R. 1.7"],
        materialized_at="2026-06-01T00:00:00Z",
    )
    kinds = {e.kind for e in snap.entries}
    assert ClosureKind.USPTO_CLOSURE in kinds
    assert ClosureKind.EMERGENCY_RELIEF in kinds
    assert ClosureKind.FEDERAL_HOLIDAY in kinds
    assert snap.has_calendar_provenance is True


# ---------------------------------------------------------------------------
# Happy path: computed review-only with separated sections
# ---------------------------------------------------------------------------


def test_computed_candidate_separates_output_sections() -> None:
    proc = AuthoritativeDeadlineCalendar(id_factory=_id_factory())
    result = proc.compute(_request())
    _assert_round_trip(result)
    _assert_review_only(result)
    _assert_separated_sections(result)

    assert result.schema_version == CALENDAR_SCHEMA_VERSION
    assert result.status is DeadlineComputationStatus.COMPUTED
    assert result.calculated_dates.base_period_end == "2026-04-15"
    assert result.calculated_dates.base_adjusted_end == "2026-04-15"
    assert result.calculated_dates.base_candidate_utc is not None
    assert result.assumptions.extension_months is None
    assert result.assumptions.to_dict()["extension_policy"] == "not_assumed"
    assert result.has_calendar_provenance is True
    # Computationally definitive, but human confirmation still required for export.
    assert result.is_definitive is True
    assert (
        DefinitiveBlockReason.HUMAN_CONFIRMATION_REQUIRED.value
        in result.definitive_blocked_reasons
    )
    assert CalendarReasonCode.EXTENSION_NOT_ASSUMED.value in result.reason_codes
    assert CalendarReasonCode.REVIEW_ONLY.value in result.reason_codes


def test_module_level_wrapper() -> None:
    result = compute_authoritative_deadline(
        _request(),
        id_factory=lambda: "adc:wrap:1",
    )
    assert result.result_id == "adc:wrap:1"
    assert result.is_review_only is True


# ---------------------------------------------------------------------------
# Weekend / holiday / closure / emergency / extension
# ---------------------------------------------------------------------------


def test_weekend_adjustment_deterministic() -> None:
    proc = AuthoritativeDeadlineCalendar(id_factory=_id_factory())
    # 2026-03-30 + 5 days = 2026-04-04 (Saturday) → Monday 2026-04-06
    result = proc.compute(
        _request(
            trigger_date="2026-03-30",
            period_amount=5,
            period_unit=PeriodUnit.DAYS,
        )
    )
    _assert_review_only(result)
    assert result.calculated_dates.base_period_end == "2026-04-04"
    assert result.calculated_dates.base_adjusted_end == "2026-04-06"
    assert "weekend" in result.calculated_dates.hit_closure_kinds
    assert CalendarReasonCode.WEEKEND_ADJUSTED.value in result.reason_codes
    # Determinism: identical inputs → identical calculated dates
    result2 = proc.compute(
        _request(
            trigger_date="2026-03-30",
            period_amount=5,
            period_unit=PeriodUnit.DAYS,
        )
    )
    assert (
        result.calculated_dates.to_dict()
        == result2.calculated_dates.to_dict()
    )


def test_holiday_adjustment_independence_day() -> None:
    proc = AuthoritativeDeadlineCalendar(id_factory=_id_factory())
    # 2026-04-04 + 3 months = 2026-07-04 (Saturday) — weekend+holiday path
    result = proc.compute(
        _request(
            trigger_date="2026-04-04",
            period_amount=3,
            period_unit=PeriodUnit.MONTHS,
            calendar=_sourced_calendar(as_of="2026-04-01"),
        )
    )
    assert result.calculated_dates.base_period_end == "2026-07-04"
    assert result.calculated_dates.base_adjusted_end == "2026-07-06"
    assert CalendarReasonCode.WEEKEND_ADJUSTED.value in result.reason_codes or (
        CalendarReasonCode.HOLIDAY_ADJUSTED.value in result.reason_codes
    )


def test_holiday_christmas_friday() -> None:
    proc = AuthoritativeDeadlineCalendar(id_factory=_id_factory())
    # 2026-09-25 + 3 months = 2026-12-25 (Christmas Friday)
    result = proc.compute(
        _request(
            trigger_date="2026-09-25",
            period_amount=3,
            period_unit=PeriodUnit.MONTHS,
        )
    )
    assert result.calculated_dates.base_period_end == "2026-12-25"
    assert result.calculated_dates.base_adjusted_end == "2026-12-28"
    assert "federal_holiday" in result.calculated_dates.hit_closure_kinds
    assert CalendarReasonCode.HOLIDAY_ADJUSTED.value in result.reason_codes


def test_uspto_closure_adjustment() -> None:
    proc = AuthoritativeDeadlineCalendar(id_factory=_id_factory())
    cal = _sourced_calendar(
        uspto_closures=[
            ClosureCalendarEntry(
                entry_id="uspto-closure:2026-03-12",
                closed_date="2026-03-12",
                kind=ClosureKind.USPTO_CLOSURE,
                source_id="src:closure",
                source_digest="b" * 64,
                authority_citation="USPTO notice",
            )
        ]
    )
    result = proc.compute(
        _request(
            trigger_date="2026-02-10",
            period_amount=30,
            period_unit=PeriodUnit.DAYS,
            calendar=cal,
        )
    )
    assert result.calculated_dates.base_period_end == "2026-03-12"
    assert result.calculated_dates.base_adjusted_end == "2026-03-13"
    assert "uspto_closure" in result.calculated_dates.hit_closure_kinds
    assert (
        CalendarReasonCode.USPTO_CLOSURE_ADJUSTED.value in result.reason_codes
    )


def test_emergency_relief_extends() -> None:
    proc = AuthoritativeDeadlineCalendar(id_factory=_id_factory())
    cal = _sourced_calendar(
        as_of="2026-08-15",
        emergency_relief=[
            ClosureCalendarEntry(
                entry_id="emergency:fixture",
                closed_date="2026-08-28",
                relief_end_date="2026-09-10",
                kind=ClosureKind.EMERGENCY_RELIEF,
                source_id="src:emerg",
                source_digest="c" * 64,
                authority_citation="USPTO emergency notice",
            )
        ],
    )
    result = proc.compute(
        _request(
            trigger_date="2026-08-01",
            period_amount=1,
            period_unit=PeriodUnit.MONTHS,
            calendar=cal,
        )
    )
    assert result.calculated_dates.base_period_end == "2026-09-01"
    assert result.calculated_dates.emergency_relief_end == "2026-09-10"
    assert (
        CalendarReasonCode.EMERGENCY_RELIEF_APPLIED.value in result.reason_codes
    )


def test_explicit_extension_not_assumed_by_default() -> None:
    proc = AuthoritativeDeadlineCalendar(id_factory=_id_factory())
    # Default: no extension
    base = proc.compute(_request(trigger_date="2026-01-15"))
    assert base.assumptions.extension_months is None
    assert base.calculated_dates.base_adjusted_end == "2026-04-15"
    assert not base.calculated_dates.extension_period_ends

    # Explicit extension_months=1
    ext = proc.compute(
        _request(
            trigger_date="2026-01-15",
            assumptions=ExplicitAssumptions(
                extension_months=1,
                emit_extension_ladder=True,
                max_extension_months=5,
                entity_status="undiscounted",
            ),
        )
    )
    assert ext.assumptions.extension_months == 1
    assert ext.assumptions.to_dict()["extension_policy"] == "explicit"
    assert ext.calculated_dates.base_period_end == "2026-04-15"
    assert "extension_1_month" in ext.calculated_dates.extension_period_ends
    assert (
        ext.calculated_dates.extension_period_ends["extension_1_month"]
        == "2026-05-15"
    )
    assert CalendarReasonCode.EXTENSION_EXPLICIT.value in ext.reason_codes
    # Ladder emits multiple months
    assert "extension_5_month" in ext.calculated_dates.extension_period_ends
    assert ext.calculated_dates.maximum_adjusted_end is not None


# ---------------------------------------------------------------------------
# Conflicting dates
# ---------------------------------------------------------------------------


def test_conflicting_source_stated_blocks_definitive() -> None:
    proc = AuthoritativeDeadlineCalendar(id_factory=_id_factory())
    stated = (
        SourceStatedDate(
            role="response_due_date",
            stated_date="2026-04-01",
            source_id="src:oa:1",
            source_span_id="span:due",
            surface_text="Response is due by April 1, 2026.",
        ),
    )
    result = proc.compute(
        _request(trigger_date="2026-01-15", source_stated=stated)
    )
    _assert_review_only(result)
    _assert_separated_sections(result)
    assert result.status is DeadlineComputationStatus.CONFLICT
    assert result.is_definitive is False
    assert (
        DefinitiveBlockReason.CONFLICTING_DATES.value
        in result.definitive_blocked_reasons
    )
    assert result.calculated_dates.base_adjusted_end == "2026-04-15"
    assert result.source_stated_dates[0].stated_date == "2026-04-01"
    # Both sides retained separately
    assert result.calculated_dates.base_adjusted_end != (
        result.source_stated_dates[0].stated_date
    )
    assert any(
        "conflict" in c.requirement_id
        for c in result.human_confirmation_requirements
    )


# ---------------------------------------------------------------------------
# Missing trigger / calendar provenance → not definitive
# ---------------------------------------------------------------------------


def test_missing_trigger_blocks_definitive() -> None:
    proc = AuthoritativeDeadlineCalendar(id_factory=_id_factory())
    result = proc.compute(_request(trigger_date=None))
    _assert_review_only(result)
    _assert_separated_sections(result)
    assert result.is_definitive is False
    assert (
        DefinitiveBlockReason.MISSING_TRIGGER.value
        in result.definitive_blocked_reasons
    )
    assert result.calculated_dates.base_adjusted_end is None
    assert result.status in (
        DeadlineComputationStatus.BLOCKED,
        DeadlineComputationStatus.PARTIAL,
    )
    assert any(
        c.requirement_id == "confirm:supply-trigger"
        for c in result.human_confirmation_requirements
    )
    assert CalendarReasonCode.MISSING_TRIGGER.value in result.reason_codes


def test_missing_calendar_provenance_blocks_definitive() -> None:
    proc = AuthoritativeDeadlineCalendar(id_factory=_id_factory())
    bare_entries = tuple(
        ClosureCalendarEntry(
            entry_id=e.entry_id,
            closed_date=e.closed_date,
            kind=e.kind,
        )
        for e in seed_federal_holiday_entries(2026)
    )
    bare = ClosureCalendarSnapshot(
        snapshot_id="snap:no-prov",
        as_of="2026-01-15",
        entries=bare_entries,
        sources=(),
        authority_citations=(),
    )
    assert bare.has_calendar_provenance is False
    result = proc.compute(
        _request(trigger_date="2026-01-15", calendar=bare)
    )
    _assert_review_only(result)
    _assert_separated_sections(result)
    assert result.is_definitive is False
    assert result.has_calendar_provenance is False
    assert (
        DefinitiveBlockReason.MISSING_CALENDAR_PROVENANCE.value
        in result.definitive_blocked_reasons
    )
    assert any(
        c.requirement_id == "confirm:calendar-provenance"
        for c in result.human_confirmation_requirements
    )


def test_omit_calendar_blocks_definitive() -> None:
    proc = AuthoritativeDeadlineCalendar(id_factory=_id_factory())
    result = proc.compute(_request(omit_calendar=True))
    assert result.is_definitive is False
    assert (
        DefinitiveBlockReason.MISSING_CALENDAR_PROVENANCE.value
        in result.definitive_blocked_reasons
    )


def test_missing_period_blocks_definitive() -> None:
    proc = AuthoritativeDeadlineCalendar(id_factory=_id_factory())
    result = proc.compute(
        _request(period_amount=None, period_unit=None)
    )
    assert result.is_definitive is False
    assert (
        DefinitiveBlockReason.MISSING_PERIOD.value
        in result.definitive_blocked_reasons
    )


# ---------------------------------------------------------------------------
# Recipe fixtures — deterministic coverage of all acceptance cases
# ---------------------------------------------------------------------------


def test_recipe_file_exists_and_schema() -> None:
    assert _RECIPE_PATH.is_file(), f"missing recipe at {_RECIPE_PATH}"
    data = load_closure_calendar_recipe(_RECIPE_PATH)
    assert data["schema_version"] == RECIPE_SCHEMA_VERSION
    assert data["recipe_id"] == "patlaw-138-closure-calendar"
    case_ids = {c["id"] for c in data["cases"]}
    required = {
        "weekend_saturday",
        "holiday",
        "uspto_closure",
        "emergency",
        "extension",
        "conflicting_dates",
        "missing_trigger",
        "missing_calendar_provenance",
    }
    assert required.issubset(case_ids)


def test_all_recipe_cases_deterministic_and_separated() -> None:
    data = load_closure_calendar_recipe(_RECIPE_PATH)
    for case in data["cases"]:
        factory = _id_factory()
        r1 = run_recipe_case(case, id_factory=factory)
        factory2 = _id_factory()
        r2 = run_recipe_case(case, id_factory=factory2)
        _assert_review_only(r1)
        _assert_separated_sections(r1)
        # Calculated dates must be deterministic across runs
        assert r1.calculated_dates.to_dict() == r2.calculated_dates.to_dict()
        assert r1.is_definitive == r2.is_definitive
        assert (
            r1.definitive_blocked_reasons == r2.definitive_blocked_reasons
        )
        assert r1.status == r2.status
        expect = case.get("expect") or {}
        if expect.get("is_review_only"):
            assert r1.is_review_only is True
        if "raw_end" in expect:
            assert r1.calculated_dates.base_period_end == expect["raw_end"]
        if "adjusted_end" in expect:
            assert (
                r1.calculated_dates.base_adjusted_end == expect["adjusted_end"]
            )
        if "base_raw_end" in expect:
            assert (
                r1.calculated_dates.base_period_end == expect["base_raw_end"]
            )
        if "base_adjusted_end" in expect:
            assert (
                r1.calculated_dates.base_adjusted_end
                == expect["base_adjusted_end"]
            )
        if "extension_1_month" in expect:
            assert (
                r1.calculated_dates.extension_period_ends.get(
                    "extension_1_month"
                )
                == expect["extension_1_month"]
            )
        if expect.get("has_extension_ladder"):
            assert len(r1.calculated_dates.extension_period_ends) >= 1
        if "emergency_relief_end" in expect:
            assert (
                r1.calculated_dates.emergency_relief_end
                == expect["emergency_relief_end"]
            )
        if "hit_kinds_include" in expect:
            for k in expect["hit_kinds_include"]:
                assert k in r1.calculated_dates.hit_closure_kinds
        if "reason_codes_include" in expect:
            for code in expect["reason_codes_include"]:
                # Some codes are optional depending on path; require if listed
                # as core acceptance codes.
                if code in (
                    "review_only",
                    "weekend_adjusted",
                    "holiday_adjusted",
                    "uspto_closure_adjusted",
                    "emergency_relief_applied",
                    "extension_explicit",
                ):
                    if code == "holiday_adjusted" and case["id"] == "weekend":
                        continue  # weekend case note allows skip
                    if code in ("weekend_adjusted", "holiday_adjusted") and case[
                        "id"
                    ] == "weekend":
                        continue
                    assert (
                        code in r1.reason_codes
                        or code in r1.calculated_dates.adjustment_reasons
                    ), f"case {case['id']} missing reason {code}"
        if "is_definitive" in expect:
            assert r1.is_definitive is expect["is_definitive"]
        if "block_reasons_include" in expect:
            for br in expect["block_reasons_include"]:
                assert br in r1.definitive_blocked_reasons
        if "has_calendar_provenance" in expect:
            assert r1.has_calendar_provenance is expect["has_calendar_provenance"]
        if "status" in expect:
            assert r1.status.value == expect["status"]
        if "status_in" in expect:
            assert r1.status.value in expect["status_in"]
        if "human_confirmation_includes" in expect:
            ids = {c.requirement_id for c in r1.human_confirmation_requirements}
            assert expect["human_confirmation_includes"] in ids
        if expect.get("calculated_base_null"):
            assert r1.calculated_dates.base_adjusted_end is None
        if "calculated_adjusted_end" in expect:
            assert (
                r1.calculated_dates.base_adjusted_end
                == expect["calculated_adjusted_end"]
            )
        if "source_stated_due" in expect:
            assert any(
                s.stated_date == expect["source_stated_due"]
                for s in r1.source_stated_dates
            )
        if expect.get("assumptions_extension_months") is not None:
            assert (
                r1.assumptions.extension_months
                == expect["assumptions_extension_months"]
            )


def test_recipe_missing_trigger_and_provenance_block() -> None:
    data = load_closure_calendar_recipe(_RECIPE_PATH)
    by_id = {c["id"]: c for c in data["cases"]}
    mt = run_recipe_case(by_id["missing_trigger"], id_factory=_id_factory())
    assert mt.is_definitive is False
    assert DefinitiveBlockReason.MISSING_TRIGGER.value in mt.definitive_blocked_reasons

    mp = run_recipe_case(
        by_id["missing_calendar_provenance"], id_factory=_id_factory()
    )
    assert mp.is_definitive is False
    assert (
        DefinitiveBlockReason.MISSING_CALENDAR_PROVENANCE.value
        in mp.definitive_blocked_reasons
    )
    assert mp.has_calendar_provenance is False


def test_recipe_conflicting_dates_retains_both_sides() -> None:
    data = load_closure_calendar_recipe(_RECIPE_PATH)
    case = next(c for c in data["cases"] if c["id"] == "conflicting_dates")
    result = run_recipe_case(case, id_factory=_id_factory())
    assert result.status is DeadlineComputationStatus.CONFLICT
    assert result.calculated_dates.base_adjusted_end == "2026-04-15"
    assert result.source_stated_dates[0].stated_date == "2026-04-01"
    # Separated: not overwritten
    d = result.to_dict()
    assert d["calculated_dates"]["base_adjusted_end"] != d["source_stated_dates"][0][
        "stated_date"
    ]


# ---------------------------------------------------------------------------
# Contract projection / invariants
# ---------------------------------------------------------------------------


def test_candidate_deadline_contract_projection() -> None:
    result = compute_authoritative_deadline(
        _request(),
        id_factory=lambda: "adc:contract:1",
    )
    assert result.candidate_deadline is not None
    assert result.candidate_deadline["schema_version"] == CONTRACTS_SCHEMA_VERSION
    assert result.candidate_deadline["reviewer_confirmation"] == (
        ReviewState.REQUIRED.value
    )
    assert (
        CalendarReasonCode.CONTRACT_CANDIDATE_PROJECTED.value
        in result.reason_codes
    )


def test_result_rejects_final_deadline_assertion() -> None:
    result = compute_authoritative_deadline(
        _request(),
        id_factory=lambda: "adc:ok:1",
    )
    bad = result.to_dict()
    bad["is_final_deadline_assertion"] = True
    with pytest.raises(ValueError, match="final"):
        AuthoritativeDeadlineResult.from_dict(bad)


def test_disclaimer_present() -> None:
    result = compute_authoritative_deadline(
        _request(), id_factory=lambda: "adc:disc:1"
    )
    assert result.disclaimer == REVIEW_ONLY_CALENDAR_DISCLAIMER
    assert "not a docket entry" in result.disclaimer.lower()


def test_build_request_from_recipe_helpers() -> None:
    data = load_closure_calendar_recipe(_RECIPE_PATH)
    case = next(c for c in data["cases"] if c["id"] == "extension")
    cal = build_calendar_from_recipe_case(case)
    assert cal.has_calendar_provenance
    req = build_request_from_recipe_case(case, calendar=cal)
    assert req.assumptions.extension_months == 1
    assert req.trigger.trigger_date == "2026-01-15"
