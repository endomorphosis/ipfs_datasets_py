from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional

import pytest

from ipfs_datasets_py.logic.zkp.onchain_pipeline import (
    OnchainPipelineResult,
    run_offchain_to_onchain_pipeline,
)


@dataclass
class FakeProver:
    proof_obj: Any

    def generate_proof(self, witness_json: str) -> Any:
        return self.proof_obj


class FakeClient:
    def __init__(self, *, precheck_ok: bool = True):
        self.precheck_ok = precheck_ok
        self.calls: list[tuple[str, Any]] = []

    def verify_proof_rpc_call(self, proof_hex: str, public_inputs_hex: list[str]) -> bool:
        self.calls.append(("precheck", (proof_hex, public_inputs_hex)))
        return self.precheck_ok

    def submit_proof_transaction(
        self,
        proof_hex: str,
        public_inputs_hex: list[str],
        from_account: str,
        private_key: str,
        gas_price_wei: Optional[int] = None,
    ) -> str:
        self.calls.append(("submit", (proof_hex, public_inputs_hex, from_account, private_key, gas_price_wei)))
        return "0x" + "ab" * 32

    def wait_for_confirmation(self, tx_hash: str, timeout_seconds: int = 300) -> Mapping[str, Any]:
        self.calls.append(("confirm", (tx_hash, timeout_seconds)))
        return {"transactionHash": tx_hash, "status": 1, "blockNumber": 123}


def _sample_proof_obj() -> dict[str, Any]:
    return {
        "proof_data": "0x" + "a" * 512,
        "public_inputs": {
            "theorem_hash": "0x" + "b" * 64,
            "axioms_commitment": "0x" + "c" * 64,
            "circuit_version": 1,
            "ruleset_id": "TDFOL_v1",
        },
    }


def test_pipeline_dry_run_precheck_only():
    prover = FakeProver(_sample_proof_obj())
    client = FakeClient(precheck_ok=True)

    result = run_offchain_to_onchain_pipeline(
        witness_json="{}",
        prover=prover,
        client=client,
        from_account="0x" + "1" * 40,
        private_key="0x" + "2" * 64,
        dry_run=True,
    )

    assert isinstance(result, OnchainPipelineResult)
    assert result.precheck_ok is True
    assert result.submitted is False
    assert [c[0] for c in client.calls] == ["precheck"]


def test_pipeline_precheck_failure_does_not_submit():
    prover = FakeProver(_sample_proof_obj())
    client = FakeClient(precheck_ok=False)

    result = run_offchain_to_onchain_pipeline(
        witness_json="{}",
        prover=prover,
        client=client,
        from_account="0x" + "1" * 40,
        private_key="0x" + "2" * 64,
        dry_run=False,
    )

    assert result.precheck_ok is False
    assert result.submitted is False
    assert [c[0] for c in client.calls] == ["precheck"]


def test_pipeline_success_submits_and_confirms():
    prover = FakeProver(_sample_proof_obj())
    client = FakeClient(precheck_ok=True)

    result = run_offchain_to_onchain_pipeline(
        witness_json="{}",
        prover=prover,
        client=client,
        from_account="0x" + "1" * 40,
        private_key="0x" + "2" * 64,
        dry_run=False,
        gas_price_wei=123,
        confirmation_timeout_seconds=7,
    )

    assert result.precheck_ok is True
    assert result.submitted is True
    assert result.tx_hash == "0x" + "ab" * 32
    assert result.receipt and result.receipt.get("blockNumber") == 123
    assert [c[0] for c in client.calls] == ["precheck", "submit", "confirm"]


def test_pipeline_requires_proof_data():
    prover = FakeProver({"public_inputs": _sample_proof_obj()["public_inputs"]})
    client = FakeClient(precheck_ok=True)

    with pytest.raises(KeyError):
        run_offchain_to_onchain_pipeline(
            witness_json="{}",
            prover=prover,
            client=client,
            from_account="0x" + "1" * 40,
            private_key="0x" + "2" * 64,
        )
