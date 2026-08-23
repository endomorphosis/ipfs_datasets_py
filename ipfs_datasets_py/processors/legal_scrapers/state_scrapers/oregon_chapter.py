"""Official Oregon Revised Statutes chapter HTML parser.

Adapted from the ``163.005 Title.`` chapter walk in ``oregon.py``.
Vaquill lists Oregon as in-progress; this is the official HTML-structure
parser, env-gated to a local dump.

Local dump: ``OREGON_CHAPTER_HTML``.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import List, Optional, Tuple

from .base_scraper import NormalizedStatute, StatuteMetadata

BASE = "https://www.oregonlegislature.gov"
ORS_LINK_RE = re.compile(r"ors(\d{3}[a-z]?)\.html$", re.IGNORECASE)
_RESERVED = re.compile(r"\b(repealed|reserved|expired|renumbered)\b", re.IGNORECASE)
_HISTORY_RE = re.compile(r"^\s*(History|Note|Or\.?\s+Laws)\b", re.IGNORECASE)
_WS = re.compile(r"\s+")


def _clean(text: str) -> str:
    return _WS.sub(" ", (text or "").replace("\xa0", " ")).strip()


def chapter_slug_from_url(url: str) -> str:
    match = ORS_LINK_RE.search(str(url or ""))
    return match.group(1).lower() if match else ""


def chapter_number_display(chapter_slug: str) -> str:
    digits = "".join(ch for ch in chapter_slug if ch.isdigit())
    suffix = "".join(ch for ch in chapter_slug if ch.isalpha())
    if not digits:
        return chapter_slug
    return f"{int(digits)}{suffix}"


def section_start_regex(chapter_display: str) -> re.Pattern[str]:
    return re.compile(
        rf"^\s*({re.escape(chapter_display)}\.\d{{3}}[a-z]?)\b\s*(.*)$",
        re.IGNORECASE,
    )


def parse_oregon_chapter_html(
    html: str,
    *,
    source_url: str = "",
    code_name: str = "Oregon Revised Statutes",
    max_statutes: Optional[int] = None,
) -> List[NormalizedStatute]:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    soup = BeautifulSoup(html or "", "html.parser")
    for tag in soup(["script", "style", "nav", "header", "footer", "noscript", "form"]):
        tag.decompose()
    lines = [_clean(line) for line in soup.get_text("\n", strip=True).splitlines()]
    lines = [line for line in lines if line]
    slug = chapter_slug_from_url(source_url)
    chapter_display = chapter_number_display(slug) if slug else ""
    if not chapter_display:
        for line in lines[:40]:
            match = re.match(r"^chapter\s+(\d+[a-z]?)\b", line, flags=re.IGNORECASE)
            if match:
                chapter_display = match.group(1)
                break
    if not chapter_display:
        return []
    start_re = section_start_regex(chapter_display)
    statutes: List[NormalizedStatute] = []
    current_id = ""
    current_title = ""
    buffer: List[str] = []

    def flush() -> None:
        nonlocal current_id, current_title, buffer
        if not current_id:
            return
        if _RESERVED.search(current_title):
            current_id = ""
            current_title = ""
            buffer = []
            return
        paras = [part for part in buffer if part and not _HISTORY_RE.match(part)]
        body = _clean(" ".join(paras))
        if len(body) < 40:
            current_id = ""
            current_title = ""
            buffer = []
            return
        if max_statutes is not None and len(statutes) >= int(max_statutes):
            current_id = ""
            return
        number = current_id.lower()
        link = source_url or f"{BASE}/bills_laws/ors/ors{slug or chapter_display}.html"
        statutes.append(
            NormalizedStatute(
                state_code="OR",
                state_name="Oregon",
                statute_id=f"ORS {number}",
                code_name=code_name,
                title_number=chapter_display,
                chapter_number=chapter_display,
                section_number=number,
                section_name=(current_title or f"ORS {number}")[:200],
                full_text=body[:14000],
                source_url=f"{link.split('#')[0]}#section-{number}",
                official_cite=f"Or. Rev. Stat. § {number}",
                metadata=StatuteMetadata(),
                structured_data={
                    "source_kind": "official_oregon_revised_statutes_html",
                    "source_authority_class": "official",
                    "discovery_method": "official_ors_chapter_html",
                    "skip_hydrate": True,
                },
            )
        )
        current_id = ""
        current_title = ""
        buffer = []

    for line in lines:
        match = start_re.match(line)
        if match:
            flush()
            current_id = match.group(1)
            current_title = _clean(match.group(2) or "")
            buffer = []
            continue
        if current_id:
            buffer.append(line)
    flush()
    return statutes


def configured_chapter_html_path() -> Optional[Path]:
    raw = str(os.environ.get("OREGON_CHAPTER_HTML") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None


def configured_index_html_path() -> Optional[Path]:
    raw = str(os.environ.get("OREGON_ORS_INDEX_HTML") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None


def parse_configured_index_html() -> List[Tuple[str, str, str]]:
    path = configured_index_html_path()
    if path is None:
        return []
    return ors_chapter_links(path.read_text(encoding="utf-8", errors="replace"))


def ors_chapter_links(html: str, *, base_url: str = f"{BASE}/bills_laws/ors/") -> List[Tuple[str, str, str]]:
    """Index ``ors163.html`` / ``ors163a.html`` chapter rows."""

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
        slug = chapter_slug_from_url(href)
        if not slug or slug in seen:
            continue
        seen.add(slug)
        number = chapter_number_display(slug)
        name = _clean(anchor.get_text(" ")) or f"ORS Chapter {number}"
        out.append((number, name, urljoin(base_url, href)))
    return out
