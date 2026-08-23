"""Official Kansas Statutes section HTML parser.

Adapted from Vaquill-AI/open-us-law ``scrapeKS.py`` (Apache-2.0).
Body lives in ``.statute-body`` table[1] ``p.p_pt`` paragraphs; table[2]
is history and is dropped. ``Accept-Encoding`` must omit Brotli because
kslegislature.gov otherwise serves undecodable ``br`` payloads.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Optional

from .base_scraper import NormalizedStatute, StatuteMetadata

SESSION = "b2025_26"
BASE = f"https://www.kslegislature.gov/{SESSION}/laws"
_RESERVED = re.compile(r"\b(repealed|reserved|expired|renumbered)\b", re.IGNORECASE)
_KSA_RE = re.compile(r"^([\da-z]+-[\da-z]+(?:-[\da-z]+)*)", re.IGNORECASE)
_WS = re.compile(r"\s+")
BROTLI_SAFE_ACCEPT_ENCODING = "gzip, deflate"


def _clean(text: str) -> str:
    return _WS.sub(" ", (text or "").replace("\xa0", " ").replace("\u2002", " ")).strip()


def parse_kansas_section_html(
    html: str,
    *,
    source_url: str,
    section_number: str = "",
    code_name: str = "Kansas Statutes",
) -> Optional[NormalizedStatute]:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return None
    soup = BeautifulSoup(html or "", "html.parser")
    body_node = soup.find(class_="statute-body")
    if body_node is None:
        return None
    tables = body_node.find_all("table")
    if len(tables) < 2:
        return None
    cell = tables[1].find("td")
    if cell is None:
        return None
    paras = [_clean(p.get_text(" ")) for p in cell.find_all("p")]
    paras = [p for p in paras if p]
    if not paras:
        fallback = _clean(cell.get_text(" "))
        if fallback:
            paras = [fallback]
    body = _clean(" ".join(paras))
    if len(body) < 40:
        return None
    number = section_number
    if not number:
        listed = soup.select_one(".stat_5f_number")
        number = _clean(listed.get_text(" ")).rstrip(".") if listed else ""
    if not number:
        match = _KSA_RE.match(body)
        number = match.group(1) if match else ""
    if not number:
        return None
    caption_node = soup.select_one(".stat_5f_caption")
    caption = _clean(caption_node.get_text(" ")) if caption_node else paras[0][:200]
    if _RESERVED.search(caption) or _RESERVED.search(body[:160]):
        return None
    chapter = number.split("-", 1)[0]
    return NormalizedStatute(
        state_code="KS",
        state_name="Kansas",
        statute_id=f"{code_name} § {number}",
        code_name=code_name,
        chapter_number=chapter,
        section_number=number,
        section_name=caption[:200],
        full_text=body[:14000],
        source_url=source_url or f"{BASE}/",
        official_cite=f"K.S.A. § {number}",
        metadata=StatuteMetadata(),
        structured_data={
            "source_kind": "official_kansas_statute_body",
            "source_authority_class": "official",
            "discovery_method": "kslegislature_statute_body_table",
            "skip_hydrate": True,
        },
    )


def configured_section_html_path() -> Optional[Path]:
    raw = str(os.environ.get("KANSAS_SECTION_HTML") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None
