"""Adversarial guarded projection/replay cases; target source is never executed."""
from copy import deepcopy
import hashlib
import json
import subprocess

import pytest

from ipfs_datasets_py.logic.software_verification import numerical_logic as legacy
from ipfs_datasets_py.logic.software_verification import numerical_logic_v2 as logic
from ipfs_datasets_py.logic.software_verification import numerical_obligation_retrieval as pages
from ipfs_datasets_py.logic.software_contracts import source_unit_numerical_links as links
from ipfs_datasets_py.logic.formalization.autoencoder import source_function_units as units
from ipfs_datasets_py.logic.syntax_core.ast import TypedExpression


SOURCE = '''import numpy as np
def choose(matrix, condition, alternative):
    return np.linalg.eig(matrix) if condition else alternative[0]

def check(value, width):
    assert accepted(value), f"bad: {value!r:{width}} {later()}"
'''


def wire(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def build(source=SOURCE):
    return logic.formalize_numerical_source(source, path="authored.py")


@pytest.fixture(scope="module")
def report():
    return build()


def conditions(row):
    return [guard for context in row["evaluation_contexts"] for guard in context["guard_conditions"]]


def test_conditional_library_and_index_obligations_keep_opposite_branch_guards(report):
    assert report["structural"]["status"] == "translated"
    assert report["summary"]["structurally_complete_functions"] == 2
    shape, = [row for row in report["pending_obligations"] if row["kind"] == "matrix_shape"]
    index, = [row for row in report["pending_obligations"] if row["kind"] == "index_safety"]
    assert {g["value"] for g in conditions(shape) if g["kind"] == "truthiness_result"} == {True}
    assert {g["value"] for g in conditions(index) if g["kind"] == "truthiness_result"} == {False}
    assert shape["guarded_region_ids"] == index["guarded_region_ids"]
    assert len(shape["function_ids"]) == len(index["function_ids"]) == 1
    assert shape["evaluation_guard_verified"] is False
    assert shape["runtime_truthiness_verified"] is False


def test_assert_message_and_later_field_retain_enablement_false_and_prefix_completion(report):
    rows = report["pending_obligations"]
    formatting = [row for row in rows if row["kind"] == "formatting_evaluation_semantics"]
    assert len(formatting) >= 2
    for row in formatting:
        assert any(g["kind"] == "assertions_enabled" for g in conditions(row))
        assert any(g["kind"] == "truthiness_result" and g["value"] is False for g in conditions(row))
        assert row["roles"]["evaluation_policy"] == "value_then_format_spec_then_conversion_then_format"
    later = next(row for row in rows if row["kind"] == "library_semantics_and_effects"
                 and row["roles"]["qualified_callee"] == "later")
    assert sum(g["kind"] == "normal_completion" for g in conditions(later)) >= 2
    assertion, = report["assertion_requirements"]
    assert any(g["kind"] == "assertions_enabled" for g in conditions(assertion))
    assert not any(g["kind"] == "truthiness_result" for g in conditions(assertion))
    assert assertion["function_postcondition_inferred"] is False
    assert assertion["assertion_execution_verified"] is False
    assert assertion["failure_message_structure_lowered"] is True


def test_nested_conditions_accumulate_not_replace_guards():
    report = build("def choose(a, b, x, y, z):\n    return (x[0] if b else y[0]) if a else z[0]\n")
    indices = [row for row in report["pending_obligations"] if row["kind"] == "index_safety"]
    truth = [tuple(g["value"] for g in conditions(row) if g["kind"] == "truthiness_result") for row in indices]
    assert sorted(truth) == sorted([(True, True), (True, False), (False,)])
    assert sorted(len(row["guarded_region_ids"]) for row in indices) == [1, 2, 2]


def test_all_projection_families_preserve_exact_guard_bindings_and_do_not_assert_them(report):
    rows = {row["obligation_id"]: row for row in report["pending_obligations"]}
    for projection in report["projections"]["first_order"]:
        row = rows[projection["obligation_id"]]
        assert projection["evaluation_contexts"] == row["evaluation_contexts"]
        assert projection["guarded_region_ids"] == row["guarded_region_ids"]
        typed = TypedExpression.from_dict(projection["expression"])
        assert typed.to_dict() == projection["expression"]
        assert typed.root.kind.value == "implies"
    assert report["projections"]["smt"]
    for projection in report["projections"]["smt"]:
        row = rows[projection["obligation_id"]]
        assert projection["evaluation_contexts"] == row["evaluation_contexts"]
        script = projection["compilation"]["script"]["source"]
        assert "evaluation_context" in script and "=>" in script
        assert projection["solver_executed"] is projection["discharged"] is False
    lean = report["projections"]["lean"]
    assert lean["lake_executed"] is False
    assert len(lean["bindings"]) == len(rows)
    for binding in lean["bindings"]:
        assert binding["evaluation_contexts"] == rows[binding["obligation_id"]]["evaluation_contexts"]
        assert binding["definition"] == "GuardedRequirement"
    assert "evaluationContext → requirement" in lean["source"]
    assert report["projections"]["program"]["guarded_extension_required"] is True
    assert report["projections"]["program"]["standalone_program_evaluation_complete"] is False


def test_bounded_summary_keeps_guard_references(report):
    assertion, = report["summary"]["assertion_requirements"]
    assert assertion["guarded_region_ids"]
    assert assertion["evaluation_guard_verified"] is False
    assert assertion["full_evaluation_contexts_in_native_report"] is True
    assert report["summary"]["guarded_region_count"] == 2
    assert not report["compound_contracts"]


def test_complete_straight_line_compounds_survive_but_guarded_siblings_are_fenced():
    source = '''import numpy as np
def selected(matrix):
    values, vectors = np.linalg.eig(matrix)
    chosen = np.argmax(np.abs(values))
    return values[chosen], vectors[:, chosen]

def guarded(matrix, condition):
    values, vectors = np.linalg.eig(matrix)
    chosen = np.argmax(np.abs(values))
    return (values[chosen], vectors[:, chosen]) if condition else (0, matrix[:, 0])
'''
    report = build(source)
    contract, = report["compound_contracts"]
    assert contract["matcher_scope"] == "complete_function_without_guarded_or_format_constructs"
    assert contract["guarded_region_ids"] == []
    assert contract["evaluation_contexts"]
    bound = [row for row in report["pending_obligations"]
             if row["roles"].get("compound_contract_id") == contract["contract_id"]]
    assert len(bound) == 7
    assert contract["obligation_ids"] == [row["obligation_id"] for row in bound]
    assert all(row["function_ids"] == [contract["function_id"]] for row in bound)
    assert len({row["obligation_id"] for row in report["pending_obligations"]}) == len(report["pending_obligations"])
    assert report["compound_contract_assessments"][1]["status"] == "not_derived"
    assert "selected_column_contract" in report["projections"]["lean"]["conditional_lemmas"]
    assert report["summary"]["compound_contract_count"] == 1
    assert logic.validate_numerical_logic_report(report, source, path="authored.py") == report


@pytest.mark.parametrize("damage", ["drop_guard", "flip_branch", "projection_guard", "strip_extension", "authority", "obligation", "lean"])
def test_rehashed_guard_or_projection_mutation_fails_exact_source_replay(report, damage):
    bad = deepcopy(report)
    row = next(row for row in bad["pending_obligations"] if row["kind"] == "matrix_shape")
    if damage == "drop_guard": row["evaluation_contexts"] = []
    elif damage == "flip_branch":
        next(g for g in row["evaluation_contexts"][0]["guard_conditions"] if g["kind"] == "truthiness_result")["value"] = False
    elif damage == "projection_guard": bad["projections"]["first_order"][0]["evaluation_contexts"] = []
    elif damage == "strip_extension": bad["projections"]["program"]["guarded_regions"] = []
    elif damage == "authority": row["evaluation_guard_verified"] = True
    elif damage == "obligation": bad["pending_obligations"].pop()
    else: bad["projections"]["lean"]["source"] += "\n"
    bad["report_sha256"] = logic._sha({k: v for k, v in bad.items() if k != "report_sha256"})
    with pytest.raises(logic.NumericalLogicError, match="differs"):
        logic.validate_numerical_logic_report(bad, SOURCE, path="authored.py")


def test_pager_retains_whole_guard_rows_and_refuses_cross_profile_cursor(report):
    collected, cursor = [], None
    while True:
        page = pages.page_numerical_obligations(report=report, source_text=SOURCE, path="authored.py",
                                               limit=2, max_bytes=8192, cursor=cursor)
        collected.extend(page["rows"])
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert collected == report["pending_obligations"]
    assert all(row["evaluation_contexts"] for row in collected)
    cursor = pages.page_numerical_obligations(report=report, source_text=SOURCE, path="authored.py", limit=1)["next_cursor"]
    old = legacy.formalize_numerical_source(SOURCE, path="authored.py")
    with pytest.raises(pages.NumericalObligationRetrievalError, match="cursor"):
        pages.page_numerical_obligations(report=old, source_text=SOURCE, path="authored.py", limit=1, cursor=cursor)


@pytest.mark.parametrize("profile,schema", [
    (logic.PROFILE, legacy.SCHEMA), (legacy.PROFILE, logic.SCHEMA), ("foreign", logic.SCHEMA)])
def test_dispatch_never_accepts_mixed_or_unknown_profile(report, profile, schema):
    bad = deepcopy(report)
    bad.update(profile=profile, schema=schema)
    with pytest.raises(pages.NumericalObligationRetrievalError, match="source replay"):
        pages.page_numerical_obligations(report=bad, source_text=SOURCE, path="authored.py")


def test_unit_links_include_all_side_branch_and_message_obligations(report):
    source = SOURCE.encode()
    inventory = units.extract_function_units(source_bytes=source, source_sha256=hashlib.sha256(source).hexdigest(),
                                             source_path="authored.py")
    linked = links.bind_function_unit_logic(source_bytes=source, unit_inventory=inventory, numerical_report=report)
    assert linked["matched_unit_count"] == 2
    assert linked["pending_obligation_count"] == linked["linked_pending_obligation_count"]
    assert not linked["unlinked_pending_obligation_ids"]
    assert {"numerical_source_v2.py", "numerical_logic_v2.py"} <= linked["producer"].keys()
    assert links.validate_function_unit_logic_links(linked, source_bytes=source, unit_inventory=inventory,
                                                    numerical_report=report) == linked


def test_unresolved_loops_remain_partial_and_do_not_gain_assertion_requirements():
    report = build("def check(items):\n    for item in items:\n        assert valid(item), f'{item}'\n")
    assert report["structural"]["status"] == "partial"
    assert not report["assertion_requirements"]
    assert report["summary"]["partial_or_unsupported_functions"] == 1
    assert report["coverage"]["source_obligations_discharged"] == 0


def test_prepare_and_replay_never_run_target_or_subprocess(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("source preparation must not run subprocesses")
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    source = "raise RuntimeError('never run this')\ndef f(x):\n    return x[0] if x else x[1]\n"
    report = build(source)
    assert logic.validate_numerical_logic_report(report, source, path="authored.py") == report
    for key in logic._FALSE:
        assert report[key] is False
    assert report["provider_calls"] == report["solver_calls"] == 0


def test_original_path_or_source_required_even_when_ast_is_unchanged(report):
    for text, path in [(SOURCE + "\n# same AST\n", "authored.py"), (SOURCE, "elsewhere.py")]:
        with pytest.raises(logic.NumericalLogicError, match="differs"):
            logic.validate_numerical_logic_report(report, text, path=path)
