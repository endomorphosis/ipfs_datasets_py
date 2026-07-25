"""Stable, source-mapped diagnostics for the shared IR kernel."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Final

from .evidence import EvidenceCollection, validate_cross_references as validate_evidence
from .provenance import (
    CrossReferenceIssue,
    CrossReferenceValidation,
    ProvenanceBundle,
    canonical_json_bytes,
    canonical_sha256,
    freeze_json,
    thaw_json,
    validate_cross_references as validate_provenance,
)


IR_DIAGNOSTICS_SCHEMA_VERSION: Final = "ir-diagnostics/v1"
_CODE_RE = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z0-9_]+)+$")


class DiagnosticValidationError(ValueError):
    """Raised when a diagnostic or its references violate the contract."""


class DiagnosticSeverity(str, Enum):
    """Stable severity levels.  Errors and fatals make a report unsuccessful."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    FATAL = "fatal"


class CoreDiagnosticCode(str, Enum):
    """Codes emitted by shared cross-reference validators."""

    DUPLICATE_REFERENCE = "ir.reference.duplicate"
    SOURCE_REFERENCE_MISSING = "ir.provenance.source_reference.missing"
    SPAN_MISSING = "ir.provenance.span.missing"
    SPAN_SOURCE_UNBOUND = "ir.provenance.span.source_unbound"
    SPAN_OUT_OF_BOUNDS = "ir.provenance.span.out_of_bounds"
    PARENT_SUBJECT_MISSING = "ir.provenance.parent_subject.missing"
    PARENT_SUBJECT_CYCLE = "ir.provenance.parent_subject.cycle"
    PRODUCER_MISSING = "ir.provenance.producer.missing"
    CONFIGURATION_MISSING = "ir.provenance.configuration.missing"
    EVIDENCE_PARENT_MISSING = "ir.evidence.parent.missing"
    EVIDENCE_PARENT_CYCLE = "ir.evidence.parent.cycle"
    EVIDENCE_SOURCE_MISSING = "ir.evidence.source_reference.missing"
    EVIDENCE_SPAN_MISSING = "ir.evidence.span.missing"
    EVIDENCE_SPAN_SOURCE_UNBOUND = "ir.evidence.span.source_unbound"
    EVIDENCE_SUBJECT_MISSING = "ir.evidence.subject.missing"
    EVIDENCE_PRODUCER_MISSING = "ir.evidence.producer.missing"
    EVIDENCE_CONFIGURATION_MISSING = "ir.evidence.configuration.missing"
    EVIDENCE_MISSING = "ir.diagnostic.evidence.missing"
    DIAGNOSTIC_SOURCE_MISSING = "ir.diagnostic.source_reference.missing"
    DIAGNOSTIC_SPAN_MISSING = "ir.diagnostic.span.missing"
    DIAGNOSTIC_SPAN_SOURCE_UNBOUND = "ir.diagnostic.span.source_unbound"
    DIAGNOSTIC_SUBJECT_MISSING = "ir.diagnostic.subject.missing"
    DIAGNOSTIC_PRODUCER_MISSING = "ir.diagnostic.producer.missing"
    DIAGNOSTIC_CONFIGURATION_MISSING = "ir.diagnostic.configuration.missing"
    DIAGNOSTIC_CONTENT_ID_MISMATCH = "ir.diagnostic.content_id.mismatch"


@dataclass(frozen=True, slots=True)
class Diagnostic:
    """One immutable machine-readable finding with optional source/evidence links."""

    code: str | CoreDiagnosticCode
    message: str
    severity: DiagnosticSeverity = DiagnosticSeverity.ERROR
    diagnostic_id: str = ""
    subject_id: str = ""
    field_path: str = ""
    source_reference_ids: tuple[str, ...] = ()
    source_span_ids: tuple[str, ...] = ()
    evidence_reference_ids: tuple[str, ...] = ()
    producer_id: str = ""
    configuration_id: str = ""
    remediation: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = IR_DIAGNOSTICS_SCHEMA_VERSION

    def __post_init__(self) -> None:
        code = self.code.value if isinstance(self.code, CoreDiagnosticCode) else str(self.code)
        if not _CODE_RE.fullmatch(code):
            raise DiagnosticValidationError(
                "Diagnostic.code must be a stable lowercase namespaced code"
            )
        if not isinstance(self.message, str) or not self.message.strip():
            raise DiagnosticValidationError("Diagnostic.message must not be empty")
        object.__setattr__(self, "code", code)
        object.__setattr__(self, "severity", _severity(self.severity))
        for name in (
            "source_reference_ids",
            "source_span_ids",
            "evidence_reference_ids",
        ):
            object.__setattr__(
                self,
                name,
                _identifier_tuple(f"Diagnostic.{name}", getattr(self, name)),
            )
        for name in ("subject_id", "producer_id", "configuration_id"):
            value = getattr(self, name)
            if value:
                _require_identifier(f"Diagnostic.{name}", value)
        object.__setattr__(self, "metadata", freeze_json(self.metadata))
        expected = self.expected_diagnostic_id
        if self.diagnostic_id:
            _require_identifier("Diagnostic.diagnostic_id", self.diagnostic_id)
        else:
            object.__setattr__(self, "diagnostic_id", expected)

    @property
    def error(self) -> bool:
        return self.severity in {
            DiagnosticSeverity.ERROR,
            DiagnosticSeverity.FATAL,
        }

    @property
    def content_sha256(self) -> str:
        return canonical_sha256(self.identity_dict())

    @property
    def expected_diagnostic_id(self) -> str:
        return "diagnostic:sha256:" + self.content_sha256

    @property
    def content_address_valid(self) -> bool:
        return (
            not self.diagnostic_id.startswith("diagnostic:sha256:")
            or self.diagnostic_id == self.expected_diagnostic_id
        )

    def identity_dict(self) -> dict[str, Any]:
        """Return content that determines the default diagnostic identifier."""

        return {
            "code": self.code,
            "configuration_id": self.configuration_id,
            "evidence_reference_ids": list(self.evidence_reference_ids),
            "field_path": self.field_path,
            "message": self.message,
            "metadata": thaw_json(self.metadata),
            "producer_id": self.producer_id,
            "remediation": self.remediation,
            "schema_version": self.schema_version,
            "severity": self.severity.value,
            "source_reference_ids": list(self.source_reference_ids),
            "source_span_ids": list(self.source_span_ids),
            "subject_id": self.subject_id,
        }

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "configuration_id": self.configuration_id,
            "diagnostic_id": self.diagnostic_id,
            "evidence_reference_ids": list(self.evidence_reference_ids),
            "field_path": self.field_path,
            "message": self.message,
            "metadata": thaw_json(self.metadata),
            "producer_id": self.producer_id,
            "remediation": self.remediation,
            "schema_version": self.schema_version,
            "severity": self.severity.value,
            "source_reference_ids": list(self.source_reference_ids),
            "source_span_ids": list(self.source_span_ids),
            "subject_id": self.subject_id,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Diagnostic":
        return cls(
            code=str(data.get("code") or ""),
            message=str(data.get("message") or ""),
            severity=data.get("severity") or DiagnosticSeverity.ERROR,
            diagnostic_id=str(data.get("diagnostic_id") or ""),
            subject_id=str(data.get("subject_id") or ""),
            field_path=str(data.get("field_path") or ""),
            source_reference_ids=_strings(data.get("source_reference_ids")),
            source_span_ids=_strings(
                data.get("source_span_ids", data.get("span_ids"))
            ),
            evidence_reference_ids=_strings(
                data.get("evidence_reference_ids", data.get("evidence_ids"))
            ),
            producer_id=str(data.get("producer_id") or ""),
            configuration_id=str(
                data.get("configuration_id") or data.get("config_id") or ""
            ),
            remediation=str(
                data.get("remediation") or data.get("remediation_hint") or ""
            ),
            metadata=_mapping(data.get("metadata")),
            schema_version=str(
                data.get("schema_version") or IR_DIAGNOSTICS_SCHEMA_VERSION
            ),
        )


@dataclass(frozen=True, slots=True)
class DiagnosticReport:
    """Canonical collection of diagnostics with deterministic summary properties."""

    diagnostics: tuple[Diagnostic, ...] = ()
    report_id: str = ""
    artifact_id: str = ""
    provenance_bundle_id: str = ""
    evidence_collection_id: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = IR_DIAGNOSTICS_SCHEMA_VERSION

    def __post_init__(self) -> None:
        converted = tuple(
            item
            if isinstance(item, Diagnostic)
            else Diagnostic.from_dict(_mapping(item))
            for item in self.diagnostics
        )
        object.__setattr__(
            self,
            "diagnostics",
            tuple(sorted(converted, key=lambda item: item.diagnostic_id)),
        )
        for name in (
            "report_id",
            "artifact_id",
            "provenance_bundle_id",
            "evidence_collection_id",
        ):
            value = getattr(self, name)
            if value:
                _require_identifier(f"DiagnosticReport.{name}", value)
        object.__setattr__(self, "metadata", freeze_json(self.metadata))
        if not self.report_id:
            object.__setattr__(
                self,
                "report_id",
                "diagnostic-report:sha256:"
                + canonical_sha256(self.identity_dict()),
            )

    @property
    def diagnostic_by_id(self) -> Mapping[str, Diagnostic]:
        return MappingProxyType(
            {item.diagnostic_id: item for item in self.diagnostics}
        )

    @property
    def error_count(self) -> int:
        return sum(item.error for item in self.diagnostics)

    @property
    def warning_count(self) -> int:
        return sum(
            item.severity is DiagnosticSeverity.WARNING
            for item in self.diagnostics
        )

    @property
    def info_count(self) -> int:
        return sum(
            item.severity is DiagnosticSeverity.INFO
            for item in self.diagnostics
        )

    @property
    def valid(self) -> bool:
        return self.error_count == 0

    @property
    def content_sha256(self) -> str:
        return canonical_sha256(self.to_dict())

    def identity_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "diagnostics": [item.to_dict() for item in self.diagnostics],
            "evidence_collection_id": self.evidence_collection_id,
            "metadata": thaw_json(self.metadata),
            "provenance_bundle_id": self.provenance_bundle_id,
            "schema_version": self.schema_version,
        }

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())

    def validate_cross_references(
        self,
        provenance: ProvenanceBundle | Mapping[str, Any] | None = None,
        evidence: EvidenceCollection | Mapping[str, Any] | None = None,
    ) -> CrossReferenceValidation:
        return validate_cross_references(self, provenance, evidence)

    def assert_valid_references(
        self,
        provenance: ProvenanceBundle | Mapping[str, Any] | None = None,
        evidence: EvidenceCollection | Mapping[str, Any] | None = None,
    ) -> None:
        result = self.validate_cross_references(provenance, evidence)
        if not result.valid:
            summary = "; ".join(
                f"{item.code} at {item.field_path}: {item.message}"
                for item in result.issues
                if item.severity == "error"
            )
            raise DiagnosticValidationError(summary)

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "diagnostics": [item.to_dict() for item in self.diagnostics],
            "error_count": self.error_count,
            "evidence_collection_id": self.evidence_collection_id,
            "info_count": self.info_count,
            "metadata": thaw_json(self.metadata),
            "provenance_bundle_id": self.provenance_bundle_id,
            "report_id": self.report_id,
            "schema_version": self.schema_version,
            "valid": self.valid,
            "warning_count": self.warning_count,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "DiagnosticReport":
        return cls(
            diagnostics=tuple(
                Diagnostic.from_dict(_mapping(item))
                for item in _sequence(data.get("diagnostics"))
            ),
            report_id=str(data.get("report_id") or ""),
            artifact_id=str(data.get("artifact_id") or ""),
            provenance_bundle_id=str(
                data.get("provenance_bundle_id") or ""
            ),
            evidence_collection_id=str(
                data.get("evidence_collection_id") or ""
            ),
            metadata=_mapping(data.get("metadata")),
            schema_version=str(
                data.get("schema_version") or IR_DIAGNOSTICS_SCHEMA_VERSION
            ),
        )


def validate_cross_references(
    report: DiagnosticReport | Mapping[str, Any],
    provenance: ProvenanceBundle | Mapping[str, Any] | None = None,
    evidence: EvidenceCollection | Mapping[str, Any] | None = None,
) -> CrossReferenceValidation:
    """Validate a full provenance/evidence/diagnostic reference graph."""

    diagnostic_report = (
        report
        if isinstance(report, DiagnosticReport)
        else DiagnosticReport.from_dict(report)
    )
    provenance_bundle = (
        provenance
        if isinstance(provenance, ProvenanceBundle)
        else ProvenanceBundle.from_dict(provenance)
        if provenance is not None
        else None
    )
    evidence_collection = (
        evidence
        if isinstance(evidence, EvidenceCollection)
        else EvidenceCollection.from_dict(evidence)
        if evidence is not None
        else None
    )
    issues: list[CrossReferenceIssue] = []
    if provenance_bundle is not None:
        issues.extend(validate_provenance(provenance_bundle).issues)
    if evidence_collection is not None:
        issues.extend(
            validate_evidence(evidence_collection, provenance_bundle).issues
        )

    diagnostic_ids: set[str] = set()
    for index, diagnostic in enumerate(diagnostic_report.diagnostics):
        if diagnostic.diagnostic_id in diagnostic_ids:
            issues.append(
                _issue(
                    CoreDiagnosticCode.DUPLICATE_REFERENCE,
                    f"duplicate identifier {diagnostic.diagnostic_id!r}",
                    f"diagnostics.{index}.diagnostic_id",
                    diagnostic.diagnostic_id,
                )
            )
        diagnostic_ids.add(diagnostic.diagnostic_id)
        if not diagnostic.content_address_valid:
            issues.append(
                _issue(
                    CoreDiagnosticCode.DIAGNOSTIC_CONTENT_ID_MISMATCH,
                    "content-addressed diagnostic_id does not match content",
                    f"diagnostics.{index}.diagnostic_id",
                    diagnostic.diagnostic_id,
                )
            )

    if provenance_bundle is not None:
        sources = {
            item.reference_id for item in provenance_bundle.sources
        }
        spans = {item.span_id: item for item in provenance_bundle.spans}
        subjects = {
            item.subject_id for item in provenance_bundle.bindings
        }
        producers = {
            item.producer_id for item in provenance_bundle.producers
        }
        configurations = {
            item.configuration_id for item in provenance_bundle.configurations
        }
        for index, diagnostic in enumerate(diagnostic_report.diagnostics):
            for offset, reference_id in enumerate(
                diagnostic.source_reference_ids
            ):
                _check_reference(
                    reference_id,
                    sources,
                    CoreDiagnosticCode.DIAGNOSTIC_SOURCE_MISSING,
                    f"diagnostics.{index}.source_reference_ids.{offset}",
                    issues,
                )
            for offset, span_id in enumerate(diagnostic.source_span_ids):
                _check_reference(
                    span_id,
                    set(spans),
                    CoreDiagnosticCode.DIAGNOSTIC_SPAN_MISSING,
                    f"diagnostics.{index}.source_span_ids.{offset}",
                    issues,
                )
                span = spans.get(span_id)
                if (
                    span is not None
                    and span.source_reference_id
                    not in diagnostic.source_reference_ids
                ):
                    issues.append(
                        _issue(
                            "ir.diagnostic.span.source_unbound",
                            (
                                f"span {span_id!r} belongs to source "
                                f"{span.source_reference_id!r}, which is not "
                                "bound to the diagnostic"
                            ),
                            f"diagnostics.{index}.source_span_ids.{offset}",
                            span_id,
                        )
                    )
            if diagnostic.subject_id:
                _check_reference(
                    diagnostic.subject_id,
                    subjects,
                    CoreDiagnosticCode.DIAGNOSTIC_SUBJECT_MISSING,
                    f"diagnostics.{index}.subject_id",
                    issues,
                )
            if diagnostic.producer_id:
                _check_reference(
                    diagnostic.producer_id,
                    producers,
                    CoreDiagnosticCode.DIAGNOSTIC_PRODUCER_MISSING,
                    f"diagnostics.{index}.producer_id",
                    issues,
                )
            if diagnostic.configuration_id:
                _check_reference(
                    diagnostic.configuration_id,
                    configurations,
                    CoreDiagnosticCode.DIAGNOSTIC_CONFIGURATION_MISSING,
                    f"diagnostics.{index}.configuration_id",
                    issues,
                )

    if evidence_collection is not None:
        evidence_ids = {
            item.evidence_id for item in evidence_collection.evidence
        }
        for index, diagnostic in enumerate(diagnostic_report.diagnostics):
            for offset, evidence_id in enumerate(
                diagnostic.evidence_reference_ids
            ):
                _check_reference(
                    evidence_id,
                    evidence_ids,
                    CoreDiagnosticCode.EVIDENCE_MISSING,
                    f"diagnostics.{index}.evidence_reference_ids.{offset}",
                    issues,
                )

    return CrossReferenceValidation(tuple(_sorted_issues(issues)))


def diagnostics_from_validation(
    validation: CrossReferenceValidation,
) -> tuple[Diagnostic, ...]:
    """Convert validator issues to structured diagnostics without losing severity."""

    return tuple(
        Diagnostic(
            code=issue.code,
            message=issue.message,
            severity=issue.severity,
            field_path=issue.field_path,
            metadata=(
                {"reference_id": issue.reference_id}
                if issue.reference_id
                else {}
            ),
        )
        for issue in validation.issues
    )


def build_diagnostic_report(
    diagnostics: Iterable[Diagnostic | Mapping[str, Any]],
    **kwargs: Any,
) -> DiagnosticReport:
    """Convenience constructor that defensively materializes an iterable."""

    return DiagnosticReport(diagnostics=tuple(diagnostics), **kwargs)


def _check_reference(
    identifier: str,
    known: set[str],
    code: str | CoreDiagnosticCode,
    field_path: str,
    issues: list[CrossReferenceIssue],
) -> None:
    if identifier not in known:
        issues.append(
            _issue(
                code,
                f"reference {identifier!r} does not exist",
                field_path,
                identifier,
            )
        )


def _issue(
    code: str | CoreDiagnosticCode,
    message: str,
    field_path: str,
    reference_id: str = "",
) -> CrossReferenceIssue:
    return CrossReferenceIssue(
        code=code.value if isinstance(code, CoreDiagnosticCode) else code,
        message=message,
        field_path=field_path,
        reference_id=reference_id,
    )


def _sorted_issues(
    issues: Sequence[CrossReferenceIssue],
) -> tuple[CrossReferenceIssue, ...]:
    return tuple(
        sorted(
            issues,
            key=lambda item: (
                item.field_path,
                item.code,
                item.reference_id,
                item.message,
            ),
        )
    )


def _severity(value: Any) -> DiagnosticSeverity:
    if isinstance(value, DiagnosticSeverity):
        return value
    try:
        return DiagnosticSeverity(str(value))
    except ValueError as exc:
        raise DiagnosticValidationError(
            f"invalid diagnostic severity {value!r}"
        ) from exc


def _require_identifier(name: str, value: Any) -> None:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 512
        or not value[0].isalnum()
        or any(
            not (character.isalnum() or character in "._:/@+-")
            for character in value
        )
    ):
        raise DiagnosticValidationError(f"{name} must be a stable identifier")


def _identifier_tuple(name: str, value: Any) -> tuple[str, ...]:
    result = tuple(sorted(set(_strings(value))))
    for identifier in result:
        _require_identifier(name, identifier)
    return result


def _strings(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,) if value else ()
    if isinstance(value, Sequence):
        return tuple(str(item) for item in value if str(item))
    raise DiagnosticValidationError("identifier collection must be a sequence")


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _sequence(value: Any) -> Sequence[Any]:
    if isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        return value
    return ()


# Compatibility-friendly descriptive aliases for downstream domain adapters.
IRDiagnostic = Diagnostic
IRDiagnosticReport = DiagnosticReport
validate_ir_references = validate_cross_references
