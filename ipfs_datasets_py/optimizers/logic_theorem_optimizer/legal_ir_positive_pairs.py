"""Deterministic miner for typed proof-aware ``IRPositivePair@1`` shards.

PGIR-040 admits only train-split, lineage-complete pairs whose equivalence
class is supported by explicit authority.  Weaker classes are never emitted
as ``exact``.  Logical and proof classes require independent verification.
Model-only proof labels, cross-split siblings, and duplicate endpoint pairs
are rejected.  Mining is deterministic: no model checkpoint is consulted.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Final

from ipfs_datasets_py.logic.formalization.training_contracts import (
    EvidenceStatus,
    IRCompilerTrace,
    IRDecompilerTrace,
    IRPositivePair,
    IRProofTrace,
    IRRoundTripTrace,
    IRTrainingExample,
    IRTranslationTrace,
    LabelAuthority,
    LabelEvidence,
    LineageBinding,
    LogicFamily,
    PreservationClass,
    ProofOutcome,
    RepresentationKind,
    SemanticRelationship,
    StatementAuthority,
    StatementBinding,
    TrainingContractValidationError,
    TraceStatus,
)
from ipfs_datasets_py.logic.formalization.training_shared import (
    IR_POSITIVE_PAIR_INTERFACE,
    IR_POSITIVE_PAIR_SCHEMA_VERSION,
    _RELATION_AUTHORITIES,
    _has_verified_relationship_evidence,
)
from ipfs_datasets_py.logic.ir_core.identity import canonical_identity
from ipfs_datasets_py.logic.ir_core.protocols import AuthorityKind
from ipfs_datasets_py.logic.ir_core.source_lineage import RightsDisposition


IR_POSITIVE_PAIR_SHARD_INTERFACE: Final = "IRPositivePairShard@1"
IR_POSITIVE_PAIR_SHARD_SCHEMA: Final = "ir-positive-pair-shard/v1"
IR_POSITIVE_PAIR_RECIPE_INTERFACE: Final = "IRPositivePairRecipe@1"
IR_POSITIVE_PAIR_RECIPE_SCHEMA: Final = "ir-positive-pair-recipe/v1"
IR_POSITIVE_PAIR_MANIFEST_INTERFACE: Final = "IRPositivePairManifest@1"
IR_POSITIVE_PAIR_MANIFEST_SCHEMA: Final = "ir-positive-pair-manifest/v1"
IR_POSITIVE_PAIR_INDEX_INTERFACE: Final = "IRPositiveEquivalenceIndex@1"
IR_POSITIVE_PAIR_MINER_VERSION: Final = "pgir-040-positive-miner-v1"
IR_POSITIVE_PAIR_TASK_ID: Final = "PGIR-040"

SEALED_CORPUS_MANIFEST_ID: Final = "corp:jdao-pinset-1"
SEALED_CORPUS_MANIFEST_CID: Final = (
    "bafkreiha35x7mcukzzb5x67hmykwsny5wipf5jb4do5gpsl24mxvix55n4"
)
SEALED_LINEAGE_GRAPH_ID: Final = "lin:jdao-pinset-1"
SEALED_LINEAGE_GRAPH_CID: Final = (
    "bafkreia5jirpcpummrddhczxebz554lkd7wrq4o5ynizjlgbczyzuwhakq"
)
SEALED_SPLIT_MANIFEST_ID: Final = "split:pgir-012"
SEALED_SPLIT_MANIFEST_DIGEST: Final = (
    "sha256:047b263b85067aa3dad6760f623c2855fbaf776d565ec9c273c49425fcc14eb4"
)
SEALED_SPLIT_ROOT_SHA256: Final = (
    "sha256:b522f15f2597ed4902f1af9b7f3aac5b855193d289369df70ccfda5ce8798f9d"
)
SEALED_CORPUS_ROOT_SHA256: Final = (
    "sha256:c54519f43b7950a04b79167e7b61be68d358b2441b8beb810c54b1b10ab2c9dd"
)
TRAIN_SPLIT_NAME: Final = "train"

POSITIVE_EQUIVALENCE_CLASSES: Final[tuple[SemanticRelationship, ...]] = (
    SemanticRelationship.EXACT,
    SemanticRelationship.ALPHA_EQUIVALENT,
    SemanticRelationship.CANONICAL_EQUIVALENT,
    SemanticRelationship.LOGICALLY_EQUIVALENT,
    SemanticRelationship.EQUISATISFIABLE,
    SemanticRelationship.PROOF_EQUIVALENT,
    SemanticRelationship.TRANSLATION_EQUIVALENT,
    SemanticRelationship.PARAPHRASE,
)

INDEPENDENT_VERIFICATION_CLASSES: Final[frozenset[SemanticRelationship]] = frozenset(
    {
        SemanticRelationship.LOGICALLY_EQUIVALENT,
        SemanticRelationship.EQUISATISFIABLE,
        SemanticRelationship.PROOF_EQUIVALENT,
    }
)

WEAKER_THAN_EXACT: Final[frozenset[SemanticRelationship]] = frozenset(
    {
        SemanticRelationship.EQUISATISFIABLE,
        SemanticRelationship.PARAPHRASE,
        SemanticRelationship.TRANSLATION_EQUIVALENT,
        SemanticRelationship.UNKNOWN,
    }
)

_CLASS_STRENGTH: Final[dict[SemanticRelationship, int]] = {
    SemanticRelationship.EXACT: 80,
    SemanticRelationship.ALPHA_EQUIVALENT: 70,
    SemanticRelationship.CANONICAL_EQUIVALENT: 60,
    SemanticRelationship.LOGICALLY_EQUIVALENT: 50,
    SemanticRelationship.PROOF_EQUIVALENT: 40,
    SemanticRelationship.TRANSLATION_EQUIVALENT: 30,
    SemanticRelationship.EQUISATISFIABLE: 20,
    SemanticRelationship.PARAPHRASE: 10,
    SemanticRelationship.UNKNOWN: 0,
}

INDEPENDENT_AUTHORITIES: Final[frozenset[LabelAuthority]] = frozenset(
    {
        LabelAuthority.INDEPENDENT_TRANSLATION_CHECKER,
        LabelAuthority.INDEPENDENT_SEMANTIC_CHECKER,
        LabelAuthority.INDEPENDENT_PROOF_CHECKER,
        LabelAuthority.INDEPENDENT_COUNTEREXAMPLE_CHECKER,
    }
)

MODEL_ONLY_AUTHORITIES: Final[frozenset[LabelAuthority]] = frozenset(
    {
        LabelAuthority.MODEL_OUTPUT,
        LabelAuthority.TOOL_CANDIDATE,
        LabelAuthority.UNKNOWN,
    }
)

CANDIDATE_STATEMENT_AUTHORITIES: Final[frozenset[StatementAuthority]] = frozenset(
    {
        StatementAuthority.UNKNOWN,
        StatementAuthority.MODEL_CANDIDATE,
    }
)

RECEIPT_RECONSTRUCTION: Final = "reconstruction"
RECEIPT_KERNEL: Final = "kernel"
RECEIPT_TRANSLATION: Final = "translation"
RECEIPT_SEMANTIC: Final = "semantic"
RECEIPT_HUMAN: Final = "human"

RECEIPT_KINDS: Final[tuple[str, ...]] = (
    RECEIPT_RECONSTRUCTION,
    RECEIPT_KERNEL,
    RECEIPT_TRANSLATION,
    RECEIPT_SEMANTIC,
    RECEIPT_HUMAN,
)

_DEFAULT_RECEIPT_KIND: Final[dict[SemanticRelationship, str]] = {
    SemanticRelationship.EXACT: RECEIPT_RECONSTRUCTION,
    SemanticRelationship.ALPHA_EQUIVALENT: RECEIPT_RECONSTRUCTION,
    SemanticRelationship.CANONICAL_EQUIVALENT: RECEIPT_RECONSTRUCTION,
    SemanticRelationship.LOGICALLY_EQUIVALENT: RECEIPT_SEMANTIC,
    SemanticRelationship.EQUISATISFIABLE: RECEIPT_SEMANTIC,
    SemanticRelationship.PROOF_EQUIVALENT: RECEIPT_KERNEL,
    SemanticRelationship.TRANSLATION_EQUIVALENT: RECEIPT_TRANSLATION,
    SemanticRelationship.PARAPHRASE: RECEIPT_HUMAN,
}

_DEFAULT_RESULT_AUTHORITY: Final[dict[LabelAuthority, AuthorityKind | None]] = {
    LabelAuthority.INDEPENDENT_PROOF_CHECKER: AuthorityKind.THEOREM_PROOF,
    LabelAuthority.INDEPENDENT_SEMANTIC_CHECKER: AuthorityKind.THEOREM_PROOF,
    LabelAuthority.INDEPENDENT_COUNTEREXAMPLE_CHECKER: AuthorityKind.SATISFIABILITY,
}

DEFAULT_POSITIVE_PAIR_DATA_DIR: Final = Path("data/ir_learning/pairs/positive")


class PositivePairMinerError(ValueError):
    """Raised when a candidate cannot become an ``IRPositivePair@1`` record."""


class PositivePairAdmissionError(PositivePairMinerError):
    """Raised when an explicit authority or lineage gate fails closed."""


class PositivePairShardConflictError(PositivePairMinerError):
    """Raised when a compare-and-swap shard write would clobber different bytes."""


class PositivePairRejection(str, Enum):
    """Closed vocabulary of miner rejection reasons."""

    CROSS_SPLIT_SIBLING = "cross_split_sibling"
    NON_TRAINING_SPLIT = "non_training_split"
    LINEAGE_GROUP_SPLIT = "lineage_group_split"
    INCOMPLETE_LINEAGE = "incomplete_lineage"
    RIGHTS_NOT_ADMITTED = "rights_not_admitted"
    CANDIDATE_STATEMENT_AUTHORITY = "candidate_statement_authority"
    MODEL_ONLY_PROOF_LABEL = "model_only_proof_label"
    MODEL_ONLY_EVIDENCE = "model_only_evidence"
    UNVERIFIED_EVIDENCE = "unverified_evidence"
    INDEPENDENT_VERIFICATION_REQUIRED = "independent_verification_required"
    WEAKER_CLASS_AS_EXACT = "weaker_class_as_exact"
    DUPLICATE_PAIR = "duplicate_pair"
    UNKNOWN_RELATIONSHIP = "unknown_relationship"
    ENDPOINTS_NOT_DISTINCT = "endpoints_not_distinct"
    AUTHORITY_NOT_ADMITTED_FOR_CLASS = "authority_not_admitted_for_class"
    UNRESOLVED_LOSS_AS_EXACT = "unresolved_loss_as_exact"
    SUPERSEDED_WEAKER_CLASS = "superseded_weaker_class"
    TRACE_NOT_SUCCEEDED = "trace_not_succeeded"


def _canonical_json(value: Any) -> str:
    return json.dumps(
        _json_ready(value),
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _json_ready(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _json_ready(item) for key, item in sorted(value.items())}
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray, str)):
        return [_json_ready(item) for item in value]
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return _json_ready(to_dict())
    return str(value)


def content_digest(value: Any) -> str:
    return f"sha256:{hashlib.sha256(_canonical_json(value).encode('utf-8')).hexdigest()}"


def content_cid(value: Any, *, domain: str, schema_version: str) -> str:
    return canonical_identity(
        _json_ready(value),
        domain=domain,
        schema_version=schema_version,
    ).cid


def _digest_for(*parts: str) -> str:
    payload = "\0".join(parts).encode("utf-8")
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def _short_id(digest: str, size: int = 16) -> str:
    hex_part = digest.split(":", 1)[-1]
    return hex_part[:size]


def _endpoint_key(statement: StatementBinding) -> tuple[str, str]:
    return (statement.statement_id, statement.statement_digest)


def _ordered_endpoints(
    left: StatementBinding, right: StatementBinding
) -> tuple[StatementBinding, StatementBinding]:
    if _endpoint_key(right) < _endpoint_key(left):
        return right, left
    return left, right


def _pair_duplicate_key(
    left: StatementBinding,
    right: StatementBinding,
    relationship: SemanticRelationship,
) -> tuple[tuple[str, str], tuple[str, str], str]:
    first, second = _ordered_endpoints(left, right)
    return (_endpoint_key(first), _endpoint_key(second), relationship.value)


def _endpoint_pair_key(left: StatementBinding, right: StatementBinding) -> tuple[tuple[str, str], tuple[str, str]]:
    first, second = _ordered_endpoints(left, right)
    return (_endpoint_key(first), _endpoint_key(second))


def positive_pair_authorities(relationship: SemanticRelationship) -> frozenset[LabelAuthority]:
    return _RELATION_AUTHORITIES[relationship]


def receipt_kind_for(relationship: SemanticRelationship) -> str:
    return _DEFAULT_RECEIPT_KIND.get(relationship, RECEIPT_SEMANTIC)


def sealed_campaign_lineage(
    *,
    lineage_group_ids: Sequence[str],
    source_record_ids: Sequence[str],
    split_name: str = TRAIN_SPLIT_NAME,
    rights_disposition: RightsDisposition = RightsDisposition.ADMITTED,
    parent_example_id: str = "",
    parent_example_digest: str = "",
) -> LineageBinding:
    """Bind a fixture or mined pair to the sealed PGIR-011/012 roots."""

    return LineageBinding(
        corpus_manifest_id=SEALED_CORPUS_MANIFEST_ID,
        corpus_manifest_cid=SEALED_CORPUS_MANIFEST_CID,
        lineage_graph_id=SEALED_LINEAGE_GRAPH_ID,
        lineage_graph_cid=SEALED_LINEAGE_GRAPH_CID,
        split_manifest_id=SEALED_SPLIT_MANIFEST_ID,
        split_manifest_digest=SEALED_SPLIT_MANIFEST_DIGEST,
        split_name=split_name,
        lineage_group_ids=tuple(lineage_group_ids),
        rights_disposition=rights_disposition,
        source_record_ids=tuple(source_record_ids),
        parent_example_id=parent_example_id,
        parent_example_digest=parent_example_digest,
    )


def make_statement(
    name: str,
    *,
    digest: str | None = None,
    representation: RepresentationKind = RepresentationKind.SOURCE_TEXT,
    logic_family: LogicFamily = LogicFamily.DEONTIC,
    lineage_group_ids: Sequence[str] = ("lineage:pgir-040",),
    source_record_ids: Sequence[str] = ("source:pgir-040",),
    source_ref_ids: Sequence[str] | None = None,
) -> StatementBinding:
    statement_digest = digest or _digest_for("statement", name)
    refs = source_ref_ids if source_ref_ids is not None else (f"source-ref:{name}",)
    return StatementBinding(
        statement_id=f"statement:{name}",
        statement_digest=statement_digest,
        representation=representation,
        logic_family=logic_family,
        artifact_id=f"artifact:{name}",
        artifact_digest=statement_digest,
        lineage_group_ids=tuple(lineage_group_ids),
        source_record_ids=tuple(source_record_ids),
        source_ref_ids=tuple(refs),
    )


def make_relationship_evidence(
    left: StatementBinding,
    right: StatementBinding,
    relationship: SemanticRelationship,
    *,
    evidence_id: str,
    authority: LabelAuthority,
    status: EvidenceStatus = EvidenceStatus.VERIFIED,
    independent: bool | None = None,
    result_authority: AuthorityKind | None = None,
    producer_id: str = "checker:pgir-040",
    producer_version: str = "1.0",
    evidence_digest: str | None = None,
) -> LabelEvidence:
    if independent is None:
        independent = authority in INDEPENDENT_AUTHORITIES
    if result_authority is None and authority is LabelAuthority.INDEPENDENT_SEMANTIC_CHECKER:
        if relationship is SemanticRelationship.EQUISATISFIABLE:
            result_authority = AuthorityKind.SATISFIABILITY
        else:
            result_authority = AuthorityKind.THEOREM_PROOF
    elif result_authority is None:
        result_authority = _DEFAULT_RESULT_AUTHORITY.get(authority)
    digest = evidence_digest or _digest_for(
        "evidence",
        evidence_id,
        relationship.value,
        authority.value,
        left.statement_digest,
        right.statement_digest,
    )
    return LabelEvidence(
        evidence_id=evidence_id,
        evidence_digest=digest,
        authority=authority,
        status=status,
        subject_statement_ids=(left.statement_id, right.statement_id),
        subject_statement_digests=(left.statement_digest, right.statement_digest),
        producer_id=producer_id,
        producer_version=producer_version,
        independent=independent,
        relationship=relationship,
        result_authority=result_authority,
    )


@dataclass(frozen=True, slots=True)
class PositivePairCandidate:
    """One proposed pair before fail-closed admission."""

    candidate_id: str
    left: StatementBinding
    right: StatementBinding
    left_authority: StatementAuthority
    right_authority: StatementAuthority
    relationship: SemanticRelationship
    lineage: LineageBinding
    evidence: tuple[LabelEvidence, ...]
    source_kind: str = "identity"
    receipt_kind: str = RECEIPT_RECONSTRUCTION
    unresolved_losses: tuple[str, ...] = ()
    preservation: PreservationClass = PreservationClass.UNKNOWN
    split_name: str = TRAIN_SPLIT_NAME
    sibling_split_name: str = TRAIN_SPLIT_NAME
    claimed_exact: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "claimed_exact": self.claimed_exact,
            "evidence": [item.to_dict() for item in self.evidence],
            "left": self.left.to_dict(),
            "left_authority": self.left_authority.value,
            "lineage": self.lineage.to_dict(),
            "preservation": self.preservation.value,
            "receipt_kind": self.receipt_kind,
            "relationship": self.relationship.value,
            "right": self.right.to_dict(),
            "right_authority": self.right_authority.value,
            "sibling_split_name": self.sibling_split_name,
            "source_kind": self.source_kind,
            "split_name": self.split_name,
            "unresolved_losses": list(self.unresolved_losses),
        }


@dataclass(frozen=True, slots=True)
class RejectedPositivePair:
    """A candidate that failed a fail-closed authority or lineage gate."""

    candidate_id: str
    reason: PositivePairRejection
    detail: str
    relationship: str
    claimed_exact: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "claimed_exact": self.claimed_exact,
            "detail": self.detail,
            "reason": self.reason.value,
            "relationship": self.relationship,
        }


@dataclass(frozen=True, slots=True)
class EvidenceReceipt:
    """Reconstruction, kernel, or translation receipt bound to one pair."""

    receipt_id: str
    kind: str
    pair_id: str
    evidence_id: str
    evidence_digest: str
    authority: str
    independent: bool
    relationship: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority": self.authority,
            "evidence_digest": self.evidence_digest,
            "evidence_id": self.evidence_id,
            "independent": self.independent,
            "kind": self.kind,
            "pair_id": self.pair_id,
            "receipt_id": self.receipt_id,
            "relationship": self.relationship,
        }


@dataclass(frozen=True, slots=True)
class AdmittedPositivePair:
    """An ``IRPositivePair@1`` plus the receipt that justified it."""

    pair: IRPositivePair
    source_kind: str
    receipt: EvidenceReceipt
    example: IRTrainingExample

    @property
    def pair_id(self) -> str:
        return self.pair.pair_id

    def to_dict(self) -> dict[str, Any]:
        return {
            "example_cid": self.example.cid,
            "example_digest": self.example.digest,
            "pair": self.pair.to_dict(),
            "pair_cid": self.pair.cid,
            "pair_digest": self.pair.digest,
            "receipt": self.receipt.to_dict(),
            "source_kind": self.source_kind,
        }


@dataclass(frozen=True, slots=True)
class PositiveEquivalenceIndex:
    """Read-only index used by hard-negative false-negative protection."""

    interface: str = IR_POSITIVE_PAIR_INDEX_INTERFACE
    pairs_by_class: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    siblings_by_statement: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    class_by_pair: Mapping[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "class_by_pair": dict(self.class_by_pair),
            "interface": self.interface,
            "pairs_by_class": {key: list(value) for key, value in self.pairs_by_class.items()},
            "siblings_by_statement": {
                key: list(value) for key, value in self.siblings_by_statement.items()
            },
        }

    def siblings(self, statement_id: str) -> tuple[str, ...]:
        return tuple(self.siblings_by_statement.get(statement_id, ()))


@dataclass(frozen=True, slots=True)
class PositivePairMiningResult:
    """Deterministic output of one mining pass."""

    admitted: tuple[AdmittedPositivePair, ...]
    rejected: tuple[RejectedPositivePair, ...]
    index: PositiveEquivalenceIndex
    receipts: tuple[EvidenceReceipt, ...]
    miner_version: str = IR_POSITIVE_PAIR_MINER_VERSION
    interface: str = IR_POSITIVE_PAIR_INTERFACE

    @property
    def pairs(self) -> tuple[IRPositivePair, ...]:
        return tuple(item.pair for item in self.admitted)

    @property
    def covered_classes(self) -> tuple[str, ...]:
        return tuple(
            relationship.value
            for relationship in POSITIVE_EQUIVALENCE_CLASSES
            if any(item.pair.relationship is relationship for item in self.admitted)
        )

    def identity(self) -> str:
        return content_digest(
            {
                "admitted": [item.to_dict() for item in self.admitted],
                "covered_classes": list(self.covered_classes),
                "interface": self.interface,
                "miner_version": self.miner_version,
                "rejected": [item.to_dict() for item in self.rejected],
            }
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "admitted": [item.to_dict() for item in self.admitted],
            "covered_classes": list(self.covered_classes),
            "identity": self.identity(),
            "index": self.index.to_dict(),
            "interface": self.interface,
            "miner_version": self.miner_version,
            "pair_count": len(self.admitted),
            "receipts": [item.to_dict() for item in self.receipts],
            "rejected": [item.to_dict() for item in self.rejected],
            "rejected_count": len(self.rejected),
        }


def _lineage_complete(lineage: LineageBinding, *statements: StatementBinding) -> bool:
    if not lineage.corpus_manifest_id or not lineage.corpus_manifest_cid:
        return False
    if not lineage.lineage_graph_id or not lineage.lineage_graph_cid:
        return False
    if not lineage.split_manifest_id or not lineage.split_manifest_digest:
        return False
    if not lineage.lineage_group_ids:
        return False
    if not lineage.source_record_ids and not lineage.parent_example_id:
        return False
    for statement in statements:
        if not statement.lineage_group_ids:
            return False
        if set(statement.lineage_group_ids) - set(lineage.lineage_group_ids):
            return False
        if not lineage.parent_example_id and (
            not statement.source_record_ids or not statement.source_ref_ids
        ):
            return False
        if set(statement.source_record_ids) - set(lineage.source_record_ids):
            return False
    return True


def _group_split(
    group_id: str,
    assignments: Mapping[str, str],
    default_split: str,
) -> str:
    return str(assignments.get(group_id, default_split))


def classify_positive_pair_candidate(
    candidate: PositivePairCandidate,
    *,
    split_assignments: Mapping[str, str] | None = None,
) -> PositivePairRejection | None:
    """Return the first fail-closed rejection, or ``None`` when admissible."""

    assignments = dict(split_assignments or {})
    if candidate.relationship is SemanticRelationship.UNKNOWN:
        return PositivePairRejection.UNKNOWN_RELATIONSHIP
    if candidate.relationship not in POSITIVE_EQUIVALENCE_CLASSES:
        return PositivePairRejection.UNKNOWN_RELATIONSHIP
    if _endpoint_key(candidate.left) == _endpoint_key(candidate.right):
        return PositivePairRejection.ENDPOINTS_NOT_DISTINCT
    if candidate.lineage.rights_disposition is not RightsDisposition.ADMITTED:
        return PositivePairRejection.RIGHTS_NOT_ADMITTED
    if not _lineage_complete(candidate.lineage, candidate.left, candidate.right):
        return PositivePairRejection.INCOMPLETE_LINEAGE
    if (
        candidate.split_name != TRAIN_SPLIT_NAME
        or candidate.lineage.split_name != TRAIN_SPLIT_NAME
    ):
        return PositivePairRejection.NON_TRAINING_SPLIT
    if candidate.sibling_split_name != TRAIN_SPLIT_NAME:
        return PositivePairRejection.CROSS_SPLIT_SIBLING
    if candidate.split_name != candidate.sibling_split_name:
        return PositivePairRejection.CROSS_SPLIT_SIBLING

    group_splits = {
        _group_split(group_id, assignments, candidate.split_name)
        for group_id in (
            *candidate.left.lineage_group_ids,
            *candidate.right.lineage_group_ids,
            *candidate.lineage.lineage_group_ids,
        )
    }
    if any(split != TRAIN_SPLIT_NAME for split in group_splits):
        if len(group_splits) > 1:
            return PositivePairRejection.CROSS_SPLIT_SIBLING
        return PositivePairRejection.LINEAGE_GROUP_SPLIT

    if (
        candidate.left_authority in CANDIDATE_STATEMENT_AUTHORITIES
        or candidate.right_authority in CANDIDATE_STATEMENT_AUTHORITIES
    ):
        return PositivePairRejection.CANDIDATE_STATEMENT_AUTHORITY

    if candidate.claimed_exact and candidate.relationship in WEAKER_THAN_EXACT:
        return PositivePairRejection.WEAKER_CLASS_AS_EXACT
    if candidate.relationship is SemanticRelationship.EXACT and (
        candidate.unresolved_losses
        or candidate.preservation
        in {
            PreservationClass.EQUISATISFIABLE,
            PreservationClass.HEURISTIC,
            PreservationClass.OVER_APPROXIMATION,
            PreservationClass.UNDER_APPROXIMATION,
            PreservationClass.UNSUPPORTED,
            PreservationClass.UNKNOWN,
        }
        and candidate.source_kind
        in {"compiler", "decompiler", "translation", "round_trip"}
    ):
        if candidate.unresolved_losses:
            return PositivePairRejection.UNRESOLVED_LOSS_AS_EXACT
        if candidate.preservation in {
            PreservationClass.EQUISATISFIABLE,
            PreservationClass.HEURISTIC,
            PreservationClass.OVER_APPROXIMATION,
            PreservationClass.UNDER_APPROXIMATION,
            PreservationClass.UNSUPPORTED,
        }:
            return PositivePairRejection.WEAKER_CLASS_AS_EXACT

    if not candidate.evidence:
        return PositivePairRejection.UNVERIFIED_EVIDENCE

    if any(item.authority in MODEL_ONLY_AUTHORITIES for item in candidate.evidence):
        if candidate.relationship is SemanticRelationship.PROOF_EQUIVALENT:
            return PositivePairRejection.MODEL_ONLY_PROOF_LABEL
        return PositivePairRejection.MODEL_ONLY_EVIDENCE

    if not _has_verified_relationship_evidence(
        candidate.evidence,
        (candidate.left, candidate.right),
        candidate.relationship,
    ):
        return PositivePairRejection.UNVERIFIED_EVIDENCE

    admitted_authorities = positive_pair_authorities(candidate.relationship)
    verified = [
        item
        for item in candidate.evidence
        if item.status is EvidenceStatus.VERIFIED
        and item.relationship is candidate.relationship
    ]
    if not verified or any(item.authority not in admitted_authorities for item in verified):
        return PositivePairRejection.AUTHORITY_NOT_ADMITTED_FOR_CLASS

    if candidate.relationship in INDEPENDENT_VERIFICATION_CLASSES:
        if not any(
            item.independent and item.authority in INDEPENDENT_AUTHORITIES for item in verified
        ):
            return PositivePairRejection.INDEPENDENT_VERIFICATION_REQUIRED
        if candidate.relationship is SemanticRelationship.PROOF_EQUIVALENT and not any(
            item.authority is LabelAuthority.INDEPENDENT_PROOF_CHECKER
            and item.result_authority is AuthorityKind.THEOREM_PROOF
            for item in verified
        ):
            return PositivePairRejection.INDEPENDENT_VERIFICATION_REQUIRED
    return None


def _pair_and_example(candidate: PositivePairCandidate) -> tuple[IRPositivePair, IRTrainingExample]:
    left, right = candidate.left, candidate.right
    left_authority, right_authority = candidate.left_authority, candidate.right_authority
    if _endpoint_key(right) < _endpoint_key(left):
        left, right = right, left
        left_authority, right_authority = right_authority, left_authority
    pair_id = (
        f"pair:{candidate.relationship.value}:"
        f"{_short_id(_digest_for(left.statement_digest, right.statement_digest, candidate.relationship.value))}"
    )
    class_id = (
        f"equivalence:{candidate.relationship.value}:"
        f"{_short_id(_digest_for('class', left.statement_digest, right.statement_digest, candidate.relationship.value))}"
    )
    pair = IRPositivePair(
        pair_id=pair_id,
        lineage=candidate.lineage,
        left=left,
        right=right,
        left_authority=left_authority,
        right_authority=right_authority,
        relationship=candidate.relationship,
        equivalence_class_id=class_id,
        evidence=candidate.evidence,
    )
    selected = pair.evidence[0].evidence_id
    example = IRTrainingExample.classify(
        example_id=f"example:{pair.pair_id}",
        record=pair,
        selected_evidence_id=selected,
    )
    if not example.training_eligible:
        raise PositivePairAdmissionError(
            f"{pair.pair_id} failed training admission: "
            + ", ".join(item.value for item in example.quarantine_reasons)
        )
    return pair, example


def _receipt_for(pair: IRPositivePair, candidate: PositivePairCandidate) -> EvidenceReceipt:
    evidence = pair.evidence[0]
    kind = candidate.receipt_kind or receipt_kind_for(pair.relationship)
    if kind not in RECEIPT_KINDS:
        raise PositivePairAdmissionError(f"unknown receipt kind {kind!r}")
    return EvidenceReceipt(
        receipt_id=f"receipt:{kind}:{_short_id(evidence.evidence_digest)}",
        kind=kind,
        pair_id=pair.pair_id,
        evidence_id=evidence.evidence_id,
        evidence_digest=evidence.evidence_digest,
        authority=evidence.authority.value,
        independent=evidence.independent,
        relationship=pair.relationship.value,
    )


def _build_index(admitted: Sequence[AdmittedPositivePair]) -> PositiveEquivalenceIndex:
    pairs_by_class: dict[str, list[str]] = {item.value: [] for item in POSITIVE_EQUIVALENCE_CLASSES}
    siblings: dict[str, set[str]] = {}
    class_by_pair: dict[str, str] = {}
    for item in admitted:
        pair = item.pair
        pairs_by_class[pair.relationship.value].append(pair.pair_id)
        class_by_pair[pair.pair_id] = pair.relationship.value
        siblings.setdefault(pair.left.statement_id, set()).add(pair.right.statement_id)
        siblings.setdefault(pair.right.statement_id, set()).add(pair.left.statement_id)
    return PositiveEquivalenceIndex(
        pairs_by_class={
            key: tuple(values) for key, values in pairs_by_class.items() if values
        },
        siblings_by_statement={
            key: tuple(sorted(values)) for key, values in sorted(siblings.items())
        },
        class_by_pair=class_by_pair,
    )


def mine_positive_pairs(
    candidates: Sequence[PositivePairCandidate],
    *,
    split_assignments: Mapping[str, str] | None = None,
    raise_on_reject: bool = False,
) -> PositivePairMiningResult:
    """Admit typed positives, filter duplicates, and keep the strongest class."""

    rejected: list[RejectedPositivePair] = []
    pending: list[PositivePairCandidate] = []
    seen_duplicates: set[tuple[tuple[str, str], tuple[str, str], str]] = set()

    for candidate in candidates:
        reason = classify_positive_pair_candidate(
            candidate, split_assignments=split_assignments
        )
        if reason is not None:
            item = RejectedPositivePair(
                candidate_id=candidate.candidate_id,
                reason=reason,
                detail=reason.value,
                relationship=candidate.relationship.value,
                claimed_exact=candidate.claimed_exact,
            )
            rejected.append(item)
            if raise_on_reject:
                raise PositivePairAdmissionError(
                    f"{candidate.candidate_id}: {reason.value}"
                )
            continue
        key = _pair_duplicate_key(
            candidate.left, candidate.right, candidate.relationship
        )
        if key in seen_duplicates:
            rejected.append(
                RejectedPositivePair(
                    candidate_id=candidate.candidate_id,
                    reason=PositivePairRejection.DUPLICATE_PAIR,
                    detail="duplicate endpoints and relationship",
                    relationship=candidate.relationship.value,
                )
            )
            continue
        seen_duplicates.add(key)
        pending.append(candidate)

    strongest: dict[tuple[tuple[str, str], tuple[str, str]], PositivePairCandidate] = {}
    for candidate in pending:
        endpoint_key = _endpoint_pair_key(candidate.left, candidate.right)
        current = strongest.get(endpoint_key)
        if current is None:
            strongest[endpoint_key] = candidate
            continue
        if _CLASS_STRENGTH[candidate.relationship] > _CLASS_STRENGTH[current.relationship]:
            rejected.append(
                RejectedPositivePair(
                    candidate_id=current.candidate_id,
                    reason=PositivePairRejection.SUPERSEDED_WEAKER_CLASS,
                    detail=f"kept {candidate.relationship.value}",
                    relationship=current.relationship.value,
                )
            )
            strongest[endpoint_key] = candidate
        else:
            rejected.append(
                RejectedPositivePair(
                    candidate_id=candidate.candidate_id,
                    reason=PositivePairRejection.SUPERSEDED_WEAKER_CLASS,
                    detail=f"kept {current.relationship.value}",
                    relationship=candidate.relationship.value,
                )
            )

    admitted: list[AdmittedPositivePair] = []
    for candidate in sorted(
        strongest.values(),
        key=lambda item: (
            item.relationship.value,
            item.left.statement_id,
            item.right.statement_id,
            item.candidate_id,
        ),
    ):
        pair, example = _pair_and_example(candidate)
        receipt = _receipt_for(pair, candidate)
        admitted.append(
            AdmittedPositivePair(
                pair=pair,
                source_kind=candidate.source_kind,
                receipt=receipt,
                example=example,
            )
        )

    result = PositivePairMiningResult(
        admitted=tuple(admitted),
        rejected=tuple(
            sorted(rejected, key=lambda item: (item.reason.value, item.candidate_id))
        ),
        index=_build_index(admitted),
        receipts=tuple(item.receipt for item in admitted),
    )
    return result


def candidate_from_transformation(
    trace: IRCompilerTrace | IRDecompilerTrace | IRTranslationTrace,
    *,
    receipt_kind: str | None = None,
) -> PositivePairCandidate:
    if trace.target is None or trace.status is not TraceStatus.SUCCEEDED:
        raise PositivePairAdmissionError("transformation must succeed and bind a target")
    source_kind = {
        IRCompilerTrace: "compiler",
        IRDecompilerTrace: "decompiler",
        IRTranslationTrace: "translation",
    }[type(trace)]
    kind = receipt_kind or (
        RECEIPT_TRANSLATION
        if isinstance(trace, IRTranslationTrace)
        else RECEIPT_RECONSTRUCTION
    )
    return PositivePairCandidate(
        candidate_id=f"candidate:{trace.trace_id}",
        left=trace.source,
        right=trace.target,
        left_authority=trace.source_authority,
        right_authority=trace.target_authority,
        relationship=trace.relationship,
        lineage=trace.lineage,
        evidence=trace.evidence,
        source_kind=source_kind,
        receipt_kind=kind,
        unresolved_losses=trace.unresolved_losses,
        preservation=trace.preservation,
        split_name=trace.lineage.split_name,
        sibling_split_name=trace.lineage.split_name,
        claimed_exact=trace.relationship is SemanticRelationship.EXACT,
    )


def candidate_from_round_trip(trace: IRRoundTripTrace) -> PositivePairCandidate:
    if (
        trace.forward.status is not TraceStatus.SUCCEEDED
        or trace.reverse.status is not TraceStatus.SUCCEEDED
    ):
        raise PositivePairAdmissionError("round trip must succeed in both directions")
    return PositivePairCandidate(
        candidate_id=f"candidate:{trace.trace_id}",
        left=trace.original,
        right=trace.reconstructed,
        left_authority=trace.forward.trace.source_authority,
        right_authority=trace.reverse.trace.target_authority,
        relationship=trace.relationship,
        lineage=trace.lineage,
        evidence=trace.evidence,
        source_kind="round_trip",
        receipt_kind=RECEIPT_RECONSTRUCTION,
        unresolved_losses=trace.unresolved_losses,
        preservation=trace.preservation,
        split_name=trace.lineage.split_name,
        sibling_split_name=trace.lineage.split_name,
        claimed_exact=trace.relationship is SemanticRelationship.EXACT,
    )


def candidate_from_proof_identity(
    left: IRProofTrace,
    right: IRProofTrace,
    *,
    relationship: SemanticRelationship = SemanticRelationship.PROOF_EQUIVALENT,
    evidence: Sequence[LabelEvidence] | None = None,
) -> PositivePairCandidate:
    """Pair two independently proved statements of the same claim."""

    if left.claim_digest != right.claim_digest:
        raise PositivePairAdmissionError("proof-equivalent statements must share a claim digest")
    if left.outcome is not ProofOutcome.PROVED or right.outcome is not ProofOutcome.PROVED:
        raise PositivePairAdmissionError("proof-equivalent mining requires independently proved traces")
    if left.producer.producer_kind is not None and any(
        item.authority in MODEL_ONLY_AUTHORITIES for item in (*left.evidence, *right.evidence)
    ):
        raise PositivePairAdmissionError("model-only proof labels cannot seed proof pairs")
    lineage = left.lineage
    if set(right.statement.lineage_group_ids) - set(lineage.lineage_group_ids):
        lineage = sealed_campaign_lineage(
            lineage_group_ids=tuple(
                sorted(set(left.lineage.lineage_group_ids) | set(right.lineage.lineage_group_ids))
            ),
            source_record_ids=tuple(
                sorted(set(left.lineage.source_record_ids) | set(right.lineage.source_record_ids))
            ),
            split_name=left.lineage.split_name,
            rights_disposition=left.lineage.rights_disposition,
        )
    pair_evidence = tuple(evidence) if evidence is not None else (
        make_relationship_evidence(
            left.statement,
            right.statement,
            relationship,
            evidence_id=f"evidence:kernel:{_short_id(left.proof_receipt_digest)}",
            authority=LabelAuthority.INDEPENDENT_PROOF_CHECKER,
            independent=True,
            result_authority=AuthorityKind.THEOREM_PROOF,
            producer_id=left.checker.tool_id if left.checker is not None else "tool:kernel",
            producer_version=left.checker.tool_version if left.checker is not None else "1.0",
            evidence_digest=left.proof_receipt_digest or _digest_for("kernel", left.trace_id),
        ),
    )
    return PositivePairCandidate(
        candidate_id=f"candidate:proof:{left.trace_id}:{right.trace_id}",
        left=left.statement,
        right=right.statement,
        left_authority=StatementAuthority.INDEPENDENTLY_VERIFIED,
        right_authority=StatementAuthority.INDEPENDENTLY_VERIFIED,
        relationship=relationship,
        lineage=lineage,
        evidence=pair_evidence,
        source_kind="proof",
        receipt_kind=RECEIPT_KERNEL,
        preservation=PreservationClass.PROOF,
        split_name=left.lineage.split_name,
        sibling_split_name=right.lineage.split_name,
    )


def mine_from_records(
    *,
    traces: Sequence[Any] = (),
    identities: Sequence[PositivePairCandidate] = (),
    proof_pairs: Sequence[tuple[IRProofTrace, IRProofTrace]] = (),
    split_assignments: Mapping[str, str] | None = None,
    raise_on_reject: bool = False,
) -> PositivePairMiningResult:
    """Mine pairs from verified traces, identities, and same-claim proofs."""

    candidates: list[PositivePairCandidate] = list(identities)
    for trace in traces:
        if isinstance(trace, IRRoundTripTrace):
            candidates.append(candidate_from_round_trip(trace))
        elif isinstance(trace, (IRCompilerTrace, IRDecompilerTrace, IRTranslationTrace)):
            candidates.append(candidate_from_transformation(trace))
        else:
            raise PositivePairMinerError(f"unsupported mining record {type(trace).__name__}")
    for left, right in proof_pairs:
        candidates.append(candidate_from_proof_identity(left, right))
    return mine_positive_pairs(
        candidates,
        split_assignments=split_assignments,
        raise_on_reject=raise_on_reject,
    )


def _representation(value: str) -> RepresentationKind:
    return RepresentationKind(value)


def _authority(value: str) -> LabelAuthority:
    return LabelAuthority(value)


def _statement_authority(value: str) -> StatementAuthority:
    return StatementAuthority(value)


def candidate_from_recipe_case(
    case: Mapping[str, Any],
    *,
    default_family: LogicFamily = LogicFamily.DEONTIC,
) -> PositivePairCandidate:
    """Expand one compact recipe case into a fully bound candidate."""

    if not isinstance(case, Mapping):
        raise PositivePairMinerError("recipe case must be a mapping")
    case_id = str(case.get("case_id") or "").strip()
    if not case_id:
        raise PositivePairMinerError("recipe case requires case_id")
    try:
        relationship = SemanticRelationship(str(case.get("relationship") or ""))
    except ValueError as exc:
        raise PositivePairMinerError(
            f"unknown positive-pair relationship {case.get('relationship')!r}"
        ) from exc
    group = str(case.get("lineage_group") or f"lineage:pgir-040:{case_id}")
    source = str(case.get("source_record") or f"source:pgir-040:{case_id}")
    split_name = str(case.get("split") or TRAIN_SPLIT_NAME)
    sibling_split = str(case.get("sibling_split") or split_name)
    left_name = str(case.get("left_name") or f"{case_id}-left")
    right_name = str(case.get("right_name") or f"{case_id}-right")
    left = make_statement(
        left_name,
        representation=_representation(str(case.get("left_representation") or "source_text")),
        logic_family=LogicFamily(str(case.get("logic_family") or default_family.value)),
        lineage_group_ids=(group,),
        source_record_ids=(source,),
    )
    right = make_statement(
        right_name,
        representation=_representation(str(case.get("right_representation") or "canonical_ir")),
        logic_family=LogicFamily(str(case.get("logic_family") or default_family.value)),
        lineage_group_ids=(str(case.get("right_lineage_group") or group),),
        source_record_ids=(str(case.get("right_source_record") or source),),
    )
    rights = RightsDisposition(str(case.get("rights") or RightsDisposition.ADMITTED.value))
    lineage = sealed_campaign_lineage(
        lineage_group_ids=tuple(
            sorted({group, str(case.get("right_lineage_group") or group)})
        ),
        source_record_ids=tuple(
            sorted({source, str(case.get("right_source_record") or source)})
        ),
        split_name=split_name,
        rights_disposition=rights,
    )
    authority = _authority(str(case.get("authority") or LabelAuthority.CANONICAL_VALIDATOR.value))
    independent = case.get("independent")
    if independent is None:
        independent = authority in INDEPENDENT_AUTHORITIES
    result_authority_raw = case.get("result_authority")
    result_authority = (
        AuthorityKind(str(result_authority_raw)) if result_authority_raw else None
    )
    status = EvidenceStatus(str(case.get("evidence_status") or EvidenceStatus.VERIFIED.value))
    evidence = make_relationship_evidence(
        left,
        right,
        relationship,
        evidence_id=str(case.get("evidence_id") or f"evidence:{case_id}"),
        authority=authority,
        status=status,
        independent=bool(independent),
        result_authority=result_authority,
        producer_id=str(case.get("producer_id") or "checker:pgir-040"),
        producer_version=str(case.get("producer_version") or "1.0"),
    )
    preservation_raw = case.get("preservation")
    if preservation_raw:
        preservation = PreservationClass(str(preservation_raw))
    elif relationship is SemanticRelationship.EXACT:
        preservation = PreservationClass.LOSSLESS
    elif relationship is SemanticRelationship.PROOF_EQUIVALENT:
        preservation = PreservationClass.PROOF
    elif relationship is SemanticRelationship.EQUISATISFIABLE:
        preservation = PreservationClass.EQUISATISFIABLE
    elif relationship in {
        SemanticRelationship.LOGICALLY_EQUIVALENT,
        SemanticRelationship.TRANSLATION_EQUIVALENT,
        SemanticRelationship.PARAPHRASE,
    }:
        preservation = PreservationClass.SEMANTIC
    else:
        preservation = PreservationClass.STRUCTURAL
    return PositivePairCandidate(
        candidate_id=f"candidate:{case_id}",
        left=left,
        right=right,
        left_authority=_statement_authority(
            str(case.get("left_authority") or StatementAuthority.SOURCE_ASSERTED.value)
        ),
        right_authority=_statement_authority(
            str(case.get("right_authority") or StatementAuthority.CANONICALLY_VALIDATED.value)
        ),
        relationship=relationship,
        lineage=lineage,
        evidence=(evidence,),
        source_kind=str(case.get("source_kind") or "recipe"),
        receipt_kind=str(case.get("receipt_kind") or receipt_kind_for(relationship)),
        unresolved_losses=tuple(case.get("unresolved_losses") or ()),
        preservation=preservation,
        split_name=split_name,
        sibling_split_name=sibling_split,
        claimed_exact=bool(case.get("claimed_exact", relationship is SemanticRelationship.EXACT)),
    )


def canonical_positive_pair_recipe() -> dict[str, Any]:
    """Compact generator for the sealed PGIR-040 class coverage set."""

    cases = [
        {
            "authority": LabelAuthority.CANONICAL_VALIDATOR.value,
            "case_id": "exact-reconstruction",
            "left_authority": StatementAuthority.SOURCE_ASSERTED.value,
            "left_representation": RepresentationKind.SOURCE_TEXT.value,
            "preservation": PreservationClass.LOSSLESS.value,
            "receipt_kind": RECEIPT_RECONSTRUCTION,
            "relationship": SemanticRelationship.EXACT.value,
            "right_authority": StatementAuthority.CANONICALLY_VALIDATED.value,
            "right_representation": RepresentationKind.CANONICAL_IR.value,
            "source_kind": "round_trip",
        },
        {
            "authority": LabelAuthority.DETERMINISTIC_VALIDATOR.value,
            "case_id": "alpha-binder-rename",
            "left_authority": StatementAuthority.DETERMINISTICALLY_DERIVED.value,
            "left_representation": RepresentationKind.TYPED_SYNTAX.value,
            "preservation": PreservationClass.STRUCTURAL.value,
            "receipt_kind": RECEIPT_RECONSTRUCTION,
            "relationship": SemanticRelationship.ALPHA_EQUIVALENT.value,
            "right_authority": StatementAuthority.DETERMINISTICALLY_DERIVED.value,
            "right_representation": RepresentationKind.TYPED_SYNTAX.value,
            "source_kind": "identity",
        },
        {
            "authority": LabelAuthority.CANONICAL_VALIDATOR.value,
            "case_id": "canonical-ir-identity",
            "left_authority": StatementAuthority.CANONICALLY_VALIDATED.value,
            "left_representation": RepresentationKind.CANONICAL_IR.value,
            "preservation": PreservationClass.STRUCTURAL.value,
            "receipt_kind": RECEIPT_RECONSTRUCTION,
            "relationship": SemanticRelationship.CANONICAL_EQUIVALENT.value,
            "right_authority": StatementAuthority.CANONICALLY_VALIDATED.value,
            "right_representation": RepresentationKind.CANONICAL_IR.value,
            "source_kind": "identity",
        },
        {
            "authority": LabelAuthority.INDEPENDENT_SEMANTIC_CHECKER.value,
            "case_id": "logical-independent",
            "independent": True,
            "left_authority": StatementAuthority.INDEPENDENTLY_VERIFIED.value,
            "left_representation": RepresentationKind.CANONICAL_IR.value,
            "preservation": PreservationClass.SEMANTIC.value,
            "receipt_kind": RECEIPT_SEMANTIC,
            "relationship": SemanticRelationship.LOGICALLY_EQUIVALENT.value,
            "result_authority": AuthorityKind.THEOREM_PROOF.value,
            "right_authority": StatementAuthority.INDEPENDENTLY_VERIFIED.value,
            "right_representation": RepresentationKind.CANONICAL_IR.value,
            "source_kind": "identity",
        },
        {
            "authority": LabelAuthority.INDEPENDENT_SEMANTIC_CHECKER.value,
            "case_id": "equisatisfiable-independent",
            "claimed_exact": False,
            "independent": True,
            "left_authority": StatementAuthority.INDEPENDENTLY_VERIFIED.value,
            "left_representation": RepresentationKind.CANONICAL_IR.value,
            "preservation": PreservationClass.EQUISATISFIABLE.value,
            "receipt_kind": RECEIPT_SEMANTIC,
            "relationship": SemanticRelationship.EQUISATISFIABLE.value,
            "result_authority": AuthorityKind.SATISFIABILITY.value,
            "right_authority": StatementAuthority.INDEPENDENTLY_VERIFIED.value,
            "right_representation": RepresentationKind.PROVER_SYNTAX.value,
            "source_kind": "translation",
        },
        {
            "authority": LabelAuthority.INDEPENDENT_PROOF_CHECKER.value,
            "case_id": "proof-kernel",
            "independent": True,
            "left_authority": StatementAuthority.INDEPENDENTLY_VERIFIED.value,
            "left_representation": RepresentationKind.PROVER_SYNTAX.value,
            "preservation": PreservationClass.PROOF.value,
            "receipt_kind": RECEIPT_KERNEL,
            "relationship": SemanticRelationship.PROOF_EQUIVALENT.value,
            "result_authority": AuthorityKind.THEOREM_PROOF.value,
            "right_authority": StatementAuthority.INDEPENDENTLY_VERIFIED.value,
            "right_representation": RepresentationKind.PROOF_STATE.value,
            "source_kind": "proof",
        },
        {
            "authority": LabelAuthority.INDEPENDENT_TRANSLATION_CHECKER.value,
            "case_id": "translation-independent",
            "independent": True,
            "left_authority": StatementAuthority.CANONICALLY_VALIDATED.value,
            "left_representation": RepresentationKind.CANONICAL_IR.value,
            "preservation": PreservationClass.SEMANTIC.value,
            "receipt_kind": RECEIPT_TRANSLATION,
            "relationship": SemanticRelationship.TRANSLATION_EQUIVALENT.value,
            "right_authority": StatementAuthority.DETERMINISTICALLY_DERIVED.value,
            "right_representation": RepresentationKind.PROVER_SYNTAX.value,
            "source_kind": "translation",
        },
        {
            "authority": LabelAuthority.HUMAN_REVIEW.value,
            "case_id": "paraphrase-review",
            "claimed_exact": False,
            "independent": False,
            "left_authority": StatementAuthority.SOURCE_ASSERTED.value,
            "left_representation": RepresentationKind.SOURCE_TEXT.value,
            "preservation": PreservationClass.SEMANTIC.value,
            "receipt_kind": RECEIPT_HUMAN,
            "relationship": SemanticRelationship.PARAPHRASE.value,
            "right_authority": StatementAuthority.DETERMINISTICALLY_DERIVED.value,
            "right_representation": RepresentationKind.CONTROLLED_NATURAL_LANGUAGE.value,
            "source_kind": "decompiler",
        },
    ]
    recipe = {
        "cases": cases,
        "classes": [item.value for item in POSITIVE_EQUIVALENCE_CLASSES],
        "compiler_identity": "RESULT(PGIR-021)",
        "corpus_manifest_cid": SEALED_CORPUS_MANIFEST_CID,
        "corpus_manifest_id": SEALED_CORPUS_MANIFEST_ID,
        "corpus_root_sha256": SEALED_CORPUS_ROOT_SHA256,
        "decompiler_identity": "RESULT(PGIR-022)",
        "independent_verification_classes": [
            item.value for item in sorted(INDEPENDENT_VERIFICATION_CLASSES, key=lambda item: item.value)
        ],
        "interface": IR_POSITIVE_PAIR_RECIPE_INTERFACE,
        "miner_version": IR_POSITIVE_PAIR_MINER_VERSION,
        "model_checkpoint_identity": "none/deterministic",
        "prohibited": [
            "equisatisfiable_as_exact",
            "paraphrase_as_exact",
            "cross_split_siblings",
            "model_only_proof_labels",
        ],
        "schema": IR_POSITIVE_PAIR_RECIPE_SCHEMA,
        "split_manifest_digest": SEALED_SPLIT_MANIFEST_DIGEST,
        "split_name": TRAIN_SPLIT_NAME,
        "split_root_sha256": SEALED_SPLIT_ROOT_SHA256,
        "task_id": IR_POSITIVE_PAIR_TASK_ID,
    }
    recipe["recipe_cid"] = content_cid(
        recipe,
        domain="ir.positive-pair-recipe",
        schema_version=IR_POSITIVE_PAIR_RECIPE_SCHEMA,
    )
    return recipe


def equivalence_class_catalog() -> dict[str, Any]:
    catalog = {
        "classes": [
            {
                "authorities": [item.value for item in sorted(positive_pair_authorities(relationship), key=lambda item: item.value)],
                "independent_verification_required": relationship in INDEPENDENT_VERIFICATION_CLASSES,
                "receipt_kind": receipt_kind_for(relationship),
                "relationship": relationship.value,
                "weaker_than_exact": relationship in WEAKER_THAN_EXACT,
            }
            for relationship in POSITIVE_EQUIVALENCE_CLASSES
        ],
        "interface": "IRPositiveEquivalenceClassCatalog@1",
        "schema": "ir-positive-equivalence-class/v1",
        "task_id": IR_POSITIVE_PAIR_TASK_ID,
    }
    catalog["catalog_cid"] = content_cid(
        catalog,
        domain="ir.positive-pair-class-catalog",
        schema_version="ir-positive-equivalence-class/v1",
    )
    return catalog


def mine_canonical_positive_pairs() -> PositivePairMiningResult:
    recipe = canonical_positive_pair_recipe()
    candidates = tuple(candidate_from_recipe_case(case) for case in recipe["cases"])
    return mine_positive_pairs(candidates)


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    except Exception:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
        raise


def cas_write_json(path: Path, payload: Mapping[str, Any]) -> str:
    """Write a JSON document with compare-and-swap on the canonical bytes."""

    text = _canonical_json(payload) + "\n"
    digest = content_digest(payload)
    if path.exists():
        existing = path.read_text(encoding="utf-8")
        if existing != text and existing.rstrip("\n") != text.rstrip("\n"):
            raise PositivePairShardConflictError(
                f"{path} already holds a different shard payload"
            )
        return digest
    _atomic_write_text(path, text)
    return digest


def build_positive_pair_shards(
    result: PositivePairMiningResult,
    *,
    recipe: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    recipe_payload = dict(recipe or canonical_positive_pair_recipe())
    shards: list[dict[str, Any]] = []
    for relationship in POSITIVE_EQUIVALENCE_CLASSES:
        members = [
            item.to_dict()
            for item in result.admitted
            if item.pair.relationship is relationship
        ]
        if not members:
            continue
        body = {
            "class": relationship.value,
            "interface": IR_POSITIVE_PAIR_SHARD_INTERFACE,
            "miner_version": IR_POSITIVE_PAIR_MINER_VERSION,
            "pair_count": len(members),
            "pairs": members,
            "schema": IR_POSITIVE_PAIR_SHARD_SCHEMA,
            "split_name": TRAIN_SPLIT_NAME,
            "task_id": IR_POSITIVE_PAIR_TASK_ID,
        }
        shard = {
            **body,
            "shard_cid": content_cid(
                body,
                domain="ir.positive-pair-shard",
                schema_version=IR_POSITIVE_PAIR_SHARD_SCHEMA,
            ),
            "shard_digest": content_digest(body),
        }
        shards.append(shard)
    receipts = {
        "interface": "IRPositivePairReceiptSet@1",
        "kinds": sorted({item.kind for item in result.receipts}),
        "receipts": [item.to_dict() for item in result.receipts],
        "schema": "ir-positive-pair-receipts/v1",
        "task_id": IR_POSITIVE_PAIR_TASK_ID,
    }
    receipts["receipts_cid"] = content_cid(
        receipts,
        domain="ir.positive-pair-receipts",
        schema_version="ir-positive-pair-receipts/v1",
    )
    catalog = equivalence_class_catalog()
    manifest = {
        "corpus_manifest_cid": SEALED_CORPUS_MANIFEST_CID,
        "covered_classes": list(result.covered_classes),
        "index": result.index.to_dict(),
        "interface": IR_POSITIVE_PAIR_MANIFEST_INTERFACE,
        "miner_identity": result.identity(),
        "miner_version": IR_POSITIVE_PAIR_MINER_VERSION,
        "model_checkpoint_identity": "none/deterministic",
        "pair_count": len(result.admitted),
        "recipe_cid": recipe_payload.get("recipe_cid"),
        "receipts_cid": receipts["receipts_cid"],
        "rejected_count": len(result.rejected),
        "schema": IR_POSITIVE_PAIR_MANIFEST_SCHEMA,
        "shards": [
            {
                "class": shard["class"],
                "pair_count": shard["pair_count"],
                "path": f"shards/{shard['class']}.json",
                "shard_cid": shard["shard_cid"],
                "shard_digest": shard["shard_digest"],
            }
            for shard in shards
        ],
        "split_manifest_digest": SEALED_SPLIT_MANIFEST_DIGEST,
        "split_name": TRAIN_SPLIT_NAME,
        "task_id": IR_POSITIVE_PAIR_TASK_ID,
    }
    manifest["manifest_cid"] = content_cid(
        manifest,
        domain="ir.positive-pair-manifest",
        schema_version=IR_POSITIVE_PAIR_MANIFEST_SCHEMA,
    )
    return {
        "catalog": catalog,
        "manifest": manifest,
        "receipts": receipts,
        "recipe": recipe_payload,
        "shards": shards,
    }


def write_positive_pair_shards(
    output_dir: str | Path,
    *,
    result: PositivePairMiningResult | None = None,
    recipe: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Persist immutable recipe, class catalog, receipts, and class shards."""

    mined = result or mine_canonical_positive_pairs()
    bundle = build_positive_pair_shards(mined, recipe=recipe)
    root = Path(output_dir)
    cas_write_json(root / "recipe.json", bundle["recipe"])
    cas_write_json(root / "classes.json", bundle["catalog"])
    cas_write_json(root / "receipts.json", bundle["receipts"])
    cas_write_json(root / "manifest.json", bundle["manifest"])
    for shard in bundle["shards"]:
        cas_write_json(root / "shards" / f"{shard['class']}.json", shard)
    return bundle


def load_positive_pair_shards(input_dir: str | Path) -> tuple[IRPositivePair, ...]:
    root = Path(input_dir)
    pairs: list[IRPositivePair] = []
    for path in sorted((root / "shards").glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        for item in payload.get("pairs", ()):
            pairs.append(IRPositivePair.from_dict(item["pair"]))
    return tuple(pairs)


def resolve_positive_pair_data_dir(start: str | Path | None = None) -> Path:
    """Locate ``data/ir_learning/pairs/positive`` from a package or cwd root."""

    if start is not None:
        candidate = Path(start)
        if candidate.is_dir():
            return candidate
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "data" / "ir_learning" / "pairs" / "positive"
        if candidate.is_dir():
            return candidate
    cwd = Path.cwd() / "ipfs_datasets_py" / "data" / "ir_learning" / "pairs" / "positive"
    return cwd


def loss_pair_admissions(
    pairs: Sequence[IRPositivePair],
) -> tuple[dict[str, Any], ...]:
    """Project admitted pairs into the ``IRLossPairAdmission`` shape."""

    return tuple(
        {
            "admitted": True,
            "left_id": pair.left.statement_id,
            "pair_class": "positive",
            "relationship": pair.relationship.value,
            "right_id": pair.right.statement_id,
        }
        for pair in pairs
    )


__all__ = [
    "AdmittedPositivePair",
    "DEFAULT_POSITIVE_PAIR_DATA_DIR",
    "EvidenceReceipt",
    "INDEPENDENT_VERIFICATION_CLASSES",
    "IR_POSITIVE_PAIR_INTERFACE",
    "IR_POSITIVE_PAIR_MINER_VERSION",
    "IR_POSITIVE_PAIR_SCHEMA_VERSION",
    "POSITIVE_EQUIVALENCE_CLASSES",
    "PositiveEquivalenceIndex",
    "PositivePairAdmissionError",
    "PositivePairCandidate",
    "PositivePairMinerError",
    "PositivePairMiningResult",
    "PositivePairRejection",
    "PositivePairShardConflictError",
    "RejectedPositivePair",
    "WEAKER_THAN_EXACT",
    "build_positive_pair_shards",
    "candidate_from_proof_identity",
    "candidate_from_recipe_case",
    "candidate_from_round_trip",
    "candidate_from_transformation",
    "canonical_positive_pair_recipe",
    "cas_write_json",
    "classify_positive_pair_candidate",
    "content_digest",
    "equivalence_class_catalog",
    "load_positive_pair_shards",
    "loss_pair_admissions",
    "make_relationship_evidence",
    "make_statement",
    "mine_canonical_positive_pairs",
    "mine_from_records",
    "mine_positive_pairs",
    "positive_pair_authorities",
    "receipt_kind_for",
    "resolve_positive_pair_data_dir",
    "sealed_campaign_lineage",
    "write_positive_pair_shards",
]
