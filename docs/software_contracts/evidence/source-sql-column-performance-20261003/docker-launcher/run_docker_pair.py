"""External SQL diagnostic; ordinary deployment, no Source384 qualification."""
import asyncio
import hashlib
import json
from pathlib import Path
import shlex
import time
import traceback

B = Path(__file__).parent
ARCHIVE = B.parent / 'source384-docker-reconstruction-20261003/bundle'
ARCHIVE_SHA = '43ba7c9bc830b9c6c684589db15ddad25a37339014a5287d41a962c10d98f9c3'
TASK = Path('/home/barberb/lift_coding/.benchmarks/terminal-bench-2/fix-code-vulnerability')
PROFILE = 'source384-5cpu-12gib@1'


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def save(path, value):
    with Path(path).open('x') as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write('\n')


def verify_inputs():
    pins = json.loads((B / 'docker-inputs.json').read_text())
    if set(pins) != {'corpus', 'replay', 'candidate'}:
        raise ValueError('exact diagnostic inputs required')
    for name, bound in [('corpus', 32 * 1024 * 1024), ('replay', 65536), ('candidate', 65536)]:
        row = pins[name]
        path = Path(row['path'])
        if path.is_symlink() or not path.is_file() or path.stat().st_size > bound or digest(path) != row['sha256']:
            raise ValueError('diagnostic input digest or bound differs')
    manifest = json.loads((ARCHIVE / 'manifest.json').read_text())
    if manifest['archive_sha256'] != ARCHIVE_SHA or digest(ARCHIVE / 'runtime.tar.gz') != ARCHIVE_SHA:
        raise ValueError('frozen archive differs')
    roots = {'source': Path('/home/barberb/lift_coding/.worktrees/ir-release-accelerate-20261002'),
             'datasets': Path('/home/barberb/lift_coding/.worktrees/ir-release-datasets-20261002')}
    files = {r['path']: r['sha256'] for r in manifest['files']}
    for name in ('prepared-a-pins.json', 'frozen-d-pins.json'):
        for row in json.loads((ARCHIVE.parent / name).read_text()):
            prefix, relative = row['path'].split('/', 1)
            if files[row['path']] != row['sha256'] or digest(roots[prefix] / relative) != row['sha256']:
                raise ValueError('live producer differs from frozen archive')
    corpus = json.loads(Path(pins['corpus']['path']).read_text())
    for module, sha in corpus['producer'].items():
        if files['datasets/' + module.replace('.', '/') + '.py'] != sha:
            raise ValueError('corpus producer differs from archive')
    return pins


async def run():
    from benchmarks.agent_supervisor.container_coding import terminal_deployment as deployment
    from benchmarks.agent_supervisor.container_coding.terminal_source384_qualification import observe_resources
    from ipfs_accelerate_py.agent_supervisor.runtime.source384_config import _regular_bytes
    if json.loads((B / 'docker-go.json').read_text()).get('root_go') is not True:
        raise ValueError('root diagnostic GO required')
    pins = verify_inputs()
    corpus_producer = json.loads(Path(pins['corpus']['path']).read_text())['producer']
    save(B / 'docker-producer-verification.json', {'inputs': pins, 'archive_sha256': ARCHIVE_SHA})
    original = deployment.deploy_supervisor
    reports = []

    async def with_sql(environment, **kwargs):
        deployed = await original(environment, **kwargs)
        resources = B / 'docker-resources-before'
        resources.mkdir()
        await observe_resources(environment, output=resources, profile=PROFILE)
        remote = deployment.ROOT + '/state/sql-replay'
        response = await environment.exec(command='mkdir -m 0700 ' + shlex.quote(remote),
            cwd='/app', user='supervisor', env=deployment.runtime_environment(), timeout_sec=30)
        if response.return_code:
            raise RuntimeError('private diagnostic directory creation failed')
        remote_inputs = {'corpus': remote + '/corpus.json', 'replay': remote + '/sql_replay.py',
                         'candidate': remote + '/vector_candidate.py'}
        for name, target in remote_inputs.items():
            await environment.upload_file(Path(pins[name]['path']), target)
        for mode in ('baseline', 'candidate'):
            args = [deployment.PYTHON, '-P', remote_inputs['replay'], 'replay',
                    '--corpus', remote_inputs['corpus'], '--expected-sha256', pins['corpus']['sha256'],
                    '--output', remote + '/' + mode]
            if mode == 'candidate':
                args += ['--candidate-path', remote_inputs['candidate'], '--candidate-sha256', pins['candidate']['sha256']]
            response = None
            collected = False
            try:
                response = await environment.exec(command=shlex.join(args), cwd='/app', user='supervisor',
                    env=deployment.runtime_environment(), timeout_sec=300)
                (B / ('docker-' + mode + '.stdout')).write_text(response.stdout or '')
                (B / ('docker-' + mode + '.stderr')).write_text(response.stderr or '')
                save(B / ('docker-' + mode + '-status.json'), {'return_code': response.return_code})
            finally:
                target = B / ('docker-' + mode + '-receipt.json')
                try:
                    await asyncio.wait_for(environment.download_file(remote + '/' + mode + '/receipt.json', target), 30)
                    row = json.loads(_regular_bytes(target.resolve(strict=True), 1024 * 1024))
                    reports.append(row)
                    collected = True
                finally:
                    save(B / ('docker-' + mode + '-collection.json'), {'receipt_collected': collected})
            if response.return_code or row.get('qualified') is not True or row.get('diagnostic_only') is not True:
                raise RuntimeError('SQL-only replay failed; see retained receipt')
            if row['corpus_sha256'] != pins['corpus']['sha256'] or row['harness_sha256'] != pins['replay']['sha256']:
                raise ValueError('actual replay inputs differ')
            expected_mode = 'native_multi_values_baseline' if mode == 'baseline' else 'external_column_unnest_candidate'
            if (row['mode'] != expected_mode or row['projections'] != 31 or len(row['tables']) != 13
                    or row['timeout_seconds'] != 90 or row['all_table_parity'] is not True
                    or row['cold_native_replay'] is not True
                    or row['producer_before'] != corpus_producer or row['producer_after'] != corpus_producer):
                raise ValueError('replay population, checks or producers differ')
            if ((mode == 'baseline' and row['external_candidate'] is not None)
                    or (mode == 'candidate' and row['external_candidate']['sha256'] != pins['candidate']['sha256'])):
                raise ValueError('replay implementation selection differs')
            if (row['model_loads'] != 0 or row['provider_calls'] != 0 or row['training_steps'] != 0
                    or row['neural_inference'] is not False or row['production_qualification'] is not False):
                raise ValueError('diagnostic scope differs')
        if reports[0]['tables'] != reports[1]['tables'] or reports[0]['projections'] != 31:
            raise ValueError('paired corpus parity differs')
        verify_inputs()
        return deployed

    start = time.monotonic()
    result = {'schema': 'source384-docker-sql-pair@1', 'diagnostic_only': True,
              'production_qualification': False, 'benchmark_result': False, 'source384_context_requested': False,
              'archive_sha256': ARCHIVE_SHA, 'resource_profile': PROFILE, 'pair_passed': False}
    deployment.deploy_supervisor = with_sql
    try:
        returned = await asyncio.wait_for(deployment.qualify_original_container(task_dir=TASK,
            archive_dir=ARCHIVE, output=B / 'docker-01', install_codex=False,
            resource_profile=PROFILE, source384_context=False), 2300)
        save(B / 'raw-deployment-return.json', returned)
        result['pair_passed'] = len(reports) == 2
    except BaseException as exc:
        traceback.print_exc()
        result.update(error_type=type(exc).__name__, error=str(exc)[:2048])
    finally:
        deployment.deploy_supervisor = original
        result['seconds'] = time.monotonic() - start
        save(B / 'docker-pair-result.json', result)
    return result


if __name__ == '__main__':
    raise SystemExit(0 if asyncio.run(run())['pair_passed'] else 1)
