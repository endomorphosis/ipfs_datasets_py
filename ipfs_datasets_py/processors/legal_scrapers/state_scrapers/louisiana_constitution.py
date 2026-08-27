"""Official Louisiana Constitution PDF-text parser.

Adapted from Vaquill-AI/open-us-law ``ingest_state_constitutions.scrape_la``
(Apache-2.0). Real articles are ALL-CAPS ``ARTICLE I.`` lines the mixed-case
TOC never uses. Split on ``Section N.`` (not ``§``) so TOC catchlines drop.

Local dump: ``LOUISIANA_CONSTITUTION_TEXT``. No auto-download of the PDF.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import List, Optional

from .base_scraper import NormalizedStatute, StatuteMetadata

LA_CONST_PDF = "https://senate.la.gov/Documents/LAConstitution.pdf"
_LA_FOOTER_RE = re.compile(
    r"\nCompiled from the La\. Senate Statutory Database\.\n\(As amended through calendar year \d+\)\n-[ivxlc\d]+-\n*",
    re.IGNORECASE,
)
_LA_HYPHEN_WRAP_RE = re.compile(r"(\w)-\n(\w)")
_LA_ARTICLE_RE = re.compile(r"\n\s*ARTICLE\s+([IVXLC]+)\.\s*\n([A-Z][A-Z .,;'\-]+)\n")
_LA_SECTION_RE = re.compile(r"\n\s*Section\s+(\d+(?:\.\d+)?[A-Za-z]?)\.\s*")
_RESERVED = re.compile(r"\b(repealed|reserved|expired|renumbered)\b", re.IGNORECASE)
_WS = re.compile(r"\s+")


def parse_louisiana_constitution_text(
    text: str,
    *,
    code_name: str = "Louisiana Constitution",
    max_statutes: Optional[int] = None,
) -> List[NormalizedStatute]:
    body = _LA_HYPHEN_WRAP_RE.sub(r"\1\2", _LA_FOOTER_RE.sub("\n", "\n" + (text or "")))
    art_matches = list(_LA_ARTICLE_RE.finditer(body))
    statutes: List[NormalizedStatute] = []
    for index, match in enumerate(art_matches):
        if max_statutes is not None and len(statutes) >= int(max_statutes):
            break
        art_id = match.group(1)
        start = match.end()
        end = art_matches[index + 1].start() if index + 1 < len(art_matches) else len(body)
        span = body[start:end]
        sec_matches = list(_LA_SECTION_RE.finditer("\n" + span))
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
            cite = f"La. Const. art. {art_id}, § {number}"
            statutes.append(
                NormalizedStatute(
                    state_code="LA",
                    state_name="Louisiana",
                    statute_id=cite,
                    code_name=code_name,
                    title_number=art_id,
                    section_number=number,
                    section_name=(raw.split(".", 1)[0] or f"Section {number}")[:200],
                    full_text=raw,
                    source_url=LA_CONST_PDF,
                    official_cite=cite,
                    metadata=StatuteMetadata(),
                    structured_data={
                        "source_kind": "official_louisiana_constitution_pdf",
                        "source_authority_class": "official",
                        "discovery_method": "senate_la_gov_constitution_pdf",
                        "article_id": art_id,
                        "skip_hydrate": True,
                    },
                )
            )
    return statutes


def configured_constitution_text_path() -> Optional[Path]:
    raw = str(os.environ.get("LOUISIANA_CONSTITUTION_TEXT") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None
