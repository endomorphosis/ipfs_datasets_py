"""Integration contract for TLA+/TLC/Apalache state-model checking (LFV-G044).

Covers:

* deterministic, source-mapped TLA generation from state IR;
* concurrency, rely/guarantee, and refinement projections with loss disclosure;
* distinct TLC vs Apalache capabilities and bound disclosures;
* counterexample parse and source-map replay;
* liveness/fairness limitation disclosure;
* absent JVM/tools return unavailable (never a silent pass).
"""

from __future__ import annotations

import pytest

from ipfs_datasets_py.logic.backends.process import (
    BoundedToolRunner,
    RawProcessResult,
)
from ipfs_datasets_py.logic.backends.results import ResultAuthority, ResultStatus
from ipfs_datasets_py.logic.backends.tla.compiler import (
    TLA_BACKEND_VERSION,
    GeneratedTLAArtifacts,
    ProjectionKind,
    TLACompileBounds,
    TLACompiler,
    TLACompilerError,
)
from ipfs_datasets_py.logic.backends.tla.runners import (
    APALACHE_BACKEND_VERSION,
    APALACHE_CAPABILITY,
    TLC_BACKEND_VERSION,
    TLC_CAPABILITY,
    ApalacheBackend,
    ModelCheckerTool,
    ModelCheckOutcomeStatus,
    TLCBackend,
    TLABackend,
    parse_counterexample_trace,
    replay_counterexample,
)
from ipfs_datasets_py.logic.families.models import EvidenceAuthority
from ipfs_datasets_py.logic.ir_core.claims import FrozenMap
from ipfs_datasets_py.logic.ir_core.protocols import (
    BackendRequest,
    ExecutionBounds,
    QueryKind,
)
from ipfs_datasets_py.logic.software_verification.concurrency import (
    ComponentKind,
    ConcurrencyIR,
    ConcurrentComponent,
    ConcurrentStep,
    InterferenceAssumption,
    InterferenceKind,
    RelyGuaranteeContract,
    StepOwner,
)
from ipfs_datasets_py.logic.software_verification.refinement import (
    RefinementIR,
    RefinementState,
    RefinementSystem,
    RefinementTransition,
    SystemLevel,
)
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


def _concurrency_document() -> ConcurrencyIR:
    steps = (
        ConcurrentStep(
            "step:a",
            StepOwner.COMPONENT,
            "a-step",
            guard_statement="true",
            effect_statement="pc_a := done",
            component_id="comp:a",
            read_variable_ids=("var:shared",),
            write_variable_ids=("var:shared",),
        ),
        ConcurrentStep(
            "step:b",
            StepOwner.COMPONENT,
            "b-step",
            guard_statement="true",
            effect_statement="pc_b := done",
            component_id="comp:b",
            read_variable_ids=("var:shared",),
            write_variable_ids=("var:shared",),
        ),
        ConcurrentStep(
            "step:env",
            StepOwner.ENVIRONMENT,
            "env",
            guard_statement="true",
            effect_statement="may observe shared",
            read_variable_ids=("var:shared",),
        ),
    )
    return ConcurrencyIR(
        components=(
            ConcurrentComponent(
                "comp:a", ComponentKind.THREAD, "A", step_ids=("step:a",)
            ),
            ConcurrentComponent(
                "comp:b", ComponentKind.THREAD, "B", step_ids=("step:b",)
            ),
        ),
        steps=steps,
        shared_variable_ids=("var:shared",),
        interference=(
            InterferenceAssumption(
                "intf:env",
                InterferenceKind.READ,
                "Environment may observe shared state.",
                subject_component_id="comp:a",
                interferer_is_environment=True,
                shared_variable_ids=("var:shared",),
            ),
        ),
        rely_guarantee=(
            RelyGuaranteeContract(
                "rg:a",
                "comp:a",
                rely_statement="shared stays well typed",
                guarantee_statement="a only writes its own effects",
                shared_variable_ids=("var:shared",),
                interference_ids=("intf:env",),
            ),
        ),
        require_interference=True,
    )


def _refinement_document() -> RefinementIR:
    abstract = RefinementSystem(
        "sys:abstract",
        SystemLevel.ABSTRACT,
        "Abstract",
        states=(
            RefinementState("st:a0", "a0", is_initial=True),
            RefinementState("st:a1", "a1", is_terminal=True),
        ),
        transitions=(
            RefinementTransition(
                "tr:a0-a1",
                "st:a0",
                "st:a1",
                "step",
            ),
        ),
    )
    concrete = RefinementSystem(
        "sys:concrete",
        SystemLevel.CONCRETE,
        "Concrete",
        states=(
            RefinementState("st:c0", "c0", is_initial=True),
            RefinementState("st:c1", "c1"),
            RefinementState("st:c2", "c2", is_terminal=True),
        ),
        transitions=(
            RefinementTransition("tr:c0-c1", "st:c0", "st:c1", "micro1"),
            RefinementTransition("tr:c1-c2", "st:c1", "st:c2", "micro2"),
        ),
    )
    return RefinementIR(systems=(abstract, concrete))


def _process_runner(
    stdout: str,
    *,
    returncode: int | None = 0,
    timed_out: bool = False,
    unavailable: bool = False,
    output_truncated: bool = False,
    stderr: str = "",
    error: str = "",
) -> tuple[BoundedToolRunner, list[object]]:
    invocations: list[object] = []

    def execute(invocation, _cancellation):
        invocations.append(invocation)
        return RawProcessResult(
            returncode=None if unavailable else returncode,
            stdout="" if unavailable else stdout,
            stderr="" if unavailable else stderr,
            elapsed_seconds=0.012,
            timed_out=timed_out,
            output_truncated=output_truncated,
            process_tree_terminated=timed_out,
            error=error or ("executable not found" if unavailable else ""),
        )

    return BoundedToolRunner(executor=execute), invocations


def _request(**payload: object) -> BackendRequest:
    return BackendRequest(
        request_id="request:tla:test",
        claim_id="claim:tla:test",
        declaration_id="declaration:tla:test",
        claim_digest="1" * 64,
        obligation_id="obligation:tla:test",
        obligation_digest="2" * 64,
        assumption_ids=("assumption:reviewed",),
        logic_family="state_transition",
        query_kind=QueryKind.SATISFIABILITY,
        bounds=ExecutionBounds(timeout_ms=250, max_steps=32),
        payload=FrozenMap(payload),
        requested_backend_id="tlc",
    )


def test_compiler_is_deterministic_and_source_mapped():
    compiler = TLACompiler(bounds=TLACompileBounds(max_steps=8))
    document = _counter_document()
    first = compiler.compile(document, module_name="Counter")
    second = compiler.compile(document, module_name="Counter")

    assert first.interface_version == TLA_BACKEND_VERSION
    assert first.model_text == second.model_text
    assert first.tlc_config_text == second.tlc_config_text
    assert first.apalache_config_text == second.apalache_config_text
    assert first.model_digest == second.model_digest
    assert first.artifact_digest == second.artifact_digest
    assert first.model_text.endswith("\n")
    assert "---- MODULE Counter ----" in first.model_text
    assert f"source_document_id: {document.document_id}" in first.model_text
    assert first.source_map
    mapped_sources = {entry.source_id for entry in first.source_map}
    assert "var:pc" in mapped_sources
    assert "action:inc" in mapped_sources
    assert "pred:init" in mapped_sources
    assert "TypeOK" in first.safety_properties
    assert "BoundedProgress" in first.liveness_properties
    assert first.fairness_limitations
    assert first.bounded is True
    assert first.unbounded_proof is False


def test_state_concurrency_rely_guarantee_refinement_disclose_losses():
    compiler = TLACompiler(bounds=TLACompileBounds(max_steps=6))

    state_art = compiler.compile_state(_counter_document(), module_name="S")
    assert any(loss.projection is ProjectionKind.STATE for loss in state_art.losses)
    assert any("MaxSteps" in loss.statement or "finite" in loss.statement.lower() for loss in state_art.losses)

    conc_art = compiler.compile_concurrency(
        _concurrency_document(), module_name="C"
    )
    assert conc_art.source_kind == "concurrency_ir"
    conc_kinds = {loss.projection for loss in conc_art.losses}
    assert ProjectionKind.CONCURRENCY in conc_kinds
    assert any(
        "interleaving" in loss.construct or "interleaving" in loss.statement
        for loss in conc_art.losses
    )
    assert any(
        loss.projection is ProjectionKind.RELY_GUARANTEE for loss in conc_art.losses
    )

    rg = RelyGuaranteeContract(
        "rg:solo",
        "comp:solo",
        rely_statement="environment is well behaved",
        guarantee_statement="system preserves invariant",
        shared_variable_ids=("var:shared",),
    )
    rg_art = compiler.compile_rely_guarantee(rg, module_name="RG")
    assert rg_art.source_kind == "rely_guarantee"
    assert any(
        loss.projection is ProjectionKind.RELY_GUARANTEE for loss in rg_art.losses
    )
    assert any("rely" in loss.construct for loss in rg_art.losses)

    ref_art = compiler.compile_refinement(
        _refinement_document(), module_name="R", prefer="concrete"
    )
    assert ref_art.source_kind == "refinement_ir"
    assert any(
        loss.projection is ProjectionKind.REFINEMENT for loss in ref_art.losses
    )
    assert any("simulation" in loss.construct for loss in ref_art.losses)
    # concrete states appear in the domain
    assert "st:c0" in ref_art.model_text or '"st:c0"' in ref_art.model_text


def test_tlc_and_apalache_capabilities_and_bounds_differ():
    assert TLC_CAPABILITY.checks_liveness is True
    assert TLC_CAPABILITY.checks_fairness is True
    assert TLC_CAPABILITY.finite_trace_only is False
    assert APALACHE_CAPABILITY.checks_liveness is False
    assert APALACHE_CAPABILITY.checks_fairness is False
    assert APALACHE_CAPABILITY.finite_trace_only is True
    assert TLC_CAPABILITY.max_declared_steps != APALACHE_CAPABILITY.max_declared_steps
    assert TLC_BACKEND_VERSION != APALACHE_BACKEND_VERSION

    facade = TLABackend()
    caps = facade.capabilities()
    assert caps["tlc"]["checks_liveness"] is True
    assert caps["apalache"]["checks_liveness"] is False
    assert "liveness" in " ".join(caps["apalache"]["limitations"]).lower()


def test_tlc_config_includes_liveness_apalache_does_not():
    artifacts = TLACompiler().compile(_counter_document(), module_name="Cfg")
    assert "SPECIFICATION Spec" in artifacts.tlc_config_text
    assert "PROPERTY" in artifacts.tlc_config_text
    assert "BoundedProgress" in artifacts.tlc_config_text
    assert "INVARIANT Safety" in artifacts.apalache_config_text
    assert "PROPERTY" not in artifacts.apalache_config_text
    assert artifacts.configuration_for("tlc") == artifacts.tlc_config_text
    assert artifacts.configuration_for("apalache") == artifacts.apalache_config_text


def test_counterexample_parse_and_replay():
    raw = (
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
    trace = parse_counterexample_trace(raw)
    assert len(trace.states) == 2
    assert trace.states[0].assignments["pc"] == '"idle"'
    assert trace.states[1].assignments["count"] == "1"

    artifacts = TLACompiler().compile(_counter_document(), module_name="Counter")
    replayed = replay_counterexample(trace, artifacts.source_map)
    assert replayed.replayed is True
    assert replayed.replay_notes
    assert any("replayed mapped symbols" in note for note in replayed.replay_notes)


def test_tlc_passed_run_is_bounded_model_check_not_theorem():
    runner, invocations = _process_runner(
        "Model checking completed. No error has been found.\n"
    )
    backend = TLCBackend(
        runner=runner,
        which=lambda name: "/usr/bin/tlc" if name in {"tlc", "tlc2"} else None,
        jvm_probe=lambda: True,
    )
    artifacts = TLACompiler(bounds=TLACompileBounds(max_steps=4)).compile(
        _counter_document(), module_name="Counter"
    )
    outcome = backend.check(artifacts, request=_request(module_name="Counter"))

    assert outcome.result.authority is ResultAuthority.MODEL_CHECK
    assert outcome.result.status is ResultStatus.SATISFIED
    assert outcome.result.translation_ceiling is EvidenceAuthority.BOUNDED
    assert outcome.receipt.status is ModelCheckOutcomeStatus.PASSED
    assert outcome.receipt.bounded is True
    assert outcome.receipt.unbounded_proof is False
    assert "TypeOK" in outcome.receipt.checked_safety_properties
    assert "BoundedProgress" in outcome.receipt.checked_liveness_properties
    assert outcome.receipt.fairness_limitations
    assert invocations
    # checker was invoked on the generated module path
    assert any(str(arg).endswith(".tla") for arg in invocations[0].argv)


def test_apalache_does_not_claim_liveness_and_passes_on_safety_markers():
    runner, invocations = _process_runner(
        "Checker reports no error\nNo error up to computation length 4\n"
    )
    backend = ApalacheBackend(
        runner=runner,
        which=lambda name: (
            "/usr/bin/apalache-mc" if name in {"apalache-mc", "apalache"} else None
        ),
        jvm_probe=lambda: True,
    )
    artifacts = TLACompiler(bounds=TLACompileBounds(max_steps=4)).compile(
        _counter_document(), module_name="Counter"
    )
    outcome = backend.check(artifacts)

    assert outcome.result.status is ResultStatus.SATISFIED
    assert outcome.receipt.checked_liveness_properties == ()
    assert outcome.receipt.capability.checks_liveness is False
    assert any(
        "liveness" in item.lower() for item in outcome.receipt.fairness_limitations
    )
    assert any("--length=" in arg for arg in outcome.receipt.command)
    assert invocations


def test_counterexample_status_parses_and_replays_via_tlc():
    stdout = (
        "Error: Invariant Safety is violated.\n"
        "The following behavior constitutes a counter-example:\n"
        "State 1: <Initial predicate>\n"
        "/\\ pc = \"idle\"\n"
        "/\\ count = 0\n"
        "State 2: <Next>\n"
        "/\\ pc = \"busy\"\n"
        "/\\ count = 4\n"
    )
    runner, _ = _process_runner(stdout, returncode=12)
    backend = TLCBackend(
        runner=runner,
        which=lambda name: "/usr/bin/tlc" if name == "tlc" else None,
        jvm_probe=lambda: True,
    )
    artifacts = TLACompiler().compile(_counter_document(), module_name="Counter")
    outcome = backend.check(artifacts)

    assert outcome.result.status is ResultStatus.VIOLATED
    assert outcome.receipt.status is ModelCheckOutcomeStatus.COUNTEREXAMPLE
    assert outcome.receipt.counterexample is not None
    assert outcome.receipt.counterexample.replayed is True
    assert outcome.receipt.counterexample.states
    assert "counterexample" in outcome.result.witness.to_dict()


def test_absent_jvm_or_tools_return_unavailable():
    runner, invocations = _process_runner("", unavailable=True)
    no_tool = TLCBackend(
        runner=runner,
        which=lambda _name: None,
        jvm_probe=lambda: True,
    )
    artifacts = TLACompiler().compile(_counter_document(), module_name="Counter")
    outcome = no_tool.check(artifacts)
    assert outcome.result.status is ResultStatus.UNAVAILABLE
    assert outcome.receipt.status is ModelCheckOutcomeStatus.UNAVAILABLE
    assert outcome.receipt.checked_safety_properties == ()
    assert outcome.receipt.checked_liveness_properties == ()
    assert "unavailable" in outcome.receipt.reason.lower()
    assert invocations == []  # never launched

    no_jvm = ApalacheBackend(
        runner=runner,
        which=lambda name: "/usr/bin/apalache-mc" if "apalache" in name else None,
        jvm_probe=lambda: False,
    )
    outcome_jvm = no_jvm.check(artifacts)
    assert outcome_jvm.result.status is ResultStatus.UNAVAILABLE
    assert outcome_jvm.receipt.jvm_available is False
    assert "jvm" in outcome_jvm.receipt.reason.lower()


def test_facade_routes_tools_and_compile_and_check():
    tlc_runner, tlc_inv = _process_runner(
        "Model checking completed. No error has been found.\n"
    )
    apalache_runner, apa_inv = _process_runner(
        "Checker reports no error\n"
    )
    facade = TLABackend(
        tlc=TLCBackend(
            runner=tlc_runner,
            which=lambda name: "/bin/tlc" if name == "tlc" else None,
            jvm_probe=lambda: True,
        ),
        apalache=ApalacheBackend(
            runner=apalache_runner,
            which=lambda name: "/bin/apalache-mc" if "apalache" in name else None,
            jvm_probe=lambda: True,
        ),
    )
    document = _counter_document()
    artifacts = facade.compile(document, module_name="Facade")
    assert isinstance(artifacts, GeneratedTLAArtifacts)

    tlc_out = facade.check(artifacts, tool=ModelCheckerTool.TLC)
    apa_out = facade.check(artifacts, tool="apalache")
    assert tlc_out.receipt.tool is ModelCheckerTool.TLC
    assert apa_out.receipt.tool is ModelCheckerTool.APALACHE
    assert tlc_inv and apa_inv


def test_timeout_and_unknown_are_non_conclusive():
    timeout_runner, _ = _process_runner("", timed_out=True, returncode=None)
    backend = TLCBackend(
        runner=timeout_runner,
        which=lambda name: "/bin/tlc" if name == "tlc" else None,
        jvm_probe=lambda: True,
    )
    artifacts = TLACompiler().compile(_counter_document(), module_name="T")
    outcome = backend.check(artifacts)
    assert outcome.result.status is ResultStatus.TIMEOUT
    assert outcome.receipt.status is ModelCheckOutcomeStatus.TIMED_OUT

    unknown_runner, _ = _process_runner("some unrecognised chatter\n", returncode=0)
    backend2 = TLCBackend(
        runner=unknown_runner,
        which=lambda name: "/bin/tlc" if name == "tlc" else None,
        jvm_probe=lambda: True,
    )
    outcome2 = backend2.check(artifacts)
    assert outcome2.result.status is ResultStatus.UNKNOWN


def test_compile_rejects_oversized_schema():
    compiler = TLACompiler(bounds=TLACompileBounds(max_variables=1, max_steps=2))
    with pytest.raises(TLACompilerError, match="max_variables"):
        compiler.compile(_counter_document())
