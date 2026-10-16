#!/usr/bin/env python3
"""Missing-only, availability-only registration through the genuine ModelManager.

The CLI authenticates and prepares metadata only. Live registration additionally
requires --register semantics through run_request(..., registration_scope=...) in
an independently admitted, in-process ModelManagerRegistrationScope. This file
creates no resource owner or grant and never restores a numerical model.
"""
from __future__ import annotations

import argparse
import ast
from collections import Counter
from datetime import datetime, timezone
import hashlib
import importlib
import importlib.abc
import importlib.util
import json
import logging
import os
from pathlib import Path
import re
import stat
import sys
import types

REQUEST_SCHEMA = "legal-ir-missing-component-registration-request/v1"
REVIEW_SCHEMA = "legal-ir-missing-component-registration-driver-review/v1"
RESULT_SCHEMA = "legal-ir-missing-component-registration-result/v1"
AUTH_SCHEMA = "legal-ir-missing-source-components-authentication/v1"
DATASETS = Path("/home/barberb/lift_coding/artifacts/legal-ir-missing-component-import-20261016/datasets")
DATASETS_HEAD = "6b8b1346f888adbebbcf1d714e4ad0ab39a02052"
ACCELERATE = Path("/home/barberb/lift_coding/external/ipfs_accelerate")
ACCELERATE_HEAD = "90acc9b21c214e2f4c3a6c84769fd891cfdbd627"
STORE = ACCELERATE / "model_manager.duckdb"
IMPORTER = "ipfs_datasets_py/logic/formalization/autoencoder/ir_model_manager_import.py"
GUARD = Path("/home/barberb/lift_coding/artifacts/normative-checkpoint-availability-20261006/registration/register_normative_states.py")
CUSTODY = GUARD.with_name("custody.py")
GUARD_SHA = "ba8f50acd731ae42ba1883b1289395fdc108e0ece1045b39f8afd0b785598309"
CUSTODY_SHA = "c3b355c2b3e4743a839a721b61c1d2868fe25c609b8da562a6b302fbe0cb6864"
MAX_METADATA = 32 * 1024**2
MAX_DATABASE = 4 * 1024**3
MAX_RECORDS = 1000
BACKUP_CHUNK_BYTES = 64 * 1024**2
FORBIDDEN = {
    "torch", "numpy", "pandas", "transformers", "tensorflow", "symai",
    "sentence_transformers", "huggingface_hub", "requests", "httpx", "aiohttp",
    "boto3", "botocore", "ipfs_multiformats", "ipfs_kit_py",
    "ipfs_accelerate_py.ipfs_multiformats", "ipfs_accelerate_py.utils",
    "ipfs_accelerate_py.common", "ipfs_accelerate_py.ipfs_kit_integration",
    "ipfs_accelerate_py.datasets_integration", "ipfs_accelerate_py.model_manager_graphrag",
}
HEX = re.compile(r"[0-9a-f]{64}\Z")


class RegistrationRefusal(ValueError):
    """A metadata/source/resource boundary refused; no fallback is permitted."""


def need(condition, message):
    if not condition:
        raise RegistrationRefusal(message)


def wire(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode("utf-8")


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def witness(value):
    return (value.st_dev, value.st_ino, value.st_mode, value.st_nlink,
            value.st_size, value.st_mtime_ns, value.st_ctime_ns)


def capture(path, *, maximum=MAX_METADATA, expected=None, retain=False):
    path = Path(path)
    need(path.is_absolute() and path.resolve(strict=True) == path,
         "canonical regular input path required")
    before = path.lstat()
    need(stat.S_ISREG(before.st_mode) and before.st_nlink == 1
         and 0 < before.st_size <= maximum, "bounded single-link input required")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    digest, chunks, total = hashlib.sha256(), [], 0
    try:
        need(witness(os.fstat(fd)) == witness(before), "input descriptor changed")
        while True:
            block = os.read(fd, 1024**2)
            if not block:
                break
            total += len(block)
            need(total <= before.st_size, "input grew during read")
            digest.update(block)
            if retain:
                chunks.append(block)
        need(total == before.st_size and witness(os.fstat(fd)) == witness(before),
             "input changed while read")
    finally:
        os.close(fd)
    need(witness(path.lstat()) == witness(before) and path.resolve(strict=True) == path,
         "input path changed")
    pin = {"path": str(path), "bytes": total, "sha256": digest.hexdigest()}
    need(expected is None or wire(pin) == wire(expected), "input pin differs")
    return (pin, b"".join(chunks)) if retain else pin


def document(pin):
    def pairs(entries):
        out = {}
        for key, value in entries:
            need(key not in out, "duplicate JSON field")
            out[key] = value
        return out
    _, raw = capture(pin["path"], expected=pin, retain=True)
    return json.loads(raw, object_pairs_hook=pairs,
        parse_constant=lambda _: (_ for _ in ()).throw(RegistrationRefusal("nonfinite JSON")))


def checked_module(name, pin, *, injected=None):
    _, raw = capture(pin["path"], expected=pin, retain=True)
    module = types.ModuleType(name)
    module.__file__ = pin["path"]
    if injected:
        module.__dict__.update(injected)
    need(name not in sys.modules, "private checked module already present")
    sys.modules[name] = module
    try:
        exec(compile(raw, pin["path"], "exec", dont_inherit=True), module.__dict__)
    except BaseException:
        sys.modules.pop(name, None)
        raise
    return module


class CurrentSources(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    def __init__(self, owners):
        self.items, self.loaded = {}, {}
        for owner in owners[1:]:
            path = Path(owner["pin"]["path"])
            _, raw = capture(path, expected=owner["pin"], retain=True)
            parts = list(Path(owner["relative_path"]).with_suffix("").parts)
            package = parts[-1] == "__init__"
            if package:
                parts.pop()
            self.items[".".join(parts)] = (path, raw, package)
        self.refused = Counter()

    def find_spec(self, fullname, path=None, target=None):
        if any(fullname == x or fullname.startswith(x + ".") for x in FORBIDDEN):
            self.refused[fullname] += 1
            raise ImportError("registration excludes an optional provider/ML owner")
        if fullname == "ipfs_accelerate_py" or fullname.startswith("ipfs_accelerate_py."):
            need(fullname in self.items, "unselected ACC source import refused")
            location, _, package = self.items[fullname]
            return importlib.util.spec_from_file_location(fullname, str(location), loader=self,
                submodule_search_locations=[str(location.parent)] if package else None)
        return None

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        path, raw, _ = self.items[module.__name__]
        need(module.__spec__.origin == str(path), "checked module origin differs")
        if module.__name__ == "ipfs_accelerate_py.model_manager":
            # The genuine source references logger in optional-import fallbacks
            # before assigning it. This is the retained guard's authored seam.
            module.logger = logging.getLogger("ipfs_accelerate_model_manager")
        exec(compile(raw, str(path), "exec", dont_inherit=True), module.__dict__)
        need(Path(module.__file__) == path and module.__spec__.origin == str(path),
             "checked module origin changed")
        self.loaded[module.__name__] = module

    def observations(self):
        rows = []
        for name, module in sorted(self.loaded.items()):
            path, raw, _ = self.items[name]
            need(sys.modules.get(name) is module and Path(module.__file__) == path
                 and module.__spec__.origin == str(path), "loaded owner substituted")
            rows.append({"module": name, "path": str(path), "bytes": len(raw),
                         "sha256": sha(raw), "checked_source_buffer": True})
        return rows


def output_directory(path, *, live=False, scope=None):
    path = Path(path)
    need(path.is_absolute() and ".." not in path.parts and not path.exists(),
         "fresh declared absolute output directory required")
    need(path.parent.resolve(strict=True) == path.parent and path.parent.is_dir(),
         "existing canonical output parent required")
    if live:
        value = scope.snapshot()
        attempt = Path(value["attempt_directory"])
        need(attempt.is_absolute() and attempt.resolve(strict=True) == attempt
             and path.is_relative_to(attempt) and path != attempt,
             "outputs must belong to the actual owned attempt")
    path.mkdir(mode=0o700)
    return path


def write(path, value):
    raw = wire(value) + b"\n"
    need(len(raw) <= MAX_METADATA, "metadata export exceeds bound")
    with Path(path).open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    return capture(path)


def restrict_live_scope(scope, pin):
    need(scope is not None, "live registration requires an in-process purpose owner")
    cls = type(scope)
    module = sys.modules.get(cls.__module__)
    need(module is not None and getattr(module, "ModelManagerRegistrationScope", None) is cls
         and cls.__name__ == "ModelManagerRegistrationScope", "exact live scope class required")
    need(Path(module.__file__) == Path(pin["path"]), "scope source origin differs")
    capture(pin["path"], expected=pin)
    for name in ("guard", "assert_writable_store", "snapshot"):
        bound = getattr(scope, name, None)
        need(getattr(bound, "__self__", None) is scope
             and getattr(bound, "__func__", None) is cls.__dict__.get(name),
             "retained scope method identity differs")
    scope.guard()
    scope.assert_writable_store(STORE)
    return scope


def checkpoint_join(plan, authentication, releases):
    need(authentication.get("schema") == AUTH_SCHEMA
         and authentication.get("status") == "pass" and authentication.get("completed") is True
         and authentication.get("model_restored") is False
         and authentication.get("checkpoint_tensor_json_parsed") is False
         and authentication.get("all_six_payloads_opaque_sha256_verified") is True
         and authentication.get("all_closing_witnesses_unchanged") is True,
         "complete opaque original/download custody required")
    authority = authentication.get("authority")
    need(type(authority) is dict and authority and all(v is False for v in authority.values()),
         "opaque custody supplies no model authority")
    components = authentication.get("components")
    need(type(components) is list and [x.get("label") for x in components] == ["F15", "F17", "F18"]
         and len(plan["models"]) == 3, "exact three ordered source components required")
    need(wire(releases) == wire([x["publication_receipt_pin"] for x in components]),
         "exact independently retained publication receipts required")
    joins = []
    for record, component in zip(plan["models"], components):
        original, downloaded = component["checkpoint_pin"], component["verified_download_pin"]
        need(record["checkpoint_pin"] == original
             and original["sha256"] == downloaded["sha256"] and original["bytes"] == downloaded["bytes"]
             and wire(record["release"]) == wire(component["release"]), "original/archive/plan join differs")
        capture(original["path"], maximum=original["bytes"], expected=original)
        capture(downloaded["path"], maximum=downloaded["bytes"], expected=downloaded)
        metadata = record["model_metadata"]
        identity = metadata["huggingface_config"]["ir_checkpoint"]
        expected = {"ir_family_id": "legal_ir", "dimension": None, "dimension_role": "source_tokens",
            "asset_binding_schema": "ir-decoder-component-binding/v1", "external_lane_binding": None,
            "schema_version": None, "task_id": "semantic_IR_reconstruction",
            "profile_id": None, "format_id": None, "trained": True, "initialization_only": False, "runtime_ready": False,
            "teacher_qualified": False, "proof_authority": False, "original_checkpoint_pin": original}
        need(all(wire(identity.get(k)) == wire(v) for k, v in expected.items()),
             "source component must retain explicit off-matrix/unknown/non-operational identity")
        need(component["configured_latent_dimension"] == 384
             and type(component["configured_latent_dimension"]) is int
             and component["latent_conditioning_enabled"] is False,
             "reported placeholder cannot become a native embedding lane")
        need(all(io["data_type"] != "embeddings" for io in metadata["inputs"]),
             "source-only component cannot declare a latent input")
        expected_parent = None if component["label"] == "F15" else plan["models"][0]["model_metadata"]["model_id"]
        need(metadata.get("parent_model_id") == expected_parent,
             "source component's declared F15 parent lineage differs")
        joins.append({"label": component["label"], "model_id": metadata["model_id"],
            "checkpoint_pin": original, "verified_download_pin": downloaded,
            "release": component["release"],
            "reported_checkpoint_serialization_schema": component["checkpoint_serialization_schema"],
            "decoder_task": identity["task_id"], "dimension": None, "dimension_role": "source_tokens"})
    return joins


def constructor_schema(schema, manager_raw):
    """Refuse a constructor migration before opening a writable manager."""
    tree = ast.parse(manager_raw)
    classes = [n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "ModelManager"]
    need(len(classes) == 1, "one pinned genuine Manager class required")
    methods = [n for n in classes[0].body if isinstance(n, ast.FunctionDef)
               and n.name == "_create_database_tables"]
    need(len(methods) == 1, "one current constructor schema method required")
    node = methods[0]
    strings = [n.value for n in ast.walk(node) if isinstance(n, ast.Constant) and type(n.value) is str]
    creates = [x for x in strings if "CREATE TABLE IF NOT EXISTS model_metadata" in x]
    need(len(creates) == 1, "pinned constructor table declaration changed")
    expected = {}
    for line in creates[0].splitlines():
        matched = re.fullmatch(r"\s*(\w+)\s+(VARCHAR|TEXT|JSON|TIMESTAMP|BIGINT)(?:\s+PRIMARY KEY|\s+NOT NULL)?\s*,?\s*", line)
        if matched:
            expected[matched[1]] = "VARCHAR" if matched[2] == "TEXT" else matched[2]
    need(len(expected) == 32 and "serving_config" in strings,
         "known current constructor column shape required")
    expected["serving_config"] = "JSON"
    actual = {row[2]: row[4] for row in schema["columns"] if row[:2] == ["main", "model_metadata"]}
    need(actual == expected, "existing column/types would require constructor migration")
    indexes = {}
    for value in strings:
        match = re.fullmatch(r"CREATE INDEX IF NOT EXISTS (\w+) ON model_metadata\((\w+)\)", value.strip())
        if match:
            indexes[match[1]] = match[2]
    need(indexes == {"idx_model_type": "model_type", "idx_architecture": "architecture",
                     "idx_model_name": "model_name"}, "known pinned constructor indexes required")
    current = {row[2]: row for row in schema["indexes"]}
    for name, column in indexes.items():
        need(name in current and current[name][:2] == ["main", "model_metadata"]
             and current[name][3:5] == [False, False]
             and str(current[name][5]).replace('"', "").replace(" ", "") == "[" + column + "]",
             "existing index would require constructor migration")
    return {"columns": expected, "required_indexes": indexes,
            "constructor_source_sha256": sha(manager_raw), "migration_required": False}


def construct_manager(ModelManager, native, baseline, allowed_ids, duckdb, poll):
    """Fence genuine saves before __init__, including partial/fallback cleanup."""
    poll()
    manager = ModelManager.__new__(ModelManager)
    allowed = frozenset(allowed_ids)
    genuine_save = ModelManager._save_data
    def guarded_save():
        poll()
        need(getattr(manager, "use_database", None) is True
             and getattr(manager, "storage_path", None) == str(STORE)
             and isinstance(getattr(manager, "con", None), duckdb.DuckDBPyConnection),
             "genuine save cannot fall back to JSON")
        lock = getattr(manager, "_model_lock", None)
        need(lock is not None, "genuine save requires initialized lock")
        with lock:
            need(set(manager.models) <= allowed, "genuine save population exceeds absent targets")
            genuine_save(manager)
        poll()
    manager._save_data = guarded_save
    try:
        ModelManager.__init__(manager, storage_path=str(STORE), use_database=True,
            enable_ipfs=False, project_legacy_models=True, usage_service=None)
        poll()
        need(manager._save_data is guarded_save and manager.use_database is True
             and manager.storage_path == str(STORE)
             and isinstance(getattr(manager, "con", None), duckdb.DuckDBPyConnection),
             "genuine constructor lost the guarded selected DuckDB boundary")
        expected = {row["model_id"]: row for row in baseline}
        need(set(manager.models) == set(expected), "genuine constructor baseline population differs")
        for key, row in expected.items():
            need(native._matches(manager.models[key], row), "genuine constructor baseline metadata differs")
        need(all(getattr(manager, name) is None for name in (
            "_ipfs_backend", "_datasets_manager", "_filesystem_handler", "_provenance_logger",
            "_artifact_storage", "_storage_wrapper", "_knowledge_graph")),
            "optional side-effect owner became active")
        with manager._model_lock:
            manager.models = {key: item for key, item in manager.models.items() if key in allowed}
        return manager
    except BaseException:
        cleanup_manager(manager, duckdb)
        raise


def cleanup_manager(manager, duckdb):
    if manager is None:
        return
    lock = getattr(manager, "_model_lock", None)
    if lock is None:
        manager.models = {}
    else:
        with lock:
            manager.models = {}
    connection = getattr(manager, "con", None)
    # Never call close() on a fallback/partial manager: genuine close() may save
    # JSON. A known real native connection is closed directly even on refusal.
    if isinstance(connection, duckdb.DuckDBPyConnection):
        connection.close()


def coherent_backup(out, guard, poll):
    poll()
    need(not Path(str(STORE) + ".wal").exists(), "WAL requires separately coordinated snapshot")
    before = STORE.lstat()
    need(guard.store_witness() == guard.witness(before), "store changed before backup")
    destination = out / "model-manager-before.duckdb"
    digest, total = hashlib.sha256(), 0
    incoming = os.open(STORE, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    outgoing = None
    try:
        outgoing = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
        need(witness(os.fstat(incoming)) == witness(before), "backup source descriptor differs")
        while True:
            poll()
            block = os.read(incoming, BACKUP_CHUNK_BYTES)
            if not block:
                break
            total += len(block)
            need(total <= before.st_size <= MAX_DATABASE, "backup exceeded original bound")
            digest.update(block)
            remaining = memoryview(block)
            while remaining:
                count = os.write(outgoing, remaining)
                need(count > 0, "backup write made no progress")
                remaining = remaining[count:]
            poll()
        os.fsync(outgoing)
        need(total == before.st_size and witness(os.fstat(incoming)) == witness(before),
             "backup source changed during copy")
    finally:
        os.close(incoming)
        if outgoing is not None:
            os.close(outgoing)
    need(guard.store_witness() == guard.witness(before)
         and not Path(str(STORE) + ".wal").exists(), "store/WAL changed during backup")
    original = {"path": str(STORE), "bytes": total, "sha256": digest.hexdigest()}
    backup = capture(destination, maximum=MAX_DATABASE)
    need((backup["bytes"], backup["sha256"]) == (original["bytes"], original["sha256"]),
         "backup verification differs from streamed original bytes")
    poll()
    return original, backup, before


def review_binding(value, *, driver_pin, request, joins, owners):
    need(value.get("schema") == REVIEW_SCHEMA and value.get("approved") is True
         and value.get("findings") == [], "approved exact-source registration review required")
    expected = {"reviewed_driver_pin": driver_pin,
        "reviewed_resource_scope_pin": request["resource_scope_pin"],
        "reviewed_guard_pin": request["guard_pin"], "reviewed_custody_pin": request["custody_pin"],
        "reviewed_plan_pin": request["plan_pin"], "reviewed_authentication_pin": request["authentication_pin"],
        "reviewed_release_receipt_pins": request["release_receipt_pins"],
        "reviewed_source_owners": owners, "selected_model_ids": [x["model_id"] for x in joins]}
    need(all(wire(value.get(key)) == wire(answer) for key, answer in expected.items()),
         "registration review differs from selected bytes/identities")


def run_request(request_path, expected_request_sha256, *, register=False, registration_scope=None):
    phase = "metadata_preflight"; out = None; manager = None; duckdb = None
    mutation_possible = False; absent_ids = frozenset(); guard = None
    try:
        need(type(register) is bool, "explicit register boolean required")
        request_pin, _ = capture(request_path, retain=True)
        need(request_pin["sha256"] == expected_request_sha256 and HEX.fullmatch(expected_request_sha256),
             "independent exact request SHA required")
        request = document(request_pin)
        need(type(request) is dict and set(request) == {
            "schema", "datasets_root", "datasets_head", "accelerate_root", "accelerate_head", "store_path",
            "guard_pin", "custody_pin", "plan_pin", "release_receipt_pins", "authentication_pin",
            "review_pin", "resource_scope_pin", "source_owners", "output_directory"}
            and request["schema"] == REQUEST_SCHEMA, "closed registration input request required")
        need((request["datasets_root"], request["datasets_head"], request["accelerate_root"],
              request["accelerate_head"], request["store_path"]) ==
             (str(DATASETS), DATASETS_HEAD, str(ACCELERATE), ACCELERATE_HEAD, str(STORE)),
             "selected current committed source/store generation differs")
        need(request["guard_pin"]["path"] == str(GUARD) and request["guard_pin"]["sha256"] == GUARD_SHA
             and request["custody_pin"]["path"] == str(CUSTODY)
             and request["custody_pin"]["sha256"] == CUSTODY_SHA, "original unchanged guard/custody required")
        custody = checked_module("_missing_components_custody", request["custody_pin"])
        prior = sys.modules.get("custody")
        sys.modules["custody"] = custody
        try:
            guard = checked_module("_missing_components_guard", request["guard_pin"])
        finally:
            if prior is None:
                sys.modules.pop("custody", None)
            else:
                sys.modules["custody"] = prior
        # Only the private reused instance's source roots change; its original
        # helper function bodies and all production files remain unchanged.
        guard.DATASETS, guard.DATASETS_HEAD = DATASETS, DATASETS_HEAD
        guard.ACCELERATE, guard.ACCELERATE_HEAD = ACCELERATE, ACCELERATE_HEAD
        owners = guard.selected_source_owners()
        need(wire(owners) == wire(request["source_owners"]), "current committed selected owners differ")
        native = checked_module("_missing_components_native_importer", owners[0]["pin"])
        plan, native_pins, _, _ = native._prepare(request["plan_pin"],
            request["release_receipt_pins"], native.MAX_REFERENCE_BYTES)
        authentication = document(request["authentication_pin"])
        joins = checkpoint_join(plan, authentication, request["release_receipt_pins"])
        driver_pin = capture(Path(__file__))
        protected = native_pins + guard.nested_pins(authentication) + [request_pin, driver_pin,
            request["guard_pin"], request["custody_pin"], request["authentication_pin"],
            request["resource_scope_pin"]]
        if request["review_pin"] is not None:
            review_binding(document(request["review_pin"]), driver_pin=driver_pin,
                           request=request, joins=joins, owners=owners)
            protected.append(request["review_pin"])
        def fence():
            guard.fence(protected, owners)
        fence()
        scope = restrict_live_scope(registration_scope, request["resource_scope_pin"]) if register else None
        need(not register or request["review_pin"] is not None, "live registration requires exact review")
        out = output_directory(request["output_directory"], live=register, scope=scope)
        preflight_pin = write(out / "preflight.json", {"schema": "legal-ir-missing-component-preflight/v1",
            "complete": True, "request_pin": request_pin, "plan_pin": request["plan_pin"],
            "authentication_pin": request["authentication_pin"], "source_owners": owners,
            "resource_scope_pin": request["resource_scope_pin"], "joins": joins,
            "checkpoint_tensor_json_parsed": False, "model_restored": False,
            "database_opened": False, "manager_constructed": False})
        if not register:
            return preflight_pin
        def poll():
            scope.guard()
            scope.assert_writable_store(STORE)
        poll()
        guard.environment()
        need(not any(any(name == bad or name.startswith(bad + ".") for bad in FORBIDDEN)
                     for name in sys.modules), "optional provider/ML module preloaded")
        loader = CurrentSources(owners)
        refused_imports, refused_events = guard.install_execution_fence(owners)
        sys.meta_path.insert(0, loader)
        need(not any(name == "ipfs_accelerate_py" or name.startswith("ipfs_accelerate_py.")
                     for name in sys.modules), "ACC source was loaded before checked-source boundary")
        fallback = Path(str(STORE) + ".json")
        need(not fallback.exists() and not fallback.is_symlink(), "JSON fallback must remain absent")
        need(not Path(str(STORE) + ".wal").exists(), "WAL requires a coherent separate snapshot")
        phase = "fresh_complete_native_baseline"
        duckdb = importlib.import_module("duckdb")
        poll(); baseline, baseline_schema = guard.fresh_snapshot(duckdb); poll()
        need(len(baseline) <= MAX_RECORDS and len(wire(baseline)) <= MAX_METADATA,
             "complete native baseline exceeds declared metadata bounds")
        manager_owner = next(x for x in owners if x["relative_path"] == "ipfs_accelerate_py/model_manager.py")
        _, manager_raw = capture(manager_owner["pin"]["path"], expected=manager_owner["pin"], retain=True)
        schema_compatibility = constructor_schema(baseline_schema, manager_raw)
        absent, present = guard.partition_records(native, plan, baseline)
        absent_ids = frozenset(x["model_metadata"]["model_id"] for x in absent)
        before_pin = write(out / "before-records.json", baseline)
        schema_pin = write(out / "before-schema.json", baseline_schema)
        queries = []; ModelManager = None
        if absent:
            phase = "coherent_original_store_backup"
            original_store, backup_pin, backup_stat = coherent_backup(out, guard, poll)
            poll(); repeated, repeated_schema = guard.fresh_snapshot(duckdb); poll()
            need(wire(repeated) == wire(baseline) and wire(repeated_schema) == wire(baseline_schema),
                 "complete baseline changed during backup")
            repeated_absent, _ = guard.partition_records(native, plan, repeated)
            need({x["model_metadata"]["model_id"] for x in repeated_absent} == set(absent_ids),
                 "absent target population changed")
            fence(); poll()
            need(guard.store_witness() == guard.witness(backup_stat), "store changed before constructor")
            ModelManager = importlib.import_module("ipfs_accelerate_py.model_manager").ModelManager
            guard.loaded_owner_origins(owners)
            def make_manager(ids):
                nonlocal mutation_possible
                poll(); mutation_possible = True
                value = construct_manager(ModelManager, native, baseline, ids, duckdb, poll)
                try:
                    poll(); guard.loaded_owner_origins(owners)
                    need(wire(guard.schema_snapshot(value.con)) == wire(baseline_schema),
                         "genuine constructor changed schema/indexes")
                    return value
                except BaseException:
                    cleanup_manager(value, duckdb)
                    raise
            def readback(model_id):
                poll()
                rows, schema = guard.fresh_snapshot(duckdb, read_only=False)
                poll()
                need(wire(schema) == wire(baseline_schema), "schema changed during actual import")
                matches = [row for row in rows if row["model_id"] == model_id]
                need(len(matches) <= 1, "fresh native readback is not unique")
                queries.append({"model_id": model_id, "fresh_native_connection": True,
                    "shared_engine_cache_possible": True, "manager_models_not_used": True})
                return matches[0] if matches else None
            phase = "genuine_absent_only_public_import"
            # import_missing's retained empty_close is safe here: every manager
            # receives the pre-init genuine-save guard before any constructor.
            registration = guard.import_missing(native, plan, baseline, make_manager=make_manager,
                stage_plan=lambda value: write(out / "missing-only-import-plan.json", value),
                readback=readback, releases=request["release_receipt_pins"],
                max_reference_bytes=native.MAX_REFERENCE_BYTES)
            poll()
        else:
            original_store, backup_pin = None, None
            def forbidden(*args):
                raise RegistrationRefusal("all-present path must construct no manager or missing plan")
            registration = guard.import_missing(native, plan, baseline, make_manager=forbidden,
                stage_plan=forbidden, readback=None, releases=request["release_receipt_pins"],
                max_reference_bytes=native.MAX_REFERENCE_BYTES)
        phase = "cold_complete_native_readback"
        poll(); rows, schema = guard.fresh_snapshot(duckdb); poll()
        need(wire(schema) == wire(baseline_schema), "schema differs after actual first close")
        guard.check_population(native, rows, baseline, plan)
        poll(); exact_catalog = guard.exact_catalog(plan); poll()
        genuine_catalog = None
        if absent:
            phase = "cold_genuine_reload_empty_close"
            poll()
            manager = construct_manager(ModelManager, native, rows, frozenset(), duckdb, poll)
            try:
                guard.loaded_owner_origins(owners); poll()
                need(wire(guard.schema_snapshot(manager.con)) == wire(baseline_schema), "cold schema differs")
                genuine_catalog = guard.genuine_catalog_targets(manager,
                    {x["model_metadata"]["model_id"] for x in plan["models"]})
                poll(); guard.empty_close(manager); manager = None; poll()
            finally:
                cleanup_manager(manager, duckdb); manager = None
        phase = "closing_complete_readback"
        poll(); final, final_schema = guard.fresh_snapshot(duckdb); poll()
        need(wire(final_schema) == wire(baseline_schema), "final schema/indexes differ")
        guard.check_population(native, final, baseline, plan)
        need(wire(final) == wire(rows), "cold empty close changed persisted rows or activity")
        poll(); final_catalog = guard.exact_catalog(plan); poll()
        need(wire(exact_catalog) == wire(final_catalog), "closing exact catalog generation changed")
        need(not fallback.exists() and not fallback.is_symlink()
             and not Path(str(STORE) + ".wal").exists(), "fallback or closing WAL appeared")
        fence(); poll()
        native._prepare(request["plan_pin"], request["release_receipt_pins"], native.MAX_REFERENCE_BYTES)
        fence(); poll()
        after_pin = write(out / "after-records.json", final)
        result = {"schema": RESULT_SCHEMA, "complete": True,
            "observed_at_utc": datetime.now(timezone.utc).isoformat(),
            "preflight_pin": preflight_pin, "review_pin": request["review_pin"],
            "before_records_pin": before_pin, "before_schema_pin": schema_pin,
            "original_store_pin": original_store, "backup_pin": backup_pin, "after_records_pin": after_pin,
            "before_count": len(baseline), "after_count": len(final),
            "absent_ids": sorted(absent_ids), "already_present_ids": sorted(x["model_metadata"]["model_id"] for x in present),
            "registration": registration, "per_insert_native_readbacks": queries,
            "cold_exact_catalog": final_catalog, "cold_genuine_catalog": genuine_catalog,
            "constructor_schema_preflight": schema_compatibility,
            "all_baseline_metadata_and_activity_exactly_preserved": True,
            "schema_and_indexes_unchanged": True, "JSON_fallback_absent": True,
            "genuine_save_guard_installed_before_init": True,
            "genuine_save_population_absent_only": True, "close_save_population_empty": True,
            "loaded_product_origins": loader.observations(),
            "optional_import_refusals": dict(loader.refused),
            "legacy_optional_import_refusals": refused_imports, "refused_execution_events": refused_events,
            "live_resource_observation": scope.snapshot(),
            "cooperative_endpoint_scope": True,
            "active_other_manager_process_refreshed": False,
            "authority": {"model_restored": False, "numerical_reload_qualified": False,
                "inference_executed": False, "training_executed": False, "embeddings_generated": False,
                "Hub_updated": False, "teacher_qualified": False, "runtime_admitted": False,
                "proof_authority": False, "source_meaning_verified": False, "gold_eligible": False}}
        result_pin = write(out / "registration-result.json", result)
        poll()
        return result_pin
    except BaseException as error:
        if out is not None:
            failure = {"schema": "legal-ir-missing-component-registration-failure/v1", "phase": phase,
                "failure_type": type(error).__name__, "database_may_have_changed": mutation_possible,
                "absent_ids": sorted(absent_ids), "partial_native_outcomes": getattr(error, "outcomes", []),
                "no_automatic_retry_or_rollback": True, "model_restored": False}
            try:
                write(out / "failure.json", failure)
            except Exception:
                pass
        raise
    finally:
        if duckdb is not None:
            cleanup_manager(manager, duckdb)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", required=True)
    parser.add_argument("--expected-request-sha256", required=True)
    parser.add_argument("--register", action="store_true")
    args = parser.parse_args()
    need(not args.register, "CLI cannot create a live purpose owner; use admitted in-process run_request")
    pin = run_request(Path(args.request), args.expected_request_sha256)
    print(wire({"complete": True, "result_pin": pin, "registration_requested": False}).decode())


if __name__ == "__main__":
    main()
