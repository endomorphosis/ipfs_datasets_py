"""Official Montana Constitution MCA section parser.

Adapted from Vaquill-AI/open-us-law ``ingest_state_constitutions.scrape_mt``
(Apache-2.0). mca.legmt.gov hosts the constitution as title_0000. Article
rows live in ``chapter-toc-content``; section bodies are ``section-content``
plus optional ``history-content``. Preamble / Transition Schedule rows with
no ARTICLE number are skipped.

Local dump: ``MONTANA_CONSTITUTION_HTML``.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import List, Optional, Tuple

from .base_scraper import NormalizedStatute, StatuteMetadata

MT_CONST_TOC = "https://mca.legmt.gov/bills/mca/title_0000/chapters_index.html"
_MT_ARTICLE_RE = re.compile(r"(?i)ARTICLE\s+([IVXLC]+)\.?\s*(.*)")
_MT_SECTION_HEAD_RE = re.compile(r"(?i)(?:section\s+)?(\d+[A-Za-z]?)\.\s*(.*)")
_RESERVED = re.compile(r"\b(repealed|reserved|expired|renumbered)\b", re.IGNORECASE)
_WS = re.compile(r"\s+")


def constitution_articles(html: str) -> List[Tuple[str, str]]:
    """Return ``(article_id, title)`` from a title_0000 chapters index."""

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    soup = BeautifulSoup(html or "", "html.parser")
    container = soup.find(class_="chapter-toc-content") or soup
    out: List[Tuple[str, str]] = []
    for item in container.find_all("li", class_="line"):
        anchor = item.find("a")
        if anchor is None:
            continue
        text = _WS.sub(" ", anchor.get_text(" ", strip=True)).strip()
        match = _MT_ARTICLE_RE.match(text)
        if not match:
            continue
        out.append((match.group(1), match.group(2).strip().rstrip(".")))
    return out


def parse_montana_constitution_html(
    html: str,
    *,
    code_name: str = "Montana Constitution",
    source_url: str = "",
    max_statutes: Optional[int] = None,
) -> List[NormalizedStatute]:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    soup = BeautifulSoup(html or "", "html.parser")
    text_div = soup.find(class_="section-content")
    if text_div is None:
        return []
    body = text_div.get_text(" ", strip=True)
    history_div = soup.find(class_="history-content")
    if history_div is not None:
        history = history_div.get_text(" ", strip=True)
        if history:
            body = f"{body} History: {history}"
    body = _WS.sub(" ", body).strip()
    if len(body) < 40:
        return []
    heading = ""
    h2 = soup.find("h2") or soup.find("h1")
    if h2 is not None:
        heading = h2.get_text(" ", strip=True)
    h3 = soup.find("h3")
    sec_text = h3.get_text(" ", strip=True) if h3 is not None else ""
    art_match = _MT_ARTICLE_RE.search(heading)
    art_id = art_match.group(1) if art_match else "I"
    sec_match = _MT_SECTION_HEAD_RE.match(sec_text) if sec_text else None
    number = sec_match.group(1) if sec_match else "1"
    sec_title = sec_match.group(2).strip() if sec_match else ""
    if _RESERVED.search(sec_title) or _RESERVED.search(body[:160]):
        return []
    if max_statutes is not None and int(max_statutes) < 1:
        return []
    cite = f"Mont. Const. art. {art_id}, § {number}"
    return [
        NormalizedStatute(
            state_code="MT",
            state_name="Montana",
            statute_id=cite,
            code_name=code_name,
            title_number=art_id,
            section_number=number,
            section_name=(sec_title or f"Section {number}")[:200],
            full_text=body,
            source_url=source_url or MT_CONST_TOC,
            official_cite=cite,
            metadata=StatuteMetadata(),
            structured_data={
                "source_kind": "official_montana_constitution_html",
                "source_authority_class": "official",
                "discovery_method": "mca_legmt_gov_constitution",
                "article_id": art_id,
                "skip_hydrate": True,
            },
        )
    ]


def configured_constitution_html_path() -> Optional[Path]:
    raw = str(os.environ.get("MONTANA_CONSTITUTION_HTML") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None
