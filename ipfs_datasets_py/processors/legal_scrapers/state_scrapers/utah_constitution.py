"""Official Utah Constitution xcode HTML parser.

Adapted from Vaquill-AI/open-us-law ``ingest_state_constitutions.scrape_ut``
(Apache-2.0). le.utah.gov/xcode serves Article/Section pages with ``#content``
and ``#secdiv``. Preamble rows in ``#childtbl`` are skipped. Empty section
tables fall back to the whole article. Duplicate section numbers get ``-vN``.

Local dump: ``UTAH_CONSTITUTION_HTML``.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import List, Optional, Tuple

from .base_scraper import NormalizedStatute, StatuteMetadata

UT_ORIGIN = "https://le.utah.gov"
UT_CONST_WRAPPER = f"{UT_ORIGIN}/xcode/constitution.html"
_UT_ARTICLE_RE = re.compile(r"(?i)article\s+([IVXLC]+)")
_UT_SECTION_LABEL_RE = re.compile(r"(?i)section\s+(\d+[A-Za-z]?)")
_RESERVED = re.compile(r"\b(repealed|reserved|expired|renumbered)\b", re.IGNORECASE)
_WS = re.compile(r"\s+")
_JUNK_IDS = ("childtbl", "topnavtbl", "parenttbl", "breadcrumb")


def constitution_articles(html: str) -> List[Tuple[str, str]]:
    """Return ``(article_id, title)`` from a top-level ``#childtbl``."""

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    soup = BeautifulSoup(html or "", "html.parser")
    table = soup.find(id="childtbl")
    if table is None:
        return []
    out: List[Tuple[str, str]] = []
    for row in table.find_all("tr"):
        anchor = row.find("a", href=True)
        if anchor is None:
            continue
        match = _UT_ARTICLE_RE.match(anchor.get_text(" ", strip=True))
        if not match:
            continue
        cells = row.find_all("td")
        title = cells[1].get_text(" ", strip=True) if len(cells) > 1 else ""
        out.append((match.group(1), title))
    return out


def constitution_section_numbers(html: str) -> List[str]:
    """Section labels from ``#childtbl``, with ``-vN`` on repeats."""

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    soup = BeautifulSoup(html or "", "html.parser")
    table = soup.find(id="childtbl")
    if table is None:
        return []
    seen = {}
    out: List[str] = []
    for row in table.find_all("tr"):
        anchor = row.find("a", href=True)
        if anchor is None:
            continue
        match = _UT_SECTION_LABEL_RE.match(anchor.get_text(" ", strip=True))
        if not match:
            continue
        raw = match.group(1)
        seen[raw] = seen.get(raw, 0) + 1
        out.append(raw if seen[raw] == 1 else f"{raw}-v{seen[raw]}")
    return out


def parse_utah_constitution_html(
    html: str,
    *,
    code_name: str = "Utah Constitution",
    source_url: str = "",
    max_statutes: Optional[int] = None,
) -> List[NormalizedStatute]:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    soup = BeautifulSoup(html or "", "html.parser")
    content = soup.find(id="content") or soup
    heading = _WS.sub(" ", content.get_text(" ", strip=True)[:400])
    art_match = _UT_ARTICLE_RE.search(heading)
    art_id = art_match.group(1) if art_match else "I"
    statutes: List[NormalizedStatute] = []
    secdiv = content.find(id="secdiv")
    if secdiv is not None:
        copy = BeautifulSoup(str(secdiv), "html.parser")
        bolds = copy.find_all("b")
        sec_title = (
            bolds[1].get_text(" ", strip=True).strip("[]").strip() if len(bolds) >= 2 else ""
        )
        body = _WS.sub(" ", copy.get_text(" ", strip=True)).strip()
        number_match = _UT_SECTION_LABEL_RE.search(bolds[0].get_text(" ", strip=True) if bolds else "")
        number = number_match.group(1) if number_match else "1"
        if len(body) >= 40 and not (_RESERVED.search(sec_title) or _RESERVED.search(body[:160])):
            if max_statutes is None or int(max_statutes) >= 1:
                cite = f"Utah Const. art. {art_id}, § {number}"
                statutes.append(
                    NormalizedStatute(
                        state_code="UT",
                        state_name="Utah",
                        statute_id=cite,
                        code_name=code_name,
                        title_number=art_id,
                        section_number=number,
                        section_name=(sec_title or f"Section {number}")[:200],
                        full_text=body[:14000],
                        source_url=source_url or UT_CONST_WRAPPER,
                        official_cite=cite,
                        metadata=StatuteMetadata(),
                        structured_data={
                            "source_kind": "official_utah_constitution_html",
                            "source_authority_class": "official",
                            "discovery_method": "le_utah_gov_xcode_constitution",
                            "article_id": art_id,
                            "skip_hydrate": True,
                        },
                    )
                )
        return statutes
    childtbl = content.find(id="childtbl")
    has_sections = False
    if childtbl is not None:
        for anchor in childtbl.find_all("a", href=True):
            if _UT_SECTION_LABEL_RE.match(anchor.get_text(" ", strip=True)):
                has_sections = True
                break
    if has_sections:
        return []
    copy = BeautifulSoup(str(content), "html.parser")
    for junk_id in _JUNK_IDS:
        tag = copy.find(id=junk_id)
        if tag is not None:
            tag.decompose()
    body = _WS.sub(" ", copy.get_text(" ", strip=True)).strip()
    if len(body) < 40 or _RESERVED.search(body[:160]):
        return []
    if max_statutes is not None and int(max_statutes) < 1:
        return []
    cite = f"Utah Const. art. {art_id}"
    return [
        NormalizedStatute(
            state_code="UT",
            state_name="Utah",
            statute_id=cite,
            code_name=code_name,
            title_number=art_id,
            section_number="0",
            section_name=cite,
            full_text=body[:14000],
            source_url=source_url or UT_CONST_WRAPPER,
            official_cite=cite,
            metadata=StatuteMetadata(),
            structured_data={
                "source_kind": "official_utah_constitution_html",
                "source_authority_class": "official",
                "discovery_method": "le_utah_gov_xcode_constitution",
                "article_id": art_id,
                "skip_hydrate": True,
            },
        )
    ]


def configured_constitution_html_path() -> Optional[Path]:
    raw = str(os.environ.get("UTAH_CONSTITUTION_HTML") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None
