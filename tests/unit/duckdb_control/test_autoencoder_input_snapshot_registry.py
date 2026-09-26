"""Owner input-export bindings, using isolated DuckDB files and synthetic bytes.

These are storage/authority checks; the corpus export factory qualifies actual
job contents separately. Nothing in this suite establishes a Lean admission.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path

import pytest

from ipfs_datasets_py.duckdb_control.autoencoder_registry import (
    AutoencoderRegistry,
    INPUT_SNAPSHOT_SCHEMA,
    MAX_INPUT_SNAPSHOT_BYTES,
    RegistryError,
)
from ipfs_datasets_py.duckdb_control.contracts import canonical_json_bytes


def _stage(registry, tmp_path, raw):
    source = tmp_path / "staging-source"
    source.write_bytes(raw)
    return registry.stage_artifact(source)


def _seed(registry, tmp_path):
    manifest = {"source_languages": ["en"], "fixture": "résumé"}
    registry.register_variant("variant", "english", manifest)
    base = _stage(registry, tmp_path, b"synthetic-checkpoint")
    version = registry.register_version("base", "english", base)
    registry.initialize_head("head", "english", "main", version["version_id"])
    job = _stage(registry, tmp_path, b'{"synthetic_job":true}')
    job_sha = "1" * 64  # Registry digest binding; factory tests parse real jobs.
    registry.create_run("run", "run-1", "english", version["version_id"],
                        {"job_spec_sha256": job_sha, "job_spec_artifact": job})
    return {
        "schema_version": INPUT_SNAPSHOT_SCHEMA,
        "run_id": "run-1", "variant_id": "english", "job_spec_sha256": job_sha,
        "job_spec_artifact": job, "variant_manifest": manifest,
        "variant_manifest_sha256": hashlib.sha256(canonical_json_bytes(manifest)).hexdigest(),
        "artifact_root": str(registry.artifact_root),
    }


def _register(registry, artifact, snapshot, operation="export"):
    return registry.register_input_snapshot(operation, "run-1", artifact,
                                           snapshot["job_spec_sha256"],
                                           snapshot["variant_manifest_sha256"])


@pytest.mark.parametrize("status", ["queued", "running", "completed", "failed"])
def test_input_export_preserves_execution_and_promotion_state(tmp_path, status):
    with AutoencoderRegistry(tmp_path / "owner.duckdb", tmp_path / "cas") as registry:
        snapshot = _seed(registry, tmp_path)
        if status != "queued":
            lease = registry.claim_run("claim", "run-1", "worker")["lease"]
            if status == "failed":
                registry.fail_run("fail", lease, {"admitted": False})
            elif status == "completed":
                result = _stage(registry, tmp_path, b"synthetic-result")
                registry.complete_run("complete", lease, result, {"admitted": False})
        run_before = registry.get_run("run-1")
        head_before = registry.resolve_head("english", "main")
        with registry._transaction() as cx:
            versions_before = cx.execute("SELECT count(*) FROM autoencoder_control.versions").fetchone()[0]
        artifact = _stage(registry, tmp_path, canonical_json_bytes(snapshot))
        receipt = _register(registry, artifact, snapshot)
        assert receipt["artifact"] == artifact
        assert receipt["scope"] == "immutable_inputs_only"
        assert receipt["command"] == "RegisterInputSnapshot"
        assert receipt["admitted"] is False
        assert receipt["execution_authorized"] is False
        assert receipt["promotion_authorized"] is False
        assert registry.get_run("run-1") == run_before
        assert registry.resolve_head("english", "main") == head_before
        with registry._transaction() as cx:
            assert cx.execute("SELECT count(*) FROM autoencoder_control.versions").fetchone()[0] == versions_before
            kind, event_json = cx.execute("SELECT kind,event_data FROM autoencoder_control.events WHERE event_id=?", [receipt["event_id"]]).fetchone()
            assert kind == "input_snapshot_registered"
            assert json.loads(event_json)["artifact"] == artifact
            assert cx.execute("SELECT consumer,status,lease FROM autoencoder_control.outbox WHERE event_id=?", [receipt["event_id"]]).fetchone() == ("ducklake", "pending", None)


def test_input_export_retry_is_historical_and_survives_owner_restart(tmp_path):
    db, root = tmp_path / "owner.duckdb", tmp_path / "cas"
    with AutoencoderRegistry(db, root) as registry:
        snapshot = _seed(registry, tmp_path)
        artifact = _stage(registry, tmp_path, canonical_json_bytes(snapshot))
        expected = _register(registry, artifact, snapshot)
        registry.artifact_path(artifact).unlink()
        assert _register(registry, artifact, snapshot) == expected
        with pytest.raises(RegistryError, match="missing or unreadable"):
            _register(registry, artifact, snapshot, "new-export")
    with AutoencoderRegistry(db, root, max_artifact_bytes=16) as registry:
        assert _register(registry, artifact, snapshot) == expected
        with pytest.raises(RegistryError, match="different payload"):
            _register(registry, {**artifact, "sha256": "2" * 64}, snapshot)
        with registry._transaction() as cx:
            assert cx.execute("SELECT count(*) FROM autoencoder_control.events WHERE kind='input_snapshot_registered'").fetchone()[0] == 1


@pytest.mark.parametrize("change", [
    "unknown_field", "missing_field", "schema", "run", "variant", "job_digest",
    "job_artifact", "manifest", "manifest_digest", "root", "command_digest",
])
def test_input_snapshot_cannot_substitute_registered_bindings(tmp_path, change):
    with AutoencoderRegistry(tmp_path / "owner.duckdb", tmp_path / "cas") as registry:
        original = _seed(registry, tmp_path)
        snapshot = copy.deepcopy(original)
        if change == "unknown_field":
            snapshot["execution_authorized"] = True
        elif change == "missing_field":
            del snapshot["variant_id"]
        elif change == "schema":
            snapshot["schema_version"] = "future-v2"
        elif change == "run":
            snapshot["run_id"] = "another-run"
        elif change == "variant":
            snapshot["variant_id"] = "french"
        elif change == "job_digest":
            snapshot["job_spec_sha256"] = "2" * 64
        elif change == "job_artifact":
            snapshot["job_spec_artifact"]["bytes"] += 1
        elif change == "manifest":
            snapshot["variant_manifest"]["source_languages"] = ["fr"]
            snapshot["variant_manifest_sha256"] = hashlib.sha256(canonical_json_bytes(snapshot["variant_manifest"])).hexdigest()
        elif change == "manifest_digest":
            snapshot["variant_manifest_sha256"] = "2" * 64
        elif change == "root":
            snapshot["artifact_root"] = str(tmp_path / "other-cas")
        artifact = _stage(registry, tmp_path, canonical_json_bytes(snapshot))
        command = snapshot if change != "command_digest" else {**snapshot, "job_spec_sha256": "2" * 64}
        with pytest.raises(RegistryError):
            _register(registry, artifact, command)
        with registry._transaction() as cx:
            assert cx.execute("SELECT count(*) FROM autoencoder_control.operations WHERE operation_id='export'").fetchone()[0] == 0
            assert cx.execute("SELECT count(*) FROM autoencoder_control.events WHERE kind='input_snapshot_registered'").fetchone()[0] == 0


@pytest.mark.parametrize("encoding", ["whitespace", "duplicate_key", "ascii_escape", "nonfinite"])
def test_input_snapshot_requires_exact_canonical_json(tmp_path, encoding):
    with AutoencoderRegistry(tmp_path / "owner.duckdb", tmp_path / "cas") as registry:
        snapshot = _seed(registry, tmp_path)
        raw = canonical_json_bytes(snapshot)
        if encoding == "whitespace":
            raw += b"\n"
        elif encoding == "duplicate_key":
            raw = b'{"run_id":"concealed-run",' + raw[1:]
        elif encoding == "ascii_escape":
            raw = json.dumps(snapshot, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
        else:
            raw = b'{"nonfinite":NaN,' + raw[1:]
        artifact = _stage(registry, tmp_path, raw)
        with pytest.raises(RegistryError):
            _register(registry, artifact, snapshot)


@pytest.mark.parametrize("replacement", ["corrupt", "symlink", "fifo"])
def test_replaced_snapshot_cannot_block_or_register(tmp_path, replacement):
    with AutoencoderRegistry(tmp_path / "owner.duckdb", tmp_path / "cas") as registry:
        snapshot = _seed(registry, tmp_path)
        artifact = _stage(registry, tmp_path, canonical_json_bytes(snapshot))
        path = registry.artifact_path(artifact)
        path.unlink()
        if replacement == "corrupt":
            path.write_bytes(b"x" * artifact["bytes"])
        elif replacement == "symlink":
            path.symlink_to(tmp_path / "staging-source")
        else:
            os.mkfifo(path)
        with pytest.raises(RegistryError):
            _register(registry, artifact, snapshot)


def test_oversized_snapshot_descriptor_is_rejected_before_read(tmp_path):
    with AutoencoderRegistry(tmp_path / "owner.duckdb", tmp_path / "cas") as registry:
        snapshot = _seed(registry, tmp_path)
        with pytest.raises(RegistryError, match="size bound"):
            _register(registry, {"sha256": "f" * 64, "bytes": MAX_INPUT_SNAPSHOT_BYTES + 1}, snapshot)
