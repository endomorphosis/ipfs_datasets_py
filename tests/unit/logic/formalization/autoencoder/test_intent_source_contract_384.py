"""Ground DFOL keeps the complete learned candidate and its source gate."""
from copy import deepcopy

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import intent_source_contract_384 as subject
from ipfs_datasets_py.logic.formalization.autoencoder import family_training_v7 as training
from ipfs_datasets_py.logic.formalization.autoencoder import native_family_lake_v5 as lake
from ipfs_datasets_py.logic.intent_ir.formalize import rich_grammar


def atom(**changes):
    return {"kind": "atom", "actor": "agent", "action": "inspect", "object": "Cache.py",
            "modality": "required", **changes}


def conditional(negative=False, **changes):
    return {"kind": "if", "guard": {"subject": "Cache.py", "property": "ready", "negated": negative},
            "body": atom(**changes)}


def envelope(ast):
    return {"kind": "intent_rich_ast", "document": ast}


def prepare(ast=None, **kwargs):
    ast = conditional() if ast is None else ast
    target = envelope(ast)
    return subject.prepare_family_targets(rich_grammar.ast_to_text(ast), target, **kwargs)


@pytest.mark.parametrize("negative", [False, True])
@pytest.mark.parametrize("modality,operator", [("required", "O"), ("permitted", "P"), ("prohibited", "F")])
def test_conditional_full_guard_polarity_modal_scope_and_ground_family(negative, modality, operator):
    ast = conditional(negative, modality=modality)
    target, source = envelope(ast), rich_grammar.ast_to_text(ast)
    before = deepcopy(target)
    prepared = subject.prepare_family_targets(source, target)
    audit, report = prepared["audit"], prepared["report"]
    native = audit["native_formula"]["payload"]
    root = native["native_ast"]
    assert root["node_type"] == "BinaryFormula" and root["operator"]["value"] == "→"
    assert root["left"]["node_type"] == ("UnaryFormula" if negative else "Predicate")
    if negative:
        assert root["left"]["operator"]["value"] == "¬"
    assert root["right"]["node_type"] == "DeonticFormula"
    assert root["right"]["operator"]["value"] == operator
    assert native["operator_counts"] == {"deontic": 1, "temporal": 0, "quantifier": 0, "predicate": 2}
    assert native["source_meaning_verified"] is False
    assert audit["available_families"] == ["dcec", "deontic", "higher_order", "tdfol"]
    assert len(report["family_inventory"]) == len(report["requested_families"]) == 40
    assert len(audit["missing_requested_families"]) == 36
    assert "first_order" in audit["missing_requested_families"]
    assert "program" in audit["missing_requested_families"]
    assert "temporal" in audit["missing_requested_families"]
    assert audit["supplemental_DFOL"]["included_in_family_report"] is True
    assert audit["ground_structure"]["complete_candidate_structure_equal"]
    assert audit["candidate"] == target == before
    assert audit["source_agreement_audit"]["source_agreement"] is True
    assert all(audit[key] is False for key in subject.FALSE)
    assert report["all_requested_families_available"] is False
    training.validate_family_training_report_v7(report, **prepared["source_inputs"])
    assert subject.validate_prepared(prepared, source, target)


@pytest.mark.parametrize("kind,operator", [("and", "∧"), ("or", "∨")])
@pytest.mark.parametrize("left,right", [("required", "permitted"), ("prohibited", "required")])
def test_binary_complete_modal_branches_preserve_order_and_distinct_referents(kind, operator, left, right):
    ast = {"kind": kind, "left": atom(modality=left),
           "right": atom(actor="reviewer", action="archive", object="Report.py", modality=right)}
    audit = prepare(ast)["audit"]
    native = audit["native_formula"]["payload"]
    assert native["native_ast"]["operator"]["value"] == operator
    assert native["operator_counts"] == {"deontic": 2, "temporal": 0, "quantifier": 0, "predicate": 2}
    assert audit["ground_structure"]["ordered_terms_and_branches_preserved"]
    swapped = prepare({"kind": kind, "left": ast["right"], "right": ast["left"]})["audit"]
    assert swapped["native_formula"]["payload"]["native_ast"] != native["native_ast"]
    assert swapped["candidate_sha256"] != audit["candidate_sha256"]


@pytest.mark.parametrize("modality", ["required", "permitted", "prohibited"])
def test_atom_keeps_existing_payloads_and_adds_distinct_ground_dfol_profile(modality):
    prepared = prepare(atom(modality=modality))
    inputs = {key: value for key, value in prepared["source_inputs"].items() if key != "formula_inputs"}
    base = training.prepare_family_training_targets_v7("intent_ir", **inputs)
    original = {row["projection_id"]: row["payload"] for row in base["projections"]}
    after = {row["projection_id"]: row["payload"] for row in prepared["report"]["projections"]}
    assert len(after) == len(original) + 1
    assert all(after[key] == value for key, value in original.items())
    assert {row["logic_family"] for row in base["projections"]} == set(prepared["audit"]["available_families"])
    new = next(row for row in prepared["report"]["projections"] if row["projection_id"] not in original)
    assert new["logic_family"] == "deontic" and new["profile"] == "deontic_first_order"


@pytest.mark.parametrize("ast,reason", [
    (conditional(modality="intended"), "intention_agency_operator_not_in_tdfol_subset"),
    (conditional(modality="recommended"), "recommendation_has_no_equivalent_strict_deontic_operator"),
    ({"kind": "and", "left": atom(), "right": atom(modality="intended")}, "intention_agency_operator_not_in_tdfol_subset"),
    ({"kind": "or", "left": atom(modality="recommended"), "right": atom()}, "recommendation_has_no_equivalent_strict_deontic_operator"),
    ({"kind": "then", "left": atom(), "right": atom(action="archive")}, "ordered_actions_have_no_Boolean_deontic_formula"),
])
def test_unsupported_supplement_does_not_drop_existing_views_or_weaken_modalities(ast, reason):
    prepared = prepare(ast)
    assert prepared["audit"]["supplemental_DFOL"] == {"requirement_id": "DFOL", "family_id": "deontic",
        "status": "unsupported", "reason": reason, "included_in_family_report": False}
    assert prepared["audit"]["native_formula"] is None
    assert "formula_inputs" not in prepared["source_inputs"]
    base = training.prepare_family_training_targets_v7("intent_ir", **prepared["source_inputs"])
    assert prepared["report"] == base
    result = subject.qualify_source_candidate(rich_grammar.ast_to_text(ast), envelope(ast))
    assert result["status"] == "projected_candidate"
    assert result["report"]["projections"]


@pytest.mark.parametrize("change", [
    lambda d: d["body"].update(actor="reviewer"),
    lambda d: d["body"].update(action="delete"),
    lambda d: d["body"].update(object="Report.py"),
    lambda d: d["body"].update(modality="prohibited"),
    lambda d: d["guard"].update(negated=True),
    lambda d: d["guard"].update(property="pending"),
    lambda d: d["guard"].update(subject="Report.py"),
])
def test_source_disagreement_blocks_before_any_projection(monkeypatch, change):
    ast = conditional()
    source = rich_grammar.ast_to_text(ast)
    candidate = deepcopy(ast)
    change(candidate)
    monkeypatch.setattr(subject.rich_logic, "project_rich_intent_logic", lambda *a, **k: pytest.fail("projection before source agreement"))
    result = subject.qualify_source_candidate(source, envelope(candidate))
    assert result["status"] == "source_disagreement"
    assert result["audit"]["candidate"] == envelope(candidate)
    assert result["report"] is None and not result["projections"]
    assert all(result[key] is False for key in subject.FALSE)


@pytest.mark.parametrize("source", [
    "Every agent must inspect Cache.py.", "agent must inspect Cache.py before noon.",
    "agent must inspect Cache.py until ready.", "agent must inspect Cache.py unless pending.",
    "agent must inspect caf\u00e9.",
])
def test_unsupported_source_scope_never_falls_back_to_flat_formula(monkeypatch, source):
    monkeypatch.setattr(subject.rich_logic, "project_rich_intent_logic", lambda *a, **k: pytest.fail("unsupported source projected"))
    result = subject.qualify_source_candidate(source, envelope(atom()))
    assert result["status"] == "source_unsupported" and result["report"] is None


@pytest.mark.parametrize("candidate", [None, {"kind": "intent_rich_ast", "document": {"kind": "atom"}},
    envelope({**atom(), "extra": "must not be dropped"}), {**envelope(atom()), "qualified": True}])
def test_invalid_closed_candidate_preserved_and_blocked(candidate):
    result = subject.qualify_source_candidate(rich_grammar.ast_to_text(atom()), candidate)
    assert result["status"] == "native_invalid" and result["report"] is None
    assert result["audit"]["candidate"] == candidate


@pytest.mark.parametrize("mutation", ["modal", "guard_negation", "guard_omission", "branch_order", "term_order", "surface", "symbol_omission"])
def test_independent_candidate_structure_check_catches_native_semantic_mutations(mutation):
    prepared = prepare(conditional(True))
    audit = prepared["audit"]
    representation = deepcopy(next(row["representation"] for row in audit["rich_logic_report"]["projections"] if row["family_id"] == "tdfol"))
    payload = deepcopy(audit["native_formula"]["payload"])
    root = payload["native_ast"]
    if mutation == "modal":
        root["right"]["operator"]["value"] = "P"
    elif mutation == "guard_negation":
        root["left"] = root["left"]["formula"]
    elif mutation == "guard_omission":
        payload["native_ast"] = root["right"]
    elif mutation == "branch_order":
        root["left"], root["right"] = root["right"], root["left"]
    elif mutation == "term_order":
        root["right"]["formula"]["arguments"].reverse()
    elif mutation == "surface":
        next(row for row in representation["symbols"] if row["role"] == "slot")["value"]["surface"] = "Other.py"
    else:
        representation["symbols"].pop()
    # Make the two native snapshots agree: direct candidate comparison must
    # still fail, independently of rich/native parser snapshot equality.
    representation["ast"] = deepcopy(payload["native_ast"])
    with pytest.raises(ValueError):
        subject._check_ground_structure(payload, representation, audit["candidate"])


def test_native_owner_ast_mismatch_refuses_even_if_formula_label_is_dfol():
    audit = prepare()["audit"]
    representation = deepcopy(next(row["representation"] for row in audit["rich_logic_report"]["projections"] if row["family_id"] == "tdfol"))
    representation["ast"]["right"]["operator"]["value"] = "P"
    with pytest.raises(ValueError, match="complete rich native AST"):
        subject._check_ground_structure(audit["native_formula"]["payload"], representation, audit["candidate"])


@pytest.mark.parametrize("requested", [["deontic"], ["higher_order"], ["first_order", "deontic"]])
def test_explicit_family_requests_do_not_hide_requested_gaps(requested):
    prepared = prepare(requested_families=requested)
    audit = prepared["audit"]
    assert set(prepared["report"]["requested_families"]) == set(requested)
    assert set(audit["available_families"]) <= set(requested)
    assert audit["missing_requested_families"] == (["first_order"] if "first_order" in requested else [])
    assert audit["supplemental_DFOL"]["included_in_family_report"] == ("deontic" in requested)
    assert len(prepared["report"]["family_inventory"]) == 40


@pytest.mark.parametrize("requested", ["deontic", [1], [], ["DFOL"], ["deontic", "deontic"]])
def test_family_requests_fail_closed_without_filtering_or_aliasing(requested):
    with pytest.raises(ValueError):
        prepare(requested_families=requested)


@pytest.mark.parametrize("part", ["source", "candidate", "audit", "report", "formula"])
def test_exact_replay_rejects_mutation(part):
    ast = conditional()
    source, target = rich_grammar.ast_to_text(ast), envelope(ast)
    prepared = prepare(ast)
    if part == "source":
        source += " "
    elif part == "candidate":
        target["document"]["guard"]["negated"] = True
    elif part == "audit":
        prepared["audit"]["qualified"] = True
    elif part == "report":
        prepared["report"]["projections"].pop()
    else:
        prepared["audit"]["native_formula"]["payload"]["formula"] = "O(Changed(entity:X))"
    with pytest.raises(ValueError):
        subject.validate_prepared(prepared, source, target)


@pytest.mark.parametrize("ast", [conditional(True),
    {"kind": "and", "left": atom(), "right": atom(action="archive", modality="permitted")},
    {"kind": "or", "left": atom(), "right": atom(action="delete", modality="prohibited")}])
def test_existing_native_lean_preparation_accepts_complete_dfol_without_claiming_build(ast):
    prepared = prepare(ast)
    native = lake.prepare_native_family_lean(prepared["report"], source_inputs=prepared["source_inputs"])
    dfol = next(row for row in native["per_projection"] if row["projection_id"] == "intent_ir/native_formula/DFOL/v3")
    assert dfol["parser_status"] == "passed"
    assert native["backend_executed"] is False
    assert "axiom" not in native["lean_source"]
