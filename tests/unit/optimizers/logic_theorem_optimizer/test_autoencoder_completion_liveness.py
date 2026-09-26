"""Deterministic completion liveness with real local storage and synthetic workers.

No native training, network service or process benchmark runs here. Fake time
moves only while an actual filesystem preparation thread is held at a bounded
Event gate; registry transactions still execute on the invoking owner thread.
"""
from __future__ import annotations

from collections import Counter
from concurrent.futures import Future, wait as real_wait
from contextlib import contextmanager
import json
from pathlib import Path
import threading
import time

import pytest

from ipfs_datasets_py.duckdb_control.autoencoder_registry import AutoencoderRegistry
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_training_coordinator as coordinator
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_training_worker as worker
from tests.unit.optimizers.logic_theorem_optimizer.test_autoencoder_training_coordinator import (
    ImmediateExecutor, _prepare, _sparse_trainer,
)


class Scenario:
    LEASE_SECONDS = 0.6

    def __init__(self, registry, root, monkeypatch, now):
        self.registry, self.root, self.patch, self.now = registry, root, monkeypatch, now
        self.owner = threading.get_ident()
        self.initial_time = now[0]
        self.entered, self.release, self.unwound = (threading.Event() for _ in range(3))
        self.phase = 'replay'
        self.prep_failure = False
        self.tick = lambda: None
        self.ready_to_release = lambda: all(self.renewals[run] >= 2 for run in ('run-0', 'run-1'))
        self.renewals = Counter()
        self.renew_errors = []
        self.renew_arguments = []
        self.transactions = []
        self.preparations = []
        self.threads = set()
        self.active_preparations = self.peak_preparations = 0
        self.dispatched = []
        self.completions = []
        self.worker_shutdown = []
        self.waits = 0
        self.loss_mode = None
        self.lost_operation = None
        self.lookup_lost = False
        self.complete_hash_expiry = False
        self.inside_complete = False
        self.expired_during_complete = False
        self.install()

    def install(self):
        registry, patch = self.registry, self.patch
        original_transaction = registry._transaction

        @contextmanager
        def transaction():
            self.transactions.append(threading.get_ident())
            assert threading.get_ident() == self.owner, 'registry SQL moved into preparation thread'
            with original_transaction() as connection:
                yield connection

        patch.setattr(registry, '_transaction', transaction)
        original_prepare = coordinator._prepare_completion

        def prepare(*args, **kwargs):
            assert threading.get_ident() != self.owner
            self.threads.add(threading.current_thread())
            self.active_preparations += 1
            self.peak_preparations = max(self.peak_preparations, self.active_preparations)
            self.preparations.append(args[1].run_id)
            try:
                return original_prepare(*args, **kwargs)
            finally:
                self.active_preparations -= 1

        patch.setattr(coordinator, '_prepare_completion', prepare)
        original_replay = coordinator._verify_and_stage_patches

        def replay(registry, spec, receipt, policy):
            if spec.run_id == 'run-0' and self.phase == 'replay':
                self.block()
                if self.prep_failure:
                    raise ValueError('synthetic filesystem preparation failure')
            return original_replay(registry, spec, receipt, policy)

        patch.setattr(coordinator, '_verify_and_stage_patches', replay)
        original_stage = registry.stage_artifact

        def stage(path, *args, **kwargs):
            if self.phase == 'receipt-stage' and Path(path) == self.root / 'attempt-0' / 'receipt.json':
                self.block()
            return original_stage(path, *args, **kwargs)

        patch.setattr(registry, 'stage_artifact', stage)
        original_renew = registry.renew_lease

        def renew(*args, **kwargs):
            assert threading.get_ident() == self.owner
            self.renew_arguments.append(json.dumps([args, kwargs], sort_keys=True))
            try:
                receipt = original_renew(*args, **kwargs)
            except Exception:
                self.renew_errors.append(args[1]['run_id'])
                raise
            if self.entered.is_set() and not self.release.is_set():
                self.renewals[args[1]['run_id']] += 1
                if self.loss_mode in {'renew', 'renew-and-lookup'} and self.lost_operation is None:
                    self.lost_operation = args[0]
                    raise OSError('synthetic renewal response lost after commit')
            return receipt

        patch.setattr(registry, 'renew_lease', renew)
        original_resolve = registry.resolve_operation

        def resolve(operation_id, command, payload):
            assert threading.get_ident() == self.owner
            if self.loss_mode == 'renew-and-lookup' and operation_id == self.lost_operation and not self.lookup_lost:
                self.lookup_lost = True
                raise OSError('synthetic committed-operation lookup interruption')
            return original_resolve(operation_id, command, payload)

        patch.setattr(registry, 'resolve_operation', resolve)
        original_complete = registry.complete_run

        def complete(*args, **kwargs):
            assert threading.get_ident() == self.owner
            self.completions.append(json.dumps([args, kwargs], sort_keys=True))
            self.inside_complete = True
            try:
                receipt = original_complete(*args, **kwargs)
            finally:
                self.inside_complete = False
            if self.loss_mode == 'complete' and self.lost_operation is None:
                self.lost_operation = args[0]
                raise OSError('synthetic completion response lost after commit')
            return receipt

        patch.setattr(registry, 'complete_run', complete)
        original_verify = registry.verify_artifact

        def verify(artifact):
            result = original_verify(artifact)
            if self.complete_hash_expiry and self.inside_complete and not self.expired_during_complete:
                self.now[0] += self.LEASE_SECONDS + 0.1
                self.expired_during_complete = True
            return result

        patch.setattr(registry, 'verify_artifact', verify)

        def preparation_wait(futures, *, timeout):
            assert threading.get_ident() == self.owner
            if not self.release.is_set():
                assert self.entered.wait(5), 'filesystem preparation never entered its gate'
                self.waits += 1
                assert self.waits <= 50, 'owner stopped renewing while preparation was blocked'
                self.now[0] += 0.11
                assert self.dispatched == ['run-0', 'run-1'][:len(self.dispatched)], 'queued dispatch escaped active slot bound'
                self.tick()
                if self.ready_to_release():
                    self.release.set()
            return real_wait(futures, timeout=0.002)

        patch.setattr(coordinator, '_wait_for_preparation', preparation_wait)
        # Stable ordering makes run-0 the blocked completion even though the
        # standard wait API returns an unordered set of ready worker futures.
        def worker_wait(futures, *, timeout, return_when):
            done = sorted((future for future in futures if future.done()), key=lambda future: future.fixture_run_id)
            return done, {future for future in futures if not future.done()}

        patch.setattr(coordinator, 'wait', worker_wait)
        scenario = self

        class Executor(ImmediateExecutor):
            def submit(self, function, spec):
                scenario.dispatched.append(spec.run_id)
                future = super().submit(function, spec)
                future.fixture_run_id = spec.run_id
                return future

            def shutdown(self, **kwargs):
                # The owner must join filesystem work before closing its worker
                # executor or allowing the caller to close the registry.
                assert all(not thread.is_alive() for thread in scenario.threads)
                assert scenario.active_preparations == 0
                scenario.worker_shutdown.append(kwargs)

        self.executor = Executor

    def block(self):
        assert threading.get_ident() != self.owner
        self.entered.set()
        try:
            assert self.release.wait(5), 'owner failed to service the preparation gate'
        finally:
            self.unwound.set()

    def run(self, count=2):
        specs = [_prepare(self.registry, self.root, index,
            training_config={'max_seconds': 0.2},
            job_updates={'schema_version': 'autoencoder-training-job-v3',
                         'capture_sparse_patches': True, 'candidate_storage': 'sparse'})
            for index in range(count)]
        result = coordinator.run_training_jobs(self.registry, specs, max_workers=2,
            lease_seconds=self.LEASE_SECONDS, poll_seconds=0.01, clock=lambda: self.now[0],
            executor_factory=self.executor,
            worker_function=lambda spec: worker.execute_training_job(spec, trainer=_sparse_trainer))
        assert self.transactions and set(self.transactions) == {self.owner}
        assert self.worker_shutdown == [{'wait': True, 'cancel_futures': True}]
        assert self.active_preparations == 0
        assert all(not thread.is_alive() for thread in self.threads)
        assert not list(self.registry.artifact_root.glob('.compact-*'))
        assert not list(self.registry.artifact_root.glob('.stage-*'))
        for index, spec in enumerate(specs):
            assert self.registry.resolve_head(f'english-{index}', 'best')['version_id'] == spec.base_version_id
        assert result['execution_mode'] == 'injected_test'
        assert result['admitted'] is result['promotion_performed'] is False
        return result, specs


@pytest.fixture
def scenario(tmp_path, monkeypatch):
    now = [1_800_000_000.0]
    with AutoencoderRegistry(tmp_path / 'registry.duckdb', tmp_path / 'artifacts', clock=lambda: now[0]) as registry:
        value = Scenario(registry, tmp_path, monkeypatch, now)
        try:
            yield value
        finally:
            value.release.set()


@pytest.mark.parametrize('phase', ['replay', 'receipt-stage'])
def test_blocked_filesystem_work_renews_current_and_other_done_workers_without_extra_dispatch(scenario, phase):
    scenario.phase = phase
    result, _ = scenario.run(count=3)
    assert not result['failed'], result
    assert len(result['completed']) == 3
    assert scenario.now[0] - scenario.initial_time > scenario.LEASE_SECONDS
    assert scenario.renewals['run-0'] >= 2 and scenario.renewals['run-1'] >= 2
    assert scenario.preparations == ['run-0', 'run-1', 'run-2']
    assert scenario.peak_preparations == len(scenario.threads) == 1
    assert scenario.unwound.is_set()


def test_preparation_heartbeats_cover_another_still_running_worker_future(scenario):
    ready_executor = scenario.executor
    pending = Future()
    delayed = []
    pending_started = []
    observed_pending_renewals = Counter()
    completed_after_renewal = []

    class PendingWorkerExecutor(ready_executor):
        def submit(self, function, spec):
            if spec.run_id != 'run-1':
                return super().submit(function, spec)
            scenario.dispatched.append(spec.run_id)
            pending.fixture_run_id = spec.run_id
            assert pending.set_running_or_notify_cancel()
            pending_started.append(time.monotonic())
            delayed.append((function, spec))
            return pending

    scenario.executor = PendingWorkerExecutor
    original_worker_wait = coordinator.wait

    def bounded_worker_wait(futures, **kwargs):
        if pending.running():
            failed_other = any(future is not pending and future.done() and future.exception() is not None
                               for future in futures)
            if failed_other or time.monotonic() - pending_started[0] >= 5:
                # A source guard or broken preparation must not leave this
                # deliberately unexecuted fixture Future running forever.
                pending.set_exception(RuntimeError('pending fixture stopped after preceding failure or five-second deadline'))
        return original_worker_wait(futures, **kwargs)

    scenario.patch.setattr(coordinator, 'wait', bounded_worker_wait)
    original_renew = scenario.registry.renew_lease

    def renew(*args, **kwargs):
        if scenario.entered.is_set() and pending.running():
            observed_pending_renewals[args[1]['run_id']] += 1
        return original_renew(*args, **kwargs)

    scenario.patch.setattr(scenario.registry, 'renew_lease', renew)

    def complete_pending_after_heartbeats():
        if pending.done() or not all(observed_pending_renewals[run] >= 2 for run in ('run-0', 'run-1')):
            return
        assert pending.running() and not scenario.release.is_set()
        assert scenario.preparations == ['run-0']
        function, spec = delayed.pop()
        # Execute the existing synthetic worker only after proving its live
        # Future was covered by the completion-preparation heartbeat pump.
        pending.set_result(function(spec))
        completed_after_renewal.append(dict(observed_pending_renewals))

    scenario.tick = complete_pending_after_heartbeats
    scenario.ready_to_release = lambda: pending.done()
    result, _ = scenario.run()
    assert not result['failed'], result
    assert {row['run_id'] for row in result['completed']} == {'run-0', 'run-1'}
    assert completed_after_renewal == [{'run-0': 2, 'run-1': 2}]
    assert pending.done() and not pending.cancelled()
    assert scenario.preparations == ['run-0', 'run-1']
    assert scenario.peak_preparations == 1 and scenario.unwound.is_set()


@pytest.mark.parametrize('fenced', ['run-0', 'run-1'])
def test_fenced_current_or_other_run_is_quarantined_while_survivor_keeps_renewing(scenario, fenced):
    replacements = []
    survivor = 'run-1' if fenced == 'run-0' else 'run-0'

    def replace():
        if replacements:
            return
        registry = scenario.registry
        old = registry.get_run(fenced)['lease']
        # Real owner transitions invalidate exactly one lease without moving
        # the fake clock past the other run's expiry or editing registry rows.
        registry.fail_run('fixture-displace', old, {'admitted': False, 'synthetic_fixture': True})
        replacement = registry.claim_run('fixture-reassign', fenced, 'replacement-fixture', 10)['lease']
        assert replacement['attempt'] > old['attempt'] and replacement['fence'] > old['fence']
        replacements.append(replacement)

    scenario.tick = replace
    scenario.ready_to_release = lambda: fenced in scenario.renew_errors and scenario.renewals[survivor] >= 2
    result, _ = scenario.run()
    assert [row['run_id'] for row in result['completed']] == [survivor]
    assert [row['run_id'] for row in result['failed']] == [fenced]
    assert result['failed'][0]['failure_recorded'] is False
    current = scenario.registry.get_run(fenced)
    assert current['status'] == 'running' and current['lease'] == replacements[0]
    assert len(scenario.completions) == 1
    assert json.loads(scenario.completions[0])[0][1]['run_id'] == survivor
    assert scenario.renewals[survivor] >= 2 and scenario.unwound.is_set()
    if fenced == 'run-1':
        assert scenario.preparations == ['run-0']
    else:
        assert scenario.preparations == ['run-0', 'run-1']


def test_preparation_exception_does_not_stop_other_completion_and_closes_pool(scenario):
    scenario.prep_failure = True
    result, _ = scenario.run()
    assert [row['run_id'] for row in result['completed']] == ['run-1']
    assert [row['run_id'] for row in result['failed']] == ['run-0']
    assert result['failed'][0]['failure_recorded'] is True
    assert 'synthetic filesystem preparation failure' in result['failed'][0]['error']
    assert scenario.registry.get_run('run-0')['status'] == 'failed'
    assert scenario.registry.get_run('run-1')['status'] == 'completed'
    assert scenario.unwound.is_set() and scenario.peak_preparations == 1


@pytest.mark.parametrize('loss_mode', ['renew', 'renew-and-lookup', 'complete'])
def test_lost_responses_resolve_exact_owner_operations_after_blocked_preparation(scenario, loss_mode):
    scenario.loss_mode = loss_mode
    result, _ = scenario.run()
    assert not result['failed'], result
    assert len(result['completed']) == 2
    assert scenario.lost_operation is not None
    if loss_mode == 'renew-and-lookup':
        repeated = [raw for raw in scenario.renew_arguments if json.loads(raw)[0][0] == scenario.lost_operation]
        assert len(repeated) == 2 and repeated[0] == repeated[1]
        assert result['mutation_retry_count'] == 1
        assert scenario.lookup_lost is True
    else:
        assert result['resolved_operation_count'] == 1
    assert scenario.renewals['run-0'] >= 2 and scenario.renewals['run-1'] >= 2
    with scenario.registry._transaction() as connection:
        assert connection.execute("SELECT count(*) FROM autoencoder_control.events WHERE kind='candidate_durable'").fetchone()[0] == 2


def test_final_synchronous_complete_run_hash_expiry_still_rejects_completion(scenario):
    # Async preparation does not change CompleteRun's final synchronous rehash
    # or authorize a stale lease. This is a residual latency bound, not a bypass.
    scenario.ready_to_release = lambda: scenario.renewals['run-0'] >= 2
    scenario.complete_hash_expiry = True
    result, _ = scenario.run(count=1)
    assert scenario.expired_during_complete is True
    assert not result['completed']
    assert len(result['failed']) == 1 and result['failed'][0]['failure_recorded'] is False
    assert 'stale, expired or invalid lease' in result['failed'][0]['error']
    assert scenario.registry.get_run('run-0')['status'] == 'running'
    with scenario.registry._transaction() as connection:
        assert connection.execute("SELECT count(*) FROM autoencoder_control.events WHERE kind='candidate_durable'").fetchone()[0] == 0
