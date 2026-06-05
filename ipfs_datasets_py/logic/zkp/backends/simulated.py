"""Simulated ZKP backend.

This backend implements the existing demo-only behavior and is intended to be
used as the default backend.

Security: NOT cryptographically secure.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import hashlib
import json
import time

from .. import ZKPError, ZKPProof
from ..canonicalization import axioms_commitment_hex, normalize_text, theorem_hash_hex
from ..circuits import attestation_view_matches_proof, build_proof_attestation_view
from ..statement import format_circuit_ref, parse_circuit_ref_lenient


@dataclass
class SimulatedBackend:
    backend_id: str = "simulated"

    _DEFAULT_CIRCUIT_ID = "knowledge_of_axioms"
    _PADDING_LENGTH = 56
    _U64_MAX = (1 << 64) - 1

    def _simulated_proof_layout_metadata(self) -> dict[str, Any]:
        magic = b"SIMZKP\x00\x01"
        return {
            "format": "SIMZKP/1",
            "byte_length": 160,
            "magic_hex": magic.hex(),
            "segments": [
                {"tag": "magic", "offset": 0, "length": 8},
                {
                    "tag": "proof_hash",
                    "offset": 8,
                    "length": 32,
                    "description": "SHA256(circuit_hash || witness || normalize_text(theorem))",
                },
                {
                    "tag": "circuit_hash",
                    "offset": 40,
                    "length": 32,
                    "description": "SHA256(circuit metadata derived from theorem + axioms)",
                },
                {
                    "tag": "witness",
                    "offset": 72,
                    "length": 32,
                    "description": "SHA256(canonicalized axioms JSON)",
                },
                {
                    "tag": "padding",
                    "offset": 104,
                    "length": 56,
                    "description": "deterministic pseudo-random bytes derived from theorem/axioms/seed",
                },
            ],
        }

    def generate_proof(self, theorem: str, private_axioms: list[str], metadata: dict) -> ZKPProof:
        if not theorem:
            raise ZKPError("Theorem cannot be empty")
        if not private_axioms:
            raise ZKPError("At least one axiom required")

        metadata_dict = dict(metadata or {})
        circuit_hash = self._hash_circuit(theorem, private_axioms)
        witness = self._compute_witness(private_axioms)
        proof_data = self._simulate_groth16_proof(
            circuit_hash=circuit_hash,
            witness=witness,
            theorem=theorem,
            seed=metadata_dict.get("seed"),
        )

        circuit_version = int(metadata_dict.get("circuit_version", 1))
        ruleset_id = str(metadata_dict.get("ruleset_id", "TDFOL_v1"))
        circuit_ref = self._resolve_circuit_ref(
            metadata_dict,
            circuit_version=circuit_version,
        )


        output_metadata = {**metadata_dict}
        output_metadata.setdefault("simulated_proof_layout", self._simulated_proof_layout_metadata())
        public_inputs = {
            "theorem": theorem,
            "theorem_hash": theorem_hash_hex(theorem),
            "axioms_commitment": axioms_commitment_hex(private_axioms),
            "circuit_ref": circuit_ref,
            "circuit_version": circuit_version,
            "ruleset_id": ruleset_id,
        }
        guidance_ref = str(metadata_dict.get("compiler_guidance_ref") or "")
        if guidance_ref:
            public_inputs["compiler_guidance_ref"] = guidance_ref
            public_inputs["compiler_guidance_version"] = int(
                metadata_dict.get("compiler_guidance_version") or 1
            )
        attestation_view = build_proof_attestation_view(
            proof_data=proof_data,
            public_inputs=public_inputs,
            metadata={
                **output_metadata,
                "backend": self.backend_id,
                "proof_system": "Groth16 (simulated)",
            },
        )
        public_inputs["attestation_ref"] = attestation_view["attestation_ref"]
        public_inputs["attestation_view_version"] = int(attestation_view["attestation_view_version"])
        output_metadata.setdefault("attestation_view", attestation_view)

        return ZKPProof(
            proof_data=proof_data,
            public_inputs=public_inputs,
            metadata={
                **output_metadata,
                "proof_system": "Groth16 (simulated)",
                "num_axioms": len(private_axioms),
            },
            timestamp=time.time(),
            size_bytes=len(proof_data),
        )

    def verify_proof(self, proof: ZKPProof) -> bool:
        theorem = proof.public_inputs.get("theorem", "")
        theorem_hash = proof.public_inputs.get("theorem_hash", "")

        # Check required public input keys
        if "theorem" not in proof.public_inputs or "theorem_hash" not in proof.public_inputs:
            return False

        # Verify theorem hash matches
        expected_hash = theorem_hash_hex(theorem)
        legacy_hash = hashlib.sha256(theorem.encode()).hexdigest()
        if theorem_hash not in (expected_hash, legacy_hash):
            return False

        # Check proof data size bounds (simulated Groth16-like)
        if len(proof.proof_data) < 100 or len(proof.proof_data) > 300:
            return False

        # Check metadata sanity (if present)
        if hasattr(proof, 'metadata') and isinstance(proof.metadata, dict):
            # Verify proof_system field exists (for clarity)
            if 'proof_system' not in proof.metadata:
                return False

            if (
                "attestation_ref" in proof.public_inputs
                or "attestation_view_version" in proof.public_inputs
                or isinstance(proof.metadata.get("attestation_view"), dict)
            ) and not attestation_view_matches_proof(
                proof_data=proof.proof_data,
                public_inputs=proof.public_inputs,
                metadata=proof.metadata,
            ):
                return False

        return True

    def _hash_circuit(self, theorem: str, axioms: list[str]) -> bytes:
        normalized_theorem = normalize_text(theorem)
        normalized_axioms = [normalize_text(a) for a in axioms]
        circuit_data = json.dumps(
            {
                "theorem": normalized_theorem,
                "num_axioms": len(normalized_axioms),
                "axiom_hashes": [hashlib.sha256(a.encode("utf-8")).hexdigest() for a in normalized_axioms],
            },
            sort_keys=True,
        )
        return hashlib.sha256(circuit_data.encode()).digest()

    def _compute_witness(self, axioms: list[str]) -> bytes:
        witness_data = json.dumps([normalize_text(a) for a in axioms], sort_keys=True)
        return hashlib.sha256(witness_data.encode()).digest()

    def _simulate_groth16_proof(
        self,
        circuit_hash: bytes,
        witness: bytes,
        theorem: str,
        seed: Any = None,
    ) -> bytes:
        proof_inputs = circuit_hash + witness + normalize_text(theorem).encode("utf-8")
        proof_hash = hashlib.sha256(proof_inputs).digest()

        # Byte layout (fixed 160 bytes):
        # - [0:8]     Magic header: b"SIMZKP\x00\x01"
        # - [8:40]    proof_hash: SHA256(circuit_hash || witness || normalize_text(theorem))
        # - [40:72]   circuit_hash: SHA256(normalized theorem + axiom hashes metadata)
        # - [72:104]  witness: SHA256(canonicalized axioms JSON)
        # - [104:160] deterministic padding (simulated but stable for attestation views)
        #
        # This is demo-only and intentionally non-verifiable as a real zkSNARK.
        magic = b"SIMZKP\x00\x01"
        padding = self._deterministic_padding(
            theorem=theorem,
            circuit_hash=circuit_hash,
            witness=witness,
            proof_hash=proof_hash,
            seed=seed,
        )
        simulated_proof = magic + proof_hash + circuit_hash + witness + padding
        return simulated_proof

    def _deterministic_padding(
        self,
        *,
        theorem: str,
        circuit_hash: bytes,
        witness: bytes,
        proof_hash: bytes,
        seed: Any,
    ) -> bytes:
        """Derive stable pseudo-random bytes for simulated proof padding."""
        seed_material = self._seed_material(seed)
        seed_len = len(seed_material).to_bytes(2, "big")
        base = (
            b"SIMZKP_PAD_V1"
            + circuit_hash
            + witness
            + proof_hash
            + normalize_text(theorem).encode("utf-8")
            + seed_len
            + seed_material
        )
        output = bytearray()
        counter = 0
        while len(output) < self._PADDING_LENGTH:
            block = hashlib.sha256(base + counter.to_bytes(4, "big")).digest()
            output.extend(block)
            counter += 1
        return bytes(output[: self._PADDING_LENGTH])

    @staticmethod
    def _seed_material(seed: Any) -> bytes:
        if seed is None:
            return b""
        if isinstance(seed, bool):
            raise ZKPError("seed must be a uint64 integer when provided")
        if isinstance(seed, int):
            if seed < 0 or seed > SimulatedBackend._U64_MAX:
                raise ZKPError("seed must be in uint64 range")
            return seed.to_bytes(8, "big", signed=False)
        raise ZKPError("seed must be a uint64 integer when provided")

    def _resolve_circuit_ref(self, metadata: dict[str, Any], *, circuit_version: int) -> str:
        """Return a versioned circuit_ref consistent with circuit_version."""
        candidate = str(metadata.get("circuit_ref") or "").strip()
        default_circuit_id = str(metadata.get("circuit_id") or self._DEFAULT_CIRCUIT_ID).strip()
        circuit_id = default_circuit_id or self._DEFAULT_CIRCUIT_ID

        if candidate:
            try:
                parsed_id, parsed_version = parse_circuit_ref_lenient(
                    candidate,
                    legacy_default_version=circuit_version,
                )
                circuit_id = parsed_id
                if parsed_version != circuit_version:
                    return format_circuit_ref(circuit_id, circuit_version)
                return format_circuit_ref(circuit_id, parsed_version)
            except Exception:
                return format_circuit_ref(circuit_id, circuit_version)

        return format_circuit_ref(circuit_id, circuit_version)
