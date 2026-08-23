"""Official Arizona Revised Statutes section HTML parser.

Adapted from Vaquill-AI/open-us-law ``scrapeAZ.py`` (Apache-2.0).
Body lives in ``.content-sidebar-wrap .first`` paragraph tags.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import List, Optional, Tuple

from .base_scraper import NormalizedStatute, StatuteMetadata

BASE = "https://www.azleg.gov"
_HEAD_RE = re.compile(r"^\s*(\d+-\d+(?:\.\d+)?)\s*[-–]\s*(.+)$")
_URL_RE = re.compile(r"/ars/(\d+)/([0-9A-Za-z-]+)\.htm$", re.IGNORECASE)
_ARS_DETAIL_RE = re.compile(r"arsDetail/?\?title=(\d+)", re.IGNORECASE)
_RESERVED = re.compile(r"\b(repealed|reserved|expired|renumbered)\b", re.IGNORECASE)
_WS = re.compile(r"\s+")


def _clean(text: str) -> str:
    return _WS.sub(" ", (text or "").replace("\xa0", " ")).strip()


def parse_arizona_section_html(
    html: str,
    *,
    source_url: str = "",
    code_name: str = "Arizona Revised Statutes",
) -> Optional[NormalizedStatute]:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return None
    soup = BeautifulSoup(html or "", "html.parser")
    wrap = soup.find(class_="content-sidebar-wrap")
    first = wrap.find(class_="first") if wrap is not None else None
    container = first or wrap
    if container is None:
        return None
    paras = [_clean(para.get_text(" ")) for para in container.find_all("p")]
    paras = [para for para in paras if para]
    if not paras:
        return None
    heading = paras[0]
    body = _clean(" ".join(paras[1:] or paras))
    if len(body) < 40:
        return None
    if _RESERVED.search(heading) or _RESERVED.search(body[:160]):
        return None
    match = _HEAD_RE.match(heading)
    number = match.group(1) if match else ""
    name = match.group(2).strip() if match else heading
    url_match = _URL_RE.search(source_url or "")
    title = url_match.group(1) if url_match else (number.split("-", 1)[0] if number else "")
    if url_match and not number:
        number = f"{url_match.group(1)}-{url_match.group(2)}"
    if not number:
        return None
    return NormalizedStatute(
        state_code="AZ",
        state_name="Arizona",
        statute_id=f"{code_name} § {number}",
        code_name=code_name,
        title_number=title or None,
        section_number=number,
        section_name=name[:200],
        full_text=body[:14000],
        source_url=source_url or f"{BASE}/arsOverview/",
        official_cite=f"Ariz. Rev. Stat. § {number}",
        metadata=StatuteMetadata(),
        structured_data={
            "source_kind": "official_arizona_ars_html",
            "source_authority_class": "official",
            "discovery_method": "azleg_content_sidebar_wrap",
            "skip_hydrate": True,
        },
    )


def configured_section_html_path() -> Optional[Path]:
    raw = str(os.environ.get("ARIZONA_SECTION_HTML") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None


def title_links(html: str, *, base_url: str = BASE) -> List[Tuple[str, str]]:
    """``arsDetail?title=N`` rows from the ARS TOC."""

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
        match = _ARS_DETAIL_RE.search(href)
        if not match:
            continue
        number = match.group(1)
        if number in seen:
            continue
        seen.add(number)
        out.append((number, urljoin(base_url.rstrip("/") + "/", href)))
    out.sort(key=lambda row: int(row[0]))
    return out


def accordion_section_links(html: str, *, base_url: str = BASE) -> List[Tuple[str, str, str]]:
    """Title-page ``.colleft a`` section rows (``13-1101``)."""

    from urllib.parse import urljoin

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    soup = BeautifulSoup(html or "", "html.parser")
    out: List[Tuple[str, str, str]] = []
    seen: set[str] = set()
    for left in soup.find_all(class_="colleft"):
        anchor = left.find("a", href=True)
        if anchor is None:
            continue
        number = _clean(anchor.get_text(" "))
        if not number or number.lower() in seen:
            continue
        seen.add(number.lower())
        parent = left.parent
        right = parent.find(class_="colright") if parent is not None else None
        name = _clean(right.get_text(" ")) if right is not None else ""
        out.append((number, name, urljoin(base_url, str(anchor.get("href") or ""))))
    return out
