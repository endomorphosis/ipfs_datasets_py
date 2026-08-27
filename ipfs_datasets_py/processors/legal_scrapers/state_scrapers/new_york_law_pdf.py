"""Exact parser for official full New York law-volume PDFs.

The NY Senate's public ``/pdf/laws/{lawId}?full=true`` endpoint emits one
machine-text PDF containing every current leaf in a law tree.  It is a much
smaller acquisition frontier than walking every HTML section page and does not
require an Open Legislation API key.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Dict, Iterable, List, Mapping, Optional
from urllib.parse import quote, urlparse

from .base_scraper import NormalizedStatute, StatuteMetadata

PDF_BASE = "https://legislation.nysenate.gov/pdf/laws"
PUBLIC_LAW_BASE = "https://www.nysenate.gov/legislation/laws"
AGM28_LIFECYCLE_REPORT_URL = (
    "https://agriculture.ny.gov/system/files/documents/2023/02/"
    "urbanruralconsumeraccessreport.pdf"
)
AGM28_LIFECYCLE_REPORT_SHA256 = (
    "6abaab50ad7bf3bec0c5c98949de8d543bdb4fb8b869f13a824776d39ed8580d"
)
AGM28_LIFECYCLE_SELECTOR_KEY = "AGM:28"
SUPPLEMENTAL_PROOF_SCHEMA_VERSION = "new-york-supplemental-proof-input-v1"
SUPPLEMENTAL_RESOLUTION_SCHEMA_VERSION = (
    "new-york-supplemental-proof-resolution-v1"
)
_WS = re.compile(r"\s+")
_SECTION_ID_PATTERN = (
    r"(?=[0-9A-Za-z.-]*[0-9])"
    r"[0-9A-Za-z]+(?:\.[0-9]+|-[0-9A-Za-z]+)*"
)
_SECTION_HEADER_RE = re.compile(
    r"(?m)^[ \t]*(?P<annotated>\*+[ \t]*)?§(?!§)[ \t]+"
    rf"(?P<section>{_SECTION_ID_PATTERN})"
    r"(?P<header_suffix>(?:\.\*?|\*\.?))?(?:[ \t]+|(?=$))"
)
_SECTION_MARKER_RE = re.compile(r"(?m)^[ \t]*(?:\*+[ \t]*)?§(?!§)")
_BARE_ANNOTATED_SECTION_HEADER_RE = re.compile(
    r"(?m)^[ \t]*(?P<annotated>\*+)[ \t]+"
    rf"(?P<section>{_SECTION_ID_PATTERN})"
    r"(?P<terminal_dot>\.)?[ \t]+"
)
_BARE_BODY_SECTION_HEADER_RE = re.compile(
    r"(?mi)^[ \t]*"
    rf"(?P<section>{_SECTION_ID_PATTERN})"
    r"(?P<terminal_dot>\.)?[ \t]+(?P<heading>[^\n]*)$"
)
_WORD_SECTION_HEADER_RE = re.compile(
    r"(?mi)^[ \t]*(?P<annotated>\*+[ \t]*)?Section[ \t]+"
    rf"(?P<section>{_SECTION_ID_PATTERN})"
    r"(?P<terminal_dot>\.)?[ \t]+(?P<heading>[^\n]*)$"
)
_RULE_SECTION_HEADER_RE = re.compile(
    r"(?mi)^[ \t]*(?P<annotated>\*+[ \t]*)?Rule"
    r"(?:\.[ \t]*|[ \t]+)"
    rf"(?P<section>{_SECTION_ID_PATTERN})"
    r"(?P<terminal_dot>\.)?[ \t]+(?P<heading>[^\n]*)$"
)
_TOC_FIRST_RE = re.compile(
    rf"^(?P<indent>[ \t]*)(?:\*+[ \t]*)?(?:Section|SECTION)[ \t]+"
    rf"(?P<section>{_SECTION_ID_PATTERN})"
    r"(?P<variant>\*[0-9]+)?(?:\.[ \t]*|[ \t]+)"
    r"(?P<heading>.*)$"
)
_TOC_CONTINUATION_RE = re.compile(
    rf"^(?P<indent>[ \t]+)(?:\*+[ \t]*)?"
    rf"(?P<section>{_SECTION_ID_PATTERN})"
    r"(?P<variant>\*[0-9]+)?(?P<separator>\.[ \t]*|[ \t]+)"
    r"(?P<heading>.*)$"
)
_UCC_SECTION_ID_PATTERN = (
    r"(?=[0-9A-Za-z-]*[0-9])"
    r"[0-9A-Za-z]+(?:-{1,2}[0-9A-Za-z]+)+"
)
_UCC_SECTION_HEADER_RE = re.compile(
    rf"(?m)^[ \t]*(?:(?P<word>Section)[ \t]+|§[ \t]+)"
    rf"(?P<section>{_UCC_SECTION_ID_PATTERN})\."
    r"[ \t]*(?P<heading>[^\n]*)$",
    re.IGNORECASE,
)
_UCC_TOC_FIRST_RE = re.compile(
    rf"^[ \t]*Section[ \t]+(?P<section>{_UCC_SECTION_ID_PATTERN})\."
    r"[ \t]*(?P<heading>.*)$",
    re.IGNORECASE,
)
_UCC_TOC_CONTINUATION_RE = re.compile(
    rf"^[ \t]+(?P<section>{_UCC_SECTION_ID_PATTERN})\."
    r"[ \t]+(?P<heading>.*)$",
    re.IGNORECASE,
)
_EMBEDDED_COMPACT_INTRO_RE = re.compile(
    r"\bcompact\s+is\s+as\s+follows\s*:",
    re.IGNORECASE,
)
_AMENDATORY_QUOTE_RE = re.compile(
    r"\bsection\s+(?P<section>[0-9A-Za-z.-]+)\s+of\b.{0,220}?"
    r"\bamended\s+to\s+read\s+as\s+follows\s*:",
    re.IGNORECASE | re.DOTALL,
)
_TERMINAL_RE = re.compile(
    r"^[\[(]?(repealed|reserved|expired|omitted|transferred|renumbered)\b",
    re.IGNORECASE,
)
_EXPLICIT_RELEASE_DATE = date(2026, 8, 26)
_INSURANCE_UNJUXTAPOSED_SPECIAL_NOTE = (
    "Notwithstanding that Chapter 585 of the Laws of 1984: Bill sections 2, "
    "3, 5, 6, 7, and 9 of such chapter amend provisions of the former "
    "Insurance Law that are not possible to juxtapose at this time due to "
    "the highly technical nature of such changes and will need future "
    "corrective legislation to implement such provisions into the new "
    "Insurance Law as enacted by such Chapter 367 of the Laws of 1984."
)
_SEPARATELY_AMENDED_HEADING_RE = re.compile(
    rf"(?:§[ \t]*)?(?P<section>{_SECTION_ID_PATTERN})[ \t]+"
    r"Heading[ \t]+separately[ \t]+amended;[ \t]+cannot[ \t]+be[ \t]+"
    r"put[ \t]+together\.?",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class _PdfLine:
    start: int
    text: str


@dataclass(frozen=True)
class _TocEntry:
    section: str
    heading: str
    start: int
    variant_label: str = ""
    lifecycle_note: str = ""


@dataclass
class _TocBlock:
    toc_start: int
    body_start: int
    entries: List[_TocEntry]
    source_order: int = 0
    # ``-1`` is an authoritative TOC identity with no body header.  Keeping
    # the slot preserves exact source-order algebra while letting later rows
    # in the same generated inventory align independently.
    selected_header_indexes: List[int] = field(default_factory=list)
    corrected_first_identity: bool = False
    leading_terminal_count: int = 0


@dataclass
class _SourceUnit:
    section: str
    printed_section: str
    heading: str
    header_index: int
    block_index: int
    block_entry_index: int
    source_order: int
    variant_label: str = ""
    lifecycle_note: str = ""
    block_lifecycle_note: str = ""
    chunk_end: int = 0
    variant_header_indexes: List[int] = field(default_factory=list)
    inventory_header_indexes: List[int] = field(default_factory=list)


@dataclass
class NewYorkLawPdfParseResult:
    """Source-node reconciliation for one official law-volume PDF."""

    law_code: str
    law_name: str
    statutes: List[NormalizedStatute] = field(default_factory=list)
    terminal_sections: List[Dict[str, str]] = field(default_factory=list)
    embedded_section_markers: List[Dict[str, str]] = field(default_factory=list)
    lifecycle_alternate_sections: List[Dict[str, str]] = field(default_factory=list)
    conditional_event_selectors: Dict[str, Dict[str, Any]] = field(
        default_factory=dict
    )
    # Resolution attempts are diagnostic until a fixed, source-bound resolver
    # returns a decision.  Merely retaining a supplemental page never changes
    # an operative/terminal disposition.
    supplemental_proof_attempts: List[Dict[str, Any]] = field(
        default_factory=list
    )
    toc_body_corrections: List[Dict[str, str]] = field(default_factory=list)
    unclassified_sections: List[Dict[str, str]] = field(default_factory=list)
    raw_section_marker_count: int = 0
    toc_section_count: int = 0
    source_section_count: int = 0
    # Authoritative generated-TOC identities for which no body marker aligned.
    # These remain source nodes (normally typed residuals or terminal headings)
    # but must sit on the raw-marker side of the reconciliation equation.
    source_sections_without_raw_markers: int = 0
    release_date: str = _EXPLICIT_RELEASE_DATE.isoformat()
    page_count: int = 0
    closed: bool = False


@dataclass(frozen=True)
class NewYorkSupplementalProofInput:
    """One exact supplemental source input with no embedded decision claim."""

    selector_key: str
    proof_kind: str
    official_url: str
    media_type: str
    content_sha256: str
    payload: bytes = field(repr=False)
    schema_version: str = SUPPLEMENTAL_PROOF_SCHEMA_VERSION

    @classmethod
    def bind(
        cls,
        *,
        selector_key: str,
        proof_kind: str,
        official_url: str,
        media_type: str,
        payload: bytes,
    ) -> "NewYorkSupplementalProofInput":
        key = str(selector_key or "").strip()
        kind = str(proof_kind or "").strip()
        url = str(official_url or "").strip()
        resolved_media_type = str(media_type or "").strip().lower()
        body = bytes(payload or b"")
        parsed = urlparse(url)
        host = str(parsed.hostname or "").strip().lower()
        if not key:
            raise ValueError("New York supplemental proof selector must be non-empty")
        if kind not in {"official_event_report", "official_senate_section"}:
            raise ValueError("New York supplemental proof kind is not source-bound")
        if (
            parsed.scheme != "https"
            or not host
            or not (
                host == "www.nysenate.gov"
                or host.endswith(".ny.gov")
            )
        ):
            raise ValueError("New York supplemental proof URL is not official")
        if resolved_media_type not in {"application/pdf", "text/html"}:
            raise ValueError("New York supplemental proof media type is unsupported")
        if not body:
            raise ValueError("New York supplemental proof body must be non-empty")
        return cls(
            selector_key=key,
            proof_kind=kind,
            official_url=url,
            media_type=resolved_media_type,
            content_sha256=hashlib.sha256(body).hexdigest(),
            payload=body,
        )

    def manifest_row(self) -> Dict[str, Any]:
        return {
            "content_sha256": self.content_sha256,
            "media_type": self.media_type,
            "official_url": self.official_url,
            "proof_kind": self.proof_kind,
            "schema_version": self.schema_version,
            "selector_key": self.selector_key,
        }


class NewYorkSupplementalProofRegistry:
    """Fixed resolver registry for exact supplemental New York inputs.

    The registry deliberately exposes no dynamic resolver-registration API.
    Unknown selectors always remain unknown, even when an official page is
    present.  A new decision therefore requires reviewed source code for a
    selector-specific resolver rather than data that asserts its own status.
    """

    def __init__(
        self,
        proofs: Iterable[NewYorkSupplementalProofInput] = (),
    ) -> None:
        by_url: Dict[str, NewYorkSupplementalProofInput] = {}
        for proof in proofs:
            if not isinstance(proof, NewYorkSupplementalProofInput):
                raise TypeError(
                    "New York supplemental proof registry accepts bound inputs only"
                )
            existing = by_url.get(proof.official_url)
            if existing is not None and existing != proof:
                raise ValueError(
                    "New York supplemental proof URL has conflicting bytes or identity"
                )
            by_url[proof.official_url] = proof
        self._by_url = by_url

    def with_inputs(
        self,
        proofs: Iterable[NewYorkSupplementalProofInput],
    ) -> "NewYorkSupplementalProofRegistry":
        return NewYorkSupplementalProofRegistry([*self._by_url.values(), *proofs])

    def input_for_url(
        self,
        official_url: str,
    ) -> Optional[NewYorkSupplementalProofInput]:
        return self._by_url.get(str(official_url or "").strip())

    def manifest(self) -> List[Dict[str, Any]]:
        return [
            proof.manifest_row()
            for proof in sorted(
                self._by_url.values(),
                key=lambda item: (item.official_url, item.selector_key),
            )
        ]

    def manifest_sha256(self) -> str:
        return hashlib.sha256(
            json.dumps(
                self.manifest(),
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()

    def resolve_agm28(
        self,
        *,
        legal_as_of: date = _EXPLICIT_RELEASE_DATE,
    ) -> Optional[Dict[str, Any]]:
        proof = self.input_for_url(AGM28_LIFECYCLE_REPORT_URL)
        if proof is None:
            return None
        if (
            proof.selector_key != AGM28_LIFECYCLE_SELECTOR_KEY
            or proof.proof_kind != "official_event_report"
            or proof.media_type != "application/pdf"
        ):
            raise ValueError("New York AGM 28 proof input changed source identity")
        return evaluate_new_york_agm28_lifecycle_report(
            proof.payload,
            source_url=proof.official_url,
            legal_as_of=legal_as_of,
        )

    def resolve_residual(
        self,
        *,
        law_code: str,
        residual: Mapping[str, Any],
    ) -> Dict[str, Any]:
        """Return a diagnostic unknown result for every unimplemented resolver."""

        code = str(law_code or "").strip().upper()
        section = str(residual.get("section_number") or "").strip()
        variant = str(residual.get("toc_variant") or "").strip()
        reason = str(residual.get("reason") or "").strip()
        detail = str(residual.get("detail") or "").strip()
        disposition = detail.split(":", 1)[0] if ":" in detail else ""
        selector_key = ":".join(
            part
            for part in (
                code,
                f"{section}{variant}",
                reason,
                disposition,
            )
            if part
        )
        section_url = public_section_url(code, section) if code and section else ""
        proof = self.input_for_url(section_url) if section_url else None
        outcome: Dict[str, Any] = {
            "decision_action": None,
            "proof_present": proof is not None,
            "reason": (
                "source_bound_resolver_not_implemented"
                if proof is not None
                else "proof_input_missing"
            ),
            "schema_version": SUPPLEMENTAL_RESOLUTION_SCHEMA_VERSION,
            "selector_key": selector_key,
            "status": "unknown",
        }
        if proof is not None:
            outcome["proof"] = proof.manifest_row()
        outcome["resolution_sha256"] = hashlib.sha256(
            json.dumps(
                outcome,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        return outcome


def reconcile_new_york_supplemental_proofs(
    report: NewYorkLawPdfParseResult,
    registry: Optional[NewYorkSupplementalProofRegistry],
) -> NewYorkLawPdfParseResult:
    """Invoke every fixed resolver without admitting generic proof claims."""

    if registry is None:
        return report
    report.supplemental_proof_attempts = [
        registry.resolve_residual(law_code=report.law_code, residual=row)
        for row in report.unclassified_sections
    ]
    return report


def full_law_pdf_url(law_code: str) -> str:
    code = str(law_code or "").strip().upper()
    return f"{PDF_BASE}/{quote(code, safe='')}?full=true"


def _agm28_active_xmp_metadata(payload: bytes) -> Dict[str, str]:
    """Read only the active XMP object, not stale incremental revisions."""

    try:
        from pypdf import PdfReader

        xmp = PdfReader(io.BytesIO(bytes(payload or b""))).xmp_metadata
    except Exception:
        return {}
    if xmp is None:
        return {}
    creators = getattr(xmp, "dc_creator", None)
    creator = (
        str(creators[0]).strip()
        if isinstance(creators, list) and creators
        else ""
    )
    create_date = getattr(xmp, "xmp_create_date", None)
    modify_date = getattr(xmp, "xmp_modify_date", None)
    return {
        "creator": creator,
        "create_date": (
            create_date.isoformat() if isinstance(create_date, datetime) else ""
        ),
        "modify_date": (
            modify_date.isoformat() if isinstance(modify_date, datetime) else ""
        ),
    }


def _agm28_metadata_date(value: str) -> Optional[date]:
    normalized = str(value or "").strip()
    if not normalized:
        return None
    try:
        return datetime.fromisoformat(normalized.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def evaluate_new_york_agm28_lifecycle_report(
    payload: bytes,
    *,
    source_url: str,
    legal_as_of: date = _EXPLICIT_RELEASE_DATE,
) -> Dict[str, Any]:
    """Resolve AGM § 28 only from the exact official report conjunction.

    Publication or report existence is deliberately insufficient.  Occurrence
    requires the report itself to identify the exact 2022 report, reproduce
    the delivery duty to both recipients, state that submission of *this*
    report concludes the statutory requirement, and carry department-authored
    XMP metadata dated on or before the legal observation date.
    """

    if not isinstance(legal_as_of, date):
        raise TypeError("legal_as_of must be a date")
    body = bytes(payload or b"")
    exact_source = str(source_url or "").strip() == AGM28_LIFECYCLE_REPORT_URL
    content_sha256 = hashlib.sha256(body).hexdigest()
    exact_retained_report = content_sha256 == AGM28_LIFECYCLE_REPORT_SHA256
    valid_pdf = len(body) > 1_000 and body.lstrip().startswith(b"%PDF")
    try:
        extracted, page_count = extract_new_york_law_pdf_text(body)
    except Exception:
        extracted, page_count = "", 0
    visible = _WS.sub(
        " ", unicodedata.normalize("NFKC", str(extracted or ""))
    ).strip().casefold()

    title_marker = (
        "nys advisory group for improving urban and rural consumer access to "
        "locally produced, healthy foods 2022 report"
    )
    delivery_marker = (
        "a report shall be delivered by the commissioner to the governor and "
        "the legislature"
    )
    conclusion_marker = (
        "the statutory requirement for this group concludes upon submission "
        "of this report"
    )
    identifies_exact_report = title_marker in visible
    states_both_recipients = delivery_marker in visible
    states_this_report_concludes_requirement = conclusion_marker in visible

    active_xmp = _agm28_active_xmp_metadata(body)
    create_raw = str(active_xmp.get("create_date") or "").strip()
    modify_raw = str(active_xmp.get("modify_date") or "").strip()
    creator = str(active_xmp.get("creator") or "").strip()
    parsed_dates = [
        parsed
        for parsed in (
            _agm28_metadata_date(create_raw),
            _agm28_metadata_date(modify_raw),
        )
        if parsed is not None
    ]
    metadata_date = max(parsed_dates) if parsed_dates else None
    authoritative_metadata = bool(active_xmp) and (
        "(agriculture)" in creator.casefold()
    )
    dated_on_or_before_legal_as_of = bool(
        authoritative_metadata
        and metadata_date is not None
        and metadata_date <= legal_as_of
    )
    conjuncts = {
        "exact_official_source": exact_source,
        "exact_retained_report_sha256": exact_retained_report,
        "valid_pdf": valid_pdf and page_count > 0,
        "identifies_exact_2022_report": identifies_exact_report,
        "states_delivery_to_governor_and_legislature": states_both_recipients,
        "states_submission_of_this_report_concludes_requirement": (
            states_this_report_concludes_requirement
        ),
        "authoritative_dated_metadata_on_or_before_legal_as_of": (
            dated_on_or_before_legal_as_of
        ),
    }
    status = "occurred" if all(conjuncts.values()) else "unknown"
    outcome: Dict[str, Any] = {
        "schema_version": "new-york-agm28-lifecycle-selector-v1",
        "selector_key": AGM28_LIFECYCLE_SELECTOR_KEY,
        "status": status,
        "legal_as_of": legal_as_of.isoformat(),
        "source_url": str(source_url or "").strip(),
        "content_sha256": content_sha256,
        "page_count": int(page_count),
        "metadata": {
            "creator": creator,
            "create_date": create_raw or None,
            "modify_date": modify_raw or None,
            "date_basis": metadata_date.isoformat() if metadata_date else None,
        },
        "conjuncts": conjuncts,
    }
    outcome["selector_decision_sha256"] = hashlib.sha256(
        json.dumps(
            outcome,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    return outcome


def public_section_url(law_code: str, section_number: str) -> str:
    code = quote(str(law_code or "").strip().upper(), safe="")
    section = quote(str(section_number or "").strip(), safe=".-")
    return f"{PUBLIC_LAW_BASE}/{code}/{section}"


def _boundary_line_key(line: str) -> str:
    return _WS.sub(" ", str(line or "")).strip()


def extract_new_york_law_pdf_text(payload: bytes) -> tuple[str, int]:
    """Extract text while dropping only unambiguous numeric page chrome.

    A repeated first/last line is not sufficient evidence that a line is PDF
    chrome.  The official law-volume generator regularly puts repeated
    statutory text, ``* NB`` lifecycle annotations, and repeated-identity
    section headers on page boundaries.  Removing those lines corrupts both
    the retained text and the exact source frontier, so only a standalone
    numeric page marker is discarded here.
    """

    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover - production dependency gate
        raise RuntimeError("pypdf is required for New York law PDFs") from exc

    reader = PdfReader(io.BytesIO(bytes(payload)), strict=False)
    raw_pages = [str(page.extract_text() or "") for page in reader.pages]
    page_lines: List[List[str]] = []
    for page_text in raw_pages:
        lines = page_text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        page_lines.append(lines)
    cleaned_pages: List[str] = []
    for lines in page_lines:
        nonempty_indexes = [
            index for index, line in enumerate(lines) if _boundary_line_key(line)
        ]
        boundary_indexes = set(nonempty_indexes[:2] + nonempty_indexes[-2:])
        kept: List[str] = []
        for index, line in enumerate(lines):
            key = _boundary_line_key(line)
            if index in boundary_indexes and re.fullmatch(r"-?\s*\d+\s*-?", key):
                continue
            kept.append(line)
        cleaned_pages.append("\n".join(kept))
    return "\n".join(cleaned_pages), len(raw_pages)


def _section_heading(chunk_after_marker: str, section_number: str) -> str:
    value = _WS.sub(" ", str(chunk_after_marker or "")).strip()
    if not value:
        return f"Section {section_number}"
    sentence = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9\[(])", value, maxsplit=1)[0]
    return sentence.strip(" .")[:200] or f"Section {section_number}"


def _pdf_lines(text: str) -> List[_PdfLine]:
    lines: List[_PdfLine] = []
    offset = 0
    for raw_line in str(text or "").splitlines(keepends=True):
        lines.append(_PdfLine(offset, raw_line.rstrip("\r\n")))
        offset += len(raw_line)
    return lines


def _toc_continuation_is_leaf(match, *, baseline_indent: int) -> bool:
    """Reject a wrapped heading line that merely starts with a citation.

    Generated continuation rows either carry a terminal separator dot or
    align within twelve columns of the inventory's ``Section`` row.  Deeply
    indented, dotless lines are wrapped heading text (for example TAX's
    ``2032A of the internal revenue code``), not independent source leaves.
    """

    separator = str(match.group("separator") or "")
    if separator.lstrip().startswith("."):
        return True
    indent = len(str(match.group("indent") or "").expandtabs(8))
    return indent <= int(baseline_indent) + 12


def _heading_key(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", str(value or "").casefold()))


def _headings_prove_same_identity(expected: str, observed: str) -> bool:
    expected_key = _heading_key(expected)
    observed_key = _heading_key(observed)
    return bool(
        len(expected_key) >= 8
        and (
            observed_key == expected_key
            or observed_key.startswith(expected_key + " ")
        )
    )


def _confusable_section_key(value: str) -> str:
    return str(value or "").casefold().replace("l", "1").replace("o", "0")


def _raw_header_after_text(text: str, matches, index: int) -> str:
    end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
    return _WS.sub(" ", text[matches[index].end() : end]).strip()


def _source_header_matches(
    text: str,
    *,
    missing_toc_entries: Optional[List[Dict[str, str]]] = None,
):
    primary = list(_SECTION_HEADER_RE.finditer(text))
    expected = {
        str(row.get("section_number") or "").casefold(): str(
            row.get("toc_heading") or ""
        )
        for row in (missing_toc_entries or [])
    }
    if not expected:
        return primary
    bare = list(_BARE_ANNOTATED_SECTION_HEADER_RE.finditer(text))
    bare_bodies = list(_BARE_BODY_SECTION_HEADER_RE.finditer(text))
    rules = list(_RULE_SECTION_HEADER_RE.finditer(text))
    boundary_candidates = sorted(
        [*primary, *bare, *rules], key=lambda match: match.start()
    )
    all_candidates = sorted(
        [*primary, *bare, *bare_bodies, *rules],
        key=lambda match: match.start(),
    )
    admitted_supplements = []
    for candidate_index, match in enumerate(all_candidates):
        if match.re not in (
            _BARE_ANNOTATED_SECTION_HEADER_RE,
            _BARE_BODY_SECTION_HEADER_RE,
            _RULE_SECTION_HEADER_RE,
        ):
            continue
        section = str(match.group("section") or "").strip()
        if section.casefold() not in expected:
            continue
        end = next(
            (
                candidate.start()
                for candidate in boundary_candidates
                if candidate.start() > match.start()
            ),
            len(text),
        )
        annotation = re.search(
            r"(?mi)^[ \t]*\*[ \t]*NB[ \t]+",
            text[match.end() : end],
        )
        if annotation is not None:
            end = match.end() + annotation.start()
        body = _WS.sub(" ", text[match.end() : end]).strip()
        is_rule = match.re is _RULE_SECTION_HEADER_RE
        is_bare_body = match.re is _BARE_BODY_SECTION_HEADER_RE
        observed_heading = (
            str(match.group("heading") or "").strip()
            if is_rule or is_bare_body
            else _section_heading(body, section)
        )
        expected_heading = expected[section.casefold()]
        expected_key = _heading_key(expected_heading)
        observed_key = _heading_key(observed_heading)
        heading_proved = (
            bool(expected_key)
            and (
                observed_key == expected_key
                or observed_key.startswith(expected_key + " ")
            )
            if is_rule or is_bare_body
            else _headings_prove_same_identity(
                expected_heading,
                observed_heading,
            )
        )
        first_body_after_toc = 0
        if is_bare_body:
            toc_offsets = [
                int(offset.group(1))
                for row in (missing_toc_entries or [])
                if str(row.get("section_number") or "").casefold()
                == section.casefold()
                and (
                    offset := re.search(
                        r"\btoc_offset=(\d+)\b",
                        str(row.get("detail") or ""),
                    )
                )
                is not None
            ]
            controlling_toc_offset = max(
                (offset for offset in toc_offsets if offset < match.start()),
                default=-1,
            )
            first_body_after_toc = next(
                (
                    candidate.start()
                    for candidate in primary
                    if candidate.start() > controlling_toc_offset
                ),
                len(text),
            )
            # Generated inventory rows repeat only the heading.  The admitted
            # bare body must occur after that inventory's first § body and add
            # inline statutory text after the exact normalized heading.
            heading_proved = bool(
                heading_proved
                and match.start() > first_body_after_toc
                and not expected_key.startswith("of ")
                and observed_key.startswith(expected_key + " ")
            )
        substantive_length = (
            len(body) + max(0, len(observed_heading) - len(expected_heading))
            if is_rule or is_bare_body
            else len(body)
        )
        # A starred continuation in a TOC is short; the rare official body
        # form without § (GMU 72-k*2), and a CPLR ``Rule`` body, has a
        # substantive retained body whose heading repeats the source TOC.
        if (
            substantive_length >= (40 if is_rule or is_bare_body else 240)
            and heading_proved
        ):
            admitted_supplements.append(match)
    return sorted(
        [*primary, *admitted_supplements], key=lambda match: match.start()
    )


def _source_bound_word_header_supplements(
    text: str,
    primary_matches,
    units: List[_SourceUnit],
):
    """Find a substantive ``Section`` body before the first § body.

    This covers TAX §1500 while excluding quoted/nested ``Section`` forms:
    the candidate must repeat the immediately preceding official TOC first
    row, occur before any § body for that inventory, and lie outside an
    already TOC-bounded parent interval.
    """

    lines = _pdf_lines(text)
    toc_first_rows = [
        (line.start, match)
        for line in lines
        if (match := _TOC_FIRST_RE.match(line.text)) is not None
    ]
    supplements = []
    for candidate in _WORD_SECTION_HEADER_RE.finditer(text):
        section = str(candidate.group("section") or "").strip()
        preceding = [
            (start, row)
            for start, row in toc_first_rows
            if start < candidate.start()
            and candidate.start() - start <= 200_000
            and str(row.group("section") or "").casefold()
            == section.casefold()
        ]
        if not preceding:
            continue
        toc_start, toc_row = preceding[-1]
        if candidate.start() == toc_start:
            continue
        next_primary = next(
            (
                match
                for match in primary_matches
                if match.start() > toc_start
            ),
            None,
        )
        if next_primary is not None and candidate.start() > next_primary.start():
            continue
        if _inside_source_bounded_interval(candidate.start(), units, primary_matches):
            continue
        toc_heading = str(toc_row.group("heading") or "").strip()
        body_heading = str(candidate.group("heading") or "").strip()
        if len(body_heading) < len(toc_heading) + 20:
            continue
        supplements.append(candidate)
    return supplements


def _extract_standard_toc_blocks(text: str, matches) -> List[_TocBlock]:
    """Return source-order TOC blocks whose first body identity is proved.

    The official generator emits a local ``Section ...`` inventory before
    each article/title body.  Prose can also begin with the word ``Section``,
    so a candidate is admitted only when its first inventory identity matches
    the immediately following body header, or their headings prove an official
    printed-number correction.
    """

    lines = _pdf_lines(text)
    header_by_start = {match.start(): index for index, match in enumerate(matches)}
    candidates: List[_TocBlock] = []
    for line_index, line in enumerate(lines):
        first = _TOC_FIRST_RE.match(line.text)
        if first is None:
            continue
        if re.search(
            r"\bamended\b.{0,120}\bto[ \t]+read[ \t]+as(?:[ \t]+follows)?\b",
            str(first.group("heading") or ""),
            re.IGNORECASE,
        ):
            # Enacting wrappers can be followed by an article-level contents
            # list.  They are quoted legislative structure, not the generated
            # leaf ``Section`` inventory for the law body.
            continue
        entries: List[_TocEntry] = []
        first_header_start: Optional[int] = None
        for following in lines[line_index:]:
            if following.start - line.start > 200_000:
                break
            if following.start in header_by_start:
                first_header_start = following.start
                break
            entry = _TOC_FIRST_RE.match(following.text)
            if entry is None:
                entry = _TOC_CONTINUATION_RE.match(following.text)
                if entry is not None and not _toc_continuation_is_leaf(
                    entry,
                    baseline_indent=len(
                        str(first.group("indent") or "").expandtabs(8)
                    ),
                ):
                    entry = None
            if entry is not None:
                entries.append(
                    _TocEntry(
                        section=str(entry.group("section") or "").strip(),
                        heading=str(entry.group("heading") or "").strip(),
                        start=following.start,
                        variant_label=str(entry.group("variant") or "").strip(),
                    )
                )
                continue
            note = re.match(
                r"^[ \t]*\*[ \t]*NB[ \t]+(?P<note>.*)$",
                following.text,
                re.IGNORECASE,
            )
            if note is not None and entries:
                previous = entries[-1]
                entries[-1] = _TocEntry(
                    section=previous.section,
                    heading=previous.heading,
                    start=previous.start,
                    variant_label=previous.variant_label,
                    lifecycle_note=_WS.sub(
                        " ", str(note.group("note") or "")
                    ).strip(),
                )
        if first_header_start is None or not entries:
            continue
        # A bare ``Section N.`` inside an explanatory footnote is not a
        # source inventory entry.  Real generated TOC rows always carry a
        # heading (possibly continued on the following line).
        entries = [entry for entry in entries if _heading_key(entry.heading)]
        if not entries:
            continue
        # A page-boundary sub-TOC can be printed before the final body section
        # of the preceding block.  Locate the first matching body identity in
        # the next four headers instead of requiring it to be the first one.
        first_header_index = header_by_start[first_header_start]
        leading_terminal_count = 0
        for entry in entries:
            if re.match(
                r"^(?:intentionally[ \t]+)?"
                r"(?:repealed|reserved|expired|omitted|transferred|renumbered)\b",
                _WS.sub(" ", entry.heading).strip(),
                re.IGNORECASE,
            ) is None:
                break
            leading_terminal_count += 1
        if leading_terminal_count >= len(entries):
            continue
        expected = entries[leading_terminal_count]
        body_index: Optional[int] = None
        corrected_identity = False
        for candidate_index in range(
            first_header_index,
            min(len(matches), first_header_index + 4),
        ):
            observed_section = str(
                matches[candidate_index].group("section") or ""
            ).strip()
            if expected.section.casefold() == observed_section.casefold():
                if candidate_index != first_header_index:
                    observed_heading = _section_heading(
                        _raw_header_after_text(text, matches, candidate_index),
                        observed_section,
                    )
                    if not _headings_prove_same_identity(
                        expected.heading,
                        observed_heading,
                    ):
                        continue
                body_index = candidate_index
                break
        if body_index is None:
            # A correction is authoritative only at the immediate generated
            # body boundary and only when the TOC/body headings agree.  This
            # admits PBG's printed 455/official 445 correction without using a
            # remotely similar later section as a substitute.
            candidate_index = first_header_index
            observed_section = str(
                matches[candidate_index].group("section") or ""
            ).strip()
            observed_heading = _section_heading(
                _raw_header_after_text(text, matches, candidate_index),
                observed_section,
            )
            if _headings_prove_same_identity(expected.heading, observed_heading):
                body_index = candidate_index
                corrected_identity = True
        if body_index is None:
            continue
        body_start = matches[body_index].start()
        # A repeated first row immediately before the body can either be a
        # generated local sub-TOC (TAX article 37) or the real inventory after
        # an enacting wrapper (WKC).  Body-heading identity determines which
        # side is authoritative.
        for entry_index in range(leading_terminal_count + 1, len(entries)):
            if (
                entries[entry_index].section.casefold()
                == entries[leading_terminal_count].section.casefold()
                and not entries[entry_index].variant_label
            ):
                observed_section = str(
                    matches[body_index].group("section") or ""
                ).strip()
                observed_heading = _section_heading(
                    _raw_header_after_text(text, matches, body_index),
                    observed_section,
                )
                first_proves = _headings_prove_same_identity(
                    entries[leading_terminal_count].heading,
                    observed_heading,
                )
                repeated_proves = _headings_prove_same_identity(
                    entries[entry_index].heading,
                    observed_heading,
                )
                entries = (
                    [
                        *entries[:leading_terminal_count],
                        *entries[entry_index:],
                    ]
                    if repeated_proves and not first_proves
                    else entries[:entry_index]
                )
                break
        candidates.append(
            _TocBlock(
                toc_start=line.start,
                body_start=body_start,
                entries=entries,
                corrected_first_identity=corrected_identity,
                leading_terminal_count=leading_terminal_count,
            )
        )

    # A few official volumes omit the literal ``Section`` label while still
    # printing a generated, indented schedule immediately after an
    # ARTICLE/TITLE/PART boundary (for example EDN part 2).  Admit that source
    # inventory only when it has at least two heading-bearing rows and its
    # first nonterminal identity/heading agrees with the first body marker.
    structural_lines = [
        (line_index, line)
        for line_index, line in enumerate(lines)
        if (
            re.match(
                r"^[ \t]*(?:ARTICLE|TITLE|PART)[ \t]+[0-9A-Za-z.-]+[ \t]*$",
                line.text,
            )
            or (
                4 <= len(line.text.strip()) <= 180
                and line.text.strip().upper() == line.text.strip()
                and re.search(r"[A-Z]", line.text)
                and not re.match(
                    r"^[ \t]*(?:SECTION|§)",
                    line.text,
                    re.IGNORECASE,
                )
            )
        )
    ]
    for structural_index, (line_index, structural_line) in enumerate(
        structural_lines
    ):
        structural_end = (
            structural_lines[structural_index + 1][1].start
            if structural_index + 1 < len(structural_lines)
            else len(text)
        )
        first_header = next(
            (
                (start, header_index)
                for start, header_index in sorted(header_by_start.items())
                if structural_line.start < start < structural_end
                and start - structural_line.start <= 200_000
            ),
            None,
        )
        if first_header is None:
            continue
        first_header_start, first_header_index = first_header
        entries: List[_TocEntry] = []
        for line in lines[line_index + 1 :]:
            if line.start >= first_header_start:
                break
            entry = _TOC_CONTINUATION_RE.match(line.text)
            if entry is not None and not _toc_continuation_is_leaf(
                entry,
                baseline_indent=len(
                    structural_line.text
                ) - len(structural_line.text.lstrip(" \t")),
            ):
                entry = None
            if entry is None or not _heading_key(str(entry.group("heading") or "")):
                continue
            entries.append(
                _TocEntry(
                    section=str(entry.group("section") or "").strip(),
                    heading=str(entry.group("heading") or "").strip(),
                    start=line.start,
                    variant_label=str(entry.group("variant") or "").strip(),
                )
            )
        if len(entries) < 2:
            continue
        leading_terminal_count = 0
        for entry in entries:
            if re.match(
                r"^(?:intentionally[ \t]+)?"
                r"(?:repealed|reserved|expired|omitted|transferred|renumbered)\b",
                _WS.sub(" ", entry.heading).strip(),
                re.IGNORECASE,
            ) is None:
                break
            leading_terminal_count += 1
        if leading_terminal_count >= len(entries):
            continue
        expected = entries[leading_terminal_count]
        observed = str(
            matches[first_header_index].group("section") or ""
        ).strip()
        observed_heading = _section_heading(
            _raw_header_after_text(text, matches, first_header_index),
            observed,
        )
        exact_identity = expected.section.casefold() == observed.casefold()
        corrected_identity = bool(
            not exact_identity
            and _headings_prove_same_identity(expected.heading, observed_heading)
        )
        if not exact_identity and not corrected_identity:
            continue
        candidates.append(
            _TocBlock(
                toc_start=entries[0].start,
                body_start=first_header_start,
                entries=entries,
                corrected_first_identity=corrected_identity,
                leading_terminal_count=leading_terminal_count,
            )
        )

    # A later ``Section`` line in the same inventory produces the same body
    # candidate.  Keep the earliest, complete source inventory only.
    by_body_start: Dict[int, _TocBlock] = {}
    for candidate in candidates:
        by_body_start.setdefault(candidate.body_start, candidate)
    blocks = sorted(by_body_start.values(), key=lambda row: row.toc_start)
    for source_order, block in enumerate(blocks):
        block.source_order = source_order
    return blocks


def _amendatory_quote_uses_next_duplicate(
    text: str,
    matches,
    *,
    previous_header_index: int,
    candidate_header_index: int,
    section: str,
) -> bool:
    if candidate_header_index + 1 >= len(matches):
        return False
    if (
        str(matches[candidate_header_index + 1].group("section") or "").casefold()
        != str(section or "").casefold()
    ):
        return False
    start = matches[max(0, previous_header_index)].start()
    context = text[start : matches[candidate_header_index].start()]
    quoted = list(_AMENDATORY_QUOTE_RE.finditer(context))
    return bool(
        quoted
        and str(quoted[-1].group("section") or "").casefold()
        == str(section or "").casefold()
    )


def _align_standard_toc_blocks(
    text: str,
    matches,
    blocks: List[_TocBlock],
) -> tuple[
    List[_TocBlock],
    List[Dict[str, str]],
    List[Dict[str, str]],
]:
    header_by_start = {match.start(): index for index, match in enumerate(matches)}
    accepted: List[_TocBlock] = []
    failures: List[Dict[str, str]] = []
    identity_corrections: List[Dict[str, str]] = []
    covered_interiors: List[tuple[int, int]] = []
    globally_selected: set[int] = set()

    for block in blocks:
        if any(
            start < block.toc_start < end and block.body_start < end
            for start, end in covered_interiors
        ):
            continue
        collapsed_entries: List[_TocEntry] = []
        for entry in block.entries:
            note_match = _SEPARATELY_AMENDED_HEADING_RE.fullmatch(
                _WS.sub(" ", entry.lifecycle_note).strip()
            )
            previous = collapsed_entries[-1] if collapsed_entries else None
            if (
                note_match is not None
                and previous is not None
                and previous.section.casefold() == entry.section.casefold()
                and str(note_match.group("section") or "").casefold()
                == entry.section.casefold()
            ):
                body_candidates = []
                for header_index, match in enumerate(matches):
                    if match.start() < block.body_start:
                        continue
                    observed = str(match.group("section") or "").strip()
                    if observed.casefold() != entry.section.casefold():
                        continue
                    observed_heading = _section_heading(
                        _raw_header_after_text(text, matches, header_index),
                        observed,
                    )
                    if (
                        _headings_prove_same_identity(
                            entry.heading,
                            observed_heading,
                        )
                        and not _headings_prove_same_identity(
                            previous.heading,
                            observed_heading,
                        )
                    ):
                        body_candidates.append(header_index)
                if len(body_candidates) == 1:
                    collapsed_entries[-1] = entry
                    identity_corrections.append(
                        {
                            "section_number": entry.section,
                            "printed_section_number": str(
                                matches[body_candidates[0]].group("section") or ""
                            ).strip(),
                            "reason": (
                                "source_proved_separately_amended_heading_alternate"
                            ),
                            "detail": (
                                f"alternate_heading={previous.heading}; "
                                f"selected_heading={entry.heading}; "
                                f"note={entry.lifecycle_note}"
                            )[:600],
                        }
                    )
                    continue
            collapsed_entries.append(entry)
        block.entries = collapsed_entries
        cursor = header_by_start[block.body_start]
        selected: List[int] = []
        local_failures: List[Dict[str, str]] = []
        corrections: List[tuple[_TocEntry, int]] = []
        for entry_index, entry in enumerate(block.entries):
            if entry_index < block.leading_terminal_count:
                local_failures.append(
                    {
                        "section_number": entry.section,
                        "toc_variant": entry.variant_label,
                        "toc_heading": entry.heading,
                        "reason": "toc_section_missing_body_identity",
                        "detail": f"toc_offset={block.toc_start}",
                    }
                )
                selected.append(-1)
                continue
            target = entry.section.casefold()
            found: Optional[int] = None
            preserve_cursor = False
            if (
                entry_index == block.leading_terminal_count
                and block.corrected_first_identity
            ):
                found = header_by_start[block.body_start]
                corrections.append((entry, found))
            for header_index in range(cursor, len(matches)):
                if found is not None:
                    break
                observed = str(matches[header_index].group("section") or "").strip()
                if observed.casefold() != target:
                    continue
                previous = selected[-1] if selected else max(0, cursor - 1)
                if _amendatory_quote_uses_next_duplicate(
                    text,
                    matches,
                    previous_header_index=previous,
                    candidate_header_index=header_index,
                    section=entry.section,
                ):
                    continue
                found = header_index
                break

            if found is None:
                # Official TOC/body typography occasionally confuses ``l``/``1``
                # or ``O``/``0``.  Correct only when the source-order heading
                # itself proves the identity, never from citation similarity.
                for header_index in range(cursor, min(len(matches), cursor + 8)):
                    observed = str(
                        matches[header_index].group("section") or ""
                    ).strip()
                    if (
                        _confusable_section_key(observed)
                        != _confusable_section_key(entry.section)
                    ):
                        continue
                    observed_heading = _section_heading(
                        _raw_header_after_text(text, matches, header_index),
                        observed,
                    )
                    if _headings_prove_same_identity(entry.heading, observed_heading):
                        found = header_index
                        corrections.append((entry, header_index))
                        break
            if found is None and cursor < len(matches):
                # A retained official body can carry a non-confusable printed
                # number error (ENV's TOC 71-1721/body 17-1721).  Correct only
                # the body at the exact source-order cursor, only when its
                # heading proves the identity, and never consume a printed
                # number claimed by a later TOC row.  A merely similar later
                # body therefore cannot heal a missing source identity.
                header_index = cursor
                observed = str(
                    matches[header_index].group("section") or ""
                ).strip()
                later_toc_identities = {
                    later.section.casefold()
                    for later in block.entries[entry_index + 1 :]
                }
                observed_heading = _section_heading(
                    _raw_header_after_text(text, matches, header_index),
                    observed,
                )
                if (
                    observed.casefold() not in later_toc_identities
                    and _headings_prove_same_identity(
                        entry.heading,
                        observed_heading,
                    )
                ):
                    found = header_index
                    corrections.append((entry, header_index))
            if found is None and len(selected) >= 2:
                # MHY's retained article 9 body prints 9.63 immediately before
                # 9.61 even though its generated inventory orders them 9.61,
                # 9.63.  Admit only that exact adjacent transposition: the
                # otherwise-unassigned preceding body must carry this exact
                # identity and an independently matching heading, and it must
                # remain after the body selected two TOC rows earlier.
                previous_selected = selected[-1]
                preceding_selected = next(
                    (index for index in reversed(selected[:-1]) if index >= 0),
                    -1,
                )
                candidate_index = previous_selected - 1
                if (
                    previous_selected >= 1
                    and preceding_selected < candidate_index
                    and candidate_index not in selected
                    and candidate_index not in globally_selected
                ):
                    observed = str(
                        matches[candidate_index].group("section") or ""
                    ).strip()
                    observed_heading = _section_heading(
                        _raw_header_after_text(text, matches, candidate_index),
                        observed,
                    )
                    if (
                        observed.casefold() == entry.section.casefold()
                        and _headings_prove_same_identity(
                            entry.heading,
                            observed_heading,
                        )
                    ):
                        found = candidate_index
                        preserve_cursor = True
                        identity_corrections.append(
                            {
                                "section_number": entry.section,
                                "printed_section_number": observed,
                                "reason": "adjacent_toc_body_order_inversion",
                                "detail": entry.heading[:200],
                            }
                        )
            if found is None and entry.variant_label:
                # A generated repeated-identity TOC row can retain its source
                # identity after the statutory body has been renumbered.  AGM
                # article 26 is the retained production example: TOC 380*2's
                # exact heading is printed on body § 383, after bodies 381 and
                # 382.  Admit that mismatch only for a variant-labelled row,
                # only when exactly one of the next eight unassigned bodies has
                # the exact normalized heading, and never by consuming an
                # identity that a later TOC row claims.  Keeping the cursor in
                # place lets the intervening source rows align normally.
                later_toc_identities = {
                    later.section.casefold()
                    for later in block.entries[entry_index + 1 :]
                }
                exact_heading_key = _heading_key(entry.heading)
                heading_candidates: List[int] = []
                if exact_heading_key:
                    for header_index in range(
                        cursor,
                        min(len(matches), cursor + 8),
                    ):
                        if (
                            header_index in selected
                            or header_index in globally_selected
                        ):
                            continue
                        observed = str(
                            matches[header_index].group("section") or ""
                        ).strip()
                        if observed.casefold() in later_toc_identities:
                            continue
                        observed_heading = _section_heading(
                            _raw_header_after_text(text, matches, header_index),
                            observed,
                        )
                        if _headings_prove_same_identity(
                            entry.heading,
                            observed_heading,
                        ):
                            heading_candidates.append(header_index)
                if len(heading_candidates) == 1:
                    found = heading_candidates[0]
                    preserve_cursor = True
                    corrections.append((entry, found))
            if found is None:
                local_failures.append(
                    {
                        "section_number": entry.section,
                        "toc_variant": entry.variant_label,
                        "toc_heading": entry.heading,
                        "reason": "toc_section_missing_body_identity",
                        "detail": f"toc_offset={block.toc_start}",
                    }
                )
                selected.append(-1)
                continue
            selected.append(found)
            if not preserve_cursor:
                cursor = found + 1

        selected_present = [index for index in selected if index >= 0]
        if not selected_present:
            continue
        # A candidate inside a previously admitted source body may align to
        # later real sections.  Shared raw indexes prove that it is not another
        # top-level block.
        if any(index in globally_selected for index in selected_present):
            continue
        block.selected_header_indexes = selected
        accepted.append(block)
        failures.extend(local_failures)
        globally_selected.update(selected_present)
        selected_in_body_order = sorted(selected_present)
        for left, right in zip(
            selected_in_body_order,
            selected_in_body_order[1:],
        ):
            covered_interiors.append(
                (matches[left].start(), matches[right].start())
            )
        for entry, header_index in corrections:
            identity_corrections.append(
                {
                    "section_number": entry.section,
                    "printed_section_number": str(
                        matches[header_index].group("section") or ""
                    ).strip(),
                    "reason": "toc_body_identity_correction",
                    "detail": entry.heading[:200],
                }
            )
    return accepted, failures, identity_corrections


def _standard_source_units(
    text: str,
    matches,
    accepted_blocks: List[_TocBlock],
) -> List[_SourceUnit]:
    units: List[_SourceUnit] = []
    source_order = 0
    for block_index, block in enumerate(accepted_blocks):
        block_note = _lifecycle_note(text[block.toc_start : block.body_start])
        for entry_index, (entry, header_index) in enumerate(
            zip(block.entries, block.selected_header_indexes, strict=True)
        ):
            if header_index < 0:
                continue
            printed = str(matches[header_index].group("section") or "").strip()
            units.append(
                _SourceUnit(
                    section=entry.section,
                    printed_section=printed,
                    heading=entry.heading,
                    header_index=header_index,
                    block_index=block_index,
                    block_entry_index=entry_index,
                    source_order=source_order,
                    variant_label=entry.variant_label,
                    lifecycle_note=entry.lifecycle_note,
                    block_lifecycle_note=block_note,
                )
            )
            source_order += 1

    # A heading-proved renumbering can put a variant-labelled TOC identity at
    # a different position in the printed body.  Body order is authoritative
    # for chunk boundaries; ordinary blocks are already in this order, so the
    # sort is a no-op outside that narrowly admitted correction.
    units.sort(key=lambda unit: matches[unit.header_index].start())
    for source_order, unit in enumerate(units):
        unit.source_order = source_order

    for index, unit in enumerate(units):
        block = accepted_blocks[unit.block_index]
        next_same_block = next(
            (
                later
                for later in units[index + 1 :]
                if later.block_index == unit.block_index
            ),
            None,
        )
        if next_same_block is not None:
            unit.chunk_end = matches[next_same_block.header_index].start()
        elif unit.block_index + 1 < len(accepted_blocks):
            next_block = accepted_blocks[unit.block_index + 1]
            next_selected = next(
                (
                    selected
                    for selected in next_block.selected_header_indexes
                    if selected >= 0
                ),
                None,
            )
            if next_block.toc_start > matches[unit.header_index].start():
                unit.chunk_end = next_block.toc_start
            elif next_selected is not None:
                unit.chunk_end = matches[next_selected].start()
            else:
                unit.chunk_end = len(text)
        else:
            unit.chunk_end = len(text)
    return units


def _inside_source_bounded_interval(
    position: int,
    units: List[_SourceUnit],
    matches,
) -> bool:
    for index, unit in enumerate(units):
        if not (
            matches[unit.header_index].start() < position < unit.chunk_end
        ):
            continue
        if (
            index + 1 < len(units)
            and units[index + 1].block_index == unit.block_index
        ):
            return True
    return False


def _augment_body_local_inventory_units(
    text: str,
    matches,
    units: List[_SourceUnit],
) -> List[_SourceUnit]:
    """Admit a body-local ``§`` inventory only when its duplicate proves it.

    EXC article 49-C prints a short heading-only ``§ 996`` inventory and then
    the substantive ``§ 996`` body.  This generic rule requires consecutive
    identical identities, matching headings, and a materially longer second
    body; it does not collapse amendatory quoted text inside a TOC-bounded
    parent.
    """

    selected = {unit.header_index for unit in units}
    additions: List[_SourceUnit] = []
    next_block_index = max((unit.block_index for unit in units), default=-1) + 1
    for first_index in range(len(matches) - 1):
        second_index = first_index + 1
        if first_index in selected or second_index in selected:
            continue
        first = matches[first_index]
        second = matches[second_index]
        section = str(first.group("section") or "").strip()
        if section.casefold() != str(
            second.group("section") or ""
        ).strip().casefold():
            continue
        if _inside_source_bounded_interval(first.start(), units, matches):
            continue
        first_after = _raw_header_after_text(text, matches, first_index)
        second_after = _raw_header_after_text(text, matches, second_index)
        heading_only_inventory = bool(
            20 <= len(first_after) <= 240
            or re.search(
                r"\bNB[ \t]+Added[ \t]+without[ \t]+title\b",
                first_after,
                re.IGNORECASE,
            )
        )
        if not (heading_only_inventory and len(second_after) >= 80):
            continue
        first_heading = _section_heading(first_after, section)
        second_heading = _section_heading(second_after, section)
        if not _headings_prove_same_identity(first_heading, second_heading):
            continue
        boundary = (
            matches[second_index + 1].start()
            if second_index + 1 < len(matches)
            else len(text)
        )
        additions.append(
            _SourceUnit(
                section=section,
                printed_section=str(second.group("section") or "").strip(),
                heading=first_heading,
                header_index=second_index,
                block_index=next_block_index,
                block_entry_index=0,
                source_order=0,
                chunk_end=boundary,
                inventory_header_indexes=[first_index],
            )
        )
        selected.update((first_index, second_index))
        next_block_index += 1

    if not additions:
        return units
    combined = sorted(
        [*units, *additions],
        key=lambda unit: matches[unit.header_index].start(),
    )
    for source_order, unit in enumerate(combined):
        unit.source_order = source_order
    for addition in additions:
        inventory_start = matches[addition.inventory_header_indexes[0]].start()
        predecessor = next(
            (
                unit
                for unit in reversed(combined)
                if matches[unit.header_index].start() < inventory_start
                and unit is not addition
            ),
            None,
        )
        if predecessor is not None and predecessor.chunk_end > inventory_start:
            predecessor.chunk_end = inventory_start
    return combined


def _augment_local_generated_inventory_units(
    text: str,
    matches,
    units: List[_SourceUnit],
) -> List[_SourceUnit]:
    """Admit bodies proved by a newer local generated inventory.

    The opening consolidated schedule can lag a later article-local schedule.
    LLC article XI is the retained production example: the opening schedule
    stops at 1104 while the generated inventory immediately above the article
    body proves 1105 through 1108.  A local inventory is allowed to supplement
    the opening schedule only when it aligns without failures and at least two
    of its body indexes are already-selected anchors.  Quoted or merely
    similar inventories cannot satisfy that conjunction.
    """

    selected = {unit.header_index for unit in units}
    additions: List[_SourceUnit] = []
    next_block_index = max((unit.block_index for unit in units), default=-1) + 1
    for block in _extract_standard_toc_blocks(text, matches):
        aligned, failures, _corrections = _align_standard_toc_blocks(
            text,
            matches,
            [block],
        )
        if failures or len(aligned) != 1:
            continue
        local = aligned[0]
        anchors = [
            header_index
            for header_index in local.selected_header_indexes
            if header_index in selected
        ]
        if len(anchors) < 2:
            continue
        local_indexes = [
            header_index
            for header_index in local.selected_header_indexes
            if header_index >= 0
        ]
        pending = [
            (entry_index, entry, header_index)
            for entry_index, (entry, header_index) in enumerate(
                zip(
                    local.entries,
                    local.selected_header_indexes,
                    strict=True,
                )
            )
            if header_index >= 0 and header_index not in selected
        ]
        if not pending:
            continue
        for entry_index, entry, header_index in pending:
            next_local = next(
                (
                    later
                    for later in local_indexes
                    if matches[later].start() > matches[header_index].start()
                ),
                None,
            )
            next_existing = next(
                (
                    unit.header_index
                    for unit in units
                    if matches[unit.header_index].start()
                    > matches[header_index].start()
                ),
                None,
            )
            boundaries = [
                matches[index].start()
                for index in (next_local, next_existing)
                if index is not None
            ]
            additions.append(
                _SourceUnit(
                    section=entry.section,
                    printed_section=str(
                        matches[header_index].group("section") or ""
                    ).strip(),
                    heading=entry.heading,
                    header_index=header_index,
                    block_index=next_block_index,
                    block_entry_index=entry_index,
                    source_order=0,
                    variant_label=entry.variant_label,
                    lifecycle_note=entry.lifecycle_note,
                    block_lifecycle_note=_lifecycle_note(
                        text[local.toc_start : local.body_start]
                    ),
                    chunk_end=min(boundaries) if boundaries else len(text),
                )
            )
            selected.add(header_index)
        next_block_index += 1

    if not additions:
        return units
    combined = sorted(
        [*units, *additions],
        key=lambda unit: matches[unit.header_index].start(),
    )
    for source_order, unit in enumerate(combined):
        unit.source_order = source_order
        if source_order + 1 < len(combined):
            unit.chunk_end = min(
                unit.chunk_end,
                matches[combined[source_order + 1].header_index].start(),
            )
    return combined


def _augment_title_body_units(
    text: str,
    matches,
    units: List[_SourceUnit],
) -> List[_SourceUnit]:
    """Admit bodies in official TITLE/ARTICLE spans that omit ``Section``."""

    lines = _pdf_lines(text)
    title_lines = [
        line
        for line in lines
        if re.match(
            r"^[ \t]*(?:TITLE|ARTICLE)[ \t]+[0-9A-Za-z.-]+[ \t]*$",
            line.text,
        )
    ]
    if not title_lines:
        return units
    selected = {unit.header_index for unit in units}
    additions: List[_SourceUnit] = []
    next_block_index = max((unit.block_index for unit in units), default=-1) + 1
    for title_index, title_line in enumerate(title_lines):
        span_end = (
            title_lines[title_index + 1].start
            if title_index + 1 < len(title_lines)
            else len(text)
        )
        span_headers = [
            index
            for index, match in enumerate(matches)
            if title_line.start < match.start() < span_end
        ]
        if not span_headers or any(index in selected for index in span_headers):
            continue
        if _inside_source_bounded_interval(title_line.start, units, matches):
            continue
        # A generated local ``Section`` inventory, when present, is strictly
        # stronger and is handled by the normal TOC path.
        if any(
            _TOC_FIRST_RE.match(line.text)
            for line in lines
            if title_line.start < line.start < matches[span_headers[0]].start()
        ):
            continue
        heading_lines = [
            line.text.strip()
            for line in lines
            if title_line.start < line.start < matches[span_headers[0]].start()
            and line.text.strip()
        ]
        if not heading_lines or not any(
            value.upper() == value and re.search(r"[A-Z]", value)
            for value in heading_lines
        ):
            continue
        by_section: Dict[str, List[int]] = {}
        for header_index in span_headers:
            section = str(matches[header_index].group("section") or "").strip()
            key = section.casefold()
            by_section.setdefault(key, []).append(header_index)
        inventory_by_header: Dict[int, List[int]] = {}
        block_headers: List[int] = []
        for candidates in by_section.values():
            chosen = candidates[0]
            if len(candidates) > 1 and re.search(
                r"\bNB[ \t]+Added[ \t]+without[ \t]+title\b",
                _raw_header_after_text(text, matches, candidates[0]),
                re.IGNORECASE,
            ):
                chosen = candidates[-1]
                inventory_by_header[chosen] = candidates[:-1]
            block_headers.append(chosen)
        block_headers.sort(key=lambda index: matches[index].start())
        for entry_index, header_index in enumerate(block_headers):
            match = matches[header_index]
            section = str(match.group("section") or "").strip()
            additions.append(
                _SourceUnit(
                    section=section,
                    printed_section=section,
                    heading=_section_heading(
                        _raw_header_after_text(text, matches, header_index),
                        section,
                    ),
                    header_index=header_index,
                    block_index=next_block_index,
                    block_entry_index=entry_index,
                    source_order=0,
                    chunk_end=(
                        matches[block_headers[entry_index + 1]].start()
                        if entry_index + 1 < len(block_headers)
                        else span_end
                    ),
                    inventory_header_indexes=inventory_by_header.get(
                        header_index, []
                    ),
                )
            )
        selected.update(block_headers)
        next_block_index += 1

    if not additions:
        return units
    combined = sorted(
        [*units, *additions],
        key=lambda unit: matches[unit.header_index].start(),
    )
    for source_order, unit in enumerate(combined):
        unit.source_order = source_order
    # Stop a preceding source body at the intervening structural title rather
    # than allowing it to absorb the newly admitted title.
    for addition in additions:
        addition_start = matches[addition.header_index].start()
        predecessor = next(
            (
                unit
                for unit in reversed(combined)
                if matches[unit.header_index].start() < addition_start
                and unit is not addition
            ),
            None,
        )
        if predecessor is not None and predecessor.chunk_end > addition_start:
            predecessor.chunk_end = addition_start
    return combined


def _redirect_added_without_title_units(
    text: str,
    matches,
    units: List[_SourceUnit],
) -> List[_SourceUnit]:
    """Replace an official title-inventory marker with its substantive body.

    Some generated law PDFs place ``* NB Added without title`` directly in an
    ARTICLE title inventory, then print the real body after the preceding
    titled section.  The note proves why the body lacks its own ``Section``
    inventory row.  Redirect only when the same printed identity and heading
    recur inside an already source-bounded body span; otherwise leave the raw
    marker to fail closed.
    """

    selected = {unit.header_index for unit in units}
    redirected = False
    for unit in units:
        inventory_index = unit.header_index
        inventory_after = _raw_header_after_text(text, matches, inventory_index)
        if re.search(
            r"\bNB[ \t]+Added[ \t]+without[ \t]+title\b",
            inventory_after,
            re.IGNORECASE,
        ) is None:
            continue
        inventory_heading = _WS.sub(
            " ",
            re.split(
                r"\*[ \t]*NB[ \t]+Added[ \t]+without[ \t]+title\b",
                inventory_after,
                maxsplit=1,
                flags=re.IGNORECASE,
            )[0],
        ).strip(" .")
        candidates = [
            index
            for index, match in enumerate(matches)
            if index not in selected
            and match.start() > matches[inventory_index].start()
            and str(match.group("section") or "").strip().casefold()
            == unit.section.casefold()
            and len(_raw_header_after_text(text, matches, index)) >= 80
            and _headings_prove_same_identity(
                inventory_heading,
                _section_heading(
                    _raw_header_after_text(text, matches, index),
                    unit.section,
                ),
            )
        ]
        if len(candidates) != 1:
            continue
        candidate_index = candidates[0]
        candidate_start = matches[candidate_index].start()
        containing = next(
            (
                other
                for other in units
                if other is not unit
                and matches[other.header_index].start() < candidate_start
                < other.chunk_end
            ),
            None,
        )
        if containing is None:
            continue
        inherited_end = containing.chunk_end
        containing.chunk_end = candidate_start
        selected.remove(inventory_index)
        selected.add(candidate_index)
        unit.inventory_header_indexes.append(inventory_index)
        unit.header_index = candidate_index
        unit.printed_section = str(
            matches[candidate_index].group("section") or ""
        ).strip()
        unit.heading = _section_heading(
            _raw_header_after_text(text, matches, candidate_index),
            unit.section,
        )
        unit.block_index = containing.block_index
        unit.block_entry_index = containing.block_entry_index + 1
        unit.chunk_end = inherited_end
        redirected = True

    if not redirected:
        return units
    units.sort(key=lambda unit: matches[unit.header_index].start())
    for source_order, unit in enumerate(units):
        unit.source_order = source_order
    return units


def _augment_explicit_schedule_omission_units(
    text: str,
    matches,
    units: List[_SourceUnit],
) -> List[_SourceUnit]:
    """Admit an ARTICLE body whose official schedule is expressly omitted."""

    selected = {unit.header_index for unit in units}
    additions: List[_SourceUnit] = []
    next_block_index = max((unit.block_index for unit in units), default=-1) + 1
    omitted_notes = list(
        re.finditer(
            r"(?mi)^[ \t]*\*[ \t]*NB[ \t]+Enacted[ \t]+without[ \t]+"
            r"schedule[ \t]+of[ \t]+sections\.?[ \t]*$",
            text,
        )
    )
    for note in omitted_notes:
        preceding = text[max(0, note.start() - 1_000) : note.start()]
        article_headers = list(
            re.finditer(
                r"(?mi)^[ \t]*\*?[ \t]*ARTICLE[ \t]+[0-9A-Za-z.-]+\.?[ \t]*$",
                preceding,
            )
        )
        if not article_headers:
            continue
        following_structure = re.search(
            r"(?mi)^[ \t]*\*?[ \t]*(?:ARTICLE|TITLE|PART)[ \t]+"
            r"[0-9A-Za-z.-]+\.?[ \t]*$",
            text[note.end() :],
        )
        span_end = (
            note.end() + following_structure.start()
            if following_structure is not None
            else len(text)
        )
        span_headers = [
            index
            for index, match in enumerate(matches)
            if note.end() < match.start() < span_end
        ]
        if not span_headers or any(index in selected for index in span_headers):
            continue
        for entry_index, header_index in enumerate(span_headers):
            match = matches[header_index]
            section = str(match.group("section") or "").strip()
            additions.append(
                _SourceUnit(
                    section=section,
                    printed_section=section,
                    heading=_section_heading(
                        _raw_header_after_text(text, matches, header_index),
                        section,
                    ),
                    header_index=header_index,
                    block_index=next_block_index,
                    block_entry_index=entry_index,
                    source_order=0,
                    chunk_end=(
                        matches[span_headers[entry_index + 1]].start()
                        if entry_index + 1 < len(span_headers)
                        else span_end
                    ),
                )
            )
        selected.update(span_headers)
        next_block_index += 1

    if not additions:
        return units
    combined = sorted(
        [*units, *additions],
        key=lambda unit: matches[unit.header_index].start(),
    )
    for source_order, unit in enumerate(combined):
        unit.source_order = source_order
    for addition in additions:
        addition_start = matches[addition.header_index].start()
        predecessor = next(
            (
                unit
                for unit in reversed(combined)
                if unit is not addition
                and matches[unit.header_index].start() < addition_start
            ),
            None,
        )
        if predecessor is not None and predecessor.chunk_end > addition_start:
            predecessor.chunk_end = addition_start
    return combined


def _augment_annotated_body_units(
    text: str,
    matches,
    units: List[_SourceUnit],
) -> List[_SourceUnit]:
    """Admit a starred, note-bound body addition inside a generated span.

    Official amendments sometimes add a section that is absent from the older
    local schedule.  A starred body header plus its attached ``* NB`` status
    note proves both the extra source identity and its lifecycle.  Quoted
    compact/model/amendatory bodies remain inside their parent.
    """

    selected = {unit.header_index for unit in units}
    combined = list(units)
    next_block_index = max((unit.block_index for unit in units), default=-1) + 1
    redirected = False
    for header_index, match in enumerate(matches):
        if header_index in selected or not _match_is_annotated(match):
            continue
        next_boundary = (
            matches[header_index + 1].start()
            if header_index + 1 < len(matches)
            else len(text)
        )
        note, _annotation_start = _lifecycle_annotation_after_header(
            text,
            match,
            next_boundary,
        )
        if not note:
            continue
        candidate_start = match.start()
        containing = next(
            (
                unit
                for unit in combined
                if matches[unit.header_index].start() < candidate_start
                < unit.chunk_end
            ),
            None,
        )
        if containing is None:
            continue
        section = str(match.group("section") or "").strip()
        if section.casefold() == containing.section.casefold():
            continue
        containing_context = text[
            matches[containing.header_index].start() : candidate_start
        ]
        if (
            _EMBEDDED_COMPACT_INTRO_RE.search(containing_context)
            or re.search(
                r"\bmodel\s+local\s+law\b",
                containing_context,
                re.IGNORECASE,
            )
            or re.search(
                r"\binternal\s+revenue\s+code\b",
                containing_context,
                re.IGNORECASE,
            )
            or re.search(
                r"\bamended\s+to\s+read\s+as\s+follows\s*:",
                containing_context,
                re.IGNORECASE,
            )
        ):
            continue
        inherited_end = containing.chunk_end
        containing.chunk_end = candidate_start
        addition = _SourceUnit(
            section=section,
            printed_section=section,
            heading=_section_heading(
                _raw_header_after_text(text, matches, header_index),
                section,
            ),
            header_index=header_index,
            block_index=next_block_index,
            block_entry_index=0,
            source_order=0,
            chunk_end=inherited_end,
        )
        combined.append(addition)
        selected.add(header_index)
        next_block_index += 1
        redirected = True

    if not redirected:
        return units
    combined.sort(key=lambda unit: matches[unit.header_index].start())
    for source_order, unit in enumerate(combined):
        unit.source_order = source_order
    return combined


def _ucc_source_units(
    text: str,
) -> tuple[List, List[_SourceUnit], List[Dict[str, str]]]:
    """Align UCC's official global TOC to its mixed ``Section``/``§`` body."""

    lines = _pdf_lines(text)
    first_occurrences = [
        line.start
        for line in lines
        if (match := _UCC_TOC_FIRST_RE.match(line.text)) is not None
        and str(match.group("section") or "").casefold() == "1--101"
    ]
    if len(first_occurrences) < 2:
        return [], [], [
            {
                "reason": "ucc_global_toc_boundary_missing",
                "detail": f"occurrences={len(first_occurrences)}",
            }
        ]
    body_start = first_occurrences[-1]
    first_toc_start = first_occurrences[0]
    entries: List[_TocEntry] = []
    continuing_entry = False
    for line in lines:
        if line.start < first_toc_start or line.start >= body_start:
            continue
        entry = _UCC_TOC_FIRST_RE.match(line.text)
        if entry is None:
            entry = _UCC_TOC_CONTINUATION_RE.match(line.text)
        if entry is not None and re.fullmatch(
            _UCC_SECTION_ID_PATTERN,
            str(entry.group("section") or ""),
            re.IGNORECASE,
        ):
            entries.append(
                _TocEntry(
                    section=str(entry.group("section") or "").strip(),
                    heading=str(entry.group("heading") or "").strip(),
                    start=line.start,
                    variant_label="",
                )
            )
            continuing_entry = True
            continue
        stripped = line.text.strip()
        if (
            continuing_entry
            and entries
            and len(line.text) - len(line.text.lstrip(" \t")) >= 8
            and stripped
            and not re.match(
                r"^(?:ARTICLE|PART|SUBPART|GENERAL|SHORT TITLE|EFFECTIVE DATE)\b",
                stripped,
                re.IGNORECASE,
            )
        ):
            previous = entries[-1]
            entries[-1] = _TocEntry(
                section=previous.section,
                heading=f"{previous.heading} {stripped}".strip(),
                start=previous.start,
                variant_label=previous.variant_label,
                lifecycle_note=previous.lifecycle_note,
            )
            continue
        continuing_entry = False

    matches = [
        match for match in _UCC_SECTION_HEADER_RE.finditer(text) if match.start() >= body_start
    ]
    selected: List[int] = []
    failures: List[Dict[str, str]] = []
    cursor = 0
    for entry in entries:
        found: Optional[int] = None
        for header_index in range(cursor, len(matches)):
            if (
                str(matches[header_index].group("section") or "").casefold()
                != entry.section.casefold()
            ):
                continue
            after = _raw_header_after_text(text, matches, header_index)
            candidate_heading = " ".join(
                (
                    str(matches[header_index].group("heading") or "").strip(),
                    after,
                )
            ).strip()
            # Local UCC part inventories use the same ``Section N--N.``
            # typography as body headers.  If the entire candidate is only
            # the official TOC heading, it is an inventory row; substantive
            # body candidates necessarily contain text beyond that heading.
            if _heading_key(candidate_heading) == _heading_key(entry.heading):
                continue
            if len(after) < 8 and not _TERMINAL_RE.match(after):
                continue
            found = header_index
            break
        if found is None:
            failures.append(
                {
                    "section_number": entry.section,
                    "reason": "ucc_toc_section_missing_body_identity",
                }
            )
            break
        selected.append(found)
        cursor = found + 1

    if failures:
        return matches, [], failures
    units: List[_SourceUnit] = []
    for source_order, (entry, header_index) in enumerate(
        zip(entries, selected, strict=True)
    ):
        units.append(
            _SourceUnit(
                section=entry.section,
                printed_section=str(
                    matches[header_index].group("section") or ""
                ).strip(),
                heading=entry.heading,
                header_index=header_index,
                block_index=0,
                block_entry_index=source_order,
                source_order=source_order,
                chunk_end=(
                    matches[selected[source_order + 1]].start()
                    if source_order + 1 < len(selected)
                    else len(text)
                ),
            )
        )
    return matches, units, []


def _parse_calendar_date(value: str) -> Optional[date]:
    match = re.search(
        r"\b(January|February|March|April|May|June|July|August|September|"
        r"October|November|December)\s+(\d{1,2}),?\s+(\d{4})\b",
        str(value or ""),
        re.IGNORECASE,
    )
    if match is None:
        return None
    try:
        normalized = re.sub(r"\s+", " ", match.group(0)).strip()
        for form in ("%B %d, %Y", "%B %d %Y"):
            try:
                return datetime.strptime(normalized, form).date()
            except ValueError:
                pass
        return None
    except ValueError:
        return None


def _explicit_status_date(value: str) -> Optional[date]:
    parsed = _parse_calendar_date(value)
    if parsed is not None:
        return parsed
    numeric = re.search(
        r"\b(0?[1-9]|1[0-2])/(0?[1-9]|[12][0-9]|3[01])/(\d{4})\b",
        str(value or ""),
    )
    if numeric is not None:
        try:
            return date(
                int(numeric.group(3)),
                int(numeric.group(1)),
                int(numeric.group(2)),
            )
        except ValueError:
            return None
    return None


def _lifecycle_note(chunk: str) -> str:
    annotations = list(
        re.finditer(r"(?mi)^[ \t]*\*[ \t]*NB[ \t]+", str(chunk or ""))
    )
    if not annotations:
        return ""
    notes: List[str] = []
    raw = str(chunk or "")
    for index, annotation in enumerate(annotations):
        boundary = (
            annotations[index + 1].start()
            if index + 1 < len(annotations)
            else len(raw)
        )
        suffix = raw[annotation.end() : boundary]
        suffix = re.split(
            r"(?mi)^\s*\*?[ \t]*(?:ARTICLE|TITLE|PART|Section[ \t]+[0-9])",
            suffix,
            maxsplit=1,
        )[0]
        normalized = _WS.sub(" ", suffix).strip()
        if normalized:
            notes.append(normalized)
    return " | ".join(notes)


def _lifecycle_annotation_after_header(
    text: str,
    match,
    boundary: int,
) -> tuple[str, Optional[int]]:
    chunk = text[match.end() : max(match.end(), boundary)]
    annotations = list(re.finditer(r"(?mi)^[ \t]*\*[ \t]*NB[ \t]+", chunk))
    for annotation in re.finditer(
        r"(?mi)^[ \t]*\*{2}[ \t]*NB[ \t]+",
        chunk,
    ):
        trailing_note = _WS.sub(" ", chunk[annotation.end() :]).strip()
        if (
            re.fullmatch(
                r"Repealed[ \t]+"
                r"(?:January|February|March|April|May|June|July|August|"
                r"September|October|November|December)[ \t]+"
                r"[0-9]{1,2},?[ \t]+[0-9]{4}\.?",
                trailing_note,
                re.IGNORECASE,
            )
            is not None
            and _explicit_status_date(trailing_note) is not None
        ):
            annotations.append(annotation)
    annotations.sort(key=lambda annotation: annotation.start())
    if not annotations:
        return "", None
    notes: List[str] = []
    for index, annotation in enumerate(annotations):
        note_boundary = (
            annotations[index + 1].start()
            if index + 1 < len(annotations)
            else len(chunk)
        )
        note = chunk[annotation.end() : note_boundary]
        note = re.split(
            r"(?mi)^\s*\*?[ \t]*(?:ARTICLE|TITLE|PART|Section[ \t]+[0-9])",
            note,
            maxsplit=1,
        )[0]
        normalized = _WS.sub(" ", note).strip()
        if normalized:
            notes.append(normalized)
    return " | ".join(notes), match.end() + annotations[0].start()


def _lifecycle_note_before_header(text: str, matches, header_index: int) -> str:
    """Return the generated ``* NB`` annotation attached to this header.

    Retained PDFs normally place the controlling annotation after the body;
    this helper remains useful only for identifying an annotation boundary
    before a following header.
    """

    note, _start = _lifecycle_annotation_before_header(text, matches, header_index)
    return note


def _lifecycle_annotation_before_header(
    text: str,
    matches,
    header_index: int,
) -> tuple[str, Optional[int]]:
    start = matches[header_index - 1].end() if header_index else 0
    prefix = text[start : matches[header_index].start()]
    annotations = list(re.finditer(r"(?mi)^[ \t]*\*[ \t]*NB[ \t]+", prefix))
    if not annotations:
        return "", None
    annotation = annotations[-1]
    note_start = annotation.end()
    return (
        _WS.sub(" ", prefix[note_start:]).strip(),
        start + annotation.start(),
    )


def _has_source_proved_insurance_special_note(chunk: str) -> bool:
    """Recognize the publisher's exact non-juxtaposition editorial note."""

    annotations = list(
        re.finditer(
            r"(?mi)^[ \t]*\*+[ \t]+SPECIAL[ \t]+NOTE\.\s*--",
            str(chunk or ""),
        )
    )
    if len(annotations) != 1:
        return False
    note_and_remainder = _WS.sub(
        " ", str(chunk)[annotations[0].end() :]
    ).strip()
    return note_and_remainder.startswith(_INSURANCE_UNJUXTAPOSED_SPECIAL_NOTE)


def _annotated_lifecycle_status(
    note: str,
    *,
    release_date: date,
    applicable_historical_text: bool = False,
) -> tuple[str, str]:
    """Return ``(status, disposition)`` for an official starred version."""

    normalized = _WS.sub(" ", str(note or "")).strip()
    lowered = normalized.casefold()
    effective_date = _explicit_status_date(normalized)
    if applicable_historical_text and (
        not normalized
        or lowered.startswith("the text of article 5 of the former state housing law")
    ):
        return "current", "applicable_historical_text"
    if not normalized:
        return (
            ("current", "applicable_historical_text")
            if applicable_historical_text
            else ("ambiguous", "missing_lifecycle_note")
        )
    if lowered.startswith("there are "):
        return "current", "source_proved_repeated_identity"
    if lowered.startswith("this section survives"):
        return "current", "survives_repeal"
    if lowered.startswith("effective and repealed"):
        if effective_date is None:
            return "ambiguous", "event_conditioned_repeal"
        return (
            ("current", "future_repeal")
            if release_date < effective_date
            else ("terminal", "repealed")
        )
    if lowered.startswith("effectiveness of amendments") and "expired" in lowered:
        return "terminal", "superseded"
    if lowered.startswith("effective until"):
        if effective_date is None:
            return "ambiguous", "event_conditioned_effective_until"
        return (
            ("current", "effective_until")
            if release_date < effective_date
            else ("terminal", "superseded")
        )
    if lowered.startswith("effective"):
        if effective_date is None:
            return "ambiguous", "event_conditioned_effective"
        return (
            ("current", "effective")
            if release_date >= effective_date
            else ("terminal", "future_effective")
        )
    if lowered.startswith("repealed after"):
        return "ambiguous", "event_conditioned_repeal"
    if lowered.startswith("repealed"):
        if effective_date is not None and release_date < effective_date:
            return "current", "future_repeal"
        return "terminal", "repealed"
    if lowered.startswith("rpld per"):
        return "terminal", "repealed"
    if lowered.startswith("expired") or lowered.startswith("expires"):
        if effective_date is not None and release_date < effective_date:
            return "current", "future_expiration"
        return "terminal", "expired"
    if lowered.startswith("(expired"):
        if effective_date is not None and release_date < effective_date:
            return "current", "future_expiration"
        return "terminal", "expired"
    if lowered.startswith("section effective") or lowered.startswith("see "):
        return "ambiguous", "event_conditioned_effective"
    if lowered.startswith("amendments effective"):
        return "ambiguous", "event_conditioned_effective"
    if lowered.startswith("(effective until"):
        return "ambiguous", "event_conditioned_effective_until"
    if lowered.startswith("(effective pending"):
        return "ambiguous", "event_conditioned_effective"
    if lowered.startswith(
        ("not effective", "not operative", "denied congressional consent")
    ):
        return "terminal", "never_effective"
    if lowered.startswith("revived"):
        if effective_date is None:
            return "ambiguous", "event_conditioned_revival"
        return (
            ("current", "revived")
            if release_date >= effective_date
            else ("terminal", "future_revival")
        )
    if lowered.startswith(("null & void", "null and void")):
        if " if " in lowered:
            return "ambiguous", "event_conditioned_nullification"
        return "terminal", "null_and_void"
    if lowered.startswith("section null and void"):
        if " if " in lowered:
            return "ambiguous", "event_conditioned_nullification"
        return "terminal", "null_and_void"
    if lowered.startswith(
        (
            "ceased to exist",
            "dissolved",
            "terminated",
            "scholarship terminated",
            "(abolished",
            "(authority abolished",
            "(disbanded",
            "(discontinued-board",
        )
    ):
        return "terminal", "terminated"
    if lowered.startswith(("authority ceased", "authority dissolved")):
        return "terminal", "terminated"
    if lowered.startswith("authority terminated"):
        if effective_date is not None and release_date < effective_date:
            return "current", "future_termination"
        return "terminal", "terminated"
    if lowered.startswith("nonexistent"):
        if effective_date is not None and release_date < effective_date:
            return "current", "future_termination"
        return "terminal", "terminated"
    if lowered.startswith("authority of office") and (
        "terminated" in lowered or "expired" in lowered
    ):
        return "terminal", "terminated"
    if lowered.startswith("agency expired"):
        return "terminal", "expired"
    if lowered.startswith("agency expires"):
        if effective_date is None:
            return "ambiguous", "event_conditioned_expiration"
        return (
            ("current", "future_expiration")
            if release_date < effective_date
            else ("terminal", "expired")
        )
    if lowered.startswith("agency shall continue in existence until"):
        if effective_date is None:
            return "ambiguous", "event_conditioned_expiration"
        return (
            ("current", "effective_until")
            if release_date < effective_date
            else ("terminal", "expired")
        )
    if lowered.startswith("the corporation shall continue for a term ending"):
        return "ambiguous", "event_conditioned_expiration"
    if lowered.startswith("city ") and "ceased to exist" in lowered:
        return "terminal", "terminated"
    if lowered.startswith("effectiveness") and "expired" in lowered:
        return "terminal", "expired"
    if lowered.startswith(
        (
            "enacted without section heading",
            "added without title",
            "numerically this section",
            "section set out as",
            "section number supplied",
            "section inadvertently added",
        )
    ):
        return "current", "official_identity_annotation"
    if (
        lowered.startswith("added ch.")
        and "section number supplied by the legislative bill drafting commission"
        in lowered
    ):
        return "current", "official_identity_annotation"
    if lowered.startswith("section operative only"):
        if effective_date is None:
            return "ambiguous", "event_conditioned_expiration"
        return (
            ("current", "effective_until")
            if release_date <= effective_date
            else ("terminal", "expired")
        )
    if lowered.startswith("commission existence"):
        return "current", "commission_exists"
    if lowered.startswith("separately amended"):
        return "current", "source_proved_separate_amendment"
    if lowered.startswith("this section partially repealed"):
        if "retained" in lowered:
            return "current", "partially_repealed_retained_text"
        return "ambiguous", "partial_repeal"
    return "ambiguous", "unrecognized_lifecycle_note"


def _pure_repeated_identity_count(note: str, section: str) -> Optional[int]:
    normalized = _WS.sub(" ", str(note or "")).strip()
    match = re.fullmatch(
        rf"There[ \t]+are[ \t]+(?P<count>[0-9]+)[ \t]+"
        rf"(?:§[ \t]*)?{re.escape(str(section or '').strip())}"
        r"(?:'s|s)?\.?",
        normalized,
        re.IGNORECASE,
    )
    return int(match.group("count")) if match is not None else None


def _match_is_annotated(match) -> bool:
    try:
        return bool(
            match.group("annotated")
            or "*" in str(match.groupdict().get("header_suffix") or "")
        )
    except (IndexError, KeyError):
        return False


def _source_identity_suffix(unit: _SourceUnit, duplicate_count: int) -> str:
    if unit.variant_label:
        return f":variant-{unit.variant_label.lstrip('*')}"
    if duplicate_count > 1:
        return f":source-{unit.source_order + 1}"
    return ""


def _append_source_statute(
    report: NewYorkLawPdfParseResult,
    *,
    code: str,
    name: str,
    code_name: str,
    bundle_url: str,
    unit: _SourceUnit,
    full_text: str,
    section_name: str,
    duplicate_count: int,
    lifecycle_disposition: str,
) -> None:
    identity_suffix = _source_identity_suffix(unit, duplicate_count)
    display_suffix = (
        f" [source {unit.source_order + 1}{unit.variant_label}]"
        if identity_suffix
        else ""
    )
    report.statutes.append(
        NormalizedStatute(
            state_code="NY",
            state_name="New York",
            statute_id=(
                f"{code_name} § {code} {unit.section}{display_suffix}"
            ),
            code_name=code_name,
            title_number=code,
            title_name=name,
            section_number=unit.section,
            section_name=section_name,
            full_text=full_text,
            source_url=public_section_url(code, unit.section),
            official_cite=f"N.Y. {code} Law § {unit.section}",
            metadata=StatuteMetadata(),
            structured_data={
                "source_kind": "official_new_york_senate_law_pdf",
                "source_authority_class": "official",
                "discovery_method": "nysenate_full_law_pdf",
                "law_code": code,
                "source_bundle_url": bundle_url,
                "source_record_id": f"{code}:{unit.section}{identity_suffix}",
                "source_order": unit.source_order,
                "toc_variant": unit.variant_label,
                "printed_section_number": unit.printed_section,
                "lifecycle_disposition": lifecycle_disposition,
                "release_date": report.release_date,
                "skip_hydrate": True,
            },
        )
    )


def _parse_source_bound_units(
    report: NewYorkLawPdfParseResult,
    *,
    text: str,
    matches,
    units: List[_SourceUnit],
    code: str,
    name: str,
    code_name: str,
    bundle_url: str,
    toc_section_count: int,
    toc_failures: List[Dict[str, str]],
    toc_corrections: List[Dict[str, str]],
    first_toc_start: int,
    extra_source_residual_count: int = 0,
    source_sections_without_raw_markers: int = 0,
    ucc: bool = False,
) -> NewYorkLawPdfParseResult:
    """Project source-proved TOC identities onto body variants.

    Every raw body marker is assigned exactly one role: selected source
    identity, lifecycle alternate, source-bounded nested text, or a typed
    fail-closed residual.  Editorial notes and alternate versions therefore
    cannot silently inflate or erase the statutory frontier.
    """

    report.toc_section_count = int(toc_section_count)
    report.source_sections_without_raw_markers = int(
        source_sections_without_raw_markers
    )
    if report.source_sections_without_raw_markers < 0:
        raise ValueError("source sections without raw markers cannot be negative")
    report.toc_body_corrections.extend(toc_corrections)
    for failure in toc_failures:
        heading = _WS.sub(" ", str(failure.get("toc_heading") or "")).strip()
        terminal_heading = re.match(
            r"^(?:intentionally[ \t]+)?"
            r"(repealed|reserved|expired|omitted|transferred|renumbered)\b",
            heading,
            re.IGNORECASE,
        )
        if terminal_heading is None:
            report.unclassified_sections.append(failure)
            continue
        section = str(failure.get("section_number") or "").strip()
        report.terminal_sections.append(
            {
                "section_number": section,
                "toc_variant": str(failure.get("toc_variant") or ""),
                "disposition": terminal_heading.group(1).lower(),
                "note": heading,
                "source_record_id": f"{code}:{section}:toc-terminal",
                "source_url": public_section_url(code, section),
            }
        )
    selected_indexes = {unit.header_index for unit in units}
    assigned_indexes = set(selected_indexes)
    for unit in units:
        for inventory_index in unit.inventory_header_indexes:
            assigned_indexes.add(inventory_index)
            report.embedded_section_markers.append(
                {
                    "section_number": str(
                        matches[inventory_index].group("section") or ""
                    ).strip(),
                    "parent_section_number": unit.section,
                    "reason": "body_local_section_inventory_header",
                }
            )
    # Official TOC order proves nesting between adjacent top-level entries.
    for unit_index, unit in enumerate(units):
        start = matches[unit.header_index].start()
        end = max(start, unit.chunk_end)
        next_same_block = bool(
            unit_index + 1 < len(units)
            and units[unit_index + 1].block_index == unit.block_index
        )
        prefix = text[matches[unit.header_index].end() : end]
        nested_context = f"{unit.heading} {prefix}"
        explicit_nested = bool(
            _EMBEDDED_COMPACT_INTRO_RE.search(nested_context)
            or re.search(
                r"\bmodel\s+local\s+law\b", nested_context, re.IGNORECASE
            )
            or re.search(
                r"\binternal\s+revenue\s+code\b",
                nested_context,
                re.IGNORECASE,
            )
            or re.search(
                r"\bamended\s+to\s+read\s+as\s+follows\s*:",
                prefix,
                re.IGNORECASE,
            )
        )
        for header_index, match in enumerate(matches):
            if header_index in assigned_indexes:
                continue
            if not (start < match.start() < end):
                continue
            observed = str(match.group("section") or "").strip()
            if observed.casefold() == unit.section.casefold():
                unit.variant_header_indexes.append(header_index)
                assigned_indexes.add(header_index)
                continue
            if ucc or next_same_block or explicit_nested:
                reason = "source_toc_bounded_nested_section_header"
                if _EMBEDDED_COMPACT_INTRO_RE.search(nested_context):
                    reason = "embedded_compact_section_header"
                elif re.search(
                    r"\bmodel\s+local\s+law\b",
                    nested_context,
                    re.IGNORECASE,
                ):
                    reason = "embedded_model_law_section_header"
                elif re.search(
                    r"\binternal\s+revenue\s+code\b",
                    nested_context,
                    re.IGNORECASE,
                ):
                    reason = "embedded_federal_code_section_header"
                elif re.search(
                    r"\bamended\s+to\s+read\s+as\s+follows\s*:",
                    prefix,
                    re.IGNORECASE,
                ):
                    reason = "embedded_amendatory_section_header"
                report.embedded_section_markers.append(
                    {
                        "section_number": observed,
                        "parent_section_number": unit.section,
                        "reason": reason,
                    }
                )
                assigned_indexes.add(header_index)

    # A printed § marker before the first authoritative generated inventory is
    # an enactment/editorial wrapper, not a leaf in that inventory (COR).
    if not ucc:
        for header_index, match in enumerate(matches):
            if header_index in assigned_indexes:
                continue
            if match.start() < first_toc_start:
                report.embedded_section_markers.append(
                    {
                        "section_number": str(
                            match.group("section") or ""
                        ).strip(),
                        "parent_section_number": "",
                        "reason": "pre_toc_enactment_wrapper_section_header",
                    }
                )
                assigned_indexes.add(header_index)

    duplicate_counts = Counter(unit.section.casefold() for unit in units)
    applicable_historical_text = bool(
        re.search(r"\bcontinues\s+to\s+be\s+applicable\b", text, re.IGNORECASE)
        and re.search(r"\bcurrent\s+Public\s+Housing\s+Law\b", text, re.IGNORECASE)
    )

    source_group_repeated_notes: Dict[str, str] = {}
    group_candidate_counts: Dict[str, int] = Counter()
    group_note_rows: Dict[str, List[tuple[int, str]]] = {}
    for source_unit in units:
        section_key = source_unit.section.casefold()
        source_candidate_indexes = sorted(
            [source_unit.header_index, *source_unit.variant_header_indexes],
            key=lambda index: matches[index].start(),
        )
        group_candidate_counts[section_key] += len(source_candidate_indexes)
        for candidate_offset, header_index in enumerate(source_candidate_indexes):
            boundary = (
                matches[source_candidate_indexes[candidate_offset + 1]].start()
                if candidate_offset + 1 < len(source_candidate_indexes)
                else source_unit.chunk_end
            )
            candidate_note, _annotation_start = (
                _lifecycle_annotation_after_header(
                    text,
                    matches[header_index],
                    boundary,
                )
            )
            repeated_count = _pure_repeated_identity_count(
                candidate_note,
                source_unit.section,
            )
            if repeated_count is not None:
                group_note_rows.setdefault(section_key, []).append(
                    (repeated_count, candidate_note)
                )
    for section_key, note_rows in group_note_rows.items():
        announced_counts = {count for count, _note in note_rows}
        if (
            len(announced_counts) == 1
            and next(iter(announced_counts))
            >= group_candidate_counts[section_key]
        ):
            source_group_repeated_notes[section_key] = note_rows[0][1]

    for unit in units:
        candidate_indexes = sorted(
            [unit.header_index, *unit.variant_header_indexes],
            key=lambda index: matches[index].start(),
        )
        candidates: List[Dict[str, object]] = []
        for candidate_offset, header_index in enumerate(candidate_indexes):
            match = matches[header_index]
            next_boundary = (
                matches[candidate_indexes[candidate_offset + 1]].start()
                if candidate_offset + 1 < len(candidate_indexes)
                else unit.chunk_end
            )
            note, annotation_start = _lifecycle_annotation_after_header(
                text,
                match,
                next_boundary,
            )
            note = (
                note
                or unit.lifecycle_note
                or (unit.block_lifecycle_note if candidate_offset == 0 else "")
                or source_group_repeated_notes.get(unit.section.casefold(), "")
            )
            content_boundary = (
                annotation_start
                if annotation_start is not None
                else next_boundary
            )
            raw_chunk = text[match.start() : max(match.start(), content_boundary)]
            normalized_chunk = _WS.sub(" ", raw_chunk).strip()
            normalized_after = _WS.sub(
                " ",
                text[match.end() : max(match.end(), content_boundary)],
            ).strip()
            selector: Optional[Mapping[str, Any]] = None
            terminal = _TERMINAL_RE.match(normalized_after)
            if terminal is not None:
                status = "terminal"
                disposition = terminal.group(1).lower()
            elif _match_is_annotated(match):
                if (
                    code == "ISC"
                    and not note
                    and _has_source_proved_insurance_special_note(raw_chunk)
                ):
                    status, disposition = (
                        "current",
                        "source_proved_unjuxtaposed_insurance_special_note",
                    )
                else:
                    status, disposition = _annotated_lifecycle_status(
                        note,
                        release_date=_EXPLICIT_RELEASE_DATE,
                        applicable_historical_text=applicable_historical_text,
                    )
                selector = report.conditional_event_selectors.get(
                    AGM28_LIFECYCLE_SELECTOR_KEY
                )
                if (
                    code == "AGM"
                    and unit.section == "28"
                    and status == "ambiguous"
                    and disposition == "event_conditioned_repeal"
                    and isinstance(selector, Mapping)
                    and selector.get("status") == "occurred"
                ):
                    status, disposition = "terminal", "repealed"
                if (
                    status == "ambiguous"
                    and disposition == "missing_lifecycle_note"
                    and unit.variant_label
                ):
                    status, disposition = (
                        "current",
                        "source_toc_alternate_identity",
                    )
            else:
                status, disposition = "current", "unannotated_current"
            candidates.append(
                {
                    "header_index": header_index,
                    "status": status,
                    "disposition": disposition,
                    "note": note,
                    "full_text": normalized_chunk,
                    "normalized_after": normalized_after,
                    "lifecycle_selector": (
                        dict(selector)
                        if (
                            code == "AGM"
                            and unit.section == "28"
                            and isinstance(selector, Mapping)
                        )
                        else None
                    ),
                }
            )

        # The generator can print a pure repeated-identity annotation after
        # only some of the same-number bodies (HAY 344-h/344-n).  Propagate it
        # to otherwise note-less candidates only when the exact section and a
        # single announced count are source-proved, and that count covers the
        # observed body group.  Event/lifecycle clauses never propagate.
        repeated_note_matches: List[tuple[int, str]] = []
        for candidate in candidates:
            candidate_note = _WS.sub(
                " ", str(candidate.get("note") or "")
            ).strip()
            repeated_count = _pure_repeated_identity_count(
                candidate_note,
                unit.section,
            )
            if repeated_count is not None:
                repeated_note_matches.append(
                    (repeated_count, candidate_note)
                )
        repeated_counts = {count for count, _note in repeated_note_matches}
        if (
            len(candidates) > 1
            and len(repeated_counts) == 1
            and next(iter(repeated_counts)) >= len(candidates)
        ):
            group_note = repeated_note_matches[0][1]
            for candidate in candidates:
                if (
                    candidate["status"] == "ambiguous"
                    and candidate["disposition"] == "missing_lifecycle_note"
                ):
                    candidate["status"] = "current"
                    candidate["disposition"] = (
                        "source_proved_repeated_identity"
                    )
                    candidate["note"] = group_note

        ambiguous = [row for row in candidates if row["status"] == "ambiguous"]
        current = [row for row in candidates if row["status"] == "current"]
        terminal = [row for row in candidates if row["status"] == "terminal"]
        source_proved_repeated = bool(
            len(current) > 1
            and not ambiguous
            and any(
                row["disposition"] == "source_proved_repeated_identity"
                or row["disposition"] == "source_proved_separate_amendment"
                or re.search(
                    r"\bThere[ \t]+are[ \t]+[0-9]+[ \t]+§",
                    str(row["note"]),
                    re.IGNORECASE,
                )
                for row in current
            )
        )
        if source_proved_repeated:
            group_disposition = (
                "source_proved_separate_amendment"
                if any(
                    row["disposition"] == "source_proved_separate_amendment"
                    for row in current
                )
                else "source_proved_repeated_identity"
            )
            report.toc_section_count += len(current) - 1
            for repeated_index, chosen in enumerate(current, start=1):
                repeated_unit = _SourceUnit(
                    section=unit.section,
                    printed_section=unit.printed_section,
                    heading=unit.heading,
                    header_index=int(chosen["header_index"]),
                    block_index=unit.block_index,
                    block_entry_index=unit.block_entry_index,
                    source_order=unit.source_order * 100 + repeated_index,
                    variant_label=(
                        unit.variant_label
                        if repeated_index == 1 and unit.variant_label
                        else f"*{repeated_index}"
                    ),
                )
                _append_source_statute(
                    report,
                    code=code,
                    name=name,
                    code_name=code_name,
                    bundle_url=bundle_url,
                    unit=repeated_unit,
                    full_text=str(chosen["full_text"]),
                    section_name=(
                        (
                            unit.heading.strip(" .")
                            if repeated_index == 1
                            else ""
                        )
                        or _section_heading(
                            str(chosen["normalized_after"]),
                            unit.section,
                        )
                    ),
                    duplicate_count=len(current),
                    lifecycle_disposition=group_disposition,
                )
            continue
        if ambiguous or len(current) > 1:
            for alternate in candidates[1:]:
                report.lifecycle_alternate_sections.append(
                    {
                        "section_number": unit.section,
                        "toc_variant": unit.variant_label,
                        "disposition": str(alternate["disposition"]),
                        "note": str(alternate["note"]),
                    }
                )
            report.unclassified_sections.append(
                {
                    "section_number": unit.section,
                    "toc_variant": unit.variant_label,
                    "reason": (
                        "ambiguous_lifecycle_status"
                        if ambiguous
                        else "multiple_current_lifecycle_variants"
                    ),
                    "detail": " | ".join(
                        f"{row['disposition']}: {row['note']}".strip()
                        for row in (ambiguous or current)
                    )[:600],
                }
            )
            continue

        if len(current) == 1:
            chosen = current[0]
            chosen_match = matches[int(chosen["header_index"])]
            inline_word_body = ""
            if chosen_match.re in (
                _WORD_SECTION_HEADER_RE,
                _RULE_SECTION_HEADER_RE,
                _BARE_BODY_SECTION_HEADER_RE,
            ):
                inline_heading = str(chosen_match.group("heading") or "").strip()
                expected_heading = unit.heading.strip(" .")
                if _heading_key(inline_heading).startswith(
                    _heading_key(expected_heading)
                ):
                    inline_word_body = inline_heading[len(expected_heading) :]
            if (
                len(str(chosen["full_text"])) < 20
                or (
                    len(str(chosen["normalized_after"])) < 8
                    and len(_WS.sub(" ", inline_word_body).strip(" .")) < 8
                )
            ):
                report.unclassified_sections.append(
                    {
                        "section_number": unit.section,
                        "toc_variant": unit.variant_label,
                        "reason": "missing_or_short_operative_body",
                    }
                )
                continue
            for alternate in terminal:
                report.lifecycle_alternate_sections.append(
                    {
                        "section_number": unit.section,
                        "toc_variant": unit.variant_label,
                        "disposition": str(alternate["disposition"]),
                        "note": str(alternate["note"]),
                    }
                )
            _append_source_statute(
                report,
                code=code,
                name=name,
                code_name=code_name,
                bundle_url=bundle_url,
                unit=unit,
                full_text=str(chosen["full_text"]),
                section_name=(
                    unit.heading.strip(" .")
                    or _section_heading(
                        str(chosen["normalized_after"]),
                        unit.section,
                    )
                ),
                duplicate_count=duplicate_counts[unit.section.casefold()],
                lifecycle_disposition=str(chosen["disposition"]),
            )
            continue

        if terminal:
            chosen = terminal[-1]
            terminal_row: Dict[str, Any] = {
                "section_number": unit.section,
                "toc_variant": unit.variant_label,
                "disposition": str(chosen["disposition"]),
                "note": str(chosen["note"]),
                "source_record_id": (
                    f"{code}:{unit.section}"
                    f"{_source_identity_suffix(unit, duplicate_counts[unit.section.casefold()])}"
                ),
                "source_url": public_section_url(code, unit.section),
            }
            lifecycle_selector = chosen.get("lifecycle_selector")
            if isinstance(lifecycle_selector, Mapping):
                terminal_row["lifecycle_selector"] = dict(lifecycle_selector)
            report.terminal_sections.append(terminal_row)
            for alternate in terminal[:-1]:
                report.lifecycle_alternate_sections.append(
                    {
                        "section_number": unit.section,
                        "toc_variant": unit.variant_label,
                        "disposition": str(alternate["disposition"]),
                        "note": str(alternate["note"]),
                    }
                )
            continue

        report.unclassified_sections.append(
            {
                "section_number": unit.section,
                "toc_variant": unit.variant_label,
                "reason": "source_identity_without_body_variant",
            }
        )

    unreconciled_indexes = [
        index for index in range(len(matches)) if index not in assigned_indexes
    ]
    for header_index in unreconciled_indexes:
        match = matches[header_index]
        report.unclassified_sections.append(
            {
                "section_number": str(match.group("section") or "").strip(),
                "reason": "unreconciled_raw_section_header",
                "detail": _raw_header_after_text(
                    text, matches, header_index
                )[:240],
            }
        )

    report.source_section_count = (
        report.toc_section_count
        + len(unreconciled_indexes)
        + int(extra_source_residual_count)
    )
    report.closed = bool(
        report.page_count > 0
        and report.source_section_count > 0
        and (
            report.raw_section_marker_count
            + report.source_sections_without_raw_markers
            == report.source_section_count
            + len(report.embedded_section_markers)
            + len(report.lifecycle_alternate_sections)
        )
        and report.source_section_count
        == len(report.statutes)
        + len(report.terminal_sections)
        + len(report.unclassified_sections)
        and not report.unclassified_sections
    )
    return report


def parse_new_york_law_pdf(
    payload: bytes,
    *,
    law_code: str,
    law_name: str,
    code_name: str = "New York Consolidated Laws",
    source_bundle_url: str = "",
    agm28_lifecycle_report_payload: Optional[bytes] = None,
    agm28_lifecycle_report_source_url: str = "",
    supplemental_proof_registry: Optional[
        NewYorkSupplementalProofRegistry
    ] = None,
) -> NewYorkLawPdfParseResult:
    """Parse every source-bound section and type terminal leaf nodes."""

    code = str(law_code or "").strip().upper()
    name = _WS.sub(" ", str(law_name or "")).strip() or code
    report = NewYorkLawPdfParseResult(law_code=code, law_name=name)
    try:
        text, page_count = extract_new_york_law_pdf_text(payload)
    except Exception as exc:
        report.unclassified_sections.append(
            {"reason": "pdf_text_extraction_failed", "detail": str(exc)[:300]}
        )
        return reconcile_new_york_supplemental_proofs(
            report,
            supplemental_proof_registry,
        )
    report.page_count = page_count
    bundle_url = source_bundle_url or full_law_pdf_url(code)
    registry = supplemental_proof_registry
    if agm28_lifecycle_report_payload is not None:
        if code != "AGM":
            raise ValueError(
                "AGM 28 lifecycle report evidence may be supplied only to AGM"
            )
        bound_agm = NewYorkSupplementalProofInput.bind(
            selector_key=AGM28_LIFECYCLE_SELECTOR_KEY,
            proof_kind="official_event_report",
            official_url=agm28_lifecycle_report_source_url,
            media_type="application/pdf",
            payload=bytes(agm28_lifecycle_report_payload),
        )
        registry = (registry or NewYorkSupplementalProofRegistry()).with_inputs(
            [bound_agm]
        )
    if code == "AGM" and registry is not None:
        agm28_outcome = registry.resolve_agm28(legal_as_of=_EXPLICIT_RELEASE_DATE)
        if agm28_outcome is not None:
            report.conditional_event_selectors[AGM28_LIFECYCLE_SELECTOR_KEY] = (
                agm28_outcome
            )

    if code == "UCC":
        ucc_matches, ucc_units, ucc_failures = _ucc_source_units(text)
        report.raw_section_marker_count = len(ucc_matches)
        parsed = _parse_source_bound_units(
            report,
            text=text,
            matches=ucc_matches,
            units=ucc_units,
            code=code,
            name=name,
            code_name=code_name,
            bundle_url=bundle_url,
            toc_section_count=len(ucc_units) + len(ucc_failures),
            toc_failures=ucc_failures,
            toc_corrections=[],
            first_toc_start=0,
            source_sections_without_raw_markers=len(ucc_failures),
            ucc=True,
        )
        return reconcile_new_york_supplemental_proofs(parsed, registry)

    matches = _source_header_matches(text)
    source_markers = list(_SECTION_MARKER_RE.finditer(text))
    supplemental_header_count = sum(
        match.re in (
            _BARE_ANNOTATED_SECTION_HEADER_RE,
            _BARE_BODY_SECTION_HEADER_RE,
            _WORD_SECTION_HEADER_RE,
            _RULE_SECTION_HEADER_RE,
        )
        for match in matches
    )
    report.raw_section_marker_count = (
        len(source_markers) + supplemental_header_count
    )
    parsed_marker_starts = {match.start() for match in matches}
    unparsed_marker_residuals: List[Dict[str, str]] = []
    for marker in source_markers:
        if marker.start() in parsed_marker_starts:
            continue
        line_end = text.find("\n", marker.start())
        if line_end < 0:
            line_end = min(len(text), marker.start() + 240)
        detail = _WS.sub(" ", text[marker.start() : line_end]).strip()[:240]
        if detail == "§":
            report.embedded_section_markers.append(
                {
                    "section_number": "",
                    "parent_section_number": "",
                    "reason": "pdf_boundary_section_glyph",
                }
            )
            continue
        citation = re.match(
            rf"^[ \t]*(?:\*[ \t]*)?§[ \t]*(?P<section>{_SECTION_ID_PATTERN})"
            r"(?=[,;(]|[ \t]+(?:et\.?[ \t]+seq\.?|of\b|or\b))",
            detail,
        )
        if citation is not None:
            report.embedded_section_markers.append(
                {
                    "section_number": str(citation.group("section") or "").strip(),
                    "parent_section_number": "",
                    "reason": "line_leading_section_citation",
                }
            )
            continue
        malformed_inventory = re.match(
            rf"^[ \t]*\*[ \t]*§[ \t]+(?P<section>{_SECTION_ID_PATTERN})"
            r"\*\.[ \t]*\S",
            detail,
        )
        if malformed_inventory is not None:
            report.embedded_section_markers.append(
                {
                    "section_number": str(
                        malformed_inventory.group("section") or ""
                    ).strip(),
                    "parent_section_number": "",
                    "reason": "annotated_section_inventory_header",
                }
            )
            continue
        unparsed_marker_residuals.append(
            {
                "reason": "unparsed_section_header",
                "detail": detail,
            }
        )

    toc_blocks = _extract_standard_toc_blocks(text, matches)
    accepted_blocks, toc_failures, toc_corrections = _align_standard_toc_blocks(
        text,
        matches,
        toc_blocks,
    )
    preliminary_units = _standard_source_units(text, matches, accepted_blocks)
    word_supplements = _source_bound_word_header_supplements(
        text,
        matches,
        preliminary_units,
    )
    if word_supplements:
        matches = sorted(
            [*matches, *word_supplements],
            key=lambda match: match.start(),
        )
        supplemental_header_count = sum(
            match.re in (
                _BARE_ANNOTATED_SECTION_HEADER_RE,
                _BARE_BODY_SECTION_HEADER_RE,
                _WORD_SECTION_HEADER_RE,
                _RULE_SECTION_HEADER_RE,
            )
            for match in matches
        )
        report.raw_section_marker_count = (
            len(source_markers) + supplemental_header_count
        )
        toc_blocks = _extract_standard_toc_blocks(text, matches)
        accepted_blocks, toc_failures, toc_corrections = (
            _align_standard_toc_blocks(text, matches, toc_blocks)
        )
    supplemented_matches = _source_header_matches(
        text,
        missing_toc_entries=toc_failures,
    )
    supplemented_matches = sorted(
        [
            *supplemented_matches,
            *(match for match in matches if match.re is _WORD_SECTION_HEADER_RE),
        ],
        key=lambda match: match.start(),
    )
    if len(supplemented_matches) > len(matches):
        matches = supplemented_matches
        supplemental_header_count = sum(
            match.re in (
                _BARE_ANNOTATED_SECTION_HEADER_RE,
                _BARE_BODY_SECTION_HEADER_RE,
                _WORD_SECTION_HEADER_RE,
                _RULE_SECTION_HEADER_RE,
            )
            for match in matches
        )
        report.raw_section_marker_count = (
            len(source_markers) + supplemental_header_count
        )
        toc_blocks = _extract_standard_toc_blocks(text, matches)
        accepted_blocks, toc_failures, toc_corrections = (
            _align_standard_toc_blocks(text, matches, toc_blocks)
        )
    if accepted_blocks:
        source_units = _standard_source_units(text, matches, accepted_blocks)
        base_source_unit_count = len(source_units)
        source_units = _augment_body_local_inventory_units(
            text,
            matches,
            source_units,
        )
        source_units = _augment_local_generated_inventory_units(
            text,
            matches,
            source_units,
        )
        source_units = _augment_title_body_units(
            text,
            matches,
            source_units,
        )
        source_units = _redirect_added_without_title_units(
            text,
            matches,
            source_units,
        )
        source_units = _augment_explicit_schedule_omission_units(
            text,
            matches,
            source_units,
        )
        source_units = _augment_annotated_body_units(
            text,
            matches,
            source_units,
        )
        augmented_source_unit_count = len(source_units) - base_source_unit_count
        parsed = _parse_source_bound_units(
            report,
            text=text,
            matches=matches,
            units=source_units,
            code=code,
            name=name,
            code_name=code_name,
            bundle_url=bundle_url,
            toc_section_count=sum(
                len(block.entries) for block in accepted_blocks
            ) + augmented_source_unit_count,
            toc_failures=[*toc_failures, *unparsed_marker_residuals],
            toc_corrections=toc_corrections,
            first_toc_start=min(block.toc_start for block in accepted_blocks),
            extra_source_residual_count=len(unparsed_marker_residuals),
            source_sections_without_raw_markers=len(toc_failures),
        )
        return reconcile_new_york_supplemental_proofs(parsed, registry)

    report.unclassified_sections.extend(unparsed_marker_residuals)
    # A law can quote another enacted compact inside one of its own sections.
    # The quoted compact's internal section headings are body text, not another
    # set of top-level identities in the containing New York law.  Admit that
    # distinction only when the active primary section expressly introduces a
    # compact as source text.  Every other repeated header remains a typed,
    # fail-closed residual rather than being silently deduplicated.
    primary_matches = []
    seen: set[str] = set()
    active_primary = None
    active_primary_key = ""
    active_embedded_compact = False
    for match in matches:
        section = str(match.group("section") or "").strip()
        section_key = section.casefold()
        if section and section_key not in seen:
            seen.add(section_key)
            primary_matches.append(match)
            active_primary = match
            active_primary_key = section_key
            active_embedded_compact = False
            continue

        if (
            section
            and active_primary is not None
            and section_key != active_primary_key
        ):
            parent_prefix = text[active_primary.end() : match.start()]
            active_embedded_compact = bool(
                active_embedded_compact
                or _EMBEDDED_COMPACT_INTRO_RE.search(parent_prefix)
            )
            if active_embedded_compact:
                report.embedded_section_markers.append(
                    {
                        "section_number": section,
                        "parent_section_number": str(
                            active_primary.group("section") or ""
                        ).strip(),
                        "reason": "embedded_compact_section_header",
                    }
                )
                continue

        report.unclassified_sections.append(
            {
                "section_number": section,
                "reason": (
                    "duplicate_section_header" if section_key in seen
                    else "missing_section_number"
                ),
            }
        )

    report.source_section_count = (
        report.raw_section_marker_count - len(report.embedded_section_markers)
    )
    for index, match in enumerate(primary_matches):
        section = str(match.group("section") or "").strip()
        chunk_end = (
            primary_matches[index + 1].start()
            if index + 1 < len(primary_matches)
            else len(text)
        )
        raw_chunk = text[match.start() : chunk_end]
        chunk = _WS.sub(" ", raw_chunk).strip()
        after_marker = text[match.end() : chunk_end]
        normalized_after = _WS.sub(" ", after_marker).strip()

        terminal = _TERMINAL_RE.match(normalized_after)
        if terminal:
            report.terminal_sections.append(
                {
                    "section_number": section,
                    "disposition": terminal.group(1).lower(),
                    "source_url": public_section_url(code, section),
                }
            )
            continue
        if len(chunk) < 20 or len(normalized_after) < 8:
            report.unclassified_sections.append(
                {
                    "section_number": section,
                    "reason": "missing_or_short_operative_body",
                }
            )
            continue

        section_name = _section_heading(normalized_after, section)
        report.statutes.append(
            NormalizedStatute(
                state_code="NY",
                state_name="New York",
                statute_id=f"{code_name} § {code} {section}",
                code_name=code_name,
                title_number=code,
                title_name=name,
                section_number=section,
                section_name=section_name,
                full_text=chunk,
                source_url=public_section_url(code, section),
                official_cite=f"N.Y. {code} Law § {section}",
                metadata=StatuteMetadata(),
                structured_data={
                    "source_kind": "official_new_york_senate_law_pdf",
                    "source_authority_class": "official",
                    "discovery_method": "nysenate_full_law_pdf",
                    "law_code": code,
                    "source_bundle_url": bundle_url,
                    "source_record_id": f"{code}:{section}",
                    "skip_hydrate": True,
                },
            )
        )

    report.closed = bool(
        report.page_count > 0
        and report.source_section_count > 0
        and (
            report.raw_section_marker_count
            + report.source_sections_without_raw_markers
            == report.source_section_count
            + len(report.embedded_section_markers)
            + len(report.lifecycle_alternate_sections)
        )
        and report.source_section_count
        == len(report.statutes)
        + len(report.terminal_sections)
        + len(report.unclassified_sections)
        and not report.unclassified_sections
    )
    return reconcile_new_york_supplemental_proofs(report, registry)
