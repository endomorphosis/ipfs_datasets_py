"""Official Arkansas Code section HTML parser.

Adapted from the arkleg ``div#content`` / ``5-10-101. heading`` walk in
``arkansas.py``. Vaquill lists Arkansas as in-progress; this is the
official HTML-structure parser, env-gated to a local dump.

Local dump: ``ARKANSAS_SECTION_HTML``.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import List, Optional, Tuple

from .base_scraper import NormalizedStatute, StatuteMetadata

BASE = "https://www.arkleg.state.ar.us"
_HEAD_RE = re.compile(
    r"(?m)^\s*(?:§\s*)?(?P<section>\d+-\d+(?:-\d+)?(?:\.\d+)?)\s*[.–—-]\s*(?P<title>.+)$"
)
_SECTION_HREF_RE = re.compile(
    r"/ArkansasCode/(?P<section>\d+-\d+(?:-\d+)?(?:\.\d+)?)/?$",
    re.IGNORECASE,
)
_TITLE_QUERY_RE = re.compile(r"[?&](?:title|codeTitle)=(\d{1,2})\b", re.IGNORECASE)
_RESERVED = re.compile(r"\b(repealed|reserved|expired|renumbered)\b", re.IGNORECASE)
_WS = re.compile(r"\s+")


def _clean(text: str) -> str:
    return _WS.sub(" ", (text or "").replace("\xa0", " ")).strip()


def title_url(number: str) -> str:
    return f"{BASE}/ArkansasCode/?title={str(number).strip()}"


def section_url(number: str) -> str:
    return f"{BASE}/ArkansasCode/{str(number).strip()}/"


def title_links(html: str, *, base_url: str = f"{BASE}/ArkansasCode/") -> List[Tuple[str, str, str]]:
    """Index ``?title=5`` / ``codeTitle=5`` rows."""

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    soup = BeautifulSoup(html or "", "html.parser")
    out: List[Tuple[str, str, str]] = []
    seen: set[str] = set()
    for anchor in soup.find_all("a", href=True):
        href = str(anchor.get("href") or "")
        match = _TITLE_QUERY_RE.search(href)
        if not match:
            continue
        number = str(int(match.group(1)))
        if number in seen:
            continue
        seen.add(number)
        name = _clean(anchor.get_text(" ")) or f"Title {number}"
        out.append((number, name, title_url(number)))
    return out


def section_links(html: str, *, base_url: str = f"{BASE}/ArkansasCode/") -> List[Tuple[str, str, str]]:
    """TOC ``/ArkansasCode/5-10-101/`` rows."""

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    soup = BeautifulSoup(html or "", "html.parser")
    out: List[Tuple[str, str, str]] = []
    seen: set[str] = set()
    for anchor in soup.find_all("a", href=True):
        href = str(anchor.get("href") or "").strip()
        match = _SECTION_HREF_RE.search(href)
        if not match:
            continue
        number = match.group("section")
        if number in seen:
            continue
        seen.add(number)
        name = _clean(anchor.get_text(" ")) or f"Section {number}"
        out.append((number, name, section_url(number)))
    return out


def parse_arkansas_section_html(
    html: str,
    *,
    source_url: str = "",
    code_name: str = "Arkansas Code",
    max_statutes: Optional[int] = None,
) -> List[NormalizedStatute]:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    soup = BeautifulSoup(html or "", "html.parser")
    content = (
        soup.select_one("div#content")
        or soup.select_one("div.content")
        or soup.select_one("main")
        or soup.select_one("article")
        or soup.find("body")
        or soup
    )
    for tag in content.find_all(["script", "style", "nav", "header", "footer", "noscript", "form"]):
        tag.decompose()
    text = content.get_text("\n", strip=True)
    matches = list(_HEAD_RE.finditer(text))
    statutes: List[NormalizedStatute] = []
    for index, match in enumerate(matches):
        if max_statutes is not None and len(statutes) >= int(max_statutes):
            break
        number = match.group("section")
        heading = match.group("title").strip()
        if _RESERVED.search(heading):
            continue
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        body = _clean(text[start:end])
        if len(body) < 40:
            continue
        parts = number.split("-")
        statutes.append(
            NormalizedStatute(
                state_code="AR",
                state_name="Arkansas",
                statute_id=f"{code_name} § {number}",
                code_name=code_name,
                title_number=parts[0] if parts else None,
                chapter_number=parts[1] if len(parts) > 1 else None,
                section_number=number,
                section_name=heading[:200],
                full_text=body,
                source_url=source_url or f"{BASE}/ArkansasCode/{number}/",
                official_cite=f"Ark. Code Ann. § {number}",
                metadata=StatuteMetadata(),
                structured_data={
                    "source_kind": "official_arkansas_code_html",
                    "source_authority_class": "official",
                    "discovery_method": "arkleg_content_heading",
                    "skip_hydrate": True,
                },
            )
        )
    return statutes


def configured_section_html_path() -> Optional[Path]:
    raw = str(os.environ.get("ARKANSAS_SECTION_HTML") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None


def configured_toc_html_path() -> Optional[Path]:
    raw = str(os.environ.get("ARKANSAS_TOC_HTML") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None


def parse_configured_toc_html() -> List[Tuple[str, str, str]]:
    path = configured_toc_html_path()
    if path is None:
        return []
    return title_links(path.read_text(encoding="utf-8", errors="replace"))
