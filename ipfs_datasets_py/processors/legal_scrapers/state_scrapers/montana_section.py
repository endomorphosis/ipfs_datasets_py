"""Official Montana MCA section HTML parser.

Adapted from Vaquill-AI/open-us-law ``scrapeMT.py`` (Apache-2.0).
Canonical host is ``mca.legmt.gov``. Body lives in ``.section-content``;
``.history-content`` is dropped.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import List, Optional, Tuple

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


def parse_title_numbers(text: str) -> List[str]:
    """Expand ``TITLE 5`` / ``TITLES 8 AND 9`` labels."""

    raw = str(text or "")
    match = re.match(r"(?i)\s*TITLES\s+(\d+)\s+AND\s+(\d+)\b", raw)
    if match:
        return [match.group(1), match.group(2)]
    match = re.match(r"(?i)\s*TITLES\s+(\d+)\s+THROUGH\s+(\d+)\b", raw)
    if match:
        return [str(n) for n in range(int(match.group(1)), int(match.group(2)) + 1)]
    match = re.match(r"(?i)\s*TITLE\s+(\d+)\b", raw)
    if match:
        return [match.group(1)]
    return []


def title_toc_items(html: str, *, base_url: str = f"{BASE}/") -> List[Tuple[str, str, str]]:
    """``.title-toc-content`` / ``.mca-toc-nav`` title rows."""

    from urllib.parse import urljoin

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    soup = BeautifulSoup(html or "", "html.parser")
    nav = soup.find(class_="mca-toc-nav") or soup.find(class_="mca-content mca-toc") or soup
    container = nav.find(class_="title-toc-content") or nav
    out: List[Tuple[str, str, str]] = []
    seen: set[str] = set()
    for item in container.find_all("li"):
        link = item.find("a", href=True)
        reserved = item.find("span", class_="reserved")
        raw = _clean((link or reserved or item).get_text(" "))
        for number in parse_title_numbers(raw):
            if number in seen:
                continue
            seen.add(number)
            href = str(link.get("href") or "") if link is not None else ""
            out.append((number, raw or f"Title {number}", urljoin(base_url, href) if href else base_url))
    return out


def structure_toc_items(
    html: str, *, level: str, container_class: str, base_url: str = f"{BASE}/"
) -> List[Tuple[str, str, str]]:
    """Chapter/part/section TOC ``li.line`` / ``li.heading`` rows."""

    from urllib.parse import urljoin

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    soup = BeautifulSoup(html or "", "html.parser")
    container = soup.find(class_=container_class) or soup
    out: List[Tuple[str, str, str]] = []
    seen: set[str] = set()
    for item in container.find_all("li"):
        link = item.find("a", href=True)
        citation = item.find("span", class_="citation")
        raw = _clean((link or item).get_text(" "))
        if level == "section":
            number = _clean(citation.get_text(" ")) if citation is not None else ""
            if not number:
                match = re.search(r"\b(\d+(?:-\d+){1,3})\b", raw)
                number = match.group(1) if match else ""
        else:
            match = re.search(rf"(?i)\b{re.escape(level)}\s+([\w][\w\-]*?)(?:\.|$|\s)", raw)
            if not match or re.search(r"(?i)\bthrough\b", raw):
                continue
            number = match.group(1).rstrip(".")
        if not number or number in seen:
            continue
        seen.add(number)
        href = str(link.get("href") or "") if link is not None else ""
        out.append((number, raw or f"{level} {number}", urljoin(base_url, href) if href else base_url))
    return out
