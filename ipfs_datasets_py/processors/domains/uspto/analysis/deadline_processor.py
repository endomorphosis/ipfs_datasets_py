"""Calculate review-only response-date candidates (PATLAW-044).

Builds **candidate** response dates from:

* mailing / notification event basis
* cited rule chain (e.g. 37 C.F.R. 1.134, 1.136(a), 1.7)
* response periods extracted from government instruction spans
* calendar / time zone and weekend / federal-holiday adjustment
* entity-status, extension, and fee assumptions
* unresolved exceptions and upstream status freshness

Design invariants
-----------------
* Every candidate is labeled **review-only** with explicit assumptions and
  source spans. This module never writes docket entries or asserts a final
  deadline.
* Missing facts yield ``unknown`` candidates (or empty computed set with
  disposition ``unknown`` / ``review``).
* Conflicting rules or event bases yield **multiple** candidates rather than
  a silent pick.
* **Named human confirmation** is required before any docket export; export
  remains blocked until a non-empty confirmer name is recorded on the gate.
* Body text of office actions is never written to logs or exception messages.

Contract mapping
----------------
Each fully computed candidate projects to
:class:`~ipfs_datasets_py.processors.domains.uspto.contracts.CandidateDeadline`
with ``reviewer_confirmation = REQUIRED`` until a named confirmation is
recorded for export (which still does not mutate docket systems).
"""

from __future__ import annotations

import calendar
import hashlib
import re
import uuid
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from enum import Enum
from types import MappingProxyType
from typing import Any, Callable, Final, Iterable, Mapping, Sequence

from ipfs_datasets_py.processors.domains.uspto.contracts import (
    CONTRACTS_SCHEMA_VERSION,
    CandidateDeadline,
    DisclosureClassification,
    ReviewState,
    canonical_json,
    most_restrictive_classification,
    requires_quarantine,
)
from ipfs_datasets_py.processors.domains.uspto.analysis.office_action_processor import (
    AnalysisCandidate,
    CandidateKind,
    OfficeActionResult,
)
from ipfs_datasets_py.processors.domains.uspto.analysis.requirement_processor import (
    CompiledPredicate,
    RequirementCompilationResult,
    propose_date_rule,
)

# ---------------------------------------------------------------------------
# Versions / interface
# ---------------------------------------------------------------------------

DEADLINE_SCHEMA_VERSION: Final = "uspto.deadline-processor.v1"
DEADLINE_INTERFACE: Final = "DeadlineProcessor@1"
DEADLINE_RULESET_VERSION: Final = "deadline-rules@1"

OUTPUT_KIND_REVIEW_ONLY_RESPONSE_DATE_CANDIDATES: Final = (
    "review_only_response_date_candidates"
)

REVIEW_ONLY_DEADLINE_DISCLAIMER: Final = (
    "This output lists review-only response-date candidates with explicit "
    "assumptions, rule chains, and source spans. It is not a docket entry, "
    "not a final deadline assertion, and not legal advice. Named human "
    "confirmation is required before any candidate may be exported to a docket."
)

DEFAULT_MAX_CANDIDATES: Final = 256
DEFAULT_MAX_SOURCE_SPANS: Final = 64
DEFAULT_CALENDAR: Final = "US-federal"
DEFAULT_TIME_ZONE: Final = "America/New_York"
DEFAULT_END_OF_DAY_LOCAL: Final = time(23, 59, 59)

# Closed-set rule identifiers used in rule chains (never invent statute text).
RULE_37_CFR_1_7: Final = "37_cfr_1.7"
RULE_37_CFR_1_134: Final = "37_cfr_1.134"
RULE_37_CFR_1_136A: Final = "37_cfr_1.136(a)"
RULE_SHORTENED_STATUTORY_PERIOD: Final = "shortened_statutory_period"
RULE_WEEKEND_HOLIDAY_ADJUSTMENT: Final = "weekend_holiday_next_business_day"
RULE_CALENDAR_MONTH_PERIOD: Final = "calendar_month_period"

_SHA256_RE = re.compile(r"\A[0-9a-f]{64}\Z")
_NONEMPTY_ID_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._:/=+\-]{0,255}\Z")
_WS_RE = re.compile(r"\s+")

_ISO_DATE_RE = re.compile(r"\A(?P<y>\d{4})-(?P<m>\d{2})-(?P<d>\d{2})\Z")
_US_SLASH_DATE_RE = re.compile(
    r"\A(?P<m>\d{1,2})[/\-](?P<d>\d{1,2})[/\-](?P<y>\d{2,4})\Z"
)
_MONTH_NAME_DATE_RE = re.compile(
    r"\A(?P<mon>Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+"
    r"(?P<d>\d{1,2}),?\s+(?P<y>\d{4})\Z",
    re.IGNORECASE,
)
_PERIOD_RE = re.compile(
    r"(?i)\b(?P<amount>\d+)\s*(?P<unit>months?|days?|weeks?)\b"
)
_MONTH_NAMES: Final[Mapping[str, int]] = MappingProxyType(
    {
        "jan": 1,
        "feb": 2,
        "mar": 3,
        "apr": 4,
        "may": 5,
        "jun": 6,
        "jul": 7,
        "aug": 8,
        "sep": 9,
        "oct": 10,
        "nov": 11,
        "dec": 12,
    }
)

# Labels that would claim a final docket deadline — stripped / rejected.
_FORBIDDEN_FINAL_DEADLINE_TOKENS: Final[frozenset[str]] = frozenset(
    {
        "final_deadline",
        "docket_entry",
        "docketed",
        "binding_deadline",
        "asserted_deadline",
        "confirmed_deadline_without_review",
        "auto_docket",
        "write_docket",
    }
)


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class DeadlineDisposition(str, Enum):
    """Top-level outcome of candidate-date analysis."""

    COMPUTED = "computed"
    MULTIPLE = "multiple"
    PARTIAL = "partial"
    UNKNOWN = "unknown"
    REVIEW = "review"
    QUARANTINE = "quarantine"
    EMPTY = "empty"
    REJECTED = "rejected"


class CandidateComputationStatus(str, Enum):
    """Per-candidate computation status.

    Closed set — never a final docket assertion.
    """

    COMPUTED = "computed"
    UNKNOWN = "unknown"
    CONFLICT = "conflict"
    INCOMPLETE = "incomplete"
    EXCLUDED = "excluded"


class EventBasisKind(str, Enum):
    MAILING_DATE = "mailing_date"
    NOTIFICATION_DATE = "notification_date"
    STATUS_EVENT = "status_event"
    INSTRUCTION_STATED = "instruction_stated"
    ASSUMED = "assumed"
    UNKNOWN = "unknown"


class PeriodUnit(str, Enum):
    MONTHS = "months"
    DAYS = "days"
    WEEKS = "weeks"
    UNKNOWN = "unknown"


class CalendarAdjustmentKind(str, Enum):
    NONE = "none"
    WEEKEND = "weekend"
    HOLIDAY = "holiday"
    WEEKEND_AND_HOLIDAY = "weekend_and_holiday"
    UNKNOWN = "unknown"


class UncertaintyKind(str, Enum):
    NONE = "none"
    MISSING_EVENT_BASIS = "missing_event_basis"
    MISSING_PERIOD = "missing_period"
    MISSING_RULE = "missing_rule"
    CONFLICTING_EVENT_BASIS = "conflicting_event_basis"
    CONFLICTING_PERIOD = "conflicting_period"
    CONFLICTING_RULE = "conflicting_rule"
    UNRESOLVED_EXCEPTION = "unresolved_exception"
    STALE_STATUS = "stale_status"
    ENTITY_STATUS_ASSUMED = "entity_status_assumed"
    EXTENSION_ASSUMED = "extension_assumed"
    FEE_ASSUMED = "fee_assumed"
    TIME_ZONE_ASSUMED = "time_zone_assumed"
    HOLIDAY_SET_INCOMPLETE = "holiday_set_incomplete"
    MULTIPLE_CANDIDATES = "multiple_candidates"
    UNKNOWN = "unknown"


class DeadlineReasonCode(str, Enum):
    CANDIDATES_EMITTED = "candidates_emitted"
    REVIEW_ONLY = "review_only"
    NOT_DOCKET_ENTRY = "not_docket_entry"
    NOT_FINAL_DEADLINE_ASSERTION = "not_final_deadline_assertion"
    NAMED_CONFIRMATION_REQUIRED = "named_confirmation_required"
    DOCKET_EXPORT_BLOCKED = "docket_export_blocked"
    DOCKET_EXPORT_ALLOWED_AFTER_CONFIRMATION = (
        "docket_export_allowed_after_confirmation"
    )
    ASSUMPTIONS_RECORDED = "assumptions_recorded"
    SOURCE_SPANS_RETAINED = "source_spans_retained"
    EVENT_BASIS_RESOLVED = "event_basis_resolved"
    EVENT_BASIS_MISSING = "event_basis_missing"
    EVENT_BASIS_CONFLICT = "event_basis_conflict"
    PERIOD_RESOLVED = "period_resolved"
    PERIOD_MISSING = "period_missing"
    PERIOD_CONFLICT = "period_conflict"
    RULE_CHAIN_RECORDED = "rule_chain_recorded"
    WEEKEND_ADJUSTED = "weekend_adjusted"
    HOLIDAY_ADJUSTED = "holiday_adjusted"
    EXTENSION_VARIANT = "extension_variant"
    ENTITY_STATUS_ASSUMED = "entity_status_assumed"
    FEE_ASSUMED = "fee_assumed"
    EXCEPTION_UNRESOLVED = "exception_unresolved"
    STALE_STATUS = "stale_status"
    MULTIPLE_CANDIDATES = "multiple_candidates"
    UNKNOWN_CANDIDATE = "unknown_candidate"
    EMPTY_INPUT = "empty_input"
    NO_RESPONSE_INSTRUCTIONS = "no_response_instructions"
    QUARANTINED = "quarantined"
    CANDIDATE_LIMIT = "candidate_limit"
    FORBIDDEN_LABEL_STRIPPED = "forbidden_label_stripped"
    HUMAN_REVIEW_REQUIRED = "human_review_required"
    CONTRACT_CANDIDATE_PROJECTED = "contract_candidate_projected"


# ---------------------------------------------------------------------------
# Errors / helpers
# ---------------------------------------------------------------------------


class DeadlineProcessorError(ValueError):
    """Bounded deadline analysis failure (never logs document body)."""

    def __init__(self, message: str, *, code: str = "deadline_processor_error") -> None:
        super().__init__(message)
        self.code = str(code)

    def audit_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": str(self)[:256]}


def sha256_hex(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def _normalize_ws(text: str) -> str:
    return _WS_RE.sub(" ", (text or "").strip())


def _text_digest(text: str) -> str:
    return sha256_hex(_normalize_ws(text))


def _require_str(value: Any, field: str, *, max_len: int = 4096) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field} must be str, got {type(value).__name__}")
    text = value.strip()
    if not text:
        raise ValueError(f"{field} must be non-empty")
    if len(text) > max_len:
        raise ValueError(f"{field} exceeds max length {max_len}")
    return text


def _optional_str(value: Any, field: str, *, max_len: int = 4096) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError(f"{field} must be str or None, got {type(value).__name__}")
    text = value.strip()
    if not text:
        return None
    if len(text) > max_len:
        raise ValueError(f"{field} exceeds max length {max_len}")
    return text


def _identifier(value: Any, field: str) -> str:
    text = _require_str(value, field, max_len=256)
    if not _NONEMPTY_ID_RE.match(text):
        raise ValueError(f"{field} is not a valid identifier: {text!r}")
    return text


def _optional_identifier(value: Any, field: str) -> str | None:
    text = _optional_str(value, field, max_len=256)
    if text is None:
        return None
    if not _NONEMPTY_ID_RE.match(text):
        raise ValueError(f"{field} is not a valid identifier: {text!r}")
    return text


def _nonneg_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field} must be int")
    if value < 0:
        raise ValueError(f"{field} must be non-negative")
    return value


def _optional_float_01(value: Any, field: str) -> float | None:
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError) as exc:
        raise TypeError(f"{field} must be float or None") from exc
    if not (0.0 <= f <= 1.0):
        raise ValueError(f"{field} must be in [0, 1]")
    return f


def _coerce_enum(enum_cls: type[Enum], value: Any, field: str) -> Enum:
    if isinstance(value, enum_cls):
        return value
    if value is None:
        raise ValueError(f"{field} is required")
    text = str(value).strip()
    for member in enum_cls:
        if (
            member.value == text
            or member.name == text
            or member.name.lower() == text.lower()
        ):
            return member
    raise ValueError(f"{field} has unknown value: {value!r}")


def _coerce_classification(value: Any) -> DisclosureClassification:
    if isinstance(value, DisclosureClassification):
        return value
    return _coerce_enum(  # type: ignore[return-value]
        DisclosureClassification, value, "classification"
    )


def _tuple_of_str(
    value: Any, field: str, *, max_items: int = 256
) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        raise TypeError(f"{field} must be a sequence of str, not str")
    if not isinstance(value, Sequence):
        raise TypeError(f"{field} must be a sequence")
    out: list[str] = []
    for i, item in enumerate(value):
        if i >= max_items:
            break
        if not isinstance(item, str):
            raise TypeError(f"{field}[{i}] must be str")
        text = item.strip()
        if text:
            out.append(text[:512])
    return tuple(out)


def _frozen_str_map(
    value: Any, field: str, *, max_items: int = 32
) -> Mapping[str, str]:
    if value is None:
        return MappingProxyType({})
    if not isinstance(value, Mapping):
        raise TypeError(f"{field} must be a mapping")
    out: dict[str, str] = {}
    for i, (k, v) in enumerate(sorted(value.items(), key=lambda kv: str(kv[0]))):
        if i >= max_items:
            break
        key = str(k).strip()
        if not key:
            continue
        if not isinstance(v, str):
            v = str(v)
        out[key[:128]] = v.strip()[:512]
    return MappingProxyType(out)


def contains_forbidden_final_deadline_token(text: str | None) -> bool:
    """Return True if *text* claims a final/docket deadline improperly."""
    if not text:
        return False
    lowered = text.lower().replace("-", "_").replace(" ", "_")
    for token in _FORBIDDEN_FINAL_DEADLINE_TOKENS:
        if token in lowered:
            return True
    raw = text.lower()
    if "final deadline" in raw and "not a final" not in raw:
        return True
    if "write docket" in raw or "auto docket" in raw:
        return True
    return False


def sanitize_deadline_labels(
    labels: Mapping[str, str] | None,
) -> tuple[Mapping[str, str], tuple[str, ...]]:
    """Strip labels that would assert a final docket deadline."""
    if not labels:
        return MappingProxyType({}), ()
    cleaned: dict[str, str] = {}
    reasons: list[str] = []
    for key, value in labels.items():
        k = str(key).strip().lower()
        if k in _FORBIDDEN_FINAL_DEADLINE_TOKENS:
            reasons.append(DeadlineReasonCode.FORBIDDEN_LABEL_STRIPPED.value)
            continue
        if contains_forbidden_final_deadline_token(k) or contains_forbidden_final_deadline_token(
            value
        ):
            reasons.append(DeadlineReasonCode.FORBIDDEN_LABEL_STRIPPED.value)
            continue
        cleaned[str(key).strip()[:128]] = str(value).strip()[:512]
    return MappingProxyType(cleaned), tuple(dict.fromkeys(reasons))


# ---------------------------------------------------------------------------
# Calendar pure helpers
# ---------------------------------------------------------------------------


def parse_date_surface(value: str | date | datetime | None) -> date | None:
    """Parse common mailing-date surfaces to :class:`datetime.date`.

    Returns ``None`` when unparseable — never invents a date.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    m = _ISO_DATE_RE.match(text)
    if m:
        try:
            return date(int(m.group("y")), int(m.group("m")), int(m.group("d")))
        except ValueError:
            return None
    m = _US_SLASH_DATE_RE.match(text)
    if m:
        y = int(m.group("y"))
        if y < 100:
            y += 2000 if y < 70 else 1900
        try:
            return date(y, int(m.group("m")), int(m.group("d")))
        except ValueError:
            return None
    m = _MONTH_NAME_DATE_RE.match(text)
    if m:
        mon = _MONTH_NAMES.get(m.group("mon")[:3].lower())
        if mon is None:
            return None
        try:
            return date(int(m.group("y")), mon, int(m.group("d")))
        except ValueError:
            return None
    # ISO datetime prefix
    if "T" in text:
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
        except ValueError:
            return None
    return None


def add_calendar_months(start: date, months: int) -> date:
    """Add *months* calendar months with end-of-month clamping.

    Example: 2024-01-31 + 1 month → 2024-02-29 (leap year).
    """
    if months < 0:
        raise ValueError("months must be non-negative")
    month_index = start.month - 1 + months
    year = start.year + month_index // 12
    month = month_index % 12 + 1
    last_day = calendar.monthrange(year, month)[1]
    day = min(start.day, last_day)
    return date(year, month, day)


def add_calendar_weeks(start: date, weeks: int) -> date:
    if weeks < 0:
        raise ValueError("weeks must be non-negative")
    return start + timedelta(days=7 * weeks)


def add_calendar_days(start: date, days: int) -> date:
    if days < 0:
        raise ValueError("days must be non-negative")
    return start + timedelta(days=days)


def nth_weekday_of_month(year: int, month: int, weekday: int, n: int) -> date:
    """Return the *n*-th *weekday* (Mon=0) of *month* in *year*."""
    if n < 1 or n > 5:
        raise ValueError("n must be 1..5")
    first = date(year, month, 1)
    offset = (weekday - first.weekday()) % 7
    day = 1 + offset + 7 * (n - 1)
    return date(year, month, day)


def last_weekday_of_month(year: int, month: int, weekday: int) -> date:
    last = date(year, month, calendar.monthrange(year, month)[1])
    offset = (last.weekday() - weekday) % 7
    return last - timedelta(days=offset)


def observed_fixed_holiday(year: int, month: int, day: int) -> date:
    """Fixed-date holiday with Saturday→Friday / Sunday→Monday observation."""
    d = date(year, month, day)
    if d.weekday() == 5:  # Saturday
        return d - timedelta(days=1)
    if d.weekday() == 6:  # Sunday
        return d + timedelta(days=1)
    return d


def us_federal_holidays(year: int) -> frozenset[date]:
    """US federal holidays commonly used for USPTO 37 C.F.R. 1.7 adjustment.

    Includes New Year's Day, MLK Day, Washington's Birthday, Memorial Day,
    Juneteenth, Independence Day, Labor Day, Columbus Day, Veterans Day,
    Thanksgiving, and Christmas. Observation rules applied for fixed dates.
    """
    holidays: set[date] = {
        observed_fixed_holiday(year, 1, 1),  # New Year's Day
        nth_weekday_of_month(year, 1, 0, 3),  # MLK Day (3rd Monday)
        nth_weekday_of_month(year, 2, 0, 3),  # Washington's Birthday
        last_weekday_of_month(year, 5, 0),  # Memorial Day
        observed_fixed_holiday(year, 6, 19),  # Juneteenth
        observed_fixed_holiday(year, 7, 4),  # Independence Day
        nth_weekday_of_month(year, 9, 0, 1),  # Labor Day
        nth_weekday_of_month(year, 10, 0, 2),  # Columbus Day
        observed_fixed_holiday(year, 11, 11),  # Veterans Day
        nth_weekday_of_month(year, 11, 3, 4),  # Thanksgiving (4th Thursday)
        observed_fixed_holiday(year, 12, 25),  # Christmas
    }
    # Also include adjacent-year New Year when relevant for Dec 31 periods.
    holidays.add(observed_fixed_holiday(year + 1, 1, 1))
    holidays.add(observed_fixed_holiday(year - 1, 12, 25))
    return frozenset(holidays)


def is_weekend(d: date) -> bool:
    return d.weekday() >= 5


def is_non_business_day(d: date, holidays: frozenset[date] | set[date] | None) -> bool:
    if is_weekend(d):
        return True
    if holidays and d in holidays:
        return True
    return False


def next_business_day(
    d: date,
    holidays: frozenset[date] | set[date] | None = None,
) -> date:
    """Advance to the next weekday that is not a listed holiday."""
    current = d
    # Cap loop to avoid pathological holiday sets.
    for _ in range(370):
        if not is_non_business_day(current, holidays):
            return current
        current = current + timedelta(days=1)
    return current


def adjust_period_end(
    raw_end: date,
    *,
    holidays: frozenset[date] | set[date] | None = None,
    apply_weekend_holiday: bool = True,
) -> tuple[date, CalendarAdjustmentKind, tuple[str, ...]]:
    """Apply 37 C.F.R. 1.7-style weekend/holiday next-business-day adjustment."""
    reasons: list[str] = []
    if not apply_weekend_holiday:
        return raw_end, CalendarAdjustmentKind.NONE, ()
    holiday_hit = bool(holidays and raw_end in holidays)
    weekend_hit = is_weekend(raw_end)
    if not holiday_hit and not weekend_hit:
        return raw_end, CalendarAdjustmentKind.NONE, ()
    adjusted = next_business_day(raw_end, holidays)
    if weekend_hit and holiday_hit:
        kind = CalendarAdjustmentKind.WEEKEND_AND_HOLIDAY
        reasons.append(DeadlineReasonCode.WEEKEND_ADJUSTED.value)
        reasons.append(DeadlineReasonCode.HOLIDAY_ADJUSTED.value)
    elif weekend_hit:
        kind = CalendarAdjustmentKind.WEEKEND
        reasons.append(DeadlineReasonCode.WEEKEND_ADJUSTED.value)
    else:
        kind = CalendarAdjustmentKind.HOLIDAY
        reasons.append(DeadlineReasonCode.HOLIDAY_ADJUSTED.value)
    if adjusted != raw_end:
        reasons.append(RULE_WEEKEND_HOLIDAY_ADJUSTMENT)
    return adjusted, kind, tuple(dict.fromkeys(reasons))


def parse_period_surface(
    surface: str | None,
    *,
    labels: Mapping[str, str] | None = None,
) -> tuple[int | None, PeriodUnit, str | None]:
    """Extract a response period amount/unit from surface text or labels.

    Returns ``(amount, unit, surface_form)``. Never invents a period when
    none is stated.
    """
    labels = labels or {}
    rp = labels.get("response_period")
    if rp:
        m = _PERIOD_RE.search(rp)
        if m:
            amount = int(m.group("amount"))
            unit_raw = m.group("unit").lower()
            unit = (
                PeriodUnit.MONTHS
                if unit_raw.startswith("month")
                else PeriodUnit.WEEKS
                if unit_raw.startswith("week")
                else PeriodUnit.DAYS
            )
            return amount, unit, _normalize_ws(rp)
    text = surface or ""
    m = _PERIOD_RE.search(text)
    if m:
        amount = int(m.group("amount"))
        unit_raw = m.group("unit").lower()
        unit = (
            PeriodUnit.MONTHS
            if unit_raw.startswith("month")
            else PeriodUnit.WEEKS
            if unit_raw.startswith("week")
            else PeriodUnit.DAYS
        )
        return amount, unit, _normalize_ws(m.group(0))
    return None, PeriodUnit.UNKNOWN, None


def compute_raw_period_end(
    start: date,
    amount: int,
    unit: PeriodUnit,
) -> date | None:
    """Compute unadjusted period end from start + amount/unit."""
    if amount < 0:
        return None
    if unit is PeriodUnit.MONTHS:
        return add_calendar_months(start, amount)
    if unit is PeriodUnit.WEEKS:
        return add_calendar_weeks(start, amount)
    if unit is PeriodUnit.DAYS:
        return add_calendar_days(start, amount)
    return None


def candidate_local_end_to_utc_iso(
    local_day: date,
    *,
    time_zone: str = DEFAULT_TIME_ZONE,
    end_of_day: time = DEFAULT_END_OF_DAY_LOCAL,
) -> str:
    """Encode candidate end-of-day as ISO-8601 UTC string.

    America/New_York is treated as fixed UTC-5 for deterministic tests without
    requiring zoneinfo/tzdata. The assumption is recorded by callers.
    """
    # Deterministic offset: Eastern Standard Time (UTC-5). Daylight-saving
    # variance is an explicit uncertainty callers may surface.
    if time_zone in ("America/New_York", "US/Eastern", "EST", "EDT"):
        offset = timezone(timedelta(hours=-5))
    elif time_zone in ("UTC", "Z", "Etc/UTC"):
        offset = timezone.utc
    else:
        # Unknown zone: still emit as naive local tagged with Z-less offset 0
        # and rely on uncertainty flags; fail-closed to UTC.
        offset = timezone.utc
    local_dt = datetime.combine(local_day, end_of_day, tzinfo=offset)
    utc_dt = local_dt.astimezone(timezone.utc)
    return utc_dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def build_human_review_question(
    *,
    candidate_id: str,
    event_basis: str | None,
    period_surface: str | None,
    candidate_date: str | None,
    status: CandidateComputationStatus,
    conflict_ids: Sequence[str] = (),
) -> str:
    """Deterministic human-review question (not a model summary of the law)."""
    basis = event_basis or "event basis unknown"
    period = period_surface or "period unknown"
    cand = candidate_date or "candidate date unknown"
    if status is CandidateComputationStatus.CONFLICT or conflict_ids:
        others = ", ".join(conflict_ids[:6]) if conflict_ids else "sibling candidates"
        return (
            f"Human review required for candidate {candidate_id}: conflicting "
            f"rules or event bases produce multiple candidates ({others}). "
            f"Event basis={basis}; period={period}; this candidate={cand}. "
            f"Do not docket until a named human confirms which candidate, if any, "
            f"applies. This is review-only and not a final deadline assertion."
        )
    if status in (
        CandidateComputationStatus.UNKNOWN,
        CandidateComputationStatus.INCOMPLETE,
    ):
        return (
            f"Human review required for candidate {candidate_id}: facts are "
            f"incomplete (event basis={basis}; period={period}). Do not treat "
            f"this as a docket deadline. Named confirmation is required before "
            f"any export."
        )
    return (
        f"Human review required for candidate {candidate_id}: verify event "
        f"basis ({basis}), period ({period}), calendar/time-zone/extension "
        f"assumptions, and computed candidate ({cand}) against source spans "
        f"before any docket export. Review-only; not a final deadline."
    )


# ---------------------------------------------------------------------------
# Value records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AnalysisBounds:
    """Hard bounds for candidate emission."""

    max_candidates: int = DEFAULT_MAX_CANDIDATES
    max_source_spans: int = DEFAULT_MAX_SOURCE_SPANS

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "max_candidates",
            _nonneg_int(self.max_candidates, "max_candidates") or DEFAULT_MAX_CANDIDATES,
        )
        object.__setattr__(
            self,
            "max_source_spans",
            _nonneg_int(self.max_source_spans, "max_source_spans")
            or DEFAULT_MAX_SOURCE_SPANS,
        )


@dataclass(frozen=True, slots=True)
class SourceSpanRef:
    """Reference to a source span used in candidate reasoning."""

    span_id: str | None
    artifact_id: str | None
    role: str
    text_digest: str | None
    surface_excerpt: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "span_id", _optional_identifier(self.span_id, "span_id")
        )
        object.__setattr__(
            self, "artifact_id", _optional_identifier(self.artifact_id, "artifact_id")
        )
        object.__setattr__(
            self, "role", _require_str(self.role, "role", max_len=64)
        )
        digest = _optional_str(self.text_digest, "text_digest", max_len=64)
        if digest is not None:
            digest = digest.lower()
            if not _SHA256_RE.match(digest):
                raise ValueError("text_digest must be sha256 hex")
        object.__setattr__(self, "text_digest", digest)
        excerpt = _optional_str(self.surface_excerpt, "surface_excerpt", max_len=512)
        object.__setattr__(self, "surface_excerpt", excerpt)

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "role": self.role,
            "span_id": self.span_id,
            "surface_excerpt": self.surface_excerpt,
            "text_digest": self.text_digest,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SourceSpanRef":
        if not isinstance(value, Mapping):
            raise TypeError("SourceSpanRef must be a mapping")
        return cls(
            span_id=value.get("span_id"),
            artifact_id=value.get("artifact_id"),
            role=value.get("role", "source"),
            text_digest=value.get("text_digest"),
            surface_excerpt=value.get("surface_excerpt"),
        )


@dataclass(frozen=True, slots=True)
class StatusEventInput:
    """Normalized status / transaction event that may supply mailing basis."""

    event_id: str
    event_date: str | None
    kind: str = "status"
    code: str | None = None
    description_digest: str | None = None
    is_mailing_or_notification: bool = False
    freshness_utc: str | None = None
    is_stale: bool = False
    labels: Mapping[str, str] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "event_id", _identifier(self.event_id, "event_id")
        )
        object.__setattr__(
            self,
            "event_date",
            _optional_str(self.event_date, "event_date", max_len=64),
        )
        object.__setattr__(
            self, "kind", _require_str(self.kind, "kind", max_len=64)
        )
        object.__setattr__(
            self, "code", _optional_str(self.code, "code", max_len=128)
        )
        digest = _optional_str(
            self.description_digest, "description_digest", max_len=64
        )
        if digest is not None:
            digest = digest.lower()
            if not _SHA256_RE.match(digest):
                raise ValueError("description_digest must be sha256 hex")
        object.__setattr__(self, "description_digest", digest)
        if not isinstance(self.is_mailing_or_notification, bool):
            raise TypeError("is_mailing_or_notification must be bool")
        object.__setattr__(
            self,
            "freshness_utc",
            _optional_str(self.freshness_utc, "freshness_utc", max_len=64),
        )
        if not isinstance(self.is_stale, bool):
            raise TypeError("is_stale must be bool")
        object.__setattr__(
            self, "labels", _frozen_str_map(self.labels, "labels", max_items=16)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "description_digest": self.description_digest,
            "event_date": self.event_date,
            "event_id": self.event_id,
            "freshness_utc": self.freshness_utc,
            "is_mailing_or_notification": self.is_mailing_or_notification,
            "is_stale": self.is_stale,
            "kind": self.kind,
            "labels": dict(self.labels),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "StatusEventInput":
        if not isinstance(value, Mapping):
            raise TypeError("StatusEventInput must be a mapping")
        return cls(
            event_id=value.get("event_id", ""),
            event_date=value.get("event_date"),
            kind=value.get("kind", "status"),
            code=value.get("code"),
            description_digest=value.get("description_digest"),
            is_mailing_or_notification=bool(
                value.get("is_mailing_or_notification", False)
            ),
            freshness_utc=value.get("freshness_utc"),
            is_stale=bool(value.get("is_stale", False)),
            labels=value.get("labels") or {},
        )


@dataclass(frozen=True, slots=True)
class DeadlineSourceInput:
    """One response-instruction / date-rule source for candidate computation."""

    source_id: str
    source_span_id: str | None
    surface_text: str
    response_period_surface: str | None = None
    period_amount: int | None = None
    period_unit: PeriodUnit | str | None = None
    proposed_date_rule: str | None = None
    legal_citations: tuple[str, ...] = ()
    exceptions: tuple[str, ...] = ()
    mailing_date: str | None = None
    notification_date: str | None = None
    action_id: str | None = None
    artifact_id: str | None = None
    requirement_type: str | None = None
    confidence: float | None = None
    classification: DisclosureClassification | str = DisclosureClassification.UNKNOWN
    labels: Mapping[str, str] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "source_id", _identifier(self.source_id, "source_id")
        )
        object.__setattr__(
            self,
            "source_span_id",
            _optional_identifier(self.source_span_id, "source_span_id"),
        )
        # Surface retained for period parsing only; may be empty for structured.
        if not isinstance(self.surface_text, str):
            raise TypeError("surface_text must be str")
        if len(self.surface_text) > 8000:
            object.__setattr__(self, "surface_text", self.surface_text[:8000])
        object.__setattr__(
            self,
            "response_period_surface",
            _optional_str(
                self.response_period_surface, "response_period_surface", max_len=128
            ),
        )
        if self.period_amount is not None:
            object.__setattr__(
                self,
                "period_amount",
                _nonneg_int(self.period_amount, "period_amount"),
            )
        if self.period_unit is not None and not isinstance(self.period_unit, PeriodUnit):
            object.__setattr__(
                self,
                "period_unit",
                _coerce_enum(PeriodUnit, self.period_unit, "period_unit"),
            )
        object.__setattr__(
            self,
            "proposed_date_rule",
            _optional_str(self.proposed_date_rule, "proposed_date_rule", max_len=256),
        )
        object.__setattr__(
            self,
            "legal_citations",
            _tuple_of_str(self.legal_citations, "legal_citations", max_items=32),
        )
        object.__setattr__(
            self,
            "exceptions",
            _tuple_of_str(self.exceptions, "exceptions", max_items=32),
        )
        object.__setattr__(
            self,
            "mailing_date",
            _optional_str(self.mailing_date, "mailing_date", max_len=64),
        )
        object.__setattr__(
            self,
            "notification_date",
            _optional_str(self.notification_date, "notification_date", max_len=64),
        )
        object.__setattr__(
            self, "action_id", _optional_identifier(self.action_id, "action_id")
        )
        object.__setattr__(
            self, "artifact_id", _optional_identifier(self.artifact_id, "artifact_id")
        )
        object.__setattr__(
            self,
            "requirement_type",
            _optional_str(self.requirement_type, "requirement_type", max_len=128),
        )
        object.__setattr__(
            self, "confidence", _optional_float_01(self.confidence, "confidence")
        )
        object.__setattr__(
            self, "classification", _coerce_classification(self.classification)
        )
        cleaned, _ = sanitize_deadline_labels(self.labels)
        object.__setattr__(self, "labels", cleaned)

    @classmethod
    def from_analysis_candidate(
        cls,
        cand: AnalysisCandidate,
        *,
        artifact_id: str | None = None,
        action_id: str | None = None,
        mailing_date: str | None = None,
        classification: DisclosureClassification | str | None = None,
    ) -> "DeadlineSourceInput":
        labels = dict(cand.labels) if cand.labels else {}
        surface = cand.surface_text or ""
        period_surface = labels.get("response_period")
        amount, unit, parsed_surface = parse_period_surface(surface, labels=labels)
        date_rule = propose_date_rule(cand.kind, surface=surface, labels=labels)
        return cls(
            source_id=cand.candidate_id,
            source_span_id=cand.source_span_id,
            surface_text=surface,
            response_period_surface=period_surface or parsed_surface,
            period_amount=amount,
            period_unit=unit if amount is not None else None,
            proposed_date_rule=date_rule,
            legal_citations=tuple(cand.legal_citations or ()),
            exceptions=tuple(cand.exceptions or ()),
            mailing_date=mailing_date,
            action_id=action_id,
            artifact_id=artifact_id,
            requirement_type=cand.requirement_type,
            confidence=cand.confidence,
            classification=classification or DisclosureClassification.UNKNOWN,
            labels=labels,
        )

    @classmethod
    def from_compiled_predicate(
        cls,
        pred: CompiledPredicate,
        *,
        artifact_id: str | None = None,
        mailing_date: str | None = None,
    ) -> "DeadlineSourceInput":
        labels = dict(pred.labels) if pred.labels else {}
        surface = pred.surface_text or ""
        # Prefer structured proposed_date_rule; fall back to surface/labels.
        amount: int | None = None
        unit: PeriodUnit | None = None
        period_surface: str | None = None
        rule = pred.proposed_date_rule
        if rule:
            m = re.search(
                r"(?:response_period:|period_)(?P<amount>\d+)[_ ]?(?P<unit>months?|days?|weeks?)?",
                rule,
                re.I,
            )
            if m:
                amount = int(m.group("amount"))
                unit_raw = (m.group("unit") or "months").lower()
                unit = (
                    PeriodUnit.MONTHS
                    if unit_raw.startswith("month")
                    else PeriodUnit.WEEKS
                    if unit_raw.startswith("week")
                    else PeriodUnit.DAYS
                )
                period_surface = f"{amount} {unit.value}"
        if amount is None:
            amount, unit, period_surface = parse_period_surface(surface, labels=labels)
        exceptions = tuple(pred.applicability.exceptions) if pred.applicability else ()
        return cls(
            source_id=pred.predicate_id,
            source_span_id=pred.source_span_id,
            surface_text=surface,
            response_period_surface=period_surface,
            period_amount=amount,
            period_unit=unit if amount is not None else None,
            proposed_date_rule=rule,
            legal_citations=tuple(pred.legal_citations or ()),
            exceptions=exceptions,
            mailing_date=mailing_date,
            artifact_id=artifact_id,
            requirement_type=pred.requirement_type,
            confidence=pred.parser_confidence,
            classification=pred.classification,
            labels=labels,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_id": self.action_id,
            "artifact_id": self.artifact_id,
            "classification": self.classification.value
            if isinstance(self.classification, DisclosureClassification)
            else str(self.classification),
            "confidence": self.confidence,
            "exceptions": list(self.exceptions),
            "labels": dict(self.labels),
            "legal_citations": list(self.legal_citations),
            "mailing_date": self.mailing_date,
            "notification_date": self.notification_date,
            "period_amount": self.period_amount,
            "period_unit": self.period_unit.value
            if isinstance(self.period_unit, PeriodUnit)
            else self.period_unit,
            "proposed_date_rule": self.proposed_date_rule,
            "requirement_type": self.requirement_type,
            "response_period_surface": self.response_period_surface,
            "source_id": self.source_id,
            "source_span_id": self.source_span_id,
            "surface_text": self.surface_text,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "DeadlineSourceInput":
        if not isinstance(value, Mapping):
            raise TypeError("DeadlineSourceInput must be a mapping")
        return cls(
            source_id=value.get("source_id", ""),
            source_span_id=value.get("source_span_id"),
            surface_text=value.get("surface_text", "") or "",
            response_period_surface=value.get("response_period_surface"),
            period_amount=value.get("period_amount"),
            period_unit=value.get("period_unit"),
            proposed_date_rule=value.get("proposed_date_rule"),
            legal_citations=tuple(value.get("legal_citations") or ()),
            exceptions=tuple(value.get("exceptions") or ()),
            mailing_date=value.get("mailing_date"),
            notification_date=value.get("notification_date"),
            action_id=value.get("action_id"),
            artifact_id=value.get("artifact_id"),
            requirement_type=value.get("requirement_type"),
            confidence=value.get("confidence"),
            classification=value.get(
                "classification", DisclosureClassification.UNKNOWN.value
            ),
            labels=value.get("labels") or {},
        )


@dataclass(frozen=True, slots=True)
class DeadlineAssumptions:
    """Explicit assumptions applied to candidate computation.

    All fields are assumptions, never proven facts. Empty means "not provided".
    """

    entity_status: str | None = None
    extension_months: int | None = None
    extension_label: str | None = None
    fee_assumption: str | None = None
    time_zone: str = DEFAULT_TIME_ZONE
    calendar: str = DEFAULT_CALENDAR
    apply_weekend_holiday: bool = True
    extra_holidays: tuple[str, ...] = ()
    exclude_holidays: tuple[str, ...] = ()
    end_of_day_local: str = "23:59:59"
    notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "entity_status",
            _optional_str(self.entity_status, "entity_status", max_len=128),
        )
        if self.extension_months is not None:
            object.__setattr__(
                self,
                "extension_months",
                _nonneg_int(self.extension_months, "extension_months"),
            )
            if self.extension_months > 5:
                # 1.136(a) max commonly 5 months for non-final; still allowed as
                # assumption with uncertainty — do not hard reject.
                pass
        object.__setattr__(
            self,
            "extension_label",
            _optional_str(self.extension_label, "extension_label", max_len=128),
        )
        object.__setattr__(
            self,
            "fee_assumption",
            _optional_str(self.fee_assumption, "fee_assumption", max_len=128),
        )
        object.__setattr__(
            self,
            "time_zone",
            _require_str(self.time_zone, "time_zone", max_len=64),
        )
        object.__setattr__(
            self,
            "calendar",
            _require_str(self.calendar, "calendar", max_len=64),
        )
        if not isinstance(self.apply_weekend_holiday, bool):
            raise TypeError("apply_weekend_holiday must be bool")
        object.__setattr__(
            self,
            "extra_holidays",
            _tuple_of_str(self.extra_holidays, "extra_holidays", max_items=64),
        )
        object.__setattr__(
            self,
            "exclude_holidays",
            _tuple_of_str(self.exclude_holidays, "exclude_holidays", max_items=64),
        )
        object.__setattr__(
            self,
            "end_of_day_local",
            _require_str(self.end_of_day_local, "end_of_day_local", max_len=16),
        )
        object.__setattr__(
            self, "notes", _tuple_of_str(self.notes, "notes", max_items=32)
        )

    def extension_assumption_label(self) -> str | None:
        if self.extension_label:
            return self.extension_label
        if self.extension_months is not None:
            if self.extension_months == 0:
                return "no_extension"
            return f"extension_{self.extension_months}_month"
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "apply_weekend_holiday": self.apply_weekend_holiday,
            "calendar": self.calendar,
            "end_of_day_local": self.end_of_day_local,
            "entity_status": self.entity_status,
            "exclude_holidays": list(self.exclude_holidays),
            "extension_label": self.extension_label,
            "extension_months": self.extension_months,
            "extra_holidays": list(self.extra_holidays),
            "fee_assumption": self.fee_assumption,
            "notes": list(self.notes),
            "time_zone": self.time_zone,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any] | None) -> "DeadlineAssumptions":
        if value is None:
            return cls()
        if not isinstance(value, Mapping):
            raise TypeError("DeadlineAssumptions must be a mapping")
        return cls(
            entity_status=value.get("entity_status"),
            extension_months=value.get("extension_months"),
            extension_label=value.get("extension_label"),
            fee_assumption=value.get("fee_assumption"),
            time_zone=value.get("time_zone", DEFAULT_TIME_ZONE),
            calendar=value.get("calendar", DEFAULT_CALENDAR),
            apply_weekend_holiday=bool(value.get("apply_weekend_holiday", True)),
            extra_holidays=tuple(value.get("extra_holidays") or ()),
            exclude_holidays=tuple(value.get("exclude_holidays") or ()),
            end_of_day_local=value.get("end_of_day_local", "23:59:59"),
            notes=tuple(value.get("notes") or ()),
        )


@dataclass(frozen=True, slots=True)
class DocketExportGate:
    """Gate enforcing named human confirmation before docket export.

    Export is **never** enabled without a non-empty ``confirmed_by`` name.
    This gate does not write docket entries; it only records whether export
    would be permitted after human confirmation.
    """

    requires_named_confirmation: bool
    export_allowed: bool
    confirmed_by: str | None
    confirmation_utc: str | None
    confirmation_note: str | None
    blocked_reason: str

    def __post_init__(self) -> None:
        if not isinstance(self.requires_named_confirmation, bool):
            raise TypeError("requires_named_confirmation must be bool")
        if not isinstance(self.export_allowed, bool):
            raise TypeError("export_allowed must be bool")
        object.__setattr__(
            self,
            "confirmed_by",
            _optional_str(self.confirmed_by, "confirmed_by", max_len=256),
        )
        object.__setattr__(
            self,
            "confirmation_utc",
            _optional_str(self.confirmation_utc, "confirmation_utc", max_len=64),
        )
        object.__setattr__(
            self,
            "confirmation_note",
            _optional_str(self.confirmation_note, "confirmation_note", max_len=512),
        )
        object.__setattr__(
            self,
            "blocked_reason",
            _require_str(self.blocked_reason, "blocked_reason", max_len=512),
        )
        # Fail-closed: export_allowed requires named confirmation.
        if self.export_allowed:
            if not self.requires_named_confirmation:
                raise ValueError(
                    "export_allowed requires requires_named_confirmation=True"
                )
            if not self.confirmed_by:
                raise ValueError(
                    "export_allowed requires non-empty confirmed_by (named human)"
                )
        if not self.requires_named_confirmation:
            # Policy: always require named confirmation for this processor.
            object.__setattr__(self, "requires_named_confirmation", True)
            if self.export_allowed:
                object.__setattr__(self, "export_allowed", False)
                object.__setattr__(
                    self,
                    "blocked_reason",
                    "named human confirmation is always required before docket export",
                )

    @classmethod
    def blocked(cls, reason: str | None = None) -> "DocketExportGate":
        return cls(
            requires_named_confirmation=True,
            export_allowed=False,
            confirmed_by=None,
            confirmation_utc=None,
            confirmation_note=None,
            blocked_reason=reason
            or (
                "named human confirmation is required before any docket export; "
                "candidates remain review-only"
            ),
        )

    @classmethod
    def confirmed(
        cls,
        confirmed_by: str,
        *,
        confirmation_utc: str | None = None,
        confirmation_note: str | None = None,
    ) -> "DocketExportGate":
        name = _require_str(confirmed_by, "confirmed_by", max_len=256)
        # Reject placeholder / anonymous names.
        lowered = name.lower()
        if lowered in {"system", "auto", "bot", "anonymous", "unknown", "n/a", "na"}:
            raise DeadlineProcessorError(
                "confirmed_by must be a named human, not a placeholder",
                code="invalid_confirmer",
            )
        utc = confirmation_utc or datetime.now(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        return cls(
            requires_named_confirmation=True,
            export_allowed=True,
            confirmed_by=name,
            confirmation_utc=utc,
            confirmation_note=confirmation_note,
            blocked_reason="export permitted only after named confirmation; "
            "still not a final legal determination",
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "blocked_reason": self.blocked_reason,
            "confirmation_note": self.confirmation_note,
            "confirmation_utc": self.confirmation_utc,
            "confirmed_by": self.confirmed_by,
            "export_allowed": self.export_allowed,
            "requires_named_confirmation": self.requires_named_confirmation,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any] | None) -> "DocketExportGate":
        if value is None:
            return cls.blocked()
        if not isinstance(value, Mapping):
            raise TypeError("DocketExportGate must be a mapping")
        return cls(
            requires_named_confirmation=bool(
                value.get("requires_named_confirmation", True)
            ),
            export_allowed=bool(value.get("export_allowed", False)),
            confirmed_by=value.get("confirmed_by"),
            confirmation_utc=value.get("confirmation_utc"),
            confirmation_note=value.get("confirmation_note"),
            blocked_reason=value.get(
                "blocked_reason",
                "named human confirmation is required before any docket export",
            ),
        )


@dataclass(frozen=True, slots=True)
class ResponseDateCandidate:
    """One review-only response-date candidate with full assumption trace."""

    candidate_id: str
    status: CandidateComputationStatus
    is_review_only: bool
    event_basis_kind: EventBasisKind
    event_basis_date: str | None
    event_basis_source: str | None
    period_amount: int | None
    period_unit: PeriodUnit | None
    period_surface: str | None
    raw_end_date: str | None
    adjusted_end_date: str | None
    candidate_utc: str | None
    calendar_adjustment: CalendarAdjustmentKind
    rule_chain: tuple[str, ...]
    assumptions: Mapping[str, str]
    uncertainty_kinds: tuple[str, ...]
    uncertainty_summary: str
    source_spans: tuple[SourceSpanRef, ...]
    exceptions: tuple[str, ...]
    conflict_group_id: str | None
    conflict_peer_ids: tuple[str, ...]
    human_review_question: str
    review_state: ReviewState
    classification: DisclosureClassification
    reason_codes: tuple[str, ...]
    labels: Mapping[str, str]
    confidence: float | None = None
    action_id: str | None = None
    source_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "candidate_id", _identifier(self.candidate_id, "candidate_id")
        )
        object.__setattr__(
            self,
            "status",
            _coerce_enum(CandidateComputationStatus, self.status, "status"),
        )
        if not isinstance(self.is_review_only, bool):
            raise TypeError("is_review_only must be bool")
        if not self.is_review_only:
            raise ValueError(
                "is_review_only must be True — candidates are never final deadlines"
            )
        object.__setattr__(
            self,
            "event_basis_kind",
            _coerce_enum(EventBasisKind, self.event_basis_kind, "event_basis_kind"),
        )
        object.__setattr__(
            self,
            "event_basis_date",
            _optional_str(self.event_basis_date, "event_basis_date", max_len=64),
        )
        object.__setattr__(
            self,
            "event_basis_source",
            _optional_str(self.event_basis_source, "event_basis_source", max_len=256),
        )
        if self.period_amount is not None:
            object.__setattr__(
                self,
                "period_amount",
                _nonneg_int(self.period_amount, "period_amount"),
            )
        if self.period_unit is not None and not isinstance(self.period_unit, PeriodUnit):
            object.__setattr__(
                self,
                "period_unit",
                _coerce_enum(PeriodUnit, self.period_unit, "period_unit"),
            )
        object.__setattr__(
            self,
            "period_surface",
            _optional_str(self.period_surface, "period_surface", max_len=128),
        )
        object.__setattr__(
            self,
            "raw_end_date",
            _optional_str(self.raw_end_date, "raw_end_date", max_len=64),
        )
        object.__setattr__(
            self,
            "adjusted_end_date",
            _optional_str(self.adjusted_end_date, "adjusted_end_date", max_len=64),
        )
        object.__setattr__(
            self,
            "candidate_utc",
            _optional_str(self.candidate_utc, "candidate_utc", max_len=64),
        )
        object.__setattr__(
            self,
            "calendar_adjustment",
            _coerce_enum(
                CalendarAdjustmentKind, self.calendar_adjustment, "calendar_adjustment"
            ),
        )
        object.__setattr__(
            self, "rule_chain", _tuple_of_str(self.rule_chain, "rule_chain", max_items=32)
        )
        object.__setattr__(
            self, "assumptions", _frozen_str_map(self.assumptions, "assumptions", max_items=32)
        )
        object.__setattr__(
            self,
            "uncertainty_kinds",
            _tuple_of_str(self.uncertainty_kinds, "uncertainty_kinds", max_items=32),
        )
        object.__setattr__(
            self,
            "uncertainty_summary",
            _require_str(self.uncertainty_summary, "uncertainty_summary", max_len=512),
        )
        if not isinstance(self.source_spans, tuple):
            object.__setattr__(self, "source_spans", tuple(self.source_spans))
        for span in self.source_spans:
            if not isinstance(span, SourceSpanRef):
                raise TypeError("source_spans items must be SourceSpanRef")
        object.__setattr__(
            self, "exceptions", _tuple_of_str(self.exceptions, "exceptions", max_items=32)
        )
        object.__setattr__(
            self,
            "conflict_group_id",
            _optional_identifier(self.conflict_group_id, "conflict_group_id"),
        )
        object.__setattr__(
            self,
            "conflict_peer_ids",
            _tuple_of_str(self.conflict_peer_ids, "conflict_peer_ids", max_items=64),
        )
        object.__setattr__(
            self,
            "human_review_question",
            _require_str(
                self.human_review_question, "human_review_question", max_len=2048
            ),
        )
        object.__setattr__(
            self,
            "review_state",
            _coerce_enum(ReviewState, self.review_state, "review_state"),
        )
        # Always require review for candidates.
        if self.review_state is ReviewState.NOT_REQUIRED:
            object.__setattr__(self, "review_state", ReviewState.REQUIRED)
        if self.review_state is ReviewState.COMPLETE:
            # COMPLETE would imply docket-ready without gate — force REQUIRED.
            object.__setattr__(self, "review_state", ReviewState.REQUIRED)
        object.__setattr__(
            self, "classification", _coerce_classification(self.classification)
        )
        object.__setattr__(
            self,
            "reason_codes",
            _tuple_of_str(self.reason_codes, "reason_codes", max_items=64),
        )
        cleaned, _ = sanitize_deadline_labels(self.labels)
        object.__setattr__(self, "labels", cleaned)
        object.__setattr__(
            self, "confidence", _optional_float_01(self.confidence, "confidence")
        )
        object.__setattr__(
            self, "action_id", _optional_identifier(self.action_id, "action_id")
        )
        object.__setattr__(
            self, "source_id", _optional_identifier(self.source_id, "source_id")
        )

    @property
    def has_source_spans(self) -> bool:
        return any(s.span_id for s in self.source_spans)

    @property
    def has_assumptions(self) -> bool:
        return bool(self.assumptions)

    def to_candidate_deadline(self) -> CandidateDeadline | None:
        """Project to the contracts.CandidateDeadline shape when computable.

        Returns ``None`` for incomplete/unknown candidates without a
        ``candidate_utc`` (contract requires non-empty candidate_utc).
        """
        if not self.candidate_utc:
            return None
        entity = self.assumptions.get("entity_status")
        extension = self.assumptions.get("extension")
        calendar = self.assumptions.get("calendar", DEFAULT_CALENDAR)
        time_zone = self.assumptions.get("time_zone", DEFAULT_TIME_ZONE)
        event_basis = (
            f"{self.event_basis_kind.value}:{self.event_basis_date or 'unknown'}"
        )
        if self.event_basis_source:
            event_basis = f"{event_basis}@{self.event_basis_source}"
        return CandidateDeadline(
            schema_version=CONTRACTS_SCHEMA_VERSION,
            deadline_id=self.candidate_id,
            event_basis=event_basis[:256],
            rule_chain=self.rule_chain,
            calendar=calendar,
            time_zone=time_zone,
            entity_status_assumption=entity,
            extension_assumption=extension,
            candidate_utc=self.candidate_utc,
            uncertainty=self.uncertainty_summary[:256],
            reviewer_confirmation=ReviewState.REQUIRED,
            classification=self.classification,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_id": self.action_id,
            "adjusted_end_date": self.adjusted_end_date,
            "assumptions": dict(self.assumptions),
            "calendar_adjustment": self.calendar_adjustment.value,
            "candidate_id": self.candidate_id,
            "candidate_utc": self.candidate_utc,
            "classification": self.classification.value,
            "confidence": self.confidence,
            "conflict_group_id": self.conflict_group_id,
            "conflict_peer_ids": list(self.conflict_peer_ids),
            "event_basis_date": self.event_basis_date,
            "event_basis_kind": self.event_basis_kind.value,
            "event_basis_source": self.event_basis_source,
            "exceptions": list(self.exceptions),
            "human_review_question": self.human_review_question,
            "is_review_only": self.is_review_only,
            "labels": dict(self.labels),
            "period_amount": self.period_amount,
            "period_surface": self.period_surface,
            "period_unit": self.period_unit.value if self.period_unit else None,
            "raw_end_date": self.raw_end_date,
            "reason_codes": list(self.reason_codes),
            "review_state": self.review_state.value,
            "rule_chain": list(self.rule_chain),
            "source_id": self.source_id,
            "source_spans": [s.to_dict() for s in self.source_spans],
            "status": self.status.value,
            "uncertainty_kinds": list(self.uncertainty_kinds),
            "uncertainty_summary": self.uncertainty_summary,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ResponseDateCandidate":
        if not isinstance(value, Mapping):
            raise TypeError("ResponseDateCandidate must be a mapping")
        unit_raw = value.get("period_unit")
        period_unit: PeriodUnit | None
        if unit_raw is None or unit_raw == "":
            period_unit = None
        else:
            period_unit = _coerce_enum(PeriodUnit, unit_raw, "period_unit")  # type: ignore[assignment]
        return cls(
            candidate_id=value.get("candidate_id", ""),
            status=value.get("status", CandidateComputationStatus.UNKNOWN.value),
            is_review_only=bool(value.get("is_review_only", True)),
            event_basis_kind=value.get(
                "event_basis_kind", EventBasisKind.UNKNOWN.value
            ),
            event_basis_date=value.get("event_basis_date"),
            event_basis_source=value.get("event_basis_source"),
            period_amount=value.get("period_amount"),
            period_unit=period_unit,
            period_surface=value.get("period_surface"),
            raw_end_date=value.get("raw_end_date"),
            adjusted_end_date=value.get("adjusted_end_date"),
            candidate_utc=value.get("candidate_utc"),
            calendar_adjustment=value.get(
                "calendar_adjustment", CalendarAdjustmentKind.NONE.value
            ),
            rule_chain=tuple(value.get("rule_chain") or ()),
            assumptions=value.get("assumptions") or {},
            uncertainty_kinds=tuple(value.get("uncertainty_kinds") or ()),
            uncertainty_summary=value.get("uncertainty_summary", "unknown"),
            source_spans=tuple(
                SourceSpanRef.from_dict(s) for s in (value.get("source_spans") or ())
            ),
            exceptions=tuple(value.get("exceptions") or ()),
            conflict_group_id=value.get("conflict_group_id"),
            conflict_peer_ids=tuple(value.get("conflict_peer_ids") or ()),
            human_review_question=value.get(
                "human_review_question",
                "Human review required before any docket export.",
            ),
            review_state=value.get("review_state", ReviewState.REQUIRED.value),
            classification=value.get(
                "classification", DisclosureClassification.UNKNOWN.value
            ),
            reason_codes=tuple(value.get("reason_codes") or ()),
            labels=value.get("labels") or {},
            confidence=value.get("confidence"),
            action_id=value.get("action_id"),
            source_id=value.get("source_id"),
        )


@dataclass(frozen=True, slots=True)
class DeadlineConflict:
    """Explicit conflict among candidates (never silently resolved)."""

    conflict_id: str
    kind: str
    candidate_ids: tuple[str, ...]
    detail: str
    source_span_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "conflict_id", _identifier(self.conflict_id, "conflict_id")
        )
        object.__setattr__(
            self, "kind", _require_str(self.kind, "kind", max_len=64)
        )
        object.__setattr__(
            self,
            "candidate_ids",
            _tuple_of_str(self.candidate_ids, "candidate_ids", max_items=64),
        )
        object.__setattr__(
            self, "detail", _require_str(self.detail, "detail", max_len=1024)
        )
        object.__setattr__(
            self,
            "source_span_ids",
            _tuple_of_str(self.source_span_ids, "source_span_ids", max_items=64),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_ids": list(self.candidate_ids),
            "conflict_id": self.conflict_id,
            "detail": self.detail,
            "kind": self.kind,
            "source_span_ids": list(self.source_span_ids),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "DeadlineConflict":
        if not isinstance(value, Mapping):
            raise TypeError("DeadlineConflict must be a mapping")
        return cls(
            conflict_id=value.get("conflict_id", ""),
            kind=value.get("kind", "unknown"),
            candidate_ids=tuple(value.get("candidate_ids") or ()),
            detail=value.get("detail", "conflict"),
            source_span_ids=tuple(value.get("source_span_ids") or ()),
        )


@dataclass(frozen=True, slots=True)
class DeadlineAnalysisInput:
    """Inputs for review-only response-date candidate analysis."""

    matter_id: str | None = None
    analysis_id: str | None = None
    sources: tuple[DeadlineSourceInput, ...] = ()
    status_events: tuple[StatusEventInput, ...] = ()
    office_action_results: tuple[OfficeActionResult, ...] = ()
    requirement_results: tuple[RequirementCompilationResult, ...] = ()
    mailing_date: str | None = None
    notification_date: str | None = None
    assumptions: DeadlineAssumptions | None = None
    # Optional explicit alternative assumption sets → multiple candidates.
    alternative_assumptions: tuple[DeadlineAssumptions, ...] = ()
    classification: DisclosureClassification | str = DisclosureClassification.UNKNOWN
    labels: Mapping[str, str] = MappingProxyType({})
    # When True, emit extension variants 0..N if extension_months provided.
    emit_extension_variants: bool = False
    max_extension_months: int = 3

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "matter_id", _optional_identifier(self.matter_id, "matter_id")
        )
        object.__setattr__(
            self,
            "analysis_id",
            _optional_identifier(self.analysis_id, "analysis_id"),
        )
        if not isinstance(self.sources, tuple):
            object.__setattr__(self, "sources", tuple(self.sources))
        for s in self.sources:
            if not isinstance(s, DeadlineSourceInput):
                raise TypeError("sources items must be DeadlineSourceInput")
        if not isinstance(self.status_events, tuple):
            object.__setattr__(self, "status_events", tuple(self.status_events))
        for e in self.status_events:
            if not isinstance(e, StatusEventInput):
                raise TypeError("status_events items must be StatusEventInput")
        if not isinstance(self.office_action_results, tuple):
            object.__setattr__(
                self, "office_action_results", tuple(self.office_action_results)
            )
        if not isinstance(self.requirement_results, tuple):
            object.__setattr__(
                self, "requirement_results", tuple(self.requirement_results)
            )
        object.__setattr__(
            self,
            "mailing_date",
            _optional_str(self.mailing_date, "mailing_date", max_len=64),
        )
        object.__setattr__(
            self,
            "notification_date",
            _optional_str(self.notification_date, "notification_date", max_len=64),
        )
        if self.assumptions is None:
            object.__setattr__(self, "assumptions", DeadlineAssumptions())
        elif not isinstance(self.assumptions, DeadlineAssumptions):
            raise TypeError("assumptions must be DeadlineAssumptions or None")
        if not isinstance(self.alternative_assumptions, tuple):
            object.__setattr__(
                self, "alternative_assumptions", tuple(self.alternative_assumptions)
            )
        for a in self.alternative_assumptions:
            if not isinstance(a, DeadlineAssumptions):
                raise TypeError(
                    "alternative_assumptions items must be DeadlineAssumptions"
                )
        object.__setattr__(
            self, "classification", _coerce_classification(self.classification)
        )
        cleaned, _ = sanitize_deadline_labels(self.labels)
        object.__setattr__(self, "labels", cleaned)
        if not isinstance(self.emit_extension_variants, bool):
            raise TypeError("emit_extension_variants must be bool")
        object.__setattr__(
            self,
            "max_extension_months",
            _nonneg_int(self.max_extension_months, "max_extension_months"),
        )


@dataclass(frozen=True, slots=True)
class DeadlineAnalysisResult:
    """Full review-only response-date candidate analysis outcome."""

    schema_version: str
    analysis_id: str
    matter_id: str | None
    disposition: DeadlineDisposition
    review_state: ReviewState
    classification: DisclosureClassification
    output_kind: str
    disclaimer: str
    is_review_only: bool
    is_final_deadline_assertion: bool
    is_docket_entry: bool
    reason_codes: tuple[str, ...]
    warnings: tuple[str, ...]
    candidates: tuple[ResponseDateCandidate, ...]
    conflicts: tuple[DeadlineConflict, ...]
    docket_export_gate: DocketExportGate
    assumptions: DeadlineAssumptions
    ruleset_versions: Mapping[str, str]
    labels: Mapping[str, str]
    text_digest: str
    computed_count: int
    unknown_count: int
    conflict_count: int

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _require_str(self.schema_version, "schema_version", max_len=64),
        )
        if self.schema_version != DEADLINE_SCHEMA_VERSION:
            raise ValueError(
                f"DeadlineAnalysisResult.schema_version must be {DEADLINE_SCHEMA_VERSION}"
            )
        object.__setattr__(
            self, "analysis_id", _identifier(self.analysis_id, "analysis_id")
        )
        object.__setattr__(
            self, "matter_id", _optional_identifier(self.matter_id, "matter_id")
        )
        object.__setattr__(
            self,
            "disposition",
            _coerce_enum(DeadlineDisposition, self.disposition, "disposition"),
        )
        object.__setattr__(
            self,
            "review_state",
            _coerce_enum(ReviewState, self.review_state, "review_state"),
        )
        object.__setattr__(
            self, "classification", _coerce_classification(self.classification)
        )
        object.__setattr__(
            self,
            "output_kind",
            _require_str(self.output_kind, "output_kind", max_len=128),
        )
        if self.output_kind != OUTPUT_KIND_REVIEW_ONLY_RESPONSE_DATE_CANDIDATES:
            raise ValueError(
                "output_kind must be "
                f"{OUTPUT_KIND_REVIEW_ONLY_RESPONSE_DATE_CANDIDATES!r}"
            )
        object.__setattr__(
            self,
            "disclaimer",
            _require_str(self.disclaimer, "disclaimer", max_len=2048),
        )
        if "review-only" not in self.disclaimer.lower():
            raise ValueError("disclaimer must state review-only nature")
        if not isinstance(self.is_review_only, bool) or not self.is_review_only:
            raise ValueError("is_review_only must be True")
        if not isinstance(self.is_final_deadline_assertion, bool):
            raise TypeError("is_final_deadline_assertion must be bool")
        if self.is_final_deadline_assertion:
            raise ValueError(
                "is_final_deadline_assertion must be False — never assert final deadlines"
            )
        if not isinstance(self.is_docket_entry, bool):
            raise TypeError("is_docket_entry must be bool")
        if self.is_docket_entry:
            raise ValueError("is_docket_entry must be False — never write docket entries")
        object.__setattr__(
            self,
            "reason_codes",
            _tuple_of_str(self.reason_codes, "reason_codes", max_items=128),
        )
        object.__setattr__(
            self, "warnings", _tuple_of_str(self.warnings, "warnings", max_items=128)
        )
        if not isinstance(self.candidates, tuple):
            object.__setattr__(self, "candidates", tuple(self.candidates))
        for c in self.candidates:
            if not isinstance(c, ResponseDateCandidate):
                raise TypeError("candidates items must be ResponseDateCandidate")
            if not c.is_review_only:
                raise ValueError("every candidate must be review-only")
        if not isinstance(self.conflicts, tuple):
            object.__setattr__(self, "conflicts", tuple(self.conflicts))
        if not isinstance(self.docket_export_gate, DocketExportGate):
            raise TypeError("docket_export_gate must be DocketExportGate")
        if not self.docket_export_gate.requires_named_confirmation:
            raise ValueError(
                "docket_export_gate.requires_named_confirmation must be True"
            )
        if not isinstance(self.assumptions, DeadlineAssumptions):
            raise TypeError("assumptions must be DeadlineAssumptions")
        object.__setattr__(
            self,
            "ruleset_versions",
            _frozen_str_map(self.ruleset_versions, "ruleset_versions", max_items=16),
        )
        cleaned, _ = sanitize_deadline_labels(self.labels)
        object.__setattr__(self, "labels", cleaned)
        object.__setattr__(
            self, "text_digest", _require_str(self.text_digest, "text_digest", max_len=64)
        )
        if not _SHA256_RE.match(self.text_digest.lower()):
            raise ValueError("text_digest must be sha256 hex")
        object.__setattr__(
            self, "computed_count", _nonneg_int(self.computed_count, "computed_count")
        )
        object.__setattr__(
            self, "unknown_count", _nonneg_int(self.unknown_count, "unknown_count")
        )
        object.__setattr__(
            self, "conflict_count", _nonneg_int(self.conflict_count, "conflict_count")
        )
        if requires_quarantine(self.classification) and self.review_state not in (
            ReviewState.REQUIRED,
            ReviewState.PENDING,
        ):
            object.__setattr__(self, "review_state", ReviewState.REQUIRED)

    @property
    def requires_review(self) -> bool:
        return True  # always — review-only product

    @property
    def docket_export_allowed(self) -> bool:
        return self.docket_export_gate.export_allowed

    def candidate_by_id(self, candidate_id: str) -> ResponseDateCandidate | None:
        for c in self.candidates:
            if c.candidate_id == candidate_id:
                return c
        return None

    def to_contract_deadlines(self) -> tuple[CandidateDeadline, ...]:
        """Project computable candidates to contracts.CandidateDeadline."""
        out: list[CandidateDeadline] = []
        for c in self.candidates:
            projected = c.to_candidate_deadline()
            if projected is not None:
                out.append(projected)
        return tuple(out)

    def with_named_confirmation(
        self,
        confirmed_by: str,
        *,
        confirmation_utc: str | None = None,
        confirmation_note: str | None = None,
    ) -> "DeadlineAnalysisResult":
        """Return a copy with docket export gate opened after named confirmation.

        Still does not write docket entries or assert final deadlines.
        """
        gate = DocketExportGate.confirmed(
            confirmed_by,
            confirmation_utc=confirmation_utc,
            confirmation_note=confirmation_note,
        )
        reasons = list(self.reason_codes)
        if (
            DeadlineReasonCode.DOCKET_EXPORT_ALLOWED_AFTER_CONFIRMATION.value
            not in reasons
        ):
            reasons.append(
                DeadlineReasonCode.DOCKET_EXPORT_ALLOWED_AFTER_CONFIRMATION.value
            )
        return DeadlineAnalysisResult(
            schema_version=self.schema_version,
            analysis_id=self.analysis_id,
            matter_id=self.matter_id,
            disposition=self.disposition,
            review_state=ReviewState.REQUIRED,  # still review-only product
            classification=self.classification,
            output_kind=self.output_kind,
            disclaimer=self.disclaimer,
            is_review_only=True,
            is_final_deadline_assertion=False,
            is_docket_entry=False,
            reason_codes=tuple(dict.fromkeys(reasons)),
            warnings=self.warnings,
            candidates=self.candidates,
            conflicts=self.conflicts,
            docket_export_gate=gate,
            assumptions=self.assumptions,
            ruleset_versions=self.ruleset_versions,
            labels=self.labels,
            text_digest=self.text_digest,
            computed_count=self.computed_count,
            unknown_count=self.unknown_count,
            conflict_count=self.conflict_count,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "analysis_id": self.analysis_id,
            "assumptions": self.assumptions.to_dict(),
            "candidates": [c.to_dict() for c in self.candidates],
            "classification": self.classification.value,
            "computed_count": self.computed_count,
            "conflict_count": self.conflict_count,
            "conflicts": [c.to_dict() for c in self.conflicts],
            "disclaimer": self.disclaimer,
            "disposition": self.disposition.value,
            "docket_export_gate": self.docket_export_gate.to_dict(),
            "is_docket_entry": self.is_docket_entry,
            "is_final_deadline_assertion": self.is_final_deadline_assertion,
            "is_review_only": self.is_review_only,
            "labels": dict(self.labels),
            "matter_id": self.matter_id,
            "output_kind": self.output_kind,
            "reason_codes": list(self.reason_codes),
            "review_state": self.review_state.value,
            "ruleset_versions": dict(self.ruleset_versions),
            "schema_version": self.schema_version,
            "text_digest": self.text_digest,
            "unknown_count": self.unknown_count,
            "warnings": list(self.warnings),
        }

    def to_canonical_json(self) -> str:
        return canonical_json(self.to_dict())

    def public_projection(self) -> dict[str, Any]:
        """Identifiers and counts only — no instruction body text."""
        return {
            "analysis_id": self.analysis_id,
            "candidate_count": len(self.candidates),
            "classification": self.classification.value,
            "computed_count": self.computed_count,
            "conflict_count": self.conflict_count,
            "disclaimer": self.disclaimer,
            "disposition": self.disposition.value,
            "docket_export_allowed": self.docket_export_gate.export_allowed,
            "is_docket_entry": False,
            "is_final_deadline_assertion": False,
            "is_review_only": True,
            "matter_id": self.matter_id,
            "output_kind": self.output_kind,
            "reason_codes": list(self.reason_codes),
            "requires_named_confirmation": (
                self.docket_export_gate.requires_named_confirmation
            ),
            "review_state": self.review_state.value,
            "schema_version": self.schema_version,
            "unknown_count": self.unknown_count,
            "warnings": list(self.warnings),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "DeadlineAnalysisResult":
        if not isinstance(value, Mapping):
            raise TypeError("DeadlineAnalysisResult must be a mapping")
        assumptions_raw = value.get("assumptions")
        return cls(
            schema_version=value.get("schema_version", DEADLINE_SCHEMA_VERSION),
            analysis_id=value.get("analysis_id", ""),
            matter_id=value.get("matter_id"),
            disposition=value.get("disposition", DeadlineDisposition.UNKNOWN.value),
            review_state=value.get("review_state", ReviewState.REQUIRED.value),
            classification=value.get(
                "classification", DisclosureClassification.UNKNOWN.value
            ),
            output_kind=value.get(
                "output_kind", OUTPUT_KIND_REVIEW_ONLY_RESPONSE_DATE_CANDIDATES
            ),
            disclaimer=value.get("disclaimer", REVIEW_ONLY_DEADLINE_DISCLAIMER),
            is_review_only=bool(value.get("is_review_only", True)),
            is_final_deadline_assertion=bool(
                value.get("is_final_deadline_assertion", False)
            ),
            is_docket_entry=bool(value.get("is_docket_entry", False)),
            reason_codes=tuple(value.get("reason_codes") or ()),
            warnings=tuple(value.get("warnings") or ()),
            candidates=tuple(
                ResponseDateCandidate.from_dict(c)
                for c in (value.get("candidates") or ())
            ),
            conflicts=tuple(
                DeadlineConflict.from_dict(c) for c in (value.get("conflicts") or ())
            ),
            docket_export_gate=DocketExportGate.from_dict(
                value.get("docket_export_gate")
            ),
            assumptions=DeadlineAssumptions.from_dict(assumptions_raw),
            ruleset_versions=value.get("ruleset_versions") or {},
            labels=value.get("labels") or {},
            text_digest=value.get("text_digest", sha256_hex("")),
            computed_count=int(value.get("computed_count", 0)),
            unknown_count=int(value.get("unknown_count", 0)),
            conflict_count=int(value.get("conflict_count", 0)),
        )


# ---------------------------------------------------------------------------
# Processor
# ---------------------------------------------------------------------------


class DeadlineProcessor:
    """Calculate review-only response-date candidates (PATLAW-044).

    Never writes docket entries or makes final deadline assertions.
    """

    def __init__(
        self,
        *,
        id_factory: Callable[[], str] | None = None,
        bounds: AnalysisBounds | None = None,
        holiday_provider: Callable[[int], frozenset[date]] | None = None,
    ) -> None:
        self._id_factory = id_factory or (lambda: f"dl:{uuid.uuid4().hex[:16]}")
        self.bounds = bounds or AnalysisBounds()
        self._holiday_provider = holiday_provider or us_federal_holidays

    def analyze(
        self,
        value: DeadlineAnalysisInput | Mapping[str, Any] | None = None,
        /,
        **kwargs: Any,
    ) -> DeadlineAnalysisResult:
        if value is None:
            inp = DeadlineAnalysisInput(**kwargs)
        elif isinstance(value, DeadlineAnalysisInput):
            if kwargs:
                raise TypeError("analyze() does not accept kwargs with an input object")
            inp = value
        elif isinstance(value, Mapping):
            if kwargs:
                raise TypeError("analyze() does not accept kwargs with a mapping")
            inp = self._input_from_mapping(value)
        else:
            raise TypeError(
                "value must be DeadlineAnalysisInput, mapping, or None"
            )
        return self._analyze(inp)

    def analyze_many(
        self, inputs: Iterable[DeadlineAnalysisInput | Mapping[str, Any]]
    ) -> tuple[DeadlineAnalysisResult, ...]:
        return tuple(self.analyze(item) for item in inputs)

    def _input_from_mapping(self, value: Mapping[str, Any]) -> DeadlineAnalysisInput:
        sources = tuple(
            DeadlineSourceInput.from_dict(s) for s in (value.get("sources") or ())
        )
        events = tuple(
            StatusEventInput.from_dict(e) for e in (value.get("status_events") or ())
        )
        oa_results: list[OfficeActionResult] = []
        for raw in value.get("office_action_results") or ():
            if isinstance(raw, OfficeActionResult):
                oa_results.append(raw)
            elif isinstance(raw, Mapping):
                oa_results.append(OfficeActionResult.from_dict(raw))
            else:
                raise TypeError(
                    "office_action_results items must be OfficeActionResult or mapping"
                )
        req_results: list[RequirementCompilationResult] = []
        for raw in value.get("requirement_results") or ():
            if isinstance(raw, RequirementCompilationResult):
                req_results.append(raw)
            elif isinstance(raw, Mapping):
                req_results.append(RequirementCompilationResult.from_dict(raw))
            else:
                raise TypeError(
                    "requirement_results items must be RequirementCompilationResult "
                    "or mapping"
                )
        alts = tuple(
            DeadlineAssumptions.from_dict(a)
            for a in (value.get("alternative_assumptions") or ())
        )
        return DeadlineAnalysisInput(
            matter_id=value.get("matter_id"),
            analysis_id=value.get("analysis_id"),
            sources=sources,
            status_events=events,
            office_action_results=tuple(oa_results),
            requirement_results=tuple(req_results),
            mailing_date=value.get("mailing_date"),
            notification_date=value.get("notification_date"),
            assumptions=DeadlineAssumptions.from_dict(value.get("assumptions")),
            alternative_assumptions=alts,
            classification=value.get(
                "classification", DisclosureClassification.UNKNOWN.value
            ),
            labels=value.get("labels") or {},
            emit_extension_variants=bool(value.get("emit_extension_variants", False)),
            max_extension_months=int(value.get("max_extension_months", 3)),
        )

    def _analyze(self, inp: DeadlineAnalysisInput) -> DeadlineAnalysisResult:
        analysis_id = inp.analysis_id or self._id_factory()
        reason_codes: list[str] = [
            DeadlineReasonCode.REVIEW_ONLY.value,
            DeadlineReasonCode.NOT_DOCKET_ENTRY.value,
            DeadlineReasonCode.NOT_FINAL_DEADLINE_ASSERTION.value,
            DeadlineReasonCode.NAMED_CONFIRMATION_REQUIRED.value,
            DeadlineReasonCode.DOCKET_EXPORT_BLOCKED.value,
        ]
        warnings: list[str] = []

        # Collect sources from explicit inputs + OA + requirements.
        sources: list[DeadlineSourceInput] = list(inp.sources)
        for oa in inp.office_action_results:
            sources.extend(self._sources_from_office_action(oa))
        for req in inp.requirement_results:
            sources.extend(self._sources_from_requirement(req, inp.mailing_date))

        classification = inp.classification
        if (
            classification is DisclosureClassification.UNKNOWN
            and inp.office_action_results
        ):
            classification = most_restrictive_classification(
                [oa.classification for oa in inp.office_action_results]
            )

        if requires_quarantine(classification):
            reason_codes.append(DeadlineReasonCode.QUARANTINED.value)
            return self._terminal(
                analysis_id=analysis_id,
                inp=inp,
                disposition=DeadlineDisposition.QUARANTINE,
                review_state=ReviewState.REQUIRED,
                reason_codes=reason_codes,
                warnings=warnings,
                classification=classification,
                candidates=(),
                conflicts=(),
            )

        # Resolve event bases (mailing / notification / status).
        event_bases = self._resolve_event_bases(inp, sources)
        if not event_bases:
            reason_codes.append(DeadlineReasonCode.EVENT_BASIS_MISSING.value)
        else:
            reason_codes.append(DeadlineReasonCode.EVENT_BASIS_RESOLVED.value)
        if len(event_bases) > 1:
            reason_codes.append(DeadlineReasonCode.EVENT_BASIS_CONFLICT.value)

        # Period sources: only response-instruction-like sources with periods,
        # or all sources that carry period data.
        period_sources = self._select_period_sources(sources)
        if not period_sources and not sources:
            reason_codes.append(DeadlineReasonCode.EMPTY_INPUT.value)
            reason_codes.append(DeadlineReasonCode.NO_RESPONSE_INSTRUCTIONS.value)
            return self._terminal(
                analysis_id=analysis_id,
                inp=inp,
                disposition=DeadlineDisposition.EMPTY,
                review_state=ReviewState.REQUIRED,
                reason_codes=reason_codes,
                warnings=["no_deadline_sources"],
                classification=classification,
                candidates=(),
                conflicts=(),
            )

        if not period_sources:
            reason_codes.append(DeadlineReasonCode.PERIOD_MISSING.value)
            reason_codes.append(DeadlineReasonCode.NO_RESPONSE_INSTRUCTIONS.value)
            # Emit unknown candidates per event basis if any.
            unknown_cands = self._unknown_candidates(
                analysis_id=analysis_id,
                event_bases=event_bases or [
                    (EventBasisKind.UNKNOWN, None, "missing", ())
                ],
                sources=sources,
                assumptions=inp.assumptions or DeadlineAssumptions(),
                classification=classification,
                reason="missing_period",
            )
            reason_codes.append(DeadlineReasonCode.UNKNOWN_CANDIDATE.value)
            reason_codes.append(DeadlineReasonCode.HUMAN_REVIEW_REQUIRED.value)
            return self._finish(
                analysis_id=analysis_id,
                inp=inp,
                classification=classification,
                candidates=unknown_cands,
                conflicts=(),
                reason_codes=reason_codes,
                warnings=warnings,
            )

        # Build assumption sets (base + alternatives + optional extension variants).
        assumption_sets = self._build_assumption_sets(inp)

        candidates: list[ResponseDateCandidate] = []
        for src in period_sources:
            for basis_kind, basis_date, basis_source, basis_spans in (
                event_bases
                or [(EventBasisKind.UNKNOWN, None, "missing", ())]
            ):
                for assumptions in assumption_sets:
                    cand = self._compute_candidate(
                        analysis_id=analysis_id,
                        source=src,
                        basis_kind=basis_kind,
                        basis_date=basis_date,
                        basis_source=basis_source,
                        basis_spans=basis_spans,
                        assumptions=assumptions,
                        classification=classification,
                        status_events=inp.status_events,
                    )
                    candidates.append(cand)
                    if len(candidates) >= self.bounds.max_candidates:
                        reason_codes.append(DeadlineReasonCode.CANDIDATE_LIMIT.value)
                        warnings.append("candidate_limit_applied")
                        break
                if len(candidates) >= self.bounds.max_candidates:
                    break
            if len(candidates) >= self.bounds.max_candidates:
                break

        conflicts = self._detect_conflicts(candidates)
        candidates = self._annotate_conflicts(candidates, conflicts)

        if any(c.status is CandidateComputationStatus.COMPUTED for c in candidates):
            reason_codes.append(DeadlineReasonCode.CANDIDATES_EMITTED.value)
            reason_codes.append(DeadlineReasonCode.PERIOD_RESOLVED.value)
        if any(
            c.status
            in (
                CandidateComputationStatus.UNKNOWN,
                CandidateComputationStatus.INCOMPLETE,
            )
            for c in candidates
        ):
            reason_codes.append(DeadlineReasonCode.UNKNOWN_CANDIDATE.value)
        if conflicts:
            reason_codes.append(DeadlineReasonCode.MULTIPLE_CANDIDATES.value)
            reason_codes.append(DeadlineReasonCode.PERIOD_CONFLICT.value)
        if any(c.assumptions for c in candidates):
            reason_codes.append(DeadlineReasonCode.ASSUMPTIONS_RECORDED.value)
        if any(c.source_spans for c in candidates):
            reason_codes.append(DeadlineReasonCode.SOURCE_SPANS_RETAINED.value)
        if any(c.rule_chain for c in candidates):
            reason_codes.append(DeadlineReasonCode.RULE_CHAIN_RECORDED.value)
        if any(
            DeadlineReasonCode.WEEKEND_ADJUSTED.value in c.reason_codes
            for c in candidates
        ):
            reason_codes.append(DeadlineReasonCode.WEEKEND_ADJUSTED.value)
        if any(
            DeadlineReasonCode.HOLIDAY_ADJUSTED.value in c.reason_codes
            for c in candidates
        ):
            reason_codes.append(DeadlineReasonCode.HOLIDAY_ADJUSTED.value)
        if any(
            DeadlineReasonCode.EXTENSION_VARIANT.value in c.reason_codes
            for c in candidates
        ):
            reason_codes.append(DeadlineReasonCode.EXTENSION_VARIANT.value)
        if any(c.exceptions for c in candidates):
            reason_codes.append(DeadlineReasonCode.EXCEPTION_UNRESOLVED.value)
        if any(
            UncertaintyKind.STALE_STATUS.value in c.uncertainty_kinds for c in candidates
        ):
            reason_codes.append(DeadlineReasonCode.STALE_STATUS.value)

        reason_codes.append(DeadlineReasonCode.HUMAN_REVIEW_REQUIRED.value)
        if any(c.to_candidate_deadline() is not None for c in candidates):
            reason_codes.append(DeadlineReasonCode.CONTRACT_CANDIDATE_PROJECTED.value)

        return self._finish(
            analysis_id=analysis_id,
            inp=inp,
            classification=classification,
            candidates=tuple(candidates),
            conflicts=tuple(conflicts),
            reason_codes=reason_codes,
            warnings=warnings,
        )

    def _sources_from_office_action(
        self, oa: OfficeActionResult
    ) -> list[DeadlineSourceInput]:
        out: list[DeadlineSourceInput] = []
        mailing = oa.mailing_date
        for cand in oa.candidates:
            if cand.kind is not CandidateKind.RESPONSE_INSTRUCTION:
                # Still accept fee/extension cues only as non-period sources? Skip.
                continue
            out.append(
                DeadlineSourceInput.from_analysis_candidate(
                    cand,
                    artifact_id=oa.artifact_id,
                    action_id=oa.action_id,
                    mailing_date=mailing,
                    classification=oa.classification,
                )
            )
        return out

    def _sources_from_requirement(
        self,
        result: RequirementCompilationResult,
        mailing_date: str | None,
    ) -> list[DeadlineSourceInput]:
        out: list[DeadlineSourceInput] = []
        for pred in result.predicates:
            if not pred.proposed_date_rule and not (
                pred.requirement_type
                and "response" in (pred.requirement_type or "").lower()
            ):
                continue
            out.append(
                DeadlineSourceInput.from_compiled_predicate(
                    pred,
                    artifact_id=result.source_artifact_id,
                    mailing_date=mailing_date,
                )
            )
        return out

    def _select_period_sources(
        self, sources: Sequence[DeadlineSourceInput]
    ) -> list[DeadlineSourceInput]:
        selected: list[DeadlineSourceInput] = []
        for src in sources:
            amount = src.period_amount
            unit = src.period_unit
            if amount is None or unit is None or unit is PeriodUnit.UNKNOWN:
                amount2, unit2, _ = parse_period_surface(
                    src.surface_text, labels=src.labels
                )
                if amount2 is not None:
                    # Rebuild with resolved period (immutable → new object).
                    src = DeadlineSourceInput(
                        source_id=src.source_id,
                        source_span_id=src.source_span_id,
                        surface_text=src.surface_text,
                        response_period_surface=src.response_period_surface
                        or (f"{amount2} {unit2.value}" if unit2 else None),
                        period_amount=amount2,
                        period_unit=unit2,
                        proposed_date_rule=src.proposed_date_rule,
                        legal_citations=src.legal_citations,
                        exceptions=src.exceptions,
                        mailing_date=src.mailing_date,
                        notification_date=src.notification_date,
                        action_id=src.action_id,
                        artifact_id=src.artifact_id,
                        requirement_type=src.requirement_type,
                        confidence=src.confidence,
                        classification=src.classification,
                        labels=dict(src.labels),
                    )
            if src.period_amount is not None and src.period_unit not in (
                None,
                PeriodUnit.UNKNOWN,
            ):
                selected.append(src)
        return selected

    def _resolve_event_bases(
        self,
        inp: DeadlineAnalysisInput,
        sources: Sequence[DeadlineSourceInput],
    ) -> list[tuple[EventBasisKind, date | None, str, tuple[SourceSpanRef, ...]]]:
        """Collect distinct event bases; conflicts → multiple entries."""
        found: list[tuple[EventBasisKind, date, str, tuple[SourceSpanRef, ...]]] = []
        seen_keys: set[str] = set()

        def _add(
            kind: EventBasisKind,
            d: date,
            source: str,
            spans: tuple[SourceSpanRef, ...] = (),
        ) -> None:
            key = f"{kind.value}:{d.isoformat()}:{source}"
            if key in seen_keys:
                return
            seen_keys.add(key)
            found.append((kind, d, source, spans))

        if inp.mailing_date:
            d = parse_date_surface(inp.mailing_date)
            if d is not None:
                _add(EventBasisKind.MAILING_DATE, d, "input.mailing_date")
        if inp.notification_date:
            d = parse_date_surface(inp.notification_date)
            if d is not None:
                _add(EventBasisKind.NOTIFICATION_DATE, d, "input.notification_date")

        for oa in inp.office_action_results:
            if oa.mailing_date:
                d = parse_date_surface(oa.mailing_date)
                if d is not None:
                    _add(
                        EventBasisKind.MAILING_DATE,
                        d,
                        f"office_action:{oa.action_id or oa.analysis_id}",
                    )

        for src in sources:
            if src.mailing_date:
                d = parse_date_surface(src.mailing_date)
                if d is not None:
                    spans = ()
                    if src.source_span_id:
                        spans = (
                            SourceSpanRef(
                                span_id=src.source_span_id,
                                artifact_id=src.artifact_id,
                                role="mailing_date_source",
                                text_digest=_text_digest(src.surface_text)
                                if src.surface_text
                                else None,
                                surface_excerpt=None,
                            ),
                        )
                    _add(
                        EventBasisKind.MAILING_DATE,
                        d,
                        f"source:{src.source_id}",
                        spans,
                    )
            if src.notification_date:
                d = parse_date_surface(src.notification_date)
                if d is not None:
                    _add(
                        EventBasisKind.NOTIFICATION_DATE,
                        d,
                        f"source:{src.source_id}",
                    )

        for ev in inp.status_events:
            if not ev.is_mailing_or_notification:
                continue
            d = parse_date_surface(ev.event_date)
            if d is None:
                continue
            kind = EventBasisKind.STATUS_EVENT
            _add(kind, d, f"status_event:{ev.event_id}")

        # Deduplicate by date+kind only for return shape with date|None.
        # Keep all distinct (kind, date) pairs — same date different sources
        # collapse to one basis with multi source label when same kind+date.
        collapsed: dict[tuple[str, str], tuple[EventBasisKind, date, str, tuple[SourceSpanRef, ...]]] = {}
        for kind, d, source, spans in found:
            key = (kind.value, d.isoformat())
            if key not in collapsed:
                collapsed[key] = (kind, d, source, spans)
            else:
                prev = collapsed[key]
                merged_source = prev[2]
                if source not in merged_source:
                    merged_source = f"{merged_source}|{source}"
                merged_spans = prev[3] + spans
                collapsed[key] = (kind, d, merged_source, merged_spans)

        return [
            (k, d, s, spans) for (k, d, s, spans) in collapsed.values()
        ]

    def _build_assumption_sets(
        self, inp: DeadlineAnalysisInput
    ) -> list[DeadlineAssumptions]:
        base = inp.assumptions or DeadlineAssumptions()
        sets: list[DeadlineAssumptions] = [base]
        for alt in inp.alternative_assumptions:
            sets.append(alt)
        if inp.emit_extension_variants:
            max_ext = min(inp.max_extension_months, 5)
            existing_ext = {
                a.extension_months for a in sets if a.extension_months is not None
            }
            for months in range(0, max_ext + 1):
                if months in existing_ext:
                    continue
                sets.append(
                    DeadlineAssumptions(
                        entity_status=base.entity_status,
                        extension_months=months,
                        extension_label=f"extension_{months}_month"
                        if months
                        else "no_extension",
                        fee_assumption=base.fee_assumption
                        or (
                            f"1.136(a)_{months}_month_fee"
                            if months
                            else "no_extension_fee"
                        ),
                        time_zone=base.time_zone,
                        calendar=base.calendar,
                        apply_weekend_holiday=base.apply_weekend_holiday,
                        extra_holidays=base.extra_holidays,
                        exclude_holidays=base.exclude_holidays,
                        end_of_day_local=base.end_of_day_local,
                        notes=base.notes + ("extension_variant",),
                    )
                )
                existing_ext.add(months)
        return sets

    def _holiday_set(
        self, year: int, assumptions: DeadlineAssumptions
    ) -> frozenset[date]:
        holidays = set(self._holiday_provider(year))
        # Include neighbors for period edges.
        holidays |= set(self._holiday_provider(year - 1))
        holidays |= set(self._holiday_provider(year + 1))
        for raw in assumptions.extra_holidays:
            d = parse_date_surface(raw)
            if d is not None:
                holidays.add(d)
        for raw in assumptions.exclude_holidays:
            d = parse_date_surface(raw)
            if d is not None:
                holidays.discard(d)
        return frozenset(holidays)

    def _compute_candidate(
        self,
        *,
        analysis_id: str,
        source: DeadlineSourceInput,
        basis_kind: EventBasisKind,
        basis_date: date | None,
        basis_source: str,
        basis_spans: tuple[SourceSpanRef, ...],
        assumptions: DeadlineAssumptions,
        classification: DisclosureClassification,
        status_events: Sequence[StatusEventInput],
    ) -> ResponseDateCandidate:
        candidate_id = self._id_factory()
        reason_codes: list[str] = [
            DeadlineReasonCode.REVIEW_ONLY.value,
            DeadlineReasonCode.NOT_DOCKET_ENTRY.value,
            DeadlineReasonCode.NOT_FINAL_DEADLINE_ASSERTION.value,
        ]
        uncertainty: list[str] = []
        assumption_map: dict[str, str] = {
            "calendar": assumptions.calendar,
            "time_zone": assumptions.time_zone,
            "apply_weekend_holiday": str(assumptions.apply_weekend_holiday).lower(),
            "end_of_day_local": assumptions.end_of_day_local,
        }
        if assumptions.entity_status:
            assumption_map["entity_status"] = assumptions.entity_status
            uncertainty.append(UncertaintyKind.ENTITY_STATUS_ASSUMED.value)
            reason_codes.append(DeadlineReasonCode.ENTITY_STATUS_ASSUMED.value)
        ext_label = assumptions.extension_assumption_label()
        if ext_label:
            assumption_map["extension"] = ext_label
            if assumptions.extension_months and assumptions.extension_months > 0:
                uncertainty.append(UncertaintyKind.EXTENSION_ASSUMED.value)
                reason_codes.append(DeadlineReasonCode.EXTENSION_VARIANT.value)
        if assumptions.fee_assumption:
            assumption_map["fee"] = assumptions.fee_assumption
            uncertainty.append(UncertaintyKind.FEE_ASSUMED.value)
            reason_codes.append(DeadlineReasonCode.FEE_ASSUMED.value)
        uncertainty.append(UncertaintyKind.TIME_ZONE_ASSUMED.value)
        assumption_map["time_zone_offset"] = "fixed_utc-5_for_America/New_York"

        source_spans: list[SourceSpanRef] = list(basis_spans)
        if source.source_span_id:
            source_spans.append(
                SourceSpanRef(
                    span_id=source.source_span_id,
                    artifact_id=source.artifact_id,
                    role="response_instruction",
                    text_digest=_text_digest(source.surface_text)
                    if source.surface_text
                    else None,
                    surface_excerpt=(
                        (source.response_period_surface or source.surface_text or "")[
                            :200
                        ]
                        or None
                    ),
                )
            )
        # Bound spans.
        source_spans = source_spans[: self.bounds.max_source_spans]

        exceptions = tuple(source.exceptions)
        if exceptions:
            uncertainty.append(UncertaintyKind.UNRESOLVED_EXCEPTION.value)
            reason_codes.append(DeadlineReasonCode.EXCEPTION_UNRESOLVED.value)

        for ev in status_events:
            if ev.is_stale:
                uncertainty.append(UncertaintyKind.STALE_STATUS.value)
                reason_codes.append(DeadlineReasonCode.STALE_STATUS.value)
                assumption_map["status_freshness"] = "stale"
                break

        period_amount = source.period_amount
        period_unit = source.period_unit
        if isinstance(period_unit, str):
            period_unit = _coerce_enum(PeriodUnit, period_unit, "period_unit")  # type: ignore[assignment]
        period_surface = source.response_period_surface

        rule_chain: list[str] = []
        if source.proposed_date_rule:
            rule_chain.append(source.proposed_date_rule)
        rule_chain.append(RULE_37_CFR_1_134)
        rule_chain.append(RULE_SHORTENED_STATUTORY_PERIOD)
        rule_chain.append(RULE_CALENDAR_MONTH_PERIOD)
        if assumptions.apply_weekend_holiday:
            rule_chain.append(RULE_37_CFR_1_7)
            rule_chain.append(RULE_WEEKEND_HOLIDAY_ADJUSTMENT)
        if assumptions.extension_months and assumptions.extension_months > 0:
            rule_chain.append(RULE_37_CFR_1_136A)
            rule_chain.append(f"extension_months:{assumptions.extension_months}")
        for cite in source.legal_citations:
            if cite not in rule_chain:
                rule_chain.append(cite[:128])

        # Incomplete: missing basis or period.
        if basis_date is None or basis_kind is EventBasisKind.UNKNOWN:
            uncertainty.append(UncertaintyKind.MISSING_EVENT_BASIS.value)
            reason_codes.append(DeadlineReasonCode.EVENT_BASIS_MISSING.value)
            status = CandidateComputationStatus.INCOMPLETE
            summary = self._uncertainty_summary(uncertainty, "missing event basis")
            return ResponseDateCandidate(
                candidate_id=candidate_id,
                status=status,
                is_review_only=True,
                event_basis_kind=basis_kind,
                event_basis_date=None,
                event_basis_source=basis_source,
                period_amount=period_amount,
                period_unit=period_unit if isinstance(period_unit, PeriodUnit) else None,
                period_surface=period_surface,
                raw_end_date=None,
                adjusted_end_date=None,
                candidate_utc=None,
                calendar_adjustment=CalendarAdjustmentKind.UNKNOWN,
                rule_chain=tuple(rule_chain),
                assumptions=assumption_map,
                uncertainty_kinds=tuple(dict.fromkeys(uncertainty)),
                uncertainty_summary=summary,
                source_spans=tuple(source_spans),
                exceptions=exceptions,
                conflict_group_id=None,
                conflict_peer_ids=(),
                human_review_question=build_human_review_question(
                    candidate_id=candidate_id,
                    event_basis=None,
                    period_surface=period_surface,
                    candidate_date=None,
                    status=status,
                ),
                review_state=ReviewState.REQUIRED,
                classification=classification,
                reason_codes=tuple(dict.fromkeys(reason_codes)),
                labels=dict(source.labels),
                confidence=source.confidence,
                action_id=source.action_id,
                source_id=source.source_id,
            )

        if period_amount is None or period_unit in (None, PeriodUnit.UNKNOWN):
            uncertainty.append(UncertaintyKind.MISSING_PERIOD.value)
            reason_codes.append(DeadlineReasonCode.PERIOD_MISSING.value)
            status = CandidateComputationStatus.INCOMPLETE
            summary = self._uncertainty_summary(uncertainty, "missing period")
            return ResponseDateCandidate(
                candidate_id=candidate_id,
                status=status,
                is_review_only=True,
                event_basis_kind=basis_kind,
                event_basis_date=basis_date.isoformat(),
                event_basis_source=basis_source,
                period_amount=None,
                period_unit=None,
                period_surface=period_surface,
                raw_end_date=None,
                adjusted_end_date=None,
                candidate_utc=None,
                calendar_adjustment=CalendarAdjustmentKind.UNKNOWN,
                rule_chain=tuple(rule_chain),
                assumptions=assumption_map,
                uncertainty_kinds=tuple(dict.fromkeys(uncertainty)),
                uncertainty_summary=summary,
                source_spans=tuple(source_spans),
                exceptions=exceptions,
                conflict_group_id=None,
                conflict_peer_ids=(),
                human_review_question=build_human_review_question(
                    candidate_id=candidate_id,
                    event_basis=basis_date.isoformat(),
                    period_surface=period_surface,
                    candidate_date=None,
                    status=status,
                ),
                review_state=ReviewState.REQUIRED,
                classification=classification,
                reason_codes=tuple(dict.fromkeys(reason_codes)),
                labels=dict(source.labels),
                confidence=source.confidence,
                action_id=source.action_id,
                source_id=source.source_id,
            )

        assert isinstance(period_unit, PeriodUnit)
        assert period_amount is not None

        # Extension adds months to the base period (1.136(a) style assumption).
        total_amount = period_amount
        total_unit = period_unit
        if (
            assumptions.extension_months
            and assumptions.extension_months > 0
            and period_unit is PeriodUnit.MONTHS
        ):
            total_amount = period_amount + assumptions.extension_months
            assumption_map["base_period_months"] = str(period_amount)
            assumption_map["extension_months"] = str(assumptions.extension_months)
            assumption_map["total_period_months"] = str(total_amount)

        raw_end = compute_raw_period_end(basis_date, total_amount, total_unit)
        if raw_end is None:
            uncertainty.append(UncertaintyKind.UNKNOWN.value)
            status = CandidateComputationStatus.UNKNOWN
            summary = self._uncertainty_summary(uncertainty, "period computation failed")
            return ResponseDateCandidate(
                candidate_id=candidate_id,
                status=status,
                is_review_only=True,
                event_basis_kind=basis_kind,
                event_basis_date=basis_date.isoformat(),
                event_basis_source=basis_source,
                period_amount=period_amount,
                period_unit=period_unit,
                period_surface=period_surface,
                raw_end_date=None,
                adjusted_end_date=None,
                candidate_utc=None,
                calendar_adjustment=CalendarAdjustmentKind.UNKNOWN,
                rule_chain=tuple(rule_chain),
                assumptions=assumption_map,
                uncertainty_kinds=tuple(dict.fromkeys(uncertainty)),
                uncertainty_summary=summary,
                source_spans=tuple(source_spans),
                exceptions=exceptions,
                conflict_group_id=None,
                conflict_peer_ids=(),
                human_review_question=build_human_review_question(
                    candidate_id=candidate_id,
                    event_basis=basis_date.isoformat(),
                    period_surface=period_surface,
                    candidate_date=None,
                    status=status,
                ),
                review_state=ReviewState.REQUIRED,
                classification=classification,
                reason_codes=tuple(dict.fromkeys(reason_codes)),
                labels=dict(source.labels),
                confidence=source.confidence,
                action_id=source.action_id,
                source_id=source.source_id,
            )

        holidays = self._holiday_set(raw_end.year, assumptions)
        uncertainty.append(UncertaintyKind.HOLIDAY_SET_INCOMPLETE.value)
        assumption_map["holiday_set"] = "us_federal_observed"

        adjusted, adj_kind, adj_reasons = adjust_period_end(
            raw_end,
            holidays=holidays,
            apply_weekend_holiday=assumptions.apply_weekend_holiday,
        )
        reason_codes.extend(adj_reasons)

        candidate_utc = candidate_local_end_to_utc_iso(
            adjusted,
            time_zone=assumptions.time_zone,
        )

        status = CandidateComputationStatus.COMPUTED
        if exceptions:
            # Still computed but flagged.
            pass
        summary = self._uncertainty_summary(
            uncertainty,
            f"review-only candidate {adjusted.isoformat()}",
        )

        return ResponseDateCandidate(
            candidate_id=candidate_id,
            status=status,
            is_review_only=True,
            event_basis_kind=basis_kind,
            event_basis_date=basis_date.isoformat(),
            event_basis_source=basis_source,
            period_amount=period_amount,
            period_unit=period_unit,
            period_surface=period_surface or f"{period_amount} {period_unit.value}",
            raw_end_date=raw_end.isoformat(),
            adjusted_end_date=adjusted.isoformat(),
            candidate_utc=candidate_utc,
            calendar_adjustment=adj_kind,
            rule_chain=tuple(dict.fromkeys(rule_chain)),
            assumptions=assumption_map,
            uncertainty_kinds=tuple(dict.fromkeys(uncertainty)),
            uncertainty_summary=summary,
            source_spans=tuple(source_spans),
            exceptions=exceptions,
            conflict_group_id=None,
            conflict_peer_ids=(),
            human_review_question=build_human_review_question(
                candidate_id=candidate_id,
                event_basis=basis_date.isoformat(),
                period_surface=period_surface,
                candidate_date=adjusted.isoformat(),
                status=status,
            ),
            review_state=ReviewState.REQUIRED,
            classification=classification,
            reason_codes=tuple(dict.fromkeys(reason_codes)),
            labels=dict(source.labels),
            confidence=source.confidence,
            action_id=source.action_id,
            source_id=source.source_id,
        )

    def _unknown_candidates(
        self,
        *,
        analysis_id: str,
        event_bases: Sequence[
            tuple[EventBasisKind, date | None, str, tuple[SourceSpanRef, ...]]
        ],
        sources: Sequence[DeadlineSourceInput],
        assumptions: DeadlineAssumptions,
        classification: DisclosureClassification,
        reason: str,
    ) -> tuple[ResponseDateCandidate, ...]:
        out: list[ResponseDateCandidate] = []
        span_sources = sources[:1]
        for basis_kind, basis_date, basis_source, basis_spans in event_bases:
            candidate_id = self._id_factory()
            spans = list(basis_spans)
            for src in span_sources:
                if src.source_span_id:
                    spans.append(
                        SourceSpanRef(
                            span_id=src.source_span_id,
                            artifact_id=src.artifact_id,
                            role="instruction",
                            text_digest=_text_digest(src.surface_text)
                            if src.surface_text
                            else None,
                        )
                    )
            assumption_map = {
                "calendar": assumptions.calendar,
                "time_zone": assumptions.time_zone,
                "reason": reason,
            }
            if assumptions.entity_status:
                assumption_map["entity_status"] = assumptions.entity_status
            status = CandidateComputationStatus.UNKNOWN
            out.append(
                ResponseDateCandidate(
                    candidate_id=candidate_id,
                    status=status,
                    is_review_only=True,
                    event_basis_kind=basis_kind,
                    event_basis_date=basis_date.isoformat() if basis_date else None,
                    event_basis_source=basis_source,
                    period_amount=None,
                    period_unit=None,
                    period_surface=None,
                    raw_end_date=None,
                    adjusted_end_date=None,
                    candidate_utc=None,
                    calendar_adjustment=CalendarAdjustmentKind.UNKNOWN,
                    rule_chain=(RULE_37_CFR_1_134,),
                    assumptions=assumption_map,
                    uncertainty_kinds=(
                        UncertaintyKind.MISSING_PERIOD.value,
                        UncertaintyKind.UNKNOWN.value,
                    ),
                    uncertainty_summary=f"unknown: {reason}",
                    source_spans=tuple(spans[: self.bounds.max_source_spans]),
                    exceptions=(),
                    conflict_group_id=None,
                    conflict_peer_ids=(),
                    human_review_question=build_human_review_question(
                        candidate_id=candidate_id,
                        event_basis=basis_date.isoformat() if basis_date else None,
                        period_surface=None,
                        candidate_date=None,
                        status=status,
                    ),
                    review_state=ReviewState.REQUIRED,
                    classification=classification,
                    reason_codes=(
                        DeadlineReasonCode.REVIEW_ONLY.value,
                        DeadlineReasonCode.UNKNOWN_CANDIDATE.value,
                        DeadlineReasonCode.PERIOD_MISSING.value,
                    ),
                    labels={},
                )
            )
        return tuple(out)

    def _detect_conflicts(
        self, candidates: Sequence[ResponseDateCandidate]
    ) -> list[DeadlineConflict]:
        """Expose conflicts: differing adjusted dates or event bases/periods."""
        conflicts: list[DeadlineConflict] = []
        computed = [
            c
            for c in candidates
            if c.status is CandidateComputationStatus.COMPUTED and c.adjusted_end_date
        ]
        if len(computed) < 2:
            return conflicts

        # Group by adjusted end date.
        by_date: dict[str, list[ResponseDateCandidate]] = {}
        for c in computed:
            by_date.setdefault(c.adjusted_end_date or "", []).append(c)

        if len(by_date) > 1:
            ids = [c.candidate_id for c in computed]
            dates = sorted(by_date.keys())
            conflicts.append(
                DeadlineConflict(
                    conflict_id=f"conflict:dates:{sha256_hex('|'.join(dates))[:12]}",
                    kind="conflicting_candidate_dates",
                    candidate_ids=tuple(ids),
                    detail=(
                        "Multiple distinct adjusted end dates: "
                        + ", ".join(dates)
                        + ". Show all candidates; do not pick silently."
                    ),
                    source_span_ids=tuple(
                        dict.fromkeys(
                            s.span_id
                            for c in computed
                            for s in c.source_spans
                            if s.span_id
                        )
                    ),
                )
            )

        # Conflicting event bases among computed.
        bases = {
            (c.event_basis_kind.value, c.event_basis_date or "")
            for c in computed
        }
        if len(bases) > 1:
            ids = [c.candidate_id for c in computed]
            conflicts.append(
                DeadlineConflict(
                    conflict_id=f"conflict:basis:{sha256_hex(str(sorted(bases)))[:12]}",
                    kind="conflicting_event_basis",
                    candidate_ids=tuple(ids),
                    detail=(
                        "Multiple event bases used for candidates: "
                        + "; ".join(f"{k}:{d}" for k, d in sorted(bases))
                    ),
                )
            )

        # Conflicting periods.
        periods = {
            (c.period_amount, c.period_unit.value if c.period_unit else None)
            for c in computed
        }
        if len(periods) > 1:
            ids = [c.candidate_id for c in computed]
            conflicts.append(
                DeadlineConflict(
                    conflict_id=f"conflict:period:{sha256_hex(str(sorted(periods, key=str)))[:12]}",
                    kind="conflicting_period",
                    candidate_ids=tuple(ids),
                    detail="Multiple response periods stated across sources.",
                )
            )

        return conflicts

    def _annotate_conflicts(
        self,
        candidates: Sequence[ResponseDateCandidate],
        conflicts: Sequence[DeadlineConflict],
    ) -> list[ResponseDateCandidate]:
        if not conflicts:
            return list(candidates)
        # Map candidate_id → conflict peers / group.
        peer_map: dict[str, set[str]] = {}
        group_map: dict[str, str] = {}
        for conf in conflicts:
            for cid in conf.candidate_ids:
                peer_map.setdefault(cid, set()).update(
                    x for x in conf.candidate_ids if x != cid
                )
                group_map[cid] = conf.conflict_id
        out: list[ResponseDateCandidate] = []
        for c in candidates:
            peers = peer_map.get(c.candidate_id)
            if not peers:
                out.append(c)
                continue
            # Rebuild with conflict annotation; mark CONFLICT only when dates differ.
            status = c.status
            if c.status is CandidateComputationStatus.COMPUTED and any(
                conf.kind == "conflicting_candidate_dates" for conf in conflicts
            ):
                status = CandidateComputationStatus.CONFLICT
            uncertainty = list(c.uncertainty_kinds)
            if UncertaintyKind.MULTIPLE_CANDIDATES.value not in uncertainty:
                uncertainty.append(UncertaintyKind.MULTIPLE_CANDIDATES.value)
            reasons = list(c.reason_codes)
            if DeadlineReasonCode.MULTIPLE_CANDIDATES.value not in reasons:
                reasons.append(DeadlineReasonCode.MULTIPLE_CANDIDATES.value)
            group = group_map.get(c.candidate_id)
            out.append(
                ResponseDateCandidate(
                    candidate_id=c.candidate_id,
                    status=status,
                    is_review_only=True,
                    event_basis_kind=c.event_basis_kind,
                    event_basis_date=c.event_basis_date,
                    event_basis_source=c.event_basis_source,
                    period_amount=c.period_amount,
                    period_unit=c.period_unit,
                    period_surface=c.period_surface,
                    raw_end_date=c.raw_end_date,
                    adjusted_end_date=c.adjusted_end_date,
                    candidate_utc=c.candidate_utc,
                    calendar_adjustment=c.calendar_adjustment,
                    rule_chain=c.rule_chain,
                    assumptions=dict(c.assumptions),
                    uncertainty_kinds=tuple(uncertainty),
                    uncertainty_summary=c.uncertainty_summary,
                    source_spans=c.source_spans,
                    exceptions=c.exceptions,
                    conflict_group_id=group,
                    conflict_peer_ids=tuple(sorted(peers)),
                    human_review_question=build_human_review_question(
                        candidate_id=c.candidate_id,
                        event_basis=c.event_basis_date,
                        period_surface=c.period_surface,
                        candidate_date=c.adjusted_end_date,
                        status=status,
                        conflict_ids=tuple(sorted(peers)),
                    ),
                    review_state=ReviewState.REQUIRED,
                    classification=c.classification,
                    reason_codes=tuple(dict.fromkeys(reasons)),
                    labels=dict(c.labels),
                    confidence=c.confidence,
                    action_id=c.action_id,
                    source_id=c.source_id,
                )
            )
        return out

    def _uncertainty_summary(
        self, kinds: Sequence[str], fallback: str
    ) -> str:
        if not kinds:
            return fallback[:256]
        unique = list(dict.fromkeys(kinds))
        return ("review-only; " + ", ".join(unique) + f"; {fallback}")[:256]

    def _disposition_for(
        self,
        candidates: Sequence[ResponseDateCandidate],
        conflicts: Sequence[DeadlineConflict],
        classification: DisclosureClassification,
    ) -> tuple[DeadlineDisposition, ReviewState]:
        if requires_quarantine(classification):
            return DeadlineDisposition.QUARANTINE, ReviewState.REQUIRED
        if not candidates:
            return DeadlineDisposition.EMPTY, ReviewState.REQUIRED
        if conflicts:
            return DeadlineDisposition.MULTIPLE, ReviewState.REQUIRED
        statuses = {c.status for c in candidates}
        if CandidateComputationStatus.CONFLICT in statuses:
            return DeadlineDisposition.MULTIPLE, ReviewState.REQUIRED
        computed = sum(
            1 for c in candidates if c.status is CandidateComputationStatus.COMPUTED
        )
        unknownish = sum(
            1
            for c in candidates
            if c.status
            in (
                CandidateComputationStatus.UNKNOWN,
                CandidateComputationStatus.INCOMPLETE,
            )
        )
        if computed and unknownish:
            return DeadlineDisposition.PARTIAL, ReviewState.REQUIRED
        if computed == 0:
            return DeadlineDisposition.UNKNOWN, ReviewState.REQUIRED
        if computed > 1:
            # Multiple extension variants without date conflict still MULTIPLE
            # if distinct adjusted dates; else COMPUTED with review.
            dates = {
                c.adjusted_end_date
                for c in candidates
                if c.status is CandidateComputationStatus.COMPUTED
            }
            if len(dates) > 1:
                return DeadlineDisposition.MULTIPLE, ReviewState.REQUIRED
            return DeadlineDisposition.COMPUTED, ReviewState.REQUIRED
        return DeadlineDisposition.COMPUTED, ReviewState.REQUIRED

    def _content_digest(
        self, candidates: Sequence[ResponseDateCandidate]
    ) -> str:
        payload = {
            "candidates": [
                {
                    "id": c.candidate_id,
                    "status": c.status.value,
                    "basis": c.event_basis_date,
                    "end": c.adjusted_end_date,
                    "utc": c.candidate_utc,
                    "rules": list(c.rule_chain),
                }
                for c in candidates
            ],
            "schema": DEADLINE_SCHEMA_VERSION,
            "ruleset": DEADLINE_RULESET_VERSION,
        }
        return sha256_hex(canonical_json(payload))

    def _finish(
        self,
        *,
        analysis_id: str,
        inp: DeadlineAnalysisInput,
        classification: DisclosureClassification,
        candidates: Sequence[ResponseDateCandidate],
        conflicts: Sequence[DeadlineConflict],
        reason_codes: Sequence[str],
        warnings: Sequence[str],
    ) -> DeadlineAnalysisResult:
        disposition, review_state = self._disposition_for(
            candidates, conflicts, classification
        )
        computed = sum(
            1 for c in candidates if c.status is CandidateComputationStatus.COMPUTED
        )
        # Count CONFLICT with a date as computed-for-export projection purposes.
        computed += sum(
            1
            for c in candidates
            if c.status is CandidateComputationStatus.CONFLICT and c.candidate_utc
        )
        unknown = sum(
            1
            for c in candidates
            if c.status
            in (
                CandidateComputationStatus.UNKNOWN,
                CandidateComputationStatus.INCOMPLETE,
            )
        )
        return DeadlineAnalysisResult(
            schema_version=DEADLINE_SCHEMA_VERSION,
            analysis_id=analysis_id,
            matter_id=inp.matter_id,
            disposition=disposition,
            review_state=review_state,
            classification=classification,
            output_kind=OUTPUT_KIND_REVIEW_ONLY_RESPONSE_DATE_CANDIDATES,
            disclaimer=REVIEW_ONLY_DEADLINE_DISCLAIMER,
            is_review_only=True,
            is_final_deadline_assertion=False,
            is_docket_entry=False,
            reason_codes=tuple(dict.fromkeys(reason_codes)),
            warnings=tuple(warnings),
            candidates=tuple(candidates),
            conflicts=tuple(conflicts),
            docket_export_gate=DocketExportGate.blocked(),
            assumptions=inp.assumptions or DeadlineAssumptions(),
            ruleset_versions={
                "deadline": DEADLINE_RULESET_VERSION,
                "deadline_processor": DEADLINE_SCHEMA_VERSION,
                "contracts": CONTRACTS_SCHEMA_VERSION,
            },
            labels=dict(inp.labels),
            text_digest=self._content_digest(candidates),
            computed_count=computed,
            unknown_count=unknown,
            conflict_count=len(conflicts),
        )

    def _terminal(
        self,
        *,
        analysis_id: str,
        inp: DeadlineAnalysisInput,
        disposition: DeadlineDisposition,
        review_state: ReviewState,
        reason_codes: Sequence[str],
        warnings: Sequence[str],
        classification: DisclosureClassification,
        candidates: Sequence[ResponseDateCandidate],
        conflicts: Sequence[DeadlineConflict],
    ) -> DeadlineAnalysisResult:
        return DeadlineAnalysisResult(
            schema_version=DEADLINE_SCHEMA_VERSION,
            analysis_id=analysis_id,
            matter_id=inp.matter_id,
            disposition=disposition,
            review_state=review_state,
            classification=classification,
            output_kind=OUTPUT_KIND_REVIEW_ONLY_RESPONSE_DATE_CANDIDATES,
            disclaimer=REVIEW_ONLY_DEADLINE_DISCLAIMER,
            is_review_only=True,
            is_final_deadline_assertion=False,
            is_docket_entry=False,
            reason_codes=tuple(dict.fromkeys(reason_codes)),
            warnings=tuple(warnings),
            candidates=tuple(candidates),
            conflicts=tuple(conflicts),
            docket_export_gate=DocketExportGate.blocked(),
            assumptions=inp.assumptions or DeadlineAssumptions(),
            ruleset_versions={
                "deadline": DEADLINE_RULESET_VERSION,
                "deadline_processor": DEADLINE_SCHEMA_VERSION,
                "contracts": CONTRACTS_SCHEMA_VERSION,
            },
            labels=dict(inp.labels),
            text_digest=self._content_digest(candidates),
            computed_count=0,
            unknown_count=len(candidates),
            conflict_count=len(conflicts),
        )


def calculate_response_date_candidates(
    value: DeadlineAnalysisInput | Mapping[str, Any] | None = None,
    /,
    **kwargs: Any,
) -> DeadlineAnalysisResult:
    """Module-level convenience wrapper around :class:`DeadlineProcessor`."""
    id_factory = kwargs.pop("id_factory", None)
    bounds = kwargs.pop("bounds", None)
    holiday_provider = kwargs.pop("holiday_provider", None)
    return DeadlineProcessor(
        id_factory=id_factory,
        bounds=bounds,
        holiday_provider=holiday_provider,
    ).analyze(value, **kwargs)


def sources_from_office_action(
    result: OfficeActionResult,
) -> tuple[DeadlineSourceInput, ...]:
    """Project office-action response-instruction candidates into deadline sources."""
    return tuple(DeadlineProcessor()._sources_from_office_action(result))


def confirm_for_docket_export(
    result: DeadlineAnalysisResult,
    confirmed_by: str,
    *,
    confirmation_utc: str | None = None,
    confirmation_note: str | None = None,
) -> DeadlineAnalysisResult:
    """Record named human confirmation allowing docket export of candidates.

    Does **not** write any docket entry. Export remains a downstream concern.
    """
    return result.with_named_confirmation(
        confirmed_by,
        confirmation_utc=confirmation_utc,
        confirmation_note=confirmation_note,
    )


__all__ = [
    "DEADLINE_INTERFACE",
    "DEADLINE_RULESET_VERSION",
    "DEADLINE_SCHEMA_VERSION",
    "DEFAULT_CALENDAR",
    "DEFAULT_TIME_ZONE",
    "OUTPUT_KIND_REVIEW_ONLY_RESPONSE_DATE_CANDIDATES",
    "REVIEW_ONLY_DEADLINE_DISCLAIMER",
    "RULE_37_CFR_1_134",
    "RULE_37_CFR_1_136A",
    "RULE_37_CFR_1_7",
    "AnalysisBounds",
    "CalendarAdjustmentKind",
    "CandidateComputationStatus",
    "DeadlineAnalysisInput",
    "DeadlineAnalysisResult",
    "DeadlineAssumptions",
    "DeadlineConflict",
    "DeadlineDisposition",
    "DeadlineProcessor",
    "DeadlineProcessorError",
    "DeadlineReasonCode",
    "DeadlineSourceInput",
    "DocketExportGate",
    "EventBasisKind",
    "PeriodUnit",
    "ResponseDateCandidate",
    "SourceSpanRef",
    "StatusEventInput",
    "UncertaintyKind",
    "add_calendar_months",
    "adjust_period_end",
    "build_human_review_question",
    "calculate_response_date_candidates",
    "candidate_local_end_to_utc_iso",
    "compute_raw_period_end",
    "confirm_for_docket_export",
    "contains_forbidden_final_deadline_token",
    "next_business_day",
    "parse_date_surface",
    "parse_period_surface",
    "sanitize_deadline_labels",
    "sha256_hex",
    "sources_from_office_action",
    "us_federal_holidays",
]
