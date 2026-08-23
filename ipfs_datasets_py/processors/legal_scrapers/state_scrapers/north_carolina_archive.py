"""North Carolina ByChapter archive-recovery harvest of official ncleg.gov locators.

Vaquill withdrew NC because navigation/footer leaked into section bodies.
Live ``/EnactedLegislation/Statutes/HTML/ByChapter/Chapter_{N}.html`` is
real statute HTML (not an SPA shell). This module:

* keeps official ``ncleg.gov`` ByChapter locators as the citation source
* fetches those locators through web_archiving transports (Wayback ``id_``,
  archive.is, Common Crawl CDX) when live HTML is blocked
* reuses the chrome-stripped ByChapter parser
* always labels archive transport ``source_authority_class=recovery``

This does **not** close LCR-084 exact-51 official live scrape. A live
ByChapter walk remains official; archive captures of the same URLs do not.

Local dumps: ``NORTH_CAROLINA_ARCHIVE_HTML``, ``NORTH_CAROLINA_ARCHIVE_HTML_DIR``.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import quote

from .base_scraper import NormalizedStatute
from .north_carolina_chapter import (
    chapter_token_from_path,
    chapter_url,
    parse_north_carolina_chapter_html,
)

OFFICIAL_HOST = "www.ncleg.gov"
WAYBACK = "https://web.archive.org/web"
ARCHIVE_IS = "https://archive.is"
CDX = "https://web.archive.org/cdx/search/cdx"
COMMON_CRAWL_CDX = "https://index.commoncrawl.org/CC-MAIN-2024-51-index"

# Timestamp with confirmed Chapter_14 capture (355KB+ HTML, 2019-02-24).
CHAPTER_14_WAYBACK_TS = "20190224180051"


def wayback_identity_url(official_url: str, timestamp: str = "20200201") -> str:
    return f"{WAYBACK}/{timestamp}id_/{official_url}"


def archive_is_url(official_url: str) -> str:
    return f"{ARCHIVE_IS}/{official_url}"


def wayback_cdx_query_url(*, match_type: str = "prefix") -> str:
    return (
        f"{CDX}?url={quote('www.ncleg.gov/EnactedLegislation/Statutes/HTML/ByChapter/*')}"
        "&output=json&fl=original,timestamp,statuscode,mimetype,length"
        "&filter=statuscode:200&filter=mimetype:text/html"
        f"&matchType={match_type}&collapse=urlkey"
    )


def wayback_chapter_cdx_query_url(chapter: str) -> str:
    return (
        f"{CDX}?url={quote(f'www.ncleg.gov/EnactedLegislation/Statutes/HTML/ByChapter/Chapter_{chapter}.html')}"
        "&output=json&fl=original,timestamp,statuscode,mimetype,length"
        "&filter=statuscode:200&limit=5"
    )


def common_crawl_cdx_query_url() -> str:
    return (
        f"{COMMON_CRAWL_CDX}?url="
        + quote("www.ncleg.gov/EnactedLegislation/Statutes/HTML/ByChapter/*")
        + "&output=json&filter=status:200"
    )


def official_chapter_frontier() -> List[Dict[str, str]]:
    """Exhaustive official ByChapter locators plus archive-transport URLs."""

    from .north_carolina import NorthCarolinaScraper

    rows: List[Dict[str, str]] = []
    for number, name in NorthCarolinaScraper.OFFICIAL_CHAPTERS:
        official = chapter_url(number)
        timestamp = CHAPTER_14_WAYBACK_TS if number == "14" else "20200201"
        rows.append(
            {
                "chapter_number": number,
                "chapter_name": name,
                "official_url": official,
                "wayback_url": wayback_identity_url(official, timestamp=timestamp),
                "archive_is_url": archive_is_url(official),
                "source_authority_class": "recovery",
            }
        )
    return rows


def parse_north_carolina_archive_html(
    html: str,
    *,
    chapter: str,
    source_url: str = "",
    code_name: str = "North Carolina General Statutes",
    max_statutes: Optional[int] = None,
) -> List[NormalizedStatute]:
    """Parse ByChapter HTML recovered via archive transport of an official locator."""

    statutes = parse_north_carolina_chapter_html(
        html,
        chapter=chapter,
        code_name=code_name,
        max_statutes=max_statutes,
    )
    official = chapter_url(chapter)
    for row in statutes:
        row.source_url = official
        data = dict(row.structured_data or {})
        data["source_kind"] = "official_north_carolina_bychapter_html_via_archive"
        data["source_authority_class"] = "recovery"
        data["discovery_method"] = "web_archiving_official_locator"
        data["archive_source_url"] = source_url or None
        data["wayback_url"] = wayback_identity_url(official)
        data["skip_hydrate"] = True
        row.structured_data = data
    return statutes


def configured_archive_html_paths() -> List[Path]:
    paths: List[Path] = []
    raw = str(os.environ.get("NORTH_CAROLINA_ARCHIVE_HTML") or "").strip()
    if raw:
        path = Path(raw).expanduser()
        if path.is_file():
            paths.append(path)
    raw_dir = str(os.environ.get("NORTH_CAROLINA_ARCHIVE_HTML_DIR") or "").strip()
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
    """Fetch one official ncleg.gov ByChapter locator through the Wayback engine.

    Returns empty string on miss. Callers must still parse with
    ``parse_north_carolina_archive_html`` and label the result recovery.
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
        from .north_carolina_chapter import decode_chapter_bytes

        return decode_chapter_bytes(content)
    return str(content or "")


def parse_configured_north_carolina_archive(
    *,
    code_name: str = "North Carolina General Statutes",
    max_statutes: Optional[int] = None,
) -> List[NormalizedStatute]:
    statutes: List[NormalizedStatute] = []
    seen: set[str] = set()
    for path in configured_archive_html_paths():
        if max_statutes is not None and len(statutes) >= int(max_statutes):
            break
        remaining = None if max_statutes is None else max(0, int(max_statutes) - len(statutes))
        rows = parse_north_carolina_archive_html(
            path.read_text(encoding="utf-8", errors="replace"),
            chapter=chapter_token_from_path(path),
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
