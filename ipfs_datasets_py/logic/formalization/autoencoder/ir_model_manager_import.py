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
LegalIR4096 source representations use a separate, pinned expected-producer
profile; registration does not authenticate that producer's native execution.

The separate v2 entrypoint also reads the already published historical
source/span declaration contract. Its record IDs and path-sensitive native
library declarations remain distinct from the independent expected-producer
profile above. Neither schema is converted into the other.
"""
from __future__ import annotations

from dataclasses import fields, is_dataclass
from datetime import datetime
from enum import Enum
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat


SCHEMA = "ir-model-manager-import-plan/v1"
RESULT_SCHEMA = "ir-model-manager-import-result/v1"
PUBLICATION_SCHEMA = "ir-model-hub-publication-receipt/v1"
COMPONENT_BINDING_SCHEMA = "ir-decoder-component-binding/v1"
SOURCE_REPRESENTATION_BINDING_SCHEMA = "ir-source-representation-asset-binding/v1"
SCHEMA_V2 = "ir-model-manager-import-plan/v2"
RESULT_SCHEMA_V2 = "ir-model-manager-import-result/v2"
SOURCE_BINDING_SCHEMA = "ir-source-representation-binding/v2"
SOURCE_PROFILE_SCHEMA = "ir-native4096-source-profile/v1"
_SOURCE_FIELDS = {"schema", "expected_producer", "pooling", "normalization", "attention",
    "context_tokens", "sequences", "source_text_required", "evidence_pins", "evidence_scope",
    "ordinary_receipt_is_capability"}
_PRODUCER_FIELDS = {"profile", "model_sha256", "worker_sha256", "worker_source_sha256",
    "owner_source_sha256", "vocabulary_owner_source_sha256", "library_sha256"}
_SOURCE_PROFILES = {"leanstral4096:cpu1:last:l2:single-sequence:tokens512:lazy-mmap:v2",
    "leanstral4096:cpu1:last:l2:single-sequence:tokens512:layer-reclaim:v3"}
_SOURCE_CHECKPOINT_SCHEMAS = {"native-4096-source-span-checkpoint/v1",
    "bound-native4096-source-span-checkpoint/v1"}
_SOURCE_TASK = "source_text_and_representation_to_legal_ir"
_SOURCE_ARCHITECTURE = "utf8-byte-bidirectional-gru-native-4096-film-spans/v1"
_SOURCE_FALSE = {"native_execution_verified_by_importer": False,
    "source_compatibility_verified": False, "live_native_capability_restored": False}
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


def ir_model_source_representation_record_id(role, checkpoint_sha256, source_representation_profile_id):
    """Name a LegalIR4096 source asset, binding its expected-producer profile."""
    _require(type(checkpoint_sha256) is str and _HEX.fullmatch(checkpoint_sha256),
             "checkpoint SHA256 required")
    _require(type(source_representation_profile_id) is str
             and source_representation_profile_id.startswith("ir-source-representation-profile/v1:")
             and _HEX.fullmatch(source_representation_profile_id.split(":", 1)[1]),
             "versioned source-representation profile ID required")
    identity = {"asset_binding_schema": SOURCE_REPRESENTATION_BINDING_SCHEMA,
        "ir_family_id": "legal_ir", "dimension": 4096, "dimension_role": "input_embedding",
        "role": _text(role, "declared role", 256), "checkpoint_sha256": checkpoint_sha256,
        "source_representation_profile_id": source_representation_profile_id}
    return SOURCE_REPRESENTATION_BINDING_SCHEMA + ":" + hashlib.sha256(_raw(identity)).hexdigest()


def _source_representation(value):
    """Validate historical declarations without importing the live owner.

    Evidence files are authenticated by the import plan's ordinary pin fences.
    No serialized declaration can recreate native execution or a live handle.
    Locator paths are excluded from the logical evidence identity.
    """
    value = _detached(value)
    _require(type(value) is dict and set(value) == _SOURCE_FIELDS,
             "closed native4096 source representation declaration required")
    _require(value["schema"] == SOURCE_PROFILE_SCHEMA and value["pooling"] == "last"
             and value["normalization"] == "l2" and value["attention"] == "causal"
             and type(value["context_tokens"]) is int and value["context_tokens"] == 512
             and type(value["sequences"]) is int and value["sequences"] == 1
             and value["source_text_required"] is True,
             "preserved source-text plus native4096 input profile required")
    _require(value["evidence_scope"] == "pinned_historical_metadata_only"
             and value["ordinary_receipt_is_capability"] is False,
             "historical metadata cannot grant native capability")
    producer = value["expected_producer"]
    _require(type(producer) is dict and set(producer) == _PRODUCER_FIELDS,
             "closed existing native producer declaration required")
    _require(type(producer["profile"]) is str and producer["profile"] in _SOURCE_PROFILES,
             "explicit preserved native producer profile required")
    for key in _PRODUCER_FIELDS - {"profile", "library_sha256"}:
        _require(type(producer[key]) is str and _HEX.fullmatch(producer[key]),
                 "native producer SHA256 required: " + key)
    libraries = producer["library_sha256"]
    _require(type(libraries) is dict and 1 <= len(libraries) <= 63,
             "bounded explicit native library declarations required")
    for path, digest in libraries.items():
        name = PurePosixPath(path)
        _text(path, "native library path")
        _require(name.is_absolute() and name.as_posix() == path and ".." not in name.parts,
                 "canonical absolute native library declaration path required")
        _require(type(digest) is str and _HEX.fullmatch(digest), "native library SHA256 required")
    pins = value["evidence_pins"]
    _require(type(pins) is list and 1 <= len(pins) <= 8,
             "one to eight explicit historical evidence pins required")
    pins = [_pin(pin, MAX_MANIFEST_BYTES) for pin in pins]
    _require(len({pin["path"] for pin in pins}) == len(pins), "unique native evidence paths required")
    content = [{"bytes": pin["bytes"], "sha256": pin["sha256"]} for pin in pins]
    _require(len({_raw(item) for item in content}) == len(content), "unique native evidence contents required")
    logical = {**value, "evidence_pins": sorted(content, key=_raw)}
    return logical, pins


def ir_model_source_record_id_v2(ir_family_id, dimension_role, role, checkpoint_sha256, *,
                                 schema_version, task_id, source_representation):
    """Name an explicit LegalIR4096 source/span asset, not a runtime profile.

    This validates metadata only. The importer separately authenticates pinned
    bytes; neither this helper nor that authentication proves native execution.
    """
    _require(type(ir_family_id) is str and ir_family_id == "legal_ir"
             and type(dimension_role) is str and dimension_role == "source_input_representation_width",
             "explicit LegalIR4096 source-input representation role required")
    _require(type(schema_version) is str and schema_version in _SOURCE_CHECKPOINT_SCHEMAS
             and type(task_id) is str and task_id == _SOURCE_TASK, "supported source/span checkpoint task required")
    _require(type(checkpoint_sha256) is str and _HEX.fullmatch(checkpoint_sha256),
             "checkpoint SHA256 required")
    logical, _ = _source_representation(source_representation)
    identity = {"asset_binding_schema": SOURCE_BINDING_SCHEMA, "ir_family_id": ir_family_id,
        "dimension": 4096, "dimension_role": dimension_role,
        "role": _text(role, "declared role", 256), "checkpoint_sha256": checkpoint_sha256,
        "schema_version": schema_version, "task_id": task_id,
        "source_representation": logical}
    return "ir-model-source-binding/v2:" + hashlib.sha256(_raw(identity)).hexdigest()


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


def _decoder_identity_witness(binding, identity, value, maximum):
    _require(type(binding) is dict and set(binding) == {"schema", "registry_pin", "record_id", "target_format_schema_version"}
             and binding["schema"] == "ir-decoder-identity-witness/v1"
             and type(binding["record_id"]) is str and binding["record_id"] == identity["record_id"]
             and identity["record_id"].startswith("ir-decoder-checkpoint-record/v1:")
             and identity.get("asset_binding_schema") is None,
             "strict decoder witness requires the explicit original decoder record branch")
    _text(binding["target_format_schema_version"], "target format schema version", 512)
    registry_pin = _pin(binding["registry_pin"], min(maximum, MAX_MANIFEST_BYTES))
    from .ir_decoder_profile_inventory import (DecoderProfileInventoryError,
        select_ir_decoder_identity_witness_v1)
    try:
        select_ir_decoder_identity_witness_v1(_json(registry_pin), record_id=binding["record_id"], expected_identity={
            **{key: identity[key] for key in ("ir_family_id", "dimension", "dimension_role", "task_id", "profile_id", "format_id")},
            "checkpoint_schema": identity["schema_version"],
            "target_format_schema_version": binding["target_format_schema_version"],
            "original_checkpoint_pin": identity["original_checkpoint_pin"], "architecture": value["architecture"]})
    except DecoderProfileInventoryError as error:
        raise ModelManagerImportError("invalid strict decoder identity witness") from error
    return registry_pin


def _metadata(value, checkpoint, *, max_reference_bytes=MAX_REFERENCE_BYTES, source_v2=False):
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
    source_representation = identity.get("asset_binding_schema") == SOURCE_REPRESENTATION_BINDING_SCHEMA
    source = identity.get("asset_binding_schema") == SOURCE_BINDING_SCHEMA
    if not source:
        _require("source_representation" not in identity,
                 "historical source declaration requires its explicit v2 asset binding schema")
    if not source_representation:
        _require(not ({"source_representation_profile_id", "source_representation_profile_pin"} & set(identity)),
                 "source-representation profile requires its explicit asset binding schema")
        _require(not (type(identity.get("asset_binding_schema")) is str
                 and identity["asset_binding_schema"].startswith("ir-source-representation-")
                 and not source),
                 "unknown source-representation binding schema")
        for name in ("profile_id", "format_id"):
            _require(not (type(identity[name]) is str
                     and identity[name].startswith(("ir-source-representation-profile/",
                         "ir-native4096-source-profile/"))),
                     "source-representation profile cannot be used as a decoder profile/format")
    if source:
        _require(source_v2 is True, "native4096 binding requires the explicit v2 importer")
        _require(set(identity) == _IDENTITY_FIELDS | {"asset_binding_schema", "source_representation"},
                 "closed source-representation checkpoint identity required")
        _require(family == "legal_ir" and type(dimension) is int and dimension == 4096
                 and identity["dimension_role"] == "source_input_representation_width",
                 "explicit LegalIR4096 source width required; bottleneck claims are unsupported")
        _require(identity["profile_id"] is None and identity["format_id"] is None,
                 "metadata source binding cannot invent a qualified decoder format/profile")
        _require(config.get("complete_runtime_io_contract") is False
                 and all(config.get(key) is False for key in _SOURCE_FALSE),
                 "native runtime/source qualification must remain explicitly false")
        _require(value["architecture"] == _SOURCE_ARCHITECTURE
                 and value["model_type"] == "decoder_only", "preserved source/span decoder architecture required")
        _require(value["inputs"] == [{"name": "source_text", "data_type": "text", "dtype": "utf8"},
                 {"name": "source_representation", "data_type": "embeddings", "shape": [4096], "dtype": "float32"}]
                 and value["outputs"] == [{"name": "legal_ir", "data_type": "text", "dtype": "utf8"}],
                 "exact declared source-text plus4096 representation IO required")
    elif source_representation:
        _require(set(identity) == _IDENTITY_FIELDS | {"asset_binding_schema",
                 "source_representation_profile_id", "source_representation_profile_pin"},
                 "closed source-representation checkpoint identity required")
        _require(family == "legal_ir" and type(dimension) is int and dimension == 4096
                 and identity["dimension_role"] == "input_embedding",
                 "source representation requires exact legal_ir4096 input_embedding identity")
        _require(identity["profile_id"] is None and identity["format_id"] is None,
                 "source representation cannot claim a decoder format/profile")
        _require(config.get("complete_runtime_io_contract") is False,
                 "source representation runtime IO qualification must remain false")
        _require(any(spec["data_type"] == "embeddings" and spec.get("shape") in ([4096], [-1, 4096])
                 and spec.get("dtype") == "float32" for spec in value["inputs"]),
                 "source representation requires explicit float32 4096-wide embeddings input")
        profile_pin = _pin(identity.get("source_representation_profile_pin"),
                           min(max_reference_bytes, MAX_MANIFEST_BYTES))
        # Load only this versioned metadata validator, after byte-pinned JSON parsing.
        from .ir_decoder_profile_inventory import (DecoderProfileInventoryError,
            validate_ir_source_representation_profile)
        try:
            profile = validate_ir_source_representation_profile(_json(profile_pin))
        except DecoderProfileInventoryError as error:
            raise ModelManagerImportError("invalid source-representation profile") from error
        _require(identity.get("source_representation_profile_id") == profile["profile_id"],
                 "source-representation profile ID differs from pinned profile")
    elif component:
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
    if source:
        expected = ir_model_source_record_id_v2(family, identity["dimension_role"], identity["role"],
            checkpoint["sha256"], schema_version=identity["schema_version"], task_id=identity["task_id"],
            source_representation=identity["source_representation"])
        _require(record_id == expected, "deterministic source representation record_id required")
    elif source_representation:
        _require(record_id == ir_model_source_representation_record_id(identity["role"],
                 checkpoint["sha256"], identity["source_representation_profile_id"]),
                 "deterministic source-representation record_id required")
    elif component:
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


def _metadata_v2(value, checkpoint, *, max_reference_bytes=MAX_REFERENCE_BYTES):
    return _metadata(value, checkpoint, max_reference_bytes=max_reference_bytes, source_v2=True)


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


def _prepare(manifest_pin, release_receipts, maximum, *, schema=SCHEMA, metadata_validator=_metadata):
    _require(type(maximum) is int and 0 < maximum <= MAX_REFERENCE_BYTES, "reference byte cap required")
    manifest = _pin(_detached(manifest_pin), min(maximum, MAX_MANIFEST_BYTES))
    _require(type(release_receipts) in (list, tuple) and 1 <= len(release_receipts) <= MAX_MODELS,
             "explicit persisted publication receipt pins required")
    releases = [_pin(_detached(pin), min(maximum, MAX_MANIFEST_BYTES)) for pin in release_receipts]
    _require(len({pin["path"] for pin in releases}) == len(releases), "unique publication receipt paths required")
    plan = _json(manifest)
    _require(type(plan) is dict and set(plan) == {"schema", "models"} and plan["schema"] == schema,
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
        _require(type(record) is dict and {"model_metadata", "checkpoint_pin", "release"} <= set(record)
                 <= {"model_metadata", "checkpoint_pin", "release", "decoder_identity_witness"},
                 "closed model/checkpoint/release with optional decoder witness required")
        checkpoint = _pin(record["checkpoint_pin"], maximum)
        original = metadata_validator(record["model_metadata"], checkpoint, max_reference_bytes=maximum)
        identity = record["model_metadata"]["huggingface_config"]["ir_checkpoint"]
        if identity.get("asset_binding_schema") == SOURCE_REPRESENTATION_BINDING_SCHEMA:
            pins.append(_pin(identity["source_representation_profile_pin"],
                             min(maximum, MAX_MANIFEST_BYTES)))
        if identity.get("asset_binding_schema") == SOURCE_BINDING_SCHEMA:
            _, evidence = _source_representation(identity["source_representation"])
            pins.extend(_pin(pin, min(maximum, MAX_MANIFEST_BYTES)) for pin in evidence)
        if "decoder_identity_witness" in record:
            pins.append(_decoder_identity_witness(record["decoder_identity_witness"], identity,
                                                 record["model_metadata"], maximum))
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


def _matches(actual, expected, *, strict=False):
    actual = _stable_metadata(actual)
    expected = _stable_metadata(expected)
    if strict:
        return _raw(actual) == _raw(expected)
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
    return _import_prepared(plan, pins, manifest, releases, manager, readback, metadata_factory, RESULT_SCHEMA)


def import_ir_model_manager_records_v2(manifest_pin, *, release_receipts, manager, readback,
                                       metadata_factory=None, max_reference_bytes=MAX_REFERENCE_BYTES):
    """Register explicit source4096 metadata alongside unchanged legacy records.

    Historical native evidence is byte-checked, never executed or converted into
    a live capability. The separate twelve-cell inventory and runtime contracts
    are unchanged. Genuine persistence still belongs to the selected driver.
    """
    plan, pins, manifest, releases = _prepare(manifest_pin, release_receipts, max_reference_bytes,
        schema=SCHEMA_V2, metadata_validator=_metadata_v2)
    return _import_prepared(plan, pins, manifest, releases, manager, readback, metadata_factory, RESULT_SCHEMA_V2)


def _import_prepared(plan, pins, manifest, releases, manager, readback, metadata_factory, result_schema):
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
            _require(existing is None or _matches(existing, metadata, strict="decoder_identity_witness" in record), "existing model_id has conflicting metadata")
        _fence(pins)
        for record in plan["models"]:
            metadata = record["model_metadata"]
            model_id = metadata["model_id"]
            existing = manager.get_model(model_id)
            _require(existing is None or _matches(existing, metadata, strict="decoder_identity_witness" in record), "model_id changed to conflicting metadata")
            outcome = {"model_id": model_id, "checkpoint_sha256": record["checkpoint_pin"]["sha256"],
                "status": "pending", "already_present": existing is not None,
                "add_model_started": False, "add_model_returned": False, "add_model_result": None,
                "persisted_readback_started": False, "persisted_readback_returned": False,
                "persisted_metadata_matched": False}
            if "decoder_identity_witness" in record:
                outcome["decoder_identity_witness"] = _detached(record["decoder_identity_witness"])
                outcome["decoder_identity_witness_scope"] = "selected_registry_metadata_identity_consistency_only"
            outcomes.append(outcome)
            if existing is None:
                materialized = factory(_detached(metadata))
                _require(_matches(materialized, metadata, strict="decoder_identity_witness" in record), "metadata factory changed declared fields")
                _fence(pins)
                current = manager.get_model(model_id)
                _require(current is None or _matches(current, metadata, strict="decoder_identity_witness" in record),
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
            _require(persisted is not None and _matches(persisted, metadata, strict="decoder_identity_witness" in record), "fresh persisted metadata differs or is missing")
            outcome["persisted_metadata_matched"] = True
            outcome["status"] = "already_present_verified" if existing is not None else "registered_verified"
            _fence(pins)
        return _detached({"schema": result_schema, "manifest_receipt": manifest,
            "publication_receipts": releases, "outcomes": outcomes, "completed": True,
            "registered_count": sum(item["status"] == "registered_verified" for item in outcomes),
            "already_present_count": sum(item["status"] == "already_present_verified" for item in outcomes),
            "persisted_metadata_matched_count": len(outcomes),
            "readback_semantics": "Explicit driver-owned reopened-storage callable; adapter verifies returned fields, not its implementation.",
            "authority": {"registration_metadata_verified": True, "remote_independently_verified_by_adapter": False,
                "active_process_refreshed": False, "runtime_ready": False, "teacher_qualified": False,
                "proof_authority": False, "model_numerically_loaded": False, "model_quality_qualified": False,
                **(_SOURCE_FALSE if result_schema == RESULT_SCHEMA_V2 else {})}})
    except Exception as error:
        if isinstance(error, ModelManagerImportError):
            raise ModelManagerImportError(str(error), outcomes=outcomes) from error
        raise ModelManagerImportError("explicit manager registration/readback failed", outcomes=outcomes) from error


__all__ = ["ModelManagerImportError", "ir_model_asset_record_id", "ir_model_component_record_id",
           "ir_model_source_representation_record_id", "import_ir_model_manager_records",
           "ir_model_source_record_id_v2", "import_ir_model_manager_records_v2"]
