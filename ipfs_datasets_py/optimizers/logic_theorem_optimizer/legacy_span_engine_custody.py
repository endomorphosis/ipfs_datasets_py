"""Join a legacy engine to its actual external native owner before execution.

Launch hashes bind observations to an existing native lease and disk row; they
are not credentials or Lean admission. No global facade, lease, ledger or model is
created here. Only the owner can write its existing reservation's launch hash.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import select
import stat
import sys
import time
import uuid

from . import autoencoder_daemon_resources as host
from . import existing_resource_scheduler as existing
from .existing_resource_scheduler import open_existing_scheduler

SCHEMA = "legacy-span-engine-launch/v2"
MAX_LAUNCH_BYTES = 65_536
SPEC_FIELDS = frozenset(("runtime_directory", "resource_ledger_path", "scheduler_state_path",
    "expected_scheduler_policy_sha256", "invocation_sha256", "storage_bytes", "memory_mb",
    "cpu_slots", "child_process_slots"))
LAUNCH_FIELDS = frozenset(("schema", "spec", "spec_sha256", "owner", "child", "lease_id",
    "reservation_id", "roots", "bytecode", "producer_sources"))


class LegacySpanEngineCustodyError(host.DaemonResourceError):
    """The engine is not joined to its currently live external native owner."""


def _need(condition, message):
    if not condition:
        raise LegacySpanEngineCustodyError(message)


def _bytes(value):
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    except (ValueError, TypeError) as error:
        raise LegacySpanEngineCustodyError("closed finite engine launch required") from error


def _sha(value):
    return hashlib.sha256(_bytes(value)).hexdigest()


def _digest(value):
    return type(value) is str and len(value) == 64 and all(char in "0123456789abcdef" for char in value)


def invocation_sha256(args):
    """Bind all parsed CLI options except the parent's hidden engine switch."""
    return _sha({key: str(value) if isinstance(value, Path) else value
        for key, value in vars(args).items() if key != "_engine"})


def engine_resource_spec(args):
    return dict(runtime_directory=str(args.runtime_directory), resource_ledger_path=str(args.resource_ledger),
        scheduler_state_path=str(args.scheduler_state), expected_scheduler_policy_sha256=args.expected_policy_sha256,
        invocation_sha256=invocation_sha256(args), storage_bytes=args.storage_bytes,
        memory_mb=min(args.memory_mb, 2048) if args.publish_only else args.memory_mb,
        cpu_slots=1 if args.publish_only else args.compiler_workers + args.bridge_workers + 1,
        child_process_slots=1 if args.publish_only else args.compiler_workers + 4)


def _spec(spec):
    _need(type(spec) is dict and set(spec) == SPEC_FIELDS, "closed engine resource spec required")
    for field in ("runtime_directory", "resource_ledger_path", "scheduler_state_path"):
        _need(type(spec[field]) is str and spec[field] and Path(spec[field]).is_absolute(),
              "absolute native engine paths required")
    for field in ("expected_scheduler_policy_sha256", "invocation_sha256"):
        _need(_digest(spec[field]), "exact native engine SHA256 required")
    for field in ("storage_bytes", "memory_mb", "cpu_slots", "child_process_slots"):
        _need(type(spec[field]) is int and spec[field] > 0, "positive native engine resource envelope required")
    _need(spec["storage_bytes"] <= host.MAX_STORAGE_BYTES, "engine storage exceeds preserved cap")
    return spec



PRODUCER_FILES = (
    "ipfs_datasets_py/__init__.py", "ipfs_datasets_py/logic/__init__.py",
    "ipfs_datasets_py/optimizers/__init__.py",
    "ipfs_datasets_py/optimizers/logic_theorem_optimizer/__init__.py",
    "ipfs_datasets_py/optimizers/logic_theorem_optimizer/legacy_span_engine_custody.py",
    "ipfs_datasets_py/optimizers/logic_theorem_optimizer/legacy_span_campaign_resources.py",
    "ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_daemon_resources.py",
    "ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_daemon_invocation.py",
    "ipfs_datasets_py/optimizers/logic_theorem_optimizer/existing_resource_scheduler.py",
    "ipfs_datasets_py/optimizers/logic_theorem_optimizer/resource_scheduler.py",
    "ipfs_datasets_py/optimizers/logic_theorem_optimizer/proof_resource_safety.py",
    "ipfs_datasets_py/optimizers/logic_theorem_optimizer/runtime_telemetry.py",
    "ipfs_datasets_py/logic/autoformal/__init__.py",
    "ipfs_datasets_py/logic/autoformal/span_ingest_runtime.py",
    "ipfs_datasets_py/logic/autoformal/tree_pin.py", "scripts/ops/legal_ir/run_legacy_span_cuda.py")


def _producer_sources():
    """Current declared source bytes/origins, not binary or loaded-code attestation."""
    root = Path(__file__).resolve().parents[3]
    modules = ((host, "autoencoder_daemon_resources.py"),
        (existing, "existing_resource_scheduler.py"), (existing.native, "resource_scheduler.py"))
    for module, filename in modules:
        expected = root / "ipfs_datasets_py/optimizers/logic_theorem_optimizer" / filename
        _need(Path(module.__file__).resolve() == expected.resolve() and not Path(module.__file__).is_symlink(),
              "engine resource producer escaped its source tree")
    result = {}
    for relative in PRODUCER_FILES:
        path = host._safe_path(root / relative)
        info = path.lstat()
        _need(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and 0 < info.st_size <= 4 * 1024**2,
              "unaliased bounded engine source required")
        raw = path.read_bytes()
        after = path.lstat()
        _need((info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns) ==
              (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns),
              "engine source changed while capturing")
        result[str(path)] = hashlib.sha256(raw).hexdigest()
    return result


def _bytecode_identity(path, runtime_directory):
    runtime = host._safe_path(runtime_directory, directory=True)
    directory = host._safe_path(path, directory=True)
    _need(directory.parent == runtime / ".engine-bytecode" and len(directory.name) == 32
          and all(char in "0123456789abcdef" for char in directory.name), "bytecode escaped owned startup directory")
    info = directory.lstat()
    _need(info.st_uid == os.geteuid() and stat.S_IMODE(info.st_mode) == 0o700,
          "private native engine bytecode directory required")
    with os.scandir(directory) as entries:
        _need(next(entries, None) is None, "engine bytecode directory is not empty")
    return host._root_identity(directory)


def prepare_engine_bytecode(reservation, runtime_directory):
    """Create a fresh prefix solely inside the already admitted owner runtime."""
    reservation._verify_owner_roots()
    _need(reservation.heartbeat() and not reservation.cancelled, "native engine owner reservation lost")
    runtime = host._safe_path(runtime_directory, directory=True)
    _need(reservation._record.get("attempt_directory") == host._root_identity(runtime),
          "bytecode startup requires attached native runtime")
    parent = host._safe_path(runtime / ".engine-bytecode", directory=True, missing=True)
    parent.mkdir(mode=0o700, exist_ok=True)
    host._safe_path(parent, directory=True)
    directory = parent / uuid.uuid4().hex
    directory.mkdir(mode=0o700)
    _bytecode_identity(directory, runtime)
    reservation._verify_owner_roots()
    return directory



def owned_child_identity(process):
    observed = host._process(process.pid)
    _need(observed is not None and observed["parent_pid"] == os.getpid()
          and observed["group_pid"] == process.pid, "actual isolated direct engine child required")
    return {key: observed[key] for key in ("pid", "birth")}

def verify_startup_deadline(started):
    _need(type(started) in (int, float) and math.isfinite(started)
          and 0 <= time.monotonic() - started <= 60, "owned engine startup barrier exceeded 60 seconds")



def engine_ready_path(launch):
    directory = Path(launch["bytecode"]["path"])
    return directory.with_name(directory.name + ".ready.json")

def wait_engine_ready(process, launch, verify_live):
    """Accept only this child handoff under the caller's unchanged startup deadline."""
    path = engine_ready_path(launch)
    expected = dict(schema="legacy-span-engine-ready/v1", launch_sha256=_sha(launch),
        child=dict(launch["child"]), model_executed=False, training_started=False,
        admitted=False, qualified=False)
    while True:
        verify_live()
        try:
            observed = host._safe_path(path, missing=True)
            descriptor = os.open(observed, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(descriptor, "rb") as stream:
                before = os.fstat(stream.fileno())
                _need(stat.S_ISREG(before.st_mode) and before.st_nlink == 1
                      and 0 < before.st_size <= MAX_LAUNCH_BYTES, "bounded unaliased engine ready receipt required")
                raw = stream.read(MAX_LAUNCH_BYTES + 1)
                after = os.fstat(stream.fileno())
            current = path.lstat()
            identity = lambda info:(info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
            _need(len(raw) == before.st_size and identity(before) == identity(after) == identity(current),
                  "engine ready receipt changed while reading")
            receipt = json.loads(raw, object_pairs_hook=host._json_pairs,
                parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite ready receipt")))
            if receipt == expected:
                verify_live()
                return receipt
            # A prior retained receipt may still exist during this startup.
            # It conveys no success for the new child and is never rewritten here.
        except FileNotFoundError:
            pass
        _need(process.poll() is None, "engine exited without its current owner handoff")
        time.sleep(0.05)

def bind_engine_launch(reservation, runtime_directory, invocation_digest, *, bytecode_directory):
    """Called solely by the actual entered disk/lease owner after child attach."""
    reservation._verify_owner_roots()
    _need(reservation.heartbeat() and not reservation.cancelled, "native engine owner reservation lost")
    _need(reservation._child is not None and _digest(invocation_digest), "attached engine and invocation required")
    owner = host._process(os.getpid())
    _need(owner is not None, "native engine owner birth unavailable")
    spec = _spec(dict(runtime_directory=str(runtime_directory), resource_ledger_path=str(reservation.ledger_path),
        scheduler_state_path=str(reservation._scheduler_state_path),
        expected_scheduler_policy_sha256=reservation._expected_scheduler_policy_sha256,
        invocation_sha256=invocation_digest, storage_bytes=reservation.storage_bytes,
        memory_mb=reservation.memory_mb, cpu_slots=reservation.cpu_slots,
        child_process_slots=reservation.child_process_slots))
    launch = dict(schema=SCHEMA, spec=spec, spec_sha256=_sha(spec),
        owner={key: owner[key] for key in ("pid", "birth")}, child=dict(reservation._child),
        lease_id=reservation.to_dict()["resource_lease"]["lease_id"],
        reservation_id=reservation.reservation_id, roots=reservation.root_identities,
        bytecode=_bytecode_identity(bytecode_directory, runtime_directory), producer_sources=_producer_sources())
    _need(len(_bytes(launch)) + 1 <= MAX_LAUNCH_BYTES, "engine launch exceeds control bound")
    reservation._update(legacy_engine_launch_sha256=_sha(launch))
    return launch


def read_engine_launch(stream):
    """Bound startup only; no deadline is placed on productive inference."""
    descriptor = stream.fileno()
    was_blocking = os.get_blocking(descriptor)
    deadline = time.monotonic() + 60
    raw = bytearray()
    os.set_blocking(descriptor, False)
    try:
        while True:
            remaining = deadline - time.monotonic()
            _need(remaining > 0, "native engine startup barrier timed out")
            ready, _, _ = select.select([descriptor], [], [], min(remaining, 0.25))
            if not ready:
                continue
            try:
                part = os.read(descriptor, min(4096, MAX_LAUNCH_BYTES + 1 - len(raw)))
            except BlockingIOError:
                continue
            if not part:
                break
            raw.extend(part)
            _need(len(raw) <= MAX_LAUNCH_BYTES, "engine launch exceeds control bound")
    finally:
        os.set_blocking(descriptor, was_blocking)
    _need(bool(raw) and raw.endswith(b"\n") and raw.count(b"\n") == 1,
          "bounded owner launch required before engine execution")
    try:
        return json.loads(raw, object_pairs_hook=host._json_pairs,
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite engine launch")))
    except (ValueError, UnicodeError) as error:
        raise LegacySpanEngineCustodyError("invalid native engine launch JSON") from error


class LegacySpanEngineVerifier:
    """Read actual native owner state; never acquire, renew or inject authority."""
    def __init__(self, launch, expected_spec):
        _need(type(launch) is dict and set(launch) == LAUNCH_FIELDS and launch["schema"] == SCHEMA,
              "closed native engine launch required")
        spec = _spec(expected_spec)
        _need(launch["spec"] == spec and launch["spec_sha256"] == _sha(spec), "engine invocation or resource scope differs")
        for field in ("owner", "child"):
            item = launch[field]
            _need(type(item) is dict and set(item) == {"pid", "birth"}
                  and type(item["pid"]) is int and item["pid"] > 0
                  and type(item["birth"]) is str and item["birth"], "native process birth required")
        _need(all(type(launch[field]) is str and launch[field] for field in ("lease_id", "reservation_id")),
              "native owner identities required")
        self.launch, self.spec = launch, spec
        self.scheduler = open_existing_scheduler(spec["scheduler_state_path"], spec["expected_scheduler_policy_sha256"])
        _need(launch["producer_sources"] == _producer_sources(), "engine source generation differs")
        self.verify()

    def verify(self):
        launch, spec = self.launch, self.spec
        _need(launch["producer_sources"] == _producer_sources(), "engine source generation changed")
        bytecode = _bytecode_identity(launch["bytecode"]["path"], spec["runtime_directory"])
        _need(bytecode == launch["bytecode"] and os.environ.get("PYTHONPYCACHEPREFIX") == bytecode["path"]
              and sys.pycache_prefix == bytecode["path"] and sys.dont_write_bytecode,
              "fresh engine bytecode environment differs")
        child = host._process(os.getpid())
        owner = host._process(launch["owner"]["pid"])
        _need(child is not None and {key: child[key] for key in ("pid", "birth")} == launch["child"]
              and child["group_pid"] == child["pid"] and child["parent_pid"] == launch["owner"]["pid"],
              "engine is not the actual isolated direct child")
        _need(owner is not None and owner["birth"] == launch["owner"]["birth"] and owner["state"] != "Z",
              "native engine owner birth or liveness differs")
        leases = [item for item in self.scheduler.active_leases() if item["lease_id"] == launch["lease_id"]]
        _need(len(leases) == 1 and not self.scheduler.is_cancelled(launch["lease_id"], missing_is_cancelled=True),
              "native engine owner lease is absent or cancelled")
        lease = leases[0]
        expires = lease.get("expires_at")
        _need(type(expires) in (int, float) and math.isfinite(expires) and expires > time.time(),
              "native engine owner lease expired")
        _need(lease["owner_pid"] == owner["pid"] and lease.get("owner_birth_marker") == owner["birth"]
              and lease["lane"] == host.SCHEDULER_LANE.value and not lease.get("parent_lease_id")
              and lease["request_id"] == "daemon:" + launch["reservation_id"]
              and all(lease[key] == spec[key] for key in ("cpu_slots", "memory_mb", "child_process_slots")),
              "native engine owner lease scope differs")
        # Reuse the fenced runtime's bounded, shared-lock native metadata read.
        # This never opens the span cache or copies an active catalog.
        from ipfs_datasets_py.logic.autoformal.span_ingest_runtime import _ledger
        ledger = _ledger(spec["resource_ledger_path"])
        row = ledger["reservations"].get(launch["reservation_id"])
        _need(ledger["roots"] == launch["roots"] and type(row) is dict and row.get("status") == "active"
              and row.get("owner_pid") == owner["pid"] and row.get("child") == launch["child"]
              and row.get("attempt_directory") == host._root_identity(Path(spec["runtime_directory"]))
              and all(row.get(key) == spec[key] for key in ("storage_bytes", "memory_mb", "cpu_slots", "child_process_slots"))
              and row.get("legacy_engine_launch_sha256") == _sha(launch), "native engine disk reservation scope differs")
        group = host._group_usage(launch["child"])
        _need(group["live_processes"] <= spec["child_process_slots"]
              and group["rss_bytes"] + owner["rss_bytes"] <= spec["memory_mb"] * 1024**2,
              "native engine owner/group exceeds its envelope")
        return True

    def ready_path(self):
        self.verify()
        return engine_ready_path(self.launch)

    def ready_receipt(self):
        self.verify()
        return dict(schema="legacy-span-engine-ready/v1", launch_sha256=_sha(self.launch),
            child=dict(self.launch["child"]), model_executed=False, training_started=False,
            admitted=False, qualified=False)


__all__ = ["LegacySpanEngineCustodyError", "LegacySpanEngineVerifier", "bind_engine_launch",
           "engine_resource_spec", "invocation_sha256", "read_engine_launch",
           "prepare_engine_bytecode", "owned_child_identity", "verify_startup_deadline", "wait_engine_ready",
           "engine_ready_path"]
