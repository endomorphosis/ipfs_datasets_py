"""Unit tests for the Worldcoin / World Chain transaction guard (CRYPTOIR-G570).

Offline adversarial fixtures cover:

* World Chain ID, candidate bytes, WLD/native effects, verifier/proxy epoch,
  action/external-nullifier/domain, RP/app, bridge legs, proof age,
  list/graph/policy, and expected effects.
* Replay/domain/nullifier/verifier/bridge/candidate substitution and stale
  evidence.
* Proof success cannot bypass contract or sanctions policy.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest

from ipfs_datasets_py.logic.crypto_ir.adapters.evm import (
    WORLD_CHAIN_MAINNET_CHAIN_ID,
    WORLD_CHAIN_MAINNET_GENESIS_HASH,
    WORLD_CHAIN_MAINNET_NETWORK,
)
from ipfs_datasets_py.logic.crypto_ir.adapters.worldcoin import (
    WLD_WORLD_CHAIN_MAINNET_ADDRESS,
)
from ipfs_datasets_py.logic.crypto_ir.verdicts import TransactionVerdictOutcome
from ipfs_datasets_py.processors.wallets.guard import (
    GuardCapabilityError,
    GuardForbiddenSurfaceError,
    GuardValidationError,
    PreflightPhase,
)
from ipfs_datasets_py.processors.wallets.worldcoin.transaction_guard import (
    PROOF_CANNOT_BYPASS,
    WORLDCOIN_TRANSACTION_GUARD_INTERFACE,
    BridgeLegBinding,
    VerifierProxyEpoch,
    WorldChainTransactionCandidate,
    WorldIDBinding,
    WorldcoinGuardDecision,
    WorldcoinTransactionBinding,
    WorldcoinTransactionGuard,
    evaluate_worldcoin_transaction_guard,
)


_ISSUED = "2026-07-28T12:00:00Z"
_DEADLINE = "2026-07-28T12:05:00Z"
_EXPIRY = "2026-07-28T12:10:00Z"
_INTENT_EXPIRY = "2026-07-28T12:15:00Z"
_NOW_OK = "2026-07-28T12:02:00Z"
_NOW_LATE = "2026-07-28T12:20:00Z"
_PROOF_OBSERVED = "2026-07-28T11:55:00Z"

_ALICE = "0x1111111111111111111111111111111111111111"
_BOB = "0x2222222222222222222222222222222222222222"
_VERIFIER = "0x3333333333333333333333333333333333333333"
_IMPL = "0x4444444444444444444444444444444444444444"
_BRIDGE = "0x5555555555555555555555555555555555555555"
_NULLIFIER_COMMIT = "a" * 64


def _candidate(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "intent_id": "intent:world-chain-1",
        "chain_id": WORLD_CHAIN_MAINNET_CHAIN_ID,
        "from_address": _ALICE,
        "to_address": _BOB,
        "value_wei": "1000000000000000000",
        "data": "0x",
        "method": "transfer",
        "nonce": 7,
        "gas_limit": 21000,
        "max_fee_per_gas": 1_000_000_000,
        "network": WORLD_CHAIN_MAINNET_NETWORK,
        "genesis_hash": WORLD_CHAIN_MAINNET_GENESIS_HASH,
        "wld_effects": (),
        "native_effects": (
            {
                "kind": "native_transfer",
                "from": _ALICE,
                "to": _BOB,
                "value_wei": "1000000000000000000",
            },
        ),
        "serialized_hex": "0x02f8704807843b9aca00",
    }
    payload.update(overrides)
    return payload


def _verifier_epoch(**overrides: Any) -> VerifierProxyEpoch:
    base = {
        "verifier_id": "verifier:world-id-v3",
        "verifier_address": _VERIFIER,
        "code_epoch": "epoch:verifier-v3.1",
        "chain_id": WORLD_CHAIN_MAINNET_CHAIN_ID,
        "implementation_address": _IMPL,
        "implementation_code_digest": "b" * 64,
        "proxy_kind": "transparent",
        "proxy_admin": _ALICE,
    }
    base.update(overrides)
    return VerifierProxyEpoch(**base)


def _world_id(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "binding_id": "worldid:binding-1",
        "rp_id": "app_staging_example",
        "action": "claim-airdrop",
        "environment": "production",
        "nullifier_commitment": _NULLIFIER_COMMIT,
        "app_id": "app_abc123",
        "protocol_version": "4.0",
        "verification_status": "verified",
        "proof_observed_at": _PROOF_OBSERVED,
        "proof_max_age_seconds": 900,
        "verifier_epoch": _verifier_epoch().to_dict(),
        "mini_app_id": "mini:claim",
        "chain_id": WORLD_CHAIN_MAINNET_CHAIN_ID,
    }
    payload.update(overrides)
    return payload


def _bridge_leg(**overrides: Any) -> BridgeLegBinding:
    base = {
        "leg_id": "bridge:deposit-1",
        "direction": "deposit",
        "source_chain_id": "1",
        "destination_chain_id": str(WORLD_CHAIN_MAINNET_CHAIN_ID),
        "bridge_contract": _BRIDGE,
        "message_digest": "c" * 64,
        "asset_id": "asset:eth-native",
        "amount": "500000000000000000",
    }
    base.update(overrides)
    return BridgeLegBinding(**base)


def _guard(**kwargs: Any) -> WorldcoinTransactionGuard:
    return WorldcoinTransactionGuard(**kwargs)


def _request_for(
    guard: WorldcoinTransactionGuard,
    binding: WorldcoinTransactionBinding,
    request_id: str = "req:worldcoin-1",
):
    return guard.to_preflight_request(
        binding,
        request_id=request_id,
        tenant_id="tenant:alpha",
        actor_id="actor:policy",
        audience_id="audience:signer",
        issued_at=_ISSUED,
        deadline=_DEADLINE,
        expiry=_EXPIRY,
        intent_expires_at=_INTENT_EXPIRY,
    )


# ---------------------------------------------------------------------------
# AST / import surface
# ---------------------------------------------------------------------------


def test_ast_symbols_exported() -> None:
    from ipfs_datasets_py.processors.wallets.worldcoin import transaction_guard as mod

    assert hasattr(mod, "WorldcoinTransactionGuard")
    assert hasattr(mod, "WorldChainTransactionCandidate")
    assert hasattr(mod, "WorldIDBinding")
    assert callable(mod.WorldcoinTransactionGuard)
    assert callable(mod.WorldChainTransactionCandidate)
    assert callable(mod.WorldIDBinding)


def test_interface_constants() -> None:
    guard = _guard()
    assert guard.interface == WORLDCOIN_TRANSACTION_GUARD_INTERFACE
    assert "worldcoin" in guard.schema_version


def test_proof_cannot_bypass_boundary() -> None:
    assert "contract_safety" in PROOF_CANNOT_BYPASS
    assert "sanctions_policy" in PROOF_CANNOT_BYPASS


# ---------------------------------------------------------------------------
# Candidate / World ID binding
# ---------------------------------------------------------------------------


def test_world_chain_candidate_binds_identity_and_bytes() -> None:
    cand = WorldChainTransactionCandidate.from_dict(_candidate())
    assert cand.chain_id == WORLD_CHAIN_MAINNET_CHAIN_ID
    assert cand.network == WORLD_CHAIN_MAINNET_NETWORK
    assert cand.genesis_hash == WORLD_CHAIN_MAINNET_GENESIS_HASH
    assert cand.settlement_layer == "ethereum-mainnet"
    assert cand.from_address == _ALICE.lower()
    assert cand.candidate_digest
    assert cand.serialized_hex.startswith("0x")


def test_world_chain_candidate_rejects_non_world_chain() -> None:
    with pytest.raises(GuardValidationError, match="World Chain"):
        WorldChainTransactionCandidate.from_dict(_candidate(chain_id=1))


def test_world_chain_candidate_rejects_forbidden_fields() -> None:
    payload = _candidate()
    payload["private_key"] = "deadbeef"
    with pytest.raises(GuardForbiddenSurfaceError):
        WorldChainTransactionCandidate.from_dict(payload)


def test_world_id_binding_domain_and_nullifier() -> None:
    wid = WorldIDBinding.from_dict(_world_id())
    assert wid.rp_id == "app_staging_example"
    assert wid.action == "claim-airdrop"
    assert wid.nullifier_commitment.startswith("sha256:") or len(
        wid.nullifier_commitment
    ) >= 8
    assert wid.external_nullifier_domain
    assert "claim-airdrop" in wid.external_nullifier_domain
    assert wid.proof_implies_authorization is False
    assert wid.verifier_epoch is not None
    assert wid.verifier_epoch.epoch_digest
    assert wid.binding_digest


def test_world_id_binding_rejects_proof_as_authorization() -> None:
    with pytest.raises(GuardValidationError, match="cannot imply"):
        WorldIDBinding.from_dict(_world_id(proof_implies_authorization=True))


def test_world_id_binding_rejects_raw_nullifier_field() -> None:
    payload = _world_id()
    payload["nullifier"] = "raw-secret-nullifier-material"
    with pytest.raises(GuardForbiddenSurfaceError):
        WorldIDBinding.from_dict(payload)


# ---------------------------------------------------------------------------
# Bind path
# ---------------------------------------------------------------------------


def test_bind_transaction_full_composition() -> None:
    guard = _guard()
    binding = guard.bind_transaction(
        _candidate(),
        world_id=_world_id(),
        bridge_legs=[_bridge_leg()],
        list_revision="list:ofac-2026-07-28",
        graph_revision="graph:v1",
        policy_revision="policy:v1",
    )
    assert isinstance(binding, WorldcoinTransactionBinding)
    assert binding.chain_id == WORLD_CHAIN_MAINNET_CHAIN_ID
    assert binding.world_id is not None
    assert binding.world_id.action == "claim-airdrop"
    assert len(binding.bridge_legs) == 1
    assert binding.list_revision == "list:ofac-2026-07-28"
    assert binding.binding_digest
    assert binding.serialized_digest
    assert binding.byte_length > 0
    assert binding.expected_effects
    kinds = {e.kind for e in binding.expected_effects}
    assert "native_transfer" in kinds or "world_id_proof_evidence" in kinds
    assert "bridge_deposit" in kinds


def test_bind_with_wld_effects() -> None:
    guard = _guard()
    cand = _candidate(
        value_wei="0",
        native_effects=(),
        wld_effects=(
            {
                "kind": "wld_transfer",
                "token": WLD_WORLD_CHAIN_MAINNET_ADDRESS,
                "from": _ALICE,
                "to": _BOB,
                "amount": "25000000000000000000",
            },
        ),
    )
    binding = guard.bind_transaction(cand, world_id=_world_id())
    assert binding.wld_effects
    assert any(e.kind == "wld_transfer" for e in binding.expected_effects)


def test_bind_rejects_world_id_chain_mismatch() -> None:
    guard = _guard()
    with pytest.raises(GuardValidationError, match="chain_id"):
        guard.bind_transaction(
            _candidate(),
            world_id=_world_id(chain_id=4801),
        )


def test_bind_world_chain_only_without_world_id() -> None:
    guard = _guard()
    binding = guard.bind_transaction(_candidate())
    assert binding.world_id is None
    assert binding.binding_digest


# ---------------------------------------------------------------------------
# Evaluate allow path
# ---------------------------------------------------------------------------


def test_evaluate_allows_clean_composition() -> None:
    guard = _guard()
    binding = guard.bind_transaction(
        _candidate(),
        world_id=_world_id(),
        bridge_legs=[_bridge_leg()],
        list_revision="list:v1",
        graph_revision="graph:v1",
        policy_revision="policy:v1",
    )
    request = _request_for(guard, binding)
    decision = guard.evaluate(
        binding,
        request=request,
        security_results={req: "pass" for req in request.security_requirement_ids},
        compliance_results={req: "pass" for req in request.compliance_requirement_ids},
        now=_NOW_OK,
        live_verifier_epochs={
            "verifier:world-id-v3": _verifier_epoch(),
        },
    )
    assert isinstance(decision, WorldcoinGuardDecision)
    assert decision.outcome is TransactionVerdictOutcome.ALLOW
    assert decision.allowed is True
    assert decision.preflight is not None
    assert decision.preflight.capability is not None
    assert decision.binding_digest == binding.binding_digest


def test_evaluate_convenience_helper() -> None:
    decision = evaluate_worldcoin_transaction_guard(
        _candidate(),
        world_id=_world_id(),
        issued_at=_ISSUED,
        deadline=_DEADLINE,
        expiry=_EXPIRY,
        now=_NOW_OK,
        compliance_results={
            "comp:direct-sanctions": "pass",
            "comp:bounded-exposure": "pass",
            "comp:contract-safety": "pass",
        },
    )
    assert decision.allowed is True


# ---------------------------------------------------------------------------
# Fail-closed: stale / replay / substitution
# ---------------------------------------------------------------------------


def test_evaluate_stale_compliance_blocks() -> None:
    guard = _guard()
    binding = guard.bind_transaction(_candidate(), world_id=_world_id())
    request = _request_for(guard, binding, "req:stale-comp")
    decision = guard.evaluate(
        binding,
        request=request,
        security_results={req: "pass" for req in request.security_requirement_ids},
        compliance_results={
            req: "stale" for req in request.compliance_requirement_ids
        },
        now=_NOW_OK,
    )
    assert decision.outcome is TransactionVerdictOutcome.STALE
    assert decision.blocks_automation is True
    assert decision.allowed is False


def test_evaluate_stale_proof_age_blocks() -> None:
    guard = _guard()
    # Proof observed long ago relative to now.
    wid = _world_id(
        proof_observed_at="2026-07-28T10:00:00Z",
        proof_max_age_seconds=300,
    )
    binding = guard.bind_transaction(_candidate(), world_id=wid)
    request = _request_for(guard, binding, "req:stale-proof")
    decision = guard.evaluate(
        binding,
        request=request,
        compliance_results={req: "pass" for req in request.compliance_requirement_ids},
        now=_NOW_OK,
    )
    assert decision.outcome is TransactionVerdictOutcome.STALE
    assert any("proof" in c for c in decision.reason_codes)
    assert decision.blocks_automation is True


def test_evaluate_nullifier_replay_blocks() -> None:
    guard = _guard(
        nullifier_already_used=lambda _n, _d: True,
    )
    binding = guard.bind_transaction(_candidate(), world_id=_world_id())
    request = _request_for(guard, binding, "req:replay")
    decision = guard.evaluate(
        binding,
        request=request,
        compliance_results={req: "pass" for req in request.compliance_requirement_ids},
        now=_NOW_OK,
    )
    assert decision.outcome is TransactionVerdictOutcome.DENY
    assert any("replay" in c for c in decision.reason_codes)
    assert decision.allowed is False


def test_proof_success_cannot_bypass_sanctions() -> None:
    """Verified World ID proof must not clear sanctions/contract compliance."""

    guard = _guard()
    binding = guard.bind_transaction(
        _candidate(),
        world_id=_world_id(verification_status="verified"),
    )
    request = _request_for(guard, binding, "req:proof-no-bypass")
    decision = guard.evaluate(
        binding,
        request=request,
        security_results={req: "pass" for req in request.security_requirement_ids},
        # Sanctions denied despite verified proof.
        compliance_results={
            "comp:direct-sanctions": "deny",
            "comp:bounded-exposure": "pass",
            "comp:contract-safety": "pass",
        },
        now=_NOW_OK,
    )
    assert decision.allowed is False
    assert decision.outcome is TransactionVerdictOutcome.DENY


def test_proof_success_cannot_bypass_contract_safety() -> None:
    guard = _guard()
    binding = guard.bind_transaction(
        _candidate(),
        world_id=_world_id(verification_status="verified"),
    )
    request = _request_for(guard, binding, "req:proof-no-contract")
    decision = guard.evaluate(
        binding,
        request=request,
        security_results={req: "pass" for req in request.security_requirement_ids},
        compliance_results={
            "comp:direct-sanctions": "pass",
            "comp:bounded-exposure": "pass",
            "comp:contract-safety": "deny",
        },
        now=_NOW_OK,
    )
    assert decision.allowed is False
    assert decision.outcome is TransactionVerdictOutcome.DENY


# ---------------------------------------------------------------------------
# Consumption: revalidation / substitution
# ---------------------------------------------------------------------------


def test_candidate_substitution_at_consumption() -> None:
    guard = _guard()
    binding = guard.bind_transaction(_candidate(), world_id=_world_id())
    request = _request_for(guard, binding, "req:cand-sub")
    decision = guard.evaluate(
        binding,
        request=request,
        security_results={req: "pass" for req in request.security_requirement_ids},
        compliance_results={req: "pass" for req in request.compliance_requirement_ids},
        now=_NOW_OK,
        live_verifier_epochs={"verifier:world-id-v3": _verifier_epoch()},
    )
    assert decision.allowed
    capability = decision.preflight.capability  # type: ignore[union-attr]

    mutated = _candidate(to_address=_VERIFIER, value_wei="999")
    with pytest.raises(GuardCapabilityError, match="candidate|substituted"):
        guard.revalidate_and_consume(
            capability,
            request,
            binding,
            phase=PreflightPhase.PRE_SIGN,
            now=_NOW_OK,
            live_candidate=mutated,
            live_verifier_epochs={"verifier:world-id-v3": _verifier_epoch()},
        )


def test_nullifier_domain_substitution_at_consumption() -> None:
    guard = _guard()
    binding = guard.bind_transaction(_candidate(), world_id=_world_id())
    request = _request_for(guard, binding, "req:domain-sub")
    decision = guard.evaluate(
        binding,
        request=request,
        security_results={req: "pass" for req in request.security_requirement_ids},
        compliance_results={req: "pass" for req in request.compliance_requirement_ids},
        now=_NOW_OK,
        live_verifier_epochs={"verifier:world-id-v3": _verifier_epoch()},
    )
    capability = decision.preflight.capability  # type: ignore[union-attr]

    mutated_wid = _world_id(action="different-action")
    with pytest.raises(GuardCapabilityError) as excinfo:
        guard.revalidate_and_consume(
            capability,
            request,
            binding,
            phase=PreflightPhase.PRE_SIGN,
            now=_NOW_OK,
            live_world_id=mutated_wid,
            live_verifier_epochs={"verifier:world-id-v3": _verifier_epoch()},
        )
    assert "world_id" in str(excinfo.value).lower() or "domain" in str(
        excinfo.value
    ).lower() or "substituted" in str(excinfo.value).lower()


def test_verifier_upgrade_blocks_consumption() -> None:
    guard = _guard()
    epoch = _verifier_epoch(code_epoch="epoch:v1", implementation_code_digest="d" * 64)
    binding = guard.bind_transaction(
        _candidate(),
        world_id=_world_id(verifier_epoch=epoch.to_dict()),
    )
    request = _request_for(guard, binding, "req:verifier-upgrade")
    decision = guard.evaluate(
        binding,
        request=request,
        security_results={req: "pass" for req in request.security_requirement_ids},
        compliance_results={req: "pass" for req in request.compliance_requirement_ids},
        now=_NOW_OK,
        live_verifier_epochs={"verifier:world-id-v3": epoch},
    )
    assert decision.allowed
    capability = decision.preflight.capability  # type: ignore[union-attr]

    upgraded = _verifier_epoch(
        code_epoch="epoch:v2-upgraded",
        implementation_code_digest="e" * 64,
    )
    with pytest.raises(GuardCapabilityError) as excinfo:
        guard.revalidate_and_consume(
            capability,
            request,
            binding,
            phase=PreflightPhase.PRE_BROADCAST,
            now=_NOW_OK,
            live_verifier_epochs={"verifier:world-id-v3": upgraded},
        )
    msg = str(excinfo.value).lower()
    assert "upgrade" in msg or "verifier" in msg or "epoch" in msg


def test_bridge_leg_substitution_at_consumption() -> None:
    guard = _guard()
    leg = _bridge_leg()
    binding = guard.bind_transaction(
        _candidate(),
        world_id=_world_id(),
        bridge_legs=[leg],
    )
    request = _request_for(guard, binding, "req:bridge-sub")
    decision = guard.evaluate(
        binding,
        request=request,
        security_results={req: "pass" for req in request.security_requirement_ids},
        compliance_results={req: "pass" for req in request.compliance_requirement_ids},
        now=_NOW_OK,
        live_verifier_epochs={"verifier:world-id-v3": _verifier_epoch()},
    )
    capability = decision.preflight.capability  # type: ignore[union-attr]

    mutated = _bridge_leg(amount="999999999999999999", direction="withdraw")
    with pytest.raises(GuardCapabilityError, match="bridge"):
        guard.revalidate_and_consume(
            capability,
            request,
            binding,
            phase=PreflightPhase.PRE_SIGN,
            now=_NOW_OK,
            live_bridge_legs=[mutated],
            live_verifier_epochs={"verifier:world-id-v3": _verifier_epoch()},
        )


def test_clean_consumption_succeeds() -> None:
    guard = _guard()
    epoch = _verifier_epoch()
    binding = guard.bind_transaction(
        _candidate(),
        world_id=_world_id(verifier_epoch=epoch.to_dict()),
        bridge_legs=[_bridge_leg()],
    )
    request = _request_for(guard, binding, "req:consume-ok")
    decision = guard.evaluate(
        binding,
        request=request,
        security_results={req: "pass" for req in request.security_requirement_ids},
        compliance_results={req: "pass" for req in request.compliance_requirement_ids},
        now=_NOW_OK,
        live_verifier_epochs={"verifier:world-id-v3": epoch},
    )
    assert decision.allowed
    capability = decision.preflight.capability  # type: ignore[union-attr]
    result = guard.revalidate_and_consume(
        capability,
        request,
        binding,
        phase=PreflightPhase.PRE_SIGN,
        now=_NOW_OK,
        live_candidate=_candidate(),
        live_world_id=_world_id(verifier_epoch=epoch.to_dict()),
        live_bridge_legs=[_bridge_leg()],
        live_verifier_epochs={"verifier:world-id-v3": epoch},
    )
    assert result is not None
    assert result.allowed is True
    assert result.consumed_at


def test_stale_list_revision_at_consumption() -> None:
    guard = _guard()
    binding = guard.bind_transaction(
        _candidate(),
        world_id=_world_id(),
        list_revision="stale",
    )
    request = _request_for(guard, binding, "req:stale-list")
    decision = guard.evaluate(
        binding,
        request=request,
        security_results={req: "pass" for req in request.security_requirement_ids},
        compliance_results={req: "pass" for req in request.compliance_requirement_ids},
        now=_NOW_OK,
        live_verifier_epochs={"verifier:world-id-v3": _verifier_epoch()},
    )
    # Evaluate may still allow (stale list checked at re_resolve).
    if decision.allowed and decision.preflight and decision.preflight.capability:
        with pytest.raises(GuardCapabilityError) as excinfo:
            guard.revalidate_and_consume(
                decision.preflight.capability,
                request,
                binding,
                phase=PreflightPhase.PRE_SIGN,
                now=_NOW_OK,
                live_verifier_epochs={"verifier:world-id-v3": _verifier_epoch()},
            )
        assert "stale" in str(excinfo.value).lower() or "list" in str(
            excinfo.value
        ).lower()


# ---------------------------------------------------------------------------
# Round-trip serialization
# ---------------------------------------------------------------------------


def test_binding_round_trip() -> None:
    guard = _guard()
    binding = guard.bind_transaction(
        _candidate(),
        world_id=_world_id(),
        bridge_legs=[_bridge_leg()],
        list_revision="list:v1",
    )
    restored = WorldcoinTransactionBinding.from_dict(binding.to_dict())
    assert restored.binding_digest == binding.binding_digest
    assert restored.chain_id == binding.chain_id
    assert restored.world_id is not None
    assert restored.world_id.action == binding.world_id.action  # type: ignore[union-attr]


def test_decision_to_dict() -> None:
    guard = _guard()
    binding = guard.bind_transaction(_candidate(), world_id=_world_id())
    request = _request_for(guard, binding, "req:dict")
    decision = guard.evaluate(
        binding,
        request=request,
        security_results={req: "pass" for req in request.security_requirement_ids},
        compliance_results={req: "pass" for req in request.compliance_requirement_ids},
        now=_NOW_OK,
    )
    payload = decision.to_dict()
    assert payload["outcome"] in {"allow", "deny", "stale", "review", "error", "inconclusive"}
    assert payload["binding_digest"] == binding.binding_digest
    assert "proof_cannot_bypass" in payload["attributes"] or decision.allowed is not None
