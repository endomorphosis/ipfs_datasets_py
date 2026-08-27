"""Official Florida Constitution HTML parser.

Adapted from Vaquill-AI/open-us-law ``ingest_state_constitutions.scrape_fl``
(Apache-2.0). flsenate.gov/Laws/Constitution uses the same ``div.Article`` /
``div.Section`` markup as the statute pages. Walk ``div.Section`` by class so
the CatchlineIndex mini-TOC is not admitted as sections.

Local dump: ``FLORIDA_CONSTITUTION_HTML``.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import List, Optional

from .base_scraper import NormalizedStatute, StatuteMetadata

FL_CONST_URL = "https://www.flsenate.gov/Laws/Constitution"
_FL_ARTICLE_NUM_RE = re.compile(r"ARTICLE\s+([IVXLC]+)", re.IGNORECASE)
_FL_SECTION_NUM_RE = re.compile(r"(\d+[A-Za-z]?)")
_RESERVED = re.compile(r"\b(repealed|reserved|expired|renumbered)\b", re.IGNORECASE)
_WS = re.compile(r"\s+")


def parse_florida_constitution_html(
    html: str,
    *,
    code_name: str = "Florida Constitution",
    max_statutes: Optional[int] = None,
) -> List[NormalizedStatute]:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    soup = BeautifulSoup(html or "", "html.parser")
    statutes: List[NormalizedStatute] = []
    for art_div in soup.select("div.Article"):
        if max_statutes is not None and len(statutes) >= int(max_statutes):
            break
        num_div = art_div.select_one("div.ArticleNumber")
        if num_div is None:
            continue
        art_match = _FL_ARTICLE_NUM_RE.search(num_div.get_text(strip=True))
        if not art_match:
            continue
        art_id = art_match.group(1)
        for sec_div in art_div.select("div.Section"):
            if max_statutes is not None and len(statutes) >= int(max_statutes):
                break
            num_span = sec_div.select_one("span.SectionNumber")
            catch_span = sec_div.select_one("span.CatchlineText")
            body_span = sec_div.select_one("span.SectionBody")
            if num_span is None or body_span is None:
                continue
            sec_match = _FL_SECTION_NUM_RE.search(num_span.get_text(strip=True))
            if not sec_match:
                continue
            number = sec_match.group(1)
            catchline = catch_span.get_text(strip=True) if catch_span else ""
            body_text = body_span.get_text(" ", strip=True)
            history_div = sec_div.select_one("div.History")
            if history_div is not None:
                body_text = f"{body_text} {history_div.get_text(' ', strip=True)}"
            body_text = _WS.sub(" ", body_text).strip()
            if not body_text:
                continue
            if _RESERVED.search(catchline) or _RESERVED.search(body_text[:160]):
                continue
            heading = catchline or (body_text.split(".", 1)[0] or f"Section {number}")
            cite = f"Fla. Const. art. {art_id}, § {number}"
            statutes.append(
                NormalizedStatute(
                    state_code="FL",
                    state_name="Florida",
                    statute_id=cite,
                    code_name=code_name,
                    title_number=art_id,
                    section_number=number,
                    section_name=heading[:200],
                    full_text=body_text,
                    source_url=FL_CONST_URL,
                    official_cite=cite,
                    metadata=StatuteMetadata(),
                    structured_data={
                        "source_kind": "official_florida_constitution_html",
                        "source_authority_class": "official",
                        "discovery_method": "flsenate_gov_constitution_html",
                        "article_id": art_id,
                        "skip_hydrate": True,
                    },
                )
            )
    return statutes


def configured_constitution_html_path() -> Optional[Path]:
    raw = str(os.environ.get("FLORIDA_CONSTITUTION_HTML") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None
