"""Exercise actual public imports in direct-script and module subprocesses."""
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from ipfs_datasets_py.logic.autoformal.corpus_contracts import seal_record
from ipfs_datasets_py.logic.autoformal.corpus_graph import (
    build_edge,
    build_graph_snapshot,
    build_node,
)
from ipfs_datasets_py.utils.cid_utils import canonical_dag_json_bytes

ROOT = Path(__file__).resolve().parents[4]
SCRIPT = ROOT / "scripts/ops/legal_ir/validate_uscode_corpus_release.py"
MODULE = "scripts.ops.legal_ir.validate_uscode_corpus_release"


def cid(label):
    return seal_record({"schema": "cli-fixture/v1", "label": label})["record_cid"]


@pytest.fixture
def snapshot_input(tmp_path):
    rule = build_node(node_type="norm_assertion", stable_id="1 USC 2(a):rule:0",
        content_cid=cid("assertion"), source_occurrence_cids=[cid("occurrence")],
        interpretation_cids=[cid("interpretation")])
    actor = build_node(node_type="entity", stable_id="1 USC 2(a):actor:clerk",
                       content_cid=cid("clerk"))
    edge = build_edge(src_cid=rule["record_cid"], dst_cid=actor["record_cid"],
                      relation="HAS_ACTOR", ordinal=0, evidence_cids=[cid("binding")])
    snapshot = build_graph_snapshot([rule, actor], [edge])
    raw = canonical_dag_json_bytes(snapshot)
    path = tmp_path / "snapshot.json"
    path.write_bytes(raw)
    return path, hashlib.sha256(raw).hexdigest(), snapshot


def run_cli(arguments, *, cwd, direct=False):
    environment = dict(os.environ)
    environment["IPFS_DATASETS_PY_MINIMAL_IMPORTS"] = "1"
    environment["PYTHONPATH"] = str(ROOT)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    entrypoint = [str(SCRIPT)] if direct else ["-m", MODULE]
    result = subprocess.run([sys.executable, *entrypoint, *arguments], cwd=cwd,
        env=environment, capture_output=True, text=True, timeout=45)
    lines = result.stdout.splitlines()
    assert len(lines) == 1, (result.stdout, result.stderr)
    receipt = json.loads(lines[0])
    assert receipt["admitted"] is False
    assert receipt["formalized"] is False
    assert receipt["source_semantics_verified"] is False
    assert receipt["source_authenticity_verified"] is False
    assert receipt["proof_verified"] is False
    return result, receipt


@pytest.mark.parametrize("direct", [False, True])
def test_actual_cli_export_validate_and_readable_graph(tmp_path, snapshot_input, direct):
    source, source_sha, snapshot = snapshot_input
    bundle = tmp_path / "bundle"
    result, exported = run_cli(["export", "--snapshot", str(source), "--snapshot-sha256",
        source_sha, "--output", str(bundle)], cwd=tmp_path, direct=direct)
    assert result.returncode == 0, exported
    assert exported["status"] == "success"
    assert (exported["node_count"], exported["edge_count"]) == (2, 1)
    assert exported["snapshot_cid"] == snapshot["record_cid"]
    manifest_raw = (bundle / "manifest.json").read_bytes()
    assert hashlib.sha256(manifest_raw).hexdigest() == exported["manifest_sha256"]
    result, validated = run_cli(["validate", "--bundle", str(bundle), "--manifest-sha256",
        exported["manifest_sha256"]], cwd=tmp_path, direct=not direct)
    assert result.returncode == 0, validated
    assert validated["snapshot_cid"] == exported["snapshot_cid"]
    assert validated["manifest_cid"] == exported["manifest_cid"]
    wrong, refused = run_cli(["validate", "--bundle", str(bundle), "--manifest-sha256",
        "0" * 64], cwd=tmp_path, direct=direct)
    assert wrong.returncode != 0
    assert refused["status"] == "error"
    import pyarrow.parquet as parquet
    nodes = parquet.read_table(bundle / "nodes.parquet").to_pylist()
    assert len(nodes) == 2
    assert {row["stable_id"] for row in nodes} == {node["stable_id"] for node in snapshot["nodes"]}
    edges = parquet.read_table(bundle / "edges.parquet").to_pylist()
    assert len(edges) == 1
    assert edges[0]["src_cid"] == snapshot["edges"][0]["src_cid"]
    assert edges[0]["dst_cid"] == snapshot["edges"][0]["dst_cid"]


@pytest.mark.parametrize("arguments", [[], ["unknown"], ["export"],
    ["validate", "--bundle", "missing"], ["export", "--bad-option"]])
def test_usage_failures_are_one_json_error_record(tmp_path, arguments):
    result, receipt = run_cli(arguments, cwd=tmp_path)
    assert result.returncode != 0
    assert receipt["status"] == "error"
    assert receipt["error_type"] == "CLIError"


@pytest.mark.parametrize("direct", [False, True])
def test_help_is_a_json_receipt(tmp_path, direct):
    result, receipt = run_cli(["export", "--help"], cwd=tmp_path, direct=direct)
    assert result.returncode == 0
    assert receipt["status"] == "help"
    assert len(receipt["usage"]) == 2


@pytest.mark.parametrize("bad_sha", ["", "bad", "f" * 64])
def test_export_requires_exact_external_snapshot_digest(tmp_path, snapshot_input, bad_sha):
    source, _, _ = snapshot_input
    destination = tmp_path / "not-created"
    result, receipt = run_cli(["export", "--snapshot", str(source), "--snapshot-sha256",
        bad_sha, "--output", str(destination)], cwd=tmp_path)
    assert result.returncode != 0
    assert receipt["status"] == "error"
    assert not destination.exists()


@pytest.mark.parametrize("path_kind", ["missing", "directory", "symlink", "parent-symlink", "fifo"])
def test_snapshot_paths_must_be_regular_and_never_follow_symlinks(tmp_path, snapshot_input, path_kind):
    source, source_sha, _ = snapshot_input
    if path_kind == "missing":
        source = tmp_path / "missing"
    elif path_kind == "directory":
        source = tmp_path
    elif path_kind == "symlink":
        link = tmp_path / "snapshot-link.json"
        link.symlink_to(source)
        source = link
    elif path_kind == "parent-symlink":
        link = tmp_path / "directory-link"
        link.symlink_to(tmp_path, target_is_directory=True)
        source = link / source.name
    else:
        source = tmp_path / "input-fifo"
        os.mkfifo(source)
    destination = tmp_path / "not-created"
    result, receipt = run_cli(["export", "--snapshot", str(source), "--snapshot-sha256",
        source_sha, "--output", str(destination)], cwd=tmp_path)
    assert result.returncode != 0
    assert receipt["status"] == "error"
    assert not destination.exists()


@pytest.mark.parametrize("raw", [b"{broken", b"{}", b'{"schema":"x","schema":"y"}',
                                  b'{"bad":NaN}'])
def test_malformed_or_unsealed_snapshot_refuses_before_export(tmp_path, raw):
    source = tmp_path / "malformed.json"
    source.write_bytes(raw)
    destination = tmp_path / "not-created"
    result, receipt = run_cli(["export", "--snapshot", str(source), "--snapshot-sha256",
        hashlib.sha256(raw).hexdigest(), "--output", str(destination)], cwd=tmp_path)
    assert result.returncode != 0
    assert receipt["status"] == "error"
    assert not destination.exists()


def test_snapshot_byte_bound_is_enforced_before_json_parsing(tmp_path):
    from ipfs_datasets_py.logic.autoformal.corpus_contracts import MAX_RECORD_BYTES
    raw = b" " * (MAX_RECORD_BYTES + 1)
    source = tmp_path / "oversized.json"
    source.write_bytes(raw)
    destination = tmp_path / "not-created"
    result, receipt = run_cli(["export", "--snapshot", str(source), "--snapshot-sha256",
        hashlib.sha256(raw).hexdigest(), "--output", str(destination)], cwd=tmp_path)
    assert result.returncode != 0
    assert "bounded regular file" in receipt["error"]
    assert not destination.exists()


def test_cli_never_overwrites_existing_bundle(tmp_path, snapshot_input):
    source, source_sha, _ = snapshot_input
    bundle = tmp_path / "existing"
    bundle.mkdir()
    marker = bundle / "keep.txt"
    marker.write_text("retain original")
    result, receipt = run_cli(["export", "--snapshot", str(source), "--snapshot-sha256",
        source_sha, "--output", str(bundle)], cwd=tmp_path, direct=True)
    assert result.returncode != 0
    assert receipt["status"] == "error"
    assert marker.read_text() == "retain original"
    assert sorted(path.name for path in bundle.iterdir()) == ["keep.txt"]


def test_validate_missing_and_bad_manifest_digest_fail(tmp_path):
    for manifest_sha in ("bad", "0" * 64):
        result, receipt = run_cli(["validate", "--bundle", str(tmp_path / "missing"),
            "--manifest-sha256", manifest_sha], cwd=tmp_path)
        assert result.returncode != 0
        assert receipt["status"] == "error"


def test_validate_corrupted_snapshot_in_existing_bundle_fails(tmp_path, snapshot_input):
    source, source_sha, _ = snapshot_input
    bundle = tmp_path / "bundle"
    result, receipt = run_cli(["export", "--snapshot", str(source), "--snapshot-sha256",
        source_sha, "--output", str(bundle)], cwd=tmp_path)
    assert result.returncode == 0, receipt
    (bundle / "snapshot.json").write_bytes(b"{}")
    result, invalid = run_cli(["validate", "--bundle", str(bundle), "--manifest-sha256",
        receipt["manifest_sha256"]], cwd=tmp_path)
    assert result.returncode != 0
    assert invalid["status"] == "error"
