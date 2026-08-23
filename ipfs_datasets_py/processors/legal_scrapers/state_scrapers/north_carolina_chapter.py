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
    r"(?m)^(?:§|&sect;)\s*(?P<num>[0-9A-Za-z.\-]+)\.\s*(?P<head>[^\n]+)",
)
_WS = re.compile(r"\s+")


def chapter_url(chapter: str) -> str:
    return (
        "https://www.ncleg.gov/EnactedLegislation/Statutes/HTML/ByChapter/"
        f"Chapter_{chapter}.html"
    )


def _clean_soup_text(html: str) -> str:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return html
    soup = BeautifulSoup(html or "", "html.parser")
    for tag in soup(["script", "style", "nav", "header", "footer", "noscript", "form"]):
        tag.decompose()
    for node in soup.find_all(True):
        text = (node.get_text(" ") or "").lower()
        if any(marker in text and len(text) < 180 for marker in NAV_MARKERS):
            node.decompose()
    return soup.get_text("\n", strip=True)


def parse_north_carolina_chapter_html(
    html: str,
    *,
    chapter: str,
    code_name: str = "North Carolina General Statutes",
    max_statutes: Optional[int] = None,
) -> List[NormalizedStatute]:
    text = _clean_soup_text(html)
    matches = list(_SECTION_RE.finditer(text))
    statutes: List[NormalizedStatute] = []
    for index, match in enumerate(matches):
        if max_statutes is not None and len(statutes) >= int(max_statutes):
            break
        number = match.group("num").strip()
        heading = match.group("head").strip()
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
