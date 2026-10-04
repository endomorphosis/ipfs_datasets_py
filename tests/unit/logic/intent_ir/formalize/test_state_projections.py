"""Abstract workflow scope, native TLA rendering, and explicit tool boundaries."""
from dataclasses import replace
from copy import deepcopy
import sys

import pytest

from ipfs_datasets_py.logic.intent_ir.formalize import state_projections as sut
from ipfs_datasets_py.logic.intent_ir.formalize.projection_contracts import validate_projection, source_ir_sha256
from ipfs_datasets_py.logic.intent_ir.formalize.roundtrip import frame_to_intent_ir
from ipfs_datasets_py.logic.intent_ir.schema import (
    ControlEdgeKind, IntentControlEdge, IntentKind, NodeGrounding, StatementKind)
from ipfs_datasets_py.logic.software_verification.transitions import StateTransitionIR
from ipfs_datasets_py.logic.backends.tla.compiler import TLACompiler
from ipfs_datasets_py.logic.backends.process import BoundedToolRunner, RawProcessResult


def document(modality="required"):
    return frame_to_intent_ir({"actor": "agent", "action": "inspect", "object": "cache", "modality": modality},
                             instruction=f"agent {modality} inspect cache")


def chain():
    first = document()
    second = replace(first.actions[0], action_id="second", verb="update")
    edge = IntentControlEdge("next", "action", "second", ControlEdgeKind.NEXT,
                             source_ref_ids=("source",), grounding=NodeGrounding.INFERRED)
    return replace(first, intent_kind=IntentKind.PROCEDURE, actions=(*first.actions, second),
                   control_edges=(edge,), terminal_action_ids=("second",))


def test_default_projection_is_pure_source_bound_partial_abstraction(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("default projection must not run an external process")
    monkeypatch.setattr(BoundedToolRunner, "run", forbidden)
    source = document()
    reports = sut.project_state_families(source)
    assert [(r["family_id"], r["profile_id"]) for r in reports] == [
        ("transition_system", None), ("transition_system", "tla_plus")]
    for report in reports:
        validate_projection(report, source)
        assert report["status"] == "partial"
        assert report["semantics"] == "abstract_intent_control_flow"
        assert report["proof_authority"] is report["execution_authority"] is False
        assert {r["node_id"] for r in report["unsupported"]} == {"goal", "action"}
    assert reports[1]["validation"][-1]["status"] == "not_run"


def test_native_state_has_explicit_guard_effect_domains_and_done_self_loop():
    report = sut.project_state_families(chain(), {"state": {"max_steps": 4}})[0]
    state = StateTransitionIR.from_dict(report["representation"]["payload"])
    assert state.schema.variable_ids == ("var:pc",)
    assert state.schema.variables[0].domain_bound.members == ("position_0", "position_1", "done")
    assert len(state.actions) == 3
    assert any(a.action_id == "action:done" and a.enables_stutter for a in state.actions)
    assert all(a.guard_predicate_id and a.next_predicate_id for a in state.actions)
    assert all(a.frame.reads == a.frame.writes == ("var:pc",) for a in state.actions)
    assert state.metadata["code_effects_modeled"] is False


def test_native_compiler_artifact_name_matches_declared_header_regression():
    state = StateTransitionIR.from_dict(sut.project_state_families(document())[0]["representation"]["payload"])
    compiled = TLACompiler().compile(state, module_name="ChosenIntentModel")
    assert compiled.module_name == "ChosenIntentModel"
    assert compiled.model_text.startswith("---- MODULE ChosenIntentModel ----\n")
    assert "TypeOK" in compiled.safety_properties
    # A future disagreement must fail rather than silently select another file.
    with pytest.raises(ValueError, match="module name differs"):
        sut._qualification_artifacts(replace(compiled, module_name="TypeOK"))


def test_qualification_wrapper_preserves_native_artifact_and_checks_deadlocks():
    report = sut.project_state_families(document())[1]
    native = report["representation"]["payload"]
    qualifier = report["representation"]["qualification"]
    assert "PROPERTY BoundedProgress" in native["tlc_config_text"]
    assert qualifier["excluded_liveness_properties"] == ["BoundedProgress"]
    assert "PROPERTY" not in qualifier["tlc_config_text"]
    assert "CHECK_DEADLOCK TRUE" in qualifier["tlc_config_text"]
    assert "BudgetStutter ==" in qualifier["model_text"]
    assert qualifier["model_text"].startswith(native["model_text"][:-5])
    assert qualifier["native_model_digest"] == native["model_digest"]


@pytest.mark.parametrize("kind", [ControlEdgeKind.PARALLEL, ControlEdgeKind.RETRY,
    ControlEdgeKind.CONDITIONAL, ControlEdgeKind.ON_SUCCESS, ControlEdgeKind.ON_FAILURE, ControlEdgeKind.JOIN])
def test_non_next_control_semantics_fail_closed(kind):
    source = chain()
    source = replace(source, control_edges=(replace(source.control_edges[0], kind=kind),))
    reports = sut.project_state_families(source)
    assert all(r["status"] == "unsupported" and r["representation"]["payload"] is None for r in reports)
    assert all(any(r["node_id"] == "next" for r in p["unsupported"]) for p in reports)


def test_unbound_action_preconditions_fail_closed():
    source = document()
    condition = replace(source.statements[0], statement_id="ready", kind=StatementKind.PRECONDITION)
    source = replace(source, statements=(*source.statements, condition),
                     actions=(replace(source.actions[0], precondition_ids=("ready",)),))
    reports = sut.project_state_families(source)
    assert all(r["status"] == "unsupported" for r in reports)
    assert reports[0]["unsupported"][0]["reason"] == "action_preconditions_have_no_reviewed_state_binding"


def test_disconnected_actions_and_short_budget_do_not_imply_completed_workflow():
    source = chain()
    disconnected = replace(source, control_edges=())
    assert all(p["status"] == "unsupported" for p in sut.project_state_families(disconnected))
    short = sut.project_state_families(source, {"state": {"max_steps": 1}})
    assert all(p["status"] == "unsupported" for p in short)
    assert short[0]["unsupported"][0]["reason"] == "step_budget_does_not_cover_the_declared_workflow"


@pytest.mark.parametrize("options", [{"max_steps": True}, {"max_steps": 0}, {"max_steps": 257},
                                   {"abstraction": "real_code_behavior"}, {"proof": True}])
def test_state_context_is_closed_and_bounded(options):
    with pytest.raises(ValueError):
        sut.project_state_families(document(), {"state": options})


def test_prohibition_and_source_operators_are_never_execution_authority():
    source = document("prohibited")
    source = replace(source, actions=(replace(source.actions[0], verb="Injected == TRUE\n===="),))
    report = sut.project_state_families(source)[1]
    assert report["status"] == "partial"
    assert "Injected" not in report["representation"]["qualification"]["model_text"]
    assert report["execution_authority"] is False
    assert any("modality_not_encoded" in r["reason"] for r in report["unsupported"])


def test_forged_model_rejected_before_external_run(tmp_path):
    source = document()
    report = sut.project_state_families(source)[1]
    report["representation"]["qualification"]["model_text"] += "malicious changes"
    class NeverRun:
        def run(self, *args, **kwargs):
            raise AssertionError("forged projection reached subprocess boundary")
    with pytest.raises(ValueError, match="exact native source replay"):
        sut.validate_tla_projection(report, tmp_path / "absent.jar", document=source, runner=NeverRun())


def test_missing_explicit_tool_is_unavailable_not_passed(tmp_path):
    source = document()
    report = sut.project_state_families(source)[1]
    result = sut.validate_tla_projection(report, tmp_path / "absent.jar", document=source)
    assert result["status"] == "unavailable" and result["runs"] == []
    assert result["projection_sha256"] == report["projection_sha256"]
    assert result["source_ir_sha256"] == report["source_ir_sha256"]
    assert result["proof_authority"] is False


def test_sany_zero_exit_with_parse_errors_fails_and_stops_before_tlc(tmp_path):
    calls = []
    def execute(invocation, cancellation):
        calls.append(invocation)
        assert (invocation.cwd / "IntentControlFlow.tla").is_file()
        return RawProcessResult(returncode=0, stdout="Semantic processing of module IntentControlFlow\n*** Errors: 1\n")
    jar = tmp_path / "test.jar"
    jar.write_bytes(b"inert test fixture; injected executor")
    source = document()
    report = sut.project_state_families(source)[1]
    result = sut.validate_tla_projection(report, jar, document=source, java_executable=sys.executable,
        run_model_checker=True, runner=BoundedToolRunner(executor=execute))
    assert result["status"] == "failed" and len(calls) == 1
    assert result["runs"][0]["result"]["workspace_cleaned"] is True
    assert not calls[0].cwd.exists()


def test_explicit_tool_receipt_contains_exact_source_config_and_no_proof_authority(tmp_path):
    def execute(invocation, cancellation):
        main = invocation.argv[4]
        text = ("Semantic processing of module IntentControlFlow\n" if main == "tla2sany.SANY"
                else "Model checking completed. No error has been found.\n")
        return RawProcessResult(returncode=0, stdout=text)
    jar = tmp_path / "test.jar"
    jar.write_bytes(b"inert test fixture; injected executor")
    source = document()
    report = sut.project_state_families(source)[1]
    result = sut.validate_tla_projection(report, jar, document=source, java_executable=sys.executable,
        run_model_checker=True, runner=BoundedToolRunner(executor=execute))
    assert result["status"] == "passed" and len(result["runs"]) == 2
    assert result["projection_sha256"] == report["projection_sha256"]
    assert result["source_ir_sha256"] == report["source_ir_sha256"]
    assert result["model_text"] == report["representation"]["qualification"]["model_text"]
    assert "CHECK_DEADLOCK TRUE" in result["tlc_config_text"]
    assert result["proof_authority"] is result["code_correctness_verified"] is result["unbounded_liveness_verified"] is False


def workflow_fixture(parallel=False, branch_length=1, branch_count=2):
    """Authored control-only evidence; no code or observed execution is implied."""
    base = document()
    actions = [base.actions[0]]
    edges, starts, tails = [], [], []
    for branch in range(branch_count):
        previous = "action"
        for step in range(branch_length):
            name = f"branch{branch}_{step}"
            actions.append(replace(base.actions[0], action_id=name, verb="inspect"))
            edge_id = f"edge{branch}_{step}"
            kind = ControlEdgeKind.PARALLEL if parallel and step == 0 else ControlEdgeKind.NEXT
            edges.append(IntentControlEdge(edge_id, previous, name, kind, source_ref_ids=("source",)))
            if step == 0:
                starts.append(edge_id)
            previous = name
        tail = f"join{branch}"
        edges.append(IntentControlEdge(tail, previous, "terminal",
            ControlEdgeKind.JOIN if parallel else ControlEdgeKind.NEXT, source_ref_ids=("source",)))
        tails.append(tail)
    actions.append(replace(base.actions[0], action_id="terminal", verb="validate"))
    source = replace(base, intent_kind=IntentKind.PROCEDURE, actions=tuple(actions),
                     control_edges=tuple(edges), terminal_action_ids=("terminal",))
    premise = {"semantics": "finite_single_use_token_flow", "source_ir_sha256": source_ir_sha256(source),
               "evidence_ref": "source", "choices": [], "fork_joins": []}
    if parallel:
        premise["fork_joins"] = [{"fork_action_id": "action", "join_action_id": "terminal",
            "parallel_edge_ids": starts, "join_edge_ids": tails,
            "semantics": "all_branches_then_join", "evidence_ref": "source"}]
    else:
        premise["choices"] = [{"source_action_id": "action", "edge_ids": starts,
            "semantics": "exclusive_nondeterministic", "evidence_ref": "source"}]
    return source, {"state": {"max_steps": len(actions), "workflow": premise}}


def _token_graph(source, context):
    report = sut.project_state_families(source, context)[0]
    assert report["status"] == "partial"
    state = StateTransitionIR.from_dict(report["representation"]["payload"])
    return report, state.metadata["token_graph"]


def test_explicit_exclusive_choice_explores_both_branches_without_combining_them():
    source, context = workflow_fixture()
    report, graph = _token_graph(source, context)
    assert report["semantics"] == "finite_single_use_token_flow"
    assert len(graph["configurations"]) == 7
    assert len(graph["transitions"]) == 8
    for state in graph["configurations"]:
        selected = set(state["active_action_ids"]) | set(state["completed_action_ids"])
        assert not {"branch0_0", "branch1_0"} <= selected
    finals = [r for r in graph["configurations"] if r["terminal"]]
    assert len(finals) == 2
    assert all(len(r["completed_action_ids"]) == 3 for r in finals)
    assert graph["premises_verified"] is graph["shared_memory_modeled"] is graph["fairness_assumed"] is False


def test_fork_join_enumerates_every_interleaving_and_never_activates_join_early():
    source, context = workflow_fixture(parallel=True, branch_length=2)
    report, graph = _token_graph(source, context)
    assert len(graph["configurations"]) == 11  # start + 3x3 branch progress + terminal completion
    assert any(set(r["active_action_ids"]) == {"branch0_0", "branch1_0"} for r in graph["configurations"])
    tails = {"branch0_1", "branch1_1"}
    for row in graph["configurations"]:
        if "terminal" in row["active_action_ids"] or row["terminal"]:
            assert tails <= set(row["completed_action_ids"])
        assert not set(row["active_action_ids"]) & set(row["completed_action_ids"])
    by_position = {r["position"]: r for r in graph["configurations"]}
    for edge in graph["transitions"]:
        before, after = by_position[edge["from_position"]], by_position[edge["to_position"]]
        if edge["intent_action_id"] is not None:
            assert set(after["completed_action_ids"]) - set(before["completed_action_ids"]) == {edge["intent_action_id"]}
    assert len([r for r in graph["configurations"] if r["terminal"]]) == 1
    assert report["execution_authority"] is False
    compiled = sut.project_state_families(source, context)[1]
    assert compiled["representation"]["qualification"]["model_text"].startswith("---- MODULE IntentControlFlow ----")
    assert not any("opaque" in r["construct"] for r in compiled["representation"]["payload"]["losses"])


@pytest.mark.parametrize("parallel", [False, True])
def test_nonlinear_workflow_still_requires_explicit_premises(parallel):
    source, context = workflow_fixture(parallel)
    assert all(r["status"] == "unsupported" for r in sut.project_state_families(source))
    context["state"]["workflow"]["choices" if not parallel else "fork_joins"] = []
    assert all(r["status"] == "unsupported" for r in sut.project_state_families(source, context))


@pytest.mark.parametrize("mutation", ["source", "evidence", "semantics", "extra", "group_edges", "group_evidence"])
def test_workflow_premises_are_closed_and_bound_to_exact_source(mutation):
    source, context = workflow_fixture()
    premise = context["state"]["workflow"]
    if mutation == "source": premise["source_ir_sha256"] = "0" * 64
    elif mutation == "evidence": premise["evidence_ref"] = "unknown"
    elif mutation == "semantics": premise["semantics"] = "implementation_execution"
    elif mutation == "extra": premise["proven"] = True
    elif mutation == "group_edges": premise["choices"][0]["edge_ids"] = ["join0", "join1"]
    else: premise["choices"][0]["evidence_ref"] = "unknown"
    with pytest.raises(ValueError):
        sut.project_state_families(source, context)


@pytest.mark.parametrize("kind", ["guard", "precondition", "outcome", "retry"])
def test_token_models_do_not_guess_conditions_or_outcomes(kind):
    source, context = workflow_fixture()
    condition = replace(source.statements[0], statement_id="condition", kind=StatementKind.GUARD)
    source = replace(source, statements=(*source.statements, condition))
    if kind == "precondition":
        source = replace(source, actions=(replace(source.actions[0], precondition_ids=("condition",)), *source.actions[1:]))
    else:
        edge = source.control_edges[0]
        change = {"guard_statement_id": "condition"} if kind == "guard" else {
            "kind": ControlEdgeKind.ON_SUCCESS if kind == "outcome" else ControlEdgeKind.RETRY}
        source = replace(source, control_edges=(replace(edge, **change), *source.control_edges[1:]))
    context["state"]["workflow"]["source_ir_sha256"] = source_ir_sha256(source)
    reports = sut.project_state_families(source, context)
    assert all(r["status"] == "unsupported" and r["representation"]["payload"] is None for r in reports)


def test_mismatched_join_and_overlapping_branch_interiors_fail_closed():
    source, context = workflow_fixture(parallel=True)
    malformed = deepcopy(context)
    malformed["state"]["workflow"]["fork_joins"][0]["join_action_id"] = "branch0_0"
    with pytest.raises(ValueError, match="exactly bind"):
        sut.project_state_families(source, malformed)
    # A duplicate branch entry would collapse two obligations into one token.
    changed = list(source.control_edges)
    changed[2] = replace(changed[2], target_action_id="branch0_0")
    source = replace(source, control_edges=tuple(changed))
    context["state"]["workflow"]["source_ir_sha256"] = source_ir_sha256(source)
    assert all(r["status"] == "unsupported" for r in sut.project_state_families(source, context))


def test_configuration_explosion_and_short_budget_reject_instead_of_truncating():
    source, context = workflow_fixture(parallel=True, branch_length=3, branch_count=4)
    report = sut.project_state_families(source, context)[0]
    assert report["status"] == "unsupported" and report["representation"]["payload"] is None
    assert "bound_exceeded" in report["unsupported"][0]["reason"]
    source, context = workflow_fixture(parallel=True)
    context["state"]["max_steps"] = 2
    report = sut.project_state_families(source, context)[0]
    assert report["status"] == "unsupported"
    assert report["unsupported"][0]["reason"] == "step_budget_does_not_cover_the_declared_workflow"


def test_token_projection_is_canonical_under_set_like_ir_ordering():
    source, context = workflow_fixture(parallel=True, branch_length=2)
    permuted = replace(source, actions=tuple(reversed(source.actions)), control_edges=tuple(reversed(source.control_edges)))
    assert sut.project_state_families(source, context) == sut.project_state_families(permuted, context)


def test_changed_token_semantics_or_source_cannot_reuse_qualification(tmp_path):
    source, context = workflow_fixture(parallel=True)
    report = sut.project_state_families(source, context)[1]
    report["representation"]["configuration_map"][1]["active_action_ids"] = ["terminal"]
    with pytest.raises(ValueError, match="exact native source replay"):
        sut.validate_tla_projection(report, tmp_path / "absent.jar", document=source, context=context)


def test_token_qualification_receipt_discloses_its_exact_workflow_premises(tmp_path):
    source, context = workflow_fixture(parallel=True)
    report = sut.project_state_families(source, context)[1]
    jar = tmp_path / "inert.jar"
    jar.write_bytes(b"injected process executor")
    def execute(invocation, cancellation):
        return RawProcessResult(returncode=0, stdout="Semantic processing of module IntentControlFlow\n")
    receipt = sut.validate_tla_projection(report, jar, document=source, context=context,
        java_executable=sys.executable, runner=BoundedToolRunner(executor=execute))
    assert receipt["status"] == "passed"
    assert receipt["assumptions"] == report["assumptions"]
    assert any("caller-supplied" in a for a in receipt["assumptions"])
    assert any("complete active/completed" in a for a in receipt["assumptions"])
    assert not any("terminal Done" in a for a in receipt["assumptions"])
