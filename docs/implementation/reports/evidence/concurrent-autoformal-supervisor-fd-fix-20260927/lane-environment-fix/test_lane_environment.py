"""Execute only the actual harness environment-construction AST; no project imports."""
import ast
import os
from pathlib import Path
from types import SimpleNamespace
import unittest

HERE = Path(__file__).resolve().parent
HARNESS = HERE.parent / 'parent_harness.py'
ACCELERATE = Path('/explicit/published-accelerate')
DATASETS = Path('/explicit/canonical-datasets')
APPROVED = '/home/barberb/.local/lib/python3.12/site-packages'


def lane_environment(inherited):
    tree = ast.parse(HARNESS.read_text())
    function = next(node for node in tree.body
                    if isinstance(node, ast.FunctionDef) and node.name == 'run_smoke')
    start = next(index for index, node in enumerate(function.body)
                 if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name)
                    and target.id == 'env' for target in node.targets))
    end = next(index for index, node in enumerate(function.body)
               if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name)
                  and target.id == 'cpus' for target in node.targets))
    module = ast.Module(body=function.body[start:end], type_ignores=[])
    scope = {'os': SimpleNamespace(environ=inherited, pathsep=os.pathsep),
             'ACCELERATE': ACCELERATE, 'ROOT': DATASETS, 'root': Path('/owned/lanes')}
    exec(compile(module, str(HARNESS), 'exec'), scope)
    return scope['env']


class LaneEnvironmentTests(unittest.TestCase):
    def test_preserves_approved_package_roots_after_pinned_projects(self):
        result = lane_environment({'PYTHONPATH': APPROVED + ':/usr/lib/python3/dist-packages'})
        self.assertEqual(result['PYTHONPATH'].split(os.pathsep),
                         [str(ACCELERATE), str(DATASETS), APPROVED,
                          '/usr/lib/python3/dist-packages'])

    def test_empty_entries_do_not_add_current_directory(self):
        result = lane_environment({'PYTHONPATH': ':' + APPROVED + '::'})
        self.assertEqual(result['PYTHONPATH'].split(os.pathsep),
                         [str(ACCELERATE), str(DATASETS), APPROVED])

    def test_duplicates_keep_explicit_roots_first(self):
        result = lane_environment({'PYTHONPATH': ':'.join(
            [str(DATASETS), APPROVED, str(ACCELERATE), APPROVED])})
        self.assertEqual(result['PYTHONPATH'].split(os.pathsep),
                         [str(ACCELERATE), str(DATASETS), APPROVED])

    def test_absent_path_does_not_discover_external_roots(self):
        result = lane_environment({})
        self.assertEqual(result['PYTHONPATH'].split(os.pathsep),
                         [str(ACCELERATE), str(DATASETS)])

    def test_parent_environment_is_not_mutated(self):
        inherited = {'PYTHONPATH': APPROVED, 'PYTHONNOUSERSITE': '1', 'GIT_DIR': '/foreign'}
        original = dict(inherited)
        result = lane_environment(inherited)
        self.assertEqual(inherited, original)
        self.assertNotIn('GIT_DIR', result)
        self.assertEqual(result['PYTHONNOUSERSITE'], '1')

    def test_offline_cpu_and_cache_settings_remain(self):
        result = lane_environment({'HF_HUB_OFFLINE': '0', 'CUDA_VISIBLE_DEVICES': '0'})
        for name in ['HF_HUB_OFFLINE', 'TRANSFORMERS_OFFLINE', 'PYTHONDONTWRITEBYTECODE',
                     'OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS',
                     'NUMEXPR_NUM_THREADS']:
            self.assertEqual(result[name], '1')
        self.assertEqual(result['IPFS_DATASETS_LEGAL_IR_METRIC_DISK_CACHE'], '0')
        self.assertEqual(result['IPFS_DATASETS_PY_LAZY_INSTALL_ERGOAI'], '0')
        self.assertEqual(result['CUDA_VISIBLE_DEVICES'], '')
        self.assertEqual(result['TMPDIR'], '/owned/lanes/tmp')


if __name__ == '__main__':
    unittest.main(verbosity=2)
