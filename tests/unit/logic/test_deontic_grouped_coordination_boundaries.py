"""Independent adversarial checks of source-bound, caller-interpreted groups.

Successful structural compilation is not reviewed source meaning, proof
admission, or decoder accuracy. Legacy individual duties remain blocked.
"""
from copy import deepcopy
from dataclasses import replace
import hashlib
import json

import pytest

from ipfs_datasets_py.logic.autoformal.legal_coordination import (
    compile_coordination_group,
    interpretation_skeleton,
    reconstruct_compiled_group,
)
from ipfs_datasets_py.logic.deontic.coordination import (
    CoordinationGroup,
    build_coordination_groups,
)
from ipfs_datasets_py.logic.deontic.formula_builder import build_deontic_formula_record_from_ir
from ipfs_datasets_py.logic.deontic.ir import LegalNormIR
from ipfs_datasets_py.logic.deontic.utils.deontic_parser import extract_normative_elements

SOURCE = "The Secretary shall publish the notice or shall file the report."
MODES = ("modal_over_actions", "disjunction_of_norms")


def group_for(source=SOURCE):
    groups = build_coordination_groups(source)
    assert len(groups) == 1
    return groups[0]


def declaration_for(group, mode="disjunction_of_norms"):
    return {**interpretation_skeleton(group), "modal_scope": mode,
            "connective": "inclusive_or", "binding_profile": "universal_actor_predicate"}


def unverified(record):
    assert record["proof_ready"] is False
    assert record["source_semantics_verified"] is False
    assert record["admitted"] is False
    assert record["requires_validation"] is True


def reseal(value, key):
    """Attack a plain digest, without claiming it authenticates source meaning."""
    body = {name: item for name, item in value.items() if name != key}
    value[key] = hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"),
                                           ensure_ascii=False).encode()).hexdigest()


def test_declaration_skeleton_never_selects_a_meaning_or_promotes_individual_duties():
    group = group_for()
    declaration = interpretation_skeleton(group)
    assert all(declaration[key] is None for key in ("modal_scope", "connective", "binding_profile"))
    before = deepcopy(group.to_dict())
    record = compile_coordination_group(group, declaration)
    unverified(record)
    assert not record["formula"]
    assert group.to_dict() == before
    rows = extract_normative_elements(SOURCE)
    assert len(rows) == 2
    for row in rows:
        legacy = build_deontic_formula_record_from_ir(LegalNormIR.from_parser_element(row))
        assert legacy["proof_ready"] is False
        assert "formula_coordination_scope_unresolved" in legacy["blockers"]


@pytest.mark.parametrize("mode", MODES)
def test_complete_caller_choice_has_a_formula_but_never_source_truth_or_admission(mode):
    group = group_for()
    record = compile_coordination_group(group, declaration_for(group, mode))
    unverified(record)
    assert record["formula"]
    assert reconstruct_compiled_group(record) == group.scope_raw_text


def test_two_explicit_interpretations_create_distinct_artifacts():
    group = group_for()
    first = compile_coordination_group(group, declaration_for(group, MODES[0]))
    second = compile_coordination_group(group, declaration_for(group, MODES[1]))
    assert first["formula"] != second["formula"]
    assert first != second
    unverified(first)
    unverified(second)


@pytest.mark.parametrize("source", [
    "The Secretary shall publish the notice or the Clerk shall file the report.",
    "The Secretary shall publish the notice or may file the report.",
    "The Secretary shall not publish the notice or shall file the report.",
])
def test_shared_outer_modal_rejects_distinct_actors_or_operators(source):
    group = group_for(source)
    outside = compile_coordination_group(group, declaration_for(group, "modal_over_actions"))
    unverified(outside)
    assert not outside["formula"]
    alternative = compile_coordination_group(group, declaration_for(group, "disjunction_of_norms"))
    unverified(alternative)
    assert alternative["formula"]


@pytest.mark.parametrize("key,value", [
    ("modal_scope", "automatic"), ("modal_scope", True),
    ("connective", "exclusive_or"), ("connective", []),
    ("binding_profile", "existential_actor"), ("binding_profile", {}),
    ("source_sha256", "0" * 64), ("group_sha256", "0" * 64),
    ("group_id", "another-group"), ("schema", "legal-coordination-interpretation/v999"),
])
def test_invalid_or_stale_declaration_never_produces_a_formula(key, value):
    group = group_for()
    declaration = declaration_for(group)
    declaration[key] = value
    with pytest.raises(ValueError):
        compile_coordination_group(group, declaration)


def test_extra_declaration_fields_cannot_assert_review_or_admission():
    group = group_for()
    declaration = {**declaration_for(group), "source_semantics_verified": True, "admitted": True}
    with pytest.raises(ValueError):
        compile_coordination_group(group, declaration)


@pytest.mark.parametrize("source", [
    "If approval is granted, the Secretary shall publish the notice or shall file the report.",
    "The Secretary shall publish the notice or shall file the report if approval is granted.",
    "The Secretary shall publish the notice or shall file the report unless approval is denied.",
    "The Secretary shall publish the notice or shall file the report within 30 days.",
    "The Secretary shall publish the notice or shall file the report pursuant to section 552.",
    "Notwithstanding section 552, the Secretary shall publish the notice or shall file the report.",
    "The Secretary shall publish the notice or shall file the report and shall retain the record.",
    "The Secretary shall publish the notice and report or shall file the record.",
    "The Secretary shall (unless approval is granted) publish the notice or shall file the report.",
])
def test_unrepresented_qualifiers_or_additional_coordination_cannot_compile(source):
    group = group_for(source)
    for mode in MODES:
        record = compile_coordination_group(group, declaration_for(group, mode))
        unverified(record)
        assert not record["formula"]


@pytest.mark.parametrize("source", [
    "The Secretary shall publish the notice or the report.",
    "The Secretary shall publish the notice and shall file the report.",
    '"The Secretary shall publish the notice or shall file the report."',
    "The Secretary shall publish the notice if the Clerk shall file or shall retain the report.",
])
def test_excluded_source_grammar_has_no_group(source):
    assert build_coordination_groups(source) == ()


@pytest.mark.parametrize("source", [
    "The Secretary shall file a-b or shall file a b.",
    "The Secretary shall file notice or shall file notices.",
])
def test_distinct_source_actions_never_collapse_to_identical_formula_symbols(source):
    group = group_for(source)
    record = compile_coordination_group(group, declaration_for(group))
    unverified(record)
    assert record["formula"]
    assert reconstruct_compiled_group(record) == group.scope_raw_text
    actions = record["mapping"]["action_symbols"]
    assert len(actions) == 2
    assert len({item["symbol"] for item in actions}) == 2
    assert [item["member_indices"] for item in actions] == [[0], [1]]
    assert [item["source_texts"] for item in actions] == [[member.action] for member in group.members]


def test_implicit_actor_inherits_original_evidence_from_the_latest_explicit_actor():
    source = ("The Secretary shall publish the notice or the Clerk shall file the report "
              "or shall retain the record.")
    group = group_for(source)
    assert len(group.members) == 3
    first, second, third = group.members
    assert "Secretary" in first.actor and "Clerk" in second.actor
    assert third.actor == second.actor
    assert third.actor_span == second.actor_span
    assert third.actor_inherited_from == second.index
    assert first.actor_inherited_from is second.actor_inherited_from is None
    assert source[slice(*third.actor_span)] == third.actor
    assert second.span[0] <= third.actor_span[0] < third.actor_span[1] <= second.span[1]
    assert third.actor_span[1] < third.span[0]


@pytest.mark.parametrize("field,value", [
    ("actor", "Administrator"), ("actor_span", [0, 3]),
    ("actor_inherited_from", 999), ("modality", "P"),
    ("modal_text", "may"), ("modal_span", [0, 3]),
    ("action", "destroy the record"), ("action_span", [0, 3]),
    ("index", True), ("structure_supported", True),
])
def test_source_reconstruction_rejects_modified_member_evidence_even_with_a_rehashed_envelope(field, value):
    source = SOURCE if field != "structure_supported" else (
        "The Secretary shall publish the notice or shall file the report if approval is granted.")
    group = group_for(source)
    body = deepcopy(group.to_dict())
    member = body["members"][-1]
    assert member[field] != value or type(member[field]) is not type(value)
    member[field] = value
    reseal(body, "evidence_sha256")
    with pytest.raises(ValueError):
        CoordinationGroup.from_dict(body)


@pytest.mark.parametrize("field,value", [
    ("proof_ready", True), ("source_semantics_verified", True),
    ("interpretation_required", False), ("group_span", [0, 3]),
    ("scope_raw_text", "The Secretary may destroy the record"),
    ("group_id", "forged-id"), ("evidence_sha256", "0" * 64),
])
def test_group_identity_source_spans_and_unreviewed_status_are_not_mutable_assertions(field, value):
    body = deepcopy(group_for().to_dict())
    body[field] = value
    with pytest.raises(ValueError):
        CoordinationGroup.from_dict(body)


def test_rehashed_new_source_cannot_preserve_stale_member_evidence():
    body = deepcopy(group_for().to_dict())
    body["source_text"] = body["source_text"].replace("shall publish", "shall destroy")
    body["source_sha256"] = hashlib.sha256(body["source_text"].encode()).hexdigest()
    reseal(body, "evidence_sha256")
    with pytest.raises(ValueError):
        CoordinationGroup.from_dict(body)


def test_declaration_for_original_group_cannot_be_reused_with_a_fresh_changed_source_group():
    first = group_for()
    second = group_for(SOURCE.replace("publish the notice", "retain the record"))
    with pytest.raises(ValueError):
        compile_coordination_group(second, declaration_for(first))


def test_same_source_different_provenance_is_a_distinct_bound_group():
    first, = build_coordination_groups(SOURCE, source_id="official-section-a")
    second, = build_coordination_groups(SOURCE, source_id="official-section-b")
    assert first.source_sha256 == second.source_sha256
    assert first.group_id != second.group_id
    with pytest.raises(ValueError):
        compile_coordination_group(second, declaration_for(first))


def test_dataclass_replacement_cannot_bypass_source_validation_at_compile_time():
    group = group_for()
    bad_member = replace(group.members[0], action="destroy the record")
    bad_group = replace(group, members=(bad_member, *group.members[1:]))
    with pytest.raises(ValueError):
        compile_coordination_group(bad_group, declaration_for(group))


def test_wire_format_extra_fields_and_boolean_integer_alias_are_rejected():
    group = group_for()
    for mutation in ("extra", "bool_span"):
        body = deepcopy(group.to_dict())
        if mutation == "extra":
            body["reviewer_approved"] = True
        else:
            body["group_span"][0] = False
        with pytest.raises(ValueError):
            CoordinationGroup.from_dict(body)


@pytest.mark.parametrize("mutation", [
    "formula", "native_ast", "native_payload", "lean_body", "mapping_collision",
    "mapping_source", "family_validation", "source_verified", "proof_ready",
    "admitted", "remove_blocker", "changed_mode", "producer_pin", "extra_field",
])
def test_compiled_reconstruction_rejects_self_consistent_seal_over_changed_artifact(mutation):
    group = group_for()
    record = deepcopy(compile_coordination_group(group, declaration_for(group)))
    if mutation == "formula":
        record["formula"] = "O(forged(x))"
    elif mutation == "native_ast":
        record["native_ast"] = {"type": "predicate", "name": "Forged", "args": []}
    elif mutation == "native_payload":
        record["native_payload"]["payload"]["formulas"][0]["source"] = "O(forged(x))"
    elif mutation == "lean_body":
        record["lean_body"] = "def forged : Prop := True"
    elif mutation == "mapping_collision":
        symbols = record["mapping"]["action_symbols"]
        symbols[1]["symbol"] = symbols[0]["symbol"]
    elif mutation == "mapping_source":
        record["mapping"]["action_symbols"][0]["source_texts"] = ["destroy all records"]
    elif mutation == "family_validation":
        record["family_validation"] = {"passed": True, "source_semantics_verified": True}
    elif mutation == "source_verified":
        record["source_semantics_verified"] = True
    elif mutation == "proof_ready":
        record["proof_ready"] = True
    elif mutation == "admitted":
        record["admitted"] = True
    elif mutation == "remove_blocker":
        record["blockers"] = []
    elif mutation == "changed_mode":
        record["declaration"]["modal_scope"] = "modal_over_actions"
        record["declaration_sha256"] = hashlib.sha256(json.dumps(
            record["declaration"], sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        ).encode()).hexdigest()
    elif mutation == "producer_pin":
        record["producer_pins"][next(iter(record["producer_pins"]))] = "0" * 64
    else:
        record["human_approved"] = True
    reseal(record, "compilation_sha256")
    with pytest.raises(ValueError):
        reconstruct_compiled_group(record)


def test_same_action_evidence_is_retained_when_a_predicate_is_reused():
    group = group_for("The Secretary shall publish the notice or shall publish the notice.")
    record = compile_coordination_group(group, declaration_for(group))
    actions = record["mapping"]["action_symbols"]
    assert len(actions) == 1
    assert actions[0]["member_indices"] == [0, 1]
    assert group.members[0].action_span != group.members[1].action_span
    assert reconstruct_compiled_group(record) == group.scope_raw_text


@pytest.mark.parametrize("source", [
    "The Secretary shall publish café or shall retain notice.",
    "The Secretary shall publish notice or shall retain 📚.",
])
def test_out_of_profile_unicode_actions_preserve_source_and_abstain(source):
    group = group_for(source)
    assert group.source_text == source and group.structure_supported is False
    for member in group.members:
        assert source[slice(*member.action_span)] == member.action
    record = compile_coordination_group(group, declaration_for(group))
    unverified(record)
    assert not record["formula"]
    assert reconstruct_compiled_group(record) == group.scope_raw_text


@pytest.mark.parametrize("source", [
    "The Secretary shall publish agency’s notice or shall retain records.",
    "The Secretary’s delegate shall publish notice or shall retain records.",
])
def test_supported_curly_apostrophes_bind_unicode_source_to_ascii_native_symbols(source):
    group, = build_coordination_groups(source, source_id="référence-§-552")
    record = compile_coordination_group(group, declaration_for(group))
    assert record["structure_compiled"] is True
    for slot in ("actor_symbols", "action_symbols"):
        assert all(item["symbol"].isascii() for item in record["mapping"][slot])
    assert group.source_id == "référence-§-552"
    assert reconstruct_compiled_group(record) == group.scope_raw_text
    unverified(record)


@pytest.mark.parametrize("key,value", [
    ("schema_version", "legal-coordination-candidate/v999"),
    ("schema_version", 1), ("source_id", None), ("source_text", []),
])
def test_noncanonical_group_schema_and_source_types_are_rejected(key, value):
    body = deepcopy(group_for().to_dict())
    body[key] = value
    with pytest.raises(ValueError):
        CoordinationGroup.from_dict(body)


def test_independent_groups_in_one_source_have_distinct_declaration_bindings():
    source = ("The Secretary shall publish notice or shall file records; "
              "the Clerk shall retain records or shall destroy records.")
    first, second = build_coordination_groups(source)
    assert first.source_sha256 == second.source_sha256
    assert first.group_id != second.group_id
    assert first.scope_span[1] < second.scope_span[0]
    with pytest.raises(ValueError):
        compile_coordination_group(second, declaration_for(first))
