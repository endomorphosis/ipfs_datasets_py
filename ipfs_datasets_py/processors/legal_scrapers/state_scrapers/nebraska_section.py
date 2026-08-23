"""Official Nebraska section HTML parser.

Adapted from Vaquill-AI/open-us-law ``scrapeNE.py`` (Apache-2.0).
Body lives in ``#statute_text`` / ``.statute-body``; history/source classes
are dropped, and repealed stubs are skipped.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qs, urlparse

from .base_scraper import NormalizedStatute, StatuteMetadata

BASE = "https://nebraskalegislature.gov"
_SELECTORS = (
    ("div", {"id": "statute_text"}),
    ("div", {"id": "statuteText"}),
    ("div", {"class": "statute-body"}),
    ("div", {"class": "statute_body"}),
    ("div", {"class": "statute"}),
)
_RESERVED = re.compile(
    r"\brepealed\b|\bexpired\b|\breserved\b|\brenumbered\b|\bunconstitutional\b|\btransferred to\b",
    re.IGNORECASE,
)
_WS = re.compile(r"\s+")


def _clean(text: str) -> str:
    return _WS.sub(" ", (text or "").replace("\xa0", " ")).strip()


def parse_nebraska_section_html(
    html: str,
    *,
    source_url: str = "",
    code_name: str = "Nebraska Revised Statutes",
) -> Optional[NormalizedStatute]:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return None
    soup = BeautifulSoup(html or "", "html.parser")
    body = None
    for name, kwargs in _SELECTORS:
        body = soup.find(name, **kwargs)
        if body is not None:
            break
    if body is None:
        body = soup.find("main") or soup.find("div", class_="card-body")
    if body is None:
        return None
    paras: list[str] = []
    heading = ""
    for element in body.find_all(["p", "div", "li", "h1", "h2", "h3"], recursive=True):
        classes = " ".join(element.get("class") or []).lower()
        if any(token in classes for token in ("history", "source", "fa-ul", "annotation")):
            continue
        if any(token in classes for token in ("heading", "section-head", "card-header", "statute-head")):
            heading = heading or _clean(element.get_text(" "))
            continue
        text = _clean(element.get_text(" "))
        if not text:
            continue
        if element.name in {"h1", "h2", "h3"}:
            heading = heading or text
            continue
        paras.append(text)
    full = _clean(" ".join(paras))
    if len(full) < 40:
        return None
    if _RESERVED.search(full[:200]) or _RESERVED.search(heading):
        return None
    query = parse_qs(urlparse(source_url).query)
    number = (query.get("statute") or [""])[0]
    if not number:
        h2 = body.find("h2") or body.find("h1")
        number = _clean(h2.get_text(" ")) if h2 else ""
    number = number.rstrip(".")
    if not number:
        return None
    name = heading if heading and heading != number else (paras[0] if paras else f"Section {number}")
    chapter = number.split("-", 1)[0]
    return NormalizedStatute(
        state_code="NE",
        state_name="Nebraska",
        statute_id=f"{code_name} § {number}",
        code_name=code_name,
        chapter_number=chapter,
        section_number=number,
        section_name=name[:200],
        full_text=full[:14000],
        source_url=source_url or f"{BASE}/laws/statutes.php?statute={number}",
        official_cite=f"Neb. Rev. Stat. § {number}",
        metadata=StatuteMetadata(),
        structured_data={
            "source_kind": "official_nebraska_statutes_html",
            "source_authority_class": "official",
            "discovery_method": "nebraskalegislature_statute_text",
            "skip_hydrate": True,
        },
    )


def configured_section_html_path() -> Optional[Path]:
    raw = str(os.environ.get("NEBRASKA_SECTION_HTML") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None
