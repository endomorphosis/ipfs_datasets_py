"""Serialized submission-assurance workflow (PATLAW-140).

Composes resumable matter analysis, baseline filing-obligation resolution,
submission-vs-instruction comparison, coverage reporting, and redacted dossier
export into one one-shot / resumable processor exposed through the USPTO API
and CLI.

Design invariants
-----------------
* Callers supply tenant/matter plus an authorized source profile (documents /
  offline snapshots). No hand-built middle-stage objects are required.
* Classification is derived from admitted artifacts; omitted or unknown
  classification defaults to quarantine rather than public success.
* Transport execution (stages ran without crash) is distinct from domain
  assurance disposition. Outage, quarantine, incomplete analysis, proof-unknown,
  and mandatory review never collapse to domain ``success`` / ``ok``.
* Result status reports coverage for sync, extraction, authority, proof, and
  compliance dimensions.
* Output lists satisfied / missing / contradictory / unknown / review items
  with exact provenance (artifact ids, digests, rule ids, span ids).
* Never files, pays, signs, automates a browser, or claims legal advice.
* Checkpoints store digests, statuses, and reason codes — never private body
  text.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Final, Iterable, Mapping, MutableMapping, Sequence

from .analysis.filing_obligation_processor import (
    FILING_OBLIGATION_SCHEMA_VERSION,
    FilingObligationProcessor,
    FilingObligationRequest,
    FilingObligationResult,
    ObligationResolutionStatus,
    REVIEW_ONLY_OBLIGATION_DISCLAIMER,
)
from .analysis.filing_rule_packs import (
    ApplicationType,
    EvidenceKind,
    FilingScenario,
    ProsecutionStage,
)
from .contracts import (
    CONTRACTS_SCHEMA_VERSION,
    DisclosureClassification,
    ReviewState,
    canonical_json,
    most_restrictive_classification,
    requires_quarantine,
)
from .matter_analysis_processor import (
    MATTER_ANALYSIS_SCHEMA_VERSION,
    MatterAnalysisDisposition,
    MatterAnalysisInput,
    MatterAnalysisProcessor,
    MatterAnalysisResult,
    MatterDocumentInput,
    create_matter_analysis_processor,
)
from .workflow_processor import (
    FORBIDDEN_WORKFLOW_ACTIONS,
    WORKFLOW_SCHEMA_VERSION,
    PreflightPackageInput,
    PreflightResult,
    WorkflowProcessor,
)

# ---------------------------------------------------------------------------
# Versions / interface
# ---------------------------------------------------------------------------

SUBMISSION_ASSURANCE_SCHEMA_VERSION: Final = "uspto.submission-assurance.v1"
SUBMISSION_ASSURANCE_INTERFACE: Final = "SubmissionAssuranceProcessor@1"
SUBMISSION_ASSURANCE_PARSER_DIGEST_MATERIAL: Final = (
    f"{SUBMISSION_ASSURANCE_SCHEMA_VERSION}|"
    f"{CONTRACTS_SCHEMA_VERSION}|"
    f"{MATTER_ANALYSIS_SCHEMA_VERSION}|"
    f"{FILING_OBLIGATION_SCHEMA_VERSION}|"
    f"{WORKFLOW_SCHEMA_VERSION}"
)

REVIEW_ONLY_ASSURANCE_DISCLAIMER: Final = (
    "This submission-assurance result is a review-only decision-support "
    "product. It is not legal advice, not a completeness certification, and "
    "does not authorize filing, payment, signature, browser automation, or "
    "docket mutation. Coverage is not exhaustive. Named human review is "
    "required before any export relied upon for external action."
)

_DIRECTORY_MODE: Final = 0o700
_FILE_MODE: Final = 0o600
_ID_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._:/=+\-]{0,255}\Z")
_SHA256_RE = re.compile(r"\A[0-9a-f]{64}\Z")
_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._\-]+")
_MAX_REASON_CODES: Final = 128
_MAX_DOCUMENTS: Final = 64
_MAX_ITEMS: Final = 4096
_MAX_TEXT_CHARS: Final = 256_000

# Document role → evidence kinds that role can satisfy.
_ROLE_TO_EVIDENCE: Final[Mapping[str, frozenset[str]]] = MappingProxyType(
    {
        "specification": frozenset(
            {EvidenceKind.SPECIFICATION.value, EvidenceKind.ATTACHMENT.value}
        ),
        "claims": frozenset(
            {
                EvidenceKind.CLAIMS.value,
                EvidenceKind.CLAIM_AMENDMENT.value,
                EvidenceKind.ATTACHMENT.value,
            }
        ),
        "drawings": frozenset(
            {EvidenceKind.DRAWINGS.value, EvidenceKind.ATTACHMENT.value}
        ),
        "ads": frozenset(
            {
                EvidenceKind.ADS.value,
                EvidenceKind.FORM.value,
                EvidenceKind.IDENTIFIER.value,
            }
        ),
        "application_data_sheet": frozenset(
            {
                EvidenceKind.ADS.value,
                EvidenceKind.FORM.value,
                EvidenceKind.IDENTIFIER.value,
            }
        ),
        "form": frozenset({EvidenceKind.FORM.value, EvidenceKind.ATTACHMENT.value}),
        "fee": frozenset({EvidenceKind.FEE.value}),
        "oath": frozenset(
            {
                EvidenceKind.OATH_DECLARATION.value,
                EvidenceKind.SIGNATURE_PRESENCE.value,
                EvidenceKind.CERTIFICATION.value,
            }
        ),
        "declaration": frozenset(
            {
                EvidenceKind.OATH_DECLARATION.value,
                EvidenceKind.SIGNATURE_PRESENCE.value,
                EvidenceKind.CERTIFICATION.value,
            }
        ),
        "remarks": frozenset(
            {EvidenceKind.REMARKS.value, EvidenceKind.ATTACHMENT.value}
        ),
        "amendment": frozenset(
            {
                EvidenceKind.CLAIM_AMENDMENT.value,
                EvidenceKind.REMARKS.value,
                EvidenceKind.ATTACHMENT.value,
            }
        ),
        "office_action": frozenset({EvidenceKind.ATTACHMENT.value}),
        "attachment": frozenset({EvidenceKind.ATTACHMENT.value, EvidenceKind.OTHER.value}),
        "other": frozenset({EvidenceKind.OTHER.value, EvidenceKind.ATTACHMENT.value}),
        "sequence_listing": frozenset({EvidenceKind.SEQUENCE_LISTING.value}),
        "benefit_claim": frozenset({EvidenceKind.BENEFIT_CLAIM.value}),
    }
)


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class AssuranceStage(str, Enum):
    """Ordered stages of the submission-assurance DAG."""

    AUTHORIZE = "authorize"
    MATTER_ANALYSIS = "matter_analysis"
    FILING_OBLIGATIONS = "filing_obligations"
    COMPLIANCE_COMPARE = "compliance_compare"
    COVERAGE = "coverage"
    PREFLIGHT = "preflight"
    DOSSIER_EXPORT = "dossier_export"
    FINALIZE = "finalize"


ASSURANCE_STAGE_ORDER: Final[tuple[AssuranceStage, ...]] = (
    AssuranceStage.AUTHORIZE,
    AssuranceStage.MATTER_ANALYSIS,
    AssuranceStage.FILING_OBLIGATIONS,
    AssuranceStage.COMPLIANCE_COMPARE,
    AssuranceStage.COVERAGE,
    AssuranceStage.PREFLIGHT,
    AssuranceStage.DOSSIER_EXPORT,
    AssuranceStage.FINALIZE,
)


class AssuranceStageStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMMITTED = "committed"
    SKIPPED = "skipped"
    FAILED = "failed"
    QUARANTINED = "quarantined"


class AssuranceDisposition(str, Enum):
    """Terminal domain outcome for a submission-assurance run.

    Non-success dispositions must never collapse to unconditional success.
    """

    COMPLETED = "completed"
    PARTIAL = "partial"
    QUARANTINED = "quarantined"
    STALE_AUTHORITY = "stale_authority"
    PROOF_UNKNOWN = "proof_unknown"
    REVIEW_REQUIRED = "review_required"
    OUTAGE = "outage"
    FAILED = "failed"
    INTERRUPTED = "interrupted"


class AssuranceItemKind(str, Enum):
    """Bucket for provenance-backed assurance findings."""

    SATISFIED = "satisfied"
    MISSING = "missing"
    CONTRADICTORY = "contradictory"
    UNKNOWN = "unknown"
    REVIEW = "review"


class CoverageDimension(str, Enum):
    """Coverage axes reported on every assurance result."""

    SYNC = "sync"
    EXTRACTION = "extraction"
    AUTHORITY = "authority"
    PROOF = "proof"
    COMPLIANCE = "compliance"


class CoverageStatus(str, Enum):
    COVERED = "covered"
    PARTIAL = "partial"
    MISSING = "missing"
    UNKNOWN = "unknown"
    FAILED = "failed"
    OUTAGE = "outage"


class AssuranceReasonCode(str, Enum):
    STAGE_COMMITTED = "stage_committed"
    STAGE_RESUMED = "stage_resumed"
    STAGE_REUSED_BY_DIGEST = "stage_reused_by_digest"
    AUTHORIZED = "authorized"
    MATTER_ANALYSIS_COMPLETED = "matter_analysis_completed"
    MATTER_ANALYSIS_NON_SUCCESS = "matter_analysis_non_success"
    OBLIGATIONS_RESOLVED = "obligations_resolved"
    COMPLIANCE_COMPARED = "compliance_compared"
    COVERAGE_COMPUTED = "coverage_computed"
    PREFLIGHT_EVALUATED = "preflight_evaluated"
    DOSSIER_EXPORTED = "dossier_exported"
    FINALIZED = "finalized"
    PARTIAL_COVERAGE = "partial_coverage"
    QUARANTINE_CLASSIFICATION = "quarantine_classification"
    QUARANTINE_POLICY = "quarantine_policy"
    STALE_AUTHORITY = "stale_authority"
    PROOF_UNKNOWN = "proof_unknown"
    REVIEW_REQUIRED = "review_required"
    OUTAGE = "outage"
    MISSING_MATTER = "missing_matter"
    MISSING_TENANT = "missing_tenant"
    MISSING_SOURCE_PROFILE = "missing_source_profile"
    INJECTED_FAILURE = "injected_failure"
    JOB_COMPLETED = "job_completed"
    JOB_PARTIAL = "job_partial"
    JOB_QUARANTINED = "job_quarantined"
    JOB_STALE_AUTHORITY = "job_stale_authority"
    JOB_PROOF_UNKNOWN = "job_proof_unknown"
    JOB_REVIEW_REQUIRED = "job_review_required"
    JOB_OUTAGE = "job_outage"
    JOB_FAILED = "job_failed"
    JOB_INTERRUPTED = "job_interrupted"
    NOT_LEGAL_ADVICE = "not_legal_advice"
    NOT_EXHAUSTIVE = "not_exhaustive"
    REVIEW_ONLY = "review_only"
    NO_FILE_PAY_SIGN = "no_file_pay_sign"
    TRANSPORT_OK = "transport_ok"
    TRANSPORT_FAILED = "transport_failed"
    DOMAIN_SUCCESS = "domain_success"
    DOMAIN_NON_SUCCESS = "domain_non_success"


class SubmissionAssuranceError(ValueError):
    """Bounded orchestration error with a stable machine-readable code."""

    def __init__(self, message: str, *, code: str = "submission_assurance_error") -> None:
        super().__init__(message)
        self.code = str(code)

    def audit_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": str(self)[:256]}


class InjectedAssuranceFailure(Exception):
    """Raised by failure injection before a stage body executes (tests/resume)."""

    def __init__(self, stage: AssuranceStage) -> None:
        super().__init__(f"injected failure before stage {stage.value}")
        self.stage = stage
        self.code = AssuranceReasonCode.INJECTED_FAILURE.value


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def sha256_hex(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def parser_digest() -> str:
    """Stable digest of orchestrator + dependency schema identities."""
    return sha256_hex(SUBMISSION_ASSURANCE_PARSER_DIGEST_MATERIAL)


def stage_idempotency_key(
    *,
    assurance_id: str,
    stage: AssuranceStage | str,
    input_digest: str,
    parser_digest_value: str | None = None,
) -> str:
    stage_v = stage.value if isinstance(stage, AssuranceStage) else str(stage)
    digest = parser_digest_value or parser_digest()
    material = f"{assurance_id}|{stage_v}|{input_digest}|{digest}"
    return sha256_hex(material)


def _require_id(value: str, name: str) -> str:
    text = str(value or "").strip()
    if not text or not _ID_RE.match(text):
        raise SubmissionAssuranceError(f"invalid {name}: {value!r}", code="invalid_id")
    return text


def _optional_str(value: Any, *, max_len: int = 512) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return text[:max_len]


def _safe_filename(value: str) -> str:
    cleaned = _SAFE_NAME_RE.sub("_", value.strip())
    return cleaned[:180] or "assurance"


def _frozen_str_map(
    value: Mapping[str, Any] | None, *, max_items: int = 64
) -> Mapping[str, str]:
    if not value:
        return MappingProxyType({})
    items = {
        str(k): str(v)
        for k, v in sorted(value.items(), key=lambda kv: str(kv[0]))
    }
    if len(items) > max_items:
        items = dict(list(items.items())[:max_items])
    return MappingProxyType(items)


def _coerce_classification(
    value: DisclosureClassification | str | None,
) -> DisclosureClassification:
    if value is None:
        return DisclosureClassification.UNKNOWN
    if isinstance(value, DisclosureClassification):
        return value
    try:
        return DisclosureClassification(str(value).strip())
    except ValueError:
        return DisclosureClassification.UNKNOWN


def _coerce_stage(
    value: AssuranceStage | str | None,
) -> AssuranceStage | None:
    if value is None:
        return None
    if isinstance(value, AssuranceStage):
        return value
    return AssuranceStage(str(value).strip())


def _ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path, _DIRECTORY_MODE)
    except OSError:
        pass
    return path


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    _ensure_dir(path.parent)
    tmp = path.with_suffix(path.suffix + ".tmp")
    text = json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    fd = os.open(tmp, flags, _FILE_MODE)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        try:
            tmp.unlink(missing_ok=True)  # type: ignore[call-arg]
        except TypeError:
            if tmp.exists():
                tmp.unlink()
        raise
    os.replace(tmp, path)
    try:
        os.chmod(path, _FILE_MODE)
    except OSError:
        pass


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise SubmissionAssuranceError(
            f"expected object at {path.name}", code="checkpoint_integrity"
        )
    return data


def _canonical_digest(payload: Any) -> str:
    return sha256_hex(canonical_json(payload))


def _evidence_kinds_for_role(role: str) -> frozenset[str]:
    key = str(role or "other").strip().lower()
    return _ROLE_TO_EVIDENCE.get(key, frozenset({EvidenceKind.OTHER.value}))


def assert_assurance_action_allowed(action: str) -> None:
    """Fail closed if *action* is a forbidden capability."""
    key = str(action or "").strip().lower().replace("-", "_").replace(" ", "_")
    if not key:
        raise SubmissionAssuranceError(
            "action is required", code="missing_action"
        )
    if key in FORBIDDEN_WORKFLOW_ACTIONS or key in {
        "sign",
        "pay",
        "file",
        "submit",
        "browser",
        "automate_browser",
        "scrape",
        "login",
        "legal_advice",
        "certify",
    }:
        raise SubmissionAssuranceError(
            f"forbidden submission-assurance action: {action!r}",
            code="forbidden_action",
        )


# ---------------------------------------------------------------------------
# Input / finding models
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ProvenanceRef:
    """Exact provenance anchor for an assurance item (no body text)."""

    kind: str
    ref_id: str
    digest: str | None = None
    span_id: str | None = None
    rule_id: str | None = None
    labels: Mapping[str, str] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "kind", (_optional_str(self.kind, max_len=64) or "unknown")
        )
        object.__setattr__(self, "ref_id", _require_id(str(self.ref_id), "ref_id"))
        if self.digest is not None:
            digest = str(self.digest).strip().lower()
            if digest and not _SHA256_RE.match(digest):
                raise SubmissionAssuranceError(
                    "provenance digest must be 64-char lowercase hex",
                    code="invalid_digest",
                )
            object.__setattr__(self, "digest", digest or None)
        object.__setattr__(self, "span_id", _optional_str(self.span_id, max_len=256))
        object.__setattr__(self, "rule_id", _optional_str(self.rule_id, max_len=256))
        object.__setattr__(self, "labels", _frozen_str_map(self.labels))

    def to_dict(self) -> dict[str, Any]:
        return {
            "digest": self.digest,
            "kind": self.kind,
            "labels": dict(self.labels),
            "ref_id": self.ref_id,
            "rule_id": self.rule_id,
            "span_id": self.span_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ProvenanceRef":
        if not isinstance(value, Mapping):
            raise TypeError("ProvenanceRef must be a mapping")
        return cls(
            kind=str(value.get("kind") or "unknown"),
            ref_id=str(value.get("ref_id") or value.get("id") or ""),
            digest=value.get("digest"),
            span_id=value.get("span_id"),
            rule_id=value.get("rule_id"),
            labels=value.get("labels") or {},
        )


@dataclass(frozen=True, slots=True)
class AssuranceItem:
    """One provenance-backed finding in a bucketed assurance inventory."""

    item_id: str
    kind: AssuranceItemKind | str
    title: str
    description: str
    provenance: tuple[ProvenanceRef, ...] = ()
    dimension: CoverageDimension | str | None = None
    obligation_rule_id: str | None = None
    evidence_kind: str | None = None
    blocking: bool = False
    labels: Mapping[str, str] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(self, "item_id", _require_id(str(self.item_id), "item_id"))
        if not isinstance(self.kind, AssuranceItemKind):
            object.__setattr__(
                self, "kind", AssuranceItemKind(str(self.kind).strip().lower())
            )
        object.__setattr__(
            self, "title", (_optional_str(self.title, max_len=256) or self.item_id)
        )
        object.__setattr__(
            self,
            "description",
            (_optional_str(self.description, max_len=1024) or ""),
        )
        refs: list[ProvenanceRef] = []
        for raw in self.provenance or ():
            if isinstance(raw, ProvenanceRef):
                refs.append(raw)
            elif isinstance(raw, Mapping):
                refs.append(ProvenanceRef.from_dict(raw))
            else:
                raise TypeError("provenance entries must be ProvenanceRef or mapping")
        object.__setattr__(self, "provenance", tuple(refs[:64]))
        if self.dimension is not None and not isinstance(
            self.dimension, CoverageDimension
        ):
            object.__setattr__(
                self,
                "dimension",
                CoverageDimension(str(self.dimension).strip().lower()),
            )
        object.__setattr__(
            self,
            "obligation_rule_id",
            _optional_str(self.obligation_rule_id, max_len=256),
        )
        object.__setattr__(
            self, "evidence_kind", _optional_str(self.evidence_kind, max_len=64)
        )
        if not isinstance(self.blocking, bool):
            raise TypeError("blocking must be bool")
        object.__setattr__(self, "labels", _frozen_str_map(self.labels))

    def to_dict(self) -> dict[str, Any]:
        return {
            "blocking": self.blocking,
            "description": self.description,
            "dimension": (
                self.dimension.value
                if isinstance(self.dimension, CoverageDimension)
                else self.dimension
            ),
            "evidence_kind": self.evidence_kind,
            "item_id": self.item_id,
            "kind": (
                self.kind.value
                if isinstance(self.kind, AssuranceItemKind)
                else str(self.kind)
            ),
            "labels": dict(self.labels),
            "obligation_rule_id": self.obligation_rule_id,
            "provenance": [p.to_dict() for p in self.provenance],
            "title": self.title,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "AssuranceItem":
        if not isinstance(value, Mapping):
            raise TypeError("AssuranceItem must be a mapping")
        raw_prov = value.get("provenance") or ()
        return cls(
            item_id=str(value.get("item_id") or ""),
            kind=str(value.get("kind") or AssuranceItemKind.UNKNOWN.value),
            title=str(value.get("title") or ""),
            description=str(value.get("description") or ""),
            provenance=tuple(raw_prov),
            dimension=value.get("dimension"),
            obligation_rule_id=value.get("obligation_rule_id"),
            evidence_kind=value.get("evidence_kind"),
            blocking=bool(value.get("blocking", False)),
            labels=value.get("labels") or {},
        )


@dataclass(frozen=True, slots=True)
class CoverageReport:
    """Per-dimension coverage status for the assurance run."""

    statuses: Mapping[str, str]
    notes: Mapping[str, str] = MappingProxyType({})

    def __post_init__(self) -> None:
        statuses = {
            str(k): str(v)
            for k, v in sorted((self.statuses or {}).items(), key=lambda kv: str(kv[0]))
        }
        # Ensure all dimensions are present.
        for dim in CoverageDimension:
            statuses.setdefault(dim.value, CoverageStatus.UNKNOWN.value)
        object.__setattr__(self, "statuses", MappingProxyType(statuses))
        object.__setattr__(self, "notes", _frozen_str_map(self.notes))

    def to_dict(self) -> dict[str, Any]:
        return {
            "notes": dict(self.notes),
            "statuses": dict(self.statuses),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CoverageReport":
        if not isinstance(value, Mapping):
            raise TypeError("CoverageReport must be a mapping")
        return cls(
            statuses=value.get("statuses") or {},
            notes=value.get("notes") or {},
        )

    def status_for(self, dimension: CoverageDimension | str) -> str:
        key = (
            dimension.value
            if isinstance(dimension, CoverageDimension)
            else str(dimension)
        )
        return str(self.statuses.get(key, CoverageStatus.UNKNOWN.value))


@dataclass(frozen=True, slots=True)
class SubmissionAssuranceInput:
    """Inputs for one one-shot or resumable submission-assurance run.

    Provide documents (and optional status snapshot) directly — no caller-built
    middle-stage dossier/compliance objects are required.
    """

    tenant_id: str
    matter_id: str
    assurance_id: str | None = None
    application_number: str | None = None
    documents: tuple[MatterDocumentInput, ...] = ()
    status_snapshot: Mapping[str, Any] = MappingProxyType({})
    # Source profile: authorized offline/live intent for acquisition.
    source_profile: str = "offline_authorized"
    application_type: ApplicationType | str = ApplicationType.UTILITY
    scenario: FilingScenario | str = FilingScenario.NEW_APPLICATION
    prosecution_stage: ProsecutionStage | str = ProsecutionStage.FILING
    filing_date: str | None = None
    as_of_utc: str | None = None
    authority_snapshot_id: str | None = None
    authority_digest: str | None = None
    authority_stale: bool = False
    force_proof_unknown: bool = False
    force_review_required: bool = False
    force_partial: bool = False
    force_quarantine: bool = False
    force_outage: bool = False
    classification: DisclosureClassification | str | None = None
    labels: Mapping[str, str] = MappingProxyType({})
    inject_failure_before: AssuranceStage | str | None = None
    offline: bool = True
    run_preflight: bool = True
    # When set, treat this invocation as a resume/delta over prior checkpoint.
    delta_token: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "tenant_id", _require_id(str(self.tenant_id), "tenant_id")
        )
        object.__setattr__(
            self, "matter_id", _require_id(str(self.matter_id), "matter_id")
        )
        if self.assurance_id is not None:
            object.__setattr__(
                self,
                "assurance_id",
                _require_id(str(self.assurance_id), "assurance_id"),
            )
        object.__setattr__(
            self,
            "application_number",
            _optional_str(self.application_number, max_len=64),
        )
        docs: list[MatterDocumentInput] = []
        raw_docs = self.documents or ()
        if not isinstance(raw_docs, tuple):
            raw_docs = tuple(raw_docs)  # type: ignore[arg-type]
        for item in raw_docs[:_MAX_DOCUMENTS]:
            if isinstance(item, MatterDocumentInput):
                docs.append(item)
            elif isinstance(item, Mapping):
                docs.append(MatterDocumentInput(**dict(item)))
            else:
                raise TypeError(
                    "documents entries must be MatterDocumentInput or mapping"
                )
        object.__setattr__(self, "documents", tuple(docs))
        snap = self.status_snapshot or {}
        if not isinstance(snap, Mapping):
            raise TypeError("status_snapshot must be a mapping")
        object.__setattr__(
            self,
            "status_snapshot",
            MappingProxyType({str(k): v for k, v in dict(snap).items()}),
        )
        object.__setattr__(
            self,
            "source_profile",
            (_optional_str(self.source_profile, max_len=128) or "offline_authorized"),
        )
        if not isinstance(self.application_type, ApplicationType):
            try:
                object.__setattr__(
                    self,
                    "application_type",
                    ApplicationType(str(self.application_type).strip().lower()),
                )
            except ValueError:
                object.__setattr__(self, "application_type", ApplicationType.UNKNOWN)
        if not isinstance(self.scenario, FilingScenario):
            try:
                object.__setattr__(
                    self,
                    "scenario",
                    FilingScenario(str(self.scenario).strip().lower()),
                )
            except ValueError:
                object.__setattr__(self, "scenario", FilingScenario.UNKNOWN)
        if not isinstance(self.prosecution_stage, ProsecutionStage):
            try:
                object.__setattr__(
                    self,
                    "prosecution_stage",
                    ProsecutionStage(str(self.prosecution_stage).strip().lower()),
                )
            except ValueError:
                object.__setattr__(
                    self, "prosecution_stage", ProsecutionStage.FILING
                )
        object.__setattr__(
            self, "filing_date", _optional_str(self.filing_date, max_len=32)
        )
        object.__setattr__(
            self, "as_of_utc", _optional_str(self.as_of_utc, max_len=64)
        )
        object.__setattr__(
            self,
            "authority_snapshot_id",
            _optional_str(self.authority_snapshot_id, max_len=256),
        )
        if self.authority_digest is not None:
            digest = str(self.authority_digest).strip().lower()
            if not _SHA256_RE.match(digest):
                raise SubmissionAssuranceError(
                    "authority_digest must be 64-char lowercase hex",
                    code="invalid_digest",
                )
            object.__setattr__(self, "authority_digest", digest)
        for flag_name in (
            "authority_stale",
            "force_proof_unknown",
            "force_review_required",
            "force_partial",
            "force_quarantine",
            "force_outage",
            "offline",
            "run_preflight",
        ):
            if not isinstance(getattr(self, flag_name), bool):
                raise TypeError(f"{flag_name} must be bool")
        if self.classification is None:
            object.__setattr__(self, "classification", None)
        else:
            object.__setattr__(
                self, "classification", _coerce_classification(self.classification)
            )
        object.__setattr__(self, "labels", _frozen_str_map(self.labels))
        inject = self.inject_failure_before
        if inject is not None and not isinstance(inject, AssuranceStage):
            object.__setattr__(
                self, "inject_failure_before", AssuranceStage(str(inject))
            )
        object.__setattr__(
            self, "delta_token", _optional_str(self.delta_token, max_len=128)
        )

    def documents_identity(self) -> list[dict[str, Any]]:
        return [d.identity_material() for d in self.documents]

    def to_dict(self) -> dict[str, Any]:
        return {
            "application_number": self.application_number,
            "application_type": (
                self.application_type.value
                if isinstance(self.application_type, ApplicationType)
                else str(self.application_type)
            ),
            "as_of_utc": self.as_of_utc,
            "assurance_id": self.assurance_id,
            "authority_digest": self.authority_digest,
            "authority_snapshot_id": self.authority_snapshot_id,
            "authority_stale": self.authority_stale,
            "classification": (
                self.classification.value
                if isinstance(self.classification, DisclosureClassification)
                else self.classification
            ),
            "delta_token": self.delta_token,
            "documents": [d.to_dict() for d in self.documents],
            "filing_date": self.filing_date,
            "force_outage": self.force_outage,
            "force_partial": self.force_partial,
            "force_proof_unknown": self.force_proof_unknown,
            "force_quarantine": self.force_quarantine,
            "force_review_required": self.force_review_required,
            "labels": dict(self.labels),
            "matter_id": self.matter_id,
            "offline": self.offline,
            "prosecution_stage": (
                self.prosecution_stage.value
                if isinstance(self.prosecution_stage, ProsecutionStage)
                else str(self.prosecution_stage)
            ),
            "run_preflight": self.run_preflight,
            "scenario": (
                self.scenario.value
                if isinstance(self.scenario, FilingScenario)
                else str(self.scenario)
            ),
            "source_profile": self.source_profile,
            "status_snapshot": dict(self.status_snapshot),
            "tenant_id": self.tenant_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SubmissionAssuranceInput":
        if not isinstance(value, Mapping):
            raise TypeError("SubmissionAssuranceInput must be a mapping")
        return cls(**{k: v for k, v in dict(value).items() if k in cls.__dataclass_fields__})  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Checkpoint / stage records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AssuranceStageCheckpoint:
    """Durable record for one committed (or terminal) assurance stage."""

    schema_version: str
    stage: AssuranceStage
    status: AssuranceStageStatus
    input_digest: str
    idempotency_key: str
    output_digest: str | None
    reason_codes: tuple[str, ...]
    diagnostics: Mapping[str, str]
    committed_utc: str | None
    attempt: int = 1
    stage_disposition: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "attempt": self.attempt,
            "committed_utc": self.committed_utc,
            "diagnostics": dict(self.diagnostics),
            "idempotency_key": self.idempotency_key,
            "input_digest": self.input_digest,
            "output_digest": self.output_digest,
            "reason_codes": list(self.reason_codes),
            "schema_version": self.schema_version,
            "stage": self.stage.value,
            "stage_disposition": self.stage_disposition,
            "status": self.status.value,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "AssuranceStageCheckpoint":
        return cls(
            schema_version=str(
                value.get("schema_version") or SUBMISSION_ASSURANCE_SCHEMA_VERSION
            ),
            stage=AssuranceStage(str(value.get("stage"))),
            status=AssuranceStageStatus(
                str(value.get("status", AssuranceStageStatus.PENDING.value))
            ),
            input_digest=str(value.get("input_digest") or ""),
            idempotency_key=str(value.get("idempotency_key") or ""),
            output_digest=_optional_str(value.get("output_digest"), max_len=64),
            reason_codes=tuple(str(r) for r in (value.get("reason_codes") or ())),
            diagnostics=_frozen_str_map(value.get("diagnostics") or {}),
            committed_utc=_optional_str(value.get("committed_utc"), max_len=64),
            attempt=int(value.get("attempt") or 1),
            stage_disposition=_optional_str(
                value.get("stage_disposition"), max_len=64
            ),
        )


@dataclass
class AssuranceCheckpoint:
    """Resumable assurance checkpoint (filesystem or in-memory)."""

    schema_version: str
    assurance_id: str
    tenant_id: str
    matter_id: str
    parser_digest: str
    stages: dict[str, AssuranceStageCheckpoint] = field(default_factory=dict)
    disposition: str | None = None
    classification: str | None = None
    reason_codes: list[str] = field(default_factory=list)
    created_utc: str | None = None
    updated_utc: str | None = None
    labels: dict[str, str] = field(default_factory=dict)
    delta_token: str | None = None
    dossier_id: str | None = None
    bundle_id: str | None = None
    stage_outputs: dict[str, dict[str, Any]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "assurance_id": self.assurance_id,
            "bundle_id": self.bundle_id,
            "classification": self.classification,
            "created_utc": self.created_utc,
            "delta_token": self.delta_token,
            "disposition": self.disposition,
            "dossier_id": self.dossier_id,
            "labels": dict(sorted(self.labels.items())),
            "matter_id": self.matter_id,
            "parser_digest": self.parser_digest,
            "reason_codes": list(self.reason_codes),
            "schema_version": self.schema_version,
            "stage_outputs": {
                k: dict(v) for k, v in sorted(self.stage_outputs.items())
            },
            "stages": {
                key: stage.to_dict() for key, stage in sorted(self.stages.items())
            },
            "tenant_id": self.tenant_id,
            "updated_utc": self.updated_utc,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "AssuranceCheckpoint":
        raw_stages = value.get("stages") or {}
        stages: dict[str, AssuranceStageCheckpoint] = {}
        if isinstance(raw_stages, Mapping):
            for key, raw in raw_stages.items():
                if isinstance(raw, Mapping):
                    stages[str(key)] = AssuranceStageCheckpoint.from_dict(raw)
        raw_outputs = value.get("stage_outputs") or {}
        outputs: dict[str, dict[str, Any]] = {}
        if isinstance(raw_outputs, Mapping):
            for key, raw in raw_outputs.items():
                if isinstance(raw, Mapping):
                    outputs[str(key)] = dict(raw)
        return cls(
            schema_version=str(
                value.get("schema_version") or SUBMISSION_ASSURANCE_SCHEMA_VERSION
            ),
            assurance_id=str(value.get("assurance_id") or ""),
            tenant_id=str(value.get("tenant_id") or ""),
            matter_id=str(value.get("matter_id") or ""),
            parser_digest=str(value.get("parser_digest") or ""),
            stages=stages,
            disposition=_optional_str(value.get("disposition"), max_len=64),
            classification=_optional_str(value.get("classification"), max_len=64),
            reason_codes=[str(r) for r in (value.get("reason_codes") or [])],
            created_utc=_optional_str(value.get("created_utc"), max_len=64),
            updated_utc=_optional_str(value.get("updated_utc"), max_len=64),
            labels={str(k): str(v) for k, v in (value.get("labels") or {}).items()},
            delta_token=_optional_str(value.get("delta_token"), max_len=128),
            dossier_id=_optional_str(value.get("dossier_id"), max_len=256),
            bundle_id=_optional_str(value.get("bundle_id"), max_len=256),
            stage_outputs=outputs,
        )

    def get_stage(self, stage: AssuranceStage) -> AssuranceStageCheckpoint | None:
        return self.stages.get(stage.value)

    def is_committed_with_digest(
        self, stage: AssuranceStage, input_digest: str
    ) -> bool:
        entry = self.get_stage(stage)
        return (
            entry is not None
            and entry.status is AssuranceStageStatus.COMMITTED
            and entry.input_digest == input_digest
        )

    def put_stage(self, entry: AssuranceStageCheckpoint) -> None:
        self.stages[entry.stage.value] = entry
        self.updated_utc = _utc_now()


@dataclass(frozen=True, slots=True)
class AssuranceStageRunRecord:
    """In-memory observation of a stage execution attempt (not durable)."""

    stage: AssuranceStage
    status: AssuranceStageStatus
    input_digest: str
    idempotency_key: str
    executed: bool
    resumed: bool
    reused_by_digest: bool
    reason_codes: tuple[str, ...]
    diagnostics: Mapping[str, str]
    output_digest: str | None = None
    stage_disposition: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "diagnostics": dict(self.diagnostics),
            "executed": self.executed,
            "idempotency_key": self.idempotency_key,
            "input_digest": self.input_digest,
            "output_digest": self.output_digest,
            "reason_codes": list(self.reason_codes),
            "resumed": self.resumed,
            "reused_by_digest": self.reused_by_digest,
            "stage": self.stage.value,
            "stage_disposition": self.stage_disposition,
            "status": self.status.value,
        }


@dataclass(frozen=True, slots=True)
class SubmissionAssuranceResult:
    """Domain outcome of a submission-assurance run.

    ``success`` / ``ok`` / ``domain_ok`` are True only for
    :attr:`AssuranceDisposition.COMPLETED`. Transport success is reported
    separately via :attr:`transport_ok` and never conceals quarantine, outage,
    incomplete analysis, or mandatory review.
    """

    schema_version: str
    assurance_id: str
    tenant_id: str
    matter_id: str
    disposition: AssuranceDisposition
    review_state: ReviewState
    classification: DisclosureClassification
    reason_codes: tuple[str, ...]
    stage_records: tuple[AssuranceStageRunRecord, ...]
    committed_stages: tuple[str, ...]
    resumed_stages: tuple[str, ...]
    executed_stages: tuple[str, ...]
    reused_stages: tuple[str, ...]
    parser_digest: str
    coverage: CoverageReport
    items: tuple[AssuranceItem, ...] = ()
    transport_ok: bool = True
    is_review_only: bool = True
    is_legal_advice: bool = False
    is_exhaustive: bool = False
    disclaimer: str = REVIEW_ONLY_ASSURANCE_DISCLAIMER
    stage_input_digests: Mapping[str, str] = MappingProxyType({})
    stage_output_digests: Mapping[str, str] = MappingProxyType({})
    dossier_id: str | None = None
    bundle_id: str | None = None
    bundle_digest: str | None = None
    analysis_id: str | None = None
    obligation_result_id: str | None = None
    delta_token: str | None = None
    is_delta: bool = False
    labels: Mapping[str, str] = MappingProxyType({})
    diagnostics: Mapping[str, str] = MappingProxyType({})
    interface: str = SUBMISSION_ASSURANCE_INTERFACE

    def __post_init__(self) -> None:
        if self.schema_version != SUBMISSION_ASSURANCE_SCHEMA_VERSION:
            raise ValueError(
                "SubmissionAssuranceResult.schema_version must be "
                f"{SUBMISSION_ASSURANCE_SCHEMA_VERSION}"
            )
        if not isinstance(self.coverage, CoverageReport):
            if isinstance(self.coverage, Mapping):
                object.__setattr__(
                    self, "coverage", CoverageReport.from_dict(self.coverage)
                )
            else:
                raise TypeError("coverage must be CoverageReport")
        if not isinstance(self.labels, MappingProxyType):
            object.__setattr__(self, "labels", _frozen_str_map(self.labels))
        if not isinstance(self.diagnostics, MappingProxyType):
            object.__setattr__(self, "diagnostics", _frozen_str_map(self.diagnostics))
        if not isinstance(self.stage_input_digests, MappingProxyType):
            object.__setattr__(
                self,
                "stage_input_digests",
                _frozen_str_map(self.stage_input_digests),
            )
        if not isinstance(self.stage_output_digests, MappingProxyType):
            object.__setattr__(
                self,
                "stage_output_digests",
                _frozen_str_map(self.stage_output_digests),
            )
        if not isinstance(self.items, tuple):
            object.__setattr__(self, "items", tuple(self.items or ()))

    @property
    def ok(self) -> bool:
        """Domain success: completed without fail-closed dispositions."""
        return (
            self.disposition is AssuranceDisposition.COMPLETED
            and self.transport_ok
            and not self.is_legal_advice
        )

    @property
    def success(self) -> bool:
        """Alias of :attr:`ok` — domain outcome, not exception absence."""
        return self.ok

    @property
    def domain_ok(self) -> bool:
        return self.ok

    @property
    def is_quarantined(self) -> bool:
        return self.disposition is AssuranceDisposition.QUARANTINED

    @property
    def is_partial(self) -> bool:
        return self.disposition is AssuranceDisposition.PARTIAL

    @property
    def is_stale_authority(self) -> bool:
        return self.disposition is AssuranceDisposition.STALE_AUTHORITY

    @property
    def is_proof_unknown(self) -> bool:
        return self.disposition is AssuranceDisposition.PROOF_UNKNOWN

    @property
    def is_review_required(self) -> bool:
        return self.disposition is AssuranceDisposition.REVIEW_REQUIRED

    @property
    def is_outage(self) -> bool:
        return self.disposition is AssuranceDisposition.OUTAGE

    def items_by_kind(self, kind: AssuranceItemKind | str) -> tuple[AssuranceItem, ...]:
        key = kind.value if isinstance(kind, AssuranceItemKind) else str(kind)
        return tuple(
            i
            for i in self.items
            if (
                i.kind.value
                if isinstance(i.kind, AssuranceItemKind)
                else str(i.kind)
            )
            == key
        )

    @property
    def satisfied_items(self) -> tuple[AssuranceItem, ...]:
        return self.items_by_kind(AssuranceItemKind.SATISFIED)

    @property
    def missing_items(self) -> tuple[AssuranceItem, ...]:
        return self.items_by_kind(AssuranceItemKind.MISSING)

    @property
    def contradictory_items(self) -> tuple[AssuranceItem, ...]:
        return self.items_by_kind(AssuranceItemKind.CONTRADICTORY)

    @property
    def unknown_items(self) -> tuple[AssuranceItem, ...]:
        return self.items_by_kind(AssuranceItemKind.UNKNOWN)

    @property
    def review_items(self) -> tuple[AssuranceItem, ...]:
        return self.items_by_kind(AssuranceItemKind.REVIEW)

    def to_dict(self) -> dict[str, Any]:
        return {
            "analysis_id": self.analysis_id,
            "assurance_id": self.assurance_id,
            "bundle_digest": self.bundle_digest,
            "bundle_id": self.bundle_id,
            "classification": self.classification.value,
            "committed_stages": list(self.committed_stages),
            "contradictory_items": [i.to_dict() for i in self.contradictory_items],
            "coverage": self.coverage.to_dict(),
            "delta_token": self.delta_token,
            "diagnostics": dict(self.diagnostics),
            "disclaimer": self.disclaimer,
            "disposition": self.disposition.value,
            "domain_ok": self.domain_ok,
            "dossier_id": self.dossier_id,
            "executed_stages": list(self.executed_stages),
            "interface": self.interface,
            "is_delta": self.is_delta,
            "is_exhaustive": self.is_exhaustive,
            "is_legal_advice": self.is_legal_advice,
            "is_outage": self.is_outage,
            "is_partial": self.is_partial,
            "is_proof_unknown": self.is_proof_unknown,
            "is_quarantined": self.is_quarantined,
            "is_review_only": self.is_review_only,
            "is_review_required": self.is_review_required,
            "is_stale_authority": self.is_stale_authority,
            "items": [i.to_dict() for i in self.items],
            "labels": dict(self.labels),
            "matter_id": self.matter_id,
            "missing_items": [i.to_dict() for i in self.missing_items],
            "obligation_result_id": self.obligation_result_id,
            "ok": self.ok,
            "parser_digest": self.parser_digest,
            "reason_codes": list(self.reason_codes),
            "resumed_stages": list(self.resumed_stages),
            "reused_stages": list(self.reused_stages),
            "review_items": [i.to_dict() for i in self.review_items],
            "review_state": self.review_state.value,
            "satisfied_items": [i.to_dict() for i in self.satisfied_items],
            "schema_version": self.schema_version,
            "stage_input_digests": dict(self.stage_input_digests),
            "stage_output_digests": dict(self.stage_output_digests),
            "stage_records": [r.to_dict() for r in self.stage_records],
            "success": self.success,
            "tenant_id": self.tenant_id,
            "transport_ok": self.transport_ok,
            "unknown_items": [i.to_dict() for i in self.unknown_items],
        }

    def public_projection(self) -> dict[str, Any]:
        """Safe projection: identifiers, digests, codes — never body text."""
        return self.to_dict()

    def to_canonical_json(self) -> str:
        return canonical_json(self.public_projection())


# ---------------------------------------------------------------------------
# Checkpoint store
# ---------------------------------------------------------------------------


class SubmissionAssuranceCheckpointStore:
    """Filesystem or in-memory atomic assurance checkpoint persistence."""

    def __init__(self, root: str | Path | None = None) -> None:
        self._root = Path(root) if root is not None else None
        self._memory: dict[str, AssuranceCheckpoint] = {}
        self._lock = threading.RLock()
        if self._root is not None:
            _ensure_dir(self._root)

    @property
    def root(self) -> Path | None:
        return self._root

    def _path_for(self, assurance_id: str) -> Path:
        assert self._root is not None
        return self._root / f"submission-assurance-{_safe_filename(assurance_id)}.json"

    def load(self, assurance_id: str) -> AssuranceCheckpoint | None:
        aid = _require_id(assurance_id, "assurance_id")
        with self._lock:
            if self._root is not None:
                path = self._path_for(aid)
                raw = _read_json(path)
                if raw is not None:
                    return AssuranceCheckpoint.from_dict(raw)
            return self._memory.get(aid)

    def save(self, checkpoint: AssuranceCheckpoint) -> None:
        with self._lock:
            checkpoint.updated_utc = _utc_now()
            self._memory[checkpoint.assurance_id] = checkpoint
            if self._root is None:
                return
            path = self._path_for(checkpoint.assurance_id)
            _atomic_write_json(path, checkpoint.to_dict())

    def delete(self, assurance_id: str) -> None:
        aid = _require_id(assurance_id, "assurance_id")
        with self._lock:
            self._memory.pop(aid, None)
            if self._root is not None:
                path = self._path_for(aid)
                if path.is_file():
                    path.unlink()


# ---------------------------------------------------------------------------
# Processor
# ---------------------------------------------------------------------------


StageHook = Callable[
    [AssuranceStage, "SubmissionAssuranceInput", AssuranceCheckpoint], None
]


@dataclass
class _StageOutcome:
    record: AssuranceStageRunRecord
    terminal_disposition: AssuranceDisposition | None = None
    output_summary: Mapping[str, Any] = field(default_factory=dict)
    items: tuple[AssuranceItem, ...] = ()
    transport_failed: bool = False


class SubmissionAssuranceProcessor:
    """One-shot and resumable submission-assurance orchestrator.

    Accepts tenant/matter plus authorized documents/status; runs matter
    analysis, filing-obligation resolution, compliance compare, coverage
    reporting, optional preflight, and redacted dossier export without requiring
    hand-built middle-stage objects.
    """

    schema_version: Final = SUBMISSION_ASSURANCE_SCHEMA_VERSION
    interface: Final = SUBMISSION_ASSURANCE_INTERFACE

    def __init__(
        self,
        *,
        checkpoint_store: SubmissionAssuranceCheckpointStore | None = None,
        matter_processor: MatterAnalysisProcessor | None = None,
        obligation_processor: FilingObligationProcessor | None = None,
        workflow_processor: WorkflowProcessor | None = None,
        id_factory: Callable[[], str] | None = None,
        stage_hook: StageHook | None = None,
        matter_checkpoint_root: str | Path | None = None,
    ) -> None:
        self._store = checkpoint_store or SubmissionAssuranceCheckpointStore()
        self._matter = matter_processor or create_matter_analysis_processor(
            checkpoint_dir=matter_checkpoint_root,
            id_factory=id_factory,
        )
        self._obligations = obligation_processor or FilingObligationProcessor(
            require_active_pack=True
        )
        self._workflow = workflow_processor or WorkflowProcessor(id_factory=id_factory)
        self._id_factory = id_factory or (lambda: f"assurance:{uuid.uuid4().hex}")
        self._stage_hook = stage_hook
        self._workspace: dict[str, Any] = {}
        self._execution_counts: MutableMapping[str, int] = {}

    @property
    def checkpoint_store(self) -> SubmissionAssuranceCheckpointStore:
        return self._store

    @property
    def execution_counts(self) -> Mapping[str, int]:
        return MappingProxyType(dict(self._execution_counts))

    def reset_execution_counts(self) -> None:
        self._execution_counts.clear()

    def assure(
        self,
        value: SubmissionAssuranceInput | Mapping[str, Any] | None = None,
        /,
        **kwargs: Any,
    ) -> SubmissionAssuranceResult:
        """Run or resume a checkpointed submission-assurance workflow."""
        inp = self._coerce_input(value, **kwargs)
        return self._assure(inp)

    def process(
        self,
        value: SubmissionAssuranceInput | Mapping[str, Any] | None = None,
        /,
        **kwargs: Any,
    ) -> SubmissionAssuranceResult:
        """Alias of :meth:`assure` for processor-adapter compatibility."""
        return self.assure(value, **kwargs)

    def assure_many(
        self, values: Iterable[SubmissionAssuranceInput | Mapping[str, Any]]
    ) -> list[SubmissionAssuranceResult]:
        return [self.assure(v) for v in values]

    # -- coercion -----------------------------------------------------------

    def _coerce_input(
        self,
        value: SubmissionAssuranceInput | Mapping[str, Any] | None,
        **kwargs: Any,
    ) -> SubmissionAssuranceInput:
        if value is None:
            return SubmissionAssuranceInput(**kwargs)
        if isinstance(value, SubmissionAssuranceInput):
            if not kwargs:
                return value
            data = value.to_dict()
            # documents need objects, not dicts for reconstruction
            data["documents"] = value.documents
            data.update(kwargs)
            return SubmissionAssuranceInput(**data)
        if isinstance(value, Mapping):
            data = dict(value)
            data.update(kwargs)
            return SubmissionAssuranceInput(**data)
        raise TypeError(
            "assure() expects SubmissionAssuranceInput, mapping, or kwargs"
        )

    # -- main orchestration -------------------------------------------------

    def _assure(self, inp: SubmissionAssuranceInput) -> SubmissionAssuranceResult:
        pdigest = parser_digest()
        assurance_id = inp.assurance_id or str(self._id_factory())
        is_delta = bool(inp.delta_token)

        class_values: list[DisclosureClassification] = []
        if inp.classification is not None:
            class_values.append(_coerce_classification(inp.classification))
        for doc in inp.documents:
            if doc.classification is not None:
                class_values.append(_coerce_classification(doc.classification))
        # Default is UNKNOWN → quarantine (not public_user).
        if not class_values:
            disclosure = DisclosureClassification.UNKNOWN
        else:
            disclosure = most_restrictive_classification(class_values)

        self._workspace = {
            "assurance_id": assurance_id,
            "tenant_id": inp.tenant_id,
            "matter_id": inp.matter_id,
            "disclosure": disclosure,
            "is_delta": is_delta,
            "delta_token": inp.delta_token,
            "matter_result": None,
            "obligation_result": None,
            "items": [],
            "coverage": None,
            "preflight": None,
            "dossier_id": None,
            "bundle_id": None,
            "bundle_digest": None,
            "analysis_id": None,
            "labels": dict(inp.labels),
            "stage_outputs": {},
            "partial_signals": [],
            "review_signals": [],
            "proof_unknown": False,
            "stale_authority": False,
            "quarantine_signals": [],
            "outage_signals": [],
            "transport_failed": False,
        }

        ckpt = self._store.load(assurance_id)
        if ckpt is None:
            ckpt = AssuranceCheckpoint(
                schema_version=SUBMISSION_ASSURANCE_SCHEMA_VERSION,
                assurance_id=assurance_id,
                tenant_id=inp.tenant_id,
                matter_id=inp.matter_id,
                parser_digest=pdigest,
                created_utc=_utc_now(),
                updated_utc=_utc_now(),
                labels=dict(inp.labels),
                delta_token=inp.delta_token,
            )
        else:
            if ckpt.matter_id and ckpt.matter_id != inp.matter_id:
                return self._terminal(
                    assurance_id=assurance_id,
                    inp=inp,
                    pdigest=pdigest,
                    disposition=AssuranceDisposition.FAILED,
                    reason_codes=(
                        AssuranceReasonCode.JOB_FAILED.value,
                        "matter_id_mismatch_on_resume",
                    ),
                    review_state=ReviewState.REQUIRED,
                    stage_records=(),
                    committed=(),
                    resumed=(),
                    executed=(),
                    reused=(),
                    input_digests={},
                    output_digests={},
                    coverage=CoverageReport(statuses={}),
                    items=(),
                    transport_ok=False,
                    ckpt=ckpt,
                    diagnostics={
                        "expected_matter_id": ckpt.matter_id,
                        "observed_matter_id": inp.matter_id,
                    },
                )
            if ckpt.tenant_id and ckpt.tenant_id != inp.tenant_id:
                return self._terminal(
                    assurance_id=assurance_id,
                    inp=inp,
                    pdigest=pdigest,
                    disposition=AssuranceDisposition.FAILED,
                    reason_codes=(
                        AssuranceReasonCode.JOB_FAILED.value,
                        "tenant_id_mismatch_on_resume",
                    ),
                    review_state=ReviewState.REQUIRED,
                    stage_records=(),
                    committed=(),
                    resumed=(),
                    executed=(),
                    reused=(),
                    input_digests={},
                    output_digests={},
                    coverage=CoverageReport(statuses={}),
                    items=(),
                    transport_ok=False,
                    ckpt=ckpt,
                    diagnostics={
                        "expected_tenant_id": ckpt.tenant_id,
                        "observed_tenant_id": inp.tenant_id,
                    },
                )
            self._workspace["stage_outputs"] = dict(ckpt.stage_outputs)
            if ckpt.dossier_id:
                self._workspace["dossier_id"] = ckpt.dossier_id
            if ckpt.bundle_id:
                self._workspace["bundle_id"] = ckpt.bundle_id

        stage_records: list[AssuranceStageRunRecord] = []
        committed: list[str] = []
        resumed: list[str] = []
        executed: list[str] = []
        reused: list[str] = []
        input_digests: dict[str, str] = {}
        output_digests: dict[str, str] = {}
        collected_items: list[AssuranceItem] = []
        reason_codes: list[str] = [
            AssuranceReasonCode.NOT_LEGAL_ADVICE.value,
            AssuranceReasonCode.NOT_EXHAUSTIVE.value,
            AssuranceReasonCode.REVIEW_ONLY.value,
            AssuranceReasonCode.NO_FILE_PAY_SIGN.value,
        ]
        if is_delta:
            reason_codes.append("delta_applied")

        early_disposition: AssuranceDisposition | None = None

        # Fail-closed force flags and quarantine before stages run.
        if inp.force_outage:
            self._workspace["outage_signals"].append("force_outage")
        if inp.force_quarantine or requires_quarantine(disclosure):
            self._workspace["quarantine_signals"].append("classification")
            reason_codes.append(AssuranceReasonCode.QUARANTINE_CLASSIFICATION.value)
        if disclosure is DisclosureClassification.UNKNOWN:
            self._workspace["quarantine_signals"].append("unknown_default")
            reason_codes.append(AssuranceReasonCode.QUARANTINE_CLASSIFICATION.value)
        if inp.authority_stale:
            self._workspace["stale_authority"] = True
            reason_codes.append(AssuranceReasonCode.STALE_AUTHORITY.value)
        if inp.force_proof_unknown:
            self._workspace["proof_unknown"] = True
            reason_codes.append(AssuranceReasonCode.PROOF_UNKNOWN.value)
        if inp.force_review_required:
            self._workspace["review_signals"].append("force_review")
            reason_codes.append(AssuranceReasonCode.REVIEW_REQUIRED.value)
        if inp.force_partial:
            self._workspace["partial_signals"].append("force_partial")
            reason_codes.append(AssuranceReasonCode.PARTIAL_COVERAGE.value)

        stage_runners: Mapping[
            AssuranceStage, Callable[[SubmissionAssuranceInput, str, str], _StageOutcome]
        ] = {
            AssuranceStage.AUTHORIZE: self._stage_authorize,
            AssuranceStage.MATTER_ANALYSIS: self._stage_matter_analysis,
            AssuranceStage.FILING_OBLIGATIONS: self._stage_filing_obligations,
            AssuranceStage.COMPLIANCE_COMPARE: self._stage_compliance_compare,
            AssuranceStage.COVERAGE: self._stage_coverage,
            AssuranceStage.PREFLIGHT: self._stage_preflight,
            AssuranceStage.DOSSIER_EXPORT: self._stage_dossier_export,
            AssuranceStage.FINALIZE: self._stage_finalize,
        }

        try:
            for stage in ASSURANCE_STAGE_ORDER:
                input_digest = self._stage_input_digest(stage, inp)
                input_digests[stage.value] = input_digest
                ikey = stage_idempotency_key(
                    assurance_id=assurance_id,
                    stage=stage,
                    input_digest=input_digest,
                    parser_digest_value=pdigest,
                )

                if self._stage_hook is not None:
                    self._stage_hook(stage, inp, ckpt)

                # Resume/reuse by matching input digest.
                if ckpt.is_committed_with_digest(stage, input_digest):
                    prior = ckpt.get_stage(stage)
                    assert prior is not None
                    record = AssuranceStageRunRecord(
                        stage=stage,
                        status=AssuranceStageStatus.SKIPPED,
                        input_digest=input_digest,
                        idempotency_key=ikey,
                        executed=False,
                        resumed=True,
                        reused_by_digest=True,
                        reason_codes=(
                            AssuranceReasonCode.STAGE_REUSED_BY_DIGEST.value,
                        ),
                        diagnostics=prior.diagnostics,
                        output_digest=prior.output_digest,
                        stage_disposition=prior.stage_disposition,
                    )
                    stage_records.append(record)
                    committed.append(stage.value)
                    resumed.append(stage.value)
                    reused.append(stage.value)
                    if prior.output_digest:
                        output_digests[stage.value] = prior.output_digest
                    # Hydrate items from prior stage outputs when present.
                    prior_out = ckpt.stage_outputs.get(stage.value) or {}
                    for raw_item in prior_out.get("items") or ():
                        if isinstance(raw_item, Mapping):
                            collected_items.append(AssuranceItem.from_dict(raw_item))
                    if stage is AssuranceStage.COVERAGE and prior_out.get("coverage"):
                        self._workspace["coverage"] = CoverageReport.from_dict(
                            prior_out["coverage"]
                        )
                    continue

                # Failure injection (tests).
                if (
                    inp.inject_failure_before is not None
                    and _coerce_stage(inp.inject_failure_before) is stage
                ):
                    raise InjectedAssuranceFailure(stage)

                self._execution_counts[stage.value] = (
                    self._execution_counts.get(stage.value, 0) + 1
                )
                outcome = stage_runners[stage](inp, input_digest, ikey)
                stage_records.append(outcome.record)
                executed.append(stage.value)

                if outcome.record.status is AssuranceStageStatus.COMMITTED:
                    committed.append(stage.value)
                    if outcome.record.output_digest:
                        output_digests[stage.value] = outcome.record.output_digest
                    summary = dict(outcome.output_summary)
                    if outcome.items:
                        summary["items"] = [i.to_dict() for i in outcome.items]
                        collected_items.extend(outcome.items)
                    if "coverage" in summary:
                        self._workspace["coverage"] = CoverageReport.from_dict(
                            summary["coverage"]
                        )
                    ckpt.stage_outputs[stage.value] = summary
                    self._workspace["stage_outputs"][stage.value] = summary
                    ckpt.put_stage(
                        AssuranceStageCheckpoint(
                            schema_version=SUBMISSION_ASSURANCE_SCHEMA_VERSION,
                            stage=stage,
                            status=AssuranceStageStatus.COMMITTED,
                            input_digest=input_digest,
                            idempotency_key=ikey,
                            output_digest=outcome.record.output_digest,
                            reason_codes=outcome.record.reason_codes,
                            diagnostics=outcome.record.diagnostics,
                            committed_utc=_utc_now(),
                            stage_disposition=outcome.record.stage_disposition,
                        )
                    )
                    self._store.save(ckpt)
                else:
                    # Stage failed / quarantined.
                    ckpt.put_stage(
                        AssuranceStageCheckpoint(
                            schema_version=SUBMISSION_ASSURANCE_SCHEMA_VERSION,
                            stage=stage,
                            status=outcome.record.status,
                            input_digest=input_digest,
                            idempotency_key=ikey,
                            output_digest=outcome.record.output_digest,
                            reason_codes=outcome.record.reason_codes,
                            diagnostics=outcome.record.diagnostics,
                            committed_utc=_utc_now(),
                            stage_disposition=outcome.record.stage_disposition,
                        )
                    )
                    self._store.save(ckpt)

                if outcome.transport_failed:
                    self._workspace["transport_failed"] = True
                if outcome.terminal_disposition is not None:
                    early_disposition = outcome.terminal_disposition
                    reason_codes.extend(outcome.record.reason_codes)
                    break
                reason_codes.extend(
                    r
                    for r in outcome.record.reason_codes
                    if r not in reason_codes
                )

        except InjectedAssuranceFailure as exc:
            self._workspace["transport_failed"] = True
            stage_records.append(
                AssuranceStageRunRecord(
                    stage=exc.stage,
                    status=AssuranceStageStatus.FAILED,
                    input_digest=input_digests.get(exc.stage.value, ""),
                    idempotency_key=stage_idempotency_key(
                        assurance_id=assurance_id,
                        stage=exc.stage,
                        input_digest=input_digests.get(exc.stage.value, ""),
                        parser_digest_value=pdigest,
                    ),
                    executed=False,
                    resumed=False,
                    reused_by_digest=False,
                    reason_codes=(AssuranceReasonCode.INJECTED_FAILURE.value,),
                    diagnostics=MappingProxyType({"injected": "true"}),
                )
            )
            return self._terminal(
                assurance_id=assurance_id,
                inp=inp,
                pdigest=pdigest,
                disposition=AssuranceDisposition.INTERRUPTED,
                reason_codes=tuple(
                    list(dict.fromkeys(reason_codes + [AssuranceReasonCode.JOB_INTERRUPTED.value]))
                ),
                review_state=ReviewState.REQUIRED,
                stage_records=tuple(stage_records),
                committed=tuple(committed),
                resumed=tuple(resumed),
                executed=tuple(executed),
                reused=tuple(reused),
                input_digests=input_digests,
                output_digests=output_digests,
                coverage=self._workspace.get("coverage")
                or CoverageReport(statuses={}),
                items=tuple(collected_items[:_MAX_ITEMS]),
                transport_ok=False,
                ckpt=ckpt,
                diagnostics={"injected_stage": exc.stage.value},
            )
        except Exception as exc:
            self._workspace["transport_failed"] = True
            code = getattr(exc, "code", None) or type(exc).__name__
            return self._terminal(
                assurance_id=assurance_id,
                inp=inp,
                pdigest=pdigest,
                disposition=AssuranceDisposition.OUTAGE
                if "timeout" in str(exc).lower() or "outage" in str(code).lower()
                else AssuranceDisposition.FAILED,
                reason_codes=tuple(
                    list(
                        dict.fromkeys(
                            reason_codes
                            + [
                                AssuranceReasonCode.JOB_FAILED.value,
                                AssuranceReasonCode.TRANSPORT_FAILED.value,
                                str(code)[:64],
                            ]
                        )
                    )
                ),
                review_state=ReviewState.REQUIRED,
                stage_records=tuple(stage_records),
                committed=tuple(committed),
                resumed=tuple(resumed),
                executed=tuple(executed),
                reused=tuple(reused),
                input_digests=input_digests,
                output_digests=output_digests,
                coverage=self._workspace.get("coverage")
                or CoverageReport(statuses={}),
                items=tuple(collected_items[:_MAX_ITEMS]),
                transport_ok=False,
                ckpt=ckpt,
                diagnostics={"error_type": type(exc).__name__},
            )

        disposition = early_disposition or self._resolve_disposition(inp)
        if disposition is AssuranceDisposition.COMPLETED:
            reason_codes.append(AssuranceReasonCode.JOB_COMPLETED.value)
            reason_codes.append(AssuranceReasonCode.DOMAIN_SUCCESS.value)
            reason_codes.append(AssuranceReasonCode.TRANSPORT_OK.value)
            job_code = AssuranceReasonCode.JOB_COMPLETED.value
        else:
            reason_codes.append(AssuranceReasonCode.DOMAIN_NON_SUCCESS.value)
            job_map = {
                AssuranceDisposition.PARTIAL: AssuranceReasonCode.JOB_PARTIAL,
                AssuranceDisposition.QUARANTINED: AssuranceReasonCode.JOB_QUARANTINED,
                AssuranceDisposition.STALE_AUTHORITY: AssuranceReasonCode.JOB_STALE_AUTHORITY,
                AssuranceDisposition.PROOF_UNKNOWN: AssuranceReasonCode.JOB_PROOF_UNKNOWN,
                AssuranceDisposition.REVIEW_REQUIRED: AssuranceReasonCode.JOB_REVIEW_REQUIRED,
                AssuranceDisposition.OUTAGE: AssuranceReasonCode.JOB_OUTAGE,
                AssuranceDisposition.FAILED: AssuranceReasonCode.JOB_FAILED,
                AssuranceDisposition.INTERRUPTED: AssuranceReasonCode.JOB_INTERRUPTED,
            }
            job_code = job_map.get(
                disposition, AssuranceReasonCode.JOB_FAILED
            ).value
            reason_codes.append(job_code)

        transport_ok = not bool(self._workspace.get("transport_failed"))
        if transport_ok:
            if AssuranceReasonCode.TRANSPORT_OK.value not in reason_codes:
                reason_codes.append(AssuranceReasonCode.TRANSPORT_OK.value)
        else:
            reason_codes.append(AssuranceReasonCode.TRANSPORT_FAILED.value)

        review_state = (
            ReviewState.NOT_REQUIRED
            if disposition is AssuranceDisposition.COMPLETED
            else ReviewState.REQUIRED
        )
        coverage = self._workspace.get("coverage") or CoverageReport(statuses={})

        # Deduplicate reason codes while preserving order.
        reason_codes = list(dict.fromkeys(reason_codes))[:_MAX_REASON_CODES]

        # Deduplicate items by item_id.
        seen_ids: set[str] = set()
        unique_items: list[AssuranceItem] = []
        for item in collected_items:
            if item.item_id in seen_ids:
                continue
            seen_ids.add(item.item_id)
            unique_items.append(item)

        result = self._terminal(
            assurance_id=assurance_id,
            inp=inp,
            pdigest=pdigest,
            disposition=disposition,
            reason_codes=tuple(reason_codes),
            review_state=review_state,
            stage_records=tuple(stage_records),
            committed=tuple(committed),
            resumed=tuple(resumed),
            executed=tuple(executed),
            reused=tuple(reused),
            input_digests=input_digests,
            output_digests=output_digests,
            coverage=coverage,
            items=tuple(unique_items[:_MAX_ITEMS]),
            transport_ok=transport_ok,
            ckpt=ckpt,
            diagnostics={
                "source_profile": inp.source_profile,
                "job_code": job_code,
            },
        )
        return result

    def _resolve_disposition(
        self, inp: SubmissionAssuranceInput
    ) -> AssuranceDisposition:
        """Derive terminal domain disposition from workspace signals (fail-closed)."""
        if self._workspace.get("outage_signals") or inp.force_outage:
            return AssuranceDisposition.OUTAGE
        if self._workspace.get("quarantine_signals") or inp.force_quarantine:
            return AssuranceDisposition.QUARANTINED
        if self._workspace.get("stale_authority") or inp.authority_stale:
            return AssuranceDisposition.STALE_AUTHORITY
        if self._workspace.get("proof_unknown") or inp.force_proof_unknown:
            return AssuranceDisposition.PROOF_UNKNOWN
        if self._workspace.get("review_signals") or inp.force_review_required:
            return AssuranceDisposition.REVIEW_REQUIRED
        if self._workspace.get("partial_signals") or inp.force_partial:
            return AssuranceDisposition.PARTIAL
        # Blocking missing/contradictory items force review (not silent success).
        items: Sequence[AssuranceItem] = self._workspace.get("items") or ()
        for item in items:
            if item.blocking and item.kind in (
                AssuranceItemKind.MISSING,
                AssuranceItemKind.CONTRADICTORY,
                AssuranceItemKind.UNKNOWN,
                AssuranceItemKind.REVIEW,
            ):
                return AssuranceDisposition.REVIEW_REQUIRED
        # Matter analysis non-success propagates.
        matter: MatterAnalysisResult | None = self._workspace.get("matter_result")
        if matter is not None and not matter.success:
            mapping = {
                MatterAnalysisDisposition.PARTIAL: AssuranceDisposition.PARTIAL,
                MatterAnalysisDisposition.QUARANTINED: AssuranceDisposition.QUARANTINED,
                MatterAnalysisDisposition.STALE_AUTHORITY: AssuranceDisposition.STALE_AUTHORITY,
                MatterAnalysisDisposition.PROOF_UNKNOWN: AssuranceDisposition.PROOF_UNKNOWN,
                MatterAnalysisDisposition.REVIEW_REQUIRED: AssuranceDisposition.REVIEW_REQUIRED,
                MatterAnalysisDisposition.FAILED: AssuranceDisposition.FAILED,
                MatterAnalysisDisposition.INTERRUPTED: AssuranceDisposition.INTERRUPTED,
            }
            return mapping.get(matter.disposition, AssuranceDisposition.PARTIAL)
        return AssuranceDisposition.COMPLETED

    def _terminal(
        self,
        *,
        assurance_id: str,
        inp: SubmissionAssuranceInput,
        pdigest: str,
        disposition: AssuranceDisposition,
        reason_codes: tuple[str, ...],
        review_state: ReviewState,
        stage_records: tuple[AssuranceStageRunRecord, ...],
        committed: tuple[str, ...],
        resumed: tuple[str, ...],
        executed: tuple[str, ...],
        reused: tuple[str, ...],
        input_digests: Mapping[str, str],
        output_digests: Mapping[str, str],
        coverage: CoverageReport,
        items: tuple[AssuranceItem, ...],
        transport_ok: bool,
        ckpt: AssuranceCheckpoint,
        diagnostics: Mapping[str, str] | None = None,
    ) -> SubmissionAssuranceResult:
        disclosure = self._workspace.get("disclosure") or DisclosureClassification.UNKNOWN
        if not isinstance(disclosure, DisclosureClassification):
            disclosure = _coerce_classification(disclosure)

        ckpt.disposition = disposition.value
        ckpt.classification = disclosure.value
        ckpt.reason_codes = list(reason_codes)
        ckpt.dossier_id = self._workspace.get("dossier_id")
        ckpt.bundle_id = self._workspace.get("bundle_id")
        ckpt.delta_token = inp.delta_token
        self._store.save(ckpt)

        return SubmissionAssuranceResult(
            schema_version=SUBMISSION_ASSURANCE_SCHEMA_VERSION,
            assurance_id=assurance_id,
            tenant_id=inp.tenant_id,
            matter_id=inp.matter_id,
            disposition=disposition,
            review_state=review_state,
            classification=disclosure,
            reason_codes=reason_codes,
            stage_records=stage_records,
            committed_stages=committed,
            resumed_stages=resumed,
            executed_stages=executed,
            reused_stages=reused,
            parser_digest=pdigest,
            coverage=coverage,
            items=items,
            transport_ok=transport_ok,
            is_review_only=True,
            is_legal_advice=False,
            is_exhaustive=False,
            disclaimer=REVIEW_ONLY_ASSURANCE_DISCLAIMER,
            stage_input_digests=dict(input_digests),
            stage_output_digests=dict(output_digests),
            dossier_id=self._workspace.get("dossier_id"),
            bundle_id=self._workspace.get("bundle_id"),
            bundle_digest=self._workspace.get("bundle_digest"),
            analysis_id=self._workspace.get("analysis_id"),
            obligation_result_id=self._workspace.get("obligation_result_id"),
            delta_token=inp.delta_token,
            is_delta=bool(inp.delta_token),
            labels=dict(inp.labels),
            diagnostics=dict(diagnostics or {}),
        )

    # -- stage input digests ------------------------------------------------

    def _stage_input_digest(
        self, stage: AssuranceStage, inp: SubmissionAssuranceInput
    ) -> str:
        base = {
            "assurance_id": self._workspace.get("assurance_id"),
            "matter_id": inp.matter_id,
            "stage": stage.value,
            "tenant_id": inp.tenant_id,
        }
        if stage is AssuranceStage.AUTHORIZE:
            material = {
                **base,
                "classification": (
                    self._workspace["disclosure"].value
                    if isinstance(
                        self._workspace.get("disclosure"), DisclosureClassification
                    )
                    else str(self._workspace.get("disclosure"))
                ),
                "source_profile": inp.source_profile,
            }
        elif stage is AssuranceStage.MATTER_ANALYSIS:
            material = {
                **base,
                "authority_digest": inp.authority_digest,
                "authority_snapshot_id": inp.authority_snapshot_id,
                "authority_stale": inp.authority_stale,
                "documents": inp.documents_identity(),
                "force_partial": inp.force_partial,
                "force_proof_unknown": inp.force_proof_unknown,
                "force_quarantine": inp.force_quarantine,
                "force_review_required": inp.force_review_required,
                "status_snapshot_keys": sorted(str(k) for k in inp.status_snapshot),
            }
        elif stage is AssuranceStage.FILING_OBLIGATIONS:
            material = {
                **base,
                "application_type": (
                    inp.application_type.value
                    if isinstance(inp.application_type, ApplicationType)
                    else str(inp.application_type)
                ),
                "filing_date": inp.filing_date,
                "scenario": (
                    inp.scenario.value
                    if isinstance(inp.scenario, FilingScenario)
                    else str(inp.scenario)
                ),
            }
        elif stage is AssuranceStage.COMPLIANCE_COMPARE:
            # Digest is input-stable so resume can reuse without hydrated
            # intermediate obligation digests in the workspace.
            material = {
                **base,
                "application_type": (
                    inp.application_type.value
                    if isinstance(inp.application_type, ApplicationType)
                    else str(inp.application_type)
                ),
                "documents": inp.documents_identity(),
                "scenario": (
                    inp.scenario.value
                    if isinstance(inp.scenario, FilingScenario)
                    else str(inp.scenario)
                ),
            }
        elif stage is AssuranceStage.COVERAGE:
            material = {
                **base,
                "authority_digest": inp.authority_digest,
                "authority_snapshot_id": inp.authority_snapshot_id,
                "authority_stale": inp.authority_stale,
                "documents": inp.documents_identity(),
                "force_partial": inp.force_partial,
                "force_proof_unknown": inp.force_proof_unknown,
                "offline": inp.offline,
            }
        elif stage is AssuranceStage.PREFLIGHT:
            material = {
                **base,
                "run_preflight": inp.run_preflight,
            }
        elif stage is AssuranceStage.DOSSIER_EXPORT:
            material = {
                **base,
                "documents": inp.documents_identity(),
            }
        else:  # FINALIZE
            material = {
                **base,
                "documents": inp.documents_identity(),
                "source_profile": inp.source_profile,
            }
        return _canonical_digest(material)

    # -- stages -------------------------------------------------------------

    def _stage_authorize(
        self, inp: SubmissionAssuranceInput, input_digest: str, ikey: str
    ) -> _StageOutcome:
        reasons = [AssuranceReasonCode.AUTHORIZED.value]
        if not inp.tenant_id:
            return _StageOutcome(
                record=AssuranceStageRunRecord(
                    stage=AssuranceStage.AUTHORIZE,
                    status=AssuranceStageStatus.FAILED,
                    input_digest=input_digest,
                    idempotency_key=ikey,
                    executed=True,
                    resumed=False,
                    reused_by_digest=False,
                    reason_codes=(AssuranceReasonCode.MISSING_TENANT.value,),
                    diagnostics=MappingProxyType({}),
                ),
                terminal_disposition=AssuranceDisposition.FAILED,
            )
        if not inp.matter_id:
            return _StageOutcome(
                record=AssuranceStageRunRecord(
                    stage=AssuranceStage.AUTHORIZE,
                    status=AssuranceStageStatus.FAILED,
                    input_digest=input_digest,
                    idempotency_key=ikey,
                    executed=True,
                    resumed=False,
                    reused_by_digest=False,
                    reason_codes=(AssuranceReasonCode.MISSING_MATTER.value,),
                    diagnostics=MappingProxyType({}),
                ),
                terminal_disposition=AssuranceDisposition.FAILED,
            )
        if not inp.source_profile:
            return _StageOutcome(
                record=AssuranceStageRunRecord(
                    stage=AssuranceStage.AUTHORIZE,
                    status=AssuranceStageStatus.FAILED,
                    input_digest=input_digest,
                    idempotency_key=ikey,
                    executed=True,
                    resumed=False,
                    reused_by_digest=False,
                    reason_codes=(AssuranceReasonCode.MISSING_SOURCE_PROFILE.value,),
                    diagnostics=MappingProxyType({}),
                ),
                terminal_disposition=AssuranceDisposition.FAILED,
            )
        if inp.force_outage:
            self._workspace["outage_signals"].append("authorize")
            return _StageOutcome(
                record=AssuranceStageRunRecord(
                    stage=AssuranceStage.AUTHORIZE,
                    status=AssuranceStageStatus.FAILED,
                    input_digest=input_digest,
                    idempotency_key=ikey,
                    executed=True,
                    resumed=False,
                    reused_by_digest=False,
                    reason_codes=(
                        AssuranceReasonCode.OUTAGE.value,
                        AssuranceReasonCode.TRANSPORT_FAILED.value,
                    ),
                    diagnostics=MappingProxyType({"outage": "forced"}),
                ),
                terminal_disposition=AssuranceDisposition.OUTAGE,
                transport_failed=True,
            )

        disclosure = self._workspace["disclosure"]
        quarantine = requires_quarantine(disclosure) or (
            disclosure is DisclosureClassification.UNKNOWN
        )
        stage_disp = "quarantined" if quarantine else "authorized"
        if quarantine:
            self._workspace["quarantine_signals"].append("authorize")
            reasons.append(AssuranceReasonCode.QUARANTINE_CLASSIFICATION.value)

        summary = {
            "classification": (
                disclosure.value
                if isinstance(disclosure, DisclosureClassification)
                else str(disclosure)
            ),
            "output_digest": input_digest,
            "source_profile": inp.source_profile,
            "stage_disposition": stage_disp,
        }
        return _StageOutcome(
            record=AssuranceStageRunRecord(
                stage=AssuranceStage.AUTHORIZE,
                status=AssuranceStageStatus.COMMITTED,
                input_digest=input_digest,
                idempotency_key=ikey,
                executed=True,
                resumed=False,
                reused_by_digest=False,
                reason_codes=tuple(reasons),
                diagnostics=_frozen_str_map(
                    {
                        "classification": summary["classification"],
                        "source_profile": inp.source_profile,
                    }
                ),
                output_digest=input_digest,
                stage_disposition=stage_disp,
            ),
            # Quarantine does not abort the pipeline; disposition is resolved
            # at the end so coverage and item lists still materialize.
            output_summary=summary,
        )

    def _stage_matter_analysis(
        self, inp: SubmissionAssuranceInput, input_digest: str, ikey: str
    ) -> _StageOutcome:
        analysis_id = f"analysis:{self._workspace['assurance_id']}"
        # Matter analysis defaults public when omitted; pass explicit
        # classification from assurance (may be UNKNOWN for quarantine).
        disclosure = self._workspace["disclosure"]
        matter_input = MatterAnalysisInput(
            tenant_id=inp.tenant_id,
            matter_id=inp.matter_id,
            analysis_id=analysis_id,
            application_number=inp.application_number,
            documents=inp.documents,
            status_snapshot=dict(inp.status_snapshot),
            as_of_utc=inp.as_of_utc,
            authority_snapshot_id=inp.authority_snapshot_id,
            authority_digest=inp.authority_digest,
            authority_stale=inp.authority_stale,
            force_proof_unknown=inp.force_proof_unknown,
            force_review_required=inp.force_review_required,
            force_partial=inp.force_partial,
            force_quarantine=inp.force_quarantine
            or disclosure is DisclosureClassification.UNKNOWN,
            classification=disclosure,
            labels={**dict(inp.labels), "assurance_id": self._workspace["assurance_id"]},
            offline=inp.offline,
        )
        try:
            matter_result = self._matter.analyze(matter_input)
        except Exception as exc:
            self._workspace["transport_failed"] = True
            self._workspace["outage_signals"].append("matter_analysis")
            return _StageOutcome(
                record=AssuranceStageRunRecord(
                    stage=AssuranceStage.MATTER_ANALYSIS,
                    status=AssuranceStageStatus.FAILED,
                    input_digest=input_digest,
                    idempotency_key=ikey,
                    executed=True,
                    resumed=False,
                    reused_by_digest=False,
                    reason_codes=(
                        AssuranceReasonCode.OUTAGE.value,
                        AssuranceReasonCode.TRANSPORT_FAILED.value,
                    ),
                    diagnostics=_frozen_str_map(
                        {"error_type": type(exc).__name__}
                    ),
                ),
                terminal_disposition=AssuranceDisposition.OUTAGE,
                transport_failed=True,
            )

        self._workspace["matter_result"] = matter_result
        self._workspace["analysis_id"] = matter_result.analysis_id
        self._workspace["dossier_id"] = matter_result.dossier_id
        self._workspace["bundle_id"] = matter_result.bundle_id
        self._workspace["bundle_digest"] = matter_result.bundle_digest

        reasons = [AssuranceReasonCode.MATTER_ANALYSIS_COMPLETED.value]
        if not matter_result.success:
            reasons.append(AssuranceReasonCode.MATTER_ANALYSIS_NON_SUCCESS.value)
            if matter_result.is_quarantined:
                self._workspace["quarantine_signals"].append("matter_analysis")
            if matter_result.is_partial:
                self._workspace["partial_signals"].append("matter_analysis")
            if matter_result.is_stale_authority:
                self._workspace["stale_authority"] = True
            if matter_result.is_proof_unknown:
                self._workspace["proof_unknown"] = True
            if matter_result.is_review_required:
                self._workspace["review_signals"].append("matter_analysis")

        out_digest = matter_result.bundle_digest or _canonical_digest(
            matter_result.public_projection()
        )
        summary = {
            "analysis_id": matter_result.analysis_id,
            "bundle_digest": matter_result.bundle_digest,
            "bundle_id": matter_result.bundle_id,
            "disposition": matter_result.disposition.value,
            "dossier_id": matter_result.dossier_id,
            "output_digest": out_digest,
            "success": matter_result.success,
        }
        return _StageOutcome(
            record=AssuranceStageRunRecord(
                stage=AssuranceStage.MATTER_ANALYSIS,
                status=AssuranceStageStatus.COMMITTED,
                input_digest=input_digest,
                idempotency_key=ikey,
                executed=True,
                resumed=False,
                reused_by_digest=False,
                reason_codes=tuple(reasons),
                diagnostics=_frozen_str_map(
                    {
                        "analysis_id": matter_result.analysis_id or "",
                        "disposition": matter_result.disposition.value,
                        "success": str(matter_result.success).lower(),
                    }
                ),
                output_digest=out_digest,
                stage_disposition=matter_result.disposition.value,
            ),
            output_summary=summary,
        )

    def _stage_filing_obligations(
        self, inp: SubmissionAssuranceInput, input_digest: str, ikey: str
    ) -> _StageOutcome:
        request_id = f"fob:{self._workspace['assurance_id']}"
        disclosure = self._workspace["disclosure"]
        request = FilingObligationRequest(
            request_id=request_id,
            application_type=inp.application_type,
            scenario=inp.scenario,
            filing_date=inp.filing_date
            or (inp.as_of_utc[:10] if inp.as_of_utc and len(inp.as_of_utc) >= 10 else None),
            as_of=inp.filing_date
            or (inp.as_of_utc[:10] if inp.as_of_utc and len(inp.as_of_utc) >= 10 else None),
            prosecution_stage=inp.prosecution_stage,
            matter_id=inp.matter_id,
            classification=disclosure
            if isinstance(disclosure, DisclosureClassification)
            else DisclosureClassification.UNKNOWN,
        )
        try:
            result = self._obligations.process(request)
        except Exception as exc:
            self._workspace["partial_signals"].append("filing_obligations")
            item = AssuranceItem(
                item_id=f"item:obligation-error:{self._workspace['assurance_id']}",
                kind=AssuranceItemKind.UNKNOWN,
                title="Filing obligation resolution incomplete",
                description=(
                    "Baseline filing-obligation pack could not be resolved; "
                    "coverage is unknown (not a silent pass)."
                ),
                provenance=(
                    ProvenanceRef(
                        kind="stage",
                        ref_id="filing_obligations",
                        labels={"error_type": type(exc).__name__},
                    ),
                ),
                dimension=CoverageDimension.COMPLIANCE,
                blocking=True,
            )
            self._workspace.setdefault("items", []).append(item)
            out_digest = _canonical_digest({"error": type(exc).__name__})
            return _StageOutcome(
                record=AssuranceStageRunRecord(
                    stage=AssuranceStage.FILING_OBLIGATIONS,
                    status=AssuranceStageStatus.COMMITTED,
                    input_digest=input_digest,
                    idempotency_key=ikey,
                    executed=True,
                    resumed=False,
                    reused_by_digest=False,
                    reason_codes=(
                        AssuranceReasonCode.PARTIAL_COVERAGE.value,
                        AssuranceReasonCode.OBLIGATIONS_RESOLVED.value,
                    ),
                    diagnostics=_frozen_str_map(
                        {"error_type": type(exc).__name__}
                    ),
                    output_digest=out_digest,
                    stage_disposition="partial",
                ),
                output_summary={"output_digest": out_digest, "status": "error"},
                items=(item,),
            )

        self._workspace["obligation_result"] = result
        self._workspace["obligation_result_id"] = result.result_id
        reasons = [
            AssuranceReasonCode.OBLIGATIONS_RESOLVED.value,
            AssuranceReasonCode.REVIEW_ONLY.value,
        ]
        if result.status is not ObligationResolutionStatus.MATCHED:
            self._workspace["partial_signals"].append("obligation_status")
            reasons.append(AssuranceReasonCode.PARTIAL_COVERAGE.value)
        if result.coverage_gaps:
            self._workspace["review_signals"].append("coverage_gaps")
            reasons.append(AssuranceReasonCode.REVIEW_REQUIRED.value)

        items: list[AssuranceItem] = []
        for gap in result.coverage_gaps:
            items.append(
                AssuranceItem(
                    item_id=f"item:gap:{gap.gap_id}",
                    kind=AssuranceItemKind.REVIEW
                    if gap.blocking
                    else AssuranceItemKind.UNKNOWN,
                    title=f"Coverage gap: {gap.kind.value if hasattr(gap.kind, 'value') else gap.kind}",
                    description=gap.description,
                    provenance=(
                        ProvenanceRef(
                            kind="coverage_gap",
                            ref_id=gap.gap_id,
                            labels={
                                "application_type": (
                                    gap.application_type.value
                                    if hasattr(gap.application_type, "value")
                                    else str(gap.application_type)
                                ),
                                "scenario": (
                                    gap.scenario.value
                                    if hasattr(gap.scenario, "value")
                                    else str(gap.scenario)
                                ),
                            },
                        ),
                    ),
                    dimension=CoverageDimension.COMPLIANCE,
                    blocking=bool(gap.blocking),
                )
            )

        # Always emit a review-only disclaimer item.
        items.append(
            AssuranceItem(
                item_id=f"item:disclaimer:{result.result_id}",
                kind=AssuranceItemKind.REVIEW,
                title="Review-only decision support",
                description=REVIEW_ONLY_OBLIGATION_DISCLAIMER[:512],
                provenance=(
                    ProvenanceRef(
                        kind="obligation_result",
                        ref_id=result.result_id,
                        digest=result.pack_content_digest or None,
                        rule_id=result.pack_id,
                    ),
                ),
                dimension=CoverageDimension.COMPLIANCE,
                blocking=False,
                labels={"is_legal_advice": "false"},
            )
        )

        self._workspace.setdefault("items", []).extend(items)
        out_digest = _canonical_digest(
            {
                "matched": len(result.matched_obligations),
                "pack_digest": result.pack_content_digest,
                "result_id": result.result_id,
                "status": (
                    result.status.value
                    if isinstance(result.status, ObligationResolutionStatus)
                    else str(result.status)
                ),
            }
        )
        summary = {
            "gaps": len(result.coverage_gaps),
            "matched": len(result.matched_obligations),
            "output_digest": out_digest,
            "pack_id": result.pack_id,
            "result_id": result.result_id,
            "status": (
                result.status.value
                if isinstance(result.status, ObligationResolutionStatus)
                else str(result.status)
            ),
        }
        return _StageOutcome(
            record=AssuranceStageRunRecord(
                stage=AssuranceStage.FILING_OBLIGATIONS,
                status=AssuranceStageStatus.COMMITTED,
                input_digest=input_digest,
                idempotency_key=ikey,
                executed=True,
                resumed=False,
                reused_by_digest=False,
                reason_codes=tuple(reasons),
                diagnostics=_frozen_str_map(
                    {
                        "matched": str(len(result.matched_obligations)),
                        "result_id": result.result_id,
                        "status": summary["status"],
                    }
                ),
                output_digest=out_digest,
                stage_disposition=summary["status"],
            ),
            output_summary=summary,
            items=tuple(items),
        )

    def _stage_compliance_compare(
        self, inp: SubmissionAssuranceInput, input_digest: str, ikey: str
    ) -> _StageOutcome:
        """Compare admitted submission documents against matched obligations."""
        obligation: FilingObligationResult | None = self._workspace.get(
            "obligation_result"
        )
        items: list[AssuranceItem] = []
        doc_kinds: dict[str, list[MatterDocumentInput]] = {}
        for doc in inp.documents:
            for ek in _evidence_kinds_for_role(doc.role):
                doc_kinds.setdefault(ek, []).append(doc)
            # Also index by raw role.
            doc_kinds.setdefault(doc.role.lower(), []).append(doc)

        if obligation is None:
            item = AssuranceItem(
                item_id=f"item:compare-no-obligations:{self._workspace['assurance_id']}",
                kind=AssuranceItemKind.UNKNOWN,
                title="No obligations available for comparison",
                description=(
                    "Compliance compare skipped because filing obligations "
                    "were not resolved."
                ),
                provenance=(
                    ProvenanceRef(
                        kind="stage",
                        ref_id="compliance_compare",
                    ),
                ),
                dimension=CoverageDimension.COMPLIANCE,
                blocking=True,
            )
            items.append(item)
            self._workspace["partial_signals"].append("compliance_compare")
        else:
            for match in obligation.matched_obligations:
                rule = match.rule
                rule_id = rule.rule_id
                for evidence in rule.required_evidence:
                    ek = (
                        evidence.evidence_kind.value
                        if isinstance(evidence.evidence_kind, EvidenceKind)
                        else str(evidence.evidence_kind)
                    )
                    candidates = doc_kinds.get(ek) or ()
                    # Soft match: ADS/form roles, specification text presence.
                    if not candidates and ek == EvidenceKind.ADS.value:
                        candidates = doc_kinds.get("form") or doc_kinds.get("ads") or ()
                    if not candidates and ek == EvidenceKind.SPECIFICATION.value:
                        candidates = [
                            d
                            for d in inp.documents
                            if d.role.lower() in {"specification", "spec"}
                            or (d.text and "specification" in (d.text or "").lower()[:200])
                        ]
                    if not candidates and ek == EvidenceKind.CLAIMS.value:
                        candidates = [
                            d
                            for d in inp.documents
                            if d.role.lower() in {"claims", "claim", "claim_set"}
                            or (d.text and "claim" in (d.text or "").lower()[:200])
                        ]
                    if not candidates and ek == EvidenceKind.REMARKS.value:
                        candidates = [
                            d
                            for d in inp.documents
                            if d.role.lower() in {"remarks", "amendment"}
                        ]

                    if candidates:
                        docs = list(candidates)
                        prov = tuple(
                            ProvenanceRef(
                                kind="document",
                                ref_id=d.document_id,
                                digest=d.content_sha256,
                                rule_id=rule_id,
                                labels={"role": d.role, "evidence_kind": ek},
                            )
                            for d in docs[:8]
                        )
                        # Contradictory: multiple conflicting digests for same kind.
                        digests = {d.content_sha256 for d in docs if d.content_sha256}
                        if len(digests) > 3 and evidence.mandatory:
                            kind = AssuranceItemKind.CONTRADICTORY
                            title = f"Contradictory evidence for {ek}"
                            desc = (
                                f"Multiple distinct artifacts ({len(digests)}) "
                                f"present for mandatory evidence {ek} under "
                                f"rule {rule_id}."
                            )
                            blocking = True
                            self._workspace["review_signals"].append(
                                f"contradictory:{ek}"
                            )
                        else:
                            kind = AssuranceItemKind.SATISFIED
                            title = f"Satisfied: {ek}"
                            desc = (
                                f"Evidence kind {ek} matched for obligation "
                                f"{rule_id}: {evidence.description[:200]}"
                            )
                            blocking = False
                        items.append(
                            AssuranceItem(
                                item_id=f"item:ev:{rule_id}:{ek}",
                                kind=kind,
                                title=title,
                                description=desc,
                                provenance=prov,
                                dimension=CoverageDimension.COMPLIANCE,
                                obligation_rule_id=rule_id,
                                evidence_kind=ek,
                                blocking=blocking,
                            )
                        )
                    else:
                        if evidence.mandatory:
                            kind = AssuranceItemKind.MISSING
                            blocking = True
                            self._workspace["review_signals"].append(f"missing:{ek}")
                        else:
                            kind = AssuranceItemKind.UNKNOWN
                            blocking = False
                            # Optional gaps are inventory only; they must not
                            # force partial disposition by themselves.
                        items.append(
                            AssuranceItem(
                                item_id=f"item:ev:{rule_id}:{ek}",
                                kind=kind,
                                title=f"{'Missing' if evidence.mandatory else 'Unknown'}: {ek}",
                                description=(
                                    f"{'Mandatory' if evidence.mandatory else 'Optional'} "
                                    f"evidence kind {ek} for rule {rule_id} not found among "
                                    f"admitted documents: {evidence.description[:200]}"
                                ),
                                provenance=(
                                    ProvenanceRef(
                                        kind="obligation_rule",
                                        ref_id=rule_id,
                                        rule_id=rule_id,
                                        labels={
                                            "evidence_kind": ek,
                                            "mandatory": str(evidence.mandatory).lower(),
                                        },
                                    ),
                                ),
                                dimension=CoverageDimension.COMPLIANCE,
                                obligation_rule_id=rule_id,
                                evidence_kind=ek,
                                blocking=blocking,
                            )
                        )

        # If no documents at all, mark extraction/compliance unknown.
        if not inp.documents:
            items.append(
                AssuranceItem(
                    item_id=f"item:no-docs:{self._workspace['assurance_id']}",
                    kind=AssuranceItemKind.UNKNOWN,
                    title="No admitted submission documents",
                    description=(
                        "No documents were provided in the authorized source "
                        "profile; extraction and compliance coverage remain unknown."
                    ),
                    provenance=(
                        ProvenanceRef(
                            kind="source_profile",
                            ref_id=inp.source_profile,
                        ),
                    ),
                    dimension=CoverageDimension.EXTRACTION,
                    blocking=True,
                )
            )
            self._workspace["partial_signals"].append("no_documents")

        self._workspace["items"] = list(self._workspace.get("items") or []) + items
        out_digest = _canonical_digest(
            {
                "item_ids": [i.item_id for i in items],
                "kinds": [
                    i.kind.value if isinstance(i.kind, AssuranceItemKind) else str(i.kind)
                    for i in items
                ],
            }
        )
        summary = {
            "item_count": len(items),
            "missing": sum(
                1 for i in items if i.kind is AssuranceItemKind.MISSING
            ),
            "output_digest": out_digest,
            "satisfied": sum(
                1 for i in items if i.kind is AssuranceItemKind.SATISFIED
            ),
        }
        return _StageOutcome(
            record=AssuranceStageRunRecord(
                stage=AssuranceStage.COMPLIANCE_COMPARE,
                status=AssuranceStageStatus.COMMITTED,
                input_digest=input_digest,
                idempotency_key=ikey,
                executed=True,
                resumed=False,
                reused_by_digest=False,
                reason_codes=(AssuranceReasonCode.COMPLIANCE_COMPARED.value,),
                diagnostics=_frozen_str_map(
                    {
                        "item_count": str(len(items)),
                        "missing": str(summary["missing"]),
                        "satisfied": str(summary["satisfied"]),
                    }
                ),
                output_digest=out_digest,
                stage_disposition="compared",
            ),
            output_summary=summary,
            items=tuple(items),
        )

    def _stage_coverage(
        self, inp: SubmissionAssuranceInput, input_digest: str, ikey: str
    ) -> _StageOutcome:
        matter: MatterAnalysisResult | None = self._workspace.get("matter_result")
        items: Sequence[AssuranceItem] = self._workspace.get("items") or ()
        statuses: dict[str, str] = {}
        notes: dict[str, str] = {}

        # SYNC
        if self._workspace.get("outage_signals"):
            statuses[CoverageDimension.SYNC.value] = CoverageStatus.OUTAGE.value
            notes[CoverageDimension.SYNC.value] = "outage_signal"
        elif matter is not None and matter.success:
            statuses[CoverageDimension.SYNC.value] = CoverageStatus.COVERED.value
            notes[CoverageDimension.SYNC.value] = "matter_analysis_ok"
        elif matter is not None:
            statuses[CoverageDimension.SYNC.value] = CoverageStatus.PARTIAL.value
            notes[CoverageDimension.SYNC.value] = matter.disposition.value
        elif inp.offline and inp.status_snapshot:
            statuses[CoverageDimension.SYNC.value] = CoverageStatus.COVERED.value
            notes[CoverageDimension.SYNC.value] = "offline_status_snapshot"
        else:
            statuses[CoverageDimension.SYNC.value] = CoverageStatus.UNKNOWN.value
            notes[CoverageDimension.SYNC.value] = "no_sync_evidence"

        # EXTRACTION
        if not inp.documents:
            statuses[CoverageDimension.EXTRACTION.value] = CoverageStatus.MISSING.value
            notes[CoverageDimension.EXTRACTION.value] = "no_documents"
        elif matter is not None and MatterAnalysisDisposition.PARTIAL is matter.disposition:
            statuses[CoverageDimension.EXTRACTION.value] = CoverageStatus.PARTIAL.value
            notes[CoverageDimension.EXTRACTION.value] = "matter_partial"
        else:
            statuses[CoverageDimension.EXTRACTION.value] = CoverageStatus.COVERED.value
            notes[CoverageDimension.EXTRACTION.value] = f"documents={len(inp.documents)}"

        # AUTHORITY
        if inp.authority_stale or self._workspace.get("stale_authority"):
            statuses[CoverageDimension.AUTHORITY.value] = CoverageStatus.FAILED.value
            notes[CoverageDimension.AUTHORITY.value] = "stale_authority"
        elif inp.authority_snapshot_id or inp.authority_digest:
            statuses[CoverageDimension.AUTHORITY.value] = CoverageStatus.COVERED.value
            notes[CoverageDimension.AUTHORITY.value] = (
                inp.authority_snapshot_id or "digest_bound"
            )
        else:
            statuses[CoverageDimension.AUTHORITY.value] = CoverageStatus.UNKNOWN.value
            notes[CoverageDimension.AUTHORITY.value] = "no_authority_snapshot"

        # PROOF
        if self._workspace.get("proof_unknown") or inp.force_proof_unknown:
            statuses[CoverageDimension.PROOF.value] = CoverageStatus.UNKNOWN.value
            notes[CoverageDimension.PROOF.value] = "proof_unknown"
        elif matter is not None and matter.is_proof_unknown:
            statuses[CoverageDimension.PROOF.value] = CoverageStatus.UNKNOWN.value
            notes[CoverageDimension.PROOF.value] = "matter_proof_unknown"
        elif matter is not None and matter.success:
            statuses[CoverageDimension.PROOF.value] = CoverageStatus.COVERED.value
            notes[CoverageDimension.PROOF.value] = "matter_ok"
        else:
            statuses[CoverageDimension.PROOF.value] = CoverageStatus.PARTIAL.value
            notes[CoverageDimension.PROOF.value] = "proof_not_confirmed"

        # COMPLIANCE
        missing = sum(1 for i in items if i.kind is AssuranceItemKind.MISSING and i.blocking)
        contradictory = sum(
            1 for i in items if i.kind is AssuranceItemKind.CONTRADICTORY
        )
        if contradictory:
            statuses[CoverageDimension.COMPLIANCE.value] = CoverageStatus.FAILED.value
            notes[CoverageDimension.COMPLIANCE.value] = f"contradictory={contradictory}"
        elif missing:
            statuses[CoverageDimension.COMPLIANCE.value] = CoverageStatus.MISSING.value
            notes[CoverageDimension.COMPLIANCE.value] = f"missing={missing}"
        elif any(i.kind is AssuranceItemKind.UNKNOWN and i.blocking for i in items):
            statuses[CoverageDimension.COMPLIANCE.value] = CoverageStatus.UNKNOWN.value
            notes[CoverageDimension.COMPLIANCE.value] = "blocking_unknown"
        elif any(i.kind is AssuranceItemKind.SATISFIED for i in items):
            statuses[CoverageDimension.COMPLIANCE.value] = CoverageStatus.COVERED.value
            notes[CoverageDimension.COMPLIANCE.value] = "obligations_compared"
        else:
            statuses[CoverageDimension.COMPLIANCE.value] = CoverageStatus.PARTIAL.value
            notes[CoverageDimension.COMPLIANCE.value] = "no_satisfied_items"

        # Only outage / failed / mandatory missing on core dimensions escalate.
        for dim, status in statuses.items():
            if status == CoverageStatus.OUTAGE.value:
                self._workspace["outage_signals"].append(f"coverage:{dim}")
            elif status == CoverageStatus.FAILED.value:
                self._workspace["review_signals"].append(f"coverage:{dim}")
            elif (
                status == CoverageStatus.MISSING.value
                and dim
                in {
                    CoverageDimension.EXTRACTION.value,
                    CoverageDimension.COMPLIANCE.value,
                }
            ):
                self._workspace["partial_signals"].append(f"coverage:{dim}")

        coverage = CoverageReport(statuses=statuses, notes=notes)
        self._workspace["coverage"] = coverage
        out_digest = _canonical_digest(coverage.to_dict())
        return _StageOutcome(
            record=AssuranceStageRunRecord(
                stage=AssuranceStage.COVERAGE,
                status=AssuranceStageStatus.COMMITTED,
                input_digest=input_digest,
                idempotency_key=ikey,
                executed=True,
                resumed=False,
                reused_by_digest=False,
                reason_codes=(AssuranceReasonCode.COVERAGE_COMPUTED.value,),
                diagnostics=_frozen_str_map(statuses),
                output_digest=out_digest,
                stage_disposition="computed",
            ),
            output_summary={
                "coverage": coverage.to_dict(),
                "output_digest": out_digest,
            },
        )

    def _stage_preflight(
        self, inp: SubmissionAssuranceInput, input_digest: str, ikey: str
    ) -> _StageOutcome:
        if not inp.run_preflight:
            summary = {"output_digest": input_digest, "skipped": True}
            return _StageOutcome(
                record=AssuranceStageRunRecord(
                    stage=AssuranceStage.PREFLIGHT,
                    status=AssuranceStageStatus.COMMITTED,
                    input_digest=input_digest,
                    idempotency_key=ikey,
                    executed=True,
                    resumed=False,
                    reused_by_digest=False,
                    reason_codes=(AssuranceReasonCode.PREFLIGHT_EVALUATED.value,),
                    diagnostics=MappingProxyType({"skipped": "true"}),
                    output_digest=input_digest,
                    stage_disposition="skipped",
                ),
                output_summary=summary,
            )

        # Build a minimal preflight package from assurance outputs when
        # available; skip gracefully if the package contract cannot be met.
        items: list[AssuranceItem] = []
        preflight_disposition = "not_run"
        try:
            bundle_id = self._workspace.get("bundle_id") or (
                f"bundle:{self._workspace['assurance_id']}"
            )
            # Prefer calling workflow only when a full package is supplied via
            # labels; otherwise emit a review item that preflight is incomplete.
            package_json = (inp.labels or {}).get("preflight_package_json")
            if package_json:
                raw = json.loads(package_json)
                pkg = PreflightPackageInput.from_dict(raw)
                pf: PreflightResult = self._workflow.run_preflight(pkg)
                self._workspace["preflight"] = pf
                preflight_disposition = getattr(
                    getattr(pf, "disposition", None), "value", str(getattr(pf, "disposition", "unknown"))
                )
                if not getattr(pf, "ok", getattr(pf, "success", False)):
                    self._workspace["review_signals"].append("preflight")
                    items.append(
                        AssuranceItem(
                            item_id=f"item:preflight:{self._workspace['assurance_id']}",
                            kind=AssuranceItemKind.REVIEW,
                            title="Preflight requires human review",
                            description=(
                                "Package preflight did not clear all gates; "
                                "human review is required before external handoff."
                            ),
                            provenance=(
                                ProvenanceRef(
                                    kind="preflight",
                                    ref_id=getattr(pf, "result_id", bundle_id),
                                    labels={"disposition": str(preflight_disposition)},
                                ),
                            ),
                            dimension=CoverageDimension.COMPLIANCE,
                            blocking=True,
                        )
                    )
            else:
                # No hand-built package: record that preflight is review-gated.
                self._workspace["review_signals"].append("preflight_not_cleared")
                preflight_disposition = "review_required"
                items.append(
                    AssuranceItem(
                        item_id=f"item:preflight-gate:{self._workspace['assurance_id']}",
                        kind=AssuranceItemKind.REVIEW,
                        title="Preflight gate open",
                        description=(
                            "Submission-assurance preflight remains open until "
                            "named human review binds immutable package digests. "
                            "This processor never files, pays, or signs."
                        ),
                        provenance=(
                            ProvenanceRef(
                                kind="bundle",
                                ref_id=str(bundle_id),
                                digest=self._workspace.get("bundle_digest"),
                            ),
                        ),
                        dimension=CoverageDimension.COMPLIANCE,
                        blocking=True,
                    )
                )
        except Exception as exc:
            self._workspace["partial_signals"].append("preflight_error")
            preflight_disposition = "error"
            items.append(
                AssuranceItem(
                    item_id=f"item:preflight-error:{self._workspace['assurance_id']}",
                    kind=AssuranceItemKind.UNKNOWN,
                    title="Preflight evaluation incomplete",
                    description=(
                        "Preflight could not be fully evaluated; status is "
                        "unknown rather than success."
                    ),
                    provenance=(
                        ProvenanceRef(
                            kind="stage",
                            ref_id="preflight",
                            labels={"error_type": type(exc).__name__},
                        ),
                    ),
                    dimension=CoverageDimension.COMPLIANCE,
                    blocking=True,
                )
            )

        self._workspace.setdefault("items", []).extend(items)
        out_digest = _canonical_digest(
            {
                "disposition": preflight_disposition,
                "item_ids": [i.item_id for i in items],
            }
        )
        return _StageOutcome(
            record=AssuranceStageRunRecord(
                stage=AssuranceStage.PREFLIGHT,
                status=AssuranceStageStatus.COMMITTED,
                input_digest=input_digest,
                idempotency_key=ikey,
                executed=True,
                resumed=False,
                reused_by_digest=False,
                reason_codes=(
                    AssuranceReasonCode.PREFLIGHT_EVALUATED.value,
                    AssuranceReasonCode.NO_FILE_PAY_SIGN.value,
                ),
                diagnostics=_frozen_str_map(
                    {"disposition": str(preflight_disposition)}
                ),
                output_digest=out_digest,
                stage_disposition=str(preflight_disposition),
            ),
            output_summary={
                "disposition": preflight_disposition,
                "output_digest": out_digest,
            },
            items=tuple(items),
        )

    def _stage_dossier_export(
        self, inp: SubmissionAssuranceInput, input_digest: str, ikey: str
    ) -> _StageOutcome:
        """Export a redacted assurance dossier projection (no private body text)."""
        dossier_id = (
            self._workspace.get("dossier_id")
            or f"dossier:assurance:{self._workspace['assurance_id']}"
        )
        self._workspace["dossier_id"] = dossier_id
        bundle_id = self._workspace.get("bundle_id") or (
            f"bundle:assurance:{self._workspace['assurance_id']}"
        )
        self._workspace["bundle_id"] = bundle_id

        redacted = {
            "analysis_id": self._workspace.get("analysis_id"),
            "assurance_id": self._workspace["assurance_id"],
            "bundle_id": bundle_id,
            "classification": (
                self._workspace["disclosure"].value
                if isinstance(
                    self._workspace.get("disclosure"), DisclosureClassification
                )
                else str(self._workspace.get("disclosure"))
            ),
            "coverage": (
                self._workspace["coverage"].to_dict()
                if isinstance(self._workspace.get("coverage"), CoverageReport)
                else {}
            ),
            "disclaimer": REVIEW_ONLY_ASSURANCE_DISCLAIMER,
            "document_ids": [d.document_id for d in inp.documents],
            "dossier_id": dossier_id,
            "is_legal_advice": False,
            "is_review_only": True,
            "item_ids": [
                i.item_id for i in (self._workspace.get("items") or ())
            ],
            "matter_id": inp.matter_id,
            "obligation_result_id": self._workspace.get("obligation_result_id"),
            "tenant_id": inp.tenant_id,
        }
        out_digest = _canonical_digest(redacted)
        self._workspace["bundle_digest"] = (
            self._workspace.get("bundle_digest") or out_digest
        )
        summary = {
            "bundle_digest": self._workspace["bundle_digest"],
            "bundle_id": bundle_id,
            "dossier_id": dossier_id,
            "output_digest": out_digest,
            "redacted": True,
        }
        return _StageOutcome(
            record=AssuranceStageRunRecord(
                stage=AssuranceStage.DOSSIER_EXPORT,
                status=AssuranceStageStatus.COMMITTED,
                input_digest=input_digest,
                idempotency_key=ikey,
                executed=True,
                resumed=False,
                reused_by_digest=False,
                reason_codes=(AssuranceReasonCode.DOSSIER_EXPORTED.value,),
                diagnostics=_frozen_str_map(
                    {
                        "bundle_id": str(bundle_id),
                        "dossier_id": str(dossier_id),
                        "redacted": "true",
                    }
                ),
                output_digest=out_digest,
                stage_disposition="exported",
            ),
            output_summary=summary,
        )

    def _stage_finalize(
        self, inp: SubmissionAssuranceInput, input_digest: str, ikey: str
    ) -> _StageOutcome:
        summary = {
            "output_digest": input_digest,
            "stages": list(ASSURANCE_STAGE_ORDER[-1:]),
        }
        return _StageOutcome(
            record=AssuranceStageRunRecord(
                stage=AssuranceStage.FINALIZE,
                status=AssuranceStageStatus.COMMITTED,
                input_digest=input_digest,
                idempotency_key=ikey,
                executed=True,
                resumed=False,
                reused_by_digest=False,
                reason_codes=(AssuranceReasonCode.FINALIZED.value,),
                diagnostics=MappingProxyType({}),
                output_digest=input_digest,
                stage_disposition="finalized",
            ),
            output_summary=summary,
        )


# ---------------------------------------------------------------------------
# Public factories
# ---------------------------------------------------------------------------


def create_submission_assurance_processor(
    *,
    checkpoint_dir: str | Path | None = None,
    matter_checkpoint_root: str | Path | None = None,
    **kwargs: Any,
) -> SubmissionAssuranceProcessor:
    """Create a :class:`SubmissionAssuranceProcessor` with optional FS checkpoints."""
    store = SubmissionAssuranceCheckpointStore(root=checkpoint_dir)
    return SubmissionAssuranceProcessor(
        checkpoint_store=store,
        matter_checkpoint_root=matter_checkpoint_root,
        **kwargs,
    )


def assure_submission(
    value: SubmissionAssuranceInput | Mapping[str, Any] | None = None,
    /,
    **kwargs: Any,
) -> SubmissionAssuranceResult:
    """One-shot helper that constructs a default processor and runs assurance."""
    return SubmissionAssuranceProcessor().assure(value, **kwargs)


__all__ = [
    "ASSURANCE_STAGE_ORDER",
    "AssuranceDisposition",
    "AssuranceItem",
    "AssuranceItemKind",
    "AssuranceReasonCode",
    "AssuranceStage",
    "AssuranceStageCheckpoint",
    "AssuranceStageRunRecord",
    "AssuranceStageStatus",
    "AssuranceCheckpoint",
    "CoverageDimension",
    "CoverageReport",
    "CoverageStatus",
    "InjectedAssuranceFailure",
    "ProvenanceRef",
    "REVIEW_ONLY_ASSURANCE_DISCLAIMER",
    "SUBMISSION_ASSURANCE_INTERFACE",
    "SUBMISSION_ASSURANCE_SCHEMA_VERSION",
    "SubmissionAssuranceCheckpointStore",
    "SubmissionAssuranceError",
    "SubmissionAssuranceInput",
    "SubmissionAssuranceProcessor",
    "SubmissionAssuranceResult",
    "assert_assurance_action_allowed",
    "assure_submission",
    "create_submission_assurance_processor",
    "parser_digest",
    "sha256_hex",
    "stage_idempotency_key",
]
