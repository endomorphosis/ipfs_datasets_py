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
