"""Official Michigan Compiled Laws chapter XML parser.

Adapted from Vaquill-AI/open-us-law ``mi_bulk.parse`` (Apache-2.0).
``legislature.mi.gov/documents/mcl/Chapter%20{N}.xml`` is UTF-16 with escaped
inner BodyText markup. Local path: ``MICHIGAN_CHAPTER_XML``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from xml.etree import ElementTree as ET

from .base_scraper import (
    NormalizedStatute,
    StatuteMetadata,
    current_state_law_run_environment_value,
)

BASE = "https://www.legislature.mi.gov"
_WS = re.compile(r"\s+")


@dataclass
class MichiganChapterParseResult:
    """Exact reconciliation for one official MCL chapter XML document."""

    chapter_number: str = ""
    chapter_title: str = ""
    statutes: List[NormalizedStatute] = field(default_factory=list)
    terminal_sections: List[Dict[str, str]] = field(default_factory=list)
    unclassified_sections: List[Dict[str, str]] = field(default_factory=list)
    source_section_count: int = 0
    closed: bool = False


def act_slug(name: str) -> str:
    return re.sub(r"[^0-9A-Za-z-]+", "-", (name or "").strip()).lstrip("-")


def chapter_xml_url(chapter_name: str) -> str:
    return f"{BASE}/documents/mcl/Chapter%20{chapter_name}.xml"


def section_url(section_number: str) -> str:
    token = _clean(section_number)
    constitution = re.fullmatch(
        r"Article\s+([IVXLCDM]+)\s*§\s*([0-9A-Za-z.-]+)",
        token,
        re.IGNORECASE,
    )
    if constitution:
        return (
            f"{BASE}/Laws/MCL?objectName=mcl-Article-"
            f"{constitution.group(1).upper()}-{constitution.group(2)}"
        )
    schedule = re.fullmatch(
        r"Schedule\s*§\s*([0-9A-Za-z.-]+)",
        token,
        re.IGNORECASE,
    )
    if schedule:
        return f"{BASE}/Laws/MCL?objectName=mcl-Schedule-{schedule.group(1)}"
    return f"{BASE}/Laws/MCL?objectName=mcl-{token.replace('.', '-')}"


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


def _terminal_disposition(*, repealed: bool, catchline: str) -> str:
    normalized = _clean(catchline).strip(" .")
    for disposition in ("expired", "reserved", "renumbered", "transferred", "omitted"):
        if re.match(rf"^{disposition}\b", normalized, re.IGNORECASE):
            return disposition
    if repealed or re.match(r"^repealed\b", normalized, re.IGNORECASE):
        return "repealed"
    return ""


def parse_michigan_chapter_xml_closure(
    xml_text: str | bytes,
    *,
    chapter_hint: str = "",
    code_name: str = "Michigan Compiled Laws",
    max_statutes: Optional[int] = None,
    source_bundle_url: str = "",
) -> MichiganChapterParseResult:
    """Parse and reconcile every exposed MCL statutory source unit.

    The official XML supplies an explicit ``Repealed`` flag.  Strict callers
    can therefore prove ``source = operative + typed terminal`` without
    inventing missing section numbers or treating an empty body as a statute.
    A wholly repealed ``MCLStatuteInfo`` may retain no section children at all;
    that source unit is a typed terminal rather than an empty chapter.
    """

    report = MichiganChapterParseResult(chapter_number=str(chapter_hint or "").strip())
    if isinstance(xml_text, bytes):
        if xml_text[:2] in (b"\xff\xfe", b"\xfe\xff"):
            xml_text = xml_text.decode("utf-16")
        else:
            xml_text = xml_text.decode("utf-8-sig", errors="replace")
    try:
        root = ET.fromstring(xml_text)
    except (ET.ParseError, ValueError, UnicodeError) as exc:
        report.unclassified_sections.append(
            {"reason": "xml_parse_error", "detail": str(exc)[:300]}
        )
        return report
    chapter_name = _clean(root.findtext("Name") or "") or str(chapter_hint)
    chapter_title = _clean(root.findtext("Title") or "")
    report.chapter_number = chapter_name
    report.chapter_title = chapter_title
    source_url = source_bundle_url or chapter_xml_url(chapter_name)
    constitution_chapter = "constitution" in chapter_title.casefold()
    seen_numbers: set[str] = set()
    seen_terminal_statutes: set[str] = set()
    truncated = False

    def recurse(node: ET.Element, cur_act: Optional[str]) -> None:
        nonlocal truncated
        if max_statutes is not None and len(report.statutes) >= int(max_statutes):
            truncated = True
            return
        for child in node:
            tag = child.tag
            if tag == "MCLStatuteInfo":
                act_name = _clean(child.findtext("Name") or "")
                document_id = _clean(child.findtext("DocumentID") or "")
                source_record_id = document_id or act_name
                section_nodes = list(child.iter("MCLSectionInfo"))
                if section_nodes:
                    recurse(child, act_slug(act_name))
                    continue

                # The official bundle preserves some wholly repealed acts as
                # statute metadata with an empty document collection (for
                # example, current chapters 340 and 804).  Count the retained
                # statute node once; there are no section nodes to count.
                report.source_section_count += 1
                repealed_raw = (child.findtext("Repealed") or "").strip().lower()
                heading = _clean(child.findtext("Heading") or "")
                long_title = _clean(child.findtext("LongTitle") or "")
                repeated = (
                    source_record_id.casefold() in seen_terminal_statutes
                    if source_record_id
                    else False
                )
                if source_record_id:
                    seen_terminal_statutes.add(source_record_id.casefold())
                if not source_record_id or repeated:
                    report.unclassified_sections.append(
                        {
                            "section_number": "",
                            "catchline": long_title or heading,
                            "reason": (
                                "duplicate_sectionless_statute_identity"
                                if repeated
                                else "missing_sectionless_statute_identity"
                            ),
                        }
                    )
                    continue
                if repealed_raw != "true":
                    report.unclassified_sections.append(
                        {
                            "section_number": "",
                            "catchline": long_title or heading or act_name,
                            "reason": "nonrepealed_statute_without_section_nodes",
                            "source_record_id": source_record_id,
                        }
                    )
                    continue
                report.terminal_sections.append(
                    {
                        "section_number": "",
                        "catchline": long_title or heading or act_name,
                        "disposition": "repealed",
                        "source_record_id": source_record_id,
                        "source_record_type": "sectionless_statute",
                        "source_url": source_url,
                    }
                )
            elif tag in ("MCLDivisionInfo", "MCLDocumentInfoCollection"):
                recurse(child, cur_act)
            elif tag == "MCLSectionInfo":
                report.source_section_count += 1
                number = _clean(child.findtext("MCLNumber") or "")
                catchline = _clean(child.findtext("CatchLine") or "")
                repeated = number.casefold() in seen_numbers if number else False
                if number:
                    seen_numbers.add(number.casefold())
                if not number or repeated:
                    report.unclassified_sections.append(
                        {
                            "section_number": number,
                            "catchline": catchline,
                            "reason": (
                                "duplicate_section_number" if repeated else "missing_section_number"
                            ),
                        }
                    )
                    continue
                repealed_raw = (child.findtext("Repealed") or "").strip().lower()
                if repealed_raw not in {"true", "false"}:
                    report.unclassified_sections.append(
                        {
                            "section_number": number,
                            "catchline": catchline,
                            "reason": "missing_or_invalid_repealed_flag",
                        }
                    )
                    continue
                disposition = _terminal_disposition(
                    repealed=repealed_raw == "true",
                    catchline=catchline,
                )
                if repealed_raw == "true":
                    report.terminal_sections.append(
                        {
                            "section_number": number,
                            "catchline": catchline,
                            "disposition": disposition or "repealed",
                            "source_url": section_url(number),
                        }
                    )
                    continue
                if disposition:
                    report.unclassified_sections.append(
                        {
                            "section_number": number,
                            "catchline": catchline,
                            "reason": "terminal_disposition_flag_mismatch",
                            "disposition": disposition,
                        }
                    )
                    continue
                if cur_act is None:
                    report.unclassified_sections.append(
                        {
                            "section_number": number,
                            "catchline": catchline,
                            "reason": "missing_statute_context",
                        }
                    )
                    continue
                paras = _markup_to_paragraphs(child.findtext("BodyText") or "")
                body = " ".join(paras).strip()
                if len(body) < 20:
                    report.unclassified_sections.append(
                        {
                            "section_number": number,
                            "catchline": catchline,
                            "reason": "missing_or_short_operative_body",
                        }
                    )
                    continue
                row_code_name = "Michigan Constitution" if constitution_chapter else code_name
                title_number: Optional[str] = None
                official_cite = f"Mich. Comp. Laws § {number}"
                if constitution_chapter:
                    article = re.fullmatch(
                        r"Article\s+([IVXLCDM]+)\s*§\s*([0-9A-Za-z.-]+)",
                        number,
                        re.IGNORECASE,
                    )
                    schedule = re.fullmatch(
                        r"Schedule\s*§\s*([0-9A-Za-z.-]+)",
                        number,
                        re.IGNORECASE,
                    )
                    if article:
                        title_number = article.group(1).upper()
                        official_cite = (
                            f"Mich. Const. art. {title_number}, § {article.group(2)}"
                        )
                    elif schedule:
                        title_number = "Schedule"
                        official_cite = f"Mich. Const. sched. § {schedule.group(1)}"
                    else:
                        official_cite = f"Mich. Const. {number}"
                report.statutes.append(
                    NormalizedStatute(
                        state_code="MI",
                        state_name="Michigan",
                        statute_id=f"{row_code_name} § {number}",
                        code_name=row_code_name,
                        title_number=title_number,
                        title_name=chapter_title or None,
                        chapter_number=chapter_name or None,
                        section_number=number,
                        section_name=(catchline or f"Section {number}")[:200],
                        full_text=body,
                        source_url=section_url(number),
                        official_cite=official_cite,
                        metadata=StatuteMetadata(),
                        structured_data={
                            "source_kind": "official_michigan_mcl_xml",
                            "source_authority_class": "official",
                            "discovery_method": "legislature_mi_mcl_chapter_xml",
                            "act_slug": cur_act,
                            "source_bundle_url": source_url,
                            "source_record_id": number,
                            "skip_hydrate": True,
                        },
                    )
                )
                if max_statutes is not None and len(report.statutes) >= int(max_statutes):
                    truncated = True
                    return

    recurse(root, None)
    report.closed = bool(
        not truncated
        and report.source_section_count > 0
        and report.source_section_count
        == len(report.statutes)
        + len(report.terminal_sections)
        + len(report.unclassified_sections)
        and not report.unclassified_sections
    )
    return report


def parse_michigan_chapter_xml(
    xml_text: str | bytes,
    *,
    chapter_hint: str = "",
    code_name: str = "Michigan Compiled Laws",
    max_statutes: Optional[int] = None,
) -> List[NormalizedStatute]:
    """Compatibility wrapper returning operative rows only."""

    return parse_michigan_chapter_xml_closure(
        xml_text,
        chapter_hint=chapter_hint,
        code_name=code_name,
        max_statutes=max_statutes,
    ).statutes


def configured_chapter_xml_path() -> Optional[Path]:
    raw = current_state_law_run_environment_value("MICHIGAN_CHAPTER_XML").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None


def configured_chapter_index_html_path() -> Optional[Path]:
    raw = current_state_law_run_environment_value(
        "MICHIGAN_CHAPTER_INDEX_HTML"
    ).strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None


def parse_configured_chapter_index_html() -> List[Tuple[str, str, str]]:
    path = configured_chapter_index_html_path()
    if path is None:
        return []
    return chapter_index_links(path.read_text(encoding="utf-8", errors="replace"))


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
