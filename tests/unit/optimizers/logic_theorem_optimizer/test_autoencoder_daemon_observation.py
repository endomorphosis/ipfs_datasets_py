"""Observer identity/lifetime contracts, without native training claims."""

from concurrent.futures import ThreadPoolExecutor
import gc
import weakref

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_daemon_observation as observation
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder import ModalAutoencoderTrainingState


BINDING = {"request_sha256": "a" * 64, "launch_sha256": "b" * 64}
LINEAGE = "synthetic-observation-metrics-v1"


def _state_event(observer, state, phase="completed_cycle", **kwargs):
    observer.record_state(phase, state, cycle=1, metric_lineage=LINEAGE, **kwargs)


@pytest.mark.parametrize("binding", [None, {}, [], {**BINDING, "extra": "c" * 64},
                                      {"request_sha256": "a" * 64},
                                      {**BINDING, "launch_sha256": "B" * 64},
                                      {**BINDING, "launch_sha256": True}])
def test_binding_is_closed_and_exact(binding):
    with pytest.raises(ValueError):
        with observation.observation_session(binding=binding):
            pytest.fail("invalid binding installed")
    assert observation.current_observer() is None


def test_native_identity_is_detached_without_state_clone_or_retention(monkeypatch):
    state = ModalAutoencoderTrainingState()
    state.legal_ir_view_logits["synthetic"] = -0.0
    expected = state.state_identity_record(metric_lineage=LINEAGE).to_dict()
    reference = weakref.ref(state)
    monkeypatch.setattr(state, "to_dict", lambda: pytest.fail("weight graph serialized"))
    monkeypatch.setattr(state, "copy", lambda: pytest.fail("weight graph cloned"))
    binding = dict(BINDING)
    with observation.observation_session(binding=binding) as collector:
        binding["request_sha256"] = "c" * 64
        _state_event(collector, state, metadata={"compiler_version": "compiler", "holdout_version": "holdout"})
        first = collector.to_dict()["events"][0]
        assert first["metric_state_identity"] == expected
        assert first["versions"] == {"state_version": expected["digest"], "schema_version": LINEAGE,
                                    "compiler_version": "compiler", "holdout_version": "holdout"}
        first["metric_state_identity"]["component_digests"].clear()
        state.legal_ir_view_logits["synthetic"] = 2.0
        _state_event(collector, state, "final_shutdown")
        collector.record_return(0)
        assert collector.to_dict()["success"] is False
    payload = collector.to_dict()
    assert payload["success"] and payload["closed"] and payload["binding"] == BINDING
    assert payload["events"][0]["metric_state_identity"] == expected
    assert payload["events"][1]["metric_state_identity"]["digest"] != expected["digest"]
    assert payload["lease_authority_verified"] is False and payload["admitted"] is False
    monkeypatch.undo()
    del state
    gc.collect()
    assert reference() is None


def test_nested_context_and_exception_restore_original_context_and_error():
    failure = ValueError("original synthetic failure")
    with observation.observation_session(binding=BINDING) as outer:
        with pytest.raises(ValueError) as caught:
            with observation.observation_session(binding=BINDING) as inner:
                assert observation.current_observer() is inner
                raise failure
        assert caught.value is failure
        assert observation.current_observer() is outer
        assert inner.to_dict()["error"] == {"error_type": "builtins.ValueError", "error": str(failure)}
    assert observation.current_observer() is None
    assert not outer.to_dict()["success"] and not inner.to_dict()["success"]


def test_failure_recording_does_not_mask_primary_or_leak_context(monkeypatch):
    failure = ValueError("primary")
    with pytest.raises(ValueError) as caught:
        with observation.observation_session(binding=BINDING) as collector:
            monkeypatch.setattr(collector, "_close", lambda error: (_ for _ in ()).throw(RuntimeError("secondary")))
            raise failure
    assert caught.value is failure and observation.current_observer() is None


def test_async_threads_cannot_observe_trainer_even_with_explicit_collector():
    state = ModalAutoencoderTrainingState()
    with observation.observation_session(binding=BINDING) as collector, ThreadPoolExecutor(max_workers=1) as pool:
        assert pool.submit(observation.current_observer).result() is None
        with pytest.raises(RuntimeError, match="creating thread"):
            pool.submit(_state_event, collector, state).result()
        assert collector.to_dict()["events"] == []
    with pytest.raises(RuntimeError, match="closed"):
        _state_event(collector, state)


def test_revision_change_during_identity_capture_fails_without_partial_event(monkeypatch):
    state = ModalAutoencoderTrainingState()
    original = state.state_identity_record

    def mutating_record(*, metric_lineage=None):
        result = original(metric_lineage=metric_lineage)
        if metric_lineage is not None:
            state.legal_ir_view_logits["changed"] = 1.0
        return result

    monkeypatch.setattr(state, "state_identity_record", mutating_record)
    with observation.observation_session(binding=BINDING) as collector:
        with pytest.raises(RuntimeError, match="mutated"):
            _state_event(collector, state)
        assert collector.to_dict()["events"] == []


def test_event_count_bound_does_not_drop_records_silently(monkeypatch):
    monkeypatch.setattr(observation, "_MAX_EVENTS", 1)
    with observation.observation_session(binding=BINDING) as collector:
        _state_event(collector, ModalAutoencoderTrainingState())
        with pytest.raises(ValueError, match="count exceeds"):
            _state_event(collector, ModalAutoencoderTrainingState())


@pytest.mark.parametrize("exit_code,final", [(None, True), (2, True), (0, False)])
def test_context_exit_alone_is_not_success(exit_code, final):
    with observation.observation_session(binding=BINDING) as collector:
        if final:
            _state_event(collector, ModalAutoencoderTrainingState(), "final_shutdown")
        if exit_code is not None:
            collector.record_return(exit_code)
    assert not collector.to_dict()["success"]
