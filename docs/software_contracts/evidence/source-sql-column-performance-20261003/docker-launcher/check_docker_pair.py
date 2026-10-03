"""Light external-wrapper controls: no container, SQL, model or subprocess."""
import asyncio
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import shlex
import sys
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

B = Path(__file__).parent
spec = importlib.util.spec_from_file_location('reviewed_docker_sql_pair', B / 'run_docker_pair.py')
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)
PINS = json.loads((B / 'docker-inputs.json').read_text())
RECEIPTS = {mode: json.loads((B / ('host-' + mode + '-01/receipt.json')).read_text())
            for mode in ('baseline', 'candidate')}


def module_tree(names):
    modules = {}
    for name in names:
        parts = name.split('.')
        for i in range(1, len(parts) + 1):
            key = '.'.join(parts[:i])
            if key not in modules:
                modules[key] = ModuleType(key)
                modules[key].__path__ = []
            if i > 1:
                setattr(modules['.'.join(parts[:i - 1])], parts[i - 1], modules[key])
    return modules


class DockerPairControls(unittest.TestCase):
    def exercise(self, *, alter=None, exec_error=False, download_error=False, resource_error=False):
        receipts = copy.deepcopy(RECEIPTS)
        if alter:
            alter(receipts)
        calls, cleanup = [], []
        deployment_name = 'benchmarks.agent_supervisor.container_coding.terminal_deployment'
        resources_name = 'benchmarks.agent_supervisor.container_coding.terminal_source384_qualification'
        reader_name = 'ipfs_accelerate_py.agent_supervisor.runtime.source384_config'
        modules = module_tree((deployment_name, resources_name, reader_name))
        deployment = modules[deployment_name]
        deployment.ROOT, deployment.PYTHON = '/opt/ipfs-supervisor', '/opt/python'
        deployment.runtime_environment = lambda: {'BOUND_ENV': '1'}

        class Environment:
            async def upload_file(self, path, target):
                calls.append(('upload', str(path), target))

            async def exec(self, **kwargs):
                calls.append(('exec', kwargs))
                self.last = kwargs
                if exec_error and ' replay ' in kwargs['command']:
                    raise RuntimeError('mock child command failed')
                return SimpleNamespace(return_code=0, stdout='', stderr='')

            async def download_file(self, remote, local):
                calls.append(('download', remote))
                if download_error:
                    raise OSError('mock receipt collection failed')
                mode = 'candidate' if '/candidate/' in remote else 'baseline'
                Path(local).write_text(json.dumps(receipts[mode]))

        environment = Environment()

        async def original(_environment, **kwargs):
            calls.append(('deploy', kwargs))
            return {'deployed': True}

        async def qualify(**kwargs):
            calls.append(('qualify', kwargs))
            try:
                value = await deployment.deploy_supervisor(environment, archive_dir=kwargs['archive_dir'])
                return {'qualified': True, 'source384_requested': False, 'deployment': value}
            finally:
                cleanup.append('native_environment_stop_delete')

        async def observe(_environment, **kwargs):
            calls.append(('observe_resources', kwargs))
            if resource_error:
                raise ValueError('mock cgroup mismatch')
            return {'limits_verified': True}

        def read_regular(path, maximum):
            value = Path(path).read_bytes()
            if len(value) > maximum:
                raise ValueError('mock bounded collection exceeds limit')
            return value

        deployment.deploy_supervisor = original
        deployment.qualify_original_container = qualify
        modules[resources_name].observe_resources = observe
        modules[reader_name]._regular_bytes = read_regular
        with tempfile.TemporaryDirectory(prefix='sql-pair-wrapper-') as temporary:
            output = Path(temporary)
            (output / 'docker-go.json').write_text('{"root_go":true}')
            with patch.dict(sys.modules, modules), patch.object(runner, 'B', output), \
                 patch.object(runner, 'verify_inputs', return_value=PINS), \
                 patch.object(runner.traceback, 'print_exc'):
                result = asyncio.run(runner.run())
            self.assertIs(deployment.deploy_supervisor, original)
            self.assertEqual(cleanup, ['native_environment_stop_delete'])
            collections = {p.name: json.loads(p.read_text()) for p in output.glob('*-collection.json')}
            persisted = json.loads((output / 'docker-pair-result.json').read_text())
            self.assertEqual(result, persisted)
        return result, calls, collections

    def test_real_frozen_inputs_and_archive_match(self):
        self.assertEqual(runner.verify_inputs(), PINS)

    def test_success_keeps_resource_limits_modes_bounds_and_scope(self):
        result, calls, collections = self.exercise()
        self.assertTrue(result['pair_passed'])
        self.assertFalse(result['production_qualification'])
        self.assertFalse(result['source384_context_requested'])
        self.assertTrue(all(v['receipt_collected'] for v in collections.values()))
        config = next(row[1] for row in calls if row[0] == 'qualify')
        self.assertEqual(config['resource_profile'], 'source384-5cpu-12gib@1')
        self.assertIs(config['source384_context'], False)
        self.assertIs(config['install_codex'], False)
        commands = [row[1] for row in calls if row[0] == 'exec']
        self.assertEqual([row['timeout_sec'] for row in commands], [30, 300, 300])
        for row in commands:
            self.assertEqual(row['user'], 'supervisor')
            self.assertEqual(row['env'], {'BOUND_ENV': '1'})
        baseline, candidate = [shlex.split(row['command']) for row in commands[1:]]
        self.assertNotIn('--candidate-path', baseline)
        self.assertIn('--candidate-path', candidate)
        self.assertIn(PINS['candidate']['sha256'], candidate)

    def test_wrong_arm_receipt_cannot_pass(self):
        result, _, _ = self.exercise(alter=lambda rows: rows['candidate'].update(mode='native_multi_values_baseline'))
        self.assertFalse(result['pair_passed'])

    def test_wrong_candidate_or_producer_cannot_pass(self):
        for field in ('candidate', 'producer'):
            def alter(rows):
                if field == 'candidate':
                    rows['candidate']['external_candidate']['sha256'] = '0' * 64
                else:
                    rows['baseline']['producer_after'] = {}
            with self.subTest(field=field):
                result, _, _ = self.exercise(alter=alter)
                self.assertFalse(result['pair_passed'])

    def test_changed_population_deadline_parity_or_scope_cannot_pass(self):
        for field, value in [('projections', 30), ('timeout_seconds', 91),
                             ('cold_native_replay', False), ('all_table_parity', False),
                             ('training_steps', 1), ('neural_inference', True),
                             ('harness_sha256', '0' * 64)]:
            with self.subTest(field=field):
                result, _, _ = self.exercise(alter=lambda rows: rows['baseline'].update({field: value}))
                self.assertFalse(result['pair_passed'])

    def test_exec_failure_still_collects_and_restores(self):
        result, _, collections = self.exercise(exec_error=True)
        self.assertFalse(result['pair_passed'])
        self.assertTrue(collections['docker-baseline-collection.json']['receipt_collected'])

    def test_collection_failure_still_cleans_and_restores(self):
        result, _, collections = self.exercise(download_error=True)
        self.assertFalse(result['pair_passed'])
        self.assertFalse(collections['docker-baseline-collection.json']['receipt_collected'])

    def test_bad_resources_refused_before_upload_or_replay(self):
        result, calls, collections = self.exercise(resource_error=True)
        self.assertFalse(result['pair_passed'])
        self.assertFalse(any(row[0] in ('upload', 'exec') for row in calls))
        self.assertEqual(collections, {})


if __name__ == '__main__':
    unittest.main(verbosity=2)
