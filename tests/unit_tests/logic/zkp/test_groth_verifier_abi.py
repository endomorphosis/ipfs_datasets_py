from __future__ import annotations

from typing import Any


def _find_fn(abi: list[dict[str, Any]], name: str) -> dict[str, Any]:
    for entry in abi:
        if entry.get("type") == "function" and entry.get("name") == name:
            return entry
    raise AssertionError(f"function {name!r} not found in ABI")


def test_groth_verifier_abi_has_verify_proof_signature():
    # eth_integration is import-safe without web3; ABI constants must exist.
    from ipfs_datasets_py.logic.zkp.eth_integration import GROTH_VERIFIER_ABI

    fn = _find_fn(GROTH_VERIFIER_ABI, "verifyProof")

    assert fn.get("stateMutability") == "view"

    inputs = fn.get("inputs")
    assert isinstance(inputs, list)
    assert [i.get("type") for i in inputs] == ["uint256[8]", "uint256[4]"]

    outputs = fn.get("outputs")
    assert isinstance(outputs, list)
    assert len(outputs) == 1
    assert outputs[0].get("type") == "bool"
