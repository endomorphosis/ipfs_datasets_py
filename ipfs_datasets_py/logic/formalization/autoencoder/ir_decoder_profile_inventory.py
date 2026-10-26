"""Metadata-only decoder profiles and explicit checkpoint/run inventory.

The original twelve family/width declarations remain separate physical lanes.
Stable output-format and decoder-profile identities exclude concrete asset
locators, fitting corpora, weights and experiment labels. Concrete records keep
those bindings, including operator-assigned run aliases. This module neither
loads a decoder nor creates a database, remote repository or embedding.

Only the two preserved Intent/Security 384D original fragment contracts can be
registered. Other declared assets are hash-checked without deserialization;
verified initialization weights do not imply a supported or qualified runtime.
Resolution authenticates a pinned registry by rebuilding every record and all
twelve lanes from its embedded bindings. File reads and endpoint fences do not
establish an atomic snapshot, ongoing source currentness, or model authority.

A separate source-representation profile describes the expected LegalIR4096
producer. It neither changes those twelve cells nor registers a decoder format
or authenticates an encoder execution.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import importlib
import json
import math
import os
from pathlib import Path
import re
import stat

from . import ir_cell_routing as routing
from . import ir_cell_runtime as cached
from . import ir_decoder_format_runtime as formats


SCHEMA = "ir-decoder-profile-inventory/v1"
SOURCE_REPRESENTATION_SCHEMA = "ir-source-representation-profile/v1"
_SOURCE_PRODUCER_FIELDS = {"profile", "model_sha256", "worker_sha256", "worker_source_sha256",
    "owner_source_sha256", "vocabulary_owner_source_sha256", "library_sha256"}
_SOURCE_PRODUCER_PROFILES = {
    "leanstral4096:cpu1:last:l2:single-sequence:tokens512:lazy-mmap:v2",
    "leanstral4096:cpu1:last:l2:single-sequence:tokens512:layer-reclaim:v3",
}
_SOURCE_MODEL_SHA256 = "4668fd2a6d2764de250489852230e96238eb5c0d7495866eb3b9c6c4fac5c7da"
_SOURCE_AUTHORITY = {"source_producer_execution_authenticated": False,
    "source_vectors_verified": False, "checkpoint_compatible": False,
    "runtime_ready": False, "teacher_qualified": False, "proof_authority": False,
    "model_quality_qualified": False}
MAX_REFERENCE_BYTES = formats.MAX_REFERENCE_BYTES
MAX_BINDINGS = 256
_REQUEST_FIELDS = {"ir_family_id", "dimension", "dimension_role", "task_id", "checkpoint_sha256"}
_BINDING_FIELDS = {"request", "format_request", "package_manifest_pin", "corpus_pin", "run_id"}
_REGISTRY_FIELDS = {"schema", "directory_plan_receipt", "inventory_receipts", "bindings",
                    "cells", "formats", "profiles", "checkpoints", "authority", "consistency_scope"}
_EXPERIMENT_CONFIG = {"seed", "epochs", "batch_size", "learning_rate", "patience",
                      "reconstruction_weight", "max_seconds"}
_PRODUCER_OBSERVATIONS = {"elapsed_seconds_including_load", "vectors_executed"}
_SHAPE_FIELDS = ("projection_width", "hidden_size", "token_embedding_dim")
_RUN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_PROFILE = re.compile(r"ir-decoder-profile/v1:[0-9a-f]{64}\Z")
_AUTHORITY = {**formats._AUTHORITY, "registry_release_qualified": False,
    "original_training_run_authenticated": False, "tensor_shapes_verified": False,
    "numerical_model_loaded": False, "database_operations_executed": False,
    "remote_operations_executed": False}


class DecoderProfileInventoryError(cached.IRCellRuntimeError):
    """Malformed, unsupported, ambiguous, corrupt or changed metadata binding."""


def _require(condition, message):
    if not condition:
        raise DecoderProfileInventoryError(message)


def _id(prefix, identity):
    return prefix + hashlib.sha256(cached._raw(identity)).hexdigest()


def build_ir_source_representation_profile(producer):
    """Describe an expected LegalIR4096 producer without executing it.

    This independent metadata profile adds no cell or decoder format to the
    original twelve-lane inventory. Producer hashes are caller declarations,
    never native execution evidence. Library content digests exclude physical
    locators and retain multiplicity; a matching width or profile cannot issue
    the live capability required by the existing native embedding owner.
    """
    _require(type(producer) is dict and all(type(key) is str for key in producer)
             and set(producer) == _SOURCE_PRODUCER_FIELDS,
             "closed expected source4096 producer declaration required")
    _require(type(producer["profile"]) is str
             and producer["profile"] in _SOURCE_PRODUCER_PROFILES,
             "explicit supported Leanstral full-forward producer profile required")
    for key in _SOURCE_PRODUCER_FIELDS - {"profile", "library_sha256"}:
        _require(cached._hash(producer[key]), "exact declared producer SHA256 required: " + key)
    _require(producer["model_sha256"] == _SOURCE_MODEL_SHA256,
             "declared Leanstral model identity differs")
    libraries = producer["library_sha256"]
    _require(type(libraries) is list and 1 <= len(libraries) <= 63
             and all(cached._hash(value) for value in libraries),
             "one to 63 explicit native library content digests required")
    captured = {key: producer[key] for key in sorted(_SOURCE_PRODUCER_FIELDS - {"library_sha256"})}
    captured["library_sha256"] = sorted(libraries)
    identity = {"ir_family_id": "legal_ir", "dimension": 4096,
        "dimension_role": "input_embedding", "producer": captured,
        "source_text_policy": "exact_utf8_no_normalization",
        "maximum_source_utf8_bytes": 65536, "source_nul_policy": "reject",
        "pooling": "last", "normalization": "l2",
        "tokenizer_policy": "native-model-vocabulary:add-special:no-parse-special:no-chat-template:untruncated:tokens512",
        "maximum_source_tokens_including_special": 512}
    return {"schema": SOURCE_REPRESENTATION_SCHEMA,
        "profile_id": _id(SOURCE_REPRESENTATION_SCHEMA + ":", identity),
        "identity": identity, "scope": "declared_expected_source_producer_only",
        "authority": dict(_SOURCE_AUTHORITY)}


def validate_ir_source_representation_profile(profile):
    """Validate closed metadata; authenticate no native capability or model."""
    _require(type(profile) is dict and all(type(key) is str for key in profile)
             and set(profile) == {"schema", "profile_id", "identity", "scope", "authority"},
             "closed source representation profile required")
    identity = profile["identity"]
    _require(type(identity) is dict and all(type(key) is str for key in identity)
             and set(identity) == {"ir_family_id", "dimension", "dimension_role",
        "producer", "source_text_policy", "pooling", "normalization", "tokenizer_policy",
        "maximum_source_tokens_including_special", "maximum_source_utf8_bytes", "source_nul_policy"},
             "closed source representation identity required")
    # Exact builtins throughout prevent custom serializer callbacks and keep
    # booleans/floats distinct from the integer contracts.
    _require(type(profile["schema"]) is str and type(profile["profile_id"]) is str
             and type(profile["scope"]) is str and type(profile["authority"]) is dict
             and all(type(key) is str for key in profile["authority"])
             and set(profile["authority"]) == set(_SOURCE_AUTHORITY)
             and all(type(value) is bool for value in profile["authority"].values()),
             "exact source profile schema, ID, scope and boolean authority required")
    expected = build_ir_source_representation_profile(identity["producer"])
    for key in set(identity) - {"producer"}:
        _require(type(identity[key]) is type(expected["identity"][key]),
                 "exact source representation field type required: " + key)
    _require(profile == expected, "source representation profile identity or authority differs")
    return expected


def _maximum(value):
    _require(type(value) is int and 0 < value <= MAX_REFERENCE_BYTES,
             "reference byte cap must be within 1..512MiB")
    return value


def _request(value):
    _require(type(value) is dict and set(value) == _REQUEST_FIELDS,
             "closed five-field original decoder request required")
    _require(type(value["ir_family_id"]) is str and value["ir_family_id"] in formats._FORMATS
             and type(value["dimension"]) is int and value["dimension"] == 384
             and type(value["dimension_role"]) is str and value["dimension_role"] == "input_embedding"
             and type(value["task_id"]) is str and value["task_id"] == "source_to_native_ir"
             and cached._hash(value["checkpoint_sha256"]),
             "only explicit original Intent/Security source384 fragment checkpoints can be registered")
    return dict(value)


def _run(value):
    _require(type(value) is str and _RUN.fullmatch(value) is not None,
             "explicit bounded ASCII operator-assigned run alias required")
    return value


def _capture(directory_plan_pin, inventory_pins, bindings, maximum):
    maximum = _maximum(maximum)
    directory = routing._pin(directory_plan_pin, routing.MAX_MANIFEST_BYTES)
    _require(type(inventory_pins) in (list, tuple) and len(inventory_pins) == 12,
             "exactly twelve explicitly pinned original inventories required")
    inventories = [routing._pin(pin, routing.MAX_MANIFEST_BYTES) for pin in inventory_pins]
    _require(len({pin["path"] for pin in inventories}) == 12, "unique original inventory paths required")
    _require(type(bindings) is list and 1 <= len(bindings) <= MAX_BINDINGS,
             "one to 256 explicit decoder bindings required")
    captured = []
    for binding in bindings:
        _require(type(binding) is dict and set(binding) == _BINDING_FIELDS,
                 "closed request/format/package/corpus/run binding required")
        request = _request(binding["request"])
        captured.append({"request": request,
            "format_request": formats._format_request(binding["format_request"], request),
            "package_manifest_pin": routing._pin(binding["package_manifest_pin"], routing.MAX_MANIFEST_BYTES),
            "corpus_pin": routing._pin(binding["corpus_pin"], maximum),
            "run_id": _run(binding["run_id"])})
    # All supplied containers/primitive fields are closed-validated before any
    # preparation call. Serialize captured data to eliminate caller aliases.
    options = {"directory_plan_pin": directory,
        "inventory_pins": sorted(inventories, key=lambda pin: pin["path"]),
        "bindings": sorted(captured, key=cached._raw), "max_reference_bytes": maximum}
    return json.loads(cached._raw(options))


def _training_ids(corpus_pin):
    corpus = cached._json(corpus_pin, node_limit=4_000_000)
    rows = corpus.get("rows")
    _require(type(rows) is list and 1 <= len(rows) <= 4096
             and all(type(row) is dict for row in rows), "bounded original corpus rows required")
    identifiers = [row.get("id") for row in rows if row.get("split") == "train"]
    _require(1 <= len(identifiers) <= cached.MAX_SELECTED_ROWS
             and all(type(identifier) is str for identifier in identifiers),
             "one to 64 complete original fitting IDs required by the preserved replay API")
    return identifiers


def _format_identity(plan):
    contract = plan["format_contract"]
    return {"ir_family_id": contract["ir_family_id"],
        **dict(plan["format_request"]), "output_scope": contract["output_scope"],
        "target_kind": contract["target_kind"]}


def _profile_identity(plan, checkpoint, corpus, format_id):
    config = checkpoint["config"]
    clean = {key: deepcopy(value) for key, value in config.items() if key not in _EXPERIMENT_CONFIG}
    provenance = None
    if "embedding_provenance" in clean:
        _require(type(clean["embedding_provenance"]) is dict,
                 "declared embedding provenance must be an object")
        provenance = {key: deepcopy(value) for key, value in clean["embedding_provenance"].items()
                      if key not in _PRODUCER_OBSERVATIONS}
        clean["embedding_provenance"] = provenance
    shape = {"input_width": 384}
    for name in _SHAPE_FIELDS:
        value = config.get(name)
        _require(value is None or type(value) is int and 1 <= value <= 4096,
                 "bounded positive declared decoder shape required: " + name)
        shape[name] = value
    shape.update(status="declared_not_tensor_verified" if all(shape[name] is not None for name in _SHAPE_FIELDS)
                 else "unknown", tensor_shapes_verified=False)
    contract = plan["format_contract"]
    return {"format_id": format_id, "ir_family_id": contract["ir_family_id"],
        "dimension": 384, "dimension_role": "input_embedding",
        "decoder_architecture_id": checkpoint["architecture"],
        "ordered_codec_sha256": contract["canonical_codec_sha256"],
        "implementation_content_sha256": contract["implementation_declaration_sha256"],
        "format_implementation_content_sha256": contract["format_implementation_receipt"]["sha256"],
        "decoder_configuration": clean, "declared_shape": shape,
        "source_producer": {"corpus_embedding_model": corpus["embedding_model"],
            "corpus_embedding_revision": corpus["embedding_revision"],
            "embedding_provenance": provenance,
            "status": "declared_not_execution_authenticated" if provenance is not None else "unknown"},
        "source_budget_policy": deepcopy(plan["route"]["cell_declaration"]["dimension_profile"]),
        "target_budget_policy": {"max_target_tokens": config["max_target_tokens"],
                                 "qualified_target_token_limit": None}}


def _add_unique(collection, key, value):
    _require(key not in collection or cached._raw(collection[key]) == cached._raw(value),
             "conflicting canonical decoder identity")
    collection[key] = value


def _binding_plan(options, binding):
    replay = {"directory_plan_pin": options["directory_plan_pin"],
        "inventory_pins": options["inventory_pins"], "request": binding["request"],
        "format_request": binding["format_request"],
        "package_manifest_pin": binding["package_manifest_pin"], "corpus_pin": binding["corpus_pin"]}
    plan = formats.prepare_ir_decoder_format_runtime(**replay, corpus_split="train",
        row_ids=_training_ids(binding["corpus_pin"]), max_reference_bytes=options["max_reference_bytes"])
    checkpoint = cached._json(plan["format_contract"]["checkpoint_receipt"], node_limit=4_000_000)
    corpus = cached._json(binding["corpus_pin"], node_limit=4_000_000)
    return plan, checkpoint, corpus, replay


def _cells(options, records):
    cells = []
    for pin in options["inventory_pins"]:
        declaration = routing._manifest(pin)
        family, dimension = routing._cell_key(declaration)
        original_checkpoints = declaration["existing_checkpoint_evidence"]
        cached_vectors = declaration["existing_cached_vector_rows"]
        descriptor = declaration["huggingface"].get("existing_descriptor_source")
        checks = {
            "checkpoints": [routing._check_reference(row["receipt"]) for row in original_checkpoints],
            "cached_vectors": [routing._check_reference(row["receipt"]) for row in cached_vectors],
            "descriptor_source": None if descriptor is None else
                routing._check_reference(routing._pin(descriptor, options["max_reference_bytes"]))}
        registered = sorted(record["record_id"] for record in records
            if record["request"]["ir_family_id"] == family and record["request"]["dimension"] == dimension)
        cells.append({"cell_id": declaration["cell_id"], "ir_family_id": family,
            "dimension": dimension, "inventory_receipt": dict(pin),
            "storage_plan": deepcopy(declaration["storage"]),
            "huggingface_plan": deepcopy(declaration["huggingface"]),
            "original_declared_checkpoints": deepcopy(original_checkpoints),
            "reference_checks": checks, "registered_record_ids": registered,
            "binding_status": "registered_supported_formats" if registered else
                              "declared_only_no_supported_format_binding",
            "authority": dict(_AUTHORITY)})
    _require(len(cells) == 12 and len({(cell["ir_family_id"], cell["dimension"]) for cell in cells}) == 12,
             "all twelve unique original lanes required")
    return sorted(cells, key=lambda cell: (cell["ir_family_id"], cell["dimension"]))


def _endpoint_fence(registry):
    """Reobserve every required pin and declared availability, without owners.

    This closes changes after an earlier preparation or lane capture. Sequential
    reads still do not freeze ancestors or establish cross-file atomicity.
    """
    required = [registry["directory_plan_receipt"], *registry["inventory_receipts"]]
    for record in registry["checkpoints"]:
        required.extend([record["checkpoint_receipt"], record["package_manifest_receipt"],
                         record["corpus_receipt"], record["format_contract"]["format_implementation_receipt"]])
        required.extend(record["package_file_receipts"].values())
        required.extend(record["codec_source_receipts"])
    unique = {}
    for pin in required:
        _require(pin["path"] not in unique or unique[pin["path"]] == pin,
                 "conflicting endpoint receipts for one source path")
        unique[pin["path"]] = pin
    for path in sorted(unique):
        routing._read_pin(unique[path])
    for cell in registry["cells"]:
        checks = cell["reference_checks"]
        observed = [*checks["checkpoints"], *checks["cached_vectors"]]
        if checks["descriptor_source"] is not None:
            observed.append(checks["descriptor_source"])
        for check in observed:
            _require(routing._check_reference(check["receipt"]) == check,
                     "declared asset availability changed after lane capture")


def _build(options):
    format_records, profile_records, records, selected = {}, {}, [], set()
    for binding in options["bindings"]:
        plan, checkpoint, corpus, replay = _binding_plan(options, binding)
        format_identity = _format_identity(plan)
        format_id = _id("ir-decoder-format/v1:", format_identity)
        _add_unique(format_records, format_id, {"format_id": format_id, "identity": format_identity})
        profile_identity = _profile_identity(plan, checkpoint, corpus, format_id)
        profile_id = _id("ir-decoder-profile/v1:", profile_identity)
        _add_unique(profile_records, profile_id,
            {"profile_id": profile_id, "format_id": format_id, "identity": profile_identity})
        contract = plan["format_contract"]
        key = (profile_id, binding["run_id"], contract["checkpoint_receipt"]["sha256"])
        _require(key not in selected, "duplicate profile/run/explicit checkpoint binding")
        selected.add(key)
        record_identity = {"profile_id": profile_id, "format_id": format_id, "run_id": binding["run_id"],
            "checkpoint_receipt": contract["checkpoint_receipt"],
            "package_manifest_receipt": binding["package_manifest_pin"], "corpus_receipt": binding["corpus_pin"]}
        records.append({"record_id": _id("ir-decoder-checkpoint-record/v1:", record_identity),
            **record_identity, "run_id_provenance": "operator_assigned_inventory_alias",
            "request": deepcopy(binding["request"]), "format_request": deepcopy(binding["format_request"]),
            "format_contract": deepcopy(contract), "full_checkpoint_configuration": deepcopy(checkpoint["config"]),
            "package_file_receipts": deepcopy(plan["package_file_receipts"]),
            "codec_source_receipts": deepcopy(plan["codec_source_receipts"]),
            "training_manifest_sha256": contract["training_manifest_sha256"],
            "validation_manifest_sha256": contract["validation_manifest_sha256"],
            "declared_weights_sha256": checkpoint.get("weights_sha256"),
            "replay_binding_options": replay, "authority": dict(_AUTHORITY)})
    records.sort(key=lambda record: record["record_id"])
    cells = _cells(options, records)
    # Preserve only metadata, asset locators and digests. Plan inputs, original
    # source texts, target bodies, native evidence and vector rows are omitted.
    registry = {"schema": SCHEMA, "directory_plan_receipt": options["directory_plan_pin"],
        "inventory_receipts": options["inventory_pins"], "bindings": options["bindings"],
        "cells": cells, "formats": [format_records[key] for key in sorted(format_records)],
        "profiles": [profile_records[key] for key in sorted(profile_records)],
        "checkpoints": records, "authority": dict(_AUTHORITY), "consistency_scope": cached._SCOPE}
    _endpoint_fence(registry)
    return registry


def build_ir_decoder_profile_inventory(directory_plan_pin, inventory_pins, bindings, *,
        max_reference_bytes=MAX_REFERENCE_BYTES):
    """Build a detached inventory from explicit original fragment bindings.

    Run IDs are operator-assigned inventory aliases. A preserved fitting
    manifest authenticates its data association, not that alias as a historical
    training execution. Unregistered declared assets retain byte availability
    separately from supported-format capability and all quality authorities.
    """
    try:
        options = _capture(directory_plan_pin, inventory_pins, bindings, max_reference_bytes)
        return deepcopy(_build(options))
    except DecoderProfileInventoryError:
        raise
    except (routing.RoutingError, cached.IRCellRuntimeError) as error:
        raise DecoderProfileInventoryError(str(error)) from error
    except (TypeError, ValueError, KeyError, OverflowError, RecursionError) as error:
        raise DecoderProfileInventoryError("invalid decoder profile inventory binding") from error


def resolve_ir_decoder_profile_route(registry_pin, request, *, format_request,
        profile_id, run_id, max_reference_bytes=MAX_REFERENCE_BYTES):
    """Rebuild a pinned inventory and select one exact profile/run/checkpoint.

    The returned replay binding contains only original pins, the five-field
    request and the explicit format request. A caller must separately select
    its original corpus split/row IDs when using the existing format API.
    Resolution performs no numerical dispatch and makes no implicit selection.
    """
    try:
        maximum = _maximum(max_reference_bytes)
        request = _request(request)
        format_request = formats._format_request(format_request, request)
        _require(type(profile_id) is str and _PROFILE.fullmatch(profile_id) is not None,
                 "explicit canonical decoder profile ID required")
        run_id = _run(run_id)
        registry_pin = routing._pin(registry_pin, maximum)
        selection = json.loads(cached._raw({"registry_pin": registry_pin, "request": request,
            "format_request": format_request, "profile_id": profile_id, "run_id": run_id}))
        registry = cached._json(selection["registry_pin"], node_limit=4_000_000)
        _require(set(registry) == _REGISTRY_FIELDS and registry["schema"] == SCHEMA,
                 "closed versioned decoder profile inventory required")
        rebuilt = build_ir_decoder_profile_inventory(registry["directory_plan_receipt"],
            registry["inventory_receipts"], registry["bindings"], max_reference_bytes=maximum)
        _require(cached._raw(registry) == cached._raw(rebuilt),
                 "registry claims differ from complete authenticated rebuild")
        matches = [record for record in rebuilt["checkpoints"]
            if record["profile_id"] == selection["profile_id"] and record["run_id"] == selection["run_id"]
            and record["request"] == selection["request"] and record["format_request"] == selection["format_request"]]
        _require(len(matches) == 1, "exact format/profile/run/checkpoint selection is unavailable or ambiguous")
        checkpoint = matches[0]
        profiles = [value for value in rebuilt["profiles"] if value["profile_id"] == checkpoint["profile_id"]]
        format_records = [value for value in rebuilt["formats"] if value["format_id"] == checkpoint["format_id"]]
        _require(len(profiles) == len(format_records) == 1, "unique selected profile and format required")
        # Reobserve sources/assets after selection, then fence the registry.
        _endpoint_fence(rebuilt)
        routing._read_pin(selection["registry_pin"])
        return deepcopy({"schema": "ir-decoder-profile-route/v1", "registry_receipt": selection["registry_pin"],
            "request": selection["request"], "format_request": selection["format_request"],
            "selected_format": format_records[0], "selected_profile": profiles[0],
            "selected_checkpoint": checkpoint, "replay_binding_options": checkpoint["replay_binding_options"],
            "authority": dict(_AUTHORITY), "consistency_scope": cached._SCOPE})
    except DecoderProfileInventoryError:
        raise
    except (routing.RoutingError, cached.IRCellRuntimeError) as error:
        raise DecoderProfileInventoryError(str(error)) from error
    except (TypeError, ValueError, KeyError, OverflowError, RecursionError) as error:
        raise DecoderProfileInventoryError("invalid decoder profile route binding") from error


__all__ = ["SCHEMA", "SOURCE_REPRESENTATION_SCHEMA", "DecoderProfileInventoryError",
           "build_ir_source_representation_profile", "validate_ir_source_representation_profile",
           "build_ir_decoder_profile_inventory", "resolve_ir_decoder_profile_route"]


# An independent declared shape contract. It does not enter the twelve-cell
# registry, authenticate conditioning, allocate tensors or create a checkpoint.
COUNTED_HEAD_SPEC_SCHEMA = "legal-counted-content-head-spec/v1"
COUNTED_HEAD_SPEC_PROFILE = "declared-counted28-content-head-384/v1"
MAX_COUNTED_HEAD_SPEC_BYTES = 65536
_COUNTED_HEAD_SELF_PATH = Path(__file__).absolute()
_COUNTED_HEAD_SELF_SHA = hashlib.sha256(_COUNTED_HEAD_SELF_PATH.read_bytes()).hexdigest()
_COUNTED_HEAD_OWNER_SHA = "8e32341e5962c01193ec46313011b83ba67b340a8996f866e417b10179b5c021"
_COUNTED_CODEC_OWNER_SHA = "df91798d11e2b0da36afc75e0bc1a8b6d0a3d08bc255e7362d1c200e5e9baa13"
_COUNTED_CODEC_SHA = "8a1e8e0f8c6c2259b7c1040d3518974b1c84ac6d532521199f46a76b7d78dcd8"
_COUNTED_HEAD_GEOMETRY = {"hidden_size": (32, 8, 128), "token_embedding_dim": (16, 8, 64),
                          "projection_width": (16, 1, 64)}
_COUNTED_HEAD_LEXICAL = ("target_embedding.weight", "output.weight", "output.bias")
_COUNTED_HEAD_STATE_KEYS = {
    "projection_down.weight", "projection_down.bias", "projection_up.weight", "projection_up.bias",
    "condition.weight", "condition.bias", "target_embedding.weight", "decoder.weight_ih_l0",
    "decoder.weight_hh_l0", "decoder.bias_ih_l0", "decoder.bias_hh_l0", "output.weight", "output.bias",
}
_COUNTED_HEAD_FALSE = dict.fromkeys(("runtime_ready", "checkpoint_compatible", "tensor_shapes_verified",
    "numerical_model_loaded", "model_executed", "training_executed", "training_qualified",
    "permitted_inference_context_verified", "conditioning_space_training_compatibility_verified",
    "varied_reviewed_target_population_verified", "source_semantics_verified", "proof_authority",
    "accepted", "admitted", "Lean_admitted"), False)
_COUNTED_HEAD_LIMITATIONS = [
    "This is a checkpoint-free declared shape specification, not an instantiated or trained numerical head.",
    "Only three lexical first dimensions change from537 to28; no old checkpoint, weights, optimizer or lexical transfer is accepted.",
    "The fixed counted codec supports complete sequences only. No counted allowed-prefix, score-selection or generation runtime is supplied.",
    "Raw native GTE384 is an expected input-space declaration; source receipts, permitted source-only context and training-space compatibility are not authenticated.",
    "One fixed authored counted target is not a varied reviewed training population or evidence of learned source dependence, legal meaning or convergence.",
    "Named source and sequential input fences do not attest loaded bytecode, third-party libraries, an atomic snapshot or a hermetic runtime.",
]


def _counted_head_copy(value, maximum=MAX_COUNTED_HEAD_SPEC_BYTES):
    remaining, budget, active = 20000, maximum, set()

    def visit(item, depth):
        nonlocal remaining, budget
        remaining -= 1
        _require(remaining >= 0 and depth <= 32, "bounded counted head metadata structure required")
        if type(item) in (dict, list):
            _require(id(item) not in active and len(item) <= remaining, "cyclic or oversized counted metadata refused")
            active.add(id(item))
            try:
                budget -= 2 + max(0, len(item) - 1)
                if type(item) is dict:
                    _require(all(type(key) is str for key in item), "ordinary counted metadata keys required")
                    budget -= len(item)
                    result = {visit(key, depth + 1): visit(child, depth + 1) for key, child in item.items()}
                else:
                    result = [visit(child, depth + 1) for child in item]
            finally:
                active.remove(id(item))
        elif type(item) is str:
            _require(len(item) <= maximum, "bounded counted metadata text required")
            budget -= 2
            for char in item:
                code = ord(char)
                _require(code != 0 and not 0xD800 <= code <= 0xDFFF, "ordinary scalar UTF8 metadata required")
                budget -= (2 if char in '\"\\\b\f\n\r\t' else 6 if code < 32 else
                           1 if code < 128 else 2 if code < 2048 else 3 if code < 65536 else 4)
                _require(budget >= 0, "complete counted metadata byte bound exceeded")
            result = item
        elif item is None or type(item) is bool:
            budget -= 4 if item is None or item is True else 5
            result = item
        elif type(item) is int:
            _require(-(1 << 63) < item < (1 << 63), "bounded plain counted metadata integer required")
            budget -= len(str(item))
            result = item
        else:
            raise DecoderProfileInventoryError("ordinary counted metadata without floats required")
        _require(budget >= 0, "complete counted metadata byte bound exceeded")
        return result

    return visit(value, 0)


def _counted_head_wire(value):
    captured = _counted_head_copy(value)
    raw = json.dumps(captured, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                     allow_nan=False).encode()
    _require(len(raw) <= MAX_COUNTED_HEAD_SPEC_BYTES, "complete counted head metadata bound exceeded")
    return raw


def _counted_head_config(config):
    _require(config is None or type(config) is dict and
             all(type(key) is str for key in config) and set(config) <= set(_COUNTED_HEAD_GEOMETRY),
             "only declared H/E/P geometry fields are accepted")
    result = {name: default for name, (default, _, _) in _COUNTED_HEAD_GEOMETRY.items()}
    result.update(config or {})
    for name, (_, low, high) in _COUNTED_HEAD_GEOMETRY.items():
        _require(type(result[name]) is int and low <= result[name] <= high,
                 "bounded plain integer counted head geometry required: " + name)
    return result


def _counted_head_preflight(codec, expected_codec_sha256, config):
    _require(type(expected_codec_sha256) is str and expected_codec_sha256 == _COUNTED_CODEC_SHA,
             "independent selected counted28 codec pin required")
    geometry = _counted_head_config(config)
    _require(type(codec) is dict and hashlib.sha256(_counted_head_wire(codec)).hexdigest() == expected_codec_sha256,
             "complete independently pinned counted28 codec differs")
    return geometry


def _counted_head_source(path, expected):
    _require(path.is_absolute() and path.resolve(strict=True) == path, "canonical unaliased known producer required")
    before = path.lstat()
    _require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and 0 < before.st_size <= 4 * 1024**2,
             "bounded regular known producer source required")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        opened = os.fstat(fd)
        with os.fdopen(fd, 'rb', closefd=False) as stream:
            raw = stream.read(before.st_size + 1)
        closed = os.fstat(fd)
    finally:
        os.close(fd)
    after = path.lstat()
    identity = lambda item: (item.st_dev, item.st_ino, item.st_size, item.st_mtime_ns, item.st_ctime_ns)
    _require(identity(before) == identity(opened) == identity(closed) == identity(after)
             and len(raw) == before.st_size and hashlib.sha256(raw).hexdigest() == expected,
             "known counted head producer source changed")
    return expected


def _counted_head_sources():
    package = _COUNTED_HEAD_SELF_PATH.parents[3]
    paths = {
        'logic/formalization/autoencoder/ir_decoder_profile_inventory.py': (_COUNTED_HEAD_SELF_PATH, _COUNTED_HEAD_SELF_SHA),
        'logic/formalization/autoencoder/legal_compact_content_head_v1.py': (_COUNTED_HEAD_SELF_PATH.with_name('legal_compact_content_head_v1.py'), _COUNTED_HEAD_OWNER_SHA),
        'logic/autoformal/legal_counted_frame_v1.py': (package / 'logic/autoformal/legal_counted_frame_v1.py', _COUNTED_CODEC_OWNER_SHA),
    }
    return {name: _counted_head_source(path, expected) for name, (path, expected) in paths.items()}


def _counted_head_owners():
    pins = _counted_head_sources()
    names = ('ipfs_datasets_py.logic.autoformal.legal_counted_frame_v1',
             'ipfs_datasets_py.logic.formalization.autoencoder.legal_compact_content_head_v1')
    owners = tuple(importlib.import_module(name) for name in names)
    _counted_head_origins(owners)
    _require(_counted_head_sources() == pins, "counted head sources changed during pure owner import")
    return owners, pins


def _counted_head_origins(owners):
    package = _COUNTED_HEAD_SELF_PATH.parents[3]
    expected = (package / 'logic/autoformal/legal_counted_frame_v1.py',
                _COUNTED_HEAD_SELF_PATH.with_name('legal_compact_content_head_v1.py'))
    for owner, path in zip(owners, expected):
        _require(type(getattr(owner, '__file__', None)) is str and Path(owner.__file__).absolute() == path,
                 "known canonical counted head operation owner origin required")


def _counted_head_fence(pins, original, captured, commitment, owners):
    _require(_counted_head_wire(original) == commitment and _counted_head_wire(captured) == commitment,
             "counted head original or captured inputs changed")
    _counted_head_origins(owners)
    _require(_counted_head_sources() == pins, "counted head producers changed")
    _counted_head_origins(owners)


def _counted_head_layout(head, geometry):
    _require(head.DIMENSION == 384 and head.VOCABULARY_SIZE == 537 and head.MAX_SEQUENCE_TOKENS == 512
             and head.ARCHITECTURE == 'residual-projection-latent-formula-gru/v1',
             "original fixed537 head shape declaration differs")
    captured_geometry = _counted_head_copy(geometry)
    geometry_token = _counted_head_wire(captured_geometry)
    original = head._shapes(captured_geometry)
    _require(_counted_head_wire(geometry) == geometry_token and
             _counted_head_wire(captured_geometry) == geometry_token,
             "declared counted geometry changed during original layout call")
    _require(type(original) is dict and set(original) == _COUNTED_HEAD_STATE_KEYS,
             "complete original thirteen-tensor layout required")
    shapes, changes = {}, []
    for name, dimensions in original.items():
        _require(type(name) is str and type(dimensions) is tuple and 1 <= len(dimensions) <= 2
                 and all(type(item) is int and 0 < item <= 537 for item in dimensions),
                 "bounded original declared tensor shape required")
        shapes[name] = list(dimensions)
    for name in _COUNTED_HEAD_LEXICAL:
        _require(shapes[name][0] == 537, "original lexical first dimension must be537")
        before = list(shapes[name])
        shapes[name][0] = 28
        changes.append({'tensor': name, 'axis': 0, 'before': before, 'after': list(shapes[name])})
    return shapes, changes


def build_counted_content_head_spec_v1(codec, *, expected_codec_sha256, config=None):
    """Declare a counted28 layout without weights, model calls or registration."""
    original = {'codec': codec, 'config': config}
    captured = _counted_head_copy(original)
    commitment = _counted_head_wire(captured)
    geometry = _counted_head_preflight(captured['codec'], expected_codec_sha256, captured['config'])
    owners, pins = _counted_head_owners()
    counted, head = owners
    fence = lambda: _counted_head_fence(pins, original, captured, commitment, owners)
    fence()
    fixed = counted.build_counted_frame_token_codec_v1()
    _require(counted.counted_frame_token_codec_sha256(fixed) == expected_codec_sha256
             and _counted_head_wire(fixed) == _counted_head_wire(captured['codec']),
             "actual public counted28 codec differs")
    fence()
    shapes, changes = _counted_head_layout(head, geometry)
    fence()
    parameters = sum(math.prod(shape) for shape in shapes.values())
    identity = {'profile': COUNTED_HEAD_SPEC_PROFILE, 'ir_family_id': 'legal_ir',
        'task_id': 'conditioning_to_counted_frame_content', 'architecture': head.ARCHITECTURE,
        'device': 'cpu', 'dtype': 'float32',
        'input': {'dimension': 384, 'dimension_role': 'input_embedding',
            'space': 'raw_native_gte_small384', 'conditioning_schema': 'legal-compact-source-conditioning/v1',
            'conditioning_profile': 'exact-native-gte-small384-receipt-reuse/v1',
            'model': 'thenlper/gte-small', 'revision': '17e1f347d17fe144873b1201da91788898c639cd',
            'asset_manifest_sha256': 'def8d7e04c05560b1d0dd1fa9317be7a59a1ba8399ca725be0ac807a9a264edc'},
        'codec': fixed, 'codec_sha256': expected_codec_sha256, 'max_total_ids': 512,
        'geometry': geometry, 'tensor_shapes': shapes, 'lexical_shape_changes': changes,
        'parameter_count': parameters, 'parameter_bytes': parameters * 4,
        'layout_owner_source_sha256': _COUNTED_HEAD_OWNER_SHA, 'codec_owner_source_sha256': _COUNTED_CODEC_OWNER_SHA}
    report = {'schema': COUNTED_HEAD_SPEC_SCHEMA,
        'spec_id': COUNTED_HEAD_SPEC_SCHEMA + ':' + hashlib.sha256(_counted_head_wire(identity)).hexdigest(),
        'identity': identity, 'producer_pins': pins, 'scope': 'declared_checkpoint_free_counted_head_spec_only',
        'runtime_compatible': False, 'tensor_shapes_verified': False, 'checkpoint_compatible': False,
        'prefix_api_available': False, 'permitted_source_only_context': False,
        'varied_reviewed_targets_supplied': False, 'authority': dict(_COUNTED_HEAD_FALSE),
        'training_mask': 0, 'evaluation_gold_mask': 0, 'model_calls': 0, 'training_calls': 0,
        'limitations': list(_COUNTED_HEAD_LIMITATIONS)}
    raw = _counted_head_wire(report)
    fence()
    return json.loads(raw)


def counted_content_head_spec_sha256(spec):
    """Hash bounded metadata only; perform no owner, model or runtime import."""
    _counted_head_source(_COUNTED_HEAD_SELF_PATH, _COUNTED_HEAD_SELF_SHA)
    result = hashlib.sha256(_counted_head_wire(spec)).hexdigest()
    _counted_head_source(_COUNTED_HEAD_SELF_PATH, _COUNTED_HEAD_SELF_SHA)
    return result


def validate_counted_content_head_spec_v1(spec, codec, *, expected_spec_sha256,
                                          expected_codec_sha256, config=None):
    """Require independent complete pins and regeneration from original config."""
    _require(cached._hash(expected_spec_sha256), "independent counted head spec pin required")
    original = {'spec': spec, 'codec': codec, 'config': config}
    captured = _counted_head_copy(original)
    commitment = _counted_head_wire(captured)
    _require(hashlib.sha256(_counted_head_wire(captured['spec'])).hexdigest() == expected_spec_sha256,
             "independently pinned complete counted head spec differs")
    _counted_head_preflight(captured['codec'], expected_codec_sha256, captured['config'])
    owners, pins = _counted_head_owners()
    fence = lambda: _counted_head_fence(pins, original, captured, commitment, owners)
    fence()
    regenerated = build_counted_content_head_spec_v1(captured['codec'],
        expected_codec_sha256=expected_codec_sha256, config=captured['config'])
    fence()
    _require(_counted_head_wire(captured['spec']) == _counted_head_wire(regenerated),
             "counted head spec differs from original public regeneration")
    raw = _counted_head_wire(regenerated)
    fence()
    return json.loads(raw)


__all__ += ['COUNTED_HEAD_SPEC_SCHEMA', 'COUNTED_HEAD_SPEC_PROFILE',
            'build_counted_content_head_spec_v1', 'counted_content_head_spec_sha256',
            'validate_counted_content_head_spec_v1']


# A transfer declaration composes the existing public spec; it builds no head.
COUNTED_HEAD_TRANSFER_SCHEMA = 'legal-counted-content-head-transfer-plan/v1'
_COUNTED_TRANSFER_DONOR_SCHEMA = 'legal-counted-content-head-donor-declaration/v1'
_COUNTED_TRANSFER_FALSE = {**_COUNTED_HEAD_FALSE, **dict.fromkeys((
    'donor_checkpoint_validated', 'donor_tensors_validated', 'weights_transferred',
    'conditioning_space_compatible', 'source_dependence_established',
    'varied_training_population_supplied', 'optimizer_continuation_supported',
), False)}
_COUNTED_TRANSFER_LIMITATIONS = [
    'This is a declared transfer plan over a genuinely regenerated checkpoint-free head spec, not a checkpoint, tensor restore, numerical head or executed transfer.',
    'Donor hashes, vocabulary, geometry, runtime and conditioning space are caller declarations only. No donor asset path or weight body is accepted or opened.',
    'The unchanged head owner supplies the exact token-spelling map. Copied rows and donor lexical-row means are requested initialization policies, not learned counted meaning.',
    'Matching conditioning declarations do not prove the same latent space. Raw native GTE384, authored sparse vectors and unverified384 declarations remain distinct.',
    'Any actual transfer requires independent complete donor validation and a fresh optimizer; no donor Adam state or exact optimizer continuation is authorized.',
    'The counted profile admits one fixed content tree and context. Archive-ID variants and constrained complete output provide no varied target population or learned source-dependence evidence.',
    'No counted prefix, numerical serving, training implementation, permitted source-only context, reviewed complete statutory target, legal accuracy or Lean admission is supplied.',
    'Named source and sequential input fences preserve the stated metadata generation, not arbitrary bytecode, runtime binaries, a hermetic environment or atomic cross-file state.',
]


def _counted_transfer_donor(value):
    fields = {'schema', 'profile', 'architecture', 'input_dimension', 'input_role', 'geometry',
              'checkpoint_sha256', 'weights_sha256', 'vocabulary', 'vocabulary_sha256',
              'torch_version', 'conditioning_profile'}
    _require(type(value) is dict and set(value) == fields,
             'closed declared donor metadata required for counted transfer')
    _require(value['schema'] == _COUNTED_TRANSFER_DONOR_SCHEMA
             and value['architecture'] == 'residual-projection-latent-formula-gru/v1'
             and type(value['input_dimension']) is int and value['input_dimension'] == 384
             and value['input_role'] == 'caller_supplied_conditioning_vector',
             'declared384 residual-GRU donor contract required')
    for key in ('profile', 'torch_version', 'conditioning_profile'):
        _require(type(value[key]) is str and 0 < len(value[key]) <= 256 and bool(value[key].strip()),
                 'bounded ordinary donor declaration text required: ' + key)
    for key in ('checkpoint_sha256', 'weights_sha256', 'vocabulary_sha256'):
        _require(type(value[key]) is str and cached._hash(value[key]),
                 'plain declared donor SHA256 required: ' + key)
    _require(type(value['geometry']) is dict and set(value['geometry']) == set(_COUNTED_HEAD_GEOMETRY),
             'complete original donor H/E/P geometry required')
    _counted_head_config(value['geometry'])
    vocabulary = value['vocabulary']
    _require(type(vocabulary) is list and 4 <= len(vocabulary) <= 4096
             and all(type(token) is str and 0 < len(token) <= 4096 for token in vocabulary)
             and vocabulary[:3] == ['<pad>', '<bos>', '<eos>']
             and len(set(vocabulary)) == len(vocabulary),
             'bounded unique complete declared donor vocabulary required')
    _require(hashlib.sha256(_counted_head_wire(vocabulary)).hexdigest() == value['vocabulary_sha256'],
             'independent declared donor vocabulary SHA256 differs')
    return value


def _counted_transfer_roles(name):
    if name.startswith('projection_down.'):
        return 'residual_projection_down'
    if name.startswith('projection_up.'):
        return 'residual_projection_up'
    if name.startswith('condition.'):
        return 'conditioning_to_initial_GRU_state'
    if name == 'target_embedding.weight':
        return 'target_token_embedding'
    if name.startswith('output.'):
        return 'target_token_logits'
    return 'single_layer_GRU_recurrence'


def plan_counted_content_head_transfer_v1(spec, codec, *, expected_spec_sha256,
                                         expected_codec_sha256, donor_declaration, config=None):
    """Compose the public counted head spec and a bounded unverified donor ledger."""
    _require(type(expected_spec_sha256) is str and cached._hash(expected_spec_sha256)
             and type(expected_codec_sha256) is str and cached._hash(expected_codec_sha256),
             'independent plain spec and codec SHA256 pins required')
    original = {'spec': spec, 'codec': codec, 'donor': donor_declaration, 'config': config,
                'expected_spec_sha256': expected_spec_sha256, 'expected_codec_sha256': expected_codec_sha256}
    captured = _counted_head_copy(original)
    commitment = _counted_head_wire(captured)
    donor = _counted_transfer_donor(captured['donor'])
    # Public validation genuinely regenerates the complete prior spec and codec.
    checked = validate_counted_content_head_spec_v1(captured['spec'], captured['codec'],
        expected_spec_sha256=expected_spec_sha256, expected_codec_sha256=expected_codec_sha256,
        config=captured['config'])
    checked_commitment = _counted_head_wire(checked)
    _require(checked_commitment == _counted_head_wire(captured['spec']),
             'public head spec validation changed the independently committed original spec')
    owners, pins = _counted_head_owners()
    def fence():
        _counted_head_fence(pins, original, captured, commitment, owners)
        _require(_counted_head_wire(checked) == checked_commitment,
                 'captured original head spec changed during transfer planning')
    fence()
    geometry = checked['identity']['geometry']
    _require(_counted_head_wire(donor['geometry']) == _counted_head_wire(geometry),
             'declared donor H/E/P geometry must match the original spec')
    counted, head = owners
    shapes = checked['identity']['tensor_shapes']
    # The peer public spec owns all thirteen formulas. Only declared lexical
    # first dimensions are replaced to describe the prospective donor shapes.
    donor_shapes = _counted_head_copy(shapes)
    for name in _COUNTED_HEAD_LEXICAL:
        donor_shapes[name][0] = len(donor['vocabulary'])
    vocabulary = checked['identity']['codec']['vocabulary']
    mapping = head._token_rows(vocabulary, donor['vocabulary'])
    fence()
    _require(type(mapping) is list and len(mapping) == 28,
             'complete unchanged head token-row map required')
    ledger = [{'parameter': name, 'target_shape': shape, 'declared_donor_shape': donor_shapes[name],
        'semantic_role': _counted_transfer_roles(name), 'fit_policy': 'unprovided',
        'disposition': 'declared_lexical_remap_if_future_validated' if name in _COUNTED_HEAD_LEXICAL
            else 'declared_copy_if_future_validated',
        'initializer': 'head_owner_exact_token_rows_else_donor_lexical_row_mean' if name in _COUNTED_HEAD_LEXICAL
            else 'exact_nonlexical_copy_required_not_executed'}
        for name, shape in shapes.items()]
    target_space = checked['identity']['input']['space']
    known = {'raw_native_gte_small384', 'authored_sparse384'}
    relation = ('unknown' if donor['conditioning_profile'] not in known or target_space not in known
                else 'matching' if donor['conditioning_profile'] == target_space else 'different')
    identity = {'profile': 'declared-counted28-head-transfer-384/v1',
        'spec_sha256': expected_spec_sha256, 'codec_sha256': expected_codec_sha256,
        'donor_declaration_sha256': hashlib.sha256(_counted_head_wire(donor)).hexdigest(),
        'target_conditioning_space': target_space, 'declared_donor_conditioning_space': donor['conditioning_profile'],
        'geometry': geometry, 'tensor_ledger': ledger, 'lexical_row_map': mapping,
        'declared_conditioning_relation': relation}
    result = {'schema': COUNTED_HEAD_TRANSFER_SCHEMA,
        'plan_id': COUNTED_HEAD_TRANSFER_SCHEMA + ':' + hashlib.sha256(_counted_head_wire(identity)).hexdigest(),
        'identity': identity, 'spec': checked, 'spec_sha256': expected_spec_sha256,
        'codec_sha256': expected_codec_sha256, 'donor_declaration': donor,
        'donor_declaration_sha256': identity['donor_declaration_sha256'],
        'target_conditioning_space': target_space, 'declared_conditioning_relation': relation,
        'tensor_ledger': ledger, 'lexical_row_map': mapping,
        'donor_validation_scope': 'bounded_caller_declaration_only',
        'optimizer_policy': {'fresh_required': True, 'inherit_donor_state': False,
                             'exact_Adam_continuation_supported': False, 'optimizer_created': False},
        'fixed_language': {'admissible_content_count': 1, 'admissible_context_count': 1,
                          'varied_target_population': False, 'source_dependence_established': False},
        'implementation_readiness': {'numerical_head_implemented': False, 'prefix_api_implemented': False,
                                     'serving_implemented': False, 'trainer_implemented': False},
        'unresolved': {'source_context_permission': 'unprovided', 'conditioning_space_compatibility': 'unprovided',
            'reviewed_varied_target_population': 'unprovided', 'complete_statutory_target': None},
        'producer_pins': pins, 'authority': dict(_COUNTED_TRANSFER_FALSE),
        'training_mask': 0, 'evaluation_gold_mask': 0, 'model_calls': 0, 'transfer_calls': 0,
        'training_calls': 0, 'limitations': list(_COUNTED_TRANSFER_LIMITATIONS)}
    raw = _counted_head_wire(result)
    fence()
    return json.loads(raw)


def counted_content_head_transfer_sha256(plan):
    """Hash bounded transfer metadata only; no donor or model is authenticated."""
    _counted_head_source(_COUNTED_HEAD_SELF_PATH, _COUNTED_HEAD_SELF_SHA)
    result = hashlib.sha256(_counted_head_wire(plan)).hexdigest()
    _counted_head_source(_COUNTED_HEAD_SELF_PATH, _COUNTED_HEAD_SELF_SHA)
    return result


def validate_counted_content_head_transfer_v1(plan, spec, codec, *, expected_plan_sha256,
        expected_spec_sha256, expected_codec_sha256, donor_declaration, config=None):
    """Bind the complete offered plan and repeat all original metadata operations."""
    _require(type(expected_plan_sha256) is str and cached._hash(expected_plan_sha256),
             'independent complete counted transfer plan SHA256 required')
    _require(type(expected_spec_sha256) is str and cached._hash(expected_spec_sha256)
             and type(expected_codec_sha256) is str and cached._hash(expected_codec_sha256),
             'independent plain original spec and codec SHA256 pins required')
    original = {'plan': plan, 'spec': spec, 'codec': codec, 'donor': donor_declaration, 'config': config}
    captured = _counted_head_copy(original)
    commitment = _counted_head_wire(captured)
    _require(hashlib.sha256(_counted_head_wire(captured['plan'])).hexdigest() == expected_plan_sha256,
             'independently pinned counted transfer plan differs')
    owners, pins = _counted_head_owners()
    fence = lambda: _counted_head_fence(pins, original, captured, commitment, owners)
    fence()
    regenerated = plan_counted_content_head_transfer_v1(captured['spec'], captured['codec'],
        expected_spec_sha256=expected_spec_sha256, expected_codec_sha256=expected_codec_sha256,
        donor_declaration=captured['donor'], config=captured['config'])
    fence()
    _require(_counted_head_wire(captured['plan']) == _counted_head_wire(regenerated),
             'counted transfer plan differs from complete original metadata regeneration')
    raw = _counted_head_wire(regenerated)
    fence()
    return json.loads(raw)


__all__ += ['COUNTED_HEAD_TRANSFER_SCHEMA', 'plan_counted_content_head_transfer_v1',
            'counted_content_head_transfer_sha256', 'validate_counted_content_head_transfer_v1']
