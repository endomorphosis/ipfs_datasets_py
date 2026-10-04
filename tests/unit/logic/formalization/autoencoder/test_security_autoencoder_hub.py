"""Real portable security inference with an inert simulated Hub transport."""
from dataclasses import replace
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder.security import security_autoencoder_hub as hub
from tests.unit.logic.formalization.autoencoder.test_codebase_autoencoder_transfer import teacher, fork, joint_inputs  # noqa: F401


@pytest.fixture
def package(joint_inputs, tmp_path):
    from ipfs_datasets_py.logic.formalization.autoencoder.security.codebase_autoencoder import train_codebase_autoencoder
    from ipfs_datasets_py.logic.formalization.autoencoder.security.security_autoencoder_checkpoint import export_security_checkpoint
    learner = train_codebase_autoencoder(**{**joint_inputs, "epochs": 2})
    descriptor = export_security_checkpoint(repository=joint_inputs["repository"], expected_receipt=learner,
        output=tmp_path / "portable-security-checkpoint")
    return Path(descriptor["output"]), descriptor, (joint_inputs, learner)


def _descriptor(package):
    return {"schema": hub.HUB_SCHEMA, "repository_id": "authored/security-autoencoder",
        "repository_type": "model", "revision": "a" * 40,
        "release_prefix": "releases/sha256-" + package[1]["manifest_sha256"],
        "manifest_sha256": package[1]["manifest_sha256"]}


def _fetcher(package):
    calls = []
    def fetch(repo, revision, path):
        calls.append((repo, revision, path))
        assert repo == "authored/security-autoencoder" and revision == "a" * 40
        return (package[0] / path.rsplit("/", 1)[1]).read_bytes()
    return fetch, calls


def test_download_uses_native_pinned_verification_and_warm_offline_reuse(package, tmp_path):
    fetch, calls = _fetcher(package)
    descriptor = _descriptor(package)
    first = hub.download_security_checkpoint(descriptor=descriptor, cache_root=tmp_path / "cache", fetch_bytes=fetch)
    assert first["frozen_inference"] and not first["cache_hit"]
    assert first["checkpoint"]["manifest_sha256"] == descriptor["manifest_sha256"]
    assert len(calls) == first["downloaded_files"]
    assert all(revision == descriptor["revision"] and path.startswith(descriptor["release_prefix"] + "/")
               for _, revision, path in calls)
    assert first["provider_calls"] == first["training_steps"] == 0
    assert all(path.stat().st_mode & 0o222 == 0 for path in Path(first["package"]).iterdir())
    cached = hub.download_security_checkpoint(descriptor=descriptor, cache_root=tmp_path / "cache",
        fetch_bytes=lambda *_: pytest.fail("offline cache must not download"), local_files_only=True)
    assert cached["cache_hit"] and cached["downloaded_files"] == 0


@pytest.mark.parametrize("mutation", ["revision", "type", "prefix", "extra", "legal", "digest"])
def test_invalid_hub_identity_refuses_before_transport(package, tmp_path, mutation):
    d = _descriptor(package)
    if mutation == "revision": d["revision"] = "main"
    elif mutation == "type": d["repository_type"] = "dataset"
    elif mutation == "prefix": d["release_prefix"] = "releases/../mutable"
    elif mutation == "extra": d["remote_code"] = True
    elif mutation == "legal": d["repository_id"] = "authored/legal-security-weights"
    else: d["manifest_sha256"] = "f" * 63
    with pytest.raises(ValueError):
        hub.download_security_checkpoint(descriptor=d, cache_root=tmp_path / "cache",
            fetch_bytes=lambda *_: pytest.fail("invalid descriptor must not download"))


def test_offline_miss_and_corrupt_payload_never_publish_a_cache(package, tmp_path):
    d = _descriptor(package)
    with pytest.raises(ValueError, match="offline cache"):
        hub.download_security_checkpoint(descriptor=d, cache_root=tmp_path / "cache", local_files_only=True)
    fetch, _ = _fetcher(package)
    def corrupt(repo, revision, path):
        raw = fetch(repo, revision, path)
        return raw + b" " if path.endswith("checkpoint.json") else raw
    with pytest.raises(ValueError):
        hub.download_security_checkpoint(descriptor=d, cache_root=tmp_path / "cache", fetch_bytes=corrupt)
    assert not list((tmp_path / "cache").glob("security-autoencoder-*"))


def test_rebound_manifest_cannot_download_remote_python(package, tmp_path):
    d = _descriptor(package)
    manifest = json.loads((package[0] / hub.MANIFEST).read_text())
    manifest["files"]["model.py"] = {"sha256": "f" * 64, "bytes": 100}
    raw = json.dumps(manifest).encode()
    d["manifest_sha256"] = hashlib.sha256(raw).hexdigest()
    calls = []
    def fetch(*args): calls.append(args); return raw
    with pytest.raises(ValueError, match="closed development"):
        hub.download_security_checkpoint(descriptor=d, cache_root=tmp_path / "cache", fetch_bytes=fetch)
    assert len(calls) == 1


class FakeHub:
    def __init__(self, private=True):
        self.private, self.head, self.writes, self.files = private, "b" * 40, [], {}
    def repo_info(self, **kwargs): return SimpleNamespace(private=self.private, sha=self.head)
    def get_paths_info(self, **kwargs): return []
    def create_commit(self, **kwargs):
        self.writes.append(kwargs)
        assert kwargs["parent_commit"] == self.head and kwargs["repo_type"] == "model"
        for op in kwargs["operations"]:
            op.path_or_fileobj.seek(0)
            self.files[op.path_in_repo] = op.path_or_fileobj.read()
        self.head = "a" * 40
        return {"commit_sha": self.head}
    def fetch(self, repo, revision, path):
        assert revision == self.head == "a" * 40
        return self.files[path]


def _plan(package):
    return hub.plan_security_checkpoint_publication(package=package[0],
        expected_manifest_sha256=package[1]["manifest_sha256"],
        repository_id="authored/security-autoencoder", audited_parent_commit="b" * 40, private=True)


def _approval(publication):
    from ipfs_datasets_py.huggingface.publisher import PublicationApproval
    return PublicationApproval(approver="authored-test-only", approval_id="authored-explicit-approval",
        plan_digest=publication.plan.plan_digest, max_cost_usd=1.0,
        max_upload_bytes=publication.plan.to_dict()["upload_bytes"],
        credentials_scope="model:write:authored/security-autoencoder")


def test_native_publication_dry_run_and_commit_readback_are_separate(package, tmp_path, monkeypatch):
    monkeypatch.setattr(hub, "_fetch_bytes", lambda *_: pytest.fail("offline plan must not fetch"))
    publication = _plan(package)
    description = publication.to_dict()
    assert description["private"] is True and description["checkpoint_uploaded"] is False
    assert description["plan"]["remote_write_contacted"] is False
    assert description["plan"]["repository_type"] == "model"
    assert all(op["remote_path"].startswith(description["plan"]["release_prefix"] + "/")
               for op in description["plan"]["operations"])
    api = FakeHub()
    result = hub.publish_security_checkpoint(publication=publication, approval=_approval(publication),
        api=api, verification_root=tmp_path / "readback", fetch_bytes=api.fetch)
    assert len(api.writes) == 1
    assert result["checkpoint_uploaded"] and result["pinned_readback_verified"]
    assert result["hub"]["revision"] == "a" * 40 and result["inference_probe"]["executed"]
    assert result["runtime_promoted"] is result["proof_authority"] is False
    evidence = result["native_publication"]["evidence"]
    assert evidence["pinned_redownload_validation"] is True
    assert evidence["signed_reviewed_release_manifest"] is False


@pytest.mark.parametrize("change", ["approval", "visibility", "parent", "weights"])
def test_publication_refuses_drift_without_remote_write(package, tmp_path, change):
    publication = _plan(package)
    approval = _approval(publication)
    api = FakeHub()
    if change == "approval": approval = replace(approval, plan_digest="f" * 64)
    elif change == "visibility": api.private = False
    elif change == "parent": api.head = "c" * 40
    else:
        path = package[0] / "checkpoint.json"
        path.chmod(0o644); path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError):
        hub.publish_security_checkpoint(publication=publication, approval=approval, api=api,
            verification_root=tmp_path / "readback", fetch_bytes=api.fetch)
    assert api.writes == []


def test_public_release_refuses_unreviewed_development_package(package):
    with pytest.raises(ValueError, match="provenance review"):
        hub.plan_security_checkpoint_publication(package=package[0],
            expected_manifest_sha256=package[1]["manifest_sha256"],
            repository_id="authored/security-autoencoder", audited_parent_commit="b" * 40, private=False)


def test_public_release_binds_review_card_and_separate_native_approval(package, tmp_path):
    from ipfs_datasets_py.logic.formalization.autoencoder.security import security_autoencoder_checkpoint as portable
    loaded = portable.load_security_checkpoint(package[0], expected_manifest_sha256=package[1]["manifest_sha256"])
    lineage = loaded["lineage"]
    inputs, learner = package[2]
    review = {"schema": "security-autoencoder-public-provenance-review@1",
        "review_status": "reviewed_with_explicit_lineage_limits", "requested_visibility": "public",
        "release_kind": "experimental_benchmark_informed_development", "proposed_repository": "authored/security-autoencoder",
        "bottle_training_input": {"header_copyright": "Authored test fixture", "header_license": "Unspecified authored fixture",
            "source_sha256": inputs["source_hashes"]["code.py"], "raw_source_in_release": False},
        "formal_capabilities": "Authored fixture: advisory classification only, no proof authority",
        "license_statement": "Authored test provenance; no blanket inherited-weight license assertion",
        "parent_initializer": {"initializer_sha256": lineage["parent_initializer_sha256"],
            "source_checkpoint_sha256": lineage["legal_source_checkpoint_sha256"], "original_fit_history_known": False,
            "original_training_metadata_available": False, "standalone_weight_license_declared": False,
            "transferred_component": "Authored native lexical rows"},
        "security_training": {"canonical_export_manifest_sha256": lineage["canonical_export_manifest_sha256"],
            "checkpoint_sha256": lineage["training_checkpoint_sha256"], "epochs": lineage["training"]["epochs"],
            "external_pairs": lineage["training"]["security_pair_count"], "task_functions": lineage["training"]["sample_count"],
            "head_target_vocabulary": loaded["vocabularies"]["targets"], "held_out_evaluation": False,
            "dataset_family_exclusions": "Authored fixtures only"},
        "release_exclusions": ["raw source", "original teacher"], "remote_evidence": [], "source_components": []}
    exported = portable.export_security_checkpoint(repository=inputs["repository"], expected_receipt=learner,
        output=tmp_path / "public-security-package", provenance_review=review,
        model_card="# Authored security model\n\nExperimental candidates; no proof authority or held-out evaluation.\n")
    publication = hub.plan_security_checkpoint_publication(package=exported["output"],
        expected_manifest_sha256=exported["manifest_sha256"], repository_id=review["proposed_repository"],
        private=False, audited_parent_commit="b" * 40)
    remotes = {row.remote_path for row in publication.plan.operations}
    assert publication.plan.release_prefix + "/README.md" in remotes
    assert publication.plan.release_prefix + "/provenance-review.json" in remotes
    api = FakeHub(private=False)
    result = hub.publish_security_checkpoint(publication=publication, approval=_approval(publication), api=api,
        verification_root=tmp_path / "readback", fetch_bytes=api.fetch)
    assert result["checkpoint_uploaded"] is True and result["private"] is False
    assert result["proof_authority"] is False
