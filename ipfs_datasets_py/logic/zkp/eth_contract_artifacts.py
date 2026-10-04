"""EVM contract ABI/artifact helpers (stdlib-only).

This module is intentionally dependency-light: it does not require `web3`.

It provides helpers to load contract ABIs and deployment bytecode from common
JSON artifact formats (Hardhat/Truffle/solc-style outputs).

The Ethereum integration layer (`eth_integration.py`) can optionally use these
helpers when `web3` is installed.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Mapping, Optional, Union


PathLike = Union[str, Path]


@dataclass(frozen=True)
class ContractArtifact:
    """Parsed contract artifact information."""

    abi: list[dict[str, Any]]
    bytecode: Optional[str] = None
    contract_name: Optional[str] = None


def _normalize_hex_prefixed(hex_str: Optional[str]) -> Optional[str]:
    if hex_str is None:
        return None

    s = str(hex_str).strip()
    if s == "" or s == "0x":
        return None
    if s.startswith("0x") or s.startswith("0X"):
        return "0x" + s[2:]
    return "0x" + s


def _as_mapping(obj: Any) -> Mapping[str, Any]:
    if not isinstance(obj, Mapping):
        raise ValueError("Contract artifact JSON must be an object")
    return obj


def load_contract_artifact(path: PathLike) -> ContractArtifact:
    """Load ABI/bytecode from a JSON artifact file.

    Supported shapes (best-effort):
    - {"abi": [...], "bytecode": "0x..."}
    - {"abi": [...], "bytecode": {"object": "..."}}
    - {"abi": [...], "evm": {"bytecode": {"object": "..."}}}

    Args:
        path: Path to a JSON artifact.

    Returns:
        ContractArtifact(abi=..., bytecode=..., contract_name=...)

    Raises:
        ValueError: If ABI is missing or malformed.
    """

    p = Path(path)
    data = json.loads(p.read_text(encoding="utf-8"))
    obj = _as_mapping(data)

    abi = obj.get("abi")
    if not isinstance(abi, list):
        raise ValueError("Contract artifact missing 'abi' list")

    contract_name = None
    for key in ("contractName", "contract_name", "name"):
        value = obj.get(key)
        if isinstance(value, str) and value.strip():
            contract_name = value.strip()
            break

    bytecode: Optional[str] = None

    # Hardhat/Truffle-style
    top_level_bytecode = obj.get("bytecode")
    if isinstance(top_level_bytecode, str):
        bytecode = top_level_bytecode
    elif isinstance(top_level_bytecode, Mapping):
        maybe_obj = top_level_bytecode.get("object")
        if isinstance(maybe_obj, str):
            bytecode = maybe_obj

    # solc-style
    if bytecode is None:
        evm = obj.get("evm")
        if isinstance(evm, Mapping):
            evm_bc = evm.get("bytecode")
            if isinstance(evm_bc, Mapping):
                maybe_obj = evm_bc.get("object")
                if isinstance(maybe_obj, str):
                    bytecode = maybe_obj

    bytecode = _normalize_hex_prefixed(bytecode)

    # Validate ABI elements are objects (helpful early error)
    normalized_abi: list[dict[str, Any]] = []
    for item in abi:
        if not isinstance(item, Mapping):
            raise ValueError("Contract ABI entries must be JSON objects")
        normalized_abi.append(dict(item))

    return ContractArtifact(abi=normalized_abi, bytecode=bytecode, contract_name=contract_name)


def load_contract_abi(path: PathLike) -> list[dict[str, Any]]:
    """Load just the ABI list from an artifact JSON file."""

    return load_contract_artifact(path).abi
