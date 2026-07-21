"""Canonical LegalIR citation and cross-reference linking.

LegalIR proof targets must distinguish cited law from unresolved text.  This
module records legal authorities, canonical citation targets, source-map
lineage, deterministic resolution confidence, and diagnostics for unresolved,
ambiguous, repealed, and provenance-broken references.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Final

from .legal_ir_source_maps import (
    LegalIRFactTrace,
    LegalIRProvenanceSpan,
    LegalIRSourceMap,
    LegalIRSourceMapIssue,
    LegalIRSourceMapTransform,
    trace_legal_ir_fact,
)


LEGAL_IR_CITATION_LINKER_SCHEMA_VERSION: Final = "legal-ir-citation-linker-v1"

_WORD_RE = re.compile(r"[A-Za-z0-9]+")
_SUBSECTION_RE = re.compile(r"\(([A-Za-z0-9]+)\)")
_RANGE_SPLIT_RE = re.compile(r"\s+(?:through|thru|to|-|--|/)\s+", re.IGNORECASE)
_SECTION_MARK_RE = re.compile(r"(?:section|sec\.?|secs\.?|sections|ss\.?|§§?|¶)", re.IGNORECASE)
_USC_RE = re.compile(
    r"^\s*(?P<title>\d+)\s+U\.?\s*S\.?\s*C\.?\s*(?:§+\s*)?(?P<section>[A-Za-z0-9_.-]+)(?P<subs>(?:\([A-Za-z0-9]+\))*)\s*$",
    re.IGNORECASE,
)
_ORS_RE = re.compile(
    r"^\s*O\.?\s*R\.?\s*S\.?\s*(?:§+\s*)?(?P<section>[A-Za-z0-9_.-]+)(?P<subs>(?:\([A-Za-z0-9]+\))*)\s*$",
    re.IGNORECASE,
)
_OAR_RE = re.compile(
    r"^\s*O\.?\s*A\.?\s*R\.?\s*(?:§+\s*)?(?P<section>[A-Za-z0-9_.-]+)(?P<subs>(?:\([A-Za-z0-9]+\))*)\s*$",
    re.IGNORECASE,
)
_CFR_RE = re.compile(
    r"^\s*(?P<title>\d+)\s+C\.?\s*F\.?\s*R\.?\s*(?:§+\s*)?(?P<section>[A-Za-z0-9_.-]+)(?P<subs>(?:\([A-Za-z0-9]+\))*)\s*$",
    re.IGNORECASE,
)
_BARE_SECTION_RE = re.compile(
    r"^\s*(?:§+\s*)?(?P<section>[A-Za-z0-9_.-]+)(?P<subs>(?:\([A-Za-z0-9]+\))*)\s*$",
    re.IGNORECASE,
)


class LegalIRCitationKind(str, Enum):
    """Citation categories that have different legal resolution semantics."""

    INTERNAL = "internal"
    EXTERNAL = "external"
    RANGE = "range"
    SUBSECTION = "subsection"
    INCORPORATED = "incorporated"
    REPEALED = "repealed"
    UNKNOWN = "unknown"


class LegalIRCitationResolutionStatus(str, Enum):
    """Deterministic outcome for one citation reference."""

    RESOLVED = "resolved"
    UNRESOLVED = "unresolved"
    AMBIGUOUS = "ambiguous"
    REPEALED = "repealed"


class LegalIRCitationDiagnosticType(str, Enum):
    """Typed citation-linker diagnostics."""

    UNRESOLVED_CITATION = "unresolved_citation"
    AMBIGUOUS_CITATION = "ambiguous_citation"
    REPEALED_CITATION = "repealed_citation"
    AUTHORITY_MISSING = "authority_missing"
    TARGET_AUTHORITY_MISSING = "target_authority_missing"
    TARGET_VERSION_MISSING = "target_version_missing"
    DUPLICATE_AUTHORITY_ID = "duplicate_authority_id"
    DUPLICATE_TARGET_ID = "duplicate_target_id"
    DUPLICATE_REFERENCE_ID = "duplicate_reference_id"
    RESOLUTION_TARGET_MISSING = "resolution_target_missing"
    RESOLUTION_DIAGNOSTIC_MISSING = "resolution_diagnostic_missing"
    SOURCE_PROVENANCE_MISSING = "source_provenance_missing"
    SOURCE_PROVENANCE_UNTRACEABLE = "source_provenance_untraceable"


class LegalIRCitationUse(str, Enum):
    """Downstream use categories that must fail closed on unresolved law."""

    COMPILER = "compiler"
    DIAGNOSTIC = "diagnostic"
    PROOF_TARGET = "proof_target"
    LEARNED_TARGET = "learned_target"


@dataclass(frozen=True)
class LegalIRAuthority:
    """One legal authority or corpus version used by citation targets."""

    authority_id: str
    name: str
    jurisdiction: str = ""
    authority_type: str = ""
    version: str = ""
    source_uri: str = ""
    rank: int = 0
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority_id": self.authority_id,
            "authority_type": self.authority_type,
            "jurisdiction": self.jurisdiction,
            "metadata": _canonical_json_value(self.metadata),
            "name": self.name,
            "rank": int(self.rank),
            "source_uri": self.source_uri,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "LegalIRAuthority":
        return cls(
            authority_id=str(data.get("authority_id") or ""),
            name=str(data.get("name") or ""),
            jurisdiction=str(data.get("jurisdiction") or ""),
            authority_type=str(data.get("authority_type") or data.get("type") or ""),
            version=str(data.get("version") or ""),
            source_uri=str(data.get("source_uri") or ""),
            rank=int(data.get("rank") or 0),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass(frozen=True)
class LegalIRCitationTarget:
    """A canonical citable legal unit known to the linker."""

    target_id: str
    canonical_citation: str
    authority_id: str
    document_id: str = ""
    version: str = ""
    citation_kind: LegalIRCitationKind = LegalIRCitationKind.EXTERNAL
    title: str = ""
    section: str = ""
    subsections: tuple[str, ...] = ()
    range_start: str = ""
    range_end: str = ""
    repealed: bool = False
    incorporated: bool = False
    source_node_ids: tuple[str, ...] = ()
    span_ids: tuple[str, ...] = ()
    aliases: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def canonical_key(self) -> str:
        return normalize_legal_citation(self.canonical_citation)

    @property
    def active_law(self) -> bool:
        return bool(self.canonical_citation and self.authority_id and self.version and not self.repealed)

    def to_dict(self) -> dict[str, Any]:
        return {
            "aliases": list(self.aliases),
            "authority_id": self.authority_id,
            "canonical_citation": self.canonical_citation,
            "citation_kind": self.citation_kind.value,
            "document_id": self.document_id,
            "incorporated": bool(self.incorporated),
            "metadata": _canonical_json_value(self.metadata),
            "range_end": self.range_end,
            "range_start": self.range_start,
            "repealed": bool(self.repealed),
            "section": self.section,
            "source_node_ids": list(self.source_node_ids),
            "span_ids": list(self.span_ids),
            "subsections": list(self.subsections),
            "target_id": self.target_id,
            "title": self.title,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "LegalIRCitationTarget":
        return cls(
            target_id=str(data.get("target_id") or ""),
            canonical_citation=str(data.get("canonical_citation") or data.get("citation") or ""),
            authority_id=str(data.get("authority_id") or ""),
            document_id=str(data.get("document_id") or ""),
            version=str(data.get("version") or ""),
            citation_kind=_citation_kind(data.get("citation_kind") or data.get("kind")),
            title=str(data.get("title") or ""),
            section=str(data.get("section") or ""),
            subsections=tuple(_unique(_strings(data.get("subsections", ())))),
            range_start=str(data.get("range_start") or ""),
            range_end=str(data.get("range_end") or ""),
            repealed=bool(data.get("repealed")),
            incorporated=bool(data.get("incorporated")),
            source_node_ids=tuple(_unique(_strings(data.get("source_node_ids", ())))),
            span_ids=tuple(_unique(_strings(data.get("span_ids", ())))),
            aliases=tuple(_unique(normalize_legal_citation(item) for item in _strings(data.get("aliases", ())))),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass(frozen=True)
class LegalIRCitationReference:
    """A citation use-site that must link to a canonical target or diagnostic."""

    reference_id: str
    raw_text: str
    citation_kind: LegalIRCitationKind
    document_id: str = ""
    authority_id: str = ""
    version: str = ""
    explicit_target_id: str = ""
    explicit_target_document_id: str = ""
    source_node_ids: tuple[str, ...] = ()
    span_ids: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def canonical_citation(self) -> str:
        return normalize_legal_citation(
            self.raw_text,
            default_authority=self.metadata.get("default_authority") or self.authority_id,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority_id": self.authority_id,
            "canonical_citation": self.canonical_citation,
            "citation_kind": self.citation_kind.value,
            "document_id": self.document_id,
            "explicit_target_document_id": self.explicit_target_document_id,
            "explicit_target_id": self.explicit_target_id,
            "metadata": _canonical_json_value(self.metadata),
            "raw_text": self.raw_text,
            "reference_id": self.reference_id,
            "source_node_ids": list(self.source_node_ids),
            "span_ids": list(self.span_ids),
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "LegalIRCitationReference":
        return cls(
            reference_id=str(data.get("reference_id") or ""),
            raw_text=str(data.get("raw_text") or data.get("citation") or data.get("text") or ""),
            citation_kind=_citation_kind(data.get("citation_kind") or data.get("kind")),
            document_id=str(data.get("document_id") or ""),
            authority_id=str(data.get("authority_id") or ""),
            version=str(data.get("version") or ""),
            explicit_target_id=str(data.get("explicit_target_id") or data.get("target_id") or ""),
            explicit_target_document_id=str(data.get("explicit_target_document_id") or data.get("target_document_id") or ""),
            source_node_ids=tuple(_unique(_strings(data.get("source_node_ids", ())))),
            span_ids=tuple(_unique(_strings(data.get("span_ids", ())))),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass(frozen=True)
class LegalIRCitationDiagnostic:
    """One typed citation diagnostic with source-map identifiers."""

    diagnostic_type: LegalIRCitationDiagnosticType
    message: str
    severity: str = "error"
    reference_id: str = ""
    target_ids: tuple[str, ...] = ()
    authority_id: str = ""
    document_id: str = ""
    source_node_ids: tuple[str, ...] = ()
    source_span_ids: tuple[str, ...] = ()
    field_path: str = ""

    @property
    def code(self) -> str:
        return self.diagnostic_type.value

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority_id": self.authority_id,
            "code": self.code,
            "diagnostic_type": self.diagnostic_type.value,
            "document_id": self.document_id,
            "field_path": self.field_path,
            "message": self.message,
            "reference_id": self.reference_id,
            "severity": self.severity,
            "source_node_ids": list(self.source_node_ids),
            "source_span_ids": list(self.source_span_ids),
            "target_ids": list(self.target_ids),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "LegalIRCitationDiagnostic":
        return cls(
            diagnostic_type=_diagnostic_type(data.get("diagnostic_type") or data.get("code")),
            message=str(data.get("message") or ""),
            severity=str(data.get("severity") or "error"),
            reference_id=str(data.get("reference_id") or ""),
            target_ids=tuple(_unique(_strings(data.get("target_ids", ())))),
            authority_id=str(data.get("authority_id") or ""),
            document_id=str(data.get("document_id") or ""),
            source_node_ids=tuple(_unique(_strings(data.get("source_node_ids", ())))),
            source_span_ids=tuple(_unique(_strings(data.get("source_span_ids", ())))),
            field_path=str(data.get("field_path") or ""),
        )


@dataclass(frozen=True)
class LegalIRCitationResolution:
    """Recorded canonical link result for one citation reference."""

    reference_id: str
    status: LegalIRCitationResolutionStatus
    canonical_citation: str = ""
    target_ids: tuple[str, ...] = ()
    authority_id: str = ""
    version: str = ""
    citation_kind: LegalIRCitationKind = LegalIRCitationKind.UNKNOWN
    confidence: float = 0.0
    diagnostics: tuple[LegalIRCitationDiagnostic, ...] = ()
    source_traces: tuple[LegalIRFactTrace, ...] = ()

    @property
    def resolved(self) -> bool:
        return self.status is LegalIRCitationResolutionStatus.RESOLVED and bool(self.target_ids)

    @property
    def active_law(self) -> bool:
        return self.resolved and self.confidence > 0.0

    @property
    def diagnostic_types(self) -> tuple[LegalIRCitationDiagnosticType, ...]:
        return tuple(issue.diagnostic_type for issue in self.diagnostics)

    def to_dict(self) -> dict[str, Any]:
        return {
            "active_law": self.active_law,
            "authority_id": self.authority_id,
            "canonical_citation": self.canonical_citation,
            "citation_kind": self.citation_kind.value,
            "confidence": float(self.confidence),
            "diagnostic_types": [item.value for item in self.diagnostic_types],
            "diagnostics": [issue.to_dict() for issue in self.diagnostics],
            "reference_id": self.reference_id,
            "resolved": self.resolved,
            "source_traces": [trace.to_dict() for trace in self.source_traces],
            "status": self.status.value,
            "target_ids": list(self.target_ids),
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "LegalIRCitationResolution":
        return cls(
            reference_id=str(data.get("reference_id") or ""),
            status=_resolution_status(data.get("status")),
            canonical_citation=str(data.get("canonical_citation") or ""),
            target_ids=tuple(_unique(_strings(data.get("target_ids", ())))),
            authority_id=str(data.get("authority_id") or ""),
            version=str(data.get("version") or ""),
            citation_kind=_citation_kind(data.get("citation_kind")),
            confidence=float(data.get("confidence") or 0.0),
            diagnostics=tuple(
                LegalIRCitationDiagnostic.from_dict(_mapping(item))
                for item in data.get("diagnostics", []) or []
            ),
            source_traces=tuple(
                _fact_trace_from_dict(_mapping(item))
                for item in data.get("source_traces", []) or []
            ),
        )


@dataclass(frozen=True)
class LegalIRCitationValidationResult:
    """Validation result for a complete citation graph."""

    citation_graph_id: str
    authority_count: int
    target_count: int
    reference_count: int
    resolved_count: int
    diagnostics: tuple[LegalIRCitationDiagnostic, ...] = ()
    schema_version: str = LEGAL_IR_CITATION_LINKER_SCHEMA_VERSION

    @property
    def valid(self) -> bool:
        return not any(issue.severity == "error" for issue in self.diagnostics)

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority_count": int(self.authority_count),
            "citation_graph_id": self.citation_graph_id,
            "diagnostics": [issue.to_dict() for issue in self.diagnostics],
            "reference_count": int(self.reference_count),
            "resolved_count": int(self.resolved_count),
            "schema_version": self.schema_version,
            "target_count": int(self.target_count),
            "valid": self.valid,
        }


@dataclass(frozen=True)
class LegalIRCitationGraph:
    """Immutable graph of authorities, canonical targets, and citation links."""

    citation_graph_id: str
    authorities: tuple[LegalIRAuthority, ...]
    targets: tuple[LegalIRCitationTarget, ...]
    references: tuple[LegalIRCitationReference, ...] = ()
    resolutions: tuple[LegalIRCitationResolution, ...] = ()
    diagnostics: tuple[LegalIRCitationDiagnostic, ...] = ()
    source_map_id: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = LEGAL_IR_CITATION_LINKER_SCHEMA_VERSION

    @property
    def authority_by_id(self) -> Mapping[str, LegalIRAuthority]:
        return {authority.authority_id: authority for authority in self.authorities}

    @property
    def target_by_id(self) -> Mapping[str, LegalIRCitationTarget]:
        return {target.target_id: target for target in self.targets}

    @property
    def reference_by_id(self) -> Mapping[str, LegalIRCitationReference]:
        return {reference.reference_id: reference for reference in self.references}

    @property
    def resolution_by_reference_id(self) -> Mapping[str, LegalIRCitationResolution]:
        return {resolution.reference_id: resolution for resolution in self.resolutions}

    @property
    def unresolved_references(self) -> tuple[LegalIRCitationReference, ...]:
        resolutions = self.resolution_by_reference_id
        return tuple(
            reference
            for reference in self.references
            if resolutions.get(
                reference.reference_id,
                LegalIRCitationResolution(reference.reference_id, LegalIRCitationResolutionStatus.UNRESOLVED),
            ).status
            is LegalIRCitationResolutionStatus.UNRESOLVED
        )

    @property
    def ambiguous_references(self) -> tuple[LegalIRCitationReference, ...]:
        resolutions = self.resolution_by_reference_id
        return tuple(
            reference
            for reference in self.references
            if resolutions.get(
                reference.reference_id,
                LegalIRCitationResolution(reference.reference_id, LegalIRCitationResolutionStatus.UNRESOLVED),
            ).status
            is LegalIRCitationResolutionStatus.AMBIGUOUS
        )

    @property
    def repealed_references(self) -> tuple[LegalIRCitationReference, ...]:
        resolutions = self.resolution_by_reference_id
        return tuple(
            reference
            for reference in self.references
            if resolutions.get(
                reference.reference_id,
                LegalIRCitationResolution(reference.reference_id, LegalIRCitationResolutionStatus.UNRESOLVED),
            ).status
            is LegalIRCitationResolutionStatus.REPEALED
        )

    @property
    def resolved(self) -> bool:
        return not self.unresolved_references and not self.ambiguous_references

    @property
    def proof_safe(self) -> bool:
        return self.resolved and not self.repealed_references

    def to_dict(self) -> dict[str, Any]:
        return {
            "authorities": [authority.to_dict() for authority in self.authorities],
            "citation_graph_id": self.citation_graph_id,
            "diagnostics": [issue.to_dict() for issue in self.diagnostics],
            "metadata": _canonical_json_value(self.metadata),
            "references": [reference.to_dict() for reference in self.references],
            "resolutions": [resolution.to_dict() for resolution in self.resolutions],
            "schema_version": self.schema_version,
            "source_map_id": self.source_map_id,
            "targets": [target.to_dict() for target in self.targets],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "LegalIRCitationGraph":
        return cls(
            citation_graph_id=str(data.get("citation_graph_id") or data.get("citation_table_id") or ""),
            authorities=tuple(
                LegalIRAuthority.from_dict(_mapping(item))
                for item in data.get("authorities", []) or []
            ),
            targets=tuple(
                LegalIRCitationTarget.from_dict(_mapping(item))
                for item in data.get("targets", []) or []
            ),
            references=tuple(
                LegalIRCitationReference.from_dict(_mapping(item))
                for item in data.get("references", []) or []
            ),
            resolutions=tuple(
                LegalIRCitationResolution.from_dict(_mapping(item))
                for item in data.get("resolutions", []) or []
            ),
            diagnostics=tuple(
                LegalIRCitationDiagnostic.from_dict(_mapping(item))
                for item in data.get("diagnostics", []) or []
            ),
            source_map_id=str(data.get("source_map_id") or ""),
            metadata=dict(data.get("metadata") or {}),
            schema_version=str(data.get("schema_version") or LEGAL_IR_CITATION_LINKER_SCHEMA_VERSION),
        )


class LegalIRCitationGraphBuilder:
    """Mutable builder that links citation references deterministically."""

    def __init__(
        self,
        *,
        citation_graph_id: str = "",
        source_map: LegalIRSourceMap | Mapping[str, Any] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        self.citation_graph_id = citation_graph_id
        self.source_map = _source_map(source_map) if source_map is not None else None
        self.metadata = dict(metadata or {})
        self._authorities: dict[str, LegalIRAuthority] = {}
        self._targets: dict[str, LegalIRCitationTarget] = {}
        self._references: dict[str, LegalIRCitationReference] = {}
        self._diagnostics: list[LegalIRCitationDiagnostic] = []

    def add_authority(
        self,
        authority_id: str,
        *,
        name: str = "",
        jurisdiction: str = "",
        authority_type: str = "",
        version: str = "",
        source_uri: str = "",
        rank: int = 0,
        metadata: Mapping[str, Any] | None = None,
    ) -> LegalIRAuthority:
        authority = LegalIRAuthority(
            authority_id=str(authority_id or ""),
            name=str(name or authority_id or ""),
            jurisdiction=str(jurisdiction or ""),
            authority_type=str(authority_type or ""),
            version=str(version or ""),
            source_uri=str(source_uri or ""),
            rank=int(rank or 0),
            metadata=dict(metadata or {}),
        )
        self._authorities[authority.authority_id] = authority
        return authority

    def add_target(
        self,
        citation: str,
        *,
        target_id: str = "",
        authority_id: str = "",
        document_id: str = "",
        version: str = "",
        citation_kind: LegalIRCitationKind | str = LegalIRCitationKind.EXTERNAL,
        source_node_ids: Sequence[str] = (),
        span_ids: Sequence[str] = (),
        aliases: Sequence[str] = (),
        repealed: bool = False,
        incorporated: bool = False,
        metadata: Mapping[str, Any] | None = None,
    ) -> LegalIRCitationTarget:
        canonical = normalize_legal_citation(citation, default_authority=authority_id)
        parsed = parse_legal_citation(canonical)
        kind = _citation_kind(citation_kind)
        if parsed["range_start"] or parsed["range_end"]:
            kind = LegalIRCitationKind.RANGE
        elif parsed["subsections"] and kind is LegalIRCitationKind.EXTERNAL:
            kind = LegalIRCitationKind.SUBSECTION
        payload = {
            "authority_id": authority_id,
            "citation": canonical,
            "document_id": document_id,
            "version": version,
        }
        target = LegalIRCitationTarget(
            target_id=str(target_id or f"lir-citation-target-{_stable_hash(payload)[:24]}"),
            canonical_citation=canonical,
            authority_id=str(authority_id or _authority_id_for_citation(canonical)),
            document_id=str(document_id or ""),
            version=str(version or ""),
            citation_kind=kind,
            title=str(parsed["title"]),
            section=str(parsed["section"]),
            subsections=tuple(_strings(parsed["subsections"])),
            range_start=str(parsed["range_start"]),
            range_end=str(parsed["range_end"]),
            repealed=bool(repealed),
            incorporated=bool(incorporated),
            source_node_ids=tuple(_unique(_strings(source_node_ids))),
            span_ids=tuple(_unique(_strings(span_ids))),
            aliases=tuple(_unique(normalize_legal_citation(item, default_authority=authority_id) for item in _strings(aliases))),
            metadata=dict(metadata or {}),
        )
        self._targets[target.target_id] = target
        if target.authority_id and target.authority_id not in self._authorities:
            self.add_authority(
                target.authority_id,
                name=target.authority_id,
                version=target.version,
                metadata={"inferred": True},
            )
        return target

    def add_reference(
        self,
        raw_text: str,
        *,
        reference_id: str = "",
        citation_kind: LegalIRCitationKind | str = LegalIRCitationKind.UNKNOWN,
        document_id: str = "",
        authority_id: str = "",
        version: str = "",
        explicit_target_id: str = "",
        explicit_target_document_id: str = "",
        source_node_ids: Sequence[str] = (),
        span_ids: Sequence[str] = (),
        metadata: Mapping[str, Any] | None = None,
    ) -> LegalIRCitationReference:
        kind = _citation_kind(citation_kind)
        if kind is LegalIRCitationKind.UNKNOWN:
            kind = infer_legal_citation_kind(raw_text, document_id=document_id, authority_id=authority_id)
        payload = {
            "authority_id": authority_id,
            "document_id": document_id,
            "raw_text": normalize_legal_citation(raw_text, default_authority=authority_id),
            "target_id": explicit_target_id,
            "version": version,
        }
        reference = LegalIRCitationReference(
            reference_id=str(reference_id or f"lir-citation-reference-{_stable_hash(payload)[:24]}"),
            raw_text=str(raw_text or ""),
            citation_kind=kind,
            document_id=str(document_id or ""),
            authority_id=str(authority_id or ""),
            version=str(version or ""),
            explicit_target_id=str(explicit_target_id or ""),
            explicit_target_document_id=str(explicit_target_document_id or ""),
            source_node_ids=tuple(_unique(_strings(source_node_ids))),
            span_ids=tuple(_unique(_strings(span_ids))),
            metadata=dict(metadata or {}),
        )
        self._references[reference.reference_id] = reference
        return reference

    def resolve_reference(
        self,
        reference: LegalIRCitationReference | str,
        *,
        external_citation_graphs: Sequence[LegalIRCitationGraph | Mapping[str, Any]] = (),
    ) -> LegalIRCitationResolution:
        ref = self._references[str(reference)] if isinstance(reference, str) else reference
        graph = self.to_citation_graph(resolve=False)
        return _resolve_reference(
            graph,
            ref,
            external_citation_graphs=external_citation_graphs,
            source_map=self.source_map,
        )

    def to_citation_graph(
        self,
        *,
        resolve: bool = True,
        external_citation_graphs: Sequence[LegalIRCitationGraph | Mapping[str, Any]] = (),
    ) -> LegalIRCitationGraph:
        graph_id = self.citation_graph_id or "lir-citation-graph-" + _stable_hash(
            {
                "authorities": sorted(self._authorities),
                "references": sorted(self._references),
                "targets": sorted(self._targets),
            }
        )[:24]
        base = LegalIRCitationGraph(
            citation_graph_id=graph_id,
            authorities=tuple(self._authorities[key] for key in sorted(self._authorities)),
            targets=tuple(self._targets[key] for key in sorted(self._targets)),
            references=tuple(self._references[key] for key in sorted(self._references)),
            resolutions=(),
            diagnostics=tuple(_dedupe_diagnostics(self._diagnostics)),
            source_map_id=self.source_map.source_map_id if self.source_map is not None else "",
            metadata=dict(self.metadata),
        )
        if not resolve:
            return base
        resolutions = tuple(
            _resolve_reference(
                base,
                reference,
                external_citation_graphs=external_citation_graphs,
                source_map=self.source_map,
            )
            for reference in base.references
        )
        diagnostics = tuple(
            _dedupe_diagnostics(
                (
                    *base.diagnostics,
                    *(diagnostic for resolution in resolutions for diagnostic in resolution.diagnostics),
                )
            )
        )
        return LegalIRCitationGraph(
            citation_graph_id=base.citation_graph_id,
            authorities=base.authorities,
            targets=base.targets,
            references=base.references,
            resolutions=resolutions,
            diagnostics=diagnostics,
            source_map_id=base.source_map_id,
            metadata=base.metadata,
        )

    def to_citation_table(
        self,
        *,
        resolve: bool = True,
        external_citation_graphs: Sequence[LegalIRCitationGraph | Mapping[str, Any]] = (),
    ) -> LegalIRCitationGraph:
        """Compatibility alias for callers that name the graph a table."""

        return self.to_citation_graph(
            resolve=resolve,
            external_citation_graphs=external_citation_graphs,
        )


LegalIRCitationTable = LegalIRCitationGraph
LegalIRCitationTableBuilder = LegalIRCitationGraphBuilder
LegalIRCitationLinker = LegalIRCitationGraphBuilder


def normalize_legal_citation(raw_citation: Any, *, default_authority: str = "") -> str:
    """Return a canonical, deterministic citation key."""

    text = str(raw_citation or "").strip()
    if not text:
        return ""
    text = text.replace("\u00a7", "§")
    text = re.sub(r"\s+", " ", text)
    text = _strip_citation_context(text)
    text = re.sub(r"\bU\s*S\s*C\b", "U.S.C.", text, flags=re.IGNORECASE)
    text = re.sub(r"\bC\s*F\s*R\b", "C.F.R.", text, flags=re.IGNORECASE)
    text = _SECTION_MARK_RE.sub("", text).strip()
    text = text.rstrip(".,;")
    text = _normalize_range_citation(text, default_authority=default_authority)
    if "-" in text and _looks_like_range(text):
        return text
    for regex, formatter in (
        (_USC_RE, lambda m: f"{m.group('title')} U.S.C. {m.group('section')}{m.group('subs')}"),
        (_CFR_RE, lambda m: f"{m.group('title')} C.F.R. {m.group('section')}{m.group('subs')}"),
        (_ORS_RE, lambda m: f"ORS {m.group('section')}{m.group('subs')}"),
        (_OAR_RE, lambda m: f"OAR {m.group('section')}{m.group('subs')}"),
    ):
        match = regex.match(text)
        if match:
            return formatter(match)
    bare = _BARE_SECTION_RE.match(text)
    if bare and default_authority:
        prefix = _canonical_authority_prefix(default_authority)
        if prefix:
            return f"{prefix} {bare.group('section')}{bare.group('subs')}"
    return _canonical_text_key(text)


def parse_legal_citation(citation: Any) -> Mapping[str, Any]:
    """Parse a canonical citation into stable fields used for range matching."""

    canonical = normalize_legal_citation(citation)
    range_start = ""
    range_end = ""
    if _looks_like_range(canonical):
        left, right = canonical.split("-", 1)
        range_start = normalize_legal_citation(left.strip())
        range_end = normalize_legal_citation(right.strip(), default_authority=_authority_id_for_citation(range_start))
        canonical = f"{range_start}-{range_end}"
    title = ""
    section = ""
    subsections: tuple[str, ...] = ()
    for regex in (_USC_RE, _CFR_RE, _ORS_RE, _OAR_RE):
        match = regex.match(canonical)
        if match:
            title = str(match.groupdict().get("title") or "")
            section = str(match.group("section"))
            subsections = tuple(_SUBSECTION_RE.findall(str(match.group("subs") or "")))
            break
    if not section and range_start:
        parsed_start = parse_legal_citation(range_start)
        title = str(parsed_start.get("title") or "")
        section = str(parsed_start.get("section") or "")
        subsections = tuple(_strings(parsed_start.get("subsections", ())))
    return {
        "canonical_citation": canonical,
        "range_end": range_end,
        "range_start": range_start,
        "section": section,
        "subsections": subsections,
        "title": title,
    }


def infer_legal_citation_kind(
    raw_text: Any,
    *,
    document_id: str = "",
    authority_id: str = "",
) -> LegalIRCitationKind:
    """Infer citation kind without resolving it."""

    text = str(raw_text or "").lower()
    canonical = normalize_legal_citation(raw_text, default_authority=authority_id)
    if any(word in text for word in ("repealed", "former", "superseded")):
        return LegalIRCitationKind.REPEALED
    if any(word in text for word in ("incorporated by reference", "incorporates", "incorporated")):
        return LegalIRCitationKind.INCORPORATED
    if _looks_like_range(canonical) or bool(_RANGE_SPLIT_RE.search(str(raw_text or ""))):
        return LegalIRCitationKind.RANGE
    if _SUBSECTION_RE.search(canonical):
        return LegalIRCitationKind.SUBSECTION
    if document_id and authority_id and _authority_id_for_citation(canonical) == _canonical_authority_prefix(authority_id):
        return LegalIRCitationKind.INTERNAL
    return LegalIRCitationKind.EXTERNAL if canonical else LegalIRCitationKind.UNKNOWN


def build_legal_ir_citation_graph(
    document_or_sample: Mapping[str, Any] | Any,
    *,
    source_map: LegalIRSourceMap | Mapping[str, Any] | None = None,
    external_citation_graphs: Sequence[LegalIRCitationGraph | Mapping[str, Any]] = (),
) -> LegalIRCitationGraph:
    """Build a citation graph from common LegalIR document shapes."""

    sample = _payload_mapping(document_or_sample)
    document = _mapping(sample.get("modal_ir") or sample.get("document") or sample)
    document_id = str(document.get("document_id") or sample.get("document_id") or sample.get("sample_id") or "legal-ir-document")
    citation = str(document.get("citation") or sample.get("citation") or "")
    version = str(document.get("version") or document.get("effective_version") or sample.get("version") or "")
    authority_payload = _mapping(document.get("authority") or sample.get("authority"))
    authority_id = str(
        authority_payload.get("authority_id")
        or document.get("authority_id")
        or sample.get("authority_id")
        or _authority_id_for_citation(citation)
    )
    builder = LegalIRCitationGraphBuilder(
        source_map=source_map,
        metadata={"builder": "build_legal_ir_citation_graph"},
    )
    if authority_id:
        builder.add_authority(
            authority_id,
            name=str(authority_payload.get("name") or authority_id),
            jurisdiction=str(authority_payload.get("jurisdiction") or ""),
            authority_type=str(authority_payload.get("authority_type") or authority_payload.get("type") or ""),
            version=str(authority_payload.get("version") or version),
            source_uri=str(authority_payload.get("source_uri") or ""),
            rank=int(authority_payload.get("rank") or 0),
        )
    explicit_target_citations = {
        normalize_legal_citation(
            str(_mapping(item).get("canonical_citation") or _mapping(item).get("citation") or _mapping(item).get("section") or ""),
            default_authority=authority_id,
        )
        for item in _sequence(document.get("citation_targets") or document.get("targets") or document.get("sections"))
    }
    if citation and normalize_legal_citation(citation, default_authority=authority_id) not in explicit_target_citations:
        builder.add_target(
            citation,
            target_id=str(document.get("target_id") or f"document:{document_id}"),
            authority_id=authority_id,
            document_id=document_id,
            version=version,
            citation_kind=LegalIRCitationKind.INTERNAL,
            source_node_ids=_source_node_ids(document) or (document_id,),
            span_ids=_strings(document.get("span_ids", ())),
        )

    for item in _sequence(document.get("citation_targets") or document.get("targets") or document.get("sections")):
        payload = _mapping(item)
        target_citation = str(payload.get("canonical_citation") or payload.get("citation") or payload.get("section") or "")
        if not target_citation:
            continue
        builder.add_target(
            target_citation,
            target_id=str(payload.get("target_id") or ""),
            authority_id=str(payload.get("authority_id") or authority_id),
            document_id=str(payload.get("document_id") or document_id),
            version=str(payload.get("version") or version),
            citation_kind=_citation_kind(payload.get("citation_kind") or payload.get("kind")),
            source_node_ids=_source_node_ids(payload),
            span_ids=_strings(payload.get("span_ids", ())),
            aliases=_strings(payload.get("aliases", ())),
            repealed=bool(payload.get("repealed")),
            incorporated=bool(payload.get("incorporated")),
            metadata={key: value for key, value in payload.items() if key not in {"citation", "canonical_citation", "section"}},
        )

    for field_name, kind in (
        ("references", LegalIRCitationKind.UNKNOWN),
        ("citations", LegalIRCitationKind.UNKNOWN),
        ("cross_references", LegalIRCitationKind.INTERNAL),
        ("incorporated_references", LegalIRCitationKind.INCORPORATED),
        ("repealed_references", LegalIRCitationKind.REPEALED),
    ):
        for item in _sequence(document.get(field_name)):
            payload = _reference_payload(item)
            raw = str(payload.get("raw_text") or payload.get("citation") or payload.get("text") or item or "")
            if raw:
                builder.add_reference(
                    raw,
                    reference_id=str(payload.get("reference_id") or ""),
                    citation_kind=_citation_kind(payload.get("citation_kind") or payload.get("kind") or kind),
                    document_id=str(payload.get("document_id") or document_id),
                    authority_id=str(payload.get("authority_id") or authority_id),
                    version=str(payload.get("version") or version),
                    explicit_target_id=str(payload.get("explicit_target_id") or payload.get("target_id") or ""),
                    explicit_target_document_id=str(payload.get("explicit_target_document_id") or payload.get("target_document_id") or ""),
                    source_node_ids=_source_node_ids(payload),
                    span_ids=_strings(payload.get("span_ids", ())),
                    metadata={key: value for key, value in payload.items() if key not in {"raw_text", "citation", "text"}},
                )

    for index, formula in enumerate(_sequence(document.get("formulas")), start=1):
        formula_payload = _mapping(formula)
        formula_id = str(formula_payload.get("formula_id") or f"formula-{index}")
        for field_name in ("citation", "citations", "references", "cross_references", "incorporated_references"):
            values = _sequence(formula_payload.get(field_name))
            if not values and field_name == "citation" and formula_payload.get(field_name):
                values = (formula_payload[field_name],)
            for item in values:
                payload = _reference_payload(item)
                raw = str(payload.get("raw_text") or payload.get("citation") or payload.get("text") or item or "")
                if raw:
                    builder.add_reference(
                        raw,
                        reference_id=str(payload.get("reference_id") or f"{formula_id}:{field_name}:{_stable_hash(raw)[:8]}"),
                        citation_kind=_citation_kind(payload.get("citation_kind") or payload.get("kind")),
                        document_id=str(payload.get("document_id") or document_id),
                        authority_id=str(payload.get("authority_id") or authority_id),
                        version=str(payload.get("version") or version),
                        explicit_target_id=str(payload.get("explicit_target_id") or payload.get("target_id") or ""),
                        explicit_target_document_id=str(payload.get("explicit_target_document_id") or payload.get("target_document_id") or ""),
                        source_node_ids=_source_node_ids(payload) or (formula_id,),
                        span_ids=_strings(payload.get("span_ids", ())),
                        metadata={"field": field_name, "formula_id": formula_id},
                    )

    return builder.to_citation_graph(external_citation_graphs=external_citation_graphs)


def build_legal_ir_citation_table(
    document_or_sample: Mapping[str, Any] | Any,
    *,
    source_map: LegalIRSourceMap | Mapping[str, Any] | None = None,
    external_citation_graphs: Sequence[LegalIRCitationGraph | Mapping[str, Any]] = (),
) -> LegalIRCitationGraph:
    """Compatibility alias for table-oriented callers."""

    return build_legal_ir_citation_graph(
        document_or_sample,
        source_map=source_map,
        external_citation_graphs=external_citation_graphs,
    )


def resolve_legal_ir_citation(
    citation_graph: LegalIRCitationGraph | Mapping[str, Any],
    reference: LegalIRCitationReference | str,
    *,
    external_citation_graphs: Sequence[LegalIRCitationGraph | Mapping[str, Any]] = (),
    source_map: LegalIRSourceMap | Mapping[str, Any] | None = None,
) -> LegalIRCitationResolution:
    """Resolve one citation reference against canonical targets."""

    graph = _citation_graph(citation_graph)
    ref = graph.reference_by_id[str(reference)] if isinstance(reference, str) else reference
    return _resolve_reference(
        graph,
        ref,
        external_citation_graphs=external_citation_graphs,
        source_map=_source_map(source_map) if source_map is not None else None,
    )


def validate_legal_ir_citation_graph(
    citation_graph: LegalIRCitationGraph | Mapping[str, Any],
    *,
    source_map: LegalIRSourceMap | Mapping[str, Any] | None = None,
    external_citation_graphs: Sequence[LegalIRCitationGraph | Mapping[str, Any]] = (),
) -> LegalIRCitationValidationResult:
    """Validate citation graph IDs, resolution integrity, and provenance."""

    graph = _citation_graph(citation_graph)
    resolved_source_map = _source_map(source_map) if source_map is not None else None
    external_graphs = tuple(_citation_graph(item) for item in external_citation_graphs)
    diagnostics: list[LegalIRCitationDiagnostic] = list(graph.diagnostics)
    authorities = graph.authority_by_id
    targets = graph.target_by_id
    references = graph.reference_by_id

    _duplicate_diagnostic("authority", [authority.authority_id for authority in graph.authorities], diagnostics, LegalIRCitationDiagnosticType.DUPLICATE_AUTHORITY_ID)
    _duplicate_diagnostic("target", [target.target_id for target in graph.targets], diagnostics, LegalIRCitationDiagnosticType.DUPLICATE_TARGET_ID)
    _duplicate_diagnostic("reference", [reference.reference_id for reference in graph.references], diagnostics, LegalIRCitationDiagnosticType.DUPLICATE_REFERENCE_ID)

    for target in graph.targets:
        if not target.authority_id:
            diagnostics.append(_diagnostic(LegalIRCitationDiagnosticType.TARGET_AUTHORITY_MISSING, "Citation target has no authority.", target_ids=(target.target_id,), field_path=f"targets.{target.target_id}.authority_id"))
        elif target.authority_id not in authorities and not _external_authority_exists(target.authority_id, external_graphs):
            diagnostics.append(_diagnostic(LegalIRCitationDiagnosticType.TARGET_AUTHORITY_MISSING, "Citation target authority is missing.", target_ids=(target.target_id,), authority_id=target.authority_id, field_path=f"targets.{target.target_id}.authority_id"))
        if not target.version:
            diagnostics.append(_diagnostic(LegalIRCitationDiagnosticType.TARGET_VERSION_MISSING, "Citation target has no version.", target_ids=(target.target_id,), authority_id=target.authority_id, field_path=f"targets.{target.target_id}.version"))
        _append_provenance_diagnostics(diagnostics, target.source_node_ids, resolved_source_map, target_ids=(target.target_id,), authority_id=target.authority_id)

    for reference in graph.references:
        _append_provenance_diagnostics(diagnostics, reference.source_node_ids, resolved_source_map, reference_id=reference.reference_id, authority_id=reference.authority_id)

    for resolution in graph.resolutions:
        if resolution.reference_id not in references:
            diagnostics.append(_diagnostic(LegalIRCitationDiagnosticType.RESOLUTION_TARGET_MISSING, "Resolution references a missing citation reference.", reference_id=resolution.reference_id))
        for target_id in resolution.target_ids:
            if target_id not in targets and not _external_target_exists(target_id, external_graphs):
                diagnostics.append(_diagnostic(LegalIRCitationDiagnosticType.RESOLUTION_TARGET_MISSING, "Resolution points at a missing citation target.", reference_id=resolution.reference_id, target_ids=(target_id,)))
        if resolution.status is not LegalIRCitationResolutionStatus.RESOLVED and not resolution.diagnostics:
            diagnostics.append(_diagnostic(LegalIRCitationDiagnosticType.RESOLUTION_DIAGNOSTIC_MISSING, "Non-resolved citation resolution lacks diagnostics.", reference_id=resolution.reference_id))

    diagnostics = list(_dedupe_diagnostics(diagnostics))
    return LegalIRCitationValidationResult(
        citation_graph_id=graph.citation_graph_id,
        authority_count=len(graph.authorities),
        target_count=len(graph.targets),
        reference_count=len(graph.references),
        resolved_count=sum(1 for resolution in graph.resolutions if resolution.resolved),
        diagnostics=tuple(diagnostics),
    )


def validate_legal_ir_citation_table(
    citation_graph: LegalIRCitationGraph | Mapping[str, Any],
    *,
    source_map: LegalIRSourceMap | Mapping[str, Any] | None = None,
    external_citation_graphs: Sequence[LegalIRCitationGraph | Mapping[str, Any]] = (),
) -> LegalIRCitationValidationResult:
    """Compatibility alias for table-oriented callers."""

    return validate_legal_ir_citation_graph(
        citation_graph,
        source_map=source_map,
        external_citation_graphs=external_citation_graphs,
    )


def legal_ir_citations_allowed_for_use(
    citation_graph: LegalIRCitationGraph | Mapping[str, Any],
    *,
    artifact_use: LegalIRCitationUse | str = LegalIRCitationUse.PROOF_TARGET,
) -> bool:
    """Return whether citation links may feed the requested downstream use."""

    graph = _citation_graph(citation_graph)
    use = _citation_use(artifact_use)
    if use in {LegalIRCitationUse.PROOF_TARGET, LegalIRCitationUse.LEARNED_TARGET}:
        return graph.proof_safe
    return graph.resolved


def assert_legal_ir_citations_resolved(
    citation_graph: LegalIRCitationGraph | Mapping[str, Any],
    *,
    artifact_use: LegalIRCitationUse | str = LegalIRCitationUse.PROOF_TARGET,
) -> LegalIRCitationGraph:
    """Return a graph or raise if references cannot be treated as resolved law."""

    graph = _citation_graph(citation_graph)
    if not legal_ir_citations_allowed_for_use(graph, artifact_use=artifact_use):
        codes = ",".join(issue.code for issue in graph.diagnostics) or "unresolved_citations"
        raise ValueError(f"LegalIR citations are not resolved for {str(artifact_use)}: {codes}")
    return graph


def merge_legal_ir_citation_graphs(
    citation_graphs: Sequence[LegalIRCitationGraph | Mapping[str, Any]],
    *,
    citation_graph_id: str = "",
) -> LegalIRCitationGraph:
    """Merge canonical citation graphs for cross-document linking."""

    graphs = tuple(_citation_graph(graph) for graph in citation_graphs)
    return LegalIRCitationGraph(
        citation_graph_id=citation_graph_id or "lir-citation-graph-" + _stable_hash([graph.citation_graph_id for graph in graphs])[:24],
        authorities=tuple(_unique_records(authority for graph in graphs for authority in graph.authorities)),
        targets=tuple(_unique_records(target for graph in graphs for target in graph.targets)),
        references=tuple(_unique_records(reference for graph in graphs for reference in graph.references)),
        resolutions=tuple(_unique_records(resolution for graph in graphs for resolution in graph.resolutions)),
        diagnostics=tuple(_dedupe_diagnostics(issue for graph in graphs for issue in graph.diagnostics)),
        source_map_id=",".join(_unique(graph.source_map_id for graph in graphs if graph.source_map_id)),
        metadata={"merged_citation_graph_ids": [graph.citation_graph_id for graph in graphs]},
    )


def _resolve_reference(
    graph: LegalIRCitationGraph,
    reference: LegalIRCitationReference,
    *,
    external_citation_graphs: Sequence[LegalIRCitationGraph | Mapping[str, Any]] = (),
    source_map: LegalIRSourceMap | None = None,
) -> LegalIRCitationResolution:
    external_graphs = tuple(_citation_graph(item) for item in external_citation_graphs)
    canonical = normalize_legal_citation(reference.raw_text, default_authority=reference.authority_id)
    candidates, confidence = _candidate_targets(graph, reference, canonical, external_graphs)
    diagnostics: list[LegalIRCitationDiagnostic] = []
    source_traces = _source_traces_for_reference(source_map, reference, candidates)
    source_node_ids = tuple(_unique((*reference.source_node_ids, *(node for target in candidates for node in target.source_node_ids))))
    source_span_ids = tuple(
        _unique(
            (
                *reference.span_ids,
                *(span_id for target in candidates for span_id in target.span_ids),
                *(span.span_id for trace in source_traces for span in trace.source_spans),
            )
        )
    )

    if not candidates:
        diagnostics.append(
            _diagnostic(
                LegalIRCitationDiagnosticType.UNRESOLVED_CITATION,
                f"Citation reference {reference.reference_id!r} does not resolve to known law.",
                reference_id=reference.reference_id,
                authority_id=reference.authority_id,
                document_id=reference.document_id,
                source_node_ids=source_node_ids,
                source_span_ids=source_span_ids,
            )
        )
        return LegalIRCitationResolution(
            reference_id=reference.reference_id,
            status=LegalIRCitationResolutionStatus.UNRESOLVED,
            canonical_citation=canonical,
            citation_kind=reference.citation_kind,
            confidence=0.0,
            diagnostics=tuple(_dedupe_diagnostics(diagnostics)),
            source_traces=source_traces,
        )

    if reference.citation_kind is LegalIRCitationKind.REPEALED:
        diagnostics.append(
            _diagnostic(
                LegalIRCitationDiagnosticType.REPEALED_CITATION,
                f"Citation reference {reference.reference_id!r} is marked as repealed law.",
                reference_id=reference.reference_id,
                target_ids=tuple(target.target_id for target in candidates),
                authority_id=candidates[0].authority_id,
                document_id=reference.document_id,
                source_node_ids=source_node_ids,
                source_span_ids=source_span_ids,
            )
        )
        return _resolution(reference, canonical, candidates, LegalIRCitationResolutionStatus.REPEALED, confidence, diagnostics, source_traces)

    repealed = tuple(target for target in candidates if target.repealed)
    active = tuple(target for target in candidates if not target.repealed)
    if repealed and not active:
        diagnostics.append(
            _diagnostic(
                LegalIRCitationDiagnosticType.REPEALED_CITATION,
                f"Citation reference {reference.reference_id!r} points only to repealed law.",
                reference_id=reference.reference_id,
                target_ids=tuple(target.target_id for target in candidates),
                authority_id=candidates[0].authority_id,
                document_id=reference.document_id,
                source_node_ids=source_node_ids,
                source_span_ids=source_span_ids,
            )
        )
        return _resolution(reference, canonical, candidates, LegalIRCitationResolutionStatus.REPEALED, confidence, diagnostics, source_traces)

    collapsed = active
    if reference.citation_kind is not LegalIRCitationKind.RANGE and len(collapsed) > 1:
        diagnostics.append(
            _diagnostic(
                LegalIRCitationDiagnosticType.AMBIGUOUS_CITATION,
                f"Citation reference {reference.reference_id!r} resolves to multiple active targets.",
                reference_id=reference.reference_id,
                target_ids=tuple(target.target_id for target in collapsed),
                authority_id=collapsed[0].authority_id,
                document_id=reference.document_id,
                source_node_ids=source_node_ids,
                source_span_ids=source_span_ids,
            )
        )
        return _resolution(reference, canonical, collapsed, LegalIRCitationResolutionStatus.AMBIGUOUS, confidence, diagnostics, source_traces)

    return _resolution(reference, canonical, collapsed, LegalIRCitationResolutionStatus.RESOLVED, confidence, diagnostics, source_traces)


def _candidate_targets(
    graph: LegalIRCitationGraph,
    reference: LegalIRCitationReference,
    canonical: str,
    external_graphs: Sequence[LegalIRCitationGraph],
) -> tuple[tuple[LegalIRCitationTarget, ...], float]:
    all_targets = tuple(graph.targets) + tuple(target for external in external_graphs for target in external.targets)
    if reference.explicit_target_id:
        explicit = tuple(target for target in all_targets if target.target_id == reference.explicit_target_id)
        return explicit, 1.0 if explicit else 0.0
    exact = tuple(target for target in all_targets if _target_matches_exact(target, reference, canonical))
    if exact:
        return tuple(_unique_records(exact)), 1.0
    alias = tuple(target for target in all_targets if canonical in target.aliases and _target_scope_matches(target, reference))
    if alias:
        return tuple(_unique_records(alias)), 0.92
    if reference.citation_kind is LegalIRCitationKind.RANGE or _looks_like_range(canonical):
        ranged = tuple(target for target in all_targets if _target_in_range(target, canonical, reference))
        if ranged:
            return tuple(_unique_records(ranged)), 0.9
    subsection_parent = tuple(target for target in all_targets if _target_matches_parent_section(target, reference, canonical))
    if subsection_parent:
        return tuple(_unique_records(subsection_parent)), 0.84
    return (), 0.0


def _target_matches_exact(
    target: LegalIRCitationTarget,
    reference: LegalIRCitationReference,
    canonical: str,
) -> bool:
    if target.canonical_key != canonical:
        return False
    return _target_scope_matches(target, reference)


def _target_scope_matches(target: LegalIRCitationTarget, reference: LegalIRCitationReference) -> bool:
    if reference.authority_id and target.authority_id != reference.authority_id:
        return False
    if reference.version and target.version != reference.version:
        return False
    if reference.explicit_target_document_id and target.document_id != reference.explicit_target_document_id:
        return False
    return True


def _target_in_range(
    target: LegalIRCitationTarget,
    canonical_range: str,
    reference: LegalIRCitationReference,
) -> bool:
    parsed = parse_legal_citation(canonical_range)
    start = str(parsed.get("range_start") or "")
    end = str(parsed.get("range_end") or "")
    if not start or not end or not _target_scope_matches(target, reference):
        return False
    target_key = target.canonical_key
    if target_key in {start, end}:
        return True
    start_parts = parse_legal_citation(start)
    end_parts = parse_legal_citation(end)
    target_parts = parse_legal_citation(target_key)
    if _authority_id_for_citation(start) != _authority_id_for_citation(target_key):
        return False
    if str(start_parts.get("title") or "") != str(target_parts.get("title") or ""):
        return False
    if str(end_parts.get("title") or "") != str(target_parts.get("title") or ""):
        return False
    return _section_sort_key(str(start_parts.get("section") or "")) <= _section_sort_key(str(target_parts.get("section") or "")) <= _section_sort_key(str(end_parts.get("section") or ""))


def _target_matches_parent_section(
    target: LegalIRCitationTarget,
    reference: LegalIRCitationReference,
    canonical: str,
) -> bool:
    parsed_ref = parse_legal_citation(canonical)
    parsed_target = parse_legal_citation(target.canonical_key)
    if not parsed_ref.get("subsections") or parsed_target.get("subsections"):
        return False
    if _authority_id_for_citation(canonical) != _authority_id_for_citation(target.canonical_key):
        return False
    if str(parsed_ref.get("title") or "") != str(parsed_target.get("title") or ""):
        return False
    if str(parsed_ref.get("section") or "") != str(parsed_target.get("section") or ""):
        return False
    return _target_scope_matches(target, reference)


def _resolution(
    reference: LegalIRCitationReference,
    canonical: str,
    targets: Sequence[LegalIRCitationTarget],
    status: LegalIRCitationResolutionStatus,
    confidence: float,
    diagnostics: Sequence[LegalIRCitationDiagnostic],
    source_traces: Sequence[LegalIRFactTrace],
) -> LegalIRCitationResolution:
    target_tuple = tuple(_unique_records(targets))
    authority_id = target_tuple[0].authority_id if target_tuple else reference.authority_id
    version = ",".join(_unique(target.version for target in target_tuple if target.version)) or reference.version
    return LegalIRCitationResolution(
        reference_id=reference.reference_id,
        status=status,
        canonical_citation=canonical,
        target_ids=tuple(target.target_id for target in target_tuple),
        authority_id=authority_id,
        version=version,
        citation_kind=reference.citation_kind,
        confidence=float(confidence if status is LegalIRCitationResolutionStatus.RESOLVED else 0.0),
        diagnostics=tuple(_dedupe_diagnostics(diagnostics)),
        source_traces=tuple(source_traces),
    )


def _normalize_range_citation(text: str, *, default_authority: str = "") -> str:
    match = _RANGE_SPLIT_RE.search(text)
    if not match:
        compact_ors = re.match(r"^\s*ORS\s+(?P<left>\d+(?:\.\d+)?)-(?P<right>\d+(?:\.\d+)?)(?P<subs>(?:\([A-Za-z0-9]+\))*)\s*$", text, re.IGNORECASE)
        if compact_ors:
            left_canonical = normalize_legal_citation(f"ORS {compact_ors.group('left')}")
            right_canonical = normalize_legal_citation(f"ORS {compact_ors.group('right')}{compact_ors.group('subs')}")
            return f"{left_canonical}-{right_canonical}"
        return text
    left = text[: match.start()].strip()
    right = text[match.end() :].strip()
    left_canonical = normalize_legal_citation(left, default_authority=default_authority)
    right_canonical = normalize_legal_citation(right, default_authority=_authority_id_for_citation(left_canonical) or default_authority)
    return f"{left_canonical}-{right_canonical}"


def _strip_citation_context(text: str) -> str:
    cleaned = str(text or "").strip()
    cleaned = re.sub(
        r"^(?:incorporated\s+by\s+reference|incorporates?|see|pursuant\s+to)\s*:?\s+",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(
        r"^(?:former|repealed|superseded)\s+",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    if ":" in cleaned:
        tail = cleaned.rsplit(":", 1)[1].strip()
        if _authority_id_for_citation(tail) or _BARE_SECTION_RE.match(tail):
            cleaned = tail
    return cleaned


def _looks_like_range(text: str) -> bool:
    if "-" not in text:
        return False
    left, right = text.split("-", 1)
    return bool(_authority_id_for_citation(left) and _authority_id_for_citation(right))


def _canonical_authority_prefix(authority_id: str) -> str:
    normalized = str(authority_id or "").strip().upper()
    for prefix in ("ORS", "OAR", "U.S.C.", "C.F.R."):
        if normalized == prefix or normalized.replace(".", "") == prefix.replace(".", ""):
            return prefix
    if normalized in {"USC", "UNITED STATES CODE"}:
        return "U.S.C."
    if normalized in {"CFR", "CODE OF FEDERAL REGULATIONS"}:
        return "C.F.R."
    return normalized


def _authority_id_for_citation(citation: str) -> str:
    text = str(citation or "").strip().upper()
    if text.startswith("ORS "):
        return "ORS"
    if text.startswith("OAR "):
        return "OAR"
    if " U.S.C. " in text:
        return "U.S.C."
    if " C.F.R. " in text:
        return "C.F.R."
    return ""


def _canonical_text_key(text: str) -> str:
    cleaned = re.sub(r"\s+", " ", str(text or "").strip())
    words = _WORD_RE.findall(cleaned)
    if not words:
        return cleaned.upper()
    return " ".join(words).upper()


def _section_sort_key(section: str) -> tuple[Any, ...]:
    parts: list[Any] = []
    for item in re.split(r"([0-9]+)", str(section or "")):
        if not item:
            continue
        parts.append(int(item) if item.isdigit() else item.lower())
    return tuple(parts)


def _source_traces_for_reference(
    source_map: LegalIRSourceMap | None,
    reference: LegalIRCitationReference,
    targets: Sequence[LegalIRCitationTarget],
) -> tuple[LegalIRFactTrace, ...]:
    if source_map is None:
        return ()
    traces: list[LegalIRFactTrace] = []
    for node_id in _unique((*reference.source_node_ids, *(node for target in targets for node in target.source_node_ids))):
        trace = trace_legal_ir_fact(source_map, node_id)
        traces.append(trace)
    return tuple(traces)


def _append_provenance_diagnostics(
    diagnostics: list[LegalIRCitationDiagnostic],
    source_node_ids: Sequence[str],
    source_map: LegalIRSourceMap | None,
    *,
    reference_id: str = "",
    target_ids: Sequence[str] = (),
    authority_id: str = "",
) -> None:
    nodes = tuple(_unique(_strings(source_node_ids)))
    if not nodes:
        diagnostics.append(
            _diagnostic(
                LegalIRCitationDiagnosticType.SOURCE_PROVENANCE_MISSING,
                "Citation record has no source-map node lineage.",
                reference_id=reference_id,
                target_ids=target_ids,
                authority_id=authority_id,
            )
        )
        return
    if source_map is None:
        return
    for node_id in nodes:
        trace = trace_legal_ir_fact(source_map, node_id)
        if not trace.traceable:
            diagnostics.append(
                _diagnostic(
                    LegalIRCitationDiagnosticType.SOURCE_PROVENANCE_UNTRACEABLE,
                    "Citation source-map lineage is not traceable.",
                    reference_id=reference_id,
                    target_ids=target_ids,
                    authority_id=authority_id,
                    source_node_ids=(node_id,),
                    source_span_ids=tuple(span.span_id for span in trace.source_spans),
                )
            )


def _diagnostic(
    diagnostic_type: LegalIRCitationDiagnosticType,
    message: str,
    *,
    severity: str = "error",
    reference_id: str = "",
    target_ids: Sequence[str] = (),
    authority_id: str = "",
    document_id: str = "",
    source_node_ids: Sequence[str] = (),
    source_span_ids: Sequence[str] = (),
    field_path: str = "",
) -> LegalIRCitationDiagnostic:
    return LegalIRCitationDiagnostic(
        diagnostic_type=diagnostic_type,
        message=message,
        severity=severity,
        reference_id=str(reference_id or ""),
        target_ids=tuple(_unique(_strings(target_ids))),
        authority_id=str(authority_id or ""),
        document_id=str(document_id or ""),
        source_node_ids=tuple(_unique(_strings(source_node_ids))),
        source_span_ids=tuple(_unique(_strings(source_span_ids))),
        field_path=str(field_path or ""),
    )


def _dedupe_diagnostics(items: Iterable[LegalIRCitationDiagnostic]) -> tuple[LegalIRCitationDiagnostic, ...]:
    seen: set[tuple[Any, ...]] = set()
    result: list[LegalIRCitationDiagnostic] = []
    for item in items:
        key = (
            item.diagnostic_type.value,
            item.reference_id,
            item.target_ids,
            item.authority_id,
            item.field_path,
            item.message,
        )
        if key not in seen:
            seen.add(key)
            result.append(item)
    return tuple(result)


def _duplicate_diagnostic(
    kind: str,
    values: Sequence[str],
    diagnostics: list[LegalIRCitationDiagnostic],
    diagnostic_type: LegalIRCitationDiagnosticType,
) -> None:
    seen: set[str] = set()
    for value in values:
        if value in seen:
            diagnostics.append(_diagnostic(diagnostic_type, f"Duplicate {kind} ID {value!r}.", field_path=kind))
        seen.add(value)


def _external_authority_exists(authority_id: str, graphs: Sequence[LegalIRCitationGraph]) -> bool:
    return any(authority_id in graph.authority_by_id for graph in graphs)


def _external_target_exists(target_id: str, graphs: Sequence[LegalIRCitationGraph]) -> bool:
    return any(target_id in graph.target_by_id for graph in graphs)


def _citation_graph(value: LegalIRCitationGraph | Mapping[str, Any]) -> LegalIRCitationGraph:
    return value if isinstance(value, LegalIRCitationGraph) else LegalIRCitationGraph.from_dict(_mapping(value))


def _source_map(value: LegalIRSourceMap | Mapping[str, Any]) -> LegalIRSourceMap:
    return value if isinstance(value, LegalIRSourceMap) else LegalIRSourceMap.from_dict(_mapping(value))


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _sequence(value: Any) -> tuple[Any, ...]:
    if value is None:
        return ()
    if isinstance(value, (str, bytes, bytearray, Mapping)):
        return (value,)
    if isinstance(value, Sequence):
        return tuple(value)
    return (value,)


def _strings(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,) if value else ()
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        return tuple(str(item) for item in value if str(item))
    return (str(value),) if str(value) else ()


def _unique(values: Iterable[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value or "")
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return tuple(result)


def _unique_records(records: Iterable[Any]) -> tuple[Any, ...]:
    seen: set[str] = set()
    result: list[Any] = []
    for record in records:
        key = _stable_hash(record.to_dict() if hasattr(record, "to_dict") else record)
        if key not in seen:
            seen.add(key)
            result.append(record)
    return tuple(result)


def _stable_hash(value: Any) -> str:
    payload = json.dumps(_canonical_json_value(value), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _canonical_json_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _canonical_json_value(value[key]) for key in sorted(value)}
    if isinstance(value, tuple):
        return [_canonical_json_value(item) for item in value]
    if isinstance(value, list):
        return [_canonical_json_value(item) for item in value]
    if isinstance(value, Enum):
        return value.value
    return value


def _payload_mapping(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    if hasattr(value, "to_dict"):
        return _mapping(value.to_dict())
    return {}


def _reference_payload(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    return {"raw_text": value}


def _source_node_ids(payload: Mapping[str, Any]) -> tuple[str, ...]:
    return tuple(
        _unique(
            (
                *_strings(payload.get("source_node_ids", ())),
                *_strings(payload.get("node_ids", ())),
                *_strings(payload.get("formula_ids", ())),
                *_strings(payload.get("formula_id", "")),
                *_strings(payload.get("node_id", "")),
            )
        )
    )


def _citation_kind(value: Any) -> LegalIRCitationKind:
    try:
        return value if isinstance(value, LegalIRCitationKind) else LegalIRCitationKind(str(value or LegalIRCitationKind.UNKNOWN.value))
    except ValueError:
        return LegalIRCitationKind.UNKNOWN


def _resolution_status(value: Any) -> LegalIRCitationResolutionStatus:
    try:
        return value if isinstance(value, LegalIRCitationResolutionStatus) else LegalIRCitationResolutionStatus(str(value or LegalIRCitationResolutionStatus.UNRESOLVED.value))
    except ValueError:
        return LegalIRCitationResolutionStatus.UNRESOLVED


def _diagnostic_type(value: Any) -> LegalIRCitationDiagnosticType:
    try:
        return value if isinstance(value, LegalIRCitationDiagnosticType) else LegalIRCitationDiagnosticType(str(value or LegalIRCitationDiagnosticType.UNRESOLVED_CITATION.value))
    except ValueError:
        return LegalIRCitationDiagnosticType.UNRESOLVED_CITATION


def _citation_use(value: Any) -> LegalIRCitationUse:
    try:
        return value if isinstance(value, LegalIRCitationUse) else LegalIRCitationUse(str(value or LegalIRCitationUse.PROOF_TARGET.value))
    except ValueError:
        return LegalIRCitationUse.PROOF_TARGET


def _fact_trace_from_dict(data: Mapping[str, Any]) -> LegalIRFactTrace:
    return LegalIRFactTrace(
        fact_id=str(data.get("fact_id") or ""),
        found=bool(data.get("found")),
        derived=bool(data.get("derived")),
        source_spans=tuple(
            LegalIRProvenanceSpan.from_dict(_mapping(item))
            for item in data.get("source_spans", []) or []
        ),
        transformation_steps=tuple(
            LegalIRSourceMapTransform.from_dict(_mapping(item))
            for item in data.get("transformation_steps", []) or []
        ),
        visited_node_ids=tuple(_unique(_strings(data.get("visited_node_ids", ())))),
        issues=tuple(
            LegalIRSourceMapIssue(
                code=str(_mapping(item).get("code") or ""),
                message=str(_mapping(item).get("message") or ""),
                field_path=str(_mapping(item).get("field_path") or ""),
                severity=str(_mapping(item).get("severity") or "error"),
            )
            for item in data.get("issues", []) or []
        ),
    )


canonicalize_legal_citation = normalize_legal_citation
link_legal_ir_citations = build_legal_ir_citation_graph
validate_legal_ir_citations = validate_legal_ir_citation_graph


__all__ = [
    "LEGAL_IR_CITATION_LINKER_SCHEMA_VERSION",
    "LegalIRAuthority",
    "LegalIRCitationDiagnostic",
    "LegalIRCitationDiagnosticType",
    "LegalIRCitationGraph",
    "LegalIRCitationGraphBuilder",
    "LegalIRCitationKind",
    "LegalIRCitationLinker",
    "LegalIRCitationReference",
    "LegalIRCitationResolution",
    "LegalIRCitationResolutionStatus",
    "LegalIRCitationTable",
    "LegalIRCitationTableBuilder",
    "LegalIRCitationTarget",
    "LegalIRCitationUse",
    "LegalIRCitationValidationResult",
    "assert_legal_ir_citations_resolved",
    "build_legal_ir_citation_graph",
    "build_legal_ir_citation_table",
    "canonicalize_legal_citation",
    "infer_legal_citation_kind",
    "legal_ir_citations_allowed_for_use",
    "link_legal_ir_citations",
    "merge_legal_ir_citation_graphs",
    "normalize_legal_citation",
    "parse_legal_citation",
    "resolve_legal_ir_citation",
    "validate_legal_ir_citation_graph",
    "validate_legal_ir_citation_table",
    "validate_legal_ir_citations",
]
