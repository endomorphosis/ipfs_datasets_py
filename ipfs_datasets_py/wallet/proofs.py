"""Proof backend and receipt helpers for wallet workflows."""

from __future__ import annotations

import hashlib
import uuid
from typing import Any, Dict, List, Protocol

from .location import haversine_distance_km
from .manifest import canonical_bytes
from .models import ProofReceipt


SIMULATED_VERIFIER_ID = "simulated-wallet-zkp-v0.1"
SIMULATED_PROOF_SYSTEM = "simulated"
DETERMINISTIC_LOCATION_VERIFIER_ID = "deterministic-location-region-v0.1"
DETERMINISTIC_LOCATION_DISTANCE_VERIFIER_ID = "deterministic-location-distance-v0.1"
DETERMINISTIC_PROOF_SYSTEM = "deterministic-test-proof"


class ProofBackend(Protocol):
    """Backend interface for proof generation and verification."""

    verifier_id: str
    proof_system: str
    mode: str
    is_simulated: bool

    def prove_location_region(
        self,
        *,
        wallet_id: str,
        statement: Dict[str, Any],
        public_inputs: Dict[str, Any],
        witness: Dict[str, Any],
        witness_record_ids: List[str],
    ) -> ProofReceipt:
        """Create a receipt proving a precise wallet location is in a region."""

    def prove_location_distance(
        self,
        *,
        wallet_id: str,
        statement: Dict[str, Any],
        public_inputs: Dict[str, Any],
        witness: Dict[str, Any],
        witness_record_ids: List[str],
    ) -> ProofReceipt:
        """Create a receipt proving a precise wallet location is near a target."""

    def verify(self, receipt: ProofReceipt) -> bool:
        """Verify a proof receipt against this backend's verifier."""


def verifier_digest(verifier_id: str, proof_system: str) -> str:
    return hashlib.sha256(f"{proof_system}:{verifier_id}".encode("utf-8")).hexdigest()


def create_simulated_proof_receipt(
    *,
    wallet_id: str,
    proof_type: str,
    statement: Dict[str, Any],
    public_inputs: Dict[str, Any],
    witness_record_ids: List[str],
    circuit_id: str | None = None,
) -> ProofReceipt:
    digest = verifier_digest(SIMULATED_VERIFIER_ID, SIMULATED_PROOF_SYSTEM)
    proof_hash = hashlib.sha256(
        canonical_bytes(
            {
                "wallet_id": wallet_id,
                "proof_type": proof_type,
                "statement": statement,
                "public_inputs": public_inputs,
                "witness_record_ids": witness_record_ids,
                "verifier_id": SIMULATED_VERIFIER_ID,
                "proof_system": SIMULATED_PROOF_SYSTEM,
                "verifier_digest": digest,
            }
        )
    ).hexdigest()
    return ProofReceipt(
        proof_id=f"proof-{uuid.uuid4().hex}",
        wallet_id=wallet_id,
        proof_type=proof_type,
        statement=statement,
        verifier_id=SIMULATED_VERIFIER_ID,
        public_inputs=public_inputs,
        proof_hash=proof_hash,
        witness_record_ids=list(witness_record_ids),
        is_simulated=True,
        proof_system=SIMULATED_PROOF_SYSTEM,
        circuit_id=circuit_id or f"simulated-{proof_type.replace('_', '-')}",
        verifier_digest=digest,
        verification_status="verified",
    )


class SimulatedProofBackend:
    """Development proof backend that creates deterministic simulated receipts."""

    verifier_id = SIMULATED_VERIFIER_ID
    proof_system = SIMULATED_PROOF_SYSTEM
    mode = "development"
    is_simulated = True

    def prove_location_region(
        self,
        *,
        wallet_id: str,
        statement: Dict[str, Any],
        public_inputs: Dict[str, Any],
        witness: Dict[str, Any],
        witness_record_ids: List[str],
    ) -> ProofReceipt:
        _ = witness
        return create_simulated_proof_receipt(
            wallet_id=wallet_id,
            proof_type="location_region",
            statement=statement,
            public_inputs=public_inputs,
            witness_record_ids=witness_record_ids,
        )

    def prove_location_distance(
        self,
        *,
        wallet_id: str,
        statement: Dict[str, Any],
        public_inputs: Dict[str, Any],
        witness: Dict[str, Any],
        witness_record_ids: List[str],
    ) -> ProofReceipt:
        _ = witness
        return create_simulated_proof_receipt(
            wallet_id=wallet_id,
            proof_type="location_distance",
            statement=statement,
            public_inputs=public_inputs,
            witness_record_ids=witness_record_ids,
        )

    def verify(self, receipt: ProofReceipt) -> bool:
        return (
            receipt.is_simulated is True
            and receipt.verifier_id == self.verifier_id
            and receipt.proof_system == self.proof_system
            and receipt.verification_status == "verified"
        )


class DeterministicLocationRegionProofBackend:
    """Non-simulated integration backend for location-region proof plumbing.

    This backend exercises the production proof path without using a simulated
    receipt. It is deterministic and not a cryptographic ZK circuit.
    """

    verifier_id = DETERMINISTIC_LOCATION_VERIFIER_ID
    proof_system = DETERMINISTIC_PROOF_SYSTEM
    mode = "integration"
    is_simulated = False
    circuit_id = "deterministic-location-region-v0.1"

    def prove_location_region(
        self,
        *,
        wallet_id: str,
        statement: Dict[str, Any],
        public_inputs: Dict[str, Any],
        witness: Dict[str, Any],
        witness_record_ids: List[str],
    ) -> ProofReceipt:
        digest = verifier_digest(self.verifier_id, self.proof_system)
        artifact_payload = {
            "proof_type": "location_region",
            "public_inputs": public_inputs,
            "statement": statement,
            "verifier_digest": digest,
            "witness_commitment": statement.get("witness_commitment"),
        }
        proof_hash = hashlib.sha256(canonical_bytes(artifact_payload)).hexdigest()
        _ = witness
        return ProofReceipt(
            proof_id=f"proof-{uuid.uuid4().hex}",
            wallet_id=wallet_id,
            proof_type="location_region",
            statement=dict(statement),
            verifier_id=self.verifier_id,
            public_inputs=dict(public_inputs),
            proof_hash=proof_hash,
            witness_record_ids=list(witness_record_ids),
            is_simulated=False,
            proof_system=self.proof_system,
            circuit_id=self.circuit_id,
            verifier_digest=digest,
            proof_artifact_ref=f"deterministic-proof://{proof_hash}",
            verification_status="verified",
        )

    def verify(self, receipt: ProofReceipt) -> bool:
        if receipt.is_simulated or receipt.verifier_id != self.verifier_id:
            return False
        if receipt.proof_system != self.proof_system or receipt.verification_status != "verified":
            return False
        expected_digest = verifier_digest(self.verifier_id, self.proof_system)
        if receipt.verifier_digest != expected_digest:
            return False
        artifact_payload = {
            "proof_type": receipt.proof_type,
            "public_inputs": receipt.public_inputs,
            "statement": receipt.statement,
            "verifier_digest": receipt.verifier_digest,
            "witness_commitment": receipt.statement.get("witness_commitment"),
        }
        expected_hash = hashlib.sha256(canonical_bytes(artifact_payload)).hexdigest()
        return (
            receipt.proof_type == "location_region"
            and receipt.proof_hash == expected_hash
            and receipt.proof_artifact_ref == f"deterministic-proof://{expected_hash}"
        )


class DeterministicLocationDistanceProofBackend:
    """Non-simulated integration backend for location-distance proof plumbing.

    This backend checks distance deterministically and exercises the production
    receipt path. It is not a cryptographic ZK circuit.
    """

    verifier_id = DETERMINISTIC_LOCATION_DISTANCE_VERIFIER_ID
    proof_system = DETERMINISTIC_PROOF_SYSTEM
    mode = "integration"
    is_simulated = False
    circuit_id = "deterministic-location-distance-v0.1"

    def prove_location_distance(
        self,
        *,
        wallet_id: str,
        statement: Dict[str, Any],
        public_inputs: Dict[str, Any],
        witness: Dict[str, Any],
        witness_record_ids: List[str],
    ) -> ProofReceipt:
        distance_km = haversine_distance_km(
            float(witness["lat"]),
            float(witness["lon"]),
            float(witness["target_lat"]),
            float(witness["target_lon"]),
        )
        max_distance_km = float(witness["max_distance_km"])
        if distance_km > max_distance_km:
            raise ValueError("Location is outside the requested distance threshold")
        digest = verifier_digest(self.verifier_id, self.proof_system)
        artifact_payload = {
            "proof_type": "location_distance",
            "public_inputs": public_inputs,
            "statement": statement,
            "verifier_digest": digest,
            "witness_commitment": statement.get("witness_commitment"),
        }
        proof_hash = hashlib.sha256(canonical_bytes(artifact_payload)).hexdigest()
        return ProofReceipt(
            proof_id=f"proof-{uuid.uuid4().hex}",
            wallet_id=wallet_id,
            proof_type="location_distance",
            statement=dict(statement),
            verifier_id=self.verifier_id,
            public_inputs=dict(public_inputs),
            proof_hash=proof_hash,
            witness_record_ids=list(witness_record_ids),
            is_simulated=False,
            proof_system=self.proof_system,
            circuit_id=self.circuit_id,
            verifier_digest=digest,
            proof_artifact_ref=f"deterministic-proof://{proof_hash}",
            verification_status="verified",
        )

    def prove_location_region(
        self,
        *,
        wallet_id: str,
        statement: Dict[str, Any],
        public_inputs: Dict[str, Any],
        witness: Dict[str, Any],
        witness_record_ids: List[str],
    ) -> ProofReceipt:
        raise NotImplementedError("DeterministicLocationDistanceProofBackend only supports location_distance")

    def verify(self, receipt: ProofReceipt) -> bool:
        if receipt.is_simulated or receipt.verifier_id != self.verifier_id:
            return False
        if receipt.proof_system != self.proof_system or receipt.verification_status != "verified":
            return False
        expected_digest = verifier_digest(self.verifier_id, self.proof_system)
        if receipt.verifier_digest != expected_digest:
            return False
        artifact_payload = {
            "proof_type": receipt.proof_type,
            "public_inputs": receipt.public_inputs,
            "statement": receipt.statement,
            "verifier_digest": receipt.verifier_digest,
            "witness_commitment": receipt.statement.get("witness_commitment"),
        }
        expected_hash = hashlib.sha256(canonical_bytes(artifact_payload)).hexdigest()
        return (
            receipt.proof_type == "location_distance"
            and receipt.proof_hash == expected_hash
            and receipt.proof_artifact_ref == f"deterministic-proof://{expected_hash}"
        )


class ProofBackendRegistry:
    """In-memory verifier registry keyed by proof type and verifier ID."""

    def __init__(self) -> None:
        self._backends: Dict[tuple[str, str], ProofBackend] = {}

    def register(self, proof_type: str, backend: ProofBackend) -> None:
        self._backends[(proof_type, backend.verifier_id)] = backend

    def get(self, proof_type: str, verifier_id: str) -> ProofBackend:
        return self._backends[(proof_type, verifier_id)]


DEFAULT_PROOF_REGISTRY = ProofBackendRegistry()
DEFAULT_PROOF_REGISTRY.register("location_region", SimulatedProofBackend())
DEFAULT_PROOF_REGISTRY.register("location_region", DeterministicLocationRegionProofBackend())
DEFAULT_PROOF_REGISTRY.register("location_distance", SimulatedProofBackend())
DEFAULT_PROOF_REGISTRY.register("location_distance", DeterministicLocationDistanceProofBackend())
