"""Official Connecticut Constitution parser.

Adapted from Vaquill-AI/open-us-law ``ingest_state_constitutions._ct_split_articles``
(Apache-2.0). Main articles use spelled ordinals (``ARTICLE FIRST``);
amendment articles use Roman numerals and are prefixed ``AMEND`` so they
cannot collide. Section markers are ``SEC.N.`` or ``Sec. N.``.

Local dump: ``CONNECTICUT_CONSTITUTION_HTML``.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import List, Optional, Tuple

from .base_scraper import NormalizedStatute, StatuteMetadata

CT_CONST_URL = "https://www.cga.ct.gov/asp/Content/constitutions/CTConstitution.htm"
_CT_ORDINALS = {
    "FIRST": "I",
    "SECOND": "II",
    "THIRD": "III",
    "FOURTH": "IV",
    "FIFTH": "V",
    "SIXTH": "VI",
    "SEVENTH": "VII",
    "EIGHTH": "VIII",
    "NINTH": "IX",
    "TENTH": "X",
    "ELEVENTH": "XI",
    "TWELFTH": "XII",
    "THIRTEENTH": "XIII",
    "FOURTEENTH": "XIV",
}
_CT_MAIN_ARTICLE_RE = re.compile(
    r"\n\s*ARTICLE\s+(" + "|".join(_CT_ORDINALS) + r")\.?\*?\s*[^\n]*\n"
)
_CT_AMEND_ARTICLE_RE = re.compile(r"\n\s*ARTICLE\s+([IVXLC]+)\.\s*\n")
_CT_SECTION_RE = re.compile(
    r"\n\s*(?:SEC\.|SECTION|Section|Sec\.)\s*(\d+(?:\.\d+)?[A-Za-z]?)\.?\s*"
)
_RESERVED = re.compile(r"\b(repealed|reserved|expired|renumbered)\b", re.IGNORECASE)
_WS = re.compile(r"\s+")


def split_connecticut_articles(body_text: str) -> List[Tuple[str, str]]:
    main_parts = _CT_MAIN_ARTICLE_RE.split(body_text)
    if len(main_parts) <= 1:
        return []
    main_iter = [
        [_CT_ORDINALS[main_parts[index]], main_parts[index + 1]]
        for index in range(1, len(main_parts) - 1, 2)
    ]
    tail = main_parts[-1]
    amend_parts = _CT_AMEND_ARTICLE_RE.split(tail)
    main_iter[-1][1] = amend_parts[0]
    amend_iter = [
        (f"AMEND{amend_parts[index]}", amend_parts[index + 1])
        for index in range(1, len(amend_parts) - 1, 2)
    ]
    return [(art_id, span) for art_id, span in main_iter] + amend_iter


def parse_connecticut_constitution_html(
    html: str,
    *,
    code_name: str = "Connecticut Constitution",
    max_statutes: Optional[int] = None,
) -> List[NormalizedStatute]:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    soup = BeautifulSoup(html or "", "html.parser")
    main = soup.find("main") or soup.find("body") or soup
    body_text = "\n" + main.get_text("\n", strip=True)
    statutes: List[NormalizedStatute] = []
    for art_id, span in split_connecticut_articles(body_text):
        if max_statutes is not None and len(statutes) >= int(max_statutes):
            break
        matches = list(_CT_SECTION_RE.finditer("\n" + span))
        for index, match in enumerate(matches):
            if max_statutes is not None and len(statutes) >= int(max_statutes):
                break
            number = match.group(1)
            end = matches[index + 1].start() if index + 1 < len(matches) else len(span) + 1
            raw = _WS.sub(" ", ("\n" + span)[match.end() : end].replace("\xa0", " ")).strip()
            if len(raw) < 40 or _RESERVED.search(raw[:160]):
                continue
            cite = f"Conn. Const. art. {art_id}, § {number}"
            statutes.append(
                NormalizedStatute(
                    state_code="CT",
                    state_name="Connecticut",
                    statute_id=cite,
                    code_name=code_name,
                    title_number=art_id,
                    section_number=number,
                    section_name=(raw.split(".", 1)[0] or f"Section {number}")[:200],
                    full_text=raw[:14000],
                    source_url=CT_CONST_URL,
                    official_cite=cite,
                    metadata=StatuteMetadata(),
                    structured_data={
                        "source_kind": "official_connecticut_constitution_html",
                        "source_authority_class": "official",
                        "discovery_method": "cga_ct_gov_constitution",
                        "article_id": art_id,
                        "skip_hydrate": True,
                    },
                )
            )
    return statutes


def configured_constitution_html_path() -> Optional[Path]:
    raw = str(os.environ.get("CONNECTICUT_CONSTITUTION_HTML") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None
