"""Single-owner registration of separately trained native formula checkpoints."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat

from . import native_formula_training as learning

SCHEMA = "registered-native-formula-candidate/v1"
MAX_BYTES = 72 * 1024 * 1024
FALSE = {"admitted": False, "qualified": False, "formalized": False,
         "promotion_performed": False, "lake_executed": False}


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _raw(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      allow_nan=False).encode()


def _hash(value):
    return hashlib.sha256(_raw(value)).hexdigest()


def _json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            _require(key not in result, "duplicate candidate JSON key")
            result[key] = value
        return result
    def reject(value):
        raise ValueError("nonfinite candidate JSON")
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=reject)


def _validate(result):
    learning.validate_training_result(result)
    _require(result["report"]["training_executed"] is True,
             "candidate has no completed optimizer step in this training call")
    return result["checkpoint"]


def _manifest(checkpoint):
    return learning.checkpoint_binding(checkpoint)


def _metadata(result):
    return {"schema": SCHEMA, "checkpoint_sha256": learning.checkpoint_digest(result["checkpoint"]),
            "report_sha256": _hash(result["report"]), "purpose": "native_categorical_formula_reconstruction", **FALSE}


def _read_row(registry, row):
    from ...duckdb_control.autoencoder_registry import SCHEMA as REGISTRY_SCHEMA, content_identity
    expected = content_identity({"schema": REGISTRY_SCHEMA, **{key: row[key] for key in
        ("variant_id", "artifact", "metadata", "parent_version_id")}})
    _require(row["version_id"] == expected, "registry version content identity differs")
    _require(type(row["artifact"].get("bytes")) is int and 0 < row["artifact"]["bytes"] <= MAX_BYTES,
             "native formula candidate exceeds byte bound")
    artifact = registry.verify_artifact(row["artifact"])
    path = registry.artifact_path(artifact)
    with path.open("rb") as stream:
        before = os.fstat(stream.fileno())
        _require(stat.S_ISREG(before.st_mode), "regular candidate artifact required")
        raw = stream.read(MAX_BYTES + 1)
        after = os.fstat(stream.fileno())
    _require(len(raw) == artifact["bytes"] and hashlib.sha256(raw).hexdigest() == artifact["sha256"]
             and (before.st_size, before.st_mtime_ns, before.st_ctime_ns) ==
                 (after.st_size, after.st_mtime_ns, after.st_ctime_ns), "candidate changed while reading")
    saved = _json(raw)
    _require(type(saved) is dict and set(saved) == {"schema", "checkpoint", "report"}
             and saved["schema"] == SCHEMA, "unsupported native formula candidate envelope")
    result = {"checkpoint": saved["checkpoint"], "report": saved["report"]}
    checkpoint = _validate(result)
    manifest = _manifest(checkpoint)
    _require(row["variant_id"] == "native-formula-" + _hash(manifest), "candidate belongs to another variant")
    _require(registry.get_variant(row["variant_id"])["manifest"] == manifest,
             "formula candidate manifest differs")
    _require(row["metadata"] == _metadata(result), "formula candidate metadata differs")
    return result


def _parent(registry, parent_version_id, variant_id, checkpoint):
    expected = checkpoint["parent_checkpoint_sha256"]
    if parent_version_id is None:
        _require(expected is None, "resumed formula candidate needs its exact registry parent")
        return
    row = registry.get_version(parent_version_id)
    _require(row["variant_id"] == variant_id, "formula parent belongs to another variant")
    parent = _read_row(registry, row)["checkpoint"]
    _require(learning.checkpoint_digest(parent) == expected, "formula numerical parent differs")
    _require(checkpoint["latest"]["progress"]["optimizer_steps"] > parent["latest"]["progress"]["optimizer_steps"],
             "formula candidate optimizer progress went backwards")


def register_candidate(registry, result, directory, *, parent_version_id=None):
    """Record an immutable candidate; registration never promotes its authority."""
    result = _json(_raw(result))
    checkpoint = _validate(result)
    manifest = _manifest(checkpoint)
    variant_id = "native-formula-" + _hash(manifest)
    _parent(registry, parent_version_id, variant_id, checkpoint)
    raw = _raw({"schema": SCHEMA, **result})
    _require(len(raw) <= MAX_BYTES, "native formula candidate exceeds byte bound")
    directory = Path(directory).absolute()
    _require(not directory.exists() and directory.parent.resolve(strict=True) == directory.parent,
             "fresh candidate directory under a canonical parent required")
    directory.mkdir()
    path = directory / "candidate.json"
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    artifact = registry.stage_artifact(path, expected_sha256=hashlib.sha256(raw).hexdigest())
    # Recheck producer identity before recording a row that can be resumed.
    _validate(result)
    registry.register_variant("formula-variant-" + _hash(manifest), variant_id, manifest)
    metadata = _metadata(result)
    operation = "formula-version-" + _hash({"artifact": artifact, "metadata": metadata,
                                            "parent_version_id": parent_version_id})
    registered = registry.register_version(operation, variant_id, artifact, metadata=metadata,
                                          parent_version_id=parent_version_id)
    return {**registered, "variant_id": variant_id, "artifact": artifact,
            "checkpoint_sha256": metadata["checkpoint_sha256"], **FALSE}


def load_registered_candidate(registry, version_id):
    row = registry.get_version(version_id)
    result = _read_row(registry, row)
    _parent(registry, row["parent_version_id"], row["variant_id"], result["checkpoint"])
    return result
