"""Official Minnesota Revisor section HTML parser.

Adapted from Vaquill-AI/open-us-law ``scrapeMN.py`` (Apache-2.0).
Body lives in ``.section``; ``shn`` headings are skipped and ``.history``
is dropped.
"""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .base_scraper import NormalizedStatute, StatuteMetadata

BASE = "https://www.revisor.mn.gov/statutes"
_WS = re.compile(r"\s+")
_CITE_RE = re.compile(
    r"/statutes/cite/([0-9A-Za-z]+(?:[.-][0-9A-Za-z]+)+)/?$",
    re.IGNORECASE,
)
_SECTION_ID_RE = re.compile(r"^[\w.\-]+$")
_CHAPTER_ID_RE = re.compile(r"^[\w.\-]+$")
_TERMINAL_MARKER_RE = re.compile(r"^\[\s*(?P<marker>[^\]]+?)\s*\]$")
_SOURCE_EDITION_PREFIX_RE = re.compile(
    r"^(?:MS\s+\d{4}(?:\s+Supp)?|Supp)\s+",
    re.IGNORECASE,
)
_STATUTES_EDITION_RE = re.compile(r"^20\d{2} Minnesota Statutes$")

# One retained Revisor source-reference page uses a historical display
# citation that differs from the exact URL/id identity.  Bind that alias to
# the retained bytes so a future markup or content change fails closed.
_EXACT_TERMINAL_DISPLAY_CITATION_ALIASES = {
    "https://www.revisor.mn.gov/statutes/cite/124D.085": {
        "content_byte_size": 62353,
        "content_sha256": (
            "9c6cb6bc7f2cf1e840453b0a7b03307d8372358bf99669b40bfc2acd6aafad35"
        ),
        "display_citation": "124.085",
    },
    "https://www.revisor.mn.gov/statutes/cite/296.01-1": {
        "content_byte_size": 60883,
        "content_sha256": (
            "04a01e0bb5ce4817e0ca76ab1e9a67bfa80920ed4155adbbd9fcbbfc7dbb6893"
        ),
        "display_citation": "296.01",
    }
}


def _clean(text: str) -> str:
    return _WS.sub(" ", (text or "").replace("\xa0", " ")).strip()


def _minnesota_statutes_edition_from_soup(soup: Any) -> str:
    """Return the one exact Revisor statutes-edition heading, if present."""

    headers = soup.find_all(id="header")
    if len(headers) != 1:
        return ""
    headings = headers[0].find_all("h1")
    if len(headings) != 1:
        return ""
    edition = _clean(headings[0].get_text(" "))
    return edition if _STATUTES_EDITION_RE.fullmatch(edition) else ""


def minnesota_statutes_edition_from_html(html: str) -> str:
    """Extract the edition only from the Revisor ``#header > h1`` contract.

    Breadcrumbs, page titles, statutory prose, and source-reference prefixes
    can all mention other Minnesota Statutes editions.  None of those locations
    authorizes a current-edition claim, so ambiguous or changed header markup
    deliberately returns an empty value.
    """

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return ""
    soup = BeautifulSoup(html or "", "html.parser")
    return _minnesota_statutes_edition_from_soup(soup)


def parse_minnesota_section_html(
    html: str,
    *,
    source_url: str = "",
    code_name: str = "Minnesota Statutes",
    expected_edition: str = "",
    require_source_identity: bool = False,
) -> Optional[NormalizedStatute]:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return None
    soup = BeautifulSoup(html or "", "html.parser")
    observed_edition = _minnesota_statutes_edition_from_soup(soup)
    normalized_expected_edition = _clean(expected_edition)
    if (
        normalized_expected_edition
        and observed_edition != normalized_expected_edition
    ):
        return None
    section = soup.find(class_="section")
    if section is None:
        return None
    match = _CITE_RE.search(source_url or "")
    url_number = match.group(1) if match else ""
    if require_source_identity and (
        not url_number or str(section.get("id") or "") != f"stat.{url_number}"
    ):
        return None
    paras: list[str] = []
    heading = ""
    for element in section.find_all(recursive=False):
        classes = " ".join(element.get("class") or [])
        text = _clean(element.get_text(" "))
        if not text:
            continue
        if element.name in {"h1", "h2", "h3"} or "shn" in classes:
            heading = text
            continue
        if "history" in classes.lower():
            continue
        paras.append(text)
    body = _clean(" ".join(paras))
    # Some current operative Minnesota sections are intentionally only a few
    # words long.  The source DOM, not an arbitrary character floor, decides
    # whether this is statutory text.  Publication-wide minimum-text policy is
    # enforced after normalization by the caller.
    if not body:
        return None
    number = url_number
    if not number:
        token = heading.split()[0] if heading else ""
        number = token.rstrip(".")
    if not number:
        return None
    if require_source_identity:
        heading_number = heading.split()[0].rstrip(".") if heading else ""
        if heading_number.casefold() != number.casefold():
            return None
    return NormalizedStatute(
        state_code="MN",
        state_name="Minnesota",
        statute_id=f"{code_name} § {number}",
        code_name=code_name,
        chapter_number=number.split(".", 1)[0],
        section_number=number,
        section_name=(heading or f"Section {number}")[:200],
        full_text=body,
        source_url=source_url or f"{BASE}/cite/{number}",
        official_cite=f"Minn. Stat. § {number}",
        metadata=StatuteMetadata(),
        structured_data={
            "source_kind": "official_minnesota_statutes_html",
            "source_authority_class": "official",
            "discovery_method": "revisor_section_div",
            "skip_hydrate": True,
            **(
                {"source_edition": observed_edition}
                if observed_edition
                else {}
            ),
        },
    )


def _terminal_marker_disposition(marker: str) -> str:
    """Normalize one exact Revisor source-reference marker.

    These checks run only inside ``.sr``/``.sr_by_subd`` containers on a page
    with no operative ``.section`` container.  They therefore cannot turn an
    incidental word in statutory prose into a terminal disposition.
    """

    value = _clean(marker).casefold()
    if value.startswith(("impliedly repealed", "repealed")):
        return "repealed"
    if value.startswith("renumbered"):
        return "renumbered"
    if value.startswith("expired"):
        return "expired"
    if value.startswith("obsolete"):
        return "obsolete"
    if value.startswith("superseded"):
        return "superseded"
    if value.startswith("omitted"):
        return "omitted"
    if value.startswith("unnecessary"):
        return "unnecessary"
    if value.startswith("held unconstitutional"):
        return "unconstitutional"
    if value.startswith("never effective"):
        return "never_effective"
    if value.startswith("inoperative"):
        return "inoperative"
    if value.startswith("temporary"):
        return "temporary"
    if value.startswith(
        ("local", "private", "special", "no local approval filed")
    ):
        return "local_or_special"
    if " transferred to " in f" {value} " or " conveyed to " in f" {value} ":
        return "transferred"
    if value.startswith("deleted"):
        return "deleted"
    if value.startswith("uncodified"):
        return "uncodified"
    return ""


def _terminal_source_reference_dispositions(reference: str) -> List[str]:
    """Type lifecycle words in one exact ``.sr`` source-reference string.

    Most Revisor source references are a single bracketed marker.  A small
    current-edition set uses multiple direct paragraphs, prefixes markers with
    a paragraph/subdivision locator, places ``Renumbered`` just outside the
    target bracket, or omits one bracket.  The surrounding exact container and
    citation id remain authoritative; this grammar recognizes only lifecycle
    terms and leaves every other changed source-reference string unclassified.
    """

    candidate = _clean(reference)
    if not candidate or ("[" not in candidate and "]" not in candidate):
        return []
    marker_match = _TERMINAL_MARKER_RE.fullmatch(
        _SOURCE_EDITION_PREFIX_RE.sub("", candidate)
    )
    if marker_match is not None:
        disposition = _terminal_marker_disposition(marker_match.group("marker"))
        if disposition:
            return [disposition]

    value = candidate.casefold()
    patterns = (
        ("repealed", r"\brepealed\b"),
        ("renumbered", r"\brenumbered\b"),
        ("expired", r"\bexpired\b"),
        ("obsolete", r"\bobsolete\b"),
        ("superseded", r"\bsuperseded\b"),
        ("omitted", r"\bomitted\b"),
        ("unnecessary", r"\bunnecessary\b"),
        ("unconstitutional", r"\b(?:held\s+)?unconstitutional\b"),
        ("never_effective", r"\bnever\s+effective\b"),
        ("inoperative", r"\binoperative\b"),
        ("temporary", r"\btemporary\b"),
        ("transferred", r"\b(?:transferred|conveyed)\b"),
        ("deleted", r"\bdeleted\b"),
        ("uncodified", r"\buncodified\b"),
        (
            "local_or_special",
            r"\b(?:local|private|special)\b|\bno\s+local\s+approval\s+filed\b",
        ),
    )
    return sorted(
        disposition
        for disposition, pattern in patterns
        if re.search(pattern, value)
    )


def classify_minnesota_terminal_section_html(
    html: str,
    *,
    source_url: str,
    expected_edition: str = "",
) -> Optional[Dict[str, Any]]:
    """Classify an exact official source-reference-only section page.

    Current operative law is published in ``.section``.  Historical and other
    non-operative source references are published in an exact ``.sr`` or
    ``.sr_by_subd`` container keyed by the citation.  Every source block must
    be a bracketed, recognized terminal marker; mixed or changed markup fails
    closed and is left for review.
    """

    match = _CITE_RE.search(str(source_url or ""))
    section_number = match.group(1) if match else ""
    if not section_number:
        return None
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return None
    soup = BeautifulSoup(html or "", "html.parser")
    observed_edition = _minnesota_statutes_edition_from_soup(soup)
    normalized_expected_edition = _clean(expected_edition)
    if (
        normalized_expected_edition
        and observed_edition != normalized_expected_edition
    ):
        return None
    if soup.find(class_="section") is not None:
        return None

    expected_id = f"stat.{section_number}"
    containers = [
        node
        for node in soup.find_all(id=expected_id)
        if {"sr", "sr_by_subd"}.intersection(node.get("class") or [])
    ]
    if not containers:
        return None

    marker_texts: List[str] = []
    dispositions: List[str] = []
    source_blocks = 0
    for container in containers:
        classes = set(container.get("class") or [])
        if "sr_by_subd" in classes:
            blocks = container.find_all(class_="subd", recursive=False)
            if not blocks:
                return None
            candidates = []
            for block in blocks:
                paragraphs = block.find_all("p", recursive=False)
                block_id = str(block.get("id") or "")
                if (
                    not paragraphs
                    or not block_id.startswith(f"stat.{section_number}.")
                ):
                    return None
                candidates.extend(_clean(paragraph.get_text(" ")) for paragraph in paragraphs)
        else:
            if "sr" not in classes:
                return None
            candidate = _clean(container.get_text(" "))
            display_citation = section_number
            direct_bold = container.find("b", recursive=False)
            if direct_bold is not None:
                observed_display = _clean(direct_bold.get_text(" "))
                if observed_display.casefold() != section_number.casefold():
                    alias = _EXACT_TERMINAL_DISPLAY_CITATION_ALIASES.get(
                        str(source_url or "").strip()
                    )
                    raw = str(html or "").encode("utf-8")
                    if (
                        alias is None
                        or observed_display != str(alias["display_citation"])
                        or len(raw) != int(alias["content_byte_size"])
                        or hashlib.sha256(raw).hexdigest()
                        != str(alias["content_sha256"])
                    ):
                        return None
                    display_citation = observed_display
            candidate = re.sub(
                rf"^{re.escape(display_citation)}\s+",
                "",
                candidate,
            )
            candidates = [candidate]

        for candidate in candidates:
            source_blocks += 1
            candidate_dispositions = _terminal_source_reference_dispositions(
                candidate
            )
            if not candidate_dispositions:
                return None
            marker_texts.append(_clean(candidate))
            dispositions.extend(candidate_dispositions)

    if not source_blocks or not dispositions:
        return None
    unique_dispositions = sorted(set(dispositions))
    return {
        "closed": True,
        "disposition": "+".join(unique_dispositions),
        "dispositions": unique_dispositions,
        "marker_texts": marker_texts,
        "section_number": section_number,
        "source_blocks": source_blocks,
        **(
            {"source_edition": observed_edition}
            if observed_edition
            else {}
        ),
        "source_url": str(source_url),
    }


def _absolute(href: str, *, base_url: str = BASE) -> str:
    token = str(href or "").strip()
    if token.startswith("http"):
        return token
    if token.startswith("/"):
        return f"https://www.revisor.mn.gov{token}"
    return f"{base_url.rstrip('/')}/{token.lstrip('/')}"


def toc_part_rows(html: str) -> List[Tuple[str, str, str]]:
    """Part rows from ``#toc_table`` (chapter range + name)."""

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    soup = BeautifulSoup(html or "", "html.parser")
    table = soup.find(id="toc_table")
    if table is None:
        return []
    out: List[Tuple[str, str, str]] = []
    for row in table.find_all("tr"):
        cells = row.find_all("td")
        if not cells:
            continue
        link = cells[0].find("a", href=True)
        if link is None:
            continue
        chapter_range = _clean(link.get_text(" "))
        if not chapter_range:
            continue
        name = _clean(cells[1].get_text(" ")) if len(cells) > 1 else ""
        out.append((_absolute(str(link.get("href") or "")), chapter_range, name))
    return out


def chapter_table_rows(html: str) -> List[Tuple[str, str, str]]:
    """Chapter rows from ``#chapters_table`` (``2A``, ``169A`` included)."""

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    soup = BeautifulSoup(html or "", "html.parser")
    table = soup.find(id="chapters_table")
    if table is None:
        return []
    out: List[Tuple[str, str, str]] = []
    seen = set()
    for row in table.find_all("tr"):
        cells = row.find_all("td")
        if not cells:
            continue
        link = cells[0].find("a", href=True)
        if link is None:
            continue
        number = _clean(link.get_text(" "))
        if not number or not _CHAPTER_ID_RE.match(number) or "." in number:
            continue
        if number in seen:
            continue
        seen.add(number)
        name = _clean(cells[1].get_text(" ")) if len(cells) > 1 else ""
        out.append((number, name, _absolute(str(link.get("href") or ""))))
    return out


def chapter_analysis_section_rows(html: str) -> List[Tuple[str, str, str]]:
    """Section rows from ``#chapter_analysis`` tables (skip classed headings)."""

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    soup = BeautifulSoup(html or "", "html.parser")
    analysis = soup.find(id="chapter_analysis") or soup
    table = analysis.find("table") if analysis is not None else None
    if table is None:
        return []
    out: List[Tuple[str, str, str]] = []
    seen = set()
    for row in table.find_all("tr"):
        if row.get("class"):
            continue
        cells = row.find_all("td")
        if not cells:
            continue
        link = cells[0].find("a", href=True)
        if link is None:
            continue
        number = _clean(link.get_text(" "))
        if not number or not _SECTION_ID_RE.match(number):
            continue
        if number in seen:
            continue
        seen.add(number)
        name = _clean(cells[1].get_text(" ")) if len(cells) > 1 else ""
        href = str(link.get("href") or "").strip()
        url = _absolute(href) if href else f"{BASE}/cite/{number}"
        out.append((number, name, url))
    return out


def configured_section_html_path() -> Optional[Path]:
    raw = str(os.environ.get("MINNESOTA_SECTION_HTML") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None


def configured_toc_html_path() -> Optional[Path]:
    raw = str(os.environ.get("MINNESOTA_TOC_HTML") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None


def parse_configured_toc_html() -> List[Tuple[str, str, str]]:
    path = configured_toc_html_path()
    if path is None:
        return []
    return toc_part_rows(path.read_text(encoding="utf-8", errors="replace"))
