"""Official Oklahoma Constitution RTF-text parser.

Adapted from Vaquill-AI/open-us-law ``ingest_state_constitutions.scrape_ok``
(Apache-2.0). Start at the second ``PREAMBLE`` so the TOC copy is dropped.
Section markers repeat the article roman (``SECTION VII-1.``); lettered
sub-articles such as ``VII-A`` are kept.

Local dump: ``OKLAHOMA_CONSTITUTION_TEXT``. No auto-download of the RTF.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import List, Optional

from .base_scraper import NormalizedStatute, StatuteMetadata

OK_CONST_RTF = "https://www.oklegislature.gov/OK_Statutes/CompleteTitles/AllOKConstitutionArticles.rtf"
_OK_ARTICLE_RE = re.compile(r"\n\s*ARTICLE\s+([IVXLC]+(?:-[A-Z])?)\s*-\s*([^\n]+)\n")
_OK_SECTION_RE = re.compile(r"\n\s*SECTION\s+[IVXLC]+(?:-[A-Z])?-(\d+[A-Za-z]?)\.\s*")
_RESERVED = re.compile(r"\b(repealed|reserved|expired|renumbered)\b", re.IGNORECASE)
_WS = re.compile(r"\s+")


def parse_oklahoma_constitution_text(
    text: str,
    *,
    code_name: str = "Oklahoma Constitution",
    max_statutes: Optional[int] = None,
) -> List[NormalizedStatute]:
    body = "\n" + (text or "")
    preamble_idxs = [match.start() for match in re.finditer(r"\bPREAMBLE\b", body)]
    if len(preamble_idxs) >= 2:
        body = body[preamble_idxs[-1] :]
    art_matches = list(_OK_ARTICLE_RE.finditer(body))
    statutes: List[NormalizedStatute] = []
    for index, match in enumerate(art_matches):
        if max_statutes is not None and len(statutes) >= int(max_statutes):
            break
        art_id = match.group(1)
        start = match.end()
        end = art_matches[index + 1].start() if index + 1 < len(art_matches) else len(body)
        span = body[start:end]
        sec_matches = list(_OK_SECTION_RE.finditer("\n" + span))
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
            cite = f"Okla. Const. art. {art_id}, § {number}"
            statutes.append(
                NormalizedStatute(
                    state_code="OK",
                    state_name="Oklahoma",
                    statute_id=cite,
                    code_name=code_name,
                    title_number=art_id,
                    section_number=number,
                    section_name=(raw.split(".", 1)[0] or f"Section {number}")[:200],
                    full_text=raw,
                    source_url=OK_CONST_RTF,
                    official_cite=cite,
                    metadata=StatuteMetadata(),
                    structured_data={
                        "source_kind": "official_oklahoma_constitution_rtf",
                        "source_authority_class": "official",
                        "discovery_method": "oklegislature_constitution_rtf",
                        "article_id": art_id,
                        "skip_hydrate": True,
                    },
                )
            )
    return statutes


def configured_constitution_text_path() -> Optional[Path]:
    raw = str(os.environ.get("OKLAHOMA_CONSTITUTION_TEXT") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None
