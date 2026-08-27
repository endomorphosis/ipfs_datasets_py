"""Official Alaska LAA AJAX print-fragment parser.

Adapted from Vaquill-AI/open-us-law ``scrapeAK.py`` (Apache-2.0).  The live
fragment is malformed after its first ``div.statute``, so anchored bold section
headings, rather than div boundaries, delimit bodies.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import List, Optional, Tuple

from .base_scraper import NormalizedStatute, StatuteMetadata

BASE = "https://www.akleg.gov/basis/statutes.asp"
_SEC_RE = re.compile(
    r"Sec\.\s*(?P<num>\d{2}\.\d{2}\.\d{3}[A-Za-z]?)\.\s*(?P<head>.*)$",
    re.IGNORECASE,
)
_SEC_ANCHOR_RE = re.compile(r"^\d{2}\.\d{2}\.\d{3}[A-Za-z]?$", re.IGNORECASE)
_REPEALED = re.compile(r"\[\s*Repealed\b", re.IGNORECASE)
_RESERVED = re.compile(r"\b(repealed|reserved|expired|renumbered)\b", re.IGNORECASE)
_WS = re.compile(r"\s+")


def print_url(section_number: str) -> str:
    return f"{BASE}?media=print&secStart={section_number}&secEnd={section_number}"


def toc_url(title_or_chapter: str) -> str:
    token = str(title_or_chapter or "").strip()
    if token.isdigit():
        token = f"{int(token):02d}"
    return f"{BASE}?media=js&type=TOC&title={token}"


def xref_url(section_number: str) -> str:
    return f"{BASE}?type=xRef&sec={section_number}"


def chapter_toc_links(html: str) -> List[Tuple[str, str]]:
    """Title TOC fragments: ``loadTOC(\"01.05\")`` chapter rows."""

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    soup = BeautifulSoup(html or "", "html.parser")
    out: List[Tuple[str, str]] = []
    seen: set[str] = set()
    for link in soup.find_all("a", onclick=True):
        match = re.search(r'loadTOC\("(\d{2}\.\d{2})"\)', str(link.get("onclick") or ""))
        if not match:
            continue
        number = match.group(1)
        if number in seen:
            continue
        seen.add(number)
        out.append((number, _clean(link.get_text(" ")) or f"Chapter {number}"))
    return out


def section_toc_links(html: str) -> List[Tuple[str, str]]:
    """Chapter TOC fragments: ``#01.05.006`` section anchors."""

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    soup = BeautifulSoup(html or "", "html.parser")
    out: List[Tuple[str, str]] = []
    seen: set[str] = set()
    for link in soup.find_all("a", href=True):
        match = re.search(r"#(\d{2}\.\d{2}\.\d{3}[A-Za-z]?)$", str(link.get("href") or ""))
        if not match:
            continue
        number = match.group(1)
        if number in seen:
            continue
        seen.add(number)
        out.append((number, _clean(link.get_text(" ")) or f"Sec. {number}"))
    return out


def _clean(text: str) -> str:
    return _WS.sub(" ", (text or "").replace("\xa0", " ")).strip()


def parse_alaska_statute_html(
    html: str,
    *,
    code_name: str = "Alaska Statutes",
    max_statutes: Optional[int] = None,
) -> List[NormalizedStatute]:
    """Split every section heading in an Alaska BASIS print fragment.

    The live ``type=fetch`` endpoint emits deliberately loose HTML.  A response
    commonly starts one ``div.statute`` and then closes it after the first
    section even though another 60-80 anchored ``<b>Sec. ...`` headings follow.
    Iterating only ``div.statute`` therefore admitted about one row per
    response.  Walk the whole parsed document in order and use the anchored
    bold headings as section boundaries instead.

    A heading without an anchor is also accepted for local fixture/export
    compatibility, but an anchored heading always supplies the canonical
    section identity.  Bodies are retained in full; durable normalization and
    chunking, rather than this acquisition adapter, own any later size policy.
    """

    try:
        from bs4 import BeautifulSoup, NavigableString, Tag
    except ImportError:
        return []
    soup = BeautifulSoup(html or "", "html.parser")

    def _heading_identity(node: Tag) -> Optional[Tuple[str, str]]:
        if str(getattr(node, "name", "") or "").lower() != "b":
            return None
        heading = _clean(node.get_text(" "))
        match = _SEC_RE.search(heading)
        anchor = node.find("a", attrs={"name": True})
        anchored_number = str(anchor.get("name") or "").strip() if anchor else ""
        if anchored_number and not _SEC_ANCHOR_RE.fullmatch(anchored_number):
            anchored_number = ""
        if not match and not anchored_number:
            return None
        number = anchored_number or (match.group("num") if match else "")
        if not number:
            return None
        if match and match.group("num").lower() != number.lower():
            return None
        return number, heading

    headings: dict[int, Tuple[str, str]] = {}
    for bold in soup.find_all("b"):
        identity = _heading_identity(bold)
        if identity is not None:
            headings[id(bold)] = identity
    if not headings:
        return []

    raw_sections: List[Tuple[str, str, str]] = []
    current: Optional[Tuple[str, str, Tag]] = None
    body_parts: List[str] = []

    def _finish_current() -> None:
        nonlocal body_parts, current
        if current is None:
            return
        number, heading, _node = current
        raw_sections.append((number, heading, _clean(" ".join(body_parts))))
        body_parts = []

    for node in soup.descendants:
        if isinstance(node, Tag) and id(node) in headings:
            _finish_current()
            number, heading = headings[id(node)]
            current = (number, heading, node)
            continue
        if current is None:
            continue
        if isinstance(node, Tag):
            if str(node.name or "").lower() == "br":
                body_parts.append("\n")
            continue
        if not isinstance(node, NavigableString):
            continue
        current_heading = current[2]
        containing_bold = node.find_parent("b")
        if containing_bold is current_heading:
            continue
        # Chapter/article labels sometimes appear between a section heading and
        # its body in the malformed fragment.  They are hierarchy, not text of
        # the section whose heading preceded them.
        if containing_bold is not None and containing_bold.find(["h6", "h7"]):
            continue
        body_parts.append(str(node))
    _finish_current()

    statutes: List[NormalizedStatute] = []
    seen_numbers: set[str] = set()
    for number, heading, body in raw_sections:
        if max_statutes is not None and len(statutes) >= int(max_statutes):
            break
        if number in seen_numbers:
            continue
        seen_numbers.add(number)
        match = _SEC_RE.search(heading)
        name = match.group("head").strip() if match else heading[:200]
        if _REPEALED.search(heading) or _RESERVED.search(heading):
            continue
        if len(body) < 40:
            continue
        parts = number.split(".")
        statutes.append(
            NormalizedStatute(
                state_code="AK",
                state_name="Alaska",
                statute_id=f"{code_name} § {number}",
                code_name=code_name,
                title_number=parts[0] if parts else None,
                chapter_number=parts[1] if len(parts) > 1 else None,
                section_number=number,
                section_name=(name or f"Section {number}")[:200],
                full_text=body,
                source_url=f"{BASE}#{number}",
                official_cite=f"Alaska Stat. § {number}",
                metadata=StatuteMetadata(),
                structured_data={
                    "source_kind": "official_alaska_statutes_ajax_html",
                    "source_authority_class": "official",
                    "discovery_method": "official_fetch_endpoint",
                    "skip_hydrate": True,
                },
            )
        )
    return statutes


def configured_section_html_path() -> Optional[Path]:
    raw = str(os.environ.get("ALASKA_SECTION_HTML") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None


def configured_toc_html_path() -> Optional[Path]:
    raw = str(os.environ.get("ALASKA_TOC_HTML") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None


def parse_configured_toc_html() -> List[Tuple[str, str]]:
    path = configured_toc_html_path()
    if path is None:
        return []
    return chapter_toc_links(path.read_text(encoding="utf-8", errors="replace"))


def configured_section_toc_html_path() -> Optional[Path]:
    raw = str(os.environ.get("ALASKA_SECTION_TOC_HTML") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None


def parse_configured_section_toc_html() -> List[Tuple[str, str]]:
    path = configured_section_toc_html_path()
    if path is None:
        return []
    return section_toc_links(path.read_text(encoding="utf-8", errors="replace"))
