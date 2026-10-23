"""Conditional definition instances do not establish category membership.

Every source, interpretation, and nomination is fictional. Positive cases replay
the complete upstream evidence; generated Lean text is never compiled here.
"""

from copy import deepcopy
import hashlib
import importlib.util
import itertools
import json
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.autoformal import legal_bound_variable_definition_v1 as owner
from ipfs_datasets_py.logic.autoformal import legal_norm_definition_evidence_v1 as evidence


def wire(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def fixtures():
    spec = importlib.util.spec_from_file_location(
        "authored_bound_variable_definition_fixture",
        Path(__file__).with_name("test_legal_norm_definition_evidence_v1.py"))
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def declaration(data, *, link_index=0, mode="instance_only"):
    report = data["companion"]
    link = report["links"][link_index]
    relational = data["inputs"]["norm_preparation"]["correspondence"]["relational_fragment"]
    binding = link["typed_context"]["binding"]
    binder = next(row for row in relational["structural_mapping"]
                  if row["typed_path"] == binding["typed_path"])
    endpoint = next(row for row in report["definitions"]
                    if row["alternative_id"] == link["request_link"]["alternative_id"])
    link_pin = evidence.norm_definition_evidence_sha256(link)
    return {"schema": owner.REQUEST_SCHEMA, "profile": owner.PROFILE,
        "companion_sha256": data["companion_sha256"], "link_sha256": link_pin,
        "alternative_id": endpoint["alternative_id"], "target": deepcopy(link["request_link"]["target"]),
        "binding": deepcopy(binding), "binder_target": deepcopy(binder),
        "argument": deepcopy(link["typed_context"]["argument"]),
        "source_paths": deepcopy(link["request_link"]["source_paths"]),
        "definition_term_ref": deepcopy(link["definition_term_ref"]),
        "definition_ast_ref": deepcopy(link["definition_ast_ref"]),
        "carrier_map": deepcopy(owner.CARRIER_MAP), "evaluation_context": deepcopy(owner.EVALUATION_CONTEXT),
        "definition_assumption": {"kind": "explicit_unverified_parameter", "parameter": "hDefinition",
                                  "definition_ast_ref": deepcopy(link["definition_ast_ref"])},
        "mode": mode,
        "membership_assumption": None if mode == "instance_only" else {
            "kind": "explicit_unverified_parameter", "parameter": "hMembership",
            "link_sha256": link_pin, "definition_symbol": endpoint["term_record"]["symbol"],
            "carrier": "Entity"}}


def prepare(data, request, **overrides):
    raw = wire(request)
    return owner.prepare_bound_variable_definition_v1(data["companion"], raw,
        **{"expected_companion_sha256": data["companion_sha256"],
           "expected_request_sha256": sha(raw), "companion_inputs": data["inputs"], **overrides})


def validate(data, request, report, **overrides):
    raw = wire(request)
    return owner.validate_bound_variable_definition_v1(report, data["companion"], raw,
        **{"expected_report_sha256": owner.bound_variable_definition_sha256(report),
           "expected_companion_sha256": data["companion_sha256"],
           "expected_request_sha256": sha(raw), "companion_inputs": data["inputs"], **overrides})


@pytest.fixture(scope="module")
def baseline():
    helper = fixtures()
    inputs = helper.build_case()
    companion = helper.prepare(inputs)
    data = {"inputs": inputs, "companion": companion,
            "companion_sha256": evidence.norm_definition_evidence_sha256(companion)}
    data["request"] = declaration(data)
    original_norm = wire(inputs["norm_preparation"])
    original_companion = wire(companion)
    data["report"] = prepare(data, data["request"])
    assert wire(inputs["norm_preparation"]) == original_norm
    assert wire(companion) == original_companion
    return data


@pytest.fixture(scope="module")
def membership_case(baseline):
    request = declaration(baseline, mode="body_with_membership")
    return request, prepare(baseline, request)


@pytest.fixture(scope="module")
def alternate_case(baseline):
    request = declaration(baseline, link_index=3)
    return request, prepare(baseline, request)


def no_authority(report):
    assert all(value is False for value in report["authority"].values())
    for field in ("native_ast_rewritten", "norm_interpretation_ready", "backend_executed", "lean_compilation_verified"):
        assert report[field] is False
    assert report["selected_interpretation"] is None and report["governing_definition_use"] is None
    assert type(report["training_mask"]) is int and report["training_mask"] == 0
    assert type(report["evaluation_gold_mask"]) is int and report["evaluation_gold_mask"] == 0
    assert report["external_complete_inputs_required"] is True


def forbid_evidence_replay(monkeypatch):
    def unexpected(*args, **kwargs):
        pytest.fail("invalid request reached expensive evidence replay")
    monkeypatch.setattr(evidence, "validate_norm_definition_evidence_v1", unexpected)


def test_conditional_instance_replays_complete_original_evidence(baseline, monkeypatch):
    original = evidence.validate_norm_definition_evidence_v1
    calls = []

    def traced(companion, *args, **kwargs):
        calls.append(kwargs["expected_report_sha256"])
        return original(companion, *args, **kwargs)

    monkeypatch.setattr(evidence, "validate_norm_definition_evidence_v1", traced)
    report = baseline["report"]
    assert validate(baseline, baseline["request"], report) == report
    assert calls == [baseline["companion_sha256"]]
    assert report["request"] == baseline["request"]
    assert report["selected_link"] == baseline["companion"]["links"][0]
    no_authority(report)


def test_target_binder_role_and_native_argument_are_preserved_without_norm_rewrite(baseline):
    report, request = baseline["report"], baseline["request"]
    binding = report["occurrence_binding"]
    for field in ("target", "binding", "binder_target", "argument", "source_paths"):
        assert binding[field] == request[field]
    assert binding["typed_node"]["symbol"] == binding["binding"]["name"] == "actor"
    assert binding["native_variable"]["name"] == "actor"
    assert binding["native_predicate"]["name"] == "Retain"
    assert binding["native_predicate"]["arguments"][binding["argument"]["index"]] == binding["native_variable"]
    assert binding["source_rows"] == baseline["companion"]["links"][0]["source_rows"]
    original = report["original_norm"]
    companion = baseline["companion"]
    for field, original_field in (("preparation_sha256", "norm_preparation_sha256"),
        ("correspondence_sha256", "norm_correspondence_sha256"), ("ast_sha256", "norm_ast_sha256"),
        ("native_ast_sha256", "norm_native_ast_sha256"), ("scope_id", "norm_scope_id")):
        assert original[field] == companion[original_field]
    assert original["unchanged"] is True
    assert report["definition_alternatives"] == companion["definitions"]
    assert [row["request_link"] for row in report["nomination_inventory"]] == [row["request_link"] for row in companion["links"]]
    no_authority(report)


def test_second_same_spelling_occurrence_and_competing_definition_remain_distinct(baseline, alternate_case):
    request, report = alternate_case
    first = baseline["report"]
    assert report["selected_link"] == baseline["companion"]["links"][3]
    assert report["occurrence_binding"]["native_variable"]["name"] == "actor"
    assert report["occurrence_binding"]["native_predicate"]["name"] == "Approved"
    assert request["target"]["native_path"] != baseline["request"]["target"]["native_path"]
    assert request["target"]["typed_path"] != baseline["request"]["target"]["typed_path"]
    assert request["binding"] == baseline["request"]["binding"]
    assert request["alternative_id"] != baseline["request"]["alternative_id"]
    assert report["definition_native_ast"] != first["definition_native_ast"]
    assert report["original_norm"] == first["original_norm"]
    assert report["definition_alternatives"] == first["definition_alternatives"]
    no_authority(report)


@pytest.mark.parametrize("pin", ["expected_companion_sha256", "expected_request_sha256"])
def test_independent_input_pins_refuse_before_evidence_replay(baseline, monkeypatch, pin):
    forbid_evidence_replay(monkeypatch)
    with pytest.raises(ValueError):
        prepare(baseline, baseline["request"], **{pin: "0" * 64})


def test_changed_original_definition_source_is_not_accepted_under_old_companion(baseline):
    inputs = deepcopy(baseline["inputs"])
    inputs["definitions"][0]["correspondence_inputs"]["candidate_inputs"]["raw_html"] += b"<!-- changed source -->"
    with pytest.raises(ValueError):
        prepare(baseline, baseline["request"], companion_inputs=inputs)


@pytest.mark.parametrize("damage", ["alternative", "link_pin", "binding", "binder_target", "role",
    "boolean_argument_index", "native_path", "source_paths", "carrier", "native_sort", "evaluation_time"])
def test_exact_occurrence_and_explicit_semantic_profile_cannot_be_retargeted(baseline, monkeypatch, damage):
    request = deepcopy(baseline["request"])
    if damage == "alternative":
        request["alternative_id"] = baseline["companion"]["definitions"][1]["alternative_id"]
    elif damage == "link_pin":
        request["link_sha256"] = "0" * 64
    elif damage == "binding":
        request["binding"]["name"] = "object"
    elif damage == "binder_target":
        request["binder_target"]["native_path"] = "/formula/variable"
    elif damage == "role":
        request["argument"]["role"] = "object"
    elif damage == "boolean_argument_index":
        assert request["argument"]["index"] == 0
        request["argument"]["index"] = False
    elif damage == "native_path":
        request["target"]["native_path"] = baseline["companion"]["links"][3]["request_link"]["target"]["native_path"]
    elif damage == "source_paths":
        request["source_paths"] = ["/occurrences/3/anchor"]
    elif damage == "carrier":
        request["carrier_map"]["lean_carrier"] = "Agent"
    elif damage == "native_sort":
        request["carrier_map"]["native_sort"] = "Entity"
    else:
        request["evaluation_context"]["time"] = "all_unobserved_future_times"
    forbid_evidence_replay(monkeypatch)
    with pytest.raises(ValueError):
        prepare(baseline, request)


@pytest.mark.parametrize("damage", ["missing", "foreign_link", "wrong_symbol", "unrequested_membership"])
def test_membership_is_an_explicit_occurrence_bound_parameter(baseline, monkeypatch, damage):
    request = declaration(baseline, mode="body_with_membership")
    if damage == "missing":
        request["membership_assumption"] = None
    elif damage == "foreign_link":
        request["membership_assumption"]["link_sha256"] = evidence.norm_definition_evidence_sha256(baseline["companion"]["links"][3])
    elif damage == "wrong_symbol":
        request["membership_assumption"]["definition_symbol"] = "ForeignDefinition"
    else:
        request["mode"] = "instance_only"
    forbid_evidence_replay(monkeypatch)
    with pytest.raises(ValueError):
        prepare(baseline, request)


@pytest.mark.parametrize("damage", ["extra_field", "duplicate_json", "oversize"])
def test_closed_bounded_request_refuses_before_evidence_replay(baseline, monkeypatch, damage):
    request = deepcopy(baseline["request"])
    if damage == "extra_field":
        request["accepted"] = True
        raw = wire(request)
    elif damage == "duplicate_json":
        raw = b'{"schema":"first","schema":"second"}'
    else:
        raw = wire(request)
        monkeypatch.setattr(owner, "MAX_REQUEST_BYTES", len(raw) - 1)
    forbid_evidence_replay(monkeypatch)
    with pytest.raises(ValueError):
        owner.prepare_bound_variable_definition_v1(baseline["companion"], raw,
            expected_companion_sha256=baseline["companion_sha256"],
            expected_request_sha256=sha(raw), companion_inputs=baseline["inputs"])


def test_body_requires_membership_and_neither_mode_asserts_actual_membership(baseline, membership_case):
    request, report = membership_case
    instance = baseline["report"]
    assert instance["conditional_theorems"] == ["LegalBoundVariableDefinition.definition_instance"]
    assert "theorem body_instance" not in instance["lean_source"]
    assert "hMembership" not in instance["lean_source"]
    assert "exact hDefinition entity" in instance["lean_source"]
    assert report["conditional_theorems"] == instance["conditional_theorems"] + [
        "LegalBoundVariableDefinition.body_instance"]
    assert "(hMembership : headAt i entity t) : bodyAt i entity t" in report["lean_source"]
    assert "exact (hDefinition entity).mp hMembership" in report["lean_source"]
    assert request["membership_assumption"]["kind"] == "explicit_unverified_parameter"
    assert report["conditional_theorem_statements"][1]["hypotheses"] == [
        "hDefinition : formula_0 i t", "hMembership : headAt i entity t"]
    for item in report["conditional_theorem_statements"]:
        assert item["kernel_checked"] is False
        assert item["status"] == "generated_under_explicit_unverified_hypotheses"
    for field in ("original_norm", "definition_native_ast", "head_native_ast", "body_native_ast",
                  "selected_link", "definition_alternatives", "nomination_inventory"):
        assert report[field] == instance[field]
    no_authority(instance)
    no_authority(report)


def test_finite_singleton_witness_definition_alone_does_not_establish_membership(baseline):
    """Four fictional valuations illustrate the premise gap, not legal validity."""
    report = baseline["report"]
    head, body = report["head_native_ast"], report["body_native_ast"]
    assert head["node_type"] == body["node_type"] == "Predicate"
    assert head["name"] != body["name"]
    assert report["definition_native_ast"]["formula"]["operator"]["value"] == "↔"
    assert report["definition_native_ast"]["formula"]["left"] == head
    assert report["definition_native_ast"]["formula"]["right"] == body
    valuations = []
    for head_value, body_value in itertools.product((False, True), repeat=2):
        definition = head_value == body_value
        valuations.append((definition, head_value, body_value))
        if definition and head_value:
            assert body_value
    assert (True, False, False) in valuations
    assert (True, True, True) in valuations
    assert report["authority"]["membership_assumption_verified"] is False
    assert report["authority"]["norm_witness_extracted"] is False


def test_retained_fictional_conditional_outputs(baseline, membership_case, tmp_path):
    """Retain already prepared bytes; complete replay inputs remain in the fixture."""
    request, membership = membership_case
    documents = {"request-instance.json": baseline["request"],
                 "request-membership.json": request, "evidence.json": baseline["companion"],
                 "instance.json": baseline["report"], "membership.json": membership}
    for name, value in documents.items():
        raw = wire(value)
        (tmp_path / name).write_bytes(raw)
        assert json.loads((tmp_path / name).read_bytes()) == value
    for name, report in (("instance.lean", baseline["report"]), ("membership.lean", membership)):
        raw = report["lean_source"].encode("utf-8")
        (tmp_path / name).write_bytes(raw)
        assert (tmp_path / name).read_bytes() == raw
    assert sha((tmp_path / "evidence.json").read_bytes()) == baseline["companion_sha256"]
    assert sha((tmp_path / "request-instance.json").read_bytes()) == baseline["report"]["request_sha256"]
    assert sha((tmp_path / "request-membership.json").read_bytes()) == membership["request_sha256"]


@pytest.mark.parametrize("binder_name", ["v0", "entity", "hDefinition"])
def test_native_only_renderer_avoids_binder_capture_and_preserves_symbols(baseline, binder_name):
    """Synthetic alpha-renaming tests rendering only, never source qualification."""
    original = baseline["report"]
    ast = deepcopy(original["definition_native_ast"])
    old_name = ast["variable"]["name"]

    def rename(node):
        if isinstance(node, dict):
            if node.get("node_type") == "Variable" and node.get("name") == old_name:
                node["name"] = binder_name
            for value in node.values():
                rename(value)
        elif isinstance(node, list):
            for value in node:
                rename(value)

    rename(ast)
    emitter, _ = owner._owners()
    native = {"lean_body": "def formula_0 {Entity Agent : Type} (i : Interpretation Entity Agent) : Nat → Prop := "
              + emitter.FormulaRenderer().formula(ast)}
    head, body = ast["formula"]["left"], ast["formula"]["right"]
    rendering, source, theorems = owner._render_conditionals(
        native, ast, head, body, "body_with_membership", emitter)
    assert rendering["environment"] == {binder_name: "entity"}
    assert rendering["head_expression"] == original["rendering"]["head_expression"]
    assert rendering["body_expression"] == original["rendering"]["body_expression"]
    for predicate in (head, body):
        assert len(predicate["name"]) == 65
        assert predicate["name"] in source
    assert "exact (hDefinition entity).mp hMembership" in source
    assert theorems == ["LegalBoundVariableDefinition.definition_instance", "LegalBoundVariableDefinition.body_instance"]


def test_rehashed_report_cannot_promote_unverified_membership(baseline):
    forged = deepcopy(baseline["report"])
    forged["authority"]["membership_assumption_verified"] = True
    with pytest.raises(ValueError):
        validate(baseline, baseline["request"], forged)


def test_stale_independent_report_pin_refuses_before_evidence_replay(baseline, monkeypatch):
    forbid_evidence_replay(monkeypatch)
    with pytest.raises(ValueError):
        validate(baseline, baseline["request"], baseline["report"], expected_report_sha256="0" * 64)
