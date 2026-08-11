"""Pre-submission workflow and mandatory human gate (PATLAW-052).

Owns the package preflight **state machine** and **named human review
receipt**. Final USPTO filing remains external: this module never signs,
pays, files, automates Patent Center, or marks a package as submitted.

Design invariants
-----------------
* Run package preflight against an immutable analysis bundle + gap report
  (and optional dossier / prior-art readiness inputs).
* Every open unknown, gap, candidate date, and mandatory reviewer action
  requires explicit human resolution or acceptance.
* Named human review is bound to content digests (bundle, gap report,
  package). Changed material inputs **invalidate** any prior review.
* Export surface is a :class:`ReviewedPackageManifest` only — decision
  support for an external filing handoff, not a filing authorization.
* Acknowledgement and payment receipts are admitted only as
  **user-supplied** post-filing evidence imports. They are never
  fabricated by the workflow.
* Forbidden operations raise :class:`ForbiddenWorkflowActionError` and
  never appear as successful phase transitions.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Any, Callable, Final, Mapping, Sequence

from ipfs_datasets_py.processors.domains.uspto.contracts import (
    DisclosureClassification,
    ReviewState,
    canonical_json,
    is_private_classification,
    requires_quarantine,
)

# Soft imports keep the import graph light for unit tests that supply
# compact digests rather than full dossier / gap-report objects.
try:
    from ipfs_datasets_py.processors.domains.uspto.analysis.gap_report import (
        GAP_REPORT_SCHEMA_VERSION,
        CandidateDateProjection,
        GapReportLabel,
        GapStatus,
        RequirementEvidenceGapReport,
        ReviewerActionProjection,
    )
except Exception:  # pragma: no cover
    GAP_REPORT_SCHEMA_VERSION = "uspto.gap-report.v1"
    CandidateDateProjection = None  # type: ignore[misc, assignment]
    GapReportLabel = None  # type: ignore[misc, assignment]
    GapStatus = None  # type: ignore[misc, assignment]
    RequirementEvidenceGapReport = None  # type: ignore[misc, assignment]
    ReviewerActionProjection = None  # type: ignore[misc, assignment]

try:
    from ipfs_datasets_py.processors.domains.uspto.analysis.analysis_bundle import (
        UsptoAnalysisBundle,
    )
except Exception:  # pragma: no cover
    UsptoAnalysisBundle = None  # type: ignore[misc, assignment]

try:
    from ipfs_datasets_py.processors.domains.uspto.dossier_processor import (
        ApplicationDossier,
    )
except Exception:  # pragma: no cover
    ApplicationDossier = None  # type: ignore[misc, assignment]

# ---------------------------------------------------------------------------
# Versions / interface
# ---------------------------------------------------------------------------

WORKFLOW_SCHEMA_VERSION: Final = "uspto.workflow.v1"
WORKFLOW_INTERFACE: Final = "WorkflowProcessor@1"
WORKFLOW_RULESET_VERSION: Final = "preflight-human-gate-rules@1"
PARSER_VERSION: Final = "patlaw-052.workflow.v1"

OUTPUT_KIND_PREFLIGHT_RESULT: Final = "submission_preflight_result"
OUTPUT_KIND_HUMAN_REVIEW_RECEIPT: Final = "human_review_receipt"
OUTPUT_KIND_REVIEWED_PACKAGE_MANIFEST: Final = "reviewed_package_manifest"
OUTPUT_KIND_POST_FILING_EVIDENCE: Final = "post_filing_evidence_import"
OUTPUT_KIND_WORKFLOW_STATE: Final = "preflight_workflow_state"

WORKFLOW_DISCLAIMER: Final = (
    "This pre-submission workflow is decision support for human review. "
    "It never signs, pays, files, or marks a package submitted. Final "
    "filing remains external. Acknowledgement and payment receipts must "
    "be imported afterward as user-supplied evidence and are never "
    "fabricated by this workflow."
)

DEFAULT_MAX_GATES: Final = 4096
DEFAULT_MAX_RESOLUTIONS: Final = 4096
DEFAULT_MAX_WARNINGS: Final = 256
DEFAULT_MAX_REASON_CODES: Final = 128

_SHA256_RE = re.compile(r"\A[0-9a-f]{64}\Z")
_ID_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._:/=+\-]{0,255}\Z")
_ISO_UTC_RE = re.compile(
    r"\A\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})\Z"
)

# Operations that this workflow must never perform successfully.
FORBIDDEN_WORKFLOW_ACTIONS: Final[frozenset[str]] = frozenset(
    {
        "sign",
        "apply_signature",
        "pay",
        "pay_fee",
        "file",
        "file_application",
        "file_response",
        "submit",
        "perform_final_submission",
        "mark_submitted",
        "mark_as_submitted",
        "set_submitted",
        "automate_patent_center",
        "scrape_authenticated_patent_center",
        "read_browser_profile_or_session_storage",
        "store_credentials_or_cookies",
        "fabricate_acknowledgement",
        "fabricate_payment_receipt",
        "fabricate_receipt",
        "invent_filing_receipt",
    }
)

# Material input keys that participate in package digest / invalidation.
_PACKAGE_DIGEST_KEYS: Final[tuple[str, ...]] = (
    "analysis_id",
    "dossier_digest",
    "dossier_id",
    "gap_report_digest",
    "gap_report_id",
    "matter_id",
    "prior_art_checklist_digest",
    "prior_art_checklist_id",
    "schema_version",
    "source_bundle_digest",
    "source_bundle_id",
)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class PreflightPhase(str, Enum):
    """Preflight state machine phases.

    There is intentionally **no** ``submitted`` phase. After a reviewed
    package is exported, filing is external; post-filing evidence returns
    as imported records without the workflow claiming submission.
    """

    DRAFT = "draft"
    PREFLIGHT_OPEN = "preflight_open"
    REVIEW_IN_PROGRESS = "review_in_progress"
    REVIEW_BOUND = "review_bound"
    PACKAGE_EXPORTABLE = "package_exportable"
    EXTERNAL_FILING_HANDOFF = "external_filing_handoff"
    POST_FILING_EVIDENCE_OPEN = "post_filing_evidence_open"
    INVALIDATED = "invalidated"


class PreflightGateKind(str, Enum):
    """Kinds of mandatory preflight gates requiring human action."""

    UNKNOWN = "unknown"
    GAP = "gap"
    CANDIDATE_DATE = "candidate_date"
    REVIEWER_ACTION = "reviewer_action"
    MANDATORY_PACKAGE_ACCEPTANCE = "mandatory_package_acceptance"
    PRIOR_ART_COVERAGE = "prior_art_coverage"
    QUARANTINE = "quarantine"
    OTHER = "other"


class ResolutionDisposition(str, Enum):
    """How a human resolved one gate item."""

    ACCEPTED = "accepted"
    RESOLVED = "resolved"
    DEFERRED_WITH_ACCEPTANCE = "deferred_with_acceptance"
    CONFIRMED_DATE = "confirmed_date"
    ACKNOWLEDGED_COVERAGE = "acknowledged_coverage"
    REJECTED = "rejected"


class PreflightDisposition(str, Enum):
    """Top-level preflight outcome (fail-closed)."""

    NOT_READY = "not_ready"
    REVIEW_REQUIRED = "review_required"
    READY_FOR_HUMAN_REVIEW = "ready_for_human_review"
    REVIEW_COMPLETE = "review_complete"
    EXPORTABLE = "exportable"
    INVALIDATED = "invalidated"
    BLOCKED = "blocked"


class PostFilingEvidenceKind(str, Enum):
    """Kinds of post-filing evidence that may be imported (never fabricated)."""

    ACKNOWLEDGEMENT = "acknowledgement"
    PAYMENT_RECEIPT = "payment_receipt"


class EvidenceSourceChannel(str, Enum):
    """Provenance channel for post-filing evidence."""

    USER_SUPPLIED_IMPORT = "user_supplied_import"
    # Fabricated / workflow-generated channels are deliberately absent.


class WorkflowReasonCode(str, Enum):
    PREFLIGHT_RUN = "preflight_run"
    OPEN_GATES_REMAIN = "open_gates_remain"
    ALL_GATES_RESOLVED = "all_gates_resolved"
    HUMAN_REVIEW_BOUND = "human_review_bound"
    PACKAGE_EXPORTABLE = "package_exportable"
    EXTERNAL_FILING_ONLY = "external_filing_only"
    INPUTS_CHANGED = "inputs_changed"
    REVIEW_INVALIDATED = "review_invalidated"
    FORBIDDEN_ACTION_BLOCKED = "forbidden_action_blocked"
    POST_FILING_EVIDENCE_IMPORTED = "post_filing_evidence_imported"
    MISSING_GAP_REPORT = "missing_gap_report"
    MISSING_BUNDLE = "missing_bundle"
    MANDATORY_REVIEW_REMAINING = "mandatory_review_remaining"
    UNRESOLVED_UNKNOWN = "unresolved_unknown"
    UNRESOLVED_GAP = "unresolved_gap"
    UNRESOLVED_CANDIDATE_DATE = "unresolved_candidate_date"
    UNRESOLVED_REVIEWER_ACTION = "unresolved_reviewer_action"
    QUARANTINE_BLOCK = "quarantine_block"
    PRIOR_ART_READINESS_BLOCK = "prior_art_readiness_block"
    RECEIPT_NOT_FABRICATED = "receipt_not_fabricated"
    NEVER_MARKED_SUBMITTED = "never_marked_submitted"


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class WorkflowProcessorError(ValueError):
    """Base error for preflight / human-gate failures."""

    def __init__(self, message: str, *, code: str = "workflow_error") -> None:
        super().__init__(message)
        self.code = code

    def audit_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": str(self)[:256]}


class ForbiddenWorkflowActionError(WorkflowProcessorError):
    """Raised when a sign/pay/file/submit/fabricate action is attempted."""

    def __init__(self, action: str, message: str | None = None) -> None:
        action_s = str(action)
        super().__init__(
            message
            or (
                f"workflow forbids action {action_s!r}: filing remains external; "
                "this processor cannot sign, pay, file, mark submitted, or "
                "fabricate receipts"
            ),
            code="forbidden_workflow_action",
        )
        self.action = action_s


class ReviewInvalidatedError(WorkflowProcessorError):
    """Raised when material inputs no longer match a bound review."""

    def __init__(self, message: str) -> None:
        super().__init__(message, code="review_invalidated")


class PreflightNotReadyError(WorkflowProcessorError):
    """Raised when export or binding is attempted before gates are satisfied."""

    def __init__(self, message: str) -> None:
        super().__init__(message, code="preflight_not_ready")


class FabricatedEvidenceError(WorkflowProcessorError):
    """Raised when acknowledgement/payment evidence is invented by the workflow."""

    def __init__(self, message: str) -> None:
        super().__init__(message, code="fabricated_evidence")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def sha256_hex(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def _require_str(value: Any, field: str, *, max_len: int = 4096) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field} must be str, got {type(value).__name__}")
    text = value.strip()
    if not text:
        raise ValueError(f"{field} must be non-empty")
    if len(text) > max_len:
        raise ValueError(f"{field} exceeds max length {max_len}")
    return text


def _optional_str(value: Any, field: str, *, max_len: int = 4096) -> str | None:
    if value is None:
        return None
    return _require_str(value, field, max_len=max_len)


def _identifier(value: Any, field: str) -> str:
    text = _require_str(value, field, max_len=256)
    if not _ID_RE.match(text):
        raise ValueError(f"{field} has invalid identifier shape")
    return text


def _optional_identifier(value: Any, field: str) -> str | None:
    if value is None:
        return None
    return _identifier(value, field)


def _sha256_hex_field(value: Any, field: str) -> str:
    text = _require_str(value, field, max_len=64)
    lowered = text.lower()
    if not _SHA256_RE.match(lowered):
        raise ValueError(f"{field} must be a 64-char lowercase hex sha256")
    return lowered


def _optional_sha256(value: Any, field: str) -> str | None:
    if value is None:
        return None
    return _sha256_hex_field(value, field)


def _iso_utc(value: Any, field: str) -> str:
    text = _require_str(value, field, max_len=64)
    if not _ISO_UTC_RE.match(text):
        raise ValueError(f"{field} must be ISO-8601 UTC timestamp")
    return text


def _optional_iso_utc(value: Any, field: str) -> str | None:
    if value is None:
        return None
    return _iso_utc(value, field)


def _coerce_enum(enum_cls: type[Enum], value: Any, field: str) -> Enum:
    if isinstance(value, enum_cls):
        return value
    if isinstance(value, str):
        try:
            return enum_cls(value)
        except ValueError as exc:
            raise ValueError(f"invalid {field}: {value!r}") from exc
    raise TypeError(f"{field} must be {enum_cls.__name__} or str")


def _coerce_classification(value: Any) -> DisclosureClassification:
    if isinstance(value, DisclosureClassification):
        return value
    if isinstance(value, str):
        try:
            return DisclosureClassification(value)
        except ValueError as exc:
            raise ValueError(f"invalid classification: {value!r}") from exc
    raise TypeError("classification must be DisclosureClassification or str")


def _tuple_of_str(
    value: Any, field: str, *, max_items: int = 256
) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        raise TypeError(f"{field} must be a sequence of str, not str")
    if not isinstance(value, Sequence):
        raise TypeError(f"{field} must be a sequence of str")
    if len(value) > max_items:
        raise ValueError(f"{field} exceeds max items {max_items}")
    out: list[str] = []
    for i, item in enumerate(value):
        if not isinstance(item, str):
            raise TypeError(f"{field}[{i}] must be str")
        text = item.strip()
        if not text:
            raise ValueError(f"{field}[{i}] must be non-empty")
        if len(text) > 512:
            raise ValueError(f"{field}[{i}] exceeds max length 512")
        out.append(text)
    return tuple(out)


def _frozen_str_map(
    value: Any, field: str, *, max_items: int = 64
) -> Mapping[str, str]:
    if value is None:
        return MappingProxyType({})
    if not isinstance(value, Mapping):
        raise TypeError(f"{field} must be a mapping")
    if len(value) > max_items:
        raise ValueError(f"{field} exceeds max items {max_items}")
    out: dict[str, str] = {}
    for k, v in value.items():
        if not isinstance(k, str) or not isinstance(v, str):
            raise TypeError(f"{field} keys and values must be str")
        ks, vs = k.strip(), v.strip()
        if not ks:
            raise ValueError(f"{field} key must be non-empty")
        out[ks] = vs
    return MappingProxyType(out)


def _default_id_factory() -> str:
    return uuid.uuid4().hex[:12]


def assert_action_allowed(action: str) -> None:
    """Fail closed if *action* is a forbidden workflow capability."""
    key = _require_str(action, "action", max_len=128).lower().replace(" ", "_")
    if key in FORBIDDEN_WORKFLOW_ACTIONS:
        raise ForbiddenWorkflowActionError(key)
    # Block common aliases / prefixes even when not in the exact set.
    if key.startswith(
        (
            "sign_",
            "pay_",
            "file_",
            "submit_",
            "mark_submitted",
            "mark_as_submitted",
            "fabricate_",
        )
    ):
        raise ForbiddenWorkflowActionError(key)
    for token in (
        "sign_and_file",
        "pay_and_file",
        "auto_file",
        "auto_submit",
        "fabricate_receipt",
        "fabricate_acknowledgement",
        "fabricate_payment",
    ):
        if token in key:
            raise ForbiddenWorkflowActionError(key)


def is_forbidden_action(action: str) -> bool:
    try:
        assert_action_allowed(action)
    except ForbiddenWorkflowActionError:
        return True
    except (TypeError, ValueError):
        return True
    return False


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PreflightGateItem:
    """One mandatory gate requiring human resolution or acceptance."""

    gate_id: str
    kind: PreflightGateKind
    subject_id: str
    summary: str
    mandatory: bool
    reason_codes: tuple[str, ...] = ()
    source_record_ids: tuple[str, ...] = ()
    labels: Mapping[str, str] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(self, "gate_id", _identifier(self.gate_id, "gate_id"))
        object.__setattr__(
            self, "kind", _coerce_enum(PreflightGateKind, self.kind, "kind")
        )
        object.__setattr__(
            self, "subject_id", _identifier(self.subject_id, "subject_id")
        )
        object.__setattr__(
            self, "summary", _require_str(self.summary, "summary", max_len=1024)
        )
        if not isinstance(self.mandatory, bool):
            raise TypeError("mandatory must be bool")
        object.__setattr__(
            self,
            "reason_codes",
            _tuple_of_str(self.reason_codes, "reason_codes", max_items=32),
        )
        object.__setattr__(
            self,
            "source_record_ids",
            _tuple_of_str(
                self.source_record_ids, "source_record_ids", max_items=64
            ),
        )
        object.__setattr__(
            self, "labels", _frozen_str_map(self.labels, "labels", max_items=16)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "gate_id": self.gate_id,
            "kind": self.kind.value,
            "labels": dict(self.labels),
            "mandatory": self.mandatory,
            "reason_codes": list(self.reason_codes),
            "source_record_ids": list(self.source_record_ids),
            "subject_id": self.subject_id,
            "summary": self.summary,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "PreflightGateItem":
        if not isinstance(value, Mapping):
            raise TypeError("PreflightGateItem must be a mapping")
        return cls(
            gate_id=value.get("gate_id", ""),
            kind=value.get("kind", PreflightGateKind.OTHER.value),
            subject_id=value.get("subject_id", ""),
            summary=value.get("summary", "gate"),
            mandatory=bool(value.get("mandatory", True)),
            reason_codes=tuple(value.get("reason_codes") or ()),
            source_record_ids=tuple(value.get("source_record_ids") or ()),
            labels=value.get("labels") or {},
        )


@dataclass(frozen=True, slots=True)
class ItemResolution:
    """Explicit human resolution/acceptance for one gate."""

    gate_id: str
    disposition: ResolutionDisposition
    reviewer_name: str
    resolved_at_utc: str
    statement: str
    bound_package_digest: str
    notes: str | None = None
    labels: Mapping[str, str] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(self, "gate_id", _identifier(self.gate_id, "gate_id"))
        object.__setattr__(
            self,
            "disposition",
            _coerce_enum(ResolutionDisposition, self.disposition, "disposition"),
        )
        if self.disposition is ResolutionDisposition.REJECTED:
            # Rejected gates remain open; disposition is recorded but does not
            # clear the gate. Consumers should treat REJECTED as non-clearing.
            pass
        object.__setattr__(
            self,
            "reviewer_name",
            _require_str(self.reviewer_name, "reviewer_name", max_len=256),
        )
        object.__setattr__(
            self,
            "resolved_at_utc",
            _iso_utc(self.resolved_at_utc, "resolved_at_utc"),
        )
        object.__setattr__(
            self,
            "statement",
            _require_str(self.statement, "statement", max_len=4096),
        )
        object.__setattr__(
            self,
            "bound_package_digest",
            _sha256_hex_field(self.bound_package_digest, "bound_package_digest"),
        )
        object.__setattr__(
            self, "notes", _optional_str(self.notes, "notes", max_len=2048)
        )
        object.__setattr__(
            self, "labels", _frozen_str_map(self.labels, "labels", max_items=16)
        )

    @property
    def clears_gate(self) -> bool:
        return self.disposition is not ResolutionDisposition.REJECTED

    def to_dict(self) -> dict[str, Any]:
        return {
            "bound_package_digest": self.bound_package_digest,
            "disposition": self.disposition.value,
            "gate_id": self.gate_id,
            "labels": dict(self.labels),
            "notes": self.notes,
            "resolved_at_utc": self.resolved_at_utc,
            "reviewer_name": self.reviewer_name,
            "statement": self.statement,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ItemResolution":
        if not isinstance(value, Mapping):
            raise TypeError("ItemResolution must be a mapping")
        return cls(
            gate_id=value.get("gate_id", ""),
            disposition=value.get(
                "disposition", ResolutionDisposition.ACCEPTED.value
            ),
            reviewer_name=value.get("reviewer_name", ""),
            resolved_at_utc=value.get("resolved_at_utc", ""),
            statement=value.get("statement", ""),
            bound_package_digest=value.get("bound_package_digest", ""),
            notes=value.get("notes"),
            labels=value.get("labels") or {},
        )


@dataclass(frozen=True, slots=True)
class PreflightPackageInput:
    """Compact material inputs for package preflight.

    Prefer supplying digests/ids (and optionally full objects). Full objects
    are used only to project gates and re-verify digests — legal outcomes are
    never recomputed here.
    """

    matter_id: str
    source_bundle_id: str
    source_bundle_digest: str
    gap_report_id: str
    gap_report_digest: str
    analysis_id: str | None = None
    dossier_id: str | None = None
    dossier_digest: str | None = None
    prior_art_checklist_id: str | None = None
    prior_art_checklist_digest: str | None = None
    prior_art_search_complete: bool = False
    prior_art_blocking_reason_codes: tuple[str, ...] = ()
    classification: DisclosureClassification = DisclosureClassification.UNKNOWN
    # Compact gate projections when full gap report object is unavailable.
    open_unknown_ids: tuple[str, ...] = ()
    open_gap_ids: tuple[str, ...] = ()
    open_candidate_date_ids: tuple[str, ...] = ()
    open_reviewer_action_ids: tuple[str, ...] = ()
    mandatory_review_remaining: bool = True
    gap_report_label: str | None = None
    labels: Mapping[str, str] = MappingProxyType({})
    # Optional full objects (not serialized into package digest by identity).
    gap_report: Any = None
    analysis_bundle: Any = None
    dossier: Any = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "matter_id", _identifier(self.matter_id, "matter_id")
        )
        object.__setattr__(
            self,
            "source_bundle_id",
            _identifier(self.source_bundle_id, "source_bundle_id"),
        )
        object.__setattr__(
            self,
            "source_bundle_digest",
            _sha256_hex_field(self.source_bundle_digest, "source_bundle_digest"),
        )
        object.__setattr__(
            self, "gap_report_id", _identifier(self.gap_report_id, "gap_report_id")
        )
        object.__setattr__(
            self,
            "gap_report_digest",
            _sha256_hex_field(self.gap_report_digest, "gap_report_digest"),
        )
        object.__setattr__(
            self, "analysis_id", _optional_identifier(self.analysis_id, "analysis_id")
        )
        object.__setattr__(
            self, "dossier_id", _optional_identifier(self.dossier_id, "dossier_id")
        )
        object.__setattr__(
            self,
            "dossier_digest",
            _optional_sha256(self.dossier_digest, "dossier_digest"),
        )
        object.__setattr__(
            self,
            "prior_art_checklist_id",
            _optional_identifier(
                self.prior_art_checklist_id, "prior_art_checklist_id"
            ),
        )
        object.__setattr__(
            self,
            "prior_art_checklist_digest",
            _optional_sha256(
                self.prior_art_checklist_digest, "prior_art_checklist_digest"
            ),
        )
        if not isinstance(self.prior_art_search_complete, bool):
            raise TypeError("prior_art_search_complete must be bool")
        object.__setattr__(
            self,
            "prior_art_blocking_reason_codes",
            _tuple_of_str(
                self.prior_art_blocking_reason_codes,
                "prior_art_blocking_reason_codes",
                max_items=64,
            ),
        )
        object.__setattr__(
            self, "classification", _coerce_classification(self.classification)
        )
        object.__setattr__(
            self,
            "open_unknown_ids",
            _tuple_of_str(self.open_unknown_ids, "open_unknown_ids", max_items=512),
        )
        object.__setattr__(
            self,
            "open_gap_ids",
            _tuple_of_str(self.open_gap_ids, "open_gap_ids", max_items=512),
        )
        object.__setattr__(
            self,
            "open_candidate_date_ids",
            _tuple_of_str(
                self.open_candidate_date_ids,
                "open_candidate_date_ids",
                max_items=512,
            ),
        )
        object.__setattr__(
            self,
            "open_reviewer_action_ids",
            _tuple_of_str(
                self.open_reviewer_action_ids,
                "open_reviewer_action_ids",
                max_items=512,
            ),
        )
        if not isinstance(self.mandatory_review_remaining, bool):
            raise TypeError("mandatory_review_remaining must be bool")
        object.__setattr__(
            self,
            "gap_report_label",
            _optional_str(self.gap_report_label, "gap_report_label", max_len=64),
        )
        object.__setattr__(
            self, "labels", _frozen_str_map(self.labels, "labels", max_items=32)
        )
        # Verify full objects when provided (digest binding).
        gr = self.gap_report
        if gr is not None and RequirementEvidenceGapReport is not None:
            if isinstance(gr, RequirementEvidenceGapReport):
                if gr.report_id != self.gap_report_id:
                    raise WorkflowProcessorError(
                        "gap_report.report_id must match gap_report_id",
                        code="gap_report_id_mismatch",
                    )
                if gr.content_digest != self.gap_report_digest:
                    raise WorkflowProcessorError(
                        "gap_report.content_digest must match gap_report_digest",
                        code="gap_report_digest_mismatch",
                    )
                if gr.source_bundle_id != self.source_bundle_id:
                    raise WorkflowProcessorError(
                        "gap_report.source_bundle_id must match source_bundle_id",
                        code="bundle_id_mismatch",
                    )
                if gr.source_bundle_digest != self.source_bundle_digest:
                    raise WorkflowProcessorError(
                        "gap_report.source_bundle_digest must match "
                        "source_bundle_digest",
                        code="bundle_digest_mismatch",
                    )
        bundle = self.analysis_bundle
        if bundle is not None and UsptoAnalysisBundle is not None:
            if isinstance(bundle, UsptoAnalysisBundle):
                if bundle.bundle_id != self.source_bundle_id:
                    raise WorkflowProcessorError(
                        "analysis_bundle.bundle_id must match source_bundle_id",
                        code="bundle_id_mismatch",
                    )
                if bundle.bundle_digest != self.source_bundle_digest:
                    raise WorkflowProcessorError(
                        "analysis_bundle.bundle_digest must match "
                        "source_bundle_digest",
                        code="bundle_digest_mismatch",
                    )
        dossier = self.dossier
        if dossier is not None and ApplicationDossier is not None:
            if isinstance(dossier, ApplicationDossier):
                if self.dossier_id and dossier.dossier_id != self.dossier_id:
                    raise WorkflowProcessorError(
                        "dossier.dossier_id must match dossier_id",
                        code="dossier_id_mismatch",
                    )
                if (
                    self.dossier_digest
                    and dossier.content_digest != self.dossier_digest
                ):
                    raise WorkflowProcessorError(
                        "dossier.content_digest must match dossier_digest",
                        code="dossier_digest_mismatch",
                    )

    def material_payload(self) -> dict[str, Any]:
        """Material fields that determine the package digest."""
        return {
            "analysis_id": self.analysis_id,
            "classification": self.classification.value,
            "dossier_digest": self.dossier_digest,
            "dossier_id": self.dossier_id,
            "gap_report_digest": self.gap_report_digest,
            "gap_report_id": self.gap_report_id,
            "gap_report_label": self.gap_report_label,
            "labels": dict(self.labels),
            "mandatory_review_remaining": self.mandatory_review_remaining,
            "matter_id": self.matter_id,
            "open_candidate_date_ids": list(self.open_candidate_date_ids),
            "open_gap_ids": list(self.open_gap_ids),
            "open_reviewer_action_ids": list(self.open_reviewer_action_ids),
            "open_unknown_ids": list(self.open_unknown_ids),
            "prior_art_blocking_reason_codes": list(
                self.prior_art_blocking_reason_codes
            ),
            "prior_art_checklist_digest": self.prior_art_checklist_digest,
            "prior_art_checklist_id": self.prior_art_checklist_id,
            "prior_art_search_complete": self.prior_art_search_complete,
            "schema_version": WORKFLOW_SCHEMA_VERSION,
            "source_bundle_digest": self.source_bundle_digest,
            "source_bundle_id": self.source_bundle_id,
        }

    def package_digest(self) -> str:
        return sha256_hex(canonical_json(self.material_payload()))

    def to_dict(self) -> dict[str, Any]:
        payload = self.material_payload()
        payload["package_digest"] = self.package_digest()
        return payload

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "PreflightPackageInput":
        if not isinstance(value, Mapping):
            raise TypeError("PreflightPackageInput must be a mapping")
        return cls(
            matter_id=value.get("matter_id", ""),
            source_bundle_id=value.get("source_bundle_id", ""),
            source_bundle_digest=value.get("source_bundle_digest", ""),
            gap_report_id=value.get("gap_report_id", ""),
            gap_report_digest=value.get("gap_report_digest", ""),
            analysis_id=value.get("analysis_id"),
            dossier_id=value.get("dossier_id"),
            dossier_digest=value.get("dossier_digest"),
            prior_art_checklist_id=value.get("prior_art_checklist_id"),
            prior_art_checklist_digest=value.get("prior_art_checklist_digest"),
            prior_art_search_complete=bool(
                value.get("prior_art_search_complete", False)
            ),
            prior_art_blocking_reason_codes=tuple(
                value.get("prior_art_blocking_reason_codes") or ()
            ),
            classification=value.get(
                "classification", DisclosureClassification.UNKNOWN.value
            ),
            open_unknown_ids=tuple(value.get("open_unknown_ids") or ()),
            open_gap_ids=tuple(value.get("open_gap_ids") or ()),
            open_candidate_date_ids=tuple(
                value.get("open_candidate_date_ids") or ()
            ),
            open_reviewer_action_ids=tuple(
                value.get("open_reviewer_action_ids") or ()
            ),
            mandatory_review_remaining=bool(
                value.get("mandatory_review_remaining", True)
            ),
            gap_report_label=value.get("gap_report_label"),
            labels=value.get("labels") or {},
        )

    @classmethod
    def from_gap_report(
        cls,
        report: Any,
        *,
        dossier: Any = None,
        analysis_bundle: Any = None,
        prior_art_checklist_id: str | None = None,
        prior_art_checklist_digest: str | None = None,
        prior_art_search_complete: bool = False,
        prior_art_blocking_reason_codes: Sequence[str] = (),
        labels: Mapping[str, str] | None = None,
    ) -> "PreflightPackageInput":
        """Project a :class:`RequirementEvidenceGapReport` into package input."""
        if RequirementEvidenceGapReport is None or not isinstance(
            report, RequirementEvidenceGapReport
        ):
            raise TypeError(
                "report must be RequirementEvidenceGapReport "
                f"(got {type(report).__name__})"
            )
        open_unknowns = tuple(u.statement_id for u in report.unknowns)
        open_gaps: list[str] = []
        for row in report.requirement_rows:
            status = row.status
            status_val = status.value if hasattr(status, "value") else str(status)
            if status_val in ("gap", "unsatisfied", "missing", "unknown"):
                open_gaps.append(row.requirement_id)
        open_dates: list[str] = []
        for cand in report.candidate_dates:
            if getattr(cand, "is_review_only", False) or getattr(
                cand, "is_unknown", False
            ):
                open_dates.append(cand.candidate_id)
            elif GapStatus is not None:
                st = cand.status
                if st in (
                    GapStatus.UNKNOWN,
                    GapStatus.GAP,
                    GapStatus.UNSATISFIED,
                    GapStatus.MISSING,
                ):
                    open_dates.append(cand.candidate_id)
        open_actions = tuple(a.action_id for a in report.reviewer_actions)
        dossier_id = None
        dossier_digest = None
        if dossier is not None:
            dossier_id = getattr(dossier, "dossier_id", None)
            dossier_digest = getattr(dossier, "content_digest", None) or getattr(
                dossier, "bundle_digest", None
            )
        label = report.label
        label_val = label.value if hasattr(label, "value") else str(label)
        return cls(
            matter_id=report.matter_id or report.matter_summary.matter_id or "matter:unknown",
            source_bundle_id=report.source_bundle_id,
            source_bundle_digest=report.source_bundle_digest,
            gap_report_id=report.report_id,
            gap_report_digest=report.content_digest,
            analysis_id=report.analysis_id,
            dossier_id=dossier_id,
            dossier_digest=dossier_digest,
            prior_art_checklist_id=prior_art_checklist_id,
            prior_art_checklist_digest=prior_art_checklist_digest,
            prior_art_search_complete=prior_art_search_complete,
            prior_art_blocking_reason_codes=tuple(prior_art_blocking_reason_codes),
            classification=report.classification,
            open_unknown_ids=open_unknowns,
            open_gap_ids=tuple(dict.fromkeys(open_gaps)),
            open_candidate_date_ids=tuple(dict.fromkeys(open_dates)),
            open_reviewer_action_ids=open_actions,
            mandatory_review_remaining=bool(report.mandatory_review_remaining),
            gap_report_label=label_val,
            labels=labels or {},
            gap_report=report,
            analysis_bundle=analysis_bundle,
            dossier=dossier,
        )


@dataclass(frozen=True, slots=True)
class PreflightResult:
    """Immutable result of package preflight."""

    schema_version: str
    preflight_id: str
    matter_id: str
    phase: PreflightPhase
    disposition: PreflightDisposition
    package_digest: str
    source_bundle_id: str
    source_bundle_digest: str
    gap_report_id: str
    gap_report_digest: str
    gate_items: tuple[PreflightGateItem, ...]
    open_gate_ids: tuple[str, ...]
    resolved_gate_ids: tuple[str, ...]
    reason_codes: tuple[str, ...]
    warnings: tuple[str, ...]
    classification: DisclosureClassification
    review_state: ReviewState
    output_kind: str = OUTPUT_KIND_PREFLIGHT_RESULT
    disclaimer: str = WORKFLOW_DISCLAIMER
    ruleset_version: str = WORKFLOW_RULESET_VERSION
    content_digest: str = ""
    analysis_id: str | None = None
    dossier_id: str | None = None
    dossier_digest: str | None = None
    prior_art_checklist_id: str | None = None
    prior_art_checklist_digest: str | None = None
    prior_art_search_complete: bool = False
    is_submitted: bool = False  # always False; enforced in __post_init__
    filing_is_external: bool = True
    can_sign: bool = False
    can_pay: bool = False
    can_file: bool = False
    labels: Mapping[str, str] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _require_str(self.schema_version, "schema_version", max_len=64),
        )
        if self.schema_version != WORKFLOW_SCHEMA_VERSION:
            raise WorkflowProcessorError(
                f"schema_version must be {WORKFLOW_SCHEMA_VERSION}",
                code="schema_version_mismatch",
            )
        object.__setattr__(
            self, "preflight_id", _identifier(self.preflight_id, "preflight_id")
        )
        object.__setattr__(
            self, "matter_id", _identifier(self.matter_id, "matter_id")
        )
        object.__setattr__(
            self, "phase", _coerce_enum(PreflightPhase, self.phase, "phase")
        )
        object.__setattr__(
            self,
            "disposition",
            _coerce_enum(PreflightDisposition, self.disposition, "disposition"),
        )
        # Never allow a submitted phase (defense in depth).
        if self.phase.value == "submitted" or getattr(self.phase, "name", "") == "SUBMITTED":
            raise ForbiddenWorkflowActionError(
                "mark_submitted",
                "preflight phase cannot be submitted; filing remains external",
            )
        object.__setattr__(
            self,
            "package_digest",
            _sha256_hex_field(self.package_digest, "package_digest"),
        )
        object.__setattr__(
            self,
            "source_bundle_id",
            _identifier(self.source_bundle_id, "source_bundle_id"),
        )
        object.__setattr__(
            self,
            "source_bundle_digest",
            _sha256_hex_field(self.source_bundle_digest, "source_bundle_digest"),
        )
        object.__setattr__(
            self, "gap_report_id", _identifier(self.gap_report_id, "gap_report_id")
        )
        object.__setattr__(
            self,
            "gap_report_digest",
            _sha256_hex_field(self.gap_report_digest, "gap_report_digest"),
        )
        gates = self.gate_items
        if not isinstance(gates, tuple):
            gates = tuple(gates)
            object.__setattr__(self, "gate_items", gates)
        if len(gates) > DEFAULT_MAX_GATES:
            raise WorkflowProcessorError(
                f"gate_items exceeds max {DEFAULT_MAX_GATES}",
                code="too_many_gates",
            )
        for g in gates:
            if not isinstance(g, PreflightGateItem):
                raise TypeError("gate_items must be PreflightGateItem instances")
        object.__setattr__(
            self,
            "open_gate_ids",
            _tuple_of_str(self.open_gate_ids, "open_gate_ids", max_items=DEFAULT_MAX_GATES),
        )
        object.__setattr__(
            self,
            "resolved_gate_ids",
            _tuple_of_str(
                self.resolved_gate_ids, "resolved_gate_ids", max_items=DEFAULT_MAX_GATES
            ),
        )
        object.__setattr__(
            self,
            "reason_codes",
            _tuple_of_str(
                self.reason_codes, "reason_codes", max_items=DEFAULT_MAX_REASON_CODES
            ),
        )
        object.__setattr__(
            self,
            "warnings",
            _tuple_of_str(self.warnings, "warnings", max_items=DEFAULT_MAX_WARNINGS),
        )
        object.__setattr__(
            self, "classification", _coerce_classification(self.classification)
        )
        object.__setattr__(
            self,
            "review_state",
            _coerce_enum(ReviewState, self.review_state, "review_state"),
        )
        object.__setattr__(
            self,
            "output_kind",
            _require_str(self.output_kind, "output_kind", max_len=128),
        )
        if self.output_kind != OUTPUT_KIND_PREFLIGHT_RESULT:
            raise WorkflowProcessorError(
                f"output_kind must be {OUTPUT_KIND_PREFLIGHT_RESULT!r}",
                code="invalid_output_kind",
            )
        object.__setattr__(
            self,
            "disclaimer",
            _require_str(self.disclaimer, "disclaimer", max_len=4096),
        )
        lower = self.disclaimer.lower()
        if "never signs" not in lower and "cannot sign" not in lower:
            # Require explicit non-filing language.
            if "sign" not in lower or "external" not in lower:
                raise WorkflowProcessorError(
                    "disclaimer must state that the workflow does not sign/"
                    "file and filing remains external",
                    code="disclaimer_incomplete",
                )
        object.__setattr__(
            self,
            "ruleset_version",
            _require_str(self.ruleset_version, "ruleset_version", max_len=128),
        )
        # Hard capability flags — never elevatable.
        object.__setattr__(self, "is_submitted", False)
        object.__setattr__(self, "filing_is_external", True)
        object.__setattr__(self, "can_sign", False)
        object.__setattr__(self, "can_pay", False)
        object.__setattr__(self, "can_file", False)
        if not isinstance(self.prior_art_search_complete, bool):
            raise TypeError("prior_art_search_complete must be bool")
        object.__setattr__(
            self, "analysis_id", _optional_identifier(self.analysis_id, "analysis_id")
        )
        object.__setattr__(
            self, "dossier_id", _optional_identifier(self.dossier_id, "dossier_id")
        )
        object.__setattr__(
            self,
            "dossier_digest",
            _optional_sha256(self.dossier_digest, "dossier_digest"),
        )
        object.__setattr__(
            self,
            "prior_art_checklist_id",
            _optional_identifier(
                self.prior_art_checklist_id, "prior_art_checklist_id"
            ),
        )
        object.__setattr__(
            self,
            "prior_art_checklist_digest",
            _optional_sha256(
                self.prior_art_checklist_digest, "prior_art_checklist_digest"
            ),
        )
        object.__setattr__(
            self, "labels", _frozen_str_map(self.labels, "labels", max_items=32)
        )
        # Content digest (identity-stable material payload).
        material = self.material_payload()
        digest = sha256_hex(canonical_json(material))
        if self.content_digest:
            existing = _sha256_hex_field(self.content_digest, "content_digest")
            if existing != digest:
                # Allow pre-set only when it matches (round-trip).
                raise WorkflowProcessorError(
                    "content_digest does not match material payload",
                    code="content_digest_mismatch",
                )
            object.__setattr__(self, "content_digest", existing)
        else:
            object.__setattr__(self, "content_digest", digest)

        # Quarantine forces review.
        if requires_quarantine(self.classification) and self.review_state not in (
            ReviewState.REQUIRED,
            ReviewState.PENDING,
        ):
            object.__setattr__(self, "review_state", ReviewState.REQUIRED)

    def material_payload(self) -> dict[str, Any]:
        return {
            "analysis_id": self.analysis_id,
            "can_file": False,
            "can_pay": False,
            "can_sign": False,
            "classification": self.classification.value,
            "disclaimer": self.disclaimer,
            "disposition": self.disposition.value,
            "dossier_digest": self.dossier_digest,
            "dossier_id": self.dossier_id,
            "filing_is_external": True,
            "gap_report_digest": self.gap_report_digest,
            "gap_report_id": self.gap_report_id,
            "gate_items": [g.to_dict() for g in self.gate_items],
            "is_submitted": False,
            "labels": dict(self.labels),
            "matter_id": self.matter_id,
            "open_gate_ids": list(self.open_gate_ids),
            "output_kind": self.output_kind,
            "package_digest": self.package_digest,
            "phase": self.phase.value,
            "prior_art_checklist_digest": self.prior_art_checklist_digest,
            "prior_art_checklist_id": self.prior_art_checklist_id,
            "prior_art_search_complete": self.prior_art_search_complete,
            "reason_codes": list(self.reason_codes),
            "resolved_gate_ids": list(self.resolved_gate_ids),
            "review_state": self.review_state.value,
            "ruleset_version": self.ruleset_version,
            "schema_version": self.schema_version,
            "source_bundle_digest": self.source_bundle_digest,
            "source_bundle_id": self.source_bundle_id,
            "warnings": list(self.warnings),
        }

    @property
    def all_mandatory_gates_resolved(self) -> bool:
        mandatory_ids = {g.gate_id for g in self.gate_items if g.mandatory}
        resolved = set(self.resolved_gate_ids)
        return mandatory_ids.issubset(resolved) and not (
            set(self.open_gate_ids) & mandatory_ids
        )

    @property
    def is_exportable(self) -> bool:
        return (
            self.disposition is PreflightDisposition.EXPORTABLE
            and self.phase
            in (
                PreflightPhase.PACKAGE_EXPORTABLE,
                PreflightPhase.EXTERNAL_FILING_HANDOFF,
            )
            and self.all_mandatory_gates_resolved
            and not self.is_submitted
        )

    def to_dict(self) -> dict[str, Any]:
        payload = self.material_payload()
        payload["content_digest"] = self.content_digest
        payload["preflight_id"] = self.preflight_id
        return payload

    def public_projection(self) -> dict[str, Any]:
        return {
            "can_file": False,
            "can_pay": False,
            "can_sign": False,
            "classification": self.classification.value,
            "content_digest": self.content_digest,
            "disposition": self.disposition.value,
            "filing_is_external": True,
            "gate_count": len(self.gate_items),
            "is_submitted": False,
            "matter_id": self.matter_id,
            "open_gate_count": len(self.open_gate_ids),
            "output_kind": self.output_kind,
            "package_digest": self.package_digest,
            "phase": self.phase.value,
            "preflight_id": self.preflight_id,
            "resolved_gate_count": len(self.resolved_gate_ids),
            "review_state": self.review_state.value,
            "schema_version": self.schema_version,
            "source_bundle_digest": self.source_bundle_digest,
            "source_bundle_id": self.source_bundle_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "PreflightResult":
        if not isinstance(value, Mapping):
            raise TypeError("PreflightResult must be a mapping")
        return cls(
            schema_version=value.get("schema_version", WORKFLOW_SCHEMA_VERSION),
            preflight_id=value.get("preflight_id", ""),
            matter_id=value.get("matter_id", ""),
            phase=value.get("phase", PreflightPhase.PREFLIGHT_OPEN.value),
            disposition=value.get(
                "disposition", PreflightDisposition.REVIEW_REQUIRED.value
            ),
            package_digest=value.get("package_digest", ""),
            source_bundle_id=value.get("source_bundle_id", ""),
            source_bundle_digest=value.get("source_bundle_digest", ""),
            gap_report_id=value.get("gap_report_id", ""),
            gap_report_digest=value.get("gap_report_digest", ""),
            gate_items=tuple(
                PreflightGateItem.from_dict(g)
                for g in (value.get("gate_items") or ())
            ),
            open_gate_ids=tuple(value.get("open_gate_ids") or ()),
            resolved_gate_ids=tuple(value.get("resolved_gate_ids") or ()),
            reason_codes=tuple(value.get("reason_codes") or ()),
            warnings=tuple(value.get("warnings") or ()),
            classification=value.get(
                "classification", DisclosureClassification.UNKNOWN.value
            ),
            review_state=value.get("review_state", ReviewState.REQUIRED.value),
            output_kind=value.get("output_kind", OUTPUT_KIND_PREFLIGHT_RESULT),
            disclaimer=value.get("disclaimer", WORKFLOW_DISCLAIMER),
            ruleset_version=value.get("ruleset_version", WORKFLOW_RULESET_VERSION),
            content_digest=value.get("content_digest", ""),
            analysis_id=value.get("analysis_id"),
            dossier_id=value.get("dossier_id"),
            dossier_digest=value.get("dossier_digest"),
            prior_art_checklist_id=value.get("prior_art_checklist_id"),
            prior_art_checklist_digest=value.get("prior_art_checklist_digest"),
            prior_art_search_complete=bool(
                value.get("prior_art_search_complete", False)
            ),
            is_submitted=False,
            filing_is_external=True,
            can_sign=False,
            can_pay=False,
            can_file=False,
            labels=value.get("labels") or {},
        )


@dataclass(frozen=True, slots=True)
class HumanReviewReceipt:
    """Named human review bound to an immutable package digest.

    Changing material inputs (new package digest) invalidates this receipt.
    """

    schema_version: str
    receipt_id: str
    preflight_id: str
    matter_id: str
    reviewer_name: str
    reviewed_at_utc: str
    package_digest: str
    source_bundle_digest: str
    gap_report_digest: str
    resolutions: tuple[ItemResolution, ...]
    statement: str
    output_kind: str = OUTPUT_KIND_HUMAN_REVIEW_RECEIPT
    disclaimer: str = WORKFLOW_DISCLAIMER
    content_digest: str = ""
    review_state: ReviewState = ReviewState.COMPLETE
    labels: Mapping[str, str] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _require_str(self.schema_version, "schema_version", max_len=64),
        )
        if self.schema_version != WORKFLOW_SCHEMA_VERSION:
            raise WorkflowProcessorError(
                f"schema_version must be {WORKFLOW_SCHEMA_VERSION}",
                code="schema_version_mismatch",
            )
        object.__setattr__(
            self, "receipt_id", _identifier(self.receipt_id, "receipt_id")
        )
        object.__setattr__(
            self, "preflight_id", _identifier(self.preflight_id, "preflight_id")
        )
        object.__setattr__(
            self, "matter_id", _identifier(self.matter_id, "matter_id")
        )
        object.__setattr__(
            self,
            "reviewer_name",
            _require_str(self.reviewer_name, "reviewer_name", max_len=256),
        )
        object.__setattr__(
            self,
            "reviewed_at_utc",
            _iso_utc(self.reviewed_at_utc, "reviewed_at_utc"),
        )
        object.__setattr__(
            self,
            "package_digest",
            _sha256_hex_field(self.package_digest, "package_digest"),
        )
        object.__setattr__(
            self,
            "source_bundle_digest",
            _sha256_hex_field(self.source_bundle_digest, "source_bundle_digest"),
        )
        object.__setattr__(
            self,
            "gap_report_digest",
            _sha256_hex_field(self.gap_report_digest, "gap_report_digest"),
        )
        resolutions = self.resolutions
        if not isinstance(resolutions, tuple):
            resolutions = tuple(resolutions)
            object.__setattr__(self, "resolutions", resolutions)
        if len(resolutions) > DEFAULT_MAX_RESOLUTIONS:
            raise WorkflowProcessorError(
                f"resolutions exceeds max {DEFAULT_MAX_RESOLUTIONS}",
                code="too_many_resolutions",
            )
        for r in resolutions:
            if not isinstance(r, ItemResolution):
                raise TypeError("resolutions must be ItemResolution instances")
            if r.bound_package_digest != self.package_digest:
                raise ReviewInvalidatedError(
                    f"resolution for gate {r.gate_id} is bound to a different "
                    "package digest than this review receipt"
                )
            if r.reviewer_name != self.reviewer_name:
                raise WorkflowProcessorError(
                    "all resolutions on a receipt must share reviewer_name",
                    code="reviewer_name_mismatch",
                )
        object.__setattr__(
            self,
            "statement",
            _require_str(self.statement, "statement", max_len=8192),
        )
        object.__setattr__(
            self,
            "output_kind",
            _require_str(self.output_kind, "output_kind", max_len=128),
        )
        if self.output_kind != OUTPUT_KIND_HUMAN_REVIEW_RECEIPT:
            raise WorkflowProcessorError(
                f"output_kind must be {OUTPUT_KIND_HUMAN_REVIEW_RECEIPT!r}",
                code="invalid_output_kind",
            )
        object.__setattr__(
            self,
            "disclaimer",
            _require_str(self.disclaimer, "disclaimer", max_len=4096),
        )
        object.__setattr__(
            self,
            "review_state",
            _coerce_enum(ReviewState, self.review_state, "review_state"),
        )
        object.__setattr__(
            self, "labels", _frozen_str_map(self.labels, "labels", max_items=16)
        )
        material = self.material_payload()
        digest = sha256_hex(canonical_json(material))
        if self.content_digest:
            existing = _sha256_hex_field(self.content_digest, "content_digest")
            if existing != digest:
                raise WorkflowProcessorError(
                    "content_digest does not match material payload",
                    code="content_digest_mismatch",
                )
            object.__setattr__(self, "content_digest", existing)
        else:
            object.__setattr__(self, "content_digest", digest)

    def material_payload(self) -> dict[str, Any]:
        return {
            "disclaimer": self.disclaimer,
            "gap_report_digest": self.gap_report_digest,
            "labels": dict(self.labels),
            "matter_id": self.matter_id,
            "output_kind": self.output_kind,
            "package_digest": self.package_digest,
            "preflight_id": self.preflight_id,
            "resolutions": [r.to_dict() for r in self.resolutions],
            "review_state": self.review_state.value,
            "reviewed_at_utc": self.reviewed_at_utc,
            "reviewer_name": self.reviewer_name,
            "schema_version": self.schema_version,
            "source_bundle_digest": self.source_bundle_digest,
            "statement": self.statement,
        }

    def binds_package_digest(self, package_digest: str) -> bool:
        return self.package_digest == _sha256_hex_field(
            package_digest, "package_digest"
        )

    def to_dict(self) -> dict[str, Any]:
        payload = self.material_payload()
        payload["content_digest"] = self.content_digest
        payload["receipt_id"] = self.receipt_id
        return payload

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "HumanReviewReceipt":
        if not isinstance(value, Mapping):
            raise TypeError("HumanReviewReceipt must be a mapping")
        return cls(
            schema_version=value.get("schema_version", WORKFLOW_SCHEMA_VERSION),
            receipt_id=value.get("receipt_id", ""),
            preflight_id=value.get("preflight_id", ""),
            matter_id=value.get("matter_id", ""),
            reviewer_name=value.get("reviewer_name", ""),
            reviewed_at_utc=value.get("reviewed_at_utc", ""),
            package_digest=value.get("package_digest", ""),
            source_bundle_digest=value.get("source_bundle_digest", ""),
            gap_report_digest=value.get("gap_report_digest", ""),
            resolutions=tuple(
                ItemResolution.from_dict(r)
                for r in (value.get("resolutions") or ())
            ),
            statement=value.get("statement", ""),
            output_kind=value.get("output_kind", OUTPUT_KIND_HUMAN_REVIEW_RECEIPT),
            disclaimer=value.get("disclaimer", WORKFLOW_DISCLAIMER),
            content_digest=value.get("content_digest", ""),
            review_state=value.get("review_state", ReviewState.COMPLETE.value),
            labels=value.get("labels") or {},
        )


@dataclass(frozen=True, slots=True)
class ReviewedPackageManifest:
    """Exportable reviewed package for **external** filing handoff only.

    This is never a filing authorization and never marks the matter submitted.
    """

    schema_version: str
    manifest_id: str
    matter_id: str
    preflight_id: str
    review_receipt_id: str
    review_receipt_digest: str
    package_digest: str
    source_bundle_id: str
    source_bundle_digest: str
    gap_report_id: str
    gap_report_digest: str
    exported_at_utc: str
    exported_by: str
    phase: PreflightPhase = PreflightPhase.EXTERNAL_FILING_HANDOFF
    output_kind: str = OUTPUT_KIND_REVIEWED_PACKAGE_MANIFEST
    disclaimer: str = WORKFLOW_DISCLAIMER
    content_digest: str = ""
    is_submitted: bool = False
    filing_is_external: bool = True
    filing_authorization: bool = False
    can_sign: bool = False
    can_pay: bool = False
    can_file: bool = False
    labels: Mapping[str, str] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _require_str(self.schema_version, "schema_version", max_len=64),
        )
        if self.schema_version != WORKFLOW_SCHEMA_VERSION:
            raise WorkflowProcessorError(
                f"schema_version must be {WORKFLOW_SCHEMA_VERSION}",
                code="schema_version_mismatch",
            )
        object.__setattr__(
            self, "manifest_id", _identifier(self.manifest_id, "manifest_id")
        )
        object.__setattr__(
            self, "matter_id", _identifier(self.matter_id, "matter_id")
        )
        object.__setattr__(
            self, "preflight_id", _identifier(self.preflight_id, "preflight_id")
        )
        object.__setattr__(
            self,
            "review_receipt_id",
            _identifier(self.review_receipt_id, "review_receipt_id"),
        )
        object.__setattr__(
            self,
            "review_receipt_digest",
            _sha256_hex_field(self.review_receipt_digest, "review_receipt_digest"),
        )
        object.__setattr__(
            self,
            "package_digest",
            _sha256_hex_field(self.package_digest, "package_digest"),
        )
        object.__setattr__(
            self,
            "source_bundle_id",
            _identifier(self.source_bundle_id, "source_bundle_id"),
        )
        object.__setattr__(
            self,
            "source_bundle_digest",
            _sha256_hex_field(self.source_bundle_digest, "source_bundle_digest"),
        )
        object.__setattr__(
            self, "gap_report_id", _identifier(self.gap_report_id, "gap_report_id")
        )
        object.__setattr__(
            self,
            "gap_report_digest",
            _sha256_hex_field(self.gap_report_digest, "gap_report_digest"),
        )
        object.__setattr__(
            self, "exported_at_utc", _iso_utc(self.exported_at_utc, "exported_at_utc")
        )
        object.__setattr__(
            self,
            "exported_by",
            _require_str(self.exported_by, "exported_by", max_len=256),
        )
        object.__setattr__(
            self, "phase", _coerce_enum(PreflightPhase, self.phase, "phase")
        )
        if self.phase not in (
            PreflightPhase.EXTERNAL_FILING_HANDOFF,
            PreflightPhase.PACKAGE_EXPORTABLE,
            PreflightPhase.POST_FILING_EVIDENCE_OPEN,
        ):
            raise WorkflowProcessorError(
                "reviewed package phase must be an external handoff phase",
                code="invalid_export_phase",
            )
        # Capability locks — never elevatable.
        object.__setattr__(self, "is_submitted", False)
        object.__setattr__(self, "filing_is_external", True)
        object.__setattr__(self, "filing_authorization", False)
        object.__setattr__(self, "can_sign", False)
        object.__setattr__(self, "can_pay", False)
        object.__setattr__(self, "can_file", False)
        object.__setattr__(
            self,
            "output_kind",
            _require_str(self.output_kind, "output_kind", max_len=128),
        )
        if self.output_kind != OUTPUT_KIND_REVIEWED_PACKAGE_MANIFEST:
            raise WorkflowProcessorError(
                f"output_kind must be {OUTPUT_KIND_REVIEWED_PACKAGE_MANIFEST!r}",
                code="invalid_output_kind",
            )
        object.__setattr__(
            self,
            "disclaimer",
            _require_str(self.disclaimer, "disclaimer", max_len=4096),
        )
        object.__setattr__(
            self, "labels", _frozen_str_map(self.labels, "labels", max_items=16)
        )
        material = self.material_payload()
        digest = sha256_hex(canonical_json(material))
        if self.content_digest:
            existing = _sha256_hex_field(self.content_digest, "content_digest")
            if existing != digest:
                raise WorkflowProcessorError(
                    "content_digest does not match material payload",
                    code="content_digest_mismatch",
                )
            object.__setattr__(self, "content_digest", existing)
        else:
            object.__setattr__(self, "content_digest", digest)

    def material_payload(self) -> dict[str, Any]:
        return {
            "can_file": False,
            "can_pay": False,
            "can_sign": False,
            "disclaimer": self.disclaimer,
            "exported_at_utc": self.exported_at_utc,
            "exported_by": self.exported_by,
            "filing_authorization": False,
            "filing_is_external": True,
            "gap_report_digest": self.gap_report_digest,
            "gap_report_id": self.gap_report_id,
            "is_submitted": False,
            "labels": dict(self.labels),
            "matter_id": self.matter_id,
            "output_kind": self.output_kind,
            "package_digest": self.package_digest,
            "phase": self.phase.value,
            "preflight_id": self.preflight_id,
            "review_receipt_digest": self.review_receipt_digest,
            "review_receipt_id": self.review_receipt_id,
            "schema_version": self.schema_version,
            "source_bundle_digest": self.source_bundle_digest,
            "source_bundle_id": self.source_bundle_id,
        }

    def to_dict(self) -> dict[str, Any]:
        payload = self.material_payload()
        payload["content_digest"] = self.content_digest
        payload["manifest_id"] = self.manifest_id
        return payload

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ReviewedPackageManifest":
        if not isinstance(value, Mapping):
            raise TypeError("ReviewedPackageManifest must be a mapping")
        return cls(
            schema_version=value.get("schema_version", WORKFLOW_SCHEMA_VERSION),
            manifest_id=value.get("manifest_id", ""),
            matter_id=value.get("matter_id", ""),
            preflight_id=value.get("preflight_id", ""),
            review_receipt_id=value.get("review_receipt_id", ""),
            review_receipt_digest=value.get("review_receipt_digest", ""),
            package_digest=value.get("package_digest", ""),
            source_bundle_id=value.get("source_bundle_id", ""),
            source_bundle_digest=value.get("source_bundle_digest", ""),
            gap_report_id=value.get("gap_report_id", ""),
            gap_report_digest=value.get("gap_report_digest", ""),
            exported_at_utc=value.get("exported_at_utc", ""),
            exported_by=value.get("exported_by", ""),
            phase=value.get(
                "phase", PreflightPhase.EXTERNAL_FILING_HANDOFF.value
            ),
            output_kind=value.get(
                "output_kind", OUTPUT_KIND_REVIEWED_PACKAGE_MANIFEST
            ),
            disclaimer=value.get("disclaimer", WORKFLOW_DISCLAIMER),
            content_digest=value.get("content_digest", ""),
            is_submitted=False,
            filing_is_external=True,
            filing_authorization=False,
            can_sign=False,
            can_pay=False,
            can_file=False,
            labels=value.get("labels") or {},
        )


@dataclass(frozen=True, slots=True)
class ImportedPostFilingEvidence:
    """User-supplied acknowledgement or payment receipt imported as new evidence.

    Never fabricated by the workflow. Source channel must be user-supplied
    import. Does not mark the package submitted by itself — filing status
    remains external until an operator records external confirmation out of
    band; this record is evidence only.
    """

    schema_version: str
    evidence_id: str
    matter_id: str
    kind: PostFilingEvidenceKind
    artifact_id: str
    artifact_sha256: str
    source_channel: EvidenceSourceChannel
    imported_at_utc: str
    imported_by: str
    package_digest: str | None = None
    reviewed_manifest_id: str | None = None
    source_receipt_id: str | None = None
    output_kind: str = OUTPUT_KIND_POST_FILING_EVIDENCE
    disclaimer: str = WORKFLOW_DISCLAIMER
    content_digest: str = ""
    fabricated: bool = False  # always False
    labels: Mapping[str, str] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _require_str(self.schema_version, "schema_version", max_len=64),
        )
        if self.schema_version != WORKFLOW_SCHEMA_VERSION:
            raise WorkflowProcessorError(
                f"schema_version must be {WORKFLOW_SCHEMA_VERSION}",
                code="schema_version_mismatch",
            )
        object.__setattr__(
            self, "evidence_id", _identifier(self.evidence_id, "evidence_id")
        )
        object.__setattr__(
            self, "matter_id", _identifier(self.matter_id, "matter_id")
        )
        object.__setattr__(
            self, "kind", _coerce_enum(PostFilingEvidenceKind, self.kind, "kind")
        )
        object.__setattr__(
            self, "artifact_id", _identifier(self.artifact_id, "artifact_id")
        )
        object.__setattr__(
            self,
            "artifact_sha256",
            _sha256_hex_field(self.artifact_sha256, "artifact_sha256"),
        )
        object.__setattr__(
            self,
            "source_channel",
            _coerce_enum(
                EvidenceSourceChannel, self.source_channel, "source_channel"
            ),
        )
        if self.source_channel is not EvidenceSourceChannel.USER_SUPPLIED_IMPORT:
            raise FabricatedEvidenceError(
                "post-filing evidence source_channel must be user_supplied_import; "
                "workflow cannot fabricate acknowledgement or payment receipts"
            )
        if self.fabricated:
            raise FabricatedEvidenceError(
                "fabricated=True is forbidden; receipts must be user-supplied"
            )
        object.__setattr__(self, "fabricated", False)
        object.__setattr__(
            self, "imported_at_utc", _iso_utc(self.imported_at_utc, "imported_at_utc")
        )
        object.__setattr__(
            self,
            "imported_by",
            _require_str(self.imported_by, "imported_by", max_len=256),
        )
        object.__setattr__(
            self,
            "package_digest",
            _optional_sha256(self.package_digest, "package_digest"),
        )
        object.__setattr__(
            self,
            "reviewed_manifest_id",
            _optional_identifier(
                self.reviewed_manifest_id, "reviewed_manifest_id"
            ),
        )
        object.__setattr__(
            self,
            "source_receipt_id",
            _optional_identifier(self.source_receipt_id, "source_receipt_id"),
        )
        object.__setattr__(
            self,
            "output_kind",
            _require_str(self.output_kind, "output_kind", max_len=128),
        )
        if self.output_kind != OUTPUT_KIND_POST_FILING_EVIDENCE:
            raise WorkflowProcessorError(
                f"output_kind must be {OUTPUT_KIND_POST_FILING_EVIDENCE!r}",
                code="invalid_output_kind",
            )
        object.__setattr__(
            self,
            "disclaimer",
            _require_str(self.disclaimer, "disclaimer", max_len=4096),
        )
        object.__setattr__(
            self, "labels", _frozen_str_map(self.labels, "labels", max_items=16)
        )
        material = self.material_payload()
        digest = sha256_hex(canonical_json(material))
        if self.content_digest:
            existing = _sha256_hex_field(self.content_digest, "content_digest")
            if existing != digest:
                raise WorkflowProcessorError(
                    "content_digest does not match material payload",
                    code="content_digest_mismatch",
                )
            object.__setattr__(self, "content_digest", existing)
        else:
            object.__setattr__(self, "content_digest", digest)

    def material_payload(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "artifact_sha256": self.artifact_sha256,
            "disclaimer": self.disclaimer,
            "fabricated": False,
            "imported_at_utc": self.imported_at_utc,
            "imported_by": self.imported_by,
            "kind": self.kind.value,
            "labels": dict(self.labels),
            "matter_id": self.matter_id,
            "output_kind": self.output_kind,
            "package_digest": self.package_digest,
            "reviewed_manifest_id": self.reviewed_manifest_id,
            "schema_version": self.schema_version,
            "source_channel": self.source_channel.value,
            "source_receipt_id": self.source_receipt_id,
        }

    def to_dict(self) -> dict[str, Any]:
        payload = self.material_payload()
        payload["content_digest"] = self.content_digest
        payload["evidence_id"] = self.evidence_id
        return payload

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ImportedPostFilingEvidence":
        if not isinstance(value, Mapping):
            raise TypeError("ImportedPostFilingEvidence must be a mapping")
        return cls(
            schema_version=value.get("schema_version", WORKFLOW_SCHEMA_VERSION),
            evidence_id=value.get("evidence_id", ""),
            matter_id=value.get("matter_id", ""),
            kind=value.get("kind", PostFilingEvidenceKind.ACKNOWLEDGEMENT.value),
            artifact_id=value.get("artifact_id", ""),
            artifact_sha256=value.get("artifact_sha256", ""),
            source_channel=value.get(
                "source_channel",
                EvidenceSourceChannel.USER_SUPPLIED_IMPORT.value,
            ),
            imported_at_utc=value.get("imported_at_utc", ""),
            imported_by=value.get("imported_by", ""),
            package_digest=value.get("package_digest"),
            reviewed_manifest_id=value.get("reviewed_manifest_id"),
            source_receipt_id=value.get("source_receipt_id"),
            output_kind=value.get("output_kind", OUTPUT_KIND_POST_FILING_EVIDENCE),
            disclaimer=value.get("disclaimer", WORKFLOW_DISCLAIMER),
            content_digest=value.get("content_digest", ""),
            fabricated=False,
            labels=value.get("labels") or {},
        )


# ---------------------------------------------------------------------------
# Processor
# ---------------------------------------------------------------------------


class WorkflowProcessor:
    """Pre-submission preflight state machine and mandatory human gate."""

    def __init__(self, *, id_factory: Callable[[], str] | None = None) -> None:
        self._id_factory = id_factory or _default_id_factory

    def _new_id(self, prefix: str) -> str:
        return f"{prefix}:{self._id_factory()}"

    # ---- Forbidden surfaces (explicit for API / tests / audit) ----

    def sign(self, *args: Any, **kwargs: Any) -> None:
        raise ForbiddenWorkflowActionError("sign")

    def pay(self, *args: Any, **kwargs: Any) -> None:
        raise ForbiddenWorkflowActionError("pay")

    def file(self, *args: Any, **kwargs: Any) -> None:
        raise ForbiddenWorkflowActionError("file")

    def submit(self, *args: Any, **kwargs: Any) -> None:
        raise ForbiddenWorkflowActionError("submit")

    def mark_submitted(self, *args: Any, **kwargs: Any) -> None:
        raise ForbiddenWorkflowActionError("mark_submitted")

    def fabricate_acknowledgement(self, *args: Any, **kwargs: Any) -> None:
        raise ForbiddenWorkflowActionError("fabricate_acknowledgement")

    def fabricate_payment_receipt(self, *args: Any, **kwargs: Any) -> None:
        raise ForbiddenWorkflowActionError("fabricate_payment_receipt")

    def perform_action(self, action: str, *args: Any, **kwargs: Any) -> None:
        assert_action_allowed(action)
        raise WorkflowProcessorError(
            f"unknown or unsupported action: {action!r}",
            code="unsupported_action",
        )

    # ---- Preflight ----

    def run_preflight(self, package_input: PreflightPackageInput) -> PreflightResult:
        """Evaluate package gates from digests + open item projections."""
        if not isinstance(package_input, PreflightPackageInput):
            raise TypeError("package_input must be PreflightPackageInput")
        gates = self._build_gates(package_input)
        open_ids = tuple(g.gate_id for g in gates if g.mandatory)
        reason_codes: list[str] = [WorkflowReasonCode.PREFLIGHT_RUN.value]
        warnings: list[str] = []

        if package_input.mandatory_review_remaining:
            reason_codes.append(WorkflowReasonCode.MANDATORY_REVIEW_REMAINING.value)
        if package_input.open_unknown_ids:
            reason_codes.append(WorkflowReasonCode.UNRESOLVED_UNKNOWN.value)
        if package_input.open_gap_ids:
            reason_codes.append(WorkflowReasonCode.UNRESOLVED_GAP.value)
        if package_input.open_candidate_date_ids:
            reason_codes.append(WorkflowReasonCode.UNRESOLVED_CANDIDATE_DATE.value)
        if package_input.open_reviewer_action_ids:
            reason_codes.append(WorkflowReasonCode.UNRESOLVED_REVIEWER_ACTION.value)
        if requires_quarantine(package_input.classification):
            reason_codes.append(WorkflowReasonCode.QUARANTINE_BLOCK.value)
            warnings.append("classification requires quarantine; review mandatory")
        if package_input.prior_art_blocking_reason_codes:
            reason_codes.append(WorkflowReasonCode.PRIOR_ART_READINESS_BLOCK.value)
        if not package_input.prior_art_search_complete and (
            package_input.prior_art_checklist_id
            or package_input.prior_art_checklist_digest
        ):
            reason_codes.append(WorkflowReasonCode.PRIOR_ART_READINESS_BLOCK.value)
            warnings.append(
                "prior-art checklist present but search not marked complete "
                "(requires dated report + human coverage acknowledgment)"
            )

        reason_codes.append(WorkflowReasonCode.EXTERNAL_FILING_ONLY.value)
        reason_codes.append(WorkflowReasonCode.NEVER_MARKED_SUBMITTED.value)
        reason_codes.append(WorkflowReasonCode.RECEIPT_NOT_FABRICATED.value)

        if open_ids:
            reason_codes.append(WorkflowReasonCode.OPEN_GATES_REMAIN.value)
            disposition = PreflightDisposition.REVIEW_REQUIRED
            phase = PreflightPhase.PREFLIGHT_OPEN
            review_state = ReviewState.REQUIRED
        else:
            # Only package-acceptance gate may remain as mandatory baseline;
            # _build_gates always adds it, so open_ids should never be empty
            # unless that gate is somehow non-mandatory. Fail closed to review.
            disposition = PreflightDisposition.READY_FOR_HUMAN_REVIEW
            phase = PreflightPhase.PREFLIGHT_OPEN
            review_state = ReviewState.REQUIRED

        if requires_quarantine(package_input.classification):
            disposition = PreflightDisposition.BLOCKED
            phase = PreflightPhase.PREFLIGHT_OPEN
            review_state = ReviewState.REQUIRED

        package_digest = package_input.package_digest()
        return PreflightResult(
            schema_version=WORKFLOW_SCHEMA_VERSION,
            preflight_id=self._new_id("preflight"),
            matter_id=package_input.matter_id,
            phase=phase,
            disposition=disposition,
            package_digest=package_digest,
            source_bundle_id=package_input.source_bundle_id,
            source_bundle_digest=package_input.source_bundle_digest,
            gap_report_id=package_input.gap_report_id,
            gap_report_digest=package_input.gap_report_digest,
            gate_items=gates,
            open_gate_ids=open_ids,
            resolved_gate_ids=(),
            reason_codes=tuple(dict.fromkeys(reason_codes)),
            warnings=tuple(warnings),
            classification=package_input.classification,
            review_state=review_state,
            analysis_id=package_input.analysis_id,
            dossier_id=package_input.dossier_id,
            dossier_digest=package_input.dossier_digest,
            prior_art_checklist_id=package_input.prior_art_checklist_id,
            prior_art_checklist_digest=package_input.prior_art_checklist_digest,
            prior_art_search_complete=package_input.prior_art_search_complete,
            labels=package_input.labels,
        )

    def _build_gates(
        self, package_input: PreflightPackageInput
    ) -> tuple[PreflightGateItem, ...]:
        gates: list[PreflightGateItem] = []
        # Prefer full gap report projection when available.
        gr = package_input.gap_report
        if gr is not None and RequirementEvidenceGapReport is not None and isinstance(
            gr, RequirementEvidenceGapReport
        ):
            for unk in gr.unknowns:
                gates.append(
                    PreflightGateItem(
                        gate_id=f"gate:unknown:{unk.statement_id}",
                        kind=PreflightGateKind.UNKNOWN,
                        subject_id=unk.statement_id,
                        summary=unk.summary[:512]
                        if getattr(unk, "summary", None)
                        else f"unknown:{unk.statement_id}",
                        mandatory=True,
                        reason_codes=("unresolved_unknown",),
                        source_record_ids=(unk.statement_id,),
                    )
                )
            for row in gr.requirement_rows:
                status = row.status
                status_val = (
                    status.value if hasattr(status, "value") else str(status)
                )
                if status_val in ("gap", "unsatisfied", "missing", "unknown"):
                    gates.append(
                        PreflightGateItem(
                            gate_id=f"gate:gap:{row.requirement_id}",
                            kind=PreflightGateKind.GAP,
                            subject_id=row.requirement_id,
                            summary=(
                                f"requirement {row.requirement_id} status="
                                f"{status_val}"
                            ),
                            mandatory=True,
                            reason_codes=("unresolved_gap", status_val),
                            source_record_ids=(row.requirement_id,),
                        )
                    )
            for cand in gr.candidate_dates:
                needs = bool(
                    getattr(cand, "is_review_only", False)
                    or getattr(cand, "is_unknown", False)
                )
                if not needs and GapStatus is not None:
                    st = cand.status
                    needs = st in (
                        GapStatus.UNKNOWN,
                        GapStatus.GAP,
                        GapStatus.UNSATISFIED,
                        GapStatus.MISSING,
                    )
                if needs:
                    gates.append(
                        PreflightGateItem(
                            gate_id=f"gate:date:{cand.candidate_id}",
                            kind=PreflightGateKind.CANDIDATE_DATE,
                            subject_id=cand.candidate_id,
                            summary=(
                                f"candidate date {cand.candidate_id} requires "
                                "human confirmation"
                            ),
                            mandatory=True,
                            reason_codes=("unresolved_candidate_date",),
                            source_record_ids=(cand.candidate_id,),
                        )
                    )
            for action in gr.reviewer_actions:
                gates.append(
                    PreflightGateItem(
                        gate_id=f"gate:action:{action.action_id}",
                        kind=PreflightGateKind.REVIEWER_ACTION,
                        subject_id=action.action_id,
                        summary=action.message[:512],
                        mandatory=True,
                        reason_codes=tuple(action.reason_codes)
                        or ("unresolved_reviewer_action",),
                        source_record_ids=(action.action_id,),
                    )
                )
        else:
            for uid in package_input.open_unknown_ids:
                gates.append(
                    PreflightGateItem(
                        gate_id=f"gate:unknown:{uid}",
                        kind=PreflightGateKind.UNKNOWN,
                        subject_id=uid,
                        summary=f"unknown item requires acceptance: {uid}",
                        mandatory=True,
                        reason_codes=("unresolved_unknown",),
                        source_record_ids=(uid,),
                    )
                )
            for gid in package_input.open_gap_ids:
                gates.append(
                    PreflightGateItem(
                        gate_id=f"gate:gap:{gid}",
                        kind=PreflightGateKind.GAP,
                        subject_id=gid,
                        summary=f"gap/unsatisfied requirement requires resolution: {gid}",
                        mandatory=True,
                        reason_codes=("unresolved_gap",),
                        source_record_ids=(gid,),
                    )
                )
            for did in package_input.open_candidate_date_ids:
                gates.append(
                    PreflightGateItem(
                        gate_id=f"gate:date:{did}",
                        kind=PreflightGateKind.CANDIDATE_DATE,
                        subject_id=did,
                        summary=f"candidate date requires confirmation: {did}",
                        mandatory=True,
                        reason_codes=("unresolved_candidate_date",),
                        source_record_ids=(did,),
                    )
                )
            for aid in package_input.open_reviewer_action_ids:
                gates.append(
                    PreflightGateItem(
                        gate_id=f"gate:action:{aid}",
                        kind=PreflightGateKind.REVIEWER_ACTION,
                        subject_id=aid,
                        summary=f"reviewer action requires resolution: {aid}",
                        mandatory=True,
                        reason_codes=("unresolved_reviewer_action",),
                        source_record_ids=(aid,),
                    )
                )

        if requires_quarantine(package_input.classification):
            gates.append(
                PreflightGateItem(
                    gate_id="gate:quarantine:classification",
                    kind=PreflightGateKind.QUARANTINE,
                    subject_id=package_input.matter_id,
                    summary="quarantine classification requires human clearance",
                    mandatory=True,
                    reason_codes=("quarantine_block",),
                    source_record_ids=(package_input.matter_id,),
                )
            )

        # Prior-art readiness block when checklist is present but incomplete.
        if (
            package_input.prior_art_checklist_id
            or package_input.prior_art_checklist_digest
            or package_input.prior_art_blocking_reason_codes
        ) and not package_input.prior_art_search_complete:
            gates.append(
                PreflightGateItem(
                    gate_id="gate:prior-art:coverage",
                    kind=PreflightGateKind.PRIOR_ART_COVERAGE,
                    subject_id=package_input.prior_art_checklist_id
                    or "prior-art-checklist",
                    summary=(
                        "prior-art search coverage requires human acknowledgment "
                        "bound to a dated report"
                    ),
                    mandatory=True,
                    reason_codes=tuple(package_input.prior_art_blocking_reason_codes)
                    or ("prior_art_readiness_block",),
                    source_record_ids=tuple(
                        filter(
                            None,
                            (
                                package_input.prior_art_checklist_id,
                            ),
                        )
                    ),
                )
            )

        # Always require named package acceptance (mandatory human gate).
        gates.append(
            PreflightGateItem(
                gate_id="gate:package:acceptance",
                kind=PreflightGateKind.MANDATORY_PACKAGE_ACCEPTANCE,
                subject_id=package_input.gap_report_id,
                summary=(
                    "named human must accept the preflight package bound to "
                    f"bundle digest {package_input.source_bundle_digest[:16]}…"
                ),
                mandatory=True,
                reason_codes=("mandatory_package_acceptance",),
                source_record_ids=(
                    package_input.source_bundle_id,
                    package_input.gap_report_id,
                ),
            )
        )

        # De-dupe by gate_id preserving order.
        seen: set[str] = set()
        unique: list[PreflightGateItem] = []
        for g in gates:
            if g.gate_id not in seen:
                seen.add(g.gate_id)
                unique.append(g)
        return tuple(unique)

    def apply_resolutions(
        self,
        preflight: PreflightResult,
        resolutions: Sequence[ItemResolution],
    ) -> PreflightResult:
        """Apply human resolutions; reject resolutions bound to other digests."""
        if not isinstance(preflight, PreflightResult):
            raise TypeError("preflight must be PreflightResult")
        if preflight.phase is PreflightPhase.INVALIDATED:
            raise ReviewInvalidatedError(
                "cannot apply resolutions to an invalidated preflight"
            )
        res_list = list(resolutions or ())
        if len(res_list) > DEFAULT_MAX_RESOLUTIONS:
            raise WorkflowProcessorError(
                f"resolutions exceeds max {DEFAULT_MAX_RESOLUTIONS}",
                code="too_many_resolutions",
            )
        known = {g.gate_id: g for g in preflight.gate_items}
        resolved: set[str] = set(preflight.resolved_gate_ids)
        for r in res_list:
            if not isinstance(r, ItemResolution):
                raise TypeError("resolutions must be ItemResolution instances")
            if r.bound_package_digest != preflight.package_digest:
                raise ReviewInvalidatedError(
                    f"resolution for {r.gate_id} bound to package digest "
                    f"{r.bound_package_digest[:16]}… does not match preflight "
                    f"package digest {preflight.package_digest[:16]}…"
                )
            if r.gate_id not in known:
                raise WorkflowProcessorError(
                    f"unknown gate_id in resolution: {r.gate_id}",
                    code="unknown_gate",
                )
            if r.clears_gate:
                resolved.add(r.gate_id)

        open_ids = tuple(
            g.gate_id
            for g in preflight.gate_items
            if g.mandatory and g.gate_id not in resolved
        )
        reason_codes = list(preflight.reason_codes)
        if open_ids:
            if WorkflowReasonCode.OPEN_GATES_REMAIN.value not in reason_codes:
                reason_codes.append(WorkflowReasonCode.OPEN_GATES_REMAIN.value)
            disposition = PreflightDisposition.REVIEW_REQUIRED
            phase = PreflightPhase.REVIEW_IN_PROGRESS
            review_state = ReviewState.REQUIRED
        else:
            reason_codes = [
                c
                for c in reason_codes
                if c != WorkflowReasonCode.OPEN_GATES_REMAIN.value
            ]
            reason_codes.append(WorkflowReasonCode.ALL_GATES_RESOLVED.value)
            disposition = PreflightDisposition.REVIEW_COMPLETE
            phase = PreflightPhase.REVIEW_IN_PROGRESS
            review_state = ReviewState.PENDING

        # Rebuild without content_digest so it recomputes.
        data = preflight.to_dict()
        data.pop("content_digest", None)
        data["open_gate_ids"] = list(open_ids)
        data["resolved_gate_ids"] = sorted(resolved)
        data["disposition"] = disposition.value
        data["phase"] = phase.value
        data["review_state"] = review_state.value
        data["reason_codes"] = list(dict.fromkeys(reason_codes))
        return PreflightResult.from_dict(data)

    def bind_human_review(
        self,
        preflight: PreflightResult,
        *,
        reviewer_name: str,
        reviewed_at_utc: str,
        resolutions: Sequence[ItemResolution],
        statement: str,
        labels: Mapping[str, str] | None = None,
    ) -> tuple[PreflightResult, HumanReviewReceipt]:
        """Bind named human review to the preflight package digest.

        All mandatory gates must be resolved with matching package digests.
        """
        if not isinstance(preflight, PreflightResult):
            raise TypeError("preflight must be PreflightResult")
        if preflight.phase is PreflightPhase.INVALIDATED:
            raise ReviewInvalidatedError(
                "cannot bind human review to an invalidated preflight"
            )

        updated = self.apply_resolutions(preflight, resolutions)
        if updated.open_gate_ids:
            raise PreflightNotReadyError(
                "cannot bind human review while mandatory gates remain open: "
                + ", ".join(updated.open_gate_ids[:12])
            )
        if requires_quarantine(updated.classification):
            # Quarantine may be accepted via resolution of the quarantine gate,
            # but disposition stays careful: export still allowed only after bind.
            pass

        receipt = HumanReviewReceipt(
            schema_version=WORKFLOW_SCHEMA_VERSION,
            receipt_id=self._new_id("review"),
            preflight_id=updated.preflight_id,
            matter_id=updated.matter_id,
            reviewer_name=reviewer_name,
            reviewed_at_utc=reviewed_at_utc,
            package_digest=updated.package_digest,
            source_bundle_digest=updated.source_bundle_digest,
            gap_report_digest=updated.gap_report_digest,
            resolutions=tuple(resolutions),
            statement=statement,
            labels=labels or {},
        )

        data = updated.to_dict()
        data.pop("content_digest", None)
        data["phase"] = PreflightPhase.REVIEW_BOUND.value
        data["disposition"] = PreflightDisposition.REVIEW_COMPLETE.value
        data["review_state"] = ReviewState.COMPLETE.value
        codes = list(data.get("reason_codes") or [])
        codes.append(WorkflowReasonCode.HUMAN_REVIEW_BOUND.value)
        data["reason_codes"] = list(dict.fromkeys(codes))
        bound = PreflightResult.from_dict(data)
        return bound, receipt

    def export_reviewed_package(
        self,
        preflight: PreflightResult,
        receipt: HumanReviewReceipt,
        *,
        exported_at_utc: str,
        exported_by: str | None = None,
        labels: Mapping[str, str] | None = None,
    ) -> tuple[PreflightResult, ReviewedPackageManifest]:
        """Export a reviewed package manifest for external filing only."""
        if not isinstance(preflight, PreflightResult):
            raise TypeError("preflight must be PreflightResult")
        if not isinstance(receipt, HumanReviewReceipt):
            raise TypeError("receipt must be HumanReviewReceipt")
        if preflight.phase is PreflightPhase.INVALIDATED:
            raise ReviewInvalidatedError(
                "cannot export an invalidated preflight"
            )
        if preflight.phase not in (
            PreflightPhase.REVIEW_BOUND,
            PreflightPhase.PACKAGE_EXPORTABLE,
            PreflightPhase.EXTERNAL_FILING_HANDOFF,
        ):
            raise PreflightNotReadyError(
                f"preflight phase {preflight.phase.value} is not exportable; "
                "bind human review first"
            )
        if preflight.open_gate_ids:
            raise PreflightNotReadyError(
                "cannot export while open gates remain: "
                + ", ".join(preflight.open_gate_ids[:12])
            )
        if not receipt.binds_package_digest(preflight.package_digest):
            raise ReviewInvalidatedError(
                "human review receipt package digest does not match preflight"
            )
        if receipt.preflight_id != preflight.preflight_id:
            raise WorkflowProcessorError(
                "review receipt preflight_id does not match preflight",
                code="preflight_id_mismatch",
            )
        if receipt.source_bundle_digest != preflight.source_bundle_digest:
            raise ReviewInvalidatedError(
                "review receipt source_bundle_digest does not match preflight"
            )
        if receipt.gap_report_digest != preflight.gap_report_digest:
            raise ReviewInvalidatedError(
                "review receipt gap_report_digest does not match preflight"
            )

        exporter = exported_by or receipt.reviewer_name
        manifest = ReviewedPackageManifest(
            schema_version=WORKFLOW_SCHEMA_VERSION,
            manifest_id=self._new_id("pkg"),
            matter_id=preflight.matter_id,
            preflight_id=preflight.preflight_id,
            review_receipt_id=receipt.receipt_id,
            review_receipt_digest=receipt.content_digest,
            package_digest=preflight.package_digest,
            source_bundle_id=preflight.source_bundle_id,
            source_bundle_digest=preflight.source_bundle_digest,
            gap_report_id=preflight.gap_report_id,
            gap_report_digest=preflight.gap_report_digest,
            exported_at_utc=exported_at_utc,
            exported_by=exporter,
            phase=PreflightPhase.EXTERNAL_FILING_HANDOFF,
            labels=labels or {},
        )

        data = preflight.to_dict()
        data.pop("content_digest", None)
        data["phase"] = PreflightPhase.EXTERNAL_FILING_HANDOFF.value
        data["disposition"] = PreflightDisposition.EXPORTABLE.value
        codes = list(data.get("reason_codes") or [])
        codes.append(WorkflowReasonCode.PACKAGE_EXPORTABLE.value)
        codes.append(WorkflowReasonCode.EXTERNAL_FILING_ONLY.value)
        data["reason_codes"] = list(dict.fromkeys(codes))
        exported_pf = PreflightResult.from_dict(data)
        return exported_pf, manifest

    def check_inputs_still_valid(
        self,
        preflight: PreflightResult,
        package_input: PreflightPackageInput,
        *,
        receipt: HumanReviewReceipt | None = None,
    ) -> PreflightResult:
        """Return preflight unchanged or an INVALIDATED copy if digests drift."""
        if not isinstance(preflight, PreflightResult):
            raise TypeError("preflight must be PreflightResult")
        if not isinstance(package_input, PreflightPackageInput):
            raise TypeError("package_input must be PreflightPackageInput")
        current = package_input.package_digest()
        if current == preflight.package_digest:
            if receipt is not None and not receipt.binds_package_digest(current):
                return self._invalidate(
                    preflight,
                    reason="human review receipt no longer matches package digest",
                )
            return preflight
        return self._invalidate(
            preflight,
            reason=(
                "material package inputs changed: package digest "
                f"{preflight.package_digest[:16]}… -> {current[:16]}…"
            ),
        )

    def _invalidate(
        self, preflight: PreflightResult, *, reason: str
    ) -> PreflightResult:
        data = preflight.to_dict()
        data.pop("content_digest", None)
        data["phase"] = PreflightPhase.INVALIDATED.value
        data["disposition"] = PreflightDisposition.INVALIDATED.value
        data["review_state"] = ReviewState.REQUIRED.value
        # Re-open all mandatory gates on invalidation.
        data["open_gate_ids"] = [
            g["gate_id"] for g in data.get("gate_items") or [] if g.get("mandatory")
        ]
        data["resolved_gate_ids"] = []
        codes = list(data.get("reason_codes") or [])
        codes.append(WorkflowReasonCode.INPUTS_CHANGED.value)
        codes.append(WorkflowReasonCode.REVIEW_INVALIDATED.value)
        data["reason_codes"] = list(dict.fromkeys(codes))
        warnings = list(data.get("warnings") or [])
        warnings.append(reason[:512])
        data["warnings"] = warnings
        return PreflightResult.from_dict(data)

    def invalidate_review(
        self, preflight: PreflightResult, *, reason: str = "manual invalidation"
    ) -> PreflightResult:
        """Force-invalidate a preflight/review (e.g. operator action)."""
        return self._invalidate(preflight, reason=reason)

    def import_post_filing_evidence(
        self,
        *,
        matter_id: str,
        kind: PostFilingEvidenceKind | str,
        artifact_id: str,
        artifact_sha256: str,
        imported_at_utc: str,
        imported_by: str,
        package_digest: str | None = None,
        reviewed_manifest_id: str | None = None,
        source_receipt_id: str | None = None,
        labels: Mapping[str, str] | None = None,
    ) -> ImportedPostFilingEvidence:
        """Import a user-supplied acknowledgement or payment receipt.

        Never fabricates content. Requires a real artifact id + sha256 from
        an authorized user import path.
        """
        # Explicitly reject fabrication paths.
        if labels and any(
            str(k).lower() in ("fabricated", "synthetic", "invented")
            for k in labels
        ):
            raise FabricatedEvidenceError(
                "labels must not mark evidence as fabricated/synthetic/invented"
            )
        return ImportedPostFilingEvidence(
            schema_version=WORKFLOW_SCHEMA_VERSION,
            evidence_id=self._new_id("pfevid"),
            matter_id=matter_id,
            kind=kind,
            artifact_id=artifact_id,
            artifact_sha256=artifact_sha256,
            source_channel=EvidenceSourceChannel.USER_SUPPLIED_IMPORT,
            imported_at_utc=imported_at_utc,
            imported_by=imported_by,
            package_digest=package_digest,
            reviewed_manifest_id=reviewed_manifest_id,
            source_receipt_id=source_receipt_id,
            labels=labels or {},
        )


# ---------------------------------------------------------------------------
# Convenience helpers
# ---------------------------------------------------------------------------


def run_package_preflight(
    package_input: PreflightPackageInput,
    *,
    id_factory: Callable[[], str] | None = None,
) -> PreflightResult:
    return WorkflowProcessor(id_factory=id_factory).run_preflight(package_input)


def package_inputs_match(
    preflight: PreflightResult, package_input: PreflightPackageInput
) -> bool:
    """True when *package_input* still matches the preflight package digest."""
    if not isinstance(preflight, PreflightResult):
        raise TypeError("preflight must be PreflightResult")
    if not isinstance(package_input, PreflightPackageInput):
        raise TypeError("package_input must be PreflightPackageInput")
    return package_input.package_digest() == preflight.package_digest


def build_resolution(
    gate_id: str,
    *,
    disposition: ResolutionDisposition | str,
    reviewer_name: str,
    resolved_at_utc: str,
    statement: str,
    package_digest: str,
    notes: str | None = None,
    labels: Mapping[str, str] | None = None,
) -> ItemResolution:
    return ItemResolution(
        gate_id=gate_id,
        disposition=disposition,
        reviewer_name=reviewer_name,
        resolved_at_utc=resolved_at_utc,
        statement=statement,
        bound_package_digest=package_digest,
        notes=notes,
        labels=labels or {},
    )


def accept_all_open_gates(
    preflight: PreflightResult,
    *,
    reviewer_name: str,
    resolved_at_utc: str,
    statement: str = "accepted after human review",
) -> tuple[ItemResolution, ...]:
    """Helper: produce ACCEPTED resolutions for every open mandatory gate."""
    if not isinstance(preflight, PreflightResult):
        raise TypeError("preflight must be PreflightResult")
    out: list[ItemResolution] = []
    for gate_id in preflight.open_gate_ids:
        out.append(
            ItemResolution(
                gate_id=gate_id,
                disposition=ResolutionDisposition.ACCEPTED,
                reviewer_name=reviewer_name,
                resolved_at_utc=resolved_at_utc,
                statement=statement,
                bound_package_digest=preflight.package_digest,
            )
        )
    return tuple(out)


__all__ = [
    "DEFAULT_MAX_GATES",
    "DEFAULT_MAX_RESOLUTIONS",
    "FORBIDDEN_WORKFLOW_ACTIONS",
    "OUTPUT_KIND_HUMAN_REVIEW_RECEIPT",
    "OUTPUT_KIND_POST_FILING_EVIDENCE",
    "OUTPUT_KIND_PREFLIGHT_RESULT",
    "OUTPUT_KIND_REVIEWED_PACKAGE_MANIFEST",
    "OUTPUT_KIND_WORKFLOW_STATE",
    "PARSER_VERSION",
    "WORKFLOW_DISCLAIMER",
    "WORKFLOW_INTERFACE",
    "WORKFLOW_RULESET_VERSION",
    "WORKFLOW_SCHEMA_VERSION",
    "EvidenceSourceChannel",
    "FabricatedEvidenceError",
    "ForbiddenWorkflowActionError",
    "HumanReviewReceipt",
    "ImportedPostFilingEvidence",
    "ItemResolution",
    "PostFilingEvidenceKind",
    "PreflightDisposition",
    "PreflightGateItem",
    "PreflightGateKind",
    "PreflightNotReadyError",
    "PreflightPackageInput",
    "PreflightPhase",
    "PreflightResult",
    "ResolutionDisposition",
    "ReviewInvalidatedError",
    "ReviewedPackageManifest",
    "WorkflowProcessor",
    "WorkflowProcessorError",
    "WorkflowReasonCode",
    "accept_all_open_gates",
    "assert_action_allowed",
    "build_resolution",
    "is_forbidden_action",
    "package_inputs_match",
    "run_package_preflight",
    "sha256_hex",
]
