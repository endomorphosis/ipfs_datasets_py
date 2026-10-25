"""Exact fictional norm/definition custody never resolves a legal meaning.

Successful construction, validation, and export use the complete existing
norm-definition replay. Cheap projection refusal tests never replace a positive
operation with a mocked upstream result.
"""

from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.autoformal import corpus_contracts as contracts
from ipfs_datasets_py.logic.autoformal import corpus_graph
from ipfs_datasets_py.logic.autoformal import corpus_norm_definition_adapter as owner
from ipfs_datasets_py.logic.autoformal import legal_norm_definition_evidence_v1 as evidence
from ipfs_datasets_py.utils.cid_utils import canonical_dag_json_bytes


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def fixture_helper():
    spec = importlib.util.spec_from_file_location(
        "authored_norm_definition_graph_fixture",
        Path(__file__).with_name("test_legal_norm_definition_evidence_v1.py"))
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def baseline():
    helper = fixture_helper()
    inputs = helper.build_case()
    report = helper.prepare(inputs)
    pin = evidence.norm_definition_evidence_sha256(report)
    record = owner.build_norm_definition_graph_v1(report, expected_report_sha256=pin, **inputs)
    return {"inputs": inputs, "report": report, "record": record, "report_sha256": pin,
            "graph_sha256": owner.norm_definition_graph_sha256(record)}


def validate(baseline, record=None, **overrides):
    record = baseline["record"] if record is None else record
    arguments = {"expected_graph_sha256": owner.norm_definition_graph_sha256(record),
                 "expected_report_sha256": baseline["report_sha256"], **baseline["inputs"], **overrides}
    return owner.validate_norm_definition_graph_v1(record, baseline["report"], **arguments)


def reseal(record):
    return contracts.seal_record({key: value for key, value in record.items()
                                  if key not in {"record_cid", "cid_scope"}})


def forbid_upstream_replay(monkeypatch):
    def unexpected(*args, **kwargs):
        pytest.fail("invalid projection reached expensive upstream replay")
    monkeypatch.setattr(evidence, "validate_norm_definition_evidence_v1", unexpected)


def test_full_upstream_replay_is_required_for_candidate_graph_validation(baseline, monkeypatch):
    original = evidence.validate_norm_definition_evidence_v1
    observed = []

    def traced(report, *args, **kwargs):
        observed.append((evidence.norm_definition_evidence_sha256(report), kwargs["expected_report_sha256"]))
        return original(report, *args, **kwargs)

    monkeypatch.setattr(evidence, "validate_norm_definition_evidence_v1", traced)
    before = canonical_dag_json_bytes(baseline["record"])
    assert validate(baseline) == baseline["record"]
    assert observed == [(baseline["report_sha256"], baseline["report_sha256"])]
    assert canonical_dag_json_bytes(baseline["record"]) == before
    assert corpus_graph.validate_graph_snapshot(baseline["record"]["graph"]) == baseline["record"]["graph"]


def test_same_spelling_variable_uses_keep_exact_binder_argument_and_source_evidence(baseline):
    record, report = baseline["record"], baseline["report"]
    uses = record["use_records"]
    assert len(uses) == 2
    assert {use["typed_node"]["symbol"] for use in uses} == {"actor"}
    assert len({use["target"]["typed_path"] for use in uses}) == 2
    assert len({use["record_cid"] for use in uses}) == 2
    assert [use["ordinal"] for use in uses] == [0, 1]
    for use in uses:
        original = next(link for link in report["links"]
                        if link["request_link"]["target"] == use["target"])
        assert use["typed_context"] == original["typed_context"]
        assert use["typed_context"]["binding"]["name"] == "actor"
        assert use["typed_context"]["argument"]["role"] == "actor"
        assert use["typed_node"] == original["typed_node"]
        assert use["typed_row"] == original["typed_row"]
        assert use["source_paths"] == original["request_link"]["source_paths"]
        assert use["source_rows"] == original["source_rows"]
        assert use["norm_source_target"] == original["norm_source_target"]
        assert use["norm_record_cid"] == record["norm_record"]["record_cid"]


def test_every_competing_alternative_and_ordered_nomination_is_retained(baseline):
    record, report = baseline["record"], baseline["report"]
    alternatives = record["definition_records"]
    assert [row["alternative_id"] for row in alternatives] == [row["alternative_id"] for row in report["definitions"]]
    assert [row["ordinal"] for row in alternatives] == [0, 1]
    assert record["counts"]["alternatives"] == 2
    assert record["counts"]["typed_uses"] == 2
    assert record["counts"]["nominations"] == 4
    assert record["counts"]["source_references"] == len(record["source_records"])
    for offered, original in zip(alternatives, report["definitions"], strict=True):
        assert offered["endpoint_ref"]["sha256"] == evidence.norm_definition_evidence_sha256(original)
        assert offered["candidate_pin"] == original["candidate_pin"]
        assert offered["source_identity"] == original["source_identity"]
        assert offered["original_assessment_sha256"] == original["review_evidence"]["assessment_sha256"]
        assert offered["original_review_covers_projection"] is False
    by_alternative = {row["alternative_id"]: row for row in alternatives}
    by_use = {row["record_cid"]: row for row in record["use_records"]}
    for index, (nomination, original) in enumerate(zip(record["nomination_records"], report["links"], strict=True)):
        assert nomination["ordinal"] == index
        assert nomination["request_link"] == original["request_link"]
        assert nomination["link_ref"]["sha256"] == evidence.norm_definition_evidence_sha256(original)
        assert nomination["definition_record_cid"] == by_alternative[original["request_link"]["alternative_id"]]["record_cid"]
        assert by_use[nomination["use_record_cid"]]["target"] == original["request_link"]["target"]
        for field in ("nomination", "definition_support", "definition_term_ref", "definition_ast_ref"):
            assert nomination[field] == original[field]
        assert nomination["governing_definition_use"] is None


def test_source_references_and_closed_endpoints_do_not_invent_physical_or_semantic_authority(baseline):
    record = baseline["record"]
    graph = record["graph"]
    assert {node["node_type"] for node in graph["nodes"]} == {"interpretation", "expression"}
    assert {edge["relation"] for edge in graph["edges"]} == {"DERIVED_FROM", "CITES", "HAS_SOURCE"}
    assert all(row["alternative_group_id"] is None and row["alternative_id"] is None for row in graph["nodes"])
    assert all(row["source_occurrence_cids"] == [] for row in graph["nodes"])
    node_ids = {row["record_cid"] for row in graph["nodes"]}
    assert all(edge["src_cid"] in node_ids and edge["dst_cid"] in node_ids for edge in graph["edges"])
    for source in record["source_records"]:
        assert source["custody_only"] is True
        assert source["reference_kind"] in {"norm_source_target", "required_definition_subject"}
        assert source["reference_sha256"] == evidence.norm_definition_evidence_sha256(source["reference"])
    assert record["authority"] == owner.FALSE_FLAGS
    assert all(value is False for value in record["authority"].values())
    assert record["view"] == graph["view"] == "candidate"
    assert record["selected_interpretation"] is None and record["governing_definition_use"] is None
    assert record["external_complete_inputs_required"] is True
    assert record["report_record"]["external_complete_inputs_required"] is True
    assert type(record["training_mask"]) is int and record["training_mask"] == 0
    assert type(record["evaluation_gold_mask"]) is int and record["evaluation_gold_mask"] == 0
    assert graph["admitted"] is graph["formalized"] is graph["source_semantics_verified"] is False


@pytest.mark.parametrize("pin", ["expected_graph_sha256", "expected_report_sha256"])
def test_independent_graph_and_evidence_pins_are_required_before_replay(baseline, monkeypatch, pin):
    forbid_upstream_replay(monkeypatch)
    with pytest.raises(ValueError):
        validate(baseline, **{pin: "0" * 64})


def test_changed_original_definition_bytes_fail_real_owner_replay(baseline):
    inputs = deepcopy(baseline["inputs"])
    inputs["definitions"][0]["correspondence_inputs"]["candidate_inputs"]["raw_html"] += b"<!--changed fixture source-->"
    with pytest.raises(ValueError):
        owner.build_norm_definition_graph_v1(baseline["report"],
            expected_report_sha256=baseline["report_sha256"], **inputs)


@pytest.mark.parametrize("collection", ["definition_records", "nomination_records"])
def test_original_alternative_and_nomination_order_cannot_be_resealed_away(baseline, monkeypatch, collection):
    record = deepcopy(baseline["record"])
    assert len(record[collection]) > 1
    record[collection].reverse()
    forbid_upstream_replay(monkeypatch)
    with pytest.raises(ValueError):
        validate(baseline, reseal(record))


def test_closed_custody_graph_with_dropped_links_still_fails_exact_projection(baseline, monkeypatch):
    record = deepcopy(baseline["record"])
    record["graph"] = corpus_graph.build_graph_snapshot(record["graph"]["nodes"], [])
    forbid_upstream_replay(monkeypatch)
    with pytest.raises(ValueError):
        validate(baseline, reseal(record))


def test_different_definition_cannot_replace_one_alternative_under_repaired_seal(baseline, monkeypatch):
    record = deepcopy(baseline["record"])
    assert len(record["definition_records"]) == 2
    record["definition_records"][0] = deepcopy(record["definition_records"][1])
    forbid_upstream_replay(monkeypatch)
    with pytest.raises(ValueError):
        validate(baseline, reseal(record))


@pytest.mark.parametrize("damage", ["source_path", "source_rows", "binder_context"])
def test_same_label_cannot_hide_discarded_or_retargeted_use_evidence(baseline, monkeypatch, damage):
    record = deepcopy(baseline["record"])
    use = record["use_records"][0]
    assert use["typed_node"]["symbol"] == "actor"
    if damage == "source_path":
        use["source_paths"] = ["/occurrences/1/anchor"]
    elif damage == "source_rows":
        use["source_rows"] = []
    else:
        del use["typed_context"]["binding"]
    record["use_records"][0] = reseal(use)
    forbid_upstream_replay(monkeypatch)
    with pytest.raises(ValueError):
        validate(baseline, reseal(record))


@pytest.mark.parametrize("damage", ["reference_kind", "reference_hash", "invented_endpoint"])
def test_resealed_unsupported_source_reference_or_endpoint_is_not_accepted(baseline, monkeypatch, damage):
    record = deepcopy(baseline["record"])
    source = record["source_records"][0]
    if damage == "reference_kind":
        source["reference_kind"] = "verified_physical_occurrence"
    elif damage == "reference_hash":
        source["reference_sha256"] = "0" * 64
    else:
        source["reference"] = {"approved_source": "invented"}
        source["reference_sha256"] = evidence.norm_definition_evidence_sha256(source["reference"])
    record["source_records"][0] = reseal(source)
    forbid_upstream_replay(monkeypatch)
    with pytest.raises(ValueError):
        validate(baseline, reseal(record))


@pytest.mark.parametrize("damage", ["semantic_authority", "integer_alias", "training", "governing_choice"])
def test_repaired_projection_seal_cannot_upgrade_authority(baseline, monkeypatch, damage):
    record = deepcopy(baseline["record"])
    if damage == "semantic_authority":
        record["authority"]["definition_applicability_verified"] = True
    elif damage == "integer_alias":
        record["authority"]["admitted"] = 0
    elif damage == "training":
        record["training_mask"] = 1
    else:
        record["governing_definition_use"] = record["definition_records"][0]["record_cid"]
    forbid_upstream_replay(monkeypatch)
    with pytest.raises(ValueError):
        validate(baseline, reseal(record))


def test_aggregate_input_budget_refuses_before_expensive_replay(baseline, monkeypatch):
    forbid_upstream_replay(monkeypatch)
    monkeypatch.setattr(evidence, "MAX_INPUT_NODES", 1)
    with pytest.raises(ValueError):
        owner.build_norm_definition_graph_v1(baseline["report"],
            expected_report_sha256=baseline["report_sha256"], **baseline["inputs"])


@pytest.mark.parametrize("damage", ["request_pin", "closed_replay_inputs"])
def test_original_input_preflight_precedes_operation_owner_loading(baseline, monkeypatch, damage):
    inputs = deepcopy(baseline["inputs"])
    if damage == "request_pin":
        inputs["expected_request_sha256"] = "0" * 64
    else:
        inputs["norm_inputs"]["invented_replay_option"] = True

    def unexpected():
        pytest.fail("malformed original replay input loaded operation owners")

    monkeypatch.setattr(evidence, "_owners", unexpected)
    with pytest.raises(ValueError):
        owner.build_norm_definition_graph_v1(baseline["report"],
            expected_report_sha256=baseline["report_sha256"], **inputs)


def test_graph_exchange_keeps_separately_retained_candidate_companion(baseline, tmp_path):
    pytest.importorskip("pyarrow")
    from ipfs_datasets_py.logic.autoformal.corpus_graph_exchange import load_graph_bundle

    record = baseline["record"]
    companion = tmp_path / "candidate-companion.json"
    raw = canonical_dag_json_bytes(record)
    companion.write_bytes(raw)
    # The graph and companion do not contain all original replay inputs. Retain
    # this fictional upstream report separately, with its independent byte pin.
    report_bytes = json.dumps(baseline["report"], ensure_ascii=False, sort_keys=True,
                              separators=(",", ":"), allow_nan=False).encode("utf-8")
    assert sha(report_bytes) == baseline["report_sha256"]
    evidence_path = tmp_path / "upstream-evidence.json"
    evidence_path.write_bytes(report_bytes)
    assert sha(evidence_path.read_bytes()) == baseline["report_sha256"]
    output = tmp_path / "graph-bundle"
    manifest = owner.export_norm_definition_graph_v1(record, output, baseline["report"],
        expected_graph_sha256=baseline["graph_sha256"],
        expected_report_sha256=baseline["report_sha256"], **baseline["inputs"])
    loaded = load_graph_bundle(output, expected_manifest_sha256=sha(canonical_dag_json_bytes(manifest)))
    retained = contracts.load_record_bytes(companion.read_bytes(), expected_sha256=sha(raw))
    assert retained == record
    assert loaded["snapshot"] == retained["graph"]
    assert manifest["external_references_verified"] is False
    assert not (output / "candidate.json").exists()


def test_graph_and_conditional_corpus_share_original_companion_without_promoting_nominations(
        baseline, monkeypatch):
    """One companion supplies graph custody and two conditional preparations."""
    import subprocess

    from ipfs_datasets_py.logic.autoformal import legal_corpus_definition_use_lake_v2 as lake

    def forbidden(*args, **kwargs):
        pytest.fail("graph/corpus preparation attempted a native probe or execution")

    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)
    spec = importlib.util.spec_from_file_location(
        "authored_graph_bound_definition_handoff_fixture",
        Path(__file__).with_name("test_legal_bound_variable_definition_v1.py"))
    assert spec is not None and spec.loader is not None
    bound_fixture = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bound_fixture)
    graph_record, companion, inputs = baseline["record"], baseline["report"], baseline["inputs"]
    data = {"companion": companion, "companion_sha256": baseline["report_sha256"], "inputs": inputs}
    graph_before = canonical_dag_json_bytes(graph_record)
    report_before, inputs_before = deepcopy(companion), deepcopy(inputs)
    norm = inputs["norm_preparation"]["correspondence"]["relational_fragment"]
    norm_before = deepcopy(norm)
    assert len(graph_record["definition_records"]) == 2
    assert len(graph_record["use_records"]) == 2
    assert len(graph_record["nomination_records"]) == 4
    assert len({canonical_dag_json_bytes(row["norm_source_target"])
                for row in graph_record["use_records"]}) == 1
    assert len([row for row in graph_record["source_records"]
                if row["reference_kind"] == "norm_source_target"]) == 1
    assert {row["relation"] for row in graph_record["graph"]["edges"]} == {
        "DERIVED_FROM", "CITES", "HAS_SOURCE"}
    selected_targets = []
    for link_index in (0, 2):
        request = bound_fixture.declaration(data, link_index=link_index, mode="body_with_membership")
        bound_report = bound_fixture.prepare(data, request)
        request_raw = bound_fixture.wire(request)
        bound_inputs = {"companion": companion, "request_raw": request_raw,
            "expected_companion_sha256": data["companion_sha256"],
            "expected_request_sha256": sha(request_raw), "companion_inputs": inputs}
        preparation = lake.prepare_bound_norm_definition_corpus_v1(
            bound_report,
            expected_bound_report_sha256=bound_fixture.owner.bound_variable_definition_sha256(bound_report),
            bound_definition_inputs=bound_inputs, toolchain="leanprover/lean4:v4.34.1")
        manifest = preparation.to_dict()
        assert (graph_record["report_record"]["report_sha256"]
                == bound_report["companion_sha256"]
                == manifest["review_intake_binding"]["companion_sha256"]
                == baseline["report_sha256"])
        for graph_field, bound_field in (
                ("norm_preparation_sha256", "preparation_sha256"),
                ("norm_correspondence_sha256", "correspondence_sha256"),
                ("norm_ast_sha256", "ast_sha256"),
                ("norm_native_ast_sha256", "native_ast_sha256"),
                ("norm_scope_id", "scope_id")):
            assert graph_record["norm_record"][graph_field] == companion[graph_field]
            assert graph_record["norm_record"][graph_field] == bound_report["original_norm"][bound_field]
        assert manifest["original_norm"] == bound_report["original_norm"]
        assert bound_report["original_norm"]["unchanged"] is True
        assert bound_report["selected_link"] == companion["links"][link_index]
        selected_targets.append(bound_report["occurrence_binding"]["target"]["typed_path"])
        assert bound_report["definition_alternatives"] == manifest["definition_alternatives"] == companion["definitions"]
        assert [row["request_link"] for row in manifest["nomination_inventory"]] == [
            row["request_link"] for row in companion["links"]]
        assert request["definition_assumption"]["parameter"] == "hDefinition"
        assert request["membership_assumption"]["parameter"] == "hMembership"
        assert "(hDefinition : formula_0 i t)" in bound_report["lean_source"]
        assert "(hMembership : headAt i entity t)" in bound_report["lean_source"]
        assert len(manifest["conditional_theorems"]) == 3
        assert manifest["native_fragments"][0]["native"]["lean_body"] == norm_before["lean_body"]
        assert manifest["native_ast_rewritten"] is False
        assert manifest["definition_applied_to_norm"] is False
        assert manifest["review_prerequisites_satisfied_under_selected_trust"] is False
        assert manifest["execution_handoff"]["processes_executed"] == 0
        assert manifest["build_eligible"] is False
        assert manifest["selected_interpretation"] is manifest["governing_definition_use"] is None
        assert all(value is False for value in manifest["authority"].values())
        assert type(manifest["training_mask"]) is type(manifest["evaluation_gold_mask"]) is int
        assert manifest["training_mask"] == manifest["evaluation_gold_mask"] == 0
        assert norm["source_binding"] is None and norm["source_bound"] is False
        assert norm == norm_before
        assert canonical_dag_json_bytes(graph_record) == graph_before
        assert graph_record["selected_interpretation"] is graph_record["governing_definition_use"] is None
        assert graph_record["training_mask"] == graph_record["evaluation_gold_mask"] == 0
        assert all(value is False for value in graph_record["authority"].values())
    assert len(set(selected_targets)) == 2
    assert companion == report_before and inputs == inputs_before


# The original parent-nomination helper already owns complete physical norm and
# definition populations. Reuse that route; a report-shaped stub is not enough.
@pytest.fixture(scope="module")
def parent_graph_baseline(tmp_path_factory):
    helper = fixture_helper()
    definition_helper = helper.fixture(
        "_parent_graph_definition_fixture", "test_plaintext_definition_review.py")
    case = helper._parent_nomination_materialize(definition_helper,
        tmp_path_factory.mktemp("parent-graph-originals", numbered=False))
    report = helper._parent_nomination_prepare(case)
    pin = evidence.norm_definition_evidence_sha256(report)
    record = owner.build_parent_norm_definition_graph_v1(
        report, expected_report_sha256=pin, **case)
    return {"inputs": case, "report": report, "record": record,
        "report_sha256": pin, "helper": helper,
        "graph_sha256": owner.norm_definition_graph_sha256(record)}


def validate_parent_graph(baseline, record=None, **overrides):
    record = baseline["record"] if record is None else record
    return owner.validate_parent_norm_definition_graph_v1(record, baseline["report"],
        expected_graph_sha256=owner.norm_definition_graph_sha256(record),
        **{"expected_report_sha256": baseline["report_sha256"],
            **baseline["inputs"], **overrides})


def forbid_parent_graph_replay(monkeypatch):
    def unexpected(*args, **kwargs):
        pytest.fail("malformed parent graph reached expensive original replay")
    monkeypatch.setattr(evidence, "validate_parent_norm_definition_evidence_v1", unexpected)


def assert_parent_graph_ref(reference, original):
    assert reference["sha256"] == evidence.norm_definition_evidence_sha256(original)
    if type(original) is dict and "record_cid" in original:
        assert reference["record_cid"] == original["record_cid"]


def test_parent_graph_genuine_validation_replays_original_companion_without_tools(
        parent_graph_baseline, monkeypatch):
    import subprocess

    baseline = parent_graph_baseline
    original = evidence.validate_parent_norm_definition_evidence_v1
    observed = []

    def traced(report, *args, **kwargs):
        observed.append((evidence.norm_definition_evidence_sha256(report),
            kwargs["expected_report_sha256"]))
        return original(report, *args, **kwargs)

    def forbidden(*args, **kwargs):
        pytest.fail("parent graph custody attempted a native probe or process")

    before = canonical_dag_json_bytes(baseline["record"])
    report_before = deepcopy(baseline["report"])
    inputs_before = deepcopy(baseline["inputs"])
    monkeypatch.setattr(evidence, "validate_parent_norm_definition_evidence_v1", traced)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)
    assert validate_parent_graph(baseline) == baseline["record"]
    assert observed == [(baseline["report_sha256"], baseline["report_sha256"])]
    assert canonical_dag_json_bytes(baseline["record"]) == before
    assert baseline["report"] == report_before and baseline["inputs"] == inputs_before
    assert corpus_graph.validate_graph_snapshot(baseline["record"]["graph"]) == baseline["record"]["graph"]


def test_parent_graph_three_exact_uses_and_six_ordered_nominations_remain_distinct(
        parent_graph_baseline):
    record, report = parent_graph_baseline["record"], parent_graph_baseline["report"]
    assert record["schema"] == owner.PARENT_SCHEMA and record["profile"] == owner.PARENT_PROFILE
    assert record["counts"]["alternatives"] == len(report["definitions"]) == 2
    assert record["counts"]["typed_uses"] == len(record["use_records"]) == 3
    assert record["counts"]["nominations"] == len(report["links"]) == 6
    assert [row["ordinal"] for row in record["definition_records"]] == [0, 1]
    assert [row["alternative_id"] for row in record["definition_records"]] == [
        row["alternative_id"] for row in report["definitions"]]
    uses = {row["record_cid"]: row for row in record["use_records"]}
    definitions = {row["alternative_id"]: row for row in record["definition_records"]}
    sources = {row["record_cid"]: row for row in record["source_records"]}

    def source_reference(cid, kind, original):
        retained = sources[cid]
        assert retained["reference_kind"] == kind and retained["custody_only"] is True
        assert_parent_graph_ref(retained["reference"], original)
        assert retained["reference_sha256"] == evidence.norm_definition_evidence_sha256(original)

    norm = report["norm_preparation"]
    norm_record = record["norm_record"]
    assert norm_record["norm_preparation_sha256"] == report["norm_preparation_sha256"]
    assert_parent_graph_ref(norm_record["preparation_ref"], norm)
    assert_parent_graph_ref(norm_record["correspondence_ref"], norm["correspondence"])
    assert norm_record["source_identity"] == norm["source_identity"]
    for field in ("source_identity", "original_parent_context", "obligations",
            "context_obligation_ids", "typed_context_inventory", "source_rows"):
        assert_parent_graph_ref(norm_record[field + "_ref"], norm[field])
    original_binding = norm["correspondence"]["source_scope"]["parent_source_binding"]
    assert_parent_graph_ref(norm_record["source_binding_ref"], original_binding)
    source_reference(norm_record["parent_source_record_cid"], "norm_parent_source_binding", original_binding)
    source_reference(norm_record["context_record_cid"], "norm_original_parent_context", norm["original_parent_context"])
    assert len(norm["context_obligation_ids"]) == 6 and norm["external_context_not_supplied"] is True
    occurrence_count = context_count = 0
    for offered, endpoint in zip(record["definition_records"], report["definitions"], strict=True):
        prepared, candidate = endpoint["preparation"], endpoint["candidate"]
        assert_parent_graph_ref(offered["endpoint_ref"], endpoint)
        assert_parent_graph_ref(offered["preparation_ref"], prepared)
        assert_parent_graph_ref(offered["candidate_ref"], candidate)
        assert offered["preparation_sha256"] == endpoint["preparation_sha256"]
        assert offered["candidate_pin"] == prepared["candidate_pin"]
        for field in ("source_version", "source_bindings", "contexts", "expected_context_population", "context_slot_ids"):
            assert_parent_graph_ref(offered[field + "_ref"], prepared[field])
        for field in ("term_record", "ast_record", "definition_record", "scope_record"):
            assert_parent_graph_ref(offered[field + "_ref"], candidate[field])
        assert offered["definition_term_ref"] == endpoint["definition_term_ref"]
        assert offered["definition_ast_ref"] == endpoint["definition_ast_ref"]
        assert offered["original_review_covers_projection"] is False
        source_reference(offered["parent_source_record_cid"],
            "definition_parent_source_binding", prepared["parent_source_binding"])
        for field, refs, cids, kind in (
                ("source_occurrences", "source_occurrence_refs", "source_occurrence_record_cids", "definition_source_occurrence"),
                ("contexts", "context_refs", "context_record_cids", "definition_context")):
            assert len(offered[refs]) == len(offered[cids]) == len(prepared[field])
            for reference, cid, original in zip(offered[refs], offered[cids], prepared[field], strict=True):
                assert_parent_graph_ref(reference, original)
                source_reference(cid, kind, original)
        occurrence_count += len(prepared["source_occurrences"])
        context_count += len(prepared["contexts"])
    assert record["counts"]["definition_source_occurrences"] == occurrence_count
    assert record["counts"]["definition_contexts"] == context_count
    variables = [row for row in uses.values() if row["target"]["kind"] == "variable"]
    assert len(variables) == 2 and variables[0]["typed_node"]["symbol"] == variables[1]["typed_node"]["symbol"]
    assert variables[0]["target"]["typed_path"] != variables[1]["target"]["typed_path"]
    assert len({row["record_cid"] for row in uses.values()}) == 3
    for ordinal, (offered, original) in enumerate(zip(
            record["nomination_records"], report["links"], strict=True)):
        use = uses[offered["use_record_cid"]]
        assert offered["ordinal"] == ordinal
        assert offered["request_link"] == original["request_link"]
        assert_parent_graph_ref(offered["link_ref"], original)
        assert offered["definition_record_cid"] == definitions[
            original["request_link"]["alternative_id"]]["record_cid"]
        assert use["target"] == original["request_link"]["target"]
        for field in ("typed_node", "typed_context", "typed_row", "source_rows"):
            assert use[field] == original[field]
        assert use["source_paths"] == original["request_link"]["source_paths"]
        assert offered["definition_candidate_ref"] == original["definition_candidate_ref"]
        assert offered["definition_term_ref"] == original["definition_term_ref"]
        assert offered["definition_ast_ref"] == original["definition_ast_ref"]
        assert offered["governing_definition_use"] is None
        assert len(offered["norm_source_record_cids"]) == len(original["source_rows"])
        for cid, source in zip(offered["norm_source_record_cids"], original["source_rows"], strict=True):
            source_reference(cid, "norm_source_row", source)
        assert offered["definition_source_record_cids"] == definitions[
            original["request_link"]["alternative_id"]]["source_occurrence_record_cids"]


def test_parent_graph_closed_custody_edges_and_pending_masks_confer_no_meaning(
        parent_graph_baseline):
    record = parent_graph_baseline["record"]
    graph = record["graph"]
    assert {row["node_type"] for row in graph["nodes"]} == {"interpretation", "expression"}
    assert {row["relation"] for row in graph["edges"]} == {"DERIVED_FROM", "CITES", "HAS_SOURCE"}
    ids = {row["record_cid"] for row in graph["nodes"]}
    assert all(row["src_cid"] in ids and row["dst_cid"] in ids for row in graph["edges"])
    assert all(row["source_occurrence_cids"] == [] for row in graph["nodes"])
    assert record["counts"]["source_references"] == len(record["source_records"])
    assert all(row["custody_only"] is True for row in record["source_records"])
    assert record["authority"] == owner.FALSE_FLAGS
    assert all(value is False for value in record["authority"].values())
    assert record["view"] == graph["view"] == "candidate"
    assert record["external_complete_inputs_required"] is True
    assert record["selected_interpretation"] is record["governing_definition_use"] is None
    assert graph["admitted"] is graph["formalized"] is graph["source_semantics_verified"] is False
    for key in ("semantic_mask", "consumer_mask", "training_mask", "evaluation_gold_mask"):
        assert type(record[key]) is int and record[key] == 0


@pytest.mark.parametrize("pin", ["expected_graph_sha256", "expected_report_sha256"])
def test_parent_graph_independent_pins_refuse_before_original_replay(
        parent_graph_baseline, monkeypatch, pin):
    forbid_parent_graph_replay(monkeypatch)
    baseline = parent_graph_baseline
    arguments = {"expected_graph_sha256": baseline["graph_sha256"],
        "expected_report_sha256": baseline["report_sha256"], **baseline["inputs"]}
    arguments[pin] = "0" * 64
    with pytest.raises(ValueError):
        owner.validate_parent_norm_definition_graph_v1(
            baseline["record"], baseline["report"], **arguments)


def test_parent_graph_resealed_reordering_refuses_before_original_replay(
        parent_graph_baseline, monkeypatch):
    changed = deepcopy(parent_graph_baseline["record"])
    changed["nomination_records"].reverse()
    forbid_parent_graph_replay(monkeypatch)
    with pytest.raises(ValueError):
        validate_parent_graph(parent_graph_baseline, reseal(changed))


@pytest.mark.parametrize("damage", ["binder_context", "definition_ref", "dropped_edge"])
def test_parent_graph_resealed_occurrence_and_endpoint_damage_cannot_hide_behind_closed_graph(
        parent_graph_baseline, monkeypatch, damage):
    changed = deepcopy(parent_graph_baseline["record"])
    if damage == "binder_context":
        use = changed["use_records"][0]
        use["typed_context"] = {}
        changed["use_records"][0] = reseal(use)
    elif damage == "definition_ref":
        nomination = changed["nomination_records"][0]
        nomination["definition_ast_ref"]["sha256"] = "0" * 64
        changed["nomination_records"][0] = reseal(nomination)
    else:
        changed["graph"] = corpus_graph.build_graph_snapshot(changed["graph"]["nodes"], [])
    forbid_parent_graph_replay(monkeypatch)
    with pytest.raises(ValueError):
        validate_parent_graph(parent_graph_baseline, reseal(changed))


@pytest.mark.parametrize("damage", ["governing", "semantic_mask"])
def test_parent_graph_resealed_projection_cannot_promote_pending_authority_or_boolean_masks(
        parent_graph_baseline, monkeypatch, damage):
    changed = deepcopy(parent_graph_baseline["record"])
    if damage == "governing":
        changed["governing_definition_use"] = changed["definition_records"][0]["record_cid"]
    else:
        changed[damage] = False
    forbid_parent_graph_replay(monkeypatch)
    with pytest.raises(ValueError):
        validate_parent_graph(parent_graph_baseline, reseal(changed))


def test_parent_graph_changed_request_pin_refuses_before_operation_owner_loading(
        parent_graph_baseline, monkeypatch):
    arguments = deepcopy(parent_graph_baseline["inputs"])
    arguments["expected_request_sha256"] = "0" * 64

    def unexpected():
        pytest.fail("malformed original parent input loaded operation owners")

    monkeypatch.setattr(evidence, "_parent_definition_owners", unexpected)
    with pytest.raises(ValueError):
        owner.build_parent_norm_definition_graph_v1(parent_graph_baseline["report"],
            expected_report_sha256=parent_graph_baseline["report_sha256"], **arguments)


def test_parent_graph_changed_original_physical_bytes_fail_genuine_replay(
        parent_graph_baseline, tmp_path):
    helper = parent_graph_baseline["helper"]
    definition_helper = helper.fixture(
        "_parent_graph_changed_physical_fixture", "test_plaintext_definition_review.py")
    # Only the norm needs a private physical generation. Retain the existing
    # complete definition populations; their files are never modified here.
    case = helper._parent_nomination_materialize(definition_helper, tmp_path,
        definitions=parent_graph_baseline["inputs"]["definitions"])
    report = helper._parent_nomination_prepare(case)
    original_path = helper._parent_nomination_parent_path(case, "norm")
    original = original_path.read_bytes()
    original_path.write_bytes(original + b"\nchanged original physical source\n")
    with pytest.raises(ValueError):
        owner.build_parent_norm_definition_graph_v1(report,
            expected_report_sha256=evidence.norm_definition_evidence_sha256(report), **case)
    assert original_path.read_bytes() != original


def test_parent_graph_exchange_roundtrip_keeps_external_original_report_and_complete_inputs_required(
        parent_graph_baseline, tmp_path):
    pytest.importorskip("pyarrow")
    from ipfs_datasets_py.logic.autoformal.corpus_graph_exchange import load_graph_bundle

    baseline = parent_graph_baseline
    raw = canonical_dag_json_bytes(baseline["record"])
    companion = tmp_path / "parent-candidate-companion.json"
    companion.write_bytes(raw)
    report_raw = json.dumps(baseline["report"], ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode("utf-8")
    assert sha(report_raw) == baseline["report_sha256"]
    (tmp_path / "original-parent-evidence.json").write_bytes(report_raw)
    output = tmp_path / "parent-graph-bundle"
    manifest = owner.export_parent_norm_definition_graph_v1(
        baseline["record"], output, baseline["report"],
        expected_graph_sha256=baseline["graph_sha256"],
        expected_report_sha256=baseline["report_sha256"], **baseline["inputs"])
    loaded = load_graph_bundle(output,
        expected_manifest_sha256=sha(canonical_dag_json_bytes(manifest)))
    retained = contracts.load_record_bytes(companion.read_bytes(), expected_sha256=sha(raw))
    assert retained == baseline["record"] and loaded["snapshot"] == retained["graph"]
    assert manifest["external_references_verified"] is False
    assert retained["external_complete_inputs_required"] is True
    assert not (output / "candidate.json").exists()
