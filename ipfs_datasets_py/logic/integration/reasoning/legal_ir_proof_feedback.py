"""Versioned, source-free proof-feedback records for Legal IR training.

This module is the persistence boundary between proof execution and learned
Legal IR components.  A backend trace or a Leanstral response is useful while
searching for a proof, but neither is a training label.  Records created here
contain only bounded categorical features, content digests, and verifier-owned
identifiers.  In particular they never contain a legal statement, solver
output, proof script, counterexample prose, or a model-authored assertion.

Record identifiers are SHA-256 content addresses over canonical JSON.  There
are deliberately no timestamps in the addressed payload, making records
stable across workers and suitable for deterministic replay.  Train/holdout
assignment hashes a source-free group digest so all feedback for one sample is
kept in the same partition.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import tempfile
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Final, Iterable, Iterator, Mapping, Optional, Sequence

from .legal_ir_hammer_translation import (
    LEGAL_IR_HAMMER_RECONSTRUCTION_RECEIPT_SCHEMA_VERSION,
    LEGAL_IR_HAMMER_TRANSLATION_SCHEMA_VERSION,
    HammerReconstructionReceipt,
    reconstruction_receipt_from_hammer_result,
)
from .legal_ir_obligations import LEGAL_IR_OBLIGATION_SCHEMA_VERSION
from .legal_ir_premises import LEGAL_IR_PREMISE_LIBRARY_VERSION
from .legal_ir_proof_router import (
    LEGAL_IR_PROOF_ROUTER_SCHEMA_VERSION,
    LegalIRProofRouteResult,
    ProofTrustLevel,
)
from .legal_ir_view_contracts import LEGAL_IR_VIEW_CONTRACT_REGISTRY_VERSION


LEGAL_IR_PROOF_FEEDBACK_SCHEMA_VERSION: Final = "legal-ir-proof-feedback-v1"
LEGAL_IR_PROOF_FEEDBACK_STORE_VERSION: Final = "legal-ir-proof-feedback-store-v1"
LEGAL_IR_PROOF_FEEDBACK_REPLAY_VERSION: Final = "legal-ir-proof-feedback-replay-v1"
LEGAL_IR_PROOF_FEEDBACK_PARTITION_VERSION: Final = "legal-ir-proof-feedback-partition-v1"
DEFAULT_PROOF_FEEDBACK_HOLDOUT_FRACTION: Final = 0.10
DEFAULT_PROOF_FEEDBACK_PARTITION_SALT: Final = "legal-ir-proof-feedback/frozen/v1"

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+\-]*$")
_SLOT_STATES = frozenset({"absent", "empty", "multiple", "present", "single", "unknown"})
_ROUTE_STATES = frozenset(
    {
        "cancelled",
        "error",
        "passed",
        "proved",
        "skipped",
        "theorem_failed",
        "timeout",
        "unknown",
        "unsupported_translation",
    }
)


class ProofFeedbackError(ValueError):
    """Base error for malformed or unsafe proof-feedback data."""


class ProofFeedbackIntegrityError(ProofFeedbackError):
    """Raised when a content address does not match its record payload."""


class ProofFeedbackTrustError(ProofFeedbackError):
    """Raised when a label is assigned more authority than its receipts allow."""


class ProofFeedbackPartitionError(ProofFeedbackError):
    """Raised for invalid train/holdout policies or assignments."""


class ProofFeedbackPartition(str, Enum):
    TRAIN = "train"
    HOLDOUT = "holdout"


class ProofFeedbackTrustStatus(str, Enum):
    """Whether a record is authorized to supervise learned weights."""

    TRUSTED = "trusted"
    UNTRUSTED = "untrusted"


class ProofFeedbackLabel(str, Enum):
    """Verifier-derived outcome labels used by proof-aware training heads."""

    KERNEL_OR_DETERMINISTIC_TRUSTED = "kernel_or_deterministic_trusted"
    VERIFIED_COUNTEREXAMPLE = "verified_counterexample"
    CONTRACT_FAILURE = "contract_failure"
    RECONSTRUCTION_FAILURE = "reconstruction_failure"
    UNSUPPORTED_TRANSLATION = "unsupported_translation"
    NO_TRUSTED_SIGNAL = "no_trusted_signal"


def _json_ready(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ProofFeedbackError("non-finite numbers are not canonical JSON")
        return value
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {
            str(key): _json_ready(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_json_ready(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return [_json_ready(item) for item in sorted(value, key=str)]
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return _json_ready(to_dict())
    return str(value)


def canonical_proof_feedback_json(value: Any) -> str:
    """Return the canonical JSON representation used for every record digest."""

    return json.dumps(
        _json_ready(value),
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )


def proof_feedback_content_digest(value: Any) -> str:
    return hashlib.sha256(canonical_proof_feedback_json(value).encode("utf-8")).hexdigest()


def _get(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def _mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        converted = to_dict()
        if isinstance(converted, Mapping):
            return dict(converted)
    return {}


def _enum_text(value: Any) -> str:
    return str(getattr(value, "value", value) or "")


def _safe_identifier(value: Any, *, fallback: str = "unknown", max_length: int = 256) -> str:
    """Normalize an identifier without ever retaining free-form prose."""

    text = str(value or "").strip()
    if text and len(text) <= max_length and _IDENTIFIER_RE.fullmatch(text):
        return text
    if not text:
        return fallback
    return f"sha256:{hashlib.sha256(text.encode('utf-8')).hexdigest()}"


def _require_safe_identifier(value: str, field_name: str, *, allow_empty: bool = False) -> None:
    if not value and allow_empty:
        return
    if not value or len(value) > 256 or not _IDENTIFIER_RE.fullmatch(value):
        raise ProofFeedbackError(f"{field_name} must be a bounded source-free identifier")


def _digest(value: Any) -> str:
    text = str(value or "")
    if _SHA256_RE.fullmatch(text):
        return text
    if text.startswith("sha256:") and _SHA256_RE.fullmatch(text[7:]):
        return text[7:]
    return proof_feedback_content_digest(value)


def _identifier_tuple(values: Any) -> tuple[str, ...]:
    if values is None:
        return ()
    if isinstance(values, str):
        raw = [values]
    elif isinstance(values, Sequence) and not isinstance(values, (bytes, bytearray, str)):
        raw = list(values)
    else:
        raw = [values]
    return tuple(sorted({_safe_identifier(item) for item in raw if str(item or "").strip()}))


def _slot_features(
    slots: Optional[Mapping[str, Any]],
) -> tuple[dict[str, str], dict[str, tuple[str, ...]]]:
    """Reduce semantic slot values to presence/cardinality and value digests."""

    states: dict[str, str] = {}
    digests: dict[str, tuple[str, ...]] = {}
    for raw_name, raw_value in sorted(dict(slots or {}).items(), key=lambda item: str(item[0])):
        name = _safe_identifier(raw_name, max_length=96)
        values: list[Any]
        if raw_value is None:
            state, values = "absent", []
        elif isinstance(raw_value, bool):
            state, values = ("present", [True]) if raw_value else ("absent", [])
        elif isinstance(raw_value, str) and raw_value.strip().lower() in _SLOT_STATES:
            state, values = raw_value.strip().lower(), []
        elif isinstance(raw_value, Sequence) and not isinstance(raw_value, (bytes, bytearray, str)):
            values = [item for item in raw_value if item is not None and str(item).strip()]
            state = "empty" if not values else "single" if len(values) == 1 else "multiple"
        else:
            state, values = "present", [raw_value]
        states[name] = state
        if values:
            digests[name] = tuple(sorted({_digest(value) for value in values}))
    return states, digests


@dataclass(frozen=True)
class ProofFeedbackVersions:
    """Identities which must match before a feedback record can train a model."""

    compiler_version: str = "unspecified"
    obligation_schema_version: str = LEGAL_IR_OBLIGATION_SCHEMA_VERSION
    contract_registry_version: str = LEGAL_IR_VIEW_CONTRACT_REGISTRY_VERSION
    premise_library_version: str = LEGAL_IR_PREMISE_LIBRARY_VERSION
    proof_router_version: str = LEGAL_IR_PROOF_ROUTER_SCHEMA_VERSION
    translation_schema_version: str = LEGAL_IR_HAMMER_TRANSLATION_SCHEMA_VERSION
    reconstruction_schema_version: str = LEGAL_IR_HAMMER_RECONSTRUCTION_RECEIPT_SCHEMA_VERSION
    solver_toolchain_version: str = "unspecified"
    lean_toolchain_version: str = "unspecified"
    theorem_registry_version: str = "unspecified"
    repair_taxonomy_version: str = "legal-ir-repair-labels-v1"

    def __post_init__(self) -> None:
        for name, value in self.to_dict().items():
            _require_safe_identifier(str(value), f"versions.{name}")

    @property
    def fingerprint(self) -> str:
        return proof_feedback_content_digest(self.to_dict())

    def to_dict(self) -> dict[str, str]:
        return {
            "compiler_version": self.compiler_version,
            "contract_registry_version": self.contract_registry_version,
            "lean_toolchain_version": self.lean_toolchain_version,
            "obligation_schema_version": self.obligation_schema_version,
            "premise_library_version": self.premise_library_version,
            "proof_router_version": self.proof_router_version,
            "reconstruction_schema_version": self.reconstruction_schema_version,
            "repair_taxonomy_version": self.repair_taxonomy_version,
            "solver_toolchain_version": self.solver_toolchain_version,
            "theorem_registry_version": self.theorem_registry_version,
            "translation_schema_version": self.translation_schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ProofFeedbackVersions":
        fields = cls.__dataclass_fields__
        return cls(**{name: str(value[name]) for name in fields if name in value})


@dataclass(frozen=True)
class ProofFeedbackPartitionPolicy:
    """Frozen deterministic partitioning policy."""

    holdout_fraction: float = DEFAULT_PROOF_FEEDBACK_HOLDOUT_FRACTION
    salt: str = DEFAULT_PROOF_FEEDBACK_PARTITION_SALT
    version: str = LEGAL_IR_PROOF_FEEDBACK_PARTITION_VERSION

    def __post_init__(self) -> None:
        fraction = float(self.holdout_fraction)
        if not math.isfinite(fraction) or not 0.0 <= fraction <= 1.0:
            raise ProofFeedbackPartitionError("holdout_fraction must be between zero and one")
        _require_safe_identifier(self.salt, "partition salt")
        _require_safe_identifier(self.version, "partition version")

    def assign(self, group_key: Any) -> ProofFeedbackPartition:
        group_digest = _digest(group_key)
        bucket = int(
            hashlib.sha256(f"{self.version}:{self.salt}:{group_digest}".encode("utf-8")).hexdigest()[:16],
            16,
        )
        threshold = int(float(self.holdout_fraction) * (1 << 64))
        return ProofFeedbackPartition.HOLDOUT if bucket < threshold else ProofFeedbackPartition.TRAIN

    def to_dict(self) -> dict[str, Any]:
        return {
            "holdout_fraction": float(self.holdout_fraction),
            "salt": self.salt,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ProofFeedbackPartitionPolicy":
        return cls(
            holdout_fraction=float(value.get("holdout_fraction", DEFAULT_PROOF_FEEDBACK_HOLDOUT_FRACTION)),
            salt=str(value.get("salt") or DEFAULT_PROOF_FEEDBACK_PARTITION_SALT),
            version=str(value.get("version") or LEGAL_IR_PROOF_FEEDBACK_PARTITION_VERSION),
        )


def deterministic_proof_feedback_partition(
    group_key: Any,
    *,
    holdout_fraction: float = DEFAULT_PROOF_FEEDBACK_HOLDOUT_FRACTION,
    salt: str = DEFAULT_PROOF_FEEDBACK_PARTITION_SALT,
) -> ProofFeedbackPartition:
    return ProofFeedbackPartitionPolicy(holdout_fraction=holdout_fraction, salt=salt).assign(group_key)


@dataclass(frozen=True)
class KernelReconstructionFeedback:
    """Source-free projection of a kernel reconstruction receipt."""

    status: str = "not_attempted"
    attempted: bool = False
    verified: bool = False
    checker: str = ""
    receipt_id: str = ""

    def __post_init__(self) -> None:
        _require_safe_identifier(self.status, "kernel_reconstruction.status")
        _require_safe_identifier(self.checker, "kernel_reconstruction.checker", allow_empty=True)
        _require_safe_identifier(self.receipt_id, "kernel_reconstruction.receipt_id", allow_empty=True)
        if self.verified and (not self.attempted or not self.receipt_id):
            raise ProofFeedbackTrustError("verified reconstruction requires an attempted receipt")

    def to_dict(self) -> dict[str, Any]:
        return {
            "attempted": bool(self.attempted),
            "checker": self.checker,
            "receipt_id": self.receipt_id,
            "status": self.status,
            "verified": bool(self.verified),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "KernelReconstructionFeedback":
        return cls(
            status=_safe_identifier(value.get("status") or "not_attempted"),
            attempted=bool(value.get("attempted")),
            verified=bool(value.get("verified")),
            checker=_safe_identifier(value.get("checker"), fallback="") if value.get("checker") else "",
            receipt_id=_safe_identifier(value.get("receipt_id"), fallback="") if value.get("receipt_id") else "",
        )

    @classmethod
    def from_receipt(
        cls,
        receipt: Optional[HammerReconstructionReceipt | Mapping[str, Any]],
    ) -> "KernelReconstructionFeedback":
        if receipt is None:
            return cls()
        value = _mapping(receipt)
        attempted = bool(value.get("native_reconstruction")) or bool(value.get("reconstruction_status"))
        return cls(
            status=_safe_identifier(value.get("reconstruction_status") or value.get("outcome") or "not_attempted"),
            attempted=attempted,
            verified=bool(value.get("native_reconstruction_verified")),
            checker=_safe_identifier(value.get("checker"), fallback="") if value.get("checker") else "",
            receipt_id=_safe_identifier(value.get("receipt_id"), fallback="") if value.get("receipt_id") else "",
        )


@dataclass(frozen=True)
class VerifiedCounterexampleFeedback:
    """Verifier-attested counterexample identity; witness prose is never stored."""

    counterexample_type: str
    witness_digest: str
    verifier: str
    evidence_ids: tuple[str, ...] = ()
    receipt_ids: tuple[str, ...] = ()
    verified: bool = True

    def __post_init__(self) -> None:
        _require_safe_identifier(self.counterexample_type, "counterexample.type")
        _require_safe_identifier(self.verifier, "counterexample.verifier")
        if not _SHA256_RE.fullmatch(self.witness_digest):
            raise ProofFeedbackError("counterexample witness_digest must be a SHA-256 digest")
        if not self.verified:
            raise ProofFeedbackTrustError("unverified counterexamples cannot enter a training record")
        for item in (*self.evidence_ids, *self.receipt_ids):
            _require_safe_identifier(item, "counterexample identifier")

    def to_dict(self) -> dict[str, Any]:
        return {
            "counterexample_type": self.counterexample_type,
            "evidence_ids": list(self.evidence_ids),
            "receipt_ids": list(self.receipt_ids),
            "verified": True,
            "verifier": self.verifier,
            "witness_digest": self.witness_digest,
        }

    @classmethod
    def from_verified(cls, value: Mapping[str, Any]) -> Optional["VerifiedCounterexampleFeedback"]:
        if not bool(value.get("verified") or value.get("verifier_attested")):
            return None
        witness = value.get("witness_digest") or value.get("counterexample_digest")
        if not witness:
            # Hashing the witness permits replay equality without persisting it.
            witness = _digest(value.get("witness") or value.get("counterexample") or value)
        return cls(
            counterexample_type=_safe_identifier(
                value.get("counterexample_type") or value.get("kind") or "counterexample"
            ),
            witness_digest=_digest(witness),
            verifier=_safe_identifier(value.get("verifier") or value.get("checker") or "deterministic_verifier"),
            evidence_ids=_identifier_tuple(value.get("evidence_ids") or value.get("evidence_id")),
            receipt_ids=_identifier_tuple(value.get("receipt_ids") or value.get("receipt_id")),
        )

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "VerifiedCounterexampleFeedback":
        result = cls.from_verified(value)
        if result is None:
            raise ProofFeedbackTrustError("persisted counterexample must be verifier-attested")
        return result


@dataclass(frozen=True)
class MinimalFailingContractFeedback:
    """Smallest deterministically failing contract, represented without values."""

    contract_id: str
    failure_code: str
    failing_fields: tuple[str, ...] = ()
    contract_digest: str = ""
    verifier: str = "deterministic_contract_validator"
    evidence_ids: tuple[str, ...] = ()
    receipt_ids: tuple[str, ...] = ()
    verified: bool = True

    def __post_init__(self) -> None:
        for name in ("contract_id", "failure_code", "verifier"):
            _require_safe_identifier(getattr(self, name), f"minimal_failing_contract.{name}")
        for item in self.failing_fields:
            _require_safe_identifier(item, "minimal_failing_contract.failing_fields")
        if self.contract_digest and not _SHA256_RE.fullmatch(self.contract_digest):
            raise ProofFeedbackError("contract_digest must be empty or a SHA-256 digest")
        if not self.verified:
            raise ProofFeedbackTrustError("an unverified contract failure is not a training target")

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_digest": self.contract_digest,
            "contract_id": self.contract_id,
            "evidence_ids": list(self.evidence_ids),
            "failing_fields": list(self.failing_fields),
            "failure_code": self.failure_code,
            "receipt_ids": list(self.receipt_ids),
            "verified": True,
            "verifier": self.verifier,
        }

    @classmethod
    def from_verified(cls, value: Mapping[str, Any]) -> Optional["MinimalFailingContractFeedback"]:
        if not bool(value.get("verified") or value.get("deterministic")):
            return None
        return cls(
            contract_id=_safe_identifier(value.get("contract_id") or "unknown_contract"),
            failure_code=_safe_identifier(value.get("failure_code") or value.get("reason") or "contract_failure"),
            failing_fields=_identifier_tuple(value.get("failing_fields") or value.get("required_field")),
            contract_digest=_digest(value["contract_digest"]) if value.get("contract_digest") else "",
            verifier=_safe_identifier(value.get("verifier") or "deterministic_contract_validator"),
            evidence_ids=_identifier_tuple(value.get("evidence_ids") or value.get("evidence_id")),
            receipt_ids=_identifier_tuple(value.get("receipt_ids") or value.get("receipt_id")),
        )

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "MinimalFailingContractFeedback":
        result = cls.from_verified(value)
        if result is None:
            raise ProofFeedbackTrustError("persisted contract failure must be verifier-attested")
        return result


def _training_label(
    *,
    deterministic_trusted: bool,
    kernel: KernelReconstructionFeedback,
    counterexample: Optional[VerifiedCounterexampleFeedback],
    contract: Optional[MinimalFailingContractFeedback],
    route_statuses: Mapping[str, str],
) -> ProofFeedbackLabel:
    positives = deterministic_trusted or kernel.verified
    negatives = sum(
        (
            counterexample is not None,
            contract is not None,
            kernel.attempted and not kernel.verified and bool(kernel.receipt_id),
            "unsupported_translation" in route_statuses.values(),
        )
    )
    if positives and negatives:
        raise ProofFeedbackTrustError("contradictory positive and negative verifier signals")
    if positives:
        return ProofFeedbackLabel.KERNEL_OR_DETERMINISTIC_TRUSTED
    if counterexample is not None:
        return ProofFeedbackLabel.VERIFIED_COUNTEREXAMPLE
    if contract is not None:
        return ProofFeedbackLabel.CONTRACT_FAILURE
    if kernel.attempted and not kernel.verified and kernel.receipt_id:
        return ProofFeedbackLabel.RECONSTRUCTION_FAILURE
    if "unsupported_translation" in route_statuses.values():
        return ProofFeedbackLabel.UNSUPPORTED_TRANSLATION
    return ProofFeedbackLabel.NO_TRUSTED_SIGNAL


@dataclass(frozen=True)
class LegalIRProofFeedbackRecord:
    """One immutable, content-addressed proof supervision example."""

    record_id: str
    obligation_id: str
    obligation_digest: str
    obligation_type: str
    legal_ir_view: str
    semantic_family: str
    semantic_slots: Mapping[str, str]
    semantic_slot_value_digests: Mapping[str, tuple[str, ...]]
    selected_premise_families: tuple[str, ...]
    route_availability: Mapping[str, bool]
    route_statuses: Mapping[str, str]
    backend_outcomes: Mapping[str, str]
    kernel_reconstruction: KernelReconstructionFeedback
    counterexample: Optional[VerifiedCounterexampleFeedback]
    minimal_failing_contract: Optional[MinimalFailingContractFeedback]
    deterministic_trusted: bool
    training_label: ProofFeedbackLabel
    repair_label: str
    trust_status: ProofFeedbackTrustStatus
    evidence_ids: tuple[str, ...]
    receipt_ids: tuple[str, ...]
    partition_key_digest: str
    partition: ProofFeedbackPartition
    partition_policy: ProofFeedbackPartitionPolicy
    versions: ProofFeedbackVersions
    schema_version: str = LEGAL_IR_PROOF_FEEDBACK_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != LEGAL_IR_PROOF_FEEDBACK_SCHEMA_VERSION:
            raise ProofFeedbackError(f"unsupported proof-feedback schema: {self.schema_version!r}")
        for name in ("obligation_id", "obligation_type", "legal_ir_view", "semantic_family", "repair_label"):
            _require_safe_identifier(str(getattr(self, name)), name)
        for name in ("obligation_digest", "partition_key_digest"):
            if not _SHA256_RE.fullmatch(str(getattr(self, name))):
                raise ProofFeedbackError(f"{name} must be a SHA-256 digest")
        for slot, state in self.semantic_slots.items():
            _require_safe_identifier(str(slot), "semantic slot")
            if state not in _SLOT_STATES:
                raise ProofFeedbackError(f"unsupported semantic slot state: {state!r}")
        for values in self.semantic_slot_value_digests.values():
            if any(not _SHA256_RE.fullmatch(value) for value in values):
                raise ProofFeedbackError("semantic slot values must be represented by SHA-256 digests")
        if any(status not in _ROUTE_STATES for status in self.route_statuses.values()):
            raise ProofFeedbackError("route_statuses contains an unsupported status")
        expected_partition = self.partition_policy.assign(self.partition_key_digest)
        if self.partition != expected_partition:
            raise ProofFeedbackPartitionError("persisted partition does not match its group digest and policy")
        expected_label = _training_label(
            deterministic_trusted=self.deterministic_trusted,
            kernel=self.kernel_reconstruction,
            counterexample=self.counterexample,
            contract=self.minimal_failing_contract,
            route_statuses=self.route_statuses,
        )
        if self.training_label != expected_label:
            raise ProofFeedbackTrustError("training label does not match verifier-owned evidence")
        expected_trust = (
            ProofFeedbackTrustStatus.TRUSTED
            if expected_label != ProofFeedbackLabel.NO_TRUSTED_SIGNAL
            else ProofFeedbackTrustStatus.UNTRUSTED
        )
        if self.trust_status != expected_trust:
            raise ProofFeedbackTrustError("trust status does not match the derived training label")
        for item in (
            *self.selected_premise_families,
            *self.route_availability.keys(),
            *self.route_statuses.keys(),
            *self.backend_outcomes.keys(),
            *self.backend_outcomes.values(),
            *self.evidence_ids,
            *self.receipt_ids,
        ):
            _require_safe_identifier(str(item), "categorical feature or identifier")
        if self.record_id:
            if self.record_id != self.expected_record_id:
                raise ProofFeedbackIntegrityError("record_id does not match canonical record content")

    @property
    def eligible_for_training(self) -> bool:
        return self.trust_status == ProofFeedbackTrustStatus.TRUSTED

    @property
    def positive(self) -> bool:
        return self.training_label == ProofFeedbackLabel.KERNEL_OR_DETERMINISTIC_TRUSTED

    @property
    def content_hash(self) -> str:
        return proof_feedback_content_digest(self._content_dict())

    @property
    def expected_record_id(self) -> str:
        return f"legal-ir-proof-feedback-{self.content_hash}"

    @property
    def version_fingerprint(self) -> str:
        return self.versions.fingerprint

    def _content_dict(self) -> dict[str, Any]:
        return {
            "backend_outcomes": dict(sorted(self.backend_outcomes.items())),
            "counterexample": self.counterexample.to_dict() if self.counterexample else None,
            "deterministic_trusted": bool(self.deterministic_trusted),
            "evidence_ids": list(self.evidence_ids),
            "kernel_reconstruction": self.kernel_reconstruction.to_dict(),
            "legal_ir_view": self.legal_ir_view,
            "minimal_failing_contract": (
                self.minimal_failing_contract.to_dict() if self.minimal_failing_contract else None
            ),
            "obligation_digest": self.obligation_digest,
            "obligation_id": self.obligation_id,
            "obligation_type": self.obligation_type,
            "partition": self.partition.value,
            "partition_key_digest": self.partition_key_digest,
            "partition_policy": self.partition_policy.to_dict(),
            "receipt_ids": list(self.receipt_ids),
            "repair_label": self.repair_label,
            "route_availability": dict(sorted(self.route_availability.items())),
            "route_statuses": dict(sorted(self.route_statuses.items())),
            "schema_version": self.schema_version,
            "selected_premise_families": list(self.selected_premise_families),
            "semantic_family": self.semantic_family,
            "semantic_slot_value_digests": {
                key: list(values) for key, values in sorted(self.semantic_slot_value_digests.items())
            },
            "semantic_slots": dict(sorted(self.semantic_slots.items())),
            "training_label": self.training_label.value,
            "trust_status": self.trust_status.value,
            "versions": self.versions.to_dict(),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id,
            "content_hash": self.content_hash,
            "eligible_for_training": self.eligible_for_training,
            "version_fingerprint": self.version_fingerprint,
            **self._content_dict(),
        }

    def to_json(self) -> str:
        """Serialize one record in the same canonical form used on disk."""

        return canonical_proof_feedback_json(self.to_dict())

    @classmethod
    def create(
        cls,
        *,
        obligation_id: Any,
        obligation_type: Any,
        legal_ir_view: Any,
        semantic_family: Any,
        semantic_slots: Optional[Mapping[str, Any]] = None,
        selected_premise_families: Sequence[Any] = (),
        route_availability: Optional[Mapping[str, Any]] = None,
        route_statuses: Optional[Mapping[str, Any]] = None,
        backend_outcomes: Optional[Mapping[str, Any]] = None,
        kernel_reconstruction: Optional[KernelReconstructionFeedback | Mapping[str, Any]] = None,
        counterexample: Optional[VerifiedCounterexampleFeedback | Mapping[str, Any]] = None,
        minimal_failing_contract: Optional[MinimalFailingContractFeedback | Mapping[str, Any]] = None,
        deterministic_trusted: bool = False,
        repair_label: Any = "none",
        evidence_ids: Sequence[Any] = (),
        receipt_ids: Sequence[Any] = (),
        obligation_digest: Any = "",
        partition_key: Any = "",
        partition_policy: Optional[ProofFeedbackPartitionPolicy] = None,
        versions: Optional[ProofFeedbackVersions] = None,
    ) -> "LegalIRProofFeedbackRecord":
        slots, slot_digests = _slot_features(semantic_slots)
        routes = {
            _safe_identifier(key): bool(value)
            for key, value in sorted(dict(route_availability or {}).items(), key=lambda item: str(item[0]))
        }
        statuses = {
            _safe_identifier(key): _safe_identifier(_enum_text(value).lower())
            for key, value in sorted(dict(route_statuses or {}).items(), key=lambda item: str(item[0]))
        }
        backends = {
            _safe_identifier(key): _safe_identifier(_enum_text(value).lower())
            for key, value in sorted(dict(backend_outcomes or {}).items(), key=lambda item: str(item[0]))
        }
        kernel = (
            kernel_reconstruction
            if isinstance(kernel_reconstruction, KernelReconstructionFeedback)
            else KernelReconstructionFeedback.from_dict(kernel_reconstruction or {})
        )
        verified_counterexample = (
            counterexample
            if isinstance(counterexample, VerifiedCounterexampleFeedback)
            else VerifiedCounterexampleFeedback.from_verified(counterexample or {})
        )
        verified_contract = (
            minimal_failing_contract
            if isinstance(minimal_failing_contract, MinimalFailingContractFeedback)
            else MinimalFailingContractFeedback.from_verified(minimal_failing_contract or {})
        )
        label = _training_label(
            deterministic_trusted=bool(deterministic_trusted),
            kernel=kernel,
            counterexample=verified_counterexample,
            contract=verified_contract,
            route_statuses=statuses,
        )
        trust = (
            ProofFeedbackTrustStatus.TRUSTED
            if label != ProofFeedbackLabel.NO_TRUSTED_SIGNAL
            else ProofFeedbackTrustStatus.UNTRUSTED
        )
        evidence = set(_identifier_tuple(evidence_ids))
        receipts = set(_identifier_tuple(receipt_ids))
        if kernel.receipt_id:
            receipts.add(kernel.receipt_id)
        for artifact in (verified_counterexample, verified_contract):
            if artifact is not None:
                evidence.update(artifact.evidence_ids)
                receipts.update(artifact.receipt_ids)
        normalized_obligation_id = _safe_identifier(obligation_id)
        obligation_hash = _digest(
            obligation_digest
            or {
                "obligation_id": normalized_obligation_id,
                "type": str(obligation_type),
            }
        )
        group_digest = _digest(partition_key or normalized_obligation_id)
        policy = partition_policy or ProofFeedbackPartitionPolicy()
        kwargs = dict(
            record_id="",
            obligation_id=normalized_obligation_id,
            obligation_digest=obligation_hash,
            obligation_type=_safe_identifier(obligation_type),
            legal_ir_view=_safe_identifier(legal_ir_view),
            semantic_family=_safe_identifier(semantic_family),
            semantic_slots=slots,
            semantic_slot_value_digests=slot_digests,
            selected_premise_families=_identifier_tuple(selected_premise_families),
            route_availability=routes,
            route_statuses=statuses,
            backend_outcomes=backends,
            kernel_reconstruction=kernel,
            counterexample=verified_counterexample,
            minimal_failing_contract=verified_contract,
            deterministic_trusted=bool(deterministic_trusted),
            training_label=label,
            repair_label=_safe_identifier(repair_label or "none"),
            trust_status=trust,
            evidence_ids=tuple(sorted(evidence)),
            receipt_ids=tuple(sorted(receipts)),
            partition_key_digest=group_digest,
            partition=policy.assign(group_digest),
            partition_policy=policy,
            versions=versions or ProofFeedbackVersions(),
        )
        provisional = cls(**kwargs)
        return cls(**{**kwargs, "record_id": provisional.expected_record_id})

    @classmethod
    def from_dict(
        cls,
        value: Mapping[str, Any],
        *,
        verify_content_address: bool = True,
    ) -> "LegalIRProofFeedbackRecord":
        allowed = {
            "backend_outcomes", "content_hash", "counterexample", "deterministic_trusted",
            "eligible_for_training", "evidence_ids", "kernel_reconstruction", "legal_ir_view",
            "minimal_failing_contract", "obligation_digest", "obligation_id", "obligation_type",
            "partition", "partition_key_digest", "partition_policy", "receipt_ids", "record_id",
            "repair_label", "route_availability", "route_statuses", "schema_version",
            "selected_premise_families", "semantic_family", "semantic_slot_value_digests",
            "semantic_slots", "training_label", "trust_status", "version_fingerprint", "versions",
        }
        unknown = set(value) - allowed
        if unknown:
            raise ProofFeedbackError(f"unknown proof-feedback fields: {', '.join(sorted(unknown))}")
        counterexample = value.get("counterexample")
        contract = value.get("minimal_failing_contract")
        record = cls(
            record_id=str(value.get("record_id") or "") if verify_content_address else "",
            obligation_id=str(value.get("obligation_id") or ""),
            obligation_digest=str(value.get("obligation_digest") or ""),
            obligation_type=str(value.get("obligation_type") or ""),
            legal_ir_view=str(value.get("legal_ir_view") or ""),
            semantic_family=str(value.get("semantic_family") or ""),
            semantic_slots={str(k): str(v) for k, v in dict(value.get("semantic_slots") or {}).items()},
            semantic_slot_value_digests={
                str(k): tuple(str(item) for item in values)
                for k, values in dict(value.get("semantic_slot_value_digests") or {}).items()
            },
            selected_premise_families=tuple(str(item) for item in value.get("selected_premise_families", []) or []),
            route_availability={str(k): bool(v) for k, v in dict(value.get("route_availability") or {}).items()},
            route_statuses={str(k): str(v) for k, v in dict(value.get("route_statuses") or {}).items()},
            backend_outcomes={str(k): str(v) for k, v in dict(value.get("backend_outcomes") or {}).items()},
            kernel_reconstruction=KernelReconstructionFeedback.from_dict(_mapping(value.get("kernel_reconstruction"))),
            counterexample=(
                VerifiedCounterexampleFeedback.from_dict(counterexample)
                if isinstance(counterexample, Mapping)
                else None
            ),
            minimal_failing_contract=(
                MinimalFailingContractFeedback.from_dict(contract)
                if isinstance(contract, Mapping)
                else None
            ),
            deterministic_trusted=bool(value.get("deterministic_trusted")),
            training_label=ProofFeedbackLabel(str(value.get("training_label") or "")),
            repair_label=str(value.get("repair_label") or ""),
            trust_status=ProofFeedbackTrustStatus(str(value.get("trust_status") or "")),
            evidence_ids=tuple(str(item) for item in value.get("evidence_ids", []) or []),
            receipt_ids=tuple(str(item) for item in value.get("receipt_ids", []) or []),
            partition_key_digest=str(value.get("partition_key_digest") or ""),
            partition=ProofFeedbackPartition(str(value.get("partition") or "")),
            partition_policy=ProofFeedbackPartitionPolicy.from_dict(_mapping(value.get("partition_policy"))),
            versions=ProofFeedbackVersions.from_dict(_mapping(value.get("versions"))),
            schema_version=str(value.get("schema_version") or ""),
        )
        if not verify_content_address:
            return cls(**{**record.__dict__, "record_id": record.expected_record_id})
        claimed_hash = str(value.get("content_hash") or record.content_hash)
        if claimed_hash != record.content_hash:
            raise ProofFeedbackIntegrityError("content_hash does not match canonical record content")
        claimed_version = str(value.get("version_fingerprint") or record.version_fingerprint)
        if claimed_version != record.version_fingerprint:
            raise ProofFeedbackIntegrityError("version_fingerprint does not match record versions")
        return record

    @classmethod
    def from_json(cls, value: str | bytes, *, verify_content_address: bool = True) -> "LegalIRProofFeedbackRecord":
        """Deserialize and integrity-check canonical or ordinary JSON."""

        try:
            payload = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ProofFeedbackIntegrityError(f"invalid proof-feedback JSON: {exc}") from exc
        if not isinstance(payload, Mapping):
            raise ProofFeedbackError("proof-feedback JSON must contain an object")
        return cls.from_dict(payload, verify_content_address=verify_content_address)


ProofFeedbackRecord = LegalIRProofFeedbackRecord


def _premise_family(premise: Any) -> str:
    metadata = _mapping(_get(premise, "metadata", {}))
    for key in ("premise_family", "premise_kind", "logic_family", "legal_ir_view", "source_module"):
        if metadata.get(key):
            return _safe_identifier(metadata[key])
    name = _safe_identifier(_get(premise, "name", premise))
    return name.split("_", 1)[0] if "_" in name else name


def _route_features(route_result: Optional[LegalIRProofRouteResult]) -> tuple[dict[str, bool], dict[str, str], bool]:
    if route_result is None:
        return {}, {}, False
    availability: dict[str, bool] = {}
    statuses: dict[str, str] = {}
    deterministic_trusted = False
    for attempt in route_result.attempts:
        route = _safe_identifier(attempt.route)
        status = _safe_identifier(_enum_text(attempt.status).lower())
        statuses[route] = status
        unavailable = status == "unsupported_translation" or (
            status == "skipped" and "disabled" in str(attempt.skip_reason or "").lower()
        )
        availability[route] = not unavailable
        if (
            attempt.stage.value == "deterministic"
            and status in {"passed", "proved"}
            and attempt.trust_level >= ProofTrustLevel.DETERMINISTIC
        ):
            deterministic_trusted = True
    return availability, statuses, deterministic_trusted


def build_legal_ir_proof_feedback_record(
    obligation: Any,
    *,
    route_result: Optional[LegalIRProofRouteResult] = None,
    selected_premises: Sequence[Any] = (),
    reconstruction_receipt: Optional[HammerReconstructionReceipt | Mapping[str, Any]] = None,
    semantic_slots: Optional[Mapping[str, Any]] = None,
    counterexample: Optional[VerifiedCounterexampleFeedback | Mapping[str, Any]] = None,
    minimal_failing_contract: Optional[MinimalFailingContractFeedback | Mapping[str, Any]] = None,
    repair_label: Any = "",
    evidence_ids: Sequence[Any] = (),
    receipt_ids: Sequence[Any] = (),
    versions: Optional[ProofFeedbackVersions] = None,
    partition_policy: Optional[ProofFeedbackPartitionPolicy] = None,
    partition_key: Any = "",
    deterministic_trusted: Optional[bool] = None,
    unverified_leanstral_assertions: Any = None,
) -> LegalIRProofFeedbackRecord:
    """Project proof artifacts into one safe training record.

    ``unverified_leanstral_assertions`` is accepted only so callers can pass a
    complete audit envelope without pre-filtering it.  Its value is
    intentionally ignored and cannot affect either content or record identity.
    """

    del unverified_leanstral_assertions
    obligation_map = _mapping(obligation)
    metadata = _mapping(_get(obligation, "metadata", obligation_map.get("metadata", {})))
    obligation_id = _get(obligation, "obligation_id", obligation_map.get("obligation_id"))
    obligation_type = _get(obligation, "kind", obligation_map.get("kind")) or metadata.get("obligation_type")
    legal_ir_view = _get(obligation, "legal_ir_view", obligation_map.get("legal_ir_view"))
    semantic_family = (
        metadata.get("semantic_family")
        or _get(obligation, "logic_family", obligation_map.get("logic_family"))
        or metadata.get("obligation_family")
    )
    extracted_slots = semantic_slots
    if extracted_slots is None:
        raw_slots = metadata.get("semantic_slots") or metadata.get("slots")
        extracted_slots = dict(raw_slots) if isinstance(raw_slots, Mapping) else {}
        for slot_name in (
            "actor",
            "action",
            "object",
            "condition",
            "exception",
            "temporal",
            "authority",
            "provenance",
        ):
            if slot_name in metadata and slot_name not in extracted_slots:
                extracted_slots[slot_name] = metadata[slot_name]

    availability, route_statuses, route_deterministic = _route_features(route_result)
    hammer_result = getattr(route_result, "hammer_result", None) if route_result is not None else None
    if not selected_premises and hammer_result is not None:
        selected_premises = tuple(hammer_result.premise_selection.selected)
    backend_outcomes = {
        _safe_identifier(item.backend): _safe_identifier(_enum_text(item.status).lower())
        for item in (getattr(hammer_result, "backend_results", ()) or ())
    }
    receipt = reconstruction_receipt
    if receipt is None and hammer_result is not None:
        receipt = reconstruction_receipt_from_hammer_result(
            hammer_result,
            obligation_id=str(obligation_id or ""),
            input_formula_id=str(_get(obligation, "formula_id", "") or ""),
            trusted_requires_reconstruction=True,
        )
    kernel = KernelReconstructionFeedback.from_receipt(receipt)
    receipt_map = _mapping(receipt)
    resolved_receipts = list(receipt_ids)
    if receipt_map.get("receipt_id"):
        resolved_receipts.append(receipt_map["receipt_id"])

    if minimal_failing_contract is None and metadata.get("contract_id"):
        contract_attempt_failed = any(
            name.endswith("contract") and status == "theorem_failed"
            for name, status in route_statuses.items()
        )
        if contract_attempt_failed:
            minimal_failing_contract = {
                "contract_id": metadata["contract_id"],
                "failure_code": metadata.get("failure_code") or "deterministic_contract_failure",
                "failing_fields": metadata.get("required_field") or (),
                "verified": True,
            }

    # Hashing the original statement binds the record to the obligation while
    # keeping the statement itself outside the training corpus.
    statement = _get(obligation, "statement", obligation_map.get("statement", ""))
    obligation_hash = _digest(
        {
            "obligation_id": str(obligation_id or ""),
            "statement_sha256": hashlib.sha256(str(statement).encode("utf-8")).hexdigest(),
            "type": str(obligation_type or ""),
        }
    )
    sample_group = partition_key or _get(obligation, "sample_id", obligation_map.get("sample_id")) or obligation_id
    return LegalIRProofFeedbackRecord.create(
        obligation_id=obligation_id,
        obligation_type=obligation_type,
        legal_ir_view=legal_ir_view,
        semantic_family=semantic_family,
        semantic_slots=extracted_slots,
        selected_premise_families=tuple(_premise_family(item) for item in selected_premises),
        route_availability=availability,
        route_statuses=route_statuses,
        backend_outcomes=backend_outcomes,
        kernel_reconstruction=kernel,
        counterexample=counterexample,
        minimal_failing_contract=minimal_failing_contract,
        deterministic_trusted=route_deterministic if deterministic_trusted is None else deterministic_trusted,
        repair_label=repair_label or metadata.get("repair_label") or metadata.get("repair_lane") or "none",
        evidence_ids=evidence_ids,
        receipt_ids=resolved_receipts,
        obligation_digest=obligation_hash,
        partition_key=sample_group,
        partition_policy=partition_policy,
        versions=versions,
    )


legal_ir_proof_feedback_record_from_result = build_legal_ir_proof_feedback_record


@dataclass(frozen=True)
class ProofFeedbackReplay:
    """Content-addressed deterministic ordering of feedback records."""

    replay_id: str
    records: tuple[LegalIRProofFeedbackRecord, ...]
    schema_version: str = LEGAL_IR_PROOF_FEEDBACK_REPLAY_VERSION

    @classmethod
    def create(cls, records: Iterable[LegalIRProofFeedbackRecord]) -> "ProofFeedbackReplay":
        ordered = tuple(sorted(records, key=lambda record: record.record_id))
        if len({record.record_id for record in ordered}) != len(ordered):
            raise ProofFeedbackIntegrityError("a replay cannot contain duplicate record IDs")
        payload = {
            "record_ids": [record.record_id for record in ordered],
            "schema_version": LEGAL_IR_PROOF_FEEDBACK_REPLAY_VERSION,
        }
        return cls(
            replay_id=f"legal-ir-proof-feedback-replay-{proof_feedback_content_digest(payload)}",
            records=ordered,
        )

    def to_dict(self, *, include_records: bool = False) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "record_count": len(self.records),
            "record_ids": [record.record_id for record in self.records],
            "replay_id": self.replay_id,
            "schema_version": self.schema_version,
        }
        if include_records:
            payload["records"] = [record.to_dict() for record in self.records]
        return payload


class ProofFeedbackStore:
    """Filesystem content-addressed store with atomic idempotent writes."""

    def __init__(self, root: str | os.PathLike[str]) -> None:
        self.root = Path(root)
        self.records_path = self.root / "records"

    def _path(self, record_id: str) -> Path:
        _require_safe_identifier(record_id, "record_id")
        if not record_id.startswith("legal-ir-proof-feedback-"):
            raise ProofFeedbackError("record_id has an invalid namespace")
        return self.records_path / f"{record_id}.json"

    def put(self, record: LegalIRProofFeedbackRecord) -> bool:
        """Persist a record atomically; return ``False`` for an exact duplicate."""

        # Re-parse before writing so manually constructed/mutated mappings can
        # never bypass the source-free and content-address checks.
        checked = LegalIRProofFeedbackRecord.from_dict(record.to_dict())
        path = self._path(checked.record_id)
        self.records_path.mkdir(parents=True, exist_ok=True)
        encoded = (canonical_proof_feedback_json(checked.to_dict()) + "\n").encode("utf-8")
        if path.exists():
            existing = path.read_bytes()
            if existing != encoded:
                raise ProofFeedbackIntegrityError(f"content-address collision at {path}")
            return False
        descriptor, temporary_name = tempfile.mkstemp(prefix=".proof-feedback-", suffix=".tmp", dir=self.records_path)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            # Another process may win the same idempotent write.  os.replace is
            # safe because identical IDs have already been content-validated.
            if path.exists():
                if path.read_bytes() != encoded:
                    raise ProofFeedbackIntegrityError(f"content-address collision at {path}")
                return False
            os.replace(temporary_name, path)
            temporary_name = ""
            return True
        finally:
            if temporary_name:
                try:
                    os.unlink(temporary_name)
                except FileNotFoundError:
                    pass

    def put_many(self, records: Iterable[LegalIRProofFeedbackRecord]) -> int:
        return sum(1 for record in records if self.put(record))

    def get(self, record_id: str) -> LegalIRProofFeedbackRecord:
        value = json.loads(self._path(record_id).read_text(encoding="utf-8"))
        return LegalIRProofFeedbackRecord.from_dict(value)

    def __iter__(self) -> Iterator[LegalIRProofFeedbackRecord]:
        if not self.records_path.exists():
            return
        for path in sorted(self.records_path.glob("legal-ir-proof-feedback-*.json")):
            value = json.loads(path.read_text(encoding="utf-8"))
            record = LegalIRProofFeedbackRecord.from_dict(value)
            if path.stem != record.record_id:
                raise ProofFeedbackIntegrityError(f"record filename does not match content at {path}")
            yield record

    def replay(
        self,
        *,
        partition: Optional[ProofFeedbackPartition | str] = None,
        versions: Optional[ProofFeedbackVersions] = None,
        trusted_only: bool = False,
    ) -> ProofFeedbackReplay:
        selected_partition = ProofFeedbackPartition(partition) if partition is not None else None
        records = (
            record
            for record in self
            if (selected_partition is None or record.partition == selected_partition)
            and (versions is None or record.versions == versions)
            and (not trusted_only or record.eligible_for_training)
        )
        return ProofFeedbackReplay.create(records)

    def export_jsonl(
        self,
        path: str | os.PathLike[str],
        *,
        partition: Optional[ProofFeedbackPartition | str] = None,
        versions: Optional[ProofFeedbackVersions] = None,
        trusted_only: bool = False,
    ) -> ProofFeedbackReplay:
        replay = self.replay(partition=partition, versions=versions, trusted_only=trusted_only)
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
                for record in replay.records:
                    handle.write(canonical_proof_feedback_json(record.to_dict()))
                    handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_name, destination)
            temporary_name = ""
        finally:
            if temporary_name:
                try:
                    os.unlink(temporary_name)
                except FileNotFoundError:
                    pass
        return replay

    def import_jsonl(self, path: str | os.PathLike[str]) -> ProofFeedbackReplay:
        records = load_proof_feedback_jsonl(path)
        self.put_many(records)
        return ProofFeedbackReplay.create(records)


LegalIRProofFeedbackStore = ProofFeedbackStore


def load_proof_feedback_jsonl(path: str | os.PathLike[str]) -> tuple[LegalIRProofFeedbackRecord, ...]:
    records: list[LegalIRProofFeedbackRecord] = []
    seen: set[str] = set()
    with Path(path).open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
                record = LegalIRProofFeedbackRecord.from_dict(value)
            except (json.JSONDecodeError, ProofFeedbackError, TypeError) as exc:
                raise ProofFeedbackIntegrityError(
                    f"invalid proof-feedback record at line {line_number}: {exc}"
                ) from exc
            if record.record_id in seen:
                raise ProofFeedbackIntegrityError(f"duplicate proof-feedback record at line {line_number}")
            seen.add(record.record_id)
            records.append(record)
    return tuple(records)


def write_proof_feedback_jsonl(
    path: str | os.PathLike[str], records: Iterable[LegalIRProofFeedbackRecord]
) -> ProofFeedbackReplay:
    replay = ProofFeedbackReplay.create(records)
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            for record in replay.records:
                handle.write(canonical_proof_feedback_json(record.to_dict()))
                handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, destination)
        temporary_name = ""
    finally:
        if temporary_name:
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass
    return replay


__all__ = [
    "DEFAULT_PROOF_FEEDBACK_HOLDOUT_FRACTION",
    "DEFAULT_PROOF_FEEDBACK_PARTITION_SALT",
    "LEGAL_IR_PROOF_FEEDBACK_PARTITION_VERSION",
    "LEGAL_IR_PROOF_FEEDBACK_REPLAY_VERSION",
    "LEGAL_IR_PROOF_FEEDBACK_SCHEMA_VERSION",
    "LEGAL_IR_PROOF_FEEDBACK_STORE_VERSION",
    "KernelReconstructionFeedback",
    "LegalIRProofFeedbackRecord",
    "LegalIRProofFeedbackStore",
    "MinimalFailingContractFeedback",
    "ProofFeedbackError",
    "ProofFeedbackIntegrityError",
    "ProofFeedbackLabel",
    "ProofFeedbackPartition",
    "ProofFeedbackPartitionError",
    "ProofFeedbackPartitionPolicy",
    "ProofFeedbackRecord",
    "ProofFeedbackReplay",
    "ProofFeedbackStore",
    "ProofFeedbackTrustError",
    "ProofFeedbackTrustStatus",
    "ProofFeedbackVersions",
    "VerifiedCounterexampleFeedback",
    "build_legal_ir_proof_feedback_record",
    "canonical_proof_feedback_json",
    "deterministic_proof_feedback_partition",
    "legal_ir_proof_feedback_record_from_result",
    "load_proof_feedback_jsonl",
    "proof_feedback_content_digest",
    "write_proof_feedback_jsonl",
]
