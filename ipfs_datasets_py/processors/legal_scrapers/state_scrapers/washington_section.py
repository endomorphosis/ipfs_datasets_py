"""Official Washington RCW section HTML parser (contentWrapper).

Adapted from Vaquill-AI/open-us-law ``scrapeWA.py`` (Apache-2.0).
Section body is ``contentWrapper`` top-level ``div[2]``; history lives in
the ``margin-top:15pt`` sibling. Notes are dropped. On the official two-version
page shape, the selected version's history remains explicit metadata.
"""

from __future__ import annotations

import hashlib
import os
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlparse

from .base_scraper import NormalizedStatute, StatuteMetadata

BASE = "https://app.leg.wa.gov/RCW"
_WS = re.compile(r"\s+")
_STANDARD_CITE_PATTERN = r"\d+[A-Za-z]?(?:\.\d+[A-Za-z]?){1,3}"
_UCC_CHAPTER_PATTERN = r"62A\.\d+[A-Za-z]?"
_UCC_SECTION_PATTERN = rf"{_UCC_CHAPTER_PATTERN}-\d+[A-Za-z]?"
_SECTION_CITE_PATTERN = rf"(?:{_STANDARD_CITE_PATTERN}|{_UCC_SECTION_PATTERN})"
_CITE_RE = re.compile(rf"\b({_SECTION_CITE_PATTERN})\b", re.IGNORECASE)
_TITLE_HREF_RE = re.compile(r"default\.aspx\?Cite=([\w]+)$", re.IGNORECASE)
_CHAPTER_HREF_RE = re.compile(
    r"(?:/rcw/)?default\.aspx\?cite=([\w]+\.[\w]+)$", re.IGNORECASE
)
_SECTION_PAGE_TITLE_RE = re.compile(
    rf"^RCW\s+(?P<cite>{_SECTION_CITE_PATTERN})\s*:\s*$",
    re.IGNORECASE,
)
_SECTION_PAGE_HEADING_RE = re.compile(
    rf"^RCW\s+(?P<cite>{_SECTION_CITE_PATTERN})\s*$",
    re.IGNORECASE,
)
_SECTION_PAGE_DUAL_TITLE_RE = re.compile(
    rf"^RCW\s+(?P<cite>{_SECTION_CITE_PATTERN})\s*:\s*(?P<caption>.+)$",
    re.IGNORECASE,
)
_EFFECTIVE_UNTIL_CAPTION_RE = re.compile(
    r"^(?P<base>.+)\s+\(Effective until "
    r"(?P<date>[A-Z][a-z]+\s+\d{1,2},\s+\d{4})\.\)$",
    re.IGNORECASE,
)
_EFFECTIVE_FROM_CAPTION_RE = re.compile(
    r"^(?P<base>.+)\s+\(Effective "
    r"(?P<date>[A-Z][a-z]+\s+\d{1,2},\s+\d{4})\.\)$",
    re.IGNORECASE,
)
_VARIANT_DATE_PATTERN = r"[A-Z][a-z]+\s+\d{1,2},\s+\d{4}"
_VARIANT_UNTIL_QUALIFIER_RE = re.compile(
    rf"^Effective until (?P<until>{_VARIANT_DATE_PATTERN})"
    r"(?:;\s*contingent (?P<contingent>expiration|effective) date)?\.$",
    re.IGNORECASE,
)
_VARIANT_FROM_QUALIFIER_RE = re.compile(
    rf"^Effective (?P<from>{_VARIANT_DATE_PATTERN})"
    rf"(?:,\s*until (?P<until>{_VARIANT_DATE_PATTERN}))?"
    r"(?:;\s*contingent (?P<contingent>expiration|effective) date)?\.$",
    re.IGNORECASE,
)
_VARIANT_CONTINGENT_QUALIFIER_RE = re.compile(
    r"^Contingent (?P<contingent>expiration|effective) date\.$",
    re.IGNORECASE,
)
_VARIANT_FINAL_PAREN_RE = re.compile(r"^(?P<base>.*)\s+\((?P<value>[^()]*)\)$")
_MULTI_VERSION_CONFLICT_MARKERS = (
    "without reference",
    "without cognizance",
    "amended twice",
    "amended three times",
    "amended more than once",
    "rcw 1.12.025",
)
_CONTINGENCY_DID_NOT_OCCUR_RE = re.compile(
    r"(?:the\s+)?contingenc(?:y|ies).{0,120}"
    r"(?:did not|has not|have not|had not)\s+occur",
    re.IGNORECASE,
)
_CONTINGENCY_OCCURRED_RE = re.compile(
    r"reviser's note:.{0,240}(?:the\s+)?contingenc(?:y|ies).{0,120}"
    r"(?<!not\s)(?:has\s+|have\s+|had\s+|appears\s+to\s+have\s+)?occurred",
    re.IGNORECASE,
)
_REVIEWED_PENDING_CONTINGENCY_SNAPSHOTS = {
    "30a.08.140": {
        "content_sha256": (
            "39adcf067e7a655dfa2a60900665988b915daa95d829bf609b796bb7bf0c73b6"
        ),
        "observed_on": date(2026, 8, 28),
    },
    "32.08.140": {
        "content_sha256": (
            "6e5f2865325535b1553cb108df75592be6a511afddf060235f743510b259dae3"
        ),
        "observed_on": date(2026, 8, 28),
    },
    "35a.21.190": {
        "content_sha256": (
            "1f0b802f555a6336b1744cbb7c4eb6940df14ef0ecd4449ffb1cd19c0e506977"
        ),
        "observed_on": date(2026, 8, 28),
    },
    "43.84.092": {
        "content_sha256": (
            "963dc7a644c4b5f97db0c63455d5cc79f7e6a2966aa7564db88f506389f39473"
        ),
        "observed_on": date(2026, 8, 28),
    },
    "70.157.020": {
        "content_sha256": (
            "40f6c19367033d6fd8886be1f0e34b389f5e3f449b6c9d2e7c9b9b75b76576cd"
        ),
        "observed_on": date(2026, 8, 28),
    },
    "71.05.020": {
        "content_sha256": (
            "5e09054e36011fb9834813870727bc9b37dd1ccf6226fdb11ba50681e5f8ce73"
        ),
        "observed_on": date(2026, 8, 28),
    },
    "71.05.212": {
        "content_sha256": (
            "e71fca258032b954dc54bc199d5da7609c06eb765faeb455b59e1ecf0945d37d"
        ),
        "observed_on": date(2026, 8, 28),
    },
    "71.34.020": {
        "content_sha256": (
            "b8cfbebdba1dd40c25c35b1176183b040d6933e599acf16578520175b545a9ca"
        ),
        "observed_on": date(2026, 8, 28),
    },
    "82.12.022": {
        "content_sha256": (
            "aebb1de26b7d9626d5ca8acce876c6825e183a9bd172b80194b96e9b6ec857a0"
        ),
        "observed_on": date(2026, 8, 28),
    },
}
_CHAPTER_CITE_PATTERN = r"\d+[A-Za-z]?\.\d+[A-Za-z]?"
_CHAPTER_PAGE_TITLE_RE = re.compile(
    rf"^Chapter\s+(?P<cite>{_CHAPTER_CITE_PATTERN})\s+RCW\s*:\s*$",
    re.IGNORECASE,
)
_CHAPTER_PAGE_HEADING_RE = re.compile(
    rf"^Chapter\s+(?P<cite>{_CHAPTER_CITE_PATTERN})\s+RCW\s*$",
    re.IGNORECASE,
)
_ARTICLE_PAGE_HEADING_RE = re.compile(
    r"^Article\s+(?P<article>\d+[A-Za-z]?)\s*$",
    re.IGNORECASE,
)
_SOURCE_BOUND_EMPTY_CHAPTER_TERMINALS = {
    "48.26": "reserved",
}
_SOURCE_BOUND_CHAPTER_MATERIALS = {
    "29a.76c": {
        "record_type": "congressional_redistricting_plan",
        "section_name": "Congressional redistricting plan",
        "required_markers": (
            "washington state redistricting commission",
            "congressional districts",
            "district 10:",
        ),
    },
    "44.07f": {
        "record_type": "legislative_redistricting_plan",
        "section_name": "Legislative redistricting plan",
        "required_markers": (
            "washington state redistricting commission",
            "legislative districts",
            "district 49:",
        ),
    },
}
_SOURCE_BOUND_SHORT_OPERATIVE_SECTIONS = {
    "1.70.903": {
        "caption": "Effective date — 2017 c 106.",
        "body_parts": ("This act takes effect January 1, 2018.",),
        "history_parts": ("[ 2017 c 106 s 13 .]",),
    },
    "2.06.045": {
        "caption": "When open for transaction of business.",
        "body_parts": ("See RCW 2.04.030 .",),
        "history_parts": (),
    },
    "2.76.900": {
        "caption": "Expiration date.",
        "body_parts": ("This chapter expires January 1, 2031.",),
        "history_parts": ("[ 2025 c 398 s 4 ; 2022 c 284 s 5 .]",),
    },
    "2.78.900": {
        "caption": "Expiration date.",
        "body_parts": ("This chapter expires December 31, 2029.",),
        "history_parts": ("[ 2026 c 199 s 6 .]",),
    },
    "4.84.320": {
        "caption": (
            "Attorneys' fees in actions for injuries resulting from the "
            "rendering of medical and other health care."
        ),
        "body_parts": ("See RCW 7.70.070 .",),
        "history_parts": (),
    },
    "6.23.011": {
        "caption": (
            "Voluntary relinquishment of ownership rights by mortgagor may "
            "result in loss of redemption rights."
        ),
        "body_parts": ("See RCW 61.12.093 through 61.12.095 .",),
        "history_parts": (),
    },
    "7.04a.900": {
        "caption": "Effective date — 2005 c 433.",
        "body_parts": ("This act takes effect January 1, 2006.",),
        "history_parts": ("[ 2005 c 433 s 51 .]",),
    },
}
_TERMINAL_CAPTION_PATTERNS = (
    (
        "repealed",
        re.compile(
            r"^\[?repealed\]?(?:\.|$|\s+(?:by|effective)\b)",
            re.IGNORECASE,
        ),
    ),
    ("reserved", re.compile(r"^\[?reserved\]?\.?$", re.IGNORECASE)),
    (
        "expired",
        re.compile(
            r"^\[?expired\]?(?:\.|$|\s+(?:by|effective)\b)",
            re.IGNORECASE,
        ),
    ),
    (
        "renumbered",
        re.compile(
            r"^\[?renumbered\]?(?:\.|$|\s+(?:as|to|effective)\b)",
            re.IGNORECASE,
        ),
    ),
    (
        "deleted",
        re.compile(
            r"^\[?deleted\]?(?:\.|$|\s+(?:by|effective)\b)",
            re.IGNORECASE,
        ),
    ),
    (
        "transferred",
        re.compile(
            r"^\[?transferred\]?(?:\.|$|\s+(?:as|to|effective)\b)",
            re.IGNORECASE,
        ),
    ),
    (
        "recodified",
        re.compile(
            r"^\[?recodified\]?(?:\.|$|\s+(?:as|to|effective)\b)",
            re.IGNORECASE,
        ),
    ),
)

_SOURCE_BOUND_SHORT_BODY_PATTERNS = (
    (
        "cross_reference",
        re.compile(r"^See\s+\S.+\.$", re.IGNORECASE),
    ),
    (
        "effective_date",
        re.compile(
            r"^This act takes effect "
            r"[A-Z][a-z]+\s+\d{1,2},\s+\d{4}\.$",
            re.IGNORECASE,
        ),
    ),
    (
        "expiration_date",
        re.compile(
            r"^This chapter expires "
            r"[A-Z][a-z]+\s+\d{1,2},\s+\d{4}\.$",
            re.IGNORECASE,
        ),
    ),
    (
        "incorporation_by_reference",
        re.compile(
            rf"^RCW\s+{_SECTION_CITE_PATTERN}\s+"
            r"appl(?:y|ies) to this (?:chapter|title)\.$",
            re.IGNORECASE,
        ),
    ),
)

_DECODIFIED_SECTION_NOTE_RE = re.compile(
    r"^Notes:\s+Reviser's note:\s+RCW\s+.+?\s+was amended by\s+.+?\s+"
    r"without reference to its repeal by\s+.+?\s+It has been decodified "
    r"for publication purposes under RCW\s+1\.12\.025\s*\.$",
    re.IGNORECASE,
)


def section_url(cite: str) -> str:
    return f"{BASE}/default.aspx?cite={cite}"


def _clean(text: str) -> str:
    return _WS.sub(" ", (text or "").replace("\xa0", " ")).strip()


def _caption_identity(text: str) -> str:
    """Normalize only markup-created spacing in an RCW caption."""

    normalized = _clean(text)
    normalized = re.sub(r"\s*([\u2013\u2014])\s*", r"\1", normalized)
    normalized = re.sub(r"\(\s+", "(", normalized)
    normalized = re.sub(r"\s+\)", ")", normalized)
    return re.sub(r"\s+([.,;:])", r"\1", normalized)


def _effective_boundary(value: str) -> Optional[date]:
    try:
        return datetime.strptime(value, "%B %d, %Y").date()
    except (TypeError, ValueError):
        return None


def _variant_caption_contract(caption: str) -> Optional[Dict[str, Any]]:
    """Return an exact temporal/contingent qualifier from one RCW caption."""

    normalized = _caption_identity(caption)
    final = _VARIANT_FINAL_PAREN_RE.fullmatch(normalized)
    if final is None:
        if re.search(r"\b(?:effective|contingent)\b", normalized, re.IGNORECASE):
            return None
        return {
            "base_caption": normalized,
            "effective_from": None,
            "effective_until": None,
            "contingent_role": "",
            "qualification_kind": "unqualified",
        }

    qualifier = final.group("value")
    until_match = _VARIANT_UNTIL_QUALIFIER_RE.fullmatch(qualifier)
    from_match = _VARIANT_FROM_QUALIFIER_RE.fullmatch(qualifier)
    contingent_match = _VARIANT_CONTINGENT_QUALIFIER_RE.fullmatch(qualifier)
    if until_match is not None:
        upper = _effective_boundary(until_match.group("until"))
        if upper is None:
            return None
        return {
            "base_caption": final.group("base"),
            "effective_from": None,
            "effective_until": upper,
            "contingent_role": str(until_match.group("contingent") or "").lower(),
            "qualification_kind": "dated_interval",
        }
    if from_match is not None:
        lower = _effective_boundary(from_match.group("from"))
        upper = (
            _effective_boundary(from_match.group("until"))
            if from_match.group("until")
            else None
        )
        if lower is None or (upper is not None and lower >= upper):
            return None
        return {
            "base_caption": final.group("base"),
            "effective_from": lower,
            "effective_until": upper,
            "contingent_role": str(from_match.group("contingent") or "").lower(),
            "qualification_kind": "dated_interval",
        }
    if contingent_match is not None:
        return {
            "base_caption": final.group("base"),
            "effective_from": None,
            "effective_until": None,
            "contingent_role": str(contingent_match.group("contingent")).lower(),
            "qualification_kind": "contingent",
        }
    if re.search(r"\b(?:effective|contingent)\b", qualifier, re.IGNORECASE):
        return None
    return {
        "base_caption": normalized,
        "effective_from": None,
        "effective_until": None,
        "contingent_role": "",
        "qualification_kind": "unqualified",
    }


def _multi_version_section_contract_from_soup(
    soup: Any,
) -> Optional[Dict[str, Any]]:
    """Extract an exact arbitrary-cardinality same-cite RCW page.

    The official renderer places each version in one top-level body div,
    followed by one bracketed history div and an optional Notes block.  Every
    later version begins with adjacent same-cite ``h3.h1``/``h4.h2`` divs.
    Keeping that complete structural contract prevents a decorated or partial
    page from falling through to the permissive single-version parser.
    """

    title_text = _clean(soup.title.get_text(" ")) if soup.title else ""
    title_match = _SECTION_PAGE_DUAL_TITLE_RE.fullmatch(title_text)
    title_block = soup.select_one("#ContentPlaceHolder1_pnlTitleBlock")
    wrapper = soup.find("div", id="contentWrapper")
    if title_match is None or title_block is None or wrapper is None:
        return None
    wrapper_classes = {
        str(value).strip().casefold()
        for value in (wrapper.get("class") or [])
        if str(value).strip()
    }
    if "section-page" not in wrapper_classes:
        return None

    primary_headings = title_block.select("h1")
    primary_captions = title_block.select("h2")
    nested_headings = wrapper.select("h3.h1")
    nested_captions = wrapper.select("h4.h2")
    if (
        len(primary_headings) != 1
        or len(primary_captions) != 1
        or not nested_headings
        or len(nested_headings) != len(nested_captions)
    ):
        return None

    cite = title_match.group("cite")
    headings = [primary_headings[0], *nested_headings]
    for heading in headings:
        match = _SECTION_PAGE_HEADING_RE.fullmatch(_clean(heading.get_text(" ")))
        if match is None or match.group("cite").casefold() != cite.casefold():
            return None

    direct_divs = wrapper.find_all("div", recursive=False)

    def _direct_position(node: Any) -> Optional[int]:
        matches = [
            index
            for index, div in enumerate(direct_divs)
            if div is node or any(descendant is node for descendant in div.descendants)
        ]
        return matches[0] if len(matches) == 1 else None

    heading_positions = [_direct_position(node) for node in nested_headings]
    caption_positions = [_direct_position(node) for node in nested_captions]
    if any(value is None for value in (*heading_positions, *caption_positions)):
        return None
    heading_indexes = [int(value) for value in heading_positions]
    caption_indexes = [int(value) for value in caption_positions]
    if (
        heading_indexes != sorted(set(heading_indexes))
        or caption_indexes != sorted(set(caption_indexes))
        or any(
            caption_index != heading_index + 1
            for heading_index, caption_index in zip(
                heading_indexes,
                caption_indexes,
                strict=True,
            )
        )
    ):
        return None

    captions = [
        _clean(primary_captions[0].get_text(" ")),
        *[_clean(node.get_text(" ")) for node in nested_captions],
    ]
    title_caption_identity = _caption_identity(title_match.group("caption")).casefold()
    title_matching_indexes = [
        index
        for index, caption in enumerate(captions)
        if _caption_identity(caption).casefold() == title_caption_identity
    ]
    if not title_matching_indexes:
        return None

    segment_ranges = [(0, heading_indexes[0])]
    segment_ranges.extend(
        (
            caption_indexes[index] + 1,
            heading_indexes[index + 1]
            if index + 1 < len(heading_indexes)
            else len(direct_divs),
        )
        for index in range(len(heading_indexes))
    )
    if len(segment_ranges) != len(captions):
        return None

    variants: List[Dict[str, Any]] = []
    for caption, (start, end) in zip(captions, segment_ranges, strict=True):
        segment = direct_divs[start:end]
        history_positions = [
            index
            for index, div in enumerate(segment)
            if "margin-top:15pt" in str(div.get("style") or "")
        ]
        if len(history_positions) != 1:
            return None
        history_index = history_positions[0]
        body_parts = [
            _clean(div.get_text(" "))
            for div in segment[:history_index]
            if _clean(div.get_text(" "))
        ]
        if len(body_parts) > 1:
            return None
        body = body_parts[0] if body_parts else ""
        history = _clean(segment[history_index].get_text(" "))
        notes = [
            _clean(div.get_text(" "))
            for div in segment[history_index + 1 :]
            if _clean(div.get_text(" "))
        ]
        if (
            (body and len(body) < 40)
            or re.fullmatch(r"\[\s*.+\.\]", history) is None
            or (notes and notes[0].casefold() != "notes:")
        ):
            return None
        caption_contract = _variant_caption_contract(caption)
        if caption_contract is None:
            return None
        variants.append(
            {
                "caption": caption,
                "body": body,
                "history": history,
                "notes": tuple(notes),
                **caption_contract,
            }
        )

    combined_notes = " ".join(
        note for variant in variants for note in variant["notes"]
    )
    # Preserve the separately audited legacy 70.96.150 contract.  If any of
    # its exact proof phrases drift, the broader extractor must not rescue it.
    if "subsequently recodified" in combined_notes.casefold():
        return None

    if len(variants) == 2:
        upper_only = [
            variant
            for variant in variants
            if variant["effective_from"] is None
            and variant["effective_until"] is not None
            and not variant["contingent_role"]
        ]
        lower_only = [
            variant
            for variant in variants
            if variant["effective_from"] is not None
            and variant["effective_until"] is None
            and not variant["contingent_role"]
        ]
        if (
            len(upper_only) == 1
            and len(lower_only) == 1
            and upper_only[0]["effective_until"]
            != lower_only[0]["effective_from"]
        ):
            return None

    return {
        "cite": cite,
        "title_caption": title_match.group("caption"),
        "title_matching_indexes": tuple(title_matching_indexes),
        "variants": tuple(variants),
        "combined_notes": combined_notes,
    }


def _multi_version_selection(
    contract: Dict[str, Any],
    *,
    as_of_date: date,
    source_content_sha256: str,
) -> Optional[Dict[str, Any]]:
    """Select one operative version using dates and publisher-bound proof."""

    variants = list(contract["variants"])
    candidates = [
        index
        for index, variant in enumerate(variants)
        if variant["body"]
        and (
            variant["effective_from"] is None
            or variant["effective_from"] <= as_of_date
        )
        and (
            variant["effective_until"] is None
            or as_of_date < variant["effective_until"]
        )
    ]
    if not candidates:
        return None
    combined_notes_folded = str(contract["combined_notes"]).casefold()
    conflict_note_bound = any(
        marker in combined_notes_folded
        for marker in _MULTI_VERSION_CONFLICT_MARKERS
    )

    # A later explicit start supersedes an otherwise unbounded earlier branch.
    latest_start = max(
        variants[index]["effective_from"] or date.min for index in candidates
    )
    candidates = [
        index
        for index in candidates
        if (variants[index]["effective_from"] or date.min) == latest_start
    ]
    if len(candidates) == 1:
        if sum(bool(variant["body"]) for variant in variants) == 1:
            if not conflict_note_bound:
                return None
            return {
                "selected_index": candidates[0],
                "selection": "publisher_unique_nonempty_parallel_amendment",
                "contingent_status_evidence": "",
            }
        return {
            "selected_index": candidates[0],
            "selection": "source_observation_date",
            "contingent_status_evidence": "",
        }

    role_indexes = {
        role: [
            index
            for index in candidates
            if variants[index]["contingent_role"] == role
        ]
        for role in ("expiration", "effective")
    }
    if all(len(role_indexes[role]) == 1 for role in role_indexes):
        combined_notes = str(contract["combined_notes"])
        if _CONTINGENCY_DID_NOT_OCCUR_RE.search(combined_notes):
            return {
                "selected_index": role_indexes["expiration"][0],
                "selection": "official_reviser_contingency_nonoccurrence",
                "contingent_status_evidence": "explicit_reviser_nonoccurrence_note",
            }
        if _CONTINGENCY_OCCURRED_RE.search(combined_notes):
            return {
                "selected_index": role_indexes["effective"][0],
                "selection": "official_reviser_contingency_occurrence",
                "contingent_status_evidence": "explicit_reviser_occurrence_note",
            }
        before_index = role_indexes["expiration"][0]
        after_index = role_indexes["effective"][0]
        if before_index == 0 and after_index > before_index:
            reviewed_snapshot = _REVIEWED_PENDING_CONTINGENCY_SNAPSHOTS.get(
                str(contract["cite"]).casefold()
            )
            if (
                reviewed_snapshot is None
                or source_content_sha256
                != reviewed_snapshot["content_sha256"]
                or as_of_date != reviewed_snapshot["observed_on"]
            ):
                return None
            return {
                "selected_index": before_index,
                "selection": "official_pending_contingency_primary_branch",
                "contingent_status_evidence": "reviewed_retained_snapshot_digest",
                "contingent_status_content_sha256": source_content_sha256,
                "contingent_status_observed_on": as_of_date.isoformat(),
            }
        return None

    title_candidates = [
        index
        for index in candidates
        if index in contract["title_matching_indexes"]
    ]
    if len(title_candidates) != 1:
        return None
    if not conflict_note_bound:
        return None
    return {
        "selected_index": title_candidates[0],
        "selection": "publisher_title_bound_parallel_amendment",
        "contingent_status_evidence": "",
    }


def _dual_effective_section_contract_from_soup(
    soup: Any,
) -> Optional[Dict[str, Any]]:
    """Return two exact same-cite RCW versions from the official page shape."""

    title_text = _clean(soup.title.get_text(" ")) if soup.title else ""
    title_match = _SECTION_PAGE_DUAL_TITLE_RE.fullmatch(title_text)
    title_block = soup.select_one("#ContentPlaceHolder1_pnlTitleBlock")
    wrapper = soup.find("div", id="contentWrapper")
    if title_match is None or title_block is None or wrapper is None:
        return None
    wrapper_classes = {
        str(value).strip().casefold()
        for value in (wrapper.get("class") or [])
        if str(value).strip()
    }
    if "section-page" not in wrapper_classes:
        return None

    primary_headings = title_block.select("h1")
    primary_captions = title_block.select("h2")
    nested_headings = wrapper.select("h3.h1")
    nested_captions = wrapper.select("h4.h2")
    if not all(
        len(nodes) == 1
        for nodes in (
            primary_headings,
            primary_captions,
            nested_headings,
            nested_captions,
        )
    ):
        return None

    cite = title_match.group("cite")
    primary_heading = _clean(primary_headings[0].get_text(" "))
    nested_heading = _clean(nested_headings[0].get_text(" "))
    primary_match = _SECTION_PAGE_HEADING_RE.fullmatch(primary_heading)
    nested_match = _SECTION_PAGE_HEADING_RE.fullmatch(nested_heading)
    if (
        primary_match is None
        or nested_match is None
        or primary_match.group("cite").casefold() != cite.casefold()
        or nested_match.group("cite").casefold() != cite.casefold()
    ):
        return None

    primary_caption = _clean(primary_captions[0].get_text(" "))
    nested_caption = _clean(nested_captions[0].get_text(" "))
    primary_caption_identity = _caption_identity(primary_caption)
    nested_caption_identity = _caption_identity(nested_caption)
    until_match = _EFFECTIVE_UNTIL_CAPTION_RE.fullmatch(
        primary_caption_identity
    )
    from_match = _EFFECTIVE_FROM_CAPTION_RE.fullmatch(nested_caption_identity)
    if (
        until_match is None
        or from_match is None
        or _caption_identity(title_match.group("caption")).casefold()
        != nested_caption_identity.casefold()
    ):
        return None
    until_boundary = _effective_boundary(until_match.group("date"))
    from_boundary = _effective_boundary(from_match.group("date"))
    if until_boundary is None or until_boundary != from_boundary:
        return None

    direct_divs = wrapper.find_all("div", recursive=False)
    nested_heading_node = nested_headings[0]
    nested_heading_positions = [
        index
        for index, div in enumerate(direct_divs)
        if any(node is nested_heading_node for node in div.descendants)
    ]
    nested_caption_node = nested_captions[0]
    nested_caption_positions = [
        index
        for index, div in enumerate(direct_divs)
        if any(node is nested_caption_node for node in div.descendants)
    ]
    if (
        len(nested_heading_positions) != 1
        or len(nested_caption_positions) != 1
    ):
        return None
    nested_heading_index = nested_heading_positions[0]
    nested_caption_index = nested_caption_positions[0]
    if nested_caption_index != nested_heading_index + 1:
        return None

    before_nested = direct_divs[:nested_heading_index]
    primary_history_positions = [
        index
        for index, div in enumerate(before_nested)
        if "margin-top:15pt" in str(div.get("style") or "")
    ]
    if len(primary_history_positions) != 1:
        return None
    primary_history_index = primary_history_positions[0]
    primary_body_positions = [
        index
        for index, div in enumerate(before_nested[:primary_history_index])
        if _clean(div.get_text(" "))
    ]
    if len(primary_body_positions) != 1:
        return None
    primary_body_index = primary_body_positions[0]
    primary_notes = [
        _clean(div.get_text(" "))
        for div in before_nested[primary_history_index + 1 :]
        if _clean(div.get_text(" "))
    ]
    if primary_notes and primary_notes[0].casefold() != "notes:":
        return None

    future_body_index = nested_caption_index + 1
    future_history_index = nested_caption_index + 2
    future_notes_index = nested_caption_index + 3
    if future_history_index >= len(direct_divs):
        return None
    if "margin-top:15pt" not in str(
        direct_divs[future_history_index].get("style") or ""
    ):
        return None
    future_notes = [
        _clean(div.get_text(" "))
        for div in direct_divs[future_notes_index:]
        if _clean(div.get_text(" "))
    ]
    if future_notes and future_notes[0].casefold() != "notes:":
        return None

    primary_body = _clean(direct_divs[primary_body_index].get_text(" "))
    primary_history = _clean(direct_divs[primary_history_index].get_text(" "))
    future_body = _clean(direct_divs[future_body_index].get_text(" "))
    future_history = _clean(direct_divs[future_history_index].get_text(" "))
    if (
        len(primary_body) < 40
        or len(future_body) < 40
        or not re.fullmatch(r"\[\s*.+\.\]", primary_history)
        or not re.fullmatch(r"\[\s*.+\.\]", future_history)
    ):
        return None

    return {
        "cite": cite,
        "boundary_date": until_boundary,
        "variants": (
            {
                "caption": primary_caption,
                "body": primary_body,
                "history": primary_history,
                "effective_from": None,
                "effective_until": until_boundary,
            },
            {
                "caption": nested_caption,
                "body": future_body,
                "history": future_history,
                "effective_from": from_boundary,
                "effective_until": None,
            },
        ),
    }


def _legacy_conflicting_repeal_section_contract_from_soup(
    soup: Any,
) -> Optional[Dict[str, Any]]:
    """Select the publisher-designated operative version on an exact legacy page.

    Washington publishes a small legacy shape where one enactment repealed a
    section while a same-session enactment amended it without cognizance of
    that repeal.  The page keeps the repealed history first and publishes the
    operative amendment as a second same-cite section whose caption is also
    the document-title caption.  Admit only that complete source-bound shape.
    """

    title_text = _clean(soup.title.get_text(" ")) if soup.title else ""
    title_match = _SECTION_PAGE_DUAL_TITLE_RE.fullmatch(title_text)
    title_block = soup.select_one("#ContentPlaceHolder1_pnlTitleBlock")
    wrapper = soup.find("div", id="contentWrapper")
    if title_match is None or title_block is None or wrapper is None:
        return None
    wrapper_classes = {
        str(value).strip().casefold()
        for value in (wrapper.get("class") or [])
        if str(value).strip()
    }
    if "section-page" not in wrapper_classes:
        return None

    primary_headings = title_block.select("h1")
    primary_captions = title_block.select("h2")
    nested_headings = wrapper.select("h3.h1")
    nested_captions = wrapper.select("h4.h2")
    if not all(
        len(nodes) == 1
        for nodes in (
            primary_headings,
            primary_captions,
            nested_headings,
            nested_captions,
        )
    ):
        return None

    cite = title_match.group("cite")
    primary_match = _SECTION_PAGE_HEADING_RE.fullmatch(
        _clean(primary_headings[0].get_text(" "))
    )
    nested_match = _SECTION_PAGE_HEADING_RE.fullmatch(
        _clean(nested_headings[0].get_text(" "))
    )
    nested_caption = _clean(nested_captions[0].get_text(" "))
    if (
        primary_match is None
        or nested_match is None
        or primary_match.group("cite").casefold() != cite.casefold()
        or nested_match.group("cite").casefold() != cite.casefold()
        or _caption_identity(title_match.group("caption")).casefold()
        != _caption_identity(nested_caption).casefold()
    ):
        return None

    direct_divs = wrapper.find_all("div", recursive=False)
    nested_heading_positions = [
        index
        for index, div in enumerate(direct_divs)
        if any(node is nested_headings[0] for node in div.descendants)
    ]
    nested_caption_positions = [
        index
        for index, div in enumerate(direct_divs)
        if any(node is nested_captions[0] for node in div.descendants)
    ]
    if (
        len(nested_heading_positions) != 1
        or len(nested_caption_positions) != 1
        or nested_caption_positions[0] != nested_heading_positions[0] + 1
    ):
        return None
    nested_heading_index = nested_heading_positions[0]
    nested_caption_index = nested_caption_positions[0]

    before_nested = direct_divs[:nested_heading_index]
    primary_history_positions = [
        index
        for index, div in enumerate(before_nested)
        if "margin-top:15pt" in str(div.get("style") or "")
    ]
    if len(primary_history_positions) != 1:
        return None
    primary_history_index = primary_history_positions[0]
    if any(
        _clean(div.get_text(" "))
        for div in before_nested[:primary_history_index]
    ):
        return None
    primary_history = _clean(
        before_nested[primary_history_index].get_text(" ")
    )
    primary_notes = " ".join(
        _clean(div.get_text(" "))
        for div in before_nested[primary_history_index + 1 :]
        if _clean(div.get_text(" "))
    )
    if (
        not re.fullmatch(r"\[\s*.+\.\]", primary_history)
        or not primary_notes.casefold().startswith("notes:")
        or "without cognizance of the repeal thereof" not in primary_notes.casefold()
        or "subsequently recodified" not in primary_notes.casefold()
    ):
        return None

    operative_body_index = nested_caption_index + 1
    operative_history_index = nested_caption_index + 2
    operative_notes_index = nested_caption_index + 3
    if operative_notes_index >= len(direct_divs):
        return None
    if "margin-top:15pt" not in str(
        direct_divs[operative_history_index].get("style") or ""
    ):
        return None
    operative_body = _clean(direct_divs[operative_body_index].get_text(" "))
    operative_history = _clean(
        direct_divs[operative_history_index].get_text(" ")
    )
    operative_notes = " ".join(
        _clean(div.get_text(" "))
        for div in direct_divs[operative_notes_index:]
        if _clean(div.get_text(" "))
    )
    operative_notes_folded = operative_notes.casefold()
    if (
        len(operative_body) < 40
        or not re.fullmatch(r"\[\s*.+\.\]", operative_history)
        or not operative_notes_folded.startswith("notes:")
        or "also repealed by" not in operative_notes_folded
        or "without cognizance of its amendment" not in operative_notes_folded
        or "subsequently recodified" not in operative_notes_folded
        or "rcw 1.12.025" not in operative_notes_folded
    ):
        return None

    return {
        "cite": cite,
        "caption": nested_caption,
        "body": operative_body,
        "history": operative_history,
        "excluded_history": primary_history,
        "resolution": "publisher_title_bound_same_session_amendment",
    }


def dual_effective_section_contract(html: str) -> Optional[Dict[str, Any]]:
    """Expose a fail-closed two-version contract for an official RCW page."""

    if "effective until" not in str(html or "").casefold():
        return None
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return None
    return _dual_effective_section_contract_from_soup(
        BeautifulSoup(html or "", "html.parser")
    )


def _cite_from_url(url: str) -> str:
    try:
        parsed = urlparse(url)
        values = parse_qs(parsed.query).get("cite") or parse_qs(parsed.query).get("Cite") or []
        return str(values[0] if values else "").strip()
    except Exception:
        return ""


def section_page_identity(html: str) -> Optional[str]:
    """Return the exact RCW identity when all visible identity markers agree."""

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return None

    soup = BeautifulSoup(html or "", "html.parser")
    title_text = _clean(soup.title.get_text(" ")) if soup.title else ""
    heading_node = soup.select_one("#ContentPlaceHolder1_pnlTitleBlock h1")
    heading_text = _clean(heading_node.get_text(" ")) if heading_node else ""
    title_match = _SECTION_PAGE_TITLE_RE.match(title_text)
    heading_match = _SECTION_PAGE_HEADING_RE.match(heading_text)
    if title_match is None:
        dual_contract = _dual_effective_section_contract_from_soup(soup)
        if dual_contract is not None:
            return str(dual_contract["cite"])
        legacy_contract = _legacy_conflicting_repeal_section_contract_from_soup(
            soup
        )
        if legacy_contract is not None:
            return str(legacy_contract["cite"])
        multi_contract = _multi_version_section_contract_from_soup(soup)
        return str(multi_contract["cite"]) if multi_contract is not None else None
    if heading_match is None:
        return None
    title_cite = title_match.group("cite")
    heading_cite = heading_match.group("cite")
    if title_cite.casefold() != heading_cite.casefold():
        return None
    return title_cite


def chapter_page_identity(html: str) -> Optional[str]:
    """Return an exact RCW chapter identity from its title, heading, and wrapper."""

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return None

    soup = BeautifulSoup(html or "", "html.parser")
    title_text = _clean(soup.title.get_text(" ")) if soup.title else ""
    heading_node = soup.select_one("#ContentPlaceHolder1_pnlTitleBlock h1")
    heading_text = _clean(heading_node.get_text(" ")) if heading_node else ""
    wrapper = soup.find("div", id="contentWrapper")
    title_match = _CHAPTER_PAGE_TITLE_RE.fullmatch(title_text)
    heading_match = _CHAPTER_PAGE_HEADING_RE.fullmatch(heading_text)
    wrapper_classes = {
        str(value).strip().casefold()
        for value in ((wrapper.get("class") if wrapper else None) or [])
        if str(value).strip()
    }
    if (
        title_match is None
        or "chapter-page" not in wrapper_classes
    ):
        return None
    title_cite = title_match.group("cite")
    if heading_match is not None:
        heading_cite = heading_match.group("cite")
        return (
            title_cite
            if title_cite.casefold() == heading_cite.casefold()
            else None
        )

    # Washington labels Uniform Commercial Code chapter pages as Articles,
    # while the document title and locator remain Chapter 62A.N RCW.  Admit
    # only that exact official shape and require its section table to bind the
    # same article prefix; a generic "Article N" heading is insufficient.
    article_match = _ARTICLE_PAGE_HEADING_RE.fullmatch(heading_text)
    ucc_chapter_match = re.fullmatch(
        r"62A\.(?P<article>\d+[A-Za-z]?)",
        title_cite,
        flags=re.IGNORECASE,
    )
    list_heading = soup.select_one("#contentWrapper h3.list-heading")
    if (
        article_match is None
        or ucc_chapter_match is None
        or _clean(list_heading.get_text(" ") if list_heading else "").casefold()
        != "sections"
        or article_match.group("article").casefold()
        != ucc_chapter_match.group("article").casefold()
    ):
        return None
    rows = chapter_section_rows(html)
    expected_prefix = f"{title_cite}-".casefold()
    if not rows or any(
        not re.fullmatch(_UCC_SECTION_PATTERN, cite, flags=re.IGNORECASE)
        or not cite.casefold().startswith(expected_prefix)
        for cite, _heading, _url in rows
    ):
        return None
    return title_cite


def section_cite_belongs_to_chapter(
    section_cite: str,
    chapter_cite: str,
) -> bool:
    """Bind a standard or UCC RCW section identity to its exact chapter."""

    section = str(section_cite or "").strip()
    chapter = str(chapter_cite or "").strip()
    if not section or not chapter:
        return False
    if re.fullmatch(_UCC_CHAPTER_PATTERN, chapter, flags=re.IGNORECASE):
        return bool(
            re.fullmatch(_UCC_SECTION_PATTERN, section, flags=re.IGNORECASE)
            and section.casefold().startswith(f"{chapter}-".casefold())
        )
    return bool(
        re.fullmatch(_STANDARD_CITE_PATTERN, section, flags=re.IGNORECASE)
        and section.casefold().startswith(f"{chapter}.".casefold())
    )


def source_bound_terminal_disposition_from_chapter_html(
    html: str,
    *,
    source_url: str,
    chapter_number: str,
) -> Optional[Dict[str, str]]:
    """Classify an exact zero-row RCW chapter from its own published content."""

    expected = str(chapter_number or "").strip()
    identity = chapter_page_identity(html)
    if (
        not expected
        or identity is None
        or identity.casefold() != expected.casefold()
        or source_url != section_url(expected)
        or chapter_section_rows(html)
    ):
        return None
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return None
    soup = BeautifulSoup(html or "", "html.parser")
    wrapper = soup.find("div", id="contentWrapper")
    if wrapper is None:
        return None
    visible_text = _clean(wrapper.get_text(" "))
    terminal = _SOURCE_BOUND_EMPTY_CHAPTER_TERMINALS.get(expected)
    if terminal and not visible_text:
        return {"disposition": terminal}

    without_pdf_control = re.sub(
        r"^PDF\s+",
        "",
        visible_text,
        flags=re.IGNORECASE,
    )
    direct_reference = re.fullmatch(
        rf"See\s+chapter\s+(?P<target>{_CHAPTER_CITE_PATTERN})\s+RCW\.?",
        without_pdf_control,
        flags=re.IGNORECASE,
    )
    if direct_reference is not None:
        return {
            "disposition": "cross_reference",
            "target_chapter": direct_reference.group("target"),
        }

    if not visible_text.casefold().startswith("notes:") or len(visible_text) > 1024:
        return None
    recodified = re.search(
        rf"has\s+been\s+codified\s+as\s+chapter\s+"
        rf"(?P<target>{_CHAPTER_CITE_PATTERN})\s+RCW\b",
        visible_text,
        flags=re.IGNORECASE,
    )
    if recodified is not None:
        return {
            "disposition": "recodified",
            "target_chapter": recodified.group("target"),
        }
    references = re.findall(
        rf"(?:See\s+)?chapter\s+({_CHAPTER_CITE_PATTERN})\s+RCW\b",
        visible_text,
        flags=re.IGNORECASE,
    )
    unique_references = list(dict.fromkeys(reference.casefold() for reference in references))
    if len(unique_references) == 1:
        original_target = next(
            reference
            for reference in references
            if reference.casefold() == unique_references[0]
        )
        return {
            "disposition": "notes_only_cross_reference",
            "target_chapter": original_target,
        }
    return None


def parse_washington_chapter_material_html(
    html: str,
    *,
    source_url: str,
    chapter_number: str,
    code_name: str = "Revised Code of Washington",
) -> Optional[NormalizedStatute]:
    """Normalize the two source-bound RCW redistricting-plan chapters."""

    expected = str(chapter_number or "").strip()
    specification = _SOURCE_BOUND_CHAPTER_MATERIALS.get(expected.casefold())
    identity = chapter_page_identity(html)
    if (
        specification is None
        or identity is None
        or identity.casefold() != expected.casefold()
        or source_url != section_url(expected)
        or chapter_section_rows(html)
    ):
        return None
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return None
    soup = BeautifulSoup(html or "", "html.parser")
    wrapper = soup.find("div", id="contentWrapper")
    if wrapper is None:
        return None
    for control in wrapper.select("a.btn, .hidden-print"):
        control.decompose()
    body = _clean(wrapper.get_text(" "))
    body_folded = body.casefold()
    if not body or not all(
        marker in body_folded for marker in specification["required_markers"]
    ):
        return None
    title_number = expected.split(".", 1)[0]
    return NormalizedStatute(
        state_code="WA",
        state_name="Washington",
        statute_id=f"{code_name} ch. {expected}",
        code_name=code_name,
        title_number=title_number,
        section_number=expected,
        section_name=str(specification["section_name"])[:200],
        full_text=body,
        source_url=source_url,
        official_cite=f"Wash. Rev. Code ch. {expected}",
        metadata=StatuteMetadata(),
        structured_data={
            "source_kind": "official_washington_chapter_material",
            "source_authority_class": "official",
            "discovery_method": "rcw_source_bound_chapter_material",
            "record_level": "chapter_material",
            "record_type": specification["record_type"],
            "source_record_id": source_url,
            "skip_hydrate": True,
        },
    )


def source_bound_terminal_disposition_from_section_html(
    html: str,
    *,
    source_url: str,
    section_number: str,
) -> Optional[str]:
    """Classify an exact official RCW terminal page without broad keyword guesses."""

    expected = str(section_number or "").strip()
    source_cite = _cite_from_url(source_url)
    identity = section_page_identity(html)
    if (
        not expected
        or not source_cite
        or identity is None
        or source_cite.casefold() != expected.casefold()
        or identity.casefold() != expected.casefold()
    ):
        return None
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return None
    soup = BeautifulSoup(html or "", "html.parser")
    wrapper = soup.find("div", id="contentWrapper")
    caption_node = soup.select_one("#ContentPlaceHolder1_pnlTitleBlock h2")
    if wrapper is None or caption_node is None:
        return None
    caption = _clean(caption_node.get_text(" "))
    for disposition, pattern in _TERMINAL_CAPTION_PATTERNS:
        if pattern.match(caption):
            return disposition
    visible_text = _clean(wrapper.get_text(" "))
    if (
        len(visible_text) <= 1024
        and _DECODIFIED_SECTION_NOTE_RE.fullmatch(visible_text)
    ):
        return "decodified"
    return None


def parse_washington_section_html(
    html: str,
    *,
    source_url: str = "",
    section_number: str = "",
    code_name: str = "Revised Code of Washington",
    as_of_date: Optional[date] = None,
) -> Optional[NormalizedStatute]:
    """Parse one RCW section page, selecting explicit effective variants."""

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return None

    soup = BeautifulSoup(html or "", "html.parser")
    wrapper = soup.find("div", id="contentWrapper")
    if wrapper is None:
        return None
    dual_contract = _dual_effective_section_contract_from_soup(soup)
    legacy_contract = _legacy_conflicting_repeal_section_contract_from_soup(
        soup
    )
    multi_contract = (
        _multi_version_section_contract_from_soup(soup)
        if dual_contract is None and legacy_contract is None
        else None
    )
    decorated_title = bool(
        soup.title
        and _SECTION_PAGE_DUAL_TITLE_RE.fullmatch(
            _clean(soup.title.get_text(" "))
        )
        and _SECTION_PAGE_TITLE_RE.fullmatch(
            _clean(soup.title.get_text(" "))
        )
        is None
    )
    has_nested_version_markers = bool(wrapper.select("h3.h1, h4.h2"))
    if (
        (decorated_title or has_nested_version_markers)
        and dual_contract is None
        and legacy_contract is None
        and multi_contract is None
    ):
        return None
    if dual_contract is not None:
        cite = str(dual_contract["cite"])
        expected_cite = section_number or _cite_from_url(source_url)
        if (
            not isinstance(as_of_date, date)
            or not expected_cite
            or expected_cite.casefold() != cite.casefold()
            or source_url != section_url(cite)
        ):
            return None
        variants = list(dual_contract["variants"])
        eligible = [
            (index, variant)
            for index, variant in enumerate(variants)
            if (
                variant["effective_from"] is None
                or variant["effective_from"] <= as_of_date
            )
            and (
                variant["effective_until"] is None
                or as_of_date < variant["effective_until"]
            )
        ]
        if len(eligible) != 1:
            return None
        selected_index, selected = eligible[0]
        variant_metadata = [
            {
                "variant_index": index,
                "caption": str(variant["caption"]),
                "effective_from": (
                    variant["effective_from"].isoformat()
                    if variant["effective_from"] is not None
                    else ""
                ),
                "effective_until": (
                    variant["effective_until"].isoformat()
                    if variant["effective_until"] is not None
                    else ""
                ),
                "body_sha256": hashlib.sha256(
                    str(variant["body"]).encode("utf-8")
                ).hexdigest(),
                "history_sha256": hashlib.sha256(
                    str(variant["history"]).encode("utf-8")
                ).hexdigest(),
            }
            for index, variant in enumerate(variants)
        ]
        selected_start = selected["effective_from"]
        return NormalizedStatute(
            state_code="WA",
            state_name="Washington",
            statute_id=f"{code_name} § {cite}",
            code_name=code_name,
            title_number=cite.split(".", 1)[0],
            section_number=cite,
            section_name=str(selected["caption"])[:200],
            full_text=str(selected["body"]),
            source_url=source_url,
            official_cite=f"Wash. Rev. Code § {cite}",
            metadata=StatuteMetadata(
                effective_date=(
                    selected_start.isoformat()
                    if selected_start is not None
                    else None
                ),
                history=[str(selected["history"])],
            ),
            structured_data={
                "source_kind": "official_washington_contentwrapper",
                "source_authority_class": "official",
                "discovery_method": "rcw_contentwrapper_div2",
                "source_bound_short_operative": False,
                "effective_variant_count": len(variants),
                "effective_variant_selection": "source_observation_date",
                "effective_variant_as_of_date": as_of_date.isoformat(),
                "effective_variant_boundary_date": dual_contract[
                    "boundary_date"
                ].isoformat(),
                "effective_variant_selected_index": selected_index,
                "effective_variant_excluded_indexes": [
                    index for index in range(len(variants)) if index != selected_index
                ],
                "effective_variants": variant_metadata,
                "skip_hydrate": True,
            },
        )
    if legacy_contract is not None:
        cite = str(legacy_contract["cite"])
        expected_cite = section_number or _cite_from_url(source_url)
        if (
            not expected_cite
            or expected_cite.casefold() != cite.casefold()
            or source_url != section_url(cite)
        ):
            return None
        return NormalizedStatute(
            state_code="WA",
            state_name="Washington",
            statute_id=f"{code_name} § {cite}",
            code_name=code_name,
            title_number=cite.split(".", 1)[0],
            section_number=cite,
            section_name=str(legacy_contract["caption"])[:200],
            full_text=str(legacy_contract["body"]),
            source_url=source_url,
            official_cite=f"Wash. Rev. Code § {cite}",
            metadata=StatuteMetadata(
                history=[str(legacy_contract["history"])],
            ),
            structured_data={
                "source_kind": "official_washington_contentwrapper",
                "source_authority_class": "official",
                "discovery_method": "rcw_legacy_conflicting_repeal_resolution",
                "effective_variant_count": 2,
                "effective_variant_selection": str(
                    legacy_contract["resolution"]
                ),
                "effective_variant_selected_index": 1,
                "effective_variant_excluded_indexes": [0],
                "excluded_variant_history_sha256": hashlib.sha256(
                    str(legacy_contract["excluded_history"]).encode("utf-8")
                ).hexdigest(),
                "source_bound_short_operative": False,
                "skip_hydrate": True,
            },
        )
    if multi_contract is not None:
        cite = str(multi_contract["cite"])
        expected_cite = section_number or _cite_from_url(source_url)
        if (
            not isinstance(as_of_date, date)
            or not expected_cite
            or expected_cite.casefold() != cite.casefold()
            or source_url != section_url(cite)
        ):
            return None
        selection = _multi_version_selection(
            multi_contract,
            as_of_date=as_of_date,
            source_content_sha256=hashlib.sha256(
                str(html or "").encode("utf-8")
            ).hexdigest(),
        )
        if selection is None:
            return None
        variants = list(multi_contract["variants"])
        selected_index = int(selection["selected_index"])
        selected = variants[selected_index]
        variant_metadata = [
            {
                "variant_index": index,
                "caption": str(variant["caption"]),
                "qualification_kind": str(variant["qualification_kind"]),
                "contingent_role": str(variant["contingent_role"]),
                "effective_from": (
                    variant["effective_from"].isoformat()
                    if variant["effective_from"] is not None
                    else ""
                ),
                "effective_until": (
                    variant["effective_until"].isoformat()
                    if variant["effective_until"] is not None
                    else ""
                ),
                "body_present": bool(variant["body"]),
                "body_sha256": hashlib.sha256(
                    str(variant["body"]).encode("utf-8")
                ).hexdigest(),
                "history_sha256": hashlib.sha256(
                    str(variant["history"]).encode("utf-8")
                ).hexdigest(),
                "notes_sha256": hashlib.sha256(
                    " ".join(variant["notes"]).encode("utf-8")
                ).hexdigest(),
            }
            for index, variant in enumerate(variants)
        ]
        structured_data: Dict[str, Any] = {
            "source_kind": "official_washington_contentwrapper",
            "source_authority_class": "official",
            "discovery_method": "rcw_same_cite_multi_version_contract",
            "source_bound_short_operative": False,
            "effective_variant_count": len(variants),
            "effective_variant_selection": str(selection["selection"]),
            "effective_variant_as_of_date": as_of_date.isoformat(),
            "effective_variant_selected_index": selected_index,
            "effective_variant_excluded_indexes": [
                index for index in range(len(variants)) if index != selected_index
            ],
            "effective_variant_title_caption": str(
                multi_contract["title_caption"]
            ),
            "effective_variants": variant_metadata,
            "skip_hydrate": True,
        }
        contingent_status_evidence = str(
            selection.get("contingent_status_evidence") or ""
        )
        if contingent_status_evidence:
            structured_data["contingent_status_evidence"] = (
                contingent_status_evidence
            )
            for key in (
                "contingent_status_content_sha256",
                "contingent_status_observed_on",
            ):
                value = selection.get(key)
                if value:
                    structured_data[key] = str(value)
        selected_start = selected["effective_from"]
        return NormalizedStatute(
            state_code="WA",
            state_name="Washington",
            statute_id=f"{code_name} § {cite}",
            code_name=code_name,
            title_number=cite.split(".", 1)[0],
            section_number=cite,
            section_name=str(selected["caption"])[:200],
            full_text=str(selected["body"]),
            source_url=source_url,
            official_cite=f"Wash. Rev. Code § {cite}",
            metadata=StatuteMetadata(
                effective_date=(
                    selected_start.isoformat()
                    if selected_start is not None
                    else None
                ),
                history=[str(selected["history"])],
            ),
            structured_data=structured_data,
        )

    title_text = _clean(soup.title.get_text(" ")) if soup.title else ""
    heading_node = soup.select_one("#ContentPlaceHolder1_pnlTitleBlock h1")
    heading_text = _clean(heading_node.get_text(" ")) if heading_node else ""
    title_match = _SECTION_PAGE_TITLE_RE.fullmatch(title_text)
    heading_match = _SECTION_PAGE_HEADING_RE.fullmatch(heading_text)
    page_identity = (
        title_match.group("cite")
        if (
            title_match is not None
            and heading_match is not None
            and title_match.group("cite").casefold()
            == heading_match.group("cite").casefold()
        )
        else ""
    )
    expected_cite = section_number or _cite_from_url(source_url)
    if expected_cite and (
        not page_identity
        or page_identity.casefold() != expected_cite.casefold()
        or (source_url and source_url != section_url(page_identity))
    ):
        return None
    top_divs = wrapper.find_all("div", recursive=False)
    body_parts: List[str] = []
    history_parts: List[str] = []
    heading = ""
    in_notes = False
    for index, div in enumerate(top_divs):
        style = str(div.get("style") or "")
        text = _clean(div.get_text(" "))
        if not text:
            continue
        if "margin-top:15pt" in style or (text.startswith("[") and "]" in text and len(text) < 400):
            history_parts.append(text)
            continue
        if text.lower() == "notes:":
            in_notes = True
            continue
        if in_notes:
            continue
        if index <= 1:
            continue
        if not heading:
            heading = text[:200]
        body_parts.append(text)
    body = _clean(" ".join(body_parts))
    cite = section_number or _cite_from_url(source_url)
    if not cite:
        match = _CITE_RE.search(heading) or _CITE_RE.search(body)
        cite = match.group(1) if match else ""
    if not cite:
        caption = soup.select_one("#ContentPlaceHolder1_pnlTitleBlock h1")
        caption_text = _clean(caption.get_text(" ")) if caption else ""
        match = _CITE_RE.search(caption_text)
        cite = match.group(1) if match else ""
    if not cite:
        return None
    title_number = cite.split(".", 1)[0]
    caption_node = soup.select_one("#ContentPlaceHolder1_pnlTitleBlock h2")
    caption = _clean(caption_node.get_text(" ")) if caption_node else heading
    short_contract = _SOURCE_BOUND_SHORT_OPERATIVE_SECTIONS.get(cite.casefold())
    exact_short_source_bound = bool(
        short_contract is not None
        and source_url == section_url(cite)
        and page_identity
        and page_identity.casefold() == cite.casefold()
        and "section-page"
        in {
            str(value).strip().casefold()
            for value in (wrapper.get("class") or [])
            if str(value).strip()
        }
        and caption == short_contract["caption"]
        and tuple(body_parts) == short_contract["body_parts"]
        and tuple(history_parts) == short_contract["history_parts"]
    )
    if short_contract is not None and not exact_short_source_bound:
        return None
    short_contract_kind = "exact_static" if exact_short_source_bound else ""
    if len(body) < 40 and not exact_short_source_bound:
        pattern_kind = next(
            (
                kind
                for kind, pattern in _SOURCE_BOUND_SHORT_BODY_PATTERNS
                if pattern.fullmatch(body)
            ),
            "",
        )
        history_bound = bool(history_parts) and all(
            re.fullmatch(r"\[\s*.+\.\]", value)
            for value in history_parts
        )
        general_short_source_bound = bool(
            body
            and caption
            and len(body_parts) == 1
            and source_url == section_url(cite)
            and page_identity
            and page_identity.casefold() == cite.casefold()
            and "section-page"
            in {
                str(value).strip().casefold()
                for value in (wrapper.get("class") or [])
                if str(value).strip()
            }
            and (pattern_kind or history_bound)
        )
        if not general_short_source_bound:
            return None
        short_contract_kind = pattern_kind or "source_history_bound"
    short_source_bound = bool(short_contract_kind)
    return NormalizedStatute(
        state_code="WA",
        state_name="Washington",
        statute_id=f"{code_name} § {cite}",
        code_name=code_name,
        title_number=title_number,
        section_number=cite,
        section_name=(caption or heading or cite)[:200],
        full_text=body,
        source_url=source_url or section_url(cite),
        official_cite=f"Wash. Rev. Code § {cite}",
        metadata=StatuteMetadata(),
        structured_data={
            "source_kind": "official_washington_contentwrapper",
            "source_authority_class": "official",
            "discovery_method": "rcw_contentwrapper_div2",
            "source_bound_short_operative": short_source_bound,
            "source_bound_short_contract_kind": short_contract_kind,
            "skip_hydrate": True,
        },
    )


def configured_section_html_path() -> Optional[Path]:
    raw = str(os.environ.get("WASHINGTON_SECTION_HTML") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None


def configured_toc_html_path() -> Optional[Path]:
    raw = str(os.environ.get("WASHINGTON_TOC_HTML") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None


def parse_configured_toc_html() -> List[str]:
    path = configured_toc_html_path()
    if path is None:
        return []
    return title_cites(path.read_text(encoding="utf-8", errors="replace"))


def title_cites(html: str) -> List[str]:
    """Title cites from the RCW TOC (``default.aspx?Cite=9A``)."""

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    soup = BeautifulSoup(html or "", "html.parser")
    out: List[str] = []
    seen = set()
    for anchor in soup.find_all("a", href=True):
        href = str(anchor.get("href") or "").strip()
        match = _TITLE_HREF_RE.search(href)
        if not match:
            continue
        cite = match.group(1)
        if cite in seen or "." in cite:
            continue
        seen.add(cite)
        out.append(cite)
    return out


def chapter_cites(html: str, *, title_cite: str = "") -> List[str]:
    """Two-segment chapter cites (``/rcw/default.aspx?cite=9A.32``)."""

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    soup = BeautifulSoup(html or "", "html.parser")
    wrapper = soup.find("div", id="contentWrapper") or soup
    out: List[str] = []
    seen = set()
    prefix = f"{title_cite}." if title_cite else ""
    for anchor in wrapper.find_all("a", href=True):
        href = str(anchor.get("href") or "").strip()
        match = _CHAPTER_HREF_RE.search(href)
        if not match:
            continue
        cite = match.group(1)
        if prefix and not cite.startswith(prefix):
            continue
        if cite.count(".") != 1 or cite in seen:
            continue
        seen.add(cite)
        out.append(cite)
    return out


def chapter_section_rows(html: str) -> List[Tuple[str, str, str]]:
    """Section cites from chapter table rows (number cell + heading cell)."""

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    soup = BeautifulSoup(html or "", "html.parser")
    wrapper = soup.find("div", id="contentWrapper") or soup
    out: List[Tuple[str, str, str]] = []
    seen = set()
    for row in wrapper.find_all("tr"):
        cells = row.find_all("td")
        if len(cells) < 3:
            continue
        link = cells[1].find("a", href=True)
        if link is None:
            continue
        cite = _clean(link.get_text(" "))
        if not cite or not cite[0].isdigit():
            continue
        if cite in seen:
            continue
        seen.add(cite)
        heading = _clean(cells[2].get_text(" "))
        out.append((cite, heading, section_url(cite)))
    return out
