"""Official Minnesota Constitution HTML parser.

Adapted from Vaquill-AI/open-us-law ``ingest_state_constitutions.scrape_mn``
(Apache-2.0). revisor.mn.gov/constitution/ serves the whole document with
``div.article`` / ``div.section`` markup. Preamble body is siblings of the
Preamble h2 and must stop at the next sibling ``h2`` or ``div`` (the first
article wrapper), not at a nested heading.

Local dump: ``MINNESOTA_CONSTITUTION_HTML``.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import List, Optional

from .base_scraper import NormalizedStatute, StatuteMetadata

MN_CONST_URL = "https://www.revisor.mn.gov/constitution/"
_MN_ARTICLE_NUM_RE = re.compile(r"ARTICLE\s+([IVXLC]+)", re.IGNORECASE)
_MN_SECTION_NUM_RE = re.compile(r"(\d+[A-Za-z]?)")
_RESERVED = re.compile(r"\b(repealed|reserved|expired|renumbered)\b", re.IGNORECASE)
_WS = re.compile(r"\s+")


def _row(
    *,
    article_id: str,
    number: str,
    heading: str,
    body: str,
    code_name: str,
) -> NormalizedStatute:
    cite = (
        "Minn. Const. Preamble"
        if number == "0"
        else f"Minn. Const. art. {article_id}, § {number}"
    )
    return NormalizedStatute(
        state_code="MN",
        state_name="Minnesota",
        statute_id=cite,
        code_name=code_name,
        title_number=article_id,
        section_number=number,
        section_name=heading[:200] or f"Section {number}",
        full_text=body[:14000],
        source_url=MN_CONST_URL,
        official_cite=cite,
        metadata=StatuteMetadata(),
        structured_data={
            "source_kind": "official_minnesota_constitution_html",
            "source_authority_class": "official",
            "discovery_method": "revisor_mn_gov_constitution_html",
            "article_id": article_id,
            "skip_hydrate": True,
        },
    )


def parse_minnesota_constitution_html(
    html: str,
    *,
    code_name: str = "Minnesota Constitution",
    max_statutes: Optional[int] = None,
) -> List[NormalizedStatute]:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    soup = BeautifulSoup(html or "", "html.parser")
    statutes: List[NormalizedStatute] = []
    preamble_h2 = soup.find("h2", string=re.compile(r"^\s*Preamble\s*$", re.IGNORECASE))
    if preamble_h2 is not None:
        parts = []
        for sib in preamble_h2.find_next_siblings():
            if getattr(sib, "name", None) in ("h2", "div"):
                break
            parts.append(sib.get_text(" ", strip=True))
        preamble_text = _WS.sub(" ", " ".join(p for p in parts if p)).strip()
        if (
            len(preamble_text) >= 40
            and not _RESERVED.search(preamble_text[:160])
            and (max_statutes is None or len(statutes) < int(max_statutes))
        ):
            statutes.append(
                _row(
                    article_id="0",
                    number="0",
                    heading="Preamble",
                    body=preamble_text,
                    code_name=code_name,
                )
            )
    for art_div in soup.select("div.article"):
        if max_statutes is not None and len(statutes) >= int(max_statutes):
            break
        headers = art_div.find_all("h2", recursive=False)
        if not headers:
            continue
        art_match = _MN_ARTICLE_NUM_RE.search(headers[0].get_text(strip=True))
        if not art_match:
            continue
        art_id = art_match.group(1)
        for sec_div in art_div.find_all("div", class_="section", recursive=False):
            if max_statutes is not None and len(statutes) >= int(max_statutes):
                break
            h3 = sec_div.find("h3", class_="section_no")
            if h3 is None:
                continue
            headnote = h3.find("span", class_="headnote")
            sec_title_text = headnote.get_text(strip=True) if headnote else ""
            num_text = h3.get_text(" ", strip=True)
            if sec_title_text:
                num_text = num_text.replace(sec_title_text, "")
            sec_match = _MN_SECTION_NUM_RE.search(num_text)
            if not sec_match:
                continue
            number = sec_match.group(1)
            body_copy = BeautifulSoup(str(sec_div), "html.parser")
            h3_copy = body_copy.find("h3", class_="section_no")
            if h3_copy is not None:
                h3_copy.decompose()
            body_text = _WS.sub(" ", body_copy.get_text(" ", strip=True)).strip()
            if len(body_text) < 40:
                continue
            if _RESERVED.search(sec_title_text) or _RESERVED.search(body_text[:160]):
                continue
            heading = sec_title_text or (body_text.split(".", 1)[0] or f"Section {number}")
            statutes.append(
                _row(
                    article_id=art_id,
                    number=number,
                    heading=heading,
                    body=body_text,
                    code_name=code_name,
                )
            )
    return statutes


def configured_constitution_html_path() -> Optional[Path]:
    raw = str(os.environ.get("MINNESOTA_CONSTITUTION_HTML") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None
