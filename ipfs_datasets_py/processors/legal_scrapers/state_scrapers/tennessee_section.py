"""Official Tennessee Code Annotated section HTML parser.

Adapted from the TGA ``main`` / ``#content`` walk in ``tennessee.py``.
Vaquill lists Tennessee as in-progress; this is the official HTML-structure
parser, env-gated to a local dump.

Local dump: ``TENNESSEE_SECTION_HTML``.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import List, Optional, Tuple

from .base_scraper import NormalizedStatute, StatuteMetadata

BASE = "https://www.tn.gov/tga/statutes"
_SECTION_LABEL_RE = re.compile(
    r"(?:§|Section)?\s*(?P<section>\d{1,2}-\d{1,2}-\d{1,4}(?:\.[0-9A-Za-z]+)?)(?:\s*[.–—-]\s*(?P<title>.+))?",
    re.IGNORECASE,
)
_URL_SECTION_RE = re.compile(
    r"section[/_-]?([0-9]+(?:-[0-9A-Za-z.]+)+)",
    re.IGNORECASE,
)
_TITLE_HREF_RE = re.compile(r"/title-?(?P<title>\d{1,2})(?:/|$)", re.IGNORECASE)
_OFFICIAL_SECTION_RE = re.compile(
    r"(?:/tca/|/statutes?/|/code/)[^?#]*section[/_-]?([0-9]+(?:-[0-9A-Za-z.]+)+)",
    re.IGNORECASE,
)
_RESERVED = re.compile(r"\b(repealed|reserved|expired|renumbered)\b", re.IGNORECASE)
_WS = re.compile(r"\s+")


def _clean(text: str) -> str:
    return _WS.sub(" ", (text or "").replace("\xa0", " ")).strip()


def title_url(number: str) -> str:
    return f"{BASE}/title-{int(str(number).strip())}/"


def title_links(html: str, *, base_url: str = f"{BASE}.html") -> List[Tuple[str, str, str]]:
    """Index ``/tga/statutes/title-39/`` rows."""

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    soup = BeautifulSoup(html or "", "html.parser")
    out: List[Tuple[str, str, str]] = []
    seen: set[str] = set()
    for anchor in soup.find_all("a", href=True):
        href = str(anchor.get("href") or "")
        match = _TITLE_HREF_RE.search(href)
        if not match:
            continue
        number = str(int(match.group("title")))
        if number in seen:
            continue
        seen.add(number)
        name = _clean(anchor.get_text(" ")) or f"Title {number}"
        out.append((number, name, title_url(number)))
    return out


def section_links(html: str, *, base_url: str = BASE) -> List[Tuple[str, str, str]]:
    """Title-page ``/statutes/.../section-39-13-202`` rows."""

    from urllib.parse import urljoin

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    soup = BeautifulSoup(html or "", "html.parser")
    out: List[Tuple[str, str, str]] = []
    seen: set[str] = set()
    for anchor in soup.find_all("a", href=True):
        href = str(anchor.get("href") or "").strip()
        match = _OFFICIAL_SECTION_RE.search(href)
        if not match:
            continue
        number = match.group(1)
        if number in seen:
            continue
        seen.add(number)
        name = _clean(anchor.get_text(" ")) or f"Section {number}"
        out.append((number, name, urljoin(base_url.rstrip("/") + "/", href)))
    return out


def parse_tennessee_section_html(
    html: str,
    *,
    source_url: str = "",
    code_name: str = "Tennessee Code Annotated",
    max_statutes: Optional[int] = None,
) -> List[NormalizedStatute]:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    soup = BeautifulSoup(html or "", "html.parser")
    content = (
        soup.select_one("main")
        or soup.select_one("article")
        or soup.select_one("#content")
        or soup.find("body")
        or soup
    )
    for tag in content.find_all(["script", "style", "nav", "header", "footer", "noscript", "form"]):
        tag.decompose()
    text = content.get_text("\n", strip=True)
    matches = list(
        re.finditer(
            r"(?m)^\s*(?:§|Section)?\s*(?P<section>\d{1,2}-\d{1,2}-\d{1,4}(?:\.[0-9A-Za-z]+)?)\s*[.–—-]\s*(?P<title>.+)$",
            text,
        )
    )
    statutes: List[NormalizedStatute] = []
    if matches:
        for index, match in enumerate(matches):
            if max_statutes is not None and len(statutes) >= int(max_statutes):
                break
            number = match.group("section")
            heading = match.group("title").strip()
            if _RESERVED.search(heading):
                continue
            start = match.end()
            end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
            body = _clean(text[start:end])
            if len(body) < 40:
                continue
            statutes.append(_row(code_name, number, heading, body, source_url))
        return statutes

    heading_node = content.find(["h1", "h2", "h3"])
    heading = _clean(heading_node.get_text(" ") if heading_node else "")
    body = _clean(text)
    if heading and body.startswith(heading):
        body = _clean(body[len(heading) :])
    if len(body) < 40:
        return []
    number = ""
    url_match = _URL_SECTION_RE.search(source_url or "")
    if url_match:
        number = url_match.group(1)
    label = _SECTION_LABEL_RE.search(heading) or _SECTION_LABEL_RE.search(text[:400])
    name = heading
    if label:
        number = number or label.group("section")
        if label.group("title"):
            name = label.group("title").strip()
    if not number or _RESERVED.search(name or heading):
        return []
    return [_row(code_name, number, name or f"Section {number}", body, source_url)]


def _row(
    code_name: str,
    number: str,
    heading: str,
    body: str,
    source_url: str,
) -> NormalizedStatute:
    parts = number.split("-")
    return NormalizedStatute(
        state_code="TN",
        state_name="Tennessee",
        statute_id=f"{code_name} § {number}",
        code_name=code_name,
        title_number=parts[0] if parts else None,
        chapter_number=parts[1] if len(parts) > 1 else None,
        section_number=number,
        section_name=heading[:200],
        full_text=body,
        source_url=source_url
        or f"https://www.tn.gov/tga/statutes/title-{parts[0] if parts else '1'}/",
        official_cite=f"Tenn. Code Ann. § {number}",
        metadata=StatuteMetadata(),
        structured_data={
            "source_kind": "official_tennessee_code_html",
            "source_authority_class": "official",
            "discovery_method": "official_tga_capitol_hierarchy",
            "skip_hydrate": True,
        },
    )


def configured_section_html_path() -> Optional[Path]:
    raw = str(os.environ.get("TENNESSEE_SECTION_HTML") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None
