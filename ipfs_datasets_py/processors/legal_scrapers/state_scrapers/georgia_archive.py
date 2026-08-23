"""Georgia OCGA archive-recovery harvest of official legis.ga.gov locators.

Georgia has no free official bulk dump (commercial exclusive). Vaquill withdrew
GA because navigation/footer leaked into section bodies. This module:

* keeps official ``legis.ga.gov`` locators as the citation source
* fetches those locators through web_archiving transports (Wayback ``id_``,
  archive.is, Common Crawl CDX) when live HTML is blocked
* strips nav/header/footer chrome so archive snapshots can be admitted
* always labels the result ``source_authority_class=recovery``

This does **not** close LCR-084 exact-51 official live scrape.

Local dumps: ``GEORGIA_CHAPTER_HTML``, ``GEORGIA_ARCHIVE_HTML``,
``GEORGIA_CHAPTER_HTML_DIR``.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import quote

from .base_scraper import NormalizedStatute, StatuteMetadata

OFFICIAL_HOST = "www.legis.ga.gov"
OFFICIAL_CODE_ROOT = f"https://{OFFICIAL_HOST}/legislation/georgia-code"
WAYBACK = "https://web.archive.org/web"
ARCHIVE_IS = "https://archive.is"
CDX = "https://web.archive.org/cdx/search/cdx"
COMMON_CRAWL_CDX = "https://index.commoncrawl.org/CC-MAIN-2024-51-index"

# Titles 1-53 match GeorgiaScraper.OFFICIAL_TITLES.
TITLE_NUMBERS = tuple(str(number) for number in range(1, 54))

NAV_MARKERS = (
    "skip to main",
    "skip to content",
    "skip to navigation",
    "privacy policy",
    "site map",
    "sitemap",
    "copyright ©",
    "copyright (c)",
    "footer navigation",
    "cookie policy",
    "terms of use",
)
_SECTION_RE = re.compile(
    r"(?m)^(?:§|&sect;)\s*(?P<num>\d+[A-Za-z]?-\d+[A-Za-z0-9.-]*)\.\s*(?P<head>[^\n]+)"
)
_RESERVED = re.compile(r"\b(repealed|reserved|expired|renumbered)\b", re.IGNORECASE)
_WS = re.compile(r"\s+")


def official_title_url(title_number: str) -> str:
    return f"{OFFICIAL_CODE_ROOT}/title-{title_number}"


def official_hyphen_title_url(title_number: str) -> str:
    """Alternate legis.ga.gov title URL seen in Wayback CDX (Title 40, 2025-04-14)."""

    return f"https://{OFFICIAL_HOST}/legislation/georgia-code-title-{title_number}"


def official_section_url(section_number: str) -> str:
    parts = str(section_number or "").split("-")
    title = parts[0] if parts else ""
    chapter = parts[1] if len(parts) > 1 else "1"
    return f"{OFFICIAL_CODE_ROOT}/title-{title}/chapter-{chapter}/section-{section_number}"


def wayback_identity_url(official_url: str, timestamp: str = "2020") -> str:
    """Wayback ``id_`` capture of an official locator (no toolbar chrome)."""

    return f"{WAYBACK}/{timestamp}id_/{official_url}"


def archive_is_url(official_url: str) -> str:
    return f"{ARCHIVE_IS}/{official_url}"


def wayback_cdx_query_url(*, match_type: str = "prefix") -> str:
    return (
        f"{CDX}?url={quote('www.legis.ga.gov/legislation/georgia-code/*')}"
        "&output=json&fl=original,timestamp,statuscode,mimetype"
        "&filter=statuscode:200&filter=mimetype:text/html"
        f"&matchType={match_type}&collapse=urlkey"
    )


def common_crawl_cdx_query_url() -> str:
    return (
        f"{COMMON_CRAWL_CDX}?url={quote('www.legis.ga.gov/legislation/georgia-code/*')}"
        "&output=json&filter=status:200"
    )


def official_title_frontier() -> List[Dict[str, str]]:
    """Exhaustive official title locators plus archive-transport URLs."""

    rows: List[Dict[str, str]] = []
    for number in TITLE_NUMBERS:
        official = official_title_url(number)
        hyphen = official_hyphen_title_url(number)
        rows.append(
            {
                "title_number": number,
                "official_url": official,
                "hyphen_url": hyphen,
                "wayback_url": wayback_identity_url(official),
                "wayback_hyphen_url": wayback_identity_url(hyphen, timestamp="20250414215500"),
                "archive_is_url": archive_is_url(official),
                "source_authority_class": "recovery",
            }
        )
    return rows


def _clean(text: str) -> str:
    return _WS.sub(" ", (text or "").replace("\xa0", " ")).strip()


def strip_georgia_chrome(html: str) -> str:
    """Drop nav/header/footer and short chrome nodes (Vaquill contamination)."""

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return html or ""
    soup = BeautifulSoup(html or "", "html.parser")
    for tag in soup(["script", "style", "nav", "header", "footer", "noscript", "form"]):
        tag.decompose()
    for node in list(soup.find_all(True)):
        text = (node.get_text(" ") or "").lower()
        if any(marker in text and len(text) < 220 for marker in NAV_MARKERS):
            node.decompose()
    raw = soup.get_text("\n", strip=True)
    lines = []
    for line in raw.splitlines():
        lowered = line.lower()
        if any(marker in lowered for marker in NAV_MARKERS):
            continue
        lines.append(line)
    return "\n".join(lines)


def parse_georgia_archive_html(
    html: str,
    *,
    source_url: str = "",
    code_name: str = "Official Code of Georgia Annotated",
    max_statutes: Optional[int] = None,
) -> List[NormalizedStatute]:
    """Parse stripped official-locator HTML recovered via archive transport."""

    text = strip_georgia_chrome(html)
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
        body = _clean(text[start:end])
        lowered = body.lower()
        if any(marker in lowered for marker in NAV_MARKERS):
            continue
        if len(body) < 40:
            continue
        parts = number.split("-")
        official = official_section_url(number)
        statutes.append(
            NormalizedStatute(
                state_code="GA",
                state_name="Georgia",
                statute_id=f"{code_name} § {number}",
                code_name=code_name,
                title_number=parts[0] if parts else None,
                chapter_number=parts[1] if len(parts) > 1 else None,
                section_number=number,
                section_name=heading[:200],
                full_text=body[:14000],
                source_url=official,
                official_cite=f"Ga. Code Ann. § {number}",
                metadata=StatuteMetadata(),
                structured_data={
                    "source_kind": "official_georgia_code_html_via_archive",
                    "source_authority_class": "recovery",
                    "discovery_method": "web_archiving_official_locator",
                    "archive_source_url": source_url or None,
                    "wayback_url": wayback_identity_url(official),
                    "skip_hydrate": True,
                },
            )
        )
    return statutes


def configured_georgia_html_paths() -> List[Path]:
    paths: List[Path] = []
    for key in ("GEORGIA_CHAPTER_HTML", "GEORGIA_ARCHIVE_HTML"):
        raw = str(os.environ.get(key) or "").strip()
        if not raw:
            continue
        path = Path(raw).expanduser()
        if path.is_file():
            paths.append(path)
    raw_dir = str(os.environ.get("GEORGIA_CHAPTER_HTML_DIR") or "").strip()
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


async def fetch_official_locator_via_wayback(official_url: str) -> str:
    """Fetch one official legis.ga.gov locator through the Wayback engine.

    Returns empty string on miss. Callers must still parse with
    ``parse_georgia_archive_html`` and label the result recovery.
    """

    try:
        from ipfs_datasets_py.processors.web_archiving.wayback_machine_engine import (
            get_wayback_content,
        )
    except Exception:
        return ""
    try:
        result = await get_wayback_content(official_url, closest=True)
    except Exception:
        return ""
    if not isinstance(result, dict) or result.get("status") != "success":
        return ""
    content = result.get("content")
    if isinstance(content, bytes):
        return content.decode("utf-8", errors="replace")
    return str(content or "")


def parse_configured_georgia_archive(
    *,
    code_name: str = "Official Code of Georgia Annotated",
    max_statutes: Optional[int] = None,
) -> List[NormalizedStatute]:
    statutes: List[NormalizedStatute] = []
    seen: set[str] = set()
    for path in configured_georgia_html_paths():
        if max_statutes is not None and len(statutes) >= int(max_statutes):
            break
        remaining = None if max_statutes is None else max(0, int(max_statutes) - len(statutes))
        rows = parse_georgia_archive_html(
            path.read_text(encoding="utf-8", errors="replace"),
            source_url=str(path),
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
