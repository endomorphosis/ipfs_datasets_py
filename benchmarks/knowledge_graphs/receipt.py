"""Versioned load-run receipts (KGP-029).

Receipts bind environment, repository revision, seed, config, throughput,
latency histograms, queue/conflict/error counters, CPU/RSS/heap/FD samples,
cache/IPFS bytes and fetches, shard fan-out, and recovery measurements.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import socket
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

JSONDict = Dict[str, Any]

RECEIPT_SCHEMA = "ipfs-datasets.knowledge-graphs.load-receipt.v1"
RECEIPT_SCHEMA_VERSION = 1

# Mandatory top-level keys for validate_receipt.
REQUIRED_RECEIPT_KEYS = (
    "schema",
    "schema_version",
    "receipt_id",
    "created_at",
    "environment",
    "revision",
    "seed",
    "config",
    "throughput",
    "latency_histogram",
    "queue",
    "conflict",
    "error",
    "resources",
    "cache",
    "ipfs",
    "shard_fan_out",
    "recovery",
    "results",
)


def _git_revision(cwd: Optional[Path] = None) -> JSONDict:
    """Capture git HEAD revision and dirty flag when available."""
    root = cwd or Path.cwd()
    info: JSONDict = {
        "commit": None,
        "short": None,
        "branch": None,
        "dirty": None,
        "describe": None,
        "source": "unavailable",
    }
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if commit.returncode != 0:
            return info
        full = (commit.stdout or "").strip()
        info["commit"] = full
        info["short"] = full[:12]
        info["source"] = "git"
        branch = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if branch.returncode == 0:
            info["branch"] = (branch.stdout or "").strip()
        dirty = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if dirty.returncode == 0:
            info["dirty"] = bool((dirty.stdout or "").strip())
        describe = subprocess.run(
            ["git", "describe", "--always", "--tags", "--dirty"],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if describe.returncode == 0:
            info["describe"] = (describe.stdout or "").strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return info


def capture_environment(*, repo_root: Optional[Path] = None) -> JSONDict:
    """Snapshot host / interpreter / process environment for the receipt."""
    return {
        "hostname": socket.gethostname(),
        "platform": platform.platform(),
        "system": platform.system(),
        "release": platform.release(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "python_version": sys.version,
        "python_implementation": platform.python_implementation(),
        "python_executable": sys.executable,
        "pid": os.getpid(),
        "cwd": str(Path.cwd()),
        "cpu_count": os.cpu_count(),
        "env_labels": {
            "CI": os.environ.get("CI"),
            "GITHUB_ACTIONS": os.environ.get("GITHUB_ACTIONS"),
            "HOSTNAME": os.environ.get("HOSTNAME"),
            "IPFS_ACCELERATE_AGENT_TASK_CHECKPOINT_DIR": os.environ.get(
                "IPFS_ACCELERATE_AGENT_TASK_CHECKPOINT_DIR"
            ),
        },
        "revision": _git_revision(repo_root),
    }


def _canonical_json(data: Mapping[str, Any]) -> bytes:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), default=str).encode(
        "utf-8"
    )


def content_digest(data: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(data)).hexdigest()


@dataclass
class LoadReceipt:
    """In-memory versioned load receipt."""

    schema: str = RECEIPT_SCHEMA
    schema_version: int = RECEIPT_SCHEMA_VERSION
    receipt_id: str = ""
    created_at: float = field(default_factory=time.time)
    environment: JSONDict = field(default_factory=dict)
    revision: JSONDict = field(default_factory=dict)
    seed: int = 0
    config: JSONDict = field(default_factory=dict)
    throughput: JSONDict = field(default_factory=dict)
    latency_histogram: JSONDict = field(default_factory=dict)
    queue: JSONDict = field(default_factory=dict)
    conflict: JSONDict = field(default_factory=dict)
    error: JSONDict = field(default_factory=dict)
    resources: JSONDict = field(default_factory=dict)
    cache: JSONDict = field(default_factory=dict)
    ipfs: JSONDict = field(default_factory=dict)
    shard_fan_out: JSONDict = field(default_factory=dict)
    recovery: JSONDict = field(default_factory=dict)
    results: List[JSONDict] = field(default_factory=list)
    shape_fingerprint: Optional[str] = None
    elapsed_s: float = 0.0
    status: str = "success"
    warnings: List[str] = field(default_factory=list)
    digest: Optional[str] = None

    def to_json_dict(self) -> JSONDict:
        body = {
            "schema": self.schema,
            "schema_version": self.schema_version,
            "receipt_id": self.receipt_id,
            "created_at": self.created_at,
            "environment": dict(self.environment),
            "revision": dict(self.revision),
            "seed": self.seed,
            "config": dict(self.config),
            "throughput": dict(self.throughput),
            "latency_histogram": dict(self.latency_histogram),
            "queue": dict(self.queue),
            "conflict": dict(self.conflict),
            "error": dict(self.error),
            "resources": dict(self.resources),
            "cache": dict(self.cache),
            "ipfs": dict(self.ipfs),
            "shard_fan_out": dict(self.shard_fan_out),
            "recovery": dict(self.recovery),
            "results": list(self.results),
            "shape_fingerprint": self.shape_fingerprint,
            "elapsed_s": self.elapsed_s,
            "status": self.status,
            "warnings": list(self.warnings),
        }
        # Digest excludes itself for stable content addressing.
        body["digest"] = content_digest(body)
        self.digest = body["digest"]
        return body


def build_receipt(
    *,
    seed: int,
    config: Mapping[str, Any],
    throughput: Mapping[str, Any],
    latency_histogram: Mapping[str, Any],
    counters: Mapping[str, Any],
    resources_start: Mapping[str, Any],
    resources_end: Mapping[str, Any],
    resources_peak: Optional[Mapping[str, Any]] = None,
    shard_fan_out: Mapping[str, Any],
    recovery: Mapping[str, Any],
    results: Sequence[Mapping[str, Any]],
    shape_fingerprint: Optional[str] = None,
    elapsed_s: float = 0.0,
    status: str = "success",
    warnings: Optional[Sequence[str]] = None,
    environment: Optional[Mapping[str, Any]] = None,
    repo_root: Optional[Path] = None,
    receipt_id: Optional[str] = None,
) -> LoadReceipt:
    """Assemble a complete versioned receipt from harness measurements."""
    env = dict(environment) if environment is not None else capture_environment(
        repo_root=repo_root
    )
    revision = dict(env.get("revision") or _git_revision(repo_root))
    ctr = dict(counters)
    rid = receipt_id or f"kg-load-{int(time.time())}-{seed:08x}"

    receipt = LoadReceipt(
        receipt_id=rid,
        created_at=time.time(),
        environment=env,
        revision=revision,
        seed=int(seed),
        config=dict(config),
        throughput=dict(throughput),
        latency_histogram=dict(latency_histogram),
        queue={
            "wait_ms_total": ctr.get("queue_wait_ms_total", 0.0),
            "depth_peak": ctr.get("queue_depth_peak", 0),
        },
        conflict={
            "count": ctr.get("conflicts", 0),
            "rate": (
                float(ctr.get("conflicts", 0))
                / float(ctr.get("operations_total") or 1)
            ),
        },
        error={
            "count": ctr.get("operations_error", 0),
            "rate": (
                float(ctr.get("operations_error", 0))
                / float(ctr.get("operations_total") or 1)
            ),
            "operations_ok": ctr.get("operations_ok", 0),
            "operations_total": ctr.get("operations_total", 0),
        },
        resources={
            "start": dict(resources_start),
            "end": dict(resources_end),
            "peak": dict(resources_peak or resources_end),
            "cpu": {
                "user_s_delta": float(resources_end.get("cpu_user_s", 0))
                - float(resources_start.get("cpu_user_s", 0)),
                "system_s_delta": float(resources_end.get("cpu_system_s", 0))
                - float(resources_start.get("cpu_system_s", 0)),
            },
            "rss_bytes_end": resources_end.get("rss_bytes"),
            "heap_bytes_end": resources_end.get("heap_bytes"),
            "open_fds_end": resources_end.get("open_fds"),
            "max_rss_bytes": max(
                int(resources_start.get("max_rss_bytes") or 0),
                int(resources_end.get("max_rss_bytes") or 0),
                int((resources_peak or {}).get("max_rss_bytes") or 0),
            ),
        },
        cache={
            "hits": ctr.get("cache_hits", 0),
            "misses": ctr.get("cache_misses", 0),
            "bytes": ctr.get("cache_bytes", 0),
            "hit_rate": (
                float(ctr.get("cache_hits", 0))
                / float(
                    (ctr.get("cache_hits", 0) or 0)
                    + (ctr.get("cache_misses", 0) or 0)
                    or 1
                )
            ),
        },
        ipfs={
            "bytes": ctr.get("ipfs_bytes", 0),
            "fetches": ctr.get("ipfs_fetches", 0),
            "puts": ctr.get("ipfs_puts", 0),
            "bytes_written": ctr.get("bytes_written", 0),
            "bytes_read": ctr.get("bytes_read", 0),
        },
        shard_fan_out=dict(shard_fan_out),
        recovery=dict(recovery),
        results=[dict(r) for r in results],
        shape_fingerprint=shape_fingerprint,
        elapsed_s=float(elapsed_s),
        status=status,
        warnings=list(warnings or ()),
    )
    return receipt


def receipt_to_json(receipt: LoadReceipt) -> JSONDict:
    return receipt.to_json_dict()


def validate_receipt(data: Mapping[str, Any]) -> List[str]:
    """Return a list of validation problems (empty means valid)."""
    problems: List[str] = []
    if not isinstance(data, Mapping):
        return ["receipt must be a mapping"]
    for key in REQUIRED_RECEIPT_KEYS:
        if key not in data:
            problems.append(f"missing required key: {key}")
    if data.get("schema") != RECEIPT_SCHEMA:
        problems.append(
            f"schema must be {RECEIPT_SCHEMA!r}, got {data.get('schema')!r}"
        )
    if data.get("schema_version") != RECEIPT_SCHEMA_VERSION:
        problems.append(
            f"schema_version must be {RECEIPT_SCHEMA_VERSION}, "
            f"got {data.get('schema_version')!r}"
        )
    if not isinstance(data.get("seed"), int):
        problems.append("seed must be int")
    for section in (
        "environment",
        "revision",
        "config",
        "throughput",
        "latency_histogram",
        "queue",
        "conflict",
        "error",
        "resources",
        "cache",
        "ipfs",
        "shard_fan_out",
        "recovery",
    ):
        if section in data and not isinstance(data[section], Mapping):
            problems.append(f"{section} must be a mapping")
    if "results" in data and not isinstance(data["results"], list):
        problems.append("results must be a list")
    # Nested resource fields.
    resources = data.get("resources") if isinstance(data.get("resources"), Mapping) else {}
    for snap in ("start", "end"):
        if snap in resources and not isinstance(resources[snap], Mapping):
            problems.append(f"resources.{snap} must be a mapping")
        elif isinstance(resources.get(snap), Mapping):
            for field_name in (
                "cpu_user_s",
                "cpu_system_s",
                "rss_bytes",
                "heap_bytes",
                "open_fds",
            ):
                if field_name not in resources[snap]:
                    problems.append(f"resources.{snap} missing {field_name}")
    hist = data.get("latency_histogram") if isinstance(data.get("latency_histogram"), Mapping) else {}
    for field_name in ("count", "p50_ms", "p95_ms", "p99_ms", "buckets_ms", "bucket_counts"):
        if field_name not in hist:
            problems.append(f"latency_histogram missing {field_name}")
    thr = data.get("throughput") if isinstance(data.get("throughput"), Mapping) else {}
    for field_name in ("ops_per_s", "operations", "elapsed_s"):
        if field_name not in thr:
            problems.append(f"throughput missing {field_name}")
    return problems


def write_receipt(receipt: LoadReceipt, path: Path | str) -> Path:
    """Atomically write a receipt JSON file."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(receipt.to_json_dict(), indent=2, sort_keys=True) + "\n"
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(payload, encoding="utf-8")
    tmp.replace(target)
    return target


def load_receipt(path: Path | str) -> JSONDict:
    return json.loads(Path(path).read_text(encoding="utf-8"))
