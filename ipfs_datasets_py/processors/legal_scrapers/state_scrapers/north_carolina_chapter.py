"""Official North Carolina ByChapter HTML parser.

Vaquill withdrew NC because nav/footer leaked into section bodies. This parser
keeps only statutory blocks from
``/EnactedLegislation/Statutes/HTML/ByChapter/Chapter_{N}.html``.
"""

from __future__ import annotations

import hashlib
import os
import re
from datetime import date, datetime
from pathlib import Path
from typing import List, Literal, Mapping, Optional, Sequence, Tuple, TypedDict
from urllib.parse import urljoin

from .base_scraper import NormalizedStatute, StatuteMetadata

NAV_MARKERS = (
    "skip to main",
    "skip to content",
    "skip to navigation",
    "privacy policy",
    "site map",
    "sitemap",
    "copyright ©",
    "footer navigation",
    "cookie policy",
    "terms of use",
)
_SECTION_RE = re.compile(
    r"(?m)^(?:§|&sect;|&#167;)\s*"
    r"(?P<num>[0-9]+[A-Za-z]?\s*[-‑.]\s*[0-9A-Za-z.\-]+?)"
    r"(?:[.:]\s+|\s+)(?P<head>[^\n]+)",
)
_WORD_HEAD_RE = re.compile(
    r"(?m)^(?P<num>\d+[A-Za-z]?-\d+[A-Za-z0-9.]*)[.:]\s+(?P<head>.+)$"
)
_INACTIVE = re.compile(
    r"\b(abolished|deleted|expired|omitted|recodified|recodifed|renumbered|"
    r"repealed|reserved|rewritten|superseded|transferred|unconstitutional|"
    r"redesignated|not\s+in\s+effect|not\s+effectuated)\b",
    re.IGNORECASE,
)
_WS = re.compile(r"\s+")
_EFFECTIVE_DATE_RE = re.compile(
    r"\b(?P<month>January|February|March|April|May|June|July|August|"
    r"September|October|November|December)\s+(?P<day>\d{1,2}),\s*"
    r"(?P<year>\d{4})\b",
    re.IGNORECASE,
)
_EXACT_HEADING_ONLY_SECTION_TERMINALS = {
    ("130A", "130A-295.1"): {
        "content_sha256": (
            "4b0497f8a514759e31af675facad821268d82a90db7d4e71fc1333b89a5804c6"
        ),
        "heading": (
            "§ 130A-295.1. (See Editor's note) Limitations on permits for "
            "sanitary landfills."
        ),
        "disposition": "editor_note_only",
    },
}


BYCHAPTER_INDEX_URL = (
    "https://www.ncleg.gov/EnactedLegislation/Statutes/HTML/ByChapter/"
)
TOC_URL = "https://www.ncleg.gov/Laws/GeneralStatutesTOC"


def chapter_url(chapter: str) -> str:
    return (
        "https://www.ncleg.gov/EnactedLegislation/Statutes/HTML/ByChapter/"
        f"Chapter_{chapter}.html"
    )


def chapter_sections_url(chapter: str) -> str:
    return f"https://www.ncleg.gov/Laws/GeneralStatuteSections/Chapter{chapter}"


def section_url(chapter: str, section: str) -> str:
    """Return the canonical official HTML locator for one exact section."""

    return (
        "https://www.ncleg.gov/EnactedLegislation/Statutes/HTML/BySection/"
        f"Chapter_{chapter}/GS_{section}.html"
    )


_CHAPTER_HREF_RE = re.compile(
    r"Chapter_([0-9]+[A-Za-z]?)\.html",
    re.IGNORECASE,
)
_TOC_CHAPTER_PATH_RE = re.compile(
    r"/Laws/GeneralStatuteSections/Chapter([0-9]+[A-Za-z]?)\b",
    re.IGNORECASE,
)
_TOC_CHAPTER_LABEL_RE = re.compile(
    r"\bChapter\s+([0-9]+[A-Za-z]?)\b",
    re.IGNORECASE,
)
_TOC_INACTIVE_CHAPTER_RE = re.compile(
    r"\b(repealed|recodified|recodifed|transferred|expired|unconstitutional|"
    r"abolished|deleted|omitted|redesignated|rewritten|superseded)\b",
    re.IGNORECASE,
)


def _is_inactive_disposition(value: str) -> bool:
    """Return whether a heading is unambiguously no longer operative.

    The official inventory also publishes ``Contingently repealed`` sections
    whose operative text remains in force until the stated contingency.  A
    bare keyword search would silently discard those current statutes.
    """

    normalized = _WS.sub(" ", str(value or "")).strip()
    without_contingent_repeal = re.sub(
        r"\bcontingently\s+repealed\b",
        "",
        normalized,
        flags=re.IGNORECASE,
    )
    return _INACTIVE.search(without_contingent_repeal) is not None


class NorthCarolinaTocChapterRecord(TypedDict):
    chapter_number: str
    chapter_name: str
    label: str
    disposition: Literal["active", "inactive"]
    source_url: str


class NorthCarolinaChapterSectionRecord(TypedDict):
    """One section advertised by an official chapter-section index."""

    section_number: str
    section_name: str
    disposition: Literal["active", "inactive"]
    source_url: str


def bychapter_index_links(html: str) -> List[str]:
    """Chapter numbers from an official ByChapter directory listing."""

    seen: List[str] = []
    found = set()
    for match in _CHAPTER_HREF_RE.finditer(html or ""):
        number = match.group(1)
        if number in found:
            continue
        found.add(number)
        seen.append(number)
    return seen


def toc_chapter_links(html: str) -> List[str]:
    """Chapter numbers from the official GeneralStatutesTOC page.

    Prefers ``/Laws/GeneralStatuteSections/ChapterN`` hrefs; falls back to
    ``Chapter N`` labels when the listing has no ByChapter files.
    """

    seen: List[str] = []
    found = set()
    for match in _TOC_CHAPTER_PATH_RE.finditer(html or ""):
        number = match.group(1)
        if number in found:
            continue
        found.add(number)
        seen.append(number)
    if seen:
        return seen
    for match in _TOC_CHAPTER_LABEL_RE.finditer(html or ""):
        number = match.group(1)
        if number in found:
            continue
        found.add(number)
        seen.append(number)
    return seen


def toc_chapter_frontier(html: str) -> List[NorthCarolinaTocChapterRecord]:
    """Return deduplicated live TOC chapters with explicit inactive dispositions."""

    try:
        from bs4 import BeautifulSoup
    except ImportError as exc:
        raise RuntimeError("BeautifulSoup is required for NC TOC closure") from exc

    soup = BeautifulSoup(html or "", "html.parser")
    records: List[NorthCarolinaTocChapterRecord] = []
    seen: set[str] = set()
    for anchor in soup.find_all("a", href=True):
        href = str(anchor.get("href") or "").strip()
        match = _TOC_CHAPTER_PATH_RE.search(href)
        if not match:
            continue
        number = match.group(1)
        canonical_number = number.upper()
        if canonical_number in seen:
            continue
        seen.add(canonical_number)
        row = anchor.find_parent("div", class_="row")
        label = _WS.sub(" ", (row or anchor).get_text(" ", strip=True)).strip()
        name = re.sub(
            rf"^Chapter\s+{re.escape(number)}\s*",
            "",
            label,
            flags=re.IGNORECASE,
        ).strip()
        disposition: Literal["active", "inactive"] = (
            "inactive" if _TOC_INACTIVE_CHAPTER_RE.search(label) else "active"
        )
        records.append(
            NorthCarolinaTocChapterRecord(
                chapter_number=number,
                chapter_name=name or f"Chapter {number}",
                label=label,
                disposition=disposition,
                source_url=chapter_url(number),
            )
        )
    return records


def merge_discovered_chapters(
    catalog: Sequence[Tuple[str, str]],
    discovered: Sequence[str],
) -> List[Tuple[str, str]]:
    """Put discovered ByChapter/TOC numbers first; keep named catalog as tail."""

    names = dict(catalog)
    leading: List[Tuple[str, str]] = []
    found = set()
    for number in discovered:
        token = str(number or "").strip()
        if not token or token in found:
            continue
        found.add(token)
        leading.append((token, names.get(token, f"Chapter {token}")))
    tail = [(number, name) for number, name in catalog if number not in found]
    return leading + tail


def configured_bychapter_index_path() -> Optional[Path]:
    raw = str(os.environ.get("NORTH_CAROLINA_BYCHAPTER_INDEX_HTML") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None


def configured_toc_html_path() -> Optional[Path]:
    raw = str(os.environ.get("NORTH_CAROLINA_TOC_HTML") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None


def decode_chapter_bytes(payload: bytes) -> str:
    """Decode ByChapter dumps (utf-8 live pages or Word cp1252 Wayback captures)."""

    data = payload or b""
    for encoding in ("utf-8", "cp1252", "latin-1"):
        try:
            text = data.decode(encoding)
        except Exception:
            continue
        if "§" in text or "&sect;" in text or "&#167;" in text:
            return text
    return data.decode("utf-8", errors="replace")


def _clean_soup_text(html: str) -> str:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return html or ""
    soup = BeautifulSoup(html or "", "html.parser")
    for tag in soup(["script", "style", "nav", "header", "footer", "noscript", "form"]):
        tag.decompose()
    for node in list(soup.find_all(True)):
        text = _WS.sub(" ", node.get_text(" ") or "").strip().lower()
        ambiguous_site_map_only = text in {"site map", "sitemap"}
        if ambiguous_site_map_only or any(
            marker in text and len(text) < 180
            for marker in NAV_MARKERS
            if marker not in {"site map", "sitemap"}
        ):
            node.decompose()
    return soup.get_text("\n", strip=True).replace("\xa0", " ")


def chapter_section_index_frontier(
    html: str,
    *,
    chapter: str,
) -> List[NorthCarolinaChapterSectionRecord]:
    """Parse the independent official ChapterN listing's HTML section links."""

    try:
        from bs4 import BeautifulSoup
    except ImportError as exc:
        raise RuntimeError("BeautifulSoup is required for NC section closure") from exc

    section_href_re = re.compile(
        rf"/EnactedLegislation/Statutes/HTML/BySection/Chapter_{re.escape(chapter)}/"
        r"GS_(?P<num>[0-9A-Za-z.\-]+)\.html$",
        re.IGNORECASE,
    )
    soup = BeautifulSoup(html or "", "html.parser")
    records: List[NorthCarolinaChapterSectionRecord] = []
    seen: set[str] = set()
    for anchor in soup.find_all("a", href=True):
        href = str(anchor.get("href") or "").strip()
        match = section_href_re.search(href)
        if not match:
            continue
        number = match.group("num").strip()
        canonical_number = number.upper()
        if not number or canonical_number in seen:
            continue
        seen.add(canonical_number)
        row = anchor.find_parent("div", class_="row")
        label = _WS.sub(" ", (row or anchor).get_text(" ", strip=True)).strip()
        heading_match = re.search(
            rf"§\s*{re.escape(number)}[.:]?\s*(?P<head>.*)$",
            label,
            flags=re.IGNORECASE,
        ) or re.search(
            rf"G\.S\.\s*{re.escape(number)}[.:]?\s*(?P<head>.*)$",
            label,
            flags=re.IGNORECASE,
        )
        heading = (
            str(heading_match.group("head") or "").strip()
            if heading_match
            else label
        )
        records.append(
            NorthCarolinaChapterSectionRecord(
                section_number=number,
                section_name=heading,
                disposition=(
                    "inactive" if _is_inactive_disposition(label) else "active"
                ),
                source_url=urljoin("https://www.ncleg.gov", href),
            )
        )
    return records


def north_carolina_section_page_identity(html: str) -> Optional[Tuple[str, str]]:
    """Return the exact ``(chapter, section)`` identity proved by a section page.

    North Carolina's official BySection pages expose the requested section in
    both the document title and the statutory heading.  A containing chapter
    heading is an additional exact cross-check when present; Article/Subpart
    documents legitimately omit it.  This prevents an archived redirect,
    generic shell, or neighboring section from satisfying a residual request.
    """

    try:
        from bs4 import BeautifulSoup
    except ImportError as exc:
        raise RuntimeError("BeautifulSoup is required for NC section identity") from exc

    soup = BeautifulSoup(html or "", "html.parser")
    title_text = _WS.sub(" ", soup.title.get_text(" ", strip=True)).strip() if soup.title else ""
    title_match = re.fullmatch(
        r"G\.S\.\s*(?P<section>[0-9A-Za-z.\-]+)",
        title_text,
        flags=re.IGNORECASE,
    )
    if title_match is None:
        return None

    chapter = ""
    for heading in soup.find_all(("h1", "h2", "h3", "h4", "h5", "h6")):
        heading_text = _WS.sub(" ", heading.get_text(" ", strip=True)).strip()
        chapter_match = re.fullmatch(
            r"Chapter\s+(?P<chapter>[0-9]+[A-Za-z]?)\.?",
            heading_text,
            flags=re.IGNORECASE,
        )
        if chapter_match is not None:
            chapter = chapter_match.group("chapter")
            break
    section = title_match.group("section")
    section_chapter, separator, _section_tail = section.partition("-")
    if not separator or not section_chapter:
        return None
    # Some exact BySection documents nested under an Article/Subpart omit the
    # chapter heading entirely.  The title and statutory heading still prove
    # the exact section; when a chapter heading is present it remains a strict
    # independent cross-check rather than a prerequisite.
    if chapter and chapter.casefold() != section_chapter.casefold():
        return None
    body_text = _WS.sub(
        " ",
        (soup.body or soup).get_text(" ", strip=True),
    ).strip()
    escaped_section = re.escape(section)
    if "-" in section:
        escaped_section = escaped_section.replace(
            r"\-",
            r"\s*[.\-]\s*",
            1,
        )
    statutory_heading = re.search(
        rf"(?:§|G\.S\.)\s*{escaped_section}(?:[.:](?=\s|$)|(?=\s))",
        body_text,
        flags=re.IGNORECASE,
    )
    if statutory_heading is None:
        return None
    return section_chapter, section


def source_bound_terminal_disposition_from_section_html(
    html: str,
    *,
    chapter: str,
    section: str,
    source_url: str,
) -> Optional[str]:
    """Classify one exact official heading-only section publication.

    The current General Assembly document for G.S. 130A-295.1 contains only
    its source-bound heading and an editor-note marker—no operative body or
    history.  Treating every editor-note heading as terminal would be unsafe,
    so the contract pins the official URL, body digest, page identity, and DOM
    shape.  Any publisher change fails closed and must be audited again.
    """

    expected_chapter = str(chapter or "").strip()
    expected_section = str(section or "").strip()
    specification = _EXACT_HEADING_ONLY_SECTION_TERMINALS.get(
        (expected_chapter, expected_section)
    )
    if (
        specification is None
        or source_url != section_url(expected_chapter, expected_section)
        or north_carolina_section_page_identity(html)
        != (expected_chapter, expected_section)
        or hashlib.sha256(str(html or "").encode("utf-8")).hexdigest()
        != specification["content_sha256"]
    ):
        return None
    try:
        from bs4 import BeautifulSoup
    except ImportError as exc:
        raise RuntimeError("BeautifulSoup is required for NC terminal identity") from exc
    soup = BeautifulSoup(html or "", "html.parser")
    body = soup.body
    if body is None:
        return None
    direct_elements = [child for child in body.children if getattr(child, "name", None)]
    if len(direct_elements) != 1 or direct_elements[0].name != "p":
        return None
    paragraph = direct_elements[0]
    anchor = paragraph.find("a", attrs={"name": "GSDocumentHeader"})
    spans = paragraph.find_all("span", recursive=False)
    if (
        anchor is None
        or anchor.get("href") is not None
        or len(spans) != 1
        or _WS.sub(" ", body.get_text(" ", strip=True)).strip()
        != specification["heading"]
    ):
        return None
    return str(specification["disposition"])


def source_bound_empty_chapter_disposition(
    chapter_html: str,
    section_index_html: str,
    *,
    chapter: str,
    chapter_source_url: str,
    section_index_source_url: str,
) -> Optional[str]:
    """Classify an official no-link chapter only when two pages prove it terminal."""

    if (
        chapter_source_url != chapter_url(chapter)
        or section_index_source_url != chapter_sections_url(chapter)
        or chapter_section_index_frontier(section_index_html, chapter=chapter)
    ):
        return None
    try:
        from bs4 import BeautifulSoup
    except ImportError as exc:
        raise RuntimeError("BeautifulSoup is required for NC terminal identity") from exc

    chapter_soup = BeautifulSoup(chapter_html or "", "html.parser")
    index_soup = BeautifulSoup(section_index_html or "", "html.parser")
    chapter_title = (
        _WS.sub(" ", chapter_soup.title.get_text(" ", strip=True)).strip()
        if chapter_soup.title
        else ""
    )
    if re.fullmatch(
        rf"Chapter\s+{re.escape(chapter)}",
        chapter_title,
        flags=re.IGNORECASE,
    ) is None:
        return None
    chapter_headings = [
        _WS.sub(" ", heading.get_text(" ", strip=True)).strip()
        for heading in chapter_soup.find_all(("h1", "h2", "h3", "h4", "h5", "h6"))
    ]
    if not any(
        re.fullmatch(
            rf"Chapter\s+{re.escape(chapter)}\.?",
            heading,
            flags=re.IGNORECASE,
        )
        for heading in chapter_headings
    ):
        return None
    index_heading = index_soup.find("h1", class_="section-title")
    index_heading_text = (
        _WS.sub(" ", index_heading.get_text(" ", strip=True)).strip()
        if index_heading is not None
        else ""
    )
    if re.fullmatch(
        rf"Chapter\s+{re.escape(chapter)}\s+-\s+.+",
        index_heading_text,
        flags=re.IGNORECASE,
    ) is None:
        return None
    breadcrumb = index_soup.select_one("li.breadcrumb-item.active")
    breadcrumb_text = (
        _WS.sub(" ", breadcrumb.get_text(" ", strip=True)).strip()
        if breadcrumb is not None
        else ""
    )
    if breadcrumb_text.casefold() != f"chapter {chapter}".casefold():
        return None

    terminal_pattern = re.compile(
        rf"§§?\s*{re.escape(chapter)}-[0-9A-Za-z.]+"
        rf"(?:\s+through\s+(?:§§?\s*)?{re.escape(chapter)}-[0-9A-Za-z.]+)?"
        r"\s*[:.]\s*(?P<disposition>abolished|expired|recodified|renumbered|"
        r"recodifed|repealed|reserved|transferred|unconstitutional|deleted|"
        r"omitted)\b",
        flags=re.IGNORECASE,
    )

    def _terminal_disposition(soup: object) -> str:
        text = _WS.sub(" ", soup.get_text(" ", strip=True)).strip()
        match = terminal_pattern.search(text)
        return str(match.group("disposition") or "").casefold() if match else ""

    chapter_disposition = _terminal_disposition(chapter_soup)
    index_disposition = _terminal_disposition(index_soup)
    if not chapter_disposition or chapter_disposition != index_disposition:
        return None
    return chapter_disposition


def _effective_date(match: re.Match[str]) -> date:
    return datetime.strptime(
        f"{match.group('month')} {match.group('day')} {match.group('year')}",
        "%B %d %Y",
    ).date()


def _effective_variant_interval(
    heading: str,
) -> Tuple[Optional[date], Optional[date], str]:
    """Return a half-open legal-effective interval for one NC variant heading."""

    normalized = _WS.sub(" ", str(heading or "")).strip()
    lowered = normalized.casefold().replace("–", "-").replace("—", "-")
    dated = [
        (_effective_date(match), match.start())
        for match in _EFFECTIVE_DATE_RE.finditer(normalized)
    ]
    lower_bound: Optional[date] = None
    upper_bound: Optional[date] = None

    for effective_date, offset in dated:
        prefix = lowered[max(0, offset - 90) : offset]
        last_until = prefix.rfind("until")
        last_before = prefix.rfind("beginning before")
        last_on_or_after = prefix.rfind("beginning on or after")
        last_effective = prefix.rfind("effective")
        if (
            max(last_until, last_before) > max(last_on_or_after, last_effective)
            or "expiring for taxable years beginning on or after" in prefix
        ):
            upper_bound = effective_date
        elif last_effective >= 0 and (
            last_on_or_after > last_before
            or prefix.rstrip().endswith("effective")
        ):
            lower_bound = effective_date

    if dated and (lower_bound is not None or upper_bound is not None):
        return lower_bound, upper_bound, "dated_interval"
    school_year = re.search(
        r"(?P<first>\d{4})-(?P<second>\d{4})\s+school\s+year",
        lowered,
    )
    if school_year is not None:
        boundary = date(int(school_year.group("first")), 7, 1)
        if "before" in lowered:
            return None, boundary, "dated_interval"
        if "beginning with" in lowered:
            return boundary, None, "dated_interval"
    if "effective until contingency met" in lowered:
        return None, None, "until_contingency"
    if "effective once contingency met" in lowered:
        return None, None, "after_contingency"
    return None, None, "unqualified"


def _normalized_frontier_heading(value: str) -> str:
    heading = re.split(
        r"\bModified\s+by\s*:",
        _WS.sub(" ", str(value or "")).strip(),
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]
    return heading.replace("–", "-").replace("—", "-").rstrip().casefold()


def _select_effective_variant(
    rows: Sequence[NormalizedStatute],
    *,
    as_of_date: Optional[date],
    frontier_heading: str,
) -> Optional[NormalizedStatute]:
    """Select exactly one temporal version for a single statutory identity."""

    if len(rows) == 1:
        return rows[0]

    intervals = [
        _effective_variant_interval(str(row.section_name or "")) for row in rows
    ]
    if as_of_date is not None:
        eligible = [
            row
            for row, (lower_bound, upper_bound, kind) in zip(
                rows,
                intervals,
                strict=True,
            )
            if kind == "dated_interval"
            and (lower_bound is None or lower_bound <= as_of_date)
            and (upper_bound is None or as_of_date < upper_bound)
        ]
        if len(eligible) == 1:
            selected = eligible[0]
            selected.structured_data = {
                **dict(selected.structured_data or {}),
                "effective_variant_count": len(rows),
                "effective_variant_selection": "source_observation_date",
                "effective_variant_as_of_date": as_of_date.isoformat(),
            }
            return selected

    # The current official inventory names the pre-contingency variant.  Use
    # that independent heading only for an event-based pair that cannot be
    # resolved from a calendar date; dated variants never take this fallback.
    if frontier_heading and {kind for _lower, _upper, kind in intervals} <= {
        "until_contingency",
        "after_contingency",
    }:
        expected = _normalized_frontier_heading(frontier_heading)
        matches = [
            row
            for row in rows
            if _normalized_frontier_heading(str(row.section_name or "")) == expected
        ]
        if len(matches) == 1:
            selected = matches[0]
            selected.structured_data = {
                **dict(selected.structured_data or {}),
                "effective_variant_count": len(rows),
                "effective_variant_selection": (
                    "official_frontier_contingency_heading"
                ),
                "effective_variant_as_of_date": (
                    as_of_date.isoformat() if as_of_date is not None else ""
                ),
            }
            return selected
    return None


def parse_north_carolina_chapter_html(
    html: str,
    *,
    chapter: str,
    code_name: str = "North Carolina General Statutes",
    max_statutes: Optional[int] = None,
    source_url: Optional[str] = None,
    as_of_date: Optional[date] = None,
    section_frontier_names: Optional[Mapping[str, str]] = None,
    minimum_body_chars: int = 40,
) -> List[NormalizedStatute]:
    text = _clean_soup_text(html)
    matches = list(_SECTION_RE.finditer(text))
    if not matches:
        matches = list(_WORD_HEAD_RE.finditer(text))
    parsed: List[NormalizedStatute] = []
    for index, match in enumerate(matches):
        number = re.sub(
            r"\s*[-‑]\s*",
            "-",
            match.group("num").strip(),
        ).rstrip(".")
        if "-" not in number and number.count(".") >= 2:
            # One retained official BySection document prints the first
            # chapter separator as a period (``143.215.74H``).  Page-title
            # identity remains canonical and independently checked by the
            # residual wrapper, so normalize only that first separator.
            number = number.replace(".", "-", 1)
        heading = match.group("head").strip()
        if _is_inactive_disposition(heading):
            continue
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        body = _WS.sub(" ", text[start:end]).strip()
        lowered = body.lower()
        # ``site map`` is ordinary statutory language in environmental,
        # alcohol-permit, and outdoor-advertising provisions.  Navigation
        # nodes carrying that label were already removed structurally by
        # ``_clean_soup_text``; a body-wide substring test must not erase law.
        if any(
            marker in lowered
            for marker in NAV_MARKERS
            if marker != "site map"
        ):
            continue
        if len(body) < max(1, int(minimum_body_chars)):
            continue
        parsed.append(
            NormalizedStatute(
                state_code="NC",
                state_name="North Carolina",
                statute_id=f"{code_name} § {number}",
                code_name=code_name,
                chapter_number=str(chapter),
                section_number=number,
                section_name=heading[:200],
                full_text=body,
                source_url=source_url or chapter_url(chapter),
                official_cite=f"N.C. Gen. Stat. § {number}",
                metadata=StatuteMetadata(),
                structured_data={
                    "source_kind": "official_north_carolina_bychapter_html",
                    "source_authority_class": "official",
                    "discovery_method": "ncleg_bychapter_nav_stripped",
                    "skip_hydrate": True,
                },
            )
        )

    grouped: dict[str, List[NormalizedStatute]] = {}
    order: List[str] = []
    for row in parsed:
        key = str(row.section_number or "").casefold()
        if key not in grouped:
            grouped[key] = []
            order.append(key)
        grouped[key].append(row)
    frontier_names = {
        str(number).casefold(): str(heading)
        for number, heading in dict(section_frontier_names or {}).items()
    }
    statutes: List[NormalizedStatute] = []
    for key in order:
        selected = _select_effective_variant(
            grouped[key],
            as_of_date=as_of_date,
            frontier_heading=frontier_names.get(key, ""),
        )
        if selected is None:
            continue
        statutes.append(selected)
        if max_statutes is not None and len(statutes) >= int(max_statutes):
            break
    return statutes


def parse_north_carolina_section_html(
    html: str,
    *,
    chapter: str,
    section: str,
    source_url: str,
    code_name: str = "North Carolina General Statutes",
    as_of_date: Optional[date] = None,
    frontier_section_name: str = "",
) -> Optional[NormalizedStatute]:
    """Parse one source-bound official BySection residual page.

    This intentionally delegates statutory block extraction to the existing
    ByChapter parser.  The wrapper adds strict page/URL identity and changes
    only the source provenance for the exact residual document.
    """

    expected_url = section_url(chapter, section)
    identity = north_carolina_section_page_identity(html)
    if (
        source_url != expected_url
        or identity is None
        or identity[0].casefold() != str(chapter).casefold()
        or identity[1].casefold() != str(section).casefold()
    ):
        return None

    rows = parse_north_carolina_chapter_html(
        html,
        chapter=chapter,
        code_name=code_name,
        source_url=source_url,
        as_of_date=as_of_date,
        section_frontier_names={section: frontier_section_name},
        minimum_body_chars=1,
    )

    def _comparison_identity(value: str) -> str:
        token = str(value or "").strip()
        if "-" not in token and "." in token:
            token = token.replace(".", "-", 1)
        return token.casefold()

    matching = [
        row
        for row in rows
        if str(row.chapter_number or "").casefold() == str(chapter).casefold()
        and _comparison_identity(str(row.section_number or ""))
        == _comparison_identity(str(section))
        and str(row.source_url or "") == source_url
    ]
    if len(matching) != 1:
        return None
    row = matching[0]
    # Preserve the independent inventory/title spelling when an official body
    # differs only in chapter-letter case or the known first-separator typo.
    row.section_number = str(section)
    row.statute_id = f"{code_name} § {section}"
    row.official_cite = f"N.C. Gen. Stat. § {section}"
    row.structured_data = {
        **dict(row.structured_data or {}),
        "source_kind": "official_north_carolina_bysection_html",
        "discovery_method": "official_active_section_residual_reconciliation",
    }
    return row


def configured_chapter_html_path() -> Optional[Path]:
    raw = str(os.environ.get("NORTH_CAROLINA_CHAPTER_HTML") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None


def configured_chapter_html_paths() -> List[Path]:
    paths: List[Path] = []
    single = configured_chapter_html_path()
    if single is not None:
        paths.append(single)
    raw_dir = str(os.environ.get("NORTH_CAROLINA_CHAPTER_HTML_DIR") or "").strip()
    if raw_dir:
        directory = Path(raw_dir).expanduser()
        if directory.is_dir():
            paths.extend(
                sorted(
                    child
                    for child in directory.iterdir()
                    if child.is_file() and child.suffix.lower() in {".html", ".htm"}
                )
            )
    return paths


def chapter_token_from_path(path: Path) -> str:
    stem = path.stem.replace("Chapter_", "").replace("chapter_", "")
    return stem or "14"


def parse_configured_north_carolina_chapters(
    *,
    code_name: str = "North Carolina General Statutes",
    max_statutes: Optional[int] = None,
) -> List[NormalizedStatute]:
    statutes: List[NormalizedStatute] = []
    seen: set[str] = set()
    for path in configured_chapter_html_paths():
        if max_statutes is not None and len(statutes) >= int(max_statutes):
            break
        remaining = None if max_statutes is None else max(0, int(max_statutes) - len(statutes))
        rows = parse_north_carolina_chapter_html(
            path.read_text(encoding="utf-8", errors="replace"),
            chapter=chapter_token_from_path(path),
            code_name=code_name,
            max_statutes=remaining,
        )
        for row in rows:
            key = str(row.section_number or "")
            if key in seen:
                continue
            seen.add(key)
            statutes.append(row)
    return statutes
