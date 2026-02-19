from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest


_TRUE = {"1", "true", "TRUE", "yes", "YES"}


def _enabled() -> bool:
    return os.environ.get("IPFS_DATASETS_ENABLE_EVM_E2E", "").strip() in _TRUE


@pytest.mark.skipif(
    not _enabled(),
    reason="Local-EVM smoke tests are opt-in (set IPFS_DATASETS_ENABLE_EVM_E2E=1)",
)
def test_local_evm_smoke_compiles_and_deploys_verifiers():
    """Opt-in local EVM smoke test.

    Goals (when enabled + deps available):
    - Prove the Python EVM toolchain is wired: compile Solidity, deploy to an in-memory chain.
    - Confirm the `verifyProof(uint256[8],uint256[4]) -> bool` call path works (via a stub).

    This is intentionally NOT a cryptographic end-to-end proof verification.
    """

    for dep in ("web3", "eth_tester", "solcx"):
        if importlib.util.find_spec(dep) is None:
            pytest.skip(f"Optional dependency {dep!r} is not installed")

    from solcx import compile_source, get_installed_solc_versions, set_solc_version

    installed = list(get_installed_solc_versions())
    if not installed:
        pytest.skip("No solc versions are installed for py-solc-x (solcx)")

    # Use the newest installed solc to reduce version friction.
    solc_version = str(sorted(installed)[-1])
    set_solc_version(solc_version)

    repo_root = Path(__file__).resolve().parents[4]
    groth_path = (
        repo_root
        / "ipfs_datasets_py"
        / "processors"
        / "groth16_backend"
        / "contracts"
        / "GrothVerifier.sol"
    )
    groth_source = groth_path.read_text(encoding="utf-8")

    compiled = compile_source(groth_source, output_values=["abi", "bin"])
    groth_key = next(k for k in compiled.keys() if k.endswith(":GrothVerifier"))
    groth_abi = compiled[groth_key]["abi"]
    groth_bin = compiled[groth_key]["bin"]
    assert groth_bin

    # A minimal stub verifier keeps the smoke test stable even if the prototype
    # verifier reverts on invalid points.
    smoke_source = """
pragma solidity ^0.8.0;

contract SmokeVerifier {
    function verifyProof(uint256[8] calldata, uint256[4] calldata) external pure returns (bool) {
        return false;
    }
}
""".strip()

    compiled_smoke = compile_source(smoke_source, output_values=["abi", "bin"])
    smoke_key = next(k for k in compiled_smoke.keys() if k.endswith(":SmokeVerifier"))
    smoke_abi = compiled_smoke[smoke_key]["abi"]
    smoke_bin = compiled_smoke[smoke_key]["bin"]
    assert smoke_bin

    from web3 import Web3
    from web3.providers.eth_tester import EthereumTesterProvider

    w3 = Web3(EthereumTesterProvider())
    from_account = w3.eth.accounts[0]

    Groth = w3.eth.contract(abi=groth_abi, bytecode=groth_bin)
    tx_hash = Groth.constructor().transact({"from": from_account})
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
    assert receipt.contractAddress
    assert w3.eth.get_code(receipt.contractAddress) != b""

    Smoke = w3.eth.contract(abi=smoke_abi, bytecode=smoke_bin)
    tx_hash2 = Smoke.constructor().transact({"from": from_account})
    receipt2 = w3.eth.wait_for_transaction_receipt(tx_hash2)

    smoke = w3.eth.contract(address=receipt2.contractAddress, abi=smoke_abi)
    assert smoke.functions.verifyProof([0] * 8, [0] * 4).call() is False
