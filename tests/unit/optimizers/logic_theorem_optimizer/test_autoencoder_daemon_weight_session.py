"""Bound real Arrow/checkpoint lifecycle with explicit synthetic state writes.

These small fixtures exercise native storage, tracking and transport. They do
not generate embeddings, train a model, evaluate bridges or admit anything.
"""
from __future__ import annotations

import copy
import gc
import hashlib
import json
import struct
import weakref
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_daemon_weight_session as weights
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import uscode_modal_daemon_runner as runner
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.async_artifact_writer import AsyncArtifactWriter, ArtifactFsyncPolicy
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder import (
    MODAL_AUTOENCODER_STATE_COMPONENT_FIELDS, ModalAutoencoderTrainingState,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder_arrow_weights import (
    ArrowWeightError, MappedFeatureEmbeddingWeights, build_feature_embedding_weights_ipc,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder_checkpoint import (
    load_checkpoint, serialize_checkpoint,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder_patch_codec import encode_patch, replay_patch


def _ref(path):
    raw = path.read_bytes()
    return {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}


def _row_bits(rows):
    return [(key, b"".join(struct.pack(">d", value) for value in rows[key])) for key in rows]


def make_bound_weights(directory):
    directory.mkdir(parents=True, exist_ok=True)
    state = ModalAutoencoderTrainingState(
        feature_embedding_weights={"alpha": [-0.0, 0.12345678901234568], "empty": [], "z-last": [2.0]},
        feature_family_logits={"alpha": {"deontic": 0.25}},
        decoded_embeddings={"remembered": [-0.0, 0.75]},
        applied_todo_ids=["fixture-prior", "fixture-prior"],
    )
    state.legal_ir_view_logits["fixture-nonzero-revision"] = 0.125
    state.applied_proof_feedback_ids.append("fixture-only-not-proof")
    base_path = directory / "base.compact"
    metadata = {"synthetic_fixture": True, "reason": "weight-session-unit-base"}
    base_path.write_bytes(serialize_checkpoint(state, metadata=metadata))
    base_ref = _ref(base_path)
    state = load_checkpoint(base_path, recover=False).state
    arrow_path = directory / "features.arrow"
    build_feature_embedding_weights_ipc(
        state.feature_embedding_weights, arrow_path,
        base_checkpoint_sha256=base_ref["sha256"], batch_rows=1,
    )
    return SimpleNamespace(state=state, base_ref=base_ref, arrow_ref=_ref(arrow_path),
                           base_path=base_path, arrow_path=arrow_path, metadata=metadata,
                           base_identity=state.state_identity_record().to_dict())


@pytest.fixture
def bound(tmp_path):
    return make_bound_weights(tmp_path / "bound")


def _session(bound, **overrides):
    return weights.VerifiedDaemonWeightSession(**{
        "arrow_ref": bound.arrow_ref, "base_artifact": bound.base_ref,
        "base_identity": bound.base_identity, **overrides,
    })


def test_attach_preserves_same_loaded_state_all_components_revision_and_full_checkpoint(bound):
    state = bound.state
    fields = MODAL_AUTOENCODER_STATE_COMPONENT_FIELDS
    assert len(fields) == 38 and state.state_revision > 0
    original_objects = {field: getattr(state, field) for field in fields}
    original_json = state.to_json()
    original_rows = _row_bits(state.feature_embedding_weights)
    identities = [state.state_identity_record(metric_lineage=lineage) for lineage in (None, "fixture-metric-v1")]
    original_bytes = serialize_checkpoint(state, metadata=bound.metadata)
    session = _session(bound)
    try:
        session.verify_base_state(state)
        assert session.attach(state) is state
        assert type(state.feature_embedding_weights) is MappedFeatureEmbeddingWeights
        assert all(getattr(state, field) is original_objects[field] for field in fields
                   if field != "feature_embedding_weights")
        assert _row_bits(state.feature_embedding_weights) == original_rows
        assert state.to_json() == original_json
        assert [state.state_identity_record(metric_lineage=lineage) for lineage in (None, "fixture-metric-v1")] == identities
        assert serialize_checkpoint(state, metadata=bound.metadata) == original_bytes == bound.base_path.read_bytes()
        session.verify_boundary("attached", state)
        summary = session.summary()
        assert summary["base_verified"] and summary["attached"]
        assert summary["current_storage"] == "mapped_overlay"
        assert summary["mapping_statistics"]["overlay_rows"] == 0
        assert summary["provenance"] == session.provenance()
        provenance = session.provenance()
        assert provenance["artifact"] == {key: bound.arrow_ref[key] for key in ("sha256", "bytes")}
        assert provenance["base_artifact"] == {key: bound.base_ref[key] for key in ("sha256", "bytes")}
        assert provenance["base_identity"] == bound.base_identity
        assert provenance["whole_training_zero_copy"] is False
        assert provenance["full_checkpoint_authoritative"] is True
    finally:
        session.close()
    assert session.summary()["closed"]


@pytest.mark.parametrize("change", ["base_sha", "identity_digest", "identity_revision"])
def test_incorrect_base_binding_fails_without_modifying_loaded_state(bound, change):
    base_ref, identity = copy.deepcopy(bound.base_ref), copy.deepcopy(bound.base_identity)
    if change == "base_sha":
        base_ref["sha256"] = "a" * 64
    elif change == "identity_digest":
        identity["digest"] = "b" * 64
    else:
        identity["revision"] += 1
    old_map, old_json = bound.state.feature_embedding_weights, bound.state.to_json()
    session = None
    try:
        with pytest.raises(ValueError):
            session = _session(bound, base_artifact=base_ref, base_identity=identity)
            session.verify_base_state(bound.state)
            session.attach(bound.state)
        assert bound.state.feature_embedding_weights is old_map
        assert bound.state.to_json() == old_json
    finally:
        if session is not None:
            session.close()


@pytest.mark.parametrize("change", ["zero_sign", "order", "membership"])
def test_correct_declared_base_hash_does_not_authorize_different_sidecar_rows(bound, tmp_path, change):
    rows = {key: list(value) for key, value in bound.state.feature_embedding_weights.items()}
    if change == "zero_sign":
        rows["alpha"][0] = 0.0
    elif change == "order":
        rows = dict(reversed(list(rows.items())))
    else:
        rows["invented"] = [1.0]
    path = tmp_path / "mismatched.arrow"
    build_feature_embedding_weights_ipc(rows, path, base_checkpoint_sha256=bound.base_ref["sha256"])
    original = bound.state.feature_embedding_weights
    session = _session(bound, arrow_ref=_ref(path))
    try:
        with pytest.raises(ValueError):
            session.verify_base_state(bound.state)
            session.attach(bound.state)
        assert bound.state.feature_embedding_weights is original
    finally:
        session.close()


def _synthetic_edits(state):
    state.feature_embedding_weights["alpha"][:] = [9.0, -0.0]
    state.feature_embedding_weights["inserted"] = [0.5, 0.25]
    del state.feature_embedding_weights["z-last"]


def test_real_rejection_rollback_and_portable_committed_patch_match_plain_full_state(bound):
    plain = load_checkpoint(bound.base_path, recover=False).state
    session = _session(bound)
    try:
        session.attach(bound.state)
        before = bound.state.state_identity()
        original_json = plain.to_json()
        patches = []
        for state in (plain, bound.state):
            trial = state.transaction(label="explicit-synthetic-rejected-trial").begin()
            _synthetic_edits(state)
            patches.append(trial.capture_patch())
            trial.rollback()
            assert state.to_json() == original_json
            assert state.state_identity() == before
        assert patches[0] == patches[1]
        assert _row_bits(plain.feature_embedding_weights) == _row_bits(bound.state.feature_embedding_weights)
        assert bound.state.feature_embedding_weights.statistics["overlay_rows"] == 0
        with bound.state.transaction(label="explicit-synthetic-commit") as transaction:
            _synthetic_edits(bound.state)
        version = "sha256:" + bound.base_ref["sha256"]
        wire = encode_patch(transaction.patch, base_state_identity=before,
                            result_state_identity=bound.state.state_identity(),
                            base_version_id=version, sequence=0,
                            provenance={"synthetic_fixture": True, "learning_performed": False})
        replay = replay_patch(plain, wire, expected_base_version_id=version, expected_sequence=0)
        assert replay["admitted"] is False
        assert plain.state_revision == bound.state.state_revision
        assert plain.state_identity_record() == bound.state.state_identity_record()
        assert plain.to_json() == bound.state.to_json()
        assert _row_bits(plain.feature_embedding_weights) == _row_bits(bound.state.feature_embedding_weights)
        assert serialize_checkpoint(plain, metadata=bound.metadata) == serialize_checkpoint(bound.state, metadata=bound.metadata)
        assert len(json.loads(plain.to_json())) >= len(MODAL_AUTOENCODER_STATE_COMPONENT_FIELDS)
        session.verify_boundary("after_synthetic_commit", bound.state)
        assert session.summary()["current_storage"] == "mapped_overlay"
    finally:
        session.close()


@pytest.mark.parametrize("detach", ["compaction", "state_copy"])
def test_allowed_native_detachment_is_reported_and_never_silently_reattached(bound, detach):
    session = _session(bound)
    try:
        session.attach(bound.state)
        mapped = bound.state.feature_embedding_weights
        if detach == "compaction":
            bound.state.compact_generalizable_capacity(1)
            current = bound.state
        else:
            current = bound.state.copy()
            current._state_identity_tracker.restore_revision(bound.state.state_revision)
        assert type(current.feature_embedding_weights) is not MappedFeatureEmbeddingWeights
        detached = current.feature_embedding_weights
        session.verify_boundary(detach, current)
        # The worker's final boundary supplies no state argument. It must use
        # the replacement observed above, not the originally attached state.
        session.verify_boundary("later")
        assert current.feature_embedding_weights is detached and detached is not mapped
        summary = session.summary()
        assert summary["current_storage"] == "detached_native"
        assert summary["first_detachment_phase"] == detach
        assert summary["boundaries"][-1] == {"phase": "later", "storage": "detached_native"}
        before_close = current.to_json()
        session.close()
        assert current.to_json() == before_close
    finally:
        session.close()


@pytest.mark.parametrize("release", ["state_copy", "close"])
def test_session_releases_tracked_state_and_mapping_without_losing_diagnostic_counters(bound, release):
    session = _session(bound)
    try:
        session.attach(bound.state)
        bound.state.feature_embedding_weights["alpha"][0] = 0.5
        before = dict(bound.state.feature_embedding_weights.statistics)
        assert before["overlay_rows"] == 1
        old_state = weakref.ref(bound.state)
        old_mapping = weakref.ref(bound.state.feature_embedding_weights)
        if release == "state_copy":
            replacement = bound.state.copy()
            replacement._state_identity_tracker.restore_revision(bound.state.state_revision)
            # Native copy reads untouched mapped rows; retain those reads in
            # the last observed counters rather than expecting pre-copy stats.
            before = dict(bound.state.feature_embedding_weights.statistics)
            session.verify_boundary("native_state_replacement", replacement)
        else:
            session.close()
        # Drop all test-owned strong references. Collection is necessary for
        # ordinary tracked-state cycles; no timing or GC policy is qualified.
        bound.state = None
        gc.collect()
        assert old_state() is None
        assert old_mapping() is None
        expected = {**before, "closed": release == "close"}
        assert session.summary()["mapping_statistics"] == expected
        if release == "state_copy":
            session.verify_boundary("after_old_state_collection")
            assert session.summary()["current_storage"] == "detached_native"
            latest_state = weakref.ref(replacement)
            replacement = None
            session.close()
            gc.collect()
            assert latest_state() is None
        assert session.summary()["closed"] is True
        assert session.summary()["mapping_statistics"] == {**before, "closed": True}
    finally:
        session.close()


def test_foreign_mapping_cannot_be_mislabeled_as_native_detachment(bound):
    session, foreign = _session(bound), _session(bound)
    other_state = load_checkpoint(bound.base_path, recover=False).state
    try:
        session.attach(bound.state)
        foreign.attach(other_state)
        assert bound.state.feature_embedding_weights._base is not other_state.feature_embedding_weights._base
        # Even identical bytes/base identity cannot make a separately owned
        # mapping subject to this session's lifetime and integrity checks.
        bound.state.feature_embedding_weights = other_state.feature_embedding_weights
        with pytest.raises(weights.DaemonWeightSessionError, match="unbound representation"):
            session.verify_boundary("foreign_mapping", bound.state)
        assert session.summary()["poisoned"] is True
        assert session.summary()["current_storage"] != "detached_native"
    finally:
        session.close()
        foreign.close()


def test_same_owner_rebound_overlay_retains_mapped_boundary_contract(bound):
    session = _session(bound)
    try:
        session.attach(bound.state)
        original = bound.state.feature_embedding_weights
        bound.state.feature_embedding_weights = original
        rebound = bound.state.feature_embedding_weights
        assert rebound._base is original._base
        session.verify_boundary("same_owner_rebound", bound.state)
        assert session.summary()["current_storage"] == "mapped_overlay"
        assert session.summary()["first_detachment_phase"] is None
        assert _row_bits(rebound) == _row_bits(original)
    finally:
        session.close()


def test_snapshot_and_queued_full_checkpoint_are_detached_before_mapping_close(bound, tmp_path):
    session = _session(bound)
    writer = AsyncArtifactWriter(spool_dir=tmp_path / "spool", autostart=False,
                                 fsync_policy=ArtifactFsyncPolicy.disabled())
    try:
        session.attach(bound.state)
        _synthetic_edits(bound.state)
        expected_json = bound.state.to_json()
        expected_identity = bound.state.state_identity_record()
        metadata = {"synthetic_fixture": True, "arrow_feature_weights_provenance": session.provenance()}
        snapshot = runner.build_autoencoder_evaluation_snapshot(
            bound.state, sequence=1, compiler_version="fixture-only", holdout_sample_ids=["fixture"],
            validation_mode="synthetic-fixture", metadata=metadata,
        )
        handle = writer.snapshot_state_checkpoint(bound.state, cycle=1, metadata=metadata)
        output = tmp_path / "detached.compact"
        future = writer.write_state_checkpoint(output, handle, cycle=1, compact=True)
        session.close()
        with pytest.raises(ArrowWeightError, match="closed"):
            list(bound.state.feature_embedding_weights["alpha"])
        assert snapshot.state_json() == json.loads(expected_json)
        detached = ModalAutoencoderTrainingState.from_dict(snapshot.state_json())
        assert type(detached.feature_embedding_weights) is not MappedFeatureEmbeddingWeights
        assert _row_bits(detached.feature_embedding_weights) == _row_bits(json.loads(expected_json)["feature_embedding_weights"])
        writer.start()
        future.result(timeout=5)
        checkpoint = load_checkpoint(output, recover=False)
        assert checkpoint.state.to_json() == expected_json
        assert checkpoint.state.state_identity_record() == expected_identity
        assert checkpoint.manifest.metadata["arrow_feature_weights_provenance"] == metadata["arrow_feature_weights_provenance"]
    finally:
        writer.close(wait=True, cancel_pending=True)
        session.close()


def test_nested_context_refusal_and_exception_restore_without_implicit_close(bound):
    outer, inner = _session(bound), _session(bound)
    failure = KeyboardInterrupt("explicit-context-fixture")
    try:
        assert weights.current_weight_session() is None
        with weights.weight_session(outer):
            assert weights.current_weight_session() is outer
            with pytest.raises(weights.DaemonWeightSessionError, match="already installed"):
                with weights.weight_session(inner):
                    pytest.fail("nested owner session was installed")
            assert weights.current_weight_session() is outer
            assert not inner.summary()["closed"]
        assert weights.current_weight_session() is None
        assert not outer.summary()["closed"]
        with pytest.raises(KeyboardInterrupt) as caught:
            with weights.weight_session(inner):
                assert weights.current_weight_session() is inner
                raise failure
        assert caught.value is failure
        assert weights.current_weight_session() is None
        assert not inner.summary()["closed"]
    finally:
        outer.close()
        inner.close()
