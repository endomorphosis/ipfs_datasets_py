"""Official Mississippi Constitution SOS parser.

Adapted from Vaquill-AI/open-us-law ``ingest_state_constitutions.scrape_ms``
(Apache-2.0). Truncate at the first ``PREAMBLE`` so the global TOC is
dropped. Keep the longest body per section number so each article's mini-TOC
preview is not admitted as the real section.

Local dump: ``MISSISSIPPI_CONSTITUTION_HTML``.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Dict, List, Optional

from .base_scraper import NormalizedStatute, StatuteMetadata

MS_CONST_URL = "https://www.sos.state.ms.us/ed_pubs/constitution/constitution.asp"
_MS_PREAMBLE_RE = re.compile(r"\bPREAMBLE\b")
_MS_ARTICLE_RE = re.compile(r"ARTICLE\s+(\d{1,2})\s+")
_MS_SECTION_RE = re.compile(r"SECTION\s+(\d+(?:-[A-Z])?)\.\s*")
_RESERVED = re.compile(r"\b(repealed|reserved|expired|renumbered)\b", re.IGNORECASE)
_WS = re.compile(r"\s+")


def parse_mississippi_constitution_html(
    html: str,
    *,
    code_name: str = "Mississippi Constitution",
    max_statutes: Optional[int] = None,
) -> List[NormalizedStatute]:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    soup = BeautifulSoup(html or "", "html.parser")
    body_text = _WS.sub(" ", soup.get_text(" ", strip=True)).strip()
    pre_match = _MS_PREAMBLE_RE.search(body_text)
    if not pre_match:
        return []
    real_body = body_text[pre_match.end() :]
    art_matches = list(_MS_ARTICLE_RE.finditer(real_body))
    if not art_matches:
        return []
    statutes: List[NormalizedStatute] = []
    for index, match in enumerate(art_matches):
        if max_statutes is not None and len(statutes) >= int(max_statutes):
            break
        art_id = match.group(1)
        start = match.end()
        end = art_matches[index + 1].start() if index + 1 < len(art_matches) else len(real_body)
        art_body = real_body[start:end]
        sec_matches = list(_MS_SECTION_RE.finditer(art_body))
        best_by_num: Dict[str, str] = {}
        for sec_index, sec_match in enumerate(sec_matches):
            number = sec_match.group(1)
            sec_end = (
                sec_matches[sec_index + 1].start()
                if sec_index + 1 < len(sec_matches)
                else len(art_body)
            )
            sec_body = art_body[sec_match.end() : sec_end].strip()
            if number not in best_by_num or len(sec_body) > len(best_by_num[number]):
                best_by_num[number] = sec_body
        for number, sec_body in best_by_num.items():
            if max_statutes is not None and len(statutes) >= int(max_statutes):
                break
            raw = _WS.sub(" ", sec_body).strip()
            if len(raw) < 40:
                continue
            if _RESERVED.search(raw[:160]):
                continue
            heading = (raw.split(".", 1)[0] or f"Section {number}")[:200]
            cite = f"Miss. Const. art. {art_id}, § {number}"
            statutes.append(
                NormalizedStatute(
                    state_code="MS",
                    state_name="Mississippi",
                    statute_id=cite,
                    code_name=code_name,
                    title_number=art_id,
                    section_number=number,
                    section_name=heading,
                    full_text=raw[:14000],
                    source_url=MS_CONST_URL,
                    official_cite=cite,
                    metadata=StatuteMetadata(),
                    structured_data={
                        "source_kind": "official_mississippi_constitution_html",
                        "source_authority_class": "official",
                        "discovery_method": "sos_state_ms_us_constitution",
                        "article_id": art_id,
                        "skip_hydrate": True,
                    },
                )
            )
    return statutes


def configured_constitution_html_path() -> Optional[Path]:
    raw = str(os.environ.get("MISSISSIPPI_CONSTITUTION_HTML") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None
