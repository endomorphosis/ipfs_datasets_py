"""Official Louisiana legis.la.gov Law.aspx parser.

Adapted from Vaquill-AI/open-us-law ``la_bulk.parse`` (Apache-2.0).
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import List, Optional, Tuple

from .base_scraper import NormalizedStatute, StatuteMetadata

_WS = re.compile(r"[\s\xa0]+")
_LABEL_RE = re.compile(r"^(RS|CCRP|CCP|CHC|CE|CC)\s+(.+?)\s*$")
_HEADING_RE = re.compile(r"^(?:§|Art\.)\s*[0-9][0-9A-Za-z.\-]*\.?\s*(?P<title>.*)$")
_DOCID_RE = re.compile(r"Law\.aspx\?d=(\d+)")
_HEADER_RE = re.compile(
    r'id="ctl00_ctl00_PageBody_PageContent_LabelHeader"[^>]*>([^<]{0,80})'
)
HEADER_TO_PREFIX = {
    "Revised Statutes": "RS",
    "Code of Civil Procedure": "CCP",
    "Code of Criminal Procedure": "CCRP",
    "Children's Code": "CHC",
    "Code of Evidence": "CE",
    "Civil Code": "CC",
}


def parse_label(label: str) -> Optional[Tuple[str, str, str]]:
    match = _LABEL_RE.match((label or "").strip())
    if not match:
        return None
    body, rest = match.group(1), match.group(2).strip()
    if body == "RS":
        if ":" not in rest:
            return None
        title, _, number = rest.partition(":")
        title, number = title.strip(), number.strip()
        if not title or not number:
            return None
        return body, title, number
    if not re.match(r"^[0-9]", rest):
        return None
    return body, "", rest


def document_blocks(html: str) -> List[str]:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    soup = BeautifulSoup(html or "", "html.parser")
    doc = soup.find(id="ctl00_PageBody_LabelDocument")
    if doc is None:
        return []
    blocks = doc.find_all(["p", "li", "blockquote"])
    out: List[str] = []
    if blocks:
        for block in blocks:
            text = _WS.sub(" ", block.get_text(" ")).strip()
            if text:
                out.append(text)
    else:
        text = _WS.sub(" ", doc.get_text(" ")).strip()
        if text:
            out.append(text)
    return out


def heading_and_body(blocks: List[str]) -> Tuple[str, List[str]]:
    for index, block in enumerate(blocks):
        match = _HEADING_RE.match(block)
        if match:
            return match.group("title").strip(), [item for item in blocks[index + 1 :] if item]
    return "", [item for item in blocks if item]


def folder_header(html: str) -> str:
    """LabelHeader of a TOC folder page (statute body name)."""

    match = _HEADER_RE.search(html or "")
    return match.group(1).strip() if match else ""


def folder_body_prefix(html: str) -> Optional[str]:
    header = folder_header(html)
    return HEADER_TO_PREFIX.get(header)


def toc_docids(html: str) -> List[str]:
    seen = set()
    out: List[str] = []
    for match in _DOCID_RE.finditer(html or ""):
        token = match.group(1)
        if token in seen:
            continue
        seen.add(token)
        out.append(token)
    return out


def statute_from_law_html(
    html: str,
    *,
    source_url: str,
    code_name: str = "Louisiana Revised Statutes",
) -> Optional[NormalizedStatute]:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return None
    soup = BeautifulSoup(html or "", "html.parser")
    label_el = soup.find(id="ctl00_PageBody_LabelName")
    label = label_el.get_text(" ", strip=True) if label_el else ""
    parsed = parse_label(label)
    if parsed is None:
        return None
    body, title, number = parsed
    heading, paras = heading_and_body(document_blocks(html))
    text = " ".join(paras).strip()
    if len(text) < 20:
        return None
    cite = f"{body} {title}:{number}" if title else f"{body} {number}"
    return NormalizedStatute(
        state_code="LA",
        state_name="Louisiana",
        statute_id=f"{code_name} § {cite}",
        code_name=code_name,
        title_number=title or None,
        section_number=number,
        section_name=(heading or f"Section {number}")[:200],
        full_text=text[:14000],
        source_url=source_url,
        official_cite=f"La. {cite}",
        metadata=StatuteMetadata(),
        structured_data={
            "source_kind": "official_louisiana_law_aspx",
            "source_authority_class": "official",
            "discovery_method": "legis_la_labeldocument",
            "body_prefix": body,
            "skip_hydrate": True,
        },
    )


def configured_law_html_path() -> Optional[Path]:
    raw = str(os.environ.get("LOUISIANA_LAW_HTML") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None


def configured_toc_html_path() -> Optional[Path]:
    raw = str(os.environ.get("LOUISIANA_TOC_HTML") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None


def parse_configured_toc_html() -> List[str]:
    path = configured_toc_html_path()
    if path is None:
        return []
    return toc_docids(path.read_text(encoding="utf-8", errors="replace"))


def parse_configured_louisiana_law(
    *,
    code_name: str = "Louisiana Revised Statutes",
    max_statutes: Optional[int] = None,
) -> List[NormalizedStatute]:
    path = configured_law_html_path()
    if path is None:
        return []
    row = statute_from_law_html(
        path.read_text(encoding="utf-8", errors="replace"),
        source_url="https://legis.la.gov/Legis/Law.aspx?d=0",
        code_name=code_name,
    )
    if row is None:
        return []
    return [row] if max_statutes is None or int(max_statutes) >= 1 else []
