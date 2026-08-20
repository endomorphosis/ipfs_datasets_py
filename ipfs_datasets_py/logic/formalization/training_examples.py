"""Positive, hard-negative, and fail-closed training-example admission records."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, ClassVar, TypeAlias

from ipfs_datasets_py.logic.ir_core.claims import FrozenMap
from ipfs_datasets_py.logic.ir_core.source_lineage import RightsDisposition

from .training_proofs import (
    IRProofTrace,
    IRTacticTrace,
    _verified_proof_evidence,
)
from .training_shared import (
    _JSON_POINTER_RE,
    IR_HARD_NEGATIVE_INTERFACE,
    IR_HARD_NEGATIVE_SCHEMA_VERSION,
    IR_POSITIVE_PAIR_INTERFACE,
    IR_POSITIVE_PAIR_SCHEMA_VERSION,
    IR_TRAINING_EXAMPLE_INTERFACE,
    IR_TRAINING_EXAMPLE_SCHEMA_VERSION,
    EvidenceStatus,
    ExampleDisposition,
    ExampleKind,
    LabelAuthority,
    LabelEvidence,
    LineageBinding,
    LogicFamily,
    MutationClass,
    NegativeDisposition,
    PreservationClass,
    QuarantineReason,
    SemanticRelationship,
    StatementAuthority,
    StatementBinding,
    TacticOutcome,
    TraceStatus,
    TrainingContractValidationError,
    _bind_statement_to_lineage,
    _bool,
    _CanonicalRecord,
    _enum,
    _frozen_map,
    _has_verified_relationship_evidence,
    _identifier,
    _mapping,
    _normalize_evidence,
    _reject_unknown,
    _sequence,
    _text,
    _validate_evidence_subjects,
)
from .training_transforms import (
    IRCompilerTrace,
    IRDecompilerTrace,
    IRRoundTripTrace,
    IRTranslationTrace,
)

_POSITIVE_RELATIONSHIPS = frozenset(
    {
        SemanticRelationship.EXACT,
        SemanticRelationship.ALPHA_EQUIVALENT,
        SemanticRelationship.CANONICAL_EQUIVALENT,
        SemanticRelationship.LOGICALLY_EQUIVALENT,
        SemanticRelationship.EQUISATISFIABLE,
        SemanticRelationship.PROOF_EQUIVALENT,
        SemanticRelationship.TRANSLATION_EQUIVALENT,
        SemanticRelationship.PARAPHRASE,
        SemanticRelationship.UNKNOWN,
    }
)

_NEGATIVE_RELATIONSHIPS = frozenset(
    {
        SemanticRelationship.NON_EQUIVALENT,
        SemanticRelationship.CONTRADICTS,
        SemanticRelationship.NOT_ENTAILED,
        SemanticRelationship.UNKNOWN,
    }
)


@dataclass(frozen=True, slots=True)
class IRPositivePair(_CanonicalRecord):
    """Symmetric pair with a precise, non-collapsed equivalence class."""

    INTERFACE: ClassVar[str] = IR_POSITIVE_PAIR_INTERFACE
    SCHEMA_VERSION: ClassVar[str] = IR_POSITIVE_PAIR_SCHEMA_VERSION
    IDENTITY_SUFFIX: ClassVar[str] = "positive-pair"
    COLLECTION_SCHEMA: ClassVar[Mapping[str, str]] = {"/evidence": "set-like"}
    KIND: ClassVar[ExampleKind] = ExampleKind.POSITIVE_PAIR

    pair_id: str
    lineage: LineageBinding
    left: StatementBinding
    right: StatementBinding
    left_authority: StatementAuthority
    right_authority: StatementAuthority
    relationship: SemanticRelationship
    equivalence_class_id: str
    evidence: tuple[LabelEvidence, ...] = ()
    schema_version: str = IR_POSITIVE_PAIR_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "pair_id", _identifier(self.pair_id, "pair_id"))
        if not isinstance(self.lineage, LineageBinding):
            object.__setattr__(
                self, "lineage", LineageBinding.from_dict(_mapping(self.lineage, "lineage"))
            )
        if not isinstance(self.left, StatementBinding):
            object.__setattr__(
                self, "left", StatementBinding.from_dict(_mapping(self.left, "left"))
            )
        if not isinstance(self.right, StatementBinding):
            object.__setattr__(
                self, "right", StatementBinding.from_dict(_mapping(self.right, "right"))
            )
        object.__setattr__(
            self,
            "left_authority",
            _enum(self.left_authority, StatementAuthority, "left_authority"),
        )
        object.__setattr__(
            self,
            "right_authority",
            _enum(self.right_authority, StatementAuthority, "right_authority"),
        )
        object.__setattr__(
            self,
            "relationship",
            _enum(self.relationship, SemanticRelationship, "relationship"),
        )
        object.__setattr__(
            self,
            "equivalence_class_id",
            _identifier(self.equivalence_class_id, "equivalence_class_id"),
        )
        object.__setattr__(self, "evidence", _normalize_evidence(self.evidence))
        object.__setattr__(self, "schema_version", _text(self.schema_version, "schema_version"))
        if self.schema_version != self.SCHEMA_VERSION:
            raise TrainingContractValidationError(
                f"unsupported positive-pair schema: {self.schema_version!r}"
            )
        if self.relationship not in _POSITIVE_RELATIONSHIPS:
            raise TrainingContractValidationError(
                f"{self.relationship.value} is not a positive-pair relationship"
            )
        if (
            self.left.statement_id,
            self.left.statement_digest,
        ) == (
            self.right.statement_id,
            self.right.statement_digest,
        ):
            raise TrainingContractValidationError(
                "positive pair endpoints must be distinct records"
            )
        _bind_statement_to_lineage(self.left, self.lineage)
        _bind_statement_to_lineage(self.right, self.lineage)
        _validate_evidence_subjects(self.evidence, (self.left, self.right), self.relationship)
        # All admitted pair classes are symmetric.  Canonicalize endpoints and
        # their authorities together so caller ordering does not alter identity.
        if (self.right.statement_id, self.right.statement_digest) < (
            self.left.statement_id,
            self.left.statement_digest,
        ):
            left, right = self.right, self.left
            left_authority, right_authority = (
                self.right_authority,
                self.left_authority,
            )
            object.__setattr__(self, "left", left)
            object.__setattr__(self, "right", right)
            object.__setattr__(self, "left_authority", left_authority)
            object.__setattr__(self, "right_authority", right_authority)

    @property
    def kind(self) -> ExampleKind:
        return self.KIND

    def to_dict(self) -> dict[str, Any]:
        return {
            "equivalence_class_id": self.equivalence_class_id,
            "evidence": [item.to_dict() for item in self.evidence],
            "left": self.left.to_dict(),
            "left_authority": self.left_authority.value,
            "lineage": self.lineage.to_dict(),
            "pair_id": self.pair_id,
            "relationship": self.relationship.value,
            "right": self.right.to_dict(),
            "right_authority": self.right_authority.value,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> IRPositivePair:
        value = _mapping(value, "positive pair")
        _reject_unknown(
            value,
            frozenset(
                {
                    "equivalence_class_id",
                    "evidence",
                    "left",
                    "left_authority",
                    "lineage",
                    "pair_id",
                    "relationship",
                    "right",
                    "right_authority",
                    "schema_version",
                }
            ),
            "positive pair",
        )
        return cls(
            pair_id=value.get("pair_id", ""),
            lineage=LineageBinding.from_dict(_mapping(value.get("lineage", {}), "lineage")),
            left=StatementBinding.from_dict(_mapping(value.get("left", {}), "left")),
            right=StatementBinding.from_dict(_mapping(value.get("right", {}), "right")),
            left_authority=value.get("left_authority", ""),
            right_authority=value.get("right_authority", ""),
            relationship=value.get("relationship", SemanticRelationship.UNKNOWN.value),
            equivalence_class_id=value.get("equivalence_class_id", ""),
            evidence=tuple(_sequence(value.get("evidence", ()), "evidence")),
            schema_version=value.get("schema_version", IR_POSITIVE_PAIR_SCHEMA_VERSION),
        )


def _normalize_paths(value: Any) -> tuple[str, ...]:
    paths = tuple(_text(item, "mutated_paths") for item in _sequence(value, "mutated_paths"))
    if not paths:
        raise TrainingContractValidationError("hard negative requires mutated_paths")
    if len(paths) != len(set(paths)):
        raise TrainingContractValidationError("mutated_paths values must be unique")
    for path in paths:
        if not _JSON_POINTER_RE.fullmatch(path):
            raise TrainingContractValidationError(
                "mutated_paths values must be non-root JSON pointers"
            )
    return tuple(sorted(paths))


def _checked_negative_evidence(
    evidence: Sequence[LabelEvidence],
    original: StatementBinding,
    mutant: StatementBinding,
    relationship: SemanticRelationship,
) -> bool:
    allowed = {
        LabelAuthority.INDEPENDENT_COUNTEREXAMPLE_CHECKER,
        LabelAuthority.INDEPENDENT_SEMANTIC_CHECKER,
        LabelAuthority.INDEPENDENT_PROOF_CHECKER,
    }
    subjects = frozenset(
        {
            (original.statement_id, original.statement_digest),
            (mutant.statement_id, mutant.statement_digest),
        }
    )
    return any(
        item.status is EvidenceStatus.VERIFIED
        and item.independent
        and item.authority in allowed
        and item.relationship is relationship
        and frozenset(zip(item.subject_statement_ids, item.subject_statement_digests, strict=True))
        == subjects
        for item in evidence
    )


@dataclass(frozen=True, slots=True)
class IRHardNegative(_CanonicalRecord):
    """Directional minimal mutation with confirmed-negative or unknown status."""

    INTERFACE: ClassVar[str] = IR_HARD_NEGATIVE_INTERFACE
    SCHEMA_VERSION: ClassVar[str] = IR_HARD_NEGATIVE_SCHEMA_VERSION
    IDENTITY_SUFFIX: ClassVar[str] = "hard-negative"
    COLLECTION_SCHEMA: ClassVar[Mapping[str, str]] = {
        "/evidence": "set-like",
        "/mutated_paths": "set-like",
    }
    KIND: ClassVar[ExampleKind] = ExampleKind.HARD_NEGATIVE

    negative_id: str
    lineage: LineageBinding
    original: StatementBinding
    mutant: StatementBinding
    relationship: SemanticRelationship
    mutation_class: MutationClass
    mutated_paths: tuple[str, ...]
    minimality_checked: bool
    disposition: NegativeDisposition
    evidence: tuple[LabelEvidence, ...] = ()
    schema_version: str = IR_HARD_NEGATIVE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "negative_id", _identifier(self.negative_id, "negative_id"))
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
        if not isinstance(self.mutant, StatementBinding):
            object.__setattr__(
                self, "mutant", StatementBinding.from_dict(_mapping(self.mutant, "mutant"))
            )
        object.__setattr__(
            self,
            "relationship",
            _enum(self.relationship, SemanticRelationship, "relationship"),
        )
        object.__setattr__(
            self,
            "mutation_class",
            _enum(self.mutation_class, MutationClass, "mutation_class"),
        )
        object.__setattr__(self, "mutated_paths", _normalize_paths(self.mutated_paths))
        object.__setattr__(
            self,
            "minimality_checked",
            _bool(self.minimality_checked, "minimality_checked"),
        )
        object.__setattr__(
            self,
            "disposition",
            _enum(self.disposition, NegativeDisposition, "disposition"),
        )
        object.__setattr__(self, "evidence", _normalize_evidence(self.evidence))
        object.__setattr__(self, "schema_version", _text(self.schema_version, "schema_version"))
        if self.schema_version != self.SCHEMA_VERSION:
            raise TrainingContractValidationError(
                f"unsupported hard-negative schema: {self.schema_version!r}"
            )
        if self.relationship not in _NEGATIVE_RELATIONSHIPS:
            raise TrainingContractValidationError(
                f"{self.relationship.value} is not a hard-negative relationship"
            )
        if (
            self.original.statement_id,
            self.original.statement_digest,
        ) == (
            self.mutant.statement_id,
            self.mutant.statement_digest,
        ):
            raise TrainingContractValidationError("hard-negative original and mutant must differ")
        _bind_statement_to_lineage(self.original, self.lineage)
        _bind_statement_to_lineage(self.mutant, self.lineage)
        _validate_evidence_subjects(self.evidence, (self.original, self.mutant), self.relationship)
        if self.disposition is NegativeDisposition.CONFIRMED_NEGATIVE:
            if self.relationship is SemanticRelationship.UNKNOWN:
                raise TrainingContractValidationError(
                    "confirmed negative cannot have unknown relationship"
                )
            if not self.minimality_checked:
                raise TrainingContractValidationError(
                    "confirmed negative requires a minimality check"
                )
            if not _checked_negative_evidence(
                self.evidence, self.original, self.mutant, self.relationship
            ):
                raise TrainingContractValidationError(
                    "confirmed negative requires independently checked evidence"
                )
        elif self.disposition is NegativeDisposition.UNKNOWN:
            if self.relationship is not SemanticRelationship.UNKNOWN:
                raise TrainingContractValidationError(
                    "unknown negative disposition must retain unknown relationship"
                )

    @property
    def kind(self) -> ExampleKind:
        return self.KIND

    def to_dict(self) -> dict[str, Any]:
        return {
            "disposition": self.disposition.value,
            "evidence": [item.to_dict() for item in self.evidence],
            "lineage": self.lineage.to_dict(),
            "minimality_checked": self.minimality_checked,
            "mutant": self.mutant.to_dict(),
            "mutated_paths": list(self.mutated_paths),
            "mutation_class": self.mutation_class.value,
            "negative_id": self.negative_id,
            "original": self.original.to_dict(),
            "relationship": self.relationship.value,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> IRHardNegative:
        value = _mapping(value, "hard negative")
        _reject_unknown(
            value,
            frozenset(
                {
                    "disposition",
                    "evidence",
                    "lineage",
                    "minimality_checked",
                    "mutant",
                    "mutated_paths",
                    "mutation_class",
                    "negative_id",
                    "original",
                    "relationship",
                    "schema_version",
                }
            ),
            "hard negative",
        )
        return cls(
            negative_id=value.get("negative_id", ""),
            lineage=LineageBinding.from_dict(_mapping(value.get("lineage", {}), "lineage")),
            original=StatementBinding.from_dict(_mapping(value.get("original", {}), "original")),
            mutant=StatementBinding.from_dict(_mapping(value.get("mutant", {}), "mutant")),
            relationship=value.get("relationship", SemanticRelationship.UNKNOWN.value),
            mutation_class=value.get("mutation_class", ""),
            mutated_paths=tuple(_sequence(value.get("mutated_paths", ()), "mutated_paths")),
            minimality_checked=value.get("minimality_checked", False),
            disposition=value.get("disposition", NegativeDisposition.UNKNOWN.value),
            evidence=tuple(_sequence(value.get("evidence", ()), "evidence")),
            schema_version=value.get("schema_version", IR_HARD_NEGATIVE_SCHEMA_VERSION),
        )


TrainingRecord: TypeAlias = (
    IRCompilerTrace
    | IRDecompilerTrace
    | IRTranslationTrace
    | IRRoundTripTrace
    | IRProofTrace
    | IRTacticTrace
    | IRPositivePair
    | IRHardNegative
)

_RECORD_CLASSES: dict[ExampleKind, type[TrainingRecord]] = {
    ExampleKind.COMPILER: IRCompilerTrace,
    ExampleKind.DECOMPILER: IRDecompilerTrace,
    ExampleKind.TRANSLATION: IRTranslationTrace,
    ExampleKind.ROUND_TRIP: IRRoundTripTrace,
    ExampleKind.PROOF: IRProofTrace,
    ExampleKind.TACTIC: IRTacticTrace,
    ExampleKind.POSITIVE_PAIR: IRPositivePair,
    ExampleKind.HARD_NEGATIVE: IRHardNegative,
}


def _record_statements(record: TrainingRecord) -> tuple[StatementBinding, ...]:
    if isinstance(record, (IRCompilerTrace, IRDecompilerTrace, IRTranslationTrace)):
        return (record.source,) + ((record.target,) if record.target is not None else ())
    if isinstance(record, IRRoundTripTrace):
        return (record.original, record.reconstructed)
    if isinstance(record, (IRProofTrace, IRTacticTrace)):
        return (record.statement,)
    if isinstance(record, IRPositivePair):
        return (record.left, record.right)
    return (record.original, record.mutant)


def _selected_evidence(record: TrainingRecord, selected_evidence_id: str) -> LabelEvidence | None:
    if not selected_evidence_id:
        return None
    for item in record.evidence:
        if item.evidence_id == selected_evidence_id:
            return item
    raise TrainingContractValidationError(
        f"selected evidence {selected_evidence_id!r} is not embedded in the record"
    )


def _admissibility_reasons(
    record: TrainingRecord, selected_evidence_id: str
) -> tuple[QuarantineReason, ...]:
    reasons: set[QuarantineReason] = set()
    if record.lineage.rights_disposition is not RightsDisposition.ADMITTED:
        reasons.add(QuarantineReason.RIGHTS_NOT_ADMITTED)
    if record.lineage.split_name != "train":
        reasons.add(QuarantineReason.NON_TRAINING_SPLIT)
    if any(item.logic_family is LogicFamily.UNSPECIFIED for item in _record_statements(record)):
        reasons.add(QuarantineReason.UNKNOWN_LOGIC_FAMILY)

    selected = _selected_evidence(record, selected_evidence_id)
    if selected is None or selected.status is not EvidenceStatus.VERIFIED:
        reasons.add(QuarantineReason.UNVERIFIED_EVIDENCE)
    if selected is not None and selected.authority in {
        LabelAuthority.MODEL_OUTPUT,
        LabelAuthority.TOOL_CANDIDATE,
        LabelAuthority.UNKNOWN,
    }:
        reasons.add(QuarantineReason.MODEL_ONLY_EVIDENCE)

    if isinstance(record, (IRCompilerTrace, IRDecompilerTrace, IRTranslationTrace)):
        if record.target_authority in {
            StatementAuthority.UNKNOWN,
            StatementAuthority.MODEL_CANDIDATE,
        }:
            reasons.add(QuarantineReason.CANDIDATE_STATEMENT_AUTHORITY)
        if record.status is not TraceStatus.SUCCEEDED or record.target is None:
            reasons.add(QuarantineReason.TRACE_NOT_SUCCEEDED)
        if record.relationship is SemanticRelationship.UNKNOWN:
            reasons.add(QuarantineReason.UNKNOWN_RELATIONSHIP)
        if record.preservation is PreservationClass.UNKNOWN:
            reasons.add(QuarantineReason.UNKNOWN_PRESERVATION)
        if record.preservation in {
            PreservationClass.HEURISTIC,
            PreservationClass.UNSUPPORTED,
        }:
            reasons.add(QuarantineReason.UNSUPPORTED_OR_HEURISTIC)
        if record.unresolved_losses:
            reasons.add(QuarantineReason.UNRESOLVED_LOSS)
        if (
            record.target is None
            or selected is None
            or not _has_verified_relationship_evidence(
                (selected,), (record.source, record.target), record.relationship
            )
        ):
            reasons.add(QuarantineReason.UNVERIFIED_EVIDENCE)
    elif isinstance(record, IRRoundTripTrace):
        if (
            record.forward.status is not TraceStatus.SUCCEEDED
            or record.reverse.status is not TraceStatus.SUCCEEDED
        ):
            reasons.add(QuarantineReason.TRACE_NOT_SUCCEEDED)
        if record.relationship is SemanticRelationship.UNKNOWN:
            reasons.add(QuarantineReason.UNKNOWN_RELATIONSHIP)
        if record.preservation is PreservationClass.UNKNOWN:
            reasons.add(QuarantineReason.UNKNOWN_PRESERVATION)
        if record.preservation in {
            PreservationClass.HEURISTIC,
            PreservationClass.UNSUPPORTED,
        }:
            reasons.add(QuarantineReason.UNSUPPORTED_OR_HEURISTIC)
        if record.unresolved_losses:
            reasons.add(QuarantineReason.UNRESOLVED_LOSS)
        if selected is None or not _has_verified_relationship_evidence(
            (selected,), (record.original, record.reconstructed), record.relationship
        ):
            reasons.add(QuarantineReason.UNVERIFIED_EVIDENCE)
    elif isinstance(record, IRProofTrace):
        if (
            record.outcome.value != "proved"
            or selected is None
            or not _verified_proof_evidence(
                (selected,),
                record.statement,
                record.checker,
                record.proof_receipt_digest,
            )
        ):
            reasons.add(QuarantineReason.UNVERIFIED_PROOF)
    elif isinstance(record, IRTacticTrace):
        if (
            record.outcome is not TacticOutcome.VERIFIED_SUCCESS
            or selected is None
            or not _verified_proof_evidence(
                (selected,),
                record.statement,
                record.checker,
                record.proof_trace_digest,
            )
        ):
            reasons.add(QuarantineReason.UNVERIFIED_TACTIC)
    elif isinstance(record, IRPositivePair):
        if record.left_authority in {
            StatementAuthority.UNKNOWN,
            StatementAuthority.MODEL_CANDIDATE,
        } or record.right_authority in {
            StatementAuthority.UNKNOWN,
            StatementAuthority.MODEL_CANDIDATE,
        }:
            reasons.add(QuarantineReason.CANDIDATE_STATEMENT_AUTHORITY)
        if record.relationship is SemanticRelationship.UNKNOWN:
            reasons.add(QuarantineReason.UNKNOWN_RELATIONSHIP)
        if selected is None or not _has_verified_relationship_evidence(
            (selected,), (record.left, record.right), record.relationship
        ):
            reasons.add(QuarantineReason.UNVERIFIED_EVIDENCE)
    else:
        if record.disposition is not NegativeDisposition.CONFIRMED_NEGATIVE:
            reasons.add(QuarantineReason.UNKNOWN_NEGATIVE)
        if not record.minimality_checked:
            reasons.add(QuarantineReason.MINIMALITY_UNCHECKED)
        if (
            selected is None
            or record.relationship is SemanticRelationship.UNKNOWN
            or not _checked_negative_evidence(
                (selected,), record.original, record.mutant, record.relationship
            )
        ):
            reasons.add(QuarantineReason.UNVERIFIED_EVIDENCE)
    return tuple(sorted(reasons, key=lambda item: item.value))


@dataclass(frozen=True, slots=True)
class IRTrainingExample(_CanonicalRecord):
    """Closed wrapper that separates valid decoding from training admission."""

    INTERFACE: ClassVar[str] = IR_TRAINING_EXAMPLE_INTERFACE
    SCHEMA_VERSION: ClassVar[str] = IR_TRAINING_EXAMPLE_SCHEMA_VERSION
    IDENTITY_SUFFIX: ClassVar[str] = "training-example"
    COLLECTION_SCHEMA: ClassVar[Mapping[str, str]] = {
        "/quarantine_reasons": "set-like",
        "/record/evidence": "set-like",
        "/record/diagnostics": "set-like",
        "/record/unresolved_losses": "set-like",
        "/record/mutated_paths": "set-like",
        "/record/steps": "ordered",
    }

    example_id: str
    kind: ExampleKind
    record: TrainingRecord
    selected_evidence_id: str
    disposition: ExampleDisposition
    quarantine_reasons: tuple[QuarantineReason, ...] = ()
    metadata: FrozenMap = field(default_factory=FrozenMap)
    schema_version: str = IR_TRAINING_EXAMPLE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "example_id", _identifier(self.example_id, "example_id"))
        object.__setattr__(self, "kind", _enum(self.kind, ExampleKind, "kind"))
        expected = _RECORD_CLASSES[self.kind]
        if type(self.record) is not expected:
            raise TrainingContractValidationError(
                f"{self.kind.value} example requires {expected.__name__}, "
                f"not {type(self.record).__name__}"
            )
        object.__setattr__(
            self,
            "selected_evidence_id",
            _identifier(
                self.selected_evidence_id,
                "selected_evidence_id",
                allow_empty=True,
            ),
        )
        object.__setattr__(
            self,
            "disposition",
            _enum(self.disposition, ExampleDisposition, "disposition"),
        )
        reasons = tuple(
            _enum(item, QuarantineReason, "quarantine_reason")
            for item in _sequence(self.quarantine_reasons, "quarantine_reasons")
        )
        if len(reasons) != len(set(reasons)):
            raise TrainingContractValidationError("quarantine reasons must be unique")
        object.__setattr__(
            self, "quarantine_reasons", tuple(sorted(reasons, key=lambda item: item.value))
        )
        object.__setattr__(self, "metadata", _frozen_map(self.metadata, "metadata"))
        object.__setattr__(self, "schema_version", _text(self.schema_version, "schema_version"))
        if self.schema_version != self.SCHEMA_VERSION:
            raise TrainingContractValidationError(
                f"unsupported training-example schema: {self.schema_version!r}"
            )
        required = set(_admissibility_reasons(self.record, self.selected_evidence_id))
        declared = set(self.quarantine_reasons)
        if self.disposition is ExampleDisposition.ADMITTED:
            if required or declared:
                names = ", ".join(
                    item.value for item in sorted(required | declared, key=lambda item: item.value)
                )
                raise TrainingContractValidationError(
                    f"inadmissible training example cannot be admitted: {names}"
                )
            if not self.selected_evidence_id:
                raise TrainingContractValidationError(
                    "admitted training example must select exact label evidence"
                )
        else:
            if not declared:
                raise TrainingContractValidationError(
                    "quarantined/rejected example requires a reason"
                )
            missing = required - declared
            if missing:
                raise TrainingContractValidationError(
                    "quarantine reasons omit required failure class(es): "
                    + ", ".join(sorted(item.value for item in missing))
                )
            unexpected = declared - required - {QuarantineReason.POLICY}
            if unexpected:
                raise TrainingContractValidationError(
                    "quarantine reasons contain inapplicable failure class(es): "
                    + ", ".join(sorted(item.value for item in unexpected))
                )

    @property
    def training_eligible(self) -> bool:
        return self.disposition is ExampleDisposition.ADMITTED

    @classmethod
    def classify(
        cls,
        *,
        example_id: str,
        record: TrainingRecord,
        selected_evidence_id: str = "",
        reject: bool = False,
        metadata: Mapping[str, Any] | FrozenMap | None = None,
    ) -> IRTrainingExample:
        reasons = _admissibility_reasons(record, selected_evidence_id)
        disposition = (
            ExampleDisposition.REJECTED
            if reasons and reject
            else ExampleDisposition.QUARANTINED
            if reasons
            else ExampleDisposition.ADMITTED
        )
        return cls(
            example_id=example_id,
            kind=record.kind,
            record=record,
            selected_evidence_id=selected_evidence_id,
            disposition=disposition,
            quarantine_reasons=reasons,
            metadata={} if metadata is None else metadata,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "disposition": self.disposition.value,
            "example_id": self.example_id,
            "kind": self.kind.value,
            "metadata": self.metadata.to_dict(),
            "quarantine_reasons": [item.value for item in self.quarantine_reasons],
            "record": self.record.to_dict(),
            "schema_version": self.schema_version,
            "selected_evidence_id": self.selected_evidence_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> IRTrainingExample:
        value = _mapping(value, "training example")
        _reject_unknown(
            value,
            frozenset(
                {
                    "disposition",
                    "example_id",
                    "kind",
                    "metadata",
                    "quarantine_reasons",
                    "record",
                    "schema_version",
                    "selected_evidence_id",
                }
            ),
            "training example",
        )
        kind = _enum(value.get("kind", ""), ExampleKind, "kind")
        record_cls = _RECORD_CLASSES[kind]
        return cls(
            example_id=value.get("example_id", ""),
            kind=kind,
            record=record_cls.from_dict(_mapping(value.get("record", {}), "record")),
            selected_evidence_id=value.get("selected_evidence_id", ""),
            disposition=value.get("disposition", ""),
            quarantine_reasons=tuple(
                _sequence(value.get("quarantine_reasons", ()), "quarantine_reasons")
            ),
            metadata=_frozen_map(value.get("metadata", {}), "metadata"),
            schema_version=value.get("schema_version", IR_TRAINING_EXAMPLE_SCHEMA_VERSION),
        )


def validate_training_example(
    value: IRTrainingExample | Mapping[str, Any],
) -> IRTrainingExample:
    """Reconstruct and validate one untrusted example payload."""

    if isinstance(value, IRTrainingExample):
        return IRTrainingExample.from_dict(value.to_dict())
    return IRTrainingExample.from_dict(value)


# Readable compatibility spellings; the IR-prefixed names remain canonical.
TrainingExample = IRTrainingExample
PositivePair = IRPositivePair
HardNegative = IRHardNegative


__all__ = [
    "HardNegative",
    "IRHardNegative",
    "IRPositivePair",
    "IRTrainingExample",
    "PositivePair",
    "TrainingExample",
    "TrainingRecord",
    "validate_training_example",
]
