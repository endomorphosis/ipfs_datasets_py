"""Official Indiana Constitution PDF-text parser.

Adapted from Vaquill-AI/open-us-law ``ingest_state_constitutions.scrape_in``
(Apache-2.0). ``ARTICLE N.\\nTitle.\\nSection N.`` with optional
``(History: As Amended ...)`` notes kept inline.

Local dump: ``INDIANA_CONSTITUTION_TEXT``. No auto-download of the PDF.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import List, Optional

from .base_scraper import NormalizedStatute, StatuteMetadata

IN_CONST_PDF = (
    "https://iga.in.gov/publications/indiana_constitution/Constitution%20(as%20amended%202024).pdf"
)
_IN_ARTICLE_RE = re.compile(r"\n\s*ARTICLE\s+(\d+)\.\s*\n\s*([^\n]+)\n")
_IN_SECTION_RE = re.compile(r"\n\s*Section\s+(\d+[A-Za-z]?)\.\s*")
_RESERVED = re.compile(r"\b(repealed|reserved|expired|renumbered)\b", re.IGNORECASE)
_WS = re.compile(r"\s+")


def parse_indiana_constitution_text(
    text: str,
    *,
    code_name: str = "Indiana Constitution",
    max_statutes: Optional[int] = None,
) -> List[NormalizedStatute]:
    body = "\n" + (text or "")
    art_matches = list(_IN_ARTICLE_RE.finditer(body))
    statutes: List[NormalizedStatute] = []
    for index, match in enumerate(art_matches):
        if max_statutes is not None and len(statutes) >= int(max_statutes):
            break
        art_id = match.group(1)
        start = match.end()
        end = art_matches[index + 1].start() if index + 1 < len(art_matches) else len(body)
        span = body[start:end]
        sec_matches = list(_IN_SECTION_RE.finditer("\n" + span))
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
            cite = f"Ind. Const. art. {art_id}, § {number}"
            statutes.append(
                NormalizedStatute(
                    state_code="IN",
                    state_name="Indiana",
                    statute_id=cite,
                    code_name=code_name,
                    title_number=art_id,
                    section_number=number,
                    section_name=(raw.split(".", 1)[0] or f"Section {number}")[:200],
                    full_text=raw[:14000],
                    source_url=IN_CONST_PDF,
                    official_cite=cite,
                    metadata=StatuteMetadata(),
                    structured_data={
                        "source_kind": "official_indiana_constitution_pdf",
                        "source_authority_class": "official",
                        "discovery_method": "iga_in_gov_constitution_pdf",
                        "article_id": art_id,
                        "skip_hydrate": True,
                    },
                )
            )
    return statutes


def configured_constitution_text_path() -> Optional[Path]:
    raw = str(os.environ.get("INDIANA_CONSTITUTION_TEXT") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None
