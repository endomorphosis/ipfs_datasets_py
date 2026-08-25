"""Official Maryland StatuteText HTML parser.

Adapted from Vaquill-AI/open-us-law ``scrapeMD.py`` (Apache-2.0).
Body lives in ``#StatuteText``; ``div.row`` chrome and center-aligned
divs are dropped. ``File Not Found`` / repealed stubs are skipped.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import List, Optional, Tuple
from urllib.parse import parse_qs, urlencode, urlparse

from .base_scraper import NormalizedStatute, StatuteMetadata

BASE = "https://mgaleg.maryland.gov/mgawebsite/Laws/StatuteText"
TOC_URL = "https://mgaleg.maryland.gov/mgawebsite/Laws/Statutes"
NEXT_API_URL = "https://mgaleg.maryland.gov/mgawebsite/api/Laws/GetNext"
PREV_API_URL = "https://mgaleg.maryland.gov/mgawebsite/api/Laws/GetPrevious"
_RESERVED = re.compile(r"\b(repealed|expired|reserved|renumbered|transferred)\b", re.IGNORECASE)
_HEAD_RE = re.compile(r"§\s*(?P<num>[\w.–\-]+)\.\s*(?P<head>.*)?")
_WS = re.compile(r"\s+")
# Vaquill scrapeMD: statute articles are lowercase g-codes; constitution is c*.
_STATUTE_CODE_RE = re.compile(r"^g[a-z]{2,3}$")
_ARTICLES_SELECT_RE = re.compile(
    r'<select[^>]*id="Articles"[^>]*>(.*?)</select>', re.DOTALL | re.IGNORECASE
)
_OPTION_RE = re.compile(r'<option[^>]+value="([^"]+)"[^>]*>([^<]+)</option>', re.IGNORECASE)
_FIRST_SECTION_SEEDS = (
    "1-101",
    "1-01",
    "01-101",
    "1-001",
    "1-1-01",
    "0-101",
    "2-101",
    "1A-01",
    "1-100",
)


def _clean(text: str) -> str:
    return _WS.sub(" ", (text or "").replace("\xa0", " ")).strip()


def parse_maryland_section_html(
    html: str,
    *,
    source_url: str = "",
    code_name: str = "Maryland Code",
) -> Optional[NormalizedStatute]:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return None
    soup = BeautifulSoup(html or "", "html.parser")
    stat = soup.find(id="StatuteText")
    if stat is None:
        return None
    raw = stat.get_text("\n")
    if "File Not Found" in raw:
        return None
    if _RESERVED.search(raw[:400]):
        return None
    for tag in stat.find_all("div", class_="row"):
        tag.decompose()
    for tag in stat.find_all("div", style=re.compile(r"text-align\s*:\s*center", re.I)):
        tag.decompose()
    paras = [_clean(part) for part in stat.get_text("\n").split("\n")]
    paras = [part for part in paras if part]
    heading = ""
    number = ""
    name = ""
    if paras:
        match = _HEAD_RE.search(paras[0])
        if match:
            heading = paras[0]
            number = match.group("num").replace("–", "-").replace("—", "-")
            name = _clean(match.group("head") or "")
            paras = paras[1:]
    body = _clean(" ".join(paras))
    if len(body) < 40:
        return None
    query = parse_qs(urlparse(source_url).query)
    article = (query.get("article") or [""])[0]
    number = number or (query.get("section") or [""])[0]
    if not number:
        return None
    return NormalizedStatute(
        state_code="MD",
        state_name="Maryland",
        statute_id=f"{code_name} § {number}",
        code_name=code_name,
        section_number=number,
        section_name=(name or heading or f"Section {number}")[:200],
        full_text=body[:14000],
        source_url=source_url or f"{BASE}?article={article}&section={number}&enactments=false",
        official_cite=f"Md. Code § {number}",
        metadata=StatuteMetadata(),
        structured_data={
            "source_kind": "official_maryland_statute_text",
            "source_authority_class": "official",
            "discovery_method": "mgaleg_statute_text",
            "article_code": article.upper() if article else None,
            "skip_hydrate": True,
        },
    )


def configured_section_html_path() -> Optional[Path]:
    raw = str(os.environ.get("MARYLAND_SECTION_HTML") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None


def configured_toc_html_path() -> Optional[Path]:
    raw = str(os.environ.get("MARYLAND_TOC_HTML") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None


def parse_get_next_envelope(body: str) -> Optional[str]:
    """Parse GetNext/GetPrevious .NET XML ``<string>`` or quoted JSON."""

    from .maryland_constitution import parse_get_next_envelope as _parse

    return _parse(body)


def is_statute_article_code(code: str) -> bool:
    return bool(_STATUTE_CODE_RE.match(str(code or "").strip()))


def statute_articles(html: str) -> List[Tuple[str, str]]:
    """Statute ``g*`` rows from ``<select id="Articles">`` (skip constitution ``c*``)."""

    match = _ARTICLES_SELECT_RE.search(html or "")
    if not match:
        return []
    out: List[Tuple[str, str]] = []
    seen: set[str] = set()
    for code, display in _OPTION_RE.findall(match.group(1)):
        code = code.strip()
        display = display.strip()
        if not code or not display or not is_statute_article_code(code):
            continue
        if code.lower() in seen:
            continue
        seen.add(code.lower())
        name = display.split(" - (")[0].strip() or display
        out.append((code, name))
    return out


def get_next_url(article_code: str, section_code: str) -> str:
    return f"{NEXT_API_URL}?{urlencode({'articleCode': article_code, 'sectionCode': section_code, 'enactments': 'False'})}"


def get_previous_url(article_code: str, section_code: str) -> str:
    return f"{PREV_API_URL}?{urlencode({'articleCode': article_code, 'sectionCode': section_code, 'enactments': 'False'})}"


def parse_section_code(code: str) -> Tuple[str, str, str]:
    """Split ``2-201`` / ``1-1-01`` into title, subtitle, section tokens."""

    token = str(code or "").strip()
    parts = token.split("-")
    if len(parts) == 3:
        return parts[0], parts[1], parts[2]
    if len(parts) == 2:
        title = parts[0]
        rest = parts[1]
        match = re.match(r"^([0-9]+[A-Z]?)([0-9]{2}(?:\.[0-9]+)?)$", rest)
        if match is not None:
            return title, match.group(1), match.group(2)
        return title, rest, rest
    return token, "0", token


def first_section_seeds() -> Tuple[str, ...]:
    return _FIRST_SECTION_SEEDS
