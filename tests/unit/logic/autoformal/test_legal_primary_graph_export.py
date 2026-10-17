"""Corrected graph transport preserves original occurrences without admission.

These authored regular-file fixtures exercise the real release writer and strict
wrapper decoder. They supply no statutory review, cache migration or model work.
The historical suites' symlink fixtures are deliberately not executed here.
"""
from copy import deepcopy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from ipfs_datasets_py.logic.autoformal import legal_primary_graph_export as exports
from ipfs_datasets_py.logic.autoformal import legal_primary_graph_manifest as manifests
from ipfs_datasets_py.logic.autoformal import legal_primary_graph_records as records
from ipfs_datasets_py.processors.legal_data import uscode_hf_release as release


def _load_helper(relative_path, name):
    """Load the real pinned helper source without resolving a tests package."""
    path = Path(__file__).resolve().parents[4] / relative_path
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


_fixture_helpers = _load_helper(
    "tests/unit/logic/autoformal/test_legal_primary_graph_reconstruction.py",
    "_legal_primary_graph_export_reconstruction_fixtures")
edge, node, wrapped = _fixture_helpers.edge, _fixture_helpers.node, _fixture_helpers.wrapped
source_fixture = _fixture_helpers.fixture
_citation_helpers = _load_helper(
    "tests/unit/logic/test_kg_graph_citation_identity.py",
    "_legal_primary_graph_export_citation_fixtures")
citation_reader = _citation_helpers.citation_reader


def file_sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_bytes(root):
    return {str(path.relative_to(root)): path.read_bytes()
            for path in root.rglob("*") if path.is_file()}


def graph_case(tmp_path):
    nodes = [node("A", legal_id="usc:us:10:101", ordinal=3,
                  source={"revision": "authored", "bytes_sha256": "a" * 64},
                  unknown={"ordered": [3, "é", 3], "admitted": True}),
             node("B", legal_id="usc:us:10:102", ordinal=4)]
    edges = [edge("edge", logic_role="reference", ordinal=7,
                  source_evidence={"source_sha256": "b" * 64,
                                   "span": {"char_start": 2, "char_end": 8},
                                   "notes": ["retain", "retain"]})]
    # Whitespace and escape style are original transport data; the real writer
    # may canonicalize them, provided both original commitments remain explicit.
    first = wrapped(nodes[0], encoded=json.dumps(nodes[0], ensure_ascii=True, indent=3) + "\n")
    return source_fixture(tmp_path, nodes=[first, wrapped(nodes[1])],
                          edges=[wrapped(edges[0])])


def export_case(tmp_path, *, limits=None, profile=exports.PROFILE):
    selection, root, trusted = graph_case(tmp_path)
    output = tmp_path / "corrected"
    result = exports.export_primary_graph(selection, root, output, **trusted, limits=limits, profile=profile)
    return selection, root, trusted, output, result


def lineage(output):
    rows = [json.loads(line) for line in (output / "lineage.jsonl").read_bytes().splitlines()]
    assert rows[0]["schema"] == "legal-primary-graph-export-lineage-header/v1"
    assert all(row["schema"] == "legal-primary-graph-export-lineage-row/v1" for row in rows[1:])
    return rows[1:]


def parquet_rows(output, manifest):
    result, tables = {}, []
    for descriptor in manifest["files"]:
        if descriptor["kind"] != "parquet":
            continue
        path = output / descriptor["path"]
        with pq.ParquetFile(path) as parquet:
            table = parquet.read(use_threads=False)
        assert tuple(table.schema.names) == manifests.FIELDS
        assert all(field.type == pa.string() for field in table.schema)
        rows = table.to_pylist()
        assert len(rows) == descriptor["rows"]
        result[descriptor["path"]] = rows
        tables.append(table)
    return result, tables


def validate(output, result, selection, root, trusted, *, limits=None, profile=exports.PROFILE,
             replay_parent=None):
    return exports.validate_primary_graph_export(
        output, expected_manifest_sha256=result["manifest_sha256"],
        selection=selection, snapshot_root=root, **trusted, limits=limits,
        profile=profile, replay_parent=replay_parent)


def rewrite_manifest(output, manifest):
    raw = (json.dumps(manifest, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False) + "\n").encode()
    (output / "manifest.json").write_bytes(raw)
    return {"manifest": manifest, "manifest_sha256": hashlib.sha256(raw).hexdigest(),
            "manifest_bytes": len(raw)}


def update_descriptor(manifest, output, filename):
    descriptor = next(row for row in manifest["files"] if row["path"] == filename)
    descriptor["bytes"] = (output / filename).stat().st_size
    descriptor["sha256"] = file_sha(output / filename)


def assert_no_partial_output(tmp_path, output, before):
    assert not output.exists()
    assert {path.name for path in tmp_path.iterdir()} == before


def test_actual_writer_roundtrip_preserves_body_identity_custody_and_original_bytes(tmp_path):
    selection, root, trusted = graph_case(tmp_path)
    original_selection, original_files = deepcopy(selection), source_bytes(root)
    original_rows = list(manifests.iter_verified_graph_rows(selection, root, **trusted))
    output = tmp_path / "corrected"
    result = exports.export_primary_graph(selection, root, output, **trusted)
    manifest = result["manifest"]
    assert result["status"] == "candidate_export_complete"
    assert manifest["schema"] == "legal-primary-graph-export/v1"
    assert result["manifest_sha256"] == file_sha(output / "manifest.json")
    assert result["manifest_bytes"] == (output / "manifest.json").stat().st_size
    assert manifest["source_rows"] == manifest["exported_rows"] == 3
    assert manifest["lineage_only_rows"] == manifest["quarantined_rows"] == 0
    assert manifest["family_row_counts"] == manifest["exported_family_row_counts"] == {
        "graph_edges": 1, "graph_nodes": 2}
    assert manifest["structural_endpoint_integrity_passed"] is True
    assert sum(manifest["disposition_counts"].values()) == 3
    assert all(value is False for value in manifest["authority"].values())
    assert manifest["authority"]["accepted_graph_view_enabled"] is False
    assert manifest["authority"]["historical_flat_occurrences_repaired"] is False
    expected_names = {row["path"] for row in manifest["files"]} | {"manifest.json"}
    assert {path.name for path in output.iterdir()} == expected_names
    for descriptor in manifest["files"]:
        assert set(descriptor) == {"path", "kind", "family", "rows", "bytes", "sha256"}
        assert descriptor["bytes"] == (output / descriptor["path"]).stat().st_size
        assert descriptor["sha256"] == file_sha(output / descriptor["path"])
    saved, tables = parquet_rows(output, manifest)
    rows = lineage(output)
    assert len(rows) == len(original_rows) == 3
    for row, observation in zip(rows, original_rows, strict=True):
        assert row["global_ordinal"] == observation["global_ordinal"]
        assert row["original_raw_wrapper"] == observation["raw_row"]
        reconstruction = row["reconstruction_row"]
        assert reconstruction["custody"] == observation["custody"]
        assert reconstruction["raw_row_sha256"] == observation["raw_row_sha256"]
        assert all(flag is False for flag in reconstruction["authority"].values())
        location = row["export_location"]
        wrapper = saved[location["file"]][location["row_ordinal"]]
        assert row["exported_wrapper"] == wrapper
        decoded = records.decode_primary_graph_payload(
            wrapper, family=observation["custody"]["family"],
            expected_raw_row_sha256=records.raw_row_sha256(wrapper))
        assert decoded["original_body"] == json.loads(observation["raw_row"]["record_json"])
        assert decoded["disposition"] in {"decoded_unreviewed_node", "decoded_unreviewed_edge"}
        assert all(flag is False for flag in decoded["authority"].values())
        assert row["quarantined"] is False
        change = row["encoding_transformation"]
        assert change["profile"] == "canonical-json-encoding-only/v1"
        assert change["original_record_sha256"] == observation["raw_row"]["record_sha256"]
        assert change["exported_record_sha256"] == wrapper["record_sha256"]
        assert change["original_raw_row_sha256"] == observation["raw_row_sha256"]
        assert change["exported_raw_row_sha256"] == records.raw_row_sha256(wrapper)
        assert change["record_json_changed"] is True
        assert change["record_sha256_changed"] is True
    assert manifest["encoding_transformation_counts"] == {"unchanged": 0, "canonicalized": 3}
    bodies = [json.loads(row["record_json"]) for values in saved.values() for row in values]
    nodes = [body for body in bodies if body["family"] == "graph_nodes"]
    edge_body = next(body for body in bodies if body["family"] == "graph_edges")
    assert nodes[0]["label"] == nodes[1]["label"]
    assert nodes[0]["entry_cid"] != nodes[1]["entry_cid"]
    assert edge_body["logic_role"] == "reference" and edge_body["ordinal"] == 7
    assert edge_body["source_evidence"]["notes"] == ["retain", "retain"]
    assert citation_reader().read_graph_cites(pa.concat_tables(tables)) == [{
        "source_legal_id": "usc:us:10:101", "target_legal_id": "usc:us:10:102", "unresolved": False}]
    verified = validate(output, result, selection, root, trusted)
    assert verified["status"] == "candidate_export_verified"
    assert verified["fresh_original_replay_performed"] is True
    assert verified["manifest"] == manifest
    assert selection == original_selection and source_bytes(root) == original_files


def test_repeated_export_is_reproducible_without_rewriting_either_destination(tmp_path):
    selection, root, trusted = graph_case(tmp_path)
    first, second = tmp_path / "first", tmp_path / "second"
    a = exports.export_primary_graph(selection, root, first, **trusted)
    b = exports.export_primary_graph(selection, root, second, **trusted)
    assert a == b
    assert source_bytes(first) == source_bytes(second)


def test_explicit_2gib_profile_preserves_v1_transport_and_all_other_ceilings(tmp_path):
    selection, root, trusted = graph_case(tmp_path)
    original = source_bytes(root)
    first, second = tmp_path / "default-profile", tmp_path / "explicit-2gib-profile"
    default = exports.export_primary_graph(selection, root, first, **trusted)
    larger = exports.export_primary_graph(selection, root, second, **trusted, profile=exports.PROFILE_2GIB)
    assert exports.PROFILE == "manifest-selected-primary-entry-cid-canonical-parquet/v1"
    assert exports.DEFAULT_LIMITS["max_output_bytes"] == 1024**3
    assert default["manifest"]["profile"] == exports.PROFILE
    assert default["manifest"]["limits"] == exports.DEFAULT_LIMITS
    assert larger["manifest"]["profile"] == "manifest-selected-primary-entry-cid-canonical-parquet-2gib/v1"
    expected = deepcopy(default["manifest"])
    expected["profile"] = exports.PROFILE_2GIB
    expected["limits"]["max_output_bytes"] = 2 * 1024**3
    assert larger["manifest"] == expected
    assert {name: body for name, body in source_bytes(first).items() if name != "manifest.json"} == {
        name: body for name, body in source_bytes(second).items() if name != "manifest.json"}
    assert json.loads((second / "reconstruction.json").read_bytes())["limits"]["max_output_bytes"] == 1024**3
    assert all(value is False for value in larger["manifest"]["authority"].values())
    validate(first, default, selection, root, trusted)
    verified = validate(second, larger, selection, root, trusted, profile=exports.PROFILE_2GIB)
    assert verified["manifest"] == larger["manifest"]
    assert source_bytes(root) == original


@pytest.mark.parametrize("ceiling", [1024**3 + 1, 2 * 1024**3])
def test_only_explicit_2gib_profile_permits_larger_generation_limits(tmp_path, ceiling):
    limits = {"max_output_bytes": ceiling}
    selection, root, trusted, output, result = export_case(
        tmp_path, limits=limits, profile=exports.PROFILE_2GIB)
    assert result["manifest"]["limits"]["max_output_bytes"] == ceiling
    validate(output, result, selection, root, trusted, limits=limits, profile=exports.PROFILE_2GIB)
    with pytest.raises(exports.PrimaryGraphExportError):
        exports.validate_primary_graph_export(output, expected_manifest_sha256=result["manifest_sha256"],
            selection=selection, snapshot_root=root, **trusted, limits=limits)


@pytest.mark.parametrize("producer,consumer", [
    (exports.PROFILE, exports.PROFILE_2GIB), (exports.PROFILE_2GIB, exports.PROFILE)])
def test_validator_requires_caller_profile_even_when_generation_limits_are_identical(
        tmp_path, monkeypatch, producer, consumer):
    limits = {"max_output_bytes": 1024**3}
    selection, root, trusted, output, result = export_case(tmp_path, limits=limits, profile=producer)
    before = source_bytes(output)
    def no_reconstruction(*args, **kwargs):
        raise AssertionError("profile mismatch must refuse before original traversal")
    monkeypatch.setattr(exports, "_reconstruct", no_reconstruction)
    with pytest.raises(exports.PrimaryGraphExportError):
        validate(output, result, selection, root, trusted, limits=limits, profile=consumer)
    assert source_bytes(output) == before


@pytest.mark.parametrize("profile", [None, False, 1, "unknown-primary-export-profile/v1"])
@pytest.mark.parametrize("operation", ["export", "validate"])
def test_unknown_or_nonstring_profile_refuses_before_operation_owners(
        tmp_path, monkeypatch, profile, operation):
    selection, root, trusted = graph_case(tmp_path)
    output = tmp_path / "unknown-profile"
    before = {path.name for path in tmp_path.iterdir()}
    def no_owners():
        raise AssertionError("unknown caller profile must refuse before lazy owners")
    monkeypatch.setattr(exports, "_owners", no_owners)
    with pytest.raises(exports.PrimaryGraphExportError):
        if operation == "export":
            exports.export_primary_graph(selection, root, output, **trusted, profile=profile)
        else:
            exports.validate_primary_graph_export(output, expected_manifest_sha256="0" * 64,
                selection=selection, snapshot_root=root, **trusted, profile=profile)
    assert_no_partial_output(tmp_path, output, before)


@pytest.mark.parametrize("profile,limits", [
    (exports.PROFILE, {"max_output_bytes": 1024**3 + 1}),
    (exports.PROFILE_2GIB, {"max_output_bytes": 2 * 1024**3 + 1}),
    (exports.PROFILE_2GIB, {"max_parquet_bytes": 64 * 1024**2 + 1}),
    (exports.PROFILE_2GIB, {"rows_per_shard": 513}),
    (exports.PROFILE_2GIB, {"max_output_bytes": True}),
    (exports.PROFILE_2GIB, {"max_output_bytes": float(2 * 1024**3)}),
    (exports.PROFILE_2GIB, {"unknown_limit": 1}),
])
def test_profile_limits_cannot_implicitly_select_or_expand_a_profile(tmp_path, profile, limits):
    selection, root, trusted = graph_case(tmp_path)
    output = tmp_path / "profile-limit-refusal"
    before = {path.name for path in tmp_path.iterdir()}
    with pytest.raises(exports.PrimaryGraphExportError):
        exports.export_primary_graph(selection, root, output, **trusted, profile=profile, limits=limits)
    assert_no_partial_output(tmp_path, output, before)


def test_unknown_saved_profile_cannot_dispatch_its_own_validator(tmp_path, monkeypatch):
    selection, root, trusted, output, result = export_case(tmp_path, profile=exports.PROFILE_2GIB)
    changed = deepcopy(result["manifest"])
    changed["profile"] = "untrusted-profile/v1"
    incoming = rewrite_manifest(output, changed)
    def no_reconstruction(*args, **kwargs):
        raise AssertionError("saved unknown profile must refuse before original traversal")
    monkeypatch.setattr(exports, "_reconstruct", no_reconstruction)
    with pytest.raises(exports.PrimaryGraphExportError):
        validate(output, incoming, selection, root, trusted, profile=exports.PROFILE_2GIB)


@pytest.mark.parametrize("separate_parent", [False, True])
def test_reader_replay_parent_preserves_producer_and_uses_only_its_owned_child(
        tmp_path, monkeypatch, separate_parent):
    selection, root, trusted = graph_case(tmp_path)
    producer, consumer = tmp_path / "producer", tmp_path / "consumer"
    producer.mkdir()
    consumer.mkdir()
    output = producer / "candidate"
    result = exports.export_primary_graph(selection, root, output, **trusted, profile=exports.PROFILE_2GIB)
    producer_before, original = source_bytes(producer), source_bytes(root)
    created, real_init = [], exports._Directory.__init__
    def observe_init(self, path, *, create=False):
        if create:
            created.append(Path(path))
        real_init(self, path, create=create)
    monkeypatch.setattr(exports._Directory, "__init__", observe_init)
    replay_parent = consumer if separate_parent else None
    verified = validate(output, result, selection, root, trusted,
        profile=exports.PROFILE_2GIB, replay_parent=replay_parent)
    assert verified["status"] == "candidate_export_verified"
    expected_parent = consumer if separate_parent else producer
    assert len(created) == 1 and created[0].parent == expected_parent
    assert created[0].name.startswith(".legal-primary-replay-") and not created[0].exists()
    assert source_bytes(producer) == producer_before and source_bytes(root) == original
    assert {path.name for path in producer.iterdir()} == {"candidate"}
    assert list(consumer.iterdir()) == []


@pytest.mark.parametrize("damage", ["snapshot", "blobs", "candidate", "candidate_descendant",
                                    "missing", "parent_traversal"])
def test_reader_refuses_unsafe_replay_parent_without_mutating_producer_or_source(tmp_path, damage):
    selection, root, trusted, output, result = export_case(tmp_path, profile=exports.PROFILE_2GIB)
    blobs = tmp_path / "blobs"
    blobs.mkdir()
    if damage == "snapshot":
        parent = root
    elif damage == "blobs":
        parent = blobs
    elif damage == "candidate":
        parent = output
    elif damage == "candidate_descendant":
        parent = output / "untrusted-child"
        parent.mkdir()
    elif damage == "missing":
        parent = tmp_path / "not-created"
    else:
        parent = tmp_path / ".." / tmp_path.name
    before, original = source_bytes(output), source_bytes(root)
    inventory = {path.name for path in tmp_path.iterdir()}
    with pytest.raises((exports.PrimaryGraphExportError, OSError)):
        exports.validate_primary_graph_export(output, expected_manifest_sha256=result["manifest_sha256"],
            selection=selection, snapshot_root=root, **trusted, blobs_root=blobs,
            profile=exports.PROFILE_2GIB, replay_parent=parent)
    assert source_bytes(output) == before and source_bytes(root) == original
    assert {path.name for path in tmp_path.iterdir()} == inventory
    assert list(blobs.iterdir()) == []


def test_already_canonical_original_wrappers_are_not_rewritten(tmp_path):
    def canonical(body):
        return wrapped(body, encoded=json.dumps(body, ensure_ascii=False, sort_keys=True,
                                               separators=(",", ":")))
    selection, root, trusted = source_fixture(
        tmp_path, nodes=[canonical(node("A")), canonical(node("B"))],
        edges=[canonical(edge("edge"))])
    output = tmp_path / "canonical"
    result = exports.export_primary_graph(selection, root, output, **trusted)
    assert result["manifest"]["encoding_transformation_counts"] == {"unchanged": 3, "canonicalized": 0}
    for row in lineage(output):
        assert row["original_raw_wrapper"] == row["exported_wrapper"]
        assert row["encoding_transformation"]["record_json_changed"] is False
        assert row["encoding_transformation"]["record_sha256_changed"] is False
    validate(output, result, selection, root, trusted)


def test_exact_row_and_shard_boundaries_are_accepted(tmp_path):
    limits = {"max_rows": 3, "max_shards": 2, "rows_per_shard": 2, "batch_size": 1}
    selection, root, trusted, output, result = export_case(tmp_path, limits=limits)
    assert result["manifest"]["source_rows"] == result["manifest"]["exported_rows"] == 3
    shards = [row for row in result["manifest"]["files"] if row["kind"] == "parquet"]
    assert len(shards) == 2
    assert sorted(row["rows"] for row in shards) == [1, 2]
    validate(output, result, selection, root, trusted, limits=limits)


def test_shards_respect_small_physical_bound_and_keep_every_occurrence(tmp_path):
    selection, root, trusted, output, result = export_case(tmp_path, limits={"rows_per_shard": 1})
    parquet = [row for row in result["manifest"]["files"] if row["kind"] == "parquet"]
    assert len(parquet) == 3 and all(row["rows"] == 1 for row in parquet)
    assert sum(row["rows"] for row in parquet) == result["manifest"]["source_rows"] == 3
    assert len(lineage(output)) == 3
    validate(output, result, selection, root, trusted, limits={"rows_per_shard": 1})


def test_empty_family_never_writes_null_typed_empty_parquet(tmp_path):
    selection, root, trusted = source_fixture(tmp_path, edges=[])
    output = tmp_path / "nodes-only"
    result = exports.export_primary_graph(selection, root, output, **trusted)
    manifest = result["manifest"]
    assert manifest["source_rows"] == manifest["exported_rows"] == 2
    assert manifest["exported_family_row_counts"].get("graph_edges", 0) == 0
    descriptors = [row for row in manifest["files"] if row["kind"] == "parquet"]
    assert descriptors and all(row["family"] == "graph_nodes" for row in descriptors)
    parquet_rows(output, manifest)
    validate(output, result, selection, root, trusted)


@pytest.mark.parametrize("damage", ["duplicate", "conflict", "dangling", "edge_duplicate", "cross_family", "malformed"])
def test_quarantine_retains_complete_source_population_without_graph_or_repair_authority(tmp_path, damage):
    nodes, edges = [wrapped(node("A")), wrapped(node("B"))], [wrapped(edge("edge"))]
    if damage == "duplicate":
        nodes.append(deepcopy(nodes[0]))
    elif damage == "conflict":
        nodes.append(wrapped(node("A", label="Conflicting original body")))
    elif damage == "dangling":
        edges = [wrapped(edge("edge", target="outside"))]
    elif damage == "edge_duplicate":
        edges.append(deepcopy(edges[0]))
    elif damage == "cross_family":
        edges = [wrapped(edge("A"))]
    else:
        nodes[0] = wrapped(node("A"), encoded="{malformed")
    selection, root, trusted = source_fixture(tmp_path, nodes=nodes, edges=edges)
    before = source_bytes(root)
    output = tmp_path / "quarantined"
    result = exports.export_primary_graph(selection, root, output, **trusted)
    manifest, rows = result["manifest"], lineage(output)
    expected_rows = len(nodes) + len(edges)
    assert manifest["source_rows"] == len(rows) == expected_rows
    assert manifest["source_rows"] == manifest["exported_rows"] + manifest["lineage_only_rows"]
    assert manifest["structural_endpoint_integrity_passed"] is False
    assert manifest["quarantined_rows"] == sum(row["quarantined"] for row in rows) > 0
    assert all(flag is False for flag in manifest["authority"].values())
    assert sum(manifest["disposition_counts"].values()) == expected_rows
    assert [row["original_raw_wrapper"] for row in rows] == [
        row["raw_row"] for row in manifests.iter_verified_graph_rows(selection, root, **trusted)]
    if damage == "malformed":
        unresolved = next(row for row in rows if row["original_raw_wrapper"]["record_json"] == "{malformed")
        assert unresolved["exported_wrapper"] is unresolved["export_location"] is None
        assert unresolved["encoding_transformation"] is None
        assert manifest["lineage_only_rows"] == 1
    else:
        assert manifest["lineage_only_rows"] == 0
        assert manifest["exported_rows"] == expected_rows
    validate(output, result, selection, root, trusted)
    assert source_bytes(root) == before


def test_writer_legal_id_fallback_cannot_silently_reinterpret_original_wrapper(tmp_path):
    body = node("A", term="A term is not the absent legal citation")
    body.pop("legal_id")
    selection, root, trusted = source_fixture(tmp_path, nodes=[wrapped(body), wrapped(node("B"))])
    original = source_bytes(root)
    output = tmp_path / "refused"
    before = {path.name for path in tmp_path.iterdir()}
    with pytest.raises(ValueError):
        exports.export_primary_graph(selection, root, output, **trusted)
    assert_no_partial_output(tmp_path, output, before)
    assert source_bytes(root) == original


@pytest.mark.parametrize("option", ["max_rows", "max_shards", "max_shard_input_bytes", "max_parquet_bytes",
                                    "max_output_bytes", "max_lineage_line_bytes", "max_manifest_bytes",
                                    "max_decoded_batch_bytes"])
def test_finite_export_bounds_refuse_without_partial_destination(tmp_path, option):
    selection, root, trusted = graph_case(tmp_path)
    output = tmp_path / "bounded"
    before, original = {path.name for path in tmp_path.iterdir()}, source_bytes(root)
    with pytest.raises(ValueError):
        exports.export_primary_graph(selection, root, output, **trusted, limits={option: 1})
    assert_no_partial_output(tmp_path, output, before)
    assert source_bytes(root) == original


@pytest.mark.parametrize("limits", [{"rows_per_shard": 4097}, {"batch_size": 4097},
                                    {"max_rows": True}, {"max_rows": 0}, {"unknown_limit": 1}])
def test_unsupported_or_noninteger_limits_cannot_raise_the_owner_ceiling(tmp_path, limits):
    selection, root, trusted = graph_case(tmp_path)
    output = tmp_path / "bad-limits"
    before = {path.name for path in tmp_path.iterdir()}
    with pytest.raises(ValueError):
        exports.export_primary_graph(selection, root, output, **trusted, limits=limits)
    assert_no_partial_output(tmp_path, output, before)


def test_wrong_independent_selection_pin_cannot_export_another_population(tmp_path):
    selection, root, _trusted = graph_case(tmp_path)
    output = tmp_path / "wrong-pin"
    before = {path.name for path in tmp_path.iterdir()}
    with pytest.raises(ValueError):
        exports.export_primary_graph(selection, root, output, expected_selection_sha256="0" * 64)
    assert_no_partial_output(tmp_path, output, before)


def test_existing_destination_and_immutable_source_root_survive_refusal(tmp_path):
    selection, root, trusted = graph_case(tmp_path)
    existing = tmp_path / "existing"
    existing.mkdir()
    sentinel = existing / "retained.txt"
    sentinel.write_bytes(b"preserve prior output")
    with pytest.raises((ValueError, FileExistsError)):
        exports.export_primary_graph(selection, root, existing, **trusted)
    assert source_bytes(existing) == {"retained.txt": b"preserve prior output"}
    original = source_bytes(root)
    with pytest.raises(ValueError):
        exports.export_primary_graph(selection, root, root / "new-generation", **trusted)
    assert source_bytes(root) == original
    assert not (root / "new-generation").exists()


def test_late_real_parquet_writer_failure_leaves_no_partial_publication(tmp_path, monkeypatch):
    selection, root, trusted = graph_case(tmp_path)
    output = tmp_path / "failed"
    before, original = {path.name for path in tmp_path.iterdir()}, source_bytes(root)
    real_write, calls = pq.write_table, []
    def fail_second_write(*args, **kwargs):
        calls.append(True)
        if len(calls) == 2:
            raise OSError("authored second-Parquet failure")
        return real_write(*args, **kwargs)
    monkeypatch.setattr(pq, "write_table", fail_second_write)
    with pytest.raises((ValueError, OSError)):
        exports.export_primary_graph(selection, root, output, **trusted)
    assert len(calls) == 2
    assert_no_partial_output(tmp_path, output, before)
    assert source_bytes(root) == original


def test_lower_aggregate_budget_refuses_before_opening_generation_companions(tmp_path, monkeypatch):
    selection, root, trusted = graph_case(tmp_path)
    output = tmp_path / "early-budget"
    before = {path.name for path in tmp_path.iterdir()}
    opened = []
    real_new = exports._Directory.new
    def observe_new(directory, name):
        opened.append(name)
        return real_new(directory, name)
    monkeypatch.setattr(exports._Directory, "new", observe_new)
    with pytest.raises(exports.PrimaryGraphExportError, match="byte bound"):
        exports.export_primary_graph(selection, root, output, **trusted,
                                     limits={"max_output_bytes": 1})
    # Existing reconstruction has its own source limits; no final-generation
    # companion may even be opened when its known bytes exceed this budget.
    assert opened == []
    assert_no_partial_output(tmp_path, output, before)


@pytest.mark.parametrize("replacement", ["none", "foreign_inode", "nonempty_owned_inode"])
def test_new_destination_open_failure_removes_only_provably_owned_empty_directory(
        tmp_path, monkeypatch, replacement):
    selection, root, trusted = graph_case(tmp_path)
    output = tmp_path / "open-failure"
    original, before = source_bytes(root), {path.name for path in tmp_path.iterdir()}
    real_open, triggered = os.open, []
    def refuse_first_destination_open(path, flags, *args, **kwargs):
        if (not triggered and path == output.name and flags & os.O_DIRECTORY
                and kwargs.get("dir_fd") is not None):
            triggered.append(True)
            if replacement == "foreign_inode":
                output.rename(tmp_path / "moved-original")
                output.mkdir()
            if replacement != "none":
                (output / "foreign.txt").write_bytes(b"foreign content must survive")
            raise OSError("authored destination-open failure")
        return real_open(path, flags, *args, **kwargs)
    monkeypatch.setattr(os, "open", refuse_first_destination_open)
    with pytest.raises(OSError, match="authored destination-open failure"):
        exports.export_primary_graph(selection, root, output, **trusted)
    assert triggered == [True]
    assert source_bytes(root) == original
    if replacement == "none":
        assert_no_partial_output(tmp_path, output, before)
    else:
        assert (output / "foreign.txt").read_bytes() == b"foreign content must survive"
        expected = before | {output.name}
        if replacement == "foreign_inode":
            expected.add("moved-original")
            assert list((tmp_path / "moved-original").iterdir()) == []
        assert {path.name for path in tmp_path.iterdir()} == expected


def test_resealed_compressed_shard_is_refused_before_saved_arrow_row_allocation(tmp_path, monkeypatch):
    selection, root, trusted, output, result = export_case(tmp_path)
    manifest = deepcopy(result["manifest"])
    descriptor = next(row for row in manifest["files"]
                      if row["kind"] == "parquet" and row["family"] == "graph_edges")
    saved, _tables = parquet_rows(output, manifest)
    body = json.loads(saved[descriptor["path"]][0]["record_json"])
    body["oversized_authored_value"] = "z" * (9 * 1024 * 1024)
    target = output / descriptor["path"]
    target.write_bytes(release._encode_parquet_rows([body], family="graph_edges"))
    assert target.stat().st_size < 1024 * 1024
    update_descriptor(manifest, output, descriptor["path"])
    tampered = rewrite_manifest(output, manifest)
    info = target.stat()
    target_inode = info.st_dev, info.st_ino
    saved_row_decodes = []
    real_parquet_file = pq.ParquetFile
    class AllocationTripwire(real_parquet_file):
        def __init__(self, source, *args, **kwargs):
            self.is_untrusted_saved_shard = False
            try:
                current = os.fstat(source.fileno())
                self.is_untrusted_saved_shard = (current.st_dev, current.st_ino) == target_inode
            except (AttributeError, OSError, ValueError):
                pass
            super().__init__(source, *args, **kwargs)

        def iter_batches(self, *args, **kwargs):
            if self.is_untrusted_saved_shard:
                saved_row_decodes.append(True)
                raise AssertionError("untrusted compressed shard reached Arrow row allocation")
            return super().iter_batches(*args, **kwargs)
    monkeypatch.setattr(pq, "ParquetFile", AllocationTripwire)
    with pytest.raises(exports.PrimaryGraphExportError):
        validate(output, tampered, selection, root, trusted)
    assert saved_row_decodes == []


@pytest.mark.parametrize("damage", ["authority", "flat_repair", "population", "unknown",
                                    "authority_numeric", "population_float", "structural_numeric"])
def test_resealed_manifest_cannot_change_authority_population_or_contract(tmp_path, damage):
    selection, root, trusted, output, result = export_case(tmp_path)
    manifest = deepcopy(result["manifest"])
    if damage == "authority":
        manifest["authority"]["accepted_graph_view_enabled"] = True
    elif damage == "flat_repair":
        manifest["authority"]["historical_flat_occurrences_repaired"] = True
    elif damage == "population":
        manifest["source_rows"] -= 1
    elif damage == "authority_numeric":
        manifest["authority"]["accepted_graph_view_enabled"] = 0
    elif damage == "population_float":
        manifest["source_rows"] = float(manifest["source_rows"])
    elif damage == "structural_numeric":
        manifest["structural_endpoint_integrity_passed"] = 1
    else:
        manifest["reviewed_statutory_gold"] = True
    tampered = rewrite_manifest(output, manifest)
    with pytest.raises(ValueError):
        validate(output, tampered, selection, root, trusted)


@pytest.mark.parametrize("damage", ["number", "boolean"])
def test_resealed_lineage_cannot_alias_json_number_or_boolean_types(tmp_path, damage):
    selection, root, trusted, output, result = export_case(tmp_path)
    lines = [json.loads(raw) for raw in (output / "lineage.jsonl").read_bytes().splitlines()]
    selected = next(row for row in lines[1:]
                    if row["reconstruction_row"]["original_body"].get("ordinal") == 3)
    body = selected["reconstruction_row"]["original_body"]
    if damage == "number":
        body["ordinal"] = 3.0
    else:
        body["unknown"]["admitted"] = 1
    (output / "lineage.jsonl").write_bytes(b"".join(
        (json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()
        for row in lines))
    manifest = deepcopy(result["manifest"])
    update_descriptor(manifest, output, "lineage.jsonl")
    tampered = rewrite_manifest(output, manifest)
    with pytest.raises(exports.PrimaryGraphExportError):
        validate(output, tampered, selection, root, trusted)


@pytest.mark.parametrize("damage", ["role", "source_evidence", "endpoint"])
def test_resealed_parquet_and_lineage_cannot_replace_original_typed_edge(tmp_path, damage):
    selection, root, trusted, output, result = export_case(tmp_path)
    original = source_bytes(root)
    manifest = deepcopy(result["manifest"])
    descriptor = next(row for row in manifest["files"] if row["kind"] == "parquet" and row["family"] == "graph_edges")
    saved, _tables = parquet_rows(output, manifest)
    bodies = [json.loads(row["record_json"]) for row in saved[descriptor["path"]]]
    if damage == "role":
        bodies[0]["logic_role"] = "authored substituted role"
    elif damage == "source_evidence":
        bodies[0]["source_evidence"]["source_sha256"] = "c" * 64
    else:
        bodies[0]["target_entry_cid"] = bodies[0]["source_entry_cid"]
    path = output / descriptor["path"]
    path.write_bytes(release._encode_parquet_rows(bodies, family="graph_edges"))
    with pq.ParquetFile(path) as parquet:
        changed = parquet.read(use_threads=False).to_pylist()
    all_lines = [json.loads(raw) for raw in (output / "lineage.jsonl").read_bytes().splitlines()]
    for row in all_lines[1:]:
        location = row["export_location"]
        if location is not None and location["file"] == descriptor["path"]:
            wrapper = changed[location["row_ordinal"]]
            row["exported_wrapper"] = wrapper
            row["encoding_transformation"]["exported_record_sha256"] = wrapper["record_sha256"]
            row["encoding_transformation"]["exported_raw_row_sha256"] = records.raw_row_sha256(wrapper)
    (output / "lineage.jsonl").write_bytes(b"".join(
        (json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()
        for row in all_lines))
    update_descriptor(manifest, output, descriptor["path"])
    update_descriptor(manifest, output, "lineage.jsonl")
    tampered = rewrite_manifest(output, manifest)
    with pytest.raises(ValueError):
        validate(output, tampered, selection, root, trusted)
    assert source_bytes(root) == original


@pytest.mark.parametrize("damage", ["missing", "extra", "lineage_drop", "source_bytes", "manifest_pin"])
def test_independent_validation_rejects_missing_added_dropped_or_retargeted_inputs(tmp_path, damage):
    selection, root, trusted, output, result = export_case(tmp_path)
    if damage == "missing":
        descriptor = next(row for row in result["manifest"]["files"] if row["kind"] == "parquet")
        (output / descriptor["path"]).unlink()
    elif damage == "extra":
        (output / "foreign.txt").write_bytes(b"must remain untouched")
    elif damage == "lineage_drop":
        lines = (output / "lineage.jsonl").read_bytes().splitlines(keepends=True)
        (output / "lineage.jsonl").write_bytes(b"".join(lines[:-1]))
        manifest = deepcopy(result["manifest"])
        update_descriptor(manifest, output, "lineage.jsonl")
        result = rewrite_manifest(output, manifest)
    elif damage == "source_bytes":
        source = root / selection["descriptors"][0]["relative_path"]
        data = bytearray(source.read_bytes())
        data[8] ^= 1
        source.write_bytes(data)
    else:
        result = {**result, "manifest_sha256": "0" * 64}
    with pytest.raises((ValueError, OSError)):
        validate(output, result, selection, root, trusted)
    if damage == "extra":
        assert (output / "foreign.txt").read_bytes() == b"must remain untouched"
