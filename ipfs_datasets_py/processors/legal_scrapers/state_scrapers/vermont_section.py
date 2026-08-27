"""Official Vermont section HTML parser.

Adapted from Vaquill-AI/open-us-law ``scrapeVT.py`` (Apache-2.0).
Body lives in ``ul.statutes-detail``; the bold heading is skipped and
``(Added`` / ``(Amended`` suffixes are dropped.
"""

from __future__ import annotations

import os
import re
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse

from .base_scraper import NormalizedStatute, StatuteMetadata

BASE = "https://legislature.vermont.gov"
_ADDENDUM_RE = re.compile(r"^\((?:Added|Amended)", re.IGNORECASE)
_SPLIT_RE = re.compile(r"\s+(?=\((?:Added|Amended)\b)", re.IGNORECASE)
_SECTION_URL_RE = re.compile(
    r"/statutes/section/(?P<title>[\w.\-]+)/(?P<chapter>[\w.\-]+)/(?P<section>[\w.\-]+)/?$",
    re.IGNORECASE,
)
_TITLE_HREF_RE = re.compile(r"(?:^|/)statutes/title/([\w.\-]+)/?$", re.IGNORECASE)
_CHAPTER_HREF_RE = re.compile(
    r"(?:^|/)statutes/chapter/([\w.\-]+)/([\w.\-]+)/?$", re.IGNORECASE
)
_SUBCHAPTER_HREF_RE = re.compile(
    r"(?:^|/)statutes/(subchapter|article)/([\w.\-]+)/([\w.\-]+)/([\w.\-]+)/?$",
    re.IGNORECASE,
)
_HEAD_RE = re.compile(r"§\s*(?P<num>[0-9A-Za-z.\-–—]+)\.\s*(?P<head>.+)")
_EXEC_ORDER_HEAD_RE = re.compile(
    r"\bExecutive\s+Order\s+No\.\s*(?P<num>[0-9A-Za-z.\-–—]+)\b",
    re.IGNORECASE,
)
_EXEC_ORDER_REVOKED_BODY_RE = re.compile(
    r"^(?:revoked(?:\s+and\s+rescinded)?|rescinded(?:\s+and\s+revoked)?)\s+"
    r"by\s+Executive\s+Order\s+No\.",
    re.IGNORECASE,
)
_WS = re.compile(r"\s+")
_TERMINAL_KIND_PATTERN = (
    r"repealed|expired|reserved|renumbered|redesignated|transferred|"
    r"recodified|eliminated|omitted|intentionally\s+left\s+blank"
)
_FUTURE_EFFECTIVE_RE = re.compile(
    r"\b(?:effective|eff\.?)\s+"
    r"(?P<date>[A-Z][a-z]+\s+\d{1,2},\s+\d{4})\b",
    re.IGNORECASE,
)


def _clean(text: str) -> str:
    return _WS.sub(" ", (text or "").replace("\xa0", " ").replace("’", "'")).strip()


def _normalise_number(raw: str) -> str:
    raw = str(raw or "").replace("–", "-").replace("—", "-")
    if not raw or not any(char.isdigit() for char in raw):
        return raw
    match = re.match(r"^0*(\d+)(.*)", raw)
    return match.group(1) + match.group(2) if match else raw


def terminal_disposition_from_label(
    label: str,
    *,
    observed_on: Optional[date] = None,
) -> Optional[str]:
    """Classify only an explicit source label for a nonoperative unit.

    A future-effective repeal remains active at the observation date.  Broad
    prose mentions such as ``repeal of statutes`` are deliberately rejected;
    the marker must be bracketed or follow an official section/chapter label.
    """

    value = _clean(label)
    if not value:
        return None
    future = _FUTURE_EFFECTIVE_RE.search(value)
    if future is not None:
        try:
            effective = datetime.strptime(future.group("date"), "%B %d, %Y").date()
        except ValueError:
            return None
        if effective > (observed_on or date.today()):
            return None
    bracketed = re.search(
        rf"[\[(]\s*(?P<kind>{_TERMINAL_KIND_PATTERN})\b",
        value,
        flags=re.IGNORECASE,
    )
    section_labelled = re.match(
        r"^§{1,2}\s*.+?(?:[:.]|\s[\-–—])\s*"
        rf"(?P<kind>{_TERMINAL_KIND_PATTERN})\b",
        value,
        flags=re.IGNORECASE,
    )
    hierarchy_labelled = re.match(
        r"^(?:title|chapter|subchapter|article)\s+[0-9A-Za-z.\-]+"
        r"\s*(?:[:.\-–—]|\s)\s*"
        rf"(?P<kind>{_TERMINAL_KIND_PATTERN})\b",
        value,
        flags=re.IGNORECASE,
    )
    match = bracketed or section_labelled or hierarchy_labelled
    if match is None:
        return None
    return re.sub(r"\s+", "_", str(match.group("kind")).lower())


def source_bound_terminal_disposition(
    html: str,
    *,
    source_url: str,
    frontier_label: str,
    expected_level: str,
    observed_on: Optional[date] = None,
) -> Optional[Dict[str, str]]:
    """Bind a terminal classification to one exact official VT locator."""

    parsed = urlparse(str(source_url or ""))
    if parsed.scheme.lower() != "https" or parsed.hostname != "legislature.vermont.gov":
        return None
    level = str(expected_level or "").strip().lower()
    patterns = {
        "title": _TITLE_HREF_RE,
        "chapter": _CHAPTER_HREF_RE,
        "subchapter": _SUBCHAPTER_HREF_RE,
        "section": _SECTION_URL_RE,
    }
    pattern = patterns.get(level)
    if pattern is None or pattern.search(parsed.path) is None:
        return None
    disposition = terminal_disposition_from_label(
        frontier_label,
        observed_on=observed_on,
    )
    if disposition is None:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return None
        soup = BeautifulSoup(html or "", "html.parser")
        candidates = []
        for selector in ("h1", "h2", "h3", "h4", "b", "ul.statutes-detail"):
            node = soup.select_one(selector)
            if node is not None:
                candidates.append(_clean(node.get_text(" ", strip=True)))
        for candidate in candidates:
            disposition = terminal_disposition_from_label(
                candidate,
                observed_on=observed_on,
            )
            if disposition is not None:
                break
        section_match = _SECTION_URL_RE.search(parsed.path)
        if (
            disposition is None
            and level == "section"
            and section_match is not None
            and section_match.group("title").upper().endswith("APPENDIX")
        ):
            detail = soup.find("ul", class_="statutes-detail")
            detail_paragraphs = (
                [
                    _clean(node.get_text(" "))
                    for node in detail.find_all("p")
                    if _clean(node.get_text(" "))
                ]
                if detail is not None
                else []
            )
            if any(
                _EXEC_ORDER_REVOKED_BODY_RE.match(text)
                for text in detail_paragraphs
            ):
                disposition = "revoked"
    if disposition is None:
        return None
    return {
        "disposition": disposition,
        "source_url": source_url,
        "source_label": _clean(frontier_label),
    }


def parse_vermont_section_html(
    html: str,
    *,
    source_url: str = "",
    code_name: str = "Vermont Statutes",
    observed_on: Optional[date] = None,
) -> Optional[NormalizedStatute]:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return None
    soup = BeautifulSoup(html or "", "html.parser")
    container = soup.find("ul", class_="statutes-detail") or soup.find("div", id="main-content") or soup
    paras: list[str] = []
    heading = ""
    for para in container.find_all("p"):
        text = _clean(para.get_text(" "))
        if not text:
            continue
        bold = para.find("b")
        if bold is not None:
            bold_text = _clean(bold.get_text(" "))
            rest = text.replace(bold_text, "").strip()
            if not rest:
                heading = bold_text
                continue
        if _ADDENDUM_RE.match(text):
            continue
        parts = _SPLIT_RE.split(text, maxsplit=1)
        body_part = parts[0].strip()
        if body_part:
            paras.append(body_part)
    body = _clean(" ".join(paras))
    if not body:
        return None
    if (
        _EXEC_ORDER_HEAD_RE.search(heading) is not None
        and _EXEC_ORDER_REVOKED_BODY_RE.match(body) is not None
    ):
        return None
    if terminal_disposition_from_label(
        heading,
        observed_on=observed_on,
    ) is not None or terminal_disposition_from_label(
        body[:160],
        observed_on=observed_on,
    ) is not None:
        return None
    url_match = _SECTION_URL_RE.search(source_url or "")
    title = _normalise_number(url_match.group("title")) if url_match else ""
    chapter = _normalise_number(url_match.group("chapter")) if url_match else ""
    locator_number = _normalise_number(url_match.group("section")) if url_match else ""
    head_match = _HEAD_RE.search(heading)
    if head_match:
        number = _normalise_number(head_match.group("num"))
        name = head_match.group("head").strip()
    else:
        executive_order = _EXEC_ORDER_HEAD_RE.search(heading)
        number = (
            _normalise_number(executive_order.group("num"))
            if executive_order is not None
            else locator_number
        )
        name = heading or f"Section {locator_number}"
    if not number:
        return None
    return NormalizedStatute(
        state_code="VT",
        state_name="Vermont",
        statute_id=f"{code_name} § {number}",
        code_name=code_name,
        title_number=title or None,
        chapter_number=chapter or None,
        section_number=number,
        section_name=name[:200],
        full_text=body,
        source_url=source_url or f"{BASE}/statutes/",
        official_cite=f"{title} V.S.A. § {number}" if title else f"Vt. Stat. Ann. § {number}",
        metadata=StatuteMetadata(),
        structured_data={
            "source_kind": "official_vermont_statutes_detail",
            "source_authority_class": "official",
            "discovery_method": "legislature_statutes_detail",
            "skip_hydrate": True,
        },
    )


def configured_section_html_path() -> Optional[Path]:
    raw = str(os.environ.get("VERMONT_SECTION_HTML") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None


def configured_toc_html_path() -> Optional[Path]:
    raw = str(os.environ.get("VERMONT_TOC_HTML") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None


def parse_configured_toc_html() -> List[Tuple[str, str]]:
    path = configured_toc_html_path()
    if path is None:
        return []
    return title_links(path.read_text(encoding="utf-8", errors="replace"))


def _absolute(href: str, *, base_url: str = BASE) -> str:
    token = str(href or "").strip()
    if token.startswith("http"):
        return token
    if token.startswith("/"):
        return f"{base_url}{token}"
    return f"{base_url.rstrip('/')}/{token.lstrip('/')}"


def title_links(html: str, *, base_url: str = BASE) -> List[Tuple[str, str]]:
    """Title URLs from ``ul.statutes-list`` (relative ``statutes/title/01`` included)."""

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    soup = BeautifulSoup(html or "", "html.parser")
    toc = soup.find("ul", class_="statutes-list") or soup
    out: List[Tuple[str, str]] = []
    seen = set()
    for anchor in toc.find_all("a", href=True):
        href = str(anchor.get("href") or "").strip()
        match = _TITLE_HREF_RE.search(href.replace("\\", "/"))
        if not match:
            continue
        number = _normalise_number(match.group(1))
        url = _absolute(href, base_url=base_url).rstrip("/")
        if url in seen:
            continue
        seen.add(url)
        out.append((url, number))
    return out


def chapter_links(html: str, *, base_url: str = BASE) -> List[Tuple[str, str]]:
    """Chapter URLs ``/statutes/chapter/{title}/{chapter}``."""

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    soup = BeautifulSoup(html or "", "html.parser")
    out: List[Tuple[str, str]] = []
    seen = set()
    for anchor in soup.find_all("a", href=True):
        href = str(anchor.get("href") or "").strip()
        match = _CHAPTER_HREF_RE.search(href.replace("\\", "/"))
        if not match:
            continue
        number = _normalise_number(match.group(2))
        url = _absolute(href, base_url=base_url).rstrip("/")
        if url in seen:
            continue
        seen.add(url)
        out.append((url, number))
    return out


def subchapter_links(html: str, *, base_url: str = BASE) -> List[Tuple[str, str]]:
    """Subchapter/article URLs nested under a chapter."""

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    soup = BeautifulSoup(html or "", "html.parser")
    out: List[Tuple[str, str]] = []
    seen = set()
    for anchor in soup.find_all("a", href=True):
        href = str(anchor.get("href") or "").strip()
        match = _SUBCHAPTER_HREF_RE.search(href.replace("\\", "/"))
        if not match:
            continue
        number = _normalise_number(match.group(4))
        url = _absolute(href, base_url=base_url).rstrip("/")
        if url in seen:
            continue
        seen.add(url)
        out.append((url, number))
    return out


def section_links(html: str, *, base_url: str = BASE) -> List[Tuple[str, str]]:
    """Section URLs ``/statutes/section/{title}/{chapter}/{section}``."""

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    soup = BeautifulSoup(html or "", "html.parser")
    out: List[Tuple[str, str]] = []
    seen = set()
    for anchor in soup.find_all("a", href=True):
        href = str(anchor.get("href") or "").strip()
        match = _SECTION_URL_RE.search(href.replace("\\", "/"))
        if not match:
            continue
        number = _normalise_number(match.group("section"))
        url = _absolute(href, base_url=base_url).rstrip("/")
        if url in seen:
            continue
        seen.add(url)
        name = _clean(anchor.get_text(" "))
        out.append((url, name or number))
    return out
