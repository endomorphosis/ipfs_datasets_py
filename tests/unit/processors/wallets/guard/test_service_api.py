"""Unit tests for GuardService cutover API (CRYPTOIR-G600 / CRYPTOIR-034).

Evidence:

* ``ipfs_datasets_py/processors/wallets/guard/service.py``
* public service surface: GuardService, sign_transaction, send_raw_transaction,
  broadcast
* no approved=true escape hatch; capability consumption required
* read-only preflight remains usable without custody authority
"""

from __future__ import annotations

from typing import Any

import pytest

from ipfs_datasets_py.logic.crypto_ir.verdicts import TransactionVerdictOutcome
from ipfs_datasets_py.processors.wallets.api import WalletProcessorAPI
from ipfs_datasets_py.processors.wallets.errors import UnsupportedCapabilityError
from ipfs_datasets_py.processors.wallets.guard import (
    AdmissibilityCapability,
    AssetAmount,
    ExpectedEffect,
    FeeSpec,
    GuardCapabilityError,
    GuardConsumptionRaceError,
    GuardForbiddenSurfaceError,
    GuardService,
    GuardValidationError,
    PreflightPhase,
    TransactionCandidate,
    TransactionIntent,
    TransactionPreflightRequest,
    broadcast,
    send_raw_transaction,
    sign_transaction,
)
from ipfs_datasets_py.processors.wallets.guard.service import (
    GUARD_SERVICE_INTERFACE,
    KNOWN_SIGNING_PATHS,
    reset_default_guard_service,
)
from ipfs_datasets_py.processors.wallets.registry import (
    WalletProcessorRegistry,
    WalletRegistry,
    default_registry,
    reset_default_registry,
)
from ipfs_datasets_py.processors.smart_contracts.api import (
    SmartContractProcessorAPI,
)
from ipfs_datasets_py.processors.smart_contracts.errors import SigningForbiddenError


# ---------------------------------------------------------------------------
# Fixtures (shared digests / timestamps with preflight tests)
# ---------------------------------------------------------------------------

_DIGEST_A = "a" * 64
_DIGEST_ENV = "e" * 64
_ISSUED = "2026-07-28T12:00:00Z"
_DEADLINE = "2026-07-28T12:05:00Z"
_EXPIRY = "2026-07-28T12:10:00Z"
_INTENT_EXPIRY = "2026-07-28T12:15:00Z"
_NOW_OK = "2026-07-28T12:02:00Z"


def _intent(**overrides: Any) -> TransactionIntent:
    base: dict[str, Any] = {
        "intent_id": "intent:transfer-001",
        "network": "ethereum:mainnet",
        "sender": "0xSender0000000000000000000000000000000001",
        "destination": "0xDest000000000000000000000000000000000002",
        "method": "transfer(address,uint256)",
        "assets": (
            AssetAmount(
                asset_id="asset:eth-native",
                amount="1000000000000000000",
                asset_namespace="native",
                symbol="ETH",
            ),
        ),
        "fees": (FeeSpec(amount="21000000000000", asset_id="asset:eth-native"),),
        "nonce_or_sequence": "42",
        "signers": ("signer:0xSender0000000000000000000000000000000001",),
        "expected_effects": (
            ExpectedEffect(
                effect_id="effect:transfer-eth",
                kind="transfer",
                summary="send 1 ETH",
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
        "candidate_id": "candidate:tx-001",
        "intent_id": intent.intent_id,
        "serialized_digest": _DIGEST_A,
        "encoding": "rlp",
        "byte_length": 128,
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
        "request_id": "req:preflight-001",
        "intent": intent,
        "candidate": candidate,
        "tenant_id": "tenant:alpha",
        "actor_id": "actor:policy-engine",
        "audience_id": "audience:custody-signer",
        "policy_id": "policy:wallet-guard-v1",
        "security_requirement_ids": ("sec:no-self-destruct",),
        "compliance_requirement_ids": ("comp:direct-sanctions",),
        "issued_at": _ISSUED,
        "deadline": _DEADLINE,
        "expiry": _EXPIRY,
        "environment_id": "env:prod",
        "environment_digest": _DIGEST_ENV,
        "nonce": "nonce-preflight-001",
    }
    base.update(overrides)
    return TransactionPreflightRequest(**base)


def _pass_results(request: TransactionPreflightRequest) -> tuple[dict, dict]:
    security = {req: "pass" for req in request.security_requirement_ids}
    compliance = {req: "pass" for req in request.compliance_requirement_ids}
    return security, compliance


def _allow(
    service: GuardService | None = None,
    request: TransactionPreflightRequest | None = None,
) -> tuple[GuardService, TransactionPreflightRequest, AdmissibilityCapability]:
    service = service or GuardService()
    request = request or _request()
    security, compliance = _pass_results(request)
    result = service.evaluate_preflight(
        request,
        security_results=security,
        compliance_results=compliance,
        now=_NOW_OK,
    )
    assert result.outcome is TransactionVerdictOutcome.ALLOW
    assert result.capability is not None
    return service, request, result.capability


@pytest.fixture(autouse=True)
def _reset_singletons() -> None:
    reset_default_guard_service()
    reset_default_registry()
    yield
    reset_default_guard_service()
    reset_default_registry()


# ---------------------------------------------------------------------------
# Service discovery / inventory
# ---------------------------------------------------------------------------


def test_guard_service_ast_symbols_exported() -> None:
    import ipfs_datasets_py.processors.wallets.guard as guard

    assert guard.GuardService is GuardService
    assert callable(guard.sign_transaction)
    assert callable(guard.send_raw_transaction)
    assert callable(guard.broadcast)
    assert guard.GUARD_SERVICE_INTERFACE == GUARD_SERVICE_INTERFACE


def test_capabilities_are_read_only_without_key_storage() -> None:
    service = GuardService()
    caps = service.capabilities()
    assert caps["supports_preflight"] is True
    assert caps["supports_capability_consumption"] is True
    assert caps["requires_consumed_capability"] is True
    assert caps["approved_escape_hatch"] is False
    assert caps["stores_keys"] is False
    assert caps["read_only_lookup"] is True
    assert caps["supports_sign"] is True  # gated, not unguarded


def test_signing_inventory_covers_eth_integration_and_apis() -> None:
    inventory = GuardService().inventory_signing_paths()
    path_ids = {p["path_id"] for p in inventory.paths}
    assert "guard.service.sign_transaction" in path_ids
    assert "guard.service.send_raw_transaction" in path_ids
    assert "guard.service.broadcast" in path_ids
    assert "zkp.eth_integration.submit_proof_transaction" in path_ids
    assert "wallets.api.sign_verbs" in path_ids
    assert "smart_contracts.api" in path_ids
    assert len(KNOWN_SIGNING_PATHS) == len(inventory.paths)
    payload = inventory.to_dict()
    assert payload["path_count"] == len(KNOWN_SIGNING_PATHS)


# ---------------------------------------------------------------------------
# Preflight (read-only)
# ---------------------------------------------------------------------------


def test_evaluate_preflight_allow_issues_capability() -> None:
    service, request, capability = _allow()
    assert isinstance(capability, AdmissibilityCapability)
    assert capability.request_digest == request.request_digest
    assert service.is_consumed(capability) is False


def test_evaluate_preflight_rejects_approved_escape() -> None:
    service = GuardService()
    with pytest.raises(GuardForbiddenSurfaceError, match="approved"):
        service.evaluate_preflight(
            _request(),
            options={"approved": True},
            now=_NOW_OK,
        )


def test_evaluate_preflight_rejects_boolean_override() -> None:
    service = GuardService()
    request = _request()
    security, compliance = _pass_results(request)
    with pytest.raises(GuardForbiddenSurfaceError):
        service.evaluate_preflight(
            request,
            security_results=security,
            compliance_results=compliance,
            outcome_override=True,  # type: ignore[arg-type]
            now=_NOW_OK,
        )


def test_deny_blocks_and_issues_no_capability() -> None:
    service = GuardService()
    request = _request()
    result = service.evaluate_preflight(
        request,
        security_results={"sec:no-self-destruct": "deny"},
        compliance_results={"comp:direct-sanctions": "pass"},
        now=_NOW_OK,
    )
    assert result.outcome is TransactionVerdictOutcome.DENY
    assert result.blocks_automation is True
    assert result.capability is None


# ---------------------------------------------------------------------------
# sign_transaction / send_raw_transaction / broadcast
# ---------------------------------------------------------------------------


def test_sign_transaction_requires_capability() -> None:
    service = GuardService()
    with pytest.raises(GuardCapabilityError, match="disabled without"):
        service.sign_transaction()


def test_sign_transaction_rejects_approved_true() -> None:
    service, request, capability = _allow()
    with pytest.raises(GuardForbiddenSurfaceError, match="approved"):
        service.sign_transaction(
            capability=capability,
            live_request=request,
            approved=True,
            now=_NOW_OK,
        )


def test_sign_transaction_rejects_private_key_kwarg() -> None:
    service, request, capability = _allow()
    with pytest.raises(GuardForbiddenSurfaceError, match="private_key"):
        service.sign_transaction(
            capability=capability,
            live_request=request,
            private_key="0xdead",
            now=_NOW_OK,
        )


def test_sign_transaction_consumes_capability_and_invokes_external_signer() -> None:
    service, request, capability = _allow()
    seen: dict[str, Any] = {}

    def external_signer(unsigned: Any, auth: Any) -> bytes:
        seen["unsigned"] = unsigned
        seen["allowed"] = auth.allowed
        seen["capability_id"] = auth.capability_id
        return b"signed-bytes"

    auth = service.sign_transaction(
        capability=capability,
        live_request=request,
        unsigned_candidate={"rlp": "0x01"},
        external_signer=external_signer,
        now=_NOW_OK,
    )
    assert auth.allowed is True
    assert auth.phase == PreflightPhase.PRE_SIGN.value
    assert auth.signed_payload == b"signed-bytes"
    assert seen["allowed"] is True
    assert seen["capability_id"] == capability.capability_id
    assert service.is_consumed(capability) is True
    # Replay fails closed.
    with pytest.raises(GuardConsumptionRaceError):
        service.sign_transaction(
            capability=capability,
            live_request=request,
            now=_NOW_OK,
        )


def test_send_raw_transaction_and_broadcast_require_consumption() -> None:
    service = GuardService()
    request = _request(request_id="req:broadcast-001", nonce="nonce-broadcast-001")
    # Fresh capability for pre-broadcast path.
    service_a, _, capability = _allow(service=service, request=request)

    receipts: list[Any] = []

    def broadcaster(raw: Any, auth: Any) -> str:
        receipts.append((raw, auth.capability_id))
        return "0x" + "ab" * 32

    result = service_a.send_raw_transaction(
        capability=capability,
        live_request=request,
        raw_transaction=b"\x01\x02",
        external_broadcaster=broadcaster,
        now=_NOW_OK,
    )
    assert result.allowed is True
    assert result.phase == PreflightPhase.PRE_BROADCAST.value
    assert result.broadcast_receipt.startswith("0x")
    assert receipts and receipts[0][0] == b"\x01\x02"

    # broadcast() is an alias and needs a new capability.
    request2 = _request(request_id="req:broadcast-002", nonce="nonce-broadcast-002")
    _, _, capability2 = _allow(service=service, request=request2)
    alias = service.broadcast(
        capability=capability2,
        live_request=request2,
        raw_transaction=b"\x03",
        now=_NOW_OK,
    )
    assert alias.allowed is True
    assert alias.phase == PreflightPhase.PRE_BROADCAST.value


def test_module_level_sign_transaction_disabled_without_capability() -> None:
    reset_default_guard_service()
    with pytest.raises(GuardCapabilityError):
        sign_transaction()
    with pytest.raises(GuardCapabilityError):
        send_raw_transaction()
    with pytest.raises(GuardForbiddenSurfaceError, match="approved"):
        broadcast(approved=True)
    with pytest.raises(GuardCapabilityError):
        broadcast()


def test_signing_master_disable() -> None:
    service = GuardService(signing_enabled=False)
    request = _request()
    security, compliance = _pass_results(request)
    # Read-only preflight still works.
    result = service.evaluate_preflight(
        request,
        security_results=security,
        compliance_results=compliance,
        now=_NOW_OK,
    )
    assert result.capability is not None
    with pytest.raises(GuardCapabilityError, match="signing_enabled"):
        service.sign_transaction(
            capability=result.capability,
            live_request=request,
            now=_NOW_OK,
        )


def test_candidate_substitution_fails_at_sign() -> None:
    service, request, capability = _allow()
    mutated_candidate = _candidate(
        request.intent,
        serialized_digest="c" * 64,
        candidate_id=request.candidate.candidate_id,
    )
    mutated = _request(
        intent=request.intent,
        candidate=mutated_candidate,
        request_id=request.request_id,
        nonce=request.nonce,
    )
    with pytest.raises(GuardCapabilityError, match="does not match"):
        service.sign_transaction(
            capability=capability,
            live_request=mutated,
            now=_NOW_OK,
        )


# ---------------------------------------------------------------------------
# Wallet API / registry cutover alignment
# ---------------------------------------------------------------------------


def test_wallet_api_rejects_sign_and_approved_options() -> None:
    api = WalletProcessorAPI()
    with pytest.raises(UnsupportedCapabilityError):
        api.sign_transaction  # type: ignore[attr-defined]
    with pytest.raises(UnsupportedCapabilityError):
        api.broadcast  # type: ignore[attr-defined]
    with pytest.raises(UnsupportedCapabilityError):
        api.send_raw_transaction  # type: ignore[attr-defined]
    # Read-only capabilities remain available.
    caps = api.list_families().to_dict()
    assert caps["supports_sign"] is False
    assert caps["supports_broadcast"] is False
    # Guard service is reachable without custody authority.
    guard = api.guard_service()
    assert isinstance(guard, GuardService)


def test_wallet_registry_alias_and_no_signing() -> None:
    assert WalletRegistry is WalletProcessorRegistry
    registry = default_registry()
    assert registry.asserts_no_signing_authority() is True
    guards = registry.list_transaction_guards()
    assert "ethereum" in guards
    assert "BitcoinTransactionGuard" in guards["bitcoin"]["symbol"]
    for family in registry.list_families():
        meta = dict(registry.get_spec(family).metadata)
        assert meta.get("supports_sign") is not True
        assert meta.get("supports_broadcast") is not True


def test_smart_contract_api_is_read_only() -> None:
    api = SmartContractProcessorAPI()
    caps = api.capabilities()
    assert caps.supports_sign is False
    assert caps.supports_broadcast is False
    with pytest.raises(SigningForbiddenError):
        api.sign_transaction  # type: ignore[attr-defined]
    with pytest.raises(SigningForbiddenError):
        api.broadcast  # type: ignore[attr-defined]
    with pytest.raises(SigningForbiddenError):
        _ = api.acquire(
            {"request_id": "x", "approved": True}  # type: ignore[arg-type]
        )
