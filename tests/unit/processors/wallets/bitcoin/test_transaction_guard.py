"""Unit tests for the Bitcoin transaction guard (CRYPTOIR-G560 / CRYPTOIR-032).

Offline adversarial fixtures cover:

* Network, every prevout/amount/script, all outputs and change, fee, RBF,
  locktime/sequence, sighash commitment, descriptor/spend path, UTXO
  availability, exact unsigned transaction, list/graph revisions, exposure.
* Output/change/prevout/sighash mutation, spent UTXO, reorg, stale evidence.
* Every output screened; UTXO ancestry without CoinJoin ownership assumption.
"""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from ipfs_datasets_py.logic.crypto_ir.adapters.bitcoin import (
    MAINNET_GENESIS,
    MAINNET_NETWORK,
)
from ipfs_datasets_py.logic.crypto_ir.verdicts import TransactionVerdictOutcome
from ipfs_datasets_py.processors.wallets.guard import (
    GuardCapabilityError,
    GuardForbiddenSurfaceError,
    GuardValidationError,
    PreflightPhase,
)
from ipfs_datasets_py.processors.wallets.bitcoin.transaction_guard import (
    BITCOIN_TRANSACTION_GUARD_INTERFACE,
    PSBTBinding,
    BitcoinGuardDecision,
    BitcoinTransactionBinding,
    BitcoinTransactionCandidate,
    BitcoinTransactionGuard,
    BoundOutput,
    BoundPrevout,
    UtxoAncestryEdge,
    UtxoAvailability,
    UtxoStatus,
    evaluate_bitcoin_transaction_guard,
    outpoint_key,
    signals_rbf,
)


FIXTURE_DIR = (
    Path(__file__).resolve().parents[4]
    / "fixtures"
    / "wallets"
    / "bitcoin"
)

_ISSUED = "2026-07-28T12:00:00Z"
_DEADLINE = "2026-07-28T12:05:00Z"
_EXPIRY = "2026-07-28T12:10:00Z"
_INTENT_EXPIRY = "2026-07-28T12:15:00Z"
_NOW_OK = "2026-07-28T12:02:00Z"


@pytest.fixture(scope="module")
def multi_io() -> dict[str, Any]:
    return json.loads(
        (FIXTURE_DIR / "multi_input_output.json").read_text(encoding="utf-8")
    )


def _candidate_from_multi_io(
    multi_io: dict[str, Any], **overrides: Any
) -> dict[str, Any]:
    tx = multi_io["transaction"]
    payload: dict[str, Any] = {
        "kind": "transaction_candidate",
        "intent_id": "intent:bitcoin-multi-1",
        "network": multi_io.get("network", MAINNET_NETWORK),
        "genesis_hash": MAINNET_GENESIS,
        "version": tx.get("version", 2),
        "locktime": tx.get("locktime", 0),
        "inputs": list(tx["vin"]),
        "outputs": list(tx["vout"]),
        "fee_sats": str(tx.get("fee", 0)),
        # Explicit change only — never inferred from co-spend.
        "change_output_indexes": [1],
        "list_revision": "list:ofac-2026-07-28",
        "graph_revision": "graph:exposure-v1",
        "exposure_paths": [
            {
                "path_id": "path:out-0-direct",
                "output_index": 0,
                "summary": "payment output screened for direct sanctions",
            }
        ],
        "descriptor_paths": [
            {
                "input_index": 0,
                "path_id": "path:wpkh-keypath",
                "descriptor": "wpkh([fpr/0h/0h/0h]xpub.../0/*)",
            }
        ],
        "ancestry_edges": [
            {
                "child_outpoint": outpoint_key(
                    tx["vin"][0]["txid"], tx["vin"][0]["vout"]
                ),
                "parent_outpoint": "eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee:0",
                "depth": 1,
                "value_sats": "100000",
                "ownership_assumed": False,
            }
        ],
    }
    payload.update(overrides)
    return payload


def _utxo_available(outpoint: str, **overrides: Any) -> UtxoAvailability:
    base = {
        "outpoint": outpoint,
        "status": UtxoStatus.AVAILABLE,
        "confirmations": 6,
        "block_height": 840000,
        "block_hash": "f" * 64,
        "tip_height": 840100,
        "tip_hash": "a" * 64,
    }
    base.update(overrides)
    return UtxoAvailability(**base)


def _guard(**kwargs: Any) -> BitcoinTransactionGuard:
    return BitcoinTransactionGuard(**kwargs)


def _allow(
    guard: BitcoinTransactionGuard,
    binding: BitcoinTransactionBinding,
    *,
    request_id: str = "req:btc-1",
    live_utxos: dict[str, UtxoAvailability] | None = None,
) -> BitcoinGuardDecision:
    request = guard.to_preflight_request(
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
    return guard.evaluate(
        binding,
        request=request,
        security_results={req: "pass" for req in request.security_requirement_ids},
        compliance_results={req: "pass" for req in request.compliance_requirement_ids},
        now=_NOW_OK,
        live_utxos=live_utxos,
    )


# ---------------------------------------------------------------------------
# AST / import surface
# ---------------------------------------------------------------------------


def test_ast_symbols_exported() -> None:
    from ipfs_datasets_py.processors.wallets.bitcoin import transaction_guard as mod

    assert hasattr(mod, "BitcoinTransactionGuard")
    assert hasattr(mod, "BitcoinTransactionCandidate")
    assert hasattr(mod, "PSBTBinding")
    assert callable(mod.BitcoinTransactionGuard)
    assert callable(mod.BitcoinTransactionCandidate)
    assert mod.PSBTBinding is PSBTBinding


def test_interface_constants() -> None:
    guard = _guard()
    assert guard.interface == BITCOIN_TRANSACTION_GUARD_INTERFACE
    assert "bitcoin" in guard.schema_version


def test_signals_rbf() -> None:
    assert signals_rbf(0xFFFFFFFD) is True
    assert signals_rbf(0xFFFFFFFE) is False
    assert signals_rbf(0xFFFFFFFF) is False


# ---------------------------------------------------------------------------
# Binding
# ---------------------------------------------------------------------------


def test_bind_multi_io_binds_all_fields(multi_io: dict[str, Any]) -> None:
    guard = _guard()
    cand = BitcoinTransactionCandidate.from_dict(_candidate_from_multi_io(multi_io))
    binding = guard.bind_transaction(cand)

    assert isinstance(binding, BitcoinTransactionBinding)
    assert binding.network == MAINNET_NETWORK
    assert binding.genesis_hash == MAINNET_GENESIS
    assert len(binding.prevouts) == 2
    assert len(binding.outputs) == 2
    assert binding.fee_sats == "5000"
    assert binding.rbf_signaled is True  # sequences 0xfffffffd
    assert binding.locktime == 0
    assert binding.change_output_indexes == (1,)
    assert binding.outputs[1].is_change is True
    assert binding.outputs[1].is_explicit_change is True
    # Payment output is not assumed change.
    assert binding.outputs[0].is_change is False
    assert binding.all_prevouts_known is True
    assert binding.has_weak_sighash is False
    assert binding.list_revision == "list:ofac-2026-07-28"
    assert binding.graph_revision == "graph:exposure-v1"
    assert binding.binding_digest
    assert binding.serialized_digest
    assert binding.byte_length > 0
    # Every prevout has amount + script + sighash commitment.
    for prev in binding.prevouts:
        assert prev.value_sats
        assert prev.script_digest
        assert prev.sighash_commitment_digest
        assert prev.previous_output_known is True
    # Exposure path attached to output 0.
    assert "path:out-0-direct" in binding.outputs[0].exposure_path_ids


def test_bind_screens_every_output(multi_io: dict[str, Any]) -> None:
    guard = _guard()
    payload = _candidate_from_multi_io(multi_io)
    # Drop script from second output — must fail closed.
    payload["outputs"] = deepcopy(payload["outputs"])
    del payload["outputs"][1]["scriptpubkey"]
    with pytest.raises(GuardValidationError, match="script unbound"):
        guard.bind_transaction(payload)


def test_bind_requires_every_prevout_amount_script(multi_io: dict[str, Any]) -> None:
    guard = _guard()
    payload = _candidate_from_multi_io(multi_io)
    payload["inputs"] = deepcopy(payload["inputs"])
    del payload["inputs"][0]["prevout"]
    with pytest.raises(GuardValidationError, match="prevout"):
        guard.bind_transaction(payload)


def test_bind_fee_must_match_inputs_minus_outputs(multi_io: dict[str, Any]) -> None:
    guard = _guard()
    payload = _candidate_from_multi_io(multi_io)
    payload["fee_sats"] = "1"
    with pytest.raises(GuardValidationError, match="fee_sats"):
        guard.bind_transaction(payload)


def test_bind_rejects_forbidden_custody_fields(multi_io: dict[str, Any]) -> None:
    guard = _guard()
    payload = _candidate_from_multi_io(multi_io)
    payload["private_key"] = "deadbeef"
    with pytest.raises(GuardForbiddenSurfaceError):
        guard.bind_transaction(payload)


def test_bind_rejects_coinjoin_ownership_assumption(multi_io: dict[str, Any]) -> None:
    guard = _guard()
    payload = _candidate_from_multi_io(multi_io)
    payload["ancestry_edges"] = [
        {
            "child_outpoint": outpoint_key(
                payload["inputs"][0]["txid"], payload["inputs"][0]["vout"]
            ),
            "parent_outpoint": outpoint_key(
                payload["inputs"][1]["txid"], payload["inputs"][1]["vout"]
            ),
            "depth": 1,
            "value_sats": "1",
            "ownership_assumed": True,
        }
    ]
    with pytest.raises(GuardValidationError, match="ownership"):
        guard.bind_transaction(payload)


def test_bind_rejects_coinjoin_cluster_attribute(multi_io: dict[str, Any]) -> None:
    guard = _guard()
    payload = _candidate_from_multi_io(multi_io)
    a = outpoint_key(payload["inputs"][0]["txid"], payload["inputs"][0]["vout"])
    b = outpoint_key(payload["inputs"][1]["txid"], payload["inputs"][1]["vout"])
    payload["ancestry_edges"] = [
        {
            "child_outpoint": a,
            "parent_outpoint": b,
            "depth": 1,
            "value_sats": "1",
            "ownership_assumed": False,
            "attributes": {"coinjoin_cluster": True},
        }
    ]
    with pytest.raises(GuardValidationError, match="CoinJoin"):
        guard.bind_transaction(payload)


def test_multi_input_does_not_imply_change_clustering(multi_io: dict[str, Any]) -> None:
    """Without explicit change_output_indexes, no output is marked change."""

    guard = _guard()
    payload = _candidate_from_multi_io(multi_io, change_output_indexes=[])
    binding = guard.bind_transaction(payload)
    assert all(not o.is_change for o in binding.outputs)
    assert binding.change_output_indexes == ()


def test_weak_sighash_flagged(multi_io: dict[str, Any]) -> None:
    guard = _guard()
    payload = _candidate_from_multi_io(multi_io)
    payload["inputs"] = deepcopy(payload["inputs"])
    payload["inputs"][0]["sighash_type"] = 0x02  # SIGHASH_NONE
    binding = guard.bind_transaction(payload)
    assert binding.has_weak_sighash is True
    assert binding.prevouts[0].sighash_is_weak is True


# ---------------------------------------------------------------------------
# Evaluate allow path
# ---------------------------------------------------------------------------


def test_evaluate_allows_clean_multi_io(multi_io: dict[str, Any]) -> None:
    guard = _guard()
    binding = guard.bind_transaction(_candidate_from_multi_io(multi_io))
    live = {
        p.outpoint: _utxo_available(p.outpoint) for p in binding.prevouts
    }
    decision = _allow(guard, binding, live_utxos=live)
    assert isinstance(decision, BitcoinGuardDecision)
    assert decision.outcome is TransactionVerdictOutcome.ALLOW
    assert decision.allowed is True
    assert decision.preflight is not None
    assert decision.preflight.capability is not None
    assert decision.binding_digest == binding.binding_digest


def test_evaluate_convenience_function(multi_io: dict[str, Any]) -> None:
    decision = evaluate_bitcoin_transaction_guard(
        _candidate_from_multi_io(multi_io),
        request_id="req:btc-conv",
        tenant_id="tenant:alpha",
        actor_id="actor:policy",
        audience_id="audience:signer",
        issued_at=_ISSUED,
        deadline=_DEADLINE,
        expiry=_EXPIRY,
        now=_NOW_OK,
        security_results={req: "pass" for req in (
            "sec:bitcoin-network-binding",
            "sec:bitcoin-prevout-binding",
            "sec:bitcoin-output-binding",
            "sec:bitcoin-fee-rbf",
            "sec:bitcoin-locktime-sequence",
            "sec:bitcoin-sighash-commitment",
            "sec:bitcoin-spend-path",
            "sec:bitcoin-utxo-availability",
            "sec:bitcoin-exact-candidate",
        )},
        compliance_results={
            "comp:direct-sanctions": "pass",
            "comp:bounded-exposure": "pass",
        },
    )
    assert decision.allowed is True


def test_evaluate_stale_compliance_blocks(multi_io: dict[str, Any]) -> None:
    guard = _guard()
    binding = guard.bind_transaction(_candidate_from_multi_io(multi_io))
    request = guard.to_preflight_request(
        binding,
        request_id="req:btc-stale-comp",
        tenant_id="tenant:alpha",
        actor_id="actor:policy",
        audience_id="audience:signer",
        issued_at=_ISSUED,
        deadline=_DEADLINE,
        expiry=_EXPIRY,
        intent_expires_at=_INTENT_EXPIRY,
    )
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


def test_evaluate_weak_sighash_blocks(multi_io: dict[str, Any]) -> None:
    guard = _guard()
    payload = _candidate_from_multi_io(multi_io)
    payload["inputs"] = deepcopy(payload["inputs"])
    payload["inputs"][0]["sighash_type"] = 0x83  # SINGLE|ANYONECANPAY
    binding = guard.bind_transaction(payload)
    decision = _allow(guard, binding)
    assert decision.allowed is False
    assert any("sighash" in c for c in decision.reason_codes)
    assert decision.blocks_automation is True


def test_evaluate_stale_list_revision_blocks(multi_io: dict[str, Any]) -> None:
    guard = _guard(list_revision_is_current=lambda _rev, _now: False)
    binding = guard.bind_transaction(_candidate_from_multi_io(multi_io))
    decision = _allow(guard, binding)
    assert decision.outcome is TransactionVerdictOutcome.STALE
    assert any("list_revision" in c for c in decision.reason_codes)


def test_evaluate_spent_utxo_blocks(multi_io: dict[str, Any]) -> None:
    guard = _guard()
    binding = guard.bind_transaction(_candidate_from_multi_io(multi_io))
    spent_key = binding.prevouts[0].outpoint
    live = {
        p.outpoint: _utxo_available(p.outpoint) for p in binding.prevouts
    }
    live[spent_key] = _utxo_available(spent_key, status=UtxoStatus.SPENT)
    decision = _allow(guard, binding, live_utxos=live)
    assert decision.allowed is False
    assert any("spent" in c for c in decision.reason_codes)


# ---------------------------------------------------------------------------
# Adversarial: mutation / reorg / consumption
# ---------------------------------------------------------------------------


def test_output_mutation_at_consumption(multi_io: dict[str, Any]) -> None:
    guard = _guard()
    binding = guard.bind_transaction(_candidate_from_multi_io(multi_io))
    live = {p.outpoint: _utxo_available(p.outpoint) for p in binding.prevouts}
    decision = _allow(guard, binding, request_id="req:btc-out-mut", live_utxos=live)
    assert decision.allowed
    capability = decision.preflight.capability  # type: ignore[union-attr]
    request = guard.to_preflight_request(
        binding,
        request_id="req:btc-out-mut",
        tenant_id="tenant:alpha",
        actor_id="actor:policy",
        audience_id="audience:signer",
        issued_at=_ISSUED,
        deadline=_DEADLINE,
        expiry=_EXPIRY,
        intent_expires_at=_INTENT_EXPIRY,
    )
    mutated_outputs = [o.to_dict() for o in binding.outputs]
    mutated_outputs[0] = dict(mutated_outputs[0])
    # Steal value from change into payment.
    mutated_outputs[0]["value_sats"] = str(int(mutated_outputs[0]["value_sats"]) + 1)
    with pytest.raises(GuardCapabilityError, match="output"):
        guard.revalidate_and_consume(
            capability,
            request,
            binding,
            phase=PreflightPhase.PRE_SIGN,
            now=_NOW_OK,
            live_utxos=live,
            live_outputs=mutated_outputs,
        )


def test_prevout_mutation_at_consumption(multi_io: dict[str, Any]) -> None:
    guard = _guard()
    binding = guard.bind_transaction(_candidate_from_multi_io(multi_io))
    live = {p.outpoint: _utxo_available(p.outpoint) for p in binding.prevouts}
    decision = _allow(guard, binding, request_id="req:btc-prev-mut", live_utxos=live)
    capability = decision.preflight.capability  # type: ignore[union-attr]
    request = guard.to_preflight_request(
        binding,
        request_id="req:btc-prev-mut",
        tenant_id="tenant:alpha",
        actor_id="actor:policy",
        audience_id="audience:signer",
        issued_at=_ISSUED,
        deadline=_DEADLINE,
        expiry=_EXPIRY,
        intent_expires_at=_INTENT_EXPIRY,
    )
    live_prevouts = [p.to_dict() for p in binding.prevouts]
    live_prevouts[0] = dict(live_prevouts[0])
    live_prevouts[0]["txid"] = "ff" * 32
    with pytest.raises(GuardCapabilityError) as excinfo:
        guard.revalidate_and_consume(
            capability,
            request,
            binding,
            phase=PreflightPhase.PRE_SIGN,
            now=_NOW_OK,
            live_utxos=live,
            live_prevouts=live_prevouts,
        )
    assert "prevout" in str(excinfo.value).lower() or "prevout" in excinfo.value.reason_code


def test_sighash_mutation_at_consumption(multi_io: dict[str, Any]) -> None:
    guard = _guard()
    binding = guard.bind_transaction(_candidate_from_multi_io(multi_io))
    live = {p.outpoint: _utxo_available(p.outpoint) for p in binding.prevouts}
    decision = _allow(guard, binding, request_id="req:btc-sighash", live_utxos=live)
    capability = decision.preflight.capability  # type: ignore[union-attr]
    request = guard.to_preflight_request(
        binding,
        request_id="req:btc-sighash",
        tenant_id="tenant:alpha",
        actor_id="actor:policy",
        audience_id="audience:signer",
        issued_at=_ISSUED,
        deadline=_DEADLINE,
        expiry=_EXPIRY,
        intent_expires_at=_INTENT_EXPIRY,
    )
    live_prevouts = [p.to_dict() for p in binding.prevouts]
    live_prevouts[0] = dict(live_prevouts[0])
    live_prevouts[0]["sighash_type"] = 0x02  # mutated to NONE
    with pytest.raises(GuardCapabilityError) as excinfo:
        guard.revalidate_and_consume(
            capability,
            request,
            binding,
            phase=PreflightPhase.PRE_SIGN,
            now=_NOW_OK,
            live_utxos=live,
            live_prevouts=live_prevouts,
        )
    assert "sighash" in str(excinfo.value).lower() or "sighash" in excinfo.value.reason_code


def test_spent_utxo_blocks_consumption(multi_io: dict[str, Any]) -> None:
    guard = _guard()
    binding = guard.bind_transaction(_candidate_from_multi_io(multi_io))
    live = {p.outpoint: _utxo_available(p.outpoint) for p in binding.prevouts}
    decision = _allow(guard, binding, request_id="req:btc-spent", live_utxos=live)
    capability = decision.preflight.capability  # type: ignore[union-attr]
    request = guard.to_preflight_request(
        binding,
        request_id="req:btc-spent",
        tenant_id="tenant:alpha",
        actor_id="actor:policy",
        audience_id="audience:signer",
        issued_at=_ISSUED,
        deadline=_DEADLINE,
        expiry=_EXPIRY,
        intent_expires_at=_INTENT_EXPIRY,
    )
    spent = dict(live)
    first = binding.prevouts[0].outpoint
    spent[first] = _utxo_available(first, status=UtxoStatus.SPENT)
    with pytest.raises(GuardCapabilityError) as excinfo:
        guard.revalidate_and_consume(
            capability,
            request,
            binding,
            phase=PreflightPhase.PRE_BROADCAST,
            now=_NOW_OK,
            live_utxos=spent,
        )
    assert "spent" in str(excinfo.value).lower() or "utxo" in excinfo.value.reason_code


def test_reorg_blocks_consumption(multi_io: dict[str, Any]) -> None:
    guard = _guard()
    # Bind with tip height high so reorg (lower tip) is detectable.
    binding = guard.bind_transaction(_candidate_from_multi_io(multi_io))
    live = {
        p.outpoint: _utxo_available(
            p.outpoint, tip_height=840100, tip_hash="a" * 64
        )
        for p in binding.prevouts
    }
    # Rebuild binding with explicit tip on availability epochs.
    binding = guard.bind_transaction(
        _candidate_from_multi_io(multi_io),
        utxo_availability=list(live.values()),
    )
    decision = _allow(guard, binding, request_id="req:btc-reorg", live_utxos=live)
    assert decision.allowed
    capability = decision.preflight.capability  # type: ignore[union-attr]
    request = guard.to_preflight_request(
        binding,
        request_id="req:btc-reorg",
        tenant_id="tenant:alpha",
        actor_id="actor:policy",
        audience_id="audience:signer",
        issued_at=_ISSUED,
        deadline=_DEADLINE,
        expiry=_EXPIRY,
        intent_expires_at=_INTENT_EXPIRY,
    )
    reorged = {
        p.outpoint: _utxo_available(
            p.outpoint,
            tip_height=839900,  # rewound
            tip_hash="b" * 64,
            status=UtxoStatus.AVAILABLE,
        )
        for p in binding.prevouts
    }
    with pytest.raises(GuardCapabilityError) as excinfo:
        guard.revalidate_and_consume(
            capability,
            request,
            binding,
            phase=PreflightPhase.PRE_SIGN,
            now=_NOW_OK,
            live_utxos=reorged,
        )
    assert (
        "reorg" in str(excinfo.value).lower()
        or "reorg" in excinfo.value.reason_code
    )


def test_reorged_utxo_status_blocks_consumption(multi_io: dict[str, Any]) -> None:
    guard = _guard()
    binding = guard.bind_transaction(_candidate_from_multi_io(multi_io))
    live = {p.outpoint: _utxo_available(p.outpoint) for p in binding.prevouts}
    decision = _allow(guard, binding, request_id="req:btc-reorged", live_utxos=live)
    capability = decision.preflight.capability  # type: ignore[union-attr]
    request = guard.to_preflight_request(
        binding,
        request_id="req:btc-reorged",
        tenant_id="tenant:alpha",
        actor_id="actor:policy",
        audience_id="audience:signer",
        issued_at=_ISSUED,
        deadline=_DEADLINE,
        expiry=_EXPIRY,
        intent_expires_at=_INTENT_EXPIRY,
    )
    reorged = dict(live)
    first = binding.prevouts[0].outpoint
    reorged[first] = _utxo_available(first, status=UtxoStatus.REORGED)
    with pytest.raises(GuardCapabilityError) as excinfo:
        guard.revalidate_and_consume(
            capability,
            request,
            binding,
            phase=PreflightPhase.PRE_SIGN,
            now=_NOW_OK,
            live_utxos=reorged,
        )
    assert "reorg" in str(excinfo.value).lower() or "utxo" in excinfo.value.reason_code


def test_stale_list_revision_at_consumption(multi_io: dict[str, Any]) -> None:
    guard = _guard()
    binding = guard.bind_transaction(_candidate_from_multi_io(multi_io))
    live = {p.outpoint: _utxo_available(p.outpoint) for p in binding.prevouts}
    decision = _allow(guard, binding, request_id="req:btc-list", live_utxos=live)
    capability = decision.preflight.capability  # type: ignore[union-attr]
    request = guard.to_preflight_request(
        binding,
        request_id="req:btc-list",
        tenant_id="tenant:alpha",
        actor_id="actor:policy",
        audience_id="audience:signer",
        issued_at=_ISSUED,
        deadline=_DEADLINE,
        expiry=_EXPIRY,
        intent_expires_at=_INTENT_EXPIRY,
    )
    with pytest.raises(GuardCapabilityError, match="list revision"):
        guard.revalidate_and_consume(
            capability,
            request,
            binding,
            phase=PreflightPhase.PRE_SIGN,
            now=_NOW_OK,
            live_utxos=live,
            live_list_revision="list:ofac-STALE",
        )


def test_successful_consumption(multi_io: dict[str, Any]) -> None:
    guard = _guard()
    binding = guard.bind_transaction(_candidate_from_multi_io(multi_io))
    live = {p.outpoint: _utxo_available(p.outpoint) for p in binding.prevouts}
    # Align availability epochs with binding by re-binding with live utxos.
    binding = guard.bind_transaction(
        _candidate_from_multi_io(multi_io),
        utxo_availability=list(live.values()),
    )
    live = {u.outpoint: u for u in binding.utxo_availability}
    decision = _allow(guard, binding, request_id="req:btc-ok", live_utxos=live)
    assert decision.allowed
    capability = decision.preflight.capability  # type: ignore[union-attr]
    request = guard.to_preflight_request(
        binding,
        request_id="req:btc-ok",
        tenant_id="tenant:alpha",
        actor_id="actor:policy",
        audience_id="audience:signer",
        issued_at=_ISSUED,
        deadline=_DEADLINE,
        expiry=_EXPIRY,
        intent_expires_at=_INTENT_EXPIRY,
    )
    result = guard.revalidate_and_consume(
        capability,
        request,
        binding,
        phase=PreflightPhase.PRE_SIGN,
        now=_NOW_OK,
        live_utxos=live,
        live_list_revision=binding.list_revision,
        live_graph_revision=binding.graph_revision,
    )
    assert result is not None
    assert result.allowed is True
    assert result.consumed_at


def test_network_mismatch_fails_bind() -> None:
    guard = _guard()
    payload = {
        "intent_id": "intent:bad-net",
        "network": "bitcoin-mainnet",
        "genesis_hash": "0" * 64,  # wrong genesis
        "inputs": [
            {
                "txid": "bb" * 32,
                "vout": 0,
                "prevout": {
                    "value": 10000,
                    "scriptpubkey": "0014" + "11" * 20,
                    "scriptpubkey_type": "v0_p2wpkh",
                },
                "sequence": 0xFFFFFFFF,
            }
        ],
        "outputs": [
            {
                "n": 0,
                "value": 9000,
                "scriptpubkey": "0014" + "22" * 20,
                "scriptpubkey_type": "v0_p2wpkh",
            }
        ],
        "fee_sats": "1000",
    }
    with pytest.raises(GuardValidationError, match="network"):
        guard.bind_transaction(payload)


def test_bound_records_roundtrip(multi_io: dict[str, Any]) -> None:
    guard = _guard()
    binding = guard.bind_transaction(_candidate_from_multi_io(multi_io))
    restored = BitcoinTransactionBinding.from_dict(binding.to_dict())
    assert restored.binding_digest == binding.binding_digest
    assert len(restored.prevouts) == len(binding.prevouts)
    assert len(restored.outputs) == len(binding.outputs)
    assert BoundPrevout.from_dict(binding.prevouts[0].to_dict()).outpoint == (
        binding.prevouts[0].outpoint
    )
    assert BoundOutput.from_dict(binding.outputs[0].to_dict()).value_sats == (
        binding.outputs[0].value_sats
    )


def test_ancestry_edge_roundtrip() -> None:
    edge = UtxoAncestryEdge(
        child_outpoint=outpoint_key("aa" * 32, 0),
        parent_outpoint=outpoint_key("bb" * 32, 1),
        depth=2,
        value_sats="5000",
    )
    restored = UtxoAncestryEdge.from_dict(edge.to_dict())
    assert restored.child_outpoint == edge.child_outpoint
    assert restored.ownership_assumed is False
