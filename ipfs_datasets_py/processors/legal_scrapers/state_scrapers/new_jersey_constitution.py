"""Official New Jersey Constitution parser.

Adapted from Vaquill-AI/open-us-law ``ingest_state_constitutions.scrape_nj``
(Apache-2.0). njleg.state.nj.us/constitution uses bare ``1.`` paragraph
markers. Nested ``SECTION <roman>`` sub-levels fold into composite article
ids such as ``II.I`` so paragraph 1 is not dropped after the split.

Local dump: ``NEW_JERSEY_CONSTITUTION_HTML``.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import List, Optional

from .base_scraper import NormalizedStatute, StatuteMetadata

NJ_CONST_URL = "https://njleg.state.nj.us/constitution"
_NJ_ARTICLE_RE = re.compile(
    r"\n\s*(?:ARTICLE|Article)\s+([IVXLC\d]+(?:[\.\-][IVXLC\d]+)?(?:[A-Z])?)[\.\:]?(?:[ \t][^\n]*)?\n"
)
_NJ_SUBSECTION_RE = re.compile(r"\n\s*(?:SECTION|Section)\s+([IVXLC]+)\s*\n")
_NJ_PARA_RE = re.compile(r"\n\s*(\d+(?:\.\d+)?[A-Za-z]?)\.\s+")
_RESERVED = re.compile(r"\b(repealed|reserved|expired|renumbered)\b", re.IGNORECASE)
_WS = re.compile(r"\s+")


def parse_new_jersey_constitution_html(
    html: str,
    *,
    code_name: str = "New Jersey Constitution",
    max_statutes: Optional[int] = None,
) -> List[NormalizedStatute]:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    soup = BeautifulSoup(html or "", "html.parser")
    main = soup.find("main") or soup.find("body") or soup
    body_text = "\n" + main.get_text("\n", strip=True)
    art_parts = _NJ_ARTICLE_RE.split(body_text)
    if len(art_parts) <= 1:
        return []
    art_pairs = [(art_parts[index], art_parts[index + 1]) for index in range(1, len(art_parts) - 1, 2)]
    statutes: List[NormalizedStatute] = []
    for art_id, art_body in art_pairs:
        if max_statutes is not None and len(statutes) >= int(max_statutes):
            break
        sub_parts = _NJ_SUBSECTION_RE.split(art_body)
        if len(sub_parts) > 1:
            groups = [
                (f"{art_id}.{sub_parts[index]}", sub_parts[index + 1])
                for index in range(1, len(sub_parts) - 1, 2)
            ]
        else:
            groups = [(art_id, art_body)]
        for composite_art, group_body in groups:
            if max_statutes is not None and len(statutes) >= int(max_statutes):
                break
            pieces = _NJ_PARA_RE.split("\n" + group_body)
            para_pairs = [
                (pieces[index], pieces[index + 1])
                for index in range(1, len(pieces) - 1, 2)
            ]
            for number, para_body in para_pairs:
                if max_statutes is not None and len(statutes) >= int(max_statutes):
                    break
                raw = _WS.sub(" ", para_body.replace("\xa0", " ")).strip()
                if len(raw) < 40:
                    continue
                if _RESERVED.search(raw[:160]):
                    continue
                heading = (raw.split(".", 1)[0] or f"Section {number}")[:200]
                cite = f"N.J. Const. art. {composite_art}, ¶ {number}"
                statutes.append(
                    NormalizedStatute(
                        state_code="NJ",
                        state_name="New Jersey",
                        statute_id=cite,
                        code_name=code_name,
                        title_number=str(composite_art),
                        section_number=number,
                        section_name=heading,
                        full_text=raw[:14000],
                        source_url=NJ_CONST_URL,
                        official_cite=cite,
                        metadata=StatuteMetadata(),
                        structured_data={
                            "source_kind": "official_new_jersey_constitution_html",
                            "source_authority_class": "official",
                            "discovery_method": "njleg_state_nj_us_constitution",
                            "article_id": str(composite_art),
                            "skip_hydrate": True,
                        },
                    )
                )
    return statutes


def configured_constitution_html_path() -> Optional[Path]:
    raw = str(os.environ.get("NEW_JERSEY_CONSTITUTION_HTML") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None
