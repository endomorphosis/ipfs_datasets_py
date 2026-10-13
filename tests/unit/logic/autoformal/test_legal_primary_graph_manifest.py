"""Small offline manifest/file custody fixtures; no primary-corpus scan."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from ipfs_datasets_py.logic.autoformal import legal_primary_graph_manifest as subject


def wrapper(family, index):
    body = {"entry_cid": "sha256:" + str(index) * 64, "family": family, "legal_id": "", "unknown": "Café §"}
    raw = subject.wire(body).decode()
    return {"entry_cid": body["entry_cid"], "legal_id": "", "family": family,
            "record_sha256": hashlib.sha256(raw.encode()).hexdigest(), "record_json": raw}


def descriptor(root, family, values, index=0, schema=None):
    directory, schema_id = subject.GRAPH_FAMILIES[family]
    name = f"data/graph/{directory}/part-{index:06d}.parquet"
    path = root / name; path.parent.mkdir(parents=True, exist_ok=True)
    if schema is None: schema = pa.schema([(key, pa.string()) for key in subject.FIELDS])
    pq.write_table(pa.Table.from_pylist(values, schema=schema), path, row_group_size=1)
    raw = path.read_bytes()
    return {"family": family, "first_key": None, "last_key": None, "media_type": "application/vnd.apache.parquet",
            "relative_path": name, "row_count": len(values), "schema_id": schema_id,
            "sha256": hashlib.sha256(raw).hexdigest(), "size_bytes": len(raw)}


def selection(manifest, *, population=None):
    body = {key: value for key, value in manifest.items() if key != "manifest_digest"}
    manifest = {**body, "manifest_digest": subject.digest(body)}
    raw = (json.dumps(manifest, sort_keys=True, ensure_ascii=False, indent=2) + "\n").encode()
    if population is None:
        population = {family: {"files": sum(d["family"] == family for d in manifest["artifacts"]),
                              "rows": sum(d["row_count"] for d in manifest["artifacts"] if d["family"] == family)}
                      for family in subject.GRAPH_FAMILIES}
    pins = {"expected_manifest_sha256": hashlib.sha256(raw).hexdigest(), "repository": "fixture/primary",
        "revision": "a" * 40, "expected_release_identity": {key: manifest[key] for key in subject.RELEASE_FIELDS},
        "expected_graph_population": population}
    return subject.select_primary_graph_manifest(raw, **pins), raw, pins


@pytest.fixture
def case(tmp_path):
    root = tmp_path / "snapshot"; root.mkdir()
    nodes = [wrapper("graph_nodes", 1), wrapper("graph_nodes", 2)]
    edges = [wrapper("graph_edges", 3)]
    descriptors = [descriptor(root, "graph_nodes", nodes), descriptor(root, "graph_edges", edges)]
    # Deliberately invalid extra bytes: extras are retained without decoding.
    (root / "data/graph/nodes/part-000099.parquet").write_bytes(b"old retained generation")
    manifest = {"schema_version": "uscode-sparse-graphrag-release-schema-v2",
        "hf_release_schema_version": "uscode-hf-release/v1", "release_profile": "publicus-ir-graphrag/v2",
        "dataset_repo_id": "fixture/primary", "release_point": "us/pl/119/102", "release_root_cid": "fixture-declared-root",
        "source_revision": "b" * 40, "graph_ontology_version": "uscode-legal-graph-ontology/v1",
        "producer": "uscode_hf_release.py", "artifacts": descriptors,
        "unknown_future_metadata": {"note": "Café § retained", "finite_float": 1.2}}
    selected, raw, pins = selection(manifest)
    return {"root": root, "manifest": manifest, "selection": selected, "raw": raw, "pins": pins,
            "values": nodes + edges, "tmp_path": tmp_path}


def verify(case, **kwargs):
    return subject.verify_primary_graph_files(case["selection"], case["root"],
        expected_selection_sha256=case["selection"]["selection_sha256"], **kwargs)


def rows(case, **kwargs):
    return subject.iter_verified_graph_rows(case["selection"], case["root"],
        expected_selection_sha256=case["selection"]["selection_sha256"], **kwargs)


def test_manifest_selection_recomputes_producer_digest_and_preserves_unknown_raw_metadata(case):
    selected = case["selection"]
    assert selected["raw_manifest_utf8"].encode() == case["raw"]
    assert selected["manifest"]["unknown_future_metadata"] == case["manifest"]["unknown_future_metadata"]
    assert selected["selected_file_count"] == 2 and selected["selected_row_count"] == 3
    assert selected["producer_manifest_digest_verified"] is True
    assert selected["release_root_cid_recomputed"] is False
    assert all(flag is False for flag in selected["authority"].values())


def test_every_selected_file_body_schema_footer_and_separate_extra_inventory_is_verified(case):
    result = verify(case)
    assert result["selected_file_count"] == 2 and result["selected_row_count"] == 3
    assert result["extra_file_count"] == 1
    assert result["extras"][0]["relative_path"] == "data/graph/nodes/part-000099.parquet"
    assert result["extras"][0]["body_hash_verified"] is False
    assert result["files"][0]["row_groups"][1]["start_ordinal"] == 1
    assert result == verify(case)
    assert all(flag is False for flag in result["authority"].values())


def test_bounded_iterator_preserves_exact_wrapper_ordinals_and_compact_decoder_custody(case):
    observed = list(rows(case, limits={"batch_size": 1}))
    assert [row["raw_row"] for row in observed] == case["values"]
    assert [row["global_ordinal"] for row in observed] == [0, 1, 2]
    assert [row["custody"]["row_ordinal"] for row in observed] == [0, 1, 0]
    assert [row["custody"]["row_group"] for row in observed] == [0, 1, 0]
    assert all(row["custody_sha256"] == subject.digest(row["custody"]) for row in observed)
    assert all(row["raw_row_sha256"] == subject.digest(row["raw_row"]) for row in observed)
    assert all("manifest" not in row and "raw_manifest_utf8" not in row for row in observed)
    assert all(flag is False for row in observed for flag in row["authority"].values())


@pytest.mark.parametrize("damage", ["raw_hash", "internal_digest", "release_identity", "revision", "repository"])
def test_independent_manifest_release_and_revision_pins_are_required(case, damage):
    pins, raw = deepcopy(case["pins"]), case["raw"]
    if damage == "raw_hash": pins["expected_manifest_sha256"] = "0" * 64
    elif damage == "internal_digest":
        value = json.loads(raw); value["manifest_digest"] = "0" * 64;raw = subject.wire(value)
        pins["expected_manifest_sha256"] = hashlib.sha256(raw).hexdigest();pins["expected_release_identity"]["manifest_digest"] = "0" * 64
    elif damage == "release_identity": pins["expected_release_identity"]["source_revision"] = "c" * 40
    elif damage == "revision": pins["revision"] = "main"
    else: pins["repository"] = "other/repository"
    with pytest.raises(ValueError): subject.select_primary_graph_manifest(raw, **pins)


def test_shrunk_and_resealed_manifest_cannot_shrink_independent_expected_population(case):
    changed = deepcopy(case["manifest"]); changed["artifacts"].pop()
    with pytest.raises(ValueError, match="descriptor population"):
        selection(changed, population=case["pins"]["expected_graph_population"])


@pytest.mark.parametrize("damage", ["duplicate", "path_traversal", "absolute", "path_alias", "family", "schema", "hidden_graph", "extra_descriptor_field"])
def test_unsupported_duplicate_or_escaping_descriptors_cannot_be_hidden_by_resealing(case, damage):
    value = deepcopy(case["manifest"]); d = value["artifacts"][0]
    if damage == "duplicate": value["artifacts"].append(deepcopy(d))
    elif damage == "path_traversal": d["relative_path"] = "data/graph/nodes/../outside.parquet"
    elif damage == "absolute": d["relative_path"] = "/tmp/outside.parquet"
    elif damage == "path_alias": d["relative_path"] = "data//graph/nodes/part-000000.parquet"
    elif damage == "family": d["family"] = "unrecognized_graph_family"
    elif damage == "schema": d["schema_id"] = "unrecognized-graph-schema"
    elif damage == "hidden_graph": d["family"] = "receipt"
    else: d["unreviewed_projection"] = True
    with pytest.raises(ValueError): selection(value)


def test_duplicate_json_keys_nonfinite_and_manifest_byte_bounds_are_refused(case, monkeypatch):
    duplicate = case["raw"].replace(b'"dataset_repo_id":', b'"dataset_repo_id":"duplicate","dataset_repo_id":', 1)
    for raw in (duplicate, b'{"artifacts":NaN}', b'[]'):
        with pytest.raises(ValueError): subject.select_primary_graph_manifest(raw, **case["pins"])
    monkeypatch.setattr(subject, "MAX_MANIFEST_BYTES", 1)
    with pytest.raises(ValueError, match="bounded exact"): subject.select_primary_graph_manifest(case["raw"], **case["pins"])


def test_self_resealed_selection_cannot_drop_descriptors_or_promote_authority(case):
    changed = deepcopy(case["selection"]); changed["descriptors"].pop();changed["authority"]["admitted"] = True
    changed["selection_sha256"] = subject.digest({key: value for key, value in changed.items() if key != "selection_sha256"})
    with pytest.raises(ValueError, match="complete pinned manifest regeneration"):
        subject.verify_primary_graph_files(changed, case["root"], expected_selection_sha256=changed["selection_sha256"])


@pytest.mark.parametrize("damage", ["missing", "size", "sha", "footer"])
def test_actual_selected_file_custody_is_required_before_iteration(case, damage):
    d = case["manifest"]["artifacts"][0];p = case["root"] / d["relative_path"]
    if damage == "missing": p.unlink()
    elif damage == "size": p.write_bytes(p.read_bytes()[:-1])
    elif damage == "sha":
        raw=bytearray(p.read_bytes());raw[20]^=1;p.write_bytes(raw)
    else:
        d["row_count"] += 1
        case["selection"], _, _ = selection(case["manifest"])
    with pytest.raises((ValueError, OSError)): list(rows(case))


@pytest.mark.parametrize("damage", ["extra", "type", "order", "duplicate"])
def test_exact_five_ordered_string_columns_are_required(case, damage):
    fields = [pa.field(key, pa.string()) for key in subject.FIELDS]
    if damage == "extra": fields.append(pa.field("extra", pa.string()))
    elif damage == "type": fields[0] = pa.field("entry_cid", pa.int64())
    elif damage == "order": fields[0], fields[1] = fields[1], fields[0]
    else: fields[-1] = pa.field("record_sha256", pa.string())
    schema = pa.schema(fields);d = case["manifest"]["artifacts"][0];path = case["root"] / d["relative_path"]
    pq.write_table(pa.Table.from_arrays([pa.array([], type=f.type) for f in fields], schema=schema), path)
    d.update(row_count=0, size_bytes=path.stat().st_size, sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    case["selection"], _, _ = selection(case["manifest"])
    with pytest.raises(ValueError, match="five-string"): verify(case)


@pytest.mark.parametrize("bound", ["max_files", "max_rows", "max_file_bytes", "max_total_file_bytes",
    "max_row_group_bytes", "max_decoded_bytes", "max_batch_bytes", "max_row_bytes"])
def test_finite_file_footer_and_runtime_decode_limits_never_return_partial_completion(case, bound):
    with pytest.raises(ValueError): list(rows(case, limits={bound: 1}))


def cache_layout(case):
    owner = case["tmp_path"] / "datasets--fixture--primary"
    root, blobs = owner / "snapshots" / ("a" * 40), owner / "blobs"
    root.mkdir(parents=True);blobs.mkdir()
    for source in case["root"].rglob("*.parquet"):
        target = root / source.relative_to(case["root"]);target.parent.mkdir(parents=True, exist_ok=True)
        raw=source.read_bytes();blob=blobs/hashlib.sha256(raw).hexdigest();blob.write_bytes(raw)
        target.symlink_to(os.path.relpath(blob,target.parent))
    case["root"] = root
    return blobs


def test_explicit_same_repository_hf_blob_links_are_supported_and_bound(case):
    blobs = cache_layout(case)
    result = verify(case, blobs_root=blobs)
    assert result["selected_file_count"] == 2 and result["extra_file_count"] == 1
    assert result["extras"][0]["kind"] == "same_repo_blob_link"
    assert len(list(rows(case, blobs_root=blobs))) == 3
    with pytest.raises(ValueError, match="explicit same-repository"): verify(case)


@pytest.mark.parametrize("damage", ["foreign_blob_root", "outside_link", "blob_second_link", "wrong_blob_name"])
def test_arbitrary_blob_roots_escaping_links_and_alias_chains_are_refused(case, damage):
    blobs = cache_layout(case);d = case["selection"]["descriptors"][0];link = case["root"] / d["relative_path"]
    if damage == "foreign_blob_root": blobs = case["tmp_path"];message = "not this pinned cache"
    elif damage == "outside_link":
        outside = case["tmp_path"] / d["sha256"];outside.write_bytes(link.read_bytes());link.unlink();link.symlink_to(outside);message = "escaped"
    elif damage == "blob_second_link":
        blob = blobs / d["sha256"];outside=case["tmp_path"]/"outside";outside.write_bytes(blob.read_bytes());blob.unlink();blob.symlink_to(outside);message = "unaliased"
    else:
        wrong=blobs/("0"*64);wrong.write_bytes(link.read_bytes());link.unlink();link.symlink_to(wrong);message = "escaped"
    with pytest.raises(ValueError, match=message): verify(case, blobs_root=blobs)


def test_parent_directory_alias_and_regular_file_hardlink_are_refused(case):
    parent=case["root"] / "data/graph/nodes";real=parent.with_name("real-nodes");parent.rename(real);parent.symlink_to(real,target_is_directory=True)
    with pytest.raises(ValueError, match="directory is aliased"): verify(case)
    parent.unlink();real.rename(parent)
    path=case["root"] / case["selection"]["descriptors"][0]["relative_path"]
    os.link(path,case["tmp_path"] / "hardlink")
    with pytest.raises(ValueError, match="unaliased regular"): verify(case)


@pytest.mark.parametrize("damage", ["rewrite", "replace"])
def test_live_file_changes_are_detected_on_iterator_exit(case, damage):
    iterator=rows(case);next(iterator);path=case["root"] / case["selection"]["descriptors"][0]["relative_path"]
    raw=path.read_bytes()
    if damage == "rewrite": path.write_bytes(raw)
    else:
        replacement=case["tmp_path"] / "replacement";replacement.write_bytes(raw);replacement.replace(path)
    with pytest.raises(ValueError, match="changed|replaced"): iterator.close()


def test_change_during_initial_hash_is_detected_before_any_row_is_yielded(case, monkeypatch):
    original=subject._hash;calls=0;path=case["root"] / case["selection"]["descriptors"][0]["relative_path"]
    def mutate(stream, maximum):
        nonlocal calls
        result=original(stream,maximum);calls+=1
        if calls==1: path.write_bytes(path.read_bytes())
        return result
    monkeypatch.setattr(subject,"_hash",mutate)
    with pytest.raises(ValueError, match="changed|replaced"): next(rows(case))


def test_extra_inventory_and_unknown_limit_bounds_are_explicit(case):
    (case["root"] / "data/graph/edges/part-000099.parquet").write_bytes(b"another retained generation")
    with pytest.raises(ValueError, match="extra source file inventory"): verify(case, limits={"max_extra_files":1})
    with pytest.raises(ValueError, match="unknown primary"): verify(case, limits={"silent_truncate":1})


def test_directory_entry_enumeration_stops_at_finite_bound_before_sorting(case, monkeypatch):
    original = Path.iterdir;parent = case["root"] / "data/graph/nodes";consumed = []
    def entries(path):
        if path == parent:
            for index in range(1000):
                consumed.append(index)
                yield parent / "part-000099.parquet"
        else: yield from original(path)
    monkeypatch.setattr(Path, "iterdir", entries)
    with pytest.raises(ValueError, match="extra source file inventory"):
        verify(case, limits={"max_extra_files":1})
    assert len(consumed) == case["selection"]["selected_file_count"] + 2


def test_yielded_rows_cannot_mutate_selection_or_later_custody(case):
    iterator=rows(case);first=next(iterator);first["raw_row"]["entry_cid"]="caller-edit";first["custody"]["family"]="caller-edit"
    later=list(iterator)
    assert later[0]["custody"]["family"] == "graph_nodes"
    assert case["selection"]["descriptors"][0]["family"] == "graph_nodes"
