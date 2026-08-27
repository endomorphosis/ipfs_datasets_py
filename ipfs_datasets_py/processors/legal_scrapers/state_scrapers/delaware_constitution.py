"""Official Delaware Constitution parser.

Adapted from Vaquill-AI/open-us-law ``ingest_state_constitutions`` Delaware
section split (Apache-2.0). Captions are ``§ N.``; a following
``Section N.`` restatement is ignored as a duplicate marker.

Local dump: ``DELAWARE_CONSTITUTION_HTML``.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import List, Optional

from .base_scraper import NormalizedStatute, StatuteMetadata

DE_CONST_URL = "https://delcode.delaware.gov/constitution/index.html"
_DE_ARTICLE_RE = re.compile(r"\n\s*(?:ARTICLE|Article)\s+([IVXLC]+)\b")
_DE_SECTION_RE = re.compile(r"(?:\A|\n)\s*§\s*(\d+(?:\.\d+)?[A-Za-z]?)\.?\s*")
_RESERVED = re.compile(r"\b(repealed|reserved|expired|renumbered)\b", re.IGNORECASE)
_WS = re.compile(r"\s+")


def parse_delaware_constitution_html(
    html: str,
    *,
    code_name: str = "Delaware Constitution",
    max_statutes: Optional[int] = None,
) -> List[NormalizedStatute]:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    soup = BeautifulSoup(html or "", "html.parser")
    main = soup.find("main") or soup.find("body") or soup
    body_text = "\n" + main.get_text("\n", strip=True)
    art_matches = list(_DE_ARTICLE_RE.finditer(body_text))
    if not art_matches:
        art_iter = [("I", body_text)]
    else:
        art_iter = [
            (
                match.group(1),
                body_text[
                    match.end() : art_matches[index + 1].start()
                    if index + 1 < len(art_matches)
                    else len(body_text)
                ],
            )
            for index, match in enumerate(art_matches)
        ]
    statutes: List[NormalizedStatute] = []
    for art_id, span in art_iter:
        if max_statutes is not None and len(statutes) >= int(max_statutes):
            break
        matches = list(_DE_SECTION_RE.finditer("\n" + span))
        for index, match in enumerate(matches):
            if max_statutes is not None and len(statutes) >= int(max_statutes):
                break
            number = match.group(1)
            end = matches[index + 1].start() if index + 1 < len(matches) else len(span) + 1
            raw = _WS.sub(" ", ("\n" + span)[match.end() : end].replace("\xa0", " ")).strip()
            raw = re.sub(r"^Section\s+\d+[A-Za-z]?\.?\s*", "", raw, flags=re.I).strip()
            if not raw or _RESERVED.search(raw[:160]):
                continue
            cite = f"Del. Const. art. {art_id}, § {number}"
            statutes.append(
                NormalizedStatute(
                    state_code="DE",
                    state_name="Delaware",
                    statute_id=cite,
                    code_name=code_name,
                    title_number=art_id,
                    section_number=number,
                    section_name=(raw.split(".", 1)[0] or f"Section {number}")[:200],
                    full_text=raw,
                    source_url=DE_CONST_URL,
                    official_cite=cite,
                    metadata=StatuteMetadata(),
                    structured_data={
                        "source_kind": "official_delaware_constitution_html",
                        "source_authority_class": "official",
                        "discovery_method": "delcode_delaware_gov_constitution",
                        "article_id": art_id,
                        "skip_hydrate": True,
                    },
                )
            )
    return statutes


def configured_constitution_html_path() -> Optional[Path]:
    raw = str(os.environ.get("DELAWARE_CONSTITUTION_HTML") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None
