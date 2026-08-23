"""Official Florida Online Sunshine chapter-page parser.

Adapted from Vaquill-AI/open-us-law ``fl_bulk`` (Apache-2.0).
``leg.state.fl.us`` publishes each chapter as one ``Display_Statute`` page of
``div.Section`` blocks (number / catchline / body / history).
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import List, Optional
from urllib.parse import parse_qs, urlparse

from .base_scraper import NormalizedStatute, StatuteMetadata

SITE = "https://www.leg.state.fl.us/Statutes"
INDEX = f"{SITE}/index.cfm"

_WS_RE = re.compile(r"\s+")
_ROMAN_RE = re.compile(r"(?:title|part)\s+([IVXLCDM]+)", re.IGNORECASE)
_TITLE_REQ_RE = re.compile(r"Title_Request=([IVXLCDM]+)")
_CH_HREF_RE = re.compile(
    r"URL=(\d{4}-\d{4})/(\d{4})/\d{4}\w*\.html",
    re.IGNORECASE,
)
_RESERVED_KEYWORDS = (
    "[repealed",
    "[reserved",
    "[expired",
    "[transferred",
    "[renumbered",
    "[former",
)
_HIST_LEAD_RE = re.compile(r"^\s*history\.?\s*[—\-:]*\s*", re.IGNORECASE)
_SENATE_CHAPTER_RE = re.compile(
    r"/Laws/Statutes/(?P<year>\d{4})/Chapter(?P<chapter>\d+)/All",
    re.IGNORECASE,
)
SENATE_BASE = "https://www.flsenate.gov"


def band_for(chapter: str) -> str:
    """``782`` -> ``0700-0799`` (Online Sunshine directory band)."""

    lo = (int(chapter) // 100) * 100
    return f"{lo:04d}-{lo + 99:04d}"


def padded(chapter: str) -> str:
    """``782`` -> ``0782``."""

    return f"{int(chapter):04d}"


def chapter_page_url(chapter: str) -> str:
    pad = padded(chapter)
    return f"{INDEX}?App_mode=Display_Statute&URL={band_for(chapter)}/{pad}/{pad}.html"


def section_page_url(chapter: str, section_number: str) -> str:
    pad = padded(chapter)
    return (
        f"{INDEX}?App_mode=Display_Statute&Search_String=&URL="
        f"{band_for(chapter)}/{pad}/Sections/{section_number}.html"
    )


def chapter_number_from_url(url: str) -> str:
    """Extract the integer chapter token from an Online Sunshine chapter URL."""

    parsed = urlparse(str(url or ""))
    query = parse_qs(parsed.query)
    raw = (query.get("URL") or [""])[0]
    match = _CH_HREF_RE.search(f"URL={raw}") if raw else _CH_HREF_RE.search(str(url or ""))
    if match:
        return str(int(match.group(2)))
    digits = re.search(r"/(\d{4})(?:ContentsIndex)?\.html", str(url or ""), re.IGNORECASE)
    if digits:
        return str(int(digits.group(1)))
    return ""


def title_romans(toc_html: str) -> List[str]:
    out: List[str] = []
    seen = set()
    for match in _TITLE_REQ_RE.finditer(toc_html or ""):
        roman = match.group(1).upper()
        if roman in seen:
            continue
        seen.add(roman)
        out.append(roman)
    return out


def title_chapters(index_html: str) -> List[str]:
    out: List[str] = []
    seen = set()
    for match in _CH_HREF_RE.finditer(index_html or ""):
        number = str(int(match.group(2)))
        if number in seen:
            continue
        seen.add(number)
        out.append(number)
    return out


def _clean(raw: str) -> str:
    text = (raw or "").replace("\xa0", " ").replace("\u200b", "")
    return _WS_RE.sub(" ", text).strip()


def _roman(label: str) -> Optional[str]:
    match = _ROMAN_RE.search(label or "")
    return match.group(1).upper() if match else None


def _has_reserved_marker(text: str) -> bool:
    low = (text or "").lower()
    return any(keyword in low for keyword in _RESERVED_KEYWORDS)


def parse_florida_chapter_html(
    html: str | bytes,
    *,
    chapter: str,
    code_name: str = "Florida Statutes",
    title_roman: str = "",
    title_name: str = "",
    max_statutes: Optional[int] = None,
) -> List[NormalizedStatute]:
    """Parse every ``div.Section`` on one Online Sunshine chapter page."""

    if not html:
        return []
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []

    if isinstance(html, bytes):
        html = html.decode("utf-8", errors="replace")
    soup = BeautifulSoup(html, "html.parser")
    chapter_token = str(chapter or "").strip() or chapter_number_from_url("")
    statutes: List[NormalizedStatute] = []
    seen = set()

    for section_div in soup.find_all("div", class_="Section"):
        if max_statutes is not None and len(statutes) >= int(max_statutes):
            break
        num_el = section_div.find(class_="SectionNumber")
        if num_el is None:
            continue
        number = _clean(num_el.get_text(" "))
        if not number or number in seen:
            continue
        cat_el = section_div.find(class_="CatchlineText") or section_div.find(class_="Catchline")
        catchline = _clean(cat_el.get_text(" ")) if cat_el is not None else ""
        if _has_reserved_marker(catchline):
            continue
        body = section_div.find(class_="SectionBody")
        paragraphs: List[str] = []
        if body is not None:
            for child in body.find_all(recursive=False):
                text = _clean(child.get_text(" "))
                if text:
                    paragraphs.append(text)
            if not paragraphs:
                flat = _clean(body.get_text(" "))
                if flat:
                    paragraphs.append(flat)
        if not paragraphs:
            skip = {"sectionnumber", "catchlinetext", "catchline", "history"}
            for child in section_div.find_all(recursive=False):
                classes = {str(item).lower() for item in (child.get("class") or [])}
                if classes & skip:
                    continue
                text = _clean(child.get_text(" "))
                if text and text not in {number, catchline}:
                    paragraphs.append(text)
        full_text = " ".join(paragraphs).strip()
        if len(full_text) < 40:
            continue
        hist_el = section_div.find(class_="History")
        history = ""
        if hist_el is not None:
            history = _HIST_LEAD_RE.sub("", _clean(hist_el.get_text(" "))).strip()
        part_div = section_div.find_parent("div", class_="Part")
        part_roman = None
        if part_div is not None:
            pn = part_div.find(class_="PartNumber") or part_div.find(class_="PartTitle")
            part_roman = _roman(pn.get_text(" ", strip=True)) if pn is not None else None
        seen.add(number)
        try:
            source = section_page_url(chapter_token, number)
        except (TypeError, ValueError):
            source = chapter_page_url(chapter_token) if chapter_token else ""
        statutes.append(
            NormalizedStatute(
                state_code="FL",
                state_name="Florida",
                statute_id=f"FL-{number}",
                code_name=code_name,
                title_number=title_roman or None,
                title_name=title_name or None,
                chapter_number=chapter_token or None,
                section_number=number,
                section_name=(catchline[:200] if catchline else f"Section {number}"),
                short_title=catchline[:200] if catchline else None,
                full_text=full_text[:14000],
                source_url=source,
                official_cite=f"Fla. Stat. § {number}",
                structured_data={
                    "source_kind": "official_florida_chapter_html",
                    "source_authority_class": "official",
                    "discovery_method": "online_sunshine_display_statute",
                    "part_roman": part_roman,
                    "history": history,
                    "skip_hydrate": True,
                },
            )
        )
    return statutes


def senate_chapter_url(chapter: str, year: str = "2025") -> str:
    return f"{SENATE_BASE}/Laws/Statutes/{year}/Chapter{int(chapter)}/All"


def chapter_number_from_senate_url(url: str) -> str:
    match = _SENATE_CHAPTER_RE.search(str(url or ""))
    if match:
        return str(int(match.group("chapter")))
    return ""


def parse_florida_senate_all_html(
    html: str | bytes,
    *,
    chapter: str = "",
    year: str = "2025",
    code_name: str = "Florida Statutes",
    max_statutes: Optional[int] = None,
    source_url: str = "",
) -> List[NormalizedStatute]:
    """Parse flsenate.gov ``/Laws/Statutes/{year}/Chapter{N}/All`` dumps.

    Vaquill listed this as the Online Sunshine alternative. The Senate All
    page often reuses ``div.Section``; otherwise SectionNumber/Catchline
    spans are walked until the next section. History paragraphs are dropped.
    """

    if isinstance(html, bytes):
        html = html.decode("utf-8", errors="replace")
    chapter_token = str(chapter or "").strip() or chapter_number_from_senate_url(source_url)
    structured = parse_florida_chapter_html(
        html,
        chapter=chapter_token or "1",
        code_name=code_name,
        max_statutes=max_statutes,
    )
    if structured:
        link = source_url or (senate_chapter_url(chapter_token, year) if chapter_token else SENATE_BASE)
        for row in structured:
            row.source_url = f"{link}#{row.section_number}" if row.section_number else link
            row.structured_data["source_kind"] = "official_florida_senate_chapter_html"
            row.structured_data["discovery_method"] = "flsenate_chapter_all"
        return structured
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    soup = BeautifulSoup(html or "", "html.parser")
    nodes = soup.find_all(class_=re.compile(r"SectionNumber", re.IGNORECASE))
    if not nodes:
        return []
    statutes: List[NormalizedStatute] = []
    seen = set()
    for index, node in enumerate(nodes):
        if max_statutes is not None and len(statutes) >= int(max_statutes):
            break
        number = _clean(node.get_text(" "))
        if not number or number in seen:
            continue
        parent = node.find_parent(["p", "div", "h2", "h3"]) or node
        catch_el = parent.find(class_=re.compile(r"Catchline", re.IGNORECASE))
        catchline = _clean(catch_el.get_text(" ")) if catch_el is not None else ""
        if _has_reserved_marker(catchline) or _has_reserved_marker(number):
            continue
        parts: List[str] = []
        sibling = parent.next_sibling
        stop = nodes[index + 1] if index + 1 < len(nodes) else None
        stop_parent = stop.find_parent(["p", "div", "h2", "h3"]) if stop is not None else None
        while sibling is not None and sibling is not stop_parent:
            if getattr(sibling, "get_text", None):
                text = _clean(sibling.get_text(" "))
                if text and not _HIST_LEAD_RE.match(text) and "history." not in text.lower()[:12]:
                    parts.append(text)
            sibling = sibling.next_sibling
        full_text = " ".join(parts).strip()
        if len(full_text) < 40:
            rest = _clean(parent.get_text(" "))
            rest = rest.replace(number, "", 1).replace(catchline, "", 1).strip()
            full_text = rest
        if len(full_text) < 40 or _has_reserved_marker(full_text[:160]):
            continue
        seen.add(number)
        link = source_url or (senate_chapter_url(chapter_token or number.split(".", 1)[0], year))
        statutes.append(
            NormalizedStatute(
                state_code="FL",
                state_name="Florida",
                statute_id=f"FL-{number}",
                code_name=code_name,
                chapter_number=chapter_token or number.split(".", 1)[0],
                section_number=number,
                section_name=(catchline[:200] if catchline else f"Section {number}"),
                short_title=catchline[:200] if catchline else None,
                full_text=full_text[:14000],
                source_url=f"{link}#{number}",
                official_cite=f"Fla. Stat. § {number}",
                structured_data={
                    "source_kind": "official_florida_senate_chapter_html",
                    "source_authority_class": "official",
                    "discovery_method": "flsenate_chapter_all",
                    "skip_hydrate": True,
                },
            )
        )
    return statutes


def configured_florida_chapter_paths() -> List[Path]:
    paths: List[Path] = []
    for key in ("FLORIDA_SENATE_CHAPTER_HTML", "FLORIDA_CHAPTER_HTML"):
        raw = str(os.environ.get(key) or "").strip()
        if not raw:
            continue
        path = Path(raw).expanduser()
        if path.is_file():
            paths.append(path)
    return paths


def parse_configured_florida_chapter(
    *,
    code_name: str = "Florida Statutes",
    max_statutes: Optional[int] = None,
) -> List[NormalizedStatute]:
    statutes: List[NormalizedStatute] = []
    seen: set[str] = set()
    for path in configured_florida_chapter_paths():
        if max_statutes is not None and len(statutes) >= int(max_statutes):
            break
        remaining = None if max_statutes is None else max(0, int(max_statutes) - len(statutes))
        html = path.read_text(encoding="utf-8", errors="replace")
        chapter = ""
        match = re.search(r"(?:chapter[-_ ]?)(\d{1,4})", path.stem, re.IGNORECASE)
        if match:
            chapter = str(int(match.group(1)))
        rows = parse_florida_senate_all_html(
            html,
            chapter=chapter,
            code_name=code_name,
            max_statutes=remaining,
            source_url=senate_chapter_url(chapter or "782"),
        )
        if not rows:
            rows = parse_florida_chapter_html(
                html,
                chapter=chapter or "782",
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
