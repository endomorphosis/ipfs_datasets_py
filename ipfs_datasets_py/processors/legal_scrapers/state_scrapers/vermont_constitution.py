"""Official Vermont Constitution HTML parser.

Adapted from Vaquill-AI/open-us-law ``ingest_state_constitutions.scrape_vt``
(Apache-2.0). Chapter I uses ``Article N.``; Chapter II uses ``§N.``.
Truncate the repeated General Assembly footer before splitting.

Local dump: ``VERMONT_CONSTITUTION_HTML``.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import List, Optional

from .base_scraper import NormalizedStatute, StatuteMetadata

VT_CONST_URL = "https://legislature.vermont.gov/statutes/constitution-of-the-state-of-vermont"
_VT_FOOTER_RE = re.compile(r"\n\s*The Vermont General Assembly\n.*", re.DOTALL)
_VT_ARTICLE_RE = re.compile(r"\n\s*CHAPTER\s+([IVXLC]+)[\.\:]?(?:[ \t][^\n]*)?\n")
_VT_SECTION_RE = re.compile(r"\n\s*(?:Article|§)\s*(\d+[A-Za-z]?)\.\s*")
_RESERVED = re.compile(r"\b(repealed|reserved|expired|renumbered)\b", re.IGNORECASE)
_WS = re.compile(r"\s+")


def parse_vermont_constitution_html(
    html: str,
    *,
    code_name: str = "Vermont Constitution",
    max_statutes: Optional[int] = None,
) -> List[NormalizedStatute]:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    soup = BeautifulSoup(html or "", "html.parser")
    main = soup.find("main") or soup.find("body") or soup
    body_text = _VT_FOOTER_RE.sub("", "\n" + main.get_text("\n", strip=True))
    parts = _VT_ARTICLE_RE.split(body_text)
    if len(parts) <= 1:
        return []
    art_iter = [(parts[index], parts[index + 1]) for index in range(1, len(parts) - 1, 2)]
    statutes: List[NormalizedStatute] = []
    for chapter_id, span in art_iter:
        if max_statutes is not None and len(statutes) >= int(max_statutes):
            break
        matches = list(_VT_SECTION_RE.finditer("\n" + span))
        for index, match in enumerate(matches):
            if max_statutes is not None and len(statutes) >= int(max_statutes):
                break
            number = match.group(1)
            end = matches[index + 1].start() if index + 1 < len(matches) else len(span) + 1
            raw = _WS.sub(" ", ("\n" + span)[match.end() : end].replace("\xa0", " ")).strip()
            if len(raw) < 40:
                continue
            if _RESERVED.search(raw[:160]):
                continue
            heading = (raw.split(".", 1)[0] or f"Section {number}")[:200]
            cite = f"Vt. Const. ch. {chapter_id}, § {number}"
            statutes.append(
                NormalizedStatute(
                    state_code="VT",
                    state_name="Vermont",
                    statute_id=cite,
                    code_name=code_name,
                    title_number=str(chapter_id),
                    section_number=number,
                    section_name=heading,
                    full_text=raw,
                    source_url=VT_CONST_URL,
                    official_cite=cite,
                    metadata=StatuteMetadata(),
                    structured_data={
                        "source_kind": "official_vermont_constitution_html",
                        "source_authority_class": "official",
                        "discovery_method": "legislature_vermont_gov_constitution",
                        "article_id": str(chapter_id),
                        "skip_hydrate": True,
                    },
                )
            )
    return statutes


def configured_constitution_html_path() -> Optional[Path]:
    raw = str(os.environ.get("VERMONT_CONSTITUTION_HTML") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None
