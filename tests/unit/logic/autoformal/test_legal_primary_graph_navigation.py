"""Navigation bundles bind every projected row to independently replayed sources."""
from contextlib import contextmanager
from copy import deepcopy
import hashlib
import json

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from ipfs_datasets_py.logic.autoformal import legal_entity_index_intake as intake
from ipfs_datasets_py.logic.autoformal import legal_primary_graph_navigation as navigation
from tests.unit.logic.autoformal.test_legal_primary_graph_reconstruction import (
    edge, fixture, identity, node, read_candidate, wrapped,
)


def wire(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def commitment(path):
    raw = path.read_bytes()
    return {"sha256": sha(raw), "bytes": len(raw)}


def reseal(directory, *, report=None, change=None):
    """Adversary can reseal local files, but cannot change the external source pin."""
    manifest = json.loads((directory/navigation.MANIFEST).read_bytes())
    if report is not None:
        report["reconstruction_sha256"] = sha(wire({key: value for key, value in report.items() if key != "reconstruction_sha256"}))
        (directory/navigation.REPORT).write_bytes(wire(report)+b"\n")
        manifest["reconstruction_sha256"] = report["reconstruction_sha256"]
    manifest["files"] = {name: commitment(directory/name) for name in manifest["files"]}
    if change is not None:
        change(manifest)
    raw = wire(manifest)+b"\n"
    (directory/navigation.MANIFEST).write_bytes(raw)
    return sha(raw)


@pytest.fixture
def bundle(tmp_path):
    selection, root, trusted = fixture(tmp_path)
    output = tmp_path/"navigation"
    result = navigation.write_navigation_bundle(selection, root, output, **trusted)
    request = dict(expected_manifest_sha256=result["manifest_sha256"], selection=selection, snapshot_root=root, **trusted)
    return output, result, request


def test_complete_companion_exact_ids_original_lineage_and_false_authority(bundle, monkeypatch):
    directory, result, request = bundle
    manifest = result["manifest"]
    assert set(path.name for path in directory.iterdir()) == navigation.FILES
    assert commitment(directory/navigation.MANIFEST)["sha256"] == result["manifest_sha256"]
    assert manifest["rows"] == 3
    assert manifest["family_row_counts"] == {"graph_nodes": 2, "graph_edges": 1}
    assert manifest["source_lineage"]["revision"] == request["selection"]["revision"]
    assert manifest["source_lineage"]["manifest_sha256"] == request["selection"]["manifest_sha256"]
    assert manifest["source_shards_required"] is True
    assert manifest["coverage_scope"] == "exact_manifest_selected_primary_graph_rows_only"
    assert all(value is False for value in manifest["authority"].values())
    companion = read_candidate(directory/navigation.CANDIDATE)
    assert companion[0]["selection"]["raw_manifest_utf8"] == request["selection"]["raw_manifest_utf8"]
    assert companion[1]["declared_identity"]["entry_cid"] == identity("edge")
    assert companion[2]["original_body"]["unknown"] == {"ordered": [3, "é", 3], "admitted": True}
    table = pq.read_table(directory/navigation.INDEX)
    assert tuple(table.column_names) == navigation.FIELDS == intake.FIELDS
    actual = table.to_pylist()
    assert actual[0]["src"] == identity("A") and actual[0]["dst"] == identity("B")
    assert actual[0]["graph_kind"] == "CITES" and actual[0]["logic_role"] == "reference"
    assert actual[1]["node_id"] == identity("A") and actual[2]["node_id"] == identity("B")
    assert actual[1]["label"] == actual[2]["label"] == "Café same label"
    assert all(row[field] is False for row in actual for field in navigation.BOOLEANS)
    original = navigation.reconstruction.validate_reconstruction
    replay_calls = []
    def observed(*args, **kwargs):
        replay_calls.append(kwargs["expected_selection_sha256"])
        return original(*args, **kwargs)
    monkeypatch.setattr(navigation.reconstruction, "validate_reconstruction", observed)
    verified = navigation.validate_navigation_bundle(directory, **request)
    assert replay_calls == [request["expected_selection_sha256"]]
    assert verified["source_replayed"] is True and verified["projection_rows_verified"] == 3
    assert all(value is False for value in verified["authority"].values())


def test_existing_endpoint_census_accepts_projection_and_finds_all_exact_endpoints(bundle):
    directory, result, _ = bundle
    report = intake.census_parquet(directory/navigation.INDEX,
        expected_file_sha256=result["manifest"]["files"][navigation.INDEX]["sha256"],
        expected_rows=3, max_rows=3, batch_size=2, endpoint_details=True)
    assert report["population_complete"] is True
    assert report["duplicate_node_identities"] == 0
    assert report["disposition_counts"] == {"node_observation": 2, "edge_observation_unique_declared_endpoints": 1,
        "edge_observation_ambiguous_endpoint": 0, "edge_observation_unresolved_endpoint": 0}
    assert report["endpoint_integrity"]["nonempty_dangling_references"] == {"source": 0, "target": 0, "either": 0}
    assert report["endpoint_integrity"]["missing_endpoint_values"] == {"source": 0, "target": 0, "both": 0, "either": 0}
    assert all(value is False for value in report["authority"].values())


def test_unknown_producer_kind_is_retained_without_defaulting_to_scope_or_derivation(tmp_path):
    selection, root, trusted = fixture(tmp_path,
        nodes=[wrapped(node("A", node_type="future_kind", label=None)), wrapped(node("B"))],
        edges=[wrapped(edge("edge", edge_type="FUTURE_RELATION"))])
    output = tmp_path/"unknown"
    result = navigation.write_navigation_bundle(selection, root, output, **trusted, limits={"batch_size": 2})
    rows = pq.read_table(output/navigation.INDEX).to_pylist()
    assert rows[0]["graph_kind"] == "FUTURE_RELATION"
    assert rows[0]["meta_category"] == rows[0]["logic_role"] == "unclassified"
    assert rows[1]["graph_kind"] == "future_kind" and rows[1]["meta_category"] == "unclassified"
    assert rows[1]["label"] == ""
    assert read_candidate(output/navigation.CANDIDATE)[2]["original_body"]["label"] is None
    navigation.validate_navigation_bundle(output, expected_manifest_sha256=result["manifest_sha256"],
        selection=selection, snapshot_root=root, **trusted, limits={"batch_size": 2})


@pytest.mark.parametrize("damage", ["duplicate", "conflict", "missing", "malformed", "cross_family"])
def test_incomplete_or_conflicting_population_never_publishes_manifest(tmp_path, damage):
    nodes = [wrapped(node("A")), wrapped(node("B"))]
    edges = [wrapped(edge("edge"))]
    if damage == "duplicate": nodes.append(deepcopy(nodes[0]))
    elif damage == "conflict": nodes.append(wrapped(node("A", label="different")))
    elif damage == "missing": edges = [wrapped(edge("edge", target="outside"))]
    elif damage == "malformed": nodes[0] = wrapped(node("A"), encoded="{broken")
    else: edges = [wrapped(edge("A"))]
    selection, root, trusted = fixture(tmp_path, nodes=nodes, edges=edges)
    output = tmp_path/"blocked"
    with pytest.raises(navigation.PrimaryGraphNavigationError, match="complete conflict-free"):
        navigation.write_navigation_bundle(selection, root, output, **trusted)
    assert not (output/navigation.MANIFEST).exists()
    assert not (output/navigation.INDEX).exists()
    assert len(read_candidate(output/navigation.CANDIDATE)) == len(nodes)+len(edges)+1


@pytest.mark.parametrize("field,value", [("label", "changed"), ("src", "guessed"), ("in_formula", True)])
def test_resealed_navigation_rows_must_match_every_original_record(bundle, field, value):
    directory, _, request = bundle
    table = pq.read_table(directory/navigation.INDEX)
    rows = table.to_pylist(); rows[0][field] = value
    pq.write_table(pa.Table.from_pylist(rows, schema=table.schema), directory/navigation.INDEX)
    request["expected_manifest_sha256"] = reseal(directory)
    with pytest.raises(navigation.PrimaryGraphNavigationError, match="navigation row differs"):
        navigation.validate_navigation_bundle(directory, **request)


def test_resealed_companion_report_and_manifest_cannot_substitute_for_original_sources(bundle):
    directory, _, request = bundle
    rows = read_candidate(directory/navigation.CANDIDATE)
    rows[2]["original_body"]["unknown"]["ordered"].append("fabricated")
    rows[2]["candidate_row_sha256"] = sha(wire({key: value for key, value in rows[2].items() if key != "candidate_row_sha256"}))
    (directory/navigation.CANDIDATE).write_bytes(b"".join(wire(row)+b"\n" for row in rows))
    report = json.loads((directory/navigation.REPORT).read_bytes())
    changed = commitment(directory/navigation.CANDIDATE)
    report["candidate_sha256"], report["candidate_bytes"] = changed["sha256"], changed["bytes"]
    request["expected_manifest_sha256"] = reseal(directory, report=report)
    with pytest.raises(navigation.reconstruction.PrimaryGraphReconstructionError, match="independent complete source replay"):
        navigation.validate_navigation_bundle(directory, **request)


@pytest.mark.parametrize("damage", ["manifest_pin", "selection_pin", "source_bytes"])
def test_external_manifest_selection_and_original_shard_pins_are_all_required(bundle, damage):
    directory, _, request = bundle
    if damage == "manifest_pin": request["expected_manifest_sha256"] = "0"*64
    elif damage == "selection_pin": request["expected_selection_sha256"] = "0"*64
    else:
        source = request["snapshot_root"]/request["selection"]["descriptors"][0]["relative_path"]
        raw = bytearray(source.read_bytes()); raw[8] ^= 1; source.write_bytes(raw)
    with pytest.raises(ValueError):
        navigation.validate_navigation_bundle(directory, **request)


@pytest.mark.parametrize("field", ["authority", "source_shards_required"])
def test_resealed_manifest_does_not_accept_boolean_integer_equality(bundle, field):
    directory, _, request = bundle
    def change(manifest):
        if field == "authority": manifest[field]["admitted"] = 0
        else: manifest[field] = 1
    request["expected_manifest_sha256"] = reseal(directory, change=change)
    with pytest.raises(navigation.PrimaryGraphNavigationError, match="manifest differs from original source"):
        navigation.validate_navigation_bundle(directory, **request)


@pytest.mark.parametrize("name", [navigation.CANDIDATE, navigation.REPORT])
def test_writer_binds_readback_files_to_original_reconstruction_before_publication(tmp_path, monkeypatch, name):
    selection, root, trusted = fixture(tmp_path)
    output = tmp_path/"mutated"
    original = navigation._read_file
    changed = False
    @contextmanager
    def mutated(directory, descriptor, filename, bound, expected=None):
        nonlocal changed
        if filename == name and expected is None and not changed:
            changed = True
            path = directory/filename
            if name == navigation.CANDIDATE:
                rows = read_candidate(path)
                rows[2]["original_body"]["unknown"]["ordered"].append("changed")
                rows[2]["candidate_row_sha256"] = sha(wire({key: value for key, value in rows[2].items() if key != "candidate_row_sha256"}))
                path.write_bytes(b"".join(wire(row)+b"\n" for row in rows))
            else:
                report = json.loads(path.read_bytes()); report["unrelated_extra"] = True
                path.write_bytes(wire(report)+b"\n")
        with original(directory, descriptor, filename, bound, expected) as read:
            yield read
    monkeypatch.setattr(navigation, "_read_file", mutated)
    with pytest.raises(navigation.PrimaryGraphNavigationError, match="commitment differs from original reconstruction report"):
        navigation.write_navigation_bundle(selection, root, output, **trusted)
    assert changed and not (output/navigation.MANIFEST).exists()


def test_manifest_is_published_last_and_only_after_stream_comparison(tmp_path, monkeypatch):
    selection, root, trusted = fixture(tmp_path)
    output = tmp_path/"atomic"
    original_compare = navigation._compare
    original_link = navigation.os.link
    compared = False
    def compare(*args, **kwargs):
        nonlocal compared
        assert not (output/navigation.MANIFEST).exists()
        original_compare(*args, **kwargs)
        compared = True
    def link(source, destination, **kwargs):
        if destination == navigation.MANIFEST:
            assert compared and not (output/navigation.MANIFEST).exists()
            assert {navigation.CANDIDATE, navigation.REPORT, navigation.INDEX}.issubset(path.name for path in output.iterdir())
        return original_link(source, destination, **kwargs)
    monkeypatch.setattr(navigation, "_compare", compare)
    monkeypatch.setattr(navigation.os, "link", link)
    navigation.write_navigation_bundle(selection, root, output, **trusted)
    assert compared and (output/navigation.MANIFEST).exists()
    assert not (output/".manifest-pending.json").exists()


def test_existing_outputs_and_aliased_parents_are_never_overwritten(tmp_path):
    selection, root, trusted = fixture(tmp_path)
    output = tmp_path/"existing"; output.mkdir(); (output/"foreign").write_text("preserve")
    with pytest.raises(navigation.PrimaryGraphNavigationError, match="overwrite refused"):
        navigation.write_navigation_bundle(selection, root, output, **trusted)
    assert (output/"foreign").read_text() == "preserve"
    alias = tmp_path/"alias"; alias.symlink_to(output, target_is_directory=True)
    with pytest.raises(navigation.PrimaryGraphNavigationError, match="nonaliased"):
        navigation.write_navigation_bundle(selection, root, alias/"child", **trusted)
    assert not (output/"child").exists()
    with pytest.raises(navigation.PrimaryGraphNavigationError, match="source roots"):
        navigation.write_navigation_bundle(selection, root, root/"child", **trusted)


def test_failed_publication_removes_owned_files_and_preserves_foreign_files(tmp_path, monkeypatch):
    selection, root, trusted = fixture(tmp_path)
    output = tmp_path/"failed"
    original = navigation._publish_manifest
    def interrupted(directory, descriptor, manifest, maximum, owned):
        # A foreign file at the final name makes atomic publication fail.
        (directory/navigation.MANIFEST).write_bytes(b"foreign manifest bytes")
        return original(directory, descriptor, manifest, maximum, owned)
    monkeypatch.setattr(navigation, "_publish_manifest", interrupted)
    with pytest.raises(FileExistsError):
        navigation.write_navigation_bundle(selection, root, output, **trusted)
    assert (output/navigation.MANIFEST).read_bytes() == b"foreign manifest bytes"
    assert set(path.name for path in output.iterdir()) == {navigation.CANDIDATE, navigation.MANIFEST}


@pytest.mark.parametrize("option", ["max_index_bytes", "max_batch_bytes", "max_candidate_bytes", "max_rows", "max_manifest_bytes", "max_row_group_bytes"])
def test_lowered_resource_bounds_never_publish_a_partial_bundle(tmp_path, option):
    selection, root, trusted = fixture(tmp_path)
    output = tmp_path/"bounded"
    with pytest.raises(navigation.PrimaryGraphNavigationError):
        navigation.write_navigation_bundle(selection, root, output, **trusted, limits={option: 1})
    assert not (output/navigation.MANIFEST).exists()
    assert not (output/navigation.INDEX).exists()
    assert not (output/".manifest-pending.json").exists()


@pytest.mark.parametrize("damage", ["extra", "missing", "symlink", "changed_owner"])
def test_incomplete_aliased_or_differently_produced_bundle_is_not_admitted(bundle, monkeypatch, damage):
    directory, _, request = bundle
    if damage == "extra": (directory/"foreign").write_text("preserve")
    elif damage == "missing": (directory/navigation.INDEX).unlink()
    elif damage == "symlink":
        original = directory/navigation.INDEX
        outside = directory.parent/"original.parquet"; original.rename(outside); original.symlink_to(outside)
    else:
        original = navigation._pins
        monkeypatch.setattr(navigation, "_pins", lambda: {**original(), "different-owner": "0"*64})
    with pytest.raises((ValueError, OSError)):
        navigation.validate_navigation_bundle(directory, **request)


@pytest.mark.parametrize("raw", [b'{"rows":1,"rows":2}', b'{"value":1e999}', b'{"value":NaN}'])
def test_bounded_json_refuses_duplicate_keys_and_nonfinite_numbers(raw):
    with pytest.raises(navigation.PrimaryGraphNavigationError):
        navigation._parse(raw)
