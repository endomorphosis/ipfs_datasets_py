"""Typed temporal-deadline anchor compilation for Legal IR."""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields
import hashlib
import json
import re
from typing import Any


TDFOL_COMPILER_REPAIR_SCHEMA_VERSION = "legal-ir-tdfol-compiler-repair-v1"

_WITHIN_RE = re.compile(
    r"\bwithin\s+(?P<amount>\d+)\s+(?P<unit>business\s+days?|days?|weeks?|months?|years?)"
    r"(?:\s+(?P<relation>after|from|before)\s+(?P<anchor>[^,.;]+))?",
    re.IGNORECASE,
)
_ORDER_RE = re.compile(
    r"\b(?P<relation>not\s+later\s+than|no\s+later\s+than|on\s+or\s+before|before|after|until)\s+"
    r"(?P<anchor>[^,.;]+)",
    re.IGNORECASE,
)

_DEADLINE_ANCHOR = r"[A-Za-z0-9][A-Za-z0-9_]{0,127}"
_MAX_DEADLINE_OFFSET = 999_999_999
_DAY_UNITS = {"calendar_days": "calendar", "business_days": "business"}
_RELATIVE_RELATIONS = {"after", "from", "before"}
_ORDERED_RELATIONS = {"before_or_at": "on or before", "before": "before", "after": "after"}
_ANCHOR_TYPES = {"event": "event", "instant": "instant", "event_or_instant": "event or instant"}
_EXPLICIT_RELATIVE_RE = re.compile(
    r'(?P<boundary>within|less than) (?P<offset>0|[1-9][0-9]{0,8}) '
    r'(?P<unit>calendar|business) (?P<days>days?) (?P<relation>after|from|before) '
    rf'event "(?P<anchor>{_DEADLINE_ANCHOR})"'
)
_EXPLICIT_ORDER_RE = re.compile(
    r'(?P<relation>on or before|before|after) (?P<anchor_type>event or instant|event|instant) '
    rf'"(?P<anchor>{_DEADLINE_ANCHOR})"'
)


@dataclass(frozen=True, slots=True)
class TemporalDeadline:
    """The TDFOL constraint fields without source provenance or a calendar interpretation."""

    anchor: str
    anchor_type: str
    inclusive: bool
    offset: int
    relation: str
    unit: str

    def __post_init__(self):
        if (type(self.anchor) is not str or re.fullmatch(_DEADLINE_ANCHOR, self.anchor) is None
                or type(self.anchor_type) is not str or self.anchor_type not in _ANCHOR_TYPES
                or type(self.inclusive) is not bool or type(self.offset) is not int
                or not 0 <= self.offset <= _MAX_DEADLINE_OFFSET
                or type(self.relation) is not str or type(self.unit) is not str):
            raise ValueError("complete typed deadline fields required")
        if self.unit == "instant":
            if (self.offset != 0 or self.relation not in _ORDERED_RELATIONS
                    or self.inclusive != (self.relation == "before_or_at")):
                raise ValueError("ordered deadline has inconsistent offset, relation or boundary")
        elif (self.unit not in _DAY_UNITS or self.anchor_type != "event"
                or self.relation not in _RELATIVE_RELATIONS):
            raise ValueError("explicit calendar or business day deadline relative to an event required")

    def to_dict(self) -> dict[str, Any]:
        TemporalDeadline.__post_init__(self)
        return asdict(self)

    @classmethod
    def from_dict(cls, value: object) -> TemporalDeadline:
        if (type(value) is not dict or any(type(key) is not str for key in value)
                or set(value) != {item.name for item in fields(cls)}):
            raise ValueError("closed typed deadline fields required")
        return cls(**value)


def parse_temporal_deadline(text: str) -> TemporalDeadline | None:
    """Parse one complete explicit deadline clause with a named anchor."""
    if type(text) is not str:
        raise ValueError("deadline clause must be text")
    relative = _EXPLICIT_RELATIVE_RE.fullmatch(text)
    if relative is not None:
        offset = int(relative["offset"])
        if relative["days"] != ("day" if offset == 1 else "days"):
            return None
        return TemporalDeadline(relative["anchor"], "event", relative["boundary"] == "within",
                                offset, relative["relation"], relative["unit"] + "_days")
    ordered = _EXPLICIT_ORDER_RE.fullmatch(text)
    if ordered is None:
        return None
    relation = "before_or_at" if ordered["relation"] == "on or before" else ordered["relation"]
    return TemporalDeadline(ordered["anchor"], ordered["anchor_type"].replace(" ", "_"),
                            relation == "before_or_at", 0, relation, "instant")


def render_temporal_deadline(deadline: TemporalDeadline) -> str:
    """Render a typed constraint as controlled prose with an explicit unit and boundary."""
    if type(deadline) is not TemporalDeadline:
        raise ValueError("typed temporal deadline required")
    TemporalDeadline.__post_init__(deadline)
    anchor = f'{_ANCHOR_TYPES[deadline.anchor_type]} "{deadline.anchor}"'
    if deadline.unit == "instant":
        return f"{_ORDERED_RELATIONS[deadline.relation]} {anchor}"
    boundary = "within" if deadline.inclusive else "less than"
    days = "day" if deadline.offset == 1 else "days"
    return f"{boundary} {deadline.offset} {_DAY_UNITS[deadline.unit]} {days} {deadline.relation} {anchor}"


def compile_temporal_deadline(text: str, *, provenance_id: str = "") -> dict[str, Any]:
    """Generate historical heuristic candidates and their original provenance IDs."""

    provenance_ids = [str(provenance_id).strip()] if str(provenance_id).strip() else []
    constraints: list[dict[str, Any]] = []
    occupied: list[tuple[int, int]] = []
    for match in _WITHIN_RE.finditer(str(text or "")):
        relation = _atom(match.group("relation") or "from_trigger")
        anchor = _anchor(match.group("anchor") or "governing_event")
        item = {
            "anchor": anchor,
            "anchor_type": "event",
            "inclusive": True,
            "offset": int(match.group("amount")),
            "relation": relation,
            "unit": _canonical_unit(match.group("unit")),
        }
        item["constraint_id"] = (
            f"tdfol-deadline:{_digest({'item': item, 'provenance_ids': provenance_ids})[:24]}"
        )
        constraints.append(item)
        occupied.append(match.span())
    for match in _ORDER_RE.finditer(str(text or "")):
        if any(start <= match.start() < end for start, end in occupied):
            continue
        raw_relation = _atom(match.group("relation"))
        relation = (
            "before_or_at"
            if raw_relation in {"not_later_than", "no_later_than", "on_or_before"}
            else raw_relation
        )
        item = {
            "anchor": _anchor(match.group("anchor")),
            "anchor_type": "event_or_instant",
            "inclusive": relation in {"before_or_at", "until"},
            "offset": 0,
            "relation": relation,
            "unit": "instant",
        }
        item["constraint_id"] = (
            f"tdfol-deadline:{_digest({'item': item, 'provenance_ids': provenance_ids})[:24]}"
        )
        constraints.append(item)
    return {
        "constraints": constraints,
        "provenance_ids": provenance_ids,
        "schema_version": TDFOL_COMPILER_REPAIR_SCHEMA_VERSION,
        "temporal_logic": "TDFOL",
    }


def _canonical_unit(value: Any) -> str:
    unit = _atom(value)
    return {
        "day": "days",
        "week": "weeks",
        "month": "months",
        "year": "years",
        "business_day": "business_days",
    }.get(unit, unit)


def _anchor(value: Any) -> str:
    text = str(value or "").lower()
    text = re.split(
        r"\s+(?:and|or)\s+(?:(?:the|a|an)\s+)?(?:[a-z]+\s+)?"
        r"(?:shall|must|may|is\s+required\s+to)\b|"
        r"\s+within\s+\d+\b",
        text,
        maxsplit=1,
    )[0]
    tokens = re.findall(r"[a-z0-9]+", text)[:10]
    return "_".join(tokens) or "governing_event"


def _atom(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()).strip("_")


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    ).hexdigest()


__all__ = ["TDFOL_COMPILER_REPAIR_SCHEMA_VERSION", "TemporalDeadline", "compile_temporal_deadline",
           "parse_temporal_deadline", "render_temporal_deadline"]
