"""Complete source/section fixtures prepare review requests, never acceptance."""
from copy import deepcopy
import hashlib
import json
import shutil

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from ipfs_datasets_py.logic.autoformal import legal_graph_dependencies as dependencies
from ipfs_datasets_py.logic.autoformal import legal_graph_review as review
from ipfs_datasets_py.logic.autoformal import legal_semantic_graph as graphs
from ipfs_datasets_py.logic.autoformal import legal_source_graph_proposals as proposals
from ipfs_datasets_py.logic.autoformal import legal_span_section_bridge as bridge_owner
from ipfs_datasets_py.logic.autoformal import legal_statutory_context as context
from ipfs_datasets_py.logic.autoformal import legal_primary_graph_manifest as manifests
from ipfs_datasets_py.logic.autoformal import legal_primary_graph_reconstruction as reconstruction
from ipfs_datasets_py.logic.autoformal.legal_primary_section_index import PrimarySectionIndex
from tests.unit.logic.autoformal.test_legal_span_section_bridge import (
    RAW, LEGAL_ID, cid, wrapped, primary_fixture, open_index, policy, span_fixture, trusted,
)


def empty_input(record_sha256):
    return {key: record_sha256 if key == "record_sha256" else None for key in proposals.INPUT_FIELDS}


def source_fixture(index):
    raw, bindings, _ = span_fixture()
    inputs = trusted([raw], bindings, index, policy([raw], bindings))
    bridge = bridge_owner.reconcile_span_sections([raw], **inputs)
    row = bridge["rows"][0]
    declaration = bindings["span:1"]
    selected = row["graph_proposal"]["source"]["selector"]
    mention = context.source_selector(declaration["document"], RAW,
        char_start=selected["char_start"], char_end=selected["char_start"] + len("Agency"))
    semantics = {"entities": [
        {"entity_key": "mention-agency", "kind": "mention", "label": "Agency", "source_selector": mention,
         "definition_kind": None, "ast_path": "/rules/0/actor", "ambiguity": ["institution or officeholder"], "evidence_refs": []},
        {"entity_key": "concept-agency", "kind": "concept", "label": "Agency", "source_selector": None,
         "definition_kind": None, "ast_path": "/rules/0/actor", "ambiguity": [], "evidence_refs": []}],
        "assertions": [{"assertion_key": "candidate-denotation", "subject_key": "mention-agency", "predicate": "candidate_denotation",
            "object_keys": ["concept-agency"], "ambiguity": ["requires independent interpretation review"],
            "evidence_refs": [], "dependency_refs": [{"artifact_id": "fixture:definition", "artifact_sha256": "d" * 64, "role": "definition"}]}]}
    graph = graphs.build_graph(**row["graph_request"], semantic_declarations=semantics)
    packet = context.build_context_packet(declaration["document"], RAW,
        char_start=selected["char_start"], char_end=selected["char_end"])
    refs = proposals.required_primary_artifacts(row["primary_binding"], row["candidate_section"])
    artifacts = [{"artifact_id": graph["graph_id"], "artifact_sha256": review.digest(graph)},
                 {"artifact_id": packet["packet_id"], "artifact_sha256": review.digest(packet)},
                 *[{key: ref[key] for key in ("artifact_id", "artifact_sha256")} for ref in refs],
                 {"artifact_id": "fixture:definition", "artifact_sha256": "d" * 64}]
    for artifact in artifacts: artifact["dependency_pins"] = {kind: [] for kind in dependencies.PIN_KINDS}
    artifacts[0]["dependency_pins"]["revision"] = [{"key": "explicit-source-revision", "sha256": hashlib.sha256(row["primary_binding"]["source_revision"].encode()).hexdigest()}]
    manifest = dependencies.build_dependency_manifest(artifacts,
        [{"dependent_id": graph["graph_id"], "dependency_id": artifact["artifact_id"]} for artifact in artifacts[1:]],
        expected_artifact_ids=[artifact["artifact_id"] for artifact in artifacts])
    observed_pins = {kind: {} for kind in dependencies.PIN_KINDS}
    for artifact in artifacts:
        for kind, pins in artifact["dependency_pins"].items():
            observed_pins[kind].update({pin["key"]: pin["sha256"] for pin in pins})
    supplied = empty_input(row["record_sha256"])
    supplied.update(semantic_declarations=semantics, expected_scope_id=graph["scope"]["scope_id"],
        expected_graph_sha256=review.digest(graph), context_packet=packet, expected_context_sha256=review.digest(packet),
        dependency_manifest=manifest, expected_manifest_sha256=manifest["manifest_sha256"],
        required_dependency_ids=[artifact["artifact_id"] for artifact in artifacts],
        observed_artifact_sha256s={artifact["artifact_id"]: artifact["artifact_sha256"] for artifact in artifacts},
        observed_pins=observed_pins)
    return bridge, [raw], dict(expected_bridge_sha256=bridge["bridge_sha256"], bridge_inputs=inputs,
        row_inputs=[supplied], expected_row_inputs_sha256=proposals.proposal_inputs_sha256([supplied]),
        expected_record_sha256s=inputs["expected_record_sha256s"])


def refresh(inputs):
    inputs["expected_row_inputs_sha256"] = proposals.proposal_inputs_sha256(inputs["row_inputs"])


def release_point_index(tmp_path):
    original = tmp_path / "original"; original.mkdir()
    candidate, _ = primary_fixture(original)
    old_selection = json.loads(candidate.read_bytes().splitlines()[0])["selection"]
    root = tmp_path / "release-primary"
    # Author a separate fixture generation; the first pinned fixture is untouched.
    shutil.copytree(original / "primary", root)
    manifest = deepcopy(old_selection["manifest"])
    for descriptor in manifest["artifacts"]:
        path = root / descriptor["relative_path"]
        rows = pq.read_table(path).to_pylist()
        body = ({"entry_cid": cid("release-point"), "family": "graph_nodes", "node_type": "release_point",
                 "node_key": "release_point:" + manifest["release_point"], "label": manifest["release_point"]}
                if descriptor["family"] == "graph_nodes" else
                {"entry_cid": cid("release-relation"), "family": "graph_edges", "edge_type": "HAS_SOURCE",
                 "source_entry_cid": cid("section"), "target_entry_cid": cid("release-point")})
        rows.append(wrapped(body))
        pq.write_table(pa.Table.from_pylist(rows, schema=pa.schema([(key, pa.string()) for key in manifests.FIELDS])), path)
        descriptor.update(row_count=len(rows), size_bytes=path.stat().st_size, sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    manifest["manifest_digest"] = manifests.digest({k: v for k, v in manifest.items() if k != "manifest_digest"})
    raw = json.dumps(manifest).encode()
    selection = manifests.select_primary_graph_manifest(raw, expected_manifest_sha256=hashlib.sha256(raw).hexdigest(),
        repository=old_selection["repository"], revision=old_selection["revision"],
        expected_release_identity={key: manifest[key] for key in manifests.RELEASE_FIELDS},
        expected_graph_population={family: {"files": 1, "rows": next(d["row_count"] for d in manifest["artifacts"] if d["family"] == family)}
                                   for family in ("graph_nodes", "graph_edges")})
    candidate = tmp_path / "release-candidate.jsonl"
    report = reconstruction.reconstruct_to_jsonl(selection, root, candidate, expected_selection_sha256=selection["selection_sha256"])
    return PrimarySectionIndex(candidate, reconstruction_report=report, expected_candidate_sha256=report["candidate_sha256"],
                               expected_reconstruction_sha256=report["reconstruction_sha256"])


def test_source_primary_entities_and_review_request_reuse_existing_owners_without_authority(tmp_path):
    with open_index(tmp_path) as index:
        bridge, rows, inputs = source_fixture(index)
        report = proposals.prepare_source_graph_proposals(bridge, rows, **inputs)
        observed = report["rows"][0]
        assert observed["disposition"] == "review_request_prepared_context_open"
        assert len(observed["primary_links"]) == 3
        assert all(link["primary_binding"]["legal_id"] == LEGAL_ID for link in observed["primary_links"])
        assert observed["source_scoped_graph"]["entities"][0]["declaration"]["ambiguity"] == ["institution or officeholder"]
        assert len(observed["context_obligations"]) == 6 and all(slot["open"] for slot in observed["context_obligations"])
        assert observed["review_request"]["subject"]["required_dependency_ids"] == inputs["row_inputs"][0]["required_dependency_ids"]
        assert report["bridge"] == bridge and report["row_count"] == 1
        assert all(not value for value in report["authority"].values())
        assert all(not value for value in observed["review_request"]["authority"].values())
        assert proposals.validate_source_graph_proposals(report, bridge, rows, **inputs) == report


@pytest.mark.parametrize("damage", ["missing_context", "stale_context", "missing_definition", "changed_source_pin", "cycle", "missing_primary_mapping", "missing_package", "scope", "no_declarations"])
def test_context_definition_primary_scope_and_current_dependency_gaps_never_prepare_review(tmp_path, damage):
    with open_index(tmp_path) as index:
        bridge, rows, inputs = source_fixture(index)
        supplied = inputs["row_inputs"][0]
        if damage == "missing_context": supplied["context_packet"] = None
        elif damage == "stale_context": supplied["context_packet"]["selection"]["utf8_byte_start"] += 1
        elif damage == "missing_definition": supplied["observed_artifact_sha256s"]["fixture:definition"] = None
        elif damage == "changed_source_pin": supplied["observed_pins"]["revision"]["explicit-source-revision"] = "0" * 64
        elif damage in ("cycle", "missing_primary_mapping", "missing_package"):
            manifest = supplied["dependency_manifest"]
            edges = deepcopy(manifest["edges"])
            if damage == "cycle": edges.append({"dependent_id": "fixture:definition", "dependency_id": manifest["expected_artifact_ids"][0]})
            else:
                role = "declared_primary_source_correspondence_only" if damage == "missing_primary_mapping" else "declared_primary_source_package"
                ref = next(ref for ref in proposals.required_primary_artifacts(bridge["rows"][0]["primary_binding"], bridge["rows"][0]["candidate_section"]) if ref["role"] == role)
                edges = [edge for edge in edges if edge["dependency_id"] != ref["artifact_id"]]
                supplied["required_dependency_ids"] = [value for value in supplied["required_dependency_ids"] if value != ref["artifact_id"]]
            supplied["dependency_manifest"] = dependencies.build_dependency_manifest(manifest["artifacts"], edges,
                expected_artifact_ids=manifest["expected_artifact_ids"])
            supplied["expected_manifest_sha256"] = supplied["dependency_manifest"]["manifest_sha256"]
        elif damage == "scope": supplied["expected_scope_id"] = "legal-scope:sha256:" + "0" * 64
        else: supplied["semantic_declarations"] = None
        refresh(inputs)
        report = proposals.prepare_source_graph_proposals(bridge, rows, **inputs)
        observed = report["rows"][0]
        assert observed["review_request"] is None and observed["issues"]
        assert len(observed["context_obligations"]) == 6 and all(slot["open"] for slot in observed["context_obligations"])
        assert all(not value for value in observed["authority"].values())


def test_forged_closed_context_cannot_close_displayed_obligations(tmp_path):
    with open_index(tmp_path) as index:
        bridge, rows, inputs = source_fixture(index)
        supplied = inputs["row_inputs"][0]
        for slot in supplied["context_packet"]["dependency_slots"]: slot.update(open=False, semantic_attachment_verified=True)
        supplied["expected_context_sha256"] = review.digest(supplied["context_packet"])
        refresh(inputs)
        observed = proposals.prepare_source_graph_proposals(bridge, rows, **inputs)["rows"][0]
        assert observed["review_request"] is None
        assert all(slot["open"] and not slot["semantic_attachment_verified"] for slot in observed["context_obligations"])
        assert supplied["context_packet"] == observed["proposal_input"]["context_packet"]


@pytest.mark.parametrize("wrong_pin", ["0" * 64, "malformed-graph-pin"])
def test_supplied_graph_pin_is_enforced_before_missing_review_inputs(tmp_path, wrong_pin):
    with open_index(tmp_path) as index:
        bridge, rows, inputs = source_fixture(index)
        supplied = inputs["row_inputs"][0]
        supplied.update(expected_graph_sha256=wrong_pin, context_packet=None, dependency_manifest=None)
        refresh(inputs)
        observed = proposals.prepare_source_graph_proposals(bridge, rows, **inputs)["rows"][0]
        assert observed["source_scoped_graph"] is None and observed["review_request"] is None
        assert observed["primary_links"] == observed["primary_artifact_refs"] == []
        assert observed["disposition"] == "unresolved"
        assert any("independent_graph_pin_malformed_or_different" in issue.get("message", "") for issue in observed["issues"])


@pytest.mark.parametrize("damage", ["authority", "omitted_row", "subject", "primary_anchor"])
def test_self_resealed_proposal_population_or_review_subject_cannot_pass_regeneration(tmp_path, damage):
    with open_index(tmp_path) as index:
        bridge, rows, inputs = source_fixture(index)
        report = proposals.prepare_source_graph_proposals(bridge, rows, **inputs)
        if damage == "authority": report["authority"]["accepted_view_eligible"] = True
        elif damage == "omitted_row": report["rows"] = []; report["row_count"] = 0
        elif damage == "subject": report["rows"][0]["review_request"]["subject"]["scope_id"] = "different"
        else: report["rows"][0]["primary_links"][0]["primary_binding"]["section_entry_cid"] = "different"
        report["proposals_sha256"] = proposals._digest({k: v for k, v in report.items() if k != "proposals_sha256"})
        with pytest.raises(proposals.SourceGraphProposalError, match="independent complete regeneration"):
            proposals.validate_source_graph_proposals(report, bridge, rows, **inputs)


def test_missing_reordered_or_duplicate_sidecar_population_is_rejected(tmp_path):
    with open_index(tmp_path) as index:
        bridge, rows, inputs = source_fixture(index)
        for changed in ([], inputs["row_inputs"] * 2):
            with pytest.raises(ValueError):
                proposals.prepare_source_graph_proposals(bridge, rows, **{**inputs, "row_inputs": changed})
        inputs["row_inputs"][0]["record_sha256"] = "0" * 64; refresh(inputs)
        with pytest.raises(proposals.SourceGraphProposalError, match="membership"):
            proposals.prepare_source_graph_proposals(bridge, rows, **inputs)


def test_complete_unsupported_paired_population_remains_unresolved_even_with_legacy_true_flags(tmp_path):
    row = {"schema_version": "uscode-paired-span-census/v1",
        "source": {"span_id": "paired:1", "text": "Agency", "text_sha256": context.sha("Agency"),
                   "legal_id": LEGAL_ID, "revision": "ipfs-uscode-5016b86a"},
        "autoencoder": {"complete": True, "model_identity": "mock", "formal_outputs": [{"target_conditioned": True}]},
        "admitted": True, "formalized": True}
    rows = [deepcopy(row) for _ in range(8)]
    with open_index(tmp_path) as index:
        bridge_inputs = trusted(rows, {}, index, policy([], {}, mappings=False))
        bridge = bridge_owner.reconcile_span_sections(rows, **bridge_inputs)
        supplied = [empty_input(value) for value in bridge_inputs["expected_record_sha256s"]]
        report = proposals.prepare_source_graph_proposals(bridge, rows, expected_bridge_sha256=bridge["bridge_sha256"],
            bridge_inputs=bridge_inputs, row_inputs=supplied, expected_row_inputs_sha256=proposals.proposal_inputs_sha256(supplied),
            expected_record_sha256s=bridge_inputs["expected_record_sha256s"])
        assert report["row_count"] == 8 and report["disposition_counts"] == {"unresolved": 8}
        assert len({value["record_sha256"] for value in report["rows"]}) == 8
        assert all(value["source_scoped_graph"] is None and value["review_request"] is None for value in report["rows"])
        assert [value["raw_row"] for value in report["bridge"]["rows"]] == rows


def test_declared_release_point_and_relationship_are_bound_without_applicability_authority(tmp_path):
    with release_point_index(tmp_path) as index:
        bridge, rows, inputs = source_fixture(index)
        report = proposals.prepare_source_graph_proposals(bridge, rows, **inputs)
        observed = report["rows"][0]
        assert observed["review_request"] is not None
        roles = {ref["role"]: ref for ref in observed["primary_artifact_refs"]}
        assert roles["declared_primary_release_point"]["artifact_id"] == cid("release-point")
        assert roles["declared_HAS_SOURCE_release_context_evidence"]["artifact_id"] == cid("release-relation")
        assert all(not value for value in observed["review_request"]["authority"].values())
        assert all(slot["open"] for slot in observed["context_obligations"])


@pytest.mark.parametrize("damage", ["omitted_node", "omitted_relationship", "stale_node", "stale_relationship"])
def test_declared_release_point_or_relationship_cannot_be_omitted_or_stale_in_review_closure(tmp_path, damage):
    with release_point_index(tmp_path) as index:
        bridge, rows, inputs = source_fixture(index)
        supplied = inputs["row_inputs"][0]
        target = cid("release-point" if damage.endswith("node") else "release-relation")
        if damage.startswith("stale"):
            supplied["observed_artifact_sha256s"][target] = "0" * 64
        else:
            old = supplied["dependency_manifest"]
            edges = [edge for edge in old["edges"] if edge["dependency_id"] != target]
            supplied["dependency_manifest"] = dependencies.build_dependency_manifest(old["artifacts"], edges,
                expected_artifact_ids=old["expected_artifact_ids"])
            supplied["expected_manifest_sha256"] = supplied["dependency_manifest"]["manifest_sha256"]
            supplied["required_dependency_ids"].remove(target)
        refresh(inputs)
        observed = proposals.prepare_source_graph_proposals(bridge, rows, **inputs)["rows"][0]
        assert observed["source_scoped_graph"] is not None
        assert observed["review_request"] is None and observed["issues"]
        assert all(slot["open"] for slot in observed["context_obligations"])


# Wire-coordinate semantic proposals reuse genuine original graph-v3 fixtures.
# Every declaration below is an authored unreviewed candidate, including its
# definition operator. No declaration infers entity-cache meaning or authority.
import base64 as _semantic_base64
import os as _semantic_os
from ipfs_datasets_py.logic.autoformal import corpus_proposed_graph_adapter as _semantic_adapter
from ipfs_datasets_py.logic.autoformal import legal_span_cache_intake as intake
from ipfs_datasets_py.utils.cid_utils import canonical_dag_json_bytes as _semantic_dag_bytes
from tests.unit.logic.autoformal.test_legal_span_cache_intake import (
    coordinate_join, wire_coordinate_join, wire_original_replay_v4,
    wire_graph_v3_case, _prepare_wire_graph_v3, _wire_graph_v3_request,
    _coordinate_graph_retained_table, coordinate_graph_v2_case,
    _prepare_coordinate_graph_v2, _coordinate_graph_v2_request,
)

_SEMANTIC_REQUEST_SCHEMA = "legal-coordinate-semantic-graph-proposals-request/v1"
_SEMANTIC_SCHEMA = "legal-coordinate-semantic-graph-proposals/v1"
_SEMANTIC_PROFILE = "original-input-wire-coordinate-authored-semantic-proposals/v1"
_SEMANTIC_REQUEST_FIELDS = {
    "schema", "profile", "graph_report_raw_sha256", "graph_report_sha256",
    "graph_originals_sha256", "output_inputs",
}
_SEMANTIC_SLOT_FIELDS = {
    "output_occurrence_ordinal", "physical_identity_sha256", "route", "ordinal",
    "semantic_declarations", "expected_scope_id", "expected_graph_sha256",
}


def _semantic_wire(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def _semantic_sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _semantic_reference(ordinal, role):
    name = "authored-wire-semantic:" + str(ordinal) + ":" + role
    return {"artifact_id": name, "artifact_sha256": _semantic_sha(name.encode()), "role": role}


def _semantic_declarations(output, ordinal):
    selector = deepcopy(output["graph_request"]["source"]["selector"])
    def entity(key, kind, definition_kind=None):
        return {"entity_key": key, "kind": kind, "label": "authored Clerk alternative " + str(ordinal),
            "source_selector": None if kind == "concept" else deepcopy(selector),
            "definition_kind": definition_kind, "ast_path": "/rules/0",
            "ambiguity": ["independent authored proposal; no reviewed definition meaning"],
            "evidence_refs": [_semantic_reference(ordinal, "source")]}
    return {"entities": [entity("mention", "mention"), entity("concept-A", "concept"),
                entity("concept-B", "concept"),
                entity("definition", "definition", "means" if ordinal % 2 == 0 else "includes")],
        "assertions": [{"assertion_key": "ordered-candidate-denotation", "subject_key": "mention",
            "predicate": "candidate_denotation", "object_keys": ["concept-A", "concept-B", "concept-A"],
            "ambiguity": ["no governing interpretation selected"],
            "evidence_refs": [_semantic_reference(ordinal, "source")],
            "dependency_refs": [_semantic_reference(ordinal, "definition")]}]}


@pytest.fixture
def wire_semantic_case(wire_graph_v3_case):
    upstream = wire_graph_v3_case
    report = _prepare_wire_graph_v3(upstream)
    graph_raw = (json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    original_request = _wire_graph_v3_request(upstream)
    originals = {"request_raw": original_request,
        "eligibility_report_raw": upstream["eligibility_raw"],
        "eligibility_request_raw": upstream["eligibility_request_raw"],
        "join_manifest_raw": upstream["join_raw"],
        "expected_request_sha256": _semantic_sha(original_request),
        "join_originals": upstream["originals"], "source_bindings": upstream["bindings"]}
    sidecars, expected = [], []
    for ordinal, output in enumerate(report["output_occurrences"]):
        slot = {key: deepcopy(output[key]) for key in
                ("output_occurrence_ordinal", "physical_identity_sha256", "route", "ordinal")}
        declarations = _semantic_declarations(output, ordinal) if output["graph"] is not None else None
        graph = None
        if declarations is not None:
            args = deepcopy(output["graph_request"])
            args.update(semantic_declarations=declarations, scope_request=None)
            graph = graphs.build_graph(**args)
        slot.update(semantic_declarations=declarations,
            expected_scope_id=None if graph is None else graph["scope"]["scope_id"],
            expected_graph_sha256=None if graph is None else _semantic_sha(_semantic_wire(graph)))
        assert set(slot) == _SEMANTIC_SLOT_FIELDS
        sidecars.append(slot); expected.append(graph)
    return {"upstream": upstream, "graph": report, "graph_raw": graph_raw,
            "originals": originals, "sidecars": sidecars, "expected_graphs": expected}


def _semantic_request(case, **changes):
    return _semantic_wire({"schema": _SEMANTIC_REQUEST_SCHEMA, "profile": _SEMANTIC_PROFILE,
        "graph_report_raw_sha256": _semantic_sha(case["graph_raw"]),
        "graph_report_sha256": intake.coordinate_source_graph_intake_sha256(case["graph"]),
        "graph_originals_sha256": proposals.coordinate_semantic_graph_proposals_originals_sha256(case["originals"]),
        "output_inputs": deepcopy(case["sidecars"]), **changes})


def _prepare_semantic(case, *, request_raw=None, **changes):
    raw = _semantic_request(case) if request_raw is None else request_raw
    args = {"expected_request_sha256": _semantic_sha(raw), "graph_originals": case["originals"], **changes}
    return proposals.prepare_coordinate_semantic_graph_proposals_v1(raw, case["graph_raw"], **args)


def _validate_semantic(case, report, *, request_raw=None, **changes):
    raw = _semantic_request(case) if request_raw is None else request_raw
    offered = json.loads(report) if type(report) is bytes else report
    # An independently supplied pin must bypass default hashing entirely: a
    # patched final encoder belongs to the operation being tested, not helper
    # argument construction before the genuine reader has returned anything.
    expected = (changes["expected_report_sha256"] if "expected_report_sha256" in changes
                else proposals.coordinate_semantic_graph_proposals_sha256(offered))
    args = {"expected_report_sha256": expected,
        "expected_request_sha256": _semantic_sha(raw), "graph_originals": case["originals"], **changes}
    return proposals.validate_coordinate_semantic_graph_proposals_v1(report, raw, case["graph_raw"], **args)


def _assert_semantic_no_authority(report):
    assert report["schema"] == _SEMANTIC_SCHEMA and report["profile"] == _SEMANTIC_PROFILE
    for value in [report, *report["output_occurrences"]]:
        assert value["authority"] and all(type(flag) is bool and flag is False for flag in value["authority"].values())
        assert type(value["training_mask"]) is type(value["evaluation_gold_mask"]) is int
        assert value["training_mask"] == value["evaluation_gold_mask"] == 0
    for output in report["output_occurrences"]:
        assert type(output["source_binding_mask"]) is int and output["source_binding_mask"] == 0
        assert output["selected_occurrence"] is output["governing_definition_use"] is None
        graph = output["source_scoped_graph"]
        if graph is not None:
            assert all(flag is False for flag in graph["authority"].values())
            assert all(entity["accepted"] is False and entity["source_semantics_verified"] is False for entity in graph["entities"])


@pytest.mark.parametrize("coordinate_join", [{"documents": [{"z_metadata": "first", "a_metadata": "second", "legal_id": "usc:us:5:551", "text": "Unselected Ω context. Clerk shall file report."}], "selected_indices": (1,), "compiler_rule": {"modality": "O", "actor": "Clerk", "action": "file", "object": "report", "conditions": [], "exceptions": [], "temporal": []}}], ids=["wire-supported"], indirect=True)
@pytest.mark.parametrize("offered", ["object", "bytes"], ids=["object", "bytes"])
def test_wire_semantic_genuine_graphs_keep_independent_slot_declarations_and_roundtrip(wire_semantic_case, monkeypatch, offered):
    case = wire_semantic_case
    actual_upstream, actual_builder = intake.validate_coordinate_source_graph_intake_v3, graphs.build_graph
    upstream_returns, declared_graphs = [], []
    def replay(*args, **kwargs):
        value = actual_upstream(*args, **kwargs); upstream_returns.append(value); return value
    def build(*args, **kwargs):
        value = actual_builder(*args, **kwargs)
        if kwargs.get("semantic_declarations") is not None: declared_graphs.append(value)
        return value
    monkeypatch.setattr(intake, "validate_coordinate_source_graph_intake_v3", replay)
    monkeypatch.setattr(graphs, "build_graph", build)
    monkeypatch.setattr(bridge_owner, "reconcile_span_sections", lambda *a, **k: pytest.fail("wire route called legacy section bridge"))
    before = deepcopy(case["originals"]), deepcopy(case["sidecars"])
    report = _prepare_semantic(case)
    outputs = report["output_occurrences"]
    assert len(outputs) == len(declared_graphs) == 2 and len(upstream_returns) >= 2
    assert set(json.loads(_semantic_request(case))) == _SEMANTIC_REQUEST_FIELDS
    assert outputs[0]["physical_identity_sha256"] == outputs[1]["physical_identity_sha256"]
    assert [v["output_occurrence_ordinal"] for v in outputs] == [0, 1]
    assert len({v["source_scoped_graph"]["graph_id"] for v in outputs}) == 2
    for ordinal, row in enumerate(outputs):
        upstream = case["graph"]["output_occurrences"][ordinal]
        assert row["upstream_output"] == upstream and row["proposal_input"] == case["sidecars"][ordinal]
        assert row["disposition"] == "proposed_unreviewed_graph" and row["issues"] == []
        graph = row["source_scoped_graph"]
        assert graph == case["expected_graphs"][ordinal] == declared_graphs[ordinal]
        assert graphs.graph_to_ast(graph) == upstream["eligibility_output"]["canonical_ir"]
        expected_inputs = {**deepcopy(upstream["graph_request"]),
            "semantic_declarations": case["sidecars"][ordinal]["semantic_declarations"], "scope_request": None}
        assert set(row["graph_request"]) == _semantic_adapter.TRUSTED_INPUT_FIELDS
        assert row["graph_request"] == expected_inputs
        assert graph["source"] == upstream["graph"]["source"] and graph["scope"] == upstream["graph"]["scope"]
        entities = graph["entities"]; assert len(entities) == 4
        assert entities[3]["identity"]["definition_kind"] == ("means" if ordinal == 0 else "includes")
        assert graph["assertions"][0]["object_ids"] == [entities[1]["entity_id"], entities[2]["entity_id"], entities[1]["entity_id"]]
    value = report if offered == "object" else _semantic_wire(report)
    assert _validate_semantic(case, value) == report
    assert (case["originals"], case["sidecars"]) == before
    _assert_semantic_no_authority(report)


@pytest.mark.parametrize("coordinate_join", [{"documents": [{"z_metadata": "first", "a_metadata": "second", "legal_id": "usc:us:5:551", "text": "Unselected Ω context. Clerk shall file report."}], "selected_indices": (1,), "compiler_rule": {"modality": "O", "actor": "Clerk", "action": "file", "object": "report", "conditions": [], "exceptions": [], "temporal": []}}], ids=["wire-supported"], indirect=True)
def test_wire_semantic_existing_general_corpus_adapter_preserves_declared_graph_and_ast(wire_semantic_case):
    case = wire_semantic_case; report = _prepare_semantic(case); row = report["output_occurrences"][0]
    graph = row["source_scoped_graph"]; inputs = row["graph_request"]
    binding = case["originals"]["source_bindings"][row["physical_identity_sha256"]]
    raw_html = _semantic_base64.b64decode(binding["raw_html_base64"], validate=True)
    graph_raw = _semantic_dag_bytes(graph)
    args = dict(expected_proposal_sha256=_semantic_sha(graph_raw), trusted_proposal_inputs=inputs,
        expected_inputs_sha256=_semantic_sha(_semantic_dag_bytes(inputs)), document=binding["document"],
        raw_html=raw_html, expected_raw_sha256=_semantic_sha(raw_html),
        expected_extracted_sha256=_semantic_sha(binding["document"]["document_text"].encode("utf-8")))
    candidate = _semantic_adapter.adapt_proposed_graph_bytes(graph_raw, **args)
    retained = json.loads(candidate["proposal_record"]["proposal_json"])
    assert retained == graph and retained["entities"] == graph["entities"] and retained["assertions"] == graph["assertions"]
    assert _semantic_adapter.restore_proposed_graph_ast(candidate, **args) == inputs["ast"]
    assert _semantic_adapter.validate_proposed_graph_candidate(candidate, **args) == candidate
    assert candidate["definition_semantics_encoded"] is candidate["admitted"] is candidate["formalized"] is candidate["source_semantics_verified"] is False
    _assert_semantic_no_authority(report)


@pytest.mark.parametrize("coordinate_join", [{"documents": [{"z_metadata": "first", "a_metadata": "second", "legal_id": "usc:us:5:551", "text": "Unselected Ω context. Clerk shall file report."}], "selected_indices": (1,), "compiler_rule": {"modality": "O", "actor": "Clerk", "action": "file", "object": "report", "conditions": [], "exceptions": [], "temporal": []}}], ids=["wire-supported"], indirect=True)
def test_wire_semantic_null_declarations_keep_resolved_ast_slot_unresolved(wire_semantic_case):
    case = wire_semantic_case
    for sidecar in case["sidecars"]: sidecar.update(semantic_declarations=None, expected_scope_id=None, expected_graph_sha256=None)
    report = _prepare_semantic(case)
    assert len(report["output_occurrences"]) == 2
    for row in report["output_occurrences"]:
        assert row["upstream_output"]["graph"] is not None
        assert row["source_scoped_graph"] is row["graph_request"] is None and row["disposition"] == "unresolved"
        assert any(issue["code"] == "semantic_declarations_not_supplied" for issue in row["issues"])
    _assert_semantic_no_authority(report)


def test_wire_semantic_unsupported_upstream_preserves_every_slot_and_supplied_candidate(wire_semantic_case, monkeypatch):
    case = wire_semantic_case
    assert all(row["graph"] is None for row in case["graph"]["output_occurrences"])
    declarations = {"entities": [{"entity_key": "unresolved-concept", "kind": "concept", "label": "independent candidate",
        "source_selector": None, "definition_kind": None, "ast_path": None, "ambiguity": ["upstream AST unsupported"], "evidence_refs": []}], "assertions": []}
    for slot in case["sidecars"]:
        binding = case["originals"]["source_bindings"][slot["physical_identity_sha256"]]
        slot.update(semantic_declarations=deepcopy(declarations), expected_scope_id=binding["scope"]["scope_id"])
    monkeypatch.setattr(graphs, "build_graph", lambda *a, **k: pytest.fail("unsupported upstream invented semantic graph"))
    report = _prepare_semantic(case)
    assert len(report["output_occurrences"]) == len(case["graph"]["output_occurrences"])
    for row, source, slot in zip(report["output_occurrences"], case["graph"]["output_occurrences"], case["sidecars"]):
        assert row["upstream_output"] == source and row["proposal_input"] == slot
        assert row["source_scoped_graph"] is None and row["disposition"] == "unresolved"
        assert any(issue["code"] == "upstream_graph_unresolved" for issue in row["issues"])
    _assert_semantic_no_authority(report)


@pytest.mark.parametrize("coordinate_join", [{"documents": [{"z_metadata": "first", "a_metadata": "second", "legal_id": "usc:us:5:551", "text": "Unselected Ω context. Clerk shall file report."}, {"z_metadata": "first", "a_metadata": "second", "legal_id": "usc:us:5:551", "text": "Unselected Ω context. Clerk shall file report."}], "selected_indices": (1, 3), "compiler_rule": {"modality": "O", "actor": "Clerk", "action": "file", "object": "report", "conditions": [], "exceptions": [], "temporal": []}}], ids=["wire-repeated"], indirect=True)
def test_wire_semantic_equal_text_distinct_physical_rows_keep_all_four_ordered_outputs(wire_semantic_case):
    case = wire_semantic_case; report = _prepare_semantic(case); outputs = report["output_occurrences"]
    assert len(outputs) == 4 and [v["output_occurrence_ordinal"] for v in outputs] == [0, 1, 2, 3]
    assert len({v["physical_identity_sha256"] for v in outputs}) == 2
    assert [v["upstream_output"]["eligibility_output"]["source_coordinate_span_index"] for v in outputs] == [1, 1, 3, 3]
    assert [v["proposal_input"] for v in outputs] == case["sidecars"]
    assert all(v["source_scoped_graph"] == e for v,e in zip(outputs,case["expected_graphs"]))
    _assert_semantic_no_authority(report)


@pytest.mark.parametrize("coordinate_join", [{"documents": [{"z_metadata": "first", "a_metadata": "second", "legal_id": "usc:us:5:551", "text": "Unselected Ω context. Clerk shall file report."}], "selected_indices": (1,), "compiler_rule": {"modality": "O", "actor": "Clerk", "action": "file", "object": "report", "conditions": [], "exceptions": [], "temporal": []}}], ids=["wire-supported"], indirect=True)
@pytest.mark.parametrize("pin", ["request", "graph-raw", "graph-canonical", "originals"],
                         ids=["request", "graph-raw", "graph-canonical", "originals"])
def test_wire_semantic_independent_original_pins_cannot_be_resealed(wire_semantic_case, pin):
    case = wire_semantic_case
    if pin == "request":
        with pytest.raises(ValueError): _prepare_semantic(case, expected_request_sha256="0" * 64)
    else:
        field = {"graph-raw": "graph_report_raw_sha256", "graph-canonical": "graph_report_sha256", "originals": "graph_originals_sha256"}[pin]
        raw = _semantic_request(case, **{field: "0" * 64})
        with pytest.raises(ValueError): _prepare_semantic(case, request_raw=raw)


@pytest.mark.parametrize("coordinate_join", [{"documents": [{"z_metadata": "first", "a_metadata": "second", "legal_id": "usc:us:5:551", "text": "Unselected Ω context. Clerk shall file report."}], "selected_indices": (1,), "compiler_rule": {"modality": "O", "actor": "Clerk", "action": "file", "object": "report", "conditions": [], "exceptions": [], "temporal": []}}], ids=["wire-supported"], indirect=True)
@pytest.mark.parametrize("damage", ["missing", "extra", "profile"], ids=["missing", "extra", "profile"])
def test_wire_semantic_request_has_one_closed_explicit_profile(wire_semantic_case, damage):
    case = wire_semantic_case; request = json.loads(_semantic_request(case))
    if damage == "missing": request.pop("graph_originals_sha256")
    elif damage == "extra": request["semantic_entity_cache_authorized"] = True
    else: request["profile"] = "original-input-coordinate-graph-v2-corpus-custody/v1"
    with pytest.raises(ValueError): _prepare_semantic(case, request_raw=_semantic_wire(request))


@pytest.mark.parametrize("coordinate_join", [{"documents": [{"z_metadata": "first", "a_metadata": "second", "legal_id": "usc:us:5:551", "text": "Unselected Ω context. Clerk shall file report."}], "selected_indices": (1,), "compiler_rule": {"modality": "O", "actor": "Clerk", "action": "file", "object": "report", "conditions": [], "exceptions": [], "temporal": []}}], ids=["wire-supported"], indirect=True)
@pytest.mark.parametrize("damage", ["omit", "duplicate", "reorder", "extra-field"],
                         ids=["omit", "duplicate", "reorder", "extra-field"])
def test_wire_semantic_exact_complete_ordered_sidecar_population_required(wire_semantic_case, damage):
    case = wire_semantic_case
    if damage == "omit": case["sidecars"].pop()
    elif damage == "duplicate": case["sidecars"][1] = deepcopy(case["sidecars"][0])
    elif damage == "reorder": case["sidecars"].reverse()
    else: case["sidecars"][0]["reviewed"] = True
    # The request is freshly encoded and independently pinned; outer resealing
    # does not authorize changing the original ordered output-slot population.
    with pytest.raises(ValueError): _prepare_semantic(case)


@pytest.mark.parametrize("coordinate_join", [{"documents": [{"z_metadata": "first", "a_metadata": "second", "legal_id": "usc:us:5:551", "text": "Unselected Ω context. Clerk shall file report."}], "selected_indices": (1,), "compiler_rule": {"modality": "O", "actor": "Clerk", "action": "file", "object": "report", "conditions": [], "exceptions": [], "temporal": []}}], ids=["wire-supported"], indirect=True)
@pytest.mark.parametrize("damage", ["scope", "graph-pin", "null-with-pin"], ids=["scope", "graph-pin", "null-with-pin"])
def test_wire_semantic_scope_graph_and_explicit_null_pins_remain_independent(wire_semantic_case, damage):
    case = wire_semantic_case; sidecar = case["sidecars"][0]
    if damage == "scope": sidecar["expected_scope_id"] = "legal-scope:sha256:" + "0" * 64
    elif damage == "graph-pin": sidecar["expected_graph_sha256"] = "0" * 64
    else: sidecar["semantic_declarations"] = None
    with pytest.raises(ValueError): _prepare_semantic(case)


@pytest.mark.parametrize("coordinate_join", [{"documents": [{"z_metadata": "first", "a_metadata": "second", "legal_id": "usc:us:5:551", "text": "Unselected Ω context. Clerk shall file report."}], "selected_indices": (1,), "compiler_rule": {"modality": "O", "actor": "Clerk", "action": "file", "object": "report", "conditions": [], "exceptions": [], "temporal": []}}], ids=["wire-supported"], indirect=True)
@pytest.mark.parametrize("damage", ["dangling", "geometry", "duplicate-entity"], ids=["dangling", "geometry", "duplicate-entity"])
def test_wire_semantic_invalid_authored_declarations_are_refused_without_repair(wire_semantic_case, damage):
    case = wire_semantic_case; sidecar = case["sidecars"][0]
    declarations = sidecar["semantic_declarations"]; sidecar["expected_graph_sha256"] = None
    if damage == "dangling": declarations["assertions"][0]["object_keys"][1] = "missing"
    elif damage == "geometry": declarations["entities"][0]["source_selector"]["utf8_byte_start"] += 1
    else: declarations["entities"].append(deepcopy(declarations["entities"][0]))
    with pytest.raises(ValueError): _prepare_semantic(case)


@pytest.mark.parametrize("coordinate_join", [{"documents": [{"z_metadata": "first", "a_metadata": "second", "legal_id": "usc:us:5:551", "text": "Unselected Ω context. Clerk shall file report."}], "selected_indices": (1,), "compiler_rule": {"modality": "O", "actor": "Clerk", "action": "file", "object": "report", "conditions": [], "exceptions": [], "temporal": []}}], ids=["wire-supported"], indirect=True)
@pytest.mark.parametrize("damage", ["authority", "omit", "reorder", "sidecar", "graph"], ids=["authority", "omit", "reorder", "sidecar", "graph"])
def test_wire_semantic_rehashed_offered_report_requires_complete_original_regeneration(wire_semantic_case, damage):
    case = wire_semantic_case; report = _prepare_semantic(case)
    if damage == "authority": report["authority"]["admitted"] = True
    elif damage == "omit": report["output_occurrences"].pop()
    elif damage == "reorder": report["output_occurrences"].reverse()
    elif damage == "sidecar": report["output_occurrences"][0]["proposal_input"]["semantic_declarations"]["entities"][0]["label"] = "changed"
    else: report["output_occurrences"][0]["source_scoped_graph"]["entities"][0]["accepted"] = True
    with pytest.raises(ValueError): _validate_semantic(case, report)


@pytest.mark.parametrize("coordinate_join", [{"documents": [{"z_metadata": "first", "a_metadata": "second", "legal_id": "usc:us:5:551", "text": "Unselected Ω context. Clerk shall file report."}], "selected_indices": (1,), "compiler_rule": {"modality": "O", "actor": "Clerk", "action": "file", "object": "report", "conditions": [], "exceptions": [], "temporal": []}}], ids=["wire-supported"], indirect=True)
def test_wire_semantic_bad_complete_report_pin_refuses_before_replay(wire_semantic_case, monkeypatch):
    case = wire_semantic_case; report = _prepare_semantic(case)
    monkeypatch.setattr(proposals, "_coordinate_semantic_owners", lambda *a, **k: pytest.fail("bad offered pin entered genuine replay"))
    with pytest.raises(ValueError): _validate_semantic(case, report, expected_report_sha256="0" * 64)


@pytest.mark.parametrize("coordinate_join", [{"documents": [{"z_metadata": "first", "a_metadata": "second", "legal_id": "usc:us:5:551", "text": "Unselected Ω context. Clerk shall file report."}], "selected_indices": (1,), "compiler_rule": {"modality": "O", "actor": "Clerk", "action": "file", "object": "report", "conditions": [], "exceptions": [], "temporal": []}}], ids=["wire-supported"], indirect=True)
def test_wire_semantic_real_paired_file_drift_after_declared_builder_is_refused(wire_semantic_case, monkeypatch):
    case = wire_semantic_case; genuine = graphs.build_graph; reached = []
    def build(*args, **kwargs):
        result = genuine(*args, **kwargs)
        if kwargs.get("semantic_declarations") is not None and not reached:
            reached.append(result)
            table = _coordinate_graph_retained_table(case["upstream"])
            table.write_bytes(table.read_bytes() + b"changed after genuine semantic graph")
        return result
    monkeypatch.setattr(graphs, "build_graph", build)
    with pytest.raises(ValueError): _prepare_semantic(case)
    assert len(reached) == 1


@pytest.mark.parametrize("coordinate_join", [{"documents": [{"z_metadata": "first", "a_metadata": "second", "legal_id": "usc:us:5:551", "text": "Unselected Ω context. Clerk shall file report."}], "selected_indices": (1,), "compiler_rule": {"modality": "O", "actor": "Clerk", "action": "file", "object": "report", "conditions": [], "exceptions": [], "temporal": []}}], ids=["wire-supported"], indirect=True)
def test_wire_semantic_original_caller_binding_mutated_after_genuine_builder_is_refused(wire_semantic_case, monkeypatch):
    case = wire_semantic_case; genuine = graphs.build_graph; reached = []
    def build(*args, **kwargs):
        result = genuine(*args, **kwargs)
        if kwargs.get("semantic_declarations") is not None and not reached:
            reached.append(result)
            next(iter(case["originals"]["source_bindings"].values()))["context_observation"]["status"] += ":changed"
        return result
    monkeypatch.setattr(graphs, "build_graph", build)
    with pytest.raises(ValueError): _prepare_semantic(case)
    assert len(reached) == 1


@pytest.mark.parametrize("coordinate_join", [{"documents": [{"z_metadata": "first", "a_metadata": "second", "legal_id": "usc:us:5:551", "text": "Unselected Ω context. Clerk shall file report."}], "selected_indices": (1,), "compiler_rule": {"modality": "O", "actor": "Clerk", "action": "file", "object": "report", "conditions": [], "exceptions": [], "temporal": []}}], ids=["wire-supported"], indirect=True)
def test_wire_semantic_actual_opening_upstream_return_stays_guarded_through_closing_replay(wire_semantic_case, monkeypatch):
    case = wire_semantic_case; genuine = intake.validate_coordinate_source_graph_intake_v3; results = []; mutated = []
    def replay(*args, **kwargs):
        result = genuine(*args, **kwargs); results.append(result)
        if len(results) >= 2 and not mutated:
            results[0]["output_occurrences"][0]["graph"]["authority"]["accepted"] = True
            mutated.append(results[0])
        return result
    monkeypatch.setattr(intake, "validate_coordinate_source_graph_intake_v3", replay)
    with pytest.raises(ValueError): _prepare_semantic(case)
    assert len(results) >= 2 and len(mutated) == 1


@pytest.mark.parametrize("coordinate_join", [{"documents": [{"z_metadata": "first", "a_metadata": "second", "legal_id": "usc:us:5:551", "text": "Unselected Ω context. Clerk shall file report."}], "selected_indices": (1,), "compiler_rule": {"modality": "O", "actor": "Clerk", "action": "file", "object": "report", "conditions": [], "exceptions": [], "temporal": []}}], ids=["wire-supported"], indirect=True)
@pytest.mark.parametrize("target", ["caller", "upstream-return", "builder-return", "encoded-report"],
                         ids=["caller", "upstream-return", "builder-return", "encoded-report"])
def test_wire_semantic_final_encoder_retains_actual_inputs_returns_and_report(wire_semantic_case, monkeypatch, target):
    case = wire_semantic_case
    real_replay, real_build, real_wire = intake.validate_coordinate_source_graph_intake_v3, graphs.build_graph, proposals._coordinate_semantic_wire
    upstream, built, reached = [], [], []
    def replay(*args, **kwargs):
        value = real_replay(*args, **kwargs); upstream.append(value); return value
    def build(*args, **kwargs):
        value = real_build(*args, **kwargs)
        if kwargs.get("semantic_declarations") is not None: built.append(value)
        return value
    def encode(value, *args, **kwargs):
        raw = real_wire(value, *args, **kwargs)
        if type(value) is dict and value.get("schema") == _SEMANTIC_SCHEMA and len(upstream) >= 2 and not reached:
            reached.append(target)
            if target == "caller": next(iter(case["originals"]["source_bindings"].values()))["context_observation"]["status"] += ":late"
            elif target == "upstream-return": upstream[0]["output_occurrences"][0]["training_mask"] = 1
            elif target == "builder-return": built[0]["entities"][0]["accepted"] = True
            else: value["authority"]["admitted"] = True
        return raw
    monkeypatch.setattr(intake, "validate_coordinate_source_graph_intake_v3", replay)
    monkeypatch.setattr(graphs, "build_graph", build)
    monkeypatch.setattr(proposals, "_coordinate_semantic_wire", encode)
    with pytest.raises(ValueError): _prepare_semantic(case)
    assert reached == [target] and built and len(upstream) >= 2


@pytest.mark.parametrize("coordinate_join", [{"documents": [{"z_metadata": "first", "a_metadata": "second", "legal_id": "usc:us:5:551", "text": "Unselected Ω context. Clerk shall file report."}], "selected_indices": (1,), "compiler_rule": {"modality": "O", "actor": "Clerk", "action": "file", "object": "report", "conditions": [], "exceptions": [], "temporal": []}}], ids=["wire-supported"], indirect=True)
def test_wire_semantic_validator_retains_original_offered_report_during_real_builder(wire_semantic_case, monkeypatch):
    case = wire_semantic_case; offered = _prepare_semantic(case); genuine = graphs.build_graph; reached = []
    def build(*args, **kwargs):
        value = genuine(*args, **kwargs)
        if kwargs.get("semantic_declarations") is not None and not reached:
            offered["authority"]["admitted"] = True; reached.append(value)
        return value
    monkeypatch.setattr(graphs, "build_graph", build)
    with pytest.raises(ValueError): _validate_semantic(case, offered)
    assert len(reached) == 1


@pytest.mark.parametrize("coordinate_join", [{"documents": [{"z_metadata": "first", "a_metadata": "second", "legal_id": "usc:us:5:551", "text": "Unselected Ω context. Clerk shall file report."}], "selected_indices": (1,), "compiler_rule": {"modality": "O", "actor": "Clerk", "action": "file", "object": "report", "conditions": [], "exceptions": [], "temporal": []}}], ids=["wire-supported"], indirect=True)
def test_wire_semantic_validator_fences_actual_parsed_bad_offered_report_before_mutable_reencoding(wire_semantic_case, monkeypatch):
    case = wire_semantic_case; good = _prepare_semantic(case); bad = deepcopy(good); bad["counts"]["proposed_unreviewed_graphs"] += 1
    offered_raw = _semantic_wire(bad)
    real_read, real_builder = proposals._coordinate_semantic_read, graphs.build_graph
    parsed, reached = [], []
    def read(*args, **kwargs):
        value = real_read(*args, **kwargs)
        if type(value) is dict and value.get("schema") == _SEMANTIC_SCHEMA: parsed.append(value)
        return value
    def build(*args, **kwargs):
        value = real_builder(*args, **kwargs)
        if kwargs.get("semantic_declarations") is not None and not reached:
            assert parsed
            for report in parsed: report.clear(); report.update(deepcopy(good))
            reached.append(value)
        return value
    monkeypatch.setattr(proposals, "_coordinate_semantic_read", read)
    monkeypatch.setattr(graphs, "build_graph", build)
    with pytest.raises(ValueError):
        _validate_semantic(case, offered_raw, expected_report_sha256=proposals.coordinate_semantic_graph_proposals_sha256(bad))
    assert len(reached) == 1


@pytest.mark.parametrize("coordinate_join", [{"documents": [{"z_metadata": "first", "a_metadata": "second", "legal_id": "usc:us:5:551", "text": "Unselected Ω context. Clerk shall file report."}], "selected_indices": (1,), "compiler_rule": {"modality": "O", "actor": "Clerk", "action": "file", "object": "report", "conditions": [], "exceptions": [], "temporal": []}}], ids=["wire-supported"], indirect=True)
def test_wire_semantic_held_original_finalizer_survives_callback_replacement(wire_semantic_case, monkeypatch):
    case = wire_semantic_case; real_builder = graphs.build_graph; real_replay = intake.validate_coordinate_source_graph_intake_v3
    reached, attempts = [], []
    def replay(*args, **kwargs): attempts.append(True); return real_replay(*args, **kwargs)
    def build(*args, **kwargs):
        value = real_builder(*args, **kwargs)
        if kwargs.get("semantic_declarations") is not None and not reached:
            reached.append(value); monkeypatch.setattr(proposals, "_coordinate_semantic_finish", lambda *a, **k: None)
        return value
    monkeypatch.setattr(graphs, "build_graph", build)
    monkeypatch.setattr(intake, "validate_coordinate_source_graph_intake_v3", replay)
    with pytest.raises(ValueError): _prepare_semantic(case)
    assert reached and len(attempts) >= 2


class _WireSemanticInterrupt(BaseException):
    pass


@pytest.mark.parametrize("coordinate_join", [{"documents": [{"z_metadata": "first", "a_metadata": "second", "legal_id": "usc:us:5:551", "text": "Unselected Ω context. Clerk shall file report."}], "selected_indices": (1,), "compiler_rule": {"modality": "O", "actor": "Clerk", "action": "file", "object": "report", "conditions": [], "exceptions": [], "temporal": []}}], ids=["wire-supported"], indirect=True)
def test_wire_semantic_primary_baseexception_survives_genuine_closing_physical_refusal(wire_semantic_case, monkeypatch):
    case = wire_semantic_case; real_builder = graphs.build_graph; real_replay = intake.validate_coordinate_source_graph_intake_v3
    sentinel = _WireSemanticInterrupt("authored primary semantic callback failure")
    attempts, closing_failures, reached = [], [], []
    def replay(*args, **kwargs):
        attempts.append(True)
        try: return real_replay(*args, **kwargs)
        except BaseException as error: closing_failures.append(error); raise
    def build(*args, **kwargs):
        value = real_builder(*args, **kwargs)
        if kwargs.get("semantic_declarations") is not None:
            reached.append(value); table = _coordinate_graph_retained_table(case["upstream"])
            table.write_bytes(table.read_bytes() + b"changed before primary BaseException")
            raise sentinel
        return value
    monkeypatch.setattr(intake, "validate_coordinate_source_graph_intake_v3", replay)
    monkeypatch.setattr(graphs, "build_graph", build)
    with pytest.raises(_WireSemanticInterrupt) as caught: _prepare_semantic(case)
    assert caught.value is sentinel and len(reached) == 1 and len(attempts) >= 2
    assert closing_failures and any(isinstance(error, ValueError) for error in closing_failures)
    assert getattr(caught.value, "__notes__", None), "the actual secondary closing refusal must remain visible"


@pytest.mark.parametrize("coordinate_join", [{"documents": [{"z_metadata": "first", "a_metadata": "second", "legal_id": "usc:us:5:551", "text": "Unselected Ω context. Clerk shall file report."}], "selected_indices": (1,), "compiler_rule": {"modality": "O", "actor": "Clerk", "action": "file", "object": "report", "conditions": [], "exceptions": [], "temporal": []}}], ids=["wire-supported"], indirect=True)
@pytest.mark.parametrize("bound", ["request-bytes", "output-slots"], ids=["request-bytes", "output-slots"])
def test_wire_semantic_finite_input_bounds_refuse_without_output_truncation(wire_semantic_case, bound):
    case = wire_semantic_case
    if bound == "request-bytes": raw = b" " * (4 * 1024 * 1024 + 1)
    else:
        case["sidecars"] = [deepcopy(case["sidecars"][0]) for _ in range(257)]
        raw = _semantic_request(case)
    with pytest.raises(ValueError): _prepare_semantic(case, request_raw=raw)


@pytest.mark.parametrize("coordinate_join", [{"documents": [{"z_metadata": "first", "a_metadata": "second", "legal_id": "usc:us:5:551", "text": "Unselected Ω context. Clerk shall file report."}], "selected_indices": (1,), "compiler_rule": {"modality": "O", "actor": "Clerk", "action": "file", "object": "report", "conditions": [], "exceptions": [], "temporal": []}}], ids=["wire-supported"], indirect=True)
def test_wire_semantic_optional_graph_pin_absence_does_not_drop_independent_declarations(wire_semantic_case):
    case = wire_semantic_case
    for row in case["sidecars"]: row["expected_graph_sha256"] = None
    report = _prepare_semantic(case)
    assert [v["source_scoped_graph"] for v in report["output_occurrences"]] == case["expected_graphs"]
    assert _validate_semantic(case, _semantic_wire(report)) == report
    _assert_semantic_no_authority(report)


@pytest.mark.parametrize("coordinate_join", [{"documents": [{"z_metadata": "first", "a_metadata": "second", "legal_id": "usc:us:5:551", "text": "Unselected Ω context. Clerk shall file report."}], "selected_indices": (1,), "compiler_rule": {"modality": "O", "actor": "Clerk", "action": "file", "object": "report", "conditions": [], "exceptions": [], "temporal": []}}], ids=["wire-supported"], indirect=True)
@pytest.mark.parametrize("target", ["parsed-request", "parsed-offered"], ids=["parsed-request", "parsed-offered"])
def test_wire_semantic_early_actual_reader_returns_are_held_before_first_encoder(wire_semantic_case, monkeypatch, target):
    case = wire_semantic_case; good = _prepare_semantic(case)
    offered_pin = proposals.coordinate_semantic_graph_proposals_sha256(good)
    real_read, real_wire = proposals._coordinate_semantic_read, proposals._coordinate_semantic_wire
    parsed_requests, parsed_offered, reached = [], [], []
    def read(*args, **kwargs):
        value = real_read(*args, **kwargs)
        if type(value) is dict and value.get("schema") == _SEMANTIC_REQUEST_SCHEMA: parsed_requests.append(value)
        if type(value) is dict and value.get("schema") == _SEMANTIC_SCHEMA: parsed_offered.append(value)
        return value
    def encode(value, *args, **kwargs):
        raw = real_wire(value, *args, **kwargs)
        trigger = (target == "parsed-request" and type(value) is dict and value.get("schema") == "legal-coordinate-source-graph-intake/v3"
            or target == "parsed-offered" and type(value) is dict and value.get("schema") == _SEMANTIC_SCHEMA)
        if trigger and not reached:
            reached.append(target)
            if target == "parsed-request":
                assert parsed_requests
                slot = parsed_requests[0]["output_inputs"][0]
                slot["semantic_declarations"]["entities"][0]["label"] += ":changed before parsed commitment"
                slot["expected_graph_sha256"] = None
            else:
                assert parsed_offered
                parsed_offered[0]["counts"]["proposed_unreviewed_graphs"] += 1
        return raw
    monkeypatch.setattr(proposals, "_coordinate_semantic_read", read)
    monkeypatch.setattr(proposals, "_coordinate_semantic_wire", encode)
    with pytest.raises(ValueError):
        if target == "parsed-request": _prepare_semantic(case)
        else: _validate_semantic(case, _semantic_wire(good), expected_report_sha256=offered_pin)
    assert reached == [target]


@pytest.mark.parametrize("coordinate_join", [{"documents": [{"z_metadata": "first", "a_metadata": "second", "legal_id": "usc:us:5:551", "text": "Unselected Ω context. Clerk shall file report."}], "selected_indices": (1,), "compiler_rule": {"modality": "O", "actor": "Clerk", "action": "file", "object": "report", "conditions": [], "exceptions": [], "temporal": []}}], ids=["wire-supported"], indirect=True)
def test_wire_semantic_postvalidator_file_mutation_cannot_become_new_opening_baseline(wire_semantic_case, monkeypatch):
    case = wire_semantic_case; real_replay = intake.validate_coordinate_source_graph_intake_v3; real_build = graphs.build_graph
    returned, mutated, declared_attempts = [], [], []
    def replay(*args, **kwargs):
        value = real_replay(*args, **kwargs); returned.append(value)
        if not mutated:
            table = _coordinate_graph_retained_table(case["upstream"]); witness = table.stat()
            _semantic_os.utime(table, ns=(witness.st_atime_ns, witness.st_mtime_ns + 1000000))
            mutated.append(table)
        return value
    def build(*args, **kwargs):
        if kwargs.get("semantic_declarations") is not None:
            declared_attempts.append(True)
            pytest.fail("changed postvalidator physical witnesses became a trusted semantic opening baseline")
        return real_build(*args, **kwargs)
    monkeypatch.setattr(intake, "validate_coordinate_source_graph_intake_v3", replay)
    monkeypatch.setattr(graphs, "build_graph", build)
    with pytest.raises(ValueError): _prepare_semantic(case)
    assert returned and len(mutated) == 1 and declared_attempts == []


@pytest.mark.parametrize("coordinate_join", [{"documents": [{"z_metadata": "first", "a_metadata": "second", "legal_id": "usc:us:5:551", "text": "Unselected Ω context. Clerk shall file report."}], "selected_indices": (1,), "compiler_rule": {"modality": "O", "actor": "Clerk", "action": "file", "object": "report", "conditions": [], "exceptions": [], "temporal": []}}], ids=["wire-supported"], indirect=True)
def test_wire_semantic_genuine_older_graph_v2_is_not_relabelled_as_wire_v3(coordinate_graph_v2_case):
    upstream = coordinate_graph_v2_case
    report = _prepare_coordinate_graph_v2(upstream); request_raw = _coordinate_graph_v2_request(upstream)
    originals = {"request_raw": request_raw, "eligibility_report_raw": upstream["eligibility_raw"],
        "eligibility_request_raw": upstream["eligibility_request_raw"], "join_manifest_raw": upstream["join_raw"],
        "expected_request_sha256": _semantic_sha(request_raw), "join_originals": upstream["originals"],
        "source_bindings": upstream["bindings"]}
    slots = [{**{key: row[key] for key in ("output_occurrence_ordinal", "physical_identity_sha256", "route", "ordinal")},
        "semantic_declarations": None, "expected_scope_id": None, "expected_graph_sha256": None}
        for row in report["output_occurrences"]]
    case = {"graph": report, "graph_raw": _semantic_wire(report), "originals": originals, "sidecars": slots}
    assert report["schema"] == "legal-coordinate-source-graph-intake/v2"
    with pytest.raises(ValueError): _prepare_semantic(case)
