"""Official California Constitution article parser.

Adapted from Vaquill-AI/open-us-law ``ingest_state_constitutions.scrape_ca``
(Apache-2.0). leginfo requires a space in lettered articles (``XIII A``, not
``XIIIA``) or it silently serves an Angular SPA shell with no SECTION markers.

Local dump: ``CALIFORNIA_CONSTITUTION_HTML``.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import quote

from .base_scraper import NormalizedStatute, StatuteMetadata

CA_BASE = "https://leginfo.legislature.ca.gov/faces/codes_displayText.xhtml"
CA_ROMAN = (
    "I", "II", "III", "IIIB", "IV", "V", "VI", "VII", "VIII", "IX", "X", "XA",
    "XB", "XBA", "XI", "XII", "XIII", "XIIIA", "XIIIB", "XIIIC", "XIIID", "XIV",
    "XV", "XVI", "XVII", "XVIII", "XIX", "XIXA", "XIXB", "XIXC", "XIXD", "XX",
    "XXI", "XXII", "XXXIV", "XXXV",
)
_CA_SPACED_ARTICLE_QUERIES: Dict[str, str] = {
    "IIIB": "III B",
    "XA": "X A",
    "XB": "X B",
    "XBA": "X B A",
    "XIIIA": "XIII A",
    "XIIIB": "XIII B",
    "XIIIC": "XIII C",
    "XIIID": "XIII D",
    "XIXA": "XIX A",
    "XIXB": "XIX B",
    "XIXC": "XIX C",
    "XIXD": "XIX D",
}
_SECTION_SPLIT = re.compile(r"\n\s*(?:SECTION|SEC\.)\s+(\d+(?:\.\d+)?[A-Z]?)\.\s*")
_RESERVED = re.compile(r"\b(repealed|reserved|expired|renumbered)\b", re.IGNORECASE)
_WS = re.compile(r"\s+")


def ca_article_query(article_id: str) -> str:
    token = str(article_id or "").strip().upper()
    return _CA_SPACED_ARTICLE_QUERIES.get(token, token)


def ca_article_url(article_id: str) -> str:
    return f"{CA_BASE}?lawCode=CONS&article={quote(ca_article_query(article_id))}"


def looks_like_constitution_spa_shell(html: str) -> bool:
    text = html or ""
    if len(text) > 20000:
        return False
    lowered = text.lower()
    return "<base href" in lowered and not _SECTION_SPLIT.search(text)


def parse_california_constitution_html(
    html: str,
    *,
    article_id: str = "I",
    code_name: str = "California Constitution",
    max_statutes: Optional[int] = None,
) -> List[NormalizedStatute]:
    if looks_like_constitution_spa_shell(html):
        return []
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    soup = BeautifulSoup(html or "", "html.parser")
    container = soup.find(id="manylawsections") or soup.find("body") or soup
    body_text = container.get_text("\n", strip=True)
    parts = _SECTION_SPLIT.split("\n" + body_text)
    if len(parts) <= 1:
        return []
    pairs = [(parts[index], parts[index + 1]) for index in range(1, len(parts) - 1, 2)]
    statutes: List[NormalizedStatute] = []
    article = str(article_id or "I")
    source = ca_article_url(article)
    for number, raw in pairs:
        if max_statutes is not None and len(statutes) >= int(max_statutes):
            break
        text = _WS.sub(" ", (raw or "").replace("\xa0", " ")).strip()
        if len(text) < 40:
            continue
        if _RESERVED.search(text[:160]):
            continue
        heading = text.split(".", 1)[0][:200]
        statutes.append(
            NormalizedStatute(
                state_code="CA",
                state_name="California",
                statute_id=f"Cal. Const. art. {article}, § {number}",
                code_name=code_name,
                title_number=article,
                section_number=number,
                section_name=heading or f"Section {number}",
                full_text=text[:14000],
                source_url=source,
                official_cite=f"Cal. Const. art. {article}, § {number}",
                metadata=StatuteMetadata(),
                structured_data={
                    "source_kind": "official_california_constitution_html",
                    "source_authority_class": "official",
                    "discovery_method": "leginfo_cons_article_section",
                    "article_id": article,
                    "skip_hydrate": True,
                },
            )
        )
    return statutes


def configured_constitution_html_path() -> Optional[Path]:
    raw = str(os.environ.get("CALIFORNIA_CONSTITUTION_HTML") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None
