"""Stable, immutable, source-mapped diagnostics for the shared IR kernel."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Final

from .evidence import Evidence, EvidenceValidationError, validate_evidence
from .provenance import (
    Provenance,
    ProvenanceValidationError,
    _as_mapping,
    _as_sequence,
    _decode_json_object,
    _enum_value,
    _require_known,
    _string_tuple,
    _unique_tuple,
    _validate_id,
    canonical_json_bytes,
    freeze_json_mapping,
    thaw_json,
)


IR_DIAGNOSTICS_SCHEMA_VERSION: Final = "ir-diagnostics/v1"

_CODE_RE = re.compile(
    r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*){1,7}$"
)


class DiagnosticValidationError(ValueError):
    """Raised for malformed diagnostics or dangling diagnostic references."""


class DiagnosticSeverity(str, Enum):
    """Stable severity values ordered by operational impact."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    FATAL = "fatal"

    @property
    def rank(self) -> int:
        return {
            DiagnosticSeverity.INFO: 10,
            DiagnosticSeverity.WARNING: 20,
            DiagnosticSeverity.ERROR: 30,
            DiagnosticSeverity.FATAL: 40,
        }[self]


class DiagnosticCode(str, Enum):
    """Kernel-owned codes. Domains may add validated namespaced code strings."""

    DANGLING_SOURCE = "ir.provenance.dangling_source"
    DANGLING_SPAN = "ir.provenance.dangling_span"
    DANGLING_EVIDENCE = "ir.evidence.dangling_reference"
    DANGLING_PRODUCER = "ir.provenance.dangling_producer"
    DANGLING_CONFIG = "ir.provenance.dangling_config"
    UNTRACEABLE_SUBJECT = "ir.provenance.untraceable_subject"
    INVALID_SCHEMA = "ir.schema.invalid"
    UNSUPPORTED_FEATURE = "ir.feature.unsupported"
    VALIDATION_FAILED = "ir.validation.failed"


@dataclass(frozen=True, slots=True)
class DiagnosticLocation:
    """Source and semantic coordinates for one diagnostic."""

    subject_ids: tuple[str, ...] = ()
    source_ref_ids: tuple[str, ...] = ()
    span_ids: tuple[str, ...] = ()
    field_path: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "subject_ids", _unique_tuple(self.subject_ids))
        object.__setattr__(self, "source_ref_ids", _unique_tuple(self.source_ref_ids))
        object.__setattr__(self, "span_ids", _unique_tuple(self.span_ids))
        object.__setattr__(self, "metadata", freeze_json_mapping(self.metadata))

    def validate(self) -> None:
        try:
            for name, values in (
                ("subject_ids", self.subject_ids),
                ("source_ref_ids", self.source_ref_ids),
                ("span_ids", self.span_ids),
            ):
                for value in values:
                    _validate_id(f"DiagnosticLocation.{name}", value)
            if self.field_path and not self.field_path.startswith(("/", "$", ".")):
                raise ProvenanceValidationError(
                    "DiagnosticLocation.field_path must use JSON Pointer, "
                    "JSONPath, or dotted-path syntax"
                )
        except ProvenanceValidationError as exc:
            raise DiagnosticValidationError(str(exc)) from exc

    @property
    def traceable(self) -> bool:
        return bool(self.source_ref_ids or self.span_ids)

    def to_dict(self) -> dict[str, Any]:
        return {
            "field_path": self.field_path,
            "metadata": thaw_json(self.metadata),
            "source_ref_ids": list(self.source_ref_ids),
            "span_ids": list(self.span_ids),
            "subject_ids": list(self.subject_ids),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "DiagnosticLocation":
        result = cls(
            subject_ids=_string_tuple(data.get("subject_ids")),
            source_ref_ids=_string_tuple(data.get("source_ref_ids")),
            span_ids=_string_tuple(data.get("span_ids")),
            field_path=str(data.get("field_path") or ""),
            metadata=_as_mapping(data.get("metadata")),
        )
        result.validate()
        return result


@dataclass(frozen=True, slots=True)
class Diagnostic:
    """One structured, content-addressable diagnostic."""

    code: str | DiagnosticCode
    message: str
    severity: DiagnosticSeverity = DiagnosticSeverity.ERROR
    location: DiagnosticLocation = field(default_factory=DiagnosticLocation)
    evidence_ref_ids: tuple[str, ...] = ()
    producer_id: str = ""
    config_id: str = ""
    remediation: str = ""
    related_diagnostic_ids: tuple[str, ...] = ()
    diagnostic_id: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        code = self.code.value if isinstance(self.code, DiagnosticCode) else str(self.code)
        location = (
            self.location
            if isinstance(self.location, DiagnosticLocation)
            else DiagnosticLocation.from_dict(_as_mapping(self.location))
        )
        evidence_ids = _unique_tuple(self.evidence_ref_ids)
        related_ids = _unique_tuple(self.related_diagnostic_ids)
        metadata = freeze_json_mapping(self.metadata)
        object.__setattr__(self, "code", code)
        object.__setattr__(self, "location", location)
        object.__setattr__(self, "evidence_ref_ids", evidence_ids)
        object.__setattr__(self, "related_diagnostic_ids", related_ids)
        object.__setattr__(self, "metadata", metadata)
        if not self.diagnostic_id:
            identity_payload = {
                "code": code,
                "config_id": self.config_id,
                "evidence_ref_ids": list(evidence_ids),
                "location": location.to_dict(),
                "message": self.message,
                "producer_id": self.producer_id,
                "severity": (
                    self.severity.value
                    if isinstance(self.severity, DiagnosticSeverity)
                    else str(self.severity)
                ),
            }
            digest = hashlib.sha256(canonical_json_bytes(identity_payload)).hexdigest()
            object.__setattr__(self, "diagnostic_id", f"diagnostic:{digest[:32]}")

    def validate(self) -> None:
        try:
            _validate_id("Diagnostic.diagnostic_id", self.diagnostic_id)
            if not isinstance(self.code, str) or not _CODE_RE.fullmatch(self.code):
                raise ProvenanceValidationError(
                    "Diagnostic.code must be a stable lowercase namespaced code"
                )
            if not isinstance(self.severity, DiagnosticSeverity):
                raise ProvenanceValidationError(
                    "Diagnostic.severity must be a DiagnosticSeverity member"
                )
            if not isinstance(self.message, str) or not self.message.strip():
                raise ProvenanceValidationError(
                    "Diagnostic.message must not be empty"
                )
            self.location.validate()
            for value in (*self.evidence_ref_ids, *self.related_diagnostic_ids):
                _validate_id("Diagnostic reference", value)
            if self.producer_id:
                _validate_id("Diagnostic.producer_id", self.producer_id)
            if self.config_id:
                _validate_id("Diagnostic.config_id", self.config_id)
            if self.config_id and not self.producer_id:
                raise ProvenanceValidationError(
                    "Diagnostic config_id requires producer_id"
                )
        except ProvenanceValidationError as exc:
            raise DiagnosticValidationError(str(exc)) from exc

    @property
    def is_error(self) -> bool:
        return self.severity in {
            DiagnosticSeverity.ERROR,
            DiagnosticSeverity.FATAL,
        }

    @property
    def error(self) -> bool:
        """Legal IR-compatible spelling for error/fatal classification."""

        return self.is_error

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "config_id": self.config_id,
            "diagnostic_id": self.diagnostic_id,
            "evidence_ref_ids": list(self.evidence_ref_ids),
            "location": self.location.to_dict(),
            "message": self.message,
            "metadata": thaw_json(self.metadata),
            "producer_id": self.producer_id,
            "related_diagnostic_ids": list(self.related_diagnostic_ids),
            "remediation": self.remediation,
            "severity": self.severity.value,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Diagnostic":
        try:
            severity = _enum_value(
                DiagnosticSeverity,
                data.get("severity"),
                "Diagnostic.severity",
            )
        except ProvenanceValidationError as exc:
            raise DiagnosticValidationError(str(exc)) from exc
        result = cls(
            code=str(data.get("code") or ""),
            message=str(data.get("message") or ""),
            severity=severity,
            location=DiagnosticLocation.from_dict(
                _as_mapping(data.get("location"))
            ),
            evidence_ref_ids=_string_tuple(data.get("evidence_ref_ids")),
            producer_id=str(data.get("producer_id") or ""),
            config_id=str(data.get("config_id") or ""),
            remediation=str(data.get("remediation") or ""),
            related_diagnostic_ids=_string_tuple(
                data.get("related_diagnostic_ids")
            ),
            diagnostic_id=str(data.get("diagnostic_id") or ""),
            metadata=_as_mapping(data.get("metadata")),
        )
        result.validate()
        return result


@dataclass(frozen=True, slots=True)
class DiagnosticReport:
    """Canonical diagnostic batch bound to provenance and evidence registries."""

    report_id: str
    diagnostics: tuple[Diagnostic, ...]
    provenance_id: str = ""
    evidence_set_id: str = ""
    producer_id: str = ""
    config_id: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = IR_DIAGNOSTICS_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "diagnostics",
            tuple(
                item
                if isinstance(item, Diagnostic)
                else Diagnostic.from_dict(_as_mapping(item))
                for item in self.diagnostics
            ),
        )
        object.__setattr__(self, "metadata", freeze_json_mapping(self.metadata))

    @property
    def error_count(self) -> int:
        return sum(item.is_error for item in self.diagnostics)

    @property
    def warning_count(self) -> int:
        return sum(
            item.severity is DiagnosticSeverity.WARNING for item in self.diagnostics
        )

    @property
    def valid(self) -> bool:
        return self.error_count == 0

    def validate(
        self,
        *,
        provenance: Provenance | None = None,
        evidence: Evidence | None = None,
    ) -> None:
        validate_diagnostics(self, provenance=provenance, evidence=evidence)

    def to_dict(self) -> dict[str, Any]:
        return {
            "config_id": self.config_id,
            "diagnostics": [
                item.to_dict()
                for item in sorted(
                    self.diagnostics, key=lambda item: item.diagnostic_id
                )
            ],
            "error_count": self.error_count,
            "evidence_set_id": self.evidence_set_id,
            "metadata": thaw_json(self.metadata),
            "producer_id": self.producer_id,
            "provenance_id": self.provenance_id,
            "report_id": self.report_id,
            "schema_version": self.schema_version,
            "valid": self.valid,
            "warning_count": self.warning_count,
        }

    def canonical_bytes(self) -> bytes:
        self.validate()
        return canonical_json_bytes(self.to_dict())

    def to_json(self) -> str:
        return self.canonical_bytes().decode("utf-8")

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_bytes()).hexdigest()

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "DiagnosticReport":
        try:
            result = cls(
                report_id=str(data.get("report_id") or ""),
                diagnostics=tuple(
                    Diagnostic.from_dict(_as_mapping(item))
                    for item in _as_sequence(data.get("diagnostics"))
                ),
                provenance_id=str(data.get("provenance_id") or ""),
                evidence_set_id=str(data.get("evidence_set_id") or ""),
                producer_id=str(data.get("producer_id") or ""),
                config_id=str(data.get("config_id") or ""),
                metadata=_as_mapping(data.get("metadata")),
                schema_version=str(
                    data.get("schema_version") or IR_DIAGNOSTICS_SCHEMA_VERSION
                ),
            )
        except ProvenanceValidationError as exc:
            raise DiagnosticValidationError(str(exc)) from exc
        result.validate()
        return result

    @classmethod
    def from_json(cls, value: str | bytes | bytearray) -> "DiagnosticReport":
        try:
            data = _decode_json_object(value, "diagnostic report")
        except ProvenanceValidationError as exc:
            raise DiagnosticValidationError(str(exc)) from exc
        return cls.from_dict(data)


def validate_diagnostics(
    report: DiagnosticReport,
    *,
    provenance: Provenance | None = None,
    evidence: Evidence | None = None,
) -> DiagnosticReport:
    """Validate report structure and all supplied registry references."""

    if not isinstance(report, DiagnosticReport):
        raise DiagnosticValidationError(
            "report must be a DiagnosticReport instance"
        )
    try:
        if report.schema_version != IR_DIAGNOSTICS_SCHEMA_VERSION:
            raise ProvenanceValidationError(
                f"Unsupported diagnostic schema_version {report.schema_version!r}"
            )
        _validate_id("DiagnosticReport.report_id", report.report_id)
        ids: set[str] = set()
        for diagnostic in report.diagnostics:
            diagnostic.validate()
            if diagnostic.diagnostic_id in ids:
                raise ProvenanceValidationError(
                    f"duplicate diagnostic id {diagnostic.diagnostic_id!r}"
                )
            ids.add(diagnostic.diagnostic_id)
        for diagnostic in report.diagnostics:
            _require_known(
                diagnostic.related_diagnostic_ids,
                ids,
                f"Diagnostic {diagnostic.diagnostic_id!r}.related_diagnostic_ids",
            )
            if diagnostic.diagnostic_id in diagnostic.related_diagnostic_ids:
                raise ProvenanceValidationError(
                    f"Diagnostic {diagnostic.diagnostic_id!r} relates to itself"
                )

        evidence_ids: set[str] | None = None
        if evidence is not None:
            validate_evidence(evidence, provenance=provenance)
            evidence_ids = {item.evidence_id for item in evidence.references}
            if report.evidence_set_id != evidence.evidence_set_id:
                raise ProvenanceValidationError(
                    "DiagnosticReport.evidence_set_id does not match evidence"
                )
        elif report.evidence_set_id:
            evidence_ids = None

        if provenance is not None:
            provenance.validate(
                evidence_ref_ids=tuple(evidence_ids)
                if evidence_ids is not None
                else None
            )
            if report.provenance_id != provenance.provenance_id:
                raise ProvenanceValidationError(
                    "DiagnosticReport.provenance_id does not match provenance"
                )
            source_ids = {item.ref_id for item in provenance.sources}
            spans = {item.span_id: item for item in provenance.spans}
            subject_ids = {item.subject_id for item in provenance.bindings}
            producer_ids = {item.producer_id for item in provenance.producers}
            config_ids = {item.config_id for item in provenance.configs}
            if report.producer_id:
                _require_known(
                    (report.producer_id,),
                    producer_ids,
                    "DiagnosticReport.producer_id",
                )
            if report.config_id:
                _require_known(
                    (report.config_id,),
                    config_ids,
                    "DiagnosticReport.config_id",
                )
            if report.config_id and not report.producer_id:
                raise ProvenanceValidationError(
                    "DiagnosticReport config_id requires producer_id"
                )
            for diagnostic in report.diagnostics:
                location = diagnostic.location
                _require_known(
                    location.source_ref_ids,
                    source_ids,
                    f"Diagnostic {diagnostic.diagnostic_id!r}.source_ref_ids",
                )
                _require_known(
                    location.span_ids,
                    set(spans),
                    f"Diagnostic {diagnostic.diagnostic_id!r}.span_ids",
                )
                _require_known(
                    location.subject_ids,
                    subject_ids,
                    f"Diagnostic {diagnostic.diagnostic_id!r}.subject_ids",
                )
                for span_id in location.span_ids:
                    source_id = spans[span_id].source_ref_id
                    if location.source_ref_ids and source_id not in location.source_ref_ids:
                        raise ProvenanceValidationError(
                            f"Diagnostic {diagnostic.diagnostic_id!r} span "
                            f"{span_id!r} belongs to unlisted source {source_id!r}"
                        )
                if diagnostic.producer_id:
                    _require_known(
                        (diagnostic.producer_id,),
                        producer_ids,
                        f"Diagnostic {diagnostic.diagnostic_id!r}.producer_id",
                    )
                if diagnostic.config_id:
                    _require_known(
                        (diagnostic.config_id,),
                        config_ids,
                        f"Diagnostic {diagnostic.diagnostic_id!r}.config_id",
                    )
        if evidence_ids is not None:
            for diagnostic in report.diagnostics:
                _require_known(
                    diagnostic.evidence_ref_ids,
                    evidence_ids,
                    f"Diagnostic {diagnostic.diagnostic_id!r}.evidence_ref_ids",
                )
    except (ProvenanceValidationError, EvidenceValidationError) as exc:
        raise DiagnosticValidationError(str(exc)) from exc
    return report


def canonical_diagnostics_bytes(report: DiagnosticReport) -> bytes:
    return report.canonical_bytes()


def canonical_diagnostics_json(report: DiagnosticReport) -> str:
    return report.to_json()


def diagnostics_sha256(report: DiagnosticReport) -> str:
    return report.sha256


def validate_cross_references(
    provenance: Provenance,
    evidence: Evidence,
    diagnostics: DiagnosticReport,
) -> tuple[Provenance, Evidence, DiagnosticReport]:
    """Validate the complete provenance/evidence/diagnostic reference graph."""

    diagnostics.validate(provenance=provenance, evidence=evidence)
    return provenance, evidence, diagnostics


validate_ir_references = validate_cross_references


IRDiagnostic = Diagnostic
IRDiagnosticReport = DiagnosticReport
IRDiagnostics = DiagnosticReport


__all__ = [
    "Diagnostic",
    "DiagnosticCode",
    "DiagnosticLocation",
    "DiagnosticReport",
    "DiagnosticSeverity",
    "DiagnosticValidationError",
    "IRDiagnostic",
    "IRDiagnosticReport",
    "IRDiagnostics",
    "IR_DIAGNOSTICS_SCHEMA_VERSION",
    "canonical_diagnostics_bytes",
    "canonical_diagnostics_json",
    "diagnostics_sha256",
    "validate_cross_references",
    "validate_diagnostics",
    "validate_ir_references",
]
