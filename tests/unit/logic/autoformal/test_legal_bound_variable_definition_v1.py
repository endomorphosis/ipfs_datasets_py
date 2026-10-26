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


# The explicit parent consumer reuses the qualified nomination fixture. Its
# generated conditional text remains uncompiled and every premise unverified.
@pytest.fixture(scope="module")
def parent_bound_helpers():
    return fixtures()


@pytest.fixture(scope="module")
def parent_bound_base(parent_bound_helpers, tmp_path_factory):
    helper = parent_bound_helpers
    definitions = helper.parent_nomination_helpers.__wrapped__()
    inputs = helper._parent_nomination_materialize(definitions,
        tmp_path_factory.mktemp("parent-bound-originals", numbered=False))
    companion = helper._parent_nomination_prepare(inputs)
    return {"inputs": inputs, "companion": companion,
            "companion_sha256": evidence.norm_definition_evidence_sha256(companion)}


def _parent_bound_declaration(data, *, link_index=0, mode="instance_only"):
    companion = data["companion"]
    link = companion["links"][link_index]
    context = link["typed_context"]
    relational = data["inputs"]["norm_preparation"]["correspondence"]["relational_fragment"]
    binder = next(row for row in relational["structural_mapping"]
                  if row["typed_path"] == context["binding"]["typed_path"])
    endpoint = next(row for row in companion["definitions"]
                    if row["alternative_id"] == link["request_link"]["alternative_id"])
    link_hash = evidence.norm_definition_evidence_sha256(link)
    return {"schema": owner.PARENT_REQUEST_SCHEMA, "profile": owner.PARENT_PROFILE,
        "companion_sha256": data["companion_sha256"], "link_sha256": link_hash,
        "alternative_id": endpoint["alternative_id"], "target": deepcopy(link["request_link"]["target"]),
        "binding": deepcopy(context["binding"]), "binder_target": deepcopy(binder),
        "argument": deepcopy(context["argument"]), "source_paths": deepcopy(link["request_link"]["source_paths"]),
        "definition_term_ref": deepcopy(link["definition_term_ref"]),
        "definition_ast_ref": deepcopy(link["definition_ast_ref"]),
        "carrier_map": deepcopy(owner.CARRIER_MAP), "evaluation_context": deepcopy(owner.EVALUATION_CONTEXT),
        "definition_assumption": {"kind": "explicit_unverified_parameter", "parameter": "hDefinition",
                                  "definition_ast_ref": deepcopy(link["definition_ast_ref"])},
        "mode": mode, "membership_assumption": None if mode == "instance_only" else {
            "kind": "explicit_unverified_parameter", "parameter": "hMembership",
            "link_sha256": link_hash, "definition_symbol": endpoint["candidate"]["term_record"]["symbol"],
            "carrier": "Entity"}}


def _parent_bound_arguments(data, request):
    raw = wire(request)
    return {"companion": data["companion"], "request_raw": raw,
        "expected_companion_sha256": data["companion_sha256"],
        "expected_request_sha256": sha(raw), "companion_inputs": data["inputs"]}


def _parent_bound_prepare(data, request=None, **overrides):
    request = _parent_bound_declaration(data) if request is None else request
    return owner.prepare_parent_bound_variable_definition_v1(**(_parent_bound_arguments(data, request) | overrides))


def _parent_bound_validate(data, request, report, **overrides):
    return owner.validate_parent_bound_variable_definition_v1(report,
        **(_parent_bound_arguments(data, request) | {
            "expected_report_sha256": owner.bound_variable_definition_sha256(report)} | overrides))


def _parent_bound_unqualified(report):
    assert report["schema"] == owner.PARENT_SCHEMA and report["profile"] == owner.PARENT_PROFILE
    assert report["authority"] and all(value is False for value in report["authority"].values())
    for field in ("semantic_mask", "consumer_mask", "training_mask", "evaluation_gold_mask"):
        assert type(report[field]) is int and report[field] == 0
    for field in ("native_ast_rewritten", "norm_interpretation_ready", "backend_executed", "lean_compilation_verified"):
        assert report[field] is False
    assert report["selected_interpretation"] is None and report["governing_definition_use"] is None
    assert report["authority"]["norm_witness_extracted"] is False
    assert report["authority"]["membership_assumption_verified"] is False
    assert report["external_complete_inputs_required"] is True


@pytest.mark.parametrize("mode", ["instance_only", "body_with_membership"])
def test_parent_bound_genuine_modes_preserve_exact_premises_and_save_uncompiled_outputs(
        parent_bound_base, tmp_path, mode):
    data = parent_bound_base
    request = _parent_bound_declaration(data, mode=mode)
    original_inputs = evidence.norm._parent_review_fingerprint(data)
    report = _parent_bound_prepare(data, request)
    assert _parent_bound_validate(data, request, report) == report
    assert evidence.norm._parent_review_fingerprint(data) == original_inputs
    assert report["companion"] == data["companion"]
    assert report["request"] == request
    assert report["selected_link"] == data["companion"]["links"][0]
    assert [row["alternative_id"] for row in report["definition_alternative_refs"]] == [
        row["alternative_id"] for row in data["companion"]["definitions"]]
    for ordinal, (ref, endpoint) in enumerate(zip(report["definition_alternative_refs"],
                                                data["companion"]["definitions"], strict=True)):
        assert ref["ordinal"] == ordinal and ref["preparation_sha256"] == endpoint["preparation_sha256"]
        assert ref["candidate_ref"] == {"record_cid": endpoint["candidate"]["record_cid"],
            "sha256": evidence.norm_definition_evidence_sha256(endpoint["candidate"])}
    assert [row["request_link"] for row in report["nomination_inventory"]] == [
        row["request_link"] for row in data["companion"]["links"]]
    original = data["inputs"]["norm_preparation"]
    relational = original["correspondence"]["relational_fragment"]
    assert report["original_norm"]["ast_sha256"] == evidence.norm.norm_review_sha256(relational["typed_expression"])
    assert report["original_norm"]["native_ast_sha256"] == evidence.norm.norm_review_sha256(relational["native_ast"])
    assert report["original_norm"]["source_identity"] == original["source_identity"]
    assert "scope_id" not in report["original_norm"]
    assert report["original_norm"]["unchanged"] is True
    binding = report["occurrence_binding"]
    for field in ("target", "binding", "binder_target", "argument", "source_paths"):
        assert binding[field] == request[field]
    assert binding["native_predicate"]["arguments"][request["argument"]["index"]] == binding["native_variable"]
    assert request["argument"]["role"] == "actor" and request["binding"]["name"] == "actor"
    assert "exact hDefinition entity" in report["lean_source"]
    assert report["conditional_theorem_statements"][0]["hypotheses"] == ["hDefinition : formula_0 i t"]
    if mode == "instance_only":
        assert len(report["conditional_theorems"]) == 1
        assert "theorem body_instance" not in report["lean_source"] and "hMembership" not in report["lean_source"]
    else:
        assert len(report["conditional_theorems"]) == 2
        assert "exact (hDefinition entity).mp hMembership" in report["lean_source"]
        assert report["conditional_theorem_statements"][1]["hypotheses"] == [
            "hDefinition : formula_0 i t", "hMembership : headAt i entity t"]
    assert all(statement["kernel_checked"] is False for statement in report["conditional_theorem_statements"])
    _parent_bound_unqualified(report)
    # Concrete owned test examples, not a new product writer or compiled corpus.
    raw = wire(report)
    examples = {"conditional-report.json": raw, "conditional-source.lean": report["lean_source"].encode("utf-8"),
                "conditional-request.json": wire(request)}
    for name, body in examples.items():
        path = tmp_path / name
        path.write_bytes(body)
        assert path.read_bytes() == body and sha(path.read_bytes()) == sha(body)
    assert json.loads((tmp_path / "conditional-report.json").read_bytes()) == report
    assert owner.bound_variable_definition_sha256(report) == sha(raw)


def test_parent_bound_repeated_variable_use_and_other_definition_keep_exact_occurrence_identity(parent_bound_base):
    first_request = _parent_bound_declaration(parent_bound_base)
    other_request = _parent_bound_declaration(parent_bound_base, link_index=3)
    report = _parent_bound_prepare(parent_bound_base, other_request)
    assert other_request["binding"] == first_request["binding"]
    assert other_request["target"]["typed_path"] != first_request["target"]["typed_path"]
    assert other_request["target"]["native_path"] != first_request["target"]["native_path"]
    assert other_request["alternative_id"] != first_request["alternative_id"]
    assert report["selected_link"] == parent_bound_base["companion"]["links"][3]
    assert report["occurrence_binding"]["native_predicate"]["name"] == "Approved"
    assert report["companion"]["definitions"] == parent_bound_base["companion"]["definitions"]
    assert [row["alternative_id"] for row in report["definition_alternative_refs"]] == [
        row["alternative_id"] for row in parent_bound_base["companion"]["definitions"]]
    _parent_bound_unqualified(report)


def test_parent_bound_existential_norm_preserves_its_quantifier_without_extracting_a_witness(
        parent_bound_helpers, parent_bound_base, tmp_path, monkeypatch):
    helper = parent_bound_helpers
    correspondence = helper.NORM.fixture
    relational = correspondence.relational_fixture
    def existential_request():
        builder = relational.Builder()
        action = builder.atom("Retain", "actor", "object")
        body = builder.binary("implies", builder.modal("P", action), builder.atom("Approved", "actor"))
        return relational.request_for(builder, body,
            [("Retain", ("actor", "object")), ("Approved", ("actor",))],
            [("actor", "exists"), ("object", "forall")])
    with monkeypatch.context() as patch:
        patch.setattr(correspondence, "authored_request", existential_request)
        inputs = helper._parent_nomination_materialize(helper.parent_nomination_helpers.__wrapped__(),
            tmp_path / "existential-originals", definitions=parent_bound_base["inputs"]["definitions"])
    companion = helper._parent_nomination_prepare(inputs)
    data = {"inputs": inputs, "companion": companion,
            "companion_sha256": evidence.norm_definition_evidence_sha256(companion)}
    original_ast = inputs["norm_preparation"]["correspondence"]["relational_fragment"]["native_ast"]
    assert original_ast["quantifier"]["value"] == "∃"
    report = _parent_bound_prepare(data)
    assert report["companion"]["norm_preparation"]["correspondence"]["relational_fragment"]["native_ast"] == original_ast
    assert "(entity : Entity)" in report["lean_source"]
    assert "Classical.choose" not in report["lean_source"] and "Exists.choose" not in report["lean_source"]
    assert report["authority"]["norm_witness_extracted"] is False
    _parent_bound_unqualified(report)


@pytest.mark.parametrize("pin", ["companion", "request", "report"])
def test_parent_bound_independent_full_pins_refuse_before_nomination_replay(parent_bound_base, monkeypatch, pin):
    request = _parent_bound_declaration(parent_bound_base)
    calls = []
    def denied(*args, **kwargs):
        calls.append("nomination")
        pytest.fail("independent full pin must refuse before genuine nomination replay")
    monkeypatch.setattr(evidence, "validate_parent_norm_definition_evidence_v1", denied)
    if pin == "report":
        with pytest.raises(ValueError):
            _parent_bound_validate(parent_bound_base, request, {}, expected_report_sha256="0" * 64)
    else:
        field = "expected_companion_sha256" if pin == "companion" else "expected_request_sha256"
        with pytest.raises(ValueError): _parent_bound_prepare(parent_bound_base, request, **{field: "0" * 64})
    assert calls == []


@pytest.mark.parametrize("damage", ["predicate-target", "binder-role-refs-carrier"])
def test_parent_bound_exact_target_binder_argument_whole_refs_and_carrier_are_not_retargetable(
        parent_bound_base, monkeypatch, damage):
    request = _parent_bound_declaration(parent_bound_base)
    calls = []
    def denied(*args, **kwargs):
        calls.append("nomination")
        pytest.fail("retargeted exact selection must refuse before nomination replay")
    monkeypatch.setattr(evidence, "validate_parent_norm_definition_evidence_v1", denied)
    if damage == "predicate-target":
        link = parent_bound_base["companion"]["links"][4]
        request.update(target=deepcopy(link["request_link"]["target"]),
            link_sha256=evidence.norm_definition_evidence_sha256(link))
        with pytest.raises(ValueError): _parent_bound_prepare(parent_bound_base, request)
    else:
        changes = [lambda row: row["binder_target"].update(binder_name="object"),
                   lambda row: row["argument"].update(role="object"),
                   lambda row: row["definition_term_ref"].update(sha256="0" * 64),
                   lambda row: row["definition_ast_ref"].update(sha256="0" * 64),
                   lambda row: row["carrier_map"].update(lean_carrier="Agent")]
        for change in changes:
            altered = deepcopy(request)
            change(altered)
            with pytest.raises(ValueError): _parent_bound_prepare(parent_bound_base, altered)
    assert calls == []


@pytest.mark.parametrize("damage", ["definition", "missing-membership", "foreign-membership"])
def test_parent_bound_definition_and_membership_are_explicit_unverified_matching_parameters(
        parent_bound_base, monkeypatch, damage):
    request = _parent_bound_declaration(parent_bound_base, mode="body_with_membership")
    if damage == "definition": request["definition_assumption"] = None
    elif damage == "missing-membership": request["membership_assumption"] = None
    else: request["membership_assumption"]["link_sha256"] = "0" * 64
    calls = []
    def denied(*args, **kwargs):
        calls.append("nomination")
        pytest.fail("a missing or foreign premise must refuse before nomination replay")
    monkeypatch.setattr(evidence, "validate_parent_norm_definition_evidence_v1", denied)
    with pytest.raises(ValueError): _parent_bound_prepare(parent_bound_base, request)
    assert calls == []


@pytest.mark.parametrize("damage", ["wrong-profile", "bounded-input"])
def test_parent_bound_profiles_and_finite_complete_input_preflight_preserve_legacy_defaults(
        parent_bound_base, monkeypatch, damage):
    request = _parent_bound_declaration(parent_bound_base)
    calls = []
    def denied(*args, **kwargs):
        calls.append("nomination")
        pytest.fail("malformed profile or bounded input must refuse before nomination replay")
    monkeypatch.setattr(evidence, "validate_parent_norm_definition_evidence_v1", denied)
    if damage == "wrong-profile":
        raw = wire(request)
        with pytest.raises(ValueError):
            owner.prepare_bound_variable_definition_v1(parent_bound_base["companion"], raw,
                expected_companion_sha256=parent_bound_base["companion_sha256"],
                expected_request_sha256=sha(raw), companion_inputs=parent_bound_base["inputs"])
        request.update(schema=owner.REQUEST_SCHEMA, profile=owner.PROFILE)
        with pytest.raises(ValueError): _parent_bound_prepare(parent_bound_base, request)
    else:
        raw = b"x" * (owner.MAX_REQUEST_BYTES + 1)
        with pytest.raises(ValueError):
            _parent_bound_prepare(parent_bound_base, request, request_raw=raw, expected_request_sha256=sha(raw))
        inputs = deepcopy(parent_bound_base["inputs"])
        inputs["definitions"].append(inputs["definitions"])
        with pytest.raises(ValueError): _parent_bound_prepare(parent_bound_base, request, companion_inputs=inputs)
    assert calls == []


@pytest.mark.parametrize("returned", ["opening", "closing", "parsed-native", "route-native"])
def test_parent_bound_actual_nomination_returns_remain_held_after_final_genuine_serialization(
        parent_bound_base, monkeypatch, returned):
    actual, final, native = [], [], {}
    real_validate = evidence.validate_parent_norm_definition_evidence_v1
    real_finish = owner._parent_bound_serialized_fence
    real_render = owner._render
    def retained(*args, **kwargs):
        result = real_validate(*args, **kwargs)
        actual.append(result)
        return result
    def retained_render(*args, **kwargs):
        real_hold = kwargs['hold']
        def observe(label, value):
            result = real_hold(label, value)
            native[label] = value
            return result
        return real_render(*args, **(kwargs | {'hold': observe}))
    def checked_then_change(report, expected):
        result = real_finish(report, expected)
        final.append("checked")
        if len(final) == 2:
            if returned in ('opening', 'closing'):
                actual[0 if returned == 'opening' else -1]['training_mask'] = False
            else:
                target = 'donor_original_native' if returned == 'parsed-native' else 'native_fragment'
                native[target]['lean_body'] += '\n-- late actual render return mutation\n'
        return result
    monkeypatch.setattr(evidence, "validate_parent_norm_definition_evidence_v1", retained)
    monkeypatch.setattr(owner, '_render', retained_render)
    monkeypatch.setattr(owner, "_parent_bound_serialized_fence", checked_then_change)
    with pytest.raises(ValueError): _parent_bound_prepare(parent_bound_base)
    assert len(actual) == 2 and len(final) == 2


@pytest.mark.parametrize("location", ["caller", "detached", "parsed-request"])
def test_parent_bound_caller_and_actual_detached_inputs_remain_fenced_after_final_callback(
        parent_bound_base, monkeypatch, location):
    data = deepcopy(parent_bound_base)
    actual, final, parsed = [], [], []
    real_validate = evidence.validate_parent_norm_definition_evidence_v1
    real_finish = owner._parent_bound_serialized_fence
    real_parse = owner._parse
    def retained(*args, **kwargs):
        result = real_validate(*args, **kwargs)
        actual.append(kwargs["norm_inputs"])
        return result
    def retained_parse(*args, **kwargs):
        result = real_parse(*args, **kwargs)
        if kwargs.get('parent') is True:
            parsed.append(result)
        return result
    def checked_then_change(report, expected):
        result = real_finish(report, expected)
        final.append("checked")
        if len(final) == 2:
            if location == 'parsed-request': parsed[0]['argument']['role'] = 'object'
            else:
                target = data['inputs']['norm_inputs'] if location == 'caller' else actual[0]
                target['correspondence']['retained_unresolved'].append({'late': True})
        return result
    monkeypatch.setattr(evidence, "validate_parent_norm_definition_evidence_v1", retained)
    monkeypatch.setattr(owner, '_parse', retained_parse)
    monkeypatch.setattr(owner, "_parent_bound_serialized_fence", checked_then_change)
    with pytest.raises(ValueError): _parent_bound_prepare(data)
    assert len(actual) == 2 and len(final) == 2 and parsed


@pytest.mark.parametrize("endpoint", ["norm", "definition"])
def test_parent_bound_original_physical_parent_bytes_survive_last_serialization_guard(
        parent_bound_helpers, tmp_path, monkeypatch, endpoint):
    helper = parent_bound_helpers
    inputs = helper._parent_nomination_materialize(helper.parent_nomination_helpers.__wrapped__(),
        tmp_path / "physical-originals")
    companion = helper._parent_nomination_prepare(inputs)
    data = {"inputs": inputs, "companion": companion,
            "companion_sha256": evidence.norm_definition_evidence_sha256(companion)}
    path = helper._parent_nomination_parent_path(inputs, endpoint)
    original = path.read_bytes()
    real = owner._parent_bound_serialized_fence
    final = []
    def checked_then_change(report, expected):
        result = real(report, expected)
        final.append("checked")
        if len(final) == 2: path.write_bytes(original + b"\nlate parent conditional input mutation\n")
        return result
    monkeypatch.setattr(owner, "_parent_bound_serialized_fence", checked_then_change)
    with pytest.raises(ValueError): _parent_bound_prepare(data)
    assert len(final) == 2 and path.read_bytes() != original


def test_parent_bound_private_producer_remains_fenced_after_final_serialization(
        parent_bound_base, tmp_path, monkeypatch):
    original_path = Path(owner.__file__)
    original = original_path.read_bytes()
    private = tmp_path / original_path.name
    private.write_bytes(original)
    monkeypatch.setattr(owner, "__file__", str(private))
    monkeypatch.setattr(owner, "_SELF_PATH", private)
    monkeypatch.setattr(owner, "_DIRECT_PINS", {str(private): sha(original),
        str(owner._EVIDENCE_PATH): sha(Path(owner._EVIDENCE_PATH).read_bytes())})
    monkeypatch.setattr(owner, "_PARENT_BOUND_PINS", None)
    real = owner._parent_bound_serialized_fence
    final = []
    def checked_then_change(report, expected):
        result = real(report, expected)
        final.append("checked")
        if len(final) == 2: private.write_bytes(original + b"\n# late private conditional producer mutation\n")
        return result
    monkeypatch.setattr(owner, "_parent_bound_serialized_fence", checked_then_change)
    with pytest.raises(ValueError): _parent_bound_prepare(parent_bound_base)
    assert len(final) == 2 and private.read_bytes() != original
    assert original_path.read_bytes() == original


def test_parent_bound_actual_output_cannot_change_after_second_genuine_serialization(parent_bound_base, monkeypatch):
    real = owner._parent_bound_serialized_fence
    final = []
    def checked_then_change(report, expected):
        result = real(report, expected)
        final.append("checked")
        if len(final) == 2: report["training_mask"] = False
        return result
    monkeypatch.setattr(owner, "_parent_bound_serialized_fence", checked_then_change)
    with pytest.raises(ValueError): _parent_bound_prepare(parent_bound_base)
    assert len(final) == 2


def test_parent_bound_rehashed_report_cannot_verify_membership_governing_use_or_zero_mask_types(parent_bound_base):
    request = _parent_bound_declaration(parent_bound_base)
    report = _parent_bound_prepare(parent_bound_base, request)
    for damage in ("membership", "boolean-mask"):
        offered = deepcopy(report)
        if damage == "membership": offered["authority"]["membership_assumption_verified"] = True
        else: offered["training_mask"] = False
        with pytest.raises(ValueError): _parent_bound_validate(parent_bound_base, request, offered)



def test_parent_bound_renderer_term_callback_is_rechecked_after_second_genuine_serialization(
        parent_bound_base, monkeypatch):
    emitter, _ = owner._owners()
    original_term = emitter.FormulaRenderer.term
    original_source = Path(emitter.__file__).read_bytes()
    real_finish = owner._parent_bound_serialized_fence
    final = []

    def changed_term(self, *args, **kwargs):
        return original_term(self, *args, **kwargs)

    def checked_then_change(report, expected):
        result = real_finish(report, expected)
        final.append("checked")
        if len(final) == 2:
            monkeypatch.setattr(emitter.FormulaRenderer, "term", changed_term)
        return result

    monkeypatch.setattr(owner, "_parent_bound_serialized_fence", checked_then_change)
    with pytest.raises(ValueError, match="parent bound replay, renderer or custody callbacks changed"):
        _parent_bound_prepare(parent_bound_base)
    assert len(final) == 2
    assert emitter.FormulaRenderer.term is changed_term
    assert Path(emitter.__file__).read_bytes() == original_source
