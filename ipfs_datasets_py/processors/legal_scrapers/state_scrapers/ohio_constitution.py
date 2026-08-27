"""Official Ohio Constitution article-page parser.

Adapted from Vaquill-AI/open-us-law ``ingest_state_constitutions.scrape_oh``
(Apache-2.0). codes.ohio.gov/ohio-constitution/article-N uses the same CMS
as the Revised Code: ``table.laws-table`` rows with a content-head citation
and ``div.laws-body`` text.

Local dump: ``OHIO_CONSTITUTION_HTML``.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import List, Optional

from .base_scraper import NormalizedStatute, StatuteMetadata

OH_CONST_TOC = "https://codes.ohio.gov/ohio-constitution"
OH_ARTICLE_URL_TMPL = "https://codes.ohio.gov/ohio-constitution/article-{n}"
_OH_ARTICLE_HREF_RE = re.compile(r"ohio-constitution/article-(\d+)")
_OH_ARTICLE_H1_RE = re.compile(r"(?i)article\s+([IVXLC]+)\s*\|\s*(.*)")
_OH_SECTION_RE = re.compile(r"(?i)section\s+(\d+[A-Za-z]?)")
_RESERVED = re.compile(r"\b(repealed|reserved|expired|renumbered)\b", re.IGNORECASE)
_WS = re.compile(r"\s+")


def constitution_article_ids(html: str) -> List[str]:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    soup = BeautifulSoup(html or "", "html.parser")
    ids: List[str] = []
    for anchor in soup.find_all("a", href=True):
        match = _OH_ARTICLE_HREF_RE.search(str(anchor.get("href") or ""))
        if match and match.group(1) not in ids:
            ids.append(match.group(1))
    return ids


def parse_ohio_constitution_html(
    html: str,
    *,
    code_name: str = "Ohio Constitution",
    source_url: str = "",
    max_statutes: Optional[int] = None,
) -> List[NormalizedStatute]:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    soup = BeautifulSoup(html or "", "html.parser")
    h1 = soup.find("h1")
    art_id, art_title = "I", ""
    if h1 is not None:
        h1_text = h1.get_text(" ", strip=True)
        match = _OH_ARTICLE_H1_RE.match(h1_text)
        if match:
            art_id, art_title = match.group(1), match.group(2).strip()
    table = soup.find("table", class_="laws-table")
    if table is None:
        return []
    url = source_url or OH_CONST_TOC
    statutes: List[NormalizedStatute] = []
    for row in table.find_all("tr"):
        if max_statutes is not None and len(statutes) >= int(max_statutes):
            break
        head = row.find(class_="content-head")
        body_div = row.find("div", class_="laws-body")
        if head is None or body_div is None:
            continue
        head_text = _WS.sub(" ", head.get_text(" ", strip=True)).strip()
        parts = [part.strip() for part in head_text.split("|")]
        cite_part = parts[0] if parts else ""
        sec_title = parts[1] if len(parts) > 1 else ""
        sec_match = _OH_SECTION_RE.search(cite_part)
        if not sec_match:
            continue
        number = sec_match.group(1)
        body = body_div.get_text(" ", strip=True)
        info = row.find("div", class_="laws-section-info")
        if info is not None:
            info_text = _WS.sub(" ", info.get_text(" ", strip=True)).strip()
            if info_text:
                body = f"{body} {info_text}"
        body = _WS.sub(" ", body).strip()
        if len(body) < 40:
            continue
        if _RESERVED.search(sec_title) or _RESERVED.search(body[:160]):
            continue
        cite = f"Ohio Const. art. {art_id}, § {number}"
        statutes.append(
            NormalizedStatute(
                state_code="OH",
                state_name="Ohio",
                statute_id=cite,
                code_name=code_name,
                title_number=art_id,
                section_number=number,
                section_name=(sec_title or art_title or f"Section {number}")[:200],
                full_text=body,
                source_url=url,
                official_cite=cite,
                metadata=StatuteMetadata(),
                structured_data={
                    "source_kind": "official_ohio_constitution_html",
                    "source_authority_class": "official",
                    "discovery_method": "codes_ohio_gov_constitution",
                    "article_id": art_id,
                    "skip_hydrate": True,
                },
            )
        )
    return statutes


def configured_constitution_html_path() -> Optional[Path]:
    raw = str(os.environ.get("OHIO_CONSTITUTION_HTML") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None
