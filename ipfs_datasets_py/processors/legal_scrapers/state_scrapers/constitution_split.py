"""Shared ARTICLE/Section split for official constitution HTML dumps."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import List, Optional, Pattern

from .base_scraper import NormalizedStatute, StatuteMetadata

_ARTICLE_RE = re.compile(r"\n\s*(?:ARTICLE|Article)\s+([IVXLC]+|\d+)\b")
_SECTION_RE = re.compile(
    r"\n\s*(?:SECTION|Section|Sec\.)\s+(\d+(?:\.\d+)?[A-Za-z]?)\.?\s*"
)
_RESERVED = re.compile(r"\b(repealed|reserved|expired|renumbered)\b", re.IGNORECASE)
_WS = re.compile(r"\s+")


def parse_article_section_html(
    html: str,
    *,
    state_code: str,
    state_name: str,
    cite_fmt: str,
    source_url: str,
    source_kind: str,
    discovery_method: str,
    code_name: str,
    max_statutes: Optional[int] = None,
    article_re: Optional[Pattern[str]] = None,
    section_re: Optional[Pattern[str]] = None,
) -> List[NormalizedStatute]:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    soup = BeautifulSoup(html or "", "html.parser")
    main = soup.find("main") or soup.find("body") or soup
    body_text = "\n" + main.get_text("\n", strip=True)
    art_re = article_re or _ARTICLE_RE
    sec_re = section_re or _SECTION_RE
    art_matches = list(art_re.finditer(body_text))
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
        sec_matches = list(sec_re.finditer(span))
        for sec_index, sec_match in enumerate(sec_matches):
            if max_statutes is not None and len(statutes) >= int(max_statutes):
                break
            number = sec_match.group(1)
            sec_end = (
                sec_matches[sec_index + 1].start()
                if sec_index + 1 < len(sec_matches)
                else len(span)
            )
            raw = _WS.sub(" ", span[sec_match.end() : sec_end].replace("\xa0", " ")).strip()
            if len(raw) < 40 or _RESERVED.search(raw[:160]):
                continue
            cite = cite_fmt.format(art=art_id, sec=number)
            statutes.append(
                NormalizedStatute(
                    state_code=state_code,
                    state_name=state_name,
                    statute_id=cite,
                    code_name=code_name,
                    title_number=str(art_id),
                    section_number=number,
                    section_name=(raw.split(".", 1)[0] or f"Section {number}")[:200],
                    full_text=raw,
                    source_url=source_url,
                    official_cite=cite,
                    metadata=StatuteMetadata(),
                    structured_data={
                        "source_kind": source_kind,
                        "source_authority_class": "official",
                        "discovery_method": discovery_method,
                        "article_id": str(art_id),
                        "skip_hydrate": True,
                    },
                )
            )
    return statutes


def env_html_path(name: str) -> Optional[Path]:
    raw = str(os.environ.get(name) or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None
