"""Guardian-local, read-only observations of one authenticated scheduler lease.

Never constructs a scheduler client, renews/releases a lease, repairs shared
state, or follows changed configuration. Capability keys stay in memory only.
An observation gap is uncertainty, not proof of continuous lease coverage.
"""
from copy import deepcopy
from dataclasses import dataclass, field
import errno
import fcntl
import hashlib
import hmac
import json
import math
import os
from pathlib import Path
import signal
import stat
import threading
import time
import traceback

SCHEMA = 'guardian-owned-lease-observation/v1'
SCHEDULER_SCHEMA = 'legal-ir-global-resource-scheduler-v1'
MAX_STATE_BYTES = 16*1024*1024
STATE_KEYS = {'schema_version','config','leases','waiters','metrics','next_sequence'}
OWN_FIELDS = ('lease_id','lane','cpu_slots','memory_mb','gpu_memory_mb','unified_memory_mb',
              'child_process_slots','requires_gpu','parent_lease_id','owner_pid','owner_birth_marker','acquired_at')


def _raw(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def _digest(value):
    return hashlib.sha256(_raw(value)).hexdigest()


class LeaseWatchdogError(RuntimeError):
    def __init__(self, code, observation=None):
        self.code = code
        self.observation = deepcopy(observation)
        super().__init__('owned lease watchdog: '+code)


def _require(value, code, observation=None):
    if not value:
        raise LeaseWatchdogError(code, observation)


def _finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def _bounded_seconds(value, maximum, code):
    _require(_finite(value) and 0 < value <= maximum, code)
    return float(value)


def _unique(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result, 'duplicate_state_key')
        result[key] = value
    return result


def _reject_constant(_):
    raise LeaseWatchdogError('nonfinite_state_json')


def _validate_historical_proof_refusal(value):
    """Validate but never normalize, disclose, or act on historical metadata."""
    def required(condition):
        if not condition:
            raise ValueError('invalid bounded historical proof refusal metadata')
    def number(item):
        return type(item) in (int, float) and math.isfinite(item) and item >= 0
    def string(item, maximum, optional=False):
        return (optional and item is None) or (type(item) is str and len(item) <= maximum and (not item or item.isprintable()))
    keys = {'schema','historical','decision_cycle_at','gate','reason','waiter_id','sequence','request_id','lane',
        'parent_lease_id','sample','sample_contract','thresholds','proof_memory_headroom_mb','demand','backoff_until','error_type'}
    required(type(value) is dict and set(value) == keys and value['schema'] == 'proof-resource-admission-refusal@1'
        and value['historical'] is True and value['gate'] in ('request_pressure','envelope'))
    required(value['decision_cycle_at'] is None or number(value['decision_cycle_at']))
    required(value['backoff_until'] is None or number(value['backoff_until']))
    required(value['sequence'] is None or type(value['sequence']) is int and value['sequence'] >= 1)
    required(all(string(value[key],limit,optional) for key,limit,optional in
        (('reason',128,False),('waiter_id',128,False),('request_id',256,False),('lane',128,False),
         ('parent_lease_id',128,True),('error_type',128,True))))
    required(value['sample_contract'] == 'max-host-visible-cgroup-avg10; memory/full,cpu/some,io/full; optional-psi-zero-fallback')
    required(type(value['proof_memory_headroom_mb']) is int and value['proof_memory_headroom_mb'] >= 0)
    thresholds = value['thresholds']
    required(type(thresholds) is dict and set(thresholds) == {'memory_stall_percent','cpu_stall_percent','io_stall_percent'}
        and all(number(item) and item <= 100 for item in thresholds.values()))
    sample = value['sample']
    if sample is not None:
        required(type(sample) is dict and set(sample) == {'cpu_slots','total_memory_mb','available_memory_mb',
            'memory_stall_percent','cpu_stall_percent','io_stall_percent','pid_task_limit','available_pid_tasks'})
        required(type(sample['cpu_slots']) is int and sample['cpu_slots'] >= 1
            and type(sample['total_memory_mb']) is int and sample['total_memory_mb'] >= 1
            and type(sample['available_memory_mb']) is int and 0 <= sample['available_memory_mb'] <= sample['total_memory_mb'])
        required(all(number(sample[key]) and sample[key] <= 100 for key in ('memory_stall_percent','cpu_stall_percent','io_stall_percent')))
        required((sample['pid_task_limit'] is None) == (sample['available_pid_tasks'] is None))
        if sample['pid_task_limit'] is not None:
            required(type(sample['pid_task_limit']) is int and sample['pid_task_limit'] >= 1
                and type(sample['available_pid_tasks']) is int and 0 <= sample['available_pid_tasks'] <= sample['pid_task_limit'])
    demand = value['demand']
    if demand is not None:
        required(type(demand) is dict and set(demand) in ({'requested_memory_mb'},
            {'root_reserved_memory_mb','additional_memory_mb','root_reserved_process_slots','additional_process_slots','pid_tasks_required'})
            and all(type(item) is int and item >= 0 for item in demand.values()))


@dataclass(frozen=True)
class LeaseBinding:
    state_path: Path
    lock_path: Path
    config: dict = field(repr=False)
    own_fields: dict = field(repr=False)
    lock_identity: tuple
    lease_key: str = field(repr=False)
    _config_digest: str = field(init=False,repr=False)
    _own_digest: str = field(init=False,repr=False)

    def __post_init__(self):
        object.__setattr__(self,'config',deepcopy(self.config))
        object.__setattr__(self,'own_fields',deepcopy(self.own_fields))
        object.__setattr__(self,'_config_digest',_digest(self.config))
        object.__setattr__(self,'_own_digest',_digest(self.own_fields))

    @property
    def lease_id(self):
        return self.own_fields['lease_id']

    def public(self):
        return dict(state_path=str(self.state_path), lock_path=str(self.lock_path),
                    config_sha256=_digest(self.config), own_fields=deepcopy(self.own_fields),
                    lock_identity=list(self.lock_identity), capability_persisted=False)


def _regular(path, *, single_link=False):
    metadata = path.lstat()
    _require(stat.S_ISREG(metadata.st_mode) and not path.is_symlink(), 'nonregular_scheduler_path')
    _require(not single_link or metadata.st_nlink == 1, 'scheduler_lock_link_count')
    _require(metadata.st_uid == os.getuid(), 'scheduler_path_owner_differs')
    return metadata


def capture_lease_binding(owner, adoption, resources):
    """Bind known owner/client attributes without to_dict/cancelled/snapshot calls."""
    lease = owner._lease
    _require(lease is not None and owner._entered and owner._owner_pid == os.getpid(), 'owner_not_admitted_here')
    client = lease._scheduler
    config = deepcopy(adoption['shared_config'])
    _require(_digest(config) == adoption['shared_config_sha256']
             and client.config.persisted_dict() == config, 'admission_configuration_differs')
    state_path = Path(adoption['observed_after']['path']).absolute()
    lock_path = state_path.with_name(state_path.name+'.lock')
    _require(Path(client.state_path).absolute() == state_path
             and Path(client.lock_path).absolute() == lock_path, 'admission_scheduler_path_differs')
    process = resources._process(os.getpid())
    _require(process is not None and process['birth'], 'owner_birth_unavailable')
    values = {name: deepcopy(getattr(lease, name)) for name in OWN_FIELDS if name != 'owner_birth_marker'}
    values['owner_birth_marker'] = process['birth']
    _require(values['owner_pid'] == os.getpid() and values['lease_id']
             and type(lease.lease_key) is str and lease.lease_key, 'invalid_owned_lease_identity')
    meta = _regular(lock_path, single_link=True)
    return LeaseBinding(state_path, lock_path, config, values,
                        (meta.st_dev, meta.st_ino), lease.lease_key)


def observe_lease(binding, *, stage, expected='present', lock_timeout=.5):
    """Bounded shared-lock snapshot; no shared file is created or written."""
    _require(type(binding) is LeaseBinding, 'explicit_lease_binding_required')
    _require(_digest(binding.config)==binding._config_digest and _digest(binding.own_fields)==binding._own_digest,
             'lease_binding_changed')
    _require(expected in ('present','absent'), 'invalid_expected_lease_state')
    _require(type(stage) is str and stage in ('pre_spawn','post_spawn','monitor','pre_finalize','post_finalize','cleanup'),
             'invalid_observation_stage')
    timeout = _bounded_seconds(lock_timeout, 10., 'invalid_lock_timeout')
    started = time.monotonic(); deadline = started+timeout
    event = dict(schema=SCHEMA, stage=stage, expected=expected, observed_at_unix=time.time(),
                 observed_at_monotonic=started, lease_id=binding.lease_id,
                 expected_config_sha256=_digest(binding.config), read_only=True,
                 capability_persisted=False, continuous_coverage_claimed=False)
    lock_fd = state_fd = None
    try:
        meta = _regular(binding.lock_path, single_link=True)
        _require((meta.st_dev,meta.st_ino) == binding.lock_identity, 'scheduler_lock_identity_changed', event)
        lock_fd = os.open(binding.lock_path, os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
        held = os.fstat(lock_fd)
        _require((held.st_dev,held.st_ino) == binding.lock_identity and held.st_nlink == 1,
                 'scheduler_lock_identity_changed', event)
        while True:
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_SH|fcntl.LOCK_NB)
                break
            except BlockingIOError:
                _require(time.monotonic() < deadline, 'scheduler_lock_timeout', event)
                time.sleep(min(.01, max(0.,deadline-time.monotonic())))
        _require(time.monotonic() < deadline, 'observation_deadline', event)
        meta = _regular(binding.lock_path, single_link=True)
        _require((meta.st_dev,meta.st_ino) == binding.lock_identity, 'scheduler_lock_identity_changed', event)
        state_fd = os.open(binding.state_path, os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
        info = os.fstat(state_fd)
        _require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
                 and 0 < info.st_size <= MAX_STATE_BYTES, 'invalid_bounded_scheduler_state', event)
        chunks=[];length=0
        while True:
            _require(time.monotonic() < deadline, 'observation_deadline', event)
            block=os.read(state_fd,min(65536, MAX_STATE_BYTES+1-length))
            if not block:break
            chunks.append(block);length+=len(block)
            _require(length <= MAX_STATE_BYTES, 'scheduler_state_too_large', event)
        content=b''.join(chunks)
        event.update(state_sha256=hashlib.sha256(content).hexdigest(),state_bytes=len(content))
        try:
            state=json.loads(content,object_pairs_hook=_unique,parse_constant=_reject_constant)
        except LeaseWatchdogError:
            raise
        except (ValueError,UnicodeError):
            raise LeaseWatchdogError('invalid_scheduler_json',event) from None
        _require(time.monotonic() < deadline, 'observation_deadline', event)
        meta = _regular(binding.lock_path, single_link=True)
        _require((meta.st_dev,meta.st_ino) == binding.lock_identity, 'scheduler_lock_identity_changed', event)
        _require(type(state) is dict and STATE_KEYS <= set(state) <= STATE_KEYS|{'proof_backoff', 'last_proof_refusal'}
                 and state['schema_version']==SCHEDULER_SCHEMA, 'scheduler_schema_changed', event)
        if 'last_proof_refusal' in state:
            try:
                _validate_historical_proof_refusal(state['last_proof_refusal'])
            except ValueError:
                raise LeaseWatchdogError('historical_proof_refusal_invalid', event) from None
        _require(type(state['config']) is dict and type(state['leases']) is dict, 'invalid_scheduler_containers', event)
        event['observed_config_sha256']=_digest(state['config'])
        event['configuration_matches']=state['config']==binding.config and event['observed_config_sha256']==event['expected_config_sha256']
        # Only trusted configuration field names are exposed; never arbitrary
        # state contents, unknown keys, lease capabilities, or foreign records.
        event['changed_known_configuration_fields']=[key for key in sorted(binding.config)
                                                     if state['config'].get(key)!=binding.config[key]]
        event['unknown_configuration_fields_present']=bool(set(state['config'])-set(binding.config))
        row=state['leases'].get(binding.lease_id)
        event['lease_present']=row is not None
        _require(event['configuration_matches'], 'scheduler_configuration_changed', event)
        if expected=='absent':
            _require(row is None, 'owned_lease_still_present_after_release', event)
        else:
            _require(type(row) is dict, 'owned_lease_missing', event)
            _require(type(row.get('lease_key')) is str and hmac.compare_digest(row['lease_key'],binding.lease_key),
                     'owned_lease_authority_changed', event)
            matches=all(type(row.get(key)) is type(value) and row[key]==value for key,value in binding.own_fields.items())
            event['owned_identity_matches']=matches
            _require(matches,'owned_lease_identity_changed',event)
            now=time.time();event['checked_at_unix']=now
            for name in ('heartbeat_at','expires_at'):
                _require(_finite(row.get(name)), 'invalid_owned_lease_clock', event)
                event[name]=row[name]
            _require(type(row.get('cancelled')) is bool,'invalid_owned_cancellation_flag',event)
            event['cancelled']=row['cancelled']
            _require(not event['cancelled'],'owned_lease_cancelled',event)
            _require(row['heartbeat_at']>=row['acquired_at'] and row['expires_at']>=row['heartbeat_at'],
                     'invalid_owned_lease_clock',event)
            _require(row['expires_at']>now,'owned_lease_expired',event)
            event['remaining_ttl_seconds']=row['expires_at']-now
        event.update(healthy=True,elapsed_seconds=time.monotonic()-started)
        return event
    except LeaseWatchdogError as error:
        if error.observation is None:error.observation=deepcopy(event)
        raise
    except OSError as error:
        event['os_error_number']=error.errno
        raise LeaseWatchdogError('scheduler_io_failure',event) from None
    finally:
        if state_fd is not None:os.close(state_fd)
        if lock_fd is not None:os.close(lock_fd)


class OwnedLeaseWatchdog:
    """Watch independently of expensive disk accounting; interrupt only owned work."""
    def __init__(self,binding,*,resources,events_path,poll_seconds=1.,lock_timeout=.5,max_observation_gap=5.,signal_group=None):
        self.binding=binding;self.resources=resources
        self.poll_seconds=_bounded_seconds(poll_seconds,5.,'invalid_poll_interval')
        self.lock_timeout=_bounded_seconds(lock_timeout,10.,'invalid_lock_timeout')
        self.max_gap=_bounded_seconds(max_observation_gap,30.,'invalid_observation_gap')
        _require(self.max_gap>self.poll_seconds+self.lock_timeout,'observation_gap_too_short')
        self._signal_group=signal_group or os.killpg
        self._mutex=threading.RLock();self._io=threading.Lock();self._stop=threading.Event()
        self._thread=None;self._failure=None;self._last=None;self._child=None;self._signalled=False
        self._fd=os.open(Path(events_path),os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        self.events_path=Path(events_path);self._closed=False
        try:
            self._record(dict(schema='guardian-owned-lease-watchdog-start/v1',binding=binding.public(),
                              poll_seconds=self.poll_seconds,lock_timeout_seconds=self.lock_timeout,
                              maximum_observation_gap_seconds=self.max_gap,continuous_coverage_claimed=False))
        except BaseException:
            os.close(self._fd);self._closed=True
            raise

    def _record(self,event):
        data=_raw(event)+b'\n'
        # An explicit defensive check also protects injected diagnostic errors.
        _require(self.binding.lease_key.encode() not in data,'capability_in_observation_refused')
        with self._io:
            _require(not self._closed,'watchdog_log_closed')
            offset=0
            while offset<len(data):
                written=os.write(self._fd,data[offset:])
                _require(written>0,'watchdog_log_write_stalled');offset+=written
            os.fsync(self._fd)

    def bind_child(self,identity):
        _require(type(identity) is dict and set(identity)=={'pid','birth'} and type(identity['pid']) is int
                 and identity['pid']>1 and type(identity['birth']) is str and identity['birth'], 'invalid_child_identity')
        process=self.resources._process(identity['pid'])
        _require(process is not None and process['birth']==identity['birth'] and process['parent_pid']==os.getpid()
                 and process['group_pid']==identity['pid'] and identity['pid']!=os.getpgrp(), 'child_not_owned_isolated_group')
        with self._mutex:
            _require(self._child is None,'child_already_bound')
            self._child=dict(identity)
        if self._failure is not None:self._interrupt_owned_child()

    def _interrupt_owned_child(self):
        with self._mutex:
            if self._child is None or self._signalled:return
            identity=dict(self._child)
            try:
                usage=self.resources._group_usage(identity)
                if not usage['live_processes']:
                    self._failure['child_interrupt']=dict(status='owned_group_already_exited')
                    return
                # Revalidate immediately before signaling; never use a PID read
                # from scheduler state or a mutable foreign record.
                usage=self.resources._group_usage(identity)
                if not usage['live_processes']:
                    self._failure['child_interrupt']=dict(status='owned_group_already_exited')
                    return
                self._signal_group(identity['pid'],signal.SIGINT);self._signalled=True
                self._failure['child_interrupt']=dict(status='SIGINT_sent',identity=identity,
                    observed_live_processes=usage['live_processes'])
            except ProcessLookupError:
                self._failure['child_interrupt']=dict(status='owned_group_exited_during_signal')
            except BaseException as error:
                self._failure['child_interrupt']=dict(status='signal_refused_or_failed',error_type=type(error).__name__)

    def _fail(self,error):
        with self._mutex:
            if self._failure is not None:return
            self._failure=dict(schema='guardian-owned-lease-watchdog-failure/v1',code=error.code,
                error_type=type(error).__name__,observation=deepcopy(error.observation),
                recorded_at_unix=time.time(),recorded_at_monotonic=time.monotonic(),
                shared_state_mutated=False,continuous_coverage_claimed=False)
        self._stop.set()
        # Interrupt before durable logging: a stalled sink must not prevent
        # the owned child receiving the fail-closed signal. Never hold the
        # failure-state mutex across a filesystem write.
        self._interrupt_owned_child()
        if self._io.acquire(blocking=False):
            self._io.release()
            try:self._record(self.failure_receipt())
            except BaseException as recording:
                with self._mutex:self._failure['evidence_write_error_type']=type(recording).__name__
        else:
            with self._mutex:self._failure['evidence_write_error_type']='ObservationLogBusy'

    def observe(self,stage,*,expected='present'):
        self.assert_healthy()
        try:
            previous=self._last
            event=observe_lease(self.binding,stage=stage,expected=expected,lock_timeout=self.lock_timeout)
            if stage in ('monitor','post_spawn') and previous is not None:
                event['observation_gap_seconds']=event['observed_at_monotonic']-previous
                _require(event['observation_gap_seconds']<=self.max_gap,'observation_gap_exceeded',event)
            self._last=event['observed_at_monotonic'];self._record(event)
            return event
        except LeaseWatchdogError as error:
            self._fail(error);raise
        except BaseException as error:
            failure=LeaseWatchdogError('observer_internal_failure',dict(error_type=type(error).__name__))
            self._fail(failure);raise failure from None

    def _loop(self):
        while not self._stop.wait(self.poll_seconds):
            try:self.observe('monitor')
            except LeaseWatchdogError:return

    def start(self):
        _require(self._thread is None and self._child is not None,'watchdog_requires_one_bound_child')
        self.observe('post_spawn')
        self._thread=threading.Thread(target=self._loop,name='owned-lease-watchdog',daemon=True)
        self._thread.start()

    def assert_healthy(self):
        with self._mutex:
            failure=deepcopy(self._failure)
        if failure is not None:raise LeaseWatchdogError(failure['code'],failure.get('observation'))
        # The main guardian also checks this while the observer thread may be
        # blocked in local I/O. This cannot promise a kernel-level time bound.
        if self._thread is not None and not self._stop.is_set() and self._last is not None:
            if time.monotonic()-self._last>self.max_gap:
                error=LeaseWatchdogError('observation_gap_exceeded',dict(last_observed_at_monotonic=self._last,
                    observed_at_monotonic=time.monotonic(),maximum_observation_gap_seconds=self.max_gap))
                self._fail(error);raise error

    def stop(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=min(15.,self.poll_seconds+self.lock_timeout+2.))
            _require(not self._thread.is_alive(),'watchdog_thread_did_not_stop')
        return self.failure_receipt()

    def failure_receipt(self):
        with self._mutex:return deepcopy(self._failure)

    def close(self):
        self.stop()
        with self._io:
            if not self._closed:os.close(self._fd);self._closed=True


def safe_exception(error):
    """Preserve exception identity without serializing arbitrary capability data."""
    return dict(error_type=type(error).__name__,code=error.code if isinstance(error,LeaseWatchdogError) else None,
                message_omitted_to_avoid_capability_leak=True,
                traceback_frames=[dict(file=frame.filename,line=frame.lineno,function=frame.name)
                    for frame in traceback.extract_tb(error.__traceback__)[-16:]])


def safe_owner_snapshot(owner):
    """Cached primitives only: no lease.cancelled, scheduler read, or to_dict."""
    lease=getattr(owner,'_lease',None)
    allowed=('lease_id','lane','cpu_slots','memory_mb','gpu_memory_mb','unified_memory_mb','child_process_slots',
             'requires_gpu','parent_lease_id','owner_pid','acquired_at','wait_seconds')
    value=dict(schema='guardian-cached-resource-snapshot/v1',reservation_id=getattr(owner,'reservation_id',None),
        ledger_path=str(owner.ledger_path),record=deepcopy(getattr(owner,'_record',None)),
        cleanup_error=getattr(owner,'_cleanup_error',None),resource_lease=None,
        scheduler_state_read=False,lease_cancellation_read=False,snapshot_scope='cached_owner_primitives_only')
    if lease is not None:
        value['resource_lease']={name:deepcopy(getattr(lease,name)) for name in allowed}
        value['resource_lease']['locally_released_flag']=bool(getattr(lease,'_released',False))
        _require(lease.lease_key.encode() not in _raw(value),'capability_in_cached_snapshot_refused')
    return value
