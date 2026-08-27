"""Exact official Oregon Laws overlay for the static 2025 ORS edition.

The Oregon Revised Statutes page is an edition, not a currentness feed.  This
module closes the bounded session-law delta that was published after that
edition: the 2025 first special session and the 2026 regular session.  It does
not guess chapter URLs.  The URLs and source-declared counts are read from the
official SharePoint group inventories exposed by ``Laws_Mobile.aspx``.
"""

from __future__ import annotations

import os
import re
import subprocess
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote, unquote, urljoin, urlsplit, urlunsplit

from .base_scraper import NormalizedStatute, StatuteMetadata
from .retained_replay_network_guard import trusted_pdftotext_executable

BASE = "https://www.oregonlegislature.gov"
OFFICIAL_HOST = "www.oregonlegislature.gov"
LAWS_MOBILE_URL = f"{BASE}/bills_laws/Pages/Laws_Mobile.aspx"
LAW_LIST_GUID = "{88BF04C7-3C52-4FFA-9717-94016EC3B24E}"
LAW_VIEW_GUID = "{66C431F3-786B-45B2-8A42-583FE8ED7C3B}"
SUPPLEMENT_VIEW_GUID = "{4BB3B97A-3661-46B2-A304-3DCFA9C8F6C9}"
RESOLUTION_VIEW_GUID = "{623EAA30-F2E6-4B93-95D8-89F723E580BC}"
LAW_GROUP_ENDPOINT = f"{BASE}/bills_laws/_layouts/15/inplview.aspx"

_COUNT_RE = re.compile(r"\((?P<count>\d+)\)\s*$")
_SPACE_RE = re.compile(r"\s+")
_SECTION_HEADING_RE = re.compile(r"(?m)^[ \t]*SECTION[ \t]+(?P<number>\d+[A-Za-z]?)\.")
_LOOSE_SECTION_HEADING_RE = re.compile(
    r"(?m)^[ \t]*SECTION[ \t]+(?P<number>\d+[A-Za-z]?)(?P<ending>\S?)"
)
_ORS_CITE_RE = re.compile(r"\b(?P<cite>\d{1,3}\.\d{3}[A-Za-z]?)\b")
_DATE_RE = re.compile(
    r"\b(?:January|February|March|April|May|June|July|August|September|"
    r"October|November|December)\s+\d{1,2},\s+\d{4}\b",
    re.IGNORECASE,
)
_TRAILER_START_RE = re.compile(
    r"(?m)^[ \t]*(?:Approved by the Governor|Became law without (?:the )?"
    r"Governor(?:'s)? signature)\b"
)
_PAGE_HEADER_RE = re.compile(
    r"^(?:OREGON LAWS \d{4}(?: SPECIAL SESSION)?\s+Chap\.\s*\d+|"
    r"Chap\.\s*\d+\s+OREGON LAWS \d{4}(?: SPECIAL SESSION)?)$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class OregonLawSession:
    """One source-declared current Oregon Laws group."""

    key: str
    label: str
    year: int
    declared_chapter_count: int
    group_string: str
    inventory_url: str
    filename_prefix: str
    official_cite_session: str


@dataclass(frozen=True)
class OregonLawChapterLocator:
    """One exact chapter locator, including the source-declared HTTP form."""

    session_key: str
    session_label: str
    year: int
    chapter_number: int
    chapter_label: str
    declared_url: str
    canonical_url: str


@dataclass(frozen=True)
class OregonLawDocumentMetadata:
    """Document-wide enactment metadata printed in an Oregon Laws PDF."""

    bill_number: str
    approved_event: str
    approved_date: str
    filed_date: str
    effective_date: str


@dataclass(frozen=True)
class OregonLawSection:
    """One complete, independently indexable ``SECTION N[letter].`` block."""

    number: str
    text: str
    amended_ors_citations: tuple[str, ...]
    repealed_ors_citations: tuple[str, ...]
    added_to_ors_chapters: tuple[str, ...]
    operative_semantics: tuple[Mapping[str, Any], ...]
    effective_semantics: tuple[Mapping[str, Any], ...]
    sunset_semantics: tuple[Mapping[str, Any], ...]
    conditional_semantics: tuple[str, ...]
    emergency_clause: bool


@dataclass(frozen=True)
class ParsedOregonLaw:
    """A validated official chapter and all of its untruncated sections."""

    locator: OregonLawChapterLocator
    metadata: OregonLawDocumentMetadata
    sections: tuple[OregonLawSection, ...]


@dataclass(frozen=True)
class OregonSessionEvidenceLocator:
    """One exact official table or expressly excluded resolution locator."""

    session_key: str
    document_kind: str
    identity: str
    declared_label: str
    declared_url: str
    canonical_url: str


@dataclass(frozen=True)
class OregonEnactedBill:
    """One bill disposition printed in an official Oregon Laws enacted table."""

    session_key: str
    bill_number: str
    disposition: str
    chapter_number: int | None
    effective_date: str | None
    notes: tuple[str, ...]


@dataclass(frozen=True)
class OregonAffectedReference:
    """One independently identified row from an official A&R table."""

    session_key: str
    table_kind: str
    target: str
    action: str
    law_chapter_number: int
    law_section_number: str
    bill_number: str
    emergency_marker: str
    raw_text: str


@dataclass(frozen=True)
class OregonSessionEvidenceReconciliation:
    """Exact joins from the two tables back to retained chapter sections."""

    enacted_by_chapter: Mapping[tuple[str, int], OregonEnactedBill]
    actions_by_section: Mapping[
        tuple[str, int, str], tuple[OregonAffectedReference, ...]
    ]
    summary: Mapping[str, Any]


_SESSION_SPECS = (
    {
        "key": "2025_special_1",
        "label": "2025 Special 1",
        "year": 2025,
        "count": 2,
        "group_string": ";#2025 Special 1;#",
        "filename_prefix": "2025S1OrLaw",
        "official_cite_session": "2025 (Spec. Sess. 1)",
    },
    {
        "key": "2026_regular",
        "label": "2026 Regular",
        "year": 2026,
        "count": 142,
        "group_string": ";#2026 Regular;#",
        "filename_prefix": "2026orlaw",
        "official_cite_session": "2026",
    },
)

_SUPPLEMENT_SPECS: Mapping[str, tuple[tuple[str, str, str], ...]] = {
    "2025_special_1": (
        ("foreword", "2025S1Foreword.pdf", "Oregon Laws Foreword"),
        (
            "enacted_table",
            "2025S1OrLawEnacted.pdf",
            "Senate and House Bills Enacted",
        ),
        ("affected_table", "2025S1OrLawAR.pdf", "Statutes Affected by Measures"),
    ),
    "2026_regular": (
        (
            "publication_authority",
            "2026OrLawAuthorizing.pdf",
            "Law Authorizing this Publication",
        ),
        ("foreword", "2026OrLawForeword.pdf", "Oregon Laws Foreword"),
        ("index", "2026OrLawIndex.pdf", "Oregon Laws Index"),
        (
            "enacted_table",
            "2026OrLawEnacted.pdf",
            "Senate and House Bills Enacted",
        ),
        ("affected_table", "2026OrLawAR.pdf", "Statutes Affected by Measures"),
    ),
}

_RESOLUTION_SPECS: Mapping[str, tuple[tuple[str, str], ...]] = {
    "2025_special_1": (("2025S1hcr0051.pdf", "House Concurrent Resolution 0051"),),
    "2026_regular": (
        ("2026hcr0201.pdf", "House Concurrent Resolution 0201"),
        ("2026hcr0202.pdf", "House Concurrent Resolution 0202"),
        ("2026scr0201.pdf", "Senate Concurrent Resolution 0201"),
        ("2026scr0203.pdf", "Senate Concurrent Resolution 0203"),
        ("2026scr0204.pdf", "Senate Concurrent Resolution 0204"),
        ("2026scr0205.pdf", "Senate Concurrent Resolution 0205"),
        ("2026scr0206.pdf", "Senate Concurrent Resolution 0206"),
        ("2026scr0207.pdf", "Senate Concurrent Resolution 0207"),
        ("2026scr0209.pdf", "Senate Concurrent Resolution 0209"),
    ),
}

_AFFECTED_EXPECTATIONS: Mapping[str, Mapping[str, Mapping[str, int]]] = {
    "2025_special_1": {
        "ors": {"A": 56, "R": 4, "Add": 5},
        "uncodified": {"A": 1, "R": 1, "Add": 0},
    },
    "2026_regular": {
        "ors": {"A": 504, "R": 15, "Add": 69},
        "uncodified": {"A": 81, "R": 9, "Add": 2},
    },
}

_ENACTED_EXPECTATIONS: Mapping[str, tuple[int, int]] = {
    "2025_special_1": (2, 0),
    "2026_regular": (142, 1),
}

_NAMED_ORS_RANGE_TARGETS: Mapping[str, str] = {
    "Ch. 731 to Ch. 750": "Insurance Code",
    "Ch. 801 to Ch. 826": "Oregon Vehicle Code",
}

_ACTION_ROW_RE = re.compile(
    r"\b(?P<action>Add|A|R)\s+c\.\s*(?P<chapter>\d+)\s+"
    r"§\s*(?P<section>\d+[A-Za-z]?(?:-\d+[A-Za-z]?)?)\s+"
    r"\((?P<bill>(?:HB|SB)\s*\d+(?:\s+(?:OV|OVP))?|BM\s*\d+)\)"
    r"(?:\s+(?P<emergency>E\*?))?"
)
_ENACTED_ROW_RE = re.compile(
    r"(?P<number>\d{4})\s*\.{2,}\s*(?P<chapter>\d+)?\s*\.{2,}\s*"
    r"(?P<status>\d{2}/\d{2}/\d{2}|Vetoed)\b",
    re.IGNORECASE,
)


def _clean(text: str) -> str:
    return _SPACE_RE.sub(" ", str(text or "").replace("\xa0", " ")).strip()


def _group_inventory_url(group_string: str, *, view_guid: str = LAW_VIEW_GUID) -> str:
    raw_group = unquote(str(group_string or "").strip())
    if not raw_group:
        raise ValueError("Oregon Laws group has no exact group selector")
    query = (
        f"List={quote(LAW_LIST_GUID, safe='')}"
        f"&View={quote(view_guid, safe='')}"
        "&ViewCount=1"
        "&IsXslView=TRUE"
        "&IsGroupRender=TRUE"
        "&DrillDown=1"
        f"&GroupString={quote(raw_group, safe='')}"
    )
    return f"{LAW_GROUP_ENDPOINT}?{query}"


def oregon_current_law_sessions(html: str) -> list[OregonLawSession]:
    """Parse exactly the two post-2025-edition law groups.

    Other historical session groups are deliberately ignored.  A missing,
    duplicate, renamed, or count-drifted current group fails closed.
    """

    try:
        from bs4 import BeautifulSoup
    except ImportError as exc:  # pragma: no cover - production dependency
        raise RuntimeError(
            "BeautifulSoup is required for Oregon Laws inventory"
        ) from exc

    soup = BeautifulSoup(html or "", "html.parser")
    candidates: dict[str, list[tuple[str, int]]] = {
        str(spec["key"]): [] for spec in _SESSION_SPECS
    }
    for tbody in soup.find_all("tbody"):
        encoded_group = str(tbody.get("groupstring") or "").strip()
        if not encoded_group:
            continue
        raw_group = unquote(encoded_group)
        text = _clean(tbody.get_text(" ", strip=True))
        count_match = _COUNT_RE.search(text)
        for spec in _SESSION_SPECS:
            if raw_group != spec["group_string"]:
                continue
            if (
                count_match is None
                or str(spec["label"]).casefold() not in text.casefold()
            ):
                raise ValueError(
                    "Oregon Laws current group lacks its exact label/count: "
                    f"{spec['label']}"
                )
            candidates[str(spec["key"])].append(
                (raw_group, int(count_match.group("count")))
            )

    sessions: list[OregonLawSession] = []
    for spec in _SESSION_SPECS:
        rows = candidates[str(spec["key"])]
        if len(rows) != 1:
            raise ValueError(
                "Oregon Laws current group inventory is missing or duplicated: "
                f"{spec['label']} matches={len(rows)}"
            )
        group_string, declared_count = rows[0]
        if declared_count != int(spec["count"]):
            raise ValueError(
                "Oregon Laws current group count changed: "
                f"{spec['label']} expected={spec['count']} actual={declared_count}"
            )
        sessions.append(
            OregonLawSession(
                key=str(spec["key"]),
                label=str(spec["label"]),
                year=int(spec["year"]),
                declared_chapter_count=declared_count,
                group_string=group_string,
                inventory_url=_group_inventory_url(group_string),
                filename_prefix=str(spec["filename_prefix"]),
                official_cite_session=str(spec["official_cite_session"]),
            )
        )

    if len({row.inventory_url for row in sessions}) != len(sessions):
        raise ValueError("Oregon Laws current groups share an inventory URL")
    return sessions


def _canonical_official_pdf_url(declared_url: str) -> str:
    parsed = urlsplit(str(declared_url or "").strip())
    if (
        parsed.scheme.casefold() not in {"http", "https"}
        or (parsed.hostname or "").casefold() != OFFICIAL_HOST
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port not in {None, 80, 443}
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(f"nonofficial Oregon Laws PDF locator: {declared_url!r}")
    return urlunsplit(("https", OFFICIAL_HOST, parsed.path, "", ""))


def oregon_supplement_inventory_url(session: OregonLawSession) -> str:
    """Return the exact official supplemental-material group endpoint."""

    return _group_inventory_url(
        session.group_string,
        view_guid=SUPPLEMENT_VIEW_GUID,
    )


def oregon_resolution_inventory_url(session: OregonLawSession) -> str:
    """Return the exact official resolution group endpoint."""

    return _group_inventory_url(
        session.group_string,
        view_guid=RESOLUTION_VIEW_GUID,
    )


def _official_pdf_anchors(html: str, *, base_url: str) -> list[tuple[str, str, str]]:
    try:
        from bs4 import BeautifulSoup
    except ImportError as exc:  # pragma: no cover - production dependency
        raise RuntimeError(
            "BeautifulSoup is required for Oregon Laws inventory"
        ) from exc

    soup = BeautifulSoup(html or "", "html.parser")
    rows: list[tuple[str, str, str]] = []
    for anchor in soup.find_all("a", href=True):
        declared = urljoin(base_url, str(anchor.get("href") or "").strip())
        parsed = urlsplit(declared)
        if not parsed.path.casefold().startswith(
            "/bills_laws/lawsstatutes/"
        ) or not parsed.path.casefold().endswith(".pdf"):
            continue
        canonical = _canonical_official_pdf_url(declared)
        rows.append((_clean(anchor.get_text(" ", strip=True)), declared, canonical))
    return rows


def oregon_supplement_locators(
    html: str,
    session: OregonLawSession,
) -> list[OregonSessionEvidenceLocator]:
    """Close a session's complete supplemental inventory and select its tables."""

    expected = _SUPPLEMENT_SPECS.get(session.key)
    if expected is None:
        raise ValueError(f"unsupported Oregon supplement session: {session.key}")
    base_url = oregon_supplement_inventory_url(session)
    anchors = _official_pdf_anchors(html, base_url=base_url)
    expected_by_filename = {
        filename.casefold(): (kind, filename, label)
        for kind, filename, label in expected
    }
    actual_filenames = [urlsplit(row[2]).path.rsplit("/", 1)[-1] for row in anchors]
    if len(actual_filenames) != len({name.casefold() for name in actual_filenames}):
        raise ValueError(f"Oregon supplement inventory repeats a PDF: {session.label}")
    if {name.casefold() for name in actual_filenames} != set(expected_by_filename):
        raise ValueError(
            "Oregon supplement inventory changed: "
            f"session={session.label!r} expected={sorted(expected_by_filename)} "
            f"actual={sorted(name.casefold() for name in actual_filenames)}"
        )

    rows: list[OregonSessionEvidenceLocator] = []
    for label, declared, canonical in anchors:
        filename = urlsplit(canonical).path.rsplit("/", 1)[-1]
        kind, expected_filename, expected_label = expected_by_filename[
            filename.casefold()
        ]
        if filename != expected_filename or label != expected_label:
            raise ValueError(
                "Oregon supplement label or filename case changed: "
                f"session={session.label!r} filename={filename!r} label={label!r}"
            )
        rows.append(
            OregonSessionEvidenceLocator(
                session_key=session.key,
                document_kind=kind,
                identity=expected_filename,
                declared_label=label,
                declared_url=declared,
                canonical_url=canonical,
            )
        )
    return rows


def oregon_resolution_locators(
    html: str,
    session: OregonLawSession,
) -> list[OregonSessionEvidenceLocator]:
    """Enumerate every official resolution and type it out of statutory scope."""

    expected = _RESOLUTION_SPECS.get(session.key)
    if expected is None:
        raise ValueError(f"unsupported Oregon resolution session: {session.key}")
    base_url = oregon_resolution_inventory_url(session)
    anchors = _official_pdf_anchors(html, base_url=base_url)
    expected_by_filename = {
        filename.casefold(): (filename, label) for filename, label in expected
    }
    actual_filenames = [urlsplit(row[2]).path.rsplit("/", 1)[-1] for row in anchors]
    if len(actual_filenames) != len({name.casefold() for name in actual_filenames}):
        raise ValueError(f"Oregon resolution inventory repeats a PDF: {session.label}")
    if {name.casefold() for name in actual_filenames} != set(expected_by_filename):
        raise ValueError(
            "Oregon resolution inventory changed: "
            f"session={session.label!r} expected={sorted(expected_by_filename)} "
            f"actual={sorted(name.casefold() for name in actual_filenames)}"
        )

    rows: list[OregonSessionEvidenceLocator] = []
    for label, declared, canonical in anchors:
        filename = urlsplit(canonical).path.rsplit("/", 1)[-1]
        expected_filename, expected_label = expected_by_filename[filename.casefold()]
        if filename != expected_filename or label != expected_label:
            raise ValueError(
                "Oregon resolution label or filename case changed: "
                f"session={session.label!r} filename={filename!r} label={label!r}"
            )
        rows.append(
            OregonSessionEvidenceLocator(
                session_key=session.key,
                document_kind="resolution_excluded_nonstatutory",
                identity=expected_label,
                declared_label=label,
                declared_url=declared,
                canonical_url=canonical,
            )
        )
    return rows


def oregon_law_chapter_locators(
    html: str,
    session: OregonLawSession,
) -> list[OregonLawChapterLocator]:
    """Parse and close one law-group page to consecutive chapter identities."""

    try:
        from bs4 import BeautifulSoup
    except ImportError as exc:  # pragma: no cover - production dependency
        raise RuntimeError(
            "BeautifulSoup is required for Oregon Laws inventory"
        ) from exc

    soup = BeautifulSoup(html or "", "html.parser")
    filename_re = re.compile(
        rf"^/bills_laws/lawsstatutes/{re.escape(session.filename_prefix)}"
        r"(?P<number>\d{4})\.pdf$",
        re.IGNORECASE,
    )
    rows: list[OregonLawChapterLocator] = []
    for anchor in soup.find_all("a", href=True):
        declared = urljoin(session.inventory_url, str(anchor.get("href") or "").strip())
        parsed = urlsplit(declared)
        match = filename_re.fullmatch(parsed.path)
        if match is None:
            continue
        canonical = _canonical_official_pdf_url(declared)
        chapter_number = int(match.group("number"))
        chapter_label = _clean(anchor.get_text(" ", strip=True))
        if chapter_label != f"Chapter {chapter_number:04d}":
            raise ValueError(
                "Oregon Laws chapter label/filename identity changed: "
                f"label={chapter_label!r} url={declared}"
            )
        rows.append(
            OregonLawChapterLocator(
                session_key=session.key,
                session_label=session.label,
                year=session.year,
                chapter_number=chapter_number,
                chapter_label=chapter_label,
                declared_url=declared,
                canonical_url=canonical,
            )
        )

    actual_numbers = [row.chapter_number for row in rows]
    expected_numbers = list(range(1, session.declared_chapter_count + 1))
    canonical_keys = [row.canonical_url.casefold() for row in rows]
    if actual_numbers != expected_numbers:
        raise ValueError(
            "Oregon Laws chapter inventory is not exact and consecutive: "
            f"session={session.label!r} expected={expected_numbers[:3]}.."
            f"{expected_numbers[-1:]} actual={actual_numbers[:3]}..{actual_numbers[-1:]}"
        )
    if len(canonical_keys) != len(set(canonical_keys)):
        raise ValueError(f"Oregon Laws chapter URLs repeat in {session.label}")
    return rows


def valid_full_oregon_law_pdf(payload: bytes) -> bool:
    """Cheap transport validator; Poppler performs the structural validation."""

    body = bytes(payload or b"")
    if len(body) < 1024 or not re.match(rb"%PDF-1\.[0-9]", body[:16]):
        return False
    eof_at = body.rfind(b"%%EOF")
    if eof_at < 0 or body[eof_at + len(b"%%EOF") :].strip():
        return False
    return b"startxref" in body[max(0, eof_at - 4096) : eof_at]


def pdftotext_raw(payload: bytes, *, timeout_seconds: int = 300) -> str:
    """Convert retained PDF bytes with deterministic, unbounded ``-raw`` output."""

    if not valid_full_oregon_law_pdf(payload):
        raise ValueError("Oregon Laws parser input is not a complete PDF")
    env = {
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PATH": os.defpath,
        "TZ": "UTC",
    }
    try:
        result = subprocess.run(
            (trusted_pdftotext_executable(), "-raw", "-", "-"),
            input=bytes(payload),
            capture_output=True,
            check=False,
            timeout=max(1, int(timeout_seconds)),
            env=env,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError("deterministic pdftotext -raw conversion failed") from exc
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace").strip()[:500]
        raise RuntimeError(
            f"pdftotext -raw rejected the retained Oregon Laws PDF: {detail}"
        )
    try:
        text = result.stdout.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise RuntimeError("pdftotext -raw emitted non-UTF-8 Oregon Laws text") from exc
    if not text.strip() or "\x00" in text:
        raise RuntimeError("pdftotext -raw emitted empty or invalid Oregon Laws text")
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _normalize_bill_number(value: str) -> str:
    match = re.fullmatch(r"\s*(HB|SB)\s*(\d+)(?:\s+(OV|OVP))?\s*", value)
    if match is None:
        raise ValueError(f"unsupported Oregon measure identity: {value!r}")
    suffix = f" {match.group(3)}" if match.group(3) else ""
    return f"{match.group(1)} {match.group(2)}{suffix}"


def parse_oregon_enacted_text(
    text: str,
    *,
    session_key: str,
) -> tuple[OregonEnactedBill, ...]:
    """Parse every enacted-table disposition, including the explicit veto."""

    expected = _ENACTED_EXPECTATIONS.get(session_key)
    if expected is None:
        raise ValueError(f"unsupported Oregon enacted-table session: {session_key}")
    raw = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    expected_heading = (
        "OREGON LAWS 2025 SPECIAL SESSION"
        if session_key == "2025_special_1"
        else "OREGON LAWS 2026 REGULAR SESSION"
    )
    if expected_heading not in raw or "SENATE AND HOUSE BILLS ENACTED" not in raw:
        raise ValueError("Oregon enacted table lacks its exact session/table heading")

    chamber = ""
    rows: list[OregonEnactedBill] = []
    candidate_count = 0
    for line in raw.splitlines():
        cleaned = _clean(line.replace("\f", " "))
        if cleaned == "SENATE BILLS":
            chamber = "SB"
            continue
        if cleaned == "HOUSE BILLS":
            chamber = "HB"
            continue
        matches = list(_ENACTED_ROW_RE.finditer(line))
        candidate_count += len(re.findall(r"\b\d{4}\s*\.{2,}", line))
        for match in matches:
            if chamber not in {"HB", "SB"}:
                raise ValueError("Oregon enacted row appeared outside a chamber table")
            status = match.group("status")
            chapter = match.group("chapter")
            if status.casefold() == "vetoed":
                if chapter is not None:
                    raise ValueError(
                        "vetoed Oregon bill unexpectedly has a law chapter"
                    )
                disposition = "vetoed"
                effective_date = None
            else:
                if chapter is None:
                    raise ValueError("enacted Oregon bill has no law chapter")
                try:
                    effective_date = (
                        datetime.strptime(status, "%m/%d/%y")
                        .replace(tzinfo=UTC)
                        .date()
                        .isoformat()
                    )
                except ValueError as exc:
                    raise ValueError(
                        f"invalid Oregon enacted-table effective date: {status!r}"
                    ) from exc
                disposition = "enacted"
            rows.append(
                OregonEnactedBill(
                    session_key=session_key,
                    bill_number=f"{chamber} {match.group('number')}",
                    disposition=disposition,
                    chapter_number=int(chapter) if chapter is not None else None,
                    effective_date=effective_date,
                    notes=(),
                )
            )

    if candidate_count != len(rows):
        raise ValueError(
            "Oregon enacted table contains an unparsed bill row: "
            f"candidates={candidate_count} parsed={len(rows)}"
        )
    footnotes: dict[str, list[str]] = {}
    for match in re.finditer(r"(?m)^\s*\*\s*(?P<note>[^\n]+)$", raw):
        note = _clean(match.group("note"))
        bills = re.findall(r"\b(?:HB|SB)\s*\d+\b", note)
        if len(bills) != 1:
            raise ValueError(f"ambiguous Oregon enacted-table footnote: {note!r}")
        footnotes.setdefault(_normalize_bill_number(bills[0]), []).append(note)
    rows = [
        OregonEnactedBill(
            session_key=row.session_key,
            bill_number=row.bill_number,
            disposition=row.disposition,
            chapter_number=row.chapter_number,
            effective_date=row.effective_date,
            notes=tuple(footnotes.get(row.bill_number, ())),
        )
        for row in rows
    ]
    known_bills = {row.bill_number for row in rows}
    if set(footnotes) - known_bills:
        raise ValueError("Oregon enacted-table footnote names an unknown bill")

    enacted = [row for row in rows if row.disposition == "enacted"]
    vetoed = [row for row in rows if row.disposition == "vetoed"]
    expected_enacted, expected_vetoed = expected
    if len(enacted) != expected_enacted or len(vetoed) != expected_vetoed:
        raise ValueError(
            "Oregon enacted-table disposition count changed: "
            f"session={session_key} enacted={len(enacted)} vetoed={len(vetoed)}"
        )
    chapters = [int(row.chapter_number or 0) for row in enacted]
    if sorted(chapters) != list(range(1, expected_enacted + 1)):
        raise ValueError("Oregon enacted table does not cover consecutive law chapters")
    bills = [row.bill_number.casefold() for row in rows]
    if len(bills) != len(set(bills)):
        raise ValueError("Oregon enacted table repeats a bill identity")
    return tuple(rows)


def parse_oregon_enacted_pdf(
    payload: bytes,
    *,
    session_key: str,
) -> tuple[OregonEnactedBill, ...]:
    """Parse an enacted table from the exact retained PDF bytes."""

    return parse_oregon_enacted_text(pdftotext_raw(payload), session_key=session_key)


def _normalize_affected_target(
    prefix: str,
    *,
    last_target: str,
    pending_range_start: str,
    table_kind: str,
) -> str:
    target = _clean(prefix).rstrip(")").strip()
    if pending_range_start:
        if not target:
            raise ValueError("Oregon A&R range has no terminal target")
        return f"{pending_range_start} to {target}"
    if not target:
        if not last_target:
            raise ValueError("Oregon A&R continuation has no prior target")
        return last_target
    if table_kind == "uncodified" and target.startswith("§"):
        base = re.match(r"(?P<base>.+?\bc\.\s*\d+)\s+§", last_target)
        if base is None:
            raise ValueError("Oregon uncodified continuation has no year/chapter base")
        return f"{_clean(base.group('base'))} {target}"
    return target


def _parse_affected_table(
    text: str,
    *,
    session_key: str,
    table_kind: str,
) -> tuple[OregonAffectedReference, ...]:
    rows: list[OregonAffectedReference] = []
    last_target = ""
    pending_range_start = ""
    candidate_count = 0
    range_start_re = re.compile(
        r"^(?P<target>(?:Ch\.\s*)?\d+[A-Za-z]?(?:\.\d{3}[A-Za-z]?)?)\s+to\)$"
    )
    for raw_line in text.splitlines():
        line = raw_line.replace("\f", " ")
        cleaned = _clean(line)
        range_match = range_start_re.fullmatch(cleaned)
        if range_match is not None:
            if pending_range_start:
                raise ValueError("Oregon A&R table contains nested range starts")
            pending_range_start = _clean(range_match.group("target"))
            continue

        matches = list(_ACTION_ROW_RE.finditer(line))
        candidate_count += len(re.findall(r"\b(?:Add|A|R)\s+c\.\s*\d+\s+§", line))
        cursor = 0
        for match in matches:
            prefix = line[cursor : match.start()]
            target = _normalize_affected_target(
                prefix,
                last_target=last_target,
                pending_range_start=pending_range_start,
                table_kind=table_kind,
            )
            pending_range_start = ""
            last_target = target
            bill = match.group("bill")
            if bill.upper().replace(" ", "").startswith("BM"):
                raise ValueError(
                    "current Oregon overlay unexpectedly names a ballot measure"
                )
            rows.append(
                OregonAffectedReference(
                    session_key=session_key,
                    table_kind=table_kind,
                    target=target,
                    action=match.group("action"),
                    law_chapter_number=int(match.group("chapter")),
                    law_section_number=match.group("section").upper(),
                    bill_number=_normalize_bill_number(bill),
                    emergency_marker=str(match.group("emergency") or ""),
                    raw_text=_clean(match.group(0)),
                )
            )
            cursor = match.end()
    if pending_range_start:
        raise ValueError("Oregon A&R table ends with an unterminated target range")
    if candidate_count != len(rows):
        raise ValueError(
            "Oregon A&R table contains an unparsed action row: "
            f"kind={table_kind} candidates={candidate_count} parsed={len(rows)}"
        )
    return tuple(rows)


def parse_oregon_affected_text(
    text: str,
    *,
    session_key: str,
) -> tuple[OregonAffectedReference, ...]:
    """Parse all ORS and uncodified-law A&R rows with continuation inheritance."""

    expected = _AFFECTED_EXPECTATIONS.get(session_key)
    if expected is None:
        raise ValueError(f"unsupported Oregon A&R-table session: {session_key}")
    raw = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    expected_heading = (
        "OREGON LAWS 2025 SPECIAL SESSION"
        if session_key == "2025_special_1"
        else "OREGON LAWS 2026 REGULAR SESSION"
    )
    required_headings = (
        "ORS SECTIONS AMENDED, REPEALED OR “ADDED TO”",
        "OREGON RULES OF CIVIL PROCEDURE (ORCP) AMENDED,",
        "SECTIONS IN UNCODIFIED LAW AMENDED,",
        "CONSTITUTIONAL PROVISIONS - AMENDMENTS,",
    )
    if expected_heading not in raw or any(
        value not in raw for value in required_headings
    ):
        raise ValueError("Oregon A&R table lacks an exact bounded table heading")
    ors_start = raw.index(required_headings[0])
    orcp_start = raw.index(required_headings[1], ors_start)
    uncodified_start = raw.index(required_headings[2], orcp_start)
    constitution_start = raw.index(required_headings[3], uncodified_start)
    ors_rows = _parse_affected_table(
        raw[ors_start:orcp_start],
        session_key=session_key,
        table_kind="ors",
    )
    uncodified_rows = _parse_affected_table(
        raw[uncodified_start:constitution_start],
        session_key=session_key,
        table_kind="uncodified",
    )
    for kind, rows in (("ors", ors_rows), ("uncodified", uncodified_rows)):
        actual = {
            action: sum(row.action == action for row in rows)
            for action in ("A", "R", "Add")
        }
        if actual != dict(expected[kind]):
            raise ValueError(
                "Oregon A&R table action count changed: "
                f"session={session_key} kind={kind} expected={dict(expected[kind])} "
                f"actual={actual}"
            )
    if "There were no amendments, repeals or additions" not in raw[orcp_start:]:
        raise ValueError("Oregon A&R table no longer closes ORCP/constitution scope")
    return (*ors_rows, *uncodified_rows)


def parse_oregon_affected_pdf(
    payload: bytes,
    *,
    session_key: str,
) -> tuple[OregonAffectedReference, ...]:
    """Parse an A&R table from the exact retained PDF bytes."""

    return parse_oregon_affected_text(pdftotext_raw(payload), session_key=session_key)


def _iso_date(value: str, *, field: str) -> str:
    normalized = _clean(value)
    try:
        return (
            datetime.strptime(normalized, "%B %d, %Y")
            .replace(tzinfo=UTC)
            .date()
            .isoformat()
        )
    except ValueError as exc:
        raise ValueError(f"invalid Oregon Laws {field}: {value!r}") from exc


def _one_date(text: str, pattern: str, *, field: str) -> tuple[str, str]:
    matches = list(re.finditer(pattern, text, flags=re.IGNORECASE))
    if len(matches) != 1:
        raise ValueError(
            f"Oregon Laws PDF requires exactly one {field}; found {len(matches)}"
        )
    raw = matches[0].group("date")
    return _iso_date(raw, field=field), _clean(matches[0].group(0))


def _document_metadata(text: str) -> OregonLawDocumentMetadata:
    bill_matches = re.findall(r"(?m)^\s*AN ACT\s+((?:HB|SB)\s*\d+)\b", text)
    if len(bill_matches) != 1:
        raise ValueError(
            "Oregon Laws PDF requires exactly one HB/SB enactment identity"
        )
    approval_patterns = (
        r"Approved by the Governor\s+(?P<date>" + _DATE_RE.pattern + r")",
        r"Became law without (?:the )?Governor(?:'s)? signature\s+"
        r"(?P<date>" + _DATE_RE.pattern + r")",
    )
    approval_rows: list[tuple[str, str]] = []
    for pattern in approval_patterns:
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            approval_rows.append(
                (
                    _iso_date(match.group("date"), field="approval date"),
                    _clean(match.group(0)),
                )
            )
    if len(approval_rows) != 1:
        raise ValueError(
            "Oregon Laws PDF requires exactly one approval/passage event; "
            f"found {len(approval_rows)}"
        )
    filed_date, _filed_line = _one_date(
        text,
        r"Filed in (?:the )?office of (?:the )?Secretary of State\s+"
        r"(?P<date>" + _DATE_RE.pattern + r")",
        field="filed date",
    )
    effective_date, _effective_line = _one_date(
        text,
        r"Effective date\s*:?[ \t]*(?P<date>" + _DATE_RE.pattern + r")",
        field="effective date",
    )
    return OregonLawDocumentMetadata(
        bill_number=_clean(bill_matches[0]),
        approved_event=approval_rows[0][1],
        approved_date=approval_rows[0][0],
        filed_date=filed_date,
        effective_date=effective_date,
    )


def _dedupe(values: Iterable[str]) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = _clean(value)
        key = cleaned.casefold()
        if cleaned and key not in seen:
            result.append(cleaned)
            seen.add(key)
    return tuple(result)


def _ors_action_citations(text: str, action: str) -> tuple[str, ...]:
    values: list[str] = []
    action_re = re.compile(
        rf"(?is)\bORS\s+(?P<refs>\d{{1,3}}\.\d{{3}}[A-Za-z]?"
        rf"(?:\s*\([^)]{{1,80}}\))?(?:(?:\s*,\s*|\s+and\s+)"
        rf"(?:ORS\s+)?\d{{1,3}}\.\d{{3}}[A-Za-z]?"
        rf"(?:\s*\([^)]{{1,80}}\))?)*)\s+(?:is|are)\s+{action}\b"
    )
    for match in action_re.finditer(text):
        if re.match(
            r"\s+by\s+section\b",
            text[match.end() :],
            flags=re.IGNORECASE,
        ):
            # A later section can describe an action performed by a different
            # section of the same Act.  The A&R table correctly joins the action
            # to that named section, not to this cross-reference.
            continue
        values.extend(
            f"ORS {item.group('cite')}"
            for item in _ORS_CITE_RE.finditer(match.group("refs"))
        )
    return _dedupe(values)


def _semantic_clauses(text: str, terms: Sequence[str]) -> tuple[Mapping[str, Any], ...]:
    values: list[Mapping[str, Any]] = []
    seen: set[str] = set()
    normalized = text.replace("\n", " ")
    for sentence in re.split(r"(?<=[.;])\s+", normalized):
        cleaned = _clean(sentence)
        lowered = cleaned.casefold()
        if not cleaned or not any(term in lowered for term in terms):
            continue
        key = cleaned.casefold()
        if key in seen:
            continue
        dates = tuple(match.group(0) for match in _DATE_RE.finditer(cleaned))
        relative_triggers = _dedupe(
            match.group(0)
            for match in re.finditer(
                r"\b(?:on its passage|on or after the effective date|"
                r"\d+(?:st|nd|rd|th) day after[^.;]*|if [^.;]* becomes law)\b",
                cleaned,
                flags=re.IGNORECASE,
            )
        )
        values.append(
            {
                "text": cleaned,
                "dates": list(dates),
                "relative_triggers": list(relative_triggers),
            }
        )
        seen.add(key)
    return tuple(values)


def _strip_exact_page_headers(text: str) -> str:
    lines = []
    for line in text.replace("\f", "\n").splitlines():
        if _PAGE_HEADER_RE.fullmatch(_clean(line)):
            continue
        lines.append(line.rstrip())
    return "\n".join(lines).strip()


def _parse_section(number: str, text: str) -> OregonLawSection:
    amended = _ors_action_citations(text, "amended")
    repealed = _ors_action_citations(text, "repealed")
    added_chapters = _dedupe(
        f"ORS chapter {match.group('chapter')}"
        for match in re.finditer(
            r"(?i)added to and made a part of ORS chapter\s+"
            r"(?P<chapter>\d{1,3}[A-Za-z]?)",
            text,
        )
    )
    operative = _semantic_clauses(
        text,
        ("become operative", "becomes operative", "operative on", "applies to"),
    )
    effective = _semantic_clauses(
        text,
        ("takes effect", "effective on", "effective date"),
    )
    sunset = _semantic_clauses(
        text,
        ("is repealed on", "are repealed on", "sunset"),
    )
    conditional = _dedupe(
        match.group(0)
        for match in re.finditer(
            r"(?is)\bIf\s+[^.;]{1,700}\b(?:becomes law|does not become law)[^.;]*[.;]",
            text,
        )
    )
    emergency = bool(
        re.search(
            r"(?is)an emergency,?\s+is declared\s+to\s+exist.*?"
            r"takes effect on its passage",
            text,
        )
    )
    return OregonLawSection(
        number=number.upper(),
        text=text,
        amended_ors_citations=amended,
        repealed_ors_citations=repealed,
        added_to_ors_chapters=added_chapters,
        operative_semantics=operative,
        effective_semantics=effective,
        sunset_semantics=sunset,
        conditional_semantics=conditional,
        emergency_clause=emergency,
    )


def parse_oregon_law_text(
    text: str,
    *,
    locator: OregonLawChapterLocator,
) -> ParsedOregonLaw:
    """Validate one chapter identity and split every official section heading."""

    raw = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    if not raw.strip() or "\x00" in raw:
        raise ValueError("Oregon Laws extracted text is empty or invalid")
    page_headers = [
        _clean(line)
        for line in raw.replace("\f", "\n").splitlines()
        if _PAGE_HEADER_RE.fullmatch(_clean(line))
    ]
    header_years = {
        int(match.group(1))
        for line in page_headers
        if (match := re.search(r"\bOREGON LAWS\s+(\d{4})\b", line, re.IGNORECASE))
    }
    if not page_headers or header_years != {locator.year}:
        raise ValueError("Oregon Laws PDF year does not match its requested locator")
    chapter_matches = re.findall(r"(?mi)^\s*CHAPTER\s+(\d+)\s*$", raw)
    if len(chapter_matches) != 1 or int(chapter_matches[0]) != locator.chapter_number:
        raise ValueError("Oregon Laws PDF chapter does not match its requested locator")
    if locator.session_key == "2025_special_1":
        session_header = rf"OREGON LAWS 2025 SPECIAL SESSION\s+Chap\.\s*{locator.chapter_number}"
    elif locator.session_key == "2026_regular":
        # The regular-session volumes identify themselves as ``OREGON LAWS
        # 2026 Chap. N``.  The official landing inventory and ``2026orlaw``
        # filename frontier supply the regular-session binding; the PDFs do not
        # print an additional ``REGULAR SESSION`` token in their page headers.
        session_header = rf"OREGON LAWS 2026\s+Chap\.\s*{locator.chapter_number}"
    else:
        raise ValueError("unsupported Oregon Laws session locator")
    if re.search(rf"(?mi)^\s*{session_header}\s*$", raw) is None:
        raise ValueError("Oregon Laws PDF does not declare the expected session")

    metadata = _document_metadata(raw)
    exact_headings = list(_SECTION_HEADING_RE.finditer(raw))
    loose_headings = list(_LOOSE_SECTION_HEADING_RE.finditer(raw))
    if not exact_headings or len(exact_headings) != len(loose_headings):
        raise ValueError(
            "Oregon Laws PDF contains an unparseable SECTION N[letter]. heading"
        )
    if [item.start() for item in exact_headings] != [
        item.start() for item in loose_headings
    ]:
        raise ValueError("Oregon Laws PDF section-heading alignment changed")

    trailer_match = _TRAILER_START_RE.search(raw, exact_headings[-1].end())
    if trailer_match is None:
        raise ValueError("Oregon Laws PDF has no source trailer after its last section")
    document_end = trailer_match.start()
    section_numbers = [match.group("number").upper() for match in exact_headings]
    if len(section_numbers) != len(set(section_numbers)):
        raise ValueError("Oregon Laws PDF repeats a section identity")
    sort_keys = [
        (
            int(re.match(r"\d+", number).group(0)),
            number[len(re.match(r"\d+", number).group(0)) :],
        )
        for number in section_numbers
    ]
    if sort_keys != sorted(sort_keys) or sort_keys[0][0] != 1:
        raise ValueError("Oregon Laws PDF section identities are out of source order")

    sections: list[OregonLawSection] = []
    for index, heading in enumerate(exact_headings):
        end = (
            exact_headings[index + 1].start()
            if index + 1 < len(exact_headings)
            else document_end
        )
        if end <= heading.start():
            raise ValueError("Oregon Laws PDF emitted a truncated section range")
        section_text = _strip_exact_page_headers(raw[heading.start() : end])
        expected_heading = f"SECTION {section_numbers[index]}."
        if (
            section_text[: len(expected_heading)].casefold()
            != expected_heading.casefold()
        ):
            raise ValueError("Oregon Laws section text lost its exact heading")
        if len(section_text) <= len(expected_heading):
            raise ValueError("Oregon Laws PDF emitted an empty section")
        sections.append(_parse_section(section_numbers[index], section_text))
    return ParsedOregonLaw(locator=locator, metadata=metadata, sections=tuple(sections))


def parse_oregon_law_pdf(
    payload: bytes,
    *,
    locator: OregonLawChapterLocator,
) -> ParsedOregonLaw:
    """Convert and parse one retained official chapter PDF."""

    return parse_oregon_law_text(pdftotext_raw(payload), locator=locator)


def reconcile_oregon_session_evidence(
    parsed_laws: Sequence[ParsedOregonLaw],
    enacted_entries: Sequence[OregonEnactedBill],
    affected_references: Sequence[OregonAffectedReference],
) -> OregonSessionEvidenceReconciliation:
    """Join every table fact to one exact retained chapter and section."""

    laws_by_chapter: dict[tuple[str, int], ParsedOregonLaw] = {}
    sections_by_key: dict[tuple[str, int, str], OregonLawSection] = {}
    for law in parsed_laws:
        chapter_key = (law.locator.session_key, law.locator.chapter_number)
        if chapter_key in laws_by_chapter:
            raise ValueError(
                f"repeated Oregon law chapter during reconciliation: {chapter_key}"
            )
        laws_by_chapter[chapter_key] = law
        for section in law.sections:
            section_key = (*chapter_key, section.number.upper())
            if section_key in sections_by_key:
                raise ValueError(
                    f"repeated Oregon law section during reconciliation: {section_key}"
                )
            sections_by_key[section_key] = section

    enacted_by_chapter: dict[tuple[str, int], OregonEnactedBill] = {}
    vetoed: list[OregonEnactedBill] = []
    for entry in enacted_entries:
        if entry.disposition == "vetoed":
            vetoed.append(entry)
            continue
        if entry.chapter_number is None:
            raise ValueError("enacted Oregon table row has no chapter identity")
        key = (entry.session_key, entry.chapter_number)
        if key in enacted_by_chapter:
            raise ValueError(f"Oregon enacted table repeats a chapter: {key}")
        law = laws_by_chapter.get(key)
        if law is None:
            raise ValueError(
                f"Oregon enacted table names an undiscovered chapter: {key}"
            )
        if law.metadata.bill_number != entry.bill_number:
            raise ValueError(
                "Oregon enacted-table bill does not match chapter PDF: "
                f"chapter={key} table={entry.bill_number} pdf={law.metadata.bill_number}"
            )
        if law.metadata.effective_date != entry.effective_date:
            raise ValueError(
                "Oregon enacted-table effective date does not match chapter PDF: "
                f"chapter={key} table={entry.effective_date} "
                f"pdf={law.metadata.effective_date}"
            )
        enacted_by_chapter[key] = entry
    if set(enacted_by_chapter) != set(laws_by_chapter):
        missing = sorted(set(laws_by_chapter) - set(enacted_by_chapter))
        extra = sorted(set(enacted_by_chapter) - set(laws_by_chapter))
        raise ValueError(
            "Oregon enacted-table/chapter parity is incomplete: "
            f"missing={missing} extra={extra}"
        )

    actions_by_section_lists: dict[
        tuple[str, int, str], list[OregonAffectedReference]
    ] = {}
    for reference in affected_references:
        key = (
            reference.session_key,
            reference.law_chapter_number,
            reference.law_section_number.upper(),
        )
        law = laws_by_chapter.get(key[:2])
        if law is None or key not in sections_by_key:
            raise ValueError(
                "Oregon A&R row does not resolve to one retained law section: "
                f"key={key} target={reference.target!r}"
            )
        if law.metadata.bill_number != reference.bill_number:
            raise ValueError(
                "Oregon A&R bill does not match its law chapter: "
                f"key={key} table={reference.bill_number} pdf={law.metadata.bill_number}"
            )
        section = sections_by_key[key]
        if reference.table_kind == "ors":
            section_text = re.sub(
                r"(?<=\w)-\s*\n\s*(?=\w)",
                "",
                section.text,
            )
            action_term = {
                "A": r"\bamend(?:ed|ing|s)?\b",
                "R": r"\brepeal(?:ed|ing|s)?\b",
                "Add": r"\badded\s+to\s+and\s+made\s+a\s+part\b",
            }[reference.action]
            if re.search(action_term, section_text, flags=re.IGNORECASE) is None:
                raise ValueError(
                    "Oregon A&R action is not stated in its retained law section: "
                    f"key={key} action={reference.action} target={reference.target!r}"
                )
            target_tokens = re.findall(
                r"\d+[A-Za-z]?(?:\.\d{3}[A-Za-z]?)?",
                reference.target,
            )
            missing_tokens = [
                token
                for token in target_tokens
                if re.search(
                    rf"(?<![\w.]){re.escape(token)}(?!\w)",
                    section_text,
                    flags=re.IGNORECASE,
                )
                is None
            ]
            named_target = _NAMED_ORS_RANGE_TARGETS.get(reference.target)
            named_target_match = bool(
                named_target
                and re.search(
                    rf"\b{re.escape(named_target)}\b",
                    _clean(section_text),
                    flags=re.IGNORECASE,
                )
            )
            if not target_tokens or (missing_tokens and not named_target_match):
                raise ValueError(
                    "Oregon A&R target is not stated in its retained law section: "
                    f"key={key} target={reference.target!r} missing={missing_tokens}"
                )
        actions_by_section_lists.setdefault(key, []).append(reference)

    # The chapter parser independently extracts direct ORS A/R references.  Each
    # such fact must also occur in the official A&R table for the exact section.
    for key, section in sections_by_key.items():
        references = actions_by_section_lists.get(key, [])
        for action, citations in (
            ("A", section.amended_ors_citations),
            ("R", section.repealed_ors_citations),
        ):
            targets = {
                reference.target.casefold()
                for reference in references
                if reference.table_kind == "ors" and reference.action == action
            }
            for citation in citations:
                target = citation.removeprefix("ORS ").casefold()
                if target not in targets:
                    raise ValueError(
                        "Oregon law-section ORS action is absent from its A&R table: "
                        f"key={key} action={action} target={target}"
                    )
        add_targets = {
            reference.target.casefold()
            for reference in references
            if reference.table_kind == "ors" and reference.action == "Add"
        }
        for chapter in section.added_to_ors_chapters:
            target = chapter.replace("ORS chapter", "Ch.").strip().casefold()
            if target not in add_targets:
                raise ValueError(
                    "Oregon law-section ORS addition is absent from its A&R table: "
                    f"key={key} target={target}"
                )

    actions_by_section = {
        key: tuple(rows) for key, rows in actions_by_section_lists.items()
    }
    per_session = {}
    for session_key, expected_chapters in _ENACTED_EXPECTATIONS.items():
        per_session[session_key] = {
            "chapter_count": sum(key[0] == session_key for key in laws_by_chapter),
            "enacted_count": sum(key[0] == session_key for key in enacted_by_chapter),
            "vetoed_count": sum(row.session_key == session_key for row in vetoed),
            "ors_action_count": sum(
                row.session_key == session_key and row.table_kind == "ors"
                for row in affected_references
            ),
            "uncodified_action_count": sum(
                row.session_key == session_key and row.table_kind == "uncodified"
                for row in affected_references
            ),
            "expected_chapter_count": expected_chapters[0],
        }
    return OregonSessionEvidenceReconciliation(
        enacted_by_chapter=enacted_by_chapter,
        actions_by_section=actions_by_section,
        summary={
            "closed": True,
            "chapter_count": len(laws_by_chapter),
            "enacted_count": len(enacted_by_chapter),
            "vetoed_count": len(vetoed),
            "affected_reference_count": len(affected_references),
            "ors_action_count": sum(
                row.table_kind == "ors" for row in affected_references
            ),
            "uncodified_action_count": sum(
                row.table_kind == "uncodified" for row in affected_references
            ),
            "per_session": per_session,
        },
    )


def normalized_oregon_law_sections(
    parsed: ParsedOregonLaw,
    *,
    legal_area: str = "general",
) -> list[NormalizedStatute]:
    """Project every parsed session-law section onto the common row schema."""

    session = next(
        spec for spec in _SESSION_SPECS if spec["key"] == parsed.locator.session_key
    )
    rows: list[NormalizedStatute] = []
    for section in parsed.sections:
        cite = (
            f"Or. Laws {session['official_cite_session']}, "
            f"ch. {parsed.locator.chapter_number}, § {section.number}"
        )
        all_citations = _dedupe(
            (*section.amended_ors_citations, *section.repealed_ors_citations)
        )
        structured_data = {
            "source_kind": "official_oregon_session_law_pdf",
            "source_authority_class": "official",
            "document_kind": "session_law",
            "discovery_method": "official_oregon_laws_sharepoint_inventory",
            "skip_hydrate": True,
            "session_key": parsed.locator.session_key,
            "session_label": parsed.locator.session_label,
            "chapter_number": parsed.locator.chapter_number,
            "section_number": section.number,
            "bill_number": parsed.metadata.bill_number,
            "official_locator": {
                "declared_url": parsed.locator.declared_url,
                "canonical_url": parsed.locator.canonical_url,
                "canonicalization": (
                    "declared_http_to_https"
                    if parsed.locator.declared_url.startswith("http://")
                    else "identity"
                ),
            },
            "enactment": {
                "approved_event": parsed.metadata.approved_event,
                "approved_date": parsed.metadata.approved_date,
                "filed_date": parsed.metadata.filed_date,
                "effective_date": parsed.metadata.effective_date,
                "emergency_clause": section.emergency_clause,
            },
            "amended_ors_citations": list(section.amended_ors_citations),
            "repealed_ors_citations": list(section.repealed_ors_citations),
            "added_to_ors_chapters": list(section.added_to_ors_chapters),
            "operative_semantics": list(section.operative_semantics),
            "effective_semantics": list(section.effective_semantics),
            "sunset_semantics": list(section.sunset_semantics),
            "conditional_semantics": list(section.conditional_semantics),
        }
        rows.append(
            NormalizedStatute(
                state_code="OR",
                state_name="Oregon",
                statute_id=cite,
                code_name=f"Oregon Laws {parsed.locator.session_label}",
                title_number=parsed.locator.session_key,
                title_name=parsed.locator.session_label,
                chapter_number=str(parsed.locator.chapter_number),
                chapter_name=f"Chapter {parsed.locator.chapter_number}",
                section_number=section.number,
                section_name=f"SECTION {section.number}",
                short_title=f"SECTION {section.number}",
                full_text=section.text,
                summary="",
                legal_area=legal_area,
                keywords=list(all_citations),
                source_url=(
                    f"{parsed.locator.canonical_url}#section-{section.number.casefold()}"
                ),
                official_cite=cite,
                metadata=StatuteMetadata(
                    effective_date=parsed.metadata.effective_date,
                    enacted_year=str(parsed.locator.year),
                    legislative_session=parsed.locator.session_label,
                    bill_number=parsed.metadata.bill_number,
                    history=[
                        parsed.metadata.approved_event,
                        f"Filed {parsed.metadata.filed_date}",
                        f"Effective {parsed.metadata.effective_date}",
                    ],
                ),
                structured_data=structured_data,
            )
        )
    return rows


def expected_oregon_law_chapter_count() -> int:
    """Return the immutable current-overlay chapter count (2 + 142)."""

    return sum(int(spec["count"]) for spec in _SESSION_SPECS)


__all__ = [
    "LAWS_MOBILE_URL",
    "OregonAffectedReference",
    "OregonEnactedBill",
    "OregonLawChapterLocator",
    "OregonLawDocumentMetadata",
    "OregonLawSection",
    "OregonLawSession",
    "OregonSessionEvidenceLocator",
    "OregonSessionEvidenceReconciliation",
    "ParsedOregonLaw",
    "expected_oregon_law_chapter_count",
    "normalized_oregon_law_sections",
    "oregon_current_law_sessions",
    "oregon_law_chapter_locators",
    "oregon_resolution_inventory_url",
    "oregon_resolution_locators",
    "oregon_supplement_inventory_url",
    "oregon_supplement_locators",
    "parse_oregon_affected_pdf",
    "parse_oregon_affected_text",
    "parse_oregon_enacted_pdf",
    "parse_oregon_enacted_text",
    "parse_oregon_law_pdf",
    "parse_oregon_law_text",
    "pdftotext_raw",
    "reconcile_oregon_session_evidence",
    "valid_full_oregon_law_pdf",
]
