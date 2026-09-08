"""Official NY Senate Open Legislation law-tree parser.

Adapted from Vaquill-AI/open-us-law ``ny_bulk.walk`` (Apache-2.0).
Local dump: ``NY_OPENLEG_LAW_JSON``. Live API still needs OPENLEG_API_KEY.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Tuple

from .base_scraper import (
    NormalizedStatute,
    StatuteMetadata,
    current_state_law_run_environment_value,
)

_LAW_HREF_RE = re.compile(r"/legislation/laws/([A-Z][A-Z0-9]{1,5})(?:/|\?|#|$)")
_SKIP_LAW_SLUGS = {
    "CONSOLIDATED",
    "UNCONSOLIDATED",
    "COURT",
    "ACTS",
    "RULES",
    "MISC",
    # The constitution and administrative regulations are separately scoped
    # corpora.  They must never become full-law PDF members merely because a
    # navigation link appears beside the consolidated statutory catalog.
    "CNS",
    "NYCRR",
}
SENATE_BASE = "https://www.nysenate.gov"
OPENLEG_API_BASE = "https://legislation.nysenate.gov/api/3"
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
        # Leaf SECTION/RULE nodes, plus single-blob unconsolidated acts
        # (Vaquill LEH/NNY: a CHAPTER with statutory text and no children).
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
                full_text=sec["text"],
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
    raw = current_state_law_run_environment_value("NY_OPENLEG_LAW_JSON").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None


def configured_category_html_path() -> Optional[Path]:
    raw = current_state_law_run_environment_value("NY_CATEGORY_HTML").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None


def parse_configured_category_html() -> List[Tuple[str, str, str]]:
    path = configured_category_html_path()
    if path is None:
        return []
    return category_law_links(path.read_text(encoding="utf-8", errors="replace"))


def openleg_law_json_url(law_id: str) -> str:
    """Unkeyed official Open Legislation law-tree URL.

    Live GETs may attach ``OPENLEG_API_KEY`` as a request query; receipts and
    Common Crawl / Wayback locators must keep this identity without a key.
    """

    code = str(law_id or "").strip().upper()
    if not re.fullmatch(r"[A-Z][A-Z0-9]{1,5}", code):
        return ""
    return f"{OPENLEG_API_BASE}/laws/{code}?full=true"


def is_valid_openleg_law_json(payload: bytes) -> bool:
    """Admit a successful OpenLeg law tree; reject 401/error shells."""

    raw = bytes(payload or b"")
    if len(raw) < 32 or raw[:1] not in {b"{", b"["}:
        return False
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        return False
    if not isinstance(data, dict) or data.get("success") is False:
        return False
    result = data.get("result") if isinstance(data.get("result"), dict) else data
    documents = result.get("documents") if isinstance(result, dict) else None
    return isinstance(documents, dict) and bool(documents)


def section_from_openleg_law_json(
    payload: bytes,
    *,
    law_code: str,
    section: str,
) -> Optional[Dict[str, str]]:
    """Return the matching leaf from a retained OpenLeg law tree."""

    if not is_valid_openleg_law_json(payload):
        return None
    data = json.loads(bytes(payload).decode("utf-8"))
    result = data.get("result") if isinstance(data.get("result"), dict) else data
    wanted = re.sub(
        r"[A-Za-z]+",
        lambda match: match.group(0).upper(),
        str(section or "").strip(),
    )
    wanted_fold = wanted.replace("–", "-").replace("—", "-").casefold()
    expected_law = str(law_code or "").strip().upper()
    for row in iter_sections(result if isinstance(result, dict) else {}):
        if expected_law and str(row.get("law_id") or "").strip().upper() != expected_law:
            continue
        for token in (row.get("location_id"), row.get("doc_level_id")):
            candidate = re.sub(
                r"[A-Za-z]+",
                lambda match: match.group(0).upper(),
                str(token or "").strip(),
            )
            if candidate.replace("–", "-").replace("—", "-").casefold() == wanted_fold:
                return {
                    "law_id": str(row.get("law_id") or ""),
                    "location_id": str(row.get("location_id") or ""),
                    "doc_level_id": str(row.get("doc_level_id") or ""),
                    "title": str(row.get("title") or ""),
                    "text": str(row.get("text") or ""),
                }
    return None


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
