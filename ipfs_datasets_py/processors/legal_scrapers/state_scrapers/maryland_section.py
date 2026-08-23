"""Official Maryland StatuteText HTML parser.

Adapted from Vaquill-AI/open-us-law ``scrapeMD.py`` (Apache-2.0).
Body lives in ``#StatuteText``; ``div.row`` chrome and center-aligned
divs are dropped. ``File Not Found`` / repealed stubs are skipped.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qs, urlparse

from .base_scraper import NormalizedStatute, StatuteMetadata

BASE = "https://mgaleg.maryland.gov/mgawebsite/Laws/StatuteText"
_RESERVED = re.compile(r"\b(repealed|expired|reserved|renumbered|transferred)\b", re.IGNORECASE)
_HEAD_RE = re.compile(r"§\s*(?P<num>[\w.–\-]+)\.\s*(?P<head>.*)?")
_WS = re.compile(r"\s+")


def _clean(text: str) -> str:
    return _WS.sub(" ", (text or "").replace("\xa0", " ")).strip()


def parse_maryland_section_html(
    html: str,
    *,
    source_url: str = "",
    code_name: str = "Maryland Code",
) -> Optional[NormalizedStatute]:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return None
    soup = BeautifulSoup(html or "", "html.parser")
    stat = soup.find(id="StatuteText")
    if stat is None:
        return None
    raw = stat.get_text("\n")
    if "File Not Found" in raw:
        return None
    if _RESERVED.search(raw[:400]):
        return None
    for tag in stat.find_all("div", class_="row"):
        tag.decompose()
    for tag in stat.find_all("div", style=re.compile(r"text-align\s*:\s*center", re.I)):
        tag.decompose()
    paras = [_clean(part) for part in stat.get_text("\n").split("\n")]
    paras = [part for part in paras if part]
    heading = ""
    number = ""
    name = ""
    if paras:
        match = _HEAD_RE.search(paras[0])
        if match:
            heading = paras[0]
            number = match.group("num").replace("–", "-").replace("—", "-")
            name = _clean(match.group("head") or "")
            paras = paras[1:]
    body = _clean(" ".join(paras))
    if len(body) < 40:
        return None
    query = parse_qs(urlparse(source_url).query)
    article = (query.get("article") or [""])[0]
    number = number or (query.get("section") or [""])[0]
    if not number:
        return None
    return NormalizedStatute(
        state_code="MD",
        state_name="Maryland",
        statute_id=f"{code_name} § {number}",
        code_name=code_name,
        section_number=number,
        section_name=(name or heading or f"Section {number}")[:200],
        full_text=body[:14000],
        source_url=source_url or f"{BASE}?article={article}&section={number}&enactments=false",
        official_cite=f"Md. Code § {number}",
        metadata=StatuteMetadata(),
        structured_data={
            "source_kind": "official_maryland_statute_text",
            "source_authority_class": "official",
            "discovery_method": "mgaleg_statute_text",
            "article_code": article.upper() if article else None,
            "skip_hydrate": True,
        },
    )


def configured_section_html_path() -> Optional[Path]:
    raw = str(os.environ.get("MARYLAND_SECTION_HTML") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None
