"""Official New Mexico Constitution PDF/text parser.

Adapted from Vaquill-AI/open-us-law ``ingest_state_constitutions.scrape_nm``
(Apache-2.0). nmonesource.com is a JS SPA; the SOS PDF is the official
current text. Strip doubled-character footers and running headers, then
split ``ARTICLE N`` / ``Section N.``.

Local dump: ``NEW_MEXICO_CONSTITUTION_TEXT``. No auto-download of the SOS PDF.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import List, Optional

from .base_scraper import NormalizedStatute, StatuteMetadata

NM_CONST_PDF = "https://www.sos.nm.gov/wp-content/uploads/2025/01/NM_Constitution_-2025-for-SOS.pdf"
_NM_FOOTER_RE = re.compile(r"\n?\d*\s*©\s*2025 State of New Mexico\..*?AAMM?\n*", re.DOTALL)
_NM_RUNNING_HEADER_RE = re.compile(r"\nArticle\s+[IVXLC]+\s*[–-]\s*[^\n]*\n")
_NM_HYPHEN_WRAP_RE = re.compile(r"(\w)-\n(\w)")
_NM_ARTICLE_RE = re.compile(r"\nARTICLE\s+([IVXLC]+)\n[^\n]*\n")
_NM_SECTION_RE = re.compile(
    r"(?:\A|\n)(?:Section[^\S\n]+|Sec\.[^\S\n]+)(\d+[A-Za-z]?)\.[^\S\n]*"
)
_RESERVED = re.compile(r"\b(repealed|reserved|expired|renumbered)\b", re.IGNORECASE)
_WS = re.compile(r"\s+")


def clean_nm_constitution_text(text: str) -> str:
    body = _NM_FOOTER_RE.sub("\n", text or "")
    body = _NM_RUNNING_HEADER_RE.sub("\n", body)
    return _NM_HYPHEN_WRAP_RE.sub(r"\1\2", body)


def parse_new_mexico_constitution_text(
    text: str,
    *,
    code_name: str = "New Mexico Constitution",
    max_statutes: Optional[int] = None,
) -> List[NormalizedStatute]:
    body = clean_nm_constitution_text("\n" + (text or ""))
    articles = list(_NM_ARTICLE_RE.finditer(body))
    statutes: List[NormalizedStatute] = []
    if not articles:
        articles = [None]
    for index, article_match in enumerate(articles):
        if max_statutes is not None and len(statutes) >= int(max_statutes):
            break
        if article_match is None:
            article_id = "I"
            start = 0
            end = len(body)
        else:
            article_id = article_match.group(1)
            start = article_match.end()
            end = articles[index + 1].start() if index + 1 < len(articles) else len(body)
        span = body[start:end]
        matches = list(_NM_SECTION_RE.finditer(span))
        for sec_index, match in enumerate(matches):
            if max_statutes is not None and len(statutes) >= int(max_statutes):
                break
            number = match.group(1)
            sec_end = matches[sec_index + 1].start() if sec_index + 1 < len(matches) else len(span)
            raw = _WS.sub(" ", span[match.end() : sec_end].replace("\xa0", " ")).strip()
            if len(raw) < 40:
                continue
            if _RESERVED.search(raw[:160]):
                continue
            heading = (raw.split(".", 1)[0] or f"Section {number}")[:200]
            statutes.append(
                NormalizedStatute(
                    state_code="NM",
                    state_name="New Mexico",
                    statute_id=f"N.M. Const. art. {article_id}, § {number}",
                    code_name=code_name,
                    title_number=article_id,
                    section_number=number,
                    section_name=heading,
                    full_text=raw[:14000],
                    source_url=NM_CONST_PDF,
                    official_cite=f"N.M. Const. art. {article_id}, § {number}",
                    metadata=StatuteMetadata(),
                    structured_data={
                        "source_kind": "official_new_mexico_constitution_pdf",
                        "source_authority_class": "official",
                        "discovery_method": "sos_nm_gov_constitution_pdf",
                        "article_id": article_id,
                        "skip_hydrate": True,
                    },
                )
            )
    return statutes


def configured_constitution_text_path() -> Optional[Path]:
    raw = str(os.environ.get("NEW_MEXICO_CONSTITUTION_TEXT") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None
