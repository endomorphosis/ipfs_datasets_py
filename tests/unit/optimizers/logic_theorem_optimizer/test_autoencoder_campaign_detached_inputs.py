"""Detached evidence uses declared synthetic vectors, never native execution."""
from dataclasses import asdict
import hashlib
import json
from pathlib import Path

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_campaign_detached_inputs as detached
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_corpus_index as index
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_training_worker as worker
from tests.unit.optimizers.logic_theorem_optimizer.test_autoencoder_campaign_shared_sparse_arrow import _forbid_native
from tests.unit.optimizers.logic_theorem_optimizer.test_autoencoder_campaign_training_worker import _campaign_job
from tests.unit.optimizers.logic_theorem_optimizer.test_autoencoder_produced_record_projection import _prepared, _summary


ROOTS = ("source_inventory_artifact", "source_partitions_artifact", "embedding_receipt_set_artifact",
         "produced_record_projection_artifact", "corpus_manifest_artifact")


@pytest.fixture(autouse=True)
def no_native(monkeypatch):
    _forbid_native(monkeypatch)


def _bare(value):
    return {key: value[key] for key in ("sha256", "bytes")}


class _Store:
    def __init__(self, root):
        self.root, self.paths, self.references, self.calls = root, {}, {}, []
        root.mkdir(parents=True)

    def add(self, raw):
        reference = {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}
        path = self.root / reference["sha256"]
        path.write_bytes(raw)
        self.paths[reference["sha256"]] = path
        self.references[reference["sha256"]] = reference
        return reference

    def resolve(self, reference):
        assert set(reference) == {"sha256", "bytes"}, "a historical path reached the resolver"
        assert self.references[reference["sha256"]] == reference
        self.calls.append(reference["sha256"])
        return self.paths[reference["sha256"]]


def _variant(payload):
    return {**payload["variant"], "source_campaign_binding": {
        name: _bare(payload[field]) for name, field in (
            ("source_inventory", "source_inventory_artifact"),
            ("source_partitions", "source_partitions_artifact"),
            ("embedding_receipt_set", "embedding_receipt_set_artifact"))}}


def _job_bytes(payload):
    # Preserve a real distinction between artifact bytes and canonical spec hash.
    return (json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()


def _fixture(tmp_path, *, shared_leaf=False):
    payload, case, projection = _campaign_job(tmp_path / "original",
        groups=[list(range(32))] if shared_leaf else None)
    # This is historical producer metadata, deliberately not current execution
    # compatibility. Corpus verification does not invoke the native worker.
    payload["expected_source_sha256"] = {key: "1" * 64 for key in worker.SOURCE_MODULE_NAMES}
    spec = worker.TrainingJobSpec.from_dict(payload)
    payload = spec.to_dict()
    store = _Store(tmp_path / "detached")
    artifacts = [payload[name] for name in (*ROOTS, "base_checkpoint")]
    artifacts += payload["corpus_source_artifacts"] + payload["embedding_receipt_artifacts"]
    artifacts += payload["base_checkpoint_dependencies"]
    for artifact in artifacts:
        assert store.add(Path(artifact["path"]).read_bytes()) == _bare(artifact)
    return payload, case, projection, store


def _verify(payload, store, *, resolver=None, variant=None, digest=None):
    spec = worker.TrainingJobSpec.from_dict(payload)
    job_artifact = store.add(_job_bytes(payload))
    return detached.verify_detached_campaign_job(job_artifact,
        resolver=resolver or store.resolve,
        expected_job_spec_sha256=digest or spec.canonical_sha256,
        variant_manifest=variant or _variant(payload))


def _selected(payload):
    return {ref["sha256"] for name in ("corpus_source_artifacts", "embedding_receipt_artifacts")
            for ref in payload[name]}


def _no_selected(payload, store, *, selected=None):
    selected = _selected(payload) if selected is None else selected
    def resolve(reference):
        assert reference["sha256"] not in selected, "rejected metadata reached selected I/O"
        return store.resolve(reference)
    return resolve


@pytest.mark.parametrize("shared_leaf", [False, True])
def test_detached_original_job_and_summary_survive_removed_historical_paths(tmp_path, shared_leaf):
    payload, case, projection, store = _fixture(tmp_path, shared_leaf=shared_leaf)
    spec = worker.TrainingJobSpec.from_dict(payload)
    expected = worker.verify_corpus_job_inputs(spec)
    artifacts = [payload[name] for name in (*ROOTS, "base_checkpoint")]
    artifacts += payload["corpus_source_artifacts"] + payload["embedding_receipt_artifacts"]
    for artifact in artifacts:
        Path(artifact["path"]).unlink(missing_ok=True)
    for path in case.case.source_paths.values():
        path.unlink(missing_ok=True)
    before = _job_bytes(payload)
    result = _verify(payload, store)
    assert result["spec"].to_dict() == payload
    assert result["spec"].canonical_sha256 == spec.canonical_sha256
    assert _job_bytes(payload) == before
    assert result["corpus_verification"] == expected
    assert result["_receipt_set"].to_bytes() == case.receipt_set.to_bytes()
    assert result["corpus_verification"]["produced_record_projection_verification"]["selected_artifacts"] == projection.selected_artifacts()
    by_digest = {row["sha256"]: row for row in result["required_artifacts"]}
    assert len(by_digest) == len(result["required_artifacts"])
    assert set(by_digest) == set(store.references)
    assert all(row["roles"] == sorted(set(row["roles"])) for row in by_digest.values())
    assert set(store.calls) == set(store.references) - {payload["base_checkpoint"]["sha256"]}
    assert len(store.calls) == len(set(store.calls)), "resolvers are captured once per exact descriptor"
    qualification = result["qualification"]
    assert qualification["expected_source_manifest_supplied"] is True
    assert qualification["expected_source_manifest_preserved"] is True
    assert qualification["canonical_logic_tree_verified"] is True
    for flag in ("historical_absolute_paths_used", "execution_source_manifest_verified", "training_authorized",
                 "weights_constructed", "checkpoint_semantic_replay_verified", "target_runtime_membership_verified",
                 "arrow_runtime_compatibility_verified", "source_authority_authenticated", "global_holdout_verified",
                 "admitted", "formalized", "publication_performed"):
        assert qualification[flag] is False
    assert qualification["original_job_artifact"]["sha256"] != spec.canonical_sha256


def test_shared_artifact_roles_are_inventoried_without_runtime_validation(tmp_path):
    payload, _, _, store = _fixture(tmp_path)
    artifact = store.add(b"deliberately unqualified shared artifact bytes")
    original = {**artifact, "path": str(tmp_path / "absent-original-shared-artifact")}
    payload.update(target_snapshot_id="sha256:" + "2" * 64, target_snapshot_artifact=original,
                   arrow_feature_weights_artifact=dict(original))
    result = _verify(payload, store)
    row = next(row for row in result["required_artifacts"] if row["sha256"] == artifact["sha256"])
    assert row["roles"] == ["arrow_feature_weights", "target_snapshot"]
    assert artifact["sha256"] not in store.calls
    assert result["qualification"]["target_runtime_membership_verified"] is False
    assert result["qualification"]["arrow_runtime_compatibility_verified"] is False


@pytest.mark.parametrize("change", ["digest", "training_config", "model_config", "code_identity", "historical_path"])
def test_full_spec_identity_precedes_metadata_or_selected_reads(tmp_path, change):
    payload, _, _, store = _fixture(tmp_path)
    expected = worker.TrainingJobSpec.from_dict(payload).canonical_sha256
    if change == "digest":
        expected = "f" * 64
    elif change == "training_config":
        payload["training_config"]["learning_rate"] *= 2
    elif change == "model_config":
        payload["autoencoder_config"]["new_configuration"] = 1
    elif change == "code_identity":
        payload["code_identity"] = "different-historical-producer"
    else:
        payload["corpus_manifest_artifact"]["path"] += ".different"
    with pytest.raises(detached.DetachedCampaignInputError, match="complete specification"):
        _verify(payload, store, digest=expected)
    assert len(store.calls) == 1


@pytest.mark.parametrize("change", ["variant", "variant_number", "variant_bool", "roots", "legacy"])
def test_exact_variant_and_campaign_bindings_precede_selected_reads(tmp_path, change):
    payload, _, _, store = _fixture(tmp_path)
    variant = _variant(payload)
    if change == "variant":
        variant["model_variant"] = "another-variant"
    elif change == "variant_number":
        variant["model_variant"] = 1
    elif change == "variant_bool":
        variant["model_variant"] = True
    elif change == "roots":
        variant["source_campaign_binding"]["source_inventory"]["sha256"] = "f" * 64
    else:
        variant["corpus_index_binding"] = {}
    with pytest.raises(detached.DetachedCampaignInputError):
        _verify(payload, store, variant=variant, resolver=_no_selected(payload, store))
    assert len(store.calls) == 1


@pytest.mark.parametrize("change", ["training_order", "validation_order", "vector", "dataset", "split"])
def test_detached_records_and_order_cannot_drift_before_selected_reads(tmp_path, change):
    payload, _, _, store = _fixture(tmp_path)
    if change == "training_order":
        payload["samples"].reverse()
    elif change == "validation_order":
        payload["validation_samples"].reverse()
    elif change == "vector":
        payload["samples"][0]["embedding_vector"][0] += 0.25
    else:
        payload[f"{change}_snapshot_id"] = "sha256:" + "0" * 64
    with pytest.raises(detached.DetachedCampaignInputError):
        _verify(payload, store, resolver=_no_selected(payload, store))


@pytest.mark.parametrize("closure", ["corpus_source_artifacts", "embedding_receipt_artifacts"])
@pytest.mark.parametrize("change", ["missing", "size"])
def test_detached_exact_selected_closure_precedes_selected_reads(tmp_path, closure, change):
    payload, _, _, store = _fixture(tmp_path)
    selected = _selected(payload)
    if change == "missing":
        payload[closure].pop()
    else:
        payload[closure][0]["bytes"] += 1
    with pytest.raises(detached.DetachedCampaignInputError, match="exact projection closure"):
        _verify(payload, store, resolver=_no_selected(payload, store, selected=selected))


def test_invalid_validation_group_cannot_trigger_valid_training_reads(tmp_path):
    payload, _, projection, store = _fixture(tmp_path)
    data = projection.to_dict()
    data["validation_record_ids"] = data["training_record_ids"]
    reference = store.add(worker._json_bytes(data))
    payload["produced_record_projection_artifact"] = {**reference,
        "path": payload["produced_record_projection_artifact"]["path"]}
    with pytest.raises(detached.DetachedCampaignInputError):
        _verify(payload, store, resolver=_no_selected(payload, store))


@pytest.mark.parametrize("split", ["canary", "holdout"])
def test_detached_protected_roles_reject_before_any_selected_payload(tmp_path, split):
    payload, _, _, store = _fixture(tmp_path)
    policy = index.SplitPolicy("detached-protected-fixture", **{
        name: 10000 if name == split else 0 for name in ("train", "validation", "canary", "holdout")})
    fixture = _prepared(tmp_path / "protected", policy=policy)
    root, manifest = fixture.receipt_set, fixture.manifest
    roles = manifest.to_dict()["split"]
    def bind(name, raw):
        return {**store.add(raw), "path": str(tmp_path / "historical-protected" / name)}
    projection = {"schema_version": "autoencoder-produced-record-projection-v1",
        "receipt_set": {"sha256": root.sha256, "bytes": len(root.to_bytes())},
        "source_partitions": {"sha256": root.partitions.sha256, "bytes": len(root.partitions.to_bytes())},
        "corpus_manifest": {"sha256": manifest.sha256, "bytes": len(manifest.to_bytes())},
        "dataset_snapshot_id": manifest.dataset_snapshot_id, "split_snapshot_id": manifest.split_snapshot_id,
        "training_record_ids": roles["training_record_ids"], "validation_record_ids": roles["validation_record_ids"],
        "records": [{"record_summary": _summary(record), **root.binding_for(entry)}
            for record, entry in zip(manifest.records, fixture.entry_cids, strict=True)]}
    records = {record.record_id: record for record in manifest.records}
    payload.update(source_inventory_artifact=bind("inventory", root.partitions.inventory.to_bytes()),
        source_partitions_artifact=bind("partitions", root.partitions.to_bytes()),
        embedding_receipt_set_artifact=bind("receipts", root.to_bytes()),
        corpus_manifest_artifact=bind("manifest", manifest.to_bytes()),
        produced_record_projection_artifact=bind("projection", worker._json_bytes(projection)),
        dataset_snapshot_id=manifest.dataset_snapshot_id, split_snapshot_id=manifest.split_snapshot_id,
        samples=[asdict(records[key].sample) for key in roles["training_record_ids"]],
        validation_samples=[asdict(records[key].sample) for key in roles["validation_record_ids"]],
        embedding_receipt_artifacts=[bind("leaf-" + ref["sha256"], fixture.case.leaf_paths[ref["sha256"]].read_bytes())
                                    for ref in root.selected_leaf_artifacts(fixture.entry_cids)],
        corpus_source_artifacts=[bind("source-" + ref["sha256"], fixture.case.source_paths[ref["sha256"]].read_bytes())
                                 for ref in manifest.source_refs])
    with pytest.raises(detached.DetachedCampaignInputError):
        _verify(payload, store, resolver=_no_selected(payload, store))


@pytest.mark.parametrize("field", ROOTS)
def test_changed_metadata_blob_rejects_before_any_selected_read(tmp_path, field):
    payload, _, _, store = _fixture(tmp_path)
    store.paths[payload[field]["sha256"]].write_bytes(b"changed detached metadata")
    with pytest.raises(detached.DetachedCampaignInputError):
        _verify(payload, store, resolver=_no_selected(payload, store))


@pytest.mark.parametrize("closure", ["corpus_source_artifacts", "embedding_receipt_artifacts"])
def test_detached_selected_current_bytes_are_required(tmp_path, closure):
    payload, _, _, store = _fixture(tmp_path)
    store.paths[payload[closure][0]["sha256"]].write_bytes(b"changed selected payload")
    with pytest.raises(detached.DetachedCampaignInputError):
        _verify(payload, store)


@pytest.mark.parametrize("target", ["inventory", "job", "earlier_source"])
def test_later_resolver_cannot_conceal_earlier_bytes_drifting(tmp_path, target):
    payload, _, _, store = _fixture(tmp_path)
    job_ref = store.add(_job_bytes(payload))
    source_ids = {ref["sha256"] for ref in payload["corpus_source_artifacts"]}
    first, changed = [], []
    def resolve(reference):
        path = store.resolve(reference)
        if reference["sha256"] in source_ids:
            if not first:
                first.append(reference["sha256"])
            elif not changed:
                digest = {"inventory": payload["source_inventory_artifact"]["sha256"],
                          "job": job_ref["sha256"], "earlier_source": first[0]}[target]
                store.paths[digest].write_bytes(b"later resolver changed prior bytes")
                changed.append(digest)
        return path
    with pytest.raises(detached.DetachedCampaignInputError):
        _verify(payload, store, resolver=resolve)
    assert changed


def test_original_declared_bounds_apply_before_selected_resolution(tmp_path):
    payload, _, _, store = _fixture(tmp_path)
    payload["source_inventory_artifact"]["bytes"] = 64 * 1024**2 + 1
    job_ref = store.add(_job_bytes(payload))
    with pytest.raises(detached.DetachedCampaignInputError, match="byte bound"):
        detached.verify_detached_campaign_job(job_ref, resolver=_no_selected(payload, store),
            expected_job_spec_sha256="0" * 64, variant_manifest=_variant(payload))
    assert store.calls == [job_ref["sha256"]]


def test_job_byte_bound_rejects_before_any_resolver_call():
    def forbidden(_):
        pytest.fail("over-limit job must not resolve a payload")
    with pytest.raises(detached.DetachedCampaignInputError, match="byte bound"):
        detached.verify_detached_campaign_job({"sha256": "0" * 64, "bytes": detached.MAX_JOB_BYTES + 1},
            resolver=forbidden, expected_job_spec_sha256="0" * 64, variant_manifest={})


def test_current_workspace_pin_failure_is_not_bypassed(tmp_path, monkeypatch):
    from ipfs_datasets_py.logic.autoformal import tree_pin
    payload, _, _, store = _fixture(tmp_path)
    def fail():
        raise tree_pin.LogicTreePinError("drifted HACC parser fixture")
    monkeypatch.setattr(tree_pin, "require_workspace_logic_tree", fail)
    with pytest.raises(tree_pin.LogicTreePinError, match="HACC"):
        _verify(payload, store)
    assert store.calls == []
