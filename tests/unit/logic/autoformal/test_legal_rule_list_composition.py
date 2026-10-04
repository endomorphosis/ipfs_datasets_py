from copy import deepcopy
import pytest

from ipfs_datasets_py.logic.autoformal import legal_rule_list_composition as subject
from scripts.ops.legal_ir.check_legal_calendar_decoder_outputs import synthetic_interpretation, POLICY


def rule(actor="Zulu Agency", *, modality="O", action="retain", obj="reports", conditions=(), exceptions=(), temporal=()):
    return {"modality": modality, "actor": actor, "action": action, "object": obj,
        "conditions": list(conditions), "exceptions": list(exceptions), "temporal": list(temporal)}


def fixtures():
    clauses = [
        ("Zulu Agency must retain reports if approval holds.", rule(conditions=["approval holds"])),
        ("Alpha Board may publish notices before 2075-01-01.", rule("Alpha Board", modality="P", action="publish", obj="notices", temporal=["before 2075-01-01"])),
        ("Zulu Agency must retain reports if approval holds.", rule(conditions=["approval holds"])),
        ("Beta Office must not disclose records unless consent remains valid.", rule("Beta Office", modality="F", action="disclose", obj="records", exceptions=["consent remains valid"]))]
    text = "\n".join(t for t, _ in clauses)
    source = {"candidate_id": "authored:four-clauses", "source_text": text, "source_sha256": subject.text_sha256(text)}
    declarations, predictions, offset = [], [], 0
    for index, (clause, ir) in enumerate(clauses):
        identity = "clause-" + str(index)
        declarations.append({"clause_id": identity, "char_start": offset, "char_end": offset + len(clause), "scope": deepcopy(subject.FLAT_SCOPE)})
        attachments = {}
        for field in subject.SPAN_FIELDS:
            atoms = ir[field] if field in subject.QUALIFIERS else ([ir[field]] if ir[field] else [])
            attachments[field] = [{"char_start": offset + clause.index(atom), "char_end": offset + clause.index(atom) + len(atom)} for atom in atoms]
        predictions.append({"clause_id": identity, "clause_source_sha256": subject.text_sha256(clause), "rule": ir,
            "attachments": attachments, "scope": deepcopy(subject.FLAT_SCOPE)})
        offset += len(clause) + 1
    plan = subject.prepare_source_plan(source, declarations)
    return plan, predictions


def compose(plan, predictions):
    return subject.compose_rule_list(plan, predictions, expected_plan_sha256=plan["plan_sha256"])


def test_sorted_canonical_projection_roundtrips_source_order_and_duplicate_occurrences():
    plan, predictions = fixtures()
    before = deepcopy((plan, predictions))
    result = compose(plan, predictions)
    assert (plan, predictions) == before
    assert result["rule_count"] == 4
    assert result["canonical_to_source_ordinal"] == [3, 0, 2, 1]
    assert result["source_rule_list"][0] == result["source_rule_list"][2]
    assert result["occurrences"][0]["canonical_rule_index"] != result["occurrences"][2]["canonical_rule_index"]
    assert subject.reconstruct_source_rule_list(result, expected_plan_sha256=plan["plan_sha256"]) == [p["rule"] for p in predictions]
    assert result["duplicate_rule_occurrences_preserved"] and result["source_order_preserved_in_ledger"]
    assert all(result[key] is False for key in subject.FALSE)


def test_existing_calendar_route_reverses_all_four_rules_without_new_compiler():
    plan, predictions = fixtures()
    result = compose(plan, predictions)
    candidate = subject.calendar_candidate(result, expected_plan_sha256=plan["plan_sha256"])
    interpretation = synthetic_interpretation(candidate, policy=POLICY)
    prepared = subject.prepare_calendar_composition(result, interpretation, expected_plan_sha256=plan["plan_sha256"])
    assert len(prepared["lowering"]["native_projection"]["payload"]["formulas"]) == 4
    assert prepared["canonical_to_source_ordinal"] == [3, 0, 2, 1]
    assert prepared["lowering"]["original_canonical_ir"] == result["canonical_ir"]
    assert prepared["lowering"]["lean_body"].count("def qualifiedLegalFormula_") == 4


@pytest.mark.parametrize("mutation", ["drop_prediction", "duplicate_prediction", "swap_predictions", "wrong_clause_sha"])
def test_every_declared_clause_requires_exactly_one_ordered_prediction(mutation):
    plan, predictions = fixtures()
    if mutation == "drop_prediction": predictions.pop()
    if mutation == "duplicate_prediction": predictions[1] = deepcopy(predictions[0])
    if mutation == "swap_predictions": predictions[0], predictions[1] = predictions[1], predictions[0]
    if mutation == "wrong_clause_sha": predictions[0]["clause_source_sha256"] = "0" * 64
    with pytest.raises(ValueError): compose(plan, predictions)


@pytest.mark.parametrize("mutation", ["drop_canonical_rule", "drop_occurrence", "deduplicate_source_rules", "swap_permutation", "change_pointer"])
def test_composed_outputs_cannot_drop_or_reassign_occurrences_even_with_rehashed_outer_payload(mutation):
    plan, predictions = fixtures()
    result = compose(plan, predictions)
    if mutation == "drop_canonical_rule": result["canonical_ir"]["rules"].pop()
    if mutation == "drop_occurrence": result["occurrences"].pop()
    if mutation == "deduplicate_source_rules": result["source_rule_list"].pop(2)
    if mutation == "swap_permutation": result["canonical_to_source_ordinal"][0:2] = [0, 3]
    if mutation == "change_pointer": result["occurrences"][0]["attachments"]["actor"][0]["char_start"] += 1
    result["composition_sha256"] = subject.digest({k: v for k, v in result.items() if k != "composition_sha256"})
    with pytest.raises(ValueError, match="composition rule coverage"):
        subject.validate_composition(result, expected_plan_sha256=plan["plan_sha256"])


def test_identical_atom_from_duplicate_clause_cannot_be_borrowed():
    plan, predictions = fixtures()
    predictions[0]["attachments"]["actor"] = deepcopy(predictions[2]["attachments"]["actor"])
    with pytest.raises(ValueError, match="cross-clause"):
        compose(plan, predictions)


def test_explicit_coordinates_disambiguate_repeated_same_atom_within_clause():
    text = "Agency must notify Agency."
    source = {"candidate_id": "repeat", "source_text": text, "source_sha256": subject.text_sha256(text)}
    plan = subject.prepare_source_plan(source, [{"clause_id": "one", "char_start": 0, "char_end": len(text), "scope": subject.FLAT_SCOPE}])
    ir = rule("Agency", action="notify", obj="Agency")
    attachments = {"actor": [{"char_start": 0, "char_end": 6}], "action": [{"char_start": 12, "char_end": 18}],
        "object": [{"char_start": 19, "char_end": 25}], "conditions": [], "exceptions": [], "temporal": []}
    predictions = [{"clause_id": "one", "clause_source_sha256": source["source_sha256"], "rule": ir,
        "attachments": attachments, "scope": subject.FLAT_SCOPE}]
    assert compose(plan, predictions)["rule_count"] == 1
    predictions[0]["attachments"]["object"] = deepcopy(attachments["actor"])
    with pytest.raises(ValueError, match="overlap"):
        compose(plan, predictions)


@pytest.mark.parametrize("scope", [{"kind": "nested_if", "parent_clause_id": None, "shared_qualifier_scope": None},
    {"kind": "independent_flat_rule", "parent_clause_id": "clause-0", "shared_qualifier_scope": None},
    {"kind": "independent_flat_rule", "parent_clause_id": None, "shared_qualifier_scope": "all_following_rules"}])
def test_declared_nested_or_shared_scope_rejected_without_collapsing(scope):
    plan, predictions = fixtures()
    predictions[1]["scope"] = scope
    with pytest.raises(ValueError, match="unsupported nested"):
        compose(plan, predictions)


@pytest.mark.parametrize("conditions", [["approval holds", "approval holds"], ["z condition", "a condition"]])
def test_noncanonical_qualifier_lists_are_rejected_instead_of_normalized(conditions):
    plan, predictions = fixtures()
    predictions[0]["rule"]["conditions"] = conditions
    with pytest.raises(ValueError, match="normalization"):
        compose(plan, predictions)


def test_plan_cannot_hide_clause_in_unassigned_source_text():
    plan, _ = fixtures()
    declarations = [{k: c[k] for k in ("clause_id", "char_start", "char_end", "scope")} for c in plan["clauses"]]
    for dropped in (declarations[1:], declarations[:-1], [declarations[0], *declarations[2:]]):
        with pytest.raises(ValueError, match="unassigned non-whitespace"):
            subject.prepare_source_plan(plan["source"], dropped)


def test_external_inventory_commitment_rejects_replaced_plan():
    plan, predictions = fixtures()
    expected = plan["plan_sha256"]
    changed = deepcopy(plan)
    changed["source"]["candidate_id"] = "replacement"
    changed["plan_sha256"] = subject.digest({k: v for k, v in changed.items() if k != "plan_sha256"})
    with pytest.raises(ValueError, match="external commitment"):
        subject.compose_rule_list(changed, predictions, expected_plan_sha256=expected)


def test_unfilled_interpretations_cannot_lower_successfully():
    plan, predictions = fixtures()
    result = compose(plan, predictions)
    candidate = subject.calendar_candidate(result, expected_plan_sha256=plan["plan_sha256"])
    skeleton = subject.calendar.interpretation_skeleton(candidate)
    with pytest.raises(ValueError):
        subject.prepare_calendar_composition(result, skeleton, expected_plan_sha256=plan["plan_sha256"])


def test_attach_existing_span_prediction_translates_only_local_coordinates():
    plan, predictions = fixtures()
    clause, expected = plan["clauses"][1], predictions[1]
    facets = {}
    for field, pointers in expected["attachments"].items():
        atom = (expected["rule"][field][0] if field in subject.QUALIFIERS else expected["rule"][field]) if pointers else None
        facets[field] = {"present": bool(pointers), "char_start": pointers[0]["char_start"] - clause["char_start"] if pointers else None,
            "char_end": pointers[0]["char_end"] - clause["char_start"] if pointers else None, "text": atom}
    prediction = {"status": "decoded", "source_sha256": clause["source_sha256"], "target_access": False, "teacher_forcing": False,
        "canonical_ir": {"rules": [expected["rule"]]}, "span_diagnostics": {"facets": facets}}
    attached = subject.attach_span_prediction(plan, clause["clause_id"], prediction, scope=subject.FLAT_SCOPE, expected_plan_sha256=plan["plan_sha256"])
    assert attached == expected
    prediction["source_sha256"] = plan["clauses"][0]["source_sha256"]
    with pytest.raises(ValueError, match="free single-clause"):
        subject.attach_span_prediction(plan, clause["clause_id"], prediction, scope=subject.FLAT_SCOPE, expected_plan_sha256=plan["plan_sha256"])


@pytest.mark.parametrize("offset", [True, 0.0, -1, 1])
def test_invalid_or_subtoken_atom_offsets_are_rejected(offset):
    plan, predictions = fixtures()
    predictions[0]["attachments"]["actor"][0]["char_start"] = offset
    with pytest.raises(ValueError): compose(plan, predictions)
