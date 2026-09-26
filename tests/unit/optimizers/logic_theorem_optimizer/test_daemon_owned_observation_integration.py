"""Actual orchestration with synthetic consumers: wiring, not native training."""

from types import SimpleNamespace

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import uscode_modal_daemon_runner as runner
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_daemon_observation import (
    current_observer, observation_session,
)
from tests.unit.optimizers.logic_theorem_optimizer.test_daemon_shared_target_integration import actual_run
from tests.unit.optimizers.logic_theorem_optimizer.test_daemon_corpus_input_integration import corpus_run


BINDING = {"request_sha256": "a" * 64, "launch_sha256": "b" * 64}


def _main(case, monkeypatch):
    # The synthetic fixture supplies an already parsed namespace. Main's actual
    # dispatch and runner cleanup remain exercised; no native claim is made.
    monkeypatch.setattr(runner, "build_uscode_modal_daemon_arg_parser",
                        lambda: SimpleNamespace(parse_args=lambda argv: case.args))
    return runner.main([])


@pytest.mark.parametrize("before_train_mode", ["always", "off"])
def test_main_observes_full_final_state_and_binds_real_checkpoint(corpus_run, monkeypatch, before_train_mode):
    case = corpus_run
    case.args.autoencoder_before_train_eval_mode = before_train_mode
    with observation_session(binding=BINDING) as collector:
        assert _main(case, monkeypatch) == 0
        assert all(writer._closed for writer in case.seen.writers)
        assert not collector.to_dict()["success"]
    receipt = collector.to_dict()
    assert receipt["success"] and receipt["exit_code"] == 0 and receipt["closed"]
    phases = [event["phase"] for event in receipt["events"] if event["kind"] == "state"]
    assert phases == ["registered_base", "startup_complete", "before_train_evaluation",
                      "before_validation_evaluation", "before_projection", "before_after_train_evaluation",
                      "before_after_validation_evaluation", "completed_cycle", "final_shutdown"]
    selection, = [event for event in receipt["events"] if event["kind"] == "selection"]
    assert selection["train"] == {"indices": [0], "sample_ids": [case.train[0].sample_id], "record_ids": ["record-0"]}
    assert selection["validation"] == {"indices": [1], "sample_ids": [case.validation[0].sample_id], "record_ids": ["record-1"]}
    state_events = {event["phase"]: event for event in receipt["events"] if event["kind"] == "state"}
    for phase, enabled in (("before_train_evaluation", True), ("before_validation_evaluation", False),
                           ("before_after_train_evaluation", True), ("before_after_validation_evaluation", False)):
        assert state_events[phase]["metadata"]["use_sample_memory"] is enabled
    for rows, kwargs in case.seen.evaluations:
        assert kwargs["use_sample_memory"] is (rows[0].sample_id == case.train[0].sample_id)
    assert "use_sample_memory" not in state_events["before_projection"]["metadata"]
    assert state_events["registered_base"]["cycle"] == state_events["startup_complete"]["cycle"] == 0
    final = state_events["final_shutdown"]
    loaded = runner.load_autoencoder_checkpoint(case.root / "workspace/todo-queues" / f"{case.args.run_id}.state.json")
    assert loaded.manifest.metadata["daemon_invocation"] == BINDING
    assert all(write["metadata"]["daemon_invocation"] == BINDING for write in case.seen.checkpoint_writes)
    assert final["state_identity"] == loaded.state.state_identity_record().to_dict()
    assert final["metric_state_identity"] == loaded.state.state_identity_record(
        metric_lineage=runner.AUTOENCODER_DAEMON_METRIC_SCHEMA_VERSION).to_dict()
    assert final["metadata"]["final_state_persistence"]["durable"] is True
    assert final["versions"] == state_events["completed_cycle"]["versions"]
    assert final["state_identity"]["digest"] != state_events["registered_base"]["state_identity"]["digest"]
    assert current_observer() is None


def test_default_runner_omits_binding_entirely(corpus_run, monkeypatch):
    case = corpus_run
    assert _main(case, monkeypatch) == 0
    assert current_observer() is None
    assert all("daemon_invocation" not in write["metadata"] for write in case.seen.checkpoint_writes)


def test_projection_failure_preserves_original_and_has_no_final_observation(corpus_run, monkeypatch):
    case = corpus_run
    failure = ValueError("synthetic projection failure")
    case.seen.projection_error = failure
    with pytest.raises(ValueError) as caught:
        with observation_session(binding=BINDING) as collector:
            _main(case, monkeypatch)
    assert caught.value is failure
    receipt = collector.to_dict()
    assert receipt["closed"] and not receipt["success"] and receipt["exit_code"] is None
    assert receipt["error"]["error_type"] == "builtins.ValueError"
    assert not any(event.get("phase") in {"completed_cycle", "final_shutdown"} for event in receipt["events"])
    assert current_observer() is None and all(writer._closed for writer in case.seen.writers)


def test_disabled_projection_has_no_synthetic_before_projection_event(corpus_run, monkeypatch):
    case = corpus_run
    case.args.generalizable_projection_epochs = 0
    with observation_session(binding=BINDING) as collector:
        assert _main(case, monkeypatch) == 0
    assert not any(event.get("phase") == "before_projection" for event in collector.to_dict()["events"])
    assert case.seen.projections == []


def test_shutdown_guard_failure_keeps_completed_cycle_but_never_final(corpus_run, monkeypatch):
    case = corpus_run
    case.seen.corpus_failure = ("shutdown", 1)
    with pytest.raises(ValueError, match="shutdown"):
        with observation_session(binding=BINDING) as collector:
            _main(case, monkeypatch)
    phases = [event.get("phase") for event in collector.to_dict()["events"]]
    assert "completed_cycle" in phases and "final_shutdown" not in phases
    assert not collector.to_dict()["success"] and current_observer() is None


def test_startup_compaction_and_post_evaluation_guidance_are_in_complete_state(corpus_run, monkeypatch):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder_checkpoint import serialize_checkpoint

    case = corpus_run
    case.args.autoencoder_max_generalizable_entries_per_group = 1
    base = runner.ModalAutoencoderTrainingState(feature_embedding_weights={
        "synthetic-a": [0.25, 0.0], "synthetic-b": [0.5, 0.0], "synthetic-c": [0.75, 0.0],
    })
    state_path = case.root / "workspace/todo-queues" / f"{case.args.run_id}.state.json"
    state_path.parent.mkdir(parents=True)
    state_path.write_bytes(serialize_checkpoint(base))
    original_guidance = runner.project_verified_leanstral_guidance_artifacts_into_queue

    def synthetic_guidance(**kwargs):
        result = original_guidance(**kwargs)
        kwargs["autoencoder"].state.applied_leanstral_guidance_ids.append("synthetic-late-guidance")
        return result

    monkeypatch.setattr(runner, "project_verified_leanstral_guidance_artifacts_into_queue", synthetic_guidance)
    with observation_session(binding=BINDING) as collector:
        assert _main(case, monkeypatch) == 0
    events = {row["phase"]: row for row in collector.to_dict()["events"] if row["kind"] == "state"}
    assert events["registered_base"]["state_identity"]["digest"] == base.state_identity()
    assert events["registered_base"]["metadata"]["checkpoint_loaded"]
    assert events["startup_complete"]["state_identity"]["digest"] != base.state_identity()
    assert events["before_after_validation_evaluation"]["state_identity"]["digest"] != events["completed_cycle"]["state_identity"]["digest"]
    final = runner.load_autoencoder_checkpoint(state_path)
    assert final.state.applied_leanstral_guidance_ids == ["synthetic-late-guidance"]
    assert events["final_shutdown"]["state_identity"] == final.state.state_identity_record().to_dict()
    assert case.seen.checkpoint_writes[0]["metadata"]["reason"] == "bounded_startup_state"
    assert all(row["metadata"]["daemon_invocation"] == BINDING for row in case.seen.checkpoint_writes)


def test_exact_evaluation_cache_hits_do_not_claim_new_evaluations(corpus_run, monkeypatch):
    case = corpus_run
    case.args.generalizable_projection_epochs = 0
    case.args.max_cycles = 2
    with observation_session(binding=BINDING) as collector:
        assert _main(case, monkeypatch) == 0
    rows = collector.to_dict()["events"]
    assert len([row for row in rows if row.get("phase") == "completed_cycle"]) == 2
    for phase in ("before_train_evaluation", "before_validation_evaluation"):
        assert [row["cycle"] for row in rows if row.get("phase") == phase] == [1]


def test_failure_after_final_durability_does_not_become_success(corpus_run, monkeypatch):
    case = corpus_run
    original_close = runner.AsyncArtifactWriter.close
    failure = ValueError("synthetic cleanup failure after durability")
    failed = False

    def failing_close(writer, *args, **kwargs):
        nonlocal failed
        original_close(writer, *args, **kwargs)
        if not failed:
            failed = True
            raise failure

    monkeypatch.setattr(runner.AsyncArtifactWriter, "close", failing_close)
    with pytest.raises(ValueError) as caught:
        with observation_session(binding=BINDING) as collector:
            _main(case, monkeypatch)
    assert caught.value is failure
    receipt = collector.to_dict()
    assert any(row.get("phase") == "final_shutdown" for row in receipt["events"])
    assert receipt["closed"] and not receipt["success"] and receipt["exit_code"] is None
    assert receipt["error"]["error"] == str(failure)
    assert current_observer() is None and all(writer._closed for writer in case.seen.writers)
