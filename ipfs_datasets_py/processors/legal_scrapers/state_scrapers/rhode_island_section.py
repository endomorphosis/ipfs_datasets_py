"""Official Rhode Island section HTML parser.

Adapted from Vaquill-AI/open-us-law ``scrapeRI.py`` (Apache-2.0).
Canonical host is ``webserver.rilegislature.gov`` (the old rilin host
redirects every sub-path back to the TOC). Body is top-level ``divs[2]``;
the nested ``History of Section`` div is dropped.
"""

from __future__ import annotations

import os
import re
from datetime import date, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple
from urllib.parse import urljoin, urlparse

from .base_scraper import NormalizedStatute, StatuteMetadata

BASE = "https://webserver.rilegislature.gov/Statutes"
_HEAD_RE = re.compile(r"§\s*(?P<num>[0-9A-Za-z.-]+)\.\s*(?P<head>.+)")
_TERMINAL_TOKEN_PATTERN = (
    r"repealed|expired|reserved|renumbered|superseded|obsolete|"
    r"transferred|deleted|omitted|rejected"
)
_RESERVED = re.compile(
    rf"\[(?:{_TERMINAL_TOKEN_PATTERN})\.?\]"
    rf"|(?:{_TERMINAL_TOKEN_PATTERN})\.",
    re.IGNORECASE,
)
_HISTORY_PREFIX = "History of Section"
_WS = re.compile(r"\s+")
_STEM_RE = re.compile(
    r"/Statutes/TITLE(?P<title>[^/]+)/(?P<chapter>[^/]+)/"
    r"(?:(?P<part>[^/]+)/(?:(?P<subpart>[^/]+)/)?)?"
    r"(?P<section>[^/]+)\.htm$",
    re.IGNORECASE,
)
_TERMINAL_HEADING_RE = re.compile(
    rf"^(?:\[(?P<bracket>{_TERMINAL_TOKEN_PATTERN})\.?\]"
    rf"|(?P<plain>{_TERMINAL_TOKEN_PATTERN})\.)$",
    re.IGNORECASE,
)
_TERMINAL_RANGE_HEADING_RE = re.compile(
    r"^§{1,2}\s*(?P<start>[0-9A-Za-z.-]+)\s+[—–-]\s+"
    r"(?P<end>[0-9A-Za-z.-]+)\.\s*"
    rf"(?P<terminal>(?:\[(?:{_TERMINAL_TOKEN_PATTERN})\.?\]"
    rf"|(?:{_TERMINAL_TOKEN_PATTERN})\.))$",
    re.IGNORECASE,
)
_TERMINAL_LIST_HEADING_RE = re.compile(
    r"^§§\s*(?P<sections>[0-9A-Za-z.-]+\.?"
    r"(?:\s*,\s*[0-9A-Za-z.-]+\.?)+)\s*"
    rf"(?P<terminal>(?:\[(?:{_TERMINAL_TOKEN_PATTERN})\.?\]"
    rf"|(?:{_TERMINAL_TOKEN_PATTERN})\.))$",
    re.IGNORECASE,
)
_SECTION_TOKEN_RE = re.compile(
    r"^[0-9A-Za-z.]+(?:-[0-9A-Za-z.]+)+$",
    re.IGNORECASE,
)
_EFFECTIVE_DATE_RE = re.compile(
    r"(?P<month>January|February|March|April|May|June|July|August|"
    r"September|October|November|December)\s+(?P<day>[0-9]{1,2}),\s*"
    r"(?P<year>[0-9]{4})",
    re.IGNORECASE,
)

# The retained 2026-08-25 official chapter cohort contains two malformed
# section filenames whose independent index label and section-page identity
# agree on the logical cite.  No other prefix mismatch is admitted.
_SOURCE_BOUND_SECTION_LOCATOR_CORRECTIONS = {
    (
        "21",
        "21-28.12",
        "21-28-12-5.5",
        "§ 21-28-12-5.5. [Reserved.]",
    ): ("21-28.12-5.5", "21-28-12-5.5"),
    (
        "42",
        "42-164",
        "42-162-4",
        "§ 42-164-4. Certification cancellation.",
    ): ("42-164-4", "42-164-4"),
}

# These are official terminal chapter-range documents linked from the exact
# chapter indexes.  Their filenames are not section cites, so they are kept as
# source-bound closure evidence and never normalized as operative statutes.
_SOURCE_BOUND_CHAPTER_RANGE_MATERIALS = {
    (
        "6",
        "6-3",
        "3",
        "§ Chs. 3 - 8. SALE OF GOODS. REPEALED.",
    ): "repealed_chapter_range",
    (
        "6",
        "6-18",
        "18",
        "§ Chs. 18 - 25. [REPEALED AND TRANSFERRED]",
    ): "repealed_and_transferred_chapter_range",
}


def _clean(text: str) -> str:
    value = (
        (text or "")
        .replace("\xa0", " ")
        .replace("Â§", "§")
        .replace("ยง", "§")
        .replace("â€”", "—")
        .replace("â€“", "–")
    )
    return _WS.sub(" ", value).strip()


def repeated_section_locator_identity(locator: str) -> Optional[Tuple[str, int]]:
    """Resolve a normal or repeated temporal filename to one exact cite."""

    tokens = [token.strip() for token in str(locator or "").split("_")]
    if (
        not tokens
        or any(not _SECTION_TOKEN_RE.fullmatch(token) for token in tokens)
        or any(token.casefold() != tokens[0].casefold() for token in tokens[1:])
    ):
        return None
    return tokens[0], len(tokens)


def source_bound_section_locator_identity(
    *,
    title_number: str,
    chapter_number: str,
    locator: str,
    frontier_label: str,
) -> Optional[Tuple[str, int, str]]:
    """Resolve one retained index locator without accepting prefix drift.

    The third return value is the section number expected in the body heading;
    it differs from the logical cite only for one exact official typo.
    """

    title = str(title_number or "").strip()
    chapter = str(chapter_number or "").strip()
    label = _clean(frontier_label)
    chapter_material = _SOURCE_BOUND_CHAPTER_RANGE_MATERIALS.get(
        (title, chapter, str(locator or "").strip(), label)
    )
    if chapter_material is not None:
        return chapter, 1, str(locator or "").strip()
    repeated = repeated_section_locator_identity(locator)
    if repeated is None:
        return None
    physical, count = repeated
    if physical.casefold().startswith(f"{chapter.casefold()}-"):
        label_match = _SECTION_LINK_LABEL_RE.match(label)
        if (
            label_match is None
            or label_match.group("section").rstrip(".").casefold()
            != physical.casefold()
        ):
            return None
        return physical, count, physical

    correction = _SOURCE_BOUND_SECTION_LOCATOR_CORRECTIONS.get(
        (title, chapter, physical, label)
    )
    if correction is not None and count == 1:
        logical, body_heading = correction
        return logical, count, body_heading

    return None


def _source_url_identity(
    source_url: str,
) -> Optional[Tuple[str, str, str, str, str]]:
    parsed = urlparse(str(source_url or ""))
    match = _STEM_RE.fullmatch(parsed.path)
    if (
        parsed.scheme.lower() != "https"
        or parsed.netloc.lower() != "webserver.rilegislature.gov"
        or parsed.params
        or parsed.query
        or parsed.fragment
        or match is None
    ):
        return None
    return (
        match.group("title"),
        match.group("chapter"),
        str(match.group("part") or ""),
        str(match.group("subpart") or ""),
        match.group("section"),
    )


def _content_variants(body: Any) -> List[Dict[str, str]]:
    """Extract exact top-level official section content blocks in source order."""

    variants: List[Dict[str, str]] = []
    for content in body.find_all("div", recursive=False):
        heading = ""
        paragraphs: List[str] = []
        for paragraph in content.find_all("p", recursive=False):
            text = _clean(paragraph.get_text(" "))
            if not text:
                continue
            bold = paragraph.find("b")
            bold_text = _clean(bold.get_text(" ")) if bold is not None else ""
            if not heading and bold_text.startswith("§"):
                heading = bold_text
                remainder = text[len(bold_text) :].strip()
                if remainder:
                    paragraphs.append(remainder)
                continue
            paragraphs.append(text)
        if not heading:
            continue
        history_parts = [
            _clean(nested.get_text(" "))
            for nested in content.find_all("div", recursive=False)
            if _HISTORY_PREFIX in _clean(nested.get_text(" "))
            or "P.L." in _clean(nested.get_text(" "))
            or "G.L." in _clean(nested.get_text(" "))
        ]
        variants.append(
            {
                "heading": heading,
                "body": _clean(" ".join(paragraphs)),
                "history": _clean(" ".join(history_parts)),
            }
        )
    return variants


def _heading_interval(heading: str) -> Tuple[Optional[date], Optional[date], str]:
    normalized = _clean(heading)
    lowered = normalized.casefold()
    dated = list(_EFFECTIVE_DATE_RE.finditer(normalized))
    lower: Optional[date] = None
    upper: Optional[date] = None
    for match in dated:
        boundary = datetime.strptime(
            f"{match.group('month')} {match.group('day')} {match.group('year')}",
            "%B %d %Y",
        ).date()
        prefix = lowered[max(0, match.start() - 45) : match.start()]
        if "effective until" in prefix:
            upper = boundary
        elif "effective" in prefix and "repealed effective" not in prefix:
            lower = boundary
    if lower is not None or upper is not None:
        return lower, upper, "dated_interval"
    if "repealed effective" in lowered and dated:
        match = dated[-1]
        boundary = datetime.strptime(
            f"{match.group('month')} {match.group('day')} {match.group('year')}",
            "%B %d %Y",
        ).date()
        return None, boundary, "scheduled_repeal"
    if "effective until contingency" in lowered:
        return None, None, "until_contingency"
    if "effective when contingency" in lowered:
        return None, None, "after_contingency"
    if "contingent amendment; see other version" in lowered:
        return None, None, "until_contingency"
    if "contingent effective date; see note" in lowered:
        return None, None, "after_contingency"
    if "as amended by p.l." in lowered:
        return None, None, "parallel_compiler"
    return None, None, "unqualified"


def _exact_terminal_heading_disposition(
    heading: str,
    *,
    expected_section: str,
) -> Optional[str]:
    match = _HEAD_RE.fullmatch(_clean(heading))
    if match is None or match.group("num").casefold() != expected_section.casefold():
        return None
    terminal = _TERMINAL_HEADING_RE.fullmatch(match.group("head").strip())
    if terminal is None:
        return None
    return str(terminal.group("bracket") or terminal.group("plain") or "").lower()


def _frontier_binds_variant_headings(
    frontier_label: str,
    headings: Sequence[str],
) -> bool:
    """Require every official variant heading in the retained index order."""

    remaining = _clean(frontier_label)
    if not remaining or not headings:
        return False
    cursor = 0
    for heading in headings:
        fragment = _clean(heading).removeprefix("§").strip()
        offset = remaining.find(fragment, cursor)
        if offset < 0:
            return False
        cursor = offset + len(fragment)
    return True


def _latest_history_effective_date(history: str) -> Optional[date]:
    dates: List[date] = []
    lowered = _clean(history).casefold()
    for match in _EFFECTIVE_DATE_RE.finditer(_clean(history)):
        if "effective" not in lowered[max(0, match.start() - 30) : match.start()]:
            continue
        dates.append(
            datetime.strptime(
                f"{match.group('month')} {match.group('day')} {match.group('year')}",
                "%B %d %Y",
            ).date()
        )
    return max(dates) if dates else None


def _temporal_variant_resolution(
    variants: Sequence[Dict[str, str]],
    *,
    expected_section: str,
    as_of_date: date,
    frontier_label: str,
) -> Optional[Dict[str, Any]]:
    """Select or explicitly combine one exact official multi-version page."""

    headings = [row["heading"] for row in variants]
    if not _frontier_binds_variant_headings(frontier_label, headings):
        return None
    parsed: List[Dict[str, Any]] = []
    for index, row in enumerate(variants, start=1):
        match = _HEAD_RE.fullmatch(row["heading"])
        if match is None or match.group("num").casefold() != expected_section.casefold():
            return None
        lower, upper, kind = _heading_interval(row["heading"])
        terminal = _exact_terminal_heading_disposition(
            row["heading"],
            expected_section=expected_section,
        )
        parsed.append(
            {
                **row,
                "index": index,
                "name": match.group("head").strip(),
                "lower": lower,
                "upper": upper,
                "kind": kind,
                "terminal": terminal,
            }
        )

    disclosure = [
        {
            "variant_index": row["index"],
            "heading": row["heading"],
            "effective_from": row["lower"].isoformat() if row["lower"] else "",
            "effective_until": row["upper"].isoformat() if row["upper"] else "",
            "temporal_kind": row["kind"],
            "terminal_disposition": row["terminal"] or "",
            "full_text_chars": len(row["body"]),
            "full_text_sha256": sha256(row["body"].encode("utf-8")).hexdigest(),
            "history_sha256": sha256(row["history"].encode("utf-8")).hexdigest(),
        }
        for row in parsed
    ]

    dated = [
        row
        for row in parsed
        if row["kind"] == "dated_interval"
        and (row["lower"] is None or row["lower"] <= as_of_date)
        and (row["upper"] is None or as_of_date < row["upper"])
    ]
    if len(dated) == 1:
        selected = dated[0]
        selection = "source_observation_date"
    else:
        scheduled = [row for row in parsed if row["kind"] == "scheduled_repeal"]
        substantive = [row for row in scheduled if len(row["body"]) >= 40]
        empty = [row for row in scheduled if not row["body"]]
        boundaries = {row["upper"] for row in scheduled if row["upper"] is not None}
        if (
            len(scheduled) == len(parsed) == 2
            and len(substantive) == len(empty) == len(boundaries) == 1
        ):
            boundary = next(iter(boundaries))
            selected = substantive[0] if as_of_date < boundary else empty[0]
            selected = dict(selected)
            if not selected["body"]:
                selected["terminal"] = "repealed"
            selection = "source_observation_date_scheduled_repeal"
        elif {row["kind"] for row in parsed} == {
            "until_contingency",
            "after_contingency",
        } and len(parsed) == 2:
            selected = parsed[0]
            selection = "source_bound_official_pre_contingency_order"
        elif all(row["kind"] == "parallel_compiler" for row in parsed):
            bodies = [row for row in parsed if len(row["body"]) >= 40]
            if len(bodies) != len(parsed):
                return None
            selected = dict(bodies[0])
            selected["body"] = "\n\n".join(
                f"Official parallel variant {row['index']}: {row['heading']}\n"
                f"{row['body']}"
                for row in bodies
            )
            selection = "source_bound_parallel_compilation"
        elif all(row["kind"] == "unqualified" for row in parsed):
            terminals = [row for row in parsed if row["terminal"]]
            substantive = [row for row in parsed if len(row["body"]) >= 40]
            if len(parsed) == 2 and len(terminals) == len(substantive) == 1:
                selected = terminals[0]
                selection = "source_bound_current_terminal_variant"
            else:
                history_dates = [
                    _latest_history_effective_date(row["history"]) for row in parsed
                ]
                eligible = [
                    (row, observed)
                    for row, observed in zip(parsed, history_dates, strict=True)
                    if observed is not None and observed <= as_of_date
                ]
                latest = max((observed for _row, observed in eligible), default=None)
                winners = [row for row, observed in eligible if observed == latest]
                if latest is None or len(winners) != 1:
                    return None
                selected = winners[0]
                selection = "source_observation_date_latest_history"
        else:
            return None

    return {
        "selected": selected,
        "selection": selection,
        "disclosure": disclosure,
    }


def parse_rhode_island_section_html(
    html: str,
    *,
    source_url: str = "",
    code_name: str = "Rhode Island General Laws",
    as_of_date: Optional[date] = None,
    frontier_section_label: str = "",
    expected_section_number: str = "",
    strict_official_identity: bool = False,
) -> Optional[NormalizedStatute]:
    """Parse one official RI page, selecting repeated temporal variants.

    Unbounded production passes the retained index label, source observation
    date, and expected logical cite.  The legacy fallback remains only for
    bounded probes and fixture HTML that predates the official wrapper shape.
    """

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return None
    soup = BeautifulSoup(html or "", "html.parser")
    body = soup.find("body") or soup
    source_identity = _source_url_identity(source_url)
    variants = _content_variants(body)
    selected: Dict[str, Any]
    temporal_metadata: Dict[str, Any] = {}

    if source_identity is not None:
        title, chapter, _part, _subpart, locator = source_identity
        repeated = repeated_section_locator_identity(locator)
        if frontier_section_label:
            bound_identity = source_bound_section_locator_identity(
                title_number=title,
                chapter_number=chapter,
                locator=locator,
                frontier_label=frontier_section_label,
            )
        else:
            bound_identity = (
                (repeated[0], repeated[1], repeated[0])
                if repeated is not None
                and repeated[0].casefold().startswith(
                    f"{chapter.casefold()}-"
                )
                else None
            )
        if bound_identity is None:
            return None
        logical_section, locator_count, body_heading_section = bound_identity
        expected = str(expected_section_number or logical_section).strip()
        if expected.casefold() != logical_section.casefold():
            return None

        if locator_count > 1:
            if (
                as_of_date is None
                or len(variants) != locator_count
                or not frontier_section_label
            ):
                return None
            title_headings = [
                _clean(heading.get_text(" ")) for heading in body.find_all("h1")
            ]
            chapter_headings = [
                _clean(heading.get_text(" ")) for heading in body.find_all("h2")
            ]
            cite_headings = [
                _clean(heading.get_text(" "))
                for heading in body.find_all("h3")
                if _clean(heading.get_text(" ")).startswith("R.I. Gen. Laws §")
            ]
            local_chapter = chapter.split("-", 1)[1]
            if (
                sum(
                    bool(re.match(rf"^Title\s+{re.escape(title)}\b", value, re.I))
                    for value in title_headings
                )
                != 1
                or sum(
                    bool(
                        re.match(
                            rf"^Chapter\s+{re.escape(local_chapter)}\b",
                            value,
                            re.I,
                        )
                    )
                    for value in chapter_headings
                )
                != 1
                or cite_headings != [f"R.I. Gen. Laws § {logical_section}"]
            ):
                return None
            resolution = _temporal_variant_resolution(
                variants,
                expected_section=body_heading_section,
                as_of_date=as_of_date,
                frontier_label=frontier_section_label,
            )
            if resolution is None:
                return None
            selected = dict(resolution["selected"])
            if selected.get("terminal"):
                return None
            temporal_metadata = {
                "effective_variant_count": locator_count,
                "effective_variant_selection": resolution["selection"],
                "effective_variant_as_of_date": as_of_date.isoformat(),
                "effective_variants": resolution["disclosure"],
            }
        else:
            if strict_official_identity and len(variants) != 1:
                return None
            if variants:
                selected = dict(variants[0])
                match = _HEAD_RE.fullmatch(selected["heading"])
                if (
                    match is None
                    or match.group("num").casefold()
                    != body_heading_section.casefold()
                ):
                    return None
                selected["name"] = match.group("head").strip()
            else:
                selected = {}
        title_number = title
        chapter_number = chapter
        number = logical_section
    else:
        selected = {}
        title_number = ""
        chapter_number = ""
        number = ""

    if not selected:
        if strict_official_identity:
            return None
        top_divs = body.find_all("div", recursive=False)
        content = (
            top_divs[2]
            if len(top_divs) >= 3
            else (top_divs[-1] if top_divs else body)
        )
        heading = ""
        paragraphs: List[str] = []
        for paragraph in content.find_all("p", recursive=False):
            text = _clean(paragraph.get_text(" "))
            if not text:
                continue
            bold = paragraph.find("b")
            bold_text = _clean(bold.get_text(" ")) if bold is not None else ""
            if not heading and bold_text.startswith("§"):
                heading = bold_text
                continue
            if not text.startswith(_HISTORY_PREFIX):
                paragraphs.append(text)
        if not heading:
            for bold in body.find_all("b"):
                bold_text = _clean(bold.get_text(" "))
                if bold_text.startswith("§"):
                    heading = bold_text
                    break
        match = _HEAD_RE.search(heading)
        number = match.group("num") if match else number
        selected = {
            "heading": heading,
            "name": match.group("head").strip() if match else heading,
            "body": _clean(" ".join(paragraphs)),
        }
        if source_identity is not None:
            title_number = source_identity[0]
            chapter_number = source_identity[1]
        else:
            title_number = number.split("-", 1)[0] if number else ""
            chapter_number = "-".join(number.split("-")[:2]) if number else ""

    heading = _clean(str(selected.get("heading") or ""))
    body_text = _clean(str(selected.get("body") or ""))
    if len(body_text) < 40:
        return None
    if _RESERVED.search(heading) or _RESERVED.search(body_text[:160]):
        return None
    if not number:
        return None
    name = _clean(str(selected.get("name") or heading))
    return NormalizedStatute(
        state_code="RI",
        state_name="Rhode Island",
        statute_id=f"{code_name} § {number}",
        code_name=code_name,
        title_number=title_number or None,
        chapter_number=chapter_number or None,
        section_number=number,
        section_name=name[:200] or f"Section {number}",
        full_text=body_text,
        source_url=source_url or BASE,
        official_cite=f"R.I. Gen. Laws § {number}",
        metadata=StatuteMetadata(),
        structured_data={
            "source_kind": "official_rhode_island_section_html",
            "source_authority_class": "official",
            "discovery_method": "rilegislature_source_bound_content_block",
            "skip_hydrate": True,
            **temporal_metadata,
        },
    )


def source_bound_terminal_section_disposition(
    html: str,
    *,
    section_number: str,
    source_url: str,
    as_of_date: Optional[date] = None,
    frontier_section_label: str = "",
) -> Optional[str]:
    """Classify an exact official section heading as an inactive terminal."""

    expected_section = str(section_number or "").strip()
    source_identity = _source_url_identity(source_url)
    if source_identity is None or not expected_section:
        return None
    title, chapter, _part, _subpart, locator = source_identity
    label = _clean(frontier_section_label)
    chapter_material = _SOURCE_BOUND_CHAPTER_RANGE_MATERIALS.get(
        (title, chapter, locator, label)
    )
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return None
    soup = BeautifulSoup(html or "", "html.parser")
    body = soup.find("body") or soup

    if chapter_material is not None and expected_section.casefold() == chapter.casefold():
        observed = [_clean(bold.get_text(" ")) for bold in body.find_all("b")]
        expected_wrapper = {
            "repealed_chapter_range": (
                "Chapters 3 - 8 Sale of Goods. Repealed",
                "R.I. Gen. Laws Chs. 3-8",
                "§ Chs. 3 - 8. SALE OF GOODS. REPEALED.",
            ),
            "repealed_and_transferred_chapter_range": (
                "Chapters 18 TO 25 [Repealed And Transferred]",
                "R.I. Gen. Laws Chs. 18-25",
                "§ Chs. 18 - 25. [REPEALED AND TRANSFERRED]",
            ),
        }[chapter_material]
        h2 = [_clean(node.get_text(" ")) for node in body.find_all("h2")]
        h3 = [_clean(node.get_text(" ")) for node in body.find_all("h3")]
        if h2 == [expected_wrapper[0]] and h3 == [expected_wrapper[1]] and observed == [expected_wrapper[2]]:
            return chapter_material
        return None

    if label:
        bound_identity = source_bound_section_locator_identity(
            title_number=title,
            chapter_number=chapter,
            locator=locator,
            frontier_label=label,
        )
    else:
        repeated = repeated_section_locator_identity(locator)
        bound_identity = (
            (repeated[0], repeated[1], repeated[0])
            if repeated is not None
            and repeated[0].casefold() == expected_section.casefold()
            else None
        )
    if bound_identity is None or bound_identity[0].casefold() != expected_section.casefold():
        return None
    _logical, locator_count, body_heading_section = bound_identity

    if locator_count > 1:
        if as_of_date is None:
            return None
        variants = _content_variants(body)
        if len(variants) != locator_count:
            return None
        resolution = _temporal_variant_resolution(
            variants,
            expected_section=body_heading_section,
            as_of_date=as_of_date,
            frontier_label=label,
        )
        if resolution is None:
            return None
        selected = resolution["selected"]
        return str(selected.get("terminal") or "") or None

    for bold in body.find_all("b"):
        heading = _clean(bold.get_text(" "))
        range_match = _TERMINAL_RANGE_HEADING_RE.fullmatch(heading)
        if range_match is not None:
            start = range_match.group("start").strip().rstrip(".")
            end = range_match.group("end").strip().rstrip(".")
            chapter_prefix = expected_section.rsplit("-", 1)[0] + "-"
            if (
                start.casefold() != body_heading_section.casefold()
                or not end.casefold().startswith(chapter_prefix.casefold())
            ):
                return None
            terminal = range_match.group("terminal").strip("[].").lower()
            return f"{terminal}_range"
        list_match = _TERMINAL_LIST_HEADING_RE.fullmatch(heading)
        if list_match is not None:
            sections = [
                token.strip().rstrip(".")
                for token in list_match.group("sections").split(",")
            ]
            chapter_prefix = expected_section.rsplit("-", 1)[0] + "-"
            if (
                len(sections) < 2
                or sections[0].casefold() != body_heading_section.casefold()
                or any(
                    not token.casefold().startswith(chapter_prefix.casefold())
                    for token in sections[1:]
                )
            ):
                return None
            terminal = list_match.group("terminal").strip("[].").lower()
            return f"{terminal}_list"
        match = _HEAD_RE.fullmatch(heading)
        if (
            not match
            or match.group("num").casefold() != body_heading_section.casefold()
        ):
            continue
        terminal_match = _TERMINAL_HEADING_RE.fullmatch(
            match.group("head").strip()
        )
        if terminal_match is None:
            return None
        return str(
            terminal_match.group("bracket")
            or terminal_match.group("plain")
            or ""
        ).lower()
    return None


def configured_section_html_path() -> Optional[Path]:
    raw = str(os.environ.get("RHODE_ISLAND_SECTION_HTML") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None


def configured_toc_html_path() -> Optional[Path]:
    raw = str(os.environ.get("RHODE_ISLAND_TOC_HTML") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None


def parse_configured_toc_html() -> List[Tuple[str, str]]:
    path = configured_toc_html_path()
    if path is None:
        return []
    return toc_title_links(path.read_text(encoding="utf-8", errors="replace"))


_TOC_TITLE_RE = re.compile(r"^TITLE([\w.\-]+)/INDEX\.HTM$", re.IGNORECASE)
_TITLE_CHAPTER_RE = re.compile(r"^([\w.\-]+)/INDEX\.HTM$", re.IGNORECASE)
_CHAPTER_SECTION_RE = re.compile(r"^([\w.\-]+)\.htm$", re.IGNORECASE)
_TITLE_TOKEN_RE = re.compile(r"^[0-9]+(?:A|\.[0-9]+)?$", re.IGNORECASE)
_CHAPTER_TOKEN_RE = re.compile(
    r"^[0-9A-Za-z.]+(?:-[0-9A-Za-z.]+)+$",
    re.IGNORECASE,
)
_CHAPTER_INDEX_PATH_RE = re.compile(
    r"^/Statutes/TITLE(?P<title>[0-9]+(?:A|\.[0-9]+)?)/"
    r"(?P<chapter>[0-9A-Za-z.]+(?:-[0-9A-Za-z.]+)+)/INDEX\.htm$",
    re.IGNORECASE,
)
_PART_INDEX_PATH_RE = re.compile(
    r"^/Statutes/TITLE(?P<title>[0-9]+(?:A|\.[0-9]+)?)/"
    r"(?P<chapter>[0-9A-Za-z.]+(?:-[0-9A-Za-z.]+)+)/"
    r"(?P<part>[0-9A-Za-z.]+(?:-[0-9A-Za-z.]+)+)/INDEX\.htm$",
    re.IGNORECASE,
)
_SUBPART_INDEX_PATH_RE = re.compile(
    r"^/Statutes/TITLE(?P<title>[0-9]+(?:A|\.[0-9]+)?)/"
    r"(?P<chapter>[0-9A-Za-z.]+(?:-[0-9A-Za-z.]+)+)/"
    r"(?P<part>[0-9A-Za-z.]+(?:-[0-9A-Za-z.]+)+)/"
    r"(?P<subpart>[0-9A-Za-z.]+(?:-[0-9A-Za-z.]+)+)/INDEX\.htm$",
    re.IGNORECASE,
)
_PART_SECTION_PATH_RE = re.compile(
    r"^/Statutes/TITLE(?P<title>[0-9]+(?:A|\.[0-9]+)?)/"
    r"(?P<chapter>[0-9A-Za-z.]+(?:-[0-9A-Za-z.]+)+)/"
    r"(?P<part>[0-9A-Za-z.]+(?:-[0-9A-Za-z.]+)+)/"
    r"(?P<section>[0-9A-Za-z._-]+)\.htm$",
    re.IGNORECASE,
)
_SUBPART_SECTION_PATH_RE = re.compile(
    r"^/Statutes/TITLE(?P<title>[0-9]+(?:A|\.[0-9]+)?)/"
    r"(?P<chapter>[0-9A-Za-z.]+(?:-[0-9A-Za-z.]+)+)/"
    r"(?P<part>[0-9A-Za-z.]+(?:-[0-9A-Za-z.]+)+)/"
    r"(?P<subpart>[0-9A-Za-z.]+(?:-[0-9A-Za-z.]+)+)/"
    r"(?P<section>[0-9A-Za-z._-]+)\.htm$",
    re.IGNORECASE,
)
_CHAPTER_INDEX_HEADING_RE = re.compile(
    r"^Chapter\s+(?P<chapter>[0-9A-Za-z.]+)(?:\s+.+)?$",
    re.IGNORECASE,
)
_PART_INDEX_HEADING_RE = re.compile(
    r"^(?P<kind>Part|Article)\s+"
    r"(?P<part>[0-9]+|[IVXLCDM]+)(?:\s+.+)?$",
    re.IGNORECASE,
)
_PART_LINK_LABEL_RE = re.compile(
    r"^(?P<kind>Part|Article)\s+"
    r"(?P<part>[0-9]+|[IVXLCDM]+)(?:\s+.+)?$",
    re.IGNORECASE,
)
_SUBPART_INDEX_HEADING_RE = re.compile(
    r"^Subpart\s+(?P<subpart>[0-9A-Za-z.]+)(?:\s+.+)?$",
    re.IGNORECASE,
)
_SUBPART_LINK_LABEL_RE = re.compile(
    r"^Subpart\s+(?P<subpart>[0-9A-Za-z.]+)(?:\s+.+)?$",
    re.IGNORECASE,
)
_SECTION_LINK_LABEL_RE = re.compile(
    r"^\s*§{1,2}\s*(?P<section>[0-9A-Za-z.-]+)",
    re.IGNORECASE,
)

# The retained 2026-08-25 official frontier contains exactly these exceptional
# intermediate indexes whose next authoritative level is one more bounded
# directory.  Most are ``Part -> Subpart``; Title 7, Chapter 12.1 uses the
# equivalent ``Article -> Part`` shape.  The byte digests make this exceptional
# extra hierarchy fail closed if the source changes; DOM, locator, and label
# identity are still independently checked.
_SOURCE_BOUND_SUBPART_INDEX_DIGESTS = {
    ("6A", "6A-2.1", "6A-5"): (
        "e0dee32512d9742297f183ea962154eae0a6a20d027bf4114714fefc45dfe80b"
    ),
    ("6A", "6A-9", "6A-1"): (
        "af134e6ee571dee204261b31a4e95ce9079672f1b45e92858a390111fdfffd27"
    ),
    ("6A", "6A-9", "6A-2"): (
        "d08c519d6837bfcd4d93a2d0f9f80e14f264679e2b0cf935076e7e13bd66b1ee"
    ),
    ("6A", "6A-9", "6A-3"): (
        "0c3efa1c000abb4bf1b219f4112a1b71996ada0fc3c66c8651a5f251c222f816"
    ),
    ("6A", "6A-9", "6A-5"): (
        "efc53b80c455acc78d15070500386c85dd6baf1a7f65c1381cc427a3a06597b4"
    ),
    ("6A", "6A-9", "6A-6"): (
        "bfb14301efb04ba6b119a806214024a748d42672638a142dc112f26780a9a8eb"
    ),
    ("7", "7-13.1", "7-11"): (
        "a09b00a6e17ccd58bde9edf7c5d5eae33415763fe4a169ded609b2fdc99b2525"
    ),
    ("7", "7-12.1", "7-11"): (
        "5a6d02fe5011707edf6cfeb59305114f25e72c1e05c199b697ba81467db7e359"
    ),
    ("15", "15-23.1", "15-6"): (
        "9446cef94458118d5701254227571dc6b383abd87e025c9fe9b698c69af14f8e"
    ),
}

# Only these retained identities label the two bounded directory levels as an
# article followed by parts.  Every other admitted digest above retains the
# default part/subpart vocabulary.
_SOURCE_BOUND_NESTED_PART_INDEX_IDENTITIES = frozenset(
    {
        ("7", "7-12.1", "7-11"),
        ("15", "15-23.1", "15-6"),
    }
)


def _same_origin_child_href(href: str, *, parent_url: str) -> str:
    """Return a child-relative locator for relative or official root paths."""

    absolute = urljoin(parent_url, href)
    parsed_parent = urlparse(parent_url)
    parsed_child = urlparse(absolute)
    if (
        parsed_child.scheme.lower() not in {"http", "https"}
        or parsed_child.hostname != parsed_parent.hostname
        or parsed_child.params
        or parsed_child.query
        or parsed_child.fragment
    ):
        return ""
    parent_prefix = parsed_parent.path.rsplit("/", 1)[0].rstrip("/") + "/"
    if not parsed_child.path.casefold().startswith(parent_prefix.casefold()):
        return ""
    return parsed_child.path[len(parent_prefix) :]


def _official_source_identity(
    url: str,
    *,
    path_pattern: re.Pattern[str],
) -> Optional[re.Match[str]]:
    """Match a canonical HTTPS RI statutory locator on the exact official host."""

    parsed = urlparse(str(url or ""))
    if (
        parsed.scheme.lower() != "https"
        or parsed.netloc.lower() != "webserver.rilegislature.gov"
        or parsed.params
        or parsed.query
        or parsed.fragment
    ):
        return None
    return path_pattern.fullmatch(parsed.path)


def source_bound_empty_chapter_disposition(
    html: str,
    *,
    chapter_url: str,
    title_number: str,
    chapter_number: str,
) -> Optional[str]:
    """Classify an exact anchor-free official reserved chapter wrapper."""

    source_match = _official_source_identity(
        chapter_url,
        path_pattern=_CHAPTER_INDEX_PATH_RE,
    )
    expected_title = str(title_number or "").strip()
    expected_chapter = str(chapter_number or "").strip()
    if (
        source_match is None
        or source_match.group("title").casefold() != expected_title.casefold()
        or source_match.group("chapter").casefold()
        != expected_chapter.casefold()
        or not expected_chapter.casefold().startswith(
            f"{expected_title.casefold()}-"
        )
    ):
        return None
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return None
    soup = BeautifulSoup(html or "", "html.parser")
    body = soup.find("body")
    if body is None or body.find("a", href=True) is not None:
        return None
    h2 = [_clean(node.get_text(" ")) for node in body.find_all("h2")]
    h3 = [_clean(node.get_text(" ")) for node in body.find_all("h3")]
    if len(h2) != 1 or h3 != ["Index of"]:
        return None
    local_chapter = expected_chapter.split("-", 1)[1]
    single = re.fullmatch(
        r"Chapter\s+(?P<start>[0-9A-Za-z.]+)\s+\[Reserved\.?\]",
        h2[0],
        flags=re.IGNORECASE,
    )
    range_match = re.fullmatch(
        r"Chapters\s+(?P<start>[0-9A-Za-z.]+)\s+[\u2014–-]\s+"
        r"(?P<end>[0-9A-Za-z.]+)\s+\[Reserved\.?\]",
        h2[0],
        flags=re.IGNORECASE,
    )
    if single is not None and single.group("start").casefold() == local_chapter.casefold():
        disposition = "reserved"
    elif (
        range_match is not None
        and range_match.group("start").casefold() == local_chapter.casefold()
        and range_match.group("end").casefold() != local_chapter.casefold()
    ):
        disposition = "reserved_chapter_range"
    else:
        return None
    if _clean(body.get_text(" ")) != f"{h2[0]} Index of":
        return None
    return disposition


def chapter_part_links(
    html: str,
    *,
    chapter_url: str,
    title_number: str,
    chapter_number: str,
) -> List[Tuple[str, str]]:
    """Return a source-bound official ``Index of Parts`` frontier.

    Rhode Island nests part and article indexes below selected chapter indexes.
    This recognizer intentionally returns no rows unless the requested chapter
    identity, the official DOM headings, every part label, and every nested
    locator agree exactly.
    """

    expected_title = str(title_number or "").strip()
    expected_chapter = str(chapter_number or "").strip()
    source_match = _official_source_identity(
        chapter_url,
        path_pattern=_CHAPTER_INDEX_PATH_RE,
    )
    if (
        source_match is None
        or not _TITLE_TOKEN_RE.fullmatch(expected_title)
        or not _CHAPTER_TOKEN_RE.fullmatch(expected_chapter)
        or source_match.group("title").casefold() != expected_title.casefold()
        or source_match.group("chapter").casefold()
        != expected_chapter.casefold()
        or not expected_chapter.casefold().startswith(
            f"{expected_title.casefold()}-"
        )
    ):
        return []
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []

    soup = BeautifulSoup(html or "", "html.parser")
    body = soup.find("body")
    if body is None:
        return []
    chapter_headings = [
        _CHAPTER_INDEX_HEADING_RE.fullmatch(_clean(heading.get_text(" ")))
        for heading in body.find_all("h2")
    ]
    chapter_headings = [match for match in chapter_headings if match is not None]
    local_chapter = expected_chapter.split("-", 1)[1]
    if (
        len(chapter_headings) != 1
        or chapter_headings[0].group("chapter").casefold()
        != local_chapter.casefold()
    ):
        return []

    intermediate_indexes = [
        _clean(heading.get_text(" ")).casefold()
        for heading in body.find_all("h3")
        if _clean(heading.get_text(" ")).casefold()
        in {"index of parts", "index of articles"}
    ]
    if len(intermediate_indexes) != 1:
        return []
    expected_kind = (
        "part" if intermediate_indexes[0] == "index of parts" else "article"
    )

    anchors = body.find_all("a", href=True)
    if not anchors:
        return []
    out: List[Tuple[str, str]] = []
    seen_urls: set[str] = set()
    seen_parts: set[str] = set()
    for anchor in anchors:
        href = str(anchor.get("href") or "").strip()
        label = _clean(anchor.get_text(" "))
        label_match = _PART_LINK_LABEL_RE.fullmatch(label)
        absolute = urljoin(chapter_url, href)
        part_match = _official_source_identity(
            absolute,
            path_pattern=_PART_INDEX_PATH_RE,
        )
        if part_match is None or label_match is None:
            return []
        observed_title = part_match.group("title")
        observed_chapter = part_match.group("chapter")
        observed_part = part_match.group("part")
        part_prefix = f"{expected_title}-"
        if (
            observed_title.casefold() != expected_title.casefold()
            or observed_chapter.casefold() != expected_chapter.casefold()
            or not observed_part.casefold().startswith(part_prefix.casefold())
            or observed_part[len(part_prefix) :].casefold()
            != label_match.group("part").casefold()
            or label_match.group("kind").casefold() != expected_kind
        ):
            return []
        canonical_url = (
            f"https://webserver.rilegislature.gov/Statutes/TITLE{expected_title}/"
            f"{expected_chapter}/{observed_part}/INDEX.htm"
        )
        part_key = observed_part.casefold()
        if canonical_url in seen_urls or part_key in seen_parts:
            return []
        seen_urls.add(canonical_url)
        seen_parts.add(part_key)
        out.append((canonical_url, label))
    return out


def part_subpart_links(
    html: str,
    *,
    part_url: str,
    title_number: str,
    chapter_number: str,
    part_number: str,
    intermediate_label: str,
) -> List[Tuple[str, str]]:
    """Return an exact retained one-level nested-index frontier.

    Rhode Island uses this additional level in retained intermediate indexes.
    Admission is bound to the official source identity, the retained byte
    digest, the intermediate heading and parent label, and every nested child
    locator.  One exact Article-to-Part source identity uses the same bounded
    path depth as the otherwise Part-to-Subpart frontier.
    """

    expected_title = str(title_number or "").strip()
    expected_chapter = str(chapter_number or "").strip()
    expected_part = str(part_number or "").strip()
    source_match = _official_source_identity(
        part_url,
        path_pattern=_PART_INDEX_PATH_RE,
    )
    expected_digest = _SOURCE_BOUND_SUBPART_INDEX_DIGESTS.get(
        (expected_title, expected_chapter, expected_part)
    )
    nested_part_index = (
        expected_title,
        expected_chapter,
        expected_part,
    ) in _SOURCE_BOUND_NESTED_PART_INDEX_IDENTITIES
    observed_digest = sha256((html or "").encode("utf-8")).hexdigest()
    expected_label = _PART_LINK_LABEL_RE.fullmatch(_clean(intermediate_label))
    if (
        source_match is None
        or expected_digest is None
        or observed_digest != expected_digest
        or expected_label is None
        or source_match.group("title").casefold() != expected_title.casefold()
        or source_match.group("chapter").casefold()
        != expected_chapter.casefold()
        or source_match.group("part").casefold() != expected_part.casefold()
        or expected_label.group("kind").casefold()
        != ("article" if nested_part_index else "part")
    ):
        return []
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []

    soup = BeautifulSoup(html or "", "html.parser")
    body = soup.find("body")
    if body is None:
        return []
    h3 = [_clean(node.get_text(" ")) for node in body.find_all("h3")]
    part_headings = [
        match
        for heading in h3
        if (match := _PART_INDEX_HEADING_RE.fullmatch(heading)) is not None
    ]
    local_part = expected_part.split("-", 1)[1]
    if (
        len(h3) != 2
        or len(part_headings) != 1
        or h3.count(
            "Index of Parts" if nested_part_index else "Index of Subparts"
        )
        != 1
        or part_headings[0].group("kind").casefold()
        != expected_label.group("kind").casefold()
        or part_headings[0].group("part").casefold()
        != expected_label.group("part").casefold()
        or part_headings[0].group("part").casefold() != local_part.casefold()
    ):
        return []

    anchors = body.find_all("a", href=True)
    if not anchors:
        return []
    child_label_group = "part" if nested_part_index else "subpart"
    out: List[Tuple[str, str]] = []
    seen_urls: set[str] = set()
    seen_subparts: set[str] = set()
    for anchor in anchors:
        href = str(anchor.get("href") or "").strip()
        label = _clean(anchor.get_text(" "))
        label_match = (
            _PART_LINK_LABEL_RE if nested_part_index else _SUBPART_LINK_LABEL_RE
        ).fullmatch(label)
        absolute = urljoin(part_url, href)
        subpart_match = _official_source_identity(
            absolute,
            path_pattern=_SUBPART_INDEX_PATH_RE,
        )
        if subpart_match is None or label_match is None:
            return []
        observed_title = subpart_match.group("title")
        observed_chapter = subpart_match.group("chapter")
        observed_part = subpart_match.group("part")
        observed_subpart = subpart_match.group("subpart")
        subpart_prefix = f"{expected_title}-"
        if (
            observed_title.casefold() != expected_title.casefold()
            or observed_chapter.casefold() != expected_chapter.casefold()
            or observed_part.casefold() != expected_part.casefold()
            or (
                nested_part_index
                and label_match.group("kind").casefold() != "part"
            )
            or not observed_subpart.casefold().startswith(
                subpart_prefix.casefold()
            )
            or observed_subpart[len(subpart_prefix) :].casefold()
            != label_match.group(child_label_group).casefold()
        ):
            return []
        canonical_url = (
            "https://webserver.rilegislature.gov/Statutes/"
            f"TITLE{expected_title}/{expected_chapter}/{expected_part}/"
            f"{observed_subpart}/INDEX.htm"
        )
        subpart_key = observed_subpart.casefold()
        if canonical_url in seen_urls or subpart_key in seen_subparts:
            return []
        seen_urls.add(canonical_url)
        seen_subparts.add(subpart_key)
        out.append((canonical_url, label))
    return out


def subpart_section_links(
    html: str,
    *,
    subpart_url: str,
    title_number: str,
    chapter_number: str,
    part_number: str,
    subpart_number: str,
    intermediate_label: str,
) -> List[Tuple[str, str]]:
    """Return exact sections from one source-bound nested index."""

    expected_title = str(title_number or "").strip()
    expected_chapter = str(chapter_number or "").strip()
    expected_part = str(part_number or "").strip()
    expected_subpart = str(subpart_number or "").strip()
    nested_part_index = (
        expected_title,
        expected_chapter,
        expected_part,
    ) in _SOURCE_BOUND_NESTED_PART_INDEX_IDENTITIES
    source_match = _official_source_identity(
        subpart_url,
        path_pattern=_SUBPART_INDEX_PATH_RE,
    )
    expected_label = (
        _PART_LINK_LABEL_RE if nested_part_index else _SUBPART_LINK_LABEL_RE
    ).fullmatch(_clean(intermediate_label))
    if (
        source_match is None
        or expected_label is None
        or source_match.group("title").casefold() != expected_title.casefold()
        or source_match.group("chapter").casefold()
        != expected_chapter.casefold()
        or source_match.group("part").casefold() != expected_part.casefold()
        or source_match.group("subpart").casefold()
        != expected_subpart.casefold()
        or not expected_part.casefold().startswith(
            f"{expected_title.casefold()}-"
        )
        or not expected_subpart.casefold().startswith(
            f"{expected_title.casefold()}-"
        )
        or (
            nested_part_index
            and expected_label.group("kind").casefold() != "part"
        )
    ):
        return []
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []

    soup = BeautifulSoup(html or "", "html.parser")
    body = soup.find("body")
    if body is None:
        return []
    h4 = [_clean(node.get_text(" ")) for node in body.find_all("h4")]
    nested_heading_re = (
        _PART_INDEX_HEADING_RE
        if nested_part_index
        else _SUBPART_INDEX_HEADING_RE
    )
    subpart_headings = [
        match
        for heading in h4
        if (match := nested_heading_re.fullmatch(heading)) is not None
    ]
    h3 = [_clean(node.get_text(" ")) for node in body.find_all("h3")]
    local_subpart = expected_subpart.split("-", 1)[1]
    child_label_group = "part" if nested_part_index else "subpart"
    if (
        len(h4) != 1
        or len(subpart_headings) != 1
        or (
            nested_part_index
            and subpart_headings[0].group("kind").casefold() != "part"
        )
        or subpart_headings[0].group(child_label_group).casefold()
        != expected_label.group(child_label_group).casefold()
        or subpart_headings[0].group(child_label_group).casefold()
        != local_subpart.casefold()
        or h3 != ["Index of Sections"]
    ):
        return []

    anchors = body.find_all("a", href=True)
    if not anchors:
        return []
    out: List[Tuple[str, str]] = []
    seen_urls: set[str] = set()
    seen_sections: set[str] = set()
    for anchor in anchors:
        href = str(anchor.get("href") or "").strip()
        label = _clean(anchor.get_text(" "))
        label_match = _SECTION_LINK_LABEL_RE.match(label)
        absolute = urljoin(subpart_url, href)
        section_match = _official_source_identity(
            absolute,
            path_pattern=_SUBPART_SECTION_PATH_RE,
        )
        if section_match is None or label_match is None:
            return []
        observed_locator = section_match.group("section")
        locator_identity = source_bound_section_locator_identity(
            title_number=expected_title,
            chapter_number=expected_chapter,
            locator=observed_locator,
            frontier_label=label,
        )
        observed_section = locator_identity[0] if locator_identity else ""
        if (
            section_match.group("title").casefold()
            != expected_title.casefold()
            or section_match.group("chapter").casefold()
            != expected_chapter.casefold()
            or section_match.group("part").casefold()
            != expected_part.casefold()
            or section_match.group("subpart").casefold()
            != expected_subpart.casefold()
            or locator_identity is None
            or label_match.group("section").rstrip(".").casefold()
            != observed_section.casefold()
        ):
            return []
        canonical_url = (
            "https://webserver.rilegislature.gov/Statutes/"
            f"TITLE{expected_title}/{expected_chapter}/{expected_part}/"
            f"{expected_subpart}/{observed_locator}.htm"
        )
        section_key = observed_section.casefold()
        if canonical_url in seen_urls or section_key in seen_sections:
            return []
        seen_urls.add(canonical_url)
        seen_sections.add(section_key)
        out.append((canonical_url, label))
    return out


def part_section_links(
    html: str,
    *,
    part_url: str,
    title_number: str,
    chapter_number: str,
    part_number: str,
    intermediate_label: str = "",
) -> List[Tuple[str, str]]:
    """Return exact sections from a source-bound part or article index."""

    expected_title = str(title_number or "").strip()
    expected_chapter = str(chapter_number or "").strip()
    expected_part = str(part_number or "").strip()
    source_match = _official_source_identity(
        part_url,
        path_pattern=_PART_INDEX_PATH_RE,
    )
    if (
        source_match is None
        or source_match.group("title").casefold() != expected_title.casefold()
        or source_match.group("chapter").casefold()
        != expected_chapter.casefold()
        or source_match.group("part").casefold() != expected_part.casefold()
        or not expected_chapter.casefold().startswith(
            f"{expected_title.casefold()}-"
        )
        or not expected_part.casefold().startswith(
            f"{expected_title.casefold()}-"
        )
    ):
        return []
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []

    soup = BeautifulSoup(html or "", "html.parser")
    body = soup.find("body")
    if body is None:
        return []
    headings = [_clean(heading.get_text(" ")) for heading in body.find_all("h3")]
    part_headings = [
        match
        for heading in headings
        if (match := _PART_INDEX_HEADING_RE.fullmatch(heading)) is not None
    ]
    local_part = expected_part.split("-", 1)[1]
    expected_label_match = (
        _PART_LINK_LABEL_RE.fullmatch(_clean(intermediate_label))
        if intermediate_label
        else None
    )
    if (
        len(part_headings) != 1
        or part_headings[0].group("part").casefold() != local_part.casefold()
        or (
            expected_label_match is not None
            and (
                part_headings[0].group("kind").casefold()
                != expected_label_match.group("kind").casefold()
                or part_headings[0].group("part").casefold()
                != expected_label_match.group("part").casefold()
            )
        )
        or sum(heading.casefold() == "index of sections" for heading in headings)
        != 1
    ):
        return []

    anchors = body.find_all("a", href=True)
    if not anchors:
        return []
    out: List[Tuple[str, str]] = []
    seen_urls: set[str] = set()
    seen_sections: set[str] = set()
    for anchor in anchors:
        href = str(anchor.get("href") or "").strip()
        label = _clean(anchor.get_text(" "))
        label_match = _SECTION_LINK_LABEL_RE.match(label)
        absolute = urljoin(part_url, href)
        section_match = _official_source_identity(
            absolute,
            path_pattern=_PART_SECTION_PATH_RE,
        )
        if section_match is None or label_match is None:
            return []
        observed_title = section_match.group("title")
        observed_chapter = section_match.group("chapter")
        observed_part = section_match.group("part")
        observed_locator = section_match.group("section")
        locator_identity = source_bound_section_locator_identity(
            title_number=expected_title,
            chapter_number=expected_chapter,
            locator=observed_locator,
            frontier_label=label,
        )
        observed_section = locator_identity[0] if locator_identity else ""
        if (
            observed_title.casefold() != expected_title.casefold()
            or observed_chapter.casefold() != expected_chapter.casefold()
            or observed_part.casefold() != expected_part.casefold()
            or locator_identity is None
            or label_match.group("section").rstrip(".").casefold()
            != observed_section.casefold()
        ):
            return []
        canonical_url = (
            f"https://webserver.rilegislature.gov/Statutes/TITLE{expected_title}/"
            f"{expected_chapter}/{expected_part}/{observed_locator}.htm"
        )
        section_key = observed_section.casefold()
        if canonical_url in seen_urls or section_key in seen_sections:
            return []
        seen_urls.add(canonical_url)
        seen_sections.add(section_key)
        out.append((canonical_url, label))
    return out


def toc_title_links(html: str, *, base_url: str = BASE) -> List[Tuple[str, str]]:
    """Master TOC ``TITLE{N}/INDEX.HTM`` links, including TITLE6A."""

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    from urllib.parse import urljoin

    soup = BeautifulSoup(html or "", "html.parser")
    out: List[Tuple[str, str]] = []
    seen = set()
    for anchor in soup.find_all("a", href=True):
        href = str(anchor.get("href") or "").strip()
        match = _TOC_TITLE_RE.match(href)
        if not match:
            continue
        number = match.group(1)
        if number.isdigit():
            number = str(int(number))
        url = urljoin(base_url.rstrip("/") + "/", href)
        if url in seen:
            continue
        seen.add(url)
        out.append((url, number))
    return out


def title_chapter_links(html: str, *, title_url: str) -> List[Tuple[str, str]]:
    """Chapter index links ``{N}-{M}/INDEX.htm`` from a title page."""

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    soup = BeautifulSoup(html or "", "html.parser")
    out: List[Tuple[str, str]] = []
    seen = set()
    for anchor in soup.find_all("a", href=True):
        href = str(anchor.get("href") or "").strip()
        match = _TITLE_CHAPTER_RE.match(
            _same_origin_child_href(href, parent_url=title_url)
        )
        if not match:
            continue
        number = match.group(1)
        url = urljoin(title_url, href)
        if url in seen:
            continue
        seen.add(url)
        out.append((url, number))
    return out


def chapter_section_links(html: str, *, chapter_url: str) -> List[Tuple[str, str]]:
    """Return source-bound section, temporal, and terminal-material locators."""

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    soup = BeautifulSoup(html or "", "html.parser")
    source_match = _official_source_identity(
        chapter_url,
        path_pattern=_CHAPTER_INDEX_PATH_RE,
    )
    if source_match is None:
        return []
    title_number = source_match.group("title")
    chapter_number = source_match.group("chapter")
    out: List[Tuple[str, str]] = []
    seen = set()
    for anchor in soup.find_all("a", href=True):
        href = str(anchor.get("href") or "").strip()
        match = _CHAPTER_SECTION_RE.match(
            _same_origin_child_href(href, parent_url=chapter_url)
        )
        if not match or href.upper() == "INDEX.HTM":
            continue
        relative = _same_origin_child_href(href, parent_url=chapter_url)
        locator = re.sub(r"\.htm$", "", relative, flags=re.IGNORECASE)
        name = _clean(anchor.get_text(" "))
        if source_bound_section_locator_identity(
            title_number=title_number,
            chapter_number=chapter_number,
            locator=locator,
            frontier_label=name,
        ) is None:
            continue
        url = urljoin(chapter_url, href)
        if url in seen:
            continue
        seen.add(url)
        out.append((url, name or locator))
    return out
