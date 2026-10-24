"""Unsigned declarations over compact fictional retained evidence.

These fixtures are authored report-shaped evidence, not source reexecution,
authenticated reviews, accepted statutory interpretations or learning targets.
"""
from copy import deepcopy
import hashlib
import json

import pytest

from ipfs_datasets_py.logic.autoformal import legal_norm_content_declaration_v1 as owner


def wire(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def digest(value):
    return sha(wire(value))


def fixture_reports():
    """Two occurrence paths share a variable spelling and retain both definitions."""
    text = "Clérk may receive notice and file it."
    variable = {"node_id": "v1", "kind": "variable", "symbol": "recipient", "arguments": [], "binders": []}
    second_variable = dict(variable, node_id="v2")
    expression = {"root": {"node_id": "q", "kind": "forall", "binders": [{"name": "recipient", "sort": {"name": "Object"}}],
        "arguments": [{"node_id": "both", "kind": "and", "binders": [], "arguments": [
            {"node_id": "p1", "kind": "predicate", "symbol": "receives", "binders": [], "arguments": [deepcopy(variable)]},
            {"node_id": "p2", "kind": "predicate", "symbol": "files", "binders": [], "arguments": [deepcopy(second_variable)]}]}]}}
    native_variable = {"node_type": "Variable", "name": "recipient", "sort": None}
    native = {"node_type": "QuantifiedFormula", "quantifier": {"enum": "Quantifier", "value": "∀"},
        "variable": native_variable, "formula": {"node_type": "BinaryFormula",
            "operator": {"enum": "LogicOperator", "value": "∧"},
            "left": {"node_type": "Predicate", "name": "receives", "arguments": [native_variable]},
            "right": {"node_type": "Predicate", "name": "files", "arguments": [native_variable]}}}
    paths = ["/root/arguments/0/arguments/0/arguments/0", "/root/arguments/0/arguments/1/arguments/0"]
    mapping = [{"typed_path": "/root", "native_path": "", "node_id": "q", "kind": "forall"},
        {"typed_path": "/root/binders/0", "native_path": "/variable", "binder_name": "recipient", "kind": "binder", "typed_sort": "Object", "native_sort": None},
        {"typed_path": "/root/arguments/0", "native_path": "/formula", "node_id": "both", "kind": "and"},
        {"typed_path": "/root/arguments/0/arguments/0", "native_path": "/formula/left", "node_id": "p1", "kind": "predicate"},
        {"typed_path": paths[0], "native_path": "/formula/left/arguments/0", "node_id": "v1", "kind": "variable"},
        {"typed_path": "/root/arguments/0/arguments/1", "native_path": "/formula/right", "node_id": "p2", "kind": "predicate"},
        {"typed_path": paths[1], "native_path": "/formula/right/arguments/0", "node_id": "v2", "kind": "variable"}]
    targets = [row for row in mapping if row["kind"] == "variable"]
    source_paths = ["/occurrences/0/anchor"]
    anchor = {"declaration_path": source_paths[0],
        "local_anchor": {"origin": "source", "start": 0, "end": 5, "text": "Clérk", "offset_unit": "unicode_codepoints"}}
    source_row = {"anchor_mapping": anchor, "disposition": "proposed_mapping",
        "targets": deepcopy(targets), "rationale": "Fictional authored actor nomination only."}
    typed_rows = [{"target": target, "disposition": "source_linked" if target in targets else "authored_scaffolding",
        "source_paths": list(source_paths) if target in targets else [],
        "rationale": "Same authored variable spelling, distinct structural use."} for target in mapping]
    contexts = []
    for target in mapping:
        path = target["typed_path"]
        ancestry = [{"typed_path": parent["typed_path"], "kind": parent["kind"],
                     "relative_path": path[len(parent["typed_path"]):]}
                    for parent in mapping if path.startswith(parent["typed_path"] + "/")
                    and parent["kind"] not in ("binder", "variable")]
        is_variable = target["kind"] == "variable"
        predicate = "receives" if path == paths[0] else "files"
        contexts.append({"target": target, "ancestry": ancestry,
            "binding": {"typed_path": "/root/binders/0", "name": "recipient", "quantifier": "forall"} if is_variable else None,
            "argument": {"predicate_path": path.rsplit("/arguments/", 1)[0], "symbol": predicate,
                         "index": 0, "role": "actor"} if is_variable else None})
    occurrence_ref = {"schema": "fixture-source-occurrence/v1", "record_cid": "fixture:occurrence", "sha256": "1" * 64}
    context_ref = {"schema": "fixture-context/v1", "record_cid": "fixture:context", "sha256": "2" * 64}
    unit = {"schema": "legal-source-structured-sample-unit/v1", "record_cid": "fixture:unit",
        "ordinal": 0, "source_text": text, "source_occurrence_ref": occurrence_ref,
        "context_ref": context_ref, "source_text_sha256": sha(text.encode())}
    slots = [{"slot_id": "context:" + name, "kind": name, "availability": "required_unavailable"}
             for name in ("definitions", "references")]
    unresolved = [{"issue_id": "fictional-role", "description": "Participant meaning remains unresolved."}]
    source_scope = {"schema": "legal-source-norm-scope-proposal/v1",
        "source_records": {"unit": unit}, "source_context_packet": {"dependency_slots": slots},
        "scope_declaration": {"coverage": {"declared_status": "partial"}, "unresolved": deepcopy(unresolved)},
        "declared_semantic_coverage": "partial", "anchor_mappings": [anchor]}
    correspondence = {"schema": "legal-norm-scope-correspondence-report/v1", "alternative_id": "fictional-norm",
        "source_scope": source_scope,
        "relational_fragment": {"profile": "authored-object-relational-deontic/v1", "typed_expression": expression,
            "native_ast": native, "structural_mapping": mapping,
            "argument_roles": [{"symbol": name, "roles": ["actor"]} for name in ("receives", "files")]},
        "request": {"source_rows": [source_row], "typed_rows": typed_rows},
        "typed_context_inventory": contexts, "retained_unresolved": unresolved,
        "counts": {"source_anchors": 1, "typed_targets": 7, "authored_scaffolding": 5, "proposed_links": 2},
        "authority": {"accepted": False, "source_semantics_verified": False},
        "training_mask": 0, "evaluation_gold_mask": 0}
    target_source = {"bundle_sha256": "3" * 64,
        "subject_ref": {"kind": "unit", "index": 0, "sha256": digest(unit)},
        "source_occurrence_ref": occurrence_ref, "context_ref": context_ref}
    nominations = [{"nomination": {"target_bundle_sha256": target_source["bundle_sha256"],
        "target_subject_ref": target_source["subject_ref"], "supporting_bundle_sha256": "4" * 64,
        "supporting_subject_ref": {"kind": "unit", "index": index + 1, "sha256": str(index + 5) * 64},
        "role": "Fictional competing definition; applicability unknown."}, "nomination_sha256": str(index + 7) * 64}
        for index in range(2)]
    obligations = [{"slot_id": slot["slot_id"], "kind": "original_context", "original": slot} for slot in slots]
    correspondence_pin = digest(correspondence)
    obligations += [{"slot_id": "norm-issue:" + digest([correspondence_pin, index, issue]),
        "kind": "original_unresolved_issue", "original": issue} for index, issue in enumerate(unresolved)]
    obligations += [{"slot_id": "norm-question:" + digest([correspondence_pin, question]),
        "kind": "interpretation_question", "question": question} for question in (
            "source_meaning", "participant_roles", "condition_and_modal_scope", "definition_applicability",
            "exceptions_and_time", "unsupported_grammar", "source_coverage")]
    preparation = {"schema": "legal-norm-interpretation-review-evidence/v1", "correspondence": correspondence,
        "correspondence_sha256": digest(correspondence), "ast_sha256": digest(expression),
        "native_ast_sha256": digest(native), "scope_id": "fictional:norm-scope",
        "obligations": obligations, "context_slot_ids": [row["slot_id"] for row in obligations],
        "context_evidence": {"status": "replayed_source_nominations_not_applicability", "packet_sha256": "a" * 64,
            "target": target_source, "nominations": nominations, "typed_definition_reviews_supplied": False},
        "governing_definition_use": None, "original_signatures_cover_norm_review": False,
        "authority": {"accepted": False, "source_semantics_verified": False}, "training_mask": 0, "evaluation_gold_mask": 0}
    definitions = [{"alternative_id": "fictional-definition-" + str(index),
        "candidate_cid": "fixture:definition:" + str(index), "candidate_pin": str(index + 1) * 64,
        "term_record": {"record_cid": "fixture:term:" + str(index), "spelling": "clerk"},
        "ast_record": {"record_cid": "fixture:definition-ast:" + str(index), "body": "authored alternative " + str(index)},
        "review_evidence": {"assessment": None, "status": "not_supplied"}}
        for index in range(2)]
    links = []
    for typed_row, typed_context in zip(typed_rows, contexts):
        if typed_row["target"]["kind"] != "variable":
            continue
        for index, endpoint in enumerate(definitions):
            nomination = nominations[index]
            request_link = {"alternative_id": endpoint["alternative_id"], "target": typed_row["target"],
                "source_paths": list(source_paths), "nomination_sha256": digest(nomination),
                "rationale": "Unreviewed nomination; no definition is selected."}
            node = variable if typed_row["target"]["typed_path"] == paths[0] else second_variable
            links.append({"request_link": request_link, "typed_row": typed_row, "typed_node": deepcopy(node),
                "typed_context": typed_context, "source_rows": [source_row], "norm_source_target": target_source,
                "nomination": nomination,
                "definition_term_ref": {"record_cid": endpoint["term_record"]["record_cid"], "sha256": digest(endpoint["term_record"])},
                "definition_ast_ref": {"record_cid": endpoint["ast_record"]["record_cid"], "sha256": digest(endpoint["ast_record"])},
                "status": "source_linked_definition_nomination_unreviewed", "governing_definition_use": None,
                "authority": {"definition_applicability_verified": False}})
    evidence = {"schema": "legal-norm-definition-evidence/v1",
        "profile": "unsigned-source-linked-term-definition-nominations/v1", "status": "unsigned_exact_term_use_evidence",
        "norm_preparation_sha256": digest(preparation), "norm_correspondence_sha256": preparation["correspondence_sha256"],
        "norm_scope_id": preparation["scope_id"], "norm_ast_sha256": preparation["ast_sha256"],
        "norm_native_ast_sha256": preparation["native_ast_sha256"], "source_context": preparation["context_evidence"],
        "original_unresolved": unresolved, "original_context_slots": slots, "norm_obligations": obligations,
        "definitions": definitions, "links": links,
        "counts": {"alternatives": 2, "links": 4, "distinct_typed_uses": 2, "supplied_definition_assessments": 0},
        "all_norm_term_uses_enumerated": False, "selected_interpretation": None, "governing_definition_use": None,
        "original_signatures_cover_companion": False, "native_ast_rewritten": False,
        "authority": {"accepted": False, "definition_applicability_verified": False}, "training_mask": 0, "evaluation_gold_mask": 0}
    # JSON transport duplicates references independently, as retained bytes do.
    return json.loads(wire(preparation)), json.loads(wire(evidence))


def request_for(preparation, evidence, *, preparation_raw=None, evidence_raw=None):
    preparation_raw = wire(preparation) if preparation_raw is None else preparation_raw
    evidence_raw = wire(evidence) if evidence_raw is None else evidence_raw
    groups = list({link["request_link"]["target"]["typed_path"]: link["request_link"]["target"]
                   for link in evidence["links"]}.values())
    return {"schema": "legal-norm-content-declaration-request/v1", "input_scope": "retained_historical_evidence_only",
        "candidate_id": preparation["correspondence"]["alternative_id"],
        "norm_preparation_raw_sha256": sha(preparation_raw), "norm_preparation_sha256": digest(preparation),
        "definition_evidence_raw_sha256": sha(evidence_raw), "definition_evidence_sha256": digest(evidence),
        "interpretation": {"disposition": "pending", "typed_expression_sha256": preparation["ast_sha256"], "rationale": ""},
        "meaning_unit": {"source_unit_sha256": digest(preparation["correspondence"]["source_scope"]["source_records"]["unit"]),
            "coverage": "unassessed", "legal_as_of": None, "rationale": ""},
        "coverage_decisions": [{"slot_id": row["slot_id"], "disposition": "pending", "evidence_refs": [], "rationale": ""}
            for row in preparation["obligations"]],
        "definition_decisions": [{"target": target, "disposition": "pending", "alternative_id": None,
            "link_sha256": None, "evidence_refs": [], "rationale": ""} for target in groups]}


@pytest.fixture
def case():
    preparation, evidence = fixture_reports()
    return {"preparation": preparation, "evidence": evidence, "request": request_for(preparation, evidence)}


def prepare(case):
    request_raw = case.get("request_raw", wire(case["request"]))
    preparation_raw = case.get("preparation_raw", wire(case["preparation"]))
    evidence_raw = case.get("evidence_raw", wire(case["evidence"]))
    return owner.prepare_norm_content_declaration(request_raw, preparation_raw, evidence_raw,
        expected_request_sha256=case.get("expected_request_sha256", sha(request_raw)))


def reseal(case):
    case["evidence"]["norm_preparation_sha256"] = digest(case["preparation"])
    case["request"] = request_for(case["preparation"], case["evidence"])
    return case


def validate(case, report):
    request_raw = case.get("request_raw", wire(case["request"]))
    return owner.validate_norm_content_declaration(report, request_raw,
        case.get("preparation_raw", wire(case["preparation"])), case.get("evidence_raw", wire(case["evidence"])),
        expected_request_sha256=case.get("expected_request_sha256", sha(request_raw)),
        expected_report_sha256=owner.norm_content_declaration_sha256(json.loads(report) if type(report) is bytes else report))


@pytest.mark.parametrize("field", ["norm_preparation_raw_sha256", "norm_preparation_sha256",
    "definition_evidence_raw_sha256", "definition_evidence_sha256"])
def test_independent_raw_and_canonical_evidence_pins_required(case, field):
    case["request"][field] = "0" * 64
    with pytest.raises(ValueError):
        prepare(case)


@pytest.mark.parametrize("pin", [None, False, "", "a" * 63, "A" * 64, "0" * 64])
def test_request_byte_pin_is_exact_and_independent(case, pin):
    case["expected_request_sha256"] = pin
    with pytest.raises(ValueError):
        prepare(case)


@pytest.mark.parametrize("damage", ["schema", "scope", "candidate", "extra", "omitted", "wrong_type"])
def test_closed_top_request_refuses_wrong_scope_or_identity(case, damage):
    if damage == "schema": case["request"]["schema"] = "future/v2"
    elif damage == "scope": case["request"]["input_scope"] = "current_source_replayed"
    elif damage == "candidate": case["request"]["candidate_id"] = "another-norm"
    elif damage == "extra": case["request"]["accepted"] = True
    elif damage == "omitted": case["request"].pop("meaning_unit")
    else: case["request"]["candidate_id"] = False
    with pytest.raises(ValueError):
        prepare(case)


@pytest.mark.parametrize("part", ["interpretation", "meaning_unit"])
@pytest.mark.parametrize("damage", ["extra", "missing", "wrong_type"])
def test_closed_nested_declaration_types(case, part, damage):
    value = case["request"][part]
    if damage == "extra": value["reviewed"] = True
    elif damage == "missing": value.pop("rationale")
    else: case["request"][part] = []
    with pytest.raises(ValueError):
        prepare(case)


@pytest.mark.parametrize("disposition", [None, True, "support", "accepted", "reviewed_gold"])
def test_interpretation_acceptance_cannot_enter_unsigned_profile(case, disposition):
    case["request"]["interpretation"]["disposition"] = disposition
    with pytest.raises(ValueError):
        prepare(case)


@pytest.mark.parametrize("disposition", ["proposed_support", "proposed_reject"])
def test_proposed_interpretation_requires_nonblank_rationale(case, disposition):
    case["request"]["interpretation"].update(disposition=disposition, rationale=" \n ")
    with pytest.raises(ValueError):
        prepare(case)


def test_interpretation_binds_exact_retained_ast(case):
    case["request"]["interpretation"]["typed_expression_sha256"] = "0" * 64
    with pytest.raises(ValueError):
        prepare(case)


@pytest.mark.parametrize("coverage", ["complete", "reviewed_complete", None, True, 1])
def test_complete_meaning_unit_coverage_is_not_supported(case, coverage):
    case["request"]["meaning_unit"]["coverage"] = coverage
    with pytest.raises(ValueError):
        prepare(case)


@pytest.mark.parametrize("date", [False, 20241016, "today", "2024-02-30", "2024-01-01T00:00:00Z"])
def test_legal_date_is_explicit_unknown_or_valid_date_only(case, date):
    case["request"]["meaning_unit"]["legal_as_of"] = date
    with pytest.raises(ValueError):
        prepare(case)


def test_meaning_unit_names_exact_source_unit_not_equal_text(case):
    case["request"]["meaning_unit"]["source_unit_sha256"] = "0" * 64
    with pytest.raises(ValueError):
        prepare(case)


@pytest.mark.parametrize("population", ["coverage_decisions", "definition_decisions"])
@pytest.mark.parametrize("damage", ["omit", "reverse", "duplicate", "empty", "wrong_type"])
def test_complete_ordered_decision_populations_cannot_be_filtered(case, population, damage):
    choices = case["request"][population]
    if damage == "omit": choices.pop()
    elif damage == "reverse": choices.reverse()
    elif damage == "duplicate": choices[1] = deepcopy(choices[0])
    elif damage == "empty": case["request"][population] = []
    else: case["request"][population] = {}
    with pytest.raises(ValueError):
        prepare(case)


@pytest.mark.parametrize("damage", ["foreign_slot", "extra", "missing", "disposition", "refs_type"])
def test_coverage_choices_bind_exact_obligations_with_closed_fields(case, damage):
    value = case["request"]["coverage_decisions"][0]
    if damage == "foreign_slot": value["slot_id"] = "another:obligation"
    elif damage == "extra": value["accepted"] = False
    elif damage == "missing": value.pop("evidence_refs")
    elif damage == "disposition": value["disposition"] = "resolved"
    else: value["evidence_refs"] = None
    with pytest.raises(ValueError):
        prepare(case)


@pytest.mark.parametrize("disposition", ["proposed_resolved", "proposed_not_applicable"])
@pytest.mark.parametrize("missing", ["rationale", "evidence_refs"])
def test_positive_coverage_proposals_require_rationale_and_evidence_references(case, disposition, missing):
    value = case["request"]["coverage_decisions"][0]
    value.update(disposition=disposition, rationale="Declared evidence only.",
                 evidence_refs=[{"artifact_id": "fictional:evidence", "sha256": "e" * 64}])
    value[missing] = " " if missing == "rationale" else []
    with pytest.raises(ValueError):
        prepare(case)


@pytest.mark.parametrize("damage", ["extra", "missing", "id_type", "hash", "duplicate", "duplicate_identity_different_hash"])
def test_declared_evidence_references_are_typed_distinct_and_closed(case, damage):
    ref = {"artifact_id": "fictional:evidence", "sha256": "e" * 64}
    value = case["request"]["coverage_decisions"][0]
    value.update(disposition="proposed_resolved", rationale="Authored supporting reference.", evidence_refs=[ref])
    if damage == "extra": ref["verified"] = True
    elif damage == "missing": ref.pop("sha256")
    elif damage == "id_type": ref["artifact_id"] = False
    elif damage == "hash": ref["sha256"] = "E" * 64
    elif damage == "duplicate": value["evidence_refs"].append(deepcopy(ref))
    else: value["evidence_refs"].append(dict(ref, sha256="f" * 64))
    with pytest.raises(ValueError):
        prepare(case)


@pytest.mark.parametrize("damage", ["bare_name", "path", "node_id", "extra", "missing", "disposition"])
def test_definition_choices_bind_exact_occurrence_not_variable_name(case, damage):
    value = case["request"]["definition_decisions"][0]
    if damage == "bare_name": value["target"] = "recipient"
    elif damage == "path": value["target"]["typed_path"] = "/root/arguments/0"
    elif damage == "node_id": value["target"]["node_id"] = "another-variable"
    elif damage == "extra": value["governing"] = True
    elif damage == "missing": value.pop("link_sha256")
    else: value["disposition"] = "applicable"
    with pytest.raises(ValueError):
        prepare(case)


def applicable(case, *, index=0, link_index=0):
    value = case["request"]["definition_decisions"][index]
    link = case["evidence"]["links"][link_index]
    value.update(disposition="proposed_applicable", alternative_id=link["request_link"]["alternative_id"],
        link_sha256=digest(link), rationale="An explicitly authored applicability proposal.",
        evidence_refs=[{"artifact_id": "fictional:applicability-evidence", "sha256": "f" * 64}])
    return value


@pytest.mark.parametrize("damage", ["alternative", "link", "other_occurrence", "rationale", "refs"])
def test_applicability_proposal_requires_exact_alternative_link_and_support(case, damage):
    value = applicable(case)
    if damage == "alternative": value["alternative_id"] = "unavailable-definition"
    elif damage == "link": value["link_sha256"] = "0" * 64
    elif damage == "other_occurrence": value["link_sha256"] = digest(case["evidence"]["links"][2])
    elif damage == "rationale": value["rationale"] = ""
    else: value["evidence_refs"] = []
    with pytest.raises(ValueError):
        prepare(case)


@pytest.mark.parametrize("disposition", ["pending", "proposed_not_applicable"])
@pytest.mark.parametrize("field", ["alternative_id", "link_sha256"])
def test_pending_and_all_alternatives_inapplicable_declarations_cannot_select(case, disposition, field):
    value = case["request"]["definition_decisions"][0]
    value.update(disposition=disposition, rationale="No definition is selected.",
        evidence_refs=[{"artifact_id": "fictional:evidence", "sha256": "e" * 64}])
    value[field] = "fictional-definition-0" if field == "alternative_id" else digest(case["evidence"]["links"][0])
    with pytest.raises(ValueError):
        prepare(case)


@pytest.mark.parametrize("part", ["request", "preparation", "evidence"])
@pytest.mark.parametrize("malformed", ["duplicate", "nonfinite", "wrong_root", "invalid_utf8"])
def test_rehashed_bad_json_transport_is_refused(case, part, malformed):
    if malformed == "duplicate": raw = b'{"schema":"one","schema":"two"}'
    elif malformed == "nonfinite": raw = b'{"value":NaN}'
    elif malformed == "wrong_root": raw = b'[]'
    else: raw = b'\xff'
    case[part + "_raw"] = raw
    if part != "request": case["request"]["norm_preparation_raw_sha256" if part == "preparation" else "definition_evidence_raw_sha256"] = sha(raw)
    with pytest.raises(ValueError):
        prepare(case)


@pytest.mark.parametrize("part", ["request", "preparation", "evidence"])
def test_inputs_require_exact_bytes_without_coercion(case, part):
    args = [wire(case["request"]), wire(case["preparation"]), wire(case["evidence"])]
    args[("request", "preparation", "evidence").index(part)] = args[("request", "preparation", "evidence").index(part)].decode()
    with pytest.raises(ValueError):
        owner.prepare_norm_content_declaration(*args, expected_request_sha256=sha(wire(case["request"])))


def assert_unqualified(report):
    assert report["meaning_unit_id"] is report["accepted_interpretation"] is report["governing_definition_use"] is None
    assert report["selected_occurrence"] is None
    assert report["current_upstream_reexecution_performed"] is False
    assert report["typed_native_equivalence_reexecution"] is False
    assert report["declaration_status"] == "unsigned_proposed_content"
    assert report["evidence_reference_status"] == "declared_not_verified"
    assert report["typed_definition_application_status"] == "unsupported_requires_separate_adapter"
    assert report["blockers"]
    assert all(type(flag) is bool and flag is False for flag in report["authority"].values())
    for field in ("semantic_mask", "consumer_mask", "training_mask", "evaluation_gold_mask"):
        assert type(report[field]) is int and report[field] == 0
    for field in ("established_meaning_units", "accepted_interpretations", "applied_definition_uses"):
        assert type(report["counts"][field]) is int and report["counts"][field] == 0


def test_pending_population_preserves_complete_original_evidence_and_occurrences(case, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("historical source or compiler operation owner was invoked")
    monkeypatch.setattr(owner.contexts, "_owners", forbidden)
    if hasattr(owner.transport, "_owners"):
        monkeypatch.setattr(owner.transport, "_owners", forbidden)
    before = deepcopy(case)
    report = prepare(case)
    assert validate(case, report) == report
    assert owner.norm_content_declaration_sha256(report) == digest(report)
    assert wire(case) == wire(before)
    assert report["schema"] == "legal-norm-content-declaration-preparation/v1"
    assert report["input_scope"] == "retained_historical_evidence_only"
    assert wire(report["retained_norm_preparation"]) == wire(case["preparation"])
    assert wire(report["retained_definition_evidence"]) == wire(case["evidence"])
    assert report["counts"] == {"typed_targets": 7, "source_anchors": 1, "obligations": 10,
        "definition_alternatives": 2, "definition_links": 4, "distinct_typed_uses": 2,
        "established_meaning_units": 0, "accepted_interpretations": 0, "applied_definition_uses": 0}
    uses = report["definition_uses"]
    assert len({group["target"]["typed_path"] for group in uses}) == 2
    assert [group["target"]["node_id"] for group in uses] == ["v1", "v2"]
    assert all(group["typed_context"]["binding"]["name"] == "recipient" for group in uses)
    assert [group["typed_context"]["argument"]["symbol"] for group in uses] == ["receives", "files"]
    assert all(len(group["links"]) == 2 for group in uses)
    assert all(choice["disposition"] == "pending" for choice in report["request"]["coverage_decisions"])
    assert all(choice["disposition"] == "pending" for choice in report["request"]["definition_decisions"])
    assert report["request"]["meaning_unit"]["legal_as_of"] is None
    assert_unqualified(report)


@pytest.mark.parametrize("disposition", ["proposed_support", "proposed_reject"])
def test_declared_positive_or_negative_content_has_no_acceptance_effect(case, disposition):
    case["request"]["interpretation"].update(disposition=disposition, rationale="An authored declaration, not an authenticated review.")
    for choice in case["request"]["coverage_decisions"]:
        choice.update(disposition="proposed_resolved", rationale="A declared supporting artifact only.",
            evidence_refs=[{"artifact_id": "fictional:evidence", "sha256": "e" * 64}])
    applicable(case)
    case["request"]["definition_decisions"][1].update(disposition="proposed_not_applicable",
        rationale="Both nominated alternatives are proposed inapplicable to this occurrence.",
        evidence_refs=[{"artifact_id": "fictional:dispute", "sha256": "d" * 64}])
    report = prepare(case)
    assert report["request"] == case["request"]
    assert len(report["definition_uses"][1]["links"]) == 2
    assert report["retained_definition_evidence"]["original_unresolved"] == case["evidence"]["original_unresolved"]
    assert_unqualified(report)


@pytest.mark.parametrize("date", [None, "2024-02-29"])
def test_partial_unit_and_unknown_or_declared_civil_date_are_retained_as_proposals(case, date):
    case["request"]["meaning_unit"].update(coverage="partial", legal_as_of=date,
        rationale="Declared partial scope; source applicability remains unverified.")
    report = prepare(case)
    assert report["request"]["meaning_unit"] == case["request"]["meaning_unit"]
    assert_unqualified(report)


def test_historical_producer_metadata_and_disputed_choices_are_not_rewritten(case):
    case["preparation"]["producer_pins"] = {"/unavailable/historical-norm.py": "b" * 64}
    case["evidence"]["producer_pins"] = {"/unavailable/historical-definition.py": "c" * 64}
    reseal(case)
    case["request"]["coverage_decisions"][0].update(disposition="proposed_not_applicable",
        rationale="A disputed authored coverage choice.", evidence_refs=[{"artifact_id": "fictional:dispute", "sha256": "d" * 64}])
    report = prepare(case)
    assert report["original_subjects_and_producer_pins_unchanged"] is True
    assert report["retained_norm_preparation"]["producer_pins"] == case["preparation"]["producer_pins"]
    assert report["retained_definition_evidence"]["producer_pins"] == case["evidence"]["producer_pins"]
    assert report["request"]["coverage_decisions"][1]["disposition"] == "pending"
    assert report["request"]["coverage_decisions"][0]["disposition"] == "proposed_not_applicable"
    assert_unqualified(report)


def test_transport_whitespace_is_distinct_from_canonical_retained_identity(case):
    before = prepare(case)
    case["preparation_raw"] = json.dumps(case["preparation"], ensure_ascii=False, indent=2).encode()
    case["evidence_raw"] = json.dumps(case["evidence"], ensure_ascii=False, indent=2).encode()
    case["request"] = request_for(case["preparation"], case["evidence"],
        preparation_raw=case["preparation_raw"], evidence_raw=case["evidence_raw"])
    report = prepare(case)
    assert report["request"]["norm_preparation_sha256"] == before["request"]["norm_preparation_sha256"]
    assert report["request"]["definition_evidence_sha256"] == before["request"]["definition_evidence_sha256"]
    assert report["request"]["norm_preparation_raw_sha256"] != before["request"]["norm_preparation_raw_sha256"]
    assert report["request"]["definition_evidence_raw_sha256"] != before["request"]["definition_evidence_raw_sha256"]
    assert validate(case, wire(report)) == report


@pytest.mark.parametrize("damage", ["authority", "mask", "training_alias", "interpretation", "source", "output", "drop_group"])
def test_resealed_output_mutation_fails_full_regeneration(case, damage):
    report = prepare(case)
    changed = deepcopy(report)
    if damage == "authority": changed["authority"]["source_semantics_verified"] = True
    elif damage == "mask": changed["semantic_mask"] = 1
    elif damage == "training_alias": changed["training_mask"] = False
    elif damage == "interpretation": changed["accepted_interpretation"] = "fictional-norm"
    elif damage == "source": changed["retained_norm_preparation"]["correspondence"]["source_scope"]["source_records"]["unit"]["source_text"] += " changed"
    elif damage == "output": changed["definition_uses"][0]["typed_context"]["binding"]["name"] = "different"
    else: changed["definition_uses"].pop()
    with pytest.raises(ValueError):
        validate(case, changed)


@pytest.mark.parametrize("damage", ["ast_commitment", "native_ast", "source_unit", "source_context", "binder",
    "term_ref", "definition_ast_ref", "unresolved", "obligation", "def_count_alias", "authority_alias", "mask_alias"])
def test_rehashed_retained_crosslinks_and_exact_types_remain_required(case, damage):
    preparation, evidence = case["preparation"], case["evidence"]
    if damage == "ast_commitment": evidence["norm_ast_sha256"] = "0" * 64
    elif damage == "native_ast": preparation["correspondence"]["relational_fragment"]["native_ast"]["formula"]["operator"]["value"] = "∨"
    elif damage == "source_unit": preparation["correspondence"]["source_scope"]["source_records"]["unit"]["ordinal"] = False
    elif damage == "source_context": evidence["source_context"]["target"]["subject_ref"]["index"] = False
    elif damage == "binder": evidence["links"][0]["typed_context"]["binding"]["name"] = "another"
    elif damage == "term_ref": evidence["links"][0]["definition_term_ref"]["sha256"] = "0" * 64
    elif damage == "definition_ast_ref": evidence["links"][0]["definition_ast_ref"] = deepcopy(evidence["links"][1]["definition_ast_ref"])
    elif damage == "unresolved": evidence["original_unresolved"] = []
    elif damage == "obligation": evidence["norm_obligations"].pop()
    elif damage == "def_count_alias": evidence["counts"]["supplied_definition_assessments"] = False
    elif damage == "authority_alias": preparation["authority"]["accepted"] = 0
    else: evidence["training_mask"] = False
    reseal(case)
    with pytest.raises(ValueError):
        prepare(case)


@pytest.mark.parametrize("damage", ["mapping_omission", "mapping_order", "typed_rows", "anchor", "node", "duplicate_link", "unused_definition"])
def test_complete_retained_structural_populations_are_not_summarized_or_repaired(case, damage):
    fragment = case["preparation"]["correspondence"]["relational_fragment"]
    if damage == "mapping_omission": fragment["structural_mapping"].pop()
    elif damage == "mapping_order": fragment["structural_mapping"].reverse()
    elif damage == "typed_rows": case["preparation"]["correspondence"]["request"]["typed_rows"].pop()
    elif damage == "anchor": case["evidence"]["links"][0]["source_rows"][0]["anchor_mapping"]["local_anchor"]["text"] = "different"
    elif damage == "node": case["evidence"]["links"][0]["typed_node"]["symbol"] = "different"
    elif damage == "duplicate_link": case["evidence"]["links"].append(deepcopy(case["evidence"]["links"][0]))
    else: case["evidence"]["definitions"].append(deepcopy(case["evidence"]["definitions"][0]) | {"alternative_id": "unused"})
    reseal(case)
    with pytest.raises(ValueError):
        prepare(case)


@pytest.mark.parametrize("bound", ["MAX_REQUEST_BYTES", "MAX_INPUT_BYTES", "MAX_REPORT_BYTES", "MAX_TARGETS", "MAX_OBLIGATIONS", "MAX_DEFINITIONS", "MAX_LINKS", "MAX_REFS"])
def test_complete_bounds_refuse_without_truncation(case, monkeypatch, bound):
    report = prepare(case)
    limits = {"MAX_REQUEST_BYTES": len(wire(case["request"])) - 1,
        "MAX_INPUT_BYTES": min(len(wire(case["preparation"])), len(wire(case["evidence"]))) - 1,
        "MAX_REPORT_BYTES": len(wire(report)) - 1, "MAX_TARGETS": 6,
        "MAX_OBLIGATIONS": 9, "MAX_DEFINITIONS": 1, "MAX_LINKS": 3, "MAX_REFS": 0}
    if bound == "MAX_REFS": applicable(case)
    monkeypatch.setattr(owner, bound, limits[bound])
    with pytest.raises(ValueError):
        prepare(case)


@pytest.mark.parametrize("which", ["self", "transport", "contexts", "review_schema"])
def test_self_and_strict_helper_source_freshness_is_checked_before_preparation(case, monkeypatch, which):
    pins = dict(owner._IMPORT_PINS)
    path = owner.__file__ if which == "self" else getattr(owner, which).__file__
    pins[path] = "0" * 64
    monkeypatch.setattr(owner, "_IMPORT_PINS", pins)
    with pytest.raises(ValueError, match="changed since import"):
        prepare(case)


def test_helper_freshness_is_checked_again_after_structural_work(case, monkeypatch):
    original = owner._retained
    def changed(*args, **kwargs):
        result = original(*args, **kwargs)
        monkeypatch.setattr(owner, "_IMPORT_PINS", dict.fromkeys(owner._IMPORT_PINS, "0" * 64))
        return result
    monkeypatch.setattr(owner, "_retained", changed)
    with pytest.raises(ValueError, match="changed since import"):
        prepare(case)


@pytest.mark.parametrize("field", ["declared_semantic_coverage", "scope_declaration"])
def test_rehashed_retained_profile_cannot_claim_complete_meaning_coverage(case, field):
    scope = case["preparation"]["correspondence"]["source_scope"]
    if field == "declared_semantic_coverage":
        scope[field] = "complete"
    else:
        scope[field]["coverage"]["declared_status"] = "complete"
    reseal(case)
    with pytest.raises(ValueError, match="retained partial coverage"):
        prepare(case)
