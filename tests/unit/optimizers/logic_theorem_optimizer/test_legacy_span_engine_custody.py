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



READY_CHILD = r'''import json,os,select,sys,time
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legacy_span_engine_custody import (
    LegacySpanEngineVerifier,read_engine_launch)
launch=read_engine_launch(sys.stdin.buffer)
verifier=LegacySpanEngineVerifier(launch,dict(launch['spec']))
path=verifier.ready_path()
assert not path.exists()
control=int(sys.argv[1])
def await_command(expected):
    deadline=time.monotonic()+10
    while True:
        verifier.verify()
        remaining=deadline-time.monotonic()
        if remaining<=0: raise RuntimeError('bounded test child control timed out')
        if select.select([control],[],[],min(remaining,0.05))[0]:
            assert os.read(control,1)==expected
            return
await_command(b'R')
receipt=verifier.ready_receipt()
temporary=path.with_name(path.name+'.child.tmp')
temporary.write_text(json.dumps(receipt,sort_keys=True,separators=(',',':'))+'\n')
os.replace(temporary,path)
await_command(b'F')
os.close(control)
print(json.dumps(dict(ready=receipt,model_executed=False,training_started=False,admitted=False)))
'''


def test_actual_native_child_ready_wait_polls_missing_leaf_before_current_handoff(private):
    import time
    path, policy, initial, runtime, ledger = private
    preserved = deepcopy(json.loads(ledger.read_bytes())["reservations"]["preserved"])
    args = arguments(private)
    resource = resources.LegacySpanCampaignResources(runtime, ledger, storage_bytes=100000,
        memory_mb=1024, cpu_slots=3, child_process_slots=5,
        scheduler_state_path=path, expected_scheduler_policy_sha256=policy)
    child = None
    read_fd = write_fd = None
    callbacks = []
    with resource:
        try:
            bytecode = resource.prepare_engine_bytecode()
            read_fd, write_fd = os.pipe()
            environment = dict(os.environ, PYTHONPATH=str(ROOT), PYTHONDONTWRITEBYTECODE="1",
                PYTHONPYCACHEPREFIX=str(bytecode), IPFS_DATASETS_AUTO_INSTALL="false",
                IPFS_AUTO_INSTALL="false", OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1",
                MKL_NUM_THREADS="1")
            started = time.monotonic()
            child = subprocess.Popen([sys.executable, "-B", "-c", READY_CHILD, str(read_fd)], cwd=ROOT,
                env=environment, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, start_new_session=True, pass_fds=(read_fd,))
            os.close(read_fd)
            read_fd = None
            launch = resource.bind_engine_launch(child.pid, custody.invocation_sha256(args),
                bytecode_directory=bytecode)
            ready_path = custody.engine_ready_path(launch)
            assert not ready_path.exists()
            serialized = json.dumps(launch, sort_keys=True, separators=(",", ":")).encode() + b"\n"
            assert b'"lease_key"' not in serialized
            child.stdin.write(serialized)
            child.stdin.close()
            child.stdin = None

            def verify_live():
                custody.verify_startup_deadline(started)
                assert child.poll() is None
                assert custody.owned_child_identity(child) == launch["child"]
                assert resource.reservation.heartbeat() and not resource.reservation.cancelled
                resource.check_limits(full=True)
                owner = host._process(os.getpid())
                assert launch["owner"] == {key: owner[key] for key in ("pid", "birth")}
                lease = json.loads(path.read_bytes())["leases"][launch["lease_id"]]
                assert lease["owner_pid"] == owner["pid"] and lease["owner_birth_marker"] == owner["birth"]
                assert lease["request_id"] == "daemon:" + resource.reservation.reservation_id
                row = json.loads(ledger.read_bytes())["reservations"][resource.reservation.reservation_id]
                assert row["status"] == "active" and row["child"] == launch["child"]
                assert row["attempt_directory"] == host._root_identity(runtime)
                assert row["legacy_engine_launch_sha256"] == custody._sha(launch)
                callbacks.append(ready_path.exists())
                if len(callbacks) == 1:
                    # The child cannot write until the second loop callback,
                    # so this first iteration must exercise missing-leaf polling.
                    assert callbacks[-1] is False
                elif len(callbacks) == 2:
                    assert os.write(write_fd, b"R") == 1
                custody.verify_startup_deadline(started)

            ready = custody.wait_engine_ready(child, launch, verify_live)
            assert len(callbacks) >= 3 and callbacks[0] is False
            assert ready == dict(schema="legacy-span-engine-ready/v1", launch_sha256=custody._sha(launch),
                child=launch["child"], model_executed=False, training_started=False,
                admitted=False, qualified=False)
            assert json.loads(ready_path.read_bytes()) == ready
            assert child.poll() is None
            assert os.write(write_fd, b"F") == 1
            output, error = child.communicate(timeout=15)
            assert child.returncode == 0, error.decode()
            assert json.loads(output) == dict(ready=ready, model_executed=False,
                training_started=False, admitted=False)
            assert list(bytecode.iterdir()) == []
            resource.close(artifacts_durable=True)
        finally:
            for descriptor in (read_fd, write_fd):
                if descriptor is not None:
                    os.close(descriptor)
            if child is not None and child.poll() is None:
                child.kill()
                child.wait(timeout=10)
    rows = json.loads(ledger.read_bytes())["reservations"]
    assert rows["preserved"] == preserved
    assert rows[resource.reservation.reservation_id]["status"] == "released"
    final = json.loads(path.read_bytes())
    assert final["config"] == initial["config"]
    assert final["retained_campaign_history"] == initial["retained_campaign_history"]
    assert final["next_sequence"] == initial["next_sequence"] + 1
    assert final["metrics"]["acquisitions_total"] == initial["metrics"]["acquisitions_total"] + 1
    assert final["metrics"]["releases_total"] == initial["metrics"]["releases_total"] + 1
    assert final["leases"] == {} and final["waiters"] == {}


@pytest.mark.parametrize("kind", ["missing_parent", "symlink", "directory", "hardlink", "malformed"])
def test_ready_wait_refuses_invalid_parent_or_receipt_before_polling(tmp_path, kind):
    directory = tmp_path / "absent-parent" if kind == "missing_parent" else tmp_path
    launch = dict(spec={"runtime_directory": str(tmp_path)}, child={"pid": 123, "birth": "path-fixture"},
        bytecode={"path": str(directory / ("a" * 32))})
    ready_path = custody.engine_ready_path(launch)
    before = None
    if kind == "symlink":
        target = tmp_path / "retained-target.json"
        target.write_bytes(b'{"retained":true}\n')
        ready_path.symlink_to(target)
        error, message = host.DaemonResourceError, "symlink resource path"
    elif kind == "directory":
        ready_path.mkdir()
        error, message = host.DaemonResourceError, "resource file is not regular"
    elif kind == "hardlink":
        target = tmp_path / "retained-target.json"
        target.write_bytes(b'{"retained":true}\n')
        os.link(target, ready_path)
        error, message = custody.LegacySpanEngineCustodyError, "bounded unaliased"
    elif kind == "malformed":
        ready_path.write_bytes(b"{not-json")
        error, message = json.JSONDecodeError, None
    else:
        error, message = host.DaemonResourceError, "missing resource path"
    if kind != "missing_parent":
        info = ready_path.lstat()
        before = info.st_dev, info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns, info.st_ctime_ns
    calls = []
    process = type("NoPolling", (), {"poll": lambda self: pytest.fail("invalid readiness path was polled")})()
    with pytest.raises(error, match=message):
        custody.wait_engine_ready(process, launch, lambda: calls.append("verified"))
    assert calls == ["verified"]
    if before is not None:
        info = ready_path.lstat()
        assert (info.st_dev, info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns, info.st_ctime_ns) == before
    if kind in ("symlink", "hardlink"):
        assert target.read_bytes() == b'{"retained":true}\n'
    elif kind == "malformed":
        assert ready_path.read_bytes() == b"{not-json"
    elif kind == "missing_parent":
        assert not directory.exists()


LOCK_WAIT_CHILD = r'''import json,sys
from ipfs_datasets_py.logic.autoformal import span_ingest_runtime as metadata
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legacy_span_engine_custody as c
# One tiny actual private producer file exercises a source change without
# editing canonical modules. This is metadata-only, never source admission.
c.PRODUCER_FILES = (*c.PRODUCER_FILES, sys.argv[1])
launch=c.read_engine_launch(sys.stdin.buffer)
actual_ledger=metadata._ledger
actual_flock=metadata.resources.fcntl.flock
budget=None
reported=False
def ledger(path, *, lock_timeout_seconds=5):
    global budget
    budget=lock_timeout_seconds
    return actual_ledger(path,lock_timeout_seconds=lock_timeout_seconds)
def observed_flock(fd,operation):
    global reported
    try:
        return actual_flock(fd,operation)
    except BlockingIOError:
        if not reported and budget is not None:
            reported=True
            print(json.dumps({'event':'actual_disk_lock_blocked','lock_timeout_seconds':budget,
                'model_executed':False,'admitted':False}),flush=True)
        raise
metadata._ledger=ledger
metadata.resources.fcntl.flock=observed_flock
try:
    c.LegacySpanEngineVerifier(launch,dict(launch['spec']))
except Exception as error:
    print(json.dumps({'verified':False,'error_type':type(error).__name__,
        'error':str(error),'model_executed':False,'admitted':False}),flush=True)
    raise SystemExit(2)
print(json.dumps({'verified':True,'model_executed':False,'admitted':False}),flush=True)
'''


def _private_child_line(process, timeout=15):
    import select
    assert select.select([process.stdout], [], [], timeout)[0], "private child observation timed out"
    line = process.stdout.readline()
    assert line, "private child exited before its observation"
    return json.loads(line)


@pytest.mark.parametrize("change", ["none", "expire_lease", "release_lease", "cancel_lease", "source", "bytecode"])
def test_actual_native_engine_refreshes_custody_after_held_disk_lock(private, monkeypatch, change):
    """Actual lease/birth/row and flock; no cache, CUDA, model or legal result."""
    import time
    path, policy, initial, runtime, ledger = private
    preserved = deepcopy(json.loads(ledger.read_bytes())["reservations"]["preserved"])
    source_observation = runtime.parent / "private-producer-observation.py"
    source_observation.write_bytes(b"# actual private initial source observation\n")
    monkeypatch.setattr(custody, "PRODUCER_FILES", (*custody.PRODUCER_FILES, str(source_observation)))
    args = arguments(private)
    resource = resources.LegacySpanCampaignResources(runtime, ledger, storage_bytes=100000,
        memory_mb=1024, cpu_slots=3, child_process_slots=5,
        scheduler_state_path=path, expected_scheduler_policy_sha256=policy)
    child = None
    descriptor = None
    with resource:
        try:
            bytecode = resource.prepare_engine_bytecode()
            environment = dict(os.environ, PYTHONPATH=str(ROOT), PYTHONDONTWRITEBYTECODE="1",
                PYTHONPYCACHEPREFIX=str(bytecode), IPFS_DATASETS_AUTO_INSTALL="false",
                IPFS_AUTO_INSTALL="false", OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1")
            started = time.monotonic()
            child = subprocess.Popen([sys.executable, "-B", "-c", LOCK_WAIT_CHILD, str(source_observation)],
                cwd=ROOT, env=environment, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, start_new_session=True)
            launch = resource.bind_engine_launch(child.pid, custody.invocation_sha256(args), bytecode_directory=bytecode)
            descriptor = os.open(ledger.with_name(ledger.name + ".lock"), os.O_RDWR | os.O_NOFOLLOW)
            host.fcntl.flock(descriptor, host.fcntl.LOCK_EX | host.fcntl.LOCK_NB)
            child.stdin.write(json.dumps(launch, sort_keys=True, separators=(",", ":")).encode() + b"\n")
            child.stdin.close()
            child.stdin = None
            blocked = _private_child_line(child)
            assert blocked == dict(event="actual_disk_lock_blocked", lock_timeout_seconds=60,
                model_executed=False, admitted=False)
            assert child.poll() is None
            if change == "none":
                # Real elapsed contention exceeds the historical five-second
                # read budget. No clock, flock result or authority is mocked.
                time.sleep(5.2)
                assert child.poll() is None
            elif change == "expire_lease":
                with resource.reservation._lease._scheduler._locked_state() as state:
                    state["leases"][launch["lease_id"]]["expires_at"] = time.time() - 1
            elif change == "release_lease":
                assert resource.reservation._lease.release()
            elif change == "cancel_lease":
                assert resource.reservation._lease.cancel()
            elif change == "source":
                source_observation.write_bytes(b"# actual private changed source observation\n")
            else:
                (bytecode / "unexpected.pyc").write_bytes(b"retained bytecode refusal fixture")
            host.fcntl.flock(descriptor, host.fcntl.LOCK_UN)
            os.close(descriptor)
            descriptor = None
            output, error = child.communicate(timeout=15)
            assert child.returncode == (0 if change == "none" else 2), error.decode()
            result = json.loads(output)
            assert result["verified"] is (change == "none")
            assert result["model_executed"] is result["admitted"] is False
            if change == "source":
                assert "source generation changed while reading disk metadata" in result["error"]
            elif change == "bytecode":
                assert "bytecode directory is not empty" in result["error"]
            elif change != "none":
                assert "lease" in result["error"]
            custody.verify_startup_deadline(started)
            resource.close(artifacts_durable=True)
        finally:
            if descriptor is not None:
                host.fcntl.flock(descriptor, host.fcntl.LOCK_UN)
                os.close(descriptor)
            if child is not None and child.poll() is None:
                child.kill()
                child.wait(timeout=10)
            if child is not None:
                for stream in (child.stdin, child.stdout, child.stderr):
                    if stream is not None:
                        stream.close()
    final = json.loads(path.read_bytes())
    assert final["config"] == initial["config"]
    assert final["retained_campaign_history"] == initial["retained_campaign_history"]
    assert json.loads(ledger.read_bytes())["reservations"]["preserved"] == preserved
    assert json.loads(ledger.read_bytes())["reservations"][resource.reservation.reservation_id]["status"] == "released"


LOCK_WAIT_OWNER = r'''import hashlib,json,os,subprocess,sys,time
from pathlib import Path
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import existing_resource_scheduler as existing
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import resource_scheduler as native
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legacy_span_campaign_resources as resources
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legacy_span_engine_custody as c
request=json.loads(sys.stdin.readline())
actual_factory=existing.open_existing_scheduler
def private_factory(*args):
    facade=actual_factory(*args)
    facade.config.proof_resource_sampler=lambda:native.ProofHostResources(
        8,32768,32768,pid_task_limit=500,available_pid_tasks=400)
    facade.config.auto_renew_leases=False
    return facade
existing.open_existing_scheduler=private_factory
c.PRODUCER_FILES=(*c.PRODUCER_FILES,request['source_observation'])
resource=resources.LegacySpanCampaignResources(request['runtime'],request['ledger'],
    storage_bytes=100000,memory_mb=1024,cpu_slots=3,child_process_slots=5,
    scheduler_state_path=request['scheduler'],expected_scheduler_policy_sha256=request['policy'])
with resource:
    bytecode=resource.prepare_engine_bytecode()
    environment=dict(os.environ,PYTHONPATH=request['root'],PYTHONDONTWRITEBYTECODE='1',
        PYTHONPYCACHEPREFIX=str(bytecode),IPFS_DATASETS_AUTO_INSTALL='false',IPFS_AUTO_INSTALL='false',
        OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='1')
    child=subprocess.Popen([sys.executable,'-B','-c',request['child_source'],request['source_observation']],
        cwd=request['root'],env=environment,stdin=subprocess.PIPE,stdout=sys.stdout,stderr=sys.stderr,
        start_new_session=True)
    launch=resource.bind_engine_launch(child.pid,hashlib.sha256(json.dumps(request,sort_keys=True).encode()).hexdigest(),
        bytecode_directory=bytecode)
    print(json.dumps({'event':'bound','owner':launch['owner'],'child':launch['child'],
        'reservation_id':launch['reservation_id'],'lease_id':launch['lease_id']}),flush=True)
    assert sys.stdin.readline()=='G\n'
    child.stdin.write(json.dumps(launch,sort_keys=True,separators=(',',':')).encode()+b'\n')
    child.stdin.close()
    child.wait(timeout=30)
    resource.close(artifacts_durable=True)
'''


def test_actual_native_engine_cannot_accept_owner_exit_during_disk_lock_wait(private):
    """A real isolated owner dies; its actual child must refuse after unlock."""
    import signal
    import time
    path, policy, initial, runtime, ledger = private
    preserved = deepcopy(json.loads(ledger.read_bytes())["reservations"]["preserved"])
    source_observation = runtime.parent / "owner-exit-producer-observation.py"
    source_observation.write_bytes(b"# actual private source observation\n")
    request = dict(runtime=str(runtime), ledger=str(ledger), scheduler=str(path), policy=policy,
        root=str(ROOT), source_observation=str(source_observation), child_source=LOCK_WAIT_CHILD)
    environment = dict(os.environ, PYTHONPATH=str(ROOT), PYTHONDONTWRITEBYTECODE="1",
        IPFS_DATASETS_AUTO_INSTALL="false", IPFS_AUTO_INSTALL="false", OMP_NUM_THREADS="1",
        OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1")
    owner = subprocess.Popen([sys.executable, "-B", "-c", LOCK_WAIT_OWNER], cwd=ROOT,
        env=environment, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        start_new_session=True)
    descriptor = None
    child_identity = None
    try:
        owner.stdin.write(json.dumps(request).encode() + b"\n")
        owner.stdin.flush()
        bound = _private_child_line(owner)
        assert bound["event"] == "bound" and bound["owner"]["pid"] == owner.pid
        actual_owner = host._process(owner.pid)
        assert bound["owner"] == {key: actual_owner[key] for key in ("pid", "birth")}
        child_identity = bound["child"]
        row = json.loads(ledger.read_bytes())["reservations"][bound["reservation_id"]]
        assert row["status"] == "active" and row["owner_pid"] == owner.pid and row["child"] == child_identity
        descriptor = os.open(ledger.with_name(ledger.name + ".lock"), os.O_RDWR | os.O_NOFOLLOW)
        host.fcntl.flock(descriptor, host.fcntl.LOCK_EX | host.fcntl.LOCK_NB)
        owner.stdin.write(b"G\n")
        owner.stdin.flush()
        blocked = _private_child_line(owner)
        assert blocked == dict(event="actual_disk_lock_blocked", lock_timeout_seconds=60,
            model_executed=False, admitted=False)
        owner.terminate()
        owner.wait(timeout=10)
        assert host._process(owner.pid) is None
        host.fcntl.flock(descriptor, host.fcntl.LOCK_UN)
        os.close(descriptor)
        descriptor = None
        result = _private_child_line(owner)
        assert result["verified"] is False and result["model_executed"] is result["admitted"] is False
        assert "actual isolated direct child" in result["error"] or "owner birth or liveness" in result["error"]
        deadline = time.monotonic() + 5
        while host._group_usage(child_identity)["live_processes"] and time.monotonic() < deadline:
            time.sleep(0.05)
        assert host._group_usage(child_identity)["live_processes"] == 0
        after = json.loads(ledger.read_bytes())["reservations"]
        assert after["preserved"] == preserved
        assert after[bound["reservation_id"]]["status"] != "released"
        assert after[bound["reservation_id"]]["storage_bytes"] == 100000
        final = json.loads(path.read_bytes())
        assert final["config"] == initial["config"]
        assert final["retained_campaign_history"] == initial["retained_campaign_history"]
    finally:
        if descriptor is not None:
            host.fcntl.flock(descriptor, host.fcntl.LOCK_UN)
            os.close(descriptor)
        if owner.poll() is None:
            owner.kill()
            owner.wait(timeout=10)
        if child_identity is not None:
            observed = host._process(child_identity["pid"])
            if observed is not None and observed["birth"] == child_identity["birth"]:
                try:
                    os.killpg(child_identity["pid"], signal.SIGKILL)
                except ProcessLookupError:
                    pass
        for stream in (owner.stdin, owner.stdout, owner.stderr):
            if stream is not None:
                stream.close()
