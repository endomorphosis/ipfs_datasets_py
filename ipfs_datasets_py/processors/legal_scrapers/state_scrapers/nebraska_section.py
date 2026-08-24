"""Official Nebraska section HTML parser.

Adapted from Vaquill-AI/open-us-law ``scrapeNE.py`` (Apache-2.0).
Body lives in ``#statute_text`` / ``.statute-body``; history/source classes
are dropped, and repealed stubs are skipped.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urljoin, urlparse

from .base_scraper import NormalizedStatute, StatuteMetadata

BASE = "https://nebraskalegislature.gov"
_SELECTORS = (
    ("div", {"id": "statute_text"}),
    ("div", {"id": "statuteText"}),
    ("div", {"class": "statute-body"}),
    ("div", {"class": "statute_body"}),
    ("div", {"class": "statute"}),
)
_RESERVED = re.compile(
    r"\brepealed\b|\bexpired\b|\breserved\b|\brenumbered\b|\bunconstitutional\b|\btransferred to\b",
    re.IGNORECASE,
)
_WS = re.compile(r"\s+")
# Vaquill scrapeNE: chapter tokens include alpha suffixes (76A) and hyphens;
# section ids include dotted forms such as 25-2740.04. Keep comma-thousands
# (2-32,113) from the live Nebraska index as well.
_CHAPTER_HREF_RE = re.compile(
    r"/laws/browse-chapters\.php\?chapter=([\w\-]+)$", re.IGNORECASE
)
_SECTION_HREF_RE = re.compile(
    r"/laws/statutes\.php\?statute=([\w.\-]+)$", re.IGNORECASE
)
_SECTION_NUMBER_RE = re.compile(r"^[\dA-Za-z]+(?:[-.,][\dA-Za-z]+)+$")
_ARTICLE_HEADING_RE = re.compile(
    r"^\s*ARTICLE\s+([\w\-]+)\b[\.\s\-:]*(.*)$", re.IGNORECASE
)


def _clean(text: str) -> str:
    return _WS.sub(" ", (text or "").replace("\xa0", " ")).strip()


def parse_nebraska_section_html(
    html: str,
    *,
    source_url: str = "",
    code_name: str = "Nebraska Revised Statutes",
) -> Optional[NormalizedStatute]:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return None
    soup = BeautifulSoup(html or "", "html.parser")
    body = None
    for name, kwargs in _SELECTORS:
        body = soup.find(name, **kwargs)
        if body is not None:
            break
    if body is None:
        body = soup.find("main") or soup.find("div", class_="card-body")
    if body is None:
        return None
    paras: list[str] = []
    heading = ""
    for element in body.find_all(["p", "div", "li", "h1", "h2", "h3"], recursive=True):
        classes = " ".join(element.get("class") or []).lower()
        if any(token in classes for token in ("history", "source", "fa-ul", "annotation")):
            continue
        if any(token in classes for token in ("heading", "section-head", "card-header", "statute-head")):
            heading = heading or _clean(element.get_text(" "))
            continue
        text = _clean(element.get_text(" "))
        if not text:
            continue
        if element.name in {"h1", "h2", "h3"}:
            heading = heading or text
            continue
        paras.append(text)
    full = _clean(" ".join(paras))
    if len(full) < 40:
        return None
    if _RESERVED.search(full[:200]) or _RESERVED.search(heading):
        return None
    query = parse_qs(urlparse(source_url).query)
    number = (query.get("statute") or [""])[0]
    if not number:
        h2 = body.find("h2") or body.find("h1")
        number = _clean(h2.get_text(" ")) if h2 else ""
    number = number.rstrip(".")
    if not number:
        return None
    name = heading if heading and heading != number else (paras[0] if paras else f"Section {number}")
    chapter = number.split("-", 1)[0]
    return NormalizedStatute(
        state_code="NE",
        state_name="Nebraska",
        statute_id=f"{code_name} § {number}",
        code_name=code_name,
        chapter_number=chapter,
        section_number=number,
        section_name=name[:200],
        full_text=full[:14000],
        source_url=source_url or f"{BASE}/laws/statutes.php?statute={number}",
        official_cite=f"Neb. Rev. Stat. § {number}",
        metadata=StatuteMetadata(),
        structured_data={
            "source_kind": "official_nebraska_statutes_html",
            "source_authority_class": "official",
            "discovery_method": "nebraskalegislature_statute_text",
            "skip_hydrate": True,
        },
    )


def configured_section_html_path() -> Optional[Path]:
    raw = str(os.environ.get("NEBRASKA_SECTION_HTML") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None


def configured_toc_html_path() -> Optional[Path]:
    raw = str(os.environ.get("NEBRASKA_TOC_HTML") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None


def configured_chapter_html_path() -> Optional[Path]:
    raw = str(os.environ.get("NEBRASKA_CHAPTER_HTML") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None


def parse_configured_toc_html() -> List[Tuple[str, str, str]]:
    path = configured_toc_html_path()
    if path is None:
        return []
    return chapter_links(path.read_text(encoding="utf-8", errors="replace"))


def parse_configured_chapter_html() -> List[Tuple[str, str, str]]:
    path = configured_chapter_html_path()
    if path is None:
        return []
    return section_links(path.read_text(encoding="utf-8", errors="replace"))


def is_nebraska_section_number(value: str) -> bool:
    token = str(value or "").strip()
    return bool(token) and bool(_SECTION_NUMBER_RE.match(token))


def chapter_links(html: str, *, base_url: str = f"{BASE}/laws/browse-statutes.php") -> List[Tuple[str, str, str]]:
    """Chapter rows from browse-statutes.php (includes ``76A``)."""

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    soup = BeautifulSoup(html or "", "html.parser")
    out: List[Tuple[str, str, str]] = []
    seen: set[str] = set()
    for anchor in soup.find_all("a", href=True):
        href = str(anchor.get("href") or "").strip()
        match = _CHAPTER_HREF_RE.search(href)
        if not match:
            continue
        number = match.group(1)
        if number in seen:
            continue
        seen.add(number)
        name = _clean(anchor.get_text(" ")) or f"Chapter {number}"
        out.append((number, name, urljoin(base_url, href)))
    return out


def section_links(html: str, *, base_url: str = f"{BASE}/laws/browse-chapters.php") -> List[Tuple[str, str, str]]:
    """Section hrefs from a chapter page (dotted ids such as ``25-2740.04``)."""

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    soup = BeautifulSoup(html or "", "html.parser")
    out: List[Tuple[str, str, str]] = []
    seen: set[str] = set()
    for anchor in soup.find_all("a", href=True):
        href = str(anchor.get("href") or "").strip()
        if "print=true" in href.lower():
            continue
        match = _SECTION_HREF_RE.search(href.split("&", 1)[0])
        if not match:
            continue
        number = match.group(1)
        if not is_nebraska_section_number(number) or number.lower() in seen:
            continue
        seen.add(number.lower())
        name = _clean(anchor.get_text(" ")) or f"Section {number}"
        out.append((number, name, urljoin(base_url, href)))
    return out


def chapter_structure(html: str, *, base_url: str = f"{BASE}/laws/browse-chapters.php") -> List[Dict[str, str]]:
    """Document-order sections with intervening ``ARTICLE N`` parents."""

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    soup = BeautifulSoup(html or "", "html.parser")
    out: List[Dict[str, str]] = []
    seen: set[str] = set()
    current_article = ""
    current_article_name = ""
    for element in soup.find_all(
        ["a", "h1", "h2", "h3", "h4", "h5", "h6", "strong", "b", "p", "li"]
    ):
        if element.name != "a":
            text = _clean(element.get_text(" "))
            if not text:
                continue
            match = _ARTICLE_HEADING_RE.match(text)
            if match:
                current_article = match.group(1)
                current_article_name = _clean(match.group(2) or "")
            continue
        href = str(element.get("href") or "").strip()
        if "print=true" in href.lower():
            continue
        match = _SECTION_HREF_RE.search(href.split("&", 1)[0])
        if not match:
            continue
        number = match.group(1)
        if not is_nebraska_section_number(number) or number.lower() in seen:
            continue
        seen.add(number.lower())
        out.append(
            {
                "section_number": number,
                "section_name": _clean(element.get_text(" ")) or f"Section {number}",
                "source_url": urljoin(base_url, href),
                "article_number": current_article,
                "article_name": current_article_name,
            }
        )
    return out
