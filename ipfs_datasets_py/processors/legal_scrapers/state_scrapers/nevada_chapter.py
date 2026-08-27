"""Official Nevada Revised Statutes chapter HTML parser.

``leg.state.nv.us/NRS/NRS-XXX.html`` publishes every section inline. The
compiler also publishes multiple effective versions under the same NRS number.
This parser keeps those source observations together and emits exactly one
version for the supplied source-observation date while retaining a digest and
effective-boundary disclosure for every excluded version.
"""

from __future__ import annotations

import hashlib
import os
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .base_scraper import NormalizedStatute, StatuteMetadata

BASE = "https://www.leg.state.nv.us/NRS"
_SECTION_NUM_RE = re.compile(
    r"^\d+[A-Za-z]?\.\d+(?:\.\d+)?[A-Za-z]?$",
    re.IGNORECASE,
)
_EXACT_TERMINAL_RE = re.compile(
    r"^[\[(]?\s*(?P<kind>repealed|reserved|expired|renumbered)"
    r"(?:\s+by\s+[^\])]+)?\s*[.\])]?$",
    re.IGNORECASE,
)
_CAPTION_TERMINAL_RE = re.compile(
    r"^.+?\.\s*[\[(]\s*(?P<kind>repealed|reserved|expired|renumbered)"
    r"(?:\s+by\s+[^\])]+)?\s*[\])]\.?$",
    re.IGNORECASE,
)
_HISTORY_RE = re.compile(
    r"^\s*(?:History\s*:|[([]?\s*(?:Added|Amended|Substituted)\b)",
    re.IGNORECASE,
)
_EFFECTIVE_QUALIFIER_RE = re.compile(
    r"\[(?P<qualifier>Effective\s+[^\]]+)\]\s*$",
    re.IGNORECASE,
)
_MONTH_PATTERN = (
    r"(?:January|February|March|April|May|June|July|August|September|"
    r"October|November|December)"
)
_DATE_RE = re.compile(
    rf"(?P<month>{_MONTH_PATTERN})\s+(?P<day>\d{{1,2}}),\s+"
    r"(?P<year>\d{4})",
    re.IGNORECASE,
)
_WS = re.compile(r"\s+")
_NRS_ANCHOR_RE = re.compile(
    r"^NRS(?P<chapter>\d+[A-Za-z]?)Sec(?P<section>\d+[A-Za-z]?)$",
    re.IGNORECASE,
)
_TOC_SECTION_RE = re.compile(
    r"^(?:NRS\s*)?(?P<number>\d+[A-Za-z]?\.\d+(?:\.\d+)?[A-Za-z]?)\b",
    re.IGNORECASE,
)


def _clean(text: str) -> str:
    return _WS.sub(" ", (text or "").replace("\xa0", " ")).strip()


def _terminal_disposition(heading: str) -> str:
    normalized = _clean(heading)
    for pattern in (_EXACT_TERMINAL_RE, _CAPTION_TERMINAL_RE):
        match = pattern.fullmatch(normalized)
        if match is not None:
            return str(match.group("kind") or "").casefold()
    return ""


def _section_number_parts(paragraph: Any) -> List[str]:
    """Return exact adjacent compiler ``span.Section`` fragments."""

    return [
        _clean(span.get_text(" ")).replace(" ", "")
        for span in paragraph.find_all("span", class_="Section")
    ]


def _normalized_chapter_token(value: str) -> str:
    match = re.fullmatch(r"0*(?P<number>\d+)(?P<suffix>[A-Za-z]?)", value)
    if match is None:
        return ""
    return f"{int(match.group('number'))}{match.group('suffix').upper()}"


def _page_identity_from_soup(soup: Any) -> str:
    title = _clean(soup.title.get_text(" ")) if soup.title else ""
    if re.fullmatch(r"NRS:\s*PRELIMINARY\s+CHAPTER", title, re.IGNORECASE):
        return "0"
    match = re.fullmatch(
        r"NRS:\s*CHAPTER\s+(?P<chapter>\d+[A-Za-z]?)\s*-\s*.+",
        title,
        flags=re.IGNORECASE,
    )
    return str(match.group("chapter") or "").upper() if match else ""


def _paragraph_body(paragraph: Any, *, number: str, heading: str) -> str:
    text = _clean(paragraph.get_text(" "))
    if heading:
        offset = text.find(heading)
        if offset >= 0:
            return _clean(text[offset + len(heading) :])
    offset = text.find(number)
    if offset >= 0:
        return _clean(text[offset + len(number) :])
    return text


def _date_from_match(match: re.Match[str]) -> date:
    return datetime.strptime(
        f"{match.group('month')} {match.group('day')} {match.group('year')}",
        "%B %d %Y",
    ).date()


def _effective_qualifier(heading: str) -> str:
    match = _EFFECTIVE_QUALIFIER_RE.search(_clean(heading))
    return _clean(match.group("qualifier")) if match else ""


def _calendar_boundaries(
    qualifier: str,
) -> Tuple[Optional[date], Optional[date], bool]:
    """Return conservative half-open calendar bounds and disjoint-window flag.

    Contingency language is intentionally not guessed here. Calendar dates can
    still exclude a branch (or make it newly possible), after which the strict
    selector resolves the remaining official pre/post-contingency branches.
    """

    normalized = _clean(qualifier)
    lowered = normalized.casefold().replace("–", "-").replace("—", "-")
    dated = [
        (match, _date_from_match(match)) for match in _DATE_RE.finditer(normalized)
    ]
    if not dated:
        return None, None, False

    through_and_after = re.fullmatch(
        rf"Effective\s+through\s+(?P<first>{_MONTH_PATTERN}\s+\d{{1,2}},\s+\d{{4}}),"
        rf"\s+and\s+after\s+(?P<second>{_MONTH_PATTERN}\s+\d{{1,2}},\s+\d{{4}})\.?",
        normalized,
        flags=re.IGNORECASE,
    )
    if through_and_after is not None:
        return None, None, True

    lower: Optional[date] = None
    upper: Optional[date] = None
    for match, observed in dated:
        prefix = lowered[max(0, match.start() - 48) : match.start()]
        nearest_clause = re.split(r"[,;]", prefix)[-1]
        if re.search(r"\b(?:through|earlier\s+of)\s*$", nearest_clause):
            candidate = observed + timedelta(days=1)
            upper = candidate if upper is None else min(upper, candidate)
            continue
        if re.search(
            r"\buntil(?:\s+the)?(?:\s+earlier\s+of)?\s*$", nearest_clause
        ):
            candidate = observed + timedelta(days=1)
            upper = candidate if upper is None else min(upper, candidate)
            continue
        if re.search(r"\bafter\s*$", nearest_clause):
            candidate = observed + timedelta(days=1)
            lower = candidate if lower is None else max(lower, candidate)
            continue
        if re.search(r"\b(?:effective|later\s+of)\s*$", nearest_clause):
            lower = observed if lower is None else max(lower, observed)

    return lower, upper, False


def _disjoint_calendar_eligible(qualifier: str, as_of_date: date) -> bool:
    normalized = _clean(qualifier)
    match = re.fullmatch(
        rf"Effective\s+through\s+(?P<first>{_MONTH_PATTERN}\s+\d{{1,2}},\s+\d{{4}}),"
        rf"\s+and\s+after\s+(?P<second>{_MONTH_PATTERN}\s+\d{{1,2}},\s+\d{{4}})\.?",
        normalized,
        flags=re.IGNORECASE,
    )
    if match is None:
        return False
    first = datetime.strptime(match.group("first"), "%B %d, %Y").date()
    second = datetime.strptime(match.group("second"), "%B %d, %Y").date()
    return as_of_date <= first or as_of_date > second


def _contingency_polarity(qualifier: str) -> str:
    lowered = _clean(qualifier).casefold()
    if not lowered:
        return "none"
    # A bare calendar boundary is completely resolved above and is not a
    # contingency.  Nevada's compiler uses a much wider event vocabulary than
    # a fixed marker list (regulations, notices, judgments, proclamations,
    # contracts, federal ratification, and more), but its branch grammar is
    # stable: ``until`` is the pre-event text and ``on/upon/when/from the date``
    # is the post-event text.
    calendar_only = re.fullmatch(
        rf"effective\s+(?:on\s+|until\s+|through\s+|after\s+)?"
        rf"{_MONTH_PATTERN}\s+\d{{1,2}},\s+\d{{4}}\.?",
        lowered,
        flags=re.IGNORECASE,
    )
    if calendar_only is not None:
        return "none"
    if lowered.startswith(
        (
            "effective on ",
            "effective upon ",
            "effective when ",
            "effective from the date ",
            "effective 2 years after ",
        )
    ) or "later of" in lowered:
        return "after"
    if (
        lowered.startswith("effective until")
        or lowered.startswith("effective through the earlier")
        or " and until " in lowered
    ):
        return "before"
    if _DATE_RE.search(lowered) is not None:
        return "none"
    return "unknown"


def _variant_temporal_metadata(
    variant: Dict[str, Any],
    as_of_date: Optional[date],
) -> Dict[str, Any]:
    qualifier = _effective_qualifier(str(variant["heading"]))
    lower, upper, disjoint = _calendar_boundaries(qualifier)
    if as_of_date is None:
        calendar_status = "not_evaluated"
    elif disjoint:
        calendar_status = (
            "eligible"
            if _disjoint_calendar_eligible(qualifier, as_of_date)
            else "ineligible"
        )
    elif (lower is None or lower <= as_of_date) and (
        upper is None or as_of_date < upper
    ):
        calendar_status = "eligible"
    else:
        calendar_status = "ineligible"
    polarity = _contingency_polarity(qualifier)
    if lower is not None or upper is not None or disjoint:
        temporal_kind = (
            "dated_contingency" if polarity != "none" else "dated_interval"
        )
    elif polarity != "none":
        temporal_kind = "contingency"
    else:
        temporal_kind = "unqualified"
    history = _clean(" ".join(variant["history_parts"]))
    body = _clean(" ".join(variant["body_parts"]))
    return {
        "body": body,
        "body_sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
        "calendar_status": calendar_status,
        "contingency_polarity": polarity,
        "effective_from": lower.isoformat() if lower is not None else "",
        "effective_qualifier": qualifier,
        "effective_until": upper.isoformat() if upper is not None else "",
        "history": history,
        "history_sha256": hashlib.sha256(history.encode("utf-8")).hexdigest(),
        "temporal_kind": temporal_kind,
    }


def _select_variant(
    variants: Sequence[Dict[str, Any]],
    *,
    as_of_date: Optional[date],
) -> Tuple[int, str, List[Dict[str, Any]]]:
    metadata = [
        _variant_temporal_metadata(variant, as_of_date) for variant in variants
    ]
    if len(variants) == 1:
        return 0, "single_official_variant", metadata

    named = [index for index, variant in enumerate(variants) if variant["anchor"]]
    if len(named) != 1:
        raise ValueError("Nevada repeated section lacks one exact compiler anchor")
    if any(not item["effective_qualifier"] for item in metadata):
        raise ValueError("Nevada repeated section lacks an effective-version qualifier")

    if as_of_date is None:
        return named[0], "official_named_anchor_without_observation_date", metadata

    eligible = [
        index
        for index, item in enumerate(metadata)
        if item["calendar_status"] != "ineligible"
    ]
    if len(eligible) == 1:
        return eligible[0], "source_observation_date", metadata

    before = [
        index
        for index in eligible
        if metadata[index]["contingency_polarity"] == "before"
    ]
    if len(before) == 1:
        return (
            before[0],
            "source_observation_date_pre_contingency_compiler_branch",
            metadata,
        )

    anchored_eligible = [index for index in eligible if index in named]
    if len(anchored_eligible) == 1 and all(
        metadata[index]["temporal_kind"] in {"contingency", "dated_contingency"}
        for index in eligible
    ):
        return (
            anchored_eligible[0],
            "source_observation_date_official_contingency_anchor",
            metadata,
        )
    raise ValueError(
        "Nevada effective variants do not select one observation-date row"
    )


def _variant_disclosure(
    variants: Sequence[Dict[str, Any]],
    temporal: Sequence[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    return [
        {
            "variant_index": index,
            "heading": _clean(str(variant["heading"])),
            "named_anchor": bool(variant["anchor"]),
            "source_anchor": str(variant["anchor"]),
            "effective_qualifier": str(item["effective_qualifier"]),
            "effective_from": str(item["effective_from"]),
            "effective_until": str(item["effective_until"]),
            "calendar_status": str(item["calendar_status"]),
            "contingency_polarity": str(item["contingency_polarity"]),
            "temporal_kind": str(item["temporal_kind"]),
            "full_text_chars": len(str(item["body"])),
            "full_text_sha256": str(item["body_sha256"]),
            "history_sha256": str(item["history_sha256"]),
            "section_identity_repair": str(variant["identity_repair"]),
            "section_number_raw": str(variant["raw_number"]),
            "section_number_fragments": list(variant["number_parts"]),
        }
        for index, (variant, item) in enumerate(zip(variants, temporal, strict=True))
    ]


def _raw_variants(html: str) -> List[Dict[str, Any]]:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    soup = BeautifulSoup(html or "", "html.parser")
    page_identity = _normalized_chapter_token(_page_identity_from_soup(soup))
    variants: List[Dict[str, Any]] = []
    current: Optional[Dict[str, Any]] = None

    def flush() -> None:
        nonlocal current
        if current is not None:
            variants.append(current)
        current = None

    for paragraph in soup.find_all("p"):
        spans = paragraph.find_all("span", class_="Section")
        if spans:
            flush()
            number_parts = _section_number_parts(paragraph)
            number = "".join(number_parts)
            if not _SECTION_NUM_RE.fullmatch(number):
                continue
            raw_number = number
            identity_repair = ""
            named = paragraph.find("a", attrs={"name": True})
            anchor = str(named.get("name") or "").strip() if named else ""
            section_chapter, section_tail = number.split(".", 1)
            if (
                page_identity
                and _normalized_chapter_token(section_chapter) != page_identity
            ):
                anchor_match = _NRS_ANCHOR_RE.fullmatch(anchor)
                if (
                    anchor_match is not None
                    and _normalized_chapter_token(anchor_match.group("chapter"))
                    == page_identity
                    and anchor_match.group("section").casefold()
                    == section_tail.replace(".", "").casefold()
                ):
                    number = f"{page_identity}.{section_tail}"
                    identity_repair = "official_chapter_anchor_prefix_repair"
            lead = paragraph.find("span", class_="Leadline")
            heading = _clean(lead.get_text(" ")) if lead else ""
            body = _paragraph_body(paragraph, number=number, heading=heading)
            current = {
                "anchor": anchor,
                "body_parts": [body] if body else [],
                "heading": heading,
                "history_parts": [],
                "identity_repair": identity_repair,
                "number": number,
                "number_parts": number_parts,
                "raw_number": raw_number,
            }
            continue
        if current is None:
            continue
        text = _clean(paragraph.get_text(" "))
        if not text:
            continue
        classes = {
            str(value).strip().casefold()
            for value in (paragraph.get("class") or [])
            if str(value).strip()
        }
        if "sourcenote" in classes or _HISTORY_RE.match(text):
            current["history_parts"].append(text)
            continue
        if classes and not any(value.startswith("sectbody") for value in classes):
            continue
        current["body_parts"].append(text)
    flush()
    return variants


def nevada_chapter_page_identity(html: str) -> str:
    """Return the exact chapter token declared by an official NRS page."""

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return ""
    soup = BeautifulSoup(html or "", "html.parser")
    return _page_identity_from_soup(soup)


def nevada_chapter_terminal_sections(html: str) -> List[Dict[str, str]]:
    """Return only exact compiler terminal headings, never keyword guesses."""

    out: List[Dict[str, str]] = []
    for variant in _raw_variants(html):
        disposition = _terminal_disposition(str(variant["heading"]))
        if not disposition:
            continue
        out.append(
            {
                "section_number": str(variant["number"]),
                "section_name": _clean(str(variant["heading"])),
                "disposition": disposition,
            }
        )
    return out


def nevada_chapter_toc_section_identities(html: str) -> List[str]:
    """Return the chapter's own ordered official section frontier."""

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    soup = BeautifulSoup(html or "", "html.parser")
    out: List[str] = []
    for paragraph in soup.find_all("p"):
        classes = {
            str(value).strip().casefold()
            for value in (paragraph.get("class") or [])
            if str(value).strip()
        }
        if "coleadline" not in classes:
            continue
        anchor = paragraph.find("a", href=True)
        if anchor is None or not str(anchor.get("href") or "").startswith("#NRS"):
            continue
        match = _TOC_SECTION_RE.match(_clean(paragraph.get_text(" ")))
        if match is not None:
            out.append(str(match.group("number")))
    return out


def parse_nevada_chapter_html(
    html: str,
    *,
    source_url: str = "",
    code_name: str = "Nevada Revised Statutes",
    max_statutes: Optional[int] = None,
    as_of_date: Optional[date] = None,
    temporal_exclusions: Optional[List[Dict[str, Any]]] = None,
) -> List[NormalizedStatute]:
    variants = _raw_variants(html)
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    order: List[str] = []
    for variant in variants:
        number = str(variant["number"])
        if number not in grouped:
            grouped[number] = []
            order.append(number)
        grouped[number].append(variant)

    statutes: List[NormalizedStatute] = []
    for number in order:
        section_variants = grouped[number]
        if len(section_variants) == 1:
            temporal = [
                _variant_temporal_metadata(section_variants[0], as_of_date)
            ]
            if (
                as_of_date is not None
                and temporal[0]["calendar_status"] == "ineligible"
            ):
                if temporal_exclusions is not None:
                    effective_from = str(temporal[0]["effective_from"])
                    effective_until = str(temporal[0]["effective_until"])
                    if effective_from and effective_from > as_of_date.isoformat():
                        reason = "future_effective_official_variant"
                    elif effective_until and effective_until <= as_of_date.isoformat():
                        reason = "expired_official_variant"
                    else:
                        reason = (
                            "no_official_variant_effective_on_observation_date"
                        )
                    named_anchors = [
                        str(variant["anchor"])
                        for variant in section_variants
                        if str(variant["anchor"])
                    ]
                    exclusion_url = source_url
                    if len(named_anchors) == 1:
                        exclusion_url = (
                            f"{source_url.split('#')[0]}#{named_anchors[0]}"
                        )
                    temporal_exclusions.append(
                        {
                            "as_of_date": as_of_date.isoformat(),
                            "exclusion_reason": reason,
                            "section_number": number,
                            "source_url": exclusion_url,
                            "variants": _variant_disclosure(
                                section_variants,
                                temporal,
                            ),
                        }
                    )
                continue
            selected_index = 0
            selection = (
                "source_observation_date_single_official_variant"
                if as_of_date is not None
                and temporal[0]["effective_qualifier"]
                else "single_official_variant"
            )
        else:
            selected_index, selection, temporal = _select_variant(
                section_variants,
                as_of_date=as_of_date,
            )
        selected = section_variants[selected_index]
        selected_temporal = temporal[selected_index]
        heading = _clean(str(selected["heading"]))
        if _terminal_disposition(heading):
            continue
        body = str(selected_temporal["body"])
        if not body:
            continue
        if max_statutes is not None and len(statutes) >= int(max_statutes):
            break

        named_anchors = [
            str(variant["anchor"])
            for variant in section_variants
            if str(variant["anchor"])
        ]
        canonical_anchor = (
            named_anchors[0]
            if len(named_anchors) == 1
            else str(selected["anchor"])
        )
        link = source_url or BASE
        if canonical_anchor:
            link = f"{link.split('#')[0]}#{canonical_anchor}"
        effective_date = str(selected_temporal["effective_from"] or "") or None
        variant_disclosure = _variant_disclosure(section_variants, temporal)
        structured: Dict[str, Any] = {
            "source_kind": "official_nevada_revised_statutes_html",
            "source_authority_class": "official",
            "discovery_method": "nrs_section_leadline",
            "source_section_identity_reconstructed": bool(
                sum(bool(part) for part in selected["number_parts"]) > 1
                or selected["identity_repair"]
            ),
            "source_section_identity_repair": str(selected["identity_repair"]),
            "source_section_number_raw": str(selected["raw_number"]),
            "source_section_number_empty_span_count": sum(
                not part for part in selected["number_parts"]
            ),
            "source_section_number_fragments": list(selected["number_parts"]),
            "source_section_number_span_count": len(selected["number_parts"]),
            "skip_hydrate": True,
        }
        if len(heading) > 200:
            structured.update(
                {
                    "source_section_name_full": heading,
                    "source_section_name_truncated_for_display": True,
                }
            )
        if len(section_variants) > 1 or selected_temporal["effective_qualifier"]:
            structured.update(
                {
                    "effective_variant_as_of_date": (
                        as_of_date.isoformat() if as_of_date is not None else ""
                    ),
                    "effective_variant_count": len(section_variants),
                    "effective_variant_excluded_indexes": [
                        index
                        for index in range(len(section_variants))
                        if index != selected_index
                    ],
                    "effective_variant_selected_index": selected_index,
                    "effective_variant_selection": selection,
                    "effective_variants": variant_disclosure,
                }
            )
        statutes.append(
            NormalizedStatute(
                state_code="NV",
                state_name="Nevada",
                statute_id=f"{code_name} § {number}",
                code_name=code_name,
                section_number=number,
                section_name=(heading or f"NRS {number}")[:200],
                full_text=body,
                source_url=link,
                official_cite=f"Nev. Rev. Stat. § {number}",
                metadata=StatuteMetadata(
                    effective_date=effective_date,
                    history=(
                        [str(selected_temporal["history"])]
                        if selected_temporal["history"]
                        else []
                    ),
                ),
                structured_data=structured,
            )
        )
    return statutes


def configured_chapter_html_path() -> Optional[Path]:
    raw = str(os.environ.get("NEVADA_CHAPTER_HTML") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None


_NRS_INDEX_RE = re.compile(r"NRS-(\d+[A-Za-z]?)\.html?$", re.IGNORECASE)


def nrs_index_links(
    html: str,
    *,
    base_url: str = f"{BASE}/",
) -> List[Tuple[str, str, str]]:
    """Index ``NRS-XXX.html`` chapter rows."""

    from urllib.parse import urljoin

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    soup = BeautifulSoup(html or "", "html.parser")
    out: List[Tuple[str, str, str]] = []
    seen: set[str] = set()
    for anchor in soup.find_all("a", href=True):
        href = str(anchor.get("href") or "").strip()
        match = _NRS_INDEX_RE.search(href)
        if not match:
            continue
        number = (
            str(int(match.group(1)))
            if match.group(1).isdigit()
            else match.group(1)
        )
        if number in seen:
            continue
        seen.add(number)
        name = _clean(anchor.get_text(" ")) or f"NRS {number}"
        out.append((number, name, urljoin(base_url, href)))
    return out


def configured_index_html_path() -> Optional[Path]:
    raw = str(os.environ.get("NEVADA_INDEX_HTML") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None


def parse_configured_index_html() -> List[Tuple[str, str, str]]:
    path = configured_index_html_path()
    if path is None:
        return []
    return nrs_index_links(path.read_text(encoding="utf-8", errors="replace"))
