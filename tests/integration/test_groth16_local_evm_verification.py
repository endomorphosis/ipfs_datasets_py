import json
import os
import subprocess
from pathlib import Path

import pytest


@pytest.mark.skipif(
    os.environ.get("IPFS_DATASETS_RUN_GROTH16_EVM", "").strip() not in {"1", "true", "TRUE", "yes", "YES"},
    reason="Set IPFS_DATASETS_RUN_GROTH16_EVM=1 to run the local-EVM Groth16 test",
)
def test_groth16_proof_verifies_on_local_evm(tmp_path: Path):
    solcx = pytest.importorskip("solcx")
    pytest.importorskip("eth_tester")
    web3_mod = pytest.importorskip("web3")
    eth_tester_provider_mod = pytest.importorskip("web3.providers.eth_tester")
    Web3 = web3_mod.Web3
    EthereumTesterProvider = eth_tester_provider_mod.EthereumTesterProvider

    ipfs_root = Path(__file__).resolve().parents[2]  # .../ipfs_datasets_py

    crate_dir = ipfs_root / "ipfs_datasets_py" / "processors" / "groth16_backend"
    if not crate_dir.exists():
        crate_dir = ipfs_root / "processors" / "groth16_backend"
    if not crate_dir.exists():
        pytest.skip("groth16_backend crate not found in expected locations")

    binary_path = crate_dir / "target" / "release" / "groth16"
    if not binary_path.exists():
        # Only build when explicitly opted in via env var.
        subprocess.run(["cargo", "build", "--release"], cwd=crate_dir, check=True)
    if not binary_path.exists():
        pytest.skip("groth16 binary not available after cargo build --release")

    artifacts_root = tmp_path / "artifacts"
    env = os.environ.copy()
    env["GROTH16_BACKEND_ARTIFACTS_ROOT"] = str(artifacts_root)

    # 1) Setup (writes proving_key.bin + verifying_key.bin under artifacts_root/v1/)
    setup_proc = subprocess.run(
        [str(binary_path), "setup", "--version", "1", "--seed", "123", "--quiet"],
        cwd=crate_dir,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    manifest = json.loads(setup_proc.stdout)
    vk_path = manifest["verifying_key_path"]

    # 2) Export Solidity verifier contract for this VK
    base_verifier_src = (crate_dir / "contracts" / "GrothVerifier.sol").read_text(encoding="utf-8")
    (tmp_path / "GrothVerifier.sol").write_text(base_verifier_src, encoding="utf-8")

    verifier_sol_path = tmp_path / "GrothVerifierV1.sol"
    subprocess.run(
        [
            str(binary_path),
            "export-solidity",
            "--verifying-key",
            str(vk_path),
            "--version",
            "1",
            "--out",
            str(verifier_sol_path),
            "--import-path",
            "GrothVerifier.sol",
            "--quiet",
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )

    # 3) Prove
    vectors_path = ipfs_root / "tests" / "unit_tests" / "logic" / "zkp" / "groth16_wire_vectors.json"
    vectors = json.loads(vectors_path.read_text(encoding="utf-8"))
    witness = vectors["vectors"]["modus_ponens_v1"]["witness"]

    prove_proc = subprocess.run(
        [
            str(binary_path),
            "prove",
            "--input",
            "/dev/stdin",
            "--output",
            "/dev/stdout",
            "--seed",
            "42",
            "--quiet",
        ],
        cwd=crate_dir,
        env=env,
        input=json.dumps(witness),
        capture_output=True,
        text=True,
        check=True,
    )
    proof_payload = json.loads(prove_proc.stdout)

    evm_proof = proof_payload.get("evm_proof")
    evm_inputs = proof_payload.get("evm_public_inputs")
    assert isinstance(evm_proof, list) and len(evm_proof) == 8
    assert isinstance(evm_inputs, list) and len(evm_inputs) == 4

    proof_words = [int(x, 16) for x in evm_proof]
    public_inputs = [int(x, 16) for x in evm_inputs]

    # 4) Compile + deploy to an in-memory EVM, then call verifyProof.
    installed = solcx.get_installed_solc_versions()
    if not installed:
        pytest.skip("No solc installed for py-solc-x; install one (e.g. solcx.install_solc('0.8.20'))")
    solcx.set_solc_version(sorted(installed)[-1])

    compiled = solcx.compile_standard(
        {
            "language": "Solidity",
            "sources": {
                "GrothVerifier.sol": {"content": (tmp_path / "GrothVerifier.sol").read_text(encoding="utf-8")},
                "GrothVerifierV1.sol": {"content": verifier_sol_path.read_text(encoding="utf-8")},
            },
            "settings": {
                "outputSelection": {
                    "*": {
                        "*": ["abi", "evm.bytecode.object"],
                    }
                }
            },
        },
        allow_paths=str(tmp_path),
    )

    contract_out = compiled["contracts"]["GrothVerifierV1.sol"]["GrothVerifierV1"]
    abi = contract_out["abi"]
    bytecode = contract_out["evm"]["bytecode"]["object"]

    w3 = Web3(EthereumTesterProvider())
    deployer = w3.eth.accounts[0]

    contract = w3.eth.contract(abi=abi, bytecode=bytecode)
    tx_hash = contract.constructor().transact({"from": deployer})
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash)

    verifier = w3.eth.contract(address=receipt.contractAddress, abi=abi)
    assert verifier.functions.verifyProof(proof_words, public_inputs).call({"from": deployer}) is True
