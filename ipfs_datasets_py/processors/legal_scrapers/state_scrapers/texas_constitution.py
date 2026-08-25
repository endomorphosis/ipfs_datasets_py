"""Official Texas Constitution article parser.

Adapted from Vaquill-AI/open-us-law ``ingest_state_constitutions.scrape_tx``
(Apache-2.0). ``statutes.capitol.texas.gov`` now serves an Angular SPA shell;
``tcss.legis.texas.gov/resources/CN/htm/CN.{N}.htm`` still has section text.

Local dump: ``TEXAS_CONSTITUTION_HTML``.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import List, Optional

from .base_scraper import NormalizedStatute, StatuteMetadata

TX_BASE = "https://tcss.legis.texas.gov/resources/CN"
_SECTION_SPLIT = re.compile(
    r"\n\s*(?:Sec\.|SECTION|SEC\.)\s+(\d+(?:[a-z]?(?:-\d+)?))\.\s*"
)
_RESERVED = re.compile(r"\b(repealed|reserved|expired|renumbered)\b", re.IGNORECASE)
_WS = re.compile(r"\s+")


def tx_article_url(article_id: str) -> str:
    number = str(article_id or "1").strip()
    return f"{TX_BASE}/htm/CN.{number}.htm"


def looks_like_constitution_spa_shell(html: str) -> bool:
    text = html or ""
    if len(text) > 20000:
        return False
    lowered = text.lower()
    return "<base href" in lowered and not _SECTION_SPLIT.search("\n" + text)


def parse_texas_constitution_html(
    html: str,
    *,
    article_id: str = "1",
    code_name: str = "Texas Constitution",
    max_statutes: Optional[int] = None,
) -> List[NormalizedStatute]:
    if looks_like_constitution_spa_shell(html):
        return []
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    soup = BeautifulSoup(html or "", "html.parser")
    body_text = soup.get_text("\n", strip=True)
    parts = _SECTION_SPLIT.split("\n" + body_text)
    if len(parts) <= 1:
        return []
    pairs = [(parts[index], parts[index + 1]) for index in range(1, len(parts) - 1, 2)]
    article = str(article_id or "1")
    source = tx_article_url(article)
    statutes: List[NormalizedStatute] = []
    for number, raw in pairs:
        if max_statutes is not None and len(statutes) >= int(max_statutes):
            break
        text = _WS.sub(" ", (raw or "").replace("\xa0", " ")).strip()
        if len(text) < 40:
            continue
        if _RESERVED.search(text[:160]):
            continue
        heading = (text.split(".", 1)[0] or f"Section {number}")[:200]
        statutes.append(
            NormalizedStatute(
                state_code="TX",
                state_name="Texas",
                statute_id=f"Tex. Const. art. {article}, § {number}",
                code_name=code_name,
                title_number=article,
                section_number=number,
                section_name=heading,
                full_text=text[:14000],
                source_url=source,
                official_cite=f"Tex. Const. art. {article}, § {number}",
                metadata=StatuteMetadata(),
                structured_data={
                    "source_kind": "official_texas_constitution_html",
                    "source_authority_class": "official",
                    "discovery_method": "tcss_legis_cn_htm",
                    "article_id": article,
                    "skip_hydrate": True,
                },
            )
        )
    return statutes


def configured_constitution_html_path() -> Optional[Path]:
    raw = str(os.environ.get("TEXAS_CONSTITUTION_HTML") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None
