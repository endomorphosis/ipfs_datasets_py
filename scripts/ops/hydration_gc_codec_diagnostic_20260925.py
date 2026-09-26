"""Archived-format target hydration diagnostic; never a training qualification.

Run each mode in a fresh python3 process. The six verified raw shards are held
as bytes before timing. Both modes retain every hydrated target and perform a
full post-load collection inside their measured total. Only the candidate's
parse/decode/validate loop disables automatic cyclic GC. Re-encoding parity is
checked outside timing, using the original embedded configuration unchanged.
"""
from __future__ import annotations

import argparse
import gc
import hashlib
import json
import os
from pathlib import Path
import platform
import resource
import sys
import time


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from ipfs_datasets_py.logic.autoformal.tree_pin import require_workspace_logic_tree
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_ir_target_bundle as bundle_codec
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_ir_target_snapshot as codec


RECEIPT = ROOT / "docs/implementation/reports/evidence/autoencoder_control_plane_plan/ontology-observation-native-20260925.json"
RECEIPT_SHA256 = "1e9d5c52cd80974a89d335fd429c2d04bdf454b51f250c4c64d6163b04b6625b"
ARTIFACT_SHA256 = "ee87ec939d4b9fe2bf2bae162366769961ac8eec178f328b1dc92b0c54982613"
SOURCE_PATHS = (
    "optimizers/logic_theorem_optimizer/legal_ir_target_snapshot.py",
    "optimizers/logic_theorem_optimizer/legal_ir_target_bundle.py",
    "logic/bridge/types.py",
    "logic/bridge/multiview.py",
    "optimizers/logic_theorem_optimizer/modal_autoencoder.py",
    "logic/deontic/utils/deontic_parser.py",
)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def sources():
    return {name: sha((ROOT / "ipfs_datasets_py" / name).read_bytes()) for name in SOURCE_PATHS}


def rss():
    with open("/proc/self/statm", encoding="ascii") as stream:
        pages = int(stream.read().split()[1])
    return {"current_rss_bytes": pages * os.sysconf("SC_PAGE_SIZE"),
            "max_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}


def stats_delta(before, after):
    return [{key: right[key] - left[key] for key in right}
            for left, right in zip(before, after)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("normal_gc", "paused_gc"))
    parser.add_argument("output", type=Path)
    parser.add_argument("--pair", required=True, type=int, choices=(1, 2))
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    require_workspace_logic_tree()
    # Match the worker's already-imported target class environment before timing.
    codec._types()
    for name, module in tuple(sys.modules.items()):
        if name == "ipfs_datasets_py" or name.startswith("ipfs_datasets_py."):
            filename = getattr(module, "__file__", None)
            if filename:
                assert Path(filename).resolve().is_relative_to(ROOT / "ipfs_datasets_py"), (name, filename)
    source_before = sources()
    original_enabled = gc.isenabled()
    original_threshold = gc.get_threshold()
    original_callbacks = tuple(gc.callbacks)
    assert original_enabled, "normal-GC comparison requires a GC-enabled fresh interpreter"
    receipt_raw = RECEIPT.read_bytes()
    assert sha(receipt_raw) == RECEIPT_SHA256
    receipt = json.loads(receipt_raw)
    artifact = receipt["worker"]["target_snapshot_artifact"]
    assert artifact["sha256"] == ARTIFACT_SHA256 and artifact["bytes"] == 12843560
    rows_and_raw = []
    setup_started = time.perf_counter()
    with bundle_codec.load_target_bundle(artifact["path"], expected_sha256=artifact["sha256"]) as bundle:
        assert bundle.statistics["artifact_bytes"] == artifact["bytes"]
        config = bundle.config
        config_before = codec._json(config.to_dict())
        manifest = bundle._manifest
        assert len(manifest["records"]) == len(manifest["shards"]) == 6
        assert sum(item["uncompressed_bytes"] for item in manifest["shards"]) == 212314592
        shard_by_sha = {item["target_sha256"]: item for item in manifest["shards"]}
        for row in manifest["records"]:
            assert row["has_target"] is True
            shard = shard_by_sha[row["target_sha256"]]
            compressed = bundle_codec._read_at(bundle._check_open(), shard["compressed_bytes"],
                                               bundle._payload_offset + shard["offset"])
            assert sha(compressed) == shard["compressed_sha256"]
            raw = bundle_codec._expand(compressed, shard["uncompressed_bytes"])
            assert len(raw) == shard["uncompressed_bytes"] and sha(raw) == shard["target_sha256"]
            rows_and_raw.append((row, raw))
        bundle._check_open()
        snapshot_id = bundle.snapshot_id
    setup_seconds = time.perf_counter() - setup_started
    del receipt, receipt_raw, compressed, raw, bundle

    # Fixed-size callback aggregates avoid retaining GC objects or event lists.
    phases = ("preload_collection", "hydrate_validate", "post_load_collection", "parity")
    aggregates = {phase: [{"collections": 0, "elapsed_seconds": 0.0,
                          "collected": 0, "uncollectable": 0} for _ in range(3)] for phase in phases}
    current_phase = "preload_collection"
    collection_started = [0.0, 0.0, 0.0]

    def callback(phase, info):
        generation = info["generation"]
        if phase == "start":
            collection_started[generation] = time.perf_counter()
        else:
            values = aggregates[current_phase][generation]
            values["collections"] += 1
            values["elapsed_seconds"] += time.perf_counter() - collection_started[generation]
            values["collected"] += info["collected"]
            values["uncollectable"] += info["uncollectable"]

    targets = {}
    rows_timing = []
    gc.callbacks.append(callback)
    try:
        reset_collected = gc.collect()
        before_stats = gc.get_stats()
        before_count = gc.get_count()
        before_rss = rss()
        current_phase = "hydrate_validate"
        measured_started = time.perf_counter()
        if args.mode == "paused_gc":
            gc.disable()
        loop_started = time.perf_counter()
        try:
            for row, raw in rows_and_raw:
                started = time.perf_counter()
                parsed = codec._parse(raw)
                parsed_at = time.perf_counter()
                target = codec._decode(parsed)
                decoded_at = time.perf_counter()
                codec._validate_target(target, row["sample_id"], config, row["status"])
                validated_at = time.perf_counter()
                targets[row["sample_id"]] = target
                del parsed, target
                rows_timing.append({"sample_id": row["sample_id"], "parse_seconds": parsed_at - started,
                                    "decode_seconds": decoded_at - parsed_at,
                                    "validate_seconds": validated_at - decoded_at})
        finally:
            if original_enabled:
                gc.enable()
            else:
                gc.disable()
            gc.set_threshold(*original_threshold)
        loop_seconds = time.perf_counter() - loop_started
        loop_stats = gc.get_stats()
        loop_count = gc.get_count()
        loop_rss = rss()
        current_phase = "post_load_collection"
        collection_started_at = time.perf_counter()
        post_load_collected = gc.collect()
        post_load_collection_seconds = time.perf_counter() - collection_started_at
        measured_total_seconds = time.perf_counter() - measured_started
        post_stats = gc.get_stats()
        post_count = gc.get_count()
        post_rss = rss()
        assert len(targets) == 6
        assert gc.isenabled() == original_enabled and gc.get_threshold() == original_threshold
        # Full byte equality, not a summary hash of selected fields. All six live
        # targets remain retained through this post-timing validation.
        current_phase = "parity"
        parity_started = time.perf_counter()
        reencoding = []
        for row, raw in rows_and_raw:
            target = targets[row["sample_id"]]
            codec._validate_target(target, row["sample_id"], config, row["status"])
            rebuilt = codec._json(codec._encode(target))
            assert rebuilt == raw and sha(rebuilt) == row["target_sha256"]
            reencoding.append({"sample_id": row["sample_id"], "bytes": len(rebuilt),
                               "sha256": sha(rebuilt), "exact_bytes_equal": True})
            del rebuilt, target
        parity_seconds = time.perf_counter() - parity_started
        parity_rss = rss()
    finally:
        gc.set_threshold(*original_threshold)
        if original_enabled:
            gc.enable()
        else:
            gc.disable()
        gc.callbacks.remove(callback)
    assert tuple(gc.callbacks) == original_callbacks
    assert gc.isenabled() == original_enabled and gc.get_threshold() == original_threshold
    assert sources() == source_before, "source changed during archived codec diagnostic"
    assert codec._json(config.to_dict()) == config_before
    artifact_path = Path(artifact["path"])
    assert artifact_path.stat().st_size == artifact["bytes"] and sha(artifact_path.read_bytes()) == artifact["sha256"]
    result = {
        "schema": "archived-target-hydration-gc-diagnostic-v1", "mode": args.mode, "pair": args.pair,
        "scope": "archived-format strict codec hydration only; no current producer/config qualification or training claim",
        "training_performed": False, "formalized": False, "admitted": False,
        "current_training_configuration_validated": False, "embedded_configuration_unchanged": True,
        "receipt": {"path": str(RECEIPT), "sha256": RECEIPT_SHA256}, "artifact": artifact,
        "snapshot_id": snapshot_id, "embedded_config_sha256": sha(config_before),
        "embedded_producer_source_sha256": {name: config.code_sha256.get(name) for name in SOURCE_PATHS},
        "current_source_sha256": source_before,
        "harness_sha256": sha(Path(__file__).read_bytes()),
        "python": {"executable": sys.executable, "version": platform.python_version(),
                   "implementation": platform.python_implementation()},
        "raw_shards_preloaded": True, "expanded_bytes": sum(len(raw) for _, raw in rows_and_raw),
        "target_count_retained": len(targets), "manifest_order_preserved": True,
        "whole_bundle_compressed_and_expanded_digests_verified": True,
        "strict_parse_decode_validate_used": True, "full_canonical_reencoding": reencoding,
        "setup_seconds": setup_seconds, "parse_decode_validate_loop_seconds": loop_seconds,
        "post_load_collection_seconds": post_load_collection_seconds,
        "measured_total_including_gc_restore_and_collection_seconds": measured_total_seconds,
        "parity_check_seconds_outside_measurement": parity_seconds, "per_record": rows_timing,
        "gc": {"original_enabled": original_enabled, "original_threshold": original_threshold,
               "restored_enabled": gc.isenabled(), "restored_threshold": gc.get_threshold(),
               "callbacks_restored": True, "reset_collected": reset_collected,
               "first_post_load_collected": post_load_collected,
               "count_before_loop": before_count, "count_after_loop": loop_count, "count_after_collection": post_count,
               "stats_before_loop": before_stats, "stats_after_loop": loop_stats, "stats_after_collection": post_stats,
               "loop_generation_deltas": stats_delta(before_stats, loop_stats),
               "post_load_collection_generation_deltas": stats_delta(loop_stats, post_stats),
               "callback_aggregates": aggregates},
        "memory": {"before_loop": before_rss, "after_loop": loop_rss,
                   "after_post_load_collection": post_rss, "after_parity": parity_rss},
        "caveats": ["Fresh process per mode; OS cache uncontrolled.",
                    "All six verified raw byte strings are retained before timing, unlike sequential bundle hydration.",
                    "GC callback accounting adds instrumentation overhead in both modes.",
                    "No source/configuration identities are rewritten; the artifact is archived-format diagnostic input."]}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(json.dumps({"mode": args.mode, "pair": args.pair,
                      "loop_seconds": loop_seconds, "collection_seconds": post_load_collection_seconds,
                      "total_seconds": measured_total_seconds, "rss": post_rss,
                      "output": str(args.output), "sha256": sha(args.output.read_bytes())}))


if __name__ == "__main__":
    main()
