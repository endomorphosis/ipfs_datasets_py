"""Official Mississippi Code section HTML parser.

Adapted from the billstatus ``code_sections`` tree in ``mississippi.py``.
Vaquill lists Mississippi as in-progress; this is the official HTML
parser, env-gated to a local dump.

Local dump: ``MISSISSIPPI_SECTION_HTML``.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import List, Optional, Tuple
from urllib.parse import urlparse

from .base_scraper import NormalizedStatute, StatuteMetadata

BILLSTATUS = "https://billstatus.ls.state.ms.us/documents/2024/html/code_sections"
_HEAD_RE = re.compile(
    r"(?m)^\s*(?:§\s*)?(?P<section>\d{1,3}-\d{1,3}-\d{1,4}(?:\.[0-9A-Za-z]+)?)\s*[.–—-]\s*(?P<title>.+)$"
)
_URL_RE = re.compile(
    r"/code_sections/(?P<title>\d{1,3})/(?P<rest>\d{8})(?:_\d+)?\.(?:htm|html|xml)$",
    re.IGNORECASE,
)
_RESERVED = re.compile(r"\b(repealed|reserved|expired|renumbered)\b", re.IGNORECASE)
_WS = re.compile(r"\s+")


def _clean(text: str) -> str:
    return _WS.sub(" ", (text or "").replace("\xa0", " ")).strip()


def code_section_links(html: str, *, base_url: str = BILLSTATUS) -> List[Tuple[str, str, str]]:
    """Title-index ``/code_sections/097/00030019.htm`` rows."""

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
        number = section_number_from_url(href)
        if not number or number in seen:
            continue
        seen.add(number)
        name = _clean(anchor.get_text(" ")) or f"Section {number}"
        out.append((number, name, urljoin(base_url.rstrip("/") + "/", href)))
    return out


def section_number_from_url(url: str) -> str:
    match = _URL_RE.search(str(url or ""))
    if not match:
        return ""
    title = str(int(match.group("title")))
    rest = match.group("rest")
    chapter = str(int(rest[:4]))
    section = rest[4:].lstrip("0") or "0"
    return f"{title}-{chapter}-{section}"


def parse_mississippi_section_html(
    html: str,
    *,
    source_url: str = "",
    code_name: str = "Mississippi Code",
    max_statutes: Optional[int] = None,
) -> List[NormalizedStatute]:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    soup = BeautifulSoup(html or "", "html.parser")
    for tag in soup(["script", "style", "nav", "header", "footer", "noscript", "form"]):
        tag.decompose()
    text = soup.get_text("\n", strip=True)
    matches = list(_HEAD_RE.finditer(text))
    statutes: List[NormalizedStatute] = []
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
        parts = number.split("-")
        official = source_url or f"{BILLSTATUS}/{parts[0].zfill(3)}/"
        host = (urlparse(official).hostname or "").lower()
        if "justia" in host:
            official = f"{BILLSTATUS}/{parts[0].zfill(3)}/"
        statutes.append(
            NormalizedStatute(
                state_code="MS",
                state_name="Mississippi",
                statute_id=f"{code_name} § {number}",
                code_name=code_name,
                title_number=parts[0] if parts else None,
                chapter_number=parts[1] if len(parts) > 1 else None,
                section_number=number,
                section_name=heading[:200],
                full_text=body[:14000],
                source_url=official,
                official_cite=f"Miss. Code Ann. § {number}",
                metadata=StatuteMetadata(),
                structured_data={
                    "source_kind": "official_mississippi_code_section_html",
                    "source_authority_class": "official",
                    "discovery_method": "official_billstatus_code_section",
                    "skip_hydrate": True,
                },
            )
        )
    if statutes:
        return statutes
    number = section_number_from_url(source_url)
    body = _clean(text)
    if not number or len(body) < 40:
        return []
    if _RESERVED.search(body[:160]):
        return []
    parts = number.split("-")
    return [
        NormalizedStatute(
            state_code="MS",
            state_name="Mississippi",
            statute_id=f"{code_name} § {number}",
            code_name=code_name,
            title_number=parts[0] if parts else None,
            chapter_number=parts[1] if len(parts) > 1 else None,
            section_number=number,
            section_name=f"Section {number}",
            full_text=body[:14000],
            source_url=source_url or f"{BILLSTATUS}/{parts[0].zfill(3)}/",
            official_cite=f"Miss. Code Ann. § {number}",
            metadata=StatuteMetadata(),
            structured_data={
                "source_kind": "official_mississippi_code_section_html",
                "source_authority_class": "official",
                "discovery_method": "official_billstatus_code_section",
                "skip_hydrate": True,
            },
        )
    ]


def configured_section_html_path() -> Optional[Path]:
    raw = str(os.environ.get("MISSISSIPPI_SECTION_HTML") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None
