#!/usr/bin/env python3
"""Inventory explicit local training artifacts without granting training eligibility.

Inputs are closed ``source-training-inventory-spec/v1`` JSON specifications.
Each artifact declares an ID, domain, path, format, role and source kind. JSON
record arrays require a JSON Pointer; JSONL records are counted incrementally.
Optional record_fields are JSON Pointers whose *presence*, never contents or
truth, is counted. File references inside artifacts are never followed. No
package/model import, source execution, network request or corpus scan occurs.
"""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict, dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
from typing import Any

DOMAINS = ("legal_ir", "intent_ir", "security_ir", "ui_ux_ir")
ROLES = {"source", "rows", "embedding_manifest", "split_manifest", "target_manifest", "native_receipt"}
SOURCE_KINDS = {"real_source", "authored_diagnostic", "mixed", "unknown"}
SCHEMA = "source-training-inventory/v1"
SPEC_SCHEMA = "source-training-inventory-spec/v1"


class InventoryError(ValueError):
    """A bounded input or inventory declaration was invalid."""


@dataclass(frozen=True)
class Limits:
    max_artifacts: int = 128
    max_file_bytes: int = 64 * 1024 * 1024
    max_total_bytes: int = 256 * 1024 * 1024
    max_json_bytes: int = 32 * 1024 * 1024
    max_record_bytes: int = 1024 * 1024
    max_records: int = 100_000
    max_json_nodes: int = 500_000
    max_json_depth: int = 32

    def __post_init__(self):
        ceilings = {"max_artifacts": 1024, "max_file_bytes": 1024**3,
                    "max_total_bytes": 4 * 1024**3, "max_json_bytes": 128 * 1024**2,
                    "max_record_bytes": 16 * 1024**2, "max_records": 1_000_000,
                    "max_json_nodes": 2_000_000, "max_json_depth": 64}
        for key, limit in ceilings.items():
            if type(getattr(self, key)) is not int or not 1 <= getattr(self, key) <= limit:
                raise InventoryError(f"invalid bound: {key}")


def _strict_json(raw: bytes, limits: Limits) -> Any:
    def pairs(items):
        value = {}
        for key, item in items:
            if key in value:
                raise InventoryError("duplicate_json_key")
            value[key] = item
        return value
    try:
        value = json.loads(raw, object_pairs_hook=pairs,
                           parse_constant=lambda _: (_ for _ in ()).throw(InventoryError("nonfinite_json")))
    except (ValueError, UnicodeError, RecursionError, OverflowError) as exc:
        raise InventoryError("invalid_json") from exc
    remaining = limits.max_json_nodes
    pending = [(value, 0)]
    while pending:
        item, depth = pending.pop()
        remaining -= 1
        if remaining < 0 or depth > limits.max_json_depth:
            raise InventoryError("json_shape_limit_exceeded")
        if isinstance(item, dict):
            if len(item) > remaining:
                raise InventoryError("json_shape_limit_exceeded")
            pending.extend((child, depth + 1) for child in item.values())
        elif isinstance(item, list):
            if len(item) > remaining:
                raise InventoryError("json_shape_limit_exceeded")
            pending.extend((child, depth + 1) for child in item)
        elif isinstance(item, float) and not math.isfinite(item):
            raise InventoryError("nonfinite_json")
    return value


def _pointer_tokens(pointer: str) -> tuple[str, ...]:
    if not isinstance(pointer, str) or len(pointer) > 1024 or (pointer and not pointer.startswith("/")):
        raise InventoryError("invalid JSON Pointer")
    parts = pointer[1:].split("/") if pointer else []
    if len(parts) > 16 or any(re.search(r"~(?![01])", part) for part in parts):
        raise InventoryError("invalid JSON Pointer")
    return tuple(part.replace("~1", "/").replace("~0", "~") for part in parts)


def _at(value: Any, pointer: str):
    for token in _pointer_tokens(pointer):
        if isinstance(value, dict) and token in value:
            value = value[token]
        elif isinstance(value, list) and re.fullmatch(r"0|[1-9][0-9]*", token) and int(token) < len(value):
            value = value[int(token)]
        else:
            return False, None
    return True, value


def _same_file(before, after):
    return all(getattr(before, name) == getattr(after, name)
               for name in ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns"))


def _open_regular(path: Path):
    # Reject final symlinks and nonregular files before opening (including FIFO).
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode):
        raise InventoryError("not_regular_file")
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    stream = os.fdopen(fd, "rb")
    opened = os.fstat(stream.fileno())
    if not stat.S_ISREG(opened.st_mode) or not _same_file(before, opened):
        stream.close()
        raise InventoryError("changed_during_open")
    return stream, before


def _artifact(spec, path: Path, limits: Limits, remaining: int):
    result = {"artifact_id": spec["artifact_id"], "domain_id": spec["domain_id"], "path": str(path),
              "declared_role": spec["declared_role"], "declared_source_kind": spec["declared_source_kind"],
              "format": spec["format"], "status": "unavailable", "bytes_read": 0,
              "content_sha256": None, "evidence_verified": False, "readiness_assessed": False}
    stream = None
    try:
        stream, before = _open_regular(path)
        result["file_size_bytes"] = before.st_size
        if before.st_size > limits.max_file_bytes or before.st_size > remaining:
            raise InventoryError("file_or_total_byte_limit_exceeded")
        if spec["format"] == "json" and before.st_size > limits.max_json_bytes:
            raise InventoryError("json_byte_limit_exceeded")
        digest = hashlib.sha256()
        error = None
        rows = 0
        fields = {pointer: {"present_rows": 0, "nonempty_rows": 0} for pointer in spec.get("record_fields", [])}
        def record(value):
            nonlocal rows
            if rows >= limits.max_records:
                raise InventoryError("record_limit_exceeded")
            if not isinstance(value, dict):
                raise InventoryError("record_not_object")
            rows += 1
            for pointer, observed in fields.items():
                present, field = _at(value, pointer)
                observed["present_rows"] += int(present)
                observed["nonempty_rows"] += int(present and field is not None and field != "" and field != [] and field != {})
        chunks = []
        if spec["format"] == "jsonl":
            while True:
                line = stream.readline(limits.max_record_bytes + 1)
                if not line:
                    break
                digest.update(line)
                result["bytes_read"] += len(line)
                if result["bytes_read"] > min(limits.max_file_bytes, remaining):
                    raise InventoryError("file_grew_beyond_byte_limit")
                if error is not None:
                    continue
                try:
                    if len(line) > limits.max_record_bytes:
                        raise InventoryError("record_byte_limit_exceeded")
                    if not line.strip():
                        raise InventoryError("blank_jsonl_record")
                    record(_strict_json(line, limits))
                except InventoryError as exc:
                    error = str(exc)
        else:
            while True:
                chunk = stream.read(min(1024 * 1024, limits.max_file_bytes - result["bytes_read"] + 1))
                if not chunk:
                    break
                digest.update(chunk)
                result["bytes_read"] += len(chunk)
                if result["bytes_read"] > min(limits.max_file_bytes, remaining):
                    raise InventoryError("file_grew_beyond_byte_limit")
                if spec["format"] == "json":
                    if result["bytes_read"] > limits.max_json_bytes:
                        raise InventoryError("file_grew_beyond_json_limit")
                    chunks.append(chunk)
            if spec["format"] == "json":
                try:
                    value = _strict_json(b"".join(chunks), limits)
                    schema = value.get("schema") if isinstance(value, dict) else None
                    if isinstance(schema, str) and re.fullmatch(r"[A-Za-z0-9_.:/-]{1,160}", schema):
                        result["observed_schema"] = schema
                    if "records_pointer" in spec:
                        present, selected = _at(value, spec["records_pointer"])
                        if not present or not isinstance(selected, list):
                            raise InventoryError("records_pointer_not_array")
                        for value in selected:
                            record(value)
                except InventoryError as exc:
                    error = str(exc)
        after = os.fstat(stream.fileno())
        if not _same_file(before, after) or not _same_file(after, path.lstat()):
            raise InventoryError("changed_during_read")
        result["content_sha256"] = digest.hexdigest()
        expected = spec.get("expected_sha256")
        result["expected_sha256_match"] = None if expected is None else expected == digest.hexdigest()
        if expected is not None and expected != digest.hexdigest():
            error = "expected_sha256_mismatch"
        if spec["format"] == "jsonl" or "records_pointer" in spec:
            result.update(observed_record_count=rows, record_count_complete=error is None,
                          field_presence=fields)
        result["status"] = "available" if error is None else "invalid"
        if error:
            result["reason"] = error
    except (InventoryError, OSError) as exc:
        result["status"] = "missing" if isinstance(exc, FileNotFoundError) else "unavailable"
        result["reason"] = str(exc) if isinstance(exc, InventoryError) else type(exc).__name__
    finally:
        if stream is not None:
            stream.close()
    return result


def audit_inventory(spec: dict, *, base_directory: Path, limits: Limits | None = None) -> dict:
    """Hash/count only explicitly declared artifacts; supplied assertions remain inert."""
    limits = limits or Limits()
    if not isinstance(spec, dict) or set(spec) != {"schema", "artifacts"} or spec["schema"] != SPEC_SCHEMA:
        raise InventoryError("invalid inventory specification")
    entries = spec["artifacts"]
    if not isinstance(entries, list) or not 1 <= len(entries) <= limits.max_artifacts:
        raise InventoryError("invalid artifact count")
    ids = set()
    normalized = []
    required = {"artifact_id", "domain_id", "path", "format", "declared_role", "declared_source_kind"}
    for entry in entries:
        if not isinstance(entry, dict) or not required <= set(entry) or set(entry) - required - {"records_pointer", "record_fields", "expected_sha256"}:
            raise InventoryError("invalid artifact fields")
        if not isinstance(entry["artifact_id"], str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", entry["artifact_id"]) or entry["artifact_id"] in ids:
            raise InventoryError("invalid or duplicate artifact ID")
        ids.add(entry["artifact_id"])
        if any(not isinstance(entry[key], str) for key in ("domain_id", "format", "declared_role", "declared_source_kind")) or entry["domain_id"] not in DOMAINS or entry["format"] not in {"json", "jsonl", "opaque"} or entry["declared_role"] not in ROLES or entry["declared_source_kind"] not in SOURCE_KINDS:
            raise InventoryError("invalid artifact declaration")
        if not isinstance(entry["path"], str) or not entry["path"] or len(entry["path"]) > 4096 or "\0" in entry["path"]:
            raise InventoryError("invalid artifact path")
        if "expected_sha256" in entry and (not isinstance(entry["expected_sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", entry["expected_sha256"])):
            raise InventoryError("invalid expected digest")
        if "records_pointer" in entry:
            _pointer_tokens(entry["records_pointer"])
            if entry["format"] != "json":
                raise InventoryError("records_pointer requires JSON")
        if "record_fields" in entry:
            fields = entry["record_fields"]
            if not isinstance(fields, list) or len(fields) > 32 or any(not isinstance(field, str) for field in fields) or len(set(fields)) != len(fields):
                raise InventoryError("invalid record_fields")
            for field in fields:
                _pointer_tokens(field)
            if entry["format"] != "jsonl" and "records_pointer" not in entry:
                raise InventoryError("record_fields requires records")
        path = Path(entry["path"])
        normalized.append((entry, Path(os.path.abspath(path if path.is_absolute() else base_directory / path))))
    results = []
    remaining = limits.max_total_bytes
    for entry, path in normalized:
        result = _artifact(entry, path, limits, remaining)
        remaining -= result["bytes_read"]
        results.append(result)
    domains = {}
    for domain in DOMAINS:
        selected = [row for row in results if row["domain_id"] == domain]
        domains[domain] = {"artifact_count": len(selected), "status_counts": dict(Counter(row["status"] for row in selected)),
                           "declared_source_kind_artifact_counts": dict(Counter(row["declared_source_kind"] for row in selected)),
                           "inventory_scope": "explicit_artifacts_only", "readiness_assessed": False}
    return {"schema": SCHEMA, "limits": asdict(limits), "artifacts": results, "domains": domains,
            "all_declared_artifacts_available": all(row["status"] == "available" for row in results),
            "bytes_read": limits.max_total_bytes - remaining, "eligibility_granted": False,
            "source_semantics_verified": False, "embedding_producer_authenticated": False,
            "native_checks_executed": False, "training_executed": False, "qualified": False, "admitted": False,
            "scope": "File identity and bounded shape observations; declarations and schema names do not establish training eligibility or source truth."}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True, help="Fresh local report; existing files are never replaced")
    for name, default in asdict(Limits()).items():
        parser.add_argument("--" + name.replace("_", "-"), type=int, default=default)
    args = parser.parse_args(argv)
    limits = Limits(**{name: getattr(args, name) for name in asdict(Limits())})
    if args.output.exists() or args.output.is_symlink():
        raise InventoryError("output must be a fresh path")
    stream, before = _open_regular(args.spec)
    with stream:
        if before.st_size > 1024 * 1024:
            raise InventoryError("specification exceeds byte limit")
        raw = stream.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024:
            raise InventoryError("specification exceeds byte limit")
        if not _same_file(before, os.fstat(stream.fileno())) or not _same_file(before, args.spec.lstat()):
            raise InventoryError("specification changed during read")
    report = audit_inventory(_strict_json(raw, Limits()), base_directory=args.spec.absolute().parent, limits=limits)
    report["spec_sha256"] = hashlib.sha256(raw).hexdigest()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    print(json.dumps({key: report[key] for key in ("schema", "domains", "bytes_read", "all_declared_artifacts_available", "eligibility_granted")}))
    return 0 if report["all_declared_artifacts_available"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
