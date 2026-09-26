#!/usr/bin/env python3
"""Freeze source partitions offline from an exact pinned inventory artifact.

Run within the existing resource-controlled operation wrapper. This prepares
source membership only; it does not change a model variant or training-job
schema, execute embeddings, train, evaluate or publish.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import sys
import time

from inventory_pinned_uscode_sources import ROOT, _sources, _write


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--inventory-sha256", required=True)
    parser.add_argument("--seed", required=True)
    parser.add_argument("--output-directory", type=Path, required=True)
    parser.add_argument("--source-root", type=Path)
    parser.add_argument("--materialize-training-count", type=int, default=0)
    args = parser.parse_args(argv)
    if not 0 <= args.materialize_training_count <= 256 or args.materialize_training_count and args.source_root is None:
        parser.error("materialization requires --source-root and a count in [1,256]")
    sys.path.insert(0, str(ROOT))
    sys.dont_write_bytecode = True
    os.environ.update({"IPFS_DATASETS_PY_MINIMAL_IMPORTS": "1", "IPFS_DATASETS_PY_LAZY_INSTALL_ERGOAI": "0",
                       "HF_HUB_OFFLINE": "1", "HF_DATASETS_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
                       "CUDA_VISIBLE_DEVICES": "", "IPFS_DATASETS_MODAL_AUTOENCODER_AUTO_CUDA": "0",
                       "IPFS_DATASETS_LEGAL_IR_METRIC_DISK_CACHE": "0", "OMP_NUM_THREADS": "1",
                       "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"})
    worker = ROOT / "ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_daemon_invocation_worker.py"
    spec = importlib.util.spec_from_file_location("_source_partitions_offline_bootstrap", worker)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    guard = module._deny_network()
    before = _sources()
    from ipfs_datasets_py.logic.autoformal.tree_pin import require_workspace_logic_tree
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_corpus_index import SplitPolicy
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_uscode_inventory import load_uscode_source_inventory
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_uscode_import import load_uscode_release, USCodeImportLimits
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_source_partitions import (
        build_source_partitions, load_source_partitions, materialize_partition_inputs,
    )
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_eval_splits import TRAIN_SPLIT, TRAINING_OPERATION
    pin = require_workspace_logic_tree()
    output = args.output_directory.absolute()
    output.mkdir(parents=False, exist_ok=False)
    report = {"schema": "pinned-uscode-source-partitions-run-v1", "passed": False,
              "network_guard": guard, "tree_pin": pin, "policy": SplitPolicy(args.seed).to_dict(),
              "native_training_validation_deferred": True, "training_performed": False,
              "embedding_inference_performed": False, "bridge_evaluation_performed": False,
              "publication_performed": False, "downloads_performed": False,
              "registry_modified": False, "training_job_contract_changed": False,
              "constitution_formalized": False, "admitted": False,
              "selected_training_input_rule": "first eligible physical rows in the frozen training partition; no fallback"}
    started = time.perf_counter()
    _write(output / "sources-before.json", before)
    try:
        inventory = load_uscode_source_inventory(args.inventory, expected_sha256=args.inventory_sha256)
        partitions = build_source_partitions(inventory, policy=SplitPolicy(args.seed))
        report["source_partitions"] = partitions.save(output / "source-partitions.json")
        report["summary"] = partitions.verification_summary()
        report["load_inventory_freeze_save_seconds"] = time.perf_counter() - started
        reopened = load_source_partitions(output / "source-partitions.json", inventory=inventory,
            expected_sha256=partitions.sha256, expected_size_bytes=len(partitions.to_bytes()))
        if reopened.to_bytes() != partitions.to_bytes():
            raise ValueError("partition artifact differs after reopening")
        report["reopen_verified"] = True
        if args.materialize_training_count:
            source_root = args.source_root.resolve(strict=True)
            source_meta = inventory.to_dict()["release"]
            release = load_uscode_release({"path": str(source_root / "manifest.json"), **source_meta["manifest"]},
                repo_id=source_meta["repo_id"], revision=source_meta["revision"],
                limits=USCodeImportLimits(**source_meta["import_limits"]))
            references = {source_meta["manifest"]["sha256"]: source_root / "manifest.json"}
            for artifact in release.artifacts:
                path = source_root / artifact.relative_path
                if not path.resolve(strict=False).is_relative_to(source_root):
                    raise ValueError("source artifact path escaped pinned source root")
                references.setdefault(artifact.sha256, path)
            entries = partitions.entry_cids_for(TRAIN_SPLIT)[:args.materialize_training_count]
            if len(entries) != args.materialize_training_count:
                raise ValueError("requested frozen training partition selection is too small")
            selected = materialize_partition_inputs(partitions, entries, output / "selected-inputs",
                operation=TRAINING_OPERATION, release=release, resolver=lambda ref: references[ref["sha256"]])
            report["selection_receipt"] = selected.selection_receipt_artifact
            report["selected_entry_cids"] = list(entries)
            report["selected_input_ids"] = [item.input_id for item in selected.inputs]
        after = _sources()
        report["source_files"] = len(before)
        report["source_unchanged"] = before == after
        report["changed_sources"] = [key for key in sorted(before.keys() | after.keys()) if before.get(key) != after.get(key)]
        _write(output / "sources-after.json", after)
        report["passed"] = before == after
    except BaseException as exc:
        report["error"] = {"type": type(exc).__name__, "message": str(exc)[:2048]}
        raise
    finally:
        if "source_unchanged" not in report:
            try:
                after = _sources()
                report["source_files"] = len(before)
                report["source_unchanged"] = before == after
                report["changed_sources"] = [key for key in sorted(before.keys() | after.keys()) if before.get(key) != after.get(key)]
                _write(output / "sources-after.json", after)
            except BaseException as exc:
                report["source_unchanged"] = False
                report["source_guard_error"] = {"type": type(exc).__name__, "message": str(exc)[:2048]}
        report["wall_seconds"] = time.perf_counter() - started
        artifact = _write(output / "source-partitions-report.json", report)
        fd = os.open(output, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
        print(json.dumps({"report": artifact, "passed": report["passed"], "wall_seconds": report["wall_seconds"]}), flush=True)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
