from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import pytest


def test_eth_integration_pipeline_packs_public_inputs_for_evm(monkeypatch: pytest.MonkeyPatch):
    try:
        from ipfs_datasets_py.logic.zkp.evm_public_inputs import pack_public_inputs_for_evm
        from ipfs_datasets_py.logic.zkp.eth_integration import (
            EthereumConfig,
            ProofSubmissionPipeline,
        )
        import ipfs_datasets_py.logic.zkp.eth_integration as eth_integration
    except ImportError as e:
        pytest.skip(f"eth_integration optional deps missing: {e}")

    proof_obj = {
        "proof_data": "00" * 32,
        "public_inputs": {
            "theorem_hash": "0x" + "11" * 32,
            "axioms_commitment": "0x" + "22" * 32,
            "circuit_version": 1,
            "ruleset_id": "TDFOL_v1",
        },
    }

    expected_public_inputs = pack_public_inputs_for_evm(
        theorem_hash_hex=proof_obj["public_inputs"]["theorem_hash"],
        axioms_commitment_hex=proof_obj["public_inputs"]["axioms_commitment"],
        circuit_version=int(proof_obj["public_inputs"]["circuit_version"]),
        ruleset_id=proof_obj["public_inputs"]["ruleset_id"],
    )

    @dataclass
    class _GasEstimate:
        estimated_fee_eth: float = 0.0
        recommended_gas_price: float = 1.0
        base_fee: float = 1.0

    class DummyEthereumProofClient:
        last_instance: "DummyEthereumProofClient | None" = None

        def __init__(self, config: EthereumConfig):
            self.config = config
            self.calls: list[tuple[str, Any]] = []
            DummyEthereumProofClient.last_instance = self

        def estimate_verification_cost(self, proof_bytes: bytes) -> _GasEstimate:
            self.calls.append(("estimate", proof_bytes))
            return _GasEstimate()

        def verify_proof_rpc_call(self, proof_hex: str, public_inputs: list[str]) -> bool:
            self.calls.append(("precheck", (proof_hex, public_inputs)))
            return True

    class DummyGroth16Backend:
        def generate_proof(self, witness_json: str) -> str:
            return json.dumps(proof_obj)

    monkeypatch.setattr(eth_integration, "EthereumProofClient", DummyEthereumProofClient)

    cfg = EthereumConfig(
        rpc_url="http://localhost:8545",
        network_id=31337,
        network_name="local",
        verifier_contract_address="0x" + "a" * 40,
        registry_contract_address="0x" + "b" * 40,
    )

    pipeline = ProofSubmissionPipeline(cfg, DummyGroth16Backend())
    pipeline.generate_and_verify_proof(
        witness_json="{}",
        from_account="0x" + "1" * 40,
        private_key="0x" + "2" * 64,
        dry_run=True,
    )

    client = DummyEthereumProofClient.last_instance
    assert client is not None

    precheck_calls = [c for c in client.calls if c[0] == "precheck"]
    assert len(precheck_calls) == 1
    _, (seen_proof_hex, seen_public_inputs) = precheck_calls[0]

    assert seen_proof_hex == proof_obj["proof_data"]
    assert seen_public_inputs == expected_public_inputs
