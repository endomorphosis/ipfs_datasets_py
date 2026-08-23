"""Official West Virginia full-code HTML dump parser.

Vaquill notes ``wvcodeentire.htm`` as the full-code dump. Local path:
``WEST_VIRGINIA_CODE_HTML``.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import List, Optional, Tuple

from .base_scraper import NormalizedStatute, StatuteMetadata

_SECTION_RE = re.compile(
    r"(?m)^(?:§|&sect;)\s*(?P<num>\d+[A-Za-z]?-\d+[A-Za-z]?-\d+[A-Za-z0-9.]*)\.\s*(?P<head>[^\n]+)"
)
_WS = re.compile(r"\s+")
_RESERVED = re.compile(r"\b(repealed|reserved|expired|omitted)\b", re.IGNORECASE)


BASE = "https://code.wvlegislature.gov"
_PATH_TOKEN = r"\d+[A-Z]?"


def section_url(section_number: str) -> str:
    return f"{BASE}/{section_number}/"


def chapter_options(html: str) -> List[Tuple[str, str]]:
    """``select#sel-chapter`` options, including alpha chapters such as ``17H``."""

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    soup = BeautifulSoup(html or "", "html.parser")
    select = soup.find("select", id="sel-chapter")
    if select is None:
        return []
    out: List[Tuple[str, str]] = []
    seen: set[str] = set()
    for option in select.find_all("option"):
        number = str(option.get("value") or "").strip()
        if not number or not re.match(rf"^{_PATH_TOKEN}$", number) or number in seen:
            continue
        seen.add(number)
        name = _WS.sub(" ", (option.get_text(" ") or "").replace("\xa0", " ")).strip()
        out.append((number, name or f"Chapter {number}"))
    return out


def article_heads(html: str, *, base_url: str = BASE) -> List[Tuple[str, str, str]]:
    """``.art-head`` article links (``/61-2/``)."""

    from urllib.parse import urljoin

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    soup = BeautifulSoup(html or "", "html.parser")
    out: List[Tuple[str, str, str]] = []
    seen: set[str] = set()
    for head in soup.find_all(class_="art-head"):
        anchor = head.find("a", href=True)
        if anchor is None:
            continue
        href = str(anchor.get("href") or "").strip()
        match = re.search(rf"/({_PATH_TOKEN})-({_PATH_TOKEN})/?$", href)
        if not match:
            continue
        number = match.group(2)
        if number in seen:
            continue
        seen.add(number)
        name = _WS.sub(" ", (head.get_text(" ") or "").replace("\xa0", " ")).strip()
        out.append((number, name, urljoin(base_url.rstrip("/") + "/", href)))
    return out


def section_heads(html: str, *, base_url: str = BASE) -> List[Tuple[str, str, str]]:
    """``.sec-head`` section links (``/61-2-1/``)."""

    from urllib.parse import urljoin

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    soup = BeautifulSoup(html or "", "html.parser")
    out: List[Tuple[str, str, str]] = []
    seen: set[str] = set()
    for head in soup.find_all(class_="sec-head"):
        anchor = head.find("a", href=True)
        if anchor is None:
            continue
        href = str(anchor.get("href") or "").strip()
        match = re.search(rf"/({_PATH_TOKEN}-{_PATH_TOKEN}-{_PATH_TOKEN})/?$", href)
        if not match:
            continue
        number = match.group(1)
        if number in seen:
            continue
        seen.add(number)
        name = _WS.sub(" ", (head.get_text(" ") or "").replace("\xa0", " ")).strip()
        out.append((number, name, urljoin(base_url.rstrip("/") + "/", href)))
    return out


def parse_west_virginia_code_html(
    html: str,
    *,
    code_name: str = "West Virginia Code",
    max_statutes: Optional[int] = None,
) -> List[NormalizedStatute]:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        text = html
    else:
        soup = BeautifulSoup(html or "", "html.parser")
        for tag in soup(["script", "style", "nav", "header", "footer"]):
            tag.decompose()
        text = soup.get_text("\n", strip=True)
    matches = list(_SECTION_RE.finditer(text))
    statutes: List[NormalizedStatute] = []
    for index, match in enumerate(matches):
        if max_statutes is not None and len(statutes) >= int(max_statutes):
            break
        number = match.group("num")
        heading = match.group("head").strip()
        if _RESERVED.search(heading):
            continue
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        body = _WS.sub(" ", text[start:end]).strip()
        if len(body) < 40:
            continue
        parts = number.split("-")
        statutes.append(
            NormalizedStatute(
                state_code="WV",
                state_name="West Virginia",
                statute_id=f"{code_name} § {number}",
                code_name=code_name,
                chapter_number=parts[0] if parts else None,
                section_number=number,
                section_name=heading[:200],
                full_text=body[:14000],
                source_url=section_url(number),
                official_cite=f"W. Va. Code § {number}",
                metadata=StatuteMetadata(),
                structured_data={
                    "source_kind": "official_west_virginia_code_dump",
                    "source_authority_class": "official",
                    "discovery_method": "wvcodeentire_html",
                    "skip_hydrate": True,
                },
            )
        )
    return statutes


def configured_code_html_path() -> Optional[Path]:
    raw = str(os.environ.get("WEST_VIRGINIA_CODE_HTML") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None
