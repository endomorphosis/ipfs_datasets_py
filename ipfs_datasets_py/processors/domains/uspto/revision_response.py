"""Respond to USPTO deficiency letters / office actions by revising submissions.

Operator workflow (decision-support only)
-----------------------------------------
1. ``scan`` IFW inventory (from export-ui / public ODP) for outgoing documents
   that typically require a reply (office actions, missing-parts, non-compliant
   amendment notices, etc.).
2. ``open`` a local revision case bound to the application + triggering document.
3. ``prepare`` a response package skeleton + filing checklist.
4. ``attach`` revised claims/spec/drawings/remarks (human-authored files).
5. Use ``filing-assist`` / human Sign-Pay-Submit (never automated).
6. ``mark-submitted`` only after an external human assertion; then
   ``watch-receipts`` for EAR/payment.

This module never signs, pays, files, or claims a docket deadline is final.
Reply-date fields are **review-only candidates**.
"""

from __future__ import annotations

import calendar
import hashlib
import json
import re
import shutil
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final, Iterable, Mapping, Sequence

from ipfs_datasets_py.processors.domains.uspto.filing_assist import (
    build_filing_checklist,
    compute_package_digest,
    write_filing_checklist,
)
from ipfs_datasets_py.processors.domains.uspto.portfolio_automation import (
    PortfolioAutomationError,
    default_state_root,
    utc_now_iso,
)

REVISION_SCHEMA: Final = "patlaw-revision-case-v1"
REVISION_SCAN_SCHEMA: Final = "patlaw-revision-scan-v1"
REVISION_INDEX_SCHEMA: Final = "patlaw-revision-index-v1"

REVIEW_ONLY_DEADLINE_DISCLAIMER: Final = (
    "Reply-date candidates are review-only decision support, not a docket "
    "entry and not legal advice. Confirm periods on the face of the USPTO "
    "letter (and any extensions under 37 C.F.R. 1.136) before relying on them."
)

_APP_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9/_\-]{2,31}\Z")
_ISO_DATE_RE = re.compile(r"\A\d{4}-\d{2}-\d{2}")


class RevisionCaseState(str, Enum):
    OPEN = "open"
    PREPARED = "prepared"
    HUMAN_READY = "human-ready"
    SUBMITTED = "submitted"
    CLOSED = "closed"
    CANCELLED = "cancelled"


class TriggerKind(str, Enum):
    OFFICE_ACTION_NONFINAL = "office_action_nonfinal"
    OFFICE_ACTION_FINAL = "office_action_final"
    ADVISORY_ACTION = "advisory_action"
    RESTRICTION = "restriction_requirement"
    MISSING_PARTS = "missing_parts"
    INCOMPLETE_APPLICATION = "incomplete_application"
    NONCOMPLIANT_AMENDMENT = "noncompliant_amendment"
    DEFICIENCY_NOTICE = "deficiency_notice"
    MISC_COMMUNICATION = "miscellaneous_communication"
    NOTICE_REQUIRING_RESPONSE = "notice_requiring_response"
    OTHER_OUTGOING = "other_outgoing"
    MANUAL = "manual"


# Document codes that commonly open a response/revision obligation.
# period_months is a *review-only default SSP/reply period* when the face of
# the paper is not yet OCR'd; always verify on the letter.
_CODE_TRIGGERS: Final[Mapping[str, tuple[TriggerKind, int | None]]] = MappingProxyType(
    {
        "CTNF": (TriggerKind.OFFICE_ACTION_NONFINAL, 3),
        "CTFR": (TriggerKind.OFFICE_ACTION_FINAL, 3),
        "CTAV": (TriggerKind.ADVISORY_ACTION, 3),
        "CTRS": (TriggerKind.RESTRICTION, 2),
        "CTMS": (TriggerKind.MISC_COMMUNICATION, 3),
        "EXIN": (TriggerKind.MISC_COMMUNICATION, None),
        "OA": (TriggerKind.OFFICE_ACTION_NONFINAL, 3),
        "NRES": (TriggerKind.RESTRICTION, 2),
        # Missing / incomplete family (codes vary by era)
        "NTCMIS": (TriggerKind.MISSING_PARTS, 2),
        "NTC.MIS": (TriggerKind.MISSING_PARTS, 2),
        "NTC.MISS": (TriggerKind.MISSING_PARTS, 2),
        "A.NTC.MIS": (TriggerKind.MISSING_PARTS, 2),
        "MP": (TriggerKind.MISSING_PARTS, 2),
        "N417.INC": (TriggerKind.INCOMPLETE_APPLICATION, 2),
    }
)

_DESC_PATTERNS: Final[tuple[tuple[re.Pattern[str], TriggerKind, int | None], ...]] = (
    (
        re.compile(r"non[-\s]?final\s+reject|nonfinal\s+office\s+action", re.I),
        TriggerKind.OFFICE_ACTION_NONFINAL,
        3,
    ),
    (
        re.compile(r"\bfinal\s+reject|final\s+office\s+action", re.I),
        TriggerKind.OFFICE_ACTION_FINAL,
        3,
    ),
    (re.compile(r"advisory\s+action", re.I), TriggerKind.ADVISORY_ACTION, 3),
    (
        re.compile(r"restriction\s+requirement|election\s+of\s+species", re.I),
        TriggerKind.RESTRICTION,
        2,
    ),
    (
        re.compile(r"missing\s+parts|notice\s+to\s+file\s+missing", re.I),
        TriggerKind.MISSING_PARTS,
        2,
    ),
    (
        re.compile(r"incomplete\s+application|notice\s+of\s+incomplete", re.I),
        TriggerKind.INCOMPLETE_APPLICATION,
        2,
    ),
    (
        re.compile(r"non[-\s]?compliant\s+amendment|noncompliant\s+amendment", re.I),
        TriggerKind.NONCOMPLIANT_AMENDMENT,
        2,
    ),
    (
        re.compile(r"deficien(t|cy)|correct(ion)?\s+required|cure\s+required", re.I),
        TriggerKind.DEFICIENCY_NOTICE,
        2,
    ),
    (
        re.compile(r"period\s+for\s+reply|response\s+required|require[sd]\s+response", re.I),
        TriggerKind.NOTICE_REQUIRING_RESPONSE,
        3,
    ),
)

# Roles human may attach into the response package.
ALLOWED_ATTACHMENT_ROLES: Final[frozenset[str]] = frozenset(
    {
        "amended_claims",
        "amended_specification",
        "substitute_specification",
        "amended_drawings",
        "remarks",
        "amendment_transmittal",
        "ids",
        "declaration",
        "fee_transmittal",
        "evidence",
        "other",
        "triggering_letter",
    }
)

# Suggested empty placeholders by trigger kind (content-free filenames).
_SUGGESTED_PLACEHOLDERS: Final[Mapping[TriggerKind, tuple[str, ...]]] = MappingProxyType(
    {
        TriggerKind.OFFICE_ACTION_NONFINAL: (
            "01_remarks.docx",
            "02_amended_claims.pdf",
            "03_amendment_transmittal.pdf",
        ),
        TriggerKind.OFFICE_ACTION_FINAL: (
            "01_remarks.docx",
            "02_amended_claims.pdf",
            "03_amendment_transmittal.pdf",
            "04_extension_of_time_if_needed.pdf",
        ),
        TriggerKind.MISSING_PARTS: (
            "01_missing_parts_response.pdf",
            "02_required_document.pdf",
            "03_fee_transmittal_if_needed.pdf",
        ),
        TriggerKind.INCOMPLETE_APPLICATION: (
            "01_completion_papers.pdf",
            "02_substitute_specification_if_needed.pdf",
        ),
        TriggerKind.NONCOMPLIANT_AMENDMENT: (
            "01_compliant_amendment.pdf",
            "02_remarks.docx",
        ),
        TriggerKind.DEFICIENCY_NOTICE: (
            "01_cure_response.pdf",
            "02_corrected_document.pdf",
        ),
        TriggerKind.RESTRICTION: (
            "01_election_and_remarks.pdf",
        ),
        TriggerKind.ADVISORY_ACTION: (
            "01_remarks_or_rce_papers.pdf",
        ),
        TriggerKind.MISC_COMMUNICATION: (
            "01_response.pdf",
        ),
        TriggerKind.NOTICE_REQUIRING_RESPONSE: (
            "01_response.pdf",
        ),
        TriggerKind.OTHER_OUTGOING: (
            "01_response.pdf",
        ),
        TriggerKind.MANUAL: (
            "01_response.pdf",
        ),
    }
)


class RevisionError(PortfolioAutomationError):
    """Fail-closed revision workflow error."""


def _normalize_app(app: str) -> str:
    text = str(app or "").strip().replace(",", "").replace(" ", "")
    if not text or not _APP_RE.match(text):
        raise RevisionError("invalid application_number", code="invalid_application_number")
    return text


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    text = str(value).strip()
    m = _ISO_DATE_RE.match(text)
    if not m:
        return None
    try:
        return date.fromisoformat(m.group(0)[:10])
    except ValueError:
        return None


def _add_calendar_months(start: date, months: int) -> date:
    """Add calendar months (CFR-style month arithmetic, review-only)."""
    month = start.month - 1 + months
    year = start.year + month // 12
    month = month % 12 + 1
    day = min(start.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def _weekend_to_monday(d: date) -> date:
    # Saturday→Monday, Sunday→Monday (simple US federal next-business-day stub;
    # does not encode full holiday calendar — review-only).
    if d.weekday() == 5:
        return d + timedelta(days=2)
    if d.weekday() == 6:
        return d + timedelta(days=1)
    return d


def revisions_root(state_root: Path | None = None) -> Path:
    root = Path(state_root) if state_root else default_state_root()
    path = root / "revisions"
    path.mkdir(parents=True, exist_ok=True)
    return path


def classify_trigger(
    *,
    document_code: str = "",
    document_description: str = "",
    direction: str = "",
) -> tuple[TriggerKind | None, int | None, list[str]]:
    """Classify whether an IFW entry likely needs a revision/response.

    Returns (kind or None if not a trigger, period_months, reasons).
    """
    code = str(document_code or "").strip().upper()
    desc = str(document_description or "").strip()
    direction_u = str(direction or "").strip().upper()
    reasons: list[str] = []

    # Prefer outgoing government letters
    if direction_u and direction_u not in {"OUTGOING", "OUT", "O"}:
        # Incoming applicant docs are not deficiency letters
        if direction_u in {"INCOMING", "IN", "I"}:
            return None, None, ["direction_incoming"]

    if code in _CODE_TRIGGERS:
        kind, months = _CODE_TRIGGERS[code]
        reasons.append(f"document_code:{code}")
        return kind, months, reasons

    for pattern, kind, months in _DESC_PATTERNS:
        if pattern.search(desc):
            reasons.append(f"description_match:{kind.value}")
            return kind, months, reasons

    return None, None, ["no_trigger_match"]


def candidate_reply_window(
    *,
    official_date: str | None,
    period_months: int | None,
) -> dict[str, Any]:
    """Build a review-only reply-date candidate from mailing date + months."""
    basis = _parse_date(official_date)
    out: dict[str, Any] = {
        "basis_date": basis.isoformat() if basis else None,
        "period_months": period_months,
        "candidate_date": None,
        "candidate_date_adjusted": None,
        "rule_labels": [],
        "disclaimer": REVIEW_ONLY_DEADLINE_DISCLAIMER,
        "status": "unknown",
    }
    if basis is None or period_months is None:
        out["status"] = "unknown"
        out["rule_labels"] = ["missing_basis_or_period"]
        return out
    raw = _add_calendar_months(basis, int(period_months))
    adjusted = _weekend_to_monday(raw)
    out["candidate_date"] = raw.isoformat()
    out["candidate_date_adjusted"] = adjusted.isoformat()
    out["rule_labels"] = [
        "calendar_month_period_review_only",
        "weekend_to_monday_stub_review_only",
    ]
    out["status"] = "review_only_candidate"
    return out


@dataclass
class TriggerDocument:
    document_identifier: str = ""
    document_code: str = ""
    document_description: str = ""
    official_date: str = ""
    direction: str = ""
    local_path: str = ""
    kind: str = TriggerKind.MANUAL.value
    period_months: int | None = None
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "document_identifier": self.document_identifier,
            "document_code": self.document_code,
            "document_description": self.document_description,
            "official_date": self.official_date,
            "direction": self.direction,
            "local_path": self.local_path,
            "kind": self.kind,
            "period_months": self.period_months,
            "reasons": list(self.reasons),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TriggerDocument":
        return cls(
            document_identifier=str(value.get("document_identifier") or ""),
            document_code=str(value.get("document_code") or ""),
            document_description=str(value.get("document_description") or ""),
            official_date=str(value.get("official_date") or ""),
            direction=str(value.get("direction") or ""),
            local_path=str(value.get("local_path") or ""),
            kind=str(value.get("kind") or TriggerKind.MANUAL.value),
            period_months=value.get("period_months"),
            reasons=list(value.get("reasons") or []),
        )


@dataclass
class RevisionAttachment:
    role: str
    path: str
    sha256: str = ""
    filename: str = ""
    attached_at_utc: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "path": self.path,
            "sha256": self.sha256,
            "filename": self.filename,
            "attached_at_utc": self.attached_at_utc,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "RevisionAttachment":
        return cls(
            role=str(value.get("role") or "other"),
            path=str(value.get("path") or ""),
            sha256=str(value.get("sha256") or ""),
            filename=str(value.get("filename") or ""),
            attached_at_utc=str(value.get("attached_at_utc") or ""),
        )


@dataclass
class RevisionCase:
    schema: str = REVISION_SCHEMA
    revision_id: str = ""
    application_number: str = ""
    state: str = RevisionCaseState.OPEN.value
    trigger: TriggerDocument = field(default_factory=TriggerDocument)
    response_kind: str = "response"
    candidate_reply: dict[str, Any] = field(default_factory=dict)
    case_dir: str = ""
    package_dir: str = ""
    attachments: list[RevisionAttachment] = field(default_factory=list)
    package_digest: str = ""
    notes: list[str] = field(default_factory=list)
    created_at_utc: str = ""
    updated_at_utc: str = ""
    submitted_at_utc: str = ""
    submitted_package_digest: str = ""
    submitted_by: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "revision_id": self.revision_id,
            "application_number": self.application_number,
            "state": self.state,
            "trigger": self.trigger.to_dict(),
            "response_kind": self.response_kind,
            "candidate_reply": dict(self.candidate_reply),
            "case_dir": self.case_dir,
            "package_dir": self.package_dir,
            "attachments": [a.to_dict() for a in self.attachments],
            "package_digest": self.package_digest,
            "notes": list(self.notes),
            "created_at_utc": self.created_at_utc,
            "updated_at_utc": self.updated_at_utc,
            "submitted_at_utc": self.submitted_at_utc,
            "submitted_package_digest": self.submitted_package_digest,
            "submitted_by": self.submitted_by,
            "disclaimer": (
                "Decision support only. Never auto-files. "
                + REVIEW_ONLY_DEADLINE_DISCLAIMER
            ),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "RevisionCase":
        trigger_raw = value.get("trigger") or {}
        atts = [
            RevisionAttachment.from_dict(a)
            for a in (value.get("attachments") or [])
            if isinstance(a, Mapping)
        ]
        return cls(
            schema=str(value.get("schema") or REVISION_SCHEMA),
            revision_id=str(value.get("revision_id") or ""),
            application_number=str(value.get("application_number") or ""),
            state=str(value.get("state") or RevisionCaseState.OPEN.value),
            trigger=TriggerDocument.from_dict(trigger_raw)
            if isinstance(trigger_raw, Mapping)
            else TriggerDocument(),
            response_kind=str(value.get("response_kind") or "response"),
            candidate_reply=dict(value.get("candidate_reply") or {}),
            case_dir=str(value.get("case_dir") or ""),
            package_dir=str(value.get("package_dir") or ""),
            attachments=atts,
            package_digest=str(value.get("package_digest") or ""),
            notes=list(value.get("notes") or []),
            created_at_utc=str(value.get("created_at_utc") or ""),
            updated_at_utc=str(value.get("updated_at_utc") or ""),
            submitted_at_utc=str(value.get("submitted_at_utc") or ""),
            submitted_package_digest=str(value.get("submitted_package_digest") or ""),
            submitted_by=str(value.get("submitted_by") or ""),
        )


def _case_path(state_root: Path, revision_id: str) -> Path:
    return revisions_root(state_root) / f"{revision_id}.json"


def save_revision_case(case: RevisionCase, state_root: Path | None = None) -> Path:
    root = Path(state_root) if state_root else default_state_root()
    case.updated_at_utc = utc_now_iso()
    path = _case_path(root, case.revision_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(case.to_dict(), indent=2) + "\n", encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    # Mirror into case_dir if present
    if case.case_dir:
        mirror = Path(case.case_dir) / "revision_case.json"
        try:
            mirror.write_text(json.dumps(case.to_dict(), indent=2) + "\n", encoding="utf-8")
        except OSError:
            pass
    return path


def load_revision_case(
    revision_id: str, *, state_root: Path | None = None
) -> RevisionCase:
    root = Path(state_root) if state_root else default_state_root()
    path = _case_path(root, revision_id)
    if not path.is_file():
        # Also accept bare id without rev- prefix search
        matches = list(revisions_root(root).glob(f"*{revision_id}*.json"))
        if len(matches) == 1:
            path = matches[0]
        else:
            raise RevisionError(
                f"revision case not found: {revision_id}", code="revision_not_found"
            )
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, Mapping):
        raise RevisionError("invalid revision case file", code="invalid_revision_case")
    return RevisionCase.from_dict(data)


def list_revision_cases(
    *,
    state_root: Path | None = None,
    application_number: str = "",
    include_closed: bool = False,
) -> list[RevisionCase]:
    root = Path(state_root) if state_root else default_state_root()
    app = str(application_number or "").strip()
    if app:
        app = _normalize_app(app)
    cases: list[RevisionCase] = []
    for path in sorted(revisions_root(root).glob("rev-*.json")):
        try:
            case = RevisionCase.from_dict(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            continue
        if app and case.application_number != app:
            continue
        if not include_closed and case.state in {
            RevisionCaseState.CLOSED.value,
            RevisionCaseState.CANCELLED.value,
        }:
            continue
        cases.append(case)
    return cases


def _load_ifw_docs_from_paths(paths: Sequence[Path]) -> list[dict[str, Any]]:
    docs: list[dict[str, Any]] = []
    for path in paths:
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(data, Mapping) and "documents" in data:
            bag = data.get("documents") or []
            if isinstance(bag, list):
                for d in bag:
                    if isinstance(d, Mapping):
                        docs.append(dict(d))
        elif isinstance(data, Mapping) and "resultBag" in data:
            for item in data.get("resultBag") or []:
                if not isinstance(item, Mapping):
                    continue
                for d in item.get("documentBag") or []:
                    if isinstance(d, Mapping):
                        docs.append(dict(d))
        elif isinstance(data, list):
            for d in data:
                if isinstance(d, Mapping):
                    docs.append(dict(d))
        elif isinstance(data, Mapping) and "documentBag" in data:
            for d in data.get("documentBag") or []:
                if isinstance(d, Mapping):
                    docs.append(dict(d))
    return docs


def discover_ifw_metadata_paths(
    application_number: str, *, state_root: Path | None = None
) -> list[Path]:
    """Locate local IFW inventory JSON for an application."""
    app = _normalize_app(application_number)
    root = Path(state_root) if state_root else default_state_root()
    candidates = [
        root / "exports" / app / "patent_center_ui" / "metadata" / "ifw_document_summary.json",
        root
        / "exports"
        / app
        / "patent_center_ui"
        / "metadata"
        / "ifw_document_inventory.json",
        root
        / "exports"
        / app
        / "patent_center_ui"
        / "metadata"
        / f"spa_retrieval_private_v1_applications_sdwp_external_metadata_{app}.json",
        root / "exports" / app / "public_odp_wrapper" / "public_odp_inventory.json",
    ]
    # Also search sdwp spa files generically
    meta_dir = root / "exports" / app / "patent_center_ui" / "metadata"
    if meta_dir.is_dir():
        candidates.extend(sorted(meta_dir.glob("*sdwp*metadata*.json")))
        candidates.extend(sorted(meta_dir.glob("ifw*.json")))
    # Dedup existing
    out: list[Path] = []
    seen: set[str] = set()
    for p in candidates:
        key = str(p.resolve()) if p.exists() else str(p)
        if key in seen:
            continue
        seen.add(key)
        if p.is_file():
            out.append(p)
    return out


def resolve_local_document_path(
    application_number: str,
    document_identifier: str,
    *,
    state_root: Path | None = None,
) -> Path | None:
    """Best-effort find a downloaded PDF for a document id/code."""
    app = _normalize_app(application_number)
    root = Path(state_root) if state_root else default_state_root()
    doc_id = str(document_identifier or "").strip()
    if not doc_id:
        return None
    search_roots = [
        root / "exports" / app / "patent_center_ui" / "files",
        root / "exports" / app / "patent_center_ui" / "package",
        root / "exports" / app / "public_odp_wrapper",
        root / "public_docs" / "admitted",
    ]
    for base in search_roots:
        if not base.is_dir():
            continue
        for path in base.rglob("*"):
            if not path.is_file():
                continue
            name = path.name
            if doc_id in name or doc_id.replace("-", "") in name:
                return path
    return None


def scan_response_triggers(
    application_number: str,
    *,
    state_root: Path | None = None,
    include_all_outgoing: bool = False,
) -> dict[str, Any]:
    """Scan local IFW metadata for letters that may require a revision response."""
    app = _normalize_app(application_number)
    root = Path(state_root) if state_root else default_state_root()
    paths = discover_ifw_metadata_paths(app, state_root=root)
    raw_docs = _load_ifw_docs_from_paths(paths)

    # Normalize heterogeneous inventory shapes
    normalized: list[dict[str, Any]] = []
    for d in raw_docs:
        code = str(
            d.get("documentCode")
            or d.get("document_code")
            or d.get("code")
            or ""
        )
        desc = str(
            d.get("documentDescription")
            or d.get("document_description")
            or d.get("description")
            or d.get("filename")
            or ""
        )
        doc_id = str(
            d.get("documentIdentifier")
            or d.get("document_identifier")
            or d.get("source_document_id")
            or d.get("filename")
            or ""
        )
        official = str(
            d.get("officialDate")
            or d.get("official_date")
            or d.get("mailDate")
            or ""
        )
        direction = str(
            d.get("directionCategory") or d.get("direction") or "OUTGOING"
        )
        normalized.append(
            {
                "document_code": code,
                "document_description": desc,
                "document_identifier": doc_id,
                "official_date": official,
                "direction": direction,
            }
        )

    triggers: list[dict[str, Any]] = []
    skipped = 0
    for d in normalized:
        kind, months, reasons = classify_trigger(
            document_code=d["document_code"],
            document_description=d["document_description"],
            direction=d["direction"],
        )
        if kind is None:
            if include_all_outgoing and str(d["direction"]).upper().startswith("OUT"):
                kind = TriggerKind.OTHER_OUTGOING
                months = None
                reasons = ["include_all_outgoing"]
            else:
                skipped += 1
                continue
        local = resolve_local_document_path(
            app, d["document_identifier"], state_root=root
        )
        reply = candidate_reply_window(
            official_date=d["official_date"], period_months=months
        )
        triggers.append(
            {
                **d,
                "kind": kind.value,
                "period_months": months,
                "reasons": reasons,
                "local_path": str(local) if local else "",
                "candidate_reply": reply,
            }
        )

    # Sort newest first
    def _sort_key(item: Mapping[str, Any]) -> str:
        return str(item.get("official_date") or "")

    triggers.sort(key=_sort_key, reverse=True)

    return {
        "schema": REVISION_SCAN_SCHEMA,
        "application_number": app,
        "source_paths": [str(p) for p in paths],
        "document_count_scanned": len(normalized),
        "trigger_count": len(triggers),
        "skipped_count": skipped,
        "triggers": triggers,
        "open_revisions": [
            c.to_dict()
            for c in list_revision_cases(state_root=root, application_number=app)
        ],
        "disclaimer": REVIEW_ONLY_DEADLINE_DISCLAIMER,
        "generated_at_utc": utc_now_iso(),
        "hint": (
            "If trigger_count is 0, run export-ui first to refresh IFW inventory, "
            "or open a manual revision with --document-code / --document-description."
        ),
    }


def open_revision_case(
    application_number: str,
    *,
    state_root: Path | None = None,
    document_identifier: str = "",
    document_code: str = "",
    document_description: str = "",
    official_date: str = "",
    direction: str = "OUTGOING",
    local_path: str = "",
    kind: str = "",
    period_months: int | None = None,
    notes: Sequence[str] = (),
) -> RevisionCase:
    """Create a revision case directory + record for a deficiency/OA letter."""
    app = _normalize_app(application_number)
    root = Path(state_root) if state_root else default_state_root()

    auto_kind, auto_months, reasons = classify_trigger(
        document_code=document_code,
        document_description=document_description,
        direction=direction,
    )
    if kind:
        try:
            trigger_kind = TriggerKind(kind)
        except ValueError:
            trigger_kind = TriggerKind.MANUAL
            reasons = list(reasons) + [f"unknown_kind:{kind}"]
    else:
        trigger_kind = auto_kind or TriggerKind.MANUAL
        if auto_kind is None:
            reasons = list(reasons) + ["manual_open"]

    months = period_months if period_months is not None else auto_months
    if not local_path and document_identifier:
        found = resolve_local_document_path(app, document_identifier, state_root=root)
        if found:
            local_path = str(found)

    rid = f"rev-{app}-{uuid.uuid4().hex[:10]}"
    case_dir = revisions_root(root) / "cases" / app / rid
    package_dir = case_dir / "response_package"
    for sub in (
        case_dir / "triggering",
        case_dir / "drafts",
        package_dir,
        case_dir / "receipts",
    ):
        sub.mkdir(parents=True, exist_ok=True)

    # Copy triggering letter into case if we have a local file
    trigger = TriggerDocument(
        document_identifier=str(document_identifier or ""),
        document_code=str(document_code or ""),
        document_description=str(document_description or ""),
        official_date=str(official_date or ""),
        direction=str(direction or "OUTGOING"),
        local_path=str(local_path or ""),
        kind=trigger_kind.value,
        period_months=months,
        reasons=list(reasons),
    )
    if local_path and Path(local_path).is_file():
        dest = case_dir / "triggering" / Path(local_path).name
        try:
            shutil.copy2(local_path, dest)
            trigger.local_path = str(dest)
        except OSError:
            pass

    # Placeholder README for drafts
    placeholders = _SUGGESTED_PLACEHOLDERS.get(
        trigger_kind, _SUGGESTED_PLACEHOLDERS[TriggerKind.MANUAL]
    )
    (case_dir / "drafts" / "README.txt").write_text(
        "Place human-authored revision drafts here, then:\n"
        "  portfolio_cli.py revise attach --revision-id "
        f"{rid} --file <path> --role amended_claims\n"
        "Suggested response package filenames:\n"
        + "\n".join(f"  - {name}" for name in placeholders)
        + "\n\nHARD BARRIER: Sign / Pay / Submit remain human-only in Patent Center.\n",
        encoding="utf-8",
    )

    now = utc_now_iso()
    case = RevisionCase(
        revision_id=rid,
        application_number=app,
        state=RevisionCaseState.OPEN.value,
        trigger=trigger,
        response_kind=trigger_kind.value,
        candidate_reply=candidate_reply_window(
            official_date=official_date or None, period_months=months
        ),
        case_dir=str(case_dir),
        package_dir=str(package_dir),
        notes=list(notes),
        created_at_utc=now,
        updated_at_utc=now,
    )
    save_revision_case(case, state_root=root)
    return case


def attach_to_revision(
    revision_id: str,
    file_path: Path,
    *,
    role: str = "other",
    state_root: Path | None = None,
    copy: bool = True,
) -> RevisionCase:
    """Attach a human-authored file into the response package."""
    root = Path(state_root) if state_root else default_state_root()
    case = load_revision_case(revision_id, state_root=root)
    if case.state in {
        RevisionCaseState.CLOSED.value,
        RevisionCaseState.CANCELLED.value,
    }:
        raise RevisionError("cannot attach to closed revision", code="revision_closed")

    role_key = str(role or "other").strip().lower()
    if role_key not in ALLOWED_ATTACHMENT_ROLES:
        raise RevisionError(
            f"invalid attachment role {role_key!r}; allowed: "
            + ", ".join(sorted(ALLOWED_ATTACHMENT_ROLES)),
            code="invalid_attachment_role",
        )
    src = Path(file_path).expanduser().resolve()
    if not src.is_file():
        raise RevisionError(f"file not found: {src}", code="missing_attachment")

    package = Path(case.package_dir)
    package.mkdir(parents=True, exist_ok=True)
    dest_name = f"{role_key}__{src.name}"
    dest = package / dest_name
    if copy:
        shutil.copy2(src, dest)
    else:
        # Still copy for package integrity (no symlinks to external edits)
        shutil.copy2(src, dest)

    digest = _sha256_file(dest)
    case.attachments.append(
        RevisionAttachment(
            role=role_key,
            path=str(dest),
            sha256=digest,
            filename=dest.name,
            attached_at_utc=utc_now_iso(),
        )
    )
    try:
        case.package_digest = compute_package_digest(package)
    except Exception:
        case.package_digest = ""
    if case.state == RevisionCaseState.OPEN.value:
        case.state = RevisionCaseState.PREPARED.value
    save_revision_case(case, state_root=root)
    return case


def prepare_revision_package(
    revision_id: str,
    *,
    state_root: Path | None = None,
) -> dict[str, Any]:
    """Refresh package digest + write filing checklist for the response package."""
    root = Path(state_root) if state_root else default_state_root()
    case = load_revision_case(revision_id, state_root=root)
    package = Path(case.package_dir)
    package.mkdir(parents=True, exist_ok=True)

    # Ensure triggering letter is also in package if present
    if case.trigger.local_path and Path(case.trigger.local_path).is_file():
        tdest = package / f"triggering_letter__{Path(case.trigger.local_path).name}"
        if not tdest.exists():
            try:
                shutil.copy2(case.trigger.local_path, tdest)
            except OSError:
                pass

    files = [p for p in package.iterdir() if p.is_file() and p.name != "README.txt"]
    digest = ""
    if files:
        digest = compute_package_digest(package)
        case.package_digest = digest
        case.state = (
            RevisionCaseState.HUMAN_READY.value
            if len(files) >= 1
            else RevisionCaseState.PREPARED.value
        )
    else:
        case.state = RevisionCaseState.PREPARED.value
        case.notes = list(case.notes) + [
            "package empty — attach revised documents before filing"
        ]

    meta_dir = None
    export_meta = (
        root
        / "exports"
        / case.application_number
        / "patent_center_ui"
        / "metadata"
    )
    if export_meta.is_dir():
        meta_dir = export_meta

    checklist = build_filing_checklist(
        application_number=case.application_number,
        package_dir=package if files else None,
        package_digest=digest,
        metadata_dir=meta_dir,
        state_root=root,
    )
    # Point receipts at the revision case folder (not the default post_submit path).
    case_receipts = Path(case.case_dir) / "receipts"
    case_receipts.mkdir(parents=True, exist_ok=True)
    checklist.post_submit_receipt_dir = str(case_receipts)
    # Augment checklist with revision-specific preamble note via warnings
    checklist.warnings = list(checklist.warnings) + [
        f"revision_id={case.revision_id}",
        f"trigger_kind={case.trigger.kind}",
        f"trigger_code={case.trigger.document_code}",
        f"candidate_reply={case.candidate_reply.get('candidate_date_adjusted') or case.candidate_reply.get('candidate_date') or 'unknown'}",
        REVIEW_ONLY_DEADLINE_DISCLAIMER,
    ]
    checklist_path = write_filing_checklist(
        checklist, Path(case.case_dir) / "filing_checklist.json"
    )
    save_revision_case(case, state_root=root)

    try:
        trigger_kind_e = TriggerKind(case.trigger.kind)
    except ValueError:
        trigger_kind_e = TriggerKind.MANUAL
    response_plan = {
        "revision_id": case.revision_id,
        "application_number": case.application_number,
        "trigger": case.trigger.to_dict(),
        "candidate_reply": case.candidate_reply,
        "suggested_attachments": list(
            _SUGGESTED_PLACEHOLDERS.get(
                trigger_kind_e,
                _SUGGESTED_PLACEHOLDERS[TriggerKind.MANUAL],
            )
        ),
        "attached": [a.to_dict() for a in case.attachments],
        "package_dir": case.package_dir,
        "package_digest": case.package_digest,
        "package_file_count": len(files),
        "next_steps": [
            "Attach any missing revised documents "
            f"(revise attach --revision-id {case.revision_id} --file … --role …)",
            "Review package digest and filing checklist",
            "Run filing-assist or open Patent Center yourself",
            "HARD BARRIER: you Sign / Pay / Submit",
            "Drop EAR into case receipts/ then watch-receipts or revise mark-submitted",
        ],
        "disclaimer": REVIEW_ONLY_DEADLINE_DISCLAIMER,
    }
    plan_path = Path(case.case_dir) / "response_plan.json"
    plan_path.write_text(json.dumps(response_plan, indent=2) + "\n", encoding="utf-8")

    return {
        "ok": True,
        "case": case.to_dict(),
        "checklist_path": str(checklist_path),
        "response_plan_path": str(plan_path),
        "response_plan": response_plan,
        "generated_at_utc": utc_now_iso(),
    }


def mark_revision_submitted(
    revision_id: str,
    *,
    authorizing_user: str,
    package_digest: str = "",
    state_root: Path | None = None,
    notes: Sequence[str] = (),
) -> RevisionCase:
    """Record that a natural person submitted the response (external assertion)."""
    root = Path(state_root) if state_root else default_state_root()
    case = load_revision_case(revision_id, state_root=root)
    user = str(authorizing_user or "").strip()
    if not user or user.lower() in {"system", "bot", "automation"}:
        raise RevisionError(
            "mark-submitted requires a human authorizing_user label",
            code="human_assertion_required",
        )
    digest = str(package_digest or case.package_digest or "").strip().lower()
    if digest and case.package_digest and digest != case.package_digest:
        case.notes = list(case.notes) + [
            f"submitted digest {digest[:16]}… differs from package_digest "
            f"{case.package_digest[:16]}…"
        ]
    case.state = RevisionCaseState.SUBMITTED.value
    case.submitted_at_utc = utc_now_iso()
    case.submitted_by = user
    case.submitted_package_digest = digest or case.package_digest
    case.notes = list(case.notes) + list(notes) + [
        "External human assertion: response filed in Patent Center outside automation."
    ]
    save_revision_case(case, state_root=root)
    return case


def close_revision_case(
    revision_id: str,
    *,
    state_root: Path | None = None,
    cancel: bool = False,
    note: str = "",
) -> RevisionCase:
    root = Path(state_root) if state_root else default_state_root()
    case = load_revision_case(revision_id, state_root=root)
    case.state = (
        RevisionCaseState.CANCELLED.value if cancel else RevisionCaseState.CLOSED.value
    )
    if note:
        case.notes = list(case.notes) + [note]
    save_revision_case(case, state_root=root)
    return case


__all__ = [
    "ALLOWED_ATTACHMENT_ROLES",
    "REVISION_SCHEMA",
    "REVIEW_ONLY_DEADLINE_DISCLAIMER",
    "RevisionAttachment",
    "RevisionCase",
    "RevisionCaseState",
    "RevisionError",
    "TriggerDocument",
    "TriggerKind",
    "attach_to_revision",
    "candidate_reply_window",
    "classify_trigger",
    "close_revision_case",
    "discover_ifw_metadata_paths",
    "list_revision_cases",
    "load_revision_case",
    "mark_revision_submitted",
    "open_revision_case",
    "prepare_revision_package",
    "resolve_local_document_path",
    "revisions_root",
    "save_revision_case",
    "scan_response_triggers",
]
