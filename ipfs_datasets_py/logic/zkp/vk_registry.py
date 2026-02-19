"""Verifying-key (VK) hash registry.

This module is intentionally stdlib-only and backend-agnostic.

It provides a minimal off-chain registry that maps `(circuit_id, version)` to a
VK hash. This supports future workflows where:
- VK artifacts are stored in content-addressed storage (e.g., IPFS), and
- an on-chain registry stores/verifies the VK hash per circuit version.

Note: This does not implement Groth16 setup, proving, or verifying.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, Optional, Tuple
import hashlib
import json

from .statement import parse_circuit_ref_lenient


_U64_MAX = (1 << 64) - 1


def compute_vk_hash(vk: object) -> str:
    """Compute a stable SHA-256 hash for a verifying key representation.

    Supported input types:
    - bytes: hashed directly
    - str: UTF-8 bytes hashed
    - dict/list: canonical JSON (sorted keys, compact separators) hashed

    Returns:
        64-char lowercase hex string.

    Raises:
        TypeError: if `vk` is not a supported type.
    """
    if isinstance(vk, bytes):
        payload = vk
    elif isinstance(vk, str):
        payload = vk.encode("utf-8")
    elif isinstance(vk, (dict, list)):
        payload = json.dumps(vk, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    else:
        raise TypeError("vk must be bytes, str, dict, or list")

    return hashlib.sha256(payload).hexdigest()


def _validate_circuit_id(circuit_id: object) -> str:
    if not isinstance(circuit_id, str):
        raise TypeError("circuit_id must be a str")
    if circuit_id == "":
        raise ValueError("circuit_id cannot be empty")
    if "@" in circuit_id:
        raise ValueError("circuit_id must not contain '@'")
    return circuit_id


def _validate_version(version: object) -> int:
    if not isinstance(version, int):
        raise TypeError("version must be an int")
    if version < 0 or version > _U64_MAX:
        raise ValueError("version must be in uint64 range")
    return version


def _validate_vk_hash_hex(vk_hash_hex: object) -> str:
    if not isinstance(vk_hash_hex, str):
        raise TypeError("vk_hash_hex must be a str")
    if len(vk_hash_hex) != 64:
        raise ValueError("vk_hash_hex must be 64 hex characters")
    try:
        int(vk_hash_hex, 16)
    except Exception as e:
        raise ValueError("vk_hash_hex must be hex") from e
    return vk_hash_hex.lower()


@dataclass(frozen=True)
class VKRegistryEntry:
    circuit_id: str
    version: int
    vk_hash_hex: str


class VKRegistry:
    """In-memory registry mapping `(circuit_id, version)` to VK hash."""

    def __init__(self, entries: Optional[Iterable[VKRegistryEntry]] = None):
        self._entries: Dict[Tuple[str, int], str] = {}
        if entries is not None:
            for entry in entries:
                self.register(entry.circuit_id, entry.version, entry.vk_hash_hex, overwrite=False)

    def register(self, circuit_id: str, version: int, vk_hash_hex: str, *, overwrite: bool = False) -> None:
        circuit_id = _validate_circuit_id(circuit_id)
        version = _validate_version(version)
        vk_hash_hex = _validate_vk_hash_hex(vk_hash_hex)

        key = (circuit_id, version)
        if key in self._entries and not overwrite:
            if self._entries[key] != vk_hash_hex:
                raise ValueError("VK hash already registered for this circuit_id/version")
            return

        self._entries[key] = vk_hash_hex

    def get(self, circuit_id: str, version: int) -> Optional[str]:
        circuit_id = _validate_circuit_id(circuit_id)
        version = _validate_version(version)
        return self._entries.get((circuit_id, version))

    def get_by_ref(self, circuit_ref: str) -> Optional[str]:
        circuit_id, version = parse_circuit_ref_lenient(circuit_ref)
        return self._entries.get((circuit_id, version))

    def list_versions(self, circuit_id: str) -> list[int]:
        circuit_id = _validate_circuit_id(circuit_id)
        versions = [v for (cid, v), _ in self._entries.items() if cid == circuit_id]
        return sorted(versions)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to a JSON-friendly dict."""
        data: Dict[str, Dict[str, str]] = {}
        for (circuit_id, version), vk_hash_hex in self._entries.items():
            data.setdefault(circuit_id, {})[str(version)] = vk_hash_hex
        return {"vk_registry": data}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "VKRegistry":
        if not isinstance(data, dict) or "vk_registry" not in data:
            raise TypeError("data must be a dict containing 'vk_registry'")
        raw = data.get("vk_registry")
        if not isinstance(raw, dict):
            raise TypeError("'vk_registry' must be a dict")

        entries: list[VKRegistryEntry] = []
        for circuit_id, versions in raw.items():
            if not isinstance(versions, dict):
                raise TypeError("vk_registry values must be dicts")
            for version_str, vk_hash_hex in versions.items():
                if not isinstance(version_str, str) or not version_str.isdigit():
                    raise ValueError("version keys must be base-10 integer strings")
                entries.append(
                    VKRegistryEntry(
                        circuit_id=str(circuit_id),
                        version=int(version_str),
                        vk_hash_hex=str(vk_hash_hex),
                    )
                )

        return cls(entries=entries)
