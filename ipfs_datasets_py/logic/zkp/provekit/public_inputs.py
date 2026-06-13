"""Public-input mapping for ProveKit-backed ZKP circuits.

This module is a compatibility layer, not a prover. It preserves the existing
``ZKPProof.public_inputs`` contract used by the simulated and Groth16 backends,
then derives deterministic ProveKit/Noir-friendly field inputs from that same
contract.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, replace
from typing import Any, Mapping, Optional, Sequence

from ..canonicalization import (
    P_BN254,
    axioms_commitment_hex,
    theorem_hash_hex,
)
from ..circuits import (
    build_proof_attestation_view,
    compiler_guidance_ref_from_metadata,
)
from ..statement import format_circuit_ref, parse_circuit_ref_lenient


PROVEKIT_PUBLIC_INPUT_SCHEMA_VERSION = "provekit-public-inputs-v1"
DEFAULT_PROVEKIT_CIRCUIT_ID = "provekit_knowledge_of_axioms"
DEFAULT_PROVEKIT_CIRCUIT_VERSION = 1
DEFAULT_PROVEKIT_RULESET_ID = "TDFOL_v1"
DEFAULT_PROVEKIT_HASH_BACKEND = "sha256"

_HEX_32_BYTES_LENGTH = 64
_U64_MAX = (1 << 64) - 1


@dataclass(frozen=True)
class ProveKitPublicInputRecord:
    """Canonical public-input record for ProveKit circuit calls.

    ``to_zkp_public_inputs()`` returns the current backend-neutral public-input
    shape. ``to_provekit_inputs()`` wraps that shape with ProveKit-specific
    metadata and a field-element projection suitable for Noir circuit inputs.
    """

    theorem: str
    theorem_hash: str
    axioms_commitment: str
    circuit_ref: str
    circuit_version: int
    ruleset_id: str
    hash_backend: str = DEFAULT_PROVEKIT_HASH_BACKEND
    compiler_guidance_ref: str = ""
    compiler_guidance_version: int = 0
    attestation_ref: str = ""
    attestation_view_version: int = 0
    schema_version: str = PROVEKIT_PUBLIC_INPUT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.theorem, str) or not self.theorem:
            raise ValueError("theorem must be a non-empty string")
        _validate_hex_32_bytes("theorem_hash", self.theorem_hash)
        _validate_hex_32_bytes("axioms_commitment", self.axioms_commitment)
        _validate_non_negative_u64("circuit_version", self.circuit_version)
        if not isinstance(self.ruleset_id, str) or not self.ruleset_id:
            raise ValueError("ruleset_id must be a non-empty string")
        if not isinstance(self.hash_backend, str) or not self.hash_backend.strip():
            raise ValueError("hash_backend must be a non-empty string")

        circuit_id, parsed_version = parse_circuit_ref_lenient(
            self.circuit_ref,
            legacy_default_version=self.circuit_version,
        )
        if parsed_version != self.circuit_version:
            raise ValueError("circuit_ref version must match circuit_version")
        canonical_ref = format_circuit_ref(circuit_id, self.circuit_version)
        if canonical_ref != self.circuit_ref:
            object.__setattr__(self, "circuit_ref", canonical_ref)

        if self.compiler_guidance_ref:
            _validate_hex_32_bytes(
                "compiler_guidance_ref",
                self.compiler_guidance_ref,
            )
            _validate_non_negative_u64(
                "compiler_guidance_version",
                self.compiler_guidance_version,
            )
        elif self.compiler_guidance_version:
            raise ValueError(
                "compiler_guidance_version requires compiler_guidance_ref"
            )

        if self.attestation_ref:
            _validate_hex_32_bytes("attestation_ref", self.attestation_ref)
            _validate_non_negative_u64(
                "attestation_view_version",
                self.attestation_view_version,
            )
        elif self.attestation_view_version:
            raise ValueError("attestation_view_version requires attestation_ref")

    @classmethod
    def from_zkp_public_inputs(
        cls,
        public_inputs: Mapping[str, Any],
        *,
        metadata: Optional[Mapping[str, Any]] = None,
        hash_backend: Optional[str] = None,
    ) -> "ProveKitPublicInputRecord":
        """Build a ProveKit record from an existing proof public-input dict."""

        metadata_dict = dict(metadata or {})
        public = dict(public_inputs or {})
        theorem = str(public.get("theorem") or "")
        circuit_version = _coerce_non_negative_int(
            public.get("circuit_version"),
            default=DEFAULT_PROVEKIT_CIRCUIT_VERSION,
        )
        circuit_ref = _canonical_circuit_ref(
            circuit_ref=str(public.get("circuit_ref") or DEFAULT_PROVEKIT_CIRCUIT_ID),
            circuit_id=DEFAULT_PROVEKIT_CIRCUIT_ID,
            circuit_version=circuit_version,
        )
        guidance_ref = str(
            public.get("compiler_guidance_ref")
            or metadata_dict.get("compiler_guidance_ref")
            or compiler_guidance_ref_from_metadata(metadata_dict)
            or ""
        )
        guidance_version = _coerce_non_negative_int(
            public.get("compiler_guidance_version")
            or metadata_dict.get("compiler_guidance_version"),
            default=1 if guidance_ref else 0,
        )
        return cls(
            theorem=theorem,
            theorem_hash=str(public.get("theorem_hash") or ""),
            axioms_commitment=str(public.get("axioms_commitment") or ""),
            circuit_ref=circuit_ref,
            circuit_version=circuit_version,
            ruleset_id=str(public.get("ruleset_id") or DEFAULT_PROVEKIT_RULESET_ID),
            hash_backend=str(
                hash_backend
                or metadata_dict.get("hash_backend")
                or DEFAULT_PROVEKIT_HASH_BACKEND
            ),
            compiler_guidance_ref=guidance_ref,
            compiler_guidance_version=guidance_version,
            attestation_ref=str(public.get("attestation_ref") or ""),
            attestation_view_version=_coerce_non_negative_int(
                public.get("attestation_view_version"),
                default=0,
            ),
        )

    def to_zkp_public_inputs(self, *, include_attestation: bool = True) -> dict[str, Any]:
        """Return the backend-neutral public-input dict used by current proofs."""

        public_inputs: dict[str, Any] = {
            "theorem": self.theorem,
            "theorem_hash": self.theorem_hash,
            "axioms_commitment": self.axioms_commitment,
            "circuit_ref": self.circuit_ref,
            "circuit_version": self.circuit_version,
            "ruleset_id": self.ruleset_id,
        }
        if self.compiler_guidance_ref:
            public_inputs["compiler_guidance_ref"] = self.compiler_guidance_ref
            public_inputs["compiler_guidance_version"] = self.compiler_guidance_version
        if include_attestation and self.attestation_ref:
            public_inputs["attestation_ref"] = self.attestation_ref
            public_inputs["attestation_view_version"] = self.attestation_view_version
        return public_inputs

    def to_noir_field_inputs(self) -> dict[str, int]:
        """Return deterministic BN254 scalar-field public inputs for Noir."""

        return {
            "theorem_hash_field": field_element_from_hex_digest(self.theorem_hash),
            "axioms_commitment_field": field_element_from_hex_digest(
                self.axioms_commitment
            ),
            "circuit_version": self.circuit_version,
            "ruleset_id_field": field_element_from_text(self.ruleset_id),
            "circuit_ref_field": field_element_from_text(self.circuit_ref),
            "compiler_guidance_ref_field": (
                field_element_from_hex_digest(self.compiler_guidance_ref)
                if self.compiler_guidance_ref
                else 0
            ),
            "compiler_guidance_version": self.compiler_guidance_version,
            "hash_backend_field": field_element_from_text(self.hash_backend),
        }

    def to_provekit_inputs(self) -> dict[str, Any]:
        """Return a stable ProveKit-facing public input envelope."""

        return {
            "schema_version": self.schema_version,
            "hash_backend": self.hash_backend,
            "zkp_public_inputs": self.to_zkp_public_inputs(),
            "noir_field_inputs": self.to_noir_field_inputs(),
        }

    def to_dict(self) -> dict[str, Any]:
        """Return the dataclass as a plain JSON-serializable dictionary."""

        return asdict(self)

    def canonical_json(self) -> str:
        """Return deterministic JSON for manifests and cache-key material."""

        return json.dumps(
            self.to_provekit_inputs(),
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )

    def canonical_hash(self) -> str:
        """Return SHA-256 over the deterministic ProveKit public-input JSON."""

        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    def with_attestation(
        self,
        *,
        proof_data: object,
        metadata: Optional[Mapping[str, Any]] = None,
    ) -> "ProveKitPublicInputRecord":
        """Return a copy with attestation fields derived from proof bytes."""

        metadata_dict = {
            **dict(metadata or {}),
            "hash_backend": self.hash_backend,
        }
        attestation_view = build_proof_attestation_view(
            proof_data=proof_data,
            public_inputs=self.to_zkp_public_inputs(include_attestation=False),
            metadata=metadata_dict,
        )
        return replace(
            self,
            attestation_ref=str(attestation_view["attestation_ref"]),
            attestation_view_version=int(attestation_view["attestation_view_version"]),
        )


def build_provekit_public_input_record(
    *,
    theorem: str,
    private_axioms: Optional[Sequence[str]] = None,
    axioms_commitment: Optional[str] = None,
    circuit_id: str = DEFAULT_PROVEKIT_CIRCUIT_ID,
    circuit_ref: Optional[str] = None,
    circuit_version: int = DEFAULT_PROVEKIT_CIRCUIT_VERSION,
    ruleset_id: str = DEFAULT_PROVEKIT_RULESET_ID,
    metadata: Optional[Mapping[str, Any]] = None,
    hash_backend: str = DEFAULT_PROVEKIT_HASH_BACKEND,
) -> ProveKitPublicInputRecord:
    """Build canonical ProveKit public inputs from theorem and axiom data."""

    if axioms_commitment is None:
        axioms_commitment = axioms_commitment_hex(list(private_axioms or ()))
    metadata_dict = dict(metadata or {})
    guidance_ref = compiler_guidance_ref_from_metadata(metadata_dict)
    guidance_version = _coerce_non_negative_int(
        metadata_dict.get("compiler_guidance_version"),
        default=1 if guidance_ref else 0,
    )
    return ProveKitPublicInputRecord(
        theorem=str(theorem),
        theorem_hash=theorem_hash_hex(theorem),
        axioms_commitment=str(axioms_commitment),
        circuit_ref=_canonical_circuit_ref(
            circuit_ref=circuit_ref,
            circuit_id=circuit_id,
            circuit_version=circuit_version,
        ),
        circuit_version=circuit_version,
        ruleset_id=str(ruleset_id),
        hash_backend=str(hash_backend),
        compiler_guidance_ref=guidance_ref,
        compiler_guidance_version=guidance_version,
    )


def field_element_from_hex_digest(value: str) -> int:
    """Map a 32-byte hex digest to the BN254 scalar field."""

    _validate_hex_32_bytes("hex_digest", value)
    return int(value, 16) % P_BN254


def field_element_from_text(value: str) -> int:
    """Map UTF-8 text to the BN254 scalar field via SHA-256."""

    if not isinstance(value, str):
        raise TypeError("value must be a string")
    digest = hashlib.sha256(value.encode("utf-8")).digest()
    return int.from_bytes(digest, "big") % P_BN254


def _canonical_circuit_ref(
    *,
    circuit_ref: Optional[str],
    circuit_id: str,
    circuit_version: int,
) -> str:
    _validate_non_negative_u64("circuit_version", circuit_version)
    candidate = str(circuit_ref or "").strip()
    fallback_id = str(circuit_id or "").strip() or DEFAULT_PROVEKIT_CIRCUIT_ID
    if candidate:
        parsed_id, _ = parse_circuit_ref_lenient(
            candidate,
            legacy_default_version=circuit_version,
        )
        return format_circuit_ref(parsed_id, circuit_version)
    return format_circuit_ref(fallback_id, circuit_version)


def _validate_hex_32_bytes(name: str, value: object) -> None:
    if not isinstance(value, str) or len(value) != _HEX_32_BYTES_LENGTH:
        raise ValueError(f"{name} must be a 32-byte lowercase hex string")
    try:
        int(value, 16)
    except ValueError as exc:
        raise ValueError(f"{name} must be a valid hex string") from exc
    if value.lower() != value:
        raise ValueError(f"{name} must be lowercase hex")


def _validate_non_negative_u64(name: str, value: object) -> None:
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"{name} must be an int")
    if value < 0 or value > _U64_MAX:
        raise ValueError(f"{name} must be in uint64 range")


def _coerce_non_negative_int(value: object, *, default: int) -> int:
    if value is None or isinstance(value, bool):
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed >= 0 else default


__all__ = [
    "DEFAULT_PROVEKIT_CIRCUIT_ID",
    "DEFAULT_PROVEKIT_CIRCUIT_VERSION",
    "DEFAULT_PROVEKIT_HASH_BACKEND",
    "DEFAULT_PROVEKIT_RULESET_ID",
    "PROVEKIT_PUBLIC_INPUT_SCHEMA_VERSION",
    "ProveKitPublicInputRecord",
    "build_provekit_public_input_record",
    "field_element_from_hex_digest",
    "field_element_from_text",
]
