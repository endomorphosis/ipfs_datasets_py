"""First-class ambiguity values for LegalIR.

Ambiguity is legal information, not a spare learned label.  This module records
unresolved ambiguity, competing parses, unsupported interpretations, and human
review requirements as typed IR objects with source spans and confidence.  The
validation and routing helpers fail closed for proof and learned-target use and
send high-impact ambiguity to Leanstral audit or operator diagnostics.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Final


LEGAL_IR_AMBIGUITY_SCHEMA_VERSION: Final = "legal-ir-ambiguity-v1"

DEFAULT_HIGH_IMPACT_CONFIDENCE_THRESHOLD: Final = 0.85
DEFAULT_LOW_CONFIDENCE_THRESHOLD: Final = 0.72


class LegalIRAmbiguityKind(str, Enum):
    """Stable ambiguity categories emitted by LegalIR compiler passes."""

    UNRESOLVED_AMBIGUITY = "unresolved_ambiguity"
    COMPETING_PARSE = "competing_parse"
    UNSUPPORTED_INTERPRETATION = "unsupported_interpretation"
    REQUIRED_HUMAN_REVIEW = "required_human_review"
    CITATION_AMBIGUITY = "citation_ambiguity"
    TEMPORAL_AUTHORITY_AMBIGUITY = "temporal_authority_ambiguity"
    SYMBOL_AMBIGUITY = "symbol_ambiguity"
    DEONTIC_SCOPE_AMBIGUITY = "deontic_scope_ambiguity"
    SOURCE_SPAN_AMBIGUITY = "source_span_ambiguity"


class LegalIRAmbiguityStatus(str, Enum):
    """Resolution state for one first-class ambiguity record."""

    UNRESOLVED = "unresolved"
    COMPETING = "competing"
    UNSUPPORTED = "unsupported"
    REVIEW_REQUIRED = "review_required"
    OPERATOR_DIAGNOSTIC = "operator_diagnostic"
    RESOLVED = "resolved"
    REJECTED = "rejected"


class LegalIRAmbiguityImpact(str, Enum):
    """Legal and operational impact used for audit routing."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class LegalIRAmbiguityRoute(str, Enum):
    """Where ambiguity must go before it can influence downstream artifacts."""

    ALLOWED = "allowed"
    COMPILER_DIAGNOSTIC = "compiler_diagnostic"
    OPERATOR_DIAGNOSTIC = "operator_diagnostic"
    HAMMER_LEANSTRAL_AUDIT = "hammer_leanstral_audit"
    BLOCKED_FROM_PROOF = "blocked_from_proof"
    BLOCKED_FROM_LEARNED_TARGET = "blocked_from_learned_target"


class LegalIRAmbiguityUse(str, Enum):
    """Downstream use classes that have different fail-closed semantics."""

    COMPILER = "compiler"
    DIAGNOSTIC = "diagnostic"
    PROOF_TARGET = "proof_target"
    LEARNED_TARGET = "learned_target"


class LegalIRAmbiguityDiagnosticType(str, Enum):
    """Typed diagnostics emitted by ambiguity validation and routing."""

    SOURCE_SPAN_MISSING = "source_span_missing"
    CONFIDENCE_OUT_OF_RANGE = "confidence_out_of_range"
    LOW_CONFIDENCE = "low_confidence"
    COMPETING_PARSE_REQUIRED = "competing_parse_required"
    COMPETING_PARSE_WITHOUT_CHOICE = "competing_parse_without_choice"
    UNSUPPORTED_INTERPRETATION_PRESENT = "unsupported_interpretation_present"
    HUMAN_REVIEW_REQUIRED = "human_review_required"
    HIGH_IMPACT_AMBIGUITY = "high_impact_ambiguity"
    LEARNED_LABEL_COLLAPSE_BLOCKED = "learned_label_collapse_blocked"
    DUPLICATE_AMBIGUITY_ID = "duplicate_ambiguity_id"
    DUPLICATE_PARSE_ID = "duplicate_parse_id"
    AMBIGUITY_ID_MISSING = "ambiguity_id_missing"
    PARSE_ID_MISSING = "parse_id_missing"


@dataclass(frozen=True)
class LegalIRAmbiguitySourceSpan:
    """Source-map span reference attached to an ambiguity value."""

    span_id: str
    source_document_id: str = ""
    start_offset: int = 0
    end_offset: int = 0
    source_node_id: str = ""
    citation: str = ""
    normalized_text_sha256: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def has_offsets(self) -> bool:
        return self.end_offset > self.start_offset >= 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "citation": self.citation,
            "end_offset": int(self.end_offset),
            "metadata": _canonical_json_value(self.metadata),
            "normalized_text_sha256": self.normalized_text_sha256,
            "source_document_id": self.source_document_id,
            "source_node_id": self.source_node_id,
            "span_id": self.span_id,
            "start_offset": int(self.start_offset),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "LegalIRAmbiguitySourceSpan":
        offset = _mapping(data.get("offset"))
        return cls(
            span_id=str(data.get("span_id") or ""),
            source_document_id=str(
                data.get("source_document_id") or data.get("source_document") or ""
            ),
            start_offset=int(data.get("start_offset", offset.get("start", 0)) or 0),
            end_offset=int(data.get("end_offset", offset.get("end", 0)) or 0),
            source_node_id=str(data.get("source_node_id") or data.get("node_id") or ""),
            citation=str(data.get("citation") or ""),
            normalized_text_sha256=str(
                data.get("normalized_text_sha256") or data.get("text_sha256") or ""
            ),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass(frozen=True)
class LegalIRCompetingParse:
    """One candidate parse or interpretation retained without promotion."""

    parse_id: str
    target_view: str
    parse_kind: str = "interpretation"
    confidence: float = 0.0
    supported: bool = True
    support_reason: str = ""
    source_node_ids: tuple[str, ...] = ()
    span_ids: tuple[str, ...] = ()
    formula_ids: tuple[str, ...] = ()
    citation_ids: tuple[str, ...] = ()
    typed_payload: Mapping[str, Any] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "confidence", _bounded_confidence(self.confidence))
        object.__setattr__(self, "source_node_ids", tuple(_unique(_strings(self.source_node_ids))))
        object.__setattr__(self, "span_ids", tuple(_unique(_strings(self.span_ids))))
        object.__setattr__(self, "formula_ids", tuple(_unique(_strings(self.formula_ids))))
        object.__setattr__(self, "citation_ids", tuple(_unique(_strings(self.citation_ids))))

    def to_dict(self) -> dict[str, Any]:
        return {
            "citation_ids": list(self.citation_ids),
            "confidence": round(float(self.confidence), 12),
            "formula_ids": list(self.formula_ids),
            "metadata": _canonical_json_value(self.metadata),
            "parse_id": self.parse_id,
            "parse_kind": self.parse_kind,
            "source_node_ids": list(self.source_node_ids),
            "span_ids": list(self.span_ids),
            "support_reason": self.support_reason,
            "supported": bool(self.supported),
            "target_view": self.target_view,
            "typed_payload": _canonical_json_value(self.typed_payload),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "LegalIRCompetingParse":
        return cls(
            parse_id=str(data.get("parse_id") or data.get("interpretation_id") or data.get("candidate_id") or ""),
            target_view=str(data.get("target_view") or data.get("target_component") or data.get("legal_ir_view") or ""),
            parse_kind=str(data.get("parse_kind") or data.get("kind") or "interpretation"),
            confidence=_bounded_confidence(data.get("confidence")),
            supported=bool(data.get("supported", True)),
            support_reason=str(data.get("support_reason") or data.get("reason") or ""),
            source_node_ids=tuple(_strings(data.get("source_node_ids", ()))),
            span_ids=tuple(_strings(data.get("span_ids", ()))),
            formula_ids=tuple(_strings(data.get("formula_ids", ()))),
            citation_ids=tuple(_strings(data.get("citation_ids", ()))),
            typed_payload=dict(data.get("typed_payload") or data.get("payload") or {}),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass(frozen=True)
class LegalIRAmbiguityDiagnostic:
    """One source-linked ambiguity diagnostic."""

    diagnostic_type: LegalIRAmbiguityDiagnosticType
    message: str
    severity: str = "error"
    ambiguity_id: str = ""
    parse_id: str = ""
    route: LegalIRAmbiguityRoute = LegalIRAmbiguityRoute.COMPILER_DIAGNOSTIC
    span_ids: tuple[str, ...] = ()
    source_node_ids: tuple[str, ...] = ()
    confidence: float = 0.0
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def code(self) -> str:
        return self.diagnostic_type.value

    def to_dict(self) -> dict[str, Any]:
        return {
            "ambiguity_id": self.ambiguity_id,
            "code": self.code,
            "confidence": round(float(self.confidence), 12),
            "diagnostic_type": self.diagnostic_type.value,
            "message": self.message,
            "metadata": _canonical_json_value(self.metadata),
            "parse_id": self.parse_id,
            "route": self.route.value,
            "severity": self.severity,
            "source_node_ids": list(self.source_node_ids),
            "span_ids": list(self.span_ids),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "LegalIRAmbiguityDiagnostic":
        return cls(
            diagnostic_type=_diagnostic_type(data.get("diagnostic_type") or data.get("code")),
            message=str(data.get("message") or ""),
            severity=str(data.get("severity") or "error"),
            ambiguity_id=str(data.get("ambiguity_id") or ""),
            parse_id=str(data.get("parse_id") or ""),
            route=_route(data.get("route")),
            span_ids=tuple(_unique(_strings(data.get("span_ids", ())))),
            source_node_ids=tuple(_unique(_strings(data.get("source_node_ids", ())))),
            confidence=_bounded_confidence(data.get("confidence")),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass(frozen=True)
class LegalIRAmbiguity:
    """A first-class LegalIR ambiguity value."""

    ambiguity_id: str
    ambiguity_kind: LegalIRAmbiguityKind
    status: LegalIRAmbiguityStatus = LegalIRAmbiguityStatus.UNRESOLVED
    confidence: float = 0.0
    impact: LegalIRAmbiguityImpact = LegalIRAmbiguityImpact.MEDIUM
    source_spans: tuple[LegalIRAmbiguitySourceSpan, ...] = ()
    competing_parses: tuple[LegalIRCompetingParse, ...] = ()
    unsupported_interpretations: tuple[LegalIRCompetingParse, ...] = ()
    selected_parse_id: str = ""
    human_review_required: bool = False
    human_review_reason: str = ""
    source_node_ids: tuple[str, ...] = ()
    span_ids: tuple[str, ...] = ()
    authority_ids: tuple[str, ...] = ()
    law_version_ids: tuple[str, ...] = ()
    citation_ids: tuple[str, ...] = ()
    learned_label: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "confidence", _bounded_confidence(self.confidence))
        object.__setattr__(self, "source_node_ids", tuple(_unique(_strings(self.source_node_ids))))
        explicit_span_ids = list(_strings(self.span_ids))
        explicit_span_ids.extend(span.span_id for span in self.source_spans)
        object.__setattr__(self, "span_ids", tuple(_unique(explicit_span_ids)))
        object.__setattr__(self, "authority_ids", tuple(_unique(_strings(self.authority_ids))))
        object.__setattr__(self, "law_version_ids", tuple(_unique(_strings(self.law_version_ids))))
        object.__setattr__(self, "citation_ids", tuple(_unique(_strings(self.citation_ids))))

    @property
    def unresolved(self) -> bool:
        return self.status in {
            LegalIRAmbiguityStatus.UNRESOLVED,
            LegalIRAmbiguityStatus.COMPETING,
            LegalIRAmbiguityStatus.UNSUPPORTED,
            LegalIRAmbiguityStatus.REVIEW_REQUIRED,
            LegalIRAmbiguityStatus.OPERATOR_DIAGNOSTIC,
        }

    @property
    def high_impact(self) -> bool:
        return self.impact in {
            LegalIRAmbiguityImpact.HIGH,
            LegalIRAmbiguityImpact.CRITICAL,
        }

    @property
    def requires_review(self) -> bool:
        return bool(
            self.human_review_required
            or self.status is LegalIRAmbiguityStatus.REVIEW_REQUIRED
            or self.ambiguity_kind is LegalIRAmbiguityKind.REQUIRED_HUMAN_REVIEW
        )

    @property
    def has_unsupported_interpretation(self) -> bool:
        return bool(
            self.unsupported_interpretations
            or any(not item.supported for item in self.competing_parses)
            or self.status is LegalIRAmbiguityStatus.UNSUPPORTED
            or self.ambiguity_kind is LegalIRAmbiguityKind.UNSUPPORTED_INTERPRETATION
        )

    @property
    def learned_label_safe(self) -> bool:
        return not (
            self.unresolved
            or self.requires_review
            or self.has_unsupported_interpretation
            or bool(self.learned_label)
        )

    @property
    def proof_safe(self) -> bool:
        return (
            self.status is LegalIRAmbiguityStatus.RESOLVED
            and bool(self.selected_parse_id)
            and not self.requires_review
            and not self.has_unsupported_interpretation
        )

    @property
    def route(self) -> LegalIRAmbiguityRoute:
        if self.high_impact and (self.unresolved or self.requires_review or self.has_unsupported_interpretation):
            return LegalIRAmbiguityRoute.HAMMER_LEANSTRAL_AUDIT
        if self.requires_review:
            return LegalIRAmbiguityRoute.OPERATOR_DIAGNOSTIC
        if self.unresolved or self.has_unsupported_interpretation:
            return LegalIRAmbiguityRoute.COMPILER_DIAGNOSTIC
        return LegalIRAmbiguityRoute.ALLOWED

    def to_dict(self) -> dict[str, Any]:
        return {
            "ambiguity_id": self.ambiguity_id,
            "ambiguity_kind": self.ambiguity_kind.value,
            "authority_ids": list(self.authority_ids),
            "citation_ids": list(self.citation_ids),
            "competing_parses": [item.to_dict() for item in self.competing_parses],
            "confidence": round(float(self.confidence), 12),
            "high_impact": self.high_impact,
            "human_review_reason": self.human_review_reason,
            "human_review_required": self.requires_review,
            "impact": self.impact.value,
            "law_version_ids": list(self.law_version_ids),
            "learned_label": self.learned_label,
            "learned_label_safe": self.learned_label_safe,
            "metadata": _canonical_json_value(self.metadata),
            "proof_safe": self.proof_safe,
            "route": self.route.value,
            "selected_parse_id": self.selected_parse_id,
            "source_node_ids": list(self.source_node_ids),
            "source_spans": [span.to_dict() for span in self.source_spans],
            "span_ids": list(self.span_ids),
            "status": self.status.value,
            "unsupported_interpretations": [
                item.to_dict() for item in self.unsupported_interpretations
            ],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "LegalIRAmbiguity":
        return cls(
            ambiguity_id=str(data.get("ambiguity_id") or data.get("id") or ""),
            ambiguity_kind=_ambiguity_kind(data.get("ambiguity_kind") or data.get("kind")),
            status=_status(data.get("status")),
            confidence=_bounded_confidence(data.get("confidence")),
            impact=_impact(data.get("impact")),
            source_spans=tuple(
                LegalIRAmbiguitySourceSpan.from_dict(_mapping(item))
                for item in _sequence(data.get("source_spans"))
            ),
            competing_parses=tuple(
                LegalIRCompetingParse.from_dict(_mapping(item))
                for item in _sequence(data.get("competing_parses") or data.get("parse_candidates"))
            ),
            unsupported_interpretations=tuple(
                LegalIRCompetingParse.from_dict(_mapping(item))
                for item in _sequence(data.get("unsupported_interpretations"))
            ),
            selected_parse_id=str(data.get("selected_parse_id") or ""),
            human_review_required=bool(data.get("human_review_required")),
            human_review_reason=str(data.get("human_review_reason") or ""),
            source_node_ids=tuple(_strings(data.get("source_node_ids", ()))),
            span_ids=tuple(_strings(data.get("span_ids", ()))),
            authority_ids=tuple(_strings(data.get("authority_ids", ()))),
            law_version_ids=tuple(_strings(data.get("law_version_ids", ()))),
            citation_ids=tuple(_strings(data.get("citation_ids", ()))),
            learned_label=str(data.get("learned_label") or data.get("arbitrary_learned_label") or ""),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass(frozen=True)
class LegalIRAmbiguityReport:
    """Validated collection of first-class ambiguity records."""

    ambiguity_report_id: str
    ambiguities: tuple[LegalIRAmbiguity, ...] = ()
    diagnostics: tuple[LegalIRAmbiguityDiagnostic, ...] = ()
    schema_version: str = LEGAL_IR_AMBIGUITY_SCHEMA_VERSION
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def valid(self) -> bool:
        return not any(item.severity == "error" for item in self.diagnostics)

    @property
    def proof_safe(self) -> bool:
        return self.valid and all(item.proof_safe for item in self.ambiguities)

    @property
    def learned_target_safe(self) -> bool:
        return self.valid and all(item.learned_label_safe for item in self.ambiguities)

    @property
    def audit_required(self) -> bool:
        return any(
            ambiguity.route is LegalIRAmbiguityRoute.HAMMER_LEANSTRAL_AUDIT
            for ambiguity in self.ambiguities
        ) or any(
            diagnostic.route is LegalIRAmbiguityRoute.HAMMER_LEANSTRAL_AUDIT
            for diagnostic in self.diagnostics
        )

    @property
    def operator_diagnostics_required(self) -> bool:
        return any(
            ambiguity.route is LegalIRAmbiguityRoute.OPERATOR_DIAGNOSTIC
            for ambiguity in self.ambiguities
        ) or any(
            diagnostic.route is LegalIRAmbiguityRoute.OPERATOR_DIAGNOSTIC
            for diagnostic in self.diagnostics
        )

    @property
    def route(self) -> LegalIRAmbiguityRoute:
        if self.audit_required:
            return LegalIRAmbiguityRoute.HAMMER_LEANSTRAL_AUDIT
        if self.operator_diagnostics_required:
            return LegalIRAmbiguityRoute.OPERATOR_DIAGNOSTIC
        if not self.learned_target_safe:
            return LegalIRAmbiguityRoute.BLOCKED_FROM_LEARNED_TARGET
        if not self.proof_safe:
            return LegalIRAmbiguityRoute.BLOCKED_FROM_PROOF
        return LegalIRAmbiguityRoute.ALLOWED

    @property
    def ambiguity_ids(self) -> tuple[str, ...]:
        return tuple(item.ambiguity_id for item in self.ambiguities)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ambiguity_count": len(self.ambiguities),
            "ambiguity_ids": list(self.ambiguity_ids),
            "ambiguities": [item.to_dict() for item in self.ambiguities],
            "audit_required": self.audit_required,
            "diagnostics": [item.to_dict() for item in self.diagnostics],
            "learned_target_safe": self.learned_target_safe,
            "metadata": _canonical_json_value(self.metadata),
            "operator_diagnostics_required": self.operator_diagnostics_required,
            "proof_safe": self.proof_safe,
            "report_id": self.ambiguity_report_id,
            "route": self.route.value,
            "schema_version": self.schema_version,
            "valid": self.valid,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "LegalIRAmbiguityReport":
        return cls(
            ambiguity_report_id=str(data.get("report_id") or data.get("ambiguity_report_id") or ""),
            ambiguities=tuple(
                LegalIRAmbiguity.from_dict(_mapping(item))
                for item in _sequence(data.get("ambiguities"))
            ),
            diagnostics=tuple(
                LegalIRAmbiguityDiagnostic.from_dict(_mapping(item))
                for item in _sequence(data.get("diagnostics"))
            ),
            schema_version=str(data.get("schema_version") or LEGAL_IR_AMBIGUITY_SCHEMA_VERSION),
            metadata=dict(data.get("metadata") or {}),
        )


class LegalIRAmbiguityBuilder:
    """Builder for deterministic ambiguity reports."""

    def __init__(
        self,
        ambiguity_report_id: str = "",
        *,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        self.ambiguity_report_id = ambiguity_report_id
        self.metadata = dict(metadata or {})
        self._ambiguities: list[LegalIRAmbiguity] = []

    def add_ambiguity(
        self,
        ambiguity_id: str,
        ambiguity_kind: LegalIRAmbiguityKind | str = LegalIRAmbiguityKind.UNRESOLVED_AMBIGUITY,
        *,
        status: LegalIRAmbiguityStatus | str = LegalIRAmbiguityStatus.UNRESOLVED,
        confidence: float = 0.0,
        impact: LegalIRAmbiguityImpact | str = LegalIRAmbiguityImpact.MEDIUM,
        source_spans: Sequence[LegalIRAmbiguitySourceSpan | Mapping[str, Any]] = (),
        competing_parses: Sequence[LegalIRCompetingParse | Mapping[str, Any]] = (),
        unsupported_interpretations: Sequence[LegalIRCompetingParse | Mapping[str, Any]] = (),
        selected_parse_id: str = "",
        human_review_required: bool = False,
        human_review_reason: str = "",
        source_node_ids: Sequence[str] = (),
        span_ids: Sequence[str] = (),
        authority_ids: Sequence[str] = (),
        law_version_ids: Sequence[str] = (),
        citation_ids: Sequence[str] = (),
        learned_label: str = "",
        metadata: Mapping[str, Any] | None = None,
    ) -> LegalIRAmbiguity:
        ambiguity = LegalIRAmbiguity(
            ambiguity_id=ambiguity_id,
            ambiguity_kind=_ambiguity_kind(ambiguity_kind),
            status=_status(status),
            confidence=confidence,
            impact=_impact(impact),
            source_spans=tuple(_source_span(item) for item in source_spans),
            competing_parses=tuple(_parse_candidate(item) for item in competing_parses),
            unsupported_interpretations=tuple(
                _parse_candidate(item) for item in unsupported_interpretations
            ),
            selected_parse_id=selected_parse_id,
            human_review_required=human_review_required,
            human_review_reason=human_review_reason,
            source_node_ids=tuple(source_node_ids),
            span_ids=tuple(span_ids),
            authority_ids=tuple(authority_ids),
            law_version_ids=tuple(law_version_ids),
            citation_ids=tuple(citation_ids),
            learned_label=learned_label,
            metadata=dict(metadata or {}),
        )
        self._ambiguities.append(ambiguity)
        return ambiguity

    def add_competing_parse_ambiguity(
        self,
        ambiguity_id: str,
        parses: Sequence[LegalIRCompetingParse | Mapping[str, Any]],
        *,
        confidence: float = 0.0,
        impact: LegalIRAmbiguityImpact | str = LegalIRAmbiguityImpact.MEDIUM,
        **kwargs: Any,
    ) -> LegalIRAmbiguity:
        return self.add_ambiguity(
            ambiguity_id,
            LegalIRAmbiguityKind.COMPETING_PARSE,
            status=LegalIRAmbiguityStatus.COMPETING,
            confidence=confidence,
            impact=impact,
            competing_parses=parses,
            **kwargs,
        )

    def add_unsupported_interpretation(
        self,
        ambiguity_id: str,
        interpretation: LegalIRCompetingParse | Mapping[str, Any],
        *,
        confidence: float = 0.0,
        impact: LegalIRAmbiguityImpact | str = LegalIRAmbiguityImpact.MEDIUM,
        **kwargs: Any,
    ) -> LegalIRAmbiguity:
        return self.add_ambiguity(
            ambiguity_id,
            LegalIRAmbiguityKind.UNSUPPORTED_INTERPRETATION,
            status=LegalIRAmbiguityStatus.UNSUPPORTED,
            confidence=confidence,
            impact=impact,
            unsupported_interpretations=(_parse_candidate(interpretation),),
            **kwargs,
        )

    def to_report(self) -> LegalIRAmbiguityReport:
        return validate_legal_ir_ambiguities(
            tuple(self._ambiguities),
            ambiguity_report_id=self.ambiguity_report_id,
            metadata=self.metadata,
        )


def build_legal_ir_ambiguity_report(
    document_or_sample: Any,
    *,
    ambiguity_report_id: str = "",
    metadata: Mapping[str, Any] | None = None,
) -> LegalIRAmbiguityReport:
    """Build an ambiguity report from common LegalIR payload shapes."""

    payload = _payload_mapping(document_or_sample)
    rows = _ambiguity_rows(payload)
    ambiguities = tuple(LegalIRAmbiguity.from_dict(row) for row in rows)
    report_id = (
        ambiguity_report_id
        or str(payload.get("ambiguity_report_id") or payload.get("report_id") or "")
        or "legal-ir-ambiguity-" + _hash_json([item.to_dict() for item in ambiguities])[:24]
    )
    return validate_legal_ir_ambiguities(
        ambiguities,
        ambiguity_report_id=report_id,
        metadata=metadata or _mapping(payload.get("metadata")),
    )


def validate_legal_ir_ambiguities(
    ambiguities: Sequence[LegalIRAmbiguity | Mapping[str, Any]] | LegalIRAmbiguityReport | Mapping[str, Any],
    *,
    ambiguity_report_id: str = "",
    metadata: Mapping[str, Any] | None = None,
    low_confidence_threshold: float = DEFAULT_LOW_CONFIDENCE_THRESHOLD,
) -> LegalIRAmbiguityReport:
    """Validate ambiguity objects and attach fail-closed diagnostics."""

    if isinstance(ambiguities, LegalIRAmbiguityReport):
        rows = list(ambiguities.ambiguities)
        report_id = ambiguity_report_id or ambiguities.ambiguity_report_id
        report_metadata = dict(ambiguities.metadata)
        report_metadata.update(dict(metadata or {}))
    elif isinstance(ambiguities, Mapping):
        return build_legal_ir_ambiguity_report(
            ambiguities,
            ambiguity_report_id=ambiguity_report_id,
            metadata=metadata,
        )
    else:
        rows = [_ambiguity(item) for item in ambiguities]
        report_id = ambiguity_report_id
        report_metadata = dict(metadata or {})

    diagnostics: list[LegalIRAmbiguityDiagnostic] = []
    seen_ambiguity_ids: set[str] = set()
    for ambiguity in rows:
        span_ids = ambiguity.span_ids
        if not ambiguity.ambiguity_id:
            diagnostics.append(
                _diagnostic(
                    LegalIRAmbiguityDiagnosticType.AMBIGUITY_ID_MISSING,
                    "Ambiguity value is missing an ambiguity_id.",
                    ambiguity=ambiguity,
                )
            )
        elif ambiguity.ambiguity_id in seen_ambiguity_ids:
            diagnostics.append(
                _diagnostic(
                    LegalIRAmbiguityDiagnosticType.DUPLICATE_AMBIGUITY_ID,
                    f"Duplicate ambiguity_id {ambiguity.ambiguity_id!r}.",
                    ambiguity=ambiguity,
                )
            )
        seen_ambiguity_ids.add(ambiguity.ambiguity_id)

        if not span_ids and not ambiguity.source_spans:
            diagnostics.append(
                _diagnostic(
                    LegalIRAmbiguityDiagnosticType.SOURCE_SPAN_MISSING,
                    "Ambiguity must retain source span lineage.",
                    ambiguity=ambiguity,
                )
            )
        if ambiguity.confidence < low_confidence_threshold and ambiguity.unresolved:
            diagnostics.append(
                _diagnostic(
                    LegalIRAmbiguityDiagnosticType.LOW_CONFIDENCE,
                    "Unresolved ambiguity is below the configured confidence threshold.",
                    ambiguity=ambiguity,
                    severity="warning",
                )
            )
        if ambiguity.ambiguity_kind is LegalIRAmbiguityKind.COMPETING_PARSE and len(ambiguity.competing_parses) < 2:
            diagnostics.append(
                _diagnostic(
                    LegalIRAmbiguityDiagnosticType.COMPETING_PARSE_REQUIRED,
                    "Competing parse ambiguity must retain at least two candidates.",
                    ambiguity=ambiguity,
                )
            )
        if (
            ambiguity.competing_parses
            and ambiguity.status is not LegalIRAmbiguityStatus.RESOLVED
            and not ambiguity.selected_parse_id
        ):
            diagnostics.append(
                _diagnostic(
                    LegalIRAmbiguityDiagnosticType.COMPETING_PARSE_WITHOUT_CHOICE,
                    "Competing parses are unresolved and cannot be collapsed to one interpretation.",
                    ambiguity=ambiguity,
                    route=(
                        LegalIRAmbiguityRoute.HAMMER_LEANSTRAL_AUDIT
                        if ambiguity.high_impact
                        else LegalIRAmbiguityRoute.COMPILER_DIAGNOSTIC
                    ),
                )
            )
        if ambiguity.has_unsupported_interpretation:
            diagnostics.append(
                _diagnostic(
                    LegalIRAmbiguityDiagnosticType.UNSUPPORTED_INTERPRETATION_PRESENT,
                    "Unsupported interpretations must remain explicit diagnostics.",
                    ambiguity=ambiguity,
                    route=(
                        LegalIRAmbiguityRoute.HAMMER_LEANSTRAL_AUDIT
                        if ambiguity.high_impact
                        else LegalIRAmbiguityRoute.COMPILER_DIAGNOSTIC
                    ),
                )
            )
        if ambiguity.requires_review:
            diagnostics.append(
                _diagnostic(
                    LegalIRAmbiguityDiagnosticType.HUMAN_REVIEW_REQUIRED,
                    ambiguity.human_review_reason or "Ambiguity requires human review.",
                    ambiguity=ambiguity,
                    route=(
                        LegalIRAmbiguityRoute.HAMMER_LEANSTRAL_AUDIT
                        if ambiguity.high_impact
                        else LegalIRAmbiguityRoute.OPERATOR_DIAGNOSTIC
                    ),
                )
            )
        if ambiguity.high_impact and (ambiguity.unresolved or ambiguity.requires_review or ambiguity.has_unsupported_interpretation):
            diagnostics.append(
                _diagnostic(
                    LegalIRAmbiguityDiagnosticType.HIGH_IMPACT_AMBIGUITY,
                    "High-impact ambiguity requires Hammer/Leanstral audit.",
                    ambiguity=ambiguity,
                    route=LegalIRAmbiguityRoute.HAMMER_LEANSTRAL_AUDIT,
                )
            )
        if ambiguity.learned_label and not ambiguity.learned_label_safe:
            diagnostics.append(
                _diagnostic(
                    LegalIRAmbiguityDiagnosticType.LEARNED_LABEL_COLLAPSE_BLOCKED,
                    "Ambiguity cannot be collapsed into an arbitrary learned label.",
                    ambiguity=ambiguity,
                    route=LegalIRAmbiguityRoute.BLOCKED_FROM_LEARNED_TARGET,
                )
            )

        seen_parse_ids: set[str] = set()
        for candidate in (*ambiguity.competing_parses, *ambiguity.unsupported_interpretations):
            if not candidate.parse_id:
                diagnostics.append(
                    _diagnostic(
                        LegalIRAmbiguityDiagnosticType.PARSE_ID_MISSING,
                        "Parse candidate is missing parse_id.",
                        ambiguity=ambiguity,
                        parse_id=candidate.parse_id,
                    )
                )
            elif candidate.parse_id in seen_parse_ids:
                diagnostics.append(
                    _diagnostic(
                        LegalIRAmbiguityDiagnosticType.DUPLICATE_PARSE_ID,
                        f"Duplicate parse_id {candidate.parse_id!r}.",
                        ambiguity=ambiguity,
                        parse_id=candidate.parse_id,
                    )
                )
            seen_parse_ids.add(candidate.parse_id)

    report_payload = {
        "ambiguities": [item.to_dict() for item in rows],
        "diagnostics": [item.to_dict() for item in diagnostics],
        "schema": LEGAL_IR_AMBIGUITY_SCHEMA_VERSION,
    }
    return LegalIRAmbiguityReport(
        ambiguity_report_id=report_id or "legal-ir-ambiguity-" + _hash_json(report_payload)[:24],
        ambiguities=tuple(rows),
        diagnostics=tuple(_dedupe_diagnostics(diagnostics)),
        metadata=report_metadata,
    )


def legal_ir_ambiguity_allowed_for_use(
    ambiguities: Sequence[LegalIRAmbiguity | Mapping[str, Any]] | LegalIRAmbiguityReport | Mapping[str, Any],
    *,
    artifact_use: LegalIRAmbiguityUse | str = LegalIRAmbiguityUse.PROOF_TARGET,
) -> bool:
    """Return whether ambiguity records can feed the requested artifact use."""

    report = _report(ambiguities)
    use = _use(artifact_use)
    if use in {LegalIRAmbiguityUse.COMPILER, LegalIRAmbiguityUse.DIAGNOSTIC}:
        return report.valid or bool(report.diagnostics)
    if use is LegalIRAmbiguityUse.LEARNED_TARGET:
        return report.learned_target_safe
    return report.proof_safe


def assert_legal_ir_ambiguity_resolved(
    ambiguities: Sequence[LegalIRAmbiguity | Mapping[str, Any]] | LegalIRAmbiguityReport | Mapping[str, Any],
    *,
    artifact_use: LegalIRAmbiguityUse | str = LegalIRAmbiguityUse.PROOF_TARGET,
) -> LegalIRAmbiguityReport:
    """Raise if ambiguity is not safe for proof or learned-target use."""

    report = _report(ambiguities)
    if not legal_ir_ambiguity_allowed_for_use(report, artifact_use=artifact_use):
        codes = ",".join(item.code for item in report.diagnostics) or "legal_ir_ambiguity_unresolved"
        raise ValueError(f"LegalIR ambiguity is not safe for {str(artifact_use)}: {codes}")
    return report


def route_legal_ir_ambiguity(
    ambiguities: Sequence[LegalIRAmbiguity | Mapping[str, Any]] | LegalIRAmbiguityReport | Mapping[str, Any],
) -> dict[str, Any]:
    """Return deterministic Leanstral/operator routing for ambiguity records."""

    report = _report(ambiguities)
    audit: list[dict[str, Any]] = []
    operator: list[dict[str, Any]] = []
    compiler: list[dict[str, Any]] = []
    blocked_learned: list[dict[str, Any]] = []
    blocked_proof: list[dict[str, Any]] = []
    for ambiguity in report.ambiguities:
        item = ambiguity.to_dict()
        if ambiguity.route is LegalIRAmbiguityRoute.HAMMER_LEANSTRAL_AUDIT:
            audit.append(item)
        elif ambiguity.route is LegalIRAmbiguityRoute.OPERATOR_DIAGNOSTIC:
            operator.append(item)
        elif not ambiguity.learned_label_safe:
            blocked_learned.append(item)
        elif not ambiguity.proof_safe:
            blocked_proof.append(item)
        elif ambiguity.route is LegalIRAmbiguityRoute.COMPILER_DIAGNOSTIC:
            compiler.append(item)
    return {
        "audit_ambiguities": audit,
        "audit_count": len(audit),
        "blocked_learned_target_ambiguities": blocked_learned,
        "blocked_learned_target_count": len(blocked_learned),
        "blocked_proof_ambiguities": blocked_proof,
        "blocked_proof_count": len(blocked_proof),
        "compiler_diagnostics": compiler,
        "compiler_diagnostic_count": len(compiler),
        "operator_diagnostics": operator,
        "operator_diagnostic_count": len(operator),
        "report": report.to_dict(),
        "route": report.route.value,
        "schema_version": LEGAL_IR_AMBIGUITY_SCHEMA_VERSION,
    }


def ambiguity_guidance_observation(ambiguity: LegalIRAmbiguity | Mapping[str, Any]) -> dict[str, Any]:
    """Project ambiguity into a learned-guidance uncertainty observation."""

    item = _ambiguity(ambiguity)
    family = _family_from_ambiguity(item)
    return {
        "abstained": True,
        "ambiguity_id": item.ambiguity_id,
        "calibrated_confidence": 0.0 if item.unresolved else item.confidence,
        "calibration_error": 1.0 if not item.learned_label_safe else 0.0,
        "confidence": 0.0 if not item.learned_label_safe else item.confidence,
        "evidence_sources": ("legal_ir_ambiguity",),
        "guidance_id": item.ambiguity_id,
        "legal_ir_ambiguity": True,
        "legal_ir_family": family,
        "normalized_entropy": 1.0 if item.competing_parses or item.unresolved else 0.0,
        "out_of_distribution": True,
        "source": "legal_ir_ambiguity",
        "unsupported_family_signal": not item.learned_label_safe,
    }


def _family_from_ambiguity(ambiguity: LegalIRAmbiguity) -> str:
    candidates = [item.target_view for item in ambiguity.competing_parses]
    candidates.extend(item.target_view for item in ambiguity.unsupported_interpretations)
    for value in candidates:
        text = str(value or "").strip()
        if text:
            return text
    return str(ambiguity.metadata.get("legal_ir_family") or "deontic")


def _report(value: Any) -> LegalIRAmbiguityReport:
    if isinstance(value, LegalIRAmbiguityReport):
        return validate_legal_ir_ambiguities(value)
    if isinstance(value, Mapping):
        return build_legal_ir_ambiguity_report(value)
    return validate_legal_ir_ambiguities(value)


def _diagnostic(
    diagnostic_type: LegalIRAmbiguityDiagnosticType,
    message: str,
    *,
    ambiguity: LegalIRAmbiguity,
    parse_id: str = "",
    severity: str = "error",
    route: LegalIRAmbiguityRoute | None = None,
) -> LegalIRAmbiguityDiagnostic:
    return LegalIRAmbiguityDiagnostic(
        diagnostic_type=diagnostic_type,
        message=message,
        severity=severity,
        ambiguity_id=ambiguity.ambiguity_id,
        parse_id=parse_id,
        route=route or ambiguity.route,
        span_ids=ambiguity.span_ids,
        source_node_ids=ambiguity.source_node_ids,
        confidence=ambiguity.confidence,
    )


def _dedupe_diagnostics(
    diagnostics: Sequence[LegalIRAmbiguityDiagnostic],
) -> list[LegalIRAmbiguityDiagnostic]:
    seen: set[tuple[str, str, str, str]] = set()
    result: list[LegalIRAmbiguityDiagnostic] = []
    for diagnostic in diagnostics:
        key = (
            diagnostic.code,
            diagnostic.ambiguity_id,
            diagnostic.parse_id,
            diagnostic.message,
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(diagnostic)
    return result


def _ambiguity_rows(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    nested = payload.get("ambiguities")
    if nested is None:
        nested = payload.get("legal_ir_ambiguities")
    if nested is None:
        nested = payload.get("ambiguity_records")
    if nested is not None:
        return [_mapping(item) for item in _sequence(nested)]
    if "ambiguity_id" in payload or "ambiguity_kind" in payload:
        return [payload]
    document = _mapping(payload.get("modal_ir") or payload.get("document"))
    if document:
        return _ambiguity_rows(document)
    return []


def _ambiguity(value: LegalIRAmbiguity | Mapping[str, Any]) -> LegalIRAmbiguity:
    if isinstance(value, LegalIRAmbiguity):
        return value
    return LegalIRAmbiguity.from_dict(_mapping(value))


def _source_span(value: LegalIRAmbiguitySourceSpan | Mapping[str, Any]) -> LegalIRAmbiguitySourceSpan:
    if isinstance(value, LegalIRAmbiguitySourceSpan):
        return value
    return LegalIRAmbiguitySourceSpan.from_dict(_mapping(value))


def _parse_candidate(value: LegalIRCompetingParse | Mapping[str, Any]) -> LegalIRCompetingParse:
    if isinstance(value, LegalIRCompetingParse):
        return value
    return LegalIRCompetingParse.from_dict(_mapping(value))


def _ambiguity_kind(value: Any) -> LegalIRAmbiguityKind:
    if isinstance(value, LegalIRAmbiguityKind):
        return value
    text = str(value or "").strip()
    if not text:
        return LegalIRAmbiguityKind.UNRESOLVED_AMBIGUITY
    try:
        return LegalIRAmbiguityKind(text)
    except ValueError:
        normalized = text.lower().replace("-", "_")
        aliases = {
            "ambiguous": LegalIRAmbiguityKind.UNRESOLVED_AMBIGUITY,
            "parse_conflict": LegalIRAmbiguityKind.COMPETING_PARSE,
            "competing_parses": LegalIRAmbiguityKind.COMPETING_PARSE,
            "unsupported": LegalIRAmbiguityKind.UNSUPPORTED_INTERPRETATION,
            "human_review": LegalIRAmbiguityKind.REQUIRED_HUMAN_REVIEW,
        }
        return aliases.get(normalized, LegalIRAmbiguityKind.UNRESOLVED_AMBIGUITY)


def _status(value: Any) -> LegalIRAmbiguityStatus:
    if isinstance(value, LegalIRAmbiguityStatus):
        return value
    text = str(value or "").strip()
    if not text:
        return LegalIRAmbiguityStatus.UNRESOLVED
    try:
        return LegalIRAmbiguityStatus(text)
    except ValueError:
        normalized = text.lower().replace("-", "_")
        aliases = {
            "ambiguous": LegalIRAmbiguityStatus.UNRESOLVED,
            "requires_review": LegalIRAmbiguityStatus.REVIEW_REQUIRED,
            "human_review_required": LegalIRAmbiguityStatus.REVIEW_REQUIRED,
            "unsupported_interpretation": LegalIRAmbiguityStatus.UNSUPPORTED,
        }
        return aliases.get(normalized, LegalIRAmbiguityStatus.UNRESOLVED)


def _impact(value: Any) -> LegalIRAmbiguityImpact:
    if isinstance(value, LegalIRAmbiguityImpact):
        return value
    text = str(value or "").strip()
    if not text:
        return LegalIRAmbiguityImpact.MEDIUM
    try:
        return LegalIRAmbiguityImpact(text)
    except ValueError:
        normalized = text.lower().replace("-", "_")
        if normalized in {"p0", "severe", "material"}:
            return LegalIRAmbiguityImpact.HIGH
        return LegalIRAmbiguityImpact.MEDIUM


def _route(value: Any) -> LegalIRAmbiguityRoute:
    if isinstance(value, LegalIRAmbiguityRoute):
        return value
    text = str(value or "").strip()
    if not text:
        return LegalIRAmbiguityRoute.COMPILER_DIAGNOSTIC
    try:
        return LegalIRAmbiguityRoute(text)
    except ValueError:
        return LegalIRAmbiguityRoute.COMPILER_DIAGNOSTIC


def _use(value: Any) -> LegalIRAmbiguityUse:
    if isinstance(value, LegalIRAmbiguityUse):
        return value
    try:
        return LegalIRAmbiguityUse(str(value))
    except ValueError:
        return LegalIRAmbiguityUse.PROOF_TARGET


def _diagnostic_type(value: Any) -> LegalIRAmbiguityDiagnosticType:
    if isinstance(value, LegalIRAmbiguityDiagnosticType):
        return value
    try:
        return LegalIRAmbiguityDiagnosticType(str(value))
    except ValueError:
        return LegalIRAmbiguityDiagnosticType.SOURCE_SPAN_MISSING


def _bounded_confidence(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(number):
        return 0.0
    return max(0.0, min(1.0, number))


def _payload_mapping(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        mapped = to_dict()
        if isinstance(mapped, Mapping):
            return mapped
    if hasattr(value, "__dict__"):
        return vars(value)
    return {}


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _sequence(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return list(value)
    return [value]


def _strings(value: Any) -> list[str]:
    return [str(item).strip() for item in _sequence(value) if str(item).strip()]


def _unique(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _canonical_json_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _canonical_json_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_canonical_json_value(item) for item in value]
    if isinstance(value, Enum):
        return value.value
    return value


def _hash_json(value: Any) -> str:
    payload = json.dumps(
        value,
        default=str,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


__all__ = [
    "LEGAL_IR_AMBIGUITY_SCHEMA_VERSION",
    "DEFAULT_HIGH_IMPACT_CONFIDENCE_THRESHOLD",
    "DEFAULT_LOW_CONFIDENCE_THRESHOLD",
    "LegalIRAmbiguity",
    "LegalIRAmbiguityBuilder",
    "LegalIRAmbiguityDiagnostic",
    "LegalIRAmbiguityDiagnosticType",
    "LegalIRAmbiguityImpact",
    "LegalIRAmbiguityKind",
    "LegalIRAmbiguityReport",
    "LegalIRAmbiguityRoute",
    "LegalIRAmbiguitySourceSpan",
    "LegalIRAmbiguityStatus",
    "LegalIRAmbiguityUse",
    "LegalIRCompetingParse",
    "ambiguity_guidance_observation",
    "assert_legal_ir_ambiguity_resolved",
    "build_legal_ir_ambiguity_report",
    "legal_ir_ambiguity_allowed_for_use",
    "route_legal_ir_ambiguity",
    "validate_legal_ir_ambiguities",
]
