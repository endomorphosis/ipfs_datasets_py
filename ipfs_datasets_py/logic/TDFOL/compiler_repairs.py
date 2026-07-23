"""Typed temporal-deadline anchor compilation for Legal IR."""

from __future__ import annotations

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


def compile_temporal_deadline(text: str, *, provenance_id: str = "") -> dict[str, Any]:
    """Compile relative and ordered deadlines with explicit typed anchors."""

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
        item["constraint_id"] = f"tdfol-deadline:{_digest({'item': item, 'provenance_ids': provenance_ids})[:24]}"
        constraints.append(item)
        occupied.append(match.span())
    for match in _ORDER_RE.finditer(str(text or "")):
        if any(start <= match.start() < end for start, end in occupied):
            continue
        raw_relation = _atom(match.group("relation"))
        relation = "before_or_at" if raw_relation in {"not_later_than", "no_later_than", "on_or_before"} else raw_relation
        item = {
            "anchor": _anchor(match.group("anchor")),
            "anchor_type": "event_or_instant",
            "inclusive": relation in {"before_or_at", "until"},
            "offset": 0,
            "relation": relation,
            "unit": "instant",
        }
        item["constraint_id"] = f"tdfol-deadline:{_digest({'item': item, 'provenance_ids': provenance_ids})[:24]}"
        constraints.append(item)
    return {
        "constraints": constraints,
        "provenance_ids": provenance_ids,
        "schema_version": TDFOL_COMPILER_REPAIR_SCHEMA_VERSION,
        "temporal_logic": "TDFOL",
    }


def _canonical_unit(value: Any) -> str:
    unit = _atom(value)
    return {"day": "days", "week": "weeks", "month": "months", "year": "years", "business_day": "business_days"}.get(unit, unit)


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
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()


__all__ = ["TDFOL_COMPILER_REPAIR_SCHEMA_VERSION", "compile_temporal_deadline"]
