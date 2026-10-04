"""Fresh pinned Hyper builds with the actual shared scheduler and bounded transport.

This opt-in driver runs real dependency probes, upstream downloads and builds.
It retains the resulting installation outside the small evidence directory.
No solver proof, model-checking verdict, throughput or scaling is qualified here.
Each invocation requires fresh output/install roots; failures remain evidence.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
ACCELERATE = ROOT.parent / 'ipfs_accelerate'
TOOLS = ('hyperltl', 'autohyper', 'mchyper')
SOURCE_PATHS = (
    'ipfs_datasets_py/logic/backends/installers/hyperproperty.py',
    'ipfs_datasets_py/logic/backends/installers/hyperproperty_setup.py',
    'ipfs_datasets_py/logic/backends/installers/hyperproperty_transaction.py',
    'ipfs_datasets_py/logic/backends/installers/install_control.py',
    'ipfs_datasets_py/logic/backends/installers/registry.py',
    'ipfs_datasets_py/logic/backends/toolchain_roles.py',
    'ipfs_datasets_py/logic/external_provers/lazy_installer.py',
    'ipfs_datasets_py/logic/backends/process.py',
    'ipfs_datasets_py/logic/backends/resource_admission.py',
    'ipfs_datasets_py/logic/backends/smt/operation_budget.py',
    'ipfs_datasets_py/optimizers/logic_theorem_optimizer/resource_scheduler.py',
    'ipfs_datasets_py/optimizers/logic_theorem_optimizer/proof_resource_safety.py',
)
ENV_KEYS = ('MAKEFLAGS', 'CMAKE_BUILD_PARALLEL_LEVEL', 'DOTNET_PROCESSOR_COUNT',
            'DOTNET_gcServer', 'DOTNET_GCHeapHardLimit', 'OMP_NUM_THREADS',
            'OPENBLAS_NUM_THREADS')
RAW_FIELDS = ('returncode', 'elapsed_seconds', 'pid', 'timed_out', 'cancelled',
              'output_truncated', 'resource_exhausted', 'process_tree_terminated',
              'workspace_limit_exceeded', 'error')


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def write(path, value):
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')
    temporary.replace(path)


def pins():
    paths = [ROOT / name for name in SOURCE_PATHS] + [Path(__file__).resolve(),
             ACCELERATE / 'config/formal_verification_toolchains.lock.json']
    return {str(path): sha(path) for path in paths}


def file_evidence(path):
    """Hash one selected regular file; never recursively enumerate a toolchain."""
    path = Path(path)
    resolved = path.resolve(strict=True)
    require(resolved.is_file(), 'selected dependency is not a regular file')
    with resolved.open('rb') as stream:
        header = stream.read(64)
    elf = header[:4] == b'\x7fELF'
    return {'path': str(path), 'resolved': str(resolved), 'bytes': resolved.stat().st_size,
            'sha256': sha(resolved), 'elf': elf,
            'elf_class': header[4] if elf else None,
            'elf_machine': int.from_bytes(header[18:20], 'little' if header[5] == 1 else 'big') if elf else None,
            'script': header.startswith(b'#!')}


def default_roots(base):
    build = base / 'build-dependencies/mchyper'
    return {
        'hyperltl': {'make': '/usr/bin/make', 'g++': '/usr/bin/g++', 'zlib': '/usr/bin/pkgconf',
                    'opam': str(base / 'opam/ipfs-datasets-coq/bin')},
        'autohyper': {'dotnet-sdk': str(base / 'dotnet-sdk-8.0.300-linux-arm64'),
                     'spot': str(base / 'spot-2.12-linux-aarch64')},
        'mchyper': {'ghcup-bin': str(build / '.ghcup/bin'),
                   'ghc-package-db': str(build / 'cabal/store/ghc-9.4.7/package.db'),
                   'python-root': str(build / 'python-2.7.18'),
                   'abc-root': str(build / 'abc-e76768b9d34f9dc67cb6608efecd55db271ff849'),
                   'aiger-root': str(build / 'aiger-1.9.4'),
                   'python-source': str(base / 'sources/Python-2.7.18'),
                   'abc-source': str(base / 'sources/abc-e76768b9d34f9dc67cb6608efecd55db271ff849'),
                   'aiger-source': str(base / 'sources/aiger-1.9.4'),
                   'python-archive': str(base / 'downloads/Python-2.7.18.tar.xz'),
                   'abc-archive': str(base / 'downloads/abc-e76768b9d34f9dc67cb6608efecd55db271ff849.tar.gz'),
                   'aiger-archive': str(base / 'downloads/aiger-1.9.4.tar.gz')},
    }


class Audit:
    """Observers delegate unchanged production execution/admission decisions."""
    def __init__(self, directory):
        self.directory, self.stack = directory, ExitStack()
        self.local = threading.local()
        self.commands, self.launches, self.admissions = [], [], []
        self.children, self.leases, self.owners = [], [], []
        self.tool, self.phase = '', ''

    def save(self):
        write(self.directory / 'command-audit.json', {'commands': self.commands,
              'launches': self.launches, 'admissions': self.admissions})

    def __enter__(self):
        from ipfs_datasets_py.logic.backends import process
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer import resource_scheduler as rs
        original_acquire = rs.GlobalResourceScheduler.acquire
        def configuration(owner):
            config = owner.config
            sampler = config.proof_resource_sampler
            return {**{key: getattr(config, key) for key in ('total_cpu_slots', 'total_memory_mb',
                'total_child_process_slots', 'proof_safety_enabled', 'proof_memory_headroom_mb',
                'proof_memory_stall_percent', 'proof_cpu_stall_percent', 'proof_io_stall_percent',
                'proof_backoff_seconds')}, 'state_path': str(owner.state_path),
                'sampler': sampler.__module__ + '.' + sampler.__qualname__}
        self.configuration = configuration
        def observe_acquire(owner, lane, **kwargs):
            if not any(item is owner for item in self.owners):
                self.owners.append(owner)
            row = {'tool': self.tool, 'phase': self.phase, 'lane': str(lane),
                   'scheduler_configuration': configuration(owner),
                   'started': time.monotonic(), 'request': {key: kwargs.get(key) for key in
                   ('cpu_slots', 'memory_mb', 'child_process_slots', 'timeout', 'request_id')}}
            self.admissions.append(row)
            try:
                lease = original_acquire(owner, lane, **kwargs)
            except BaseException as error:
                row.update(error_type=type(error).__name__, completed=time.monotonic())
                self.save()
                raise
            self.leases.append(lease)
            row.update(lease_id=lease.lease_id, wait_seconds=lease.wait_seconds, granted=time.monotonic())
            return lease
        self.stack.enter_context(patch.object(rs.GlobalResourceScheduler, 'acquire', observe_acquire))
        original_execute = process.SubprocessExecutor.execute
        def observe_execute(executor, invocation, cancellation=None):
            number = len(self.commands) + 1
            row = {'number': number, 'tool': self.tool, 'phase': self.phase,
                   'argv': list(invocation.argv), 'cwd': str(invocation.cwd),
                   'limits': asdict(invocation.limits), 'started': time.monotonic(),
                   'environment_controls': {key: invocation.environment.get(key) for key in ENV_KEYS}}
            self.commands.append(row)
            self.save()
            self.local.executing = True
            try:
                raw = original_execute(executor, invocation, cancellation)
                row['result'] = {key: getattr(raw, key) for key in RAW_FIELDS}
                for name in ('stdout', 'stderr'):
                    body = getattr(raw, name)
                    body = body if isinstance(body, bytes) else body.encode('utf-8')
                    require(len(body) <= invocation.limits.max_output_bytes, 'transport output exceeded bound')
                    path = self.directory / f'command-{number:03d}.{name}'
                    path.write_bytes(body)
                    row[name] = {'path': path.name, 'bytes': len(body), 'sha256': sha(path)}
                return raw
            except BaseException as error:
                row['exception_type'] = type(error).__name__
                raise
            finally:
                self.local.executing = False
                row['completed'] = time.monotonic()
                row['observed_seconds'] = row['completed'] - row['started']
                self.save()
                print(json.dumps({'tool': self.tool, 'phase': self.phase,
                    'command': Path(invocation.argv[0]).name,
                    'returncode': row.get('result', {}).get('returncode'),
                    'seconds': row['observed_seconds']}), flush=True)
        self.stack.enter_context(patch.object(process.SubprocessExecutor, 'execute', observe_execute))
        original_popen = subprocess.Popen
        def observe_popen(*args, **kwargs):
            require(getattr(self.local, 'executing', False), 'unbounded top-level subprocess refused')
            require(kwargs.get('shell') is False and kwargs.get('start_new_session') is True,
                    'native transport must own a process session')
            child = original_popen(*args, **kwargs)
            # Do not perform fallible I/O/scheduler work after Popen before the
            # executor receives ownership of the live process.
            self.children.append(child)
            self.launches.append({'tool': self.tool, 'phase': self.phase, 'pid': child.pid,
                                  'argv': list(args[0]), 'cwd': str(kwargs.get('cwd'))})
            return child
        self.stack.enter_context(patch.object(subprocess, 'Popen', observe_popen))
        self.stack.enter_context(patch.dict(process.SubprocessExecutor.__init__.__kwdefaults__, {'popen': observe_popen}))
        return self

    def __exit__(self, *args):
        self.stack.close()
        for row in self.admissions:
            owner = next(owner for owner in self.owners if str(owner.state_path) == row['scheduler_configuration']['state_path'])
            row['scheduler_configuration_after'] = self.configuration(owner)
            require(row['scheduler_configuration'] == row['scheduler_configuration_after'], 'scheduler configuration drift')
        for row, lease in zip((row for row in self.admissions if 'lease_id' in row), self.leases):
            row['released'] = lease.released
        self.save()


def validate_identity(hp, receipt, install_root):
    require(receipt.ok and receipt.identity is not None, 'installer did not return an installed identity')
    identity = receipt.identity
    require(identity.is_vendor_build and identity.is_upstream_build and not identity.is_hermetic_engine,
            'fresh setup must produce a real upstream identity')
    require(not identity.authorizes_universal_proof, 'setup cannot authorize universal proof')
    executable = file_evidence(identity.executable)
    require(executable['sha256'] == identity.artifact_sha256, 'installed executable digest changed')
    require(Path(identity.executable).resolve().is_relative_to(install_root), 'build escaped fresh install root')
    manifest = hp.identity_manifest_path(install_root, identity.tool_id, identity.version, vendor=True)
    archive = file_evidence(identity.source_archive_path)
    require(archive['sha256'] == identity.source_archive_sha256, 'installed source archive digest changed')
    components = []
    for component in identity.source_components:
        evidence = file_evidence(component.source_archive_path)
        require(evidence['sha256'] == component.source_archive_sha256, 'component archive digest changed')
        components.append(evidence)
    return {'manifest': file_evidence(manifest), 'executable': executable,
            'source_archive': archive, 'component_archives': components}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--install-root', type=Path, required=True,
                        help='Fresh live prefix outside the evidence directory; retained for reuse')
    parser.add_argument('--tools', choices=TOOLS, nargs='+', default=list(TOOLS))
    parser.add_argument('--managed-root', type=Path,
                        default=Path.home() / '.local/share/ipfs_datasets_py/theorem-provers')
    parser.add_argument('--dependency-roots', type=Path,
                        help='JSON mapping tool IDs to explicit dependency-root overrides')
    args = parser.parse_args()
    output, install_root = args.output_dir.absolute(), args.install_root.absolute()
    require(not output.exists() and not install_root.exists(), 'output and installation roots must be fresh')
    require(not install_root.is_relative_to(output) and not output.is_relative_to(install_root),
            'evidence and live installation roots must be separate')
    require(len(args.tools) == len(set(args.tools)), 'select each tool at most once')
    roots = default_roots(args.managed_root.absolute())
    if args.dependency_roots:
        override = json.loads(args.dependency_roots.read_text())
        require(isinstance(override, dict) and set(override) <= set(TOOLS), 'invalid per-tool dependency mapping')
        for tool, mapping in override.items():
            require(isinstance(mapping, dict) and all(isinstance(k, str) and isinstance(v, str) for k,v in mapping.items()),
                    'dependency overrides must map names to path strings')
            roots[tool] = dict(mapping)
    output.mkdir(parents=True)
    result = {'status': 'running', 'scope': 'real dependency probes and fresh upstream installation; no solver proofs',
              'install_root': str(install_root), 'tools': args.tools, 'cases': [],
              'source_pins_before': pins(), 'started': time.monotonic(),
              'dependency_override': file_evidence(args.dependency_roots) if args.dependency_roots else None}
    write(output / 'partial.json', result)
    from ipfs_datasets_py.logic.backends.installers import hyperproperty as hp
    from ipfs_datasets_py.logic.backends.installers.install_control import HyperInstallLimits, installation_scope
    from ipfs_datasets_py.logic.backends.installers.hyperproperty_setup import plan_hyperproperty_setup
    result['limits'] = asdict(HyperInstallLimits())
    functions = {'hyperltl': hp.ensure_hyperltl, 'autohyper': hp.ensure_autohyper, 'mchyper': hp.ensure_mchyper}
    audit = Audit(output)
    try:
        with audit:
            for tool in args.tools:
                require(pins() == result['source_pins_before'], 'source drift before engine execution')
                audit.tool = tool
                case = {'tool': tool, 'status': 'running', 'started': time.monotonic(),
                        'source_pins_before': pins(), 'dependency_roots': roots[tool], 'command_start': len(audit.commands)}
                result['cases'].append(case)
                snapshots = output / 'sources' / tool
                snapshots.mkdir(parents=True)
                case['source_snapshots'] = {}
                for index, (path, digest) in enumerate(case['source_pins_before'].items()):
                    target = snapshots / f'{index:02d}-{Path(path).name}'
                    target.write_bytes(Path(path).read_bytes())
                    require(sha(target) == digest, 'source changed during snapshot')
                    case['source_snapshots'][path] = str(target.relative_to(output))
                write(output / 'partial.json', result)
                try:
                    with installation_scope(limits=HyperInstallLimits()):
                        audit.phase = 'dependency-preflight'
                        case['dependency_plan'] = plan_hyperproperty_setup(tool, install_root=args.managed_root,
                                                                         dependency_roots=roots[tool])
                        dependencies = hp._resolve_vendor_dependencies(tool, dependency_roots=roots[tool])
                        case['dependency_identities'] = [item.to_dict() for item in dependencies]
                        case['dependency_files'] = [file_evidence(item.executable) for item in dependencies]
                        write(output / 'partial.json', result)
                        audit.phase = 'fresh-build'
                        receipt = functions[tool](yes=True, strict=True, force=False, vendor=True,
                            install_root=install_root, dependency_roots=roots[tool], repo_root=ACCELERATE)
                        case['receipt'] = receipt.to_dict()
                        write(output / 'partial.json', result)
                        require(receipt.status == 'installed', 'fresh root returned unexpected receipt status')
                        case['installed_files'] = validate_identity(hp, receipt, install_root)
                        audit.phase = 'cached-reuse'
                        before_reuse = len(audit.commands)
                        cached = functions[tool](yes=True, strict=True, force=False, vendor=True,
                            install_root=install_root, dependency_roots=roots[tool], repo_root=ACCELERATE)
                        case['cached_receipt'] = cached.to_dict()
                        require(cached.status == 'already_present' and cached.identity == receipt.identity,
                                'cached identity reuse changed the installed identity')
                        require(len(audit.commands) == before_reuse, 'cached reuse unexpectedly launched native work')
                        require(validate_identity(hp, cached, install_root) == case['installed_files'],
                                'cached reuse changed retained installed files')
                        case['status'] = 'passed'
                except Exception as error:
                    case.update(status='failed', error_type=type(error).__name__, error=str(error),
                                block_reasons=list(getattr(error, 'block_reasons', ())))
                    # Stop after a failed engine: retain partial evidence and the
                    # real prefix for diagnosis, without retrying/widening policy.
                    raise
                finally:
                    case.update(completed=time.monotonic(), command_end=len(audit.commands), source_pins_after=pins())
                    case['elapsed_seconds'] = case['completed'] - case['started']
                    write(output / 'partial.json', result)
                    require(case['source_pins_before'] == case['source_pins_after'], 'source changed during engine execution')
        result['status'] = 'passed'
    except Exception as error:
        result.update(status='failed', error_type=type(error).__name__, error=str(error),
                      block_reasons=list(getattr(error, 'block_reasons', ())))
    finally:
        result.update(source_pins_after=pins(), elapsed_seconds=time.monotonic()-result['started'],
                      native_launches=len(audit.launches), native_commands=len(audit.commands),
                      all_observed_children_reaped=all(child.poll() is not None for child in audit.children),
                      all_observed_leases_released=all(lease.released for lease in audit.leases))
        result['checks'] = {'stable_sources': result['source_pins_before'] == result['source_pins_after'],
                            'children_reaped': result['all_observed_children_reaped'],
                            'leases_released': result['all_observed_leases_released']}
        if not all(result['checks'].values()):
            result['status'] = 'failed'
        write(output / 'result.json', result)
    return 0 if result['status'] == 'passed' else 1


if __name__ == '__main__':
    sys.path[:0] = [str(ACCELERATE), str(ROOT)]
    raise SystemExit(main())
