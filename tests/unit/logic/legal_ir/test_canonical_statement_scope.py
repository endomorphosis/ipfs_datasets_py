"""Handcrafted scope declarations test transport, never semantic gold."""

import builtins
import copy
import hashlib
import json

import pytest

from ipfs_datasets_py.logic.legal_ir import canonical_statement_scope as subject

MASKS = ("weak_decoder_fit", "strong_semantic_fit", "contrastive_supervision", "proof_supervision", "fidelity_evaluation")
FALSE_FLAGS = (
    "target_access", "source_fidelity_established", "source_semantics_verified", "qualified", "accepted",
    "proof_authority", "semantic_equivalence_assessed", "semantic_profile_validated", "binder_terms_typechecked",
    "normalization_approved", "lowering_authorized", "training_executed", "model_executed",
)


def raw(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


def digest(value):
    return hashlib.sha256(raw(value)).hexdigest()


def text_sha(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def seal(declaration):
    declaration["content_sha256"] = digest({key: value for key, value in declaration.items() if key != "content_sha256"})
    return declaration


def span(text, start=0, end=None, *, origin="source"):
    end = len(text) if end is None else end
    return {"origin": origin, "start": start, "end": end, "text": text[start:end],
            "offset_unit": "unicode_character_half_open"}


def literal_span(text, literal, *, origin="source", after=0):
    start = text.index(literal, after)
    return span(text, start, start + len(literal), origin=origin)


def occurrence(identity, facet, symbol, text, literal, *, after=0, origin="source"):
    return {"occurrence_id": identity, "facet": facet, "canonical_symbol": symbol,
            "anchor": literal_span(text, literal, after=after, origin=origin)}


def leaf(identity):
    return {"op": "leaf", "occurrence_id": identity}


def connective(op, children, *, operator_anchor=None):
    return {"op": op, "children": children, "operator_anchor": operator_anchor}


def rule_leaf(identity):
    return {"op": "rule", "rule_id": identity}


def cover_all(value):
    declaration, request = value["declaration"], value["request"]
    segments = []
    for origin, text in (("source", request["source_text"]), ("context", request["context"]["text"])):
        if text:
            segments.append({"span": span(text, origin=origin), "disposition": "represented",
                             "rule_ids": [rule["rule_id"] for rule in declaration["rules"]],
                             "occurrence_ids": [row["occurrence_id"] for row in declaration["occurrences"]
                                                if row["anchor"]["origin"] == origin],
                             "reason": "Synthetic literal coverage declaration; meaning is unverified"})
    declaration["coverage"] = {"declared_status": "complete", "segments": segments}


def refresh_input(value):
    value["request"]["context"]["sha256"] = text_sha(value["request"]["context"]["text"])
    value["expected_input_sha256"] = digest(value["request"])
    value["declaration"]["input"] = copy.deepcopy(value["request"])
    value["declaration"]["input_sha256"] = value["expected_input_sha256"]


def scope_case(*, repeated=True, context_text=""):
    condition_text = "B and A and B" if repeated else "A"
    source = f"É📄 the clerk must retain evidence if {condition_text} unless X or Y before T."
    request = {"source_text": source,
               "context": {"role": "declared_context" if context_text else "none_required",
                           "text": context_text, "bindings": {}, "sha256": text_sha(context_text)}}
    occurrences = [occurrence("actor", "actor", "clerk", source, "the clerk"),
                   occurrence("modal", "modality", "O", source, "must"),
                   occurrence("action", "action", "retain", source, "retain"),
                   occurrence("object", "object", "evidence", source, "evidence")]
    if repeated:
        first = occurrence("q1", "conditions", "b", source, "B")
        occurrences.extend([first, occurrence("q2", "conditions", "a", source, "A"),
                            occurrence("q3", "conditions", "b", source, "B", after=first["anchor"]["end"])])
        conditions = connective("all", [leaf("q1"), leaf("q2"), leaf("q3")],
                                operator_anchor=literal_span(source, "and"))
    else:
        occurrences.append(occurrence("q1", "conditions", "a", source, "A"))
        conditions = leaf("q1")
    occurrences.extend([occurrence("x", "exceptions", "x", source, "X"),
                        occurrence("y", "exceptions", "y", source, "Y"),
                        occurrence("t", "temporal", "t", source, "T")])
    declaration = {"schema": "canonical-normative-scope-declaration/v1", "family": "deontic",
                   "profile": "normative-occurrence-scope/v1", "input": copy.deepcopy(request),
                   "input_sha256": digest(request), "occurrences": occurrences,
                   "rules": [{"rule_id": "r1", "body": {"modality": "modal", "actor": "actor",
                                                        "action": "action", "object": "object"},
                              "qualifiers": {"conditions": conditions,
                                             "exceptions": connective("any", [leaf("x"), leaf("y")],
                                                                      operator_anchor=literal_span(source, "or")),
                                             "temporal": leaf("t")}}],
                   "statement_structure": rule_leaf("r1"), "binders": [], "coverage": {}, "unresolved": []}
    value = {"request": request, "declaration": declaration, "expected_input_sha256": digest(request)}
    cover_all(value)
    seal(declaration)
    return value


def two_rule_case():
    value = scope_case(repeated=False)
    value["request"]["source_text"] += " The auditor must release records."
    text = value["request"]["source_text"]
    second_start = text.index("The auditor")
    declaration = value["declaration"]
    declaration["occurrences"].extend([
        occurrence("actor2", "actor", "auditor", text, "The auditor", after=second_start),
        occurrence("modal2", "modality", "O", text, "must", after=second_start),
        occurrence("action2", "action", "release", text, "release", after=second_start),
        occurrence("object2", "object", "records", text, "records", after=second_start),
    ])
    declaration["rules"].append({"rule_id": "r2", "body": {"modality": "modal2", "actor": "actor2",
                                                             "action": "action2", "object": "object2"},
                                 "qualifiers": dict.fromkeys(("conditions", "exceptions", "temporal"))})
    declaration["statement_structure"] = connective("all", [rule_leaf("r1"), rule_leaf("r2")])
    refresh_input(value)
    cover_all(value)
    seal(declaration)
    return value


def add_binder(value, *, scope_path="/rules/0", bound=("actor",)):
    value["request"]["source_text"] += " For each z in People."
    text = value["request"]["source_text"]
    declaration = value["declaration"]
    declaration["occurrences"].extend([
        occurrence("variable", "binder_variable", "z", text, "z"),
        occurrence("domain", "binder_domain", "People", text, "People"),
    ])
    declaration["binders"].append({"binder_id": "binder1", "quantifier": "forall",
                                    "variable_occurrence": "variable", "domain_occurrence": "domain",
                                    "scope_path": scope_path, "bound_occurrence_ids": list(bound)})
    refresh_input(value)
    cover_all(value)
    seal(declaration)


def validate(value):
    return subject.validate_scope_declaration(**value)


def assess(value, **options):
    return subject.assess_flat_profile_compatibility(value["declaration"], **options)


def codes(receipt):
    return {issue["code"] for issue in receipt["issues"]}


def assert_diagnostic(receipt):
    assert all(receipt[field] is False for field in FALSE_FLAGS)
    assert receipt["masks"] == dict.fromkeys(MASKS, 0)
    assert all(type(value) is int and value == 0 for value in receipt["masks"].values())
    assert type(receipt["model_calls"]) is int and receipt["model_calls"] == 0
    assert type(receipt["prover_calls"]) is int and receipt["prover_calls"] == 0
    if "profiles" in receipt:
        assert receipt["lowered_ir"] is None
        for profile in receipt["profiles"].values():
            assert profile["scope_sidecar_required"] is True
            assert profile["standalone_scope_roundtrip_lossless"] is False
            assert profile["complete_legacy_encoding_qualified"] is False
    else:
        assert receipt["context_resolved"] is False
        assert receipt["verification_status"] == receipt["admission_status"] == "pending"


def test_exact_unicode_spans_repeated_occurrence_ids_and_order_survive_transport():
    value = scope_case()
    before = copy.deepcopy(value)
    result = validate(value)
    assert result["declaration"] == value["declaration"]
    assert result["occurrence_count"] == 10 and result["rule_count"] == 1
    actor = value["declaration"]["occurrences"][0]["anchor"]
    assert actor["start"] == 3 and len(value["request"]["source_text"][:3].encode("utf-8")) == 7
    repeated = [row for row in result["declaration"]["occurrences"] if row["canonical_symbol"] == "b"]
    assert len(repeated) == 2
    assert repeated[0]["anchor"]["start"] != repeated[1]["anchor"]["start"]
    assert [child["occurrence_id"] for child in result["declaration"]["rules"][0]["qualifiers"]["conditions"]["children"]] == ["q1", "q2", "q3"]
    assert value == before
    assert_diagnostic(result)


def test_duplicate_qualifiers_require_unapproved_normalization_not_silent_deduplication():
    value = scope_case()
    result = assess(value)
    assert "legacy_qualifier_sort_or_dedup_loses_occurrences" in codes(result)
    assert all(profile["status"] == "normalization_required_unapproved" for profile in result["profiles"].values())
    assert result["byte_encoding_capacity"]["checked"] is False
    assert value["declaration"]["rules"][0]["qualifiers"]["conditions"]["children"] == [leaf("q1"), leaf("q2"), leaf("q3")]
    assert_diagnostic(result)


def test_reordered_occurrences_are_distinct_records_without_equivalence_or_negative_labels():
    left = scope_case()
    right = copy.deepcopy(left)
    right["declaration"]["rules"][0]["qualifiers"]["conditions"]["children"].reverse()
    right["declaration"]["occurrences"].reverse()
    seal(right["declaration"])
    assert left["declaration"]["content_sha256"] != right["declaration"]["content_sha256"]
    assert validate(right)["declaration"] == right["declaration"]
    for result in (assess(left), assess(right)):
        assert_diagnostic(result)
        assert not {"equivalent", "non_equivalent", "negative_pair", "positive_pair"}.intersection(result)


@pytest.mark.parametrize("variant", ["conditions_any", "exceptions_all", "nested", "negation"])
def test_supported_rich_connectives_remain_distinct_and_unavailable_for_flat_lowering(variant):
    value = scope_case()
    qualifiers = value["declaration"]["rules"][0]["qualifiers"]
    if variant == "conditions_any":
        qualifiers["conditions"]["op"] = "any"
    elif variant == "exceptions_all":
        qualifiers["exceptions"]["op"] = "all"
    elif variant == "nested":
        qualifiers["conditions"] = connective("all", [leaf("q1"), connective("any", [leaf("q2"), leaf("q3")])])
    else:
        qualifiers["temporal"] = {"op": "not", "child": leaf("t"), "operator_anchor": None}
    seal(value["declaration"])
    assert validate(value)["declaration"] == value["declaration"]
    result = assess(value)
    assert "qualifier_operator_or_nesting_not_flat_profile" in codes(result)
    assert all(profile["status"] == "unavailable" for profile in result["profiles"].values())
    assert result["byte_encoding_capacity"]["checked"] is False
    assert_diagnostic(result)


@pytest.mark.parametrize("variant", ["all", "any", "nested", "shared"])
def test_rule_order_and_local_or_shared_attachment_are_preserved(variant):
    value = two_rule_case()
    declaration = value["declaration"]
    if variant == "any":
        declaration["statement_structure"]["op"] = "any"
    elif variant == "nested":
        declaration["statement_structure"] = connective("all", [connective("any", [rule_leaf("r1"), rule_leaf("r2")])])
    elif variant == "shared":
        conditions = declaration["rules"][0]["qualifiers"]["conditions"]
        declaration["rules"][0]["qualifiers"]["conditions"] = None
        declaration["statement_structure"] = {"op": "attach", "body": declaration["statement_structure"],
                                              "qualifiers": {"conditions": conditions, "exceptions": None, "temporal": None}}
    seal(declaration)
    assert validate(value)["declaration"] == declaration
    result = assess(value)
    assert "byte_profile_requires_exactly_one_rule" in codes(result)
    if variant == "all":
        assert "legacy_rule_or_qualifier_order_changes" in codes(result)
        assert result["profiles"]["canonical_roundtrip_ir_v1"]["status"] == "normalization_required_unapproved"
    else:
        assert "nonflat_statement_connective_or_shared_attachment" in codes(result)
    assert_diagnostic(result)


def test_statement_leaf_order_difference_is_reported_without_rewriting_rules():
    value = two_rule_case()
    value["declaration"]["statement_structure"]["children"].reverse()
    seal(value["declaration"])
    validate(value)
    assert "statement_and_occurrence_rule_order_differ" in codes(assess(value))
    assert [rule["rule_id"] for rule in value["declaration"]["rules"]] == ["r1", "r2"]


def test_reusing_one_physical_mention_is_distinguished_from_two_literal_occurrences():
    value = scope_case(repeated=False)
    value["declaration"]["rules"][0]["qualifiers"]["conditions"] = connective("all", [leaf("q1"), leaf("q1")])
    seal(value["declaration"])
    validate(value)
    result = assess(value)
    assert "byte_anchors_overlap_or_share_a_mention" in codes(result)
    assert result["profiles"]["byte_proposal_v1"]["status"] == "unavailable"
    assert_diagnostic(result)


@pytest.mark.parametrize("scope_path", ["/rules/0", "/statement_structure"])
def test_binder_domains_and_scope_are_retained_but_not_typed_or_flattened(scope_path):
    value = scope_case(repeated=False)
    add_binder(value, scope_path=scope_path)
    result = validate(value)
    assert result["binder_count"] == 1
    assert result["declaration"]["binders"] == value["declaration"]["binders"]
    assessment = assess(value)
    assert "binders_domains_and_attachment_not_in_flat_facets" in codes(assessment)
    assert all(profile["status"] == "unavailable" for profile in assessment["profiles"].values())
    assert_diagnostic(result)
    assert_diagnostic(assessment)


@pytest.mark.parametrize("fault", ["escape", "unknown_path", "wrong_domain", "duplicate_association", "duplicate_id", "quantifier"])
def test_invalid_binder_association_is_rejected_without_claiming_term_typing(fault):
    value = scope_case(repeated=False)
    add_binder(value)
    binder = value["declaration"]["binders"][0]
    if fault == "escape":
        binder["scope_path"] = "/rules/0/qualifiers/conditions"
    elif fault == "unknown_path":
        binder["scope_path"] = "/rules/99"
    elif fault == "wrong_domain":
        binder["domain_occurrence"] = "q1"
    elif fault in {"duplicate_association", "duplicate_id"}:
        second = copy.deepcopy(binder)
        if fault == "duplicate_association":
            second["binder_id"] = "binder2"
        value["declaration"]["binders"].append(second)
    else:
        binder["quantifier"] = "verified_forall"
    seal(value["declaration"])
    with pytest.raises(ValueError):
        validate(value)


@pytest.mark.parametrize("scope_path", ["/rules/0", "/statement_structure/children/0"])
def test_bound_occurrence_reused_in_another_rule_escapes_both_rule_and_statement_scope(scope_path):
    value = two_rule_case()
    value["declaration"]["rules"][1]["qualifiers"]["conditions"] = leaf("q1")
    add_binder(value, scope_path=scope_path, bound=("q1",))
    with pytest.raises(ValueError, match="outside.*scope"):
        validate(value)


def test_bound_occurrence_reused_in_another_child_cannot_hide_behind_set_membership():
    value = scope_case(repeated=False)
    value["declaration"]["rules"][0]["qualifiers"]["conditions"] = connective("all", [leaf("q1"), leaf("q1")])
    add_binder(value, scope_path="/rules/0/qualifiers/conditions/children/0", bound=("q1",))
    with pytest.raises(ValueError, match="outside.*scope"):
        validate(value)


def test_equal_declared_variable_names_do_not_assert_capture_or_alpha_equivalence():
    value = scope_case(repeated=False)
    add_binder(value)
    second = copy.deepcopy(value["declaration"]["binders"][0])
    second.update(binder_id="binder2", quantifier="exists", bound_occurrence_ids=["q1"])
    value["declaration"]["binders"].append(second)
    seal(value["declaration"])
    result = validate(value)
    assert result["binder_count"] == 2
    assert_diagnostic(result)
    assert_diagnostic(assess(value))


@pytest.mark.parametrize("fault", ["prefix_gap", "suffix_gap", "unsupported", "unresolved", "required_context"])
def test_complete_literal_coverage_cannot_hide_gaps_or_unavailable_meaning(fault):
    value = scope_case(repeated=False)
    segment = value["declaration"]["coverage"]["segments"][0]
    if fault == "prefix_gap":
        segment["span"] = span(value["request"]["source_text"], 1)
    elif fault == "suffix_gap":
        segment["span"] = span(value["request"]["source_text"], end=len(value["request"]["source_text"]) - 1)
    elif fault == "unsupported":
        segment["disposition"] = "unsupported"
    elif fault == "unresolved":
        value["declaration"]["unresolved"] = [{"code": "attachment_unknown", "span": copy.deepcopy(segment["span"]),
                                              "reason": "Synthetic unresolved scope"}]
    else:
        value["request"]["context"]["role"] = "required_unavailable"
        refresh_input(value)
    seal(value["declaration"])
    with pytest.raises(ValueError):
        validate(value)


@pytest.mark.parametrize("status", ["partial", "unassessed"])
def test_gaps_and_unresolved_meaning_are_explicit_and_never_qualified(status):
    value = scope_case(repeated=False)
    value["declaration"]["coverage"].update(declared_status=status, segments=[])
    value["declaration"]["unresolved"] = [{"code": "synthetic_gap", "span": span(value["request"]["source_text"]),
                                          "reason": "Unreviewed coverage gap"}]
    seal(value["declaration"])
    assert validate(value)["declared_coverage_status"] == status
    result = assess(value)
    assert "source_coverage_partial_unassessed_or_unresolved" in codes(result)
    assert all(profile["status"] == "unavailable" for profile in result["profiles"].values())
    assert_diagnostic(result)


@pytest.mark.parametrize("fault", ["outside", "wrong_origin", "no_reference"])
def test_coverage_references_require_physical_containment_and_a_represented_association(fault):
    value = scope_case(repeated=False, context_text="É📄 evidence from a separate context.")
    source_segment = value["declaration"]["coverage"]["segments"][0]
    if fault == "outside":
        source_segment["span"] = span(value["request"]["source_text"], 0, 2)
    elif fault == "wrong_origin":
        source_segment["span"] = span(value["request"]["context"]["text"], origin="context")
    else:
        source_segment["rule_ids"] = []
        source_segment["occurrence_ids"] = []
    seal(value["declaration"])
    with pytest.raises(ValueError, match="outside|represented"):
        validate(value)


def test_supplied_context_spans_use_their_exact_origin_and_stay_unresolved():
    value = scope_case(repeated=False, context_text="É📄 evidence means the contextual filing.")
    row = next(row for row in value["declaration"]["occurrences"] if row["occurrence_id"] == "object")
    row["anchor"] = literal_span(value["request"]["context"]["text"], "evidence", origin="context")
    cover_all(value)
    seal(value["declaration"])
    result = validate(value)
    assert result["declaration"]["occurrences"][3]["anchor"]["origin"] == "context"
    assert result["context_resolved"] is False
    assessment = assess(value)
    assert {"context_has_no_qualified_flat_transport", "byte_anchors_require_direct_source"} <= codes(assessment)
    assert_diagnostic(result)
    assert_diagnostic(assessment)


def test_complete_source_coverage_cannot_omit_declared_context_characters():
    value = scope_case(repeated=False, context_text="Additional context.")
    value["declaration"]["coverage"]["segments"].pop()
    seal(value["declaration"])
    with pytest.raises(ValueError, match="omits.*characters"):
        validate(value)


@pytest.mark.parametrize("fault", ["start_bool", "end_float", "unit", "origin", "literal", "empty", "beyond", "byte_index"])
def test_resealed_span_mutations_cannot_replace_exact_unicode_occurrences(fault):
    value = scope_case(repeated=False)
    anchor = value["declaration"]["occurrences"][0]["anchor"]
    if fault == "start_bool":
        anchor["start"] = True
    elif fault == "end_float":
        anchor["end"] = float(anchor["end"])
    elif fault == "unit":
        anchor["offset_unit"] = "utf8_byte_half_open"
    elif fault == "origin":
        anchor["origin"] = "context"
    elif fault == "literal":
        anchor["text"] = anchor["text"].upper()
    elif fault == "empty":
        anchor["end"] = anchor["start"]
    elif fault == "beyond":
        anchor["end"] = 10000
    else:
        anchor["start"] = len(value["request"]["source_text"][:anchor["start"]].encode("utf-8"))
    seal(value["declaration"])
    with pytest.raises(ValueError):
        validate(value)


@pytest.mark.parametrize("fault", ["checksum", "input_pin", "embedded_input", "context_digest", "family", "profile"])
def test_payload_seal_and_external_input_identity_are_independent_boundaries(fault):
    value = scope_case(repeated=False)
    if fault == "checksum":
        value["declaration"]["content_sha256"] = "0" * 64
    elif fault == "input_pin":
        value["expected_input_sha256"] = "0" * 64
    elif fault == "embedded_input":
        value["declaration"]["input"]["source_text"] += " changed"
        seal(value["declaration"])
    elif fault == "context_digest":
        value["request"]["context"]["sha256"] = "0" * 64
        refresh = digest(value["request"])
        value["expected_input_sha256"] = refresh
        value["declaration"]["input"] = copy.deepcopy(value["request"])
        value["declaration"]["input_sha256"] = refresh
        seal(value["declaration"])
    else:
        value["declaration"][fault] = "caller-approved-general-profile"
        seal(value["declaration"])
    with pytest.raises(ValueError):
        validate(value)


def test_self_bound_assessment_is_not_external_source_authentication():
    value = scope_case(repeated=False)
    previous_pin = value["expected_input_sha256"]
    value["request"]["source_text"] = value["request"]["source_text"].replace("É", "Å", 1)
    refresh_input(value)
    cover_all(value)
    seal(value["declaration"])
    assert assess(value)["input_pin_scope"] == "embedded_input_self_binding_only"
    with pytest.raises(ValueError, match="externally expected"):
        subject.validate_scope_declaration(value["request"], value["declaration"], expected_input_sha256=previous_pin)


@pytest.mark.parametrize("fault", ["duplicate_occurrence", "unknown_ref", "wrong_facet", "orphan", "duplicate_rule",
                                   "unknown_rule", "reused_rule", "empty_connective", "absent_child", "unknown_op"])
def test_reference_graph_rejects_dangling_duplicate_or_unattached_records(fault):
    value = scope_case()
    declaration = value["declaration"]
    if fault == "duplicate_occurrence":
        declaration["occurrences"].append(copy.deepcopy(declaration["occurrences"][0]))
    elif fault == "unknown_ref":
        declaration["rules"][0]["body"]["actor"] = "unknown"
    elif fault == "wrong_facet":
        declaration["rules"][0]["body"]["actor"] = "q1"
    elif fault == "orphan":
        row = copy.deepcopy(declaration["occurrences"][0])
        row["occurrence_id"] = "orphan"
        declaration["occurrences"].append(row)
    elif fault == "duplicate_rule":
        declaration["rules"].append(copy.deepcopy(declaration["rules"][0]))
    elif fault == "unknown_rule":
        declaration["statement_structure"]["rule_id"] = "unknown"
    elif fault == "reused_rule":
        declaration["statement_structure"] = connective("all", [rule_leaf("r1"), rule_leaf("r1")])
    elif fault == "empty_connective":
        declaration["rules"][0]["qualifiers"]["conditions"]["children"] = []
    elif fault == "absent_child":
        declaration["rules"][0]["qualifiers"]["conditions"]["children"][0] = None
    else:
        declaration["rules"][0]["qualifiers"]["conditions"]["op"] = "implies"
    seal(declaration)
    with pytest.raises(ValueError):
        validate(value)


@pytest.mark.parametrize("where", ["declaration", "input", "context", "occurrence", "anchor", "rule", "body",
                                   "qualifiers", "expression", "coverage", "segment", "binder", "unresolved"])
def test_closed_schema_rejects_caller_authority_at_every_nesting_level(where):
    value = scope_case(repeated=False)
    add_binder(value)
    declaration = value["declaration"]
    declaration["coverage"]["declared_status"] = "partial"
    declaration["unresolved"] = [{"code": "synthetic", "span": span(value["request"]["source_text"]), "reason": "Unverified"}]
    targets = {"declaration": declaration, "input": declaration["input"], "context": declaration["input"]["context"],
               "occurrence": declaration["occurrences"][0], "anchor": declaration["occurrences"][0]["anchor"],
               "rule": declaration["rules"][0], "body": declaration["rules"][0]["body"],
               "qualifiers": declaration["rules"][0]["qualifiers"],
               "expression": declaration["rules"][0]["qualifiers"]["conditions"],
               "coverage": declaration["coverage"], "segment": declaration["coverage"]["segments"][0],
               "binder": declaration["binders"][0], "unresolved": declaration["unresolved"][0]}
    targets[where]["semantic_verified"] = True
    seal(declaration)
    with pytest.raises(ValueError):
        validate(value)


def test_exact_anchor_transport_does_not_check_canonical_symbol_meaning():
    value = scope_case(repeated=False)
    value["declaration"]["occurrences"][0]["canonical_symbol"] = "synthetic_wrong_actor"
    seal(value["declaration"])
    assert_diagnostic(validate(value))
    assert_diagnostic(assess(value))


def test_flat_facets_fit_only_with_sidecar_and_no_semantic_or_encoding_qualification():
    value = scope_case(repeated=False)
    result = assess(value)
    assert all(profile["status"] == "flat_facets_fit_with_scope_sidecar" for profile in result["profiles"].values())
    assert result["byte_encoding_capacity"]["checked"] is True
    assert result["byte_encoding_capacity"]["required_token_count"] > 3
    assert_diagnostic(result)


def test_complete_byte_capacity_includes_both_framing_tokens_at_exact_boundary():
    value = scope_case(repeated=False)
    initial = assess(value)
    required = initial["byte_encoding_capacity"]["required_token_count"]
    assert required == initial["byte_encoding_capacity"]["payload_bytes"] + 2
    exact = assess(value, byte_output_cap=required)
    below = assess(value, byte_output_cap=required - 1)
    tiny = assess(value, byte_output_cap=3)
    assert exact["profiles"]["byte_proposal_v1"]["status"] == "flat_facets_fit_with_scope_sidecar"
    for result in (below, tiny):
        assert "byte_complete_wire_exceeds_output_cap" in codes(result)
        assert result["byte_encoding_capacity"]["checked"] is True
        assert result["profiles"]["byte_proposal_v1"]["status"] == "unavailable"
        assert result["profiles"]["canonical_roundtrip_ir_v1"]["status"] == "flat_facets_fit_with_scope_sidecar"
        assert_diagnostic(result)


@pytest.mark.parametrize("cap", [True, False, None, 3.0, 2, 32771])
def test_byte_output_capacity_is_a_bounded_exact_integer(cap):
    with pytest.raises(ValueError, match="byte_output_cap"):
        assess(scope_case(repeated=False), byte_output_cap=cap)


def test_valid_scope_payload_can_exceed_the_unchanged_byte_wire_hard_limit():
    value = scope_case(repeated=False)
    declaration = value["declaration"]
    declaration["occurrences"] = [row for row in declaration["occurrences"] if row["facet"] != "conditions"]
    literals = [f"q{index:02d}" for index in range(64)]
    value["request"]["source_text"] += " " + " ".join(literals)
    source = value["request"]["source_text"]
    for index, literal in enumerate(literals):
        declaration["occurrences"].append(occurrence(f"long{index}", "conditions", f"s{index:02d}" + "v" * 509, source, literal))
    declaration["rules"][0]["qualifiers"]["conditions"] = connective("all", [leaf(f"long{index}") for index in range(64)])
    refresh_input(value)
    cover_all(value)
    seal(declaration)
    assert len(raw(declaration)) < subject.MAX_BYTES
    assert validate(value)["occurrence_count"] == 71
    result = assess(value, byte_output_cap=32770)
    assert "legacy_byte_owner_rejected_encoding_limits" in codes(result)
    assert result["profiles"]["byte_proposal_v1"]["status"] == "unavailable"
    assert result["byte_encoding_capacity"]["checked"] is False
    assert_diagnostic(result)


@pytest.mark.parametrize("fault", ["depth", "expression_nodes", "rules", "occurrences", "payload_bytes"])
def test_transport_bounds_reject_without_truncating(fault):
    value = scope_case(repeated=False)
    declaration = value["declaration"]
    if fault == "depth":
        node = leaf("q1")
        for _ in range(subject.MAX_EXPRESSION_DEPTH + 1):
            node = {"op": "not", "child": node, "operator_anchor": None}
        declaration["rules"][0]["qualifiers"]["conditions"] = node
    elif fault == "expression_nodes":
        groups = [connective("all", [leaf("q1") for _ in range(128)]) for _ in range(9)]
        declaration["rules"][0]["qualifiers"]["conditions"] = connective("all", groups)
    elif fault == "rules":
        declaration["rules"] *= subject.MAX_RULES + 1
    elif fault == "occurrences":
        declaration["occurrences"] *= subject.MAX_OCCURRENCES + 1
    else:
        declaration["occurrences"][0]["canonical_symbol"] = "x" * subject.MAX_BYTES
    seal(declaration)
    before = copy.deepcopy(value)
    with pytest.raises(ValueError):
        validate(value)
    assert value == before


@pytest.mark.parametrize("poison", [float("nan"), float("inf"), object(), "\ud800"])
def test_nonordinary_or_non_utf8_values_are_rejected_before_assessment(poison):
    value = scope_case(repeated=False)
    value["declaration"]["occurrences"][0]["canonical_symbol"] = poison
    with pytest.raises(ValueError):
        validate(value)
    with pytest.raises(ValueError):
        assess(value)


def test_validation_and_assessment_are_detached_repeatable_and_explicitly_sealed():
    value = scope_case()
    before = copy.deepcopy(value)
    validation = validate(value)
    assessment = assess(value)
    assert validation == validate(value) and assessment == assess(value)
    assert validation["content_sha256"] == digest({key: entry for key, entry in validation.items()
                                                if key not in {"declaration", "content_sha256"}})
    assert assessment["content_sha256"] == digest({key: entry for key, entry in assessment.items() if key != "content_sha256"})
    validation["declaration"]["occurrences"][0]["anchor"]["text"] = "mutation"
    assessment["profiles"]["byte_proposal_v1"]["issues"].append({"mutation": True})
    assert value == before
    assert validate(value)["declaration"] == before["declaration"]


def test_nonflat_qualifiers_do_not_create_fabricated_flat_values_or_trigger_byte_encoding(monkeypatch):
    from ipfs_datasets_py.logic.legal_ir import canonical_byte_codec, canonical_contracts

    value = scope_case()
    value["declaration"]["rules"][0]["qualifiers"]["conditions"]["op"] = "any"
    seal(value["declaration"])

    def unexpected(*args, **kwargs):
        pytest.fail("nonflat qualifier was fabricated into a legacy candidate")

    monkeypatch.setattr(canonical_contracts.CanonicalRoundTripIR, "from_dict", unexpected)
    monkeypatch.setattr(canonical_byte_codec, "inspect_encoding", unexpected)
    assert_diagnostic(assess(value))


def test_transport_and_capacity_assessment_do_not_import_or_execute_models_or_provers(monkeypatch):
    value = scope_case(repeated=False)
    assess(value)  # Load the pure transport owners before observing imports.
    original_import = builtins.__import__
    forbidden = {"torch", "numpy", "spacy", "transformers", "sentence_transformers", "openai", "requests", "httpx", "z3", "cvc5"}

    def guarded(name, *args, **kwargs):
        assert name.split(".")[0] not in forbidden, name
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded)
    assert_diagnostic(validate(value))
    assert_diagnostic(assess(value))
