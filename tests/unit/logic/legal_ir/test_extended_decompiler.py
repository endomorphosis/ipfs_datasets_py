"""Source-withheld realization of the existing opt-in typed surface IR.

Authored fixtures test literal facet preservation, not reviewed legal meaning.
"""
import pytest
from ipfs_datasets_py.logic.legal_ir.extended_contracts import (
    DefinitionV2, PolicyV2, NormV2, ExtendedLegalIR)
from ipfs_datasets_py.logic.legal_ir.extended_decompiler import decompile_extended


@pytest.mark.parametrize(("statement", "expected"), [
    (NormV2("O", "the clerk", "file", "the notice"),
     'Norm: "the clerk" must "file" "the notice".'),
    (DefinitionV2("eligible person", "means", "a registered applicant"),
     'Definition: "eligible person" means "a registered applicant".'),
    (PolicyV2("the agency", "supports", ("public access",)),
     'Policy: "the agency" supports "public access".'),
])
def test_extended_statement_kinds_have_source_withheld_realizations(statement, expected):
    assert decompile_extended(ExtendedLegalIR((statement,))) == expected

from copy import deepcopy
from ipfs_datasets_py.logic.legal_ir.extended_compiler import compile_extended
from ipfs_datasets_py.logic.legal_ir.extended_decompiler import MAX_RENDERED_UTF8_BYTES


@pytest.mark.parametrize("modality,word", [("O", "must"), ("P", "may"), ("F", "must not")])
def test_modalities_remain_distinct_without_claiming_observed_compliance(modality, word):
    value = ExtendedLegalIR((NormV2(modality, "agency", "publish", "notice"),))
    text = f'Norm: "agency" {word} "publish" "notice".'
    assert decompile_extended(value) == text
    assert compile_extended(text).to_dict() == value.to_dict()
    assert compile_extended('Observed: "agency" published "notice".') is None


@pytest.mark.parametrize("relation", ["means", "includes", "excludes"])
def test_definition_relations_do_not_become_norms(relation):
    value = ExtendedLegalIR((DefinitionV2("member", relation, "registered applicant"),))
    text = f'Definition: "member" {relation} "registered applicant".'
    assert decompile_extended(value) == text
    assert compile_extended(text).to_dict() == value.to_dict()


@pytest.mark.parametrize("stance,word", [("supports", "supports"), ("declares_policy", "declares as policy")])
def test_policy_objectives_and_stance_remain_policy(stance, word):
    value = ExtendedLegalIR((PolicyV2("agency", stance, ("public access", "safe retention")),))
    text = f'Policy: "agency" {word} "public access"; "safe retention".'
    assert decompile_extended(value) == text
    assert compile_extended(text).to_dict() == value.to_dict()
    assert compile_extended(text).statements[0].kind == "policy"


def test_complete_mixed_value_roundtrip_retains_all_ordered_literal_facets():
    facets = dict(scope=("within State A", "for edition 2024"),
        conditions=("after written notice", "upon registration"),
        exceptions=("unless exempt", "unless a court orders otherwise"),
        temporal=("within 3 business days", "effective 2024-07-01"))
    value = ExtendedLegalIR((DefinitionV2("member", "means", "registered applicant", **facets),
        PolicyV2("agency", "declares_policy", ("access", "retention"), **facets),
        NormV2("F", "member", "disclose", "private record", **facets)))
    before = deepcopy(value.to_dict())
    text = decompile_extended(value)
    suffix = (' Scope: "within State A"; "for edition 2024".'
        ' Conditions: "after written notice"; "upon registration".'
        ' Exceptions: "unless exempt"; "unless a court orders otherwise".'
        ' Temporal: "within 3 business days"; "effective 2024-07-01".')
    assert len(text.splitlines()) == 3 and all(line.endswith(suffix) for line in text.splitlines())
    assert compile_extended(text).to_dict() == before == value.to_dict()


@pytest.mark.parametrize("literal", ['clerk; " Scope: fake"', 'a\\b. Conditions: "fake"',
    'Greek α and emoji 🚢', 'KEEP_underscores', 'a.b; c: (d)', 'backslash \\u0061'])
def test_quoted_literals_cannot_escape_their_slots(literal):
    value = ExtendedLegalIR((NormV2("O", literal, "send", literal,
        conditions=(literal,), exceptions=(literal,), temporal=(literal,), scope=(literal,)),))
    assert compile_extended(decompile_extended(value)).to_dict() == value.to_dict()


@pytest.mark.parametrize("field,before,after", [
    ("modality", "O", "P"), ("modality", "O", "F"),
    ("actor", "clerk", "director"), ("action", "file", "withhold"),
    ("object", "notice", "sealed record"),
    ("conditions", ("upon application",), ("upon approval",)),
    ("exceptions", ("unless exempt",), ()),
    ("scope", ("State A",), ("State B",)),
    ("temporal", ("within 3 calendar days",), ("within 3 business days",)),
    ("temporal", ("effective 2024-01-01",), ("effective 2025-01-01",)),
    ("conditions", ("at most 3 members",), ("at most 4 members",)),
])
def test_authored_literal_facet_mutations_cannot_roundtrip_as_original(field, before, after):
    # These are literal-slot distinctions, not a logical interpretation of the
    # calendar, count, exception or applicability phrases.
    args = dict(modality="O", actor="clerk", action="file", object="notice")
    args[field] = before
    original = ExtendedLegalIR((NormV2(**args),))
    args[field] = after
    changed = ExtendedLegalIR((NormV2(**args),))
    assert decompile_extended(original) != decompile_extended(changed)
    assert compile_extended(decompile_extended(changed)).to_dict() == changed.to_dict()
    assert compile_extended(decompile_extended(changed)).to_dict() != original.to_dict()


def test_condition_and_exception_placement_is_preserved_without_interpreting_atom():
    a = ExtendedLegalIR((NormV2("O", "clerk", "file", "notice", conditions=("exempt",)),))
    b = ExtendedLegalIR((NormV2("O", "clerk", "file", "notice", exceptions=("exempt",)),))
    assert decompile_extended(a) != decompile_extended(b)
    assert compile_extended(decompile_extended(a)).to_dict() == a.to_dict()
    assert compile_extended(decompile_extended(b)).to_dict() == b.to_dict()


def test_conflicting_definitions_are_retained_without_selecting_governing_meaning():
    value = ExtendedLegalIR((DefinitionV2("member", "means", "applicant"),
        DefinitionV2("member", "means", "registered officer"), NormV2("P", "member", "read", "record")))
    result = compile_extended(decompile_extended(value))
    assert result.to_dict() == value.to_dict()
    assert len(result.statements) == 3


def test_collection_order_and_duplicate_atoms_are_not_repaired_or_deduplicated():
    value = ExtendedLegalIR((NormV2("P", "a", "b", "c", conditions=("two", "one", "two")),))
    assert decompile_extended(value).endswith(' Conditions: "two"; "one"; "two".')
    assert compile_extended(decompile_extended(value)).to_dict() == value.to_dict()


@pytest.mark.parametrize("text", [
    'The clerk must file a notice.',
    'Norm: "clerk" must "file" "notice". Unparsed residue.',
    'Norm: "clerk" must "file" "notice".\nUnsupported paragraph.',
    'Norm: "clerk" must "file" "notice". Conditions: "x". Conditions: "y".',
    'Norm: "clerk" must "file" "notice". Temporal: "x". Scope: "y".',
    'Norm: "clerk" must "file" "notice". Source: "hidden source".',
    'Norm: "clerk" must "file" "notice".\n',
    ' Norm: "clerk" must "file" "notice".',
    'Definition: "member" must "applicant".',
    'Policy: "agency" may "access".',
    'Norm: "clerk" MAY "file" "notice".',
    'Norm: "clerk" must "file" "notice". Exceptions: .',
    'Norm: "clerk" must "file" "notice". Conditions: "".',
    'Norm: "clerk" must "file" "notice". Conditions: "two  spaces".',
])
def test_unsupported_or_partially_parsed_span_abstains_as_a_whole(text):
    assert compile_extended(text) is None


@pytest.mark.parametrize("text", [None, 1, True, "", "  "])
def test_original_empty_and_non_text_request_refusals_remain_explicit(text):
    with pytest.raises(ValueError):
        compile_extended(text)


@pytest.mark.parametrize("value", [{"source_text": "hidden"}, {"rules": []}, None, 1])
def test_renderer_rejects_source_bearing_or_other_untyped_inputs(value):
    with pytest.raises(ValueError):
        decompile_extended(value)


def test_source_bearing_extra_fields_cannot_become_renderer_input():
    wire = ExtendedLegalIR((NormV2("P", "a", "b", "c"),)).to_dict()
    wire["source_text"] = "Hidden original wording."
    with pytest.raises(ValueError):
        ExtendedLegalIR.from_dict(wire)


def test_forged_frozen_discriminator_is_revalidated_before_rendering():
    value = ExtendedLegalIR((NormV2("P", "a", "b", "c"),))
    object.__setattr__(value.statements[0], "kind", "definition")
    with pytest.raises(ValueError):
        decompile_extended(value)


def test_output_budget_refuses_complete_value_without_emitting_truncated_prose():
    atom = "x" * 16384
    value = ExtendedLegalIR((PolicyV2("agency", "supports", (atom,) * 128),))
    with pytest.raises(ValueError, match="truncation refused"):
        decompile_extended(value)


def test_utf8_byte_budget_and_invalid_unicode_are_explicit_not_character_counts():
    assert compile_extended("x" * (MAX_RENDERED_UTF8_BYTES + 1)) is None
    assert compile_extended("é" * (MAX_RENDERED_UTF8_BYTES // 2 + 1)) is None
    assert compile_extended('Norm: "\ud800" must "file" "notice".') is None
    value = ExtendedLegalIR((NormV2("P", "\ud800", "file", "notice"),))
    with pytest.raises(ValueError, match="UTF-8"):
        decompile_extended(value)


def test_collection_and_statement_bounds_refuse_without_dropping_extra_material():
    line = 'Norm: "a" may "b" "c".'
    expected = ExtendedLegalIR((NormV2("P", "a", "b", "c"),)).to_dict()["statements"][0]
    assert compile_extended("\n".join([line] * 128)).to_dict()["statements"] == [expected] * 128
    assert compile_extended("\n".join([line] * 129)) is None
    assert compile_extended(line + ' Scope: ' + '; '.join(['"x"'] * 129) + '.') is None
