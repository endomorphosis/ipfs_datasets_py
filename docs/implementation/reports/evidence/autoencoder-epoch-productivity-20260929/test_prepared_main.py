"""Test exact prepared-main blobs in an isolated temporary source tree.

This is source integration evidence, never pinned native qualification or a
Lake admission. It does not change the live checkout/index, fetch, or download.
Run only after native timing runs have completed and root prepared the tree.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[4]
BASE = Path(__file__).resolve().parent
POLICY = 'docs/benchmarks/semantic_roundtrip_canonical_parity_policy.json'
TEST_BASE = 'tests/unit/optimizers/logic_theorem_optimizer/'
TESTS = [TEST_BASE + name for name in (
    'test_autoencoder_daemon_resources.py',
    'test_daemon_resource_inventory_lexical.py',
    'test_autoencoder_capacity.py',
    'test_autoencoder_inference.py',
    'test_run_autoencoder_fleet.py',
    'test_modal_autoencoder_tracking_fastpath.py',
    'test_modal_autoencoder_state_version.py',
    'test_modal_autoencoder_patch_codec.py',
    'test_modal_autoencoder_arrow_weights.py',
    'test_daemon_resource_inventory_concurrency.py',
    'test_daemon_resource_lock_contention.py',
    'test_autoencoder_training_worker.py',
    'test_incremental_autoencoders_cli.py',
    'test_autoencoder_source_manifest.py',
    'test_autoencoder_native_pool.py',
    'test_autoencoder_qualified_training.py',
    'test_autoencoder_qualification_pool.py',
    'test_modal_autoencoder_composed_refinement.py',
    'test_modal_autoencoder_adaptive_optimizer.py',
    'test_prepare_shared_autoencoder_targets.py',
    'test_autoencoder_target_preparation.py',
    'test_autoencoder_prepared_targets.py',
    'test_modal_autoencoder_state_transaction.py',
    'test_modal_autoencoder_sparse_state.py',
    'test_modal_autoencoder_sparse_checkpoint.py',
)] + ['tests/unit/logic/test_family_qualification.py', 'tests/unit/logic/modal/test_modal_lazy_exports.py']
SCOPE = ('Isolated exact prepared-main source integration tests; not canonical '
         'pinned native qualification, Lake evidence, admission, or generalization. '
         'The exact prepared-tree accelerator Gitlink is exported as a separately '
         'audited source dependency; other Gitlinks and all model weights are excluded.')
GIT_ENV = {k: v for k, v in os.environ.items() if k not in {
    'GIT_INDEX_FILE', 'GIT_DIR', 'GIT_WORK_TREE', 'GIT_COMMON_DIR',
    'GIT_OBJECT_DIRECTORY', 'GIT_ALTERNATE_OBJECT_DIRECTORIES'}}


def git(*args, repository=ROOT):
    return subprocess.check_output(['git', *args], cwd=repository, env=GIT_ENV)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def file_sha(path):
    return sha(path.read_bytes()) if path.is_file() else None


def save(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + '\n')


def selected(name):
    if name == POLICY:
        return True
    if name in {'pytest.ini', 'pyproject.toml', 'setup.cfg', 'setup.py', 'conftest.py'}:
        return True
    if name.startswith(('ipfs_datasets_py/', 'scripts/', 'tests/', 'benchmarks/')) and name.endswith('.py'):
        return True
    if name.startswith(('config/', 'configs/')) and Path(name).suffix in {'.json', '.toml', '.yaml', '.yml', '.ini', '.cfg'}:
        return True
    return False


def export(tree, directory, *, repository=ROOT, selector=selected, required=None):
    entries = []
    for entry in git('ls-tree', '-r', '-z', tree, repository=repository).split(b'\0'):
        if not entry:
            continue
        meta, raw_name = entry.split(b'\t', 1)
        mode, kind, oid = meta.decode().split()
        name = raw_name.decode()
        if not selector(name):
            continue
        path = Path(name)
        if path.is_absolute() or '..' in path.parts or path.as_posix() != name:
            raise ValueError('unsafe tree path')
        if kind != 'blob' or mode not in {'100644', '100755'}:
            raise ValueError('selected source/config is not an ordinary blob: ' + name)
        entries.append((name, mode, oid))
    names = {name for name, _, _ in entries}
    missing = set(TESTS + [POLICY, 'pytest.ini'] if required is None else required) - names
    if missing:
        raise ValueError('prepared tree lacks selected resources: ' + repr(sorted(missing)))
    result = {}
    process = subprocess.Popen(['git', 'cat-file', '--batch'], cwd=repository, env=GIT_ENV,
        stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    try:
        for name, mode, oid in entries:
            process.stdin.write((oid + '\n').encode()); process.stdin.flush()
            header = process.stdout.readline().decode().strip().split()
            if len(header) != 3 or header[:2] != [oid, 'blob']:
                raise ValueError('wrong source object')
            remaining = size = int(header[2])
            if not 0 <= size <= 64 * 1024 * 1024:
                raise ValueError('source/config blob exceeds export bound')
            target = directory / name
            target.parent.mkdir(parents=True, exist_ok=True)
            digest = hashlib.sha256()
            with target.open('xb') as stream:
                while remaining:
                    chunk = process.stdout.read(min(remaining, 65536))
                    if not chunk:
                        raise ValueError('truncated source object')
                    digest.update(chunk); stream.write(chunk); remaining -= len(chunk)
            if process.stdout.read(1) != b'\n':
                raise ValueError('invalid object separator')
            target.chmod(0o755 if mode == '100755' else 0o644)
            result[name] = {'git_blob': oid, 'sha256': digest.hexdigest(), 'bytes': size}
        process.stdin.close()
        if process.wait(timeout=30):
            raise ValueError('source export failed')
    finally:
        if process.poll() is None:
            process.kill(); process.wait()
    return result


PLUGIN = '''import hashlib, json, os, pathlib, sys

def pytest_sessionfinish(session, exitstatus):
    root = pathlib.Path(os.environ['ISOLATED_PREPARED_ROOT']).resolve()
    imports, outside = {}, {}
    for name, module in sorted(sys.modules.copy().items()):
        if not any(name == prefix or name.startswith(prefix + '.') for prefix in ('ipfs_datasets_py', 'ipfs_accelerate_py')):
            continue
        raw = getattr(module, '__file__', None)
        if not raw:
            continue
        path = pathlib.Path(raw).resolve()
        if root not in path.parents:
            outside[name] = str(path)
        elif path.is_file():
            imports[name] = {'path': path.relative_to(root).as_posix(), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    required = ('ipfs_accelerate_py.llm_router', 'ipfs_datasets_py.logic.legal_ir.canonical_compiler', 'ipfs_datasets_py.logic.legal_ir.canonical_decompiler', 'ipfs_datasets_py.logic.deontic.utils.deontic_parser')
    missing = [name for name in required if name not in imports]
    result = {'loaded_modules': imports, 'outside_modules': outside, 'missing_semantic_modules': missing, 'passed': not outside and not missing}
    pathlib.Path(os.environ['ISOLATED_IMPORT_AUDIT']).write_text(json.dumps(result, sort_keys=True, indent=2) + '\\n')
    if not result['passed']:
        session.exitstatus = 1
'''


def main():
    global TESTS
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepared', type=Path, default=BASE / 'prepared-publication.json')
    parser.add_argument('--export-only', action='store_true')
    parser.add_argument('--tests', type=Path, help='Optional explicit JSON list of prepared-tree test paths')
    parser.add_argument('--external-binding', type=Path, default=BASE / 'native-three-arm/baseline_adaptive/arm-binding.json')
    args = parser.parse_args()
    if args.tests:
        selected_tests = json.loads(args.tests.read_bytes())
        if (type(selected_tests) is not list or not selected_tests
                or any(type(name) is not str or not name.startswith("tests/")
                       or not name.endswith(".py") or Path(name).is_absolute()
                       or ".." in Path(name).parts or Path(name).as_posix() != name
                       for name in selected_tests)
                or len(selected_tests) != len(set(selected_tests))):
            raise ValueError("tests must be a unique explicit list of repository-relative test files")
        TESTS = selected_tests
    prepared = json.loads(args.prepared.read_bytes())
    tree = prepared['tree']
    if git('rev-parse', tree + '^{tree}').decode().strip() != tree:
        raise ValueError('prepared object is not exact tree id')
    head = git('rev-parse', 'HEAD').decode().strip()
    index = Path(git('rev-parse', '--git-path', 'index').decode().strip())
    if not index.is_absolute():
        index = ROOT / index
    index_sha = file_sha(index)
    workspace = {name: file_sha(ROOT / name) for name in prepared.get('workspace_file_sha256', {})}
    container = Path(tempfile.mkdtemp(prefix='autoencoder-prepared-main-tests-'))
    directory = container / 'external/ipfs_datasets'
    directory.mkdir(parents=True)
    # The tested orchestrator seals its sibling JevOps lock module as an
    # external dependency. Copy exact read-only bytes into the matching layout;
    # this is not an export from the prepared ipfs Git tree or native proof.
    external_lock = ROOT.parents[1] / 'JevOps/jevops/statement_lock.py'
    external_bytes = external_lock.read_bytes()
    external_binding = json.loads(args.external_binding.read_bytes())
    if external_binding['orchestration'].get(str(external_lock)) != sha(external_bytes):
        raise ValueError('external statement lock differs from captured dependency binding')
    target_lock = container / 'JevOps/jevops/statement_lock.py'
    target_lock.parent.mkdir(parents=True)
    target_lock.write_bytes(external_bytes)
    entries = export(tree, directory)
    gitlink_line = git('ls-tree', tree, 'ipfs_accelerate_py').decode().strip()
    gitlink_meta, gitlink_name = gitlink_line.split('\t')
    gitlink_mode, gitlink_kind, gitlink_commit = gitlink_meta.split()
    if (gitlink_mode, gitlink_kind, gitlink_name) != ('160000', 'commit', 'ipfs_accelerate_py'):
        raise ValueError('prepared accelerator dependency is not exact Gitlink')
    # Exact object is available in this sibling object store; never consult its
    # working tree or substitute its current HEAD, and never fetch missing data.
    accelerator_store = ROOT.parent / 'ipfs_accelerate'
    if git('cat-file', '-t', gitlink_commit, repository=accelerator_store).strip() != b'commit':
        raise ValueError('prepared accelerator commit unavailable locally')
    dependency_root = directory / 'ipfs_accelerate_py'
    def dependency_selected(name):
        return name == '__init__.py' or (name.startswith(('ipfs_accelerate_py/', 'common/', 'utils/', 'config/'))
            and Path(name).suffix in {'.py', '.json', '.toml', '.yaml', '.yml', '.ini', '.cfg', '.txt'})
    dependency_entries = export(gitlink_commit, dependency_root, repository=accelerator_store,
        selector=dependency_selected, required=['__init__.py', 'ipfs_accelerate_py/__init__.py', 'ipfs_accelerate_py/llm_router.py'])
    dependency_manifest = BASE / 'main-source-dependency-manifest.json'
    save(dependency_manifest, {'gitlink': gitlink_name, 'commit': gitlink_commit,
        'prepared_tree': tree, 'object_store': str(accelerator_store),
        'directory': str(dependency_root), 'files': dependency_entries,
        'excluded_gitlinks': [line.decode() for line in git('ls-tree', '-r', gitlink_commit,
            repository=accelerator_store).splitlines() if line.startswith(b'160000 ')]})
    export_manifest = BASE / 'main-source-export-manifest.json'
    save(export_manifest, {'tree': tree, 'directory': str(directory), 'files': entries})
    (directory / 'isolated_source_plugin.py').write_text(PLUGIN)
    summary = {'schema': 'prepared-main-focused-source-tests/v2', 'source_tree': tree,
        'origin_main_base': prepared['origin_main_base'], 'directory': str(directory),
        'scope': SCOPE, 'admitted': False, 'weights_downloaded': False,
        'exported_files': len(entries), 'exported_bytes': sum(row['bytes'] for row in entries.values()),
        'export_manifest_sha256': file_sha(export_manifest), 'policy': {**entries[POLICY], 'path': POLICY},
        'modal_sha256': entries['ipfs_datasets_py/optimizers/logic_theorem_optimizer/modal_autoencoder.py']['sha256'],
        'test_files': TESTS, 'export_only': args.export_only,
        'external_accelerator_dependency': {'commit': gitlink_commit, 'gitlink': gitlink_name,
            'directory': str(dependency_root), 'exported_files': len(dependency_entries),
            'exported_bytes': sum(row['bytes'] for row in dependency_entries.values()),
            'manifest_sha256': file_sha(dependency_manifest), 'scope': 'Exact prepared Gitlink ordinary source/resource blobs from local object store; no checkout substitution or download.'},
        'external_hash_input': {'original': str(external_lock), 'isolated': str(target_lock),
            'sha256': sha(external_bytes), 'bytes': len(external_bytes), 'binding_sha256': file_sha(args.external_binding),
            'scope': 'Exact sibling orchestration-hash input only; no Lake execution or prepared-main provenance claim.'}}
    if not args.export_only:
        xml = BASE / 'isolated-prepared-tests.xml'
        log = BASE / 'isolated-prepared-tests.log'
        import_audit = BASE / 'isolated-prepared-imports.json'
        command = [sys.executable, '-m', 'pytest', '-q', '-p', 'isolated_source_plugin', *TESTS, '--junitxml=' + str(xml)]
        environment = {**GIT_ENV, 'PYTHONPATH': str(directory),
            'IPFS_DATASETS_PY_LAZY_INSTALL_ERGOAI': '0', 'IPFS_DATASETS_LEGAL_IR_METRIC_DISK_CACHE': '0',
            'IPFS_DATASETS_MODAL_AUTOENCODER_AUTO_CUDA': '0', 'CUDA_VISIBLE_DEVICES': '',
            'HF_HUB_OFFLINE': '1', 'TRANSFORMERS_OFFLINE': '1',
            'ISOLATED_PREPARED_ROOT': str(directory), 'ISOLATED_IMPORT_AUDIT': str(import_audit)}
        started = time.monotonic()
        with log.open('wb') as stream:
            process = subprocess.run(command, cwd=directory, env=environment, stdout=stream, stderr=subprocess.STDOUT)
        summary.update(command=command, exit_code=process.returncode, elapsed_seconds=time.monotonic()-started)
        if xml.exists():
            suites = list(ET.parse(xml).getroot().iter('testsuite'))
            summary.update({key: sum(int(suite.attrib.get(key, 0)) for suite in suites)
                            for key in ('tests', 'failures', 'errors', 'skipped')})
        imported = json.loads(import_audit.read_bytes()) if import_audit.exists() else {'passed': False}
        summary.update(import_audit_passed=imported['passed'], imported_module_count=len(imported.get('loaded_modules', {})))
        summary['artifacts'] = {path.name: {'sha256': file_sha(path), 'bytes': path.stat().st_size}
                                for path in (xml, log, import_audit) if path.exists()}
    summary['live_head_unchanged'] = git('rev-parse', 'HEAD').decode().strip() == head
    summary['live_index_unchanged'] = file_sha(index) == index_sha
    summary['workspace_files_unchanged'] = all(file_sha(ROOT / name) == digest for name, digest in workspace.items())
    summary['external_hash_input_unchanged'] = external_lock.read_bytes() == external_bytes == target_lock.read_bytes()
    summary['exported_dependency_files_unchanged'] = all(file_sha(dependency_root / name) == row['sha256'] for name, row in dependency_entries.items())
    summary['exported_source_files_unchanged'] = all(file_sha(directory / name) == row['sha256'] for name, row in entries.items())
    if not args.export_only:
        summary['passed'] = (summary['exit_code'] == 0 and summary.get('failures') == 0 and summary.get('errors') == 0
            and summary['import_audit_passed'] and summary['live_head_unchanged'] and summary['live_index_unchanged']
            and summary['workspace_files_unchanged'] and summary['exported_dependency_files_unchanged'] and summary['exported_source_files_unchanged'] and summary['external_hash_input_unchanged'])
    save(BASE / 'main-source-test-summary.json', summary)
    print(json.dumps({key: summary[key] for key in ('source_tree', 'directory', 'exported_files', 'export_only', 'passed', 'tests', 'failures', 'errors', 'skipped', 'elapsed_seconds') if key in summary}, sort_keys=True))
    if not args.export_only and not summary['passed']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
