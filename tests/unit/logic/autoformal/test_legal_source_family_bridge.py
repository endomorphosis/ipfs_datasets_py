"""Source occurrence integrity and actual native structure for the new profile."""
from copy import deepcopy
import hashlib

import pytest

from ipfs_datasets_py.logic.autoformal import legal_source_family_bridge as bridge
from ipfs_datasets_py.logic.legal_ir.canonical_contracts import CanonicalRoundTripIR


def case(*, modality="O", qualified=True, repeat=False, actor="Agency", action="retain", obj="records"):
    cue = {"O": "must", "P": "may", "F": "shall not"}[modality]
    clause = f"{actor} {cue} {action}" + (" " + obj if obj else "")
    clause += " if licensed and active unless exempt or waived." if qualified else "."
    source = clause + (" " + clause if repeat else "")
    rule = {"modality": modality, "actor": actor, "action": action, "object": obj,
            "conditions": ["licensed", "active"] if qualified else [],
            "exceptions": ["exempt", "waived"] if qualified else [], "temporal": []}
    ir = CanonicalRoundTripIR.from_dict({"rules": [rule]}).to_dict()
    rule = ir["rules"][0]
    candidate = {"candidate_id": "candidate-test", "source_text": source,
                 "source_sha256": hashlib.sha256(source.encode()).hexdigest(), "canonical_ir": ir}
    interpretation = bridge.interpretation_skeleton(candidate)
    interpretation.update(activation_scope=bridge.ACTIVATION_SCOPE, exception_scope=bridge.EXCEPTION_SCOPE)
    for facet in ("conditions", "exceptions"):
        for row in interpretation["rules"][0][facet]:
            row["expression"] = {"op": "atom", "predicate": {"name": row["literal"], "arguments": [actor]}}
    occurrences = []
    for index in range(2 if repeat else 1):
        start = index * (len(clause) + 1)

        def span(literal, value=None, offset=0):
            position = source.index(literal, start + offset)
            return {"start_char": position, "end_char": position + len(literal),
                    "source_text": literal, "canonical_value": literal if value is None else value}

        facets = {"modality": span(cue, modality), "actor": span(actor), "action": span(action),
                  "object": span(obj, offset=len(actor)) if obj else None,
                  "conditions": [span(x) for x in rule["conditions"]],
                  "exceptions": [span(x) for x in rule["exceptions"]], "temporal": []}
        occurrences.append({"occurrence_id": "occurrence-" + str(index), "rule_index": 0,
            "start_char": start, "end_char": start + len(clause), "source_text": clause, "facets": facets})
    return candidate, interpretation, occurrences


def prepare(request, family="deontic_fol"):
    return bridge.prepare_source_family(*request, family=family)


@pytest.mark.parametrize("family", ["deontic_fol", "tdfol", "dcec"])
@pytest.mark.parametrize("modality", ["O", "P", "F"])
def test_ground_families_use_real_native_ast_and_preserve_all_modalities(family, modality):
    request = case(modality=modality, qualified=False)
    report = prepare(request, family)
    node = report["formulas"][0]["native_ast"]
    assert node["node_type"] == "DeonticFormula" and node["operator"]["value"] == modality
    assert report["canonical_roundtrip"] == request[0]["canonical_ir"]
    assert report["logic_family"] == {"deontic_fol": "deontic", "tdfol": "tdfol", "dcec": "dcec"}[family]
    assert report["formulas"][0]["native_receipt"]["exact_native_ast_roundtrip"]
    assert "i.modal \"deontic:" + modality + "\"" in report["lean_body"]
    assert "Occurrence0000" in report["lean_body"]
    assert bridge.validate_source_family(report, candidate=request[0], interpretation=request[1],
                                        occurrence_bindings=request[2], family=family)
    assert report["source_bound"] and report["direct_facet_spans_validated"]
    for key in ("source_semantics_verified", "backend_executed", "proof_authority", "admitted",
                "cross_family_equivalence_verified", "old_calendar_gate_equivalence_verified"):
        assert report[key] is False


@pytest.mark.parametrize("family", ["deontic_fol", "tdfol"])
def test_all_conditions_and_any_exception_remain_outside_modality(family):
    report = prepare(case(), family)
    node = report["formulas"][0]["native_ast"]
    assert node["node_type"] == "BinaryFormula" and node["operator"]["value"] == "→"
    assert node["right"]["node_type"] == "DeonticFormula"
    guard = node["left"]
    assert guard["operator"]["value"] == "∧"
    assert guard["left"]["operator"]["value"] == "∧"
    waiver = guard["right"]
    assert waiver["operator"]["value"] == "¬"
    assert waiver["formula"]["operator"]["value"] == "∨"
    assert node["right"]["context"] is None


def test_nested_explicit_qualifier_structure_is_not_flattened():
    request = case()
    expression = request[1]["rules"][0]["conditions"][0]["expression"]
    request[1]["rules"][0]["conditions"][0]["expression"] = {"op": "any", "operands": [
        deepcopy(expression), {"op": "not", "operand": deepcopy(expression)}]}
    report = prepare(request)
    nested = report["formulas"][0]["native_ast"]["left"]["left"]["left"]
    assert nested["operator"]["value"] == "∨"
    assert nested["right"]["operator"]["value"] == "¬"


def test_repeated_equal_rule_occurrences_are_not_collapsed():
    request = case(repeat=True)
    report = prepare(request)
    assert len(report["formulas"]) == 2 and len(report["canonical_roundtrip"]["rules"]) == 1
    first, second = report["formulas"]
    assert first["native_ast"] == second["native_ast"]
    assert first["occurrence_sha256"] != second["occurrence_sha256"]
    assert "Occurrence0001" in report["lean_body"]
    moved = deepcopy(request[2])
    moved[1]["facets"]["actor"] = deepcopy(moved[0]["facets"]["actor"])
    with pytest.raises(ValueError, match="inside"):
        bridge.prepare_source_family(request[0], request[1], moved, family="tdfol")


def test_unicode_and_multiword_atoms_are_reversibly_symbolized():
    request = case(qualified=False, actor="Café bureau", action="retain securely", obj="résumé records")
    report = prepare(request)
    assert report["canonical_roundtrip"] == request[0]["canonical_ir"]
    assert {row["value"] for row in report["symbol_table"]} == {"Café bureau", "retain securely", "résumé records"}
    assert "Café" not in report["lean_body"]


def test_same_entity_in_two_argument_roles_has_one_symbol_and_two_span_bindings():
    request = case(qualified=False, actor="Agency", action="notify", obj="Agency")
    report = prepare(request)
    assert len([row for row in report["symbol_table"] if row["kind"] == "constant"]) == 1
    args = report["formulas"][0]["native_ast"]["formula"]["arguments"]
    assert args[0] == args[1]
    facets = report["occurrence_bindings"][0]["facets"]
    assert facets["actor"]["start_char"] != facets["object"]["start_char"]


def test_absent_object_is_unary_and_requires_no_invented_span():
    request = case(qualified=False, obj="")
    report = prepare(request)
    assert len(report["formulas"][0]["native_ast"]["formula"]["arguments"]) == 1
    request[2][0]["facets"]["object"] = deepcopy(request[2][0]["facets"]["actor"])
    with pytest.raises(ValueError, match="absent object"):
        prepare(request)


@pytest.mark.parametrize("family", ["fol", "first_order", "temporal_fol", "temporal", "frame_logic", "cec"])
def test_other_families_cannot_erase_normative_force(family):
    with pytest.raises(ValueError, match="normative force"):
        prepare(case(qualified=False), family)


def test_dcec_qualifiers_remain_unsupported():
    with pytest.raises(ValueError, match="qualifier-free"):
        prepare(case(), "dcec")


@pytest.mark.parametrize("literal", ["within 30 days", "before 2028-01-01", "always"])
def test_temporal_literal_is_not_hidden_as_a_native_guard(literal):
    candidate, _, _ = case()
    candidate["canonical_ir"]["rules"][0]["temporal"] = [literal]
    with pytest.raises(ValueError, match="temporal and calendar"):
        bridge.interpretation_skeleton(candidate)


@pytest.mark.parametrize("facet", ["conditions", "exceptions"])
def test_recognized_time_literals_cannot_be_smuggled_into_other_qualifier_slots(facet):
    candidate, _, _ = case()
    candidate["canonical_ir"]["rules"][0][facet] = ["within 30 days"]
    with pytest.raises(ValueError, match="temporal literal"):
        bridge.interpretation_skeleton(candidate)


def test_unfilled_or_conflicting_interpretations_fail_closed():
    request = case()
    request = (request[0], bridge.interpretation_skeleton(request[0]), request[2])
    with pytest.raises(ValueError, match="explicit activation"):
        prepare(request)
    request[1].update(activation_scope=bridge.ACTIVATION_SCOPE, exception_scope=bridge.EXCEPTION_SCOPE)
    with pytest.raises(ValueError, match="qualifier_expression"):
        prepare(request)


@pytest.mark.parametrize("change", ["source", "span", "normalization", "modality", "extra", "missing", "overlap", "bool_index"])
def test_source_facet_and_occurrence_joins_reject_corruption(change):
    request = list(case(repeat=True))
    if change == "source":
        request[0]["source_text"] += " "
    elif change == "span":
        request[2][0]["facets"]["actor"]["end_char"] += 1
    elif change == "normalization":
        request[2][0]["facets"]["action"]["canonical_value"] = "Retain"
    elif change == "modality":
        request[2][0]["facets"]["modality"]["canonical_value"] = "P"
    elif change == "extra":
        request[2][0]["facets"]["unmodeled"] = {}
    elif change == "missing":
        request[2][0]["facets"]["conditions"].pop()
    elif change == "overlap":
        request[2][1] = deepcopy(request[2][0])
        request[2][1]["occurrence_id"] = "other"
    else:
        request[2][0]["rule_index"] = False
    with pytest.raises(ValueError):
        prepare(request)


@pytest.mark.parametrize("change", ["operator", "predicate", "scope", "condition", "exception", "source_binding", "authority", "lean"])
def test_repaired_report_hashes_do_not_defeat_authoritative_replay(change):
    request = case()
    report = prepare(request)
    node = report["formulas"][0]["native_ast"]
    if change == "operator":
        node["right"]["operator"]["value"] = "P"
    elif change == "predicate":
        node["right"]["formula"]["name"] = "Unbound"
    elif change == "scope":
        report["interpretation"]["modal_context"] = "explicit-clock:day"
    elif change == "condition":
        node["left"]["left"]["operator"]["value"] = "∨"
    elif change == "exception":
        node["left"]["right"]["formula"]["operator"]["value"] = "∧"
    elif change == "source_binding":
        report["occurrence_bindings"][0]["facets"]["actor"]["start_char"] += 1
    elif change == "authority":
        report["source_semantics_verified"] = True
    else:
        report["lean_body"] = "def substituted : Prop := True"
    report["formulas"][0]["native_ast_sha256"] = bridge.digest(node)
    report["interpretation_sha256"] = bridge.digest(report["interpretation"])
    report["occurrence_bindings_sha256"] = bridge.digest(report["occurrence_bindings"])
    report["report_sha256"] = bridge.digest({k: v for k, v in report.items() if k != "report_sha256"})
    with pytest.raises(ValueError, match="authoritative regeneration"):
        bridge.validate_source_family(report, candidate=request[0], interpretation=request[1],
                                      occurrence_bindings=request[2], family="deontic_fol")


def test_input_objects_are_never_mutated_and_non_json_never_serializes():
    request = case()
    before = deepcopy(request)
    prepare(request)
    assert request == before
    candidate = deepcopy(request[0])
    candidate["canonical_ir"]["rules"][0]["actor"] = object()
    with pytest.raises(ValueError, match="inert JSON"):
        bridge.interpretation_skeleton(candidate)
