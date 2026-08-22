"""Official Virginia Code section HTML/JSON body parser.

Adapted from Vaquill-AI/open-us-law ``va_bulk.parse`` (Apache-2.0).
Drops the site sidenote disclaimer from section Body HTML.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import List, Optional

from .base_scraper import NormalizedStatute, StatuteMetadata

_WS = re.compile(r"[ \t\xa0]+")
_SIDENOTE_HINT = "may not constitute a comprehensive list"
_SECTION_ANCHOR_RE = re.compile(r"/section([0-9][^/\"']+)/")


def vacode_url(section_number: str) -> str:
    return f"https://law.lis.virginia.gov/vacode/{section_number}/"


def section_numbers(chapter_html: str) -> List[str]:
    out: List[str] = []
    seen = set()
    for match in _SECTION_ANCHOR_RE.finditer(chapter_html or ""):
        sid = match.group(1).strip()
        if sid in seen:
            continue
        seen.add(sid)
        out.append(sid)
    return out


def body_to_paragraphs(body_html: str) -> List[str]:
    if not body_html or not str(body_html).strip():
        return []
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    soup = BeautifulSoup(body_html, "html.parser")
    blocks = soup.find_all(["p", "li", "blockquote"])
    paras: List[str] = []
    if blocks:
        for block in blocks:
            classes = " ".join(block.get("class") or [])
            if "sidenote" in classes:
                continue
            text = _WS.sub(" ", block.get_text(" ")).strip()
            if text and _SIDENOTE_HINT not in text:
                paras.append(text)
    else:
        text = _WS.sub(" ", soup.get_text(" ")).strip()
        if text and _SIDENOTE_HINT not in text:
            paras.append(text)
    return paras


def statutes_from_section_detail(
    payload: dict,
    *,
    section_number: str,
    code_name: str = "Code of Virginia",
) -> Optional[NormalizedStatute]:
    chapters = payload.get("ChapterList") or payload.get("chapterList") or []
    body_html = ""
    heading = ""
    if isinstance(chapters, list) and chapters:
        row = chapters[0] if isinstance(chapters[0], dict) else {}
        body_html = str(row.get("Body") or row.get("body") or "")
        heading = str(row.get("CatchLine") or row.get("SectionTitle") or "")
    paras = body_to_paragraphs(body_html)
    text = " ".join(paras).strip()
    if len(text) < 20:
        return None
    return NormalizedStatute(
        state_code="VA",
        state_name="Virginia",
        statute_id=f"{code_name} § {section_number}",
        code_name=code_name,
        section_number=section_number,
        section_name=(heading or f"Section {section_number}")[:200],
        full_text=text[:14000],
        source_url=vacode_url(section_number),
        official_cite=f"Va. Code Ann. § {section_number}",
        metadata=StatuteMetadata(),
        structured_data={
            "source_kind": "official_virginia_section_body",
            "source_authority_class": "official",
            "discovery_method": "law_lis_virginia_section_details",
            "skip_hydrate": True,
        },
    )


def configured_section_json_path() -> Optional[Path]:
    raw = str(os.environ.get("VIRGINIA_SECTION_JSON") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None


def parse_configured_section_json(code_name: str = "Code of Virginia") -> List[NormalizedStatute]:
    path = configured_section_json_path()
    if path is None:
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    number = str(payload.get("section_number") or path.stem)
    row = statutes_from_section_detail(payload, section_number=number, code_name=code_name)
    return [row] if row is not None else []
