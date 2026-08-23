"""Official Vermont section HTML parser.

Adapted from Vaquill-AI/open-us-law ``scrapeVT.py`` (Apache-2.0).
Body lives in ``ul.statutes-detail``; the bold heading is skipped and
``(Added`` / ``(Amended`` suffixes are dropped.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Optional

from .base_scraper import NormalizedStatute, StatuteMetadata

BASE = "https://legislature.vermont.gov"
_ADDENDUM_RE = re.compile(r"^\((?:Added|Amended)", re.IGNORECASE)
_SPLIT_RE = re.compile(r"\s+(?=\((?:Added|Amended)\b)", re.IGNORECASE)
_RESERVED = re.compile(
    r"[\(\[](repealed|expired|reserved|renumbered)[\.\]\)]",
    re.IGNORECASE,
)
_SECTION_URL_RE = re.compile(
    r"/statutes/section/(?P<title>[\w.\-]+)/(?P<chapter>[\w.\-]+)/(?P<section>[\w.\-]+)/?$",
    re.IGNORECASE,
)
_HEAD_RE = re.compile(r"§\s*(?P<num>[0-9A-Za-z.-]+)\.\s*(?P<head>.+)")
_WS = re.compile(r"\s+")


def _clean(text: str) -> str:
    return _WS.sub(" ", (text or "").replace("\xa0", " ").replace("’", "'")).strip()


def _normalise_number(raw: str) -> str:
    if not raw or not any(char.isdigit() for char in raw):
        return raw
    match = re.match(r"^0*(\d+)(.*)", raw)
    return match.group(1) + match.group(2) if match else raw


def parse_vermont_section_html(
    html: str,
    *,
    source_url: str = "",
    code_name: str = "Vermont Statutes",
) -> Optional[NormalizedStatute]:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return None
    soup = BeautifulSoup(html or "", "html.parser")
    container = soup.find("ul", class_="statutes-detail") or soup.find("div", id="main-content") or soup
    paras: list[str] = []
    heading = ""
    for para in container.find_all("p"):
        text = _clean(para.get_text(" "))
        if not text:
            continue
        bold = para.find("b")
        if bold is not None:
            bold_text = _clean(bold.get_text(" "))
            rest = text.replace(bold_text, "").strip()
            if not rest:
                heading = bold_text
                continue
        if _ADDENDUM_RE.match(text):
            continue
        parts = _SPLIT_RE.split(text, maxsplit=1)
        body_part = parts[0].strip()
        if body_part:
            paras.append(body_part)
    body = _clean(" ".join(paras))
    if len(body) < 40:
        return None
    if _RESERVED.search(heading) or _RESERVED.search(body[:160]):
        return None
    url_match = _SECTION_URL_RE.search(source_url or "")
    title = _normalise_number(url_match.group("title")) if url_match else ""
    chapter = _normalise_number(url_match.group("chapter")) if url_match else ""
    number = _normalise_number(url_match.group("section")) if url_match else ""
    head_match = _HEAD_RE.search(heading)
    if head_match:
        number = number or head_match.group("num")
        name = head_match.group("head").strip()
    else:
        name = heading or f"Section {number}"
    if not number:
        return None
    return NormalizedStatute(
        state_code="VT",
        state_name="Vermont",
        statute_id=f"{code_name} § {number}",
        code_name=code_name,
        title_number=title or None,
        chapter_number=chapter or None,
        section_number=number,
        section_name=name[:200],
        full_text=body[:14000],
        source_url=source_url or f"{BASE}/statutes/",
        official_cite=f"{title} V.S.A. § {number}" if title else f"Vt. Stat. Ann. § {number}",
        metadata=StatuteMetadata(),
        structured_data={
            "source_kind": "official_vermont_statutes_detail",
            "source_authority_class": "official",
            "discovery_method": "legislature_statutes_detail",
            "skip_hydrate": True,
        },
    )


def configured_section_html_path() -> Optional[Path]:
    raw = str(os.environ.get("VERMONT_SECTION_HTML") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None
