"""CFG occurrence and iteration scopes remain pending, source-bound structure."""
from copy import deepcopy
import hashlib
import json
import subprocess

import pytest

from ipfs_datasets_py.logic.software_verification import numerical_logic as v1
from ipfs_datasets_py.logic.software_verification import numerical_logic_v2 as v2
from ipfs_datasets_py.logic.software_verification import numerical_logic_v3 as logic
from ipfs_datasets_py.logic.software_verification import numerical_obligation_retrieval as pages
from ipfs_datasets_py.logic.software_contracts import source_unit_numerical_links as links
from ipfs_datasets_py.logic.formalization.autoencoder import source_function_units as units
from ipfs_datasets_py.logic.syntax_core.ast import TypedExpression


SOURCE = '''def sum_selected(items, allowed):
    total = 0
    for item in items:
        if allowed(item):
            total = total + item[0]
        else:
            continue
        assert accepted(total), f"bad {total}"
    else:
        checked(total)
    return total
'''


def build(source=SOURCE):
    return logic.formalize_numerical_source(source, path="authored.py")


@pytest.fixture(scope="module")
def report():
    return build()


def test_loop_protocol_binding_induction_and_termination_are_pending(report):
    assert report["structural"]["status"] == "translated"
    assert report["summary"]["loop_region_count"] == 1
    assert report["summary"]["control_region_count"] == 2
    kinds = {row["kind"] for row in report["pending_obligations"]}
    assert {"iterator_creation_semantics", "iterator_advance_semantics", "loop_target_binding_semantics",
            "loop_invariant_initialization", "loop_invariant_preservation", "loop_exit_reasoning",
            "loop_termination", "control_flow_semantics", "statement_truthiness_semantics"} <= kinds
    for row in report["pending_obligations"]:
        assert row["status"] == "pending"
        assert row["cfg_occurrences"] and row["evaluation_contexts"]
        assert row["assumptions_asserted"] is False
        for key in logic._CONTROL_FALSE:
            assert row[key] is False
    assert report["coverage"]["source_obligations_discharged"] == 0


def test_loop_body_index_has_cfg_and_symbolic_iteration_scope(report):
    row, = [r for r in report["pending_obligations"] if r["kind"] == "index_safety"]
    assert len(row["loop_region_ids"]) == 1
    assert len(row["control_region_ids"]) == 2
    for context in row["evaluation_contexts"]:
        assert context["cfg_id"] and context["block_id"]
        assert context["source_sha256"] == report["source_sha256"]
        assert context["occurrence"] == "symbolic_block_visit"
        assert context["reachability_verified"] is False
        assert context["guard_conditions"][0]["kind"] == "cfg_block_visit"
        assert context["loop_contexts"]
        assert all(loop["activation_variable"] for loop in context["loop_contexts"])
        assert all(loop["iteration_variable"] for loop in context["loop_contexts"])


def test_loop_else_keeps_activation_without_inventing_body_iteration(report):
    row = next(r for r in report["pending_obligations"]
               if r["kind"] == "library_semantics_and_effects" and r["roles"]["qualified_callee"] == "checked")
    loop, = row["evaluation_contexts"][0]["loop_contexts"]
    assert loop["phase"] == "else"
    assert loop["iteration_variable"] is None
    assert loop["activation_variable"]
    assert loop["occurrence"] == "exhausted_activation"


def test_invariant_and_termination_are_distinct_proof_phases_without_witnesses(report):
    expected = {"loop_invariant_initialization": "activation_entry",
                "loop_invariant_preservation": "normal_or_continue_backedge",
                "loop_exit_reasoning": "exit_cause_and_post_state",
                "loop_termination": "whole_activation_progress"}
    for kind, phase in expected.items():
        row, = [r for r in report["pending_obligations"] if r["kind"] == kind]
        assert row["roles"]["proof_phase"] == phase
        assert row["roles"]["phase_established"] is False
        assert row["roles"]["activation_variable"]
        assert row["roles"]["iteration_variable"]
        scope = row["proof_scope"]
        assert scope["proof_phase"] == phase
        assert scope["phase_established"] is scope["applicability_verified"] is False
        assert scope["full_region_cfg_interpretation_required"] is True
        assert scope["relevant_edge_ids"]
        assert row["evaluation_context_role"] == "source_anchor_only"
        assert row["logical_guard_scope"] == "unresolved_proof_scope_applicability"
        assert "source anchors only" in row["evaluation_guard_interpretation"]
    region = next(r for r in report["structural"]["control_regions"] if r["kind"] == "for_statement")
    preserve = next(r for r in report["pending_obligations"] if r["kind"] == "loop_invariant_preservation")
    assert preserve["proof_scope"]["relevant_edge_ids"] == sorted(set(region["backedge_ids"] + region["continue_edge_ids"]))
    initial = next(r for r in report["pending_obligations"] if r["kind"] == "loop_invariant_initialization")
    scope, = initial["evaluation_contexts"][0]["loop_contexts"]
    assert scope["phase"] == "initialize" and scope["iteration_variable"] is None


def test_inner_else_transfer_is_an_exit_boundary_not_an_outer_loop_owned_by_inner():
    source = "def nested(groups):\n    for group in groups:\n        for item in group:\n            inspect(item)\n        else:\n            continue\n    return groups\n"
    report = build(source)
    outer, inner = [r for r in report["structural"]["control_regions"] if r["kind"] == "for_statement"]
    transfer = next(c for c in report["structural"]["command_contexts"]
                    if c["control_transfer"] == "continue")
    assert transfer["target_region_id"] == outer["region_id"]
    row = next(r for r in report["pending_obligations"] if r["kind"] == "loop_exit_reasoning"
               and r["roles"]["control_region_id"] == inner["region_id"])
    assert set(transfer["edge_ids"]) <= set(row["proof_scope"]["relevant_edge_ids"])
    assert outer["exhaustion_edge_id"] not in row["proof_scope"]["relevant_edge_ids"]


def test_nested_activations_keep_distinct_enclosing_loop_scopes():
    source = "def nested(groups):\n    for group in groups:\n        for item in acquire(group):\n            inspect(item[0])\n"
    report = build(source)
    index, = [r for r in report["pending_obligations"] if r["kind"] == "index_safety"]
    assert len(index["loop_region_ids"]) == 2
    scopes = index["evaluation_contexts"][0]["loop_contexts"]
    assert len(scopes) == 2
    assert scopes[0]["region_id"] != scopes[1]["region_id"]
    assert scopes[0]["activation_variable"] != scopes[1]["activation_variable"]
    created = next(r for r in report["pending_obligations"]
                   if r["kind"] == "library_semantics_and_effects" and r["roles"]["qualified_callee"] == "acquire")
    assert scopes[0]["region_id"] in created["loop_region_ids"]


def test_while_assertions_retain_enablement_message_and_repeated_visit():
    source = "def retry(state):\n    while ready(state):\n        assert valid(state), f'{state[0]}'\n        state = advance(state)\n    else:\n        finish(state)\n    return state\n"
    report = build(source)
    assert report["structural"]["status"] == "translated"
    assert any(r["kind"] == "loop_test_semantics" for r in report["pending_obligations"])
    row, = [r for r in report["pending_obligations"] if r["kind"] == "index_safety"]
    conditions = row["evaluation_contexts"][0]["guard_conditions"]
    assert any(g["kind"] == "assertions_enabled" for g in conditions)
    assert any(g["kind"] == "truthiness_result" and g["value"] is False for g in conditions)
    assert row["loop_region_ids"]
    requirement, = report["assertion_requirements"]
    assert requirement["schema"] == "numerical-control-assertion-requirement@1"
    assert requirement["cfg_occurrences"]
    obligation = next(r for r in report["pending_obligations"] if r["obligation_id"] == requirement["obligation_id"])
    assert obligation["roles"]["requirement_id"] == requirement["requirement_id"]


def test_all_projection_bindings_retain_cfg_and_loop_contexts(report):
    obligations = {row["obligation_id"]: row for row in report["pending_obligations"]}
    for projection in report["projections"]["first_order"] + report["projections"]["smt"]:
        row = obligations[projection["obligation_id"]]
        assert projection["evaluation_contexts"] == row["evaluation_contexts"]
        for key in ("cfg_occurrences", "control_region_ids", "loop_region_ids", *logic._CONTROL_FALSE):
            assert projection[key] == row[key]
        if "proof_scope" in row:
            assert projection["proof_scope"] == row["proof_scope"]
            assert projection["logical_guard_scope"] == "unresolved_proof_scope_applicability"
    for binding in report["projections"]["lean"]["bindings"]:
        row = obligations[binding["obligation_id"]]
        assert binding["evaluation_contexts"] == row["evaluation_contexts"]
        assert binding["cfg_occurrences"] == row["cfg_occurrences"]
        if "proof_scope" in row:
            assert binding["proof_scope"] == row["proof_scope"]
            assert binding["logical_guard_scope"] == "unresolved_proof_scope_applicability"
    for projection in report["projections"]["first_order"]:
        expression = TypedExpression.from_dict(projection["expression"]).to_dict()
        row = obligations[projection["obligation_id"]]
        for key, value in logic._control_binding(row).items():
            assert expression["metadata"][key] == value
    native = report["projections"]["program"]
    assert native["control_regions"] == report["structural"]["control_regions"]
    assert native["command_contexts"] == report["structural"]["command_contexts"]
    assert native["control_extension_required"] is True
    assert native["standalone_program_evaluation_complete"] is False
    assert report["projections"]["lean"]["lake_executed"] is False


def test_cfg_does_not_promote_temporal_or_transition_families(report):
    unsupported = {row["family"]: row for row in report["unsupported_families"]}
    assert unsupported["transition_system"]["status"] == "unsupported"
    assert unsupported["temporal"]["status"] == "unsupported"
    assert "transition_system" not in report["summary"]["families_with_artifacts"]


def test_straight_line_compound_pattern_survives_native_exception_cfg_but_loop_does_not():
    source = '''import numpy as np
def selected(matrix):
    values, vectors = np.linalg.eig(matrix)
    chosen = np.argmax(np.abs(values))
    return values[chosen], vectors[:, chosen]

def repeated(matrix):
    for item in matrix:
        values, vectors = np.linalg.eig(matrix)
        chosen = np.argmax(np.abs(values))
        return values[chosen], vectors[:, chosen]
'''
    report = build(source)
    contract, = report["compound_contracts"]
    assert contract["cfg_occurrences"]
    assert contract["control_region_ids"] == contract["loop_region_ids"] == []
    assert contract["matcher_scope"] == "reviewed_unique_normal_return_path_without_control_guard_or_format_regions"
    rows = [r for r in report["pending_obligations"] if r["roles"].get("compound_contract_id") == contract["contract_id"]]
    assert len(rows) == 7 and contract["obligation_ids"] == [r["obligation_id"] for r in rows]
    assert report["compound_contract_assessments"][1]["status"] == "not_derived"
    assert logic.validate_numerical_logic_report(report, source, path="authored.py") == report


@pytest.mark.parametrize("damage", ["iteration", "activation", "cfg", "reachability", "invariant", "termination", "projection", "control_region", "drop_row"])
def test_rehashed_mutation_of_control_scope_or_authority_fails_replay(report, damage):
    bad = deepcopy(report)
    row = next(r for r in bad["pending_obligations"] if r["kind"] == "index_safety")
    if damage == "iteration": row["evaluation_contexts"][0]["loop_contexts"][0]["iteration_variable"] = "0"
    elif damage == "activation": row["evaluation_contexts"][0]["loop_contexts"][0]["activation_variable"] = "global_once"
    elif damage == "cfg": row["cfg_occurrences"][0]["block_id"] = "foreign"
    elif damage == "reachability": row["reachability_verified"] = True
    elif damage == "invariant": row["loop_invariants_verified"] = True
    elif damage == "termination": row["termination_verified"] = True
    elif damage == "projection": bad["projections"]["first_order"][0]["cfg_occurrences"] = []
    elif damage == "control_region": bad["projections"]["program"]["control_regions"] = []
    else: bad["pending_obligations"].pop()
    bad["report_sha256"] = logic._sha({k:v for k,v in bad.items() if k != "report_sha256"})
    with pytest.raises(logic.NumericalLogicError, match="differs"):
        logic.validate_numerical_logic_report(bad, SOURCE, path="authored.py")


def test_pager_returns_complete_iteration_contexts_and_exact_rows(report):
    cursor, rows = None, []
    while True:
        page = pages.page_numerical_obligations(report=report, source_text=SOURCE, path="authored.py",
                                               limit=2, max_bytes=8192, cursor=cursor)
        rows.extend(page["rows"])
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert rows == report["pending_obligations"]


@pytest.mark.parametrize("profile,schema", [(v1.PROFILE,logic.SCHEMA),(v2.PROFILE,logic.SCHEMA),
    (logic.PROFILE,v2.SCHEMA),(logic.PROFILE,v1.SCHEMA),("unknown",logic.SCHEMA)])
def test_dispatch_refuses_mixed_profile_and_schema(report, profile, schema):
    bad = deepcopy(report)
    bad.update(profile=profile, schema=schema)
    with pytest.raises(pages.NumericalObligationRetrievalError, match="source replay"):
        pages.page_numerical_obligations(report=bad, source_text=SOURCE, path="authored.py")


def test_source_unit_links_include_body_protocol_and_control_obligations(report):
    raw = SOURCE.encode()
    inventory = units.extract_function_units(source_bytes=raw, source_sha256=hashlib.sha256(raw).hexdigest(), source_path="authored.py")
    result = links.bind_function_unit_logic(source_bytes=raw, unit_inventory=inventory, numerical_report=report)
    assert result["pending_obligation_count"] == result["linked_pending_obligation_count"]
    assert not result["unlinked_pending_obligation_ids"]
    assert {"numerical_source_v3.py", "numerical_logic_v3.py", "numerical_source_v2.py", "numerical_logic_v2.py"} <= result["producer"].keys()
    assert links.validate_function_unit_logic_links(result, source_bytes=raw, unit_inventory=inventory,
                                                    numerical_report=report) == result


def test_exception_cleanup_constructs_remain_explicitly_unsupported():
    report = build("def guarded(items):\n    try:\n        for item in items:\n            examine(item)\n    finally:\n        cleanup()\n")
    assert report["structural"]["status"] == "partial"
    assert report["source_semantics_verified"] is False
    assert not report["compound_contracts"]


def test_prepare_never_executes_source_or_subprocess(monkeypatch):
    monkeypatch.setattr(subprocess,"Popen",lambda *a,**kw: (_ for _ in ()).throw(AssertionError("no subprocess")))
    source = "raise RuntimeError('never run this')\ndef inspect(items):\n    for item in items:\n        forbidden(item)\n"
    report = build(source)
    assert logic.validate_numerical_logic_report(report, source, path="authored.py") == report
    assert report["source_executed"] is False
    assert report["provider_calls"] == report["solver_calls"] == 0
