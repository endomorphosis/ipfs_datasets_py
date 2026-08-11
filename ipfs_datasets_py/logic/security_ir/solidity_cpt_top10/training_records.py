"""Partitioned formal-learning record streams for Solidity CPT Top-10.

Four streams remain non-interchangeable:

1. ``cpt_tokens`` — license-admitted raw continued-pretraining tokens
2. ``instruction`` — source-to-Security-IR / source-to-obligation targets
3. ``proof_attempt`` — formulas and proof-attempt labels that bind exact
   executed prover receipts
4. ``evaluation_only`` — held-out, adversarial, mutated, and control cases

Corpus quality is never a safety label.  Unlabeled rows remain unlabeled.
Solver results, traces, model scores, and evaluation labels do not leak into
declaration features.  A theorem / proof label exists only when a validated
receipt from an actually executed supported lowering is present.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Final

from ...ir_core.identity import canonical_identity
from ...ir_core.provenance import (
    ProvenanceValidationError,
    freeze_json_mapping,
    thaw_json,
)
from .adapter import CandidateAuthority
from .formalize import SolidityFormalizationRecord


TRAINING_RECORD_SCHEMA_VERSION: Final = "solidity-cpt-training-record/v1"
TRAINING_BUNDLE_SCHEMA_VERSION: Final = "solidity-cpt-training-bundle/v1"
TRAINING_RECORD_IDENTITY_DOMAIN: Final = (
    "solidity-cpt-security-ir/training-record"
)
TRAINING_BUNDLE_IDENTITY_DOMAIN: Final = (
    "solidity-cpt-security-ir/training-bundle"
)

_RESULT_FEATURE_KEYS: Final = frozenset(
    {
        "counterexample",
        "disproof_vectors",
        "model_score",
        "model_scores",
        "runtime_trace",
        "runtime_traces",
        "solver_result",
        "solver_results",
        "solver_verdict",
        "trace",
    }
)
_SAFETY_LABEL_KEYS: Final = frozenset(
    {
        "is_safe",
        "is_secure",
        "safety_label",
        "security_label",
        "vulnerability_label",
    }
)


class TrainingRecordError(ValueError):
    """Raised when a training record or bundle violates the stream contract."""


class TrainingStreamKind(str, Enum):
    """Closed vocabulary of non-interchangeable learning streams."""

    CPT_TOKENS = "cpt_tokens"
    INSTRUCTION = "instruction"
    PROOF_ATTEMPT = "proof_attempt"
    EVALUATION_ONLY = "evaluation_only"


class LabelStatus(str, Enum):
    """Whether a target is labeled, unlabeled, or proof-backed."""

    UNLABELED = "unlabeled"
    INSTRUCTION_TARGET = "instruction_target"
    PROOF_BACKED = "proof_backed"
    EVALUATION_CONTROL = "evaluation_control"


def _text(value: Any, name: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise TrainingRecordError(f"{name} must be a string")
    if not allow_empty and not value.strip():
        raise TrainingRecordError(f"{name} must be a non-empty string")
    if value != value.strip():
        raise TrainingRecordError(
            f"{name} must not have surrounding whitespace"
        )
    if "\x00" in value:
        raise TrainingRecordError(f"{name} must not contain NUL")
    return value


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TrainingRecordError(f"{name} must be a mapping")
    return value


def _freeze(value: Mapping[str, Any] | None, name: str) -> Mapping[str, Any]:
    try:
        return freeze_json_mapping(value or {})
    except ProvenanceValidationError as exc:
        raise TrainingRecordError(f"{name}: {exc}") from exc


def _contains_keys(value: Any, keys: frozenset[str]) -> bool:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if str(key).casefold() in keys and item not in (False, None, ""):
                return True
            if _contains_keys(item, keys):
                return True
    elif isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        return any(_contains_keys(item, keys) for item in value)
    return False


@dataclass(frozen=True, slots=True)
class ValidatedProofReceipt:
    """Receipt proving a supported lowering was actually executed.

    Without this receipt a proof-attempt stream cannot carry a proof label.
    """

    receipt_id: str
    backend_id: str
    obligation_id: str
    lowering_id: str
    executed: bool
    supported: bool
    receipt_digest: str
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "receipt_id", _text(self.receipt_id, "receipt_id")
        )
        object.__setattr__(
            self, "backend_id", _text(self.backend_id, "backend_id")
        )
        object.__setattr__(
            self, "obligation_id", _text(self.obligation_id, "obligation_id")
        )
        object.__setattr__(
            self, "lowering_id", _text(self.lowering_id, "lowering_id")
        )
        if self.executed is not True:
            raise TrainingRecordError(
                "proof receipt requires executed=True from an actual run"
            )
        if self.supported is not True:
            raise TrainingRecordError(
                "proof receipt requires supported=True lowering"
            )
        object.__setattr__(
            self, "receipt_digest", _text(self.receipt_digest, "receipt_digest")
        )
        object.__setattr__(self, "metadata", _freeze(self.metadata, "metadata"))
        if _contains_keys(thaw_json(self.metadata), _SAFETY_LABEL_KEYS):
            raise TrainingRecordError(
                "proof receipt metadata cannot carry safety labels"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "backend_id": self.backend_id,
            "executed": True,
            "lowering_id": self.lowering_id,
            "metadata": thaw_json(self.metadata),
            "obligation_id": self.obligation_id,
            "receipt_digest": self.receipt_digest,
            "receipt_id": self.receipt_id,
            "supported": True,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ValidatedProofReceipt":
        value = _mapping(value, "proof receipt")
        return cls(
            receipt_id=value.get("receipt_id", ""),
            backend_id=value.get("backend_id", ""),
            obligation_id=value.get("obligation_id", ""),
            lowering_id=value.get("lowering_id", ""),
            executed=value.get("executed", False),
            supported=value.get("supported", False),
            receipt_digest=value.get("receipt_digest", ""),
            metadata=value.get("metadata", {}),
        )


@dataclass(frozen=True, slots=True)
class FormalLearningRecord:
    """One content-addressed record belonging to exactly one stream."""

    stream: TrainingStreamKind
    sample_id: str
    features: Mapping[str, Any]
    target: Mapping[str, Any] | None
    label_status: LabelStatus
    graph_cid: str
    source_cids: tuple[str, ...]
    config_cid: str
    partition_cid: str
    partition_name: str = ""
    candidate_authority: str = CandidateAuthority.CANDIDATE.value
    semantic_prerequisites: tuple[str, ...] = ()
    unsupported_frontiers: tuple[str, ...] = ()
    source_spans: tuple[Mapping[str, Any], ...] = ()
    logic_family: str = ""
    quality_score: float | None = None
    quality_is_safety_label: bool = False
    proof_receipt: ValidatedProofReceipt | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = TRAINING_RECORD_SCHEMA_VERSION
    record_id: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.stream, TrainingStreamKind):
            try:
                object.__setattr__(
                    self, "stream", TrainingStreamKind(self.stream)
                )
            except (TypeError, ValueError) as exc:
                raise TrainingRecordError(
                    f"unsupported training stream: {self.stream!r}"
                ) from exc
        if not isinstance(self.label_status, LabelStatus):
            try:
                object.__setattr__(
                    self, "label_status", LabelStatus(self.label_status)
                )
            except (TypeError, ValueError) as exc:
                raise TrainingRecordError(
                    f"unsupported label status: {self.label_status!r}"
                ) from exc
        object.__setattr__(self, "sample_id", _text(self.sample_id, "sample_id"))
        object.__setattr__(
            self, "features", _freeze(_mapping(self.features, "features"), "features")
        )
        if self.target is None:
            object.__setattr__(self, "target", None)
        else:
            object.__setattr__(
                self,
                "target",
                _freeze(_mapping(self.target, "target"), "target"),
            )
        object.__setattr__(self, "graph_cid", _text(self.graph_cid, "graph_cid"))
        object.__setattr__(
            self,
            "source_cids",
            tuple(_text(item, "source_cid") for item in self.source_cids),
        )
        object.__setattr__(self, "config_cid", _text(self.config_cid, "config_cid"))
        object.__setattr__(
            self,
            "partition_cid",
            _text(self.partition_cid, "partition_cid", allow_empty=True),
        )
        object.__setattr__(
            self,
            "partition_name",
            _text(self.partition_name, "partition_name", allow_empty=True),
        )
        object.__setattr__(
            self,
            "candidate_authority",
            _text(self.candidate_authority, "candidate_authority"),
        )
        object.__setattr__(
            self,
            "semantic_prerequisites",
            tuple(
                _text(item, "semantic_prerequisite")
                for item in self.semantic_prerequisites
            ),
        )
        object.__setattr__(
            self,
            "unsupported_frontiers",
            tuple(
                _text(item, "unsupported_frontier")
                for item in self.unsupported_frontiers
            ),
        )
        object.__setattr__(
            self,
            "source_spans",
            tuple(
                MappingProxyType(dict(_mapping(item, "source_span")))
                for item in self.source_spans
            ),
        )
        object.__setattr__(
            self,
            "logic_family",
            _text(self.logic_family, "logic_family", allow_empty=True),
        )
        if self.quality_is_safety_label is not False:
            raise TrainingRecordError(
                "quality must never become a safety label"
            )
        if self.quality_score is not None:
            if (
                isinstance(self.quality_score, bool)
                or not isinstance(self.quality_score, (int, float))
                or not 0.0 <= float(self.quality_score) <= 1.0
            ):
                raise TrainingRecordError(
                    "quality_score must be in [0, 1] when present"
                )
            object.__setattr__(self, "quality_score", float(self.quality_score))
        if self.proof_receipt is not None and not isinstance(
            self.proof_receipt, ValidatedProofReceipt
        ):
            object.__setattr__(
                self,
                "proof_receipt",
                ValidatedProofReceipt.from_dict(
                    _mapping(self.proof_receipt, "proof receipt")
                ),
            )
        object.__setattr__(self, "metadata", _freeze(self.metadata, "metadata"))
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )
        if self.schema_version != TRAINING_RECORD_SCHEMA_VERSION:
            raise TrainingRecordError("unsupported training record schema")

        features = thaw_json(self.features)
        target = None if self.target is None else thaw_json(self.target)
        metadata = thaw_json(self.metadata)

        # Declaration features must not absorb result authority.
        if _contains_keys(features, _RESULT_FEATURE_KEYS):
            raise TrainingRecordError(
                "features must not include solver results, traces, or model scores"
            )
        if _contains_keys(features, _SAFETY_LABEL_KEYS):
            raise TrainingRecordError(
                "features must not include safety or vulnerability labels"
            )
        if _contains_keys(features.get("declaration", {}), _RESULT_FEATURE_KEYS):
            raise TrainingRecordError(
                "declaration features must exclude evaluation and solver labels"
            )

        self._validate_stream_contract(features, target, metadata)

        computed = self.identity.cid
        if self.record_id and self.record_id != computed:
            raise TrainingRecordError(
                "record_id does not match rehashed training record"
            )
        object.__setattr__(self, "record_id", computed)

    def _validate_stream_contract(
        self,
        features: Mapping[str, Any],
        target: Mapping[str, Any] | None,
        metadata: Mapping[str, Any],
    ) -> None:
        stream = self.stream
        if stream is TrainingStreamKind.CPT_TOKENS:
            if self.label_status is not LabelStatus.UNLABELED:
                raise TrainingRecordError(
                    "cpt_tokens records remain unlabeled continued-pretraining data"
                )
            if target is not None:
                raise TrainingRecordError(
                    "cpt_tokens stream cannot carry instruction or proof targets"
                )
            if self.proof_receipt is not None:
                raise TrainingRecordError(
                    "cpt_tokens stream cannot bind proof receipts"
                )
            if "tokens" not in features and "token_digest" not in features:
                raise TrainingRecordError(
                    "cpt_tokens features require tokens or token_digest"
                )
            if features.get("stream_kind", stream.value) != stream.value:
                raise TrainingRecordError("cpt_tokens stream_kind mismatch")
        elif stream is TrainingStreamKind.INSTRUCTION:
            if self.label_status not in {
                LabelStatus.INSTRUCTION_TARGET,
                LabelStatus.UNLABELED,
            }:
                raise TrainingRecordError(
                    "instruction stream label_status must be instruction_target or unlabeled"
                )
            if self.label_status is LabelStatus.UNLABELED and target is not None:
                raise TrainingRecordError(
                    "unlabeled instruction records must not invent targets"
                )
            if (
                self.label_status is LabelStatus.INSTRUCTION_TARGET
                and target is None
            ):
                raise TrainingRecordError(
                    "instruction_target records require a target payload"
                )
            if self.proof_receipt is not None:
                raise TrainingRecordError(
                    "instruction stream cannot bind proof receipts "
                    "(use proof_attempt)"
                )
            if target is not None and target.get("is_proof") is True:
                raise TrainingRecordError(
                    "instruction targets are not proof labels"
                )
        elif stream is TrainingStreamKind.PROOF_ATTEMPT:
            if self.label_status is LabelStatus.PROOF_BACKED:
                if self.proof_receipt is None:
                    raise TrainingRecordError(
                        "proof_backed labels require a validated execution receipt"
                    )
                if target is None:
                    raise TrainingRecordError(
                        "proof_backed records require a target bound to the receipt"
                    )
            elif self.label_status is LabelStatus.UNLABELED:
                if self.proof_receipt is not None:
                    raise TrainingRecordError(
                        "unlabeled proof_attempt records must not claim receipts"
                    )
            else:
                raise TrainingRecordError(
                    "proof_attempt label_status must be proof_backed or unlabeled"
                )
            if self.proof_receipt is not None:
                if not self.proof_receipt.executed or not self.proof_receipt.supported:
                    raise TrainingRecordError(
                        "proof receipt must be executed and supported"
                    )
        elif stream is TrainingStreamKind.EVALUATION_ONLY:
            if self.label_status not in {
                LabelStatus.EVALUATION_CONTROL,
                LabelStatus.UNLABELED,
            }:
                raise TrainingRecordError(
                    "evaluation_only label_status must be evaluation_control or unlabeled"
                )
            if features.get("evaluation_only") is not True and metadata.get(
                "evaluation_only"
            ) is not True:
                # Allow either location; require explicit marking.
                raise TrainingRecordError(
                    "evaluation_only records must set evaluation_only=True"
                )
            if self.proof_receipt is not None and self.label_status is not LabelStatus.EVALUATION_CONTROL:
                raise TrainingRecordError(
                    "evaluation_only unlabeled rows cannot bind proof receipts"
                )
        else:  # pragma: no cover - enum exhaustiveness
            raise TrainingRecordError(f"unknown stream {stream!r}")

        # Cross-stream contamination checks.
        declared_stream = features.get("stream_kind") or metadata.get("stream_kind")
        if declared_stream and declared_stream != stream.value:
            raise TrainingRecordError(
                "stream_kind marker must match the record stream"
            )
        if stream is not TrainingStreamKind.EVALUATION_ONLY and (
            features.get("evaluation_only") is True
            or metadata.get("evaluation_only") is True
        ):
            raise TrainingRecordError(
                "evaluation_only marker is reserved for the evaluation stream"
            )
        if stream is not TrainingStreamKind.CPT_TOKENS and features.get(
            "cpt_token_stream"
        ) is True:
            raise TrainingRecordError(
                "cpt_token_stream marker is reserved for cpt_tokens"
            )

    @property
    def identity(self):
        return canonical_identity(
            self.deterministic_dict(),
            domain=TRAINING_RECORD_IDENTITY_DOMAIN,
            schema_version=self.schema_version,
        )

    @property
    def cid(self) -> str:
        return self.record_id

    def deterministic_dict(self) -> dict[str, Any]:
        return {
            "candidate_authority": self.candidate_authority,
            "config_cid": self.config_cid,
            "features": thaw_json(self.features),
            "graph_cid": self.graph_cid,
            "label_status": self.label_status.value,
            "logic_family": self.logic_family,
            "metadata": thaw_json(self.metadata),
            "partition_cid": self.partition_cid,
            "partition_name": self.partition_name,
            "proof_receipt": (
                None
                if self.proof_receipt is None
                else self.proof_receipt.to_dict()
            ),
            "quality_is_safety_label": False,
            "quality_score": self.quality_score,
            "sample_id": self.sample_id,
            "schema_version": self.schema_version,
            "semantic_prerequisites": list(self.semantic_prerequisites),
            "source_cids": list(self.source_cids),
            "source_spans": [dict(item) for item in self.source_spans],
            "stream": self.stream.value,
            "target": None if self.target is None else thaw_json(self.target),
            "unsupported_frontiers": list(self.unsupported_frontiers),
        }

    def to_dict(self) -> dict[str, Any]:
        return {"record_id": self.record_id, **self.deterministic_dict()}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "FormalLearningRecord":
        value = _mapping(value, "training record")
        receipt = value.get("proof_receipt")
        return cls(
            stream=value.get("stream", ""),
            sample_id=value.get("sample_id", ""),
            features=value.get("features", {}),
            target=value.get("target"),
            label_status=value.get("label_status", LabelStatus.UNLABELED.value),
            graph_cid=value.get("graph_cid", ""),
            source_cids=tuple(value.get("source_cids", ())),
            config_cid=value.get("config_cid", ""),
            partition_cid=value.get("partition_cid", ""),
            partition_name=value.get("partition_name", ""),
            candidate_authority=value.get(
                "candidate_authority", CandidateAuthority.CANDIDATE.value
            ),
            semantic_prerequisites=tuple(
                value.get("semantic_prerequisites", ())
            ),
            unsupported_frontiers=tuple(
                value.get("unsupported_frontiers", ())
            ),
            source_spans=tuple(value.get("source_spans", ())),
            logic_family=value.get("logic_family", ""),
            quality_score=value.get("quality_score"),
            quality_is_safety_label=value.get("quality_is_safety_label", False),
            proof_receipt=(
                None
                if receipt is None
                else ValidatedProofReceipt.from_dict(_mapping(receipt, "proof receipt"))
            ),
            metadata=value.get("metadata", {}),
            schema_version=value.get(
                "schema_version", TRAINING_RECORD_SCHEMA_VERSION
            ),
            record_id=value.get("record_id", ""),
        )


@dataclass(frozen=True, slots=True)
class FormalLearningBundle:
    """Stream-partitioned learning records with hard separation invariants."""

    cpt_tokens: tuple[FormalLearningRecord, ...] = ()
    instruction: tuple[FormalLearningRecord, ...] = ()
    proof_attempt: tuple[FormalLearningRecord, ...] = ()
    evaluation_only: tuple[FormalLearningRecord, ...] = ()
    graph_cid: str = ""
    source_cids: tuple[str, ...] = ()
    config_cid: str = ""
    partition_cid: str = ""
    schema_version: str = TRAINING_BUNDLE_SCHEMA_VERSION
    bundle_id: str = ""

    def __post_init__(self) -> None:
        for name, expected in (
            ("cpt_tokens", TrainingStreamKind.CPT_TOKENS),
            ("instruction", TrainingStreamKind.INSTRUCTION),
            ("proof_attempt", TrainingStreamKind.PROOF_ATTEMPT),
            ("evaluation_only", TrainingStreamKind.EVALUATION_ONLY),
        ):
            records = getattr(self, name)
            if isinstance(records, (str, bytes, bytearray)) or not isinstance(
                records, Sequence
            ):
                raise TrainingRecordError(f"{name} must be a sequence")
            normalized: list[FormalLearningRecord] = []
            for item in records:
                if isinstance(item, FormalLearningRecord):
                    record = item
                elif isinstance(item, Mapping):
                    record = FormalLearningRecord.from_dict(item)
                else:
                    raise TrainingRecordError(
                        f"{name} must contain FormalLearningRecord values"
                    )
                if record.stream is not expected:
                    raise TrainingRecordError(
                        f"{name} stream must contain only {expected.value} records"
                    )
                normalized.append(record)
            object.__setattr__(self, name, tuple(normalized))

        object.__setattr__(
            self, "graph_cid", _text(self.graph_cid, "graph_cid", allow_empty=True)
        )
        object.__setattr__(
            self,
            "source_cids",
            tuple(_text(item, "source_cid") for item in self.source_cids),
        )
        object.__setattr__(
            self,
            "config_cid",
            _text(self.config_cid, "config_cid", allow_empty=True),
        )
        object.__setattr__(
            self,
            "partition_cid",
            _text(self.partition_cid, "partition_cid", allow_empty=True),
        )
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )
        if self.schema_version != TRAINING_BUNDLE_SCHEMA_VERSION:
            raise TrainingRecordError("unsupported training bundle schema")

        all_ids = [
            item.record_id
            for item in (
                *self.cpt_tokens,
                *self.instruction,
                *self.proof_attempt,
                *self.evaluation_only,
            )
        ]
        if len(all_ids) != len(set(all_ids)):
            raise TrainingRecordError("training bundle contains duplicate records")

        # Streams must remain distinct: no shared sample_id across streams.
        by_stream: dict[str, set[str]] = {
            TrainingStreamKind.CPT_TOKENS.value: {
                item.sample_id for item in self.cpt_tokens
            },
            TrainingStreamKind.INSTRUCTION.value: {
                item.sample_id for item in self.instruction
            },
            TrainingStreamKind.PROOF_ATTEMPT.value: {
                item.sample_id for item in self.proof_attempt
            },
            TrainingStreamKind.EVALUATION_ONLY.value: {
                item.sample_id for item in self.evaluation_only
            },
        }
        streams = list(by_stream)
        for index, left in enumerate(streams):
            for right in streams[index + 1 :]:
                overlap = sorted(by_stream[left] & by_stream[right])
                if overlap:
                    raise TrainingRecordError(
                        "sample_id values must not cross streams; "
                        f"overlap between {left} and {right}: {overlap[:5]}"
                    )

        computed = self.identity.cid
        if self.bundle_id and self.bundle_id != computed:
            raise TrainingRecordError(
                "bundle_id does not match rehashed training bundle"
            )
        object.__setattr__(self, "bundle_id", computed)

    @property
    def identity(self):
        return canonical_identity(
            self.deterministic_dict(),
            domain=TRAINING_BUNDLE_IDENTITY_DOMAIN,
            schema_version=self.schema_version,
        )

    @property
    def cid(self) -> str:
        return self.bundle_id

    def deterministic_dict(self) -> dict[str, Any]:
        return {
            "config_cid": self.config_cid,
            "cpt_tokens": [item.to_dict() for item in self.cpt_tokens],
            "evaluation_only": [item.to_dict() for item in self.evaluation_only],
            "graph_cid": self.graph_cid,
            "instruction": [item.to_dict() for item in self.instruction],
            "partition_cid": self.partition_cid,
            "proof_attempt": [item.to_dict() for item in self.proof_attempt],
            "schema_version": self.schema_version,
            "source_cids": list(self.source_cids),
        }

    def to_dict(self) -> dict[str, Any]:
        return {"bundle_id": self.bundle_id, **self.deterministic_dict()}

    def records(self) -> tuple[FormalLearningRecord, ...]:
        return (
            *self.cpt_tokens,
            *self.instruction,
            *self.proof_attempt,
            *self.evaluation_only,
        )


def build_instruction_record_from_formalization(
    formalization: SolidityFormalizationRecord,
    *,
    sample_id: str,
    partition_name: str = "train",
    include_obligation_target: bool = True,
) -> FormalLearningRecord:
    """Build an instruction-stream record from a formalization result.

    Features stay declaration-oriented.  Solver results and evaluation labels
    are never copied into features.  Obligation targets remain properties to
    check, not proof that they hold.
    """

    if not isinstance(formalization, SolidityFormalizationRecord):
        raise TrainingRecordError(
            "formalization must be a SolidityFormalizationRecord"
        )
    features = {
        "stream_kind": TrainingStreamKind.INSTRUCTION.value,
        "declaration_id": formalization.declaration_id,
        "declaration_digest": formalization.declaration_digest,
        "formulas": [item.to_dict() for item in formalization.formulas],
        "assumptions": [item.to_dict() for item in formalization.assumptions],
        # Intentionally exclude obligations from features when they are targets.
        "candidate_authority": formalization.candidate_authority.value,
        "logic_family": formalization.logic_family,
        "semantic_prerequisites": list(formalization.semantic_prerequisites),
        "unsupported_frontiers": list(formalization.unsupported_frontiers),
        "source_spans": [dict(item) for item in formalization.source_spans],
    }
    if _contains_keys(features, _RESULT_FEATURE_KEYS):
        raise TrainingRecordError(
            "instruction features must not include result authority"
        )
    target: dict[str, Any] | None = None
    label_status = LabelStatus.UNLABELED
    if include_obligation_target and formalization.obligations:
        target = {
            "kind": "proof_obligation_targets",
            "is_proof": False,
            "obligation_is_not_proof": True,
            "obligations": [item.to_dict() for item in formalization.obligations],
        }
        label_status = LabelStatus.INSTRUCTION_TARGET
    return FormalLearningRecord(
        stream=TrainingStreamKind.INSTRUCTION,
        sample_id=sample_id,
        features=features,
        target=target,
        label_status=label_status,
        graph_cid=formalization.graph_cid,
        source_cids=formalization.source_cids,
        config_cid=formalization.config_cid,
        partition_cid=formalization.partition_cid,
        partition_name=partition_name,
        candidate_authority=formalization.candidate_authority.value,
        semantic_prerequisites=formalization.semantic_prerequisites,
        unsupported_frontiers=formalization.unsupported_frontiers,
        source_spans=formalization.source_spans,
        logic_family=formalization.logic_family,
        quality_score=formalization.quality_score,
        quality_is_safety_label=False,
        metadata={
            "stream_kind": TrainingStreamKind.INSTRUCTION.value,
            "formalization_record_id": formalization.record_id,
        },
    )


def build_cpt_token_record(
    *,
    sample_id: str,
    token_digest: str,
    graph_cid: str,
    source_cids: Sequence[str],
    config_cid: str,
    partition_cid: str = "",
    partition_name: str = "train",
    token_count: int | None = None,
    quality_score: float | None = None,
) -> FormalLearningRecord:
    """Build a license-admitted continued-pretraining token record."""

    features: dict[str, Any] = {
        "stream_kind": TrainingStreamKind.CPT_TOKENS.value,
        "cpt_token_stream": True,
        "token_digest": _text(token_digest, "token_digest"),
    }
    if token_count is not None:
        if not isinstance(token_count, int) or isinstance(token_count, bool) or token_count < 0:
            raise TrainingRecordError("token_count must be a non-negative int")
        features["token_count"] = token_count
    return FormalLearningRecord(
        stream=TrainingStreamKind.CPT_TOKENS,
        sample_id=sample_id,
        features=features,
        target=None,
        label_status=LabelStatus.UNLABELED,
        graph_cid=graph_cid,
        source_cids=tuple(source_cids),
        config_cid=config_cid,
        partition_cid=partition_cid,
        partition_name=partition_name,
        candidate_authority=CandidateAuthority.CANDIDATE.value,
        quality_score=quality_score,
        quality_is_safety_label=False,
        metadata={"stream_kind": TrainingStreamKind.CPT_TOKENS.value},
    )


def build_proof_attempt_record(
    formalization: SolidityFormalizationRecord,
    *,
    sample_id: str,
    proof_receipt: ValidatedProofReceipt | None = None,
    partition_name: str = "train",
) -> FormalLearningRecord:
    """Build a proof-attempt record; proof labels require a validated receipt."""

    if not isinstance(formalization, SolidityFormalizationRecord):
        raise TrainingRecordError(
            "formalization must be a SolidityFormalizationRecord"
        )
    features = {
        "stream_kind": TrainingStreamKind.PROOF_ATTEMPT.value,
        "declaration_id": formalization.declaration_id,
        "declaration_digest": formalization.declaration_digest,
        "formulas": [item.to_dict() for item in formalization.formulas],
        "obligation_ids": [
            item.obligation_id for item in formalization.obligations
        ],
        # No solver verdicts in features.
    }
    if proof_receipt is None:
        return FormalLearningRecord(
            stream=TrainingStreamKind.PROOF_ATTEMPT,
            sample_id=sample_id,
            features=features,
            target=None,
            label_status=LabelStatus.UNLABELED,
            graph_cid=formalization.graph_cid,
            source_cids=formalization.source_cids,
            config_cid=formalization.config_cid,
            partition_cid=formalization.partition_cid,
            partition_name=partition_name,
            candidate_authority=formalization.candidate_authority.value,
            semantic_prerequisites=formalization.semantic_prerequisites,
            unsupported_frontiers=formalization.unsupported_frontiers,
            source_spans=formalization.source_spans,
            logic_family=formalization.logic_family,
            quality_score=formalization.quality_score,
            quality_is_safety_label=False,
            proof_receipt=None,
            metadata={"stream_kind": TrainingStreamKind.PROOF_ATTEMPT.value},
        )
    target = {
        "kind": "proof_attempt_label",
        "obligation_id": proof_receipt.obligation_id,
        "receipt_id": proof_receipt.receipt_id,
        "receipt_digest": proof_receipt.receipt_digest,
        "is_proof": True,
        "requires_validated_receipt": True,
    }
    return FormalLearningRecord(
        stream=TrainingStreamKind.PROOF_ATTEMPT,
        sample_id=sample_id,
        features=features,
        target=target,
        label_status=LabelStatus.PROOF_BACKED,
        graph_cid=formalization.graph_cid,
        source_cids=formalization.source_cids,
        config_cid=formalization.config_cid,
        partition_cid=formalization.partition_cid,
        partition_name=partition_name,
        candidate_authority=formalization.candidate_authority.value,
        semantic_prerequisites=formalization.semantic_prerequisites,
        unsupported_frontiers=formalization.unsupported_frontiers,
        source_spans=formalization.source_spans,
        logic_family=formalization.logic_family,
        quality_score=formalization.quality_score,
        quality_is_safety_label=False,
        proof_receipt=proof_receipt,
        metadata={"stream_kind": TrainingStreamKind.PROOF_ATTEMPT.value},
    )


def build_evaluation_only_record(
    formalization: SolidityFormalizationRecord,
    *,
    sample_id: str,
    control_kind: str,
    partition_name: str = "held_out",
    evaluation_label: Mapping[str, Any] | None = None,
) -> FormalLearningRecord:
    """Build an evaluation-only control record.

    Evaluation labels stay in the target (or remain absent).  They never enter
    declaration features.
    """

    if not isinstance(formalization, SolidityFormalizationRecord):
        raise TrainingRecordError(
            "formalization must be a SolidityFormalizationRecord"
        )
    features = {
        "stream_kind": TrainingStreamKind.EVALUATION_ONLY.value,
        "evaluation_only": True,
        "control_kind": _text(control_kind, "control_kind"),
        "declaration_id": formalization.declaration_id,
        "declaration_digest": formalization.declaration_digest,
        "formulas": [item.to_dict() for item in formalization.formulas],
    }
    if _contains_keys(features, _RESULT_FEATURE_KEYS | frozenset({"evaluation_label"})):
        # evaluation_label is allowed only as target, not feature.
        raise TrainingRecordError(
            "evaluation features must not embed evaluation labels or solver results"
        )
    target = None
    label_status = LabelStatus.UNLABELED
    if evaluation_label is not None:
        target = {
            "kind": "evaluation_control_label",
            "evaluation_only": True,
            "label": dict(_mapping(evaluation_label, "evaluation_label")),
        }
        label_status = LabelStatus.EVALUATION_CONTROL
    return FormalLearningRecord(
        stream=TrainingStreamKind.EVALUATION_ONLY,
        sample_id=sample_id,
        features=features,
        target=target,
        label_status=label_status,
        graph_cid=formalization.graph_cid,
        source_cids=formalization.source_cids,
        config_cid=formalization.config_cid,
        partition_cid=formalization.partition_cid,
        partition_name=partition_name,
        candidate_authority=formalization.candidate_authority.value,
        semantic_prerequisites=formalization.semantic_prerequisites,
        unsupported_frontiers=formalization.unsupported_frontiers,
        source_spans=formalization.source_spans,
        logic_family=formalization.logic_family,
        quality_score=formalization.quality_score,
        quality_is_safety_label=False,
        metadata={
            "stream_kind": TrainingStreamKind.EVALUATION_ONLY.value,
            "evaluation_only": True,
        },
    )


def build_learning_bundle_from_formalization(
    formalization: SolidityFormalizationRecord,
    *,
    sample_prefix: str,
    token_digest: str | None = None,
    proof_receipt: ValidatedProofReceipt | None = None,
    evaluation_control_kind: str | None = None,
) -> FormalLearningBundle:
    """Assemble a four-stream bundle with distinct sample identities."""

    cpt: tuple[FormalLearningRecord, ...] = ()
    if token_digest is not None:
        cpt = (
            build_cpt_token_record(
                sample_id=f"{sample_prefix}:cpt",
                token_digest=token_digest,
                graph_cid=formalization.graph_cid,
                source_cids=formalization.source_cids,
                config_cid=formalization.config_cid,
                partition_cid=formalization.partition_cid,
                quality_score=formalization.quality_score,
            ),
        )
    instruction = (
        build_instruction_record_from_formalization(
            formalization, sample_id=f"{sample_prefix}:instruction"
        ),
    )
    proof = (
        build_proof_attempt_record(
            formalization,
            sample_id=f"{sample_prefix}:proof",
            proof_receipt=proof_receipt,
        ),
    )
    evaluation: tuple[FormalLearningRecord, ...] = ()
    if evaluation_control_kind is not None:
        evaluation = (
            build_evaluation_only_record(
                formalization,
                sample_id=f"{sample_prefix}:eval",
                control_kind=evaluation_control_kind,
            ),
        )
    return FormalLearningBundle(
        cpt_tokens=cpt,
        instruction=instruction,
        proof_attempt=proof,
        evaluation_only=evaluation,
        graph_cid=formalization.graph_cid,
        source_cids=formalization.source_cids,
        config_cid=formalization.config_cid,
        partition_cid=formalization.partition_cid,
    )


__all__ = [
    "FormalLearningBundle",
    "FormalLearningRecord",
    "LabelStatus",
    "TRAINING_BUNDLE_SCHEMA_VERSION",
    "TRAINING_RECORD_SCHEMA_VERSION",
    "TrainingRecordError",
    "TrainingStreamKind",
    "ValidatedProofReceipt",
    "build_cpt_token_record",
    "build_evaluation_only_record",
    "build_instruction_record_from_formalization",
    "build_learning_bundle_from_formalization",
    "build_proof_attempt_record",
]
