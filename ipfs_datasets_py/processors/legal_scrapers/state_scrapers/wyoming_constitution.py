"""Official Wyoming Constitution Title 97 PDF-text parser.

Adapted from Vaquill-AI/open-us-law ``ingest_state_constitutions.scrape_wy``
(Apache-2.0). Headings are ``ARTICLE N - TITLE``; sections are
``Article N, Section M``.

Local dump: ``WYOMING_CONSTITUTION_TEXT``. No auto-download of the PDF.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import List, Optional

from .base_scraper import NormalizedStatute, StatuteMetadata

WY_CONST_PDF = "https://wyoleg.gov/statutes/compress/title97.pdf"
_WY_ARTICLE_RE = re.compile(r"\n\s*ARTICLE\s+(\d+)\s*-\s*([^\n]+)\n")
_WY_SECTION_RE = re.compile(r"\n\s*Article\s+\d+,\s*Section\s+(\d+[A-Za-z]?)[^\S\n]*")
_RESERVED = re.compile(r"\b(repealed|reserved|expired|renumbered)\b", re.IGNORECASE)
_WS = re.compile(r"\s+")


def parse_wyoming_constitution_text(
    text: str,
    *,
    code_name: str = "Wyoming Constitution",
    max_statutes: Optional[int] = None,
) -> List[NormalizedStatute]:
    body = "\n" + (text or "")
    art_matches = list(_WY_ARTICLE_RE.finditer(body))
    statutes: List[NormalizedStatute] = []
    for index, match in enumerate(art_matches):
        if max_statutes is not None and len(statutes) >= int(max_statutes):
            break
        art_id = match.group(1)
        start = match.end()
        end = art_matches[index + 1].start() if index + 1 < len(art_matches) else len(body)
        span = body[start:end]
        sec_matches = list(_WY_SECTION_RE.finditer("\n" + span))
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
            cite = f"Wyo. Const. art. {art_id}, § {number}"
            statutes.append(
                NormalizedStatute(
                    state_code="WY",
                    state_name="Wyoming",
                    statute_id=cite,
                    code_name=code_name,
                    title_number=art_id,
                    section_number=number,
                    section_name=(raw.split(".", 1)[0] or f"Section {number}")[:200],
                    full_text=raw[:14000],
                    source_url=WY_CONST_PDF,
                    official_cite=cite,
                    metadata=StatuteMetadata(),
                    structured_data={
                        "source_kind": "official_wyoming_constitution_pdf",
                        "source_authority_class": "official",
                        "discovery_method": "wyoleg_gov_title97_pdf",
                        "article_id": art_id,
                        "skip_hydrate": True,
                    },
                )
            )
    return statutes


def configured_constitution_text_path() -> Optional[Path]:
    raw = str(os.environ.get("WYOMING_CONSTITUTION_TEXT") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None
