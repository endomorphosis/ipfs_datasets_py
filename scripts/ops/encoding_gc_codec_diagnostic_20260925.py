"""Archived target encoding GC diagnostic; not a training qualification.

Run each mode in a separate native python3 process, sequentially. A suggested
counterbalanced order is normal_gc / paused_gc / paused_gc / normal_gc, with
--pair 1 / 1 / 2 / 2. This script does not launch those runs itself.

Only one complete target is hydrated at a time. Strict hydration and semantic
validation use the bundle's embedded configuration unchanged. The candidate
disables cyclic GC only while encoding the target and serializing tagged JSON;
restoration and an explicit full collection are included in its measured total.
Both modes perform that terminal collection, and also report the unextended
normal encoding interval separately. Exact raw, compressed, and reconstructed
whole-bundle bytes must match the archived input. No targets are generated.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import gc
import hashlib
import json
import os
from pathlib import Path
import platform
import resource
import sys
import time
import zlib


ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "ipfs_datasets_py"
RECEIPT = ROOT / "docs/implementation/reports/evidence/autoencoder_control_plane_plan/target-hydration-gc-native-20260925.json"
RECEIPT_SHA256 = "9af775375c4a297b7f2ce75db77c86ab2f989c32113e27ede6766464b8fae2f5"
RECEIPT_BYTES = 2488763
ARTIFACT_SHA256 = "40b16465f121169d607a315876a0a395a545d6482f1b29e79fe5c2dca150f0b7"
ARTIFACT_BYTES = 12846582
EXPANDED_BYTES = 212381851
TARGET_COUNT = 6
MAX_SHARD_BYTES = 64 * 1024 * 1024
MAX_TOTAL_EXPANDED_BYTES = 256 * 1024 * 1024
PHASES = (
    "setup", "hydrate", "validate", "pre_encoding_collection", "encode", "json",
    "tagged_release", "gc_restore", "terminal_collection", "parity_hash",
    "compress", "record_release", "final_verification",
)


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def package_sources():
    result = {}
    for path in sorted(PACKAGE.rglob("*.py")):
        if path.is_symlink() or PACKAGE not in path.resolve().parents:
            raise ValueError("package source aliases another tree: " + str(path))
        if path.is_file():
            result[str(path.relative_to(ROOT))] = sha(path.read_bytes())
    return result


def rss():
    with open("/proc/self/statm", encoding="ascii") as stream:
        pages = int(stream.read().split()[1])
    return {"current_rss_bytes": pages * os.sysconf("SC_PAGE_SIZE"),
            "max_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}


def stats_delta(before, after):
    return [{key: right[key] - left[key] for key in right}
            for left, right in zip(before, after)]


class GCPhases:
    """Fixed-size aggregates only; never retain collected objects or events."""

    def __init__(self):
        self.phase = "setup"
        self.started = [None, None, None]
        self.unmatched_stops = 0
        self.aggregates = {
            phase: [{"collections": 0, "elapsed_seconds": 0.0,
                     "collected": 0, "uncollectable": 0} for _ in range(3)]
            for phase in PHASES
        }

    def callback(self, event, info):
        generation = info["generation"]
        if event == "start":
            self.started[generation] = (time.perf_counter(), self.phase)
            return
        started = self.started[generation]
        if started is None:
            self.unmatched_stops += 1
            return
        self.started[generation] = None
        began, phase = started
        values = self.aggregates[phase][generation]
        values["collections"] += 1
        values["elapsed_seconds"] += time.perf_counter() - began
        values["collected"] += info["collected"]
        values["uncollectable"] += info["uncollectable"]


def restore_gc(enabled, threshold):
    gc.set_threshold(*threshold)
    if enabled:
        gc.enable()
    else:
        gc.disable()


def encode_one(target, *, codec, paused, observer, original_enabled, original_threshold):
    """Return bytes plus primitives; leave no target/encoded-graph references."""
    before_stats = gc.get_stats()
    before_count = gc.get_count()
    before_memory = rss()
    total_started = time.perf_counter()
    try:
        observer.phase = "encode"
        if paused:
            gc.disable()
        encode_started = time.perf_counter()
        encoded = codec._encode(target)
        encode_finished = time.perf_counter()
        observer.phase = "json"
        raw = codec._json(encoded)
        json_finished = time.perf_counter()
        observer.phase = "tagged_release"
        del encoded
        release_finished = time.perf_counter()
    finally:
        # Restoration is measured, including any automatic collection it can
        # trigger. Exceptions propagate unchanged; no success result is saved.
        observer.phase = "gc_restore"
        restore_gc(original_enabled, original_threshold)
    restore_finished = time.perf_counter()
    restored_stats = gc.get_stats()
    restored_count = gc.get_count()
    observer.phase = "terminal_collection"
    collection_started = time.perf_counter()
    collected = gc.collect(2)
    collection_finished = time.perf_counter()
    after_stats = gc.get_stats()
    after_count = gc.get_count()
    after_memory = rss()
    require(gc.isenabled() == original_enabled and gc.get_threshold() == original_threshold,
            "GC policy did not restore after encoding")
    return raw, {
        "encode_seconds": encode_finished - encode_started,
        "json_seconds": json_finished - encode_finished,
        "tagged_graph_release_seconds": release_finished - json_finished,
        "encoding_interval_seconds": release_finished - total_started,
        "gc_restore_seconds": restore_finished - release_finished,
        "explicit_terminal_collection_seconds": collection_finished - collection_started,
        "encoding_including_gc_restore_and_collection_seconds": collection_finished - total_started,
        "terminal_collected": collected,
        "gc_count_before": before_count, "gc_count_after_restore": restored_count,
        "gc_count_after_collection": after_count,
        "gc_stats_before": before_stats, "gc_stats_after_restore": restored_stats,
        "gc_stats_after_collection": after_stats,
        "encoding_and_restore_generation_deltas": stats_delta(before_stats, restored_stats),
        "terminal_collection_generation_deltas": stats_delta(restored_stats, after_stats),
        "memory_before_encoding": before_memory, "memory_after_terminal_collection": after_memory,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("normal_gc", "paused_gc"))
    parser.add_argument("output", type=Path)
    parser.add_argument("--pair", required=True, type=int, choices=(1, 2))
    args = parser.parse_args()
    require(not args.output.exists(), "output already exists")
    require(not args.output.resolve().is_relative_to(PACKAGE), "output must be outside the package")
    require(platform.python_implementation() == "CPython", "this diagnostic requires CPython")
    original_enabled = gc.isenabled()
    original_threshold = gc.get_threshold()
    original_callbacks = tuple(gc.callbacks)
    original_debug = gc.get_debug()
    require(original_enabled and not original_callbacks and original_debug == 0,
            "use a fresh GC-enabled interpreter without GC callbacks or debugging")
    environment = {
        "IPFS_DATASETS_LEGAL_IR_METRIC_DISK_CACHE": "0", "CUDA_VISIBLE_DEVICES": "",
        "IPFS_DATASETS_MODAL_AUTOENCODER_AUTO_CUDA": "0", "IPFS_DATASETS_PY_LAZY_INSTALL_ERGOAI": "0",
        "IPFS_DATASETS_LEGAL_IR_ADAPTER_WORKERS": "1", "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
        "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1",
    }
    os.environ.update(environment)
    harness_before = sha(Path(__file__).read_bytes())
    source_before = package_sources()
    sys.path.insert(0, str(ROOT))
    from ipfs_datasets_py.logic.autoformal.tree_pin import require_workspace_logic_tree
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_ir_target_bundle as bundle_codec
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_ir_target_snapshot as codec

    require_workspace_logic_tree()
    codec._types()
    for name, module in tuple(sys.modules.items()):
        if name == "ipfs_datasets_py" or name.startswith("ipfs_datasets_py."):
            filename = getattr(module, "__file__", None)
            if filename:
                require(Path(filename).resolve().is_relative_to(PACKAGE),
                        f"noncanonical package import: {name}: {filename}")
    require(package_sources() == source_before, "package source changed during imports")
    receipt_raw = RECEIPT.read_bytes()
    require(len(receipt_raw) == RECEIPT_BYTES and sha(receipt_raw) == RECEIPT_SHA256,
            "archived native receipt digest/size mismatch")
    receipt = json.loads(receipt_raw)
    require(receipt["passed"] is True, "archived native receipt did not pass")
    artifact = receipt["target_preparation"]["artifact"]
    require(artifact["sha256"] == ARTIFACT_SHA256 and artifact["bytes"] == ARTIFACT_BYTES,
            "archived native bundle descriptor mismatch")
    require(Path(artifact["path"]).resolve().is_relative_to(ROOT), "artifact is outside the canonical tree")
    del receipt, receipt_raw

    observer = GCPhases()
    gc_callback = observer.callback
    gc.callbacks.append(gc_callback)
    records = []
    try:
        setup_started = time.perf_counter()
        with bundle_codec.load_target_bundle(
            artifact["path"], expected_sha256=ARTIFACT_SHA256, max_bytes=ARTIFACT_BYTES,
            max_shard_bytes=MAX_SHARD_BYTES,
        ) as bundle:
            require(bundle.statistics["artifact_bytes"] == ARTIFACT_BYTES, "bundle byte count mismatch")
            manifest = bundle._manifest
            require(len(manifest["records"]) == len(manifest["shards"]) == TARGET_COUNT,
                    "expected exactly six archived target records and unique shards")
            expanded_bytes = sum(item["uncompressed_bytes"] for item in manifest["shards"])
            require(expanded_bytes == EXPANDED_BYTES <= MAX_TOTAL_EXPANDED_BYTES,
                    "expanded target inventory mismatch or bound exceeded")
            require([row["target_sha256"] for row in manifest["records"]]
                    == [shard["target_sha256"] for shard in manifest["shards"]],
                    "this diagnostic requires unique shards in manifest record order")
            require(all(row["has_target"] is True for row in manifest["records"]), "missing target")
            config = bundle.config
            config_before = codec._json(config.to_dict())
            snapshot_id = bundle.snapshot_id
            # Preserve the original header and canonical manifest bytes. Only
            # reconstructed shard bodies enter the streaming bundle digest.
            prefix = bundle_codec._read_at(bundle._check_open(), bundle._payload_offset, 0)
            reconstructed = hashlib.sha256(prefix)
            reconstructed_bytes = len(prefix)
            del prefix
            bundle_setup_seconds = time.perf_counter() - setup_started
            for row, shard in zip(manifest["records"], manifest["shards"]):
                observer.phase = "hydrate"
                hydration_started = time.perf_counter()
                compressed = bundle_codec._read_at(
                    bundle._check_open(), shard["compressed_bytes"],
                    bundle._payload_offset + shard["offset"],
                )
                require(sha(compressed) == shard["compressed_sha256"], "compressed shard digest mismatch")
                raw = bundle_codec._expand(compressed, shard["uncompressed_bytes"])
                require(len(raw) == shard["uncompressed_bytes"] and sha(raw) == shard["target_sha256"],
                        "expanded shard digest/size mismatch")
                parsed = codec._parse(raw)
                target = codec._decode(parsed)
                del parsed
                hydration_seconds = time.perf_counter() - hydration_started
                observer.phase = "validate"
                validation_started = time.perf_counter()
                codec._validate_target(target, row["sample_id"], config, row["status"])
                validation_seconds = time.perf_counter() - validation_started
                # Equalize the starting generation state in both modes after
                # hydration. This deliberate reset is NOT native writer policy.
                observer.phase = "pre_encoding_collection"
                reset_started = time.perf_counter()
                reset_collected = gc.collect(2)
                reset_seconds = time.perf_counter() - reset_started
                rebuilt, measured = encode_one(
                    target, codec=codec, paused=args.mode == "paused_gc", observer=observer,
                    original_enabled=original_enabled, original_threshold=original_threshold,
                )
                observer.phase = "parity_hash"
                parity_started = time.perf_counter()
                require(rebuilt == raw and sha(rebuilt) == shard["target_sha256"],
                        "full canonical reencoding changed archived target bytes")
                parity_seconds = time.perf_counter() - parity_started
                observer.phase = "compress"
                compression_started = time.perf_counter()
                recompressed = zlib.compress(rebuilt, level=6)
                compression_seconds = time.perf_counter() - compression_started
                observer.phase = "parity_hash"
                parity_started = time.perf_counter()
                require(recompressed == compressed and sha(recompressed) == shard["compressed_sha256"],
                        "zlib-6 recompression changed archived shard bytes")
                reconstructed.update(recompressed)
                reconstructed_bytes += len(recompressed)
                parity_seconds += time.perf_counter() - parity_started
                records.append({
                    "sample_id": row["sample_id"], "sample_sha256": row["sample_sha256"],
                    "status": row["status"], "target_sha256": shard["target_sha256"],
                    "raw_bytes": len(raw), "compressed_bytes": len(compressed),
                    "compressed_sha256": shard["compressed_sha256"],
                    "hydration_setup_seconds_outside_measurement": hydration_seconds,
                    "strict_validation_seconds_normal_gc": validation_seconds,
                    "pre_encoding_collection_seconds_outside_measurement": reset_seconds,
                    "pre_encoding_collected": reset_collected,
                    "compression_seconds_normal_gc": compression_seconds,
                    "parity_seconds_outside_measurement": parity_seconds,
                    "full_raw_bytes_equal": True, "full_compressed_bytes_equal": True,
                    **measured,
                })
                observer.phase = "record_release"
                del target, raw, rebuilt, compressed, recompressed, measured
                bundle._check_open()
            observer.phase = "final_verification"
            require(reconstructed_bytes == ARTIFACT_BYTES and reconstructed.hexdigest() == ARTIFACT_SHA256,
                    "stream-reconstructed whole bundle differs")
            require(codec._json(config.to_dict()) == config_before, "embedded target configuration changed")
            bundle_codec._verify_file(bundle._check_open(), os.fstat(bundle._check_open()), ARTIFACT_SHA256)
            bundle._check_open()
            final_memory = rss()
    finally:
        observer.phase = "gc_restore"
        restore_gc(original_enabled, original_threshold)
        gc.callbacks.remove(gc_callback)

    require(tuple(gc.callbacks) == original_callbacks, "GC callbacks were not restored")
    require(gc.isenabled() == original_enabled and gc.get_threshold() == original_threshold
            and gc.get_debug() == original_debug, "original GC state was not restored")
    require(observer.unmatched_stops == 0 and all(value is None for value in observer.started),
            "incomplete GC callback accounting")
    source_after = package_sources()
    require(source_after == source_before, "package source changed during archived encoding diagnostic")
    require(sha(Path(__file__).read_bytes()) == harness_before, "diagnostic harness changed during execution")
    require(len(records) == TARGET_COUNT, "incomplete target record inventory")

    total_keys = (
        "encode_seconds", "json_seconds", "tagged_graph_release_seconds", "encoding_interval_seconds",
        "gc_restore_seconds", "explicit_terminal_collection_seconds",
        "encoding_including_gc_restore_and_collection_seconds", "strict_validation_seconds_normal_gc",
        "compression_seconds_normal_gc", "hydration_setup_seconds_outside_measurement",
        "pre_encoding_collection_seconds_outside_measurement", "parity_seconds_outside_measurement",
    )
    totals = {key: sum(row[key] for row in records) for key in total_keys}
    totals["validation_encoding_compression_including_gc_cleanup_seconds"] = sum(totals[key] for key in (
        "strict_validation_seconds_normal_gc", "encoding_including_gc_restore_and_collection_seconds",
        "compression_seconds_normal_gc",
    ))
    result = {
        "schema": "archived-target-encoding-gc-diagnostic-v1", "passed": True,
        "mode": args.mode, "pair": args.pair,
        "recorded_at": datetime.now(timezone.utc).isoformat(), "pid": os.getpid(), "parent_pid": os.getppid(),
        "scope": "archived-format single-target codec reencoding; no current producer/config or native writer qualification",
        "training_performed": False, "target_generation_performed": False,
        "formalized": False, "admitted": False, "weights_loaded": False, "weights_downloaded": False,
        "artifact_published": False, "current_training_configuration_validated": False,
        "production_gc_policy_changed": False, "whole_training_speed_claim": False,
        "receipt": {"path": str(RECEIPT), "sha256": RECEIPT_SHA256, "bytes": RECEIPT_BYTES},
        "artifact": artifact, "snapshot_id": snapshot_id,
        "embedded_configuration_unchanged": True, "embedded_config_sha256": sha(config_before),
        "embedded_producer_source_sha256": dict(config.code_sha256),
        "package_source_hashes_before": source_before, "package_source_hashes_after": source_after,
        "package_source_unchanged": True, "harness_sha256": harness_before,
        "environment_settings": environment,
        "python": {"executable": sys.executable, "version": platform.python_version(),
                   "implementation": platform.python_implementation()},
        "zlib": {"compile_version": zlib.ZLIB_VERSION, "runtime_version": zlib.ZLIB_RUNTIME_VERSION,
                 "compression_level": 6},
        "bounds": {"artifact_bytes": ARTIFACT_BYTES, "per_shard_expanded_bytes": MAX_SHARD_BYTES,
                   "total_expanded_bytes": MAX_TOTAL_EXPANDED_BYTES, "rss_bounded": False},
        "expanded_bytes": expanded_bytes, "record_count": len(records),
        "maximum_complete_targets_retained": 1, "all_raw_shards_preloaded": False,
        "manifest_record_and_shard_order_preserved": True,
        "strict_parse_decode_validate_used": True,
        "whole_bundle_compressed_and_expanded_digests_verified": True,
        "full_raw_and_compressed_bytes_equal": True,
        "stream_reconstructed_bundle_sha256": reconstructed.hexdigest(),
        "stream_reconstructed_bundle_bytes": reconstructed_bytes,
        "original_manifest_bytes_reused": True, "sample_payload_recomputed": False,
        "bundle_setup_seconds_outside_measurement": bundle_setup_seconds,
        "per_record": records, "totals": totals, "final_memory": final_memory,
        "gc": {"original_enabled": original_enabled, "original_threshold": original_threshold,
               "original_debug": original_debug, "restored_enabled": gc.isenabled(),
               "restored_threshold": gc.get_threshold(), "restored_debug": gc.get_debug(),
               "callbacks_restored": True, "callback_aggregates": observer.aggregates,
               "unmatched_stops": observer.unmatched_stops,
               "collection_elapsed_is_subset_of_phase_elapsed": True},
        "caveats": [
            "Archived embedded configuration is preserved; current parser or producer compatibility is not established.",
            "One complete target is live at a time, but hydration and encoded input bounds are not RSS bounds.",
            "Strict hydration, read/decompression, and full starting collection precede the encoding measurement.",
            "The starting collection ages the target graph; it does not reproduce the writer's post-generation GC state.",
            "Both modes include a forced terminal full collection; normal writer policy has no such forced collection.",
            "Compare candidate cleanup-inclusive time with both normal interval and normal cleanup-inclusive time.",
            "GC callback accounting and phase clocks add overhead; OS caches and host contention are uncontrolled.",
            "Full raw and compressed bytes plus reconstructed bundle SHA are checked; the original manifest is reused.",
            "This does not exercise generation, sample-payload recomputation, writer publication, or bridge evaluation.",
            "No blanket production GC pause is justified for unconstrained target graphs or arbitrary Mapping code.",
            "This diagnostic does not advance admission; only lake build <Lib> constitutes a Lean admit.",
        ],
    }
    serialized = json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        stream.write(serialized)
        stream.flush()
        os.fsync(stream.fileno())
    print(json.dumps({"mode": args.mode, "pair": args.pair, "totals": totals,
                      "final_memory": final_memory, "output": str(args.output),
                      "sha256": sha(serialized.encode("utf-8"))}, sort_keys=True))


if __name__ == "__main__":
    main()
