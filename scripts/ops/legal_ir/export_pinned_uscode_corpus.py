#!/usr/bin/env python3
"""Export complete declared local U.S. Code rows without inference or publishing.

Run inside the existing resource-controlled operation wrapper. The pinned
artifact map contains local descriptors, never model settings or credentials.
Output includes an independently verified package and a separate run receipt.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import sys
import time


ROOT = Path(__file__).resolve().parents[3]
MAX_MAP_BYTES = 4 * 1024 * 1024


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
    parser.add_argument("--artifact-map", type=Path, required=True)
    parser.add_argument("--artifact-map-sha256", required=True)
    parser.add_argument("--inventory-sha256", required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--repo-id", required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--partitions-sha256")
    parser.add_argument("--receipt-set-sha256")
    parser.add_argument("--output-directory", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.receipt_set_sha256 and not args.partitions_sha256:
        parser.error("--receipt-set-sha256 requires --partitions-sha256")
    for name in ("artifact_map_sha256", "inventory_sha256", "manifest_sha256",
                 "partitions_sha256", "receipt_set_sha256"):
        value = getattr(args, name)
        if value is not None and not re.fullmatch(r"[0-9a-f]{64}", value):
            parser.error(name + " must be a lowercase SHA-256")
    sys.path.insert(0, str(ROOT))
    sys.dont_write_bytecode = True
    os.environ.update({
        "IPFS_DATASETS_PY_MINIMAL_IMPORTS": "1", "IPFS_DATASETS_PY_LAZY_INSTALL_ERGOAI": "0",
        "HF_HUB_OFFLINE": "1", "HF_DATASETS_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
        "CUDA_VISIBLE_DEVICES": "", "IPFS_DATASETS_MODAL_AUTOENCODER_AUTO_CUDA": "0",
        "IPFS_DATASETS_LEGAL_IR_METRIC_DISK_CACHE": "0", "OMP_NUM_THREADS": "1",
        "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1",
    })
    bootstrap_path = ROOT / "ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_daemon_invocation_worker.py"
    spec = importlib.util.spec_from_file_location("_corpus_export_offline_bootstrap", bootstrap_path)
    bootstrap = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = bootstrap
    spec.loader.exec_module(bootstrap)
    guard = bootstrap._deny_network()
    before = _sources()
    from ipfs_datasets_py.logic.autoformal.tree_pin import require_workspace_logic_tree
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_uscode_import as importer
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_uscode_inventory import load_uscode_source_inventory
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_source_partitions import load_source_partitions
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_embedding_receipt_set import load_embedding_receipt_set
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_uscode_corpus_export import (
        export_uscode_source_rows, verify_uscode_source_export,
    )

    tree = require_workspace_logic_tree()
    import pyarrow as pa
    pa.set_cpu_count(1)
    pa.set_io_thread_count(1)
    map_path = args.artifact_map.absolute()
    map_ref = {"sha256": args.artifact_map_sha256, "bytes": map_path.lstat().st_size}
    with importer._verified_file(map_path, map_ref, MAX_MAP_BYTES) as stream:
        mapped = importer._parse(stream.read(MAX_MAP_BYTES + 1))
    if type(mapped) is not dict or not 1 <= len(mapped) <= 65536:
        raise ValueError("artifact map requires a bounded descriptor mapping")
    for digest, descriptor in mapped.items():
        if (type(digest) is not str or not re.fullmatch(r"[0-9a-f]{64}", digest)
                or type(descriptor) is not dict or set(descriptor) != {"path", "bytes"}
                or type(descriptor["bytes"]) is not int or not 1 <= descriptor["bytes"] <= 4 * 1024**3
                or type(descriptor["path"]) is not str or not Path(descriptor["path"]).is_absolute()):
            raise ValueError("invalid artifact map descriptor")

    def descriptor(digest):
        return {**mapped[digest], "sha256": digest}

    def resolver(reference):
        item = descriptor(reference["sha256"])
        if item["bytes"] != reference["bytes"]:
            raise ValueError("artifact map size differs from requested reference")
        return item["path"]

    output = args.output_directory.absolute()
    output.mkdir(parents=False, exist_ok=False)
    report = {"schema": "pinned-uscode-corpus-export-run-v1", "passed": False,
              "network_guard": guard, "tree_pin": tree, "artifact_map": {"path": str(map_path), **map_ref},
              "arrow_cpu_threads": pa.cpu_count(), "arrow_io_threads": pa.io_thread_count(),
              "native_training_validation_deferred": True, "training_performed": False,
              "embedding_inference_performed": False, "bridge_evaluation_performed": False,
              "downloads_performed": False, "publication_performed": False,
              "constitution_formalized": False, "full_federal_corpus_complete": False,
              "admitted": False}
    started = time.perf_counter()
    _write(output / "sources-before.json", before)
    try:
        item = descriptor(args.inventory_sha256)
        inventory = load_uscode_source_inventory(item["path"], expected_sha256=item["sha256"], expected_size_bytes=item["bytes"])
        limits = importer.USCodeImportLimits(**inventory.to_dict()["release"]["import_limits"])
        release = importer.load_uscode_release(descriptor(args.manifest_sha256),
            repo_id=args.repo_id, revision=args.revision, resolver=resolver, limits=limits)
        partitions = receipt_set = None
        if args.partitions_sha256:
            item = descriptor(args.partitions_sha256)
            partitions = load_source_partitions(item["path"], expected_sha256=item["sha256"],
                expected_size_bytes=item["bytes"], inventory=inventory)
        if args.receipt_set_sha256:
            item = descriptor(args.receipt_set_sha256)
            receipt_set = load_embedding_receipt_set(item["path"], expected_sha256=item["sha256"],
                expected_size_bytes=item["bytes"], partitions=partitions)
        phase = time.perf_counter()
        report["export"] = export_uscode_source_rows(inventory, output / "package",
            release=release, resolver=resolver, partitions=partitions, receipt_set=receipt_set,
            receipt_resolver=resolver, source_resolver=resolver)
        report["export_seconds"] = time.perf_counter() - phase
        # Reopen solely from the package; do not retain the original resident
        # metadata graphs during the independent readback.
        del inventory, partitions, receipt_set, release
        phase = time.perf_counter()
        report["verification"] = verify_uscode_source_export(output / "package",
            expected_manifest_sha256=report["export"]["manifest_artifact"]["sha256"])
        report["verification_seconds"] = time.perf_counter() - phase
        if report["verification"] != report["export"]:
            raise ValueError("independent package readback differs from export result")
        with importer._verified_file(map_path, map_ref, MAX_MAP_BYTES):
            pass
        report["passed"] = True
    except BaseException as exc:
        report["error"] = {"type": type(exc).__name__, "message": str(exc)[:2048]}
        raise
    finally:
        try:
            after = _sources()
            report["source_unchanged"] = before == after
            report["source_files"] = len(before) - 1
            report["changed_sources"] = [name for name in sorted(before.keys() | after.keys()) if before.get(name) != after.get(name)]
            _write(output / "sources-after.json", after)
            report["passed"] = report["passed"] and before == after
        except BaseException as exc:
            report["passed"] = False
            report["source_guard_error"] = {"type": type(exc).__name__, "message": str(exc)[:2048]}
        report["wall_seconds"] = time.perf_counter() - started
        receipt = _write(output / "export-report.json", report)
        directory = os.open(output, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        print(json.dumps({"passed": report["passed"], "report": receipt, "wall_seconds": report["wall_seconds"]}), flush=True)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
