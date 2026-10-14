"""Native-owned, bounded fenced ingestion; engineering custody is not admission.

The external owner holds the real resource reservation and polls while its
isolated coordinator waits on compiler workers. The coordinator receives no
native lease key and opens the sole SpanCache only after a verified barrier.
"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import math
import os
from pathlib import Path
import signal
import stat
import subprocess
import sys
import time
import uuid

from .span_cache_exchange import _immutable_write, _read_regular_snapshot
from .supervisor_queue import canonical_bytes
from ...optimizers.logic_theorem_optimizer import autoencoder_capacity as capacity
from ...optimizers.logic_theorem_optimizer import autoencoder_daemon_resources as resources
from ...optimizers.logic_theorem_optimizer.autoencoder_daemon_invocation import _terminate, _group_usage
from ...optimizers.logic_theorem_optimizer.existing_resource_scheduler import open_existing_scheduler

ROOT = Path(__file__).resolve().parents[3]
CANONICAL_ROOT = Path("/home/barberb/lift_coding/external/ipfs_datasets")
SCHEMA = "span-fenced-runtime-spec/v1"
LAUNCH_SCHEMA = "span-fenced-runtime-launch/v1"
MAX_CONTROL_BYTES = 65_536
MAX_REPORT_BYTES = 16 * 1024 * 1024
CHILD_REPORT_SCHEMA = "span-fenced-child-report/v1"
FALSE = dict(qualified=False, admitted=False, formalized=False, roundtrip_ok=False,
             model_executed=False, training_started=False, Hub_upload_performed=False)
SPEC_FIELDS = frozenset(("schema", "cache_path", "source_manifest_path", "release_id", "attempt_directory",
    "resource_ledger_path", "scheduler_state_path", "expected_scheduler_policy_sha256", "storage_bytes",
    "memory_mb", "cpu_slots", "child_process_slots", "cache_growth_allowance_bytes", "max_workers",
    "per_worker_memory_mb", "per_worker_process_slots", "batch_size", "max_spans", "start_index",
    "max_examined", "timeout_seconds", "full_usage_interval_seconds"))
PRODUCERS = (
    "ipfs_datasets_py/logic/autoformal/span_ingest_runtime.py",
    "scripts/ops/legal_ir/run_fenced_span_ingest.py", "scripts/ops/legal_ir/ingest_ipfs_uscode_corpus.py",
    "ipfs_datasets_py/logic/autoformal/__init__.py", "ipfs_datasets_py/logic/autoformal/tree_pin.py",
    "ipfs_datasets_py/logic/autoformal/span_cache.py", "ipfs_datasets_py/logic/autoformal/span_cache_claims.py",
    "ipfs_datasets_py/logic/autoformal/span_cache_fenced_ingest.py",
    "ipfs_datasets_py/logic/autoformal/span_cache_exchange.py", "ipfs_datasets_py/logic/autoformal/repair_report.py",
    "ipfs_datasets_py/logic/autoformal/supervisor_queue.py", "ipfs_datasets_py/logic/autoformal/supervisor_todo.py",
    "ipfs_datasets_py/logic/autoformal/supervisor_dispatch.py", "ipfs_datasets_py/logic/autoformal/span_evidence.py",
    "ipfs_datasets_py/logic/autoformal/paired_span_census.py", "ipfs_datasets_py/logic/autoformal/family_supervision.py",
    "ipfs_datasets_py/logic/autoformal/learned_formula_observation.py",
    "ipfs_datasets_py/logic/autoformal/semantic_integrity.py", "ipfs_datasets_py/logic/autoformal/repeal_fixture.py",
    "ipfs_datasets_py/logic/autoformal/ontology_capture.py",
    "ipfs_datasets_py/logic/autoformal/span_agreement.py", "ipfs_datasets_py/logic/autoformal/lake_probe.py",
    "ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_daemon_resources.py",
    "ipfs_datasets_py/optimizers/logic_theorem_optimizer/existing_resource_scheduler.py",
    "ipfs_datasets_py/optimizers/logic_theorem_optimizer/resource_scheduler.py",
    "ipfs_datasets_py/optimizers/logic_theorem_optimizer/proof_resource_safety.py",
    "ipfs_datasets_py/optimizers/logic_theorem_optimizer/runtime_telemetry.py",
    "ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_daemon_invocation.py",
    "ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_capacity.py",
    "ipfs_datasets_py/optimizers/logic_theorem_optimizer/modal_autoencoder.py",
    "ipfs_datasets_py/optimizers/logic_theorem_optimizer/frame_bm25_selector.py",
    "ipfs_datasets_py/optimizers/logic_theorem_optimizer/legal_modal_parser.py",
    "ipfs_datasets_py/optimizers/logic_theorem_optimizer/legal_samples.py",
    "ipfs_datasets_py/optimizers/logic_theorem_optimizer/modal_ir.py",
    "ipfs_datasets_py/optimizers/logic_theorem_optimizer/modal_registry.py",
    "ipfs_datasets_py/optimizers/logic_theorem_optimizer/spacy_modal_codec.py",
    "ipfs_datasets_py/logic/flogic_optimizer.py", "ipfs_datasets_py/logic/modal/codec.py",
    "ipfs_datasets_py/logic/modal/ir_symbol_catalog.py", "ipfs_datasets_py/logic/modal/kg_bridge.py",
    "ipfs_datasets_py/logic/deontic/converter.py", "ipfs_datasets_py/logic/deontic/ir.py",
    "ipfs_datasets_py/logic/deontic/utils/deontic_parser.py", "ipfs_datasets_py/logic/deontic/formula_builder.py",
    "ipfs_datasets_py/logic/legal_ir/canonical_compiler.py", "ipfs_datasets_py/logic/legal_ir/canonical_decompiler.py",
    "ipfs_datasets_py/logic/legal_ir/canonical_contracts.py", "ipfs_datasets_py/logic/legal_ir/canonical_roundtrip.py",
    "ipfs_datasets_py/logic/legal_ir/schemas/canonical_roundtrip_ir.schema.json",
    "ipfs_datasets_py/utils/cid_utils.py",
    "ipfs_datasets_py/logic/legal_ir/extended_compiler.py", "ipfs_datasets_py/logic/legal_ir/extended_decompiler.py",
    "ipfs_datasets_py/logic/modal/decompiler.py",
)


class SpanIngestRuntimeError(RuntimeError):
    """The bounded native resource or producer boundary refused execution."""


class SpanIngestHeadroomDeferred(SpanIngestRuntimeError):
    """No admitted compiler worker fits; this is not a conversion failure."""


def need(condition, message):
    if not condition:
        raise SpanIngestRuntimeError(message)


def _pairs(pairs):
    value = {}
    for key, item in pairs:
        need(key not in value, "duplicate runtime JSON field")
        value[key] = item
    return value


def parse_json(raw, maximum=MAX_CONTROL_BYTES):
    need(type(raw) is bytes and 0 < len(raw) <= maximum, "bounded runtime JSON required")
    def finite(value):
        result = float(value)
        need(math.isfinite(result), "nonfinite runtime JSON")
        return result
    value = json.loads(raw, object_pairs_hook=_pairs, parse_float=finite,
        parse_constant=lambda _: (_ for _ in ()).throw(SpanIngestRuntimeError("nonfinite runtime JSON")))
    need(type(value) is dict, "runtime object required")
    return value


def _integer(value, name, minimum=1, maximum=None):
    need(type(value) is int and value >= minimum and (maximum is None or value <= maximum), "invalid " + name)


def validate_spec(spec):
    need(type(spec) is dict and set(spec) == SPEC_FIELDS and spec["schema"] == SCHEMA, "closed fenced runtime spec required")
    for key in ("cache_path", "source_manifest_path", "attempt_directory", "resource_ledger_path", "scheduler_state_path"):
        need(type(spec[key]) is str and Path(spec[key]).is_absolute() and len(spec[key]) <= 4096, "explicit absolute " + key + " required")
        resources._safe_path(spec[key], directory=key == "attempt_directory")
    need(Path(spec["cache_path"]).is_file() and Path(spec["source_manifest_path"]).is_file(), "existing prepared cache and source manifest required")
    need(type(spec["release_id"]) is str and 0 < len(spec["release_id"]) <= 512, "explicit release identity required")
    need(type(spec["expected_scheduler_policy_sha256"]) is str and len(spec["expected_scheduler_policy_sha256"]) == 64
         and all(char in "0123456789abcdef" for char in spec["expected_scheduler_policy_sha256"]), "exact native policy SHA256 required")
    for key in ("storage_bytes", "memory_mb", "cpu_slots", "child_process_slots", "cache_growth_allowance_bytes", "per_worker_memory_mb"):
        _integer(spec[key], key)
    _integer(spec["max_workers"], "max_workers", maximum=32)
    _integer(spec["per_worker_process_slots"], "per_worker_process_slots", minimum=3)
    _integer(spec["batch_size"], "batch_size", maximum=32)
    _integer(spec["max_spans"], "max_spans", maximum=4096)
    _integer(spec["max_examined"], "max_examined", maximum=4096)
    _integer(spec["start_index"], "start_index", minimum=0)
    need(spec["cache_growth_allowance_bytes"] < spec["storage_bytes"], "cache allowance must leave attempt headroom")
    for key, lower, upper in (("timeout_seconds", 1, 86400), ("full_usage_interval_seconds", 1, 60)):
        value = spec[key]
        need(type(value) in (int, float) and math.isfinite(value) and lower <= value <= upper, "finite bounded " + key + " required")
    need(len(canonical_bytes(spec)) <= MAX_CONTROL_BYTES, "runtime spec exceeds control bound")
    return spec


def _pins():
    result = []
    for relative in PRODUCERS:
        path = ROOT / relative
        body = _read_regular_snapshot(path, max_bytes=4 * 1024 * 1024)
        result.append({"path": relative, "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest()})
    return result


def _reference(path, maximum):
    body = _read_regular_snapshot(path, max_bytes=maximum)
    return {"path": str(Path(path)), "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest()}


def _verify_reference(ref, maximum):
    need(type(ref) is dict and set(ref) == {"path", "bytes", "sha256"}, "closed runtime file reference required")
    need(_reference(ref["path"], maximum) == ref, "runtime input bytes changed")


def _stream_reference(path, maximum):
    """Bind an immutable full report without loading its JSON into the owner."""
    path = resources._safe_path(path)
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
    with os.fdopen(os.open(path, flags), "rb") as stream:
        before = os.fstat(stream.fileno())
        need(stat.S_ISREG(before.st_mode) and before.st_nlink == 1
             and 0 < before.st_size <= maximum, "full census report exceeds reserved storage or is aliased")
        digest, size = hashlib.sha256(), 0
        while block := stream.read(1024 * 1024):
            size += len(block)
            need(size <= maximum, "full census report grew beyond reserved storage")
            digest.update(block)
        after = os.fstat(stream.fileno())
    identity = lambda info: (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
    need(size == before.st_size and identity(before) == identity(after)
         and identity(path.lstat()) == identity(after), "full census report changed while hashing")
    return {"path": str(path), "bytes": size, "sha256": digest.hexdigest()}


def stage_child_report(report, spec, reservation_id):
    """Retain complete census bytes; keep the parent transport bounded."""
    need(type(report) is dict and report.get("resource_admission_verified_by_cli") is True
         and all(report.get(key) is False for key in FALSE), "full census report lacks non-admission bindings")
    body = canonical_bytes(report)
    need(len(body) <= spec["storage_bytes"], "full census report exceeds reserved storage")
    attempt = Path(spec["attempt_directory"])
    full_path = attempt/"census-report.json"
    _immutable_write(full_path, body)
    transport = {"schema": CHILD_REPORT_SCHEMA, "native_reservation_id": reservation_id,
        "resource_admission_verified_by_cli": True, "full_report": _stream_reference(full_path, spec["storage_bytes"]),
        "census_status": report.get("status"), "processed": report.get("processed"),
        "resumed": report.get("resumed"), "held_count": len(report.get("held", [])), **FALSE}
    raw = canonical_bytes(transport)
    need(len(raw) <= MAX_CONTROL_BYTES, "child census reference exceeds control bound")
    _immutable_write(attempt/"child-report.json", raw)
    return transport


def verify_child_report(transport, spec, reservation_id):
    """Verify custody of full bytes; never treat JSON evidence as admission."""
    fields = {"schema", "native_reservation_id", "resource_admission_verified_by_cli", "full_report",
              "census_status", "processed", "resumed", "held_count", *FALSE}
    need(type(transport) is dict and set(transport) == fields and transport["schema"] == CHILD_REPORT_SCHEMA
         and transport["native_reservation_id"] == reservation_id
         and transport["resource_admission_verified_by_cli"] is True
         and all(transport[key] is False for key in FALSE), "child report lacks exact native gate/non-admission bindings")
    for name in ("processed", "resumed", "held_count"):
        _integer(transport[name], name, minimum=0, maximum=4096)
    need(transport["census_status"] in {"completed_selected_fenced_work", "held_requires_owner_reconciliation"},
         "unsupported child census disposition")
    ref = transport["full_report"]
    expected_path = Path(spec["attempt_directory"])/"census-report.json"
    need(type(ref) is dict and set(ref) == {"path", "bytes", "sha256"}
         and ref["path"] == str(expected_path), "full census report escaped this attempt")
    need(_stream_reference(expected_path, spec["storage_bytes"]) == ref, "full census report identity differs")
    return ref


def _ledger(path):
    path = resources._safe_path(path)
    lock = path.with_name(path.name+".lock")
    resources._safe_path(lock, missing=True)
    descriptor = os.open(lock, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    try:
        info = os.fstat(descriptor)
        need(stat.S_ISREG(info.st_mode) and info.st_nlink == 1, "unaliased native disk lock required")
        deadline = time.monotonic()+5
        while True:
            try:
                resources.fcntl.flock(descriptor, resources.fcntl.LOCK_SH | resources.fcntl.LOCK_NB)
                break
            except BlockingIOError:
                need(time.monotonic() < deadline, "native disk metadata read lock unavailable")
                time.sleep(0.05)
        current = lock.lstat()
        need((current.st_dev, current.st_ino) == (info.st_dev, info.st_ino), "native disk lock identity changed")
        value = parse_json(_read_regular_snapshot(path, max_bytes=resources.MAX_LEDGER_BYTES), resources.MAX_LEDGER_BYTES)
    finally:
        os.close(descriptor)
    need(set(value) == {"schema", "roots", "limit_bytes", "reservations"}
         and value["schema"] == resources.SCHEMA and value["limit_bytes"] == resources.MAX_STORAGE_BYTES,
         "existing native disk ledger scope required")
    need(type(value["roots"]) is list and 0 < len(value["roots"]) <= 64
         and type(value["reservations"]) is dict, "native disk ledger inventory differs")
    for root in value["roots"]:
        need(resources._root_identity(resources._safe_path(root["path"], directory=True)) == root, "native storage root identity changed")
    return value


def _inside(path, roots, *, directory=False):
    path = resources._safe_path(path, directory=directory, missing=True)
    return any(path == Path(root["path"]) or Path(root["path"]) in path.parents for root in roots)


def _cache_inventory(path):
    """Stat owned mutable files only; never open or copy the active database."""
    cache = resources._safe_path(path)
    result = {}
    for file in (cache, Path(str(cache)+".wal")):
        try:
            info = file.lstat()
        except FileNotFoundError:
            if file == cache: raise
            continue
        need(stat.S_ISREG(info.st_mode) and info.st_nlink == 1, "cache/WAL must be unaliased regular files")
        result[str(file)] = info.st_size
    spill = Path(str(cache)+".tmp")
    if spill.exists() or spill.is_symlink():
        result[str(spill)] = resources._inventory([resources._safe_path(spill, directory=True)], strict=True)["apparent_bytes"]
    return result


def _growth(spec, baseline):
    need(type(baseline) is dict and set(baseline) == {"files", "identity"}, "closed cache baseline required")
    need(_cache_identity(spec["cache_path"]) == baseline["identity"], "prepared cache catalog identity changed")
    current = _cache_inventory(spec["cache_path"])
    need(_cache_identity(spec["cache_path"]) == baseline["identity"], "prepared cache catalog identity changed")
    growth = sum(max(0, size-baseline["files"].get(path, 0)) for path, size in current.items())
    need(growth <= spec["cache_growth_allowance_bytes"], "prepared cache/WAL/spill growth allowance exceeded")
    return {"observed_files": current, "growth_bytes": growth, "allowance_bytes": spec["cache_growth_allowance_bytes"]}


def _cache_identity(path):
    path = resources._safe_path(path)
    info = path.lstat()
    need(stat.S_ISREG(info.st_mode) and info.st_nlink == 1, "unaliased prepared cache required")
    return {"path": str(path), "device": info.st_dev, "inode": info.st_ino}


def _cache_baseline(path):
    identity = _cache_identity(path)
    files = _cache_inventory(path)
    need(_cache_identity(path) == identity, "prepared cache catalog identity changed during baseline")
    return {"files": files, "identity": identity}


def _combined_usage(owner, child):
    observed = resources._process(owner["pid"])
    need(observed is not None and observed["birth"] == owner["birth"], "native owner process identity changed")
    group = _group_usage(child)
    return {"group": group, "owner_rss_bytes": observed["rss_bytes"],
            "combined_rss_bytes": observed["rss_bytes"]+group["rss_bytes"],
            "scope": "owner RSS plus owned-group RSS; shared pages may be counted twice"}


def _size_plan(spec, probe=None):
    return capacity.capacity_plan(max_workers=spec["max_workers"], pending_count=min(spec["max_spans"], spec["batch_size"]),
        memory_budget_mb=spec["memory_mb"], cpu_budget=spec["cpu_slots"], process_budget=spec["child_process_slots"],
        per_worker_memory_mb=spec["per_worker_memory_mb"], reserve_mb=512, reserve_cpu_slots=1,
        per_worker_process_slots=spec["per_worker_process_slots"], reserve_process_slots=2, probe=probe)


def _ancestry():
    pid, result = os.getpid(), set()
    for _ in range(64):
        if pid <= 1 or pid in result: return result
        result.add(pid)
        observed = resources._process(pid)
        need(observed is not None, "runtime ancestor disappeared")
        pid = observed["parent_pid"]
    raise SpanIngestRuntimeError("runtime ancestry exceeds bound")


def _check_deadline(started, seconds):
    need(time.monotonic()-started <= seconds, "fenced runtime deadline exceeded")


def _feed_launch(process, raw, verify_live):
    """Feed the barrier without blocking outside the owner's live deadline."""
    descriptor = process.stdin.fileno()
    os.set_blocking(descriptor, False)
    offset = 0
    while offset < len(raw):
        verify_live()
        need(process.poll() is None, "runtime child exited before receiving its launch")
        try:
            count = os.write(descriptor, raw[offset:])
            need(count > 0, "native launch pipe made no progress")
            offset += count
        except BlockingIOError:
            time.sleep(0.05)
    process.stdin.close()
    verify_live()


@contextmanager
def cancellation_handler():
    previous = signal.getsignal(signal.SIGTERM)
    def interrupted(signum, frame):
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        raise SpanIngestRuntimeError("owned fenced ingestion cancelled by SIGTERM")
    signal.signal(signal.SIGTERM, interrupted)
    try: yield
    finally: signal.signal(signal.SIGTERM, previous)


class FencedIngestChildVerifier:
    """Observe the live native owner envelope; never acquire/renew a lease."""
    def __init__(self, launch):
        fields = {"schema", "spec", "spec_sha256", "owner", "child", "lease_id", "reservation_id", "roots",
                  "workers", "capacity_plan", "cache_baseline", "source_manifest", "producer_pins"}
        need(type(launch) is dict and set(launch) == fields and launch["schema"] == LAUNCH_SCHEMA, "closed native launch envelope required")
        spec = validate_spec(launch["spec"])
        need(launch["spec_sha256"] == hashlib.sha256(canonical_bytes(spec)).hexdigest(), "launch spec digest differs")
        _integer(launch["workers"], "admitted worker count", maximum=spec["max_workers"])
        need(launch["capacity_plan"]["workers"] == launch["workers"]
             and 2 + spec["per_worker_process_slots"]*launch["workers"] <= spec["child_process_slots"]
             and 1 + launch["workers"] <= spec["cpu_slots"]
             and 512 + spec["per_worker_memory_mb"]*launch["workers"] <= spec["memory_mb"], "launch exceeds native envelope")
        self.launch, self.spec = launch, spec
        self.scheduler = open_existing_scheduler(spec["scheduler_state_path"], spec["expected_scheduler_policy_sha256"])
        self.verify()

    def verify(self):
        launch, spec = self.launch, self.spec
        need(ROOT.resolve() == CANONICAL_ROOT.resolve(), "fenced inference requires canonical workspace deployment")
        observed = resources._process(os.getpid())
        need(observed is not None and launch["child"] == {key: observed[key] for key in ("pid", "birth")}
             and observed["group_pid"] == observed["pid"] and observed["parent_pid"] == launch["owner"]["pid"], "runtime child process identity differs")
        owner = resources._process(launch["owner"]["pid"])
        need(owner is not None and owner["birth"] == launch["owner"]["birth"]
             and owner["pid"] in _ancestry(), "native controller owner identity differs")
        leases = [row for row in self.scheduler.active_leases() if row["lease_id"] == launch["lease_id"]]
        need(len(leases) == 1 and not self.scheduler.is_cancelled(launch["lease_id"], missing_is_cancelled=True), "native runtime lease is no longer live")
        lease = leases[0]
        need(lease["owner_pid"] == owner["pid"] and lease["lane"] == resources.SCHEDULER_LANE.value
             and lease["request_id"] == "daemon:"+launch["reservation_id"]
             and all(lease[key] == spec[key] for key in ("cpu_slots", "memory_mb", "child_process_slots")), "native runtime lease scope differs")
        ledger = _ledger(spec["resource_ledger_path"])
        row = ledger["reservations"].get(launch["reservation_id"])
        need(ledger["roots"] == launch["roots"] and type(row) is dict and row.get("status") == "active"
             and row.get("owner_pid") == owner["pid"] and row.get("child") == launch["child"]
             and row.get("attempt_directory") == resources._root_identity(Path(spec["attempt_directory"]))
             and row.get("external_charges", {}).get("prepared-cache-growth") == spec["cache_growth_allowance_bytes"]
             and all(row.get(key) == spec[key] for key in ("cpu_slots", "memory_mb", "child_process_slots", "storage_bytes")), "native disk reservation scope differs")
        need(row.get("fenced_launch_sha256") == hashlib.sha256(canonical_bytes(launch)).hexdigest(),
             "native owner did not bind this exact launch envelope")
        need(_pins() == launch["producer_pins"], "fenced runtime producer source changed")
        _verify_reference(launch["source_manifest"], 16*1024*1024)
        for variable in ("TMPDIR", "TMP", "TEMP"):
            need(os.environ.get(variable) == str(Path(spec["attempt_directory"])/"tmp"), "native temporary directory binding differs")
        bytecode = str(Path(spec["attempt_directory"])/"bytecode")
        need(os.environ.get("PYTHONPYCACHEPREFIX") == bytecode and sys.pycache_prefix == bytecode
             and sys.dont_write_bytecode, "native fresh bytecode directory binding differs")
        need(os.environ.get("LEAN_NUM_THREADS") == "1", "Lean thread environment differs")
        usage = _combined_usage(launch["owner"], launch["child"])
        need(usage["combined_rss_bytes"] <= spec["memory_mb"]*1024*1024, "native owner/group RSS limit exceeded")
        need(usage["group"]["live_processes"] <= spec["child_process_slots"], "native child process-slot limit exceeded")
        _growth(spec, launch["cache_baseline"])
        return True

    def configure_cache(self, cache):
        self.verify()
        path = str(Path(self.spec["attempt_directory"])/"spill").replace("'", "''")
        cache._db.execute("SET temp_directory='"+path+"'")
        cache._db.execute("SET threads=1")


def child_main(launch):
    """Run only the resource-verified existing fenced CLI path."""
    from scripts.ops.legal_ir import ingest_ipfs_uscode_corpus as ingestion
    verifier = FencedIngestChildVerifier(launch)
    spec = verifier.spec
    argv = ["--claim-profile", "fenced-v1", "--cache", spec["cache_path"], "--source-manifest", spec["source_manifest_path"],
        "--release-id", spec["release_id"], "--upload-dir", str(Path(spec["attempt_directory"])),
        "--compile-workers", str(launch["workers"]), "--batch", str(spec["batch_size"]),
        "--fenced-span-limit", str(spec["max_spans"]), "--fenced-start-index", str(spec["start_index"]),
        "--fenced-scan-limit", str(spec["max_examined"])]
    with cancellation_handler():
        return ingestion.main(argv, fenced_runtime=verifier)


def run_fenced_ingest_runtime(spec):
    """Own one bounded native run; failure leaves the original disk claim retained."""
    # Snapshot caller parameters before any grants; no concurrent mutation of
    # the original Python dictionary can change the admitted launch envelope.
    spec = parse_json(canonical_bytes(spec))
    validate_spec(spec)
    need(ROOT.resolve() == CANONICAL_ROOT.resolve(), "fenced inference requires canonical workspace deployment")
    ledger = _ledger(spec["resource_ledger_path"])
    roots = ledger["roots"]
    attempt = Path(spec["attempt_directory"])
    need(not any(attempt.iterdir()), "fresh exclusive runtime attempt directory required")
    need(all(_inside(spec[key], roots, directory=key == "attempt_directory")
             for key in ("attempt_directory", "cache_path")), "runtime cache/attempt escapes native storage roots")
    need(not (attempt == Path(spec["cache_path"]).parent or attempt in Path(spec["cache_path"]).parents), "prepared cache must use its explicit external growth allowance")
    baseline = _cache_baseline(spec["cache_path"])
    pins = _pins()
    manifest = _reference(spec["source_manifest_path"], 16*1024*1024)
    reservation = resources.DaemonResourceReservation(spec["resource_ledger_path"], roots=[row["path"] for row in roots],
        storage_bytes=spec["storage_bytes"], memory_mb=spec["memory_mb"], cpu_slots=spec["cpu_slots"],
        child_process_slots=spec["child_process_slots"], timeout_seconds=0, ledger_lock_timeout_seconds=5,
        scheduler_state_path=spec["scheduler_state_path"], expected_scheduler_policy_sha256=spec["expected_scheduler_policy_sha256"],
        require_existing_ledger=True)
    process, identity, primary = None, None, None
    started, observations = time.monotonic(), []
    result = {"schema": "span-fenced-runtime-report/v1", "status": "started", "spec": spec,
        "producer_pins_before": pins, "source_manifest": manifest, "execution_finished": False,
        "resource_admission_verified": False, "kernel_quota_enforced": False,
        "process_ceiling_verified": False, "lake_admission_conferred": False, **FALSE}
    result["producer_pin_scope"] = "declared runtime/codec/compiler/Lake/census/goal source closure; not complete package, binary, or preloaded-bytecode authentication"
    with cancellation_handler(), reservation:
        try:
            plan = _size_plan(spec)
            result["capacity_plan"] = plan
            if plan["workers"] == 0:
                raise SpanIngestHeadroomDeferred("hardware/native envelope cannot fit a fenced compiler worker")
            for name in ("tmp", "spill", "exchange", "bytecode"):
                (attempt/name).mkdir(mode=0o700)
            _immutable_write(attempt/"source-manifest.json",
                             _read_regular_snapshot(spec["source_manifest_path"], max_bytes=16*1024*1024))
            reservation.check_usage(attempt)
            reservation.account_external_bytes("prepared-cache-growth", spec["cache_growth_allowance_bytes"])
            environment = dict(os.environ, TMPDIR=str(attempt/"tmp"), TMP=str(attempt/"tmp"), TEMP=str(attempt/"tmp"),
                LEAN_NUM_THREADS="1", PYTHONDONTWRITEBYTECODE="1",
                PYTHONPYCACHEPREFIX=str(attempt/"bytecode"))
            with (attempt/"worker.log").open("xb") as log:
                process = subprocess.Popen([sys.executable, "-B", str(ROOT/"scripts/ops/legal_ir/run_fenced_span_ingest.py"), "--child"],
                    cwd=ROOT, env=environment, stdin=subprocess.PIPE, stdout=log, stderr=subprocess.STDOUT,
                    start_new_session=True)
                observed = resources._process(process.pid)
                need(observed is not None, "isolated runtime child exited before barrier")
                identity = {key: observed[key] for key in ("pid", "birth")}
                reservation.check_usage(attempt, child_pid=process.pid)
                owner = resources._process(os.getpid())
                launch = {"schema": LAUNCH_SCHEMA, "spec": spec, "spec_sha256": hashlib.sha256(canonical_bytes(spec)).hexdigest(),
                    "owner": {key: owner[key] for key in ("pid", "birth")}, "child": identity,
                    "lease_id": reservation.to_dict()["resource_lease"]["lease_id"], "reservation_id": reservation.reservation_id,
                    "roots": roots, "workers": plan["workers"], "capacity_plan": plan, "cache_baseline": baseline,
                    "source_manifest": manifest, "producer_pins": pins}
                raw = canonical_bytes(launch)
                need(len(raw)+1 <= MAX_CONTROL_BYTES, "native launch envelope exceeds control bound including delimiter")
                reservation._update(fenced_launch_sha256=hashlib.sha256(raw).hexdigest())
                _immutable_write(attempt/"launch.json", raw)
                next_full = time.monotonic()+spec["full_usage_interval_seconds"]
                def monitor():
                    nonlocal next_full
                    _check_deadline(started, spec["timeout_seconds"])
                    need(reservation.heartbeat() and not reservation.cancelled, "native runtime lease cancelled or lost")
                    combined = _combined_usage(launch["owner"], identity)
                    group = combined["group"]
                    result["last_memory_observation"] = combined
                    need(group["live_processes"] <= spec["child_process_slots"], "native child process-slot limit exceeded")
                    need(combined["combined_rss_bytes"] <= spec["memory_mb"]*1024*1024, "native owner/group RSS limit exceeded")
                    usage = _growth(spec, baseline)
                    size = resources._inventory([attempt], strict=True)["apparent_bytes"]
                    need(size+spec["cache_growth_allowance_bytes"] <= spec["storage_bytes"], "native attempt storage limit exceeded")
                    need(_pins() == pins, "fenced runtime producer source changed")
                    if len(observations) < 256:
                        observations.append({"elapsed_seconds": time.monotonic()-started, "memory": combined,
                            "attempt_bytes": size, "cache_growth": usage})
                    if time.monotonic() >= next_full:
                        reservation.check_usage(attempt)
                        next_full = time.monotonic()+spec["full_usage_interval_seconds"]
                    _check_deadline(started, spec["timeout_seconds"])
                _feed_launch(process, raw+b"\n", monitor)
                result["resource_admission_verified"] = True
                while process.poll() is None:
                    monitor()
                    time.sleep(0.25)
                _check_deadline(started, spec["timeout_seconds"])
                _terminate(process, identity)
                result["owned_group_stopped"] = not _group_usage(identity)["live_processes"]
                need(result["owned_group_stopped"], "fenced coordinator left live descendants")
                need(process.returncode == 0, "fenced coordinator failed or held unresolved rows")
                need(reservation.heartbeat() and not reservation.cancelled, "native runtime lease lost at completion")
                final_memory = _combined_usage(launch["owner"], identity)
                result["last_memory_observation"] = final_memory
                need(final_memory["combined_rss_bytes"] <= spec["memory_mb"]*1024*1024, "native owner/group RSS limit exceeded")
                report_path = attempt/"child-report.json"
                child_report = parse_json(_read_regular_snapshot(report_path, max_bytes=MAX_REPORT_BYTES), MAX_REPORT_BYTES)
                full_report = verify_child_report(child_report, spec, reservation.reservation_id)
                need(_pins() == pins, "fenced runtime producer source changed")
                _verify_reference(manifest, 16*1024*1024)
                reservation.check_usage(attempt)
                _check_deadline(started, spec["timeout_seconds"])
                result.update(status="completed_bounded_fenced_ingestion", execution_finished=True,
                    child_report=_reference(report_path, MAX_REPORT_BYTES), full_census_report=full_report, producer_pins_after=_pins(),
                    cache_growth=_growth(spec, baseline))
                log.flush()
                os.fsync(log.fileno())
            result.update(elapsed_seconds=time.monotonic()-started, observations=observations,
                          reservation=reservation.to_dict(),
                          reservation_status_scope="snapshot before strict native finalization; native ledger records release")
            _immutable_write(attempt/"runtime-report.json", canonical_bytes(result))
            reservation.finalize(attempt, artifacts_durable=True)
            return {**result, "reservation": reservation.to_dict()}
        except BaseException as error:
            primary = error
            result.update(status="deferred_fenced_runtime_headroom" if isinstance(error, SpanIngestHeadroomDeferred)
                          else "failed_bounded_fenced_ingestion", error_type=type(error).__name__,
                elapsed_seconds=time.monotonic()-started, observations=observations)
            raise
        finally:
            try:
                if process is not None: _terminate(process, identity)
                result["owned_group_stopped"] = identity is None or not _group_usage(identity)["live_processes"]
                if primary is not None:
                    result["reservation"] = reservation.to_dict()
                    _immutable_write(attempt/"runtime-failure.json", canonical_bytes(result))
            except BaseException as cleanup:
                if primary is None: raise
                primary.add_note("Native runtime cleanup failed: "+type(cleanup).__name__)


__all__ = ["run_fenced_ingest_runtime", "FencedIngestChildVerifier", "child_main", "validate_spec", "parse_json"]
