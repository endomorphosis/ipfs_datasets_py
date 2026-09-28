"""Campaign transfer tests with fake Hub and transport-only qualification data."""
import json
from pathlib import Path

import pytest

from ipfs_datasets_py.huggingface import autoencoder_incremental as pub
from ipfs_datasets_py.huggingface import autoencoder_incremental_download as download
from tests.unit.huggingface.test_autoencoder_incremental import package, FakeHub, child, evidence, put  # noqa: F401


class FakeClient:
    def __init__(self, files, *, fail_at=None, corrupt=None):
        self.files = files
        self.calls = []
        self.fail_at = fail_at
        self.corrupt = corrupt

    def fetch(self, repository, commit, path, destination, *, max_bytes):
        assert repository == pub.REPOSITORY and len(commit) == 40
        self.calls.append((commit, path))
        if self.fail_at == len(self.calls):
            raise OSError("simulated transport interruption")
        raw = self.files[path]
        if self.corrupt == path:
            raw = raw[:-1] + bytes([raw[-1] ^ 1])
        assert len(raw) <= max_bytes
        Path(destination).write_bytes(raw)
        return Path(destination)


def published(package):
    hub = FakeHub()
    seed = download.publish_seed_checkpoint(package.registry.artifact_path(package.anchor),
        expected_artifact=package.anchor, upload=True, api=hub)
    update = pub.publish_sparse_update(package.staged["manifest_path"], upload=True, api=hub)
    bundle = pub.load_sparse_update(package.staged["manifest_path"])
    return hub, seed["remote_anchor"], update, bundle


def fetch(package, *, client, anchor=None, suffix="download", commit="a" * 40, **kwargs):
    return download.download_sparse_update(pub.REPOSITORY, commit, package.staged["path_in_repo"],
        package.staged["manifest_artifact"]["sha256"], package.root / suffix,
        anchor_reference=anchor, client=client, **kwargs)


def test_seed_bootstrap_is_hashed_unqualified_and_idempotent(package):
    hub = FakeHub()
    path = package.registry.artifact_path(package.anchor)
    dry = download.publish_seed_checkpoint(path, expected_artifact=package.anchor)
    assert not dry["uploaded"] and dry["transport_baseline_only"] and not dry["qualified"]
    first = download.publish_seed_checkpoint(path, expected_artifact=package.anchor, upload=True, api=hub)
    again = download.publish_seed_checkpoint(path, expected_artifact=package.anchor, upload=True, api=hub)
    assert len(hub.commits) == 1 and again["remote_already_present"]
    assert first["remote_anchor"]["path_in_repo"].endswith(package.anchor["sha256"] + ".state.json")
    assert not first["admitted"] and not first["promoted"]
    assert pub._ref(path.read_bytes()) == package.anchor


def test_seed_hash_or_remote_conflict_fails(package):
    path = package.registry.artifact_path(package.anchor)
    with pytest.raises(ValueError, match="identity"):
        download.publish_seed_checkpoint(path, expected_artifact={**package.anchor, "sha256": "0" * 64})
    hub = FakeHub()
    hub.files[download._anchor_path(package.anchor)] = b"foreign state"
    with pytest.raises(download.CampaignDownloadError, match="conflict"):
        download.publish_seed_checkpoint(path, expected_artifact=package.anchor, upload=True, api=hub)


def test_first_generation_seed_download_parses_and_resumes_exact_bytes(package):
    hub = FakeHub()
    seed = download.publish_seed_checkpoint(package.registry.artifact_path(package.anchor),
        expected_artifact=package.anchor, upload=True, api=hub)
    client = FakeClient(hub.files)
    first = download.download_seed_checkpoint(seed["remote_anchor"], package.root / "seed", client=client)
    again = download.download_seed_checkpoint(seed["remote_anchor"], package.root / "seed", client=client)
    assert first["checkpoint_parsed"] and first["hash_verified"] and first["weights_downloaded"]
    assert first["materialized_checkpoint"] == package.anchor
    assert pub._ref(Path(first["materialized_checkpoint_path"]).read_bytes()) == package.anchor
    assert not first["locally_qualified"] and first["transport_baseline_only"]
    assert len(client.calls) == 1 and again["reused_files"] == 1 and again["downloaded_bytes"] == 0


def test_first_generation_seed_rejects_unknown_checkpoint_shape(package):
    raw = b'{"arbitrary_untrusted_payload": "not a model"}\n'
    ref = pub._ref(raw)
    anchor = {"repository_id": pub.REPOSITORY, "commit_sha": "a" * 40,
              "path_in_repo": download._anchor_path(ref), **ref}
    client = FakeClient({anchor["path_in_repo"]: raw})
    with pytest.raises(ValueError, match="unknown fields"):
        download.download_seed_checkpoint(anchor, package.root / "bad-seed", client=client)
    assert not (package.root / "bad-seed" / "receipts").exists()


def test_sparse_artifact_cannot_be_published_as_seed(package):
    ref = package.registry.get_version(package.candidate)["artifact"]
    with pytest.raises(ValueError):
        download.publish_seed_checkpoint(package.registry.artifact_path(ref), expected_artifact=ref)


def test_download_seed_closure_replay_and_resume(package):
    hub, anchor, update, bundle = published(package)
    client = FakeClient(hub.files)
    result = fetch(package, client=client, anchor=anchor, commit=update["commit_sha"])
    assert result["replayed"] and result["sparse_depth"] == 2 and result["weights_downloaded"]
    assert result["materialized_checkpoint"] == bundle["manifest"]["materialized_checkpoint"]
    assert pub._ref(Path(result["materialized_checkpoint_path"]).read_bytes()) == result["materialized_checkpoint"]
    assert not result["locally_qualified"] and not result["promotion_performed"]
    assert not result["registration_performed"] and not result["admitted"]
    count = len(client.calls)
    resumed = fetch(package, client=client, anchor=anchor, commit=update["commit_sha"])
    assert len(client.calls) == count and resumed["downloaded_files"] == resumed["downloaded_bytes"] == 0
    assert resumed["reused_files"] == result["downloaded_files"]


def test_local_preseed_needs_no_anchor_download(package):
    bundle = pub.load_sparse_update(package.staged["manifest_path"])
    client = FakeClient(bundle["snapshots"])
    result = fetch(package, client=client, local_anchor_resolver=package.registry.artifact_path)
    assert result["replayed"] and not any("/anchors/" in item[1] for item in client.calls)


def test_interrupted_download_reuses_verified_prefix(package):
    hub, anchor, update, _ = published(package)
    client = FakeClient(hub.files, fail_at=4)
    with pytest.raises(OSError, match="interruption"):
        fetch(package, client=client, anchor=anchor, commit=update["commit_sha"])
    completed_prefix = client.calls[:3]
    client.fail_at = None
    result = fetch(package, client=client, anchor=anchor, commit=update["commit_sha"])
    assert result["replayed"] and result["reused_files"] == 3
    assert all(client.calls.count(call) == 1 for call in completed_prefix)


@pytest.mark.parametrize("field,value", [
    ("repository_id", "someone/pretrained"), ("commit_sha", "main"),
    ("manifest_path", "../../weights.bin"), ("expected_manifest_sha256", "bad"),
])
def test_unpinned_or_foreign_selection_rejected_without_network(package, field, value):
    args = dict(repository_id=pub.REPOSITORY, commit_sha="a" * 40,
                manifest_path=package.staged["path_in_repo"],
                expected_manifest_sha256=package.staged["manifest_artifact"]["sha256"],
                destination=package.root / "invalid")
    args[field] = value
    client = FakeClient({})
    with pytest.raises(download.CampaignDownloadError):
        download.download_sparse_update(**args, client=client)
    assert client.calls == []


@pytest.mark.parametrize("change", ["foreign", "unbounded", "duplicate"])
def test_malicious_manifest_checked_before_artifact_fetch(package, change):
    bundle = pub.load_sparse_update(package.staged["manifest_path"])
    manifest = bundle["manifest"]
    if change == "foreign": manifest["files"][0]["path_in_repo"] = "models/pretrained.bin"
    elif change == "unbounded": manifest["files"][0]["bytes"] = pub.MAX_UPLOAD_BYTES + 1
    else: manifest["files"].append(manifest["files"][0])
    raw = pub._json(manifest)
    client = FakeClient({manifest["path_in_repo"]: raw})
    with pytest.raises(download.CampaignDownloadError):
        download.download_sparse_update(pub.REPOSITORY, "a" * 40, manifest["path_in_repo"],
            pub._sha(raw), package.root / "malicious", client=client,
            local_anchor_resolver=package.registry.artifact_path)
    assert len(client.calls) == 1


@pytest.mark.parametrize("change", ["path", "hash", "commit", "repository"])
def test_remote_anchor_requires_exact_explicit_campaign_reference(package, change):
    hub, anchor, _, _ = published(package)
    anchor = dict(anchor)
    if change == "path": anchor["path_in_repo"] = "unrelated/model.json"
    elif change == "hash": anchor["sha256"] = "0" * 64
    elif change == "commit": anchor["commit_sha"] = "main"
    else: anchor["repository_id"] = "someone/pretrained"
    client = FakeClient(hub.files)
    with pytest.raises(ValueError):
        fetch(package, client=client, anchor=anchor)
    assert len(client.calls) == 1


def test_missing_anchor_authorization_refuses_weight_transfers(package):
    bundle = pub.load_sparse_update(package.staged["manifest_path"])
    client = FakeClient(bundle["snapshots"])
    with pytest.raises(download.CampaignDownloadError, match="explicit remote seed"):
        fetch(package, client=client)
    assert len(client.calls) == 1


def test_corrupt_download_is_never_retained_as_verified_artifact(package):
    bundle = pub.load_sparse_update(package.staged["manifest_path"])
    patch = next(item for item in bundle["manifest"]["files"] if item["kind"] == "sparse_patch")
    client = FakeClient(bundle["snapshots"], corrupt=patch["path_in_repo"])
    with pytest.raises(ValueError, match="identity"):
        fetch(package, client=client, local_anchor_resolver=package.registry.artifact_path)
    assert not (package.root / "download" / "artifacts" / patch["sha256"]).exists()
    client.corrupt = None
    assert fetch(package, client=client, local_anchor_resolver=package.registry.artifact_path)["replayed"]


def test_downloaded_failure_receipt_cannot_acquire_qualification(package):
    bundle = pub.load_sparse_update(package.staged["manifest_path"])
    manifest = bundle["manifest"]
    manifest["formalized"] = True
    raw = pub._json(manifest)
    files = {**bundle["snapshots"], manifest["path_in_repo"]: raw}
    with pytest.raises(ValueError, match="authority"):
        download.download_sparse_update(pub.REPOSITORY, "a" * 40, manifest["path_in_repo"],
            pub._sha(raw), package.root / "invalid-flags", client=FakeClient(files),
            local_anchor_resolver=package.registry.artifact_path)
    assert not (package.root / "invalid-flags" / "materialized").exists()


def next_generation(package, monkeypatch):
    """Next worker starts from a reconstructed full prior generation locally."""
    hub, seed, first_upload, first_bundle = published(package)
    prior = {"kind": "sparse", "repository_id": pub.REPOSITORY,
             "commit_sha": first_upload["commit_sha"], "path_in_repo": package.staged["path_in_repo"],
             **package.staged["manifest_artifact"],
             "materialized_checkpoint": first_bundle["manifest"]["materialized_checkpoint"],
             "anchor_reference": {"kind": "anchor", **seed, "materialized_checkpoint": package.anchor}}
    current = package.registry.get_version(package.candidate)
    state = pub.sparse.resolve_checkpoint(current["artifact"], resolver=package.registry.artifact_path).state
    checkpoint = put(package.registry, package.root, pub.sparse.canonical_checkpoint_bytes(state))
    full_version = package.registry.register_version("next-machine-full", "fixture-model", checkpoint,
        parent_version_id=package.candidate)["version_id"]
    candidate = child(package.registry, package.root, full_version, 4.)
    proofs = package.root / "next-generation-proofs"
    proofs.mkdir()
    receipt = evidence(package.registry, proofs, candidate, monkeypatch)
    receipt_ref = put(package.registry, package.root, pub._json(receipt))
    staged = pub.stage_sparse_update(package.registry, candidate, receipt_ref,
                                     package.root / "next-generation", lane_id="test-0")
    upload = pub.publish_sparse_update(staged["manifest_path"], upload=True, api=hub)
    return hub, prior, staged, upload


def test_new_machine_reconstructs_recursive_sparse_anchor_and_resumes(package, monkeypatch):
    hub, prior, staged, uploaded = next_generation(package, monkeypatch)
    client = FakeClient(hub.files)
    kwargs = dict(anchor_reference=prior, client=client)
    result = download.download_sparse_update(pub.REPOSITORY, uploaded["commit_sha"], staged["path_in_repo"],
        staged["manifest_artifact"]["sha256"], package.root / "new-machine", **kwargs)
    assert result["replayed"] and result["sparse_depth"] == 1
    assert result["campaign_reference_depth"] == 2
    assert result["ancestor_replay"]["materialized_checkpoint"] == prior["materialized_checkpoint"]
    assert pub._ref(Path(result["materialized_checkpoint_path"]).read_bytes()) == result["materialized_checkpoint"]
    assert [path for _, path in client.calls if "/anchors/" in path] == [prior["anchor_reference"]["path_in_repo"]]
    assert len([path for path in hub.files if path.endswith(".state.json")]) == 1
    previous = list(client.calls)
    again = download.download_sparse_update(pub.REPOSITORY, uploaded["commit_sha"], staged["path_in_repo"],
        staged["manifest_artifact"]["sha256"], package.root / "new-machine", **kwargs)
    assert client.calls == previous and again["downloaded_files"] == again["downloaded_bytes"] == 0
    assert again["reused_files"] == result["downloaded_files"]
    assert not again["locally_qualified"] and not again["promotion_performed"]


@pytest.mark.parametrize("change,match", [("hash", "materialized hash"), ("cycle", "cyclic"),
                                         ("depth", "depth"), ("size", "manifest size")])
def test_recursive_ancestor_hash_cycle_depth_and_size_are_enforced(package, monkeypatch, change, match):
    hub, prior, staged, uploaded = next_generation(package, monkeypatch)
    if change == "hash":
        prior["materialized_checkpoint"] = {**prior["materialized_checkpoint"], "sha256": "0" * 64}
    elif change == "cycle":
        prior["anchor_reference"] = prior
    elif change == "depth":
        from copy import deepcopy
        for index in range(download.MAX_REFERENCE_DEPTH):
            prior = {**deepcopy(prior), "sha256": pub._sha(str(index).encode()), "anchor_reference": prior}
    else:
        prior["bytes"] += 1
    client = FakeClient(hub.files)
    with pytest.raises(ValueError, match=match):
        download.download_sparse_update(pub.REPOSITORY, uploaded["commit_sha"], staged["path_in_repo"],
            staged["manifest_artifact"]["sha256"], package.root / "invalid-ancestor",
            anchor_reference=prior, client=client)
    if change != "size":
        assert len(client.calls) == 1
    assert not (package.root / "invalid-ancestor" / "materialized").exists()


def test_direct_anchor_kind_materialized_hash_is_binding(package):
    hub, seed, _, _ = published(package)
    reference = {"kind": "anchor", **seed, "materialized_checkpoint": {**package.anchor, "sha256": "0" * 64}}
    client = FakeClient(hub.files)
    with pytest.raises(ValueError, match="exact campaign seed"):
        download.download_seed_checkpoint(reference, package.root / "bad-flat-anchor", client=client)
    assert not client.calls


def test_local_anchor_preferred_even_with_authorized_remote_seed(package):
    hub, anchor, uploaded, bundle = published(package)
    client = FakeClient(hub.files)
    result = fetch(package, client=client, anchor=anchor, commit=uploaded["commit_sha"],
                   local_anchor_resolver=package.registry.artifact_path)
    assert result["local_anchor_reused"] and result["replayed"]
    assert len(client.calls) == len(bundle["snapshots"])
    assert not any("/anchors/" in path for _, path in client.calls)


def test_local_sparse_parent_avoids_entire_ancestor_transfer(package, monkeypatch):
    hub, prior, staged, uploaded = next_generation(package, monkeypatch)
    bundle = pub.load_sparse_update(staged["manifest_path"])
    client = FakeClient(hub.files)
    result = download.download_sparse_update(pub.REPOSITORY, uploaded["commit_sha"], staged["path_in_repo"],
        staged["manifest_artifact"]["sha256"], package.root / "cached-parent-machine",
        anchor_reference=prior, client=client, local_anchor_resolver=package.registry.artifact_path)
    assert result["local_anchor_reused"] and result["ancestor_replay"] is None
    assert result["campaign_reference_depth"] == 2 and result["sparse_depth"] == 1
    assert result["anchor_checkpoint"] == prior["materialized_checkpoint"]
    assert len(client.calls) == len(bundle["snapshots"])
    assert all(path in bundle["snapshots"] for _, path in client.calls)
    assert not (package.root / "cached-parent-machine" / "ancestors").exists()


def test_recursive_download_can_reuse_older_local_generation(package, monkeypatch):
    hub, prior, staged, uploaded = next_generation(package, monkeypatch)
    client = FakeClient(hub.files)
    def older_only(ref):
        return package.registry.artifact_path(ref) if ref == package.anchor else None
    result = download.download_sparse_update(pub.REPOSITORY, uploaded["commit_sha"], staged["path_in_repo"],
        staged["manifest_artifact"]["sha256"], package.root / "older-generation-cache",
        anchor_reference=prior, client=client, local_anchor_resolver=older_only)
    assert not result["local_anchor_reused"] and result["ancestor_replay"]["local_anchor_reused"]
    assert result["campaign_reference_depth"] == 2
    assert not any("/anchors/" in path for _, path in client.calls)


def test_missing_local_anchor_falls_back_to_explicit_remote_reference(package):
    hub, anchor, uploaded, _ = published(package)
    client = FakeClient(hub.files)
    result = fetch(package, client=client, anchor=anchor, commit=uploaded["commit_sha"],
                   local_anchor_resolver=lambda ref: None)
    assert result["replayed"] and not result["local_anchor_reused"]
    assert any(path == anchor["path_in_repo"] for _, path in client.calls)


def test_corrupt_supplied_local_anchor_fails_without_remote_replacement(package):
    hub, anchor, uploaded, _ = published(package)
    local = package.root / "corrupt-local-anchor.state.json"
    raw = package.registry.artifact_path(package.anchor).read_bytes()
    local.write_bytes(raw[:-1] + bytes([raw[-1] ^ 1]))
    client = FakeClient(hub.files)
    with pytest.raises(ValueError, match="identity"):
        fetch(package, client=client, anchor=anchor, commit=uploaded["commit_sha"],
              local_anchor_resolver=lambda ref: local)
    assert len(client.calls) == 1
    assert local.read_bytes() != raw


def test_local_parent_cannot_bypass_portable_chain_validation(package, monkeypatch):
    hub, prior, staged, uploaded = next_generation(package, monkeypatch)
    prior["anchor_reference"] = prior
    client = FakeClient(hub.files)
    with pytest.raises(ValueError, match="cyclic"):
        download.download_sparse_update(pub.REPOSITORY, uploaded["commit_sha"], staged["path_in_repo"],
            staged["manifest_artifact"]["sha256"], package.root / "bad-chain-cached-parent",
            anchor_reference=prior, client=client, local_anchor_resolver=package.registry.artifact_path)
    assert len(client.calls) == 1
