"""Official South Dakota Constitution parser.

Adapted from Vaquill-AI/open-us-law ``ingest_state_constitutions`` South
Dakota split (Apache-2.0). Start at the second ``Article I`` so the TOC copy
drops. Sections are ``§N.``; compact-ordinance articles without that marker
fall back to First/Second/Third/Fourth.

Local dump: ``SOUTH_DAKOTA_CONSTITUTION_HTML``.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import List, Optional

from .base_scraper import NormalizedStatute, StatuteMetadata

SD_CONST_URL = "https://sdlegislature.gov/Statutes/Constitution"
_SD_ARTICLE_RE = re.compile(r"\n\s*Article\s+([IVXLC]+|\d+)\b")
_SD_SECTION_RE = re.compile(r"\n\s*§\s*(\d+(?:\.\d+)?[A-Za-z]?)\.\s*")
_SD_COMPACT_RE = re.compile(r"\n\s*(First|Second|Third|Fourth)\.\s*")
_ORDINAL_TO_NUM = {"First": "1", "Second": "2", "Third": "3", "Fourth": "4"}
_RESERVED = re.compile(r"\b(repealed|reserved|expired|renumbered)\b", re.IGNORECASE)
_WS = re.compile(r"\s+")


def skip_south_dakota_toc(body_text: str) -> str:
    first = body_text.find("\nArticle I\n")
    if first == -1:
        first = re.search(r"\n\s*Article\s+I\b", body_text)
        if first is None:
            return body_text
        first = first.start()
    second = body_text.find("\nArticle I\n", first + 1)
    if second == -1:
        nxt = re.search(r"\n\s*Article\s+I\b", body_text[first + 1 :])
        second = first + 1 + nxt.start() if nxt else -1
    return body_text[second:] if second != -1 else body_text


def parse_south_dakota_constitution_html(
    html: str,
    *,
    code_name: str = "South Dakota Constitution",
    max_statutes: Optional[int] = None,
) -> List[NormalizedStatute]:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    soup = BeautifulSoup(html or "", "html.parser")
    main = soup.find("main") or soup.find("body") or soup
    body_text = skip_south_dakota_toc("\n" + main.get_text("\n", strip=True))
    art_matches = list(_SD_ARTICLE_RE.finditer(body_text))
    if not art_matches:
        return []
    statutes: List[NormalizedStatute] = []
    for index, match in enumerate(art_matches):
        if max_statutes is not None and len(statutes) >= int(max_statutes):
            break
        art_id = match.group(1)
        start = match.end()
        end = art_matches[index + 1].start() if index + 1 < len(art_matches) else len(body_text)
        span = "\n" + body_text[start:end]
        sec_matches = list(_SD_SECTION_RE.finditer(span))
        compact = False
        if not sec_matches:
            sec_matches = list(_SD_COMPACT_RE.finditer(span))
            compact = True
        for sec_index, sec_match in enumerate(sec_matches):
            if max_statutes is not None and len(statutes) >= int(max_statutes):
                break
            raw_number = sec_match.group(1)
            number = _ORDINAL_TO_NUM.get(raw_number, raw_number) if compact else raw_number
            sec_end = (
                sec_matches[sec_index + 1].start()
                if sec_index + 1 < len(sec_matches)
                else len(span)
            )
            raw = _WS.sub(" ", span[sec_match.end() : sec_end]).strip()
            if len(raw) < 40 or _RESERVED.search(raw[:160]):
                continue
            cite = f"S.D. Const. art. {art_id}, § {number}"
            statutes.append(
                NormalizedStatute(
                    state_code="SD",
                    state_name="South Dakota",
                    statute_id=cite,
                    code_name=code_name,
                    title_number=str(art_id),
                    section_number=number,
                    section_name=(raw.split(".", 1)[0] or f"Section {number}")[:200],
                    full_text=raw[:14000],
                    source_url=SD_CONST_URL,
                    official_cite=cite,
                    metadata=StatuteMetadata(),
                    structured_data={
                        "source_kind": "official_south_dakota_constitution_html",
                        "source_authority_class": "official",
                        "discovery_method": "sdlegislature_constitution",
                        "article_id": str(art_id),
                        "skip_hydrate": True,
                    },
                )
            )
    return statutes


def configured_constitution_html_path() -> Optional[Path]:
    raw = str(os.environ.get("SOUTH_DAKOTA_CONSTITUTION_HTML") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None
