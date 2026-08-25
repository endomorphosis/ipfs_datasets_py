"""Official Washington Constitution PDF-text parser.

Adapted from Vaquill-AI/open-us-law ``ingest_state_constitutions.scrape_wa``
(Apache-2.0). The legislature PDF has (A) the current constitution, (B)
amendment history, and (C) an index. Truncate at ``AMENDMENT 1`` so part B
does not re-split as duplicate articles. Article XXVI uses First/Second/
Third/Fourth compact-ordinance headings instead of SECTION.

Local dump: ``WASHINGTON_CONSTITUTION_TEXT``. No auto-download of the PDF.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import List, Optional, Tuple

from .base_scraper import NormalizedStatute, StatuteMetadata

WA_CONST_PDF = "https://leg.wa.gov/media/o3fg0ey1/washington-state-constitution.pdf"
_WA_FOOTER_RE = re.compile(
    r"\n?\d{1,2}/\d{1,2}/\d{4}\s+\d{1,2}:\d{2}\s+[AP]M\s*\[\s*\d+\s*\][^\n]*\n?"
)
_WA_HYPHEN_WRAP_RE = re.compile(r"(\w)-\n(\w)")
_WA_PART_B_MARKER = re.compile(r"\n\s*AMENDMENT\s+1\s*\n")
_WA_ARTICLE_RE = re.compile(r"\n\s*ARTICLE\s+([IVXLC]+)\s*\n[^\n]*\n")
_WA_SECTION_RE = re.compile(r"\n\s*SECTION\s+(\d+[A-Za-z]?)\s+")
_WA_COMPACT_RE = re.compile(r"\n\s*(First|Second|Third|Fourth)\.\s*")
_ORDINAL_TO_NUM = {"First": "1", "Second": "2", "Third": "3", "Fourth": "4"}
_RESERVED = re.compile(r"\b(repealed|reserved|expired|renumbered)\b", re.IGNORECASE)
_WS = re.compile(r"\s+")


def clean_washington_constitution_text(text: str) -> str:
    body = _WA_FOOTER_RE.sub("\n", text or "")
    body = _WA_HYPHEN_WRAP_RE.sub(r"\1\2", body)
    match = _WA_PART_B_MARKER.search(body)
    if match:
        body = body[: match.start()]
    return body


def _span_sections(span: str) -> List[Tuple[str, str]]:
    matches = list(_WA_SECTION_RE.finditer(span))
    compact = False
    if not matches:
        matches = list(_WA_COMPACT_RE.finditer(span))
        compact = True
    out: List[Tuple[str, str]] = []
    for index, match in enumerate(matches):
        raw_number = match.group(1)
        number = _ORDINAL_TO_NUM.get(raw_number, raw_number) if compact else raw_number
        end = matches[index + 1].start() if index + 1 < len(matches) else len(span)
        body = _WS.sub(" ", span[match.end() : end].replace("\xa0", " ")).strip()
        out.append((number, body))
    return out


def parse_washington_constitution_text(
    text: str,
    *,
    code_name: str = "Washington Constitution",
    max_statutes: Optional[int] = None,
) -> List[NormalizedStatute]:
    body = clean_washington_constitution_text("\n" + (text or ""))
    parts = _WA_ARTICLE_RE.split(body)
    if len(parts) <= 1:
        return []
    art_iter = [(parts[index], parts[index + 1]) for index in range(1, len(parts) - 1, 2)]
    statutes: List[NormalizedStatute] = []
    for art_id, span in art_iter:
        if max_statutes is not None and len(statutes) >= int(max_statutes):
            break
        for number, raw in _span_sections("\n" + span):
            if max_statutes is not None and len(statutes) >= int(max_statutes):
                break
            if len(raw) < 40:
                continue
            if _RESERVED.search(raw[:160]):
                continue
            heading = (raw.split(".", 1)[0] or f"Section {number}")[:200]
            statutes.append(
                NormalizedStatute(
                    state_code="WA",
                    state_name="Washington",
                    statute_id=f"Wash. Const. art. {art_id}, § {number}",
                    code_name=code_name,
                    title_number=str(art_id),
                    section_number=number,
                    section_name=heading,
                    full_text=raw[:14000],
                    source_url=WA_CONST_PDF,
                    official_cite=f"Wash. Const. art. {art_id}, § {number}",
                    metadata=StatuteMetadata(),
                    structured_data={
                        "source_kind": "official_washington_constitution_pdf",
                        "source_authority_class": "official",
                        "discovery_method": "leg_wa_gov_constitution_pdf",
                        "article_id": str(art_id),
                        "skip_hydrate": True,
                    },
                )
            )
    return statutes


def configured_constitution_text_path() -> Optional[Path]:
    raw = str(os.environ.get("WASHINGTON_CONSTITUTION_TEXT") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None
