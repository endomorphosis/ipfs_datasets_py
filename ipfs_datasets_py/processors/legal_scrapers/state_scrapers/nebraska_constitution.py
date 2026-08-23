"""Official Nebraska Constitution print-view parser.

Adapted from Vaquill-AI/open-us-law ``ingest_state_constitutions.scrape_ne``
(Apache-2.0). nebraskalegislature.gov serves one clause per
``articles.php?article=I-1&print=true`` page. ``div.anno`` case-law notes
are dropped; ``div.source`` session-law notes stay. TOC ``print`` links are
not clause codes.

Local dump: ``NEBRASKA_CONSTITUTION_HTML``.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import List, Optional
from urllib.parse import parse_qs, urlparse

from .base_scraper import NormalizedStatute, StatuteMetadata

NE_CONST_TOC = "https://nebraskalegislature.gov/laws/browse-constitution.php"
NE_ARTICLE_URL_TMPL = (
    "https://nebraskalegislature.gov/laws/articles.php?article={code}&print=true"
)
_NE_CLAUSE_CODE_RE = re.compile(r"^([IVXLC]+)-(\d+[A-Za-z]?)$")
_RESERVED = re.compile(r"\b(repealed|reserved|expired|renumbered)\b", re.IGNORECASE)
_WS = re.compile(r"\s+")


def constitution_clause_codes(html: str) -> List[str]:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    soup = BeautifulSoup(html or "", "html.parser")
    codes: List[str] = []
    seen = set()
    for anchor in soup.find_all("a", href=True):
        href = str(anchor.get("href") or "")
        if "print" in href.lower():
            continue
        match = re.search(r"[?&]article=([^&]+)", href)
        if not match:
            continue
        code = match.group(1)
        if (code == "Preamble" or _NE_CLAUSE_CODE_RE.match(code)) and code not in seen:
            seen.add(code)
            codes.append(code)
    return codes


def parse_nebraska_constitution_html(
    html: str,
    *,
    code_name: str = "Nebraska Constitution",
    source_url: str = "",
    clause_code: str = "",
    max_statutes: Optional[int] = None,
) -> List[NormalizedStatute]:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    soup = BeautifulSoup(html or "", "html.parser")
    code = clause_code
    if not code:
        query = parse_qs(urlparse(source_url or "").query)
        code = (query.get("article") or [""])[0]
    clause_match = _NE_CLAUSE_CODE_RE.match(code or "")
    if (code or "").lower() == "preamble":
        art_id, number = "0", "0"
    elif clause_match:
        art_id, number = clause_match.group(1), clause_match.group(2)
    else:
        strong = soup.find("strong")
        strong_text = strong.get_text(" ", strip=True) if strong else ""
        token = re.split(r"[\s.]", strong_text or "")[0]
        clause_match = _NE_CLAUSE_CODE_RE.match(token)
        if clause_match:
            art_id, number = clause_match.group(1), clause_match.group(2)
        elif "preamble" in strong_text.lower():
            art_id, number = "0", "0"
        else:
            art_id, number = "I", "1"
    for anno in soup.find_all("div", class_="anno"):
        anno.decompose()
    strong = soup.find("strong")
    title_text = _WS.sub(" ", strong.get_text(" ", strip=True)).strip() if strong else ""
    if code:
        title_text = re.sub(rf"^{re.escape(code)}\.?\s*", "", title_text).strip()
    body_parts = [para.get_text(" ", strip=True) for para in soup.find_all("p")]
    source_div = soup.find("div", class_="source")
    if source_div is not None:
        body_parts.append(source_div.get_text(" ", strip=True))
    body = _WS.sub(" ", " ".join(part for part in body_parts if part)).strip()
    if len(body) < 40:
        return []
    if _RESERVED.search(title_text) or _RESERVED.search(body[:160]):
        return []
    if max_statutes is not None and int(max_statutes) < 1:
        return []
    cite = (
        "Neb. Const. Preamble"
        if art_id == "0"
        else f"Neb. Const. art. {art_id}, § {number}"
    )
    return [
        NormalizedStatute(
            state_code="NE",
            state_name="Nebraska",
            statute_id=cite,
            code_name=code_name,
            title_number=art_id,
            section_number=number,
            section_name=(title_text or f"Section {number}")[:200],
            full_text=body[:14000],
            source_url=source_url or NE_ARTICLE_URL_TMPL.format(code=code or f"{art_id}-{number}"),
            official_cite=cite,
            metadata=StatuteMetadata(),
            structured_data={
                "source_kind": "official_nebraska_constitution_html",
                "source_authority_class": "official",
                "discovery_method": "nebraskalegislature_constitution_print",
                "article_id": art_id,
                "skip_hydrate": True,
            },
        )
    ]


def configured_constitution_html_path() -> Optional[Path]:
    raw = str(os.environ.get("NEBRASKA_CONSTITUTION_HTML") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None
