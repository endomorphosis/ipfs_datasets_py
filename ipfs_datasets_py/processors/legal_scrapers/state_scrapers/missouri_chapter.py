"""Official Missouri revisor chapter/section parsers.

Adapted from Vaquill-AI/open-us-law ``mo_bulk.parse`` (Apache-2.0).
Reads every table on OneChapter.aspx (not just the first).
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import List, Optional, Tuple
from urllib.parse import parse_qs, urlparse

from .base_scraper import NormalizedStatute, StatuteMetadata

BASE = "https://revisor.mo.gov/main"
_CHAPTER_RE = re.compile(r"OneChapter\.aspx\?chapter=([0-9][\w.]*)")
_SECTION_RE = re.compile(r"[?&]section=([0-9][0-9.]*[A-Za-z]?)")
_EFF_DATE_RE = re.compile(r"\s*\(\d{1,2}/\d{1,2}/\d{4}\)\s*$")
_WS = re.compile(r"\s+")


def _clean(raw: str) -> str:
    text = (raw or "").replace("\xa0", " ").replace("\xad", "")
    return _WS.sub(" ", text).strip()


def details_chapter_links(html: str, *, base_url: str = BASE) -> List[Tuple[str, str, str]]:
    """Home.aspx ``<details>`` chapter rows (``OneChapter.aspx?chapter=N``)."""

    from urllib.parse import urljoin

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    soup = BeautifulSoup(html or "", "html.parser")
    out: List[Tuple[str, str, str]] = []
    seen: set[str] = set()
    containers = soup.find_all("details") or [soup]
    for detail in containers:
        for anchor in detail.find_all("a", href=True):
            href = str(anchor.get("href") or "")
            match = _CHAPTER_RE.search(href)
            if not match:
                continue
            number = match.group(1).strip()
            if not number or number in seen:
                continue
            seen.add(number)
            raw = _clean(anchor.get_text(" "))
            name = re.sub(rf"^\s*{re.escape(number)}\s*", "", raw).strip()
            out.append(
                (
                    number,
                    f"Chapter {number} {name}".strip(),
                    urljoin(base_url.rstrip("/") + "/", f"OneChapter.aspx?chapter={number}"),
                )
            )
    return out


def chapter_numbers(home_html: str) -> List[str]:
    seen = {match.group(1).strip() for match in _CHAPTER_RE.finditer(home_html or "")}

    def _key(token: str):
        try:
            return (0, int(token), token)
        except ValueError:
            return (1, 0, token)

    return sorted(seen, key=_key)


def chapter_sections(chapter_html: str, chapter_number: str) -> List[Tuple[str, str]]:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    soup = BeautifulSoup(chapter_html or "", "html.parser")
    out: List[Tuple[str, str]] = []
    seen = set()
    for row in soup.find_all("tr"):
        tds = row.find_all("td")
        if not tds:
            continue
        link = tds[0].find("a", href=True)
        if link is None:
            continue
        match = _SECTION_RE.search(str(link.get("href") or ""))
        if match:
            secnum = match.group(1).strip()
        else:
            txt = _clean(link.get_text())
            if not re.fullmatch(r"[0-9][0-9.]*[A-Za-z]?", txt):
                continue
            secnum = txt
        if secnum in seen or secnum.split(".")[0] != str(chapter_number):
            continue
        seen.add(secnum)
        title = _EFF_DATE_RE.sub("", _clean(tds[1].get_text()) if len(tds) > 1 else "").strip()
        out.append((secnum, title))
    return out


def section_content(section_html: str) -> Tuple[List[str], str]:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return [], ""
    soup = BeautifulSoup(section_html or "", "html.parser")
    bottom = soup.find(id="BOTTOM")
    if bottom is None:
        return [], ""
    outer = bottom.find_previous_sibling()
    if outer is None:
        return [], ""
    first_child = outer.find(recursive=False)
    if first_child is None:
        return [], ""
    norm_div = first_child.find("div", class_="norm")
    if norm_div is None:
        return [], ""
    paras: List[str] = []
    history = ""
    for element in norm_div.find_all(recursive=False):
        classes = element.get("class", []) or []
        if element.name == "div" and "foot" in classes:
            history = re.sub(r"^[\-\xad\s]+", "", _clean(element.get_text(" "))).strip()
            continue
        if element.name == "p":
            text = _clean(element.get_text(" "))
            if text:
                paras.append(text)
    return paras, history


def section_url(section_number: str) -> str:
    return f"{BASE}/OneSection.aspx?section={section_number}"


def statute_from_section_html(
    html: str,
    *,
    section_number: str,
    code_name: str = "Missouri Revised Statutes",
    section_title: str = "",
) -> NormalizedStatute | None:
    paras, history = section_content(html)
    body = " ".join(paras).strip()
    if len(body) < 20:
        return None
    return NormalizedStatute(
        state_code="MO",
        state_name="Missouri",
        statute_id=f"{code_name} § {section_number}",
        code_name=code_name,
        section_number=section_number,
        section_name=(section_title or f"Section {section_number}")[:200],
        full_text=body[:14000],
        source_url=section_url(section_number),
        official_cite=f"Mo. Rev. Stat. § {section_number}",
        metadata=StatuteMetadata(),
        structured_data={
            "source_kind": "official_missouri_revisor_html",
            "source_authority_class": "official",
            "discovery_method": "revisor_all_chapter_tables",
            "history": history,
            "skip_hydrate": True,
        },
    )


def configured_home_html_path() -> Optional[Path]:
    raw = str(os.environ.get("MISSOURI_HOME_HTML") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None


def parse_configured_home_html() -> List[Tuple[str, str, str]]:
    path = configured_home_html_path()
    if path is None:
        return []
    return details_chapter_links(path.read_text(encoding="utf-8", errors="replace"))
