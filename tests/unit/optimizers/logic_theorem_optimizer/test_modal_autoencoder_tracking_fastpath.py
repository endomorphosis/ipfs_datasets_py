"""Scalar dispatch must retain generic protocols, identity and replay semantics."""
from array import array
from collections import UserList
from collections.abc import Mapping, Sequence
import hashlib
import json
import math
from types import MappingProxyType

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_autoencoder as ma
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_autoencoder_state_version as version
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_autoencoder_sparse_checkpoint as checkpoint
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder_patch_codec import encode_patch


@pytest.mark.parametrize("value", [None, False, True, 0, 2**80, -0.0, 0.125, "", "é", b"bytes", bytearray(b"bytes")])
def test_atomic_leaves_preserve_values_without_mutation_callbacks(value):
    def forbidden(*args):
        pytest.fail("merely wrapping a scalar reported a mutation")
    assert version._tracked_value(value, forbidden, forbidden, ("leaf",)) is value


class FloatMapping(float, Mapping):
    def __new__(cls):
        value = float.__new__(cls, 2.0)
        value.rows = {"row": [1.0, -0.0]}
        return value

    def __iter__(self):
        return iter(self.rows)

    def __len__(self):
        return len(self.rows)

    def __getitem__(self, key):
        return self.rows[key]


class FloatSequence(float, Sequence):
    def __new__(cls):
        value = float.__new__(cls, 3.0)
        value.rows = ([1.0, -0.0],)
        return value

    def __len__(self):
        return len(self.rows)

    def __getitem__(self, key):
        return self.rows[key]


@pytest.mark.parametrize("original,key", [(FloatMapping(), "row"), (FloatSequence(), 0)])
def test_numeric_subclasses_with_container_protocols_still_track_nested_mutation(original, key):
    changes, before = [], []
    wrapped = version._tracked_value(original, lambda: changes.append(True),
                                     lambda path, op: before.append((path, op)), ("component",))
    assert wrapped is not original and not isinstance(wrapped, float)
    wrapped[key][0] = 0.75
    assert changes == [True] and before == [(("component", key, 0), "set")]
    assert original[key][0] == 1.0
    wrapped[key].append(0.5)
    assert len(changes) == 2 and before[-1] == (("component", key, 2), "insert")


@pytest.mark.parametrize("container", [tuple([1.0, -0.0]), UserList([1.0, -0.0]), array("d", [1.0, -0.0])])
def test_generic_sequences_inside_readonly_mapping_remain_tracked(container):
    tracker = version.IncrementalStateIdentity(schema_version="fixture", metric_lineage={})
    wrapped = tracker.track_component("nested", MappingProxyType({"row": container}), mutation=False)
    identity = tracker.identity()
    wrapped["row"][0] = 0.75
    assert tracker.revision == identity.revision + 1
    assert tracker.identity().digest != identity.digest
    assert list(container) == [1.0, -0.0]
    assert math.copysign(1.0, wrapped["row"][1]) == -1.0


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_atomic_dispatch_does_not_bypass_nonfinite_identity_rejection(value):
    tracker = version.IncrementalStateIdentity(schema_version="fixture", metric_lineage={})
    tracker.track_component("weights", {"row": [value]}, mutation=False)
    with pytest.raises(ValueError, match="non-finite"):
        tracker.identity()


def test_pre_mutation_failure_preserves_nested_value_and_revision():
    blocked = []
    def before(component, path, operation):
        blocked.append((component, path, operation))
        raise RuntimeError("writer rejected")
    tracker = version.IncrementalStateIdentity(schema_version="fixture", metric_lineage={}, before_mutation=before)
    wrapped = tracker.track_component("weights", {"row": [0.25]}, mutation=False)
    identity = tracker.identity()
    with pytest.raises(RuntimeError, match="writer rejected"):
        wrapped["row"][0] = 0.5
    assert wrapped["row"] == [0.25]
    assert tracker.identity() == identity
    assert blocked == [("weights", ("row", 0), "set")]


def test_full_reload_sparse_replay_and_rollback_preserve_exact_candidate(tmp_path):
    state = ma.ModalAutoencoderTrainingState(
        feature_embedding_weights={"row": [0.25, -0.0], "é": [0.125]},
        feature_family_logits={"row": {"deontic": 0.5}}, applied_todo_ids=["prior"],
    )
    paths = {}
    def store(raw):
        digest = hashlib.sha256(raw).hexdigest()
        path = tmp_path / digest
        path.write_bytes(raw)
        paths[digest] = path
        return {"sha256": digest, "bytes": len(raw)}
    original_json = state.to_json()
    original_identity = state.state_identity_record()
    base = store(checkpoint.canonical_checkpoint_bytes(state))
    restored = checkpoint.resolve_checkpoint(base, resolver=lambda ref: paths[ref["sha256"]])
    assert restored.state.to_json() == original_json
    assert restored.state.state_identity_record() == original_identity
    with pytest.raises(RuntimeError, match="rollback"):
        with state.transaction():
            state.feature_embedding_weights["row"][0] = 99.0
            raise RuntimeError("rollback")
    assert state.to_json() == original_json and state.state_identity_record() == original_identity
    before = state.state_identity()
    with state.transaction(label="accepted") as tx:
        state.feature_embedding_weights["row"][0] = 0.75
        state.feature_embedding_weights["new"] = [0.0, -0.0]
        state.feature_family_logits["row"]["deontic"] = 0.625
        state.applied_todo_ids.append("accepted")
    patch = store(encode_patch(tx.patch, base_state_identity=before, result_state_identity=state.state_identity(),
        base_version_id="base", sequence=0, provenance={"run_id": "fixture"}))
    candidate = store(checkpoint.encode_manifest(parent=base, base_version_id="base", patches=[patch],
        materialized_checkpoint=checkpoint.checkpoint_identity(state), state_identity=state.state_identity(),
        result_revision=state.state_revision, provenance={"run_id": "fixture"}))
    terminal = checkpoint.resolve_checkpoint(candidate, resolver=lambda ref: paths[ref["sha256"]], reset_revision=False)
    fresh = checkpoint.resolve_checkpoint(candidate, resolver=lambda ref: paths[ref["sha256"]])
    assert terminal.state.to_json() == fresh.state.to_json() == state.to_json()
    assert terminal.state.state_identity_record() == state.state_identity_record()
    assert fresh.state.state_revision == 0 and fresh.state.state_identity() == state.state_identity()
    assert terminal.materialized_checkpoint == fresh.materialized_checkpoint == checkpoint.checkpoint_identity(state)
    assert b"-0.0" in checkpoint.canonical_checkpoint_bytes(fresh.state)
    # Byte verification still runs after an earlier successful replay.
    raw = paths[patch["sha256"]].read_bytes()
    paths[patch["sha256"]].write_bytes(raw[:-1] + bytes([raw[-1] ^ 1]))
    with pytest.raises(checkpoint.SparseCheckpointError, match="byte identity"):
        checkpoint.resolve_checkpoint(candidate, resolver=lambda ref: paths[ref["sha256"]])
