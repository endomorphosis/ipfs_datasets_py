"""Authored geometry controls; these fixtures are not statutory reference gold."""
from __future__ import annotations

import copy
import hashlib
import json

import pytest

from ipfs_datasets_py.logic.legal_ir import canonical_statement_scope as scope
from ipfs_datasets_py.logic.legal_ir import temporal_bindings as subject


def raw(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def seal(declaration):
    declaration["content_sha256"] = subject.digest({k: v for k, v in declaration.items() if k != "content_sha256"})
    return declaration


def geometry(anchor, request):
    text = request["source_text"] if anchor["origin"] == "source" else request["context"]["text"]
    return dict(origin=anchor["origin"], source_sha256=sha(text), char_start=anchor["start"], char_end=anchor["end"],
                utf8_start=len(text[:anchor["start"]].encode("utf-8")), utf8_end=len(text[:anchor["end"]].encode("utf-8")),
                text=anchor["text"])


def fixture_binding(*, literal="within 7 days", condition="paid", exception="sealed", temporal=True,
                    actor="Clérk e\u0301", object_text="filing", context="", modality="O"):
    """Six original inputs plus external pins, suitable for consumer fixtures.

    Mapping/formula digests are inert placeholders. A native consumer fixture
    must replace the entire interpretation with its current-owner skeleton,
    fill the same choices, and regenerate pins before invoking a native owner.
    """
    cue = {"O": "must", "P": "may", "F": "must not"}[modality]
    text, anchors = "", {}

    def add(value, field=None):
        nonlocal text
        start = len(text)
        text += value
        if field is not None:
            anchors[field] = dict(origin="source", start=start, end=len(text), text=value,
                                  offset_unit="unicode_character_half_open")

    add(actor, "actor")
    add(" ")
    add(cue, "modality")
    add(" ")
    add("retain", "action")
    add(" ")
    add(object_text, "object")
    if condition is not None:
        add(" if ")
        add(condition, "conditions")
    if exception is not None:
        add(" except ")
        add(exception, "exceptions")
    if temporal:
        add(" ")
        add(literal, "temporal")
    add(".")
    request = dict(source_text=text, context=dict(role="declared_context" if context else "none_required",
        text=context, bindings={}, sha256=sha(context)))
    symbols = dict(actor="clerk", modality=modality, action="retain", object="filing",
                   conditions=condition, exceptions=exception, temporal=literal)
    occurrences = [dict(occurrence_id=field + "-1", facet=field, canonical_symbol=symbols[field], anchor=anchor)
                   for field, anchor in anchors.items()]
    qualifiers = {field: dict(op="leaf", occurrence_id=field + "-1") if field in anchors else None
                  for field in scope.QUALIFIERS}
    coverage = [dict(span=dict(origin="source", start=0, end=len(text), text=text,
                             offset_unit="unicode_character_half_open"), disposition="represented", rule_ids=["rule-1"],
                     occurrence_ids=[item["occurrence_id"] for item in occurrences], reason="Authored literal custody only.")]
    if context:
        coverage.append(dict(span=dict(origin="context", start=0, end=len(context), text=context,
                                        offset_unit="unicode_character_half_open"), disposition="represented",
                             rule_ids=["rule-1"], occurrence_ids=[], reason="Authored complete context custody only."))
    declaration = seal(dict(schema=scope.SCHEMA, family="deontic", profile=scope.PROFILE, input=copy.deepcopy(request),
        input_sha256=subject.digest(request), occurrences=occurrences,
        rules=[dict(rule_id="rule-1", body={field: field + "-1" for field in scope.CORE}, qualifiers=qualifiers)],
        statement_structure=dict(op="rule", rule_id="rule-1"), binders=[],
        coverage=dict(declared_status="complete", segments=coverage), unresolved=[]))
    rule = {field: symbols[field] for field in scope.CORE}
    rule.update({field: [symbols[field]] if field in anchors else [] for field in scope.QUALIFIERS})
    candidate = dict(candidate_id="authored-control-1", source_text=text, source_sha256=sha(text), canonical_ir=dict(rules=[rule]))
    kind = "within_duration" if literal.startswith("within ") else "minimum_duration"
    words = literal.split()
    quantity = int(words[1] if kind == "within_duration" else words[3])
    choices = dict(temporal_kind=kind, quantity=quantity, unit=words[-1].rstrip("s"), time_domain="discrete_nat",
                   origin="caller_supplied_evaluation_time", lower_inclusive=True, upper_inclusive=True)
    formula = dict(formula_index=0, original_formula_sha256="a" * 64, kind="activation_guarded_legal_rule",
        activation_scope="all_conditions_at_evaluation_origin",
        conditions=[] if condition is None else [dict(source_index=0, source_text=condition, expression=dict(kind="atom", name="paid"))],
        temporal=dict(source_index=len(rule["conditions"]), source_text=literal, **choices) if temporal else None,
        exception_scope="any_exception_at_evaluation_origin", exceptions=[] if exception is None else
        [dict(source_index=0, source_text=exception, expression=dict(kind="atom", name="sealed"))])
    interpretation = dict(schema=subject.INTERPRETATION_SCHEMA, candidate_id=candidate["candidate_id"],
        candidate_sha256=subject.digest(candidate), source_sha256=candidate["source_sha256"],
        canonical_ir_sha256=subject.digest(candidate["canonical_ir"]), mapping_sha256="b" * 64,
        declaration_scope=subject.DECLARATION_SCOPE, formulas=[formula])
    bindings = [dict(rule_index=0, temporal_index=0, scope_rule_id="rule-1", scope_leaf_path="/rules/0/qualifiers/temporal",
        occurrence_id="temporal-1", duration_anchor=geometry(anchors["temporal"], request), clock_id="clock-1")] if temporal else []
    clocks = [dict(clock_id="clock-1", declaration_id="declaration-1", declaration_scope=subject.DECLARATION_SCOPE,
        scope_rule_id="rule-1", anchor=geometry(anchors["modality"], request), **choices)] if temporal else []
    args = [candidate, interpretation, request, declaration, bindings, clocks]
    return args, pins(args)


def pins(args):
    return dict(expected_candidate_sha256=subject.digest(args[0]), expected_interpretation_sha256=subject.digest(args[1]),
                expected_scope_input_sha256=subject.digest(args[2]), expected_scope_declaration_sha256=subject.digest(args[3]))


def prepare(args, expected=None):
    return subject.prepare_duration_bindings(*args, **(pins(args) if expected is None else expected))


def test_complete_exact_occurrence_join_preserves_every_input_and_pending_authority():
    args, expected = fixture_binding()
    before = copy.deepcopy(args)
    report = prepare(args, expected)
    assert args == before
    assert report["candidate"] == args[0] and report["interpretation"] == args[1]
    assert report["scope_request"] == args[2] and report["scope_declaration"] == args[3]
    assert report["occurrence_bindings"] == args[4] and report["clock_declarations"] == args[5]
    assert report["duration_count"] == report["rule_count"] == 1
    assert report["joins"][0]["occurrence_id"] == "temporal-1"
    assert report["joins"][0]["declared_clock"]["quantity"] == 7
    assert report["geometry_units"] == dict(characters="unicode_character_half_open", bytes="UTF8_byte_half_open")
    assert report["native_interpretation_validated"] is False
    assert report["statutory_custody"] == "separate_owner_not_assessed"
    assert all(report[field] is False for field in subject.FALSE)
    assert all(type(value) is int and value == 0 for value in report["masks"].values())
    assert report["model_calls"] == report["prover_calls"] == 0
    assert report["content_sha256"] == subject.digest({k: v for k, v in report.items() if k != "content_sha256"})
    validated = subject.validate_duration_bindings(report, *args, **expected)
    assert validated["report_sha256"] == subject.digest(report)
    assert all(validated[field] is False for field in subject.FALSE)


@pytest.mark.parametrize("literal", ["within 1 day", "within 1201 days", "within 2 hours", "for at least 1 hour", "for at least 1000000 days"])
@pytest.mark.parametrize("modality", ["O", "P", "F"])
def test_existing_plain_duration_surface_and_modalities_are_custodied_only(literal, modality):
    args, expected = fixture_binding(literal=literal, modality=modality)
    assert prepare(args, expected)["joins"][0]["temporal_literal"] == literal


def test_identical_condition_exception_and_temporal_literals_retain_distinct_occurrences():
    args, expected = fixture_binding(condition="within 7 days", exception="within 7 days")
    report = prepare(args, expected)
    assert report["duration_count"] == 1
    duration = report["joins"][0]["duration_anchor"]
    occurrences = {item["facet"]: item["anchor"] for item in args[3]["occurrences"]}
    assert occurrences["conditions"]["text"] == occurrences["exceptions"]["text"] == duration["text"]
    assert occurrences["conditions"]["start"] < occurrences["exceptions"]["start"] < duration["char_start"]


@pytest.mark.parametrize("facet", ["actor", "object", "conditions", "exceptions"])
def test_duration_looking_non_temporal_roles_do_not_create_a_normative_deadline(facet):
    options = dict(temporal=False)
    options[{"actor": "actor", "object": "object_text", "conditions": "condition", "exceptions": "exception"}[facet]] = "within 7 days"
    args, expected = fixture_binding(**options)
    report = prepare(args, expected)
    assert report["duration_count"] == 0 and report["joins"] == []
    assert report["clock_declarations"] == []


@pytest.mark.parametrize("facet", ["actor", "object", "conditions", "exceptions"])
def test_a_duration_map_cannot_exchange_an_identical_literal_from_another_facet(facet):
    options = {{"actor": "actor", "object": "object_text", "conditions": "condition", "exceptions": "exception"}[facet]: "within 7 days"}
    args, _ = fixture_binding(**options)
    occurrence = next(item for item in args[3]["occurrences"] if item["facet"] == facet)
    args[4][0]["duration_anchor"] = geometry(occurrence["anchor"], args[2])
    with pytest.raises(ValueError, match="mapped scope occurrence differs"):
        prepare(args)
    args[4][0]["occurrence_id"] = occurrence["occurrence_id"]
    with pytest.raises(ValueError, match="actual temporal rule/facet/leaf/occurrence"):
        prepare(args)


def test_unicode_character_and_utf8_geometry_are_independent_and_not_normalized():
    args, _ = fixture_binding()
    anchor = args[4][0]["duration_anchor"]
    assert anchor["utf8_start"] > anchor["char_start"]
    assert "e\u0301" in args[0]["source_text"]
    anchor["utf8_start"] = anchor["char_start"]
    with pytest.raises(ValueError, match="UTF8 geometry"):
        prepare(args)


@pytest.mark.parametrize("field", ["char_start", "char_end", "utf8_start", "utf8_end"])
@pytest.mark.parametrize("container", ["duration", "clock"])
def test_bool_geometry_is_refused_even_when_json_is_resigned(field, container):
    args, _ = fixture_binding()
    anchor = args[4][0]["duration_anchor"] if container == "duration" else args[5][0]["anchor"]
    anchor[field] = True
    with pytest.raises(ValueError, match="integer"):
        prepare(args)


@pytest.mark.parametrize("field,value", [("quantity", True), ("quantity", 7.0), ("lower_inclusive", 1), ("upper_inclusive", 1)])
def test_resigned_interpretation_cannot_exploit_bool_integer_or_float_equality(field, value):
    args, _ = fixture_binding(literal="within 1 day" if field == "quantity" else "within 7 days")
    args[1]["formulas"][0]["temporal"][field] = value
    with pytest.raises(ValueError, match="independent clock differs|integer-only"):
        prepare(args)


@pytest.mark.parametrize("field,value", [("quantity", True), ("quantity", 0), ("quantity", 1000001), ("unit", "business_day"),
    ("unit", "month"), ("temporal_kind", "calendar_date"), ("origin", "enactment_time"),
    ("origin", "event_occurrence"), ("origin", None), ("time_domain", "real"), ("lower_inclusive", False), ("upper_inclusive", 1)])
def test_unsupported_or_unspecified_clock_choices_never_default(field, value):
    args, _ = fixture_binding()
    args[5][0][field] = value
    with pytest.raises(ValueError, match="clock|duration"):
        prepare(args)


@pytest.mark.parametrize("field", ["rule_index", "temporal_index"])
def test_bool_rule_indices_are_not_accepted(field):
    args, _ = fixture_binding()
    args[4][0][field] = False
    with pytest.raises(ValueError, match="integer"):
        prepare(args)


@pytest.mark.parametrize("index", [4, 5])
@pytest.mark.parametrize("operation", ["missing", "duplicate", "extra"])
def test_partial_extra_or_duplicated_map_and_clock_inventories_refuse(index, operation):
    args, _ = fixture_binding()
    if operation == "missing":
        args[index].clear()
    else:
        extra = copy.deepcopy(args[index][0])
        if operation == "extra":
            extra["clock_id"] = "extra-clock"
        args[index].append(extra)
    with pytest.raises(ValueError, match="complete"):
        prepare(args)


@pytest.mark.parametrize("field,value", [("scope_rule_id", "wrong"), ("scope_leaf_path", "/rules/0/qualifiers/conditions"),
    ("occurrence_id", "conditions-1"), ("clock_id", "missing"), ("rule_index", 1), ("temporal_index", 1)])
def test_actual_role_leaf_and_clock_identity_are_required(field, value):
    args, _ = fixture_binding()
    args[4][0][field] = value
    with pytest.raises(ValueError, match="binding differs|clock reference"):
        prepare(args)


@pytest.mark.parametrize("index", [0, 1, 2, 3])
def test_external_content_pins_cannot_be_replaced_by_self_seals(index):
    args, expected = fixture_binding()
    key = list(expected)[index]
    expected[key] = "0" * 64
    with pytest.raises(ValueError, match="externally expected"):
        prepare(args, expected)


def test_clock_origin_context_geometry_and_sha_custody_are_explicit_only():
    args, _ = fixture_binding(context="Légal é audit clock begins here.")
    text = args[2]["context"]["text"]
    start = text.index("audit")
    args[5][0]["anchor"] = geometry(dict(origin="context", start=start, end=start + len("audit clock"), text="audit clock"), args[2])
    report = prepare(args)
    assert report["joins"][0]["clock_anchor"]["origin"] == "context"
    assert report["temporal_origin_resolved"] is False
    args[5][0]["anchor"]["origin"] = "source"
    with pytest.raises(ValueError, match="source SHA"):
        prepare(args)


def test_clock_source_identity_mismatch_is_not_repaired():
    args, _ = fixture_binding()
    args[5][0]["anchor"]["source_sha256"] = "c" * 64
    with pytest.raises(ValueError, match="source SHA"):
        prepare(args)


def test_non_duration_fragments_and_dates_refuse_clock_transport():
    for fragment in ("civilian law enforcement official under this", "weapon of", "on 2026-10-12"):
        args, _ = fixture_binding()
        occurrence = next(item for item in args[3]["occurrences"] if item["facet"] == "temporal")
        occurrence["canonical_symbol"] = fragment
        args[0]["canonical_ir"]["rules"][0]["temporal"] = [fragment]
        args[1]["candidate_sha256"] = subject.digest(args[0])
        args[1]["canonical_ir_sha256"] = subject.digest(args[0]["canonical_ir"])
        args[1]["formulas"][0]["temporal"]["source_text"] = fragment
        seal(args[3])
        with pytest.raises(ValueError, match="temporal literal differs"):
            prepare(args)


@pytest.mark.parametrize("literal", ["civilian law enforcement official under this", "weapon of", "on 2026-10-12", "within 7 business days", "within 2 months"])
def test_exact_source_custodied_fragments_and_calendar_surfaces_are_not_plain_durations(literal):
    args, _ = fixture_binding()
    occurrence = next(item for item in args[3]["occurrences"] if item["facet"] == "temporal")
    start, end = occurrence["anchor"]["start"], occurrence["anchor"]["end"]
    old = args[2]["source_text"]
    text = old[:start] + literal + old[end:]
    args[2]["source_text"] = text
    occurrence["canonical_symbol"] = literal
    occurrence["anchor"].update(end=start + len(literal), text=literal)
    args[3]["input"] = copy.deepcopy(args[2])
    args[3]["input_sha256"] = subject.digest(args[2])
    args[3]["coverage"]["segments"][0]["span"].update(end=len(text), text=text)
    seal(args[3])
    args[0].update(source_text=text, source_sha256=sha(text))
    args[0]["canonical_ir"]["rules"][0]["temporal"] = [literal]
    args[1].update(candidate_sha256=subject.digest(args[0]), source_sha256=sha(text), canonical_ir_sha256=subject.digest(args[0]["canonical_ir"]))
    args[1]["formulas"][0]["temporal"]["source_text"] = literal
    args[4][0]["duration_anchor"] = geometry(occurrence["anchor"], args[2])
    args[5][0]["anchor"]["source_sha256"] = sha(text)
    with pytest.raises(ValueError, match="clock owner or explicit kind/quantity/unit"):
        prepare(args)


def test_resealed_scope_and_model_candidate_cannot_claim_a_duration_inside_an_actor():
    args, _ = fixture_binding(actor="the within 7 days board")
    actor = next(item for item in args[3]["occurrences"] if item["facet"] == "actor")["anchor"]
    start = actor["start"] + len("the ")
    occurrence = next(item for item in args[3]["occurrences"] if item["facet"] == "temporal")
    occurrence["anchor"] = dict(origin="source", start=start, end=start + len("within 7 days"), text="within 7 days",
                                offset_unit="unicode_character_half_open")
    args[4][0]["duration_anchor"] = geometry(occurrence["anchor"], args[2])
    seal(args[3])
    with pytest.raises(ValueError, match="non-temporal role"):
        prepare(args)


@pytest.mark.parametrize("change", ["statement_shared", "nested_temporal", "partial_coverage", "unavailable_context"])
def test_unsupported_scope_and_unresolved_context_are_never_flattened(change):
    args, _ = fixture_binding()
    if change == "statement_shared":
        leaf = args[3]["rules"][0]["qualifiers"]["temporal"]
        args[3]["rules"][0]["qualifiers"]["temporal"] = None
        args[3]["statement_structure"] = dict(op="attach", body=args[3]["statement_structure"],
            qualifiers=dict(conditions=None, exceptions=None, temporal=leaf))
    elif change == "nested_temporal":
        leaf = args[3]["rules"][0]["qualifiers"]["temporal"]
        args[3]["rules"][0]["qualifiers"]["temporal"] = dict(op="not", child=leaf, operator_anchor=None)
    elif change == "partial_coverage":
        args[3]["coverage"]["declared_status"] = "partial"
    else:
        args[2]["context"]["role"] = "required_unavailable"
        args[3]["input"] = copy.deepcopy(args[2])
        args[3]["input_sha256"] = subject.digest(args[2])
    seal(args[3])
    with pytest.raises(ValueError, match="unsupported|complete|coverage"):
        prepare(args)


def duplicate_rule(args, *, distinct_id=False):
    rule = copy.deepcopy(args[3]["rules"][0])
    rule["rule_id"] = "rule-2"
    if distinct_id:
        original = next(item for item in args[3]["occurrences"] if item["facet"] == "temporal")
        occurrence = copy.deepcopy(original)
        occurrence["occurrence_id"] = "temporal-2"
        args[3]["occurrences"].append(occurrence)
        args[3]["coverage"]["segments"][0]["occurrence_ids"].append("temporal-2")
        rule["qualifiers"]["temporal"]["occurrence_id"] = "temporal-2"
    args[3]["rules"].append(rule)
    args[3]["statement_structure"] = dict(op="all", children=[dict(op="rule", rule_id="rule-1"), dict(op="rule", rule_id="rule-2")], operator_anchor=None)
    args[3]["coverage"]["segments"][0]["rule_ids"].append("rule-2")
    seal(args[3])
    args[0]["canonical_ir"]["rules"].append(copy.deepcopy(args[0]["canonical_ir"]["rules"][0]))
    formula = copy.deepcopy(args[1]["formulas"][0])
    formula["formula_index"] = 1
    args[1]["formulas"].append(formula)
    args[1]["candidate_sha256"] = subject.digest(args[0])
    args[1]["canonical_ir_sha256"] = subject.digest(args[0]["canonical_ir"])


def fixture_two_repeated_temporal_rules():
    args, _ = fixture_binding()
    old = args[2]["source_text"]
    shift = len(old) + 1
    text = old + " " + old
    args[2]["source_text"] = text
    second_occurrences = []
    for occurrence in args[3]["occurrences"]:
        item = copy.deepcopy(occurrence)
        item["occurrence_id"] = item["occurrence_id"].replace("-1", "-2")
        item["anchor"]["start"] += shift
        item["anchor"]["end"] += shift
        second_occurrences.append(item)
    args[3]["occurrences"].extend(second_occurrences)
    rule = copy.deepcopy(args[3]["rules"][0])
    rule["rule_id"] = "rule-2"
    rule["body"] = {facet: identity.replace("-1", "-2") for facet, identity in rule["body"].items()}
    for node in rule["qualifiers"].values():
        if node is not None:
            node["occurrence_id"] = node["occurrence_id"].replace("-1", "-2")
    args[3]["rules"].append(rule)
    args[3]["statement_structure"] = dict(op="all", children=[dict(op="rule", rule_id="rule-1"), dict(op="rule", rule_id="rule-2")], operator_anchor=None)
    args[3]["input"] = copy.deepcopy(args[2])
    args[3]["input_sha256"] = subject.digest(args[2])
    coverage = args[3]["coverage"]["segments"][0]
    coverage["span"].update(end=len(text), text=text)
    coverage["rule_ids"] = ["rule-1", "rule-2"]
    coverage["occurrence_ids"] = [item["occurrence_id"] for item in args[3]["occurrences"]]
    seal(args[3])
    args[0].update(source_text=text, source_sha256=sha(text))
    args[0]["canonical_ir"]["rules"].append(copy.deepcopy(args[0]["canonical_ir"]["rules"][0]))
    formula = copy.deepcopy(args[1]["formulas"][0])
    formula["formula_index"] = 1
    args[1]["formulas"].append(formula)
    args[1].update(candidate_sha256=subject.digest(args[0]), source_sha256=sha(text), canonical_ir_sha256=subject.digest(args[0]["canonical_ir"]))
    table = {item["occurrence_id"]: item for item in args[3]["occurrences"]}
    args[4][0]["duration_anchor"] = geometry(table["temporal-1"]["anchor"], args[2])
    args[4].append(dict(rule_index=1, temporal_index=0, scope_rule_id="rule-2", scope_leaf_path="/rules/1/qualifiers/temporal",
                        occurrence_id="temporal-2", duration_anchor=geometry(table["temporal-2"]["anchor"], args[2]), clock_id="clock-2"))
    args[5][0]["anchor"] = geometry(table["modality-1"]["anchor"], args[2])
    clock = copy.deepcopy(args[5][0])
    clock.update(clock_id="clock-2", declaration_id="declaration-2", scope_rule_id="rule-2", anchor=geometry(table["modality-2"]["anchor"], args[2]))
    args[5].append(clock)
    return args, pins(args)


def test_two_identical_temporal_literals_at_distinct_physical_occurrences_stay_distinct():
    args, expected = fixture_two_repeated_temporal_rules()
    report = prepare(args, expected)
    assert report["duration_count"] == report["rule_count"] == 2
    assert [item["occurrence_id"] for item in report["joins"]] == ["temporal-1", "temporal-2"]
    assert report["joins"][0]["temporal_literal"] == report["joins"][1]["temporal_literal"]
    assert report["joins"][0]["duration_anchor"]["char_start"] < report["joins"][1]["duration_anchor"]["char_start"]


@pytest.mark.parametrize("mutation", ["swap_occurrence", "swap_geometry", "swap_clocks", "misordered_maps", "missing_map", "duplicate_clock_id", "duplicate_declaration_id"])
def test_repeated_temporal_rules_cannot_exchange_partial_or_misordered_custody(mutation):
    args, _ = fixture_two_repeated_temporal_rules()
    if mutation == "swap_occurrence":
        args[4][0]["occurrence_id"], args[4][1]["occurrence_id"] = args[4][1]["occurrence_id"], args[4][0]["occurrence_id"]
    elif mutation == "swap_geometry":
        args[4][0]["duration_anchor"], args[4][1]["duration_anchor"] = args[4][1]["duration_anchor"], args[4][0]["duration_anchor"]
    elif mutation == "swap_clocks":
        args[4][0]["clock_id"], args[4][1]["clock_id"] = args[4][1]["clock_id"], args[4][0]["clock_id"]
    elif mutation == "misordered_maps":
        args[4].reverse()
    elif mutation == "missing_map":
        args[4].pop()
    elif mutation == "duplicate_clock_id":
        args[5][1]["clock_id"] = args[5][0]["clock_id"]
    else:
        args[5][1]["declaration_id"] = args[5][0]["declaration_id"]
    with pytest.raises(ValueError, match="binding differs|scope occurrence differs|clock owner|complete|duplicate"):
        prepare(args)


@pytest.mark.parametrize("distinct_id", [False, True])
def test_shared_or_duplicate_physical_temporal_occurrence_cannot_claim_local_scope(distinct_id):
    args, _ = fixture_binding()
    duplicate_rule(args, distinct_id=distinct_id)
    with pytest.raises(ValueError, match="shared temporal occurrence|overlapping temporal occurrences"):
        prepare(args)


def test_temporal_context_occurrence_keeps_its_original_geometry():
    args, _ = fixture_binding(temporal=False, context="This audit retains the declared within 7 days occurrence.")
    literal = "within 7 days"
    text = args[2]["context"]["text"]
    start = text.index(literal)
    anchor = dict(origin="context", start=start, end=start + len(literal), text=literal, offset_unit="unicode_character_half_open")
    args[3]["occurrences"].append(dict(occurrence_id="temporal-1", facet="temporal", canonical_symbol=literal, anchor=anchor))
    args[3]["rules"][0]["qualifiers"]["temporal"] = dict(op="leaf", occurrence_id="temporal-1")
    args[3]["coverage"]["segments"][1]["occurrence_ids"].append("temporal-1")
    seal(args[3])
    args[0]["canonical_ir"]["rules"][0]["temporal"] = [literal]
    args[1]["candidate_sha256"] = subject.digest(args[0])
    args[1]["canonical_ir_sha256"] = subject.digest(args[0]["canonical_ir"])
    choices = dict(temporal_kind="within_duration", quantity=7, unit="day", time_domain="discrete_nat",
                   origin="caller_supplied_evaluation_time", lower_inclusive=True, upper_inclusive=True)
    args[1]["formulas"][0]["temporal"] = dict(source_index=1, source_text=literal, **choices)
    args[4] = [dict(rule_index=0, temporal_index=0, scope_rule_id="rule-1", scope_leaf_path="/rules/0/qualifiers/temporal",
                    occurrence_id="temporal-1", duration_anchor=geometry(anchor, args[2]), clock_id="clock-1")]
    args[5] = [dict(clock_id="clock-1", declaration_id="declaration-1", declaration_scope=subject.DECLARATION_SCOPE,
                    scope_rule_id="rule-1", anchor=geometry(anchor, args[2]), **choices)]
    assert prepare(args)["joins"][0]["duration_anchor"]["origin"] == "context"


def test_report_replay_rejects_resigned_derived_join_or_authority_tampering():
    args, expected = fixture_binding()
    for mutation in ("qualified", "clock", "missing_original"):
        report = prepare(args, expected)
        if mutation == "qualified":
            report["qualified"] = True
        elif mutation == "clock":
            report["joins"][0]["declared_clock"]["quantity"] = 1
        else:
            del report["scope_declaration"]
        report["content_sha256"] = subject.digest({k: v for k, v in report.items() if k != "content_sha256"})
        with pytest.raises(ValueError, match="exact replay"):
            subject.validate_duration_bindings(report, *args, **expected)


def test_report_detaches_mutable_inputs_and_exports():
    args, expected = fixture_binding()
    report = prepare(args, expected)
    before = copy.deepcopy(report)
    args[4][0]["clock_id"] = "changed-original"
    assert report == before
    report["clock_declarations"][0]["quantity"] = 99
    assert args[5][0]["quantity"] == 7


@pytest.mark.parametrize("raw_bytes", [b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":Infinity}', b'{"x":1e999}', b'{"x":1.0}', b'"\xff"'])
def test_strict_json_rejects_duplicate_nonfinite_float_and_non_utf8_bytes(raw_bytes):
    with pytest.raises(ValueError):
        subject.parse_json_bytes(raw_bytes)


def test_unknown_fields_foreign_types_and_oversized_input_are_refused():
    args, _ = fixture_binding()
    args[5][0]["source_meaning_verified"] = True
    with pytest.raises(ValueError, match="closed explicit clock"):
        prepare(args)
    with pytest.raises(ValueError, match="ordinary JSON"):
        subject.digest({"set": {1}})
    with pytest.raises(ValueError, match="byte bound"):
        subject.digest({"oversized": "x" * subject.MAX_BYTES})
    with pytest.raises(ValueError, match="depth bound"):
        subject.digest(json.loads("[" * 30 + "0" + "]" * 30))
