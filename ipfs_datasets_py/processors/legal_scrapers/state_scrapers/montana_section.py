"""Official Montana MCA section HTML parser.

Adapted from Vaquill-AI/open-us-law ``scrapeMT.py`` (Apache-2.0).
Canonical host is ``mca.legmt.gov``. Body lives in ``.section-content``;
``.history-content`` is dropped.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Optional

from .base_scraper import NormalizedStatute, StatuteMetadata

BASE = "https://mca.legmt.gov/bills/mca"
_RESERVED = re.compile(r"\b(reserved|repealed|expired|transferred|renumbered)\b", re.IGNORECASE)
_HEAD_RE = re.compile(r"^(?P<num>\d+(?:-\d+){1,3})\.\s*(?P<head>.+)$")
_URL_RE = re.compile(r"/(\d{4})-(\d{4})-(\d{4})-(\d{4})\.html$", re.IGNORECASE)
_WS = re.compile(r"\s+")


def _clean(text: str) -> str:
    return _WS.sub(" ", (text or "").replace("\xa0", " ")).strip()


def _from_padded(parts: tuple[str, str, str, str]) -> str:
    title, chapter, _part, section = (part.lstrip("0") or "0" for part in parts)
    return f"{title}-{chapter}-{section}"


def parse_montana_section_html(
    html: str,
    *,
    source_url: str = "",
    code_name: str = "Montana Code Annotated",
) -> Optional[NormalizedStatute]:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return None
    soup = BeautifulSoup(html or "", "html.parser")
    text_div = soup.find(class_="section-content")
    if text_div is None:
        return None
    paras = []
    heading = ""
    for elem in text_div.find_all(recursive=False):
        text = _clean(elem.get_text(" "))
        if not text:
            continue
        if not heading:
            heading = text
            match = _HEAD_RE.match(text)
            if match:
                continue
        paras.append(text)
    body = _clean(" ".join(paras))
    if len(body) < 40:
        return None
    if _RESERVED.search(heading) or _RESERVED.search(body[:160]):
        return None
    match = _HEAD_RE.match(heading)
    number = match.group("num") if match else ""
    name = match.group("head").strip() if match else heading
    url_match = _URL_RE.search(source_url or "")
    if not number and url_match:
        number = _from_padded(url_match.groups())
    if not number:
        return None
    parts = number.split("-")
    return NormalizedStatute(
        state_code="MT",
        state_name="Montana",
        statute_id=f"{code_name} § {number}",
        code_name=code_name,
        title_number=parts[0] if parts else None,
        chapter_number=parts[1] if len(parts) > 1 else None,
        section_number=number,
        section_name=name[:200] or f"Section {number}",
        full_text=body[:14000],
        source_url=source_url or f"{BASE}/",
        official_cite=f"Mont. Code Ann. § {number}",
        metadata=StatuteMetadata(),
        structured_data={
            "source_kind": "official_montana_section_content",
            "source_authority_class": "official",
            "discovery_method": "mca_legmt_section_content",
            "skip_hydrate": True,
        },
    )


def configured_section_html_path() -> Optional[Path]:
    raw = str(os.environ.get("MONTANA_SECTION_HTML") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None
