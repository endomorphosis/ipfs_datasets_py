"""Synthetic HTTP archive transactions and opt-in real fresh-runtime checks."""
from dataclasses import replace
import functools
import hashlib
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import io
import os
from pathlib import Path
import sys
import tarfile
import threading

import pytest

from ipfs_datasets_py.logic.backends.installers import isabelle as installer
from ipfs_datasets_py.logic.external_provers.isabelle_setup import ensure_isabelle_ready
from ipfs_datasets_py.logic.hammers.frontends.isabelle import IsabelleFrontend
from ipfs_datasets_py.logic.hammers.models import HammerRequest, HammerPolicy, ITPKind, ProofCandidateRecord
from ipfs_datasets_py.logic.hammers.reconstructors.isabelle import IsabelleReconstructor


@pytest.fixture
def archive_server(tmp_path, monkeypatch):
    def create(version='Isabelle2025-2'):
        # A controlled executable checks transaction/protocol behavior only;
        # its output is never evidence that a real Isabelle kernel ran.
        script=f'''#!{Path(sys.executable).resolve()}
from pathlib import Path
import sys
args = sys.argv[1:]
if args == ['version']:
    print({version!r})
elif args == ['process_theories', '-?']:
    print('Usage: isabelle process_theories [OPTIONS]')
    sys.exit(1)
elif args and args[0] == 'build':
    assert '-n' in args and '-b' in args
elif args and args[0] == 'process_theories':
    assert 'quick_and_dirty=false' in args
    source = Path('IPFSSetupCheck.thy').read_text()
    assert 'lemma ready: "True" by simp' in source and '@{{thm ready}}' in source
    print('IPFS_ISABELLE_KERNEL_CHECKED')
else:
    sys.exit(1)
'''.encode()
        archive=tmp_path/'archive.tar.gz'
        with tarfile.open(archive,'w:gz') as handle:
            files = {'bin/isabelle': script, 'etc/ISABELLE_IDENTIFIER': version.encode(),
                     'etc/settings': b'# controlled fixture\n', 'etc/components': b'',
                     'lib/scripts/getsettings': b'# controlled fixture\n'}
            for name, body in files.items():
                member=tarfile.TarInfo('Isabelle2025-2/' + name)
                member.mode=0o755 if name=='bin/isabelle' else 0o644
                member.size=len(body)
                handle.addfile(member,io.BytesIO(body))
        return archive
    archive=create()
    handler=functools.partial(SimpleHTTPRequestHandler,directory=str(tmp_path))
    server=ThreadingHTTPServer(('127.0.0.1',0),handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    pin=installer.ToolPin('isabelle','Isabelle2025-2',installer.detect_platform_key(),
                         f'http://127.0.0.1:{server.server_port}/archive.tar.gz', hashlib.sha256(archive.read_bytes()).hexdigest())
    monkeypatch.setattr(installer,'select_strict_pin',lambda *args,**kwargs:pin)
    try: yield tmp_path, create, pin
    finally: server.shutdown();server.server_close();thread.join(timeout=2)


def test_explicit_root_downloads_archive_and_does_not_reuse_global_runtime(archive_server, monkeypatch):
    root, _, pin=archive_server
    monkeypatch.setattr(installer,'which_executable',lambda _:pytest.fail('explicit root consulted global executable'))
    receipt=installer.ensure_isabelle(yes=True,install_root=root/'install')
    assert receipt.installed and receipt.download_attempted and receipt.checksum_verified
    assert receipt.executable_path==str(root/'install/bin/isabelle')
    assert (root/'install/downloads/archive.tar.gz').is_file()
    assert not list((root/'install').glob('.extract-*'))
    again=installer.ensure_isabelle(yes=True,install_root=root/'install')
    assert again.already_present and not again.download_attempted


def test_checksum_failure_preserves_existing_install(archive_server, monkeypatch):
    root, _, pin=archive_server
    install=root/'install'; existing=install/'Isabelle2025-2/keep';existing.parent.mkdir(parents=True);existing.write_text('original')
    monkeypatch.setattr(installer,'select_strict_pin',lambda *args,**kwargs:replace(pin,sha256='0'*64))
    with pytest.raises(installer.IsabelleInstallerError,match='checksum'):
        installer.ensure_isabelle(yes=True,force=True,install_root=install)
    assert existing.read_text()=='original' and not (install/'bin/isabelle').exists()
    assert not list(install.rglob('*.partial'))


def test_staged_validation_failure_preserves_existing_install(archive_server, monkeypatch):
    root, create, pin=archive_server
    archive=create('WrongVersion')
    monkeypatch.setattr(installer,'select_strict_pin',lambda *args,**kwargs:replace(pin,sha256=hashlib.sha256(archive.read_bytes()).hexdigest()))
    install=root/'install';existing=install/'Isabelle2025-2/keep';existing.parent.mkdir(parents=True);existing.write_text('original')
    with pytest.raises(installer.IsabelleInstallerError,match='locked version'):
        installer.ensure_isabelle(yes=True,force=True,install_root=install)
    assert existing.read_text()=='original' and not (install/'bin/isabelle').exists()
    assert not list(install.glob('.extract-*'))


def test_parallel_install_requests_publish_once_and_reuse(archive_server):
    from concurrent.futures import ThreadPoolExecutor
    root, _, _=archive_server
    with ThreadPoolExecutor(max_workers=4) as pool:
        receipts=list(pool.map(lambda _: installer.ensure_isabelle(yes=True,install_root=root/'shared'),range(4)))
    assert sum(receipt.status=='installed' for receipt in receipts)==1
    assert sum(receipt.already_present for receipt in receipts)==3
    assert all(receipt.installed for receipt in receipts)
    assert (root/'shared/.isabelle-install.lock').exists()
    assert not list((root/'shared').glob('.extract-*'))


def test_lazy_first_use_downloads_through_typed_transaction(archive_server, monkeypatch):
    from ipfs_datasets_py.logic.external_provers import lazy_installer
    from ipfs_datasets_py.logic.backends.installers import isabelle_installation as bounded
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.proof_resource_safety import ProofHostResources
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import (
        GlobalResourceScheduler, ResourceSchedulerConfig,
    )
    root, _, _=archive_server
    scheduler=GlobalResourceScheduler(ResourceSchedulerConfig.for_proof_host(
        state_path=root/'controlled-leases.json',
        proof_resource_sampler=lambda: ProofHostResources(16,16384,16384),
        total_cpu_slots=6,total_memory_mb=8192,total_child_process_slots=16,
        lane_reservations={},proof_memory_headroom_mb=512,
        proof_backoff_seconds=.02,poll_interval_seconds=.01))
    monkeypatch.setattr(bounded,'get_global_resource_scheduler',lambda:scheduler)
    receipts=[]
    original=bounded.ensure_isabelle_installation
    def observe(**kwargs):
        result=original(**kwargs)
        receipts.append(result)
        return result
    monkeypatch.setattr(bounded,'ensure_isabelle_installation',observe)
    home=root/'home'; home.mkdir()
    monkeypatch.setenv('HOME',str(home))
    target=home/'lazy-first-use'
    monkeypatch.setenv('IPFS_DATASETS_PY_EXTERNAL_PROVER_ROOT',str(target))
    for name in ('IPFS_DATASETS_PY_LAZY_INSTALL_PROVERS','IPFS_DATASETS_PY_MINIMAL_IMPORTS'):
        monkeypatch.delenv(name,raising=False)
    lazy_installer.reset_lazy_install_attempts()
    assert lazy_installer.lazy_install_prover('isabelle',allow_automatic=True,strict=True,force=True)
    assert (target/'downloads/archive.tar.gz').is_file()
    assert len(receipts)==1
    receipt=receipts[0]
    assert receipt.usable and receipt.installed and receipt.download_attempted and receipt.checksum_verified
    assert receipt.worker['observation']['workspace_cleaned']
    for preparation in (receipt.staged_preparation,receipt.preparation):
        assert preparation['usable'] and preparation['smoke_accepted']
        assert [phase['phase'] for phase in preparation['probes']]==['version','theory_help','hol_no_build','smoke']
        assert preparation['grants_proof_authority'] is False
    assert not receipt.cleanup_pending and not list(target.glob('.bounded-isabelle-*'))
    assert (target/'bin/isabelle').is_file()
    assert scheduler.snapshot()['active_lease_count']==0
    assert scheduler.snapshot()['waiting_request_count']==0


def test_nonstrict_missing_executable_returns_failed_receipt(archive_server, monkeypatch):
    root, _, pin=archive_server
    archive=root/'archive.tar.gz'
    with tarfile.open(archive,'w:gz') as handle:
        member=tarfile.TarInfo('Isabelle2025-2/README');member.size=7
        handle.addfile(member,io.BytesIO(b'no tool'))
    monkeypatch.setattr(installer,'select_strict_pin',lambda *args,**kwargs:replace(pin,sha256=hashlib.sha256(archive.read_bytes()).hexdigest()))
    receipt=installer.ensure_isabelle(yes=True,strict=False,install_root=root/'missing')
    assert receipt.status=='failed' and not receipt.installed
    assert 'executable_missing' in receipt.reason_codes
    assert not (root/'missing/bin/isabelle').exists()


@pytest.fixture
def fresh_root():
    value=os.environ.get('IPFS_DATASETS_ISABELLE_FRESH_TEST_ROOT')
    if not value: pytest.skip('set IPFS_DATASETS_ISABELLE_FRESH_TEST_ROOT after a fresh real download')
    root=Path(value).resolve()
    assert (root/'bin/isabelle').is_file()
    return root


def test_real_fresh_archive_checksum_and_setup_smoke(fresh_root):
    pin=installer.select_strict_pin('isabelle',platform_key=installer.detect_platform_key())
    archive=fresh_root/'downloads'/Path(pin.artifact_url).name
    assert archive.stat().st_size>1024**2 and installer.verify_sha256(archive,pin.sha256)
    # Full persistent HOL rebuilding is qualified once by its retained bounded
    # build benchmark; reusing the resulting runtime must not repeat that work.
    report=ensure_isabelle_ready(install=True,smoke=True,timeout=120,install_root=str(fresh_root))
    assert report['ready'] and report['smoke']['accepted']
    assert not report['installation']['receipt']['build_hol_requested']
    # Bounded readiness probes the pinned inner executable, without executing
    # the convenience wrapper as an additional discovery step.
    assert report['capability']['executables']['isabelle']['path']==str(fresh_root/installer.ISABELLE_VERSION/'bin/isabelle')


@pytest.mark.parametrize('statement,accepted',[('(n::nat) = n',True),('(0::nat) = 1',False)])
def test_real_fresh_runtime_captures_and_reconstructs(fresh_root,statement,accepted):
    executable=str(fresh_root/'bin/isabelle')
    frontend=IsabelleFrontend(executable=executable,timeout=60)
    source=f'theory FreshRuntimeCheck\nimports Main\nbegin\nlemma checked: "{statement}"\nsorry\nend\n'
    snapshot=frontend.snapshot_goal(source,theorem_id='checked')
    assert snapshot.native_command[0]==str(fresh_root/installer.ISABELLE_VERSION/"bin/isabelle")
    request=HammerRequest(request_id='fresh-proof',itp=ITPKind.ISABELLE,theorem_id='checked',
                          goal_statement=snapshot.goal_text,corpus_revision='fresh',policy=HammerPolicy(timeout_seconds=60))
    candidate=ProofCandidateRecord(candidate_id='untrusted',request_id=request.request_id,solver_attempt_id='proposal',premise_ids=[])
    reconstructor=IsabelleReconstructor(timeout=60,executable=executable)
    record,evidence,_=reconstructor.reconstruct(request=request,candidate=candidate,
        goal_snapshot=snapshot,native_source=source)
    assert record.kernel_accepted is accepted
    assert evidence.command[0]==str(fresh_root/installer.ISABELLE_VERSION/"bin/isabelle")


def test_real_fresh_canonical_backend_enforces_kernel_audit(fresh_root):
    from ipfs_datasets_py.logic.backends.kernel.isabelle import IsabelleKernelBackend
    from ipfs_datasets_py.logic.backends.results import ResultStatus
    from ipfs_datasets_py.logic.ir_core.claims import FrozenMap
    from ipfs_datasets_py.logic.ir_core.protocols import BackendRequest, ExecutionBounds, QueryKind
    executable=str(fresh_root/'bin/isabelle')
    request=BackendRequest(request_id='fresh-bounded',claim_id='claim',declaration_id='checked',
        claim_digest='1'*64,obligation_id='obligation',obligation_digest='2'*64,assumption_ids=(),
        logic_family='isabelle',query_kind=QueryKind.THEOREM_PROOF,
        bounds=ExecutionBounds(timeout_ms=60000,max_memory_bytes=2*1024**3),
        payload=FrozenMap({'encoding':'isabelle','source':
            'theory FreshBoundedCheck\nimports Main\nbegin\nlemma checked: "True" by simp\nend\n'}),
        requested_backend_id='isabelle')
    outcome=IsabelleKernelBackend(executable=executable).run(request)
    assert outcome.result.status is ResultStatus.PROVED, outcome.receipt.diagnostics
    assert outcome.receipt.accepted and outcome.receipt.toolchain.executable==str(fresh_root/installer.ISABELLE_VERSION/"bin/isabelle")
