"""Immutable Hub transport checks; no model or network required by these tests."""
import hashlib
import json

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import intent_action_hub_384 as hub


@pytest.fixture
def release(tmp_path, monkeypatch):
    weights = tmp_path / "weights"
    weights.write_bytes(b"transport-only numerical artifact")
    sha = hashlib.sha256(weights.read_bytes()).hexdigest()
    manifest = tmp_path / "manifest"
    manifest.write_text(json.dumps(dict(schema="intent-action-384-development-release/v1",
        repository_id=hub.REPOSITORY, checkpoint_schema="structured-source-384-autoencoder/v1",
        checkpoint_sha256=sha, production_promoted=False)))
    prefix = "experiments/action-contracts-384/v1/" + hashlib.sha256(manifest.read_bytes()).hexdigest()
    calls = []
    def download(**kwargs):
        calls.append(kwargs)
        return str(weights if kwargs["filename"].endswith("checkpoint.json") else manifest)
    import huggingface_hub
    monkeypatch.setattr(huggingface_hub, "hf_hub_download", download)
    return dict(schema=hub.SCHEMA, repository_id=hub.REPOSITORY, revision="a" * 40,
        checkpoint_path=prefix + "/checkpoint.json", checkpoint_sha256=sha), weights, manifest, calls


def test_default_is_offline_and_both_objects_share_exact_revision(release):
    ref, weights, _, calls = release
    assert hub.resolve_intent_action_checkpoint(ref) == {"checkpoint_path": str(weights), "expected_sha256": ref["checkpoint_sha256"]}
    assert len(calls) == 2 and all(c["local_files_only"] is True and c["revision"] == ref["revision"] for c in calls)


def test_download_requires_explicit_option(release):
    ref, _, _, calls = release
    hub.resolve_intent_action_checkpoint(ref, local_files_only=False)
    assert all(call["local_files_only"] is False for call in calls)


@pytest.mark.parametrize("field,value", [("revision", "main"), ("repository_id", "another/repo"),
    ("checkpoint_path", "../checkpoint.json"), ("checkpoint_sha256", "bad"), ("schema", "unknown")])
def test_bad_reference_is_rejected_before_transport(release, field, value):
    ref, _, _, calls = release
    ref[field] = value
    with pytest.raises(ValueError):
        hub.resolve_intent_action_checkpoint(ref)
    assert calls == []


@pytest.mark.parametrize("artifact", ["weights", "manifest"])
def test_corrupt_cached_bytes_cannot_enter_inference(release, artifact):
    ref, weights, manifest, _ = release
    (weights if artifact == "weights" else manifest).write_bytes(b"changed")
    with pytest.raises(ValueError, match="hash differs"):
        hub.resolve_intent_action_checkpoint(ref)
