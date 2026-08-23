"""Official North Carolina ByChapter HTML parser.

Vaquill withdrew NC because nav/footer leaked into section bodies. This parser
keeps only statutory blocks from
``/EnactedLegislation/Statutes/HTML/ByChapter/Chapter_{N}.html``.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import List, Optional

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


def chapter_url(chapter: str) -> str:
    return (
        "https://www.ncleg.gov/EnactedLegislation/Statutes/HTML/ByChapter/"
        f"Chapter_{chapter}.html"
    )


_CHAPTER_HREF_RE = re.compile(
    r"Chapter_([0-9]+[A-Za-z]?)\.html",
    re.IGNORECASE,
)


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


def configured_bychapter_index_path() -> Optional[Path]:
    raw = str(os.environ.get("NORTH_CAROLINA_BYCHAPTER_INDEX_HTML") or "").strip()
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
