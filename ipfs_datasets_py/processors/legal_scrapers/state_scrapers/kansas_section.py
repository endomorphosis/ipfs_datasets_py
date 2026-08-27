"""Official Kansas Statutes section HTML parser.

Adapted from Vaquill-AI/open-us-law ``scrapeKS.py`` (Apache-2.0).
Body lives in ``.statute-body`` table[1] ``p.p_pt`` paragraphs; table[2]
is history and is dropped. ``Accept-Encoding`` must omit Brotli because
kslegislature.gov otherwise serves undecodable ``br`` payloads.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import List, Optional, Tuple

from .base_scraper import NormalizedStatute, StatuteMetadata

SESSION = "b2025_26"
BASE = f"https://www.kslegislature.gov/{SESSION}/laws"
_TERMINAL_CAPTION = re.compile(
    r"^(?P<disposition>repealed|reserved|expired|omitted)\s*[.;]?$",
    re.IGNORECASE,
)
_TERMINAL_RENUMBERED = re.compile(r"^renumbered\s+(?:as|to)\b", re.IGNORECASE)
_KSA_ID_PATTERN = (
    r"[\da-z]+-[\da-z]+(?:,[\da-z]+)*(?:-[\da-z]+(?:,[\da-z]+)*)*"
)
_KSA_RE = re.compile(rf"^({_KSA_ID_PATTERN})", re.IGNORECASE)
_WS = re.compile(r"\s+")
BROTLI_SAFE_ACCEPT_ENCODING = "gzip, deflate"
_CHAPTER_HREF_RE = re.compile(r"(?:^|/)(\d+)_\d+_\d+_chapter/?$", re.IGNORECASE)
_ARTICLE_HREF_RE = re.compile(r"(?:^|/)(\d+)_(\d+)_\d+_article/?$", re.IGNORECASE)
_SECTION_HREF_RE = re.compile(
    r"(?:^|/)([0-9a-z]+)_([0-9a-z]+)_([0-9a-z]+)_section/"
    r"([0-9a-z]+)_([0-9a-z]+)_([0-9a-z]+)_k/?$",
    re.IGNORECASE,
)
_KSA_ROW_RE = re.compile(rf"^({_KSA_ID_PATTERN})\s*[-–]", re.IGNORECASE)


def _page_section_number(soup: object) -> tuple[bool, str]:
    """Return the official page-level KSA identity and meta-tag presence."""

    find = getattr(soup, "find", None)
    node = (
        find(
            "meta",
            attrs={
                "name": re.compile(
                    r"^T_KSASECTEXT_S_KSANUM$",
                    re.IGNORECASE,
                )
            },
        )
        if callable(find)
        else None
    )
    if node is None:
        return False, ""
    return True, _clean(str(node.get("content") or "")).rstrip(".")


def _clean(text: str) -> str:
    return _WS.sub(
        " ", (text or "").replace("\xa0", " ").replace("\u2002", " ")
    ).strip()


def parse_kansas_section_html(
    html: str,
    *,
    source_url: str,
    section_number: str = "",
    code_name: str = "Kansas Statutes",
) -> Optional[NormalizedStatute]:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return None
    soup = BeautifulSoup(html or "", "html.parser")
    page_number_present, page_number = _page_section_number(soup)
    body_node = soup.find(class_="statute-body")
    if body_node is None:
        return None
    number_node = body_node.select_one(".stat_5f_number")
    statute_table = (
        number_node.find_parent("table") if number_node is not None else None
    )
    if statute_table is None:
        tables = body_node.find_all("table")
        statute_table = tables[1] if len(tables) >= 2 else None
    if statute_table is None:
        return None
    cell = statute_table.find("td")
    if cell is None:
        return None
    paras = [_clean(p.get_text(" ")) for p in cell.find_all("p")]
    paras = [p for p in paras if p]
    if not paras:
        fallback = _clean(cell.get_text(" "))
        if fallback:
            paras = [fallback]
    body = _clean(" ".join(paras))
    if len(body) < 40:
        return None
    number_parts = [
        node
        for node in statute_table.select(".stat_5f_number")
        if node.select_one(".stat_5f_number") is None
    ]
    body_number = "".join(
        _clean(node.get_text(" ")) for node in number_parts
    ).rstrip(".")
    if not body_number:
        match = _KSA_RE.match(body)
        body_number = match.group(1) if match else ""
    number = str(section_number or body_number).strip()
    if not number:
        return None
    caption_node = soup.select_one(".stat_5f_caption")
    caption = _clean(caption_node.get_text(" ")) if caption_node else paras[0][:200]
    if classify_kansas_terminal_caption(caption):
        return None
    chapter = number.split("-", 1)[0]
    return NormalizedStatute(
        state_code="KS",
        state_name="Kansas",
        statute_id=f"{code_name} § {number}",
        code_name=code_name,
        chapter_number=chapter,
        section_number=number,
        section_name=caption[:200],
        full_text=body,
        source_url=source_url or f"{BASE}/",
        official_cite=f"K.S.A. § {number}",
        metadata=StatuteMetadata(),
        structured_data={
            "source_kind": "official_kansas_statute_body",
            "source_authority_class": "official",
            "discovery_method": "kslegislature_statute_body_table",
            "source_body_section_number": body_number,
            "source_page_section_number": page_number,
            "source_page_section_number_present": page_number_present,
            "skip_hydrate": True,
        },
    )


def classify_kansas_terminal_caption(caption: str) -> str:
    """Return a terminal disposition only for an explicit placeholder caption.

    Kansas has operative repeal provisions whose captions contain words such
    as ``repealed`` or ``reserved``.  Those words are legal substance, not a
    source disposition, so substring classification would silently delete
    public law (including K.S.A. 66-1,133 and 66-1,134).
    """

    normalized = _clean(caption).lstrip("\u2002\u2003\u2009")
    match = _TERMINAL_CAPTION.fullmatch(normalized)
    if match is not None:
        return str(match.group("disposition") or "").casefold()
    if _TERMINAL_RENUMBERED.match(normalized):
        return "renumbered"
    return ""


def classify_kansas_terminal_section_html(html: str) -> str:
    """Classify an official section page only when its caption is terminal."""

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return ""
    soup = BeautifulSoup(html or "", "html.parser")
    caption_node = soup.select_one(".stat_5f_caption")
    caption = _clean(caption_node.get_text(" ")) if caption_node is not None else ""
    return classify_kansas_terminal_caption(caption)


def configured_section_html_path() -> Optional[Path]:
    raw = str(os.environ.get("KANSAS_SECTION_HTML") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None


def configured_statute_table_html_path() -> Optional[Path]:
    raw = str(os.environ.get("KANSAS_STATUTE_TABLE_HTML") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None


def parse_configured_statute_table_html() -> List[Tuple[str, str, str]]:
    path = configured_statute_table_html_path()
    if path is None:
        return []
    return chapter_rows(path.read_text(encoding="utf-8", errors="replace"))


def _statute_table_anchors(html: str):
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    soup = BeautifulSoup(html or "", "html.parser")
    table = soup.find(id="statute") or soup
    return table.find_all("a", href=True)


def chapter_rows(
    html: str, *, base_url: str = f"{BASE}/"
) -> List[Tuple[str, str, str]]:
    """``#statute`` chapter rows (``001_000_0000_chapter/``)."""

    from urllib.parse import urljoin

    out: List[Tuple[str, str, str]] = []
    seen: set[str] = set()
    for anchor in _statute_table_anchors(html):
        href = str(anchor.get("href") or "").strip()
        match = _CHAPTER_HREF_RE.search(href.split("?", 1)[0])
        if not match:
            continue
        number = str(int(match.group(1)))
        if number in seen:
            continue
        seen.add(number)
        name = _clean(
            anchor.find_parent("tr").get_text(" ")
            if anchor.find_parent("tr")
            else anchor.get_text(" ")
        )
        out.append((number, name or f"Chapter {number}", urljoin(base_url, href)))
    return out


def article_rows(
    html: str, *, base_url: str = f"{BASE}/"
) -> List[Tuple[str, str, str]]:
    """``#statute`` article rows (``001_002_0000_article/``)."""

    from urllib.parse import urljoin

    out: List[Tuple[str, str, str]] = []
    seen: set[str] = set()
    for anchor in _statute_table_anchors(html):
        href = str(anchor.get("href") or "").strip()
        match = _ARTICLE_HREF_RE.search(href.split("?", 1)[0])
        if not match:
            continue
        number = str(int(match.group(2)))
        if number in seen:
            continue
        seen.add(number)
        name = _clean(
            anchor.find_parent("tr").get_text(" ")
            if anchor.find_parent("tr")
            else anchor.get_text(" ")
        )
        out.append((number, name or f"Article {number}", urljoin(base_url, href)))
    return out


def section_rows(
    html: str, *, base_url: str = f"{BASE}/"
) -> List[Tuple[str, str, str]]:
    """``#statute`` section rows (``..._section/..._k/``, KSA ``1-201``)."""

    from urllib.parse import urljoin, urlparse

    out: List[Tuple[str, str, str]] = []
    seen: set[str] = set()
    for anchor in _statute_table_anchors(html):
        href = str(anchor.get("href") or "").strip()
        if not _SECTION_HREF_RE.search(href.split("?", 1)[0]):
            continue
        row = anchor.find_parent("tr")
        row_text = _clean(
            row.get_text(" ") if row is not None else anchor.get_text(" ")
        )
        match = _KSA_ROW_RE.match(row_text) or _KSA_RE.match(row_text)
        number = match.group(1).rstrip(".") if match else ""
        if not number or number.lower() in seen:
            continue
        resolution_href = href
        if str(base_url or "").rstrip("/") == BASE and re.match(
            r"^(?:\.\./)+",
            href,
        ):
            # The parser's standalone/default-base compatibility path lacks
            # the article directory needed to interpret parent traversal.
            # Live discovery always supplies that exact nested article URL.
            resolution_href = re.sub(r"^(?:\.\./)+", "", href)
        resolved = urljoin(base_url, resolution_href)
        parsed = urlparse(resolved)
        base_parsed = urlparse(base_url)
        if (
            parsed.scheme.lower() != "https"
            or parsed.hostname != base_parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or not parsed.path.startswith(f"/{SESSION}/laws/")
            or _SECTION_HREF_RE.search(parsed.path) is None
        ):
            continue
        seen.add(number.lower())
        out.append((number, row_text or f"Section {number}", resolved))
    return out
