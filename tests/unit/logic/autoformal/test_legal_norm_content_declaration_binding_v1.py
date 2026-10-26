"""Explicit historical/current custody binding never accepts statutory meaning.

The current side uses genuine full authored source/context replay. The retained
side is a fictional older producer generation over that exact evidence, plus
the existing authored unsigned-definition fixtures. No historical execution,
human review, governing definition or training target is manufactured here.
"""

from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.autoformal import legal_graph_dependencies as dependencies
from ipfs_datasets_py.logic.autoformal import legal_norm_content_declaration_v1 as declaration
from ipfs_datasets_py.logic.autoformal import legal_norm_content_responses_v1 as content
from ipfs_datasets_py.logic.autoformal import legal_norm_interpretation_review_v1 as norm


INPUT_NAMES = ("declaration", "declaration_request", "retained_norm_preparation",
               "retained_definition_evidence", "current_preparation", "dependency_manifest")


def wire(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def digest(value):
    return sha(wire(value))


def load_fixture(name, filename):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(filename))
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def fixtures():
    return {
        "norm": load_fixture("_binding_authored_source_replay", "test_legal_norm_interpretation_review_v1.py"),
        "declaration": load_fixture("_binding_authored_unsigned_definitions", "test_legal_norm_content_declaration_v1.py"),
        "content": load_fixture("_binding_authored_signed_content", "test_legal_norm_content_responses_v1.py"),
    }


@pytest.fixture(scope="module")
def owner():
    from ipfs_datasets_py.logic.autoformal import legal_norm_content_declaration_binding_v1

    return legal_norm_content_declaration_binding_v1


def original_obligations(preparation):
    correspondence = preparation["correspondence"]
    slots = correspondence["source_scope"]["source_context_packet"]["dependency_slots"]
    obligations = [{"slot_id": slot["slot_id"], "kind": "original_context", "original": deepcopy(slot)}
                   for slot in slots]
    obligations.extend({"slot_id": "norm-issue:" + digest([preparation["correspondence_sha256"], index, issue]),
                        "kind": "original_unresolved_issue", "original": deepcopy(issue)}
                       for index, issue in enumerate(correspondence["retained_unresolved"]))
    obligations.extend({"slot_id": "norm-question:" + digest([preparation["correspondence_sha256"], question]),
                        "kind": "interpretation_question", "question": question}
                       for question in norm.SEMANTIC_QUESTIONS)
    return obligations


def historical_generation(current):
    """Author different code metadata; preserve every physical/semantic record."""
    historical = deepcopy(current)
    marker = "fixture:declared-historical-generation"
    marker_pin = sha(b"Fictional older producer metadata, not a historical execution assertion.")
    historical["producer_pins"][marker] = marker_pin
    historical["correspondence"]["producer_pins"][marker] = marker_pin
    historical["correspondence_sha256"] = digest(historical["correspondence"])
    old_root = historical["graph_id"]
    historical["graph_id"] = "norm-correspondence:" + historical["correspondence_sha256"]
    historical["graph_sha256"] = historical["correspondence_sha256"]
    historical["scope_id"] = "norm-review-scope:" + digest({
        "domain": norm.SUBJECT_SCHEMA,
        "correspondence_sha256": historical["correspondence_sha256"],
        "source_unit": historical["correspondence"]["source_scope"]["input_pins"]["selected_unit_ref"]})
    historical["obligations"] = original_obligations(historical)
    historical["context_slot_ids"] = [row["slot_id"] for row in historical["obligations"]]
    for artifact in historical["artifacts"]:
        if artifact["artifact_id"] == old_root:
            artifact.update(artifact_id=historical["graph_id"], artifact_sha256=historical["graph_sha256"])
        elif artifact["artifact_id"] == "norm-review-producers":
            artifact["artifact_sha256"] = digest(historical["producer_pins"])
            artifact["dependency_pins"]["policy"] = [
                {"key": path, "sha256": pin} for path, pin in sorted(historical["producer_pins"].items())]
    for edge in historical["edges"]:
        if edge["dependent_id"] == old_root:
            edge["dependent_id"] = historical["graph_id"]
    historical["required_dependency_ids"] = [historical["graph_id"] if value == old_root else value
                                             for value in historical["required_dependency_ids"]]
    return historical


def at(document, path):
    for token in path.split("/")[1:]:
        token = token.replace("~1", "/").replace("~0", "~")
        document = document[int(token)] if type(document) is list else document[token]
    return document


def unsigned_definitions(fixtures, preparation):
    """Bind fictional endpoint bodies to genuine retained source-use geometry."""
    _, authored = fixtures["declaration"].fixture_reports()
    definitions = deepcopy(authored["definitions"])
    correspondence = preparation["correspondence"]
    source_target = preparation["context_evidence"]["target"]
    nomination = preparation["context_evidence"]["nominations"][0]
    links = []
    for typed, context in zip(correspondence["request"]["typed_rows"],
                              correspondence["typed_context_inventory"], strict=True):
        target = typed["target"]
        if target["kind"] not in {"variable", "predicate"} or typed["disposition"] != "source_linked":
            continue
        sources = [row for row in correspondence["request"]["source_rows"]
                   if row["anchor_mapping"]["declaration_path"] in typed["source_paths"]]
        for endpoint in definitions:
            request_link = {"alternative_id": endpoint["alternative_id"], "target": deepcopy(target),
                "source_paths": deepcopy(typed["source_paths"]), "nomination_sha256": digest(nomination),
                "rationale": "Fictional retained unsigned nomination; applicability remains unverified."}
            links.append({"request_link": request_link, "typed_row": deepcopy(typed),
                "typed_node": deepcopy(at(correspondence["relational_fragment"]["typed_expression"], target["typed_path"])),
                "typed_context": deepcopy(context), "source_rows": deepcopy(sources),
                "norm_source_target": deepcopy(source_target), "nomination": deepcopy(nomination),
                "definition_term_ref": {"record_cid": endpoint["term_record"]["record_cid"],
                    "sha256": digest(endpoint["term_record"])},
                "definition_ast_ref": {"record_cid": endpoint["ast_record"]["record_cid"],
                    "sha256": digest(endpoint["ast_record"])},
                "status": "source_linked_definition_nomination_unreviewed", "governing_definition_use": None,
                "authority": {"definition_applicability_verified": False}})
    return {"schema": "legal-norm-definition-evidence/v1",
        "profile": "unsigned-source-linked-term-definition-nominations/v1", "status": "unsigned_exact_term_use_evidence",
        "norm_preparation_sha256": digest(preparation),
        "norm_correspondence_sha256": preparation["correspondence_sha256"],
        "norm_scope_id": preparation["scope_id"], "norm_ast_sha256": preparation["ast_sha256"],
        "norm_native_ast_sha256": preparation["native_ast_sha256"],
        "source_context": deepcopy(preparation["context_evidence"]),
        "original_unresolved": deepcopy(correspondence["retained_unresolved"]),
        "original_context_slots": deepcopy(correspondence["source_scope"]["source_context_packet"]["dependency_slots"]),
        "norm_obligations": deepcopy(preparation["obligations"]), "definitions": definitions, "links": links,
        "counts": {"alternatives": len(definitions), "links": len(links),
            "distinct_typed_uses": len({link["request_link"]["target"]["typed_path"] for link in links}),
            "supplied_definition_assessments": 0},
        "all_norm_term_uses_enumerated": False, "selected_interpretation": None, "governing_definition_use": None,
        "original_signatures_cover_companion": False, "native_ast_rewritten": False,
        "authority": {"accepted": False, "definition_applicability_verified": False},
        "training_mask": 0, "evaluation_gold_mask": 0}


def seal_inputs(case):
    case["expected_input_pins"] = {name: {"raw_sha256": sha(raw), "canonical_sha256": digest(json.loads(raw))}
                                   for name, raw in zip(INPUT_NAMES, case["raw_inputs"], strict=True)}
    return case


def rebuild_retained_inputs(case, fixtures, *, request=None):
    prep_raw = wire(case["historical_preparation"])
    evidence_raw = wire(case["historical_evidence"])
    request = fixtures["declaration"].request_for(case["historical_preparation"], case["historical_evidence"]) \
        if request is None else request
    request_raw = wire(request)
    report = declaration.prepare_norm_content_declaration(request_raw, prep_raw, evidence_raw,
                                                          expected_request_sha256=sha(request_raw))
    case["declaration"] = report
    case["raw_inputs"][:4] = [wire(report), request_raw, prep_raw, evidence_raw]
    return seal_inputs(case)


@pytest.fixture(scope="module")
def materialized(fixtures):
    return fixtures["norm"].materialize(norm, with_context=True)


@pytest.fixture(scope="module")
def base(fixtures, materialized):
    current = materialized["preparation"]
    historical = historical_generation(current)
    case = {"historical_preparation": historical,
        "historical_evidence": unsigned_definitions(fixtures, historical),
        "current_preparation": deepcopy(current),
        "current_build_inputs": deepcopy(materialized["build_arguments"]),
        "raw_inputs": [b""] * 4 + [wire(current), wire(materialized["manifest"])]}
    return rebuild_retained_inputs(case, fixtures)


@pytest.fixture
def case(base):
    return deepcopy(base)


def prepare(owner, case):
    return owner.prepare_norm_content_declaration_binding_v1(*case["raw_inputs"],
        expected_input_pins=case["expected_input_pins"], current_build_inputs=case["current_build_inputs"])


def validate(owner, report, case, *, expected_report_sha256=None):
    return owner.validate_norm_content_declaration_binding_v1(report, *case["raw_inputs"],
        expected_input_pins=case["expected_input_pins"], current_build_inputs=case["current_build_inputs"],
        expected_report_sha256=owner.norm_content_declaration_binding_sha256(report)
        if expected_report_sha256 is None else expected_report_sha256)


def assert_unqualified(report):
    assert report["authority"]
    assert all(value is False for value in report["authority"].values())
    for name in ("semantic_mask", "consumer_mask", "training_mask", "evaluation_gold_mask"):
        assert type(report[name]) is int and report[name] == 0
    assert report["selected_interpretation"] is report["accepted_interpretation"] is report["governing_definition_use"] is None
    assert report["norm_interpretation_ready"] is False
    assert report["automatic_response_injection_performed"] is False
    assert report["historical_inputs_rewritten"] is False
    assert report["declared_nested_evidence"]["status"] == "declared_not_verified"
    assert report["declared_nested_evidence"]["supporting_bodies_verified"] is False
    for name in ("authenticated_declarations", "applied_meaning_decisions", "applied_definition_uses"):
        assert type(report["counts"][name]) is int and report["counts"][name] == 0


@pytest.fixture(scope="module")
def prepared(owner, base):
    return prepare(owner, base)


def test_full_replay_binds_every_changed_historical_slot_without_rewriting_either_generation(owner, case, prepared):
    historical = case["historical_preparation"]
    current = case["current_preparation"]
    original = deepcopy(case)
    assert historical["correspondence_sha256"] != current["correspondence_sha256"]
    assert historical["ast_sha256"] == current["ast_sha256"]
    assert historical["native_ast_sha256"] == current["native_ast_sha256"]
    pairs = prepared["slot_pairs"]
    assert len(pairs) == len(historical["obligations"]) == len(current["obligations"])
    assert prepared["input_pins"] == case["expected_input_pins"]
    for index, (pair, old, new) in enumerate(zip(pairs, historical["obligations"], current["obligations"], strict=True)):
        assert pair["ordinal"] == index
        assert pair["kind"] == old["kind"] == new["kind"]
        assert pair["historical_slot_id"] == old["slot_id"]
        assert pair["current_slot_id"] == new["slot_id"]
        assert pair["historical_obligation_sha256"] == digest(old)
        assert pair["current_obligation_sha256"] == digest(new)
        assert pair["historical_content_sha256"] == pair["current_content_sha256"]
        if old["kind"] == "original_context":
            assert old["slot_id"] == new["slot_id"]
        else:
            assert old["slot_id"] != new["slot_id"]
    assert all(row["equal"] is True and row["historical_sha256"] == row["current_sha256"]
               for row in prepared["comparisons"])
    assert prepared["generation_differences"]
    assert any("producer_pins" in row["path"] for row in prepared["generation_differences"])
    assert prepared["counts"]["slot_pairs"] == len(pairs)
    assert prepared["counts"]["changed_slot_ids"] == sum(row["kind"] != "original_context" for row in pairs)
    assert prepared["historical_generation"]["historical_owner_reexecution_performed"] is False
    assert prepared["historical_generation"]["mapping_request_raw_bytes_verified"] is False
    assert prepared["current_generation"]["complete_current_norm_replay_performed"] is True
    assert prepared["current_generation"]["current_definition_reexecution_performed"] is False
    assert validate(owner, prepared, case) == prepared
    assert case == original
    assert_unqualified(prepared)


@pytest.mark.parametrize("name", INPUT_NAMES)
@pytest.mark.parametrize("pin_kind", ["raw_sha256", "canonical_sha256"])
def test_each_independent_input_pin_is_checked_before_current_source_replay(owner, case, monkeypatch, name, pin_kind):
    case["expected_input_pins"][name][pin_kind] = "0" * 64
    calls = []

    def forbidden(*args, **kwargs):
        calls.append("current source replay")
        raise AssertionError("invalid independent pin reached source replay")

    monkeypatch.setattr(content, "build_norm_content_template_v1", forbidden)
    with pytest.raises(ValueError):
        prepare(owner, case)
    assert calls == []


@pytest.mark.parametrize("damage", ["missing", "extra", "nested_extra", "null_pin", "wrong_type"])
def test_input_pin_population_is_closed_and_explicit(owner, case, monkeypatch, damage):
    pins = case["expected_input_pins"]
    if damage == "missing": pins.pop("declaration")
    elif damage == "extra": pins["unrelated"] = deepcopy(pins["declaration"])
    elif damage == "nested_extra": pins["declaration"]["authority"] = False
    elif damage == "null_pin": pins["declaration"]["raw_sha256"] = None
    else: case["expected_input_pins"] = list(pins.items())
    calls = []

    def forbidden(*args, **kwargs):
        calls.append("current source replay")
        raise AssertionError("malformed input pins reached source replay")

    monkeypatch.setattr(content, "build_norm_content_template_v1", forbidden)
    with pytest.raises(ValueError):
        prepare(owner, case)
    assert calls == []


def test_raw_declaration_identity_is_distinct_from_its_canonical_content(owner, case, prepared):
    original = case["expected_input_pins"]["declaration"]
    pretty = json.dumps(json.loads(case["raw_inputs"][0]), ensure_ascii=False, indent=2,
                        allow_nan=False).encode("utf-8")
    case["raw_inputs"][0] = pretty
    seal_inputs(case)
    changed = case["expected_input_pins"]["declaration"]
    assert changed["raw_sha256"] != original["raw_sha256"]
    assert changed["canonical_sha256"] == original["canonical_sha256"]
    report = prepare(owner, case)
    assert report["input_pins"]["declaration"] == changed
    assert report["slot_pairs"] == prepared["slot_pairs"]
    assert_unqualified(report)


@pytest.mark.parametrize("damage", ["missing", "reordered", "duplicate", "kind", "content"])
def test_pure_slot_pairing_refuses_incomplete_misordered_or_changed_obligations(owner, case, damage):
    historical = case["historical_preparation"]
    current = case["current_preparation"]
    if damage == "missing":
        historical["obligations"].pop()
    elif damage == "reordered":
        historical["obligations"].reverse()
    elif damage == "duplicate":
        historical["obligations"][1]["slot_id"] = historical["obligations"][0]["slot_id"]
    elif damage == "kind":
        historical["obligations"][0]["kind"] = "interpretation_question"
    else:
        historical["obligations"][0]["original"]["availability"] = "invented_available_context"
    with pytest.raises(ValueError):
        owner._slot_pairs(historical, current)


@pytest.mark.parametrize("damage", ["missing", "reordered", "old_slot", "new_slot", "hash"])
def test_rehashed_saved_pairing_cannot_drop_reorder_or_replace_the_explicit_crosswalk(owner, case, prepared, damage):
    report = deepcopy(prepared)
    if damage == "missing": report["slot_pairs"].pop()
    elif damage == "reordered": report["slot_pairs"].reverse()
    elif damage == "old_slot": report["slot_pairs"][0]["historical_slot_id"] = "fixture:foreign-old-slot"
    elif damage == "new_slot": report["slot_pairs"][0]["current_slot_id"] = "fixture:foreign-new-slot"
    else: report["slot_pairs"][0]["current_obligation_sha256"] = "0" * 64
    with pytest.raises(ValueError):
        validate(owner, report, case)


@pytest.mark.parametrize("damage", [
    "unit_identity", "occurrence_identity", "source_anchor", "coverage", "unresolved_issue",
    "typed_ast", "argument_roles", "typed_ancestry", "source_inverse", "context_nomination", "extra_semantics",
])
def test_pure_generation_comparison_preserves_complete_physical_source_and_meaning_geometry(owner, case, damage):
    historical = case["historical_preparation"]
    correspondence = historical["correspondence"]
    scope = correspondence["source_scope"]
    if damage == "unit_identity":
        scope["source_records"]["unit"]["record_cid"] = "fixture:different-physical-unit"
    elif damage == "occurrence_identity":
        scope["source_records"]["unit"]["source_occurrence_ref"]["sha256"] = "0" * 64
    elif damage == "source_anchor":
        scope["anchor_mappings"][0]["declaration_path"] += "/different-source-anchor"
    elif damage == "coverage":
        scope["scope_declaration"]["coverage"]["declared_status"] = "complete"
    elif damage == "unresolved_issue":
        correspondence["retained_unresolved"][0]["reason"] += " silently resolved"
    elif damage == "typed_ast":
        expression = correspondence["relational_fragment"]["typed_expression"]
        modal = next(target for target in correspondence["relational_fragment"]["structural_mapping"]
                     if target["kind"] == "legacy.deontic/v1")
        at(expression, modal["typed_path"])["payload"]["letter"] = "O"
    elif damage == "argument_roles":
        row = next(row for row in correspondence["relational_fragment"]["argument_roles"] if len(row["roles"]) > 1)
        row["roles"].reverse()
    elif damage == "typed_ancestry":
        row = next(row for row in correspondence["typed_context_inventory"] if row["ancestry"])
        row["ancestry"] = []
    elif damage == "source_inverse":
        row = next(row for row in correspondence["request"]["typed_rows"] if row["source_paths"])
        row["source_paths"] = []
    elif damage == "context_nomination":
        historical["context_evidence"]["nominations"][0]["nomination"]["role"] += " changed context role"
    else:
        scope["unexpected_meaning_assertion"] = "Must not disappear as generation metadata."
    with pytest.raises(ValueError):
        owner._compare_preparations(historical, case["current_preparation"])


def test_self_consistent_generation_hashes_cannot_hide_lost_typed_ancestry(owner, case):
    historical = case["historical_preparation"]
    row = next(row for row in historical["correspondence"]["typed_context_inventory"] if row["ancestry"])
    row["ancestry"] = []
    historical = historical_generation(historical)
    projection, generation_fields = owner._generation_projection(historical)
    assert generation_fields
    assert projection["correspondence"]["typed_context_inventory"] != \
        case["current_preparation"]["correspondence"]["typed_context_inventory"]
    with pytest.raises(ValueError, match="unexplained non-generation"):
        owner._compare_preparations(historical, case["current_preparation"])


def materialize_other_physical_source(fixtures):
    helper = fixtures["norm"]
    value = helper.fixture.case(edition=2025)
    arguments = helper.preparation_arguments(value, with_context=True)
    preparation = norm.prepare_norm_review_evidence_v1(**arguments)
    manifest = dependencies.build_dependency_manifest(preparation["artifacts"], preparation["edges"],
        expected_artifact_ids=[row["artifact_id"] for row in preparation["artifacts"]])
    build_inputs = {"expected_preparation_sha256": digest(preparation),
        "expected_manifest_sha256": manifest["manifest_sha256"],
        "required_dependency_ids": preparation["required_dependency_ids"], **arguments}
    return preparation, manifest, build_inputs


def test_full_replay_refuses_equal_ast_and_equal_text_from_a_different_physical_source(owner, fixtures, case):
    other, manifest, build_inputs = materialize_other_physical_source(fixtures)
    original = case["current_preparation"]
    old_unit = original["correspondence"]["source_scope"]["source_records"]["unit"]
    new_unit = other["correspondence"]["source_scope"]["source_records"]["unit"]
    assert other["ast_sha256"] == original["ast_sha256"]
    assert other["native_ast_sha256"] == original["native_ast_sha256"]
    assert original["correspondence"]["source_scope"]["source_records"]["source_occurrence"]["span_text"] == \
        other["correspondence"]["source_scope"]["source_records"]["source_occurrence"]["span_text"]
    assert old_unit["record_cid"] != new_unit["record_cid"]
    case["raw_inputs"][4:] = [wire(other), wire(manifest)]
    case["current_build_inputs"] = build_inputs
    seal_inputs(case)
    with pytest.raises(ValueError):
        prepare(owner, case)


def test_unsigned_definition_and_coverage_proposals_survive_binding_without_becoming_applicable(owner, fixtures, case):
    request = json.loads(case["raw_inputs"][1])
    declared_ref = {"artifact_id": "fixture:unverified-applicability-declaration", "sha256": "1" * 64}
    request["interpretation"].update(disposition="proposed_support", rationale="An unsigned authored proposal only.")
    request["meaning_unit"].update(coverage="partial", legal_as_of="2024-01-01",
                                  rationale="A declared civil date, not an authenticated signature clock.")
    request["coverage_decisions"][0].update(disposition="proposed_resolved",
        evidence_refs=[deepcopy(declared_ref)], rationale="Supporting bytes remain unverified by this bridge.")
    chosen = request["definition_decisions"][0]
    link = next(link for link in case["historical_evidence"]["links"]
                if link["request_link"]["target"] == chosen["target"])
    chosen.update(disposition="proposed_applicable", alternative_id=link["request_link"]["alternative_id"],
        link_sha256=digest(link), evidence_refs=[deepcopy(declared_ref)],
        rationale="An unsigned nomination is not a governing definition.")
    rebuild_retained_inputs(case, fixtures, request=request)
    report = prepare(owner, case)
    assert case["declaration"]["request"] == request
    assert case["declaration"]["governing_definition_use"] is None
    assert case["declaration"]["evidence_reference_status"] == "declared_not_verified"
    assert "fixture:unverified-applicability-declaration" in wire(report["declared_nested_evidence"]).decode()
    assert_unqualified(report)


def test_original_response_signatures_can_bind_bridge_bytes_without_reviewing_the_declaration(owner, fixtures, materialized, case, prepared):
    helper = fixtures["content"]
    source_helper = fixtures["norm"]
    signed = helper.signed_content(content, source_helper, materialized)
    bridge_bytes = wire(validate(owner, prepared, case))
    declaration_bytes = case["raw_inputs"][0]
    attachments = {
        "fixture:unsigned-content-declaration": declaration_bytes,
        "fixture:explicit-generation-binding": bridge_bytes,
    }
    signed["evidence_artifacts"].update(attachments)
    refs = [{"artifact_id": name, "sha256": sha(raw)} for name, raw in attachments.items()]
    for index in range(2):
        record = helper.current_record(signed, index)
        for answer in record["answers"]:
            answer["evidence_refs"] = deepcopy(refs)
        record["candidate_proposal"]["evidence_refs"] = deepcopy(refs)
        helper.replace_record(source_helper, signed, index, record)
    report = helper.assess(content, source_helper, signed)
    assert report["raw_norm_assessment"]["authenticated_evidence_count"] == 2
    assert report["counts"]["authenticated_typed_responses"] == 2
    for result in report["response_results"]:
        body = result["response_record"]
        assert all(answer["evidence_refs"] == refs for answer in body["answers"])
        definition = helper.answer_for(body, "definition_applicability")
        assert definition["disposition"] == definition["finding"]["status"] == "unresolved"
        assert definition["finding"]["governing_definition_use"] is None
    helper.assert_pending(report, source_helper)
    assert case["declaration"]["declaration_status"] == "unsigned_proposed_content"
    assert_unqualified(prepared)


def test_rehashed_duplicate_raw_keys_cannot_be_hidden_by_the_same_canonical_input(owner, case, monkeypatch):
    raw = case["raw_inputs"][4]
    parsed = json.loads(raw)
    duplicate = b'{"schema":' + wire(parsed["schema"]) + b"," + raw[1:]
    assert json.loads(duplicate) == parsed
    case["raw_inputs"][4] = duplicate
    seal_inputs(case)
    calls = []

    def forbidden(*args, **kwargs):
        calls.append("current source replay")
        raise AssertionError("duplicate JSON keys reached current source replay")

    monkeypatch.setattr(content, "build_norm_content_template_v1", forbidden)
    with pytest.raises(ValueError):
        prepare(owner, case)
    assert calls == []


@pytest.mark.parametrize("damage", ["authority_alias", "mask_alias", "selected_meaning"])
def test_rehashed_report_cannot_gain_authority_or_exploit_json_type_aliases(owner, case, prepared, damage):
    report = deepcopy(prepared)
    if damage == "authority_alias":
        report["authority"][next(iter(report["authority"]))] = 0
    elif damage == "mask_alias":
        report["training_mask"] = False
    else:
        report["accepted_interpretation"] = "fixture:unreviewed-meaning"
    with pytest.raises(ValueError):
        validate(owner, report, case)


@pytest.mark.parametrize("pin", [None, "", "0" * 64])
def test_saved_report_requires_an_independent_complete_report_pin(owner, case, prepared, pin):
    with pytest.raises(ValueError):
        owner.validate_norm_content_declaration_binding_v1(prepared, *case["raw_inputs"],
            expected_input_pins=case["expected_input_pins"],
            current_build_inputs=case["current_build_inputs"], expected_report_sha256=pin)


@pytest.mark.parametrize("target", ["caller", "detached"])
def test_binding_fences_complete_current_replay_inputs_after_real_template_replay(owner, case, monkeypatch, target):
    replay = content.build_norm_content_template_v1

    def mutating(*args, **kwargs):
        result = replay(*args, **kwargs)
        inputs = case["current_build_inputs"] if target == "caller" else kwargs
        inputs["correspondence_inputs"]["scope_replay_inputs"]["expected_raw_bytes"] += 1
        return result

    monkeypatch.setattr(content, "build_norm_content_template_v1", mutating)
    with pytest.raises(ValueError, match="changed"):
        prepare(owner, case)


@pytest.mark.parametrize("target", ["binding", "content", "declaration"])
def test_live_direct_owner_source_drift_refuses_binding_without_editing_files(owner, case, monkeypatch, target):
    module = {"binding": owner, "content": content, "declaration": declaration}[target]
    selected = Path(module.__file__).resolve()
    read_bytes = Path.read_bytes
    original = read_bytes(selected)

    def changed(path):
        return original + b"\n# Fictional observed drift; no source file is changed.\n" \
            if path.resolve() == selected else read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", changed)
    with pytest.raises(ValueError, match="changed"):
        prepare(owner, case)


def test_binding_fences_original_inputs_after_final_report_serialization(owner, case, monkeypatch):
    serialize = norm._wire
    calls = []

    def mutating(value):
        raw = serialize(value)
        if type(value) is dict and value.get("schema") == owner.SCHEMA:
            calls.append("binding serialized")
            case["current_build_inputs"]["correspondence_inputs"]["scope_replay_inputs"]["expected_raw_bytes"] += 1
        return raw

    monkeypatch.setattr(norm, "_wire", mutating)
    with pytest.raises(ValueError, match="changed"):
        prepare(owner, case)
    assert calls == ["binding serialized"]


def test_producer_source_is_checked_again_after_final_report_serialization(owner, case, monkeypatch):
    serialize = norm._wire
    read_bytes = Path.read_bytes
    selected = Path(owner.__file__).resolve()
    original = read_bytes(selected)
    serialized = False

    def serializing(value):
        nonlocal serialized
        raw = serialize(value)
        if type(value) is dict and value.get("schema") == owner.SCHEMA:
            serialized = True
        return raw

    def observed(path):
        return original + b"\n# Observed after serialization; source is never changed.\n" \
            if serialized and path.resolve() == selected else read_bytes(path)

    monkeypatch.setattr(norm, "_wire", serializing)
    monkeypatch.setattr(Path, "read_bytes", observed)
    with pytest.raises(ValueError, match="changed"):
        prepare(owner, case)
    assert serialized is True


def test_exact_input_byte_bound_refuses_before_current_replay_without_truncation(owner, case, monkeypatch):
    limits = dict(owner.INPUT_LIMITS)
    limits["current_preparation"] = len(case["raw_inputs"][4]) - 1
    monkeypatch.setattr(owner, "INPUT_LIMITS", limits)
    calls = []

    def forbidden(*args, **kwargs):
        calls.append("current source replay")
        raise AssertionError("overbound input reached current source replay")

    monkeypatch.setattr(content, "build_norm_content_template_v1", forbidden)
    with pytest.raises(ValueError, match="bound"):
        prepare(owner, case)
    assert calls == []


def test_complete_obligation_bound_refuses_without_dropping_any_pair(owner, case, monkeypatch):
    monkeypatch.setattr(owner, "MAX_OBLIGATIONS", len(case["historical_preparation"]["obligations"]) - 1)
    with pytest.raises(ValueError):
        owner._slot_pairs(case["historical_preparation"], case["current_preparation"])


def test_final_report_byte_bound_refuses_after_real_replay(owner, case, monkeypatch):
    monkeypatch.setattr(owner, "MAX_REPORT_BYTES", 1)
    with pytest.raises(ValueError, match="bound"):
        prepare(owner, case)


def test_rehashed_forged_historical_declaration_cannot_bypass_original_regeneration(owner, case, monkeypatch):
    forged = json.loads(case["raw_inputs"][0])
    forged["request"]["coverage_decisions"].pop()
    case["raw_inputs"][0] = wire(forged)
    seal_inputs(case)
    calls = []

    def forbidden(*args, **kwargs):
        calls.append("current source replay")
        raise AssertionError("forged historical declaration reached current replay")

    monkeypatch.setattr(content, "build_norm_content_template_v1", forbidden)
    with pytest.raises(ValueError):
        prepare(owner, case)
    assert calls == []


@pytest.mark.parametrize("damage", ["missing", "extra"])
def test_current_build_inputs_cannot_default_or_ignore_unknown_fields(owner, case, monkeypatch, damage):
    if damage == "missing": case["current_build_inputs"].pop("context_inputs")
    else: case["current_build_inputs"]["assume_compatible"] = True
    calls = []

    def forbidden(*args, **kwargs):
        calls.append("current source replay")
        raise AssertionError("malformed current build inputs reached current replay")

    monkeypatch.setattr(content, "build_norm_content_template_v1", forbidden)
    with pytest.raises(ValueError):
        prepare(owner, case)
    assert calls == []


def test_equivalent_authored_mapping_serializations_keep_distinct_raw_lengths_without_claiming_verification(owner, fixtures, case):
    current_raw = case["current_build_inputs"]["correspondence_inputs"]["mapping_request_raw"]
    mapping = json.loads(current_raw)
    historical_raw = (json.dumps(mapping, ensure_ascii=False, sort_keys=True, indent=2,
                                 allow_nan=False) + "\n").encode("utf-8")
    assert json.loads(historical_raw) == mapping
    assert len(historical_raw) != len(current_raw)
    assert sha(historical_raw) != sha(current_raw)
    historical = case["historical_preparation"]
    assert historical["correspondence"]["request"] == mapping
    historical_pins = historical["correspondence"]["input_pins"]
    historical_pins["mapping_request_raw_sha256"] = sha(historical_raw)
    historical_pins["mapping_request_raw_bytes"] = len(historical_raw)
    mapping_artifact = next(row for row in historical["artifacts"]
                            if row["artifact_id"] == "norm-input:mapping_request_raw_sha256")
    mapping_artifact["artifact_sha256"] = sha(historical_raw)
    case["historical_preparation"] = historical_generation(historical)
    case["historical_evidence"] = unsigned_definitions(fixtures, case["historical_preparation"])
    rebuild_retained_inputs(case, fixtures)
    original = deepcopy(case)

    report = prepare(owner, case)
    assert validate(owner, report, case) == report
    assert case == original
    old, new = report["historical_generation"], report["current_generation"]
    assert old["mapping_request_raw_sha256_declared"] == sha(historical_raw)
    assert old["mapping_request_raw_bytes_declared"] == len(historical_raw)
    assert new["mapping_request_raw_sha256"] == sha(current_raw)
    assert new["mapping_request_raw_bytes"] == len(current_raw)
    assert old["parsed_mapping_request_canonical_sha256"] == new["parsed_mapping_request_canonical_sha256"] == digest(mapping)
    assert old["mapping_request_raw_bytes_verified"] is False
    assert old["historical_owner_reexecution_performed"] is False
    assert new["complete_current_norm_replay_performed"] is True
    differences = {row["path"]: row for row in report["generation_differences"]}
    for field, left, right in (("mapping_request_raw_sha256", sha(historical_raw), sha(current_raw)),
                               ("mapping_request_raw_bytes", len(historical_raw), len(current_raw))):
        difference = differences["/correspondence/input_pins/" + field]
        assert difference["classification"] == "declared_mapping_raw_commitment_not_reconstructed"
        assert difference["historical_sha256"] == digest(left)
        assert difference["current_sha256"] == digest(right)
    assert report["counts"]["slot_pairs"] == len(case["historical_preparation"]["obligations"])
    assert_unqualified(report)


@pytest.mark.parametrize("damage", ["full_canonical_as_payload", "payload_as_full_canonical"])
def test_complete_manifest_custody_pin_and_embedded_payload_pin_cannot_be_interchanged(owner, case, damage):
    manifest = json.loads(case["raw_inputs"][5])
    complete_pin = case["expected_input_pins"]["dependency_manifest"]["canonical_sha256"]
    payload_pin = manifest["manifest_sha256"]
    assert complete_pin == digest(manifest)
    assert payload_pin == digest({key: value for key, value in manifest.items() if key != "manifest_sha256"})
    assert complete_pin != payload_pin
    assert case["current_build_inputs"]["expected_manifest_sha256"] == payload_pin
    if damage == "full_canonical_as_payload":
        case["current_build_inputs"]["expected_manifest_sha256"] = complete_pin
    else:
        case["expected_input_pins"]["dependency_manifest"]["canonical_sha256"] = payload_pin
    original = deepcopy(case)
    with pytest.raises(ValueError, match="manifest"):
        prepare(owner, case)
    assert case == original
