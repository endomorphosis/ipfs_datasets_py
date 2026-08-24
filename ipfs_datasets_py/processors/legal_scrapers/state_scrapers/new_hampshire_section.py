"""Official New Hampshire RSA section HTML parser.

Adapted from Vaquill-AI/open-us-law ``scrapeNH.py`` (Apache-2.0).
Body lives in ``<codesect>``; ``<sourcenote>`` history is dropped.
"""

from __future__ import annotations

import os
import re
from html import unescape
from pathlib import Path
from typing import List, Optional, Tuple

from .base_scraper import NormalizedStatute, StatuteMetadata

BASE = "https://www.gencourt.state.nh.us/rsa/html"
NHTOC_BASE = f"{BASE}/NHTOC"
_RESERVED = re.compile(r"\[(?:repealed|expired|reserved)\]|\brepealed\b|\breserved\b|\bexpired\b", re.IGNORECASE)
_WS = re.compile(r"\s+")
_URL_RE = re.compile(r"/([\w\-]+)/([\w\-]+)\.htm$", re.IGNORECASE)
_TITLE_HREF_RE = re.compile(r"NHTOC/NHTOC-([A-Z][A-Z\-]*)\.htm$", re.IGNORECASE)
_CHAPTER_HREF_RE = re.compile(
    r"^NHTOC-[A-Z][A-Z\-]*-[\dA-Z][\w\-]*\.htm$",
    re.IGNORECASE,
)
_MOJIBAKE = ("\xc2", "\xe2\x80", "â€")
_CP1252_FIX = {
    "\u0080": "€",
    "\u0082": "‚",
    "\u0083": "ƒ",
    "\u0084": "„",
    "\u0085": "…",
    "\u0091": "‘",
    "\u0092": "’",
    "\u0093": "“",
    "\u0094": "”",
    "\u0096": "–",
    "\u0097": "—",
    "\u0099": "™",
}


def _fix_encoding(text: str) -> str:
    if not text or not any(marker in text for marker in _MOJIBAKE):
        return text
    try:
        fixed = text.encode("latin-1", errors="ignore").decode("utf-8", errors="ignore")
    except Exception:
        return text
    return fixed if sum(m in fixed for m in _MOJIBAKE) < sum(m in text for m in _MOJIBAKE) else text


def _clean(text: str) -> str:
    value = unescape(text or "")
    for src, dest in _CP1252_FIX.items():
        if src in value:
            value = value.replace(src, dest)
    value = _fix_encoding(value.replace("\xa0", " "))
    return _WS.sub(" ", value).strip()


def nhtoc_title_links(html: str, *, base_url: str = BASE) -> List[Tuple[str, str]]:
    """Title TOC URLs from the master ``NHTOC.htm`` listing."""

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    from urllib.parse import urljoin

    soup = BeautifulSoup(html or "", "html.parser")
    out: List[Tuple[str, str]] = []
    seen = set()
    for anchor in soup.find_all("a", href=True):
        href = str(anchor.get("href") or "").strip()
        match = _TITLE_HREF_RE.search(href.replace("\\", "/"))
        if not match:
            continue
        roman = match.group(1).upper()
        if roman in seen:
            continue
        seen.add(roman)
        out.append((urljoin(base_url.rstrip("/") + "/", href), roman))
    return out


def nhtoc_chapter_links(html: str) -> List[str]:
    """Chapter TOC filenames from a title ``NHTOC-{ROMAN}.htm`` page."""

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    soup = BeautifulSoup(html or "", "html.parser")
    out: List[str] = []
    seen = set()
    for anchor in soup.find_all("a", href=True):
        href = str(anchor.get("href") or "").strip()
        if "/" in href:
            continue
        if not _CHAPTER_HREF_RE.match(href):
            continue
        if href in seen:
            continue
        seen.add(href)
        out.append(href)
    return out


def nhtoc_section_links(html: str) -> List[str]:
    """Relative section hrefs from a chapter TOC (``../TITLE/CH/CH-SEC.htm``)."""

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    soup = BeautifulSoup(html or "", "html.parser")
    out: List[str] = []
    seen = set()
    for anchor in soup.find_all("a", href=True):
        href = str(anchor.get("href") or "").strip()
        if not href.startswith("../") or not href.lower().endswith(".htm"):
            continue
        if re.search(r"-mrg\.htm$", href, re.IGNORECASE):
            continue
        if href in seen:
            continue
        seen.add(href)
        out.append(href)
    return out


def parse_new_hampshire_section_html(
    html: str,
    *,
    source_url: str = "",
    code_name: str = "New Hampshire RSA",
) -> Optional[NormalizedStatute]:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return None
    soup = BeautifulSoup(html or "", "html.parser")
    body = soup.find("body") or soup
    codesect = body.find("codesect")
    if codesect is None:
        return None
    full = _clean(codesect.get_text(" "))
    if len(full) < 40:
        return None
    bold = body.find("b")
    heading = _clean(bold.get_text(" ")) if bold else ""
    heading = re.sub(r"\s*[\-–—―]+\s*$", "", heading).strip()
    if _RESERVED.search(heading) or _RESERVED.search(full[:160]):
        return None
    citation = heading.split()[0] if heading else ""
    url_match = _URL_RE.search(source_url or "")
    if not re.match(r"^\d", citation) and url_match:
        chapter = url_match.group(1)
        stem = url_match.group(2)
        prefix = f"{chapter}-"
        section = stem[len(prefix) :] if stem.startswith(prefix) else stem
        citation = f"{chapter}:{section}"
    number = citation.split(":", 1)[1] if ":" in citation else citation
    number = number.rstrip(".")
    if not number:
        return None
    name = heading or f"Section {number}"
    return NormalizedStatute(
        state_code="NH",
        state_name="New Hampshire",
        statute_id=f"{code_name} § {number}",
        code_name=code_name,
        chapter_number=citation.split(":", 1)[0] if ":" in citation else None,
        section_number=number if ":" not in citation else citation,
        section_name=name[:200],
        full_text=full[:14000],
        source_url=source_url or BASE,
        official_cite=f"N.H. Rev. Stat. § {citation or number}",
        metadata=StatuteMetadata(),
        structured_data={
            "source_kind": "official_new_hampshire_rsa_html",
            "source_authority_class": "official",
            "discovery_method": "gencourt_codesect",
            "skip_hydrate": True,
        },
    )


def configured_section_html_path() -> Optional[Path]:
    raw = str(os.environ.get("NEW_HAMPSHIRE_SECTION_HTML") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None


def configured_chapter_toc_html_path() -> Optional[Path]:
    raw = str(os.environ.get("NEW_HAMPSHIRE_CHAPTER_TOC_HTML") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None


def parse_configured_chapter_toc_html() -> List[str]:
    path = configured_chapter_toc_html_path()
    if path is None:
        return []
    return nhtoc_section_links(path.read_text(encoding="utf-8", errors="replace"))


def configured_section_html_paths() -> List[Path]:
    paths: List[Path] = []
    single = configured_section_html_path()
    if single is not None:
        paths.append(single)
    raw_dir = str(os.environ.get("NEW_HAMPSHIRE_SECTION_HTML_DIR") or "").strip()
    if raw_dir:
        directory = Path(raw_dir).expanduser()
        if directory.is_dir():
            paths.extend(
                sorted(
                    child
                    for child in directory.iterdir()
                    if child.is_file() and child.suffix.lower() in {".htm", ".html"}
                )
            )
    return paths


def section_url_from_path(path: Path) -> str:
    stem = path.stem
    chapter = stem.split("-")[0] if "-" in stem else stem
    return f"{BASE}/{chapter}/{path.name}"


def parse_configured_new_hampshire_sections(
    *,
    code_name: str = "New Hampshire RSA",
    max_statutes: Optional[int] = None,
) -> List[NormalizedStatute]:
    statutes: List[NormalizedStatute] = []
    seen: set[str] = set()
    wanted: Optional[set[str]] = None
    toc_path = configured_chapter_toc_html_path()
    if toc_path is not None:
        wanted = {
            Path(href).name.lower()
            for href in nhtoc_section_links(
                toc_path.read_text(encoding="utf-8", errors="replace")
            )
        }
    for path in configured_section_html_paths():
        if max_statutes is not None and len(statutes) >= int(max_statutes):
            break
        if wanted is not None and path.name.lower() not in wanted:
            continue
        row = parse_new_hampshire_section_html(
            path.read_text(encoding="utf-8", errors="replace"),
            source_url=section_url_from_path(path),
            code_name=code_name,
        )
        if row is None:
            continue
        key = str(row.section_number or "")
        if key in seen:
            continue
        seen.add(key)
        statutes.append(row)
    return statutes
