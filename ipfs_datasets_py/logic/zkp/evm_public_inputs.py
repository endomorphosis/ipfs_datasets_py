"""EVM-friendly public input encoding for Groth16.

Groth16 verifiers on EVM (BN254) expect public inputs as field elements in the
BN254 scalar field. This codebase's current wire format includes values like
`ruleset_id` which are not field elements.

This module defines a deterministic encoding from the current logical inputs to
4 BN254-Fr scalars:
  0) theorem_hash_fr       := int(SHA256(theorem_canonical)) mod Fr
     (encoded from existing 32-byte theorem_hash)
  1) axioms_commitment_fr  := int(SHA256(sorted_axioms)) mod Fr
     (encoded from existing 32-byte axioms_commitment)
  2) circuit_version_fr    := circuit_version (must be < Fr)
  3) ruleset_id_fr         := int(SHA256(UTF-8 ruleset_id)) mod Fr

All returned scalars are encoded as 0x-prefixed 32-byte hex strings.

Note: This defines the *packing* boundary needed for on-chain work. It does not
change the existing Python/Rust proof wire formats yet.
"""

from __future__ import annotations

import hashlib
from typing import Iterable


# BN254 scalar field modulus (a.k.a. altbn128 Fr)
# Matches the Solidity constant typically used in verifiers.
BN254_FR_MODULUS: int = int(
    "21888242871839275222246405745257275088548364400416034343698204186575808495617"
)


def _strip_0x(hex_str: str) -> str:
    s = str(hex_str).strip().lower()
    return s[2:] if s.startswith("0x") else s


def _int_to_0x32(value: int) -> str:
    if not isinstance(value, int):
        raise TypeError("value must be int")
    if value < 0:
        raise ValueError("value must be non-negative")
    value = value % BN254_FR_MODULUS
    return "0x" + value.to_bytes(32, byteorder="big", signed=False).hex()


def _bytes32_hex_to_int_mod_fr(bytes32_hex: str) -> int:
    s = _strip_0x(bytes32_hex)
    if len(s) != 64:
        raise ValueError("expected 32-byte hex string")
    try:
        raw = bytes.fromhex(s)
    except Exception as e:
        raise ValueError("invalid hex") from e
    return int.from_bytes(raw, byteorder="big", signed=False) % BN254_FR_MODULUS


def hash_text_to_field_sha256(text: str) -> str:
    """Hash UTF-8 text with SHA-256 and reduce mod Fr."""
    if not isinstance(text, str):
        raise TypeError("text must be str")
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    return _int_to_0x32(int.from_bytes(digest, byteorder="big", signed=False))


def pack_public_inputs_for_evm(
    *,
    theorem_hash_hex: str,
    axioms_commitment_hex: str,
    circuit_version: int,
    ruleset_id: str,
) -> list[str]:
    """Pack current logical public inputs into 4 BN254-Fr scalars for EVM."""

    if not isinstance(circuit_version, int):
        raise TypeError("circuit_version must be int")
    if circuit_version < 0:
        raise ValueError("circuit_version must be non-negative")
    if circuit_version >= BN254_FR_MODULUS:
        raise ValueError("circuit_version must be < BN254_FR_MODULUS")

    t_fr = _int_to_0x32(_bytes32_hex_to_int_mod_fr(theorem_hash_hex))
    a_fr = _int_to_0x32(_bytes32_hex_to_int_mod_fr(axioms_commitment_hex))
    v_fr = _int_to_0x32(circuit_version)
    r_fr = hash_text_to_field_sha256(ruleset_id)

    return [t_fr, a_fr, v_fr, r_fr]


def pack_many_public_inputs_for_evm(
    inputs: Iterable[tuple[str, str, int, str]],
) -> list[list[str]]:
    """Batch pack helper."""
    out: list[list[str]] = []
    for theorem_hash_hex, axioms_commitment_hex, circuit_version, ruleset_id in inputs:
        out.append(
            pack_public_inputs_for_evm(
                theorem_hash_hex=theorem_hash_hex,
                axioms_commitment_hex=axioms_commitment_hex,
                circuit_version=circuit_version,
                ruleset_id=ruleset_id,
            )
        )
    return out
