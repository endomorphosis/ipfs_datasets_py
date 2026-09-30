"""Legacy dispatch preserves the owned envelope and observes hardware limits."""
import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legacy_span_capacity import legacy_span_capacity_plan

PROBE = {"hardware_cpu_count": 20, "affinity_cpu_count": 20, "cgroup_cpu_count": 6,
         "available_memory_mb": 20000, "cgroup_memory_remaining_mb": 14000}


def plan(**kwargs):
    base = dict(requested_compiler_workers=8, requested_batch_size=32,
        memory_budget_mb=12288, cpu_budget=6, process_budget=12,
        fixed_resident_mb=4096, probe=PROBE)
    return legacy_span_capacity_plan(**{**base, **kwargs})


def test_one_model_and_cpu_envelope_control_width():
    result = plan()
    assert result["compiler_workers"] == 4
    assert result["model_owners"] == 1
    assert result["batch_size"] == 32
    assert result["compiler_chunk_size"] == 8
    assert result["max_submitted_compiler_tasks"] == 8
    assert result["estimated_group_memory_mb"] <= 12288
    assert result["reservation_acquired"] is False
    assert result["admitted"] is False


def test_shrink_batch_under_memory_pressure_instead_of_exceeding_reservation():
    result = plan(memory_budget_mb=5000)
    assert result["batch_size"] == 4
    assert result["compiler_workers"] == 1
    assert result["estimated_group_memory_mb"] <= 5000


def test_live_fixed_owner_not_counted_twice_against_available_memory():
    observed = {**PROBE, "available_memory_mb": 3000, "cgroup_memory_remaining_mb": 3000}
    assert plan(probe=observed)["compiler_workers"] == 0
    assert plan(probe=observed, already_resident_mb=4096)["compiler_workers"] == 3
    assert plan(memory_budget_mb=4096, probe=observed, already_resident_mb=4096)["compiler_workers"] == 0


@pytest.mark.parametrize("kwargs", [
    {"process_budget": 3}, {"cpu_budget": 2}, {"memory_budget_mb": 0},
    {"pending_span_count": 0}, {"probe": {**PROBE, "available_memory_mb": None}},
    {"probe": {**PROBE, "probe_errors": ["invalid_cgroup_cpu_limit"]}},
])
def test_missing_capacity_defers_without_forcing_a_worker(kwargs):
    result = plan(**kwargs)
    assert result["compiler_workers"] == result["model_owners"] == result["batch_size"] == 0
    assert result["max_inflight_batches"] == 0


def test_affinity_bounds_even_when_reservation_has_more_slots():
    result = plan(probe={**PROBE, "affinity_cpu_count": 3})
    assert result["compiler_workers"] == 1


@pytest.mark.parametrize("kwargs", [
    {"requested_compiler_workers": True}, {"requested_compiler_workers": 9},
    {"requested_batch_size": 33}, {"fixed_resident_mb": 0},
    {"already_resident_mb": 4097}, {"per_span_working_set_mb": 0},
])
def test_bad_resource_estimates_fail_closed(kwargs):
    with pytest.raises(ValueError, match="invalid"):
        plan(**kwargs)
