"""Legacy ZK / test / proof receipt migration (IPS-012).

Classify existing receipt and proof payloads into honest IncrementalProofSealer
assurance classes without upgrading their actual meaning.

Rules:

* accept / adapt / reject are explicit migration dispositions;
* adapters never promote integrity, structural, unsigned, or simulated
  evidence to signed, direct-execution, or production seal authority;
* classification is pure and hermetic (no optional imports, network, process,
  install, key generation, or user-state access);
* every known legacy path from the datasets inventory is named and labeled.

Interfaces: ``classify_legacy_receipt``, ``LegacyReceiptClassification``,
``MigrationDisposition``.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Any, Final

from .evidence import (
    DirectExecutionProof,
    EvidenceClass,
    EvidenceClassError,
    IncrementalCommitSeal,
    IntegrityCommitment,
    ProofMode,
    ReceiptAggregationZkProof,
    SignedExecutionReceipt,
    evidence_from_canonical,
)

MIGRATION_SUBSET: Final[str] = "ips/legacy-receipt-migration@1"
PUBLIC_API_SUBSET: Final[str] = "ips/datasets-public-api@1"
MIGRATION_NAMESPACE: Final[str] = (
    "ipfs_datasets_py/logic/zkp/incremental_sealing/migration"
)
SCHEMA_MAJOR: Final[int] = 1
LEGACY_CLASSIFICATION_SCHEMA: Final[str] = (
    f"{MIGRATION_NAMESPACE}/legacy-receipt-classification@{SCHEMA_MAJOR}"
)

MAX_IDENTIFIER_BYTES: Final[int] = 512
MAX_REASON_BYTES: Final[int] = 1_024
MAX_PAYLOAD_KEYS: Final[int] = 256

# Closed inventory path families.  Values are stable classifier tokens, not
# filesystem probes; cold import never opens these paths.
LEGACY_PATH_FAMILIES: Final[tuple[str, ...]] = (
    "incremental_sealing_canonical",
    "test_execution_certificate",
    "test_pass_statement",
    "proof_receipt_attestation",
    "simulated_zkp_proof",
    "groth16_direct_computation",
    "integrity_cache",
    "event_dag_hash_commitment",
    "wallet_simulated",
    "pdf_form_simulated",
    "vk_registry_integrity",
    "canonicalization_commitment",
    "unknown",
)


class MigrationError(EvidenceClassError):
    """Legacy receipt migration contract violation."""


class MigrationDisposition(str, Enum):
    """Closed accept / adapt / reject outcomes for legacy payloads."""

    ACCEPT = "accept"
    ADAPT = "adapt"
    REJECT = "reject"


class LegacyAssurance(str, Enum):
    """Honest assurance retained after migration (never upgraded)."""

    INTEGRITY_ONLY = "integrity_only"
    STRUCTURAL = "structural"
    PREDICATE_ONLY = "predicate_only"
    SIGNED_RECEIPT = "signed_receipt"
    RECEIPT_AGGREGATION = "receipt_aggregation"
    DIRECT_EXECUTION = "direct_execution"
    SIMULATED = "simulated"
    UNKNOWN = "unknown"


def closed_migration_dispositions() -> frozenset[str]:
    return frozenset(item.value for item in MigrationDisposition)


def closed_legacy_assurances() -> frozenset[str]:
    return frozenset(item.value for item in LegacyAssurance)


def closed_legacy_path_families() -> frozenset[str]:
    return frozenset(LEGACY_PATH_FAMILIES)


def _require_text(value: Any, field: str, *, maximum: int = MAX_IDENTIFIER_BYTES) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MigrationError(f"{field} must be a non-empty string")
    text = value.strip()
    if len(text.encode("utf-8")) > maximum:
        raise MigrationError(f"{field} exceeds {maximum} bytes")
    return text


def _canonical_json(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _lower_keys(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {str(key).strip().casefold(): value for key, value in payload.items()}


def _as_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    return ""


def _joined_text_fields(payload: Mapping[str, Any], *keys: str) -> str:
    parts: list[str] = []
    for key in keys:
        text = _as_text(payload.get(key))
        if text:
            parts.append(text)
    return " ".join(parts).casefold()


def _contains_any(haystack: str, needles: Sequence[str]) -> bool:
    return any(token in haystack for token in needles)


def _has_signature_material(payload: Mapping[str, Any]) -> bool:
    lowered = _lower_keys(payload)
    for key in (
        "signature",
        "signature_hex",
        "signature_bytes",
        "signer_signature",
        "sig",
    ):
        value = lowered.get(key)
        if isinstance(value, str) and value.strip():
            return True
        if isinstance(value, (bytes, bytearray)) and value:
            return True
    return False


def _looks_simulated(payload: Mapping[str, Any]) -> bool:
    text = _joined_text_fields(
        payload,
        "backend",
        "backend_mode",
        "backend_id",
        "proof_system",
        "proof_system_id",
        "mode",
        "proof_mode",
        "kind",
        "interface",
        "schema",
        "authority",
        "issuer_id",
        "metadata",
    )
    markers = (
        "simulated",
        "simulation",
        "mock",
        "demo",
        "fake",
        "fallback",
        "educational",
    )
    if _contains_any(text, markers):
        return True
    nested = payload.get("metadata")
    if isinstance(nested, Mapping):
        return _looks_simulated(nested)
    return False


def _looks_wallet_or_pdf(payload: Mapping[str, Any]) -> bool:
    text = _joined_text_fields(
        payload,
        "path",
        "source_path",
        "module",
        "family",
        "interface",
        "schema",
        "kind",
        "authority",
    )
    return _contains_any(
        text,
        (
            "wallet/proofs",
            "wallet_proof",
            "pdf_form",
            "pdf-form",
            "worldcoin",
            "form_completion_certificate",
        ),
    )


def _looks_event_dag(payload: Mapping[str, Any]) -> bool:
    text = _joined_text_fields(
        payload,
        "path",
        "source_path",
        "module",
        "family",
        "interface",
        "schema",
        "kind",
        "authority",
        "proof_system_id",
    )
    return _contains_any(
        text,
        (
            "event_dag",
            "event-dag",
            "dag_compaction",
            "profile_f",
            "merkle_clock",
            "pseudo_cid",
        ),
    )


def _looks_integrity_cache(payload: Mapping[str, Any]) -> bool:
    text = _joined_text_fields(
        payload,
        "path",
        "source_path",
        "module",
        "family",
        "interface",
        "schema",
        "kind",
        "cache_kind",
        "authority",
    )
    return _contains_any(
        text,
        (
            "proof_cache",
            "integrity_cache",
            "cec_proof_cache",
            "tdfol_proof_cache",
            "flogic_proof_cache",
            "provekit/cache",
            "common/proof_cache",
            "proof_corpus",
        ),
    )


def _looks_test_pass_statement(payload: Mapping[str, Any]) -> bool:
    text = _joined_text_fields(
        payload,
        "interface",
        "schema",
        "statement_interface",
        "kind",
        "family",
    )
    return _contains_any(
        text,
        (
            "testpassstatementv1",
            "test_pass_statement",
            "test-pass-statement",
            "test_pass@v1",
        ),
    )


def _looks_test_execution_certificate(payload: Mapping[str, Any]) -> bool:
    text = _joined_text_fields(
        payload,
        "interface",
        "schema",
        "kind",
        "family",
        "authority",
    )
    if _contains_any(
        text,
        (
            "testproofcertificate",
            "test-proof-certificate",
            "test_proof_certificate",
            "test_execution_certificate",
            "test-execution-certificate",
        ),
    ):
        return True
    # Structural certificate shape from datasets test_execution_certificate.
    keys = {str(key).casefold() for key in payload}
    certificate_markers = {
        "certificate_id",
        "proof_artifact_cid",
        "execution_key_cid",
        "verifying_key_cid",
    }
    return len(keys & certificate_markers) >= 2


def _looks_proof_receipt_attestation(payload: Mapping[str, Any]) -> bool:
    text = _joined_text_fields(
        payload,
        "interface",
        "schema",
        "kind",
        "family",
        "module",
        "path",
        "authority",
    )
    return _contains_any(
        text,
        (
            "proof_receipt_attestation",
            "proof-receipt-attestation",
            "receipt_attestation",
            "callback_attestation",
        ),
    )


def _looks_canonical_ips(payload: Mapping[str, Any]) -> bool:
    """True only for complete-looking canonical IPS evidence records.

    Partial adapter stubs that merely stamp an ``evidence_class`` label must
    not be treated as already-canonical (that would reject them on re-entry).
    """

    evidence_class = _as_text(payload.get("evidence_class"))
    if evidence_class not in {
        EvidenceClass.INTEGRITY_COMMITMENT.value,
        EvidenceClass.SIGNED_EXECUTION_RECEIPT.value,
        EvidenceClass.RECEIPT_AGGREGATION_ZK_PROOF.value,
        EvidenceClass.DIRECT_EXECUTION_PROOF.value,
        EvidenceClass.INCREMENTAL_COMMIT_SEAL.value,
    }:
        return False
    schema = _as_text(payload.get("schema"))
    if "ipfs_datasets_py/logic/zkp/incremental_sealing" in schema.casefold():
        return True
    # Canonical records always carry claim-boundary fields.
    return bool(_as_text(payload.get("establishes"))) and bool(
        _as_text(payload.get("does_not_establish"))
    )


def _looks_vk_registry(payload: Mapping[str, Any]) -> bool:
    text = _joined_text_fields(
        payload,
        "path",
        "module",
        "family",
        "interface",
        "schema",
        "kind",
    )
    return _contains_any(text, ("vk_registry", "verification_key_registry", "vk-hash"))


def _looks_canonicalization(payload: Mapping[str, Any]) -> bool:
    text = _joined_text_fields(
        payload,
        "path",
        "module",
        "family",
        "interface",
        "schema",
        "kind",
    )
    return _contains_any(
        text,
        (
            "canonicalization",
            "axioms_commitment",
            "tdfol_v1_axioms_commitment",
            "reduced-field",
            "reduced_field",
        ),
    )


def _looks_groth16_direct(payload: Mapping[str, Any]) -> bool:
    text = _joined_text_fields(
        payload,
        "backend",
        "backend_id",
        "proof_system",
        "proof_system_id",
        "circuit_id",
        "interface",
        "schema",
        "kind",
        "family",
    )
    if _looks_simulated(payload):
        return False
    return _contains_any(
        text,
        (
            "groth16",
            "arkworks",
            "provekit",
            "direct_zk",
            "direct_execution",
            "tdfol_v1",
            "bounded_horn",
        ),
    )


def _target_class_for_assurance(assurance: LegacyAssurance) -> EvidenceClass | None:
    mapping = {
        LegacyAssurance.INTEGRITY_ONLY: EvidenceClass.INTEGRITY_COMMITMENT,
        LegacyAssurance.STRUCTURAL: EvidenceClass.INTEGRITY_COMMITMENT,
        LegacyAssurance.PREDICATE_ONLY: None,
        LegacyAssurance.SIGNED_RECEIPT: EvidenceClass.SIGNED_EXECUTION_RECEIPT,
        LegacyAssurance.RECEIPT_AGGREGATION: EvidenceClass.RECEIPT_AGGREGATION_ZK_PROOF,
        LegacyAssurance.DIRECT_EXECUTION: EvidenceClass.DIRECT_EXECUTION_PROOF,
        LegacyAssurance.SIMULATED: None,
        LegacyAssurance.UNKNOWN: None,
    }
    return mapping[assurance]


def _production_seal_allowed(assurance: LegacyAssurance) -> bool:
    return assurance in {
        LegacyAssurance.SIGNED_RECEIPT,
        LegacyAssurance.RECEIPT_AGGREGATION,
        LegacyAssurance.DIRECT_EXECUTION,
    }


@dataclass(frozen=True, slots=True)
class LegacyReceiptClassification:
    """Truthful migration result for one legacy receipt or proof payload."""

    disposition: MigrationDisposition
    path_family: str
    assurance: LegacyAssurance
    proof_mode: ProofMode
    target_evidence_class: str
    establishes: str
    does_not_establish: str
    production_seal_allowed: bool
    reasons: tuple[str, ...]
    adapted_payload: Mapping[str, Any] | None = None
    schema: str = LEGACY_CLASSIFICATION_SCHEMA

    def __post_init__(self) -> None:
        if not isinstance(self.disposition, MigrationDisposition):
            raise MigrationError("disposition must be MigrationDisposition")
        if self.path_family not in LEGACY_PATH_FAMILIES:
            raise MigrationError(f"unknown path_family {self.path_family!r}")
        if not isinstance(self.assurance, LegacyAssurance):
            raise MigrationError("assurance must be LegacyAssurance")
        if not isinstance(self.proof_mode, ProofMode):
            raise MigrationError("proof_mode must be ProofMode")
        target = _require_text(self.target_evidence_class, "target_evidence_class")
        if target not in {item.value for item in EvidenceClass} and target != "n/a":
            raise MigrationError(
                f"target_evidence_class must be a closed EvidenceClass or n/a; "
                f"got {target!r}"
            )
        object.__setattr__(self, "target_evidence_class", target)
        object.__setattr__(
            self, "establishes", _require_text(self.establishes, "establishes", maximum=MAX_REASON_BYTES)
        )
        object.__setattr__(
            self,
            "does_not_establish",
            _require_text(
                self.does_not_establish, "does_not_establish", maximum=MAX_REASON_BYTES
            ),
        )
        if type(self.production_seal_allowed) is not bool:
            raise MigrationError("production_seal_allowed must be bool")
        reasons = tuple(
            _require_text(item, "reason", maximum=MAX_REASON_BYTES)
            for item in self.reasons
        )
        if not reasons:
            raise MigrationError("reasons must be non-empty")
        object.__setattr__(self, "reasons", reasons)
        if self.adapted_payload is not None and not isinstance(
            self.adapted_payload, Mapping
        ):
            raise MigrationError("adapted_payload must be a mapping or None")
        # Never claim production seal authority for simulated/structural paths.
        if self.assurance in {
            LegacyAssurance.SIMULATED,
            LegacyAssurance.STRUCTURAL,
            LegacyAssurance.PREDICATE_ONLY,
            LegacyAssurance.UNKNOWN,
        } and self.production_seal_allowed:
            raise MigrationError(
                "simulated/structural/predicate/unknown assurance cannot allow "
                "production seals"
            )
        if (
            self.disposition is MigrationDisposition.ACCEPT
            and self.assurance is LegacyAssurance.SIMULATED
        ):
            raise MigrationError("simulated evidence cannot be accepted for production")

    def to_canonical(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "disposition": self.disposition.value,
            "path_family": self.path_family,
            "assurance": self.assurance.value,
            "proof_mode": self.proof_mode.value,
            "target_evidence_class": self.target_evidence_class,
            "establishes": self.establishes,
            "does_not_establish": self.does_not_establish,
            "production_seal_allowed": self.production_seal_allowed,
            "reasons": list(self.reasons),
            "adapted_payload": (
                dict(self.adapted_payload) if self.adapted_payload is not None else None
            ),
        }

    def to_canonical_json(self) -> str:
        return _canonical_json(self.to_canonical())


def _result(
    *,
    disposition: MigrationDisposition,
    path_family: str,
    assurance: LegacyAssurance,
    proof_mode: ProofMode,
    establishes: str,
    does_not_establish: str,
    reasons: Sequence[str],
    adapted_payload: Mapping[str, Any] | None = None,
) -> LegacyReceiptClassification:
    target = _target_class_for_assurance(assurance)
    return LegacyReceiptClassification(
        disposition=disposition,
        path_family=path_family,
        assurance=assurance,
        proof_mode=proof_mode,
        target_evidence_class=target.value if target is not None else "n/a",
        establishes=establishes,
        does_not_establish=does_not_establish,
        production_seal_allowed=_production_seal_allowed(assurance),
        reasons=tuple(reasons),
        adapted_payload=adapted_payload,
    )


def classify_legacy_receipt(
    payload: Mapping[str, Any] | None,
    *,
    declared_path: str = "",
) -> LegacyReceiptClassification:
    """Classify one legacy ZK/test/proof receipt without upgrading assurance.

    Returns an explicit accept, adapt, or reject disposition.  Adapters may
    only map fields into canonical evidence shapes when the original meaning
    is preserved exactly.
    """

    if payload is None:
        return _result(
            disposition=MigrationDisposition.REJECT,
            path_family="unknown",
            assurance=LegacyAssurance.UNKNOWN,
            proof_mode=ProofMode.INTEGRITY_ONLY,
            establishes="nothing",
            does_not_establish="any proof, integrity, or execution claim",
            reasons=("payload is null",),
        )
    if not isinstance(payload, Mapping):
        raise MigrationError("legacy receipt payload must be a mapping")
    if len(payload) > MAX_PAYLOAD_KEYS:
        raise MigrationError(
            f"legacy receipt payload exceeds {MAX_PAYLOAD_KEYS} keys"
        )

    # Optional declared path enriches family detection without filesystem I/O.
    working: dict[str, Any] = dict(payload)
    if declared_path:
        working.setdefault("path", _require_text(declared_path, "declared_path"))

    # 1) Canonical IPS evidence records: accept only when parseable as declared.
    if _looks_canonical_ips(working):
        try:
            evidence = evidence_from_canonical(working)
        except (EvidenceClassError, TypeError, ValueError) as exc:
            return _result(
                disposition=MigrationDisposition.REJECT,
                path_family="incremental_sealing_canonical",
                assurance=LegacyAssurance.UNKNOWN,
                proof_mode=ProofMode.INTEGRITY_ONLY,
                establishes="nothing",
                does_not_establish="canonical evidence admission",
                reasons=(
                    "payload claims incremental_sealing schema but failed canonical parse",
                    f"parse_error:{type(exc).__name__}",
                ),
            )
        if isinstance(evidence, IntegrityCommitment):
            mode = ProofMode.INTEGRITY_ONLY
            assurance = LegacyAssurance.INTEGRITY_ONLY
        elif isinstance(evidence, SignedExecutionReceipt):
            mode = ProofMode.SIGNED_RECEIPT
            assurance = LegacyAssurance.SIGNED_RECEIPT
        elif isinstance(evidence, ReceiptAggregationZkProof):
            mode = ProofMode.RECEIPT_AGGREGATION
            assurance = LegacyAssurance.RECEIPT_AGGREGATION
        elif isinstance(evidence, DirectExecutionProof):
            mode = ProofMode.DIRECT_EXECUTION_PROOF
            assurance = LegacyAssurance.DIRECT_EXECUTION
        elif isinstance(evidence, IncrementalCommitSeal):
            # Parent-bound seals are accepted as declared transition evidence;
            # they do not upgrade child leaves to direct execution.
            mode = ProofMode.RECEIPT_AGGREGATION
            assurance = LegacyAssurance.RECEIPT_AGGREGATION
        else:
            return _result(
                disposition=MigrationDisposition.REJECT,
                path_family="incremental_sealing_canonical",
                assurance=LegacyAssurance.UNKNOWN,
                proof_mode=ProofMode.INTEGRITY_ONLY,
                establishes="nothing",
                does_not_establish="canonical evidence admission",
                reasons=("unsupported canonical evidence instance type",),
            )
        canonical = evidence.to_canonical()
        return _result(
            disposition=MigrationDisposition.ACCEPT,
            path_family="incremental_sealing_canonical",
            assurance=assurance,
            proof_mode=mode,
            establishes=str(canonical.get("establishes") or "declared evidence"),
            does_not_establish=str(
                canonical.get("does_not_establish")
                or "claims outside the declared evidence class"
            ),
            reasons=(
                "payload is a canonical IncrementalProofSealer evidence record",
                f"evidence_class:{canonical['evidence_class']}",
            ),
            adapted_payload=canonical,
        )

    # 2) Simulated wallet / PDF / demo backends: reject for production.
    if _looks_wallet_or_pdf(working) or (
        _looks_simulated(working)
        and not _looks_test_execution_certificate(working)
        and not _looks_proof_receipt_attestation(working)
    ):
        family = (
            "wallet_simulated"
            if "wallet" in _joined_text_fields(working, "path", "module", "family")
            else (
                "pdf_form_simulated"
                if "pdf" in _joined_text_fields(working, "path", "module", "family")
                else "simulated_zkp_proof"
            )
        )
        return _result(
            disposition=MigrationDisposition.REJECT,
            path_family=family,
            assurance=LegacyAssurance.SIMULATED,
            proof_mode=ProofMode.SIMULATED,
            establishes="demo/simulated plumbing only",
            does_not_establish=(
                "cryptographic proof, production seal authority, or real execution"
            ),
            reasons=(
                "payload is labeled simulated/mock/demo or wallet/PDF simulated path",
                "schema adapters must not upgrade simulated evidence",
            ),
        )

    # 3) TestPassStatementV1 is a predicate protocol, not a ZK circuit.
    if _looks_test_pass_statement(working):
        return _result(
            disposition=MigrationDisposition.ADAPT,
            path_family="test_pass_statement",
            assurance=LegacyAssurance.PREDICATE_ONLY,
            proof_mode=ProofMode.INTEGRITY_ONLY,
            establishes=(
                "a Python predicate/statement protocol over declared public bindings"
            ),
            does_not_establish=(
                "an implemented ZK aggregation circuit, signed receipt verification, "
                "or pytest execution proof"
            ),
            reasons=(
                "TestPassStatementV1 is predicate-only per datasets inventory nonclaim",
                "cannot be promoted to ReceiptAggregationZkProof or DirectExecutionProof",
            ),
            adapted_payload={
                "evidence_class": EvidenceClass.INTEGRITY_COMMITMENT.value,
                "assurance": LegacyAssurance.PREDICATE_ONLY.value,
                "statement_interface": "TestPassStatementV1",
                "zk_circuit_implemented": False,
            },
        )

    # 4) Test execution certificates without signature verification.
    if _looks_test_execution_certificate(working):
        if _has_signature_material(working) and not _looks_simulated(working):
            return _result(
                disposition=MigrationDisposition.ADAPT,
                path_family="test_execution_certificate",
                assurance=LegacyAssurance.SIGNED_RECEIPT,
                proof_mode=ProofMode.SIGNED_RECEIPT,
                establishes=(
                    "certificate carries signature material that may support a "
                    "signed-receipt claim after accelerate signer allowlist checks"
                ),
                does_not_establish=(
                    "independent execution proof without trusting the signer; "
                    "direct computation"
                ),
                reasons=(
                    "certificate includes non-empty signature material",
                    "accelerate must still verify allowlisted signer scope",
                ),
                adapted_payload={
                    "evidence_class": EvidenceClass.SIGNED_EXECUTION_RECEIPT.value,
                    "assurance": LegacyAssurance.SIGNED_RECEIPT.value,
                    "signature_present": True,
                },
            )
        return _result(
            disposition=MigrationDisposition.ADAPT,
            path_family="test_execution_certificate",
            assurance=LegacyAssurance.STRUCTURAL,
            proof_mode=ProofMode.INTEGRITY_ONLY,
            establishes=(
                "structural certificate shape / integrity fields when digests rehash"
            ),
            does_not_establish=(
                "signed receipt authority; pytest execution; direct ZK computation"
            ),
            reasons=(
                "test-execution certificates without signature verification are "
                "not signed receipts",
                "retained as structural/integrity only",
            ),
            adapted_payload={
                "evidence_class": EvidenceClass.INTEGRITY_COMMITMENT.value,
                "assurance": LegacyAssurance.STRUCTURAL.value,
                "signature_present": False,
            },
        )

    # 5) Callback proof-receipt attestation: structural unless real backend ran.
    if _looks_proof_receipt_attestation(working):
        backend_real = _looks_groth16_direct(working) and not _looks_simulated(working)
        if backend_real:
            return _result(
                disposition=MigrationDisposition.ADAPT,
                path_family="proof_receipt_attestation",
                assurance=LegacyAssurance.DIRECT_EXECUTION,
                proof_mode=ProofMode.DIRECT_EXECUTION_PROOF,
                establishes=(
                    "callback attestation observed with a real backend marker; "
                    "still requires accelerate verification of the exact statement"
                ),
                does_not_establish=(
                    "pytest execution proof; claims beyond the declared circuit"
                ),
                reasons=(
                    "proof_receipt_attestation with real-backend markers adapts to "
                    "direct-execution candidate",
                    "no silent promotion without accelerate verification",
                ),
                adapted_payload={
                    "evidence_class": EvidenceClass.DIRECT_EXECUTION_PROOF.value,
                    "assurance": LegacyAssurance.DIRECT_EXECUTION.value,
                    "attestation_style": "callback",
                },
            )
        return _result(
            disposition=MigrationDisposition.ADAPT,
            path_family="proof_receipt_attestation",
            assurance=LegacyAssurance.STRUCTURAL,
            proof_mode=ProofMode.INTEGRITY_ONLY,
            establishes="structural attestation envelope only",
            does_not_establish=(
                "cryptographic execution proof unless a real backend actually ran"
            ),
            reasons=(
                "callback-style proof_receipt_attestation is structural without a "
                "real backend observation",
            ),
            adapted_payload={
                "evidence_class": EvidenceClass.INTEGRITY_COMMITMENT.value,
                "assurance": LegacyAssurance.STRUCTURAL.value,
                "attestation_style": "callback",
            },
        )

    # 6) Event-DAG hash commitments are integrity-only non-ZK.
    if _looks_event_dag(working):
        return _result(
            disposition=MigrationDisposition.ADAPT,
            path_family="event_dag_hash_commitment",
            assurance=LegacyAssurance.INTEGRITY_ONLY,
            proof_mode=ProofMode.INTEGRITY_ONLY,
            establishes="hash commitment / structural DAG integrity at best",
            does_not_establish="ZK proof, execution, or seal authority",
            reasons=(
                "Event-DAG fallback is integrity_only_non_zk per inventory",
                "pseudo-CID / merkle_clock paths are not proof-seal authorities",
            ),
            adapted_payload={
                "evidence_class": EvidenceClass.INTEGRITY_COMMITMENT.value,
                "assurance": LegacyAssurance.INTEGRITY_ONLY.value,
            },
        )

    # 7) Proof caches and VK registry: integrity only.
    if _looks_integrity_cache(working):
        return _result(
            disposition=MigrationDisposition.ADAPT,
            path_family="integrity_cache",
            assurance=LegacyAssurance.INTEGRITY_ONLY,
            proof_mode=ProofMode.INTEGRITY_ONLY,
            establishes="content-addressed cache / envelope integrity when rehashed",
            does_not_establish="proof validity, execution, or reuse authority",
            reasons=(
                "legacy proof caches are integrity_cache surfaces only",
                "datasets never promotes cache hits to admitted proofs",
            ),
            adapted_payload={
                "evidence_class": EvidenceClass.INTEGRITY_COMMITMENT.value,
                "assurance": LegacyAssurance.INTEGRITY_ONLY.value,
            },
        )

    if _looks_vk_registry(working):
        return _result(
            disposition=MigrationDisposition.ADAPT,
            path_family="vk_registry_integrity",
            assurance=LegacyAssurance.INTEGRITY_ONLY,
            proof_mode=ProofMode.INTEGRITY_ONLY,
            establishes="verification-key hash registry integrity",
            does_not_establish=(
                "production key origin, allowlist membership, or direct execution"
            ),
            reasons=(
                "vk_registry is integrity_only; existing keys remain test-only "
                "without allowlist evidence",
            ),
            adapted_payload={
                "evidence_class": EvidenceClass.INTEGRITY_COMMITMENT.value,
                "assurance": LegacyAssurance.INTEGRITY_ONLY.value,
            },
        )

    if _looks_canonicalization(working):
        return _result(
            disposition=MigrationDisposition.ADAPT,
            path_family="canonicalization_commitment",
            assurance=LegacyAssurance.INTEGRITY_ONLY,
            proof_mode=ProofMode.INTEGRITY_ONLY,
            establishes="text/axiom commitment integrity under declared binding",
            does_not_establish=(
                "full cryptographic hash commitment when reduced-field bindings "
                "are used; execution proof"
            ),
            reasons=(
                "canonicalization commitments are integrity_commitment surfaces",
                "reduced-field BN254 bindings remain explicit nonclaims",
            ),
            adapted_payload={
                "evidence_class": EvidenceClass.INTEGRITY_COMMITMENT.value,
                "assurance": LegacyAssurance.INTEGRITY_ONLY.value,
            },
        )

    # 8) Real Groth16 / ProveKit direct computation candidates.
    if _looks_groth16_direct(working):
        return _result(
            disposition=MigrationDisposition.ADAPT,
            path_family="groth16_direct_computation",
            assurance=LegacyAssurance.DIRECT_EXECUTION,
            proof_mode=ProofMode.DIRECT_EXECUTION_PROOF,
            establishes=(
                "candidate direct computation proof for a declared circuit when "
                "accelerate verifies the exact public inputs and proof bytes"
            ),
            does_not_establish=(
                "pytest execution; claims outside the declared program/circuit; "
                "production key trust without allowlist"
            ),
            reasons=(
                "real-backend markers present without simulation labels",
                "Groth16 computation axis is distinct from pytest-execution proof",
                "accelerate admission remains mandatory before cache use",
            ),
            adapted_payload={
                "evidence_class": EvidenceClass.DIRECT_EXECUTION_PROOF.value,
                "assurance": LegacyAssurance.DIRECT_EXECUTION.value,
                "pytest_execution_proven": False,
            },
        )

    # 9) Signed-looking legacy receipts with signature material.
    if _has_signature_material(working):
        return _result(
            disposition=MigrationDisposition.ADAPT,
            path_family="unknown",
            assurance=LegacyAssurance.SIGNED_RECEIPT,
            proof_mode=ProofMode.SIGNED_RECEIPT,
            establishes=(
                "payload includes signature material that may support a signed "
                "receipt after allowlist verification"
            ),
            does_not_establish=(
                "independent execution without trusting the signer; direct ZK proof"
            ),
            reasons=(
                "non-empty signature field present",
                "signer trust is not established by this classifier",
            ),
            adapted_payload={
                "evidence_class": EvidenceClass.SIGNED_EXECUTION_RECEIPT.value,
                "assurance": LegacyAssurance.SIGNED_RECEIPT.value,
            },
        )

    # 10) Integrity-shaped digests without stronger claims.
    integrity_keys = {
        "digest",
        "cid",
        "content_id",
        "merkle_root",
        "merkle_inclusion",
        "byte_length",
        "sha256",
    }
    payload_keys = {str(key).casefold() for key in working}
    if payload_keys & integrity_keys:
        return _result(
            disposition=MigrationDisposition.ADAPT,
            path_family="unknown",
            assurance=LegacyAssurance.INTEGRITY_ONLY,
            proof_mode=ProofMode.INTEGRITY_ONLY,
            establishes="digest/CID integrity fields when rehashed",
            does_not_establish="execution, signatures, or production seals",
            reasons=(
                "payload exposes integrity fields without signed/direct markers",
            ),
            adapted_payload={
                "evidence_class": EvidenceClass.INTEGRITY_COMMITMENT.value,
                "assurance": LegacyAssurance.INTEGRITY_ONLY.value,
            },
        )

    return _result(
        disposition=MigrationDisposition.REJECT,
        path_family="unknown",
        assurance=LegacyAssurance.UNKNOWN,
        proof_mode=ProofMode.INTEGRITY_ONLY,
        establishes="nothing",
        does_not_establish="any IncrementalProofSealer evidence class",
        reasons=(
            "payload does not match a known legacy receipt family",
            "unknown evidence is never treated as independence or success",
        ),
    )


def known_legacy_path_matrix() -> dict[str, Any]:
    """Closed inventory of legacy path families and default dispositions."""

    return {
        "schema": f"{MIGRATION_NAMESPACE}/legacy-path-matrix@{SCHEMA_MAJOR}",
        "subset": MIGRATION_SUBSET,
        "families": {
            "incremental_sealing_canonical": {
                "default_disposition": MigrationDisposition.ACCEPT.value,
                "assurance": "declared_evidence_class",
            },
            "test_execution_certificate": {
                "default_disposition": MigrationDisposition.ADAPT.value,
                "assurance": LegacyAssurance.STRUCTURAL.value,
                "nonclaim": "unsigned certificates are not signed receipts",
            },
            "test_pass_statement": {
                "default_disposition": MigrationDisposition.ADAPT.value,
                "assurance": LegacyAssurance.PREDICATE_ONLY.value,
                "nonclaim": "not an implemented ZK circuit",
            },
            "proof_receipt_attestation": {
                "default_disposition": MigrationDisposition.ADAPT.value,
                "assurance": LegacyAssurance.STRUCTURAL.value,
                "nonclaim": "structural unless real backend ran",
            },
            "simulated_zkp_proof": {
                "default_disposition": MigrationDisposition.REJECT.value,
                "assurance": LegacyAssurance.SIMULATED.value,
            },
            "wallet_simulated": {
                "default_disposition": MigrationDisposition.REJECT.value,
                "assurance": LegacyAssurance.SIMULATED.value,
            },
            "pdf_form_simulated": {
                "default_disposition": MigrationDisposition.REJECT.value,
                "assurance": LegacyAssurance.SIMULATED.value,
            },
            "groth16_direct_computation": {
                "default_disposition": MigrationDisposition.ADAPT.value,
                "assurance": LegacyAssurance.DIRECT_EXECUTION.value,
                "nonclaim": "does not prove pytest execution",
            },
            "integrity_cache": {
                "default_disposition": MigrationDisposition.ADAPT.value,
                "assurance": LegacyAssurance.INTEGRITY_ONLY.value,
            },
            "event_dag_hash_commitment": {
                "default_disposition": MigrationDisposition.ADAPT.value,
                "assurance": LegacyAssurance.INTEGRITY_ONLY.value,
            },
            "vk_registry_integrity": {
                "default_disposition": MigrationDisposition.ADAPT.value,
                "assurance": LegacyAssurance.INTEGRITY_ONLY.value,
            },
            "canonicalization_commitment": {
                "default_disposition": MigrationDisposition.ADAPT.value,
                "assurance": LegacyAssurance.INTEGRITY_ONLY.value,
            },
            "unknown": {
                "default_disposition": MigrationDisposition.REJECT.value,
                "assurance": LegacyAssurance.UNKNOWN.value,
            },
        },
    }


__all__ = (
    "LEGACY_CLASSIFICATION_SCHEMA",
    "LEGACY_PATH_FAMILIES",
    "MIGRATION_SUBSET",
    "PUBLIC_API_SUBSET",
    "LegacyAssurance",
    "LegacyReceiptClassification",
    "MigrationDisposition",
    "MigrationError",
    "classify_legacy_receipt",
    "closed_legacy_assurances",
    "closed_legacy_path_families",
    "closed_migration_dispositions",
    "known_legacy_path_matrix",
)
