"""Official D.C. Code Open Law Library XML parser.

Adapted from Vaquill-AI/open-us-law ``ingest_dc_code.py`` (Apache-2.0).
DC Council publishes codified XML at
``https://github.com/DCCouncil/law-xml-codified`` (``us/dc/council/code``).
Local path: ``DC_CODE_SECTION_XML`` or ``DC_CODE_XML_DIR``.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import List, Optional
from xml.etree import ElementTree as ET

from .base_scraper import NormalizedStatute, StatuteMetadata

_CONTAINER_TAGS = {"para", "container"}
_LEAF_TEXT_TAGS = {"text", "aftertext"}


def _strip_ns(tag: str) -> str:
    return tag.split("}", 1)[-1] if "}" in tag else tag


def _inline_text(elem: ET.Element) -> str:
    parts: List[str] = []
    if elem.text:
        parts.append(elem.text)
    for child in elem:
        parts.append(_inline_text(child))
        if child.tail:
            parts.append(child.tail)
    return " ".join(item.strip() for item in parts if item and item.strip())


def _render_node(elem: ET.Element, depth: int) -> List[str]:
    tag = _strip_ns(elem.tag)
    indent = "  " * depth
    if tag in _LEAF_TEXT_TAGS:
        text = _inline_text(elem).strip()
        return [f"{indent}{text}"] if text else []
    if tag == "table":
        lines: List[str] = []
        for row in elem.iter():
            if _strip_ns(row.tag) != "tr":
                continue
            cells = [_inline_text(td).strip() for td in row if _strip_ns(td.tag) == "td"]
            cells = [cell for cell in cells if cell]
            if cells:
                lines.append(f"{indent}| " + " | ".join(cells) + " |")
        return lines
    if tag in _CONTAINER_TAGS:
        num_text = heading_text = ""
        children: List[ET.Element] = []
        for child in elem:
            ctag = _strip_ns(child.tag)
            if ctag == "num":
                num_text = _inline_text(child).strip()
            elif ctag == "heading":
                heading_text = _inline_text(child).strip()
            elif ctag in _LEAF_TEXT_TAGS or ctag in _CONTAINER_TAGS or ctag == "table":
                children.append(child)
        prefix = " ".join(bit for bit in (num_text, heading_text) if bit)
        lines: List[str] = []
        rendered = False
        for child in children:
            ctag = _strip_ns(child.tag)
            child_lines = _render_node(child, depth + (1 if ctag in _CONTAINER_TAGS else 0))
            if not child_lines:
                continue
            if not rendered and prefix:
                child_lines[0] = f"{indent}{prefix} {child_lines[0].lstrip()}"
                rendered = True
            lines.extend(child_lines)
        if not rendered and prefix:
            lines.append(f"{indent}{prefix}")
        return lines
    return []


def parse_dc_section_xml(
    xml_bytes: bytes | str,
    *,
    code_name: str = "District of Columbia Code",
    title_number: str = "",
    chapter_number: str = "",
) -> Optional[NormalizedStatute]:
    raw = xml_bytes.encode("utf-8") if isinstance(xml_bytes, str) else xml_bytes
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return None
    if _strip_ns(root.tag) != "section":
        return None
    num = heading = ""
    is_omitted = False
    for child in root:
        tag = _strip_ns(child.tag)
        if tag == "num":
            num = (child.text or "").strip()
        elif tag == "heading":
            heading = _inline_text(child).strip()
        elif tag == "reason":
            is_omitted = True
    if not num:
        return None
    lines: List[str] = []
    for child in root:
        ctag = _strip_ns(child.tag)
        if ctag in _LEAF_TEXT_TAGS or ctag in _CONTAINER_TAGS or ctag == "table":
            lines.extend(_render_node(child, 0))
    body = "\n".join(lines).strip()
    if not body:
        if is_omitted:
            body = f"[Omitted] {heading}".strip()
        else:
            return None
    return NormalizedStatute(
        state_code="DC",
        state_name="District of Columbia",
        statute_id=f"{code_name} § {num}",
        code_name=code_name,
        title_number=title_number or None,
        chapter_number=chapter_number or None,
        section_number=num,
        section_name=(heading or f"Section {num}")[:200],
        full_text=body[:14000],
        source_url=f"https://code.dccouncil.gov/us/dc/council/code/sections/{num}",
        official_cite=f"D.C. Code § {num}",
        metadata=StatuteMetadata(),
        structured_data={
            "source_kind": "official_dc_council_law_xml",
            "source_authority_class": "official",
            "discovery_method": "dccouncil_law_xml_codified",
            "skip_hydrate": True,
        },
    )


def parse_dc_xml_dir(
    root: Path,
    *,
    code_name: str = "District of Columbia Code",
    max_statutes: Optional[int] = None,
) -> List[NormalizedStatute]:
    path = Path(root)
    files = sorted(path.rglob("*.xml")) if path.is_dir() else []
    statutes: List[NormalizedStatute] = []
    for file_path in files:
        if file_path.name.lower() == "index.xml":
            continue
        if max_statutes is not None and len(statutes) >= int(max_statutes):
            break
        title_number = ""
        match = re.search(r"/titles/([^/]+)/", str(file_path).replace("\\", "/"))
        if match:
            title_number = match.group(1)
        row = parse_dc_section_xml(
            file_path.read_bytes(),
            code_name=code_name,
            title_number=title_number,
        )
        if row is not None:
            statutes.append(row)
    return statutes


def configured_section_xml_path() -> Optional[Path]:
    raw = str(os.environ.get("DC_CODE_SECTION_XML") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None


def configured_xml_dir() -> Optional[Path]:
    raw = str(os.environ.get("DC_CODE_XML_DIR") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_dir() else None
