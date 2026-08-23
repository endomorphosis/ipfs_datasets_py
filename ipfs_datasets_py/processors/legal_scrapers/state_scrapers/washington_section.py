"""Official Washington RCW section HTML parser (contentWrapper).

Adapted from Vaquill-AI/open-us-law ``scrapeWA.py`` (Apache-2.0).
Section body is ``contentWrapper`` top-level ``div[2]``; history lives in
the ``margin-top:15pt`` sibling and is dropped. Notes are dropped.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import List, Optional, Tuple
from urllib.parse import parse_qs, urlparse

from .base_scraper import NormalizedStatute, StatuteMetadata

BASE = "https://app.leg.wa.gov/RCW"
_WS = re.compile(r"\s+")
_CITE_RE = re.compile(r"\b(\d+[A-Za-z]?(?:\.\d+[A-Za-z]?){1,3})\b")
_TITLE_HREF_RE = re.compile(r"default\.aspx\?Cite=([\w]+)$", re.IGNORECASE)
_CHAPTER_HREF_RE = re.compile(
    r"(?:/rcw/)?default\.aspx\?cite=([\w]+\.[\w]+)$", re.IGNORECASE
)
_RESERVED = re.compile(
    r"\b(repealed|reserved|expired|renumbered|deleted|transferred|recodified)\b",
    re.IGNORECASE,
)


def section_url(cite: str) -> str:
    return f"{BASE}/default.aspx?cite={cite}"


def _clean(text: str) -> str:
    return _WS.sub(" ", (text or "").replace("\xa0", " ")).strip()


def _cite_from_url(url: str) -> str:
    try:
        parsed = urlparse(url)
        values = parse_qs(parsed.query).get("cite") or parse_qs(parsed.query).get("Cite") or []
        return str(values[0] if values else "").strip()
    except Exception:
        return ""


def parse_washington_section_html(
    html: str,
    *,
    source_url: str = "",
    section_number: str = "",
    code_name: str = "Revised Code of Washington",
) -> Optional[NormalizedStatute]:
    """Parse one RCW section page; drop history bracket and notes."""

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return None

    soup = BeautifulSoup(html or "", "html.parser")
    wrapper = soup.find("div", id="contentWrapper")
    if wrapper is None:
        return None
    top_divs = wrapper.find_all("div", recursive=False)
    body_parts: List[str] = []
    heading = ""
    in_notes = False
    for index, div in enumerate(top_divs):
        style = str(div.get("style") or "")
        text = _clean(div.get_text(" "))
        if not text:
            continue
        if "margin-top:15pt" in style or (text.startswith("[") and "]" in text and len(text) < 400):
            continue
        if text.lower() == "notes:":
            in_notes = True
            continue
        if in_notes:
            continue
        if index <= 1:
            continue
        if not heading:
            heading = text[:200]
        body_parts.append(text)
    body = _clean(" ".join(body_parts))
    if len(body) < 40:
        return None
    if _RESERVED.search(heading) or _RESERVED.search(body[:120]):
        return None
    cite = section_number or _cite_from_url(source_url)
    if not cite:
        match = _CITE_RE.search(heading) or _CITE_RE.search(body)
        cite = match.group(1) if match else ""
    if not cite:
        caption = soup.select_one("#ContentPlaceHolder1_pnlTitleBlock h1")
        caption_text = _clean(caption.get_text(" ")) if caption else ""
        match = _CITE_RE.search(caption_text)
        cite = match.group(1) if match else ""
    if not cite:
        return None
    title_number = cite.split(".", 1)[0]
    caption_node = soup.select_one("#ContentPlaceHolder1_pnlTitleBlock h2")
    caption = _clean(caption_node.get_text(" ")) if caption_node else heading
    return NormalizedStatute(
        state_code="WA",
        state_name="Washington",
        statute_id=f"{code_name} § {cite}",
        code_name=code_name,
        title_number=title_number,
        section_number=cite,
        section_name=(caption or heading or cite)[:200],
        full_text=body[:14000],
        source_url=source_url or section_url(cite),
        official_cite=f"Wash. Rev. Code § {cite}",
        metadata=StatuteMetadata(),
        structured_data={
            "source_kind": "official_washington_contentwrapper",
            "source_authority_class": "official",
            "discovery_method": "rcw_contentwrapper_div2",
            "skip_hydrate": True,
        },
    )


def configured_section_html_path() -> Optional[Path]:
    raw = str(os.environ.get("WASHINGTON_SECTION_HTML") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None


def title_cites(html: str) -> List[str]:
    """Title cites from the RCW TOC (``default.aspx?Cite=9A``)."""

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    soup = BeautifulSoup(html or "", "html.parser")
    out: List[str] = []
    seen = set()
    for anchor in soup.find_all("a", href=True):
        href = str(anchor.get("href") or "").strip()
        match = _TITLE_HREF_RE.search(href)
        if not match:
            continue
        cite = match.group(1)
        if cite in seen or "." in cite:
            continue
        seen.add(cite)
        out.append(cite)
    return out


def chapter_cites(html: str, *, title_cite: str = "") -> List[str]:
    """Two-segment chapter cites (``/rcw/default.aspx?cite=9A.32``)."""

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    soup = BeautifulSoup(html or "", "html.parser")
    wrapper = soup.find("div", id="contentWrapper") or soup
    out: List[str] = []
    seen = set()
    prefix = f"{title_cite}." if title_cite else ""
    for anchor in wrapper.find_all("a", href=True):
        href = str(anchor.get("href") or "").strip()
        match = _CHAPTER_HREF_RE.search(href)
        if not match:
            continue
        cite = match.group(1)
        if prefix and not cite.startswith(prefix):
            continue
        if cite.count(".") != 1 or cite in seen:
            continue
        seen.add(cite)
        out.append(cite)
    return out


def chapter_section_rows(html: str) -> List[Tuple[str, str, str]]:
    """Section cites from chapter table rows (number cell + heading cell)."""

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    soup = BeautifulSoup(html or "", "html.parser")
    wrapper = soup.find("div", id="contentWrapper") or soup
    out: List[Tuple[str, str, str]] = []
    seen = set()
    for row in wrapper.find_all("tr"):
        cells = row.find_all("td")
        if len(cells) < 3:
            continue
        link = cells[1].find("a", href=True)
        if link is None:
            continue
        cite = _clean(link.get_text(" "))
        if not cite or not cite[0].isdigit():
            continue
        if cite in seen:
            continue
        seen.add(cite)
        heading = _clean(cells[2].get_text(" "))
        out.append((cite, heading, section_url(cite)))
    return out
