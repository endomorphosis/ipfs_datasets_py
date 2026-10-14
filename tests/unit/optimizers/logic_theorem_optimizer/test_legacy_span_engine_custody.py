"""Private native owner joins; no model, legal inference, Lake or shared DB."""
from copy import deepcopy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_daemon_resources as host
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import existing_resource_scheduler as existing
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legacy_span_campaign_resources as resources
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legacy_span_engine_custody as custody
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import resource_scheduler as native

ROOT = Path(__file__).resolve().parents[4]
SOURCE = ROOT / "scripts/ops/legal_ir/run_legacy_span_cuda.py"
SPEC = importlib.util.spec_from_file_location("legacy_pinned_owner_runner_test", SOURCE)
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


@pytest.fixture
def private(tmp_path, monkeypatch):
    state_path = tmp_path / "scheduler.json"
    scheduler = native.GlobalResourceScheduler(native.ResourceSchedulerConfig(
        state_path=state_path, total_cpu_slots=4, total_memory_mb=16384,
        total_child_process_slots=8, lane_reservations={}, proof_safety_enabled=True,
        auto_renew_leases=False))
    state = json.loads(state_path.read_bytes())
    state["next_sequence"] = 99
    state["metrics"]["acquisitions_total"] = 37
    state["retained_campaign_history"] = {"completed": ["preserved"], "budget": 17}
    state_path.write_text(json.dumps(state))
    policy = existing.policy_sha256(state["config"])
    real_factory = existing.open_existing_scheduler
    def private_factory(*args):
        facade = real_factory(*args)
        facade.config.proof_resource_sampler = lambda: native.ProofHostResources(
            8, 32768, 32768, pid_task_limit=500, available_pid_tasks=400)
        facade.config.auto_renew_leases = False
        return facade
    monkeypatch.setattr(existing, "open_existing_scheduler", private_factory)
    monkeypatch.setattr(host, "get_global_resource_scheduler", lambda: pytest.fail("implicit global facade"))
    monkeypatch.setattr(native, "get_global_resource_scheduler", lambda: pytest.fail("implicit global facade"))
    root = tmp_path / "outputs"
    root.mkdir()
    runtime = root / "runtime"
    runtime.mkdir()
    ledger = tmp_path / "disk.json"
    ledger.write_text(json.dumps(dict(schema=host.SCHEMA, roots=[host._root_identity(root)],
        limit_bytes=host.MAX_STORAGE_BYTES, reservations={"preserved": dict(reservation_id="preserved",
            status="retained", owner_pid=999999, storage_bytes=1234, reason="retained private claim")})))
    return state_path, policy, state, runtime, ledger


def arguments(private, *, engine=False):
    path, policy, _, runtime, ledger = private
    values = ["--runtime-directory", str(runtime), "--resource-ledger", str(ledger),
        "--scheduler-state", str(path), "--expected-policy-sha256", policy,
        "--compiler-workers", "1", "--bridge-workers", "1", "--memory-mb", "1024",
        "--storage-bytes", "100000"]
    if engine:
        values.append("--_engine")
    return runner.arguments(values)


@pytest.mark.parametrize("engine", [False, True])
def test_implicit_launch_refuses_before_runtime_cache_or_child(tmp_path, monkeypatch, engine):
    runtime = tmp_path / "not-created"
    monkeypatch.setattr(runner, "engine", lambda *a, **kw: pytest.fail("unowned engine"))
    monkeypatch.setattr(runner.subprocess, "Popen", lambda *a, **kw: pytest.fail("unowned child"))
    values = ["--runtime-directory", str(runtime)] + (["--_engine"] if engine else [])
    with pytest.raises(ValueError, match="explicit existing scheduler"):
        runner.main(values)
    assert not runtime.exists()


@pytest.mark.parametrize("field,value", [("--scheduler-state", "unused.json"),
    ("--expected-policy-sha256", "a" * 64)])
def test_partial_scheduler_identity_is_rejected_before_runtime(tmp_path, field, value):
    with pytest.raises(SystemExit):
        runner.arguments(["--runtime-directory", str(tmp_path / "not-created"), field, value])
    assert not (tmp_path / "not-created").exists()


@pytest.mark.parametrize("engine", [False, True])
def test_changed_policy_refuses_before_runtime_cache_or_child(private, tmp_path, monkeypatch, engine):
    path, _, _, _, _ = private
    runtime = tmp_path / "not-created"
    before = path.read_bytes()
    monkeypatch.setattr(runner, "engine", lambda *a, **kw: pytest.fail("changed-policy engine"))
    monkeypatch.setattr(runner.subprocess, "Popen", lambda *a, **kw: pytest.fail("changed-policy child"))
    values = ["--runtime-directory", str(runtime), "--scheduler-state", str(path),
        "--expected-policy-sha256", "f" * 64] + (["--_engine"] if engine else [])
    with pytest.raises(existing.ExistingResourceSchedulerError, match="exact stored"):
        runner.main(values)
    assert not runtime.exists() and path.read_bytes() == before


def test_library_policy_refusal_precedes_runtime_and_ledger_access(private, tmp_path, monkeypatch):
    path, _, _, _, _ = private
    monkeypatch.setattr(host, "_safe_path", lambda *a, **kw: pytest.fail("runtime or ledger touched"))
    with pytest.raises(existing.ExistingResourceSchedulerError, match="exact stored"):
        resources.LegacySpanCampaignResources(tmp_path / "absent", tmp_path / "absent-ledger",
            scheduler_state_path=path, expected_scheduler_policy_sha256="f" * 64)


def test_policy_drift_before_open_preserves_disk_claims(private):
    path, policy, _, runtime, ledger = private
    resource = resources.LegacySpanCampaignResources(runtime, ledger, storage_bytes=100000,
        memory_mb=1024, cpu_slots=3, child_process_slots=5,
        scheduler_state_path=path, expected_scheduler_policy_sha256=policy)
    before = ledger.read_bytes()
    state = json.loads(path.read_bytes())
    state["config"]["total_child_process_slots"] = 9
    path.write_text(json.dumps(state))
    with pytest.raises(existing.ExistingResourceSchedulerError, match="exact stored"):
        resource.open()
    assert ledger.read_bytes() == before and not resource._opened


CHILD = r'''import json,sys
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legacy_span_engine_custody import (
    LegacySpanEngineVerifier,read_engine_launch)
launch=read_engine_launch(sys.stdin.buffer)
spec=dict(launch['spec'])
change=sys.argv[1]
if change=='owner_birth': launch['owner']['birth']='forged'
elif change=='child_birth': launch['child']['birth']='forged'
elif change=='lease': launch['lease_id']='absent'
elif change=='reservation': launch['reservation_id']='absent'
elif change=='invocation': spec['invocation_sha256']='f'*64
elif change=='scope': launch['spec']['cpu_slots']=1
elif change=='hash': launch['spec_sha256']='f'*64
elif change=='extra': launch['extra']='unsupported'
elif change=='source': launch['producer_sources'][next(iter(launch['producer_sources']))]='f'*64
elif change=='bytecode': launch['bytecode']['inode']+=1
elif change=='dirty_bytecode':
    from pathlib import Path
    Path(launch['bytecode']['path'],'foreign.pyc').write_bytes(b'not-source')
elif change=='old_schema': launch['schema']='legacy-span-engine-launch/v1'
try:
    LegacySpanEngineVerifier(launch,spec).verify()
except Exception as error:
    print(json.dumps({'verified':False,'error_type':type(error).__name__}))
    raise SystemExit(2)
print(json.dumps({'verified':True,'model_executed':False,'admitted':False}))
'''


@pytest.mark.parametrize("change", ["none", "owner_birth", "child_birth", "lease", "reservation",
    "invocation", "scope", "hash", "extra", "source", "bytecode", "dirty_bytecode", "old_schema"])
def test_actual_private_child_requires_live_parent_birth_lease_and_disk_join(private, change):
    path, policy, initial, runtime, ledger = private
    preserved = deepcopy(json.loads(ledger.read_bytes())["reservations"]["preserved"])
    args = arguments(private)
    resource = resources.LegacySpanCampaignResources(runtime, ledger, storage_bytes=100000,
        memory_mb=1024, cpu_slots=3, child_process_slots=5,
        scheduler_state_path=path, expected_scheduler_policy_sha256=policy)
    child = None
    with resource:
        try:
            bytecode = resource.prepare_engine_bytecode()
            environment = dict(os.environ, PYTHONPATH=str(ROOT), PYTHONDONTWRITEBYTECODE="1",
                PYTHONPYCACHEPREFIX=str(bytecode),
                IPFS_DATASETS_AUTO_INSTALL="false", IPFS_AUTO_INSTALL="false",
                OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1")
            child = subprocess.Popen([sys.executable, "-B", "-c", CHILD, change], cwd=ROOT,
                env=environment, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, start_new_session=True)
            launch = resource.bind_engine_launch(child.pid, custody.invocation_sha256(args), bytecode_directory=bytecode)
            serialized = json.dumps(launch, sort_keys=True, separators=(",", ":")).encode() + b"\n"
            assert "lease_key" not in launch and b'"lease_key"' not in serialized
            assert launch["spec"] == custody.engine_resource_spec(args)
            output, error = child.communicate(serialized, timeout=30)
            assert child.returncode == (0 if change == "none" else 2), error.decode()
            assert json.loads(output)["verified"] is (change == "none")
            resource.close(artifacts_durable=True)
        finally:
            if child is not None and child.poll() is None:
                child.kill()
                child.wait(timeout=10)
    final = json.loads(path.read_bytes())
    assert final["config"] == initial["config"]
    assert final["retained_campaign_history"] == initial["retained_campaign_history"]
    assert final["next_sequence"] == initial["next_sequence"] + 1
    assert final["metrics"]["acquisitions_total"] == initial["metrics"]["acquisitions_total"] + 1
    assert final["metrics"]["releases_total"] == initial["metrics"]["releases_total"] + 1
    assert final["leases"] == {} and final["waiters"] == {}
    assert json.loads(ledger.read_bytes())["reservations"]["preserved"] == preserved


def test_bare_hidden_engine_cannot_use_policy_hash_as_authority(private, monkeypatch):
    args = arguments(private, engine=True)
    monkeypatch.setattr(runner, "engine", lambda *a, **kw: pytest.fail("unowned cache or CUDA"))
    with open(os.devnull, "rb") as stream:
        monkeypatch.setattr(runner.sys, "stdin", type("Input", (), {"buffer": stream})())
        values = ["--runtime-directory", str(args.runtime_directory), "--scheduler-state", str(args.scheduler_state),
            "--expected-policy-sha256", args.expected_policy_sha256, "--_engine"]
        with pytest.raises(custody.LegacySpanEngineCustodyError, match="bounded owner launch"):
            runner.main(values)


def test_service_successor_keeps_resume_publication_and_fits_preserved_envelope():
    dropin = (ROOT / "configs/autoencoders/legacy-cuda-span-census-existing-policy.conf").read_text()
    assert "ExecStart=\n" in dropin
    for retained in ("--max-batches 0", "--upload", "--guided-compiler", "--publication-format paired",
        "legacy-cuda-campaign-20260930/runtime", "--compiler-workers 1", "--bridge-workers 1", "--memory-mb 8192"):
        assert retained in dropin
    assert "--scheduler-state /tmp/ipfs-datasets-resource-scheduler-1000.json" in dropin
    assert "--expected-policy-sha256 f07cb14289fcb6275e4497dcc36be0dcf8bfc3dc87531ff7a9537eb85fdcc661" in dropin
    assert "Restart=no" in dropin and "RuntimeMaxSec=" not in dropin
    # Systemd's outer cgroup must fit the unchanged native headroom plus
    # the real 8192MiB owner/group request. The request itself stays bounded.
    assert "MemoryHigh=36G" in dropin and "MemoryMax=40G" in dropin
    assert 36*1024 >= 24922 + 8192 + 1024


@pytest.mark.parametrize("elapsed", [0, 59.999, 60, 60.001])
def test_startup_deadline_includes_boundaries_and_rejects_expired_work(monkeypatch, elapsed):
    monkeypatch.setattr(custody.time, "monotonic", lambda: 10 + elapsed)
    if elapsed <= 60:
        custody.verify_startup_deadline(10)
    else:
        with pytest.raises(custody.LegacySpanEngineCustodyError, match="startup barrier"):
            custody.verify_startup_deadline(10)


def test_ready_receipt_is_rechecked_after_read_before_acceptance(tmp_path, monkeypatch):
    launch = dict(spec={"runtime_directory":str(tmp_path)}, child={"pid":123,"birth":"fixture"},
        bytecode={"path":str(tmp_path/("a"*32))})
    expected = dict(schema="legacy-span-engine-ready/v1", launch_sha256=custody._sha(launch),
        child=launch["child"], model_executed=False, training_started=False, admitted=False, qualified=False)
    custody.engine_ready_path(launch).write_text(json.dumps(expected))
    clocks = iter([10, 70.001])
    monkeypatch.setattr(custody.time, "monotonic", lambda:next(clocks))
    process = type("ExitedFixture", (), {"poll":lambda self:0})()
    with pytest.raises(custody.LegacySpanEngineCustodyError, match="startup barrier"):
        custody.wait_engine_ready(process, launch, lambda:custody.verify_startup_deadline(10))


def test_old_ready_receipt_never_substitutes_for_this_engine(tmp_path):
    launch = dict(spec={"runtime_directory":str(tmp_path)}, child={"pid":123,"birth":"fixture"},
        bytecode={"path":str(tmp_path/("a"*32))})
    old = dict(schema="legacy-span-engine-ready/v1", launch_sha256="f"*64,
        child=launch["child"], model_executed=False, training_started=False, admitted=False, qualified=False)
    custody.engine_ready_path(launch).write_text(json.dumps(old))
    process = type("ExitedFixture", (), {"poll":lambda self:0})()
    with pytest.raises(custody.LegacySpanEngineCustodyError, match="without its current owner handoff"):
        custody.wait_engine_ready(process, launch, lambda:None)
    assert json.loads(custody.engine_ready_path(launch).read_bytes()) == old


def test_unentered_owner_cannot_prepare_a_bytecode_directory(private):
    path, policy, _, runtime, ledger = private
    resource = resources.LegacySpanCampaignResources(runtime, ledger, storage_bytes=100000,
        memory_mb=1024, cpu_slots=3, child_process_slots=5,
        scheduler_state_path=path, expected_scheduler_policy_sha256=policy)
    with pytest.raises(custody.LegacySpanEngineCustodyError, match="owner reservation lost"):
        resource.prepare_engine_bytecode()
    assert not (runtime/".engine-bytecode").exists()


def test_actual_spawn_time_is_inside_startup_deadline_and_child_is_reaped(private, monkeypatch):
    args = arguments(private)
    clock = [10.0]
    monkeypatch.setattr(custody.time, "monotonic", lambda:clock[0])
    original = subprocess.Popen
    children = []
    def slow_spawn(command, **kwargs):
        child = original([sys.executable,"-B","-c","import time;time.sleep(10)"],
            **dict(kwargs, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        children.append(child)
        clock[0] = 70.001
        return child
    monkeypatch.setattr(runner.subprocess, "Popen", slow_spawn)
    values = ["--runtime-directory", str(args.runtime_directory), "--resource-ledger", str(args.resource_ledger),
        "--scheduler-state",str(args.scheduler_state),"--expected-policy-sha256",args.expected_policy_sha256,
        "--compiler-workers","1","--bridge-workers","1","--memory-mb","1024","--storage-bytes","100000"]
    with pytest.raises(custody.LegacySpanEngineCustodyError, match="startup barrier"):
        runner.main(values)
    assert len(children) == 1 and children[0].poll() is not None
    assert not (args.runtime_directory/"owner.json").exists()
    assert json.loads(args.scheduler_state.read_bytes())["leases"] == {}
    records = json.loads(args.resource_ledger.read_bytes())["reservations"]
    owned = [row for key,row in records.items() if key != "preserved"]
    assert len(owned) == 1 and owned[0]["status"] == "retained"
    assert owned[0]["artifacts_durable_asserted"] is False
    assert owned[0]["legacy_engine_failure_type"] == "LegacySpanEngineCustodyError"


def test_native_cleanup_stops_descendants_after_engine_leader_exits(tmp_path):
    ready = tmp_path/"descendant.json"
    code = "import os,json,time;from pathlib import Path;p=os.fork();" \
        "Path("+repr(str(ready))+").write_text(json.dumps({'child':p})) if p else None;" \
        "time.sleep(0.25) if p else time.sleep(10)"
    child = subprocess.Popen([sys.executable,"-B","-c",code], start_new_session=True,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    identity = custody.owned_child_identity(child)
    try:
        child.wait(timeout=10)
        assert ready.exists() and host._group_usage(identity)["live_processes"] == 1
        runner.stop_child(child, identity)
        assert host._group_usage(identity)["live_processes"] == 0
    finally:
        runner.stop_child(child, identity)



def test_resumed_native_owner_uses_fresh_bytecode_and_preserves_prior_startup(private):
    path, policy, initial, runtime, ledger = private
    preserved = deepcopy(json.loads(ledger.read_bytes())["reservations"]["preserved"])
    args = arguments(private)
    def campaign():
        return resources.LegacySpanCampaignResources(runtime, ledger, storage_bytes=100000,
            memory_mb=1024, cpu_slots=3, child_process_slots=5,
            scheduler_state_path=path, expected_scheduler_policy_sha256=policy)

    first = campaign()
    with first:
        prior = first.prepare_engine_bytecode()
        prior_identity = host._root_identity(prior)
        prior_payload = prior / "foreign.pyc"
        prior_payload.write_bytes(b"retained previous startup bytecode")
        prior_ready = prior.with_name(prior.name + ".ready.json")
        prior_ready.write_bytes(b'{"retained_previous_startup":true}\n')
        first.close(artifacts_durable=True)
    first_row = deepcopy(json.loads(ledger.read_bytes())["reservations"][first.reservation.reservation_id])
    assert first_row["status"] == "released"
    parent_identity = host._root_identity(runtime / ".engine-bytecode")
    prior_bytes = prior_payload.read_bytes(), prior_ready.read_bytes()

    child = None
    second = campaign()
    with second:
        try:
            spare = second.prepare_engine_bytecode()
            bytecode = second.prepare_engine_bytecode()
            assert len({prior.name, spare.name, bytecode.name}) == 3
            for prefix in (spare, bytecode):
                assert prefix.parent == runtime / ".engine-bytecode"
                assert len(prefix.name) == 32 and all(char in "0123456789abcdef" for char in prefix.name)
                assert prefix.stat().st_mode & 0o777 == 0o700
                assert prefix.stat().st_uid == os.geteuid()
                assert list(prefix.iterdir()) == []
            environment = dict(os.environ, PYTHONPATH=str(ROOT), PYTHONDONTWRITEBYTECODE="1",
                PYTHONPYCACHEPREFIX=str(bytecode), IPFS_DATASETS_AUTO_INSTALL="false",
                IPFS_AUTO_INSTALL="false", OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1",
                MKL_NUM_THREADS="1")
            child = subprocess.Popen([sys.executable, "-B", "-c", CHILD, "none"], cwd=ROOT,
                env=environment, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, start_new_session=True)
            launch = second.bind_engine_launch(child.pid, custody.invocation_sha256(args),
                bytecode_directory=bytecode)
            owner = host._process(os.getpid())
            assert launch["owner"] == {key: owner[key] for key in ("pid", "birth")}
            assert launch["bytecode"] == host._root_identity(bytecode)
            assert launch["spec"] == custody.engine_resource_spec(args)
            row = json.loads(ledger.read_bytes())["reservations"][second.reservation.reservation_id]
            assert row["status"] == "active" and row["child"] == launch["child"]
            assert row["attempt_directory"] == host._root_identity(runtime)
            assert row["legacy_engine_launch_sha256"] == custody._sha(launch)
            lease = json.loads(path.read_bytes())["leases"][launch["lease_id"]]
            assert lease["owner_pid"] == owner["pid"] and lease["owner_birth_marker"] == owner["birth"]
            assert lease["request_id"] == "daemon:" + second.reservation.reservation_id
            serialized = json.dumps(launch, sort_keys=True, separators=(",", ":")).encode() + b"\n"
            assert b'"lease_key"' not in serialized
            output, error = child.communicate(serialized, timeout=30)
            assert child.returncode == 0, error.decode()
            assert json.loads(output) == {"verified": True, "model_executed": False, "admitted": False}
            assert list(bytecode.iterdir()) == []
            assert host._root_identity(prior) == prior_identity
            assert host._root_identity(runtime / ".engine-bytecode") == parent_identity
            assert (prior_payload.read_bytes(), prior_ready.read_bytes()) == prior_bytes
            assert set((runtime / ".engine-bytecode").iterdir()) == {prior, prior_ready, spare, bytecode}
            second.close(artifacts_durable=True)
        finally:
            if child is not None and child.poll() is None:
                child.kill()
                child.wait(timeout=10)
    rows = json.loads(ledger.read_bytes())["reservations"]
    assert rows["preserved"] == preserved
    assert rows[first.reservation.reservation_id] == first_row
    assert rows[second.reservation.reservation_id]["status"] == "released"
    final = json.loads(path.read_bytes())
    assert final["config"] == initial["config"]
    assert final["retained_campaign_history"] == initial["retained_campaign_history"]
    assert final["next_sequence"] == initial["next_sequence"] + 2
    assert final["metrics"]["acquisitions_total"] == initial["metrics"]["acquisitions_total"] + 2
    assert final["metrics"]["releases_total"] == initial["metrics"]["releases_total"] + 2
    assert final["leases"] == {} and final["waiters"] == {}


@pytest.mark.parametrize("kind", ["file", "symlink", "dangling_symlink"])
def test_entered_native_owner_refuses_unsafe_existing_bytecode_parent(private, tmp_path, kind):
    path, policy, initial, runtime, ledger = private
    preserved = deepcopy(json.loads(ledger.read_bytes())["reservations"]["preserved"])
    resource = resources.LegacySpanCampaignResources(runtime, ledger, storage_bytes=100000,
        memory_mb=1024, cpu_slots=3, child_process_slots=5,
        scheduler_state_path=path, expected_scheduler_policy_sha256=policy)
    parent = runtime / ".engine-bytecode"
    outside = tmp_path / "outside-bytecode"
    with resource:
        if kind == "file":
            parent.write_bytes(b"retained non-directory startup artifact")
            expected = "resource root is not a directory"
        else:
            if kind == "symlink":
                outside.mkdir()
                (outside / "retained.pyc").write_bytes(b"outside bytes must remain untouched")
            parent.symlink_to(outside, target_is_directory=True)
            expected = "symlink resource path"
        before = parent.lstat()
        with pytest.raises(host.DaemonResourceError, match=expected):
            resource.prepare_engine_bytecode()
        after = parent.lstat()
        assert (after.st_dev, after.st_ino, after.st_mode, after.st_mtime_ns, after.st_ctime_ns) == \
            (before.st_dev, before.st_ino, before.st_mode, before.st_mtime_ns, before.st_ctime_ns)
        assert set(runtime.iterdir()) == {parent}
        assert resource.reservation._child is None
        if kind == "file":
            assert parent.read_bytes() == b"retained non-directory startup artifact"
        else:
            assert parent.is_symlink() and parent.readlink() == outside
            if kind == "symlink":
                assert (outside / "retained.pyc").read_bytes() == b"outside bytes must remain untouched"
                assert set(outside.iterdir()) == {outside / "retained.pyc"}
            else:
                assert not outside.exists()
    rows = json.loads(ledger.read_bytes())["reservations"]
    assert rows["preserved"] == preserved
    assert rows[resource.reservation.reservation_id]["status"] == "retained"
    assert rows[resource.reservation.reservation_id]["child"] is None
    assert rows[resource.reservation.reservation_id]["artifacts_durable_asserted"] is False
    final = json.loads(path.read_bytes())
    assert final["config"] == initial["config"] and final["leases"] == {} and final["waiters"] == {}


def test_entered_native_owner_refuses_uuid_collision_without_reusing_old_bytecode(private, monkeypatch):
    from types import SimpleNamespace
    path, policy, initial, runtime, ledger = private
    preserved = deepcopy(json.loads(ledger.read_bytes())["reservations"]["preserved"])
    resource = resources.LegacySpanCampaignResources(runtime, ledger, storage_bytes=100000,
        memory_mb=1024, cpu_slots=3, child_process_slots=5,
        scheduler_state_path=path, expected_scheduler_policy_sha256=policy)
    with resource:
        prefix = resource.prepare_engine_bytecode()
        before = host._root_identity(prefix)
        payload = prefix / "retained.pyc"
        payload.write_bytes(b"collision must not reuse or clear this prefix")
        # Replace only custody's UUID dependency; native lease heartbeat and
        # state-file UUIDs keep their actual implementation.
        with monkeypatch.context() as patch:
            patch.setattr(custody, "uuid", SimpleNamespace(uuid4=lambda: SimpleNamespace(hex=prefix.name)))
            with pytest.raises(FileExistsError):
                resource.prepare_engine_bytecode()
        assert host._root_identity(prefix) == before
        assert payload.read_bytes() == b"collision must not reuse or clear this prefix"
        assert set(prefix.parent.iterdir()) == {prefix}
        assert resource.reservation._child is None
        resource.close(artifacts_durable=True)
    rows = json.loads(ledger.read_bytes())["reservations"]
    assert rows["preserved"] == preserved
    assert rows[resource.reservation.reservation_id]["status"] == "released"
    final = json.loads(path.read_bytes())
    assert final["config"] == initial["config"] and final["leases"] == {} and final["waiters"] == {}
