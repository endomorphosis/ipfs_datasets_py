#!/usr/bin/env python3
"""Verify a local checkpoint's lineage identity without loading model weights.

This is a preflight tool, not a runner or a checkpoint migration. Its receipt
does not establish runtime compatibility, semantic qualification, or admission.
Only the Python standard library is used; no network or model code is invoked.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import sys
from typing import Any


SCHEMA = "legal-autoencoder-lineages/v1"
RECEIPT_SCHEMA = "legal-autoencoder-lineage-check/v1"
DEFAULT_REGISTRY = Path(__file__).resolve().parents[3] / "configs/autoencoders/legal_autoencoder_lineages.json"
MAX_REGISTRY_BYTES = 1024 * 1024
HASH_CHUNK_BYTES = 1024 * 1024
LINEAGES = {"legacy_hub_v1", "current_legal_v2"}
# These historic checkpoints must never be relabeled as a current architecture.
HISTORICAL_CHECKPOINTS = frozenset({
    "7236de26bd3d7f8414ffa04805f1b6e8a8849f9e0103cec6edb4985b911658be",
    "1446cb1859ddf4ed40fb5576f6e320eece4cec268a008c5c07bffeaf959cd8dd",
})


def _reject_constant(value: str) -> None:
    raise ValueError(f"nonfinite JSON value: {value}")


def _finite_float(value: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"nonfinite JSON value: {value}")
    return result


def _unique_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate registry key: {key}")
        result[key] = value
    return result


def _hex(value: Any, length: int, label: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{" + str(length) + "}", value) is None:
        raise ValueError(f"{label} must be a lowercase {length}-character hexadecimal digest")
    return value


def _identity(info: os.stat_result) -> tuple[int, int, int, int, int]:
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _stable_read(path: Path, *, retain: bool = False) -> tuple[str, int, bytes | None]:
    """Read a regular file in bounded chunks and reject concurrent replacement/edit."""
    before = path.stat()
    if not stat.S_ISREG(before.st_mode):
        raise ValueError(f"input must be a regular file: {path}")
    if retain and before.st_size > MAX_REGISTRY_BYTES:
        raise ValueError("registry exceeds byte bound")
    digest = hashlib.sha256()
    size = 0
    parts = [] if retain else None
    with path.open("rb") as handle:
        if _identity(os.fstat(handle.fileno())) != _identity(before):
            raise ValueError("input changed before hashing")
        while chunk := handle.read(HASH_CHUNK_BYTES):
            size += len(chunk)
            if retain and size > MAX_REGISTRY_BYTES:
                raise ValueError("registry exceeds byte bound")
            digest.update(chunk)
            if parts is not None:
                parts.append(chunk)
        after_handle = os.fstat(handle.fileno())
    after_path = path.stat()
    if size != before.st_size or _identity(before) != _identity(after_handle) or _identity(before) != _identity(after_path):
        raise ValueError("input changed during hashing")
    return digest.hexdigest(), size, b"".join(parts) if parts is not None else None


def _positive_size(value: Any) -> None:
    if type(value) is not int or value <= 0:
        raise ValueError("checkpoint size_bytes must be a positive integer")


def validate_registry(registry: Any) -> dict[str, Any]:
    if not isinstance(registry, dict) or registry.get("schema") != SCHEMA:
        raise ValueError(f"registry schema must be {SCHEMA}")
    lineages = registry.get("lineages")
    if not isinstance(lineages, dict) or set(lineages) != LINEAGES:
        raise ValueError("registry must define legacy_hub_v1 and current_legal_v2 exactly")
    namespaces = set()
    for name, item in lineages.items():
        if not isinstance(item, dict) or item.get("lineage_id") != name:
            raise ValueError(f"lineage_id differs from registry key: {name}")
        _hex(item.get("source_baseline_commit"), 40, "source_baseline_commit")
        for field in ("artifact_namespace", "role"):
            if not isinstance(item.get(field), str) or not item[field].strip():
                raise ValueError(f"{name}: {field} must be a nonempty string")
        namespace = item["artifact_namespace"]
        if namespace.startswith("/") or "\\" in namespace or any(part in ("", ".", "..") for part in namespace.split("/")):
            raise ValueError("artifact_namespace must be a relative path without traversal")
        if namespace in namespaces:
            raise ValueError("lineages must have different artifact_namespace values")
        namespaces.add(namespace)
        policy = item.get("checkpoint_policy")
        if not isinstance(policy, dict) or policy.get("mode") not in ("fixed_sha256", "explicit_sha256"):
            raise ValueError(f"{name}: unknown checkpoint policy mode")
        if set(policy) - {"mode", "sha256", "size_bytes", "forbidden_sha256"}:
            raise ValueError(f"{name}: unknown checkpoint policy fields")
        required_mode = "fixed_sha256" if name == "legacy_hub_v1" else "explicit_sha256"
        if policy["mode"] != required_mode:
            raise ValueError(f"{name}: checkpoint policy must use {required_mode}")
        if policy["mode"] == "fixed_sha256":
            _hex(policy.get("sha256"), 64, "checkpoint sha256")
            _positive_size(policy.get("size_bytes"))
        elif "sha256" in policy:
            raise ValueError("explicit_sha256 policy must not supply a default sha256")
        if "size_bytes" in policy:
            _positive_size(policy["size_bytes"])
        forbidden = policy.get("forbidden_sha256", [])
        if not isinstance(forbidden, list):
            raise ValueError("forbidden_sha256 must be a list")
        for digest in forbidden:
            _hex(digest, 64, "forbidden sha256")
        if policy.get("sha256") in forbidden:
            raise ValueError("fixed checkpoint sha256 is also forbidden")
    return registry


def _write_new_receipt(path: Path, receipt: dict[str, Any]) -> None:
    raw = (json.dumps(receipt, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def check_lineage(
    registry_path: Path | str,
    lineage: str,
    checkpoint_path: Path | str,
    *,
    expected_sha256: str | None = None,
    output_receipt: Path | str | None = None,
) -> dict[str, Any]:
    """Hash and bind local checkpoint bytes to a selected, explicit lineage."""
    if lineage not in LINEAGES:
        raise ValueError(f"unknown lineage: {lineage}")
    registry_path = Path(registry_path).resolve(strict=True)
    checkpoint_path = Path(checkpoint_path).resolve(strict=True)
    output = Path(output_receipt).absolute() if output_receipt is not None else None
    if output is not None:
        if output.resolve() in (registry_path, checkpoint_path):
            raise ValueError("output receipt aliases an input")
        if os.path.lexists(output):
            raise FileExistsError(f"output receipt already exists: {output}")
    registry_sha256, registry_bytes, raw = _stable_read(registry_path, retain=True)
    registry = validate_registry(json.loads(raw, parse_constant=_reject_constant,
                                            parse_float=_finite_float, object_pairs_hook=_unique_keys))
    item = registry["lineages"][lineage]
    policy = item["checkpoint_policy"]
    if expected_sha256 is not None:
        _hex(expected_sha256, 64, "expected sha256")
    if policy["mode"] == "fixed_sha256":
        expected = policy["sha256"]
        if expected_sha256 is not None and expected_sha256 != expected:
            raise ValueError("expected sha256 differs from fixed lineage checkpoint")
    else:
        if expected_sha256 is None:
            raise ValueError("current_legal_v2 requires --expected-sha256; no checkpoint is selected automatically")
        expected = expected_sha256
    forbidden = set(policy.get("forbidden_sha256", []))
    if lineage == "current_legal_v2":
        forbidden.update(HISTORICAL_CHECKPOINTS)
        forbidden.add(registry["lineages"]["legacy_hub_v1"]["checkpoint_policy"]["sha256"])
    if expected in forbidden:
        raise ValueError("checkpoint sha256 belongs to a forbidden lineage")
    actual, byte_count, _ = _stable_read(checkpoint_path)
    if actual in forbidden:
        raise ValueError("checkpoint sha256 belongs to a forbidden lineage")
    if actual != expected:
        raise ValueError(f"checkpoint sha256 mismatch: expected {expected}, observed {actual}")
    if "size_bytes" in policy and byte_count != policy["size_bytes"]:
        raise ValueError(f"checkpoint size_bytes mismatch: expected {policy['size_bytes']}, observed {byte_count}")
    receipt = {
        "schema": RECEIPT_SCHEMA,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "lineage_id": lineage,
        "role": item["role"],
        "artifact_namespace": item["artifact_namespace"],
        "source_baseline_commit": item["source_baseline_commit"],
        "registry": {"path": str(registry_path), "sha256": registry_sha256, "size_bytes": registry_bytes},
        "checkpoint": {"path": str(checkpoint_path), "sha256": actual, "size_bytes": byte_count},
        "checkpoint_policy_mode": policy["mode"],
        "checkpoint_identity_verified": True,
        "runtime_compatibility_checked": False,
        "qualification": False,
        "admitted": False,
        "execution_not_started": True,
    }
    if output is not None:
        _write_new_receipt(output, receipt)
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--lineage", required=True, choices=sorted(LINEAGES))
    parser.add_argument("--checkpoint", required=True, type=Path, help="Existing local checkpoint; never downloaded or deserialized")
    parser.add_argument("--expected-sha256", help="Required explicit current-lineage checkpoint digest")
    parser.add_argument("--output-receipt", type=Path, help="Create a new receipt; existing paths are never overwritten")
    args = parser.parse_args(argv)
    try:
        receipt = check_lineage(args.registry, args.lineage, args.checkpoint,
                                expected_sha256=args.expected_sha256, output_receipt=args.output_receipt)
    except (ValueError, OSError) as error:
        print(f"lineage identity check failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps(receipt, indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
