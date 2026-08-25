"""Official New York Constitution OpenLeg CNS parser.

Adapted from Vaquill-AI/open-us-law ``ingest_state_constitutions.scrape_ny``
(Apache-2.0). OpenLeg law id ``CNS`` is the constitution tree. Literal
two-character ``\\n`` markers in stored text are turned into spaces.
Preamble leaves with no ARTICLE ancestor are article/section ``0``.

Local dump: ``NEW_YORK_CONSTITUTION_JSON``.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import List, Optional

from .base_scraper import NormalizedStatute, StatuteMetadata
from .new_york_openleg import iter_sections

NY_CONST_LAW_URL = "https://www.nysenate.gov/legislation/laws/CNS"
_RESERVED = re.compile(r"\b(repealed|reserved|expired|renumbered)\b", re.IGNORECASE)
_WS = re.compile(r"\s+")


def parse_new_york_constitution_tree(
    result: dict,
    *,
    code_name: str = "New York Constitution",
    max_statutes: Optional[int] = None,
) -> List[NormalizedStatute]:
    if "result" in result and isinstance(result.get("result"), dict):
        result = result["result"]
    statutes: List[NormalizedStatute] = []
    for leaf in iter_sections(result):
        if max_statutes is not None and len(statutes) >= int(max_statutes):
            break
        text = _WS.sub(" ", (leaf.get("text") or "").replace("\\n", " ")).strip()
        if len(text) < 40:
            continue
        if _RESERVED.search((leaf.get("title") or "")[:160]) or _RESERVED.search(text[:160]):
            continue
        art_id = next((lvl for cls, lvl in leaf.get("ancestors") or () if cls == "article"), None)
        if art_id is None:
            art_id, number = "0", "0"
            cite = "N.Y. Const. Preamble"
        else:
            number = str(leaf.get("doc_level_id") or leaf.get("location_id") or "1")
            cite = f"N.Y. Const. art. {art_id}, § {number}"
        statutes.append(
            NormalizedStatute(
                state_code="NY",
                state_name="New York",
                statute_id=cite,
                code_name=code_name,
                title_number=art_id,
                section_number=number,
                section_name=(leaf.get("title") or cite)[:200],
                full_text=text[:14000],
                source_url=NY_CONST_LAW_URL,
                official_cite=cite,
                metadata=StatuteMetadata(),
                structured_data={
                    "source_kind": "official_new_york_constitution_json",
                    "source_authority_class": "official",
                    "discovery_method": "nysenate_openleg_cns",
                    "article_id": art_id,
                    "skip_hydrate": True,
                },
            )
        )
    return statutes


def configured_constitution_json_path() -> Optional[Path]:
    raw = str(os.environ.get("NEW_YORK_CONSTITUTION_JSON") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None


def parse_configured_new_york_constitution(
    *,
    code_name: str = "New York Constitution",
    max_statutes: Optional[int] = None,
) -> List[NormalizedStatute]:
    path = configured_constitution_json_path()
    if path is None:
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    return parse_new_york_constitution_tree(payload, code_name=code_name, max_statutes=max_statutes)
