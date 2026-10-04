"""Pinned native graph integrity and fail-closed benchmark decontamination."""
import hashlib
import json
import os
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from ipfs_datasets_py.logic.security_ir.cvefixes.hf_source import (
    HuggingFaceSourceIntegrityError, HuggingFaceSourcePin,
)
from ipfs_datasets_py.logic.security_ir.cvefixes.schemas import GraphNode
from ipfs_datasets_py.logic.formalization.autoencoder.security import security_cve_training_source as source


def _cid(text):
    return source.native._raw_sha256_cid(hashlib.sha256(text.encode()).digest())


SOURCE_CID = _cid("authored source, no external code")
BENCHMARK_HASH = hashlib.sha256(b"authored benchmark source").hexdigest()


def _exclusions():
    return source.BenchmarkExclusions(source_families=("https://github.com/bottlepy/bottle.git",),
        file_names=("bottle.py",), code_sha256=(BENCHMARK_HASH,))


def _node(kind, payload=None, *, source_cid=SOURCE_CID):
    return GraphNode(node_type=kind, source_cids=(source_cid,), parent_cids=(_cid("parent"),),
        config_cid=_cid("config"), payload={"grants_execution_authority": False,
            "retrieval_only": True, **(payload or {})})


def _code(payload=None):
    return _node("code_unit", {"path": "src/library.py", "polarity": "vulnerable",
        "unit_kind": "file", **(payload or {})})


def _project(nodes):
    return source._project_observations(nodes, admitted_source_cids={SOURCE_CID},
                                        exclusions=_exclusions())


def _shard(tmp_path, nodes, *, transform=None):
    rows = [{"node_cid": n.cid, "node_type": n.node_type, "entry_cid": _cid("entry"),
        "label": source._node_label(n), "properties_json": n.to_json(),
        "schema_version": source.CVEFIXES_HF_GRAPH_NODE_SCHEMA_VERSION} for n in nodes]
    if transform:
        transform(rows)
    table = pa.Table.from_pylist(rows).replace_schema_metadata({
        b"schema_version": source.CVEFIXES_HF_GRAPH_NODE_SCHEMA_VERSION.encode()})
    relative = "data/graph/nodes/part-000000.parquet"
    path = tmp_path / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, path)
    data = path.read_bytes()
    descriptor = source.native._ArtifactDescriptor.from_dict({"path": relative,
        "sha256": hashlib.sha256(data).hexdigest(), "content_id":
        source.native._raw_sha256_cid(hashlib.sha256(data).digest()),
        "byte_length": len(data), "media_type": "application/vnd.apache.parquet",
        "config_name": "graph_nodes", "row_count": len(rows)})
    return path, descriptor


def test_native_canonical_graph_round_trip_verifies_without_opening_originals(tmp_path):
    nodes = (_code(), _node("repository", {"repository": "https://github.com/example/library"}))
    _path, descriptor = _shard(tmp_path, nodes)
    assert source._read_graph_shard(tmp_path, descriptor, max_bytes=1_000_000, max_rows=8) == nodes


def test_tampered_graph_bytes_fail_before_decoding(tmp_path):
    path, descriptor = _shard(tmp_path, (_code(),))
    data = bytearray(path.read_bytes()); data[len(data) // 2] ^= 1; path.write_bytes(data)
    with pytest.raises(HuggingFaceSourceIntegrityError, match="identity differs"):
        source._read_graph_shard(tmp_path, descriptor, max_bytes=1_000_000, max_rows=8)


@pytest.mark.parametrize("change", ["cid", "authority", "label", "duplicate", "schema"])
def test_valid_artifact_digest_does_not_waive_canonical_graph_validation(tmp_path, change):
    nodes = (_code(),)
    if change == "authority":
        nodes = (_code({"grants_execution_authority": True}),)
    if change == "duplicate":
        nodes = nodes * 2
    def transform(rows):
        if change == "cid":
            obj = json.loads(rows[0]["properties_json"])
            obj["payload"]["path"] = "different.py"
            rows[0]["properties_json"] = json.dumps(obj)
        elif change == "label":
            rows[0]["label"] = "rebound label"
        elif change == "schema":
            rows[0]["schema_version"] = "wrong/v9"
    _path, descriptor = _shard(tmp_path, nodes, transform=transform)
    with pytest.raises(ValueError):
        source._read_graph_shard(tmp_path, descriptor, max_bytes=1_000_000, max_rows=8)


def test_missing_canonical_records_and_hashes_stay_quarantined_with_known_repository():
    row, = _project((_code(), _node("repository", {"repository": "https://github.com/example/library"})))
    assert row["source_families"] == ["github.com/example/library"]
    assert row["feature_counts"]["node_code_unit"] == 1
    assert row["feature_counts"]["code_unit_vulnerable"] == 1
    assert set(row["feature_counts"]) == set(source.FEATURES)
    assert row["training_admitted"] is row["grants_execution_authority"] is False
    assert set(row["reason_codes"]) == {
        "canonical_security_ir_records_absent", "code_body_hash_provenance_absent"}


@pytest.mark.parametrize("repo", ["https://github.com/bottlepy/bottle", "http://GitHub.com/BottlePy/Bottle.git/",
                                  "https://example.org/fork/bottle", "https://example.org/fork/BOTTLE.GIT/"])
def test_entire_bottle_repository_family_is_excluded_before_training(repo):
    row, = _project((_code(), _node("repository", {"repository": repo})))
    assert "benchmark_repository_family_excluded" in row["reason_codes"]
    assert not row["training_admitted"]


def test_filename_and_code_hash_overlap_both_excluded_even_in_another_repository():
    row, = _project((_code({"path": "vendor/BOTTLE.py", "body_sha256": BENCHMARK_HASH}),
                    _node("repository", {"repository": "https://github.com/other/project"})))
    assert {"benchmark_filename_excluded", "benchmark_code_hash_excluded"} <= set(row["reason_codes"])
    assert not row["training_admitted"]


def test_missing_or_ambiguous_repository_provenance_never_implies_no_overlap():
    missing, = _project((_code(),))
    assert "repository_provenance_missing_or_ambiguous" in missing["reason_codes"]
    ambiguous, = _project((_code(),
        _node("repository", {"repository": "https://github.com/example/one"}),
        _node("repository", {"repository": "https://github.com/example/two"})))
    assert "repository_provenance_missing_or_ambiguous" in ambiguous["reason_codes"]


def test_source_cid_not_in_native_admitted_routing_index_is_rejected():
    with pytest.raises(source.CVETrainingSourceError, match="unverified or rejected"):
        source._project_observations((_code(),), admitted_source_cids=set(), exclusions=_exclusions())


def test_symlink_shard_is_rejected(tmp_path):
    path, descriptor = _shard(tmp_path, (_code(),))
    target = tmp_path / "outside.parquet"; path.rename(target); path.symlink_to(target)
    with pytest.raises(HuggingFaceSourceIntegrityError):
        source._read_graph_shard(tmp_path, descriptor, max_bytes=1_000_000, max_rows=8)


def test_limits_and_raw_shard_selection_reject_before_any_file_read(tmp_path):
    pin = HuggingFaceSourcePin(revision="1" * 40, manifest_sha256="2" * 64, release_root=_cid("root"))
    for paths in [("data/original/part-000000.parquet",), ("../secret",), ()]:
        with pytest.raises(source.CVETrainingSourceError):
            source.load_bounded_cve_graph_source(metadata_root=tmp_path, data_root=tmp_path, pin=pin,
                graph_shards=paths, exclusions=_exclusions())
    _path, descriptor = _shard(tmp_path, (_code(),))
    with pytest.raises(source.CVETrainingSourceError, match="row bound"):
        source._read_graph_shard(tmp_path, descriptor, max_bytes=1_000_000, max_rows=0)


def test_exclusions_require_actual_hash_and_filename_inputs():
    with pytest.raises(source.CVETrainingSourceError):
        source.BenchmarkExclusions(source_families=(), file_names=(), code_sha256=())
    with pytest.raises(source.CVETrainingSourceError):
        source.BenchmarkExclusions(source_families=(), file_names=("../bottle.py",), code_sha256=(BENCHMARK_HASH,))
    with pytest.raises(source.CVETrainingSourceError):
        source.BenchmarkExclusions(source_families=(), file_names=("bottle.py",), code_sha256=("unverified",))


def test_live_pinned_public_control_plane_and_bounded_derived_graph_are_quarantined():
    value = os.environ.get("IPFS_CVE_QUALIFICATION_ARTIFACT_ROOT")
    if not value:
        pytest.skip("explicit pinned public qualification artifacts not configured")
    root = Path(value)
    pin = HuggingFaceSourcePin(revision="6fd5918bed34f8851430e74a149502587a953fe2",
        manifest_sha256="96865caf69f2ff8208a08d50ac07732488a8fc3b447b7aae6ad137fc0936d832",
        release_root="bafkreiaoirr52so2im23swotylyffivoubcuhvumr2oei3s3sk2v6f4vly")
    result = source.load_bounded_cve_graph_source(metadata_root=root / "publicus-cve-metadata-01",
        data_root=root / "publicus-cve-bounded-01", pin=pin,
        graph_shards=("data/graph/nodes/part-000000.parquet",),
        exclusions=source.BenchmarkExclusions(source_families=("github.com/bottlepy/bottle",),
            file_names=("bottle.py",),
            code_sha256=("761756ce31753e526c48d28ccbca13a5d2493b16fe37aff3e1e4d2efaf3a2bba",)))
    assert result["native_control_receipt"]["verified"] is True
    assert result["native_control_receipt"]["index_count"] == 9
    assert result["graph_node_count"] == 4096 and result["observed_source_count"] == 2020
    assert result["training_rows"] == [] and result["training_row_count"] == 0
    assert result["raw_originals_loaded"] is result["native_cve_adapter_invoked"] is False
    assert result["source_cid_routing_verified"] is True
    assert result["raw_source_cid_preimages_verified"] is False
    assert result["code_hash_disjointness_verified"] is result["proof_authoritative"] is False
    assert all(not row["training_admitted"] for row in result["observations"])
