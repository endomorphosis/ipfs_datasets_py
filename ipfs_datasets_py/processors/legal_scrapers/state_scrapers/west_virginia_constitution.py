"""Official West Virginia Constitution parser.

Adapted from Vaquill-AI/open-us-law ``ingest_state_constitutions.scrape_wv``
(Apache-2.0). home.wvlegislature.gov hosts the full text. Articles use
``ARTICLE N``; sections are ``N-N.`` with a leading newline so section 1
is not dropped.

Local dump: ``WEST_VIRGINIA_CONSTITUTION_HTML``.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import List, Optional

from .base_scraper import NormalizedStatute, StatuteMetadata

WV_CONST_URL = "https://home.wvlegislature.gov/constitution-of-west-virginia/"
_WV_ARTICLE_RE = re.compile(r"\n\s*ARTICLE\s+([IVXLC]+)\n")
_WV_SECTION_RE = re.compile(r"(?:\A|\n)\s*(\d+)-(\d+[A-Za-z]?)\.\s*")
_RESERVED = re.compile(r"\b(repealed|reserved|expired|renumbered)\b", re.IGNORECASE)
_WS = re.compile(r"\s+")


def parse_west_virginia_constitution_html(
    html: str,
    *,
    code_name: str = "West Virginia Constitution",
    max_statutes: Optional[int] = None,
) -> List[NormalizedStatute]:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    soup = BeautifulSoup(html or "", "html.parser")
    main = soup.find("main") or soup.find("body") or soup
    body_text = "\n" + main.get_text("\n", strip=True)
    articles = list(_WV_ARTICLE_RE.finditer(body_text))
    statutes: List[NormalizedStatute] = []
    if not articles:
        articles = []
        span_iter = [(None, 0, len(body_text))]
    else:
        span_iter = [
            (
                match.group(1),
                match.end(),
                articles[index + 1].start() if index + 1 < len(articles) else len(body_text),
            )
            for index, match in enumerate(articles)
        ]
    for article_id, start, end in span_iter:
        if max_statutes is not None and len(statutes) >= int(max_statutes):
            break
        span = "\n" + body_text[start:end]
        matches = list(_WV_SECTION_RE.finditer(span))
        roman = article_id or "I"
        for index, match in enumerate(matches):
            if max_statutes is not None and len(statutes) >= int(max_statutes):
                break
            number = f"{match.group(1)}-{match.group(2)}"
            sec_end = matches[index + 1].start() if index + 1 < len(matches) else len(span)
            raw = _WS.sub(" ", span[match.end() : sec_end].replace("\xa0", " ")).strip()
            if len(raw) < 40:
                continue
            if _RESERVED.search(raw[:160]):
                continue
            heading = (raw.split(".", 1)[0] or f"Section {number}")[:200]
            statutes.append(
                NormalizedStatute(
                    state_code="WV",
                    state_name="West Virginia",
                    statute_id=f"W. Va. Const. art. {roman}, § {number}",
                    code_name=code_name,
                    title_number=roman,
                    section_number=number,
                    section_name=heading,
                    full_text=raw,
                    source_url=WV_CONST_URL,
                    official_cite=f"W. Va. Const. art. {roman}, § {number}",
                    metadata=StatuteMetadata(),
                    structured_data={
                        "source_kind": "official_west_virginia_constitution_html",
                        "source_authority_class": "official",
                        "discovery_method": "wvlegislature_constitution_html",
                        "article_id": roman,
                        "skip_hydrate": True,
                    },
                )
            )
    return statutes


def configured_constitution_html_path() -> Optional[Path]:
    raw = str(os.environ.get("WEST_VIRGINIA_CONSTITUTION_HTML") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None
