"""Official Colorado Constitution Title 00 parser.

Adapted from Vaquill-AI/open-us-law ``ingest_state_constitutions`` Colorado
Title 00 DOCX notes (Apache-2.0). ``ARTICLE <roman>`` is its own paragraph,
the article name follows, then ``Section N[letter].`` headers. ``Source:``
notes stay inline.

Local dump: ``COLORADO_CONSTITUTION_TEXT``. No auto-download of the CRS DOCX.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import List, Optional

from .base_scraper import NormalizedStatute, StatuteMetadata

CO_CONST_NOTE = "Colorado Revised Statutes Title 00 (Constitution)"
_CO_ARTICLE_RE = re.compile(r"\n\s*ARTICLE\s+([IVXLC]+)\s*\n")
_CO_SECTION_RE = re.compile(r"\n\s*Section\s+(\d+[A-Za-z]?)\.\s*")
_RESERVED = re.compile(r"\b(repealed|reserved|expired|renumbered)\b", re.IGNORECASE)
_WS = re.compile(r"\s+")


def parse_colorado_constitution_text(
    text: str,
    *,
    code_name: str = "Colorado Constitution",
    max_statutes: Optional[int] = None,
) -> List[NormalizedStatute]:
    body = "\n" + (text or "")
    art_matches = list(_CO_ARTICLE_RE.finditer(body))
    statutes: List[NormalizedStatute] = []
    for index, match in enumerate(art_matches):
        if max_statutes is not None and len(statutes) >= int(max_statutes):
            break
        art_id = match.group(1)
        start = match.end()
        end = art_matches[index + 1].start() if index + 1 < len(art_matches) else len(body)
        span = body[start:end]
        sec_matches = list(_CO_SECTION_RE.finditer("\n" + span))
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
            cite = f"Colo. Const. art. {art_id}, § {number}"
            statutes.append(
                NormalizedStatute(
                    state_code="CO",
                    state_name="Colorado",
                    statute_id=cite,
                    code_name=code_name,
                    title_number=art_id,
                    section_number=number,
                    section_name=(raw.split(".", 1)[0] or f"Section {number}")[:200],
                    full_text=raw,
                    source_url="https://leg.colorado.gov/",
                    official_cite=cite,
                    metadata=StatuteMetadata(),
                    structured_data={
                        "source_kind": "official_colorado_constitution_crs",
                        "source_authority_class": "official",
                        "discovery_method": "colorado_crs_title_00",
                        "article_id": art_id,
                        "skip_hydrate": True,
                    },
                )
            )
    return statutes


def configured_constitution_text_path() -> Optional[Path]:
    raw = str(os.environ.get("COLORADO_CONSTITUTION_TEXT") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None
