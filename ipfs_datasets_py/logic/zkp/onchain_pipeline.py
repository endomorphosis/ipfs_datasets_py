"""Dependency-light off-chain → on-chain submission pipeline.

This module is intentionally stdlib-only. It does not import `web3`.

It provides orchestration logic for:
- generating a proof (via an injected prover backend)
- packing public inputs for EVM verifier calls
- performing an optional RPC precheck
- submitting the on-chain transaction and waiting for confirmation

Actual chain interaction is provided by an injected client implementation.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Mapping, Optional, Protocol

from .evm_public_inputs import pack_public_inputs_for_evm


class OnchainClient(Protocol):
    """Minimal interface required to submit and confirm an on-chain verify call."""

    def verify_proof_rpc_call(self, proof_hex: str, public_inputs_hex: list[str]) -> bool:  # pragma: no cover
        ...

    def submit_proof_transaction(
        self,
        proof_hex: str,
        public_inputs_hex: list[str],
        from_account: str,
        private_key: str,
        gas_price_wei: Optional[int] = None,
    ) -> Any:  # pragma: no cover
        ...

    def wait_for_confirmation(self, tx_hash: Any, timeout_seconds: int = 300) -> Mapping[str, Any]:  # pragma: no cover
        ...


class ProverBackend(Protocol):
    """Minimal interface required to generate a proof."""

    def generate_proof(self, witness_json: str) -> Any:  # pragma: no cover
        ...


@dataclass(frozen=True)
class OnchainPipelineResult:
    """Result of running the dependency-light pipeline."""

    precheck_ok: bool
    submitted: bool
    tx_hash: Optional[Any] = None
    receipt: Optional[Mapping[str, Any]] = None


def _as_mapping(obj: Any) -> Mapping[str, Any]:
    if isinstance(obj, Mapping):
        return obj
    raise TypeError("proof object must be a mapping")


def _loads_json_maybe(value: Any) -> Any:
    if isinstance(value, str):
        s = value.strip()
        if s.startswith("{"):
            return json.loads(s)
    return value


def run_offchain_to_onchain_pipeline(
    *,
    witness_json: str,
    prover: ProverBackend,
    client: OnchainClient,
    from_account: str,
    private_key: str,
    dry_run: bool = False,
    gas_price_wei: Optional[int] = None,
    confirmation_timeout_seconds: int = 300,
) -> OnchainPipelineResult:
    """Generate a proof and submit it for on-chain verification.

    Notes:
    - This pipeline stays dependency-light by taking an injected `client`.
    - If `dry_run` is True, it runs generation + RPC precheck only.

    Raises:
        KeyError/TypeError/ValueError for malformed proof output.
    """

    proof_obj = _loads_json_maybe(prover.generate_proof(witness_json))
    proof_map = _as_mapping(proof_obj)

    proof_hex = proof_map["proof_data"]
    if not isinstance(proof_hex, str) or not proof_hex:
        raise ValueError("proof_data must be a non-empty hex string")

    public_inputs = _as_mapping(proof_map["public_inputs"])

    public_inputs_hex = pack_public_inputs_for_evm(
        theorem_hash_hex=str(public_inputs["theorem_hash"]),
        axioms_commitment_hex=str(public_inputs["axioms_commitment"]),
        circuit_version=int(public_inputs["circuit_version"]),
        ruleset_id=str(public_inputs["ruleset_id"]),
    )

    precheck_ok = bool(client.verify_proof_rpc_call(proof_hex, public_inputs_hex))
    if dry_run or not precheck_ok:
        return OnchainPipelineResult(precheck_ok=precheck_ok, submitted=False, tx_hash=None, receipt=None)

    tx_hash = client.submit_proof_transaction(
        proof_hex,
        public_inputs_hex,
        from_account,
        private_key,
        gas_price_wei=gas_price_wei,
    )
    receipt = client.wait_for_confirmation(tx_hash, timeout_seconds=confirmation_timeout_seconds)

    return OnchainPipelineResult(precheck_ok=True, submitted=True, tx_hash=tx_hash, receipt=receipt)
