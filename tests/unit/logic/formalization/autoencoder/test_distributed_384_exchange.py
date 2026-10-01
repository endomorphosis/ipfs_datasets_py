"""Exact distributed384 transport over an in-memory immutable Hub fixture."""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from .test_structured_source_384 import parent, rows
from ipfs_datasets_py.logic.formalization.autoencoder import structured_source_384 as decoder
from ipfs_datasets_py.logic.formalization.autoencoder.distributed_384 import exchange as ex, numerics as n
from ipfs_datasets_py.logic.formalization.autoencoder.distributed_384.contracts import binding, digest, raw, write_json


REPO, PREFIX = "Publicus/unit-test-ir", "distributed/rounds"


class Conflict(Exception):
    response = SimpleNamespace(status_code=409)


class Hub:
    def __init__(self, root):
        self.root, self.counter = root, 1
        self.head = f"{self.counter:040x}"
        self.snapshots = {self.head: {}}
        self.commits, self.downloads, self.head_reads = [], [], 0
        self.conflict_once = False

    def model_info(self, *, repo_id):
        assert repo_id == REPO
        self.head_reads += 1
        return SimpleNamespace(sha=self.head)

    def list_repo_files(self, *, repo_id, repo_type, revision):
        assert (repo_id, repo_type) == (REPO, "model")
        return sorted(self.snapshots[revision])

    def create_commit(self, *, repo_id, repo_type, parent_commit, operations, commit_message):
        assert (repo_id, repo_type) == (REPO, "model")
        assert parent_commit == self.head
        self.counter += 1
        revision = f"{self.counter:040x}"
        data = dict(self.snapshots[self.head])
        self.snapshots[revision] = data
        self.head = revision
        if self.conflict_once:
            self.conflict_once = False
            raise Conflict("concurrent writer changed HEAD")
        for operation in operations:
            assert operation.path_in_repo not in data
            data[operation.path_in_repo] = operation.path_or_fileobj
        self.commits.append(dict(parent=parent_commit, revision=revision, files=sorted(data)))
        return SimpleNamespace(oid=revision)

    def hf_hub_download(self, **kwargs):
        assert kwargs["repo_id"] == REPO and kwargs["repo_type"] == "model"
        assert len(kwargs["revision"]) == 40
        self.downloads.append(kwargs)
        data = self.snapshots[kwargs["revision"]][kwargs["filename"]]
        blob = self.root / (ex._sha(data) + ".json")
        blob.parent.mkdir(parents=True, exist_ok=True)
        blob.write_bytes(data)
        return str(blob)


@pytest.fixture(scope="module")
def data(parent, tmp_path_factory):
    root = tmp_path_factory.mktemp("exchange-round")
    domain = "intent_ir"
    base = decoder.train(domain, rows(domain, "train"), rows(domain, "validation"), parent_projection=parent)["checkpoint"]
    base["config"]["embedding_provenance"]["description"] = "authored café vectors"
    base_path = root / "base.json"
    # Original source bytes deliberately use ASCII escaping, unlike this
    # exchange's canonical UTF-8. Both identities must survive a round trip.
    base_path.write_text(json.dumps(base, sort_keys=True, separators=(",", ":"), ensure_ascii=True))
    training = [{**r, "split": "train", "group_id": "train-" + str(i // 2)}
        for i, r in enumerate(rows(domain, "train"))]
    validation = [{**r, "split": "validation", "group_id": "validation-" + str(i // 2)}
        for i, r in enumerate(rows(domain, "validation"))]
    plan = n.make_plan(base_path, training, validation, source_descriptor={
        "schema": "ir384-corpus-source/v1", "description": "authored test controls"}, shard_size=2)
    updates = [n.compute_update(plan, base, n.shard_rows(plan, training, s["shard_id"]), s["shard_id"])
        for s in plan["shards"]]
    merged = n.merge_updates(plan, base, updates, validation)["checkpoint"]
    inputs = dict(schema=ex.INPUTS_SCHEMA, plan=plan, base_checkpoint_raw=base_path.read_text(),
        training_rows=training, validation_rows=validation)
    return dict(base=base, base_path=base_path, plan=plan, binding=binding(plan),
        update=updates[0], checkpoint=merged, inputs=inputs)


def stage(data, tmp_path, kind="update", *, parent=False):
    payload = write_json(tmp_path / (kind + ".json"), data[kind])
    return ex.stage_bundle(payload, tmp_path / "staged", domain_id="intent_ir", kind=kind,
        binding=data["binding"], parent_path=data["base_path"] if parent else None)


@pytest.mark.parametrize("kind", ["update", "checkpoint", "inputs"])
def test_full_payload_roundtrip_pins_revision_and_replays_offline(data, tmp_path, kind):
    staged = stage(data, tmp_path, kind)
    hub = Hub(tmp_path / "hub")
    reference = ex.publish_bundle(staged["manifest_path"], repository_id=REPO, prefix=PREFIX, upload=True, api=hub)
    received = ex.receive_bundle(reference, tmp_path / "received", local_files_only=True, download_fn=hub.hf_hub_download)
    assert json.loads(Path(received["payload_path"]).read_bytes()) == data[kind]
    assert Path(received["payload_path"]).read_bytes() == raw(data[kind])
    assert not Path(received["payload_path"]).is_symlink()
    assert all(call["revision"] == reference["revision"] for call in hub.downloads)
    assert all(call["local_files_only"] for call in hub.downloads[-2:])
    assert ex.receive_bundle(reference, tmp_path / "received", download_fn=hub.hf_hub_download) == received


def test_checkpoint_postimage_preserves_raw_and_canonical_parent_identities(data, tmp_path):
    staged = stage(data, tmp_path, "checkpoint", parent=True)
    manifest = staged["manifest"]
    assert manifest["encoding"] == "postimages"
    assert manifest["parent"]["raw"]["sha256"] != manifest["parent"]["canonical_sha256"]
    assert manifest["parent"]["canonical_sha256"] == digest(data["base"])
    hub = Hub(tmp_path / "hub")
    ref = ex.publish_bundle(staged["manifest_path"], repository_id=REPO, prefix=PREFIX, upload=True, api=hub)
    result = ex.receive_bundle(ref, tmp_path / "received", parent_path=data["base_path"], download_fn=hub.hf_hub_download)
    assert Path(result["payload_path"]).read_bytes() == raw(data["checkpoint"])
    assert not any("parent.json" in name or "result.json" in name for name in hub.snapshots[ref["revision"]])


def test_wrong_parent_is_rejected_before_payload_download(data, tmp_path):
    staged = stage(data, tmp_path, "checkpoint", parent=True)
    hub = Hub(tmp_path / "hub")
    ref = ex.publish_bundle(staged["manifest_path"], repository_id=REPO, prefix=PREFIX, upload=True, api=hub)
    canonical_parent = write_json(tmp_path / "canonical-parent.json", data["base"])
    before = len(hub.downloads)
    with pytest.raises(ValueError, match="exact original parent"):
        ex.receive_bundle(ref, tmp_path / "wrong", parent_path=canonical_parent, download_fn=hub.hf_hub_download)
    assert len(hub.downloads) == before + 1


def test_publish_is_create_only_idempotent_and_retries_cas(data, tmp_path):
    staged = stage(data, tmp_path)
    hub = Hub(tmp_path / "hub")
    hub.conflict_once = True
    ref = ex.publish_bundle(staged["manifest_path"], repository_id=REPO, prefix=PREFIX, upload=True, api=hub)
    assert hub.head_reads == 2 and len(hub.commits) == 1
    assert ex.publish_bundle(staged["manifest_path"], repository_id=REPO, prefix=PREFIX, upload=True, api=hub) == ref
    assert len(hub.commits) == 1


def test_successful_commit_with_lost_response_recovers_without_another_commit(data, tmp_path):
    staged = stage(data, tmp_path)
    hub = Hub(tmp_path / "hub")
    native = hub.create_commit
    def lost_response(**kwargs):
        native(**kwargs)
        raise ConnectionError("fixture lost response after the server committed")
    hub.create_commit = lost_response
    with pytest.raises(ConnectionError, match="lost response"):
        ex.publish_bundle(staged["manifest_path"], repository_id=REPO, prefix=PREFIX, upload=True, api=hub)
    hub.create_commit = native
    ref = ex.publish_bundle(staged["manifest_path"], repository_id=REPO, prefix=PREFIX, upload=True, api=hub)
    assert ref["revision"] == hub.head and len(hub.commits) == 1


@pytest.mark.parametrize("key", ["plan_id", "recipe_sha256", "base_checkpoint_sha256", "trainer_id"])
def test_checkpoint_round_metadata_cannot_be_omitted(data, tmp_path, key):
    checkpoint = deepcopy(data["checkpoint"])
    del checkpoint["training"][key]
    path = write_json(tmp_path / "incomplete.json", checkpoint)
    with pytest.raises(ValueError, match="checkpoint.*(metadata|binding)"):
        ex.stage_bundle(path, tmp_path / "bad", domain_id="intent_ir", kind="checkpoint", binding=data["binding"])


def test_published_base_is_carried_as_inputs_not_mislabeled_completed_round(data, tmp_path):
    with pytest.raises(ValueError, match="send base heads as inputs"):
        ex.stage_bundle(data["base_path"], tmp_path / "bad", domain_id="intent_ir",
            kind="checkpoint", binding=data["binding"])
    assert stage(data, tmp_path, "inputs")["manifest"]["kind"] == "inputs"


def test_custom_native_shard_id_remains_exchange_compatible(data, tmp_path):
    update = deepcopy(data["update"])
    update["shard_id"] = "machineA-batch_42"
    update["update_id"] = digest({k: v for k, v in update.items() if k != "update_id"})
    path = write_json(tmp_path / "custom.json", update)
    staged = ex.stage_bundle(path, tmp_path / "staged", domain_id="intent_ir", kind="update", binding=data["binding"])
    assert staged["manifest"]["kind"] == "update"


def test_dry_run_never_contacts_hub(data, tmp_path):
    staged = stage(data, tmp_path)
    class NoContact:
        def __getattr__(self, name):
            raise AssertionError("unexpected Hub contact " + name)
    result = ex.publish_bundle(staged["manifest_path"], repository_id=REPO, prefix=PREFIX, api=NoContact())
    assert not result["uploaded"] and result["reference"] is None
    assert len(result["files"]) == 2


def test_discovery_pins_one_head_and_filters_exact_binding(data, tmp_path):
    staged = stage(data, tmp_path)
    hub = Hub(tmp_path / "hub")
    ref = ex.publish_bundle(staged["manifest_path"], repository_id=REPO, prefix=PREFIX, upload=True, api=hub)
    before = hub.head_reads
    assert ex.discover_bundles(REPO, PREFIX, expected_binding=data["binding"], api=hub) == [ref]
    assert hub.head_reads == before + 1
    different = {**data["binding"], "dataset_sha256": "0" * 64}
    assert ex.discover_bundles(REPO, PREFIX, expected_binding=different, api=hub) == []
    assert ex.discover_bundles(REPO, PREFIX, kind="checkpoint", expected_binding=data["binding"], api=hub) == []


@pytest.mark.parametrize("change", ["foreign", "authority", "identity", "nan", "unknown_field"])
def test_reject_corrupt_update(data, tmp_path, change):
    value = deepcopy(data["update"])
    if change == "foreign": value["dataset_sha256"] = "0" * 64
    elif change == "authority": value["proof_authority"] = True
    elif change == "identity": value["update_id"] = "0" * 64
    elif change == "nan": value["statistics"]["projected"][0][0] = float("nan")
    else: value["unexpected"] = True
    if change in ("foreign", "authority"):
        value["update_id"] = digest({k:v for k,v in value.items() if k != "update_id"})
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError):
        ex.stage_bundle(path, tmp_path / "bad", domain_id="intent_ir", kind="update", binding=data["binding"])


@pytest.mark.parametrize("field", ["base_checkpoint_raw", "training_rows", "validation_rows"])
def test_inputs_reject_detached_rows_or_original_base(data, tmp_path, field):
    value = deepcopy(data["inputs"])
    if field == "base_checkpoint_raw": value[field] += " "
    else: value[field][0]["source_text"] += " altered"
    path = write_json(tmp_path / "bad-inputs.json", value)
    with pytest.raises(ValueError):
        ex.stage_bundle(path, tmp_path / "bad", domain_id="intent_ir", kind="inputs", binding=data["binding"])


def test_tampered_remote_artifact_never_overwrites_local_result(data, tmp_path):
    staged = stage(data, tmp_path)
    hub = Hub(tmp_path / "hub")
    ref = ex.publish_bundle(staged["manifest_path"], repository_id=REPO, prefix=PREFIX, upload=True, api=hub)
    payload = str(Path(ref["manifest_path_in_repo"]).parent / "payload.json")
    hub.snapshots[ref["revision"]][payload] += b" "
    with pytest.raises(ValueError, match="payload hash"):
        ex.receive_bundle(ref, tmp_path / "received", download_fn=hub.hf_hub_download)
    assert not (tmp_path / "received").exists()
    with pytest.raises(ValueError, match="immutable remote artifact"):
        ex.publish_bundle(staged["manifest_path"], repository_id=REPO, prefix=PREFIX, upload=True, api=hub)


@pytest.mark.parametrize("prefix", ["../escape", "/absolute", "good//bad", "good/../bad"])
def test_reject_unsafe_remote_paths(data, tmp_path, prefix):
    staged = stage(data, tmp_path)
    with pytest.raises(ValueError, match="safe repository prefix"):
        ex.publish_bundle(staged["manifest_path"], repository_id=REPO, prefix=prefix)


def test_stage_rejects_local_symlink(data, tmp_path):
    path = write_json(tmp_path / "update.json", data["update"])
    link = tmp_path / "link.json"
    link.symlink_to(path)
    with pytest.raises(ValueError, match="aliased|regular artifact"):
        ex.stage_bundle(link, tmp_path / "bad", domain_id="intent_ir", kind="update", binding=data["binding"])
