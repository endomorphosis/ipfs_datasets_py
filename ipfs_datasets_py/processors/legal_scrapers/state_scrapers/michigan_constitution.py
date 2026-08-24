"""Official Michigan Constitution PDF-text parser.

Adapted from Vaquill-AI/open-us-law ``ingest_state_constitutions.scrape_mi``
(Apache-2.0). legislature.mi.gov serves a current PDF; the document opens
with a full table of contents that repeats every ``ARTICLE`` / ``§ N``
marker. Keep the longest body per article and per section number.

Local dump: ``MICHIGAN_CONSTITUTION_TEXT``. No auto-download of the PDF.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .base_scraper import NormalizedStatute, StatuteMetadata

MI_CONST_PDF = "https://www.legislature.mi.gov/documents/publications/constitution.pdf"
_MI_ARTICLE_RE = re.compile(
    r"\n\s*ARTICLE\s+([IVXLC]+)\s*\n([^\n]+?)\n",
    re.IGNORECASE,
)
_MI_SECTION_RE = re.compile(
    r"§\s*(\d+[A-Za-z]?)\.?\s+(.*?)(?=\n§\s*\d|\Z)",
    re.MULTILINE | re.DOTALL,
)
_RESERVED = re.compile(r"\b(repealed|reserved|expired|renumbered)\b", re.IGNORECASE)
_WS = re.compile(r"\s+")


def parse_michigan_constitution_text(
    text: str,
    *,
    code_name: str = "Michigan Constitution",
    max_statutes: Optional[int] = None,
) -> List[NormalizedStatute]:
    body = "\n" + (text or "")
    art_matches = list(_MI_ARTICLE_RE.finditer(body))
    if not art_matches:
        return []
    raw_articles: Dict[str, Tuple[str, str]] = {}
    for index, match in enumerate(art_matches):
        art_id = match.group(1).strip()
        art_title = _WS.sub(" ", match.group(2)).strip()
        start = match.end()
        end = art_matches[index + 1].start() if index + 1 < len(art_matches) else len(body)
        art_body = body[start:end]
        if art_id not in raw_articles or len(art_body) > len(raw_articles[art_id][1]):
            raw_articles[art_id] = (art_title, art_body)

    statutes: List[NormalizedStatute] = []
    for art_id, (art_title, art_body) in raw_articles.items():
        if max_statutes is not None and len(statutes) >= int(max_statutes):
            break
        sec_iter = list(_MI_SECTION_RE.finditer(art_body))
        if not sec_iter:
            body_clean = _WS.sub(" ", art_body).strip()
            if len(body_clean) < 100 or _RESERVED.search(body_clean[:160]):
                continue
            statutes.append(
                NormalizedStatute(
                    state_code="MI",
                    state_name="Michigan",
                    statute_id=f"Mich. Const. art. {art_id}",
                    code_name=code_name,
                    title_number=art_id,
                    section_number="0",
                    section_name=art_title or f"Article {art_id}",
                    full_text=body_clean[:14000],
                    source_url=MI_CONST_PDF,
                    official_cite=f"Mich. Const. art. {art_id}",
                    metadata=StatuteMetadata(),
                    structured_data={
                        "source_kind": "official_michigan_constitution_pdf",
                        "source_authority_class": "official",
                        "discovery_method": "legislature_mi_gov_constitution_pdf",
                        "article_id": art_id,
                        "skip_hydrate": True,
                    },
                )
            )
            continue
        best_by_num: Dict[str, str] = {}
        for match in sec_iter:
            number = match.group(1).strip()
            sec_body = _WS.sub(" ", match.group(2)).strip()
            if len(sec_body) < 30:
                continue
            if number not in best_by_num or len(sec_body) > len(best_by_num[number]):
                best_by_num[number] = sec_body
        for number, sec_body in best_by_num.items():
            if max_statutes is not None and len(statutes) >= int(max_statutes):
                break
            if _RESERVED.search(sec_body[:160]):
                continue
            heading = (sec_body.split(".", 1)[0] or f"Section {number}")[:200]
            statutes.append(
                NormalizedStatute(
                    state_code="MI",
                    state_name="Michigan",
                    statute_id=f"Mich. Const. art. {art_id}, § {number}",
                    code_name=code_name,
                    title_number=art_id,
                    section_number=number,
                    section_name=heading,
                    full_text=sec_body[:14000],
                    source_url=MI_CONST_PDF,
                    official_cite=f"Mich. Const. art. {art_id}, § {number}",
                    metadata=StatuteMetadata(),
                    structured_data={
                        "source_kind": "official_michigan_constitution_pdf",
                        "source_authority_class": "official",
                        "discovery_method": "legislature_mi_gov_constitution_pdf",
                        "article_id": art_id,
                        "skip_hydrate": True,
                    },
                )
            )
    return statutes


def configured_constitution_text_path() -> Optional[Path]:
    raw = str(os.environ.get("MICHIGAN_CONSTITUTION_TEXT") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None
