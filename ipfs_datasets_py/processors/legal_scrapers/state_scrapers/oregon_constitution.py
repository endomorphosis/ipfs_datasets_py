"""Official Oregon Constitution SharePoint parser.

Adapted from Vaquill-AI/open-us-law ``ingest_state_constitutions.scrape_or``
(Apache-2.0). oregonlegislature.gov OrConst.aspx splits the document across
``.ms-rtestate-field`` divs over 1,000 characters. Real headers use
``Section``; TOC uses ``Sec.``. Reused article labels get ``-vN``;
``ARTICLE VII (Amended)`` and ``ARTICLE XI-F(1)`` fold into clean ids.

Local dump: ``OREGON_CONSTITUTION_HTML``.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Dict, List, Optional

from .base_scraper import NormalizedStatute, StatuteMetadata

OR_CONST_URL = "https://www.oregonlegislature.gov/bills_laws/Pages/OrConst.aspx"
_OR_ARTICLE_RE = re.compile(
    r"\n\s*ARTICLE\s+([IVXLC]+(?:-[A-Z])?(?:\(\d\))?(?:\s*\((?:Amended|Original)\))?)\s*\n"
)
_OR_SECTION_RE = re.compile(r"\n\s*Section\s+(\d+[A-Za-z]?)\.\s*")
_OR_CLEAN_RE = re.compile(
    r"^([IVXLC]+(?:-[A-Z])?)(?:\((\d)\))?(?:\s*\((Amended|Original)\))?$"
)
_RESERVED = re.compile(r"\b(repealed|reserved|expired|renumbered)\b", re.IGNORECASE)
_WS = re.compile(r"\s+")


def clean_oregon_article_id(raw: str) -> str:
    match = _OR_CLEAN_RE.match((raw or "").strip())
    if not match:
        return re.sub(r"[()\s]", "", (raw or "").strip())
    base, paren_num, tag = match.groups()
    cleaned = base + (paren_num or "")
    if tag:
        cleaned += f"-{tag}"
    return cleaned


def parse_oregon_constitution_html(
    html: str,
    *,
    code_name: str = "Oregon Constitution",
    max_statutes: Optional[int] = None,
) -> List[NormalizedStatute]:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    soup = BeautifulSoup(html or "", "html.parser")
    content_divs = [
        node for node in soup.select(".ms-rtestate-field") if len(node.get_text(strip=True)) > 1000
    ]
    if content_divs:
        body_text = "\n".join(node.get_text("\n", strip=True) for node in content_divs)
    else:
        main = soup.find("main") or soup.find("body") or soup
        body_text = main.get_text("\n", strip=True)
    padded = "\n" + body_text
    art_matches = list(_OR_ARTICLE_RE.finditer(padded))
    if not art_matches:
        return []
    seen_ids: Dict[str, int] = {}
    statutes: List[NormalizedStatute] = []
    for index, match in enumerate(art_matches):
        if max_statutes is not None and len(statutes) >= int(max_statutes):
            break
        art_id = clean_oregon_article_id(match.group(1))
        seen_ids[art_id] = seen_ids.get(art_id, 0) + 1
        if seen_ids[art_id] > 1:
            art_id = f"{art_id}-v{seen_ids[art_id]}"
        start = match.end()
        end = art_matches[index + 1].start() if index + 1 < len(art_matches) else len(padded)
        span = padded[start:end]
        sec_matches = list(_OR_SECTION_RE.finditer("\n" + span))
        for sec_index, sec_match in enumerate(sec_matches):
            if max_statutes is not None and len(statutes) >= int(max_statutes):
                break
            number = sec_match.group(1)
            sec_end = (
                sec_matches[sec_index + 1].start()
                if sec_index + 1 < len(sec_matches)
                else len(span) + 1
            )
            raw = _WS.sub(" ", ("\n" + span)[sec_match.end() : sec_end].replace("\xa0", " ")).strip()
            if len(raw) < 40:
                continue
            if _RESERVED.search(raw[:160]):
                continue
            heading = (raw.split(".", 1)[0] or f"Section {number}")[:200]
            cite = f"Or. Const. art. {art_id}, § {number}"
            statutes.append(
                NormalizedStatute(
                    state_code="OR",
                    state_name="Oregon",
                    statute_id=cite,
                    code_name=code_name,
                    title_number=art_id,
                    section_number=number,
                    section_name=heading,
                    full_text=raw,
                    source_url=OR_CONST_URL,
                    official_cite=cite,
                    metadata=StatuteMetadata(),
                    structured_data={
                        "source_kind": "official_oregon_constitution_html",
                        "source_authority_class": "official",
                        "discovery_method": "oregonlegislature_orconst",
                        "article_id": art_id,
                        "skip_hydrate": True,
                    },
                )
            )
    return statutes


def configured_constitution_html_path() -> Optional[Path]:
    raw = str(os.environ.get("OREGON_CONSTITUTION_HTML") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None
