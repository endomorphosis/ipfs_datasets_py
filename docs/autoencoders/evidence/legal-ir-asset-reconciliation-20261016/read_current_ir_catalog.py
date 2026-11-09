#!/usr/bin/env python3
"""Read one explicitly pinned IR catalog through its public read-only owner.

Execute only through the existing owned-validation native owner. This driver
writes one new declared export. It never constructs ModelManager, reads weights,
imports model providers, registers models or falls back to handwritten SQL.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import importlib
import importlib.abc
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import sys

SCHEMA = "legal-ir-current-catalog-read-request/v1"
RESULT_SCHEMA = "legal-ir-current-catalog-observation/v1"
MAX_REQUEST = 1024 * 1024
MAX_SOURCE = 1024 * 1024
MAX_OUTPUT = 8 * 1024 * 1024
STORE = Path("/home/barberb/lift_coding/external/ipfs_accelerate/model_manager.duckdb")
ACCELERATE = STORE.parent
SOURCE_PATHS = (
    "ipfs_accelerate_py/__init__.py",
    "ipfs_accelerate_py/model_catalog/__init__.py",
    "ipfs_accelerate_py/model_catalog/identity.py",
    "ipfs_accelerate_py/model_catalog/schema.py",
    "ipfs_accelerate_py/model_catalog/sources/__init__.py",
    "ipfs_accelerate_py/model_catalog/sources/static.py",
    "ipfs_accelerate_py/model_catalog/sources/persistent.py",
    "ipfs_accelerate_py/model_catalog/sources/ir_persistent.py",
)
SELECTORS = {
    "record_id", "ir_family_id", "dimension", "dimension_role", "schema_version",
    "task_id", "profile_id", "format_id", "checkpoint_sha256", "role",
}
STATUSES = ("trained", "initialization_only", "donor", "runtime_ready",
            "teacher_qualified", "proof_authority")
FORBIDDEN = {
    "torch", "transformers", "tensorflow", "sentence_transformers",
    "huggingface_hub", "symai", "requests", "httpx", "aiohttp", "boto3",
    "botocore", "ipfs_datasets_py", "ipfs_kit_py",
}
HEX = re.compile(r"[0-9a-f]{64}\Z")


class CatalogReadRefusal(ValueError):
    """A bounded input, source or closing witness refused the observation."""


def need(condition, message):
    if not condition:
        raise CatalogReadRefusal(message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def wire(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode("utf-8")


def parse(raw):
    def pairs(entries):
        result = {}
        for key, value in entries:
            need(key not in result, "duplicate JSON field")
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=pairs,
        parse_constant=lambda _: (_ for _ in ()).throw(CatalogReadRefusal("nonfinite JSON")))


def identity(info):
    return {"device": info.st_dev, "inode": info.st_ino, "mode": info.st_mode,
            "links": info.st_nlink, "bytes": info.st_size,
            "mtime_ns": info.st_mtime_ns, "ctime_ns": info.st_ctime_ns}


def open_regular(path):
    path = Path(path)
    need(path.is_absolute() and ".." not in path.parts and path.name,
         "absolute direct input path required")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    parent = os.open("/", flags)
    try:
        for part in path.parent.parts[1:]:
            child = os.open(part, flags, dir_fd=parent)
            os.close(parent)
            parent = child
        return os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
                       dir_fd=parent)
    finally:
        os.close(parent)


def read_checked(path, *, expected_sha=None, expected_bytes=None, maximum=MAX_SOURCE):
    fd = open_regular(path)
    try:
        before = os.fstat(fd)
        need(stat.S_ISREG(before.st_mode) and before.st_nlink == 1
             and 0 < before.st_size <= maximum, "bounded regular input required")
        need(expected_bytes is None or before.st_size == expected_bytes,
             "input length differs from pin")
        chunks, count = [], 0
        while True:
            block = os.read(fd, min(65536, maximum + 1 - count))
            if not block:
                break
            chunks.append(block)
            count += len(block)
            need(count <= maximum, "input grew beyond bound")
        raw = b"".join(chunks)
        need(count == before.st_size and identity(os.fstat(fd)) == identity(before),
             "input descriptor changed while read")
        need(expected_sha is None or sha(raw) == expected_sha, "input SHA256 differs from pin")
        closing = open_regular(path)
        try:
            need(identity(os.fstat(closing)) == identity(before), "input path substituted")
        finally:
            os.close(closing)
        return raw, identity(before)
    finally:
        os.close(fd)


def witness(path, *, optional=False):
    try:
        info = Path(path).lstat()
    except FileNotFoundError:
        need(optional, "selected store is absent")
        return None
    need(stat.S_ISREG(info.st_mode) and info.st_nlink == 1,
         "selected store/WAL must be direct regular files")
    return identity(info)


def selector(value):
    need(type(value) is dict and set(value) == SELECTORS, "closed ten-selector query required")
    need(type(value["record_id"]) is str and len(value["record_id"]) <= 256,
         "bounded exact record_id required")
    need(value["ir_family_id"] == "legal_ir", "only LegalIR queries are selected")
    need((type(value["dimension"]) is int and value["dimension"] in (8, 384, 768)
          and value["dimension_role"] in ("latent", "input_embedding"))
         or (value["dimension"] is None and value["dimension_role"] in
             ("source_tokens", "unbound_component")), "exact dimension role required")
    need(type(value["checkpoint_sha256"]) is str and HEX.fullmatch(value["checkpoint_sha256"]),
         "exact checkpoint SHA256 required")
    for key in ("schema_version", "task_id", "profile_id", "format_id", "role"):
        item = value[key]
        need((item is None and key != "role") or
             (type(item) is str and 0 < len(item.encode("utf-8")) <= 512),
             "explicit bounded nullable selectors required")
    return dict(value)


class Output:
    def __init__(self, path):
        self.path = Path(path)
        need(self.path.is_absolute() and self.path.name == "current-legal-ir-catalog.json"
             and ".." not in self.path.parts, "exact catalog export filename required")
        temporary = Path(os.environ.get("TMPDIR", ""))
        need(temporary.is_absolute() and temporary.name == "tmp"
             and temporary.resolve(strict=True) == temporary,
             "native private TMPDIR required")
        need(self.path.parent == temporary.parent / "exports"
             and self.path.parent.resolve(strict=True) == self.path.parent,
             "export must belong to the native attempt")
        info = self.path.parent.stat()
        need(stat.S_ISDIR(info.st_mode) and stat.S_IMODE(info.st_mode) == 0o700
             and info.st_uid == os.getuid() and not list(self.path.parent.iterdir()),
             "empty owned private exports directory required")
        self.parent_identity = (info.st_dev, info.st_ino, info.st_mode, info.st_uid)

    def save(self, value):
        raw = wire(value) + b"\n"
        need(len(raw) <= MAX_OUTPUT, "catalog export exceeds eight MiB bound")
        info = self.path.parent.stat()
        need((info.st_dev, info.st_ino, info.st_mode, info.st_uid) == self.parent_identity,
             "export parent changed")
        parent = os.open(self.path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            need((os.fstat(parent).st_dev, os.fstat(parent).st_ino,
                  os.fstat(parent).st_mode, os.fstat(parent).st_uid) == self.parent_identity,
                 "export parent descriptor changed")
            fd = os.open(self.path.name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                0o600, dir_fd=parent)
            try:
                remaining = memoryview(raw)
                while remaining:
                    count = os.write(fd, remaining)
                    need(count > 0, "export write made no progress")
                    remaining = remaining[count:]
                os.fsync(fd)
            finally:
                os.close(fd)
            os.fsync(parent)
        finally:
            os.close(parent)
        return {"bytes": len(raw), "sha256": sha(raw)}


class CheckedSources(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    def __init__(self, sources):
        self.sources = sources
        self.loaded = {}

    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".")[0] in FORBIDDEN:
            raise ImportError("optional model/provider import is forbidden")
        if fullname == "ipfs_accelerate_py" or fullname.startswith("ipfs_accelerate_py."):
            need(fullname in self.sources, "unselected ACC import refused")
            item = self.sources[fullname]
            locations = [str(item["path"].parent)] if item["package"] else None
            return importlib.util.spec_from_file_location(fullname, str(item["path"]),
                loader=self, submodule_search_locations=locations)
        return None

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        item = self.sources[module.__name__]
        need(module.__spec__.origin == str(item["path"]), "checked module origin differs")
        exec(compile(item["raw"], str(item["path"]), "exec", dont_inherit=True), module.__dict__)
        need(Path(module.__file__) == item["path"] and
             module.__spec__.origin == str(item["path"]), "loaded module origin changed")
        self.loaded[module.__name__] = module

    def observations(self):
        need(set(self.loaded) == set(self.sources), "selected source closure was not loaded exactly")
        result = []
        for name in sorted(self.loaded):
            module = self.loaded[name]; item = self.sources[name]
            need(sys.modules.get(name) is module and Path(module.__file__) == item["path"]
                 and module.__spec__.origin == str(item["path"]), "retained module substituted")
            result.append({"module": name, "path": str(item["path"]),
                "bytes": len(item["raw"]), "sha256": sha(item["raw"]),
                "loaded_from_checked_source_buffer": True})
        return result


def inventory_row(binding, model):
    need(binding["ir_family_id"] == "legal_ir", "only LegalIR is exported")
    declaration = binding["declaration"]
    selected = selector({key: binding[key] for key in SELECTORS})
    pin = declaration["original_checkpoint_pin"]
    need(type(pin) is dict and set(pin) == {"path", "bytes", "sha256"}
         and pin["sha256"] == selected["checkpoint_sha256"], "original checkpoint declaration differs")
    return {"selectors": selected, "persisted_model_id": selected["record_id"],
        "catalog_model_id": binding["catalog_model_id"],
        "catalog_source_record_id": selected["record_id"],
        "projected_display_name": model.display_name,
        "projected_aliases": list(model.aliases),
        "declared_status": {key: declaration[key] for key in STATUSES},
        "original_checkpoint_pin": {key: pin[key] for key in ("path", "bytes", "sha256")},
        "checkpoint_bytes_authenticated_by_this_job": False,
        "runtime_observation_performed": False}


def run(request_path, expected_request_sha):
    output = None; phase = "request_preflight"; report = None
    try:
        need(type(expected_request_sha) is str and HEX.fullmatch(expected_request_sha),
             "independent request SHA256 required")
        request_raw, request_identity = read_checked(request_path,
            expected_sha=expected_request_sha, maximum=MAX_REQUEST)
        request = parse(request_raw)
        need(type(request) is dict and set(request) == {
            "schema", "accelerate_root", "store_path", "max_records", "source_pins", "queries", "output_path"}
            and request["schema"] == SCHEMA, "closed catalog input request required")
        output = Output(request["output_path"])
        need(request["accelerate_root"] == str(ACCELERATE) and request["store_path"] == str(STORE),
             "exact selected ACC root and store required")
        need(type(request["max_records"]) is int and request["max_records"] == 1000,
             "exact bounded thousand-record query required")
        queries = request["queries"]
        need(type(queries) is list and len(queries) <= 64, "bounded explicit queries required")
        queries = [selector(q) for q in queries]
        need(len({wire(q) for q in queries}) == len(queries), "duplicate exact query")
        pins = request["source_pins"]
        need(type(pins) is list and len(pins) == len(SOURCE_PATHS), "exact eight source pins required")
        indexed = {}
        for pin in pins:
            need(type(pin) is dict and set(pin) == {"path", "bytes", "sha256"}, "closed source pin required")
            need(type(pin["path"]) is str and pin["path"] not in indexed, "unique source path required")
            need(type(pin["bytes"]) is int and 0 < pin["bytes"] <= MAX_SOURCE
                 and type(pin["sha256"]) is str and HEX.fullmatch(pin["sha256"]), "bounded source pin required")
            indexed[pin["path"]] = pin
        need(set(indexed) == {str(ACCELERATE / x) for x in SOURCE_PATHS}, "source closure differs")
        sources, source_witnesses = {}, {}
        for relative in SOURCE_PATHS:
            path = ACCELERATE / relative; pin = indexed[str(path)]
            raw, info = read_checked(path, expected_sha=pin["sha256"], expected_bytes=pin["bytes"])
            package = path.name == "__init__.py"
            module = relative.removesuffix(".py").replace("/", ".")
            if package: module = module.removesuffix(".__init__")
            sources[module] = {"path": path, "raw": raw, "package": package}
            source_witnesses[str(path)] = info
        store_before = witness(STORE); wal_before = witness(str(STORE) + ".wal", optional=True)
        need(0 < store_before["bytes"] <= 4 * 1024**3, "store exceeds public reader bound")
        report = {"schema": RESULT_SCHEMA, "status": "pending",
            "observed_at_utc": datetime.now(timezone.utc).isoformat(),
            "request": {"path": str(request_path), "bytes": len(request_raw), "sha256": expected_request_sha},
            "store_path": str(STORE), "store_before": store_before, "wal_before": wal_before,
            "store_whole_file_sha256_performed": False, "max_records": 1000,
            "method": "One public IRPersistentCatalogSource read_only load; exact queries on its detached snapshot. Checked-source-buffer imports and cooperative endpoint witnesses, not an atomic database snapshot or host confinement claim.",
            "authority": {"model_manager_constructed": False, "model_loaded": False,
                "checkpoint_bytes_authenticated": False, "inference_executed": False,
                "training_executed": False, "teacher_qualified": False,
                "runtime_admitted": False, "proof_authority": False,
                "registry_mutated": False, "network_or_hub_accessed": False}}
        need(not any(name == "ipfs_accelerate_py" or name.startswith("ipfs_accelerate_py.")
                     or name.split(".")[0] in FORBIDDEN for name in sys.modules),
             "unexpected preloaded product or optional provider")
        sys.dont_write_bytecode = True
        def audit(event, args):
            if (event in {"subprocess.Popen", "os.system", "os.fork", "os.forkpty", "os.posix_spawn"}
                    or event.startswith("socket.")):
                raise CatalogReadRefusal("child process or network operation forbidden")
        sys.addaudithook(audit)
        loader = CheckedSources(sources)
        sys.meta_path.insert(0, loader)
        phase = "public_catalog_load"
        owner = importlib.import_module("ipfs_accelerate_py.model_catalog.sources.ir_persistent")
        result = owner.IRPersistentCatalogSource(path=STORE, max_records=1000).load()
        report["public_catalog_load_count"] = 1
        bindings = result.ir_bindings
        models = {p.source_record_id: m for m in result.models for p in m.provenance}
        legal = [b for b in bindings if b["ir_family_id"] == "legal_ir"]
        phase = "detached_inventory_and_queries"
        report.update(catalog_revision=result.revision,
            binding_snapshot_revision=result.binding_snapshot_revision,
            IR_catalog_binding_count=len(bindings), IR_projected_model_count=len(result.models),
            total_database_record_count=None,
            total_database_record_count_scope="Not exposed by the IR-only public source; never equated with its binding count.",
            IR_bindings_by_family=dict(sorted(Counter(b["ir_family_id"] for b in bindings).items())),
            legal_ir_binding_count=len(legal),
            legal_ir_by_dimension=dict(sorted(Counter(str(b["dimension"]) for b in legal).items())),
            legal_ir_by_dimension_role=dict(sorted(Counter(b["dimension_role"] for b in legal).items())),
            legal_ir_bindings=[inventory_row(b, models[b["record_id"]]) for b in legal],
            alias_scope="Only aliases in this native IR catalog projection; display names are not aliases. No separate running manager/router is queried.")
        resolutions = []
        for query in queries:
            try:
                resolved = result.resolve_ir_binding(query)
            except owner.IRPersistentCatalogError:
                matches = [b for b in bindings if all(b[k] == query[k] for k in SELECTORS)]
                need(len(matches) != 1, "public query refused an exact unique detached binding")
                resolutions.append({"query": query, "status": "missing" if not matches else "ambiguous",
                    "matches": len(matches)})
            else:
                selected = resolved["selected_binding"]
                need(all(selected[k] == query[k] for k in SELECTORS), "public exact query returned another binding")
                resolutions.append({"query": query, "status": "found", "matches": 1,
                    "persisted_model_id": selected["record_id"], "catalog_model_id": selected["catalog_model_id"]})
        report["exact_queries"] = resolutions
        report["query_count"] = len(resolutions)
        report["queries_found"] = sum(x["status"] == "found" for x in resolutions)
        reader = sys.modules.get("duckdb"); native = sys.modules.get("_duckdb")
        need(reader is not None and type(getattr(reader, "__version__", None)) is str,
             "actual DuckDB reader observation required")
        report["reader"] = {"version": reader.__version__, "python_module_path": reader.__file__,
            "native_extension_path": getattr(native, "__file__", None),
            "binary_bytes_independently_authenticated": False}
        phase = "closing_fences"
        report["loaded_product_origins"] = loader.observations()
        for path, pin in indexed.items():
            _, info = read_checked(path, expected_sha=pin["sha256"], expected_bytes=pin["bytes"])
            need(info == source_witnesses[path], "selected source identity changed")
        closing_request, closing_identity = read_checked(request_path,
            expected_sha=expected_request_sha, maximum=MAX_REQUEST)
        need(closing_request == request_raw and closing_identity == request_identity, "request changed")
        report["store_after"] = witness(STORE)
        report["wal_after"] = witness(str(STORE) + ".wal", optional=True)
        need(report["store_after"] == store_before and report["wal_after"] == wal_before,
             "selected store or WAL changed during observation")
        report["source_pins"] = pins
        report["source_and_request_witnesses_unchanged"] = True
        report["store_and_WAL_witnesses_unchanged"] = True
        report["F18_exact_checkpoint_declaration_matches"] = [b["record_id"] for b in legal
            if b["checkpoint_sha256"] == "90031d084f2d86cf860c5fc95d2dae374dc254adec70bd85a90893f98c5a1555"]
        report["F18_observation_scope"] = "Exact SHA presence/absence in the complete bounded strict IR declaration catalog only; not absence of every possible generic manager row or another store/process."
        report["status"] = "pass"
        output.save(report)
        return 0
    except Exception as error:
        failure = report or {"schema": RESULT_SCHEMA, "request_sha256": expected_request_sha}
        failure["status"] = "refused"
        if report is not None:
            failure.setdefault("source_pins", pins)
            failure["successful_closing_fences_completed"] = False
            for label, path in (("store_after", STORE), ("wal_after", str(STORE) + ".wal")):
                try:
                    failure[label] = witness(path, optional=(label == "wal_after"))
                except Exception:
                    failure[label + "_observation_refused"] = True
        failure["failure"] = {"phase": phase, "type": type(error).__name__,
            "message": str(error) if isinstance(error, CatalogReadRefusal) else
                "Public catalog read or closed projection refused; no fallback attempted."}
        if output is not None:
            try:
                output.save(failure)
            except Exception:
                print("Catalog observation refused; exclusive export could not be retained.", file=sys.stderr)
        else:
            print("Catalog observation refused before owned export validation.", file=sys.stderr)
        return 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", required=True)
    parser.add_argument("--expected-request-sha256", required=True)
    args = parser.parse_args()
    return run(Path(args.request), args.expected_request_sha256)


if __name__ == "__main__":
    raise SystemExit(main())
