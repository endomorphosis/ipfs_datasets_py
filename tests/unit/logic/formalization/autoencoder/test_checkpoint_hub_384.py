"""Public loader boundary: immutable selection, integrity and real dispatch."""
import hashlib
import importlib
import json
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import checkpoint_hub as hub


def descriptor(domain="intent_ir"):
    return {"schema": hub.DESCRIPTOR_SCHEMA, "domain_id": domain,
            "repository_id": "Publicus/intent-ir-autoencoder", "revision": "a" * 40,
            "release_prefix": "releases/test-v1", "manifest_sha256": "b" * 64}


@pytest.mark.parametrize("key,value", [
    ("revision", "main"), ("revision", "abc123"),
    ("release_prefix", "releases/../weights"),
    ("repository_id", "../other/repository"), ("manifest_sha256", "unverified"),
])
def test_rejects_unpinned_or_unsafe_hub_selection(key, value):
    selection = {**descriptor(), key: value}
    with pytest.raises(ValueError):
        hub.validate_descriptor(selection, domain="intent_ir")


def test_domain_cannot_be_relabelled():
    with pytest.raises(ValueError, match="domain mismatch"):
        hub.validate_descriptor(descriptor(), domain="security_ir")


def package(tmp_path):
    checkpoint = tmp_path / "original.json"
    checkpoint.write_text('{"trained": true}')
    destination = tmp_path / "release"
    manifest = hub.build_package("intent_ir", checkpoint, destination,
        provenance={"scope": "test"}, validation={"scope": "test"})
    digest = hashlib.sha256((destination / "manifest.json").read_bytes()).hexdigest()
    return destination, manifest, digest


def test_changed_weights_fail_before_runtime_loading(tmp_path):
    directory, _, digest = package(tmp_path)
    (directory / "checkpoint.json").write_text('{"trained": false}')
    with pytest.raises(ValueError, match="SHA256 mismatch"):
        hub.open_local_autoencoder("intent_ir", directory, manifest_sha256=digest)


@pytest.mark.parametrize("name", ["../checkpoint.json", "/tmp/checkpoint.json", "a/../../b", "a\\b"])
def test_manifest_cannot_escape_release_directory(tmp_path, name):
    _, manifest, _ = package(tmp_path)
    manifest["files"][name] = manifest["files"].pop("checkpoint.json")
    manifest["checkpoint_file"] = name
    with pytest.raises(ValueError):
        hub.validate_manifest(manifest, domain="intent_ir")


def test_hub_cache_request_is_pinned_and_offline_flag_preserved(tmp_path, monkeypatch):
    import huggingface_hub
    directory, _, digest = package(tmp_path)
    calls = []
    def download(**kwargs):
        calls.append(kwargs)
        return str(directory / kwargs["filename"].rsplit("/", 1)[-1])
    marker = SimpleNamespace(describe=lambda: {"loaded": True}, infer=lambda rows: rows)
    monkeypatch.setattr(huggingface_hub, "hf_hub_download", download)
    monkeypatch.setattr(hub, "_instantiate", lambda manifest, paths: marker)
    selection = {**descriptor(), "manifest_sha256": digest}
    loaded = hub.open_autoencoder("intent_ir", descriptor=selection, local_files_only=True)
    assert loaded.runtime is marker
    assert all(call["revision"] == selection["revision"] and call["local_files_only"] is True for call in calls)
    assert loaded.describe()["checkpoint"] == selection


@pytest.mark.parametrize("domain", hub.DOMAINS)
def test_ir_public_entrypoint_dispatches_its_own_domain(domain, monkeypatch):
    calls = []
    monkeypatch.setattr(hub, "open_autoencoder", lambda domain, **options: calls.append((domain, options)))
    module = importlib.import_module("ipfs_datasets_py.logic." + domain)
    module.open_autoencoder(local_files_only=True)
    assert calls == [(domain, {"local_files_only": True})]


@pytest.mark.parametrize("domain", hub.DOMAINS)
def test_formalizer_uses_loaded_runtime_and_rejects_cross_domain(domain):
    module = importlib.import_module("ipfs_datasets_py.logic." + domain)
    calls = []
    runtime = SimpleNamespace(domain=domain, infer_texts=lambda texts: calls.append(texts) or {"candidate": True})
    assert module.formalize_with_autoencoder("request", autoencoder=runtime) == {"candidate": True}
    assert calls == [["request"]]
    runtime.domain = "wrong_domain"
    with pytest.raises(ValueError, match="another IR domain"):
        module.formalize_with_autoencoder("request", autoencoder=runtime)


def test_registry_exposes_explicit_384d_runtime():
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_runtime_registry import describe_runtime
    for domain in hub.DOMAINS:
        described = describe_runtime(domain, "published_384_v1")
        assert described["dimension"] == 384
        assert described["release_stage"] == "development"
        assert described["integrated"] is True


@pytest.mark.parametrize("domain", hub.DOMAINS)
def test_registered_development_release_is_domain_bound_and_immutable(domain):
    selection = hub.default_descriptor(domain)
    assert selection["domain_id"] == domain
    assert selection["repository_id"] == "Publicus/" + domain.replace("_", "-") + "-autoencoder"
    assert len(selection["revision"]) == 40 and len(selection["manifest_sha256"]) == 64
