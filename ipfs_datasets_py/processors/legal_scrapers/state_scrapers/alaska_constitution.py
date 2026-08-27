"""Official Alaska Constitution parser.

Adapted from Vaquill-AI/open-us-law ``ingest_state_constitutions`` Alaska
section split (Apache-2.0). Sections are ``§N.`` with no SECTION keyword.

Local dump: ``ALASKA_CONSTITUTION_HTML``.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import List, Optional

from .base_scraper import NormalizedStatute, StatuteMetadata

AK_CONST_URL = "https://ltgov.alaska.gov/information/alaska-constitution/"
_AK_ARTICLE_RE = re.compile(r"\n\s*(?:ARTICLE|Article)\s+(\d+|[IVXLC]+)\b")
_AK_SECTION_RE = re.compile(r"\n\s*§\s*(\d+(?:\.\d+)?[A-Za-z]?)\.\s*")
_RESERVED = re.compile(r"\b(repealed|reserved|expired|renumbered)\b", re.IGNORECASE)
_WS = re.compile(r"\s+")


def parse_alaska_constitution_html(
    html: str,
    *,
    code_name: str = "Alaska Constitution",
    max_statutes: Optional[int] = None,
) -> List[NormalizedStatute]:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    soup = BeautifulSoup(html or "", "html.parser")
    main = soup.find("main") or soup.find("body") or soup
    body_text = "\n" + main.get_text("\n", strip=True)
    art_matches = list(_AK_ARTICLE_RE.finditer(body_text))
    if not art_matches:
        return []
    statutes: List[NormalizedStatute] = []
    for index, match in enumerate(art_matches):
        if max_statutes is not None and len(statutes) >= int(max_statutes):
            break
        art_id = match.group(1)
        start = match.end()
        end = art_matches[index + 1].start() if index + 1 < len(art_matches) else len(body_text)
        span = body_text[start:end]
        sec_matches = list(_AK_SECTION_RE.finditer("\n" + span))
        for sec_index, sec_match in enumerate(sec_matches):
            if max_statutes is not None and len(statutes) >= int(max_statutes):
                break
            number = sec_match.group(1)
            sec_end = (
                sec_matches[sec_index + 1].start()
                if sec_index + 1 < len(sec_matches)
                else len(span) + 1
            )
            raw = _WS.sub(" ", ("\n" + span)[sec_match.end() : sec_end]).strip()
            if len(raw) < 40 or _RESERVED.search(raw[:160]):
                continue
            cite = f"Alaska Const. art. {art_id}, § {number}"
            statutes.append(
                NormalizedStatute(
                    state_code="AK",
                    state_name="Alaska",
                    statute_id=cite,
                    code_name=code_name,
                    title_number=art_id,
                    section_number=number,
                    section_name=(raw.split(".", 1)[0] or f"Section {number}")[:200],
                    full_text=raw,
                    source_url=AK_CONST_URL,
                    official_cite=cite,
                    metadata=StatuteMetadata(),
                    structured_data={
                        "source_kind": "official_alaska_constitution_html",
                        "source_authority_class": "official",
                        "discovery_method": "alaska_constitution_html",
                        "article_id": art_id,
                        "skip_hydrate": True,
                    },
                )
            )
    return statutes


def configured_constitution_html_path() -> Optional[Path]:
    raw = str(os.environ.get("ALASKA_CONSTITUTION_HTML") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None
