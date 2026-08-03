"""Authoritative deadline and closure-calendar snapshots (PATLAW-138).

Materializes sourced federal/USPTO closure and emergency-relief calendars,
computes rule-specific base / extension / maximum candidate dates with
uncertainty bounds, and retains timezone, service channel, trigger,
authority, and as-of provenance.

Design invariants
-----------------
* **Review-only**: never a final docket assertion or counsel replacement.
* **No silent extension assumption**: extension months apply only when the
  caller supplies an explicit assumption; they are never inferred.
* **No service-date inference**: trigger dates must be supplied; missing
  trigger blocks a definitive deadline.
* **Calendar provenance required**: a snapshot without source digests /
  authority citations cannot support a definitive deadline.
* **Separated output**: calculated dates, source-stated dates, assumptions,
  and human confirmation requirements are distinct sections.
* Does **not** mutate the v1 deadline calculator
  (:mod:`deadline_processor`); pure helpers may be reused.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Final, Iterable, Mapping, Sequence

from ipfs_datasets_py.processors.domains.uspto.contracts import (
    CONTRACTS_SCHEMA_VERSION,
    CandidateDeadline,
    DisclosureClassification,
    ReviewState,
    canonical_json,
)
from ipfs_datasets_py.processors.domains.uspto.analysis.deadline_processor import (
    DEFAULT_TIME_ZONE,
    PeriodUnit,
    RULE_37_CFR_1_136A,
    RULE_37_CFR_1_7,
    RULE_WEEKEND_HOLIDAY_ADJUSTMENT,
    add_calendar_days,
    add_calendar_months,
    add_calendar_weeks,
    candidate_local_end_to_utc_iso,
    compute_raw_period_end,
    is_weekend,
    next_business_day,
    parse_date_surface,
    us_federal_holidays,
)

# ---------------------------------------------------------------------------
# Versions / interface
# ---------------------------------------------------------------------------

CALENDAR_SCHEMA_VERSION: Final = "uspto.authoritative-deadline-calendar.v1"
CALENDAR_INTERFACE: Final = "AuthoritativeDeadlineCalendar@1"
RECIPE_SCHEMA_VERSION: Final = "uspto.closure-calendar-recipe.v1"

OUTPUT_KIND_AUTHORITATIVE_DEADLINE_SNAPSHOT: Final = (
    "authoritative_deadline_and_closure_calendar_snapshot"
)

REVIEW_ONLY_CALENDAR_DISCLAIMER: Final = (
    "This output is a review-only candidate-date and closure-calendar "
    "snapshot with explicit assumptions, provenance, and uncertainty. It is "
    "not a docket entry, not a final deadline assertion, not legal advice, "
    "and does not replace docketing counsel. Named human confirmation is "
    "required before any export."
)

DEFAULT_MAX_EXTENSION_MONTHS: Final = 5  # 37 C.F.R. 1.136(a) common maximum
DEFAULT_CALENDAR_ID: Final = "US-federal+USPTO-closure"
DEFAULT_SERVICE_CHANNEL: Final = "unspecified"

_SHA256_RE = re.compile(r"\A[0-9a-f]{64}\Z")
_NONEMPTY_ID_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._:/=+\-]{0,255}\Z")
_WS_RE = re.compile(r"\s+")
_ISO_DATE_RE = re.compile(r"\A\d{4}-\d{2}-\d{2}\Z")

# Recipe path relative to repository root (tests resolve via package or CWD).
DEFAULT_RECIPE_RELATIVE: Final = (
    "tests/fixtures/uspto/deadlines/closure_calendar_recipe.json"
)


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class ClosureKind(str, Enum):
    """Kind of non-business day recorded in a closure calendar."""

    FEDERAL_HOLIDAY = "federal_holiday"
    USPTO_CLOSURE = "uspto_closure"
    EMERGENCY_RELIEF = "emergency_relief"
    WEEKEND = "weekend"
    OTHER = "other"


class TriggerKind(str, Enum):
    MAILING_DATE = "mailing_date"
    NOTIFICATION_DATE = "notification_date"
    STATUS_EVENT = "status_event"
    SOURCE_STATED = "source_stated"
    UNKNOWN = "unknown"


class ServiceChannel(str, Enum):
    MAIL = "mail"
    ELECTRONIC = "electronic"
    FAX = "fax"
    HAND_DELIVERY = "hand_delivery"
    UNSPECIFIED = "unspecified"
    UNKNOWN = "unknown"


class DeadlineComputationStatus(str, Enum):
    COMPUTED = "computed"
    PARTIAL = "partial"
    BLOCKED = "blocked"
    CONFLICT = "conflict"
    UNKNOWN = "unknown"


class DefinitiveBlockReason(str, Enum):
    """Reasons a deadline cannot be treated as definitive."""

    MISSING_TRIGGER = "missing_trigger"
    MISSING_CALENDAR_PROVENANCE = "missing_calendar_provenance"
    MISSING_PERIOD = "missing_period"
    MISSING_AS_OF = "missing_as_of"
    CONFLICTING_DATES = "conflicting_dates"
    EMERGENCY_RELIEF_UNCERTAIN = "emergency_relief_uncertain"
    EXTENSION_NOT_EXPLICIT = "extension_not_explicit"
    STALE_CALENDAR = "stale_calendar"
    HUMAN_CONFIRMATION_REQUIRED = "human_confirmation_required"
    UNKNOWN = "unknown"


class DateRole(str, Enum):
    """Semantic role of a date surface in the separated output."""

    CALCULATED_BASE = "calculated_base"
    CALCULATED_BASE_ADJUSTED = "calculated_base_adjusted"
    CALCULATED_EXTENSION = "calculated_extension"
    CALCULATED_MAXIMUM = "calculated_maximum"
    CALCULATED_EMERGENCY = "calculated_emergency"
    SOURCE_STATED = "source_stated"
    TRIGGER = "trigger"
    UNCERTAINTY_LOWER = "uncertainty_lower"
    UNCERTAINTY_UPPER = "uncertainty_upper"


class CalendarReasonCode(str, Enum):
    SNAPSHOT_MATERIALIZED = "snapshot_materialized"
    REVIEW_ONLY = "review_only"
    NOT_DOCKET_ENTRY = "not_docket_entry"
    NOT_FINAL_DEADLINE_ASSERTION = "not_final_deadline_assertion"
    NAMED_CONFIRMATION_REQUIRED = "named_confirmation_required"
    DEFINITIVE_BLOCKED = "definitive_blocked"
    DEFINITIVE_ALLOWED_AFTER_CONFIRMATION = "definitive_allowed_after_confirmation"
    MISSING_TRIGGER = "missing_trigger"
    MISSING_CALENDAR_PROVENANCE = "missing_calendar_provenance"
    MISSING_PERIOD = "missing_period"
    WEEKEND_ADJUSTED = "weekend_adjusted"
    HOLIDAY_ADJUSTED = "holiday_adjusted"
    USPTO_CLOSURE_ADJUSTED = "uspto_closure_adjusted"
    EMERGENCY_RELIEF_APPLIED = "emergency_relief_applied"
    EXTENSION_EXPLICIT = "extension_explicit"
    EXTENSION_NOT_ASSUMED = "extension_not_assumed"
    CONFLICTING_SOURCE_STATED = "conflicting_source_stated"
    FEDERAL_HOLIDAYS_SEEDED = "federal_holidays_seeded"
    PROVENANCE_RECORDED = "provenance_recorded"
    ASSUMPTIONS_SEPARATED = "assumptions_separated"
    CALCULATED_DATES_SEPARATED = "calculated_dates_separated"
    SOURCE_STATED_DATES_SEPARATED = "source_stated_dates_separated"
    HUMAN_CONFIRMATION_LISTED = "human_confirmation_listed"
    CONTRACT_CANDIDATE_PROJECTED = "contract_candidate_projected"
    RECIPE_CASE = "recipe_case"


# ---------------------------------------------------------------------------
# Errors / helpers
# ---------------------------------------------------------------------------


class AuthoritativeDeadlineCalendarError(ValueError):
    """Bounded calendar / deadline analysis failure."""

    def __init__(
        self, message: str, *, code: str = "authoritative_deadline_calendar_error"
    ) -> None:
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


def _optional_nonneg_int(value: Any, field: str) -> int | None:
    if value is None:
        return None
    return _nonneg_int(value, field)


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
    value: Any, field: str, *, max_items: int = 64
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


def _iso_date(value: date | str | None, field: str) -> str | None:
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value.isoformat()
    text = _optional_str(value, field, max_len=32)
    if text is None:
        return None
    parsed = parse_date_surface(text)
    if parsed is None:
        raise ValueError(f"{field} is not a parseable date: {text!r}")
    return parsed.isoformat()


def _parse_required_date(value: date | str | None, field: str) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    text = _optional_str(value, field, max_len=32) if not isinstance(value, date) else None
    if isinstance(value, datetime):
        return value.date()
    if text is None:
        raise ValueError(f"{field} is required")
    parsed = parse_date_surface(text)
    if parsed is None:
        raise ValueError(f"{field} is not a parseable date: {text!r}")
    return parsed


def _digest_or_none(value: Any, field: str) -> str | None:
    text = _optional_str(value, field, max_len=64)
    if text is None:
        return None
    text = text.lower()
    if not _SHA256_RE.match(text):
        raise ValueError(f"{field} must be sha256 hex")
    return text


# ---------------------------------------------------------------------------
# Calendar pure helpers (closure-aware; complements v1 helpers)
# ---------------------------------------------------------------------------


def closed_date_set(
    entries: Sequence["ClosureCalendarEntry"],
    *,
    include_kinds: frozenset[ClosureKind] | None = None,
) -> frozenset[date]:
    """Return the set of closed dates from *entries*, optionally filtered."""
    out: set[date] = set()
    for entry in entries:
        if include_kinds is not None and entry.kind not in include_kinds:
            continue
        d = parse_date_surface(entry.closed_date)
        if d is not None:
            out.add(d)
    return frozenset(out)


def is_closed_day(
    d: date,
    *,
    holidays: frozenset[date] | set[date] | None = None,
    closures: frozenset[date] | set[date] | None = None,
) -> bool:
    """True when *d* is a weekend, federal holiday, or USPTO closure day."""
    if is_weekend(d):
        return True
    if holidays and d in holidays:
        return True
    if closures and d in closures:
        return True
    return False


def next_open_business_day(
    d: date,
    *,
    holidays: frozenset[date] | set[date] | None = None,
    closures: frozenset[date] | set[date] | None = None,
) -> date:
    """Advance to the next weekday that is not a holiday or USPTO closure."""
    current = d
    for _ in range(370):
        if not is_closed_day(current, holidays=holidays, closures=closures):
            return current
        current = current + timedelta(days=1)
    return current


def adjust_for_closure_calendar(
    raw_end: date,
    *,
    holidays: frozenset[date] | set[date] | None = None,
    closures: frozenset[date] | set[date] | None = None,
    apply_weekend_holiday: bool = True,
) -> tuple[date, tuple[str, ...], tuple[ClosureKind, ...]]:
    """37 C.F.R. 1.7-style next-open-day adjustment including USPTO closures.

    Returns ``(adjusted_date, reason_codes, hit_kinds)``.
    """
    if not apply_weekend_holiday:
        return raw_end, (), ()
    reasons: list[str] = []
    hits: list[ClosureKind] = []
    weekend_hit = is_weekend(raw_end)
    holiday_hit = bool(holidays and raw_end in holidays)
    closure_hit = bool(closures and raw_end in closures)
    if not weekend_hit and not holiday_hit and not closure_hit:
        return raw_end, (), ()
    adjusted = next_open_business_day(
        raw_end, holidays=holidays, closures=closures
    )
    if weekend_hit:
        reasons.append(CalendarReasonCode.WEEKEND_ADJUSTED.value)
        hits.append(ClosureKind.WEEKEND)
    if holiday_hit:
        reasons.append(CalendarReasonCode.HOLIDAY_ADJUSTED.value)
        hits.append(ClosureKind.FEDERAL_HOLIDAY)
    if closure_hit:
        reasons.append(CalendarReasonCode.USPTO_CLOSURE_ADJUSTED.value)
        hits.append(ClosureKind.USPTO_CLOSURE)
    if adjusted != raw_end:
        reasons.append(RULE_WEEKEND_HOLIDAY_ADJUSTMENT)
        reasons.append(RULE_37_CFR_1_7)
    return adjusted, tuple(dict.fromkeys(reasons)), tuple(hits)


def emergency_relief_extends_to(
    raw_or_adjusted: date,
    emergency_entries: Sequence["ClosureCalendarEntry"],
) -> tuple[date | None, tuple[str, ...]]:
    """If *raw_or_adjusted* falls in an emergency-relief window, return relief end.

    Emergency relief is never invented: only sourced entries of kind
    ``emergency_relief`` with a closed_date / optional relief_end_date apply.
    """
    reasons: list[str] = []
    best: date | None = None
    for entry in emergency_entries:
        if entry.kind is not ClosureKind.EMERGENCY_RELIEF:
            continue
        start = parse_date_surface(entry.closed_date)
        if start is None:
            continue
        end_s = entry.relief_end_date or entry.closed_date
        end = parse_date_surface(end_s)
        if end is None:
            continue
        if start <= raw_or_adjusted <= end:
            # Filing due during emergency: relief typically extends to end+next open.
            candidate = end
            if best is None or candidate > best:
                best = candidate
            reasons.append(CalendarReasonCode.EMERGENCY_RELIEF_APPLIED.value)
            if entry.authority_citation:
                reasons.append(entry.authority_citation)
    return best, tuple(dict.fromkeys(reasons))


def seed_federal_holiday_entries(
    year: int,
    *,
    source_id: str = "seed:us-federal-holidays",
    authority_citation: str = "5 U.S.C. 6103; 37 C.F.R. 1.7",
    source_digest: str | None = None,
) -> tuple["ClosureCalendarEntry", ...]:
    """Build deterministic federal-holiday entries for *year* (and New Year edge)."""
    holidays = sorted(us_federal_holidays(year))
    digest = source_digest or sha256_hex(
        f"us-federal-holidays:{year}:{','.join(d.isoformat() for d in holidays)}"
    )
    entries: list[ClosureCalendarEntry] = []
    for d in holidays:
        if d.year not in (year, year - 1, year + 1):
            continue
        entries.append(
            ClosureCalendarEntry(
                entry_id=f"fed-holiday:{d.isoformat()}",
                closed_date=d.isoformat(),
                kind=ClosureKind.FEDERAL_HOLIDAY,
                label=f"US federal holiday (observed) {d.isoformat()}",
                authority_citation=authority_citation,
                source_id=source_id,
                source_digest=digest,
            )
        )
    return tuple(entries)


# ---------------------------------------------------------------------------
# Value records — provenance / calendar
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CalendarSourceProvenance:
    """Provenance for a closure-calendar source artifact."""

    source_id: str
    source_digest: str | None
    source_url: str | None = None
    provider: str | None = None
    retrieved_at: str | None = None
    authority_citation: str | None = None
    as_of: str | None = None
    notes: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "source_id", _identifier(self.source_id, "source_id")
        )
        object.__setattr__(
            self, "source_digest", _digest_or_none(self.source_digest, "source_digest")
        )
        object.__setattr__(
            self,
            "source_url",
            _optional_str(self.source_url, "source_url", max_len=1024),
        )
        object.__setattr__(
            self, "provider", _optional_str(self.provider, "provider", max_len=128)
        )
        object.__setattr__(
            self,
            "retrieved_at",
            _optional_str(self.retrieved_at, "retrieved_at", max_len=64),
        )
        object.__setattr__(
            self,
            "authority_citation",
            _optional_str(
                self.authority_citation, "authority_citation", max_len=256
            ),
        )
        object.__setattr__(self, "as_of", _iso_date(self.as_of, "as_of"))
        object.__setattr__(
            self, "notes", _optional_str(self.notes, "notes", max_len=512)
        )

    @property
    def has_digest(self) -> bool:
        return bool(self.source_digest)

    def to_dict(self) -> dict[str, Any]:
        return {
            "as_of": self.as_of,
            "authority_citation": self.authority_citation,
            "notes": self.notes,
            "provider": self.provider,
            "retrieved_at": self.retrieved_at,
            "source_digest": self.source_digest,
            "source_id": self.source_id,
            "source_url": self.source_url,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CalendarSourceProvenance":
        if not isinstance(value, Mapping):
            raise TypeError("CalendarSourceProvenance must be a mapping")
        return cls(
            source_id=value.get("source_id", ""),
            source_digest=value.get("source_digest"),
            source_url=value.get("source_url"),
            provider=value.get("provider"),
            retrieved_at=value.get("retrieved_at"),
            authority_citation=value.get("authority_citation"),
            as_of=value.get("as_of"),
            notes=value.get("notes"),
        )


@dataclass(frozen=True, slots=True)
class ClosureCalendarEntry:
    """One closed day or emergency-relief window in a sourced calendar."""

    entry_id: str
    closed_date: str
    kind: ClosureKind
    label: str | None = None
    authority_citation: str | None = None
    source_id: str | None = None
    source_digest: str | None = None
    relief_end_date: str | None = None
    notes: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "entry_id", _identifier(self.entry_id, "entry_id")
        )
        iso = _iso_date(self.closed_date, "closed_date")
        if iso is None:
            raise ValueError("closed_date is required")
        object.__setattr__(self, "closed_date", iso)
        if not isinstance(self.kind, ClosureKind):
            object.__setattr__(
                self, "kind", _coerce_enum(ClosureKind, self.kind, "kind")
            )
        object.__setattr__(
            self, "label", _optional_str(self.label, "label", max_len=256)
        )
        object.__setattr__(
            self,
            "authority_citation",
            _optional_str(
                self.authority_citation, "authority_citation", max_len=256
            ),
        )
        object.__setattr__(
            self, "source_id", _optional_identifier(self.source_id, "source_id")
        )
        object.__setattr__(
            self, "source_digest", _digest_or_none(self.source_digest, "source_digest")
        )
        object.__setattr__(
            self, "relief_end_date", _iso_date(self.relief_end_date, "relief_end_date")
        )
        object.__setattr__(
            self, "notes", _optional_str(self.notes, "notes", max_len=512)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority_citation": self.authority_citation,
            "closed_date": self.closed_date,
            "entry_id": self.entry_id,
            "kind": self.kind.value,
            "label": self.label,
            "notes": self.notes,
            "relief_end_date": self.relief_end_date,
            "source_digest": self.source_digest,
            "source_id": self.source_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ClosureCalendarEntry":
        if not isinstance(value, Mapping):
            raise TypeError("ClosureCalendarEntry must be a mapping")
        return cls(
            entry_id=value.get("entry_id", ""),
            closed_date=value.get("closed_date", ""),
            kind=value.get("kind", ClosureKind.OTHER.value),
            label=value.get("label"),
            authority_citation=value.get("authority_citation"),
            source_id=value.get("source_id"),
            source_digest=value.get("source_digest"),
            relief_end_date=value.get("relief_end_date"),
            notes=value.get("notes"),
        )


@dataclass(frozen=True, slots=True)
class ClosureCalendarSnapshot:
    """Immutable sourced federal/USPTO closure and emergency-relief calendar.

    A snapshot supports definitive deadline computation only when
    :meth:`has_calendar_provenance` is True (at least one source digest and
    non-empty as-of / authority chain).
    """

    snapshot_id: str
    as_of: str
    time_zone: str = DEFAULT_TIME_ZONE
    calendar_id: str = DEFAULT_CALENDAR_ID
    entries: tuple[ClosureCalendarEntry, ...] = ()
    sources: tuple[CalendarSourceProvenance, ...] = ()
    authority_citations: tuple[str, ...] = ()
    materialized_at: str | None = None
    year: int | None = None
    labels: Mapping[str, str] = MappingProxyType({})
    notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "snapshot_id", _identifier(self.snapshot_id, "snapshot_id")
        )
        iso = _iso_date(self.as_of, "as_of")
        if iso is None:
            raise ValueError("as_of is required")
        object.__setattr__(self, "as_of", iso)
        object.__setattr__(
            self,
            "time_zone",
            _require_str(self.time_zone, "time_zone", max_len=64),
        )
        object.__setattr__(
            self,
            "calendar_id",
            _require_str(self.calendar_id, "calendar_id", max_len=128),
        )
        if not isinstance(self.entries, tuple):
            object.__setattr__(self, "entries", tuple(self.entries or ()))
        for i, e in enumerate(self.entries):
            if not isinstance(e, ClosureCalendarEntry):
                raise TypeError(f"entries[{i}] must be ClosureCalendarEntry")
        if not isinstance(self.sources, tuple):
            object.__setattr__(self, "sources", tuple(self.sources or ()))
        for i, s in enumerate(self.sources):
            if not isinstance(s, CalendarSourceProvenance):
                raise TypeError(f"sources[{i}] must be CalendarSourceProvenance")
        object.__setattr__(
            self,
            "authority_citations",
            _tuple_of_str(
                self.authority_citations, "authority_citations", max_items=32
            ),
        )
        object.__setattr__(
            self,
            "materialized_at",
            _optional_str(self.materialized_at, "materialized_at", max_len=64),
        )
        if self.year is not None:
            if isinstance(self.year, bool) or not isinstance(self.year, int):
                raise TypeError("year must be int or None")
            if self.year < 1900 or self.year > 2200:
                raise ValueError("year out of supported range")
        object.__setattr__(
            self, "labels", _frozen_str_map(self.labels, "labels", max_items=32)
        )
        object.__setattr__(
            self, "notes", _tuple_of_str(self.notes, "notes", max_items=32)
        )

    @property
    def has_calendar_provenance(self) -> bool:
        """True when the snapshot carries source digests and as-of provenance."""
        if not self.as_of:
            return False
        if any(s.has_digest for s in self.sources):
            return True
        # Entry-level digests also count when sources list is empty but entries
        # are explicitly sourced (e.g. emergency notice with digest).
        if any(e.source_digest for e in self.entries):
            return bool(self.authority_citations) or any(
                e.authority_citation for e in self.entries
            )
        return False

    def holiday_dates(self) -> frozenset[date]:
        return closed_date_set(
            self.entries,
            include_kinds=frozenset({ClosureKind.FEDERAL_HOLIDAY}),
        )

    def uspto_closure_dates(self) -> frozenset[date]:
        return closed_date_set(
            self.entries,
            include_kinds=frozenset({ClosureKind.USPTO_CLOSURE}),
        )

    def emergency_entries(self) -> tuple[ClosureCalendarEntry, ...]:
        return tuple(
            e for e in self.entries if e.kind is ClosureKind.EMERGENCY_RELIEF
        )

    def content_digest(self) -> str:
        payload = {
            "as_of": self.as_of,
            "authority_citations": list(self.authority_citations),
            "calendar_id": self.calendar_id,
            "entries": [e.to_dict() for e in self.entries],
            "snapshot_id": self.snapshot_id,
            "sources": [s.to_dict() for s in self.sources],
            "time_zone": self.time_zone,
            "year": self.year,
        }
        return sha256_hex(canonical_json(payload))

    def to_dict(self) -> dict[str, Any]:
        return {
            "as_of": self.as_of,
            "authority_citations": list(self.authority_citations),
            "calendar_id": self.calendar_id,
            "content_digest": self.content_digest(),
            "entries": [e.to_dict() for e in self.entries],
            "has_calendar_provenance": self.has_calendar_provenance,
            "labels": dict(self.labels),
            "materialized_at": self.materialized_at,
            "notes": list(self.notes),
            "snapshot_id": self.snapshot_id,
            "sources": [s.to_dict() for s in self.sources],
            "time_zone": self.time_zone,
            "year": self.year,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ClosureCalendarSnapshot":
        if not isinstance(value, Mapping):
            raise TypeError("ClosureCalendarSnapshot must be a mapping")
        entries = tuple(
            ClosureCalendarEntry.from_dict(e)
            for e in (value.get("entries") or ())
        )
        sources = tuple(
            CalendarSourceProvenance.from_dict(s)
            for s in (value.get("sources") or ())
        )
        return cls(
            snapshot_id=value.get("snapshot_id", ""),
            as_of=value.get("as_of", ""),
            time_zone=value.get("time_zone", DEFAULT_TIME_ZONE),
            calendar_id=value.get("calendar_id", DEFAULT_CALENDAR_ID),
            entries=entries,
            sources=sources,
            authority_citations=tuple(value.get("authority_citations") or ()),
            materialized_at=value.get("materialized_at"),
            year=value.get("year"),
            labels=value.get("labels") or {},
            notes=tuple(value.get("notes") or ()),
        )


def materialize_closure_calendar(
    *,
    snapshot_id: str,
    as_of: str | date,
    year: int | None = None,
    uspto_closures: Sequence[Mapping[str, Any] | ClosureCalendarEntry] = (),
    emergency_relief: Sequence[Mapping[str, Any] | ClosureCalendarEntry] = (),
    sources: Sequence[Mapping[str, Any] | CalendarSourceProvenance] = (),
    authority_citations: Sequence[str] = (),
    time_zone: str = DEFAULT_TIME_ZONE,
    calendar_id: str = DEFAULT_CALENDAR_ID,
    seed_federal_holidays: bool = True,
    materialized_at: str | None = None,
    labels: Mapping[str, str] | None = None,
    notes: Sequence[str] = (),
) -> ClosureCalendarSnapshot:
    """Materialize a closure-calendar snapshot with optional federal-holiday seed.

    Federal holidays are deterministic pure functions of *year*. USPTO closures
    and emergency-relief windows must be supplied from sourced inputs — they
    are never invented.
    """
    as_of_date = _parse_required_date(as_of, "as_of")
    y = year if year is not None else as_of_date.year
    entries: list[ClosureCalendarEntry] = []
    if seed_federal_holidays:
        entries.extend(seed_federal_holiday_entries(y))

    def _coerce_entry(
        raw: Mapping[str, Any] | ClosureCalendarEntry, default_kind: ClosureKind
    ) -> ClosureCalendarEntry:
        if isinstance(raw, ClosureCalendarEntry):
            return raw
        data = dict(raw)
        data.setdefault("kind", default_kind.value)
        if "entry_id" not in data or not data["entry_id"]:
            cd = data.get("closed_date", "unknown")
            data["entry_id"] = f"{default_kind.value}:{cd}"
        return ClosureCalendarEntry.from_dict(data)

    for raw in uspto_closures:
        entries.append(_coerce_entry(raw, ClosureKind.USPTO_CLOSURE))
    for raw in emergency_relief:
        entries.append(_coerce_entry(raw, ClosureKind.EMERGENCY_RELIEF))

    # Stable sort: kind then date then id.
    entries.sort(
        key=lambda e: (e.kind.value, e.closed_date, e.entry_id)
    )

    source_objs: list[CalendarSourceProvenance] = []
    for raw in sources:
        if isinstance(raw, CalendarSourceProvenance):
            source_objs.append(raw)
        else:
            source_objs.append(CalendarSourceProvenance.from_dict(raw))

    # When federal holidays are seeded and no source listed for them, add a
    # synthetic provenance record only if a digest can be attached — the seed
    # digest is deterministic. Callers that omit *sources* entirely still get
    # entry-level digests on federal holidays; has_calendar_provenance needs
    # authority_citations or source digests.
    cites = list(authority_citations) if authority_citations else []
    if seed_federal_holidays and RULE_37_CFR_1_7 not in cites:
        cites.append("37 C.F.R. 1.7")
    if seed_federal_holidays and "5 U.S.C. 6103" not in cites:
        cites.append("5 U.S.C. 6103")

    mat_at = materialized_at or datetime.now(timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )

    return ClosureCalendarSnapshot(
        snapshot_id=snapshot_id,
        as_of=as_of_date.isoformat(),
        time_zone=time_zone,
        calendar_id=calendar_id,
        entries=tuple(entries),
        sources=tuple(source_objs),
        authority_citations=tuple(dict.fromkeys(cites)),
        materialized_at=mat_at,
        year=y,
        labels=labels or {},
        notes=tuple(notes),
    )


# ---------------------------------------------------------------------------
# Deadline trigger / request / separated output sections
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DeadlineTrigger:
    """Event basis for period computation — never inferred."""

    kind: TriggerKind
    trigger_date: str | None
    source_id: str | None = None
    source_span_id: str | None = None
    service_channel: ServiceChannel | str = ServiceChannel.UNSPECIFIED
    labels: Mapping[str, str] = MappingProxyType({})

    def __post_init__(self) -> None:
        if not isinstance(self.kind, TriggerKind):
            object.__setattr__(
                self, "kind", _coerce_enum(TriggerKind, self.kind, "kind")
            )
        object.__setattr__(
            self, "trigger_date", _iso_date(self.trigger_date, "trigger_date")
        )
        object.__setattr__(
            self, "source_id", _optional_identifier(self.source_id, "source_id")
        )
        object.__setattr__(
            self,
            "source_span_id",
            _optional_identifier(self.source_span_id, "source_span_id"),
        )
        if not isinstance(self.service_channel, ServiceChannel):
            object.__setattr__(
                self,
                "service_channel",
                _coerce_enum(
                    ServiceChannel, self.service_channel, "service_channel"
                ),
            )
        object.__setattr__(
            self, "labels", _frozen_str_map(self.labels, "labels", max_items=16)
        )

    @property
    def is_present(self) -> bool:
        return self.trigger_date is not None and self.kind is not TriggerKind.UNKNOWN

    def to_dict(self) -> dict[str, Any]:
        return {
            "is_present": self.is_present,
            "kind": self.kind.value,
            "labels": dict(self.labels),
            "service_channel": self.service_channel.value
            if isinstance(self.service_channel, ServiceChannel)
            else str(self.service_channel),
            "source_id": self.source_id,
            "source_span_id": self.source_span_id,
            "trigger_date": self.trigger_date,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any] | None) -> "DeadlineTrigger":
        if value is None:
            return cls(kind=TriggerKind.UNKNOWN, trigger_date=None)
        if not isinstance(value, Mapping):
            raise TypeError("DeadlineTrigger must be a mapping")
        return cls(
            kind=value.get("kind", TriggerKind.UNKNOWN.value),
            trigger_date=value.get("trigger_date"),
            source_id=value.get("source_id"),
            source_span_id=value.get("source_span_id"),
            service_channel=value.get(
                "service_channel", ServiceChannel.UNSPECIFIED.value
            ),
            labels=value.get("labels") or {},
        )

    @classmethod
    def missing(cls) -> "DeadlineTrigger":
        return cls(kind=TriggerKind.UNKNOWN, trigger_date=None)


@dataclass(frozen=True, slots=True)
class SourceStatedDate:
    """A date stated in a source document (not calculated)."""

    role: str
    stated_date: str
    source_id: str | None = None
    source_span_id: str | None = None
    surface_text: str | None = None
    labels: Mapping[str, str] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "role", _require_str(self.role, "role", max_len=64)
        )
        iso = _iso_date(self.stated_date, "stated_date")
        if iso is None:
            raise ValueError("stated_date is required")
        object.__setattr__(self, "stated_date", iso)
        object.__setattr__(
            self, "source_id", _optional_identifier(self.source_id, "source_id")
        )
        object.__setattr__(
            self,
            "source_span_id",
            _optional_identifier(self.source_span_id, "source_span_id"),
        )
        object.__setattr__(
            self,
            "surface_text",
            _optional_str(self.surface_text, "surface_text", max_len=512),
        )
        object.__setattr__(
            self, "labels", _frozen_str_map(self.labels, "labels", max_items=16)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "labels": dict(self.labels),
            "role": self.role,
            "source_id": self.source_id,
            "source_span_id": self.source_span_id,
            "stated_date": self.stated_date,
            "surface_text": self.surface_text,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SourceStatedDate":
        if not isinstance(value, Mapping):
            raise TypeError("SourceStatedDate must be a mapping")
        return cls(
            role=value.get("role", "source_stated"),
            stated_date=value.get("stated_date", ""),
            source_id=value.get("source_id"),
            source_span_id=value.get("source_span_id"),
            surface_text=value.get("surface_text"),
            labels=value.get("labels") or {},
        )


@dataclass(frozen=True, slots=True)
class ExplicitAssumptions:
    """Assumptions that must be recorded separately from calculated dates.

    Extensions are **never** filled in by default. ``extension_months=None``
    means "no extension assumed"; only an explicit integer is applied.
    """

    extension_months: int | None = None
    entity_status: str | None = None
    fee_assumption: str | None = None
    time_zone: str = DEFAULT_TIME_ZONE
    apply_weekend_holiday: bool = True
    max_extension_months: int = DEFAULT_MAX_EXTENSION_MONTHS
    emit_extension_ladder: bool = False
    notes: tuple[str, ...] = ()
    extra: Mapping[str, str] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "extension_months",
            _optional_nonneg_int(self.extension_months, "extension_months"),
        )
        object.__setattr__(
            self,
            "entity_status",
            _optional_str(self.entity_status, "entity_status", max_len=128),
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
        if not isinstance(self.apply_weekend_holiday, bool):
            raise TypeError("apply_weekend_holiday must be bool")
        object.__setattr__(
            self,
            "max_extension_months",
            _nonneg_int(self.max_extension_months, "max_extension_months"),
        )
        if not isinstance(self.emit_extension_ladder, bool):
            raise TypeError("emit_extension_ladder must be bool")
        object.__setattr__(
            self, "notes", _tuple_of_str(self.notes, "notes", max_items=32)
        )
        object.__setattr__(
            self, "extra", _frozen_str_map(self.extra, "extra", max_items=32)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "apply_weekend_holiday": self.apply_weekend_holiday,
            "emit_extension_ladder": self.emit_extension_ladder,
            "entity_status": self.entity_status,
            "extension_months": self.extension_months,
            "extension_policy": (
                "explicit"
                if self.extension_months is not None
                else "not_assumed"
            ),
            "extra": dict(self.extra),
            "fee_assumption": self.fee_assumption,
            "max_extension_months": self.max_extension_months,
            "notes": list(self.notes),
            "time_zone": self.time_zone,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any] | None) -> "ExplicitAssumptions":
        if value is None:
            return cls()
        if not isinstance(value, Mapping):
            raise TypeError("ExplicitAssumptions must be a mapping")
        return cls(
            extension_months=value.get("extension_months"),
            entity_status=value.get("entity_status"),
            fee_assumption=value.get("fee_assumption"),
            time_zone=value.get("time_zone", DEFAULT_TIME_ZONE),
            apply_weekend_holiday=bool(
                value.get("apply_weekend_holiday", True)
            ),
            max_extension_months=int(
                value.get("max_extension_months", DEFAULT_MAX_EXTENSION_MONTHS)
            ),
            emit_extension_ladder=bool(
                value.get("emit_extension_ladder", False)
            ),
            notes=tuple(value.get("notes") or ()),
            extra=value.get("extra") or {},
        )


@dataclass(frozen=True, slots=True)
class HumanConfirmationRequirement:
    """One explicit human confirmation gate."""

    requirement_id: str
    description: str
    blocking: bool = True
    related_date_roles: tuple[str, ...] = ()
    related_block_reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "requirement_id",
            _identifier(self.requirement_id, "requirement_id"),
        )
        object.__setattr__(
            self,
            "description",
            _require_str(self.description, "description", max_len=1024),
        )
        if not isinstance(self.blocking, bool):
            raise TypeError("blocking must be bool")
        object.__setattr__(
            self,
            "related_date_roles",
            _tuple_of_str(
                self.related_date_roles, "related_date_roles", max_items=16
            ),
        )
        object.__setattr__(
            self,
            "related_block_reasons",
            _tuple_of_str(
                self.related_block_reasons, "related_block_reasons", max_items=16
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "blocking": self.blocking,
            "description": self.description,
            "related_block_reasons": list(self.related_block_reasons),
            "related_date_roles": list(self.related_date_roles),
            "requirement_id": self.requirement_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "HumanConfirmationRequirement":
        if not isinstance(value, Mapping):
            raise TypeError("HumanConfirmationRequirement must be a mapping")
        return cls(
            requirement_id=value.get("requirement_id", ""),
            description=value.get("description", ""),
            blocking=bool(value.get("blocking", True)),
            related_date_roles=tuple(value.get("related_date_roles") or ()),
            related_block_reasons=tuple(
                value.get("related_block_reasons") or ()
            ),
        )


@dataclass(frozen=True, slots=True)
class CalculatedDates:
    """Rule-derived dates — never conflated with source-stated surfaces."""

    base_period_end: str | None = None
    base_adjusted_end: str | None = None
    base_candidate_utc: str | None = None
    extension_period_ends: Mapping[str, str] = MappingProxyType({})
    maximum_period_end: str | None = None
    maximum_adjusted_end: str | None = None
    emergency_relief_end: str | None = None
    uncertainty_lower: str | None = None
    uncertainty_upper: str | None = None
    adjustment_reasons: tuple[str, ...] = ()
    hit_closure_kinds: tuple[str, ...] = ()
    rule_chain: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in (
            "base_period_end",
            "base_adjusted_end",
            "base_candidate_utc",
            "maximum_period_end",
            "maximum_adjusted_end",
            "emergency_relief_end",
            "uncertainty_lower",
            "uncertainty_upper",
        ):
            val = getattr(self, name)
            if val is not None and name != "base_candidate_utc":
                object.__setattr__(self, name, _iso_date(val, name))
            elif name == "base_candidate_utc" and val is not None:
                object.__setattr__(
                    self,
                    name,
                    _require_str(val, name, max_len=64),
                )
        object.__setattr__(
            self,
            "extension_period_ends",
            _frozen_str_map(
                self.extension_period_ends, "extension_period_ends", max_items=12
            ),
        )
        object.__setattr__(
            self,
            "adjustment_reasons",
            _tuple_of_str(
                self.adjustment_reasons, "adjustment_reasons", max_items=32
            ),
        )
        object.__setattr__(
            self,
            "hit_closure_kinds",
            _tuple_of_str(
                self.hit_closure_kinds, "hit_closure_kinds", max_items=16
            ),
        )
        object.__setattr__(
            self,
            "rule_chain",
            _tuple_of_str(self.rule_chain, "rule_chain", max_items=32),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "adjustment_reasons": list(self.adjustment_reasons),
            "base_adjusted_end": self.base_adjusted_end,
            "base_candidate_utc": self.base_candidate_utc,
            "base_period_end": self.base_period_end,
            "emergency_relief_end": self.emergency_relief_end,
            "extension_period_ends": dict(self.extension_period_ends),
            "hit_closure_kinds": list(self.hit_closure_kinds),
            "maximum_adjusted_end": self.maximum_adjusted_end,
            "maximum_period_end": self.maximum_period_end,
            "rule_chain": list(self.rule_chain),
            "uncertainty_lower": self.uncertainty_lower,
            "uncertainty_upper": self.uncertainty_upper,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any] | None) -> "CalculatedDates":
        if value is None:
            return cls()
        if not isinstance(value, Mapping):
            raise TypeError("CalculatedDates must be a mapping")
        return cls(
            base_period_end=value.get("base_period_end"),
            base_adjusted_end=value.get("base_adjusted_end"),
            base_candidate_utc=value.get("base_candidate_utc"),
            extension_period_ends=value.get("extension_period_ends") or {},
            maximum_period_end=value.get("maximum_period_end"),
            maximum_adjusted_end=value.get("maximum_adjusted_end"),
            emergency_relief_end=value.get("emergency_relief_end"),
            uncertainty_lower=value.get("uncertainty_lower"),
            uncertainty_upper=value.get("uncertainty_upper"),
            adjustment_reasons=tuple(value.get("adjustment_reasons") or ()),
            hit_closure_kinds=tuple(value.get("hit_closure_kinds") or ()),
            rule_chain=tuple(value.get("rule_chain") or ()),
        )


@dataclass(frozen=True, slots=True)
class AuthoritativeDeadlineRequest:
    """Input for authoritative candidate-date computation."""

    request_id: str
    trigger: DeadlineTrigger
    period_amount: int | None
    period_unit: PeriodUnit | str | None
    calendar: ClosureCalendarSnapshot | None
    assumptions: ExplicitAssumptions = field(default_factory=ExplicitAssumptions)
    source_stated_dates: tuple[SourceStatedDate, ...] = ()
    period_surface: str | None = None
    legal_citations: tuple[str, ...] = ()
    matter_id: str | None = None
    classification: DisclosureClassification | str = (
        DisclosureClassification.UNKNOWN
    )
    labels: Mapping[str, str] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "request_id", _identifier(self.request_id, "request_id")
        )
        if not isinstance(self.trigger, DeadlineTrigger):
            raise TypeError("trigger must be DeadlineTrigger")
        if self.period_amount is not None:
            object.__setattr__(
                self,
                "period_amount",
                _nonneg_int(self.period_amount, "period_amount"),
            )
        if self.period_unit is not None and not isinstance(
            self.period_unit, PeriodUnit
        ):
            object.__setattr__(
                self,
                "period_unit",
                _coerce_enum(PeriodUnit, self.period_unit, "period_unit"),
            )
        if self.calendar is not None and not isinstance(
            self.calendar, ClosureCalendarSnapshot
        ):
            raise TypeError("calendar must be ClosureCalendarSnapshot or None")
        if not isinstance(self.assumptions, ExplicitAssumptions):
            raise TypeError("assumptions must be ExplicitAssumptions")
        if not isinstance(self.source_stated_dates, tuple):
            object.__setattr__(
                self,
                "source_stated_dates",
                tuple(self.source_stated_dates or ()),
            )
        object.__setattr__(
            self,
            "period_surface",
            _optional_str(self.period_surface, "period_surface", max_len=128),
        )
        object.__setattr__(
            self,
            "legal_citations",
            _tuple_of_str(self.legal_citations, "legal_citations", max_items=32),
        )
        object.__setattr__(
            self, "matter_id", _optional_identifier(self.matter_id, "matter_id")
        )
        object.__setattr__(
            self, "classification", _coerce_classification(self.classification)
        )
        object.__setattr__(
            self, "labels", _frozen_str_map(self.labels, "labels", max_items=32)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "assumptions": self.assumptions.to_dict(),
            "calendar_snapshot_id": (
                self.calendar.snapshot_id if self.calendar else None
            ),
            "classification": self.classification.value
            if isinstance(self.classification, DisclosureClassification)
            else str(self.classification),
            "labels": dict(self.labels),
            "legal_citations": list(self.legal_citations),
            "matter_id": self.matter_id,
            "period_amount": self.period_amount,
            "period_surface": self.period_surface,
            "period_unit": (
                self.period_unit.value
                if isinstance(self.period_unit, PeriodUnit)
                else self.period_unit
            ),
            "request_id": self.request_id,
            "source_stated_dates": [s.to_dict() for s in self.source_stated_dates],
            "trigger": self.trigger.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class AuthoritativeDeadlineResult:
    """Separated calculated / source-stated / assumptions / confirmation output.

    ``is_definitive`` is True only when trigger and calendar provenance are
    present, period is known, no unresolved conflict exists, and human
    confirmation is still required before docket export (review-only).
    """

    schema_version: str
    result_id: str
    request_id: str
    status: DeadlineComputationStatus
    is_review_only: bool
    is_definitive: bool
    is_final_deadline_assertion: bool
    is_docket_entry: bool
    output_kind: str
    disclaimer: str
    calculated_dates: CalculatedDates
    source_stated_dates: tuple[SourceStatedDate, ...]
    assumptions: ExplicitAssumptions
    human_confirmation_requirements: tuple[HumanConfirmationRequirement, ...]
    definitive_blocked_reasons: tuple[str, ...]
    calendar_snapshot_id: str | None
    calendar_content_digest: str | None
    has_calendar_provenance: bool
    trigger: DeadlineTrigger
    period_amount: int | None
    period_unit: str | None
    period_surface: str | None
    reason_codes: tuple[str, ...]
    uncertainty_summary: str
    review_state: ReviewState
    classification: DisclosureClassification
    authority_citations: tuple[str, ...]
    as_of: str | None
    time_zone: str
    service_channel: str
    matter_id: str | None
    candidate_deadline: Mapping[str, Any] | None = None
    labels: Mapping[str, str] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _require_str(self.schema_version, "schema_version", max_len=64),
        )
        if self.schema_version != CALENDAR_SCHEMA_VERSION:
            raise ValueError(
                f"schema_version must be {CALENDAR_SCHEMA_VERSION}"
            )
        object.__setattr__(
            self, "result_id", _identifier(self.result_id, "result_id")
        )
        object.__setattr__(
            self, "request_id", _identifier(self.request_id, "request_id")
        )
        if not isinstance(self.status, DeadlineComputationStatus):
            object.__setattr__(
                self,
                "status",
                _coerce_enum(DeadlineComputationStatus, self.status, "status"),
            )
        if not isinstance(self.is_review_only, bool) or not self.is_review_only:
            raise ValueError("is_review_only must be True")
        if not isinstance(self.is_definitive, bool):
            raise TypeError("is_definitive must be bool")
        if not isinstance(self.is_final_deadline_assertion, bool):
            raise TypeError("is_final_deadline_assertion must be bool")
        if self.is_final_deadline_assertion:
            raise ValueError(
                "is_final_deadline_assertion must be False — never assert final"
            )
        if not isinstance(self.is_docket_entry, bool) or self.is_docket_entry:
            raise ValueError("is_docket_entry must be False")
        object.__setattr__(
            self,
            "output_kind",
            _require_str(self.output_kind, "output_kind", max_len=128),
        )
        object.__setattr__(
            self,
            "disclaimer",
            _require_str(self.disclaimer, "disclaimer", max_len=2048),
        )
        if not isinstance(self.calculated_dates, CalculatedDates):
            raise TypeError("calculated_dates must be CalculatedDates")
        if not isinstance(self.source_stated_dates, tuple):
            object.__setattr__(
                self,
                "source_stated_dates",
                tuple(self.source_stated_dates or ()),
            )
        if not isinstance(self.assumptions, ExplicitAssumptions):
            raise TypeError("assumptions must be ExplicitAssumptions")
        if not isinstance(self.human_confirmation_requirements, tuple):
            object.__setattr__(
                self,
                "human_confirmation_requirements",
                tuple(self.human_confirmation_requirements or ()),
            )
        object.__setattr__(
            self,
            "definitive_blocked_reasons",
            _tuple_of_str(
                self.definitive_blocked_reasons,
                "definitive_blocked_reasons",
                max_items=32,
            ),
        )
        # Fail-closed: computational blockers clear definitiveness.
        # HUMAN_CONFIRMATION_REQUIRED is always listed for export gating and
        # does not alone clear is_definitive (grounded computation still
        # requires named human confirmation before docket export).
        _computational_blocks = frozenset(
            {
                DefinitiveBlockReason.MISSING_TRIGGER.value,
                DefinitiveBlockReason.MISSING_CALENDAR_PROVENANCE.value,
                DefinitiveBlockReason.MISSING_PERIOD.value,
                DefinitiveBlockReason.MISSING_AS_OF.value,
                DefinitiveBlockReason.CONFLICTING_DATES.value,
                DefinitiveBlockReason.EMERGENCY_RELIEF_UNCERTAIN.value,
                DefinitiveBlockReason.STALE_CALENDAR.value,
                DefinitiveBlockReason.UNKNOWN.value,
            }
        )
        if self.is_definitive and any(
            r in _computational_blocks for r in self.definitive_blocked_reasons
        ):
            object.__setattr__(self, "is_definitive", False)
        object.__setattr__(
            self,
            "calendar_snapshot_id",
            _optional_identifier(
                self.calendar_snapshot_id, "calendar_snapshot_id"
            ),
        )
        object.__setattr__(
            self,
            "calendar_content_digest",
            _digest_or_none(
                self.calendar_content_digest, "calendar_content_digest"
            ),
        )
        if not isinstance(self.has_calendar_provenance, bool):
            raise TypeError("has_calendar_provenance must be bool")
        if not isinstance(self.trigger, DeadlineTrigger):
            raise TypeError("trigger must be DeadlineTrigger")
        if self.period_amount is not None:
            object.__setattr__(
                self,
                "period_amount",
                _nonneg_int(self.period_amount, "period_amount"),
            )
        object.__setattr__(
            self,
            "period_unit",
            _optional_str(self.period_unit, "period_unit", max_len=32),
        )
        object.__setattr__(
            self,
            "period_surface",
            _optional_str(self.period_surface, "period_surface", max_len=128),
        )
        object.__setattr__(
            self,
            "reason_codes",
            _tuple_of_str(self.reason_codes, "reason_codes", max_items=64),
        )
        object.__setattr__(
            self,
            "uncertainty_summary",
            _require_str(
                self.uncertainty_summary, "uncertainty_summary", max_len=1024
            ),
        )
        if not isinstance(self.review_state, ReviewState):
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
            "authority_citations",
            _tuple_of_str(
                self.authority_citations, "authority_citations", max_items=32
            ),
        )
        object.__setattr__(self, "as_of", _iso_date(self.as_of, "as_of"))
        object.__setattr__(
            self,
            "time_zone",
            _require_str(self.time_zone, "time_zone", max_len=64),
        )
        object.__setattr__(
            self,
            "service_channel",
            _require_str(self.service_channel, "service_channel", max_len=64),
        )
        object.__setattr__(
            self, "matter_id", _optional_identifier(self.matter_id, "matter_id")
        )
        if self.candidate_deadline is not None and not isinstance(
            self.candidate_deadline, Mapping
        ):
            raise TypeError("candidate_deadline must be mapping or None")
        object.__setattr__(
            self, "labels", _frozen_str_map(self.labels, "labels", max_items=32)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "as_of": self.as_of,
            "assumptions": self.assumptions.to_dict(),
            "authority_citations": list(self.authority_citations),
            "calculated_dates": self.calculated_dates.to_dict(),
            "calendar_content_digest": self.calendar_content_digest,
            "calendar_snapshot_id": self.calendar_snapshot_id,
            "candidate_deadline": (
                dict(self.candidate_deadline) if self.candidate_deadline else None
            ),
            "classification": self.classification.value,
            "definitive_blocked_reasons": list(self.definitive_blocked_reasons),
            "disclaimer": self.disclaimer,
            "has_calendar_provenance": self.has_calendar_provenance,
            "human_confirmation_requirements": [
                h.to_dict() for h in self.human_confirmation_requirements
            ],
            "is_definitive": self.is_definitive,
            "is_docket_entry": self.is_docket_entry,
            "is_final_deadline_assertion": self.is_final_deadline_assertion,
            "is_review_only": self.is_review_only,
            "labels": dict(self.labels),
            "matter_id": self.matter_id,
            "output_kind": self.output_kind,
            "period_amount": self.period_amount,
            "period_surface": self.period_surface,
            "period_unit": self.period_unit,
            "reason_codes": list(self.reason_codes),
            "request_id": self.request_id,
            "result_id": self.result_id,
            "review_state": self.review_state.value,
            "schema_version": self.schema_version,
            "service_channel": self.service_channel,
            "source_stated_dates": [
                s.to_dict() for s in self.source_stated_dates
            ],
            "status": self.status.value,
            "time_zone": self.time_zone,
            "trigger": self.trigger.to_dict(),
            "uncertainty_summary": self.uncertainty_summary,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "AuthoritativeDeadlineResult":
        if not isinstance(value, Mapping):
            raise TypeError("AuthoritativeDeadlineResult must be a mapping")
        return cls(
            schema_version=value.get(
                "schema_version", CALENDAR_SCHEMA_VERSION
            ),
            result_id=value.get("result_id", ""),
            request_id=value.get("request_id", ""),
            status=value.get("status", DeadlineComputationStatus.UNKNOWN.value),
            is_review_only=bool(value.get("is_review_only", True)),
            is_definitive=bool(value.get("is_definitive", False)),
            is_final_deadline_assertion=bool(
                value.get("is_final_deadline_assertion", False)
            ),
            is_docket_entry=bool(value.get("is_docket_entry", False)),
            output_kind=value.get(
                "output_kind", OUTPUT_KIND_AUTHORITATIVE_DEADLINE_SNAPSHOT
            ),
            disclaimer=value.get("disclaimer", REVIEW_ONLY_CALENDAR_DISCLAIMER),
            calculated_dates=CalculatedDates.from_dict(
                value.get("calculated_dates")
            ),
            source_stated_dates=tuple(
                SourceStatedDate.from_dict(s)
                for s in (value.get("source_stated_dates") or ())
            ),
            assumptions=ExplicitAssumptions.from_dict(value.get("assumptions")),
            human_confirmation_requirements=tuple(
                HumanConfirmationRequirement.from_dict(h)
                for h in (value.get("human_confirmation_requirements") or ())
            ),
            definitive_blocked_reasons=tuple(
                value.get("definitive_blocked_reasons") or ()
            ),
            calendar_snapshot_id=value.get("calendar_snapshot_id"),
            calendar_content_digest=value.get("calendar_content_digest"),
            has_calendar_provenance=bool(
                value.get("has_calendar_provenance", False)
            ),
            trigger=DeadlineTrigger.from_dict(value.get("trigger")),
            period_amount=value.get("period_amount"),
            period_unit=value.get("period_unit"),
            period_surface=value.get("period_surface"),
            reason_codes=tuple(value.get("reason_codes") or ()),
            uncertainty_summary=value.get(
                "uncertainty_summary", "unknown"
            ),
            review_state=value.get("review_state", ReviewState.REQUIRED.value),
            classification=value.get(
                "classification", DisclosureClassification.UNKNOWN.value
            ),
            authority_citations=tuple(value.get("authority_citations") or ()),
            as_of=value.get("as_of"),
            time_zone=value.get("time_zone", DEFAULT_TIME_ZONE),
            service_channel=value.get(
                "service_channel", ServiceChannel.UNSPECIFIED.value
            ),
            matter_id=value.get("matter_id"),
            candidate_deadline=value.get("candidate_deadline"),
            labels=value.get("labels") or {},
        )

    def public_projection(self) -> dict[str, Any]:
        """Privacy-safe projection without per-date candidate detail."""
        return {
            "as_of": self.as_of,
            "definitive_blocked_reasons": list(self.definitive_blocked_reasons),
            "has_calendar_provenance": self.has_calendar_provenance,
            "human_confirmation_count": len(
                self.human_confirmation_requirements
            ),
            "is_definitive": self.is_definitive,
            "is_docket_entry": False,
            "is_final_deadline_assertion": False,
            "is_review_only": True,
            "output_kind": self.output_kind,
            "reason_codes": list(self.reason_codes),
            "request_id": self.request_id,
            "requires_named_confirmation": True,
            "result_id": self.result_id,
            "schema_version": self.schema_version,
            "status": self.status.value,
            "uncertainty_summary": self.uncertainty_summary,
        }


# ---------------------------------------------------------------------------
# Processor
# ---------------------------------------------------------------------------


def _default_id_factory() -> str:
    return f"adc:{sha256_hex(datetime.now(timezone.utc).isoformat())[:16]}"


class AuthoritativeDeadlineCalendar:
    """Materialize closure calendars and compute review-only candidate dates."""

    def __init__(
        self,
        *,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        self._id_factory = id_factory or _default_id_factory

    def materialize_calendar(self, **kwargs: Any) -> ClosureCalendarSnapshot:
        """Delegate to :func:`materialize_closure_calendar`."""
        if "snapshot_id" not in kwargs:
            kwargs["snapshot_id"] = self._id_factory()
        return materialize_closure_calendar(**kwargs)

    def compute(
        self, request: AuthoritativeDeadlineRequest
    ) -> AuthoritativeDeadlineResult:
        """Compute separated candidate dates with fail-closed definitiveness."""
        if not isinstance(request, AuthoritativeDeadlineRequest):
            raise TypeError("request must be AuthoritativeDeadlineRequest")

        result_id = self._id_factory()
        reasons: list[str] = [
            CalendarReasonCode.REVIEW_ONLY.value,
            CalendarReasonCode.NOT_DOCKET_ENTRY.value,
            CalendarReasonCode.NOT_FINAL_DEADLINE_ASSERTION.value,
            CalendarReasonCode.NAMED_CONFIRMATION_REQUIRED.value,
            CalendarReasonCode.ASSUMPTIONS_SEPARATED.value,
            CalendarReasonCode.CALCULATED_DATES_SEPARATED.value,
            CalendarReasonCode.SOURCE_STATED_DATES_SEPARATED.value,
            CalendarReasonCode.HUMAN_CONFIRMATION_LISTED.value,
        ]
        block: list[str] = []
        confirmations: list[HumanConfirmationRequirement] = []
        calc = CalculatedDates()
        status = DeadlineComputationStatus.UNKNOWN

        cal = request.calendar
        has_prov = bool(cal and cal.has_calendar_provenance)
        cal_id = cal.snapshot_id if cal else None
        cal_digest = cal.content_digest() if cal else None
        as_of = cal.as_of if cal else None
        time_zone = (
            request.assumptions.time_zone
            or (cal.time_zone if cal else DEFAULT_TIME_ZONE)
        )
        authority = list(request.legal_citations)
        if cal:
            for c in cal.authority_citations:
                if c not in authority:
                    authority.append(c)
            reasons.append(CalendarReasonCode.SNAPSHOT_MATERIALIZED.value)
            if has_prov:
                reasons.append(CalendarReasonCode.PROVENANCE_RECORDED.value)

        # --- Definitiveness gates (fail-closed) ---
        if not request.trigger.is_present:
            block.append(DefinitiveBlockReason.MISSING_TRIGGER.value)
            reasons.append(CalendarReasonCode.MISSING_TRIGGER.value)
        if cal is None or not has_prov:
            block.append(DefinitiveBlockReason.MISSING_CALENDAR_PROVENANCE.value)
            reasons.append(CalendarReasonCode.MISSING_CALENDAR_PROVENANCE.value)
        if cal is None or not cal.as_of:
            block.append(DefinitiveBlockReason.MISSING_AS_OF.value)

        period_amount = request.period_amount
        period_unit = request.period_unit
        if isinstance(period_unit, str):
            period_unit = _coerce_enum(PeriodUnit, period_unit, "period_unit")
        if period_amount is None or period_unit in (None, PeriodUnit.UNKNOWN):
            block.append(DefinitiveBlockReason.MISSING_PERIOD.value)
            reasons.append(CalendarReasonCode.MISSING_PERIOD.value)

        # Extension policy: never assume; record explicit policy.
        if request.assumptions.extension_months is None:
            reasons.append(CalendarReasonCode.EXTENSION_NOT_ASSUMED.value)
        else:
            reasons.append(CalendarReasonCode.EXTENSION_EXPLICIT.value)

        # Human confirmation always required for export.
        confirmations.append(
            HumanConfirmationRequirement(
                requirement_id="confirm:named-human-before-docket-export",
                description=(
                    "Named human confirmation is required before any candidate "
                    "date may be exported to a docket. This snapshot is "
                    "review-only and is not a final deadline assertion."
                ),
                blocking=True,
                related_block_reasons=(
                    DefinitiveBlockReason.HUMAN_CONFIRMATION_REQUIRED.value,
                ),
            )
        )
        block.append(DefinitiveBlockReason.HUMAN_CONFIRMATION_REQUIRED.value)

        if not request.trigger.is_present:
            confirmations.append(
                HumanConfirmationRequirement(
                    requirement_id="confirm:supply-trigger",
                    description=(
                        "Trigger (mailing/notification) date is missing. Supply "
                        "a sourced trigger; do not infer service dates."
                    ),
                    blocking=True,
                    related_date_roles=(DateRole.TRIGGER.value,),
                    related_block_reasons=(
                        DefinitiveBlockReason.MISSING_TRIGGER.value,
                    ),
                )
            )

        if cal is None or not has_prov:
            confirmations.append(
                HumanConfirmationRequirement(
                    requirement_id="confirm:calendar-provenance",
                    description=(
                        "Closure calendar lacks source digests / authority "
                        "provenance. Materialize a sourced federal/USPTO "
                        "closure snapshot before treating any date as definitive."
                    ),
                    blocking=True,
                    related_block_reasons=(
                        DefinitiveBlockReason.MISSING_CALENDAR_PROVENANCE.value,
                    ),
                )
            )

        # --- Calculate when facts permit ---
        holidays: frozenset[date] = frozenset()
        closures: frozenset[date] = frozenset()
        emergency: tuple[ClosureCalendarEntry, ...] = ()
        if cal is not None:
            holidays = cal.holiday_dates()
            closures = cal.uspto_closure_dates()
            emergency = cal.emergency_entries()
            if any(e.kind is ClosureKind.FEDERAL_HOLIDAY for e in cal.entries):
                reasons.append(CalendarReasonCode.FEDERAL_HOLIDAYS_SEEDED.value)

        rule_chain: list[str] = list(request.legal_citations)
        if RULE_37_CFR_1_7 not in rule_chain:
            rule_chain.append(RULE_37_CFR_1_7)

        base_end: date | None = None
        adj_end: date | None = None
        adj_reasons: tuple[str, ...] = ()
        hit_kinds: tuple[ClosureKind, ...] = ()
        ext_map: dict[str, str] = {}
        max_end: date | None = None
        max_adj: date | None = None
        emerg_end: date | None = None
        candidate_utc: str | None = None

        can_compute = (
            request.trigger.is_present
            and period_amount is not None
            and period_unit not in (None, PeriodUnit.UNKNOWN)
        )

        if can_compute:
            assert period_amount is not None
            assert isinstance(period_unit, PeriodUnit)
            trigger_d = parse_date_surface(request.trigger.trigger_date)
            if trigger_d is None:
                block.append(DefinitiveBlockReason.MISSING_TRIGGER.value)
                can_compute = False
            else:
                # Base period (no extension unless explicit).
                base_amount = period_amount
                if (
                    request.assumptions.extension_months is not None
                    and request.assumptions.extension_months > 0
                    and period_unit is PeriodUnit.MONTHS
                ):
                    base_amount = (
                        period_amount + request.assumptions.extension_months
                    )
                    if RULE_37_CFR_1_136A not in rule_chain:
                        rule_chain.append(RULE_37_CFR_1_136A)

                raw = compute_raw_period_end(
                    trigger_d, base_amount, period_unit
                )
                if raw is None:
                    status = DeadlineComputationStatus.UNKNOWN
                else:
                    base_end = raw
                    # For explicit extension, also record pure base without ext.
                    pure_base = compute_raw_period_end(
                        trigger_d, period_amount, period_unit
                    )
                    if (
                        request.assumptions.extension_months
                        and pure_base is not None
                        and pure_base != raw
                    ):
                        # Keep pure base as base_period_end; adjusted uses total.
                        pure_adj, pure_rs, pure_hits = adjust_for_closure_calendar(
                            pure_base,
                            holidays=holidays,
                            closures=closures,
                            apply_weekend_holiday=(
                                request.assumptions.apply_weekend_holiday
                            ),
                        )
                        # Store pure base; extension total computed below.
                        base_end = pure_base
                        adj_end = pure_adj
                        adj_reasons = pure_rs
                        hit_kinds = pure_hits
                        ext_raw = raw
                        ext_adj, ext_rs, ext_hits = adjust_for_closure_calendar(
                            ext_raw,
                            holidays=holidays,
                            closures=closures,
                            apply_weekend_holiday=(
                                request.assumptions.apply_weekend_holiday
                            ),
                        )
                        key = f"extension_{request.assumptions.extension_months}_month"
                        ext_map[key] = ext_adj.isoformat()
                        adj_reasons = tuple(
                            dict.fromkeys(list(adj_reasons) + list(ext_rs))
                        )
                        hit_kinds = tuple(
                            dict.fromkeys(list(hit_kinds) + list(ext_hits))
                        )
                    else:
                        adj_end, adj_reasons, hit_kinds = adjust_for_closure_calendar(
                            raw,
                            holidays=holidays,
                            closures=closures,
                            apply_weekend_holiday=(
                                request.assumptions.apply_weekend_holiday
                            ),
                        )

                    reasons.extend(adj_reasons)

                    # Extension ladder (explicit opt-in only).
                    if (
                        request.assumptions.emit_extension_ladder
                        and period_unit is PeriodUnit.MONTHS
                    ):
                        if RULE_37_CFR_1_136A not in rule_chain:
                            rule_chain.append(RULE_37_CFR_1_136A)
                        for m in range(
                            1, request.assumptions.max_extension_months + 1
                        ):
                            ladder_raw = compute_raw_period_end(
                                trigger_d, period_amount + m, period_unit
                            )
                            if ladder_raw is None:
                                continue
                            ladder_adj, _, _ = adjust_for_closure_calendar(
                                ladder_raw,
                                holidays=holidays,
                                closures=closures,
                                apply_weekend_holiday=(
                                    request.assumptions.apply_weekend_holiday
                                ),
                            )
                            ext_map[f"extension_{m}_month"] = (
                                ladder_adj.isoformat()
                            )
                        max_months = (
                            period_amount
                            + request.assumptions.max_extension_months
                        )
                        max_end = compute_raw_period_end(
                            trigger_d, max_months, period_unit
                        )
                        if max_end is not None:
                            max_adj, _, _ = adjust_for_closure_calendar(
                                max_end,
                                holidays=holidays,
                                closures=closures,
                                apply_weekend_holiday=(
                                    request.assumptions.apply_weekend_holiday
                                ),
                            )

                    # Emergency relief overlay.
                    focus = adj_end or base_end
                    if focus is not None and emergency:
                        emerg, emerg_rs = emergency_relief_extends_to(
                            focus, emergency
                        )
                        if emerg is not None:
                            # Advance past weekend/holiday after relief end.
                            emerg_adj, _, _ = adjust_for_closure_calendar(
                                emerg + timedelta(days=1),
                                holidays=holidays,
                                closures=closures,
                                apply_weekend_holiday=True,
                            )
                            # Common practice: relief period end itself if open,
                            # else next open day.
                            if is_closed_day(
                                emerg, holidays=holidays, closures=closures
                            ):
                                emerg_end = emerg_adj
                            else:
                                emerg_end = emerg
                            reasons.extend(emerg_rs)
                            if not any(
                                e.source_digest for e in emergency
                            ) and not has_prov:
                                block.append(
                                    DefinitiveBlockReason.EMERGENCY_RELIEF_UNCERTAIN.value
                                )
                                confirmations.append(
                                    HumanConfirmationRequirement(
                                        requirement_id="confirm:emergency-relief",
                                        description=(
                                            "Emergency relief window applied; "
                                            "confirm official notice coverage "
                                            "and relief end date with counsel."
                                        ),
                                        blocking=True,
                                        related_date_roles=(
                                            DateRole.CALCULATED_EMERGENCY.value,
                                        ),
                                        related_block_reasons=(
                                            DefinitiveBlockReason.EMERGENCY_RELIEF_UNCERTAIN.value,
                                        ),
                                    )
                                )

                    # Uncertainty bounds: base adjusted vs max adjusted / emergency.
                    lower = adj_end
                    upper_candidates = [
                        d
                        for d in (adj_end, max_adj, emerg_end)
                        if d is not None
                    ]
                    for v in ext_map.values():
                        pd = parse_date_surface(v)
                        if pd is not None:
                            upper_candidates.append(pd)
                    upper = max(upper_candidates) if upper_candidates else lower

                    candidate_utc = (
                        candidate_local_end_to_utc_iso(
                            adj_end, time_zone=time_zone
                        )
                        if adj_end is not None
                        else None
                    )

                    calc = CalculatedDates(
                        base_period_end=(
                            base_end.isoformat() if base_end else None
                        ),
                        base_adjusted_end=(
                            adj_end.isoformat() if adj_end else None
                        ),
                        base_candidate_utc=candidate_utc,
                        extension_period_ends=ext_map,
                        maximum_period_end=(
                            max_end.isoformat() if max_end else None
                        ),
                        maximum_adjusted_end=(
                            max_adj.isoformat() if max_adj else None
                        ),
                        emergency_relief_end=(
                            emerg_end.isoformat() if emerg_end else None
                        ),
                        uncertainty_lower=(
                            lower.isoformat() if lower else None
                        ),
                        uncertainty_upper=(
                            upper.isoformat() if upper else None
                        ),
                        adjustment_reasons=adj_reasons,
                        hit_closure_kinds=tuple(k.value for k in hit_kinds),
                        rule_chain=tuple(dict.fromkeys(rule_chain)),
                    )
                    status = DeadlineComputationStatus.COMPUTED

        # --- Source-stated conflicts ---
        source_stated = tuple(request.source_stated_dates)
        if source_stated and calc.base_adjusted_end:
            for s in source_stated:
                if s.stated_date != calc.base_adjusted_end:
                    # Only flag conflicts when role suggests a due date.
                    role_l = s.role.lower()
                    if any(
                        tok in role_l
                        for tok in (
                            "due",
                            "deadline",
                            "response",
                            "expire",
                            "period_end",
                        )
                    ):
                        block.append(
                            DefinitiveBlockReason.CONFLICTING_DATES.value
                        )
                        reasons.append(
                            CalendarReasonCode.CONFLICTING_SOURCE_STATED.value
                        )
                        status = DeadlineComputationStatus.CONFLICT
                        confirmations.append(
                            HumanConfirmationRequirement(
                                requirement_id=(
                                    f"confirm:conflict:{s.role}:{s.stated_date}"
                                ),
                                description=(
                                    f"Source-stated date {s.stated_date} "
                                    f"(role={s.role}) conflicts with calculated "
                                    f"adjusted end {calc.base_adjusted_end}. "
                                    "Retain both; do not silently pick one."
                                ),
                                blocking=True,
                                related_date_roles=(
                                    DateRole.SOURCE_STATED.value,
                                    DateRole.CALCULATED_BASE_ADJUSTED.value,
                                ),
                                related_block_reasons=(
                                    DefinitiveBlockReason.CONFLICTING_DATES.value,
                                ),
                            )
                        )
                        break

        if not can_compute:
            if DefinitiveBlockReason.MISSING_TRIGGER.value in block or (
                DefinitiveBlockReason.MISSING_PERIOD.value in block
            ):
                status = DeadlineComputationStatus.BLOCKED
            else:
                status = DeadlineComputationStatus.PARTIAL
        elif status is not DeadlineComputationStatus.CONFLICT:
            if block and any(
                b != DefinitiveBlockReason.HUMAN_CONFIRMATION_REQUIRED.value
                for b in block
            ):
                status = DeadlineComputationStatus.PARTIAL
            else:
                status = DeadlineComputationStatus.COMPUTED

        # is_definitive: all gates clear except human confirmation still listed
        # as required for export — "definitive" here means computation is
        # fully grounded, not that docket export is allowed without human.
        computational_blocks = [
            b
            for b in dict.fromkeys(block)
            if b != DefinitiveBlockReason.HUMAN_CONFIRMATION_REQUIRED.value
        ]
        is_definitive = (
            not computational_blocks
            and status is DeadlineComputationStatus.COMPUTED
            and calc.base_adjusted_end is not None
        )
        if not is_definitive:
            reasons.append(CalendarReasonCode.DEFINITIVE_BLOCKED.value)
        else:
            reasons.append(
                CalendarReasonCode.DEFINITIVE_ALLOWED_AFTER_CONFIRMATION.value
            )

        # Deduplicate confirmations by id (stable order).
        seen_c: set[str] = set()
        uniq_conf: list[HumanConfirmationRequirement] = []
        for c in confirmations:
            if c.requirement_id in seen_c:
                continue
            seen_c.add(c.requirement_id)
            uniq_conf.append(c)

        uncertainty_parts: list[str] = []
        if computational_blocks:
            uncertainty_parts.append(
                "blocked: " + ", ".join(computational_blocks)
            )
        if calc.base_adjusted_end:
            uncertainty_parts.append(
                f"candidate_adjusted={calc.base_adjusted_end}"
            )
        if calc.uncertainty_lower and calc.uncertainty_upper:
            uncertainty_parts.append(
                f"bounds=[{calc.uncertainty_lower},{calc.uncertainty_upper}]"
            )
        uncertainty_parts.append("review-only; named confirmation required")
        uncertainty_summary = "; ".join(uncertainty_parts)

        # Project optional CandidateDeadline when fully computed.
        candidate_deadline: dict[str, Any] | None = None
        if calc.base_candidate_utc and request.trigger.trigger_date:
            try:
                cd = CandidateDeadline(
                    schema_version=CONTRACTS_SCHEMA_VERSION,
                    deadline_id=result_id,
                    event_basis=request.trigger.trigger_date,
                    rule_chain=tuple(calc.rule_chain)
                    or (RULE_37_CFR_1_7,),
                    calendar=cal.calendar_id if cal else DEFAULT_CALENDAR_ID,
                    time_zone=time_zone,
                    entity_status_assumption=request.assumptions.entity_status,
                    extension_assumption=(
                        f"extension_{request.assumptions.extension_months}_month"
                        if request.assumptions.extension_months is not None
                        else "not_assumed"
                    ),
                    candidate_utc=calc.base_candidate_utc,
                    uncertainty=uncertainty_summary[:256],
                    reviewer_confirmation=ReviewState.REQUIRED,
                    classification=request.classification
                    if isinstance(
                        request.classification, DisclosureClassification
                    )
                    else _coerce_classification(request.classification),
                )
                candidate_deadline = cd.to_dict()
                reasons.append(
                    CalendarReasonCode.CONTRACT_CANDIDATE_PROJECTED.value
                )
            except (TypeError, ValueError):
                candidate_deadline = None

        channel = request.trigger.service_channel
        if isinstance(channel, ServiceChannel):
            channel_s = channel.value
        else:
            channel_s = str(channel)

        return AuthoritativeDeadlineResult(
            schema_version=CALENDAR_SCHEMA_VERSION,
            result_id=result_id,
            request_id=request.request_id,
            status=status,
            is_review_only=True,
            is_definitive=is_definitive,
            is_final_deadline_assertion=False,
            is_docket_entry=False,
            output_kind=OUTPUT_KIND_AUTHORITATIVE_DEADLINE_SNAPSHOT,
            disclaimer=REVIEW_ONLY_CALENDAR_DISCLAIMER,
            calculated_dates=calc,
            source_stated_dates=source_stated,
            assumptions=request.assumptions,
            human_confirmation_requirements=tuple(uniq_conf),
            definitive_blocked_reasons=tuple(dict.fromkeys(block)),
            calendar_snapshot_id=cal_id,
            calendar_content_digest=cal_digest,
            has_calendar_provenance=has_prov,
            trigger=request.trigger,
            period_amount=request.period_amount,
            period_unit=(
                period_unit.value
                if isinstance(period_unit, PeriodUnit)
                else (str(period_unit) if period_unit else None)
            ),
            period_surface=request.period_surface
            or (
                f"{request.period_amount} {period_unit.value}"
                if request.period_amount is not None
                and isinstance(period_unit, PeriodUnit)
                else None
            ),
            reason_codes=tuple(dict.fromkeys(reasons)),
            uncertainty_summary=uncertainty_summary,
            review_state=ReviewState.REQUIRED,
            classification=request.classification
            if isinstance(request.classification, DisclosureClassification)
            else _coerce_classification(request.classification),
            authority_citations=tuple(dict.fromkeys(authority)),
            as_of=as_of,
            time_zone=time_zone,
            service_channel=channel_s,
            matter_id=request.matter_id,
            candidate_deadline=candidate_deadline,
            labels=request.labels,
        )


def compute_authoritative_deadline(
    request: AuthoritativeDeadlineRequest,
    *,
    id_factory: Callable[[], str] | None = None,
) -> AuthoritativeDeadlineResult:
    """Module-level wrapper around :class:`AuthoritativeDeadlineCalendar`."""
    return AuthoritativeDeadlineCalendar(id_factory=id_factory).compute(request)


# ---------------------------------------------------------------------------
# Recipe loader (compact fixtures)
# ---------------------------------------------------------------------------


def load_closure_calendar_recipe(
    path: str | Path | None = None,
) -> dict[str, Any]:
    """Load the compact closure-calendar recipe JSON."""
    if path is None:
        # Resolve relative to this file → repo root heuristics.
        here = Path(__file__).resolve()
        candidates = [
            here.parents[5] / DEFAULT_RECIPE_RELATIVE,  # .../ipfs_datasets_py/...
            Path.cwd() / DEFAULT_RECIPE_RELATIVE,
            Path(DEFAULT_RECIPE_RELATIVE),
        ]
        # Also try walking up for tests/fixtures.
        for parent in here.parents:
            cand = parent / DEFAULT_RECIPE_RELATIVE
            if cand.is_file():
                path = cand
                break
        else:
            for cand in candidates:
                if cand.is_file():
                    path = cand
                    break
            else:
                raise FileNotFoundError(
                    f"closure calendar recipe not found; tried {candidates!r}"
                )
    p = Path(path)
    data = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise AuthoritativeDeadlineCalendarError(
            "recipe root must be an object", code="invalid_recipe"
        )
    return data


def build_calendar_from_recipe_case(
    case: Mapping[str, Any],
) -> ClosureCalendarSnapshot:
    """Build a :class:`ClosureCalendarSnapshot` from one recipe case block."""
    cal = case.get("calendar") or {}
    if not isinstance(cal, Mapping):
        raise AuthoritativeDeadlineCalendarError(
            "case.calendar must be a mapping", code="invalid_recipe_calendar"
        )
    sources = cal.get("sources") or []
    uspto = cal.get("uspto_closures") or []
    emergency = cal.get("emergency_relief") or []
    return materialize_closure_calendar(
        snapshot_id=cal.get("snapshot_id")
        or f"snap:{case.get('id', 'recipe')}",
        as_of=cal.get("as_of") or case.get("as_of") or "2026-01-01",
        year=cal.get("year"),
        uspto_closures=uspto,
        emergency_relief=emergency,
        sources=sources,
        authority_citations=tuple(cal.get("authority_citations") or ()),
        time_zone=cal.get("time_zone", DEFAULT_TIME_ZONE),
        calendar_id=cal.get("calendar_id", DEFAULT_CALENDAR_ID),
        seed_federal_holidays=bool(cal.get("seed_federal_holidays", True)),
        materialized_at=cal.get("materialized_at", "2026-01-01T00:00:00Z"),
        labels=cal.get("labels") or {},
        notes=tuple(cal.get("notes") or ()),
    )


def build_request_from_recipe_case(
    case: Mapping[str, Any],
    *,
    calendar: ClosureCalendarSnapshot | None = None,
) -> AuthoritativeDeadlineRequest:
    """Build an :class:`AuthoritativeDeadlineRequest` from a recipe case."""
    trig = case.get("trigger") or {}
    trigger = DeadlineTrigger(
        kind=trig.get("kind", TriggerKind.MAILING_DATE.value),
        trigger_date=trig.get("trigger_date") or trig.get("date"),
        source_id=trig.get("source_id"),
        source_span_id=trig.get("source_span_id"),
        service_channel=trig.get(
            "service_channel", ServiceChannel.ELECTRONIC.value
        ),
        labels=trig.get("labels") or {},
    )
    assumptions_raw = case.get("assumptions") or {}
    assumptions = ExplicitAssumptions.from_dict(assumptions_raw)
    stated = tuple(
        SourceStatedDate.from_dict(s)
        for s in (case.get("source_stated_dates") or ())
    )
    cal = calendar
    if cal is None and case.get("calendar") is not None:
        # Allow empty calendar block to mean "no calendar".
        if case.get("omit_calendar"):
            cal = None
        else:
            cal = build_calendar_from_recipe_case(case)
    if case.get("omit_calendar"):
        cal = None
    if case.get("calendar_without_provenance"):
        # Rebuild calendar stripping digests.
        if cal is not None:
            stripped_entries = tuple(
                ClosureCalendarEntry(
                    entry_id=e.entry_id,
                    closed_date=e.closed_date,
                    kind=e.kind,
                    label=e.label,
                    authority_citation=None,
                    source_id=None,
                    source_digest=None,
                    relief_end_date=e.relief_end_date,
                    notes=e.notes,
                )
                for e in cal.entries
            )
            cal = ClosureCalendarSnapshot(
                snapshot_id=cal.snapshot_id,
                as_of=cal.as_of,
                time_zone=cal.time_zone,
                calendar_id=cal.calendar_id,
                entries=stripped_entries,
                sources=(),
                authority_citations=(),
                materialized_at=cal.materialized_at,
                year=cal.year,
            )
    return AuthoritativeDeadlineRequest(
        request_id=case.get("request_id") or f"req:{case.get('id', 'case')}",
        trigger=trigger,
        period_amount=case.get("period_amount"),
        period_unit=case.get("period_unit"),
        calendar=cal,
        assumptions=assumptions,
        source_stated_dates=stated,
        period_surface=case.get("period_surface"),
        legal_citations=tuple(case.get("legal_citations") or ()),
        matter_id=case.get("matter_id"),
        classification=case.get(
            "classification", DisclosureClassification.PUBLIC_USER.value
        ),
        labels=case.get("labels") or {},
    )


def run_recipe_case(
    case: Mapping[str, Any],
    *,
    id_factory: Callable[[], str] | None = None,
) -> AuthoritativeDeadlineResult:
    """Execute one recipe case and return the result."""
    request = build_request_from_recipe_case(case)
    proc = AuthoritativeDeadlineCalendar(id_factory=id_factory)
    result = proc.compute(request)
    return result


__all__ = [
    "CALENDAR_INTERFACE",
    "CALENDAR_SCHEMA_VERSION",
    "DEFAULT_CALENDAR_ID",
    "DEFAULT_MAX_EXTENSION_MONTHS",
    "DEFAULT_RECIPE_RELATIVE",
    "OUTPUT_KIND_AUTHORITATIVE_DEADLINE_SNAPSHOT",
    "RECIPE_SCHEMA_VERSION",
    "REVIEW_ONLY_CALENDAR_DISCLAIMER",
    "AuthoritativeDeadlineCalendar",
    "AuthoritativeDeadlineCalendarError",
    "AuthoritativeDeadlineRequest",
    "AuthoritativeDeadlineResult",
    "CalculatedDates",
    "CalendarReasonCode",
    "CalendarSourceProvenance",
    "ClosureCalendarEntry",
    "ClosureCalendarSnapshot",
    "ClosureKind",
    "DateRole",
    "DeadlineComputationStatus",
    "DeadlineTrigger",
    "DefinitiveBlockReason",
    "ExplicitAssumptions",
    "HumanConfirmationRequirement",
    "ServiceChannel",
    "SourceStatedDate",
    "TriggerKind",
    "adjust_for_closure_calendar",
    "build_calendar_from_recipe_case",
    "build_request_from_recipe_case",
    "closed_date_set",
    "compute_authoritative_deadline",
    "emergency_relief_extends_to",
    "is_closed_day",
    "load_closure_calendar_recipe",
    "materialize_closure_calendar",
    "next_open_business_day",
    "run_recipe_case",
    "seed_federal_holiday_entries",
    "sha256_hex",
]
