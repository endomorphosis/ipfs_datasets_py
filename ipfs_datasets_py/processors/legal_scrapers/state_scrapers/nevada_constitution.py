"""Official Nevada Constitution parser.

Adapted from Vaquill-AI/open-us-law ``ingest_state_constitutions.scrape_nv``
(Apache-2.0). ``leg.state.nv.us/const/nvconst.html`` is the legislature's
current page. TOC ``Sec.`` column headers (nbsp-padded) are not sections.
Duplicate section numbers (current vs future-effective) get a ``-vN`` suffix.

Local dump: ``NEVADA_CONSTITUTION_HTML``.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Dict, List, Optional

from .base_scraper import NormalizedStatute, StatuteMetadata

NV_CONST_URL = "https://www.leg.state.nv.us/const/nvconst.html"
_NV_ARTICLE_RE = re.compile(r"\n\s*ARTICLE\.?\s+([IVXLC]+|\d+)\.?\s*-?\s*[^\n]*\n")
_NV_SECTION_RE = re.compile(
    r"(?:\A|\n)\s*(?:Section|Sec)[.:]\s*(\d+[A-Za-z]?)\.?(?!\s{0,3}\xa0)\s*"
)
_RESERVED = re.compile(r"\b(repealed|reserved|expired|renumbered)\b", re.IGNORECASE)
_WS = re.compile(r"\s+")


def parse_nevada_constitution_html(
    html: str,
    *,
    code_name: str = "Nevada Constitution",
    max_statutes: Optional[int] = None,
) -> List[NormalizedStatute]:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    soup = BeautifulSoup(html or "", "html.parser")
    body_text = "\n" + soup.get_text("\n", strip=True)
    parts = _NV_ARTICLE_RE.split(body_text)
    statutes: List[NormalizedStatute] = []
    if len(parts) <= 1:
        article_iter = [("1", body_text)]
    else:
        article_iter = [(parts[index], parts[index + 1]) for index in range(1, len(parts) - 1, 2)]
    for article_id, span in article_iter:
        if max_statutes is not None and len(statutes) >= int(max_statutes):
            break
        seen: Dict[str, int] = {}
        matches = list(_NV_SECTION_RE.finditer("\n" + span))
        for index, match in enumerate(matches):
            if max_statutes is not None and len(statutes) >= int(max_statutes):
                break
            raw_number = match.group(1)
            seen[raw_number] = seen.get(raw_number, 0) + 1
            number = raw_number if seen[raw_number] == 1 else f"{raw_number}-v{seen[raw_number]}"
            sec_end = matches[index + 1].start() if index + 1 < len(matches) else len(span) + 1
            raw = _WS.sub(" ", ("\n" + span)[match.end() : sec_end].replace("\xa0", " ")).strip()
            if len(raw) < 40:
                continue
            if _RESERVED.search(raw[:160]):
                continue
            heading = (raw.split(".", 1)[0] or f"Section {number}")[:200]
            statutes.append(
                NormalizedStatute(
                    state_code="NV",
                    state_name="Nevada",
                    statute_id=f"Nev. Const. art. {article_id}, § {number}",
                    code_name=code_name,
                    title_number=str(article_id),
                    section_number=number,
                    section_name=heading,
                    full_text=raw,
                    source_url=NV_CONST_URL,
                    official_cite=f"Nev. Const. art. {article_id}, § {number}",
                    metadata=StatuteMetadata(),
                    structured_data={
                        "source_kind": "official_nevada_constitution_html",
                        "source_authority_class": "official",
                        "discovery_method": "leg_state_nv_us_nvconst",
                        "article_id": str(article_id),
                        "skip_hydrate": True,
                    },
                )
            )
    return statutes


def configured_constitution_html_path() -> Optional[Path]:
    raw = str(os.environ.get("NEVADA_CONSTITUTION_HTML") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None
