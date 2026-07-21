"""Temporal authority model for LegalIR.

Legal conclusions are only valid inside an authority, jurisdiction, and time
window.  This module models those scopes explicitly: effective and sunset dates,
amendments, repeals, supersession, emergency rules, jurisdictional reach, and
authority hierarchy.  Applicability queries return typed decisions rather than
silently treating stale or lower-authority law as current proof material.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Any, Final

from .legal_ir_citations import (
    LegalIRCitationGraph,
    LegalIRCitationTarget,
    normalize_legal_citation,
)


LEGAL_IR_TEMPORAL_AUTHORITY_SCHEMA_VERSION: Final = "legal-ir-temporal-authority-v1"


class LegalIRTemporalChangeKind(str, Enum):
    """Change events that alter the legal effect of a law version."""

    ENACTMENT = "enactment"
    EFFECTIVE = "effective"
    AMENDMENT = "amendment"
    REPEAL = "repeal"
    SUPERSESSION = "supersession"
    SUNSET = "sunset"
    EMERGENCY_EFFECTIVE = "emergency_effective"
    EMERGENCY_EXPIRATION = "emergency_expiration"


class LegalIRTemporalApplicabilityStatus(str, Enum):
    """Applicability decision for one law version in one query context."""

    APPLICABLE = "applicable"
    NOT_YET_EFFECTIVE = "not_yet_effective"
    EXPIRED = "expired"
    REPEALED = "repealed"
    SUPERSEDED = "superseded"
    WRONG_JURISDICTION = "wrong_jurisdiction"
    AUTHORITY_PREEMPTED = "authority_preempted"
    EMERGENCY_EXPIRED = "emergency_expired"
    UNRESOLVED_AUTHORITY = "unresolved_authority"


class LegalIRTemporalDiagnosticType(str, Enum):
    """Typed diagnostics for temporal authority graphs and queries."""

    AUTHORITY_MISSING = "authority_missing"
    DUPLICATE_AUTHORITY_ID = "duplicate_authority_id"
    DUPLICATE_LAW_VERSION_ID = "duplicate_law_version_id"
    DUPLICATE_CHANGE_ID = "duplicate_change_id"
    EFFECTIVE_DATE_MISSING = "effective_date_missing"
    INVALID_DATE = "invalid_date"
    WINDOW_END_BEFORE_START = "window_end_before_start"
    CHANGE_TARGET_MISSING = "change_target_missing"
    CHANGE_REPLACEMENT_MISSING = "change_replacement_missing"
    REPEALED_LAW_USED = "repealed_law_used"
    SUPERSEDED_LAW_USED = "superseded_law_used"
    EXPIRED_LAW_USED = "expired_law_used"
    NOT_YET_EFFECTIVE_LAW_USED = "not_yet_effective_law_used"
    WRONG_JURISDICTION = "wrong_jurisdiction"
    LOWER_AUTHORITY_PREEMPTED = "lower_authority_preempted"
    EMERGENCY_RULE_EXPIRED = "emergency_rule_expired"
    TEMPORAL_QUERY_DATE_MISSING = "temporal_query_date_missing"
    TEMPORAL_CONTEXT_MISSING = "temporal_context_missing"


@dataclass(frozen=True)
class LegalIRAuthorityNode:
    """One node in an authority hierarchy."""

    authority_id: str
    name: str = ""
    jurisdiction: str = ""
    authority_type: str = ""
    hierarchy_rank: int = 0
    parent_authority_ids: tuple[str, ...] = ()
    version: str = ""
    source_uri: str = ""
    emergency_power: bool = False
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority_id": self.authority_id,
            "authority_type": self.authority_type,
            "emergency_power": bool(self.emergency_power),
            "hierarchy_rank": int(self.hierarchy_rank),
            "jurisdiction": self.jurisdiction,
            "metadata": _canonical_json_value(self.metadata),
            "name": self.name,
            "parent_authority_ids": list(self.parent_authority_ids),
            "source_uri": self.source_uri,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "LegalIRAuthorityNode":
        return cls(
            authority_id=str(data.get("authority_id") or ""),
            name=str(data.get("name") or data.get("authority_id") or ""),
            jurisdiction=str(data.get("jurisdiction") or ""),
            authority_type=str(data.get("authority_type") or data.get("type") or ""),
            hierarchy_rank=int(data.get("hierarchy_rank") if data.get("hierarchy_rank") is not None else data.get("rank") or 0),
            parent_authority_ids=tuple(_unique(_strings(data.get("parent_authority_ids", ())))),
            version=str(data.get("version") or ""),
            source_uri=str(data.get("source_uri") or ""),
            emergency_power=bool(data.get("emergency_power")),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass(frozen=True)
class LegalIRTemporalWindow:
    """Date window in which a law version can have legal effect."""

    effective_date: str = ""
    sunset_date: str = ""
    repeal_date: str = ""
    superseded_date: str = ""
    emergency_expires_on: str = ""

    @property
    def end_date(self) -> str:
        dates = [
            item
            for item in (
                self.sunset_date,
                self.repeal_date,
                self.superseded_date,
                self.emergency_expires_on,
            )
            if item
        ]
        if not dates:
            return ""
        parsed = sorted((_parse_date(item), item) for item in dates if _parse_date(item) is not None)
        return parsed[0][1] if parsed else ""

    def contains(self, query_date: date) -> bool:
        start = _parse_date(self.effective_date)
        if start is not None and query_date < start:
            return False
        end = _parse_date(self.end_date)
        if end is not None and query_date >= end:
            return False
        return True

    def to_dict(self) -> dict[str, str]:
        return {
            "effective_date": self.effective_date,
            "emergency_expires_on": self.emergency_expires_on,
            "repeal_date": self.repeal_date,
            "sunset_date": self.sunset_date,
            "superseded_date": self.superseded_date,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "LegalIRTemporalWindow":
        return cls(
            effective_date=_date_text(data.get("effective_date") or data.get("effective_on")),
            sunset_date=_date_text(data.get("sunset_date") or data.get("sunsets_on")),
            repeal_date=_date_text(data.get("repeal_date") or data.get("repealed_on")),
            superseded_date=_date_text(data.get("superseded_date") or data.get("superseded_on")),
            emergency_expires_on=_date_text(data.get("emergency_expires_on") or data.get("emergency_expiration_date")),
        )


@dataclass(frozen=True)
class LegalIRLawVersion:
    """One time-scoped legal rule, section, regulation, or factual authority."""

    law_version_id: str
    canonical_citation: str
    authority_id: str
    jurisdiction: str = ""
    version: str = ""
    temporal_window: LegalIRTemporalWindow = field(default_factory=LegalIRTemporalWindow)
    emergency: bool = False
    amended_by: tuple[str, ...] = ()
    amends: tuple[str, ...] = ()
    repealed_by: str = ""
    superseded_by: str = ""
    supersedes: tuple[str, ...] = ()
    source_node_ids: tuple[str, ...] = ()
    span_ids: tuple[str, ...] = ()
    citation_target_id: str = ""
    formula_ids: tuple[str, ...] = ()
    conclusion_kinds: tuple[str, ...] = ()
    conflict_key: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def effective_date(self) -> str:
        return self.temporal_window.effective_date

    @property
    def sunset_date(self) -> str:
        return self.temporal_window.sunset_date

    @property
    def repeal_date(self) -> str:
        return self.temporal_window.repeal_date

    @property
    def superseded_date(self) -> str:
        return self.temporal_window.superseded_date

    @property
    def emergency_expires_on(self) -> str:
        return self.temporal_window.emergency_expires_on

    @property
    def active_without_query(self) -> bool:
        return not (self.repealed_by or self.superseded_by or self.repeal_date or self.superseded_date)

    @property
    def applicability_key(self) -> str:
        return self.conflict_key or self.canonical_citation or self.citation_target_id or self.law_version_id

    def to_dict(self) -> dict[str, Any]:
        return {
            "amended_by": list(self.amended_by),
            "amends": list(self.amends),
            "authority_id": self.authority_id,
            "canonical_citation": self.canonical_citation,
            "citation_target_id": self.citation_target_id,
            "conclusion_kinds": list(self.conclusion_kinds),
            "conflict_key": self.conflict_key,
            "emergency": bool(self.emergency),
            "formula_ids": list(self.formula_ids),
            "jurisdiction": self.jurisdiction,
            "law_version_id": self.law_version_id,
            "metadata": _canonical_json_value(self.metadata),
            "repealed_by": self.repealed_by,
            "source_node_ids": list(self.source_node_ids),
            "span_ids": list(self.span_ids),
            "superseded_by": self.superseded_by,
            "supersedes": list(self.supersedes),
            "temporal_window": self.temporal_window.to_dict(),
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "LegalIRLawVersion":
        window_data = data.get("temporal_window")
        window = (
            LegalIRTemporalWindow.from_dict(_mapping(window_data))
            if isinstance(window_data, Mapping)
            else LegalIRTemporalWindow.from_dict(data)
        )
        citation = str(data.get("canonical_citation") or data.get("citation") or "")
        authority_id = str(data.get("authority_id") or "")
        canonical = normalize_legal_citation(citation, default_authority=authority_id)
        payload = {
            "authority_id": authority_id,
            "citation": canonical,
            "effective_date": window.effective_date,
            "version": data.get("version") or "",
        }
        return cls(
            law_version_id=str(data.get("law_version_id") or data.get("target_id") or f"lir-law-version-{_stable_hash(payload)[:24]}"),
            canonical_citation=canonical,
            authority_id=authority_id,
            jurisdiction=str(data.get("jurisdiction") or ""),
            version=str(data.get("version") or ""),
            temporal_window=window,
            emergency=bool(data.get("emergency") or data.get("emergency_rule")),
            amended_by=tuple(_unique(_strings(data.get("amended_by", ())))),
            amends=tuple(_unique(_strings(data.get("amends", ())))),
            repealed_by=str(data.get("repealed_by") or ""),
            superseded_by=str(data.get("superseded_by") or ""),
            supersedes=tuple(_unique(_strings(data.get("supersedes", ())))),
            source_node_ids=tuple(_unique(_strings(data.get("source_node_ids", ())))),
            span_ids=tuple(_unique(_strings(data.get("span_ids", ())))),
            citation_target_id=str(data.get("citation_target_id") or data.get("target_id") or ""),
            formula_ids=tuple(_unique(_strings(data.get("formula_ids", ())))),
            conclusion_kinds=tuple(_unique(_atom(item) for item in _strings(data.get("conclusion_kinds", ())))),
            conflict_key=str(data.get("conflict_key") or ""),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass(frozen=True)
class LegalIRTemporalChange:
    """One amendment, repeal, supersession, or emergency lifecycle event."""

    change_id: str
    change_kind: LegalIRTemporalChangeKind
    target_law_version_id: str
    effective_date: str
    authority_id: str = ""
    enacted_date: str = ""
    replacement_law_version_id: str = ""
    jurisdiction: str = ""
    source_node_ids: tuple[str, ...] = ()
    span_ids: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority_id": self.authority_id,
            "change_id": self.change_id,
            "change_kind": self.change_kind.value,
            "effective_date": self.effective_date,
            "enacted_date": self.enacted_date,
            "jurisdiction": self.jurisdiction,
            "metadata": _canonical_json_value(self.metadata),
            "replacement_law_version_id": self.replacement_law_version_id,
            "source_node_ids": list(self.source_node_ids),
            "span_ids": list(self.span_ids),
            "target_law_version_id": self.target_law_version_id,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "LegalIRTemporalChange":
        kind = _change_kind(data.get("change_kind") or data.get("kind"))
        target_id = str(data.get("target_law_version_id") or data.get("target_id") or "")
        effective = _date_text(data.get("effective_date") or data.get("effective_on"))
        payload = {
            "effective_date": effective,
            "kind": kind.value,
            "replacement": data.get("replacement_law_version_id") or "",
            "target": target_id,
        }
        return cls(
            change_id=str(data.get("change_id") or f"lir-temporal-change-{_stable_hash(payload)[:24]}"),
            change_kind=kind,
            target_law_version_id=target_id,
            effective_date=effective,
            authority_id=str(data.get("authority_id") or ""),
            enacted_date=_date_text(data.get("enacted_date") or data.get("enacted_on")),
            replacement_law_version_id=str(data.get("replacement_law_version_id") or data.get("replacement_id") or ""),
            jurisdiction=str(data.get("jurisdiction") or ""),
            source_node_ids=tuple(_unique(_strings(data.get("source_node_ids", ())))),
            span_ids=tuple(_unique(_strings(data.get("span_ids", ())))),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass(frozen=True)
class LegalIRTemporalQueryContext:
    """Context used to decide whether a conclusion can rely on law."""

    query_date: str
    jurisdiction: str = ""
    authority_id: str = ""
    citation: str = ""
    law_version_ids: tuple[str, ...] = ()
    formula_id: str = ""
    conclusion_kind: str = ""
    include_emergency_rules: bool = True
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def canonical_citation(self) -> str:
        return normalize_legal_citation(self.citation, default_authority=self.authority_id)

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority_id": self.authority_id,
            "canonical_citation": self.canonical_citation,
            "citation": self.citation,
            "conclusion_kind": self.conclusion_kind,
            "formula_id": self.formula_id,
            "include_emergency_rules": bool(self.include_emergency_rules),
            "jurisdiction": self.jurisdiction,
            "law_version_ids": list(self.law_version_ids),
            "metadata": _canonical_json_value(self.metadata),
            "query_date": self.query_date,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "LegalIRTemporalQueryContext":
        return cls(
            query_date=_date_text(data.get("query_date") or data.get("as_of") or data.get("date")),
            jurisdiction=str(data.get("jurisdiction") or ""),
            authority_id=str(data.get("authority_id") or ""),
            citation=str(data.get("citation") or data.get("canonical_citation") or ""),
            law_version_ids=tuple(_unique(_strings(data.get("law_version_ids", ())))),
            formula_id=str(data.get("formula_id") or ""),
            conclusion_kind=_atom(data.get("conclusion_kind") or data.get("kind") or "", fallback=""),
            include_emergency_rules=bool(data.get("include_emergency_rules", True)),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass(frozen=True)
class LegalIRTemporalDiagnostic:
    """One typed temporal authority diagnostic."""

    diagnostic_type: LegalIRTemporalDiagnosticType
    message: str
    severity: str = "error"
    law_version_id: str = ""
    authority_id: str = ""
    change_id: str = ""
    formula_id: str = ""
    source_node_ids: tuple[str, ...] = ()
    field_path: str = ""

    @property
    def code(self) -> str:
        return self.diagnostic_type.value

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority_id": self.authority_id,
            "change_id": self.change_id,
            "code": self.code,
            "diagnostic_type": self.diagnostic_type.value,
            "field_path": self.field_path,
            "formula_id": self.formula_id,
            "law_version_id": self.law_version_id,
            "message": self.message,
            "severity": self.severity,
            "source_node_ids": list(self.source_node_ids),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "LegalIRTemporalDiagnostic":
        return cls(
            diagnostic_type=_diagnostic_type(data.get("diagnostic_type") or data.get("code")),
            message=str(data.get("message") or ""),
            severity=str(data.get("severity") or "error"),
            law_version_id=str(data.get("law_version_id") or ""),
            authority_id=str(data.get("authority_id") or ""),
            change_id=str(data.get("change_id") or ""),
            formula_id=str(data.get("formula_id") or ""),
            source_node_ids=tuple(_unique(_strings(data.get("source_node_ids", ())))),
            field_path=str(data.get("field_path") or ""),
        )


@dataclass(frozen=True)
class LegalIRTemporalDecision:
    """Decision for one law version under a temporal query."""

    law_version_id: str
    status: LegalIRTemporalApplicabilityStatus
    query_date: str = ""
    authority_id: str = ""
    jurisdiction: str = ""
    canonical_citation: str = ""
    effective_date: str = ""
    end_date: str = ""
    hierarchy_rank: int = 0
    diagnostics: tuple[LegalIRTemporalDiagnostic, ...] = ()

    @property
    def applicable(self) -> bool:
        return self.status is LegalIRTemporalApplicabilityStatus.APPLICABLE

    @property
    def diagnostic_types(self) -> tuple[LegalIRTemporalDiagnosticType, ...]:
        return tuple(item.diagnostic_type for item in self.diagnostics)

    def to_dict(self) -> dict[str, Any]:
        return {
            "applicable": self.applicable,
            "authority_id": self.authority_id,
            "canonical_citation": self.canonical_citation,
            "diagnostic_types": [item.value for item in self.diagnostic_types],
            "diagnostics": [item.to_dict() for item in self.diagnostics],
            "effective_date": self.effective_date,
            "end_date": self.end_date,
            "hierarchy_rank": int(self.hierarchy_rank),
            "jurisdiction": self.jurisdiction,
            "law_version_id": self.law_version_id,
            "query_date": self.query_date,
            "status": self.status.value,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "LegalIRTemporalDecision":
        return cls(
            law_version_id=str(data.get("law_version_id") or ""),
            status=_applicability_status(data.get("status")),
            query_date=_date_text(data.get("query_date")),
            authority_id=str(data.get("authority_id") or ""),
            jurisdiction=str(data.get("jurisdiction") or ""),
            canonical_citation=str(data.get("canonical_citation") or ""),
            effective_date=_date_text(data.get("effective_date")),
            end_date=_date_text(data.get("end_date")),
            hierarchy_rank=int(data.get("hierarchy_rank") or 0),
            diagnostics=tuple(LegalIRTemporalDiagnostic.from_dict(_mapping(item)) for item in data.get("diagnostics", []) or []),
        )


@dataclass(frozen=True)
class LegalIRTemporalApplicability:
    """Result of applying a temporal query to a graph."""

    query_context: LegalIRTemporalQueryContext
    decisions: tuple[LegalIRTemporalDecision, ...]
    diagnostics: tuple[LegalIRTemporalDiagnostic, ...] = ()
    schema_version: str = LEGAL_IR_TEMPORAL_AUTHORITY_SCHEMA_VERSION

    @property
    def applicable_law_version_ids(self) -> tuple[str, ...]:
        return tuple(decision.law_version_id for decision in self.decisions if decision.applicable)

    @property
    def excluded_law_version_ids(self) -> tuple[str, ...]:
        return tuple(decision.law_version_id for decision in self.decisions if not decision.applicable)

    @property
    def proof_safe(self) -> bool:
        applicable = tuple(decision for decision in self.decisions if decision.applicable)
        return bool(applicable) and not any(
            diagnostic.severity == "error"
            for decision in applicable
            for diagnostic in decision.diagnostics
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "applicable_law_version_ids": list(self.applicable_law_version_ids),
            "decisions": [decision.to_dict() for decision in self.decisions],
            "diagnostics": [diagnostic.to_dict() for diagnostic in self.diagnostics],
            "excluded_law_version_ids": list(self.excluded_law_version_ids),
            "proof_safe": self.proof_safe,
            "query_context": self.query_context.to_dict(),
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True)
class LegalIRTemporalAuthorityValidationResult:
    """Validation result for a temporal authority graph."""

    temporal_authority_graph_id: str
    authority_count: int
    law_version_count: int
    change_count: int
    diagnostics: tuple[LegalIRTemporalDiagnostic, ...] = ()
    schema_version: str = LEGAL_IR_TEMPORAL_AUTHORITY_SCHEMA_VERSION

    @property
    def valid(self) -> bool:
        return not any(diagnostic.severity == "error" for diagnostic in self.diagnostics)

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority_count": int(self.authority_count),
            "change_count": int(self.change_count),
            "diagnostics": [diagnostic.to_dict() for diagnostic in self.diagnostics],
            "law_version_count": int(self.law_version_count),
            "schema_version": self.schema_version,
            "temporal_authority_graph_id": self.temporal_authority_graph_id,
            "valid": self.valid,
        }


@dataclass(frozen=True)
class LegalIRTemporalAuthorityGraph:
    """Immutable authority and lifecycle graph for LegalIR law versions."""

    temporal_authority_graph_id: str
    authorities: tuple[LegalIRAuthorityNode, ...]
    law_versions: tuple[LegalIRLawVersion, ...]
    changes: tuple[LegalIRTemporalChange, ...] = ()
    source_map_id: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = LEGAL_IR_TEMPORAL_AUTHORITY_SCHEMA_VERSION

    @property
    def authority_by_id(self) -> Mapping[str, LegalIRAuthorityNode]:
        return {authority.authority_id: authority for authority in self.authorities}

    @property
    def law_version_by_id(self) -> Mapping[str, LegalIRLawVersion]:
        return {law.law_version_id: law for law in self.law_versions}

    @property
    def change_by_id(self) -> Mapping[str, LegalIRTemporalChange]:
        return {change.change_id: change for change in self.changes}

    def to_dict(self) -> dict[str, Any]:
        return {
            "authorities": [authority.to_dict() for authority in self.authorities],
            "changes": [change.to_dict() for change in self.changes],
            "law_versions": [law.to_dict() for law in self.law_versions],
            "metadata": _canonical_json_value(self.metadata),
            "schema_version": self.schema_version,
            "source_map_id": self.source_map_id,
            "temporal_authority_graph_id": self.temporal_authority_graph_id,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "LegalIRTemporalAuthorityGraph":
        return cls(
            temporal_authority_graph_id=str(data.get("temporal_authority_graph_id") or data.get("graph_id") or ""),
            authorities=tuple(LegalIRAuthorityNode.from_dict(_mapping(item)) for item in data.get("authorities", []) or []),
            law_versions=tuple(LegalIRLawVersion.from_dict(_mapping(item)) for item in data.get("law_versions", []) or []),
            changes=tuple(LegalIRTemporalChange.from_dict(_mapping(item)) for item in data.get("changes", []) or []),
            source_map_id=str(data.get("source_map_id") or ""),
            metadata=dict(data.get("metadata") or {}),
            schema_version=str(data.get("schema_version") or LEGAL_IR_TEMPORAL_AUTHORITY_SCHEMA_VERSION),
        )


class LegalIRTemporalAuthorityGraphBuilder:
    """Mutable builder for authority, amendment, repeal, and temporal scope."""

    def __init__(
        self,
        *,
        temporal_authority_graph_id: str = "",
        source_map_id: str = "",
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        self.temporal_authority_graph_id = temporal_authority_graph_id
        self.source_map_id = source_map_id
        self.metadata = dict(metadata or {})
        self._authorities: dict[str, LegalIRAuthorityNode] = {}
        self._law_versions: dict[str, LegalIRLawVersion] = {}
        self._changes: dict[str, LegalIRTemporalChange] = {}

    def add_authority(
        self,
        authority_id: str,
        *,
        name: str = "",
        jurisdiction: str = "",
        authority_type: str = "",
        hierarchy_rank: int | None = None,
        rank: int | None = None,
        parent_authority_ids: Sequence[str] = (),
        version: str = "",
        source_uri: str = "",
        emergency_power: bool = False,
        metadata: Mapping[str, Any] | None = None,
    ) -> LegalIRAuthorityNode:
        resolved_rank = hierarchy_rank if hierarchy_rank is not None else rank if rank is not None else 0
        authority = LegalIRAuthorityNode(
            authority_id=str(authority_id or ""),
            name=str(name or authority_id or ""),
            jurisdiction=str(jurisdiction or ""),
            authority_type=str(authority_type or ""),
            hierarchy_rank=int(resolved_rank or 0),
            parent_authority_ids=tuple(_unique(_strings(parent_authority_ids))),
            version=str(version or ""),
            source_uri=str(source_uri or ""),
            emergency_power=bool(emergency_power),
            metadata=dict(metadata or {}),
        )
        self._authorities[authority.authority_id] = authority
        return authority

    def add_law_version(
        self,
        citation: str,
        *,
        law_version_id: str = "",
        authority_id: str = "",
        jurisdiction: str = "",
        version: str = "",
        effective_date: Any = "",
        sunset_date: Any = "",
        repeal_date: Any = "",
        superseded_date: Any = "",
        emergency: bool = False,
        emergency_expires_on: Any = "",
        amended_by: Sequence[str] = (),
        amends: Sequence[str] = (),
        repealed_by: str = "",
        superseded_by: str = "",
        supersedes: Sequence[str] = (),
        source_node_ids: Sequence[str] = (),
        span_ids: Sequence[str] = (),
        citation_target_id: str = "",
        formula_ids: Sequence[str] = (),
        conclusion_kinds: Sequence[str] = (),
        conflict_key: str = "",
        metadata: Mapping[str, Any] | None = None,
    ) -> LegalIRLawVersion:
        canonical = normalize_legal_citation(citation, default_authority=authority_id)
        window = LegalIRTemporalWindow(
            effective_date=_date_text(effective_date),
            sunset_date=_date_text(sunset_date),
            repeal_date=_date_text(repeal_date),
            superseded_date=_date_text(superseded_date),
            emergency_expires_on=_date_text(emergency_expires_on),
        )
        payload = {
            "authority_id": authority_id,
            "citation": canonical,
            "effective_date": window.effective_date,
            "target": citation_target_id,
            "version": version,
        }
        law = LegalIRLawVersion(
            law_version_id=str(law_version_id or f"lir-law-version-{_stable_hash(payload)[:24]}"),
            canonical_citation=canonical,
            authority_id=str(authority_id or ""),
            jurisdiction=str(jurisdiction or ""),
            version=str(version or ""),
            temporal_window=window,
            emergency=bool(emergency),
            amended_by=tuple(_unique(_strings(amended_by))),
            amends=tuple(_unique(_strings(amends))),
            repealed_by=str(repealed_by or ""),
            superseded_by=str(superseded_by or ""),
            supersedes=tuple(_unique(_strings(supersedes))),
            source_node_ids=tuple(_unique(_strings(source_node_ids))),
            span_ids=tuple(_unique(_strings(span_ids))),
            citation_target_id=str(citation_target_id or ""),
            formula_ids=tuple(_unique(_strings(formula_ids))),
            conclusion_kinds=tuple(_unique(_atom(item) for item in _strings(conclusion_kinds))),
            conflict_key=str(conflict_key or canonical),
            metadata=dict(metadata or {}),
        )
        self._law_versions[law.law_version_id] = law
        if law.authority_id and law.authority_id not in self._authorities:
            self.add_authority(
                law.authority_id,
                name=law.authority_id,
                jurisdiction=law.jurisdiction,
                version=law.version,
                metadata={"inferred": True},
            )
        return law

    def add_change(
        self,
        change_kind: LegalIRTemporalChangeKind | str,
        target_law_version_id: str,
        *,
        change_id: str = "",
        effective_date: Any = "",
        authority_id: str = "",
        enacted_date: Any = "",
        replacement_law_version_id: str = "",
        jurisdiction: str = "",
        source_node_ids: Sequence[str] = (),
        span_ids: Sequence[str] = (),
        metadata: Mapping[str, Any] | None = None,
    ) -> LegalIRTemporalChange:
        kind = _change_kind(change_kind)
        effective = _date_text(effective_date)
        payload = {
            "effective_date": effective,
            "kind": kind.value,
            "replacement": replacement_law_version_id,
            "target": target_law_version_id,
        }
        change = LegalIRTemporalChange(
            change_id=str(change_id or f"lir-temporal-change-{_stable_hash(payload)[:24]}"),
            change_kind=kind,
            target_law_version_id=str(target_law_version_id or ""),
            effective_date=effective,
            authority_id=str(authority_id or ""),
            enacted_date=_date_text(enacted_date),
            replacement_law_version_id=str(replacement_law_version_id or ""),
            jurisdiction=str(jurisdiction or ""),
            source_node_ids=tuple(_unique(_strings(source_node_ids))),
            span_ids=tuple(_unique(_strings(span_ids))),
            metadata=dict(metadata or {}),
        )
        self._changes[change.change_id] = change
        self._apply_change_to_law(change)
        return change

    def add_amendment(
        self,
        target_law_version_id: str,
        replacement_law_version_id: str,
        *,
        effective_date: Any,
        change_id: str = "",
        authority_id: str = "",
        enacted_date: Any = "",
        metadata: Mapping[str, Any] | None = None,
    ) -> LegalIRTemporalChange:
        return self.add_change(
            LegalIRTemporalChangeKind.AMENDMENT,
            target_law_version_id,
            change_id=change_id,
            effective_date=effective_date,
            authority_id=authority_id,
            enacted_date=enacted_date,
            replacement_law_version_id=replacement_law_version_id,
            metadata=metadata,
        )

    def add_repeal(
        self,
        target_law_version_id: str,
        *,
        effective_date: Any,
        change_id: str = "",
        authority_id: str = "",
        enacted_date: Any = "",
        metadata: Mapping[str, Any] | None = None,
    ) -> LegalIRTemporalChange:
        return self.add_change(
            LegalIRTemporalChangeKind.REPEAL,
            target_law_version_id,
            change_id=change_id,
            effective_date=effective_date,
            authority_id=authority_id,
            enacted_date=enacted_date,
            metadata=metadata,
        )

    def add_supersession(
        self,
        target_law_version_id: str,
        replacement_law_version_id: str,
        *,
        effective_date: Any,
        change_id: str = "",
        authority_id: str = "",
        enacted_date: Any = "",
        metadata: Mapping[str, Any] | None = None,
    ) -> LegalIRTemporalChange:
        return self.add_change(
            LegalIRTemporalChangeKind.SUPERSESSION,
            target_law_version_id,
            change_id=change_id,
            effective_date=effective_date,
            authority_id=authority_id,
            enacted_date=enacted_date,
            replacement_law_version_id=replacement_law_version_id,
            metadata=metadata,
        )

    def to_temporal_authority_graph(self) -> LegalIRTemporalAuthorityGraph:
        graph_id = self.temporal_authority_graph_id or "lir-temporal-authority-graph-" + _stable_hash(
            {
                "authorities": sorted(self._authorities),
                "changes": sorted(self._changes),
                "law_versions": sorted(self._law_versions),
            }
        )[:24]
        return LegalIRTemporalAuthorityGraph(
            temporal_authority_graph_id=graph_id,
            authorities=tuple(self._authorities[key] for key in sorted(self._authorities)),
            law_versions=tuple(self._law_versions[key] for key in sorted(self._law_versions)),
            changes=tuple(self._changes[key] for key in sorted(self._changes)),
            source_map_id=self.source_map_id,
            metadata=dict(self.metadata),
        )

    def _apply_change_to_law(self, change: LegalIRTemporalChange) -> None:
        law = self._law_versions.get(change.target_law_version_id)
        if law is None:
            return
        window = law.temporal_window
        if change.change_kind is LegalIRTemporalChangeKind.REPEAL:
            window = LegalIRTemporalWindow(
                effective_date=window.effective_date,
                sunset_date=window.sunset_date,
                repeal_date=change.effective_date or window.repeal_date,
                superseded_date=window.superseded_date,
                emergency_expires_on=window.emergency_expires_on,
            )
            law = _replace_law(law, temporal_window=window, repealed_by=change.change_id)
        elif change.change_kind in {LegalIRTemporalChangeKind.AMENDMENT, LegalIRTemporalChangeKind.SUPERSESSION}:
            window = LegalIRTemporalWindow(
                effective_date=window.effective_date,
                sunset_date=window.sunset_date,
                repeal_date=window.repeal_date,
                superseded_date=change.effective_date or window.superseded_date,
                emergency_expires_on=window.emergency_expires_on,
            )
            law = _replace_law(
                law,
                temporal_window=window,
                amended_by=(*law.amended_by, change.change_id) if change.change_kind is LegalIRTemporalChangeKind.AMENDMENT else law.amended_by,
                superseded_by=change.replacement_law_version_id or change.change_id,
            )
        elif change.change_kind is LegalIRTemporalChangeKind.SUNSET:
            window = LegalIRTemporalWindow(
                effective_date=window.effective_date,
                sunset_date=change.effective_date or window.sunset_date,
                repeal_date=window.repeal_date,
                superseded_date=window.superseded_date,
                emergency_expires_on=window.emergency_expires_on,
            )
            law = _replace_law(law, temporal_window=window)
        elif change.change_kind is LegalIRTemporalChangeKind.EMERGENCY_EXPIRATION:
            window = LegalIRTemporalWindow(
                effective_date=window.effective_date,
                sunset_date=window.sunset_date,
                repeal_date=window.repeal_date,
                superseded_date=window.superseded_date,
                emergency_expires_on=change.effective_date or window.emergency_expires_on,
            )
            law = _replace_law(law, temporal_window=window)
        self._law_versions[law.law_version_id] = law


LegalIRTemporalAuthorityBuilder = LegalIRTemporalAuthorityGraphBuilder


def query_legal_ir_temporal_applicability(
    temporal_authority_graph: LegalIRTemporalAuthorityGraph | Mapping[str, Any],
    query_context: LegalIRTemporalQueryContext | Mapping[str, Any],
) -> LegalIRTemporalApplicability:
    """Evaluate which law versions apply under an authority and time context."""

    graph = _temporal_authority_graph(temporal_authority_graph)
    context = _query_context(query_context)
    query_date = _parse_date(context.query_date)
    diagnostics: list[LegalIRTemporalDiagnostic] = []
    if query_date is None:
        diagnostics.append(
            _diagnostic(
                LegalIRTemporalDiagnosticType.TEMPORAL_QUERY_DATE_MISSING,
                "Temporal query context has no valid query date.",
                formula_id=context.formula_id,
                field_path="query_context.query_date",
            )
        )
        return LegalIRTemporalApplicability(context, (), tuple(diagnostics))

    candidates = tuple(_candidate_law_versions(graph, context))
    decisions = [_decision_for_law(graph, law, context, query_date) for law in candidates]
    decisions = _apply_authority_preemption(graph, decisions)
    diagnostics.extend(issue for decision in decisions for issue in decision.diagnostics)
    return LegalIRTemporalApplicability(
        query_context=context,
        decisions=tuple(decisions),
        diagnostics=tuple(_dedupe_diagnostics(diagnostics)),
    )


def validate_legal_ir_temporal_authority_graph(
    temporal_authority_graph: LegalIRTemporalAuthorityGraph | Mapping[str, Any],
) -> LegalIRTemporalAuthorityValidationResult:
    """Validate authority references, lifecycle windows, and change targets."""

    graph = _temporal_authority_graph(temporal_authority_graph)
    diagnostics: list[LegalIRTemporalDiagnostic] = []
    authority_ids = [authority.authority_id for authority in graph.authorities]
    law_ids = [law.law_version_id for law in graph.law_versions]
    change_ids = [change.change_id for change in graph.changes]
    _duplicate_diagnostics("authority", authority_ids, diagnostics, LegalIRTemporalDiagnosticType.DUPLICATE_AUTHORITY_ID)
    _duplicate_diagnostics("law_version", law_ids, diagnostics, LegalIRTemporalDiagnosticType.DUPLICATE_LAW_VERSION_ID)
    _duplicate_diagnostics("change", change_ids, diagnostics, LegalIRTemporalDiagnosticType.DUPLICATE_CHANGE_ID)
    authorities = graph.authority_by_id
    laws = graph.law_version_by_id

    for law in graph.law_versions:
        if not law.authority_id or law.authority_id not in authorities:
            diagnostics.append(
                _diagnostic(
                    LegalIRTemporalDiagnosticType.AUTHORITY_MISSING,
                    "Law version references a missing authority.",
                    law_version_id=law.law_version_id,
                    authority_id=law.authority_id,
                    source_node_ids=law.source_node_ids,
                    field_path=f"law_versions.{law.law_version_id}.authority_id",
                )
            )
        if not law.effective_date:
            diagnostics.append(
                _diagnostic(
                    LegalIRTemporalDiagnosticType.EFFECTIVE_DATE_MISSING,
                    "Law version has no effective date.",
                    law_version_id=law.law_version_id,
                    authority_id=law.authority_id,
                    source_node_ids=law.source_node_ids,
                    field_path=f"law_versions.{law.law_version_id}.temporal_window.effective_date",
                )
            )
        for field_name, value in law.temporal_window.to_dict().items():
            if value and _parse_date(value) is None:
                diagnostics.append(
                    _diagnostic(
                        LegalIRTemporalDiagnosticType.INVALID_DATE,
                        "Law version contains an invalid date.",
                        law_version_id=law.law_version_id,
                        authority_id=law.authority_id,
                        field_path=f"law_versions.{law.law_version_id}.temporal_window.{field_name}",
                    )
                )
        start = _parse_date(law.effective_date)
        end = _parse_date(law.temporal_window.end_date)
        if start is not None and end is not None and end < start:
            diagnostics.append(
                _diagnostic(
                    LegalIRTemporalDiagnosticType.WINDOW_END_BEFORE_START,
                    "Law version window ends before it starts.",
                    law_version_id=law.law_version_id,
                    authority_id=law.authority_id,
                    field_path=f"law_versions.{law.law_version_id}.temporal_window",
                )
            )

    for change in graph.changes:
        if change.target_law_version_id not in laws:
            diagnostics.append(
                _diagnostic(
                    LegalIRTemporalDiagnosticType.CHANGE_TARGET_MISSING,
                    "Temporal change points at a missing law version.",
                    change_id=change.change_id,
                    law_version_id=change.target_law_version_id,
                    authority_id=change.authority_id,
                    source_node_ids=change.source_node_ids,
                    field_path=f"changes.{change.change_id}.target_law_version_id",
                )
            )
        if change.change_kind in {LegalIRTemporalChangeKind.AMENDMENT, LegalIRTemporalChangeKind.SUPERSESSION} and change.replacement_law_version_id not in laws:
            diagnostics.append(
                _diagnostic(
                    LegalIRTemporalDiagnosticType.CHANGE_REPLACEMENT_MISSING,
                    "Amendment or supersession points at a missing replacement law version.",
                    change_id=change.change_id,
                    law_version_id=change.replacement_law_version_id,
                    authority_id=change.authority_id,
                    source_node_ids=change.source_node_ids,
                    field_path=f"changes.{change.change_id}.replacement_law_version_id",
                )
            )
        if change.effective_date and _parse_date(change.effective_date) is None:
            diagnostics.append(
                _diagnostic(
                    LegalIRTemporalDiagnosticType.INVALID_DATE,
                    "Temporal change has an invalid effective date.",
                    change_id=change.change_id,
                    authority_id=change.authority_id,
                    field_path=f"changes.{change.change_id}.effective_date",
                )
            )

    return LegalIRTemporalAuthorityValidationResult(
        temporal_authority_graph_id=graph.temporal_authority_graph_id,
        authority_count=len(graph.authorities),
        law_version_count=len(graph.law_versions),
        change_count=len(graph.changes),
        diagnostics=tuple(_dedupe_diagnostics(diagnostics)),
    )


def legal_ir_temporal_authority_allowed_for_use(
    applicability: LegalIRTemporalApplicability | Mapping[str, Any],
) -> bool:
    """Return whether this temporal decision can feed proof or learned targets."""

    result = _applicability(applicability)
    return result.proof_safe


def assert_legal_ir_temporal_authority_applicable(
    applicability: LegalIRTemporalApplicability | Mapping[str, Any],
) -> LegalIRTemporalApplicability:
    """Raise if a conclusion has no valid temporal authority support."""

    result = _applicability(applicability)
    if not result.proof_safe:
        codes = ",".join(issue.code for issue in result.diagnostics) or "temporal_authority_not_applicable"
        raise ValueError(f"LegalIR temporal authority is not proof-safe: {codes}")
    return result


def build_legal_ir_temporal_authority_graph(
    document_or_sample: Mapping[str, Any] | Any,
    *,
    citation_graph: LegalIRCitationGraph | Mapping[str, Any] | None = None,
) -> LegalIRTemporalAuthorityGraph:
    """Build a temporal authority graph from common LegalIR document shapes."""

    sample = _payload_mapping(document_or_sample)
    document = _mapping(sample.get("modal_ir") or sample.get("document") or sample)
    document_id = str(document.get("document_id") or sample.get("document_id") or sample.get("sample_id") or "legal-ir-document")
    authority_payload = _mapping(document.get("authority") or sample.get("authority"))
    authority_id = str(authority_payload.get("authority_id") or document.get("authority_id") or sample.get("authority_id") or "")
    jurisdiction = str(authority_payload.get("jurisdiction") or document.get("jurisdiction") or sample.get("jurisdiction") or "")
    version = str(authority_payload.get("version") or document.get("version") or sample.get("version") or "")
    builder = LegalIRTemporalAuthorityGraphBuilder(
        metadata={"builder": "build_legal_ir_temporal_authority_graph", "document_id": document_id}
    )

    for payload in _sequence(document.get("authorities") or sample.get("authorities")):
        item = _mapping(payload)
        item_id = str(item.get("authority_id") or "")
        if item_id:
            builder.add_authority(
                item_id,
                name=str(item.get("name") or item_id),
                jurisdiction=str(item.get("jurisdiction") or ""),
                authority_type=str(item.get("authority_type") or item.get("type") or ""),
                hierarchy_rank=int(item.get("hierarchy_rank") if item.get("hierarchy_rank") is not None else item.get("rank") or 0),
                parent_authority_ids=_strings(item.get("parent_authority_ids", ())),
                version=str(item.get("version") or ""),
                source_uri=str(item.get("source_uri") or ""),
                emergency_power=bool(item.get("emergency_power")),
                metadata={key: value for key, value in item.items() if key not in {"authority_id", "name"}},
            )

    if authority_id:
        builder.add_authority(
            authority_id,
            name=str(authority_payload.get("name") or authority_id),
            jurisdiction=jurisdiction,
            authority_type=str(authority_payload.get("authority_type") or authority_payload.get("type") or ""),
            hierarchy_rank=int(authority_payload.get("hierarchy_rank") if authority_payload.get("hierarchy_rank") is not None else authority_payload.get("rank") or 0),
            parent_authority_ids=_strings(authority_payload.get("parent_authority_ids", ())),
            version=str(authority_payload.get("version") or version),
            source_uri=str(authority_payload.get("source_uri") or ""),
            emergency_power=bool(authority_payload.get("emergency_power")),
        )

    graph = _citation_graph_or_none(citation_graph)
    if graph is not None:
        for authority in graph.authorities:
            if authority.authority_id not in builder._authorities:
                builder.add_authority(
                    authority.authority_id,
                    name=authority.name,
                    jurisdiction=authority.jurisdiction,
                    authority_type=authority.authority_type,
                    hierarchy_rank=authority.rank,
                    version=authority.version,
                    source_uri=authority.source_uri,
                    metadata=authority.metadata,
                )
        for target in graph.targets:
            payload = dict(target.metadata or {})
            if not _has_temporal_payload(payload):
                continue
            _add_law_from_payload(
                builder,
                {
                    **payload,
                    "authority_id": payload.get("authority_id") or target.authority_id,
                    "citation": payload.get("citation") or target.canonical_citation,
                    "citation_target_id": target.target_id,
                    "jurisdiction": payload.get("jurisdiction") or _authority_jurisdiction(builder, target.authority_id),
                    "law_version_id": payload.get("law_version_id") or target.target_id,
                    "source_node_ids": payload.get("source_node_ids") or target.source_node_ids,
                    "span_ids": payload.get("span_ids") or target.span_ids,
                    "version": payload.get("version") or target.version,
                },
                default_authority_id=target.authority_id,
                default_jurisdiction=_authority_jurisdiction(builder, target.authority_id),
                default_version=target.version,
            )

    for item in _sequence(document.get("law_versions") or document.get("temporal_authorities") or document.get("temporal_authority")):
        _add_law_from_payload(
            builder,
            _mapping(item),
            default_authority_id=authority_id,
            default_jurisdiction=jurisdiction,
            default_version=version,
        )

    for item in _sequence(document.get("citation_targets") or document.get("targets") or document.get("sections")):
        payload = _mapping(item)
        if _has_temporal_payload(payload):
            _add_law_from_payload(
                builder,
                payload,
                default_authority_id=authority_id,
                default_jurisdiction=jurisdiction,
                default_version=version,
            )

    for index, formula in enumerate(_sequence(document.get("formulas")), start=1):
        formula_payload = _mapping(formula)
        authority_context = _mapping(formula_payload.get("authority_context") or formula_payload.get("temporal_authority"))
        if not authority_context and not _has_temporal_payload(formula_payload):
            continue
        formula_id = str(formula_payload.get("formula_id") or f"formula-{index}")
        provenance = _mapping(formula_payload.get("provenance"))
        citation = str(
            authority_context.get("citation")
            or formula_payload.get("citation")
            or provenance.get("citation")
            or document.get("citation")
            or ""
        )
        conclusion_kind = _atom(
            authority_context.get("conclusion_kind")
            or formula_payload.get("conclusion_kind")
            or _mapping(formula_payload.get("predicate")).get("role")
            or _mapping(formula_payload.get("operator")).get("family")
            or "",
            fallback="",
        )
        _add_law_from_payload(
            builder,
            {
                **formula_payload,
                **authority_context,
                "citation": citation,
                "formula_ids": [formula_id],
                "law_version_id": authority_context.get("law_version_id") or formula_payload.get("law_version_id") or f"law:{formula_id}",
                "conclusion_kinds": _strings(authority_context.get("conclusion_kinds", ())) or ([conclusion_kind] if conclusion_kind else []),
                "source_node_ids": _source_node_ids(formula_payload) or (formula_id,),
            },
            default_authority_id=str(authority_context.get("authority_id") or authority_id),
            default_jurisdiction=str(authority_context.get("jurisdiction") or jurisdiction),
            default_version=str(authority_context.get("version") or version),
        )

    for item in _sequence(document.get("changes") or document.get("temporal_changes") or document.get("amendments")):
        payload = _mapping(item)
        kind = payload.get("change_kind") or payload.get("kind") or (
            LegalIRTemporalChangeKind.AMENDMENT.value if payload.get("replacement_law_version_id") or payload.get("amends") else ""
        )
        if kind:
            builder.add_change(
                kind,
                str(payload.get("target_law_version_id") or payload.get("target_id") or payload.get("amends") or ""),
                change_id=str(payload.get("change_id") or ""),
                effective_date=payload.get("effective_date") or payload.get("effective_on"),
                authority_id=str(payload.get("authority_id") or authority_id),
                enacted_date=payload.get("enacted_date") or payload.get("enacted_on"),
                replacement_law_version_id=str(payload.get("replacement_law_version_id") or payload.get("replacement_id") or ""),
                jurisdiction=str(payload.get("jurisdiction") or jurisdiction),
                source_node_ids=_source_node_ids(payload),
                span_ids=_strings(payload.get("span_ids", ())),
                metadata={key: value for key, value in payload.items() if key not in {"change_id", "target_law_version_id"}},
            )

    return builder.to_temporal_authority_graph()


def generate_legal_ir_temporal_authority_obligation_specs(
    document_or_sample: Mapping[str, Any] | Any,
) -> list[dict[str, Any]]:
    """Return obligation specs proving conclusions use applicable authority."""

    graph = build_legal_ir_temporal_authority_graph(document_or_sample)
    if not graph.law_versions:
        return []
    sample = _payload_mapping(document_or_sample)
    document = _mapping(sample.get("modal_ir") or sample.get("document") or sample)
    sample_id = str(sample.get("sample_id") or document.get("document_id") or "legal-ir-sample")
    query_defaults = _mapping(document.get("temporal_query_context") or sample.get("temporal_query_context"))
    default_query_date = _date_text(query_defaults.get("query_date") or query_defaults.get("as_of") or document.get("query_date") or sample.get("query_date"))
    default_jurisdiction = str(query_defaults.get("jurisdiction") or document.get("jurisdiction") or sample.get("jurisdiction") or "")
    specs: list[dict[str, Any]] = []

    for law in graph.law_versions:
        formula_ids = law.formula_ids or ("document",)
        for formula_id in formula_ids:
            kind = _conclusion_kind_for_law(law)
            query = LegalIRTemporalQueryContext(
                query_date=default_query_date or law.effective_date,
                jurisdiction=default_jurisdiction or law.jurisdiction,
                authority_id=law.authority_id,
                citation=law.canonical_citation,
                law_version_ids=(law.law_version_id,),
                formula_id=formula_id,
                conclusion_kind=kind,
            )
            applicability = query_legal_ir_temporal_applicability(graph, query)
            applicable = law.law_version_id in applicability.applicable_law_version_ids
            status = (
                "applicable"
                if applicable
                else applicability.decisions[0].status.value if applicability.decisions else "unresolved"
            )
            family = "deontic" if kind in {"deontic", "obligation", "permission", "prohibition"} else "temporal"
            obligation_kind = (
                "temporal_authority_deontic_scope"
                if family == "deontic"
                else "temporal_authority_factual_scope"
            )
            statement = (
                f"law_scoped_conclusion(formula:{_atom(formula_id)}, "
                f"law:{_atom(law.law_version_id)}, authority:{_atom(law.authority_id)}, "
                f"jurisdiction:{_atom(query.jurisdiction or law.jurisdiction)}, "
                f"date:{query.query_date}, status:{status}, kind:{kind or 'factual'})"
            )
            specs.append(
                {
                    "formula_id": formula_id,
                    "kind": obligation_kind,
                    "legal_ir_view": "temporal_authority.ir",
                    "logic_family": family,
                    "metadata": {
                        "applicability_status": status,
                        "applicable_law_version_ids": list(applicability.applicable_law_version_ids),
                        "authority_id": law.authority_id,
                        "canonical_citation": law.canonical_citation,
                        "conclusion_kind": kind,
                        "diagnostic_types": [issue.code for issue in applicability.diagnostics],
                        "effective_date": law.effective_date,
                        "emergency_rule": law.emergency,
                        "jurisdiction": query.jurisdiction or law.jurisdiction,
                        "law_version_id": law.law_version_id,
                        "obligation_family": "temporal_authority_scope",
                        "query_date": query.query_date,
                        "schema_version": LEGAL_IR_TEMPORAL_AUTHORITY_SCHEMA_VERSION,
                        "sunset_date": law.sunset_date,
                        "temporal_authority_graph_id": graph.temporal_authority_graph_id,
                    },
                    "premise_hints": (
                        "temporal_authority_window_applies",
                        "authority_hierarchy_preempts_lower_rank",
                        "deontic_and_factual_conclusions_are_time_scoped",
                    ),
                    "sample_id": sample_id,
                    "statement": statement,
                }
            )
    return specs


def _decision_for_law(
    graph: LegalIRTemporalAuthorityGraph,
    law: LegalIRLawVersion,
    context: LegalIRTemporalQueryContext,
    query_date: date,
) -> LegalIRTemporalDecision:
    authority = graph.authority_by_id.get(law.authority_id)
    diagnostics: list[LegalIRTemporalDiagnostic] = []
    jurisdiction = law.jurisdiction or (authority.jurisdiction if authority else "")
    rank = authority.hierarchy_rank if authority else 0
    status = LegalIRTemporalApplicabilityStatus.APPLICABLE

    if authority is None:
        diagnostics.append(_diagnostic(LegalIRTemporalDiagnosticType.AUTHORITY_MISSING, "Applicable law has no resolved authority.", law_version_id=law.law_version_id, authority_id=law.authority_id, source_node_ids=law.source_node_ids))
        status = LegalIRTemporalApplicabilityStatus.UNRESOLVED_AUTHORITY
    elif context.jurisdiction and not _jurisdiction_matches(context.jurisdiction, jurisdiction):
        diagnostics.append(_diagnostic(LegalIRTemporalDiagnosticType.WRONG_JURISDICTION, "Law version does not apply in the query jurisdiction.", law_version_id=law.law_version_id, authority_id=law.authority_id, formula_id=context.formula_id, source_node_ids=law.source_node_ids))
        status = LegalIRTemporalApplicabilityStatus.WRONG_JURISDICTION
    elif law.emergency and not context.include_emergency_rules:
        diagnostics.append(_diagnostic(LegalIRTemporalDiagnosticType.EMERGENCY_RULE_EXPIRED, "Emergency rule is excluded by the query context.", law_version_id=law.law_version_id, authority_id=law.authority_id, formula_id=context.formula_id, source_node_ids=law.source_node_ids))
        status = LegalIRTemporalApplicabilityStatus.EMERGENCY_EXPIRED
    elif _parse_date(law.effective_date) is not None and query_date < _parse_date(law.effective_date):  # type: ignore[arg-type]
        diagnostics.append(_diagnostic(LegalIRTemporalDiagnosticType.NOT_YET_EFFECTIVE_LAW_USED, "Law version is not effective at the query date.", law_version_id=law.law_version_id, authority_id=law.authority_id, formula_id=context.formula_id, source_node_ids=law.source_node_ids))
        status = LegalIRTemporalApplicabilityStatus.NOT_YET_EFFECTIVE
    elif law.repeal_date and _parse_date(law.repeal_date) is not None and query_date >= _parse_date(law.repeal_date):  # type: ignore[arg-type]
        diagnostics.append(_diagnostic(LegalIRTemporalDiagnosticType.REPEALED_LAW_USED, "Law version was repealed before the query date.", law_version_id=law.law_version_id, authority_id=law.authority_id, formula_id=context.formula_id, source_node_ids=law.source_node_ids))
        status = LegalIRTemporalApplicabilityStatus.REPEALED
    elif law.superseded_date and _parse_date(law.superseded_date) is not None and query_date >= _parse_date(law.superseded_date):  # type: ignore[arg-type]
        diagnostics.append(_diagnostic(LegalIRTemporalDiagnosticType.SUPERSEDED_LAW_USED, "Law version was superseded before the query date.", law_version_id=law.law_version_id, authority_id=law.authority_id, formula_id=context.formula_id, source_node_ids=law.source_node_ids))
        status = LegalIRTemporalApplicabilityStatus.SUPERSEDED
    elif law.emergency and law.emergency_expires_on and _parse_date(law.emergency_expires_on) is not None and query_date >= _parse_date(law.emergency_expires_on):  # type: ignore[arg-type]
        diagnostics.append(_diagnostic(LegalIRTemporalDiagnosticType.EMERGENCY_RULE_EXPIRED, "Emergency rule expired before the query date.", law_version_id=law.law_version_id, authority_id=law.authority_id, formula_id=context.formula_id, source_node_ids=law.source_node_ids))
        status = LegalIRTemporalApplicabilityStatus.EMERGENCY_EXPIRED
    elif law.sunset_date and _parse_date(law.sunset_date) is not None and query_date >= _parse_date(law.sunset_date):  # type: ignore[arg-type]
        diagnostics.append(_diagnostic(LegalIRTemporalDiagnosticType.EXPIRED_LAW_USED, "Law version sunset before the query date.", law_version_id=law.law_version_id, authority_id=law.authority_id, formula_id=context.formula_id, source_node_ids=law.source_node_ids))
        status = LegalIRTemporalApplicabilityStatus.EXPIRED

    return LegalIRTemporalDecision(
        law_version_id=law.law_version_id,
        status=status,
        query_date=context.query_date,
        authority_id=law.authority_id,
        jurisdiction=jurisdiction,
        canonical_citation=law.canonical_citation,
        effective_date=law.effective_date,
        end_date=law.temporal_window.end_date,
        hierarchy_rank=rank,
        diagnostics=tuple(diagnostics),
    )


def _apply_authority_preemption(
    graph: LegalIRTemporalAuthorityGraph,
    decisions: Sequence[LegalIRTemporalDecision],
) -> list[LegalIRTemporalDecision]:
    by_key: dict[str, list[LegalIRTemporalDecision]] = {}
    laws = graph.law_version_by_id
    for decision in decisions:
        if decision.status is not LegalIRTemporalApplicabilityStatus.APPLICABLE:
            continue
        law = laws.get(decision.law_version_id)
        key = law.applicability_key if law else decision.canonical_citation
        by_key.setdefault(key, []).append(decision)

    replacements: dict[str, LegalIRTemporalDecision] = {}
    for grouped in by_key.values():
        if len(grouped) <= 1:
            continue
        max_rank = max(item.hierarchy_rank for item in grouped)
        for decision in grouped:
            if decision.hierarchy_rank >= max_rank:
                continue
            diagnostic = _diagnostic(
                LegalIRTemporalDiagnosticType.LOWER_AUTHORITY_PREEMPTED,
                "A higher ranked authority controls this query context.",
                law_version_id=decision.law_version_id,
                authority_id=decision.authority_id,
            )
            replacements[decision.law_version_id] = LegalIRTemporalDecision(
                law_version_id=decision.law_version_id,
                status=LegalIRTemporalApplicabilityStatus.AUTHORITY_PREEMPTED,
                query_date=decision.query_date,
                authority_id=decision.authority_id,
                jurisdiction=decision.jurisdiction,
                canonical_citation=decision.canonical_citation,
                effective_date=decision.effective_date,
                end_date=decision.end_date,
                hierarchy_rank=decision.hierarchy_rank,
                diagnostics=(*decision.diagnostics, diagnostic),
            )
    return [replacements.get(decision.law_version_id, decision) for decision in decisions]


def _candidate_law_versions(
    graph: LegalIRTemporalAuthorityGraph,
    context: LegalIRTemporalQueryContext,
) -> tuple[LegalIRLawVersion, ...]:
    laws = graph.law_versions
    if context.law_version_ids:
        wanted = set(context.law_version_ids)
        laws = tuple(law for law in laws if law.law_version_id in wanted)
    if context.formula_id:
        scoped = tuple(law for law in laws if not law.formula_ids or context.formula_id in law.formula_ids)
        laws = scoped or laws
    if context.canonical_citation:
        laws = tuple(law for law in laws if law.canonical_citation == context.canonical_citation)
    if context.authority_id:
        laws = tuple(law for law in laws if law.authority_id == context.authority_id)
    if context.conclusion_kind:
        laws = tuple(
            law
            for law in laws
            if not law.conclusion_kinds or context.conclusion_kind in law.conclusion_kinds
        )
    return laws


def _add_law_from_payload(
    builder: LegalIRTemporalAuthorityGraphBuilder,
    payload: Mapping[str, Any],
    *,
    default_authority_id: str = "",
    default_jurisdiction: str = "",
    default_version: str = "",
) -> None:
    citation = str(payload.get("canonical_citation") or payload.get("citation") or payload.get("section") or "")
    if not citation:
        return
    authority_id = str(payload.get("authority_id") or default_authority_id)
    builder.add_law_version(
        citation,
        law_version_id=str(payload.get("law_version_id") or payload.get("target_id") or ""),
        authority_id=authority_id,
        jurisdiction=str(payload.get("jurisdiction") or default_jurisdiction),
        version=str(payload.get("version") or default_version),
        effective_date=payload.get("effective_date") or payload.get("effective_on"),
        sunset_date=payload.get("sunset_date") or payload.get("sunsets_on"),
        repeal_date=payload.get("repeal_date") or payload.get("repealed_on"),
        superseded_date=payload.get("superseded_date") or payload.get("superseded_on"),
        emergency=bool(payload.get("emergency") or payload.get("emergency_rule")),
        emergency_expires_on=payload.get("emergency_expires_on") or payload.get("emergency_expiration_date"),
        amended_by=_strings(payload.get("amended_by", ())),
        amends=_strings(payload.get("amends", ())),
        repealed_by=str(payload.get("repealed_by") or ""),
        superseded_by=str(payload.get("superseded_by") or ""),
        supersedes=_strings(payload.get("supersedes", ())),
        source_node_ids=_source_node_ids(payload),
        span_ids=_strings(payload.get("span_ids", ())),
        citation_target_id=str(payload.get("citation_target_id") or payload.get("target_id") or ""),
        formula_ids=_strings(payload.get("formula_ids", ())),
        conclusion_kinds=_strings(payload.get("conclusion_kinds", ())),
        conflict_key=str(payload.get("conflict_key") or normalize_legal_citation(citation, default_authority=authority_id)),
        metadata={key: value for key, value in payload.items() if key not in {"citation", "canonical_citation", "section"}},
    )


def _replace_law(law: LegalIRLawVersion, **updates: Any) -> LegalIRLawVersion:
    data = law.to_dict()
    data.update(updates)
    if isinstance(data.get("temporal_window"), LegalIRTemporalWindow):
        data["temporal_window"] = data["temporal_window"].to_dict()
    return LegalIRLawVersion.from_dict(data)


def _temporal_authority_graph(value: LegalIRTemporalAuthorityGraph | Mapping[str, Any]) -> LegalIRTemporalAuthorityGraph:
    if isinstance(value, LegalIRTemporalAuthorityGraph):
        return value
    return LegalIRTemporalAuthorityGraph.from_dict(_mapping(value))


def _citation_graph_or_none(value: LegalIRCitationGraph | Mapping[str, Any] | None) -> LegalIRCitationGraph | None:
    if value is None:
        return None
    if isinstance(value, LegalIRCitationGraph):
        return value
    return LegalIRCitationGraph.from_dict(_mapping(value))


def _query_context(value: LegalIRTemporalQueryContext | Mapping[str, Any]) -> LegalIRTemporalQueryContext:
    if isinstance(value, LegalIRTemporalQueryContext):
        return value
    return LegalIRTemporalQueryContext.from_dict(_mapping(value))


def _applicability(value: LegalIRTemporalApplicability | Mapping[str, Any]) -> LegalIRTemporalApplicability:
    if isinstance(value, LegalIRTemporalApplicability):
        return value
    data = _mapping(value)
    return LegalIRTemporalApplicability(
        query_context=LegalIRTemporalQueryContext.from_dict(_mapping(data.get("query_context"))),
        decisions=tuple(LegalIRTemporalDecision.from_dict(_mapping(item)) for item in data.get("decisions", []) or []),
        diagnostics=tuple(LegalIRTemporalDiagnostic.from_dict(_mapping(item)) for item in data.get("diagnostics", []) or []),
        schema_version=str(data.get("schema_version") or LEGAL_IR_TEMPORAL_AUTHORITY_SCHEMA_VERSION),
    )


def _has_temporal_payload(payload: Mapping[str, Any]) -> bool:
    return any(
        key in payload
        for key in (
            "effective_date",
            "effective_on",
            "sunset_date",
            "sunsets_on",
            "repeal_date",
            "repealed_on",
            "superseded_date",
            "superseded_on",
            "emergency_expires_on",
            "emergency_expiration_date",
            "emergency",
            "emergency_rule",
            "authority_context",
            "temporal_authority",
        )
    )


def _authority_jurisdiction(builder: LegalIRTemporalAuthorityGraphBuilder, authority_id: str) -> str:
    authority = builder._authorities.get(authority_id)
    return authority.jurisdiction if authority is not None else ""


def _conclusion_kind_for_law(law: LegalIRLawVersion) -> str:
    if law.conclusion_kinds:
        return law.conclusion_kinds[0]
    return _atom(law.metadata.get("conclusion_kind") or law.metadata.get("role") or "", fallback="factual")


def _jurisdiction_matches(query_jurisdiction: str, law_jurisdiction: str) -> bool:
    query = str(query_jurisdiction or "").strip().upper()
    law = str(law_jurisdiction or "").strip().upper()
    if not query or not law:
        return True
    if query == law:
        return True
    if law == "US":
        return True
    return query.startswith(f"{law}.") or query.startswith(f"{law}:")


def _change_kind(value: Any) -> LegalIRTemporalChangeKind:
    if isinstance(value, LegalIRTemporalChangeKind):
        return value
    text = str(value or "").strip().lower()
    for item in LegalIRTemporalChangeKind:
        if text == item.value:
            return item
    return LegalIRTemporalChangeKind.EFFECTIVE


def _diagnostic_type(value: Any) -> LegalIRTemporalDiagnosticType:
    if isinstance(value, LegalIRTemporalDiagnosticType):
        return value
    text = str(value or "").strip().lower()
    for item in LegalIRTemporalDiagnosticType:
        if text == item.value:
            return item
    return LegalIRTemporalDiagnosticType.TEMPORAL_CONTEXT_MISSING


def _applicability_status(value: Any) -> LegalIRTemporalApplicabilityStatus:
    if isinstance(value, LegalIRTemporalApplicabilityStatus):
        return value
    text = str(value or "").strip().lower()
    for item in LegalIRTemporalApplicabilityStatus:
        if text == item.value:
            return item
    return LegalIRTemporalApplicabilityStatus.UNRESOLVED_AUTHORITY


def _diagnostic(
    diagnostic_type: LegalIRTemporalDiagnosticType,
    message: str,
    *,
    severity: str = "error",
    law_version_id: str = "",
    authority_id: str = "",
    change_id: str = "",
    formula_id: str = "",
    source_node_ids: Sequence[str] = (),
    field_path: str = "",
) -> LegalIRTemporalDiagnostic:
    return LegalIRTemporalDiagnostic(
        diagnostic_type=diagnostic_type,
        message=message,
        severity=severity,
        law_version_id=law_version_id,
        authority_id=authority_id,
        change_id=change_id,
        formula_id=formula_id,
        source_node_ids=tuple(_unique(_strings(source_node_ids))),
        field_path=field_path,
    )


def _duplicate_diagnostics(
    label: str,
    values: Sequence[str],
    diagnostics: list[LegalIRTemporalDiagnostic],
    diagnostic_type: LegalIRTemporalDiagnosticType,
) -> None:
    seen: set[str] = set()
    for value in values:
        if not value:
            continue
        if value in seen:
            diagnostics.append(_diagnostic(diagnostic_type, f"Duplicate {label} id.", field_path=f"{label}.{value}"))
        seen.add(value)


def _dedupe_diagnostics(items: Sequence[LegalIRTemporalDiagnostic]) -> tuple[LegalIRTemporalDiagnostic, ...]:
    deduped: dict[str, LegalIRTemporalDiagnostic] = {}
    for item in items:
        key = _stable_hash(item.to_dict())
        deduped.setdefault(key, item)
    return tuple(deduped[key] for key in sorted(deduped))


def _parse_date(value: Any) -> date | None:
    text = _date_text(value)
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _date_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value or "").strip()
    if not text:
        return ""
    match = re.match(r"^(\d{4}-\d{2}-\d{2})", text)
    return match.group(1) if match else text


def _stable_json(value: Any) -> str:
    return json.dumps(value, default=str, ensure_ascii=True, separators=(",", ":"), sort_keys=True)


def _stable_hash(value: Any) -> str:
    return hashlib.sha256(_stable_json(value).encode("utf-8")).hexdigest()


def _canonical_json_value(value: Any) -> Any:
    return json.loads(_stable_json(value))


def _mapping(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, Mapping):
        return dict(value)
    if hasattr(value, "to_dict") and callable(getattr(value, "to_dict")):
        try:
            converted = value.to_dict()
            if isinstance(converted, Mapping):
                return dict(converted)
        except (TypeError, ValueError):
            return {}
    return {}


def _payload_mapping(value: Any) -> dict[str, Any]:
    return _mapping(value)


def _strings(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,) if value else ()
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray, str)):
        return tuple(str(item) for item in value if str(item))
    return (str(value),) if str(value) else ()


def _sequence(value: Any) -> tuple[Any, ...]:
    if value is None:
        return ()
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray, str)):
        return tuple(value)
    return (value,)


def _unique(values: Sequence[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(str(value) for value in values if str(value)))


def _atom(value: Any, *, fallback: str = "unknown") -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"[^a-z0-9_.:-]+", "_", text).strip("_")
    return text or fallback


def _source_node_ids(payload: Mapping[str, Any]) -> tuple[str, ...]:
    return tuple(
        _unique(
            _strings(
                payload.get("source_node_ids")
                or payload.get("source_nodes")
                or payload.get("node_ids")
                or payload.get("provenance_ids")
                or ()
            )
        )
    )


__all__ = [
    "LEGAL_IR_TEMPORAL_AUTHORITY_SCHEMA_VERSION",
    "LegalIRAuthorityNode",
    "LegalIRLawVersion",
    "LegalIRTemporalApplicability",
    "LegalIRTemporalApplicabilityStatus",
    "LegalIRTemporalAuthorityBuilder",
    "LegalIRTemporalAuthorityGraph",
    "LegalIRTemporalAuthorityGraphBuilder",
    "LegalIRTemporalAuthorityValidationResult",
    "LegalIRTemporalChange",
    "LegalIRTemporalChangeKind",
    "LegalIRTemporalDecision",
    "LegalIRTemporalDiagnostic",
    "LegalIRTemporalDiagnosticType",
    "LegalIRTemporalQueryContext",
    "LegalIRTemporalWindow",
    "assert_legal_ir_temporal_authority_applicable",
    "build_legal_ir_temporal_authority_graph",
    "generate_legal_ir_temporal_authority_obligation_specs",
    "legal_ir_temporal_authority_allowed_for_use",
    "query_legal_ir_temporal_applicability",
    "validate_legal_ir_temporal_authority_graph",
]
