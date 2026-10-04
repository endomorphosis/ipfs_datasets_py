"""Independent semantic controls for explicitly modeled finite Intent state.

These are authored modeling premises, not code behavior inferred from text.
Real SANY/TLC positive and negative controls are recorded separately by the
artifact qualification driver using these same source-bound inputs.
"""
from copy import deepcopy
from dataclasses import replace

import pytest

from ipfs_datasets_py.logic.intent_ir.formalize import state_projections
from ipfs_datasets_py.logic.intent_ir.formalize.projection_contracts import source_ir_sha256
from ipfs_datasets_py.logic.intent_ir.formalize.roundtrip import frame_to_intent_ir
from ipfs_datasets_py.logic.intent_ir.schema import (
    ControlEdgeKind, IntentControlEdge, IntentKind, IntentModality, IntentStatement,
    ReviewStatus, StatementKind,
)


def guarded_fixture(*, initial_values=(False,), update=True, precondition=False,
                    retry_limit=None, retry_guard=False, max_steps=20):
    """Build an independent authored two-action example with explicit premises."""
    base = frame_to_intent_ir(
        {"actor": "agent", "action": "inspect", "object": "cache", "modality": "required"},
        instruction="agent must inspect cache",
    )
    condition = IntentStatement(
        "ready", StatementKind.PRECONDITION if precondition else StatementKind.GUARD,
        IntentModality.ASSERTED, "The authored abstract readiness flag is true.",
        ("source",), predicate="ready", arguments=("cache",),
        review_status=ReviewStatus.TRUSTED_FIXTURE,
    )
    first = replace(base.actions[0], precondition_ids=("ready",) if precondition else ())
    terminal = replace(base.actions[0], action_id="terminal", verb="validate")
    edges = [IntentControlEdge(
        "exit", "action", "terminal", ControlEdgeKind.NEXT,
        guard_statement_id="ready" if retry_limit is None and not precondition else "",
        source_ref_ids=("source",),
    )]
    statements = [*base.statements]
    if retry_limit is None or precondition or retry_guard:
        statements.append(condition)
    if retry_limit is not None:
        edges.append(IntentControlEdge(
            "again", "action", "action", ControlEdgeKind.RETRY,
            guard_statement_id="ready" if retry_guard else "", source_ref_ids=("source",),
        ))
    source = replace(base, intent_kind=IntentKind.PROCEDURE,
                     statements=tuple(statements), actions=(first, terminal),
                     control_edges=tuple(edges), terminal_action_ids=("terminal",))
    binding = {"statement_id": "ready", "expression": {
        "op": "eq", "variable_id": "flag", "value": True}, "evidence_ref": "source"}
    premise = {
        "semantics": "finite_guarded_state_flow", "source_ir_sha256": source_ir_sha256(source),
        "evidence_ref": "source", "variables": [{"variable_id": "flag", "kind": "boolean",
            "domain": [False, True], "initial_values": list(initial_values), "evidence_ref": "source"}],
        "predicate_bindings": [binding] if len(statements) > len(base.statements) else [],
        "action_updates": [{"action_id": action_id, "outcomes": [{
            "values": {"flag": update} if action_id == "action" and update is not None else {},
            "evidence_ref": "source"}], "evidence_ref": "source"}
            for action_id in ("action", "terminal")],
        "retry_bounds": [{"edge_id": "again", "max_traversals": retry_limit,
                          "evidence_ref": "source"}] if retry_limit is not None else [],
    }
    return source, {"state": {"max_steps": max_steps, "workflow": premise}}


def project(source, context):
    return state_projections.project_state_families(source, context)


def graph(source, context):
    reports = project(source, context)
    assert reports[0]["status"] == reports[1]["status"] == "partial"
    return reports[0]["representation"]["payload"]["metadata"]["guarded_graph"]


def retry_deadlock_fixture(*, limit=2, max_steps=20):
    source, context = guarded_fixture(retry_limit=limit, retry_guard=True,
                                      update=False, max_steps=max_steps)
    source = replace(source, control_edges=tuple(replace(e,
        guard_statement_id="ready" if e.edge_id == "exit" else "") for e in source.control_edges))
    context["state"]["workflow"]["source_ir_sha256"] = source_ir_sha256(source)
    return source, context


def test_guard_truth_changes_reachability_and_preserves_failed_state():
    source, enabled = guarded_fixture(update=True)
    disabled = deepcopy(enabled)
    disabled["state"]["workflow"]["predicate_bindings"][0]["expression"]["value"] = False
    good, bad = graph(source, enabled), graph(source, disabled)
    assert not good["deadlocks"]
    assert any(c["terminal"] for c in good["configurations"])
    assert bad["deadlocks"]
    assert not any(c["terminal"] for c in bad["configurations"])
    assert any(t["intent_edge_ids"] == ["exit"] for t in good["transitions"])
    assert not any(t["intent_edge_ids"] == ["exit"] for t in bad["transitions"])


def test_precondition_is_checked_before_update_and_guard_after_update():
    source, context = guarded_fixture(initial_values=(False,), update=True)
    assert not graph(source, context)["deadlocks"], "post-update edge guard must see true"
    source, context = guarded_fixture(initial_values=(False,), update=True, precondition=True)
    blocked = graph(source, context)
    assert blocked["deadlocks"], "false precondition must prevent the would-be repair update"
    assert not any(t["transition_kind"] == "action" for t in blocked["transitions"])
    assert not any(c["values"].get("flag") is True for c in blocked["configurations"])


def test_all_declared_initial_valuations_are_reachable_not_only_first():
    source, context = guarded_fixture(initial_values=(True, False), update=None)
    result = graph(source, context)
    configurations = {c["position"]: c for c in result["configurations"]}
    initial_edges = [t for t in result["transitions"] if t["transition_kind"] == "initialize"]
    assert len(initial_edges) == 2
    assert {configurations[t["to_position"]]["values"]["flag"] for t in initial_edges} == {True, False}
    assert any(c["terminal"] for c in result["configurations"])
    assert len(result["deadlocks"]) == 1


def test_initial_values_form_cartesian_product_and_actions_preserve_omitted_variables():
    source, context = guarded_fixture(initial_values=(True, False), update=True)
    context["state"]["workflow"]["variables"].append({
        "variable_id": "other", "kind": "boolean", "domain": [False, True],
        "initial_values": [False, True], "evidence_ref": "source"})
    result = graph(source, context)
    configurations = {c["position"]: c for c in result["configurations"]}
    initial_edges = [t for t in result["transitions"] if t["transition_kind"] == "initialize"]
    valuations = [configurations[t["to_position"]]["values"] for t in initial_edges]
    assert {(v["flag"], v["other"]) for v in valuations} == {
        (False, False), (False, True), (True, False), (True, True)}
    for transition in result["transitions"]:
        if transition["transition_kind"] != "initialize":
            assert configurations[transition["from_position"]]["values"]["other"] == \
                configurations[transition["to_position"]]["values"]["other"]


def test_all_declared_action_outcomes_are_explored_including_failure():
    source, context = guarded_fixture(update=True)
    context["state"]["workflow"]["action_updates"][0]["outcomes"].append({
        "values": {"flag": False}, "evidence_ref": "source"})
    result = graph(source, context)
    assert any(c["terminal"] for c in result["configurations"])
    assert result["deadlocks"]
    assert {c["values"]["flag"] for c in result["configurations"] if c["phase"] == "routing"} == {False, True}


def test_retry_limit_changes_reachable_histories_without_unbounded_cycle():
    source, context = guarded_fixture(retry_limit=1, update=None)
    once = graph(source, context)
    twice_context = deepcopy(context)
    twice_context["state"]["workflow"]["retry_bounds"][0]["max_traversals"] = 2
    twice = graph(source, twice_context)
    for result, limit in [(once, 1), (twice, 2)]:
        assert not result["deadlocks"]
        assert max(c["retry_counts"].get("again", 0) for c in result["configurations"]) == limit
        assert all(c["retry_counts"].get("again", 0) <= limit for c in result["configurations"])
        assert any(c["terminal"] and c["retry_counts"].get("again") == limit
                   for c in result["configurations"])
    assert twice["max_abstract_steps"] == once["max_abstract_steps"] + 2


def test_retry_exhaustion_is_a_nonterminal_deadlock_even_at_step_cutoff():
    source, context = retry_deadlock_fixture()
    result = graph(source, context)
    assert result["deadlocks"]
    assert not any(c["terminal"] for c in result["configurations"])
    exact = deepcopy(context)
    exact["state"]["max_steps"] = result["max_abstract_steps"]
    reports = project(source, exact)
    qualifier = reports[1]["representation"]["qualification"]
    assert "INVARIANT NoAbstractDeadlock" in qualifier["tlc_config_text"]
    assert all(d["position"] in qualifier["model_text"] for d in result["deadlocks"])
    assert any(v["validator"] == "finite_guarded_deadlock_scan" and v["status"] == "failed"
               for v in reports[0]["validation"])
    assert all(not reports[0][key] for key in ("proof_authority", "execution_authority", "completion_authority"))


def test_short_budget_cannot_silently_truncate_a_retry_history():
    source, context = guarded_fixture(retry_limit=2, update=None)
    result = graph(source, context)
    context["state"]["max_steps"] = result["max_abstract_steps"] - 1
    reports = project(source, context)
    assert all(r["status"] == "unsupported" for r in reports)
    assert all(r["representation"]["payload"] is None for r in reports)


def test_longest_path_budget_survives_merged_configurations():
    # Two paths reach the same terminal-ready configuration; counting only
    # breadth-first discovery depth would silently discard the longer path.
    source, context = guarded_fixture(retry_limit=1, update=None)
    middle = replace(source.actions[0], action_id="middle")
    source = replace(source, actions=(*source.actions, middle), control_edges=(
        replace(source.control_edges[0], edge_id="direct"),
        IntentControlEdge("via", "action", "middle", ControlEdgeKind.NEXT, source_ref_ids=("source",)),
        IntentControlEdge("finish", "middle", "terminal", ControlEdgeKind.NEXT, source_ref_ids=("source",)),
    ))
    premise = context["state"]["workflow"]
    premise["source_ir_sha256"] = source_ir_sha256(source)
    premise["retry_bounds"] = []
    premise["action_updates"].append({"action_id": "middle", "outcomes": [
        {"values": {}, "evidence_ref": "source"}], "evidence_ref": "source"})
    result = graph(source, context)
    assert result["max_abstract_steps"] == 6
    context["state"]["max_steps"] = 5
    assert all(r["status"] == "unsupported" for r in project(source, context))


def test_native_source_change_invalidates_guarded_premises():
    source, context = guarded_fixture()
    changed = replace(source, title="Different exact source document")
    with pytest.raises(ValueError):
        project(changed, context)


@pytest.mark.parametrize("remove", ["predicate_bindings", "action_updates", "variables"])
def test_required_explicit_model_evidence_is_not_silently_inferred(remove):
    source, context = guarded_fixture(precondition=True)
    context["state"]["workflow"][remove] = []
    with pytest.raises(ValueError):
        project(source, context)


def test_guarded_semantics_cannot_be_enabled_by_legacy_context_shape():
    source, context = guarded_fixture()
    context["state"]["workflow"]["choices"] = []
    with pytest.raises(ValueError):
        project(source, context)


def test_retry_bounds_bind_all_and_only_retry_edges():
    source, context = guarded_fixture(retry_limit=2, update=None)
    context["state"]["workflow"]["retry_bounds"] = []
    with pytest.raises(ValueError):
        project(source, context)


def test_unknown_precondition_variable_does_not_become_true():
    source, context = guarded_fixture(precondition=True)
    context["state"]["workflow"]["predicate_bindings"][0]["expression"]["variable_id"] = "missing"
    with pytest.raises(ValueError):
        project(source, context)


@pytest.mark.parametrize("bad", [True, -1, 0, 9, "2"])
def test_retry_bound_is_a_small_positive_integer(bad):
    source, context = guarded_fixture(retry_limit=2, update=None)
    context["state"]["workflow"]["retry_bounds"][0]["max_traversals"] = bad
    with pytest.raises(ValueError):
        project(source, context)
