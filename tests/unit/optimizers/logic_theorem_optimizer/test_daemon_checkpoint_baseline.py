"""Real main/writer persistence with explicitly synthetic model consumers.

These fixtures qualify checkpoint lineage, durability and object ownership.
They perform no native training, bridge evaluation or admission.
"""
from __future__ import annotations

from dataclasses import fields
import gc
import inspect
import json
from types import SimpleNamespace
import weakref

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_autoencoder_checkpoint as codec
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import uscode_modal_daemon_runner as runner
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_daemon_observation import observation_session
from tests.unit.optimizers.logic_theorem_optimizer.test_daemon_shared_target_integration import actual_run


BINDING = {"request_sha256": "a" * 64, "launch_sha256": "b" * 64}


def _runner_baseline():
    """Observe the queue lineage at a boundary without retaining its frame."""
    frame = inspect.currentframe()
    try:
        while frame is not None:
            if frame.f_code.co_name == "_run_guarded_uscode_modal_daemon":
                return frame.f_locals.get("persisted_baseline")
            frame = frame.f_back
        raise AssertionError("expected actual daemon frame")
    finally:
        del frame


@pytest.fixture
def baseline_run(actual_run, monkeypatch):
    case = actual_run
    for name in ("autoencoder_target_bundle", "autoencoder_target_bundle_sha256",
                 "autoencoder_target_bundle_bytes", "autoencoder_target_snapshot_id"):
        setattr(case.args, name, None)
    case.args.max_cycles = 3
    case.args.async_artifact_full_checkpoint_every_n_cycles = 99
    state_path = case.root / "workspace/todo-queues" / f"{case.args.run_id}.state.json"
    delta_path = state_path.with_name(f"{case.args.run_id}.state-deltas.bin")
    snapshots, chains = [], []
    original_snapshot = runner.AsyncArtifactWriter.snapshot_state_checkpoint

    def snapshot(writer, state, **kwargs):
        before = _runner_baseline()
        reason = kwargs.get("metadata", {}).get("reason")
        if reason == "clean_shutdown":
            # Observe the real full+delta files before ordinary shutdown
            # replaces the full checkpoint. This is a bounded test barrier.
            assert writer.wait_until_idle(timeout=5)
            if state_path.exists():
                chains.append((state_path.read_bytes(), delta_path.read_bytes() if delta_path.exists() else b""))
        handle = original_snapshot(writer, state, **kwargs)
        snapshots.append({"handle": handle, "cycle": kwargs["cycle"],
                          "full": kwargs.get("full", True), "reason": reason,
                          "base": kwargs.get("base_baseline"), "queued_before": before,
                          "state_json": state.to_json(), "revision": state.state_revision,
                          "state_identity": state.state_identity_record().to_dict()})
        return handle

    monkeypatch.setattr(runner.AsyncArtifactWriter, "snapshot_state_checkpoint", snapshot)
    # Main's dispatch and cleanup execute unchanged; only argument parsing
    # uses the preexisting bounded synthetic-consumer fixture namespace.
    monkeypatch.setattr(runner, "build_uscode_modal_daemon_arg_parser",
                        lambda: SimpleNamespace(parse_args=lambda argv: case.args))
    return SimpleNamespace(case=case, path=state_path, delta_path=delta_path,
                           snapshots=snapshots, chains=chains)


def _run(value):
    with observation_session(binding=BINDING) as observation:
        assert runner.main([]) == 0
    assert observation.to_dict()["success"]
    assert all(writer._closed for writer in value.case.seen.writers)
    return observation.to_dict()


def _cycles(value):
    return [row for row in value.snapshots if row["reason"] is None]


def _load_saved_chain(tmp_path, raw, deltas, *, recover=False):
    path, delta_path = tmp_path / "saved-full.bin", tmp_path / "saved-deltas.bin"
    path.write_bytes(raw)
    delta_path.write_bytes(deltas)
    loaded = codec.load_checkpoint(path, delta_path=delta_path, allow_json=False, recover=recover)
    return loaded, delta_path


@pytest.mark.parametrize(("cycles", "interval", "kinds", "applied"), [
    (3, 99, [True, False, False], 2),
    (5, 3, [True, False, True, False, False], 2),
])
def test_real_main_full_delta_chain_interval_reset_and_exact_shutdown(
    baseline_run, tmp_path, cycles, interval, kinds, applied,
):
    value = baseline_run
    value.case.args.max_cycles = cycles
    value.case.args.async_artifact_full_checkpoint_every_n_cycles = interval
    _run(value)
    rows = _cycles(value)
    assert [row["full"] for row in rows] == kinds
    assert rows[0]["queued_before"] is None  # no eager full-state baseline
    for previous, row in zip(rows, rows[1:]):
        assert row["queued_before"] is previous["handle"].checkpoint_baseline
        if not row["full"]:
            assert row["base"] is previous["handle"].checkpoint_baseline
    raw, deltas = value.chains[-1]
    loaded, _ = _load_saved_chain(tmp_path, raw, deltas)
    assert loaded.applied_delta_count == applied
    assert loaded.state.to_json() == rows[-1]["state_json"]
    assert loaded.state.state_revision == rows[-1]["revision"]
    assert loaded.state.state_identity_record().to_dict() == rows[-1]["state_identity"]
    assert loaded.state.legal_ir_view_logits["synthetic_cycle"] == float(cycles)
    final = codec.load_checkpoint(value.path, allow_json=False, recover=False)
    assert final.manifest.kind == "full"
    assert final.manifest.metadata["reason"] == "clean_shutdown"
    assert final.state.to_json() == loaded.state.to_json()
    assert final.state.state_revision == loaded.state.state_revision
    assert value.path.read_bytes() == codec.serialize_checkpoint(final.state, metadata=final.manifest.metadata)
    assert value.case.summary()["final_state_persistence"]["durable"] is True


def test_chain_recovers_only_incomplete_tail_without_changing_prior_state(baseline_run, tmp_path):
    value = baseline_run
    _run(value)
    raw, deltas = value.chains[-1]
    row = _cycles(value)[-1]
    incomplete = _cycles(value)[-1]["handle"].payload[:19]
    loaded, delta_path = _load_saved_chain(tmp_path, raw, deltas + incomplete, recover=True)
    assert loaded.recovered_tail_bytes == len(incomplete)
    assert loaded.applied_delta_count == 2
    assert loaded.state.to_json() == row["state_json"]
    assert loaded.state.state_revision == row["revision"]
    assert delta_path.read_bytes() == deltas


def test_restart_captures_loaded_checkpoint_baseline_and_continues_delta_chain(baseline_run, monkeypatch, tmp_path):
    value = baseline_run
    _run(value)
    prior = codec.load_checkpoint(value.path, allow_json=False, recover=False)
    prior_identity = prior.state.state_identity_record().to_dict()
    captures = []
    original = runner.checkpoint_baseline

    def capture(state, **kwargs):
        result = original(state, **kwargs)
        captures.append((state.state_identity_record().to_dict(), result))
        return result

    monkeypatch.setattr(runner, "checkpoint_baseline", capture)
    value.snapshots.clear()
    value.case.args.max_cycles = 5
    _run(value)
    assert len(captures) == 1 and captures[0][0] == prior_identity
    rows = _cycles(value)
    assert [(row["cycle"], row["full"]) for row in rows] == [(4, False), (5, False)]
    assert rows[0]["base"] is captures[0][1]
    assert rows[1]["base"] is rows[0]["handle"].checkpoint_baseline
    loaded, _ = _load_saved_chain(tmp_path, *value.chains[-1])
    assert loaded.applied_delta_count == 2
    assert loaded.state.to_json() == rows[-1]["state_json"]
    assert loaded.state.state_revision == rows[-1]["revision"]


def test_startup_compaction_reuses_successfully_written_full_handle(baseline_run, monkeypatch):
    value = baseline_run
    value.case.args.autoencoder_max_generalizable_entries_per_group = 1
    state = runner.ModalAutoencoderTrainingState(feature_embedding_weights={
        "first": [0.25, -0.0], "second": [0.5, 0.0], "last": [0.75, 0.0],
    })
    value.path.parent.mkdir(parents=True, exist_ok=True)
    value.path.write_bytes(codec.serialize_checkpoint(state))
    monkeypatch.setattr(runner, "checkpoint_baseline",
                        lambda *args, **kwargs: pytest.fail("startup full already supplies its baseline"))
    _run(value)
    startup = [row for row in value.snapshots if row["reason"] == "bounded_startup_state"]
    assert len(startup) == 1 and startup[0]["cycle"] == 0 and startup[0]["full"]
    assert _cycles(value)[0]["queued_before"] is startup[0]["handle"].checkpoint_baseline
    final = codec.load_checkpoint(value.path, allow_json=False, recover=False)
    assert len(final.state.feature_embedding_weights) == 1


def test_baselines_do_not_retain_replaced_cycle_graphs(baseline_run, monkeypatch):
    value = baseline_run
    original = runner.AdaptiveModalAutoencoder.train_generalizable_projection
    replaced = []
    checks = []

    def synthetic_replacement(model, rows, **kwargs):
        if len(replaced) >= 2:
            gc.collect()
            # Startup retains the initial graph separately. The graph from
            # cycle1 has no reason to survive the completed cycle2 handoff.
            checks.append(replaced[1]() is None)
        old = model.state
        model.state = old.copy()
        model.state._state_identity_tracker.restore_revision(old.state_revision)
        replaced.append(weakref.ref(old))
        return original(model, rows, **kwargs)

    monkeypatch.setattr(runner.AdaptiveModalAutoencoder, "train_generalizable_projection", synthetic_replacement)
    _run(value)
    assert checks == [True]
    gc.collect()
    assert all(ref() is None for ref in replaced)
    for row in value.snapshots:
        token = row["handle"].checkpoint_baseline
        assert type(token) is codec.CheckpointBaseline
        assert all(type(getattr(token, field.name)) in {str, int, bytes, tuple} for field in fields(token))
        assert all(type(key) is str and type(digest) is str for key, digest in token.component_digests)


def test_enqueue_failure_keeps_previous_queued_baseline_and_invocation_failed(baseline_run, monkeypatch):
    value = baseline_run
    error = RuntimeError("synthetic delta enqueue rejection")
    at_failure = []

    def reject(writer, path, snapshot, **kwargs):
        del writer, path, kwargs
        at_failure.append((_runner_baseline(), snapshot.checkpoint_baseline))
        raise error

    monkeypatch.setattr(runner.AsyncArtifactWriter, "append_state_delta", reject)
    with pytest.raises(RuntimeError) as caught:
        with observation_session(binding=BINDING) as observation:
            runner.main([])
    assert caught.value is error
    receipt = observation.to_dict()
    assert receipt["closed"] and not receipt["success"] and receipt["exit_code"] is None
    rows = _cycles(value)
    assert [row["cycle"] for row in rows] == [1, 2]
    previous, rejected = at_failure[0]
    assert previous is rows[0]["handle"].checkpoint_baseline
    assert rejected is rows[1]["handle"].checkpoint_baseline and rejected != previous
    shutdown = [row for row in value.snapshots if row["reason"] == "clean_shutdown"]
    assert shutdown and shutdown[0]["queued_before"] is previous
    assert all(writer._closed for writer in value.case.seen.writers)
    # Existing cleanup may persist an independent full state on failure. That
    # does not turn the observed invocation into successful completion.
    final = codec.load_checkpoint(value.path, allow_json=False, recover=False)
    assert final.state.to_json() == shutdown[0]["state_json"]


def test_real_writer_final_disk_failure_is_not_success_or_durable(baseline_run, monkeypatch):
    value = baseline_run
    original = runner.AsyncArtifactWriter._apply_manifest
    error = OSError("synthetic final checkpoint disk failure")

    def fail_final(writer, path, *, replayed):
        manifest = json.loads(path.read_text())
        if manifest.get("metadata", {}).get("reason") == "clean_shutdown":
            raise error
        return original(writer, path, replayed=replayed)

    monkeypatch.setattr(runner.AsyncArtifactWriter, "_apply_manifest", fail_final)
    try:
        with pytest.raises(OSError) as caught:
            with observation_session(binding=BINDING) as observation:
                runner.main([])
        assert caught.value is error
        receipt = observation.to_dict()
        assert receipt["closed"] and not receipt["success"]
        assert not any(event.get("phase") == "final_shutdown" for event in receipt["events"])
        assert value.case.seen.writers[0].summary()["failed_count"] == 1
        recovered = codec.load_checkpoint(value.path, delta_path=value.delta_path, recover=False)
        assert recovered.applied_delta_count == 2
        assert recovered.state.to_json() == _cycles(value)[-1]["state_json"]
        # Failed payload+manifest survive for the real crash-replay mechanism.
        pending = list(value.case.seen.writers[0].spool_dir.glob("*.manifest.json"))
        assert any(json.loads(path.read_text()).get("metadata", {}).get("reason") == "clean_shutdown" for path in pending)
    finally:
        for writer in value.case.seen.writers:
            writer.close(wait=True, timeout=5)
    monkeypatch.setattr(runner.AsyncArtifactWriter, "_apply_manifest", original)
    replay_writer = runner.AsyncArtifactWriter(value.case.seen.writers[0].spool_dir, autostart=False)
    try:
        receipts = replay_writer.replay_crash_artifacts()
        assert len(receipts) == 1 and receipts[0].replayed
        final = codec.load_checkpoint(value.path, allow_json=False, recover=False)
        assert final.manifest.metadata["reason"] == "clean_shutdown"
        assert final.state.to_json() == _cycles(value)[-1]["state_json"]
        assert final.state.state_revision == _cycles(value)[-1]["revision"]
        assert replay_writer.replay_crash_artifacts() == []
    finally:
        replay_writer.close(wait=True, timeout=5)
