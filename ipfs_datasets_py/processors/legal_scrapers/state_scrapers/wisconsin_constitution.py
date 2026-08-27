"""Official Wisconsin Constitution PDF-text parser.

Adapted from Vaquill-AI/open-us-law ``ingest_state_constitutions.scrape_wi``
(Apache-2.0). The unannotated PDF is two-column; TOC runs interleave with
body text. Keep an ARTICLE heading only when a real ``Title. SECTION N.``
marker follows within a short window. Duplicate section numbers get ``-vN``.

Local dump: ``WISCONSIN_CONSTITUTION_TEXT``. No auto-download of the PDF.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Dict, List, Optional

from .base_scraper import NormalizedStatute, StatuteMetadata

WI_CONST_PDF = "https://docs.legis.wisconsin.gov/constitution/wi_unannotated"
_WI_HYPHEN_WRAP_RE = re.compile(r"([A-Za-z])-\n([A-Za-z])")
_WI_TOC_RUN_RE = re.compile(
    r"\n(?:[ \t]*\d+[A-Za-z]{0,2}\.[ \t]*\n[ \t]*[A-Z][^\n]{1,110}\n){2,}"
)
_WI_TOC_SECTION_HEADER_RE = re.compile(r"\n[ \t]*Section[ \t]*\n")
_WI_ARTICLE_RE = re.compile(r"\nARTICLE\s+([IVXLC]+)\.\s*\n([^\n]*)\n")
_WI_PDF_SECTION_RE = re.compile(
    r"(?:\A|\n)([A-Z][^\n\[\]]{1,160}?)\.\s+SECTION\s+(\d+[A-Za-z]{0,2})\.\s+"
)
_WI_RUNNING_HEADER_RE = re.compile(
    r"\n\s*[A-Za-z]+ \d{1,2}, \d{4}\.\s*\n\s*ART\.[^\n]*WIS\.\s*CONSTITUTION\s*\n"
)
_WI_FOOTER_BLOCK_RE = re.compile(
    r"(?:Report errors at[^\n]*\n|lrb\.legal@legis\.wisconsin\.gov\.?\n|Click for the Coverage of[^\n]*\n)"
    r"(?:[^\n]*\n){0,6}?"
    r"ART\.\s+[IVXLCM]+,\s*§[\w.]+,\s*WIS\.\s*CONSTITUTION\s*\n?"
)
_RESERVED = re.compile(r"\b(repealed|reserved|expired|renumbered)\b", re.IGNORECASE)
_WS = re.compile(r"\s+")


def clean_wisconsin_constitution_text(text: str) -> str:
    body = _WI_HYPHEN_WRAP_RE.sub(r"\1\2", text or "")
    body = _WI_TOC_RUN_RE.sub("\n", body)
    body = _WI_TOC_SECTION_HEADER_RE.sub("\n", body)
    body = _WI_RUNNING_HEADER_RE.sub("\n", body)
    body = _WI_FOOTER_BLOCK_RE.sub("\n", body)
    return body


def parse_wisconsin_constitution_text(
    text: str,
    *,
    code_name: str = "Wisconsin Constitution",
    max_statutes: Optional[int] = None,
) -> List[NormalizedStatute]:
    cleaned = "\n" + clean_wisconsin_constitution_text(text or "")
    art_matches = list(_WI_ARTICLE_RE.finditer(cleaned))
    real = []
    for match in art_matches:
        window = cleaned[match.end() : match.end() + 200]
        if _WI_PDF_SECTION_RE.search(window):
            real.append(match)
    statutes: List[NormalizedStatute] = []
    for index, match in enumerate(real):
        if max_statutes is not None and len(statutes) >= int(max_statutes):
            break
        art_id = match.group(1)
        start = match.end()
        end = real[index + 1].start() if index + 1 < len(real) else len(cleaned)
        art_body = "\n" + cleaned[start:end]
        sec_matches = list(_WI_PDF_SECTION_RE.finditer(art_body))
        seen: Dict[str, int] = {}
        for sec_index, sec_match in enumerate(sec_matches):
            if max_statutes is not None and len(statutes) >= int(max_statutes):
                break
            heading = _WS.sub(" ", sec_match.group(1)).strip()
            raw_number = sec_match.group(2)
            sec_end = (
                sec_matches[sec_index + 1].start()
                if sec_index + 1 < len(sec_matches)
                else len(art_body)
            )
            raw = _WS.sub(" ", art_body[sec_match.end() : sec_end]).strip()
            if len(raw) < 40:
                continue
            if _RESERVED.search(heading) or _RESERVED.search(raw[:160]):
                continue
            seen[raw_number] = seen.get(raw_number, 0) + 1
            number = raw_number if seen[raw_number] == 1 else f"{raw_number}-v{seen[raw_number]}"
            cite = f"Wis. Const. art. {art_id}, § {number}"
            statutes.append(
                NormalizedStatute(
                    state_code="WI",
                    state_name="Wisconsin",
                    statute_id=cite,
                    code_name=code_name,
                    title_number=art_id,
                    section_number=number,
                    section_name=(heading or f"Section {number}")[:200],
                    full_text=raw,
                    source_url=WI_CONST_PDF,
                    official_cite=cite,
                    metadata=StatuteMetadata(),
                    structured_data={
                        "source_kind": "official_wisconsin_constitution_pdf",
                        "source_authority_class": "official",
                        "discovery_method": "docs_legis_wisconsin_gov_constitution_pdf",
                        "article_id": art_id,
                        "skip_hydrate": True,
                    },
                )
            )
    return statutes


def configured_constitution_text_path() -> Optional[Path]:
    raw = str(os.environ.get("WISCONSIN_CONSTITUTION_TEXT") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None
