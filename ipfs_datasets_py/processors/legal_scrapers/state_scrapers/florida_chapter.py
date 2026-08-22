"""Official Florida Online Sunshine chapter-page parser.

Adapted from Vaquill-AI/open-us-law ``fl_bulk`` (Apache-2.0).
``leg.state.fl.us`` publishes each chapter as one ``Display_Statute`` page of
``div.Section`` blocks (number / catchline / body / history).
"""

from __future__ import annotations

import re
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
