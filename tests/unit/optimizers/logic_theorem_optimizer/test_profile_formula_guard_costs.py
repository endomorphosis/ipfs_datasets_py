"""Stdlib controls for source-bound, nonreplacement guard cost observation."""
from contextlib import contextmanager
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import threading
from types import SimpleNamespace

import pytest

_PATH = Path(__file__).resolve().parents[4] / "benchmarks/profile_formula_guard_costs.py"
_SPEC = importlib.util.spec_from_file_location("_tested_formula_cost_profile", _PATH)
profile = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(profile)


def _leaf():
    return sum(range(100))


def _outer():
    return _leaf() + _leaf()


def _registry(*items):
    registry = {}
    for label, function, role in items:
        profile.register(registry, label, function, role)
    return registry


def _observer(registry, **options):
    return profile.GuardCostObserver(registry, **options)


def _descriptor(summary, label):
    return next(item["id"] for item in summary["registry"] if item["label"] == label)


def _rows(summary, label):
    identifier = _descriptor(summary, label)
    return [row for row in summary["spans"] if row[3] == identifier]


def test_nested_selected_children_are_subtracted_once():
    registry = _registry(("outer", _outer, "benchmark"), ("leaf", _leaf, "benchmark"))
    observer = _observer(registry)
    with observer:
        with observer.public_scope():
            assert _outer() == 9900
    summary = observer.summary()
    outer, leaves = _rows(summary, "outer")[0], _rows(summary, "leaf")
    assert len(leaves) == 2 and all(row[1] == outer[0] for row in leaves)
    assert outer[9] == outer[8] - sum(row[8] for row in leaves)
    assert outer[11] == outer[10] - sum(row[10] for row in leaves)
    root = _rows(summary, "complete_public_call")[0]
    assert root[9] == root[8] - outer[8]
    assert root[11] == root[10] - outer[10]
    assert not summary["overflow"] and summary["hooks_restored"]


class _Writer:
    def __init__(self, descriptor):
        self.descriptor = descriptor

    @contextmanager
    def _locked_state(self):
        os.fsync(self.descriptor)
        yield None
        os.fsync(self.descriptor)


def test_generator_resumptions_are_segments_not_transactions():
    with tempfile.TemporaryFile() as stream:
        registry = _registry(("lock_segments", _Writer._locked_state, "resource_scheduler"))
        observer = _observer(registry)
        with observer:
            with observer.public_scope():
                with _Writer(stream.fileno())._locked_state():
                    pass
    summary = observer.summary()
    segments = _rows(summary, "lock_segments")
    assert len(segments) == 2
    assert summary["registry"][_descriptor(summary, "lock_segments")]["kind"] == "generator_segment"
    assert len(_rows(summary, "os.fsync")) == 2
    assert all(row[12] == "c_return" for row in _rows(summary, "os.fsync"))
    assert summary["generator_scope"] == "resumption_segments_not_logical_transactions"


def test_fsync_exception_is_observed_and_hooks_restore():
    observer = _observer(_registry(("lock_segments", _Writer._locked_state, "resource_scheduler")))
    with pytest.raises(OSError):
        with observer:
            with observer.public_scope():
                with _Writer(-1)._locked_state():
                    pass
    summary = observer.summary()
    rows = _rows(summary, "os.fsync")
    assert len(rows) == 1 and rows[0][12] == "c_exception"
    aggregate = next(row for row in summary["aggregates"] if row[1] == _descriptor(summary, "os.fsync"))
    assert aggregate[-1] == 1
    assert summary["hooks_restored"] and not summary["overflow"]


def test_same_c_callable_outside_bound_scheduler_frame_is_not_labeled_fsync():
    with tempfile.TemporaryFile() as stream:
        observer = _observer(_registry(("outer", _outer, "benchmark")))
        with observer:
            with observer.public_scope():
                os.fsync(stream.fileno())
                _outer()
    assert _rows(observer.summary(), "os.fsync") == []


def test_scheduler_like_name_with_wrong_source_role_is_not_fsync():
    with tempfile.TemporaryFile() as stream:
        observer = _observer(_registry(("wrong_role", _Writer._locked_state, "benchmark")))
        with observer:
            with observer.public_scope():
                with _Writer(stream.fileno())._locked_state():
                    pass
    assert _rows(observer.summary(), "os.fsync") == []


def test_permitted_prior_main_hook_is_chained_and_restored_on_error():
    previous = sys.getprofile()
    calls = []
    def prior(frame, event, arg):
        if event == "call" and frame.f_code is _leaf.__code__:
            calls.append(True)
    sys.setprofile(prior)
    try:
        observer = _observer(_registry(("leaf", _leaf, "benchmark")), expected_main_profiler=prior)
        with pytest.raises(RuntimeError, match="authored refusal"):
            with observer:
                with observer.public_scope():
                    _leaf()
                    raise RuntimeError("authored refusal")
        assert sys.getprofile() is prior and calls
        assert observer.summary()["hooks_restored"]
    finally:
        sys.setprofile(previous)


def test_unapproved_existing_main_hook_is_refused_without_overwriting_it():
    previous = sys.getprofile()
    def prior(frame, event, arg):
        pass
    sys.setprofile(prior)
    try:
        observer = _observer(_registry(("leaf", _leaf, "benchmark")))
        with pytest.raises(ValueError, match="unsupported existing"):
            with observer:
                pass
        assert sys.getprofile() is prior
    finally:
        sys.setprofile(previous)


def test_span_limit_refusal_does_not_interrupt_operation_and_restores_hooks():
    observer = _observer(_registry(("outer", _outer, "benchmark"), ("leaf", _leaf, "benchmark")), max_spans=2)
    with observer:
        with observer.public_scope():
            assert _outer() == 9900
    summary = observer.summary()
    assert summary["overflow"] and summary["hooks_restored"]
    assert len(summary["spans"]) <= 2


@pytest.mark.parametrize("option,value", [("max_events", 0), ("max_spans", True), ("max_threads", 33)])
def test_invalid_observer_limits_refuse(option, value):
    with pytest.raises(ValueError, match="bounded observer"):
        _observer(_registry(("leaf", _leaf, "benchmark")), **{option: value})


class _Heartbeat:
    def __init__(self, action):
        self.action = action

    def _heartbeat_loop(self):
        self.action()


def _background_fixture(action):
    keeper = _Heartbeat(action)
    thread = threading.Thread(target=keeper._heartbeat_loop)
    registry = _registry(("heartbeat", _Heartbeat._heartbeat_loop, "resource_scheduler"),
                         ("leaf", _leaf, "benchmark"), ("outer", _outer, "benchmark"))
    return thread, registry


def test_known_owned_background_is_labeled_separately():
    ready, go, done, finish = (threading.Event() for _ in range(4))
    def action():
        ready.set()
        go.wait(2)
        _outer()
        done.set()
        finish.wait(2)
    thread, registry = _background_fixture(action)
    thread.start()
    assert ready.wait(2)
    try:
        observer = _observer(registry, allowed_background_threads=[thread])
        with observer:
            with observer.public_scope():
                go.set()
                assert done.wait(2)
        summary = observer.summary()
        scopes = {row["thread_id"]: row["scope"] for row in summary["threads"]}
        assert scopes[thread.ident] == "owned_background"
        assert scopes[threading.get_ident()] == "inline_main"
        assert len(_rows(summary, "leaf")) == 2
        assert not summary["overflow"] and summary["hooks_restored"]
    finally:
        finish.set()
        thread.join(2)
    assert not thread.is_alive()


def test_background_frame_entered_before_window_is_explicitly_censored():
    ready, go, done = (threading.Event() for _ in range(3))
    def action():
        ready.set()
        go.wait(2)
    thread, registry = _background_fixture(action)
    thread.start()
    assert ready.wait(2)
    try:
        observer = _observer(registry, allowed_background_threads=[thread])
        with observer:
            with observer.public_scope():
                go.set()
                thread.join(2)
                done.set()
        summary = observer.summary()
        assert not summary["overflow"]
        assert any(row["edge"] == "entered_before_window" for row in summary["censored_background"])
        assert _rows(summary, "heartbeat") == []
    finally:
        go.set()
        thread.join(2)


def test_background_unfinished_span_is_censored_without_adding_complete_cost():
    ready, go, entered, finish = (threading.Event() for _ in range(4))
    def long_span():
        entered.set()
        finish.wait(2)
    def action():
        ready.set()
        go.wait(2)
        long_span()
    thread, registry = _background_fixture(action)
    profile.register(registry, "long_span", long_span, "benchmark")
    thread.start()
    assert ready.wait(2)
    try:
        observer = _observer(registry, allowed_background_threads=[thread])
        with observer:
            with observer.public_scope():
                go.set()
                assert entered.wait(2)
        summary = observer.summary()
        assert not summary["overflow"] and _rows(summary, "long_span") == []
        assert any(row["edge"] == "unfinished_at_window_end" for row in summary["censored_background"])
    finally:
        finish.set()
        go.set()
        thread.join(2)


def test_unknown_background_thread_is_refused_before_hook_change():
    ready, finish = threading.Event(), threading.Event()
    def action():
        ready.set()
        finish.wait(2)
    thread, registry = _background_fixture(action)
    thread.start()
    assert ready.wait(2)
    previous = sys.getprofile()
    try:
        with pytest.raises(ValueError, match="unapproved existing"):
            with _observer(registry):
                pass
        assert sys.getprofile() is previous and threading.getprofile() is None
    finally:
        finish.set()
        thread.join(2)


def _native_event(name, device):
    return SimpleNamespace(name=name, device_type=device, device_index=0, thread=1,
        time_range=SimpleNamespace(start=1., end=3.), cpu_time_total=2., self_cpu_time_total=1.,
        device_time_total=1., self_device_time_total=0.5)


def test_compact_native_trace_aggregates_complete_events():
    actual = [_native_event("aten::eq", "DeviceType.CPU"), _native_event("eq_kernel", "DeviceType.CUDA")]
    trace = profile._operator_trace(SimpleNamespace(events=lambda: actual), max_events=2)
    assert trace["event_count"] == 2 and trace["cuda_event_count"] == 1
    assert len(trace["aggregates"]) == 2
    assert trace["record_shapes"] is trace["profile_memory"] is trace["with_stack"] is False


@pytest.mark.parametrize("case", ["no_cuda", "too_many", "nonfinite"])
def test_native_trace_refuses_unavailable_or_out_of_bounds_activity(case):
    actual = [_native_event("aten::eq", "DeviceType.CPU"), _native_event("eq_kernel", "DeviceType.CUDA")]
    limit = 2
    if case == "no_cuda":
        actual.pop()
    elif case == "too_many":
        limit = 1
    else:
        actual[1].device_time_total = float("nan")
    with pytest.raises(ValueError):
        profile._operator_trace(SimpleNamespace(events=lambda: actual), max_events=limit)

