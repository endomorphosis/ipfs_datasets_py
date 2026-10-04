"""Request-local diagnostics preserve pressure decisions and nested accounting."""
from dataclasses import replace
import json
import threading

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import (
    GlobalResourceScheduler, LeaseCancelledError, LeaseTimeoutError, ResourceSchedulerConfig,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.proof_resource_safety import ProofHostResources


def owner(tmp_path, *, cooldown=0):
    healthy = ProofHostResources(8, 8192, 8192)
    current = [healthy]
    calls = []

    def sample():
        calls.append(current[0])
        return current[0]

    config = ResourceSchedulerConfig.for_proof_host(state_path=tmp_path / 'ledger.json',
        proof_resource_sampler=sample, lane_reservations={}, auto_renew_leases=False,
        total_child_process_slots=4, proof_backoff_seconds=cooldown, poll_interval_seconds=.005)
    return GlobalResourceScheduler(config), healthy, current, calls


@pytest.mark.parametrize('field,value,reason', [
    ('available_memory_mb', 100, 'proof_memory_headroom'),
    ('memory_stall_percent', 5, 'proof_memory_stall'),
    ('cpu_stall_percent', 80, 'proof_cpu_stall'),
    ('io_stall_percent', 20, 'proof_io_stall'),
])
@pytest.mark.parametrize('nested', [False, True])
def test_exact_primary_sample_survives_unwind_without_resampling(tmp_path, field, value, reason, nested):
    scheduler, healthy, current, calls = owner(tmp_path)
    parent = scheduler.acquire('orchestration', cpu_slots=2, memory_mb=1024,
        child_process_slots=2, timeout=0) if nested else None
    current[0] = replace(healthy, **{field: value})
    before = len(calls)
    try:
        with pytest.raises(LeaseTimeoutError) as caught:
            scheduler.acquire('orchestration', cpu_slots=1, memory_mb=512,
                parent_lease=parent, timeout=0, request_id='not-for-diagnostics')
        assert len(calls) == before + 1
        record = caught.value.admission_observation
        assert record['complete_admission_decision'] is False
        assert record['primary_gate']['status'] == 'refused'
        assert record['primary_gate']['reason'] == reason
        sample = record['last_sample']
        assert sample['host'][field] == value
        assert sample['reserved_root_memory_mb'] == (1024 if nested else 0)
        assert sample['additional_request_memory_mb'] == (0 if nested else 512)
        current[0] = healthy
        assert sample['host'][field] == value
        raw = json.dumps(record, allow_nan=False)
        assert len(raw) < 4096 and 'not-for-diagnostics' not in raw
        if parent:
            assert parent.lease_key not in raw and parent.lease_id not in raw
        snapshot = scheduler.snapshot()
        assert snapshot['waiting_request_count'] == 0
        assert snapshot['active_lease_count'] == int(nested)
        assert 'admission_observation' not in scheduler.state_path.read_text()
    finally:
        if parent:
            parent.release()
    assert scheduler.snapshot()['active_lease_count'] == 0


def test_backoff_from_another_request_has_no_invented_sample(tmp_path):
    scheduler, healthy, current, calls = owner(tmp_path, cooldown=1)
    current[0] = replace(healthy, memory_stall_percent=10)
    with pytest.raises(LeaseTimeoutError):
        scheduler.acquire('orchestration', memory_mb=512, timeout=0)
    current[0] = healthy
    before = len(calls)
    with pytest.raises(LeaseTimeoutError) as caught:
        scheduler.acquire('orchestration', memory_mb=512, timeout=0)
    assert len(calls) == before
    record = caught.value.admission_observation
    assert record['primary_gate']['status'] == 'backoff'
    assert record['last_sample'] is None


def test_own_sample_is_retained_across_cooldown_polls(tmp_path):
    scheduler, healthy, current, calls = owner(tmp_path, cooldown=1)
    current[0] = replace(healthy, io_stall_percent=20)
    before = len(calls)
    with pytest.raises(LeaseTimeoutError) as caught:
        scheduler.acquire('orchestration', memory_mb=512, timeout=.02)
    assert len(calls) == before + 1
    record = caught.value.admission_observation
    assert record['primary_gate']['status'] == 'backoff'
    assert record['last_sample']['host']['io_stall_percent'] == 20
    assert record['last_sample']['observed_at'] <= record['primary_gate']['observed_at']


def test_nonprimary_capacity_refusal_is_not_reported_as_pressure(tmp_path):
    scheduler, _, _, _ = owner(tmp_path)
    with scheduler.acquire('orchestration', cpu_slots=2, memory_mb=1024, timeout=0) as parent:
        with parent.acquire_child(cpu_slots=2, memory_mb=1024, timeout=0):
            with pytest.raises(LeaseTimeoutError) as caught:
                parent.acquire_child(cpu_slots=1, memory_mb=1, timeout=0)
    record = caught.value.admission_observation
    assert record['primary_gate']['status'] == 'passed'
    assert record['last_sample']['reason'] is None
    assert record['complete_admission_decision'] is False


def test_cancellation_keeps_original_error_and_cleans_waiter(tmp_path):
    scheduler, healthy, current, _ = owner(tmp_path)
    current[0] = replace(healthy, memory_stall_percent=10)
    event = threading.Event(); event.set()
    with pytest.raises(LeaseCancelledError) as caught:
        scheduler.acquire('orchestration', memory_mb=512, timeout=1, cancel_event=event)
    assert caught.value.admission_observation['terminal'] == 'cancelled'
    assert scheduler.snapshot()['waiting_request_count'] == 0


def test_malformed_sampler_still_raises_the_original_timeout(tmp_path):
    scheduler, _, current, _ = owner(tmp_path)
    current[0] = object()
    with pytest.raises(LeaseTimeoutError) as caught:
        scheduler.acquire('orchestration', memory_mb=512, timeout=0)
    assert caught.value.admission_observation['last_sample'] is None
    assert scheduler.snapshot()['waiting_request_count'] == 0
