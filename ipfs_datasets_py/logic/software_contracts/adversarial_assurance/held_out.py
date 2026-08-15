"""Deterministic diagnosis, development, and held-out evaluation policy (AAE-033).

Interface surface:

* ``partition_mutants@1`` — assign mutants into leakage-resistant diagnosis,
  development, and held-out partitions with deterministic provenance.
* ``qualify_remediation_evaluation@1`` — require unmutated, diagnosis,
  development, held-out, unrelated, cost, false-positive, overconstraint,
  regression, and safety evidence before a remediation may be qualified.

Authority rules (normative):

* Pure and deterministic: no store, worktree, or production-policy mutation.
* Canonical identity comes only from ``software_contracts.content``.
* Diagnosis, development, and held-out mutant identity sets are pairwise
  disjoint (leakage-resistant).
* Mutants used to generate or refine a candidate must not appear in held-out.
* Qualification fails closed when any required evaluation partition is missing,
  fails, or contradicts sealed partition membership.
* Model drafts cannot self-qualify or self-promote.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from hashlib import blake2b
from types import MappingProxyType
from typing import Any, ClassVar, Final, Iterable, Mapping, Sequence
import re
import unicodedata

from ipfs_datasets_py.logic.software_contracts.content import (
    cid_for_structured,
    validate_cid,
    validate_structured_value,
)
from ipfs_datasets_py.logic.software_contracts.adversarial_assurance.common import (
    AssuranceArtifactHeader,
    AssuranceBaseError,
    reject_private_model_authority_and_host_fallbacks,
)
from ipfs_datasets_py.logic.software_contracts.adversarial_assurance.remediation_contracts import (
    EvaluationPartition,
    EvaluationVerdict,
    PartitionEvaluationEvidence,
    RejectionReason,
    RemediationContractError,
    RemediationEvaluationReport,
    verify_evaluation_report_identity,
)

# ---------------------------------------------------------------------------
# Schema / interface constants (normative)
# ---------------------------------------------------------------------------

PARTITION_MUTANTS_INTERFACE: Final[str] = "partition_mutants@1"
QUALIFY_REMEDIATION_EVALUATION_INTERFACE: Final[str] = (
    "qualify_remediation_evaluation@1"
)
MUTANT_PARTITION_MEMBER_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.adversarial-assurance-mutant-partition-member@1"
)
MUTANT_PARTITION_PLAN_INTERFACE: Final[str] = "MutantPartitionPlan@1"
MUTANT_PARTITION_PLAN_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.adversarial-assurance-mutant-partition-plan@1"
)
REMEDIATION_QUALIFICATION_INTERFACE: Final[str] = "RemediationQualificationResult@1"
REMEDIATION_QUALIFICATION_SCHEMA: Final[str] = (
    "ipfs-datasets.software-contracts.adversarial-assurance-remediation-qualification@1"
)
HELD_OUT_POLICY_EVIDENCE: Final[str] = "aae/held-out-policy@1"

GENERATOR_ID: Final[str] = "held_out_policy"
GENERATOR_VERSION: Final[str] = "1.0.0"

MAX_TEXT_CHARS: Final[int] = 16_384
MAX_MUTANTS: Final[int] = 4_096
MAX_CID_LIST: Final[int] = 4_096
MAX_ID_LIST: Final[int] = 4_096
MAX_TOKEN_LIST: Final[int] = 256
MAX_REASONS: Final[int] = 64
MAX_METADATA_KEYS: Final[int] = 64
MAX_BASIS_POINTS: Final[int] = 10_000
MAX_COST_BP: Final[int] = 1_000_000
MAX_SEED: Final[int] = 2**63 - 1
DEFAULT_DEVELOPMENT_RATIO_BP: Final[int] = 3_000
DEFAULT_HELD_OUT_RATIO_BP: Final[int] = 7_000
DEFAULT_MAX_COST_DELTA_BP: Final[int] = 1_000

_TOKEN_RE: Final[re.Pattern[str]] = re.compile(r"^[a-z][a-z0-9_.:/+-]{0,127}$")

# Mutant corpus partitions (plan §10): diagnosis / development / held-out.
MUTANT_CORPUS_PARTITIONS: Final[tuple[str, ...]] = (
    EvaluationPartition.DIAGNOSIS.value,
    EvaluationPartition.DEVELOPMENT.value,
    EvaluationPartition.HELD_OUT.value,
)

# Evaluation evidence required to qualify a remediation (plan §10 + AAE-033).
REQUIRED_EVALUATION_PARTITIONS: Final[tuple[str, ...]] = (
    EvaluationPartition.UNMUTATED.value,
    EvaluationPartition.DIAGNOSIS.value,
    EvaluationPartition.DEVELOPMENT.value,
    EvaluationPartition.HELD_OUT.value,
    EvaluationPartition.UNRELATED.value,
    EvaluationPartition.PERFORMANCE_COST.value,
    EvaluationPartition.FALSE_POSITIVE.value,
    EvaluationPartition.OVERCONSTRAINT.value,
    EvaluationPartition.REGRESSION.value,
    EvaluationPartition.SAFETY.value,
)

# Rejection reasons that permanently block qualification (fail closed).
_HARD_BLOCK_REASONS: Final[frozenset[str]] = frozenset(
    {
        RejectionReason.REGRESSION.value,
        RejectionReason.OVERCONSTRAINT.value,
        RejectionReason.OVERFIT_IMPLEMENTATION_ASSERTION.value,
        RejectionReason.FLAKE.value,
        RejectionReason.MOCK_BYPASS.value,
        RejectionReason.SAFETY_WEAKENING.value,
        RejectionReason.IMPOSSIBLE_CORRECT_BEHAVIOR.value,
        RejectionReason.UNAPPROVED_COST_INCREASE.value,
        RejectionReason.MISSING_REQUIREMENT_PROVENANCE.value,
        RejectionReason.MISSING_NONVACUITY.value,
        RejectionReason.SELF_PROMOTION.value,
        RejectionReason.HELD_OUT_FAILURE.value,
        RejectionReason.FALSE_POSITIVE.value,
        RejectionReason.UNRELATED_BEHAVIOR_BROKEN.value,
        RejectionReason.DIAGNOSIS_NOT_KILLED.value,
        RejectionReason.UNMUTATED_SUITE_FAILED.value,
    }
)


class HeldOutPolicyError(AssuranceBaseError):
    """Raised when held-out partition or qualification inputs are unsafe."""


class MutantCorpusPartition(str, Enum):
    """Closed mutant corpus partition vocabulary (plan §10)."""

    DIAGNOSIS = "diagnosis"
    DEVELOPMENT = "development"
    HELD_OUT = "held_out"


class QualificationDisposition(str, Enum):
    """Closed qualification disposition for remediation evaluation."""

    QUALIFIED = "qualified"
    REJECTED = "rejected"
    INCONCLUSIVE = "inconclusive"
    HUMAN_REVIEW_REQUIRED = "human_review_required"


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _text(value: Any, name: str, *, empty: bool = False, maximum: int = MAX_TEXT_CHARS) -> str:
    if type(value) is not str or (not empty and not value):
        raise HeldOutPolicyError(f"{name} must be a nonempty string")
    if value != value.strip() or unicodedata.normalize("NFC", value) != value:
        raise HeldOutPolicyError(f"{name} must be trimmed NFC text")
    if len(value) > maximum or any(not char.isprintable() for char in value):
        raise HeldOutPolicyError(f"{name} contains invalid text")
    return value


def _optional_text(value: Any, name: str) -> str | None:
    if value is None:
        return None
    return _text(value, name)


def _bool(value: Any, name: str) -> bool:
    if type(value) is not bool:
        raise HeldOutPolicyError(f"{name} must be a boolean")
    return value


def _token(value: Any, name: str) -> str:
    text = _text(value, name)
    if _TOKEN_RE.fullmatch(text) is None:
        raise HeldOutPolicyError(
            f"{name} must be a lowercase token matching {_TOKEN_RE.pattern}"
        )
    return text


def _cid(value: Any, name: str) -> str:
    try:
        return validate_cid(value)
    except Exception as exc:
        raise HeldOutPolicyError(f"{name} must be a valid CID") from exc


def _optional_cid(value: Any, name: str) -> str | None:
    if value is None:
        return None
    return _cid(value, name)


def _enum(value: Any, enum_type: type[Enum], name: str) -> str:
    try:
        return enum_type(value).value
    except (TypeError, ValueError) as exc:
        raise HeldOutPolicyError(f"{name} has unsupported value {value!r}") from exc


def _nonneg_int(value: Any, name: str, *, maximum: int | None = None) -> int:
    if type(value) is not int or isinstance(value, bool) or value < 0:
        raise HeldOutPolicyError(f"{name} must be a nonnegative integer")
    if maximum is not None and value > maximum:
        raise HeldOutPolicyError(f"{name} exceeds maximum {maximum}")
    return value


def _basis_points(value: Any, name: str) -> int:
    return _nonneg_int(value, name, maximum=MAX_BASIS_POINTS)


def _freeze_structured(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {key: _freeze_structured(item) for key, item in value.items()}
        )
    if isinstance(value, list):
        return tuple(_freeze_structured(item) for item in value)
    return value


def _thaw_structured(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw_structured(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_structured(item) for item in value]
    return value


def _require_structured(value: Any, name: str) -> Any:
    thawed = _thaw_structured(value)
    try:
        validate_structured_value(thawed, path=name)
    except Exception as exc:
        raise HeldOutPolicyError(
            f"{name} must be strict DAG-JSON without floats or host types"
        ) from exc
    reject_private_model_authority_and_host_fallbacks(thawed, path=name)
    return thawed


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise HeldOutPolicyError(f"{name} must be a mapping")
    if len(value) > MAX_METADATA_KEYS:
        raise HeldOutPolicyError(f"{name} exceeds maximum key count")
    return _freeze_structured(_require_structured(dict(value), name))


def _closed(data: Mapping[str, Any], fields: frozenset[str], name: str) -> dict[str, Any]:
    if not isinstance(data, Mapping):
        raise HeldOutPolicyError(f"{name} must be a mapping")
    actual = set(data)
    if actual != fields:
        raise HeldOutPolicyError(
            f"{name} fields must be exactly {sorted(fields)}, got {sorted(actual)}"
        )
    return dict(data)


def _unique_sorted_tokens(
    values: Iterable[Any],
    name: str,
    *,
    maximum: int = MAX_TOKEN_LIST,
) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple)):
        raise HeldOutPolicyError(f"{name} must be a list")
    ordered = tuple(sorted(_token(value, name) for value in values))
    if len(ordered) > maximum:
        raise HeldOutPolicyError(f"{name} exceeds maximum length")
    if len(ordered) != len(set(ordered)):
        raise HeldOutPolicyError(f"{name} must not contain duplicates")
    return ordered


def _unique_sorted_cids(
    values: Iterable[Any],
    name: str,
    *,
    maximum: int = MAX_CID_LIST,
) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple)):
        raise HeldOutPolicyError(f"{name} must be a list")
    ordered = tuple(sorted(_cid(value, name) for value in values))
    if len(ordered) > maximum:
        raise HeldOutPolicyError(f"{name} exceeds maximum length")
    if len(ordered) != len(set(ordered)):
        raise HeldOutPolicyError(f"{name} must not contain duplicates")
    return ordered


def _unique_sorted_enums(
    values: Iterable[Any],
    enum_type: type[Enum],
    name: str,
    *,
    maximum: int = MAX_REASONS,
) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple)):
        raise HeldOutPolicyError(f"{name} must be a list")
    ordered = tuple(sorted(_enum(value, enum_type, name) for value in values))
    if len(ordered) > maximum:
        raise HeldOutPolicyError(f"{name} exceeds maximum length")
    if len(ordered) != len(set(ordered)):
        raise HeldOutPolicyError(f"{name} must not contain duplicates")
    return ordered


def _header(value: Any, name: str = "header") -> AssuranceArtifactHeader:
    if isinstance(value, AssuranceArtifactHeader):
        return value
    if isinstance(value, Mapping):
        return AssuranceArtifactHeader.from_dict(value)
    raise HeldOutPolicyError(f"{name} must be AssuranceArtifactHeader or mapping")


def _relatedness_key(
    *,
    relatedness_key: str | None,
    operator_id: str | None,
    target_id: str | None,
    mutant_id: str,
) -> str:
    if relatedness_key is not None:
        return _token(relatedness_key, "relatedness_key")
    if operator_id and target_id:
        return _token(f"{operator_id}+{target_id}", "relatedness_key")
    if operator_id:
        return _token(operator_id, "relatedness_key")
    if target_id:
        return _token(target_id, "relatedness_key")
    return _token(mutant_id, "relatedness_key")


def _partition_bucket(
    *,
    partition_seed: int,
    campaign_id: str,
    mutant_id: str,
    relatedness_key: str,
) -> int:
    """Return a stable [0, MAX_BASIS_POINTS) bucket for deterministic assignment."""

    material = "\x1f".join(
        (
            "aae-held-out-partition@1",
            str(partition_seed),
            campaign_id,
            mutant_id,
            relatedness_key,
        )
    ).encode("utf-8")
    digest = blake2b(material, digest_size=8).digest()
    value = int.from_bytes(digest, "big")
    return value % MAX_BASIS_POINTS


# ---------------------------------------------------------------------------
# Durable models
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MutantPartitionMember:
    """One mutant identity sealed into a corpus partition.

    Schema: ``MutantPartitionMember@1``
    """

    mutant_id: str
    partition: MutantCorpusPartition | str
    relatedness_key: str
    used_for_candidate_generation: bool = False
    candidate_cid: str | None = None
    operator_id: str | None = None
    target_id: str | None = None
    notes: str | None = None

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "mutant_id",
            "partition",
            "relatedness_key",
            "used_for_candidate_generation",
            "candidate_cid",
            "operator_id",
            "target_id",
            "notes",
            "member_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "mutant_id", _token(self.mutant_id, "mutant_id"))
        object.__setattr__(
            self,
            "partition",
            _enum(self.partition, MutantCorpusPartition, "partition"),
        )
        object.__setattr__(
            self,
            "relatedness_key",
            _token(self.relatedness_key, "relatedness_key"),
        )
        object.__setattr__(
            self,
            "used_for_candidate_generation",
            _bool(
                self.used_for_candidate_generation,
                "used_for_candidate_generation",
            ),
        )
        object.__setattr__(
            self,
            "candidate_cid",
            _optional_cid(self.candidate_cid, "candidate_cid"),
        )
        object.__setattr__(
            self,
            "operator_id",
            None if self.operator_id is None else _token(self.operator_id, "operator_id"),
        )
        object.__setattr__(
            self,
            "target_id",
            None if self.target_id is None else _token(self.target_id, "target_id"),
        )
        object.__setattr__(self, "notes", _optional_text(self.notes, "notes"))
        if (
            self.used_for_candidate_generation
            and self.partition == MutantCorpusPartition.HELD_OUT.value
        ):
            raise HeldOutPolicyError(
                "mutants used for candidate generation must not be assigned "
                "to held_out (partition leakage)"
            )

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": MUTANT_PARTITION_MEMBER_SCHEMA,
            "mutant_id": self.mutant_id,
            "partition": self.partition,
            "relatedness_key": self.relatedness_key,
            "used_for_candidate_generation": self.used_for_candidate_generation,
            "candidate_cid": self.candidate_cid,
            "operator_id": self.operator_id,
            "target_id": self.target_id,
            "notes": self.notes,
        }

    @property
    def member_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        payload = self.identity_payload()
        payload["member_cid"] = self.member_cid
        return payload

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "MutantPartitionMember":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("member_cid")
        if payload.pop("schema") != MUTANT_PARTITION_MEMBER_SCHEMA:
            raise HeldOutPolicyError(
                "unsupported MutantPartitionMember schema version"
            )
        result = cls(
            mutant_id=payload["mutant_id"],
            partition=payload["partition"],
            relatedness_key=payload["relatedness_key"],
            used_for_candidate_generation=payload["used_for_candidate_generation"],
            candidate_cid=payload["candidate_cid"],
            operator_id=payload["operator_id"],
            target_id=payload["target_id"],
            notes=payload["notes"],
        )
        if claimed != result.member_cid:
            raise HeldOutPolicyError(
                "MutantPartitionMember member_cid identity mismatch"
            )
        return result


def _normalize_member(
    value: Any,
    name: str = "member",
) -> MutantPartitionMember:
    if isinstance(value, MutantPartitionMember):
        return value
    if isinstance(value, Mapping):
        # Accept raw partition input without member_cid (construction path).
        if "member_cid" in value and "schema" in value:
            return MutantPartitionMember.from_dict(value)
        data = dict(value)
        mutant_id = _token(data.get("mutant_id"), "mutant_id")
        operator_id = data.get("operator_id")
        target_id = data.get("target_id")
        if operator_id is not None:
            operator_id = _token(operator_id, "operator_id")
        if target_id is not None:
            target_id = _token(target_id, "target_id")
        relatedness = _relatedness_key(
            relatedness_key=data.get("relatedness_key"),
            operator_id=operator_id,
            target_id=target_id,
            mutant_id=mutant_id,
        )
        partition = data.get("partition")
        if partition is None:
            raise HeldOutPolicyError(f"{name}.partition is required")
        return MutantPartitionMember(
            mutant_id=mutant_id,
            partition=partition,
            relatedness_key=relatedness,
            used_for_candidate_generation=_bool(
                data.get("used_for_candidate_generation", False),
                "used_for_candidate_generation",
            ),
            candidate_cid=data.get("candidate_cid"),
            operator_id=operator_id,
            target_id=target_id,
            notes=data.get("notes"),
        )
    raise HeldOutPolicyError(f"{name} must be MutantPartitionMember or mapping")


@dataclass(frozen=True, slots=True)
class MutantPartitionPlan:
    """Deterministic leakage-resistant mutant corpus partition plan.

    Interface: ``MutantPartitionPlan@1``

    Seals diagnosis, development, and held-out membership with campaign seed
    provenance. Pairwise disjointness and candidate-generation fencing are
    mandatory.
    """

    header: AssuranceArtifactHeader
    plan_id: str
    campaign_id: str
    partition_seed: int
    diagnosis_mutant_ids: Sequence[str]
    development_mutant_ids: Sequence[str]
    held_out_mutant_ids: Sequence[str]
    members: Sequence[MutantPartitionMember | Mapping[str, Any]]
    development_ratio_bp: int = DEFAULT_DEVELOPMENT_RATIO_BP
    held_out_ratio_bp: int = DEFAULT_HELD_OUT_RATIO_BP
    require_held_out: bool = True
    leakage_resistant: bool = True
    notes: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "interface_id",
            "header",
            "plan_id",
            "campaign_id",
            "partition_seed",
            "diagnosis_mutant_ids",
            "development_mutant_ids",
            "held_out_mutant_ids",
            "members",
            "development_ratio_bp",
            "held_out_ratio_bp",
            "require_held_out",
            "leakage_resistant",
            "notes",
            "metadata",
            "plan_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "header", _header(self.header))
        if self.header.artifact_kind != "mutant_partition_plan":
            raise HeldOutPolicyError(
                "header.artifact_kind must be mutant_partition_plan"
            )
        object.__setattr__(self, "plan_id", _token(self.plan_id, "plan_id"))
        object.__setattr__(
            self, "campaign_id", _token(self.campaign_id, "campaign_id")
        )
        object.__setattr__(
            self,
            "partition_seed",
            _nonneg_int(self.partition_seed, "partition_seed", maximum=MAX_SEED),
        )
        diagnosis = _unique_sorted_tokens(
            list(self.diagnosis_mutant_ids),
            "diagnosis_mutant_ids",
            maximum=MAX_ID_LIST,
        )
        development = _unique_sorted_tokens(
            list(self.development_mutant_ids),
            "development_mutant_ids",
            maximum=MAX_ID_LIST,
        )
        held_out = _unique_sorted_tokens(
            list(self.held_out_mutant_ids),
            "held_out_mutant_ids",
            maximum=MAX_ID_LIST,
        )
        if not diagnosis:
            raise HeldOutPolicyError("diagnosis_mutant_ids must not be empty")
        diagnosis_set = set(diagnosis)
        development_set = set(development)
        held_out_set = set(held_out)
        if (
            diagnosis_set & development_set
            or diagnosis_set & held_out_set
            or development_set & held_out_set
        ):
            raise HeldOutPolicyError(
                "diagnosis, development, and held_out mutant identity sets "
                "must be pairwise disjoint (partition leakage)"
            )
        object.__setattr__(self, "diagnosis_mutant_ids", diagnosis)
        object.__setattr__(self, "development_mutant_ids", development)
        object.__setattr__(self, "held_out_mutant_ids", held_out)

        if not isinstance(self.members, (list, tuple)):
            raise HeldOutPolicyError("members must be a list")
        if len(self.members) > MAX_MUTANTS:
            raise HeldOutPolicyError("members exceeds maximum length")
        sealed_members = tuple(
            _normalize_member(item, f"members[{index}]")
            for index, item in enumerate(self.members)
        )
        # Stable member order by mutant_id for deterministic identity.
        sealed_members = tuple(sorted(sealed_members, key=lambda item: item.mutant_id))
        member_ids = [item.mutant_id for item in sealed_members]
        if len(member_ids) != len(set(member_ids)):
            raise HeldOutPolicyError("members must not contain duplicate mutant_id")
        expected_ids = set(diagnosis) | set(development) | set(held_out)
        actual_ids = set(member_ids)
        if actual_ids != expected_ids:
            raise HeldOutPolicyError(
                "members must cover exactly the union of diagnosis, "
                "development, and held_out mutant ids"
            )
        for member in sealed_members:
            if member.partition == MutantCorpusPartition.DIAGNOSIS.value:
                if member.mutant_id not in diagnosis:
                    raise HeldOutPolicyError(
                        f"member {member.mutant_id!r} partition diagnosis "
                        "is not listed in diagnosis_mutant_ids"
                    )
            elif member.partition == MutantCorpusPartition.DEVELOPMENT.value:
                if member.mutant_id not in development:
                    raise HeldOutPolicyError(
                        f"member {member.mutant_id!r} partition development "
                        "is not listed in development_mutant_ids"
                    )
            elif member.partition == MutantCorpusPartition.HELD_OUT.value:
                if member.mutant_id not in held_out:
                    raise HeldOutPolicyError(
                        f"member {member.mutant_id!r} partition held_out "
                        "is not listed in held_out_mutant_ids"
                    )
            if (
                member.used_for_candidate_generation
                and member.partition == MutantCorpusPartition.HELD_OUT.value
            ):
                raise HeldOutPolicyError(
                    "candidate-generating mutants must not appear in held_out"
                )
        object.__setattr__(self, "members", sealed_members)

        dev_ratio = _basis_points(self.development_ratio_bp, "development_ratio_bp")
        hold_ratio = _basis_points(self.held_out_ratio_bp, "held_out_ratio_bp")
        if dev_ratio + hold_ratio != MAX_BASIS_POINTS:
            raise HeldOutPolicyError(
                "development_ratio_bp + held_out_ratio_bp must equal 10000"
            )
        object.__setattr__(self, "development_ratio_bp", dev_ratio)
        object.__setattr__(self, "held_out_ratio_bp", hold_ratio)
        require_held = _bool(self.require_held_out, "require_held_out")
        object.__setattr__(self, "require_held_out", require_held)
        if require_held and not held_out:
            raise HeldOutPolicyError(
                "require_held_out=true forbids an empty held_out partition"
            )
        leakage = _bool(self.leakage_resistant, "leakage_resistant")
        if not leakage:
            raise HeldOutPolicyError("leakage_resistant must be true")
        object.__setattr__(self, "leakage_resistant", True)
        object.__setattr__(self, "notes", _optional_text(self.notes, "notes"))
        object.__setattr__(self, "metadata", _mapping(self.metadata, "metadata"))

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": MUTANT_PARTITION_PLAN_SCHEMA,
            "interface_id": MUTANT_PARTITION_PLAN_INTERFACE,
            "header": self.header.identity_payload(),
            "plan_id": self.plan_id,
            "campaign_id": self.campaign_id,
            "partition_seed": self.partition_seed,
            "diagnosis_mutant_ids": list(self.diagnosis_mutant_ids),
            "development_mutant_ids": list(self.development_mutant_ids),
            "held_out_mutant_ids": list(self.held_out_mutant_ids),
            "members": [item.identity_payload() for item in self.members],
            "development_ratio_bp": self.development_ratio_bp,
            "held_out_ratio_bp": self.held_out_ratio_bp,
            "require_held_out": self.require_held_out,
            "leakage_resistant": self.leakage_resistant,
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
        }

    @property
    def plan_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": MUTANT_PARTITION_PLAN_SCHEMA,
            "interface_id": MUTANT_PARTITION_PLAN_INTERFACE,
            "header": self.header.to_dict(),
            "plan_id": self.plan_id,
            "campaign_id": self.campaign_id,
            "partition_seed": self.partition_seed,
            "diagnosis_mutant_ids": list(self.diagnosis_mutant_ids),
            "development_mutant_ids": list(self.development_mutant_ids),
            "held_out_mutant_ids": list(self.held_out_mutant_ids),
            "members": [item.to_dict() for item in self.members],
            "development_ratio_bp": self.development_ratio_bp,
            "held_out_ratio_bp": self.held_out_ratio_bp,
            "require_held_out": self.require_held_out,
            "leakage_resistant": self.leakage_resistant,
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
            "plan_cid": self.plan_cid,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "MutantPartitionPlan":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("plan_cid")
        if payload.pop("schema") != MUTANT_PARTITION_PLAN_SCHEMA:
            raise HeldOutPolicyError(
                "unsupported MutantPartitionPlan schema version"
            )
        if payload.pop("interface_id") != MUTANT_PARTITION_PLAN_INTERFACE:
            raise HeldOutPolicyError(
                "unsupported MutantPartitionPlan interface_id"
            )
        result = cls(
            header=payload["header"],
            plan_id=payload["plan_id"],
            campaign_id=payload["campaign_id"],
            partition_seed=payload["partition_seed"],
            diagnosis_mutant_ids=payload["diagnosis_mutant_ids"],
            development_mutant_ids=payload["development_mutant_ids"],
            held_out_mutant_ids=payload["held_out_mutant_ids"],
            members=payload["members"],
            development_ratio_bp=payload["development_ratio_bp"],
            held_out_ratio_bp=payload["held_out_ratio_bp"],
            require_held_out=payload["require_held_out"],
            leakage_resistant=payload["leakage_resistant"],
            notes=payload["notes"],
            metadata=payload["metadata"],
        )
        if claimed != result.plan_cid:
            raise HeldOutPolicyError(
                "MutantPartitionPlan plan_cid identity mismatch"
            )
        return result

    def ids_for(self, partition: MutantCorpusPartition | str) -> tuple[str, ...]:
        """Return sorted mutant ids for a corpus partition."""

        value = _enum(partition, MutantCorpusPartition, "partition")
        if value == MutantCorpusPartition.DIAGNOSIS.value:
            return self.diagnosis_mutant_ids
        if value == MutantCorpusPartition.DEVELOPMENT.value:
            return self.development_mutant_ids
        return self.held_out_mutant_ids

    def membership(self) -> Mapping[str, str]:
        """Return mutant_id → partition mapping (immutable)."""

        return MappingProxyType(
            {item.mutant_id: item.partition for item in self.members}
        )


@dataclass(frozen=True, slots=True)
class RemediationQualificationResult:
    """Sealed qualification of a held-out remediation evaluation.

    Interface: ``RemediationQualificationResult@1``

    Records whether unmutated, diagnosis, development, held-out, unrelated,
    cost, false-positive, overconstraint, regression, and safety evidence
    jointly qualify the remediation. Never mutates production policy.
    """

    header: AssuranceArtifactHeader
    result_id: str
    evaluation_report_cid: str
    disposition: QualificationDisposition | str
    verdict: EvaluationVerdict | str
    partition_plan_cid: str | None
    required_partitions_present: bool
    unmutated_suite_passed: bool
    diagnosis_killed: bool
    development_killed: bool
    held_out_killed: bool
    unrelated_behavior_preserved: bool
    safety_preserved: bool
    regression_detected: bool
    overconstraint_detected: bool
    false_positive_detected: bool
    cost_delta_basis_points: int
    cost_within_budget: bool
    partition_leakage_detected: bool
    production_policy_changed: bool
    rejection_reasons: Sequence[RejectionReason | str] = ()
    missing_partitions: Sequence[str] = ()
    failed_partitions: Sequence[str] = ()
    notes: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema",
            "interface_id",
            "header",
            "result_id",
            "evaluation_report_cid",
            "disposition",
            "verdict",
            "partition_plan_cid",
            "required_partitions_present",
            "unmutated_suite_passed",
            "diagnosis_killed",
            "development_killed",
            "held_out_killed",
            "unrelated_behavior_preserved",
            "safety_preserved",
            "regression_detected",
            "overconstraint_detected",
            "false_positive_detected",
            "cost_delta_basis_points",
            "cost_within_budget",
            "partition_leakage_detected",
            "production_policy_changed",
            "rejection_reasons",
            "missing_partitions",
            "failed_partitions",
            "notes",
            "metadata",
            "result_cid",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "header", _header(self.header))
        if self.header.artifact_kind != "remediation_qualification_result":
            raise HeldOutPolicyError(
                "header.artifact_kind must be remediation_qualification_result"
            )
        object.__setattr__(self, "result_id", _token(self.result_id, "result_id"))
        object.__setattr__(
            self,
            "evaluation_report_cid",
            _cid(self.evaluation_report_cid, "evaluation_report_cid"),
        )
        disposition = _enum(
            self.disposition, QualificationDisposition, "disposition"
        )
        object.__setattr__(self, "disposition", disposition)
        verdict = _enum(self.verdict, EvaluationVerdict, "verdict")
        object.__setattr__(self, "verdict", verdict)
        object.__setattr__(
            self,
            "partition_plan_cid",
            _optional_cid(self.partition_plan_cid, "partition_plan_cid"),
        )
        for flag_name in (
            "required_partitions_present",
            "unmutated_suite_passed",
            "diagnosis_killed",
            "development_killed",
            "held_out_killed",
            "unrelated_behavior_preserved",
            "safety_preserved",
            "regression_detected",
            "overconstraint_detected",
            "false_positive_detected",
            "cost_within_budget",
            "partition_leakage_detected",
            "production_policy_changed",
        ):
            object.__setattr__(
                self, flag_name, _bool(getattr(self, flag_name), flag_name)
            )
        if self.production_policy_changed:
            raise HeldOutPolicyError(
                "production_policy_changed must be false; held-out policy "
                "never mutates production policy"
            )
        object.__setattr__(
            self,
            "cost_delta_basis_points",
            _nonneg_int(
                self.cost_delta_basis_points,
                "cost_delta_basis_points",
                maximum=MAX_COST_BP,
            ),
        )
        reasons = _unique_sorted_enums(
            list(self.rejection_reasons),
            RejectionReason,
            "rejection_reasons",
        )
        missing = _unique_sorted_tokens(
            list(self.missing_partitions),
            "missing_partitions",
            maximum=len(REQUIRED_EVALUATION_PARTITIONS),
        )
        failed = _unique_sorted_tokens(
            list(self.failed_partitions),
            "failed_partitions",
            maximum=len(REQUIRED_EVALUATION_PARTITIONS),
        )
        for item in missing:
            if item not in REQUIRED_EVALUATION_PARTITIONS:
                raise HeldOutPolicyError(
                    f"missing_partitions contains non-required partition {item!r}"
                )
        for item in failed:
            try:
                EvaluationPartition(item)
            except ValueError as exc:
                raise HeldOutPolicyError(
                    f"failed_partitions contains unknown partition {item!r}"
                ) from exc

        if disposition == QualificationDisposition.QUALIFIED.value:
            if reasons or missing or failed:
                raise HeldOutPolicyError(
                    "qualified disposition forbids rejection_reasons, "
                    "missing_partitions, and failed_partitions"
                )
            if verdict != EvaluationVerdict.QUALIFIED.value:
                raise HeldOutPolicyError(
                    "qualified disposition requires verdict=qualified"
                )
            if not self.required_partitions_present:
                raise HeldOutPolicyError(
                    "qualified disposition requires required_partitions_present"
                )
            if not self.unmutated_suite_passed:
                raise HeldOutPolicyError(
                    "qualified disposition requires unmutated_suite_passed"
                )
            if not self.diagnosis_killed or not self.held_out_killed:
                raise HeldOutPolicyError(
                    "qualified disposition requires diagnosis and held-out kills"
                )
            if not self.unrelated_behavior_preserved or not self.safety_preserved:
                raise HeldOutPolicyError(
                    "qualified disposition requires unrelated and safety preservation"
                )
            if (
                self.regression_detected
                or self.overconstraint_detected
                or self.false_positive_detected
                or self.partition_leakage_detected
            ):
                raise HeldOutPolicyError(
                    "qualified disposition forbids regression, overconstraint, "
                    "false_positive, and partition leakage"
                )
            if not self.cost_within_budget:
                raise HeldOutPolicyError(
                    "qualified disposition requires cost_within_budget"
                )
        else:
            if not reasons and not missing and not failed:
                raise HeldOutPolicyError(
                    "non-qualified disposition requires rejection_reasons, "
                    "missing_partitions, or failed_partitions"
                )
            if verdict == EvaluationVerdict.QUALIFIED.value:
                raise HeldOutPolicyError(
                    "non-qualified disposition forbids verdict=qualified"
                )

        object.__setattr__(self, "rejection_reasons", reasons)
        object.__setattr__(self, "missing_partitions", missing)
        object.__setattr__(self, "failed_partitions", failed)
        object.__setattr__(self, "notes", _optional_text(self.notes, "notes"))
        object.__setattr__(self, "metadata", _mapping(self.metadata, "metadata"))

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema": REMEDIATION_QUALIFICATION_SCHEMA,
            "interface_id": REMEDIATION_QUALIFICATION_INTERFACE,
            "header": self.header.identity_payload(),
            "result_id": self.result_id,
            "evaluation_report_cid": self.evaluation_report_cid,
            "disposition": self.disposition,
            "verdict": self.verdict,
            "partition_plan_cid": self.partition_plan_cid,
            "required_partitions_present": self.required_partitions_present,
            "unmutated_suite_passed": self.unmutated_suite_passed,
            "diagnosis_killed": self.diagnosis_killed,
            "development_killed": self.development_killed,
            "held_out_killed": self.held_out_killed,
            "unrelated_behavior_preserved": self.unrelated_behavior_preserved,
            "safety_preserved": self.safety_preserved,
            "regression_detected": self.regression_detected,
            "overconstraint_detected": self.overconstraint_detected,
            "false_positive_detected": self.false_positive_detected,
            "cost_delta_basis_points": self.cost_delta_basis_points,
            "cost_within_budget": self.cost_within_budget,
            "partition_leakage_detected": self.partition_leakage_detected,
            "production_policy_changed": self.production_policy_changed,
            "rejection_reasons": list(self.rejection_reasons),
            "missing_partitions": list(self.missing_partitions),
            "failed_partitions": list(self.failed_partitions),
            "notes": self.notes,
            "metadata": _thaw_structured(self.metadata),
        }

    @property
    def result_cid(self) -> str:
        return cid_for_structured(self.identity_payload())

    def to_dict(self) -> dict[str, Any]:
        payload = self.identity_payload()
        payload["header"] = self.header.to_dict()
        payload["result_cid"] = self.result_cid
        return payload

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RemediationQualificationResult":
        payload = _closed(data, cls._FIELDS, cls.__name__)
        claimed = payload.pop("result_cid")
        if payload.pop("schema") != REMEDIATION_QUALIFICATION_SCHEMA:
            raise HeldOutPolicyError(
                "unsupported RemediationQualificationResult schema version"
            )
        if payload.pop("interface_id") != REMEDIATION_QUALIFICATION_INTERFACE:
            raise HeldOutPolicyError(
                "unsupported RemediationQualificationResult interface_id"
            )
        result = cls(
            header=payload["header"],
            result_id=payload["result_id"],
            evaluation_report_cid=payload["evaluation_report_cid"],
            disposition=payload["disposition"],
            verdict=payload["verdict"],
            partition_plan_cid=payload["partition_plan_cid"],
            required_partitions_present=payload["required_partitions_present"],
            unmutated_suite_passed=payload["unmutated_suite_passed"],
            diagnosis_killed=payload["diagnosis_killed"],
            development_killed=payload["development_killed"],
            held_out_killed=payload["held_out_killed"],
            unrelated_behavior_preserved=payload["unrelated_behavior_preserved"],
            safety_preserved=payload["safety_preserved"],
            regression_detected=payload["regression_detected"],
            overconstraint_detected=payload["overconstraint_detected"],
            false_positive_detected=payload["false_positive_detected"],
            cost_delta_basis_points=payload["cost_delta_basis_points"],
            cost_within_budget=payload["cost_within_budget"],
            partition_leakage_detected=payload["partition_leakage_detected"],
            production_policy_changed=payload["production_policy_changed"],
            rejection_reasons=payload["rejection_reasons"],
            missing_partitions=payload["missing_partitions"],
            failed_partitions=payload["failed_partitions"],
            notes=payload["notes"],
            metadata=payload["metadata"],
        )
        if claimed != result.result_cid:
            raise HeldOutPolicyError(
                "RemediationQualificationResult result_cid identity mismatch"
            )
        return result


# ---------------------------------------------------------------------------
# Normalization and header helpers
# ---------------------------------------------------------------------------


def _normalize_partition_plan(
    value: MutantPartitionPlan | Mapping[str, Any],
) -> MutantPartitionPlan:
    if isinstance(value, MutantPartitionPlan):
        return value
    if isinstance(value, Mapping):
        return MutantPartitionPlan.from_dict(value)
    raise HeldOutPolicyError(
        "partition_plan must be MutantPartitionPlan or mapping"
    )


def _normalize_evaluation_report(
    value: RemediationEvaluationReport | Mapping[str, Any],
) -> RemediationEvaluationReport:
    if isinstance(value, RemediationEvaluationReport):
        sealed = value
    elif isinstance(value, Mapping):
        try:
            sealed = RemediationEvaluationReport.from_dict(value)
        except RemediationContractError as exc:
            raise HeldOutPolicyError(
                f"evaluation report schema/integrity failure: {exc}"
            ) from exc
    else:
        raise HeldOutPolicyError(
            "evaluation must be RemediationEvaluationReport or mapping"
        )
    try:
        verify_evaluation_report_identity(sealed)
    except RemediationContractError as exc:
        raise HeldOutPolicyError(
            f"evaluation report identity failure: {exc}"
        ) from exc
    return sealed


def _normalize_mutant_input(value: Any, index: int) -> dict[str, Any]:
    if isinstance(value, MutantPartitionMember):
        return {
            "mutant_id": value.mutant_id,
            "candidate_cid": value.candidate_cid,
            "operator_id": value.operator_id,
            "target_id": value.target_id,
            "relatedness_key": value.relatedness_key,
            "used_for_candidate_generation": value.used_for_candidate_generation,
            "notes": value.notes,
        }
    if not isinstance(value, Mapping):
        raise HeldOutPolicyError(
            f"mutants[{index}] must be a mapping or MutantPartitionMember"
        )
    data = dict(value)
    mutant_id = _token(data.get("mutant_id"), "mutant_id")
    operator_id = data.get("operator_id")
    target_id = data.get("target_id")
    if operator_id is not None:
        operator_id = _token(operator_id, "operator_id")
    if target_id is not None:
        target_id = _token(target_id, "target_id")
    relatedness = _relatedness_key(
        relatedness_key=data.get("relatedness_key"),
        operator_id=operator_id,
        target_id=target_id,
        mutant_id=mutant_id,
    )
    return {
        "mutant_id": mutant_id,
        "candidate_cid": _optional_cid(data.get("candidate_cid"), "candidate_cid"),
        "operator_id": operator_id,
        "target_id": target_id,
        "relatedness_key": relatedness,
        "used_for_candidate_generation": _bool(
            data.get("used_for_candidate_generation", False),
            "used_for_candidate_generation",
        ),
        "notes": _optional_text(data.get("notes"), "notes"),
    }


def _clone_header(
    base: AssuranceArtifactHeader,
    *,
    artifact_kind: str,
    interface_id: str,
) -> AssuranceArtifactHeader:
    versions = base.versions
    generator = versions.generator
    new_generator = type(generator)(
        generator_id=GENERATOR_ID,
        generator_version=GENERATOR_VERSION,
        interface_id=interface_id,
    )
    new_versions = type(versions)(
        operator_id=versions.operator_id,
        operator_version=versions.operator_version,
        campaign_policy_id=versions.campaign_policy_id,
        campaign_policy_version=versions.campaign_policy_version,
        generator=new_generator,
    )
    return AssuranceArtifactHeader(
        artifact_kind=artifact_kind,
        repository_id=base.repository_id,
        repository_state_cid=base.repository_state_cid,
        target_symbol_ids=tuple(base.target_symbol_ids),
        target_artifact_cids=tuple(base.target_artifact_cids),
        capsule_cids=tuple(base.capsule_cids),
        proof_unit_cids=tuple(base.proof_unit_cids),
        environment_cid=base.environment_cid,
        dependency_lock_cid=base.dependency_lock_cid,
        versions=new_versions,
        provenance=base.provenance,
        terminal_status=base.terminal_status,
        receipt_cids=tuple(base.receipt_cids),
        proof_cids=tuple(base.proof_cids),
        metadata=dict(base.metadata),
    )


def _evidence_by_partition(
    report: RemediationEvaluationReport,
) -> dict[str, PartitionEvaluationEvidence]:
    by_partition: dict[str, PartitionEvaluationEvidence] = {}
    for item in report.partition_evidence:
        if item.partition in by_partition:
            raise HeldOutPolicyError(
                f"duplicate partition_evidence for {item.partition!r}"
            )
        by_partition[item.partition] = item
    return by_partition


def _check_partition_alignment(
    report: RemediationEvaluationReport,
    plan: MutantPartitionPlan,
) -> tuple[bool, list[str]]:
    """Return (leakage_detected, reasons) for evaluation vs partition plan."""

    reasons: list[str] = []
    by_partition = _evidence_by_partition(report)
    membership = plan.membership()

    for corpus_partition in MUTANT_CORPUS_PARTITIONS:
        evidence = by_partition.get(corpus_partition)
        if evidence is None:
            continue
        allowed = set(plan.ids_for(corpus_partition))
        for mutant_id in evidence.mutant_ids:
            assigned = membership.get(mutant_id)
            if assigned is None:
                reasons.append(
                    f"evaluation mutant {mutant_id!r} is not in partition plan"
                )
                continue
            if assigned != corpus_partition:
                reasons.append(
                    f"mutant {mutant_id!r} evaluated under {corpus_partition!r} "
                    f"but plan assigns {assigned!r} (partition leakage)"
                )
            if mutant_id not in allowed:
                reasons.append(
                    f"mutant {mutant_id!r} not listed in plan {corpus_partition} ids"
                )
        # Held-out evidence must not include diagnosis or development members.
        if corpus_partition == MutantCorpusPartition.HELD_OUT.value:
            for mutant_id in evidence.mutant_ids:
                if mutant_id in plan.diagnosis_mutant_ids:
                    reasons.append(
                        f"diagnosis mutant {mutant_id!r} leaked into held_out evidence"
                    )
                if mutant_id in plan.development_mutant_ids:
                    reasons.append(
                        f"development mutant {mutant_id!r} leaked into held_out evidence"
                    )
                member = next(
                    (item for item in plan.members if item.mutant_id == mutant_id),
                    None,
                )
                if member is not None and member.used_for_candidate_generation:
                    reasons.append(
                        f"candidate-generating mutant {mutant_id!r} scored in held_out"
                    )

    return (bool(reasons), reasons)


def _map_failure_to_reasons(
    *,
    missing: Sequence[str],
    failed: Sequence[str],
    unmutated_suite_passed: bool,
    diagnosis_killed: bool,
    held_out_killed: bool,
    unrelated_behavior_preserved: bool,
    safety_preserved: bool,
    regression_detected: bool,
    overconstraint_detected: bool,
    false_positive_detected: bool,
    cost_within_budget: bool,
    partition_leakage_detected: bool,
    report_reasons: Sequence[str],
) -> list[str]:
    reasons: list[str] = []
    if missing:
        # Missing required evidence is treated as held-out failure / incomplete.
        reasons.append(RejectionReason.HELD_OUT_FAILURE.value)
    if not unmutated_suite_passed or EvaluationPartition.UNMUTATED.value in failed:
        reasons.append(RejectionReason.UNMUTATED_SUITE_FAILED.value)
    if not diagnosis_killed or EvaluationPartition.DIAGNOSIS.value in failed:
        reasons.append(RejectionReason.DIAGNOSIS_NOT_KILLED.value)
    if not held_out_killed or EvaluationPartition.HELD_OUT.value in failed:
        reasons.append(RejectionReason.HELD_OUT_FAILURE.value)
        # One-mutant overfit pattern: diagnosis pass without held-out kill.
        if diagnosis_killed and not held_out_killed:
            reasons.append(RejectionReason.OVERFIT_IMPLEMENTATION_ASSERTION.value)
    if (
        not unrelated_behavior_preserved
        or EvaluationPartition.UNRELATED.value in failed
    ):
        reasons.append(RejectionReason.UNRELATED_BEHAVIOR_BROKEN.value)
    if not safety_preserved or EvaluationPartition.SAFETY.value in failed:
        reasons.append(RejectionReason.SAFETY_WEAKENING.value)
    if regression_detected or EvaluationPartition.REGRESSION.value in failed:
        reasons.append(RejectionReason.REGRESSION.value)
    if (
        overconstraint_detected
        or EvaluationPartition.OVERCONSTRAINT.value in failed
    ):
        reasons.append(RejectionReason.OVERCONSTRAINT.value)
    if (
        false_positive_detected
        or EvaluationPartition.FALSE_POSITIVE.value in failed
    ):
        reasons.append(RejectionReason.FALSE_POSITIVE.value)
    if not cost_within_budget or EvaluationPartition.PERFORMANCE_COST.value in failed:
        reasons.append(RejectionReason.UNAPPROVED_COST_INCREASE.value)
    if partition_leakage_detected:
        reasons.append(RejectionReason.HELD_OUT_FAILURE.value)
        reasons.append(RejectionReason.OVERFIT_IMPLEMENTATION_ASSERTION.value)

    for reason in report_reasons:
        if reason in _HARD_BLOCK_REASONS:
            reasons.append(reason)

    # Stable unique order.
    return sorted(set(reasons))


def _select_verdict(
    *,
    disposition: str,
    reasons: Sequence[str],
) -> str:
    if disposition == QualificationDisposition.QUALIFIED.value:
        return EvaluationVerdict.QUALIFIED.value
    if RejectionReason.REGRESSION.value in reasons:
        return EvaluationVerdict.REGRESSION.value
    if RejectionReason.OVERCONSTRAINT.value in reasons:
        return EvaluationVerdict.OVERCONSTRAINT.value
    if RejectionReason.OVERFIT_IMPLEMENTATION_ASSERTION.value in reasons:
        return EvaluationVerdict.OVERFIT.value
    if RejectionReason.FLAKE.value in reasons:
        return EvaluationVerdict.FLAKY.value
    if RejectionReason.UNAPPROVED_COST_INCREASE.value in reasons:
        return EvaluationVerdict.COST_EXCEEDED.value
    if RejectionReason.SAFETY_WEAKENING.value in reasons:
        return EvaluationVerdict.SAFETY_WEAKENED.value
    if RejectionReason.SELF_PROMOTION.value in reasons:
        return EvaluationVerdict.REJECTED.value
    return EvaluationVerdict.REJECTED.value


# ---------------------------------------------------------------------------
# Public interfaces
# ---------------------------------------------------------------------------


def partition_mutants(
    mutants: Sequence[Mapping[str, Any] | MutantPartitionMember],
    diagnosis_mutant_ids: Sequence[str],
    *,
    header: AssuranceArtifactHeader | Mapping[str, Any],
    campaign_id: str = "default_campaign",
    partition_seed: int = 0,
    plan_id: str | None = None,
    development_ratio_bp: int = DEFAULT_DEVELOPMENT_RATIO_BP,
    held_out_ratio_bp: int = DEFAULT_HELD_OUT_RATIO_BP,
    require_held_out: bool = True,
    notes: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> MutantPartitionPlan:
    """Partition mutants into diagnosis, development, and held-out sets.

    Interface: ``partition_mutants@1``

    Assignment is deterministic for identical mutant identities, campaign id,
    seed, and ratios. Diagnosis members are fixed from
    ``diagnosis_mutant_ids``. Remaining mutants are bucketed into development
    or held-out via a content-stable blake2 digest. Candidate-generating
    mutants are fenced out of held-out.

    Plan signature: ``partition_mutants(mutants, diagnosis_mutant_ids, ...)``.
    """

    if not isinstance(mutants, (list, tuple)):
        raise HeldOutPolicyError("mutants must be a list")
    if len(mutants) == 0:
        raise HeldOutPolicyError("mutants must not be empty")
    if len(mutants) > MAX_MUTANTS:
        raise HeldOutPolicyError("mutants exceeds maximum length")

    sealed_header = _header(header)
    campaign = _token(campaign_id, "campaign_id")
    seed = _nonneg_int(partition_seed, "partition_seed", maximum=MAX_SEED)
    dev_ratio = _basis_points(development_ratio_bp, "development_ratio_bp")
    hold_ratio = _basis_points(held_out_ratio_bp, "held_out_ratio_bp")
    if dev_ratio + hold_ratio != MAX_BASIS_POINTS:
        raise HeldOutPolicyError(
            "development_ratio_bp + held_out_ratio_bp must equal 10000"
        )
    require_hold = _bool(require_held_out, "require_held_out")

    diagnosis = _unique_sorted_tokens(
        list(diagnosis_mutant_ids),
        "diagnosis_mutant_ids",
        maximum=MAX_ID_LIST,
    )
    if not diagnosis:
        raise HeldOutPolicyError("diagnosis_mutant_ids must not be empty")

    inputs = [_normalize_mutant_input(item, index) for index, item in enumerate(mutants)]
    by_id: dict[str, dict[str, Any]] = {}
    for item in inputs:
        mutant_id = item["mutant_id"]
        if mutant_id in by_id:
            raise HeldOutPolicyError(
                f"duplicate mutant_id {mutant_id!r} in mutants"
            )
        by_id[mutant_id] = item

    missing_diagnosis = [item for item in diagnosis if item not in by_id]
    if missing_diagnosis:
        raise HeldOutPolicyError(
            "diagnosis_mutant_ids must be a subset of mutants; missing "
            f"{missing_diagnosis}"
        )

    development: list[str] = []
    held_out: list[str] = []
    members: list[MutantPartitionMember] = []

    for mutant_id in diagnosis:
        item = by_id[mutant_id]
        members.append(
            MutantPartitionMember(
                mutant_id=mutant_id,
                partition=MutantCorpusPartition.DIAGNOSIS,
                relatedness_key=item["relatedness_key"],
                used_for_candidate_generation=item["used_for_candidate_generation"],
                candidate_cid=item["candidate_cid"],
                operator_id=item["operator_id"],
                target_id=item["target_id"],
                notes=item["notes"],
            )
        )

    remainder = sorted(mutant_id for mutant_id in by_id if mutant_id not in set(diagnosis))
    for mutant_id in remainder:
        item = by_id[mutant_id]
        # Candidate-generating mutants never score held-out promotion.
        if item["used_for_candidate_generation"]:
            assigned = MutantCorpusPartition.DEVELOPMENT.value
        else:
            bucket = _partition_bucket(
                partition_seed=seed,
                campaign_id=campaign,
                mutant_id=mutant_id,
                relatedness_key=item["relatedness_key"],
            )
            if bucket < dev_ratio:
                assigned = MutantCorpusPartition.DEVELOPMENT.value
            else:
                assigned = MutantCorpusPartition.HELD_OUT.value
        if assigned == MutantCorpusPartition.DEVELOPMENT.value:
            development.append(mutant_id)
        else:
            held_out.append(mutant_id)
        members.append(
            MutantPartitionMember(
                mutant_id=mutant_id,
                partition=assigned,
                relatedness_key=item["relatedness_key"],
                used_for_candidate_generation=item["used_for_candidate_generation"],
                candidate_cid=item["candidate_cid"],
                operator_id=item["operator_id"],
                target_id=item["target_id"],
                notes=item["notes"],
            )
        )

    if require_hold and not held_out:
        # Fail closed when corpus has non-diagnosis mutants but none landed in
        # held-out (e.g. all remainder flagged candidate-generating).
        if remainder:
            raise HeldOutPolicyError(
                "require_held_out=true but held_out partition is empty; "
                "refuse leakage-prone or candidate-generation-only corpora"
            )

    plan_header = _clone_header(
        sealed_header,
        artifact_kind="mutant_partition_plan",
        interface_id=PARTITION_MUTANTS_INTERFACE,
    )
    resolved_plan_id = (
        _token(plan_id, "plan_id")
        if plan_id is not None
        else _token(f"partition_{campaign}", "plan_id")
    )
    result_metadata: dict[str, Any] = {
        "generator_id": GENERATOR_ID,
        "generator_version": GENERATOR_VERSION,
        "evidence": HELD_OUT_POLICY_EVIDENCE,
        "interface_id": PARTITION_MUTANTS_INTERFACE,
        "production_policy_changed": False,
        "diagnosis_count": len(diagnosis),
        "development_count": len(development),
        "held_out_count": len(held_out),
    }
    if metadata:
        result_metadata.update(dict(metadata))
        reject_private_model_authority_and_host_fallbacks(
            result_metadata, path="metadata"
        )

    plan = MutantPartitionPlan(
        header=plan_header,
        plan_id=resolved_plan_id,
        campaign_id=campaign,
        partition_seed=seed,
        diagnosis_mutant_ids=diagnosis,
        development_mutant_ids=tuple(sorted(development)),
        held_out_mutant_ids=tuple(sorted(held_out)),
        members=tuple(members),
        development_ratio_bp=dev_ratio,
        held_out_ratio_bp=hold_ratio,
        require_held_out=require_hold,
        leakage_resistant=True,
        notes=_optional_text(notes, "notes"),
        metadata=result_metadata,
    )
    verify_mutant_partition_plan_identity(plan)
    assert_partition_leakage_free(plan)
    return plan


def qualify_remediation_evaluation(
    evaluation: RemediationEvaluationReport | Mapping[str, Any],
    *,
    partition_plan: MutantPartitionPlan | Mapping[str, Any] | None = None,
    max_cost_delta_bp: int = DEFAULT_MAX_COST_DELTA_BP,
    result_id: str | None = None,
    notes: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> RemediationQualificationResult:
    """Qualify a remediation evaluation against held-out policy requirements.

    Interface: ``qualify_remediation_evaluation@1``

    Requires sealed evidence for unmutated, diagnosis, development, held-out,
    unrelated, performance/cost, false-positive, overconstraint, regression,
    and safety partitions. Rejects regressions, overfit one-mutant fixes, mock
    bypass, safety weakening, and unapproved cost increases. Never changes
    production policy.

    Plan signature: ``qualify_remediation_evaluation(evaluation, ...)``.
    """

    report = _normalize_evaluation_report(evaluation)
    plan = (
        _normalize_partition_plan(partition_plan)
        if partition_plan is not None
        else None
    )
    max_cost = _nonneg_int(
        max_cost_delta_bp, "max_cost_delta_bp", maximum=MAX_COST_BP
    )

    by_partition = _evidence_by_partition(report)
    present = set(by_partition)
    missing = [
        partition
        for partition in REQUIRED_EVALUATION_PARTITIONS
        if partition not in present
    ]
    failed = sorted(
        partition
        for partition, evidence in by_partition.items()
        if partition in REQUIRED_EVALUATION_PARTITIONS and not evidence.passed
    )

    unmutated_passed = report.unmutated_suite_passed and (
        EvaluationPartition.UNMUTATED.value not in by_partition
        or by_partition[EvaluationPartition.UNMUTATED.value].passed
    )
    diagnosis_killed = report.diagnosis_killed and (
        EvaluationPartition.DIAGNOSIS.value not in by_partition
        or by_partition[EvaluationPartition.DIAGNOSIS.value].passed
    )
    development_killed = report.development_killed and (
        EvaluationPartition.DEVELOPMENT.value not in by_partition
        or by_partition[EvaluationPartition.DEVELOPMENT.value].passed
    )
    held_out_killed = report.held_out_killed and (
        EvaluationPartition.HELD_OUT.value not in by_partition
        or by_partition[EvaluationPartition.HELD_OUT.value].passed
    )
    unrelated_ok = report.unrelated_behavior_preserved and (
        EvaluationPartition.UNRELATED.value not in by_partition
        or by_partition[EvaluationPartition.UNRELATED.value].passed
    )
    safety_ok = report.safety_preserved and (
        EvaluationPartition.SAFETY.value not in by_partition
        or by_partition[EvaluationPartition.SAFETY.value].passed
    )
    regression = report.regression_detected or (
        EvaluationPartition.REGRESSION.value in by_partition
        and not by_partition[EvaluationPartition.REGRESSION.value].passed
    )
    overconstraint = report.overconstraint_detected or (
        EvaluationPartition.OVERCONSTRAINT.value in by_partition
        and not by_partition[EvaluationPartition.OVERCONSTRAINT.value].passed
    )
    false_positive = report.false_positive_detected or (
        EvaluationPartition.FALSE_POSITIVE.value in by_partition
        and not by_partition[EvaluationPartition.FALSE_POSITIVE.value].passed
    )
    cost_bp = report.cost_delta_basis_points
    cost_ok = cost_bp <= max_cost and (
        EvaluationPartition.PERFORMANCE_COST.value not in by_partition
        or by_partition[EvaluationPartition.PERFORMANCE_COST.value].passed
    )

    leakage_detected = False
    leakage_notes: list[str] = []
    if plan is not None:
        leakage_detected, leakage_notes = _check_partition_alignment(report, plan)

    # Development kill is required when development partition has mutants /
    # evidence that claims kills; empty development is allowed only if
    # evidence still passes (e.g. no related development mutants available).
    development_required_kill = True
    if plan is not None and not plan.development_mutant_ids:
        development_required_kill = False
    if not development_required_kill:
        development_ok = True
    else:
        development_ok = bool(development_killed)

    reasons = _map_failure_to_reasons(
        missing=missing,
        failed=failed,
        unmutated_suite_passed=unmutated_passed,
        diagnosis_killed=bool(diagnosis_killed),
        held_out_killed=bool(held_out_killed),
        unrelated_behavior_preserved=bool(unrelated_ok),
        safety_preserved=bool(safety_ok),
        regression_detected=bool(regression),
        overconstraint_detected=bool(overconstraint),
        false_positive_detected=bool(false_positive),
        cost_within_budget=bool(cost_ok),
        partition_leakage_detected=leakage_detected,
        report_reasons=list(report.rejection_reasons),
    )
    if development_required_kill and not development_ok:
        # Development failure is a soft overfit / incomplete generalization signal.
        reasons = sorted(
            set(reasons)
            | {
                RejectionReason.HELD_OUT_FAILURE.value,
                RejectionReason.OVERFIT_IMPLEMENTATION_ASSERTION.value,
            }
        )
        if EvaluationPartition.DEVELOPMENT.value not in failed:
            failed = sorted(set(failed) | {EvaluationPartition.DEVELOPMENT.value})

    required_present = not missing
    qualifies = (
        required_present
        and not failed
        and unmutated_passed
        and diagnosis_killed
        and held_out_killed
        and development_ok
        and unrelated_ok
        and safety_ok
        and not regression
        and not overconstraint
        and not false_positive
        and cost_ok
        and not leakage_detected
        and not reasons
        and report.verdict == EvaluationVerdict.QUALIFIED.value
    )

    if qualifies:
        disposition = QualificationDisposition.QUALIFIED.value
        verdict = EvaluationVerdict.QUALIFIED.value
        rejection_reasons: tuple[str, ...] = ()
        missing_out: tuple[str, ...] = ()
        failed_out: tuple[str, ...] = ()
    else:
        disposition = QualificationDisposition.REJECTED.value
        if not reasons:
            reasons = [RejectionReason.HELD_OUT_FAILURE.value]
        rejection_reasons = tuple(sorted(set(reasons)))
        verdict = _select_verdict(disposition=disposition, reasons=rejection_reasons)
        missing_out = tuple(missing)
        failed_out = tuple(failed)

    result_header = _clone_header(
        report.header,
        artifact_kind="remediation_qualification_result",
        interface_id=QUALIFY_REMEDIATION_EVALUATION_INTERFACE,
    )
    resolved_result_id = (
        _token(result_id, "result_id")
        if result_id is not None
        else _token(f"qualify_{report.report_id}", "result_id")
    )
    note_parts: list[str] = []
    if notes:
        note_parts.append(_text(notes, "notes"))
    if leakage_notes:
        note_parts.extend(leakage_notes)
    note_text = "; ".join(note_parts) if note_parts else None

    result_metadata: dict[str, Any] = {
        "generator_id": GENERATOR_ID,
        "generator_version": GENERATOR_VERSION,
        "evidence": HELD_OUT_POLICY_EVIDENCE,
        "interface_id": QUALIFY_REMEDIATION_EVALUATION_INTERFACE,
        "production_policy_changed": False,
        "max_cost_delta_bp": max_cost,
        "report_verdict": report.verdict,
        "required_evaluation_partitions": list(REQUIRED_EVALUATION_PARTITIONS),
    }
    if plan is not None:
        result_metadata["partition_plan_cid"] = plan.plan_cid
        result_metadata["campaign_id"] = plan.campaign_id
    if metadata:
        result_metadata.update(dict(metadata))
        reject_private_model_authority_and_host_fallbacks(
            result_metadata, path="metadata"
        )

    result = RemediationQualificationResult(
        header=result_header,
        result_id=resolved_result_id,
        evaluation_report_cid=report.report_cid,
        disposition=disposition,
        verdict=verdict,
        partition_plan_cid=plan.plan_cid if plan is not None else None,
        required_partitions_present=required_present,
        unmutated_suite_passed=bool(unmutated_passed),
        diagnosis_killed=bool(diagnosis_killed),
        development_killed=bool(development_killed),
        held_out_killed=bool(held_out_killed),
        unrelated_behavior_preserved=bool(unrelated_ok),
        safety_preserved=bool(safety_ok),
        regression_detected=bool(regression),
        overconstraint_detected=bool(overconstraint),
        false_positive_detected=bool(false_positive),
        cost_delta_basis_points=cost_bp,
        cost_within_budget=bool(cost_ok),
        partition_leakage_detected=leakage_detected,
        production_policy_changed=False,
        rejection_reasons=rejection_reasons,
        missing_partitions=missing_out,
        failed_partitions=failed_out,
        notes=note_text,
        metadata=result_metadata,
    )
    verify_remediation_qualification_identity(result)
    return result


# ---------------------------------------------------------------------------
# Vocabulary helpers, verification, and leakage assertion
# ---------------------------------------------------------------------------


def mutant_corpus_partitions() -> tuple[str, ...]:
    """Return diagnosis/development/held-out corpus partition vocabulary."""

    return MUTANT_CORPUS_PARTITIONS


def required_evaluation_partitions() -> tuple[str, ...]:
    """Return the ten evaluation partitions required for qualification."""

    return REQUIRED_EVALUATION_PARTITIONS


def qualification_dispositions() -> tuple[str, ...]:
    """Return the closed qualification disposition vocabulary."""

    return tuple(item.value for item in QualificationDisposition)


def assert_partition_leakage_free(
    plan: MutantPartitionPlan | Mapping[str, Any],
) -> MutantPartitionPlan:
    """Fail closed if a partition plan exhibits identity leakage."""

    sealed = _normalize_partition_plan(plan)
    diagnosis = set(sealed.diagnosis_mutant_ids)
    development = set(sealed.development_mutant_ids)
    held_out = set(sealed.held_out_mutant_ids)
    if diagnosis & development or diagnosis & held_out or development & held_out:
        raise HeldOutPolicyError(
            "partition leakage: diagnosis/development/held_out are not disjoint"
        )
    for member in sealed.members:
        if (
            member.used_for_candidate_generation
            and member.partition == MutantCorpusPartition.HELD_OUT.value
        ):
            raise HeldOutPolicyError(
                "partition leakage: candidate-generating mutant in held_out"
            )
    if not sealed.leakage_resistant:
        raise HeldOutPolicyError("leakage_resistant must be true")
    return sealed


def verify_mutant_partition_plan_identity(
    plan: MutantPartitionPlan | Mapping[str, Any],
) -> str:
    """Recompute and return the plan CID; raise on forged input."""

    if isinstance(plan, MutantPartitionPlan):
        sealed = plan
    elif isinstance(plan, Mapping):
        sealed = MutantPartitionPlan.from_dict(plan)
    else:
        raise HeldOutPolicyError("plan must be MutantPartitionPlan or mapping")
    recomputed = cid_for_structured(sealed.identity_payload())
    if recomputed != sealed.plan_cid:
        raise HeldOutPolicyError(
            "plan_cid identity mismatch with recomputed identity"
        )
    if isinstance(plan, Mapping) and plan.get("plan_cid") != recomputed:
        raise HeldOutPolicyError(
            "plan_cid identity mismatch with recomputed identity"
        )
    return recomputed


def verify_remediation_qualification_identity(
    result: RemediationQualificationResult | Mapping[str, Any],
) -> str:
    """Recompute and return the qualification result CID; raise on forged input."""

    if isinstance(result, RemediationQualificationResult):
        sealed = result
    elif isinstance(result, Mapping):
        sealed = RemediationQualificationResult.from_dict(result)
    else:
        raise HeldOutPolicyError(
            "result must be RemediationQualificationResult or mapping"
        )
    recomputed = cid_for_structured(sealed.identity_payload())
    if recomputed != sealed.result_cid:
        raise HeldOutPolicyError(
            "result_cid identity mismatch with recomputed identity"
        )
    if isinstance(result, Mapping) and result.get("result_cid") != recomputed:
        raise HeldOutPolicyError(
            "result_cid identity mismatch with recomputed identity"
        )
    return recomputed


__all__ = [
    "DEFAULT_DEVELOPMENT_RATIO_BP",
    "DEFAULT_HELD_OUT_RATIO_BP",
    "DEFAULT_MAX_COST_DELTA_BP",
    "GENERATOR_ID",
    "GENERATOR_VERSION",
    "HELD_OUT_POLICY_EVIDENCE",
    "MUTANT_CORPUS_PARTITIONS",
    "MUTANT_PARTITION_MEMBER_SCHEMA",
    "MUTANT_PARTITION_PLAN_INTERFACE",
    "MUTANT_PARTITION_PLAN_SCHEMA",
    "PARTITION_MUTANTS_INTERFACE",
    "QUALIFY_REMEDIATION_EVALUATION_INTERFACE",
    "REMEDIATION_QUALIFICATION_INTERFACE",
    "REMEDIATION_QUALIFICATION_SCHEMA",
    "REQUIRED_EVALUATION_PARTITIONS",
    "HeldOutPolicyError",
    "MutantCorpusPartition",
    "MutantPartitionMember",
    "MutantPartitionPlan",
    "QualificationDisposition",
    "RemediationQualificationResult",
    "assert_partition_leakage_free",
    "mutant_corpus_partitions",
    "partition_mutants",
    "qualification_dispositions",
    "qualify_remediation_evaluation",
    "required_evaluation_partitions",
    "verify_mutant_partition_plan_identity",
    "verify_remediation_qualification_identity",
]
