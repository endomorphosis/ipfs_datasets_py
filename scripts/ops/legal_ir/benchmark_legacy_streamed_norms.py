#!/usr/bin/env python3
"""Compare frozen and optimized legacy bookkeeping with exact parity checks.

Synthetic eight-dimensional vectors, bridge-off training, no checkpoint I/O.
This diagnoses optimizer overhead; it is not a legal-IR conversion benchmark,
semantic qualification, or evidence of a faster bridge-on evaluation.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib
import importlib.util
import json
import os
from pathlib import Path
import statistics
import sys
import time
import tracemalloc

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
PREFIX = "ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_lineages"


def _profile(path):
    if not path:
        return importlib.import_module(f"{PREFIX}.legacy_v1_optimized")
    spec = importlib.util.spec_from_file_location(f"{PREFIX}.legacy_v1_optimized", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sample(profile, suffix):
    ir = importlib.import_module(f"{PREFIX}.legacy_v1._snapshot.modal_ir")
    text = f"The agency shall submit {suffix}."
    return profile.LegalSample(
        sample_id=suffix, source="us_code", title="5", section="552", citation="5 U.S.C. 552",
        text=text, normalized_text=text,
        embedding_model="test:explicit-synthetic-vector-not-semantic",
        embedding_vector=[(index % 7 - 3) / 7 for index in range(8)],
        modal_ir=ir.ModalIRDocument(
            document_id=suffix, source="us_code", normalized_text=text,
            formulas=[ir.ModalIRFormula(
                formula_id=suffix,
                operator=ir.ModalIROperator(family="deontic", system="SDL", symbol="O", label="obligation"),
                predicate=ir.ModalIRPredicate(name="submit", arguments=["agency", suffix]),
                provenance=ir.ModalIRProvenance(source_id=suffix, start_char=0, end_char=len(text)),
            )],
        ),
    )


def _without_timings(value):
    if isinstance(value, dict):
        return {key: _without_timings(item) for key, item in value.items() if "elapsed" not in key}
    if isinstance(value, list):
        return [_without_timings(item) for item in value]
    return value


def benchmark(profile, *, rows, head_rows, repeats):
    from ipfs_datasets_py.logic.autoformal.tree_pin import require_workspace_logic_tree
    origins = require_workspace_logic_tree()
    os.environ["IPFS_DATASETS_LEGAL_IR_METRIC_DISK_CACHE"] = "0"
    state = profile.TrainingState()
    # Include realistic eight-wide embedding rows plus bounded compiler-facing heads.
    for index in range(rows):
        state.feature_embedding_weights[str(index)] = [0.01 * (axis + 1) for axis in range(8)]
    for index in range(head_rows):
        state.feature_legal_ir_view_logits[str(index)] = {"deontic": 0.1, "cec": -0.3}
    transaction = state.transaction(label="benchmark-streamed-norms").begin()
    for index in range(rows):
        state.feature_embedding_weights[str(index)][index % 8] += 0.05
    for index in range(head_rows):
        state.feature_legal_ir_view_logits[str(index)]["deontic"] += 0.02
    functions = {
        "frozen": profile._legacy.legal_ir_trainable_head_transaction_delta_norm_report,
        "optimized": profile.legal_ir_trainable_head_transaction_delta_norm_report,
    }
    norm = {name: {"wall_seconds": []} for name in functions}
    expected = None
    try:
        for repeat in range(repeats):
            order = ("frozen", "optimized") if repeat % 2 == 0 else ("optimized", "frozen")
            for name in order:
                started = time.perf_counter()
                report = functions[name](transaction, state, learning_rate=0.01)
                norm[name]["wall_seconds"].append(time.perf_counter() - started)
                if expected is None:
                    expected = report
                if report != expected:
                    raise RuntimeError("streamed norm parity failed")
        # Allocation instrumentation is separate from the wall-time repetitions.
        for name, function in functions.items():
            tracemalloc.start()
            function(transaction, state, learning_rate=0.01)
            _, peak = tracemalloc.get_traced_memory()
            tracemalloc.stop()
            norm[name]["peak_python_allocation_bytes"] = peak
            norm[name]["median_wall_seconds"] = statistics.median(norm[name]["wall_seconds"])
    finally:
        transaction.rollback()
    norm["speedup"] = norm["frozen"]["median_wall_seconds"] / norm["optimized"]["median_wall_seconds"]
    norm["exact_report_parity"] = True
    norm["report"] = expected
    norm["unrelated_embedding_rows"] = rows
    norm["compiler_facing_head_rows"] = head_rows

    train = [_sample(profile, "reports"), _sample(profile, "summaries"), _sample(profile, "files")]
    validation = [_sample(profile, "notices"), _sample(profile, "records"), _sample(profile, "receipts")]
    training = {name: {"wall_seconds": []} for name in functions}
    reference_report = reference_state = None
    for repeat in range(repeats):
        order = ("frozen", "optimized") if repeat % 2 == 0 else ("optimized", "frozen")
        for name in order:
            model_type = profile.legacy_v1.Autoencoder if name == "frozen" else profile.Autoencoder
            model = model_type(compute_device="cpu")
            started = time.perf_counter()
            report = model.train_generalizable_projection(
                train, validation_samples=validation, epochs=2, learning_rate=0.01,
                max_seconds=30, max_line_search_attempts=1, projection_max_update_families=4,
                projection_update_backend="python_sparse_batch", legal_ir_bridge_names=(),
                legal_ir_evaluate_provers=False, legal_ir_parallel_workers=1,
            )
            training[name]["wall_seconds"].append(time.perf_counter() - started)
            normalized = _without_timings(report)
            state_digest = hashlib.sha256(json.dumps(model.state.to_dict(), sort_keys=True).encode()).hexdigest()
            if reference_report is None:
                reference_report, reference_state = normalized, state_digest
            if normalized != reference_report or state_digest != reference_state:
                raise RuntimeError("training report or state parity failed")
    for value in training.values():
        value["median_wall_seconds"] = statistics.median(value["wall_seconds"])
        value["median_wall_seconds_per_input_span"] = value["median_wall_seconds"] / (len(train) + len(validation))
    training.update({
        "sample_count": len(train), "validation_sample_count": len(validation),
        "epochs": 2, "accepted_epochs": reference_report["accepted_epochs"],
        "exact_report_parity_excluding_timings": True, "exact_weight_parity": True,
        "result_state_sha256": reference_state,
        "legal_ir_target_count": reference_report["after"]["legal_ir_target_count"],
        "speedup": training["frozen"]["median_wall_seconds"] / training["optimized"]["median_wall_seconds"],
    })
    return {
        "schema": "legacy-streamed-norms-benchmark/v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "scope": "synthetic optimizer bookkeeping diagnostic; not legal-IR speed or semantic qualification",
        "runtime_profile": profile.RUNTIME_PROFILE, "lineage_id": profile.LINEAGE_ID,
        "source_revision": profile.SOURCE_REVISION, "port_revision": profile.PORT_REVISION,
        "profile_source_sha256": hashlib.sha256(Path(profile.__file__).read_bytes()).hexdigest(),
        "frozen_batch_method_sha256": profile.FROZEN_BATCH_METHOD_SHA256,
        "canonical_logic_origins": origins, "bridge_names": [], "provers": False,
        "metric_disk_cache": False, "cold_legal_ir_run": None, "legal_ir_parallel_workers": 1,
        "use_sample_memory": False, "device": "cpu", "dimension": 8,
        "repeats": repeats, "norm_accounting": norm, "bridge_off_training": training,
        "bridge_on_evaluate": {"status": "not_run", "reason": "evaluation implementation is unchanged; this measures training bookkeeping only"},
        "admitted": False, "semantic_qualification": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--staged-profile", type=Path)
    parser.add_argument("--rows", type=int, default=3000)
    parser.add_argument("--head-rows", type=int, default=300)
    parser.add_argument("--repeats", type=int, default=5)
    args = parser.parse_args()
    if not 1 <= args.rows <= 100000 or not 1 <= args.head_rows <= 10000 or not 1 <= args.repeats <= 20:
        parser.error("rows/head-rows/repeats exceed bounded diagnostic limits")
    if args.output.exists():
        parser.error("output already exists; preserve historical receipts")
    report = benchmark(_profile(args.staged_profile), rows=args.rows, head_rows=args.head_rows, repeats=args.repeats)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"output": str(args.output), "norm_speedup": report["norm_accounting"]["speedup"],
                      "bridge_off_training_speedup": report["bridge_off_training"]["speedup"],
                      "exact_parity": True, "admitted": False}))


if __name__ == "__main__":
    main()
