"""Sparse publication transport tests; fake Lake logs/Hub never imply an admit."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.duckdb_control.autoencoder_registry import AutoencoderRegistry
from ipfs_datasets_py.huggingface import autoencoder_incremental as pub
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_candidate_qualification as qualification
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder import ModalAutoencoderTrainingState
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder_patch_codec import encode_patch


def put(registry, root, raw):
    path = root / (pub._sha(raw) + ".input")
    path.write_bytes(raw)
    return registry.stage_artifact(path)


def child(registry, root, parent_id, value):
    parent = registry.get_version(parent_id)
    state = pub.sparse.resolve_checkpoint(parent["artifact"], resolver=registry.artifact_path).state
    before = state.state_identity()
    with state.transaction() as tx:
        state.feature_embedding_weights["fixture"][0] = value
    patch = put(registry, root, encode_patch(tx.patch, base_state_identity=before,
        result_state_identity=state.state_identity(), base_version_id=parent_id, sequence=0))
    raw = pub.sparse.encode_manifest(parent=parent["artifact"], base_version_id=parent_id,
        patches=[patch], materialized_checkpoint=pub.sparse.checkpoint_identity(state),
        state_identity=state.state_identity(), result_revision=state.state_revision)
    artifact = put(registry, root, raw)
    return registry.register_version("version-" + artifact["sha256"], "fixture-model", artifact,
                                      parent_version_id=parent_id)["version_id"]


def fake_lake(rule, *, roundtrip_ok, output_directory, timeout_seconds, statement_lock):
    """Only a transport test double: production smoke separately invokes Lake."""
    assert roundtrip_ok
    pattern = statement_lock.pattern_from_rule(rule)
    source = statement_lock.render_lean(pattern)
    lock = statement_lock.lock_statement(source, source)
    raw = (source.rstrip() + "\n").encode()
    log = b"Built Legal (transport unit fixture; NOT native Lake execution)\n"
    output_directory.mkdir(parents=True)
    (output_directory / "Legal.lean").write_bytes(raw)
    (output_directory / "lake.log").write_bytes(log)
    for kind, filename in (("lakefile", "lakefile.lean"), ("lean_toolchain", "lean-toolchain")):
        (output_directory / filename).write_bytes(pub._PROJECT[kind])
    return {"passed": True, "lake_ok": True, "admitted": False,
        "unit_test_transport_only": True, "command": ["lake", "build", "Legal"],
        "returncode": 0, "scope": "source_locked_numeric_pattern", "toolchain": qualification.LEAN_TOOLCHAIN,
        "pattern": pattern, "source_lock": lock, "lean_source_sha256": pub._sha(raw),
        "source_file": str(output_directory / "Legal.lean"),
        "log": {**pub._ref(log), "path": str(output_directory / "lake.log")}}


def evidence(registry, root, version_id, monkeypatch):
    monkeypatch.setattr(qualification, "_lake_gate", fake_lake)
    lock, _, lock_sha = qualification._statement_lock()
    rows = []
    for index, days in enumerate((20, 30)):
        sample = {"title": "qualification-fixture", "section": str(index),
                  "text": f"The officer shall retain the file for at least {days} days."}
        sample_id = f"transport-fixture-{index}"
        structural = qualification._structural_gates(sample, sample_id, root / sample_id, lock, 10)
        assert all(structural[key]["passed"] for key in pub.GATES[1:-1])
        rows.append({**structural, "qualified": True, "source": sample, "sample_id": sample_id,
            "source_sha256": pub._sha(sample["text"].encode()), "split": "training" if index == 0 else "heldout",
            "metric_gate": qualification.metric_gate({"sample_count": 1,
                "embedding_cosine_similarity": .9, "reconstruction_loss": .1})})
    version = registry.get_version(version_id)
    resolved = pub.sparse.resolve_checkpoint(version["artifact"], resolver=registry.artifact_path)
    return {"schema_version": "autoencoder-candidate-qualification/v1",
        "execution_mode": "native_candidate_qualification", "qualified": True,
        "unit_test_transport_only": True, "candidate_version_id": version_id,
        "candidate_artifact": version["artifact"], "rows": rows,
        "sample_count": 1, "heldout_sample_count": 1,
        "gate_results": {name: {"passed": True} for name in pub.GATES},
        "qualification_scope": "embedding_model_and_deterministic_source_compiler_pipeline",
        "model_emits_text_or_formulas": False, "admitted": False, "formalized": False,
        "materialized_checkpoint": dict(resolved.materialized_checkpoint),
        "checkpoint_artifacts": [dict(item) for item in resolved.artifacts],
        "source_sha256": {"statement_lock": lock_sha}, "sample_set_sha256": "f" * 64}


@pytest.fixture
def package(tmp_path, monkeypatch):
    with AutoencoderRegistry(tmp_path / "control.duckdb", tmp_path / "store") as registry:
        registry.register_variant("variant", "fixture-model", {"source_language": "en"})
        state = ModalAutoencoderTrainingState(feature_embedding_weights={"fixture": [1., 2.]})
        anchor = put(registry, tmp_path, pub.sparse.canonical_checkpoint_bytes(state))
        base = registry.register_version("base", "fixture-model", anchor)["version_id"]
        intermediate = child(registry, tmp_path, base, 2.)
        candidate = child(registry, tmp_path, intermediate, 3.)
        receipt = evidence(registry, tmp_path, candidate, monkeypatch)
        receipt_ref = put(registry, tmp_path, pub._json(receipt))
        staged = pub.stage_sparse_update(registry, candidate, receipt_ref, tmp_path / "staged", lane_id="test-0")
        yield SimpleNamespace(registry=registry, root=tmp_path, anchor=anchor, candidate=candidate,
                              receipt=receipt, receipt_ref=receipt_ref, staged=staged)


class FakeHub:
    def __init__(self, *, fail_after_commit=False):
        self.sha = "a" * 40
        self.files = {}
        self.commits = []
        self.fail_after_commit = fail_after_commit

    def repo_info(self, **kwargs):
        return SimpleNamespace(sha=self.sha)

    def get_paths_info(self, repository, paths, *, revision, **kwargs):
        assert repository == pub.REPOSITORY and revision == self.sha
        return [SimpleNamespace(path=path, lfs={"sha256": pub._sha(self.files[path])})
                for path in paths if path in self.files]

    def create_commit(self, *, operations, parent_commit, **kwargs):
        assert parent_commit == self.sha
        self.commits.append(operations)
        self.files.update({item.path_in_repo: item.path_or_fileobj for item in operations})
        self.sha = hashlib.sha1(str(len(self.commits)).encode()).hexdigest()
        if self.fail_after_commit:
            self.fail_after_commit = False
            raise OSError("reply lost after remote commit")
        return SimpleNamespace(oid=self.sha)


def test_full_dependency_closure_proofs_and_explicit_preseed_replay(package):
    bundle = pub.load_sparse_update(package.staged["manifest_path"])
    manifest = bundle["manifest"]
    assert len(manifest["version_lineage"]) == 3
    kinds = [entry["kind"] for entry in manifest["files"]]
    assert kinds.count("sparse_manifest") == kinds.count("sparse_patch") == 2
    assert kinds.count("lean_source") == 2
    assert package.anchor["sha256"] not in bundle["by_sha"]
    assert manifest["base_preseed_required"] and not manifest["self_contained_restore"]
    assert not manifest["ancestors_qualified"] and not manifest["statutory_corpus_qualified"]
    assert {sample["title"] for sample in manifest["qualification_samples"]} == {"qualification-fixture"}
    replay = pub.replay_sparse_update(package.staged["manifest_path"], local_anchor_resolver=package.registry.artifact_path)
    assert replay["replayed"] and replay["depth"] == 2
    assert not replay["downloaded_weights"] and not replay["promoted"]


def test_append_retry_is_idempotent_and_does_not_promote(package):
    hub = FakeHub()
    first = pub.publish_sparse_update(package.staged["manifest_path"], upload=True, api=hub)
    again = pub.publish_sparse_update(package.staged["manifest_path"], upload=True, api=hub)
    assert first["uploaded"] and not first["lane_promoted"]
    assert again["remote_already_present"] and len(hub.commits) == 1
    assert not any(path.endswith("qualified.json") for path in hub.files)


def test_lost_reply_reuses_exact_remote_commit(package):
    hub = FakeHub(fail_after_commit=True)
    with pytest.raises(OSError, match="reply lost"):
        pub.publish_sparse_update(package.staged["manifest_path"], upload=True, api=hub)
    report = pub.publish_sparse_update(package.staged["manifest_path"], upload=True, api=hub)
    assert report["uploaded"] and report["remote_already_present"] and len(hub.commits) == 1


def test_lane_head_requires_owner_policy_and_exact_compare_swap(package):
    path = package.staged["manifest_path"]
    with pytest.raises(pub.IncrementalPublicationError, match="trusted owner"):
        pub.publish_sparse_update(path, promote_lane=True)
    hub = FakeHub()
    first = pub.publish_sparse_update(path, upload=True, promote_lane=True, owner_head_validator=lambda _: True, api=hub)
    assert first["lane_head"]["generation"] == 1 and not first["lane_head"]["global_best"]
    second = pub.publish_sparse_update(path, upload=True, promote_lane=True,
        expected_lane_head=first["lane_head"], owner_head_validator=lambda _: True, api=hub)
    assert second["lane_head"]["generation"] == 2
    with pytest.raises(pub.IncrementalPublicationError, match="compare-and-swap"):
        pub.publish_sparse_update(path, upload=True, promote_lane=True, owner_head_validator=lambda _: True, api=hub)


@pytest.mark.parametrize("change", ["metric", "family", "lake", "version", "qualified"])
def test_missing_or_false_native_evidence_rejected(package, change):
    receipt = deepcopy(package.receipt)
    if change == "metric": receipt["rows"][0]["metric_gate"]["embedding_cosine_similarity"] = .71
    elif change == "family": receipt["rows"][0]["family_syntax_gate"]["rows"][0]["families"].pop("fol")
    elif change == "lake": receipt["rows"][0]["lake_gate"]["rows"][0]["returncode"] = 1
    elif change == "version": receipt["candidate_version_id"] = "wrong"
    else: receipt["qualified"] = False
    ref = put(package.registry, package.root, pub._json(receipt))
    with pytest.raises(pub.IncrementalPublicationError):
        pub.stage_sparse_update(package.registry, package.candidate, ref, package.root / "invalid", lane_id="test-0")


@pytest.mark.parametrize("change", ["missing_patch", "extra_file", "authority", "path", "scope", "role"])
def test_modified_manifest_cannot_claim_qualification(package, change):
    original = Path(package.staged["manifest_path"])
    manifest = json.loads(original.read_bytes())
    if change == "missing_patch":
        manifest["files"].remove(next(item for item in manifest["files"] if item["kind"] == "sparse_patch"))
    elif change == "extra_file": manifest["files"].append(manifest["files"][0])
    elif change == "authority": manifest["formalized"] = True
    elif change == "path": manifest["lane_head_path"] = "../qualified.json"
    elif change == "scope": manifest["qualification_samples"][0]["title"] = "5"
    else: manifest["files"][0]["qualification_role"] = "fully_qualified"
    modified = original.with_name("modified.json")
    modified.write_bytes(pub._json(manifest))
    with pytest.raises(pub.IncrementalPublicationError):
        pub.load_sparse_update(modified)


def test_exact_proof_log_bytes_required(package):
    log = Path(package.receipt["rows"][0]["lake_gate"]["rows"][0]["log"]["path"])
    log.write_text("Built Legal (altered log)\n")
    with pytest.raises((pub.IncrementalPublicationError, ValueError), match="identity|byte|bound"):
        pub.stage_sparse_update(package.registry, package.candidate, package.receipt_ref,
                                package.root / "altered", lane_id="test-0")


def test_compacted_full_anchor_can_have_older_registry_parent(package, monkeypatch):
    previous = package.registry.get_version(package.candidate)
    state = pub.sparse.resolve_checkpoint(previous["artifact"], resolver=package.registry.artifact_path).state
    anchor = put(package.registry, package.root, pub.sparse.canonical_checkpoint_bytes(state))
    compacted = package.registry.register_version("compact", "fixture-model", anchor,
        parent_version_id=package.candidate)["version_id"]
    candidate = child(package.registry, package.root, compacted, 4.)
    proofs = package.root / "compacted-proof"
    proofs.mkdir()
    receipt = evidence(package.registry, proofs, candidate, monkeypatch)
    ref = put(package.registry, package.root, pub._json(receipt))
    staged = pub.stage_sparse_update(package.registry, candidate, ref, package.root / "compacted", lane_id="test-0")
    manifest = pub.load_sparse_update(staged["manifest_path"])["manifest"]
    assert manifest["anchor_checkpoint"] == anchor and len(manifest["version_lineage"]) == 2
    assert manifest["version_lineage"][-1]["parent_version_id"] == package.candidate


def test_owner_outbox_idempotent_enqueue_dry_run_and_ack(package):
    queued = pub.enqueue_sparse_update(package.registry, package.staged["manifest_path"])
    assert queued == pub.enqueue_sparse_update(package.registry, package.staged["manifest_path"])
    dry = pub.deliver_sparse_update(package.registry, queued["event_id"])
    assert not dry["uploaded"] and not dry["acknowledged"]
    assert package.registry.get_outbox_event("huggingface", queued["event_id"])["status"] == "pending"
    hub = FakeHub()
    done = pub.deliver_sparse_update(package.registry, queued["event_id"], upload=True, api=hub)
    again = pub.deliver_sparse_update(package.registry, queued["event_id"], upload=True, api=hub)
    assert done["acknowledged"] and again["already_delivered"] and len(hub.commits) == 1


def test_ambiguous_upload_retains_lease_and_recovers_without_retraining(package):
    queued = pub.enqueue_sparse_update(package.registry, package.staged["manifest_path"])
    hub = FakeHub(fail_after_commit=True)
    with pytest.raises(OSError):
        pub.deliver_sparse_update(package.registry, queued["event_id"], upload=True, api=hub)
    assert package.registry.get_outbox_event("huggingface", queued["event_id"])["status"] == "leased"
    receipt = pub.deliver_sparse_update(package.registry, queued["event_id"], upload=True, api=hub)
    assert receipt["acknowledged"] and receipt["remote_already_present"] and len(hub.commits) == 1
