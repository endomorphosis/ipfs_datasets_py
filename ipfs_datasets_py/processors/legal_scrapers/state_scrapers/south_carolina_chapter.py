"""Official South Carolina chapter HTML parser.

Adapted from Vaquill-AI/open-us-law ``scrapeSC.py`` (Apache-2.0).
Chapter pages are a flat ``#contentsection`` stream: bold
``SECTION X-Y-Z.`` headings, following text as body, ``HISTORY:`` terminator.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import List, Optional, Tuple

from .base_scraper import NormalizedStatute, StatuteMetadata

BASE = "https://www.scstatehouse.gov"
_SECTION_RE = re.compile(r"SECTION\s+([\w\-.]+?)\.", re.IGNORECASE)
_RESERVED = re.compile(r"\b(repealed|reserved|expired|renumbered)\b", re.IGNORECASE)
_WS = re.compile(r"\s+")


def _clean(text: str) -> str:
    return _WS.sub(" ", (text or "").replace("\xa0", " ")).strip()


def parse_south_carolina_chapter_html(
    html: str,
    *,
    source_url: str = "",
    code_name: str = "South Carolina Code of Laws",
    title_number: str = "",
    chapter_number: str = "",
    max_statutes: Optional[int] = None,
) -> List[NormalizedStatute]:
    try:
        from bs4 import BeautifulSoup, NavigableString
    except ImportError:
        return []
    soup = BeautifulSoup(html or "", "html.parser")
    content = soup.find(id="contentsection") or soup
    heads = []
    for elem in content.find_all(["span", "strong", "b"]):
        text = _clean(elem.get_text(" "))
        match = _SECTION_RE.match(text)
        if match:
            heads.append((elem, match.group(1), text))
    statutes: List[NormalizedStatute] = []
    for index, (elem, number, heading) in enumerate(heads):
        if max_statutes is not None and len(statutes) >= int(max_statutes):
            break
        if _RESERVED.search(heading):
            continue
        stop = heads[index + 1][0] if index + 1 < len(heads) else None
        name_parts: List[str] = []
        body_parts: List[str] = []
        got_name = False
        sibling = elem.next_sibling
        while sibling is not None and sibling is not stop:
            if getattr(sibling, "name", None) in {"span", "strong", "b"}:
                break
            text = ""
            if isinstance(sibling, NavigableString):
                text = _clean(str(sibling))
            elif getattr(sibling, "name", None) not in {"br", "script", "style"}:
                text = _clean(sibling.get_text(" ") if hasattr(sibling, "get_text") else "")
            if text.upper().startswith("HISTORY:"):
                break
            if text:
                if not got_name:
                    name_parts.append(text)
                    got_name = True
                else:
                    body_parts.append(text)
            sibling = sibling.next_sibling
        name = _clean(" ".join(name_parts)) or f"Section {number}"
        body = _clean(" ".join(body_parts))
        if not body and name and not name.upper().startswith("SECTION"):
            body = name
        if _RESERVED.search(name) or len(body) < 40:
            continue
        parts = number.split("-")
        statutes.append(
            NormalizedStatute(
                state_code="SC",
                state_name="South Carolina",
                statute_id=f"{code_name} § {number}",
                code_name=code_name,
                title_number=title_number or (parts[0] if parts else None),
                chapter_number=chapter_number or (parts[1] if len(parts) > 1 else None),
                section_number=number,
                section_name=name[:200],
                full_text=body[:14000],
                source_url=f"{source_url or BASE}#{number}",
                official_cite=f"S.C. Code Ann. § {number}",
                metadata=StatuteMetadata(),
                structured_data={
                    "source_kind": "official_south_carolina_code_html",
                    "source_authority_class": "official",
                    "discovery_method": "scstatehouse_contentsection_section",
                    "skip_hydrate": True,
                },
            )
        )
    return statutes


def configured_chapter_html_path() -> Optional[Path]:
    raw = str(os.environ.get("SOUTH_CAROLINA_CHAPTER_HTML") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None


def title_links(html: str, *, base_url: str = BASE) -> List[Tuple[str, str]]:
    """Master TOC ``/code/titleN.php`` links."""

    from urllib.parse import urljoin

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    soup = BeautifulSoup(html or "", "html.parser")
    out: List[Tuple[str, str]] = []
    seen: set[str] = set()
    for anchor in soup.find_all("a", href=True):
        href = str(anchor.get("href") or "").strip()
        match = re.search(r"/code/title(\d+)\.php$", href)
        if not match:
            continue
        number = match.group(1)
        if number in seen:
            continue
        seen.add(number)
        out.append((number, urljoin(base_url, href)))
    return out


def chapter_rows(html: str, *, base_url: str = BASE) -> List[Tuple[str, str, str]]:
    """Title-page ``CHAPTER N`` rows with ``/code/tNNcMMM.php`` HTML links."""

    from urllib.parse import urljoin

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    soup = BeautifulSoup(html or "", "html.parser")
    content = soup.find(id="contentsection") or soup
    out: List[Tuple[str, str, str]] = []
    seen: set[str] = set()
    for row in content.find_all("tr"):
        cells = row.find_all("td")
        if len(cells) < 2:
            continue
        label = _clean(cells[0].get_text(" "))
        match = re.match(r"CHAPTER\s+([\w\-]+)", label, re.IGNORECASE)
        if not match:
            continue
        number = match.group(1)
        if number in seen:
            continue
        link = cells[1].find("a", href=True)
        if link is None:
            continue
        seen.add(number)
        out.append((number, label, urljoin(base_url, str(link.get("href") or ""))))
    return out
