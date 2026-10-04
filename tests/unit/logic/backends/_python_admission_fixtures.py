"""Real private scheduler isolation for in-process proof admission tests."""
from types import SimpleNamespace
import threading

import pytest

from ipfs_datasets_py.logic.backends import python_admission as admission
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import resource_scheduler as scheduler
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.proof_resource_safety import ProofHostResources


@pytest.fixture
def python_pool(tmp_path, monkeypatch):
    healthy = ProofHostResources(8, 8192, 8192, pid_task_limit=8192, available_pid_tasks=8192)
    current = [healthy]
    sampled = threading.Event()
    def sample():
        sampled.set()
        if isinstance(current[0], Exception):
            raise current[0]
        return current[0]
    owner = scheduler.GlobalResourceScheduler(scheduler.ResourceSchedulerConfig.for_proof_host(
        state_path=tmp_path/'python-proof-private-pool.json', proof_resource_sampler=sample,
        total_cpu_slots=4, total_memory_mb=4096, total_child_process_slots=16,
        lane_reservations={}, proof_memory_headroom_mb=64, proof_backoff_seconds=.01,
        poll_interval_seconds=.002, auto_renew_leases=False))
    acquired = []
    original = owner.acquire
    def acquire(*args, **kwargs):
        lease = original(*args, **kwargs)
        acquired.append(lease)
        return lease
    monkeypatch.setattr(owner, 'acquire', acquire)
    # Threads without copied context must still use this actual isolated pool.
    monkeypatch.setattr(admission, 'get_global_resource_scheduler', lambda: owner)
    with admission.python_admission_context(scheduler=owner):
        yield SimpleNamespace(owner=owner, current=current, healthy=healthy,
                              sampled=sampled, acquired=acquired)
    assert owner.snapshot()['active_lease_count'] == owner.snapshot()['waiting_request_count'] == 0
    assert all(lease.released for lease in acquired)
