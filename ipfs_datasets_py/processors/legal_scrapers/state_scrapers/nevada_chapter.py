"""Official Nevada Revised Statutes chapter HTML parser.

``leg.state.nv.us/NRS/NRS-XXX.html`` publishes every section inline with
``span.Section`` / ``span.Leadline``. History paragraphs are dropped.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import List, Optional, Tuple

from .base_scraper import NormalizedStatute, StatuteMetadata

BASE = "https://www.leg.state.nv.us/NRS"
_SECTION_NUM_RE = re.compile(r"^\d+\.\d+[A-Za-z0-9.]*$")
_RESERVED = re.compile(r"\b(repealed|reserved|expired|renumbered)\b", re.IGNORECASE)
_HISTORY_RE = re.compile(r"^\s*(History|Added|NRS\s+\d|Stats\.)\b", re.IGNORECASE)
_WS = re.compile(r"\s+")


def _clean(text: str) -> str:
    return _WS.sub(" ", (text or "").replace("\xa0", " ")).strip()


def parse_nevada_chapter_html(
    html: str,
    *,
    source_url: str = "",
    code_name: str = "Nevada Revised Statutes",
    max_statutes: Optional[int] = None,
) -> List[NormalizedStatute]:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    soup = BeautifulSoup(html or "", "html.parser")
    statutes: List[NormalizedStatute] = []
    current_number = ""
    current_name = ""
    current_anchor = ""
    body_parts: List[str] = []

    def flush() -> None:
        nonlocal current_number, current_name, current_anchor, body_parts
        if not current_number:
            return
        if _RESERVED.search(current_name):
            current_number = ""
            current_name = ""
            current_anchor = ""
            body_parts = []
            return
        paras = [part for part in body_parts if part and not _HISTORY_RE.match(part)]
        body = _clean(" ".join(paras))
        if len(body) < 40:
            current_number = ""
            current_name = ""
            current_anchor = ""
            body_parts = []
            return
        if max_statutes is not None and len(statutes) >= int(max_statutes):
            current_number = ""
            return
        link = source_url or BASE
        if current_anchor:
            link = f"{link.split('#')[0]}#{current_anchor}"
        statutes.append(
            NormalizedStatute(
                state_code="NV",
                state_name="Nevada",
                statute_id=f"{code_name} § {current_number}",
                code_name=code_name,
                section_number=current_number,
                section_name=(current_name or f"NRS {current_number}")[:200],
                full_text=body[:14000],
                source_url=link,
                official_cite=f"Nev. Rev. Stat. § {current_number}",
                metadata=StatuteMetadata(),
                structured_data={
                    "source_kind": "official_nevada_revised_statutes_html",
                    "source_authority_class": "official",
                    "discovery_method": "nrs_section_leadline",
                    "skip_hydrate": True,
                },
            )
        )
        current_number = ""
        current_name = ""
        current_anchor = ""
        body_parts = []

    for paragraph in soup.find_all("p"):
        if max_statutes is not None and len(statutes) >= int(max_statutes):
            break
        span = paragraph.find("span", class_="Section")
        if span is not None:
            flush()
            number = _clean(span.get_text(" "))
            if not _SECTION_NUM_RE.match(number):
                continue
            lead = paragraph.find("span", class_="Leadline")
            current_number = number
            current_name = _clean(lead.get_text(" ")) if lead else ""
            named = paragraph.find("a", attrs={"name": True})
            current_anchor = str(named.get("name") or number) if named is not None else number
            rest = _clean(paragraph.get_text(" "))
            if rest:
                body_parts.append(rest)
            continue
        if current_number:
            text = _clean(paragraph.get_text(" "))
            if text:
                body_parts.append(text)
    flush()
    return statutes


def configured_chapter_html_path() -> Optional[Path]:
    raw = str(os.environ.get("NEVADA_CHAPTER_HTML") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None


_NRS_INDEX_RE = re.compile(r"NRS-(\d+[A-Za-z]?)\.html?$", re.IGNORECASE)


def nrs_index_links(html: str, *, base_url: str = f"{BASE}/") -> List[Tuple[str, str, str]]:
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
        number = str(int(match.group(1))) if match.group(1).isdigit() else match.group(1)
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
