"""Official Idaho Constitution pgbrk parser.

Adapted from Vaquill-AI/open-us-law ``ingest_state_constitutions.scrape_id``
(Apache-2.0). legislature.idaho.gov/statutesrules/idconst/ section pages put
the body in ``div.pgbrk`` (no breadcrumb divs). The catchline is the
uppercase ``text-transform`` span, decomposed out of the body.

Local dump: ``IDAHO_CONSTITUTION_HTML``.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import List, Optional, Tuple
from urllib.parse import urljoin

from .base_scraper import NormalizedStatute, StatuteMetadata

ID_CONST_INDEX = "https://legislature.idaho.gov/statutesrules/idconst/"
_ID_ARTICLE_LINK_RE = re.compile(r"/idconst/(Art[IVXLC]+)/?$", re.IGNORECASE)
_ID_SECTION_LINK_RE = re.compile(r"/idconst/(Art[IVXLC]+)/(Sect[\w.]+)/?$", re.IGNORECASE)
_ID_ARTICLE_TITLE_RE = re.compile(r"^ARTICLE\s+[IVXLC]+\s+(.+)$", re.IGNORECASE)
_ID_SECTION_PREFIX_RE = re.compile(r"^Section\s+[\w.]+\.\s*", re.IGNORECASE)
_ID_UPPERCASE_STYLE_RE = re.compile(r"text-transform:\s*uppercase")
_RESERVED = re.compile(r"\b(repealed|reserved|expired|renumbered)\b", re.IGNORECASE)
_WS = re.compile(r"\s+")


def constitution_section_links(html: str, base_url: str = ID_CONST_INDEX) -> List[Tuple[str, str, str]]:
    """Return ``(article_id, section_number, url)`` from an article index."""

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    soup = BeautifulSoup(html or "", "html.parser")
    out: List[Tuple[str, str, str]] = []
    for anchor in soup.find_all("a", href=True):
        href = str(anchor.get("href") or "")
        match = _ID_SECTION_LINK_RE.search(href)
        if not match:
            continue
        art_id = match.group(1)[3:]
        number = match.group(2)[4:]
        out.append((art_id, number, urljoin(base_url, href)))
    return out


def parse_idaho_constitution_html(
    html: str,
    *,
    code_name: str = "Idaho Constitution",
    source_url: str = "",
    max_statutes: Optional[int] = None,
) -> List[NormalizedStatute]:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    soup = BeautifulSoup(html or "", "html.parser")
    container = soup.find(class_="pgbrk")
    if container is None:
        return []
    art_id, number = "I", "1"
    link = _ID_SECTION_LINK_RE.search(source_url or "")
    if link:
        art_id, number = link.group(1)[3:], link.group(2)[4:]
    h3 = soup.find("h3", class_="lso-toc")
    if h3 is not None:
        heading = _WS.sub(" ", h3.get_text(" ", strip=True)).strip()
        art_match = re.match(r"^ARTICLE\s+([IVXLC]+)", heading, re.IGNORECASE)
        if art_match:
            art_id = art_match.group(1)
    divs = container.find_all("div", recursive=False)
    content = divs[-1] if divs else container
    copy = BeautifulSoup(str(content), "html.parser")
    catchline = ""
    span = copy.find("span", style=_ID_UPPERCASE_STYLE_RE)
    if span is not None:
        catchline = _WS.sub(" ", span.get_text(" ", strip=True)).strip().rstrip(".")
        span.decompose()
    body = _WS.sub(" ", copy.get_text(" ", strip=True)).strip()
    body = _ID_SECTION_PREFIX_RE.sub("", body).strip()
    if catchline and body.startswith(catchline):
        body = body[len(catchline) :].strip()
    if len(body) < 40:
        return []
    if _RESERVED.search(catchline) or _RESERVED.search(body[:160]):
        return []
    if max_statutes is not None and int(max_statutes) < 1:
        return []
    cite = f"Idaho Const. art. {art_id}, § {number}"
    return [
        NormalizedStatute(
            state_code="ID",
            state_name="Idaho",
            statute_id=cite,
            code_name=code_name,
            title_number=art_id,
            section_number=number,
            section_name=(catchline or f"Section {number}")[:200],
            full_text=body,
            source_url=source_url or ID_CONST_INDEX,
            official_cite=cite,
            metadata=StatuteMetadata(),
            structured_data={
                "source_kind": "official_idaho_constitution_html",
                "source_authority_class": "official",
                "discovery_method": "legislature_idaho_gov_idconst",
                "article_id": art_id,
                "skip_hydrate": True,
            },
        )
    ]


def configured_constitution_html_path() -> Optional[Path]:
    raw = str(os.environ.get("IDAHO_CONSTITUTION_HTML") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None
