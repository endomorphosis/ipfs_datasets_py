"""Bounded, read-only asset observations for an autoformalization alignment study.

This inventories explicit existing lineage/migration configurations. It never
imports their backends, loads a model, reads a dataset, executes a receipt,
downloads assets, or writes weights. Small JSON checkpoint bytes may be inspected;
large checkpoints and all binary tensor assets are stat-only. Expected digests
are declarations until matching bytes have actually been read. Metadata and
path presence confer neither numerical readiness nor semantic qualification.
"""
from __future__ import annotations

import ast
import hashlib
import json
import math
import os
import re
import stat
from pathlib import Path

SCHEMA = "autoformalization-alignment-asset-inventory/v1"
DEFAULT_MAX_METADATA_BYTES = 2 * 1024 * 1024
MAX_METADATA_BYTES = 8 * 1024 * 1024
MAX_REFERENCES = 256
LANE_DIMENSIONS = {"legacy_8d": 8, "source_384d": 384, "multilingual_768d": 768}
_CONFIGS = {
    "legal_autoencoder_lineages.json": "legal-autoencoder-lineages/v1",
    "gte_parallel_lineages_v1.json": "gte-parallel-lineage-plan/v1",
    "gte_migration_preparation_v1.json": "gte-migration-preparation-config/v1",
    "gte_decoder_transfer_preparation_v1.json": "gte-decoder-transfer-preparation-config/v1",
    "gte_decoder_native_preparation_v1.json": "gte-decoder-native-preparation-config/v1",
    "gte_decoder_source_evaluation_v1.json": "gte-decoder-source-evaluation-config/v1",
    "gte_multilingual_local_assets_v1.json": "gte-multilingual-local-assets/v1",
}
_SOURCES = {
    "legacy_8d": (
        "ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_lineages/legacy_v1/__init__.py",
        "ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_lineages/legacy_v1/linguistic.py",
    ),
    "source_384d": (
        "ipfs_datasets_py/logic/formalization/autoencoder/source_embeddings_384.py",
        "ipfs_datasets_py/logic/formalization/autoencoder/source_training_v2.py",
        "ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_embedding_runtime.py",
    ),
    "multilingual_768d": (
        "ipfs_datasets_py/logic/formalization/autoencoder/gte_multilingual_profile.py",
        "ipfs_datasets_py/logic/formalization/autoencoder/source_embeddings_768.py",
        "ipfs_datasets_py/logic/formalization/autoencoder/gte_decoder_warm_start.py",
        "ipfs_datasets_py/logic/formalization/autoencoder/gte_decoder_reuse.py",
    ),
}
_BINARY_SUFFIXES = {".safetensors", ".gguf", ".bin", ".pt", ".pth", ".pkl", ".pickle", ".ckpt"}
_SHA = re.compile(r"[0-9a-f]{64}\Z")


def _root(value):
    if not isinstance(value, (str, os.PathLike)):
        raise ValueError("root must be a local path")
    path = Path(value)
    if ".." in path.parts:
        raise ValueError("root traversal is forbidden")
    return Path(os.path.abspath(path))


def _path(value, base):
    if (type(value) is not str or not value or len(value) > 4096
            or "\\" in value or "\x00" in value or "<" in value or ">" in value):
        raise ValueError("invalid_path")
    path = Path(value)
    if ".." in path.parts or value.startswith("~"):
        raise ValueError("path_traversal")
    return path if path.is_absolute() else base / path


def _identity(info):
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def _open_regular(path):
    """Reject symlinks in every component and avoid FIFO blocking at open."""
    parent = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in path.parts[1:-1]:
            next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
            os.close(parent)
            parent = next_fd
        descriptor = os.open(path.name, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW, dir_fd=parent)
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            os.close(descriptor)
            raise ValueError("not_regular_file")
        return descriptor
    finally:
        os.close(parent)


def _parse(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate_json_key")
            result[key] = value
        return result

    def invalid(_value):
        raise ValueError("nonfinite_json")

    def finite(value):
        number = float(value)
        if not math.isfinite(number):
            raise ValueError("nonfinite_json")
        return number

    value = json.loads(raw, object_pairs_hook=unique, parse_constant=invalid, parse_float=finite)
    if type(value) is not dict:
        raise ValueError("json_object_required")
    return value


def _metadata(value):
    """Bounded declarations only; no tensors, source rows, or copied text."""
    result = {key: value[key] for key in (
        "schema", "architecture", "architecture_version", "domain", "domain_id",
        "dimension", "runtime", "runtime_id", "representation_id", "weights_sha256",
        "model_revision", "code_revision", "qualified", "teacher_qualified",
        "model_inference_executed", "training_executed", "proof_authority",
    ) if key in value and type(value[key]) in (str, int, float, bool, type(None))}
    for key in ("binding", "config", "embedding_contract"):
        part = value.get(key)
        if type(part) is dict:
            result[key] = {name: part[name] for name in (
                "domain", "lineage_id", "dimension", "runtime_profile", "core_sha256",
                "hidden_size", "projection_width", "token_embedding_dim", "max_target_tokens",
                "model_id", "revision", "pooling", "normalization",
            ) if name in part and type(part[name]) in (str, int, float, bool, type(None))}
    return result


def _observe(path, *, kind, maximum, expected_sha256=None, expected_bytes=None):
    record = {"path": str(path), "kind": kind, "path_exists": None, "bytes": None,
              "expected_sha256": expected_sha256, "observed_sha256": None,
              "expected_sha256_match": None, "expected_bytes": expected_bytes,
              "expected_bytes_match": None, "metadata_inspected": False,
              "content_read": False, "status": "unavailable", "reasons": []}
    if expected_sha256 is not None and (type(expected_sha256) is not str or not _SHA.fullmatch(expected_sha256)):
        record["reasons"] = ["invalid_expected_sha256"]
        return record, None
    if expected_bytes is not None and (type(expected_bytes) is not int or expected_bytes < 0):
        record["reasons"] = ["invalid_expected_bytes"]
        return record, None
    try:
        descriptor = _open_regular(path)
    except FileNotFoundError:
        record.update(path_exists=False, status="missing", reasons=["missing_file"])
        return record, None
    except (OSError, ValueError):
        record["reasons"] = ["symlink_or_nonregular_path"]
        return record, None
    try:
        before = os.fstat(descriptor)
        record.update(path_exists=True, bytes=before.st_size)
        if expected_bytes is not None:
            record["expected_bytes_match"] = before.st_size == expected_bytes
            if not record["expected_bytes_match"]:
                record["reasons"].append("expected_bytes_mismatch")
        if kind == "dataset" or path.suffix.lower() in _BINARY_SUFFIXES:
            record.update(status="presence_only")
            record["reasons"].append("content_inspection_excluded")
            return record, None
        if before.st_size > maximum:
            record.update(status="presence_only")
            record["reasons"].append("metadata_size_limit")
            return record, None
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            raw = stream.read(maximum + 1)
        after = os.fstat(descriptor)
        if len(raw) != before.st_size or len(raw) > maximum or _identity(before) != _identity(after):
            record.update(status="invalid", reasons=["file_changed_during_read"])
            return record, None
        # Reopen under the same no-symlink policy to bind the path after reading.
        check = _open_regular(path)
        try:
            if _identity(os.fstat(check)) != _identity(before):
                record.update(status="invalid", reasons=["file_changed_during_read"])
                return record, None
        finally:
            os.close(check)
        record.update(content_read=True, observed_sha256=hashlib.sha256(raw).hexdigest())
        if expected_sha256 is not None:
            record["expected_sha256_match"] = record["observed_sha256"] == expected_sha256
            if not record["expected_sha256_match"]:
                record["reasons"].append("expected_sha256_mismatch")
        parsed = None
        if kind != "source" and path.suffix.lower() == ".json":
            try:
                parsed = _parse(raw)
            except (ValueError, UnicodeError, RecursionError):
                record.update(status="invalid")
                record["reasons"].append("malformed_metadata_json")
                return record, None
            record["declared_metadata"] = _metadata(parsed)
        record.update(metadata_inspected=True, status="metadata_inspected")
        if record["reasons"]:
            record["status"] = "invalid"
            parsed = None
        return record, parsed
    except (OSError, ValueError):
        record.update(status="invalid")
        record["reasons"].append("file_changed_or_unreadable")
        return record, None
    finally:
        os.close(descriptor)


def _references(value, trail=(), depth=0):
    if depth > 16:
        raise ValueError("reference_depth_limit")
    if type(value) is dict:
        if type(value.get("path")) is str and "sha256" in value:
            yield trail, value
        else:
            for key in sorted(value):
                yield from _references(value[key], (*trail, key), depth + 1)
    elif type(value) is list:
        for index, item in enumerate(value):
            yield from _references(item, (*trail, str(index)), depth + 1)


def _reference_kind(trail, path):
    names = "/".join(trail).lower()
    if any(term in names for term in ("archive", "dataset", "rows", "inputs", "receipts", "batch")):
        return "dataset"
    if "source_files" in names or path.suffix == ".py":
        return "source"
    if any(term in names for term in ("checkpoint", "initialization")):
        return "checkpoint"
    return "manifest"


def _literal_constants(path, maximum):
    """Read profile constants through AST literals, without executing code."""
    record, _ = _observe(path, kind="source", maximum=maximum)
    if not record["metadata_inspected"] or record["status"] != "metadata_inspected":
        return {}, record
    # The first observation's bytes are rechecked after AST parsing below.
    try:
        descriptor = _open_regular(path)
        try:
            with os.fdopen(descriptor, "rb", closefd=False) as stream:
                raw = stream.read(maximum + 1)
        finally:
            os.close(descriptor)
    except (OSError, ValueError):
        record.update(status="invalid", reasons=["file_changed_or_unreadable"])
        return {}, record
    if len(raw) > maximum or hashlib.sha256(raw).hexdigest() != record["observed_sha256"]:
        record.update(status="invalid", reasons=["file_changed_during_read"])
        return {}, record
    result = {}
    try:
        for node in ast.parse(raw).body:
            if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                try:
                    result[node.targets[0].id] = ast.literal_eval(node.value)
                except (ValueError, TypeError, RecursionError):
                    pass
    except (SyntaxError, UnicodeError, RecursionError):
        record.update(status="invalid", reasons=["malformed_profile_source"])
        return {}, record
    return result, record


def describe_alignment_assets(repository_root: Path | str, workspace_root: Path | str | None = None,
                              *, max_metadata_bytes=DEFAULT_MAX_METADATA_BYTES) -> dict:
    """Return stable JSON-compatible observations; never infer readiness from width.

    Explicit workspace_root overrides config roots. Otherwise only the existing
    parallel-lineage plan's workspace_root is used; absent that, the repository
    root is the relative-path base. Config-supplied absolute paths remain explicit
    observations. No directories are created and no artifact trees are scanned.
    """
    if type(max_metadata_bytes) is not int or not 1 <= max_metadata_bytes <= MAX_METADATA_BYTES:
        raise ValueError("max_metadata_bytes must be an integer from 1 through 8388608")
    repository = _root(repository_root)
    configurations, documents = [], {}
    for name, schema in _CONFIGS.items():
        observation, value = _observe(repository / "configs/autoencoders" / name,
                                      kind="configuration", maximum=max_metadata_bytes)
        observation["config_id"] = name
        if value is not None and value.get("schema") != schema:
            observation.update(status="invalid")
            observation["reasons"].append("unexpected_config_schema")
            value = None
        configurations.append(observation)
        documents[name] = value
    plan = documents["gte_parallel_lineages_v1.json"]
    issues, artifacts = [], []
    catalog = documents["legal_autoencoder_lineages.json"]
    lineages = []
    catalog_rows = catalog.get("lineages") if catalog else None
    if catalog is not None and type(catalog_rows) is not dict:
        issues.append({"config_id": "legal_autoencoder_lineages.json", "field": "lineages",
                       "reason": "invalid_lineage_catalog"})
    if type(catalog_rows) is dict:
        for lineage_id, dimension in (("legacy_hub_v1", 8), ("current_legal_v2", 384)):
            entry = catalog_rows.get(lineage_id)
            if type(entry) is not dict or type(entry.get("runtime_dimension")) is not int or entry["runtime_dimension"] != dimension:
                issues.append({"config_id": "legal_autoencoder_lineages.json", "field": lineage_id,
                               "reason": "lineage_dimension_or_identity_missing"})
                continue
            policy = entry.get("checkpoint_policy")
            lineages.append({"lineage_id": lineage_id, "dimension": dimension,
                "runtime_namespace": entry.get("runtime_namespace"), "role": entry.get("role"),
                "declared_checkpoint_policy": policy if type(policy) is dict else None,
                "declared_representation": entry.get("representation"),
                "catalog_entry_is_selected_checkpoint": False, "numerically_evaluated": False,
                "qualified": False})
    configured_workspace = plan.get("workspace_root") if plan else None
    if workspace_root is not None:
        workspace = _root(workspace_root)
    else:
        try:
            workspace = _root(configured_workspace) if configured_workspace is not None else repository
        except ValueError:
            workspace = repository
            issues.append({"config_id": "gte_parallel_lineages_v1.json", "field": "workspace_root",
                           "reason": "invalid_configured_workspace_root"})
    for name, value in documents.items():
        if value is None or name == "legal_autoencoder_lineages.json" or name == "gte_multilingual_local_assets_v1.json":
            continue
        try:
            for index, (trail, reference) in enumerate(_references(value)):
                if index >= MAX_REFERENCES:
                    raise ValueError("reference_count_limit")
                try:
                    path = _path(reference["path"], workspace)
                except ValueError as error:
                    issues.append({"config_id": name, "field": "/".join(trail), "reason": str(error)})
                    continue
                record, _ = _observe(path, kind=_reference_kind(trail, path), maximum=max_metadata_bytes,
                                     expected_sha256=reference["sha256"], expected_bytes=reference.get("bytes"))
                record.update(config_id=name, field="/".join(trail))
                artifacts.append(record)
        except ValueError as error:
            issues.append({"config_id": name, "field": "references", "reason": str(error)})

    configured_lanes = {}
    if plan is not None:
        rows = plan.get("lanes")
        if type(rows) is not list or len(rows) > len(LANE_DIMENSIONS):
            issues.append({"config_id": "gte_parallel_lineages_v1.json", "field": "lanes", "reason": "invalid_lane_list"})
        else:
            for row in rows:
                lane_id = row.get("lane_id") if type(row) is dict else None
                if lane_id not in LANE_DIMENSIONS or lane_id in configured_lanes:
                    issues.append({"config_id": "gte_parallel_lineages_v1.json", "field": "lanes", "reason": "unknown_or_duplicate_lane"})
                    continue
                if type(row.get("dimension")) is not int or row["dimension"] != LANE_DIMENSIONS[lane_id]:
                    issues.append({"config_id": "gte_parallel_lineages_v1.json", "field": lane_id, "reason": "lane_dimension_mismatch"})
                    continue
                configured_lanes[lane_id] = row

    lanes = []
    for lane_id, dimension in LANE_DIMENSIONS.items():
        row = configured_lanes.get(lane_id)
        sources = [_observe(repository / name, kind="source", maximum=max_metadata_bytes)[0]
                   for name in _SOURCES[lane_id]]
        checkpoint = None
        if row and type(row.get("checkpoint")) is dict:
            reference = row["checkpoint"]
            try:
                path = _path(reference.get("path"), workspace)
                checkpoint, _ = _observe(path, kind="checkpoint", maximum=max_metadata_bytes,
                                          expected_sha256=reference.get("sha256"), expected_bytes=reference.get("bytes"))
            except ValueError as error:
                checkpoint = {"status": "invalid", "path_exists": None, "metadata_inspected": False,
                              "reasons": [str(error)]}
        availability = ("unconfigured" if row is None else "checkpoint_unconfigured" if checkpoint is None
                        else checkpoint["status"])
        lanes.append({"lane_id": lane_id, "dimension": dimension, "configured": row is not None,
                      "runtime_id": row.get("runtime_id") if row else None,
                      "representation_id": row.get("representation_id") if row else None,
                      "declared_availability": row.get("availability") if row else None,
                      "backend_declaration": row.get("backend") if row else None,
                      "checkpoint": checkpoint, "sources": sources,
                      "path_exists": checkpoint.get("path_exists") if checkpoint else None,
                      "metadata_inspected": bool(checkpoint and checkpoint["metadata_inspected"]),
                      "inventory_status": availability, "readiness_scope": "metadata_and_path_observations_only",
                      "numerically_evaluated": False, "qualified": False,
                      "alignment_training_readiness": "not_evaluated"})

    # Profile constants are observed source declarations, not an import or an
    # endorsement of externally provided code. No default cache directory is
    # inferred: callers must bind encoder locations explicitly in the lane plan.
    encoders = []
    for lane_id in ("source_384d", "multilingual_768d"):
        row = configured_lanes.get(lane_id, {})
        producer = row.get("producer") if type(row.get("producer")) is dict else {}
        assets = []
        if lane_id == "source_384d":
            constants, profile = _literal_constants(repository / _SOURCES[lane_id][2], max_metadata_bytes)
            declarations = {"model_id": "thenlper/gte-small", "revision": constants.get("PINNED_REVISION")
                            if type(constants.get("PINNED_REVISION")) is str else None,
                            "dimension": 384, "max_tokens": constants.get("MAX_TOKENS")
                            if type(constants.get("MAX_TOKENS")) is int else None,
                            "pooling": "mean", "normalization": "l2"}
            entries = constants.get("_PINNED_ASSETS", {})
            entries = [{"path": key, "bytes": value[0], "sha256": value[1], "relative_to": "model"}
                       for key, value in entries.items() if type(key) is str and type(value) is tuple
                       and len(value) == 2 and type(value[0]) is int and type(value[1]) is str
                       ] if type(entries) is dict else []
            asset_manifest = None
        else:
            constants, profile = _literal_constants(repository / _SOURCES[lane_id][0], max_metadata_bytes)
            declarations = {key: constants.get(name) if type(constants.get(name)) is str else None
                            for key, name in (("model_id", "MODEL_REPO"), ("revision", "MODEL_REV"),
                                              ("code_repository", "CODE_REPO"), ("code_revision", "CODE_REV"))}
            profile_values = constants.get("PROFILE", {})
            if type(profile_values) is dict:
                declarations.update({key: profile_values[key] for key in (
                    "dimension", "max_tokens", "pooling", "normalization", "device", "dtype",
                    "attention_implementation", "overlength_policy",
                ) if key in profile_values and type(profile_values[key]) in (str, int, float, bool, type(None))
                    and (type(profile_values[key]) is not float or math.isfinite(profile_values[key]))})
            manifest = documents["gte_multilingual_local_assets_v1.json"]
            asset_manifest = next(record for record in configurations
                                  if record["config_id"] == "gte_multilingual_local_assets_v1.json")
            manifest_path = producer.get("asset_manifest")
            if manifest_path is not None:
                try:
                    # Existing parallel plans name this as a repository-relative
                    # config, separately from workspace-relative model directories.
                    asset_manifest, manifest = _observe(_path(manifest_path, repository), kind="manifest",
                        maximum=max_metadata_bytes, expected_sha256=producer.get("expected_asset_manifest_sha256"))
                    if manifest is not None and manifest.get("schema") != "gte-multilingual-local-assets/v1":
                        asset_manifest.update(status="invalid")
                        asset_manifest["reasons"].append("unexpected_asset_manifest_schema")
                        manifest = None
                except ValueError as error:
                    issues.append({"config_id": lane_id, "field": "asset_manifest", "reason": str(error)})
                    manifest = None
            entries = manifest.get("files", []) if manifest else []
        if type(entries) is not list or len(entries) > MAX_REFERENCES:
            issues.append({"config_id": lane_id, "field": "encoder_assets", "reason": "invalid_asset_list"})
            entries = []
        for entry in entries:
            if type(entry) is not dict or entry.get("relative_to") not in ("model", "code"):
                issues.append({"config_id": lane_id, "field": "encoder_assets", "reason": "invalid_asset_entry"})
                continue
            directory = producer.get(entry["relative_to"] + "_directory")
            if directory is None:
                assets.append({"relative_path": entry.get("path"), "role": entry["relative_to"],
                               "expected_sha256": entry.get("sha256"), "expected_bytes": entry.get("bytes"),
                               "observed_sha256": None, "expected_sha256_match": None,
                               "path_exists": None, "metadata_inspected": False,
                               "status": "unconfigured", "reasons": ["asset_directory_not_configured"]})
                continue
            try:
                directory_path = _path(directory, workspace)
                relative = entry.get("path")
                if type(relative) is not str or Path(relative).is_absolute():
                    raise ValueError("asset_path_must_be_relative")
                path = _path(relative, directory_path)
                record, _ = _observe(path, kind="encoder_asset", maximum=max_metadata_bytes,
                                     expected_sha256=entry.get("sha256"), expected_bytes=entry.get("bytes"))
                record.update(relative_path=relative, role=entry["relative_to"])
                assets.append(record)
            except ValueError as error:
                issues.append({"config_id": lane_id, "field": "encoder_assets", "reason": str(error)})
        encoders.append({"lane_id": lane_id, "profile_source": profile, "declared_profile": declarations,
                         "asset_manifest": asset_manifest,
                         "model_directory": producer.get("model_directory"), "code_directory": producer.get("code_directory"),
                         "assets": assets, "numerically_evaluated": False, "qualified": False})

    return {"schema": SCHEMA, "repository_root": str(repository), "workspace_root": str(workspace),
            "max_metadata_bytes": max_metadata_bytes, "configurations": configurations,
            "lineages": lineages, "lanes": lanes, "artifacts": artifacts, "encoders": encoders, "issues": issues,
            "implementation_source": _observe(Path(__file__).absolute(), kind="source", maximum=max_metadata_bytes)[0],
            "source_identity_scope": "listed_files_only_not_complete_dependency_closure",
            "model_loaded": False, "download_executed": False, "training_executed": False,
            "numerically_evaluated": False, "qualified": False, "proof_authority": False}
