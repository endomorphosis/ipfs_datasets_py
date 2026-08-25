"""Official New Hampshire Constitution parser.

Adapted from Vaquill-AI/open-us-law ``ingest_state_constitutions._parse_nh``
(Apache-2.0). Part First / Part Second each contain numbered ``Article N.``
or ``[Art.] N.`` units (NH's Article is this corpus's section).

Local dump: ``NEW_HAMPSHIRE_CONSTITUTION_HTML``.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import List, Optional

from .base_scraper import NormalizedStatute, StatuteMetadata

NH_CONST_URL = "https://www.nh.gov/glance/constitution.htm"
_NH_PART_RE = re.compile(
    r"\n[^\S\n]*(Part First|Part Second)[^\S\n]*(?:—|-|:)?[^\n]*\n"
)
_NH_ART_RE = re.compile(r"\n\s*(?:\[Art\.\]|Article)\s+(\d+(?:-[a-z])?)\.\s*")
_NH_PART_LABEL = {"Part First": "1", "Part Second": "2"}
_RESERVED = re.compile(r"\b(repealed|reserved|expired|renumbered)\b", re.IGNORECASE)
_WS = re.compile(r"\s+")


def parse_new_hampshire_constitution_html(
    html: str,
    *,
    code_name: str = "New Hampshire Constitution",
    max_statutes: Optional[int] = None,
) -> List[NormalizedStatute]:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    soup = BeautifulSoup(html or "", "html.parser")
    main = soup.find("main") or soup.find("body") or soup
    body_text = "\n" + main.get_text("\n", strip=True)
    parts = _NH_PART_RE.split(body_text)
    if len(parts) <= 1:
        return []
    part_pairs = [(parts[index], parts[index + 1]) for index in range(1, len(parts) - 1, 2)]
    statutes: List[NormalizedStatute] = []
    for part_name, part_body in part_pairs:
        if max_statutes is not None and len(statutes) >= int(max_statutes):
            break
        part_id = _NH_PART_LABEL.get(part_name, part_name)
        pieces = _NH_ART_RE.split("\n" + part_body)
        art_pairs = [(pieces[index], pieces[index + 1]) for index in range(1, len(pieces) - 1, 2)]
        for number, art_body in art_pairs:
            if max_statutes is not None and len(statutes) >= int(max_statutes):
                break
            raw = _WS.sub(" ", art_body.replace("\xa0", " ")).strip()
            if len(raw) < 40 or _RESERVED.search(raw[:160]):
                continue
            cite = f"N.H. Const. pt. {part_id}, art. {number}"
            statutes.append(
                NormalizedStatute(
                    state_code="NH",
                    state_name="New Hampshire",
                    statute_id=cite,
                    code_name=code_name,
                    title_number=str(part_id),
                    section_number=number,
                    section_name=(raw.split(".", 1)[0] or f"Article {number}")[:200],
                    full_text=raw[:14000],
                    source_url=NH_CONST_URL,
                    official_cite=cite,
                    metadata=StatuteMetadata(),
                    structured_data={
                        "source_kind": "official_new_hampshire_constitution_html",
                        "source_authority_class": "official",
                        "discovery_method": "nh_gov_constitution",
                        "article_id": str(part_id),
                        "skip_hydrate": True,
                    },
                )
            )
    return statutes


def configured_constitution_html_path() -> Optional[Path]:
    raw = str(os.environ.get("NEW_HAMPSHIRE_CONSTITUTION_HTML") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None
