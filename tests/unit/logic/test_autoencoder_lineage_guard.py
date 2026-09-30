"""Checkpoint identity is separate from architecture compatibility and admission."""
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest


SCRIPT = Path(__file__).resolve().parents[3] / "scripts/ops/legal_ir/check_autoencoder_lineage.py"
spec = importlib.util.spec_from_file_location("autoencoder_lineage_guard", SCRIPT)
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


@pytest.fixture
def inputs(tmp_path):
    checkpoint = tmp_path / "legacy.state.json"
    checkpoint.write_bytes(b"opaque checkpoint; not deserialized")
    registry = {
        "schema": guard.SCHEMA,
        "lineages": {
            "legacy_hub_v1": {
                "lineage_id": "legacy_hub_v1", "role": "distillation teacher",
                "source_baseline_commit": "a" * 40, "artifact_namespace": "legacy/v1",
                "checkpoint_policy": {"mode": "fixed_sha256", "sha256": sha(checkpoint.read_bytes()),
                                      "size_bytes": checkpoint.stat().st_size},
            },
            "current_legal_v2": {
                "lineage_id": "current_legal_v2", "role": "training student",
                "source_baseline_commit": "b" * 40, "artifact_namespace": "current/v2",
                "checkpoint_policy": {"mode": "explicit_sha256", "forbidden_sha256": [sha(checkpoint.read_bytes())]},
            },
        },
    }
    path = tmp_path / "registry.json"
    path.write_text(json.dumps(registry))
    return path, checkpoint, registry


def test_fixed_checkpoint_identity_receipt_has_no_qualification(inputs, tmp_path):
    registry, checkpoint, _ = inputs
    output = tmp_path / "receipt.json"
    result = guard.check_lineage(registry, "legacy_hub_v1", checkpoint, output_receipt=output)
    assert json.loads(output.read_text()) == result
    assert result["checkpoint"] == {"path": str(checkpoint), "sha256": sha(checkpoint.read_bytes()),
                                    "size_bytes": checkpoint.stat().st_size}
    assert result["registry"]["sha256"] == sha(registry.read_bytes())
    assert result["source_baseline_commit"] == "a" * 40
    assert result["checkpoint_identity_verified"] is True
    assert result["execution_not_started"] is True
    for key in ("runtime_compatibility_checked", "qualification", "admitted"):
        assert result[key] is False


def test_tampered_checkpoint_rejected_without_receipt(inputs, tmp_path):
    registry, checkpoint, _ = inputs
    checkpoint.write_bytes(b"replacement checkpoint")
    output = tmp_path / "receipt.json"
    with pytest.raises(ValueError, match="sha256 mismatch"):
        guard.check_lineage(registry, "legacy_hub_v1", checkpoint, output_receipt=output)
    assert not output.exists()


def test_fixed_size_checked_even_with_matching_hash(inputs):
    path, checkpoint, registry = inputs
    registry["lineages"]["legacy_hub_v1"]["checkpoint_policy"]["size_bytes"] += 1
    path.write_text(json.dumps(registry))
    with pytest.raises(ValueError, match="size_bytes mismatch"):
        guard.check_lineage(path, "legacy_hub_v1", checkpoint)


def test_unknown_lineage_rejected(inputs):
    registry, checkpoint, _ = inputs
    with pytest.raises(ValueError, match="unknown lineage"):
        guard.check_lineage(registry, "renamed_teacher", checkpoint)


def test_current_requires_explicit_digest_and_accepts_distinct_local_bytes(inputs, tmp_path):
    registry, _, _ = inputs
    checkpoint = tmp_path / "new.state"
    checkpoint.write_bytes(b"distinct current checkpoint")
    with pytest.raises(ValueError, match="requires --expected-sha256"):
        guard.check_lineage(registry, "current_legal_v2", checkpoint)
    result = guard.check_lineage(registry, "current_legal_v2", checkpoint,
                                 expected_sha256=sha(checkpoint.read_bytes()))
    assert result["lineage_id"] == "current_legal_v2"
    assert result["checkpoint_identity_verified"] is True
    assert result["runtime_compatibility_checked"] is False


def test_current_cannot_relabel_teacher_even_with_expected_digest(inputs):
    path, checkpoint, registry = inputs
    registry["lineages"]["current_legal_v2"]["checkpoint_policy"]["forbidden_sha256"] = []
    path.write_text(json.dumps(registry))
    with pytest.raises(ValueError, match="forbidden lineage"):
        guard.check_lineage(path, "current_legal_v2", checkpoint, expected_sha256=sha(checkpoint.read_bytes()))


@pytest.mark.parametrize("digest", sorted(guard.HISTORICAL_CHECKPOINTS))
def test_current_forbids_known_archived_checkpoints(inputs, digest):
    path, checkpoint, _ = inputs
    with pytest.raises(ValueError, match="forbidden lineage"):
        guard.check_lineage(path, "current_legal_v2", checkpoint, expected_sha256=digest)


def test_receipt_collision_and_input_alias_are_never_overwritten(inputs, tmp_path):
    path, checkpoint, _ = inputs
    collision = tmp_path / "receipt.json"
    collision.write_bytes(b"existing")
    with pytest.raises(FileExistsError):
        guard.check_lineage(path, "legacy_hub_v1", checkpoint, output_receipt=collision)
    assert collision.read_bytes() == b"existing"
    for input_path in (path, checkpoint):
        before = input_path.read_bytes()
        with pytest.raises(ValueError, match="aliases an input"):
            guard.check_lineage(path, "legacy_hub_v1", checkpoint, output_receipt=input_path)
        assert input_path.read_bytes() == before


def test_fixed_caller_digest_cannot_override_registry(inputs):
    path, checkpoint, _ = inputs
    with pytest.raises(ValueError, match="differs from fixed"):
        guard.check_lineage(path, "legacy_hub_v1", checkpoint, expected_sha256="f" * 64)


@pytest.mark.parametrize("bad_json", [b'{"schema":NaN}', b'{"schema":Infinity}',
                                     b'{"schema":-Infinity}', b'{"schema":1e999}'])
def test_nonfinite_registry_rejected(inputs, bad_json):
    path, checkpoint, _ = inputs
    path.write_bytes(bad_json)
    with pytest.raises(ValueError, match="nonfinite"):
        guard.check_lineage(path, "legacy_hub_v1", checkpoint)


def test_duplicate_registry_keys_rejected(inputs):
    path, checkpoint, _ = inputs
    path.write_text('{"schema":"x","schema":"y"}')
    with pytest.raises(ValueError, match="duplicate registry key"):
        guard.check_lineage(path, "legacy_hub_v1", checkpoint)


@pytest.mark.parametrize("mutation", ["mode", "sha", "commit", "size", "namespace", "same_namespace"])
def test_malformed_registry_identity_policy_rejected(inputs, mutation):
    path, checkpoint, registry = inputs
    item = registry["lineages"]["legacy_hub_v1"]
    if mutation == "mode":
        item["checkpoint_policy"]["mode"] = "best_effort"
    elif mutation == "sha":
        item["checkpoint_policy"]["sha256"] = "not a digest"
    elif mutation == "commit":
        item["source_baseline_commit"] = "main"
    elif mutation == "size":
        item["checkpoint_policy"]["size_bytes"] = True
    elif mutation == "namespace":
        item["artifact_namespace"] = "../current"
    else:
        item["artifact_namespace"] = registry["lineages"]["current_legal_v2"]["artifact_namespace"]
    path.write_text(json.dumps(registry))
    with pytest.raises(ValueError):
        guard.check_lineage(path, "legacy_hub_v1", checkpoint)


def test_concurrent_checkpoint_change_rejected(inputs, monkeypatch):
    path, checkpoint, _ = inputs
    original = guard.os.fstat
    calls = 0

    def changed_stat(descriptor):
        nonlocal calls
        calls += 1
        # Registry occupies first two fstats. Modify checkpoint before final fstat.
        if calls == 4:
            with checkpoint.open("ab") as handle:
                handle.write(b"concurrent update")
        return original(descriptor)

    monkeypatch.setattr(guard.os, "fstat", changed_stat)
    with pytest.raises(ValueError, match="changed during hashing"):
        guard.check_lineage(path, "legacy_hub_v1", checkpoint)


def test_cli_runs_in_isolated_python_without_model_imports(inputs):
    path, checkpoint, _ = inputs
    result = subprocess.run([sys.executable, "-I", str(SCRIPT), "--registry", str(path),
                             "--lineage", "legacy_hub_v1", "--checkpoint", str(checkpoint)],
                            capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    receipt = json.loads(result.stdout)
    assert receipt["execution_not_started"] is True
    assert receipt["admitted"] is False
