"""Official Utah Code per-title XML parser.

Adapted from Vaquill-AI/open-us-law ``ingest_ut_statutes.py`` (Apache-2.0).
``le.utah.gov`` publishes each title as ``/xcode/Title{{N}}/{{version}}.xml``.
Amendment ``<histories>`` blocks are dropped from the body.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Dict, Iterable, List, Optional
from xml.etree import ElementTree as ET

from .base_scraper import NormalizedStatute, StatuteMetadata

UT_BASE = "https://le.utah.gov"

_TITLE_VERSION_RE = re.compile(
    r"/xcode/Title([0-9A-Za-z]+)/[0-9A-Za-z]+\.html\?v=(C[0-9A-Za-z]+_[0-9A-Za-z]+)",
    re.IGNORECASE,
)
_VERSION_DEFAULT_RE = re.compile(
    r"var\s+versionDefault\s*=\s*['\"]([^'\"]+)['\"]",
    re.IGNORECASE,
)
_SKIP_TAGS = {"histories", "history", "modyear", "modchap"}
_WS = re.compile(r"\s+")


def title_xml_url(title_num: str, version: str) -> str:
    """Official title XML URL for one Utah Code title."""

    number = str(title_num or "").strip()
    token = str(version or "").strip()
    return f"{UT_BASE}/xcode/Title{number}/{token}.xml"


def discover_title_xml_urls_from_html(html: str, *, base: str = UT_BASE) -> Dict[str, str]:
    """Map title numbers to XML URLs from TOC/title-wrapper HTML."""

    out: Dict[str, str] = {}
    for match in _TITLE_VERSION_RE.finditer(html or ""):
        title_num = match.group(1)
        version = match.group(2)
        out[title_num] = f"{base}/xcode/Title{title_num}/{version}.xml"
    return out


def version_default_from_html(html: str) -> Optional[str]:
    match = _VERSION_DEFAULT_RE.search(html or "")
    if not match:
        return None
    token = str(match.group(1) or "").strip()
    return token or None


def _elem_text(elem: ET.Element) -> str:
    """Collect descendant text, skipping amendment history."""

    parts: List[str] = []
    if elem.text:
        parts.append(elem.text)
    for child in elem:
        tag = str(child.tag or "").split("}", 1)[-1]
        if tag in _SKIP_TAGS:
            if child.tail:
                parts.append(child.tail)
            continue
        if tag == "catchline":
            if child.tail:
                parts.append(child.tail)
            continue
        if tag == "subsection":
            num = child.attrib.get("number", "")
            sub_text = _elem_text(child).strip()
            label = num.split("(")[-1].split(")")[0] if "(" in num else ""
            prefix = f"({label}) " if label else ""
            parts.append(f"\n{prefix}{sub_text}")
            if child.tail:
                parts.append(child.tail)
            continue
        parts.append(_elem_text(child))
        if child.tail:
            parts.append(child.tail)
    return "".join(parts)


def _harvest_sections(
    elem: ET.Element,
    *,
    title_num: str,
    title_name: str,
    chap_num: str,
    chap_name: str,
) -> List[dict]:
    out: List[dict] = []
    for child in elem:
        tag = str(child.tag or "").split("}", 1)[-1]
        if tag == "section":
            sec_num = str(child.attrib.get("number") or "").strip()
            catch = child.find("catchline")
            heading = (catch.text or "").strip() if catch is not None else ""
            body = _WS.sub(" ", _elem_text(child)).strip()
            if not sec_num or len(body) < 20:
                continue
            out.append(
                {
                    "title_num": title_num,
                    "title_name": title_name,
                    "chapter_num": chap_num,
                    "chapter_name": chap_name,
                    "section_num": sec_num,
                    "heading": heading,
                    "body": body,
                }
            )
        elif tag in {"part", "subpart", "subdivision", "article"}:
            out.extend(
                _harvest_sections(
                    child,
                    title_num=title_num,
                    title_name=title_name,
                    chap_num=chap_num,
                    chap_name=chap_name,
                )
            )
    return out


def _title_records(title_elem: ET.Element) -> List[dict]:
    title_num = str(title_elem.attrib.get("number") or "").strip()
    catch = title_elem.find("catchline")
    title_name = (catch.text or "").strip() if catch is not None else ""
    records: List[dict] = []
    for chap in title_elem.findall("chapter"):
        chap_num = str(chap.attrib.get("number") or "").strip()
        ccatch = chap.find("catchline")
        chap_name = (ccatch.text or "").strip() if ccatch is not None else ""
        records.extend(
            _harvest_sections(
                chap,
                title_num=title_num,
                title_name=title_name,
                chap_num=chap_num,
                chap_name=chap_name,
            )
        )
    return records


def parse_utah_xml_document(
    xml_bytes: bytes | str,
    *,
    code_name: str = "Utah Code",
    source_url: str = "",
    max_statutes: Optional[int] = None,
) -> List[NormalizedStatute]:
    """Parse one official title XML (or a document containing ``<title>`` nodes)."""

    if not xml_bytes:
        return []
    raw = xml_bytes.encode("utf-8") if isinstance(xml_bytes, str) else xml_bytes
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return []

    tag = str(root.tag or "").split("}", 1)[-1]
    titles: Iterable[ET.Element]
    if tag == "title":
        titles = [root]
    else:
        titles = root.findall(".//title")

    statutes: List[NormalizedStatute] = []
    for title_elem in titles:
        for rec in _title_records(title_elem):
            if max_statutes is not None and len(statutes) >= int(max_statutes):
                return statutes
            section_num = rec["section_num"]
            title_num = rec["title_num"]
            xml_url = source_url
            if title_num and source_url and "/xcode/Title" not in source_url:
                xml_url = f"{UT_BASE}/xcode/Title{title_num}/"
            elif not xml_url and title_num:
                xml_url = f"{UT_BASE}/xcode/Title{title_num}/"
            statutes.append(
                NormalizedStatute(
                    state_code="UT",
                    state_name="Utah",
                    statute_id=f"{code_name} § {section_num}",
                    code_name=code_name,
                    title_number=title_num or None,
                    title_name=rec["title_name"] or None,
                    chapter_number=rec["chapter_num"] or None,
                    chapter_name=rec["chapter_name"] or None,
                    section_number=section_num,
                    section_name=(
                        f"§ {section_num}. {rec['heading']}" if rec["heading"] else f"Section {section_num}"
                    )[:220],
                    full_text=rec["body"][:20000],
                    source_url=xml_url,
                    official_cite=f"Utah Code § {section_num}",
                    metadata=StatuteMetadata(),
                    structured_data={
                        "source_kind": "official_utah_title_xml",
                        "source_authority_class": "official",
                        "discovery_method": "le_utah_gov_title_xml",
                        "skip_hydrate": True,
                    },
                )
            )
    return statutes


def configured_title_xml_path() -> Optional[Path]:
    raw = str(os.environ.get("UTAH_TITLE_XML") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None
