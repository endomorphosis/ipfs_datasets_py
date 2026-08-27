"""Official Arizona Constitution per-section HTML parser.

Adapted from Vaquill-AI/open-us-law ``ingest_state_constitutions.scrape_az``
(Apache-2.0). azleg.gov pre-splits one page per section. Catchline comes
from ``<title>``; Article 4 Part 1/Part 2 fold into article ids ``4.1`` /
``4.2``. Duplicate section numbers get a ``-vN`` suffix.

Local dump: ``ARIZONA_CONSTITUTION_HTML``.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import List, Optional, Tuple

from .base_scraper import NormalizedStatute, StatuteMetadata

AZ_TOC_URL = "https://www.azleg.gov/constitution/"
AZ_PREAMBLE_URL = "https://www.azleg.gov/const/preamble.htm"
_AZ_DOC_NAME_RE = re.compile(r"docName=(https?://\S+?\.htm)")
_AZ_PART_RE = re.compile(r"Part\s+(\d+)\s*-\s*Section\s+(\d+(?:\.\d+)?)", re.IGNORECASE)
_AZ_SECTION_RE = re.compile(r"Section\s+(\d+(?:\.\d+)?)", re.IGNORECASE)
_AZ_TITLE_CATCHLINE_RE = re.compile(r".*?-\s*(.+)$")
_AZ_TITLE_IDS_RE = re.compile(
    r"Article\s+([\d.]+)\s+Section\s+(\d+(?:\.\d+)?)",
    re.IGNORECASE,
)
_AZ_LEADING_NUM_RE = re.compile(r"^\s*\d+(?:\.\d+)?[A-Za-z]?\.\s*")
_AZ_LEADING_SECTION_RE = re.compile(
    r"^\s*Section\s+\d+(?:\.\d+)?[A-Za-z]?\.\s*",
    re.IGNORECASE,
)
_RESERVED = re.compile(r"\b(repealed|reserved|expired|renumbered)\b", re.IGNORECASE)
_WS = re.compile(r"\s+")


def az_article_index_links(html: str) -> List[Tuple[str, str, str]]:
    """Return ``(section_number, part_or_'', target_url)`` from an article index."""

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    soup = BeautifulSoup(html or "", "html.parser")
    out: List[Tuple[str, str, str]] = []
    seen: dict = {}
    for anchor in soup.find_all("a", href=True):
        href = str(anchor.get("href") or "")
        if "docName=" not in href or "/const/" not in href:
            continue
        match = _AZ_DOC_NAME_RE.search(href)
        if not match:
            continue
        target = match.group(1)
        text = anchor.get_text(strip=True)
        part_match = _AZ_PART_RE.search(text)
        if part_match:
            number, part = part_match.group(2), part_match.group(1)
        else:
            sec_match = _AZ_SECTION_RE.search(text)
            if not sec_match:
                continue
            number, part = sec_match.group(1), ""
        art_id = f"4.{part}" if part else "4"
        key = (art_id, number)
        seen[key] = seen.get(key, 0) + 1
        if seen[key] > 1:
            number = f"{number}-v{seen[key]}"
        out.append((number, part, target))
    return out


def clean_arizona_constitution_body(html: str) -> Tuple[str, str]:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return "", ""
    soup = BeautifulSoup(html or "", "html.parser")
    title = soup.find("title")
    title_text = title.get_text(strip=True) if title else ""
    catch_match = _AZ_TITLE_CATCHLINE_RE.match(title_text)
    catchline = catch_match.group(1).strip() if catch_match else ""
    body_node = soup.find("body") or soup
    full_text = body_node.get_text(" ", strip=True)
    if catchline:
        idx = full_text.find(catchline)
        if idx != -1:
            full_text = full_text[:idx] + full_text[idx + len(catchline) :]
    full_text = _AZ_LEADING_NUM_RE.sub("", full_text)
    full_text = _AZ_LEADING_SECTION_RE.sub("", full_text)
    return catchline, _WS.sub(" ", full_text).strip()


def parse_arizona_constitution_html(
    html: str,
    *,
    code_name: str = "Arizona Constitution",
    source_url: str = "",
    article_id: str = "",
    section_number: str = "",
    max_statutes: Optional[int] = None,
) -> List[NormalizedStatute]:
    if max_statutes is not None and int(max_statutes) < 1:
        return []
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    soup = BeautifulSoup(html or "", "html.parser")
    title = soup.find("title")
    title_text = title.get_text(strip=True) if title else ""
    catchline, body = clean_arizona_constitution_body(html)
    url = source_url or AZ_TOC_URL
    if "preamble" in title_text.lower() or "preamble.htm" in url.lower():
        art_id, number = "0", "0"
        cite = "Ariz. Const. Preamble"
    else:
        ids_match = _AZ_TITLE_IDS_RE.search(title_text)
        art_id = article_id or (ids_match.group(1) if ids_match else "1")
        number = section_number or (ids_match.group(2) if ids_match else "1")
        cite = f"Ariz. Const. art. {art_id}, § {number}"
    if len(body) < 40:
        return []
    if _RESERVED.search(catchline) or _RESERVED.search(body[:160]):
        return []
    return [
        NormalizedStatute(
            state_code="AZ",
            state_name="Arizona",
            statute_id=cite,
            code_name=code_name,
            title_number=art_id,
            section_number=number,
            section_name=(catchline or body.split(".", 1)[0] or f"Section {number}")[:200],
            full_text=body,
            source_url=url if "preamble" not in url.lower() else AZ_PREAMBLE_URL,
            official_cite=cite,
            metadata=StatuteMetadata(),
            structured_data={
                "source_kind": "official_arizona_constitution_html",
                "source_authority_class": "official",
                "discovery_method": "azleg_gov_constitution_html",
                "article_id": art_id,
                "skip_hydrate": True,
            },
        )
    ]


def configured_constitution_html_path() -> Optional[Path]:
    raw = str(os.environ.get("ARIZONA_CONSTITUTION_HTML") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None
