#!/usr/bin/env python3
"""Materialize a verified local U.S. Code package in a dedicated owner catalog.

Invoke inside the existing resource-controlled operation wrapper. This command
performs local source data I/O only; it never starts training or publication.
Dataset language is declared metadata, not translation or source authentication.
"""
from __future__ import annotations

import argparse
import importlib.util
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time

ROOT = Path(__file__).resolve().parents[3]

def _sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()

def _sources():
    result = {}
    for path in sorted((ROOT / "ipfs_datasets_py").rglob("*.py")):
        if path.is_dir():
            continue
        if not path.is_file() or not path.resolve().is_relative_to(ROOT):
            raise ValueError("source escaped the canonical checkout")
        result[str(path.relative_to(ROOT))] = _sha(path)
    result[str(Path(__file__).resolve())] = _sha(__file__)
    return result

def _unqualified_context_imports():
    paths = {ROOT / name for name in (
        "ipfs_datasets_py/logic/autoformal/entity_cache.py",
        "ipfs_datasets_py/logic/autoformal/supervisor_loop.py",
        "scripts/ops/legal_ir/run_autoformal_supervisor.py",
    )}
    return sorted({str(Path(filename).resolve()) for module in tuple(sys.modules.values())
                   if isinstance(filename := getattr(module, "__file__", None), str)
                   and Path(filename).resolve() in paths})


def _deny_unqualified_context():
    paths = {ROOT / name for name in (
        "ipfs_datasets_py/logic/autoformal/entity_cache.py",
        "ipfs_datasets_py/logic/autoformal/supervisor_loop.py",
        "scripts/ops/legal_ir/run_autoformal_supervisor.py",
    )}
    attempts = []
    def guard(event, args):
        if event == "exec" and args and isinstance(filename := getattr(args[0], "co_filename", None), str):
            path = Path(filename).resolve()
            if path in paths:
                attempts.append(str(path))
                raise RuntimeError("unqualified context execution denied: " + str(path))
    sys.addaudithook(guard)
    return attempts


def _write(path, value):
    raw = (json.dumps(value, sort_keys=True, ensure_ascii=True, allow_nan=False,
                      indent=2) + "\n").encode()
    with Path(path).open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    return {"path": str(Path(path).absolute()), "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--package-root", type=Path, required=True)
    parser.add_argument("--source-package", type=Path, required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--manifest-bytes", type=int, required=True)
    parser.add_argument("--operation-id", required=True)
    parser.add_argument("--dataset-namespace", required=True)
    parser.add_argument("--source-language", required=True)
    parser.add_argument("--jurisdiction", required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args(argv)
    if not re.fullmatch(r"[0-9a-f]{64}", args.manifest_sha256):
        parser.error("--manifest-sha256 must be a lowercase SHA-256")
    if not 1 <= args.manifest_bytes <= 4 * 1024**2:
        parser.error("--manifest-bytes must be between 1 byte and 4 MiB")
    destination = args.report.absolute()
    if destination.exists() or destination.is_symlink() or not destination.parent.is_dir():
        parser.error("--report requires a new file in an existing directory")
    started = time.perf_counter()
    sys.path.insert(0, str(ROOT))
    sys.dont_write_bytecode = True
    os.environ.update({
        "IPFS_DATASETS_PY_MINIMAL_IMPORTS": "1", "IPFS_DATASETS_PY_LAZY_INSTALL_ERGOAI": "0",
        "HF_HUB_OFFLINE": "1", "HF_DATASETS_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
        "CUDA_VISIBLE_DEVICES": "", "IPFS_DATASETS_MODAL_AUTOENCODER_AUTO_CUDA": "0",
        "IPFS_DATASETS_LEGAL_IR_METRIC_DISK_CACHE": "0", "OMP_NUM_THREADS": "1",
        "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1",
    })
    context_execution_attempts = _deny_unqualified_context()
    bootstrap_path = ROOT / "ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_daemon_invocation_worker.py"
    spec = importlib.util.spec_from_file_location("_source_catalog_offline_bootstrap", bootstrap_path)
    bootstrap = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = bootstrap
    spec.loader.exec_module(bootstrap)
    guard = bootstrap._deny_network()
    before = _sources()
    report = {"schema": "pinned-source-corpus-catalog-run-v1", "passed": False,
        "network_guard": guard, "native_training_validation_deferred": True,
        "training_performed": False, "embedding_inference_performed": False,
        "bridge_evaluation_performed": False, "downloads_performed": False,
        "publication_performed": False, "production_registry_modified": False,
        "production_ducklake_modified": False, "source_authority_authenticated": False,
        "constitution_formalized": False, "full_federal_corpus_complete": False,
        "formalized": False, "admitted": False, "file_cache_state": "uncontrolled"}
    source_before = destination.with_name(destination.stem + "-sources-before.json")
    source_after = destination.with_name(destination.stem + "-sources-after.json")
    report["sources_before_artifact"] = _write(source_before, before)
    try:
        from ipfs_datasets_py.logic.autoformal.tree_pin import require_workspace_logic_tree
        from ipfs_datasets_py.duckdb_control.source_corpus_catalog import SourceCorpusCatalog
        import pyarrow as pa
        pa.set_cpu_count(1)
        pa.set_io_thread_count(1)
        report.update(tree_pin=require_workspace_logic_tree(),
                      arrow_cpu_threads=pa.cpu_count(), arrow_io_threads=pa.io_thread_count())
        if _unqualified_context_imports():
            raise RuntimeError("unqualified concurrent context must not be imported")
        manifest = {"sha256": args.manifest_sha256, "bytes": args.manifest_bytes}
        dataset = {"namespace": args.dataset_namespace, "source_language": args.source_language,
                   "jurisdiction": args.jurisdiction, "profile": "uscode-source-export-v1"}
        package = args.source_package.absolute()
        def resolve_package(reference):
            if reference != manifest:
                raise ValueError("package resolver was asked for another manifest")
            return package / "source-export.json"
        report.update(database_path=str(args.database.absolute()), package_root=str(args.package_root.absolute()),
                      input_package=str(package), manifest_artifact=manifest, dataset=dataset,
                      operation_id=args.operation_id)
        phase = time.perf_counter()
        with SourceCorpusCatalog(args.database.absolute(), args.package_root.absolute()) as catalog:
            report["registration"] = catalog.register_export(args.operation_id, dataset=dataset,
                package_manifest_artifact=manifest, package_resolver=resolve_package)
        report["registration_and_close_seconds"] = time.perf_counter() - phase
        phase = time.perf_counter()
        with SourceCorpusCatalog(args.database.absolute(), args.package_root.absolute()) as catalog:
            version_id = report["registration"]["version_id"]
            report["version_after_reopen"] = catalog.get_version(version_id)
            report["verification_after_reopen"] = catalog.verify_version(version_id)
            report["resolved_operation_after_reopen"] = catalog.resolve_operation(
                args.operation_id, {"dataset": dataset, "package_manifest_artifact": manifest})
        registration, version, verification = (report[name] for name in
            ("registration", "version_after_reopen", "verification_after_reopen"))
        if (report["resolved_operation_after_reopen"] != registration
                or version["package_manifest_artifact"] != manifest
                or version["dataset"] != dataset
                or version["version_id"] != verification["version_id"]
                or registration["row_count"] != version["row_count"]
                or version["row_count"] != verification["row_count"]
                or registration["row_digest"] != version["row_digest"]
                or version["row_digest"] != verification["row_digest"]
                or verification["current_package_verified"] is not True
                or verification["materialized_rows_verified"] is not True
                or any(value is not False for value in verification["qualification"].values())):
            raise RuntimeError("reopened catalog differs from its committed source release")
        report["reopen_and_verification_seconds"] = time.perf_counter() - phase
        report["passed"] = True
    except BaseException as exc:
        report["error"] = {"type": type(exc).__name__, "message": str(exc)[:2048]}
        raise
    finally:
        try:
            after = _sources()
            report["sources_after_artifact"] = _write(source_after, after)
            report["source_unchanged"] = before == after
            report["changed_sources"] = [name for name in sorted(before.keys() | after.keys())
                                         if before.get(name) != after.get(name)]
            report["entity_context_not_imported"] = "ipfs_datasets_py.logic.autoformal.entity_cache" not in sys.modules
            report["unqualified_context_imports"] = _unqualified_context_imports()
            report["nonexecuted_context_not_imported"] = not report["unqualified_context_imports"]
            report["unqualified_context_execution_attempts"] = context_execution_attempts
            report["nonexecuted_context_not_executed"] = not context_execution_attempts
            report["passed"] = report["passed"] and report["source_unchanged"] and report["entity_context_not_imported"] and report["nonexecuted_context_not_imported"] and report["nonexecuted_context_not_executed"]
        except BaseException as exc:
            report["passed"] = False
            report["source_guard_error"] = {"type": type(exc).__name__, "message": str(exc)[:2048]}
        report["wall_seconds"] = time.perf_counter() - started
        receipt = _write(destination, report)
        fd = os.open(destination.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
        print(json.dumps({"passed": report["passed"], "report": receipt,
                          "wall_seconds": report["wall_seconds"]}), flush=True)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
