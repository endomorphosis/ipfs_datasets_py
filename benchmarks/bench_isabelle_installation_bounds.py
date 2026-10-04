"""Fresh local HTTP installation of an official archive under a shared owner.

This harness contains the legacy transaction inside a bounded worker. That
containment is qualification machinery, not a claim that every installer caller
uses a bounded subprocess. No remote archive download occurs here.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import importlib
import json
import os
from pathlib import Path
import platform
import stat
import sys
import threading
import time

DATASETS = Path(__file__).resolve().parents[1]
ACCELERATE = DATASETS.parent / 'ipfs_accelerate'
sys.path[:0] = [str(ACCELERATE), str(DATASETS)]

from ipfs_datasets_py.logic.backends.installers import isabelle, isabelle_profile
from ipfs_datasets_py.logic.backends.installers.isabelle_preparation import prepare_isabelle_runtime
from ipfs_datasets_py.logic.backends.process import BoundedToolRunner, ToolRunRequest, ToolRunLimits
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import get_global_resource_scheduler
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.proof_resource_safety import collect_proof_host_resources

WORKER = r'''
from dataclasses import replace
import json
from pathlib import Path
import sys
import time
from ipfs_datasets_py.logic.backends.installers import isabelle
request=json.loads(Path(sys.argv[1]).read_text())
original=isabelle.select_strict_pin
pin=original('isabelle', platform_key=isabelle.detect_platform_key())
assert pin.sha256 == request['sha256']
# Same reviewed bytes and release, served through a fresh loopback HTTP stream.
mirror=replace(pin, artifact_url=request['url'])
isabelle.select_strict_pin=lambda *a, **kw: mirror
phases=[]
def progress(phase, message):
    phases.append({'phase':phase,'at':time.monotonic(),'message':message})
started=time.monotonic()
cold=isabelle.ensure_isabelle(yes=True, strict=True, install_root=request['root'],
    timeout_seconds=request['timeout'], on_progress=progress)
cold_seconds=time.monotonic()-started
assert cold.installed and not cold.already_present, cold.to_dict()
started=time.monotonic()
warm=isabelle.ensure_isabelle(yes=True, strict=True, install_root=request['root'],
    timeout_seconds=max(.001, request['timeout']-cold_seconds), on_progress=progress)
warm_seconds=time.monotonic()-started
assert warm.already_present and not warm.download_attempted, warm.to_dict()
Path('install-receipts.json').write_text(json.dumps({'cold':cold.to_dict(),'warm':warm.to_dict(),
    'cold_seconds':cold_seconds,'warm_seconds':warm_seconds,'phases':phases}))
'''


def digest(path, checkpoint=lambda: None, max_bytes=None):
    value = hashlib.sha256()
    total = 0
    with Path(path).open('rb') as stream:
        while True:
            checkpoint()
            block = stream.read(1024**2)
            checkpoint()
            if not block:
                return value.hexdigest()
            total += len(block)
            if max_bytes is not None and total > max_bytes:
                raise ValueError('retained artifact exceeds its byte bound')
            value.update(block)


def source_hashes():
    paths = [Path(__file__).resolve()]
    for name in ('ipfs_datasets_py.logic.backends.installers.isabelle',
                 'ipfs_datasets_py.logic.backends.installers.isabelle_profile',
                 'ipfs_datasets_py.logic.backends.installers.isabelle_preparation',
                 'ipfs_datasets_py.logic.backends.process',
                 'ipfs_datasets_py.logic.backends.kernel.isabelle',
                 'ipfs_datasets_py.logic.external_provers.isabelle_runtime',
                 'ipfs_datasets_py.logic.external_provers.isabelle_setup',
                 'ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler',
                 'ipfs_datasets_py.optimizers.logic_theorem_optimizer.proof_resource_safety'):
        path = Path(importlib.import_module(name).__file__).resolve()
        if not path.is_relative_to(DATASETS):
            raise RuntimeError(f'wrong implementation: {path}')
        paths.append(path)
    return {str(path): digest(path) for path in paths}


def main():
    import psutil
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    archive, output = args.archive.resolve(strict=True), args.output.absolute()
    info = archive.stat()
    if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= isabelle.MAX_DOWNLOAD_BYTES:
        raise ValueError('retained archive must be a regular file within the download bound')
    if output.exists():
        raise RuntimeError('Choose a new output directory; prior attempts are retained')
    output.mkdir(parents=True)
    target = output / 'runtime'
    pin = isabelle.select_strict_pin('isabelle', platform_key=isabelle.detect_platform_key())
    owner = get_global_resource_scheduler()
    if not owner.config.proof_safety_enabled:
        raise RuntimeError('default shared pressure safety must remain enabled')
    result = {'schema':'isabelle-fresh-local-archive-qualification@1','status':'running',
        'started_at_utc':datetime.now(timezone.utc).isoformat(), 'source_sha256_before':source_hashes(),
        'archive':{'path':str(archive),'size_bytes':archive.stat().st_size,'expected_sha256':pin.sha256},
        'environment':{'platform':platform.platform(),'python_executable':sys.executable,
            'host':asdict(collect_proof_host_resources()),'scheduler':owner.config.persisted_dict()},
        'scope':{'fresh_local_http_download':True,'fresh_remote_download':False,
            'official_archive_bytes':True,'worker_containment_is_harness_only':True,
            'grants_repository_or_proof_authority':False},
        'limits':{'cpu_slots':3,'process_slots':12,'reservation_memory_mb':2304,
            'native_tree_rss_bytes':2048*1024**2,'per_process_address_space_bytes':32*1024**3,
            'worker_output_bytes':128*1024,'per_file_bytes':4*1024**3,'total_seconds_after_admission':600,
            'installer_download_bytes':6*1024**3, 'installer_expanded_bytes':24*1024**3,
            'installer_member_count':200000,
            'path_scope':'Runtime destination is outside private worker workspace; installer caps govern aggregate extraction there.'},
        'checks':{},'errors':[]}
    path = output / 'result.json'
    def save():
        path.write_text(json.dumps(result, indent=2, sort_keys=True)+'\n')
    save()
    requests = []
    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=str(archive.parent), **kw)
        def do_GET(self):
            if self.path != '/' + archive.name:
                self.send_error(404)
                return
            requests.append(self.path)
            super().do_GET()
        def log_message(self, *a):
            pass
    server = ThreadingHTTPServer(('127.0.0.1',0), Handler)
    serving = threading.Thread(target=server.serve_forever, daemon=True)
    stop = threading.Event()
    peak = {'rss_bytes':0,'processes':0,'threads':0}
    sampled = set()
    monitor_errors = []
    def monitor():
        parent = psutil.Process()
        while not stop.is_set():
            rss = threads = processes = 0
            try:
                children = parent.children(recursive=True)
            except psutil.Error as exc:
                monitor_errors.append(f'{type(exc).__name__}: {exc}')
                return
            for child in children:
                try:
                    sampled.add((child.pid, child.create_time()))
                    rss += child.memory_info().rss
                    threads += child.num_threads()
                    processes += 1
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            peak['rss_bytes'] = max(peak['rss_bytes'], rss)
            peak['processes'] = max(peak['processes'], processes)
            peak['threads'] = max(peak['threads'], threads)
            stop.wait(.05)
    monitoring = threading.Thread(target=monitor, daemon=True)
    admission = time.monotonic()
    try:
        with owner.acquire('orchestration', cpu_slots=3, memory_mb=2304, child_process_slots=12,
                           timeout=180, request_id='isabelle:fresh-archive-qualification') as parent:
            result['admission_seconds'] = time.monotonic()-admission
            started = time.monotonic()
            deadline = started+600
            def remaining():
                seconds = deadline-time.monotonic()
                if seconds <= 0 or parent.cancelled:
                    raise TimeoutError('qualification deadline or parent cancellation')
                return seconds
            hashed = time.monotonic()
            observed = digest(archive, remaining, isabelle.MAX_DOWNLOAD_BYTES)
            result['archive'].update(observed_sha256=observed,hash_seconds=time.monotonic()-hashed)
            if observed != pin.sha256:
                raise RuntimeError('retained archive differs from reviewed official pin')
            serving.start()
            monitoring.start()
            runner = BoundedToolRunner(base_environment={'PATH':os.defpath,'LANG':'C','LC_ALL':'C',
                'PYTHONPATH':f'{ACCELERATE}:{DATASETS}'})
            with parent.acquire_child(lane='validation', cpu_slots=3, memory_mb=2048,
                    child_process_slots=12, timeout=remaining(),
                    request_id='isabelle:bounded-install-worker') as worker_lease:
                # Deduct fresh pressure-admission time from the one total deadline.
                budget = remaining()
                request = {'root':str(target),'url':f'http://127.0.0.1:{server.server_port}/{archive.name}',
                           'sha256':pin.sha256,'timeout':budget}
                worker_request = ToolRunRequest(argv=(sys.executable,'-P','{workspace}/install_worker.py','{workspace}/request.json'),
                    input_files={'install_worker.py':WORKER,'request.json':json.dumps(request),
                        **isabelle_profile.settings_files(isabelle.ISABELLE_VERSION, 2048)},
                    output_paths=('install-receipts.json',),
                    limits=ToolRunLimits(timeout_seconds=budget,cpu_seconds=budget,
                        memory_bytes=32*1024**3,resident_memory_bytes=2048*1024**2,
                        max_output_bytes=128*1024,max_input_bytes=32*1024,max_workspace_bytes=4*1024**3),
                    environment={'JDK_JAVA_OPTIONS':isabelle_profile.BOOTSTRAP_JAVA_OPTIONS,
                                 'IPFS_DATASETS_AUTO_INSTALL_TEST_DEPS':'0'})
                worker = runner.run(worker_request,
                    cancellation=worker_lease.cancellation_signal)
            result['worker'] = worker.to_dict()
            if not worker.ok or worker.error or worker.output_truncated or not worker.workspace_cleaned:
                raise RuntimeError('bounded install worker did not complete')
            receipts = json.loads(worker.output_files['install-receipts.json'])
            result['installation'] = receipts
            ready = prepare_isabelle_runtime(mode='smoke', install_root=target,
                parent_lease=parent, timeout_seconds=min(120, remaining()))
            result['preparation'] = ready.to_dict()
            result['checks'].update(cold_installed=receipts['cold']['installed'],
                warm_reused=receipts['warm']['already_present'] and not receipts['warm']['download_attempted'],
                exactly_one_download=len(requests)==1, readiness=ready.usable,
                no_partial_files=not list(target.rglob('*.partial')),
                no_staging_directories=not list(target.glob('.extract-*')),
                no_owned_children=all(row['lease_id']==parent.lease_id for row in owner.active_leases()
                    if row['owner_pid']==os.getpid()))
            if not ready.usable:
                raise RuntimeError('fresh installed runtime failed bounded smoke')
            runtime = Path(ready.to_dict()['native_runtime']['runtime_root'])
            result['runtime_sha256'] = {str(file.relative_to(runtime)):digest(file,remaining)
                for file in [runtime/'bin/isabelle',runtime/'etc/settings',*runtime.glob('heaps/*/HOL'),*runtime.glob('heaps/*/Pure')]}
            result['work_seconds_after_admission'] = time.monotonic()-started
        result['checks']['owned_leases_drained'] = not any(row['owner_pid']==os.getpid() for row in owner.active_leases())
        if not all(result['checks'].values()):
            raise RuntimeError('qualification checks failed')
        result['status'] = 'completed'
    except Exception as exc:
        result['status'] = 'failed'
        result['errors'].append(f'{type(exc).__name__}: {exc}')
    finally:
        stop.set()
        if monitoring.ident is not None:
            monitoring.join(3)
        if serving.ident is not None:
            server.shutdown()
            serving.join(3)
        server.server_close()
        result['monitor_errors'] = monitor_errors
        result['checks']['monitor_drained'] = not monitoring.is_alive() and not monitor_errors
        result['checks']['http_server_drained'] = not serving.is_alive()
        result['native_children_sampled_peak'] = peak
        result['http_requests'] = requests
        result['sampled_descendants_live'] = []
        for pid, birth in sampled:
            try:
                process=psutil.Process(pid)
                if process.create_time()==birth and process.status()!=psutil.STATUS_ZOMBIE:
                    result['sampled_descendants_live'].append(pid)
            except psutil.NoSuchProcess:
                pass
        result['checks']['owned_leases_drained'] = not any(row['owner_pid']==os.getpid() for row in owner.active_leases())
        result['checks']['sampled_descendants_drained'] = not result['sampled_descendants_live']
        try:
            result['source_sha256_after'] = source_hashes()
            result['checks']['selected_sources_unchanged'] = result['source_sha256_before']==result['source_sha256_after']
        except Exception as exc:
            result['checks']['selected_sources_unchanged'] = False
            result['errors'].append(f'final source recording: {type(exc).__name__}: {exc}')
        if not all(result['checks'].values()):
            result['status']='failed'
        result['finished_at_utc']=datetime.now(timezone.utc).isoformat()
        save()
    print(json.dumps({'status':result['status'],'checks':result['checks'],'errors':result['errors']}))
    if result['status']!='completed':
        raise SystemExit(1)


if __name__=='__main__':
    main()
