"""Bounded guardian for the frozen-donor learned-trigger readout pilot.

``--check`` validates an exact historical resource closure and the existing
shared configuration without constructing a client or acquiring a reservation.
Execution additionally needs a clean, hash-bound independent review. Training
artifacts live inside the existing disk ledger's test-log root. This guardian
does not grant semantic, legal-label, or proof authority.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import signal
import stat
import subprocess
import sys
import threading
import time

PACKAGE = Path('/home/barberb/lift_coding/external/ipfs_datasets')
SOURCE = PACKAGE / 'workspace/test-logs/ui-modal-coverage-20261002/validation-source-r2'
HELPERS = PACKAGE / 'workspace/test-logs/decoder-normative-wording-r2-20261006'
OWNER = PACKAGE / 'workspace/test-logs/native4096-four-width-20261004/resource-cap/autoencoder_daemon_resources.py'
RUN_ROOT = PACKAGE / 'workspace/test-logs/legal-trigger-readout-pilot-20261007-01'
LEDGER = PACKAGE / 'workspace/test-logs/federal-corpus-audits/owned-daemon-resource-control/disk-reservations.json'
ROOTS = (PACKAGE / 'workspace/test-logs', PACKAGE / 'workspace/todo-queues',
         PACKAGE / 'docs/implementation/reports/evidence', Path('/tmp/pytest-of-barberb'))
RESOURCES = dict(cpu_slots=2, memory_mb=1536, child_process_slots=1,
                 storage_bytes=200_000_000, child_deadline_seconds=300,
                 admission_timeout_seconds=120, ledger_lock_timeout_seconds=60)
PREFIX = 'ipfs_datasets_py/optimizers/logic_theorem_optimizer/'
CLOSURE = {
    SOURCE / 'ipfs_datasets_py/__init__.py': 'f258f8eada774251feacd8e2ee2048efe56c89a8ee88efd50e4271ea41d43dc9',
    SOURCE / 'ipfs_datasets_py/optimizers/__init__.py': 'a12bab3724da07be67b447719ace42fc1f480cb5635581f320a99a372f02f450',
    SOURCE / PREFIX / '__init__.py': '9d693fa576f00dc36899faad75ef3044c437e2bfec5c62306f7031236725bb0e',
    SOURCE / PREFIX / 'resource_scheduler.py': 'a418e84f70ed8509ba0518feea69e7a8c27865139f83b6c81349eefdfd5893a4',
    SOURCE / PREFIX / 'proof_resource_safety.py': '23569b40b44d9130c30c62be564d58908a509fb1f40c6377e89f2fc1e3c799c5',
    SOURCE / PREFIX / 'runtime_telemetry.py': '542f705867b93fcb138a117e1f5c97a144ad6635dc92c37bc5034eee5065ef63',
    OWNER: 'b00d2752ba852fe73760bba4fbd51b0e845742c3527642606a2a77ed9f8f5e2c',
    HELPERS / 'adopt_shared_scheduler.py': '4956baa1e41abe53fc83a2d4ae7709b3be13ebc1c775b44571a33903b8f70b1f',
    HELPERS / 'lazy_scheduler_adoption.py': '42f31d8da1eb5b44274ca0b8c8180cd78bc083dfd0e93438e61f38223929d84a',
    HELPERS / 'owned_lease_watchdog.py': 'f1b9f71e375cf5ed4004e023bbef2d6f7f61e1ecb588078a1094d7b1982609b3',
}


def require(value, message):
    if not value:
        raise ValueError(message)


def pin(path):
    path = Path(path)
    info = path.lstat()
    require(stat.S_ISREG(info.st_mode) and not path.is_symlink(), 'regular artifact required: ' + str(path))
    digest = hashlib.sha256()
    size = 0
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1_048_576), b''):
            digest.update(block)
            size += len(block)
    return dict(path=str(path.resolve()), sha256=digest.hexdigest(), bytes=size)


def unique(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, 'duplicate JSON key')
        result[key] = value
    return result


def reject_constant(value):
    raise ValueError('nonfinite JSON value: ' + value)


def read_json(path, max_bytes=16 * 1024 * 1024):
    require(pin(path)['bytes'] <= max_bytes, 'bounded JSON required')
    return json.loads(Path(path).read_bytes(), object_pairs_hook=unique, parse_constant=reject_constant)


def write(path, value, *, replace=False):
    path = Path(path)
    with path.open('w' if replace else 'x') as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())


def sync_tree(root):
    paths = list(Path(root).rglob('*'))
    for path in paths:
        require(not path.is_symlink(), 'symlink in owned output refused')
        if path.is_file():
            with path.open('rb') as stream:
                os.fsync(stream.fileno())
    directories = [Path(root)] + [p for p in paths if p.is_dir()]
    for path in sorted(directories, key=lambda p: len(p.parts), reverse=True):
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class GroupRSSSamplerError(RuntimeError):
    """An owned-group observation failed or exceeded its admitted envelope."""


class OwnedGroupRSSSampler:
    """Cheap sampled process-group RSS, independent of global disk accounting.

    The pinned owner validates the recorded leader birth before inspecting its
    process group. No scheduler client, lease, census, or foreign claim is read
    or changed here. A sampled peak is not an absolute peak or kernel quota.
    """
    def __init__(self, resources, identity, *, events_path, memory_limit_bytes,
                 safe_exception, poll_seconds=1.0, signal_group=None):
        require(type(identity) is dict and set(identity) == {'pid', 'birth'}
                and type(identity['pid']) is int and identity['pid'] > 1
                and type(identity['birth']) is str and identity['birth'], 'exact owned child identity required')
        require(type(memory_limit_bytes) is int and memory_limit_bytes > 0, 'positive RSS envelope required')
        require(type(poll_seconds) in (int, float) and math.isfinite(poll_seconds)
                and 0 < poll_seconds <= 1.0, 'RSS polling must be finite and at most one second')
        self.resources, self.identity = resources, dict(identity)
        self.memory_limit_bytes, self.poll_seconds = memory_limit_bytes, float(poll_seconds)
        self.safe_exception = safe_exception
        self.signal_group = signal_group or os.killpg
        self.events_path = Path(events_path)
        self._fd = os.open(self.events_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        self._mutex, self._io, self._sampling = threading.RLock(), threading.Lock(), threading.Lock()
        self._stop = threading.Event()
        self._thread, self._failure, self._last_observed = None, None, None
        self._phase, self._closed, self._signalled = 'gated', False, False
        self._counts = dict(gated=0, model=0, post_model=0)
        self._peaks = dict(gated=0, model=0, post_model=0)
        self._gaps = dict(gated=0.0, model=0.0, post_model=0.0)
        self._first = dict(gated=None, model=None, post_model=None)
        self._last = dict(gated=None, model=None, post_model=None)
        self._started_at = time.monotonic()
        self._model_started_at, self._model_stopped_at = None, None

    def _record(self, value):
        raw = canonical_json(value) + b'\n'
        with self._io:
            require(not self._closed, 'RSS observation log closed')
            offset = 0
            while offset < len(raw):
                written = os.write(self._fd, raw[offset:])
                require(written > 0, 'RSS observation write stalled')
                offset += written
            os.fsync(self._fd)

    def _interrupt_owned_group(self):
        with self._mutex:
            if self._signalled:
                return
            try:
                usage = self.resources._group_usage(self.identity)
                require(usage.get('available') is True and type(usage.get('live_processes')) is int,
                        'owned group availability required before RSS interrupt')
                if usage['live_processes']:
                    # Revalidate birth/group immediately before signalling.
                    again = self.resources._group_usage(self.identity)
                    require(again.get('available') is True and type(again.get('live_processes')) is int,
                            'owned group availability required before RSS interrupt')
                    if again['live_processes']:
                        self.signal_group(self.identity['pid'], signal.SIGINT)
                        self._signalled = True
                        self._failure['owned_group_interrupt'] = 'SIGINT_sent'
            except ProcessLookupError:
                self._failure['owned_group_interrupt'] = 'group_already_exited'
            except BaseException as error:
                self._failure['owned_group_interrupt'] = 'refused_or_failed'
                self._failure['interrupt_error'] = self.safe_exception(error)

    def _fail(self, error, observation=None):
        with self._mutex:
            if self._failure is not None:
                return
            self._failure = dict(schema='guardian-owned-group-rss-failure/v1',
                error=self.safe_exception(error), observation=observation,
                identity=dict(self.identity), memory_limit_bytes=self.memory_limit_bytes,
                sampled_only=True, kernel_hard_cap=False, scheduler_or_claim_mutation=False)
        self._stop.set()
        self._interrupt_owned_group()
        try:
            self._record(self._failure)
        except BaseException as evidence_error:
            with self._mutex:
                self._failure['evidence_write_error'] = self.safe_exception(evidence_error)

    def sample(self, stage):
        # Explicit phase-edge samples and the independent poller share one
        # collection lock so observation gaps remain chronological.
        with self._sampling:
            return self._sample(stage)

    def _sample(self, stage):
        self.assert_healthy()
        observed = time.monotonic()
        with self._mutex:
            phase = self._phase
        event = None
        try:
            usage = self.resources._group_usage(self.identity)
            require(type(usage) is dict and usage.get('available') is True
                    and type(usage.get('rss_bytes')) is int and usage['rss_bytes'] >= 0
                    and type(usage.get('live_processes')) is int and usage['live_processes'] >= 0,
                    'available finite owned-group RSS required')
            with self._mutex:
                gap = None if self._last_observed is None else observed - self._last_observed
                event = dict(schema='guardian-owned-group-rss-observation/v1',
                    stage=stage, phase=phase, identity=dict(self.identity), observed_at_unix=time.time(),
                    observed_at_monotonic=observed, observation_gap_seconds=gap,
                    sample_elapsed_seconds=time.monotonic() - observed,
                    phase_changed_during_sample=phase != self._phase,
                    group_rss_bytes=usage['rss_bytes'], live_group_processes=usage['live_processes'],
                    memory_limit_bytes=self.memory_limit_bytes, sampled_only=True, kernel_hard_cap=False,
                    scheduler_or_claim_mutation=False)
                self._counts[phase] += 1
                self._peaks[phase] = max(self._peaks[phase], usage['rss_bytes'])
                if gap is not None:
                    self._gaps[phase] = max(self._gaps[phase], gap)
                if self._first[phase] is None:
                    self._first[phase] = observed
                self._last[phase], self._last_observed = observed, observed
                require(sum(self._counts.values()) <= 1024, 'RSS observation count bound exceeded')
            self._record(event)
            require(usage['rss_bytes'] <= self.memory_limit_bytes, 'observed owned-group RSS exceeded envelope')
            return event
        except BaseException as error:
            self._fail(error, event)
            raise GroupRSSSamplerError('owned group RSS observation failed') from None

    def _loop(self):
        while not self._stop.wait(self.poll_seconds):
            try:
                self.sample('poll')
            except GroupRSSSamplerError:
                return

    def start(self):
        require(self._thread is None, 'one RSS monitor start required')
        self.sample('gated_start')
        self._thread = threading.Thread(target=self._loop, name='owned-group-rss-sampler', daemon=True)
        self._thread.start()

    def mark_model_started(self):
        with self._mutex:
            require(self._model_started_at is None, 'one model phase start required')
            self._model_started_at, self._phase = time.monotonic(), 'model'
        self.sample('model_gate_permitted')

    def mark_model_stopped(self):
        with self._mutex:
            if self._model_started_at is not None and self._model_stopped_at is None:
                self._model_stopped_at = time.monotonic()
            self._phase = 'post_model'
        self.sample('model_leader_reaped')

    def assert_healthy(self):
        with self._mutex:
            if self._failure is not None:
                raise GroupRSSSamplerError('owned group RSS observation failed')

    def stop(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=3.0)
            require(not self._thread.is_alive(), 'RSS monitor thread did not stop')

    def snapshot(self):
        with self._mutex:
            return dict(schema='guardian-owned-group-rss-summary/v1', identity=dict(self.identity),
                poll_seconds=self.poll_seconds, memory_limit_bytes=self.memory_limit_bytes,
                model_phase_sample_count=self._counts['model'],
                sampled_model_phase_peak_rss_bytes=self._peaks['model'] if self._counts['model'] else None,
                sample_counts_by_phase=dict(self._counts), sampled_peaks_by_phase=dict(self._peaks),
                max_observation_gap_seconds_by_phase=dict(self._gaps),
                first_observation_monotonic_by_phase=dict(self._first),
                last_observation_monotonic_by_phase=dict(self._last),
                sampler_started_at_monotonic=self._started_at,
                model_gate_permitted_at_monotonic=self._model_started_at,
                model_leader_reaped_at_monotonic=self._model_stopped_at,
                model_phase_wall_seconds=None if self._model_started_at is None or self._model_stopped_at is None
                    else self._model_stopped_at - self._model_started_at,
                failure=self._failure, sampled_peak_only=True, absolute_peak_measured=False,
                kernel_hard_cap=False, continuous_coverage_claimed=False,
                timing_scope='model gate permission through leader reap; includes model import and guardian polling, not isolated fit time',
                scheduler_or_claim_mutation=False)

    def close(self):
        self.stop()
        with self._io:
            if not self._closed:
                os.close(self._fd)
                self._closed = True


def canonical_json(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def closure_and_configuration():
    """No scheduler client, lock creation, reservation, or model execution."""
    require(not any(name == 'ipfs_datasets_py' or name.startswith('ipfs_datasets_py.')
                    for name in sys.modules), 'fresh guardian process required')
    producers = {}
    for path, expected in CLOSURE.items():
        record = pin(path)
        require(record['sha256'] == expected, 'historical resource closure changed: ' + str(path))
        producers[str(path)] = record
    sys.path.insert(0, str(SOURCE))
    import ipfs_datasets_py.optimizers.logic_theorem_optimizer as package
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import resource_scheduler as scheduler
    require(Path(scheduler.__file__).resolve() == SOURCE / PREFIX / 'resource_scheduler.py',
            'resource scheduler imported from wrong tree')
    owner = load_module(package.__name__ + '.autoencoder_daemon_resources', OWNER)
    setattr(package, 'autoencoder_daemon_resources', owner)
    adoption = load_module('scope_pilot_adoption', HELPERS / 'adopt_shared_scheduler.py')
    lazy = load_module('scope_pilot_lazy_adoption', HELPERS / 'lazy_scheduler_adoption.py')
    watch = load_module('scope_pilot_owned_watchdog', HELPERS / 'owned_lease_watchdog.py')
    path = scheduler.default_scheduler_state_path()
    state, observation = adoption.read_existing(path)
    config = adoption.validated_config(scheduler, state, path)
    require(config.total_cpu_slots >= RESOURCES['cpu_slots']
            and config.total_memory_mb >= RESOURCES['memory_mb']
            and config.total_child_process_slots >= 1, 'requested envelope cannot fit existing capacities')
    ledger = read_json(LEDGER, max_bytes=8 * 1024 * 1024)
    require(ledger['schema'] == owner.SCHEMA and ledger['limit_bytes'] == owner.MAX_STORAGE_BYTES,
            'existing disk ledger schema or authorized cap differs')
    require([r['path'] for r in ledger['roots']] == [str(root) for root in ROOTS],
            'existing disk ledger roots differ')
    report = dict(schema='scope-pilot-resource-compatibility/v1', passed=True, findings=[],
                  source_closure='authenticated historical resource owner and scheduler; model child uses isolated current candidate',
                  producers=producers, shared_state=observation, shared_config=config.persisted_dict(),
                  lease_count=len(state['leases']), waiter_count=len(state['waiters']),
                  disk_ledger=pin(LEDGER), disk_limit_bytes=ledger['limit_bytes'],
                  outstanding_full_reservations_bytes=sum(r['storage_bytes'] for r in ledger['reservations'].values()
                                                         if r['status'] != 'released'),
                  physical_run_root=str(RUN_ROOT), resources=RESOURCES,
                  model_started=False, reservation_acquired=False, scheduler_client_constructed=False,
                  shared_state_modified=False, continuous_lease_coverage_claimed=False,
                  admission_guaranteed=False)
    return owner, scheduler, adoption, lazy, watch, report


def validate_review(args):
    plan, runner, candidate = args.plan.resolve(), args.runner.resolve(), args.package_root.resolve()
    require(plan.is_file() and runner.is_file() and candidate.is_dir(), 'existing plan, runner and candidate required')
    require((candidate / 'ipfs_datasets_py').is_dir(), 'candidate package directory required')
    review = read_json(args.review)
    require(review.get('passed') is True and review.get('findings') == [], 'clean independent review required')
    require(review.get('phase') == 'training' and review.get('package_root') == str(candidate)
            and review.get('run_root') == str(RUN_ROOT), 'review phase or physical/candidate root differs')
    for field, path in [('plan_sha256', plan), ('runner_sha256', runner),
                        ('guardian_sha256', Path(__file__).resolve())]:
        require(review.get(field) == pin(path)['sha256'], 'review binding differs: ' + field)
    records = review.get('artifacts')
    require(type(records) is dict and records, 'complete independent artifact bindings required')
    for path, expected in records.items():
        require(Path(path).is_absolute() and type(expected) is dict
                and type(expected.get('sha256')) is str and type(expected.get('bytes')) is int,
                'absolute artifact hash and byte count required')
        actual = pin(path)
        require(actual['sha256'] == expected['sha256'] and actual['bytes'] == expected['bytes'],
                'reviewed artifact changed: ' + path)
    require(all(str(p) in records for p in (plan, runner, Path(__file__).resolve())),
            'plan, runner and guardian must be in complete review artifact bindings')
    require(pin(args.review)['bytes'] <= 16 * 1024 * 1024, 'review byte bound')
    read_json(plan)
    return plan, runner, candidate, review


def cleanup(child, identity, resources):
    if child is None:
        return dict(child_created=False, leader_reaped=True, live_group_processes=0)
    require(type(identity) is dict and set(identity) == {'pid', 'birth'} and identity['pid'] == child.pid,
            'captured isolated child identity required for cleanup')
    events = []
    for sig, seconds in ((signal.SIGINT, 10), (signal.SIGKILL, 5)):
        usage = resources._group_usage(identity)
        if not usage['live_processes']:
            break
        try:
            os.killpg(identity['pid'], sig)
            events.append(dict(signal=signal.Signals(sig).name, observed_live_processes=usage['live_processes']))
        except ProcessLookupError:
            pass
        deadline = time.monotonic() + seconds
        while resources._group_usage(identity)['live_processes'] and time.monotonic() < deadline:
            child.poll()
            time.sleep(.05)
    require(resources._group_usage(identity)['live_processes'] == 0, 'owned descendants remain alive')
    code = child.wait(timeout=5)
    return dict(child_created=True, identity=identity, signals=events, leader_reaped=True,
                leader_returncode=code, live_group_processes=0)


def execute(args):
    plan, runner, candidate, review = validate_review(args)
    require(Path(args.attempt).name == args.attempt and args.attempt not in ('', '.', '..'),
            'fresh single-component attempt required')
    attempt = RUN_ROOT / args.attempt
    require(not attempt.exists(), 'completed attempt is immutable')
    require(not RUN_ROOT.is_symlink(), 'physical run root may not be symlink')
    resources, scheduler, adoption, lazy, watch, compatible = closure_and_configuration()
    # All guards above complete before creating the attempt or any reservation.
    RUN_ROOT.mkdir(exist_ok=True)
    attempt.mkdir()
    write(attempt / 'pre-admission.json', dict(compatibility=compatible, plan=pin(plan), runner=pin(runner),
                                             guardian=pin(Path(__file__)), review=pin(args.review)))
    completed_adoption = lazy.install(resources, adoption.adopt_for_owner, source_root=SOURCE,
                                      receipt_path=attempt / 'scheduler-adoption.json')
    owner = resources.DaemonResourceReservation(LEDGER, roots=ROOTS,
        storage_bytes=RESOURCES['storage_bytes'], memory_mb=RESOURCES['memory_mb'],
        cpu_slots=RESOURCES['cpu_slots'], child_process_slots=1,
        timeout_seconds=RESOURCES['admission_timeout_seconds'],
        ledger_lock_timeout_seconds=RESOURCES['ledger_lock_timeout_seconds'])
    command = [sys.executable, str(runner), '--plan', str(plan), '--output', str(attempt / 'results')]
    env = dict(os.environ, PYTHONPATH=str(candidate), PYTHONDONTWRITEBYTECODE='1',
        HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', HF_DATASETS_OFFLINE='1',
        IPFS_DATASETS_PY_LAZY_INSTALL_ERGOAI='0', IPFS_DATASETS_LEGAL_IR_METRIC_DISK_CACHE='0',
        CUDA_VISIBLE_DEVICES='', OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1')
    child = identity = watchdog = rss_sampler = None
    launch_gate = None
    model_started = False
    primary = cleanup_receipt = None
    previous_alarm = signal.getsignal(signal.SIGALRM)

    def child_alarm(_signum, _frame):
        raise TimeoutError('owned child exceeded five-minute deadline')

    started = time.monotonic()
    try:
        with owner:
            try:
                adopted = completed_adoption()
                binding = watch.capture_lease_binding(owner, adopted, resources)
                watchdog = watch.OwnedLeaseWatchdog(binding, resources=resources,
                    events_path=attempt / 'lease-observations.jsonl')
                watchdog.observe('pre_spawn')
                write(attempt / 'lease-binding.json', binding.public())
                write(attempt / 'command.json', dict(argv=command, cwd=str(candidate), resources=RESOURCES,
                                                    candidate_pythonpath=str(candidate), no_cuda=True,
                                                    no_proof_workers=True, model_authority=False,
                                                    startup_gate='owned Python leader waits for custody and watchdog before exec'))
                with (attempt / 'child.log').open('x') as log:
                    read_gate, launch_gate = os.pipe()
                    gate_code = ('import os,sys;fd=int(sys.argv[1]);permit=os.read(fd,1);os.close(fd);'
                                 'sys.exit(125) if permit!=b"1" else os.execv(sys.argv[2],sys.argv[2:])')
                    try:
                        child = subprocess.Popen([sys.executable, '-c', gate_code, str(read_gate), *command],
                            cwd=candidate, env=env, stdout=log, stderr=subprocess.STDOUT,
                            start_new_session=True, pass_fds=(read_gate,))
                    finally:
                        os.close(read_gate)
                    child_started = time.monotonic()
                    signal.signal(signal.SIGALRM, child_alarm)
                    signal.setitimer(signal.ITIMER_REAL, RESOURCES['child_deadline_seconds'])
                    proc = resources._process(child.pid)
                    require(proc is not None and proc['parent_pid'] == os.getpid() and proc['group_pid'] == child.pid,
                            'new child is not an owned isolated group leader')
                    identity = {key: proc[key] for key in ('pid', 'birth')}
                    # The gated leader cannot start the model or descendants yet.
                    # Bind cached custody before any fallible write so the owner's
                    # context cannot infer an absent child on a later failure.
                    require(owner._child is None and owner._owner_pid == os.getpid() and owner._entered,
                            'fresh entered resource owner required for child custody')
                    owner._child = dict(identity)
                    owner._update(child=dict(identity), prior_children=[])
                    write(attempt / 'child-identity.json', identity)
                    watchdog.bind_child(identity)
                    watchdog.start()
                    rss_sampler = OwnedGroupRSSSampler(resources, identity,
                        events_path=attempt / 'group-rss-observations.jsonl',
                        memory_limit_bytes=RESOURCES['memory_mb'] * 1024**2,
                        safe_exception=watch.safe_exception)
                    rss_sampler.start()
                    # The full named-root census can outlast the watchdog's gap
                    # bound. Monitor concurrently while the model remains gated.
                    initial_usage = owner.check_usage(attempt, child.pid)
                    watchdog.assert_healthy()
                    rss_sampler.assert_healthy()
                    os.write(launch_gate, b'1')
                    os.close(launch_gate)
                    launch_gate = None
                    model_started = True
                    rss_sampler.mark_model_started()
                    observations = [initial_usage]
                    write(attempt / 'resources-start.json', watch.safe_owner_snapshot(owner))
                    next_usage = time.monotonic() + 20
                    while child.poll() is None:
                        watchdog.assert_healthy()
                        rss_sampler.assert_healthy()
                        require(time.monotonic() - child_started <= RESOURCES['child_deadline_seconds'],
                                'owned child exceeded five-minute deadline')
                        if time.monotonic() >= next_usage:
                            observations.append(owner.check_usage(attempt, child.pid))
                            write(attempt / 'resource-observations.json', observations, replace=True)
                            next_usage = time.monotonic() + 20
                        time.sleep(.1)
                    code = child.wait()
                    rss_sampler.mark_model_stopped()
                    signal.setitimer(signal.ITIMER_REAL, 0)
                    signal.signal(signal.SIGALRM, previous_alarm)
                    log.flush()
                    os.fsync(log.fileno())
                write(attempt / 'child-exit.json', dict(returncode=code, leader_reaped=True,
                    launch_through_reap_wall_seconds=time.monotonic() - child_started))
                require(code == 0, 'model child failed: ' + str(code))
                require((attempt / 'results/summary.json').is_file(), 'successful child summary missing')
                cleanup_receipt = cleanup(child, identity, resources)
                rss_sampler.stop()
                rss_sampler.assert_healthy()
                rss_sampler.sample('post_cleanup')
                rss_summary = rss_sampler.snapshot()
                rss_sampler.close()
                write(attempt / 'group-rss-summary.json', dict(**rss_summary,
                    events=pin(attempt / 'group-rss-observations.jsonl')))
                watchdog.stop()
                watchdog.assert_healthy()
                watchdog.observe('pre_finalize')
                write(attempt / 'resource-observations.json', observations, replace=True)
                write(attempt / 'owned-group-final.json', cleanup_receipt)
                sync_tree(attempt)
                released = owner.finalize(attempt, artifacts_durable=True)
                absent = watchdog.observe('post_finalize', expected='absent')
                watchdog.close()
                write(attempt / 'resources-final.json', dict(owner=released, lease_absent=absent,
                    lease_events=pin(attempt / 'lease-observations.jsonl'),
                    group_rss_summary=pin(attempt / 'group-rss-summary.json'),
                    continuous_lease_coverage_claimed=False))
                write(attempt / 'guardian-exit.json', dict(schema='scope-pilot-guardian-exit/v1', returncode=0,
                    child_returncode=code, elapsed_seconds=time.monotonic() - started,
                    sampled_model_phase_peak_rss_bytes=rss_summary['sampled_model_phase_peak_rss_bytes'],
                    model_phase_RSS_sample_count=rss_summary['model_phase_sample_count'],
                    model_phase_peak_is_sampled=True, kernel_hard_memory_cap=False,
                    artifacts_durable=True, resource_reservation_released=True,
                    resource_release_scope='reserved attempt bytes checked before release; final accounting excludes later terminal receipts',
                    model_authority=False))
                sync_tree(attempt)
                print(json.dumps(dict(status='completed', physical_attempt=str(attempt), returncode=0)), flush=True)
                return 0
            except BaseException as error:
                # Retain the primary event and stop only our child BEFORE owner
                # context exit can retain/release accounting or raise cleanup.
                signal.setitimer(signal.ITIMER_REAL, 0)
                signal.signal(signal.SIGALRM, previous_alarm)
                primary = watch.safe_exception(error)
                if launch_gate is not None:
                    os.close(launch_gate)
                    launch_gate = None
                try:
                    write(attempt / 'failure-primary.json', dict(error=primary,
                        resources=watch.safe_owner_snapshot(owner), child_identity=identity,
                        model_started=model_started,
                        group_rss=None if rss_sampler is None else rss_sampler.snapshot()))
                except BaseException as evidence_error:
                    primary['primary_evidence_write_error'] = watch.safe_exception(evidence_error)
                if watchdog is not None:
                    try:
                        watchdog.stop()
                    except BaseException as stop_error:
                        primary['watchdog_stop_error'] = watch.safe_exception(stop_error)
                if rss_sampler is not None:
                    try:
                        rss_sampler.stop()
                    except BaseException as rss_stop_error:
                        primary['rss_stop_error'] = watch.safe_exception(rss_stop_error)
                try:
                    cleanup_receipt = cleanup(child, identity, resources)
                except BaseException as cleanup_error:
                    cleanup_receipt = dict(cleanup_verified=False, error=watch.safe_exception(cleanup_error))
                try:
                    sync_tree(attempt)
                except BaseException as durability_error:
                    primary['failure_durability_error'] = watch.safe_exception(durability_error)
                raise
    except BaseException as error:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_alarm)
        if launch_gate is not None:
            os.close(launch_gate)
            launch_gate = None
        if primary is None:
            primary = watch.safe_exception(error)
            write(attempt / 'failure-primary.json', dict(error=primary, resources=watch.safe_owner_snapshot(owner),
                child_identity=identity, model_started=model_started))
        else:
            primary['outer_error'] = watch.safe_exception(error)
        if watchdog is not None:
            try:
                watchdog.stop()
            except BaseException as stop_error:
                primary['watchdog_stop_error'] = watch.safe_exception(stop_error)
        if rss_sampler is not None:
            try:
                rss_sampler.stop()
            except BaseException as rss_stop_error:
                primary['rss_stop_error'] = watch.safe_exception(rss_stop_error)
        if cleanup_receipt is None:
            try:
                cleanup_receipt = cleanup(child, identity, resources)
            except BaseException as cleanup_error:
                cleanup_receipt = dict(cleanup_verified=False, error=watch.safe_exception(cleanup_error))
        if watchdog is not None:
            try:
                watchdog.close()
            except BaseException as close_error:
                primary['watchdog_close_error'] = watch.safe_exception(close_error)
        if rss_sampler is not None:
            try:
                if model_started and not rss_sampler._closed:
                    rss_sampler.mark_model_stopped()
            except BaseException as rss_final_error:
                primary['rss_final_observation_error'] = watch.safe_exception(rss_final_error)
            try:
                rss_sampler.close()
            except BaseException as rss_close_error:
                primary['rss_close_error'] = watch.safe_exception(rss_close_error)
            rss_failure_path = attempt / ('group-rss-failure-summary.json'
                if (attempt / 'group-rss-summary.json').exists() else 'group-rss-summary.json')
            write(rss_failure_path, dict(**rss_sampler.snapshot(),
                events=pin(attempt / 'group-rss-observations.jsonl')))
        if (getattr(owner, '_lease', None) is not None
                and (child is None or cleanup_receipt.get('live_group_processes') == 0)
                and not getattr(owner._lease, '_released', False)):
            try:
                owner._lease.release()
            except BaseException as release_error:
                primary['owned_cpu_lease_release_error'] = watch.safe_exception(release_error)
        write(attempt / 'resources-final-failure.json', dict(resources=watch.safe_owner_snapshot(owner),
            cleanup=cleanup_receipt, artifacts_durable_before_disk_release=False,
            group_rss=None if rss_sampler is None else rss_sampler.snapshot(),
            failed_disk_claim_retained=(getattr(owner, '_record', None) or {}).get('status') != 'released'))
        write(attempt / 'child-exit.json', dict(returncode=None if child is None else child.poll(),
            child_created=child is not None, leader_reaped=child is None or child.poll() is not None), replace=True)
        write(attempt / 'guardian-exit.json', dict(schema='scope-pilot-guardian-exit/v1', returncode=1,
            child_returncode=None if child is None else child.poll(), error=primary, cleanup=cleanup_receipt,
            elapsed_seconds=time.monotonic() - started, resources=watch.safe_owner_snapshot(owner),
            resource_reservation_released=(getattr(owner, '_record', None) or {}).get('status') == 'released',
            retained_reservation_requires_explicit_reconciliation=(getattr(owner, '_record', None) or {}).get('status') != 'released',
            automatic_scheduler_reset=False, replacement_lease_acquired=False, model_authority=False))
        sync_tree(attempt)
        print(json.dumps(dict(status='failed', physical_attempt=str(attempt), error_type=type(error).__name__)), flush=True)
        return 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--plan', type=Path)
    parser.add_argument('--review', type=Path)
    parser.add_argument('--runner', type=Path)
    parser.add_argument('--package-root', type=Path)
    parser.add_argument('--attempt')
    args = parser.parse_args()
    if args.check:
        require(not any((args.plan, args.review, args.runner, args.package_root, args.attempt)),
                '--check accepts no execution inputs')
        print(json.dumps(closure_and_configuration()[-1], sort_keys=True, indent=2), flush=True)
        return 0
    require(all((args.plan, args.review, args.runner, args.package_root, args.attempt)),
            'plan, clean review, runner, candidate root and fresh attempt are required')
    return execute(args)


if __name__ == '__main__':
    raise SystemExit(main())
