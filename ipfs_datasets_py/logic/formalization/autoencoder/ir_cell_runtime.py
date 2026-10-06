"""Opt-in experimental replay of authenticated, existing 384D cached rows.

Preparation reads metadata and hashes assets; it never imports numerical owners.
Opening calls the fixed existing Hub loader only after preparation. Legal loading
may run its stored numerical fixture. Neither loading nor cached replay qualifies
model quality, teachers, spans, producers, proof, stores, or a runtime release.
Per-file fences and endpoint rechecks are not atomic cross-file/currentness locks.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import re

from . import checkpoint_hub as hub
from . import ir_cell_routing as routing


SCHEMA = "ir-cell-cached-runtime-plan/v1"
MAX_REFERENCE_BYTES = routing.MAX_REFERENCE_BYTES
MAX_ROWS = 4096
MAX_SELECTED_ROWS = 64
_FAMILIES = ("legal_ir", "security_ir", "intent_ir")
_SPLITS = ("train", "validation", "test", "canary")
_ROW_FIELDS = {"id", "source_text", "source_sha256", "embedding", "embedding_sha256",
               "embedding_token_ids_sha256", "group_id", "split", "target", "wording_style"}
_REQUEST_FIELDS = {"ir_family_id", "dimension", "dimension_role", "task_id", "checkpoint_sha256"}
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_AUTHORITY = dict(runtime_admitted=False, runtime_release_qualified=False,
    model_task_qualified=False, quality_qualified=False, teacher_qualified=False,
    source_token_budget_qualified=False, source_free_reconstruction_qualified=False,
    embedding_producer_execution_authenticated=False, source_semantics_verified=False,
    proof_authority=False, training_admitted=False, training_executed=False,
    promotion_admitted=False, physical_cell_store_qualified=False, store_available=False,
    huggingface_available=False, full_source_dependency_closure_qualified=False)
_SCOPE = ("Stable bounded per-file reads and repeated endpoint equality; no atomic "
          "cross-file snapshot, continuous source currentness, universal ancestor "
          "containment, decoder numerical qualification, or serving-head admission.")


class IRCellRuntimeError(ValueError):
    """Invalid experimental replay binding, unavailable bytes, or changed inputs."""


def _require(condition, message):
    if not condition:
        raise IRCellRuntimeError(message)


def _raw(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _text(value, maximum, name):
    _require(type(value) is str and 0 < len(value) <= maximum and value.strip(), name + " required")
    try:
        return value.encode("utf-8")
    except UnicodeError as error:
        raise IRCellRuntimeError(name + " must be exact UTF8") from error


def _hash(value):
    return type(value) is str and _SHA.fullmatch(value) is not None


def _json(pin, *, node_limit):
    raw = routing._read_pin(pin, retain=True)
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=routing._pairs,
                           parse_float=routing._float, parse_constant=routing._constant)
    except (ValueError, UnicodeError, RecursionError) as error:
        raise IRCellRuntimeError("invalid bounded replay JSON") from error
    _require(type(value) is dict, "replay JSON object required")
    pending, count = [(value, 0)], 0
    while pending:
        item, depth = pending.pop()
        count += 1
        _require(depth <= 64 and count <= node_limit, "replay JSON structure exceeds bound")
        if type(item) is dict:
            pending.extend((child, depth + 1) for child in item.values())
        elif type(item) is list:
            pending.extend((child, depth + 1) for child in item)
    return value


def _cached_rows(cache_pin, split, row_ids):
    saved = _json(cache_pin, node_limit=4_000_000)
    _require(set(saved) == {"rows"} and type(saved["rows"]) is list
             and 1 <= len(saved["rows"]) <= MAX_ROWS, "closed bounded cached rows required")
    by_id = {}
    for index, row in enumerate(saved["rows"]):
        _require(type(row) is dict and set(row) == _ROW_FIELDS, "closed original cached row required")
        _text(row["id"], 256, "cached row id")
        _require(row["id"] not in by_id, "duplicate cached row id")
        _text(row["group_id"], 256, "cached group id")
        _require(row["split"] == split and type(row["target"]) is dict,
                 "cached row split or target envelope differs")
        _require(type(row["wording_style"]) is int and 0 <= row["wording_style"] <= 1_000_000,
                 "bounded cached wording style required")
        source = _text(row["source_text"], 16384, "cached source text")
        _require(len(source) <= 65536 and _hash(row["source_sha256"])
                 and hashlib.sha256(source).hexdigest() == row["source_sha256"],
                 "cached source bytes differ")
        vector = row["embedding"]
        _require(type(vector) is list and len(vector) == 384, "actual 384-element cached vector required")
        try:
            finite = all(type(number) in (int, float) and math.isfinite(number) for number in vector)
        except OverflowError:
            finite = False
        _require(finite and _hash(row["embedding_sha256"])
                 and hashlib.sha256(_raw(vector)).hexdigest() == row["embedding_sha256"],
                 "cached embedding numbers or canonical digest differ")
        _require(_hash(row["embedding_token_ids_sha256"]), "declared cached token digest required")
        by_id[row["id"]] = index, row
    _require(all(identifier in by_id for identifier in row_ids), "requested row is outside exact cached split")
    inputs, receipts = [], []
    for identifier in row_ids:
        index, row = by_id[identifier]
        inputs.append({key: deepcopy(row[key]) for key in ("id", "source_text", "embedding")})
        receipts.append({**{key: row[key] for key in ("id", "split", "group_id", "wording_style",
            "source_sha256", "embedding_sha256", "embedding_token_ids_sha256")},
            "cache_receipt": dict(cache_pin), "row_index": index, "token_provenance_qualified": False})
    return inputs, receipts


def _capture_options(directory_plan_pin, inventory_pins, request, package_manifest_pin,
                     cache_split, row_ids, max_reference_bytes):
    _require(type(request) is dict and set(request) == _REQUEST_FIELDS,
             "closed explicit cell request required")
    _require(type(request["ir_family_id"]) is str and request["ir_family_id"] in _FAMILIES
             and type(request["dimension"]) is int and request["dimension"] == 384
             and type(request["dimension_role"]) is str and request["dimension_role"] == "input_embedding"
             and type(request["task_id"]) is str and request["task_id"] == "source_to_native_ir"
             and _hash(request["checkpoint_sha256"]),
             "experimental replay requires explicit Legal/Security/Intent source384 checkpoint")
    _require(type(max_reference_bytes) is int and 0 < max_reference_bytes <= MAX_REFERENCE_BYTES,
             "bounded reference byte cap required")
    _require(type(inventory_pins) in (list, tuple) and len(inventory_pins) == 12,
             "exactly twelve explicit cell pins required")
    _require(type(cache_split) is str and cache_split in _SPLITS, "explicit cached split required")
    _require(type(row_ids) in (list, tuple) and 1 <= len(row_ids) <= MAX_SELECTED_ROWS,
             "one to 64 explicit cached row ids required")
    for identifier in row_ids:
        _text(identifier, 256, "selected row id")
    _require(len(set(row_ids)) == len(row_ids), "unique selected row ids required")
    return dict(directory_plan_pin=routing._pin(directory_plan_pin, routing.MAX_MANIFEST_BYTES),
        inventory_pins=[routing._pin(pin, routing.MAX_MANIFEST_BYTES) for pin in inventory_pins],
        request=dict(request), package_manifest_pin=routing._pin(package_manifest_pin, routing.MAX_MANIFEST_BYTES),
        cache_split=cache_split, row_ids=list(row_ids), max_reference_bytes=max_reference_bytes)


def prepare_ir_cell_runtime(directory_plan_pin, inventory_pins, request, *, package_manifest_pin,
                            cache_split, row_ids, max_reference_bytes=MAX_REFERENCE_BYTES):
    """Authenticate explicit experimental replay; never load models or use defaults.

    The package declares a supported experimental capability, independently of
    inventory task membership or teacher/quality/span qualification. Targets are
    checked only as cached envelope fields and never forwarded to a runtime.
    """
    try:
        options = _capture_options(directory_plan_pin, inventory_pins, request, package_manifest_pin,
                                   cache_split, row_ids, max_reference_bytes)
        directory_plan_pin, inventory_pins, request = (options[name] for name in
            ("directory_plan_pin", "inventory_pins", "request"))
        package_manifest_pin, row_ids = options["package_manifest_pin"], options["row_ids"]
        route = routing.resolve_ir_cell_route(directory_plan_pin, inventory_pins, request,
                                              max_reference_bytes=max_reference_bytes)
        checkpoint = route["selected_checkpoint"]
        _require(route["availability"]["checkpoint_bytes"] == "verified"
                 and checkpoint.get("payload_ir_family", request["ir_family_id"]) == request["ir_family_id"],
                 "available same-family checkpoint bytes required")
        manifest_pin = routing._pin(package_manifest_pin, routing.MAX_MANIFEST_BYTES)
        manifest = hub.validate_manifest(_json(manifest_pin, node_limit=100000), domain=request["ir_family_id"])
        parent = Path(manifest_pin["path"]).parent
        files = {name: routing._pin({"path": str(parent / name), **entry}, max_reference_bytes)
                 for name, entry in manifest["files"].items()}
        _require(files[manifest["checkpoint_file"]] == checkpoint["receipt"],
                 "package checkpoint must match exact declared cell path, bytes and SHA256")
        for pin in files.values():
            routing._read_pin(pin)
        caches = [row for row in route["cached_vector_records"] if row.get("split") == cache_split]
        _require(len(caches) == 1, "unique original cached split declaration required")
        cache_pin = routing._pin(caches[0]["receipt"], max_reference_bytes)
        inputs, row_receipts = _cached_rows(cache_pin, cache_split, row_ids)
        result = dict(schema=SCHEMA, route=route, package_manifest_receipt=manifest_pin,
            package_manifest=manifest, package_file_receipts=files, cache_split=cache_split,
            cache_receipt=cache_pin, row_ids=list(row_ids), inputs=inputs, row_receipts=row_receipts,
            capability=dict(id="experimental_source384_cached_replay/v1", declared=True,
                family=request["ir_family_id"], dimension=384, dimension_role="input_embedding",
                task_id="source_to_native_ir", runtime_id=manifest["runtime"],
                source_access=route["provenance"]["source_access"],
                legal_parser_assistance_expected=request["ir_family_id"] == "legal_ir",
                new_source_inputs_supported=False, new_embeddings_generated=False),
            budget_status=deepcopy(route["budget_status"]), authority=dict(_AUTHORITY),
            consistency_scope=_SCOPE)
        return deepcopy(result)
    except routing.RoutingError as error:
        raise IRCellRuntimeError(str(error)) from error
    except (TypeError, KeyError, OverflowError, RecursionError) as error:
        raise IRCellRuntimeError("invalid experimental cached replay binding") from error
    except ValueError as error:
        if isinstance(error, IRCellRuntimeError):
            raise
        raise IRCellRuntimeError(str(error)) from error


class _CachedAutoencoder:
    def __init__(self, runtime, options, plan):
        self._runtime = runtime
        self._options_bytes = _raw(options)
        self._plan_bytes = _raw(plan)
        self._cached_inference_executed = False

    def _recheck(self):
        options = json.loads(self._options_bytes)
        plan = prepare_ir_cell_runtime(options.pop("directory_plan_pin"),
            options.pop("inventory_pins"), options.pop("request"), **options)
        _require(_raw(plan) == self._plan_bytes, "cached replay binding changed since opening")
        return plan

    def describe(self):
        plan = json.loads(self._plan_bytes)
        return deepcopy(dict(schema="ir-cell-cached-runtime-description/v1",
            runtime_selection=dict(request=plan["route"]["request"], runtime_id=plan["package_manifest"]["runtime"],
                checkpoint=plan["route"]["selected_checkpoint"]["receipt"],
                package_manifest=plan["package_manifest_receipt"]),
            row_selection=dict(cache_receipt=plan["cache_receipt"], split=plan["cache_split"], row_ids=plan["row_ids"]),
            capability=plan["capability"], budget_status=plan["budget_status"],
            model_load_performed=True, cached_inference_executed=self._cached_inference_executed,
            load_may_execute_model_fixture=plan["route"]["request"]["ir_family_id"] == "legal_ir",
            authority=dict(_AUTHORITY), consistency_scope=_SCOPE))

    def infer_cached(self):
        """Replay the fixed selected target-free rows; no new inputs or options."""
        plan = self._recheck()
        rows = deepcopy(plan["inputs"])
        original_inputs = _raw(rows)
        report = self._runtime.infer(rows)
        self._cached_inference_executed = True
        _require(_raw(rows) == original_inputs, "runtime mutated cached call inputs")
        self._recheck()
        return deepcopy(dict(schema="ir-cell-cached-inference/v1",
            runtime_selection=self.describe()["runtime_selection"], row_receipts=plan["row_receipts"],
            raw_candidate_report=report, model_inference_executed=True,
            authority=dict(_AUTHORITY), budget_status=plan["budget_status"], consistency_scope=_SCOPE))


def _open_ir_cell_autoencoder(directory_plan_pin, inventory_pins, request, *, package_manifest_pin,
                              cache_split, row_ids, max_reference_bytes=MAX_REFERENCE_BYTES):
    try:
        options = _capture_options(directory_plan_pin, inventory_pins, request, package_manifest_pin,
                                   cache_split, row_ids, max_reference_bytes)
    except routing.RoutingError as error:
        raise IRCellRuntimeError(str(error)) from error
    plan = prepare_ir_cell_runtime(options["directory_plan_pin"], options["inventory_pins"], options["request"],
        package_manifest_pin=options["package_manifest_pin"], cache_split=options["cache_split"],
        row_ids=options["row_ids"], max_reference_bytes=options["max_reference_bytes"])
    paths = {name: Path(pin["path"]) for name, pin in plan["package_file_receipts"].items()}
    runtime = hub._instantiate(deepcopy(plan["package_manifest"]), paths)
    wrapper = _CachedAutoencoder(runtime, options, plan)
    wrapper._recheck()
    return wrapper


__all__ = ["prepare_ir_cell_runtime", "IRCellRuntimeError", "SCHEMA", "MAX_REFERENCE_BYTES"]
