"""Official and Bluebook citations for country-law corpus rows.

Bluebook T2/T10 abbreviations are used only when this table has a row.
Unknown jurisdictions get ``official_citation`` only — never a invented
Bluebook form. Query keys are normalized so ``ORS 1.010`` and
``Or. Rev. Stat. § 1.010`` can hit the same row later.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata
from typing import Any

from pathlib import Path
import json as _json

_TABLE_PATH = Path(__file__).resolve().parent / "data" / "bluebook_t2.json"


def _load_t2() -> dict[str, dict[str, Any]]:
    if not _TABLE_PATH.is_file():
        return {}
    payload = _json.loads(_TABLE_PATH.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


_BLUEBOOK_T2 = _load_t2()


@dataclass(frozen=True)
class Citation:
    official_citation: str
    bluebook_citation: str
    cite_key: str
    citation_status: str  # bluebook | official_only | unknown
    pinpoint: str


def normalize_cite_key(value: str) -> str:
    if not value:
        return ""
    text = unicodedata.normalize("NFKC", value).lower()
    text = text.replace("§", " s ")
    text = text.replace("¶", " ")
    text = re.sub(r"\bart(?:icle|\.)?\b", "art", text)
    text = re.sub(r"\bsec(?:tion|\.)?\b", "s", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _pinpoint(article_number: str, section_number: str, record_type: str) -> str:
    if record_type == "section" and section_number:
        return f"§ {section_number}"
    if article_number:
        return f"art. {article_number}"
    if section_number:
        return f"§ {section_number}"
    return ""


def _t2_row(jurisdiction: str, country: str, slug: str = "") -> dict[str, Any]:
    for key in (slug, country, jurisdiction):
        hit = _BLUEBOOK_T2.get(str(key or "").strip().lower().replace("_", " "))
        if isinstance(hit, dict):
            return hit
    return {}


def assign_citation(
    *,
    eli: str = "",
    official_identifier: str = "",
    identifier: str = "",
    instrument_title: str = "",
    article_number: str = "",
    section_number: str = "",
    record_type: str = "law",
    jurisdiction: str = "",
    country: str = "",
    slug: str = "",
    year: str = "",
) -> Citation:
    pinpoint = _pinpoint(article_number, section_number, record_type)
    official = (
        (eli or "").strip()
        or (official_identifier or "").strip()
        or (identifier or "").strip()
        or (instrument_title or "").strip()
    )
    if official and pinpoint and pinpoint.lower() not in official.lower():
        official_cite = f"{official}, {pinpoint}"
    else:
        official_cite = official

    t2 = _t2_row(jurisdiction, country, slug)
    abbrev = str(t2.get("abbrev") or "")
    emit = str(t2.get("emit") or "official_only")
    required = list(t2.get("required") or [])
    have = {
        "year": bool(year),
        "section": bool(section_number or (record_type == "section" and article_number)),
        "article": bool(article_number),
        "title": bool(instrument_title),
    }
    missing = [k for k in required if not have.get(k)]
    bluebook = ""
    if emit == "bluebook" and abbrev and not missing:
        if pinpoint:
            bluebook = f"{abbrev} {pinpoint}" + (f" ({year})" if year else "")
        elif have.get("section"):
            bluebook = f"{abbrev} § {section_number}" + (f" ({year})" if year else "")

    if bluebook:
        status = "bluebook"
    elif official_cite:
        status = "official_only"
    else:
        status = "unknown"

    key_src = bluebook or official_cite
    return Citation(
        official_citation=official_cite,
        bluebook_citation=bluebook,
        cite_key=normalize_cite_key(key_src),
        citation_status=status,
        pinpoint=pinpoint,
    )


def citation_fields(cite: Citation) -> dict[str, Any]:
    return {
        "official_citation": cite.official_citation,
        "bluebook_citation": cite.bluebook_citation,
        "cite_key": cite.cite_key,
        "citation_status": cite.citation_status,
        "pinpoint": cite.pinpoint,
    }
