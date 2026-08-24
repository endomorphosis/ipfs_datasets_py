"""Official Alaska LAA print-fragment parser.

Adapted from Vaquill-AI/open-us-law ``scrapeAK.py`` (Apache-2.0).
Body lives in ``div.statute``; the heading ``<b>`` is dropped, ``<br><br>``
splits paragraphs, and ``[Repealed`` sections are skipped.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import List, Optional, Tuple

from .base_scraper import NormalizedStatute, StatuteMetadata

BASE = "https://www.akleg.gov/basis/statutes.asp"
_SEC_RE = re.compile(
    r"Sec\.\s*(?P<num>\d{2}\.\d{2}\.\d{3}[A-Za-z]?)\.\s*(?P<head>.*)$",
    re.IGNORECASE,
)
_REPEALED = re.compile(r"\[\s*Repealed\b", re.IGNORECASE)
_RESERVED = re.compile(r"\b(repealed|reserved|expired|renumbered)\b", re.IGNORECASE)
_WS = re.compile(r"\s+")


def print_url(section_number: str) -> str:
    return f"{BASE}?media=print&secStart={section_number}&secEnd={section_number}"


def toc_url(title_or_chapter: str) -> str:
    token = str(title_or_chapter or "").strip()
    if token.isdigit():
        token = f"{int(token):02d}"
    return f"{BASE}?media=js&type=TOC&title={token}"


def xref_url(section_number: str) -> str:
    return f"{BASE}?type=xRef&sec={section_number}"


def chapter_toc_links(html: str) -> List[Tuple[str, str]]:
    """Title TOC fragments: ``loadTOC(\"01.05\")`` chapter rows."""

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    soup = BeautifulSoup(html or "", "html.parser")
    out: List[Tuple[str, str]] = []
    seen: set[str] = set()
    for link in soup.find_all("a", onclick=True):
        match = re.search(r'loadTOC\("(\d{2}\.\d{2})"\)', str(link.get("onclick") or ""))
        if not match:
            continue
        number = match.group(1)
        if number in seen:
            continue
        seen.add(number)
        out.append((number, _clean(link.get_text(" ")) or f"Chapter {number}"))
    return out


def section_toc_links(html: str) -> List[Tuple[str, str]]:
    """Chapter TOC fragments: ``#01.05.006`` section anchors."""

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    soup = BeautifulSoup(html or "", "html.parser")
    out: List[Tuple[str, str]] = []
    seen: set[str] = set()
    for link in soup.find_all("a", href=True):
        match = re.search(r"#(\d{2}\.\d{2}\.\d{3}[A-Za-z]?)$", str(link.get("href") or ""))
        if not match:
            continue
        number = match.group(1)
        if number in seen:
            continue
        seen.add(number)
        out.append((number, _clean(link.get_text(" ")) or f"Sec. {number}"))
    return out


def _clean(text: str) -> str:
    return _WS.sub(" ", (text or "").replace("\xa0", " ")).strip()


def parse_alaska_statute_html(
    html: str,
    *,
    code_name: str = "Alaska Statutes",
    max_statutes: Optional[int] = None,
) -> List[NormalizedStatute]:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    soup = BeautifulSoup(html or "", "html.parser")
    statutes: List[NormalizedStatute] = []
    for div in soup.find_all("div", class_="statute"):
        if max_statutes is not None and len(statutes) >= int(max_statutes):
            break
        clone = BeautifulSoup(str(div), "html.parser").find("div")
        if clone is None:
            continue
        heading = ""
        head_b = clone.find("b")
        if head_b is not None:
            heading = _clean(head_b.get_text(" "))
            head_b.decompose()
        if _REPEALED.search(heading) or _RESERVED.search(heading):
            continue
        for br in clone.find_all("br"):
            br.replace_with("\n")
        chunks = [_clean(part) for part in re.split(r"\n\s*\n+", clone.get_text(" "))]
        body = _clean(" ".join(part for part in chunks if part))
        if _REPEALED.search(body) or len(body) < 40:
            continue
        match = _SEC_RE.search(heading) or _SEC_RE.search(body)
        number = match.group("num") if match else ""
        name = match.group("head").strip() if match else heading[:200]
        if not number:
            continue
        parts = number.split(".")
        statutes.append(
            NormalizedStatute(
                state_code="AK",
                state_name="Alaska",
                statute_id=f"{code_name} § {number}",
                code_name=code_name,
                title_number=parts[0] if parts else None,
                chapter_number=parts[1] if len(parts) > 1 else None,
                section_number=number,
                section_name=(name or f"Section {number}")[:200],
                full_text=body[:14000],
                source_url=f"{BASE}#{number}",
                official_cite=f"Alaska Stat. § {number}",
                metadata=StatuteMetadata(),
                structured_data={
                    "source_kind": "official_alaska_statute_print",
                    "source_authority_class": "official",
                    "discovery_method": "akleg_statute_div_print",
                    "skip_hydrate": True,
                },
            )
        )
    return statutes


def configured_section_html_path() -> Optional[Path]:
    raw = str(os.environ.get("ALASKA_SECTION_HTML") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None


def configured_toc_html_path() -> Optional[Path]:
    raw = str(os.environ.get("ALASKA_TOC_HTML") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None


def parse_configured_toc_html() -> List[Tuple[str, str]]:
    path = configured_toc_html_path()
    if path is None:
        return []
    return chapter_toc_links(path.read_text(encoding="utf-8", errors="replace"))


def configured_section_toc_html_path() -> Optional[Path]:
    raw = str(os.environ.get("ALASKA_SECTION_TOC_HTML") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None


def parse_configured_section_toc_html() -> List[Tuple[str, str]]:
    path = configured_section_toc_html_path()
    if path is None:
        return []
    return section_toc_links(path.read_text(encoding="utf-8", errors="replace"))
