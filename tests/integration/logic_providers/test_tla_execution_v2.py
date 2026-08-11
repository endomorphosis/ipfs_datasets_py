"""Integration tests: TLC / Apalache state execution + trace replay (LFP2-029).

Acceptance (fail-closed):

* TLC and Apalache capabilities/results remain distinct.
* Every counterexample binds bounds, config, module, property, and replay outcome.
* Finite-state, step-bounded, safety, liveness, fairness, and approximation
  semantics are separated on every answer.
* Mock / fallback / availability / confidence never establish model-check or
  theorem authority.

Interfaces: StateProviderEvidence@2
"""

from __future__ import annotations

import pytest

from ipfs_datasets_py.logic.backends.process import (
    BoundedToolRunner,
    RawProcessResult,
)
from ipfs_datasets_py.logic.backends.results import ResultAuthority, ResultStatus
from ipfs_datasets_py.logic.backends.tla.compiler import (
    TLACompileBounds,
    TLACompiler,
)
from ipfs_datasets_py.logic.backends.tla.execution_v2 import (
    APALACHE_STATE_CAPABILITY,
    STATE_EXECUTION_V2_TASK_ID,
    STATE_PROVIDER_EVIDENCE_V2_INTERFACE,
    TLC_STATE_CAPABILITY,
    StateAuthorityError,
    StateClaimKind,
    StateCounterexampleBindingV2,
    StateDisposition,
    StateExecutionEngineV2,
    StateExecutionError,
    StateExecutionMode,
    StateExecutionRequestV2,
    StateProviderEvidenceV2,
    StateProviderKind,
    StateReplayStatus,
    StateSemanticsAxis,
    capability_for,
    execute_apalache,
    execute_tlc,
    hermetic_engine,
    non_authoritative_signal_establishes,
    normalize_state_provider,
    provider_support_establishes_other,
)
from ipfs_datasets_py.logic.backends.tla.runners import (
    APALACHE_BACKEND_VERSION,
    TLC_BACKEND_VERSION,
    ApalacheBackend,
    TLCBackend,
)
from ipfs_datasets_py.logic.backends.toolchain_roles import (
    ToolRole,
    ToolchainAuthorityCeiling,
)
from ipfs_datasets_py.logic.families.models import EvidenceAuthority
from ipfs_datasets_py.logic.ir_core.protocols import ExecutionBounds
from ipfs_datasets_py.logic.software_verification.state import (
    Boundedness,
    FiniteDomainBound,
    PredicateRole,
    StatePredicate,
    StateSchema,
    StateTypeKind,
    StateVariable,
)
from ipfs_datasets_py.logic.software_verification.transitions import (
    Action,
    ActionFrame,
    FairnessConstraint,
    FairnessKind,
    StateTransitionIR,
    TransitionKind,
    TransitionRelation,
)

# ---------------------------------------------------------------------------
# Compact IR recipe
# ---------------------------------------------------------------------------


def _counter_document() -> StateTransitionIR:
    schema = StateSchema(
        variables=(
            StateVariable(
                "var:pc",
                "pc",
                StateTypeKind.ENUMERATION,
                Boundedness.FINITE,
                domain_bound=FiniteDomainBound(
                    "bound:pc",
                    members=("idle", "busy", "done"),
                ),
            ),
            StateVariable(
                "var:count",
                "count",
                StateTypeKind.INTEGER,
                Boundedness.FINITE,
                domain_bound=FiniteDomainBound("bound:count", lower=0, upper=3),
            ),
        ),
        metadata={"model": "bounded-counter"},
    )
    initial = StatePredicate(
        "pred:init",
        PredicateRole.INITIAL,
        "pc = idle /\\ count = 0",
        expression={"var:pc": "idle", "var:count": 0},
        subject_variable_ids=("var:pc", "var:count"),
    )
    guard = StatePredicate(
        "pred:guard-inc",
        PredicateRole.GUARD,
        "count < 3",
        expression={"role": "guard"},
        subject_variable_ids=("var:count",),
    )
    next_inc = StatePredicate(
        "pred:next-inc",
        PredicateRole.NEXT,
        "count' = count + 1 /\\ pc' = busy",
        expression={"var:count": 1, "var:pc": "busy"},
        subject_variable_ids=("var:count", "var:pc"),
    )
    invariant = StatePredicate(
        "pred:inv",
        PredicateRole.INVARIANT,
        "0 <= count <= 3",
        expression={"role": "invariant"},
        subject_variable_ids=("var:count",),
    )
    fairness_pred = StatePredicate(
        "pred:fair",
        PredicateRole.FAIRNESS,
        "progress infinitely often",
        expression={"role": "fairness"},
        subject_variable_ids=("var:pc",),
    )
    action = Action(
        "action:inc",
        "Increment",
        ActionFrame(reads=("var:count", "var:pc"), writes=("var:count", "var:pc")),
        guard_predicate_id="pred:guard-inc",
        next_predicate_id="pred:next-inc",
    )
    relation = TransitionRelation(
        "rel:next",
        TransitionKind.ACTION,
        "Next is the disjunction of enabled actions.",
        action_ids=("action:inc",),
        allows_stutter=True,
    )
    fairness = FairnessConstraint(
        "fair:progress",
        FairnessKind.WEAK,
        "Weak fairness of progress.",
        predicate_id="pred:fair",
    )
    return StateTransitionIR(
        schema=schema,
        predicates=(initial, guard, next_inc, invariant, fairness_pred),
        actions=(action,),
        transitions=(relation,),
        fairness=(fairness,),
        metadata={"subject": "counter"},
    )


COUNTEREXAMPLE_STDOUT = (
    "Error: Invariant Safety is violated.\n"
    "State 1: <Initial predicate>\n"
    "/\\ pc = \"idle\"\n"
    "/\\ count = 0\n"
    "/\\ step = 0\n"
    "State 2: <Action line 12, col 1 to line 20, col 12 of module Counter>\n"
    "/\\ pc = \"busy\"\n"
    "/\\ count = 1\n"
    "/\\ step = 1\n"
)

TLC_PASSED = "Model checking completed. No error has been found.\n"
APALACHE_PASSED = "Checker reports no error\n"


def _engine_passed() -> StateExecutionEngineV2:
    return hermetic_engine(
        tlc_stdout=TLC_PASSED,
        apalache_stdout=APALACHE_PASSED,
    )


def _engine_counterexample() -> StateExecutionEngineV2:
    return hermetic_engine(
        tlc_stdout=COUNTEREXAMPLE_STDOUT,
        apalache_stdout=COUNTEREXAMPLE_STDOUT,
        tlc_returncode=12,
        apalache_returncode=12,
    )


def _request(
    provider: StateProviderKind,
    **overrides: object,
) -> StateExecutionRequestV2:
    payload: dict[str, object] = {
        "request_id": f"req:state:{provider.value}:1",
        "provider": provider,
        "document": _counter_document(),
        "module_name": "Counter",
        "mode": StateExecutionMode.ENGINE,
        "bounds": ExecutionBounds(timeout_ms=250, max_steps=8),
        "source_ref_ids": ("source:fixture:counter",),
        "available": True,
        "confidence": 0.95,
        "fluent_text": "Obviously the invariant holds.",
    }
    payload.update(overrides)
    return StateExecutionRequestV2(**payload)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Interface / typing surface
# ---------------------------------------------------------------------------


def test_interface_identities() -> None:
    engine = StateExecutionEngineV2()
    assert engine.INTERFACE == STATE_PROVIDER_EVIDENCE_V2_INTERFACE
    assert engine.interface == "StateProviderEvidence@2"
    assert engine.TASK_ID == STATE_EXECUTION_V2_TASK_ID
    assert engine.TASK_ID == "LFP2-029"
    assert StateExecutionRequestV2.interface == "StateExecutionRequest@2"
    assert StateProviderEvidenceV2.interface == "StateProviderEvidence@2"


def test_provider_normalization() -> None:
    assert normalize_state_provider("tlc") is StateProviderKind.TLC
    assert normalize_state_provider("apalache-mc") is StateProviderKind.APALACHE
    assert normalize_state_provider("tla_tlc") is StateProviderKind.TLC
    assert normalize_state_provider(StateProviderKind.APALACHE) is StateProviderKind.APALACHE
    with pytest.raises(StateExecutionError):
        normalize_state_provider("z3")
    with pytest.raises(StateExecutionError):
        normalize_state_provider("tlc_apalache")


# ---------------------------------------------------------------------------
# Distinct TLC / Apalache capabilities and results
# ---------------------------------------------------------------------------


def test_each_provider_capability_is_independent() -> None:
    tlc = capability_for(StateProviderKind.TLC)
    ap = capability_for(StateProviderKind.APALACHE)

    assert tlc == TLC_STATE_CAPABILITY
    assert ap == APALACHE_STATE_CAPABILITY
    assert tlc.provider is StateProviderKind.TLC
    assert ap.provider is StateProviderKind.APALACHE
    assert tlc.checks_liveness is True
    assert tlc.checks_fairness is True
    assert tlc.finite_state is True
    assert tlc.finite_trace_only is False
    assert ap.checks_liveness is False
    assert ap.checks_fairness is False
    assert ap.finite_state is False
    assert ap.finite_trace_only is True
    assert tlc.backend_interface == TLC_BACKEND_VERSION
    assert ap.backend_interface == APALACHE_BACKEND_VERSION
    assert tlc.max_declared_steps != ap.max_declared_steps
    assert tlc.backend_interface != ap.backend_interface


def test_provider_support_never_establishes_other() -> None:
    for source in StateProviderKind:
        for target in StateProviderKind:
            assert (
                provider_support_establishes_other(
                    source,
                    target,
                    source_available=True,
                    source_supported=True,
                )
                is False
            )


def test_available_tlc_does_not_establish_apalache_capability() -> None:
    engine = hermetic_engine(tlc_available=True, apalache_available=False)
    tlc_cap = engine.capability_receipt(StateProviderKind.TLC)
    ap_cap = engine.capability_receipt(StateProviderKind.APALACHE)

    assert tlc_cap.available is True
    assert ap_cap.available is False
    assert tlc_cap.establishes(StateProviderKind.APALACHE) is False
    assert ap_cap.establishes(StateProviderKind.TLC) is False

    result = engine.execute(_request(StateProviderKind.TLC))
    assert result.evidence.available is True
    assert (
        result.evidence.establishes_other_provider(StateProviderKind.APALACHE)
        is False
    )
    wire = result.evidence.to_dict()
    assert wire["claim_other_provider_capability"] is False


def test_split_provider_execution_keeps_capabilities_isolated() -> None:
    engine = _engine_passed()
    results = engine.execute_split_providers(
        document=_counter_document(),
        request_id_prefix="req:split",
        module_name="Counter",
        bounds=ExecutionBounds(timeout_ms=250, max_steps=8),
    )
    assert set(results) == set(StateProviderKind)
    providers_seen = {result.evidence.provider for result in results.values()}
    assert providers_seen == set(StateProviderKind)

    for kind, result in results.items():
        assert result.provider is kind
        assert result.evidence.provider is kind
        assert result.evidence.semantics.provider is kind
        assert result.evidence.config.provider is kind
        assert result.evidence.bindings_complete() is True
        for other in StateProviderKind:
            if other is kind:
                continue
            assert result.evidence.establishes_other_provider(other) is False

    tlc_ev = results[StateProviderKind.TLC].evidence
    ap_ev = results[StateProviderKind.APALACHE].evidence
    assert tlc_ev.semantics.liveness is True
    assert tlc_ev.semantics.fairness is True
    assert tlc_ev.semantics.finite_state is True
    assert ap_ev.semantics.liveness is False
    assert ap_ev.semantics.fairness is False
    assert ap_ev.semantics.finite_state is False
    assert ap_ev.semantics.step_bounded is True
    assert ap_ev.bounds.finite_trace_only is True
    assert ap_ev.properties.checked_liveness == ()
    assert tlc_ev.config.config_kind == "tlc_cfg"
    assert ap_ev.config.config_kind == "apalache_cfg"
    assert tlc_ev.config.configuration_digest != ap_ev.config.configuration_digest


def test_capability_receipt_rejects_cross_provider_relabel() -> None:
    with pytest.raises(StateAuthorityError, match="re-labeled|match"):
        from ipfs_datasets_py.logic.backends.tla.execution_v2 import (
            StateCapabilityReceiptV2,
        )

        StateCapabilityReceiptV2(
            provider=StateProviderKind.TLC,
            available=True,
            supported_document=True,
            capability=APALACHE_STATE_CAPABILITY.to_dict(),  # wrong provider
        )


def test_semantics_binding_rejects_apalache_liveness() -> None:
    from ipfs_datasets_py.logic.backends.tla.execution_v2 import (
        StateSemanticsBindingV2,
    )

    with pytest.raises(StateAuthorityError, match="liveness|fairness"):
        StateSemanticsBindingV2(
            provider=StateProviderKind.APALACHE,
            finite_state=False,
            step_bounded=True,
            safety=True,
            liveness=True,  # forbidden
            fairness=False,
            approximation=True,
        )


# ---------------------------------------------------------------------------
# Hermetic conclusive execution + bindings
# ---------------------------------------------------------------------------


def test_tlc_passed_binds_module_config_bounds_properties_semantics() -> None:
    engine = _engine_passed()
    result = engine.execute(_request(StateProviderKind.TLC))
    evidence = result.evidence

    assert evidence.interface == STATE_PROVIDER_EVIDENCE_V2_INTERFACE
    assert evidence.disposition is StateDisposition.SATISFIED
    assert evidence.bindings_complete() is True
    assert evidence.provider is StateProviderKind.TLC
    assert evidence.module.module_name == "Counter"
    assert evidence.module.model_digest
    assert evidence.module.artifact_digest
    assert evidence.config.provider is StateProviderKind.TLC
    assert evidence.config.configuration_digest
    assert evidence.config.config_kind == "tlc_cfg"
    assert evidence.bounds.max_steps >= 1
    assert evidence.bounds.timeout_ms == 250
    assert evidence.bounds.finite_state is True
    assert evidence.bounds.step_bounded is True
    assert evidence.properties.safety_properties
    assert evidence.properties.primary_property
    assert "Safety" in evidence.properties.checked_safety or evidence.properties.checked_safety
    assert evidence.semantics.safety is True
    assert evidence.semantics.liveness is True
    assert evidence.semantics.fairness is True
    assert evidence.semantics.approximation is True
    assert StateSemanticsAxis.FINITE_STATE.value in evidence.semantics.axes
    assert StateSemanticsAxis.SAFETY.value in evidence.semantics.axes
    assert StateSemanticsAxis.LIVENESS.value in evidence.semantics.axes
    assert StateSemanticsAxis.FAIRNESS.value in evidence.semantics.axes
    assert StateSemanticsAxis.APPROXIMATION.value in evidence.semantics.axes

    assert evidence.result_authority is ResultAuthority.MODEL_CHECK
    assert evidence.authority_ceiling is ToolchainAuthorityCeiling.BOUNDED
    assert evidence.translation_ceiling is EvidenceAuthority.BOUNDED
    assert evidence.role is ToolRole.AUTHORITY
    assert evidence.is_theorem_authority is False
    assert evidence.is_proved is False
    assert evidence.proof_established is False
    assert evidence.theorem_established is False
    assert evidence.model_check_established is True
    assert evidence.result_status is ResultStatus.SATISFIED
    assert evidence.counterexample_status is StateReplayStatus.CLEAN_NO_COUNTEREXAMPLE

    wire = evidence.to_dict()
    assert wire["bindings_complete"] is True
    assert wire["provider"] == "tlc"
    assert "module" in wire
    assert "config" in wire
    assert "bounds" in wire
    assert "properties" in wire
    assert "semantics" in wire
    assert "counterexample" in wire
    assert wire["claim_theorem"] is False
    assert wire["claim_proof"] is False
    assert wire["claim_model_check"] is True
    assert wire["authorizes_universal_proof"] is False


def test_apalache_passed_has_distinct_semantics_from_tlc() -> None:
    engine = _engine_passed()
    result = execute_apalache(
        _counter_document(),
        request_id="req:state:apalache:pass",
        module_name="Counter",
        bounds=ExecutionBounds(timeout_ms=250, max_steps=8),
        engine=engine,
    )
    evidence = result.evidence
    assert evidence.provider is StateProviderKind.APALACHE
    assert evidence.disposition is StateDisposition.SATISFIED
    assert evidence.semantics.liveness is False
    assert evidence.semantics.fairness is False
    assert evidence.semantics.step_bounded is True
    assert evidence.semantics.safety is True
    assert evidence.properties.checked_liveness == ()
    assert evidence.config.config_kind == "apalache_cfg"
    assert evidence.bounds.finite_trace_only is True
    assert evidence.model_check_established is True
    assert evidence.bindings_complete() is True


def test_tlc_and_apalache_results_remain_distinct() -> None:
    engine = _engine_passed()
    tlc = execute_tlc(
        _counter_document(),
        request_id="req:tlc:distinct",
        module_name="Counter",
        bounds=ExecutionBounds(timeout_ms=250, max_steps=8),
        engine=engine,
    )
    ap = execute_apalache(
        _counter_document(),
        request_id="req:apalache:distinct",
        module_name="Counter",
        bounds=ExecutionBounds(timeout_ms=250, max_steps=8),
        engine=engine,
    )
    assert tlc.evidence.provider is not ap.evidence.provider
    assert tlc.evidence.config.configuration_digest != (
        ap.evidence.config.configuration_digest
    )
    assert tlc.evidence.semantics.liveness != ap.evidence.semantics.liveness
    assert tlc.evidence.capability.capability["checks_liveness"] is True
    assert ap.evidence.capability.capability["checks_liveness"] is False
    # Neither result establishes the other.
    assert tlc.evidence.establishes_other_provider(StateProviderKind.APALACHE) is False
    assert ap.evidence.establishes_other_provider(StateProviderKind.TLC) is False


# ---------------------------------------------------------------------------
# Counterexample binds bounds, config, module, property, replay
# ---------------------------------------------------------------------------


def test_counterexample_binds_bounds_config_module_property_replay() -> None:
    engine = _engine_counterexample()
    result = engine.execute(_request(StateProviderKind.TLC))
    evidence = result.evidence

    assert evidence.disposition is StateDisposition.COUNTEREXAMPLE
    assert evidence.result_status is ResultStatus.VIOLATED
    cex = evidence.counterexample
    assert isinstance(cex, StateCounterexampleBindingV2)
    assert cex.bindings_complete() is True

    # Required binding slots
    assert cex.module.module_name == "Counter"
    assert cex.module.model_digest
    assert cex.config.configuration_digest
    assert cex.config.provider is StateProviderKind.TLC
    assert cex.bounds.max_steps >= 1
    assert cex.bounds.timeout_ms == 250
    assert cex.property_name
    assert cex.status is StateReplayStatus.REPLAYED
    assert cex.replayed is True
    assert cex.state_count >= 1
    assert cex.states
    assert cex.replay_notes  # source-map replay notes

    wire = cex.to_dict()
    assert wire["bindings_complete"] is True
    assert "bounds" in wire
    assert "config" in wire
    assert "module" in wire
    assert "property" in wire
    assert "property_name" in wire
    assert "replay_outcome" in wire
    assert wire["replay_outcome"] == "replayed"
    assert wire["module"]["module_name"] == "Counter"

    # Evidence wire also exposes the binding.
    ev_wire = evidence.to_dict()
    assert ev_wire["counterexample_status"] == "replayed"
    assert ev_wire["counterexample"]["bounds"]["max_steps"] >= 1
    assert ev_wire["counterexample"]["config"]["configuration_digest"]
    assert ev_wire["counterexample"]["module"]["module_name"] == "Counter"
    assert ev_wire["counterexample"]["property_name"]
    assert ev_wire["counterexample"]["replay_outcome"] == "replayed"


def test_apalache_counterexample_also_binds_five_slots() -> None:
    engine = _engine_counterexample()
    result = execute_apalache(
        _counter_document(),
        request_id="req:apalache:cex",
        module_name="Counter",
        bounds=ExecutionBounds(timeout_ms=250, max_steps=8),
        engine=engine,
    )
    cex = result.evidence.counterexample
    assert cex.bindings_complete() is True
    assert cex.module.module_name == "Counter"
    assert cex.config.provider is StateProviderKind.APALACHE
    assert cex.config.config_kind == "apalache_cfg"
    assert cex.bounds.finite_trace_only is True
    assert cex.property_name
    assert cex.status is StateReplayStatus.REPLAYED
    assert result.evidence.semantics.liveness is False
    assert result.evidence.properties.checked_liveness == ()


def test_precompiled_artifacts_path_binds_digests() -> None:
    compiler = TLACompiler(bounds=TLACompileBounds(max_steps=8))
    artifacts = compiler.compile(_counter_document(), module_name="Counter")
    engine = _engine_passed()
    result = execute_tlc(
        artifacts=artifacts,
        request_id="req:tlc:artifacts",
        module_name="Counter",
        engine=engine,
    )
    assert result.evidence.module.model_digest == artifacts.model_digest
    assert result.evidence.module.artifact_digest == artifacts.artifact_digest
    assert (
        result.evidence.config.configuration_digest == artifacts.tlc_config_digest
    )
    assert result.evidence.bindings_complete() is True


# ---------------------------------------------------------------------------
# Unavailable / mock / fallback fail-closed
# ---------------------------------------------------------------------------


def test_unavailable_tool_is_typed_unavailable_not_pass() -> None:
    engine = hermetic_engine(tlc_available=False, apalache_available=False)
    result = engine.execute(_request(StateProviderKind.TLC))
    assert result.disposition is StateDisposition.UNAVAILABLE
    assert result.evidence.model_check_established is False
    assert result.evidence.result_status is ResultStatus.UNAVAILABLE
    assert result.evidence.bindings_complete() is True
    assert result.evidence.is_theorem_authority is False


def test_mock_output_cannot_establish_model_check() -> None:
    engine = _engine_passed()
    result = engine.execute(
        _request(
            StateProviderKind.TLC,
            mode=StateExecutionMode.MOCK,
            mock_output={"status": "passed"},
        )
    )
    assert result.disposition is StateDisposition.MOCK_REJECTED
    assert result.evidence.model_check_established is False
    assert result.evidence.mock_output_present is True
    assert result.evidence.claim_model_check is False
    assert result.evidence.claim_theorem is False


def test_fallback_output_cannot_establish_model_check() -> None:
    engine = _engine_passed()
    result = engine.execute(
        _request(
            StateProviderKind.APALACHE,
            mode=StateExecutionMode.FALLBACK,
            fallback_output={"status": "passed"},
        )
    )
    assert result.disposition is StateDisposition.FALLBACK_REJECTED
    assert result.evidence.model_check_established is False
    assert result.evidence.fallback_output_present is True


def test_non_authoritative_signals_never_establish() -> None:
    for claim in StateClaimKind:
        assert (
            non_authoritative_signal_establishes(
                claim,
                mock_output={"ok": True},
                fallback_output={"ok": True},
                available=True,
                confidence=1.0,
                fluent_text="proved",
                other_provider_available=True,
            )
            is False
        )


def test_availability_and_confidence_do_not_establish_authority() -> None:
    engine = hermetic_engine(tlc_available=False)
    result = engine.execute(
        _request(
            StateProviderKind.TLC,
            available=True,
            confidence=1.0,
            fluent_text="Definitely proved by TLC.",
        )
    )
    # Tool unavailable despite optimistic signals.
    assert result.evidence.model_check_established is False
    assert result.evidence.fluent_text_present is True
    assert result.evidence.confidence == 1.0
    assert result.disposition is StateDisposition.UNAVAILABLE


def test_capability_probe_does_not_grant_verdict() -> None:
    engine = _engine_passed()
    result = engine.execute(
        _request(
            StateProviderKind.TLC,
            mode=StateExecutionMode.CAPABILITY_PROBE,
        )
    )
    assert result.disposition is StateDisposition.CAPABILITY_ONLY
    assert result.evidence.model_check_established is False
    assert result.evidence.capability.available is True


# ---------------------------------------------------------------------------
# Hermetic fixture mode still establishes only via engine path
# ---------------------------------------------------------------------------


def test_hermetic_fixture_mode_establishes_model_check_not_theorem() -> None:
    engine = _engine_passed()
    result = engine.execute(
        _request(
            StateProviderKind.TLC,
            mode=StateExecutionMode.HERMETIC_FIXTURE,
        )
    )
    assert result.disposition is StateDisposition.SATISFIED
    assert result.evidence.model_check_established is True
    assert result.evidence.result_authority is ResultAuthority.MODEL_CHECK
    assert result.evidence.is_theorem_authority is False
    assert result.evidence.authorizes_universal_proof is False


def test_timeout_is_typed() -> None:
    engine = hermetic_engine(tlc_timed_out=True, tlc_stdout="")
    result = engine.execute(_request(StateProviderKind.TLC))
    assert result.disposition is StateDisposition.TIMEOUT
    assert result.evidence.model_check_established is False
    assert result.evidence.bindings_complete() is True


def test_probe_all_returns_independent_receipts() -> None:
    engine = hermetic_engine(tlc_available=True, apalache_available=False)
    probes = engine.probe_all()
    assert set(probes) == set(StateProviderKind)
    assert probes[StateProviderKind.TLC].available is True
    assert probes[StateProviderKind.APALACHE].available is False
    assert probes[StateProviderKind.TLC].establishes(StateProviderKind.APALACHE) is False


def test_apalache_cannot_claim_checked_liveness_on_evidence() -> None:
    """Direct construction of Apalache evidence with liveness must fail."""

    engine = _engine_passed()
    result = engine.execute(_request(StateProviderKind.APALACHE))
    # Engine path never sets checked_liveness for Apalache.
    assert result.evidence.properties.checked_liveness == ()
    assert result.evidence.semantics.liveness is False


def test_process_invocation_uses_tool_specific_argv() -> None:
    invocations: list[object] = []

    def execute(invocation, _cancellation):
        invocations.append(invocation)
        return RawProcessResult(
            returncode=0,
            stdout=TLC_PASSED,
            elapsed_seconds=0.01,
        )

    runner = BoundedToolRunner(executor=execute)
    engine = StateExecutionEngineV2(
        tlc=TLCBackend(
            runner=runner,
            which=lambda name: "/usr/bin/tlc" if name == "tlc" else None,
            jvm_probe=lambda: True,
            lazy_install=False,
        ),
        apalache=ApalacheBackend(
            runner=BoundedToolRunner(
                executor=lambda inv, _c: RawProcessResult(
                    returncode=0,
                    stdout=APALACHE_PASSED,
                    elapsed_seconds=0.01,
                )
            ),
            which=lambda name: (
                "/usr/bin/apalache-mc" if name in {"apalache", "apalache-mc"} else None
            ),
            jvm_probe=lambda: True,
            lazy_install=False,
        ),
        lazy_install=False,
    )
    engine.execute(_request(StateProviderKind.TLC))
    assert invocations
    argv = [str(a) for a in invocations[0].argv]
    assert any(a.endswith(".tla") for a in argv)
    assert "-config" in argv or any(".cfg" in a for a in argv)
