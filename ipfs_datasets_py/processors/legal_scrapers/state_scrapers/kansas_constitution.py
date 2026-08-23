"""Official Kansas Constitution page-content parser.

Adapted from Vaquill-AI/open-us-law ``ingest_state_constitutions.scrape_ks``
(Apache-2.0). sos.ks.gov publications pages put the body in
``div.page-content``. Walk every ``p`` (not just ``constitution-paragraph``)
so classless subsection paragraphs stay attached. Ordinance pages split the
trailing Preamble into article ``0``.

Local dump: ``KANSAS_CONSTITUTION_HTML``.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import List, Optional, Tuple

from .base_scraper import NormalizedStatute, StatuteMetadata

KS_CONST_BASE = "https://sos.ks.gov/publications/kansas-constitution"
_KS_ROMAN = (
    "I", "II", "III", "IV", "V", "VI", "VII", "VIII",
    "IX", "X", "XI", "XII", "XIII", "XIV", "XV",
)
_KS_SECTION_HEAD_RE = re.compile(r"^§\s*(\d+[A-Za-z]?)\.\s*(.*)", re.DOTALL)
_KS_PREAMBLE_TRIGGER_RE = re.compile(r"^we,\s+the\s+people\s+of\s+kansas", re.IGNORECASE)
_RESERVED = re.compile(r"\b(repealed|reserved|expired|renumbered)\b", re.IGNORECASE)
_WS = re.compile(r"\s+")


def _article_id_from_title(title: str) -> str:
    text = title or ""
    if re.search(r"bill of rights", text, re.I):
        return "BOR"
    if re.search(r"ordinance", text, re.I):
        return "ORD"
    if re.search(r"schedule", text, re.I):
        return "SCHEDULE"
    numbered = re.search(r"article\s+(\d+)", text, re.I)
    if numbered:
        index = int(numbered.group(1))
        if 1 <= index <= len(_KS_ROMAN):
            return _KS_ROMAN[index - 1]
        return str(index)
    roman = re.search(r"article\s+([IVXLC]+)", text, re.I)
    return roman.group(1) if roman else "I"


def _row(art_id: str, number: str, body: str, code_name: str) -> Optional[NormalizedStatute]:
    raw = _WS.sub(" ", body).strip()
    if len(raw) < 40:
        return None
    if _RESERVED.search(raw[:160]):
        return None
    cite = (
        "Kan. Const. Preamble"
        if art_id == "0"
        else f"Kan. Const. art. {art_id}, § {number}"
    )
    return NormalizedStatute(
        state_code="KS",
        state_name="Kansas",
        statute_id=cite,
        code_name=code_name,
        title_number=art_id,
        section_number=number,
        section_name=(raw.split(".", 1)[0] or f"Section {number}")[:200],
        full_text=raw[:14000],
        source_url=KS_CONST_BASE,
        official_cite=cite,
        metadata=StatuteMetadata(),
        structured_data={
            "source_kind": "official_kansas_constitution_html",
            "source_authority_class": "official",
            "discovery_method": "sos_ks_gov_constitution_html",
            "article_id": art_id,
            "skip_hydrate": True,
        },
    )


def parse_kansas_constitution_html(
    html: str,
    *,
    code_name: str = "Kansas Constitution",
    max_statutes: Optional[int] = None,
) -> List[NormalizedStatute]:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    soup = BeautifulSoup(html or "", "html.parser")
    container = soup.find("div", class_="page-content")
    if container is None:
        return []
    h3 = soup.find("h3", class_="constitution-subheading")
    page_title = h3.get_text(" ", strip=True) if h3 is not None else ""
    if " - " in page_title:
        page_title = page_title.split(" - ", 1)[1].strip()
    cur_art = _article_id_from_title(page_title)
    cur_num: Optional[str] = None
    cur_parts: List[str] = []
    flushed: List[Tuple[str, str, str]] = []

    def flush() -> None:
        if cur_num is None:
            return
        flushed.append((cur_art, cur_num, " ".join(cur_parts)))

    for para in container.find_all("p"):
        text = _WS.sub(" ", para.get_text(" ", strip=True)).strip()
        if not text:
            continue
        classes = para.get("class") or []
        if "constitution-history" in classes:
            cur_parts.append(text)
            continue
        match = _KS_SECTION_HEAD_RE.match(text)
        if match:
            flush()
            cur_num = match.group(1)
            cur_parts = [match.group(2).strip()]
            continue
        if cur_art == "ORD" and _KS_PREAMBLE_TRIGGER_RE.match(text):
            flush()
            cur_art, cur_num, cur_parts = "0", "0", [text]
            continue
        if cur_num is None:
            cur_num, cur_parts = "0", [text]
            continue
        cur_parts.append(text)
    flush()

    statutes: List[NormalizedStatute] = []
    for art_id, number, body in flushed:
        if max_statutes is not None and len(statutes) >= int(max_statutes):
            break
        row = _row(art_id, number, body, code_name)
        if row is not None:
            statutes.append(row)
    return statutes


def configured_constitution_html_path() -> Optional[Path]:
    raw = str(os.environ.get("KANSAS_CONSTITUTION_HTML") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None
