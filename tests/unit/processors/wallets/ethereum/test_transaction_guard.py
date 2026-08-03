"""Unit tests for the Ethereum transaction guard (CRYPTOIR-G530 / CRYPTOIR-030).

Offline adversarial fixtures cover:

* Chain ID, nonce, fee, calldata, value, approvals, internal/token effects,
  code/proxy epoch, sender recovery, exact serialized candidate.
* Permit substitution, nonce/fee mutation, proxy upgrade, hidden transfer,
  stale list/graph, and replay.
* Guarding by decoded and simulated effects, not method name alone.
"""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from ipfs_datasets_py.logic.crypto_ir.adapters.evm import (
    ETHEREUM_MAINNET_CHAIN_ID,
    ETHEREUM_MAINNET_GENESIS_HASH,
    ETHEREUM_MAINNET_NETWORK,
)
from ipfs_datasets_py.logic.crypto_ir.verdicts import TransactionVerdictOutcome
from ipfs_datasets_py.processors.wallets.guard import (
    GuardCapabilityError,
    GuardForbiddenSurfaceError,
    GuardValidationError,
    PreflightPhase,
)
from ipfs_datasets_py.processors.wallets.ethereum.transaction_guard import (
    ETHEREUM_TRANSACTION_GUARD_INTERFACE,
    SELECTOR_APPROVE,
    SELECTOR_PERMIT,
    SELECTOR_TRANSFER,
    ApprovalBinding,
    CodeProxyEpoch,
    EVMTransactionBinding,
    EVMTransactionCandidate,
    EthereumGuardDecision,
    EthereumTransactionGuard,
    content_sha256_hex,
    decode_calldata_effects,
    evaluate_ethereum_transaction_guard,
    method_selector,
)


FIXTURE_PATH = (
    Path(__file__).resolve().parents[4]
    / "fixtures"
    / "wallets"
    / "ethereum"
    / "rpc_session.json"
)

_ISSUED = "2026-07-28T12:00:00Z"
_DEADLINE = "2026-07-28T12:05:00Z"
_EXPIRY = "2026-07-28T12:10:00Z"
_INTENT_EXPIRY = "2026-07-28T12:15:00Z"
_NOW_OK = "2026-07-28T12:02:00Z"


@pytest.fixture(scope="module")
def rpc_session() -> dict[str, Any]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _addrs(rpc: dict[str, Any]) -> dict[str, str]:
    return rpc["addresses"]


def _pad_addr(address: str) -> str:
    return address.lower().removeprefix("0x").rjust(64, "0")


def _pad_uint(value: int) -> str:
    return f"{value:064x}"


def _approve_data(spender: str, amount: int = 1000) -> str:
    return SELECTOR_APPROVE + _pad_addr(spender) + _pad_uint(amount)


def _transfer_data(to: str, amount: int = 1000) -> str:
    return SELECTOR_TRANSFER + _pad_addr(to) + _pad_uint(amount)


def _permit_data(
    owner: str, spender: str, amount: int = 500, deadline: int = 9_999_999_999
) -> str:
    # permit(owner, spender, value, deadline, v, r, s) — pad dummy sig words.
    return (
        SELECTOR_PERMIT
        + _pad_addr(owner)
        + _pad_addr(spender)
        + _pad_uint(amount)
        + _pad_uint(deadline)
        + _pad_uint(27)  # v
        + ("ab" * 32)  # r
        + ("cd" * 32)  # s
    )


def _candidate(rpc: dict[str, Any], **overrides: Any) -> dict[str, Any]:
    addrs = _addrs(rpc)
    payload: dict[str, Any] = {
        "intent_id": "intent:ethereum-1",
        "chain_id": ETHEREUM_MAINNET_CHAIN_ID,
        "from_address": addrs["alice"],
        "to_address": addrs["bob"],
        "value_wei": "1000000000000000000",
        "data": "0x",
        "method": "",
        "nonce": 7,
        "gas_limit": 21000,
        "max_fee_per_gas": 1_000_000_000,
        "network": ETHEREUM_MAINNET_NETWORK,
        "genesis_hash": ETHEREUM_MAINNET_GENESIS_HASH,
        "list_revision": "list:ofac-2026-07-28",
        "graph_revision": "graph:exposure-v1",
        "serialized_hex": "0x02f87001843b9aca00",
        "recovered_sender": addrs["alice"],
        "sender_recovery_digest": "a" * 64,
    }
    payload.update(overrides)
    return payload


def _code_epoch(rpc: dict[str, Any], address: str | None = None, **overrides: Any) -> CodeProxyEpoch:
    addrs = _addrs(rpc)
    base = {
        "contract_address": address or addrs["erc20"],
        "code_epoch": "epoch:erc20-v1",
        "chain_id": ETHEREUM_MAINNET_CHAIN_ID,
        "code_hash": "0x" + "11" * 32,
        "implementation_address": addrs["operator"],
        "implementation_code_digest": "b" * 64,
        "proxy_kind": "transparent",
        "proxy_admin": addrs["alice"],
        "network": ETHEREUM_MAINNET_NETWORK,
    }
    base.update(overrides)
    return CodeProxyEpoch(**base)


def _guard(**kwargs: Any) -> EthereumTransactionGuard:
    return EthereumTransactionGuard(**kwargs)


def _request_for(
    guard: EthereumTransactionGuard,
    binding: EVMTransactionBinding,
    request_id: str = "req:eth-1",
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


def _allow(
    guard: EthereumTransactionGuard,
    binding: EVMTransactionBinding,
    *,
    request_id: str = "req:eth-1",
    live_epochs: dict[str, CodeProxyEpoch] | None = None,
) -> EthereumGuardDecision:
    request = _request_for(guard, binding, request_id=request_id)
    return guard.evaluate(
        binding,
        request=request,
        security_results={req: "pass" for req in request.security_requirement_ids},
        compliance_results={req: "pass" for req in request.compliance_requirement_ids},
        now=_NOW_OK,
        live_code_proxy_epochs=live_epochs,
    )


# ---------------------------------------------------------------------------
# AST / import surface
# ---------------------------------------------------------------------------


def test_ast_symbols_exported() -> None:
    from ipfs_datasets_py.processors.wallets.ethereum import transaction_guard as mod

    assert hasattr(mod, "EthereumTransactionGuard")
    assert hasattr(mod, "EVMTransactionCandidate")
    assert callable(mod.EthereumTransactionGuard)
    assert callable(mod.EVMTransactionCandidate)


def test_interface_constants() -> None:
    guard = _guard()
    assert guard.interface == ETHEREUM_TRANSACTION_GUARD_INTERFACE
    assert "ethereum" in guard.schema_version


def test_no_signing_or_broadcast_surface() -> None:
    from ipfs_datasets_py.processors.wallets.ethereum import transaction_guard as mod

    forbidden = {
        "sign",
        "sign_transaction",
        "broadcast",
        "send_transaction",
        "private_key",
    }
    public = {name for name in dir(mod) if not name.startswith("_")}
    assert not (public & forbidden)
    methods = {
        name for name in dir(EthereumTransactionGuard) if not name.startswith("_")
    }
    assert not (methods & forbidden)


# ---------------------------------------------------------------------------
# Calldata decoding (effects, not method names)
# ---------------------------------------------------------------------------


def test_method_selector_and_approve_decode(rpc_session: dict[str, Any]) -> None:
    addrs = _addrs(rpc_session)
    data = _approve_data(addrs["bob"], 42)
    assert method_selector(data) == SELECTOR_APPROVE
    decoded = decode_calldata_effects(
        to_address=addrs["erc20"],
        data=data,
        from_address=addrs["alice"],
    )
    assert decoded["decoded_kind"] == "approve"
    assert decoded["approvals"]
    assert decoded["approvals"][0]["spender"] == addrs["bob"].lower()
    assert decoded["approvals"][0]["amount"] == "42"
    assert decoded["approvals"][0]["token"] == addrs["erc20"].lower()


def test_permit_decode(rpc_session: dict[str, Any]) -> None:
    addrs = _addrs(rpc_session)
    data = _permit_data(addrs["alice"], addrs["operator"], amount=99)
    decoded = decode_calldata_effects(
        to_address=addrs["erc20"],
        data=data,
        from_address=addrs["alice"],
    )
    assert decoded["decoded_kind"] == "permit"
    assert decoded["approvals"][0]["kind"] == "permit"
    assert decoded["approvals"][0]["amount"] == "99"
    assert decoded["approvals"][0]["spender"] == addrs["operator"].lower()


def test_transfer_decode(rpc_session: dict[str, Any]) -> None:
    addrs = _addrs(rpc_session)
    data = _transfer_data(addrs["bob"], 1000)
    decoded = decode_calldata_effects(
        to_address=addrs["erc20"],
        data=data,
        from_address=addrs["alice"],
    )
    assert decoded["decoded_kind"] == "transfer"
    assert decoded["token_effects"][0]["amount"] == "1000"
    assert decoded["token_effects"][0]["to"] == addrs["bob"].lower()


def test_unknown_selector_not_authorized_by_method_name(
    rpc_session: dict[str, Any],
) -> None:
    addrs = _addrs(rpc_session)
    # Unknown 4-byte selector with a friendly method label.
    data = "0xdeadbeef" + _pad_addr(addrs["bob"]) + _pad_uint(1)
    payload = _candidate(
        rpc_session,
        to_address=addrs["erc20"],
        data=data,
        method="safeTransfer",  # lies about the selector
        value_wei="0",
    )
    guard = _guard()
    with pytest.raises(GuardValidationError, match="method name|decoded"):
        guard.bind_transaction(payload, code_proxy_epochs=[_code_epoch(rpc_session)])


# ---------------------------------------------------------------------------
# Binding
# ---------------------------------------------------------------------------


def test_bind_native_transfer_binds_all_fields(rpc_session: dict[str, Any]) -> None:
    guard = _guard()
    cand = EVMTransactionCandidate.from_dict(_candidate(rpc_session))
    binding = guard.bind_transaction(cand)

    assert isinstance(binding, EVMTransactionBinding)
    assert binding.chain_id == ETHEREUM_MAINNET_CHAIN_ID
    assert binding.network == ETHEREUM_MAINNET_NETWORK
    assert binding.nonce == 7
    assert binding.value_wei == "1000000000000000000"
    assert binding.from_address == _addrs(rpc_session)["alice"].lower()
    assert binding.native_effects
    assert binding.fee_wei  # derived from gas * maxFee
    assert binding.serialized_digest
    assert binding.candidate_digest
    assert binding.binding_digest
    assert binding.byte_length > 0
    assert binding.recovered_sender == _addrs(rpc_session)["alice"].lower()
    assert binding.list_revision == "list:ofac-2026-07-28"
    assert binding.graph_revision == "graph:exposure-v1"


def test_bind_approve_binds_approval_effects(rpc_session: dict[str, Any]) -> None:
    addrs = _addrs(rpc_session)
    guard = _guard()
    epoch = _code_epoch(rpc_session, addrs["erc20"])
    payload = _candidate(
        rpc_session,
        to_address=addrs["erc20"],
        data=_approve_data(addrs["operator"], 1_000_000),
        value_wei="0",
        method="approve",
        gas_limit=60_000,
    )
    binding = guard.bind_transaction(payload, code_proxy_epochs=[epoch])
    assert binding.decoded_kind == "approve"
    assert binding.selector == SELECTOR_APPROVE
    assert len(binding.approvals) == 1
    assert binding.approvals[0].spender == addrs["operator"].lower()
    assert binding.approvals[0].amount == "1000000"
    assert binding.code_proxy_epochs
    assert binding.code_proxy_epochs[0].contract_address == addrs["erc20"].lower()


def test_bind_rejects_forbidden_custody_fields(rpc_session: dict[str, Any]) -> None:
    guard = _guard()
    payload = _candidate(rpc_session)
    payload["private_key"] = "deadbeef"
    with pytest.raises(GuardForbiddenSurfaceError):
        guard.bind_transaction(payload)


def test_bind_rejects_wrong_genesis(rpc_session: dict[str, Any]) -> None:
    guard = _guard()
    payload = _candidate(rpc_session, genesis_hash="0x" + "00" * 32)
    with pytest.raises(GuardValidationError):
        guard.bind_transaction(payload)


def test_bind_requires_code_epoch_when_supplied(
    rpc_session: dict[str, Any],
) -> None:
    addrs = _addrs(rpc_session)
    guard = _guard()
    payload = _candidate(
        rpc_session,
        to_address=addrs["erc20"],
        data=_transfer_data(addrs["bob"]),
        value_wei="0",
        method="transfer",
    )
    with pytest.raises(GuardValidationError, match="code/proxy epoch"):
        guard.bind_transaction(payload, code_proxy_epochs=[])


def test_binding_round_trip(rpc_session: dict[str, Any]) -> None:
    guard = _guard()
    binding = guard.bind_transaction(_candidate(rpc_session))
    restored = EVMTransactionBinding.from_dict(binding.to_dict())
    assert restored.binding_digest == binding.binding_digest
    assert restored.chain_id == binding.chain_id
    assert restored.nonce == binding.nonce


# ---------------------------------------------------------------------------
# Evaluate allow path
# ---------------------------------------------------------------------------


def test_evaluate_allows_clean_native(rpc_session: dict[str, Any]) -> None:
    guard = _guard()
    binding = guard.bind_transaction(_candidate(rpc_session))
    decision = _allow(guard, binding)
    assert isinstance(decision, EthereumGuardDecision)
    assert decision.outcome is TransactionVerdictOutcome.ALLOW
    assert decision.allowed is True
    assert decision.preflight is not None
    assert decision.preflight.capability is not None
    assert decision.binding_digest == binding.binding_digest


def test_evaluate_stale_compliance_blocks(rpc_session: dict[str, Any]) -> None:
    guard = _guard()
    binding = guard.bind_transaction(_candidate(rpc_session))
    request = _request_for(guard, binding, request_id="req:eth-stale-comp")
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


def test_evaluate_stale_list_revision_blocks(rpc_session: dict[str, Any]) -> None:
    guard = _guard(list_revision_is_current=lambda _rev, _now: False)
    binding = guard.bind_transaction(_candidate(rpc_session))
    decision = _allow(guard, binding)
    assert decision.outcome is TransactionVerdictOutcome.STALE
    assert any("list_revision" in c for c in decision.reason_codes)


def test_evaluate_stale_graph_revision_blocks(rpc_session: dict[str, Any]) -> None:
    guard = _guard(graph_revision_is_current=lambda _rev, _now: False)
    binding = guard.bind_transaction(_candidate(rpc_session))
    decision = _allow(guard, binding)
    assert decision.outcome is TransactionVerdictOutcome.STALE
    assert any("graph_revision" in c for c in decision.reason_codes)


def test_evaluate_nonce_replay_blocks(rpc_session: dict[str, Any]) -> None:
    guard = _guard(nonce_already_used=lambda _n, _f, _c: True)
    binding = guard.bind_transaction(_candidate(rpc_session))
    decision = _allow(guard, binding)
    assert decision.allowed is False
    assert any("replay" in c for c in decision.reason_codes)


def test_evaluate_sender_recovery_mismatch_blocks(
    rpc_session: dict[str, Any],
) -> None:
    addrs = _addrs(rpc_session)
    guard = _guard()
    payload = _candidate(rpc_session, recovered_sender=addrs["bob"])
    binding = guard.bind_transaction(payload)
    decision = _allow(guard, binding)
    assert decision.allowed is False
    assert any("sender_recovery" in c for c in decision.reason_codes)


def test_evaluate_convenience_function(rpc_session: dict[str, Any]) -> None:
    decision = evaluate_ethereum_transaction_guard(
        _candidate(rpc_session),
        request_id="req:eth-conv",
        tenant_id="tenant:alpha",
        actor_id="actor:policy",
        audience_id="audience:signer",
        issued_at=_ISSUED,
        deadline=_DEADLINE,
        expiry=_EXPIRY,
        now=_NOW_OK,
        security_results={req: "pass" for req in (
            "sec:evm-chain-identity",
            "sec:evm-nonce-fee",
            "sec:evm-calldata-effects",
            "sec:evm-approvals",
            "sec:evm-internal-token-effects",
            "sec:evm-code-proxy-epoch",
            "sec:evm-sender-recovery",
            "sec:evm-exact-candidate",
            "sec:evm-list-graph-freshness",
        )},
        compliance_results={
            "comp:direct-sanctions": "pass",
            "comp:bounded-exposure": "pass",
            "comp:contract-safety": "pass",
        },
    )
    assert decision.allowed is True


# ---------------------------------------------------------------------------
# Adversarial: permit substitution / nonce-fee / proxy / hidden / stale
# ---------------------------------------------------------------------------


def test_permit_substitution_at_consumption(rpc_session: dict[str, Any]) -> None:
    addrs = _addrs(rpc_session)
    guard = _guard()
    epoch = _code_epoch(rpc_session, addrs["erc20"])
    payload = _candidate(
        rpc_session,
        to_address=addrs["erc20"],
        data=_permit_data(addrs["alice"], addrs["operator"], amount=100),
        value_wei="0",
        method="permit",
        gas_limit=100_000,
    )
    binding = guard.bind_transaction(payload, code_proxy_epochs=[epoch])
    decision = _allow(
        guard,
        binding,
        request_id="req:eth-permit",
        live_epochs={addrs["erc20"].lower(): epoch},
    )
    assert decision.allowed
    capability = decision.preflight.capability  # type: ignore[union-attr]
    request = _request_for(guard, binding, request_id="req:eth-permit")

    # Substitute spender / amount via a different permit.
    substituted = [
        ApprovalBinding(
            token=addrs["erc20"],
            owner=addrs["alice"],
            spender=addrs["bob"],  # swapped spender
            amount="999999999",
            kind="permit",
            selector=SELECTOR_PERMIT,
        )
    ]
    with pytest.raises(GuardCapabilityError) as excinfo:
        guard.revalidate_and_consume(
            capability,
            request,
            binding,
            phase=PreflightPhase.PRE_SIGN,
            now=_NOW_OK,
            live_code_proxy_epochs={addrs["erc20"].lower(): epoch},
            live_approvals=substituted,
        )
    assert (
        "permit" in str(excinfo.value).lower()
        or "permit" in excinfo.value.reason_code
    )


def test_nonce_mutation_at_consumption(rpc_session: dict[str, Any]) -> None:
    guard = _guard()
    binding = guard.bind_transaction(_candidate(rpc_session))
    decision = _allow(guard, binding, request_id="req:eth-nonce")
    capability = decision.preflight.capability  # type: ignore[union-attr]
    request = _request_for(guard, binding, request_id="req:eth-nonce")

    with pytest.raises(GuardCapabilityError, match="nonce"):
        guard.revalidate_and_consume(
            capability,
            request,
            binding,
            phase=PreflightPhase.PRE_SIGN,
            now=_NOW_OK,
            live_nonce=binding.nonce + 1 if binding.nonce is not None else 99,
        )


def test_fee_mutation_at_consumption(rpc_session: dict[str, Any]) -> None:
    guard = _guard()
    binding = guard.bind_transaction(_candidate(rpc_session))
    decision = _allow(guard, binding, request_id="req:eth-fee")
    capability = decision.preflight.capability  # type: ignore[union-attr]
    request = _request_for(guard, binding, request_id="req:eth-fee")

    with pytest.raises(GuardCapabilityError, match="fee"):
        guard.revalidate_and_consume(
            capability,
            request,
            binding,
            phase=PreflightPhase.PRE_SIGN,
            now=_NOW_OK,
            live_fee_wei=str(int(binding.fee_wei) + 1),
        )


def test_proxy_upgrade_blocks_consumption(rpc_session: dict[str, Any]) -> None:
    addrs = _addrs(rpc_session)
    guard = _guard()
    epoch = _code_epoch(
        rpc_session, addrs["erc20"], code_epoch="code:v1", implementation_code_digest="b" * 64
    )
    payload = _candidate(
        rpc_session,
        to_address=addrs["erc20"],
        data=_transfer_data(addrs["bob"]),
        value_wei="0",
        method="transfer",
        gas_limit=60_000,
    )
    binding = guard.bind_transaction(payload, code_proxy_epochs=[epoch])
    decision = _allow(
        guard,
        binding,
        request_id="req:eth-upgrade",
        live_epochs={addrs["erc20"].lower(): epoch},
    )
    assert decision.allowed
    capability = decision.preflight.capability  # type: ignore[union-attr]
    request = _request_for(guard, binding, request_id="req:eth-upgrade")

    upgraded = _code_epoch(
        rpc_session,
        addrs["erc20"],
        code_epoch="code:v2-upgraded",
        implementation_code_digest="c" * 64,
    )
    with pytest.raises(GuardCapabilityError) as excinfo:
        guard.revalidate_and_consume(
            capability,
            request,
            binding,
            phase=PreflightPhase.PRE_BROADCAST,
            now=_NOW_OK,
            live_code_proxy_epochs={addrs["erc20"].lower(): upgraded},
        )
    assert (
        "upgrade" in str(excinfo.value).lower()
        or "proxy" in excinfo.value.reason_code
        or "code" in excinfo.value.reason_code
    )


def test_hidden_transfer_blocks_consumption(rpc_session: dict[str, Any]) -> None:
    addrs = _addrs(rpc_session)
    guard = _guard()
    epoch = _code_epoch(rpc_session, addrs["erc20"])
    # Bind a simple approve with no internal effects.
    payload = _candidate(
        rpc_session,
        to_address=addrs["erc20"],
        data=_approve_data(addrs["operator"], 1),
        value_wei="0",
        method="approve",
        gas_limit=60_000,
    )
    binding = guard.bind_transaction(payload, code_proxy_epochs=[epoch])
    decision = _allow(
        guard,
        binding,
        request_id="req:eth-hidden",
        live_epochs={addrs["erc20"].lower(): epoch},
    )
    capability = decision.preflight.capability  # type: ignore[union-attr]
    request = _request_for(guard, binding, request_id="req:eth-hidden")

    hidden = [
        {
            "kind": "internal_call",
            "from": addrs["erc20"],
            "to": addrs["bob"],
            "value_wei": "42",
            "type": "call",
        }
    ]
    with pytest.raises(GuardCapabilityError) as excinfo:
        guard.revalidate_and_consume(
            capability,
            request,
            binding,
            phase=PreflightPhase.PRE_SIGN,
            now=_NOW_OK,
            live_code_proxy_epochs={addrs["erc20"].lower(): epoch},
            live_internal_effects=hidden,
        )
    assert (
        "hidden" in str(excinfo.value).lower()
        or "hidden" in excinfo.value.reason_code
    )


def test_stale_list_revision_at_consumption(rpc_session: dict[str, Any]) -> None:
    guard = _guard()
    binding = guard.bind_transaction(_candidate(rpc_session))
    decision = _allow(guard, binding, request_id="req:eth-list")
    capability = decision.preflight.capability  # type: ignore[union-attr]
    request = _request_for(guard, binding, request_id="req:eth-list")

    with pytest.raises(GuardCapabilityError, match="list revision"):
        guard.revalidate_and_consume(
            capability,
            request,
            binding,
            phase=PreflightPhase.PRE_SIGN,
            now=_NOW_OK,
            live_list_revision="list:ofac-STALE",
        )


def test_live_candidate_field_substitution(rpc_session: dict[str, Any]) -> None:
    guard = _guard()
    binding = guard.bind_transaction(_candidate(rpc_session))
    decision = _allow(guard, binding, request_id="req:eth-cand")
    capability = decision.preflight.capability  # type: ignore[union-attr]
    request = _request_for(guard, binding, request_id="req:eth-cand")

    mutated = _candidate(rpc_session, value_wei="999")
    with pytest.raises(GuardCapabilityError) as excinfo:
        guard.revalidate_and_consume(
            capability,
            request,
            binding,
            phase=PreflightPhase.PRE_SIGN,
            now=_NOW_OK,
            live_candidate=mutated,
        )
    assert (
        "substituted" in str(excinfo.value).lower()
        or "candidate" in excinfo.value.reason_code
    )


def test_successful_consumption_with_matching_epoch(
    rpc_session: dict[str, Any],
) -> None:
    addrs = _addrs(rpc_session)
    guard = _guard()
    epoch = _code_epoch(rpc_session, addrs["erc20"])
    payload = _candidate(
        rpc_session,
        to_address=addrs["erc20"],
        data=_transfer_data(addrs["bob"], 50),
        value_wei="0",
        method="transfer",
        gas_limit=60_000,
    )
    binding = guard.bind_transaction(payload, code_proxy_epochs=[epoch])
    decision = _allow(
        guard,
        binding,
        request_id="req:eth-ok",
        live_epochs={addrs["erc20"].lower(): epoch},
    )
    assert decision.allowed
    capability = decision.preflight.capability  # type: ignore[union-attr]
    request = _request_for(guard, binding, request_id="req:eth-ok")

    result = guard.revalidate_and_consume(
        capability,
        request,
        binding,
        phase=PreflightPhase.PRE_SIGN,
        now=_NOW_OK,
        live_code_proxy_epochs={addrs["erc20"].lower(): epoch},
        live_list_revision=binding.list_revision,
        live_graph_revision=binding.graph_revision,
        live_approvals=list(binding.approvals),
        live_internal_effects=list(binding.internal_effects),
        live_token_effects=list(binding.token_effects),
        live_nonce=binding.nonce,
        live_fee_wei=binding.fee_wei,
        live_candidate=payload,
    )
    assert result.allowed is True
    assert result.phase == PreflightPhase.PRE_SIGN.value

    # Second consumption races / fails closed.
    with pytest.raises(Exception):
        guard.revalidate_and_consume(
            capability,
            request,
            binding,
            phase=PreflightPhase.PRE_BROADCAST,
            now=_NOW_OK,
            live_code_proxy_epochs={addrs["erc20"].lower(): epoch},
        )


def test_code_proxy_epoch_digest_stable(rpc_session: dict[str, Any]) -> None:
    addrs = _addrs(rpc_session)
    a = _code_epoch(rpc_session, addrs["erc20"], code_epoch="e1")
    b = _code_epoch(rpc_session, addrs["erc20"], code_epoch="e1")
    assert a.epoch_digest == b.epoch_digest
    c = _code_epoch(rpc_session, addrs["erc20"], code_epoch="e2-changed")
    assert c.epoch_digest != a.epoch_digest


def test_approval_binding_digest_stable(rpc_session: dict[str, Any]) -> None:
    addrs = _addrs(rpc_session)
    a = ApprovalBinding(
        token=addrs["erc20"],
        owner=addrs["alice"],
        spender=addrs["bob"],
        amount="100",
        kind="approve",
    )
    b = ApprovalBinding(
        token=addrs["erc20"],
        owner=addrs["alice"],
        spender=addrs["bob"],
        amount="100",
        kind="approve",
    )
    assert a.approval_digest == b.approval_digest
    c = ApprovalBinding(
        token=addrs["erc20"],
        owner=addrs["alice"],
        spender=addrs["bob"],
        amount="101",
        kind="approve",
    )
    assert c.approval_digest != a.approval_digest


def test_content_sha256_hex_deterministic() -> None:
    assert content_sha256_hex({"a": 1}) == content_sha256_hex({"a": 1})
    assert content_sha256_hex("hello") == content_sha256_hex("hello")


def test_declared_internal_effects_bound(rpc_session: dict[str, Any]) -> None:
    """Simulated internal effects are bound — method name alone is not enough."""

    addrs = _addrs(rpc_session)
    guard = _guard()
    epoch = _code_epoch(rpc_session, addrs["erc20"])
    # Unknown selector but with explicit simulated internal + token effects.
    data = "0xcafebabe" + _pad_uint(1)
    internal = [
        {
            "kind": "internal_call",
            "from": addrs["erc20"],
            "to": addrs["bob"],
            "value_wei": "1",
            "type": "call",
        }
    ]
    token = [
        {
            "kind": "token_transfer",
            "token": addrs["erc20"],
            "from": addrs["alice"],
            "to": addrs["bob"],
            "amount": "1",
            "source": "simulation",
        }
    ]
    payload = _candidate(
        rpc_session,
        to_address=addrs["erc20"],
        data=data,
        method="",  # no lying method name
        value_wei="0",
        gas_limit=120_000,
        internal_effects=internal,
        token_effects=token,
    )
    binding = guard.bind_transaction(
        payload,
        code_proxy_epochs=[epoch],
        declared_internal_effects=internal,
    )
    assert binding.decoded_kind == "unknown_call"
    assert binding.internal_effects
    assert binding.token_effects
    decision = _allow(
        guard,
        binding,
        request_id="req:eth-sim",
        live_epochs={addrs["erc20"].lower(): epoch},
    )
    # With simulated effects bound, evaluation can allow when security/compliance pass.
    assert decision.allowed is True
