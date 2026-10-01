"""Formula branch identity, actual worker training, and owner-only acceptance."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import uuid

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_formula_fleet as fleet

ROOT = Path(fleet.__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location('_formula_fleet_fixtures', ROOT / 'tests/unit/optimizers/logic_theorem_optimizer/test_native_formula_training.py')
fixtures = importlib.util.module_from_spec(spec); spec.loader.exec_module(fixtures)


@pytest.fixture
def one_thread():
    import torch
    old = torch.get_num_threads(); torch.set_num_threads(1)
    yield
    torch.set_num_threads(old)


def seeded(tmp_path, registry, domain='intent_ir'):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import native_formula_checkpoint as storage
    cp, training, tuning = fixtures._build(domain)
    result = fixtures.learner.train_native_formula(cp, training, tuning, epochs=35, max_seconds=60)
    saved = storage.register_candidate(registry, result, tmp_path / ('base-' + domain))
    corpus = tmp_path / (domain + '-corpus.json')
    fleet.save(corpus, {'training_targets': training, 'tuning_targets': tuning,
                        'projection_ids': cp['feature_space']['projection_ids']})
    job = {'job_id': domain + '-branch', 'domain': domain, 'runtime_version': 'native_formula_v1',
        'parent_version_id': saved['version_id'], 'corpus': str(corpus),
        'corpus_sha256': fleet.reference(corpus)['sha256'], 'epochs': 1, 'max_seconds': 60,
        'lake_timeout_seconds': 20}
    return job, result


def test_plan_is_closed_and_hash_bound(tmp_path):
    corpus = tmp_path / 'corpus.json'
    fleet.save(corpus, {'training_targets': [{}], 'tuning_targets': [{}], 'projection_ids': ['x']})
    job = {'job_id': 'one', 'domain': 'intent_ir', 'runtime_version': 'native_formula_v1',
        'parent_version_id': 'sha256:' + '1' * 64, 'corpus': str(corpus), 'corpus_sha256': fleet.reference(corpus)['sha256'],
        'epochs': 1, 'max_seconds': 10, 'lake_timeout_seconds': 20}
    plan = {'schema': fleet.SCHEMA, 'jobs': [job]}
    path = tmp_path / 'plan.json'; fleet.save(path, plan)
    assert fleet.load_plan(path) == plan
    path.write_text(json.dumps({**plan, 'admitted': True}))
    with pytest.raises(ValueError, match='closed formula plan'):
        fleet.load_plan(path)
    path.write_text(json.dumps(plan)); corpus.write_text('{}')
    with pytest.raises(ValueError, match='digest differs'):
        fleet.load_plan(path)


@pytest.mark.parametrize('field,value', [('epochs', True), ('max_seconds', float('nan')),
    ('runtime_version', 'legacy_v1'), ('domain', 'unknown')])
def test_plan_rejects_wrong_runtime_and_unbounded_settings(tmp_path, field, value):
    corpus = tmp_path / 'corpus.json'
    fleet.save(corpus, {'training_targets': [{}], 'tuning_targets': [{}], 'projection_ids': ['x']})
    job = {'job_id': 'one', 'domain': 'intent_ir', 'runtime_version': 'native_formula_v1',
        'parent_version_id': 'sha256:' + '1' * 64, 'corpus': str(corpus), 'corpus_sha256': fleet.reference(corpus)['sha256'],
        'epochs': 1, 'max_seconds': 10, 'lake_timeout_seconds': 20, field: value}
    path = tmp_path / 'plan.json'; path.write_text(json.dumps({'schema': fleet.SCHEMA, 'jobs': [job]}))
    with pytest.raises(ValueError):
        fleet.load_plan(path)


def test_single_owner_run_identity_is_stable_and_branch_specific(tmp_path, one_thread):
    from ipfs_datasets_py.duckdb_control.autoencoder_registry import AutoencoderRegistry
    with AutoencoderRegistry(tmp_path / 'control.duckdb', tmp_path / 'artifacts') as registry:
        job, parent = seeded(tmp_path, registry)
        run, loaded = fleet.prepare_run(registry, job)
        assert loaded == parent
        assert fleet.prepare_run(registry, job)[0] == run
        other = fleet.prepare_run(registry, {**job, 'job_id': 'another-branch'})[0]
        assert other['run_id'] != run['run_id']
        assert other['base_version_id'] == run['base_version_id']
        assert registry.resolve_head(run['variant_id'], 'main') is None


@pytest.mark.skipif(os.environ.get('IPFS_DATASETS_RUN_NATIVE_STORAGE_PROBE') != '1', reason='installed native Quack opt-in')
def test_real_two_workers_share_owner_train_and_owner_replay(tmp_path, one_thread, monkeypatch):
    from contextlib import ExitStack
    from ipfs_datasets_py.duckdb_control.autoencoder_registry import AutoencoderRegistry
    from ipfs_datasets_py.duckdb_control.autoencoder_quack import WorkerScope, RegistryTransportClient
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import native_formula_checkpoint as storage
    children = []
    with ExitStack() as stack:
        registry = stack.enter_context(AutoencoderRegistry(tmp_path / 'control.duckdb', tmp_path / 'artifacts'))
        jobs = [seeded(tmp_path, registry, d) for d in ['intent_ir', 'ui_ux_ir']]
        for job, parent in jobs:
            run, _ = fleet.prepare_run(registry, job)
            output = tmp_path / job['job_id']; output.mkdir()
            fleet.save(output / 'parent.json', parent)
            fleet.save(output / 'corpus.json', fleet.read(job['corpus']))
            gateway = stack.enter_context(fleet.FormulaGateway(registry,
                WorkerScope(job['job_id'], frozenset({run['run_id']})), enable_prototype=True))
            connection = gateway.connection_parameters()
            token = output / 'token'; token.write_text(connection['token']); token.chmod(0o600)
            with RegistryTransportClient(connection['endpoint'], connection['token']) as client:
                with pytest.raises(Exception, match='cannot complete'):
                    client.request('CompleteRun', {}, uuid.uuid4().hex)
            assignment = {'schema': fleet.JOB_SCHEMA, 'job': job, 'run_id': run['run_id'], 'spec': run['spec'],
                'parent': str(output / 'parent.json'), 'parent_artifact': fleet.reference(output / 'parent.json'),
                'corpus': str(output / 'corpus.json'), 'corpus_artifact': fleet.reference(output / 'corpus.json'),
                'endpoint': connection['endpoint'], 'token_file': str(token), 'output': str(output)}
            fleet.save(output / 'assignment.json', assignment)
            env = {**os.environ, 'PYTHONPATH': str(ROOT), 'PYTHONDONTWRITEBYTECODE': '1', 'CUDA_VISIBLE_DEVICES': '', 'HF_HUB_OFFLINE': '1'}
            child = subprocess.Popen([sys.executable, str(fleet.RUNNER), 'worker', '--assignment', str(output / 'assignment.json')],
                cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
            children.append((child, job, run, output, parent))
        try:
            for child, job, run, output, parent in children:
                stdout, stderr = child.communicate(timeout=90)
                assert child.returncode == 0, stderr[-4000:] + stdout[-1000:]
                original = (output / 'worker.json').read_bytes()
                forged = json.loads(original); forged['unexpected_authority'] = True
                (output / 'worker.json').write_text(json.dumps(forged))
                with pytest.raises(ValueError, match='closed worker receipt'):
                    fleet.accept_worker(registry, job, run['run_id'], output)
                forged = json.loads(original); forged['lease']['run_id'] = 'another-run'
                (output / 'worker.json').write_text(json.dumps(forged))
                with pytest.raises(ValueError, match='lease or owner job binding'):
                    fleet.accept_worker(registry, job, run['run_id'], output)
                (output / 'worker.json').write_bytes(original)
                accepted = fleet.accept_worker(registry, job, run['run_id'], output)
                assert accepted['schema_checks_complete'] and accepted['training_executed']
                assert all(accepted[k] is False for k in fleet.FALSE)
                loaded = storage.load_registered_candidate(registry, accepted['candidate_version_id'])
                assert loaded['checkpoint']['latest']['progress']['optimizer_steps'] == 72
                assert loaded['checkpoint']['parent_checkpoint_sha256'] == fixtures.learner.checkpoint_digest(parent['checkpoint'])
                assert registry.get_run(run['run_id'])['status'] == 'completed'
                assert registry.resolve_head(run['variant_id'], 'main') is None
                from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_formula_exchange as exchange
                sibling = copy.deepcopy(loaded)
                sibling['report']['elapsed_seconds'] += 1
                staged = exchange.stage_formula_update(parent, sibling, output / 'sibling-exchange')
                def forbidden(*args, **kwargs):
                    pytest.fail('network publication must not be reached for a substituted branch')
                monkeypatch.setattr(exchange, 'publish_formula_bundle', forbidden)
                with pytest.raises(ValueError, match='publication sparse replay differs'):
                    fleet.publish_completed(registry, job, {**accepted, 'exchange': staged})
        finally:
            for child, *_ in children:
                if child.poll() is None:
                    os.killpg(child.pid, 15); child.wait(timeout=5)


def test_bounded_snapshot_rejects_duplicate_fields_and_symlinks(tmp_path):
    path = tmp_path / 'data.json'; path.write_text('{"value":1,"value":2}')
    with pytest.raises(ValueError, match='duplicate'):
        fleet.read_bound(path)
    path.write_text('{"value":1}')
    link = tmp_path / 'alias.json'; link.symlink_to(path)
    with pytest.raises(ValueError, match='symlink'):
        fleet.read_bound(link)
    with pytest.raises(ValueError, match='bounded'):
        fleet.read_bound(path, 1)


@pytest.mark.skipif(os.environ.get('IPFS_DATASETS_RUN_NATIVE_STORAGE_PROBE') != '1', reason='installed native Quack opt-in')
def test_resource_backed_cli_finishes_and_completed_retry_does_not_retrain(tmp_path, one_thread, monkeypatch):
    from ipfs_datasets_py.duckdb_control.autoencoder_registry import AutoencoderRegistry
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_daemon_resources import DaemonResourceReservation
    # Exercise real reservations in an isolated test namespace. A shared host
    # can correctly defer production workers while another campaign owns CPU;
    # this deterministic integration test does not assert host admission.
    monkeypatch.setenv('IPFS_DATASETS_RESOURCE_SCHEDULER_PATH', str(tmp_path / 'test-scheduler.json'))
    ledger = tmp_path / 'resources.json'; empty = tmp_path / 'ledger-initializer'; empty.mkdir()
    with DaemonResourceReservation(ledger, roots=[tmp_path], storage_bytes=1_000_000, memory_mb=1) as budget:
        budget.check_usage(empty); budget.finalize(empty, artifacts_durable=True)
    registry_path = tmp_path / 'owner.duckdb'; artifacts = tmp_path / 'artifacts'
    with AutoencoderRegistry(registry_path, artifacts) as owner:
        jobs = [seeded(tmp_path, owner, domain)[0] for domain in ['intent_ir', 'ui_ux_ir']]
    plan = tmp_path / 'plan.json'; fleet.save(plan, {'schema': fleet.SCHEMA, 'jobs': jobs})
    state = tmp_path / 'state'
    command = [sys.executable, str(fleet.RUNNER), 'run', '--plan-file', str(plan), '--registry', str(registry_path),
        '--artifact-root', str(artifacts), '--state-directory', str(state), '--resource-ledger', str(ledger),
        '--worker-storage-bytes', '128000000', '--max-workers', '2', '--memory-budget-mb', '8192']
    env = {**os.environ, 'PYTHONPATH': str(ROOT), 'PYTHONDONTWRITEBYTECODE': '1', 'CUDA_VISIBLE_DEVICES': '', 'HF_HUB_OFFLINE': '1'}
    for attempt in range(3):
        current = command if attempt < 2 else [*command[:-1], '1024']
        result = subprocess.run(current, cwd=ROOT, env=env, capture_output=True, text=True, timeout=120)
        assert result.returncode == 0, result.stderr[-6000:] + result.stdout[-2000:]
        report = json.loads(result.stdout.splitlines()[-1])
        assert report['status'] == 'completed'
        assert report['capacity']['workers'] == (2 if attempt < 2 else 0)
        assert {job['status'] for job in report['jobs']} == ({'completed'} if attempt == 0 else {'already_completed'})
        assert all(job['schema_checks_complete'] and not job['admitted'] and not job['qualified'] for job in report['jobs'])
        assert len(list((state / 'attempts').glob('*/worker.json'))) == 2
    assert all(row['status'] == 'released' for row in json.loads(ledger.read_text())['reservations'].values())
