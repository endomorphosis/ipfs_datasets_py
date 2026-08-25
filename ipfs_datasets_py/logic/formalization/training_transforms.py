"""Compiler, decompiler, translation, and ordered round-trip trace contracts."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, ClassVar, TypeAlias

from .training_shared import (
    _ALLOWED_AUTHORITY_TRANSITIONS,
    IR_COMPILER_TRACE_INTERFACE,
    IR_COMPILER_TRACE_SCHEMA_VERSION,
    IR_DECOMPILER_TRACE_INTERFACE,
    IR_DECOMPILER_TRACE_SCHEMA_VERSION,
    IR_ROUND_TRIP_TRACE_INTERFACE,
    IR_ROUND_TRIP_TRACE_SCHEMA_VERSION,
    IR_TRANSLATION_TRACE_INTERFACE,
    IR_TRANSLATION_TRACE_SCHEMA_VERSION,
    TRACE_REFERENCE_INTERFACE,
    TRACE_REFERENCE_SCHEMA_VERSION,
    ExampleKind,
    LabelEvidence,
    LineageBinding,
    PreservationClass,
    ProducerKind,
    SemanticRelationship,
    StatementAuthority,
    StatementBinding,
    ToolBinding,
    TraceStatus,
    TrainingContractValidationError,
    _bind_statement_to_lineage,
    _CanonicalRecord,
    _digest,
    _enum,
    _identifier,
    _mapping,
    _normalize_evidence,
    _reject_unknown,
    _sequence,
    _text,
    _unique_texts,
    _validate_evidence_subjects,
)


def _forbid_authority_increase(
    source: StatementAuthority, target: StatementAuthority, record_name: str
) -> None:
    if target not in _ALLOWED_AUTHORITY_TRANSITIONS[source]:
        raise TrainingContractValidationError(
            f"{record_name} cannot increase statement authority from "
            f"{source.value} to {target.value}"
        )


@dataclass(frozen=True, slots=True)
class _TransformationTrace(_CanonicalRecord):
    """Shared shape; concrete subclasses keep direction/schema identities closed."""

    INTERFACE: ClassVar[str] = "IRTransformationTrace@internal"
    SCHEMA_VERSION: ClassVar[str] = "ir-transformation-trace/internal"
    IDENTITY_SUFFIX: ClassVar[str] = "transformation-internal"
    COLLECTION_SCHEMA: ClassVar[Mapping[str, str]] = {
        "/evidence": "set-like",
        "/unresolved_losses": "set-like",
        "/diagnostics": "set-like",
    }
    KIND: ClassVar[ExampleKind]
    ALLOWED_PRODUCERS: ClassVar[frozenset[ProducerKind]] = frozenset(ProducerKind)

    trace_id: str
    lineage: LineageBinding
    source: StatementBinding
    target: StatementBinding | None
    producer: ToolBinding
    source_authority: StatementAuthority
    target_authority: StatementAuthority
    relationship: SemanticRelationship
    preservation: PreservationClass
    status: TraceStatus
    evidence: tuple[LabelEvidence, ...] = ()
    unresolved_losses: tuple[str, ...] = ()
    diagnostics: tuple[str, ...] = ()
    schema_version: str = "ir-transformation-trace/internal"

    def __post_init__(self) -> None:
        object.__setattr__(self, "trace_id", _identifier(self.trace_id, "trace_id"))
        if not isinstance(self.lineage, LineageBinding):
            object.__setattr__(
                self, "lineage", LineageBinding.from_dict(_mapping(self.lineage, "lineage"))
            )
        if not isinstance(self.source, StatementBinding):
            object.__setattr__(
                self, "source", StatementBinding.from_dict(_mapping(self.source, "source"))
            )
        if self.target is not None and not isinstance(self.target, StatementBinding):
            object.__setattr__(
                self, "target", StatementBinding.from_dict(_mapping(self.target, "target"))
            )
        if not isinstance(self.producer, ToolBinding):
            object.__setattr__(
                self, "producer", ToolBinding.from_dict(_mapping(self.producer, "producer"))
            )
        object.__setattr__(
            self,
            "source_authority",
            _enum(self.source_authority, StatementAuthority, "source_authority"),
        )
        object.__setattr__(
            self,
            "target_authority",
            _enum(self.target_authority, StatementAuthority, "target_authority"),
        )
        object.__setattr__(
            self,
            "relationship",
            _enum(self.relationship, SemanticRelationship, "relationship"),
        )
        object.__setattr__(
            self,
            "preservation",
            _enum(self.preservation, PreservationClass, "preservation"),
        )
        object.__setattr__(self, "status", _enum(self.status, TraceStatus, "status"))
        object.__setattr__(self, "evidence", _normalize_evidence(self.evidence))
        object.__setattr__(
            self,
            "unresolved_losses",
            _unique_texts(self.unresolved_losses, "unresolved_losses"),
        )
        object.__setattr__(self, "diagnostics", _unique_texts(self.diagnostics, "diagnostics"))
        object.__setattr__(self, "schema_version", _text(self.schema_version, "schema_version"))
        if self.schema_version != self.SCHEMA_VERSION:
            raise TrainingContractValidationError(
                f"unsupported {self.KIND.value} trace schema: {self.schema_version!r}"
            )
        _bind_statement_to_lineage(self.source, self.lineage)
        if self.target is not None:
            _bind_statement_to_lineage(self.target, self.lineage)
            if (
                self.source.statement_id == self.target.statement_id
                and self.source.statement_digest == self.target.statement_digest
            ):
                raise TrainingContractValidationError(
                    f"{self.KIND.value} source and target must be distinct bindings"
                )
            _forbid_authority_increase(
                self.source_authority, self.target_authority, f"{self.KIND.value} trace"
            )
            _validate_evidence_subjects(
                self.evidence, (self.source, self.target), self.relationship
            )
        else:
            if self.target_authority is not StatementAuthority.UNKNOWN:
                raise TrainingContractValidationError(
                    "a trace without a target must keep target authority unknown"
                )
            if self.relationship is not SemanticRelationship.UNKNOWN:
                raise TrainingContractValidationError(
                    "a trace without a target cannot claim a semantic relationship"
                )
            _validate_evidence_subjects(self.evidence, (self.source,))
        if self.producer.producer_kind not in self.ALLOWED_PRODUCERS:
            raise TrainingContractValidationError(
                f"{self.producer.producer_kind.value} cannot produce a {self.KIND.value} trace"
            )
        if self.producer.producer_kind is ProducerKind.MODEL and self.target_authority not in {
            StatementAuthority.UNKNOWN,
            StatementAuthority.MODEL_CANDIDATE,
        }:
            raise TrainingContractValidationError(
                "model transformations may only emit candidate statement authority"
            )
        if self.status is TraceStatus.SUCCEEDED and self.target is None:
            raise TrainingContractValidationError("a successful trace must bind a target")
        exact_relationships = {
            SemanticRelationship.EXACT,
            SemanticRelationship.ALPHA_EQUIVALENT,
            SemanticRelationship.CANONICAL_EQUIVALENT,
        }
        unresolved_preservation = {
            PreservationClass.UNKNOWN,
            PreservationClass.EQUISATISFIABLE,
            PreservationClass.HEURISTIC,
            PreservationClass.OVER_APPROXIMATION,
            PreservationClass.UNDER_APPROXIMATION,
            PreservationClass.UNSUPPORTED,
        }
        if self.relationship in exact_relationships and (
            self.unresolved_losses or self.preservation in unresolved_preservation
        ):
            raise TrainingContractValidationError(
                "an exact relationship cannot carry unresolved or non-exact loss"
            )
        if self.relationship in {
            SemanticRelationship.NON_EQUIVALENT,
            SemanticRelationship.CONTRADICTS,
            SemanticRelationship.NOT_ENTAILED,
        } and self.preservation in {
            PreservationClass.LOSSLESS,
            PreservationClass.SYNTACTIC,
            PreservationClass.STRUCTURAL,
            PreservationClass.SEMANTIC,
            PreservationClass.PROOF,
            PreservationClass.EQUISATISFIABLE,
        }:
            raise TrainingContractValidationError(
                "negative relationships cannot claim positive preservation"
            )
        if (
            self.preservation is PreservationClass.EQUISATISFIABLE
            and self.relationship is not SemanticRelationship.EQUISATISFIABLE
        ):
            raise TrainingContractValidationError(
                "equisatisfiable preservation requires an equisatisfiable relationship"
            )
        if self.preservation is PreservationClass.LOSSLESS and self.unresolved_losses:
            raise TrainingContractValidationError(
                "lossless preservation cannot carry unresolved losses"
            )
        if (
            self.preservation is PreservationClass.UNSUPPORTED
            and self.status is TraceStatus.SUCCEEDED
        ):
            raise TrainingContractValidationError(
                "unsupported transformation cannot have succeeded"
            )

    @property
    def kind(self) -> ExampleKind:
        return self.KIND

    def to_dict(self) -> dict[str, Any]:
        return {
            "diagnostics": list(self.diagnostics),
            "evidence": [item.to_dict() for item in self.evidence],
            "lineage": self.lineage.to_dict(),
            "preservation": self.preservation.value,
            "producer": self.producer.to_dict(),
            "relationship": self.relationship.value,
            "schema_version": self.schema_version,
            "source": self.source.to_dict(),
            "source_authority": self.source_authority.value,
            "status": self.status.value,
            "target": self.target.to_dict() if self.target is not None else None,
            "target_authority": self.target_authority.value,
            "trace_id": self.trace_id,
            "unresolved_losses": list(self.unresolved_losses),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> Any:
        value = _mapping(value, f"{cls.KIND.value} trace")
        _reject_unknown(
            value,
            frozenset(
                {
                    "diagnostics",
                    "evidence",
                    "lineage",
                    "preservation",
                    "producer",
                    "relationship",
                    "schema_version",
                    "source",
                    "source_authority",
                    "status",
                    "target",
                    "target_authority",
                    "trace_id",
                    "unresolved_losses",
                }
            ),
            f"{cls.KIND.value} trace",
        )
        target = value.get("target")
        return cls(
            trace_id=value.get("trace_id", ""),
            lineage=LineageBinding.from_dict(_mapping(value.get("lineage", {}), "lineage")),
            source=StatementBinding.from_dict(_mapping(value.get("source", {}), "source")),
            target=(
                StatementBinding.from_dict(_mapping(target, "target"))
                if target is not None
                else None
            ),
            producer=ToolBinding.from_dict(_mapping(value.get("producer", {}), "producer")),
            source_authority=value.get("source_authority", ""),
            target_authority=value.get("target_authority", ""),
            relationship=value.get("relationship", SemanticRelationship.UNKNOWN.value),
            preservation=value.get("preservation", PreservationClass.UNKNOWN.value),
            status=value.get("status", TraceStatus.UNKNOWN.value),
            evidence=tuple(_sequence(value.get("evidence", ()), "evidence")),
            unresolved_losses=tuple(
                _sequence(value.get("unresolved_losses", ()), "unresolved_losses")
            ),
            diagnostics=tuple(_sequence(value.get("diagnostics", ()), "diagnostics")),
            schema_version=value.get("schema_version", cls.SCHEMA_VERSION),
        )


@dataclass(frozen=True, slots=True)
class IRCompilerTrace(_TransformationTrace):
    INTERFACE: ClassVar[str] = IR_COMPILER_TRACE_INTERFACE
    SCHEMA_VERSION: ClassVar[str] = IR_COMPILER_TRACE_SCHEMA_VERSION
    IDENTITY_SUFFIX: ClassVar[str] = "compiler-trace"
    KIND: ClassVar[ExampleKind] = ExampleKind.COMPILER
    ALLOWED_PRODUCERS: ClassVar[frozenset[ProducerKind]] = frozenset(
        {
            ProducerKind.DETERMINISTIC_COMPILER,
            ProducerKind.GENERIC_DETERMINISTIC,
            ProducerKind.MODEL,
        }
    )

    schema_version: str = IR_COMPILER_TRACE_SCHEMA_VERSION


@dataclass(frozen=True, slots=True)
class IRDecompilerTrace(_TransformationTrace):
    INTERFACE: ClassVar[str] = IR_DECOMPILER_TRACE_INTERFACE
    SCHEMA_VERSION: ClassVar[str] = IR_DECOMPILER_TRACE_SCHEMA_VERSION
    IDENTITY_SUFFIX: ClassVar[str] = "decompiler-trace"
    KIND: ClassVar[ExampleKind] = ExampleKind.DECOMPILER
    ALLOWED_PRODUCERS: ClassVar[frozenset[ProducerKind]] = frozenset(
        {
            ProducerKind.DETERMINISTIC_DECOMPILER,
            ProducerKind.GENERIC_DETERMINISTIC,
            ProducerKind.MODEL,
        }
    )

    schema_version: str = IR_DECOMPILER_TRACE_SCHEMA_VERSION


@dataclass(frozen=True, slots=True)
class IRTranslationTrace(_TransformationTrace):
    INTERFACE: ClassVar[str] = IR_TRANSLATION_TRACE_INTERFACE
    SCHEMA_VERSION: ClassVar[str] = IR_TRANSLATION_TRACE_SCHEMA_VERSION
    IDENTITY_SUFFIX: ClassVar[str] = "translation-trace"
    KIND: ClassVar[ExampleKind] = ExampleKind.TRANSLATION
    ALLOWED_PRODUCERS: ClassVar[frozenset[ProducerKind]] = frozenset(
        {
            ProducerKind.DETERMINISTIC_TRANSLATOR,
            ProducerKind.GENERIC_DETERMINISTIC,
            ProducerKind.MODEL,
        }
    )

    schema_version: str = IR_TRANSLATION_TRACE_SCHEMA_VERSION


TransformationTrace: TypeAlias = IRCompilerTrace | IRDecompilerTrace | IRTranslationTrace


@dataclass(frozen=True, slots=True)
class TraceReference(_CanonicalRecord):
    """Self-verifying transformation reference used by an ordered round trip."""

    INTERFACE: ClassVar[str] = TRACE_REFERENCE_INTERFACE
    SCHEMA_VERSION: ClassVar[str] = TRACE_REFERENCE_SCHEMA_VERSION
    IDENTITY_SUFFIX: ClassVar[str] = "trace-reference"
    COLLECTION_SCHEMA: ClassVar[Mapping[str, str]] = {
        "/trace/evidence": "set-like",
        "/trace/unresolved_losses": "set-like",
        "/trace/diagnostics": "set-like",
    }

    trace_id: str
    trace_digest: str
    lineage_digest: str
    kind: ExampleKind
    source_statement_id: str
    source_statement_digest: str
    target_statement_id: str
    target_statement_digest: str
    status: TraceStatus
    trace: TransformationTrace
    schema_version: str = TRACE_REFERENCE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "trace_id", _identifier(self.trace_id, "trace_id"))
        object.__setattr__(self, "trace_digest", _digest(self.trace_digest, "trace_digest"))
        object.__setattr__(self, "lineage_digest", _digest(self.lineage_digest, "lineage_digest"))
        object.__setattr__(self, "kind", _enum(self.kind, ExampleKind, "kind"))
        trace_classes = {
            ExampleKind.COMPILER: IRCompilerTrace,
            ExampleKind.DECOMPILER: IRDecompilerTrace,
            ExampleKind.TRANSLATION: IRTranslationTrace,
        }
        expected_cls = trace_classes.get(self.kind)
        if expected_cls is None:
            raise TrainingContractValidationError(
                "trace reference must name a transformation trace"
            )
        if type(self.trace) is not expected_cls:
            if isinstance(self.trace, Mapping):
                object.__setattr__(
                    self,
                    "trace",
                    expected_cls.from_dict(_mapping(self.trace, "trace")),
                )
            else:
                raise TrainingContractValidationError(
                    f"{self.kind.value} reference requires {expected_cls.__name__}"
                )
        object.__setattr__(
            self,
            "source_statement_id",
            _identifier(self.source_statement_id, "source_statement_id"),
        )
        object.__setattr__(
            self,
            "source_statement_digest",
            _digest(self.source_statement_digest, "source_statement_digest"),
        )
        object.__setattr__(
            self,
            "target_statement_id",
            _identifier(self.target_statement_id, "target_statement_id"),
        )
        object.__setattr__(
            self,
            "target_statement_digest",
            _digest(self.target_statement_digest, "target_statement_digest"),
        )
        object.__setattr__(self, "status", _enum(self.status, TraceStatus, "status"))
        object.__setattr__(self, "schema_version", _text(self.schema_version, "schema_version"))
        if self.schema_version != self.SCHEMA_VERSION:
            raise TrainingContractValidationError(
                f"unsupported trace reference schema: {self.schema_version!r}"
            )
        trace = self.trace
        if trace.target is None:
            raise TrainingContractValidationError("a round-trip trace reference must bind a target")
        asserted = (
            self.trace_id,
            self.trace_digest,
            self.lineage_digest,
            self.source_statement_id,
            self.source_statement_digest,
            self.target_statement_id,
            self.target_statement_digest,
            self.status,
        )
        actual = (
            trace.trace_id,
            trace.digest,
            trace.lineage.digest,
            trace.source.statement_id,
            trace.source.statement_digest,
            trace.target.statement_id,
            trace.target.statement_digest,
            trace.status,
        )
        if asserted != actual:
            raise TrainingContractValidationError(
                "trace reference fields do not match its embedded trace"
            )

    @classmethod
    def from_trace(cls, trace: TransformationTrace) -> TraceReference:
        if type(trace) not in {IRCompilerTrace, IRDecompilerTrace, IRTranslationTrace}:
            raise TrainingContractValidationError("trace must be a transformation trace")
        if trace.target is None:
            raise TrainingContractValidationError("a referenced transformation must bind a target")
        return cls(
            trace_id=trace.trace_id,
            trace_digest=trace.digest,
            lineage_digest=trace.lineage.digest,
            kind=trace.kind,
            source_statement_id=trace.source.statement_id,
            source_statement_digest=trace.source.statement_digest,
            target_statement_id=trace.target.statement_id,
            target_statement_digest=trace.target.statement_digest,
            status=trace.status,
            trace=trace,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "lineage_digest": self.lineage_digest,
            "schema_version": self.schema_version,
            "source_statement_digest": self.source_statement_digest,
            "source_statement_id": self.source_statement_id,
            "status": self.status.value,
            "target_statement_digest": self.target_statement_digest,
            "target_statement_id": self.target_statement_id,
            "trace": self.trace.to_dict(),
            "trace_digest": self.trace_digest,
            "trace_id": self.trace_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> TraceReference:
        value = _mapping(value, "trace reference")
        _reject_unknown(
            value,
            frozenset(
                {
                    "kind",
                    "lineage_digest",
                    "schema_version",
                    "source_statement_digest",
                    "source_statement_id",
                    "status",
                    "target_statement_digest",
                    "target_statement_id",
                    "trace",
                    "trace_digest",
                    "trace_id",
                }
            ),
            "trace reference",
        )
        return cls(
            trace_id=value.get("trace_id", ""),
            trace_digest=value.get("trace_digest", ""),
            lineage_digest=value.get("lineage_digest", ""),
            kind=value.get("kind", ""),
            source_statement_id=value.get("source_statement_id", ""),
            source_statement_digest=value.get("source_statement_digest", ""),
            target_statement_id=value.get("target_statement_id", ""),
            target_statement_digest=value.get("target_statement_digest", ""),
            status=value.get("status", TraceStatus.UNKNOWN.value),
            trace=_mapping(value.get("trace", {}), "trace"),
            schema_version=value.get("schema_version", TRACE_REFERENCE_SCHEMA_VERSION),
        )


@dataclass(frozen=True, slots=True)
class IRRoundTripTrace(_CanonicalRecord):
    """Ordered forward/reverse trace binding with explicit reconstruction class."""

    INTERFACE: ClassVar[str] = IR_ROUND_TRIP_TRACE_INTERFACE
    SCHEMA_VERSION: ClassVar[str] = IR_ROUND_TRIP_TRACE_SCHEMA_VERSION
    IDENTITY_SUFFIX: ClassVar[str] = "round-trip-trace"
    COLLECTION_SCHEMA: ClassVar[Mapping[str, str]] = {
        "/evidence": "set-like",
        "/unresolved_losses": "set-like",
        "/forward/trace/evidence": "set-like",
        "/forward/trace/unresolved_losses": "set-like",
        "/forward/trace/diagnostics": "set-like",
        "/reverse/trace/evidence": "set-like",
        "/reverse/trace/unresolved_losses": "set-like",
        "/reverse/trace/diagnostics": "set-like",
    }
    KIND: ClassVar[ExampleKind] = ExampleKind.ROUND_TRIP

    trace_id: str
    lineage: LineageBinding
    original: StatementBinding
    reconstructed: StatementBinding
    forward: TraceReference
    reverse: TraceReference
    relationship: SemanticRelationship
    preservation: PreservationClass
    evidence: tuple[LabelEvidence, ...] = ()
    unresolved_losses: tuple[str, ...] = ()
    schema_version: str = IR_ROUND_TRIP_TRACE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "trace_id", _identifier(self.trace_id, "trace_id"))
        if not isinstance(self.lineage, LineageBinding):
            object.__setattr__(
                self, "lineage", LineageBinding.from_dict(_mapping(self.lineage, "lineage"))
            )
        if not isinstance(self.original, StatementBinding):
            object.__setattr__(
                self,
                "original",
                StatementBinding.from_dict(_mapping(self.original, "original")),
            )
        if not isinstance(self.reconstructed, StatementBinding):
            object.__setattr__(
                self,
                "reconstructed",
                StatementBinding.from_dict(_mapping(self.reconstructed, "reconstructed")),
            )
        if not isinstance(self.forward, TraceReference):
            object.__setattr__(
                self, "forward", TraceReference.from_dict(_mapping(self.forward, "forward"))
            )
        if not isinstance(self.reverse, TraceReference):
            object.__setattr__(
                self, "reverse", TraceReference.from_dict(_mapping(self.reverse, "reverse"))
            )
        object.__setattr__(
            self,
            "relationship",
            _enum(self.relationship, SemanticRelationship, "relationship"),
        )
        object.__setattr__(
            self,
            "preservation",
            _enum(self.preservation, PreservationClass, "preservation"),
        )
        object.__setattr__(self, "evidence", _normalize_evidence(self.evidence))
        object.__setattr__(
            self,
            "unresolved_losses",
            _unique_texts(self.unresolved_losses, "unresolved_losses"),
        )
        object.__setattr__(self, "schema_version", _text(self.schema_version, "schema_version"))
        if self.schema_version != self.SCHEMA_VERSION:
            raise TrainingContractValidationError(
                f"unsupported round-trip trace schema: {self.schema_version!r}"
            )
        _bind_statement_to_lineage(self.original, self.lineage)
        _bind_statement_to_lineage(self.reconstructed, self.lineage)
        if (
            self.forward.lineage_digest != self.lineage.digest
            or self.reverse.lineage_digest != self.lineage.digest
        ):
            raise TrainingContractValidationError(
                "round-trip stages must bind the same lineage and split root"
            )
        if (
            self.forward.source_statement_id,
            self.forward.source_statement_digest,
        ) != (self.original.statement_id, self.original.statement_digest):
            raise TrainingContractValidationError(
                "forward trace does not begin at original statement"
            )
        if (
            self.forward.target_statement_id,
            self.forward.target_statement_digest,
        ) != (
            self.reverse.source_statement_id,
            self.reverse.source_statement_digest,
        ):
            raise TrainingContractValidationError("round-trip trace stages are not contiguous")
        if (
            self.reverse.target_statement_id,
            self.reverse.target_statement_digest,
        ) != (self.reconstructed.statement_id, self.reconstructed.statement_digest):
            raise TrainingContractValidationError(
                "reverse trace does not end at reconstructed statement"
            )
        _validate_evidence_subjects(
            self.evidence, (self.original, self.reconstructed), self.relationship
        )
        exact = {
            SemanticRelationship.EXACT,
            SemanticRelationship.ALPHA_EQUIVALENT,
            SemanticRelationship.CANONICAL_EQUIVALENT,
        }
        if self.relationship in exact and (
            self.unresolved_losses
            or self.preservation
            not in {
                PreservationClass.LOSSLESS,
                PreservationClass.SYNTACTIC,
                PreservationClass.STRUCTURAL,
                PreservationClass.SEMANTIC,
                PreservationClass.PROOF,
            }
            or self.forward.status is not TraceStatus.SUCCEEDED
            or self.reverse.status is not TraceStatus.SUCCEEDED
        ):
            raise TrainingContractValidationError(
                "exact round trip requires successful stages and resolved preservation"
            )
        if self.relationship in {
            SemanticRelationship.NON_EQUIVALENT,
            SemanticRelationship.CONTRADICTS,
            SemanticRelationship.NOT_ENTAILED,
        } and self.preservation in {
            PreservationClass.LOSSLESS,
            PreservationClass.SYNTACTIC,
            PreservationClass.STRUCTURAL,
            PreservationClass.SEMANTIC,
            PreservationClass.PROOF,
            PreservationClass.EQUISATISFIABLE,
        }:
            raise TrainingContractValidationError(
                "negative relationships cannot claim positive preservation"
            )
        if (
            self.preservation is PreservationClass.EQUISATISFIABLE
            and self.relationship is not SemanticRelationship.EQUISATISFIABLE
        ):
            raise TrainingContractValidationError(
                "equisatisfiable preservation requires an equisatisfiable relationship"
            )
        if self.preservation is PreservationClass.LOSSLESS and self.unresolved_losses:
            raise TrainingContractValidationError(
                "lossless round trip cannot carry unresolved losses"
            )

    @property
    def kind(self) -> ExampleKind:
        return self.KIND

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence": [item.to_dict() for item in self.evidence],
            "forward": self.forward.to_dict(),
            "lineage": self.lineage.to_dict(),
            "original": self.original.to_dict(),
            "preservation": self.preservation.value,
            "reconstructed": self.reconstructed.to_dict(),
            "relationship": self.relationship.value,
            "reverse": self.reverse.to_dict(),
            "schema_version": self.schema_version,
            "trace_id": self.trace_id,
            "unresolved_losses": list(self.unresolved_losses),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> IRRoundTripTrace:
        value = _mapping(value, "round-trip trace")
        _reject_unknown(
            value,
            frozenset(
                {
                    "evidence",
                    "forward",
                    "lineage",
                    "original",
                    "preservation",
                    "reconstructed",
                    "relationship",
                    "reverse",
                    "schema_version",
                    "trace_id",
                    "unresolved_losses",
                }
            ),
            "round-trip trace",
        )
        return cls(
            trace_id=value.get("trace_id", ""),
            lineage=LineageBinding.from_dict(_mapping(value.get("lineage", {}), "lineage")),
            original=StatementBinding.from_dict(_mapping(value.get("original", {}), "original")),
            reconstructed=StatementBinding.from_dict(
                _mapping(value.get("reconstructed", {}), "reconstructed")
            ),
            forward=TraceReference.from_dict(_mapping(value.get("forward", {}), "forward")),
            reverse=TraceReference.from_dict(_mapping(value.get("reverse", {}), "reverse")),
            relationship=value.get("relationship", SemanticRelationship.UNKNOWN.value),
            preservation=value.get("preservation", PreservationClass.UNKNOWN.value),
            evidence=tuple(_sequence(value.get("evidence", ()), "evidence")),
            unresolved_losses=tuple(
                _sequence(value.get("unresolved_losses", ()), "unresolved_losses")
            ),
            schema_version=value.get("schema_version", IR_ROUND_TRIP_TRACE_SCHEMA_VERSION),
        )


__all__ = [
    "IRCompilerTrace",
    "IRDecompilerTrace",
    "IRRoundTripTrace",
    "IRTranslationTrace",
    "TraceReference",
    "TransformationTrace",
]
