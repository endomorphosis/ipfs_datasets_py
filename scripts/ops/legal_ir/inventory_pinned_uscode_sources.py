#!/usr/bin/env python3
"""Inventory exact local U.S. Code source shards without inference or training.

Run inside the existing resource-controlled operation wrapper. This command
denies network access, writes a new output directory, and never changes a
registry head, split assignment, corpus admission, or proof status.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import time


ROOT = Path(__file__).resolve().parents[3]


def _sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _write(path, value):
    raw = json.dumps(value, sort_keys=True, ensure_ascii=True, allow_nan=False,
                     separators=(",", ":")).encode("utf-8")
    with Path(path).open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    return {"path": str(Path(path).absolute()), "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}


def _sources():
    result = {}
    for path in sorted((ROOT / "ipfs_datasets_py").rglob("*.py")):
        if path.is_dir():
            continue
        if not path.is_file() or ROOT not in path.resolve().parents:
            raise ValueError("source escaped the canonical checkout")
        result[str(path.relative_to(ROOT))] = _sha(path)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--repo-id", required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--output-directory", type=Path, required=True)
    parser.add_argument("--select-entry-cid", action="append", default=[])
    args = parser.parse_args(argv)
    sys.path.insert(0, str(ROOT))
    sys.dont_write_bytecode = True
    for key, value in {
        "IPFS_DATASETS_PY_MINIMAL_IMPORTS": "1", "IPFS_DATASETS_PY_LAZY_INSTALL_ERGOAI": "0",
        "HF_HUB_OFFLINE": "1", "HF_DATASETS_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
        "CUDA_VISIBLE_DEVICES": "", "IPFS_DATASETS_MODAL_AUTOENCODER_AUTO_CUDA": "0",
        "IPFS_DATASETS_LEGAL_IR_METRIC_DISK_CACHE": "0", "OMP_NUM_THREADS": "1",
        "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1",
    }.items():
        os.environ[key] = value

    # Deny sockets before package imports. This is a local source-data operation.
    worker_path = ROOT / "ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_daemon_invocation_worker.py"
    spec = importlib.util.spec_from_file_location("_source_inventory_offline_bootstrap", worker_path)
    bootstrap = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = bootstrap
    spec.loader.exec_module(bootstrap)
    network_guard = bootstrap._deny_network()
    before = _sources()
    from ipfs_datasets_py.logic.autoformal.tree_pin import require_workspace_logic_tree
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_uscode_import import load_uscode_release
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_uscode_inventory import (
        build_uscode_source_inventory, materialize_uscode_inventory_inputs,
    )

    pin = require_workspace_logic_tree()
    source_root = args.source_root.resolve(strict=True)
    manifest_path = source_root / "manifest.json"
    manifest_ref = {"path": str(manifest_path), "sha256": args.manifest_sha256,
                    "bytes": manifest_path.stat().st_size}
    release = load_uscode_release(manifest_ref, repo_id=args.repo_id, revision=args.revision)
    references = {args.manifest_sha256: manifest_path}
    for artifact in release.artifacts:
        path = source_root / artifact.relative_path
        if path.resolve(strict=False).is_relative_to(source_root) is False:
            raise ValueError("release path escaped the selected local source root")
        # Equal byte identities may have multiple immutable manifest paths.
        # Choosing one file here is byte-addressed resolution, not row deduplication.
        references.setdefault(artifact.sha256, path)

    def resolver(reference):
        return references[reference["sha256"]]

    output = args.output_directory.absolute()
    output.mkdir(parents=False, exist_ok=False)
    report = {"schema": "pinned-uscode-source-inventory-run-v1", "passed": False,
              "network_guard": network_guard, "tree_pin": pin, "source_root": str(source_root),
              "manifest": manifest_ref, "repo_id": args.repo_id, "revision": args.revision,
              "native_training_validation_deferred": True, "training_performed": False,
              "embedding_inference_performed": False, "bridge_evaluation_performed": False,
              "downloads_performed": False, "publication_performed": False,
              "constitution_formalized": False, "admitted": False}
    started = time.perf_counter()
    _write(output / "sources-before.json", before)
    try:
        inventory = build_uscode_source_inventory(release, resolver=resolver)
        report["inventory"] = inventory.save(output / "inventory.json")
        report["summary"] = inventory.summary()
        report["source_inventory_seconds"] = time.perf_counter() - started
        if args.select_entry_cid:
            selected = materialize_uscode_inventory_inputs(
                inventory, args.select_entry_cid, output / "selected-inputs",
                release=release, resolver=resolver)
            report["selection_receipt"] = selected.selection_receipt_artifact
            report["selected_input_ids"] = [item.input_id for item in selected.inputs]
        after = _sources()
        report["source_files"] = len(before)
        report["source_unchanged"] = before == after
        report["changed_sources"] = [key for key in sorted(before.keys() | after.keys())
                                     if before.get(key) != after.get(key)]
        _write(output / "sources-after.json", after)
        report["passed"] = bool(report["summary"]["declared_corpus_closure_verified"] and before == after)
    except BaseException as exc:
        report["error"] = {"type": type(exc).__name__, "message": str(exc)[:2048]}
        raise
    finally:
        if "source_unchanged" not in report:
            try:
                after = _sources()
                report["source_files"] = len(before)
                report["source_unchanged"] = before == after
                report["changed_sources"] = [key for key in sorted(before.keys() | after.keys())
                                             if before.get(key) != after.get(key)]
                _write(output / "sources-after.json", after)
            except BaseException as guard_error:
                report["source_unchanged"] = False
                report["source_guard_error"] = {"type": type(guard_error).__name__,
                                                "message": str(guard_error)[:2048]}
        report["wall_seconds"] = time.perf_counter() - started
        artifact = _write(output / "inventory-report.json", report)
        directory = os.open(output, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        print(json.dumps({"report": artifact, "passed": report["passed"],
                          "wall_seconds": report["wall_seconds"]}), flush=True)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
