"""Official Minnesota Revisor section HTML parser.

Adapted from Vaquill-AI/open-us-law ``scrapeMN.py`` (Apache-2.0).
Body lives in ``.section``; ``shn`` headings are skipped and ``.history``
is dropped.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Optional

from .base_scraper import NormalizedStatute, StatuteMetadata

BASE = "https://www.revisor.mn.gov/statutes"
_RESERVED = re.compile(r"\b(repealed|renumbered|expired|reserved)\b", re.IGNORECASE)
_WS = re.compile(r"\s+")
_CITE_RE = re.compile(r"/statutes/cite/([0-9A-Za-z]+(?:\.[0-9A-Za-z]+)*)", re.IGNORECASE)


def _clean(text: str) -> str:
    return _WS.sub(" ", (text or "").replace("\xa0", " ")).strip()


def parse_minnesota_section_html(
    html: str,
    *,
    source_url: str = "",
    code_name: str = "Minnesota Statutes",
) -> Optional[NormalizedStatute]:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return None
    soup = BeautifulSoup(html or "", "html.parser")
    section = soup.find(class_="section")
    if section is None:
        return None
    paras: list[str] = []
    heading = ""
    for element in section.find_all(recursive=False):
        classes = " ".join(element.get("class") or [])
        text = _clean(element.get_text(" "))
        if not text:
            continue
        if element.name in {"h1", "h2", "h3"} or "shn" in classes:
            heading = text
            continue
        if "history" in classes.lower():
            continue
        paras.append(text)
    body = _clean(" ".join(paras))
    if len(body) < 40:
        return None
    if _RESERVED.search(heading) or _RESERVED.search(body[:160]):
        return None
    match = _CITE_RE.search(source_url or "")
    number = match.group(1) if match else ""
    if not number:
        token = heading.split()[0] if heading else ""
        number = token.rstrip(".")
    if not number:
        return None
    return NormalizedStatute(
        state_code="MN",
        state_name="Minnesota",
        statute_id=f"{code_name} § {number}",
        code_name=code_name,
        chapter_number=number.split(".", 1)[0],
        section_number=number,
        section_name=(heading or f"Section {number}")[:200],
        full_text=body[:14000],
        source_url=source_url or f"{BASE}/cite/{number}",
        official_cite=f"Minn. Stat. § {number}",
        metadata=StatuteMetadata(),
        structured_data={
            "source_kind": "official_minnesota_statutes_html",
            "source_authority_class": "official",
            "discovery_method": "revisor_section_div",
            "skip_hydrate": True,
        },
    )


def configured_section_html_path() -> Optional[Path]:
    raw = str(os.environ.get("MINNESOTA_SECTION_HTML") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None
