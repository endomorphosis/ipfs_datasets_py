"""Installer admission boundaries; process transport is covered by the benchmark."""
from dataclasses import replace
import hashlib
import io
import os
from pathlib import Path
import sys
import tarfile
import threading

import pytest

from ipfs_datasets_py.logic.backends import process
from ipfs_datasets_py.logic.backends.installers import install_control as control
from ipfs_datasets_py.logic.backends.installers import hyperproperty as installer
from ipfs_datasets_py.logic.backends.smt import operation_budget as budget
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import resource_scheduler
from tests.unit.logic.backends._python_admission_fixtures import python_pool


@pytest.fixture(autouse=True)
def no_shared_pool(monkeypatch):
    def denied(*args, **kwargs):
        pytest.fail("control fixture must not use shared capacity")
    monkeypatch.setattr(resource_scheduler, "get_global_resource_scheduler", denied)


@pytest.mark.parametrize("field,value", [
    ("max_download_bytes", 0), ("max_extract_bytes", -1),
    ("max_archive_members", True), ("build_cpu_slots", 1.5),
    ("build_process_slots", False), ("io_timeout_seconds", float("inf")),
    ("io_timeout_seconds", float("nan")), ("io_timeout_seconds", 0),
    ("build_address_space_bytes", 1), ("operation_timeout_ms", True),
])
def test_invalid_limits_fail_before_host_access(field, value):
    with pytest.raises(ValueError):
        replace(control.HyperInstallLimits(), **{field: value})


def test_configuration_inert_and_nested_timeout_cannot_extend_parent():
    assert budget.current_proof_operation() is None
    with control.installation_scope(operation_timeout_ms=1000) as outer:
        with control.installation_scope(operation_timeout_ms=2000) as inner:
            assert inner.deadline == outer.deadline
    assert budget.current_proof_operation() is None


@pytest.mark.parametrize("owner", ["scheduler", "parent_lease"])
def test_duck_typed_resource_owner_refused(owner):
    with pytest.raises(TypeError):
        with control.installation_scope(**{owner: object()}):
            pytest.fail("invalid owner entered")


def test_precancelled_command_never_resolves_pool():
    signal = threading.Event(); signal.set()
    with pytest.raises(budget.ProofOperationCancelled):
        with control.installation_scope(cancellation=signal):
            control.run_install_command([sys.executable, "-V"])


@pytest.mark.parametrize("state", ["released", "cancelled"])
def test_inactive_parent_never_launches(monkeypatch, python_pool, state):
    parent = python_pool.owner.acquire("validation", cpu_slots=2, memory_mb=2048,
                                       child_process_slots=8)
    try:
        parent.release() if state == "released" else parent.cancel()
        with control.installation_scope(parent_lease=parent):
            with pytest.raises(control.InstallControlError, match="parent"):
                control.run_install_command([sys.executable, "-V"])
    finally:
        parent.release()


def test_actual_child_admission_covers_execution_and_releases_on_exception(monkeypatch, python_pool):
    parent = python_pool.owner.acquire("validation", cpu_slots=2, memory_mb=2048,
                                       child_process_slots=8)
    def execute(executor, invocation, cancellation):
        child = python_pool.acquired[-1]
        assert child.parent_lease_id == parent.lease_id and not child.released
        assert invocation.limits.resident_memory_bytes == 1024**3
        raise OSError("controlled transport failure")
    monkeypatch.setattr(process.SubprocessExecutor, "execute", execute)
    try:
        with control.installation_scope(parent_lease=parent):
            with pytest.raises(OSError, match="controlled"):
                control.run_install_command([sys.executable, "-V"])
        assert python_pool.acquired[-1].released and not parent.released
    finally:
        parent.release()


@pytest.mark.parametrize("cwd_kind", ["owned-probe", "build"])
def test_environment_and_combined_output_are_bounded(monkeypatch, python_pool, tmp_path, cwd_kind):
    seen = []
    monkeypatch.setenv("GHCRTS", "-N999")
    monkeypatch.setenv("COMPlus_GCHeapHardLimit", "ffffffffffff")
    def execute(executor, invocation, cancellation):
        assert python_pool.owner.snapshot()["active_lease_count"] == 1
        assert "GHCRTS" not in invocation.environment
        assert "COMPlus_GCHeapHardLimit" not in invocation.environment
        assert invocation.environment["MAKEFLAGS"] == "-j1"
        assert invocation.environment["DOTNET_PROCESSOR_COUNT"] == "1"
        assert invocation.limits.max_output_bytes == 16
        assert invocation.cwd.is_dir()
        seen.append(invocation.cwd)
        return process.RawProcessResult(returncode=0, stdout=b"a"*9, stderr=b"b"*8)
    monkeypatch.setattr(process.SubprocessExecutor, "execute", execute)
    with control.installation_scope(scheduler=python_pool.owner,
            limits=replace(control.HyperInstallLimits(), build_output_bytes=16)):
        result = control.run_install_command([sys.executable, "-V"],
            cwd=tmp_path if cwd_kind == "build" else None)
    assert result.output_truncated and result.error
    assert seen[0].exists() is (cwd_kind == "build")


def test_cancel_during_transport_refuses_completed_result(monkeypatch, python_pool):
    signal = threading.Event()
    def execute(*args, **kwargs):
        signal.set()
        return process.RawProcessResult(returncode=0)
    monkeypatch.setattr(process.SubprocessExecutor, "execute", execute)
    with pytest.raises(budget.ProofOperationCancelled):
        with control.installation_scope(scheduler=python_pool.owner, cancellation=signal):
            control.run_install_command([sys.executable, "-V"])
    assert python_pool.acquired[-1].released


def test_resource_revocation_refuses_completed_result(monkeypatch, python_pool):
    def execute(*args, **kwargs):
        python_pool.acquired[-1].cancel()
        return process.RawProcessResult(returncode=0)
    monkeypatch.setattr(process.SubprocessExecutor, "execute", execute)
    with control.installation_scope(scheduler=python_pool.owner):
        with pytest.raises(control.InstallControlError, match="revoked"):
            control.run_install_command([sys.executable, "-V"])
    assert python_pool.acquired[-1].released


@pytest.mark.parametrize('function', ['_tree_sha256', '_tree_content_sha256', '_tree_relocation_content_sha256'])
def test_all_tree_hash_profiles_share_aggregate_byte_ceiling(tmp_path, function):
    tree = tmp_path/'tree'; tree.mkdir()
    (tree/'first').write_bytes(b'ab'); (tree/'second').write_bytes(b'cd')
    with control.installation_scope(limits=replace(control.HyperInstallLimits(), build_workspace_bytes=4)):
        assert len(getattr(installer, function)(tree)) == 64
    with control.installation_scope(limits=replace(control.HyperInstallLimits(), build_workspace_bytes=3)):
        with pytest.raises(installer.HyperpropertyInstallBlocked, match='tree bytes'):
            getattr(installer, function)(tree)


def test_file_hash_refuses_fifo_without_opening_a_blocking_stream(tmp_path):
    fifo = tmp_path/'pipe'; os.mkfifo(fifo)
    with control.installation_scope():
        with pytest.raises(installer.HyperpropertyInstallBlocked, match='regular file'):
            installer._sha256_file(fifo)


def test_regular_dependency_symlink_and_exact_file_hash_limit_remain_compatible(tmp_path):
    target = tmp_path/'regular'; target.write_bytes(b'abc')
    alias = tmp_path/'dependency'; alias.symlink_to(target)
    with control.installation_scope():
        assert installer._sha256_file(alias, max_bytes=3) == hashlib.sha256(b'abc').hexdigest()
        with pytest.raises(installer.HyperpropertyInstallBlocked, match='regular file'):
            installer._sha256_file(alias, max_bytes=2)


def test_adapter_marker_inspection_reads_only_the_bounded_prefix(monkeypatch, tmp_path):
    path = tmp_path/'large-executable'
    marker = installer._INTERNAL_ADAPTER_MARKERS[0]
    path.write_bytes(b'x'*(1024*1024) + marker)
    reads, real_fdopen = [], os.fdopen
    class ObservedFile:
        def __init__(self, stream): self.stream = stream
        def __enter__(self): return self
        def __exit__(self, *args): return self.stream.__exit__(*args)
        def fileno(self): return self.stream.fileno()
        def read(self, size=-1):
            assert 0 <= size <= 256*1024
            value = self.stream.read(size); reads.append(len(value))
            return value
    monkeypatch.setattr(os, 'fdopen', lambda *args, **kwargs: ObservedFile(real_fdopen(*args, **kwargs)))
    monkeypatch.setattr(Path, 'read_bytes', lambda *args: pytest.fail('unbounded whole-file adapter read'))
    assert installer._is_internal_python_adapter(path) is False
    path.write_bytes(marker + b'x'*1024)
    assert installer._is_internal_python_adapter(path) is True
    assert reads == [256*1024, len(marker)+1024]


def test_archive_fifo_is_refused_before_open_or_destination_creation(monkeypatch, tmp_path):
    fifo, destination = tmp_path/'archive', tmp_path/'extract'
    os.mkfifo(fifo)
    original_open = Path.open
    def guarded_open(path, *args, **kwargs):
        if path == fifo:
            pytest.fail('archive FIFO must be refused before a blocking open')
        return original_open(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'open', guarded_open)
    with control.installation_scope():
        with pytest.raises(installer.HyperpropertyInstallBlocked, match='unsafe'):
            installer._safe_extract_source_archive(fifo, destination, 'a'*40)
    assert not destination.exists()
    assert installer._is_internal_python_adapter(fifo) is True


def test_cancel_after_restrictive_archive_modes_cleans_owned_partial_tree(monkeypatch, tmp_path):
    commit = 'a'*40; root_name = 'reviewed-'+commit; source = tmp_path/'source.tar.gz'
    with tarfile.open(source, 'w:gz') as bundle:
        for name, mode, body in ((root_name, 0o555, None),
                                 (root_name+'/private', 0, None),
                                 (root_name+'/private/input', 0o400, b'bounded fixture')):
            member = tarfile.TarInfo(name); member.mode = mode
            member.type = tarfile.DIRTYPE if body is None else tarfile.REGTYPE
            member.size = 0 if body is None else len(body)
            bundle.addfile(member, None if body is None else io.BytesIO(body))
    destination = tmp_path/'extract'; signal = threading.Event(); applied = []
    original = Path.chmod
    def chmod(path, mode, *args, **kwargs):
        result = original(path, mode, *args, **kwargs)
        if path == destination/root_name and mode == 0o555:
            applied.append(True); signal.set()
        return result
    monkeypatch.setattr(Path, 'chmod', chmod)
    with pytest.raises(budget.ProofOperationCancelled):
        with control.installation_scope(cancellation=signal):
            installer._safe_extract_source_archive(source, destination, commit)
    assert applied == [True] and not destination.exists()
