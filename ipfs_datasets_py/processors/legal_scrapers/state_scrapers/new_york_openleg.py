"""Official NY Senate Open Legislation law-tree parser.

Adapted from Vaquill-AI/open-us-law ``ny_bulk.walk`` (Apache-2.0).
Local dump: ``NY_OPENLEG_LAW_JSON``. Live API still needs OPENLEG_API_KEY.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Tuple

from .base_scraper import NormalizedStatute, StatuteMetadata

_LAW_HREF_RE = re.compile(r"/legislation/laws/([A-Z][A-Z0-9]{1,5})(?:/|\?|#|$)")
_SKIP_LAW_SLUGS = {"CONSOLIDATED", "UNCONSOLIDATED", "COURT", "ACTS", "RULES", "MISC"}
SENATE_BASE = "https://www.nysenate.gov"
_LEAF_TYPES = {"SECTION", "RULE"}
_CLS = {
    "ARTICLE": "article",
    "TITLE": "title",
    "SUBTITLE": "subtitle",
    "PART": "part",
    "SUBPART": "subpart",
}


def iter_sections(result: Dict) -> Iterator[Dict]:
    info = result.get("info") or {}
    law_id = info.get("lawId") or (result.get("documents") or {}).get("lawId") or ""
    law_name = info.get("name") or ""
    root = result.get("documents")
    if not root:
        return

    def _walk(node: Dict, anc: Tuple) -> Iterator[Dict]:
        doc_type = node.get("docType") or ""
        if node.get("repealed"):
            return
        items = (node.get("documents") or {}).get("items") or []
        if doc_type in _LEAF_TYPES or not items:
            text = (node.get("text") or "").strip()
            if text and (doc_type in _LEAF_TYPES or not items):
                yield {
                    "law_id": law_id,
                    "law_name": law_name,
                    "location_id": node.get("locationId") or node.get("docLevelId") or "",
                    "doc_level_id": node.get("docLevelId") or node.get("locationId") or "",
                    "title": (node.get("title") or "").strip(),
                    "text": text,
                    "ancestors": anc,
                }
            return
        cls = _CLS.get(doc_type)
        child_anc = anc + ((cls, node.get("docLevelId") or ""),) if cls else anc
        for child in items:
            yield from _walk(child, child_anc)

    yield from _walk(root, ())


def parse_new_york_law_tree(
    result: Dict,
    *,
    code_name: str = "New York Consolidated Laws",
    max_statutes: Optional[int] = None,
) -> List[NormalizedStatute]:
    statutes: List[NormalizedStatute] = []
    for sec in iter_sections(result):
        if max_statutes is not None and len(statutes) >= int(max_statutes):
            break
        number = sec["doc_level_id"] or sec["location_id"]
        if not number or len(sec["text"]) < 20:
            continue
        law_id = sec["law_id"] or "NY"
        statutes.append(
            NormalizedStatute(
                state_code="NY",
                state_name="New York",
                statute_id=f"{code_name} § {law_id} {number}",
                code_name=code_name,
                title_number=law_id,
                title_name=sec["law_name"] or None,
                section_number=number,
                section_name=(sec["title"] or f"Section {number}")[:200],
                full_text=sec["text"][:14000],
                source_url=f"https://www.nysenate.gov/legislation/laws/{law_id}/{sec['location_id'] or number}",
                official_cite=f"N.Y. {law_id} Law § {number}",
                metadata=StatuteMetadata(),
                structured_data={
                    "source_kind": "official_new_york_openleg_json",
                    "source_authority_class": "official",
                    "discovery_method": "nysenate_open_legislation_laws_api",
                    "skip_hydrate": True,
                },
            )
        )
    return statutes


def category_law_links(
    html: str, *, base_url: str = SENATE_BASE
) -> List[Tuple[str, str, str]]:
    """Law slugs from a Senate category index (``/legislation/laws/PEN``)."""

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    from urllib.parse import urljoin

    soup = BeautifulSoup(html or "", "html.parser")
    out: List[Tuple[str, str, str]] = []
    seen: set[str] = set()
    for anchor in soup.find_all("a", href=True):
        href = str(anchor.get("href") or "")
        match = _LAW_HREF_RE.search(href)
        if not match:
            continue
        abbr = match.group(1)
        if abbr in _SKIP_LAW_SLUGS or abbr in seen:
            continue
        seen.add(abbr)
        name = re.sub(r"\s+", " ", (anchor.get_text(" ") or "").replace("\xa0", " ")).strip() or abbr
        out.append((abbr, name, urljoin(base_url.rstrip("/") + "/", href)))
    return out


def configured_law_json_path() -> Optional[Path]:
    raw = str(os.environ.get("NY_OPENLEG_LAW_JSON") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None


def parse_configured_law_json(
    *,
    code_name: str = "New York Consolidated Laws",
    max_statutes: Optional[int] = None,
) -> List[NormalizedStatute]:
    path = configured_law_json_path()
    if path is None:
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    if "result" in payload and isinstance(payload["result"], dict):
        payload = payload["result"]
    return parse_new_york_law_tree(payload, code_name=code_name, max_statutes=max_statutes)
