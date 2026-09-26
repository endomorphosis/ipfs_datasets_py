"""Bounded wire values for an owner-leased native daemon invocation.

These descriptors establish observed integrity, not an authenticated issuer,
computation replay, model promotion, or a Lean admission.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
from types import SimpleNamespace
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[3]
REQUEST_SCHEMA = "autoencoder-daemon-invocation-request-v1"
SHADOW_REQUEST_SCHEMA = "autoencoder-daemon-invocation-request-v2"
WEIGHT_REQUEST_SCHEMA = "autoencoder-daemon-invocation-request-v3"
LAUNCH_SCHEMA = "autoencoder-daemon-invocation-launch-v1"
RESULT_SCHEMA = "autoencoder-daemon-invocation-result-v1"
MAX_REQUEST_BYTES = 4 * 1024 * 1024
MAX_RESULT_BYTES = 64 * 1024 * 1024
MAX_CHECKPOINT_BYTES = 256 * 1024 * 1024
MAX_ARROW_FEATURE_WEIGHT_BYTES = 512 * 1024 * 1024
METRIC_LINEAGE = "legal-ir-daemon-metrics-v2"
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:@+-]{0,127}\Z")
REQUEST_FIELDS = frozenset(("schema", "run_id", "variant_id", "base_version_id",
    "base_artifact", "base_identity", "input_snapshot", "variant_manifest_sha256",
    "daemon_argv", "effective_arguments", "environment", "producer_identity",
    "output_directory", "resource_policy"))
LAUNCH_FIELDS = frozenset(("schema", "request", "lease", "attempt_directory",
    "daemon_argv", "environment", "base_artifact", "resource_reservation_id"))


class DaemonInvocationError(ValueError):
    """An owned invocation does not satisfy its immutable contract."""


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode("utf-8")


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def identifier(value: Any, name: str) -> str:
    if type(value) is not str or not _TOKEN.fullmatch(value):
        raise DaemonInvocationError(f"invalid {name}")
    return value


def safe_path(value: str | Path, *, exists: bool = True) -> Path:
    path = Path(value)
    if not path.is_absolute() or path != path.resolve(strict=False):
        raise DaemonInvocationError("path must be absolute without symlink aliases")
    for part in (path, *path.parents):
        if part.is_symlink():
            raise DaemonInvocationError("symlink path is not an immutable input")
    if exists and not path.exists():
        raise DaemonInvocationError("required path is missing")
    return path


def read_bytes(path: str | Path, limit: int) -> bytes:
    path = safe_path(path)
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= limit:
            raise DaemonInvocationError("artifact is not a bounded nonempty regular file")
        raw = stream.read(limit + 1)
        after = os.fstat(stream.fileno())
        if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
                after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns):
            raise DaemonInvocationError("artifact changed while reading")
    if len(raw) != before.st_size or path.stat().st_ino != before.st_ino:
        raise DaemonInvocationError("artifact path or length changed while reading")
    return raw


def parse_json(raw: bytes) -> Any:
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise DaemonInvocationError("duplicate JSON field")
            result[key] = value
        return result
    def invalid(_):
        raise DaemonInvocationError("nonfinite JSON value")
    try:
        return json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid)
    except (ValueError, UnicodeError) as exc:
        raise DaemonInvocationError("invalid invocation JSON") from exc


def read_json(path: str | Path, limit: int = MAX_REQUEST_BYTES) -> Any:
    return parse_json(read_bytes(path, limit))


def reference(value: Mapping[str, Any], limit: int, *, with_path: bool = False) -> dict:
    fields = {"sha256", "bytes", "path"} if with_path else {"sha256", "bytes"}
    if (type(value) is not dict or set(value) != fields
            or type(value.get("sha256")) is not str or not _HASH.fullmatch(value["sha256"])
            or type(value.get("bytes")) is not int or not 0 < value["bytes"] <= limit):
        raise DaemonInvocationError("invalid bounded artifact descriptor")
    if with_path:
        safe_path(value["path"])
    return dict(value)


def describe(path: str | Path, limit: int = MAX_RESULT_BYTES) -> dict:
    path = safe_path(path)
    raw = read_bytes(path, limit)
    return {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}


def verify(ref: Mapping[str, Any], limit: int = MAX_RESULT_BYTES) -> bytes:
    reference(dict(ref), limit, with_path=True)
    raw = read_bytes(ref["path"], limit)
    if len(raw) != ref["bytes"] or hashlib.sha256(raw).hexdigest() != ref["sha256"]:
        raise DaemonInvocationError("artifact checksum or byte count differs")
    return raw


def write_new(path: str | Path, value: Any, limit: int = MAX_RESULT_BYTES) -> dict:
    path = safe_path(path, exists=False)
    raw = canonical(value)
    if not 0 < len(raw) <= limit:
        raise DaemonInvocationError("encoded artifact exceeds byte bound")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
    return {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}


def execution_environment(overrides: Mapping[str, str] | None = None) -> dict[str, str]:
    """An explicit, credential-free child environment, sealed into the request."""
    environment = {
        "PATH": "/usr/local/bin:/usr/bin:/bin", "LANG": "C.UTF-8",
        "PYTHONPATH": str(ROOT), "IPFS_DATASETS_PY_MINIMAL_IMPORTS": "1",
        "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
        "IPFS_DATASETS_PY_LAZY_INSTALL_ERGOAI": "0",
        "CUDA_VISIBLE_DEVICES": "", "IPFS_DATASETS_MODAL_AUTOENCODER_AUTO_CUDA": "0",
        "IPFS_DATASETS_LEGAL_IR_METRIC_DISK_CACHE": "0",
        "IPFS_DATASETS_LEGAL_IR_ADAPTER_WORKERS": "1",
        "IPFS_DATASETS_LEGAL_IR_PARALLEL_WORKERS": "1",
        "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1",
    }
    # Preserve the user's existing home/cache location, not credentials or the
    # ambient application's arbitrary settings. No directory is repurposed.
    for key in ("HOME", "XDG_CACHE_HOME", "HF_HOME", "HF_HUB_CACHE", "TRANSFORMERS_CACHE",
                "IPFS_DATASETS_RESOURCE_SCHEDULER_PATH", "IPFS_DATASETS_RESOURCE_CPU_SLOTS",
                "IPFS_DATASETS_RESOURCE_MEMORY_MB", "IPFS_DATASETS_RESOURCE_GPU_MEMORY_MB",
                "IPFS_DATASETS_RESOURCE_UNIFIED_MEMORY_MB", "IPFS_DATASETS_RESOURCE_CHILD_PROCESS_SLOTS"):
        if key in os.environ:
            environment[key] = os.environ[key]
    allowed = {"IPFS_DATASETS_LEGAL_IR_METRIC_DISK_CACHE", "IPFS_DATASETS_LEGAL_IR_ADAPTER_WORKERS",
               "IPFS_DATASETS_LEGAL_IR_PARALLEL_WORKERS", "OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS",
               "MKL_NUM_THREADS"}
    for key, value in dict(overrides or {}).items():
        if key not in allowed or type(value) is not str or not value.isdecimal():
            raise DaemonInvocationError("unsupported execution environment override")
        if key.endswith("DISK_CACHE") and value not in {"0", "1"}:
            raise DaemonInvocationError("invalid metric disk cache policy")
        if not key.endswith("DISK_CACHE") and not 1 <= int(value) <= 32:
            raise DaemonInvocationError("invalid worker/thread bound")
        environment[key] = value
    return environment


def effective_configuration(argv: list[str]) -> dict:
    from . import uscode_modal_daemon_runner as runner
    if type(argv) is not list or not all(type(arg) is str for arg in argv) or len(canonical(argv)) > 65536:
        raise DaemonInvocationError("invalid bounded daemon argv")
    args = runner.build_uscode_modal_daemon_arg_parser().parse_args(argv)
    values = {key: str(value) if isinstance(value, Path) else value for key, value in vars(args).items()}
    if args.loop_role != "autoencoder" or args.max_cycles != 1:
        raise DaemonInvocationError("owned invocation requires explicit autoencoder role and max_cycles=1")
    identifier(args.run_id, "daemon run ID")
    if args.autoencoder_device != "python":
        raise DaemonInvocationError("owned invocation currently requires the qualified CPU backend")
    if args.bridge_evaluate_provers:
        raise DaemonInvocationError("external bridge prover execution is not qualified for offline invocations")
    if args.warm_start_state or args.warm_start_run_id or args.autoencoder_canonical_warm_start != "off":
        raise DaemonInvocationError("warm starts require a separately bound dependency closure")
    for key in ("leanstral_direct_guidance_path", "leanstral_rule_gap_report_path", "daemon_hammer_guidance_output_dir"):
        if values.get(key):
            raise DaemonInvocationError(f"unbound external dependency: {key}")
    if values.get("leanstral_rule_gap_wait_seconds", 0) != 0:
        raise DaemonInvocationError("external guidance wait requires an explicit dependency handoff")
    if any(values.get(key) for key in ("leanstral_direct_guidance_projection_enabled",
            "leanstral_direct_guidance_train_autoencoder", "leanstral_rule_gap_projection_enabled",
            "daemon_hammer_guidance_enabled", "daemon_hammer_guidance_train_autoencoder")):
        raise DaemonInvocationError("unbound external guidance cannot enter an owned candidate")
    if values.get("codex_exec_mode") != "packet_only" or values.get("codex_commit_mode") != "none":
        raise DaemonInvocationError("external executor/commit effects are not qualified for this adapter")
    if args.autoencoder_bridge_workers != int(os.environ["IPFS_DATASETS_LEGAL_IR_PARALLEL_WORKERS"]):
        raise DaemonInvocationError("effective bridge workers differ from the sealed environment")
    descriptor = runner._daemon_corpus_input_descriptor(args)
    if descriptor is None:
        raise DaemonInvocationError("owned daemon requires verified local corpus inputs")
    # Ordinary internal TODO and projection policies are retained verbatim.
    # Rejection of unsupported external dependencies never silently disables them.
    return values


def producer_identity(arguments: Mapping[str, Any]) -> dict:
    from .autoencoder_target_preparation import target_snapshot_config
    bridges = []
    for key in ("bridge_loss_adapters", "autoencoder_metric_bridge_adapters", "autoencoder_diagnostic_bridge_adapters"):
        for name in str(arguments.get(key, "")).split(","):
            if name.strip() and name.strip() not in bridges:
                bridges.append(name.strip())
    # Only fingerprints producer code/runtime; no worker training policy is
    # substituted for the daemon's parsed argument namespace.
    return target_snapshot_config(SimpleNamespace(legal_ir_bridge_names=tuple(bridges),
        legal_ir_evaluate_provers=arguments["bridge_evaluate_provers"],
        legal_ir_parallel_workers=arguments["autoencoder_bridge_workers"])).to_dict()


def load_full_checkpoint(ref: Mapping[str, Any], *, compact_only: bool = False):
    from .modal_autoencoder_checkpoint import CHECKPOINT_MAGIC, load_checkpoint
    raw = verify(ref, MAX_CHECKPOINT_BYTES)
    if not raw.startswith(CHECKPOINT_MAGIC):
        if compact_only:
            raise DaemonInvocationError("candidate must be a full compact checkpoint")
        value = parse_json(raw)
        if type(value) is not dict or not {"feature_embedding_weights", "family_logits", "applied_todo_ids"} <= value.keys():
            raise DaemonInvocationError("base is not a full legacy state; sparse manifests require materialization")
    del raw
    loaded = load_checkpoint(ref["path"], recover=False, allow_json=not compact_only)
    if loaded.manifest.kind != "full" or loaded.manifest.float_precision != "float64":
        raise DaemonInvocationError("owned checkpoint must be a full float64 state")
    verify(ref, MAX_CHECKPOINT_BYTES)
    return loaded


def validate_request(value: Any) -> dict:
    if type(value) is not dict or type(value.get("schema")) is not str:
        raise DaemonInvocationError("invalid closed daemon request")
    schema = value["schema"]
    if schema == REQUEST_SCHEMA:
        valid_shape = set(value) == REQUEST_FIELDS
    elif schema == SHADOW_REQUEST_SCHEMA:
        valid_shape = set(value) == REQUEST_FIELDS | {"sparse_shadow"} and value.get("sparse_shadow") is True
    elif schema == WEIGHT_REQUEST_SCHEMA:
        valid_shape = (set(value) == REQUEST_FIELDS | {"sparse_shadow", "arrow_feature_weights"}
                       and type(value.get("sparse_shadow")) is bool)
    else:
        valid_shape = False
    if not valid_shape:
        raise DaemonInvocationError("invalid closed daemon request")
    for name in ("run_id", "variant_id"):
        identifier(value[name], name)
    if type(value["base_version_id"]) is not str or not value["base_version_id"]:
        raise DaemonInvocationError("missing registered base identity")
    reference(value["base_artifact"], MAX_CHECKPOINT_BYTES, with_path=True)
    reference(value["input_snapshot"], 1024 * 1024, with_path=True)
    if schema == WEIGHT_REQUEST_SCHEMA:
        reference(value["arrow_feature_weights"], MAX_ARROW_FEATURE_WEIGHT_BYTES, with_path=True)
    safe_path(value["output_directory"])
    if not _HASH.fullmatch(str(value["variant_manifest_sha256"])):
        raise DaemonInvocationError("invalid variant digest")
    for key in ("base_identity", "effective_arguments", "environment", "producer_identity", "resource_policy"):
        if type(value[key]) is not dict:
            raise DaemonInvocationError(f"invalid request {key}")
    if len(canonical(value)) > MAX_REQUEST_BYTES:
        raise DaemonInvocationError("request exceeds byte bound")
    return value


def validate_launch(value: Any, request: Mapping[str, Any]) -> dict:
    if type(value) is not dict or set(value) != LAUNCH_FIELDS or value["schema"] != LAUNCH_SCHEMA:
        raise DaemonInvocationError("invalid closed daemon launch")
    reference(value["request"], MAX_REQUEST_BYTES, with_path=True)
    if value["lease"].get("run_id") != request["run_id"]:
        raise DaemonInvocationError("launch lease belongs to another run")
    attempt = safe_path(value["attempt_directory"])
    if attempt.parent != safe_path(request["output_directory"]):
        raise DaemonInvocationError("launch attempt escaped its request output directory")
    if value["daemon_argv"] != request["daemon_argv"] or value["environment"] != request["environment"]:
        raise DaemonInvocationError("launch settings differ from sealed request")
    if value["base_artifact"] != request["base_artifact"]:
        raise DaemonInvocationError("launch base differs from request")
    return value
