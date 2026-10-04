"""Dependency-light helpers for EVM harness integration.

This module focuses on the *data boundary* required for on-chain verification:
packing the current ZKP public inputs into `uint256[4]` suitable for Solidity
verifier calls.

It does not submit transactions (that lives in `eth_integration.py` behind the
optional `web3` dependency).
"""

from __future__ import annotations

from typing import Sequence

from .evm_public_inputs import pack_public_inputs_for_evm


def _hex_to_int(value: str) -> int:
    s = str(value).strip().lower()
    if s.startswith("0x"):
        s = s[2:]
    return int(s, 16)


def pack_public_inputs_uint256(
    *,
    theorem_hash_hex: str,
    axioms_commitment_hex: str,
    circuit_version: int,
    ruleset_id: str,
) -> list[int]:
    """Pack public inputs into `uint256[4]` values for Solidity calls."""
    scalars_hex = pack_public_inputs_for_evm(
        theorem_hash_hex=theorem_hash_hex,
        axioms_commitment_hex=axioms_commitment_hex,
        circuit_version=circuit_version,
        ruleset_id=ruleset_id,
    )
    return [_hex_to_int(x) for x in scalars_hex]


def validate_uint256_array(values: Sequence[int], *, expected_len: int) -> None:
    if len(values) != expected_len:
        raise ValueError(f"expected array of length {expected_len}")
    for idx, v in enumerate(values):
        if not isinstance(v, int):
            raise TypeError(f"values[{idx}] must be int")
        if v < 0 or v >= (1 << 256):
            raise ValueError(f"values[{idx}] must fit uint256")
