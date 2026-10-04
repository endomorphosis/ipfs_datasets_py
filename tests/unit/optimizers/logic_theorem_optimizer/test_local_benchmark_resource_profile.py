"""Operator-selected benchmark tolerance retains hard and ancestor pressure gates."""
from dataclasses import replace
import json

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import resource_scheduler as mod
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.proof_resource_safety import ProofHostResources
from ipfs_datasets_py.logic.software_contracts.codebase_resources import codebase_admission_timeout


@pytest.fixture
def environment(tmp_path, monkeypatch):
    for name in (mod.DEFAULT_PROOF_PROFILE_ENV, mod.DEFAULT_PROOF_RECOVERY_ENV,
                 'IPFS_DATASETS_PROOF_RESOURCE_SAFETY', mod.DEFAULT_CPU_ENV,
                 mod.DEFAULT_MEMORY_ENV, mod.DEFAULT_CHILD_PROCESS_ENV):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv(mod.DEFAULT_STATE_ENV, str(tmp_path / 'scheduler.json'))
    current = [ProofHostResources(8, 8192, 8192, pid_task_limit=1024, available_pid_tasks=1024)]
    def sampler():
        if isinstance(current[0], Exception):
            raise current[0]
        return current[0]
    monkeypatch.setattr(mod, 'collect_proof_host_resources', sampler)
    return current


def select(monkeypatch):
    monkeypatch.setenv(mod.DEFAULT_PROOF_PROFILE_ENV, mod.LOCAL_BENCHMARK_PROOF_PROFILE)


def test_default_policy_and_wait_remain_conservative(environment):
    cfg = mod.default_resource_scheduler_config()
    assert cfg.proof_resource_profile is None
    assert cfg.proof_memory_stall_percent == 2
    assert not cfg.proof_recovery_enabled
    assert codebase_admission_timeout(remaining_seconds=120) == 30


def test_profile_preserves_reservations_and_persists_identity(environment, monkeypatch):
    select(monkeypatch)
    cfg = mod.default_resource_scheduler_config()
    assert cfg.proof_memory_stall_percent == 10
    assert cfg.proof_memory_headroom_mb == 8192 - int(8192 * .8)
    assert (cfg.proof_recovery_enabled, cfg.proof_recovery_samples,
            cfg.proof_recovery_interval_seconds, cfg.proof_recovery_grants) == (True, 2, .25, 1)
    owner = mod.GlobalResourceScheduler(cfg)
    with owner.acquire('snapshot_evaluation', memory_mb=512, timeout=0):
        state = json.loads(owner.state_path.read_text())
        assert state['config']['proof_resource_profile'] == mod.LOCAL_BENCHMARK_PROOF_PROFILE
        with pytest.raises(mod.ResourceConfigurationError, match='active shared state'):
            mod.GlobalResourceScheduler(replace(cfg, proof_resource_profile=None,
                                                proof_memory_stall_percent=2))


@pytest.mark.parametrize('value', ['', 'local-benchmark', 'local-benchmark@2', 'LOCAL-benchmark@1'])
def test_unknown_profiles_rejected_before_host_probe(environment, monkeypatch, value):
    monkeypatch.setenv(mod.DEFAULT_PROOF_PROFILE_ENV, value)
    monkeypatch.setattr(mod, 'collect_proof_host_resources', lambda: pytest.fail('invalid profile probed host'))
    with pytest.raises(mod.ResourceConfigurationError, match='unknown'):
        mod.default_resource_scheduler_config()
    with pytest.raises(mod.ResourceConfigurationError, match='unknown'):
        codebase_admission_timeout(remaining_seconds=120)


@pytest.mark.parametrize('name,value,message', [
    (mod.DEFAULT_STATE_ENV, None, 'explicit absolute'),
    (mod.DEFAULT_STATE_ENV, 'relative.json', 'explicit absolute'),
    ('IPFS_DATASETS_PROOF_RESOURCE_SAFETY', '0', 'requires proof safety'),
    (mod.DEFAULT_PROOF_RECOVERY_ENV, '0', 'requires proof recovery'),
])
def test_profile_rejects_implicit_store_or_disabled_safety(environment, monkeypatch, name, value, message):
    select(monkeypatch)
    if value is None:
        monkeypatch.delenv(name)
    else:
        monkeypatch.setenv(name, value)
    with pytest.raises(mod.ResourceConfigurationError, match=message):
        mod.default_resource_scheduler_config()


@pytest.mark.parametrize('observed,admitted', [(1.9, True), (2, True), (9.99, True), (10, False), (18.83, False)])
@pytest.mark.parametrize('child', [False, True])
def test_memory_psi_threshold_applies_to_roots_and_children(environment, monkeypatch, observed, admitted, child):
    select(monkeypatch)
    owner = mod.GlobalResourceScheduler(mod.default_resource_scheduler_config())
    with owner.acquire('snapshot_evaluation', cpu_slots=2, memory_mb=1024,
                       child_process_slots=2, timeout=0) as parent:
        environment[0] = replace(environment[0], memory_stall_percent=observed)
        lease = owner.try_acquire('snapshot_evaluation', memory_mb=256,
                                  parent=parent if child else None)
        assert (lease is not None) == admitted
        if lease:
            lease.release()
        else:
            assert owner.snapshot()['proof_backoff']['reason'] == 'proof_memory_stall'
    assert owner.snapshot()['active_lease_count'] == 0
    assert owner.snapshot()['waiting_request_count'] == 0


@pytest.mark.parametrize('change,reason', [
    ({'available_memory_mb': 500}, 'proof_memory_headroom'),
    ({'available_pid_tasks': 0}, 'proof_pid_headroom'),
    ({'cpu_stall_percent': 50}, 'proof_cpu_stall'),
    ({'io_stall_percent': 10}, 'proof_io_stall'),
])
def test_profile_does_not_bypass_other_hard_gates(environment, monkeypatch, change, reason):
    select(monkeypatch)
    owner = mod.GlobalResourceScheduler(mod.default_resource_scheduler_config())
    environment[0] = replace(environment[0], **change)
    assert owner.try_acquire('snapshot_evaluation', memory_mb=512) is None
    assert owner.snapshot()['proof_backoff']['reason'] == reason


def test_unknown_telemetry_still_refused(environment, monkeypatch):
    select(monkeypatch)
    owner = mod.GlobalResourceScheduler(mod.default_resource_scheduler_config())
    environment[0] = OSError('telemetry unavailable')
    assert owner.try_acquire('snapshot_evaluation', memory_mb=512) is None
    assert owner.snapshot()['proof_backoff']['reason'] == 'proof_resource_telemetry_unknown'


def test_profile_recovers_only_after_cooldown_and_two_healthy_samples(environment, monkeypatch):
    select(monkeypatch)
    clock = [1000.]
    monkeypatch.setattr(mod.time, 'time', lambda: clock[0])
    owner = mod.GlobalResourceScheduler(mod.default_resource_scheduler_config())
    environment[0] = replace(environment[0], memory_stall_percent=20)
    assert owner.try_acquire('snapshot_evaluation', memory_mb=512) is None
    environment[0] = replace(environment[0], memory_stall_percent=3)
    clock[0] += 1
    assert owner.try_acquire('snapshot_evaluation', memory_mb=512) is None
    clock[0] += 1
    assert owner.try_acquire('snapshot_evaluation', memory_mb=512) is None
    assert owner.snapshot()['proof_recovery']['healthy_samples'] == 1
    clock[0] += .25
    with owner.acquire('snapshot_evaluation', memory_mb=512, timeout=0):
        assert owner.snapshot()['proof_recovery']['grants_remaining'] == 0
        assert owner.try_acquire('snapshot_evaluation', memory_mb=512) is None
    clock[0] += .25
    with owner.acquire('snapshot_evaluation', memory_mb=512, timeout=0):
        pass


@pytest.mark.parametrize('requested,remaining,expected', [
    (None, 150, 90), (None, 17.5, 17.5), (0, 100, 0), (4, 100, 4),
    (100, 5, 5), (None, 0, 0),
])
def test_profile_wait_never_expands_explicit_or_enclosing_deadline(environment, monkeypatch, requested, remaining, expected):
    select(monkeypatch)
    assert codebase_admission_timeout(requested, remaining_seconds=remaining) == expected


@pytest.mark.parametrize('requested,remaining', [(True, 10), (-1, 10), (float('nan'), 10),
    ('1', 10), (None, -1), (None, float('inf')), (None, True)])
def test_invalid_admission_bound_rejected(environment, requested, remaining):
    with pytest.raises(mod.ResourceConfigurationError, match='finite and non-negative'):
        codebase_admission_timeout(requested, remaining_seconds=remaining)


def test_child_process_resolves_same_explicit_policy(environment, monkeypatch):
    import os
    import subprocess
    import sys
    select(monkeypatch)
    script = '''
import json
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import resource_scheduler as module
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.proof_resource_safety import ProofHostResources
module.collect_proof_host_resources = lambda: ProofHostResources(8, 8192, 8192)
config = module.default_resource_scheduler_config()
print(json.dumps(dict(profile=config.proof_resource_profile,
    threshold=config.proof_memory_stall_percent, recovery=config.proof_recovery_enabled,
    admission=module.default_proof_admission_timeout_seconds(), path=str(config.state_path))))
'''
    result = subprocess.run([sys.executable, '-c', script], env=dict(os.environ),
                            capture_output=True, text=True, check=True, timeout=20)
    assert json.loads(result.stdout) == dict(profile=mod.LOCAL_BENCHMARK_PROOF_PROFILE,
        threshold=10.0, recovery=True, admission=90.0, path=os.environ[mod.DEFAULT_STATE_ENV])


@pytest.mark.parametrize('change', [
    {'proof_memory_headroom_mb': 0}, {'proof_memory_stall_percent': 100},
    {'proof_cpu_stall_percent': 100}, {'proof_io_stall_percent': 100},
    {'proof_safety_enabled': False}, {'proof_recovery_enabled': False},
    {'proof_recovery_samples': 1}, {'proof_recovery_grants': 2},
    {'proof_memory_headroom_mb': None}, {'proof_memory_headroom_mb': True},
])
def test_profile_identity_cannot_label_weakened_policy(environment, monkeypatch, change):
    select(monkeypatch)
    config = mod.default_resource_scheduler_config()
    with pytest.raises(mod.ResourceConfigurationError, match='declared profile'):
        replace(config, **change).validate()
