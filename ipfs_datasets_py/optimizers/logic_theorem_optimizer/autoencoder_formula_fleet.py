"""Bounded formula-decoder branches behind one DuckDB owner and scoped Quack.

Workers never open the owner database. A branch resumes an exact registered
parent, trains privately, and emits a version-specific sparse exchange. The
owner validates and registers it; no candidate becomes a global inference head.
"""
from __future__ import annotations

from contextlib import ExitStack
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import time
import uuid

from ...duckdb_control.autoencoder_quack import RegistryQuackGateway, RegistryTransportError
from . import autoencoder_runtime_registry as runtimes

SCHEMA = 'autoencoder-formula-fleet/v1'
JOB_SCHEMA = 'autoencoder-formula-job/v1'
MAX_BYTES = 64 * 1024 * 1024
FALSE = {'admitted': False, 'qualified': False, 'formalized': False,
         'promotion_performed': False, 'semantic_correctness_verified': False}
ROOT = Path(__file__).resolve().parents[3]
RUNNER = ROOT / 'scripts/ops/autoencoder/run_formula_fleet.py'
_SOURCE_PATHS = (Path(__file__), RUNNER, Path(__file__).with_name('autoencoder_formula_exchange.py'))
_IMPORTED_SOURCES = {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
                     for path in _SOURCE_PATHS}


class FormulaFleetError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise FormulaFleetError(message)


def raw(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(raw(value)).hexdigest()


def read_bound(path, maximum=MAX_BYTES):
    """One bounded immutable-file observation supplies both value and digest."""
    import stat
    from scripts.ops.legal_ir.run_autoencoder_fleet import _path
    path = _path(path)
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, 'rb') as stream:
        before = os.fstat(stream.fileno())
        require(stat.S_ISREG(before.st_mode) and 0 < before.st_size <= maximum, 'bounded regular formula input required')
        data = stream.read(maximum + 1)
        after = os.fstat(stream.fileno())
    require(len(data) <= maximum and (before.st_size, before.st_mtime_ns, before.st_ctime_ns) ==
            (after.st_size, after.st_mtime_ns, after.st_ctime_ns), 'formula input changed while reading')
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, 'duplicate formula JSON field')
            result[key] = value
        return result
    def reject(value):
        raise FormulaFleetError('nonfinite formula JSON')
    value = json.loads(data, object_pairs_hook=pairs, parse_constant=reject)
    require(type(value) is dict, 'formula JSON object required')
    return value, {'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data)}


def read(path, maximum=MAX_BYTES):
    return read_bound(path, maximum)[0]


def producer_sources():
    current = {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in _SOURCE_PATHS}
    require(current == _IMPORTED_SOURCES, 'loaded formula orchestration source changed')
    return current


def save(path, value):
    data = raw(value)
    require(len(data) <= MAX_BYTES, 'formula fleet artifact exceeds bound')
    with Path(path).open('xb') as stream:
        stream.write(data); stream.flush(); os.fsync(stream.fileno())


def reference(path):
    import stat
    from scripts.ops.legal_ir.run_autoencoder_fleet import _path
    path = _path(path)
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, 'rb') as stream:
        info = os.fstat(stream.fileno())
        require(stat.S_ISREG(info.st_mode) and 0 < info.st_size <= MAX_BYTES, 'bounded regular formula input required')
        data = stream.read(MAX_BYTES + 1)
    require(0 < len(data) <= MAX_BYTES, 'formula input exceeds bound')
    return {'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data)}


def checkpoint_module(domain, version):
    if (domain, version) == ('legal_ir', runtimes.LEARNED_FORMULA_VERSION):
        from . import legal_formula_checkpoint as module
    else:
        require(domain in runtimes.NATIVE_DOMAINS and version == runtimes.NATIVE_FORMULA_VERSION,
                'formula fleet accepts only explicit learned formula runtimes')
        from . import native_formula_checkpoint as module
    return module


def corpus_inputs(domain, corpus):
    if domain == 'legal_ir':
        require(set(corpus) == {'train', 'tuning'}, 'legal corpus requires exactly train and tuning')
        training, tuning = corpus['train'], corpus['tuning']
        require(type(tuning) is list and all(type(x) is dict and type(x.get('source_text')) is str for x in tuning),
                'legal tuning requires source_text records')
        inference = [x['source_text'] for x in tuning]
    else:
        require(set(corpus) == {'training_targets', 'tuning_targets', 'projection_ids'}, 'closed native corpus required')
        training, tuning = corpus['training_targets'], corpus['tuning_targets']
        ids = corpus['projection_ids']
        require(type(ids) is list and ids and all(type(x) is str for x in ids) and len(ids) == len(set(ids)),
                'unique projection IDs required')
        require(type(tuning) is list and len(tuning) * len(ids) <= 128, 'schema projection bound exceeded')
        inference = tuning
    require(type(training) is list and 1 <= len(training) <= 256 and type(tuning) is list and 1 <= len(tuning) <= 32,
            'bounded nonempty training and tuning required')
    return training, tuning, inference


def load_plan(path):
    plan = read(path, 1024 * 1024)
    require(set(plan) == {'schema', 'jobs'} and plan['schema'] == SCHEMA, 'closed formula plan required')
    jobs = plan['jobs']
    require(type(jobs) is list and 1 <= len(jobs) <= 32, 'one to 32 jobs required')
    from scripts.ops.legal_ir.run_autoencoder_fleet import SAFE_ID, _path
    ids = set()
    for job in jobs:
        require(type(job) is dict and set(job) == {'job_id', 'domain', 'runtime_version', 'parent_version_id',
                'corpus', 'corpus_sha256', 'epochs', 'max_seconds', 'lake_timeout_seconds'}, 'closed formula job required')
        require(type(job['job_id']) is str and SAFE_ID.fullmatch(job['job_id']) and job['job_id'] not in ids,
                'unique safe job IDs required')
        ids.add(job['job_id'])
        checkpoint_module(job['domain'], job['runtime_version'])
        require(type(job['parent_version_id']) is str and re.fullmatch(r'sha256:[0-9a-f]{64}', job['parent_version_id']), 'exact registered parent required')
        require(type(job['epochs']) is int and 1 <= job['epochs'] <= 1000, 'bounded epoch count required')
        for key, limit in [('max_seconds', 3600), ('lake_timeout_seconds', 120)]:
            require(type(job[key]) in (int, float) and math.isfinite(job[key]) and 1 <= job[key] <= limit,
                    'invalid ' + key)
        corpus_path = _path(job['corpus'])
        require(str(corpus_path) == job['corpus'], 'canonical absolute corpus path required')
        corpus, corpus_ref = read_bound(corpus_path, 8 * 1024 * 1024)
        require(corpus_ref['sha256'] == job['corpus_sha256'], 'corpus file digest differs')
        corpus_inputs(job['domain'], corpus)
    return plan


class FormulaGateway(RegistryQuackGateway):
    """Only claim/read/renew; candidate acceptance always occurs in the owner."""
    def dispatch(self, envelope):
        if envelope.get('command') not in {'ClaimRun', 'ReadRun', 'ReadVersion', 'RenewLease'}:
            raise RegistryTransportError('formula worker cannot complete or publish an owner run')
        return super().dispatch(envelope)


def execute_assignment(path):
    """Actual private worker path. No DuckDB owner handle or registration here."""
    from ...logic.autoformal.tree_pin import require_workspace_logic_tree
    from ...duckdb_control.autoencoder_quack import RegistryTransportClient
    from .autoencoder_decoded_schema import validate_decoded_outputs
    from . import autoencoder_formula_exchange as exchange
    require_workspace_logic_tree()
    import torch
    torch.set_num_threads(1)
    assignment = read(path, 1024 * 1024)
    require(set(assignment) == {'schema', 'job', 'run_id', 'spec', 'parent', 'parent_artifact', 'corpus',
            'corpus_artifact', 'endpoint', 'token_file', 'output'}, 'closed assignment required')
    require(assignment['schema'] == JOB_SCHEMA, 'unsupported assignment')
    job = assignment['job']; module = checkpoint_module(job['domain'], job['runtime_version'])
    require(assignment['spec'].get('job') == job and assignment['run_id'] == 'formula-' + digest(assignment['spec']),
            'assignment job identity differs')
    require(assignment['spec']['producer_sources'] == producer_sources(), 'worker orchestration source differs')
    parent, parent_ref = read_bound(assignment['parent']); module._validate(parent)
    require(parent_ref == assignment['parent_artifact'], 'parent bytes changed')
    corpus, corpus_ref = read_bound(assignment['corpus'], 8 * 1024 * 1024)
    require(corpus_ref == assignment['corpus_artifact'], 'corpus bytes changed')
    training, tuning, inference = corpus_inputs(job['domain'], corpus)
    output = Path(assignment['output'])
    require(output.is_dir() and not (output / 'result.json').exists(), 'fresh worker output required')
    token_path = Path(assignment['token_file'])
    require(not token_path.is_symlink() and token_path.stat().st_mode & 0o077 == 0 and token_path.stat().st_size <= 1024,
            'private bounded worker token required')
    with RegistryTransportClient(assignment['endpoint'], token_path.read_text().strip()) as client:
        run = client.request('ReadRun', {'run_id': assignment['run_id']}, uuid.uuid4().hex)['run']
        require(run['spec'] == assignment['spec'] and run['base_version_id'] == job['parent_version_id'],
                'owner assignment differs')
        version = client.request('ReadVersion', {'version_id': job['parent_version_id']}, uuid.uuid4().hex)['version']
        envelope = raw({'schema': module.SCHEMA, **parent})
        require(version['artifact'] == assignment['spec']['parent_artifact'] ==
                {'sha256': hashlib.sha256(envelope).hexdigest(), 'bytes': len(envelope)},
                'private checkpoint differs from owner parent artifact')
        claimed = client.request('ClaimRun', {'run_id': assignment['run_id'], 'lease_seconds': 180}, uuid.uuid4().hex)
        lease = [claimed['lease']]; errors = []; stop = threading.Event()
        def renew():
            while not stop.wait(30):
                try:
                    lease[0] = client.request('RenewLease', {'lease': lease[0], 'lease_seconds': 180}, uuid.uuid4().hex)['lease']
                except Exception as error:
                    errors.append(type(error).__name__); return
        heartbeat = threading.Thread(target=renew, daemon=True); heartbeat.start()
        try:
            runtime = runtimes.open_runtime(job['domain'], job['runtime_version'], checkpoint=parent['checkpoint'])
            if job['domain'] != 'legal_ir':
                require(sorted(corpus['projection_ids']) == runtime.checkpoint['feature_space']['projection_ids'], 'projection selection differs')
            options = {}
            if job['domain'] == 'legal_ir':
                options = {key: parent['checkpoint']['config'][key] for key in
                           ('learning_rate', 'batch_size', 'seed', 'hidden_size', 'embedding_dim')}
            result = runtime.train(training, validation_samples=tuning, epochs=job['epochs'], max_seconds=job['max_seconds'], **options)
            require(result['report']['training_executed'], 'deadline reached without optimizer update')
            module._validate(result)
            require(not errors, 'owner lease renewal failed')
            schema = validate_decoded_outputs(runtime, inference, output_directory=output / 'decoded-schema',
                                               timeout_seconds=job['lake_timeout_seconds'])
            save(output / 'result.json', result)
            save(output / 'schema.json', schema)
            # Failed schema observations are retained but never published as a successful worker update.
            require(schema['schema_checks_complete'] is True, 'decoded schema gate failed')
            staged = exchange.stage_formula_update(parent, result, output / 'exchange')
            require(not errors, 'owner lease renewal failed')
            require(assignment['spec']['producer_sources'] == producer_sources(), 'worker source changed before handoff')
        finally:
            stop.set(); heartbeat.join(timeout=65)
        require(not heartbeat.is_alive() and not errors, 'owner heartbeat did not stop cleanly')
        receipt = {'schema': JOB_SCHEMA, 'run_id': assignment['run_id'], 'job_sha256': digest(job),
            'parent_artifact': assignment['parent_artifact'], 'corpus_artifact': assignment['corpus_artifact'],
            'result_artifact': reference(output / 'result.json'), 'schema_artifact': reference(output / 'schema.json'),
            'lease': lease[0], 'exchange': staged, 'training_executed': True,
            'schema_checks_complete': True, 'qualification_scope': 'structural_schema_only', **FALSE}
        save(output / 'worker.json', receipt)
    return receipt


def _read_parent(registry, job):
    return checkpoint_module(job['domain'], job['runtime_version']).load_registered_candidate(registry, job['parent_version_id'])


def prepare_run(registry, job):
    parent = _read_parent(registry, job)
    version = registry.get_version(job['parent_version_id'])
    spec = {'schema': JOB_SCHEMA, 'job': job, 'parent_artifact': version['artifact'],
            'producer_sources': producer_sources(), **FALSE}
    run_id = 'formula-' + digest(spec)
    try:
        run = registry.get_run(run_id)
    except ValueError as error:
        if str(error) != 'unknown run':
            raise
        registry.create_run('create-' + run_id, run_id, version['variant_id'], job['parent_version_id'], spec)
        run = registry.get_run(run_id)
    require(run['spec'] == spec, 'immutable run specification differs')
    return run, parent


def accept_worker(registry, job, run_id, output, *, lease=None):
    """Owner independently checks parent/result and reruns the structural gate."""
    from .autoencoder_decoded_schema import validate_decoded_outputs
    from . import autoencoder_formula_exchange as exchange
    module = checkpoint_module(job['domain'], job['runtime_version'])
    worker = read(output / 'worker.json', 1024 * 1024)
    require(set(worker) == {'schema', 'run_id', 'job_sha256', 'parent_artifact', 'corpus_artifact',
        'result_artifact', 'schema_artifact', 'lease', 'exchange', 'training_executed',
        'schema_checks_complete', 'qualification_scope', *FALSE}, 'closed worker receipt required')
    require(worker['schema'] == JOB_SCHEMA and worker['run_id'] == run_id and worker['job_sha256'] == digest(job)
            and worker['training_executed'] is True and worker['schema_checks_complete'] is True
            and worker['qualification_scope'] == 'structural_schema_only'
            and all(worker.get(k) is False for k in FALSE), 'worker receipt binding or authority differs')
    run = registry.get_run(run_id)
    require(run['spec'].get('job') == job and run['base_version_id'] == job['parent_version_id']
            and worker['lease']['run_id'] == run_id and worker['lease']['worker_id'] == job['job_id']
            and (lease is None or lease['run_id'] == run_id),
            'worker lease or owner job binding differs')
    require(run['spec']['producer_sources'] == producer_sources(), 'owner orchestration source differs')
    result, result_ref = read_bound(output / 'result.json'); module._validate(result)
    require(result_ref == worker['result_artifact'], 'worker result bytes changed')
    require(result['report']['epochs_requested'] == job['epochs'], 'worker used another epoch schedule')
    parent = _read_parent(registry, job)
    require({'sha256': digest(parent), 'bytes': len(raw(parent))} == worker['parent_artifact'], 'numerical parent changed')
    require(reference(output / 'schema.json') == worker['schema_artifact'], 'worker schema observation bytes changed')
    # A worker stops its heartbeat before returning. Give the independently
    # bounded owner replay a lease covering the maximum allowed 128 builds.
    owner_lease = registry.renew_lease('owner-replay-' + run_id + '-' + str(worker['lease']['attempt']),
        worker['lease'] if lease is None else lease,
        lease_seconds=128 * (job['lake_timeout_seconds'] + 5) + 180)['lease']
    corpus, corpus_ref = read_bound(output / 'corpus.json', 8 * 1024 * 1024)
    require(corpus_ref == worker['corpus_artifact'], 'worker corpus changed')
    _, _, inference = corpus_inputs(job['domain'], corpus)
    original, original_ref = read_bound(job['corpus'], 8 * 1024 * 1024)
    require(original_ref['sha256'] == job['corpus_sha256'] and raw(corpus) == raw(original), 'bound source corpus changed')
    # These copied observations cannot replace actual owner-side execution.
    runtime = runtimes.open_runtime(job['domain'], job['runtime_version'], checkpoint=result['checkpoint'])
    owner_schema = validate_decoded_outputs(runtime, inference, output_directory=output / 'owner-decoded-schema',
                                             timeout_seconds=job['lake_timeout_seconds'])
    require(owner_schema['schema_checks_complete'] is True, 'owner decoded schema gate failed')
    save(output / 'owner-schema.json', owner_schema)
    loaded = exchange.load_formula_bundle(worker['exchange']['manifest_path'], parent_result=parent)
    require(raw(loaded['result']) == raw(result), 'sparse replay differs from worker result')
    manifest = loaded['manifest']
    expected_exchange = {'manifest_path': str((output / 'exchange' / Path(worker['exchange']['manifest_path']).name).absolute()),
        'manifest_artifact': loaded['manifest_artifact'], 'path_in_repo': exchange.PREFIX + '/manifests/' + loaded['manifest_artifact']['sha256'] + '.json',
        'binding': loaded['binding'], 'result_artifact': manifest['result'],
        'checkpoint_sha256': loaded['checkpoint_sha256'], 'kind': 'update',
        'payload_bytes': manifest['payload']['bytes'], 'full_result_bytes': manifest['result']['bytes'],
        'replay_verified': True, **exchange.FALSE}
    require(raw(worker['exchange']) == raw(expected_exchange), 'worker exchange metadata differs from verified replay')
    require(run['spec']['producer_sources'] == producer_sources(), 'owner source changed before registration')
    candidate = module.register_candidate(registry, result, output / 'registered', parent_version_id=job['parent_version_id'])
    receipt = {'candidate_version_id': candidate['version_id'], 'candidate_artifact': candidate['artifact'],
        'parent_version_id': job['parent_version_id'], 'job_sha256': digest(job),
        'worker_receipt_artifact': reference(output / 'worker.json'),
        'owner_schema_artifact': reference(output / 'owner-schema.json'),
        'schema_checks_complete': True, 'training_executed': True,
        'independent_branch': True, 'exchange': worker['exchange'], **FALSE}
    staged = registry.stage_artifact(output / 'worker.json')
    complete = registry.complete_run('complete-' + run_id + '-' + str(worker['lease']['attempt']), owner_lease, staged, receipt)
    # CompleteRun's generic version is a control receipt, not a loadable model.
    return {**receipt, 'control_completion': complete}


def publish_completed(registry, job, receipt):
    """Rebind the retained transport bytes to the completed registered branch."""
    from . import autoencoder_formula_exchange as exchange
    module = checkpoint_module(job['domain'], job['runtime_version'])
    result = module.load_registered_candidate(registry, receipt['candidate_version_id'])
    require(receipt['job_sha256'] == digest(job)
            and registry.get_version(receipt['candidate_version_id'])['parent_version_id'] == job['parent_version_id'],
            'completed publication belongs to another job or parent')
    parent = _read_parent(registry, job)
    loaded = exchange.load_formula_bundle(receipt['exchange']['manifest_path'], parent_result=parent)
    require(raw(loaded['result']) == raw(result), 'publication sparse replay differs from completed candidate')
    return exchange.publish_formula_bundle(receipt['exchange']['manifest_path'], parent_result=parent, upload=True)


def run_fleet(args):
    """Run bounded hardware-sized waves; explicit plan retry skips durable jobs."""
    from ...logic.autoformal.tree_pin import require_workspace_logic_tree
    from ...duckdb_control.autoencoder_registry import AutoencoderRegistry
    from ...duckdb_control.autoencoder_quack import WorkerScope
    from . import autoencoder_capacity as sizing
    from .autoencoder_daemon_resources import DaemonResourceReservation
    from scripts.ops.legal_ir.run_autoencoder_fleet import (
        storage_capacity, _path, process_snapshot, collect_owned, stop_owned, _write)
    require_workspace_logic_tree()
    import torch
    torch.set_num_threads(1)
    plan = load_plan(args.plan_file)
    state = _path(args.state_directory)
    ledger = _path(args.resource_ledger)
    ledger_data = read(ledger, 8 * 1024 * 1024)
    roots = [row['path'] for row in ledger_data['roots']]
    require(any(state == Path(p) or Path(p) in state.parents for p in roots), 'state outside existing resource roots')
    for path in (args.registry, args.artifact_root):
        checked = _path(path)
        require(any(checked == Path(p) or Path(p) in checked.parents for p in roots), 'registry/artifacts outside resource roots')
    storage = storage_capacity(ledger, state)
    scheduler = sizing.scheduler_capacity(sizing.scheduler_snapshot())
    capacity = sizing.capacity_plan(max_workers=args.max_workers, memory_budget_mb=args.memory_budget_mb,
        pending_count=len(plan['jobs']), per_worker_memory_mb=2048, per_worker_cpu=2, reserve_mb=1024,
        reserve_cpu_slots=1, storage_headroom_bytes=max(0, storage['headroom_bytes']-args.worker_storage_bytes),
        per_worker_storage_bytes=args.worker_storage_bytes, scheduler_available_cpu=scheduler['cpu_slots'],
        scheduler_available_memory_mb=scheduler['memory_mb'], scheduler_available_process_slots=scheduler['child_process_slots'],
        per_worker_process_slots=3, reserve_process_slots=2)
    observed = {'schema': SCHEMA, 'capacity': capacity, 'storage': storage, 'scheduler': scheduler,
                'plan_sha256': digest(plan), 'run_mode': 'independent_formula_branches', **FALSE}
    if args.plan_only:
        return {**observed, 'status': 'planned', 'jobs': []}
    import ctypes
    require(ctypes.CDLL(None, use_errno=True).prctl(36, 1, 0, 0, 0) == 0, 'Linux child-subreaper setup failed')
    state.mkdir(parents=True, exist_ok=True)
    attempts = state / 'attempts'; attempts.mkdir(exist_ok=True)
    # Restart never launches over an earlier still-running owned group.
    prior_processes = list(attempts.glob('*/process.json'))
    require(len(prior_processes) <= 1024, 'attempt inventory bound exceeded')
    snapshot = process_snapshot()
    for file in prior_processes:
        stored = read(file, 64 * 1024)
        known = {int(pid): birth for pid, birth in stored['owned_processes'].items()}
        require(not collect_owned(known, snapshot), 'prior formula worker is still alive')
    results = []
    owner_directory = state / ('owner-' + uuid.uuid4().hex); owner_directory.mkdir()
    # The owner serializes only acceptance/registration. Each worker has a
    # separately charged isolated process group and immutable private inputs.
    with DaemonResourceReservation(ledger, roots=roots, storage_bytes=args.worker_storage_bytes,
            memory_mb=1024, cpu_slots=1, child_process_slots=2, ledger_lock_timeout_seconds=30) as owner_budget:
        owner_budget.check_usage(owner_directory)
        with AutoencoderRegistry(args.registry, args.artifact_root) as registry:
            queue = []
            for job in plan['jobs']:
                run, _ = prepare_run(registry, job)
                if run['status'] == 'completed':
                    candidate_job = {**job, 'parent_version_id': run['result']['candidate_version_id']}
                    _read_parent(registry, candidate_job)
                    receipt = dict(run['result'])
                    if args.upload:
                        receipt['publication'] = publish_completed(registry, job, receipt)
                    results.append({'job_id': job['job_id'], 'status': 'already_completed', **receipt})
                else:
                    queue.append((job, run))
            while queue and capacity['workers'] > 0:
                active = []
                finished = []
                wave_completed = False
                selected, queue = queue[:capacity['workers']], queue[capacity['workers']:]
                with ExitStack() as stack:
                    try:
                        for job, run in selected:
                            output = attempts / (run['run_id'] + '-' + uuid.uuid4().hex)
                            output.mkdir(mode=0o700)
                            budget = stack.enter_context(DaemonResourceReservation(ledger, roots=roots,
                                storage_bytes=args.worker_storage_bytes, memory_mb=2048, cpu_slots=2,
                                child_process_slots=3, ledger_lock_timeout_seconds=30))
                            parent = _read_parent(registry, job)
                            save(output / 'parent.json', parent)
                            corpus, corpus_ref = read_bound(job['corpus'], 8 * 1024 * 1024)
                            require(corpus_ref['sha256'] == job['corpus_sha256'], 'source corpus changed')
                            save(output / 'corpus.json', corpus)
                            gateway = stack.enter_context(FormulaGateway(registry,
                                WorkerScope(job['job_id'], frozenset({run['run_id']})), enable_prototype=True))
                            connection = gateway.connection_parameters()
                            token_file = output / 'token'
                            fd = os.open(token_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                            with os.fdopen(fd, 'w') as stream:
                                stream.write(connection['token']); stream.flush(); os.fsync(stream.fileno())
                            assignment = {'schema': JOB_SCHEMA, 'job': job, 'run_id': run['run_id'], 'spec': run['spec'],
                                'parent': str(output / 'parent.json'), 'parent_artifact': reference(output / 'parent.json'),
                                'corpus': str(output / 'corpus.json'), 'corpus_artifact': reference(output / 'corpus.json'),
                                'endpoint': connection['endpoint'], 'token_file': str(token_file), 'output': str(output)}
                            save(output / 'assignment.json', assignment)
                            log = stack.enter_context((output / 'worker.log').open('xb'))
                            env = os.environ.copy(); env.update(PYTHONPATH=str(ROOT), CUDA_VISIBLE_DEVICES='',
                                PYTHONDONTWRITEBYTECODE='1', HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1')
                            child = subprocess.Popen([sys.executable, str(RUNNER), 'worker', '--assignment', str(output / 'assignment.json')],
                                env=env, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
                            try:
                                snap = process_snapshot(); require(child.pid in snap, 'worker exited before process binding')
                                known = {child.pid: snap[child.pid]['birth']}
                                nchecks = len(corpus.get('tuning', corpus.get('tuning_targets', []))) * len(corpus.get('projection_ids', [None]))
                                entry = {'job': job, 'run': run, 'output': output, 'child': child, 'known': known,
                                         'budget': budget, 'started': time.monotonic(), 'last_check': 0,
                                         'saved_processes': dict(known),
                                         'deadline_seconds': job['max_seconds'] + nchecks * (job['lake_timeout_seconds'] + 5) + 120}
                                active.append(entry)
                            except BaseException:
                                # Popen owns this unreaped process/group even
                                # if /proc binding itself fails immediately.
                                import signal
                                if child.poll() is None:
                                    os.killpg(child.pid, signal.SIGTERM)
                                    try:
                                        child.wait(timeout=5)
                                    except subprocess.TimeoutExpired:
                                        os.killpg(child.pid, signal.SIGKILL); child.wait(timeout=5)
                                raise
                            _write(output / 'process.json', {'owned_processes': known})
                            budget.check_usage(output, child.pid)
                        while active:
                            snapshot = process_snapshot()
                            for entry in list(active):
                                child, output, budget = entry['child'], entry['output'], entry['budget']
                                collect_owned(entry['known'], snapshot)
                                if entry['known'] != entry['saved_processes']:
                                    _write(output / 'process.json', {'owned_processes': entry['known']})
                                    entry['saved_processes'] = dict(entry['known'])
                                job = entry['job']
                                if time.monotonic() - entry['started'] > entry['deadline_seconds']:
                                    raise FormulaFleetError('worker whole-job deadline exceeded')
                                require((output / 'worker.log').stat().st_size <= 8 * 1024 * 1024, 'worker log bound exceeded')
                                if time.monotonic() - entry['last_check'] >= 5:
                                    budget.check_usage(output, child.pid); entry['last_check'] = time.monotonic()
                                if child.poll() is None:
                                    continue
                                child.wait()
                                if collect_owned(entry['known'], process_snapshot()):
                                    stop_owned(child, entry['known'])
                                require(child.returncode == 0, 'worker failed; inspect ' + str(output / 'worker.log'))
                                worker = read(output / 'worker.json', 1024 * 1024)
                                entry['owner_lease'] = registry.renew_lease('owner-queue-' + uuid.uuid4().hex,
                                    worker['lease'], lease_seconds=86400)['lease']
                                finished.append(entry)
                                active.remove(entry)
                            if active:
                                time.sleep(.1)
                        # Keep every live worker monitored until its process
                        # group exits. Only then run potentially slow owner
                        # schema replays, renewing all queued leases each time.
                        for index, entry in enumerate(finished):
                            for pending in finished[index:]:
                                pending['owner_lease'] = registry.renew_lease('owner-wait-' + uuid.uuid4().hex,
                                    pending['owner_lease'], lease_seconds=86400)['lease']
                            job, output, budget = entry['job'], entry['output'], entry['budget']
                            receipt = accept_worker(registry, job, entry['run']['run_id'], output, lease=entry['owner_lease'])
                            receipt['publication'] = (publish_completed(registry, job, receipt) if args.upload
                                                      else {'uploaded': False, 'dry_run': True})
                            save(output / 'owner-receipt.json', receipt)
                            budget.account_external_bytes('registry-candidate', receipt['candidate_artifact']['bytes'])
                            budget.finalize(output, artifacts_durable=True)
                            results.append({'job_id': job['job_id'], 'status': 'completed', **receipt})
                        wave_completed = True
                    finally:
                        for entry in active:
                            stop_owned(entry['child'], entry['known'])
                            # Failed attempts retain their storage claim for explicit recovery.
                        _write(state / 'last-run.json', {**observed, 'jobs': results, 'finished': wave_completed})
            owner_budget.account_external_bytes('registry-file', Path(args.registry).stat().st_size)
        save(owner_directory / 'report.json', {**observed, 'jobs': results})
        owner_budget.finalize(owner_directory, artifacts_durable=True)
    return {**observed, 'status': 'no_capacity' if queue else 'completed', 'jobs': results, 'hub_upload_requested': args.upload}
