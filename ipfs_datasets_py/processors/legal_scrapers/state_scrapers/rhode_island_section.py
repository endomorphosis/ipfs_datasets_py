"""Official Rhode Island section HTML parser.

Adapted from Vaquill-AI/open-us-law ``scrapeRI.py`` (Apache-2.0).
Canonical host is ``webserver.rilegislature.gov`` (the old rilin host
redirects every sub-path back to the TOC). Body is top-level ``divs[2]``;
the nested ``History of Section`` div is dropped.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import List, Optional, Tuple

from .base_scraper import NormalizedStatute, StatuteMetadata

BASE = "https://webserver.rilegislature.gov/Statutes"
_HEAD_RE = re.compile(r"§\s*(?P<num>[0-9A-Za-z.-]+)\.\s*(?P<head>.+)")
_RESERVED = re.compile(r"\[(?:repealed|expired|reserved|renumbered)\]|repealed\.|reserved\.", re.IGNORECASE)
_HISTORY_PREFIX = "History of Section"
_WS = re.compile(r"\s+")
_STEM_RE = re.compile(r"/Statutes/TITLE(?P<title>[^/]+)/(?P<chapter>[^/]+)/(?P<section>[^/]+)\.htm$", re.IGNORECASE)


def _clean(text: str) -> str:
    value = (text or "").replace("\xa0", " ").replace("Â§", "§")
    return _WS.sub(" ", value).strip()


def parse_rhode_island_section_html(
    html: str,
    *,
    source_url: str = "",
    code_name: str = "Rhode Island General Laws",
) -> Optional[NormalizedStatute]:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return None
    soup = BeautifulSoup(html or "", "html.parser")
    body = soup.find("body") or soup
    top_divs = body.find_all("div", recursive=False)
    content = top_divs[2] if len(top_divs) >= 3 else (top_divs[-1] if top_divs else body)
    nested = content.find_all("div", recursive=False)
    history_div = nested[-1] if nested else None
    if history_div is not None:
        hist = _clean(history_div.get_text(" "))
        if _HISTORY_PREFIX in hist or "P.L." in hist or "G.L." in hist:
            history_div.decompose()
    heading = ""
    paras: list[str] = []
    for para in content.find_all("p", recursive=False):
        text = _clean(para.get_text(" "))
        if not text:
            continue
        bold = para.find("b")
        if bold is not None:
            bold_text = _clean(bold.get_text(" "))
            remainder = text.replace(bold_text, "").strip()
            if not remainder and bold_text.startswith("§"):
                heading = bold_text
                continue
        paras.append(text)
    body_text = _clean(" ".join(paras))
    if len(body_text) < 40:
        return None
    if _RESERVED.search(heading) or _RESERVED.search(body_text[:160]):
        return None
    match = _HEAD_RE.search(heading)
    number = match.group("num") if match else ""
    name = match.group("head").strip() if match else heading
    url_match = _STEM_RE.search(source_url or "")
    if url_match:
        number = number or url_match.group("section")
        title = url_match.group("title")
        chapter = url_match.group("chapter")
    else:
        title = number.split("-", 1)[0] if number else ""
        chapter = "-".join(number.split("-")[:2]) if number else ""
    if not number:
        return None
    return NormalizedStatute(
        state_code="RI",
        state_name="Rhode Island",
        statute_id=f"{code_name} § {number}",
        code_name=code_name,
        title_number=title or None,
        chapter_number=chapter or None,
        section_number=number,
        section_name=name[:200] or f"Section {number}",
        full_text=body_text[:14000],
        source_url=source_url or BASE,
        official_cite=f"R.I. Gen. Laws § {number}",
        metadata=StatuteMetadata(),
        structured_data={
            "source_kind": "official_rhode_island_section_html",
            "source_authority_class": "official",
            "discovery_method": "rilegislature_content_div2",
            "skip_hydrate": True,
        },
    )


def configured_section_html_path() -> Optional[Path]:
    raw = str(os.environ.get("RHODE_ISLAND_SECTION_HTML") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None


_TOC_TITLE_RE = re.compile(r"^TITLE([\w.\-]+)/INDEX\.HTM$", re.IGNORECASE)
_TITLE_CHAPTER_RE = re.compile(r"^([\w.\-]+)/INDEX\.HTM$", re.IGNORECASE)
_CHAPTER_SECTION_RE = re.compile(r"^([\w.\-]+)\.htm$", re.IGNORECASE)


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
    from urllib.parse import urljoin

    soup = BeautifulSoup(html or "", "html.parser")
    out: List[Tuple[str, str]] = []
    seen = set()
    for anchor in soup.find_all("a", href=True):
        href = str(anchor.get("href") or "").strip()
        match = _TITLE_CHAPTER_RE.match(href)
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
    """Section files including decimal stems like ``1-2-1.1.htm``."""

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
        match = _CHAPTER_SECTION_RE.match(href)
        if not match or href.upper() == "INDEX.HTM":
            continue
        number = re.sub(r"\.htm$", "", href, flags=re.IGNORECASE)
        url = urljoin(chapter_url, href)
        if url in seen:
            continue
        seen.add(url)
        name = _clean(anchor.get_text(" "))
        out.append((url, name or number))
    return out
