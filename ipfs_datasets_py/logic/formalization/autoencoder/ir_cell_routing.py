"""Read-only, metadata-only routing over explicitly pinned twelve-cell plans.

No owner, encoder, checkpoint runtime or tensor library is imported. Checkpoint
and cached-vector files are hashed, never deserialized. A declaration match is
not task, geometry, training, reconstruction, producer or runtime qualification.
Paths are used exactly as declared: no discovery, alias repair or hash fallback.
Legitimate filesystem aliases are allowed with per-read alias/target/fd fences;
this is not arbitrary same-user ancestor containment or a cross-file snapshot.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat


SCHEMA = "ir-cell-route-resolution/v1"
FAMILIES = ("codebase_ir", "security_ir", "legal_ir", "intent_ir")
DIMENSIONS = (8, 384, 768)
TASKS = ("source_to_native_ir", "structural_reconstruction", "native_ir_to_logic",
         "native_ir_to_source", "retained_source_byte_restoration")
DIMENSION_ROLES = ("input_embedding", "latent")
MAX_MANIFEST_BYTES = 1024 * 1024
MAX_REFERENCE_BYTES = 512 * 1024 * 1024
_HEX = re.compile(r"[0-9a-f]{64}\Z")
_PIN_FIELDS = {"path", "bytes", "sha256"}
_REQUEST_FIELDS = {"ir_family_id", "dimension", "dimension_role", "task_id", "checkpoint_sha256"}


class RoutingError(ValueError):
    """Invalid declarations, incompatible selection or changed/corrupt bytes."""


def _require(condition, message):
    if not condition:
        raise RoutingError(message)


def _pin(value, maximum):
    _require(type(value) is dict and set(value) == _PIN_FIELDS, "closed path/bytes/sha256 pin required")
    path = value["path"]
    _require(type(path) is str and "\x00" not in path and Path(path).is_absolute(),
             "explicit absolute pinned path required")
    try:
        _require(len(path.encode("utf-8")) <= 4096, "pinned path exceeds UTF8 bound")
    except UnicodeError as error:
        raise RoutingError("pinned path must be exact UTF8") from error
    _require(type(value["bytes"]) is int and 0 < value["bytes"] <= maximum,
             "pinned byte count exceeds bound")
    _require(type(value["sha256"]) is str and _HEX.fullmatch(value["sha256"]) is not None,
             "lowercase SHA256 pin required")
    return dict(value)


def _identity(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_size,
            info.st_mtime_ns, info.st_ctime_ns)


def _witness(path):
    alias = os.lstat(path)
    _require(stat.S_ISREG(alias.st_mode) or stat.S_ISLNK(alias.st_mode),
             "pinned path must name a regular file or its alias")
    link = os.readlink(path) if stat.S_ISLNK(alias.st_mode) else None
    target = str(Path(path).resolve(strict=True))
    target_info = os.stat(target, follow_symlinks=False)
    _require(stat.S_ISREG(target_info.st_mode), "pinned target must be a regular file")
    return (_identity(alias), link, target, _identity(target_info))


def _read_pin(pin, *, retain=False, missing_ok=False):
    """Hash one bounded file; only absence can become ordinary unavailable."""
    path = pin["path"]
    fd = None
    try:
        before = _witness(path)
        _require(before[3][3] == pin["bytes"], "pinned file byte count differs")
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC)
        opened = os.fstat(fd)
        _require(stat.S_ISREG(opened.st_mode) and _identity(opened) == before[3],
                 "pinned target changed before opening")
        digest, count, chunks = hashlib.sha256(), 0, []
        while True:
            block = os.read(fd, min(1024 * 1024, pin["bytes"] - count + 1))
            if not block:
                break
            count += len(block)
            _require(count <= pin["bytes"], "pinned file grew while reading")
            digest.update(block)
            if retain:
                chunks.append(block)
        _require(_identity(os.fstat(fd)) == before[3] and _witness(path) == before,
                 "pinned alias or target changed while reading")
        _require(count == pin["bytes"] and digest.hexdigest() == pin["sha256"],
                 "pinned file SHA256 or byte count differs")
        return b"".join(chunks) if retain else True
    except FileNotFoundError as error:
        if missing_ok and fd is None and "before" not in locals():
            return None
        raise RoutingError("pinned file is missing or changed: " + path) from error
    except (OSError, RuntimeError) as error:
        raise RoutingError("cannot stably read pinned regular file: " + path) from error
    finally:
        if fd is not None:
            os.close(fd)


def _pairs(items):
    result = {}
    for key, value in items:
        _require(key not in result, "duplicate JSON key")
        result[key] = value
    return result


def _float(value):
    result = float(value)
    _require(math.isfinite(result), "nonfinite JSON number")
    return result


def _constant(value):
    raise RoutingError("nonfinite JSON constant: " + value)


def _manifest(pin):
    raw = _read_pin(pin, retain=True)
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs,
                           parse_float=_float, parse_constant=_constant)
    except (ValueError, UnicodeError, RecursionError) as error:
        raise RoutingError("invalid bounded manifest JSON") from error
    _require(type(value) is dict, "manifest must be a JSON object")
    pending, count = [(value, 0)], 0
    while pending:
        item, depth = pending.pop()
        count += 1
        _require(depth <= 64 and count <= 100000, "manifest structure exceeds bound")
        if type(item) is dict:
            pending.extend((child, depth + 1) for child in item.values())
        elif type(item) is list:
            pending.extend((child, depth + 1) for child in item)
    return value


def _cell_key(value):
    _require(type(value) is dict and type(value.get("ir_family_id")) is str
             and value["ir_family_id"] in FAMILIES,
             "known IR family required")
    dimension = value.get("dimension")
    _require(type(dimension) is int and dimension in DIMENSIONS, "exact supported cell dimension required")
    family = value["ir_family_id"]
    _require(value.get("cell_id") == f"{family}_{dimension}d", "cell identifier differs from family/dimension")
    return family, dimension


def _records(value, name, maximum):
    result = value.get(name)
    _require(type(result) is list and len(result) <= maximum and all(type(row) is dict for row in result),
             "bounded " + name + " records required")
    return result


def _validate_cell(value, row, maximum):
    family, dimension = _cell_key(value)
    _require(value.get("schema") == "ir-family-dimension-inventory-plan/v1"
             and value.get("status") == "declarative_plan_not_runtime_inventory",
             "declarative cell inventory required")
    _require(value.get("store_id_proposed") == f"ir-cell:{family}:{dimension}d", "cell store declaration differs")
    for flag in ("runtime_databases_created", "remote_repository_created", "model_or_embeddings_modified"):
        _require(value.get(flag) is False, "cell must retain uncreated/unmodified status")
    storage, hub, profile = value.get("storage"), value.get("huggingface"), value.get("dimension_profile")
    _require(type(storage) is dict and storage.get("status") == "planned_not_created"
             and storage == row.get("storage"), "directory/cell storage declarations differ")
    root = f"<ir_store_root>/{family}/{dimension}d"
    _require(storage.get("root_template") == root, "storage root must belong to its exact cell")
    locations = {"inventory_export": "/inventory.json", "registry_database": "/registry.duckdb",
        "index_database": "/index.duckdb", "ducklake_catalog_database": "/lake/catalog.duckdb",
        "ducklake_data_prefix": "/lake/data/", "mutable_artifact_root": "/artifacts/",
        "run_namespace": "/runs/<task>/<profile>/<run_id>/"}
    for name, suffix in locations.items():
        if name in storage:
            _require(storage[name] == root + suffix, "storage location must belong to its exact cell: " + name)
    _require(type(hub) is dict and hub.get("status") == "proposed_not_created"
             and hub.get("repository_id_template") == row.get("huggingface_repository_template")
             and hub.get("suggested_repository_id") == row.get("suggested_huggingface_repository"),
             "directory/cell Hub declarations differ")
    repository = f"{family.replace('_', '-')}-autoencoder-{dimension}d"
    suggestion = hub.get("suggested_repository_id")
    _require(hub.get("repository_id_template") == "<hf_namespace>/" + repository
             and type(suggestion) is str and suggestion.count("/") == 1
             and suggestion.split("/")[0] and suggestion.split("/")[1] == repository,
             "Hub destination must belong to its exact cell")
    _require(type(profile) is dict and type(profile.get("dimension")) is int
             and profile["dimension"] == dimension and profile.get("dimension_role_required") is True,
             "exact dimension-role-aware profile required")
    for name in ("hard_encoder_token_limit", "qualified_source_token_limit"):
        budget = profile.get(name)
        _require(budget is None or type(budget) is int and budget > 0, "invalid declared token budget")
    ceiling, qualified = profile.get("hard_encoder_token_limit"), profile.get("qualified_source_token_limit")
    _require(ceiling is None or qualified is None or qualified <= ceiling, "declared qualified budget exceeds ceiling")
    tasks = value.get("task_profiles_to_inventory")
    _require(type(tasks) is list and tasks and all(type(task) is str and task in TASKS for task in tasks)
             and len(tasks) == len(set(tasks)), "unique known task declarations required")
    checkpoints = _records(value, "existing_checkpoint_evidence", 16)
    seen = set()
    for checkpoint in checkpoints:
        pin = _pin(checkpoint.get("receipt"), maximum)
        _require(pin["sha256"] not in seen, "duplicate checkpoint selection identity")
        seen.add(pin["sha256"])
        role = checkpoint.get("dimension_role")
        _require(role in DIMENSION_ROLES, "checkpoint dimension role required")
        width_name = "input_width" if role == "input_embedding" else "latent_width"
        _require(type(checkpoint.get(width_name)) is int and checkpoint[width_name] == dimension,
                 "checkpoint declared role width differs from cell")
        if "owning_ir_family" in checkpoint:
            _require(checkpoint["owning_ir_family"] == family, "checkpoint owner family differs")
        for name in ("ir_family_id", "domain_id"):
            if name in checkpoint:
                _require(checkpoint[name] == family, "checkpoint family declaration differs")
        if "task_id" in checkpoint:
            _require(checkpoint["task_id"] in tasks, "checkpoint task is outside cell declarations")
    vectors = _records(value, "existing_cached_vector_rows", 32)
    for vector in vectors:
        _pin(vector.get("receipt"), maximum)
        for name in ("ir_family_id", "domain_id", "owning_ir_family"):
            if name in vector:
                _require(vector[name] == family, "cached vector owner family differs")
        if "dimension" in vector:
            _require(type(vector["dimension"]) is int and vector["dimension"] == dimension,
                     "cached vector declared dimension differs")
    descriptor = hub.get("existing_descriptor_source")
    if descriptor is not None:
        _pin(descriptor, maximum)


def _check_reference(pin):
    available = _read_pin(pin, missing_ok=True) is True
    return {"receipt": dict(pin), "status": "verified" if available else "unavailable",
            "reason": None if available else "missing"}


def resolve_ir_cell_route(directory_plan_pin, inventory_pins, request, *, max_reference_bytes=MAX_REFERENCE_BYTES):
    """Resolve one explicit request after authenticating all twelve cell plans.

    Pins are closed ``{path, bytes, sha256}`` dictionaries. The request contains
    exactly ``ir_family_id, dimension, dimension_role, task_id, checkpoint_sha256``.
    A null checkpoint SHA selects nothing. Missing declared reference paths stay
    unavailable; existing corrupt, nonregular or drifting paths raise RoutingError.
    Directory inventory locators are logical cell identifiers. Explicit manifest
    pins may name authenticated archived copies; this grants no currentness over
    historical physical manifest locations. Asset references still use the exact
    paths inside those authenticated copies, with no substitution.
    Unknown authenticated declaration fields are preserved, never used as authority.
    Per-file verification establishes observed bytes, not continuing currentness.
    """
    _require(type(max_reference_bytes) is int and 0 < max_reference_bytes <= MAX_REFERENCE_BYTES,
             "reference byte cap must be within 1..512MiB")
    directory_pin = _pin(directory_plan_pin, MAX_MANIFEST_BYTES)
    _require(type(inventory_pins) in (list, tuple) and len(inventory_pins) == 12,
             "exactly twelve explicitly pinned cell inventories required")
    pins = [_pin(pin, MAX_MANIFEST_BYTES) for pin in inventory_pins]
    _require(len({pin["path"] for pin in pins}) == 12, "duplicate inventory path")
    _require(type(request) is dict and set(request) == _REQUEST_FIELDS, "closed route request required")
    _require(type(request["ir_family_id"]) is str and request["ir_family_id"] in FAMILIES
             and type(request["dimension"]) is int and request["dimension"] in DIMENSIONS
             and type(request["dimension_role"]) is str and request["dimension_role"] in DIMENSION_ROLES
             and type(request["task_id"]) is str and request["task_id"] in TASKS,
             "explicit supported family/dimension/role/task required")
    selection = request["checkpoint_sha256"]
    _require(selection is None or type(selection) is str and _HEX.fullmatch(selection) is not None,
             "explicit checkpoint SHA256 or null required")
    directory = _manifest(directory_pin)
    _require(directory.get("schema") == "ir-family-dimension-inventory-directory-plan/v1"
             and directory.get("status") == "declarative_plan", "declarative directory plan required")
    _require(type(directory.get("ir_family_ids")) is list and len(directory["ir_family_ids"]) == 4
             and all(type(family) is str for family in directory["ir_family_ids"])
             and set(directory["ir_family_ids"]) == set(FAMILIES), "exact four-family directory required")
    dimensions = directory.get("dimensions")
    _require(type(dimensions) is list and len(dimensions) == 3
             and all(type(width) is int for width in dimensions) and set(dimensions) == set(DIMENSIONS)
             and type(directory.get("cell_count")) is int and directory["cell_count"] == 12,
             "exact three-width/twelve-cell directory required")
    _require(directory.get("physical_runtime_stores_created") is False
             and directory.get("remote_repositories_created") is False, "directory is not a runtime store admission")
    rows = _records(directory, "cells", 12)
    _require(len(rows) == 12, "directory must declare twelve cells")
    row_map = {}
    for row in rows:
        key = _cell_key(row)
        _require(key not in row_map and row.get("inventory_manifest") == f"inventories/{key[0]}/{key[1]}d.json",
                 "unique canonical directory inventory declaration required")
        row_map[key] = row
    expected = {(family, width) for family in FAMILIES for width in DIMENSIONS}
    _require(set(row_map) == expected, "directory cell coverage differs")
    cells = {}
    for pin in pins:
        value = _manifest(pin)
        key = _cell_key(value)
        _require(key not in cells and key in row_map, "duplicate or foreign inventory cell")
        _validate_cell(value, row_map[key], max_reference_bytes)
        cells[key] = value, pin
    _require(set(cells) == expected, "inventory cell coverage differs")
    cell, cell_pin = cells[request["ir_family_id"], request["dimension"]]
    _require(request["task_id"] in cell["task_profiles_to_inventory"], "requested task is not declared for cell")
    checkpoint = None
    if selection is not None:
        matches = [row for row in cell["existing_checkpoint_evidence"] if row["receipt"]["sha256"] == selection]
        _require(len(matches) == 1, "explicit checkpoint is not uniquely recorded in requested cell")
        checkpoint = matches[0]
        _require(checkpoint["dimension_role"] == request["dimension_role"], "requested checkpoint dimension role differs")
        if "task_id" in checkpoint:
            _require(checkpoint["task_id"] == request["task_id"], "requested checkpoint task declaration differs")
    vectors = cell["existing_cached_vector_rows"]
    checks = {"checkpoint": None if checkpoint is None else _check_reference(checkpoint["receipt"]),
              "cached_vectors": [_check_reference(row["receipt"]) for row in vectors],
              "descriptor_source": None}
    descriptor = cell["huggingface"].get("existing_descriptor_source")
    if descriptor is not None:
        checks["descriptor_source"] = _check_reference(descriptor)
    vector_verified = bool(vectors) and all(row["status"] == "verified" for row in checks["cached_vectors"])
    checkpoint_verified = checks["checkpoint"] is not None and checks["checkpoint"]["status"] == "verified"
    descriptor_verified = checks["descriptor_source"] is not None and checks["descriptor_source"]["status"] == "verified"
    chosen = checkpoint or {}
    width = request["dimension"]
    profile = cell["dimension_profile"]
    result = {
        "schema": SCHEMA, "request": request, "cell_id": cell["cell_id"],
        "directory_receipt": directory_pin, "inventory_receipt": cell_pin,
        "cell_declaration": cell, "selected_checkpoint": checkpoint, "cached_vector_records": vectors,
        "reference_checks": checks,
        "metadata_authenticity": {"manifest_pins_verified": True,
            "selected_checkpoint_bytes_verified": checkpoint_verified,
            "cached_vector_file_pins_verified": vector_verified,
            "descriptor_source_pin_verified": descriptor_verified},
        "declared_compatibility": {"family_dimension_match": True,
            "dimension_role_match": True if checkpoint is not None else None, "task_listed": True,
            "checkpoint_task_binding": "declared_match" if "task_id" in chosen else "unknown",
            "payload_ir_family": chosen.get("payload_ir_family"), "input_width": chosen.get("input_width"),
            "latent_width": chosen.get("latent_width"), "actual_geometry_verified": False},
        "provenance": {"encoder_tokenizer": "unknown" if width == 8 else "declared_profile_only",
            "embedding_producer_execution_authenticated": False,
            "source_access": chosen.get("source_access", "unknown"),
            "native_source_records_verified": False, "dimension_profile": profile},
        "budget_status": {"hard_encoder_token_limit": profile.get("hard_encoder_token_limit"),
            "qualified_source_token_limit": profile.get("qualified_source_token_limit"),
            "source_token_budget_qualified": False},
        "availability": {"checkpoint_bytes": "unselected" if checks["checkpoint"] is None else checks["checkpoint"]["status"],
            "cached_vector_files": "not_recorded" if not vectors else "verified" if vector_verified else "unavailable",
            "runtime": "not_established", "encoder": "unknown" if width == 8 else "not_established",
            "native_768_source_records": "unavailable" if width == 768 else "not_applicable",
            "store": "planned_not_created", "huggingface": "not_established"},
        "authority": {"model_inference_executed": False, "training_executed": False,
            "proof_authority": False, "runtime_admitted": False, "model_task_qualified": False,
            "quality_qualified": False, "store_available": False, "huggingface_available": False},
    }
    return deepcopy(result)


__all__ = ["resolve_ir_cell_route", "RoutingError", "SCHEMA", "FAMILIES", "DIMENSIONS", "TASKS",
           "DIMENSION_ROLES", "MAX_MANIFEST_BYTES", "MAX_REFERENCE_BYTES"]
