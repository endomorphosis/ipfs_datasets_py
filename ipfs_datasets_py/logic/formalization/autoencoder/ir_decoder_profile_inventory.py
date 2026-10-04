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
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import re

from . import ir_cell_routing as routing
from . import ir_cell_runtime as cached
from . import ir_decoder_format_runtime as formats


SCHEMA = "ir-decoder-profile-inventory/v1"
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


__all__ = ["SCHEMA", "DecoderProfileInventoryError", "build_ir_decoder_profile_inventory",
           "resolve_ir_decoder_profile_route"]
