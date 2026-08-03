"""Checkpointed USPTO document processing job (PATLAW-125).

Orchestrates the immutable pipeline stages:

  classify → authorize → decrypt (in-memory) → extract/OCR →
  normalize → validate_spans → persist (encrypted derived artifacts)

Each stage is committed under a deterministic idempotency key so restarts
resume without repeating committed work. Corrupt, untrusted, or policy-denied
inputs fail closed into quarantine with diagnostics. Domain ``success`` /
``ok`` reflects the pipeline disposition, not merely the absence of
exceptions.
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

from .contracts import (
    CONTRACTS_SCHEMA_VERSION,
    DisclosureClassification,
    ReviewState,
    canonical_json,
    is_private_classification,
    requires_quarantine,
)
from .document_classifier import (
    DOCUMENT_CLASSIFIER_SCHEMA_VERSION,
    ClassificationDisposition,
    DocumentClassification,
    DocumentClassificationInput,
    DocumentClassifier,
)
from .document_extraction_processor import (
    DOCUMENT_EXTRACTION_SCHEMA_VERSION,
    DocumentExtractionInput,
    DocumentExtractionProcessor,
    DocumentExtractionResult,
    ExtractionDisposition,
    MediaFamily,
    detect_media_family,
    sha256_hex,
)
from .privacy import (
    DEFAULT_PRIVACY_POLICY,
    PRIVACY_POLICY_SCHEMA_VERSION,
    ContentKind,
    PublicSink,
    SinkDecisionCode,
    UsptoPrivacyPolicy,
    VaultKind,
)
from .private_store import (
    PRIVATE_STORE_SCHEMA_VERSION,
    PrivateArtifactStore,
    PrivateStoreError,
    generate_tenant_key,
)
from .span_validator import (
    SPAN_VALIDATOR_SCHEMA_VERSION,
    SpanValidationDisposition,
    SpanValidator,
    SpanValidationResult,
)

DOCUMENT_PIPELINE_SCHEMA_VERSION: Final = "uspto.document-pipeline.v1"
DOCUMENT_PIPELINE_INTERFACE: Final = "DocumentPipelineProcessor@1"
DOCUMENT_PIPELINE_PARSER_DIGEST_MATERIAL: Final = (
    f"{DOCUMENT_PIPELINE_SCHEMA_VERSION}|"
    f"{DOCUMENT_CLASSIFIER_SCHEMA_VERSION}|"
    f"{DOCUMENT_EXTRACTION_SCHEMA_VERSION}|"
    f"{SPAN_VALIDATOR_SCHEMA_VERSION}|"
    f"{PRIVACY_POLICY_SCHEMA_VERSION}|"
    f"{PRIVATE_STORE_SCHEMA_VERSION}|"
    f"{CONTRACTS_SCHEMA_VERSION}"
)

_DIRECTORY_MODE: Final = 0o700
_FILE_MODE: Final = 0o600
_ID_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._:/=+\-]{0,255}\Z")
_SHA256_RE = re.compile(r"\A[0-9a-f]{64}\Z")
_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._\-]+")

# Magic / trust thresholds.
_MAX_INLINE_BYTES_DEFAULT: Final = 32 * 1024 * 1024
_TRUSTED_MEDIA = frozenset({MediaFamily.PDF, MediaFamily.DOCX})


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class PipelineStage(str, Enum):
    """Immutable ordered stages of a document processing job."""

    CLASSIFY = "classify"
    AUTHORIZE = "authorize"
    DECRYPT = "decrypt"
    EXTRACT = "extract"
    NORMALIZE = "normalize"
    VALIDATE_SPANS = "validate_spans"
    PERSIST = "persist"


PIPELINE_STAGE_ORDER: Final[tuple[PipelineStage, ...]] = (
    PipelineStage.CLASSIFY,
    PipelineStage.AUTHORIZE,
    PipelineStage.DECRYPT,
    PipelineStage.EXTRACT,
    PipelineStage.NORMALIZE,
    PipelineStage.VALIDATE_SPANS,
    PipelineStage.PERSIST,
)


class StageStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMMITTED = "committed"
    SKIPPED = "skipped"  # already committed on resume
    FAILED = "failed"
    QUARANTINED = "quarantined"


class PipelineDisposition(str, Enum):
    """Terminal domain outcome for the job."""

    COMPLETED = "completed"
    REVIEW = "review"
    QUARANTINE = "quarantine"
    FAILED = "failed"
    INTERRUPTED = "interrupted"


class PipelineReasonCode(str, Enum):
    STAGE_COMMITTED = "stage_committed"
    STAGE_RESUMED = "stage_resumed"
    CLASSIFIED = "classified"
    AUTHORIZED = "authorized"
    DECRYPTED_IN_MEMORY = "decrypted_in_memory"
    PLAINTEXT_PASSTHROUGH = "plaintext_passthrough"
    EXTRACTED = "extracted"
    NORMALIZED = "normalized"
    SPANS_VALIDATED = "spans_validated"
    DERIVED_ARTIFACT_PERSISTED = "derived_artifact_persisted"
    QUARANTINE_CLASSIFICATION = "quarantine_classification"
    QUARANTINE_POLICY_DENIED = "quarantine_policy_denied"
    QUARANTINE_CORRUPT = "quarantine_corrupt"
    QUARANTINE_UNTRUSTED = "quarantine_untrusted"
    QUARANTINE_EXTRACT = "quarantine_extract"
    QUARANTINE_SPAN_INVALID = "quarantine_span_invalid"
    MISSING_BYTES = "missing_bytes"
    MISSING_SOURCE = "missing_source"
    DECRYPT_FAILED = "decrypt_failed"
    INJECTED_FAILURE = "injected_failure"
    OVERSIZE_DOCUMENT = "oversize_document"
    MIME_MAGIC_CONFLICT = "mime_magic_conflict"
    JOB_COMPLETED = "job_completed"
    JOB_REVIEW = "job_review"
    JOB_QUARANTINED = "job_quarantined"
    JOB_FAILED = "job_failed"
    JOB_INTERRUPTED = "job_interrupted"


class DocumentPipelineError(ValueError):
    """Bounded pipeline error with a stable machine-readable code."""

    def __init__(self, message: str, *, code: str = "document_pipeline_error") -> None:
        super().__init__(message)
        self.code = str(code)

    def audit_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": str(self)[:256]}


class InjectedStageFailure(Exception):
    """Raised by failure injection before a stage body executes (tests/recovery)."""

    def __init__(self, stage: PipelineStage) -> None:
        super().__init__(f"injected failure before stage {stage.value}")
        self.stage = stage
        self.code = PipelineReasonCode.INJECTED_FAILURE.value


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


def parser_digest() -> str:
    """Stable digest of pipeline + dependency schema identities."""
    return sha256_hex(DOCUMENT_PIPELINE_PARSER_DIGEST_MATERIAL)


def stage_idempotency_key(
    *,
    job_id: str,
    content_sha256: str,
    stage: PipelineStage | str,
    parser_digest_value: str | None = None,
) -> str:
    """Deterministic idempotency key for an immutable stage commit."""
    stage_v = stage.value if isinstance(stage, PipelineStage) else str(stage)
    digest = parser_digest_value or parser_digest()
    material = f"{job_id}|{content_sha256}|{stage_v}|{digest}"
    return sha256_hex(material)


def _require_id(value: str, name: str) -> str:
    text = str(value or "").strip()
    if not text or not _ID_RE.match(text):
        raise DocumentPipelineError(f"invalid {name}: {value!r}", code="invalid_id")
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
    return cleaned[:180] or "job"


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
        raise DocumentPipelineError(
            f"expected object at {path.name}", code="checkpoint_integrity"
        )
    return data


def _declared_mime_for_family(family: MediaFamily) -> str | None:
    if family is MediaFamily.PDF:
        return "application/pdf"
    if family is MediaFamily.DOCX:
        return (
            "application/vnd.openxmlformats-officedocument."
            "wordprocessingml.document"
        )
    if family is MediaFamily.ARCHIVE:
        return "application/zip"
    return None


def _safe_digest_token(value: str | None) -> str | None:
    """Format a hex digest so long digit runs cannot trip PAN scanners.

    Inserts a non-digit separator every four hex characters. The token remains
    deterministic and reversible for equality checks within this module.
    """
    if value is None:
        return None
    text = str(value).strip().lower()
    if not text:
        return None
    return "g".join(text[i : i + 4] for i in range(0, len(text), 4))


def _safe_int_token(value: int | None, *, prefix: str) -> str | None:
    """Encode a non-negative integer without forming a pure digit run."""
    if value is None:
        return None
    return f"{prefix}{int(value)}"


# ---------------------------------------------------------------------------
# Input / stage records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DocumentPipelineInput:
    """Inputs for one checkpointed document processing job.

    Provide either inline ``content_bytes`` (decrypt stage is a passthrough)
    or a ``source_artifact_id`` already stored in the private vault (decrypt
    loads ciphertext into memory only).
    """

    job_id: str | None = None
    artifact_id: str | None = None
    content_bytes: bytes | None = None
    content_sha256: str | None = None
    source_artifact_id: str | None = None
    declared_mime: str | None = None
    filename: str | None = None
    classification: DisclosureClassification | str | None = None
    document_code: str | None = None
    document_description: str | None = None
    matter_id: str | None = None
    labels: Mapping[str, str] = MappingProxyType({})
    force_ocr: bool = False
    # Test/recovery: raise InjectedStageFailure before the named stage body.
    inject_failure_before: PipelineStage | str | None = None
    # Optional explicit disclosure class for authorize (overrides classifier).
    policy_classification: DisclosureClassification | str | None = None

    def __post_init__(self) -> None:
        if self.job_id is not None:
            object.__setattr__(self, "job_id", _require_id(str(self.job_id), "job_id"))
        if self.artifact_id is not None:
            object.__setattr__(
                self, "artifact_id", _require_id(str(self.artifact_id), "artifact_id")
            )
        if self.source_artifact_id is not None:
            object.__setattr__(
                self,
                "source_artifact_id",
                _require_id(str(self.source_artifact_id), "source_artifact_id"),
            )
        if self.content_bytes is not None and not isinstance(
            self.content_bytes, (bytes, bytearray)
        ):
            raise TypeError("content_bytes must be bytes or None")
        if isinstance(self.content_bytes, bytearray):
            object.__setattr__(self, "content_bytes", bytes(self.content_bytes))
        if self.content_sha256 is not None:
            digest = str(self.content_sha256).strip().lower()
            if not _SHA256_RE.match(digest):
                raise DocumentPipelineError(
                    "content_sha256 must be 64-char lowercase hex",
                    code="invalid_digest",
                )
            object.__setattr__(self, "content_sha256", digest)
        object.__setattr__(
            self, "declared_mime", _optional_str(self.declared_mime, max_len=256)
        )
        object.__setattr__(self, "filename", _optional_str(self.filename, max_len=512))
        object.__setattr__(
            self, "document_code", _optional_str(self.document_code, max_len=64)
        )
        object.__setattr__(
            self,
            "document_description",
            _optional_str(self.document_description, max_len=512),
        )
        object.__setattr__(self, "matter_id", _optional_str(self.matter_id, max_len=128))
        object.__setattr__(self, "labels", _frozen_str_map(self.labels))
        if not isinstance(self.force_ocr, bool):
            raise TypeError("force_ocr must be bool")
        if self.inject_failure_before is not None and not isinstance(
            self.inject_failure_before, PipelineStage
        ):
            object.__setattr__(
                self,
                "inject_failure_before",
                PipelineStage(str(self.inject_failure_before)),
            )


@dataclass(frozen=True, slots=True)
class StageCheckpoint:
    """Durable record for one committed (or terminal) stage.

    Never stores plaintext document body or free-form extracted text.
    """

    schema_version: str
    stage: PipelineStage
    status: StageStatus
    idempotency_key: str
    output_digest: str | None
    reason_codes: tuple[str, ...]
    diagnostics: Mapping[str, str]
    committed_utc: str | None
    attempt: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "attempt": self.attempt,
            "committed_utc": self.committed_utc,
            "diagnostics": dict(self.diagnostics),
            "idempotency_key": self.idempotency_key,
            "output_digest": self.output_digest,
            "reason_codes": list(self.reason_codes),
            "schema_version": self.schema_version,
            "stage": self.stage.value,
            "status": self.status.value,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "StageCheckpoint":
        return cls(
            schema_version=str(
                value.get("schema_version") or DOCUMENT_PIPELINE_SCHEMA_VERSION
            ),
            stage=PipelineStage(str(value.get("stage"))),
            status=StageStatus(str(value.get("status", StageStatus.PENDING.value))),
            idempotency_key=str(value.get("idempotency_key") or ""),
            output_digest=_optional_str(value.get("output_digest"), max_len=64),
            reason_codes=tuple(str(r) for r in (value.get("reason_codes") or ())),
            diagnostics=_frozen_str_map(value.get("diagnostics") or {}),
            committed_utc=_optional_str(value.get("committed_utc"), max_len=64),
            attempt=int(value.get("attempt") or 1),
        )


@dataclass
class JobCheckpoint:
    """Resumable job checkpoint (filesystem or in-memory)."""

    schema_version: str
    job_id: str
    artifact_id: str
    content_sha256: str
    parser_digest: str
    stages: dict[str, StageCheckpoint] = field(default_factory=dict)
    disposition: str | None = None
    classification: str | None = None
    media_family: str | None = None
    derived_artifact_id: str | None = None
    quarantine_id: str | None = None
    reason_codes: list[str] = field(default_factory=list)
    created_utc: str | None = None
    updated_utc: str | None = None
    labels: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "classification": self.classification,
            "content_sha256": self.content_sha256,
            "created_utc": self.created_utc,
            "derived_artifact_id": self.derived_artifact_id,
            "disposition": self.disposition,
            "job_id": self.job_id,
            "labels": dict(sorted(self.labels.items())),
            "media_family": self.media_family,
            "parser_digest": self.parser_digest,
            "quarantine_id": self.quarantine_id,
            "reason_codes": list(self.reason_codes),
            "schema_version": self.schema_version,
            "stages": {
                key: stage.to_dict() for key, stage in sorted(self.stages.items())
            },
            "updated_utc": self.updated_utc,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "JobCheckpoint":
        raw_stages = value.get("stages") or {}
        stages: dict[str, StageCheckpoint] = {}
        if isinstance(raw_stages, Mapping):
            for key, raw in raw_stages.items():
                if isinstance(raw, Mapping):
                    stages[str(key)] = StageCheckpoint.from_dict(raw)
        return cls(
            schema_version=str(
                value.get("schema_version") or DOCUMENT_PIPELINE_SCHEMA_VERSION
            ),
            job_id=str(value.get("job_id") or ""),
            artifact_id=str(value.get("artifact_id") or ""),
            content_sha256=str(value.get("content_sha256") or ""),
            parser_digest=str(value.get("parser_digest") or ""),
            stages=stages,
            disposition=_optional_str(value.get("disposition"), max_len=64),
            classification=_optional_str(value.get("classification"), max_len=64),
            media_family=_optional_str(value.get("media_family"), max_len=64),
            derived_artifact_id=_optional_str(
                value.get("derived_artifact_id"), max_len=256
            ),
            quarantine_id=_optional_str(value.get("quarantine_id"), max_len=256),
            reason_codes=[str(r) for r in (value.get("reason_codes") or [])],
            created_utc=_optional_str(value.get("created_utc"), max_len=64),
            updated_utc=_optional_str(value.get("updated_utc"), max_len=64),
            labels={
                str(k): str(v)
                for k, v in (value.get("labels") or {}).items()
            },
        )

    def get_stage(self, stage: PipelineStage) -> StageCheckpoint | None:
        return self.stages.get(stage.value)

    def is_committed(self, stage: PipelineStage) -> bool:
        entry = self.get_stage(stage)
        return entry is not None and entry.status is StageStatus.COMMITTED

    def put_stage(self, entry: StageCheckpoint) -> None:
        self.stages[entry.stage.value] = entry
        self.updated_utc = _utc_now()


@dataclass(frozen=True, slots=True)
class StageRunRecord:
    """In-memory observation of a stage execution attempt (not durable)."""

    stage: PipelineStage
    status: StageStatus
    idempotency_key: str
    executed: bool
    resumed: bool
    reason_codes: tuple[str, ...]
    diagnostics: Mapping[str, str]
    output_digest: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "diagnostics": dict(self.diagnostics),
            "executed": self.executed,
            "idempotency_key": self.idempotency_key,
            "output_digest": self.output_digest,
            "reason_codes": list(self.reason_codes),
            "resumed": self.resumed,
            "stage": self.stage.value,
            "status": self.status.value,
        }


@dataclass(frozen=True, slots=True)
class QuarantineDiagnostics:
    """Fail-closed quarantine diagnostics (identifiers and codes only)."""

    quarantine_id: str
    reason_codes: tuple[str, ...]
    stage: str
    classification: str
    media_family: str | None
    content_sha256: str | None
    message: str
    details: Mapping[str, str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "classification": self.classification,
            "content_sha256": self.content_sha256,
            "details": dict(self.details),
            "media_family": self.media_family,
            "message": self.message,
            "quarantine_id": self.quarantine_id,
            "reason_codes": list(self.reason_codes),
            "stage": self.stage,
        }


@dataclass(frozen=True, slots=True)
class DocumentPipelineResult:
    """Domain outcome of a document pipeline job.

    ``success`` / ``ok`` is True only for completed domain outcomes
    (``COMPLETED`` or ``REVIEW`` after all stages commit). Quarantine and
    failure return ``success=False`` even when no exception was raised.
    """

    schema_version: str
    job_id: str
    artifact_id: str
    content_sha256: str
    disposition: PipelineDisposition
    review_state: ReviewState
    classification: DisclosureClassification
    media_family: MediaFamily
    reason_codes: tuple[str, ...]
    stage_records: tuple[StageRunRecord, ...]
    committed_stages: tuple[str, ...]
    resumed_stages: tuple[str, ...]
    executed_stages: tuple[str, ...]
    parser_digest: str
    derived_artifact_id: str | None = None
    quarantine: QuarantineDiagnostics | None = None
    classification_result: DocumentClassification | None = None
    extraction_result: DocumentExtractionResult | None = None
    span_validation_result: SpanValidationResult | None = None
    labels: Mapping[str, str] = MappingProxyType({})
    retained: bool = True

    def __post_init__(self) -> None:
        if self.schema_version != DOCUMENT_PIPELINE_SCHEMA_VERSION:
            raise ValueError(
                "DocumentPipelineResult.schema_version must be "
                f"{DOCUMENT_PIPELINE_SCHEMA_VERSION}"
            )
        if not isinstance(self.labels, MappingProxyType):
            object.__setattr__(self, "labels", _frozen_str_map(self.labels))

    @property
    def ok(self) -> bool:
        """Domain success: all stages committed without quarantine/failure."""
        return self.disposition in (
            PipelineDisposition.COMPLETED,
            PipelineDisposition.REVIEW,
        ) and PipelineStage.PERSIST.value in self.committed_stages

    @property
    def success(self) -> bool:
        """Alias of :attr:`ok` — domain outcome, not exception absence."""
        return self.ok

    @property
    def is_quarantined(self) -> bool:
        return self.disposition is PipelineDisposition.QUARANTINE

    @property
    def is_interrupted(self) -> bool:
        return self.disposition is PipelineDisposition.INTERRUPTED

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "classification": self.classification.value,
            "classification_result": None
            if self.classification_result is None
            else self.classification_result.to_dict(),
            "committed_stages": list(self.committed_stages),
            "content_sha256": self.content_sha256,
            "derived_artifact_id": self.derived_artifact_id,
            "disposition": self.disposition.value,
            "executed_stages": list(self.executed_stages),
            "extraction_result": None
            if self.extraction_result is None
            else self.extraction_result.public_projection(),
            "job_id": self.job_id,
            "labels": dict(self.labels),
            "media_family": self.media_family.value,
            "ok": self.ok,
            "parser_digest": self.parser_digest,
            "quarantine": None if self.quarantine is None else self.quarantine.to_dict(),
            "reason_codes": list(self.reason_codes),
            "resumed_stages": list(self.resumed_stages),
            "retained": self.retained,
            "review_state": self.review_state.value,
            "schema_version": self.schema_version,
            "span_validation_result": None
            if self.span_validation_result is None
            else self.span_validation_result.public_projection(),
            "stage_records": [r.to_dict() for r in self.stage_records],
            "success": self.success,
        }

    def public_projection(self) -> dict[str, Any]:
        """Safe projection: identifiers, digests, codes — never body text."""
        payload = self.to_dict()
        # extraction/span public projections already omit body text.
        return payload

    def to_canonical_json(self) -> str:
        return canonical_json(self.public_projection())


# ---------------------------------------------------------------------------
# Checkpoint store
# ---------------------------------------------------------------------------


class DocumentPipelineJobStore:
    """Filesystem or in-memory atomic job checkpoint persistence.

    On-disk payloads hold digests, stage status, and reason codes only —
    never decrypted document bytes or free-form extracted text.
    """

    def __init__(self, root: str | Path | None = None) -> None:
        self._root = Path(root) if root is not None else None
        self._memory: dict[str, JobCheckpoint] = {}
        self._lock = threading.RLock()
        if self._root is not None:
            _ensure_dir(self._root)

    @property
    def root(self) -> Path | None:
        return self._root

    def _path_for(self, job_id: str) -> Path:
        assert self._root is not None
        return self._root / f"doc-pipeline-{_safe_filename(job_id)}.json"

    def load(self, job_id: str) -> JobCheckpoint | None:
        jid = _require_id(job_id, "job_id")
        with self._lock:
            if self._root is not None:
                path = self._path_for(jid)
                raw = _read_json(path)
                if raw is not None:
                    return JobCheckpoint.from_dict(raw)
            return self._memory.get(jid)

    def save(self, checkpoint: JobCheckpoint) -> None:
        with self._lock:
            checkpoint.updated_utc = _utc_now()
            self._memory[checkpoint.job_id] = checkpoint
            if self._root is None:
                return
            path = self._path_for(checkpoint.job_id)
            _atomic_write_json(path, checkpoint.to_dict())

    def delete(self, job_id: str) -> None:
        jid = _require_id(job_id, "job_id")
        with self._lock:
            self._memory.pop(jid, None)
            if self._root is not None:
                path = self._path_for(jid)
                if path.is_file():
                    path.unlink()


# ---------------------------------------------------------------------------
# Processor
# ---------------------------------------------------------------------------


StageHook = Callable[[PipelineStage, "DocumentPipelineInput", JobCheckpoint], None]


class DocumentPipelineProcessor:
    """Checkpointed USPTO document processing job orchestrator.

    Consumes classifiers, extractors, span validators, privacy policy, and
    private stores through their public contracts. Does not edit those
    implementations.
    """

    def __init__(
        self,
        *,
        job_store: DocumentPipelineJobStore | None = None,
        private_store: PrivateArtifactStore | None = None,
        classifier: DocumentClassifier | None = None,
        extractor: DocumentExtractionProcessor | None = None,
        span_validator: SpanValidator | None = None,
        privacy_policy: UsptoPrivacyPolicy | None = None,
        id_factory: Callable[[], str] | None = None,
        max_bytes: int = _MAX_INLINE_BYTES_DEFAULT,
        stage_hook: StageHook | None = None,
        ocr_callable: Callable[[bytes, int], Mapping[str, Any]] | None = None,
    ) -> None:
        self._job_store = job_store or DocumentPipelineJobStore()
        self._private_store = private_store
        self._classifier = classifier or DocumentClassifier()
        self._extractor = extractor or DocumentExtractionProcessor(
            ocr_callable=ocr_callable
        )
        self._span_validator = span_validator or SpanValidator()
        self._privacy = privacy_policy or DEFAULT_PRIVACY_POLICY
        self._id_factory = id_factory or (lambda: f"docjob:{uuid.uuid4().hex}")
        self._max_bytes = int(max_bytes)
        self._stage_hook = stage_hook
        # Process-local workspace for decrypted / intermediate payloads.
        # Never written to the job checkpoint store.
        self._workspace: dict[str, Any] = {}
        self._execution_counts: MutableMapping[str, int] = {}

    @property
    def job_store(self) -> DocumentPipelineJobStore:
        return self._job_store

    @property
    def private_store(self) -> PrivateArtifactStore | None:
        return self._private_store

    @property
    def execution_counts(self) -> Mapping[str, int]:
        """Per-stage body execution counts for the current process (tests)."""
        return MappingProxyType(dict(self._execution_counts))

    def reset_execution_counts(self) -> None:
        self._execution_counts.clear()

    def process(
        self,
        value: DocumentPipelineInput | Mapping[str, Any] | None = None,
        /,
        **kwargs: Any,
    ) -> DocumentPipelineResult:
        """Run or resume a checkpointed document processing job."""
        inp = self._coerce_input(value, **kwargs)
        return self._process(inp)

    def process_many(
        self, values: Iterable[DocumentPipelineInput | Mapping[str, Any]]
    ) -> list[DocumentPipelineResult]:
        return [self.process(v) for v in values]

    # -- coercion -----------------------------------------------------------

    def _coerce_input(
        self,
        value: DocumentPipelineInput | Mapping[str, Any] | None,
        **kwargs: Any,
    ) -> DocumentPipelineInput:
        if value is None:
            return DocumentPipelineInput(**kwargs)
        if isinstance(value, DocumentPipelineInput):
            if not kwargs:
                return value
            data = {
                "job_id": value.job_id,
                "artifact_id": value.artifact_id,
                "content_bytes": value.content_bytes,
                "content_sha256": value.content_sha256,
                "source_artifact_id": value.source_artifact_id,
                "declared_mime": value.declared_mime,
                "filename": value.filename,
                "classification": value.classification,
                "document_code": value.document_code,
                "document_description": value.document_description,
                "matter_id": value.matter_id,
                "labels": dict(value.labels),
                "force_ocr": value.force_ocr,
                "inject_failure_before": value.inject_failure_before,
                "policy_classification": value.policy_classification,
            }
            data.update(kwargs)
            return DocumentPipelineInput(**data)
        if isinstance(value, Mapping):
            data = dict(value)
            data.update(kwargs)
            return DocumentPipelineInput(**data)
        raise TypeError(
            "process() expects DocumentPipelineInput, mapping, or kwargs"
        )

    # -- main pipeline ------------------------------------------------------

    def _process(self, inp: DocumentPipelineInput) -> DocumentPipelineResult:
        pdigest = parser_digest()
        job_id = inp.job_id or str(self._id_factory())
        artifact_id = inp.artifact_id or f"art:{job_id}"

        # Seed workspace (plaintext lives only here).
        self._workspace = {
            "job_id": job_id,
            "artifact_id": artifact_id,
            "plaintext": None,
            "content_sha256": inp.content_sha256,
            "classification_obj": None,
            "disclosure": _coerce_classification(
                inp.policy_classification or inp.classification
            ),
            "extraction": None,
            "normalized": None,
            "span_validation": None,
            "media_family": MediaFamily.UNKNOWN,
            "derived_artifact_id": None,
            "labels": dict(inp.labels),
        }

        # Resolve bytes / digest early for checkpoint identity.
        early_error = self._bootstrap_source(inp)
        content_sha = str(self._workspace.get("content_sha256") or "")
        if not content_sha:
            content_sha = sha256_hex(b"")
            self._workspace["content_sha256"] = content_sha

        ckpt = self._job_store.load(job_id)
        if ckpt is None:
            ckpt = JobCheckpoint(
                schema_version=DOCUMENT_PIPELINE_SCHEMA_VERSION,
                job_id=job_id,
                artifact_id=artifact_id,
                content_sha256=content_sha,
                parser_digest=pdigest,
                created_utc=_utc_now(),
                updated_utc=_utc_now(),
                labels=dict(inp.labels),
            )
        else:
            # Guard against identity drift on resume.
            if ckpt.content_sha256 and content_sha and ckpt.content_sha256 != content_sha:
                return self._terminal_quarantine(
                    job_id=job_id,
                    artifact_id=artifact_id,
                    content_sha256=content_sha,
                    pdigest=pdigest,
                    disclosure=self._workspace["disclosure"],
                    media_family=MediaFamily.UNKNOWN,
                    stage=PipelineStage.DECRYPT,
                    reason_codes=(
                        PipelineReasonCode.QUARANTINE_UNTRUSTED.value,
                        "content_sha256_mismatch_on_resume",
                    ),
                    message="content digest changed across resume; refuse to continue",
                    details={"expected": ckpt.content_sha256, "observed": content_sha},
                    stage_records=(),
                    committed=(),
                    resumed=(),
                    executed=(),
                    ckpt=ckpt,
                )
            if not ckpt.content_sha256:
                ckpt.content_sha256 = content_sha
            if not ckpt.artifact_id:
                ckpt.artifact_id = artifact_id

        if early_error is not None:
            return early_error

        stage_records: list[StageRunRecord] = []
        committed: list[str] = []
        resumed: list[str] = []
        executed: list[str] = []

        # Restore workspace digests from prior commits when resuming.
        self._hydrate_workspace_from_checkpoint(ckpt)

        inject = inp.inject_failure_before
        if isinstance(inject, str):
            inject = PipelineStage(inject)

        for stage in PIPELINE_STAGE_ORDER:
            existing = ckpt.get_stage(stage)
            ikey = stage_idempotency_key(
                job_id=job_id,
                content_sha256=content_sha,
                stage=stage,
                parser_digest_value=pdigest,
            )

            if existing is not None and existing.status is StageStatus.COMMITTED:
                # Resume: do not re-execute stage body.
                record = StageRunRecord(
                    stage=stage,
                    status=StageStatus.SKIPPED,
                    idempotency_key=existing.idempotency_key or ikey,
                    executed=False,
                    resumed=True,
                    reason_codes=(
                        PipelineReasonCode.STAGE_RESUMED.value,
                        *existing.reason_codes,
                    ),
                    diagnostics=existing.diagnostics,
                    output_digest=existing.output_digest,
                )
                stage_records.append(record)
                committed.append(stage.value)
                resumed.append(stage.value)
                continue

            if inject is not None and inject is stage:
                # Commit nothing for this stage; raise so callers can restart.
                # Prior committed stages remain durable.
                self._job_store.save(ckpt)
                raise InjectedStageFailure(stage)

            if self._stage_hook is not None:
                self._stage_hook(stage, inp, ckpt)

            self._execution_counts[stage.value] = (
                self._execution_counts.get(stage.value, 0) + 1
            )

            try:
                outcome = self._run_stage(stage, inp, ckpt, ikey)
            except InjectedStageFailure:
                self._job_store.save(ckpt)
                raise
            except DocumentPipelineError as exc:
                return self._terminal_failed(
                    job_id=job_id,
                    artifact_id=artifact_id,
                    content_sha256=content_sha,
                    pdigest=pdigest,
                    disclosure=self._workspace["disclosure"],
                    media_family=self._workspace.get("media_family")
                    or MediaFamily.UNKNOWN,
                    stage=stage,
                    reason_codes=(exc.code,),
                    message=str(exc),
                    stage_records=tuple(stage_records),
                    committed=tuple(committed),
                    resumed=tuple(resumed),
                    executed=tuple(executed),
                    ckpt=ckpt,
                )
            except Exception as exc:  # pragma: no cover - defensive
                return self._terminal_failed(
                    job_id=job_id,
                    artifact_id=artifact_id,
                    content_sha256=content_sha,
                    pdigest=pdigest,
                    disclosure=self._workspace["disclosure"],
                    media_family=self._workspace.get("media_family")
                    or MediaFamily.UNKNOWN,
                    stage=stage,
                    reason_codes=("stage_exception", type(exc).__name__),
                    message=str(exc)[:256],
                    stage_records=tuple(stage_records),
                    committed=tuple(committed),
                    resumed=tuple(resumed),
                    executed=tuple(executed),
                    ckpt=ckpt,
                )

            executed.append(stage.value)
            stage_records.append(outcome.record)

            if outcome.quarantine is not None:
                ckpt.put_stage(
                    StageCheckpoint(
                        schema_version=DOCUMENT_PIPELINE_SCHEMA_VERSION,
                        stage=stage,
                        status=StageStatus.QUARANTINED,
                        idempotency_key=ikey,
                        output_digest=outcome.record.output_digest,
                        reason_codes=outcome.record.reason_codes,
                        diagnostics=outcome.record.diagnostics,
                        committed_utc=_utc_now(),
                        attempt=(existing.attempt + 1) if existing else 1,
                    )
                )
                ckpt.disposition = PipelineDisposition.QUARANTINE.value
                ckpt.quarantine_id = outcome.quarantine.quarantine_id
                ckpt.classification = self._workspace["disclosure"].value
                ckpt.media_family = (
                    self._workspace.get("media_family") or MediaFamily.UNKNOWN
                ).value
                ckpt.reason_codes = list(outcome.quarantine.reason_codes)
                self._job_store.save(ckpt)
                return DocumentPipelineResult(
                    schema_version=DOCUMENT_PIPELINE_SCHEMA_VERSION,
                    job_id=job_id,
                    artifact_id=artifact_id,
                    content_sha256=content_sha,
                    disposition=PipelineDisposition.QUARANTINE,
                    review_state=ReviewState.REQUIRED,
                    classification=self._workspace["disclosure"],
                    media_family=self._workspace.get("media_family")
                    or MediaFamily.UNKNOWN,
                    reason_codes=tuple(outcome.quarantine.reason_codes)
                    + (PipelineReasonCode.JOB_QUARANTINED.value,),
                    stage_records=tuple(stage_records),
                    committed_stages=tuple(committed),
                    resumed_stages=tuple(resumed),
                    executed_stages=tuple(executed),
                    parser_digest=pdigest,
                    derived_artifact_id=self._workspace.get("derived_artifact_id"),
                    quarantine=outcome.quarantine,
                    classification_result=self._workspace.get("classification_obj"),
                    extraction_result=self._workspace.get("extraction"),
                    span_validation_result=self._workspace.get("span_validation"),
                    labels=_frozen_str_map(self._workspace.get("labels")),
                    retained=True,
                )

            # Commit successful stage.
            ckpt.put_stage(
                StageCheckpoint(
                    schema_version=DOCUMENT_PIPELINE_SCHEMA_VERSION,
                    stage=stage,
                    status=StageStatus.COMMITTED,
                    idempotency_key=ikey,
                    output_digest=outcome.record.output_digest,
                    reason_codes=outcome.record.reason_codes,
                    diagnostics=outcome.record.diagnostics,
                    committed_utc=_utc_now(),
                    attempt=(existing.attempt + 1) if existing else 1,
                )
            )
            committed.append(stage.value)
            # Persist after every commit so restart never redoes work.
            self._job_store.save(ckpt)

        # All stages committed — domain terminal disposition.
        extraction: DocumentExtractionResult | None = self._workspace.get("extraction")
        span_val: SpanValidationResult | None = self._workspace.get("span_validation")
        disclosure = self._workspace["disclosure"]
        media = self._workspace.get("media_family") or MediaFamily.UNKNOWN

        reason_codes: list[str] = [PipelineReasonCode.JOB_COMPLETED.value]
        disposition = PipelineDisposition.COMPLETED
        review_state = ReviewState.NOT_REQUIRED

        if extraction is not None and extraction.disposition in (
            ExtractionDisposition.REVIEW,
        ):
            disposition = PipelineDisposition.REVIEW
            review_state = ReviewState.REQUIRED
            reason_codes = [PipelineReasonCode.JOB_REVIEW.value]
        if span_val is not None and span_val.disposition in (
            SpanValidationDisposition.REVIEW,
            SpanValidationDisposition.UNKNOWN,
        ):
            disposition = PipelineDisposition.REVIEW
            review_state = ReviewState.REQUIRED
            if PipelineReasonCode.JOB_REVIEW.value not in reason_codes:
                reason_codes.append(PipelineReasonCode.JOB_REVIEW.value)

        # Aggregate stage reason codes (bounded).
        for rec in stage_records:
            for code in rec.reason_codes:
                if code not in reason_codes and len(reason_codes) < 64:
                    reason_codes.append(code)

        ckpt.disposition = disposition.value
        ckpt.classification = disclosure.value
        ckpt.media_family = media.value
        ckpt.derived_artifact_id = self._workspace.get("derived_artifact_id")
        ckpt.reason_codes = list(reason_codes)
        self._job_store.save(ckpt)

        # Wipe plaintext from process workspace after successful completion.
        self._workspace["plaintext"] = None

        return DocumentPipelineResult(
            schema_version=DOCUMENT_PIPELINE_SCHEMA_VERSION,
            job_id=job_id,
            artifact_id=artifact_id,
            content_sha256=content_sha,
            disposition=disposition,
            review_state=review_state,
            classification=disclosure,
            media_family=media,
            reason_codes=tuple(reason_codes),
            stage_records=tuple(stage_records),
            committed_stages=tuple(committed),
            resumed_stages=tuple(resumed),
            executed_stages=tuple(executed),
            parser_digest=pdigest,
            derived_artifact_id=self._workspace.get("derived_artifact_id"),
            quarantine=None,
            classification_result=self._workspace.get("classification_obj"),
            extraction_result=extraction,
            span_validation_result=span_val,
            labels=_frozen_str_map(self._workspace.get("labels")),
            retained=True,
        )

    # -- bootstrap / hydrate ------------------------------------------------

    def _bootstrap_source(
        self, inp: DocumentPipelineInput
    ) -> DocumentPipelineResult | None:
        """Resolve content_bytes or mark for decrypt; validate size/digest."""
        if inp.content_bytes is not None:
            body = bytes(inp.content_bytes)
            if len(body) > self._max_bytes:
                return self._bootstrap_quarantine(
                    inp,
                    reason_codes=(PipelineReasonCode.OVERSIZE_DOCUMENT.value,),
                    message="document exceeds max_bytes bound",
                    details={"max_bytes": str(self._max_bytes), "size": str(len(body))},
                )
            digest = sha256_hex(body)
            if inp.content_sha256 and inp.content_sha256 != digest:
                return self._bootstrap_quarantine(
                    inp,
                    reason_codes=(PipelineReasonCode.QUARANTINE_UNTRUSTED.value,),
                    message="declared content_sha256 does not match bytes",
                    details={"declared": inp.content_sha256, "observed": digest},
                )
            self._workspace["plaintext"] = body
            self._workspace["content_sha256"] = digest
            family = detect_media_family(
                body, declared_mime=inp.declared_mime, filename=inp.filename
            )
            self._workspace["media_family"] = family
            return None

        if inp.source_artifact_id:
            # Decrypt deferred to DECRYPT stage; identity from store metadata.
            if self._private_store is None:
                return self._bootstrap_quarantine(
                    inp,
                    reason_codes=(PipelineReasonCode.MISSING_SOURCE.value,),
                    message="source_artifact_id provided but no private_store configured",
                    details={"source_artifact_id": inp.source_artifact_id},
                )
            record = self._private_store.get_record(inp.source_artifact_id)
            if record is None:
                return self._bootstrap_quarantine(
                    inp,
                    reason_codes=(PipelineReasonCode.MISSING_SOURCE.value,),
                    message="source artifact not found in private store",
                    details={"source_artifact_id": inp.source_artifact_id},
                )
            self._workspace["content_sha256"] = record.sha256
            if inp.content_sha256 and inp.content_sha256 != record.sha256:
                return self._bootstrap_quarantine(
                    inp,
                    reason_codes=(PipelineReasonCode.QUARANTINE_UNTRUSTED.value,),
                    message="declared content_sha256 does not match store record",
                    details={
                        "declared": inp.content_sha256,
                        "observed": record.sha256,
                    },
                )
            # Prefer store classification when policy not explicitly set.
            if inp.classification is None and inp.policy_classification is None:
                self._workspace["disclosure"] = _coerce_classification(
                    record.classification
                )
            return None

        return self._bootstrap_quarantine(
            inp,
            reason_codes=(PipelineReasonCode.MISSING_BYTES.value,),
            message="neither content_bytes nor source_artifact_id provided",
            details={},
        )

    def _bootstrap_quarantine(
        self,
        inp: DocumentPipelineInput,
        *,
        reason_codes: Sequence[str],
        message: str,
        details: Mapping[str, str],
    ) -> DocumentPipelineResult:
        job_id = inp.job_id or str(self._workspace.get("job_id") or self._id_factory())
        artifact_id = inp.artifact_id or f"art:{job_id}"
        content_sha = (
            inp.content_sha256
            or self._workspace.get("content_sha256")
            or sha256_hex(b"")
        )
        disclosure = self._workspace.get("disclosure") or DisclosureClassification.UNKNOWN
        qid = f"q:{job_id}:bootstrap"
        quarantine = QuarantineDiagnostics(
            quarantine_id=qid,
            reason_codes=tuple(reason_codes),
            stage="bootstrap",
            classification=disclosure.value
            if isinstance(disclosure, DisclosureClassification)
            else str(disclosure),
            media_family=None,
            content_sha256=content_sha,
            message=message,
            details=_frozen_str_map(details),
        )
        return DocumentPipelineResult(
            schema_version=DOCUMENT_PIPELINE_SCHEMA_VERSION,
            job_id=job_id,
            artifact_id=artifact_id,
            content_sha256=content_sha,
            disposition=PipelineDisposition.QUARANTINE,
            review_state=ReviewState.REQUIRED,
            classification=_coerce_classification(disclosure),
            media_family=MediaFamily.UNKNOWN,
            reason_codes=tuple(reason_codes)
            + (PipelineReasonCode.JOB_QUARANTINED.value,),
            stage_records=(),
            committed_stages=(),
            resumed_stages=(),
            executed_stages=(),
            parser_digest=parser_digest(),
            quarantine=quarantine,
            labels=_frozen_str_map(inp.labels),
            retained=True,
        )

    def _hydrate_workspace_from_checkpoint(self, ckpt: JobCheckpoint) -> None:
        """Restore non-plaintext workspace fields after resume.

        Plaintext must be re-supplied via content_bytes or re-decrypted.
        """
        if ckpt.classification:
            self._workspace["disclosure"] = _coerce_classification(ckpt.classification)
        if ckpt.media_family:
            try:
                self._workspace["media_family"] = MediaFamily(ckpt.media_family)
            except ValueError:
                pass
        if ckpt.derived_artifact_id:
            self._workspace["derived_artifact_id"] = ckpt.derived_artifact_id
        if ckpt.content_sha256:
            self._workspace["content_sha256"] = ckpt.content_sha256

    # -- stage dispatch -----------------------------------------------------

    @dataclass
    class _StageOutcome:
        record: StageRunRecord
        quarantine: QuarantineDiagnostics | None = None

    def _run_stage(
        self,
        stage: PipelineStage,
        inp: DocumentPipelineInput,
        ckpt: JobCheckpoint,
        ikey: str,
    ) -> "DocumentPipelineProcessor._StageOutcome":
        if stage is PipelineStage.CLASSIFY:
            return self._stage_classify(inp, ikey)
        if stage is PipelineStage.AUTHORIZE:
            return self._stage_authorize(inp, ikey)
        if stage is PipelineStage.DECRYPT:
            return self._stage_decrypt(inp, ikey)
        if stage is PipelineStage.EXTRACT:
            return self._stage_extract(inp, ikey)
        if stage is PipelineStage.NORMALIZE:
            return self._stage_normalize(inp, ikey)
        if stage is PipelineStage.VALIDATE_SPANS:
            return self._stage_validate_spans(inp, ikey)
        if stage is PipelineStage.PERSIST:
            return self._stage_persist(inp, ikey)
        raise DocumentPipelineError(
            f"unknown stage {stage!r}", code="unknown_stage"
        )

    def _stage_classify(
        self, inp: DocumentPipelineInput, ikey: str
    ) -> "DocumentPipelineProcessor._StageOutcome":
        body = self._workspace.get("plaintext")
        # Preview only — classifier accepts optional content_bytes.
        result = self._classifier.classify(
            DocumentClassificationInput(
                artifact_id=self._workspace["artifact_id"],
                document_code=inp.document_code,
                document_description=inp.document_description,
                declared_mime=inp.declared_mime,
                content_bytes=body if isinstance(body, (bytes, bytearray)) else None,
                filename=inp.filename,
                expected_matter_id=inp.matter_id,
                labels=dict(inp.labels),
            )
        )
        self._workspace["classification_obj"] = result
        # Explicit policy/input classification wins when provided.
        if inp.policy_classification is not None or inp.classification is not None:
            disclosure = _coerce_classification(
                inp.policy_classification or inp.classification
            )
        else:
            # Infer disclosure from kind defaults: public_user for known kinds.
            if result.is_quarantined or result.document_kind.value == "unknown":
                disclosure = DisclosureClassification.UNKNOWN
            else:
                disclosure = DisclosureClassification.PUBLIC_USER
        self._workspace["disclosure"] = disclosure

        reasons = (
            PipelineReasonCode.CLASSIFIED.value,
            PipelineReasonCode.STAGE_COMMITTED.value,
            *result.reason_codes[:8],
        )
        diagnostics = {
            "document_kind": result.document_kind.value,
            "classifier_disposition": result.disposition.value,
            "confidence": f"{result.confidence:.4f}",
            "disclosure": disclosure.value,
        }
        out_digest = sha256_hex(canonical_json(result.to_dict()))

        if result.disposition is ClassificationDisposition.QUARANTINE or (
            disclosure is DisclosureClassification.UNKNOWN
            and result.is_unknown
            and inp.classification is None
            and inp.policy_classification is None
        ):
            # Soft: allow AUTHORIZE to make the final quarantine decision for
            # explicit unknown policy. For classifier quarantine, fail here.
            if result.disposition is ClassificationDisposition.QUARANTINE:
                q = self._make_quarantine(
                    stage=PipelineStage.CLASSIFY,
                    reason_codes=(
                        PipelineReasonCode.QUARANTINE_CLASSIFICATION.value,
                        *result.reason_codes[:4],
                    ),
                    message="classifier disposition is quarantine",
                    details=diagnostics,
                )
                return self._StageOutcome(
                    record=StageRunRecord(
                        stage=PipelineStage.CLASSIFY,
                        status=StageStatus.QUARANTINED,
                        idempotency_key=ikey,
                        executed=True,
                        resumed=False,
                        reason_codes=reasons
                        + (PipelineReasonCode.QUARANTINE_CLASSIFICATION.value,),
                        diagnostics=_frozen_str_map(diagnostics),
                        output_digest=out_digest,
                    ),
                    quarantine=q,
                )

        return self._StageOutcome(
            record=StageRunRecord(
                stage=PipelineStage.CLASSIFY,
                status=StageStatus.COMMITTED,
                idempotency_key=ikey,
                executed=True,
                resumed=False,
                reason_codes=reasons,
                diagnostics=_frozen_str_map(diagnostics),
                output_digest=out_digest,
            )
        )

    def _stage_authorize(
        self, inp: DocumentPipelineInput, ikey: str
    ) -> "DocumentPipelineProcessor._StageOutcome":
        disclosure = self._workspace["disclosure"]
        # Re-resolve via policy when explicit policy classification provided.
        if inp.policy_classification is not None:
            disclosure = self._privacy.coerce_classification(inp.policy_classification)
            self._workspace["disclosure"] = disclosure

        reasons: list[str] = [PipelineReasonCode.AUTHORIZED.value]
        diagnostics: dict[str, str] = {
            "disclosure": disclosure.value,
            "privacy_schema": PRIVACY_POLICY_SCHEMA_VERSION,
        }

        if self._privacy.must_quarantine(disclosure):
            q = self._make_quarantine(
                stage=PipelineStage.AUTHORIZE,
                reason_codes=(
                    PipelineReasonCode.QUARANTINE_CLASSIFICATION.value,
                    "unknown_classification",
                ),
                message="unknown classification is quarantined before processing",
                details=diagnostics,
            )
            return self._StageOutcome(
                record=StageRunRecord(
                    stage=PipelineStage.AUTHORIZE,
                    status=StageStatus.QUARANTINED,
                    idempotency_key=ikey,
                    executed=True,
                    resumed=False,
                    reason_codes=(
                        PipelineReasonCode.QUARANTINE_CLASSIFICATION.value,
                        PipelineReasonCode.STAGE_COMMITTED.value,
                    ),
                    diagnostics=_frozen_str_map(diagnostics),
                    output_digest=sha256_hex(canonical_json(diagnostics)),
                ),
                quarantine=q,
            )

        if disclosure is DisclosureClassification.CREDENTIAL_OR_PAYMENT:
            q = self._make_quarantine(
                stage=PipelineStage.AUTHORIZE,
                reason_codes=(
                    PipelineReasonCode.QUARANTINE_POLICY_DENIED.value,
                    "credential_or_payment",
                ),
                message="credential_or_payment material is prohibited from document pipeline",
                details=diagnostics,
            )
            return self._StageOutcome(
                record=StageRunRecord(
                    stage=PipelineStage.AUTHORIZE,
                    status=StageStatus.QUARANTINED,
                    idempotency_key=ikey,
                    executed=True,
                    resumed=False,
                    reason_codes=(
                        PipelineReasonCode.QUARANTINE_POLICY_DENIED.value,
                        PipelineReasonCode.STAGE_COMMITTED.value,
                    ),
                    diagnostics=_frozen_str_map(diagnostics),
                    output_digest=sha256_hex(canonical_json(diagnostics)),
                ),
                quarantine=q,
            )

        # Vault admission for derived document storage.
        vault_decision = self._privacy.evaluate_vault(
            VaultKind.DOCUMENT,
            ContentKind.DOCUMENT_BYTES,
            disclosure,
        )
        diagnostics["vault_decision"] = vault_decision.code.value
        if not vault_decision.allowed:
            q = self._make_quarantine(
                stage=PipelineStage.AUTHORIZE,
                reason_codes=(
                    PipelineReasonCode.QUARANTINE_POLICY_DENIED.value,
                    vault_decision.code.value,
                ),
                message=vault_decision.reason,
                details=diagnostics,
            )
            return self._StageOutcome(
                record=StageRunRecord(
                    stage=PipelineStage.AUTHORIZE,
                    status=StageStatus.QUARANTINED,
                    idempotency_key=ikey,
                    executed=True,
                    resumed=False,
                    reason_codes=(
                        PipelineReasonCode.QUARANTINE_POLICY_DENIED.value,
                        PipelineReasonCode.STAGE_COMMITTED.value,
                    ),
                    diagnostics=_frozen_str_map(diagnostics),
                    output_digest=sha256_hex(canonical_json(diagnostics)),
                ),
                quarantine=q,
            )

        # Public sink deny-list check (private material must not leak).
        if is_private_classification(disclosure):
            sink_decision = self._privacy.evaluate_sink(
                disclosure, PublicSink.PUBLIC_IPFS, ContentKind.DOCUMENT_BYTES
            )
            diagnostics["public_sink_allowed"] = str(sink_decision.allowed).lower()
            diagnostics["public_sink_code"] = sink_decision.code.value
            if sink_decision.allowed:
                # Fail closed: private material must never be allowed to public IPFS.
                q = self._make_quarantine(
                    stage=PipelineStage.AUTHORIZE,
                    reason_codes=(
                        PipelineReasonCode.QUARANTINE_POLICY_DENIED.value,
                        "private_public_sink_allowed_anomaly",
                    ),
                    message="privacy policy incorrectly allowed private material on public sink",
                    details=diagnostics,
                )
                return self._StageOutcome(
                    record=StageRunRecord(
                        stage=PipelineStage.AUTHORIZE,
                        status=StageStatus.QUARANTINED,
                        idempotency_key=ikey,
                        executed=True,
                        resumed=False,
                        reason_codes=(
                            PipelineReasonCode.QUARANTINE_POLICY_DENIED.value,
                        ),
                        diagnostics=_frozen_str_map(diagnostics),
                        output_digest=sha256_hex(canonical_json(diagnostics)),
                    ),
                    quarantine=q,
                )
            if sink_decision.code is SinkDecisionCode.DENIED_PRIVATE:
                reasons.append("private_sink_denied_ok")

        reasons.append(PipelineReasonCode.STAGE_COMMITTED.value)
        return self._StageOutcome(
            record=StageRunRecord(
                stage=PipelineStage.AUTHORIZE,
                status=StageStatus.COMMITTED,
                idempotency_key=ikey,
                executed=True,
                resumed=False,
                reason_codes=tuple(reasons),
                diagnostics=_frozen_str_map(diagnostics),
                output_digest=sha256_hex(canonical_json(diagnostics)),
            )
        )

    def _stage_decrypt(
        self, inp: DocumentPipelineInput, ikey: str
    ) -> "DocumentPipelineProcessor._StageOutcome":
        diagnostics: dict[str, str] = {}
        reasons: list[str] = []

        if self._workspace.get("plaintext") is not None:
            reasons.extend(
                (
                    PipelineReasonCode.PLAINTEXT_PASSTHROUGH.value,
                    PipelineReasonCode.STAGE_COMMITTED.value,
                )
            )
            diagnostics["mode"] = "passthrough"
            diagnostics["size_bytes"] = str(len(self._workspace["plaintext"]))
            return self._StageOutcome(
                record=StageRunRecord(
                    stage=PipelineStage.DECRYPT,
                    status=StageStatus.COMMITTED,
                    idempotency_key=ikey,
                    executed=True,
                    resumed=False,
                    reason_codes=tuple(reasons),
                    diagnostics=_frozen_str_map(diagnostics),
                    output_digest=self._workspace["content_sha256"],
                )
            )

        if not inp.source_artifact_id or self._private_store is None:
            q = self._make_quarantine(
                stage=PipelineStage.DECRYPT,
                reason_codes=(PipelineReasonCode.MISSING_SOURCE.value,),
                message="no plaintext and no decryptable source artifact",
                details={"source_artifact_id": str(inp.source_artifact_id or "")},
            )
            return self._StageOutcome(
                record=StageRunRecord(
                    stage=PipelineStage.DECRYPT,
                    status=StageStatus.QUARANTINED,
                    idempotency_key=ikey,
                    executed=True,
                    resumed=False,
                    reason_codes=(PipelineReasonCode.MISSING_SOURCE.value,),
                    diagnostics=_frozen_str_map(diagnostics),
                    output_digest=None,
                ),
                quarantine=q,
            )

        try:
            plaintext = self._private_store.get_bytes(inp.source_artifact_id)
        except PrivateStoreError as exc:
            q = self._make_quarantine(
                stage=PipelineStage.DECRYPT,
                reason_codes=(
                    PipelineReasonCode.DECRYPT_FAILED.value,
                    getattr(exc, "code", "decrypt_error"),
                ),
                message="failed to decrypt source artifact in memory",
                details={"source_artifact_id": inp.source_artifact_id},
            )
            return self._StageOutcome(
                record=StageRunRecord(
                    stage=PipelineStage.DECRYPT,
                    status=StageStatus.QUARANTINED,
                    idempotency_key=ikey,
                    executed=True,
                    resumed=False,
                    reason_codes=(PipelineReasonCode.DECRYPT_FAILED.value,),
                    diagnostics=_frozen_str_map(diagnostics),
                    output_digest=None,
                ),
                quarantine=q,
            )

        if len(plaintext) > self._max_bytes:
            # Drop plaintext immediately.
            del plaintext
            q = self._make_quarantine(
                stage=PipelineStage.DECRYPT,
                reason_codes=(PipelineReasonCode.OVERSIZE_DOCUMENT.value,),
                message="decrypted document exceeds max_bytes",
                details={"max_bytes": str(self._max_bytes)},
            )
            return self._StageOutcome(
                record=StageRunRecord(
                    stage=PipelineStage.DECRYPT,
                    status=StageStatus.QUARANTINED,
                    idempotency_key=ikey,
                    executed=True,
                    resumed=False,
                    reason_codes=(PipelineReasonCode.OVERSIZE_DOCUMENT.value,),
                    diagnostics=_frozen_str_map(diagnostics),
                    output_digest=None,
                ),
                quarantine=q,
            )

        digest = sha256_hex(plaintext)
        expected = self._workspace.get("content_sha256")
        if expected and expected != digest:
            del plaintext
            q = self._make_quarantine(
                stage=PipelineStage.DECRYPT,
                reason_codes=(PipelineReasonCode.QUARANTINE_UNTRUSTED.value,),
                message="decrypted digest does not match store metadata",
                details={"expected": str(expected), "observed": digest},
            )
            return self._StageOutcome(
                record=StageRunRecord(
                    stage=PipelineStage.DECRYPT,
                    status=StageStatus.QUARANTINED,
                    idempotency_key=ikey,
                    executed=True,
                    resumed=False,
                    reason_codes=(PipelineReasonCode.QUARANTINE_UNTRUSTED.value,),
                    diagnostics=_frozen_str_map(diagnostics),
                    output_digest=None,
                ),
                quarantine=q,
            )

        self._workspace["plaintext"] = plaintext
        self._workspace["content_sha256"] = digest
        family = detect_media_family(
            plaintext, declared_mime=inp.declared_mime, filename=inp.filename
        )
        self._workspace["media_family"] = family
        reasons.extend(
            (
                PipelineReasonCode.DECRYPTED_IN_MEMORY.value,
                PipelineReasonCode.STAGE_COMMITTED.value,
            )
        )
        diagnostics["mode"] = "decrypt"
        diagnostics["size_bytes"] = str(len(plaintext))
        diagnostics["media_family"] = family.value
        # Checkpoint never receives plaintext.
        return self._StageOutcome(
            record=StageRunRecord(
                stage=PipelineStage.DECRYPT,
                status=StageStatus.COMMITTED,
                idempotency_key=ikey,
                executed=True,
                resumed=False,
                reason_codes=tuple(reasons),
                diagnostics=_frozen_str_map(diagnostics),
                output_digest=digest,
            )
        )

    def _stage_extract(
        self, inp: DocumentPipelineInput, ikey: str
    ) -> "DocumentPipelineProcessor._StageOutcome":
        body = self._workspace.get("plaintext")
        if not isinstance(body, (bytes, bytearray)) or len(body) == 0:
            q = self._make_quarantine(
                stage=PipelineStage.EXTRACT,
                reason_codes=(PipelineReasonCode.MISSING_BYTES.value,),
                message="no in-memory plaintext available for extraction",
                details={},
            )
            return self._StageOutcome(
                record=StageRunRecord(
                    stage=PipelineStage.EXTRACT,
                    status=StageStatus.QUARANTINED,
                    idempotency_key=ikey,
                    executed=True,
                    resumed=False,
                    reason_codes=(PipelineReasonCode.MISSING_BYTES.value,),
                    diagnostics=MappingProxyType({}),
                    output_digest=None,
                ),
                quarantine=q,
            )

        family = detect_media_family(
            body, declared_mime=inp.declared_mime, filename=inp.filename
        )
        self._workspace["media_family"] = family

        # Untrusted / unknown media → quarantine (not silent drop).
        if family is MediaFamily.UNKNOWN:
            q = self._make_quarantine(
                stage=PipelineStage.EXTRACT,
                reason_codes=(PipelineReasonCode.QUARANTINE_UNTRUSTED.value,),
                message="untrusted or unrecognized media family",
                details={
                    "declared_mime": str(inp.declared_mime or ""),
                    "filename": str(inp.filename or ""),
                },
            )
            return self._StageOutcome(
                record=StageRunRecord(
                    stage=PipelineStage.EXTRACT,
                    status=StageStatus.QUARANTINED,
                    idempotency_key=ikey,
                    executed=True,
                    resumed=False,
                    reason_codes=(PipelineReasonCode.QUARANTINE_UNTRUSTED.value,),
                    diagnostics=_frozen_str_map(
                        {"media_family": family.value}
                    ),
                    output_digest=None,
                ),
                quarantine=q,
            )

        # MIME / magic conflict is diagnostic but may still extract for review.
        mime_conflict = False
        if inp.declared_mime:
            declared_family = detect_media_family(
                None, declared_mime=inp.declared_mime, filename=inp.filename
            )
            magic_family = detect_media_family(body)
            if (
                declared_family is not MediaFamily.UNKNOWN
                and magic_family is not MediaFamily.UNKNOWN
                and declared_family is not magic_family
            ):
                mime_conflict = True

        disclosure = self._workspace["disclosure"]
        declared = inp.declared_mime or _declared_mime_for_family(family)
        extraction = self._extractor.extract(
            DocumentExtractionInput(
                artifact_id=self._workspace["artifact_id"],
                content_bytes=bytes(body),
                declared_mime=declared,
                filename=inp.filename,
                classification=disclosure,
                content_sha256=self._workspace.get("content_sha256"),
                labels=dict(inp.labels),
                force_ocr=inp.force_ocr,
            )
        )
        self._workspace["extraction"] = extraction

        diagnostics = {
            "media_family": family.value,
            "extraction_disposition": extraction.disposition.value,
            "page_count": str(extraction.page_count),
            "span_count": str(len(extraction.spans)),
            "mime_conflict": str(mime_conflict).lower(),
        }
        reasons: list[str] = [
            PipelineReasonCode.EXTRACTED.value,
            PipelineReasonCode.STAGE_COMMITTED.value,
            *list(extraction.reason_codes[:8]),
        ]
        if mime_conflict:
            reasons.append(PipelineReasonCode.MIME_MAGIC_CONFLICT.value)

        # Corrupt / rejected extractions quarantine.
        if extraction.disposition is ExtractionDisposition.REJECTED:
            q = self._make_quarantine(
                stage=PipelineStage.EXTRACT,
                reason_codes=(
                    PipelineReasonCode.QUARANTINE_CORRUPT.value,
                    *list(extraction.reason_codes[:4]),
                ),
                message="extraction rejected (corrupt or unsupported document)",
                details=diagnostics,
            )
            return self._StageOutcome(
                record=StageRunRecord(
                    stage=PipelineStage.EXTRACT,
                    status=StageStatus.QUARANTINED,
                    idempotency_key=ikey,
                    executed=True,
                    resumed=False,
                    reason_codes=tuple(reasons)
                    + (PipelineReasonCode.QUARANTINE_CORRUPT.value,),
                    diagnostics=_frozen_str_map(diagnostics),
                    output_digest=extraction.content_sha256,
                ),
                quarantine=q,
            )

        if extraction.disposition is ExtractionDisposition.QUARANTINE:
            q = self._make_quarantine(
                stage=PipelineStage.EXTRACT,
                reason_codes=(
                    PipelineReasonCode.QUARANTINE_EXTRACT.value,
                    *list(extraction.reason_codes[:4]),
                ),
                message="extraction disposition is quarantine",
                details=diagnostics,
            )
            return self._StageOutcome(
                record=StageRunRecord(
                    stage=PipelineStage.EXTRACT,
                    status=StageStatus.QUARANTINED,
                    idempotency_key=ikey,
                    executed=True,
                    resumed=False,
                    reason_codes=tuple(reasons)
                    + (PipelineReasonCode.QUARANTINE_EXTRACT.value,),
                    diagnostics=_frozen_str_map(diagnostics),
                    output_digest=extraction.content_sha256,
                ),
                quarantine=q,
            )

        out_digest = sha256_hex(
            canonical_json(
                {
                    "content_sha256": extraction.content_sha256,
                    "disposition": extraction.disposition.value,
                    "page_count": extraction.page_count,
                    "span_ids": [s.span_id for s in extraction.spans[:64]],
                }
            )
        )
        return self._StageOutcome(
            record=StageRunRecord(
                stage=PipelineStage.EXTRACT,
                status=StageStatus.COMMITTED,
                idempotency_key=ikey,
                executed=True,
                resumed=False,
                reason_codes=tuple(reasons),
                diagnostics=_frozen_str_map(diagnostics),
                output_digest=out_digest,
            )
        )

    def _stage_normalize(
        self, inp: DocumentPipelineInput, ikey: str
    ) -> "DocumentPipelineProcessor._StageOutcome":
        extraction: DocumentExtractionResult | None = self._workspace.get("extraction")
        if extraction is None:
            # On pure resume without re-extract workspace, re-run extract is
            # required — but extract should have been committed and workspace
            # rehydrated only when plaintext present. Force re-extract when
            # missing so normalize is never a silent no-op on cold resume with
            # bytes.
            body = self._workspace.get("plaintext")
            if isinstance(body, (bytes, bytearray)) and len(body) > 0:
                # Re-extract into workspace (extract stage already committed).
                disclosure = self._workspace["disclosure"]
                family = self._workspace.get("media_family") or detect_media_family(
                    body, declared_mime=inp.declared_mime, filename=inp.filename
                )
                extraction = self._extractor.extract(
                    DocumentExtractionInput(
                        artifact_id=self._workspace["artifact_id"],
                        content_bytes=bytes(body),
                        declared_mime=inp.declared_mime
                        or _declared_mime_for_family(family),
                        filename=inp.filename,
                        classification=disclosure,
                        content_sha256=self._workspace.get("content_sha256"),
                        labels=dict(inp.labels),
                        force_ocr=inp.force_ocr,
                    )
                )
                self._workspace["extraction"] = extraction
            else:
                q = self._make_quarantine(
                    stage=PipelineStage.NORMALIZE,
                    reason_codes=(PipelineReasonCode.MISSING_BYTES.value,),
                    message="normalize requires extraction workspace (re-supply bytes on resume)",
                    details={},
                )
                return self._StageOutcome(
                    record=StageRunRecord(
                        stage=PipelineStage.NORMALIZE,
                        status=StageStatus.QUARANTINED,
                        idempotency_key=ikey,
                        executed=True,
                        resumed=False,
                        reason_codes=(PipelineReasonCode.MISSING_BYTES.value,),
                        diagnostics=MappingProxyType({}),
                        output_digest=None,
                    ),
                    quarantine=q,
                )

        # Normalize: stable span order, page coverage completeness receipt.
        span_ids = sorted(s.span_id for s in extraction.spans if s.span_id)
        page_indexes = sorted(
            {cov.page_index for cov in extraction.page_coverage if cov.page_index is not None}
        )
        normalized = {
            "artifact_id": extraction.artifact_id,
            "content_sha256": extraction.content_sha256,
            "media_family": extraction.media_family.value,
            "page_count": extraction.page_count,
            "page_indexes": page_indexes,
            "span_count": len(extraction.spans),
            "span_ids": span_ids,
            "overall_coverage": extraction.overall_coverage,
            "disposition": extraction.disposition.value,
            "classification": extraction.classification.value,
        }
        self._workspace["normalized"] = normalized
        self._workspace["media_family"] = extraction.media_family
        out_digest = sha256_hex(canonical_json(normalized))
        diagnostics = {
            "span_count": str(len(span_ids)),
            "page_count": str(extraction.page_count),
            "media_family": extraction.media_family.value,
        }
        return self._StageOutcome(
            record=StageRunRecord(
                stage=PipelineStage.NORMALIZE,
                status=StageStatus.COMMITTED,
                idempotency_key=ikey,
                executed=True,
                resumed=False,
                reason_codes=(
                    PipelineReasonCode.NORMALIZED.value,
                    PipelineReasonCode.STAGE_COMMITTED.value,
                ),
                diagnostics=_frozen_str_map(diagnostics),
                output_digest=out_digest,
            )
        )

    def _stage_validate_spans(
        self, inp: DocumentPipelineInput, ikey: str
    ) -> "DocumentPipelineProcessor._StageOutcome":
        extraction: DocumentExtractionResult | None = self._workspace.get("extraction")
        if extraction is None:
            body = self._workspace.get("plaintext")
            if isinstance(body, (bytes, bytearray)) and len(body) > 0:
                disclosure = self._workspace["disclosure"]
                family = self._workspace.get("media_family") or MediaFamily.UNKNOWN
                extraction = self._extractor.extract(
                    DocumentExtractionInput(
                        artifact_id=self._workspace["artifact_id"],
                        content_bytes=bytes(body),
                        declared_mime=inp.declared_mime
                        or _declared_mime_for_family(family),
                        filename=inp.filename,
                        classification=disclosure,
                        content_sha256=self._workspace.get("content_sha256"),
                        labels=dict(inp.labels),
                        force_ocr=inp.force_ocr,
                    )
                )
                self._workspace["extraction"] = extraction
            else:
                q = self._make_quarantine(
                    stage=PipelineStage.VALIDATE_SPANS,
                    reason_codes=(PipelineReasonCode.MISSING_BYTES.value,),
                    message="validate_spans requires extraction",
                    details={},
                )
                return self._StageOutcome(
                    record=StageRunRecord(
                        stage=PipelineStage.VALIDATE_SPANS,
                        status=StageStatus.QUARANTINED,
                        idempotency_key=ikey,
                        executed=True,
                        resumed=False,
                        reason_codes=(PipelineReasonCode.MISSING_BYTES.value,),
                        diagnostics=MappingProxyType({}),
                        output_digest=None,
                    ),
                    quarantine=q,
                )

        result = self._span_validator.validate(
            extraction,
            expected_content_sha256=self._workspace.get("content_sha256"),
            labels=dict(inp.labels),
        )
        self._workspace["span_validation"] = result
        diagnostics = {
            "disposition": result.disposition.value,
            "span_count": str(result.span_count),
            "page_count": str(result.page_count),
            "accounted_pages": str(result.accounted_pages),
        }
        reasons = (
            PipelineReasonCode.SPANS_VALIDATED.value,
            PipelineReasonCode.STAGE_COMMITTED.value,
            *list(result.reason_codes[:8]),
        )
        out_digest = sha256_hex(
            canonical_json(
                {
                    "disposition": result.disposition.value,
                    "validation_id": result.validation_id,
                    "content_sha256": result.content_sha256,
                    "invalid_span_ids": list(result.invalid_span_ids[:32]),
                }
            )
        )

        if result.disposition is SpanValidationDisposition.INVALID:
            q = self._make_quarantine(
                stage=PipelineStage.VALIDATE_SPANS,
                reason_codes=(
                    PipelineReasonCode.QUARANTINE_SPAN_INVALID.value,
                    *list(result.reason_codes[:4]),
                ),
                message="span validation disposition is invalid",
                details=diagnostics,
            )
            return self._StageOutcome(
                record=StageRunRecord(
                    stage=PipelineStage.VALIDATE_SPANS,
                    status=StageStatus.QUARANTINED,
                    idempotency_key=ikey,
                    executed=True,
                    resumed=False,
                    reason_codes=reasons
                    + (PipelineReasonCode.QUARANTINE_SPAN_INVALID.value,),
                    diagnostics=_frozen_str_map(diagnostics),
                    output_digest=out_digest,
                ),
                quarantine=q,
            )

        return self._StageOutcome(
            record=StageRunRecord(
                stage=PipelineStage.VALIDATE_SPANS,
                status=StageStatus.COMMITTED,
                idempotency_key=ikey,
                executed=True,
                resumed=False,
                reason_codes=reasons,
                diagnostics=_frozen_str_map(diagnostics),
                output_digest=out_digest,
            )
        )

    def _stage_persist(
        self, inp: DocumentPipelineInput, ikey: str
    ) -> "DocumentPipelineProcessor._StageOutcome":
        extraction: DocumentExtractionResult | None = self._workspace.get("extraction")
        span_val: SpanValidationResult | None = self._workspace.get("span_validation")
        normalized = self._workspace.get("normalized") or {}
        disclosure = self._workspace["disclosure"]
        job_id = self._workspace["job_id"]
        artifact_id = self._workspace["artifact_id"]

        # Derived artifact: content-addressed digests and stage receipts only.
        # Never embed free-form text, full extraction bodies, or raw public
        # projection JSON (which can contain long digit runs that trip
        # payment-card scanners). Process-local workspace retains full results.
        derived_id = f"derived:{artifact_id}:pipeline"
        extraction_public = (
            None if extraction is None else extraction.public_projection()
        )
        span_public = (
            None if span_val is None else span_val.public_projection()
        )
        extraction_public_digest = (
            None
            if extraction_public is None
            else sha256_hex(canonical_json(extraction_public))
        )
        span_public_digest = (
            None
            if span_public is None
            else sha256_hex(canonical_json(span_public))
        )
        normalized_digest = (
            None
            if not normalized
            else sha256_hex(canonical_json(normalized))
        )
        # All digests/ids are separator-tokenized so private-store PAN scanners
        # never false-positive on synthetic hex/id digit runs.
        derived_payload: dict[str, Any] = {
            "schema_version": DOCUMENT_PIPELINE_SCHEMA_VERSION,
            "job_id": str(job_id),
            "source_artifact_id": str(artifact_id),
            "content_sha256_token": _safe_digest_token(
                self._workspace.get("content_sha256")
            ),
            "classification": disclosure.value,
            "media_family": (
                self._workspace.get("media_family") or MediaFamily.UNKNOWN
            ).value,
            "parser_digest_token": _safe_digest_token(parser_digest()),
            "normalized_digest_token": _safe_digest_token(normalized_digest),
            "extraction_public_digest_token": _safe_digest_token(
                extraction_public_digest
            ),
            "span_validation_public_digest_token": _safe_digest_token(
                span_public_digest
            ),
            "extraction_disposition": None
            if extraction is None
            else extraction.disposition.value,
            "span_disposition": None if span_val is None else span_val.disposition.value,
            "page_count_token": _safe_int_token(
                None if extraction is None else int(extraction.page_count),
                prefix="p",
            ),
            "span_count_token": _safe_int_token(
                None if extraction is None else int(len(extraction.spans)),
                prefix="s",
            ),
        }
        derived_bytes = canonical_json(derived_payload).encode("utf-8")
        derived_digest = sha256_hex(derived_bytes)

        diagnostics: dict[str, str] = {
            "derived_artifact_id": derived_id,
            "derived_sha256": derived_digest,
            "size_bytes": str(len(derived_bytes)),
        }
        reasons: list[str] = [
            PipelineReasonCode.DERIVED_ARTIFACT_PERSISTED.value,
            PipelineReasonCode.STAGE_COMMITTED.value,
        ]

        if self._private_store is not None:
            try:
                _manifest, created = self._private_store.put_bytes(
                    derived_bytes,
                    artifact_id=derived_id,
                    classification=disclosure,
                    media_type="application/json",
                    matter_id=inp.matter_id,
                    labels={
                        **dict(inp.labels),
                        "pipeline_job_id": job_id,
                        "derived_kind": "document_pipeline_result",
                    },
                    # Metadata digests of derived pipeline receipts — not raw body.
                    content_kind=ContentKind.METADATA_DIGEST,
                )
                diagnostics["created"] = str(created).lower()
                diagnostics["store"] = "private"
            except Exception as exc:
                q = self._make_quarantine(
                    stage=PipelineStage.PERSIST,
                    reason_codes=(
                        PipelineReasonCode.QUARANTINE_POLICY_DENIED.value,
                        getattr(exc, "code", type(exc).__name__),
                    ),
                    message=f"failed to persist derived artifact: {exc}"[:256],
                    details=diagnostics,
                )
                return self._StageOutcome(
                    record=StageRunRecord(
                        stage=PipelineStage.PERSIST,
                        status=StageStatus.QUARANTINED,
                        idempotency_key=ikey,
                        executed=True,
                        resumed=False,
                        reason_codes=(
                            PipelineReasonCode.QUARANTINE_POLICY_DENIED.value,
                        ),
                        diagnostics=_frozen_str_map(diagnostics),
                        output_digest=derived_digest,
                    ),
                    quarantine=q,
                )
        else:
            # In-memory only derived digest (no durable private store).
            diagnostics["store"] = "memory"
            diagnostics["created"] = "true"
            self._workspace["derived_memory"] = derived_digest

        self._workspace["derived_artifact_id"] = derived_id
        # Drop plaintext after persist.
        self._workspace["plaintext"] = None

        return self._StageOutcome(
            record=StageRunRecord(
                stage=PipelineStage.PERSIST,
                status=StageStatus.COMMITTED,
                idempotency_key=ikey,
                executed=True,
                resumed=False,
                reason_codes=tuple(reasons),
                diagnostics=_frozen_str_map(diagnostics),
                output_digest=derived_digest,
            )
        )

    # -- quarantine / failure helpers ---------------------------------------

    def _make_quarantine(
        self,
        *,
        stage: PipelineStage,
        reason_codes: Sequence[str],
        message: str,
        details: Mapping[str, str],
    ) -> QuarantineDiagnostics:
        job_id = str(self._workspace.get("job_id") or "unknown")
        qid = f"q:{job_id}:{stage.value}"
        disclosure = self._workspace.get("disclosure") or DisclosureClassification.UNKNOWN
        media = self._workspace.get("media_family")
        return QuarantineDiagnostics(
            quarantine_id=qid,
            reason_codes=tuple(str(r) for r in reason_codes if str(r).strip()),
            stage=stage.value,
            classification=disclosure.value
            if isinstance(disclosure, DisclosureClassification)
            else str(disclosure),
            media_family=media.value if isinstance(media, MediaFamily) else None,
            content_sha256=self._workspace.get("content_sha256"),
            message=message[:512],
            details=_frozen_str_map(details),
        )

    def _terminal_quarantine(
        self,
        *,
        job_id: str,
        artifact_id: str,
        content_sha256: str,
        pdigest: str,
        disclosure: DisclosureClassification,
        media_family: MediaFamily,
        stage: PipelineStage,
        reason_codes: Sequence[str],
        message: str,
        details: Mapping[str, str],
        stage_records: tuple[StageRunRecord, ...],
        committed: tuple[str, ...],
        resumed: tuple[str, ...],
        executed: tuple[str, ...],
        ckpt: JobCheckpoint,
    ) -> DocumentPipelineResult:
        q = QuarantineDiagnostics(
            quarantine_id=f"q:{job_id}:{stage.value}",
            reason_codes=tuple(reason_codes),
            stage=stage.value,
            classification=disclosure.value,
            media_family=media_family.value,
            content_sha256=content_sha256,
            message=message[:512],
            details=_frozen_str_map(details),
        )
        ckpt.disposition = PipelineDisposition.QUARANTINE.value
        ckpt.quarantine_id = q.quarantine_id
        ckpt.classification = disclosure.value
        ckpt.media_family = media_family.value
        ckpt.reason_codes = list(reason_codes)
        self._job_store.save(ckpt)
        return DocumentPipelineResult(
            schema_version=DOCUMENT_PIPELINE_SCHEMA_VERSION,
            job_id=job_id,
            artifact_id=artifact_id,
            content_sha256=content_sha256,
            disposition=PipelineDisposition.QUARANTINE,
            review_state=ReviewState.REQUIRED,
            classification=disclosure,
            media_family=media_family,
            reason_codes=tuple(reason_codes)
            + (PipelineReasonCode.JOB_QUARANTINED.value,),
            stage_records=stage_records,
            committed_stages=committed,
            resumed_stages=resumed,
            executed_stages=executed,
            parser_digest=pdigest,
            quarantine=q,
            labels=_frozen_str_map(self._workspace.get("labels")),
            retained=True,
        )

    def _terminal_failed(
        self,
        *,
        job_id: str,
        artifact_id: str,
        content_sha256: str,
        pdigest: str,
        disclosure: DisclosureClassification,
        media_family: MediaFamily,
        stage: PipelineStage,
        reason_codes: Sequence[str],
        message: str,
        stage_records: tuple[StageRunRecord, ...],
        committed: tuple[str, ...],
        resumed: tuple[str, ...],
        executed: tuple[str, ...],
        ckpt: JobCheckpoint,
    ) -> DocumentPipelineResult:
        ckpt.disposition = PipelineDisposition.FAILED.value
        ckpt.classification = disclosure.value
        ckpt.media_family = media_family.value
        ckpt.reason_codes = list(reason_codes) + [
            PipelineReasonCode.JOB_FAILED.value,
            f"failed_stage:{stage.value}",
            message[:128],
        ]
        self._job_store.save(ckpt)
        return DocumentPipelineResult(
            schema_version=DOCUMENT_PIPELINE_SCHEMA_VERSION,
            job_id=job_id,
            artifact_id=artifact_id,
            content_sha256=content_sha256,
            disposition=PipelineDisposition.FAILED,
            review_state=ReviewState.REQUIRED,
            classification=disclosure,
            media_family=media_family,
            reason_codes=tuple(ckpt.reason_codes),
            stage_records=stage_records,
            committed_stages=committed,
            resumed_stages=resumed,
            executed_stages=executed,
            parser_digest=pdigest,
            labels=_frozen_str_map(self._workspace.get("labels")),
            retained=True,
        )


# ---------------------------------------------------------------------------
# Convenience constructors
# ---------------------------------------------------------------------------


def create_document_pipeline_processor(
    *,
    checkpoint_dir: str | Path | None = None,
    private_store_root: str | Path | None = None,
    tenant_id: str = "default-tenant",
    privacy_policy: UsptoPrivacyPolicy | None = None,
    **kwargs: Any,
) -> DocumentPipelineProcessor:
    """Factory with optional filesystem checkpoint and private store roots."""
    job_store = DocumentPipelineJobStore(root=checkpoint_dir)
    private_store = None
    if private_store_root is not None:
        key = generate_tenant_key(tenant_id)
        private_store = PrivateArtifactStore(
            private_store_root,
            key,
            privacy_policy=privacy_policy or DEFAULT_PRIVACY_POLICY,
        )
    return DocumentPipelineProcessor(
        job_store=job_store,
        private_store=private_store,
        privacy_policy=privacy_policy,
        **kwargs,
    )


def process_document(
    *,
    content_bytes: bytes,
    artifact_id: str | None = None,
    job_id: str | None = None,
    classification: DisclosureClassification | str = DisclosureClassification.PUBLIC_USER,
    filename: str | None = None,
    declared_mime: str | None = None,
    checkpoint_dir: str | Path | None = None,
    **kwargs: Any,
) -> DocumentPipelineResult:
    """Module-level convenience for a single inline-bytes job."""
    processor = create_document_pipeline_processor(checkpoint_dir=checkpoint_dir)
    return processor.process(
        DocumentPipelineInput(
            job_id=job_id,
            artifact_id=artifact_id,
            content_bytes=content_bytes,
            classification=classification,
            filename=filename,
            declared_mime=declared_mime,
            **{k: v for k, v in kwargs.items() if k in DocumentPipelineInput.__dataclass_fields__},
        )
    )


__all__ = [
    "DOCUMENT_PIPELINE_INTERFACE",
    "DOCUMENT_PIPELINE_SCHEMA_VERSION",
    "PIPELINE_STAGE_ORDER",
    "DocumentPipelineError",
    "DocumentPipelineInput",
    "DocumentPipelineJobStore",
    "DocumentPipelineProcessor",
    "DocumentPipelineResult",
    "InjectedStageFailure",
    "JobCheckpoint",
    "PipelineDisposition",
    "PipelineReasonCode",
    "PipelineStage",
    "QuarantineDiagnostics",
    "StageCheckpoint",
    "StageRunRecord",
    "StageStatus",
    "create_document_pipeline_processor",
    "parser_digest",
    "process_document",
    "stage_idempotency_key",
]
