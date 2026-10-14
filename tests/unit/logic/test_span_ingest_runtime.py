"""Owned stdlib process/metadata fixtures, never parser/model/Lake inference.

Two real lifecycle cases require pytest plus at most two stdlib descendants.
All private cache files below are opaque authored bytes and never opened as DBs.
"""
import importlib.util
import json
import os
from pathlib import Path
import select
import subprocess
import sys
import time
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.logic.autoformal import span_ingest_runtime as runtime


@pytest.fixture
def spec(tmp_path):
    for directory in ("attempt", "artifacts"):
        (tmp_path/directory).mkdir()
    for name in ("prepared.duckdb", "manifest.json", "scheduler.json", "disk.json"):
        (tmp_path/name).write_bytes(b"{}")
    return dict(schema=runtime.SCHEMA, cache_path=str(tmp_path/"prepared.duckdb"),
        source_manifest_path=str(tmp_path/"manifest.json"), release_id="authored-fixture-no-law",
        attempt_directory=str(tmp_path/"attempt"), resource_ledger_path=str(tmp_path/"disk.json"),
        scheduler_state_path=str(tmp_path/"scheduler.json"), expected_scheduler_policy_sha256="a"*64,
        storage_bytes=1_000_000, memory_mb=2048, cpu_slots=4, child_process_slots=8,
        cache_growth_allowance_bytes=100_000, max_workers=32, per_worker_memory_mb=512,
        per_worker_process_slots=3, batch_size=16, max_spans=32, start_index=0,
        max_examined=256, timeout_seconds=60, full_usage_interval_seconds=15)


@pytest.mark.parametrize("change", [
    {"extra_authority": True}, {"child_process_slots": True}, {"per_worker_process_slots": 2},
    {"max_workers": 33}, {"batch_size": 0}, {"cache_growth_allowance_bytes": 1_000_000},
    {"timeout_seconds": float("inf")}, {"full_usage_interval_seconds": 61},
    {"cache_path": "relative.duckdb"}, {"expected_scheduler_policy_sha256": "not-a-policy"},
])
def test_closed_spec_rejects_unbounded_or_ambiguous_parameters_before_any_admission(spec, change):
    with pytest.raises((runtime.SpanIngestRuntimeError, OSError)):
        runtime.validate_spec({**spec, **change})


@pytest.mark.parametrize("raw", [b'{"schema":1,"schema":2}', b'{"value":NaN}', b'{"value":1e999}'])
def test_control_json_rejects_duplicate_and_nonfinite_data(raw):
    with pytest.raises(runtime.SpanIngestRuntimeError): runtime.parse_json(raw)


def test_worker_capacity_includes_owner_tracker_and_each_lake_lean_floor(spec):
    probe = dict(hardware_cpu_count=32, affinity_cpu_count=32, cgroup_cpu_count=None,
        available_memory_mb=8192, cgroup_memory_remaining_mb=None, probe_errors=[])
    for slots, workers in ((4, 0), (5, 1), (8, 2)):
        result = runtime._size_plan({**spec, "child_process_slots": slots}, probe=probe)
        assert result["workers"] == workers and result["admitted"] is False
    assert runtime._size_plan({**spec, "cpu_slots": 1}, probe=probe)["workers"] == 0
    assert runtime._size_plan({**spec, "memory_mb": 512}, probe=probe)["workers"] == 0


def test_runtime_detaches_original_caller_dictionary_before_validation_or_grants(spec, monkeypatch):
    original = spec
    checked = []
    def verify_detachment(detached):
        assert detached == original and detached is not original
        original["memory_mb"] = 999999
        checked.append(detached["memory_mb"])
    monkeypatch.setattr(runtime, "validate_spec", verify_detachment)
    monkeypatch.setattr(runtime, "CANONICAL_ROOT", Path("/never-canonical-fixture"))
    with pytest.raises(runtime.SpanIngestRuntimeError, match="canonical"):
        runtime.run_fenced_ingest_runtime(spec)
    assert checked == [2048]


def test_prepared_catalog_identity_replacement_refuses_even_with_same_path_and_size(spec):
    path = Path(spec["cache_path"])
    baseline = {"files": runtime._cache_inventory(path), "identity": runtime._cache_identity(path)}
    replacement = path.with_name("new-private-catalog")
    replacement.write_bytes(path.read_bytes())
    os.replace(replacement, path)
    with pytest.raises(runtime.SpanIngestRuntimeError, match="catalog identity changed"):
        runtime._growth(spec, baseline)


@pytest.mark.parametrize("phase", ["baseline", "growth"])
def test_catalog_replacement_during_stat_inventory_refuses_instead_of_mixing_snapshots(spec, monkeypatch, phase):
    path = Path(spec["cache_path"])
    baseline = runtime._cache_baseline(path)
    original = runtime._cache_inventory
    def replacing_inventory(selected):
        value = original(selected)
        replacement = path.with_name("replacement-mid-snapshot")
        replacement.write_bytes(path.read_bytes())
        os.replace(replacement, path)
        return value
    monkeypatch.setattr(runtime, "_cache_inventory", replacing_inventory)
    with pytest.raises(runtime.SpanIngestRuntimeError, match="catalog identity changed"):
        if phase == "baseline": runtime._cache_baseline(path)
        else: runtime._growth(spec, baseline)


def test_wal_rotation_is_allowed_but_actual_growth_remains_bounded(spec):
    path = Path(spec["cache_path"])
    baseline = {"files": runtime._cache_inventory(path), "identity": runtime._cache_identity(path)}
    wal = Path(str(path)+".wal")
    wal.write_bytes(b"a"*10)
    assert runtime._growth(spec, baseline)["growth_bytes"] == 10
    replacement = wal.with_name("rotated-private-wal")
    replacement.write_bytes(b"b"*11)
    os.replace(replacement, wal)
    assert runtime._growth(spec, baseline)["growth_bytes"] == 11
    with pytest.raises(runtime.SpanIngestRuntimeError, match="growth allowance"):
        runtime._growth({**spec, "cache_growth_allowance_bytes": 10}, baseline)


def test_owner_and_child_rss_are_conservatively_summed(monkeypatch):
    monkeypatch.setattr(runtime.resources, "_process", lambda pid: {"pid": pid, "birth": "fixture-birth", "rss_bytes": 100})
    monkeypatch.setattr(runtime, "_group_usage", lambda child: {"available": True, "live_processes": 3, "rss_bytes": 250})
    observed = runtime._combined_usage({"pid": 42, "birth": "fixture-birth"}, {"pid": 43, "birth": "fixture-child"})
    assert observed["combined_rss_bytes"] == 350 and observed["owner_rss_bytes"] == 100
    assert "counted twice" in observed["scope"]


def test_already_exited_success_cannot_escape_the_shared_deadline(monkeypatch):
    monkeypatch.setattr(runtime.time, "monotonic", lambda: 11.01)
    process = SimpleNamespace(poll=lambda: 0)
    assert process.poll() == 0
    with pytest.raises(runtime.SpanIngestRuntimeError, match="deadline"):
        runtime._check_deadline(10, 1)


def test_controller_refuses_successful_exit_after_deadline_before_reading_any_success_evidence(spec, monkeypatch):
    """Negative framework fixture; no native grant, child, DB or inference."""
    clock = [0.0]
    monkeypatch.setattr(runtime.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(runtime, "CANONICAL_ROOT", runtime.ROOT)
    roots = [runtime.resources._root_identity(Path(spec["cache_path"]).parent)]
    monkeypatch.setattr(runtime, "_ledger", lambda path: {"roots": roots})
    monkeypatch.setattr(runtime, "_pins", lambda: [])
    monkeypatch.setattr(runtime, "_size_plan", lambda request: {"workers": 1})
    class FixtureReservation:
        reservation_id = "fixture-no-native-grant"
        cancelled = False
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def check_usage(self, *args, **kwargs): return {}
        def account_external_bytes(self, *args): return {}
        def _update(self, **kwargs): pass
        def heartbeat(self): return True
        def to_dict(self): return {"resource_lease": {"lease_id": "fixture-not-a-lease"}, "scope": "negative framework fixture"}
    monkeypatch.setattr(runtime.resources, "DaemonResourceReservation", lambda *args, **kwargs: FixtureReservation())
    process = SimpleNamespace(pid=4242, returncode=0, poll=lambda: 0)
    monkeypatch.setattr(runtime.subprocess, "Popen", lambda *args, **kwargs: process)
    monkeypatch.setattr(runtime.resources, "_process", lambda pid: {"pid": pid, "birth": "fixture-birth", "rss_bytes": 0})
    monkeypatch.setattr(runtime, "_feed_launch", lambda *args: clock.__setitem__(0, 2.0))
    monkeypatch.setattr(runtime, "_terminate", lambda *args: None)
    monkeypatch.setattr(runtime, "_group_usage", lambda child: {"available": True, "live_processes": 0, "rss_bytes": 0})
    with pytest.raises(runtime.SpanIngestRuntimeError, match="deadline"):
        runtime.run_fenced_ingest_runtime({**spec, "timeout_seconds": 1})
    failure = runtime.parse_json((Path(spec["attempt_directory"])/"runtime-failure.json").read_bytes(), runtime.MAX_REPORT_BYTES)
    assert failure["status"] == "failed_bounded_fenced_ingestion"
    assert all(failure[field] is False for field in runtime.FALSE)
    assert not (Path(spec["attempt_directory"])/"child-report.json").exists()


def test_actual_nonreading_owned_child_launch_pipe_obeys_deadline_and_stops():
    import fcntl
    process = subprocess.Popen([sys.executable, "-B", "-c", "import time; time.sleep(30)"],
        stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    observed = runtime.resources._process(process.pid)
    assert observed is not None
    identity = {key: observed[key] for key in ("pid", "birth")}
    try:
        # Bound the genuine pipe below the maximum legal launch payload. No
        # inference or native reservation is fabricated by this lifecycle case.
        fcntl.fcntl(process.stdin.fileno(), fcntl.F_SETPIPE_SZ, 4096)
        started = time.monotonic()
        with pytest.raises(runtime.SpanIngestRuntimeError, match="deadline"):
            runtime._feed_launch(process, b"x"*runtime.MAX_CONTROL_BYTES,
                                 lambda: runtime._check_deadline(started, 0.2))
    finally:
        runtime._terminate(process, identity)
        process.stdin.close()
    assert process.poll() is not None and runtime._group_usage(identity)["live_processes"] == 0


def test_actual_group_cleanup_stops_descendant_after_coordinator_already_exited():
    source = "import subprocess,sys; sys.stdin.readline(); child=subprocess.Popen([sys.executable,'-B','-c','import time; time.sleep(30)']); print(child.pid,flush=True)"
    process = subprocess.Popen([sys.executable, "-B", "-c", source], stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, start_new_session=True)
    observed = runtime.resources._process(process.pid)
    assert observed is not None
    identity = {key: observed[key] for key in ("pid", "birth")}
    try:
        process.stdin.write(b"go\n")
        process.stdin.close()
        assert select.select([process.stdout], [], [], 2)[0]
        assert int(process.stdout.readline()) > 0
        process.wait(timeout=2)
        assert process.returncode == 0 and runtime._group_usage(identity)["live_processes"] >= 1
    finally:
        runtime._terminate(process, identity)
        process.stdout.close()
    assert runtime._group_usage(identity)["live_processes"] == 0


def test_unowned_direct_fenced_cli_refuses_before_compiler_preflight_or_database_open(tmp_path, monkeypatch):
    path = Path(__file__).resolve().parents[3]/"scripts/ops/legal_ir/ingest_ipfs_uscode_corpus.py"
    definition = importlib.util.spec_from_file_location("unowned_fenced_cli_fixture", path)
    cli = importlib.util.module_from_spec(definition)
    definition.loader.exec_module(cli)
    monkeypatch.setattr(cli, "_fenced_compiler_preflight", lambda: pytest.fail("unowned run reached inference preflight"))
    with pytest.raises(ValueError, match="native-owned runtime"):
        cli.main(["--claim-profile", "fenced-v1", "--cache", str(tmp_path/"never-opened.duckdb"),
                  "--source-manifest", str(tmp_path/"absent.json")])
    assert not (tmp_path/"never-opened.duckdb").exists()


def test_child_gate_rejects_missing_extra_or_forged_authority_before_native_lookup(monkeypatch):
    monkeypatch.setattr(runtime, "open_existing_scheduler", lambda *args: pytest.fail("malformed launch reached scheduler"))
    with pytest.raises(runtime.SpanIngestRuntimeError, match="closed native launch"):
        runtime.FencedIngestChildVerifier({"schema": runtime.LAUNCH_SCHEMA, "lease_key": "forged"})


def test_large_complete_census_is_retained_behind_bounded_stream_verified_transport(spec, monkeypatch):
    """Authored transport bytes only; no native grant, model or law result."""
    report = {"status": "completed_selected_fenced_work", "processed": 1, "resumed": 0,
        "held": [], "resource_admission_verified_by_cli": True, **runtime.FALSE,
        "completions": [{"complete_authored_observation": "x"*(runtime.MAX_REPORT_BYTES+1)}]}
    request = {**spec, "storage_bytes": 32*1024*1024}
    transport = runtime.stage_child_report(report, request, "fixture-no-native-grant")
    assert len(runtime.canonical_bytes(transport)) <= runtime.MAX_CONTROL_BYTES
    full_path = Path(request["attempt_directory"])/"census-report.json"
    assert full_path.stat().st_size > runtime.MAX_REPORT_BYTES
    assert json.loads(full_path.read_bytes()) == report
    # A reader of the bounded transport must not use the whole-file JSON
    # snapshot reader to verify the large body.
    monkeypatch.setattr(runtime, "_read_regular_snapshot", lambda *args, **kwargs: pytest.fail("loaded complete report into owner"))
    assert runtime.verify_child_report(transport, request, "fixture-no-native-grant") == transport["full_report"]
    assert all(transport[key] is False for key in runtime.FALSE)


@pytest.mark.parametrize("mutation", ["bytes", "reservation", "authority", "outside", "aliased"])
def test_complete_census_transport_cannot_hide_changed_bytes_scope_or_authority(spec, mutation, tmp_path):
    report = {"status": "completed_selected_fenced_work", "processed": 1, "resumed": 0,
        "held": [], "resource_admission_verified_by_cli": True, **runtime.FALSE,
        "completions": [{"observation": "authored fixture"}]}
    transport = runtime.stage_child_report(report, spec, "fixture-no-native-grant")
    full_path = Path(spec["attempt_directory"])/"census-report.json"
    if mutation == "bytes":
        full_path.write_bytes(full_path.read_bytes().replace(b"authored fixture", b"altered! fixture"))
    elif mutation == "reservation": transport["native_reservation_id"] = "other-owner"
    elif mutation == "authority": transport["admitted"] = True
    elif mutation == "outside": transport["full_report"]["path"] = str(tmp_path/"outside.json")
    elif mutation == "aliased": os.link(full_path, tmp_path/"alias.json")
    with pytest.raises(runtime.SpanIngestRuntimeError):
        runtime.verify_child_report(transport, spec, "fixture-no-native-grant")


@pytest.mark.parametrize("mutation", [None, "owner_birth", "child_birth", "lease", "roots", "attempt", "digest", "environment", "bytecode", "catalog"])
def test_actual_private_native_child_verifier_join_and_exact_field_refusals(spec, tmp_path, monkeypatch, mutation):
    """Real private native join, explicitly G-metadata-only; no DB/inference."""
    import hashlib
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import existing_resource_scheduler as existing
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import resource_scheduler as native
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.proof_resource_safety import ProofHostResources
    state_path = Path(spec["scheduler_state_path"])
    state_path.unlink()
    native.GlobalResourceScheduler(native.ResourceSchedulerConfig(state_path=state_path,
        total_cpu_slots=4, total_memory_mb=4096, total_child_process_slots=8,
        lane_reservations={}, proof_safety_enabled=True, auto_renew_leases=False))
    spec = {**spec, "expected_scheduler_policy_sha256": existing.policy_sha256(json.loads(state_path.read_bytes())["config"])}
    original_factory = existing.open_existing_scheduler
    def healthy_private_factory(*args):
        facade = original_factory(*args)
        facade.config.proof_resource_sampler = lambda: ProofHostResources(8, 8192, 8192,
            pid_task_limit=500, available_pid_tasks=400)
        facade.config.auto_renew_leases = False
        return facade
    monkeypatch.setattr(existing, "open_existing_scheduler", healthy_private_factory)
    ledger = Path(spec["resource_ledger_path"])
    ledger.unlink()
    seed = runtime.resources.DaemonResourceReservation(ledger, roots=[tmp_path], storage_bytes=spec["storage_bytes"], memory_mb=spec["memory_mb"])
    seed._write(seed._read())
    owned = runtime.resources.DaemonResourceReservation(ledger, roots=[tmp_path], storage_bytes=spec["storage_bytes"],
        memory_mb=spec["memory_mb"], cpu_slots=spec["cpu_slots"], child_process_slots=spec["child_process_slots"],
        scheduler_state_path=state_path, expected_scheduler_policy_sha256=spec["expected_scheduler_policy_sha256"], require_existing_ledger=True)
    attempt = Path(spec["attempt_directory"])
    for name in ("tmp", "spill", "exchange", "bytecode"): (attempt/name).mkdir()
    source = """
import json,sys
from ipfs_datasets_py.logic.autoformal import span_ingest_runtime as r
# Metadata-only G fixture, not canonical compiler deployment or inference.
r.CANONICAL_ROOT=r.ROOT
try:
    verifier=r.FencedIngestChildVerifier(r.parse_json(sys.stdin.buffer.readline(r.MAX_CONTROL_BYTES+2)))
    verifier.verify()
    print(json.dumps({'checked':True,'scope':'private native metadata only','qualified':False,'admitted':False}),flush=True)
except Exception as error:
    print(json.dumps({'checked':False,'error_type':type(error).__name__,'qualified':False,'admitted':False}),flush=True)
"""
    environment = dict(os.environ, TMPDIR=str(attempt/"tmp"), TMP=str(attempt/"tmp"), TEMP=str(attempt/"tmp"),
        LEAN_NUM_THREADS="1", PYTHONDONTWRITEBYTECODE="1", PYTHONPYCACHEPREFIX=str(attempt/"bytecode"))
    if mutation == "environment": environment["TMPDIR"] = str(tmp_path)
    if mutation == "bytecode": environment["PYTHONPYCACHEPREFIX"] = str(tmp_path)
    process, identity = None, None
    with owned:
        try:
            process = subprocess.Popen([sys.executable, "-B", "-c", source], cwd=runtime.ROOT, env=environment,
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
            child = runtime.resources._process(process.pid)
            assert child is not None
            identity = {key: child[key] for key in ("pid", "birth")}
            owned.check_usage(attempt, child_pid=process.pid)
            owned.account_external_bytes("prepared-cache-growth", spec["cache_growth_allowance_bytes"])
            parent = runtime.resources._process(os.getpid())
            launch = dict(schema=runtime.LAUNCH_SCHEMA, spec=spec,
                spec_sha256=hashlib.sha256(runtime.canonical_bytes(spec)).hexdigest(),
                owner={key: parent[key] for key in ("pid", "birth")}, child=dict(identity),
                lease_id=owned.to_dict()["resource_lease"]["lease_id"], reservation_id=owned.reservation_id,
                roots=owned.root_identities, workers=1, capacity_plan={"workers":1},
                cache_baseline=runtime._cache_baseline(spec["cache_path"]),
                source_manifest=runtime._reference(spec["source_manifest_path"],16*1024*1024), producer_pins=runtime._pins())
            owned._update(fenced_launch_sha256=hashlib.sha256(runtime.canonical_bytes(launch)).hexdigest())
            # Mutate only after the native owner bound the original envelope.
            if mutation == "owner_birth": launch["owner"]["birth"] = "forged"
            if mutation == "child_birth": launch["child"]["birth"] = "forged"
            if mutation == "lease": launch["lease_id"] = "not-the-native-lease"
            if mutation == "roots": launch["roots"] = []
            if mutation == "attempt":
                other = tmp_path/"other-attempt"
                other.mkdir()
                launch["spec"]["attempt_directory"] = str(other)
                launch["spec_sha256"] = hashlib.sha256(runtime.canonical_bytes(launch["spec"])).hexdigest()
            if mutation == "digest": launch["spec_sha256"] = "b"*64
            if mutation == "catalog":
                replacement = tmp_path/"replaced-private-catalog"
                replacement.write_bytes(Path(spec["cache_path"]).read_bytes())
                os.replace(replacement,spec["cache_path"])
            started = time.monotonic()
            runtime._feed_launch(process, runtime.canonical_bytes(launch)+b"\n", lambda: runtime._check_deadline(started,15))
            process.wait(timeout=15)
            assert process.returncode == 0, process.stderr.read().decode()
            observation = json.loads(process.stdout.read())
            assert observation["checked"] is (mutation is None)
            assert observation["qualified"] is observation["admitted"] is False
        finally:
            if process is not None: runtime._terminate(process,identity)
            if process is not None:
                for stream in (process.stdin,process.stdout,process.stderr):
                    if stream is not None: stream.close()
        owned.check_usage(attempt)
        owned.finalize(attempt,artifacts_durable=True)
