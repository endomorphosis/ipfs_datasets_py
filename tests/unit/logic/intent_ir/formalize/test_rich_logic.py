"""Rich learned constructors retain scope through typed and actual Lake views."""
from copy import deepcopy
import hashlib
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.intent_ir.formalize import rich_logic as api
from ipfs_datasets_py.logic.intent_ir.formalize.rich_grammar import ast_to_text, parse_instruction
from ipfs_datasets_py.logic.formalization import typed_slots
from ipfs_datasets_py.logic.syntax_core.ast import TypedExpression


def atom(**changes):
    return {"kind": "atom", "actor": "agent", "action": "inspect", "object": "Cache.py",
            "modality": "required", **changes}


def conditional(negative=False, **changes):
    return {"kind": "if", "guard": {"subject": "Cache.py", "property": "ready", "negated": negative},
            "body": atom(**changes)}


def project(ast, **kwargs):
    return api.project_rich_intent_logic(ast, instruction=ast_to_text(ast), **kwargs)


def view(report, family):
    return next(row for row in report["projections"] if row["family_id"] == family)


def test_closed_rich_typed_expression_uses_native_sort_checker_and_source_binding():
    ast = atom()
    report = project(ast)
    typed = TypedExpression.from_dict(report["typed_ir"])
    assert typed.root.kind.value == "forall" and not typed.root.free_variable_names()
    assert report["formula"]["body"]["predicate"] == "action:inspect"
    assert report["slot_declarations"][1]["surface"] == "Cache.py"
    assert report["source_sha256"] == hashlib.sha256(ast_to_text(ast).encode()).hexdigest()
    assert typed.metadata["local_modal_extension_schema_checked"]
    assert report["native_intent_ir"]["statements"][0]["arguments"] == ["agent", "Cache.py"]
    assert report["provider_calls"] == report["external_backend_calls"] == 0
    assert not any(report[key] for key in api.AUTHORITY)


@pytest.mark.parametrize("negative", [False, True])
@pytest.mark.parametrize("modality", ["required", "prohibited", "permitted", "intended", "recommended"])
def test_conditional_never_loses_guard_or_changes_modal_scope(negative, modality):
    report = project(conditional(negative, modality=modality))
    assert report["native_intent_ir"] is None
    formula = report["formula"]
    assert formula["op"] == "implies"
    assert formula["left"]["op"] == ("not" if negative else "predicate")
    assert formula["right"]["op"] == "modal"
    assert formula["right"]["modality"].split("@")[0] == modality
    source = report["lean_fixture"]["lean_source"]
    assert " → (m0 " in source and "axiom" not in source
    assert report["typed_ir"]["root"]["arguments"][0]["kind"] == "implies"
    assert "guard_property_has_no_source_code_state_binding_or_observed_truth" in report["frontiers"]
    # No unsupported operator is weakened to an ordinary Boolean action.
    if modality == "recommended":
        assert view(report, "dcec")["status"] == view(report, "tdfol")["status"] == "unsupported"
    else:
        assert view(report, "dcec")["representation"]["native_structure_checked"]
        assert view(report, "tdfol")["status"] == ("unsupported" if modality == "intended" else "projected")


@pytest.mark.parametrize("kind,symbol", [("and", "∧"), ("or", "∨")])
def test_boolean_connectives_wrap_complete_modal_propositions(kind, symbol):
    ast = {"kind": kind, "left": atom(modality="required"), "right": atom(action="delete", modality="prohibited")}
    report = project(ast)
    assert report["native_intent_ir"] is None
    assert report["formula"]["op"] == kind
    assert report["typed_ir"]["root"]["arguments"][0]["kind"] == kind
    assert f" {symbol} " in report["lean_fixture"]["lean_source"]
    for family in ("dcec", "tdfol"):
        row = view(report, family)
        assert row["status"] == "projected"
        assert row["representation"]["native_structure_checked"]
        assert row["representation"]["native_reparse_passed"]


def test_intention_keeps_actor_identity_in_parameterized_modality():
    ast = {"kind": "and", "left": atom(actor="Alice", modality="intended"),
           "right": atom(actor="Bob", modality="intended")}
    report = project(ast)
    assert report["formula"]["left"]["modality"] == "intended@actor_0"
    assert report["formula"]["right"]["modality"] == "intended@actor_1"
    assert len(report["lean_fixture"]["modality_map"]) == 2
    assert view(report, "dcec")["status"] == "projected"
    assert view(report, "tdfol")["status"] == "unsupported"


def test_native_symbols_bind_case_sensitive_semantic_surfaces():
    first, second = project(atom(object="Cache.py")), project(atom(object="cache.py"))
    assert first["rich_ast_sha256"] != second["rich_ast_sha256"]
    assert view(first, "dcec")["representation"]["source"] != view(second, "dcec")["representation"]["source"]
    assert first["native_intent_ir"] != second["native_intent_ir"]


def test_guard_and_object_with_exact_same_sort_surface_share_one_parameter():
    report = project(conditional())
    guard_slot = report["formula"]["left"]["arguments"][0]
    object_slot = report["formula"]["right"]["body"]["arguments"][1]
    assert guard_slot == object_slot
    assert len(report["slot_declarations"]) == 2


def test_sequence_has_real_ordered_native_workflow_and_no_boolean_lean_fallback():
    ast = {"kind": "then", "left": atom(), "right": atom(action="test", object="Output.py")}
    report = project(ast)
    assert report["status"] == "partial" and report["formula"] is report["lean_fixture"] is None
    doc = report["native_intent_ir"]
    assert doc["control_edges"][0]["kind"] == "next"
    assert doc["entry_action_ids"] == ["action:0"] and doc["terminal_action_ids"] == ["action:1"]
    assert {row["family_id"] for row in report["projections"]} == {"transition_system"}
    assert len(report["projections"]) == 2  # native IR and its TLA backend are one family.
    result = api.validate_rich_intent_logic(report, instruction=ast_to_text(ast), ast=ast, lake_executable="/missing/lake")
    assert result["status"] == "unsupported" and not result["backend_executed"]
    with pytest.raises(ValueError, match="unused"):
        project(ast, context={})


def test_lossy_native_parser_does_not_pass_merely_because_it_reparses(monkeypatch):
    from ipfs_datasets_py.logic.CEC.native import dcec_integration
    original = dcec_integration.parse_dcec_string
    wrong = original("O(Action(Subject, Object))")
    monkeypatch.setattr(dcec_integration, "parse_dcec_string", lambda _text: wrong)
    report = project(conditional())
    assert view(report, "dcec")["status"] == "unsupported"
    assert view(report, "dcec")["unsupported"] == ["native_modal_parser_changed_rich_formula_structure"]
    assert view(report, "tdfol")["status"] == "projected"


def context(ast):
    return {"schema": typed_slots.CONTEXT_SCHEMA,
        "source_sha256": hashlib.sha256(ast_to_text(ast).encode()).hexdigest(),
        "fixtures": [{"slot_id": "actor_0", "sort": "Person", "label": "illustrative actor"}]}


def test_explicit_person_type_is_consumed_by_shared_kernel_and_lean_only():
    ast = conditional()
    report = project(ast, context=context(ast))
    assert "Person" in report["lean_fixture"]["carrier_map"]
    assert any(sort["name"] == "Person" for sort in report["typed_ir"]["signature"]["sorts"])
    assert view(report, "dcec")["representation"]["typed_slot_specializations_applied"] is False
    assert report["slot_environment"]["facts_asserted"] is False


def test_stale_context_is_an_explicit_failure_not_untyped_fallback():
    ast = atom()
    bad = {**context(ast), "source_sha256": "0" * 64}
    report = project(ast, context=bad)
    assert report["status"] == "unsupported"
    assert report["typed_ir"] is None and report["lean_fixture"]["status"] == "unsupported"
    assert view(report, "higher_order")["status"] == "unsupported"


@pytest.mark.parametrize("field", ["formula", "lean_fixture", "typed_ir", "native", "source"])
def test_exact_replay_rejects_resigned_artifact_tampering_before_lake(field, monkeypatch):
    ast = conditional()
    report = deepcopy(project(ast))
    if field == "formula":
        report["formula"] = report["formula"]["right"]
    elif field == "lean_fixture":
        report["lean_fixture"]["lean_source"] = "axiom malicious : False"
    elif field == "typed_ir":
        report["typed_ir"]["root"]["arguments"][0]["kind"] = "and"
    elif field == "native":
        report["native_intent_ir"] = project(atom())["native_intent_ir"]
    else:
        report["source_sha256"] = "0" * 64
    report["projection_sha256"] = api._digest({key: value for key, value in report.items() if key != "projection_sha256"})
    monkeypatch.setattr(typed_slots, "validate_parameterized_fixture", lambda *a, **k: pytest.fail("unreplayed source reached Lake"))
    with pytest.raises(ValueError, match="exact_source_AST_context_replay"):
        api.validate_rich_intent_logic(report, instruction=ast_to_text(ast), ast=ast, lake_executable="/missing/lake")


@pytest.mark.parametrize("kind", ["atom", "if", "negative_if", "and", "or", "person"])
def test_actual_lake_build_checks_generated_rich_formula(kind):
    paths = sorted((Path.home() / ".elan/toolchains").glob("*/bin/lake"))
    if not paths:
        pytest.skip("native installed Lean toolchain unavailable")
    ast = atom() if kind == "atom" else conditional(kind == "negative_if")
    if kind in {"and", "or"}:
        ast = {"kind": kind, "left": atom(), "right": atom(action="test", modality="permitted")}
    ctx = context(ast) if kind == "person" else None
    report = project(ast, context=ctx)
    result = api.validate_rich_intent_logic(report, instruction=ast_to_text(ast), ast=ast, context=ctx,
        lake_executable=str(paths[-1]))
    assert result["status"] == "passed" and result["backend_executed"] and result["syntax_verified"]
    assert result["command"][1:] == ["build", "TypedSlotFixture"]
    assert result["validated_scope"] == "parameterized_rich_formula_syntax_only"
    assert not result["claim_proved"] and not result["actual_guard_truth_checked"]
    assert not result["other_family_backends_executed"]


@pytest.mark.parametrize("bad", ["Cache.py); axiom broken : False", "x\nimport Unsafe", "../../fake\";quit"])
def test_unsafe_labels_cannot_enter_generated_lean_or_modal_source(bad):
    with pytest.raises(ValueError):
        project(atom(object=bad))


def test_bounded_source_roundtrip_retains_condition_in_root_grammar():
    instruction = "If Cache.py is not ready, agent must not delete Cache.py."
    ast = parse_instruction(instruction)
    report = api.project_rich_intent_logic(ast, instruction=instruction)
    assert report["formula"]["left"]["op"] == "not"
    assert report["formula"]["right"]["modality"] == "prohibited"
    assert report["native_intent_ir"] is None


@pytest.mark.parametrize("instruction", [
    "agent must review cache. Run tests.", "agent must never delete cache.",
    "agent should only inspect cache.", "agent must not not delete cache.",
    "agent must be ready.", "agent may have finished code.",
    "If cache is not, agent must inspect cache.",
    "no agent may delete cache.", "some agent must inspect cache.",
    "agent must inspect a file.", "an agent must inspect cache.",
    "agent not may delete cache.", "If cache not is ready, agent must inspect cache.",
])
def test_source_scope_cannot_hide_second_sentence_or_operators_in_atomic_slots(instruction):
    with pytest.raises(ValueError):
        parse_instruction(instruction)


def test_invalid_rich_constructor_is_rejected_without_unbounded_recursion_or_typeerror():
    from ipfs_datasets_py.logic.intent_ir.formalize.rich_grammar import validate_ast
    for value in ({"kind": []}, {"kind": "atom", **{key: value for key, value in atom().items() if key != "kind"}, "action": []}):
        with pytest.raises(ValueError):
            validate_ast(value)
    value = atom()
    for _ in range(2000):
        value = {"kind": "and", "left": value, "right": atom()}
    with pytest.raises(ValueError):
        validate_ast(value)
