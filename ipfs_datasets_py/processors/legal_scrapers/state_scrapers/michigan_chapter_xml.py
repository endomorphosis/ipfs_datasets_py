"""Official Michigan Compiled Laws chapter XML parser.

Adapted from Vaquill-AI/open-us-law ``mi_bulk.parse`` (Apache-2.0).
``legislature.mi.gov/documents/mcl/Chapter%20{N}.xml`` is UTF-16 with escaped
inner BodyText markup. Local path: ``MICHIGAN_CHAPTER_XML``.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import List, Optional, Tuple
from xml.etree import ElementTree as ET

from .base_scraper import NormalizedStatute, StatuteMetadata

BASE = "https://www.legislature.mi.gov"
_WS = re.compile(r"\s+")


def act_slug(name: str) -> str:
    return re.sub(r"[^0-9A-Za-z-]+", "-", (name or "").strip()).lstrip("-")


def chapter_xml_url(chapter_name: str) -> str:
    return f"{BASE}/documents/mcl/Chapter%20{chapter_name}.xml"


def section_url(section_number: str) -> str:
    return f"{BASE}/Laws/MCL?objectName=mcl-{section_number.replace('.', '-')}"


def _clean(raw: str) -> str:
    text = (raw or "").replace("\xa0", " ").replace("—", "-").replace("–", "-")
    return _WS.sub(" ", text).strip()


def _markup_to_paragraphs(markup: str) -> List[str]:
    if not markup or not str(markup).strip():
        return []
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return [_clean(markup)] if _clean(markup) else []
    soup = BeautifulSoup(markup, "html.parser")
    paras = [_clean(el.get_text(" ")) for el in soup.find_all(["section-number", "p"])]
    paras = [item for item in paras if item]
    if not paras:
        whole = _clean(soup.get_text(" "))
        if whole:
            paras.append(whole)
    return paras


def parse_michigan_chapter_xml(
    xml_text: str | bytes,
    *,
    chapter_hint: str = "",
    code_name: str = "Michigan Compiled Laws",
    max_statutes: Optional[int] = None,
) -> List[NormalizedStatute]:
    if isinstance(xml_text, bytes):
        if xml_text[:2] in (b"\xff\xfe", b"\xfe\xff"):
            xml_text = xml_text.decode("utf-16")
        else:
            xml_text = xml_text.decode("utf-8-sig", errors="replace")
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []
    chapter_name = _clean(root.findtext("Name") or "") or str(chapter_hint)
    statutes: List[NormalizedStatute] = []

    def recurse(node: ET.Element, cur_act: Optional[str]) -> None:
        if max_statutes is not None and len(statutes) >= int(max_statutes):
            return
        for child in node:
            tag = child.tag
            if tag == "MCLStatuteInfo":
                recurse(child, act_slug(child.findtext("Name") or ""))
            elif tag in ("MCLDivisionInfo", "MCLDocumentInfoCollection"):
                recurse(child, cur_act)
            elif tag == "MCLSectionInfo":
                if cur_act is None:
                    continue
                if (child.findtext("Repealed") or "").strip().lower() == "true":
                    continue
                number = _clean(child.findtext("MCLNumber") or "")
                catchline = _clean(child.findtext("CatchLine") or "")
                if "repealed" in catchline.lower() or "reserved" in catchline.lower():
                    continue
                paras = _markup_to_paragraphs(child.findtext("BodyText") or "")
                body = " ".join(paras).strip()
                if not number or len(body) < 20:
                    continue
                statutes.append(
                    NormalizedStatute(
                        state_code="MI",
                        state_name="Michigan",
                        statute_id=f"{code_name} § {number}",
                        code_name=code_name,
                        chapter_number=chapter_name or None,
                        section_number=number,
                        section_name=(catchline or f"Section {number}")[:200],
                        full_text=body[:14000],
                        source_url=section_url(number),
                        official_cite=f"Mich. Comp. Laws § {number}",
                        metadata=StatuteMetadata(),
                        structured_data={
                            "source_kind": "official_michigan_mcl_xml",
                            "source_authority_class": "official",
                            "discovery_method": "legislature_mi_mcl_chapter_xml",
                            "act_slug": cur_act,
                            "skip_hydrate": True,
                        },
                    )
                )
                if max_statutes is not None and len(statutes) >= int(max_statutes):
                    return

    recurse(root, None)
    return statutes


def configured_chapter_xml_path() -> Optional[Path]:
    raw = str(os.environ.get("MICHIGAN_CHAPTER_XML") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None


def _absolute(href: str, *, base_url: str = BASE) -> str:
    token = str(href or "").strip()
    if token.startswith("http"):
        return token
    if token.startswith("/"):
        return f"{base_url}{token}"
    return f"{base_url}/{token}"


def chapter_index_links(html: str, *, base_url: str = BASE) -> List[Tuple[str, str, str]]:
    """``/Home/GetObject?objectName=mcl-chapN`` rows from ChapterIndex."""

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    soup = BeautifulSoup(html or "", "html.parser")
    main = soup.find(id="main") or soup
    out: List[Tuple[str, str, str]] = []
    seen: set[str] = set()
    for anchor in main.find_all("a", href=True):
        href = str(anchor.get("href") or "")
        match = re.search(r"objectName=mcl-chap(\d+)\b", href, re.IGNORECASE)
        if not match:
            continue
        number = match.group(1).strip()
        if not number or number in seen:
            continue
        seen.add(number)
        name = _clean(anchor.get_text(" ")) or f"Chapter {number}"
        out.append((number, name, _absolute(href, base_url=base_url)))
    return out


def act_links(html: str, *, base_url: str = BASE) -> List[Tuple[str, str, str]]:
    """Chapter-page ``objectName=mcl-Act-NNN-of-YYYY`` rows."""

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    soup = BeautifulSoup(html or "", "html.parser")
    main = soup.find(id="main") or soup
    out: List[Tuple[str, str, str]] = []
    seen: set[str] = set()
    for row in main.find_all("tr"):
        anchor = row.find("a", href=True)
        if anchor is None:
            continue
        href = str(anchor.get("href") or "")
        match = re.search(r"objectName=(mcl-(?!chap)\S+)", href, re.IGNORECASE)
        if not match:
            continue
        slug = re.sub(r"^mcl-", "", match.group(1), flags=re.IGNORECASE)
        if not slug or slug in seen:
            continue
        if re.match(r"^\d+-", slug):
            continue
        seen.add(slug)
        name = _clean(anchor.get_text(" ")) or slug
        out.append((slug, name, _absolute(href, base_url=base_url)))
    return out


def section_object_links(html: str, *, base_url: str = BASE) -> List[Tuple[str, str, str]]:
    """Act-page ``objectName=mcl-2-1`` rows -> ``2.1``."""

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    soup = BeautifulSoup(html or "", "html.parser")
    main = soup.find(id="main") or soup
    out: List[Tuple[str, str, str]] = []
    seen: set[str] = set()
    for row in main.find_all("tr"):
        anchor = row.find("a", href=True)
        if anchor is None:
            continue
        href = str(anchor.get("href") or "")
        match = re.search(r"objectName=mcl-([\d]+)-([\w\.]+)$", href, re.IGNORECASE)
        if not match:
            continue
        number = f"{match.group(1)}.{match.group(2)}"
        if number in seen:
            continue
        seen.add(number)
        cells = row.find_all("td")
        name = _clean(cells[2].get_text(" ")) if len(cells) > 2 else _clean(anchor.get_text(" "))
        out.append((number, name or f"§ {number}", _absolute(href, base_url=base_url)))
    return out
