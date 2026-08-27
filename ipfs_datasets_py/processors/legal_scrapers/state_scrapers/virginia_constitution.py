"""Official Virginia Constitution section-page parser.

Adapted from Vaquill-AI/open-us-law ``ingest_state_constitutions.scrape_va``
(Apache-2.0). law.lis.virginia.gov/constitution/articleN/sectionM/ puts the
article heading, section heading, and body in ``span#va_constitution``.
Article 13 (Schedule) has no roman numeral; fall back to the URL slug digits.

Local dump: ``VIRGINIA_CONSTITUTION_HTML``.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import List, Optional

from .base_scraper import NormalizedStatute, StatuteMetadata

VA_CONST_BASE = "https://law.lis.virginia.gov/constitution"
_VA_ARTICLE_HEADING_RE = re.compile(r"(?i)article\s+([IVXLC]+)\.?\s*(.*)")
_VA_SECTION_HEADING_RE = re.compile(r"(?i)section\s+([\dA-Za-z\-]+)\.?\s*(.*)")
_VA_ARTICLE_SLUG_RE = re.compile(r"/constitution/(article\d+)/section[\w\-]+/?")
_RESERVED = re.compile(r"\b(repealed|reserved|expired|renumbered)\b", re.IGNORECASE)
_WS = re.compile(r"\s+")


def parse_virginia_constitution_html(
    html: str,
    *,
    code_name: str = "Virginia Constitution",
    source_url: str = "",
    max_statutes: Optional[int] = None,
) -> List[NormalizedStatute]:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    soup = BeautifulSoup(html or "", "html.parser")
    span = soup.find("span", id="va_constitution")
    if span is None:
        return []
    headings = span.find_all("h2")
    if len(headings) < 2:
        return []
    art_text = headings[0].get_text(" ", strip=True)
    sec_text = headings[1].get_text(" ", strip=True)
    art_match = _VA_ARTICLE_HEADING_RE.match(art_text)
    if art_match:
        art_id = art_match.group(1)
    else:
        slug_match = _VA_ARTICLE_SLUG_RE.search(source_url or "")
        slug = slug_match.group(1) if slug_match else ""
        art_id = re.sub(r"\D", "", slug) or "13"
    sec_match = _VA_SECTION_HEADING_RE.match(sec_text)
    if not sec_match:
        return []
    number, sec_title = sec_match.group(1), sec_match.group(2).strip()
    body_section = span.find("section", class_="body")
    body = _WS.sub(" ", (body_section.get_text(" ", strip=True) if body_section else "")).strip()
    if len(body) < 40:
        return []
    if _RESERVED.search(sec_title) or _RESERVED.search(body[:160]):
        return []
    if max_statutes is not None and int(max_statutes) < 1:
        return []
    cite = f"Va. Const. art. {art_id}, § {number}"
    return [
        NormalizedStatute(
            state_code="VA",
            state_name="Virginia",
            statute_id=cite,
            code_name=code_name,
            title_number=art_id,
            section_number=number,
            section_name=(sec_title or f"Section {number}")[:200],
            full_text=body,
            source_url=source_url or f"{VA_CONST_BASE}/",
            official_cite=cite,
            metadata=StatuteMetadata(),
            structured_data={
                "source_kind": "official_virginia_constitution_html",
                "source_authority_class": "official",
                "discovery_method": "lis_virginia_gov_constitution",
                "article_id": art_id,
                "skip_hydrate": True,
            },
        )
    ]


def configured_constitution_html_path() -> Optional[Path]:
    raw = str(os.environ.get("VIRGINIA_CONSTITUTION_HTML") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None
