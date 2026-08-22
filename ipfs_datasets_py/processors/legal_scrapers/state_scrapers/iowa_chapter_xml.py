"""Official Iowa Code per-chapter slim XML parser.

Adapted from Vaquill-AI/open-us-law ``ia_bulk`` (Apache-2.0).
``legis.iowa.gov`` publishes each chapter as:

    /docs/publications/ICC/{year}/attachments/{chapter}_slim.xml
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import List, Optional
from xml.etree import ElementTree as ET

from .base_scraper import NormalizedStatute, StatuteMetadata

SITE = "https://www.legis.iowa.gov"
_WS = re.compile(r"\s+")
_SKIP_CLASS = {"history", "heading"}


def chapter_xml_url(chapter: str, year: str | int = 2026) -> str:
    return f"{SITE}/docs/publications/ICC/{year}/attachments/{chapter}_slim.xml"


def section_rtf_url(section_number: str, year: str | int = 2026) -> str:
    return f"{SITE}/docs/code/{year}/{section_number}.rtf"


def _local(tag: str) -> str:
    return str(tag or "").rsplit("}", 1)[-1]


def _text_of(el: ET.Element) -> str:
    return _WS.sub(" ", "".join(el.itertext())).strip()


def _identifier_and_headnote(heading_el: ET.Element) -> tuple[Optional[str], str]:
    identifier = None
    headnote = ""
    for child in heading_el:
        if _local(child.tag) != "span":
            continue
        cls = child.get("class")
        if cls == "identifier":
            identifier = _text_of(child)
        elif cls == "headnote":
            headnote = _text_of(child)
    return identifier, headnote


def _collect_body(el: ET.Element, parts: List[str]) -> None:
    cls = el.get("class", "")
    tag = _local(el.tag)
    if tag == "div" and cls in _SKIP_CLASS:
        return
    if tag == "p":
        text = _text_of(el)
        if text:
            parts.append(text)
        return
    for child in el:
        _collect_body(child, parts)


def parse_iowa_chapter_xml(
    xml_bytes: bytes | str,
    *,
    chapter: str,
    year: str | int = 2026,
    title_roman: str = "",
    code_name: str = "Iowa Code",
    max_statutes: Optional[int] = None,
) -> List[NormalizedStatute]:
    raw = xml_bytes.encode("utf-8") if isinstance(xml_bytes, str) else xml_bytes
    if not raw:
        return []
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return []
    statutes: List[NormalizedStatute] = []
    for sec in root.iter():
        if _local(sec.tag) != "Section":
            continue
        if max_statutes is not None and len(statutes) >= int(max_statutes):
            break
        heading = next(
            (child for child in sec if _local(child.tag) == "div" and child.get("class") == "heading"),
            None,
        )
        identifier, headnote = ("", "")
        if heading is not None:
            identifier, headnote = _identifier_and_headnote(heading)
        secnum = (identifier or (sec.get("id") or "").replace("sec", "", 1)).strip()
        if not secnum:
            continue
        low = headnote.lower()
        if "repealed" in low or "reserved" in low:
            continue
        parts: List[str] = []
        for child in sec:
            if child is heading:
                continue
            _collect_body(child, parts)
        body = " ".join(parts).strip()
        if len(body) < 20:
            continue
        statutes.append(
            NormalizedStatute(
                state_code="IA",
                state_name="Iowa",
                statute_id=f"{code_name} § {secnum}",
                code_name=code_name,
                title_number=title_roman or None,
                chapter_number=str(chapter or "") or None,
                section_number=secnum,
                section_name=(headnote or f"Section {secnum}")[:220],
                full_text=body[:14000],
                source_url=section_rtf_url(secnum, year),
                official_cite=f"Iowa Code § {secnum}",
                metadata=StatuteMetadata(),
                structured_data={
                    "source_kind": "official_iowa_chapter_slim_xml",
                    "source_authority_class": "official",
                    "discovery_method": "legis_iowa_icc_slim_xml",
                    "skip_hydrate": True,
                },
            )
        )
    return statutes


def configured_chapter_xml_path() -> Optional[Path]:
    raw = str(os.environ.get("IOWA_CHAPTER_XML") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None
