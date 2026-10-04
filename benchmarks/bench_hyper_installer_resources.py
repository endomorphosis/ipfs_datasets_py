"""Controlled local-HTTP Hyper installation and real tiny Python build transport.

Fixture pins, dependency identities, compiler recipes and AutoHyper component
selection are explicit substitutions. Production download, extraction, staged
materialization, identity auditing, transaction ownership and admitted process
cleanup run normally. These artifacts are not upstream installations or solver
certificates. Only loopback network and benchmark-owned Python processes run.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, contextmanager
from dataclasses import asdict, replace
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import traceback
from unittest.mock import patch
from urllib.parse import urlparse

import bench_hyper_registry_fallback as previous
from bench_smt_operation_control import ROOT, MIB, require, sha, write

ENGINE_NAMES = ('hyperltl', 'autohyper', 'mchyper')
NEW_PATHS = (
    'tests/unit/logic/backends/test_hyper_installer_archives.py',
    'tests/unit/logic/backends/test_hyper_installer_transactions.py',
    'ipfs_datasets_py/logic/backends/installers/install_control.py',
    'ipfs_datasets_py/logic/backends/installers/hyperproperty_transaction.py',
    'ipfs_datasets_py/logic/backends/installers/hyperproperty.py',
    'ipfs_datasets_py/logic/external_provers/lazy_installer.py',
)
ENV_KEYS = ('MAKEFLAGS', 'CMAKE_BUILD_PARALLEL_LEVEL', 'DOTNET_PROCESSOR_COUNT',
    'DOTNET_gcServer', 'DOTNET_GCHeapHardLimit', 'OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS')


def pins():
    return {**previous.pins(), **{str(ROOT / name): sha(ROOT / name) for name in NEW_PATHS},
            str(Path(__file__).resolve()): sha(__file__)}


def digest(body):
    return hashlib.sha256(body.encode() if isinstance(body, str) else body).hexdigest()


def archive_body(name, commit, files):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode='w:gz') as bundle:
        for relative, content in sorted(files.items()):
            member = tarfile.TarInfo(f'{name}-{commit}/{relative}')
            member.size, member.mode, member.mtime = len(content), 0o644, 0
            bundle.addfile(member, io.BytesIO(content))
    body = buffer.getvalue()
    require(len(body) < MIB and sum(map(len, files.values())) < MIB, 'fixture archive exceeded finite ceiling')
    return body


def write_fixture(path, body):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    path.chmod(0o755)
    return path.resolve()


class LocalArchives:
    def __init__(self):
        self.bodies, self.requests, self.lock = {}, [], threading.Lock()

    def __enter__(self):
        owner = self
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                with owner.lock:
                    body = owner.bodies.get(self.path)
                    owner.requests.append({'path': self.path, 'bytes': len(body) if body is not None else 0,
                                           'at_monotonic': time.monotonic()})
                if body is None:
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            def log_message(self, *args):
                pass
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.server.daemon_threads = True
        self.base = f'http://127.0.0.1:{self.server.server_port}'
        self.thread = threading.Thread(target=self.server.serve_forever, name='owned-archive-http', daemon=True)
        self.thread.start()
        return self

    def add(self, name, commit, files):
        path = f'/{name}-{commit}.tar.gz'
        self.bodies[path] = archive_body(name, commit, files)
        return self.base + path, digest(self.bodies[path])

    def __exit__(self, *args):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        require(not self.thread.is_alive(), 'local archive server did not stop')


class Audit:
    def __init__(self, directory):
        self.directory, self.stack, self.local = directory, ExitStack(), threading.local()
        self.lock, self.pressure = threading.Lock(), False
        self.samples, self.admissions, self.invocations, self.launches = [], [], [], []
        self.children, self.leases, self.shared_attempts, self.transactions = [], [], [], []
        self.cancel_tokens, self.max_live = {}, 0

    def __enter__(self):
        from ipfs_datasets_py.logic.backends import process, resource_admission
        from ipfs_datasets_py.logic.backends.installers import install_control, hyperproperty_transaction
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer import resource_scheduler as scheduler
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer.proof_resource_safety import ProofHostResources
        healthy = ProofHostResources(4, 4096, 4096, pid_task_limit=1024, available_pid_tasks=1024)
        def sample():
            pressured = self.pressure
            value = replace(healthy, available_memory_mb=16) if pressured else healthy
            with self.lock:
                require(len(self.samples) < 4096, 'sampler history exceeded bound')
                self.samples.append({'at_monotonic': time.monotonic(), 'pressure': pressured, 'host': asdict(value)})
            return value
        def deny_shared(*args, **kwargs):
            self.shared_attempts.append(True)
            raise AssertionError('installer benchmark forbids shared resource pool')
        self.stack.enter_context(patch.object(scheduler, 'get_global_resource_scheduler', deny_shared))
        self.stack.enter_context(patch.object(resource_admission, 'get_global_resource_scheduler', deny_shared))
        self.owner = scheduler.GlobalResourceScheduler(scheduler.ResourceSchedulerConfig.for_proof_host(
            state_path=self.directory / 'private-pool.json', proof_resource_sampler=sample,
            total_cpu_slots=2, total_memory_mb=256, total_child_process_slots=4,
            proof_memory_headroom_mb=32, proof_backoff_seconds=.02, poll_interval_seconds=.002,
            lane_reservations={}, auto_renew_leases=False))
        self.before = self.owner.snapshot()
        self.limits = replace(install_control.HyperInstallLimits(), operation_timeout_ms=5000,
            max_download_bytes=MIB, max_extract_bytes=MIB, max_member_bytes=MIB,
            max_archive_members=128, max_archive_depth=16, max_path_bytes=256, io_timeout_seconds=1,
            build_memory_bytes=128*MIB, build_address_space_bytes=512*MIB,
            build_output_bytes=65536, build_workspace_bytes=MIB, build_cpu_slots=1, build_process_slots=2)
        acquire = self.owner.acquire
        def observe_acquire(lane, **kwargs):
            row = {'case': self.local.case, 'lane': str(lane), 'started': time.monotonic(),
                   **{key: kwargs[key] for key in ('cpu_slots', 'memory_mb', 'child_process_slots', 'timeout')}}
            with self.lock:
                self.admissions.append(row)
            lease = acquire(lane, **kwargs)
            row.update(lease_id=lease.lease_id, granted=time.monotonic(), wait_seconds=lease.wait_seconds)
            self.leases.append(lease)
            require((row['cpu_slots'], row['memory_mb'], row['child_process_slots']) == (1,128,2), 'fixture reservation changed')
            return lease
        self.stack.enter_context(patch.object(self.owner, 'acquire', observe_acquire))
        real_execute = process.SubprocessExecutor.execute
        def observe_execute(executor, invocation, cancellation=None):
            require(tuple(invocation.argv[:4]) == (str(Path(sys.executable).resolve()), '-I', '-B', '-c'),
                    'benchmark may execute only tiny isolated Python fixtures')
            state = self.owner.snapshot()
            require(0 < state['allocated']['cpu_slots'] <= 2 and 0 < state['allocated']['memory_mb'] <= 256
                    and 0 < state['allocated_child_process_slots'] <= 4, 'private resource budget overspent')
            limits = asdict(invocation.limits)
            require(0 < limits['timeout_seconds'] <= 2 and limits['memory_bytes'] == 512*MIB
                    and limits['resident_memory_bytes'] == 128*MIB and limits['max_workspace_bytes'] == MIB
                    and limits['max_output_bytes'] == 65536, 'build invocation limits changed')
            row = {'case': self.local.case, 'started': time.monotonic(), 'argv': list(invocation.argv),
                'cwd': str(invocation.cwd), 'limits': limits, 'environment': {key: invocation.environment[key] for key in ENV_KEYS},
                'snapshot': state}
            require(row['environment']['MAKEFLAGS'] == '-j1' and row['environment']['OMP_NUM_THREADS'] == '1',
                    'compiler concurrency controls missing')
            self.invocations.append(row)
            self.local.executing = True
            try:
                raw = real_execute(executor, invocation, cancellation)
                row['raw_process'] = {key: getattr(raw, key) for key in ('pid','returncode','timed_out','cancelled',
                    'workspace_limit_exceeded','resource_exhausted','process_tree_terminated','output_truncated','error','elapsed_seconds')}
                row['stdout_sha256'], row['stderr_sha256'] = digest(raw.stdout), digest(raw.stderr)
                return raw
            finally:
                row['completed'] = time.monotonic()
                self.local.executing = False
        self.stack.enter_context(patch.object(process.SubprocessExecutor, 'execute', observe_execute))
        real_popen = subprocess.Popen
        def observe_popen(*args, **kwargs):
            require(getattr(self.local, 'executing', False), 'unowned subprocess denied')
            require(kwargs.get('shell') is False and kwargs.get('start_new_session') is True, 'unexpected launcher contract')
            child = real_popen(*args, **kwargs)
            # No potentially failing scheduler/IO observation after ownership transfers.
            self.children.append(child)
            self.max_live = max(self.max_live, sum(p.poll() is None for p in self.children))
            self.launches.append({'case': self.local.case, 'pid': child.pid,
                'at_monotonic': time.monotonic(), 'argv': list(args[0]), 'cwd': str(kwargs['cwd'])})
            token = self.cancel_tokens.get(self.local.case)
            if token is not None:
                token.set()
            return child
        self.stack.enter_context(patch.object(subprocess, 'Popen', observe_popen))
        self.stack.enter_context(patch.dict(process.SubprocessExecutor.__init__.__kwdefaults__, {'popen': observe_popen}))
        self.stack.enter_context(patch.object(os, 'system', lambda *a, **k: (_ for _ in ()).throw(AssertionError('shell denied'))))
        real_transaction = hyperproperty_transaction.installation_transaction
        @contextmanager
        def observe_transaction(root, tool_id):
            row = {'case': self.local.case, 'root': str(root), 'tool_id': tool_id, 'entered': time.monotonic()}
            self.transactions.append(row)
            try:
                with real_transaction(root, tool_id) as transaction:
                    row['acquired'] = time.monotonic()
                    try:
                        yield transaction
                    finally:
                        row['body_completed'] = time.monotonic()
            finally:
                row['context_completed'] = time.monotonic()
        self.stack.enter_context(patch.object(hyperproperty_transaction, 'installation_transaction', observe_transaction))
        return self

    def drained(self):
        state = self.owner.snapshot()
        require(state['active_lease_count'] == state['waiting_request_count'] == 0, 'installer capacity leaked')
        require(all(child.poll() is not None for child in self.children), 'owned Python root survived cleanup')
        require(all(lease.released for lease in self.leases), 'owned lease not released')
        require(not self.shared_attempts and self.max_live <= 2, 'fixture escaped private process bounds')
        return state

    def __exit__(self, *args):
        self.pressure = False
        for token in self.cancel_tokens.values():
            token.set()
        for child in self.children:
            if child.poll() is None:
                # Exceptional observer cleanup is restricted to the exact owned process.
                child.terminate()
                try:
                    child.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    child.kill(); child.wait(timeout=1)
        self.after = self.drained()
        return self.stack.__exit__(*args)


class Fixtures:
    def __init__(self, directory, server, audit):
        self.directory, self.server, self.audit, self.stack = directory, server, audit, ExitStack()
        self.pins, self.components, self.dependencies, self.dependency_roots, self.builds = {}, {}, {}, {}, []

    def __enter__(self):
        from ipfs_datasets_py.logic.backends.installers import hyperproperty as hp, install_control as control
        from types import MappingProxyType
        files = {
            'hyperltl': {'Makefile': b'all:\n\t@echo fixture-only\n'},
            'autohyper': {'app/paths.json': b'{}\n', 'src/AutoHyper/AutoHyper.fsproj': b'<Project />\n',
                'src/AutoHyper/Configuration.fs': b'module Configuration\nlet getSolverConfiguration () =\n    let solverConfig = parseSolverConfigurationContent configContent\n'},
            'mchyper': {'mchyper.py': b'#!/usr/bin/env python2.7\n# controlled source fixture only\nprint("fixture only")\n',
                'src/Main.hs': b'main = putStrLn "controlled fixture"\n'},
        }
        for number, engine in enumerate(ENGINE_NAMES, 1):
            commit = str(number)*40
            url, checksum = self.server.add(engine, commit, files[engine])
            pin = dict(hp.DEFAULT_PINS[engine])
            pin.update(artifact_url=url, git_commit=commit, release_tag=commit, sha256=checksum,
                source=self.server.base+'/'+engine, version=commit[:8])
            self.pins[engine] = pin
            names = {'hyperltl': ('make','ocamlc'), 'autohyper': ('dotnet','autfilt','ltl2tgba'),
                     'mchyper': ('ghc','python2.7','abc','aigtoaig')}[engine]
            identities = []
            for name in names:
                path = write_fixture(self.directory/'dependencies'/engine/name, b'not executable upstream code: controlled identity\n')
                identities.append(hp.DependencyIdentity(name=name, constraint='controlled-fixture', executable=str(path),
                    version_output=name+' controlled-fixture', executable_sha256=sha(path),
                    phase='runtime' if name in {'autfilt','ltl2tgba','python2.7','abc','aigtoaig'} else 'build'))
            self.dependencies[engine] = tuple(identities)
            self.dependency_roots[engine] = {}
        for number, name in enumerate(('FsOmegaLib','TransitionSystemLib'), 4):
            commit = str(number)*40
            url, checksum = self.server.add(name, commit, {'Library.fs': ('module '+name+'\n').encode()})
            self.components[name] = {'path': 'src/'+name, 'source': self.server.base+'/'+name,
                'git_commit': commit, 'source_archive_url': url, 'source_archive_sha256': checksum}
        roots = self.dependency_roots['mchyper']
        provenance = self.directory/'dependency-evidence'
        package_db = provenance/'ghc-package-db'; package_db.mkdir(parents=True)
        (package_db/'package.cache').write_bytes(b'controlled fixture package database\n')
        roots['ghc-package-db'] = package_db
        for name in ('aiger','abc','python'):
            source = provenance/(name+'-source'); source.mkdir()
            (source/'SOURCE').write_bytes((name+' controlled source\n').encode())
            if name == 'aiger':
                (source/'VERSION').write_text(hp.MCHYPER_AIGER_VERSION)
            archive = provenance/(name+'.tar.gz'); archive.write_bytes((name+' controlled archive identity\n').encode())
            roots[name+'-source'], roots[name+'-archive'] = source, archive
            self.stack.enter_context(patch.object(hp, 'MCHYPER_'+name.upper()+'_SOURCE_ARCHIVE_SHA256', sha(archive)))
        self.stack.enter_context(patch.object(hp, 'DEFAULT_PINS', MappingProxyType(self.pins)))
        self.stack.enter_context(patch.object(hp, 'pin_for_tool', lambda selected, **kwargs: dict(self.pins[selected])))
        self.stack.enter_context(patch.object(hp, 'tool_supported_on_platform', lambda *a, **k: True))
        self.stack.enter_context(patch.object(hp, 'AUTOHYPER_SOURCE_COMPONENTS', MappingProxyType(self.components)))
        def fixture_pin(tool_id, pin, meta):
            expected = self.pins[tool_id]
            require(dict(pin) == expected and meta['source_archive_url'] == expected['artifact_url']
                and meta['source_archive_sha256'] == expected['sha256'] and meta['git_commit'] == expected['git_commit']
                and urlparse(expected['artifact_url']).netloc == urlparse(self.server.base).netloc,
                'unregistered fixture pin')
        self.stack.enter_context(patch.object(hp, '_assert_reviewed_upstream_pin', fixture_pin))
        self.stack.enter_context(patch.object(hp, '_resolve_vendor_dependencies', lambda tool, **kwargs: self.dependencies[tool]))
        real_urlopen = hp.urlopen
        def local_open(request, **kwargs):
            require(urlparse(request.full_url).scheme == 'http' and
                urlparse(request.full_url).netloc == urlparse(self.server.base).netloc,
                'benchmark forbids external network')
            return real_urlopen(request, **kwargs)
        self.stack.enter_context(patch.object(hp, 'urlopen', local_open))
        def fixture_components(source_root, *, download_root, scratch_root):
            result = []
            for name, component in self.components.items():
                url, commit, checksum = (component[key] for key in ('source_archive_url','git_commit','source_archive_sha256'))
                archive = hp._download_verified_archive(url, download_root/f'{name}-{commit}.tar.gz', checksum)
                extracted = hp._safe_extract_source_archive(archive, scratch_root/('component-'+name), commit)
                destination = source_root/component['path']; destination.parent.mkdir(parents=True, exist_ok=True)
                require(not destination.exists(), 'component fixture destination already occupied')
                shutil.move(str(extracted), destination)
                result.append(hp.SourceComponentIdentity(name=name, git_commit=commit, source_archive_url=url,
                    source_archive_sha256=checksum, source_archive_path=str(archive.resolve())))
            return tuple(result)
        self.stack.enter_context(patch.object(hp, '_materialize_autohyper_components', fixture_components))
        def tiny_build(argv, *, cwd, environment=None):
            engine = self.audit.local.engine
            outputs = ({'eahyper_src/eahyper.native': '\x7fELF-controlled-eahyper',
                        'LTL_SAT_solver/aalta': '\x7fELF-controlled-aalta', 'LTL_SAT_solver/pltl': '\x7fELF-controlled-pltl'}
                       if engine == 'hyperltl' else {'Main': '\x7fELF-controlled-mchyper'})
            if engine == 'autohyper':
                outputs = ({'src/AutoHyper/packages.lock.json': '{"version":1,"dependencies":{}}\n'} if 'restore' in argv
                           else {'app/AutoHyper': '\x7fELF-controlled-autohyper'})
                require('src/AutoHyper/AutoHyper.fsproj' in argv and (cwd/'src/AutoHyper/AutoHyper.fsproj').is_file(),
                        'AutoHyper fixture command must guard the whole source tree')
                for key in ('DOTNET_CLI_HOME','NUGET_PACKAGES','NUGET_HTTP_CACHE_PATH','TMPDIR'):
                    value = Path(environment[key]).resolve()
                    require(value == cwd/'.hyper-build-cache' or cwd/'.hyper-build-cache' in value.parents,
                            'AutoHyper cache escaped guarded build cwd')
                outputs['.hyper-build-cache/fixture-cache'] = 'tiny controlled package-cache entry'
            require(all(cwd.resolve() in (cwd/name).resolve().parents for name in outputs), 'fixture output escaped guarded cwd')
            program = ('import pathlib,time\n' + f'outputs={outputs!r}\n' +
                'for name,text in outputs.items():\n p=pathlib.Path(name);p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(text.encode());p.chmod(0o755)\n'
                'time.sleep(.04)\nprint("CONTROLLED_BUILD_FINISHED",flush=True)\n')
            raw = control.run_install_command((sys.executable,'-I','-B','-c',program), cwd=cwd,
                environment=environment, timeout_seconds=2)
            require(raw.returncode == 0 and not any((raw.cancelled,raw.timed_out,raw.resource_exhausted,raw.workspace_limit_exceeded,raw.output_truncated,raw.process_tree_terminated,raw.error)),
                    'controlled build did not complete cleanly')
            self.builds.append({'case': self.audit.local.case, 'engine': engine, 'logical_recipe': list(argv),
                'cwd': str(cwd), 'output_paths': sorted(outputs), 'actual_python_pid': raw.pid,
                'guarded_build_environment': {key: environment[key] for key in
                    ('DOTNET_CLI_HOME','NUGET_PACKAGES','NUGET_HTTP_CACHE_PATH','TMPDIR')} if engine=='autohyper' else {}})
        self.stack.enter_context(patch.object(hp, '_run_build_command', tiny_build))
        return self

    def install(self, engine, root, label, *, force=False):
        from ipfs_datasets_py.logic.backends.installers import hyperproperty as hp
        self.audit.local.case, self.audit.local.engine = label, engine
        return hp.materialize_vendor_engine(engine, install_root=root, repo_root=self.directory/'no-lock',
            platform_id=hp.LINUX_X86_64, dependency_roots=self.dependency_roots[engine], force=force,
            limits=self.audit.limits, scheduler=self.audit.owner)

    def __exit__(self, *args):
        return self.stack.__exit__(*args)


def transport(kind, audit, directory):
    from ipfs_datasets_py.logic.backends.installers import install_control as control
    from ipfs_datasets_py.logic.backends.smt.operation_budget import ProofOperationCancelled
    label, stop = 'transport_'+kind, threading.Event()
    row = {'group': label, 'started': time.monotonic(), 'fixture_only': True}
    starting = len(audit.invocations)
    if kind == 'cancel':
        audit.cancel_tokens[label] = stop
    program = ('import pathlib,time\npathlib.Path("tiny-output").write_bytes(b"x"*1024)\n'
               + ('time.sleep(1.5)\n' if kind == 'cancel' else 'print("OWNED_PYTHON_TRANSPORT",flush=True)\n'))
    box = {}
    def work():
        audit.local.case = label
        try:
            with tempfile.TemporaryDirectory(prefix='transport-', dir=directory) as raw:
                box['cwd'] = raw
                with control.installation_scope(limits=audit.limits, scheduler=audit.owner, cancellation=stop):
                    box['result'] = control.run_install_command((sys.executable,'-I','-B','-c',program), cwd=raw, timeout_seconds=2)
        except BaseException as error:
            box['error'] = error
    if kind == 'pressure_recovery':
        audit.pressure = True
        thread = threading.Thread(target=work, name='owned-install-pressure')
        thread.start()
        observed = None
        try:
            deadline = time.monotonic()+1
            while thread.is_alive() and time.monotonic()<deadline:
                state = audit.owner.snapshot()
                if state['waiting_request_count'] == 1 and state['proof_backoff'].get('reason'):
                    observed = state; break
                time.sleep(.002)
            require(observed is not None and len(audit.invocations) == starting, 'pressure did not queue before native launch')
            row['queued_snapshot'], row['pressure_released_at'] = observed, time.monotonic()
            audit.pressure = False
            thread.join(timeout=3)
            require(not thread.is_alive(), 'pressure worker did not finish')
        finally:
            audit.pressure = False
            stop.set()
            thread.join(timeout=3)
    else:
        work()
    require('cwd' in box and not Path(box['cwd']).exists(), 'transport workspace survived')
    if kind == 'cancel':
        require(isinstance(box.get('error'), ProofOperationCancelled) and 'result' not in box, 'cancellation published a result')
        require(audit.invocations[starting]['raw_process']['cancelled'], 'actual Python cancellation not observed')
        row['exception_type'] = type(box['error']).__name__
    else:
        if 'error' in box:
            raise box['error']
        require(box['result'].returncode == 0, 'transport failed')
    row.update(elapsed_seconds=time.monotonic()-row['started'], passed=True, pool_after=audit.drained(), workspace_removed=True)
    return row


def run(directory):
    from ipfs_datasets_py.logic.backends.installers import hyperproperty as hp
    started, before, cases = time.monotonic(), pins(), []
    with LocalArchives() as server, Audit(directory) as audit, Fixtures(directory,server,audit) as fixture:
        root = directory/'install'
        identities = {}
        for engine in ENGINE_NAMES:
            label, begin = 'fresh_'+engine, time.monotonic()
            count, builds = len(server.requests), len(fixture.builds)
            identity = fixture.install(engine, root, label)
            manifest = hp.identity_manifest_path(root, engine, fixture.pins[engine]['version'], vendor=True)
            require(identity.source_archive_sha256 == fixture.pins[engine]['sha256'] and manifest.is_file(), 'fixture identity missing')
            identities[engine] = identity
            require(not (manifest.parent/'upstream/.hyper-build-cache').exists(), 'build cache leaked into installed fixture')
            cases.append({'group': label, 'engine': engine, 'elapsed_seconds': time.monotonic()-begin,
                'fresh_http_requests': len(server.requests)-count, 'actual_python_builds': len(fixture.builds)-builds,
                'manifest_sha256': sha(manifest), 'fixture_identity': identity.to_dict(), 'passed': True,
                'upstream_certificate': False, 'pool_after': audit.drained()})
        begin, count, builds = time.monotonic(), len(server.requests), len(fixture.builds)
        cached = fixture.install('hyperltl', root, 'verified_reuse')
        require(cached.to_dict() == identities['hyperltl'].to_dict() and len(server.requests)==count and len(fixture.builds)==builds,
                'verified fixture cache unexpectedly fetched or built')
        cases.append({'group': 'verified_reuse', 'passed': True, 'elapsed_seconds': time.monotonic()-begin,
            'network_requests': 0, 'actual_python_builds': 0, 'identity_unchanged': True})
        begin = time.monotonic()
        manifest = hp.identity_manifest_path(root,'hyperltl',fixture.pins['hyperltl']['version'],vendor=True)
        old_manifest = sha(manifest)
        cache = root/'hyperproperty-sources'/'hyperltl'/(fixture.pins['hyperltl']['git_commit']+'.tar.gz')
        old_cache, original_sha = sha(cache), fixture.pins['hyperltl']['sha256']
        fixture.pins['hyperltl']['sha256'] = digest(b'deliberately absent controlled replacement')
        try:
            try:
                fixture.install('hyperltl',root,'failed_archive_preserves_install',force=True)
            except hp.HyperpropertyInstallBlocked as error:
                require('source_archive_digest_mismatch' in error.block_reasons, 'unexpected archive failure')
                reason = list(error.block_reasons)
            else:
                raise AssertionError('bad replacement archive was accepted')
        finally:
            fixture.pins['hyperltl']['sha256'] = original_sha
        require(sha(cache)==old_cache and sha(manifest)==old_manifest, 'bad download replaced verified cache/install')
        cases.append({'group': 'failed_archive_preserves_install', 'passed': True,
            'elapsed_seconds': time.monotonic()-begin, 'block_reasons': reason,
            'cache_sha256': old_cache, 'manifest_sha256': old_manifest, 'previous_install_preserved': True})
        begin, count, builds = time.monotonic(), len(server.requests), len(fixture.builds)
        barrier = threading.Barrier(2)
        def install_shared(index):
            barrier.wait(timeout=2)
            return fixture.install('hyperltl',directory/'concurrent-install',f'concurrent_{index}')
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = [future.result(timeout=7) for future in [executor.submit(install_shared,index) for index in range(2)]]
        txs = [row for row in audit.transactions if row['case'].startswith('concurrent_')]
        txs.sort(key=lambda row: row['acquired'])
        require(results[0].to_dict()==results[1].to_dict() and len(server.requests)-count==1 and len(fixture.builds)-builds==1,
                'same-tool fixture requests did not reuse single materialization')
        require(len(txs)==2 and txs[1]['acquired']>=txs[0]['body_completed'], 'same-tool transaction bodies overlapped')
        cases.append({'group':'concurrent_same_root','passed':True,'elapsed_seconds':time.monotonic()-begin,
            'requests':2,'fresh_http_requests':1,'actual_python_builds':1,'transactions':txs,'pool_after':audit.drained()})
        for kind in ('success','pressure_recovery','cancel'):
            cases.append(transport(kind,audit,directory))
        after_pool = audit.drained()
        require(not list(directory.rglob('*.partial')), 'archive temporary files leaked')
        require(all(not Path(row['cwd']).exists() for row in audit.invocations), 'staged build or transport workspace leaked')
        result = {'status':'passed_controlled_installer_resources','elapsed_seconds':time.monotonic()-started,
            'source_pins_before':before,'source_pins_after':pins(),'cases':cases,'group_count':len(cases),
            'scope': {'loopback_http_only':True,'synthetic_pins_dependencies_compiler_recipes':True,
                'synthetic_component_selection':True,'production_download_extract_materialize_identity_transaction':True,
                'real_owned_python_transport':True,'synthetic_host_pressure':True,'upstream_solver_executions':0,
                'actual_upstream_installation_qualified':False,'vendor_certificate':False,'native_proof_speedup_claim':False,
                'resource_limits':'Private admission estimates and sampled logical workspace/RSS guards; not a hard aggregate quota'},
            'install_limits':asdict(audit.limits),'private_pool_before':audit.before,'private_pool_after':after_pool,
            'http_requests':server.requests,'fixture_pins':fixture.pins,'builds':fixture.builds,
            'admissions':audit.admissions,'invocations':audit.invocations,'native_launches':audit.launches,
            'native_launch_count':len(audit.launches),'max_live_owned_python_roots':audit.max_live,
            'sample_history':audit.samples,'transactions':audit.transactions,
            'checks': {'all_nine_groups_passed':len(cases)==9 and all(row['passed'] for row in cases),
                'no_shared_pool_access':not audit.shared_attempts,'all_owned_processes_reaped':all(p.poll() is not None for p in audit.children),
                'owned_leases_waiters_drained':after_pool['active_lease_count']==after_pool['waiting_request_count']==0,
                'source_pins_stable':before==pins(),'owned_staging_workspaces_removed':all(not Path(row['cwd']).exists() for row in audit.invocations)}}
        require(all(result['checks'].values()), 'controlled installer validation failed')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',required=True,type=Path)
    args = parser.parse_args()
    directory = args.output_dir.resolve()
    directory.mkdir(parents=True,exist_ok=False)
    try:
        result = run(directory)
        write(directory/'result.json',result)
        print(json.dumps({'status':result['status'],'groups':result['group_count'],'native_launches':result['native_launch_count']}))
    except BaseException as error:
        write(directory/'failure.json',{'type':type(error).__name__,'message':str(error),'traceback':traceback.format_exc()})
        raise


if __name__ == '__main__':
    sys.path[:0] = [str(ROOT.parent/'ipfs_accelerate'),str(ROOT)]
    main()
