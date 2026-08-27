"""Official North Dakota Century Code chapter PDF/text parser.

Adapted from Vaquill-AI/open-us-law ``scrapeND.py`` (Apache-2.0).
Chapter PDFs at ``ndlegis.gov/cencode/tNNcNN.pdf`` are never auto-downloaded.
Set ``NORTH_DAKOTA_CHAPTER_TEXT`` or ``NORTH_DAKOTA_CHAPTER_PDF``.
"""

from __future__ import annotations

import hashlib
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .base_scraper import NormalizedStatute, StatuteMetadata

CENCODE = "https://ndlegis.gov/cencode"
BASE = "https://ndlegis.gov"
_SEC_HEADER_RE = re.compile(r"^(\d[\d.]*(?:-[\d.]+)+)\.\s+(.+)$")
_PAGE_FOOTER_RE = re.compile(r"^Page No\.\s+\d+\s*$", re.IGNORECASE)
_RUNNING_HEADER_RE = re.compile(
    r"^(?:CHAPTER\s+\d[\d.\-]*|TITLE\s+\d[\d.]*|TABLE OF CONTENTS)\s*$",
    re.IGNORECASE,
)
_HISTORY_START_RE = re.compile(
    r"^(Source:|History:|S\.L\.\s+\d{4}|Amended\s+by\s+S\.L\.)", re.IGNORECASE
)
_STATUS_TOKEN_RE = re.compile(
    r"\b(repealed|reserved|expired|renumbered|transferred|superseded|"
    r"omitted|unconstitutional|redesignated|disapproved)\b",
    re.IGNORECASE,
)
_BRACKETED_STATUS_RE = re.compile(r"\[(?P<status>[^\]]+)\]\.?$", re.IGNORECASE)
_DOCUMENT_BRACKETED_STATUS_RE = re.compile(
    r"\[(?P<status>[^\]]+)\]",
    re.IGNORECASE | re.DOTALL,
)
_STANDALONE_STATUS_RE = re.compile(
    r"^(?:\([^)]+\)\s+)?(?P<status>repealed|reserved|expired|renumbered|"
    r"transferred|superseded|omitted|unconstitutional|redesignated|"
    r"disapproved)\.?$",
    re.IGNORECASE,
)
_COMPILER_RESERVED_RANGE_RE = re.compile(r"\bare\s+reserved\.?$", re.IGNORECASE)
_BODY_TERMINAL_RE = re.compile(
    r"^(?:this\s+(?:section|chapter|title)\s+(?:was|is)\s+)?"
    r"(repealed|reserved|expired|renumbered|transferred|superseded|omitted|"
    r"redesignated|disapproved)\b",
    re.IGNORECASE,
)
_TEMPORAL_QUALIFIER_RE = re.compile(
    r"\(\s*Effective\s+(?P<role>through|after)\s+"
    r"(?P<month>January|February|March|April|May|June|July|August|"
    r"September|October|November|December)\s+(?P<day>\d{1,2}),\s*"
    r"(?P<year>\d{4})\s*\)\.?$",
    re.IGNORECASE,
)
_TEMPORAL_QUALIFIER_PREFIX_RE = re.compile(
    r"^(?P<base>.+?)\.?\s*\(\s*Effective\s+"
    r"(?P<role>through|after)\s*$",
    re.IGNORECASE,
)
_WS = re.compile(r"\s+")


def _clean(text: str) -> str:
    return _WS.sub(" ", (text or "").replace("\xa0", " ").replace("‑", "-")).strip()


def _normalize_section_identity(value: str) -> str:
    """Reconcile the PDF's zero-padded title token with the live index."""

    parts = _clean(value).split("-")
    if parts and parts[0].isdigit():
        parts[0] = str(int(parts[0]))
    return "-".join(parts)


def _source_proved_index_identity_repair(candidate: str, expected: str) -> str:
    """Repair one PDF heading that drops the indexed chapter decimal suffix."""

    candidate_parts = _normalize_section_identity(candidate).split("-")
    expected_parts = _normalize_section_identity(expected).split("-")
    if (
        len(candidate_parts) == len(expected_parts) == 3
        and candidate_parts[0] == expected_parts[0]
        and candidate_parts[2] == expected_parts[2]
        and expected_parts[1].startswith(candidate_parts[1] + ".")
        and expected_parts[1][len(candidate_parts[1]) + 1 :].isdigit()
    ):
        return "official_pdf_dropped_chapter_decimal_suffix"
    return ""


def _comparable_source_heading(value: str) -> str:
    return re.sub(r"[\W_]+", " ", _clean(value), flags=re.UNICODE).strip().casefold()


def _source_heading_labels_concord(left: str, right: str) -> bool:
    def _comparable(value: str) -> str:
        return _comparable_source_heading(value)

    left_value = _comparable(left)
    right_value = _comparable(right)
    return bool(
        left_value
        and right_value
        and (
            left_value == right_value
            or left_value.startswith(right_value)
            or right_value.startswith(left_value)
        )
    )


def _temporal_heading_parts(
    heading_prefix: str,
    body_parts: Sequence[str],
) -> Optional[Dict[str, Any]]:
    """Split one source-marked calendar qualifier from wrapped PDF text."""

    for consumed in range(0, min(3, len(body_parts)) + 1):
        heading = _clean(" ".join([heading_prefix, *body_parts[:consumed]]))
        match = _TEMPORAL_QUALIFIER_RE.search(heading)
        if match is None:
            continue
        trigger = datetime.strptime(
            f"{match.group('month')} {match.group('day')} {match.group('year')}",
            "%B %d %Y",
        ).date()
        boundary = trigger + timedelta(days=1)
        return {
            "base_heading": _clean(heading[: match.start()].rstrip(" .-")),
            "body_parts": list(body_parts[consumed:]),
            "boundary_date": boundary.isoformat(),
            "heading": heading.rstrip("."),
            "role": str(match.group("role") or "").casefold(),
            "trigger_date": trigger.isoformat(),
        }
    return None


def _temporal_heading_prefix(value: str) -> Optional[Dict[str, str]]:
    match = _TEMPORAL_QUALIFIER_PREFIX_RE.match(_clean(value))
    if match is None:
        return None
    return {
        "base_heading": _clean(match.group("base").rstrip(" .-")),
        "role": str(match.group("role") or "").casefold(),
    }


def _find_body_start(lines: List[str]) -> int:
    for index, line in enumerate(lines):
        if not _SEC_HEADER_RE.match(line):
            continue
        for nxt in lines[index + 1 : index + 6]:
            token = nxt.strip()
            if not token:
                continue
            if _SEC_HEADER_RE.match(token):
                break
            return index
    return 0


def source_bound_terminal_disposition(label: str) -> str:
    """Return an exact source-marked non-operative disposition, if present."""

    normalized = _clean(label)
    bracketed = _BRACKETED_STATUS_RE.search(normalized)
    if bracketed is not None:
        match = _STATUS_TOKEN_RE.search(str(bracketed.group("status") or ""))
        return match.group(1).lower() if match is not None else ""
    standalone = _STANDALONE_STATUS_RE.match(normalized)
    if standalone is not None:
        return str(standalone.group("status") or "").casefold()
    if _COMPILER_RESERVED_RANGE_RE.search(normalized):
        return "reserved"
    return ""


def source_bound_document_terminal_disposition(text: str) -> str:
    """Classify an index leaf whose one-page PDF marks the whole unit terminal."""

    sample = str(text or "")[:4_000]
    disposition = source_bound_terminal_disposition(_clean(sample))
    if disposition:
        return disposition
    for bracketed in _DOCUMENT_BRACKETED_STATUS_RE.finditer(sample):
        match = _STATUS_TOKEN_RE.search(str(bracketed.group("status") or ""))
        if match is not None:
            return match.group(1).casefold()
    for line in sample.splitlines():
        normalized = _clean(line)
        disposition = source_bound_terminal_disposition(
            normalized
        ) or _source_bound_body_terminal_disposition(normalized)
        if disposition:
            return disposition
    return ""


def _source_bound_body_terminal_disposition(body: str) -> str:
    match = _BODY_TERMINAL_RE.search(_clean(body))
    return match.group(1).lower() if match is not None else ""


def parse_north_dakota_chapter_text_with_dispositions(
    text: str,
    *,
    source_url: str = "",
    code_name: str = "North Dakota Century Code",
    max_statutes: Optional[int] = None,
    expected_section_numbers: Optional[Sequence[str]] = None,
    expected_section_labels: Optional[Mapping[str, str]] = None,
) -> Tuple[List[NormalizedStatute], List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Parse a chapter PDF and account for every recognized section heading."""

    raw_lines = [_clean(line) for line in str(text or "").splitlines()]
    lines = [
        line
        for line in raw_lines
        if line and not _PAGE_FOOTER_RE.match(line) and not _RUNNING_HEADER_RE.match(line)
    ]
    start = _find_body_start(lines)
    statutes: List[NormalizedStatute] = []
    terminal_units: List[Dict[str, Any]] = []
    unresolved_units: List[Dict[str, Any]] = []
    seen_sections: set[str] = set()
    current_number = ""
    current_number_raw = ""
    current_identity_repair = ""
    current_name = ""
    current_body: List[str] = []
    in_history = False
    expected_ids = (
        [_normalize_section_identity(value) for value in expected_section_numbers]
        if expected_section_numbers is not None
        else None
    )
    if expected_ids is not None and len(expected_ids) != len(set(expected_ids)):
        raise ValueError("North Dakota expected section frontier contains duplicates")
    expected_labels = {
        _normalize_section_identity(key): _clean(value)
        for key, value in dict(expected_section_labels or {}).items()
    }
    expected_cursor = 0
    skipped_temporal_variant: Optional[Dict[str, Any]] = None

    def flush() -> None:
        nonlocal current_number, current_number_raw, current_identity_repair
        nonlocal current_name, current_body, in_history
        if not current_number:
            return
        body = _clean(" ".join(current_body))
        heading = current_name
        if current_number in seen_sections:
            raise ValueError(
                "North Dakota chapter payload repeated exact section identity: "
                f"{current_number}"
            )
        seen_sections.add(current_number)
        parts = current_number.split("-")
        identity_disclosure = (
            {
                "section_identity_repair": current_identity_repair,
                "section_number_raw": current_number_raw,
            }
            if current_identity_repair
            else {}
        )
        disposition = source_bound_terminal_disposition(
            heading
        ) or _source_bound_body_terminal_disposition(body)
        if disposition:
            terminal_units.append(
                {
                    "frontier_level": "section",
                    "title_number": parts[0] if parts else "",
                    "chapter_number": "-".join(parts[:2]) if len(parts) > 1 else "",
                    "section_number": current_number,
                    "source_label": heading,
                    "source_url": source_url or f"{CENCODE}/",
                    "disposition": disposition,
                    **identity_disclosure,
                }
            )
            current_number = ""
            current_number_raw = ""
            current_identity_repair = ""
            current_name = ""
            current_body = []
            in_history = False
            return
        if not body:
            unresolved_units.append(
                {
                    "frontier_level": "section",
                    "title_number": parts[0] if parts else "",
                    "chapter_number": "-".join(parts[:2]) if len(parts) > 1 else "",
                    "section_number": current_number,
                    "source_label": heading,
                    "source_url": source_url or f"{CENCODE}/",
                    "reason": "nonterminal_section_without_substantive_body",
                    **identity_disclosure,
                }
            )
            current_number = ""
            current_number_raw = ""
            current_identity_repair = ""
            current_name = ""
            current_body = []
            in_history = False
            return
        if max_statutes is not None and len(statutes) >= int(max_statutes):
            current_number = ""
            current_number_raw = ""
            current_identity_repair = ""
            return
        statutes.append(
            NormalizedStatute(
                state_code="ND",
                state_name="North Dakota",
                statute_id=f"{code_name} § {current_number}",
                code_name=code_name,
                title_number=parts[0] if parts else None,
                chapter_number="-".join(parts[:2]) if len(parts) > 1 else None,
                section_number=current_number,
                section_name=heading[:200] or f"Section {current_number}",
                full_text=body,
                source_url=source_url or f"{CENCODE}/",
                official_cite=f"N.D. Cent. Code § {current_number}",
                metadata=StatuteMetadata(),
                structured_data={
                    "source_kind": "official_north_dakota_chapter_pdf",
                    "source_authority_class": "official",
                    "discovery_method": "ndlegis_cencode_chapter_pdf",
                    "skip_hydrate": True,
                    **identity_disclosure,
                },
            )
        )
        current_number = ""
        current_number_raw = ""
        current_identity_repair = ""
        current_name = ""
        current_body = []
        in_history = False

    def finalize_temporal_variant() -> None:
        nonlocal skipped_temporal_variant
        if skipped_temporal_variant is None:
            return
        excluded = _temporal_heading_parts(
            str(skipped_temporal_variant["heading_prefix"]),
            list(skipped_temporal_variant["body_parts"]),
        )
        selected = dict(skipped_temporal_variant["selected_temporal"])
        selected_row = skipped_temporal_variant["selected_row"]
        expected_label = str(skipped_temporal_variant["expected_label"])
        if excluded is None:
            raise ValueError(
                "North Dakota repeated temporal section has an incomplete "
                "effective-version qualifier"
            )
        if (
            {str(selected["role"]), str(excluded["role"])}
            != {"through", "after"}
            or str(selected["boundary_date"]) != str(excluded["boundary_date"])
            or _comparable_source_heading(str(selected["base_heading"]))
            != _comparable_source_heading(str(excluded["base_heading"]))
            or not _source_heading_labels_concord(
                str(selected["heading"]),
                expected_label,
            )
            or _source_heading_labels_concord(
                str(excluded["heading"]),
                expected_label,
            )
        ):
            raise ValueError(
                "North Dakota repeated temporal section is not uniquely selected "
                "by the exact official index heading"
            )
        excluded_body = _clean(" ".join(excluded["body_parts"]))
        if not excluded_body:
            raise ValueError(
                "North Dakota noncurrent temporal variant lacks substantive body"
            )

        def disclosure(
            variant: Mapping[str, Any],
            body: str,
            *,
            index: int,
            is_selected: bool,
        ) -> Dict[str, Any]:
            role = str(variant["role"])
            result: Dict[str, Any] = {
                "full_text_sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
                "heading": str(variant["heading"]),
                "selected": is_selected,
                "source_order_index": index,
                "trigger_date": str(variant["trigger_date"]),
            }
            interval_field = (
                "effective_until" if role == "through" else "effective_from"
            )
            result[interval_field] = str(variant["boundary_date"])
            return result

        selected_row.structured_data = {
            **dict(selected_row.structured_data or {}),
            "effective_variant_boundary_date": str(selected["boundary_date"]),
            "effective_variant_count": 2,
            "effective_variant_excluded_indexes": [1],
            "effective_variant_frontier_label": expected_label,
            "effective_variant_selected_index": 0,
            "effective_variant_selection": "official_index_current_heading",
            "effective_variants": [
                disclosure(
                    selected,
                    str(selected_row.full_text or ""),
                    index=0,
                    is_selected=True,
                ),
                disclosure(
                    excluded,
                    excluded_body,
                    index=1,
                    is_selected=False,
                ),
            ],
            "source_section_occurrence_count": 2,
        }
        skipped_temporal_variant = None

    for line in lines[start:]:
        match = _SEC_HEADER_RE.match(line)
        if skipped_temporal_variant is not None:
            if match:
                candidate_number = _normalize_section_identity(match.group(1))
                candidate_label = _clean(match.group(2).rstrip("."))
                expected_label = expected_labels.get(candidate_number, "")
                is_expected_next = bool(
                    expected_ids is not None
                    and expected_cursor < len(expected_ids)
                    and candidate_number == expected_ids[expected_cursor]
                    and (
                        not expected_label
                        or _source_heading_labels_concord(
                            candidate_label,
                            expected_label,
                        )
                    )
                )
                if is_expected_next:
                    finalize_temporal_variant()
                else:
                    if candidate_number == str(
                        skipped_temporal_variant["section_number"]
                    ):
                        raise ValueError(
                            "North Dakota temporal section has more than two "
                            f"source variants: {candidate_number}"
                        )
                    if not bool(skipped_temporal_variant["in_history"]):
                        skipped_temporal_variant["body_parts"].append(line)
                    continue
            else:
                if _HISTORY_START_RE.match(line):
                    skipped_temporal_variant["in_history"] = True
                elif not bool(skipped_temporal_variant["in_history"]):
                    skipped_temporal_variant["body_parts"].append(line)
                continue
        if match:
            candidate_number_raw = _normalize_section_identity(match.group(1))
            candidate_number = candidate_number_raw
            candidate_identity_repair = ""
            if expected_ids is not None:
                candidate_label = _clean(match.group(2).rstrip("."))
                if expected_cursor < len(expected_ids):
                    expected_next_number = expected_ids[expected_cursor]
                    candidate_identity_repair = (
                        _source_proved_index_identity_repair(
                            candidate_number,
                            expected_next_number,
                        )
                    )
                    if (
                        candidate_identity_repair
                        and candidate_number not in expected_ids
                        and _source_heading_labels_concord(
                            candidate_label,
                            expected_labels.get(expected_next_number, ""),
                        )
                    ):
                        candidate_number = expected_next_number
                    else:
                        candidate_identity_repair = ""
                expected_label = expected_labels.get(candidate_number, "")
                is_expected_next = (
                    expected_cursor < len(expected_ids)
                    and candidate_number == expected_ids[expected_cursor]
                    and (
                        not expected_label
                        or _source_heading_labels_concord(
                            candidate_label,
                            expected_label,
                        )
                    )
                )
                if not is_expected_next:
                    current_temporal = (
                        _temporal_heading_parts(current_name, current_body)
                        if candidate_number == current_number
                        else None
                    )
                    candidate_temporal = _temporal_heading_parts(
                        candidate_label,
                        [],
                    ) or _temporal_heading_prefix(candidate_label)
                    if (
                        current_temporal is not None
                        and expected_label
                        and _source_heading_labels_concord(
                            str(current_temporal["heading"]),
                            expected_label,
                        )
                        and (
                            candidate_temporal is None
                            or str(current_temporal["role"])
                            != str(candidate_temporal["role"])
                        )
                        and _source_heading_labels_concord(
                            str(current_temporal["base_heading"]),
                            str(
                                candidate_temporal["base_heading"]
                                if candidate_temporal is not None
                                else candidate_label
                            ),
                        )
                    ):
                        current_name = str(current_temporal["heading"])
                        current_body = list(current_temporal["body_parts"])
                        statute_count = len(statutes)
                        terminal_count = len(terminal_units)
                        unresolved_count = len(unresolved_units)
                        flush()
                        if (
                            len(statutes) != statute_count + 1
                            or len(terminal_units) != terminal_count
                            or len(unresolved_units) != unresolved_count
                        ):
                            raise ValueError(
                                "North Dakota current temporal variant is not "
                                "an operative source section"
                            )
                        skipped_temporal_variant = {
                            "body_parts": [],
                            "expected_label": expected_label,
                            "heading_prefix": candidate_label,
                            "in_history": False,
                            "section_number": candidate_number,
                            "selected_row": statutes[-1],
                            "selected_temporal": current_temporal,
                        }
                        continue
                    if candidate_number in seen_sections or candidate_number == current_number:
                        if not expected_label or _source_heading_labels_concord(
                            candidate_label,
                            expected_label,
                        ):
                            raise ValueError(
                                "North Dakota chapter payload repeated exact "
                                f"section identity: {candidate_number}"
                            )
                    if current_number and not in_history:
                        current_body.append(line)
                    continue
                expected_cursor += 1
            flush()
            if max_statutes is not None and len(statutes) >= int(max_statutes):
                break
            current_number = candidate_number
            current_number_raw = candidate_number_raw
            current_identity_repair = candidate_identity_repair
            current_name = _clean(match.group(2).rstrip("."))
            current_body = []
            in_history = False
            continue
        if not current_number:
            continue
        if _HISTORY_START_RE.match(line):
            in_history = True
            continue
        if not in_history:
            current_body.append(line)
    finalize_temporal_variant()
    flush()
    return statutes, terminal_units, unresolved_units


def parse_north_dakota_chapter_text(
    text: str,
    *,
    source_url: str = "",
    code_name: str = "North Dakota Century Code",
    max_statutes: Optional[int] = None,
) -> List[NormalizedStatute]:
    """Compatibility rows-only projection of the exact chapter parser."""

    statutes, _terminal_units, _unresolved_units = (
        parse_north_dakota_chapter_text_with_dispositions(
            text,
            source_url=source_url,
            code_name=code_name,
            max_statutes=max_statutes,
        )
    )
    return statutes


def parse_north_dakota_chapter_pdf(
    pdf_path: Path,
    *,
    code_name: str = "North Dakota Century Code",
    max_statutes: Optional[int] = None,
) -> List[NormalizedStatute]:
    try:
        import pdfplumber
    except ImportError:
        return []
    lines: List[str] = []
    with pdfplumber.open(str(pdf_path)) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text() or ""
            lines.extend(page_text.splitlines())
    return parse_north_dakota_chapter_text(
        "\n".join(lines),
        source_url=f"{CENCODE}/{pdf_path.name}",
        code_name=code_name,
        max_statutes=max_statutes,
    )


def configured_chapter_path() -> Optional[Path]:
    for key in ("NORTH_DAKOTA_CHAPTER_TEXT", "NORTH_DAKOTA_CHAPTER_PDF"):
        raw = str(os.environ.get(key) or "").strip()
        if not raw:
            continue
        path = Path(raw).expanduser()
        if path.is_file():
            return path
    return None


def configured_toc_html_path() -> Optional[Path]:
    raw = str(os.environ.get("NORTH_DAKOTA_TOC_HTML") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.is_file() else None


def parse_configured_toc_html() -> List[Tuple[str, str, str]]:
    path = configured_toc_html_path()
    if path is None:
        return []
    return title_items(path.read_text(encoding="utf-8", errors="replace"))


def parse_configured_north_dakota_chapter(
    *,
    code_name: str = "North Dakota Century Code",
    max_statutes: Optional[int] = None,
) -> List[NormalizedStatute]:
    path = configured_chapter_path()
    if path is None:
        return []
    if path.suffix.lower() == ".pdf":
        return parse_north_dakota_chapter_pdf(path, code_name=code_name, max_statutes=max_statutes)
    return parse_north_dakota_chapter_text(
        path.read_text(encoding="utf-8", errors="replace"),
        code_name=code_name,
        max_statutes=max_statutes,
    )


def title_items(html: str, *, base_url: str = BASE) -> List[Tuple[str, str, str]]:
    """``.titles-grid .title-item`` rows from classic.html."""

    from urllib.parse import urljoin

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    soup = BeautifulSoup(html or "", "html.parser")
    grid = soup.find(class_="titles-grid") or soup
    out: List[Tuple[str, str, str]] = []
    seen: set[str] = set()
    for item in grid.find_all(class_="title-item"):
        number_node = item.find(class_=re.compile(r"title-number"))
        anchor = item.find("a", href=True)
        if number_node is None or anchor is None:
            continue
        number = _clean(number_node.get_text(" "))
        if not number or number in seen:
            continue
        seen.add(number)
        name = _clean(item.get_text(" "))
        out.append((number, name or f"Title {number}", urljoin(base_url, str(anchor.get("href") or ""))))
    return out


def chapter_table_rows(html: str, *, base_url: str = CENCODE) -> List[Tuple[str, str, str]]:
    """Title-page chapter table (number | link | name)."""

    from urllib.parse import urljoin

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    soup = BeautifulSoup(html or "", "html.parser")
    field = soup.find(class_=re.compile(r"field--name-field-pwv-custom-content")) or soup
    table = field.find("table") if field is not None else None
    if table is None:
        return []
    out: List[Tuple[str, str, str]] = []
    seen: set[str] = set()
    for row in table.find_all("tr"):
        cells = row.find_all("td")
        if len(cells) < 2:
            continue
        number = _clean(cells[0].get_text(" "))
        if not number or number in seen:
            continue
        seen.add(number)
        link = cells[1].find("a", href=True)
        name_cell = cells[2] if len(cells) > 2 else cells[1]
        name = _clean(name_cell.get_text(" "))
        url = urljoin(base_url.rstrip("/") + "/", str(link.get("href") or "")) if link else ""
        out.append((number, name, url))
    return out


def section_meta_rows(html: str) -> List[Tuple[str, str]]:
    """Chapter HTML section list ``{number, name}``."""

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    soup = BeautifulSoup(html or "", "html.parser")
    field = soup.find(class_=re.compile(r"field--name-field-pwv-custom-content")) or soup
    table = field.find("table") if field is not None else None
    if table is None:
        return []
    out: List[Tuple[str, str]] = []
    seen: set[str] = set()
    for row in table.find_all("tr"):
        cells = row.find_all("td")
        if len(cells) < 2:
            continue
        link = cells[0].find("a")
        if link is None:
            continue
        number = _clean(link.get_text(" "))
        if not number or number in seen:
            continue
        seen.add(number)
        out.append((number, _clean(cells[1].get_text(" "))))
    return out
