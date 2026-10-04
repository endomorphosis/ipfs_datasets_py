from __future__ import annotations

import json
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.zkp.eth_contract_artifacts import (
    ContractArtifact,
    load_contract_abi,
    load_contract_artifact,
)


def _write(tmp_path: Path, name: str, obj: dict) -> Path:
    p = tmp_path / name
    p.write_text(json.dumps(obj), encoding="utf-8")
    return p


def test_load_contract_artifact_top_level_bytecode(tmp_path: Path):
    p = _write(
        tmp_path,
        "GrothVerifier.json",
        {
            "contractName": "GrothVerifier",
            "abi": [{"type": "function", "name": "verifyProof", "inputs": []}],
            "bytecode": "60016000",
        },
    )

    art = load_contract_artifact(p)
    assert isinstance(art, ContractArtifact)
    assert art.contract_name == "GrothVerifier"
    assert art.bytecode == "0x60016000"
    assert art.abi[0]["name"] == "verifyProof"


def test_load_contract_artifact_solc_evm_bytecode(tmp_path: Path):
    p = _write(
        tmp_path,
        "VKHashRegistry.json",
        {
            "contractName": "VKHashRegistry",
            "abi": [{"type": "function", "name": "registerVK", "inputs": []}],
            "evm": {"bytecode": {"object": "0x60026000"}},
        },
    )

    art = load_contract_artifact(p)
    assert art.contract_name == "VKHashRegistry"
    assert art.bytecode == "0x60026000"


def test_load_contract_abi_only(tmp_path: Path):
    p = _write(
        tmp_path,
        "OnlyAbi.json",
        {
            "abi": [
                {"type": "function", "name": "f", "inputs": []},
                {"type": "event", "name": "E", "inputs": []},
            ]
        },
    )

    abi = load_contract_abi(p)
    assert isinstance(abi, list)
    assert {entry["type"] for entry in abi} == {"function", "event"}


def test_load_contract_artifact_requires_abi(tmp_path: Path):
    p = _write(tmp_path, "Bad.json", {"bytecode": "0x1234"})

    with pytest.raises(ValueError, match=r"abi"):
        load_contract_artifact(p)
