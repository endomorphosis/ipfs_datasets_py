"""Exercise the real isolated process/monitor boundary without model training."""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import signal
import sys
import time

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_daemon_resources import (
    _group_usage, _process,
)

ROOT = Path(__file__).resolve().parents[4]


@pytest.fixture
def cli():
    spec = importlib.util.spec_from_file_location(
        'ui_resource_cli', ROOT/'scripts/ops/ui_ux_ir/run_ui_feature_training.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ObservedReservation:
    """Read real /proc group accounting, with an optional injected limit error."""
    def __init__(self, reject_when=None):
        self.child = None
        self.observations = []
        self.reject_when = reject_when

    def check_usage(self, state, child_pid=None):
        if child_pid is not None:
            process = _process(child_pid)
            assert process['parent_pid'] == os.getpid()
            assert process['group_pid'] == child_pid
            self.child = {'pid': child_pid, 'birth': process['birth']}
        group = _group_usage(self.child)
        self.observations.append(group)
        if self.reject_when is not None and self.reject_when():
            raise RuntimeError('injected resource limit')
        return {'group_rss': group}


def test_owned_child_is_attached_and_real_rss_is_measured(cli, tmp_path):
    reservation = ObservedReservation()
    receipt = cli._supervise_owned_worker(
        [sys.executable, '-c', 'import time; allocation=bytearray(4000000); time.sleep(.7)'],
        state=tmp_path, reservation=reservation, log_path=tmp_path/'worker.log',
        wall_seconds=10, environment=dict(os.environ))
    assert receipt['isolated_process_group'] is True
    assert receipt['observed_peak_group_rss_bytes'] > 4_000_000
    assert receipt['observed_peak_group_processes'] == 1
    assert receipt['resource_checks'] >= 3
    assert _group_usage(reservation.child)['live_processes'] == 0


def test_deadline_stops_owned_group(cli, tmp_path):
    reservation = ObservedReservation()
    with pytest.raises(TimeoutError, match='wall deadline'):
        cli._supervise_owned_worker(
            [sys.executable, '-c', 'import time; time.sleep(60)'], state=tmp_path,
            reservation=reservation, log_path=tmp_path/'worker.log', wall_seconds=.2,
            environment=dict(os.environ))
    assert _group_usage(reservation.child)['live_processes'] == 0


def test_failed_limit_stops_descendants_even_if_leader_exits(cli, tmp_path):
    ready = tmp_path/'descendant.pid'
    descendant = 'import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); time.sleep(60)'
    worker = (
        'import subprocess,sys,time,pathlib; '
        f'p=subprocess.Popen([sys.executable,"-c",{descendant!r}]); '
        f'pathlib.Path({str(ready)!r}).write_text(str(p.pid)); '
        'time.sleep(60)'
    )
    reservation = ObservedReservation(reject_when=ready.exists)
    with pytest.raises(RuntimeError, match='injected resource limit'):
        cli._supervise_owned_worker(
            [sys.executable, '-c', worker], state=tmp_path, reservation=reservation,
            log_path=tmp_path/'worker.log', wall_seconds=10, environment=dict(os.environ))
    # A killed orphan may be a zombie until its new parent reaps it; it is not
    # live and cannot keep consuming memory or escape the group reservation.
    assert _group_usage(reservation.child)['live_processes'] == 0


def test_start_gate_prevents_work_until_resource_attachment(cli, tmp_path):
    marker = tmp_path/'started'
    read_fd, write_fd = os.pipe()
    class GateReservation(ObservedReservation):
        def check_usage(self, state, child_pid=None):
            if child_pid is not None:
                assert not marker.exists()
            return super().check_usage(state, child_pid)
    reservation = GateReservation()
    try:
        cli._supervise_owned_worker(
            [sys.executable, '-c',
             f'import os,pathlib,time; assert os.read({read_fd},1)==b"1"; '
             f'pathlib.Path({str(marker)!r}).write_text("started"); time.sleep(.1)'],
            state=tmp_path, reservation=reservation, log_path=tmp_path/'worker.log',
            wall_seconds=10, environment=dict(os.environ), gate_fd=(read_fd, write_fd))
    finally:
        os.close(read_fd)
        os.close(write_fd)
    assert marker.read_text() == 'started'


def test_cleanup_refuses_a_reused_pid(cli, monkeypatch):
    calls = []
    monkeypatch.setattr(cli, '_process_birth', lambda pid: 'new-birth')
    monkeypatch.setattr(os, 'killpg', lambda *args: calls.append(args))
    class Process:
        pid = 123
    with pytest.raises(RuntimeError, match='reused'):
        cli._stop_owned_group(Process(), 'original-birth')
    assert not calls


def test_watchdog_observes_short_allocation_during_slow_disk_census(cli, tmp_path):
    class SlowCensus(ObservedReservation):
        def check_usage(self, state, child_pid=None):
            if child_pid is None:
                time.sleep(1)
            return super().check_usage(state, child_pid)
    reservation = SlowCensus()
    receipt = cli._supervise_owned_worker(
        [sys.executable, '-c',
         'import time; time.sleep(.15); allocation=bytearray(80000000); time.sleep(.4)'],
        state=tmp_path, reservation=reservation, log_path=tmp_path/'worker.log',
        wall_seconds=10, environment=dict(os.environ))
    assert max(row['rss_bytes'] for row in reservation.observations) < 80_000_000
    assert receipt['observed_peak_group_rss_bytes'] > 80_000_000
    assert receipt['watchdog_samples'] >= 5
    assert receipt['watchdog_interval_seconds'] == .05


@pytest.mark.parametrize('kind', ['memory', 'deadline'])
def test_watchdog_enforces_limits_while_owner_blocks_in_census(cli, tmp_path, kind):
    class SlowCensus(ObservedReservation):
        stopped_while_census_blocked = False
        def check_usage(self, state, child_pid=None):
            if child_pid is None:
                time.sleep(.9)
                self.stopped_while_census_blocked = not _group_usage(self.child)['live_processes']
            return super().check_usage(state, child_pid)
    reservation = SlowCensus()
    code = ('import time; time.sleep(.1); allocation=bytearray(80000000); time.sleep(60)'
            if kind == 'memory' else 'import time; time.sleep(60)')
    with pytest.raises(MemoryError if kind == 'memory' else TimeoutError):
        cli._supervise_owned_worker(
            [sys.executable, '-c', code], state=tmp_path, reservation=reservation,
            log_path=tmp_path/'worker.log', wall_seconds=10 if kind == 'memory' else .2,
            environment=dict(os.environ), memory_mb=32 if kind == 'memory' else 4096)
    assert reservation.stopped_while_census_blocked
    assert _group_usage(reservation.child)['live_processes'] == 0
