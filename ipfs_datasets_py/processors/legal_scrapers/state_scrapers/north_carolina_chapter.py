"""Official North Carolina ByChapter HTML parser.

Vaquill withdrew NC because nav/footer leaked into section bodies. This parser
keeps only statutory blocks from
``/EnactedLegislation/Statutes/HTML/ByChapter/Chapter_{N}.html``.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import List, Literal, Optional, Sequence, Tuple, TypedDict
from urllib.parse import urljoin

from .base_scraper import NormalizedStatute, StatuteMetadata

NAV_MARKERS = (
    "skip to main",
    "skip to content",
    "skip to navigation",
    "privacy policy",
    "site map",
    "sitemap",
    "copyright ©",
    "footer navigation",
    "cookie policy",
    "terms of use",
)
_SECTION_RE = re.compile(
    r"(?m)^(?:§|&sect;|&#167;)\s*(?P<num>[0-9A-Za-z.\-]+)\.\s*(?P<head>[^\n]+)",
)
_WORD_HEAD_RE = re.compile(
    r"(?m)^(?P<num>\d+[A-Za-z]?-\d+[A-Za-z0-9.]*)\.\s+(?P<head>.+)$"
)
_RESERVED = re.compile(r"\b(repealed|reserved|expired|renumbered)\b", re.IGNORECASE)
_WS = re.compile(r"\s+")


BYCHAPTER_INDEX_URL = (
    "https://www.ncleg.gov/EnactedLegislation/Statutes/HTML/ByChapter/"
)
TOC_URL = "https://www.ncleg.gov/Laws/GeneralStatutesTOC"


def chapter_url(chapter: str) -> str:
    return (
        "https://www.ncleg.gov/EnactedLegislation/Statutes/HTML/ByChapter/"
        f"Chapter_{chapter}.html"
    )


def chapter_sections_url(chapter: str) -> str:
    return f"https://www.ncleg.gov/Laws/GeneralStatuteSections/Chapter{chapter}"


_CHAPTER_HREF_RE = re.compile(
    r"Chapter_([0-9]+[A-Za-z]?)\.html",
    re.IGNORECASE,
)
_TOC_CHAPTER_PATH_RE = re.compile(
    r"/Laws/GeneralStatuteSections/Chapter([0-9]+[A-Za-z]?)\b",
    re.IGNORECASE,
)
_TOC_CHAPTER_LABEL_RE = re.compile(
    r"\bChapter\s+([0-9]+[A-Za-z]?)\b",
    re.IGNORECASE,
)
_TOC_INACTIVE_CHAPTER_RE = re.compile(
    r"\b(repealed|recodified|transferred|expired|unconstitutional|abolished)\b",
    re.IGNORECASE,
)


class NorthCarolinaTocChapterRecord(TypedDict):
    chapter_number: str
    chapter_name: str
    label: str
    disposition: Literal["active", "inactive"]
    source_url: str


class NorthCarolinaChapterSectionRecord(TypedDict):
    """One section advertised by an official chapter-section index."""

    section_number: str
    section_name: str
    disposition: Literal["active", "inactive"]
    source_url: str


def bychapter_index_links(html: str) -> List[str]:
    """Chapter numbers from an official ByChapter directory listing."""

    seen: List[str] = []
    found = set()
    for match in _CHAPTER_HREF_RE.finditer(html or ""):
        number = match.group(1)
        if number in found:
            continue
        found.add(number)
        seen.append(number)
    return seen


def toc_chapter_links(html: str) -> List[str]:
    """Chapter numbers from the official GeneralStatutesTOC page.

    Prefers ``/Laws/GeneralStatuteSections/ChapterN`` hrefs; falls back to
    ``Chapter N`` labels when the listing has no ByChapter files.
    """

    seen: List[str] = []
    found = set()
    for match in _TOC_CHAPTER_PATH_RE.finditer(html or ""):
        number = match.group(1)
        if number in found:
            continue
        found.add(number)
        seen.append(number)
    if seen:
        return seen
    for match in _TOC_CHAPTER_LABEL_RE.finditer(html or ""):
        number = match.group(1)
        if number in found:
            continue
        found.add(number)
        seen.append(number)
    return seen


def toc_chapter_frontier(html: str) -> List[NorthCarolinaTocChapterRecord]:
    """Return deduplicated live TOC chapters with explicit inactive dispositions."""

    try:
        from bs4 import BeautifulSoup
    except ImportError as exc:
        raise RuntimeError("BeautifulSoup is required for NC TOC closure") from exc

    soup = BeautifulSoup(html or "", "html.parser")
    records: List[NorthCarolinaTocChapterRecord] = []
    seen: set[str] = set()
    for anchor in soup.find_all("a", href=True):
        href = str(anchor.get("href") or "").strip()
        match = _TOC_CHAPTER_PATH_RE.search(href)
        if not match:
            continue
        number = match.group(1)
        canonical_number = number.upper()
        if canonical_number in seen:
            continue
        seen.add(canonical_number)
        row = anchor.find_parent("div", class_="row")
        label = _WS.sub(" ", (row or anchor).get_text(" ", strip=True)).strip()
        name = re.sub(
            rf"^Chapter\s+{re.escape(number)}\s*",
            "",
            label,
            flags=re.IGNORECASE,
        ).strip()
        disposition: Literal["active", "inactive"] = (
            "inactive" if _TOC_INACTIVE_CHAPTER_RE.search(label) else "active"
        )
        records.append(
            NorthCarolinaTocChapterRecord(
                chapter_number=number,
                chapter_name=name or f"Chapter {number}",
                label=label,
                disposition=disposition,
                source_url=chapter_url(number),
            )
        )
    return records


def merge_discovered_chapters(
    catalog: Sequence[Tuple[str, str]],
    discovered: Sequence[str],
) -> List[Tuple[str, str]]:
    """Put discovered ByChapter/TOC numbers first; keep named catalog as tail."""

    names = dict(catalog)
    leading: List[Tuple[str, str]] = []
    found = set()
    for number in discovered:
        token = str(number or "").strip()
        if not token or token in found:
            continue
        found.add(token)
        leading.append((token, names.get(token, f"Chapter {token}")))
    tail = [(number, name) for number, name in catalog if number not in found]
    return leading + tail


def configured_bychapter_index_path() -> Optional[Path]:
    raw = str(os.environ.get("NORTH_CAROLINA_BYCHAPTER_INDEX_HTML") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None


def configured_toc_html_path() -> Optional[Path]:
    raw = str(os.environ.get("NORTH_CAROLINA_TOC_HTML") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None


def decode_chapter_bytes(payload: bytes) -> str:
    """Decode ByChapter dumps (utf-8 live pages or Word cp1252 Wayback captures)."""

    data = payload or b""
    for encoding in ("utf-8", "cp1252", "latin-1"):
        try:
            text = data.decode(encoding)
        except Exception:
            continue
        if "§" in text or "&sect;" in text or "&#167;" in text:
            return text
    return data.decode("utf-8", errors="replace")


def _clean_soup_text(html: str) -> str:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return html or ""
    soup = BeautifulSoup(html or "", "html.parser")
    for tag in soup(["script", "style", "nav", "header", "footer", "noscript", "form"]):
        tag.decompose()
    for node in list(soup.find_all(True)):
        text = (node.get_text(" ") or "").lower()
        if any(marker in text and len(text) < 180 for marker in NAV_MARKERS):
            node.decompose()
    return soup.get_text("\n", strip=True).replace("\xa0", " ")


def chapter_section_index_frontier(
    html: str,
    *,
    chapter: str,
) -> List[NorthCarolinaChapterSectionRecord]:
    """Parse the independent official ChapterN listing's HTML section links."""

    try:
        from bs4 import BeautifulSoup
    except ImportError as exc:
        raise RuntimeError("BeautifulSoup is required for NC section closure") from exc

    section_href_re = re.compile(
        rf"/EnactedLegislation/Statutes/HTML/BySection/Chapter_{re.escape(chapter)}/"
        r"GS_(?P<num>[0-9A-Za-z.\-]+)\.html$",
        re.IGNORECASE,
    )
    soup = BeautifulSoup(html or "", "html.parser")
    records: List[NorthCarolinaChapterSectionRecord] = []
    seen: set[str] = set()
    for anchor in soup.find_all("a", href=True):
        href = str(anchor.get("href") or "").strip()
        match = section_href_re.search(href)
        if not match:
            continue
        number = match.group("num").strip()
        canonical_number = number.upper()
        if not number or canonical_number in seen:
            continue
        seen.add(canonical_number)
        row = anchor.find_parent("div", class_="row")
        label = _WS.sub(" ", (row or anchor).get_text(" ", strip=True)).strip()
        heading_match = re.search(
            rf"(?:§|G\.S\.)\s*{re.escape(number)}[.:]?\s*(?P<head>.*)$",
            label,
            flags=re.IGNORECASE,
        )
        heading = (
            str(heading_match.group("head") or "").strip()
            if heading_match
            else label
        )
        records.append(
            NorthCarolinaChapterSectionRecord(
                section_number=number,
                section_name=heading,
                disposition=("inactive" if _RESERVED.search(label) else "active"),
                source_url=urljoin("https://www.ncleg.gov", href),
            )
        )
    return records


def parse_north_carolina_chapter_html(
    html: str,
    *,
    chapter: str,
    code_name: str = "North Carolina General Statutes",
    max_statutes: Optional[int] = None,
) -> List[NormalizedStatute]:
    text = _clean_soup_text(html)
    matches = list(_SECTION_RE.finditer(text))
    if not matches:
        matches = list(_WORD_HEAD_RE.finditer(text))
    statutes: List[NormalizedStatute] = []
    for index, match in enumerate(matches):
        if max_statutes is not None and len(statutes) >= int(max_statutes):
            break
        number = match.group("num").strip()
        heading = match.group("head").strip()
        if _RESERVED.search(heading):
            continue
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        body = _WS.sub(" ", text[start:end]).strip()
        lowered = body.lower()
        if any(marker in lowered for marker in NAV_MARKERS):
            continue
        if len(body) < 40:
            continue
        statutes.append(
            NormalizedStatute(
                state_code="NC",
                state_name="North Carolina",
                statute_id=f"{code_name} § {number}",
                code_name=code_name,
                chapter_number=str(chapter),
                section_number=number,
                section_name=heading[:200],
                full_text=body[:14000],
                source_url=chapter_url(chapter),
                official_cite=f"N.C. Gen. Stat. § {number}",
                metadata=StatuteMetadata(),
                structured_data={
                    "source_kind": "official_north_carolina_bychapter_html",
                    "source_authority_class": "official",
                    "discovery_method": "ncleg_bychapter_nav_stripped",
                    "skip_hydrate": True,
                },
            )
        )
    return statutes


def configured_chapter_html_path() -> Optional[Path]:
    raw = str(os.environ.get("NORTH_CAROLINA_CHAPTER_HTML") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None


def configured_chapter_html_paths() -> List[Path]:
    paths: List[Path] = []
    single = configured_chapter_html_path()
    if single is not None:
        paths.append(single)
    raw_dir = str(os.environ.get("NORTH_CAROLINA_CHAPTER_HTML_DIR") or "").strip()
    if raw_dir:
        directory = Path(raw_dir).expanduser()
        if directory.is_dir():
            paths.extend(
                sorted(
                    child
                    for child in directory.iterdir()
                    if child.is_file() and child.suffix.lower() in {".html", ".htm"}
                )
            )
    return paths


def chapter_token_from_path(path: Path) -> str:
    stem = path.stem.replace("Chapter_", "").replace("chapter_", "")
    return stem or "14"


def parse_configured_north_carolina_chapters(
    *,
    code_name: str = "North Carolina General Statutes",
    max_statutes: Optional[int] = None,
) -> List[NormalizedStatute]:
    statutes: List[NormalizedStatute] = []
    seen: set[str] = set()
    for path in configured_chapter_html_paths():
        if max_statutes is not None and len(statutes) >= int(max_statutes):
            break
        remaining = None if max_statutes is None else max(0, int(max_statutes) - len(statutes))
        rows = parse_north_carolina_chapter_html(
            path.read_text(encoding="utf-8", errors="replace"),
            chapter=chapter_token_from_path(path),
            code_name=code_name,
            max_statutes=remaining,
        )
        for row in rows:
            key = str(row.section_number or "")
            if key in seen:
                continue
            seen.add(key)
            statutes.append(row)
    return statutes
