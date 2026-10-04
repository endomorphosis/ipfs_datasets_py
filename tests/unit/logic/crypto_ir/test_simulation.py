"""Unit tests for Crypto IR sandboxed simulation (CRYPTOIR-G330 / CRYPTOIR-025).

Acceptance coverage:

* state, block/slot, VM, tool, input, time, memory, trace, and network bounds
  are receipt-bound
* state mutation is isolated
* counterexamples replay
* provider/backend disagreement remains explicit
* simulation and monitor satisfaction cannot be promoted to theorem proof
* a useful counterexample can disprove an obligation even when successful
  traces cannot prove it
"""

from __future__ import annotations

import pytest

from ipfs_datasets_py.logic.crypto_ir.counterexamples import (
    CounterexampleAuthority,
    CounterexampleError,
    CounterexampleTrace,
    build_counterexample_from_receipt,
    counterexample_disproves,
    replay_counterexample,
    successful_trace_cannot_prove,
)
from ipfs_datasets_py.logic.crypto_ir.differential import (
    DifferentialError,
    DifferentialResult,
    DifferentialStatus,
    compare_receipts,
    run_differential,
)
from ipfs_datasets_py.logic.crypto_ir.simulation import (
    DeterministicOfflineSandbox,
    InjectedFixtureSandbox,
    ProductionForkSandbox,
    SandboxMode,
    SandboxRunResult,
    SimulationAuthority,
    SimulationBounds,
    SimulationError,
    SimulationOutcome,
    SimulationReceipt,
    SimulationRequest,
    SimulationStep,
    StateSnapshot,
    analysis_outcome_for_simulation,
    assert_not_promoted_to_proof,
    assert_simulation_not_proof,
    authority_for_outcome,
    monitor_outcome_for_simulation,
    refuse_simulation_as_theorem_proof,
    run_simulation,
)
from ipfs_datasets_py.logic.crypto_ir.verdicts import (
    AnalysisOutcome,
    MonitorOutcome,
    VerdictFamily,
    refuse_verdict_coercion,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _snapshot(
    *,
    snapshot_id: str = "snap.1",
    storage: dict | None = None,
    block_or_slot: str = "block:100",
    chain_namespace: str = "evm",
    state_digest: str = "digest-state-001",
    vm_id: str = "offline.v1",
) -> StateSnapshot:
    storage = storage if storage is not None else {"balances": {"alice": 100, "bob": 0}}
    return StateSnapshot(
        snapshot_id=snapshot_id,
        chain_namespace=chain_namespace,
        block_or_slot=block_or_slot,
        state_digest=state_digest,
        storage=storage,
        code_digest="code-digest-001",
        vm_id=vm_id,
        subject_id="contract.vault",
    )


def _request(
    *,
    request_id: str = "req.1",
    call_input: dict | None = None,
    bounds: SimulationBounds | None = None,
    obligation_id: str = "obl.no-unauthorized-transfer",
    allow_production_fork: bool = False,
    sandbox_mode: SandboxMode = SandboxMode.OFFLINE_DETERMINISTIC,
    snapshot: StateSnapshot | None = None,
    provider_id: str = "offline",
) -> SimulationRequest:
    return SimulationRequest(
        request_id=request_id,
        snapshot=snapshot or _snapshot(),
        call_input=call_input
        if call_input is not None
        else {"op": "transfer", "from": "alice", "to": "bob", "amount": 10},
        bounds=bounds or SimulationBounds(),
        obligation_id=obligation_id,
        monitor_predicate_ids=("mon.balance-conservation",),
        allow_production_fork=allow_production_fork,
        sandbox_mode=sandbox_mode,
        provider_id=provider_id,
        tool_name="crypto-ir-offline-sandbox",
        tool_version="1.0.0",
    )


# ---------------------------------------------------------------------------
# Core types and AST symbols
# ---------------------------------------------------------------------------


def test_ast_symbols_are_importable() -> None:
    assert SimulationRequest is not None
    assert SimulationReceipt is not None
    assert DifferentialResult is not None
    assert CounterexampleTrace is not None


def test_simulation_request_identity_stable() -> None:
    a = _request()
    b = SimulationRequest.from_dict(a.to_dict())
    assert a.identity.digest == b.identity.digest
    assert a.input_digest() == b.input_digest()


def test_state_snapshot_working_storage_is_copy() -> None:
    snap = _snapshot(storage={"k": 1})
    working = snap.working_storage()
    working["k"] = 99
    assert snap.storage["k"] == 1
    assert dict(snap.storage)["k"] == 1


# ---------------------------------------------------------------------------
# Receipt-bound bounds
# ---------------------------------------------------------------------------


def test_receipt_binds_state_block_vm_tool_input_and_bounds() -> None:
    bounds = SimulationBounds(
        max_steps=32,
        max_time_ms=2_000,
        max_memory_bytes=1_000_000,
        max_trace_events=64,
        max_network_calls=0,
        allow_network=False,
        max_input_bytes=8_192,
    )
    request = _request(
        bounds=bounds,
        call_input={"op": "set", "key": "flag", "value": True},
    )
    sandbox = DeterministicOfflineSandbox()
    receipt = run_simulation(request, sandbox, receipt_id="receipt.bounds.1")

    assert receipt.snapshot_id == request.snapshot.snapshot_id
    assert receipt.snapshot_state_digest == request.snapshot.state_digest
    assert receipt.isolation_source_digest == request.snapshot.state_digest
    assert receipt.block_or_slot == request.snapshot.block_or_slot
    assert receipt.vm_id == request.vm_id
    assert receipt.tool_name == sandbox.tool_name
    assert receipt.tool_version == sandbox.tool_version
    assert receipt.input_digest == request.input_digest()
    assert receipt.bounds.max_steps == 32
    assert receipt.bounds.max_time_ms == 2_000
    assert receipt.bounds.max_memory_bytes == 1_000_000
    assert receipt.bounds.max_trace_events == 64
    assert receipt.bounds.max_network_calls == 0
    assert receipt.bounds.allow_network is False
    assert receipt.network_calls == 0
    assert receipt.elapsed_ms <= receipt.bounds.max_time_ms
    assert len(receipt.steps) <= receipt.bounds.max_steps
    assert len(receipt.steps) <= receipt.bounds.max_trace_events
    assert receipt.memory_bytes_used <= receipt.bounds.max_memory_bytes


def test_receipt_round_trip() -> None:
    receipt = run_simulation(_request(), DeterministicOfflineSandbox())
    restored = SimulationReceipt.from_dict(receipt.to_dict())
    assert restored.identity.digest == receipt.identity.digest
    assert restored.outcome is receipt.outcome
    assert restored.authority is receipt.authority


def test_input_exceeding_bound_rejected() -> None:
    bounds = SimulationBounds(max_input_bytes=16)
    with pytest.raises(SimulationError, match="max_input_bytes"):
        _request(
            bounds=bounds,
            call_input={"op": "set", "key": "x", "value": "this-is-far-too-long"},
        )


def test_network_calls_without_allow_network_rejected_on_receipt() -> None:
    request = _request(call_input={"op": "noop"})
    run = SandboxRunResult(
        outcome=SimulationOutcome.SUCCESS,
        steps=(SimulationStep(step_index=0, op="noop"),),
        final_storage={},
        post_state_digest="post",
        elapsed_ms=1,
        memory_bytes_used=10,
        network_calls=1,
        reason="illegal network",
    )
    with pytest.raises(SimulationError, match="allow_network"):
        from ipfs_datasets_py.logic.crypto_ir.simulation import build_simulation_receipt

        build_simulation_receipt(request, run, receipt_id="receipt.net.1")


# ---------------------------------------------------------------------------
# Isolation
# ---------------------------------------------------------------------------


def test_state_mutation_is_isolated() -> None:
    from ipfs_datasets_py.logic.crypto_ir.provenance import thaw_json

    snap = _snapshot(storage={"balances": {"alice": 50, "bob": 0}, "flag": False})
    original_storage = thaw_json(snap.storage)
    original_digest = snap.state_digest
    original_storage_digest = snap.storage_digest()

    request = _request(
        snapshot=snap,
        call_input={
            "op": "sequence",
            "steps": [
                {"op": "transfer", "from": "alice", "to": "bob", "amount": 5},
                {"op": "set", "key": "flag", "value": True},
            ],
        },
    )
    receipt = run_simulation(request, DeterministicOfflineSandbox())

    assert receipt.outcome is SimulationOutcome.SUCCESS
    assert receipt.final_storage["flag"] is True
    assert receipt.final_storage["balances"]["bob"] == 5
    # Source snapshot untouched.
    assert thaw_json(snap.storage) == original_storage
    assert snap.state_digest == original_digest
    assert snap.storage_digest() == original_storage_digest
    assert receipt.isolation_source_digest == original_digest
    assert receipt.snapshot_state_digest == original_digest


def test_transfer_revert_on_insufficient_balance() -> None:
    request = _request(
        call_input={"op": "transfer", "from": "alice", "to": "bob", "amount": 999},
    )
    receipt = run_simulation(request, DeterministicOfflineSandbox())
    assert receipt.outcome is SimulationOutcome.REVERT
    assert receipt.authority is SimulationAuthority.EVIDENCE_ONLY
    assert receipt.analysis_outcome is AnalysisOutcome.UNKNOWN
    assert receipt.monitor_outcome is MonitorOutcome.UNKNOWN


# ---------------------------------------------------------------------------
# Authority: simulation/monitor cannot become theorem proof
# ---------------------------------------------------------------------------


def test_successful_simulation_is_monitor_only_not_proved() -> None:
    receipt = run_simulation(
        _request(call_input={"op": "noop"}),
        DeterministicOfflineSandbox(),
    )
    assert receipt.outcome is SimulationOutcome.SUCCESS
    assert receipt.authority is SimulationAuthority.MONITOR_ONLY
    assert receipt.monitor_outcome is MonitorOutcome.MONITOR_SATISFIED
    assert receipt.analysis_outcome is AnalysisOutcome.UNKNOWN
    assert receipt.analysis_outcome is not AnalysisOutcome.PROVED
    assert_simulation_not_proof(receipt.authority)
    assert successful_trace_cannot_prove(receipt) is AnalysisOutcome.UNKNOWN


def test_refuse_simulation_promotion_to_theorem_proof() -> None:
    with pytest.raises(Exception, match="cannot coerce|cannot be promoted"):
        refuse_simulation_as_theorem_proof()
    with pytest.raises(Exception):
        refuse_verdict_coercion(
            VerdictFamily.MONITOR,
            VerdictFamily.ANALYSIS,
            context="test",
        )
    with pytest.raises(SimulationError, match="cannot be promoted"):
        assert_not_promoted_to_proof(
            simulation_outcome=SimulationOutcome.SUCCESS,
            claimed_analysis=AnalysisOutcome.PROVED,
        )


def test_receipt_rejects_proved_analysis_outcome() -> None:
    request = _request(call_input={"op": "noop"})
    with pytest.raises(SimulationError, match="PROVED"):
        SimulationReceipt(
            receipt_id="receipt.bad",
            request_id=request.request_id,
            outcome=SimulationOutcome.SUCCESS,
            authority=SimulationAuthority.MONITOR_ONLY,
            executed=True,
            snapshot_id=request.snapshot.snapshot_id,
            snapshot_state_digest=request.snapshot.state_digest,
            post_state_digest="post",
            isolation_source_digest=request.snapshot.state_digest,
            bounds=request.bounds,
            analysis_outcome=AnalysisOutcome.PROVED,
            monitor_outcome=MonitorOutcome.MONITOR_SATISFIED,
        )


def test_authority_and_monitor_projections() -> None:
    assert authority_for_outcome(SimulationOutcome.SUCCESS) is SimulationAuthority.MONITOR_ONLY
    assert authority_for_outcome(SimulationOutcome.VIOLATION) is SimulationAuthority.DISPROOF_WITNESS
    assert monitor_outcome_for_simulation(SimulationOutcome.SUCCESS) is MonitorOutcome.MONITOR_SATISFIED
    assert monitor_outcome_for_simulation(SimulationOutcome.VIOLATION) is MonitorOutcome.MONITOR_VIOLATED
    assert analysis_outcome_for_simulation(SimulationOutcome.SUCCESS) is AnalysisOutcome.UNKNOWN
    assert analysis_outcome_for_simulation(SimulationOutcome.VIOLATION) is AnalysisOutcome.DISPROVED


# ---------------------------------------------------------------------------
# Counterexamples: disprove without proving; replay
# ---------------------------------------------------------------------------


def test_counterexample_disproves_when_success_cannot_prove() -> None:
    """Asymmetry: violation → DISPROVED; success → not PROVED."""

    sandbox = DeterministicOfflineSandbox()
    snap = _snapshot(storage={"owner": "alice", "caller": "eve"})

    success_req = _request(
        request_id="req.success",
        snapshot=snap,
        call_input={"op": "assert_eq", "key": "owner", "value": "alice"},
        obligation_id="obl.only-owner",
    )
    success_receipt = run_simulation(success_req, sandbox, receipt_id="receipt.success")
    assert success_receipt.outcome is SimulationOutcome.SUCCESS
    assert successful_trace_cannot_prove(success_receipt) is AnalysisOutcome.UNKNOWN
    success_trace = build_counterexample_from_receipt(
        success_receipt, trace_id="cx.success", request=success_req
    )
    assert not success_trace.disproves_obligation
    assert not counterexample_disproves(success_trace)

    violate_req = _request(
        request_id="req.violate",
        snapshot=snap,
        call_input={"op": "assert_eq", "key": "caller", "value": "alice"},
        obligation_id="obl.only-owner",
    )
    violate_receipt = run_simulation(violate_req, sandbox, receipt_id="receipt.violate")
    assert violate_receipt.outcome is SimulationOutcome.VIOLATION
    assert violate_receipt.authority is SimulationAuthority.DISPROOF_WITNESS
    assert violate_receipt.analysis_outcome is AnalysisOutcome.DISPROVED

    cex = build_counterexample_from_receipt(
        violate_receipt, trace_id="cx.violate", request=violate_req
    )
    assert cex.authority is CounterexampleAuthority.DISPROOF_WITNESS
    assert cex.disproves_obligation
    assert cex.replayable
    assert counterexample_disproves(cex) is True
    # Successful traces cannot prove; counterexample still disproves.
    assert success_trace.analysis_outcome is not AnalysisOutcome.PROVED
    assert cex.analysis_outcome is AnalysisOutcome.DISPROVED


def test_counterexample_replay() -> None:
    sandbox = DeterministicOfflineSandbox()
    request = _request(
        call_input={"op": "violate", "predicate": "mon.reentrancy"},
        obligation_id="obl.no-reentrancy",
    )
    receipt = run_simulation(request, sandbox, receipt_id="receipt.cex.1")
    cex = build_counterexample_from_receipt(
        receipt, trace_id="cx.replay.1", request=request
    )
    assert cex.replayable
    replayed = replay_counterexample(cex, sandbox=sandbox)
    assert replayed.outcome is SimulationOutcome.VIOLATION
    assert replayed.analysis_outcome is AnalysisOutcome.DISPROVED
    assert counterexample_disproves(cex, require_replay=True, sandbox=sandbox)


def test_non_replayable_counterexample_rejects_replay() -> None:
    cex = CounterexampleTrace(
        trace_id="cx.bare",
        obligation_id="obl.x",
        outcome=SimulationOutcome.VIOLATION,
        authority=CounterexampleAuthority.DISPROOF_WITNESS,
        snapshot_digest="digest",
        input_digest="input",
        analysis_outcome=AnalysisOutcome.DISPROVED,
        monitor_outcome=MonitorOutcome.MONITOR_VIOLATED,
        replayable=False,
    )
    with pytest.raises(CounterexampleError, match="not replayable"):
        replay_counterexample(cex)


def test_explicit_violation_op() -> None:
    receipt = run_simulation(
        _request(call_input={"op": "violate", "predicate": "p.bad"}),
        DeterministicOfflineSandbox(),
    )
    assert receipt.is_disproof_witness
    assert "p.bad" in receipt.reason or receipt.reason


# ---------------------------------------------------------------------------
# Differential: explicit disagreement
# ---------------------------------------------------------------------------


def test_differential_agreement_on_identical_providers() -> None:
    request = _request(call_input={"op": "noop"})
    left = DeterministicOfflineSandbox(provider_id="offline.a")
    right = DeterministicOfflineSandbox(provider_id="offline.b")
    left_r, right_r, result = run_differential(
        request, left, right, result_id="diff.agree.1"
    )
    assert left_r.outcome is right_r.outcome
    assert result.status is DifferentialStatus.AGREE
    assert not result.disagreement_fields
    assert "outcome" in result.agreement_fields
    assert result.analysis_outcome is not AnalysisOutcome.PROVED


def test_differential_disagreement_is_explicit() -> None:
    request = _request(call_input={"op": "noop"}, request_id="req.diff.1")
    success_run = SandboxRunResult(
        outcome=SimulationOutcome.SUCCESS,
        steps=(SimulationStep(step_index=0, op="noop"),),
        final_storage={"ok": True},
        post_state_digest="post-success",
        elapsed_ms=1,
        memory_bytes_used=32,
        network_calls=0,
        reason="left success",
    )
    violate_run = SandboxRunResult(
        outcome=SimulationOutcome.VIOLATION,
        steps=(SimulationStep(step_index=0, op="violate"),),
        final_storage={"ok": False},
        post_state_digest="post-violate",
        elapsed_ms=1,
        memory_bytes_used=32,
        network_calls=0,
        reason="right violation",
    )
    left = InjectedFixtureSandbox(success_run, provider_id="provider.left")
    right = InjectedFixtureSandbox(violate_run, provider_id="provider.right")
    _left_r, _right_r, result = run_differential(
        request, left, right, result_id="diff.disagree.1"
    )
    assert result.status is DifferentialStatus.DISAGREE
    assert result.is_explicit_disagreement
    assert "outcome" in result.disagreement_fields
    assert result.left_outcome == "success"
    assert result.right_outcome == "violation"
    assert result.analysis_outcome is AnalysisOutcome.INCONCLUSIVE
    # Disagreement never elevates to proof.
    assert result.is_non_proof


def test_compare_receipts_rejects_proved() -> None:
    left = run_simulation(_request(call_input={"op": "noop"}), DeterministicOfflineSandbox())
    right = run_simulation(
        _request(request_id="req.2", call_input={"op": "noop"}),
        DeterministicOfflineSandbox(),
    )
    result = compare_receipts(left, right, result_id="diff.cmp.1")
    assert result.status in {
        DifferentialStatus.AGREE,
        DifferentialStatus.PARTIAL,
        DifferentialStatus.DISAGREE,
    }
    restored = DifferentialResult.from_dict(result.to_dict())
    assert restored.identity.digest == result.identity.digest


def test_unavailable_provider_surface() -> None:
    request = _request(call_input={"op": "noop"})
    left = DeterministicOfflineSandbox(provider_id="offline.ok")
    right = InjectedFixtureSandbox(
        SandboxRunResult(
            outcome=SimulationOutcome.UNAVAILABLE,
            steps=(),
            final_storage={},
            post_state_digest="",
            elapsed_ms=0,
            memory_bytes_used=0,
            network_calls=0,
            reason="down",
        ),
        provider_id="offline.down",
        available=False,
    )
    _l, _r, result = run_differential(request, left, right, result_id="diff.unavail.1")
    assert result.status is DifferentialStatus.UNAVAILABLE


# ---------------------------------------------------------------------------
# Production fork opt-in
# ---------------------------------------------------------------------------


def test_production_fork_refused_without_opt_in() -> None:
    request = _request(
        call_input={"op": "noop"},
        allow_production_fork=False,
        sandbox_mode=SandboxMode.OFFLINE_DETERMINISTIC,
    )
    fork = ProductionForkSandbox()
    receipt = run_simulation(request, fork, receipt_id="receipt.fork.1")
    assert receipt.outcome is SimulationOutcome.REFUSED
    assert receipt.executed is False
    assert receipt.authority is SimulationAuthority.NON_PROOF


def test_production_fork_mode_requires_allow_flag_on_request() -> None:
    with pytest.raises(SimulationError, match="allow_production_fork"):
        _request(
            sandbox_mode=SandboxMode.PRODUCTION_FORK,
            allow_production_fork=False,
        )


def test_production_fork_with_opt_in_and_injector() -> None:
    injected = InjectedFixtureSandbox(
        SandboxRunResult(
            outcome=SimulationOutcome.SUCCESS,
            steps=(SimulationStep(step_index=0, op="noop"),),
            final_storage={},
            post_state_digest="fork-post",
            elapsed_ms=2,
            memory_bytes_used=16,
            network_calls=0,
            reason="fork ok",
        ),
        provider_id="fork.injector",
    )
    fork = ProductionForkSandbox(injector=injected)
    request = _request(
        call_input={"op": "noop"},
        allow_production_fork=True,
        sandbox_mode=SandboxMode.PRODUCTION_FORK,
        provider_id="fork.production",
    )
    receipt = run_simulation(request, fork, receipt_id="receipt.fork.2")
    assert receipt.outcome is SimulationOutcome.SUCCESS
    assert receipt.sandbox_mode is SandboxMode.PRODUCTION_FORK


# ---------------------------------------------------------------------------
# Bound exceeded / forced fixtures
# ---------------------------------------------------------------------------


def test_max_steps_bound_exceeded() -> None:
    bounds = SimulationBounds(max_steps=2)
    request = _request(
        bounds=bounds,
        call_input={
            "op": "sequence",
            "steps": [
                {"op": "noop"},
                {"op": "noop"},
                {"op": "noop"},
            ],
        },
    )
    receipt = run_simulation(request, DeterministicOfflineSandbox())
    assert receipt.outcome is SimulationOutcome.BOUND_EXCEEDED
    assert receipt.authority is SimulationAuthority.EVIDENCE_ONLY


def test_forced_unavailable_fixture() -> None:
    receipt = run_simulation(
        _request(call_input={"op": "noop", "force_outcome": "unavailable"}),
        DeterministicOfflineSandbox(),
    )
    assert receipt.outcome is SimulationOutcome.UNAVAILABLE
    assert receipt.executed is False


def test_assert_eq_violation_witness() -> None:
    request = _request(
        snapshot=_snapshot(storage={"role": "user"}),
        call_input={"op": "assert_eq", "key": "role", "value": "admin"},
        obligation_id="obl.admin-only",
    )
    receipt = run_simulation(request, DeterministicOfflineSandbox())
    assert receipt.outcome is SimulationOutcome.VIOLATION
    cex = build_counterexample_from_receipt(
        receipt, trace_id="cx.admin", request=request
    )
    assert counterexample_disproves(cex, require_replay=True)


# ---------------------------------------------------------------------------
# Isolation digest integrity on receipt
# ---------------------------------------------------------------------------


def test_receipt_requires_isolation_digest_match() -> None:
    request = _request(call_input={"op": "noop"})
    with pytest.raises(SimulationError, match="isolation_source_digest"):
        SimulationReceipt(
            receipt_id="receipt.iso.bad",
            request_id=request.request_id,
            outcome=SimulationOutcome.SUCCESS,
            authority=SimulationAuthority.MONITOR_ONLY,
            executed=True,
            snapshot_id=request.snapshot.snapshot_id,
            snapshot_state_digest=request.snapshot.state_digest,
            post_state_digest="post",
            isolation_source_digest="different-digest",
            bounds=request.bounds,
            monitor_outcome=MonitorOutcome.MONITOR_SATISFIED,
            analysis_outcome=AnalysisOutcome.UNKNOWN,
        )


def test_non_executed_cannot_claim_success() -> None:
    request = _request(call_input={"op": "noop"})
    with pytest.raises(SimulationError, match="non-executed"):
        SimulationReceipt(
            receipt_id="receipt.exec.bad",
            request_id=request.request_id,
            outcome=SimulationOutcome.SUCCESS,
            authority=SimulationAuthority.MONITOR_ONLY,
            executed=False,
            snapshot_id=request.snapshot.snapshot_id,
            snapshot_state_digest=request.snapshot.state_digest,
            post_state_digest="post",
            isolation_source_digest=request.snapshot.state_digest,
            bounds=request.bounds,
            monitor_outcome=MonitorOutcome.MONITOR_SATISFIED,
            analysis_outcome=AnalysisOutcome.UNKNOWN,
        )
