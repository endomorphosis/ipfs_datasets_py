"""Stage-addressed translation-validation receipts for formalization compilation.

``StageTranslationReceipt@1`` records one source-to-backend compilation edge.
Every receipt binds the twelve required dimensions named by LGCVF-070 /
LGCVF-G080:

* input and output artifact identities
* pinned compiler
* source maps
* supported subset
* losses
* assumptions
* obligations
* validation
* replay
* bounds
* evidence class

Receipts are descriptive, content-addressed evidence.  They do not prove the
translated property.  Unsupported, omitted, or rejected losses cap this
stage's authority and every downstream stage's authority; ordinary generation
cannot be treated as proof-producing.

The module extends existing formalization, translation, and receipt
primitives.  It does not introduce a second proof cache, compiler, or
authority lattice.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum, StrEnum
from typing import Any, ClassVar, Final

from ipfs_datasets_py.logic.families.models import EvidenceAuthority
from ipfs_datasets_py.logic.formalization.samples import FormalizationValidationError
from ipfs_datasets_py.logic.ir_core.canonical import canonical_json_bytes
from ipfs_datasets_py.logic.ir_core.claims import Assumption, FrozenMap, ProofObligation
from ipfs_datasets_py.logic.ir_core.identity import CanonicalIdentity, canonical_identity
from ipfs_datasets_py.logic.software_verification.translations import (
    CompilerBinding,
    PreservationClaim,
    PreservationKind,
    SemanticMutation,
    TranslationBound,
    UnsupportedConstruct,
    UnsupportedHandling,
    authority_at_most,
    maximum_authority_for,
)


STAGE_TRANSLATION_RECEIPT_INTERFACE: Final = "StageTranslationReceipt@1"
STAGE_TRANSLATION_RECEIPT_SCHEMA_VERSION: Final = "formalization-stage-translation-receipt/v1"
STAGE_TRANSLATION_RECEIPT_IDENTITY_DOMAIN: Final = "formalization.stage.translation.receipt"

PIPELINE_RECEIPT_INTERFACE: Final = "CompilationPipelineReceipt@1"
COMPILATION_PIPELINE_RECEIPT_INTERFACE: Final = PIPELINE_RECEIPT_INTERFACE
PIPELINE_RECEIPT_SCHEMA_VERSION: Final = "formalization-compilation-pipeline-receipt/v1"
PIPELINE_RECEIPT_IDENTITY_DOMAIN: Final = "formalization.compilation.pipeline.receipt"

STAGE_ARTIFACT_SCHEMA_VERSION: Final = "formalization-stage-artifact/v1"
SUPPORTED_SUBSET_SCHEMA_VERSION: Final = "formalization-supported-subset/v1"
STAGE_SOURCE_MAP_SCHEMA_VERSION: Final = "formalization-stage-source-map/v1"
STAGE_SOURCE_MAP_ENTRY_SCHEMA_VERSION: Final = "formalization-stage-source-map-entry/v1"
STAGE_REPLAY_SCHEMA_VERSION: Final = "formalization-stage-replay/v1"
STAGE_VALIDATION_SCHEMA_VERSION: Final = "formalization-stage-validation/v1"
STAGE_RECEIPT_VALIDATION_SCHEMA_VERSION: Final = "formalization-stage-receipt-validation/v1"
STAGE_COUNTEREXAMPLE_SCHEMA_VERSION: Final = "formalization-stage-counterexample/v1"

REQUIRED_STAGE_BINDINGS: Final[tuple[str, ...]] = (
    "input",
    "output",
    "compiler",
    "source_map",
    "supported_subset",
    "losses",
    "assumptions",
    "obligations",
    "validation",
    "replay",
    "bounds",
    "evidence_class",
)


class StageReceiptError(FormalizationValidationError):
    """Raised when a stage receipt, pipeline, or expectation is malformed."""


class MissingStageReceiptError(StageReceiptError):
    """Raised when an authority-bearing path has no stage receipt."""


class StaleStageReceiptError(StageReceiptError):
    """Raised when a receipt does not match the current compilation inputs."""


class StaleProofError(StaleStageReceiptError):
    """Raised when a previously emitted receipt is offered as current proof."""


class StageReplayError(StageReceiptError):
    """Raised when a replay manifest cannot be reproduced."""


class CompilationStage(StrEnum):
    """Ordered source-to-backend compilation stages (LGCVF P7)."""

    SOURCE = "source"
    AST = "ast"
    NORMALIZED_AST = "normalized_ast"
    CFG = "cfg"
    SSA_DATA_FLOW = "ssa_data_flow"
    CONTRACT_EFFECT_IR = "contract_effect_ir"
    VC = "vc"
    FAMILY_IR = "family_ir"
    BACKEND = "backend"


STAGE_ORDER: Final[tuple[CompilationStage, ...]] = (
    CompilationStage.SOURCE,
    CompilationStage.AST,
    CompilationStage.NORMALIZED_AST,
    CompilationStage.CFG,
    CompilationStage.SSA_DATA_FLOW,
    CompilationStage.CONTRACT_EFFECT_IR,
    CompilationStage.VC,
    CompilationStage.FAMILY_IR,
    CompilationStage.BACKEND,
)

_STAGE_INDEX: Final[dict[CompilationStage, int]] = {
    stage: index for index, stage in enumerate(STAGE_ORDER)
}


class EvidenceClass(StrEnum):
    """Distinct evidence kinds; none of these is an authority waiver."""

    NONE = "none"
    CANDIDATE = "candidate"
    SYNTAX_CHECKED = "syntax_checked"
    TRANSLATION_VALIDATED = "translation_validated"
    BOUNDED_MODEL_CHECKED = "bounded_model_checked"
    SOLVER_CHECKED = "solver_checked"
    RUNTIME_OBSERVED = "runtime_observed"
    CRYPTOGRAPHICALLY_ATTESTED = "cryptographically_attested"
    KERNEL_VERIFIED = "kernel_verified"


class StageValidationStatus(StrEnum):
    """Outcome of the translation-validation check bound into a receipt."""

    VALID = "valid"
    INVALID = "invalid"
    STALE = "stale"
    UNSUPPORTED = "unsupported"
    REPLAY_FAILED = "replay_failed"


class StageMapDisposition(StrEnum):
    """How one input node is accounted for in a stage source map."""

    PRESERVED = "preserved"
    MAPPED = "mapped"
    APPROXIMATED = "approximated"
    SYNTHESIZED = "synthesized"
    UNSUPPORTED = "unsupported"
    DROPPED = "dropped"


class StageReceiptIssueCode(StrEnum):
    """Stable reasons a stage receipt cannot carry authority."""

    MISSING_RECEIPT = "missing_receipt"
    INPUT_IDENTITY_MISMATCH = "input_identity_mismatch"
    OUTPUT_IDENTITY_MISMATCH = "output_identity_mismatch"
    INPUT_STAGE_MISMATCH = "input_stage_mismatch"
    OUTPUT_STAGE_MISMATCH = "output_stage_mismatch"
    COMPILER_MISMATCH = "compiler_mismatch"
    SOURCE_MAP_MISMATCH = "source_map_mismatch"
    SUBSET_MISMATCH = "subset_mismatch"
    LOSS_MISMATCH = "loss_mismatch"
    ASSUMPTION_MISMATCH = "assumption_mismatch"
    OBLIGATION_MISMATCH = "obligation_mismatch"
    VALIDATION_MISMATCH = "validation_mismatch"
    REPLAY_MISMATCH = "replay_mismatch"
    BOUND_MISMATCH = "bound_mismatch"
    EVIDENCE_CLASS_MISMATCH = "evidence_class_mismatch"
    PRESERVATION_MISMATCH = "preservation_mismatch"
    STALE_PROOF = "stale_proof"


_AUTHORITY_RANK: Final[dict[EvidenceAuthority, int]] = {
    EvidenceAuthority.NONE: 0,
    EvidenceAuthority.ADVISORY: 1,
    EvidenceAuthority.BOUNDED: 2,
    EvidenceAuthority.INDEPENDENTLY_CHECKABLE: 3,
    EvidenceAuthority.AUTHORITATIVE: 4,
}

_EVIDENCE_CLASS_RANK: Final[dict[EvidenceClass, int]] = {
    EvidenceClass.NONE: 0,
    EvidenceClass.CANDIDATE: 1,
    EvidenceClass.SYNTAX_CHECKED: 2,
    EvidenceClass.TRANSLATION_VALIDATED: 3,
    EvidenceClass.BOUNDED_MODEL_CHECKED: 4,
    EvidenceClass.SOLVER_CHECKED: 5,
    EvidenceClass.RUNTIME_OBSERVED: 6,
    EvidenceClass.CRYPTOGRAPHICALLY_ATTESTED: 7,
    EvidenceClass.KERNEL_VERIFIED: 8,
}

_MAXIMUM_AUTHORITY_FOR_EVIDENCE_CLASS: Final[dict[EvidenceClass, EvidenceAuthority]] = {
    EvidenceClass.NONE: EvidenceAuthority.NONE,
    EvidenceClass.CANDIDATE: EvidenceAuthority.ADVISORY,
    EvidenceClass.SYNTAX_CHECKED: EvidenceAuthority.ADVISORY,
    EvidenceClass.TRANSLATION_VALIDATED: EvidenceAuthority.INDEPENDENTLY_CHECKABLE,
    EvidenceClass.BOUNDED_MODEL_CHECKED: EvidenceAuthority.BOUNDED,
    EvidenceClass.SOLVER_CHECKED: EvidenceAuthority.INDEPENDENTLY_CHECKABLE,
    EvidenceClass.RUNTIME_OBSERVED: EvidenceAuthority.BOUNDED,
    EvidenceClass.CRYPTOGRAPHICALLY_ATTESTED: EvidenceAuthority.AUTHORITATIVE,
    EvidenceClass.KERNEL_VERIFIED: EvidenceAuthority.AUTHORITATIVE,
}

_INCOMPLETE_HANDLING: Final[frozenset[UnsupportedHandling]] = frozenset(
    {UnsupportedHandling.REJECTED, UnsupportedHandling.OMITTED}
)


def _text(value: object, label: str, *, optional: bool = False) -> str:
    if optional and value == "":
        return ""
    if not isinstance(value, str) or not value or value.strip() != value or "\x00" in value:
        qualifier = "an empty or " if optional else "a "
        raise StageReceiptError(
            f"{label} must be {qualifier}non-empty trimmed string without NUL bytes"
        )
    return value


def _enum(value: object, enum_type: type[Enum], label: str) -> Any:
    try:
        return value if isinstance(value, enum_type) else enum_type(value)
    except (TypeError, ValueError) as error:
        choices = ", ".join(repr(member.value) for member in enum_type)
        raise StageReceiptError(f"{label} must be one of {choices}") from error


def _bool(value: object, label: str) -> bool:
    if not isinstance(value, bool):
        raise StageReceiptError(f"{label} must be a bool")
    return value


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise StageReceiptError(f"{label} must be a mapping")
    return value


def _frozen(value: Mapping[str, Any] | FrozenMap, label: str) -> FrozenMap:
    try:
        return value if isinstance(value, FrozenMap) else FrozenMap(value)
    except (TypeError, ValueError) as error:
        raise StageReceiptError(f"{label} must contain immutable JSON-compatible data") from error


def _reject_unknown(value: Mapping[str, Any], allowed: frozenset[str], label: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise StageReceiptError(f"unknown {label} field(s): {', '.join(unknown)}")


def _strings(values: Sequence[str] | object, label: str) -> tuple[str, ...]:
    if isinstance(values, (str, bytes, bytearray)) or not isinstance(values, Sequence):
        raise StageReceiptError(f"{label} must be a sequence of strings")
    result = tuple(_text(item, f"{label} item") for item in values)
    if len(result) != len(set(result)):
        raise StageReceiptError(f"{label} must not contain duplicates")
    return result


def _sorted_unique(values: Sequence[str] | object, label: str) -> tuple[str, ...]:
    return tuple(sorted(_strings(values, label)))


def _records(
    values: Sequence[Any] | object,
    record_type: type[Any],
    label: str,
) -> tuple[Any, ...]:
    if isinstance(values, (str, bytes, bytearray)) or not isinstance(values, Sequence):
        raise StageReceiptError(f"{label} must be a sequence")
    result: list[Any] = []
    for item in values:
        if isinstance(item, record_type):
            result.append(item)
        elif isinstance(item, Mapping):
            result.append(record_type.from_dict(item))
        else:
            raise StageReceiptError(f"{label} items must be {record_type.__name__} values")
    return tuple(result)


def _unique_by(values: Sequence[Any], attribute: str, label: str) -> tuple[Any, ...]:
    identities = [getattr(item, attribute) for item in values]
    if len(identities) != len(set(identities)):
        raise StageReceiptError(f"{label} must not contain duplicates")
    return tuple(sorted(values, key=lambda item: getattr(item, attribute)))


def _record(value: object, record_type: type[Any], label: str) -> Any:
    if isinstance(value, record_type):
        return value
    if isinstance(value, Mapping):
        return record_type.from_dict(value)
    raise StageReceiptError(f"{label} must be a {record_type.__name__}")


def _weaker_authority(
    left: EvidenceAuthority,
    right: EvidenceAuthority,
) -> EvidenceAuthority:
    return left if _AUTHORITY_RANK[left] <= _AUTHORITY_RANK[right] else right


def _weaker_evidence_class(left: EvidenceClass, right: EvidenceClass) -> EvidenceClass:
    return left if _EVIDENCE_CLASS_RANK[left] <= _EVIDENCE_CLASS_RANK[right] else right


def stage_index(stage: CompilationStage | str) -> int:
    """Return the fixed P7 index of *stage*."""

    selected = _enum(stage, CompilationStage, "stage")
    return _STAGE_INDEX[selected]


def stage_successor(stage: CompilationStage | str) -> CompilationStage | None:
    """Return the next compilation stage, or ``None`` after backend."""

    index = stage_index(stage)
    if index + 1 >= len(STAGE_ORDER):
        return None
    return STAGE_ORDER[index + 1]


def stages_are_adjacent(
    input_stage: CompilationStage | str,
    output_stage: CompilationStage | str,
) -> bool:
    """Return whether *output_stage* is the immediate successor of *input_stage*."""

    return stage_successor(input_stage) is _enum(output_stage, CompilationStage, "output_stage")


def maximum_authority_for_evidence_class(
    evidence_class: EvidenceClass | str,
) -> EvidenceAuthority:
    """Return the hard authority ceiling implied by an evidence class."""

    return _MAXIMUM_AUTHORITY_FOR_EVIDENCE_CLASS[_enum(evidence_class, EvidenceClass, "evidence_class")]


def authority_capped_by_losses(
    losses: Sequence[UnsupportedConstruct],
    *,
    preservation: PreservationClaim,
    evidence_class: EvidenceClass | str,
    declared: EvidenceAuthority | str,
) -> EvidenceAuthority:
    """Compute the strongest authority a stage may claim.

    Rejected or omitted constructs force ``none``.  Any remaining unsupported
    construct caps the stage at ``advisory``.  Preservation class and evidence
    class apply independent ceilings.  The declared ceiling cannot exceed any
    of those caps.
    """

    selected = _enum(declared, EvidenceAuthority, "declared")
    ceiling = _weaker_authority(selected, maximum_authority_for(preservation.kind))
    ceiling = _weaker_authority(
        ceiling,
        maximum_authority_for_evidence_class(evidence_class),
    )
    if any(item.handling in _INCOMPLETE_HANDLING for item in losses):
        return _weaker_authority(ceiling, EvidenceAuthority.NONE)
    if losses:
        return _weaker_authority(ceiling, EvidenceAuthority.ADVISORY)
    return ceiling


def _loss_ids(losses: Sequence[UnsupportedConstruct]) -> tuple[str, ...]:
    return tuple(item.construct_id for item in losses)


def _assumption_ids(assumptions: Sequence[Assumption]) -> tuple[str, ...]:
    return tuple(item.assumption_id for item in assumptions)


def _obligation_ids(obligations: Sequence[ProofObligation]) -> tuple[str, ...]:
    return tuple(item.obligation_id for item in obligations)


def _bound_payloads(bounds: Sequence[TranslationBound]) -> tuple[bytes, ...]:
    return tuple(canonical_json_bytes(item.to_dict()) for item in bounds)


@dataclass(frozen=True, slots=True)
class StageArtifactRef:
    """Content-addressed artifact sitting at one compilation stage."""

    artifact_id: str
    stage: CompilationStage
    content_identity: str
    family_id: str = ""
    family_version: str = ""
    schema_version: str = STAGE_ARTIFACT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "artifact_id", _text(self.artifact_id, "artifact_id"))
        object.__setattr__(self, "stage", _enum(self.stage, CompilationStage, "stage"))
        object.__setattr__(
            self, "content_identity", _text(self.content_identity, "content_identity")
        )
        object.__setattr__(self, "family_id", _text(self.family_id, "family_id", optional=True))
        object.__setattr__(
            self,
            "family_version",
            _text(self.family_version, "family_version", optional=True),
        )
        if self.schema_version != STAGE_ARTIFACT_SCHEMA_VERSION:
            raise StageReceiptError(
                f"unsupported stage artifact schema {self.schema_version!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "content_identity": self.content_identity,
            "family_id": self.family_id,
            "family_version": self.family_version,
            "schema_version": self.schema_version,
            "stage": self.stage.value,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "StageArtifactRef":
        value = _mapping(value, "stage artifact")
        _reject_unknown(
            value,
            frozenset(
                {
                    "artifact_id",
                    "content_identity",
                    "family_id",
                    "family_version",
                    "schema_version",
                    "stage",
                }
            ),
            "stage artifact",
        )
        return cls(
            artifact_id=value.get("artifact_id", ""),
            stage=value.get("stage", ""),
            content_identity=value.get("content_identity", ""),
            family_id=value.get("family_id", ""),
            family_version=value.get("family_version", ""),
            schema_version=value.get("schema_version", STAGE_ARTIFACT_SCHEMA_VERSION),
        )


@dataclass(frozen=True, slots=True)
class SupportedSubset:
    """Declared fragment the compiler claims to lower faithfully."""

    subset_id: str
    feature_ids: tuple[str, ...]
    excluded_feature_ids: tuple[str, ...] = ()
    description: str = ""
    schema_version: str = SUPPORTED_SUBSET_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "subset_id", _text(self.subset_id, "subset_id"))
        object.__setattr__(
            self, "feature_ids", _sorted_unique(self.feature_ids, "feature_ids")
        )
        if not self.feature_ids:
            raise StageReceiptError("supported subset must name at least one feature")
        object.__setattr__(
            self,
            "excluded_feature_ids",
            _sorted_unique(self.excluded_feature_ids, "excluded_feature_ids"),
        )
        overlap = sorted(set(self.feature_ids) & set(self.excluded_feature_ids))
        if overlap:
            raise StageReceiptError(
                f"supported subset features cannot also be excluded: {overlap}"
            )
        object.__setattr__(
            self, "description", _text(self.description, "description", optional=True)
        )
        if self.schema_version != SUPPORTED_SUBSET_SCHEMA_VERSION:
            raise StageReceiptError(
                f"unsupported subset schema {self.schema_version!r}"
            )

    @property
    def identity(self) -> CanonicalIdentity:
        return canonical_identity(
            self.to_dict(),
            domain="formalization.supported.subset",
            schema_version=self.schema_version,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "description": self.description,
            "excluded_feature_ids": list(self.excluded_feature_ids),
            "feature_ids": list(self.feature_ids),
            "schema_version": self.schema_version,
            "subset_id": self.subset_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SupportedSubset":
        value = _mapping(value, "supported subset")
        _reject_unknown(
            value,
            frozenset(
                {
                    "description",
                    "excluded_feature_ids",
                    "feature_ids",
                    "schema_version",
                    "subset_id",
                }
            ),
            "supported subset",
        )
        return cls(
            subset_id=value.get("subset_id", ""),
            feature_ids=tuple(value.get("feature_ids", ())),
            excluded_feature_ids=tuple(value.get("excluded_feature_ids", ())),
            description=value.get("description", ""),
            schema_version=value.get("schema_version", SUPPORTED_SUBSET_SCHEMA_VERSION),
        )


@dataclass(frozen=True, slots=True)
class StageSourceMapEntry:
    """One grounded input-to-output node mapping for a compilation stage."""

    entry_id: str
    source_node_id: str
    disposition: StageMapDisposition
    target_node_ids: tuple[str, ...] = ()
    source_ref_ids: tuple[str, ...] = ()
    span_ids: tuple[str, ...] = ()
    reason: str = ""
    schema_version: str = STAGE_SOURCE_MAP_ENTRY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "entry_id", _text(self.entry_id, "entry_id"))
        object.__setattr__(
            self, "source_node_id", _text(self.source_node_id, "source_node_id")
        )
        object.__setattr__(
            self, "disposition", _enum(self.disposition, StageMapDisposition, "disposition")
        )
        object.__setattr__(
            self, "target_node_ids", _sorted_unique(self.target_node_ids, "target_node_ids")
        )
        object.__setattr__(
            self, "source_ref_ids", _sorted_unique(self.source_ref_ids, "source_ref_ids")
        )
        object.__setattr__(self, "span_ids", _sorted_unique(self.span_ids, "span_ids"))
        object.__setattr__(self, "reason", _text(self.reason, "reason", optional=True))
        if self.schema_version != STAGE_SOURCE_MAP_ENTRY_SCHEMA_VERSION:
            raise StageReceiptError(
                f"unsupported source-map entry schema {self.schema_version!r}"
            )
        if (
            self.disposition
            in {
                StageMapDisposition.PRESERVED,
                StageMapDisposition.MAPPED,
                StageMapDisposition.APPROXIMATED,
            }
            and not self.target_node_ids
        ):
            raise StageReceiptError(
                f"{self.disposition.value} source-map entries require target_node_ids"
            )
        if (
            self.disposition
            in {
                StageMapDisposition.DROPPED,
                StageMapDisposition.UNSUPPORTED,
            }
            and self.target_node_ids
        ):
            raise StageReceiptError(
                f"{self.disposition.value} source-map entries cannot declare target_node_ids"
            )
        if self.disposition is StageMapDisposition.DROPPED and not self.reason:
            raise StageReceiptError("dropped source-map entries require an explicit reason")
        if self.disposition is StageMapDisposition.SYNTHESIZED and not self.source_node_id:
            raise StageReceiptError("synthesized entries still require a source_node_id")
        if not self.source_ref_ids and not self.span_ids:
            raise StageReceiptError("source-map entries must retain source grounding")

    def to_dict(self) -> dict[str, Any]:
        return {
            "disposition": self.disposition.value,
            "entry_id": self.entry_id,
            "reason": self.reason,
            "schema_version": self.schema_version,
            "source_node_id": self.source_node_id,
            "source_ref_ids": list(self.source_ref_ids),
            "span_ids": list(self.span_ids),
            "target_node_ids": list(self.target_node_ids),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "StageSourceMapEntry":
        value = _mapping(value, "source-map entry")
        _reject_unknown(
            value,
            frozenset(
                {
                    "disposition",
                    "entry_id",
                    "reason",
                    "schema_version",
                    "source_node_id",
                    "source_ref_ids",
                    "span_ids",
                    "target_node_ids",
                }
            ),
            "source-map entry",
        )
        return cls(
            entry_id=value.get("entry_id", ""),
            source_node_id=value.get("source_node_id", ""),
            disposition=value.get("disposition", ""),
            target_node_ids=tuple(value.get("target_node_ids", ())),
            source_ref_ids=tuple(value.get("source_ref_ids", ())),
            span_ids=tuple(value.get("span_ids", ())),
            reason=value.get("reason", ""),
            schema_version=value.get(
                "schema_version", STAGE_SOURCE_MAP_ENTRY_SCHEMA_VERSION
            ),
        )


@dataclass(frozen=True, slots=True)
class StageSourceMap:
    """Complete, silent-drop-free source map for one compilation stage."""

    map_id: str
    entries: tuple[StageSourceMapEntry, ...]
    required_source_node_ids: tuple[str, ...] = ()
    schema_version: str = STAGE_SOURCE_MAP_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "map_id", _text(self.map_id, "map_id"))
        entries = _unique_by(
            _records(self.entries, StageSourceMapEntry, "entries"),
            "entry_id",
            "entries",
        )
        if not entries:
            raise StageReceiptError("stage source maps require at least one entry")
        source_nodes = [item.source_node_id for item in entries]
        if len(source_nodes) != len(set(source_nodes)):
            raise StageReceiptError("source-map entries must not reuse source_node_id")
        object.__setattr__(self, "entries", entries)
        object.__setattr__(
            self,
            "required_source_node_ids",
            _sorted_unique(self.required_source_node_ids, "required_source_node_ids"),
        )
        missing = sorted(set(self.required_source_node_ids) - set(source_nodes))
        if missing:
            raise StageReceiptError(
                "source map is missing required source nodes "
                f"{missing}; silent drops are forbidden"
            )
        if self.schema_version != STAGE_SOURCE_MAP_SCHEMA_VERSION:
            raise StageReceiptError(
                f"unsupported source-map schema {self.schema_version!r}"
            )

    @property
    def identity(self) -> CanonicalIdentity:
        return canonical_identity(
            self.to_dict(),
            domain="formalization.stage.source_map",
            schema_version=self.schema_version,
        )

    @property
    def source_node_ids(self) -> tuple[str, ...]:
        return tuple(item.source_node_id for item in self.entries)

    def to_dict(self) -> dict[str, Any]:
        return {
            "entries": [item.to_dict() for item in self.entries],
            "map_id": self.map_id,
            "required_source_node_ids": list(self.required_source_node_ids),
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "StageSourceMap":
        value = _mapping(value, "stage source map")
        _reject_unknown(
            value,
            frozenset(
                {
                    "entries",
                    "map_id",
                    "required_source_node_ids",
                    "schema_version",
                }
            ),
            "stage source map",
        )
        return cls(
            map_id=value.get("map_id", ""),
            entries=tuple(value.get("entries", ())),
            required_source_node_ids=tuple(value.get("required_source_node_ids", ())),
            schema_version=value.get("schema_version", STAGE_SOURCE_MAP_SCHEMA_VERSION),
        )


@dataclass(frozen=True, slots=True)
class StageReplayManifest:
    """Pinned inputs needed to replay one compilation stage independently."""

    replay_id: str
    compiler: CompilerBinding
    input_identity: str
    output_identity: str
    configuration_identity: str = ""
    checker_id: str = ""
    checker_version: str = ""
    replay_inputs: FrozenMap = field(default_factory=FrozenMap)
    schema_version: str = STAGE_REPLAY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "replay_id", _text(self.replay_id, "replay_id"))
        object.__setattr__(self, "compiler", _record(self.compiler, CompilerBinding, "compiler"))
        object.__setattr__(
            self, "input_identity", _text(self.input_identity, "input_identity")
        )
        object.__setattr__(
            self, "output_identity", _text(self.output_identity, "output_identity")
        )
        object.__setattr__(
            self,
            "configuration_identity",
            _text(self.configuration_identity, "configuration_identity", optional=True),
        )
        object.__setattr__(self, "checker_id", _text(self.checker_id, "checker_id", optional=True))
        object.__setattr__(
            self,
            "checker_version",
            _text(self.checker_version, "checker_version", optional=True),
        )
        object.__setattr__(self, "replay_inputs", _frozen(self.replay_inputs, "replay_inputs"))
        if self.schema_version != STAGE_REPLAY_SCHEMA_VERSION:
            raise StageReceiptError(f"unsupported replay schema {self.schema_version!r}")

    @property
    def identity(self) -> CanonicalIdentity:
        return canonical_identity(
            self.to_dict(),
            domain="formalization.stage.replay",
            schema_version=self.schema_version,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "checker_id": self.checker_id,
            "checker_version": self.checker_version,
            "compiler": self.compiler.to_dict(),
            "configuration_identity": self.configuration_identity,
            "input_identity": self.input_identity,
            "output_identity": self.output_identity,
            "replay_id": self.replay_id,
            "replay_inputs": self.replay_inputs.to_dict(),
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "StageReplayManifest":
        value = _mapping(value, "stage replay manifest")
        _reject_unknown(
            value,
            frozenset(
                {
                    "checker_id",
                    "checker_version",
                    "compiler",
                    "configuration_identity",
                    "input_identity",
                    "output_identity",
                    "replay_id",
                    "replay_inputs",
                    "schema_version",
                }
            ),
            "stage replay manifest",
        )
        return cls(
            replay_id=value.get("replay_id", ""),
            compiler=value.get("compiler", {}),
            input_identity=value.get("input_identity", ""),
            output_identity=value.get("output_identity", ""),
            configuration_identity=value.get("configuration_identity", ""),
            checker_id=value.get("checker_id", ""),
            checker_version=value.get("checker_version", ""),
            replay_inputs=_frozen(value.get("replay_inputs", {}), "replay_inputs"),
            schema_version=value.get("schema_version", STAGE_REPLAY_SCHEMA_VERSION),
        )


@dataclass(frozen=True, slots=True)
class StageCounterexample:
    """Optional counterexample bound to a failed or disproving validation."""

    counterexample_id: str
    artifact_identity: str
    description: str = ""
    schema_version: str = STAGE_COUNTEREXAMPLE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "counterexample_id", _text(self.counterexample_id, "counterexample_id")
        )
        object.__setattr__(
            self, "artifact_identity", _text(self.artifact_identity, "artifact_identity")
        )
        object.__setattr__(
            self, "description", _text(self.description, "description", optional=True)
        )
        if self.schema_version != STAGE_COUNTEREXAMPLE_SCHEMA_VERSION:
            raise StageReceiptError(
                f"unsupported counterexample schema {self.schema_version!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_identity": self.artifact_identity,
            "counterexample_id": self.counterexample_id,
            "description": self.description,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "StageCounterexample":
        value = _mapping(value, "stage counterexample")
        _reject_unknown(
            value,
            frozenset(
                {
                    "artifact_identity",
                    "counterexample_id",
                    "description",
                    "schema_version",
                }
            ),
            "stage counterexample",
        )
        return cls(
            counterexample_id=value.get("counterexample_id", ""),
            artifact_identity=value.get("artifact_identity", ""),
            description=value.get("description", ""),
            schema_version=value.get(
                "schema_version", STAGE_COUNTEREXAMPLE_SCHEMA_VERSION
            ),
        )


@dataclass(frozen=True, slots=True)
class StageValidationRecord:
    """Independent translation-validation outcome bound into the receipt."""

    status: StageValidationStatus
    checker_id: str
    checker_version: str
    validated_identity: str
    issues: tuple[str, ...] = ()
    counterexamples: tuple[StageCounterexample, ...] = ()
    schema_version: str = STAGE_VALIDATION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "status", _enum(self.status, StageValidationStatus, "status")
        )
        object.__setattr__(self, "checker_id", _text(self.checker_id, "checker_id"))
        object.__setattr__(
            self, "checker_version", _text(self.checker_version, "checker_version")
        )
        object.__setattr__(
            self, "validated_identity", _text(self.validated_identity, "validated_identity")
        )
        object.__setattr__(self, "issues", _strings(self.issues, "issues"))
        object.__setattr__(
            self,
            "counterexamples",
            _unique_by(
                _records(self.counterexamples, StageCounterexample, "counterexamples"),
                "counterexample_id",
                "counterexamples",
            ),
        )
        if self.status is StageValidationStatus.VALID and self.issues:
            raise StageReceiptError("valid translation checks cannot retain issues")
        if self.status is not StageValidationStatus.VALID and not self.issues:
            raise StageReceiptError("non-valid translation checks require at least one issue")
        if self.schema_version != STAGE_VALIDATION_SCHEMA_VERSION:
            raise StageReceiptError(
                f"unsupported validation schema {self.schema_version!r}"
            )

    @property
    def identity(self) -> CanonicalIdentity:
        return canonical_identity(
            self.to_dict(),
            domain="formalization.stage.validation",
            schema_version=self.schema_version,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "checker_id": self.checker_id,
            "checker_version": self.checker_version,
            "counterexamples": [item.to_dict() for item in self.counterexamples],
            "issues": list(self.issues),
            "schema_version": self.schema_version,
            "status": self.status.value,
            "validated_identity": self.validated_identity,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "StageValidationRecord":
        value = _mapping(value, "stage validation")
        _reject_unknown(
            value,
            frozenset(
                {
                    "checker_id",
                    "checker_version",
                    "counterexamples",
                    "issues",
                    "schema_version",
                    "status",
                    "validated_identity",
                }
            ),
            "stage validation",
        )
        return cls(
            status=value.get("status", ""),
            checker_id=value.get("checker_id", ""),
            checker_version=value.get("checker_version", ""),
            validated_identity=value.get("validated_identity", ""),
            issues=tuple(value.get("issues", ())),
            counterexamples=tuple(value.get("counterexamples", ())),
            schema_version=value.get("schema_version", STAGE_VALIDATION_SCHEMA_VERSION),
        )


@dataclass(frozen=True, slots=True)
class StageTranslationReceipt:
    """One immutable, content-addressed compilation-stage receipt."""

    input: StageArtifactRef
    output: StageArtifactRef
    compiler: CompilerBinding
    source_map: StageSourceMap
    supported_subset: SupportedSubset
    losses: tuple[UnsupportedConstruct, ...]
    assumptions: tuple[Assumption, ...]
    obligations: tuple[ProofObligation, ...]
    validation: StageValidationRecord
    replay: StageReplayManifest
    bounds: tuple[TranslationBound, ...]
    evidence_class: EvidenceClass
    preservation_claim: PreservationClaim
    authority_ceiling: EvidenceAuthority
    semantic_mutations: tuple[SemanticMutation, ...] = ()
    metadata: FrozenMap = field(default_factory=FrozenMap)
    receipt_id: str = ""
    schema_version: str = STAGE_TRANSLATION_RECEIPT_SCHEMA_VERSION

    INTERFACE: ClassVar[str] = STAGE_TRANSLATION_RECEIPT_INTERFACE

    def __post_init__(self) -> None:
        object.__setattr__(self, "input", _record(self.input, StageArtifactRef, "input"))
        object.__setattr__(self, "output", _record(self.output, StageArtifactRef, "output"))
        if self.input.content_identity == self.output.content_identity:
            raise StageReceiptError("input and output content identities must differ")
        if not stages_are_adjacent(self.input.stage, self.output.stage):
            raise StageReceiptError(
                f"stage {self.input.stage.value!r} cannot compile directly to "
                f"{self.output.stage.value!r}; stages must be adjacent"
            )
        object.__setattr__(self, "compiler", _record(self.compiler, CompilerBinding, "compiler"))
        if self.compiler.stage != self.output.stage.value:
            raise StageReceiptError(
                "compiler.stage must equal the output compilation stage"
            )
        object.__setattr__(
            self, "source_map", _record(self.source_map, StageSourceMap, "source_map")
        )
        object.__setattr__(
            self,
            "supported_subset",
            _record(self.supported_subset, SupportedSubset, "supported_subset"),
        )
        object.__setattr__(
            self,
            "losses",
            _unique_by(
                _records(self.losses, UnsupportedConstruct, "losses"),
                "construct_id",
                "losses",
            ),
        )
        object.__setattr__(
            self,
            "assumptions",
            _unique_by(
                _records(self.assumptions, Assumption, "assumptions"),
                "assumption_id",
                "assumptions",
            ),
        )
        object.__setattr__(
            self,
            "obligations",
            _unique_by(
                _records(self.obligations, ProofObligation, "obligations"),
                "obligation_id",
                "obligations",
            ),
        )
        known_assumptions = set(_assumption_ids(self.assumptions))
        for obligation in self.obligations:
            missing = sorted(set(obligation.assumption_ids) - known_assumptions)
            if missing:
                raise StageReceiptError(
                    f"obligation {obligation.obligation_id} references unknown "
                    f"assumptions {missing}"
                )
        object.__setattr__(
            self,
            "validation",
            _record(self.validation, StageValidationRecord, "validation"),
        )
        object.__setattr__(self, "replay", _record(self.replay, StageReplayManifest, "replay"))
        if self.replay.input_identity != self.input.content_identity:
            raise StageReceiptError("replay input identity must match the stage input")
        if self.replay.output_identity != self.output.content_identity:
            raise StageReceiptError("replay output identity must match the stage output")
        if self.replay.compiler.binding_id != self.compiler.binding_id:
            raise StageReceiptError("replay compiler must match the pinned compiler")
        object.__setattr__(
            self,
            "bounds",
            _unique_by(
                _records(self.bounds, TranslationBound, "bounds"),
                "bound_id",
                "bounds",
            ),
        )
        object.__setattr__(
            self,
            "evidence_class",
            _enum(self.evidence_class, EvidenceClass, "evidence_class"),
        )
        object.__setattr__(
            self,
            "preservation_claim",
            _record(self.preservation_claim, PreservationClaim, "preservation_claim"),
        )
        object.__setattr__(
            self,
            "authority_ceiling",
            _enum(self.authority_ceiling, EvidenceAuthority, "authority_ceiling"),
        )
        object.__setattr__(
            self,
            "semantic_mutations",
            _unique_by(
                _records(self.semantic_mutations, SemanticMutation, "semantic_mutations"),
                "mutation_id",
                "semantic_mutations",
            ),
        )
        object.__setattr__(self, "metadata", _frozen(self.metadata, "metadata"))
        if self.schema_version != STAGE_TRANSLATION_RECEIPT_SCHEMA_VERSION:
            raise StageReceiptError(
                f"unsupported stage translation receipt schema {self.schema_version!r}"
            )
        self._validate_semantics()
        computed = self._compute_identity()
        if self.receipt_id and self.receipt_id != computed.cid:
            raise StageReceiptError("receipt_id does not match canonical receipt content")
        object.__setattr__(self, "receipt_id", computed.cid)

    def _validate_semantics(self) -> None:
        claim = self.preservation_claim
        # Loss/validation caps are the public authority-refusal contract and
        # must precede generic preservation/evidence-class ceilings.
        incomplete = any(item.handling in _INCOMPLETE_HANDLING for item in self.losses)
        if incomplete and self.authority_ceiling is not EvidenceAuthority.NONE:
            raise StageReceiptError(
                "rejected or omitted losses require authority_ceiling=none"
            )
        if claim.kind is PreservationKind.EXACT and self.losses:
            raise StageReceiptError("exact translations cannot contain unsupported losses")
        if self.losses and not authority_at_most(
            self.authority_ceiling, EvidenceAuthority.ADVISORY
        ):
            raise StageReceiptError("unsupported losses cap stage authority at advisory")
        if (
            self.validation.status is not StageValidationStatus.VALID
            and self.authority_ceiling is not EvidenceAuthority.NONE
        ):
            raise StageReceiptError(
                "non-valid translation checks require authority_ceiling=none"
            )
        if not claim.permits_authority(self.authority_ceiling):
            raise StageReceiptError(
                f"{claim.kind.value} preservation cannot carry "
                f"{self.authority_ceiling.value} authority"
            )
        if not authority_at_most(
            self.authority_ceiling,
            maximum_authority_for_evidence_class(self.evidence_class),
        ):
            raise StageReceiptError(
                f"{self.evidence_class.value} evidence cannot carry "
                f"{self.authority_ceiling.value} authority"
            )
        if claim.kind is PreservationKind.EXACT:
            if self.bounds:
                raise StageReceiptError("exact translations cannot introduce semantic bounds")
            if self.semantic_mutations:
                raise StageReceiptError("exact translations cannot contain semantic mutations")
        if claim.kind is PreservationKind.BOUNDED and not self.bounds:
            raise StageReceiptError("bounded translations require at least one explicit bound")
        if self.bounds and claim.kind not in {
            PreservationKind.BOUNDED,
            PreservationKind.APPROXIMATE,
            PreservationKind.HEURISTIC,
            PreservationKind.CONSERVATIVE,
        }:
            raise StageReceiptError(
                f"{claim.kind.value} translations cannot introduce bounds"
            )

        known_assumptions = set(_assumption_ids(self.assumptions))
        known_bounds = {item.bound_id for item in self.bounds}
        known_losses = set(_loss_ids(self.losses))
        for mutation in self.semantic_mutations:
            missing_assumptions = sorted(set(mutation.assumption_ids) - known_assumptions)
            if missing_assumptions:
                raise StageReceiptError(
                    f"mutation {mutation.mutation_id} references unknown "
                    f"assumptions {missing_assumptions}"
                )
            missing_bounds = sorted(set(mutation.bound_ids) - known_bounds)
            if missing_bounds:
                raise StageReceiptError(
                    f"mutation {mutation.mutation_id} references unknown bounds {missing_bounds}"
                )
            missing_constructs = sorted(
                set(mutation.source_construct_ids) - known_losses - set(self.source_map.source_node_ids)
            )
            if missing_constructs:
                raise StageReceiptError(
                    f"mutation {mutation.mutation_id} references unknown source "
                    f"constructs {missing_constructs}"
                )

        capped = authority_capped_by_losses(
            self.losses,
            preservation=self.preservation_claim,
            evidence_class=self.evidence_class,
            declared=self.authority_ceiling,
        )
        if self.authority_ceiling is not capped:
            raise StageReceiptError(
                "declared authority_ceiling exceeds the loss/evidence/preservation cap "
                f"{capped.value}"
            )

    @property
    def identity(self) -> CanonicalIdentity:
        return self._compute_identity()

    @property
    def content_id(self) -> str:
        return self.receipt_id

    @property
    def input_stage(self) -> CompilationStage:
        return self.input.stage

    @property
    def output_stage(self) -> CompilationStage:
        return self.output.stage

    def bound_fields(self) -> dict[str, Any]:
        """Return the twelve required bindings as a detached mapping."""

        payload = self.semantic_dict()
        return {name: payload[name] for name in REQUIRED_STAGE_BINDINGS}

    def _compute_identity(self) -> CanonicalIdentity:
        return canonical_identity(
            self.semantic_dict(),
            domain=STAGE_TRANSLATION_RECEIPT_IDENTITY_DOMAIN,
            schema_version=self.schema_version,
        )

    def semantic_dict(self) -> dict[str, Any]:
        """Return the complete canonical identity preimage."""

        return {
            "assumptions": [item.to_dict() for item in self.assumptions],
            "authority_ceiling": self.authority_ceiling.value,
            "bounds": [item.to_dict() for item in self.bounds],
            "compiler": self.compiler.to_dict(),
            "evidence_class": self.evidence_class.value,
            "input": self.input.to_dict(),
            "interface": self.INTERFACE,
            "losses": [item.to_dict() for item in self.losses],
            "metadata": self.metadata.to_dict(),
            "obligations": [item.to_dict() for item in self.obligations],
            "output": self.output.to_dict(),
            "preservation_claim": self.preservation_claim.to_dict(),
            "replay": self.replay.to_dict(),
            "schema_version": self.schema_version,
            "semantic_mutations": [item.to_dict() for item in self.semantic_mutations],
            "source_map": self.source_map.to_dict(),
            "supported_subset": self.supported_subset.to_dict(),
            "validation": self.validation.to_dict(),
        }

    deterministic_dict = semantic_dict

    def to_dict(self) -> dict[str, Any]:
        result = self.semantic_dict()
        result["receipt_id"] = self.receipt_id
        return result

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())

    def to_json(self) -> str:
        return self.canonical_bytes().decode("utf-8")

    def validate_current(
        self, expectation: "StageReceiptExpectation"
    ) -> "StageReceiptValidation":
        return validate_stage_receipt(self, expectation)

    def require_current(
        self, expectation: "StageReceiptExpectation"
    ) -> "StageTranslationReceipt":
        return require_current_stage_receipt(self, expectation)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "StageTranslationReceipt":
        value = _mapping(value, "stage translation receipt")
        _reject_unknown(
            value,
            frozenset(
                {
                    "assumptions",
                    "authority_ceiling",
                    "bounds",
                    "compiler",
                    "evidence_class",
                    "input",
                    "interface",
                    "losses",
                    "metadata",
                    "obligations",
                    "output",
                    "preservation_claim",
                    "receipt_id",
                    "replay",
                    "schema_version",
                    "semantic_mutations",
                    "source_map",
                    "supported_subset",
                    "validation",
                }
            ),
            "stage translation receipt",
        )
        interface = value.get("interface", STAGE_TRANSLATION_RECEIPT_INTERFACE)
        if interface != STAGE_TRANSLATION_RECEIPT_INTERFACE:
            raise StageReceiptError(
                f"unsupported stage translation receipt interface {interface!r}"
            )
        return cls(
            input=value.get("input", {}),
            output=value.get("output", {}),
            compiler=value.get("compiler", {}),
            source_map=value.get("source_map", {}),
            supported_subset=value.get("supported_subset", {}),
            losses=tuple(value.get("losses", ())),
            assumptions=tuple(value.get("assumptions", ())),
            obligations=tuple(value.get("obligations", ())),
            validation=value.get("validation", {}),
            replay=value.get("replay", {}),
            bounds=tuple(value.get("bounds", ())),
            evidence_class=value.get("evidence_class", EvidenceClass.NONE.value),
            preservation_claim=value.get("preservation_claim", {}),
            authority_ceiling=value.get("authority_ceiling", EvidenceAuthority.NONE.value),
            semantic_mutations=tuple(value.get("semantic_mutations", ())),
            metadata=_frozen(value.get("metadata", {}), "metadata"),
            receipt_id=value.get("receipt_id", ""),
            schema_version=value.get(
                "schema_version", STAGE_TRANSLATION_RECEIPT_SCHEMA_VERSION
            ),
        )


@dataclass(frozen=True, slots=True)
class StageReceiptExpectation:
    """Current semantic inputs against which a stage receipt must be checked."""

    input: StageArtifactRef
    output: StageArtifactRef
    compiler: CompilerBinding
    source_map: StageSourceMap
    supported_subset: SupportedSubset
    losses: tuple[UnsupportedConstruct, ...] = ()
    assumptions: tuple[Assumption, ...] = ()
    obligations: tuple[ProofObligation, ...] = ()
    validation: StageValidationRecord | None = None
    replay: StageReplayManifest | None = None
    bounds: tuple[TranslationBound, ...] = ()
    evidence_class: EvidenceClass | None = None
    preservation_claim: PreservationClaim | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "input", _record(self.input, StageArtifactRef, "input"))
        object.__setattr__(self, "output", _record(self.output, StageArtifactRef, "output"))
        object.__setattr__(self, "compiler", _record(self.compiler, CompilerBinding, "compiler"))
        object.__setattr__(
            self, "source_map", _record(self.source_map, StageSourceMap, "source_map")
        )
        object.__setattr__(
            self,
            "supported_subset",
            _record(self.supported_subset, SupportedSubset, "supported_subset"),
        )
        object.__setattr__(
            self,
            "losses",
            _unique_by(
                _records(self.losses, UnsupportedConstruct, "losses"),
                "construct_id",
                "losses",
            ),
        )
        object.__setattr__(
            self,
            "assumptions",
            _unique_by(
                _records(self.assumptions, Assumption, "assumptions"),
                "assumption_id",
                "assumptions",
            ),
        )
        object.__setattr__(
            self,
            "obligations",
            _unique_by(
                _records(self.obligations, ProofObligation, "obligations"),
                "obligation_id",
                "obligations",
            ),
        )
        if self.validation is not None:
            object.__setattr__(
                self,
                "validation",
                _record(self.validation, StageValidationRecord, "validation"),
            )
        if self.replay is not None:
            object.__setattr__(
                self, "replay", _record(self.replay, StageReplayManifest, "replay")
            )
        object.__setattr__(
            self,
            "bounds",
            _unique_by(
                _records(self.bounds, TranslationBound, "bounds"),
                "bound_id",
                "bounds",
            ),
        )
        if self.evidence_class is not None:
            object.__setattr__(
                self,
                "evidence_class",
                _enum(self.evidence_class, EvidenceClass, "evidence_class"),
            )
        if self.preservation_claim is not None:
            object.__setattr__(
                self,
                "preservation_claim",
                _record(self.preservation_claim, PreservationClaim, "preservation_claim"),
            )

    @classmethod
    def from_receipt(cls, receipt: StageTranslationReceipt) -> "StageReceiptExpectation":
        if not isinstance(receipt, StageTranslationReceipt):
            raise StageReceiptError("receipt must be a StageTranslationReceipt")
        return cls(
            input=receipt.input,
            output=receipt.output,
            compiler=receipt.compiler,
            source_map=receipt.source_map,
            supported_subset=receipt.supported_subset,
            losses=receipt.losses,
            assumptions=receipt.assumptions,
            obligations=receipt.obligations,
            validation=receipt.validation,
            replay=receipt.replay,
            bounds=receipt.bounds,
            evidence_class=receipt.evidence_class,
            preservation_claim=receipt.preservation_claim,
        )

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "assumptions": [item.to_dict() for item in self.assumptions],
            "bounds": [item.to_dict() for item in self.bounds],
            "compiler": self.compiler.to_dict(),
            "input": self.input.to_dict(),
            "losses": [item.to_dict() for item in self.losses],
            "obligations": [item.to_dict() for item in self.obligations],
            "output": self.output.to_dict(),
            "source_map": self.source_map.to_dict(),
            "supported_subset": self.supported_subset.to_dict(),
        }
        if self.validation is not None:
            payload["validation"] = self.validation.to_dict()
        if self.replay is not None:
            payload["replay"] = self.replay.to_dict()
        if self.evidence_class is not None:
            payload["evidence_class"] = self.evidence_class.value
        if self.preservation_claim is not None:
            payload["preservation_claim"] = self.preservation_claim.to_dict()
        return payload

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "StageReceiptExpectation":
        value = _mapping(value, "stage receipt expectation")
        _reject_unknown(
            value,
            frozenset(
                {
                    "assumptions",
                    "bounds",
                    "compiler",
                    "evidence_class",
                    "input",
                    "losses",
                    "obligations",
                    "output",
                    "preservation_claim",
                    "replay",
                    "source_map",
                    "supported_subset",
                    "validation",
                }
            ),
            "stage receipt expectation",
        )
        return cls(
            input=value.get("input", {}),
            output=value.get("output", {}),
            compiler=value.get("compiler", {}),
            source_map=value.get("source_map", {}),
            supported_subset=value.get("supported_subset", {}),
            losses=tuple(value.get("losses", ())),
            assumptions=tuple(value.get("assumptions", ())),
            obligations=tuple(value.get("obligations", ())),
            validation=value.get("validation"),
            replay=value.get("replay"),
            bounds=tuple(value.get("bounds", ())),
            evidence_class=value.get("evidence_class"),
            preservation_claim=value.get("preservation_claim"),
        )


@dataclass(frozen=True, slots=True)
class StageReceiptIssue:
    """One stable stage-receipt validation failure."""

    code: StageReceiptIssueCode
    detail: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "code", _enum(self.code, StageReceiptIssueCode, "code"))
        object.__setattr__(self, "detail", _text(self.detail, "detail"))

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code.value, "detail": self.detail}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "StageReceiptIssue":
        value = _mapping(value, "stage receipt issue")
        _reject_unknown(value, frozenset({"code", "detail"}), "stage receipt issue")
        return cls(code=value.get("code", ""), detail=value.get("detail", ""))


@dataclass(frozen=True, slots=True)
class StageReceiptValidation:
    """Fail-closed current-revision decision for one stage receipt."""

    receipt_id: str
    current: bool
    issues: tuple[StageReceiptIssue, ...]
    effective_authority_ceiling: EvidenceAuthority
    schema_version: str = STAGE_RECEIPT_VALIDATION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "receipt_id", _text(self.receipt_id, "receipt_id", optional=True)
        )
        object.__setattr__(self, "current", _bool(self.current, "current"))
        object.__setattr__(
            self, "issues", _records(self.issues, StageReceiptIssue, "issues")
        )
        if self.current != (not self.issues):
            raise StageReceiptError("current must be true exactly when issues are empty")
        object.__setattr__(
            self,
            "effective_authority_ceiling",
            _enum(
                self.effective_authority_ceiling,
                EvidenceAuthority,
                "effective_authority_ceiling",
            ),
        )
        if self.issues and self.effective_authority_ceiling is not EvidenceAuthority.NONE:
            raise StageReceiptError("invalid receipts must have effective authority none")
        if self.schema_version != STAGE_RECEIPT_VALIDATION_SCHEMA_VERSION:
            raise StageReceiptError(
                f"unsupported stage receipt validation schema {self.schema_version!r}"
            )

    @property
    def valid(self) -> bool:
        return self.current

    @property
    def stale(self) -> bool:
        return bool(self.receipt_id) and not self.current

    @property
    def promotion_allowed(self) -> bool:
        return self.current and self.effective_authority_ceiling is not EvidenceAuthority.NONE

    def permits(self, authority: EvidenceAuthority | str) -> bool:
        return self.current and authority_at_most(authority, self.effective_authority_ceiling)

    def to_dict(self) -> dict[str, Any]:
        return {
            "current": self.current,
            "effective_authority_ceiling": self.effective_authority_ceiling.value,
            "issues": [item.to_dict() for item in self.issues],
            "receipt_id": self.receipt_id,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "StageReceiptValidation":
        value = _mapping(value, "stage receipt validation")
        _reject_unknown(
            value,
            frozenset(
                {
                    "current",
                    "effective_authority_ceiling",
                    "issues",
                    "receipt_id",
                    "schema_version",
                }
            ),
            "stage receipt validation",
        )
        return cls(
            receipt_id=value.get("receipt_id", ""),
            current=value.get("current", False),
            issues=tuple(value.get("issues", ())),
            effective_authority_ceiling=value.get(
                "effective_authority_ceiling", EvidenceAuthority.NONE.value
            ),
            schema_version=value.get(
                "schema_version", STAGE_RECEIPT_VALIDATION_SCHEMA_VERSION
            ),
        )


@dataclass(frozen=True, slots=True)
class StageReplayResult:
    """Outcome of independently replaying one stage receipt."""

    receipt_id: str
    reproduced: bool
    issues: tuple[StageReceiptIssue, ...]
    effective_authority_ceiling: EvidenceAuthority

    def __post_init__(self) -> None:
        object.__setattr__(self, "receipt_id", _text(self.receipt_id, "receipt_id"))
        object.__setattr__(self, "reproduced", _bool(self.reproduced, "reproduced"))
        object.__setattr__(
            self, "issues", _records(self.issues, StageReceiptIssue, "issues")
        )
        object.__setattr__(
            self,
            "effective_authority_ceiling",
            _enum(
                self.effective_authority_ceiling,
                EvidenceAuthority,
                "effective_authority_ceiling",
            ),
        )
        if self.reproduced != (not self.issues):
            raise StageReceiptError("reproduced must be true exactly when issues are empty")
        if self.issues and self.effective_authority_ceiling is not EvidenceAuthority.NONE:
            raise StageReceiptError("failed replay must have effective authority none")

    def to_dict(self) -> dict[str, Any]:
        return {
            "effective_authority_ceiling": self.effective_authority_ceiling.value,
            "issues": [item.to_dict() for item in self.issues],
            "receipt_id": self.receipt_id,
            "reproduced": self.reproduced,
        }


@dataclass(frozen=True, slots=True)
class CompilationPipelineReceipt:
    """Weakest-link composition of adjacent stage receipts."""

    pipeline_id: str
    stages: tuple[StageTranslationReceipt, ...]
    source_identity: str
    backend_identity: str
    authority_ceiling: EvidenceAuthority
    evidence_class: EvidenceClass
    receipt_id: str = ""
    schema_version: str = PIPELINE_RECEIPT_SCHEMA_VERSION

    INTERFACE: ClassVar[str] = PIPELINE_RECEIPT_INTERFACE

    def __post_init__(self) -> None:
        object.__setattr__(self, "pipeline_id", _text(self.pipeline_id, "pipeline_id"))
        stages = _records(self.stages, StageTranslationReceipt, "stages")
        if not stages:
            raise StageReceiptError("pipeline receipts require at least one stage")
        object.__setattr__(self, "stages", stages)
        object.__setattr__(
            self, "source_identity", _text(self.source_identity, "source_identity")
        )
        object.__setattr__(
            self, "backend_identity", _text(self.backend_identity, "backend_identity")
        )
        object.__setattr__(
            self,
            "authority_ceiling",
            _enum(self.authority_ceiling, EvidenceAuthority, "authority_ceiling"),
        )
        object.__setattr__(
            self,
            "evidence_class",
            _enum(self.evidence_class, EvidenceClass, "evidence_class"),
        )
        if self.schema_version != PIPELINE_RECEIPT_SCHEMA_VERSION:
            raise StageReceiptError(
                f"unsupported pipeline receipt schema {self.schema_version!r}"
            )
        self._validate_chain()
        computed = self._compute_identity()
        if self.receipt_id and self.receipt_id != computed.cid:
            raise StageReceiptError("receipt_id does not match canonical pipeline content")
        object.__setattr__(self, "receipt_id", computed.cid)

    def _validate_chain(self) -> None:
        first = self.stages[0]
        last = self.stages[-1]
        if first.input.content_identity != self.source_identity:
            raise StageReceiptError("pipeline source_identity must match the first input")
        if last.output.content_identity != self.backend_identity:
            raise StageReceiptError("pipeline backend_identity must match the last output")
        running_authority = first.authority_ceiling
        running_class = first.evidence_class
        running_cap = authority_capped_by_losses(
            first.losses,
            preservation=first.preservation_claim,
            evidence_class=first.evidence_class,
            declared=first.authority_ceiling,
        )
        for index, stage in enumerate(self.stages[1:], start=1):
            previous = self.stages[index - 1]
            if previous.output.stage is not stage.input.stage:
                raise StageReceiptError(
                    "pipeline stages must be adjacent: "
                    f"{previous.output.stage.value} -> {stage.input.stage.value}"
                )
            if previous.output.content_identity != stage.input.content_identity:
                raise StageReceiptError(
                    "pipeline stage output identity must feed the next input"
                )
            if not authority_at_most(stage.authority_ceiling, running_cap):
                raise StageReceiptError(
                    "unsupported losses cap downstream authority; "
                    f"stage {stage.output.stage.value} claims "
                    f"{stage.authority_ceiling.value} after upstream cap {running_cap.value}"
                )
            running_cap = _weaker_authority(
                running_cap,
                authority_capped_by_losses(
                    stage.losses,
                    preservation=stage.preservation_claim,
                    evidence_class=stage.evidence_class,
                    declared=stage.authority_ceiling,
                ),
            )
            running_authority = _weaker_authority(running_authority, stage.authority_ceiling)
            running_class = _weaker_evidence_class(running_class, stage.evidence_class)
        if self.authority_ceiling is not running_authority:
            raise StageReceiptError(
                "pipeline authority_ceiling must equal the weakest stage ceiling "
                f"({running_authority.value})"
            )
        if self.evidence_class is not running_class:
            raise StageReceiptError(
                "pipeline evidence_class must equal the weakest stage class "
                f"({running_class.value})"
            )
        if not authority_at_most(self.authority_ceiling, running_cap):
            raise StageReceiptError(
                "pipeline authority exceeds the composed loss cap "
                f"{running_cap.value}"
            )

    @property
    def identity(self) -> CanonicalIdentity:
        return self._compute_identity()

    @property
    def content_id(self) -> str:
        return self.receipt_id

    @property
    def stage_receipt_ids(self) -> tuple[str, ...]:
        return tuple(item.receipt_id for item in self.stages)

    def _compute_identity(self) -> CanonicalIdentity:
        return canonical_identity(
            self.semantic_dict(),
            domain=PIPELINE_RECEIPT_IDENTITY_DOMAIN,
            schema_version=self.schema_version,
        )

    def semantic_dict(self) -> dict[str, Any]:
        return {
            "authority_ceiling": self.authority_ceiling.value,
            "backend_identity": self.backend_identity,
            "evidence_class": self.evidence_class.value,
            "interface": self.INTERFACE,
            "pipeline_id": self.pipeline_id,
            "schema_version": self.schema_version,
            "source_identity": self.source_identity,
            "stages": [item.to_dict() for item in self.stages],
        }

    def to_dict(self) -> dict[str, Any]:
        result = self.semantic_dict()
        result["receipt_id"] = self.receipt_id
        return result

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())

    def to_json(self) -> str:
        return self.canonical_bytes().decode("utf-8")

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CompilationPipelineReceipt":
        value = _mapping(value, "compilation pipeline receipt")
        _reject_unknown(
            value,
            frozenset(
                {
                    "authority_ceiling",
                    "backend_identity",
                    "evidence_class",
                    "interface",
                    "pipeline_id",
                    "receipt_id",
                    "schema_version",
                    "source_identity",
                    "stages",
                }
            ),
            "compilation pipeline receipt",
        )
        interface = value.get("interface", PIPELINE_RECEIPT_INTERFACE)
        if interface != PIPELINE_RECEIPT_INTERFACE:
            raise StageReceiptError(
                f"unsupported compilation pipeline receipt interface {interface!r}"
            )
        return cls(
            pipeline_id=value.get("pipeline_id", ""),
            stages=tuple(value.get("stages", ())),
            source_identity=value.get("source_identity", ""),
            backend_identity=value.get("backend_identity", ""),
            authority_ceiling=value.get("authority_ceiling", EvidenceAuthority.NONE.value),
            evidence_class=value.get("evidence_class", EvidenceClass.NONE.value),
            receipt_id=value.get("receipt_id", ""),
            schema_version=value.get("schema_version", PIPELINE_RECEIPT_SCHEMA_VERSION),
        )


def infer_preservation_claim(
    *,
    losses: Sequence[UnsupportedConstruct] = (),
    bounds: Sequence[TranslationBound] = (),
    description: str = "",
) -> PreservationClaim:
    """Infer the strongest honest preservation class for explicit losses/bounds."""

    if any(item.handling in _INCOMPLETE_HANDLING for item in losses):
        return PreservationClaim(
            kind=PreservationKind.HEURISTIC,
            description=description or "Rejected or omitted constructs remain untranslated.",
        )
    if losses:
        return PreservationClaim(
            kind=PreservationKind.APPROXIMATE,
            description=description or "Unsupported constructs were approximated.",
        )
    if bounds:
        return PreservationClaim(
            kind=PreservationKind.BOUNDED,
            description=description or "Translation is valid only inside declared bounds.",
        )
    return PreservationClaim(
        kind=PreservationKind.EXACT,
        description=description or "The reviewed fragment is structurally preserved.",
    )


def emit_stage_receipt(
    *,
    input: StageArtifactRef,
    output: StageArtifactRef,
    compiler: CompilerBinding,
    source_map: StageSourceMap,
    supported_subset: SupportedSubset,
    validation: StageValidationRecord,
    replay: StageReplayManifest,
    evidence_class: EvidenceClass | str,
    losses: Sequence[UnsupportedConstruct] = (),
    assumptions: Sequence[Assumption] = (),
    obligations: Sequence[ProofObligation] = (),
    bounds: Sequence[TranslationBound] = (),
    preservation_claim: PreservationClaim | None = None,
    authority_ceiling: EvidenceAuthority | str | None = None,
    semantic_mutations: Sequence[SemanticMutation] = (),
    metadata: Mapping[str, Any] | FrozenMap = FrozenMap(),
) -> StageTranslationReceipt:
    """Construct a fail-closed stage receipt with every required binding."""

    selected_class = _enum(evidence_class, EvidenceClass, "evidence_class")
    claim = preservation_claim or infer_preservation_claim(losses=losses, bounds=bounds)
    if authority_ceiling is None:
        declared = authority_capped_by_losses(
            losses,
            preservation=claim,
            evidence_class=selected_class,
            declared=maximum_authority_for(claim.kind),
        )
        if validation.status is not StageValidationStatus.VALID:
            declared = EvidenceAuthority.NONE
    else:
        # Explicit ceilings are checked fail-closed by StageTranslationReceipt.
        declared = _enum(authority_ceiling, EvidenceAuthority, "authority_ceiling")
    return StageTranslationReceipt(
        input=input,
        output=output,
        compiler=compiler,
        source_map=source_map,
        supported_subset=supported_subset,
        losses=tuple(losses),
        assumptions=tuple(assumptions),
        obligations=tuple(obligations),
        validation=validation,
        replay=replay,
        bounds=tuple(bounds),
        evidence_class=selected_class,
        preservation_claim=claim,
        authority_ceiling=declared,
        semantic_mutations=tuple(semantic_mutations),
        metadata=metadata if isinstance(metadata, FrozenMap) else FrozenMap(metadata),
    )


def validate_stage_receipt(
    receipt: StageTranslationReceipt | None,
    expectation: StageReceiptExpectation,
) -> StageReceiptValidation:
    """Validate a receipt against all current compilation inputs.

    Absence and staleness never succeed.  The typed result carries effective
    authority ``none`` so diagnostic callers can retain the failure evidence.
    """

    if not isinstance(expectation, StageReceiptExpectation):
        raise StageReceiptError("expectation must be a StageReceiptExpectation")
    if receipt is None:
        return StageReceiptValidation(
            receipt_id="",
            current=False,
            issues=(
                StageReceiptIssue(
                    StageReceiptIssueCode.MISSING_RECEIPT,
                    "stage translation receipt is required",
                ),
            ),
            effective_authority_ceiling=EvidenceAuthority.NONE,
        )
    if not isinstance(receipt, StageTranslationReceipt):
        raise StageReceiptError("receipt must be a StageTranslationReceipt or None")

    issues: list[StageReceiptIssue] = []

    def compare(actual: object, expected: object, code: StageReceiptIssueCode, label: str) -> None:
        if actual != expected:
            issues.append(
                StageReceiptIssue(code, f"receipt {label} does not match current input")
            )

    compare(
        receipt.input.content_identity,
        expectation.input.content_identity,
        StageReceiptIssueCode.INPUT_IDENTITY_MISMATCH,
        "input identity",
    )
    compare(
        receipt.input.stage,
        expectation.input.stage,
        StageReceiptIssueCode.INPUT_STAGE_MISMATCH,
        "input stage",
    )
    compare(
        receipt.output.content_identity,
        expectation.output.content_identity,
        StageReceiptIssueCode.OUTPUT_IDENTITY_MISMATCH,
        "output identity",
    )
    compare(
        receipt.output.stage,
        expectation.output.stage,
        StageReceiptIssueCode.OUTPUT_STAGE_MISMATCH,
        "output stage",
    )
    compare(
        receipt.compiler.binding_id,
        expectation.compiler.binding_id,
        StageReceiptIssueCode.COMPILER_MISMATCH,
        "compiler",
    )
    compare(
        receipt.source_map.identity.cid,
        expectation.source_map.identity.cid,
        StageReceiptIssueCode.SOURCE_MAP_MISMATCH,
        "source map",
    )
    compare(
        receipt.supported_subset.identity.cid,
        expectation.supported_subset.identity.cid,
        StageReceiptIssueCode.SUBSET_MISMATCH,
        "supported subset",
    )
    compare(
        _loss_ids(receipt.losses),
        _loss_ids(expectation.losses),
        StageReceiptIssueCode.LOSS_MISMATCH,
        "losses",
    )
    compare(
        _assumption_ids(receipt.assumptions),
        _assumption_ids(expectation.assumptions),
        StageReceiptIssueCode.ASSUMPTION_MISMATCH,
        "assumptions",
    )
    compare(
        _obligation_ids(receipt.obligations),
        _obligation_ids(expectation.obligations),
        StageReceiptIssueCode.OBLIGATION_MISMATCH,
        "obligations",
    )
    compare(
        _bound_payloads(receipt.bounds),
        _bound_payloads(expectation.bounds),
        StageReceiptIssueCode.BOUND_MISMATCH,
        "bounds",
    )
    if expectation.validation is not None:
        compare(
            receipt.validation.identity.cid,
            expectation.validation.identity.cid,
            StageReceiptIssueCode.VALIDATION_MISMATCH,
            "validation",
        )
    if expectation.replay is not None:
        compare(
            receipt.replay.identity.cid,
            expectation.replay.identity.cid,
            StageReceiptIssueCode.REPLAY_MISMATCH,
            "replay",
        )
    if expectation.evidence_class is not None:
        compare(
            receipt.evidence_class,
            expectation.evidence_class,
            StageReceiptIssueCode.EVIDENCE_CLASS_MISMATCH,
            "evidence class",
        )
    if expectation.preservation_claim is not None:
        compare(
            receipt.preservation_claim.to_dict(),
            expectation.preservation_claim.to_dict(),
            StageReceiptIssueCode.PRESERVATION_MISMATCH,
            "preservation claim",
        )

    return StageReceiptValidation(
        receipt_id=receipt.receipt_id,
        current=not issues,
        issues=tuple(issues),
        effective_authority_ceiling=(
            receipt.authority_ceiling if not issues else EvidenceAuthority.NONE
        ),
    )


def require_current_stage_receipt(
    receipt: StageTranslationReceipt | None,
    expectation: StageReceiptExpectation,
) -> StageTranslationReceipt:
    """Return a current receipt, raising for absence or any stale binding."""

    validation = validate_stage_receipt(receipt, expectation)
    if receipt is None:
        raise MissingStageReceiptError("stage translation receipt is required")
    if not validation.current:
        codes = ", ".join(issue.code.value for issue in validation.issues)
        if any(
            issue.code
            in {
                StageReceiptIssueCode.INPUT_IDENTITY_MISMATCH,
                StageReceiptIssueCode.COMPILER_MISMATCH,
                StageReceiptIssueCode.SOURCE_MAP_MISMATCH,
                StageReceiptIssueCode.LOSS_MISMATCH,
                StageReceiptIssueCode.OBLIGATION_MISMATCH,
            }
            for issue in validation.issues
        ):
            raise StaleProofError(f"stage receipt is stale proof: {codes}")
        raise StaleStageReceiptError(f"stage translation receipt is stale: {codes}")
    return receipt


def replay_stage_receipt(
    receipt: StageTranslationReceipt,
    expectation: StageReceiptExpectation,
) -> StageReplayResult:
    """Replay a stage by re-checking its pinned manifest against current inputs."""

    if not isinstance(receipt, StageTranslationReceipt):
        raise StageReceiptError("receipt must be a StageTranslationReceipt")
    validation = validate_stage_receipt(receipt, expectation)
    issues = list(validation.issues)
    if receipt.validation.status is StageValidationStatus.REPLAY_FAILED:
        issues.append(
            StageReceiptIssue(
                StageReceiptIssueCode.REPLAY_MISMATCH,
                "receipt validation status is replay_failed",
            )
        )
    if (
        expectation.replay is None
        and (
            receipt.replay.input_identity != expectation.input.content_identity
            or receipt.replay.output_identity != expectation.output.content_identity
            or receipt.replay.compiler.binding_id != expectation.compiler.binding_id
        )
    ):
        issues.append(
            StageReceiptIssue(
                StageReceiptIssueCode.REPLAY_MISMATCH,
                "replay manifest does not match current compiler or identities",
            )
        )
    # Deduplicate while preserving order.
    unique: list[StageReceiptIssue] = []
    seen: set[tuple[str, str]] = set()
    for issue in issues:
        key = (issue.code.value, issue.detail)
        if key in seen:
            continue
        seen.add(key)
        unique.append(issue)
    reproduced = not unique
    return StageReplayResult(
        receipt_id=receipt.receipt_id,
        reproduced=reproduced,
        issues=tuple(unique),
        effective_authority_ceiling=(
            receipt.authority_ceiling if reproduced else EvidenceAuthority.NONE
        ),
    )


def require_reproduced_stage_receipt(
    receipt: StageTranslationReceipt,
    expectation: StageReceiptExpectation,
) -> StageTranslationReceipt:
    """Return *receipt* only when independent replay reproduces it."""

    result = replay_stage_receipt(receipt, expectation)
    if not result.reproduced:
        codes = ", ".join(issue.code.value for issue in result.issues)
        raise StageReplayError(f"stage receipt replay failed: {codes}")
    return receipt


def reconstruct_stage_receipt(
    value: Mapping[str, Any] | StageTranslationReceipt,
) -> StageTranslationReceipt:
    """Rebuild a receipt from its canonical payload and re-bind its identity."""

    if isinstance(value, StageTranslationReceipt):
        rebuilt = StageTranslationReceipt.from_dict(value.to_dict())
    else:
        rebuilt = StageTranslationReceipt.from_dict(value)
    expected_id = rebuilt.identity.cid
    if rebuilt.receipt_id != expected_id:
        raise StageReceiptError("reconstructed receipt identity does not match receipt_id")
    return rebuilt


def reconstruct_pipeline_receipt(
    value: Mapping[str, Any] | CompilationPipelineReceipt,
) -> CompilationPipelineReceipt:
    """Rebuild a pipeline receipt and every nested stage receipt."""

    if isinstance(value, CompilationPipelineReceipt):
        payload = value.to_dict()
    else:
        payload = dict(_mapping(value, "compilation pipeline receipt"))
    stages = tuple(
        reconstruct_stage_receipt(item) for item in payload.get("stages", ())
    )
    rebuilt_payload = dict(payload)
    rebuilt_payload["stages"] = [item.to_dict() for item in stages]
    rebuilt = CompilationPipelineReceipt.from_dict(rebuilt_payload)
    if rebuilt.receipt_id != rebuilt.identity.cid:
        raise StageReceiptError("reconstructed pipeline identity does not match receipt_id")
    return rebuilt


def compose_pipeline_receipts(
    stages: Sequence[StageTranslationReceipt],
    *,
    pipeline_id: str = "pipeline:formalization",
) -> CompilationPipelineReceipt:
    """Compose adjacent stage receipts under weakest-link authority."""

    receipts = tuple(stages)
    if not receipts:
        raise StageReceiptError("pipeline composition requires at least one stage receipt")
    authority = receipts[0].authority_ceiling
    evidence = receipts[0].evidence_class
    for receipt in receipts[1:]:
        authority = _weaker_authority(authority, receipt.authority_ceiling)
        evidence = _weaker_evidence_class(evidence, receipt.evidence_class)
    return CompilationPipelineReceipt(
        pipeline_id=pipeline_id,
        stages=receipts,
        source_identity=receipts[0].input.content_identity,
        backend_identity=receipts[-1].output.content_identity,
        authority_ceiling=authority,
        evidence_class=evidence,
    )


def effective_downstream_authority(
    upstream: Sequence[StageTranslationReceipt] | StageTranslationReceipt,
    *,
    proposed: EvidenceAuthority | str = EvidenceAuthority.AUTHORITATIVE,
) -> EvidenceAuthority:
    """Return the strongest authority a later stage may still claim."""

    receipts = (upstream,) if isinstance(upstream, StageTranslationReceipt) else tuple(upstream)
    ceiling = _enum(proposed, EvidenceAuthority, "proposed")
    for receipt in receipts:
        ceiling = _weaker_authority(
            ceiling,
            authority_capped_by_losses(
                receipt.losses,
                preservation=receipt.preservation_claim,
                evidence_class=receipt.evidence_class,
                declared=receipt.authority_ceiling,
            ),
        )
    return ceiling


__all__ = [
    "COMPILATION_PIPELINE_RECEIPT_INTERFACE",
    "CompilationPipelineReceipt",
    "CompilationStage",
    "EvidenceClass",
    "MissingStageReceiptError",
    "PIPELINE_RECEIPT_INTERFACE",
    "REQUIRED_STAGE_BINDINGS",
    "STAGE_ORDER",
    "STAGE_TRANSLATION_RECEIPT_INTERFACE",
    "STAGE_TRANSLATION_RECEIPT_SCHEMA_VERSION",
    "StageArtifactRef",
    "StageCounterexample",
    "StageMapDisposition",
    "StageReceiptError",
    "StageReceiptExpectation",
    "StageReceiptIssue",
    "StageReceiptIssueCode",
    "StageReceiptValidation",
    "StageReplayError",
    "StageReplayManifest",
    "StageReplayResult",
    "StageSourceMap",
    "StageSourceMapEntry",
    "StageTranslationReceipt",
    "StageValidationRecord",
    "StageValidationStatus",
    "StaleProofError",
    "StaleStageReceiptError",
    "SupportedSubset",
    "authority_capped_by_losses",
    "compose_pipeline_receipts",
    "effective_downstream_authority",
    "emit_stage_receipt",
    "infer_preservation_claim",
    "maximum_authority_for_evidence_class",
    "reconstruct_pipeline_receipt",
    "reconstruct_stage_receipt",
    "replay_stage_receipt",
    "require_current_stage_receipt",
    "require_reproduced_stage_receipt",
    "stage_index",
    "stage_successor",
    "stages_are_adjacent",
    "validate_stage_receipt",
]
