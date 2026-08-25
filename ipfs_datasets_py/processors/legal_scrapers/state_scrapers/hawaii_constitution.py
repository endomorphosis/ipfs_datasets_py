"""Official Hawaii Constitution HTML parser.

Adapted from Vaquill-AI/open-us-law ``ingest_state_constitutions.scrape_hi``
(Apache-2.0). capitol.hawaii.gov ``05-CONST`` pages use centered
``RegularParagraphs`` for article headings and body ``Section [N].`` markers.
A sequential Next link that leaves the ``05-CONST`` directory is a statute
chapter, not more constitution text.

Local dump: ``HAWAII_CONSTITUTION_HTML``.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import List, Optional
from urllib.parse import urljoin

from .base_scraper import NormalizedStatute, StatuteMetadata

HI_CONST_TOC = "https://capitol.hawaii.gov/hrscurrent/Vol01_Ch0001-0042F/05-CONST/CONST_.htm"
_HI_ARTICLE_RE = re.compile(r"^ARTICLE\s+([IVXLC]+)$")
_HI_SECTION_RE = re.compile(r"Section\s*\[?(\d+(?:\.\d+)?[A-Za-z]?)\]?\s*\.\s*(.*)", re.DOTALL)
_HI_NEXT_RE = re.compile(r"^\s*next\s*$", re.IGNORECASE)
_RESERVED = re.compile(r"\b(repealed|reserved|expired|renumbered)\b", re.IGNORECASE)
_WS = re.compile(r"\s+")


def constitution_dir_prefix(url: str) -> str:
    return (url or "").rsplit("/", 1)[0] + "/"


def next_in_constitution_dir(html: str, current_url: str) -> Optional[str]:
    """Return the Next URL only if it stays under the current 05-CONST dir."""

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return None
    soup = BeautifulSoup(html or "", "html.parser")
    nxt = None
    for anchor in soup.find_all("a", href=True):
        if _HI_NEXT_RE.match(anchor.get_text(strip=True)):
            nxt = urljoin(current_url, str(anchor.get("href") or ""))
            break
    if not nxt:
        return None
    prefix = constitution_dir_prefix(current_url)
    if nxt.startswith(prefix):
        return nxt
    return None


def parse_hawaii_constitution_html(
    html: str,
    *,
    code_name: str = "Hawaii Constitution",
    source_url: str = "",
    max_statutes: Optional[int] = None,
) -> List[NormalizedStatute]:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    soup = BeautifulSoup(html or "", "html.parser")
    heading_lines: List[str] = []
    body_paras: List[str] = []
    for para in soup.find_all("p", class_="RegularParagraphs"):
        text = para.get_text(" ", strip=True).replace("\xa0", " ").strip()
        if not text:
            continue
        is_centered = para.get("align") == "center" or "center" in (para.get("style") or "")
        if is_centered and not body_paras:
            heading_lines.append(text)
        else:
            body_paras.append(text)
    article_id = "I"
    for line in heading_lines:
        match = _HI_ARTICLE_RE.match(line)
        if match:
            article_id = match.group(1)
            break
    body_text = _WS.sub(" ", " ".join(body_paras)).strip()
    sec_match = _HI_SECTION_RE.match(body_text)
    if not sec_match:
        return []
    number = sec_match.group(1)
    raw = _WS.sub(" ", sec_match.group(2)).strip()
    if len(raw) < 40:
        return []
    if _RESERVED.search(raw[:160]):
        return []
    if max_statutes is not None and int(max_statutes) < 1:
        return []
    cite = f"Haw. Const. art. {article_id}, § {number}"
    return [
        NormalizedStatute(
            state_code="HI",
            state_name="Hawaii",
            statute_id=cite,
            code_name=code_name,
            title_number=article_id,
            section_number=number,
            section_name=(raw.split(".", 1)[0] or f"Section {number}")[:200],
            full_text=raw[:14000],
            source_url=source_url or HI_CONST_TOC,
            official_cite=cite,
            metadata=StatuteMetadata(),
            structured_data={
                "source_kind": "official_hawaii_constitution_html",
                "source_authority_class": "official",
                "discovery_method": "capitol_hawaii_gov_05_const",
                "article_id": article_id,
                "skip_hydrate": True,
            },
        )
    ]


def configured_constitution_html_path() -> Optional[Path]:
    raw = str(os.environ.get("HAWAII_CONSTITUTION_HTML") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None
