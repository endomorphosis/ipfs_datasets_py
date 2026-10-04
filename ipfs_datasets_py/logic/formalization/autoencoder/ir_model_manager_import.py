"""Explicit checkpoint-metadata registration through a genuine ModelManager.

This adapter authenticates a caller-pinned import plan and persisted publisher
receipts before calling an injected manager. It neither creates a manager nor
uploads/downloads assets, loads a decoder, opens a database or refreshes a live
manager in another process. The driver owns database serialization and fresh
persisted readback. Publisher receipt integrity is distinct from independent
remote/account authentication, which this adapter does not perform.

The real metadata dataclasses are imported lazily at the explicit registration
call, after every artifact has been checked. Tests may inject a metadata factory
and an inert manager; those controls establish no native persistence authority.
Sequential endpoint fences are cooperative observations, not an atomic snapshot.

Detached source-token and off-matrix components use a separate identity schema.
Their internal feature/hidden widths do not create an 8D/384D/768D lane binding.
"""
from __future__ import annotations

from dataclasses import fields, is_dataclass
from datetime import datetime
from enum import Enum
import hashlib
import json
import os
from pathlib import Path
import re
import stat


SCHEMA = "ir-model-manager-import-plan/v1"
RESULT_SCHEMA = "ir-model-manager-import-result/v1"
PUBLICATION_SCHEMA = "ir-model-hub-publication-receipt/v1"
COMPONENT_BINDING_SCHEMA = "ir-decoder-component-binding/v1"
MAX_REFERENCE_BYTES = 512 * 1024 * 1024
MAX_MANIFEST_BYTES = 8 * 1024 * 1024
MAX_MODELS = 256
_HEX = re.compile(r"[0-9a-f]{64}\Z")
_REVISION = re.compile(r"[0-9a-f]{40}\Z")
_PIN_FIELDS = {"path", "bytes", "sha256"}
_MODEL_FIELDS = {"model_id", "model_name", "model_type", "architecture", "inputs", "outputs",
    "huggingface_config", "inference_code_location", "supported_backends", "hardware_requirements",
    "performance_metrics", "tags", "source_url", "license", "description", "model_card",
    "repository_structure", "model_cid", "config_cid", "tokenizer_cid", "artifact_cid",
    "model_revision", "revision_id", "revision_created_at", "parent_model_id", "parent_model_cid",
    "last_used_at", "last_inference_cid", "last_run_id", "inference_count", "created_at", "updated_at"}
_REQUIRED_MODEL_FIELDS = {"model_id", "model_name", "model_type", "architecture", "inputs", "outputs",
    "huggingface_config", "model_revision", "revision_id"}
_MODEL_TYPES = {"language_model", "vision_model", "multimodal", "audio_model", "embedding_model",
    "encoder_decoder", "encoder_only", "decoder_only"}
_DATA_TYPES = {"text", "image", "audio", "video", "embeddings", "tokens", "logits", "features"}
_IDENTITY_FIELDS = {"record_id", "ir_family_id", "dimension", "dimension_role", "role",
    "schema_version", "task_id", "profile_id", "format_id", "original_checkpoint_pin",
    "trained", "initialization_only", "donor", "runtime_ready", "teacher_qualified", "proof_authority"}
_ACTIVITY_FIELDS = {"created_at", "updated_at", "revision_created_at", "last_used_at",
    "last_inference_cid", "last_run_id", "inference_count"}


class ModelManagerImportError(ValueError):
    """Invalid/conflicting metadata or an incomplete explicit registration."""

    def __init__(self, message, *, outcomes=()):
        super().__init__(message)
        self.outcomes = json.loads(_raw(list(outcomes)))


def _require(condition, message):
    if not condition:
        raise ModelManagerImportError(message)


def _raw(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      allow_nan=False).encode("utf-8")


def _primitive(value, depth=0):
    _require(depth <= 32, "metadata nesting exceeds bound")
    if type(value) in (str, int, float, bool) or value is None:
        return value
    if type(value) is list:
        return [_primitive(item, depth + 1) for item in value]
    if type(value) is dict:
        _require(all(type(key) is str for key in value), "metadata keys must be exact strings")
        return {key: _primitive(item, depth + 1) for key, item in value.items()}
    raise ModelManagerImportError("closed JSON primitives required")


def _detached(value):
    try:
        raw = _raw(_primitive(value))
        _require(len(raw) <= MAX_MANIFEST_BYTES, "metadata exceeds evaluator byte bound")
        return json.loads(raw)
    except (ValueError, TypeError, OverflowError, RecursionError) as error:
        if isinstance(error, ModelManagerImportError):
            raise
        raise ModelManagerImportError("finite bounded JSON metadata required") from error


def _text(value, name, maximum=4096, *, optional=False):
    if optional and value is None:
        return value
    _require(type(value) is str and value and "\x00" not in value,
             name + " must be explicit nonempty text")
    try:
        _require(len(value.encode("utf-8")) <= maximum, name + " exceeds UTF8 bound")
    except UnicodeError as error:
        raise ModelManagerImportError(name + " must be UTF8") from error
    return value


def _pin(value, maximum, *, allow_empty=False):
    _require(type(value) is dict and set(value) == _PIN_FIELDS, "closed file pin required")
    _text(value["path"], "file path")
    _require(Path(value["path"]).is_absolute(), "explicit absolute pinned path required")
    _require(type(value["bytes"]) is int and (0 if allow_empty else 1) <= value["bytes"] <= maximum,
             "pinned byte count exceeds bound")
    _require(type(value["sha256"]) is str and _HEX.fullmatch(value["sha256"]), "SHA256 pin required")
    return dict(value)


def _identity(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_size,
            info.st_mtime_ns, info.st_ctime_ns)


def _witness(path):
    alias = os.lstat(path)
    _require(stat.S_ISREG(alias.st_mode) or stat.S_ISLNK(alias.st_mode), "regular file or alias required")
    link = os.readlink(path) if stat.S_ISLNK(alias.st_mode) else None
    target = str(Path(path).resolve(strict=True))
    info = os.stat(target, follow_symlinks=False)
    _require(stat.S_ISREG(info.st_mode), "pinned target must be regular")
    return (_identity(alias), link, target, _identity(info))


def _read(pin, *, retain=False, git_blob=False):
    fd = None
    try:
        before = _witness(pin["path"])
        _require(before[3][3] == pin["bytes"], "pinned byte count differs")
        fd = os.open(pin["path"], os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC)
        _require(_identity(os.fstat(fd)) == before[3], "pinned target changed before open")
        digest, count, chunks = hashlib.sha256(), 0, []
        blob_digest = hashlib.sha1(b"blob " + str(pin["bytes"]).encode() + b"\0") if git_blob else None
        while True:
            block = os.read(fd, min(1024 * 1024, pin["bytes"] - count + 1))
            if not block:
                break
            count += len(block)
            _require(count <= pin["bytes"], "pinned file grew")
            digest.update(block)
            if blob_digest is not None:
                blob_digest.update(block)
            if retain:
                chunks.append(block)
        _require(_identity(os.fstat(fd)) == before[3] and _witness(pin["path"]) == before,
                 "pinned file changed while reading")
        _require(count == pin["bytes"] and digest.hexdigest() == pin["sha256"],
                 "pinned file SHA256 differs")
        return b"".join(chunks) if retain else blob_digest.hexdigest() if blob_digest is not None else None
    except (OSError, RuntimeError) as error:
        raise ModelManagerImportError("cannot read stable pinned regular file") from error
    finally:
        if fd is not None:
            os.close(fd)


def _json(pin):
    def pairs(items):
        result = {}
        for key, value in items:
            _require(key not in result, "duplicate JSON key")
            result[key] = value
        return result
    try:
        raw = _read(pin, retain=True)
        return _detached(json.loads(raw, object_pairs_hook=pairs,
            parse_constant=lambda _: (_ for _ in ()).throw(ModelManagerImportError("nonfinite JSON"))))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ModelManagerImportError("pinned metadata must be JSON") from error


def ir_model_asset_record_id(ir_family_id, dimension, dimension_role, role, checkpoint_sha256):
    """Name a concrete asset binding, without inventing a decoder profile."""
    identity = {"ir_family_id": _text(ir_family_id, "family", 128), "dimension": dimension,
        "dimension_role": _text(dimension_role, "dimension role", 128),
        "role": _text(role, "declared role", 256), "checkpoint_sha256": checkpoint_sha256}
    _require(type(dimension) is int and dimension in (8, 384, 768), "supported lane width required")
    _require(type(checkpoint_sha256) is str and _HEX.fullmatch(checkpoint_sha256), "checkpoint SHA256 required")
    return "ir-model-asset-binding/v1:" + hashlib.sha256(_raw(identity)).hexdigest()


def ir_model_component_record_id(ir_family_id, dimension_role, role, checkpoint_sha256):
    """Name an explicit component without inventing an external IR lane width."""
    family = _text(ir_family_id, "family", 128)
    _require(family in {"codebase_ir", "security_ir", "legal_ir", "intent_ir", "ui_ux_ir"},
             "known IR family required")
    _require(type(dimension_role) is str and dimension_role in ("source_tokens", "unbound_component"),
             "explicit detached component role required")
    identity = {"asset_binding_schema": COMPONENT_BINDING_SCHEMA,
        "ir_family_id": family, "dimension": None, "dimension_role": dimension_role,
        "external_lane_binding": None, "role": _text(role, "declared role", 256),
        "checkpoint_sha256": checkpoint_sha256}
    _require(type(checkpoint_sha256) is str and _HEX.fullmatch(checkpoint_sha256),
             "checkpoint SHA256 required")
    return "ir-model-component-binding/v1:" + hashlib.sha256(_raw(identity)).hexdigest()


def _io(value):
    _require(type(value) is dict and {"name", "data_type"} <= set(value)
             and set(value) <= {"name", "data_type", "shape", "dtype", "description", "optional"},
             "closed IOSpec fields required")
    _text(value["name"], "IO name", 256)
    _require(type(value["data_type"]) is str and value["data_type"] in _DATA_TYPES, "known DataType required")
    if value.get("shape") is not None:
        _require(type(value["shape"]) is list and 1 <= len(value["shape"]) <= 16
                 and all(type(n) is int and (n == -1 or 1 <= n <= 1048576) for n in value["shape"]),
                 "bounded explicit IO shape required")
    if "optional" in value:
        _require(type(value["optional"]) is bool, "IO optional must be boolean")


def _metadata(value, checkpoint):
    _require(type(value) is dict and _REQUIRED_MODEL_FIELDS <= set(value) and set(value) <= _MODEL_FIELDS,
             "closed genuine ModelMetadata fields required; serving_config is forbidden")
    for key in ("model_id", "model_name", "architecture"):
        _text(value[key], key, 512)
    _require(type(value["model_type"]) is str and value["model_type"] in _MODEL_TYPES, "known ModelType required")
    for name in ("inputs", "outputs"):
        _require(type(value[name]) is list and len(value[name]) <= 32, "bounded IO lists required")
        for spec in value[name]:
            _io(spec)
    _require(value["model_revision"] == checkpoint["sha256"]
             and value["revision_id"] == checkpoint["sha256"], "checkpoint SHA must identify both revisions")
    config = value["huggingface_config"]
    _require(type(config) is dict and type(config.get("ir_checkpoint")) is dict, "explicit ir_checkpoint metadata required")
    identity = config["ir_checkpoint"]
    _require(_IDENTITY_FIELDS <= set(identity), "complete checkpoint identity/status declarations required")
    _require(identity["record_id"] == value["model_id"], "model_id must preserve exact record_id")
    family = _text(identity["ir_family_id"], "IR family", 128)
    _require(family in {"codebase_ir", "security_ir", "legal_ir", "intent_ir", "ui_ux_ir"}, "known IR family required")
    dimension = identity["dimension"]
    component = identity.get("asset_binding_schema") == COMPONENT_BINDING_SCHEMA
    if component:
        _require(dimension is None and identity["dimension_role"] in ("source_tokens", "unbound_component"),
                 "detached component requires null external dimension and explicit component role")
        _require("external_lane_binding" in identity and identity["external_lane_binding"] is None,
                 "detached component must explicitly remain unbound to an external lane")
        _require(identity["profile_id"] is None and identity["format_id"] is None,
                 "detached component cannot claim a qualified native format/profile")
        _require(config.get("complete_runtime_io_contract") is False,
                 "detached component runtime IO qualification must remain false")
        if identity["dimension_role"] == "source_tokens":
            _require(value["inputs"] and all(spec["data_type"] in ("text", "tokens")
                     for spec in value["inputs"]),
                     "source-token component requires only explicit text/token inputs")
    else:
        _require(type(dimension) is int and dimension in (8, 384, 768), "exact supported lane width required")
        _require(identity["dimension_role"] in ("latent", "input_embedding"), "explicit dimension role required")
    _text(identity["role"], "checkpoint role", 256)
    for name in ("schema_version", "task_id", "profile_id", "format_id"):
        _text(identity[name], name, 512, optional=True)
    for name in ("trained", "donor"):
        _require(identity[name] is None or type(identity[name]) is bool, "unknown or boolean status required")
    for name in ("initialization_only", "runtime_ready", "teacher_qualified", "proof_authority"):
        _require(type(identity[name]) is bool, "explicit boolean status required")
    _require(identity["runtime_ready"] is False and identity["teacher_qualified"] is False
             and identity["proof_authority"] is False, "publication must not promote readiness/teacher/proof")
    _require(not identity["initialization_only"] or identity["trained"] is not True,
             "initialization-only asset cannot be declared trained")
    original = _pin(identity["original_checkpoint_pin"], MAX_REFERENCE_BYTES)
    _require((original["sha256"], original["bytes"]) == (checkpoint["sha256"], checkpoint["bytes"]),
             "original checkpoint identity differs")
    record_id = identity["record_id"]
    if component:
        _require(record_id == ir_model_component_record_id(family, identity["dimension_role"],
                 identity["role"], checkpoint["sha256"]), "deterministic detached component record_id required")
    elif record_id.startswith("ir-decoder-checkpoint-record/v1:"):
        _require(_HEX.fullmatch(record_id.split(":", 1)[1]) and family in {"intent_ir", "security_ir"}
                 and dimension == 384 and identity["profile_id"] is not None and identity["format_id"] is not None,
                 "registered format record must retain explicit known binding")
    else:
        _require(record_id == ir_model_asset_record_id(family, dimension, identity["dimension_role"],
                 identity["role"], checkpoint["sha256"]), "deterministic concrete asset record_id required")
    return original


def _publication(pin, maximum):
    receipt = _json(pin)
    _require(type(receipt) is dict and receipt.get("schema") == PUBLICATION_SCHEMA,
             "explicit publication receipt schema required")
    _require(receipt.get("files_verified") is True, "verified publisher receipt required")
    _text(receipt.get("repository_id"), "repository ID", 256)
    _require(type(receipt.get("revision")) is str and _REVISION.fullmatch(receipt["revision"]),
             "immutable full publication revision required")
    _require(type(receipt.get("files")) is list and 1 <= len(receipt["files"]) <= 4096,
             "bounded publication files required")
    paths = set()
    pins = []
    for entry in receipt["files"]:
        _require(type(entry) is dict, "publication file record required")
        path = _text(entry.get("path_in_repo"), "remote file path")
        _require(not path.startswith("/") and "\\" not in path
                 and all(part not in ("", ".", "..") for part in path.split("/"))
                 and path not in paths, "unique safe exact remote paths required")
        paths.add(path)
        local = _pin(entry.get("file_pin"), maximum, allow_empty=True)
        _require(entry.get("verified") is True and type(entry.get("bytes")) is int
                 and entry["bytes"] == local["bytes"]
                 and entry.get("sha256") == local["sha256"], "publication file identity differs")
        remote = entry.get("remote_identity")
        _require(type(remote) is dict and type(remote.get("bytes")) is int
                 and remote["bytes"] == local["bytes"], "remote byte identity required")
        if remote.get("scheme") == "lfs-payload-sha256":
            _require(remote.get("sha256") == local["sha256"], "remote LFS SHA256 differs")
        else:
            _require(remote.get("scheme") == "git-blob-sha1" and type(remote.get("blob_id")) is str
                     and _REVISION.fullmatch(remote["blob_id"]), "remote Git blob identity required")
            blob = _read(local, git_blob=True)
            _require(blob == remote["blob_id"], "remote Git blob SHA1 differs")
        _read(local)
        pins.append(local)
    return receipt, pins


def _prepare(manifest_pin, release_receipts, maximum):
    _require(type(maximum) is int and 0 < maximum <= MAX_REFERENCE_BYTES, "reference byte cap required")
    manifest = _pin(_detached(manifest_pin), min(maximum, MAX_MANIFEST_BYTES))
    _require(type(release_receipts) in (list, tuple) and 1 <= len(release_receipts) <= MAX_MODELS,
             "explicit persisted publication receipt pins required")
    releases = [_pin(_detached(pin), min(maximum, MAX_MANIFEST_BYTES)) for pin in release_receipts]
    _require(len({pin["path"] for pin in releases}) == len(releases), "unique publication receipt paths required")
    plan = _json(manifest)
    _require(type(plan) is dict and set(plan) == {"schema", "models"} and plan["schema"] == SCHEMA,
             "closed import plan schema required")
    _require(type(plan["models"]) is list and 1 <= len(plan["models"]) <= MAX_MODELS, "bounded explicit model list required")
    pins = [manifest, *releases]
    publications = []
    for pin in releases:
        publication, files = _publication(pin, maximum)
        publications.append(publication)
        pins.extend(files)
    ids = set()
    for record in plan["models"]:
        _require(type(record) is dict and set(record) == {"model_metadata", "checkpoint_pin", "release"},
                 "closed model/checkpoint/release record required")
        checkpoint = _pin(record["checkpoint_pin"], maximum)
        original = _metadata(record["model_metadata"], checkpoint)
        model_id = record["model_metadata"]["model_id"]
        _require(model_id not in ids, "duplicate model_id forbidden")
        ids.add(model_id)
        release = record["release"]
        _require(type(release) is dict and set(release) == {"repository_id", "revision", "path_in_repo", "checkpoint_sha256"},
                 "closed immutable release binding required")
        _text(release["repository_id"], "release repository ID", 256)
        _text(release["path_in_repo"], "release file path")
        _require(type(release["revision"]) is str and _REVISION.fullmatch(release["revision"]),
                 "exact immutable release revision required")
        _require(release["checkpoint_sha256"] == checkpoint["sha256"], "release checkpoint SHA differs")
        if record["model_metadata"].get("source_url") is not None:
            base = "https://huggingface.co/" + release["repository_id"]
            allowed = {base + "/tree/" + release["revision"],
                base + "/blob/" + release["revision"] + "/" + release["path_in_repo"],
                base + "/resolve/" + release["revision"] + "/" + release["path_in_repo"]}
            _require(record["model_metadata"]["source_url"] in allowed,
                     "source_url must bind exact immutable publication")
        matches = [entry for publication in publications
            if publication["repository_id"] == release["repository_id"] and publication["revision"] == release["revision"]
            for entry in publication["files"] if entry["path_in_repo"] == release["path_in_repo"]
            and entry["bytes"] == checkpoint["bytes"] and entry["sha256"] == checkpoint["sha256"]]
        _require(len(matches) == 1, "exact unique verified publication checkpoint required")
        pins.extend((checkpoint, original))
    unique = {}
    for pin in pins:
        _require(pin["path"] not in unique or unique[pin["path"]] == pin, "conflicting same-path artifact pins")
        unique[pin["path"]] = pin
    pins = list(unique.values())
    _fence(pins)
    return plan, pins, manifest, releases


def _fence(pins):
    for pin in pins:
        _read(pin)


def _normalize(value):
    if isinstance(value, Enum):
        return _normalize(value.value)
    if isinstance(value, datetime):
        return value.isoformat()
    if is_dataclass(value) and not isinstance(value, type):
        return {field.name: _normalize(getattr(value, field.name)) for field in fields(value)}
    if type(value) is tuple:
        return [_normalize(item) for item in value]
    if type(value) is list:
        return [_normalize(item) for item in value]
    if type(value) is dict:
        return {key: _normalize(item) for key, item in value.items()}
    return value


def _stable_metadata(value):
    normalized = _detached(_normalize(value))
    _require(type(normalized) is dict, "metadata object or primitive field dict required")
    stable = {key: item for key, item in normalized.items() if key not in _ACTIVITY_FIELDS
              and not (key == "serving_config" and item is None)}
    # Complete only the genuine metadata/IOSpec defaults. Extra fields and a
    # non-null serving config remain visible and therefore conflict.
    for name in _MODEL_FIELDS - _ACTIVITY_FIELDS - {"model_id", "model_name", "model_type",
                                                  "architecture", "inputs", "outputs"}:
        stable.setdefault(name, [] if name in {"supported_backends", "tags"}
                          else "" if name == "description" else None)
    for name in ("inputs", "outputs"):
        if type(stable.get(name)) is list:
            complete = []
            for spec in stable[name]:
                _require(type(spec) is dict, "metadata IO must be field dictionaries")
                complete.append({"shape": None, "dtype": "float32", "description": "",
                                 "optional": False, **spec})
            stable[name] = complete
    return stable


def _matches(actual, expected):
    actual = _stable_metadata(actual)
    expected = _stable_metadata(expected)
    return actual == expected


def _real_factory(value):
    from ipfs_accelerate_py.model_manager import DataType, IOSpec, ModelMetadata, ModelType
    data = _detached(value)
    data["model_type"] = ModelType(data["model_type"])
    for name in ("inputs", "outputs"):
        converted = []
        for spec in data[name]:
            spec = dict(spec)
            spec["data_type"] = DataType(spec["data_type"])
            if spec.get("shape") is not None:
                spec["shape"] = tuple(spec["shape"])
            converted.append(IOSpec(**spec))
        data[name] = converted
    for name in ("created_at", "updated_at", "revision_created_at", "last_used_at"):
        if isinstance(data.get(name), str):
            data[name] = datetime.fromisoformat(data[name])
    return ModelMetadata(**data)


def import_ir_model_manager_records(manifest_pin, *, release_receipts, manager, readback,
                                    metadata_factory=None, max_reference_bytes=MAX_REFERENCE_BYTES):
    """Register pinned assets, refusing conflicts and requiring fresh readback.

    ``readback(model_id)`` must return that record from independently reopened
    persisted storage. This contract is the driver's responsibility; this
    adapter cannot prove that an arbitrary injected callable actually reopens
    storage. Returning True from ``add_model`` alone never qualifies a record.
    Already identical records are not overwritten or reset. Ordinary failures
    retain partial outcomes; KeyboardInterrupt/SystemExit propagate unchanged.
    """
    plan, pins, manifest, releases = _prepare(manifest_pin, release_receipts, max_reference_bytes)
    _require(callable(getattr(manager, "get_model", None)) and callable(getattr(manager, "add_model", None)),
             "genuine manager get_model/add_model API required")
    _require(callable(readback), "explicit fresh persisted readback callable required")
    factory = _real_factory if metadata_factory is None else metadata_factory
    _require(callable(factory), "explicit metadata factory callable required")
    outcomes = []
    try:
        # Inspect every collision before the first mutation, including late plan records.
        for record in plan["models"]:
            metadata = record["model_metadata"]
            existing = manager.get_model(metadata["model_id"])
            _require(existing is None or _matches(existing, metadata), "existing model_id has conflicting metadata")
        _fence(pins)
        for record in plan["models"]:
            metadata = record["model_metadata"]
            model_id = metadata["model_id"]
            existing = manager.get_model(model_id)
            _require(existing is None or _matches(existing, metadata), "model_id changed to conflicting metadata")
            outcome = {"model_id": model_id, "checkpoint_sha256": record["checkpoint_pin"]["sha256"],
                "status": "pending", "already_present": existing is not None,
                "add_model_started": False, "add_model_returned": False, "add_model_result": None,
                "persisted_readback_started": False, "persisted_readback_returned": False,
                "persisted_metadata_matched": False}
            outcomes.append(outcome)
            if existing is None:
                materialized = factory(_detached(metadata))
                _require(_matches(materialized, metadata), "metadata factory changed declared fields")
                _fence(pins)
                current = manager.get_model(model_id)
                _require(current is None or _matches(current, metadata),
                         "model_id changed to conflicting metadata during factory")
                if current is None:
                    outcome["add_model_started"] = True
                    added = manager.add_model(materialized)
                    outcome["add_model_returned"] = True
                    outcome["add_model_result"] = added if type(added) is bool else None
                    _require(added is True, "add_model did not return exact success")
                else:
                    existing = current
                    outcome["already_present"] = True
            outcome["persisted_readback_started"] = True
            persisted = readback(model_id)
            outcome["persisted_readback_returned"] = True
            _require(persisted is not None and _matches(persisted, metadata), "fresh persisted metadata differs or is missing")
            outcome["persisted_metadata_matched"] = True
            outcome["status"] = "already_present_verified" if existing is not None else "registered_verified"
            _fence(pins)
        return _detached({"schema": RESULT_SCHEMA, "manifest_receipt": manifest,
            "publication_receipts": releases, "outcomes": outcomes, "completed": True,
            "registered_count": sum(item["status"] == "registered_verified" for item in outcomes),
            "already_present_count": sum(item["status"] == "already_present_verified" for item in outcomes),
            "persisted_metadata_matched_count": len(outcomes),
            "readback_semantics": "Explicit driver-owned reopened-storage callable; adapter verifies returned fields, not its implementation.",
            "authority": {"registration_metadata_verified": True, "remote_independently_verified_by_adapter": False,
                "active_process_refreshed": False, "runtime_ready": False, "teacher_qualified": False,
                "proof_authority": False, "model_numerically_loaded": False, "model_quality_qualified": False}})
    except Exception as error:
        if isinstance(error, ModelManagerImportError):
            raise ModelManagerImportError(str(error), outcomes=outcomes) from error
        raise ModelManagerImportError("explicit manager registration/readback failed", outcomes=outcomes) from error


__all__ = ["ModelManagerImportError", "ir_model_asset_record_id", "ir_model_component_record_id",
           "import_ir_model_manager_records"]
