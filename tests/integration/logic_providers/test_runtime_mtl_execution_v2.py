"""Integration tests: runtime MTL monitoring + verdict replay (LFP2-036).

Acceptance (fail-closed):

* Deferred / placeholder unknown remains only an explicit unsupported or
  unavailable outcome — never a silent substitute for evaluation.
* Evaluated verdicts replay against the same formula, trace, position, and
  semantics (clock / event-time / lateness / prefix / interval /
  monitorability / three-valued verdict).
* Mock / fallback / availability / confidence never establish monitor,
  proof, satisfiability, or theorem authority.

Interfaces: RuntimeMTLEvidence@2
"""

from __future__ import annotations

import pytest

from ipfs_datasets_py.logic.backends.results import ResultAuthority, ResultStatus
from ipfs_datasets_py.logic.backends.runtime_mtl_execution_v2 import (
    RUNTIME_MTL_EVIDENCE_V2_INTERFACE,
    RUNTIME_MTL_EXECUTION_V2_TASK_ID,
    RUNTIME_MTL_MONITOR_INTERFACE,
    RuntimeMTLAuthorityError,
    RuntimeMTLClaimKind,
    RuntimeMTLDisposition,
    RuntimeMTLEvidenceV2,
    RuntimeMTLExecutionEngineV2,
    RuntimeMTLExecutionError,
    RuntimeMTLExecutionMode,
    RuntimeMTLExecutionRequestV2,
    RuntimeMTLProviderKind,
    RuntimeMTLReplayReceiptV2,
    RuntimeMTLSemanticsBindingV2,
    deferred_or_mock_establishes_monitor,
    execute_runtime_mtl,
    monitor_and_replay,
    non_authoritative_signal_establishes,
    normalize_runtime_mtl_provider,
)
from ipfs_datasets_py.logic.backends.toolchain_roles import (
    ToolRole,
    ToolchainAuthorityCeiling,
)
from ipfs_datasets_py.logic.software_verification.monitoring.runtime_mtl import (
    Formula,
    Logic,
    MonitorAuthority,
    TraceKind,
    Verdict,
    always,
    eventually,
    golden_fixtures,
)


# ---------------------------------------------------------------------------
# Compact fixture helpers (recipes, not bulk golden dumps)
# ---------------------------------------------------------------------------


def _tv(numerator: int, denominator: int = 1) -> dict[str, int]:
    return {"numerator": numerator, "denominator": denominator}


def _event(
    index: int,
    *true: str,
    false: tuple[str, ...] = (),
    time: int | tuple[int, int] | None = None,
) -> dict[str, object]:
    if time is None:
        time_value = _tv(index)
    elif isinstance(time, int):
        time_value = _tv(time)
    else:
        time_value = _tv(time[0], time[1])
    return {
        "event_id": f"event:{index}",
        "event_type": "state",
        "time": time_value,
        "true": list(true),
        "false": list(false),
    }


def _clock(
    *,
    unit: str = "logical_tick",
    domain: str = "discrete",
    resolution: tuple[int, int] = (1, 1),
    clock_id: str = "clock:main",
) -> dict[str, object]:
    return {
        "clock_id": clock_id,
        "domain": domain,
        "unit": unit,
        "resolution": _tv(resolution[0], resolution[1]),
    }


def _trace(
    kind: str,
    events: list[dict[str, object]],
    *,
    clock: dict[str, object] | None = None,
    policy: str = "closed_world",
) -> dict[str, object]:
    return {
        "kind": kind,
        "clock": clock or _clock(),
        "events": events,
        "observation_policy": policy,
        "schema_version": "runtime-mtl-trace/v1",
    }


def _atom(name: str, logic: str = "ltlf") -> dict[str, object]:
    return {
        "operator": "atom",
        "logic": logic,
        "operands": [],
        "proposition": name,
        "interval": None,
        "schema_version": "runtime-mtl-formula/v1",
    }


def _unary(
    operator: str,
    operand: dict[str, object],
    *,
    logic: str | None = None,
    interval: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "operator": operator,
        "logic": logic or operand["logic"],
        "operands": [operand],
        "proposition": "",
        "interval": interval,
        "schema_version": "runtime-mtl-formula/v1",
    }


def _interval(
    lower: int,
    upper: int | None,
    unit: str,
    *,
    upper_closed: bool = True,
) -> dict[str, object]:
    return {
        "lower": _tv(lower),
        "upper": None if upper is None else _tv(upper),
        "unit": unit,
        "lower_closed": True,
        "upper_closed": upper_closed,
        "schema_version": "runtime-mtl-interval/v1",
    }


def _always_safe_request(**overrides: object) -> RuntimeMTLExecutionRequestV2:
    payload: dict[str, object] = {
        "request_id": "req:runtime-mtl:always-safe",
        "formula": _unary("always", _atom("safe")),
        "trace": _trace(
            "finite",
            [_event(0, "safe"), _event(1, "safe"), _event(2, "safe", "done")],
        ),
        "provider": RuntimeMTLProviderKind.RUNTIME_MTL,
        "position": 0,
        "source_ref_ids": ("source:fixture:runtime-mtl:always-safe",),
        "available": True,
        "confidence": 0.99,
        "fluent_text": "Obviously the safety property is proved.",
    }
    payload.update(overrides)
    return RuntimeMTLExecutionRequestV2(**payload)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Interface / typing surface
# ---------------------------------------------------------------------------


def test_interface_identities() -> None:
    engine = RuntimeMTLExecutionEngineV2()
    assert engine.INTERFACE == RUNTIME_MTL_EVIDENCE_V2_INTERFACE
    assert engine.interface == "RuntimeMTLEvidence@2"
    assert engine.TASK_ID == RUNTIME_MTL_EXECUTION_V2_TASK_ID
    assert engine.TASK_ID == "LFP2-036"
    assert RuntimeMTLExecutionRequestV2.interface == "RuntimeMTLExecutionRequest@2"
    assert RUNTIME_MTL_MONITOR_INTERFACE == "RuntimeMTLMonitor@1"


def test_provider_normalization() -> None:
    assert normalize_runtime_mtl_provider("runtime_mtl") is RuntimeMTLProviderKind.RUNTIME_MTL
    assert (
        normalize_runtime_mtl_provider("runtime-mtl") is RuntimeMTLProviderKind.RUNTIME_MTL
    )
    assert (
        normalize_runtime_mtl_provider("runtime-mtl-external")
        is RuntimeMTLProviderKind.RUNTIME_MTL_EXTERNAL
    )
    assert (
        normalize_runtime_mtl_provider(RuntimeMTLProviderKind.RUNTIME_MTL)
        is RuntimeMTLProviderKind.RUNTIME_MTL
    )
    with pytest.raises(RuntimeMTLExecutionError):
        normalize_runtime_mtl_provider("z3")
    with pytest.raises(RuntimeMTLExecutionError):
        normalize_runtime_mtl_provider("tla_tlc")


# ---------------------------------------------------------------------------
# Real monitoring replaces deferred UNKNOWN
# ---------------------------------------------------------------------------


def test_native_evaluation_is_not_deferred_unknown() -> None:
    result = execute_runtime_mtl(
        _unary("always", _atom("safe")),
        _trace(
            "finite",
            [_event(0, "safe"), _event(1, "safe"), _event(2, "safe")],
        ),
        request_id="req:native:satisfied",
    )
    assert result.is_evaluated is True
    assert result.evidence.is_deferred_placeholder is False
    assert result.evidence.deferred_routing is False
    assert result.evidence.mode is RuntimeMTLExecutionMode.NATIVE_MONITOR
    assert result.disposition is RuntimeMTLDisposition.SATISFIED
    assert result.evidence.result_status is ResultStatus.SATISFIED
    assert result.evidence.monitor_authority_established is True
    assert result.evidence.result_authority is ResultAuthority.MONITOR
    assert result.evidence.authority_ceiling is ToolchainAuthorityCeiling.FINITE_TRACE
    assert result.evidence.role is ToolRole.AUTHORITY
    assert result.evidence.evaluation is not None
    assert result.evidence.evaluation.authority is MonitorAuthority.MONITOR
    assert result.evidence.evaluation.authorizes_global_proof is False
    assert result.evidence.authorizes_global_proof is False
    assert result.is_proved is False
    assert result.evidence.proof_established is False
    assert result.evidence.theorem_established is False
    assert result.evidence.satisfiability_established is False
    assert "native_monitor_invoked" in result.evidence.diagnostics
    assert "deferred_routing_not_used" in result.evidence.diagnostics
    # Must not look like the old registry deferred UNKNOWN placeholder.
    assert result.disposition is not RuntimeMTLDisposition.DEFERRED_REJECTED
    assert result.evidence.result_status is not ResultStatus.UNSUPPORTED


def test_prefix_always_is_inconclusive_evaluated_not_deferred() -> None:
    result = execute_runtime_mtl(
        _unary("always", _atom("safe")),
        _trace("finite_prefix", [_event(0, "safe"), _event(1, "safe")]),
        request_id="req:prefix:inconclusive",
    )
    assert result.is_evaluated is True
    assert result.disposition is RuntimeMTLDisposition.INCONCLUSIVE
    assert result.evidence.result_status is ResultStatus.UNKNOWN
    assert result.evidence.monitor_authority_established is True
    assert result.evidence.is_deferred_placeholder is False
    assert result.evidence.semantics.is_prefix is True
    assert result.evidence.semantics.trace_kind is TraceKind.FINITE_PREFIX
    assert result.evidence.semantics.three_valued_verdict is Verdict.INCONCLUSIVE
    assert "three_valued_inconclusive" in result.evidence.diagnostics


def test_prefix_always_violation() -> None:
    result = execute_runtime_mtl(
        _unary("always", _atom("safe")),
        _trace(
            "finite_prefix",
            [
                _event(0, "safe"),
                _event(1, "safe"),
                _event(2, false=("safe",)),
            ],
            policy="explicit",
        ),
        request_id="req:prefix:violation",
    )
    assert result.disposition is RuntimeMTLDisposition.VIOLATED
    assert result.evidence.result_status is ResultStatus.VIOLATED
    assert result.evidence.monitor_authority_established is True
    assert result.evidence.semantics.three_valued_verdict is Verdict.FALSE


def test_mtl_interval_and_clock_bindings() -> None:
    formula = _unary(
        "eventually",
        _atom("ready", logic="mtl"),
        interval=_interval(0, 1, "second"),
    )
    trace = _trace(
        "finite",
        [
            _event(0, time=(0, 1)),
            _event(1, time=(1, 2)),
            _event(2, "ready", time=(1, 1)),
        ],
        clock=_clock(unit="second", domain="dense", resolution=(1, 2)),
    )
    result = execute_runtime_mtl(
        formula, trace, request_id="req:mtl:interval"
    )
    assert result.disposition is RuntimeMTLDisposition.SATISFIED
    semantics = result.evidence.semantics
    assert isinstance(semantics, RuntimeMTLSemanticsBindingV2)
    assert semantics.clock_id == "clock:main"
    assert semantics.clock_domain == "dense"
    assert semantics.clock_unit == "second"
    assert semantics.clock_resolution == {"numerator": 1, "denominator": 2}
    assert len(semantics.event_times) == 3
    assert semantics.interval is not None
    assert semantics.interval["unit"] == "second"
    assert semantics.logic is Logic.MTL
    assert result.evidence.bindings_complete() is True
    wire = result.evidence.to_dict()
    assert wire["bindings_complete"] is True
    assert wire["claim_monitor"] is True
    assert wire["claim_proof"] is False
    assert wire["semantics"]["clock_unit"] == "second"
    assert wire["semantics"]["interval"]["upper"]["numerator"] == 1


def test_late_events_flag_bound_into_semantics() -> None:
    result = execute_runtime_mtl(
        _unary("always", _atom("safe")),
        {
            "kind": "finite",
            "clock": _clock(),
            "events": [
                _event(0, "safe", time=2),
                _event(1, "safe", time=1),
            ],
            "observation_policy": "closed_world",
            "schema_version": "runtime-mtl-trace/v1",
        },
        request_id="req:late:events",
    )
    assert result.disposition is RuntimeMTLDisposition.MALFORMED
    assert result.evidence.result_status is ResultStatus.MALFORMED
    assert result.evidence.evaluation is not None
    assert result.evidence.evaluation.late_events is True
    assert result.evidence.semantics.late_events is True
    assert "late_events_detected" in result.evidence.diagnostics
    # Still an evaluated monitor classification, not deferred routing.
    assert result.is_evaluated is True
    assert result.evidence.is_deferred_placeholder is False


# ---------------------------------------------------------------------------
# Verdict replay against same trace and semantics
# ---------------------------------------------------------------------------


def test_evaluated_verdict_replays_against_same_trace() -> None:
    engine = RuntimeMTLExecutionEngineV2()
    result = engine.execute(_always_safe_request())
    assert result.evidence.replay is not None
    replay = result.evidence.replay
    assert isinstance(replay, RuntimeMTLReplayReceiptV2)
    assert replay.matched is True
    assert replay.replay_claimed is True
    assert replay.original_verdict is Verdict.TRUE
    assert replay.replayed_verdict is Verdict.TRUE
    assert replay.formula_digest == result.evidence.formula_digest
    assert replay.trace_digest == result.evidence.trace_digest
    assert replay.semantics_digest == result.evidence.semantics.content_digest()

    # Explicit second-pass replay API also matches.
    second = engine.replay(result)
    assert second.matched is True
    assert second.replay_claimed is True
    assert second.original_verdict is second.replayed_verdict
    assert second.original_status is second.replayed_status
    assert second.original_monitorability is second.replayed_monitorability


def test_monitor_and_replay_helper_agrees() -> None:
    result, replay = monitor_and_replay(
        _unary("eventually", _atom("done")),
        _trace(
            "finite",
            [_event(0, "safe"), _event(1, "safe", "done")],
        ),
        request_id="req:helper:replay",
    )
    assert result.disposition is RuntimeMTLDisposition.SATISFIED
    assert replay.matched is True
    assert replay.replay_claimed is True
    assert result.evidence.replay is not None
    assert result.evidence.replay.matched is True


def test_golden_fixtures_evaluate_and_replay() -> None:
    engine = RuntimeMTLExecutionEngineV2()
    results = engine.execute_golden_fixtures()
    assert len(results) == len(golden_fixtures())
    for result, case in zip(results, golden_fixtures(), strict=True):
        expected = case.get("expected") or {}
        assert result.evidence.is_deferred_placeholder is False
        assert result.evidence.mode is RuntimeMTLExecutionMode.NATIVE_MONITOR
        assert result.evidence.evaluation is not None
        evaluation = result.evidence.evaluation.to_dict()
        for key, value in expected.items():
            assert evaluation.get(key) == value, (
                f"case {case.get('case_id')!r} drifted on {key}: "
                f"expected {value!r}, got {evaluation.get(key)!r}"
            )
        assert evaluation["authority"] == "monitor"
        assert evaluation["authorizes_global_proof"] is False
        # Replay is bound for every evaluated case.
        assert result.evidence.replay is not None
        assert result.evidence.replay.matched is True
        assert result.evidence.replay.replay_claimed is True
        assert result.evidence.bindings_complete() is True
        # Semantics carry clock / prefix / three-valued verdict.
        semantics = result.evidence.semantics
        assert semantics.clock_id
        assert semantics.three_valued_verdict is not None
        assert semantics.monitorability is not None
        if expected.get("trace_kind") == "finite_prefix":
            assert semantics.is_prefix is True
        if expected.get("late_events") is True:
            assert semantics.late_events is True


# ---------------------------------------------------------------------------
# Deferred / mock / unavailable remain explicit non-evaluation outcomes
# ---------------------------------------------------------------------------


def test_explicit_deferred_is_rejected_not_evaluated() -> None:
    result = RuntimeMTLExecutionEngineV2().execute(
        _always_safe_request(
            deferred=True,
            mode=RuntimeMTLExecutionMode.DEFERRED,
            request_id="req:deferred:1",
        )
    )
    assert result.disposition is RuntimeMTLDisposition.DEFERRED_REJECTED
    assert result.evidence.deferred_routing is True
    assert result.evidence.mode is RuntimeMTLExecutionMode.DEFERRED
    assert result.evidence.monitor_authority_established is False
    assert result.evidence.evaluation is None
    assert result.is_evaluated is False
    assert result.evidence.is_deferred_placeholder is True
    assert result.evidence.result_status is ResultStatus.UNSUPPORTED
    assert "deferred_routing_cannot_substitute_for_monitor_evaluation" in (
        result.evidence.diagnostics
    )
    assert "deferred_unknown_is_only_explicit_unsupported_or_unavailable" in (
        result.evidence.diagnostics
    )
    # Clock/event-time still bound even without evaluation.
    assert result.evidence.bindings_complete() is True
    assert result.evidence.semantics.clock_id == "clock:main"


def test_mode_deferred_without_flag_still_rejects() -> None:
    result = RuntimeMTLExecutionEngineV2().execute(
        _always_safe_request(
            mode=RuntimeMTLExecutionMode.DEFERRED,
            deferred=False,
            request_id="req:deferred:mode-only",
        )
    )
    assert result.disposition is RuntimeMTLDisposition.DEFERRED_REJECTED
    assert result.evidence.monitor_authority_established is False


@pytest.mark.parametrize("claim", list(RuntimeMTLClaimKind))
def test_non_authoritative_signals_never_establish_claims(
    claim: RuntimeMTLClaimKind,
) -> None:
    assert (
        non_authoritative_signal_establishes(
            claim,
            mock_output={"verdict": "true", "status": "satisfied"},
            fallback_output={"verdict": "true"},
            deferred=True,
            available=True,
            confidence=1.0,
            fluent_text="This monitor clearly proves the property.",
        )
        is False
    )
    assert (
        deferred_or_mock_establishes_monitor(
            mock_output={"verdict": "true"},
            deferred=True,
            available=True,
        )
        is False
    )


def test_mock_output_rejected_and_never_establishes_monitor() -> None:
    result = execute_runtime_mtl(
        _unary("always", _atom("safe")),
        _trace("finite", [_event(0, "safe")]),
        request_id="req:mock:1",
        mock_output={
            "verdict": "true",
            "status": "satisfied",
            "authorizes_global_proof": True,
            "proved": True,
        },
        confidence=1.0,
        available=True,
        fluent_text="Mock says satisfied and proved.",
    )
    assert result.disposition is RuntimeMTLDisposition.MOCK_REJECTED
    assert result.monitor_established is False
    assert result.evidence.mock_output_present is True
    assert result.evidence.mode is RuntimeMTLExecutionMode.MOCK
    assert result.evidence.evaluation is None
    assert result.evidence.result_status is ResultStatus.UNKNOWN
    assert "mock_output_cannot_establish_monitor" in result.evidence.diagnostics
    wire = result.evidence.to_dict()
    assert wire["claim_monitor"] is False
    assert wire["claim_proof"] is False
    assert wire["is_proved"] is False
    for claim in RuntimeMTLClaimKind:
        assert result.evidence.non_authoritative_claim(claim) is False
        assert result.evidence.claim_established(claim) is False


def test_fallback_output_rejected() -> None:
    result = execute_runtime_mtl(
        _unary("always", _atom("safe")),
        _trace("finite", [_event(0, "safe")]),
        request_id="req:fallback:1",
        fallback_output={"verdict": "true", "reason": "monitor missing"},
        available=False,
    )
    assert result.disposition is RuntimeMTLDisposition.FALLBACK_REJECTED
    assert result.evidence.fallback_output_present is True
    assert result.evidence.mode is RuntimeMTLExecutionMode.FALLBACK
    assert result.evidence.monitor_authority_established is False


def test_unavailable_external_is_explicit() -> None:
    result = execute_runtime_mtl(
        _unary("always", _atom("safe")),
        _trace("finite", [_event(0, "safe")]),
        request_id="req:unavailable:external",
        provider=RuntimeMTLProviderKind.RUNTIME_MTL_EXTERNAL,
        available=False,
    )
    assert result.disposition is RuntimeMTLDisposition.UNAVAILABLE
    assert result.evidence.result_status is ResultStatus.UNAVAILABLE
    assert result.evidence.mode is RuntimeMTLExecutionMode.UNAVAILABLE
    assert result.evidence.monitor_authority_established is False
    assert result.is_evaluated is False
    assert "unavailable_is_explicit_non_evaluation_outcome" in (
        result.evidence.diagnostics
    )


def test_mode_unavailable_is_explicit() -> None:
    result = RuntimeMTLExecutionEngineV2().execute(
        _always_safe_request(
            mode=RuntimeMTLExecutionMode.UNAVAILABLE,
            request_id="req:unavailable:mode",
        )
    )
    assert result.disposition is RuntimeMTLDisposition.UNAVAILABLE
    assert result.evidence.result_status is ResultStatus.UNAVAILABLE
    assert result.evidence.monitor_authority_established is False


# ---------------------------------------------------------------------------
# Authority fail-closed
# ---------------------------------------------------------------------------


def test_evidence_rejects_proof_authority() -> None:
    base = execute_runtime_mtl(
        _unary("always", _atom("safe")),
        _trace("finite", [_event(0, "safe"), _event(1, "safe")]),
        request_id="req:authority:base",
    )
    with pytest.raises(RuntimeMTLAuthorityError):
        RuntimeMTLEvidenceV2(
            evidence_id="ev:bad:proof",
            request_id=base.request.request_id,
            request_digest=base.evidence.request_digest,
            provider=RuntimeMTLProviderKind.RUNTIME_MTL,
            disposition=RuntimeMTLDisposition.SATISFIED,
            mode=RuntimeMTLExecutionMode.NATIVE_MONITOR,
            formula_digest=base.evidence.formula_digest,
            trace_digest=base.evidence.trace_digest,
            semantics=base.evidence.semantics.to_dict(),
            evaluation=base.evidence.evaluation,
            result_status=ResultStatus.PROVED,
            monitor_authority_established=True,
        )


def test_evidence_rejects_monitor_authority_under_mock_mode() -> None:
    base = execute_runtime_mtl(
        _unary("always", _atom("safe")),
        _trace("finite", [_event(0, "safe")]),
        request_id="req:authority:mock-base",
    )
    with pytest.raises(RuntimeMTLAuthorityError):
        RuntimeMTLEvidenceV2(
            evidence_id="ev:bad:mock-auth",
            request_id=base.request.request_id,
            request_digest=base.evidence.request_digest,
            provider=RuntimeMTLProviderKind.RUNTIME_MTL,
            disposition=RuntimeMTLDisposition.SATISFIED,
            mode=RuntimeMTLExecutionMode.MOCK,
            formula_digest=base.evidence.formula_digest,
            trace_digest=base.evidence.trace_digest,
            semantics=base.evidence.semantics.to_dict(),
            evaluation=base.evidence.evaluation,
            result_status=ResultStatus.SATISFIED,
            monitor_authority_established=True,
            mock_output_present=True,
        )


def test_monitor_result_typed_surface() -> None:
    result = execute_runtime_mtl(
        _unary("always", _atom("safe")),
        _trace("finite", [_event(0, "safe"), _event(1, "safe")]),
        request_id="req:typed:monitor-result",
    )
    assert result.monitor_result is not None
    assert result.monitor_result.authority is ResultAuthority.MONITOR
    assert result.monitor_result.status is ResultStatus.SATISFIED
    assert result.monitor_result.translation_ceiling.value == "bounded"
    wire = result.monitor_result.to_dict()
    assert wire["authority"] == "monitor"
    assert wire["result_type"] == "monitor"


def test_formula_object_path() -> None:
    formula = always(Formula.atom("safe"))
    result = execute_runtime_mtl(
        formula,
        _trace("finite", [_event(0, "safe"), _event(1, "safe")]),
        request_id="req:formula-obj",
    )
    assert result.disposition is RuntimeMTLDisposition.SATISFIED
    assert result.evidence.formula_digest
    # Rebuilding from formula object still replays.
    assert result.evidence.replay is not None
    assert result.evidence.replay.matched is True


def test_eventually_on_complete_trace() -> None:
    formula = eventually(Formula.atom("done"))
    result = execute_runtime_mtl(
        formula,
        _trace(
            "finite",
            [_event(0, "safe"), _event(1, "done")],
        ),
        request_id="req:eventually",
    )
    assert result.disposition is RuntimeMTLDisposition.SATISFIED
    assert result.evidence.semantics.three_valued_verdict is Verdict.TRUE
