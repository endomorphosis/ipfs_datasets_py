"""Official Nebraska section HTML parser.

Adapted from Vaquill-AI/open-us-law ``scrapeNE.py`` (Apache-2.0).
Body lives in ``#statute_text`` / ``.statute-body``; history/source classes
are dropped, and repealed stubs are skipped.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urljoin, urlparse

from .base_scraper import NormalizedStatute, StatuteMetadata

BASE = "https://nebraskalegislature.gov"
_SELECTORS = (
    ("div", {"id": "statute_text"}),
    ("div", {"id": "statuteText"}),
    ("div", {"class": "statute-body"}),
    ("div", {"class": "statute_body"}),
    ("div", {"class": "statute"}),
)
_TERMINAL_HEADNOTE_RE = re.compile(
    r"^\s*(?P<kind>repealed|expired|expiration\s+of\s+(?:the\s+)?act|"
    r"reserved|renumbered|deleted|"
    r"unconstitutional|transferred(?:\s+to)?)\b",
    re.IGNORECASE,
)
_SPECIAL_TERMINAL_HEADNOTE_PATTERNS = (
    (re.compile(r"^Act,\s*expired\.$", re.IGNORECASE), "expired"),
    (
        re.compile(
            r"^Note: This section was transferred in \d{4} from section "
            r"(?P<former>[\dA-Za-z]+(?:[-.,][\dA-Za-z]+)+)\s*\. Laws \d{4}, "
            r"LB \d+, section \d+ provided for a repeal of section "
            r"(?P=former) with an operative date of [A-Za-z]+ \d{1,2}, "
            r"\d{4}\.$",
            re.IGNORECASE,
        ),
        "repealed",
    ),
    (
        re.compile(
            r"^Note: According to the provisions of section "
            r"[\dA-Za-z]+(?:[-.,][\dA-Za-z]+)+, the act comprising this "
            r"article expired by its own limitation on [A-Za-z]+ \d{1,2}, "
            r"\d{4}\. The entire article has therefor been omitted\.$",
            re.IGNORECASE,
        ),
        "expired",
    ),
)
_WS = re.compile(r"\s+")
# Vaquill scrapeNE: chapter tokens include alpha suffixes (76A) and hyphens;
# section ids include dotted forms such as 25-2740.04. Keep comma-thousands
# (2-32,113) from the live Nebraska index as well.
_CHAPTER_HREF_RE = re.compile(
    r"/laws/browse-chapters\.php\?chapter=([\w\-]+)$", re.IGNORECASE
)
_SECTION_HREF_RE = re.compile(
    r"/laws/statutes\.php\?statute=([\w.,\-]+)$", re.IGNORECASE
)
_SECTION_NUMBER_RE = re.compile(r"^[\dA-Za-z]+(?:[-.,][\dA-Za-z]+)+$")
_STRONG_LOCATOR_RE = re.compile(
    r"^(?P<number>[\dA-Za-z]+(?:[-.,][\dA-Za-z]+)+)\.\s*(?P<headnote>.*)$"
)
_ARTICLE_HEADING_RE = re.compile(
    r"^\s*ARTICLE\s+([\w\-]+)\b[\.\s\-:]*(.*)$", re.IGNORECASE
)


def _clean(text: str) -> str:
    return _WS.sub(" ", (text or "").replace("\xa0", " ")).strip()


def classify_nebraska_special_terminal_headnote(value: str) -> Optional[str]:
    """Type the complete exceptional no-body lifecycle notes used by Nebraska."""

    headnote = _clean(value).replace(" ,", ",")
    for pattern, disposition in _SPECIAL_TERMINAL_HEADNOTE_PATTERNS:
        if pattern.fullmatch(headnote):
            return disposition
    return None


def _direct_nebraska_operative_text(panel: object) -> list[str]:
    """Return only identity-panel body text, preserving direct-child order.

    The current official site normally wraps operative text in direct ``p``
    children, but a small number of pages expose it as a bare text node.  The
    nested ``Source`` block and surrounding navigation must never become law
    text, so this deliberately does not recurse into any other child tag.
    """

    try:
        from bs4 import Comment, NavigableString
    except ImportError:
        return []
    out: list[str] = []
    for child in getattr(panel, "children", ()):
        if isinstance(child, Comment):
            continue
        if isinstance(child, NavigableString):
            text = _clean(str(child))
        elif str(getattr(child, "name", "")).casefold() == "p":
            classes = " ".join(child.get("class") or []).casefold()
            if any(
                token in classes
                for token in ("history", "source", "fa-ul", "annotation")
            ):
                continue
            text = _clean(child.get_text(" ", strip=True))
        else:
            continue
        if text:
            out.append(text)
    return out


def classify_nebraska_terminal_section_html(
    html: str,
    *,
    source_url: str,
) -> Optional[str]:
    """Type only an identity-bound official terminal detail-page stub.

    Current Nebraska pages place the selected locator in a direct ``h2`` and
    a terminal headnote such as ``Repealed. Laws ...`` in a direct ``h3``.
    Operative direct body text defeats terminal classification, preventing
    ordinary provisions that merely discuss repeal or transfer from being
    excluded.  Body text may be either a direct paragraph or, on the current
    official template, a direct text node.
    """

    query = parse_qs(urlparse(source_url).query)
    expected_number = _clean(str((query.get("statute") or [""])[0] or ""))
    if not is_nebraska_section_number(expected_number):
        return None
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return None
    soup = BeautifulSoup(html or "", "html.parser")
    panel = soup.select_one("#stat_panel .statute") or soup.select_one("div.statute")
    if panel is None:
        return None
    if _direct_nebraska_operative_text(panel):
        return None
    heading_node = panel.find("h2", recursive=False)
    observed_number = _clean(
        heading_node.get_text(" ", strip=True) if heading_node is not None else ""
    ).rstrip(". ")
    if observed_number:
        if observed_number != expected_number:
            return None
        headnote_node = panel.find("h3", recursive=False)
        headnote = _clean(
            headnote_node.get_text(" ", strip=True)
            if headnote_node is not None
            else ""
        )
    else:
        # Nebraska also retains a legacy official template whose identity and
        # headnote share one direct ``strong`` node.  Bind the complete prefix
        # to the URL-selected locator before typing a no-body terminal stub.
        strong_node = panel.find("strong", recursive=False)
        strong_text = _clean(
            strong_node.get_text(" ", strip=True)
            if strong_node is not None
            else ""
        )
        prefix = f"{expected_number}."
        if not strong_text.startswith(prefix):
            return None
        headnote = _clean(strong_text[len(prefix) :])
    match = _TERMINAL_HEADNOTE_RE.match(headnote)
    if not match:
        return classify_nebraska_special_terminal_headnote(headnote)
    kind = match.group("kind").casefold()
    if kind.startswith("transferred"):
        return "transferred"
    if kind.startswith("expiration"):
        return "expired"
    return kind


def parse_nebraska_section_html(
    html: str,
    *,
    source_url: str = "",
    code_name: str = "Nebraska Revised Statutes",
) -> Optional[NormalizedStatute]:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return None
    soup = BeautifulSoup(html or "", "html.parser")
    if classify_nebraska_terminal_section_html(html, source_url=source_url):
        return None
    body = soup.select_one("#stat_panel .statute") or soup.select_one("div.statute")
    if body is None:
        for name, kwargs in _SELECTORS:
            body = soup.find(name, **kwargs)
            if body is not None:
                break
    if body is None:
        body = soup.find("main") or soup.find("div", class_="card-body")
    if body is None:
        return None
    number_heading = body.find("h2", recursive=False)
    headnote_node = body.find("h3", recursive=False)
    heading = _clean(
        headnote_node.get_text(" ", strip=True) if headnote_node is not None else ""
    )
    strong_node = body.find("strong", recursive=False)
    strong_text = _clean(
        strong_node.get_text(" ", strip=True) if strong_node is not None else ""
    )
    full = _clean(" ".join(_direct_nebraska_operative_text(body)))
    if len(full) < 10:
        return None
    query = parse_qs(urlparse(source_url).query)
    selected_number = _clean(str((query.get("statute") or [""])[0] or ""))
    observed_number = _clean(
        number_heading.get_text(" ") if number_heading is not None else ""
    ).rstrip(". ")
    if selected_number:
        # The official catalog/URL selects the legal identity.  Bind the body
        # to the same displayed locator instead of admitting unrelated error
        # or navigation HTML under a syntactically valid request URL.
        if not is_nebraska_section_number(selected_number):
            return None
        if observed_number:
            if observed_number != selected_number:
                return None
        else:
            prefix = f"{selected_number}."
            if not strong_text.startswith(prefix):
                return None
            heading = _clean(strong_text[len(prefix) :])
        number = selected_number
    else:
        strong_match = _STRONG_LOCATOR_RE.fullmatch(strong_text)
        if observed_number:
            number = observed_number
        elif strong_match is not None:
            number = strong_match.group("number")
            heading = _clean(strong_match.group("headnote"))
        else:
            number = ""
    if not is_nebraska_section_number(number):
        return None
    name = heading if heading and heading != number else f"Section {number}"
    chapter = number.split("-", 1)[0]
    return NormalizedStatute(
        state_code="NE",
        state_name="Nebraska",
        statute_id=f"{code_name} § {number}",
        code_name=code_name,
        chapter_number=chapter,
        section_number=number,
        section_name=name[:200],
        full_text=full,
        source_url=source_url or f"{BASE}/laws/statutes.php?statute={number}",
        official_cite=f"Neb. Rev. Stat. § {number}",
        metadata=StatuteMetadata(),
        structured_data={
            "source_kind": "official_nebraska_statutes_html",
            "source_authority_class": "official",
            "discovery_method": "nebraskalegislature_statute_text",
            "skip_hydrate": True,
        },
    )


def configured_section_html_path() -> Optional[Path]:
    raw = str(os.environ.get("NEBRASKA_SECTION_HTML") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None


def configured_toc_html_path() -> Optional[Path]:
    raw = str(os.environ.get("NEBRASKA_TOC_HTML") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None


def configured_chapter_html_path() -> Optional[Path]:
    raw = str(os.environ.get("NEBRASKA_CHAPTER_HTML") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None


def parse_configured_toc_html() -> List[Tuple[str, str, str]]:
    path = configured_toc_html_path()
    if path is None:
        return []
    return chapter_links(path.read_text(encoding="utf-8", errors="replace"))


def parse_configured_chapter_html() -> List[Tuple[str, str, str]]:
    path = configured_chapter_html_path()
    if path is None:
        return []
    return section_links(path.read_text(encoding="utf-8", errors="replace"))


def is_nebraska_section_number(value: str) -> bool:
    token = str(value or "").strip()
    return bool(token) and bool(_SECTION_NUMBER_RE.match(token))


def chapter_links(html: str, *, base_url: str = f"{BASE}/laws/browse-statutes.php") -> List[Tuple[str, str, str]]:
    """Chapter rows from browse-statutes.php (includes ``76A``)."""

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    soup = BeautifulSoup(html or "", "html.parser")
    out: List[Tuple[str, str, str]] = []
    seen: set[str] = set()
    for anchor in soup.find_all("a", href=True):
        href = str(anchor.get("href") or "").strip()
        match = _CHAPTER_HREF_RE.search(href)
        if not match:
            continue
        number = match.group(1)
        if number in seen:
            continue
        seen.add(number)
        name = _clean(anchor.get_text(" ")) or f"Chapter {number}"
        out.append((number, name, urljoin(base_url, href)))
    return out


def section_links(html: str, *, base_url: str = f"{BASE}/laws/browse-chapters.php") -> List[Tuple[str, str, str]]:
    """Primary section rows from one official chapter catalog.

    Current catalogs put the selected locator in the first of three direct
    ``td.row`` spans.  The summary span may itself link to transferred or
    cross-referenced locators; those are not members of this chapter's leaf
    frontier.  Bare-anchor parsing remains only for the legacy/configured
    fixture shape when no official rows are present.
    """

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    soup = BeautifulSoup(html or "", "html.parser")
    out: List[Tuple[str, str, str]] = []
    seen: set[str] = set()
    candidates: List[Tuple[object, str]] = []
    official_rows = soup.select("td.row")
    if official_rows:
        for row in official_rows:
            spans = row.find_all("span", recursive=False)
            if len(spans) != 3:
                return []
            primary = spans[0].find_all("a", href=True, recursive=False)
            if len(primary) != 1:
                return []
            candidates.append((primary[0], _clean(spans[1].get_text(" "))))
    else:
        candidates = [(anchor, "") for anchor in soup.find_all("a", href=True)]

    for anchor, row_name in candidates:
        href = str(anchor.get("href") or "").strip()
        if "print=true" in href.lower():
            continue
        match = _SECTION_HREF_RE.search(href.split("&", 1)[0])
        if not match:
            continue
        number = match.group(1)
        if not is_nebraska_section_number(number):
            continue
        if number.lower() in seen:
            return []
        seen.add(number.lower())
        name = row_name or _clean(anchor.get_text(" ")) or f"Section {number}"
        out.append((number, name, urljoin(base_url, href)))
    return out


def chapter_structure(html: str, *, base_url: str = f"{BASE}/laws/browse-chapters.php") -> List[Dict[str, str]]:
    """Document-order sections with intervening ``ARTICLE N`` parents."""

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    soup = BeautifulSoup(html or "", "html.parser")
    out: List[Dict[str, str]] = []
    seen: set[str] = set()
    current_article = ""
    current_article_name = ""
    for element in soup.find_all(
        ["a", "h1", "h2", "h3", "h4", "h5", "h6", "strong", "b", "p", "li"]
    ):
        if element.name != "a":
            text = _clean(element.get_text(" "))
            if not text:
                continue
            match = _ARTICLE_HEADING_RE.match(text)
            if match:
                current_article = match.group(1)
                current_article_name = _clean(match.group(2) or "")
            continue
        href = str(element.get("href") or "").strip()
        if "print=true" in href.lower():
            continue
        match = _SECTION_HREF_RE.search(href.split("&", 1)[0])
        if not match:
            continue
        number = match.group(1)
        if not is_nebraska_section_number(number) or number.lower() in seen:
            continue
        seen.add(number.lower())
        out.append(
            {
                "section_number": number,
                "section_name": _clean(element.get_text(" ")) or f"Section {number}",
                "source_url": urljoin(base_url, href),
                "article_number": current_article,
                "article_name": current_article_name,
            }
        )
    return out
