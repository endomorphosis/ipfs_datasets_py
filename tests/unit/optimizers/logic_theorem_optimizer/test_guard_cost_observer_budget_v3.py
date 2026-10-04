"""Stdlib controls for the separately pinned owned observer budget adapter."""
import hashlib
import importlib.util
from pathlib import Path
import sys

import pytest

_BENCHMARKS = Path(__file__).resolve().parents[4] / "benchmarks"
_PATH = _BENCHMARKS / "guard_cost_observer_budget_v3.py"
_SPEC = importlib.util.spec_from_file_location("_tested_cost_budget_v3", _PATH)
adapter = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(adapter)


def _leaf():
    return 7


def _registry():
    registry = {}
    adapter.register(registry, "leaf", _leaf, "benchmark")
    return registry


@pytest.mark.parametrize("limit", [1, 1000000, 1000001, 4000000])
def test_bounded_callback_cap_is_owned_by_new_instance(limit):
    instance = adapter.GuardCostObserver(_registry(), max_events=limit)
    assert instance.max_events == limit
    assert adapter._BASE.MAX_EVENTS == 1000000
    assert instance.max_spans == 20000 and instance.max_threads == 32


@pytest.mark.parametrize("limit", [True, 0, -1, 4000001, 1.5])
def test_invalid_callback_caps_refuse_without_changing_base(limit):
    constructor = adapter._BASE.GuardCostObserver.__init__
    with pytest.raises(ValueError, match="bounded v3 callback"):
        adapter.GuardCostObserver(_registry(), max_events=limit)
    assert adapter._BASE.MAX_EVENTS == 1000000
    assert adapter._BASE.GuardCostObserver.__init__ is constructor


def test_base_source_and_constructor_are_unchanged_by_completed_observation():
    path = _BENCHMARKS / "profile_formula_guard_costs_v2.py"
    before = path.read_bytes()
    constructor = adapter._BASE.GuardCostObserver.__init__
    hooks = sys.getprofile()
    instance = adapter.GuardCostObserver(_registry(), max_events=4000000)
    with instance:
        with instance.public_scope():
            assert _leaf() == 7
    summary = instance.summary()
    assert summary["bounds"]["max_events"] == 4000000
    assert summary["hooks_restored"] and not summary["overflow"]
    assert sys.getprofile() is hooks
    assert path.read_bytes() == before
    assert len(before) == adapter.BASE_SOURCE_BYTES
    assert hashlib.sha256(before).hexdigest() == adapter.BASE_SOURCE_SHA256
    assert adapter._BASE.MAX_EVENTS == 1000000
    assert adapter._BASE.GuardCostObserver.__init__ is constructor


def test_larger_limit_counts_events_above_old_cap_and_still_refuses_at_new_cap():
    instance = adapter.GuardCostObserver(_registry(), max_events=4000000)
    with instance:
        with instance.public_scope():
            instance.callbacks = 1000000
            assert _leaf() == 7
    assert instance.summary()["callback_events_observed"] > 1000000
    assert not instance.summary()["overflow"]
    instance = adapter.GuardCostObserver(_registry(), max_events=4000000)
    with instance:
        with instance.public_scope():
            instance.callbacks = 4000000
            assert _leaf() == 7
    assert instance.summary()["callback_events_observed"] > 4000000
    assert instance.summary()["overflow"] and instance.summary()["hooks_restored"]


def test_budget_policy_retains_other_limits_and_diagnostic_scope():
    policy = adapter.callback_limit_policy()
    assert policy["all_profile_callback_cap"] == 4000000
    assert policy["base_observer_callback_cap"] == 1000000
    assert policy["selected_span_cap"] == 20000 and policy["thread_cap"] == 32
    assert policy["native_operator_cap"] == 50000
    assert policy["base_module_or_class_mutated"] is False and policy["performance_qualified"] is False
    assert policy["base_source_sha256"] == adapter.BASE_SOURCE_SHA256


def test_original_base_remains_unchanged_with_identity_bound_successor():
    original = _BENCHMARKS / "profile_formula_guard_costs.py"
    before = original.read_bytes()
    observer = adapter.GuardCostObserver(_registry(), max_events=4000000)
    with observer:
        with observer.public_scope():
            assert _leaf() == 7
    assert observer.summary()["registry_binding"] == "code_object_identity_with_strong_references"
    assert adapter.callback_limit_policy()["registry_binding"] == "code_object_identity_with_strong_references"
    assert original.read_bytes() == before
    assert hashlib.sha256(before).hexdigest() == "61786537ff7e6d442322d307ef7d7a1a609cf9279d8a005017eb9e1e73127577"
