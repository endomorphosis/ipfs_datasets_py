"""Official Rhode Island Constitution Word-export parser.

Adapted from Vaquill-AI/open-us-law ``ingest_state_constitutions.scrape_ri``
(Apache-2.0). ConstFull.aspx is Word-export HTML: walk every h1/h2/h3/p and
match ARTICLE/Section against element text, because Article IX headings are
plain ``<p>`` tags. Space-join per element so letter-spacing spans do not
split words onto their own lines.

Local dump: ``RHODE_ISLAND_CONSTITUTION_HTML``.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import List, Optional

from .base_scraper import NormalizedStatute, StatuteMetadata

RI_CONST_URL = "https://www.rilegislature.gov/riconstitution/Constitution/ConstFull.aspx"
_RI_ARTICLE_RE = re.compile(r"^ARTICLE\s+([IVXLC]+)$")
_RI_SECTION_RE = re.compile(r"^Section\s+(\d+[A-Za-z]?)\.\s*(.*)$")
_RESERVED = re.compile(r"\b(repealed|reserved|expired|renumbered)\b", re.IGNORECASE)
_WS = re.compile(r"\s+")


def parse_rhode_island_constitution_html(
    html: str,
    *,
    code_name: str = "Rhode Island Constitution",
    max_statutes: Optional[int] = None,
) -> List[NormalizedStatute]:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    soup = BeautifulSoup(html or "", "html.parser")
    body_el = soup.find("body") or soup
    elements = body_el.find_all(["h1", "h2", "h3", "p"])
    statutes: List[NormalizedStatute] = []
    cur_art: Optional[str] = None
    cur_sec: Optional[str] = None
    cur_sec_title = ""
    pending: List[str] = []
    awaiting_title = False

    def flush() -> None:
        nonlocal pending, cur_sec, cur_sec_title
        if cur_art is None or cur_sec is None:
            pending = []
            cur_sec = None
            cur_sec_title = ""
            return
        raw = _WS.sub(" ", " ".join(pending)).strip()
        if (
            len(raw) >= 40
            and not _RESERVED.search(cur_sec_title)
            and not _RESERVED.search(raw[:160])
            and (max_statutes is None or len(statutes) < int(max_statutes))
        ):
            cite = f"R.I. Const. art. {cur_art}, § {cur_sec}"
            statutes.append(
                NormalizedStatute(
                    state_code="RI",
                    state_name="Rhode Island",
                    statute_id=cite,
                    code_name=code_name,
                    title_number=cur_art,
                    section_number=cur_sec,
                    section_name=(cur_sec_title or raw.split(".", 1)[0])[:200],
                    full_text=raw,
                    source_url=RI_CONST_URL,
                    official_cite=cite,
                    metadata=StatuteMetadata(),
                    structured_data={
                        "source_kind": "official_rhode_island_constitution_html",
                        "source_authority_class": "official",
                        "discovery_method": "rilegislature_constfull",
                        "article_id": cur_art,
                        "skip_hydrate": True,
                    },
                )
            )
        pending = []
        cur_sec = None
        cur_sec_title = ""

    for element in elements:
        if max_statutes is not None and len(statutes) >= int(max_statutes):
            break
        text = _WS.sub(" ", element.get_text(" ", strip=True)).strip()
        if not text:
            continue
        art_match = _RI_ARTICLE_RE.match(text)
        if art_match:
            flush()
            cur_art = art_match.group(1)
            awaiting_title = True
            continue
        if awaiting_title:
            awaiting_title = False
            if text == text.upper() and len(text) <= 90:
                continue
        sec_match = _RI_SECTION_RE.match(text)
        if sec_match and cur_art is not None:
            flush()
            cur_sec = sec_match.group(1)
            cur_sec_title = _WS.sub(" ", sec_match.group(2)).strip()
            continue
        if cur_art is not None:
            pending.append(text)
    flush()
    return statutes


def configured_constitution_html_path() -> Optional[Path]:
    raw = str(os.environ.get("RHODE_ISLAND_CONSTITUTION_HTML") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None
