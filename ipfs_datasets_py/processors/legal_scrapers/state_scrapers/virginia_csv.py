"""Exact parser for the official Code of Virginia title CSV bundles.

The Virginia Law Library publishes one pipe-independent RFC 4180 CSV file for
every live Code title.  The CSV rows include repealed leaves and the compiler's
concurrent contingent-effective variants, so they provide a substantially
smaller and more exact frontier than recursively fetching every HTML section.
"""

from __future__ import annotations

import csv
import hashlib
import io
import re
from dataclasses import dataclass
from datetime import date, datetime
from difflib import SequenceMatcher
from typing import Any, Mapping
from urllib.parse import quote, urljoin, urlparse

from .base_scraper import NormalizedStatute, StatuteMetadata

VIRGINIA_LAW_LIBRARY_URL = "https://law.lis.virginia.gov/law-library"
VIRGINIA_OFFICIAL_EMPTY_PLACEHOLDER_STATUS = "official_empty_placeholder"
VIRGINIA_OFFICIAL_EMPTY_PLACEHOLDER_TITLE_NUMBER = "19.2"
VIRGINIA_OFFICIAL_EMPTY_PLACEHOLDER_TITLE_NAME = "Criminal Procedure"
VIRGINIA_OFFICIAL_EMPTY_PLACEHOLDER_CSV_TITLE_NAME = "CRIMINAL PROCEDURE"
VIRGINIA_OFFICIAL_EMPTY_PLACEHOLDER_CHAPTER_NUMBER = "25"
VIRGINIA_OFFICIAL_EMPTY_PLACEHOLDER_SECTION = "19.2-399"
VIRGINIA_OFFICIAL_EMPTY_PLACEHOLDER_SECTION_TITLE = (
    "Defense objections to be raised before trial; hearing; bill of particulars"
)
VIRGINIA_OFFICIAL_EMPTY_PLACEHOLDER_URL = (
    "https://law.lis.virginia.gov/vacode/"
    "title19.2/chapter25/section19.2-399/"
)

_CSV_FIELDS = (
    "TitleNum",
    "TitleName",
    "SubTitleNum",
    "SubTitleName",
    "PartNum",
    "PartName",
    "ChapterNum",
    "ChapterName",
    "ArticleNum",
    "ArticleName",
    "SubPartNum",
    "SubPartName",
    "Section",
    "Title",
    "Body",
)
_TITLE_CSV_PATH_RE = re.compile(
    r"^/CSV/CoVTitle_(?P<title>\d+(?:\.\d+)?[A-Za-z]?)\.csv$",
    re.IGNORECASE,
)
_SECTION_RE = re.compile(
    r"^[0-9A-Za-z]+(?:[.:-][0-9A-Za-z]+)+$",
    re.IGNORECASE,
)
_SECTION_HEADING_RE = re.compile(
    r"^\s*(?:§|section)\s*"
    r"(?P<section>[0-9A-Za-z]+(?:[.:-][0-9A-Za-z]+)+)"
    r"\s*\.?\s*(?P<title>.*?)\s*$",
    re.IGNORECASE,
)
_TERMINAL_RE = re.compile(
    r"^(?P<kind>repealed|reserved|expired|omitted|transferred|renumbered)"
    r"(?:\s*$|\s*[.,:;([]|\s+(?:by|effective|as\s+of|pursuant\s+to)\b)",
    re.IGNORECASE,
)
_WS = re.compile(r"\s+")
_DATE_TEXT = (
    r"(?:January|February|March|April|May|June|July|August|September|October|"
    r"November|December)\s+\d{1,2},\s+\d{4}"
)
_CALENDAR_BEFORE_RE = re.compile(
    rf"^\(\s*(?:Effective\s+until|Expires?)\s+(?P<date>{_DATE_TEXT})\s*\)$",
    re.IGNORECASE,
)
_CALENDAR_AFTER_RE = re.compile(
    rf"^\(\s*Effective\s+(?P<date>{_DATE_TEXT})\s*\)$",
    re.IGNORECASE,
)
_COMPOUND_CALENDAR_BEFORE_RE = re.compile(
    rf"^\(\s*Effective\s+until\s+the\s+later\s+of\s+"
    rf"(?P<date>{_DATE_TEXT}),\s+or\s+seven\s+years\s+after\s+the\s+"
    r"COVID-19\s+pandemic\s+state\s+of\s+emergency\s+expires\s*\)$",
    re.IGNORECASE,
)
_COMPOUND_CALENDAR_AFTER_RE = re.compile(
    rf"^\(\s*Effective\s+the\s+later\s+of\s+(?P<date>{_DATE_TEXT}),\s+"
    r"or\s+(?:7|seven)\s+years\s+after\s+the\s+COVID-19\s+pandemic\s+"
    r"state\s+of\s+emergency\s+expires\s*\)$",
    re.IGNORECASE,
)
_TAXABLE_BEFORE_RE = re.compile(
    rf"^\(\s*Applicable\s+to\s+taxable\s+years\s+beginning\s+"
    rf"(?:on\s+(?:or|and)\s+after\s+)?(?P<start>{_DATE_TEXT}),\s+"
    rf"but\s+before\s+(?P<end>{_DATE_TEXT})\s*\)$",
    re.IGNORECASE,
)
_TAXABLE_AFTER_RE = re.compile(
    rf"^\(\s*Applicable\s+to\s+taxable\s+years\s+beginning\s+"
    rf"(?:on\s+(?:or|and)\s+after\s+)?(?P<start>{_DATE_TEXT})\s*\)$",
    re.IGNORECASE,
)
_CONTINGENT_BEFORE_RE = re.compile(
    r"^\(\s*(?:For\s+)?contingent\s+expiration(?:\s+dates?)?\b",
    re.IGNORECASE,
)
_CONTINGENT_AFTER_RE = re.compile(
    r"^\(\s*(?:For\s+)?contingent\s+effective\s+date\b",
    re.IGNORECASE,
)


@dataclass
class VirginiaTitleCsvParseResult:
    """Closed disposition of every physical row in one title CSV."""

    title_number: str
    title_name: str
    source_record_count: int
    statutes: list[NormalizedStatute]
    terminal_records: list[dict[str, Any]]
    source_status_records: list[dict[str, Any]]
    unclassified_records: list[dict[str, Any]]
    closed: bool


@dataclass(frozen=True)
class _VirginiaCurrentSectionSelection:
    """One identity-bound body selected from an official current page."""

    section_number: str = ""
    body_text: str = ""
    document_title: str = ""
    branch_title: str = ""
    branch_count: int = 0


def _normalize_title_number(value: str) -> str:
    match = re.fullmatch(
        r"(?P<number>\d+(?:\.\d+)?)(?P<suffix>[A-Za-z]?)",
        str(value or "").strip(),
    )
    if match is None:
        return ""
    return match.group("number") + match.group("suffix").upper()


def virginia_title_csv_url(title_number: str) -> str:
    """Return the official bulk CSV locator for a source-derived title."""

    number = _normalize_title_number(title_number)
    if not number:
        raise ValueError(f"invalid Virginia title number: {title_number!r}")
    return f"https://law.lis.virginia.gov/CSV/CoVTitle_{number}.csv"


def virginia_title_csv_links(
    html: str | bytes,
    *,
    base_url: str = VIRGINIA_LAW_LIBRARY_URL,
) -> list[tuple[str, str, str]]:
    """Derive the complete Code-title CSV catalog from the Law Library page."""

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []

    if isinstance(html, bytes):
        text = html.decode("utf-8", errors="replace")
    else:
        text = str(html or "")
    soup = BeautifulSoup(text, "html.parser")
    container = soup.select_one("article#library") or soup
    rows: list[tuple[str, str, str]] = []
    for anchor in container.find_all("a", href=True):
        href = str(anchor.get("href") or "").strip()
        absolute = urljoin(base_url, href)
        parsed = urlparse(absolute)
        match = _TITLE_CSV_PATH_RE.fullmatch(parsed.path)
        if (
            match is None
            or parsed.scheme.casefold() != "https"
            or (parsed.hostname or "").casefold() != "law.lis.virginia.gov"
        ):
            continue
        number = _normalize_title_number(match.group("title"))
        url = virginia_title_csv_url(number)
        if not number:
            continue
        label_node = anchor.find_parent("tr")
        label_cell = label_node.find("td") if label_node is not None else None
        label = _WS.sub(
            " ",
            label_cell.get_text(" ", strip=True) if label_cell is not None else "",
        ).strip()
        label_match = re.match(
            rf"^Title\s+{re.escape(number)}\s*:\s*(?P<name>.+)$",
            label,
            flags=re.IGNORECASE,
        )
        name = (
            str(label_match.group("name") or "").strip()
            if label_match is not None
            else f"Title {number}"
        )
        rows.append((number, name, url))
    return rows


def _body_to_text(body_html: str) -> str:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return ""
    soup = BeautifulSoup(str(body_html or ""), "html.parser")
    for tag in soup(["script", "style", "nav", "header", "footer"]):
        tag.decompose()
    for tag in soup.select(".sidenote"):
        tag.decompose()
    return _WS.sub(" ", soup.get_text(" ", strip=True)).strip()


def _heading_variant_prefix(title: str) -> str:
    heading = _WS.sub(" ", str(title or "")).strip()
    if not heading.startswith("(") or ")" not in heading:
        return ""
    return heading[: heading.index(")") + 1]


def _source_date(value: str) -> date | None:
    try:
        return datetime.strptime(str(value or "").strip(), "%B %d, %Y").date()
    except ValueError:
        return None


def _calendar_variant(value: str) -> tuple[str, date, str] | None:
    prefix = _heading_variant_prefix(value)
    for role, kind, pattern in (
        ("before", "calendar", _CALENDAR_BEFORE_RE),
        ("after", "calendar", _CALENDAR_AFTER_RE),
        ("before", "compound_later_of", _COMPOUND_CALENDAR_BEFORE_RE),
        ("after", "compound_later_of", _COMPOUND_CALENDAR_AFTER_RE),
    ):
        match = pattern.fullmatch(prefix)
        if match is None:
            continue
        parsed = _source_date(match.group("date"))
        if parsed is not None:
            return role, parsed, kind
    return None


def _taxable_year_variant(value: str) -> tuple[str, date, date] | None:
    prefix = _heading_variant_prefix(value)
    before = _TAXABLE_BEFORE_RE.fullmatch(prefix)
    if before is not None:
        start = _source_date(before.group("start"))
        end = _source_date(before.group("end"))
        if start is not None and end is not None and start < end:
            return "before", start, end
        return None
    after = _TAXABLE_AFTER_RE.fullmatch(prefix)
    if after is None:
        return None
    start = _source_date(after.group("start"))
    return ("after", start, start) if start is not None else None


def _contingent_variant_role(value: str) -> str:
    prefix = _heading_variant_prefix(value)
    if _CONTINGENT_BEFORE_RE.search(prefix):
        return "before"
    if _CONTINGENT_AFTER_RE.search(prefix):
        return "after"
    return ""


def _section_heading_parts(value: str) -> tuple[str, str]:
    normalized = _WS.sub(" ", str(value or "")).strip()
    match = _SECTION_HEADING_RE.fullmatch(normalized)
    if match is None:
        return "", ""
    section_number = str(match.group("section") or "").strip()
    title = str(match.group("title") or "").strip().rstrip(".").strip()
    return section_number, title


def _normalized_branch_title(value: str) -> str:
    return _WS.sub(" ", str(value or "")).strip().rstrip(".").strip().casefold()


def _official_empty_placeholder_csv_row(
    row: Mapping[str, str],
    *,
    expected_title_number: str,
) -> bool:
    """Recognize the one exact current CSV member with no operative body.

    This is deliberately an identity-and-title allowlist, not a general rule
    for empty CSV bodies.  The separately retained current section page must
    also pass :func:`virginia_official_empty_placeholder_evidence` before the
    row can receive a source-status disposition.
    """

    return bool(
        _normalize_title_number(expected_title_number)
        == VIRGINIA_OFFICIAL_EMPTY_PLACEHOLDER_TITLE_NUMBER
        and _normalize_title_number(row.get("TitleNum", ""))
        == VIRGINIA_OFFICIAL_EMPTY_PLACEHOLDER_TITLE_NUMBER
        and str(row.get("TitleName") or "").strip()
        == VIRGINIA_OFFICIAL_EMPTY_PLACEHOLDER_CSV_TITLE_NAME
        and str(row.get("ChapterNum") or "").strip()
        == VIRGINIA_OFFICIAL_EMPTY_PLACEHOLDER_CHAPTER_NUMBER
        and str(row.get("Section") or "").strip()
        == VIRGINIA_OFFICIAL_EMPTY_PLACEHOLDER_SECTION
        and str(row.get("Title") or "").strip()
        == VIRGINIA_OFFICIAL_EMPTY_PLACEHOLDER_SECTION_TITLE
        and not str(row.get("Body") or "").strip()
    )


def virginia_official_empty_placeholder_evidence(
    payload: bytes | str,
) -> dict[str, Any]:
    """Return proof for the one exact official whitespace-only body node.

    The classifier is intentionally narrower than the ordinary current-page
    parser.  It requires the canonical document and branch identity/title, one
    exact official body node containing whitespace only, and no alternate body
    or heading.  Any mismatch returns an empty mapping.
    """

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return {}
    if isinstance(payload, bytes):
        text = payload.decode("utf-8", errors="replace")
        raw_payload = bytes(payload)
    else:
        text = str(payload or "")
        raw_payload = text.encode("utf-8")
    soup = BeautifulSoup(text, "html.parser")
    code_nodes = soup.find_all(id="va_code")
    article_nodes = soup.find_all("article", id="vacode")
    if len(code_nodes) != 1 or len(article_nodes) != 1:
        return {}
    code_node = code_nodes[0]
    article_node = article_nodes[0]
    if code_node.find_parent("article", id="vacode") is not article_node:
        return {}

    document_nodes = soup.find_all("title")
    if len(document_nodes) != 1:
        return {}
    document_identity, document_title = _section_heading_parts(
        document_nodes[0].get_text(" ", strip=True)
    )
    if (
        document_identity != VIRGINIA_OFFICIAL_EMPTY_PLACEHOLDER_SECTION
        or document_title != VIRGINIA_OFFICIAL_EMPTY_PLACEHOLDER_SECTION_TITLE
    ):
        return {}

    headings = list(code_node.find_all(["h1", "h2"]))
    if len(headings) != 1:
        return {}
    branch_identity, branch_title = _section_heading_parts(
        headings[0].get_text(" ", strip=True)
    )
    if branch_identity != document_identity or branch_title != document_title:
        return {}

    body_nodes = list(code_node.select("section.body"))
    article_body_nodes = list(article_node.select("section.body"))
    if (
        len(body_nodes) != 1
        or len(article_body_nodes) != 1
        or article_body_nodes[0] is not body_nodes[0]
    ):
        return {}
    body_node = body_nodes[0]
    if headings[0].find_next_sibling() is not body_node:
        return {}
    classes = {str(value) for value in body_node.get("class") or ()}
    if (
        body_node.name != "section"
        or not {"body", "editable"}.issubset(classes)
        or str(body_node.get("data-table") or "") != "CoV"
        or str(body_node.get("data-field") or "") != "body"
        or re.fullmatch(r"edit\d+", str(body_node.get("id") or "")) is None
    ):
        return {}
    raw_body_markup = body_node.decode_contents()
    body_text = _body_to_text(str(body_node))
    if raw_body_markup.strip() or body_text:
        return {}

    segment_nodes = soup.find_all(id="hidSegments")
    if (
        len(segment_nodes) != 1
        or str(segment_nodes[0].get("value") or "").strip()
        != VIRGINIA_OFFICIAL_EMPTY_PLACEHOLDER_SECTION
    ):
        return {}
    return {
        "source_status": VIRGINIA_OFFICIAL_EMPTY_PLACEHOLDER_STATUS,
        "section_number": document_identity,
        "section_title": document_title,
        "official_operative_body_text_length": 0,
        "official_operative_body_text_sha256": hashlib.sha256(b"").hexdigest(),
        "official_body_node_count": 1,
        "official_alternate_body_count": 0,
        "current_section_page_sha256": hashlib.sha256(raw_payload).hexdigest(),
    }


def _virginia_current_section_selection(
    payload: bytes | str,
) -> _VirginiaCurrentSectionSelection:
    """Select one page branch, binding a multi-branch page to its document title.

    The official renderer ordinarily emits one heading and one body. A small
    number of contingent sections emit multiple sibling ``h2``/``section.body``
    pairs under ``#va_code``. On those pages, the HTML document title is the
    source assertion identifying which displayed branch is current. Ambiguous
    titles, mixed section identities, or malformed branch boundaries return an
    empty selection so callers fail closed.
    """

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return _VirginiaCurrentSectionSelection()
    if isinstance(payload, bytes):
        text = payload.decode("utf-8", errors="replace")
    else:
        text = str(payload or "")
    soup = BeautifulSoup(text, "html.parser")
    node = soup.find(id="va_code") or soup.find("article", id="vacode")
    if node is None:
        return _VirginiaCurrentSectionSelection()

    document_heading = soup.find("title")
    document_value = _WS.sub(
        " ",
        document_heading.get_text(" ", strip=True) if document_heading else "",
    ).strip()
    document_identity, document_title = _section_heading_parts(document_value)

    headings = list(node.find_all(["h1", "h2"]))
    parsed_headings = [
        (heading, *_section_heading_parts(heading.get_text(" ", strip=True)))
        for heading in headings
    ]
    if any(not identity for _heading, identity, _title in parsed_headings):
        return _VirginiaCurrentSectionSelection(branch_count=len(headings))

    if len(parsed_headings) > 1:
        identities = {identity.casefold() for _, identity, _ in parsed_headings}
        if (
            not document_identity
            or not document_title
            or len(identities) != 1
            or document_identity.casefold() not in identities
        ):
            return _VirginiaCurrentSectionSelection(branch_count=len(headings))

        branches: list[tuple[str, str]] = []
        for heading, _identity, branch_title in parsed_headings:
            body_node = heading.find_next_sibling()
            classes = (
                set(body_node.get("class") or [])
                if body_node is not None
                else set()
            )
            if (
                body_node is None
                or body_node.name != "section"
                or "body" not in classes
                or not branch_title
            ):
                return _VirginiaCurrentSectionSelection(branch_count=len(headings))
            branches.append((branch_title, _body_to_text(str(body_node))))

        document_role = _normalized_branch_title(document_title)
        matches = [
            index
            for index, (branch_title, _body) in enumerate(branches)
            if _normalized_branch_title(branch_title) == document_role
        ]
        if len(matches) != 1:
            return _VirginiaCurrentSectionSelection(branch_count=len(headings))
        branch_title, body_text = branches[matches[0]]
        if not body_text:
            return _VirginiaCurrentSectionSelection(branch_count=len(headings))
        return _VirginiaCurrentSectionSelection(
            section_number=document_identity,
            body_text=body_text,
            document_title=document_title,
            branch_title=branch_title,
            branch_count=len(branches),
        )

    if parsed_headings:
        heading, section_number, branch_title = parsed_headings[0]
        if (
            document_identity
            and document_identity.casefold() != section_number.casefold()
        ):
            return _VirginiaCurrentSectionSelection(branch_count=1)
        body_node = heading.find_next_sibling()
        classes = (
            set(body_node.get("class") or []) if body_node is not None else set()
        )
        if body_node is not None and body_node.name == "section" and "body" in classes:
            body_text = _body_to_text(str(body_node))
        else:
            body_soup = BeautifulSoup(str(node), "html.parser")
            body_root = body_soup.find(id="va_code") or body_soup
            for tag in body_root(["script", "style", "nav", "header", "footer"]):
                tag.decompose()
            for tag in body_root.select(".sidenote"):
                tag.decompose()
            for tag in body_root.find_all(["h1", "h2"]):
                tag.decompose()
            body_text = _WS.sub(" ", body_root.get_text(" ", strip=True)).strip()
        if not body_text:
            return _VirginiaCurrentSectionSelection(branch_count=1)
        return _VirginiaCurrentSectionSelection(
            section_number=section_number,
            body_text=body_text,
            document_title=document_title or branch_title,
            branch_title=branch_title,
            branch_count=1,
        )

    if not document_identity:
        return _VirginiaCurrentSectionSelection()
    body_text = _body_to_text(str(node))
    if not body_text:
        return _VirginiaCurrentSectionSelection()
    return _VirginiaCurrentSectionSelection(
        section_number=document_identity,
        body_text=body_text,
        document_title=document_title,
        branch_title=document_title,
        branch_count=1,
    )


def virginia_current_section_body_text(payload: bytes | str) -> str:
    """Return the uniquely selected official current-section body."""

    return _virginia_current_section_selection(payload).body_text


def virginia_current_section_identity(payload: bytes | str) -> str:
    """Extract the section identity asserted by an official current page."""

    return _virginia_current_section_selection(payload).section_number


def _aligned_contingent_current_branch(
    payload: bytes | str,
    *,
    candidates: list[dict[str, Any]],
    observation_date: date | None,
) -> dict[str, Any]:
    """Select a source-evolved official branch without weakening pair identity.

    Virginia's section renderer can be newer than its same-day title CSV.  In
    that case exact body equality is unavailable, but the page still exposes
    one expiration and one effective contingent branch.  Admit the page body
    only when both CSV bodies align most closely and uniquely with the page
    branch carrying the same role.  This rejects a title/body swap while
    allowing bounded compiler edits to either branch.

    One additional, document-selected calendar successor is permitted only
    before its explicit effective date.  The immediately preceding contingent
    effective branch is then the current branch for the observation date.
    """

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return {}
    if len(candidates) != 2:
        return {}
    candidate_roles = [
        _contingent_variant_role(candidate["row"]["Title"])
        for candidate in candidates
    ]
    if sorted(candidate_roles) != ["after", "before"]:
        return {}

    text = (
        payload.decode("utf-8", errors="replace")
        if isinstance(payload, bytes)
        else str(payload or "")
    )
    soup = BeautifulSoup(text, "html.parser")
    node = soup.find(id="va_code") or soup.find("article", id="vacode")
    document_heading = soup.find("title")
    if node is None or document_heading is None:
        return {}
    document_identity, document_title = _section_heading_parts(
        document_heading.get_text(" ", strip=True)
    )
    if not document_identity or not document_title:
        return {}

    branches: list[dict[str, Any]] = []
    for heading in node.find_all(["h1", "h2"]):
        section_number, branch_title = _section_heading_parts(
            heading.get_text(" ", strip=True)
        )
        body_node = heading.find_next_sibling()
        classes = (
            set(body_node.get("class") or []) if body_node is not None else set()
        )
        if (
            section_number.casefold() != document_identity.casefold()
            or not branch_title
            or body_node is None
            or body_node.name != "section"
            or "body" not in classes
        ):
            return {}
        body_text = _body_to_text(str(body_node))
        if not body_text:
            return {}
        branches.append(
            {
                "title": branch_title,
                "body_text": body_text,
                "role": _contingent_variant_role(branch_title),
            }
        )
    if len(branches) < 2:
        return {}

    document_matches = [
        index
        for index, branch in enumerate(branches)
        if _normalized_branch_title(branch["title"])
        == _normalized_branch_title(document_title)
    ]
    if len(document_matches) != 1:
        return {}
    document_index = document_matches[0]

    contingent_indices = {
        role: [
            index
            for index, branch in enumerate(branches)
            if branch["role"] == role
        ]
        for role in ("before", "after")
    }
    if any(len(indices) != 1 for indices in contingent_indices.values()):
        return {}
    role_to_branch = {
        role: indices[0] for role, indices in contingent_indices.items()
    }

    alignment_scores: dict[str, float] = {}
    for candidate, role in zip(candidates, candidate_roles, strict=True):
        candidate_body = str(candidate.get("body_text") or "")
        if not candidate_body:
            return {}
        scores = [
            SequenceMatcher(
                None,
                candidate_body,
                str(branch["body_text"]),
                autojunk=False,
            ).ratio()
            for branch in branches
        ]
        best_score = max(scores)
        same_role_index = role_to_branch[role]
        if (
            best_score < 0.95
            or scores[same_role_index] != best_score
            or scores.count(best_score) != 1
        ):
            return {}
        alignment_scores[role] = best_score

    extra_indices = sorted(
        set(range(len(branches))) - set(role_to_branch.values())
    )
    if not extra_indices:
        selected_branch_index = document_index
        selected_role = str(branches[selected_branch_index]["role"] or "")
        if selected_role not in role_to_branch:
            return {}
        selection_kind = "official_document_contingent_role_alignment"
    else:
        if (
            len(extra_indices) != 1
            or observation_date is None
            or document_index != extra_indices[0]
            or document_index != len(branches) - 1
            or document_index == 0
        ):
            return {}
        calendar_variant = _calendar_variant(branches[document_index]["title"])
        if (
            calendar_variant is None
            or calendar_variant[0] != "after"
            or calendar_variant[2] != "calendar"
            or observation_date >= calendar_variant[1]
        ):
            return {}
        selected_branch_index = document_index - 1
        selected_role = str(branches[selected_branch_index]["role"] or "")
        if selected_role != "after":
            return {}
        selection_kind = "pre_effective_calendar_successor_contingent_alignment"

    selected_candidate_index = candidate_roles.index(selected_role)
    selected_branch = branches[selected_branch_index]
    return {
        "selected_candidate_index": selected_candidate_index,
        "selected_role": selected_role,
        "section_number": document_identity,
        "body_text": selected_branch["body_text"],
        "document_title": document_title,
        "branch_title": selected_branch["title"],
        "branch_count": len(branches),
        "selection_kind": selection_kind,
        "alignment_scores": alignment_scores,
    }


def _terminal_disposition(title: str, body_text: str) -> str:
    heading = _WS.sub(" ", str(title or "")).strip(" \t\r\n.-:;[]()")
    match = _TERMINAL_RE.match(heading)
    if match is not None:
        return match.group("kind").lower()
    body = _WS.sub(" ", str(body_text or "")).strip()
    match = _TERMINAL_RE.match(body)
    if match is not None and len(body) <= 1_000:
        return match.group("kind").lower()
    return ""


def _variant_context(row: dict[str, str]) -> str:
    return " ".join(
        str(row.get(field) or "")
        for field in (
            "SubTitleName",
            "PartName",
            "ChapterName",
            "ArticleName",
            "SubPartName",
            "Title",
        )
    )


def _row_digest(row: dict[str, str]) -> str:
    joined = "\x1f".join(str(row.get(field) or "") for field in _CSV_FIELDS)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def _section_url(title_number: str, chapter_number: str, section_number: str) -> str:
    title = quote(title_number, safe=".")
    chapter = quote(chapter_number, safe=".")
    section = quote(section_number, safe=".:-")
    if chapter:
        return (
            "https://law.lis.virginia.gov/vacode/"
            f"title{title}/chapter{chapter}/section{section}/"
        )
    return f"https://law.lis.virginia.gov/vacode/{section}/"


def _read_virginia_title_csv(payload: bytes | str) -> list[dict[str, str]]:
    if isinstance(payload, bytes):
        try:
            text = payload.decode("utf-8-sig", errors="strict")
        except UnicodeError as exc:
            raise ValueError("Virginia title CSV is not valid UTF-8") from exc
    else:
        text = str(payload or "")
    if "\x00" in text:
        raise ValueError("Virginia title CSV contains NUL bytes")
    try:
        reader = csv.DictReader(io.StringIO(text, newline=""))
        if tuple(reader.fieldnames or ()) != _CSV_FIELDS:
            raise ValueError("Virginia title CSV schema does not match official fields")
        return list(reader)
    except csv.Error as exc:
        raise ValueError("Virginia title CSV is malformed") from exc


def virginia_current_section_frontier(
    payload: bytes | str,
    *,
    expected_title_number: str,
) -> list[tuple[str, str, str]]:
    """Derive ordered current-page selectors and missing-body hydration inputs."""

    expected_number = _normalize_title_number(expected_title_number)
    if not expected_number:
        raise ValueError("expected_title_number must be a Virginia title number")
    groups: dict[str, list[dict[str, str]]] = {}
    for raw_row in _read_virginia_title_csv(payload):
        if None in raw_row or any(value is None for value in raw_row.values()):
            continue
        row = {field: str(raw_row.get(field) or "").strip() for field in _CSV_FIELDS}
        if _normalize_title_number(row["TitleNum"]) != expected_number:
            continue
        section_number = row["Section"]
        if (
            not section_number
            or _SECTION_RE.fullmatch(section_number) is None
            or not section_number.casefold().startswith(
                expected_number.casefold() + "-"
            )
        ):
            continue
        groups.setdefault(section_number.casefold(), []).append(row)

    frontier: list[tuple[str, str, str]] = []
    for candidates in groups.values():
        purpose = ""
        if len(candidates) == 1:
            row = candidates[0]
            body_text = _body_to_text(row["Body"])
            if (
                row["Title"]
                and not body_text
                and not _terminal_disposition(row["Title"], body_text)
            ):
                purpose = (
                    "official_empty_placeholder_witness"
                    if _official_empty_placeholder_csv_row(
                        row,
                        expected_title_number=expected_number,
                    )
                    else "operative_body_hydration"
                )
        elif len(candidates) == 2:
            roles = [_contingent_variant_role(row["Title"]) for row in candidates]
            if sorted(roles) == ["after", "before"]:
                purpose = "contingent_variant_selector"
        if not purpose:
            continue
        section_number = candidates[0]["Section"]
        chapter_numbers = {row["ChapterNum"] for row in candidates}
        if len(chapter_numbers) != 1:
            continue
        frontier.append(
            (
                section_number,
                _section_url(
                    expected_number,
                    candidates[0]["ChapterNum"],
                    section_number,
                ),
                purpose,
            )
        )
    return frontier


def virginia_contingent_section_frontier(
    payload: bytes | str,
    *,
    expected_title_number: str,
) -> list[tuple[str, str]]:
    """Compatibility view containing only contingent selector pages."""

    return [
        (section_number, source_url)
        for section_number, source_url, purpose in virginia_current_section_frontier(
            payload,
            expected_title_number=expected_title_number,
        )
        if purpose == "contingent_variant_selector"
    ]


def parse_virginia_title_csv_closure(
    payload: bytes | str,
    *,
    expected_title_number: str,
    expected_title_name: str = "",
    code_name: str = "Code of Virginia",
    source_bundle_url: str = "",
    observation_date: date | None = None,
    current_section_pages: Mapping[str, bytes | str] | None = None,
) -> VirginiaTitleCsvParseResult:
    """Parse and exactly classify every physical row in a title CSV.

    Calendar and taxable-year pairs are selected against the retained source
    observation date.  A genuinely contingent pair is selected only when its
    separately retained canonical section page body matches exactly one CSV
    branch.  Every physical row receives one and only one disposition.
    """

    expected_number = _normalize_title_number(expected_title_number)
    if not expected_number:
        raise ValueError("expected_title_number must be a Virginia title number")
    physical_rows = _read_virginia_title_csv(payload)
    current_pages = {
        str(url or "").strip(): body
        for url, body in dict(current_section_pages or {}).items()
        if str(url or "").strip()
    }
    used_current_pages: set[str] = set()

    title_name = str(expected_title_name or "").strip()
    terminal_records: list[dict[str, Any]] = []
    source_status_records: list[dict[str, Any]] = []
    unclassified: list[dict[str, Any]] = []
    candidates_by_section: dict[str, list[dict[str, Any]]] = {}
    for ordinal, raw_row in enumerate(physical_rows, start=1):
        if None in raw_row or any(value is None for value in raw_row.values()):
            unclassified.append(
                {"ordinal": ordinal, "reason": "malformed_csv_record"}
            )
            continue
        row = {field: str(raw_row.get(field) or "").strip() for field in _CSV_FIELDS}
        observed_number = _normalize_title_number(row["TitleNum"])
        section_number = row["Section"]
        if observed_number != expected_number:
            unclassified.append(
                {
                    "ordinal": ordinal,
                    "reason": "title_identity_mismatch",
                    "expected": expected_number,
                    "observed": observed_number,
                }
            )
            continue
        if not title_name:
            title_name = row["TitleName"]
        if (
            not section_number
            or _SECTION_RE.fullmatch(section_number) is None
            or not section_number.casefold().startswith(expected_number.casefold() + "-")
        ):
            unclassified.append(
                {
                    "ordinal": ordinal,
                    "reason": "invalid_section_identity",
                    "section_number": section_number,
                }
            )
            continue
        body_text = _body_to_text(row["Body"])
        disposition = _terminal_disposition(row["Title"], body_text)
        candidate = {
            "ordinal": ordinal,
            "row": row,
            "body_text": body_text,
            "disposition": disposition,
            "record_sha256": _row_digest(row),
        }
        if not disposition and not row["Title"]:
            unclassified.append(
                {
                    "ordinal": ordinal,
                    "reason": "operative_record_lacks_heading",
                    "section_number": section_number,
                }
            )
            continue
        candidates_by_section.setdefault(section_number.casefold(), []).append(candidate)

    statutes: list[NormalizedStatute] = []
    seen_statute_ids: set[str] = set()
    for candidates in candidates_by_section.values():
        variant_selection = ""
        variant_metadata: dict[str, Any] = {}
        if len(candidates) == 1:
            selected = candidates[0]
            if selected["disposition"]:
                terminal_records.append(
                    {
                        "ordinal": selected["ordinal"],
                        "section_number": selected["row"]["Section"],
                        "disposition": selected["disposition"],
                        "record_sha256": selected["record_sha256"],
                    }
                )
                continue
            excluded_variants: list[dict[str, Any]] = []
            if not selected["body_text"]:
                section_number = selected["row"]["Section"]
                current_url = _section_url(
                    expected_number,
                    selected["row"]["ChapterNum"],
                    section_number,
                )
                current_payload = current_pages.get(current_url)
                placeholder_evidence = (
                    virginia_official_empty_placeholder_evidence(current_payload)
                    if current_payload is not None
                    else {}
                )
                placeholder_csv_concordant = _official_empty_placeholder_csv_row(
                    selected["row"],
                    expected_title_number=expected_number,
                ) and str(expected_title_name or "").strip() in {
                    "",
                    VIRGINIA_OFFICIAL_EMPTY_PLACEHOLDER_TITLE_NAME,
                }
                expected_bundle_url = virginia_title_csv_url(expected_number)
                observed_bundle_url = str(
                    source_bundle_url or expected_bundle_url
                ).strip()
                if placeholder_evidence and placeholder_csv_concordant:
                    if observed_bundle_url != expected_bundle_url:
                        unclassified.append(
                            {
                                "ordinal": selected["ordinal"],
                                "reason": (
                                    "official_empty_placeholder_catalog_mismatch"
                                ),
                                "section_number": section_number,
                            }
                        )
                        continue
                    page_sha256 = hashlib.sha256(
                        bytes(current_payload)
                        if isinstance(current_payload, bytes)
                        else str(current_payload).encode("utf-8")
                    ).hexdigest()
                    if page_sha256 != str(
                        placeholder_evidence.get("current_section_page_sha256")
                        or ""
                    ):
                        unclassified.append(
                            {
                                "ordinal": selected["ordinal"],
                                "reason": (
                                    "official_empty_placeholder_page_digest_mismatch"
                                ),
                                "section_number": section_number,
                            }
                        )
                        continue
                    source_status_records.append(
                        {
                            "ordinal": selected["ordinal"],
                            "section_number": section_number,
                            "section_title": selected["row"]["Title"],
                            "source_status": (
                                VIRGINIA_OFFICIAL_EMPTY_PLACEHOLDER_STATUS
                            ),
                            "source_record_sha256": selected["record_sha256"],
                            "source_bundle_url": expected_bundle_url,
                            "source_csv_body_text_length": 0,
                            "source_csv_body_text_sha256": hashlib.sha256(
                                b""
                            ).hexdigest(),
                            "current_section_page_url": current_url,
                            **placeholder_evidence,
                            "source_status_basis": (
                                "concordant_current_official_csv_and_section_page"
                            ),
                        }
                    )
                    used_current_pages.add(current_url)
                    continue
                current_identity = (
                    virginia_current_section_identity(current_payload)
                    if current_payload is not None
                    else ""
                )
                current_text = (
                    virginia_current_section_body_text(current_payload)
                    if current_payload is not None
                    else ""
                )
                if current_payload is None:
                    reason = "operative_current_section_page_missing"
                elif current_identity.casefold() != section_number.casefold():
                    reason = "operative_current_section_identity_mismatch"
                elif not current_text:
                    reason = "operative_current_section_body_empty"
                else:
                    reason = ""
                if reason:
                    unclassified.append(
                        {
                            "ordinal": selected["ordinal"],
                            "reason": reason,
                            "section_number": section_number,
                        }
                    )
                    continue
                selected["body_text"] = current_text
                used_current_pages.add(current_url)
                variant_metadata = {
                    "current_section_page_url": current_url,
                    "current_section_page_sha256": hashlib.sha256(
                        bytes(current_payload)
                        if isinstance(current_payload, bytes)
                        else str(current_payload).encode("utf-8")
                    ).hexdigest(),
                    "current_section_body_sha256": hashlib.sha256(
                        current_text.encode("utf-8")
                    ).hexdigest(),
                    "current_section_selection": "official_missing_csv_body_hydration",
                }
        elif all(candidate["disposition"] for candidate in candidates):
            for candidate in candidates:
                terminal_records.append(
                    {
                        "ordinal": candidate["ordinal"],
                        "section_number": candidate["row"]["Section"],
                        "disposition": candidate["disposition"],
                        "record_sha256": candidate["record_sha256"],
                    }
                )
            continue
        elif any(candidate["disposition"] for candidate in candidates):
            unclassified.extend(
                {
                    "ordinal": candidate["ordinal"],
                    "reason": "mixed_terminal_and_operative_duplicate_identity",
                    "section_number": candidate["row"]["Section"],
                }
                for candidate in candidates
            )
            continue
        else:
            if len(candidates) != 2:
                unclassified.extend(
                    {
                        "ordinal": candidate["ordinal"],
                        "reason": "duplicate_variant_cardinality_not_two",
                        "section_number": candidate["row"]["Section"],
                    }
                    for candidate in candidates
                )
                continue

            selected = None
            excluded = None
            exclusion_disposition = ""
            contingent_roles = [
                _contingent_variant_role(candidate["row"]["Title"])
                for candidate in candidates
            ]
            calendar_variants = [
                _calendar_variant(candidate["row"]["Title"])
                for candidate in candidates
            ]
            taxable_variants = [
                _taxable_year_variant(candidate["row"]["Title"])
                for candidate in candidates
            ]
            if any(contingent_roles):
                if sorted(contingent_roles) != ["after", "before"]:
                    reason = "incomplete_or_ambiguous_contingent_variant_pair"
                else:
                    section_number = candidates[0]["row"]["Section"]
                    chapter_numbers = {
                        candidate["row"]["ChapterNum"] for candidate in candidates
                    }
                    current_url = (
                        _section_url(
                            expected_number,
                            candidates[0]["row"]["ChapterNum"],
                            section_number,
                        )
                        if len(chapter_numbers) == 1
                        else ""
                    )
                    current_payload = current_pages.get(current_url)
                    current_selection = (
                        _virginia_current_section_selection(current_payload)
                        if current_payload is not None
                        else _VirginiaCurrentSectionSelection()
                    )
                    current_text = current_selection.body_text
                    current_identity = current_selection.section_number
                    matches = [
                        index
                        for index, candidate in enumerate(candidates)
                        if current_text and current_text == candidate["body_text"]
                    ]
                    title_matches = [
                        index
                        for index, candidate in enumerate(candidates)
                        if _normalized_branch_title(current_selection.branch_title)
                        == _normalized_branch_title(candidate["row"]["Title"])
                    ]
                    evolved_alignment = (
                        _aligned_contingent_current_branch(
                            current_payload,
                            candidates=candidates,
                            observation_date=observation_date,
                        )
                        if current_payload is not None and len(matches) != 1
                        else {}
                    )
                    if not current_url or current_payload is None:
                        reason = "contingent_current_section_page_missing"
                    elif current_identity.casefold() != section_number.casefold():
                        reason = "contingent_current_section_identity_mismatch"
                    elif len(matches) != 1 and not evolved_alignment:
                        reason = "contingent_current_section_body_not_unique"
                    elif len(matches) == 1 and current_selection.branch_count > 1 and (
                        len(title_matches) != 1 or title_matches[0] != matches[0]
                    ):
                        reason = "contingent_current_section_title_body_mismatch"
                    else:
                        selected_index = (
                            int(evolved_alignment["selected_candidate_index"])
                            if evolved_alignment
                            else matches[0]
                        )
                        excluded_index = 1 - selected_index
                        selected = candidates[selected_index]
                        excluded = candidates[excluded_index]
                        csv_selected_body = str(selected["body_text"] or "")
                        selected_role = contingent_roles[selected_index]
                        excluded_role = contingent_roles[excluded_index]
                        exclusion_disposition = (
                            "future_contingent_variant"
                            if excluded_role == "after"
                            else "superseded_contingent_variant"
                        )
                        if evolved_alignment:
                            selected["body_text"] = str(
                                evolved_alignment["body_text"]
                            )
                            current_text = selected["body_text"]
                            current_selection = _VirginiaCurrentSectionSelection(
                                section_number=str(
                                    evolved_alignment["section_number"]
                                ),
                                body_text=current_text,
                                document_title=str(
                                    evolved_alignment["document_title"]
                                ),
                                branch_title=str(evolved_alignment["branch_title"]),
                                branch_count=int(
                                    evolved_alignment["branch_count"]
                                ),
                            )
                            variant_selection = str(
                                evolved_alignment["selection_kind"]
                            )
                        else:
                            variant_selection = (
                                "canonical_current_section_body_match"
                            )
                        used_current_pages.add(current_url)
                        variant_metadata = {
                            "contingent_current_page_url": current_url,
                            "contingent_current_page_sha256": hashlib.sha256(
                                bytes(current_payload)
                                if isinstance(current_payload, bytes)
                                else str(current_payload).encode("utf-8")
                            ).hexdigest(),
                            "contingent_current_body_sha256": hashlib.sha256(
                                current_text.encode("utf-8")
                            ).hexdigest(),
                            "contingent_current_branch_count": (
                                current_selection.branch_count
                            ),
                            "contingent_current_document_title": (
                                current_selection.document_title
                            ),
                            "contingent_current_branch_title": (
                                current_selection.branch_title
                            ),
                            "contingent_selected_role": selected_role,
                        }
                        if evolved_alignment:
                            variant_metadata.update(
                                {
                                    "contingent_body_alignment": (
                                        "mutual_unique_role_similarity_v1"
                                    ),
                                    "contingent_csv_body_sha256": hashlib.sha256(
                                        csv_selected_body.encode("utf-8")
                                    ).hexdigest(),
                                }
                            )
                        reason = ""
            elif any(calendar_variants):
                roles = [
                    variant[0] if variant is not None else ""
                    for variant in calendar_variants
                ]
                switch_dates = {
                    variant[1]
                    for variant in calendar_variants
                    if variant is not None
                }
                kinds = {
                    variant[2]
                    for variant in calendar_variants
                    if variant is not None
                }
                if (
                    sorted(roles) != ["after", "before"]
                    or len(switch_dates) != 1
                    or len(kinds) != 1
                ):
                    reason = "incomplete_or_mismatched_calendar_variant_pair"
                elif observation_date is None:
                    reason = "calendar_variant_observation_date_missing"
                else:
                    switch_date = next(iter(switch_dates))
                    kind = next(iter(kinds))
                    if kind == "compound_later_of" and observation_date >= switch_date:
                        reason = "compound_calendar_variant_trigger_not_source_resolved"
                    else:
                        selected_role = (
                            "before" if observation_date < switch_date else "after"
                        )
                        selected_index = roles.index(selected_role)
                        excluded_index = 1 - selected_index
                        selected = candidates[selected_index]
                        excluded = candidates[excluded_index]
                        exclusion_disposition = (
                            "future_calendar_variant"
                            if selected_role == "before"
                            else "expired_calendar_variant"
                        )
                        variant_selection = "source_observation_date"
                        variant_metadata = {
                            "calendar_variant_kind": kind,
                            "calendar_switch_not_before": switch_date.isoformat(),
                            "source_observation_date": observation_date.isoformat(),
                        }
                        reason = ""
            elif any(taxable_variants):
                roles = [
                    variant[0] if variant is not None else ""
                    for variant in taxable_variants
                ]
                before = next(
                    (
                        variant
                        for variant in taxable_variants
                        if variant is not None and variant[0] == "before"
                    ),
                    None,
                )
                after = next(
                    (
                        variant
                        for variant in taxable_variants
                        if variant is not None and variant[0] == "after"
                    ),
                    None,
                )
                if (
                    sorted(roles) != ["after", "before"]
                    or before is None
                    or after is None
                    or before[2] != after[1]
                ):
                    reason = "incomplete_or_mismatched_taxable_year_variant_pair"
                elif observation_date is None:
                    reason = "taxable_year_variant_observation_date_missing"
                elif observation_date < before[1]:
                    reason = "no_taxable_year_variant_effective_on_observation_date"
                else:
                    selected_role = (
                        "before" if observation_date < before[2] else "after"
                    )
                    selected_index = roles.index(selected_role)
                    excluded_index = 1 - selected_index
                    selected = candidates[selected_index]
                    excluded = candidates[excluded_index]
                    exclusion_disposition = (
                        "future_taxable_year_variant"
                        if selected_role == "before"
                        else "expired_taxable_year_variant"
                    )
                    variant_selection = "source_observation_date_taxable_year"
                    variant_metadata = {
                        "source_observation_date": observation_date.isoformat(),
                        "taxable_year_switch_date": before[2].isoformat(),
                    }
                    reason = ""
            else:
                reason = "unresolved_duplicate_section_identity"

            if selected is None or excluded is None:
                unclassified.extend(
                    {
                        "ordinal": candidate["ordinal"],
                        "reason": reason,
                        "section_number": candidate["row"]["Section"],
                    }
                    for candidate in candidates
                )
                continue
            exclusion = {
                "ordinal": excluded["ordinal"],
                "section_number": excluded["row"]["Section"],
                "disposition": exclusion_disposition,
                "record_sha256": excluded["record_sha256"],
                "variant_selection": variant_selection,
            }
            terminal_records.append(exclusion)
            excluded_variants = [dict(exclusion)]

        row = selected["row"]
        section_number = row["Section"]
        statute_id = f"{code_name} § {section_number}"
        folded_id = statute_id.casefold()
        if folded_id in seen_statute_ids:
            unclassified.append(
                {
                    "ordinal": selected["ordinal"],
                    "reason": "duplicate_normalized_statute_identity",
                    "section_number": section_number,
                }
            )
            continue
        seen_statute_ids.add(folded_id)
        source_url = _section_url(expected_number, row["ChapterNum"], section_number)
        structured_data: dict[str, Any] = {
            "source_kind": "official_virginia_title_csv",
            "source_authority_class": "official",
            "discovery_method": "official_law_library_title_csv_frontier",
            "skip_hydrate": True,
            "source_bundle_url": source_bundle_url
            or virginia_title_csv_url(expected_number),
            "source_record_ordinal": selected["ordinal"],
            "source_record_sha256": selected["record_sha256"],
            "source_hierarchy": {
                field: row[field]
                for field in _CSV_FIELDS[:12]
                if row[field]
            },
        }
        if variant_metadata:
            structured_data.update(variant_metadata)
        if excluded_variants:
            structured_data.update(
                {
                    "effective_variant_count": 1 + len(excluded_variants),
                    "effective_variant_selection": variant_selection,
                    "effective_variant_exclusions": excluded_variants,
                }
            )
        statutes.append(
            NormalizedStatute(
                state_code="VA",
                state_name="Virginia",
                statute_id=statute_id,
                code_name=code_name,
                title_number=expected_number,
                title_name=title_name or row["TitleName"] or f"Title {expected_number}",
                chapter_number=row["ChapterNum"] or None,
                chapter_name=row["ChapterName"] or None,
                section_number=section_number,
                section_name=row["Title"][:200],
                full_text=selected["body_text"],
                source_url=source_url,
                official_cite=f"Va. Code Ann. § {section_number}",
                metadata=StatuteMetadata(),
                structured_data=structured_data,
            )
        )

    for unused_url in sorted(set(current_pages) - used_current_pages):
        unclassified.append(
            {
                "reason": "unused_current_section_page",
                "source_url": unused_url,
            }
        )
    source_count = len(physical_rows)
    closed = bool(
        source_count > 0
        and not unclassified
        and source_count
        == len(statutes) + len(terminal_records) + len(source_status_records)
    )
    if source_count == 0:
        unclassified.append({"reason": "empty_title_csv"})
    return VirginiaTitleCsvParseResult(
        title_number=expected_number,
        title_name=title_name or f"Title {expected_number}",
        source_record_count=source_count,
        statutes=statutes,
        terminal_records=terminal_records,
        source_status_records=source_status_records,
        unclassified_records=unclassified,
        closed=closed,
    )


__all__ = [
    "VIRGINIA_LAW_LIBRARY_URL",
    "VIRGINIA_OFFICIAL_EMPTY_PLACEHOLDER_SECTION",
    "VIRGINIA_OFFICIAL_EMPTY_PLACEHOLDER_SECTION_TITLE",
    "VIRGINIA_OFFICIAL_EMPTY_PLACEHOLDER_STATUS",
    "VIRGINIA_OFFICIAL_EMPTY_PLACEHOLDER_URL",
    "VirginiaTitleCsvParseResult",
    "parse_virginia_title_csv_closure",
    "virginia_contingent_section_frontier",
    "virginia_current_section_body_text",
    "virginia_current_section_frontier",
    "virginia_current_section_identity",
    "virginia_official_empty_placeholder_evidence",
    "virginia_title_csv_links",
    "virginia_title_csv_url",
]
