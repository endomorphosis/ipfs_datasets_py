"""Official Idaho statutes section-page parser.

Adapted from Vaquill-AI/open-us-law ``id_bulk.parse`` (Apache-2.0).
Body lives in ``.pgbrk``; the first four child divs are breadcrumbs.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import List, Optional, Tuple

from .base_scraper import NormalizedStatute, StatuteMetadata

BASE = "https://legislature.idaho.gov"
_HEADER_DIV_COUNT = 4
_WS = re.compile(r"\s+")
_WRAPPER_CLASSES = ("vc-column-inner-wrapper", "vc-column-innner-wrapper")
_SUBCONTAINER_RE = re.compile(r"(?:PT\d|SCH)", re.IGNORECASE)
_RESERVED_KEYWORDS = ("[repealed]", "[expired]", "[reserved]", "redesignated")


def section_paragraphs(html: str) -> List[str]:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    soup = BeautifulSoup(html or "", "html.parser")
    container = soup.find(class_="pgbrk")
    if container is None:
        return []
    divs = container.find_all("div", recursive=False)[_HEADER_DIV_COUNT:]
    body: List[str] = []
    history: List[str] = []
    in_history = False
    for div in divs:
        text = _WS.sub(" ", (div.get_text(" ") or "").replace("\xa0", " ")).strip()
        if not text:
            continue
        if text.startswith("History:") or in_history:
            in_history = True
            history.append(text)
        else:
            body.append(text)
    return body + history


def statute_from_section_html(
    html: str,
    *,
    section_number: str,
    source_url: str,
    code_name: str = "Idaho Code",
    title_number: Optional[str] = None,
    chapter_number: Optional[str] = None,
) -> Optional[NormalizedStatute]:
    paras = section_paragraphs(html)
    body = " ".join(paras).strip()
    if len(body) < 40:
        return None
    heading = paras[0] if paras else f"Section {section_number}"
    return NormalizedStatute(
        state_code="ID",
        state_name="Idaho",
        statute_id=f"{code_name} § {section_number}",
        code_name=code_name,
        title_number=title_number,
        chapter_number=chapter_number,
        section_number=section_number,
        section_name=heading[:200],
        full_text=body[:14000],
        source_url=source_url,
        official_cite=f"Idaho Code § {section_number}",
        metadata=StatuteMetadata(),
        structured_data={
            "source_kind": "official_idaho_pgbrk",
            "source_authority_class": "official",
            "discovery_method": "legislature_idaho_pgbrk",
            "skip_hydrate": True,
        },
    )


def _clean_label(raw: str) -> str:
    return _WS.sub(" ", (raw or "").replace("\xa0", " ")).strip()


def _is_reserved_label(text: str) -> bool:
    lowered = (text or "").lower()
    return any(keyword in lowered for keyword in _RESERVED_KEYWORDS)


def _abs(href: str) -> str:
    token = str(href or "").strip()
    if token.startswith("http"):
        return token.rstrip("/") + "/"
    return BASE + token.rstrip("/") + "/"


def main_container(html: str):
    """Second Visual Composer wrapper (canonical spelling, then the three-n typo)."""

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return None
    soup = BeautifulSoup(html or "", "html.parser")
    wrappers = []
    for class_name in _WRAPPER_CLASSES:
        wrappers.extend(soup.find_all("div", class_=class_name))
    if len(wrappers) >= 2:
        return wrappers[1]
    if len(wrappers) == 1:
        return wrappers[0]
    return None


def title_rows(html: str) -> List[Tuple[str, str, str]]:
    """TOC rows: ``(title_number, title_name, title_url)``. Reserved titles skipped."""

    container = main_container(html)
    if container is None:
        return []
    out: List[Tuple[str, str, str]] = []
    for row in container.find_all("tr"):
        tds = row.find_all("td")
        if len(tds) < 3:
            continue
        anchor = tds[0].find("a", href=True)
        if anchor is None:
            continue
        label = _clean_label(tds[0].get_text(" "))
        words = label.split()
        if len(words) < 2 or words[0].upper() != "TITLE":
            continue
        number = words[1]
        name = f"{label} {_clean_label(tds[2].get_text(' '))}".strip()
        if _is_reserved_label(name):
            continue
        out.append((number, name, _abs(str(anchor.get("href") or ""))))
    return out


def chapter_rows(html: str) -> List[Tuple[str, str]]:
    """Title page rows: ``(chapter_number, chapter_url)``. Reserved chapters skipped."""

    container = main_container(html)
    if container is None:
        return []
    out: List[Tuple[str, str]] = []
    for row in container.find_all("tr"):
        tds = row.find_all("td")
        if len(tds) < 3:
            continue
        anchor = tds[0].find("a", href=True)
        if anchor is None:
            continue
        label = _clean_label(tds[0].get_text(" "))
        words = label.split()
        if len(words) < 2 or words[0].upper() != "CHAPTER":
            continue
        name = f"{label} {_clean_label(tds[2].get_text(' '))}".strip()
        if _is_reserved_label(name):
            continue
        out.append((words[1], _abs(str(anchor.get("href") or ""))))
    return out


def section_rows(html: str) -> Tuple[List[Tuple[str, str, str]], List[str]]:
    """Chapter page: ``(sections, subcontainer_urls)``.

    Sections are ``(number, description, url)``. Sub-chapter ``SCH`` and part
    ``PTn`` URLs flatten into the parent chapter (Vaquill Title 15 UPC walk).
    """

    container = main_container(html)
    if container is None:
        return [], []
    sections: List[Tuple[str, str, str]] = []
    subcontainers: List[str] = []
    for row in container.find_all("tr"):
        tds = row.find_all("td")
        if len(tds) < 3:
            continue
        label = _clean_label(tds[0].get_text(" "))
        if not label:
            continue
        anchor = tds[0].find("a", href=True)
        if anchor is None:
            continue
        href = str(anchor.get("href") or "")
        if "SECT" in href.upper():
            desc = _clean_label(tds[2].get_text(" "))
            if _is_reserved_label(f"{label} {desc}"):
                continue
            sections.append((label, desc, _abs(href)))
        elif _SUBCONTAINER_RE.search(href):
            subcontainers.append(_abs(href))
    return sections, subcontainers


def configured_toc_html_path() -> Optional[Path]:
    raw = str(os.environ.get("IDAHO_TOC_HTML") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None


def parse_configured_toc_html() -> List[Tuple[str, str, str]]:
    path = configured_toc_html_path()
    if path is None:
        return []
    return title_rows(path.read_text(encoding="utf-8", errors="replace"))
