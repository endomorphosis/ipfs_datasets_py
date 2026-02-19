"""Helpers for VK hash registry on-chain payloads.

These helpers are intentionally light-weight and safe to import in environments
without optional EVM dependencies.

Design:
- The Solidity VK registry uses `bytes32 circuitId` and `bytes32 vkHash`.
- `vk_hash_hex` in this codebase is typically a 64-hex-character SHA-256 digest.

This module validates and normalizes these values and can optionally compute a
`circuitId` as keccak256(circuit_id_text) when `web3` is installed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


def _normalize_hex_no_prefix(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError("value must be a str")
    s = value.strip().lower()
    if s.startswith("0x"):
        s = s[2:]
    return s


def normalize_bytes32_hex(value: str) -> str:
    """Normalize a hex string to a 0x-prefixed 32-byte hex value."""
    s = _normalize_hex_no_prefix(value)
    if len(s) != 64:
        raise ValueError("value must be 32 bytes (64 hex chars)")
    try:
        int(s, 16)
    except Exception as e:
        raise ValueError("value must be hex") from e
    return "0x" + s


def vk_hash_hex_to_bytes32(vk_hash_hex: str) -> str:
    """Convert a 64-hex-character vk hash to a bytes32 hex string."""
    return normalize_bytes32_hex(vk_hash_hex)


def circuit_id_text_to_bytes32(circuit_id_text: str) -> str:
    """Compute circuitId bytes32 as keccak256(text) (requires web3).

    Raises:
        ImportError if web3 is not installed.
    """
    if not isinstance(circuit_id_text, str):
        raise TypeError("circuit_id_text must be a str")
    if circuit_id_text == "":
        raise ValueError("circuit_id_text cannot be empty")

    try:
        from web3 import Web3  # type: ignore
    except ModuleNotFoundError as e:  # pragma: no cover
        raise ImportError(
            "Optional dependency 'web3' is required to compute keccak256 circuitId. "
            "Install it (e.g. `pip install web3`) or pass a precomputed bytes32 circuitId."
        ) from e

    return "0x" + Web3.keccak(text=circuit_id_text).hex()


@dataclass(frozen=True)
class RegisterVKPayload:
    circuit_id_bytes32: str
    version: int
    vk_hash_bytes32: str


def build_register_vk_payload(
    *,
    circuit_id_bytes32: str,
    version: int,
    vk_hash_hex: str,
) -> RegisterVKPayload:
    """Validate inputs for registerVK(circuitId, version, vkHash, ...)."""
    if not isinstance(version, int):
        raise TypeError("version must be int")
    if version < 0 or version > (1 << 64) - 1:
        raise ValueError("version must fit uint64")

    return RegisterVKPayload(
        circuit_id_bytes32=normalize_bytes32_hex(circuit_id_bytes32),
        version=version,
        vk_hash_bytes32=vk_hash_hex_to_bytes32(vk_hash_hex),
    )
