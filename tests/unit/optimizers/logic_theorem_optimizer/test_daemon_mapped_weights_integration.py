"""Actual daemon boundaries with real mapped weights and synthetic consumers.

The corpus/evaluator/projection callbacks below are fixtures. Explicit writes
and rejected trials qualify storage wiring, never learning or bridge results.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_daemon_weight_session as weights
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import uscode_modal_daemon_runner as runner
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder_arrow_weights import ArrowWeightError, MappedFeatureEmbeddingWeights
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder_checkpoint import load_checkpoint, serialize_checkpoint
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder_patch_codec import encode_patch, replay_patch
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder_state_diff import exact_state_snapshot
from tests.unit.optimizers.logic_theorem_optimizer.test_autoencoder_daemon_weight_session import make_bound_weights, _row_bits, _synthetic_edits
from tests.unit.optimizers.logic_theorem_optimizer.test_daemon_shared_target_integration import actual_run
from tests.unit.optimizers.logic_theorem_optimizer.test_daemon_corpus_input_integration import corpus_run


@pytest.fixture
def weight_run(corpus_run, monkeypatch):
    case = corpus_run
    for field in ("autoencoder_target_bundle", "autoencoder_target_bundle_sha256",
                  "autoencoder_target_bundle_bytes", "autoencoder_target_snapshot_id"):
        setattr(case.args, field, None)
    case.args.snapshot_evaluation_enabled = True
    bound = make_bound_weights(case.root / "bound-weights")
    active_path = case.root / "workspace/todo-queues" / f"{case.args.run_id}.state.json"
    active_path.parent.mkdir(parents=True, exist_ok=True)
    active_path.write_bytes(bound.base_path.read_bytes())
    session = weights.VerifiedDaemonWeightSession(bound.arrow_ref, base_artifact=bound.base_ref,
                                                  base_identity=bound.base_identity)
    snapshots, evaluated, states = [], [], []
    original_evaluate = runner.AdaptiveModalAutoencoder.evaluate

    def observe_synthetic_evaluation(model, rows, **kwargs):
        # The preexisting actual_run optimizer remains synthetic. These reads
        # exercise its genuinely mapped state at the real runner boundaries.
        states.append(model.state)
        evaluated.append((type(model.state.feature_embedding_weights), _row_bits(model.state.feature_embedding_weights)))
        return original_evaluate(model, rows, **kwargs)

    def incomplete_snapshot(snapshot, template, **kwargs):
        del template, kwargs
        snapshots.append(snapshot)
        return {"synthetic_fixture": True, "snapshot_complete": False,
                "aggregate": {"complete": False}, "evaluation_performed": False,
                "proof": {"attempted_count": 0, "valid_count": 0}}

    monkeypatch.setattr(runner.AdaptiveModalAutoencoder, "evaluate", observe_synthetic_evaluation)
    monkeypatch.setattr(runner, "evaluate_production_snapshot_bundle", incomplete_snapshot)
    try:
        yield SimpleNamespace(case=case, bound=bound, session=session, active_path=active_path,
                              snapshots=snapshots, evaluated=evaluated, states=states)
    finally:
        session.close()


@pytest.mark.parametrize("commit", [False, True], ids=["rejected-trial", "synthetic-write"])
def test_runner_bound_overlay_rollback_or_commit_matches_complete_persisted_state(weight_run, monkeypatch, commit):
    value, case = weight_run, weight_run.case
    patches = []
    oracle = load_checkpoint(value.bound.base_path, recover=False).state
    base_identity = oracle.state_identity()

    def synthetic_projection(model, rows, **kwargs):
        case.seen.projections.append((list(rows), kwargs))
        assert type(model.state.feature_embedding_weights) is MappedFeatureEmbeddingWeights
        transaction = model.state.transaction(label="explicit-fixture-projection").begin()
        _synthetic_edits(model.state)
        patch = transaction.capture_patch()
        if commit:
            transaction.commit()
        else:
            transaction.rollback()
            assert model.state.feature_embedding_weights.statistics["overlay_rows"] == 0
        patches.append(patch)
        return {"accepted_epochs": 0, "stopped_reason": "synthetic-fixture-no-learning"}

    monkeypatch.setattr(runner.AdaptiveModalAutoencoder, "train_generalizable_projection", synthetic_projection)
    with weights.weight_session(value.session):
        assert runner.run_guarded_uscode_modal_daemon(case.args) == 0
    assert len(patches) == 1
    assert weights.current_weight_session() is None
    assert value.evaluated and all(kind is MappedFeatureEmbeddingWeights for kind, _ in value.evaluated)
    assert len({id(state) for state in value.states}) == 1
    live = value.states[-1]
    if commit:
        wire = encode_patch(patches[0], base_state_identity=base_identity,
                            result_state_identity=live.state_identity(),
                            base_version_id="sha256:" + value.bound.base_ref["sha256"], sequence=0,
                            provenance={"synthetic_fixture": True, "learning_performed": False})
        replay = replay_patch(oracle, wire, expected_base_version_id="sha256:" + value.bound.base_ref["sha256"],
                              expected_sequence=0)
        assert replay["admitted"] is False
    assert oracle.state_revision == live.state_revision
    assert oracle.state_identity_record() == live.state_identity_record()
    assert oracle.to_json() == live.to_json()
    assert _row_bits(oracle.feature_embedding_weights) == _row_bits(live.feature_embedding_weights)
    summary = case.summary()
    assert summary["arrow_feature_weights"]["current_storage"] == "mapped_overlay"
    assert summary["arrow_feature_weights"]["closed"] is False  # caller owns the session
    assert summary["final_state_persistence"]["durable"] is True
    provenance = value.session.provenance()
    assert all(row["metadata"]["arrow_feature_weights_provenance"] == provenance for row in case.seen.checkpoint_writes)
    assert all(writer._closed for writer in case.seen.writers)
    final_raw = value.active_path.read_bytes()
    final = load_checkpoint(value.active_path, recover=False)
    assert final.manifest.metadata["arrow_feature_weights_provenance"] == provenance
    # Both endpoints here are detached plain native states: all38 comparison is
    # deliberately not expanded to accept mapped runtime containers.
    assert exact_state_snapshot(final.state) == exact_state_snapshot(oracle)
    assert final_raw == serialize_checkpoint(oracle, metadata=final.manifest.metadata)
    assert value.snapshots and summary["snapshot_shutdown"]["drained"]
    assert summary["latest_promoted_snapshot_complete"] is False
    snapshot_payloads = [snapshot.state_json() for snapshot in value.snapshots]
    value.session.close()
    for snapshot, payload in zip(value.snapshots, snapshot_payloads):
        assert snapshot.state_json() == payload
        detached = runner.ModalAutoencoderTrainingState.from_dict(payload)
        assert type(detached.feature_embedding_weights) is not MappedFeatureEmbeddingWeights
        assert _row_bits(detached.feature_embedding_weights) == _row_bits(oracle.feature_embedding_weights)
    with pytest.raises(ArrowWeightError, match="closed"):
        list(live.feature_embedding_weights["alpha"])
    assert value.bound.base_path.read_bytes() == serialize_checkpoint(
        load_checkpoint(value.bound.base_path, recover=False).state, metadata=value.bound.metadata)


def test_sidecar_mutation_after_consumption_blocks_persistence_and_cleans_runner(weight_run, monkeypatch):
    value, case = weight_run, weight_run.case
    original_active = value.active_path.read_bytes()

    def corrupt_after_consumption(model, rows, **kwargs):
        case.seen.projections.append((list(rows), kwargs))
        assert type(model.state.feature_embedding_weights) is MappedFeatureEmbeddingWeights
        assert _row_bits(model.state.feature_embedding_weights)
        # Same inode and length, invalid header: bounded boundary hashing must
        # catch the change, without relying on safe access to invalid buffers.
        with value.bound.arrow_path.open("r+b") as handle:
            first = handle.read(1)
            handle.seek(0)
            handle.write(bytes([first[0] ^ 1]))
            handle.flush()
        return {"accepted_epochs": 0, "stopped_reason": "synthetic-corruption-fixture"}

    monkeypatch.setattr(runner.AdaptiveModalAutoencoder, "train_generalizable_projection", corrupt_after_consumption)
    with pytest.raises(ValueError):
        with weights.weight_session(value.session):
            runner.run_guarded_uscode_modal_daemon(case.args)
    assert case.seen.projections and value.evaluated
    assert case.seen.checkpoint_writes == []
    assert value.active_path.read_bytes() == original_active
    assert value.bound.base_path.read_bytes() == original_active
    assert all(writer._closed for writer in case.seen.writers)
    assert weights.current_weight_session() is None
    assert value.session.summary()["poisoned"] is True
    summary = case.summary()
    assert summary["final_state_persistence"]["checkpoint_enqueued"] is False
    value.session.close()
    assert value.session.summary()["closed"] is True


def test_startup_compaction_reports_detached_native_without_reattachment(weight_run):
    value, case = weight_run, weight_run.case
    case.args.autoencoder_max_generalizable_entries_per_group = 1
    case.args.generalizable_projection_epochs = 0
    with weights.weight_session(value.session):
        assert runner.run_guarded_uscode_modal_daemon(case.args) == 0
    assert value.evaluated and all(kind is not MappedFeatureEmbeddingWeights for kind, _ in value.evaluated)
    summary = case.summary()["arrow_feature_weights"]
    assert summary["current_storage"] == "detached_native"
    assert summary["first_detachment_phase"]
    final = load_checkpoint(value.active_path, recover=False)
    assert set(final.state.feature_embedding_weights) == {"z-last"}
    assert final.manifest.metadata["arrow_feature_weights_provenance"] == value.session.provenance()
    state = value.states[-1]
    original_json = state.to_json()
    value.session.close()
    assert state.to_json() == original_json == final.state.to_json()
