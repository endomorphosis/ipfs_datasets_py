"""Whole selected graph fixtures retain every source row and quarantine gaps."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from ipfs_datasets_py.logic.autoformal import legal_primary_graph_manifest as manifests
from ipfs_datasets_py.logic.autoformal import legal_primary_graph_records as records
from ipfs_datasets_py.logic.autoformal import legal_primary_graph_reconstruction as graphs


def identity(value):
    return "sha256:" + hashlib.sha256(value.encode()).hexdigest()


def node(key, **properties):
    return {"family": "graph_nodes", "entry_cid": identity(key), "node_type": "section",
            "legal_id": "usc:us:10:1", "label": "Café same label", **properties}


def edge(key, source="A", target="B", **properties):
    return {"family": "graph_edges", "entry_cid": identity(key), "edge_type": "CITES",
            "source_entry_cid": identity(source), "target_entry_cid": identity(target), **properties}


def wrapped(body, *, encoded=None):
    encoded = encoded if encoded is not None else json.dumps(body, ensure_ascii=False, indent=2)
    return {"entry_cid": body.get("entry_cid") or "", "legal_id": body.get("legal_id") or "",
            "family": body["family"], "record_sha256": hashlib.sha256(encoded.encode()).hexdigest(), "record_json": encoded}


def fixture(tmp_path, *, nodes=None, edges=None, extra=True):
    root = tmp_path / "snapshot"
    root.mkdir()
    populations = {"graph_edges": [wrapped(edge("edge"))] if edges is None else edges,
                   "graph_nodes": [wrapped(node("A", unknown={"ordered": [3, "é", 3], "admitted": True})), wrapped(node("B"))]
                                  if nodes is None else nodes}
    descriptors = []
    for family, rows in populations.items():
        directory = "nodes" if family == "graph_nodes" else "edges"
        relative = f"data/graph/{directory}/part-000000.parquet"
        path = root / relative
        path.parent.mkdir(parents=True)
        schema = pa.schema([pa.field(name, pa.string()) for name in manifests.FIELDS])
        pq.write_table(pa.Table.from_pylist(rows, schema=schema), path, row_group_size=1)
        descriptors.append({"family": family, "first_key": None, "last_key": None,
            "media_type": "application/vnd.apache.parquet", "relative_path": relative,
            "row_count": len(rows), "schema_id": "uscode-graph-node/v1" if family == "graph_nodes" else "uscode-graph-edge/v1",
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "size_bytes": path.stat().st_size})
    if extra:
        (root / "data/graph/edges/part-999999.parquet").write_bytes(b"Retained old generation; deliberately not Parquet")
    manifest = {"schema_version": "uscode-sparse-graphrag-release-schema-v2", "hf_release_schema_version": "uscode-hf-release/v1",
        "release_profile": "publicus-ir-graphrag/v2", "dataset_repo_id": "fixture/primary",
        "release_point": "us/pl/119/102", "release_root_cid": identity("root"), "source_revision": "b" * 40,
        "graph_ontology_version": "uscode-legal-graph-ontology/v1", "producer": "uscode_hf_release.py",
        "artifacts": descriptors, "unknown_manifest_metadata": {"preserve": [True, "é"]}}
    manifest["manifest_digest"] = manifests.digest(manifest)
    raw = json.dumps(manifest, ensure_ascii=False, indent=2).encode()
    selection = manifests.select_primary_graph_manifest(raw, expected_manifest_sha256=hashlib.sha256(raw).hexdigest(),
        repository="fixture/primary", revision="a" * 40,
        expected_release_identity={key: manifest[key] for key in manifests.RELEASE_FIELDS},
        expected_graph_population={family: {"files": 1, "rows": len(rows)} for family, rows in populations.items()})
    return selection, root, {"expected_selection_sha256": selection["selection_sha256"]}


def read_candidate(path):
    return [json.loads(line) for line in path.read_bytes().splitlines()]


def test_whole_population_global_endpoints_properties_and_lineage_are_preserved(tmp_path):
    selection, root, trusted = fixture(tmp_path)
    path = tmp_path / "candidate.jsonl"
    report = graphs.reconstruct_to_jsonl(selection, root, path, **trusted)
    candidate = read_candidate(path)
    assert report["rows"] == sum(report["disposition_counts"].values()) == 3
    assert report["endpoint_integrity_passed"] is True and report["blockers"] == []
    assert report["family_row_counts"] == {"graph_edges": 1, "graph_nodes": 2}
    assert report["producer_declared_kind_counts"] == {"graph_nodes": {"section": 2}, "graph_edges": {"CITES": 1}}
    assert report["missing_or_invalid_producer_kind_rows"] == {"graph_nodes": 0, "graph_edges": 0}
    assert report["endpoint_resolution_scope"] == "unique_decoded_node_declarations_only_unresolved_rows_remain_global_blockers"
    assert report["endpoint_counts"] == {"source": {"unique_declared_node": 1}, "target": {"unique_declared_node": 1}}
    assert report["candidate_lines"] == len(candidate) == 4
    assert report["candidate_sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert report["candidate_bytes"] == path.stat().st_size
    assert candidate[0]["selection"]["raw_manifest_utf8"] == selection["raw_manifest_utf8"]
    assert report["source_verification"]["extra_file_count"] == 1
    assert report["source_verification"]["extras"][0]["body_hash_verified"] is False
    assert "extras" not in candidate[0]["selected_source_files"]
    assert "verification_sha256" not in candidate[0]["selected_source_files"]
    assert candidate[2]["original_body"]["unknown"] == {"ordered": [3, "é", 3], "admitted": True}
    assert candidate[2]["declared_identity"]["entry_cid"] != candidate[3]["declared_identity"]["entry_cid"]
    source = list(manifests.iter_verified_graph_rows(selection, root, **trusted))
    assert [row["global_ordinal"] for row in candidate[1:]] == list(range(3))
    for emitted, original in zip(candidate[1:], source):
        assert emitted["custody"] == original["custody"]
        assert emitted["raw_row_sha256"] == records.raw_row_sha256(original["raw_row"])
        assert emitted["record_sha256"] == hashlib.sha256(original["raw_row"]["record_json"].encode()).hexdigest()
        assert all(value is False for value in emitted["authority"].values())
    assert all(value is False for value in report["authority"].values())
    assert report["coverage_scope"] == "exact_manifest_selected_primary_graph_rows_only"
    assert graphs.validate_reconstruction(report, selection, root, path, **trusted) == report


def test_outputs_and_full_reports_are_reproducible_across_destination_paths(tmp_path):
    selection, root, trusted = fixture(tmp_path)
    first = graphs.reconstruct_to_jsonl(selection, root, tmp_path / "first.jsonl", **trusted)
    second = graphs.reconstruct_to_jsonl(selection, root, tmp_path / "second.jsonl", **trusted)
    assert first == second
    assert (tmp_path / "first.jsonl").read_bytes() == (tmp_path / "second.jsonl").read_bytes()


def test_candidate_identity_excludes_cache_location_and_unselected_older_files(tmp_path):
    selection, root, trusted = fixture(tmp_path)
    first = graphs.reconstruct_to_jsonl(selection, root, tmp_path / "first.jsonl", **trusted)
    copied = tmp_path / "different-snapshot-location"
    shutil.copytree(root, copied)
    (copied / "data/graph/nodes/part-999998.parquet").write_bytes(b"Another retained older file; never decode")
    second = graphs.reconstruct_to_jsonl(selection, copied, tmp_path / "second.jsonl", **trusted)
    assert first["source_verification"]["extra_file_count"] == 1
    assert second["source_verification"]["extra_file_count"] == 2
    assert first["source_verification"] != second["source_verification"]
    assert first["candidate_sha256"] == second["candidate_sha256"]
    assert first["selected_files_sha256"] == second["selected_files_sha256"]
    assert (tmp_path / "first.jsonl").read_bytes() == (tmp_path / "second.jsonl").read_bytes()


@pytest.mark.parametrize("damage", ["duplicate", "conflict", "missing", "malformed", "edge_duplicate", "cross_family"])
def test_all_rows_remain_visible_when_identity_or_endpoint_integrity_is_blocked(tmp_path, damage):
    nodes = [wrapped(node("A")), wrapped(node("B"))]
    edges = [wrapped(edge("edge"))]
    if damage == "duplicate": nodes.append(deepcopy(nodes[0]))
    elif damage == "conflict": nodes.append(wrapped(node("A", label="conflicting original properties")))
    elif damage == "missing": edges = [wrapped(edge("edge", target="outside"))]
    elif damage == "malformed": nodes[0] = wrapped(node("A"), encoded="{malformed")
    elif damage == "edge_duplicate": edges.append(deepcopy(edges[0]))
    else: edges = [wrapped(edge("A"))]
    selection, root, trusted = fixture(tmp_path, nodes=nodes, edges=edges)
    path = tmp_path / "blocked.jsonl"
    result = graphs.reconstruct_to_jsonl(selection, root, path, **trusted)
    assert result["endpoint_integrity_passed"] is False and result["blockers"]
    assert result["rows"] == len(nodes) + len(edges) == sum(result["disposition_counts"].values())
    assert len(read_candidate(path)) == result["rows"] + 1
    if damage in ("duplicate", "conflict"):
        assert result["endpoint_counts"]["source"] == {"ambiguous": 1}
        assert result["identity_census"]["graph_nodes"]["duplicate_identity_extra_instances"] == 1
    if damage == "conflict": assert result["identity_census"]["graph_nodes"]["conflicting_identity_ids"] == 1
    if damage == "malformed": assert result["decoder_disposition_counts"]["unresolved"] == 1
    if damage == "cross_family": assert result["identity_census"]["cross_family_identity_collisions"] == 1


def test_unresolved_edge_keeps_quarantine_and_complete_endpoint_denominators(tmp_path):
    body = edge("missing-field"); body.pop("source_entry_cid")
    selection, root, trusted = fixture(tmp_path, edges=[wrapped(body)])
    path = tmp_path / "unresolved.jsonl"
    report = graphs.reconstruct_to_jsonl(selection, root, path, **trusted)
    assert report["endpoint_counts"] == {"source": {"unresolved_record": 1}, "target": {"unresolved_record": 1}}
    assert read_candidate(path)[1]["disposition"] == "quarantined_unresolved_record"
    assert read_candidate(path)[1]["original_body"] == body


@pytest.mark.parametrize("damage", ["authority", "count", "unknown", "candidate_hash"])
def test_self_resealed_reports_cannot_replace_independently_reconstructed_inputs(tmp_path, damage):
    selection, root, trusted = fixture(tmp_path)
    path = tmp_path / "candidate.jsonl"
    report = graphs.reconstruct_to_jsonl(selection, root, path, **trusted)
    if damage == "authority": report["authority"]["admitted"] = True
    elif damage == "count": report["rows"] -= 1
    elif damage == "unknown": report["accepted"] = True
    else: report["candidate_sha256"] = "0" * 64
    report["reconstruction_sha256"] = graphs._digest({k: v for k, v in report.items() if k != "reconstruction_sha256"})
    with pytest.raises(graphs.PrimaryGraphReconstructionError, match="independent complete source replay"):
        graphs.validate_reconstruction(report, selection, root, path, **trusted)


def test_tampered_candidate_bytes_and_original_source_bytes_cannot_pass(tmp_path):
    selection, root, trusted = fixture(tmp_path)
    path = tmp_path / "candidate.jsonl"
    report = graphs.reconstruct_to_jsonl(selection, root, path, **trusted)
    original = path.read_bytes()
    path.write_bytes(original.replace(b'"admitted":false', b'"admitted":true', 1))
    with pytest.raises(graphs.PrimaryGraphReconstructionError, match="candidate bytes"):
        graphs.validate_reconstruction(report, selection, root, path, **trusted)
    path.write_bytes(original)
    source = root / selection["descriptors"][0]["relative_path"]
    damaged = bytearray(source.read_bytes()); damaged[8] ^= 1; source.write_bytes(damaged)
    with pytest.raises(manifests.PrimaryGraphManifestError, match="SHA256"):
        graphs.validate_reconstruction(report, selection, root, path, **trusted)


def test_atomic_export_never_rewrites_existing_output_or_writes_into_source_tree(tmp_path):
    selection, root, trusted = fixture(tmp_path)
    path = tmp_path / "existing.jsonl"; path.write_bytes(b"preserve original")
    with pytest.raises(graphs.PrimaryGraphReconstructionError, match="overwrite refused"):
        graphs.reconstruct_to_jsonl(selection, root, path, **trusted)
    assert path.read_bytes() == b"preserve original"
    with pytest.raises(graphs.PrimaryGraphReconstructionError, match="immutable source"):
        graphs.reconstruct_to_jsonl(selection, root, root / "new.jsonl", **trusted)
    alias = tmp_path / "alias"; alias.symlink_to(root, target_is_directory=True)
    with pytest.raises(graphs.PrimaryGraphReconstructionError, match="unaliased"):
        graphs.reconstruct_to_jsonl(selection, root, alias / "new.jsonl", **trusted)


@pytest.mark.parametrize("option", ["max_output_bytes", "max_line_bytes"])
def test_output_bounds_leave_no_partial_candidate_or_owned_tempfile(tmp_path, option):
    selection, root, trusted = fixture(tmp_path)
    path = tmp_path / "bounded.jsonl"
    with pytest.raises(graphs.PrimaryGraphReconstructionError, match="output byte bound"):
        graphs.reconstruct_to_jsonl(selection, root, path, **trusted, limits={option: 1})
    assert not path.exists()
    assert not list(tmp_path.glob(".legal-primary-graph-*"))


def test_real_scratch_allocation_limit_refuses_population_without_partial_output(tmp_path):
    selection, root, trusted = fixture(tmp_path, nodes=[wrapped(node(str(i))) for i in range(100)], edges=[])
    path = tmp_path / "bounded.jsonl"
    with pytest.raises(graphs.PrimaryGraphReconstructionError, match="scratch failed"):
        graphs.reconstruct_to_jsonl(selection, root, path, **trusted, limits={"max_scratch_bytes": 4 * 4096})
    assert not path.exists()


def test_second_pass_population_mutation_is_detected_and_partial_output_removed(tmp_path, monkeypatch):
    selection, root, trusted = fixture(tmp_path)
    original = manifests.iter_verified_graph_rows
    calls = 0
    def changed(*args, **kwargs):
        nonlocal calls
        calls += 1
        for observation in original(*args, **kwargs):
            if calls == 2 and observation["global_ordinal"] == 2:
                observation = deepcopy(observation)
                observation["raw_row"]["record_json"] += " "
                observation["raw_row"]["record_sha256"] = hashlib.sha256(observation["raw_row"]["record_json"].encode()).hexdigest()
                observation["raw_row_sha256"] = records.raw_row_sha256(observation["raw_row"])
            yield observation
    monkeypatch.setattr(manifests, "iter_verified_graph_rows", changed)
    path = tmp_path / "changed.jsonl"
    with pytest.raises(graphs.PrimaryGraphReconstructionError, match="changed between passes"):
        graphs.reconstruct_to_jsonl(selection, root, path, **trusted)
    assert not path.exists()
    assert not list(tmp_path.glob(".legal-primary-graph-*"))


def test_literal_unknown_and_missing_producer_kinds_remain_observations(tmp_path):
    missing = node("A"); missing.pop("node_type")
    selection, root, trusted = fixture(tmp_path, nodes=[wrapped(missing), wrapped(node("B", node_type="future_unknown_kind"))])
    report = graphs.reconstruct_to_jsonl(selection, root, tmp_path / "candidate.jsonl", **trusted)
    assert report["producer_declared_kind_counts"]["graph_nodes"] == {"future_unknown_kind": 1}
    assert report["missing_or_invalid_producer_kind_rows"]["graph_nodes"] == 1
    assert report["endpoint_integrity_passed"] is False


def test_edges_reference_quarantined_cross_family_identity_as_conflict(tmp_path):
    selection, root, trusted = fixture(tmp_path, edges=[wrapped(edge("A")), wrapped(edge("other-edge"))])
    path = tmp_path / "candidate.jsonl"
    report = graphs.reconstruct_to_jsonl(selection, root, path, **trusted)
    assert report["endpoint_counts"]["source"] == {"conflicting_declared_identity": 2}
    assert read_candidate(path)[2]["disposition"] == "quarantined_unresolved_or_ambiguous_endpoint"
    assert "source_endpoint_conflicting_declared_identity" in report["blockers"]


def test_output_parent_swap_during_second_pass_is_refused_without_publication(tmp_path, monkeypatch):
    selection, root, trusted = fixture(tmp_path)
    parent = tmp_path / "outputs"; parent.mkdir()
    moved = tmp_path / "moved"
    original = manifests.iter_verified_graph_rows
    calls = 0
    def swapped(*args, **kwargs):
        nonlocal calls
        calls += 1
        for observation in original(*args, **kwargs):
            if calls == 2 and observation["global_ordinal"] == 1:
                parent.rename(moved); parent.mkdir()
            yield observation
    monkeypatch.setattr(manifests, "iter_verified_graph_rows", swapped)
    with pytest.raises(graphs.PrimaryGraphReconstructionError, match="output parent changed"):
        graphs.reconstruct_to_jsonl(selection, root, parent / "candidate.jsonl", **trusted)
    assert not list(parent.iterdir())
    assert not list(moved.iterdir())


def test_failed_exclusive_temporary_creation_never_unlinks_a_preexisting_file(tmp_path, monkeypatch):
    selection, root, trusted = fixture(tmp_path)
    monkeypatch.setattr(graphs.secrets, "token_hex", lambda size: "fixed-token")
    foreign = tmp_path / ".legal-primary-graph-fixed-token"
    foreign.write_bytes(b"foreign temporary must survive")
    with pytest.raises(FileExistsError):
        graphs.reconstruct_to_jsonl(selection, root, tmp_path / "candidate.jsonl", **trusted)
    assert foreign.read_bytes() == b"foreign temporary must survive"
    assert not (tmp_path / "candidate.jsonl").exists()


def test_publication_rollback_preserves_a_replaced_foreign_output(tmp_path, monkeypatch):
    selection, root, trusted = fixture(tmp_path)
    path = tmp_path / "candidate.jsonl"
    original = os.fsync
    def replace_then_fail(descriptor):
        if stat.S_ISDIR(os.fstat(descriptor).st_mode):
            path.unlink(); path.write_bytes(b"foreign replacement must survive")
            raise OSError("simulated directory fsync failure")
        return original(descriptor)
    monkeypatch.setattr(graphs.os, "fsync", replace_then_fail)
    with pytest.raises(OSError, match="simulated directory"):
        graphs.reconstruct_to_jsonl(selection, root, path, **trusted)
    assert path.read_bytes() == b"foreign replacement must survive"
    assert not list(tmp_path.glob(".legal-primary-graph-*"))


@pytest.mark.parametrize("family", ["graph_nodes", "graph_edges"])
def test_cross_family_identity_lookup_has_bounded_work_on_a_populated_index(family):
    # A family<> predicate scans this composite primary key. Enforce a VM-step
    # budget on the real lookup, independent of wall time or tiny fixture size.
    with graphs._database(graphs.MAX_SCRATCH_BYTES) as db:
        db.executemany("INSERT INTO ids VALUES (?,?,1,1)",
            ((kind, identity(kind + str(index))) for kind in ("graph_nodes", "graph_edges") for index in range(4096)))
        envelope = {"family": family, "disposition": "decoded_unreviewed_node" if family == "graph_nodes" else "decoded_unreviewed_edge",
                    "declared_identity": {"entry_cid": identity(family + "2048")}}
        db.set_progress_handler(lambda: 1, 1000)
        try:
            result = graphs._identity_resolution(db, envelope)
        finally:
            db.set_progress_handler(None, 0)
        assert result == {"status": "unique_declared_identity", "instances": 1, "distinct_record_variants": 1}
