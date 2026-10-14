"""Adopt the existing scheduler configuration without an idle-state reset.

Guardian-local integration only. A narrow scheduler subclass rejects any changed
or missing persisted configuration under the scheduler's normal stable-file
lock. Exact configurations retain all inherited admission and proof safeguards.
No foreign lease is acquired, released, cancelled, or recovered by adoption.
"""
from copy import deepcopy
import hashlib
import importlib
import json
import math
import os
from pathlib import Path
import stat
import time

SCHEMA = 'guardian-adopt-shared-scheduler/v1'
SCHEDULER_RELATIVE = 'ipfs_datasets_py/optimizers/logic_theorem_optimizer/resource_scheduler.py'
OWNER_RELATIVE = 'ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_daemon_resources.py'
SCHEDULER_SHA256 = 'a418e84f70ed8509ba0518feea69e7a8c27865139f83b6c81349eefdfd5893a4'
OWNER_SHA256 = 'b00d2752ba852fe73760bba4fbd51b0e845742c3527642606a2a77ed9f8f5e2c'
OWNER_PATH = Path('/home/barberb/lift_coding/external/ipfs_datasets/workspace/test-logs/native4096-four-width-20261004/resource-cap/autoencoder_daemon_resources.py')
INTEGER_KEYS = {'total_cpu_slots','total_memory_mb','total_child_process_slots','reserved_memory_mb',
    'reserved_gpu_memory_mb','proof_memory_headroom_mb'}
OPTIONAL_INTEGER_KEYS = {'total_gpu_memory_mb','total_unified_memory_mb','max_waiting_requests'}
PERCENT_KEYS = {'proof_memory_stall_percent','proof_cpu_stall_percent','proof_io_stall_percent'}
OPTIONAL_PERCENT_KEYS = {'max_memory_percent','max_swap_percent','max_gpu_memory_percent'}
BOOLEAN_KEYS = {'proof_safety_enabled','require_known_gpu_for_gpu_work'}
PERSISTED_KEYS = (INTEGER_KEYS|OPTIONAL_INTEGER_KEYS|PERCENT_KEYS|OPTIONAL_PERCENT_KEYS|
    BOOLEAN_KEYS|{'proof_backoff_seconds','lane_reservations'})
STATE_REQUIRED_KEYS = {'schema_version','config','leases','waiters','metrics','next_sequence'}
STATE_OPTIONAL_KEYS = {'proof_backoff', 'last_proof_refusal'}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def raw(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(raw(value)).hexdigest()


def unique_object(pairs):
    result = {}
    for key,value in pairs:
        require(key not in result, 'duplicate scheduler JSON key: '+key)
        result[key] = value
    return result


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


def read_existing(path):
    """Read atomic JSON bytes; scheduler locking revalidates the actual state."""
    path = Path(path)
    metadata = path.lstat()
    require(stat.S_ISREG(metadata.st_mode) and not path.is_symlink()
        and 0 < metadata.st_size <= 16*1024*1024, 'bounded existing regular scheduler state required')
    content = path.read_bytes()
    require(len(content) <= 16*1024*1024, 'scheduler state grew beyond read bound')
    value = json.loads(content,object_pairs_hook=unique_object)
    require(type(value) is dict and STATE_REQUIRED_KEYS <= set(value)
        and set(value) <= STATE_REQUIRED_KEYS|STATE_OPTIONAL_KEYS,
        'closed existing scheduler state inventory required')
    require(all(type(value[name]) is dict for name in ('config','leases','waiters','metrics'))
        and type(value['next_sequence']) is int and value['next_sequence'] >= 1
        and ('proof_backoff' not in value or type(value['proof_backoff']) is dict),
        'invalid existing scheduler containers')
    if 'last_proof_refusal' in value:
        _validate_historical_proof_refusal(value['last_proof_refusal'])
    return value,dict(path=str(path),sha256=hashlib.sha256(content).hexdigest(),bytes=len(content),
        device=metadata.st_dev,inode=metadata.st_ino)


def validated_config(scheduler, state, path):
    require(state['schema_version'] == scheduler.RESOURCE_SCHEDULER_SCHEMA_VERSION,
        'unsupported existing scheduler schema')
    stored = state['config']
    require(type(stored) is dict and set(stored) == PERSISTED_KEYS,
        'exact complete persisted scheduler configuration required; unknown/missing keys refused')
    for name in INTEGER_KEYS:
        require(type(stored[name]) is int, 'integer scheduler field required: '+name)
    for name in OPTIONAL_INTEGER_KEYS:
        require(stored[name] is None or type(stored[name]) is int, 'optional integer scheduler field required: '+name)
    for name in BOOLEAN_KEYS:
        require(type(stored[name]) is bool, 'Boolean scheduler field required: '+name)
    for name in PERCENT_KEYS|{'proof_backoff_seconds'}:
        require(type(stored[name]) in (int,float) and math.isfinite(stored[name]),
            'finite numeric scheduler field required: '+name)
    for name in OPTIONAL_PERCENT_KEYS:
        require(stored[name] is None or type(stored[name]) in (int,float) and math.isfinite(stored[name]),
            'finite optional scheduler field required: '+name)
    reservations = stored['lane_reservations']
    require(type(reservations) is dict and len(reservations) <= 64, 'bounded explicit lane reservations required')
    for lane,reservation in reservations.items():
        require(type(lane) is str and 0 < len(lane) <= 128 and lane.strip() == lane
            and type(reservation) is dict and set(reservation) == {'cpu_slots','memory_mb'}
            and all(type(reservation[name]) is int and reservation[name] >= 0 for name in reservation),
            'exact typed lane reservation required')
    # No arbitrary callable or nonpersisted field is deserialized. Pressure and
    # proof samplers remain the reviewed scheduler's trusted local defaults.
    config = scheduler.ResourceSchedulerConfig(**deepcopy(stored),state_path=Path(path))
    config.validate()
    require(config.persisted_dict() == stored and digest(config.persisted_dict()) == digest(stored),
        'scheduler normalization changed persisted configuration')
    return config


def exact_existing_client(scheduler, config):
    """Use inherited locking/admission; remove only the idle reset fallback."""
    expected = deepcopy(config.persisted_dict())
    class ExactExistingScheduler(scheduler.GlobalResourceScheduler):
        def _new_state(self):
            raise scheduler.ResourceConfigurationError('shared scheduler disappeared; adoption never initializes or resets state')

        def _validate_state_configuration(self, state):
            require(type(state) is dict and STATE_REQUIRED_KEYS <= set(state) <= STATE_REQUIRED_KEYS|STATE_OPTIONAL_KEYS,
                'changed existing scheduler inventory refused without reset')
            if 'last_proof_refusal' in state:
                _validate_historical_proof_refusal(state['last_proof_refusal'])
            if (type(state) is not dict or state.get('schema_version') != scheduler.RESOURCE_SCHEDULER_SCHEMA_VERSION
                    or state.get('config') != expected or digest(state.get('config')) != digest(expected)):
                raise scheduler.ResourceConfigurationError('shared scheduler configuration changed; fail-closed adoption refuses reset')
            # Equality was checked while the inherited stable sibling lock is
            # held. Existing proof/resource guards and subsequent methods stay
            # exactly as implemented by the pinned scheduler.
            return super()._validate_state_configuration(state)
    return ExactExistingScheduler(config)


def adopt_for_owner(resources, *, source_root, receipt_path):
    """Install an explicit client getter only in this guardian's owner module."""
    source_root = Path(source_root).resolve(); receipt_path = Path(receipt_path)
    require(not receipt_path.exists(), 'scheduler adoption receipt must be fresh')
    scheduler = importlib.import_module(resources.__package__+'.resource_scheduler')
    producer = {}
    for module,relative,expected in ((resources,OWNER_RELATIVE,OWNER_SHA256),
                                    (scheduler,SCHEDULER_RELATIVE,SCHEDULER_SHA256)):
        path = Path(module.__file__).resolve()
        require(path == (OWNER_PATH if module is resources else source_root/relative) and hashlib.sha256(path.read_bytes()).hexdigest() == expected,
            'resource client outside authenticated frozen producer')
        producer[relative] = expected
    path = scheduler.default_scheduler_state_path()
    state, snapshot = read_existing(path)
    config = validated_config(scheduler,state,path)
    # Defaults are observed for explaining the failure; they are never installed
    # or used to overwrite the existing shared configuration.
    defaults = scheduler.default_resource_scheduler_config().persisted_dict()
    client = exact_existing_client(scheduler,config)
    after, after_snapshot = read_existing(path)
    require(after['config'] == state['config'] and digest(after['config']) == digest(state['config']),
        'shared configuration changed immediately after client construction')
    previous_getter = resources.get_global_resource_scheduler
    require(callable(previous_getter), 'existing resource owner getter required')
    # Explicit construction avoids get_global_resource_scheduler() recomputing
    # defaults and rejecting a correctly configured process-local facade.
    resources.get_global_resource_scheduler = lambda: client
    receipt = dict(schema=SCHEMA,complete=True,created_at_unix=time.time(),owner_pid=os.getpid(),
        helper_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),producer_sha256=producer,
        shared_config=deepcopy(state['config']),shared_config_sha256=digest(state['config']),
        observed_before=snapshot,observed_after=after_snapshot,
        observed_before_lease_count=len(state['leases']),observed_after_lease_count=len(after['leases']),
        observed_before_waiter_count=len(state['waiters']),observed_after_waiter_count=len(after['waiters']),
        observed_before_claims_sha256=digest(dict(leases=state['leases'],waiters=state['waiters'])),
        observed_after_claims_sha256=digest(dict(leases=after['leases'],waiters=after['waiters'])),
        default_config=defaults,
        differing_default_fields={key:dict(default=defaults.get(key),adopted=state['config'][key])
            for key in sorted(PERSISTED_KEYS) if defaults.get(key) != state['config'][key]},
        nonpersisted_client_policy=dict(lease_ttl_seconds=config.lease_ttl_seconds,
            poll_interval_seconds=config.poll_interval_seconds,auto_renew_leases=config.auto_renew_leases,
            pressure_sampler='trusted local scheduler default; no serialized callback',
            proof_sampler='trusted local scheduler default; no serialized callback'),
        adapter='guardian-local subclass rejects any configuration mismatch or missing state under inherited lock',
        client_getter_scope='this guardian resource-owner module only; no scheduler source or other process modified',
        reset_performed=False,capacity_changed=False,proof_guards_changed=False,
        leases_acquired_by_adoption=0,leases_released_by_adoption=0,leases_cancelled_by_adoption=0,
        stale_recovery_called_by_adoption=False,global_scheduler_cache_modified=False,
        scheduler_constructor_may_rewrite_identical_json_under_lock=True,
        observation_scope='snapshot hashes may differ when other processes progress; no foreign claims are edited by this adapter',
        model_or_training_started=False)
    try:
        with receipt_path.open('x') as stream:
            json.dump(receipt,stream,sort_keys=True,indent=2,allow_nan=False);stream.write('\n');stream.flush();os.fsync(stream.fileno())
    except BaseException:
        resources.get_global_resource_scheduler = previous_getter
        raise
    return receipt
