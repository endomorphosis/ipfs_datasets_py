"""Closed IncrementalProofSealer evidence classes, modes, kinds, and statuses.

Datasets semantic authority (IPS-005).  This module is an inert, versioned
contract surface: finite discriminated records, exact establishes / does-not-
establish statements, and fail-closed unknown rejection.

Rules:

* no generic ``zk_verified`` / ``passed`` boolean may collapse classes;
* only ``DirectExecutionProof`` may use direct-computation claim language;
* ``ProofMode.SIMULATED`` can never produce ``sealed_full`` or
  ``sealed_incremental`` under production policy;
* ``integrity_verified`` satisfies only an integrity requirement;
* ``signed_assertion_verified`` satisfies only a policy-admitted trusted
  assertion;
* ``proved`` carries only the exact theorem / direct / aggregation statement.

Interfaces: ``IntegrityCommitment``, ``SignedExecutionReceipt``,
``ReceiptAggregationZkProof``, ``DirectExecutionProof``,
``IncrementalCommitSeal``, ``ProofMode``, ``ProofUnitKind``,
``ProofTerminalStatus``, ``SealStatus``.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Any, Final

SCHEMA_MAJOR: Final[int] = 1
SCHEMA_VERSION: Final[str] = f"{SCHEMA_MAJOR}.0.0"
EVIDENCE_SUBSET: Final[str] = "ips/proof-evidence-classes@1"
EVIDENCE_NAMESPACE: Final[str] = (
    "ipfs_datasets_py/logic/zkp/incremental_sealing/evidence"
)

MAX_IDENTIFIER_BYTES: Final[int] = 512
MAX_HEX_DIGEST_CHARS: Final[int] = 128

_GENERIC_OVERCLAIM_TOKENS: Final[frozenset[str]] = frozenset(
    {
        "zk_verified",
        "zkverified",
        "passed",
        "verified_true",
        "generic_verified",
    }
)


class EvidenceClassError(ValueError):
    """Closed evidence, mode, kind, or status contract violation."""


class ProofMode(str, Enum):
    DIRECT_EXECUTION_PROOF = "direct_execution_proof"
    THEOREM_CERTIFICATE = "theorem_certificate"
    SIGNED_RECEIPT = "signed_receipt"
    RECEIPT_AGGREGATION = "receipt_aggregation"
    INTEGRITY_ONLY = "integrity_only"
    SIMULATED = "simulated"


class ProofUnitKind(str, Enum):
    STATIC_ANALYSIS = "static_analysis"
    TYPE_CHECK = "type_check"
    UNIT_TEST = "unit_test"
    INTEGRATION_TEST = "integration_test"
    PROPERTY_TEST = "property_test"
    FORMAL_OBLIGATION = "formal_obligation"
    DIRECT_ZK_COMPUTATION = "direct_zk_computation"
    RECEIPT_AGGREGATION = "receipt_aggregation"
    RELEASE_INVARIANT = "release_invariant"


class ProofTerminalStatus(str, Enum):
    PROVED = "proved"
    DISPROVED = "disproved"
    INTEGRITY_VERIFIED = "integrity_verified"
    SIGNED_ASSERTION_VERIFIED = "signed_assertion_verified"
    NOT_MODELED = "not_modeled"
    FAILED = "failed"
    PROOF_FAILED = "proof_failed"
    UNKNOWN = "unknown"
    TIMEOUT = "timeout"
    UNAVAILABLE = "unavailable"
    CANCELLED = "cancelled"
    INVALID = "invalid"
    SIMULATED = "simulated"
    STALE = "stale"


class SealStatus(str, Enum):
    SEALED_FULL = "sealed_full"
    SEALED_INCREMENTAL = "sealed_incremental"
    VERIFICATION_FAILED = "verification_failed"
    PROOF_FAILED = "proof_failed"
    UNKNOWN = "unknown"
    TIMEOUT = "timeout"
    UNAVAILABLE = "unavailable"
    STALE_PARENT = "stale_parent"
    INVALID_CACHE = "invalid_cache"
    INCOMPLETE_MANIFEST = "incomplete_manifest"
    FULL_REPROOF_REQUIRED = "full_reproof_required"
    CANCELLED = "cancelled"
    SIMULATED_ONLY = "simulated_only"


class EvidenceClass(str, Enum):
    INTEGRITY_COMMITMENT = "IntegrityCommitment"
    SIGNED_EXECUTION_RECEIPT = "SignedExecutionReceipt"
    RECEIPT_AGGREGATION_ZK_PROOF = "ReceiptAggregationZkProof"
    DIRECT_EXECUTION_PROOF = "DirectExecutionProof"
    INCREMENTAL_COMMIT_SEAL = "IncrementalCommitSeal"


def closed_proof_mode_values() -> frozenset[str]:
    return frozenset(item.value for item in ProofMode)


def closed_proof_unit_kind_values() -> frozenset[str]:
    return frozenset(item.value for item in ProofUnitKind)


def closed_terminal_status_values() -> frozenset[str]:
    return frozenset(item.value for item in ProofTerminalStatus)


def closed_seal_status_values() -> frozenset[str]:
    return frozenset(item.value for item in SealStatus)


def closed_evidence_class_names() -> frozenset[str]:
    return frozenset(item.value for item in EvidenceClass)


def parse_proof_mode(value: Any) -> ProofMode:
    return _parse_closed_enum(ProofMode, value, "ProofMode")


def parse_proof_unit_kind(value: Any) -> ProofUnitKind:
    return _parse_closed_enum(ProofUnitKind, value, "ProofUnitKind")


def parse_terminal_status(value: Any) -> ProofTerminalStatus:
    return _parse_closed_enum(ProofTerminalStatus, value, "ProofTerminalStatus")


def parse_seal_status(value: Any) -> SealStatus:
    return _parse_closed_enum(SealStatus, value, "SealStatus")


def _parse_closed_enum(enum_cls: type[Enum], value: Any, label: str) -> Any:
    if isinstance(value, enum_cls):
        return value
    if not isinstance(value, str) or not value.strip():
        raise EvidenceClassError(f"{label} must be a non-empty closed string")
    try:
        return enum_cls(value.strip())
    except ValueError as exc:
        raise EvidenceClassError(
            f"unknown {label} {value!r}; closed set is "
            f"{sorted(item.value for item in enum_cls)}"
        ) from exc


def _require_identifier(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise EvidenceClassError(f"{field} must be a non-empty string")
    text = value.strip()
    if len(text.encode("utf-8")) > MAX_IDENTIFIER_BYTES:
        raise EvidenceClassError(f"{field} exceeds {MAX_IDENTIFIER_BYTES} bytes")
    return text


def _require_digest(value: Any, field: str) -> str:
    text = _require_identifier(value, field)
    if not (
        text.startswith("sha256:")
        and len(text) == 7 + 64
        and all(char in "0123456789abcdef" for char in text[7:])
    ) and not (
        text.startswith("b")
        and 20 <= len(text) <= MAX_HEX_DIGEST_CHARS
    ):
        if not (len(text) >= 8):
            raise EvidenceClassError(f"{field} is not a digest or CID")
    return text


def _canonical_json(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _reject_generic_overclaim(payload: Mapping[str, Any]) -> None:
    keys = {str(key).strip().casefold().replace("-", "_") for key in payload}
    overlap = keys & _GENERIC_OVERCLAIM_TOKENS
    if overlap:
        raise EvidenceClassError(
            f"generic overclaim fields are forbidden: {sorted(overlap)}"
        )
    if payload.get("zk_verified") is True or payload.get("passed") is True:
        raise EvidenceClassError("generic zk_verified/passed boolean is forbidden")


def production_seal_allowed(mode: ProofMode, status: SealStatus) -> bool:
    """False when a simulated required unit is presented as a production seal."""

    if mode is ProofMode.SIMULATED and status in {
        SealStatus.SEALED_FULL,
        SealStatus.SEALED_INCREMENTAL,
    }:
        return False
    return True


def assert_production_seal_allowed(mode: ProofMode, status: SealStatus) -> None:
    if not production_seal_allowed(mode, status):
        raise EvidenceClassError(
            "simulated required units force simulated_only and cannot produce "
            "sealed_full or sealed_incremental under production policy"
        )


def status_satisfies_class(
    status: ProofTerminalStatus,
    evidence_class: EvidenceClass,
) -> bool:
    """Statement- and mode-specific acceptance.  No generic upgrade path."""

    if status is ProofTerminalStatus.INTEGRITY_VERIFIED:
        return evidence_class is EvidenceClass.INTEGRITY_COMMITMENT
    if status is ProofTerminalStatus.SIGNED_ASSERTION_VERIFIED:
        return evidence_class is EvidenceClass.SIGNED_EXECUTION_RECEIPT
    if status is ProofTerminalStatus.PROVED:
        return evidence_class in {
            EvidenceClass.DIRECT_EXECUTION_PROOF,
            EvidenceClass.RECEIPT_AGGREGATION_ZK_PROOF,
            EvidenceClass.INCREMENTAL_COMMIT_SEAL,
        }
    return False


@dataclass(frozen=True, slots=True)
class IntegrityCommitment:
    """Exact bytes, digest, CID, and Merkle inclusion.  Not execution."""

    digest: str
    cid: str
    merkle_inclusion: str
    byte_length: int
    schema: str = f"{EVIDENCE_NAMESPACE}/integrity-commitment@{SCHEMA_MAJOR}"

    ESTABLISHES: Final[str] = (
        "exact bytes, digest, CID, and Merkle inclusion"
    )
    DOES_NOT_ESTABLISH: Final[str] = "execution or semantic correctness"

    def __post_init__(self) -> None:
        _require_digest(self.digest, "digest")
        _require_digest(self.cid, "cid")
        _require_identifier(self.merkle_inclusion, "merkle_inclusion")
        if type(self.byte_length) is not int or self.byte_length < 0:
            raise EvidenceClassError("byte_length must be a non-negative int")

    def to_canonical(self) -> dict[str, Any]:
        return {
            "evidence_class": EvidenceClass.INTEGRITY_COMMITMENT.value,
            "schema": self.schema,
            "digest": self.digest,
            "cid": self.cid,
            "merkle_inclusion": self.merkle_inclusion,
            "byte_length": self.byte_length,
            "establishes": self.ESTABLISHES,
            "does_not_establish": self.DOES_NOT_ESTABLISH,
        }

    def to_canonical_json(self) -> str:
        return _canonical_json(self.to_canonical())

    @classmethod
    def from_canonical(cls, payload: Mapping[str, Any]) -> IntegrityCommitment:
        _reject_generic_overclaim(payload)
        if payload.get("evidence_class") != EvidenceClass.INTEGRITY_COMMITMENT.value:
            raise EvidenceClassError("payload is not IntegrityCommitment")
        return cls(
            digest=str(payload.get("digest") or ""),
            cid=str(payload.get("cid") or ""),
            merkle_inclusion=str(payload.get("merkle_inclusion") or ""),
            byte_length=int(payload.get("byte_length")),
        )


@dataclass(frozen=True, slots=True)
class SignedExecutionReceipt:
    """Allowlisted signer asserted execution.  Not independent observation."""

    signer_id: str
    receipt_digest: str
    signature: str
    statement: str
    schema: str = f"{EVIDENCE_NAMESPACE}/signed-execution-receipt@{SCHEMA_MAJOR}"

    ESTABLISHES: Final[str] = (
        "an allowlisted signer asserted execution; receipt integrity and "
        "signature validity"
    )
    DOES_NOT_ESTABLISH: Final[str] = (
        "independent proof that execution occurred without trusting the signer"
    )

    def __post_init__(self) -> None:
        _require_identifier(self.signer_id, "signer_id")
        _require_digest(self.receipt_digest, "receipt_digest")
        _require_identifier(self.signature, "signature")
        _require_identifier(self.statement, "statement")

    def to_canonical(self) -> dict[str, Any]:
        return {
            "evidence_class": EvidenceClass.SIGNED_EXECUTION_RECEIPT.value,
            "schema": self.schema,
            "signer_id": self.signer_id,
            "receipt_digest": self.receipt_digest,
            "signature": self.signature,
            "statement": self.statement,
            "establishes": self.ESTABLISHES,
            "does_not_establish": self.DOES_NOT_ESTABLISH,
        }

    def to_canonical_json(self) -> str:
        return _canonical_json(self.to_canonical())

    @classmethod
    def from_canonical(cls, payload: Mapping[str, Any]) -> SignedExecutionReceipt:
        _reject_generic_overclaim(payload)
        if payload.get("evidence_class") != EvidenceClass.SIGNED_EXECUTION_RECEIPT.value:
            raise EvidenceClassError("payload is not SignedExecutionReceipt")
        return cls(
            signer_id=str(payload.get("signer_id") or ""),
            receipt_digest=str(payload.get("receipt_digest") or ""),
            signature=str(payload.get("signature") or ""),
            statement=str(payload.get("statement") or ""),
        )


@dataclass(frozen=True, slots=True)
class ReceiptAggregationZkProof:
    """Admitted receipt fields satisfy the aggregation circuit."""

    circuit_id: str
    receipt_digests: tuple[str, ...]
    proof_cid: str
    schema: str = f"{EVIDENCE_NAMESPACE}/receipt-aggregation-zk-proof@{SCHEMA_MAJOR}"

    ESTABLISHES: Final[str] = (
        "admitted committed receipt fields satisfy the aggregation circuit; "
        "exact required receipt set/count/order has no blocking circuit status"
    )
    DOES_NOT_ESTABLISH: Final[str] = (
        "underlying tests ran unless signature verification and signer trust "
        "are inside the declared statement"
    )

    def __post_init__(self) -> None:
        _require_identifier(self.circuit_id, "circuit_id")
        _require_digest(self.proof_cid, "proof_cid")
        if not isinstance(self.receipt_digests, tuple) or not self.receipt_digests:
            raise EvidenceClassError("receipt_digests must be a non-empty tuple")
        if list(self.receipt_digests) != sorted(self.receipt_digests):
            raise EvidenceClassError("receipt_digests must be canonically sorted")
        if len(set(self.receipt_digests)) != len(self.receipt_digests):
            raise EvidenceClassError("receipt_digests must be unique")
        for digest in self.receipt_digests:
            _require_digest(digest, "receipt_digest")

    def to_canonical(self) -> dict[str, Any]:
        return {
            "evidence_class": EvidenceClass.RECEIPT_AGGREGATION_ZK_PROOF.value,
            "schema": self.schema,
            "circuit_id": self.circuit_id,
            "receipt_digests": list(self.receipt_digests),
            "proof_cid": self.proof_cid,
            "establishes": self.ESTABLISHES,
            "does_not_establish": self.DOES_NOT_ESTABLISH,
        }

    def to_canonical_json(self) -> str:
        return _canonical_json(self.to_canonical())

    @classmethod
    def from_canonical(cls, payload: Mapping[str, Any]) -> ReceiptAggregationZkProof:
        _reject_generic_overclaim(payload)
        if payload.get("evidence_class") != EvidenceClass.RECEIPT_AGGREGATION_ZK_PROOF.value:
            raise EvidenceClassError("payload is not ReceiptAggregationZkProof")
        raw = payload.get("receipt_digests")
        if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
            raise EvidenceClassError("receipt_digests must be a sequence")
        return cls(
            circuit_id=str(payload.get("circuit_id") or ""),
            receipt_digests=tuple(str(item) for item in raw),
            proof_cid=str(payload.get("proof_cid") or ""),
        )


@dataclass(frozen=True, slots=True)
class DirectExecutionProof:
    """Declared program/verifier ran over committed inputs."""

    program_id: str
    input_commitment: str
    output_commitment: str
    proof_system_id: str
    proof_cid: str
    schema: str = f"{EVIDENCE_NAMESPACE}/direct-execution-proof@{SCHEMA_MAJOR}"

    ESTABLISHES: Final[str] = (
        "the declared program/verifier ran inside the proof system over "
        "committed inputs and produced the committed output/property"
    )
    DOES_NOT_ESTABLISH: Final[str] = (
        "correctness beyond that exact program, inputs, outputs, and "
        "proof-system assumptions"
    )

    def __post_init__(self) -> None:
        _require_identifier(self.program_id, "program_id")
        _require_digest(self.input_commitment, "input_commitment")
        _require_digest(self.output_commitment, "output_commitment")
        _require_identifier(self.proof_system_id, "proof_system_id")
        _require_digest(self.proof_cid, "proof_cid")

    def to_canonical(self) -> dict[str, Any]:
        return {
            "evidence_class": EvidenceClass.DIRECT_EXECUTION_PROOF.value,
            "schema": self.schema,
            "program_id": self.program_id,
            "input_commitment": self.input_commitment,
            "output_commitment": self.output_commitment,
            "proof_system_id": self.proof_system_id,
            "proof_cid": self.proof_cid,
            "establishes": self.ESTABLISHES,
            "does_not_establish": self.DOES_NOT_ESTABLISH,
            "direct_computation_claim": True,
        }

    def to_canonical_json(self) -> str:
        return _canonical_json(self.to_canonical())

    @classmethod
    def from_canonical(cls, payload: Mapping[str, Any]) -> DirectExecutionProof:
        _reject_generic_overclaim(payload)
        if payload.get("evidence_class") != EvidenceClass.DIRECT_EXECUTION_PROOF.value:
            raise EvidenceClassError("payload is not DirectExecutionProof")
        if payload.get("direct_computation_claim") is not True:
            raise EvidenceClassError(
                "direct execution claims require DirectExecutionProof "
                "with direct_computation_claim=true"
            )
        return cls(
            program_id=str(payload.get("program_id") or ""),
            input_commitment=str(payload.get("input_commitment") or ""),
            output_commitment=str(payload.get("output_commitment") or ""),
            proof_system_id=str(payload.get("proof_system_id") or ""),
            proof_cid=str(payload.get("proof_cid") or ""),
        )


@dataclass(frozen=True, slots=True)
class IncrementalCommitSeal:
    """Accepted parent, transition, leaves, manifest, and new verification root."""

    parent_seal_cid: str
    transition_id: str
    reused_leaf_cids: tuple[str, ...]
    replacement_leaf_cids: tuple[str, ...]
    manifest_cid: str
    verification_root: str
    schema: str = f"{EVIDENCE_NAMESPACE}/incremental-commit-seal@{SCHEMA_MAJOR}"

    ESTABLISHES: Final[str] = (
        "an accepted parent, explicit state transition, valid reused/"
        "replacement leaves, complete new manifest, and new repository "
        "verification root"
    )
    DOES_NOT_ESTABLISH: Final[str] = (
        "arbitrary repository correctness or direct test execution unless "
        "child leaves prove it"
    )

    def __post_init__(self) -> None:
        _require_digest(self.parent_seal_cid, "parent_seal_cid")
        _require_identifier(self.transition_id, "transition_id")
        _require_digest(self.manifest_cid, "manifest_cid")
        _require_digest(self.verification_root, "verification_root")
        for field_name, values in (
            ("reused_leaf_cids", self.reused_leaf_cids),
            ("replacement_leaf_cids", self.replacement_leaf_cids),
        ):
            if not isinstance(values, tuple):
                raise EvidenceClassError(f"{field_name} must be a tuple")
            if list(values) != sorted(values):
                raise EvidenceClassError(f"{field_name} must be canonically sorted")
            if len(set(values)) != len(values):
                raise EvidenceClassError(f"{field_name} must be unique")
            for item in values:
                _require_digest(item, field_name)

    def to_canonical(self) -> dict[str, Any]:
        return {
            "evidence_class": EvidenceClass.INCREMENTAL_COMMIT_SEAL.value,
            "schema": self.schema,
            "parent_seal_cid": self.parent_seal_cid,
            "transition_id": self.transition_id,
            "reused_leaf_cids": list(self.reused_leaf_cids),
            "replacement_leaf_cids": list(self.replacement_leaf_cids),
            "manifest_cid": self.manifest_cid,
            "verification_root": self.verification_root,
            "establishes": self.ESTABLISHES,
            "does_not_establish": self.DOES_NOT_ESTABLISH,
        }

    def to_canonical_json(self) -> str:
        return _canonical_json(self.to_canonical())

    @classmethod
    def from_canonical(cls, payload: Mapping[str, Any]) -> IncrementalCommitSeal:
        _reject_generic_overclaim(payload)
        if payload.get("evidence_class") != EvidenceClass.INCREMENTAL_COMMIT_SEAL.value:
            raise EvidenceClassError("payload is not IncrementalCommitSeal")

        def _tuple(field: str) -> tuple[str, ...]:
            raw = payload.get(field)
            if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
                raise EvidenceClassError(f"{field} must be a sequence")
            return tuple(str(item) for item in raw)

        return cls(
            parent_seal_cid=str(payload.get("parent_seal_cid") or ""),
            transition_id=str(payload.get("transition_id") or ""),
            reused_leaf_cids=_tuple("reused_leaf_cids"),
            replacement_leaf_cids=_tuple("replacement_leaf_cids"),
            manifest_cid=str(payload.get("manifest_cid") or ""),
            verification_root=str(payload.get("verification_root") or ""),
        )


_EVIDENCE_LOADERS = {
    EvidenceClass.INTEGRITY_COMMITMENT.value: IntegrityCommitment.from_canonical,
    EvidenceClass.SIGNED_EXECUTION_RECEIPT.value: SignedExecutionReceipt.from_canonical,
    EvidenceClass.RECEIPT_AGGREGATION_ZK_PROOF.value: (
        ReceiptAggregationZkProof.from_canonical
    ),
    EvidenceClass.DIRECT_EXECUTION_PROOF.value: DirectExecutionProof.from_canonical,
    EvidenceClass.INCREMENTAL_COMMIT_SEAL.value: IncrementalCommitSeal.from_canonical,
}


def evidence_from_canonical(
    payload: Mapping[str, Any],
) -> (
    IntegrityCommitment
    | SignedExecutionReceipt
    | ReceiptAggregationZkProof
    | DirectExecutionProof
    | IncrementalCommitSeal
):
    if not isinstance(payload, Mapping):
        raise EvidenceClassError("evidence payload must be a mapping")
    _reject_generic_overclaim(payload)
    class_name = str(payload.get("evidence_class") or "")
    loader = _EVIDENCE_LOADERS.get(class_name)
    if loader is None:
        raise EvidenceClassError(
            f"unknown evidence class {class_name!r}; closed set is "
            f"{sorted(closed_evidence_class_names())}"
        )
    return loader(payload)


def require_direct_execution_for_claim(payload: Mapping[str, Any]) -> DirectExecutionProof:
    """Reject direct-computation language unless the class is DirectExecutionProof."""

    if payload.get("direct_computation_claim") is True:
        if payload.get("evidence_class") != EvidenceClass.DIRECT_EXECUTION_PROOF.value:
            raise EvidenceClassError(
                "direct execution claims require DirectExecutionProof"
            )
        return DirectExecutionProof.from_canonical(payload)
    evidence = evidence_from_canonical(payload)
    if isinstance(evidence, DirectExecutionProof):
        return evidence
    raise EvidenceClassError("direct execution claims require DirectExecutionProof")
