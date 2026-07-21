"""Structured LegalIR diagnostics and explanation traces.

Compiler failures must be actionable without scraping prose from individual
passes.  This module normalizes domain-local LegalIR findings into one
diagnostic envelope with stable codes, severity, family, source-map
coordinates, remediation hints, and a compact explanation trace.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Final

from .legal_ir_source_maps import (
    LegalIRSourceMap,
    LegalIRSourceMapBuilder,
    LegalIRTransformationKind,
    trace_legal_ir_fact,
)


LEGAL_IR_DIAGNOSTICS_SCHEMA_VERSION: Final = "legal-ir-diagnostics-v1"


class LegalIRDiagnosticSeverity(str, Enum):
    """Stable severity levels for compiler UX consumers."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    FATAL = "fatal"


class LegalIRDiagnosticFamily(str, Enum):
    """Top-level compiler UX families used for filtering and routing."""

    SYMBOL = "symbol"
    CITATION = "citation"
    AMBIGUITY = "ambiguity"
    TEMPORAL_AUTHORITY = "temporal_authority"
    UNSUPPORTED_BACKEND_FEATURE = "unsupported_backend_feature"
    PROOF_FAILURE = "proof_failure"
    LEARNED_GUIDANCE_ABSTENTION = "learned_guidance_abstention"
    POISONING_REJECTION = "poisoning_rejection"
    DECOMPILER_LOSS = "decompiler_loss"
    CODEX_REPAIR_ATTRIBUTION = "codex_repair_attribution"
    SOURCE_MAP = "source_map"
    COMPILER = "compiler"


class LegalIRDiagnosticCode(str, Enum):
    """Machine-readable diagnostic codes emitted by this module."""

    UNRESOLVED_SYMBOL = "legal_ir.symbol.unresolved"
    AMBIGUOUS_SYMBOL = "legal_ir.symbol.ambiguous"
    UNRESOLVED_CITATION = "legal_ir.citation.unresolved"
    AMBIGUOUS_CITATION = "legal_ir.citation.ambiguous"
    REPEALED_CITATION = "legal_ir.citation.repealed"
    AMBIGUITY_UNRESOLVED = "legal_ir.ambiguity.unresolved"
    TEMPORAL_AUTHORITY_INVALID = "legal_ir.temporal_authority.invalid"
    UNSUPPORTED_BACKEND_FEATURE = "legal_ir.backend.unsupported_feature"
    PROOF_FAILURE = "legal_ir.proof.failure"
    LEARNED_GUIDANCE_ABSTENTION = "legal_ir.learned_guidance.abstention"
    POISONING_REJECTION = "legal_ir.security.poisoning_rejection"
    DECOMPILER_LOSS = "legal_ir.decompiler.loss"
    CODEX_REPAIR_ATTRIBUTION = "legal_ir.codex.repair_attribution"
    SOURCE_MAP_UNTRACEABLE = "legal_ir.source_map.untraceable"
    COMPILER_DIAGNOSTIC = "legal_ir.compiler.diagnostic"


_REMEDIATION_HINTS: Final[Mapping[str, str]] = {
    LegalIRDiagnosticCode.UNRESOLVED_SYMBOL.value: (
        "Add a scoped definition or alias for the referenced legal symbol, then rerun symbol resolution."
    ),
    LegalIRDiagnosticCode.AMBIGUOUS_SYMBOL.value: (
        "Qualify the reference with a narrower scope, document, or explicit target symbol."
    ),
    LegalIRDiagnosticCode.UNRESOLVED_CITATION.value: (
        "Add the cited authority/version to the citation graph or correct the citation text."
    ),
    LegalIRDiagnosticCode.AMBIGUOUS_CITATION.value: (
        "Bind the citation to one canonical target or include enough authority/version context to disambiguate it."
    ),
    LegalIRDiagnosticCode.REPEALED_CITATION.value: (
        "Use the effective replacement authority or mark the obsolete citation as historical-only."
    ),
    LegalIRDiagnosticCode.AMBIGUITY_UNRESOLVED.value: (
        "Retain competing interpretations and choose a deterministic policy or human-reviewed resolution before proof use."
    ),
    LegalIRDiagnosticCode.TEMPORAL_AUTHORITY_INVALID.value: (
        "Set the query date, jurisdiction, and authority version so only applicable law reaches proof targets."
    ),
    LegalIRDiagnosticCode.UNSUPPORTED_BACKEND_FEATURE.value: (
        "Either implement the backend feature, route the obligation to a capable backend, or add an explicit waiver."
    ),
    LegalIRDiagnosticCode.PROOF_FAILURE.value: (
        "Inspect the proof receipt, selected premises, and reconstruction errors before trusting the artifact."
    ),
    LegalIRDiagnosticCode.LEARNED_GUIDANCE_ABSTENTION.value: (
        "Keep deterministic compiler defaults and collect fixed-canary evidence before promoting learned guidance."
    ),
    LegalIRDiagnosticCode.POISONING_REJECTION.value: (
        "Treat source/model text as data only, remove the rejected payload, and rescan before using it for proof or training."
    ),
    LegalIRDiagnosticCode.DECOMPILER_LOSS.value: (
        "Preserve the reported field in the decompiler projection or mark the lossy projection as non-authoritative."
    ),
    LegalIRDiagnosticCode.CODEX_REPAIR_ATTRIBUTION.value: (
        "Review the linked closed-loop repair evidence before using the repair outcome for prioritization."
    ),
    LegalIRDiagnosticCode.SOURCE_MAP_UNTRACEABLE.value: (
        "Attach source nodes or mark the fact as explicitly derived before exporting the artifact."
    ),
    LegalIRDiagnosticCode.COMPILER_DIAGNOSTIC.value: (
        "Inspect the originating compiler pass and resolve the reported field before promotion."
    ),
}

_FAMILY_BY_CODE: Final[Mapping[str, LegalIRDiagnosticFamily]] = {
    LegalIRDiagnosticCode.UNRESOLVED_SYMBOL.value: LegalIRDiagnosticFamily.SYMBOL,
    LegalIRDiagnosticCode.AMBIGUOUS_SYMBOL.value: LegalIRDiagnosticFamily.SYMBOL,
    LegalIRDiagnosticCode.UNRESOLVED_CITATION.value: LegalIRDiagnosticFamily.CITATION,
    LegalIRDiagnosticCode.AMBIGUOUS_CITATION.value: LegalIRDiagnosticFamily.CITATION,
    LegalIRDiagnosticCode.REPEALED_CITATION.value: LegalIRDiagnosticFamily.CITATION,
    LegalIRDiagnosticCode.AMBIGUITY_UNRESOLVED.value: LegalIRDiagnosticFamily.AMBIGUITY,
    LegalIRDiagnosticCode.TEMPORAL_AUTHORITY_INVALID.value: LegalIRDiagnosticFamily.TEMPORAL_AUTHORITY,
    LegalIRDiagnosticCode.UNSUPPORTED_BACKEND_FEATURE.value: LegalIRDiagnosticFamily.UNSUPPORTED_BACKEND_FEATURE,
    LegalIRDiagnosticCode.PROOF_FAILURE.value: LegalIRDiagnosticFamily.PROOF_FAILURE,
    LegalIRDiagnosticCode.LEARNED_GUIDANCE_ABSTENTION.value: LegalIRDiagnosticFamily.LEARNED_GUIDANCE_ABSTENTION,
    LegalIRDiagnosticCode.POISONING_REJECTION.value: LegalIRDiagnosticFamily.POISONING_REJECTION,
    LegalIRDiagnosticCode.DECOMPILER_LOSS.value: LegalIRDiagnosticFamily.DECOMPILER_LOSS,
    LegalIRDiagnosticCode.CODEX_REPAIR_ATTRIBUTION.value: LegalIRDiagnosticFamily.CODEX_REPAIR_ATTRIBUTION,
    LegalIRDiagnosticCode.SOURCE_MAP_UNTRACEABLE.value: LegalIRDiagnosticFamily.SOURCE_MAP,
    LegalIRDiagnosticCode.COMPILER_DIAGNOSTIC.value: LegalIRDiagnosticFamily.COMPILER,
}


@dataclass(frozen=True)
class LegalIRDiagnosticSourceMap:
    """Source-map coordinates attached to one diagnostic."""

    source_map_id: str = ""
    source_node_ids: tuple[str, ...] = ()
    source_span_ids: tuple[str, ...] = ()
    document_id: str = ""
    citation: str = ""
    field_path: str = ""
    start_offset: int | None = None
    end_offset: int | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_node_ids", _unique_text(self.source_node_ids))
        object.__setattr__(self, "source_span_ids", _unique_text(self.source_span_ids))
        object.__setattr__(self, "metadata", _json_ready_mapping(self.metadata))

    @property
    def traceable(self) -> bool:
        return bool(self.source_map_id or self.source_node_ids or self.source_span_ids)

    def to_dict(self) -> dict[str, Any]:
        return {
            "citation": self.citation,
            "document_id": self.document_id,
            "end_offset": self.end_offset,
            "field_path": self.field_path,
            "metadata": _json_ready(self.metadata),
            "source_map_id": self.source_map_id,
            "source_node_ids": list(self.source_node_ids),
            "source_span_ids": list(self.source_span_ids),
            "start_offset": self.start_offset,
            "traceable": self.traceable,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "LegalIRDiagnosticSourceMap":
        return cls(
            source_map_id=str(data.get("source_map_id") or ""),
            source_node_ids=tuple(_strings(data.get("source_node_ids", ()))),
            source_span_ids=tuple(
                _strings(data.get("source_span_ids", data.get("span_ids", ())))
            ),
            document_id=str(data.get("document_id") or data.get("source_document_id") or ""),
            citation=str(data.get("citation") or data.get("canonical_citation") or ""),
            field_path=str(data.get("field_path") or ""),
            start_offset=_optional_int(data.get("start_offset")),
            end_offset=_optional_int(data.get("end_offset")),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass(frozen=True)
class LegalIRExplanationStep:
    """One deterministic explanation step for a diagnostic."""

    step_id: str
    family: LegalIRDiagnosticFamily
    action: str
    rationale: str
    evidence_ids: tuple[str, ...] = ()
    source_map: LegalIRDiagnosticSourceMap = field(default_factory=LegalIRDiagnosticSourceMap)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "family", _family(self.family))
        object.__setattr__(self, "evidence_ids", _unique_text(self.evidence_ids))
        if not isinstance(self.source_map, LegalIRDiagnosticSourceMap):
            object.__setattr__(
                self, "source_map", LegalIRDiagnosticSourceMap.from_dict(_mapping(self.source_map))
            )
        object.__setattr__(self, "metadata", _json_ready_mapping(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "evidence_ids": list(self.evidence_ids),
            "family": self.family.value,
            "metadata": _json_ready(self.metadata),
            "rationale": self.rationale,
            "source_map": self.source_map.to_dict(),
            "step_id": self.step_id,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "LegalIRExplanationStep":
        return cls(
            step_id=str(data.get("step_id") or ""),
            family=_family(data.get("family")),
            action=str(data.get("action") or ""),
            rationale=str(data.get("rationale") or data.get("message") or ""),
            evidence_ids=tuple(_strings(data.get("evidence_ids", ()))),
            source_map=LegalIRDiagnosticSourceMap.from_dict(_mapping(data.get("source_map"))),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass(frozen=True)
class LegalIRExplanationTrace:
    """Actionable explanation attached to one diagnostic."""

    trace_id: str
    diagnostic_id: str
    summary: str
    steps: tuple[LegalIRExplanationStep, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "steps",
            tuple(
                step
                if isinstance(step, LegalIRExplanationStep)
                else LegalIRExplanationStep.from_dict(_mapping(step))
                for step in self.steps
            ),
        )
        object.__setattr__(self, "metadata", _json_ready_mapping(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "diagnostic_id": self.diagnostic_id,
            "metadata": _json_ready(self.metadata),
            "steps": [step.to_dict() for step in self.steps],
            "summary": self.summary,
            "trace_id": self.trace_id,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "LegalIRExplanationTrace":
        return cls(
            trace_id=str(data.get("trace_id") or ""),
            diagnostic_id=str(data.get("diagnostic_id") or ""),
            summary=str(data.get("summary") or ""),
            steps=tuple(
                LegalIRExplanationStep.from_dict(_mapping(item))
                for item in data.get("steps", ()) or ()
            ),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass(frozen=True)
class LegalIRDiagnostic:
    """One structured LegalIR compiler diagnostic."""

    code: str
    message: str
    severity: LegalIRDiagnosticSeverity = LegalIRDiagnosticSeverity.ERROR
    family: LegalIRDiagnosticFamily | str = LegalIRDiagnosticFamily.COMPILER
    source_map: LegalIRDiagnosticSourceMap = field(default_factory=LegalIRDiagnosticSourceMap)
    remediation_hint: str = ""
    diagnostic_id: str = ""
    related_ids: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    explanation_trace_id: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = LEGAL_IR_DIAGNOSTICS_SCHEMA_VERSION

    def __post_init__(self) -> None:
        code = _code(self.code)
        family = _family(self.family or _FAMILY_BY_CODE.get(code))
        severity = _severity(self.severity)
        source_map = (
            self.source_map
            if isinstance(self.source_map, LegalIRDiagnosticSourceMap)
            else LegalIRDiagnosticSourceMap.from_dict(_mapping(self.source_map))
        )
        related = {
            str(key): _unique_text(value)
            for key, value in (self.related_ids or {}).items()
            if _unique_text(value)
        }
        payload = {
            "code": code,
            "family": family.value,
            "message": self.message,
            "related_ids": related,
            "severity": severity.value,
            "source_map": source_map.to_dict(),
        }
        diagnostic_id = str(self.diagnostic_id or "lir-diagnostic-" + _stable_hash(payload)[:24])
        trace_id = str(self.explanation_trace_id or "lir-trace-" + _stable_hash([diagnostic_id, code])[:24])
        object.__setattr__(self, "code", code)
        object.__setattr__(self, "family", family)
        object.__setattr__(self, "severity", severity)
        object.__setattr__(self, "source_map", source_map)
        object.__setattr__(
            self,
            "remediation_hint",
            self.remediation_hint or _REMEDIATION_HINTS.get(code, _REMEDIATION_HINTS[LegalIRDiagnosticCode.COMPILER_DIAGNOSTIC.value]),
        )
        object.__setattr__(self, "diagnostic_id", diagnostic_id)
        object.__setattr__(self, "related_ids", related)
        object.__setattr__(self, "explanation_trace_id", trace_id)
        object.__setattr__(self, "metadata", _json_ready_mapping(self.metadata))

    @property
    def error(self) -> bool:
        return self.severity in {LegalIRDiagnosticSeverity.ERROR, LegalIRDiagnosticSeverity.FATAL}

    def default_trace(self) -> LegalIRExplanationTrace:
        evidence_ids = []
        for ids in self.related_ids.values():
            evidence_ids.extend(ids)
        step = LegalIRExplanationStep(
            step_id=f"{self.explanation_trace_id}:source",
            family=self.family,
            action="classify",
            rationale=self.message,
            evidence_ids=tuple(evidence_ids),
            source_map=self.source_map,
            metadata={"code": self.code, "severity": self.severity.value},
        )
        remedy = LegalIRExplanationStep(
            step_id=f"{self.explanation_trace_id}:remediate",
            family=self.family,
            action="remediate",
            rationale=self.remediation_hint,
            evidence_ids=tuple(evidence_ids),
            source_map=self.source_map,
        )
        return LegalIRExplanationTrace(
            trace_id=self.explanation_trace_id,
            diagnostic_id=self.diagnostic_id,
            summary=f"{self.family.value}: {self.code}",
            steps=(step, remedy),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "diagnostic_id": self.diagnostic_id,
            "error": self.error,
            "explanation_trace_id": self.explanation_trace_id,
            "family": self.family.value,
            "message": self.message,
            "metadata": _json_ready(self.metadata),
            "related_ids": {key: list(value) for key, value in self.related_ids.items()},
            "remediation_hint": self.remediation_hint,
            "schema_version": self.schema_version,
            "severity": self.severity.value,
            "source_map": self.source_map.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "LegalIRDiagnostic":
        return cls(
            code=str(data.get("code") or ""),
            message=str(data.get("message") or ""),
            severity=_severity(data.get("severity")),
            family=_family(data.get("family")),
            source_map=LegalIRDiagnosticSourceMap.from_dict(_mapping(data.get("source_map"))),
            remediation_hint=str(data.get("remediation_hint") or ""),
            diagnostic_id=str(data.get("diagnostic_id") or ""),
            related_ids={
                str(key): tuple(_strings(value))
                for key, value in _mapping(data.get("related_ids")).items()
            },
            explanation_trace_id=str(data.get("explanation_trace_id") or ""),
            metadata=dict(data.get("metadata") or {}),
            schema_version=str(data.get("schema_version") or LEGAL_IR_DIAGNOSTICS_SCHEMA_VERSION),
        )


@dataclass(frozen=True)
class LegalIRDiagnosticReport:
    """A deterministic batch of diagnostics and traces."""

    report_id: str
    diagnostics: tuple[LegalIRDiagnostic, ...]
    traces: tuple[LegalIRExplanationTrace, ...] = ()
    artifact_id: str = ""
    source_map_id: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = LEGAL_IR_DIAGNOSTICS_SCHEMA_VERSION

    def __post_init__(self) -> None:
        diagnostics = tuple(
            item if isinstance(item, LegalIRDiagnostic) else LegalIRDiagnostic.from_dict(_mapping(item))
            for item in self.diagnostics
        )
        trace_by_id = {
            trace.trace_id: trace
            for trace in (
                item
                if isinstance(item, LegalIRExplanationTrace)
                else LegalIRExplanationTrace.from_dict(_mapping(item))
                for item in self.traces
            )
        }
        for diagnostic in diagnostics:
            trace_by_id.setdefault(diagnostic.explanation_trace_id, diagnostic.default_trace())
        report_id = self.report_id or "lir-diagnostic-report-" + _stable_hash(
            [diagnostic.to_dict() for diagnostic in diagnostics]
        )[:24]
        object.__setattr__(self, "report_id", report_id)
        object.__setattr__(self, "diagnostics", diagnostics)
        object.__setattr__(self, "traces", tuple(trace_by_id[key] for key in sorted(trace_by_id)))
        object.__setattr__(self, "metadata", _json_ready_mapping(self.metadata))

    @property
    def error_count(self) -> int:
        return sum(1 for diagnostic in self.diagnostics if diagnostic.error)

    @property
    def warning_count(self) -> int:
        return sum(1 for diagnostic in self.diagnostics if diagnostic.severity is LegalIRDiagnosticSeverity.WARNING)

    @property
    def valid(self) -> bool:
        return self.error_count == 0

    @property
    def families(self) -> tuple[str, ...]:
        return tuple(sorted({diagnostic.family.value for diagnostic in self.diagnostics}))

    def by_family(self, family: LegalIRDiagnosticFamily | str) -> tuple[LegalIRDiagnostic, ...]:
        resolved = _family(family)
        return tuple(diagnostic for diagnostic in self.diagnostics if diagnostic.family is resolved)

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "diagnostics": [diagnostic.to_dict() for diagnostic in self.diagnostics],
            "error_count": self.error_count,
            "families": list(self.families),
            "metadata": _json_ready(self.metadata),
            "report_id": self.report_id,
            "schema_version": self.schema_version,
            "source_map_id": self.source_map_id,
            "traces": [trace.to_dict() for trace in self.traces],
            "valid": self.valid,
            "warning_count": self.warning_count,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "LegalIRDiagnosticReport":
        return cls(
            report_id=str(data.get("report_id") or ""),
            diagnostics=tuple(
                LegalIRDiagnostic.from_dict(_mapping(item))
                for item in data.get("diagnostics", ()) or ()
            ),
            traces=tuple(
                LegalIRExplanationTrace.from_dict(_mapping(item))
                for item in data.get("traces", ()) or ()
            ),
            artifact_id=str(data.get("artifact_id") or ""),
            source_map_id=str(data.get("source_map_id") or ""),
            metadata=dict(data.get("metadata") or {}),
            schema_version=str(data.get("schema_version") or LEGAL_IR_DIAGNOSTICS_SCHEMA_VERSION),
        )


class LegalIRDiagnosticsBuilder:
    """Incremental builder for diagnostics and explanation traces."""

    def __init__(
        self,
        *,
        artifact_id: str = "",
        source_map: LegalIRSourceMap | Mapping[str, Any] | None = None,
        source_map_id: str = "",
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        self.artifact_id = str(artifact_id or "")
        self.source_map = _source_map(source_map)
        self.source_map_id = source_map_id or (self.source_map.source_map_id if self.source_map else "")
        self.metadata = dict(metadata or {})
        self._diagnostics: list[LegalIRDiagnostic] = []
        self._traces: list[LegalIRExplanationTrace] = []

    def add(
        self,
        code: LegalIRDiagnosticCode | str,
        message: str,
        *,
        severity: LegalIRDiagnosticSeverity | str = LegalIRDiagnosticSeverity.ERROR,
        family: LegalIRDiagnosticFamily | str | None = None,
        remediation_hint: str = "",
        diagnostic_id: str = "",
        source_node_ids: Sequence[str] = (),
        source_span_ids: Sequence[str] = (),
        field_path: str = "",
        document_id: str = "",
        citation: str = "",
        related_ids: Mapping[str, Sequence[str]] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> LegalIRDiagnostic:
        source_ref = _source_ref(
            self.source_map,
            source_map_id=self.source_map_id,
            source_node_ids=source_node_ids,
            source_span_ids=source_span_ids,
            field_path=field_path,
            document_id=document_id,
            citation=citation,
        )
        diagnostic = LegalIRDiagnostic(
            code=_code(code),
            message=str(message or ""),
            severity=_severity(severity),
            family=_family(family or _FAMILY_BY_CODE.get(_code(code))),
            source_map=source_ref,
            remediation_hint=remediation_hint,
            diagnostic_id=diagnostic_id,
            related_ids={
                key: tuple(_strings(value))
                for key, value in (related_ids or {}).items()
            },
            metadata=dict(metadata or {}),
        )
        self._diagnostics.append(diagnostic)
        self._traces.append(diagnostic.default_trace())
        return diagnostic

    def add_unresolved_symbol(self, message: str, **kwargs: Any) -> LegalIRDiagnostic:
        return self.add(LegalIRDiagnosticCode.UNRESOLVED_SYMBOL, message, **kwargs)

    def add_ambiguous_symbol(self, message: str, **kwargs: Any) -> LegalIRDiagnostic:
        return self.add(LegalIRDiagnosticCode.AMBIGUOUS_SYMBOL, message, **kwargs)

    def add_unresolved_citation(self, message: str, **kwargs: Any) -> LegalIRDiagnostic:
        return self.add(LegalIRDiagnosticCode.UNRESOLVED_CITATION, message, **kwargs)

    def add_ambiguous_citation(self, message: str, **kwargs: Any) -> LegalIRDiagnostic:
        return self.add(LegalIRDiagnosticCode.AMBIGUOUS_CITATION, message, **kwargs)

    def add_ambiguity(self, message: str, **kwargs: Any) -> LegalIRDiagnostic:
        return self.add(LegalIRDiagnosticCode.AMBIGUITY_UNRESOLVED, message, **kwargs)

    def add_temporal_authority(self, message: str, **kwargs: Any) -> LegalIRDiagnostic:
        return self.add(LegalIRDiagnosticCode.TEMPORAL_AUTHORITY_INVALID, message, **kwargs)

    def add_unsupported_backend_feature(self, message: str, **kwargs: Any) -> LegalIRDiagnostic:
        return self.add(
            LegalIRDiagnosticCode.UNSUPPORTED_BACKEND_FEATURE,
            message,
            severity=kwargs.pop("severity", LegalIRDiagnosticSeverity.WARNING),
            **kwargs,
        )

    def add_proof_failure(self, message: str, **kwargs: Any) -> LegalIRDiagnostic:
        return self.add(LegalIRDiagnosticCode.PROOF_FAILURE, message, **kwargs)

    def add_learned_guidance_abstention(self, message: str, **kwargs: Any) -> LegalIRDiagnostic:
        return self.add(
            LegalIRDiagnosticCode.LEARNED_GUIDANCE_ABSTENTION,
            message,
            severity=kwargs.pop("severity", LegalIRDiagnosticSeverity.WARNING),
            **kwargs,
        )

    def add_poisoning_rejection(self, message: str, **kwargs: Any) -> LegalIRDiagnostic:
        return self.add(LegalIRDiagnosticCode.POISONING_REJECTION, message, **kwargs)

    def add_decompiler_loss(self, message: str, **kwargs: Any) -> LegalIRDiagnostic:
        return self.add(LegalIRDiagnosticCode.DECOMPILER_LOSS, message, **kwargs)

    def add_codex_repair_attribution(self, message: str, **kwargs: Any) -> LegalIRDiagnostic:
        return self.add(
            LegalIRDiagnosticCode.CODEX_REPAIR_ATTRIBUTION,
            message,
            severity=kwargs.pop("severity", LegalIRDiagnosticSeverity.INFO),
            **kwargs,
        )

    def extend(self, diagnostics: Iterable[LegalIRDiagnostic | Mapping[str, Any]]) -> None:
        for item in diagnostics:
            diagnostic = item if isinstance(item, LegalIRDiagnostic) else LegalIRDiagnostic.from_dict(_mapping(item))
            self._diagnostics.append(diagnostic)
            self._traces.append(diagnostic.default_trace())

    def build(self, *, report_id: str = "") -> LegalIRDiagnosticReport:
        return LegalIRDiagnosticReport(
            report_id=report_id,
            diagnostics=_dedupe_diagnostics(self._diagnostics),
            traces=tuple(self._traces),
            artifact_id=self.artifact_id,
            source_map_id=self.source_map_id,
            metadata=self.metadata,
        )


def legal_ir_diagnostic(
    code: LegalIRDiagnosticCode | str,
    message: str,
    **kwargs: Any,
) -> LegalIRDiagnostic:
    """Create one structured diagnostic."""

    builder = LegalIRDiagnosticsBuilder(source_map=kwargs.pop("source_map", None))
    return builder.add(code, message, **kwargs)


def build_legal_ir_diagnostic_report(
    *artifacts: Any,
    symbol_tables: Iterable[Any] = (),
    citation_graphs: Iterable[Any] = (),
    ambiguities: Iterable[Any] = (),
    temporal_authority: Iterable[Any] = (),
    temporal_results: Iterable[Any] = (),
    backend_reports: Iterable[Any] = (),
    proof_artifacts: Iterable[Any] = (),
    learned_guidance: Iterable[Any] = (),
    security_reports: Iterable[Any] = (),
    decompiler_reports: Iterable[Any] = (),
    decompiler_telemetry: Iterable[Any] = (),
    repair_lineages: Iterable[Any] = (),
    artifact_id: str = "",
    source_map: LegalIRSourceMap | Mapping[str, Any] | None = None,
    report_id: str = "",
    metadata: Mapping[str, Any] | None = None,
) -> LegalIRDiagnosticReport:
    """Collect diagnostics from heterogeneous LegalIR artifacts."""

    builder = LegalIRDiagnosticsBuilder(
        artifact_id=artifact_id,
        source_map=source_map,
        metadata=metadata,
    )
    grouped = (
        *artifacts,
        *_iterable_items(symbol_tables),
        *_iterable_items(citation_graphs),
        *_iterable_items(ambiguities),
        *_iterable_items(temporal_authority),
        *_iterable_items(temporal_results),
        *_iterable_items(backend_reports),
        *_iterable_items(proof_artifacts),
        *_iterable_items(learned_guidance),
        *_iterable_items(security_reports),
        *_iterable_items(decompiler_reports),
        *_iterable_items(decompiler_telemetry),
        *_iterable_items(repair_lineages),
    )
    for artifact in grouped:
        _collect_artifact(builder, artifact)
    return builder.build(report_id=report_id)


def collect_legal_ir_diagnostics(
    artifacts: Iterable[Any],
    *,
    artifact_id: str = "",
    source_map: LegalIRSourceMap | Mapping[str, Any] | None = None,
    report_id: str = "",
    metadata: Mapping[str, Any] | None = None,
) -> LegalIRDiagnosticReport:
    """Iterable-friendly alias for ``build_legal_ir_diagnostic_report``."""

    return build_legal_ir_diagnostic_report(
        *tuple(artifacts),
        artifact_id=artifact_id,
        source_map=source_map,
        report_id=report_id,
        metadata=metadata,
    )


def attach_legal_ir_diagnostic_to_source_map(
    builder: LegalIRSourceMapBuilder,
    diagnostic: LegalIRDiagnostic | Mapping[str, Any],
) -> str:
    """Record a diagnostic as a derived source-map node and return its node id."""

    resolved = diagnostic if isinstance(diagnostic, LegalIRDiagnostic) else LegalIRDiagnostic.from_dict(_mapping(diagnostic))
    source_node_ids = resolved.source_map.source_node_ids
    if source_node_ids:
        builder.add_derived_node(
            resolved.diagnostic_id,
            node_kind="diagnostic",
            derived_from_node_ids=source_node_ids,
            transformation_step="diagnostics.emit",
            transform_kind=LegalIRTransformationKind.DIAGNOSTIC,
            metadata=resolved.to_dict(),
        )
    else:
        builder.add_node(
            resolved.diagnostic_id,
            node_kind="diagnostic",
            span_ids=resolved.source_map.source_span_ids,
            transformation_step_id="diagnostics.emit",
            metadata=resolved.to_dict(),
        )
    return resolved.diagnostic_id


def _collect_artifact(builder: LegalIRDiagnosticsBuilder, artifact: Any) -> None:
    if artifact is None:
        return
    if isinstance(artifact, LegalIRDiagnostic):
        builder.extend((artifact,))
        return
    if isinstance(artifact, LegalIRDiagnosticReport):
        builder.extend(artifact.diagnostics)
        return
    data = _mapping(artifact)
    if not data:
        if isinstance(artifact, Sequence) and not isinstance(artifact, (str, bytes, bytearray)):
            for item in artifact:
                _collect_artifact(builder, item)
        return

    schema = str(data.get("schema_version") or "")
    if schema == LEGAL_IR_DIAGNOSTICS_SCHEMA_VERSION and data.get("diagnostics"):
        builder.extend(LegalIRDiagnosticReport.from_dict(data).diagnostics)
        return

    _collect_local_diagnostics(builder, data)
    _collect_unsupported_backend(builder, data)
    _collect_security_findings(builder, data)
    _collect_decompiler_losses(builder, data)
    _collect_proof_failures(builder, data)
    _collect_learned_guidance(builder, data)
    _collect_repair_lineage(builder, data)

    for key in (
        "graphs",
        "reports",
        "results",
        "resolutions",
        "security_reports",
        "telemetry",
        "validation_results",
    ):
        nested = data.get(key)
        if isinstance(nested, Sequence) and not isinstance(nested, (str, bytes, bytearray)):
            for item in nested:
                _collect_artifact(builder, item)


def _collect_local_diagnostics(builder: LegalIRDiagnosticsBuilder, data: Mapping[str, Any]) -> None:
    for item in _sequence(data.get("diagnostics")):
        diagnostic = _mapping(item)
        if not diagnostic:
            continue
        source_node_ids = tuple(_strings(diagnostic.get("source_node_ids", ())))
        source_span_ids = tuple(_strings(diagnostic.get("source_span_ids", diagnostic.get("span_ids", ()))))
        raw_code = str(diagnostic.get("code") or diagnostic.get("diagnostic_type") or "")
        code = _code_from_local(raw_code, data)
        builder.add(
            code,
            str(diagnostic.get("message") or raw_code or "LegalIR diagnostic."),
            severity=str(diagnostic.get("severity") or "error"),
            source_node_ids=source_node_ids,
            source_span_ids=source_span_ids,
            field_path=str(diagnostic.get("field_path") or ""),
            document_id=str(diagnostic.get("document_id") or ""),
            citation=str(diagnostic.get("citation") or diagnostic.get("canonical_citation") or ""),
            related_ids=_related_ids(diagnostic),
            metadata={"origin_code": raw_code, **dict(diagnostic.get("metadata") or {})},
        )


def _collect_unsupported_backend(builder: LegalIRDiagnosticsBuilder, data: Mapping[str, Any]) -> None:
    for item in _sequence(data.get("unsupported_diagnostics")) + _sequence(data.get("unsupported_features")):
        diagnostic = _mapping(item)
        if not diagnostic:
            if item:
                diagnostic = {"feature": item}
            else:
                continue
        feature = str(
            diagnostic.get("feature")
            or diagnostic.get("backend_feature")
            or diagnostic.get("unsupported_feature")
            or ""
        )
        backend = str(diagnostic.get("backend") or diagnostic.get("target") or data.get("backend") or "")
        reason = str(diagnostic.get("reason_code") or diagnostic.get("reason") or diagnostic.get("code") or "")
        message = str(diagnostic.get("message") or f"Backend {backend or '<unknown>'} does not support {feature or '<unknown feature>'}.")
        builder.add_unsupported_backend_feature(
            message,
            severity=str(diagnostic.get("severity") or "warning"),
            related_ids={
                "backend": (backend,),
                "feature": (feature,),
                "obligation_ids": tuple(_strings(diagnostic.get("obligation_ids", ()))),
            },
            metadata={"reason_code": reason, **dict(diagnostic.get("metadata") or {})},
        )


def _collect_security_findings(builder: LegalIRDiagnosticsBuilder, data: Mapping[str, Any]) -> None:
    rejected = bool(data.get("rejected") or data.get("accepted") is False)
    findings = _sequence(data.get("findings"))
    reasons = tuple(_strings(data.get("rejection_reasons", ())))
    if not rejected and not findings and not reasons:
        return
    artifact_id = str(data.get("artifact_id") or "")
    for finding in findings or [{"reason": reason} for reason in reasons] or [{}]:
        payload = _mapping(finding)
        reason = str(payload.get("reason") or ",".join(reasons) or "poisoning_rejection")
        builder.add_poisoning_rejection(
            str(payload.get("detail") or f"LegalIR artifact was rejected by poisoning defenses: {reason}."),
            severity=str(payload.get("severity") or "error"),
            field_path=str(payload.get("field_path") or ""),
            related_ids={"artifact_id": (artifact_id,), "rejection_reason": (reason,)},
            metadata=payload,
        )


def _collect_decompiler_losses(builder: LegalIRDiagnosticsBuilder, data: Mapping[str, Any]) -> None:
    for key in ("decompiler_preservation_failures", "decompiler_losses"):
        for item in _sequence(data.get(key)):
            failure = _mapping(item)
            if not failure:
                continue
            field_path = str(failure.get("field_path") or "")
            reason = str(failure.get("reason") or "decompiler_loss")
            formula_id = str(failure.get("formula_id") or "")
            builder.add_decompiler_loss(
                str(failure.get("message") or f"Decompiler failed to preserve {field_path or 'a required field'}: {reason}."),
                field_path=field_path,
                related_ids={
                    "failure_id": (str(failure.get("failure_id") or ""),),
                    "formula_id": (formula_id,),
                    "source_contract_id": (str(failure.get("source_contract_id") or ""),),
                },
                metadata=failure,
            )


def _collect_proof_failures(builder: LegalIRDiagnosticsBuilder, data: Mapping[str, Any]) -> None:
    proof_like = any(
        key in data
        for key in (
            "proof_checked",
            "proof_status",
            "reconstruction_status",
            "trusted",
            "verification_status",
            "proof_receipts",
            "reconstruction_receipts",
        )
    )
    for key in ("proof_receipts", "reconstruction_receipts", "hammer_receipts", "receipts"):
        for item in _sequence(data.get(key)):
            _collect_proof_failures(builder, _mapping(item))
    if not proof_like:
        return
    trusted = bool(data.get("trusted", data.get("proof_checked", False)))
    proof_checked = bool(data.get("proof_checked", data.get("kernel_verified", False)))
    status = str(data.get("proof_status") or data.get("status") or data.get("verification_status") or data.get("reconstruction_status") or "")
    failed = (not trusted) or (not proof_checked and status) or status.lower() in {
        "failed",
        "failure",
        "not_reconstructed",
        "rejected",
        "translation_failed",
        "untrusted",
    }
    if not failed:
        return
    obligation_id = str(data.get("obligation_id") or "")
    receipt_id = str(data.get("receipt_id") or data.get("proof_receipt_id") or "")
    builder.add_proof_failure(
        str(data.get("message") or f"Proof evidence is not trusted for obligation {obligation_id or '<unknown>'}."),
        source_node_ids=tuple(_strings(data.get("source_node_ids", ()))),
        related_ids={
            "obligation_id": (obligation_id,),
            "receipt_id": (receipt_id,),
            "input_formula_id": (str(data.get("input_formula_id") or ""),),
        },
        metadata={"status": status, **dict(data.get("metadata") or {})},
    )


def _collect_learned_guidance(builder: LegalIRDiagnosticsBuilder, data: Mapping[str, Any]) -> None:
    promoted = data.get("promoted")
    block_reasons = tuple(_strings(data.get("block_reasons", ())))
    report_outcome = str(data.get("report_outcome") or data.get("promotion_report_outcome") or "")
    if promoted is not False and not block_reasons and report_outcome not in {"no_candidate", "rejection"}:
        return
    source_export_id = str(data.get("source_export_id") or data.get("learned_export_id") or "")
    reasons = block_reasons or ((report_outcome,) if report_outcome else ("abstained",))
    for reason in reasons:
        builder.add_learned_guidance_abstention(
            f"Learned guidance abstained from promotion: {reason}.",
            related_ids={
                "promotion_id": (str(data.get("promotion_id") or ""),),
                "source_export_id": (source_export_id,),
                "block_reason": (reason,),
            },
            metadata=dict(data.get("metadata") or {}),
        )


def _collect_repair_lineage(builder: LegalIRDiagnosticsBuilder, data: Mapping[str, Any]) -> None:
    if str(data.get("schema_version") or "") != "legal-ir-compiler-repair-lineage-v1":
        return
    classification = _mapping(data.get("classification"))
    outcome = str(classification.get("outcome") or data.get("outcome") or "")
    lineage_id = str(data.get("stable_id") or data.get("lineage_id") or "")
    severity = "info" if outcome in {"accepted_benefit", "neutral_change"} else "warning"
    builder.add_codex_repair_attribution(
        f"Codex repair attribution recorded closed-loop outcome {outcome or '<unknown>'}.",
        severity=severity,
        related_ids={
            "lineage_id": (lineage_id,),
            "todo_id": (str(data.get("todo_id") or ""),),
            "outcome": (outcome,),
        },
        metadata={
            "classification": classification,
            "evidence_ids": [
                str(item.get("stable_id") or "")
                for item in _sequence(data.get("evidence_refs"))
                if isinstance(item, Mapping)
            ],
        },
    )


def _code_from_local(raw_code: str, context: Mapping[str, Any]) -> str:
    token = _token(raw_code)
    if token in {
        "unresolved_symbol",
        "alias_target_unresolved",
        "resolution_target_missing",
    }:
        return LegalIRDiagnosticCode.UNRESOLVED_SYMBOL.value
    if token in {"ambiguous_symbol", "symbol_ambiguity"}:
        return LegalIRDiagnosticCode.AMBIGUOUS_SYMBOL.value
    if token in {"unresolved_citation", "authority_missing", "target_authority_missing"}:
        return LegalIRDiagnosticCode.UNRESOLVED_CITATION.value
    if token in {"ambiguous_citation", "citation_ambiguity"}:
        return LegalIRDiagnosticCode.AMBIGUOUS_CITATION.value
    if token in {"repealed_citation"}:
        return LegalIRDiagnosticCode.REPEALED_CITATION.value
    if "ambiguity" in token or token in {"human_review_required", "competing_parse_without_choice"}:
        return LegalIRDiagnosticCode.AMBIGUITY_UNRESOLVED.value
    if token.startswith("temporal") or token in {
        "authority_preempted",
        "emergency_rule_expired",
        "expired_law_used",
        "lower_authority_preempted",
        "not_yet_effective_law_used",
        "repealed_law_used",
        "superseded_law_used",
        "wrong_jurisdiction",
    }:
        return LegalIRDiagnosticCode.TEMPORAL_AUTHORITY_INVALID.value
    if token == "unsupported_feature":
        return LegalIRDiagnosticCode.UNSUPPORTED_BACKEND_FEATURE.value
    if token in {"source_provenance_missing", "source_provenance_untraceable", "missing_fact"}:
        return LegalIRDiagnosticCode.SOURCE_MAP_UNTRACEABLE.value
    if context.get("backend") or context.get("unsupported_diagnostics"):
        return LegalIRDiagnosticCode.UNSUPPORTED_BACKEND_FEATURE.value
    return LegalIRDiagnosticCode.COMPILER_DIAGNOSTIC.value


def _source_ref(
    source_map: LegalIRSourceMap | None,
    *,
    source_map_id: str = "",
    source_node_ids: Sequence[str] = (),
    source_span_ids: Sequence[str] = (),
    field_path: str = "",
    document_id: str = "",
    citation: str = "",
) -> LegalIRDiagnosticSourceMap:
    node_ids = list(_unique_text(source_node_ids))
    span_ids = list(_unique_text(source_span_ids))
    resolved_document = document_id
    resolved_citation = citation
    start_offset: int | None = None
    end_offset: int | None = None
    if source_map is not None:
        for node_id in tuple(node_ids):
            node = source_map.node_by_id.get(node_id)
            if node is not None:
                span_ids.extend(node.span_ids)
            trace = trace_legal_ir_fact(source_map, node_id)
            span_ids.extend(span.span_id for span in trace.source_spans)
        for span_id in _unique_text(span_ids):
            span = source_map.span_by_id.get(span_id)
            if span is None:
                continue
            resolved_document = resolved_document or span.source_document_id
            resolved_citation = resolved_citation or span.citation
            if start_offset is None:
                start_offset = span.start_offset
                end_offset = span.end_offset
        source_map_id = source_map_id or source_map.source_map_id
    return LegalIRDiagnosticSourceMap(
        source_map_id=source_map_id,
        source_node_ids=tuple(node_ids),
        source_span_ids=tuple(_unique_text(span_ids)),
        document_id=resolved_document,
        citation=resolved_citation,
        field_path=field_path,
        start_offset=start_offset,
        end_offset=end_offset,
    )


def _source_map(value: LegalIRSourceMap | Mapping[str, Any] | None) -> LegalIRSourceMap | None:
    if value is None:
        return None
    if isinstance(value, LegalIRSourceMap):
        return value
    if isinstance(value, Mapping):
        return LegalIRSourceMap.from_dict(value)
    return None


def _related_ids(data: Mapping[str, Any]) -> dict[str, tuple[str, ...]]:
    related: dict[str, tuple[str, ...]] = {}
    for key in (
        "alias_ids",
        "ambiguity_id",
        "authority_id",
        "backend",
        "change_id",
        "feature",
        "formula_id",
        "law_version_id",
        "obligation_id",
        "parse_id",
        "receipt_id",
        "reference_id",
        "scope_id",
        "symbol_ids",
        "target_ids",
    ):
        value = data.get(key)
        values = _unique_text(value if isinstance(value, Sequence) and not isinstance(value, str) else (value,))
        if values:
            related[key] = values
    return related


def _code(value: Any) -> str:
    if isinstance(value, LegalIRDiagnosticCode):
        return value.value
    text = str(value or "").strip()
    if not text:
        return LegalIRDiagnosticCode.COMPILER_DIAGNOSTIC.value
    try:
        return LegalIRDiagnosticCode(text).value
    except ValueError:
        token = _token(text)
        for code in LegalIRDiagnosticCode:
            if token == _token(code.name) or token == _token(code.value):
                return code.value
        return text


def _family(value: Any) -> LegalIRDiagnosticFamily:
    if isinstance(value, LegalIRDiagnosticFamily):
        return value
    text = str(value or "").strip()
    if not text:
        return LegalIRDiagnosticFamily.COMPILER
    token = _token(text)
    aliases = {
        "backend": LegalIRDiagnosticFamily.UNSUPPORTED_BACKEND_FEATURE,
        "unsupported_feature": LegalIRDiagnosticFamily.UNSUPPORTED_BACKEND_FEATURE,
        "proof": LegalIRDiagnosticFamily.PROOF_FAILURE,
        "learned_guidance": LegalIRDiagnosticFamily.LEARNED_GUIDANCE_ABSTENTION,
        "poisoning": LegalIRDiagnosticFamily.POISONING_REJECTION,
        "security": LegalIRDiagnosticFamily.POISONING_REJECTION,
        "decompiler": LegalIRDiagnosticFamily.DECOMPILER_LOSS,
        "codex": LegalIRDiagnosticFamily.CODEX_REPAIR_ATTRIBUTION,
        "repair": LegalIRDiagnosticFamily.CODEX_REPAIR_ATTRIBUTION,
    }
    if token in aliases:
        return aliases[token]
    try:
        return LegalIRDiagnosticFamily(token)
    except ValueError:
        return _FAMILY_BY_CODE.get(_code(text), LegalIRDiagnosticFamily.COMPILER)


def _severity(value: Any) -> LegalIRDiagnosticSeverity:
    if isinstance(value, LegalIRDiagnosticSeverity):
        return value
    token = _token(value)
    aliases = {
        "debug": LegalIRDiagnosticSeverity.INFO,
        "warn": LegalIRDiagnosticSeverity.WARNING,
        "warning": LegalIRDiagnosticSeverity.WARNING,
        "err": LegalIRDiagnosticSeverity.ERROR,
        "critical": LegalIRDiagnosticSeverity.FATAL,
        "blocker": LegalIRDiagnosticSeverity.FATAL,
    }
    if token in aliases:
        return aliases[token]
    try:
        return LegalIRDiagnosticSeverity(token or "error")
    except ValueError:
        return LegalIRDiagnosticSeverity.ERROR


def _stable_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            _json_ready(value),
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


def _json_ready(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            return str(value)
        return value
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {
            str(key): _json_ready(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_json_ready(item) for item in value]
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return _json_ready(to_dict())
    return str(value)


def _json_ready_mapping(value: Mapping[str, Any]) -> Mapping[str, Any]:
    ready = _json_ready(dict(value or {}))
    return ready if isinstance(ready, Mapping) else {}


def _mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        converted = to_dict()
        if isinstance(converted, Mapping):
            return dict(converted)
    return {}


def _sequence(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return list(value)
    return [value]


def _iterable_items(value: Any) -> tuple[Any, ...]:
    if value is None:
        return ()
    if isinstance(value, (str, bytes, bytearray, Mapping)):
        return (value,)
    if isinstance(value, Iterable):
        return tuple(value)
    return (value,)


def _strings(value: Any) -> tuple[str, ...]:
    return tuple(str(item).strip() for item in _sequence(value) if str(item).strip())


def _unique_text(value: Any) -> tuple[str, ...]:
    return tuple(dict.fromkeys(_strings(value)))


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _token(value: Any) -> str:
    text = str(getattr(value, "value", value) or "").strip().lower()
    return re.sub(r"[^a-z0-9_.:-]+", "_", text).strip("_")


def _dedupe_diagnostics(
    diagnostics: Iterable[LegalIRDiagnostic],
) -> tuple[LegalIRDiagnostic, ...]:
    result: list[LegalIRDiagnostic] = []
    seen: set[tuple[Any, ...]] = set()
    for diagnostic in diagnostics:
        key = (
            diagnostic.code,
            diagnostic.family.value,
            diagnostic.severity.value,
            diagnostic.message,
            tuple(sorted(diagnostic.related_ids.items())),
            tuple(diagnostic.source_map.source_node_ids),
            tuple(diagnostic.source_map.source_span_ids),
            diagnostic.source_map.field_path,
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(diagnostic)
    return tuple(result)


__all__ = [
    "LEGAL_IR_DIAGNOSTICS_SCHEMA_VERSION",
    "LegalIRDiagnostic",
    "LegalIRDiagnosticCode",
    "LegalIRDiagnosticFamily",
    "LegalIRDiagnosticReport",
    "LegalIRDiagnosticSeverity",
    "LegalIRDiagnosticSourceMap",
    "LegalIRDiagnosticsBuilder",
    "LegalIRExplanationStep",
    "LegalIRExplanationTrace",
    "attach_legal_ir_diagnostic_to_source_map",
    "build_legal_ir_diagnostic_report",
    "collect_legal_ir_diagnostics",
    "legal_ir_diagnostic",
]
