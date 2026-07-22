"""Tests for staged, budgeted Legal IR proof routing."""

from __future__ import annotations

import threading

from ipfs_datasets_py.logic.integration.reasoning.hammer import (
    CallableHammerBackendRunner,
    HammerBackendResult,
    HammerBackendStatus,
    HammerGoal,
    HammerPipeline,
    HammerPremise,
    HammerVerification,
)
from ipfs_datasets_py.logic.integration.reasoning.legal_ir_obligations import (
    LegalIRProofObligation,
)
from ipfs_datasets_py.logic.integration.reasoning.legal_ir_proof_router import (
    LEGAL_IR_PROOF_ROUTER_SCHEMA_VERSION,
    LegalIRProofRouter,
    ProofRouteOutcome,
    ProofRouteStage,
    ProofRouteStatus,
    ProofRoutingPolicy,
    ProofTrustLevel,
)


def _obligation(**metadata):
    return LegalIRProofObligation(
        obligation_id="obligation-1",
        statement="well_formed_formula(f1)",
        kind="modal_well_formedness",
        legal_ir_view="TDFOL.prover",
        logic_family="temporal",
        sample_id="sample-1",
        formula_id="f1",
        metadata=metadata,
    )


def _goal(obligation):
    return HammerGoal(
        statement=obligation.statement,
        name=obligation.obligation_id,
        metadata={"logic_family": obligation.logic_family},
    )


def _premises():
    return [HammerPremise("well_formed", "well_formed_formula(f1)")]


def _proved_backend(calls=None):
    def run(translation, timeout_seconds):
        if calls is not None:
            calls.append(("smt_atp_portfolio", timeout_seconds))
        return HammerBackendResult(
            backend="z3",
            status=HammerBackendStatus.PROVED,
            proved=True,
            elapsed_seconds=0.01,
            translation_format=translation.target_format,
            proof_trace="unsat",
        )

    return CallableHammerBackendRunner("z3", "smt-lib", run)


def test_cheap_proof_stops_and_records_every_skipped_route() -> None:
    calls = []

    def syntax(request):
        calls.append(request.route)
        return ProofRouteOutcome(
            ProofRouteStatus.PROVED,
            ProofTrustLevel.DETERMINISTIC,
            reason="canonical syntax theorem",
        )

    router = LegalIRProofRouter(
        HammerPipeline(backends=[_proved_backend(calls)]),
        policy=ProofRoutingPolicy(required_trust="deterministic"),
        route_runners={"deterministic_syntax": syntax},
    )
    obligation = _obligation()
    result = router.route(obligation, _goal(obligation), _premises())

    assert result.trust_satisfied
    assert result.stop_reason == "required_trust_obtained"
    assert calls == ["deterministic_syntax"]
    assert len(result.attempts) == 7
    assert result.attempts[0].status == ProofRouteStatus.PROVED
    assert all(item.status == ProofRouteStatus.SKIPPED for item in result.attempts[1:])
    assert set(result.skipped_routes) == {
        "deterministic_graph",
        "deterministic_contract",
        "native_tdfol",
        "native_cec",
        "smt_atp_portfolio",
        "native_lean_reconstruction",
    }


def test_kernel_policy_runs_portfolio_then_native_lean_in_cost_order() -> None:
    backend_calls = []
    verifier_calls = []

    def verifier(itp, script, goal, premises):
        verifier_calls.append((itp, goal.name, len(premises)))
        return HammerVerification(verified=True, checker="lean-kernel", elapsed_seconds=0.02)

    router = LegalIRProofRouter(
        HammerPipeline(
            backends=[_proved_backend(backend_calls)],
            kernel_verifier=verifier,
        ),
        policy=ProofRoutingPolicy(
            required_trust="kernel",
            total_timeout_seconds=5,
            stage_timeout_seconds={
                ProofRouteStage.DETERMINISTIC: 0.2,
                ProofRouteStage.NATIVE_LOGIC: 0.4,
                ProofRouteStage.SMT_ATP: 1.5,
                ProofRouteStage.LEAN_RECONSTRUCTION: 2.0,
            },
        ),
    )
    obligation = _obligation()
    result = router.route(obligation, _goal(obligation), _premises())

    executed = [item.route for item in result.attempts if item.executed]
    assert executed == [
        "deterministic_syntax",
        "native_tdfol",
        "smt_atp_portfolio",
        "native_lean_reconstruction",
    ]
    assert result.status == ProofRouteStatus.PROVED
    assert result.trust_level == ProofTrustLevel.KERNEL
    assert result.hammer_result.reconstruction.verified
    assert verifier_calls == [("lean", "obligation-1", 1)]
    assert 0 < backend_calls[0][1] <= 1.5


def test_native_tdfol_result_avoids_external_portfolio() -> None:
    backend_calls = []
    obligation = _obligation(native_tdfol_result={"status": "proved"})
    result = LegalIRProofRouter(
        HammerPipeline(backends=[_proved_backend(backend_calls)]),
        policy=ProofRoutingPolicy(required_trust="native"),
    ).route(obligation, _goal(obligation), _premises())

    assert result.trust_satisfied
    assert result.trust_level == ProofTrustLevel.NATIVE
    assert backend_calls == []
    native = next(item for item in result.attempts if item.route == "native_tdfol")
    assert native.status == ProofRouteStatus.PROVED
    assert next(
        item for item in result.attempts if item.route == "smt_atp_portfolio"
    ).skip_reason == "required_trust_obtained"


def test_canonical_graph_check_matches_the_source_graph_payload() -> None:
    obligation = LegalIRProofObligation(
        obligation_id="graph-1",
        statement="kg_edge_typed(subject:f1, predicate:actor, object:agency)",
        kind="knowledge_graph_edge_typing",
        legal_ir_view="knowledge_graphs.neo4j_compat",
        logic_family="frame",
        metadata={"triple_index": 1},
    )
    sample = {
        "frame_logic": {
            "triples": [{"subject": "f1", "predicate": "actor", "object": "agency"}]
        }
    }
    result = LegalIRProofRouter(
        HammerPipeline(backends=[]),
        policy=ProofRoutingPolicy(required_trust="deterministic"),
    ).route(obligation, _goal(obligation), _premises(), sample_or_document=sample)

    graph = next(item for item in result.attempts if item.route == "deterministic_graph")
    assert graph.status == ProofRouteStatus.PROVED
    assert result.trust_satisfied


def test_explicit_contract_check_can_discharge_before_native_or_solver() -> None:
    obligation = LegalIRProofObligation(
        obligation_id="contract-1",
        statement="contract_required_field_present(contract:c1, field:operator)",
        kind="deontic_required_fields",
        legal_ir_view="deontic.ir",
        logic_family="deontic",
        metadata={
            "contract_id": "c1",
            "contract_view": "deontic",
            "coverage_scope": "required_field",
            "deterministic_contract_valid": True,
        },
    )
    result = LegalIRProofRouter(
        HammerPipeline(backends=[]),
        policy=ProofRoutingPolicy(required_trust="deterministic"),
    ).route(obligation, _goal(obligation), _premises())

    contract = next(item for item in result.attempts if item.route == "deterministic_contract")
    assert contract.status == ProofRouteStatus.PROVED
    assert result.trust_satisfied


def test_unsupported_translation_is_not_reported_as_failed_theorem() -> None:
    router = LegalIRProofRouter(
        HammerPipeline(backends=[]),
        policy=ProofRoutingPolicy(
            enabled_routes=("native_tdfol",),
            required_trust="native",
        ),
    )
    obligation = _obligation()
    result = router.route(obligation, _goal(obligation), _premises())

    assert result.status == ProofRouteStatus.UNSUPPORTED_TRANSLATION
    native = next(item for item in result.attempts if item.route == "native_tdfol")
    assert native.status == ProofRouteStatus.UNSUPPORTED_TRANSLATION
    assert "formula_not_available" in native.reason
    assert result.hammer_result.status.value == "translation_failed"


def test_portfolio_failure_preserves_bounded_backend_diagnostics() -> None:
    def unavailable_backend(translation, timeout_seconds):
        return HammerBackendResult(
            backend="cvc5",
            status=HammerBackendStatus.ERROR,
            proved=False,
            elapsed_seconds=0.01,
            translation_format=translation.target_format,
            error="OSError: Exec format error",
        )

    router = LegalIRProofRouter(
        HammerPipeline(
            backends=[CallableHammerBackendRunner("cvc5", "smt-lib", unavailable_backend)]
        ),
        policy=ProofRoutingPolicy(
            enabled_routes=("smt_atp_portfolio",),
            required_trust="backend",
        ),
    )
    obligation = _obligation()
    result = router.route(obligation, _goal(obligation), _premises())
    attempt = next(
        item for item in result.attempts if item.route == "smt_atp_portfolio"
    )

    assert attempt.status == ProofRouteStatus.UNKNOWN
    assert attempt.metadata["hammer_status"] == "unproved"
    assert attempt.metadata["backend_results"] == [
        {
            "backend": "cvc5",
            "error": "OSError: Exec format error",
            "status": "error",
            "timed_out": False,
        }
    ]


def test_deterministic_counterexample_stops_as_theorem_failure() -> None:
    obligation = _obligation(deterministic_syntax_valid=False)
    result = LegalIRProofRouter(HammerPipeline(backends=[])).route(
        obligation, _goal(obligation), _premises()
    )

    assert result.status == ProofRouteStatus.THEOREM_FAILED
    assert result.stop_reason == "conclusive_theorem_failure"
    assert result.attempts[0].status == ProofRouteStatus.THEOREM_FAILED
    assert result.attempts[1].skip_reason == "conclusive_theorem_failure"


def test_expired_stage_result_is_cancelled_by_its_budget() -> None:
    class Clock:
        now = 0.0

        def __call__(self):
            return self.now

    clock = Clock()

    def slow_syntax(request):
        assert request.timeout_seconds == 0.1
        clock.now += 0.11
        return {"status": "proved", "trust": "deterministic"}

    policy = ProofRoutingPolicy(
        required_trust="deterministic",
        total_timeout_seconds=1,
        stage_timeout_seconds={
            ProofRouteStage.DETERMINISTIC: 0.1,
            ProofRouteStage.NATIVE_LOGIC: 0.2,
            ProofRouteStage.SMT_ATP: 0.3,
            ProofRouteStage.LEAN_RECONSTRUCTION: 0.4,
        },
        enabled_routes=("deterministic_syntax",),
    )
    obligation = _obligation()
    result = LegalIRProofRouter(
        HammerPipeline(backends=[]),
        policy=policy,
        route_runners={"deterministic_syntax": slow_syntax},
        clock=clock,
    ).route(obligation, _goal(obligation), _premises())

    attempt = result.attempts[0]
    assert attempt.status == ProofRouteStatus.TIMEOUT
    assert attempt.cancellation_reason == "stage_deadline_exhausted"
    assert not result.trust_satisfied


def test_pre_cancelled_request_records_cancellation_for_all_routes() -> None:
    cancelled = threading.Event()
    cancelled.set()
    obligation = _obligation()
    result = LegalIRProofRouter(HammerPipeline(backends=[])).route(
        obligation,
        _goal(obligation),
        _premises(),
        cancellation_event=cancelled,
    )

    assert result.status == ProofRouteStatus.CANCELLED
    assert len(result.attempts) == 7
    assert all(item.status == ProofRouteStatus.CANCELLED for item in result.attempts)
    assert set(result.cancellation_reasons) == {"caller_cancelled"}
    assert result.to_dict()["schema_version"] == LEGAL_IR_PROOF_ROUTER_SCHEMA_VERSION
