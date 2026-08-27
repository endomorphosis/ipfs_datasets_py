"""Official Alabama Constitution GraphQL hierarchy parser.

Adapted from Vaquill-AI/open-us-law ``ingest_state_constitutions.scrape_al``
(Apache-2.0). ``constitutionTitles`` is the same ∫/† blob as the Code of
Alabama tree, but Article -> Section with no Chapter. Stop at the first row
that is neither a roman-numeral Article nor a Section under one, so the
Local Provisions county branch is never admitted.

Local dumps: ``ALABAMA_CONSTITUTION_TITLES_TEXT`` and optional
``ALABAMA_CONSTITUTION_ITEMS_JSON``. No live GraphQL from this module.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .alabama_section import parse_alabama_titles_blob
from .base_scraper import NormalizedStatute, StatuteMetadata

ORIGIN = "https://alison.legislature.state.al.us"
_AL_ARTICLE_RE = re.compile(r"^Article\s+([IVXLC]+)\s+(.*)$")
_AL_SECTION_RE = re.compile(r"^Section\s+(\S+)\s+(.*)$")
_RESERVED = re.compile(r"\b(repealed|reserved|expired|renumbered|transferred)\b", re.IGNORECASE)
_WS = re.compile(r"\s+")


def constitution_article_groups(
    pairs: List[Tuple[str, str]],
) -> List[dict]:
    """Group roman-numeral articles; stop at Local Provisions."""

    groups: List[dict] = []
    current: Optional[dict] = None
    for code_id, label in pairs:
        art_match = _AL_ARTICLE_RE.match(label)
        if art_match:
            current = {
                "roman": art_match.group(1),
                "title": art_match.group(2).strip(),
                "sections": [],
            }
            groups.append(current)
            continue
        sec_match = _AL_SECTION_RE.match(label)
        if sec_match and current is not None:
            current["sections"].append(
                (code_id, sec_match.group(1), sec_match.group(2).strip())
            )
            continue
        break
    return groups


def _items_by_code_id(payload) -> Dict[str, dict]:
    out: Dict[str, dict] = {}
    if isinstance(payload, dict) and "data" in payload:
        payload = payload.get("data")
    if isinstance(payload, dict) and "constitutionItems" in payload:
        payload = ((payload.get("constitutionItems") or {}).get("data")) or []
    if isinstance(payload, dict):
        items = payload.values() if all(isinstance(v, dict) for v in payload.values()) else [payload]
    elif isinstance(payload, list):
        items = payload
    else:
        items = []
    for item in items:
        if not isinstance(item, dict):
            continue
        code_id = str(item.get("codeId") or "").strip()
        if code_id:
            out[code_id] = item
    return out


def parse_alabama_constitution(
    titles_blob: str,
    items_payload=None,
    *,
    code_name: str = "Alabama Constitution",
    max_statutes: Optional[int] = None,
) -> List[NormalizedStatute]:
    groups = constitution_article_groups(parse_alabama_titles_blob(titles_blob))
    items = _items_by_code_id(items_payload) if items_payload is not None else {}
    statutes: List[NormalizedStatute] = []
    for group in groups:
        if max_statutes is not None and len(statutes) >= int(max_statutes):
            break
        art_id = group["roman"]
        for code_id, number, catchline in group["sections"]:
            if max_statutes is not None and len(statutes) >= int(max_statutes):
                break
            if _RESERVED.search(catchline):
                continue
            item = items.get(code_id) or {}
            html_content = str(item.get("content") or "")
            history = str(item.get("history") or "").strip()
            body = ""
            if html_content:
                try:
                    from bs4 import BeautifulSoup
                except ImportError:
                    body = _WS.sub(" ", html_content)
                else:
                    body = _WS.sub(
                        " ",
                        BeautifulSoup(html_content, "html.parser").get_text(" ", strip=True),
                    ).strip()
            if history:
                body = f"{body} {history}".strip()
            if not body:
                body = catchline
            if len(body) < 40:
                continue
            if _RESERVED.search(body[:160]):
                continue
            cite = f"Ala. Const. art. {art_id}, § {number}"
            statutes.append(
                NormalizedStatute(
                    state_code="AL",
                    state_name="Alabama",
                    statute_id=cite,
                    code_name=code_name,
                    title_number=art_id,
                    section_number=number,
                    section_name=(catchline or f"Section {number}")[:200],
                    full_text=body,
                    source_url=f"{ORIGIN}/constitution-of-alabama?article={art_id}&section={number}",
                    official_cite=cite,
                    metadata=StatuteMetadata(),
                    structured_data={
                        "source_kind": "official_alabama_constitution_graphql",
                        "source_authority_class": "official",
                        "discovery_method": "alison_constitutionTitles",
                        "article_id": art_id,
                        "code_id": code_id,
                        "skip_hydrate": True,
                    },
                )
            )
    return statutes


def configured_constitution_titles_path() -> Optional[Path]:
    raw = str(os.environ.get("ALABAMA_CONSTITUTION_TITLES_TEXT") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None


def configured_constitution_items_path() -> Optional[Path]:
    raw = str(os.environ.get("ALABAMA_CONSTITUTION_ITEMS_JSON") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None


def parse_configured_alabama_constitution(
    *,
    code_name: str = "Alabama Constitution",
    max_statutes: Optional[int] = None,
) -> List[NormalizedStatute]:
    titles_path = configured_constitution_titles_path()
    if titles_path is None:
        return []
    items_payload = None
    items_path = configured_constitution_items_path()
    if items_path is not None:
        items_payload = json.loads(items_path.read_text(encoding="utf-8"))
    return parse_alabama_constitution(
        titles_path.read_text(encoding="utf-8", errors="replace"),
        items_payload,
        code_name=code_name,
        max_statutes=max_statutes,
    )
