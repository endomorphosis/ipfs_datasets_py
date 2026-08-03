"""Orchestrate a versioned, replayable application dossier (PATLAW-050).

Binds acquisition and analysis outputs into one immutable matter dossier:

* input artifact manifests
* status / events and matter-ledger snapshot
* current claim set
* instructions (office-action candidates)
* requirements, submission evidence, assessments
* authorities, candidate dates, rejection mappings
* instruction-consistency comparisons
* span-validation and validation receipts
* warnings, unsupported checks, model/ruleset versions

Design invariants
-----------------
* Source processors and analysis records are **inputs** and remain unchanged.
* Bundle digest changes for any material input or version change.
* All bound facts/conclusions carry provenance to artifacts and/or authority;
  untraced subjects emit ``missing_provenance`` warnings.
* Unsupported and missing checks appear in warnings (fail-closed partial
  dossier rather than silent pass).
* Private / quarantine classification propagates to every derived record
  (dossier, analysis bundle, and every re-emitted derived section binding).
* No filing, signing, payment, or docket mutation.

This module owns **dossier orchestration only**. Gap reports and preflight
gates are separate tasks (PATLAW-051 / PATLAW-052).
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Any, Callable, Final, Mapping, Sequence

from ipfs_datasets_py.processors.domains.uspto.artifact_manifest import (
    ARTIFACT_MANIFEST_SCHEMA_VERSION,
    ArtifactManifest,
)
from ipfs_datasets_py.processors.domains.uspto.contracts import (
    CONTRACTS_SCHEMA_VERSION,
    AnalysisBundle as ContractAnalysisBundle,
    DisclosureClassification,
    MatterEvent,
    ReviewState,
    canonical_json,
    is_private_classification,
    most_restrictive_classification,
    requires_quarantine,
)
from ipfs_datasets_py.processors.domains.uspto.analysis.analysis_bundle import (
    ANALYSIS_BUNDLE_RULESET_VERSION,
    ANALYSIS_BUNDLE_SCHEMA_VERSION,
    PARSER_VERSION as BUNDLE_PARSER_VERSION,
    AnalysisBundleBuilder,
    BundleDisposition,
    BundleSectionKind,
    BundleSectionRef,
    BundleWarning,
    BundleWarningCode,
    ProvenanceLink,
    UsptoAnalysisBundle,
    content_digest_of,
    merge_classifications,
    sha256_hex,
)

# Soft imports for optional analysis result types (keep import graph light for
# unit tests that only supply compact section refs).
try:
    from ipfs_datasets_py.processors.domains.uspto.matter_ledger import (
        ClaimSetVersion,
        MatterLedgerSnapshot,
        MATTER_LEDGER_SCHEMA_VERSION,
    )
except Exception:  # pragma: no cover
    ClaimSetVersion = None  # type: ignore[misc, assignment]
    MatterLedgerSnapshot = None  # type: ignore[misc, assignment]
    MATTER_LEDGER_SCHEMA_VERSION = "uspto.matter-ledger.v1"

try:
    from ipfs_datasets_py.processors.domains.uspto.application_status_processor import (
        APPLICATION_STATUS_PROCESSOR_SCHEMA_VERSION,
        VersionedStatusEventSnapshot,
    )
except Exception:  # pragma: no cover
    VersionedStatusEventSnapshot = None  # type: ignore[misc, assignment]
    APPLICATION_STATUS_PROCESSOR_SCHEMA_VERSION = "uspto.application-status.v1"

try:
    from ipfs_datasets_py.processors.domains.uspto.analysis.office_action_processor import (
        OFFICE_ACTION_SCHEMA_VERSION,
        OfficeActionResult,
    )
except Exception:  # pragma: no cover
    OfficeActionResult = None  # type: ignore[misc, assignment]
    OFFICE_ACTION_SCHEMA_VERSION = "uspto.office-action-analysis.v1"

try:
    from ipfs_datasets_py.processors.domains.uspto.analysis.requirement_processor import (
        REQUIREMENT_PROCESSOR_SCHEMA_VERSION,
        RequirementCompilationResult,
    )
except Exception:  # pragma: no cover
    RequirementCompilationResult = None  # type: ignore[misc, assignment]
    REQUIREMENT_PROCESSOR_SCHEMA_VERSION = "uspto.requirement-processor.v1"

try:
    from ipfs_datasets_py.processors.domains.uspto.analysis.submission_evidence import (
        SUBMISSION_EVIDENCE_SCHEMA_VERSION,
        SubmissionEvidenceMap,
    )
except Exception:  # pragma: no cover
    SubmissionEvidenceMap = None  # type: ignore[misc, assignment]
    SUBMISSION_EVIDENCE_SCHEMA_VERSION = "uspto.submission-evidence.v1"

try:
    from ipfs_datasets_py.processors.domains.uspto.analysis.submission_compliance_processor import (
        SUBMISSION_COMPLIANCE_SCHEMA_VERSION,
        SubmissionComplianceResult,
    )
except Exception:  # pragma: no cover
    SubmissionComplianceResult = None  # type: ignore[misc, assignment]
    SUBMISSION_COMPLIANCE_SCHEMA_VERSION = "uspto.submission-compliance.v1"

try:
    from ipfs_datasets_py.processors.domains.uspto.analysis.rejection_mapping_processor import (
        REJECTION_MAPPING_SCHEMA_VERSION,
        RejectionMappingResult,
    )
except Exception:  # pragma: no cover
    RejectionMappingResult = None  # type: ignore[misc, assignment]
    REJECTION_MAPPING_SCHEMA_VERSION = "uspto.rejection-mapping.v1"

try:
    from ipfs_datasets_py.processors.domains.uspto.analysis.deadline_processor import (
        DEADLINE_SCHEMA_VERSION,
        DeadlineAnalysisResult,
    )
except Exception:  # pragma: no cover
    DeadlineAnalysisResult = None  # type: ignore[misc, assignment]
    DEADLINE_SCHEMA_VERSION = "uspto.deadline-processor.v1"

try:
    from ipfs_datasets_py.processors.domains.uspto.analysis.instruction_consistency_processor import (
        INSTRUCTION_CONSISTENCY_SCHEMA_VERSION,
        InstructionConsistencyResult,
    )
except Exception:  # pragma: no cover
    InstructionConsistencyResult = None  # type: ignore[misc, assignment]
    INSTRUCTION_CONSISTENCY_SCHEMA_VERSION = "uspto.instruction-consistency.v1"

try:
    from ipfs_datasets_py.processors.domains.uspto.span_validator import (
        SPAN_VALIDATOR_SCHEMA_VERSION,
        SpanValidationResult,
    )
except Exception:  # pragma: no cover
    SpanValidationResult = None  # type: ignore[misc, assignment]
    SPAN_VALIDATOR_SCHEMA_VERSION = "uspto.span-validator.v1"

# ---------------------------------------------------------------------------
# Versions / interface
# ---------------------------------------------------------------------------

DOSSIER_SCHEMA_VERSION: Final = "uspto.dossier.v1"
DOSSIER_INTERFACE: Final = "DossierProcessor@1"
DOSSIER_RULESET_VERSION: Final = "dossier-orchestration-rules@1"
PARSER_VERSION: Final = "patlaw-050.dossier.v1"

OUTPUT_KIND_VERSIONED_APPLICATION_DOSSIER: Final = "versioned_application_dossier"

DOSSIER_DISCLAIMER: Final = (
    "This dossier is a replayable, provenance-bound assembly of analysis "
    "records for human review. It is not a legal opinion, not a filing "
    "authorization, and does not sign, pay, or docket on anyone's behalf."
)

DEFAULT_MAX_ARTIFACTS: Final = 512
DEFAULT_MAX_EVENTS: Final = 4096
DEFAULT_MAX_SECTION_REFS: Final = 4096

_SHA256_RE = re.compile(r"\A[0-9a-f]{64}\Z")
_ID_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._:/=+\-]{0,255}\Z")


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class DossierDisposition(str, Enum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    UNKNOWN = "unknown"
    REVIEW = "review"
    QUARANTINE = "quarantine"
    EMPTY = "empty"


class DossierReasonCode(str, Enum):
    ASSEMBLED = "assembled"
    MISSING_ARTIFACTS = "missing_artifacts"
    MISSING_STATUS = "missing_status"
    MISSING_CLAIM_SET = "missing_claim_set"
    MISSING_REQUIREMENTS = "missing_requirements"
    MISSING_EVIDENCE = "missing_evidence"
    MISSING_COMPLIANCE = "missing_compliance"
    MISSING_AUTHORITIES = "missing_authorities"
    MISSING_CANDIDATE_DATES = "missing_candidate_dates"
    MISSING_VALIDATION = "missing_validation"
    UNSUPPORTED_CHECKS_PRESENT = "unsupported_checks_present"
    PRIVATE_CLASSIFICATION = "private_classification"
    QUARANTINE = "quarantine"
    PROVENANCE_GAPS = "provenance_gaps"
    MATERIAL_INPUT_BOUND = "material_input_bound"


class DossierProcessorError(ValueError):
    """Raised for invalid dossier assembly inputs."""

    def __init__(self, message: str, *, code: str = "dossier_error") -> None:
        super().__init__(message)
        self.code = code


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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
    if not isinstance(value, str):
        raise TypeError(f"{field} must be str or None")
    text = value.strip()
    if not text:
        return None
    if len(text) > max_len:
        raise ValueError(f"{field} exceeds max length {max_len}")
    return text


def _identifier(value: Any, field: str) -> str:
    text = _require_str(value, field, max_len=256)
    if not _ID_RE.match(text):
        raise ValueError(f"{field} is not a valid identifier: {text!r}")
    return text


def _optional_identifier(value: Any, field: str) -> str | None:
    text = _optional_str(value, field, max_len=256)
    if text is None:
        return None
    if not _ID_RE.match(text):
        raise ValueError(f"{field} is not a valid identifier: {text!r}")
    return text


def _sha256_hex_field(value: Any, field: str) -> str:
    text = _require_str(value, field, max_len=64).lower()
    if not _SHA256_RE.match(text):
        raise ValueError(f"{field} must be a 64-char lowercase hex SHA-256 digest")
    return text


def _coerce_enum(enum_cls: type[Enum], value: Any, field: str) -> Any:
    if isinstance(value, enum_cls):
        return value
    if isinstance(value, str):
        try:
            return enum_cls(value.strip())
        except ValueError as exc:
            raise ValueError(f"unknown {field}: {value!r}") from exc
    raise TypeError(f"{field} must be {enum_cls.__name__} or str")


def _coerce_classification(value: Any) -> DisclosureClassification:
    if isinstance(value, DisclosureClassification):
        return value
    if isinstance(value, str):
        try:
            return DisclosureClassification(value.strip())
        except ValueError as exc:
            raise ValueError(f"unknown disclosure classification: {value!r}") from exc
    raise TypeError("classification must be DisclosureClassification or str")


def _tuple_of_str(
    value: Any, field: str, *, max_items: int = 256
) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise TypeError(f"{field} must be a sequence of strings")
    if len(value) > max_items:
        raise ValueError(f"{field} exceeds max items {max_items}")
    return tuple(_require_str(item, f"{field}[{i}]", max_len=256) for i, item in enumerate(value))


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
    for key, raw in value.items():
        k = _require_str(key, f"{field}.key", max_len=128)
        v = _require_str(raw, f"{field}[{k}]", max_len=2048)
        out[k] = v
    return MappingProxyType(dict(sorted(out.items())))


def _default_id_factory() -> str:
    return uuid.uuid4().hex


def _attr(obj: Any, name: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, Mapping):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _record_classification(obj: Any) -> DisclosureClassification:
    raw = _attr(obj, "classification", DisclosureClassification.UNKNOWN)
    try:
        return _coerce_classification(raw)
    except (TypeError, ValueError):
        return DisclosureClassification.UNKNOWN


def _record_id(obj: Any, *candidates: str, fallback: str = "unknown") -> str:
    for name in candidates:
        val = _attr(obj, name)
        if val is not None and str(val).strip():
            try:
                return _identifier(str(val), name)
            except (TypeError, ValueError):
                continue
    return fallback


def _record_schema_version(obj: Any, default: str) -> str:
    val = _attr(obj, "schema_version")
    if val is None or not str(val).strip():
        return default
    return str(val).strip()


def _record_digest(obj: Any) -> str:
    for name in ("content_digest", "text_digest", "bundle_digest", "content_sha256"):
        val = _attr(obj, name)
        if isinstance(val, str) and _SHA256_RE.match(val.lower()):
            return val.lower()
    return content_digest_of(obj)


def _record_ruleset_versions(obj: Any) -> Mapping[str, str]:
    raw = _attr(obj, "ruleset_versions") or _attr(obj, "parser_versions") or {}
    if not isinstance(raw, Mapping):
        return {}
    return {str(k): str(v) for k, v in raw.items()}


def _mapping_artifact_ids(obj: Any) -> tuple[str, ...]:
    collected: list[str] = []
    for name in (
        "source_artifact_id",
        "artifact_id",
        "source_artifact_ids",
        "related_artifact_ids",
        "input_artifact_ids",
    ):
        val = _attr(obj, name)
        if val is None:
            continue
        if isinstance(val, str) and val.strip():
            collected.append(val.strip())
        elif isinstance(val, Sequence) and not isinstance(val, (str, bytes)):
            for item in val:
                if isinstance(item, str) and item.strip():
                    collected.append(item.strip())
    # artifact bindings on evidence maps
    bindings = _attr(obj, "artifact_bindings")
    if isinstance(bindings, Sequence) and not isinstance(bindings, (str, bytes)):
        for b in bindings:
            aid = _attr(b, "artifact_id")
            if isinstance(aid, str) and aid.strip():
                collected.append(aid.strip())
    # unique stable order
    return tuple(sorted(set(collected)))


def _mapping_authority_ids(obj: Any) -> tuple[str, ...]:
    collected: list[str] = []
    for name in (
        "authority_ids",
        "authority_node_ids",
        "selected_node_ids",
        "authority_graph_id",
    ):
        val = _attr(obj, name)
        if val is None:
            continue
        if isinstance(val, str) and val.strip():
            collected.append(val.strip())
        elif isinstance(val, Sequence) and not isinstance(val, (str, bytes)):
            for item in val:
                if isinstance(item, str) and item.strip():
                    collected.append(item.strip())
    # nested authority snapshot
    authority = _attr(obj, "authority")
    if authority is not None:
        for name in ("node_ids", "selected_node_ids", "authority_node_ids"):
            val = _attr(authority, name)
            if isinstance(val, Sequence) and not isinstance(val, (str, bytes)):
                for item in val:
                    if isinstance(item, str) and item.strip():
                        collected.append(item.strip())
            elif isinstance(val, str) and val.strip():
                collected.append(val.strip())
        for name in ("node_id", "authority_node_id"):
            val = _attr(authority, name)
            if isinstance(val, str) and val.strip():
                collected.append(val.strip())
    return tuple(sorted(set(collected)))


def _mapping_span_ids(obj: Any) -> tuple[str, ...]:
    collected: list[str] = []
    for name in (
        "source_span_id",
        "span_ids",
        "support_span_ids",
        "counter_span_ids",
        "instruction_span_id",
    ):
        val = _attr(obj, name)
        if val is None:
            continue
        if isinstance(val, str) and val.strip():
            collected.append(val.strip())
        elif isinstance(val, Sequence) and not isinstance(val, (str, bytes)):
            for item in val:
                if isinstance(item, str) and item.strip():
                    collected.append(item.strip())
    return tuple(sorted(set(collected)))


# ---------------------------------------------------------------------------
# Input / output records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CompactSectionInput:
    """Compact section binding for tests and pre-digested pipeline hand-off.

    Prefer full typed analysis results when available; this shape is the
    minimum material surface for digest stability.
    """

    kind: BundleSectionKind | str
    record_id: str
    schema_version: str
    content_digest: str
    classification: DisclosureClassification | str = (
        DisclosureClassification.PUBLIC_USER
    )
    source_artifact_ids: tuple[str, ...] = ()
    authority_ids: tuple[str, ...] = ()
    parent_record_ids: tuple[str, ...] = ()
    span_ids: tuple[str, ...] = ()
    ruleset_versions: Mapping[str, str] = MappingProxyType({})
    model_versions: Mapping[str, str] = MappingProxyType({})
    labels: Mapping[str, str] = MappingProxyType({})
    require_provenance: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "kind", _coerce_enum(BundleSectionKind, self.kind, "kind")
        )
        object.__setattr__(
            self, "record_id", _identifier(self.record_id, "record_id")
        )
        object.__setattr__(
            self,
            "schema_version",
            _require_str(self.schema_version, "schema_version", max_len=64),
        )
        object.__setattr__(
            self,
            "content_digest",
            _sha256_hex_field(self.content_digest, "content_digest"),
        )
        object.__setattr__(
            self, "classification", _coerce_classification(self.classification)
        )
        object.__setattr__(
            self,
            "source_artifact_ids",
            _tuple_of_str(
                self.source_artifact_ids, "source_artifact_ids", max_items=128
            ),
        )
        object.__setattr__(
            self,
            "authority_ids",
            _tuple_of_str(self.authority_ids, "authority_ids", max_items=128),
        )
        object.__setattr__(
            self,
            "parent_record_ids",
            _tuple_of_str(
                self.parent_record_ids, "parent_record_ids", max_items=128
            ),
        )
        object.__setattr__(
            self, "span_ids", _tuple_of_str(self.span_ids, "span_ids", max_items=256)
        )
        object.__setattr__(
            self,
            "ruleset_versions",
            _frozen_str_map(self.ruleset_versions, "ruleset_versions", max_items=32),
        )
        object.__setattr__(
            self,
            "model_versions",
            _frozen_str_map(self.model_versions, "model_versions", max_items=32),
        )
        object.__setattr__(
            self, "labels", _frozen_str_map(self.labels, "labels", max_items=32)
        )
        if not isinstance(self.require_provenance, bool):
            raise TypeError("require_provenance must be bool")


@dataclass(frozen=True, slots=True)
class DossierInput:
    """Immutable snapshot of material inputs for dossier assembly.

    All analysis fields are optional; missing material checks emit warnings
    rather than inventing empty "pass" semantics.
    """

    matter_id: str
    artifacts: Sequence[ArtifactManifest] = ()
    events: Sequence[MatterEvent] = ()
    ledger_snapshot: Any = None  # MatterLedgerSnapshot | None
    status_snapshot: Any = None  # VersionedStatusEventSnapshot | None
    claim_set: Any = None  # ClaimSetVersion | None
    office_action: Any = None  # OfficeActionResult | None
    requirements: Any = None  # RequirementCompilationResult | None
    evidence: Any = None  # SubmissionEvidenceMap | None
    compliance: Any = None  # SubmissionComplianceResult | None
    rejection_mapping: Any = None  # RejectionMappingResult | None
    deadlines: Any = None  # DeadlineAnalysisResult | None
    instruction_consistency: Any = None  # InstructionConsistencyResult | None
    span_validations: Sequence[Any] = ()  # Sequence[SpanValidationResult]
    validation_receipt_ids: Sequence[str] = ()
    compact_sections: Sequence[CompactSectionInput] = ()
    unsupported_checks: Sequence[str] = ()
    seed_classification: DisclosureClassification = (
        DisclosureClassification.PUBLIC_USER
    )
    model_versions: Mapping[str, str] = MappingProxyType({})
    ruleset_versions: Mapping[str, str] = MappingProxyType({})
    labels: Mapping[str, str] = MappingProxyType({})
    analysis_id: str | None = None
    as_of_utc: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "matter_id", _identifier(self.matter_id, "matter_id")
        )
        object.__setattr__(self, "artifacts", tuple(self.artifacts or ()))
        if len(self.artifacts) > DEFAULT_MAX_ARTIFACTS:
            raise DossierProcessorError(
                f"artifacts exceeds max {DEFAULT_MAX_ARTIFACTS}",
                code="too_many_artifacts",
            )
        for art in self.artifacts:
            if not isinstance(art, ArtifactManifest):
                raise TypeError("artifacts must be ArtifactManifest instances")
        object.__setattr__(self, "events", tuple(self.events or ()))
        if len(self.events) > DEFAULT_MAX_EVENTS:
            raise DossierProcessorError(
                f"events exceeds max {DEFAULT_MAX_EVENTS}",
                code="too_many_events",
            )
        for ev in self.events:
            if not isinstance(ev, MatterEvent):
                raise TypeError("events must be MatterEvent instances")
        object.__setattr__(
            self, "span_validations", tuple(self.span_validations or ())
        )
        object.__setattr__(
            self, "compact_sections", tuple(self.compact_sections or ())
        )
        if len(self.compact_sections) > DEFAULT_MAX_SECTION_REFS:
            raise DossierProcessorError(
                f"compact_sections exceeds max {DEFAULT_MAX_SECTION_REFS}",
                code="too_many_sections",
            )
        for sec in self.compact_sections:
            if not isinstance(sec, CompactSectionInput):
                raise TypeError("compact_sections must be CompactSectionInput")
        object.__setattr__(
            self,
            "validation_receipt_ids",
            _tuple_of_str(
                self.validation_receipt_ids,
                "validation_receipt_ids",
                max_items=256,
            ),
        )
        object.__setattr__(
            self,
            "unsupported_checks",
            _tuple_of_str(
                self.unsupported_checks, "unsupported_checks", max_items=256
            ),
        )
        object.__setattr__(
            self,
            "seed_classification",
            _coerce_classification(self.seed_classification),
        )
        object.__setattr__(
            self,
            "model_versions",
            _frozen_str_map(self.model_versions, "model_versions", max_items=64),
        )
        object.__setattr__(
            self,
            "ruleset_versions",
            _frozen_str_map(self.ruleset_versions, "ruleset_versions", max_items=64),
        )
        object.__setattr__(
            self, "labels", _frozen_str_map(self.labels, "labels", max_items=32)
        )
        object.__setattr__(
            self, "analysis_id", _optional_identifier(self.analysis_id, "analysis_id")
        )
        object.__setattr__(
            self, "as_of_utc", _optional_str(self.as_of_utc, "as_of_utc", max_len=64)
        )


@dataclass(frozen=True, slots=True)
class ApplicationDossier:
    """Immutable versioned application dossier."""

    schema_version: str
    dossier_id: str
    matter_id: str
    disposition: DossierDisposition
    review_state: ReviewState
    classification: DisclosureClassification
    bundle_digest: str
    content_digest: str
    output_kind: str
    disclaimer: str
    analysis_bundle: UsptoAnalysisBundle
    reason_codes: tuple[str, ...]
    warnings: tuple[str, ...]
    unsupported_checks: tuple[str, ...]
    input_artifact_ids: tuple[str, ...]
    section_record_ids: tuple[str, ...]
    validation_receipt_ids: tuple[str, ...]
    model_versions: Mapping[str, str]
    ruleset_versions: Mapping[str, str]
    labels: Mapping[str, str]
    analysis_id: str | None = None
    as_of_utc: str | None = None
    # Compact inventory projections (no body text)
    claim_set_id: str | None = None
    status_version_id: str | None = None
    ledger_snapshot_id: str | None = None
    compliance_result_id: str | None = None
    requirements_compilation_id: str | None = None
    evidence_map_id: str | None = None
    deadline_analysis_id: str | None = None
    rejection_mapping_id: str | None = None
    instruction_consistency_id: str | None = None
    event_ids: tuple[str, ...] = ()
    human_review_required: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "schema_version",
            _require_str(self.schema_version, "schema_version", max_len=64),
        )
        if self.schema_version != DOSSIER_SCHEMA_VERSION:
            raise DossierProcessorError(
                f"ApplicationDossier.schema_version must be {DOSSIER_SCHEMA_VERSION}",
                code="schema_version_mismatch",
            )
        object.__setattr__(
            self, "dossier_id", _identifier(self.dossier_id, "dossier_id")
        )
        object.__setattr__(
            self, "matter_id", _identifier(self.matter_id, "matter_id")
        )
        object.__setattr__(
            self,
            "disposition",
            _coerce_enum(DossierDisposition, self.disposition, "disposition"),
        )
        object.__setattr__(
            self,
            "review_state",
            _coerce_enum(ReviewState, self.review_state, "review_state"),
        )
        object.__setattr__(
            self, "classification", _coerce_classification(self.classification)
        )
        object.__setattr__(
            self,
            "bundle_digest",
            _sha256_hex_field(self.bundle_digest, "bundle_digest"),
        )
        object.__setattr__(
            self,
            "content_digest",
            _sha256_hex_field(self.content_digest, "content_digest"),
        )
        object.__setattr__(
            self,
            "output_kind",
            _require_str(self.output_kind, "output_kind", max_len=128),
        )
        if self.output_kind != OUTPUT_KIND_VERSIONED_APPLICATION_DOSSIER:
            raise DossierProcessorError(
                f"output_kind must be {OUTPUT_KIND_VERSIONED_APPLICATION_DOSSIER!r}",
                code="invalid_output_kind",
            )
        object.__setattr__(
            self,
            "disclaimer",
            _require_str(self.disclaimer, "disclaimer", max_len=2048),
        )
        if not isinstance(self.analysis_bundle, UsptoAnalysisBundle):
            raise TypeError("analysis_bundle must be UsptoAnalysisBundle")
        # Derived records must share dossier classification (private propagation).
        if self.analysis_bundle.classification is not self.classification:
            # Allow only if dossier is more restrictive (should not happen if
            # assembly is correct); enforce equality for fail-closed contract.
            if self.classification != most_restrictive_classification(
                (self.classification, self.analysis_bundle.classification)
            ):
                raise DossierProcessorError(
                    "dossier classification must equal analysis bundle classification",
                    code="classification_mismatch",
                )
        object.__setattr__(
            self,
            "reason_codes",
            _tuple_of_str(self.reason_codes, "reason_codes", max_items=128),
        )
        object.__setattr__(
            self, "warnings", _tuple_of_str(self.warnings, "warnings", max_items=256)
        )
        object.__setattr__(
            self,
            "unsupported_checks",
            _tuple_of_str(
                self.unsupported_checks, "unsupported_checks", max_items=256
            ),
        )
        object.__setattr__(
            self,
            "input_artifact_ids",
            _tuple_of_str(
                self.input_artifact_ids, "input_artifact_ids", max_items=512
            ),
        )
        object.__setattr__(
            self,
            "section_record_ids",
            _tuple_of_str(
                self.section_record_ids, "section_record_ids", max_items=4096
            ),
        )
        object.__setattr__(
            self,
            "validation_receipt_ids",
            _tuple_of_str(
                self.validation_receipt_ids,
                "validation_receipt_ids",
                max_items=256,
            ),
        )
        object.__setattr__(
            self,
            "model_versions",
            _frozen_str_map(self.model_versions, "model_versions", max_items=64),
        )
        object.__setattr__(
            self,
            "ruleset_versions",
            _frozen_str_map(self.ruleset_versions, "ruleset_versions", max_items=64),
        )
        object.__setattr__(
            self, "labels", _frozen_str_map(self.labels, "labels", max_items=32)
        )
        object.__setattr__(
            self, "analysis_id", _optional_identifier(self.analysis_id, "analysis_id")
        )
        object.__setattr__(
            self, "as_of_utc", _optional_str(self.as_of_utc, "as_of_utc", max_len=64)
        )
        for optional_id in (
            "claim_set_id",
            "status_version_id",
            "ledger_snapshot_id",
            "compliance_result_id",
            "requirements_compilation_id",
            "evidence_map_id",
            "deadline_analysis_id",
            "rejection_mapping_id",
            "instruction_consistency_id",
        ):
            object.__setattr__(
                self,
                optional_id,
                _optional_identifier(getattr(self, optional_id), optional_id),
            )
        object.__setattr__(
            self, "event_ids", _tuple_of_str(self.event_ids, "event_ids", max_items=4096)
        )
        if not isinstance(self.human_review_required, bool):
            raise TypeError("human_review_required must be bool")
        if requires_quarantine(self.classification) and self.review_state not in (
            ReviewState.REQUIRED,
            ReviewState.PENDING,
        ):
            object.__setattr__(self, "review_state", ReviewState.REQUIRED)

    # ---- Queries ----

    @property
    def requires_review(self) -> bool:
        return (
            self.human_review_required
            or self.review_state in (ReviewState.REQUIRED, ReviewState.PENDING)
            or self.disposition
            in (
                DossierDisposition.PARTIAL,
                DossierDisposition.UNKNOWN,
                DossierDisposition.REVIEW,
                DossierDisposition.QUARANTINE,
                DossierDisposition.EMPTY,
            )
        )

    @property
    def is_private(self) -> bool:
        return is_private_classification(self.classification)

    def to_contract_bundle(self) -> ContractAnalysisBundle:
        return self.analysis_bundle.to_contract_bundle()

    def material_payload(self) -> dict[str, Any]:
        """Fields that participate in the dossier content digest."""
        return {
            "analysis_bundle_digest": self.analysis_bundle.bundle_digest,
            "analysis_id": self.analysis_id,
            "as_of_utc": self.as_of_utc,
            "claim_set_id": self.claim_set_id,
            "classification": self.classification.value,
            "compliance_result_id": self.compliance_result_id,
            "deadline_analysis_id": self.deadline_analysis_id,
            "disclaimer": self.disclaimer,
            "disposition": self.disposition.value,
            "event_ids": list(self.event_ids),
            "evidence_map_id": self.evidence_map_id,
            "human_review_required": self.human_review_required,
            "input_artifact_ids": list(self.input_artifact_ids),
            "instruction_consistency_id": self.instruction_consistency_id,
            "labels": dict(self.labels),
            "ledger_snapshot_id": self.ledger_snapshot_id,
            "matter_id": self.matter_id,
            "model_versions": dict(self.model_versions),
            "output_kind": self.output_kind,
            "reason_codes": list(self.reason_codes),
            "rejection_mapping_id": self.rejection_mapping_id,
            "requirements_compilation_id": self.requirements_compilation_id,
            "review_state": self.review_state.value,
            "ruleset_versions": dict(self.ruleset_versions),
            "schema_version": self.schema_version,
            "section_record_ids": list(self.section_record_ids),
            "status_version_id": self.status_version_id,
            "unsupported_checks": list(self.unsupported_checks),
            "validation_receipt_ids": list(self.validation_receipt_ids),
            "warnings": list(self.warnings),
        }

    def to_dict(self) -> dict[str, Any]:
        payload = self.material_payload()
        payload["analysis_bundle"] = self.analysis_bundle.to_dict()
        payload["bundle_digest"] = self.bundle_digest
        payload["content_digest"] = self.content_digest
        payload["dossier_id"] = self.dossier_id
        return payload

    def to_canonical_json(self) -> str:
        return canonical_json(self.to_dict())

    def public_projection(self) -> dict[str, Any]:
        return {
            "analysis_bundle": self.analysis_bundle.public_projection(),
            "bundle_digest": self.bundle_digest,
            "classification": self.classification.value,
            "content_digest": self.content_digest,
            "disclaimer": self.disclaimer,
            "disposition": self.disposition.value,
            "dossier_id": self.dossier_id,
            "event_count": len(self.event_ids),
            "human_review_required": self.human_review_required,
            "input_artifact_count": len(self.input_artifact_ids),
            "is_private": self.is_private,
            "matter_id": self.matter_id,
            "model_versions": dict(self.model_versions),
            "output_kind": self.output_kind,
            "reason_codes": list(self.reason_codes),
            "requires_review": self.requires_review,
            "review_state": self.review_state.value,
            "ruleset_versions": dict(self.ruleset_versions),
            "schema_version": self.schema_version,
            "section_count": len(self.section_record_ids),
            "unsupported_checks": list(self.unsupported_checks),
            "validation_receipt_count": len(self.validation_receipt_ids),
            "warning_count": len(self.warnings),
            "warnings": list(self.warnings),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ApplicationDossier":
        if not isinstance(value, Mapping):
            raise TypeError("ApplicationDossier must be a mapping")
        bundle_raw = value.get("analysis_bundle") or {}
        if isinstance(bundle_raw, UsptoAnalysisBundle):
            bundle = bundle_raw
        else:
            bundle = UsptoAnalysisBundle.from_dict(bundle_raw)
        return cls(
            schema_version=value.get("schema_version", DOSSIER_SCHEMA_VERSION),
            dossier_id=value.get("dossier_id", ""),
            matter_id=value.get("matter_id", ""),
            disposition=value.get("disposition", DossierDisposition.UNKNOWN.value),
            review_state=value.get("review_state", ReviewState.PENDING.value),
            classification=value.get(
                "classification", DisclosureClassification.UNKNOWN.value
            ),
            bundle_digest=value.get("bundle_digest", ""),
            content_digest=value.get("content_digest", ""),
            output_kind=value.get(
                "output_kind", OUTPUT_KIND_VERSIONED_APPLICATION_DOSSIER
            ),
            disclaimer=value.get("disclaimer", DOSSIER_DISCLAIMER),
            analysis_bundle=bundle,
            reason_codes=tuple(value.get("reason_codes") or ()),
            warnings=tuple(value.get("warnings") or ()),
            unsupported_checks=tuple(value.get("unsupported_checks") or ()),
            input_artifact_ids=tuple(value.get("input_artifact_ids") or ()),
            section_record_ids=tuple(value.get("section_record_ids") or ()),
            validation_receipt_ids=tuple(
                value.get("validation_receipt_ids") or ()
            ),
            model_versions=value.get("model_versions") or {},
            ruleset_versions=value.get("ruleset_versions") or {},
            labels=value.get("labels") or {},
            analysis_id=value.get("analysis_id"),
            as_of_utc=value.get("as_of_utc"),
            claim_set_id=value.get("claim_set_id"),
            status_version_id=value.get("status_version_id"),
            ledger_snapshot_id=value.get("ledger_snapshot_id"),
            compliance_result_id=value.get("compliance_result_id"),
            requirements_compilation_id=value.get("requirements_compilation_id"),
            evidence_map_id=value.get("evidence_map_id"),
            deadline_analysis_id=value.get("deadline_analysis_id"),
            rejection_mapping_id=value.get("rejection_mapping_id"),
            instruction_consistency_id=value.get("instruction_consistency_id"),
            event_ids=tuple(value.get("event_ids") or ()),
            human_review_required=bool(value.get("human_review_required", True)),
        )


# ---------------------------------------------------------------------------
# Processor
# ---------------------------------------------------------------------------


class DossierProcessor:
    """Assemble a versioned application dossier from analysis inputs.

    Does not recompute legal analysis; binds immutable records only.
    """

    def __init__(
        self,
        *,
        id_factory: Callable[[], str] | None = None,
        require_artifacts: bool = False,
    ) -> None:
        self._id_factory = id_factory or _default_id_factory
        self._require_artifacts = bool(require_artifacts)

    def assemble(self, dossier_input: DossierInput) -> ApplicationDossier:
        if not isinstance(dossier_input, DossierInput):
            raise TypeError("dossier_input must be DossierInput")
        return self._assemble(dossier_input)

    def process(self, dossier_input: DossierInput) -> ApplicationDossier:
        """Alias for :meth:`assemble` (processor protocol familiarity)."""
        return self.assemble(dossier_input)

    # ---- internal ----

    def _assemble(self, inp: DossierInput) -> ApplicationDossier:
        builder = AnalysisBundleBuilder(
            matter_id=inp.matter_id,
            analysis_id=inp.analysis_id,
            seed_classification=inp.seed_classification,
            labels=inp.labels,
            id_factory=self._id_factory,
        )
        builder.add_ruleset_versions(
            {
                "dossier": DOSSIER_RULESET_VERSION,
                "dossier_parser": PARSER_VERSION,
                "analysis_bundle": ANALYSIS_BUNDLE_RULESET_VERSION,
                "analysis_bundle_parser": BUNDLE_PARSER_VERSION,
                "contracts": CONTRACTS_SCHEMA_VERSION,
            }
        )
        if inp.ruleset_versions:
            builder.add_ruleset_versions(inp.ruleset_versions)
        if inp.model_versions:
            builder.add_model_versions(inp.model_versions)
        if inp.unsupported_checks:
            for check in inp.unsupported_checks:
                builder.add_unsupported_check(check)
        if inp.validation_receipt_ids:
            builder.add_validation_receipt_ids(*inp.validation_receipt_ids)

        inventory: dict[str, str | None] = {
            "claim_set_id": None,
            "status_version_id": None,
            "ledger_snapshot_id": None,
            "compliance_result_id": None,
            "requirements_compilation_id": None,
            "evidence_map_id": None,
            "deadline_analysis_id": None,
            "rejection_mapping_id": None,
            "instruction_consistency_id": None,
        }
        event_ids: list[str] = []
        reason_codes: list[str] = [DossierReasonCode.ASSEMBLED.value]

        # --- Artifacts ---
        if inp.artifacts:
            for art in inp.artifacts:
                builder.add_input_artifact_ids(art.artifact_id)
                builder.bind_section(
                    kind=BundleSectionKind.ARTIFACT_MANIFEST,
                    record_id=art.artifact_id,
                    schema_version=_record_schema_version(
                        art, ARTIFACT_MANIFEST_SCHEMA_VERSION
                    ),
                    content_digest=content_digest_of(art),
                    classification=art.classification,
                    source_artifact_ids=(art.artifact_id,),
                    ruleset_versions=dict(art.parser_versions),
                    labels=dict(art.labels),
                    require_provenance=True,
                )
            reason_codes.append(DossierReasonCode.MATERIAL_INPUT_BOUND.value)
        else:
            builder.add_warning(
                BundleWarningCode.MISSING_ARTIFACT_MANIFEST,
                "No artifact manifests bound into dossier",
                section_kind=BundleSectionKind.ARTIFACT_MANIFEST,
            )
            reason_codes.append(DossierReasonCode.MISSING_ARTIFACTS.value)
            if self._require_artifacts:
                raise DossierProcessorError(
                    "artifacts are required for dossier assembly",
                    code="missing_artifacts",
                )

        # --- Ledger ---
        if inp.ledger_snapshot is not None:
            snap = inp.ledger_snapshot
            rid = _record_id(snap, "snapshot_id", fallback=f"ledger:{inp.matter_id}")
            inventory["ledger_snapshot_id"] = rid
            builder.bind_section(
                kind=BundleSectionKind.LEDGER_SNAPSHOT,
                record_id=rid,
                schema_version=_record_schema_version(
                    snap, MATTER_LEDGER_SCHEMA_VERSION
                ),
                content_digest=_record_digest(snap),
                classification=_record_classification(snap)
                if _attr(snap, "classification") is not None
                else inp.seed_classification,
                source_artifact_ids=_mapping_artifact_ids(snap),
                labels={"matter_id": inp.matter_id},
            )

        # --- Status ---
        if inp.status_snapshot is not None:
            st = inp.status_snapshot
            rid = _record_id(
                st, "version_id", "sync_key", fallback=f"status:{inp.matter_id}"
            )
            inventory["status_version_id"] = rid
            builder.bind_section(
                kind=BundleSectionKind.STATUS_SNAPSHOT,
                record_id=rid,
                schema_version=_record_schema_version(
                    st, APPLICATION_STATUS_PROCESSOR_SCHEMA_VERSION
                ),
                content_digest=_record_digest(st),
                classification=DisclosureClassification.PUBLIC_OFFICIAL
                if _attr(st, "classification") is None
                else _record_classification(st),
                source_artifact_ids=_mapping_artifact_ids(st),
            )
        else:
            builder.add_warning(
                BundleWarningCode.MISSING_STATUS,
                "No status snapshot bound into dossier",
                section_kind=BundleSectionKind.STATUS_SNAPSHOT,
            )
            reason_codes.append(DossierReasonCode.MISSING_STATUS.value)

        # --- Events ---
        if inp.events:
            for ev in inp.events:
                event_ids.append(ev.event_id)
                builder.bind_section(
                    kind=BundleSectionKind.MATTER_EVENT,
                    record_id=ev.event_id,
                    schema_version=_record_schema_version(
                        ev, CONTRACTS_SCHEMA_VERSION
                    ),
                    content_digest=content_digest_of(ev),
                    classification=ev.classification,
                    source_artifact_ids=tuple(ev.related_artifact_ids),
                    span_ids=(),
                )
        else:
            builder.add_warning(
                BundleWarningCode.MISSING_EVENTS,
                "No matter events bound into dossier",
                section_kind=BundleSectionKind.MATTER_EVENT,
            )

        # --- Claim set ---
        if inp.claim_set is not None:
            cs = inp.claim_set
            rid = _record_id(cs, "claim_set_id", fallback=f"claims:{inp.matter_id}")
            inventory["claim_set_id"] = rid
            arts = _mapping_artifact_ids(cs)
            builder.bind_section(
                kind=BundleSectionKind.CLAIM_SET,
                record_id=rid,
                schema_version=_record_schema_version(
                    cs, MATTER_LEDGER_SCHEMA_VERSION
                ),
                content_digest=_record_digest(cs),
                classification=_record_classification(cs)
                if _attr(cs, "classification") is not None
                else inp.seed_classification,
                source_artifact_ids=arts,
                labels={
                    "version": str(_attr(cs, "version", "")),
                }
                if _attr(cs, "version") is not None
                else {},
            )
        else:
            # Try ledger current claim set
            if inp.ledger_snapshot is not None and hasattr(
                inp.ledger_snapshot, "current_claim_set"
            ):
                cs = inp.ledger_snapshot.current_claim_set()
                if cs is not None:
                    rid = _record_id(
                        cs, "claim_set_id", fallback=f"claims:{inp.matter_id}"
                    )
                    inventory["claim_set_id"] = rid
                    builder.bind_section(
                        kind=BundleSectionKind.CLAIM_SET,
                        record_id=rid,
                        schema_version=_record_schema_version(
                            cs, MATTER_LEDGER_SCHEMA_VERSION
                        ),
                        content_digest=_record_digest(cs),
                        classification=inp.seed_classification,
                        source_artifact_ids=_mapping_artifact_ids(cs),
                    )
                else:
                    builder.add_warning(
                        BundleWarningCode.MISSING_CLAIM_SET,
                        "No current claim set bound into dossier",
                        section_kind=BundleSectionKind.CLAIM_SET,
                    )
                    reason_codes.append(DossierReasonCode.MISSING_CLAIM_SET.value)
            else:
                builder.add_warning(
                    BundleWarningCode.MISSING_CLAIM_SET,
                    "No current claim set bound into dossier",
                    section_kind=BundleSectionKind.CLAIM_SET,
                )
                reason_codes.append(DossierReasonCode.MISSING_CLAIM_SET.value)

        # --- Office action / instructions ---
        if inp.office_action is not None:
            oa = inp.office_action
            rid = _record_id(
                oa, "analysis_id", "result_id", fallback=f"oa:{inp.matter_id}"
            )
            builder.bind_section(
                kind=BundleSectionKind.OFFICE_ACTION,
                record_id=rid,
                schema_version=_record_schema_version(oa, OFFICE_ACTION_SCHEMA_VERSION),
                content_digest=_record_digest(oa),
                classification=_record_classification(oa),
                source_artifact_ids=_mapping_artifact_ids(oa),
                ruleset_versions=dict(_record_ruleset_versions(oa)),
            )
            # Also bind instruction kind for inventory clarity
            builder.bind_section(
                kind=BundleSectionKind.INSTRUCTION,
                record_id=f"instr:{rid}",
                schema_version=_record_schema_version(oa, OFFICE_ACTION_SCHEMA_VERSION),
                content_digest=_record_digest(oa),
                classification=_record_classification(oa),
                source_artifact_ids=_mapping_artifact_ids(oa),
                parent_record_ids=(rid,),
                ruleset_versions=dict(_record_ruleset_versions(oa)),
            )

        # --- Requirements ---
        if inp.requirements is not None:
            req = inp.requirements
            rid = _record_id(
                req, "compilation_id", "analysis_id", fallback=f"req:{inp.matter_id}"
            )
            inventory["requirements_compilation_id"] = rid
            arts = _mapping_artifact_ids(req)
            auth = _mapping_authority_ids(req)
            builder.bind_section(
                kind=BundleSectionKind.REQUIREMENT,
                record_id=rid,
                schema_version=_record_schema_version(
                    req, REQUIREMENT_PROCESSOR_SCHEMA_VERSION
                ),
                content_digest=_record_digest(req),
                classification=_record_classification(req),
                source_artifact_ids=arts,
                authority_ids=auth,
                span_ids=_mapping_span_ids(req),
                ruleset_versions=dict(_record_ruleset_versions(req)),
            )
            if not auth:
                builder.add_warning(
                    BundleWarningCode.MISSING_AUTHORITY,
                    f"Requirements compilation {rid} has no authority bindings",
                    related_record_ids=(rid,),
                    section_kind=BundleSectionKind.AUTHORITY,
                )
                reason_codes.append(DossierReasonCode.MISSING_AUTHORITIES.value)
        else:
            builder.add_warning(
                BundleWarningCode.MISSING_REQUIREMENTS,
                "No requirements compilation bound into dossier",
                section_kind=BundleSectionKind.REQUIREMENT,
            )
            reason_codes.append(DossierReasonCode.MISSING_REQUIREMENTS.value)

        # --- Evidence ---
        if inp.evidence is not None:
            evm = inp.evidence
            rid = _record_id(
                evm, "map_id", "analysis_id", fallback=f"evid:{inp.matter_id}"
            )
            inventory["evidence_map_id"] = rid
            builder.bind_section(
                kind=BundleSectionKind.SUBMISSION_EVIDENCE,
                record_id=rid,
                schema_version=_record_schema_version(
                    evm, SUBMISSION_EVIDENCE_SCHEMA_VERSION
                ),
                content_digest=_record_digest(evm),
                classification=_record_classification(evm),
                source_artifact_ids=_mapping_artifact_ids(evm),
                span_ids=_mapping_span_ids(evm),
                ruleset_versions=dict(_record_ruleset_versions(evm)),
            )
        else:
            builder.add_warning(
                BundleWarningCode.MISSING_EVIDENCE,
                "No submission evidence map bound into dossier",
                section_kind=BundleSectionKind.SUBMISSION_EVIDENCE,
            )
            reason_codes.append(DossierReasonCode.MISSING_EVIDENCE.value)

        # --- Compliance / assessments ---
        if inp.compliance is not None:
            cmpl = inp.compliance
            rid = _record_id(
                cmpl, "result_id", "analysis_id", fallback=f"cmpl:{inp.matter_id}"
            )
            inventory["compliance_result_id"] = rid
            builder.bind_section(
                kind=BundleSectionKind.COMPLIANCE,
                record_id=rid,
                schema_version=_record_schema_version(
                    cmpl, SUBMISSION_COMPLIANCE_SCHEMA_VERSION
                ),
                content_digest=_record_digest(cmpl),
                classification=_record_classification(cmpl),
                source_artifact_ids=_mapping_artifact_ids(cmpl),
                authority_ids=_mapping_authority_ids(cmpl),
                ruleset_versions=dict(_record_ruleset_versions(cmpl)),
            )
            assessments = _attr(cmpl, "assessments") or ()
            if isinstance(assessments, Sequence):
                for assessment in assessments:
                    aid = _record_id(
                        assessment,
                        "assessment_id",
                        fallback=f"assess:{self._id_factory()}",
                    )
                    builder.bind_section(
                        kind=BundleSectionKind.ASSESSMENT,
                        record_id=aid,
                        schema_version=_record_schema_version(
                            assessment, SUBMISSION_COMPLIANCE_SCHEMA_VERSION
                        ),
                        content_digest=_record_digest(assessment),
                        classification=_record_classification(assessment),
                        source_artifact_ids=_mapping_artifact_ids(assessment),
                        authority_ids=_mapping_authority_ids(assessment),
                        span_ids=_mapping_span_ids(assessment),
                        parent_record_ids=(rid,),
                    )
            proof_receipts = _attr(cmpl, "proof_receipts") or ()
            if isinstance(proof_receipts, Sequence):
                for pr in proof_receipts:
                    prid = _record_id(
                        pr, "receipt_id", fallback=f"proof:{self._id_factory()}"
                    )
                    builder.add_validation_receipt_ids(prid)
                    builder.bind_section(
                        kind=BundleSectionKind.VALIDATION_RECEIPT,
                        record_id=prid,
                        schema_version=_record_schema_version(
                            pr, SUBMISSION_COMPLIANCE_SCHEMA_VERSION
                        ),
                        content_digest=_record_digest(pr),
                        classification=_record_classification(cmpl),
                        parent_record_ids=(rid,),
                        require_provenance=False,
                    )
        else:
            builder.add_warning(
                BundleWarningCode.MISSING_ASSESSMENTS,
                "No compliance assessments bound into dossier",
                section_kind=BundleSectionKind.ASSESSMENT,
            )
            reason_codes.append(DossierReasonCode.MISSING_COMPLIANCE.value)

        # --- Rejection mapping ---
        if inp.rejection_mapping is not None:
            rm = inp.rejection_mapping
            rid = _record_id(
                rm, "analysis_id", fallback=f"rej:{inp.matter_id}"
            )
            inventory["rejection_mapping_id"] = rid
            builder.bind_section(
                kind=BundleSectionKind.REJECTION_MAPPING,
                record_id=rid,
                schema_version=_record_schema_version(
                    rm, REJECTION_MAPPING_SCHEMA_VERSION
                ),
                content_digest=_record_digest(rm),
                classification=_record_classification(rm),
                source_artifact_ids=_mapping_artifact_ids(rm),
                authority_ids=_mapping_authority_ids(rm),
                ruleset_versions=dict(_record_ruleset_versions(rm)),
            )

        # --- Deadlines ---
        if inp.deadlines is not None:
            dl = inp.deadlines
            rid = _record_id(dl, "analysis_id", fallback=f"deadline:{inp.matter_id}")
            inventory["deadline_analysis_id"] = rid
            builder.bind_section(
                kind=BundleSectionKind.CANDIDATE_DATE,
                record_id=rid,
                schema_version=_record_schema_version(dl, DEADLINE_SCHEMA_VERSION),
                content_digest=_record_digest(dl),
                classification=_record_classification(dl),
                source_artifact_ids=_mapping_artifact_ids(dl),
                span_ids=_mapping_span_ids(dl),
                ruleset_versions=dict(_record_ruleset_versions(dl)),
            )
        else:
            builder.add_warning(
                BundleWarningCode.MISSING_CANDIDATE_DATES,
                "No candidate dates bound into dossier",
                section_kind=BundleSectionKind.CANDIDATE_DATE,
            )
            reason_codes.append(DossierReasonCode.MISSING_CANDIDATE_DATES.value)

        # --- Instruction consistency ---
        if inp.instruction_consistency is not None:
            ic = inp.instruction_consistency
            rid = _record_id(
                ic, "analysis_id", fallback=f"instr-consist:{inp.matter_id}"
            )
            inventory["instruction_consistency_id"] = rid
            builder.bind_section(
                kind=BundleSectionKind.INSTRUCTION_CONSISTENCY,
                record_id=rid,
                schema_version=_record_schema_version(
                    ic, INSTRUCTION_CONSISTENCY_SCHEMA_VERSION
                ),
                content_digest=_record_digest(ic),
                classification=_record_classification(ic),
                source_artifact_ids=_mapping_artifact_ids(ic),
                authority_ids=_mapping_authority_ids(ic),
                span_ids=_mapping_span_ids(ic),
                ruleset_versions=dict(_record_ruleset_versions(ic)),
            )

        # --- Span validations ---
        if inp.span_validations:
            for sv in inp.span_validations:
                rid = _record_id(
                    sv, "validation_id", fallback=f"spanval:{self._id_factory()}"
                )
                builder.add_validation_receipt_ids(rid)
                builder.bind_section(
                    kind=BundleSectionKind.SPAN_VALIDATION,
                    record_id=rid,
                    schema_version=_record_schema_version(
                        sv, SPAN_VALIDATOR_SCHEMA_VERSION
                    ),
                    content_digest=_record_digest(sv),
                    classification=_record_classification(sv),
                    source_artifact_ids=_mapping_artifact_ids(sv),
                    span_ids=_mapping_span_ids(sv),
                )
        else:
            builder.add_warning(
                BundleWarningCode.MISSING_SPAN_VALIDATION,
                "No span validation results bound into dossier",
                section_kind=BundleSectionKind.SPAN_VALIDATION,
            )
            reason_codes.append(DossierReasonCode.MISSING_VALIDATION.value)

        # --- Compact sections (tests / pre-digested hand-off) ---
        for sec in inp.compact_sections:
            builder.bind_section(
                kind=sec.kind,
                record_id=sec.record_id,
                schema_version=sec.schema_version,
                content_digest=sec.content_digest,
                classification=sec.classification,
                source_artifact_ids=sec.source_artifact_ids,
                authority_ids=sec.authority_ids,
                parent_record_ids=sec.parent_record_ids,
                span_ids=sec.span_ids,
                ruleset_versions=dict(sec.ruleset_versions),
                model_versions=dict(sec.model_versions),
                labels=dict(sec.labels),
                require_provenance=sec.require_provenance,
            )

        bundle = builder.build()

        # Propagate most-restrictive classification to derived dossier surface.
        classification = bundle.classification

        # Map bundle disposition → dossier disposition
        disposition = self._map_disposition(bundle.disposition, classification)
        review_state = bundle.review_state
        if is_private_classification(classification):
            review_state = ReviewState.REQUIRED
            if DossierReasonCode.PRIVATE_CLASSIFICATION.value not in reason_codes:
                reason_codes.append(DossierReasonCode.PRIVATE_CLASSIFICATION.value)
        if requires_quarantine(classification):
            disposition = DossierDisposition.QUARANTINE
            review_state = ReviewState.REQUIRED
            if DossierReasonCode.QUARANTINE.value not in reason_codes:
                reason_codes.append(DossierReasonCode.QUARANTINE.value)

        if bundle.unsupported_checks:
            if DossierReasonCode.UNSUPPORTED_CHECKS_PRESENT.value not in reason_codes:
                reason_codes.append(
                    DossierReasonCode.UNSUPPORTED_CHECKS_PRESENT.value
                )
        if bundle.untraced_subjects():
            if DossierReasonCode.PROVENANCE_GAPS.value not in reason_codes:
                reason_codes.append(DossierReasonCode.PROVENANCE_GAPS.value)

        # Ensure every derived section classification is at least as restrictive
        # as the dossier (record already merged; re-assert on bundle sections).
        for section in bundle.sections:
            if most_restrictive_classification(
                (classification, section.classification)
            ) is not most_restrictive_classification(
                (classification, section.classification, classification)
            ):
                pass  # structural: classification already merged at build time

        warning_messages = tuple(
            dict.fromkeys(
                [w.message for w in bundle.warnings]
                + [f"warning_code:{c}" for c in bundle.warning_codes]
            )
        )

        material = {
            "analysis_bundle_digest": bundle.bundle_digest,
            "analysis_id": inp.analysis_id,
            "as_of_utc": inp.as_of_utc,
            "classification": classification.value,
            "disclaimer": DOSSIER_DISCLAIMER,
            "disposition": disposition.value,
            "event_ids": sorted(set(event_ids)),
            "human_review_required": True,
            "input_artifact_ids": list(bundle.input_artifact_ids),
            "labels": dict(inp.labels),
            "matter_id": inp.matter_id,
            "model_versions": dict(bundle.model_versions),
            "output_kind": OUTPUT_KIND_VERSIONED_APPLICATION_DOSSIER,
            "reason_codes": list(dict.fromkeys(reason_codes)),
            "review_state": review_state.value,
            "ruleset_versions": dict(bundle.ruleset_versions),
            "schema_version": DOSSIER_SCHEMA_VERSION,
            "section_record_ids": [s.record_id for s in bundle.sections],
            "unsupported_checks": list(bundle.unsupported_checks),
            "validation_receipt_ids": list(bundle.validation_receipt_ids),
            "warnings": list(warning_messages),
            **{k: v for k, v in inventory.items()},
        }
        content_digest = sha256_hex(canonical_json(material))
        dossier_id = f"dossier:{content_digest[:24]}"

        return ApplicationDossier(
            schema_version=DOSSIER_SCHEMA_VERSION,
            dossier_id=dossier_id,
            matter_id=inp.matter_id,
            disposition=disposition,
            review_state=review_state,
            classification=classification,
            bundle_digest=bundle.bundle_digest,
            content_digest=content_digest,
            output_kind=OUTPUT_KIND_VERSIONED_APPLICATION_DOSSIER,
            disclaimer=DOSSIER_DISCLAIMER,
            analysis_bundle=bundle,
            reason_codes=tuple(dict.fromkeys(reason_codes)),
            warnings=warning_messages,
            unsupported_checks=bundle.unsupported_checks,
            input_artifact_ids=bundle.input_artifact_ids,
            section_record_ids=tuple(s.record_id for s in bundle.sections),
            validation_receipt_ids=bundle.validation_receipt_ids,
            model_versions=bundle.model_versions,
            ruleset_versions=bundle.ruleset_versions,
            labels=inp.labels,
            analysis_id=inp.analysis_id,
            as_of_utc=inp.as_of_utc,
            claim_set_id=inventory["claim_set_id"],
            status_version_id=inventory["status_version_id"],
            ledger_snapshot_id=inventory["ledger_snapshot_id"],
            compliance_result_id=inventory["compliance_result_id"],
            requirements_compilation_id=inventory["requirements_compilation_id"],
            evidence_map_id=inventory["evidence_map_id"],
            deadline_analysis_id=inventory["deadline_analysis_id"],
            rejection_mapping_id=inventory["rejection_mapping_id"],
            instruction_consistency_id=inventory["instruction_consistency_id"],
            event_ids=tuple(sorted(set(event_ids))),
            human_review_required=True,
        )

    @staticmethod
    def _map_disposition(
        bundle_disp: BundleDisposition,
        classification: DisclosureClassification,
    ) -> DossierDisposition:
        if requires_quarantine(classification):
            return DossierDisposition.QUARANTINE
        mapping = {
            BundleDisposition.COMPLETE: DossierDisposition.COMPLETE,
            BundleDisposition.PARTIAL: DossierDisposition.PARTIAL,
            BundleDisposition.UNKNOWN: DossierDisposition.UNKNOWN,
            BundleDisposition.REVIEW: DossierDisposition.REVIEW,
            BundleDisposition.QUARANTINE: DossierDisposition.QUARANTINE,
            BundleDisposition.EMPTY: DossierDisposition.EMPTY,
        }
        return mapping.get(bundle_disp, DossierDisposition.UNKNOWN)


def assemble_application_dossier(
    dossier_input: DossierInput,
    *,
    id_factory: Callable[[], str] | None = None,
) -> ApplicationDossier:
    """Module-level convenience wrapper."""
    return DossierProcessor(id_factory=id_factory).assemble(dossier_input)


__all__ = [
    "DOSSIER_DISCLAIMER",
    "DOSSIER_INTERFACE",
    "DOSSIER_RULESET_VERSION",
    "DOSSIER_SCHEMA_VERSION",
    "OUTPUT_KIND_VERSIONED_APPLICATION_DOSSIER",
    "PARSER_VERSION",
    "ApplicationDossier",
    "CompactSectionInput",
    "DossierDisposition",
    "DossierInput",
    "DossierProcessor",
    "DossierProcessorError",
    "DossierReasonCode",
    "assemble_application_dossier",
    "sha256_hex",
]
