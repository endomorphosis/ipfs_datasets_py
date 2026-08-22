"""Official Idaho statutes section-page parser.

Adapted from Vaquill-AI/open-us-law ``id_bulk.parse`` (Apache-2.0).
Body lives in ``.pgbrk``; the first four child divs are breadcrumbs.
"""

from __future__ import annotations

import re
from typing import List, Optional

from .base_scraper import NormalizedStatute, StatuteMetadata

BASE = "https://legislature.idaho.gov"
_HEADER_DIV_COUNT = 4
_WS = re.compile(r"\s+")


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
