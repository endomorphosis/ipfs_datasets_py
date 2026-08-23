"""Official New Hampshire RSA section HTML parser.

Adapted from Vaquill-AI/open-us-law ``scrapeNH.py`` (Apache-2.0).
Body lives in ``<codesect>``; ``<sourcenote>`` history is dropped.
"""

from __future__ import annotations

import os
import re
from html import unescape
from pathlib import Path
from typing import Optional

from .base_scraper import NormalizedStatute, StatuteMetadata

BASE = "https://www.gencourt.state.nh.us/rsa/html"
_RESERVED = re.compile(r"\[(?:repealed|expired|reserved)\]|\brepealed\b|\breserved\b|\bexpired\b", re.IGNORECASE)
_WS = re.compile(r"\s+")
_URL_RE = re.compile(r"/([\w\-]+)/([\w\-]+)\.htm$", re.IGNORECASE)


def _clean(text: str) -> str:
    value = unescape(text or "").replace("\xa0", " ")
    return _WS.sub(" ", value).strip()


def parse_new_hampshire_section_html(
    html: str,
    *,
    source_url: str = "",
    code_name: str = "New Hampshire RSA",
) -> Optional[NormalizedStatute]:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return None
    soup = BeautifulSoup(html or "", "html.parser")
    body = soup.find("body") or soup
    codesect = body.find("codesect")
    if codesect is None:
        return None
    full = _clean(codesect.get_text(" "))
    if len(full) < 40:
        return None
    bold = body.find("b")
    heading = _clean(bold.get_text(" ")) if bold else ""
    heading = re.sub(r"\s*[\-–—―]+\s*$", "", heading).strip()
    if _RESERVED.search(heading) or _RESERVED.search(full[:160]):
        return None
    citation = heading.split()[0] if heading else ""
    url_match = _URL_RE.search(source_url or "")
    if not re.match(r"^\d", citation) and url_match:
        chapter = url_match.group(1)
        stem = url_match.group(2)
        prefix = f"{chapter}-"
        section = stem[len(prefix) :] if stem.startswith(prefix) else stem
        citation = f"{chapter}:{section}"
    number = citation.split(":", 1)[1] if ":" in citation else citation
    number = number.rstrip(".")
    if not number:
        return None
    name = heading or f"Section {number}"
    return NormalizedStatute(
        state_code="NH",
        state_name="New Hampshire",
        statute_id=f"{code_name} § {number}",
        code_name=code_name,
        chapter_number=citation.split(":", 1)[0] if ":" in citation else None,
        section_number=number if ":" not in citation else citation,
        section_name=name[:200],
        full_text=full[:14000],
        source_url=source_url or BASE,
        official_cite=f"N.H. Rev. Stat. § {citation or number}",
        metadata=StatuteMetadata(),
        structured_data={
            "source_kind": "official_new_hampshire_rsa_html",
            "source_authority_class": "official",
            "discovery_method": "gencourt_codesect",
            "skip_hydrate": True,
        },
    )


def configured_section_html_path() -> Optional[Path]:
    raw = str(os.environ.get("NEW_HAMPSHIRE_SECTION_HTML") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None
