"""Unit tests for eth_integration signing cutover (CRYPTOIR-G600 / CRYPTOIR-034).

Acceptance:

* ``logic/zkp/eth_integration.py`` signing/broadcast helpers are disabled by
  default without a consumed guard capability.
* There is no ``approved=true`` compatibility escape hatch.
* With a valid capability + live request, GuardService consumption runs
  immediately before sign/broadcast.
* Replay / substitution fail closed.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from ipfs_datasets_py.logic.zkp.eth_integration import (
    EthereumConfig,
    EthereumProofClient,
    EthTransactionGuardError,
    ProofSubmissionPipeline,
    require_consumed_guard_capability,
)
from ipfs_datasets_py.processors.wallets.guard import (
    AdmissibilityCapability,
    AssetAmount,
    ExpectedEffect,
    FeeSpec,
    GuardConsumptionRaceError,
    GuardService,
    TransactionCandidate,
    TransactionIntent,
    TransactionPreflightRequest,
)


_DIGEST_A = "a" * 64
_DIGEST_ENV = "e" * 64
_ISSUED = "2026-07-28T12:00:00Z"
_DEADLINE = "2026-07-28T12:05:00Z"
_EXPIRY = "2026-07-28T12:10:00Z"
_INTENT_EXPIRY = "2026-07-28T12:15:00Z"
_NOW_OK = "2026-07-28T12:02:00Z"


def _intent(**overrides: Any) -> TransactionIntent:
    base: dict[str, Any] = {
        "intent_id": "intent:zkp-submit-001",
        "network": "ethereum:sepolia",
        "sender": "0xSender0000000000000000000000000000000001",
        "destination": "0xVerifier00000000000000000000000000000002",
        "method": "verifyProof(uint256[8],uint256[4])",
        "assets": (
            AssetAmount(
                asset_id="asset:eth-native",
                amount="0",
                asset_namespace="native",
                symbol="ETH",
            ),
        ),
        "fees": (FeeSpec(amount="21000000000000", asset_id="asset:eth-native"),),
        "nonce_or_sequence": "7",
        "signers": ("signer:0xSender0000000000000000000000000000000001",),
        "expected_effects": (
            ExpectedEffect(
                effect_id="effect:verify-proof",
                kind="contract_call",
                summary="submit groth16 proof",
            ),
        ),
        "expires_at": _INTENT_EXPIRY,
        "utxos": (),
        "chain_namespace": "eip155",
    }
    base.update(overrides)
    return TransactionIntent(**base)


def _candidate(
    intent: TransactionIntent | None = None, **overrides: Any
) -> TransactionCandidate:
    intent = intent or _intent()
    base: dict[str, Any] = {
        "candidate_id": "candidate:zkp-001",
        "intent_id": intent.intent_id,
        "serialized_digest": _DIGEST_A,
        "encoding": "rlp",
        "byte_length": 256,
        "network": intent.network,
    }
    base.update(overrides)
    return TransactionCandidate(**base)


def _request(
    intent: TransactionIntent | None = None,
    candidate: TransactionCandidate | None = None,
    **overrides: Any,
) -> TransactionPreflightRequest:
    intent = intent or _intent()
    candidate = candidate or _candidate(intent)
    base: dict[str, Any] = {
        "request_id": "req:zkp-001",
        "intent": intent,
        "candidate": candidate,
        "tenant_id": "tenant:zkp",
        "actor_id": "actor:proof-pipeline",
        "audience_id": "audience:eth-integration",
        "policy_id": "policy:wallet-guard-v1",
        "security_requirement_ids": ("sec:no-self-destruct",),
        "compliance_requirement_ids": ("comp:direct-sanctions",),
        "issued_at": _ISSUED,
        "deadline": _DEADLINE,
        "expiry": _EXPIRY,
        "environment_id": "env:test",
        "environment_digest": _DIGEST_ENV,
        "nonce": "nonce-zkp-001",
    }
    base.update(overrides)
    return TransactionPreflightRequest(**base)


def _allow_capability(
    *,
    service: GuardService | None = None,
    request: TransactionPreflightRequest | None = None,
) -> tuple[GuardService, TransactionPreflightRequest, AdmissibilityCapability]:
    service = service or GuardService()
    request = request or _request()
    security = {req: "pass" for req in request.security_requirement_ids}
    compliance = {req: "pass" for req in request.compliance_requirement_ids}
    result = service.evaluate_preflight(
        request,
        security_results=security,
        compliance_results=compliance,
        now=_NOW_OK,
    )
    assert result.capability is not None
    return service, request, result.capability


@pytest.fixture
def ethereum_config() -> EthereumConfig:
    return EthereumConfig(
        rpc_url="http://localhost:8545",
        network_id=1337,
        network_name="ganache",
        verifier_contract_address="0x" + "1" * 40,
        registry_contract_address="0x" + "2" * 40,
        confirmation_blocks=1,
    )


def test_require_consumed_guard_disabled_without_capability() -> None:
    with pytest.raises(EthTransactionGuardError, match="disabled by default"):
        require_consumed_guard_capability()


def test_require_consumed_guard_rejects_approved_escape() -> None:
    service, request, capability = _allow_capability()
    with pytest.raises(EthTransactionGuardError, match="approved"):
        require_consumed_guard_capability(
            admissibility_capability=capability,
            live_request=request,
            guard_service=service,
            approved=True,
        )


def test_require_consumed_guard_succeeds_once() -> None:
    service, request, capability = _allow_capability()
    consumption = require_consumed_guard_capability(
        admissibility_capability=capability,
        live_request=request,
        guard_service=service,
        now=_NOW_OK,
    )
    assert consumption.allowed is True
    with pytest.raises(EthTransactionGuardError):
        require_consumed_guard_capability(
            admissibility_capability=capability,
            live_request=request,
            guard_service=service,
            now=_NOW_OK,
        )


def test_submit_proof_transaction_disabled_by_default(
    ethereum_config: EthereumConfig,
) -> None:
    with patch(
        "ipfs_datasets_py.logic.zkp.eth_integration.Web3"
    ) as mock_web3:
        mock_instance = MagicMock()
        mock_instance.is_connected.return_value = True
        mock_instance.eth.chain_id = 1337
        mock_web3.return_value = mock_instance
        mock_web3.to_checksum_address = lambda a: a

        client = EthereumProofClient(ethereum_config)
        client.verifier_contract = MagicMock()

        with pytest.raises(EthTransactionGuardError, match="disabled by default"):
            client.submit_proof_transaction(
                "0x" + "a" * 512,
                ["0x" + "b" * 64, "0x" + "c" * 64, "0x1", "0x" + "d" * 40],
                "0x" + "1" * 40,
                "0x" + "2" * 64,
            )


def test_submit_proof_transaction_rejects_approved_true(
    ethereum_config: EthereumConfig,
) -> None:
    service, request, capability = _allow_capability()
    with patch(
        "ipfs_datasets_py.logic.zkp.eth_integration.Web3"
    ) as mock_web3:
        mock_instance = MagicMock()
        mock_instance.is_connected.return_value = True
        mock_instance.eth.chain_id = 1337
        mock_web3.return_value = mock_instance
        mock_web3.to_checksum_address = lambda a: a

        client = EthereumProofClient(ethereum_config)
        client.verifier_contract = MagicMock()

        with pytest.raises(EthTransactionGuardError, match="approved"):
            client.submit_proof_transaction(
                "0x" + "a" * 512,
                ["0x" + "b" * 64, "0x" + "c" * 64, "0x1", "0x" + "d" * 40],
                "0x" + "1" * 40,
                "0x" + "2" * 64,
                admissibility_capability=capability,
                live_request=request,
                guard_service=service,
                approved=True,
            )


def test_submit_proof_transaction_with_consumed_capability(
    ethereum_config: EthereumConfig,
) -> None:
    service, request, capability = _allow_capability()

    with patch(
        "ipfs_datasets_py.logic.zkp.eth_integration.Web3"
    ) as mock_web3:
        mock_instance = MagicMock()
        mock_instance.is_connected.return_value = True
        mock_instance.eth.chain_id = 1337
        mock_instance.eth.gas_price = 20 * 10**9
        mock_instance.eth.get_transaction_count.return_value = 0

        mock_contract = MagicMock()
        mock_tx = {"to": "0x" + "1" * 40, "data": "0x"}
        mock_contract.functions.verifyProof.return_value.build_transaction.return_value = (
            mock_tx
        )

        mock_account = MagicMock()
        mock_signed = MagicMock()
        mock_signed.rawTransaction = b"signed"
        mock_account.sign_transaction.return_value = mock_signed
        mock_instance.eth.account = mock_account

        mock_tx_hash = bytes.fromhex("ab" * 32)
        mock_instance.eth.send_raw_transaction.return_value = mock_tx_hash
        mock_instance.eth.contract.return_value = mock_contract

        mock_web3.return_value = mock_instance
        mock_web3.to_checksum_address = lambda a: a

        client = EthereumProofClient(ethereum_config)
        client.verifier_contract = mock_contract

        tx_hash = client.submit_proof_transaction(
            "0x" + "a" * 512,
            ["0x" + "b" * 64, "0x" + "c" * 64, "0x1", "0x" + "d" * 40],
            "0x" + "1" * 40,
            "0x" + "2" * 64,
            admissibility_capability=capability,
            live_request=request,
            guard_service=service,
            now=_NOW_OK,
        )
        assert tx_hash == mock_tx_hash
        mock_account.sign_transaction.assert_called_once()
        mock_instance.eth.send_raw_transaction.assert_called_once_with(b"signed")

        # Capability is one-use: second submission fails closed.
        with pytest.raises(EthTransactionGuardError):
            client.submit_proof_transaction(
                "0x" + "a" * 512,
                ["0x" + "b" * 64, "0x" + "c" * 64, "0x1", "0x" + "d" * 40],
                "0x" + "1" * 40,
                "0x" + "2" * 64,
                admissibility_capability=capability,
                live_request=request,
                guard_service=service,
                now=_NOW_OK,
            )


def test_register_vk_hash_disabled_without_capability(
    ethereum_config: EthereumConfig,
) -> None:
    ethereum_config.vk_hash_registry_contract_address = "0x" + "3" * 40
    with patch(
        "ipfs_datasets_py.logic.zkp.eth_integration.Web3"
    ) as mock_web3:
        mock_instance = MagicMock()
        mock_instance.is_connected.return_value = True
        mock_instance.eth.chain_id = 1337
        mock_web3.return_value = mock_instance
        mock_web3.to_checksum_address = lambda a: a
        mock_web3.keccak = MagicMock(return_value=bytes.fromhex("cd" * 32))

        client = EthereumProofClient(ethereum_config)
        client.vk_hash_registry_contract = MagicMock()

        with pytest.raises(EthTransactionGuardError, match="disabled by default"):
            client.register_vk_hash(
                "circuit-a",
                1,
                "ab" * 32,
                from_account="0x" + "1" * 40,
                private_key="0x" + "2" * 64,
            )


def test_pipeline_dry_run_skips_guard(ethereum_config: EthereumConfig) -> None:
    """Dry-run / RPC-only paths remain available without a capability."""

    with patch(
        "ipfs_datasets_py.logic.zkp.eth_integration.Web3"
    ) as mock_web3:
        mock_instance = MagicMock()
        mock_instance.is_connected.return_value = True
        mock_instance.eth.chain_id = 1337
        mock_instance.eth.gas_price = 20 * 10**9
        mock_web3.return_value = mock_instance
        mock_web3.to_checksum_address = lambda a: a
        mock_web3.from_wei = lambda v, _u: 0.0

        backend = MagicMock()
        backend.generate_proof.return_value = {
            "proof_data": "aa" * 32,
            "public_inputs": {
                "theorem_hash": "0x" + "b" * 64,
                "axioms_commitment": "0x" + "c" * 64,
                "circuit_version": 1,
                "ruleset_id": "ruleset:test",
            },
        }

        pipeline = ProofSubmissionPipeline(ethereum_config, backend)
        pipeline.eth_client.verify_proof_rpc_call = MagicMock(return_value=True)
        pipeline.eth_client.estimate_verification_cost = MagicMock(
            return_value=MagicMock(
                estimated_fee_eth=0.01,
                recommended_gas_price=1e9,
                base_fee=1e9,
            )
        )

        result = pipeline.generate_and_verify_proof(
            "{}",
            "0x" + "1" * 40,
            "0x" + "2" * 64,
            dry_run=True,
        )
        assert result.verified is False
        assert result.transaction_hash.startswith("0x")


def test_pipeline_live_submission_requires_capability(
    ethereum_config: EthereumConfig,
) -> None:
    with patch(
        "ipfs_datasets_py.logic.zkp.eth_integration.Web3"
    ) as mock_web3:
        mock_instance = MagicMock()
        mock_instance.is_connected.return_value = True
        mock_instance.eth.chain_id = 1337
        mock_instance.eth.gas_price = 20 * 10**9
        mock_web3.return_value = mock_instance
        mock_web3.to_checksum_address = lambda a: a

        backend = MagicMock()
        backend.generate_proof.return_value = {
            "proof_data": "aa" * 32,
            "public_inputs": {
                "theorem_hash": "0x" + "b" * 64,
                "axioms_commitment": "0x" + "c" * 64,
                "circuit_version": 1,
                "ruleset_id": "ruleset:test",
            },
        }

        pipeline = ProofSubmissionPipeline(ethereum_config, backend)
        pipeline.eth_client.verify_proof_rpc_call = MagicMock(return_value=True)
        pipeline.eth_client.estimate_verification_cost = MagicMock(
            return_value=MagicMock(
                estimated_fee_eth=0.01,
                recommended_gas_price=1e9,
                base_fee=1e9,
            )
        )

        with pytest.raises(EthTransactionGuardError, match="disabled by default"):
            pipeline.generate_and_verify_proof(
                "{}",
                "0x" + "1" * 40,
                "0x" + "2" * 64,
                dry_run=False,
            )


def test_substitution_fails_before_signing(ethereum_config: EthereumConfig) -> None:
    service, request, capability = _allow_capability()
    mutated = _request(
        intent=_intent(destination="0xAttacker00000000000000000000000000000099"),
        candidate=_candidate(
            _intent(destination="0xAttacker00000000000000000000000000000099"),
            candidate_id=request.candidate.candidate_id,
            serialized_digest=request.candidate.serialized_digest,
        ),
        request_id=request.request_id,
        nonce=request.nonce,
    )

    with patch(
        "ipfs_datasets_py.logic.zkp.eth_integration.Web3"
    ) as mock_web3:
        mock_instance = MagicMock()
        mock_instance.is_connected.return_value = True
        mock_instance.eth.chain_id = 1337
        mock_web3.return_value = mock_instance
        mock_web3.to_checksum_address = lambda a: a

        client = EthereumProofClient(ethereum_config)
        client.verifier_contract = MagicMock()

        with pytest.raises(EthTransactionGuardError):
            client.submit_proof_transaction(
                "0x" + "a" * 512,
                ["0x" + "b" * 64, "0x" + "c" * 64, "0x1", "0x" + "d" * 40],
                "0x" + "1" * 40,
                "0x" + "2" * 64,
                admissibility_capability=capability,
                live_request=mutated,
                guard_service=service,
                now=_NOW_OK,
            )
        # Original capability remains unconsumed after failed revalidation.
        assert service.is_consumed(capability) is False
