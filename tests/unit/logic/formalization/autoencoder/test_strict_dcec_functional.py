"""Complete independent prefix parsing never weakens rich DCEC semantics."""
from copy import deepcopy

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import strict_dcec_functional as subject
from ipfs_datasets_py.logic.intent_ir.formalize import rich_logic, rich_grammar


def atom(**updates):
    return {"kind": "atom", "actor": "agent", "action": "inspect", "object": "Cache.py",
            "modality": "required", **updates}


def conditional(negative=False, **updates):
    return {"kind": "if", "guard": {"subject": "Cache.py", "property": "ready", "negated": negative},
            "body": atom(**updates)}


def payload(ast=None):
    ast = conditional() if ast is None else ast
    report = rich_logic.project_rich_intent_logic(ast, instruction=rich_grammar.ast_to_text(ast))
    return next(row["representation"] for row in report["projections"] if row["family_id"] == "dcec")


@pytest.mark.parametrize("modality", ["required", "permitted", "prohibited", "intended"])
@pytest.mark.parametrize("kind", ["atom", "if", "negative_if", "and", "or"])
def test_actual_native_complete_ast_parity_for_every_rich_constructor(modality, kind):
    ast = (atom(modality=modality) if kind == "atom" else
           conditional(kind == "negative_if", modality=modality) if kind in {"if", "negative_if"} else
           {"kind": kind, "left": atom(modality=modality), "right": atom(actor="reviewer", action="archive",
                                                                        object="Report.py", modality="permitted")})
    value = payload(ast)
    before = deepcopy(value)
    result = subject.validate_rich_dcec_payload(value)
    assert result["passed"] is True
    assert result["native_ast"] == result["independent_ast"] == value["ast"]
    assert result["full_input_consumed"] and result["independent_structure_equal"]
    assert result["native_parse_passed"] and result["native_reparse_passed"]
    assert result["free_variables"] == [] and result["ground_only"] is True
    assert result["source"] == value["source"] and value == before
    assert result["source_candidate_replay_required"] is True
    assert all(result[key] is False for key in subject.FALSE)
    assert "not_full_DCEC_or_timed_events" in result["scope"]


def test_distinct_intention_agents_and_action_actor_bindings_are_preserved():
    ast = {"kind": "and", "left": atom(actor="Alice", modality="intended"),
           "right": atom(actor="Bob", modality="intended")}
    result = subject.validate_rich_dcec_payload(payload(ast))
    left, right = result["native_ast"]["formulas"]
    assert left["agent"]["function"]["name"] != right["agent"]["function"]["name"]
    for node in (left, right):
        assert node["agent"]["function"]["return_sort"] == {"node_type": "Sort", "name": "agent", "parent": None}
        assert node["agent"]["function"]["name"] == node["formula"]["arguments"][0]["function"]["name"]
        assert node["formula"]["arguments"][0]["function"]["return_sort"]["name"] == "Object"


@pytest.mark.parametrize("suffix", [" junk", ",O(x)", ")", ";", " # comment", "\x00", "\u00a0", " O(x)"])
def test_full_consumption_and_unsupported_tokens_fail_before_native_parse(monkeypatch, suffix):
    value = payload()
    value["source"] += suffix
    monkeypatch.setattr(subject.dcec_integration, "parse_dcec_string", lambda text: pytest.fail("bad input reached native parser"))
    with pytest.raises(ValueError):
        subject.validate_rich_dcec_payload(value)


@pytest.mark.parametrize("operator", ["forall", "exists", "always", "eventually", "next", "K", "B", "Happens",
                                      "holds_at", "Unknown", "o", "AND", "iff"])
def test_unknown_or_unsupported_operators_cannot_be_ordinary_predicates(monkeypatch, operator):
    value = payload(atom())
    value["source"] = operator + value["source"][1:]
    monkeypatch.setattr(subject.dcec_integration, "parse_dcec_string", lambda text: pytest.fail("unsupported operator reached native parser"))
    with pytest.raises(ValueError):
        subject.validate_rich_dcec_payload(value)


@pytest.mark.parametrize("text", ["O()", "O(a,b)", "P(a,b,c)", "F(a,b)", "I(a)", "I(a,b,c)",
    "and(a)", "and(a,b,c)", "or(a)", "implies(a)", "implies(a,b,c)", "not(a,b)",
    "O(,a)", "O(a,)", "O((a))", "O[a](b)", "O(a", "", "()"])
def test_malformed_and_wrong_operator_arities_refuse_without_native_cleaning(monkeypatch, text):
    value = payload(atom())
    value["source"] = text
    monkeypatch.setattr(subject.dcec_integration, "parse_dcec_string", lambda text: pytest.fail("malformed formula reached native parser"))
    with pytest.raises(ValueError):
        subject.validate_rich_dcec_payload(value)


@pytest.mark.parametrize("replacement", ["free_variable", "S" + "0" * 64, "Function(Other)", "42", '"quoted"'])
def test_free_variables_functions_and_undeclared_symbols_are_not_ground_terms(monkeypatch, replacement):
    value = payload(atom())
    symbol = next(row["symbol"] for row in value["symbols"] if row["role"] == "slot")
    value["source"] = value["source"].replace(symbol, replacement)
    monkeypatch.setattr(subject.dcec_integration, "parse_dcec_string", lambda text: pytest.fail("invalid term reached native parser"))
    with pytest.raises(ValueError):
        subject.validate_rich_dcec_payload(value)


@pytest.mark.parametrize("mutation", ["missing", "extra", "duplicate", "digest", "role", "source_sort", "surface", "wrong_symbol"])
def test_symbol_table_has_exact_coverage_types_and_role_value_hash_binding(mutation):
    value = payload()
    if mutation == "missing":
        value["symbols"].pop()
    elif mutation == "extra":
        row = {"role": "slot", "value": {"surface": "other", "sort": "Entity"}}
        row["symbol"] = "S" + subject._digest([row["role"], row["value"]])
        value["symbols"].append(row)
    elif mutation == "duplicate":
        value["symbols"].append(deepcopy(value["symbols"][0]))
    elif mutation == "digest":
        value["symbols"][0]["symbol"] = "S" + "0" * 64
    elif mutation == "role":
        value["symbols"][0]["role"] = "ordinary_operator"
    elif mutation in {"source_sort", "surface"}:
        row = next(row for row in value["symbols"] if row["role"] == "slot")
        row["value"]["sort" if mutation == "source_sort" else "surface"] = "Agent" if mutation == "source_sort" else "Wrong.py"
    else:
        value["symbols"][0]["symbol"] = 1
    with pytest.raises(ValueError):
        subject.validate_rich_dcec_payload(value)


@pytest.mark.parametrize("mutation", ["operator", "guard_order", "argument_order", "predicate_arity", "sort",
    "sort_parent", "agent", "context", "extra_field", "bool_instead_of_null", "ast_digest"])
def test_complete_declared_ast_is_independently_checked_even_after_digest_refresh(mutation):
    value = payload()
    root = value["ast"]
    body = root["formulas"][1]
    if mutation == "operator":
        body["operator"]["value"] = "F"
    elif mutation == "guard_order":
        root["formulas"].reverse()
    elif mutation == "argument_order":
        body["formula"]["arguments"].reverse()
    elif mutation == "predicate_arity":
        body["formula"]["predicate"]["argument_sorts"].pop()
    elif mutation in {"sort", "sort_parent"}:
        sort = body["formula"]["arguments"][0]["function"]["return_sort"]
        sort["name" if mutation == "sort" else "parent"] = "agent"
    elif mutation == "agent":
        body["agent"] = deepcopy(body["formula"]["arguments"][0])
    elif mutation == "context":
        body["context"] = "lost-context"
    elif mutation == "extra_field":
        root["ignored"] = True
    elif mutation == "bool_instead_of_null":
        body["agent"] = False
    value["ast_sha256"] = "0" * 64 if mutation == "ast_digest" else subject._digest(root)
    with pytest.raises(ValueError, match="complete declared native AST"):
        subject.validate_rich_dcec_payload(value)


def test_native_parser_semantic_change_is_rejected_after_independent_parse(monkeypatch):
    value = payload()
    native = subject.dcec_integration.parse_dcec_string(value["source"])
    native.formulas[1].operator = subject.dcec_core.DeonticOperator.PERMISSION
    monkeypatch.setattr(subject.dcec_integration, "parse_dcec_string", lambda text: native)
    with pytest.raises(ValueError, match="native DCEC parser changed"):
        subject.validate_rich_dcec_payload(value)


def test_native_reparse_is_checked_again(monkeypatch):
    value = payload()
    original = subject.dcec_integration.parse_dcec_string
    calls = []

    def changing(text):
        node = original(text)
        calls.append(text)
        if len(calls) == 2:
            node.formulas.reverse()
        return node

    monkeypatch.setattr(subject.dcec_integration, "parse_dcec_string", changing)
    with pytest.raises(ValueError, match="reparse changed"):
        subject.validate_rich_dcec_payload(value)
    assert len(calls) == 2


def test_intention_cannot_change_actor_while_using_declared_agent_symbols():
    ast = {"kind": "and", "left": atom(actor="Alice", modality="intended"),
           "right": atom(actor="Bob", modality="intended")}
    value = payload(ast)
    alice, bob = [node["agent"]["function"]["name"] for node in value["ast"]["formulas"]]
    value["source"] = value["source"].replace("I(" + alice, "I(" + bob, 1)
    with pytest.raises(ValueError, match="intention agent differs"):
        subject.validate_rich_dcec_payload(value)


@pytest.mark.parametrize("key,value", [("native_parse_passed", 1), ("native_structure_checked", False),
    ("backend_proof_executed", True), ("typed_slot_specializations_applied", True), ("slot_declarations_sha256", None)])
def test_input_receipts_cannot_supply_authority_or_implicit_schema_defaults(key, value):
    original = payload()
    original[key] = value
    with pytest.raises(ValueError):
        subject.validate_rich_dcec_payload(original)


def test_source_and_json_bounds_are_enforced_without_truncation():
    for source in ("x" * (subject.MAX_BYTES + 1), "f(" * 34 + "x" + ")" * 34,
                   "f(" + ",".join(["x"] * 1100) + ")"):
        with pytest.raises(ValueError):
            subject._parse(source)
    value = payload()
    value["unexpected"] = None
    with pytest.raises(ValueError, match="closed rich DCEC"):
        subject.validate_rich_dcec_payload(value)


def test_old_generic_gate_remains_blocked_and_no_infix_workaround_is_used():
    from ipfs_datasets_py.logic.autoformal.family_qualification import validate_family_artifact
    value = payload()
    old = validate_family_artifact("dcec", value["source"])
    assert old["passed"] is False
    new = subject.validate_rich_dcec_payload(value)
    assert new["passed"] is True and new["source"] == value["source"]
    assert new["formula_rewritten"] is False
