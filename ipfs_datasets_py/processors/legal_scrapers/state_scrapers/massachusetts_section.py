"""Official Massachusetts General Laws section HTML parser.

Adapted from Vaquill-AI/open-us-law ``scrapeMA.py`` (Apache-2.0).
Body lives in ``div.content``; navigation and session-law addenda are dropped.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import List, Optional, Tuple
from urllib.parse import urlparse

from .base_scraper import NormalizedStatute, StatuteMetadata

BASE = "https://malegislature.gov"
_ADDENDUM_RE = re.compile(
    r"^\s*\(?(?:Added|Amended|Repealed|St\.|P\.L\.|L\.|Acts|R\.L\.)", re.IGNORECASE
)
_CHAPTER_RE = re.compile(r"/Chapter(?P<chapter>[A-Za-z0-9.]+)", re.IGNORECASE)
_SECTION_RE = re.compile(r"/Section(?P<section>[A-Za-z0-9.]+)", re.IGNORECASE)
_CHAPTER_HREF_RE = re.compile(
    r"/Laws/GeneralLaws/Part[IVXLCDM]+/Title[IVXLCDM]+[A-Z]?/Chapter([0-9]+[A-Za-z]?)/?$",
    re.IGNORECASE,
)
_WS = re.compile(r"\s+")


def chapters_for_title_url(part_id: str, title_id: str, code: str) -> str:
    return (
        f"{BASE}/Laws/GeneralLaws/GetChaptersForTitle"
        f"?partId={part_id}&titleId={title_id}&code={code}"
    )


def extract_chapter_links(fragment_html: str) -> List[Tuple[str, str]]:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    soup = BeautifulSoup(fragment_html or "", "html.parser")
    out: List[Tuple[str, str]] = []
    seen = set()
    for anchor in soup.find_all("a", href=True):
        path = urlparse(str(anchor.get("href") or "")).path
        match = _CHAPTER_HREF_RE.search(path)
        if not match:
            continue
        number = match.group(1)
        if number in seen:
            continue
        seen.add(number)
        out.append((f"{BASE}{path}", number))
    return out


def _is_navigation(text: str) -> bool:
    lower = text.lower()
    return any(
        token in lower
        for token in (
            "skip to content",
            "skip to main",
            "terms of use",
            "privacy policy",
            "print page",
            "use mylegislature",
            "general court of",
        )
    )


def parse_massachusetts_section_html(
    html: str,
    *,
    source_url: str,
    code_name: str = "Massachusetts General Laws",
) -> Optional[NormalizedStatute]:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return None
    soup = BeautifulSoup(html or "", "html.parser")
    body = (
        soup.find(class_="content")
        or soup.find(id="content")
        or soup.find("main")
        or soup
    )
    paras: List[str] = []
    for para in body.find_all("p"):
        text = _WS.sub(" ", para.get_text(" ")).strip()
        if not text or _is_navigation(text) or _ADDENDUM_RE.match(text):
            continue
        split = re.split(
            r"\s+(?=\((?:Added|Amended|Repealed|St\.|P\.L\.|L\.|Acts|R\.L\.)\b)",
            text,
            maxsplit=1,
            flags=re.IGNORECASE,
        )
        body_part = split[0].strip()
        if body_part:
            paras.append(body_part)
    full = " ".join(paras).strip()
    if len(full) < 20:
        return None
    ch_match = _CHAPTER_RE.search(source_url)
    sec_match = _SECTION_RE.search(source_url)
    chapter = ch_match.group("chapter") if ch_match else ""
    section = sec_match.group("section") if sec_match else ""
    heading = soup.select_one("h2.genLawHeading")
    name = _WS.sub(" ", heading.get_text(" ")).strip() if heading else f"Section {section}"
    return NormalizedStatute(
        state_code="MA",
        state_name="Massachusetts",
        statute_id=f"{code_name} ch. {chapter} § {section}".strip(),
        code_name=code_name,
        chapter_number=chapter or None,
        section_number=section,
        section_name=name[:200],
        full_text=full[:14000],
        source_url=source_url or f"{BASE}/Laws/GeneralLaws",
        official_cite=f"Mass. Gen. Laws ch. {chapter}, § {section}",
        metadata=StatuteMetadata(),
        structured_data={
            "source_kind": "official_massachusetts_content_html",
            "source_authority_class": "official",
            "discovery_method": "malegislature_general_laws_content",
            "skip_hydrate": True,
        },
    )


def configured_section_html_path() -> Optional[Path]:
    raw = str(os.environ.get("MASSACHUSETTS_SECTION_HTML") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None
