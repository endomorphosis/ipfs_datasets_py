#!/usr/bin/env python3
"""Check caller-pinned release receipts without importing runtime/model packages.

Only declared regular files are read. Root overrides support candidate copies;
original source paths remain provenance for immutable inventory associations.
No Git, network, database, repository scan, model or source execution occurs.
A successful report establishes declared byte consistency, never qualification.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import stat
from typing import Any

SCHEMA = "ir-release-bundle-preflight-manifest/v1"
REPORT_SCHEMA = "ir-release-bundle-preflight-report/v1"
MAX_MANIFEST_BYTES = 2 * 1024 * 1024
MAX_FILE_BYTES = 64 * 1024 * 1024
MAX_TOTAL_BYTES = 256 * 1024 * 1024
MAX_FILES = 512
FAMILIES = {"codebase_ir", "security_ir", "legal_ir", "intent_ir"}
WIDTHS = {8, 384, 768}
CAPABILITIES = {"capture", "conditional_proofs", "intent_grounding", "model_reuse"}
ROLES = {"owner_source", "inherited_asset", "cell_inventory", "inventory_index"}
DIR_FD_READS_SUPPORTED = (os.name == "posix" and hasattr(os, "O_NOFOLLOW")
                         and hasattr(os, "O_DIRECTORY") and os.open in os.supports_dir_fd)


class AuditError(ValueError):
    """An input declaration, trust anchor or bounded read is invalid."""


class _SizeMismatch(AuditError):
    pass


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AuditError(message)


def _closed(value: Any, fields: set[str], label: str) -> None:
    _require(type(value) is dict and set(value) == fields, f"invalid {label} fields")


def _text(value: Any) -> bool:
    return type(value) is str and 0 < len(value) <= 4096 and not any(ord(c) < 32 for c in value)


def _sha(value: Any) -> bool:
    return type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _json(raw: bytes) -> Any:
    def pairs(values):
        result = {}
        for key, value in values:
            _require(key not in result, "duplicate JSON key")
            result[key] = value
        return result

    def nonfinite(_):
        raise AuditError("nonfinite JSON value")

    def finite_float(text):
        value = float(text)
        _require(math.isfinite(value), "nonfinite JSON value")
        return value

    try:
        return json.loads(raw, object_pairs_hook=pairs, parse_constant=nonfinite,
                          parse_float=finite_float)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise AuditError("invalid JSON") from exc


def _witness(value):
    return (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns)


def _read_from_root(root: Path, relative: str, limit: int,
                    expected_bytes: int | None = None) -> bytes:
    """Read through anchored directory FDs; pathname races cannot follow symlinks."""
    _require(DIR_FD_READS_SUPPORTED, "descriptor-relative no-follow reads unavailable")
    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    directory_fd = os.open("/", directory_flags)
    try:
        # Resolve '.'/'..' lexically; never follow root/parent symlinks.
        components = Path(os.path.abspath(root)).parts[1:] + tuple(relative.split("/")[:-1])
        for component in components:
            next_fd = os.open(component, directory_flags, dir_fd=directory_fd)
            os.close(directory_fd)
            directory_fd = next_fd
        leaf = relative.split("/")[-1]
        fd = os.open(leaf, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory_fd)
        with os.fdopen(fd, "rb") as stream:
            before = os.fstat(stream.fileno())
            _require(stat.S_ISREG(before.st_mode), "not a regular file")
            if expected_bytes is not None and before.st_size != expected_bytes:
                raise _SizeMismatch("declared byte count differs from current file")
            _require(before.st_size <= limit, "file exceeds read bound")
            raw = stream.read(limit + 1)
            after = os.fstat(stream.fileno())
            located = os.stat(leaf, dir_fd=directory_fd, follow_symlinks=False)
            _require(_witness(before) == _witness(after) == _witness(located), "file changed during read")
        _require(len(raw) <= limit, "file grew beyond read bound")
        return raw
    finally:
        os.close(directory_fd)


def _read_regular(path: Path, limit: int) -> bytes:
    return _read_from_root(path.parent, path.name, limit)


def _relative(value: Any) -> bool:
    return (_text(value) and not PurePosixPath(value).is_absolute() and "\\" not in value
            and PurePosixPath(value).as_posix() == value
            and all(part not in {"", ".", ".."} for part in value.split("/")))


def _pointer(value: Any, pointer: str) -> Any:
    _require(type(pointer) is str and pointer.startswith("/") and len(pointer) <= 1024,
             "invalid inventory JSON pointer")
    for token in pointer[1:].split("/"):
        _require(re.search(r"~(?![01])", token) is None, "invalid pointer escape")
        token = token.replace("~1", "/").replace("~0", "~")
        if type(value) is dict and token in value:
            value = value[token]
        elif type(value) is list and re.fullmatch(r"0|[1-9][0-9]*", token) and int(token) < len(value):
            value = value[int(token)]
        else:
            raise AuditError("inventory pointer is unavailable")
    return value


def _validate(manifest: Any) -> None:
    _closed(manifest, {"schema", "roots", "files", "cells", "asset_links",
                       "inventory_index_file_id", "closure_complete"}, "manifest")
    _require(manifest["schema"] == SCHEMA and manifest["closure_complete"] is False,
             "unsupported schema or qualification claim")
    roots = manifest["roots"]
    _require(type(roots) is dict and 0 < len(roots) <= 16
             and all(_text(k) and _text(v) and Path(v).is_absolute() for k, v in roots.items()), "invalid roots")
    files = manifest["files"]
    _require(type(files) is list and 0 < len(files) <= MAX_FILES, "invalid file population")
    ids, locators, source_paths = set(), set(), set()
    for item in files:
        _closed(item, {"file_id", "root_id", "relative_path", "bytes", "sha256",
                       "roles", "capabilities", "source_path"}, "file")
        _require(_text(item["file_id"]) and item["file_id"] not in ids, "duplicate/invalid file ID")
        _require(_text(item["root_id"]) and item["root_id"] in roots
                 and _relative(item["relative_path"]), "invalid file locator")
        _require(type(item["bytes"]) is int and 0 <= item["bytes"] <= MAX_FILE_BYTES
                 and _sha(item["sha256"]), "invalid file receipt")
        _require(_text(item["source_path"]) and Path(item["source_path"]).is_absolute(), "invalid original source path")
        for field, allowed in (("roles", ROLES), ("capabilities", CAPABILITIES)):
            values = item[field]
            _require(type(values) is list and values and all(type(x) is str and x in allowed for x in values)
                     and len(values) == len(set(values)), f"invalid {field}")
        locator = (item["root_id"], item["relative_path"])
        _require(locator not in locators and item["source_path"] not in source_paths, "duplicate file locator/provenance")
        ids.add(item["file_id"]); locators.add(locator); source_paths.add(item["source_path"])
    _require(sum(x["bytes"] + 1 for x in files) <= MAX_TOTAL_BYTES, "total byte bound exceeded")
    cells = manifest["cells"]
    _require(type(cells) is list and len(cells) <= 12, "invalid cell population")
    cell_ids = set()
    for cell in cells:
        _closed(cell, {"cell_id", "ir_family_id", "dimension", "inventory_file_id"}, "cell")
        _require(type(cell["ir_family_id"]) is str and cell["ir_family_id"] in FAMILIES
                 and type(cell["dimension"]) is int and cell["dimension"] in WIDTHS, "invalid family/dimension")
        expected = f"{cell['ir_family_id']}_{cell['dimension']}d"
        _require(cell["cell_id"] == expected and expected not in cell_ids
                 and _text(cell["inventory_file_id"]) and cell["inventory_file_id"] in ids,
                 "duplicate/invalid cell binding")
        cell_ids.add(expected)
    index = manifest["inventory_index_file_id"]
    _require(index is None or (type(index) is str and index in ids), "invalid inventory index")
    if index is not None:
        _require(cell_ids == {f"{family}_{width}d" for family in FAMILIES for width in WIDTHS}, "incomplete twelve-cell matrix")
    links = manifest["asset_links"]
    _require(type(links) is list and len(links) <= MAX_FILES, "invalid asset links")
    seen_links = set()
    for link in links:
        _closed(link, {"cell_id", "inventory_pointer", "asset_file_id"}, "asset link")
        _require(_text(link["cell_id"]) and link["cell_id"] in cell_ids
                 and _text(link["asset_file_id"]) and link["asset_file_id"] in ids
                 and _text(link["inventory_pointer"]), "invalid asset association")
        key = (link["cell_id"], link["inventory_pointer"])
        _require(key not in seen_links, "duplicate asset association")
        seen_links.add(key)


def audit_file(manifest_path: str | Path, expected_sha256: str,
               root_overrides: dict[str, str] | None = None) -> dict[str, Any]:
    """Audit exactly declared bytes using a caller-trusted manifest SHA256."""
    _require(_sha(expected_sha256), "a trusted manifest SHA256 is required")
    raw = _read_regular(Path(manifest_path), MAX_MANIFEST_BYTES)
    _require(hashlib.sha256(raw).hexdigest() == expected_sha256, "manifest trust anchor mismatch")
    manifest = _json(raw)
    _validate(manifest)
    roots = dict(manifest["roots"])
    if root_overrides is not None:
        _require(type(root_overrides) is dict and set(root_overrides) <= roots.keys()
                 and all(_text(v) and Path(v).is_absolute() for v in root_overrides.values()), "invalid root overrides")
        roots.update(root_overrides)
    by_id = {x["file_id"]: x for x in manifest["files"]}
    rows, parsed = [], {}
    for item in manifest["files"]:
        row = {"file_id": item["file_id"], "status": "unavailable", "bytes_read": 0,
               "content_sha256": None, "diagnostic": None}
        try:
            data = _read_from_root(Path(roots[item["root_id"]]), item["relative_path"],
                                   item["bytes"], expected_bytes=item["bytes"])
            row["bytes_read"] = len(data)
            row["content_sha256"] = hashlib.sha256(data).hexdigest()
            row["status"] = "matched" if len(data) == item["bytes"] and row["content_sha256"] == item["sha256"] else "pin_mismatch"
            if row["status"] == "matched" and set(item["roles"]) & {"cell_inventory", "inventory_index"}:
                parsed[item["file_id"]] = _json(data)
        except FileNotFoundError:
            row["diagnostic"] = "declared file is unavailable"
        except _SizeMismatch as exc:
            row["status"] = "pin_mismatch"; row["diagnostic"] = str(exc)
        except (OSError, AuditError) as exc:
            row["status"] = "read_rejected"; row["diagnostic"] = str(exc)
        rows.append(row)
    cells = []
    for cell in manifest["cells"]:
        inventory = parsed.get(cell["inventory_file_id"])
        status = "unavailable" if inventory is None else "inventory_rejected"
        if (type(inventory) is dict and inventory.get("schema") == "ir-family-dimension-inventory-plan/v1"
                and all(inventory.get(k) == cell[k] for k in ("cell_id", "ir_family_id", "dimension"))
                and type(inventory.get("dimension")) is int):
            status = "inventory_matched"
        cells.append({"cell_id": cell["cell_id"], "status": status})
    links = []
    for link in manifest["asset_links"]:
        inventory_id = next(x["inventory_file_id"] for x in manifest["cells"] if x["cell_id"] == link["cell_id"])
        status = "association_rejected"
        try:
            record = _pointer(parsed[inventory_id], link["inventory_pointer"])
            item = by_id[link["asset_file_id"]]
            if (type(record) is dict and type(record.get("bytes")) is int
                    and "inherited_asset" in item["roles"]
                    and record == {"path": item["source_path"], "bytes": item["bytes"], "sha256": item["sha256"]}):
                status = "association_matched"
        except (AuditError, KeyError):
            pass
        links.append({**link, "status": status})
    expected_links = set()
    associations_complete = True
    for cell in manifest["cells"]:
        inventory = parsed.get(cell["inventory_file_id"])
        if type(inventory) is not dict:
            associations_complete = False
            continue
        for field in ("existing_checkpoint_evidence", "existing_cached_vector_rows"):
            records = inventory.get(field, [])
            if type(records) is not list:
                associations_complete = False
                continue
            for number, record in enumerate(records):
                if type(record) is not dict or "receipt" not in record:
                    associations_complete = False
                else:
                    expected_links.add((cell["cell_id"], f"/{field}/{number}/receipt"))
        hub = inventory.get("huggingface", {})
        if type(hub) is not dict:
            associations_complete = False
        elif hub.get("existing_descriptor_source") is not None:
            expected_links.add((cell["cell_id"], "/huggingface/existing_descriptor_source"))
    associations_complete &= expected_links == {(x["cell_id"], x["inventory_pointer"]) for x in links}
    index_status = "not_declared"
    index_id = manifest["inventory_index_file_id"]
    if index_id is not None:
        index = parsed.get(index_id)
        index_status = "inventory_index_rejected"
        if (type(index) is dict and index.get("schema") == "ir-family-dimension-inventory-directory-plan/v1"
                and type(index.get("cells")) is list and len(index["cells"]) == 12):
            actual = {x.get("cell_id"): x for x in index["cells"]
                      if type(x) is dict and type(x.get("cell_id")) is str}
            if len(actual) == 12 and set(actual) == {x["cell_id"] for x in manifest["cells"]}:
                valid = True
                for cell in manifest["cells"]:
                    entry = actual[cell["cell_id"]]
                    valid &= (type(entry.get("dimension")) is int
                              and all(entry.get(k) == cell[k] for k in ("ir_family_id", "dimension")))
                    relative = entry.get("inventory_manifest")
                    valid &= _relative(relative)
                    if _relative(relative):
                        original = str(Path(by_id[index_id]["source_path"]).parent / relative)
                        valid &= original == by_id[cell["inventory_file_id"]]["source_path"]
                if valid:
                    index_status = "inventory_index_matched"
    passed = (all(x["status"] == "matched" for x in rows)
              and all(x["status"] == "inventory_matched" for x in cells)
              and all(x["status"] == "association_matched" for x in links)
              and associations_complete
              and index_status in {"not_declared", "inventory_index_matched"})
    capability_receipts = {}
    for capability in sorted(CAPABILITIES):
        selected = {x["file_id"] for x in manifest["files"] if capability in x["capabilities"]}
        capability_receipts[capability] = {"declared_files": len(selected),
            "matched_files": sum(x["file_id"] in selected and x["status"] == "matched" for x in rows),
            "complete_dependency_closure_qualified": False, "runtime_ready": False}
    return {"schema": REPORT_SCHEMA, "manifest_sha256": expected_sha256,
            "manifest_anchor_matched": True,
            "status": "declared_receipts_match" if passed else "receipt_failures",
            "items": rows, "cells": cells, "asset_links": links,
            "inventory_associations_complete": associations_complete,
            "inventory_index_status": index_status, "capability_receipts": capability_receipts,
            "runtime_readiness_qualified": False, "model_task_qualification": False,
            "proof_authority": False, "effects_authorized": False,
            "training_admitted": False, "promotion_admitted": False,
            "package_origins_executed_or_verified": False,
            "repository_scan": False, "database_operations": False,
            "model_execution": False, "network_access": False}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--root-overrides", type=Path,
                        help="JSON object mapping declared root IDs to absolute candidate roots")
    args = parser.parse_args(argv)
    try:
        overrides = _json(_read_regular(args.root_overrides, MAX_MANIFEST_BYTES)) if args.root_overrides else None
        report = audit_file(args.manifest, args.expected_sha256, overrides)
    except (AuditError, OSError) as exc:
        print(json.dumps({"schema": REPORT_SCHEMA, "status": "input_rejected", "diagnostic": str(exc),
                          "runtime_readiness_qualified": False, "model_task_qualification": False,
                          "training_admitted": False, "promotion_admitted": False,
                          "proof_authority": False, "effects_authorized": False}))
        return 1
    print(json.dumps(report, indent=2))
    return 0 if report["status"] == "declared_receipts_match" else 2


if __name__ == "__main__":
    raise SystemExit(main())
