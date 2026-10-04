"""Stdlib preflight for trusted CPU inference workers with explicit lineage pins.

Representation declarations and supplied vectors are not encoder authentication.
Process limits are local limits, not aggregate admission or network isolation.
Apply budgets before importing model libraries. The coordinator creates private
state/output directories; this helper does not establish an OS sandbox.
"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import math
import os
from pathlib import Path
import re
import secrets
import stat
import sys


CONFIG_SCHEMA = "gte-parallel-model-worker/v1"
MAX_JSON_BYTES = 128 * 1024 * 1024
MAX_CONFIG_BYTES = 1024 * 1024
DOMAINS = ("legal_ir", "intent_ir", "security_ir", "ui_ux_ir")
LANE_DIMENSIONS = {"legacy_8d": 8, "source_384d": 384, "multilingual_768d": 768}
LEGACY_RUNTIMES = {"legal_ir:legacy_v1", "legal_ir:legacy_linguistic_historical_blank_en"}
CONFIG_FIELDS = {"schema", "lane_id", "dimension", "runtime_id", "representation_id",
                 "checkpoint", "dataset", "domain_id", "resources", "mode"}
RESOURCE_FIELDS = {"device", "threads", "max_rows", "memory_limit_mib", "cpu_time_limit_seconds"}
_HASH = re.compile(r"[0-9a-fA-F]{64}\Z")


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _fields(value, required, label):
    _require(type(value) is dict and set(value) == required, "closed " + label + " fields required")


def _text(value, label):
    _require(type(value) is str and bool(value.strip()) and "\0" not in value,
             "nonempty " + label + " string required")
    return value


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _hash(value):
    _require(type(value) is str and _HASH.fullmatch(value) is not None, "full SHA256 required")
    return value


def _identity(info):
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def _read_stable(path, *, expected_sha256=None, max_bytes=MAX_JSON_BYTES):
    _require(type(max_bytes) is int and max_bytes > 0, "positive max_bytes required")
    if expected_sha256 is not None:
        _hash(expected_sha256)
    path = Path(path).resolve()
    before = path.stat()
    _require(stat.S_ISREG(before.st_mode), "regular file required")
    _require(before.st_size <= max_bytes, "file exceeds byte limit")
    flags = os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    with os.fdopen(descriptor, "rb") as stream:
        opened = os.fstat(stream.fileno())
        _require(stat.S_ISREG(opened.st_mode) and _identity(opened) == _identity(before),
                 "file changed before reading")
        raw = stream.read(max_bytes + 1)
        after = os.fstat(stream.fileno())
    _require(len(raw) <= max_bytes and len(raw) == before.st_size,
             "file exceeded bound or changed while reading")
    _require(_identity(before) == _identity(after) == _identity(path.stat()), "file changed while reading")
    digest = _sha(raw)
    if expected_sha256 is not None:
        _require(digest == expected_sha256.lower(), "file SHA256 mismatch")
    return raw, {"path": str(path), "bytes": len(raw), "sha256": digest}, before


def _parse(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            _require(key not in result, "duplicate JSON key: " + key)
            result[key] = value
        return result

    def invalid(value):
        raise ValueError("nonfinite JSON number: " + value)

    def finite(value):
        number = float(value)
        _require(math.isfinite(number), "nonfinite JSON number")
        return number

    try:
        return json.loads(raw, object_pairs_hook=unique, parse_constant=invalid, parse_float=finite)
    except (UnicodeError, RecursionError) as error:
        raise ValueError("invalid JSON encoding or nesting") from error


def read_pinned_json(path, *, expected_sha256=None, max_bytes=MAX_JSON_BYTES):
    """Read strict JSON from stable regular-file bytes, optionally verifying a pin."""
    raw, receipt, _ = _read_stable(path, expected_sha256=expected_sha256, max_bytes=max_bytes)
    return _parse(raw), receipt


def _resources(resources):
    _fields(resources, RESOURCE_FIELDS, "resource")
    _require(resources["device"] == "cpu", "CPU-only device required")
    ranges = {"threads": (1, 64), "max_rows": (1, 1000000),
              "memory_limit_mib": (256, 262144), "cpu_time_limit_seconds": (1, 86400)}
    for name, (minimum, maximum) in ranges.items():
        value = resources[name]
        _require(type(value) is int and minimum <= value <= maximum, "bounded integer " + name + " required")
    return dict(resources)


def _config(config, directory):
    _fields(config, CONFIG_FIELDS, "worker configuration")
    _require(config["schema"] == CONFIG_SCHEMA, "unsupported worker schema")
    lane, domain = config["lane_id"], config["domain_id"]
    _require(type(lane) is str and lane in LANE_DIMENSIONS, "supported lane_id required")
    _require(type(config["dimension"]) is int and config["dimension"] == LANE_DIMENSIONS[lane],
             "dimension differs from lane identity")
    _require(type(domain) is str and domain in DOMAINS, "supported domain_id required")
    runtime = _text(config["runtime_id"], "runtime_id")
    _text(config["representation_id"], "representation_id")
    _require(config["mode"] == "infer", "infer-only worker mode required")
    if lane == "legacy_8d":
        _require(domain == "legal_ir" and runtime in LEGACY_RUNTIMES,
                 "legacy_8d requires an explicit supported Legal runtime")
    elif lane == "source_384d":
        _require(runtime == domain + ":source_training_v2", "source_384d runtime differs from domain")
    else:
        raise ValueError("multilingual_768d model worker is unavailable; no backend substitution")
    normalized = dict(config)
    normalized["resources"] = _resources(config["resources"])
    for name in ("checkpoint", "dataset"):
        ref = config[name]
        _fields(ref, {"path", "sha256"}, name + " reference")
        path = _text(ref["path"], name + " path")
        _hash(ref["sha256"])
        normalized[name] = {"path": str((directory / path).resolve()), "sha256": ref["sha256"]}
    return normalized


def _environment(config, environment):
    fields = {"GTE_PATH_LANE": "lane_id", "GTE_PATH_DIMENSION": "dimension",
              "GTE_PATH_RUNTIME": "runtime_id", "GTE_PATH_REPRESENTATION": "representation_id"}
    for name, field in fields.items():
        _require(environment.get(name) == str(config[field]), "environment identity mismatch: " + name)
    _require(environment.get("GTE_PATH_CHECKPOINT_SHA256") == config["checkpoint"]["sha256"],
             "environment identity mismatch: GTE_PATH_CHECKPOINT_SHA256")
    directories = {}
    for name, field in (("GTE_PATH_STATE_DIRECTORY", "state_directory"),
                        ("GTE_PATH_OUTPUT_DIRECTORY", "output_directory")):
        value = _text(environment.get(name), name)
        path = Path(value)
        _require(path.is_absolute(), "absolute worker directory required")
        resolved = path.resolve()
        _require(resolved.is_dir(), "coordinator-created worker directory required")
        _require(str(resolved) == value, "canonical worker directory required")
        directories[field] = str(resolved)
    _require(directories["state_directory"] != directories["output_directory"],
             "private state/output directories must be distinct")
    return {"schema": "gte-worker-environment-receipt/v1", "identities_match": True,
            **directories, "representation_authenticated": False, "checkpoint_file_verified": False,
            "filesystem_isolation_enforced": False}


def load_worker_contract(config_path, *, expected_sha256=None, environment=None):
    """Read an infer-only contract, resolve references, and compare dispatch identities.

    Checkpoint/dataset paths are relative to the configuration-file parent.
    Call ``read_pinned_json`` on each normalized reference before model use.
    This call does not load or authenticate those referenced bytes.
    """
    path = Path(config_path).resolve()
    config, receipt = read_pinned_json(path, expected_sha256=expected_sha256, max_bytes=MAX_CONFIG_BYTES)
    normalized = _config(config, path.parent)
    environment_receipt = _environment(normalized, os.environ if environment is None else environment)
    return {"config": normalized, "config_receipt": receipt, "environment_receipt": environment_receipt}


def configure_cpu_process(resources):
    """Apply offline/thread flags and nonrelaxing POSIX AS/CPU limits before imports.

    CPU seconds are total process CPU time from process start. Existing finite
    limits are never raised. Lowering a hard limit is irreversible in this worker.
    Row bounds still require enforcement by the worker's dataset reader.
    """
    resources = _resources(resources)
    _require(not any(name in sys.modules for name in ("torch", "transformers", "sentence_transformers", "tensorflow", "jax")),
             "CPU budgets must be applied before model-library imports")
    _require(os.name == "posix", "POSIX process resource limits required")
    import resource

    thread_count = str(resources["threads"])
    values = {name: thread_count for name in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "NUMEXPR_NUM_THREADS")}
    values.update({"HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "HF_DATASETS_OFFLINE": "1",
                   "HF_HUB_DISABLE_TELEMETRY": "1", "CUDA_VISIBLE_DEVICES": "", "TOKENIZERS_PARALLELISM": "false"})
    plans = {}
    for name, limit, requested in (("address_space", resource.RLIMIT_AS, resources["memory_limit_mib"] * 1024 * 1024),
                                   ("cpu_time", resource.RLIMIT_CPU, resources["cpu_time_limit_seconds"])):
        soft, hard = resource.getrlimit(limit)
        finite_hard = requested if hard == resource.RLIM_INFINITY else min(requested, hard)
        finite_soft = finite_hard if soft == resource.RLIM_INFINITY else min(finite_hard, soft)
        plans[name] = {"limit": limit, "before": {"soft": soft, "hard": hard},
                       "requested": requested, "effective": {"soft": finite_soft, "hard": finite_hard}}
    os.environ.update(values)
    for plan in plans.values():
        resource.setrlimit(plan["limit"], (plan["effective"]["soft"], plan["effective"]["hard"]))
        soft, hard = resource.getrlimit(plan["limit"])
        _require((soft, hard) == (plan["effective"]["soft"], plan["effective"]["hard"]), "effective process limit differs from plan")
    return {"schema": "gte-worker-cpu-budget-receipt/v1", "device": "cpu", "threads": resources["threads"],
            "max_rows": resources["max_rows"], "environment": values,
            "limits": {name: {key: value for key, value in plan.items() if key != "limit"} for name, plan in plans.items()},
            "scope": "this_process_only_not_aggregate_admission", "network_isolation_enforced": False,
            "model_imports_observed_before_budget": False, "dataset_row_limit_enforced": False}


def _canonical(value):
    return json.dumps(value, sort_keys=True, allow_nan=False, ensure_ascii=True,
                      separators=(",", ":")).encode("utf-8") + b"\n"


@contextmanager
def state_lease(state_directory):
    """Exclusively lease private state; never reclaim existing/stale lock files.

    Release checks both the owned inode and exact token bytes. A changed or
    replaced lock remains untouched for explicit owner review. This cooperative
    trusted-local lease is not an OS isolation boundary against external writers.
    """
    directory = Path(state_directory).resolve()
    _require(directory.is_dir(), "existing state directory required")
    path = directory / "worker.lock"
    token = {"schema": "gte-worker-state-lease/v1", "pid": os.getpid(), "nonce": secrets.token_hex(16)}
    raw = _canonical(token)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
        owned = os.fstat(stream.fileno())
    receipt = {**token, "path": str(path), "sha256": _sha(raw), "released": False}
    try:
        yield receipt
    finally:
        try:
            current = path.lstat()
            if stat.S_ISREG(current.st_mode) and (current.st_dev, current.st_ino) == (owned.st_dev, owned.st_ino):
                content, _, observed = _read_stable(path, expected_sha256=receipt["sha256"], max_bytes=4096)
                if content == raw and _identity(observed) == _identity(path.lstat()):
                    path.unlink()
                    receipt["released"] = True
        except (OSError, ValueError):
            # Preserve someone else's or damaged lease; never silently reclaim.
            pass


def write_fresh_output_json(output_directory, filename, payload):
    """Write finite JSON to one fresh exclusive file in an existing lane output."""
    directory = Path(output_directory).resolve()
    _require(directory.is_dir(), "existing output directory required")
    _text(filename, "output filename")
    _require(filename not in {".", ".."} and "/" not in filename and "\\" not in filename,
             "single output filename required")
    raw = _canonical(payload)
    path = directory / filename
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    return {"path": str(path), "bytes": len(raw), "sha256": _sha(raw)}
