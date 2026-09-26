"""Immutable checkpoint-chain integrity, replay boundaries and explicit compaction."""

import hashlib
import json
from pathlib import Path

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_autoencoder as ma
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_autoencoder_sparse_checkpoint as codec
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder_patch_codec import encode_patch


def _state():
    return ma.ModalAutoencoderTrainingState(
        feature_embedding_weights={"a": [1.0, -0.0], "unicode \u00e9": [2.0]},
        feature_family_logits={"sample": {"deontic": 0.25}},
        applied_todo_ids=["prior"],
    )


class Store:
    def __init__(self, root):
        self.root = root
        self.paths = {}

    def put(self, raw):
        ref = {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}
        path = self.root / ref["sha256"]
        if not path.exists():
            path.write_bytes(raw)
        self.paths[ref["sha256"]] = path
        return ref

    def resolve(self, ref):
        return self.paths[ref["sha256"]]

    def load(self, ref, **kwargs):
        return codec.resolve_checkpoint(ref, resolver=self.resolve, **kwargs)

    def inventory(self, ref, **kwargs):
        return codec.inventory_checkpoint(ref, resolver=self.resolve, **kwargs)

    def job(self, parent, state, *, version="v1", changes=(2.0,), **updates):
        patches = []
        state = ma.ModalAutoencoderTrainingState.from_dict(state.to_dict())
        for sequence, value in enumerate(changes):
            before = state.state_identity()
            with state.transaction(label=f"epoch:{sequence}") as tx:
                state.feature_embedding_weights["a"][0] = value
            patches.append(self.put(encode_patch(
                tx.patch, base_state_identity=before, result_state_identity=state.state_identity(),
                base_version_id=version, sequence=sequence, provenance={"run_id": version},
            )))
        args = dict(parent=parent, base_version_id=version, patches=patches,
                    materialized_checkpoint=codec.checkpoint_identity(state), state_identity=state.state_identity(),
                    result_revision=state.state_revision, provenance={"run_id": version})
        args.update(updates)
        raw = codec.encode_manifest(**args)
        return self.put(raw), state, json.loads(raw)


@pytest.fixture
def setup(tmp_path):
    store = Store(tmp_path)
    state = _state()
    base = store.put(codec.canonical_checkpoint_bytes(state))
    return store, base, state


def test_canonical_identity_exactly_matches_existing_checkpoint_format():
    state = _state()
    raw = (state.to_json() + "\n").encode("utf-8")
    assert codec.canonical_checkpoint_bytes(state) == raw
    assert codec.checkpoint_identity(state) == {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}
    assert b"-0.0" in raw and b"\\u00e9" in raw


def test_legacy_full_root_preserves_physical_hash_and_normal_reload(tmp_path):
    store = Store(tmp_path)
    raw = json.dumps(_state().to_dict(), indent=2).encode()
    ref = store.put(raw)
    resolved = store.load(ref)
    assert resolved.materialized_checkpoint == ref
    assert resolved.anchor_checkpoint == ref
    assert resolved.anchor_checkpoint_bytes == len(raw)
    assert resolved.state.state_revision == 0
    assert resolved.depth == resolved.total_patch_bytes == 0
    assert resolved.manifest is None
    assert resolved.artifacts == (ref,)
    assert codec.checkpoint_identity(resolved.state) != ref


def test_two_jobs_reset_revision_at_boundary_and_preserve_exact_bytes(setup):
    store, base, state = setup
    first, first_state, first_manifest = store.job(base, state, changes=(2.0, 3.0))
    second, second_state, second_manifest = store.job(first, first_state, version="v2", changes=(4.0,))
    terminal = store.load(second, reset_revision=False)
    fresh = store.load(second)
    assert first_state.state_revision == 2
    assert terminal.state.state_revision == terminal.replayed_revision == 1
    assert fresh.state.state_revision == 0
    assert fresh.replayed_revision == 1
    assert terminal.state.to_json() == fresh.state.to_json() == second_state.to_json()
    assert terminal.materialized_checkpoint == codec.checkpoint_identity(second_state)
    assert terminal.state_identity == second_state.state_identity()
    assert terminal.depth == 2
    assert terminal.anchor_checkpoint == base
    assert terminal.total_patch_bytes == sum(ref["bytes"] for manifest in (first_manifest, second_manifest)
                                             for ref in manifest["patches"])
    assert {ref["sha256"] for ref in terminal.artifacts} == set(store.paths)
    assert terminal.artifacts[0] == second


def test_empty_accepted_job_is_identity_preserving(setup):
    store, base, state = setup
    ref, result, manifest = store.job(base, state, changes=())
    resolved = store.load(ref)
    assert resolved.depth == 1 and resolved.total_patch_bytes == 0
    assert resolved.replayed_revision == resolved.state.state_revision == 0
    assert resolved.state.to_json() == state.to_json() == result.to_json()
    assert manifest["patches"] == []


@pytest.mark.parametrize("updates,match", [
    ({"state_identity": "0" * 64}, "state identity"),
    ({"result_revision": 10}, "revision"),
    ({"materialized_checkpoint": {"sha256": "0" * 64, "bytes": 1}}, "byte identity"),
    ({"base_version_id": "wrong"}, "base version"),
])
def test_forged_result_or_patch_binding_rejected(setup, updates, match):
    store, base, state = setup
    ref, _, _ = store.job(base, state, **updates)
    with pytest.raises(codec.SparseCheckpointError, match=match):
        store.load(ref)


@pytest.mark.parametrize("method", ["load", "inventory"])
def test_reordered_or_omitted_segments_fail_without_revision_rebasing(setup, method):
    store, base, state = setup
    _, _, manifest = store.job(base, state, changes=(2.0, 3.0))
    for patches in (list(reversed(manifest["patches"])), manifest["patches"][1:]):
        altered = dict(manifest, patches=patches)
        ref = store.put(json.dumps(altered, sort_keys=True, separators=(",", ":")).encode())
        with pytest.raises(codec.SparseCheckpointError, match="sequence"):
            getattr(store, method)(ref)


@pytest.mark.parametrize("method", ["load", "inventory"])
def test_manifest_provenance_must_match_accepted_segments(setup, method):
    store, base, state = setup
    ref, _, _ = store.job(base, state, provenance={"run_id": "different-run"})
    with pytest.raises(codec.SparseCheckpointError, match="provenance mismatch: run_id"):
        getattr(store, method)(ref)


@pytest.mark.parametrize("method", ["load", "inventory"])
def test_revision_cannot_carry_over_from_previous_job(setup, method):
    store, base, state = setup
    first, changed, _ = store.job(base, state)
    before = changed.state_identity()
    with changed.transaction() as tx:
        changed.feature_embedding_weights["a"][0] = 3.0
    patch = store.put(encode_patch(tx.patch, base_state_identity=before,
                                  result_state_identity=changed.state_identity(), base_version_id="v2", sequence=0))
    raw = codec.encode_manifest(parent=first, base_version_id="v2", patches=[patch],
                                materialized_checkpoint=codec.checkpoint_identity(changed),
                                state_identity=changed.state_identity(), result_revision=changed.state_revision)
    with pytest.raises(codec.SparseCheckpointError, match="base revision"):
        getattr(store, method)(store.put(raw))


def test_exact_depth_limit_then_compaction_restores_depth_zero(setup, tmp_path):
    store, ref, state = setup
    for i in range(8):
        ref, state, _ = store.job(ref, state, version=f"v{i}", changes=(float(i + 2),))
    resolved = store.load(ref, reset_revision=False)
    assert resolved.depth == 8
    assert store.inventory(ref).depth == 8
    full = codec.materialize_checkpoint(resolved, tmp_path / "compacted.json")
    assert codec.artifact_ref(full) == resolved.materialized_checkpoint
    store.paths[full["sha256"]] = Path(full["path"])
    compacted = store.load(full)
    assert compacted.depth == 0 and compacted.state.state_revision == 0
    assert compacted.state.to_json() == state.to_json()
    ninth, _, _ = store.job(ref, state, version="ninth")
    with pytest.raises(codec.SparseCheckpointError, match="depth"):
        store.load(ninth)
    with pytest.raises(codec.SparseCheckpointError, match="depth"):
        store.inventory(ninth)
    continued, _, _ = store.job(full, state, version="after-compaction")
    assert store.load(continued).depth == 1


@pytest.mark.parametrize("method", ["load", "inventory"])
def test_configurable_depth_and_total_patch_bounds(setup, method):
    store, base, state = setup
    first, changed, manifest = store.job(base, state)
    with pytest.raises(codec.SparseCheckpointError, match="depth"):
        getattr(store, method)(first, limits=codec.ResolutionLimits(max_depth=0))
    second, _, second_manifest = store.job(first, changed, version="v2", changes=(3.0,))
    patch_size = max(manifest["patches"][0]["bytes"], second_manifest["patches"][0]["bytes"])
    with pytest.raises(codec.SparseCheckpointError, match="total patch"):
        getattr(store, method)(second, limits=codec.ResolutionLimits(max_total_patch_bytes=patch_size))


@pytest.mark.parametrize("limits,match", [
    (codec.ResolutionLimits(max_checkpoint_bytes=1), "byte bound"),
    (codec.ResolutionLimits(max_manifest_bytes=1), "bounded"),
    (codec.ResolutionLimits(max_patch_bytes=1), "patch exceeds"),
    (codec.ResolutionLimits(max_artifacts=1), "closure count"),
    (codec.ResolutionLimits(max_total_bytes=1), "closure bytes"),
])
@pytest.mark.parametrize("method", ["load", "inventory"])
def test_read_budgets_fail_closed(setup, limits, match, method):
    store, base, state = setup
    ref, _, _ = store.job(base, state)
    with pytest.raises(codec.SparseCheckpointError, match=match):
        getattr(store, method)(ref, limits=limits)


@pytest.mark.parametrize("method", ["load", "inventory"])
def test_corrupt_missing_and_wrong_size_dependencies_rejected(setup, method):
    store, base, state = setup
    ref, _, manifest = store.job(base, state)
    patch_path = store.paths[manifest["patches"][0]["sha256"]]
    original = patch_path.read_bytes()
    patch_path.write_bytes(b"!" + original[1:])
    with pytest.raises(codec.SparseCheckpointError, match="byte identity"):
        getattr(store, method)(ref)
    patch_path.write_bytes(original + b" ")
    with pytest.raises(codec.SparseCheckpointError, match="declared size"):
        getattr(store, method)(ref)
    patch_path.unlink()
    with pytest.raises(codec.SparseCheckpointError, match="could not be read"):
        getattr(store, method)(ref)
    del store.paths[manifest["patches"][0]["sha256"]]
    with pytest.raises(codec.SparseCheckpointError, match="trusted resolver"):
        getattr(store, method)(ref)


@pytest.mark.parametrize("inspect", [codec.resolve_checkpoint, codec.inventory_checkpoint])
def test_resolver_rejects_symlink_fifo_and_relative_paths(setup, tmp_path, inspect):
    import os
    store, base, _ = setup
    symlink = tmp_path / "link"
    symlink.symlink_to(store.paths[base["sha256"]])
    fifo = tmp_path / "fifo"
    os.mkfifo(fifo)
    for path in (symlink, fifo, Path("relative")):
        with pytest.raises(codec.SparseCheckpointError):
            inspect(base, resolver=lambda _: path)


def test_manifest_unknown_fields_paths_duplicate_refs_and_noncanonical_values_rejected(setup):
    store, base, state = setup
    _, _, manifest = store.job(base, state)
    for mutate in (
        lambda value: value.update(extra=True),
        lambda value: value["parent"].update(path="/etc/passwd"),
        lambda value: value["patches"].append(value["patches"][0]),
        lambda value: value.update(reload_semantics="carry-revision"),
        lambda value: value.update(identity_profile="arbitrary"),
        lambda value: value.pop("schema_version"),
        lambda value: value.update(schema_version="full-model"),
    ):
        altered = json.loads(json.dumps(manifest))
        mutate(altered)
        raw = json.dumps(altered, sort_keys=True, separators=(",", ":")).encode()
        with pytest.raises(codec.SparseCheckpointError):
            codec.decode_manifest(raw)
    with pytest.raises(codec.SparseCheckpointError, match="canonically"):
        codec.decode_manifest(json.dumps(manifest, indent=2).encode())
    with pytest.raises(codec.SparseCheckpointError, match="duplicate JSON"):
        codec.decode_manifest(b'{"schema":"a","schema":"b"}')


def test_ordinary_full_state_loader_rejects_sparse_manifest(setup):
    store, base, state = setup
    ref, _, _ = store.job(base, state)
    manifest = codec.decode_manifest(store.paths[ref["sha256"]].read_bytes())
    assert manifest["schema_version"] == manifest["schema"] == codec.SCHEMA
    with pytest.raises(ValueError, match="unsupported modal autoencoder state schema"):
        ma.ModalAutoencoderTrainingState.from_dict(manifest)


@pytest.mark.parametrize("method", ["load", "inventory"])
def test_unknown_full_checkpoint_fields_and_nonfinite_json_rejected(setup, method):
    store, _, state = setup
    data = state.to_dict()
    data["hidden_mutation"] = {"not_serialized": 1}
    with pytest.raises(codec.SparseCheckpointError, match="unknown fields"):
        getattr(store, method)(store.put(json.dumps(data).encode()))
    with pytest.raises(codec.SparseCheckpointError, match="non-finite"):
        getattr(store, method)(store.put(b'{"x":NaN}'))
    with pytest.raises(codec.SparseCheckpointError, match="duplicate JSON"):
        getattr(store, method)(store.put(b'{"x":1,"x":2}'))


def test_materialization_is_explicit_exclusive_and_verifies_expected_identity(setup, tmp_path):
    store, base, state = setup
    ref, _, _ = store.job(base, state)
    resolved = store.load(ref, reset_revision=False)
    destination = tmp_path / "candidate.state.json"
    assert not destination.exists()
    result = codec.materialize_checkpoint(resolved, destination)
    assert destination.read_bytes() == codec.canonical_checkpoint_bytes(resolved.state)
    assert codec.artifact_ref(result) == resolved.materialized_checkpoint
    with pytest.raises(FileExistsError):
        codec.materialize_checkpoint(resolved, destination)
    wrong = tmp_path / "wrong.json"
    with pytest.raises(codec.SparseCheckpointError, match="expected"):
        codec.write_checkpoint(resolved.state, wrong, expected_identity={"sha256": "0" * 64, "bytes": 1})
    assert not wrong.exists()


@pytest.mark.parametrize("kwargs", [{"max_depth": -1}, {"max_depth": 65}, {"max_artifacts": True},
                                  {"max_total_bytes": 0}, {"max_patch_bytes": 65 * 1024 * 1024}])
def test_resolution_configuration_cannot_disable_bounds(kwargs):
    with pytest.raises(codec.SparseCheckpointError, match="bound"):
        codec.ResolutionLimits(**kwargs)


@pytest.mark.parametrize("method", ["load", "inventory"])
def test_parent_cycle_is_rejected_before_revisit_even_with_misbehaving_reader(setup, monkeypatch, method):
    # Valid content hashes cannot practically contain a cycle; this also
    # qualifies the graph guard against a future trusted-reader substitution.
    store, base, state = setup
    ref, _, manifest = store.job(base, state, changes=())
    manifest["parent"] = ref
    raw = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    monkeypatch.setattr(codec, "_read_artifact", lambda *_: raw)
    with pytest.raises(codec.SparseCheckpointError, match="cycle"):
        getattr(store, method)(ref)


def test_manifest_encoder_strips_paths_and_rejects_normalized_provenance(setup):
    store, base, state = setup
    descriptor = {**base, "path": "/trusted/owner/base.json"}
    raw = codec.encode_manifest(parent=descriptor, base_version_id="v", patches=[],
                                materialized_checkpoint=base, state_identity=state.state_identity(), result_revision=0)
    assert b"/trusted" not in raw
    with pytest.raises(codec.SparseCheckpointError, match="noncanonical"):
        codec.encode_manifest(parent=base, base_version_id="v", patches=[], materialized_checkpoint=base,
                              state_identity=state.state_identity(), result_revision=0, provenance={1: "one"})
    with pytest.raises(codec.SparseCheckpointError, match="empty job"):
        codec.encode_manifest(parent=base, base_version_id="v", patches=[], materialized_checkpoint=base,
                              state_identity=state.state_identity(), result_revision=1)


def test_inventory_never_constructs_replays_or_serializes_weights(setup, monkeypatch):
    store, base, state = setup
    first, changed, _ = store.job(base, state, changes=(2.0, 3.0))
    second, _, _ = store.job(first, changed, version="v2", changes=(4.0,))
    resolved = store.load(second)

    def forbidden(*args, **kwargs):
        raise AssertionError("inventory must not construct or replay model weights")

    monkeypatch.setattr(ma.ModalAutoencoderTrainingState, "from_dict", forbidden)
    monkeypatch.setattr(codec, "replay_patch", forbidden)
    monkeypatch.setattr(codec, "checkpoint_identity", forbidden)
    inventory = store.inventory(second)
    assert inventory.root == second
    assert inventory.artifacts == resolved.artifacts
    assert inventory.depth == resolved.depth == 2
    assert inventory.total_patch_bytes == resolved.total_patch_bytes
    assert inventory.total_bytes == sum(ref["bytes"] for ref in inventory.artifacts)
    assert inventory.anchor_checkpoint == resolved.anchor_checkpoint == base
    assert inventory.declared_materialized_checkpoint == resolved.materialized_checkpoint
    assert inventory.semantic_replay_verified is inventory.weights_constructed is False
    full = store.inventory(base)
    assert full.root == full.anchor_checkpoint == full.declared_materialized_checkpoint == base
    assert full.depth == 0


def test_inventory_preserves_noncanonical_physical_full_root_bytes(setup):
    store, _, state = setup
    raw = json.dumps(state.to_dict(), indent=2).encode()
    ref = store.put(raw)
    inventory = store.inventory(ref)
    assert inventory.declared_materialized_checkpoint == ref
    assert inventory.root == inventory.anchor_checkpoint == ref
    assert codec.checkpoint_identity(state) != ref


def test_inventory_does_not_claim_semantic_or_materialized_byte_verification(setup):
    store, base, state = setup
    ref, _, _ = store.job(base, state, materialized_checkpoint={"sha256": "0" * 64, "bytes": 1})
    inventory = store.inventory(ref)
    assert inventory.semantic_replay_verified is False
    assert inventory.declared_materialized_checkpoint["sha256"] == "0" * 64
    with pytest.raises(codec.SparseCheckpointError, match="materialized checkpoint byte identity"):
        store.load(ref)


def test_inventory_defers_nested_full_component_normalization_to_loader(setup):
    store, _, state = setup
    data = state.to_dict()
    data["feature_embedding_weights"] = "invalid nested component"
    ref = store.put(json.dumps(data).encode())
    inventory = store.inventory(ref)
    assert inventory.semantic_replay_verified is False
    with pytest.raises(codec.SparseCheckpointError, match="invalid full legacy"):
        store.load(ref)


@pytest.mark.parametrize("updates,match", [
    ({"base_version_id": "wrong"}, "base version"),
    ({"result_revision": 10}, "result revision"),
    ({"state_identity": "0" * 64}, "result identity"),
])
def test_inventory_rejects_inconsistent_patch_declarations(setup, updates, match):
    store, base, state = setup
    ref, _, _ = store.job(base, state, **updates)
    with pytest.raises(codec.SparseCheckpointError, match=match):
        store.inventory(ref)


@pytest.mark.parametrize("updates,match", [
    ({"schema_version": "unknown-model"}, "legacy JSON checkpoint schema"),
    ({"architecture_version": "unknown-model"}, "architecture"),
])
def test_inventory_rejects_unsupported_legacy_schema(setup, updates, match):
    store, _, state = setup
    data = dict(state.to_dict(), **updates)
    ref = store.put(json.dumps(data).encode())
    with pytest.raises(codec.SparseCheckpointError, match=match):
        store.inventory(ref)


def test_inventory_component_field_inventory_matches_legacy_serialization():
    expected = set(ma.MODAL_AUTOENCODER_STATE_COMPONENT_FIELDS) | {
        "schema_version", "proof_auxiliary_head_schema_version"}
    assert set(_state().to_dict()) == expected
