"""Official Rhode Island section HTML parser.

Adapted from Vaquill-AI/open-us-law ``scrapeRI.py`` (Apache-2.0).
Canonical host is ``webserver.rilegislature.gov`` (the old rilin host
redirects every sub-path back to the TOC). Body is top-level ``divs[2]``;
the nested ``History of Section`` div is dropped.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Optional

from .base_scraper import NormalizedStatute, StatuteMetadata

BASE = "https://webserver.rilegislature.gov/Statutes"
_HEAD_RE = re.compile(r"§\s*(?P<num>[0-9A-Za-z.-]+)\.\s*(?P<head>.+)")
_RESERVED = re.compile(r"\[(?:repealed|expired|reserved|renumbered)\]|repealed\.|reserved\.", re.IGNORECASE)
_HISTORY_PREFIX = "History of Section"
_WS = re.compile(r"\s+")
_STEM_RE = re.compile(r"/Statutes/TITLE(?P<title>[^/]+)/(?P<chapter>[^/]+)/(?P<section>[^/]+)\.htm$", re.IGNORECASE)


def _clean(text: str) -> str:
    value = (text or "").replace("\xa0", " ").replace("Â§", "§")
    return _WS.sub(" ", value).strip()


def parse_rhode_island_section_html(
    html: str,
    *,
    source_url: str = "",
    code_name: str = "Rhode Island General Laws",
) -> Optional[NormalizedStatute]:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return None
    soup = BeautifulSoup(html or "", "html.parser")
    body = soup.find("body") or soup
    top_divs = body.find_all("div", recursive=False)
    content = top_divs[2] if len(top_divs) >= 3 else (top_divs[-1] if top_divs else body)
    nested = content.find_all("div", recursive=False)
    history_div = nested[-1] if nested else None
    if history_div is not None:
        hist = _clean(history_div.get_text(" "))
        if _HISTORY_PREFIX in hist or "P.L." in hist or "G.L." in hist:
            history_div.decompose()
    heading = ""
    paras: list[str] = []
    for para in content.find_all("p", recursive=False):
        text = _clean(para.get_text(" "))
        if not text:
            continue
        bold = para.find("b")
        if bold is not None:
            bold_text = _clean(bold.get_text(" "))
            remainder = text.replace(bold_text, "").strip()
            if not remainder and bold_text.startswith("§"):
                heading = bold_text
                continue
        paras.append(text)
    body_text = _clean(" ".join(paras))
    if len(body_text) < 40:
        return None
    if _RESERVED.search(heading) or _RESERVED.search(body_text[:160]):
        return None
    match = _HEAD_RE.search(heading)
    number = match.group("num") if match else ""
    name = match.group("head").strip() if match else heading
    url_match = _STEM_RE.search(source_url or "")
    if url_match:
        number = number or url_match.group("section")
        title = url_match.group("title")
        chapter = url_match.group("chapter")
    else:
        title = number.split("-", 1)[0] if number else ""
        chapter = "-".join(number.split("-")[:2]) if number else ""
    if not number:
        return None
    return NormalizedStatute(
        state_code="RI",
        state_name="Rhode Island",
        statute_id=f"{code_name} § {number}",
        code_name=code_name,
        title_number=title or None,
        chapter_number=chapter or None,
        section_number=number,
        section_name=name[:200] or f"Section {number}",
        full_text=body_text[:14000],
        source_url=source_url or BASE,
        official_cite=f"R.I. Gen. Laws § {number}",
        metadata=StatuteMetadata(),
        structured_data={
            "source_kind": "official_rhode_island_section_html",
            "source_authority_class": "official",
            "discovery_method": "rilegislature_content_div2",
            "skip_hydrate": True,
        },
    )


def configured_section_html_path() -> Optional[Path]:
    raw = str(os.environ.get("RHODE_ISLAND_SECTION_HTML") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None
