"""Resumable end-to-end USPTO matter analysis orchestration (PATLAW-136).

Composes acquisition/sync, document processing, office-action and submission
semantics, as-of authority selection, legal/logic checks, candidate dates,
dossier assembly, and analysis-bundle publication into one restartable
processor.

Design invariants
-----------------
* Stages form an ordered DAG committed under deterministic idempotency keys
  that include the stage **input digest**. Unchanged stages are reused when
  the input digest matches a committed checkpoint entry (resume *and* later
  deltas).
* Retries resume exactly: committed stages are not re-executed; incomplete
  stages re-run after injected or process failures.
* Domain ``success`` / ``ok`` is True only for a completed analysis with no
  partial, quarantine, stale-authority, proof-unknown, or review-required
  disposition. Those states always surface on the top-level result.
* Leaf processors are called through their public contracts. This module does
  not perform filing, payment, signature, or legal-strategy selection.
* Checkpoints store digests, statuses, and reason codes — never private
  document body text.
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

from .analysis.analysis_bundle import (
    ANALYSIS_BUNDLE_SCHEMA_VERSION,
    BundleDisposition,
    BundleSectionKind,
    BundleSectionRef,
    BundleWarning,
    BundleWarningCode,
    UsptoAnalysisBundle,
    build_analysis_bundle,
    content_digest_of,
)
from .analysis.deadline_processor import (
    DEADLINE_SCHEMA_VERSION,
    DeadlineAnalysisInput,
    DeadlineAnalysisResult,
    DeadlineDisposition,
    DeadlineProcessor,
    DeadlineSourceInput,
    PeriodUnit,
)
from .analysis.legal_ir_proof_executor import (
    LEGAL_IR_PROOF_EXECUTOR_SCHEMA_VERSION,
    FixtureKind,
    LegalIRProofExecutor,
    ProofOutcome,
    build_fixture_problem,
)
from .analysis.office_action_semantics_v2 import (
    SEMANTICS_V2_SCHEMA_VERSION as OA_SEMANTICS_SCHEMA_VERSION,
    OfficeActionSemanticsInput,
    OfficeActionSemanticsResult,
    OfficeActionSemanticsV2,
    SemanticsDisposition,
)
from .analysis.semantic_compliance_processor import (
    SEMANTIC_COMPLIANCE_SCHEMA_VERSION,
    SemanticComplianceProcessor,
)
from .analysis.semantic_instruction_consistency_processor import (
    SEMANTIC_INSTRUCTION_CONSISTENCY_SCHEMA_VERSION,
    SemanticInstructionConsistencyProcessor,
)
from .analysis.submission_package_semantics_v2 import (
    SEMANTICS_V2_SCHEMA_VERSION as PKG_SEMANTICS_SCHEMA_VERSION,
    DocumentRole,
    PackageDocumentInput,
    PackageDisposition,
    SubmissionPackageInput,
    SubmissionPackageSemanticsResult,
    SubmissionPackageSemanticsV2,
)
from .contracts import (
    CONTRACTS_SCHEMA_VERSION,
    DisclosureClassification,
    ReviewState,
    canonical_json,
    most_restrictive_classification,
    requires_quarantine,
)
from .document_pipeline_processor import (
    DOCUMENT_PIPELINE_SCHEMA_VERSION,
    DocumentPipelineInput,
    DocumentPipelineJobStore,
    DocumentPipelineProcessor,
    DocumentPipelineResult,
    PipelineDisposition,
)
from .dossier_processor import (
    DOSSIER_SCHEMA_VERSION,
    ApplicationDossier,
    CompactSectionInput,
    DossierDisposition,
    DossierInput,
    DossierProcessor,
)

# ---------------------------------------------------------------------------
# Versions / interface
# ---------------------------------------------------------------------------

MATTER_ANALYSIS_SCHEMA_VERSION: Final = "uspto.matter-analysis.v1"
MATTER_ANALYSIS_INTERFACE: Final = "MatterAnalysisProcessor@1"
MATTER_ANALYSIS_PARSER_DIGEST_MATERIAL: Final = (
    f"{MATTER_ANALYSIS_SCHEMA_VERSION}|"
    f"{CONTRACTS_SCHEMA_VERSION}|"
    f"{DOCUMENT_PIPELINE_SCHEMA_VERSION}|"
    f"{OA_SEMANTICS_SCHEMA_VERSION}|"
    f"{PKG_SEMANTICS_SCHEMA_VERSION}|"
    f"{SEMANTIC_COMPLIANCE_SCHEMA_VERSION}|"
    f"{SEMANTIC_INSTRUCTION_CONSISTENCY_SCHEMA_VERSION}|"
    f"{DEADLINE_SCHEMA_VERSION}|"
    f"{LEGAL_IR_PROOF_EXECUTOR_SCHEMA_VERSION}|"
    f"{DOSSIER_SCHEMA_VERSION}|"
    f"{ANALYSIS_BUNDLE_SCHEMA_VERSION}"
)

_DIRECTORY_MODE: Final = 0o700
_FILE_MODE: Final = 0o600
_ID_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._:/=+\-]{0,255}\Z")
_SHA256_RE = re.compile(r"\A[0-9a-f]{64}\Z")
_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._\-]+")
_MAX_REASON_CODES: Final = 64
_MAX_DOCUMENTS: Final = 64
_MAX_TEXT_CHARS: Final = 256_000


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class MatterAnalysisStage(str, Enum):
    """Ordered stages of the matter analysis DAG."""

    AUTHORIZE = "authorize"
    STATUS_SYNC = "status_sync"
    DOCUMENT_SYNC = "document_sync"
    DOCUMENT_PROCESS = "document_process"
    OFFICE_ACTION_SEMANTICS = "office_action_semantics"
    SUBMISSION_SEMANTICS = "submission_semantics"
    AUTHORITY_VIEW = "authority_view"
    LEGAL_LOGIC = "legal_logic"
    TEMPORAL_CANDIDATES = "temporal_candidates"
    DOSSIER = "dossier"
    BUNDLE = "bundle"


MATTER_ANALYSIS_STAGE_ORDER: Final[tuple[MatterAnalysisStage, ...]] = (
    MatterAnalysisStage.AUTHORIZE,
    MatterAnalysisStage.STATUS_SYNC,
    MatterAnalysisStage.DOCUMENT_SYNC,
    MatterAnalysisStage.DOCUMENT_PROCESS,
    MatterAnalysisStage.OFFICE_ACTION_SEMANTICS,
    MatterAnalysisStage.SUBMISSION_SEMANTICS,
    MatterAnalysisStage.AUTHORITY_VIEW,
    MatterAnalysisStage.LEGAL_LOGIC,
    MatterAnalysisStage.TEMPORAL_CANDIDATES,
    MatterAnalysisStage.DOSSIER,
    MatterAnalysisStage.BUNDLE,
)


class StageStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMMITTED = "committed"
    SKIPPED = "skipped"  # reused by matching input digest
    FAILED = "failed"
    QUARANTINED = "quarantined"


class MatterAnalysisDisposition(str, Enum):
    """Terminal domain outcome for a matter analysis run.

    Non-success dispositions must never collapse to unconditional success.
    """

    COMPLETED = "completed"
    PARTIAL = "partial"
    QUARANTINED = "quarantined"
    STALE_AUTHORITY = "stale_authority"
    PROOF_UNKNOWN = "proof_unknown"
    REVIEW_REQUIRED = "review_required"
    FAILED = "failed"
    INTERRUPTED = "interrupted"


class MatterAnalysisReasonCode(str, Enum):
    STAGE_COMMITTED = "stage_committed"
    STAGE_RESUMED = "stage_resumed"
    STAGE_REUSED_BY_DIGEST = "stage_reused_by_digest"
    AUTHORIZED = "authorized"
    STATUS_SYNCED = "status_synced"
    DOCUMENTS_SYNCED = "documents_synced"
    DOCUMENTS_PROCESSED = "documents_processed"
    OFFICE_ACTION_PARSED = "office_action_parsed"
    SUBMISSION_PARSED = "submission_parsed"
    AUTHORITY_VIEW_SELECTED = "authority_view_selected"
    LEGAL_LOGIC_EVALUATED = "legal_logic_evaluated"
    TEMPORAL_CANDIDATES_COMPUTED = "temporal_candidates_computed"
    DOSSIER_ASSEMBLED = "dossier_assembled"
    BUNDLE_ASSEMBLED = "bundle_assembled"
    PARTIAL_COVERAGE = "partial_coverage"
    QUARANTINE_CLASSIFICATION = "quarantine_classification"
    QUARANTINE_POLICY = "quarantine_policy"
    STALE_AUTHORITY = "stale_authority"
    PROOF_UNKNOWN = "proof_unknown"
    REVIEW_REQUIRED = "review_required"
    MISSING_MATTER = "missing_matter"
    MISSING_TENANT = "missing_tenant"
    INJECTED_FAILURE = "injected_failure"
    JOB_COMPLETED = "job_completed"
    JOB_PARTIAL = "job_partial"
    JOB_QUARANTINED = "job_quarantined"
    JOB_STALE_AUTHORITY = "job_stale_authority"
    JOB_PROOF_UNKNOWN = "job_proof_unknown"
    JOB_REVIEW_REQUIRED = "job_review_required"
    JOB_FAILED = "job_failed"
    JOB_INTERRUPTED = "job_interrupted"
    DELTA_APPLIED = "delta_applied"
    NEW_MATTER = "new_matter"


class MatterAnalysisError(ValueError):
    """Bounded orchestration error with a stable machine-readable code."""

    def __init__(self, message: str, *, code: str = "matter_analysis_error") -> None:
        super().__init__(message)
        self.code = str(code)

    def audit_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": str(self)[:256]}


class InjectedStageFailure(Exception):
    """Raised by failure injection before a stage body executes (tests/resume)."""

    def __init__(self, stage: MatterAnalysisStage) -> None:
        super().__init__(f"injected failure before stage {stage.value}")
        self.stage = stage
        self.code = MatterAnalysisReasonCode.INJECTED_FAILURE.value


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
    return sha256_hex(MATTER_ANALYSIS_PARSER_DIGEST_MATERIAL)


def stage_idempotency_key(
    *,
    analysis_id: str,
    stage: MatterAnalysisStage | str,
    input_digest: str,
    parser_digest_value: str | None = None,
) -> str:
    """Deterministic idempotency key for a stage commit bound to its input."""
    stage_v = stage.value if isinstance(stage, MatterAnalysisStage) else str(stage)
    digest = parser_digest_value or parser_digest()
    material = f"{analysis_id}|{stage_v}|{input_digest}|{digest}"
    return sha256_hex(material)


def _require_id(value: str, name: str) -> str:
    text = str(value or "").strip()
    if not text or not _ID_RE.match(text):
        raise MatterAnalysisError(f"invalid {name}: {value!r}", code="invalid_id")
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
    return cleaned[:180] or "analysis"


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
    value: MatterAnalysisStage | str | None,
) -> MatterAnalysisStage | None:
    if value is None:
        return None
    if isinstance(value, MatterAnalysisStage):
        return value
    return MatterAnalysisStage(str(value).strip())


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
        raise MatterAnalysisError(
            f"expected object at {path.name}", code="checkpoint_integrity"
        )
    return data


def _bounded_text(value: str | None, *, max_len: int = _MAX_TEXT_CHARS) -> str:
    if not value:
        return ""
    text = str(value)
    if len(text) > max_len:
        return text[:max_len]
    return text


def _canonical_digest(payload: Any) -> str:
    return sha256_hex(canonical_json(payload))


# ---------------------------------------------------------------------------
# Input models
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MatterDocumentInput:
    """One matter-bound document available to the orchestrator.

    Either inline ``content_bytes`` (for document pipeline) or ``text`` (for
    semantics) may be provided. Digests are computed when omitted.
    """

    document_id: str
    role: str = "other"
    document_code: str | None = None
    filename: str | None = None
    declared_mime: str | None = None
    text: str | None = None
    content_bytes: bytes | None = None
    content_sha256: str | None = None
    classification: DisclosureClassification | str | None = None
    labels: Mapping[str, str] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "document_id", _require_id(str(self.document_id), "document_id")
        )
        object.__setattr__(
            self, "role", (_optional_str(self.role, max_len=64) or "other")
        )
        object.__setattr__(
            self, "document_code", _optional_str(self.document_code, max_len=64)
        )
        object.__setattr__(self, "filename", _optional_str(self.filename, max_len=512))
        object.__setattr__(
            self, "declared_mime", _optional_str(self.declared_mime, max_len=256)
        )
        if self.text is not None:
            object.__setattr__(self, "text", _bounded_text(self.text))
        if self.content_bytes is not None and not isinstance(
            self.content_bytes, (bytes, bytearray)
        ):
            raise TypeError("content_bytes must be bytes or None")
        if isinstance(self.content_bytes, bytearray):
            object.__setattr__(self, "content_bytes", bytes(self.content_bytes))
        digest = self.content_sha256
        if digest is not None:
            digest = str(digest).strip().lower()
            if not _SHA256_RE.match(digest):
                raise MatterAnalysisError(
                    "content_sha256 must be 64-char lowercase hex",
                    code="invalid_digest",
                )
            object.__setattr__(self, "content_sha256", digest)
        elif self.content_bytes is not None:
            object.__setattr__(self, "content_sha256", sha256_hex(self.content_bytes))
        elif self.text is not None:
            object.__setattr__(self, "content_sha256", sha256_hex(self.text))
        else:
            object.__setattr__(
                self, "content_sha256", sha256_hex(f"empty:{self.document_id}")
            )
        if self.classification is None:
            object.__setattr__(self, "classification", None)
        else:
            object.__setattr__(
                self, "classification", _coerce_classification(self.classification)
            )
        object.__setattr__(self, "labels", _frozen_str_map(self.labels))

    def identity_material(self) -> dict[str, Any]:
        """Safe identity fields for digests (no body text)."""
        if isinstance(self.classification, DisclosureClassification):
            class_v = self.classification.value
        elif self.classification is None:
            class_v = None
        else:
            class_v = str(self.classification)
        return {
            "classification": class_v,
            "content_sha256": self.content_sha256,
            "document_code": self.document_code,
            "document_id": self.document_id,
            "filename": self.filename,
            "role": self.role,
        }

    def to_dict(self) -> dict[str, Any]:
        payload = self.identity_material()
        payload["declared_mime"] = self.declared_mime
        payload["has_bytes"] = self.content_bytes is not None
        payload["has_text"] = bool(self.text)
        payload["labels"] = dict(self.labels)
        payload["text_chars"] = len(self.text or "")
        return payload


@dataclass(frozen=True, slots=True)
class MatterAnalysisInput:
    """Inputs for one resumable matter analysis run (new matter or delta)."""

    tenant_id: str
    matter_id: str
    analysis_id: str | None = None
    application_number: str | None = None
    # When set, treats this invocation as a delta over prior checkpoint state.
    delta_token: str | None = None
    documents: tuple[MatterDocumentInput, ...] = ()
    status_snapshot: Mapping[str, Any] = MappingProxyType({})
    # As-of / authority controls.
    as_of_utc: str | None = None
    authority_snapshot_id: str | None = None
    authority_digest: str | None = None
    authority_stale: bool = False
    # Legal/logic controls for fail-closed outcomes.
    force_proof_unknown: bool = False
    force_review_required: bool = False
    force_partial: bool = False
    force_quarantine: bool = False
    classification: DisclosureClassification | str | None = None
    labels: Mapping[str, str] = MappingProxyType({})
    # Test/resume: raise InjectedStageFailure before the named stage body.
    inject_failure_before: MatterAnalysisStage | str | None = None
    # Skip live status/document network; use supplied snapshots (default True).
    offline: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "tenant_id", _require_id(str(self.tenant_id), "tenant_id")
        )
        object.__setattr__(
            self, "matter_id", _require_id(str(self.matter_id), "matter_id")
        )
        if self.analysis_id is not None:
            object.__setattr__(
                self, "analysis_id", _require_id(str(self.analysis_id), "analysis_id")
            )
        object.__setattr__(
            self,
            "application_number",
            _optional_str(self.application_number, max_len=64),
        )
        object.__setattr__(
            self, "delta_token", _optional_str(self.delta_token, max_len=128)
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
        object.__setattr__(self, "as_of_utc", _optional_str(self.as_of_utc, max_len=64))
        object.__setattr__(
            self,
            "authority_snapshot_id",
            _optional_str(self.authority_snapshot_id, max_len=256),
        )
        if self.authority_digest is not None:
            digest = str(self.authority_digest).strip().lower()
            if not _SHA256_RE.match(digest):
                raise MatterAnalysisError(
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
            "offline",
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
        if inject is not None and not isinstance(inject, MatterAnalysisStage):
            object.__setattr__(
                self, "inject_failure_before", MatterAnalysisStage(str(inject))
            )

    def documents_identity(self) -> list[dict[str, Any]]:
        return [d.identity_material() for d in self.documents]


# ---------------------------------------------------------------------------
# Checkpoint / stage records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class StageCheckpoint:
    """Durable record for one committed (or terminal) stage."""

    schema_version: str
    stage: MatterAnalysisStage
    status: StageStatus
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
    def from_dict(cls, value: Mapping[str, Any]) -> "StageCheckpoint":
        return cls(
            schema_version=str(
                value.get("schema_version") or MATTER_ANALYSIS_SCHEMA_VERSION
            ),
            stage=MatterAnalysisStage(str(value.get("stage"))),
            status=StageStatus(str(value.get("status", StageStatus.PENDING.value))),
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
class AnalysisCheckpoint:
    """Resumable analysis checkpoint (filesystem or in-memory)."""

    schema_version: str
    analysis_id: str
    tenant_id: str
    matter_id: str
    parser_digest: str
    stages: dict[str, StageCheckpoint] = field(default_factory=dict)
    disposition: str | None = None
    classification: str | None = None
    reason_codes: list[str] = field(default_factory=list)
    created_utc: str | None = None
    updated_utc: str | None = None
    labels: dict[str, str] = field(default_factory=dict)
    delta_token: str | None = None
    dossier_id: str | None = None
    bundle_id: str | None = None
    # Safe stage output digests / summaries for hydration on resume.
    stage_outputs: dict[str, dict[str, Any]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "analysis_id": self.analysis_id,
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
    def from_dict(cls, value: Mapping[str, Any]) -> "AnalysisCheckpoint":
        raw_stages = value.get("stages") or {}
        stages: dict[str, StageCheckpoint] = {}
        if isinstance(raw_stages, Mapping):
            for key, raw in raw_stages.items():
                if isinstance(raw, Mapping):
                    stages[str(key)] = StageCheckpoint.from_dict(raw)
        raw_outputs = value.get("stage_outputs") or {}
        outputs: dict[str, dict[str, Any]] = {}
        if isinstance(raw_outputs, Mapping):
            for key, raw in raw_outputs.items():
                if isinstance(raw, Mapping):
                    outputs[str(key)] = dict(raw)
        return cls(
            schema_version=str(
                value.get("schema_version") or MATTER_ANALYSIS_SCHEMA_VERSION
            ),
            analysis_id=str(value.get("analysis_id") or ""),
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

    def get_stage(self, stage: MatterAnalysisStage) -> StageCheckpoint | None:
        return self.stages.get(stage.value)

    def is_committed_with_digest(
        self, stage: MatterAnalysisStage, input_digest: str
    ) -> bool:
        entry = self.get_stage(stage)
        return (
            entry is not None
            and entry.status is StageStatus.COMMITTED
            and entry.input_digest == input_digest
        )

    def put_stage(self, entry: StageCheckpoint) -> None:
        self.stages[entry.stage.value] = entry
        self.updated_utc = _utc_now()


@dataclass(frozen=True, slots=True)
class StageRunRecord:
    """In-memory observation of a stage execution attempt (not durable)."""

    stage: MatterAnalysisStage
    status: StageStatus
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
class MatterAnalysisResult:
    """Domain outcome of a matter analysis run.

    ``success`` / ``ok`` is True only for :attr:`MatterAnalysisDisposition.COMPLETED`.
    Partial, quarantined, stale-authority, proof-unknown, and review-required
    outcomes return ``success=False`` even when no exception was raised.
    """

    schema_version: str
    analysis_id: str
    tenant_id: str
    matter_id: str
    disposition: MatterAnalysisDisposition
    review_state: ReviewState
    classification: DisclosureClassification
    reason_codes: tuple[str, ...]
    stage_records: tuple[StageRunRecord, ...]
    committed_stages: tuple[str, ...]
    resumed_stages: tuple[str, ...]
    executed_stages: tuple[str, ...]
    reused_stages: tuple[str, ...]
    parser_digest: str
    stage_input_digests: Mapping[str, str] = MappingProxyType({})
    stage_output_digests: Mapping[str, str] = MappingProxyType({})
    dossier_id: str | None = None
    bundle_id: str | None = None
    bundle_digest: str | None = None
    delta_token: str | None = None
    is_delta: bool = False
    labels: Mapping[str, str] = MappingProxyType({})
    diagnostics: Mapping[str, str] = MappingProxyType({})

    def __post_init__(self) -> None:
        if self.schema_version != MATTER_ANALYSIS_SCHEMA_VERSION:
            raise ValueError(
                "MatterAnalysisResult.schema_version must be "
                f"{MATTER_ANALYSIS_SCHEMA_VERSION}"
            )
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

    @property
    def ok(self) -> bool:
        """Domain success: completed without fail-closed dispositions."""
        return self.disposition is MatterAnalysisDisposition.COMPLETED

    @property
    def success(self) -> bool:
        """Alias of :attr:`ok` — domain outcome, not exception absence."""
        return self.ok

    @property
    def is_quarantined(self) -> bool:
        return self.disposition is MatterAnalysisDisposition.QUARANTINED

    @property
    def is_partial(self) -> bool:
        return self.disposition is MatterAnalysisDisposition.PARTIAL

    @property
    def is_stale_authority(self) -> bool:
        return self.disposition is MatterAnalysisDisposition.STALE_AUTHORITY

    @property
    def is_proof_unknown(self) -> bool:
        return self.disposition is MatterAnalysisDisposition.PROOF_UNKNOWN

    @property
    def is_review_required(self) -> bool:
        return self.disposition is MatterAnalysisDisposition.REVIEW_REQUIRED

    def to_dict(self) -> dict[str, Any]:
        return {
            "analysis_id": self.analysis_id,
            "bundle_digest": self.bundle_digest,
            "bundle_id": self.bundle_id,
            "classification": self.classification.value,
            "committed_stages": list(self.committed_stages),
            "delta_token": self.delta_token,
            "diagnostics": dict(self.diagnostics),
            "disposition": self.disposition.value,
            "dossier_id": self.dossier_id,
            "executed_stages": list(self.executed_stages),
            "is_delta": self.is_delta,
            "is_partial": self.is_partial,
            "is_proof_unknown": self.is_proof_unknown,
            "is_quarantined": self.is_quarantined,
            "is_review_required": self.is_review_required,
            "is_stale_authority": self.is_stale_authority,
            "labels": dict(self.labels),
            "matter_id": self.matter_id,
            "ok": self.ok,
            "parser_digest": self.parser_digest,
            "reason_codes": list(self.reason_codes),
            "resumed_stages": list(self.resumed_stages),
            "reused_stages": list(self.reused_stages),
            "review_state": self.review_state.value,
            "schema_version": self.schema_version,
            "stage_input_digests": dict(self.stage_input_digests),
            "stage_output_digests": dict(self.stage_output_digests),
            "stage_records": [r.to_dict() for r in self.stage_records],
            "success": self.success,
            "tenant_id": self.tenant_id,
        }

    def public_projection(self) -> dict[str, Any]:
        """Safe projection: identifiers, digests, codes — never body text."""
        return self.to_dict()

    def to_canonical_json(self) -> str:
        return canonical_json(self.public_projection())


# ---------------------------------------------------------------------------
# Checkpoint store
# ---------------------------------------------------------------------------


class MatterAnalysisCheckpointStore:
    """Filesystem or in-memory atomic analysis checkpoint persistence."""

    def __init__(self, root: str | Path | None = None) -> None:
        self._root = Path(root) if root is not None else None
        self._memory: dict[str, AnalysisCheckpoint] = {}
        self._lock = threading.RLock()
        if self._root is not None:
            _ensure_dir(self._root)

    @property
    def root(self) -> Path | None:
        return self._root

    def _path_for(self, analysis_id: str) -> Path:
        assert self._root is not None
        return self._root / f"matter-analysis-{_safe_filename(analysis_id)}.json"

    def load(self, analysis_id: str) -> AnalysisCheckpoint | None:
        aid = _require_id(analysis_id, "analysis_id")
        with self._lock:
            if self._root is not None:
                path = self._path_for(aid)
                raw = _read_json(path)
                if raw is not None:
                    return AnalysisCheckpoint.from_dict(raw)
            return self._memory.get(aid)

    def save(self, checkpoint: AnalysisCheckpoint) -> None:
        with self._lock:
            checkpoint.updated_utc = _utc_now()
            self._memory[checkpoint.analysis_id] = checkpoint
            if self._root is None:
                return
            path = self._path_for(checkpoint.analysis_id)
            _atomic_write_json(path, checkpoint.to_dict())

    def delete(self, analysis_id: str) -> None:
        aid = _require_id(analysis_id, "analysis_id")
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
    [MatterAnalysisStage, "MatterAnalysisInput", AnalysisCheckpoint], None
]


@dataclass
class _StageOutcome:
    record: StageRunRecord
    terminal_disposition: MatterAnalysisDisposition | None = None
    output_summary: Mapping[str, Any] = field(default_factory=dict)


class MatterAnalysisProcessor:
    """Resumable matter-level analysis orchestrator.

    Given a tenant and matter reference, incrementally syncs authorized
    status/documents (or consumes offline snapshots), processes changed
    artifacts, selects the as-of authority view, runs semantic/legal/logic
    checks, assembles a versioned dossier and analysis bundle, and checkpoints
    a stage/result DAG.
    """

    def __init__(
        self,
        *,
        checkpoint_store: MatterAnalysisCheckpointStore | None = None,
        document_pipeline: DocumentPipelineProcessor | None = None,
        office_action_semantics: OfficeActionSemanticsV2 | None = None,
        submission_semantics: SubmissionPackageSemanticsV2 | None = None,
        semantic_compliance: SemanticComplianceProcessor | None = None,
        instruction_consistency: SemanticInstructionConsistencyProcessor | None = None,
        deadline_processor: DeadlineProcessor | None = None,
        proof_executor: LegalIRProofExecutor | None = None,
        dossier_processor: DossierProcessor | None = None,
        id_factory: Callable[[], str] | None = None,
        stage_hook: StageHook | None = None,
        pipeline_checkpoint_root: str | Path | None = None,
    ) -> None:
        self._store = checkpoint_store or MatterAnalysisCheckpointStore()
        self._pipeline = document_pipeline or DocumentPipelineProcessor(
            job_store=DocumentPipelineJobStore(root=pipeline_checkpoint_root)
        )
        self._oa_semantics = office_action_semantics or OfficeActionSemanticsV2()
        self._pkg_semantics = submission_semantics or SubmissionPackageSemanticsV2()
        self._compliance = semantic_compliance or SemanticComplianceProcessor()
        self._instruction = (
            instruction_consistency or SemanticInstructionConsistencyProcessor()
        )
        self._deadlines = deadline_processor or DeadlineProcessor()
        self._proofs = proof_executor or LegalIRProofExecutor()
        self._dossier = dossier_processor or DossierProcessor()
        self._id_factory = id_factory or (
            lambda: f"analysis:{uuid.uuid4().hex}"
        )
        self._stage_hook = stage_hook
        self._workspace: dict[str, Any] = {}
        self._execution_counts: MutableMapping[str, int] = {}

    @property
    def checkpoint_store(self) -> MatterAnalysisCheckpointStore:
        return self._store

    @property
    def execution_counts(self) -> Mapping[str, int]:
        """Per-stage body execution counts for the current process (tests)."""
        return MappingProxyType(dict(self._execution_counts))

    def reset_execution_counts(self) -> None:
        self._execution_counts.clear()

    def analyze(
        self,
        value: MatterAnalysisInput | Mapping[str, Any] | None = None,
        /,
        **kwargs: Any,
    ) -> MatterAnalysisResult:
        """Run or resume a checkpointed matter analysis (new matter or delta)."""
        inp = self._coerce_input(value, **kwargs)
        return self._analyze(inp)

    def process(
        self,
        value: MatterAnalysisInput | Mapping[str, Any] | None = None,
        /,
        **kwargs: Any,
    ) -> MatterAnalysisResult:
        """Alias of :meth:`analyze` for processor-adapter compatibility."""
        return self.analyze(value, **kwargs)

    def analyze_many(
        self, values: Iterable[MatterAnalysisInput | Mapping[str, Any]]
    ) -> list[MatterAnalysisResult]:
        return [self.analyze(v) for v in values]

    # -- coercion -----------------------------------------------------------

    def _coerce_input(
        self,
        value: MatterAnalysisInput | Mapping[str, Any] | None,
        **kwargs: Any,
    ) -> MatterAnalysisInput:
        if value is None:
            return MatterAnalysisInput(**kwargs)
        if isinstance(value, MatterAnalysisInput):
            if not kwargs:
                return value
            data = {
                "tenant_id": value.tenant_id,
                "matter_id": value.matter_id,
                "analysis_id": value.analysis_id,
                "application_number": value.application_number,
                "delta_token": value.delta_token,
                "documents": value.documents,
                "status_snapshot": dict(value.status_snapshot),
                "as_of_utc": value.as_of_utc,
                "authority_snapshot_id": value.authority_snapshot_id,
                "authority_digest": value.authority_digest,
                "authority_stale": value.authority_stale,
                "force_proof_unknown": value.force_proof_unknown,
                "force_review_required": value.force_review_required,
                "force_partial": value.force_partial,
                "force_quarantine": value.force_quarantine,
                "classification": value.classification,
                "labels": dict(value.labels),
                "inject_failure_before": value.inject_failure_before,
                "offline": value.offline,
            }
            data.update(kwargs)
            return MatterAnalysisInput(**data)
        if isinstance(value, Mapping):
            data = dict(value)
            data.update(kwargs)
            return MatterAnalysisInput(**data)
        raise TypeError(
            "analyze() expects MatterAnalysisInput, mapping, or kwargs"
        )

    # -- main orchestration -------------------------------------------------

    def _analyze(self, inp: MatterAnalysisInput) -> MatterAnalysisResult:
        pdigest = parser_digest()
        analysis_id = inp.analysis_id or str(self._id_factory())
        is_delta = bool(inp.delta_token)

        class_values: list[DisclosureClassification] = []
        if inp.classification is not None:
            class_values.append(_coerce_classification(inp.classification))
        for doc in inp.documents:
            if doc.classification is not None:
                class_values.append(_coerce_classification(doc.classification))
        # Default offline public path when caller omitted classification.
        # Explicit UNKNOWN (or force_quarantine) remains fail-closed.
        if not class_values:
            disclosure = DisclosureClassification.PUBLIC_USER
        else:
            disclosure = most_restrictive_classification(class_values)

        self._workspace = {
            "analysis_id": analysis_id,
            "tenant_id": inp.tenant_id,
            "matter_id": inp.matter_id,
            "disclosure": disclosure,
            "is_delta": is_delta,
            "delta_token": inp.delta_token,
            "status_digest": None,
            "document_digests": [],
            "pipeline_results": [],
            "oa_result": None,
            "pkg_result": None,
            "authority": {},
            "compliance": None,
            "instruction": None,
            "proof_outcome": None,
            "deadlines": None,
            "dossier": None,
            "bundle": None,
            "labels": dict(inp.labels),
            "stage_outputs": {},
            "partial_signals": [],
            "review_signals": [],
            "proof_unknown": False,
            "stale_authority": False,
            "quarantine_signals": [],
        }

        ckpt = self._store.load(analysis_id)
        if ckpt is None:
            ckpt = AnalysisCheckpoint(
                schema_version=MATTER_ANALYSIS_SCHEMA_VERSION,
                analysis_id=analysis_id,
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
                    analysis_id=analysis_id,
                    inp=inp,
                    pdigest=pdigest,
                    disposition=MatterAnalysisDisposition.FAILED,
                    reason_codes=(
                        MatterAnalysisReasonCode.JOB_FAILED.value,
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
                    ckpt=ckpt,
                    diagnostics={
                        "expected_matter_id": ckpt.matter_id,
                        "observed_matter_id": inp.matter_id,
                    },
                )
            if ckpt.tenant_id and ckpt.tenant_id != inp.tenant_id:
                return self._terminal(
                    analysis_id=analysis_id,
                    inp=inp,
                    pdigest=pdigest,
                    disposition=MatterAnalysisDisposition.FAILED,
                    reason_codes=(
                        MatterAnalysisReasonCode.JOB_FAILED.value,
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
                    ckpt=ckpt,
                    diagnostics={
                        "expected_tenant_id": ckpt.tenant_id,
                        "observed_tenant_id": inp.tenant_id,
                    },
                )
            # Hydrate prior stage outputs for dependent stages on resume/delta.
            self._workspace["stage_outputs"] = dict(ckpt.stage_outputs)
            if ckpt.dossier_id:
                self._workspace["dossier_id"] = ckpt.dossier_id
            if ckpt.bundle_id:
                self._workspace["bundle_id"] = ckpt.bundle_id

        if requires_quarantine(disclosure) or inp.force_quarantine:
            self._workspace["hard_quarantine"] = True

        stage_records: list[StageRunRecord] = []
        committed: list[str] = []
        resumed: list[str] = []
        executed: list[str] = []
        reused: list[str] = []
        input_digests: dict[str, str] = {}
        output_digests: dict[str, str] = {}

        inject = _coerce_stage(inp.inject_failure_before)

        for stage in MATTER_ANALYSIS_STAGE_ORDER:
            input_digest = self._compute_input_digest(stage, inp)
            input_digests[stage.value] = input_digest
            ikey = stage_idempotency_key(
                analysis_id=analysis_id,
                stage=stage,
                input_digest=input_digest,
                parser_digest_value=pdigest,
            )
            existing = ckpt.get_stage(stage)

            if existing is not None and ckpt.is_committed_with_digest(
                stage, input_digest
            ):
                # Resume or delta reuse: identical input digest → do not re-run.
                reason = (
                    MatterAnalysisReasonCode.STAGE_REUSED_BY_DIGEST.value
                    if is_delta
                    else MatterAnalysisReasonCode.STAGE_RESUMED.value
                )
                record = StageRunRecord(
                    stage=stage,
                    status=StageStatus.SKIPPED,
                    input_digest=input_digest,
                    idempotency_key=existing.idempotency_key or ikey,
                    executed=False,
                    resumed=not is_delta,
                    reused_by_digest=True,
                    reason_codes=(reason, *existing.reason_codes),
                    diagnostics=existing.diagnostics,
                    output_digest=existing.output_digest,
                    stage_disposition=existing.stage_disposition,
                )
                stage_records.append(record)
                committed.append(stage.value)
                resumed.append(stage.value)
                reused.append(stage.value)
                if existing.output_digest:
                    output_digests[stage.value] = existing.output_digest
                # Rehydrate workspace from stored summary.
                prior = ckpt.stage_outputs.get(stage.value) or {}
                self._apply_stage_output_summary(stage, prior)
                continue

            if inject is not None and inject is stage:
                self._store.save(ckpt)
                raise InjectedStageFailure(stage)

            if self._stage_hook is not None:
                self._stage_hook(stage, inp, ckpt)

            self._execution_counts[stage.value] = (
                self._execution_counts.get(stage.value, 0) + 1
            )

            try:
                outcome = self._run_stage(stage, inp, ckpt, input_digest, ikey)
            except InjectedStageFailure:
                self._store.save(ckpt)
                raise
            except MatterAnalysisError as exc:
                return self._terminal(
                    analysis_id=analysis_id,
                    inp=inp,
                    pdigest=pdigest,
                    disposition=MatterAnalysisDisposition.FAILED,
                    reason_codes=(
                        MatterAnalysisReasonCode.JOB_FAILED.value,
                        exc.code,
                    ),
                    review_state=ReviewState.REQUIRED,
                    stage_records=tuple(stage_records),
                    committed=tuple(committed),
                    resumed=tuple(resumed),
                    executed=tuple(executed),
                    reused=tuple(reused),
                    input_digests=input_digests,
                    output_digests=output_digests,
                    ckpt=ckpt,
                    diagnostics={"stage": stage.value, "message": str(exc)[:256]},
                )
            except Exception as exc:  # pragma: no cover - defensive
                return self._terminal(
                    analysis_id=analysis_id,
                    inp=inp,
                    pdigest=pdigest,
                    disposition=MatterAnalysisDisposition.FAILED,
                    reason_codes=(
                        MatterAnalysisReasonCode.JOB_FAILED.value,
                        "stage_exception",
                        type(exc).__name__,
                    ),
                    review_state=ReviewState.REQUIRED,
                    stage_records=tuple(stage_records),
                    committed=tuple(committed),
                    resumed=tuple(resumed),
                    executed=tuple(executed),
                    reused=tuple(reused),
                    input_digests=input_digests,
                    output_digests=output_digests,
                    ckpt=ckpt,
                    diagnostics={"stage": stage.value, "message": str(exc)[:256]},
                )

            executed.append(stage.value)
            stage_records.append(outcome.record)
            if outcome.record.output_digest:
                output_digests[stage.value] = outcome.record.output_digest

            if outcome.terminal_disposition is not None:
                # Fail-closed terminal mid-pipeline (e.g. quarantine).
                ckpt.put_stage(
                    StageCheckpoint(
                        schema_version=MATTER_ANALYSIS_SCHEMA_VERSION,
                        stage=stage,
                        status=StageStatus.QUARANTINED
                        if outcome.terminal_disposition
                        is MatterAnalysisDisposition.QUARANTINED
                        else StageStatus.FAILED,
                        input_digest=input_digest,
                        idempotency_key=ikey,
                        output_digest=outcome.record.output_digest,
                        reason_codes=outcome.record.reason_codes,
                        diagnostics=outcome.record.diagnostics,
                        committed_utc=_utc_now(),
                        attempt=(existing.attempt + 1) if existing else 1,
                        stage_disposition=outcome.terminal_disposition.value,
                    )
                )
                if outcome.output_summary:
                    ckpt.stage_outputs[stage.value] = dict(outcome.output_summary)
                return self._terminal(
                    analysis_id=analysis_id,
                    inp=inp,
                    pdigest=pdigest,
                    disposition=outcome.terminal_disposition,
                    reason_codes=outcome.record.reason_codes,
                    review_state=ReviewState.REQUIRED,
                    stage_records=tuple(stage_records),
                    committed=tuple(committed),
                    resumed=tuple(resumed),
                    executed=tuple(executed),
                    reused=tuple(reused),
                    input_digests=input_digests,
                    output_digests=output_digests,
                    ckpt=ckpt,
                    diagnostics=dict(outcome.record.diagnostics),
                )

            # Commit successful stage body.
            ckpt.put_stage(
                StageCheckpoint(
                    schema_version=MATTER_ANALYSIS_SCHEMA_VERSION,
                    stage=stage,
                    status=StageStatus.COMMITTED,
                    input_digest=input_digest,
                    idempotency_key=ikey,
                    output_digest=outcome.record.output_digest,
                    reason_codes=outcome.record.reason_codes,
                    diagnostics=outcome.record.diagnostics,
                    committed_utc=_utc_now(),
                    attempt=(existing.attempt + 1) if existing else 1,
                    stage_disposition=outcome.record.stage_disposition,
                )
            )
            if outcome.output_summary:
                ckpt.stage_outputs[stage.value] = dict(outcome.output_summary)
                self._workspace["stage_outputs"][stage.value] = dict(
                    outcome.output_summary
                )
            committed.append(stage.value)
            self._store.save(ckpt)

        # All stages committed — aggregate domain disposition.
        disposition, reason_codes, review_state = self._aggregate_disposition(
            inp, stage_records
        )
        dossier = self._workspace.get("dossier")
        bundle = self._workspace.get("bundle")
        dossier_id = None
        bundle_id = None
        bundle_digest = None
        if isinstance(dossier, ApplicationDossier):
            dossier_id = dossier.dossier_id
            ckpt.dossier_id = dossier_id
        elif isinstance(self._workspace.get("dossier_id"), str):
            dossier_id = self._workspace["dossier_id"]
            ckpt.dossier_id = dossier_id
        if isinstance(bundle, UsptoAnalysisBundle):
            bundle_id = bundle.bundle_id
            bundle_digest = bundle.bundle_digest
            ckpt.bundle_id = bundle_id
        elif isinstance(self._workspace.get("bundle_id"), str):
            bundle_id = self._workspace["bundle_id"]
            ckpt.bundle_id = bundle_id

        ckpt.disposition = disposition.value
        ckpt.classification = disclosure.value
        ckpt.reason_codes = list(reason_codes)
        ckpt.delta_token = inp.delta_token
        self._store.save(ckpt)

        return MatterAnalysisResult(
            schema_version=MATTER_ANALYSIS_SCHEMA_VERSION,
            analysis_id=analysis_id,
            tenant_id=inp.tenant_id,
            matter_id=inp.matter_id,
            disposition=disposition,
            review_state=review_state,
            classification=disclosure,
            reason_codes=tuple(reason_codes),
            stage_records=tuple(stage_records),
            committed_stages=tuple(committed),
            resumed_stages=tuple(resumed),
            executed_stages=tuple(executed),
            reused_stages=tuple(reused),
            parser_digest=pdigest,
            stage_input_digests=_frozen_str_map(input_digests),
            stage_output_digests=_frozen_str_map(output_digests),
            dossier_id=dossier_id,
            bundle_id=bundle_id,
            bundle_digest=bundle_digest,
            delta_token=inp.delta_token,
            is_delta=is_delta,
            labels=_frozen_str_map(inp.labels),
            diagnostics=_frozen_str_map(
                {
                    "is_delta": "true" if is_delta else "false",
                    "document_count": str(len(inp.documents)),
                }
            ),
        )

    def _terminal(
        self,
        *,
        analysis_id: str,
        inp: MatterAnalysisInput,
        pdigest: str,
        disposition: MatterAnalysisDisposition,
        reason_codes: Sequence[str],
        review_state: ReviewState,
        stage_records: tuple[StageRunRecord, ...],
        committed: tuple[str, ...],
        resumed: tuple[str, ...],
        executed: tuple[str, ...],
        reused: tuple[str, ...],
        input_digests: Mapping[str, str],
        output_digests: Mapping[str, str],
        ckpt: AnalysisCheckpoint,
        diagnostics: Mapping[str, str] | None = None,
    ) -> MatterAnalysisResult:
        codes = list(reason_codes)
        job_code = {
            MatterAnalysisDisposition.PARTIAL: MatterAnalysisReasonCode.JOB_PARTIAL,
            MatterAnalysisDisposition.QUARANTINED: MatterAnalysisReasonCode.JOB_QUARANTINED,
            MatterAnalysisDisposition.STALE_AUTHORITY: (
                MatterAnalysisReasonCode.JOB_STALE_AUTHORITY
            ),
            MatterAnalysisDisposition.PROOF_UNKNOWN: (
                MatterAnalysisReasonCode.JOB_PROOF_UNKNOWN
            ),
            MatterAnalysisDisposition.REVIEW_REQUIRED: (
                MatterAnalysisReasonCode.JOB_REVIEW_REQUIRED
            ),
            MatterAnalysisDisposition.FAILED: MatterAnalysisReasonCode.JOB_FAILED,
            MatterAnalysisDisposition.INTERRUPTED: (
                MatterAnalysisReasonCode.JOB_INTERRUPTED
            ),
        }.get(disposition)
        if job_code is not None and job_code.value not in codes:
            codes.append(job_code.value)

        disclosure = self._workspace.get("disclosure") or _coerce_classification(
            inp.classification
        )
        ckpt.disposition = disposition.value
        ckpt.classification = (
            disclosure.value
            if isinstance(disclosure, DisclosureClassification)
            else str(disclosure)
        )
        ckpt.reason_codes = list(codes)[:_MAX_REASON_CODES]
        self._store.save(ckpt)

        return MatterAnalysisResult(
            schema_version=MATTER_ANALYSIS_SCHEMA_VERSION,
            analysis_id=analysis_id,
            tenant_id=inp.tenant_id,
            matter_id=inp.matter_id,
            disposition=disposition,
            review_state=review_state,
            classification=_coerce_classification(disclosure),
            reason_codes=tuple(codes[:_MAX_REASON_CODES]),
            stage_records=stage_records,
            committed_stages=committed,
            resumed_stages=resumed,
            executed_stages=executed,
            reused_stages=reused,
            parser_digest=pdigest,
            stage_input_digests=_frozen_str_map(input_digests),
            stage_output_digests=_frozen_str_map(output_digests),
            dossier_id=ckpt.dossier_id,
            bundle_id=ckpt.bundle_id,
            delta_token=inp.delta_token,
            is_delta=bool(inp.delta_token),
            labels=_frozen_str_map(inp.labels),
            diagnostics=_frozen_str_map(diagnostics or {}),
        )

    def _aggregate_disposition(
        self,
        inp: MatterAnalysisInput,
        stage_records: Sequence[StageRunRecord],
    ) -> tuple[MatterAnalysisDisposition, list[str], ReviewState]:
        """Map stage signals to a single fail-closed top-level disposition.

        Priority: quarantine > stale_authority > proof_unknown >
        review_required > partial > completed.

        Soft leaf partials (optional package/dossier coverage) do **not**
        collapse a well-formed matter run to partial; only explicit force
        flags and hard quarantine/stale/proof/review signals do.
        """
        reasons: list[str] = []

        if bool(inp.delta_token):
            reasons.append(MatterAnalysisReasonCode.DELTA_APPLIED.value)
        else:
            reasons.append(MatterAnalysisReasonCode.NEW_MATTER.value)

        hard_quarantine = bool(inp.force_quarantine) or bool(
            self._workspace.get("hard_quarantine")
        )
        if hard_quarantine or (
            requires_quarantine(self._workspace.get("disclosure"))
            and inp.force_quarantine
        ):
            reasons.append(MatterAnalysisReasonCode.QUARANTINE_CLASSIFICATION.value)
            reasons.append(MatterAnalysisReasonCode.JOB_QUARANTINED.value)
            return (
                MatterAnalysisDisposition.QUARANTINED,
                reasons,
                ReviewState.REQUIRED,
            )
        if self._workspace.get("hard_quarantine"):
            reasons.append(MatterAnalysisReasonCode.QUARANTINE_CLASSIFICATION.value)
            reasons.append(MatterAnalysisReasonCode.JOB_QUARANTINED.value)
            return (
                MatterAnalysisDisposition.QUARANTINED,
                reasons,
                ReviewState.REQUIRED,
            )

        if self._workspace.get("stale_authority") or inp.authority_stale:
            reasons.append(MatterAnalysisReasonCode.STALE_AUTHORITY.value)
            reasons.append(MatterAnalysisReasonCode.JOB_STALE_AUTHORITY.value)
            return (
                MatterAnalysisDisposition.STALE_AUTHORITY,
                reasons,
                ReviewState.REQUIRED,
            )

        if self._workspace.get("proof_unknown") or inp.force_proof_unknown:
            reasons.append(MatterAnalysisReasonCode.PROOF_UNKNOWN.value)
            reasons.append(MatterAnalysisReasonCode.JOB_PROOF_UNKNOWN.value)
            return (
                MatterAnalysisDisposition.PROOF_UNKNOWN,
                reasons,
                ReviewState.REQUIRED,
            )

        if bool(inp.force_review_required) or bool(
            self._workspace.get("hard_review")
        ):
            reasons.append(MatterAnalysisReasonCode.REVIEW_REQUIRED.value)
            reasons.append(MatterAnalysisReasonCode.JOB_REVIEW_REQUIRED.value)
            return (
                MatterAnalysisDisposition.REVIEW_REQUIRED,
                reasons,
                ReviewState.REQUIRED,
            )

        if bool(inp.force_partial) or bool(self._workspace.get("hard_partial")):
            reasons.append(MatterAnalysisReasonCode.PARTIAL_COVERAGE.value)
            reasons.append(MatterAnalysisReasonCode.JOB_PARTIAL.value)
            return (
                MatterAnalysisDisposition.PARTIAL,
                reasons,
                ReviewState.PENDING,
            )

        reasons.append(MatterAnalysisReasonCode.JOB_COMPLETED.value)
        for rec in stage_records:
            for code in rec.reason_codes:
                if code not in reasons and len(reasons) < _MAX_REASON_CODES:
                    reasons.append(code)
        return MatterAnalysisDisposition.COMPLETED, reasons, ReviewState.NOT_REQUIRED

    # -- input digests ------------------------------------------------------

    def _compute_input_digest(
        self, stage: MatterAnalysisStage, inp: MatterAnalysisInput
    ) -> str:
        """Pure function of stage-relevant inputs (no process-local state)."""
        base: dict[str, Any] = {
            "matter_id": inp.matter_id,
            "stage": stage.value,
            "tenant_id": inp.tenant_id,
        }
        if stage is MatterAnalysisStage.AUTHORIZE:
            base.update(
                {
                    "classification": _coerce_classification(
                        inp.classification
                    ).value,
                    "force_quarantine": inp.force_quarantine,
                }
            )
        elif stage is MatterAnalysisStage.STATUS_SYNC:
            base.update(
                {
                    "application_number": inp.application_number,
                    "status_snapshot": dict(inp.status_snapshot),
                }
            )
        elif stage is MatterAnalysisStage.DOCUMENT_SYNC:
            base.update({"documents": inp.documents_identity()})
        elif stage is MatterAnalysisStage.DOCUMENT_PROCESS:
            base.update(
                {
                    "documents": [
                        {
                            "content_sha256": d.content_sha256,
                            "document_id": d.document_id,
                            "has_bytes": d.content_bytes is not None,
                        }
                        for d in inp.documents
                    ]
                }
            )
        elif stage is MatterAnalysisStage.OFFICE_ACTION_SEMANTICS:
            base.update(
                {
                    "oa_docs": [
                        {
                            "content_sha256": d.content_sha256,
                            "document_code": d.document_code,
                            "document_id": d.document_id,
                            "role": d.role,
                        }
                        for d in inp.documents
                        if d.role in ("office_action", "oa")
                        or (d.document_code or "").upper()
                        in ("CTNF", "CTFR", "CTAV", "OA")
                    ]
                }
            )
        elif stage is MatterAnalysisStage.SUBMISSION_SEMANTICS:
            base.update(
                {
                    "submission_docs": [
                        {
                            "content_sha256": d.content_sha256,
                            "document_id": d.document_id,
                            "role": d.role,
                        }
                        for d in inp.documents
                        if d.role
                        not in ("office_action", "oa")
                        or (d.document_code or "").upper()
                        not in ("CTNF", "CTFR", "CTAV", "OA")
                    ]
                }
            )
        elif stage is MatterAnalysisStage.AUTHORITY_VIEW:
            base.update(
                {
                    "as_of_utc": inp.as_of_utc,
                    "authority_digest": inp.authority_digest,
                    "authority_snapshot_id": inp.authority_snapshot_id,
                    "authority_stale": inp.authority_stale,
                }
            )
        elif stage is MatterAnalysisStage.LEGAL_LOGIC:
            base.update(
                {
                    "force_proof_unknown": inp.force_proof_unknown,
                    "force_review_required": inp.force_review_required,
                    "oa_out": (
                        self._workspace.get("stage_outputs", {})
                        .get(MatterAnalysisStage.OFFICE_ACTION_SEMANTICS.value, {})
                        .get("output_digest")
                    ),
                    "pkg_out": (
                        self._workspace.get("stage_outputs", {})
                        .get(MatterAnalysisStage.SUBMISSION_SEMANTICS.value, {})
                        .get("output_digest")
                    ),
                    "authority_out": (
                        self._workspace.get("stage_outputs", {})
                        .get(MatterAnalysisStage.AUTHORITY_VIEW.value, {})
                        .get("output_digest")
                    ),
                }
            )
        elif stage is MatterAnalysisStage.TEMPORAL_CANDIDATES:
            base.update(
                {
                    "as_of_utc": inp.as_of_utc,
                    "oa_out": (
                        self._workspace.get("stage_outputs", {})
                        .get(MatterAnalysisStage.OFFICE_ACTION_SEMANTICS.value, {})
                        .get("output_digest")
                    ),
                    "status_out": (
                        self._workspace.get("stage_outputs", {})
                        .get(MatterAnalysisStage.STATUS_SYNC.value, {})
                        .get("output_digest")
                    ),
                }
            )
        elif stage is MatterAnalysisStage.DOSSIER:
            # Dossier depends on all prior stage output digests present.
            outs = self._workspace.get("stage_outputs") or {}
            base["prior"] = {
                k: (v or {}).get("output_digest")
                for k, v in sorted(outs.items())
                if k
                not in (
                    MatterAnalysisStage.DOSSIER.value,
                    MatterAnalysisStage.BUNDLE.value,
                )
            }
            base["force_partial"] = inp.force_partial
        elif stage is MatterAnalysisStage.BUNDLE:
            dossier_out = (
                self._workspace.get("stage_outputs", {})
                .get(MatterAnalysisStage.DOSSIER.value, {})
                .get("output_digest")
            )
            base["dossier_out"] = dossier_out
        else:  # pragma: no cover
            base["documents"] = inp.documents_identity()

        return _canonical_digest(base)

    def _apply_stage_output_summary(
        self, stage: MatterAnalysisStage, summary: Mapping[str, Any]
    ) -> None:
        """Restore workspace fields needed by later stages after reuse."""
        if not summary:
            return
        self._workspace.setdefault("stage_outputs", {})[stage.value] = dict(summary)
        if stage is MatterAnalysisStage.STATUS_SYNC:
            self._workspace["status_digest"] = summary.get("output_digest")
        elif stage is MatterAnalysisStage.DOCUMENT_SYNC:
            self._workspace["document_digests"] = list(
                summary.get("document_digests") or []
            )
        elif stage is MatterAnalysisStage.AUTHORITY_VIEW:
            self._workspace["authority"] = dict(summary.get("authority") or {})
            self._workspace["stale_authority"] = bool(
                summary.get("stale_authority", False)
            )
        elif stage is MatterAnalysisStage.LEGAL_LOGIC:
            self._workspace["proof_unknown"] = bool(summary.get("proof_unknown", False))
            if summary.get("review_required"):
                self._workspace.setdefault("review_signals", []).append("legal_logic")
        elif stage is MatterAnalysisStage.DOSSIER:
            if summary.get("dossier_id"):
                self._workspace["dossier_id"] = summary["dossier_id"]
            if summary.get("partial"):
                self._workspace.setdefault("partial_signals", []).append("dossier")
        elif stage is MatterAnalysisStage.BUNDLE:
            if summary.get("bundle_id"):
                self._workspace["bundle_id"] = summary["bundle_id"]

    # -- stage dispatch -----------------------------------------------------

    def _run_stage(
        self,
        stage: MatterAnalysisStage,
        inp: MatterAnalysisInput,
        ckpt: AnalysisCheckpoint,
        input_digest: str,
        ikey: str,
    ) -> _StageOutcome:
        if stage is MatterAnalysisStage.AUTHORIZE:
            return self._stage_authorize(inp, input_digest, ikey)
        if stage is MatterAnalysisStage.STATUS_SYNC:
            return self._stage_status_sync(inp, input_digest, ikey)
        if stage is MatterAnalysisStage.DOCUMENT_SYNC:
            return self._stage_document_sync(inp, input_digest, ikey)
        if stage is MatterAnalysisStage.DOCUMENT_PROCESS:
            return self._stage_document_process(inp, input_digest, ikey)
        if stage is MatterAnalysisStage.OFFICE_ACTION_SEMANTICS:
            return self._stage_oa_semantics(inp, input_digest, ikey)
        if stage is MatterAnalysisStage.SUBMISSION_SEMANTICS:
            return self._stage_submission_semantics(inp, input_digest, ikey)
        if stage is MatterAnalysisStage.AUTHORITY_VIEW:
            return self._stage_authority_view(inp, input_digest, ikey)
        if stage is MatterAnalysisStage.LEGAL_LOGIC:
            return self._stage_legal_logic(inp, input_digest, ikey)
        if stage is MatterAnalysisStage.TEMPORAL_CANDIDATES:
            return self._stage_temporal(inp, input_digest, ikey)
        if stage is MatterAnalysisStage.DOSSIER:
            return self._stage_dossier(inp, input_digest, ikey)
        if stage is MatterAnalysisStage.BUNDLE:
            return self._stage_bundle(inp, input_digest, ikey)
        raise MatterAnalysisError(f"unknown stage {stage!r}", code="unknown_stage")

    def _stage_authorize(
        self, inp: MatterAnalysisInput, input_digest: str, ikey: str
    ) -> _StageOutcome:
        disclosure = self._workspace["disclosure"]
        reasons = [
            MatterAnalysisReasonCode.AUTHORIZED.value,
            MatterAnalysisReasonCode.STAGE_COMMITTED.value,
        ]
        diagnostics = {
            "classification": disclosure.value,
            "matter_id": inp.matter_id,
            "tenant_id": inp.tenant_id,
        }
        out = {
            "classification": disclosure.value,
            "output_digest": _canonical_digest(diagnostics),
        }
        if requires_quarantine(disclosure) or inp.force_quarantine:
            self._workspace["hard_quarantine"] = True
            reasons.append(MatterAnalysisReasonCode.QUARANTINE_CLASSIFICATION.value)
            record = StageRunRecord(
                stage=MatterAnalysisStage.AUTHORIZE,
                status=StageStatus.QUARANTINED,
                input_digest=input_digest,
                idempotency_key=ikey,
                executed=True,
                resumed=False,
                reused_by_digest=False,
                reason_codes=tuple(reasons),
                diagnostics=_frozen_str_map(diagnostics),
                output_digest=out["output_digest"],
                stage_disposition=MatterAnalysisDisposition.QUARANTINED.value,
            )
            return _StageOutcome(
                record=record,
                terminal_disposition=MatterAnalysisDisposition.QUARANTINED,
                output_summary=out,
            )

        record = StageRunRecord(
            stage=MatterAnalysisStage.AUTHORIZE,
            status=StageStatus.COMMITTED,
            input_digest=input_digest,
            idempotency_key=ikey,
            executed=True,
            resumed=False,
            reused_by_digest=False,
            reason_codes=tuple(reasons),
            diagnostics=_frozen_str_map(diagnostics),
            output_digest=out["output_digest"],
            stage_disposition="authorized",
        )
        return _StageOutcome(record=record, output_summary=out)

    def _stage_status_sync(
        self, inp: MatterAnalysisInput, input_digest: str, ikey: str
    ) -> _StageOutcome:
        snap = dict(inp.status_snapshot)
        if not snap:
            snap = {
                "application_number": inp.application_number or "unknown",
                "matter_id": inp.matter_id,
                "offline": True,
                "phase": "unknown",
                "source": "offline_snapshot",
            }
            # Empty status is a soft signal only; force_partial makes it hard.
            self._workspace.setdefault("soft_partial_signals", []).append(
                "status_empty"
            )
        status_digest = _canonical_digest(snap)
        self._workspace["status_digest"] = status_digest
        summary = {
            "application_number": snap.get("application_number")
            or inp.application_number,
            "output_digest": status_digest,
            "status_keys": sorted(str(k) for k in snap.keys())[:32],
        }
        record = StageRunRecord(
            stage=MatterAnalysisStage.STATUS_SYNC,
            status=StageStatus.COMMITTED,
            input_digest=input_digest,
            idempotency_key=ikey,
            executed=True,
            resumed=False,
            reused_by_digest=False,
            reason_codes=(
                MatterAnalysisReasonCode.STATUS_SYNCED.value,
                MatterAnalysisReasonCode.STAGE_COMMITTED.value,
            ),
            diagnostics=_frozen_str_map(
                {
                    "application_number": str(
                        summary.get("application_number") or ""
                    ),
                    "offline": "true" if inp.offline else "false",
                    "status_digest": status_digest,
                }
            ),
            output_digest=status_digest,
            stage_disposition="synced",
        )
        return _StageOutcome(record=record, output_summary=summary)

    def _stage_document_sync(
        self, inp: MatterAnalysisInput, input_digest: str, ikey: str
    ) -> _StageOutcome:
        digests = [d.content_sha256 or "" for d in inp.documents]
        self._workspace["document_digests"] = digests
        if not inp.documents:
            self._workspace.setdefault("soft_partial_signals", []).append(
                "no_documents"
            )
        out_digest = _canonical_digest(
            {"documents": inp.documents_identity(), "matter_id": inp.matter_id}
        )
        summary = {
            "document_count": len(inp.documents),
            "document_digests": digests,
            "document_ids": [d.document_id for d in inp.documents],
            "output_digest": out_digest,
        }
        record = StageRunRecord(
            stage=MatterAnalysisStage.DOCUMENT_SYNC,
            status=StageStatus.COMMITTED,
            input_digest=input_digest,
            idempotency_key=ikey,
            executed=True,
            resumed=False,
            reused_by_digest=False,
            reason_codes=(
                MatterAnalysisReasonCode.DOCUMENTS_SYNCED.value,
                MatterAnalysisReasonCode.STAGE_COMMITTED.value,
            ),
            diagnostics=_frozen_str_map(
                {
                    "document_count": str(len(inp.documents)),
                    "output_digest": out_digest,
                }
            ),
            output_digest=out_digest,
            stage_disposition="synced",
        )
        return _StageOutcome(record=record, output_summary=summary)

    def _stage_document_process(
        self, inp: MatterAnalysisInput, input_digest: str, ikey: str
    ) -> _StageOutcome:
        pipeline_results: list[dict[str, Any]] = []
        reasons: list[str] = [
            MatterAnalysisReasonCode.DOCUMENTS_PROCESSED.value,
            MatterAnalysisReasonCode.STAGE_COMMITTED.value,
        ]
        for doc in inp.documents:
            if doc.content_bytes is None:
                # Text-only / pre-extracted: record identity without pipeline.
                pipeline_results.append(
                    {
                        "document_id": doc.document_id,
                        "mode": "text_or_digest_only",
                        "content_sha256": doc.content_sha256,
                        "disposition": "skipped_no_bytes",
                    }
                )
                continue
            job_id = f"{inp.analysis_id or self._workspace['analysis_id']}:{doc.document_id}"
            result: DocumentPipelineResult = self._pipeline.process(
                DocumentPipelineInput(
                    job_id=job_id,
                    artifact_id=doc.document_id,
                    content_bytes=doc.content_bytes,
                    content_sha256=doc.content_sha256,
                    classification=doc.classification,
                    filename=doc.filename,
                    declared_mime=doc.declared_mime,
                    document_code=doc.document_code,
                    matter_id=inp.matter_id,
                    labels=dict(doc.labels),
                )
            )
            pipeline_results.append(
                {
                    "document_id": doc.document_id,
                    "disposition": result.disposition.value,
                    "success": result.success,
                    "content_sha256": result.content_sha256,
                    "derived_artifact_id": result.derived_artifact_id,
                }
            )
            if result.is_quarantined:
                # Document-level quarantine is soft unless the matter itself is
                # classified unknown / force_quarantine.
                self._workspace.setdefault("soft_partial_signals", []).append(
                    f"pipeline_quarantine:{doc.document_id}"
                )
                reasons.append(
                    MatterAnalysisReasonCode.QUARANTINE_CLASSIFICATION.value
                )
            elif not result.success:
                self._workspace.setdefault("soft_partial_signals", []).append(
                    f"pipeline:{doc.document_id}"
                )
                reasons.append(MatterAnalysisReasonCode.PARTIAL_COVERAGE.value)

        self._workspace["pipeline_results"] = pipeline_results
        out_digest = _canonical_digest(pipeline_results)
        summary = {
            "output_digest": out_digest,
            "pipeline_count": len(pipeline_results),
            "pipeline_results": pipeline_results,
        }
        terminal = None
        if self._workspace.get("quarantine_signals") and any(
            r.get("disposition") == PipelineDisposition.QUARANTINE.value
            for r in pipeline_results
        ):
            # Do not hard-stop here unless every document quarantined and force;
            # quarantine signals still aggregate at the end.
            pass

        record = StageRunRecord(
            stage=MatterAnalysisStage.DOCUMENT_PROCESS,
            status=StageStatus.COMMITTED,
            input_digest=input_digest,
            idempotency_key=ikey,
            executed=True,
            resumed=False,
            reused_by_digest=False,
            reason_codes=tuple(reasons[:_MAX_REASON_CODES]),
            diagnostics=_frozen_str_map(
                {
                    "pipeline_count": str(len(pipeline_results)),
                    "output_digest": out_digest,
                }
            ),
            output_digest=out_digest,
            stage_disposition="processed",
        )
        return _StageOutcome(
            record=record, terminal_disposition=terminal, output_summary=summary
        )

    def _stage_oa_semantics(
        self, inp: MatterAnalysisInput, input_digest: str, ikey: str
    ) -> _StageOutcome:
        oa_docs = [
            d
            for d in inp.documents
            if d.role in ("office_action", "oa")
            or (d.document_code or "").upper() in ("CTNF", "CTFR", "CTAV", "OA")
        ]
        results: list[dict[str, Any]] = []
        primary: OfficeActionSemanticsResult | None = None
        for doc in oa_docs:
            text = doc.text or ""
            if not text and doc.content_bytes:
                # Do not invent extraction; mark partial.
                self._workspace.setdefault("partial_signals", []).append(
                    f"oa_no_text:{doc.document_id}"
                )
                results.append(
                    {
                        "document_id": doc.document_id,
                        "disposition": "partial",
                        "reason": "no_text",
                    }
                )
                continue
            if not text:
                continue
            result = self._oa_semantics.analyze(
                OfficeActionSemanticsInput(
                    artifact_id=doc.document_id,
                    text=text,
                    document_code=doc.document_code,
                    classification=doc.classification,
                    labels=dict(doc.labels),
                )
            )
            primary = result
            self._workspace["oa_result"] = result
            results.append(
                {
                    "document_id": doc.document_id,
                    "disposition": result.disposition.value,
                    "output_digest": getattr(result, "result_digest", None)
                    or content_digest_of(result.to_dict())
                    if hasattr(result, "to_dict")
                    else _canonical_digest({"document_id": doc.document_id}),
                }
            )
            if result.disposition in (
                SemanticsDisposition.REVIEW,
                SemanticsDisposition.MALFORMED,
            ):
                self._workspace.setdefault("soft_review_signals", []).append(
                    f"oa:{doc.document_id}"
                )
            elif result.disposition is SemanticsDisposition.QUARANTINE:
                self._workspace.setdefault("soft_partial_signals", []).append(
                    f"oa_quarantine:{doc.document_id}"
                )
            elif result.disposition is SemanticsDisposition.REJECTED:
                self._workspace.setdefault("soft_partial_signals", []).append(
                    f"oa:{doc.document_id}"
                )

        if not oa_docs:
            self._workspace.setdefault("soft_partial_signals", []).append(
                "no_office_action"
            )
            results.append({"disposition": "skipped", "reason": "no_oa_documents"})

        out_digest = _canonical_digest(results)
        summary = {
            "oa_count": len(oa_docs),
            "output_digest": out_digest,
            "results": results,
        }
        if primary is not None:
            summary["primary_disposition"] = primary.disposition.value

        record = StageRunRecord(
            stage=MatterAnalysisStage.OFFICE_ACTION_SEMANTICS,
            status=StageStatus.COMMITTED,
            input_digest=input_digest,
            idempotency_key=ikey,
            executed=True,
            resumed=False,
            reused_by_digest=False,
            reason_codes=(
                MatterAnalysisReasonCode.OFFICE_ACTION_PARSED.value,
                MatterAnalysisReasonCode.STAGE_COMMITTED.value,
            ),
            diagnostics=_frozen_str_map(
                {
                    "oa_count": str(len(oa_docs)),
                    "output_digest": out_digest,
                }
            ),
            output_digest=out_digest,
            stage_disposition=summary.get("primary_disposition") or "parsed",
        )
        return _StageOutcome(record=record, output_summary=summary)

    def _stage_submission_semantics(
        self, inp: MatterAnalysisInput, input_digest: str, ikey: str
    ) -> _StageOutcome:
        sub_docs = [
            d
            for d in inp.documents
            if d.role
            not in ("office_action", "oa")
            and (d.document_code or "").upper()
            not in ("CTNF", "CTFR", "CTAV", "OA")
        ]
        package_docs: list[PackageDocumentInput] = []
        for doc in sub_docs:
            role = self._coerce_document_role(doc.role)
            package_docs.append(
                PackageDocumentInput(
                    document_id=doc.document_id,
                    role=role,
                    text=doc.text or "",
                    classification=doc.classification
                    or self._workspace["disclosure"],
                    media_type=doc.declared_mime,
                    content_digest=doc.content_sha256,
                    filename_hint=doc.filename,
                    labels=dict(doc.labels),
                )
            )
        results: list[dict[str, Any]] = []
        if package_docs:
            pkg_result: SubmissionPackageSemanticsResult = self._pkg_semantics.analyze(
                SubmissionPackageInput(
                    package_id=f"pkg:{self._workspace['analysis_id']}",
                    documents=tuple(package_docs),
                    matter_id=inp.matter_id,
                    classification=self._workspace["disclosure"],
                    labels=dict(inp.labels),
                )
            )
            self._workspace["pkg_result"] = pkg_result
            results.append(
                {
                    "disposition": pkg_result.disposition.value,
                    "package_id": getattr(pkg_result, "package_id", None),
                    "document_count": len(package_docs),
                }
            )
            if pkg_result.disposition in (
                PackageDisposition.REVIEW,
                PackageDisposition.MALFORMED,
            ):
                self._workspace.setdefault("soft_review_signals", []).append(
                    "submission"
                )
            elif pkg_result.disposition is PackageDisposition.QUARANTINE:
                self._workspace.setdefault("soft_partial_signals", []).append(
                    "submission_quarantine"
                )
            elif pkg_result.disposition in (
                PackageDisposition.PARTIAL,
                PackageDisposition.REJECTED,
            ):
                self._workspace.setdefault("soft_partial_signals", []).append(
                    "submission"
                )
        else:
            self._workspace.setdefault("soft_partial_signals", []).append(
                "no_submission_docs"
            )
            results.append(
                {"disposition": "skipped", "reason": "no_submission_documents"}
            )

        out_digest = _canonical_digest(results)
        summary = {
            "document_count": len(package_docs),
            "output_digest": out_digest,
            "results": results,
        }
        record = StageRunRecord(
            stage=MatterAnalysisStage.SUBMISSION_SEMANTICS,
            status=StageStatus.COMMITTED,
            input_digest=input_digest,
            idempotency_key=ikey,
            executed=True,
            resumed=False,
            reused_by_digest=False,
            reason_codes=(
                MatterAnalysisReasonCode.SUBMISSION_PARSED.value,
                MatterAnalysisReasonCode.STAGE_COMMITTED.value,
            ),
            diagnostics=_frozen_str_map(
                {
                    "document_count": str(len(package_docs)),
                    "output_digest": out_digest,
                }
            ),
            output_digest=out_digest,
            stage_disposition=(
                results[0].get("disposition") if results else "parsed"
            ),
        )
        return _StageOutcome(record=record, output_summary=summary)

    def _stage_authority_view(
        self, inp: MatterAnalysisInput, input_digest: str, ikey: str
    ) -> _StageOutcome:
        stale = bool(inp.authority_stale)
        auth_digest = inp.authority_digest or _canonical_digest(
            {
                "as_of_utc": inp.as_of_utc,
                "snapshot_id": inp.authority_snapshot_id or "offline",
            }
        )
        authority = {
            "as_of_utc": inp.as_of_utc,
            "authority_digest": auth_digest,
            "snapshot_id": inp.authority_snapshot_id or "authority:offline",
            "stale": stale,
        }
        self._workspace["authority"] = authority
        self._workspace["stale_authority"] = stale
        reasons = [
            MatterAnalysisReasonCode.AUTHORITY_VIEW_SELECTED.value,
            MatterAnalysisReasonCode.STAGE_COMMITTED.value,
        ]
        if stale:
            reasons.append(MatterAnalysisReasonCode.STALE_AUTHORITY.value)
        out_digest = _canonical_digest(authority)
        summary = {
            "authority": authority,
            "output_digest": out_digest,
            "stale_authority": stale,
        }
        # Stale authority is not a mid-pipeline hard stop: later stages still
        # run so the DAG is complete, but top-level disposition will be
        # stale_authority (not success).
        record = StageRunRecord(
            stage=MatterAnalysisStage.AUTHORITY_VIEW,
            status=StageStatus.COMMITTED,
            input_digest=input_digest,
            idempotency_key=ikey,
            executed=True,
            resumed=False,
            reused_by_digest=False,
            reason_codes=tuple(reasons),
            diagnostics=_frozen_str_map(
                {
                    "authority_digest": auth_digest,
                    "stale": "true" if stale else "false",
                }
            ),
            output_digest=out_digest,
            stage_disposition="stale" if stale else "current",
        )
        return _StageOutcome(record=record, output_summary=summary)

    def _stage_legal_logic(
        self, inp: MatterAnalysisInput, input_digest: str, ikey: str
    ) -> _StageOutcome:
        """Evaluate legal/logic gates and fail-closed proof disposition.

        Heavy leaf compliance/instruction constructors require full span
        provenance; this stage binds available workspace receipts and exercises
        the proof executor when a fixture problem is constructible. Explicit
        force flags drive top-level fail-closed outcomes for tests and
        incomplete authority.
        """
        reasons = [
            MatterAnalysisReasonCode.LEGAL_LOGIC_EVALUATED.value,
            MatterAnalysisReasonCode.STAGE_COMMITTED.value,
        ]
        proof_unknown = bool(inp.force_proof_unknown)
        review_required = bool(inp.force_review_required)
        proof_outcome = "not_run"

        if proof_unknown:
            proof_outcome = ProofOutcome.UNKNOWN.value
        else:
            try:
                problem = build_fixture_problem(FixtureKind.SATISFIABLE)
                proof_result = self._proofs.execute(problem)
                outcome = proof_result.outcome
                proof_outcome = (
                    outcome.value if isinstance(outcome, ProofOutcome) else str(outcome)
                )
                if outcome in (
                    ProofOutcome.UNKNOWN,
                    ProofOutcome.ERROR,
                    ProofOutcome.TIMEOUT,
                ):
                    # Soft unless forced; incomplete proofs do not invent certainty.
                    self._workspace.setdefault("soft_review_signals", []).append(
                        "proof_incomplete"
                    )
            except Exception:
                proof_outcome = "executor_unavailable"
                self._workspace.setdefault("soft_partial_signals", []).append(
                    "proof_executor"
                )

        if inp.force_proof_unknown:
            proof_unknown = True
            proof_outcome = ProofOutcome.UNKNOWN.value

        self._workspace["proof_outcome"] = proof_outcome
        self._workspace["proof_unknown"] = proof_unknown
        if review_required:
            self._workspace["hard_review"] = True

        if proof_unknown:
            reasons.append(MatterAnalysisReasonCode.PROOF_UNKNOWN.value)
        if review_required:
            reasons.append(MatterAnalysisReasonCode.REVIEW_REQUIRED.value)

        # Record that leaf processors are available for later serialized workflows.
        compliance_disp = "deferred_to_evidence_binding"
        instruction_disp = "deferred_to_authority_binding"
        if self._compliance is not None:
            compliance_disp = "processor_ready"
        if self._instruction is not None:
            instruction_disp = "processor_ready"

        out_digest = _canonical_digest(
            {
                "compliance": compliance_disp,
                "instruction": instruction_disp,
                "proof": proof_outcome,
                "proof_unknown": proof_unknown,
                "review_required": review_required,
                "oa_out": (
                    self._workspace.get("stage_outputs", {})
                    .get(MatterAnalysisStage.OFFICE_ACTION_SEMANTICS.value, {})
                    .get("output_digest")
                ),
                "pkg_out": (
                    self._workspace.get("stage_outputs", {})
                    .get(MatterAnalysisStage.SUBMISSION_SEMANTICS.value, {})
                    .get("output_digest")
                ),
                "authority_out": (
                    self._workspace.get("stage_outputs", {})
                    .get(MatterAnalysisStage.AUTHORITY_VIEW.value, {})
                    .get("output_digest")
                ),
            }
        )
        summary = {
            "compliance_disposition": compliance_disp,
            "instruction_disposition": instruction_disp,
            "output_digest": out_digest,
            "proof_outcome": proof_outcome,
            "proof_unknown": proof_unknown,
            "review_required": review_required,
        }
        record = StageRunRecord(
            stage=MatterAnalysisStage.LEGAL_LOGIC,
            status=StageStatus.COMMITTED,
            input_digest=input_digest,
            idempotency_key=ikey,
            executed=True,
            resumed=False,
            reused_by_digest=False,
            reason_codes=tuple(reasons[:_MAX_REASON_CODES]),
            diagnostics=_frozen_str_map(
                {
                    "compliance": compliance_disp,
                    "instruction": instruction_disp,
                    "proof_unknown": "true" if proof_unknown else "false",
                }
            ),
            output_digest=out_digest,
            stage_disposition=(
                "proof_unknown"
                if proof_unknown
                else ("review" if review_required else "evaluated")
            ),
        )
        return _StageOutcome(record=record, output_summary=summary)

    def _stage_temporal(
        self, inp: MatterAnalysisInput, input_digest: str, ikey: str
    ) -> _StageOutcome:
        reasons = [
            MatterAnalysisReasonCode.TEMPORAL_CANDIDATES_COMPUTED.value,
            MatterAnalysisReasonCode.STAGE_COMMITTED.value,
        ]
        snap = dict(inp.status_snapshot)
        mailing = snap.get("mailing_date") or snap.get("mail_date")
        sources: list[DeadlineSourceInput] = []
        if mailing:
            sources.append(
                DeadlineSourceInput(
                    source_id=f"src:{self._workspace['analysis_id']}:mail",
                    source_span_id=f"span:{self._workspace['analysis_id']}:mail",
                    surface_text=f"Mailing date {mailing}; shortened statutory period 3 months",
                    period_amount=3,
                    period_unit=PeriodUnit.MONTHS,
                    mailing_date=str(mailing),
                )
            )
        deadline_disp = "skipped"
        try:
            if sources or mailing:
                dl: DeadlineAnalysisResult = self._deadlines.analyze(
                    DeadlineAnalysisInput(
                        matter_id=inp.matter_id,
                        analysis_id=self._workspace["analysis_id"],
                        sources=tuple(sources),
                        mailing_date=str(mailing) if mailing else None,
                        classification=self._workspace["disclosure"],
                        labels=dict(inp.labels),
                    )
                )
                self._workspace["deadlines"] = dl
                deadline_disp = dl.disposition.value
                if dl.disposition is DeadlineDisposition.QUARANTINE:
                    self._workspace.setdefault("soft_partial_signals", []).append(
                        "deadlines_quarantine"
                    )
                elif dl.disposition in (
                    DeadlineDisposition.PARTIAL,
                    DeadlineDisposition.EMPTY,
                    DeadlineDisposition.UNKNOWN,
                ):
                    self._workspace.setdefault("soft_partial_signals", []).append(
                        "deadlines"
                    )
            else:
                self._workspace.setdefault("soft_partial_signals", []).append(
                    "no_deadline_basis"
                )
                deadline_disp = "no_basis"
        except Exception:
            self._workspace.setdefault("soft_partial_signals", []).append(
                "deadline_error"
            )
            deadline_disp = "error"

        out_digest = _canonical_digest(
            {"deadline_disposition": deadline_disp, "mailing": mailing}
        )
        summary = {
            "deadline_disposition": deadline_disp,
            "mailing_date": mailing,
            "output_digest": out_digest,
        }
        record = StageRunRecord(
            stage=MatterAnalysisStage.TEMPORAL_CANDIDATES,
            status=StageStatus.COMMITTED,
            input_digest=input_digest,
            idempotency_key=ikey,
            executed=True,
            resumed=False,
            reused_by_digest=False,
            reason_codes=tuple(reasons),
            diagnostics=_frozen_str_map(
                {
                    "deadline_disposition": deadline_disp,
                    "output_digest": out_digest,
                }
            ),
            output_digest=out_digest,
            stage_disposition=deadline_disp,
        )
        return _StageOutcome(record=record, output_summary=summary)

    def _stage_dossier(
        self, inp: MatterAnalysisInput, input_digest: str, ikey: str
    ) -> _StageOutcome:
        reasons = [
            MatterAnalysisReasonCode.DOSSIER_ASSEMBLED.value,
            MatterAnalysisReasonCode.STAGE_COMMITTED.value,
        ]
        sections: list[CompactSectionInput] = []
        for stage_name, summary in sorted(
            (self._workspace.get("stage_outputs") or {}).items()
        ):
            digest = (summary or {}).get("output_digest") or sha256_hex(stage_name)
            sections.append(
                CompactSectionInput(
                    kind="validation_receipt",
                    record_id=f"stage:{stage_name}",
                    schema_version=MATTER_ANALYSIS_SCHEMA_VERSION,
                    content_digest=digest
                    if _SHA256_RE.match(str(digest))
                    else sha256_hex(str(digest)),
                    classification=self._workspace["disclosure"],
                    source_artifact_ids=tuple(d.document_id for d in inp.documents[:8]),
                    labels={"stage": stage_name},
                )
            )
        if inp.force_partial:
            self._workspace["hard_partial"] = True

        soft_partials = tuple(self._workspace.get("soft_partial_signals") or ())
        try:
            dossier = self._dossier.assemble(
                DossierInput(
                    matter_id=inp.matter_id,
                    analysis_id=self._workspace["analysis_id"],
                    compact_sections=tuple(sections),
                    seed_classification=self._workspace["disclosure"],
                    as_of_utc=inp.as_of_utc,
                    labels=dict(inp.labels),
                    unsupported_checks=soft_partials,
                )
            )
            self._workspace["dossier"] = dossier
            dossier_id = dossier.dossier_id
            dossier_disp = dossier.disposition.value
            if hasattr(dossier, "content_digest") and dossier.content_digest:
                out_digest = dossier.content_digest
            elif hasattr(dossier, "to_dict"):
                out_digest = content_digest_of(dossier.to_dict())
            else:
                out_digest = _canonical_digest({"dossier_id": dossier_id})
            if dossier.disposition is DossierDisposition.QUARANTINE:
                self._workspace["hard_quarantine"] = True
            elif dossier.disposition in (
                DossierDisposition.REVIEW,
                DossierDisposition.UNKNOWN,
            ):
                self._workspace.setdefault("soft_review_signals", []).append("dossier")
            elif dossier.disposition in (
                DossierDisposition.PARTIAL,
                DossierDisposition.EMPTY,
            ):
                self._workspace.setdefault("soft_partial_signals", []).append("dossier")
        except Exception as exc:
            # Fail closed to soft partial rather than inventing a complete dossier.
            self._workspace.setdefault("soft_partial_signals", []).append(
                "dossier_error"
            )
            dossier_id = f"dossier:{self._workspace['analysis_id']}:partial"
            dossier_disp = "partial"
            out_digest = sha256_hex(f"dossier-error:{exc!s}"[:256])
            reasons.append(MatterAnalysisReasonCode.PARTIAL_COVERAGE.value)

        summary = {
            "dossier_disposition": dossier_disp,
            "dossier_id": dossier_id,
            "output_digest": out_digest,
            "partial": bool(self._workspace.get("hard_partial")),
        }
        self._workspace["dossier_id"] = dossier_id
        record = StageRunRecord(
            stage=MatterAnalysisStage.DOSSIER,
            status=StageStatus.COMMITTED,
            input_digest=input_digest,
            idempotency_key=ikey,
            executed=True,
            resumed=False,
            reused_by_digest=False,
            reason_codes=tuple(reasons),
            diagnostics=_frozen_str_map(
                {
                    "dossier_disposition": str(dossier_disp),
                    "dossier_id": str(dossier_id),
                }
            ),
            output_digest=out_digest,
            stage_disposition=str(dossier_disp),
        )
        return _StageOutcome(record=record, output_summary=summary)

    def _stage_bundle(
        self, inp: MatterAnalysisInput, input_digest: str, ikey: str
    ) -> _StageOutcome:
        reasons = [
            MatterAnalysisReasonCode.BUNDLE_ASSEMBLED.value,
            MatterAnalysisReasonCode.STAGE_COMMITTED.value,
        ]
        sections: list[BundleSectionRef] = []
        for idx, (stage_name, summary) in enumerate(
            sorted((self._workspace.get("stage_outputs") or {}).items())
        ):
            digest = (summary or {}).get("output_digest") or sha256_hex(stage_name)
            if not _SHA256_RE.match(str(digest)):
                digest = sha256_hex(str(digest))
            sections.append(
                BundleSectionRef(
                    section_id=f"sec:{self._workspace['analysis_id']}:{idx}",
                    kind=BundleSectionKind.VALIDATION_RECEIPT,
                    record_id=f"stage:{stage_name}",
                    content_digest=str(digest),
                    classification=self._workspace["disclosure"],
                    schema_version=MATTER_ANALYSIS_SCHEMA_VERSION,
                    source_artifact_ids=tuple(
                        d.document_id for d in inp.documents[:8]
                    ),
                )
            )
        warnings: list[BundleWarning] = []
        for signal in self._workspace.get("soft_partial_signals") or []:
            warnings.append(
                BundleWarning(
                    code=BundleWarningCode.UNSUPPORTED_CHECK,
                    message=f"partial signal: {signal}"[:256],
                )
            )
        for signal in self._workspace.get("soft_review_signals") or []:
            warnings.append(
                BundleWarning(
                    code=BundleWarningCode.UNSUPPORTED_CHECK,
                    message=f"review signal: {signal}"[:256],
                )
            )

        bundle = build_analysis_bundle(
            matter_id=inp.matter_id,
            analysis_id=self._workspace["analysis_id"],
            sections=tuple(sections),
            input_artifact_ids=tuple(d.document_id for d in inp.documents),
            seed_classification=self._workspace["disclosure"],
            warnings=tuple(warnings),
            labels=dict(inp.labels),
            ruleset_versions={
                "matter_analysis": MATTER_ANALYSIS_SCHEMA_VERSION,
            },
            model_versions={"parser_digest": parser_digest()},
        )
        self._workspace["bundle"] = bundle
        if bundle.disposition is BundleDisposition.QUARANTINE:
            self._workspace["hard_quarantine"] = True
        elif bundle.disposition in (
            BundleDisposition.REVIEW,
            BundleDisposition.UNKNOWN,
        ):
            self._workspace.setdefault("soft_review_signals", []).append("bundle")
        elif bundle.disposition in (
            BundleDisposition.PARTIAL,
            BundleDisposition.EMPTY,
        ):
            self._workspace.setdefault("soft_partial_signals", []).append("bundle")

        out_digest = bundle.bundle_digest
        summary = {
            "bundle_digest": out_digest,
            "bundle_disposition": bundle.disposition.value,
            "bundle_id": bundle.bundle_id,
            "output_digest": out_digest,
        }
        self._workspace["bundle_id"] = bundle.bundle_id
        record = StageRunRecord(
            stage=MatterAnalysisStage.BUNDLE,
            status=StageStatus.COMMITTED,
            input_digest=input_digest,
            idempotency_key=ikey,
            executed=True,
            resumed=False,
            reused_by_digest=False,
            reason_codes=tuple(reasons),
            diagnostics=_frozen_str_map(
                {
                    "bundle_digest": out_digest,
                    "bundle_id": bundle.bundle_id,
                }
            ),
            output_digest=out_digest,
            stage_disposition=bundle.disposition.value,
        )
        return _StageOutcome(record=record, output_summary=summary)


    @staticmethod
    def _coerce_document_role(role: str | DocumentRole | None) -> DocumentRole:
        if isinstance(role, DocumentRole):
            return role
        text = str(role or "attachment").strip().lower()
        aliases = {
            "office_action": DocumentRole.ATTACHMENT,
            "oa": DocumentRole.ATTACHMENT,
            "remarks": DocumentRole.REMARKS,
            "claims": DocumentRole.CLAIMS,
            "amendment": DocumentRole.AMENDMENT,
            "specification": DocumentRole.SPECIFICATION,
            "drawings": DocumentRole.DRAWINGS,
            "form": DocumentRole.FORM,
            "fee": DocumentRole.FEE,
            "other": DocumentRole.ATTACHMENT,
        }
        if text in aliases:
            return aliases[text]
        try:
            return DocumentRole(text)
        except ValueError:
            return DocumentRole.ATTACHMENT


# ---------------------------------------------------------------------------
# Public factories
# ---------------------------------------------------------------------------


def create_matter_analysis_processor(
    *,
    checkpoint_dir: str | Path | None = None,
    **kwargs: Any,
) -> MatterAnalysisProcessor:
    """Create a :class:`MatterAnalysisProcessor` with optional FS checkpoints."""
    store = MatterAnalysisCheckpointStore(root=checkpoint_dir)
    return MatterAnalysisProcessor(checkpoint_store=store, **kwargs)


def analyze_matter(
    value: MatterAnalysisInput | Mapping[str, Any] | None = None,
    /,
    **kwargs: Any,
) -> MatterAnalysisResult:
    """One-shot helper that constructs a default processor and analyzes."""
    return MatterAnalysisProcessor().analyze(value, **kwargs)


__all__ = [
    "MATTER_ANALYSIS_INTERFACE",
    "MATTER_ANALYSIS_SCHEMA_VERSION",
    "MATTER_ANALYSIS_STAGE_ORDER",
    "AnalysisCheckpoint",
    "InjectedStageFailure",
    "MatterAnalysisCheckpointStore",
    "MatterAnalysisDisposition",
    "MatterAnalysisError",
    "MatterAnalysisInput",
    "MatterAnalysisProcessor",
    "MatterAnalysisReasonCode",
    "MatterAnalysisResult",
    "MatterAnalysisStage",
    "MatterDocumentInput",
    "StageCheckpoint",
    "StageRunRecord",
    "StageStatus",
    "analyze_matter",
    "create_matter_analysis_processor",
    "parser_digest",
    "sha256_hex",
    "stage_idempotency_key",
]
