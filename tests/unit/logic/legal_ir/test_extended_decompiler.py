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


# Independently authored semantic trees and expected controlled legal prose.
# These are fictional syntax fixtures; no statutory meaning review is implied.
from ipfs_datasets_py.logic.syntax_core import ast as prose_ast, signatures as prose_signatures
from ipfs_datasets_py.logic.legal_ir.extended_decompiler import (
    COUNTED_PROSE_PROFILE, RELATIONAL_PROSE_PROFILE, decompile_relational,
)
from ipfs_datasets_py.logic.legal_ir.extended_compiler import compile_relational


class _ProseTree:
    def __init__(self, family="tdfol", profile="tdfol_default", mixed=False):
        self.serial = 0
        self.family, self.profile = family, profile
        self.sorts = {name: prose_signatures.LogicSort(name) for name in
                      (("Object", "EventFrame", "TimeFrame") if mixed else ("Object",))}

    def nid(self):
        self.serial += 1
        return "independent:prose:node:" + str(self.serial)

    def variable(self, name, sort="Object"):
        return prose_ast.mk_variable(self.nid(), name, self.sorts[sort])

    def atom(self, name, *arguments):
        return prose_ast.mk_predicate(self.nid(), name,
            tuple(self.variable(*item) if type(item) is tuple else self.variable(item)
                  for item in arguments))

    def modal(self, letter, body):
        kind = {"O": "obligation", "P": "permission", "F": "forbidden"}[letter]
        return prose_ast.mk_extension(self.nid(), family="tdfol", profile="tdfol_default",
            features=("legacy.classic_letter", "legacy." + kind),
            payload_schema="legacy.deontic/v1",
            payload={"kind": kind, "letter": letter, "resolution": "deontic",
                     "schema_version": "legacy.deontic/v1"}, children=(body,))

    def quantify(self, body, binders):
        for name, kind, sort in reversed(binders):
            constructor = prose_ast.mk_forall if kind == "forall" else prose_ast.mk_exists
            body = constructor(self.nid(), (prose_ast.Binder(name, self.sorts[sort]),), body)
        return body

    def expression(self, body, declarations):
        signature = prose_signatures.LogicSignature("independent:prose:signature",
            family=self.family, profile=self.profile, sorts=tuple(self.sorts.values()),
            symbols=tuple(prose_signatures.declare_predicate(name,
                tuple(self.sorts[sort] for _, sort in fields)) for name, fields in declarations))
        return prose_ast.TypedExpression("independent:prose:expression", body, signature), [
            {"symbol": name, "roles": [role for role, _ in fields]}
            for name, fields in declarations]


def _prose_fixture(letter="O", *, swapped=False, reverse_scope=False, roles=("actor", "recipient")):
    tree = _ProseTree()
    arguments = ("recipient", "actor") if swapped else ("actor", "recipient")
    body = tree.modal(letter, tree.atom("Relates", *arguments))
    binders = [("actor", "forall", "Object"), ("recipient", "exists", "Object")]
    if reverse_scope:
        binders.reverse()
    body = tree.quantify(body, binders)
    return tree.expression(body, [("Relates", [(role, "Object") for role in roles])])


def _prose_transport_free(value):
    """Independent expected typed content, excluding declared transport IDs."""
    if type(value) is dict:
        return {key: _prose_transport_free(child) for key, child in value.items()
                if key not in {"node_id", "expression_id", "signature_id", "content_digest"}}
    if type(value) is list:
        return [_prose_transport_free(child) for child in value]
    return value


_PROSE_HEADER = (
    "Typed legal rule: tdfol/tdfol_default.\n"
    "Types: Object.\n"
    "Predicate Relates: actor of type Object; recipient of type Object.\nRule: "
)
_PROSE_OBLIGATION = _PROSE_HEADER + (
    "(for every actor of type Object, (there exists recipient of type Object such that "
    "(it is obligatory that (Relates holds for actor: actor of type Object; "
    "recipient: recipient of type Object))))."
)


@pytest.mark.parametrize("letter,word", [("O", "obligatory"), ("P", "permitted"), ("F", "forbidden")])
def test_relational_prose_has_independent_exact_expected_grammar_and_modalities(letter, word):
    expression, roles = _prose_fixture(letter)
    expected = _PROSE_OBLIGATION.replace("obligatory", word)
    assert decompile_relational(expression, argument_roles=roles, profile=RELATIONAL_PROSE_PROFILE) == expected
    parsed = compile_relational(expected, profile=RELATIONAL_PROSE_PROFILE)
    assert parsed is not None
    reconstructed, reconstructed_roles = parsed
    assert _prose_transport_free(reconstructed.to_dict()) == _prose_transport_free(expression.to_dict())
    assert reconstructed_roles == roles
    assert decompile_relational(reconstructed, argument_roles=reconstructed_roles,
                                profile=RELATIONAL_PROSE_PROFILE) == expected


@pytest.mark.parametrize("change", ["argument_order", "role_labels", "quantifier_scope"])
def test_relational_prose_visible_ordered_roles_and_scope_mutations_remain_distinct(change):
    reference, roles = _prose_fixture()
    candidate, candidate_roles = _prose_fixture(
        swapped=change == "argument_order", reverse_scope=change == "quantifier_scope",
        roles=("recipient", "actor") if change == "role_labels" else ("actor", "recipient"))
    baseline = decompile_relational(reference, argument_roles=roles, profile=RELATIONAL_PROSE_PROFILE)
    changed = decompile_relational(candidate, argument_roles=candidate_roles, profile=RELATIONAL_PROSE_PROFILE)
    assert baseline != changed
    recovered, recovered_roles = compile_relational(changed, profile=RELATIONAL_PROSE_PROFILE)
    assert _prose_transport_free(recovered.to_dict()) == _prose_transport_free(candidate.to_dict())
    assert recovered_roles == candidate_roles


def _condition_exception_fixture(*, exception_inside_modal=False):
    tree = _ProseTree()
    approved = tree.atom("Approved", "actor")
    exempt = prose_ast.mk_not(tree.nid(), tree.atom("Exempt", "actor"))
    action = tree.atom("Relates", "actor", "recipient")
    if exception_inside_modal:
        condition = approved
        consequence = tree.modal("O", prose_ast.mk_implies(tree.nid(), exempt, action))
    else:
        condition = prose_ast.mk_and(tree.nid(), approved, exempt)
        consequence = tree.modal("O", action)
    root = tree.quantify(prose_ast.mk_implies(tree.nid(), condition, consequence),
        [("actor", "forall", "Object"), ("recipient", "forall", "Object")])
    return tree.expression(root, [("Approved", [("actor", "Object")]),
        ("Exempt", [("actor", "Object")]),
        ("Relates", [("actor", "Object"), ("recipient", "Object")])])


def test_relational_prose_preserves_boolean_conditions_and_exception_placement():
    expression, roles = _condition_exception_fixture()
    expected = (
        "Typed legal rule: tdfol/tdfol_default.\nTypes: Object.\n"
        "Predicate Approved: actor of type Object.\nPredicate Exempt: actor of type Object.\n"
        "Predicate Relates: actor of type Object; recipient of type Object.\nRule: "
        "(for every actor of type Object, (for every recipient of type Object, "
        "(if (both (Approved holds for actor: actor of type Object) and "
        "(it is not the case that (Exempt holds for actor: actor of type Object))) then "
        "(it is obligatory that (Relates holds for actor: actor of type Object; "
        "recipient: recipient of type Object)))))."
    )
    assert decompile_relational(expression, argument_roles=roles, profile=RELATIONAL_PROSE_PROFILE) == expected
    reconstructed, reconstructed_roles = compile_relational(expected, profile=RELATIONAL_PROSE_PROFILE)
    assert _prose_transport_free(reconstructed.to_dict()) == _prose_transport_free(expression.to_dict())
    assert reconstructed_roles == roles
    changed, changed_roles = _condition_exception_fixture(exception_inside_modal=True)
    assert decompile_relational(changed, argument_roles=changed_roles, profile=RELATIONAL_PROSE_PROFILE) != expected


def test_relational_prose_generic_mixed_equality_disjunction_and_iff_keep_complete_tree():
    tree = _ProseTree(mixed=True)
    equality = prose_ast.mk_equality(tree.nid(), tree.variable("actor"), tree.variable("recipient"))
    disjunction = prose_ast.mk_or(tree.nid(), tree.atom("Member", "actor", ("event", "EventFrame"),
        ("time", "TimeFrame")), tree.atom("Member", "recipient", ("event", "EventFrame"),
        ("time", "TimeFrame")))
    root = tree.quantify(prose_ast.mk_iff(tree.nid(), equality, disjunction),
        [("actor", "forall", "Object"), ("recipient", "exists", "Object"),
         ("event", "forall", "EventFrame"), ("time", "forall", "TimeFrame")])
    expression, roles = tree.expression(root, [("Member", [("object", "Object"),
        ("event", "EventFrame"), ("time", "TimeFrame")])])
    prose = decompile_relational(expression, argument_roles=roles, profile=RELATIONAL_PROSE_PROFILE)
    assert "actor of type Object is identical to recipient of type Object" in prose
    assert "if and only if" in prose and "(either " in prose
    assert "event: event of type EventFrame; time: time of type TimeFrame" in prose
    reconstructed, reconstructed_roles = compile_relational(prose, profile=RELATIONAL_PROSE_PROFILE)
    # Canonical declaration ordering is independent of their original order.
    left, right = _prose_transport_free(expression.to_dict()), _prose_transport_free(reconstructed.to_dict())
    left["signature"]["sorts"].sort(key=lambda item: item["name"])
    right["signature"]["sorts"].sort(key=lambda item: item["name"])
    assert left == right and reconstructed_roles == roles


@pytest.mark.parametrize("suffix", ["\n", " Further duty applies.", " Source: hidden original.",
    "\nRule: (it is not the case that (Relates holds for actor: actor of type Object))."])
def test_relational_prose_trailing_or_additional_clause_refuses_entire_input(suffix):
    assert compile_relational(_PROSE_OBLIGATION + suffix, profile=RELATIONAL_PROSE_PROFILE) is None


@pytest.mark.parametrize("replacement", [
    ("obligatory", "observed"), ("Object", "CalendarDay"),
    ("recipient: recipient", "actor: recipient"),
    ("for every actor", "for most actor"),
    ("Types: Object.", "Types: Object.\nSource: hidden wording."),
    ("Rule: ", "Original: "),
])
def test_relational_prose_unsupported_or_inconsistent_declaration_refuses_whole_input(replacement):
    assert compile_relational(_PROSE_OBLIGATION.replace(*replacement), profile=RELATIONAL_PROSE_PROFILE) is None


@pytest.mark.parametrize("value", [None, True, 7, "", "  "])
def test_relational_prose_empty_or_nontyped_source_is_explicitly_invalid(value):
    with pytest.raises(ValueError):
        compile_relational(value, profile=RELATIONAL_PROSE_PROFILE)


def test_relational_prose_profiles_require_explicit_opt_in_and_leave_surface_default_exact():
    with pytest.raises(TypeError):
        compile_relational(_PROSE_OBLIGATION)
    with pytest.raises(TypeError):
        decompile_relational(_prose_fixture()[0], argument_roles=_prose_fixture()[1])
    with pytest.raises(ValueError):
        compile_relational(_PROSE_OBLIGATION, profile="unknown/v1")
    assert compile_extended(_PROSE_OBLIGATION) is None
    legacy = ExtendedLegalIR((NormV2("O", "clerk", "file", "notice"),))
    assert decompile_extended(legacy) == 'Norm: "clerk" must "file" "notice".'
    assert compile_extended(decompile_extended(legacy)).to_dict() == legacy.to_dict()


def test_relational_prose_rejects_source_metadata_and_does_not_accept_original_wording_channel():
    expression, roles = _prose_fixture()
    source_bearing = prose_ast.TypedExpression("independent:source-bearing", expression.root,
        expression.signature, metadata={"source_text": "Hidden original bytes."})
    with pytest.raises(ValueError):
        decompile_relational(source_bearing, argument_roles=roles, profile=RELATIONAL_PROSE_PROFILE)
    with pytest.raises(ValueError):
        decompile_relational({"expression": expression.to_dict(), "source_text": "hidden"},
                             argument_roles=roles, profile=RELATIONAL_PROSE_PROFILE)
    with pytest.raises(TypeError):
        decompile_relational(expression, argument_roles=roles, profile=RELATIONAL_PROSE_PROFILE,
                             source_text="Hidden original bytes.")
    rendered = decompile_relational(expression, argument_roles=roles, profile=RELATIONAL_PROSE_PROFILE)
    assert "independent:prose" not in rendered
    assert "node_id" not in rendered and "content_digest" not in rendered
    assert "schema_version" not in rendered and "base64" not in rendered


def test_relational_prose_rejects_unused_typed_predicate_without_dropping_it():
    expression, roles = _prose_fixture()
    declared = prose_signatures.declare_predicate("Unused", (prose_signatures.LogicSort("Object"),))
    signature = expression.signature.extend(signature_id="independent:unused", symbols=(declared,))
    expression = prose_ast.TypedExpression("independent:unused", expression.root, signature)
    roles.append({"symbol": "Unused", "roles": ["actor"]})
    with pytest.raises(ValueError):
        decompile_relational(expression, argument_roles=roles, profile=RELATIONAL_PROSE_PROFILE)


def test_relational_prose_rejects_unsupported_node_without_rendering_supported_prefix():
    tree = _ProseTree()
    body = prose_ast.mk_and(tree.nid(), tree.atom("Relates", "actor", "actor"), prose_ast.mk_true(tree.nid()))
    body = tree.quantify(body, [("actor", "forall", "Object")])
    expression, roles = tree.expression(body, [("Relates", [("actor", "Object"), ("recipient", "Object")])])
    with pytest.raises(ValueError):
        decompile_relational(expression, argument_roles=roles, profile=RELATIONAL_PROSE_PROFILE)


def _independent_fixed_three_fixture():
    tree = _ProseTree(family="first_order", profile="many_sorted", mixed=True)
    members = [tree.atom("Member", name, ("event", "EventFrame"), ("time", "TimeFrame"))
               for name in ("x0", "x1", "x2", "x3")]
    pairs = (("x0", "x1"), ("x0", "x2"), ("x0", "x3"),
             ("x1", "x2"), ("x1", "x3"), ("x2", "x3"))
    equalities = [prose_ast.mk_equality(tree.nid(), tree.variable(left), tree.variable(right))
                  for left, right in pairs]
    antecedent, consequent = members[0], equalities[0]
    for member in members[1:]:
        antecedent = prose_ast.mk_and(tree.nid(), antecedent, member)
    for equality in equalities[1:]:
        consequent = prose_ast.mk_or(tree.nid(), consequent, equality)
    root = tree.quantify(prose_ast.mk_implies(tree.nid(), antecedent, consequent),
        [("event", "forall", "EventFrame"), ("time", "forall", "TimeFrame"),
         *((name, "forall", "Object") for name in ("x0", "x1", "x2", "x3"))])
    return tree.expression(root, [("Member", [("object", "Object"),
        ("event", "EventFrame"), ("time", "TimeFrame")])])


_COUNTED_THREE_PROSE = (
    "Typed legal rule: first_order/many_sorted.\nTypes: EventFrame, Object, TimeFrame.\n"
    "Predicate Member: object of type Object; event of type EventFrame; time of type TimeFrame.\n"
    "Rule: (for each event of type EventFrame and time of type TimeFrame, at most 3 distinct "
    "objects of type Object satisfy Member with object: the object; event: event; time: time)."
)


def test_fixed_three_count_prose_matches_independently_authored_complete_expansion():
    expression, roles = _independent_fixed_three_fixture()
    assert decompile_relational(expression, argument_roles=roles, profile=COUNTED_PROSE_PROFILE) == _COUNTED_THREE_PROSE
    reconstructed, reconstructed_roles = compile_relational(_COUNTED_THREE_PROSE, profile=COUNTED_PROSE_PROFILE)
    left, right = _prose_transport_free(expression.to_dict()), _prose_transport_free(reconstructed.to_dict())
    left["signature"]["sorts"].sort(key=lambda item: item["name"])
    right["signature"]["sorts"].sort(key=lambda item: item["name"])
    assert left == right and reconstructed_roles == roles


@pytest.mark.parametrize("boundary", [2, 4])
def test_other_count_boundaries_are_explicitly_unsupported_in_fixed_three_profile(boundary):
    # This qualifies whole-input unsupported handling, not legal count semantics.
    changed = _COUNTED_THREE_PROSE.replace("at most 3", "at most " + str(boundary))
    assert compile_relational(changed, profile=COUNTED_PROSE_PROFILE) is None


def test_fixed_three_profile_refuses_mutated_equality_pair_in_complete_count_expansion():
    expression, roles = _independent_fixed_three_fixture()
    # Change one equality at a real leaf while preserving a well-sorted AST.
    def change(node):
        if node.kind is prose_ast.NodeKind.EQUALITY:
            return prose_ast.mk_equality(node.node_id,
                prose_ast.mk_variable(node.arguments[0].node_id, "x0", node.arguments[0].sort),
                prose_ast.mk_variable(node.arguments[1].node_id, "x0", node.arguments[1].sort))
        return prose_ast.LogicNode(node.node_id, node.kind, sort=node.sort, symbol=node.symbol,
            arguments=tuple(change(child) for child in node.arguments), binders=node.binders,
            extension=node.extension)
    mutated = prose_ast.TypedExpression("independent:wrong-count", change(expression.root), expression.signature)
    with pytest.raises(ValueError):
        decompile_relational(mutated, argument_roles=roles, profile=COUNTED_PROSE_PROFILE)


def test_relational_prose_refuses_unknown_extension_with_supported_child_intact():
    tree = _ProseTree()
    unsupported = prose_ast.mk_extension(tree.nid(), family="tdfol", profile="tdfol_default",
        features=("legal.unavailable",), payload_schema="legal.unavailable/v1",
        payload={"kind": "unavailable", "schema_version": "legal.unavailable/v1"},
        children=(tree.atom("Relates", "actor", "actor"),))
    root = tree.quantify(unsupported, [("actor", "forall", "Object")])
    expression, roles = tree.expression(root, [("Relates", [("actor", "Object"), ("recipient", "Object")])])
    with pytest.raises(ValueError):
        decompile_relational(expression, argument_roles=roles, profile=RELATIONAL_PROSE_PROFILE)


def test_relational_prose_refuses_shadowed_binders_instead_of_dropping_a_quantifier():
    tree = _ProseTree()
    root = tree.quantify(tree.atom("Relates", "actor", "actor"),
        [("actor", "forall", "Object"), ("actor", "exists", "Object")])
    expression, roles = tree.expression(root, [("Relates", [("actor", "Object"), ("recipient", "Object")])])
    with pytest.raises(ValueError):
        decompile_relational(expression, argument_roles=roles, profile=RELATIONAL_PROSE_PROFILE)


def _generic_count_boundary_fixture(maximum):
    # Independent ordinary many-sorted FOL expansion. The prose profile retains
    # every quantifier/equality; it assigns no new statutory counting meaning.
    tree = _ProseTree(mixed=True)
    names = tuple("member" + str(index) for index in range(maximum + 1))
    members = [tree.atom("Member", name, ("event", "EventFrame"), ("time", "TimeFrame"))
               for name in names]
    equalities = [prose_ast.mk_equality(tree.nid(), tree.variable(left), tree.variable(right))
        for index, left in enumerate(names) for right in names[index + 1:]]
    conjunction, disjunction = members[0], equalities[0]
    for member in members[1:]:
        conjunction = prose_ast.mk_and(tree.nid(), conjunction, member)
    for equality in equalities[1:]:
        disjunction = prose_ast.mk_or(tree.nid(), disjunction, equality)
    root = tree.quantify(prose_ast.mk_implies(tree.nid(), conjunction, disjunction),
        [("event", "forall", "EventFrame"), ("time", "forall", "TimeFrame"),
         *((name, "forall", "Object") for name in names)])
    return tree.expression(root, [("Member", [("object", "Object"),
        ("event", "EventFrame"), ("time", "TimeFrame")])])


@pytest.mark.parametrize("maximum", [2, 3, 4])
def test_generic_count_expansion_preserves_each_supported_boundary_as_full_typed_structure(maximum):
    expression, roles = _generic_count_boundary_fixture(maximum)
    prose = decompile_relational(expression, argument_roles=roles, profile=RELATIONAL_PROSE_PROFILE)
    # The generic route must show every counting-expansion binder and typed
    # equality instead of forcing a tree into the separate fixed-three macro.
    for index in range(maximum + 1):
        assert "for every member" + str(index) + " of type Object" in prose
    assert "is identical to" in prose and "at most 3" not in prose
    reconstructed, reconstructed_roles = compile_relational(prose, profile=RELATIONAL_PROSE_PROFILE)
    left, right = _prose_transport_free(expression.to_dict()), _prose_transport_free(reconstructed.to_dict())
    left["signature"]["sorts"].sort(key=lambda item: item["name"])
    right["signature"]["sorts"].sort(key=lambda item: item["name"])
    assert left == right and reconstructed_roles == roles


def test_generic_count_boundary_mutations_cannot_become_the_same_reconstructed_tree():
    values = [_generic_count_boundary_fixture(maximum) for maximum in (2, 3, 4)]
    prose = [decompile_relational(expression, argument_roles=roles, profile=RELATIONAL_PROSE_PROFILE)
             for expression, roles in values]
    assert len(set(prose)) == 3
    parsed = [compile_relational(text, profile=RELATIONAL_PROSE_PROFILE)[0] for text in prose]
    assert len({str(_prose_transport_free(expression.to_dict())["root"]) for expression in parsed}) == 3


@pytest.mark.parametrize("channel", ["node", "signature", "extension"])
def test_relational_prose_rejects_nested_original_text_channels(channel):
    expression, roles = _prose_fixture()
    root, signature = expression.root, expression.signature
    metadata = {"source_text": "Hidden original bytes at a nested typed boundary."}
    if channel == "signature":
        signature = signature.extend(signature_id="independent:metadata-signature", metadata=metadata)
    elif channel == "node":
        root = prose_ast.LogicNode(root.node_id, root.kind, sort=root.sort, symbol=root.symbol,
            arguments=root.arguments, binders=root.binders, extension=root.extension, metadata=metadata)
    else:
        def transform(node):
            extension = node.extension
            if extension is not None:
                extension = prose_ast.LogicExtensionNode(extension.node_id,
                    extension.family, extension.profile, extension.features, extension.payload_schema,
                    extension.payload, children=extension.children, metadata=metadata)
            return prose_ast.LogicNode(node.node_id, node.kind, sort=node.sort, symbol=node.symbol,
                arguments=tuple(transform(child) for child in node.arguments),
                binders=node.binders, extension=extension)
        root = transform(root)
    source_bearing = prose_ast.TypedExpression("independent:nested-source", root, signature)
    with pytest.raises(ValueError):
        decompile_relational(source_bearing, argument_roles=roles, profile=RELATIONAL_PROSE_PROFILE)


@pytest.mark.parametrize("symbol", ["both", "either", "if"])
def test_existing_legal_predicate_symbols_that_match_prose_connectives_are_unambiguous(symbol):
    tree = _ProseTree()
    root = tree.quantify(tree.atom(symbol, "actor"), [("actor", "forall", "Object")])
    expression, roles = tree.expression(root, [(symbol, [("actor", "Object")])])
    expected = (
        "Typed legal rule: tdfol/tdfol_default.\nTypes: Object.\nPredicate " + symbol +
        ": actor of type Object.\nRule: (for every actor of type Object, (" + symbol +
        " holds for actor: actor of type Object))."
    )
    assert decompile_relational(expression, argument_roles=roles, profile=RELATIONAL_PROSE_PROFILE) == expected
    parsed = compile_relational(expected, profile=RELATIONAL_PROSE_PROFILE)
    assert parsed is not None
    reconstructed, reconstructed_roles = parsed
    assert _prose_transport_free(reconstructed.to_dict()) == _prose_transport_free(expression.to_dict())
    assert reconstructed_roles == roles


def test_existing_equality_variable_named_if_does_not_become_a_prose_conditional():
    tree = _ProseTree(mixed=True)
    equality = prose_ast.mk_equality(tree.nid(), tree.variable("if"), tree.variable("recipient"))
    root = tree.quantify(prose_ast.mk_and(tree.nid(), equality,
        tree.atom("Member", "if", ("event", "EventFrame"), ("time", "TimeFrame"))),
        [("if", "forall", "Object"), ("recipient", "exists", "Object"),
         ("event", "forall", "EventFrame"), ("time", "forall", "TimeFrame")])
    expression, roles = tree.expression(root, [("Member", [("object", "Object"),
        ("event", "EventFrame"), ("time", "TimeFrame")])])
    prose = decompile_relational(expression, argument_roles=roles, profile=RELATIONAL_PROSE_PROFILE)
    assert "(if of type Object is identical to recipient of type Object)" in prose
    parsed = compile_relational(prose, profile=RELATIONAL_PROSE_PROFILE)
    assert parsed is not None
    reconstructed, reconstructed_roles = parsed
    left, right = _prose_transport_free(expression.to_dict()), _prose_transport_free(reconstructed.to_dict())
    left["signature"]["sorts"].sort(key=lambda item: item["name"])
    right["signature"]["sorts"].sort(key=lambda item: item["name"])
    assert left == right and reconstructed_roles == roles


def test_relational_prose_refuses_deontic_extension_whose_child_is_a_term():
    # Syntax-core extensions can have term children for other families. This
    # profile's legacy deontic O/P/F operators require a complete formula child.
    tree = _ProseTree()
    root = tree.quantify(prose_ast.mk_and(tree.nid(),
        tree.atom("Relates", "actor", "actor"), tree.modal("O", tree.variable("actor"))),
        [("actor", "forall", "Object")])
    expression, roles = tree.expression(root, [("Relates", [("actor", "Object"), ("recipient", "Object")])])
    with pytest.raises(ValueError):
        decompile_relational(expression, argument_roles=roles, profile=RELATIONAL_PROSE_PROFILE)


# v02 controls enter the new public relational APIs. Guard probes retain and
# rethrow the actual implementation error; they do not replace the decision.
from ipfs_datasets_py.logic.legal_ir import extended_compiler as relational_compiler
from ipfs_datasets_py.logic.legal_ir import extended_decompiler as relational_decompiler
from ipfs_datasets_py.logic.autoformal import legal_relational_norm_v1 as relational_contract


def _unexpected_relational_boundary_stage(*args, **kwargs):
    raise AssertionError("later relational boundary stage must not be reached")


def _observe_relational_reader_guard(monkeypatch, method):
    original = getattr(relational_compiler._RelationalProseReader, method)
    observed = []
    def observe(reader, *args, **kwargs):
        try:
            return original(reader, *args, **kwargs)
        except ValueError as error:
            if not observed:
                observed.append({"message": str(error), "formulas": reader.formulas,
                                 "node_ids": reader.serial})
            raise
    monkeypatch.setattr(relational_compiler._RelationalProseReader, method, observe)
    return observed


def _balanced_boundary_body(tree, leaves):
    if len(leaves) == 1:
        return leaves[0]
    middle = len(leaves) // 2
    return prose_ast.mk_and(tree.nid(),
        _balanced_boundary_body(tree, leaves[:middle]),
        _balanced_boundary_body(tree, leaves[middle:]))


def _relational_boundary_tree(*, leaves=1, arity=1, predicates=1, negations=0):
    tree = _ProseTree()
    declarations = [("Relation" + str(index).zfill(2),
        [("role" + str(position), "Object") for position in range(arity)])
        for index in range(predicates)]
    assert leaves >= predicates
    atoms = [tree.atom(declarations[index % predicates][0], *("actor",) * arity)
             for index in range(leaves)]
    body = _balanced_boundary_body(tree, atoms)
    for _ in range(negations):
        body = prose_ast.mk_not(tree.nid(), body)
    root = tree.quantify(body, [("actor", "forall", "Object")])
    return tree.expression(root, declarations)


def _relational_boundary_text(*, leaves=1, arity=1, predicates=1, negations=0):
    # Independently authored visible grammar, including complete excessive
    # declarations. An oversized fixture would be well-formed absent its bound.
    names = ["Relation" + str(index).zfill(2) for index in range(predicates)]
    fields = ["role" + str(index) + " of type Object" for index in range(arity)]
    atoms = ["(" + names[index % predicates] + " holds for " + "; ".join(
        "role" + str(position) + ": actor of type Object" for position in range(arity)) + ")"
        for index in range(leaves)]
    def balanced(parts):
        if len(parts) == 1:
            return parts[0]
        middle = len(parts) // 2
        return "(both " + balanced(parts[:middle]) + " and " + balanced(parts[middle:]) + ")"
    body = balanced(atoms)
    for _ in range(negations):
        body = "(it is not the case that " + body + ")"
    return ("Typed legal rule: tdfol/tdfol_default.\nTypes: Object.\n"
        + "".join("Predicate " + name + ": " + "; ".join(fields) + ".\n" for name in names)
        + "Rule: (for every actor of type Object, " + body + ").")


def test_relational_compiler_surrogate_refusal_occurs_before_reader(monkeypatch):
    monkeypatch.setattr(relational_compiler._RelationalProseReader, "__init__",
                        _unexpected_relational_boundary_stage)
    # A Python str surrogate fails UTF8 encoding, independently of grammar.
    assert compile_relational(_PROSE_OBLIGATION + "\ud800", profile=RELATIONAL_PROSE_PROFILE) is None


def test_relational_compiler_multibyte_byte_bound_occurs_before_reader(monkeypatch):
    assert relational_compiler.MAX_RENDERED_UTF8_BYTES == 1024 * 1024
    monkeypatch.setattr(relational_compiler._RelationalProseReader, "__init__",
                        _unexpected_relational_boundary_stage)
    cap = relational_compiler.MAX_RENDERED_UTF8_BYTES
    candidate = "é" * (cap // 2 + 1)
    assert len(candidate) <= cap < len(candidate.encode("utf-8"))
    assert compile_relational(candidate, profile=RELATIONAL_PROSE_PROFILE) is None


def test_relational_public_api_byte_limits_accept_exact_payload_and_refuse_one_less(monkeypatch):
    expression, roles = _prose_fixture()
    size = len(_PROSE_OBLIGATION.encode("utf-8"))
    assert size < relational_decompiler.MAX_RENDERED_UTF8_BYTES
    # Tighten only the test-local caps to make each otherwise masked bound
    # reachable with a complete valid span. No production policy is changed.
    monkeypatch.setattr(relational_decompiler, "MAX_RENDERED_UTF8_BYTES", size)
    monkeypatch.setattr(relational_compiler, "MAX_RENDERED_UTF8_BYTES", size)
    assert decompile_relational(expression, argument_roles=roles,
                                profile=RELATIONAL_PROSE_PROFILE) == _PROSE_OBLIGATION
    assert compile_relational(_PROSE_OBLIGATION, profile=RELATIONAL_PROSE_PROFILE) is not None
    monkeypatch.setattr(relational_decompiler, "MAX_RENDERED_UTF8_BYTES", size - 1)
    with pytest.raises(ValueError, match="complete relational prose exceeds bound; truncation refused"):
        decompile_relational(expression, argument_roles=roles, profile=RELATIONAL_PROSE_PROFILE)
    monkeypatch.setattr(relational_compiler, "MAX_RENDERED_UTF8_BYTES", size - 1)
    monkeypatch.setattr(relational_compiler._RelationalProseReader, "__init__",
                        _unexpected_relational_boundary_stage)
    assert compile_relational(_PROSE_OBLIGATION, profile=RELATIONAL_PROSE_PROFILE) is None


def test_relational_renderer_surrogate_reaches_wire_guard_before_role_validation(monkeypatch):
    expression, roles = _prose_fixture()
    roles[0]["roles"][1] = "\ud800"
    monkeypatch.setattr(relational_contract, "_strict_expression", _unexpected_relational_boundary_stage)
    with pytest.raises(ValueError, match="bounded ordinary UTF8 JSON required"):
        decompile_relational(expression, argument_roles=roles, profile=RELATIONAL_PROSE_PROFILE)


def test_relational_parser_default_depth_guard_precedes_typed_ast_readback(monkeypatch):
    observed = _observe_relational_reader_guard(monkeypatch, "sentence")
    monkeypatch.setattr(relational_decompiler, "decompile_relational", _unexpected_relational_boundary_stage)
    # forall depth0, 48 NOTs at depths1..48, atom at depth49.
    candidate = _relational_boundary_text(negations=48)
    assert compile_relational(candidate, profile=RELATIONAL_PROSE_PROFILE) is None
    assert observed and observed[0]["message"] == "complete prose formula/depth bound exceeded"
    assert observed[0]["formulas"] == 50


def test_relational_renderer_default_deep_tree_refusal_is_attributed_to_wire_guard(monkeypatch):
    expression, roles = _relational_boundary_tree(negations=48)
    monkeypatch.setattr(relational_contract, "_strict_expression", _unexpected_relational_boundary_stage)
    # Serialized AST edges consume two JSON levels. The existing wire depth96
    # guard runs before the later renderer depth48 guard on this default case.
    with pytest.raises(ValueError, match="bounded ordinary JSON required"):
        decompile_relational(expression, argument_roles=roles, profile=RELATIONAL_PROSE_PROFILE)


def test_relational_renderer_traversal_depth_boundary_uses_complete_valid_tree(monkeypatch):
    expression, roles = _prose_fixture()
    # The fixture's deepest variable is at depth4; wire validation stays valid.
    monkeypatch.setattr(relational_contract, "MAX_DEPTH", 4)
    assert decompile_relational(expression, argument_roles=roles,
                                profile=RELATIONAL_PROSE_PROFILE) == _PROSE_OBLIGATION
    monkeypatch.setattr(relational_contract, "MAX_DEPTH", 3)
    with pytest.raises(ValueError, match="unsupported or unbounded complete relational node"):
        decompile_relational(expression, argument_roles=roles, profile=RELATIONAL_PROSE_PROFILE)


def test_relational_renderer_default_node_limit_preserves_complete_balanced_tree(monkeypatch):
    # 170 predicates +170 variables +169 binary ANDs +one forall +two NOTs =512.
    expression, roles = _relational_boundary_tree(leaves=170, negations=2)
    expected = _relational_boundary_text(leaves=170, negations=2)
    assert relational_contract.MAX_NODES == 512
    assert decompile_relational(expression, argument_roles=roles,
                                profile=RELATIONAL_PROSE_PROFILE) == expected
    assert compile_relational(expected, profile=RELATIONAL_PROSE_PROFILE) is not None
    over, over_roles = _relational_boundary_tree(leaves=170, negations=3)
    with pytest.raises(ValueError, match="unsupported or unbounded complete relational node"):
        decompile_relational(over, argument_roles=over_roles, profile=RELATIONAL_PROSE_PROFILE)
    # The same 513-node public compile input reaches final typed readback; it
    # stays below parser formula512/ID1024/depth48 and source byte bounds.
    original = relational_decompiler.decompile_relational
    observed = []
    def readback(*args, **kwargs):
        try:
            return original(*args, **kwargs)
        except ValueError as error:
            observed.append(str(error))
            raise
    monkeypatch.setattr(relational_decompiler, "decompile_relational", readback)
    assert compile_relational(_relational_boundary_text(leaves=170, negations=3),
                              profile=RELATIONAL_PROSE_PROFILE) is None
    assert observed == ["unsupported or unbounded complete relational node"]


def test_relational_parser_formula_budget_refusal_uses_complete_balanced_input(monkeypatch):
    observed = _observe_relational_reader_guard(monkeypatch, "sentence")
    monkeypatch.setattr(relational_decompiler, "decompile_relational", _unexpected_relational_boundary_stage)
    # 257 atoms +256 ANDs +forall exceed formula512 while depth and IDs fit.
    assert compile_relational(_relational_boundary_text(leaves=257),
                              profile=RELATIONAL_PROSE_PROFILE) is None
    assert observed and observed[0]["message"] == "complete prose formula/depth bound exceeded"
    assert observed[0]["formulas"] == 513 and observed[0]["node_ids"] < 1024


def test_relational_parser_ast_id_budget_refusal_is_distinct_from_formula_budget(monkeypatch):
    observed = _observe_relational_reader_guard(monkeypatch, "nid")
    monkeypatch.setattr(relational_decompiler, "decompile_relational", _unexpected_relational_boundary_stage)
    # 128*9 predicate/variable nodes +127 ANDs +forall; only256 formulas.
    assert compile_relational(_relational_boundary_text(leaves=128, arity=8),
                              profile=RELATIONAL_PROSE_PROFILE) is None
    assert observed and observed[0]["message"] == "complete prose AST node bound exceeded"
    assert observed[0]["node_ids"] == 1025 and observed[0]["formulas"] < 512


def test_relational_predicate_count_boundaries_account_for_every_declaration(monkeypatch):
    expression, roles = _relational_boundary_tree(leaves=64, predicates=64)
    expected = _relational_boundary_text(leaves=64, predicates=64)
    assert decompile_relational(expression, argument_roles=roles,
                                profile=RELATIONAL_PROSE_PROFILE) == expected
    assert compile_relational(expected, profile=RELATIONAL_PROSE_PROFILE) is not None
    expression, roles = _relational_boundary_tree(leaves=65, predicates=65)
    with pytest.raises(ValueError, match="bounded nonempty predicate signature required"):
        decompile_relational(expression, argument_roles=roles, profile=RELATIONAL_PROSE_PROFILE)
    observed = _observe_relational_reader_guard(monkeypatch, "declarations")
    monkeypatch.setattr(relational_decompiler, "decompile_relational", _unexpected_relational_boundary_stage)
    assert compile_relational(_relational_boundary_text(leaves=65, predicates=65),
                              profile=RELATIONAL_PROSE_PROFILE) is None
    assert observed and observed[0]["message"] == "predicate declaration bound exceeded"


def test_relational_predicate_arity_boundaries_preserve_all_ordered_arguments(monkeypatch):
    expression, roles = _relational_boundary_tree(arity=8)
    expected = _relational_boundary_text(arity=8)
    assert decompile_relational(expression, argument_roles=roles,
                                profile=RELATIONAL_PROSE_PROFILE) == expected
    recovered = compile_relational(expected, profile=RELATIONAL_PROSE_PROFILE)
    assert recovered is not None and recovered[1] == roles
    expression, roles = _relational_boundary_tree(arity=9)
    with pytest.raises(ValueError, match="only bounded Object predicates supported"):
        decompile_relational(expression, argument_roles=roles, profile=RELATIONAL_PROSE_PROFILE)
    observed = _observe_relational_reader_guard(monkeypatch, "declarations")
    monkeypatch.setattr(relational_decompiler, "decompile_relational", _unexpected_relational_boundary_stage)
    assert compile_relational(_relational_boundary_text(arity=9), profile=RELATIONAL_PROSE_PROFILE) is None
    assert observed and observed[0]["message"] == "complete ordered predicate arity bound exceeded"


@pytest.mark.parametrize("collection, message", [
    ("nary_and", "exact binary connective required; no flattening"),
    ("binder_pair", "exactly one binder per quantifier required"),
    ("role_rows", "roles must cover every declared predicate"),
    ("role_columns", "ordered distinct bounded argument roles required"),
])
def test_relational_collection_shapes_refuse_without_omitting_members(collection, message):
    tree = _ProseTree()
    if collection == "nary_and":
        body = prose_ast.mk_and(tree.nid(), *(tree.atom("Relates", "actor", "actor") for _ in range(3)))
        root = tree.quantify(body, [("actor", "forall", "Object")])
    elif collection == "binder_pair":
        root = prose_ast.mk_forall(tree.nid(), (prose_ast.Binder("actor", tree.sorts["Object"]),
            prose_ast.Binder("recipient", tree.sorts["Object"])), tree.atom("Relates", "actor", "recipient"))
    else:
        root = tree.quantify(tree.atom("Relates", "actor", "actor"), [("actor", "forall", "Object")])
    expression, roles = tree.expression(root, [("Relates", [("actor", "Object"), ("recipient", "Object")])])
    if collection == "role_rows":
        roles = []
    elif collection == "role_columns":
        roles[0]["roles"].pop()
    with pytest.raises(ValueError, match=message):
        decompile_relational(expression, argument_roles=roles, profile=RELATIONAL_PROSE_PROFILE)


@pytest.mark.parametrize("scalar, message", [
    ("byte_source", "source must be nonempty text"),
    ("bool_profile", "explicit supported relational prose profile required"),
    ("tuple_ledger", "complete ordinary ordered argument role ledger required"),
    ("tuple_roles", "ordinary finite JSON required"),
    ("bool_role", "ordered distinct bounded argument roles required"),
    ("float_role", "ordinary finite JSON required"),
    ("oversized_integer", "bounded JSON integer required"),
])
def test_relational_scalar_contracts_identify_the_first_refusal_guard(scalar, message):
    expression, roles = _prose_fixture()
    with pytest.raises(ValueError, match=message):
        if scalar == "byte_source":
            # Bytes are outside this str API; this is not a UTF8 decoder test.
            compile_relational(b"\xff", profile=RELATIONAL_PROSE_PROFILE)
        elif scalar == "bool_profile":
            compile_relational(_PROSE_OBLIGATION, profile=True)
        else:
            if scalar == "tuple_ledger":
                roles = tuple(roles)
            elif scalar == "tuple_roles":
                roles[0]["roles"] = tuple(roles[0]["roles"])
            else:
                roles[0]["roles"][1] = {"bool_role": True, "float_role": 1.5,
                                        "oversized_integer": 1 << 63}[scalar]
            decompile_relational(expression, argument_roles=roles, profile=RELATIONAL_PROSE_PROFILE)


# Fictional controlled statements with independently authored temporal values.
from ipfs_datasets_py.logic.TDFOL.compiler_repairs import TemporalDeadline, compile_temporal_deadline
from ipfs_datasets_py.logic.legal_ir.extended_contracts import (
    EXTENDED_DEADLINE_IR_SCHEMA, EXTENDED_IR_SCHEMA, ExtendedDeadlineLegalIR,
)
from ipfs_datasets_py.logic.legal_ir.extended_decompiler import TYPED_DEADLINE_PROSE_PROFILE


_DEADLINE_NORM = 'Norm: "clerk" must "file" "notice".'
_CALENDAR = TemporalDeadline("receipt_of_notice", "event", True, 3, "after", "calendar_days")
_CALENDAR_CLAUSE = 'within 3 calendar days after event "receipt_of_notice"'


@pytest.mark.parametrize("clause,expected", [
    (_CALENDAR_CLAUSE, _CALENDAR),
    ('within 3 business days after event "receipt_of_notice"',
     TemporalDeadline("receipt_of_notice", "event", True, 3, "after", "business_days")),
    ('within 4 calendar days after event "receipt_of_notice"',
     TemporalDeadline("receipt_of_notice", "event", True, 4, "after", "calendar_days")),
    ('within 3 calendar days after event "notice_delivery"',
     TemporalDeadline("notice_delivery", "event", True, 3, "after", "calendar_days")),
    ('within 3 calendar days before event "receipt_of_notice"',
     TemporalDeadline("receipt_of_notice", "event", True, 3, "before", "calendar_days")),
    ('less than 3 calendar days after event "receipt_of_notice"',
     TemporalDeadline("receipt_of_notice", "event", False, 3, "after", "calendar_days")),
    ('within 1 business day from event "notice_Receipt"',
     TemporalDeadline("notice_Receipt", "event", True, 1, "from", "business_days")),
    ('within 0 calendar days after event "receipt_of_notice"',
     TemporalDeadline("receipt_of_notice", "event", True, 0, "after", "calendar_days")),
    ('within 999999999 calendar days after event "receipt_of_notice"',
     TemporalDeadline("receipt_of_notice", "event", True, 999999999, "after", "calendar_days")),
    ('on or before instant "filing_cutoff"',
     TemporalDeadline("filing_cutoff", "instant", True, 0, "before_or_at", "instant")),
    ('before instant "filing_cutoff"',
     TemporalDeadline("filing_cutoff", "instant", False, 0, "before", "instant")),
    ('before event "filing_cutoff"',
     TemporalDeadline("filing_cutoff", "event", False, 0, "before", "instant")),
    ('after event or instant "filing_cutoff"',
     TemporalDeadline("filing_cutoff", "event_or_instant", False, 0, "after", "instant")),
])
def test_explicit_typed_deadlines_reconstruct_every_independently_authored_field(clause, expected):
    prose = f"{_DEADLINE_NORM} Temporal: {clause}."
    profile = TYPED_DEADLINE_PROSE_PROFILE
    authored = ExtendedDeadlineLegalIR((NormV2("O", "clerk", "file", "notice", temporal=(expected,)),))
    parsed = compile_extended(prose, profile=profile)
    assert type(parsed) is ExtendedDeadlineLegalIR
    assert parsed == authored
    wire = parsed.to_dict()
    assert wire == {"schema": EXTENDED_DEADLINE_IR_SCHEMA, "statements": [{
        "kind": "norm", "modality": "O", "actor": "clerk", "action": "file", "object": "notice",
        "scope": [], "conditions": [], "exceptions": [], "temporal": [{
            "anchor": expected.anchor, "anchor_type": expected.anchor_type, "offset": expected.offset,
            "inclusive": expected.inclusive, "relation": expected.relation, "unit": expected.unit,
        }],
    }]}
    assert ExtendedLegalIR.from_dict(wire) == authored
    assert decompile_extended(authored, profile=profile) == prose
    assert compile_extended(decompile_extended(authored, profile=profile), profile=profile) == authored
    assert compile_extended(prose) is None
    if clause != _CALENDAR_CLAUSE:
        baseline = compile_extended(f"{_DEADLINE_NORM} Temporal: {_CALENDAR_CLAUSE}.", profile=profile)
        assert baseline.statements[0].temporal == (_CALENDAR,)
        assert parsed.to_dict() != baseline.to_dict()


def test_typed_deadline_roundtrip_preserves_norm_ownership_temporal_order_and_duplicates():
    first = (f'{_DEADLINE_NORM} Scope: "State A". Conditions: "on request". Exceptions: "if sealed".'
             f' Temporal: {_CALENDAR_CLAUSE}; "effective 2025-01-01"; {_CALENDAR_CLAUSE}.')
    second = ('Norm: "director" may "retain" "copy". Temporal: '
              'within 3 business days after event "receipt_of_notice".')
    definition = 'Definition: "office" means "registry". Temporal: "effective 2024-01-01".'
    prose = "\n".join((first, second, definition))
    profile = TYPED_DEADLINE_PROSE_PROFILE
    actual = compile_extended(prose, profile=profile)
    expected = ExtendedDeadlineLegalIR((
        NormV2("O", "clerk", "file", "notice", scope=("State A",), conditions=("on request",),
               exceptions=("if sealed",), temporal=(_CALENDAR, "effective 2025-01-01", _CALENDAR)),
        NormV2("P", "director", "retain", "copy", temporal=(
            TemporalDeadline("receipt_of_notice", "event", True, 3, "after", "business_days"),)),
        DefinitionV2("office", "means", "registry", temporal=("effective 2024-01-01",)),
    ))
    assert actual == expected
    assert decompile_extended(actual, profile=profile) == prose
    assert ExtendedLegalIR.from_dict(actual.to_dict()) == expected
    for changed in (prose.replace("effective 2025", "effective 2026"),
                    prose.replace("State A", "State B"),
                    prose.replace("Exceptions: \"if sealed\". ", ""),
                    prose.replace(f'{_CALENDAR_CLAUSE}; "effective 2025-01-01"',
                                  f'"effective 2025-01-01"; {_CALENDAR_CLAUSE}', 1)):
        reparsed = compile_extended(changed, profile=profile)
        assert reparsed is not None and reparsed.to_dict() != actual.to_dict()


@pytest.mark.parametrize("invalid_clause", [
    'within 3 days after event "receipt_of_notice"',
    'within 3 business dayshift after event "receipt_of_notice"',
    'within 3 calendar days',
    'within 3 calendar days after',
    'within 3 calendar days after event ""',
    'within 3 calendar days after event "notice receipt"',
    'within 3 calendar days after event "receipt_of_notice" or event "filing"',
    'within 3 calendar days after event "receipt_of_notice" under Calendar_A',
    'within 3 calendar days after instant "receipt_of_notice"',
    'within 3 weeks after event "receipt_of_notice"',
    'within -3 calendar days after event "receipt_of_notice"',
    'within 3.5 calendar days after event "receipt_of_notice"',
    'within 03 calendar days after event "receipt_of_notice"',
    'within 1000000000 calendar days after event "receipt_of_notice"',
    'within 1 business days after event "receipt_of_notice"',
    'within 3 business day after event "receipt_of_notice"',
    'until event "receipt_of_notice"',
    'after "receipt_of_notice"',
    'on or before event "receipt_of_notice" inclusive',
    'before instant "2025-01-01"',
    f'after event "{"a" * 129}"',
    r'after event "receipt\u005fof_notice"',
])
def test_explicit_typed_deadline_refuses_unsupported_or_partial_clauses_whole_span(invalid_clause):
    profile = TYPED_DEADLINE_PROSE_PROFILE
    assert compile_extended(f"{_DEADLINE_NORM} Temporal: {invalid_clause}.", profile=profile) is None
    assert compile_extended(
        f"{_DEADLINE_NORM} Temporal: {_CALENDAR_CLAUSE}; {invalid_clause}.", profile=profile) is None


@pytest.mark.parametrize("record_change", [
    {"offset": True}, {"offset": 3.0}, {"offset": -1}, {"inclusive": 1}, {"anchor": "invalid name"},
    {"anchor_type": "instant"}, {"anchor_type": []}, {"unit": "days"}, {"unit": []},
    {"relation": "from_trigger"}, {"calendar": "invented_calendar"}, {"source_text": "hidden original"},
    {"constraint_id": "historical provenance is outside semantic IR"},
    {"unit": "instant", "offset": 3}, {"unit": "instant", "offset": 0},
])
def test_explicit_typed_deadline_wire_rejects_extra_and_inconsistent_fields(record_change):
    ir = ExtendedDeadlineLegalIR((NormV2("O", "clerk", "file", "notice", temporal=(_CALENDAR,)),))
    wire = ir.to_dict()
    wire["statements"][0]["temporal"][0].update(record_change)
    with pytest.raises(ValueError):
        ExtendedLegalIR.from_dict(wire)


def test_typed_deadline_requires_explicit_profile_complete_inventory_and_norm_scope():
    profile = TYPED_DEADLINE_PROSE_PROFILE
    literal_text = f'{_DEADLINE_NORM} Temporal: "within 3 calendar days".'
    literal = compile_extended(literal_text)
    assert literal.to_dict()["schema"] == EXTENDED_IR_SCHEMA
    assert literal.statements[0].temporal == ("within 3 calendar days",)
    assert decompile_extended(literal) == literal_text
    assert compile_extended(literal_text, profile=profile) is None
    assert compile_extended(_DEADLINE_NORM, profile=profile) is None
    valid_prose = f'{_DEADLINE_NORM} Temporal: {_CALENDAR_CLAUSE}.'
    for statement in ('Definition: "office" means "registry".', 'Policy: "agency" supports "access".'):
        assert compile_extended(f"{valid_prose}\n{statement} Temporal: {_CALENDAR_CLAUSE}.",
                                profile=profile) is None
    typed = compile_extended(valid_prose, profile=profile)
    with pytest.raises(ValueError):
        decompile_extended(typed)
    with pytest.raises(ValueError):
        decompile_extended(literal, profile=profile)
    with pytest.raises(ValueError):
        ExtendedLegalIR(typed.statements)
    with pytest.raises(ValueError):
        ExtendedDeadlineLegalIR(literal.statements)
    for ir, schema in ((typed, EXTENDED_IR_SCHEMA), (literal, EXTENDED_DEADLINE_IR_SCHEMA)):
        wire = ir.to_dict()
        wire["schema"] = schema
        with pytest.raises(ValueError):
            ExtendedLegalIR.from_dict(wire)


def test_deadline_renderer_revalidates_forged_value_and_refuses_hidden_source_parameter():
    deadline = TemporalDeadline("receipt_of_notice", "event", True, 3, "after", "calendar_days")
    ir = ExtendedDeadlineLegalIR((NormV2("O", "clerk", "file", "notice", temporal=(deadline,)),))
    with pytest.raises(TypeError):
        decompile_extended(ir, profile=TYPED_DEADLINE_PROSE_PROFILE, source_text="hidden source")
    object.__setattr__(deadline, "inclusive", 1)
    with pytest.raises(ValueError):
        decompile_extended(ir, profile=TYPED_DEADLINE_PROSE_PROFILE)


def test_existing_tdfol_business_day_candidate_retains_legacy_constraint_identity():
    candidate = compile_temporal_deadline("within 3 business days after receipt of notice")
    assert candidate["constraints"] == [{
        "anchor": "receipt_of_notice", "anchor_type": "event", "inclusive": True, "offset": 3,
        "relation": "after", "unit": "business_days",
        "constraint_id": "tdfol-deadline:ce72a7b410cd7d7da95088be",
    }]
