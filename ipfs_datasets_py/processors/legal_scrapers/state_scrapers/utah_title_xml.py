"""Official Utah Code per-title XML parser.

Adapted from Vaquill-AI/open-us-law ``ingest_ut_statutes.py`` (Apache-2.0).
``le.utah.gov`` publishes each title as ``/xcode/Title{{N}}/{{version}}.xml``.
Amendment ``<histories>`` blocks are dropped from the body.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple
from urllib.parse import parse_qs, urljoin, urlsplit, urlunsplit
from xml.etree import ElementTree as ET

from .base_scraper import (
    NormalizedStatute,
    StatuteMetadata,
    current_state_law_run_environment_value,
)

UT_BASE = "https://le.utah.gov"

_TITLE_VERSION_RE = re.compile(
    r"/xcode/Title([0-9A-Za-z]+)/[0-9A-Za-z]+\.html\?v=(C[0-9A-Za-z]+_[0-9A-Za-z]+)",
    re.IGNORECASE,
)
_VERSION_DEFAULT_RE = re.compile(
    r"var\s+versionDefault\s*=\s*['\"]([^'\"]+)['\"]",
    re.IGNORECASE,
)
_SKIP_TAGS = {
    "effdate",
    "enddate",
    "histories",
    "history",
    "modyear",
    "modchap",
}
_WS = re.compile(r"\s+")
_ROOT_VERSION_RE = re.compile(r"^C_\d{16}$")
_TITLE_PATH_RE = re.compile(
    r"^/xcode/Title(?P<title>\d{1,2}[A-Za-z]?)/"
    r"(?P=title)\.html$",
    re.IGNORECASE,
)
_TEMPORAL_NOTE_RE = re.compile(
    r"\((?P<kind>Effective|Superseded|Repealed|Expired)\s+"
    r"(?P<date>\d{1,2}/\d{1,2}/\d{4})\)",
    re.IGNORECASE,
)
_TERMINAL_TEXT_RE = re.compile(
    r"^\s*\[?\s*(repealed|reserved|renumbered|superseded|expired|deleted)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class UtahTitleXmlLocator:
    """One exact title/version row declared by the official root table."""

    position: int
    title_number: str
    title_name: str
    source_label: str
    declared_wrapper_url: str
    version_token: str
    xml_url: str
    disposition: str
    effective_date: str
    superseded_date: str


@dataclass(frozen=True)
class UtahTitleXmlParseResult:
    """Exhaustive disposition of every ``<section>`` in one title XML."""

    title_number: str
    title_name: str
    rows: tuple[NormalizedStatute, ...]
    terminal_sections: tuple[dict, ...]
    excluded_sections: tuple[dict, ...]
    duplicate_sections: tuple[dict, ...]
    residual_sections: tuple[dict, ...]
    discovered_section_count: int


def _local_tag(elem: ET.Element) -> str:
    return str(elem.tag or "").split("}", 1)[-1].casefold()


def _clean(text: str) -> str:
    return _WS.sub(" ", str(text or "").replace("\xa0", " ")).strip()


def _as_of_date(value: str | date) -> date:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value or "").strip())
    except ValueError as exc:
        raise ValueError(f"invalid Utah Code as-of date: {value!r}") from exc


def _source_date(value: str, *, field: str) -> date:
    try:
        return (
            datetime.strptime(str(value or "").strip(), "%m/%d/%Y")
            .replace(tzinfo=UTC)
            .date()
        )
    except ValueError as exc:
        raise ValueError(f"invalid Utah Code {field}: {value!r}") from exc


def root_versioned_html_url(
    wrapper_html: str,
    *,
    wrapper_url: str = f"{UT_BASE}/xcode/code.html",
) -> str:
    """Resolve the one root content URL declared by ``versionDefault``."""

    version = version_default_from_html(wrapper_html)
    if version is None or _ROOT_VERSION_RE.fullmatch(version) is None:
        raise ValueError("Utah Code wrapper lacks one valid root versionDefault")
    parsed = urlsplit(wrapper_url)
    if parsed.scheme != "https" or (parsed.hostname or "").casefold() != "le.utah.gov":
        raise ValueError("Utah Code wrapper URL is not the official HTTPS root")
    base_path = parsed.path.rsplit("/", 1)[0]
    return urlunsplit(("https", "le.utah.gov", f"{base_path}/{version}.html", "", ""))


def title_xml_frontier_from_root_html(
    html: str,
    *,
    root_url: str,
    as_of_date: str | date,
) -> List[UtahTitleXmlLocator]:
    """Parse every official ``#childtbl`` row without a static title list."""

    try:
        from bs4 import BeautifulSoup
    except ImportError as exc:  # pragma: no cover - production dependency
        raise RuntimeError("BeautifulSoup is required for Utah Code inventory") from exc

    observed_on = _as_of_date(as_of_date)
    soup = BeautifulSoup(html or "", "html.parser")
    table = soup.find(id="childtbl")
    if table is None:
        raise ValueError("Utah Code root has no #childtbl title inventory")
    locators: List[UtahTitleXmlLocator] = []
    source_rows = [row for row in table.find_all("tr") if row.find_all("td")]
    for position, row in enumerate(source_rows, start=1):
        anchor = row.find("a", href=True)
        cells = row.find_all("td")
        if anchor is None or len(cells) < 2:
            raise ValueError(
                f"Utah Code root title row {position} is not classifiable"
            )
        label = _clean(anchor.get_text(" ", strip=True))
        label_match = re.fullmatch(r"Title\s+(\d{1,2}[A-Za-z]?)", label)
        declared_wrapper_url = urljoin(root_url, str(anchor.get("href") or "").strip())
        parsed = urlsplit(declared_wrapper_url)
        path_match = _TITLE_PATH_RE.fullmatch(parsed.path)
        query = parse_qs(parsed.query, keep_blank_values=True)
        if (
            label_match is None
            or path_match is None
            or parsed.scheme != "https"
            or (parsed.hostname or "").casefold() != "le.utah.gov"
            or set(query) != {"v"}
            or len(query["v"]) != 1
        ):
            raise ValueError(
                f"Utah Code root title row {position} changed locator structure"
            )
        title_number = label_match.group(1).upper()
        if path_match.group("title").upper() != title_number:
            raise ValueError(
                f"Utah Code root title row {position} changed title identity"
            )
        version = str(query["v"][0] or "").strip()
        if re.fullmatch(rf"C{re.escape(title_number)}_\d{{16}}", version) is None:
            raise ValueError(
                f"Utah Code root title row {position} has an invalid version"
            )
        source_label = _clean(cells[1].get_text(" ", strip=True))
        notes = list(_TEMPORAL_NOTE_RE.finditer(source_label))
        if len(notes) > 1:
            raise ValueError(
                f"Utah Code root title row {position} has ambiguous temporal notes"
            )
        effective = ""
        superseded = ""
        disposition = "active"
        title_name = source_label
        if notes:
            note = notes[0]
            title_name = _clean(
                source_label[: note.start()] + source_label[note.end() :]
            )
            source_day = _source_date(
                note.group("date"),
                field=f"{note.group('kind').casefold()} date",
            )
            kind = note.group("kind").casefold()
            if kind == "effective":
                effective = source_day.isoformat()
                if source_day > observed_on:
                    disposition = "not_yet_effective"
            else:
                superseded = source_day.isoformat()
                if source_day <= observed_on:
                    disposition = kind
        if not title_name:
            raise ValueError(f"Utah Code root title row {position} has no title name")
        xml_path = parsed.path.rsplit("/", 1)[0] + f"/{version}.xml"
        xml_url = urlunsplit(("https", "le.utah.gov", xml_path, "", ""))
        locators.append(
            UtahTitleXmlLocator(
                position=position,
                title_number=title_number,
                title_name=title_name,
                source_label=source_label,
                declared_wrapper_url=declared_wrapper_url,
                version_token=version,
                xml_url=xml_url,
                disposition=disposition,
                effective_date=effective,
                superseded_date=superseded,
            )
        )

    if not locators:
        raise ValueError("Utah Code root title inventory is empty")
    xml_urls = [row.xml_url for row in locators]
    if len(xml_urls) != len(set(xml_urls)):
        raise ValueError("Utah Code root repeats a title XML URL")
    active_titles = [row.title_number.casefold() for row in locators if row.disposition == "active"]
    repeated_active = sorted(
        title for title in set(active_titles) if active_titles.count(title) > 1
    )
    if repeated_active:
        raise ValueError(
            f"Utah Code root exposes multiple active versions: {repeated_active}"
        )
    return locators


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


_VERSION_ARR_FILE_RE = re.compile(r"""\[\s*['"]([^'"]+\.html)['"]""")
_CHILD_TITLE_RE = re.compile(r"Title\s+(\S+)", re.IGNORECASE)
_CHILD_CHAPTER_RE = re.compile(r"Chapter([^/]+)/", re.IGNORECASE)
_SECTION_HREF_RE = re.compile(
    r"([\d]+(?:-[\w]+)*)-S([\w.]+)\.html$", re.IGNORECASE
)


def version_arr_files(html: str) -> List[str]:
    """Filenames from the wrapper ``versionArr`` JS array."""

    out: List[str] = []
    seen: set[str] = set()
    for match in _VERSION_ARR_FILE_RE.finditer(html or ""):
        name = match.group(1)
        if name in seen:
            continue
        seen.add(name)
        out.append(name)
    return out


def childtbl_rows(html: str, *, base_url: str = f"{UT_BASE}/xcode/") -> List[Tuple[str, str, str, str]]:
    """``#childtbl`` title/chapter rows: ``(kind, number, name, url)``."""

    from urllib.parse import urljoin

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    soup = BeautifulSoup(html or "", "html.parser")
    table = soup.find(id="childtbl")
    if table is None:
        return []
    out: List[Tuple[str, str, str, str]] = []
    seen: set[str] = set()
    for row in table.find_all("tr"):
        anchor = row.find("a", href=True)
        if anchor is None:
            continue
        href = str(anchor.get("href") or "").strip().split("?", 1)[0]
        cells = row.find_all("td")
        label = _WS.sub(" ", (anchor.get_text(" ") or "").replace("\xa0", " ")).strip()
        suffix = _WS.sub(" ", (cells[1].get_text(" ") if len(cells) > 1 else "")).strip()
        name = f"{label} {suffix}".strip()
        title_match = _CHILD_TITLE_RE.match(label)
        if title_match:
            number = title_match.group(1).rstrip(".")
            kind = "title"
        else:
            chapter_match = _CHILD_CHAPTER_RE.search(href)
            if not chapter_match:
                continue
            number = chapter_match.group(1)
            kind = "chapter"
        key = f"{kind}:{number}"
        if key in seen:
            continue
        seen.add(key)
        out.append((kind, number, name or f"{kind} {number}", urljoin(base_url, href)))
    return out


def section_number_from_href(href: str) -> Optional[str]:
    """``3-1-S1.html`` -> ``3-1-1``."""

    match = _SECTION_HREF_RE.search(str(href or "").split("?", 1)[0])
    if not match:
        return None
    return f"{match.group(1)}-{match.group(2)}"


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


def _direct_child(elem: ET.Element, tag: str) -> Optional[ET.Element]:
    wanted = tag.casefold()
    for child in elem:
        if _local_tag(child) == wanted:
            return child
    return None


def _direct_text(elem: ET.Element, tag: str) -> str:
    child = _direct_child(elem, tag)
    return _clean(child.text or "") if child is not None else ""


def _optional_node_date(elem: ET.Element, tag: str) -> Optional[date]:
    value = _direct_text(elem, tag)
    return _source_date(value, field=tag) if value else None


def _later_date(first: Optional[date], second: Optional[date]) -> Optional[date]:
    values = [value for value in (first, second) if value is not None]
    return max(values) if values else None


def _earlier_date(first: Optional[date], second: Optional[date]) -> Optional[date]:
    values = [value for value in (first, second) if value is not None]
    return min(values) if values else None


def parse_utah_title_xml_frontier_document(
    xml_bytes: bytes | str,
    *,
    expected_title_number: str,
    expected_title_name: str,
    source_url: str,
    as_of_date: str | date,
    code_name: str = "Utah Code",
) -> UtahTitleXmlParseResult:
    """Classify every official section node without caps or silent drops."""

    raw = xml_bytes.encode("utf-8") if isinstance(xml_bytes, str) else bytes(xml_bytes)
    if not raw:
        raise ValueError("Utah title XML parser input is empty")
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise ValueError("Utah title XML parser input is malformed") from exc
    if _local_tag(root) != "title":
        raise ValueError("Utah title XML root is not one exact title")
    title_number = str(root.attrib.get("number") or "").strip().upper()
    expected_number = str(expected_title_number or "").strip().upper()
    title_name = _direct_text(root, "catchline")
    if title_number != expected_number or _clean(title_name) != _clean(expected_title_name):
        raise ValueError(
            "Utah title XML payload does not match its requested title identity"
        )
    parsed_source = urlsplit(source_url)
    if (
        parsed_source.scheme != "https"
        or (parsed_source.hostname or "").casefold() != "le.utah.gov"
        or not parsed_source.path.casefold().startswith(
            f"/xcode/title{expected_number.casefold()}/"
        )
        or not parsed_source.path.casefold().endswith(".xml")
    ):
        raise ValueError("Utah title XML source URL is not the requested official title")

    observed_on = _as_of_date(as_of_date)
    rows: List[NormalizedStatute] = []
    terminals: List[dict] = []
    exclusions: List[dict] = []
    duplicates: List[dict] = []
    residuals: List[dict] = []
    active_seen: Dict[str, tuple[str, str, str, str]] = {}
    discovered = 0

    def _section_record(
        section: ET.Element,
        *,
        chapter_number: str,
        chapter_name: str,
        inherited_effective: Optional[date],
        inherited_end: Optional[date],
    ) -> None:
        nonlocal discovered
        discovered += 1
        section_number = str(section.attrib.get("number") or "").strip()
        catchline = _direct_text(section, "catchline")
        body = _clean(_elem_text(section))
        effective = _later_date(
            inherited_effective,
            _optional_node_date(section, "effdate"),
        )
        end = _earlier_date(
            inherited_end,
            _optional_node_date(section, "enddate"),
        )
        base_record = {
            "section_number": section_number,
            "source_url": source_url,
            "effective_date": effective.isoformat() if effective else "",
            "end_date": end.isoformat() if end else "",
        }
        if not section_number:
            residuals.append({**base_record, "reason": "missing_section_identity"})
            return
        if not section_number.casefold().startswith(f"{expected_number}-".casefold()):
            exclusions.append(
                {**base_record, "reason": "embedded_cross_title_section"}
            )
            return
        if effective is not None and effective > observed_on:
            terminals.append({**base_record, "disposition": "not_yet_effective"})
            return
        if end is not None and end <= observed_on:
            terminals.append({**base_record, "disposition": "ended"})
            return
        terminal_source = catchline or body
        terminal_match = _TERMINAL_TEXT_RE.match(terminal_source)
        if terminal_match is not None and len(body) < 240:
            terminals.append(
                {
                    **base_record,
                    "disposition": terminal_match.group(1).casefold(),
                }
            )
            return
        if not body:
            residuals.append({**base_record, "reason": "empty_operative_text"})
            return

        history = _dedupe_history(
            _clean(item.text or "")
            for item in section.iter()
            if _local_tag(item) == "history"
        )
        mod_years = sorted(
            {
                _clean(item.text or "")
                for item in section.iter()
                if _local_tag(item) == "modyear"
                and re.fullmatch(r"\d{4}", _clean(item.text or ""))
            }
        )
        signature = (chapter_number, catchline, body, "|".join(history))
        identity = section_number.casefold()
        prior = active_seen.get(identity)
        if prior is not None:
            if prior == signature:
                duplicates.append(
                    {**base_record, "reason": "exact_duplicate_active_section"}
                )
            else:
                residuals.append(
                    {**base_record, "reason": "divergent_duplicate_active_section"}
                )
            return
        active_seen[identity] = signature
        metadata = StatuteMetadata(
            effective_date=effective.isoformat() if effective else None,
            last_amended=mod_years[-1] if mod_years else None,
            history=list(history),
        )
        rows.append(
            NormalizedStatute(
                state_code="UT",
                state_name="Utah",
                statute_id=f"{code_name} § {section_number}",
                code_name=code_name,
                title_number=title_number,
                title_name=title_name,
                chapter_number=chapter_number or None,
                chapter_name=chapter_name or None,
                section_number=section_number,
                section_name=(
                    f"§ {section_number}. {catchline}"
                    if catchline
                    else f"Section {section_number}"
                )[:220],
                full_text=body,
                source_url=f"{source_url}#section-{section_number}",
                official_cite=f"Utah Code § {section_number}",
                metadata=metadata,
                structured_data={
                    "source_kind": "official_utah_title_xml",
                    "source_authority_class": "official",
                    "discovery_method": "official_xcode_root_title_xml_frontier",
                    "skip_hydrate": True,
                    "temporal_disposition": "active",
                    "effective_date": effective.isoformat() if effective else "",
                    "end_date": end.isoformat() if end else "",
                    "history": list(history),
                },
            )
        )

    def _walk(
        elem: ET.Element,
        *,
        chapter_number: str,
        chapter_name: str,
        inherited_effective: Optional[date],
        inherited_end: Optional[date],
    ) -> None:
        tag = _local_tag(elem)
        effective = _later_date(
            inherited_effective,
            _optional_node_date(elem, "effdate"),
        )
        end = _earlier_date(
            inherited_end,
            _optional_node_date(elem, "enddate"),
        )
        if tag == "chapter":
            chapter_number = str(elem.attrib.get("number") or "").strip()
            chapter_name = _direct_text(elem, "catchline")
        if tag == "section":
            _section_record(
                elem,
                chapter_number=chapter_number,
                chapter_name=chapter_name,
                inherited_effective=inherited_effective,
                inherited_end=inherited_end,
            )
            return
        for child in elem:
            if _local_tag(child) in {
                "catchline",
                "effdate",
                "enddate",
                "histories",
                "history",
                "modyear",
                "modchap",
            }:
                continue
            _walk(
                child,
                chapter_number=chapter_number,
                chapter_name=chapter_name,
                inherited_effective=effective,
                inherited_end=end,
            )

    _walk(
        root,
        chapter_number="",
        chapter_name="",
        inherited_effective=None,
        inherited_end=None,
    )
    classified = len(rows) + len(terminals) + len(exclusions) + len(duplicates) + len(residuals)
    if classified != discovered:
        raise ValueError("Utah title XML section disposition algebra did not close")
    return UtahTitleXmlParseResult(
        title_number=title_number,
        title_name=title_name,
        rows=tuple(rows),
        terminal_sections=tuple(terminals),
        excluded_sections=tuple(exclusions),
        duplicate_sections=tuple(duplicates),
        residual_sections=tuple(residuals),
        discovered_section_count=discovered,
    )


def _dedupe_history(items: Iterable[str]) -> tuple[str, ...]:
    out: List[str] = []
    seen: set[str] = set()
    for item in items:
        value = _clean(item)
        if value and value.casefold() not in seen:
            out.append(value)
            seen.add(value.casefold())
    return tuple(out)


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
    seen_sections: Dict[str, tuple[str, str, str, str, str]] = {}
    for title_elem in titles:
        for rec in _title_records(title_elem):
            section_num = rec["section_num"]
            title_num = rec["title_num"]
            if title_num and not section_num.casefold().startswith(
                f"{title_num}-".casefold()
            ):
                # Official title XML can embed quoted/cross-referenced sections
                # from another title.  They are not members of this title's
                # statutory frontier and must not acquire the enclosing title's
                # identity.
                continue
            section_key = section_num.casefold()
            signature = (
                str(rec["title_num"] or ""),
                str(rec["chapter_num"] or ""),
                str(rec["heading"] or ""),
                str(rec["body"] or ""),
                str(rec["title_name"] or ""),
            )
            prior = seen_sections.get(section_key)
            if prior is not None:
                if prior == signature:
                    continue
                raise ValueError(
                    "Utah title XML contains divergent duplicate section "
                    f"identity: {section_num}"
                )
            seen_sections[section_key] = signature
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
                    full_text=rec["body"],
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
    if max_statutes is None:
        return statutes
    return statutes[: max(0, int(max_statutes))]


def configured_title_xml_path() -> Optional[Path]:
    raw = current_state_law_run_environment_value("UTAH_TITLE_XML").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None


def configured_toc_html_path() -> Optional[Path]:
    raw = current_state_law_run_environment_value("UTAH_TOC_HTML").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None


def parse_configured_toc_html() -> Dict[str, str]:
    """Local TOC dump of Title hrefs. Does not run Playwright discovery."""

    path = configured_toc_html_path()
    if path is None:
        return {}
    return discover_title_xml_urls_from_html(
        path.read_text(encoding="utf-8", errors="replace")
    )
