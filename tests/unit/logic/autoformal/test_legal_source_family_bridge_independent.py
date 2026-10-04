"""Meaning-loss mutations and finite models independent of bridge rendering.

These are synthetic declared-interpretation tests. They are not adjudicated
statutory references and do not identify source text with its supplied formula.
"""
from copy import deepcopy
import hashlib
from itertools import product
import json

import pytest

from ipfs_datasets_py.logic.autoformal import legal_source_family_bridge as bridge
from tests.unit.logic.autoformal.test_legal_source_family_lake import request


def independent_digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def richer_request(family="tdfol", modality="O"):
    value = request(family, qualifiers=True)
    source = "agency must file record if registered if notified unless exempt unless suspended."
    candidate = value["candidate"]
    candidate.update(source_text=source, source_sha256=hashlib.sha256(source.encode()).hexdigest())
    rule = candidate["canonical_ir"]["rules"][0]
    rule.update(modality=modality, conditions=["if notified", "if registered"],
        exceptions=["unless exempt", "unless suspended"])
    interpretation = bridge.interpretation_skeleton(candidate)
    interpretation.update(activation_scope="all_conditions_at_evaluation_time",
        exception_scope="any_exception_waives_at_evaluation_time")
    for facet, names in (("conditions", ["Notified", "Registered"]), ("exceptions", ["Exempt", "Suspended"])):
        for binding, name in zip(interpretation["rules"][0][facet], names):
            binding["expression"] = {"op": "atom", "predicate": {"name": name, "arguments": ["agency"]}}
    def span(text, canonical=None):
        start = source.index(text)
        return {"start_char": start, "end_char": start + len(text), "source_text": text,
                "canonical_value": text if canonical is None else canonical}
    value["interpretation"] = interpretation
    value["occurrence_bindings"] = [{"occurrence_id": "occ-0", "rule_index": 0,
        "start_char": 0, "end_char": len(source), "source_text": source,
        "facets": {"modality": span("must", modality), "actor": span("agency"), "action": span("file"),
            "object": span("record"), "conditions": [span(x) for x in rule["conditions"]],
            "exceptions": [span(x) for x in rule["exceptions"]], "temporal": []}}]
    return value


def evaluate(ast, symbols, atoms, modal):
    """Independent finite interpretation for the actual returned native AST."""
    if type(ast) is bool:
        return ast
    kind = ast["node_type"]
    if kind in ("Predicate", "AtomicFormula"):
        name = ast["name"] if kind == "Predicate" else ast["predicate"]["name"]
        arguments = []
        for term in ast["arguments"]:
            if term["node_type"] == "Constant":
                arguments.append(symbols[term["name"]]["value"])
            else:
                assert term["node_type"] == "FunctionTerm" and term["arguments"] == []
                arguments.append(symbols[term["function"]["name"]]["value"])
        return atoms[(symbols[name]["value"], tuple(arguments))]
    if kind == "DeonticFormula":
        assert ast.get("agent") is None and ast.get("context") is None
        return modal(ast["operator"]["value"], evaluate(ast["formula"], symbols, atoms, modal))
    if kind == "UnaryFormula":
        assert ast["operator"]["value"] == "¬"
        return not evaluate(ast["formula"], symbols, atoms, modal)
    assert kind == "BinaryFormula"
    left, right = (evaluate(ast[key], symbols, atoms, modal) for key in ("left", "right"))
    return {"∧": lambda: left and right, "∨": lambda: left or right,
            "→": lambda: not left or right}[ast["operator"]["value"]]()


def atom_values(c1=True, c2=True, e1=False, e2=False, action=False):
    return {("Registered", ("agency",)): c1, ("Notified", ("agency",)): c2,
        ("Exempt", ("agency",)): e1, ("Suspended", ("agency",)): e2,
        ("file", ("agency", "record")): action, ("file", ("record", "agency")): not action}


@pytest.mark.parametrize("family", ["deontic_fol", "tdfol"])
@pytest.mark.parametrize("modality", ["O", "P", "F"])
def test_actual_native_ast_matches_independent_full_boolean_truth_table(family, modality):
    report = bridge.prepare_source_family(**richer_request(family, modality))
    ast = report["formulas"][0]["native_ast"]
    symbols = {row["symbol"]: row for row in report["symbol_table"]}
    for c1, c2, e1, e2, action in product((False, True), repeat=5):
        for permitted_modalities in (set(), {"O"}, {"P"}, {"F"}, {"O", "P", "F"}):
            modal = lambda op, body: op in permitted_modalities and body
            expected = not (c1 and c2 and not (e1 or e2)) or (modality in permitted_modalities and action)
            assert evaluate(ast, symbols, atom_values(c1, c2, e1, e2, action), modal) == expected
    assert report["source_semantics_verified"] is report["cross_family_equivalence_verified"] is False


@pytest.mark.parametrize("modality", ["O", "P", "F"])
def test_dcec_native_object_terms_and_modalities_have_distinct_interpretations(modality):
    inputs = request("dcec")
    inputs["candidate"]["canonical_ir"]["rules"][0]["modality"] = modality
    inputs["occurrence_bindings"][0]["facets"]["modality"]["canonical_value"] = modality
    inputs["interpretation"] = bridge.interpretation_skeleton(inputs["candidate"])
    inputs["interpretation"].update(activation_scope="all_conditions_at_evaluation_time",
        exception_scope="any_exception_waives_at_evaluation_time")
    report = bridge.prepare_source_family(**inputs)
    symbols = {row["symbol"]: row for row in report["symbol_table"]}
    for selected in ("O", "P", "F"):
        for action in (False, True):
            assert evaluate(report["formulas"][0]["native_ast"], symbols,
                atom_values(action=action), lambda op, body: op == selected and body) == (modality == selected and action)


def mutate_ast(ast, mutation):
    value = deepcopy(ast)
    if mutation == "drop_exception": value["left"] = value["left"]["left"]
    elif mutation == "drop_condition": value["left"] = value["left"]["right"]
    elif mutation == "condition_or": value["left"]["left"]["operator"]["value"] = "∨"
    elif mutation == "exception_and": value["left"]["right"]["formula"]["operator"]["value"] = "∧"
    elif mutation == "modality": value["right"]["operator"]["value"] = "P"
    elif mutation == "swap_roles": value["right"]["formula"]["arguments"].reverse()
    elif mutation == "guard_inside_modal":
        value = deepcopy(ast["right"])
        value["formula"] = {"node_type": "BinaryFormula", "operator": {"enum": "LogicOperator", "value": "→"},
                            "left": deepcopy(ast["left"]), "right": deepcopy(ast["right"]["formula"])}
    elif mutation == "true": value = True
    else: raise AssertionError(mutation)
    return value


COUNTERMODELS = [
    ("drop_exception", atom_values(e1=True), "identity"),
    ("drop_condition", atom_values(c1=False), "identity"),
    ("condition_or", atom_values(c2=False), "identity"),
    ("exception_and", atom_values(e1=True), "identity"),
    ("modality", atom_values(action=True), "permission_only"),
    ("swap_roles", atom_values(action=True), "identity"),
    ("guard_inside_modal", atom_values(c1=False), "always_false"),
    ("true", atom_values(), "identity"),
]


@pytest.mark.parametrize("mutation,atoms,modal_name", COUNTERMODELS)
def test_mutants_have_explicit_distinguishing_models_and_recomputed_hashes_fail(mutation, atoms, modal_name):
    inputs = richer_request()
    report = bridge.prepare_source_family(**inputs)
    ast = report["formulas"][0]["native_ast"]
    mutant = mutate_ast(ast, mutation)
    modal = {"identity": lambda op, body: body,
             "permission_only": lambda op, body: op == "P" and body,
             "always_false": lambda op, body: False}[modal_name]
    symbols = {row["symbol"]: row for row in report["symbol_table"]}
    assert evaluate(ast, symbols, atoms, modal) != evaluate(mutant, symbols, atoms, modal)
    forged = deepcopy(report)
    formula = forged["formulas"][0]
    for target in (formula, formula["native_receipt"]):
        target["native_ast"] = mutant
        target["native_ast_sha256"] = independent_digest(mutant)
    forged.pop("report_sha256")
    forged["report_sha256"] = independent_digest(forged)
    assert forged["report_sha256"] == independent_digest({k: v for k, v in forged.items() if k != "report_sha256"})
    with pytest.raises(ValueError, match="authoritative regeneration"):
        bridge.validate_source_family(forged, **inputs)


@pytest.mark.parametrize("mutation", ["occurrence", "symbol", "canonical", "modality", "context", "family", "lean",
    "unknown_symbol", "arity", "extra_ast", "modal_annotation"])
def test_report_mutations_do_not_become_authority_when_all_direct_hashes_recomputed(mutation):
    inputs = request()
    forged = deepcopy(bridge.prepare_source_family(**inputs))
    if mutation == "occurrence":
        forged["occurrence_bindings"][0]["occurrence_id"] = "rewritten-identity"
        forged["occurrence_bindings_sha256"] = independent_digest(forged["occurrence_bindings"])
        forged["formulas"][0]["occurrence_sha256"] = independent_digest(forged["occurrence_bindings"][0])
    if mutation == "symbol": forged["symbol_table"][0]["value"] = "invented meaning"
    if mutation == "canonical":
        forged["canonical_roundtrip"]["rules"][0]["actor"] = "record"
        forged["canonical_ir_sha256"] = independent_digest(forged["canonical_roundtrip"])
    if mutation == "modality": forged["formulas"][0]["native_ast"]["operator"]["value"] = "F"
    if mutation == "context": forged["modal_context"] = "explicit-clock:instantaneous"
    if mutation == "family": forged["family"] = "fol"
    if mutation == "lean": forged["lean_body"] = "def formula_0 : Prop := True"
    if mutation == "unknown_symbol": forged["formulas"][0]["native_ast"]["formula"]["name"] = "UnboundPredicate"
    if mutation == "arity": forged["formulas"][0]["native_ast"]["formula"]["arguments"].pop()
    if mutation == "extra_ast": forged["formulas"][0]["native_ast"]["extra_conjunct"] = {"True": True}
    if mutation == "modal_annotation": forged["formulas"][0]["native_ast"]["context"] = "explicit-clock:instantaneous"
    if mutation in {"modality", "unknown_symbol", "arity", "extra_ast", "modal_annotation"}:
        changed = forged["formulas"][0]
        changed["native_ast_sha256"] = independent_digest(changed["native_ast"])
        changed["native_receipt"]["native_ast"] = deepcopy(changed["native_ast"])
        changed["native_receipt"]["native_ast_sha256"] = changed["native_ast_sha256"]
    forged.pop("report_sha256")
    forged["report_sha256"] = independent_digest(forged)
    with pytest.raises(ValueError, match="authoritative regeneration"):
        bridge.validate_source_family(forged, **inputs)


@pytest.mark.parametrize("mutation", ["source_hash", "facet_shift", "wrong_canonical_span", "missing_exception",
    "scope", "context", "empty_expression", "tautology_expression", "extra_rule"])
def test_incomplete_or_incompatible_source_interpretations_fail_closed(mutation):
    value = request(qualifiers=True)
    if mutation == "source_hash": value["candidate"]["source_sha256"] = "0" * 64
    if mutation == "facet_shift": value["occurrence_bindings"][0]["facets"]["actor"]["start_char"] += 1
    if mutation == "wrong_canonical_span": value["occurrence_bindings"][0]["facets"]["actor"]["canonical_value"] = "record"
    if mutation == "missing_exception": value["interpretation"]["rules"][0]["exceptions"] = []
    if mutation == "scope": value["interpretation"]["exception_scope"] = "inside_modality"
    if mutation == "context": value["interpretation"]["modal_context"] = "explicit-clock:instantaneous"
    if mutation == "empty_expression": value["interpretation"]["rules"][0]["conditions"][0]["expression"] = {"op": "all", "operands": []}
    if mutation == "tautology_expression": value["interpretation"]["rules"][0]["conditions"][0]["expression"] = {"op": "True"}
    if mutation == "extra_rule": value["candidate"]["canonical_ir"]["rules"].append(deepcopy(value["candidate"]["canonical_ir"]["rules"][0]))
    with pytest.raises(ValueError):
        bridge.prepare_source_family(**value)


def test_duplicate_rule_occurrences_survive_with_distinct_source_intervals():
    value = request()
    original = value["candidate"]["source_text"]
    source = original + " " + original
    value["candidate"].update(source_text=source, source_sha256=hashlib.sha256(source.encode()).hexdigest())
    value["interpretation"] = bridge.interpretation_skeleton(value["candidate"])
    value["interpretation"].update(activation_scope="all_conditions_at_evaluation_time",
        exception_scope="any_exception_waives_at_evaluation_time")
    second = deepcopy(value["occurrence_bindings"][0])
    second["occurrence_id"] = "occ-1"
    shift = len(original) + 1
    def shift_offsets(node):
        if type(node) is dict:
            for key, child in node.items():
                if key in {"start_char", "end_char"}: node[key] += shift
                else: shift_offsets(child)
        elif type(node) is list:
            for child in node: shift_offsets(child)
    shift_offsets(second)
    value["occurrence_bindings"].append(second)
    report = bridge.prepare_source_family(**value)
    assert report["canonical_roundtrip"] == value["candidate"]["canonical_ir"]
    assert len(report["formulas"]) == 2
    assert report["formulas"][0]["native_ast"] == report["formulas"][1]["native_ast"]
    assert report["formulas"][0]["occurrence_sha256"] != report["formulas"][1]["occurrence_sha256"]
    assert "Occurrence0001" in report["lean_body"]
    forged = deepcopy(report)
    forged["formulas"].pop()
    forged["occurrence_bindings"].pop()
    forged["occurrence_bindings_sha256"] = independent_digest(forged["occurrence_bindings"])
    forged.pop("report_sha256")
    forged["report_sha256"] = independent_digest(forged)
    with pytest.raises(ValueError, match="authoritative regeneration"):
        bridge.validate_source_family(forged, **value)


@pytest.mark.parametrize("family", ["fol", "temporal_fol", "frame_logic", "higher_order", "transition_system"])
def test_deontic_force_cannot_be_dropped_to_an_incompatible_family(family):
    with pytest.raises(ValueError, match="normative force"):
        bridge.prepare_source_family(**request(family))


@pytest.mark.parametrize("literal", ["within 30 days", "before 2030-01-01", "for at least 2 hours"])
def test_tdfol_route_does_not_hide_temporal_facets_as_opaque_predicates(literal):
    value = request("tdfol")
    value["candidate"]["canonical_ir"]["rules"][0]["temporal"] = [literal]
    with pytest.raises(ValueError, match="another explicit profile"):
        bridge.prepare_source_family(**value)


def test_source_bytes_do_not_verify_declared_modality_meaning():
    # Deliberately mismatched natural-language cue: the bridge is a declared
    # structural compiler, so accepting its bytes must never assert fidelity.
    value = richer_request(modality="P")
    assert value["occurrence_bindings"][0]["facets"]["modality"]["source_text"] == "must"
    report = bridge.prepare_source_family(**value)
    assert report["canonical_roundtrip"]["rules"][0]["modality"] == "P"
    assert report["source_semantics_verified"] is report["admitted"] is False


def test_dcec_qualified_rule_has_no_fallback_to_qualifier_free_norm():
    with pytest.raises(ValueError, match="qualifier-free"):
        bridge.prepare_source_family(**request("dcec", qualifiers=True))
