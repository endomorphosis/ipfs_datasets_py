#!/usr/bin/env python3
"""Uninstrumented native preparation of the frozen six source samples.

Reuses the frozen profiler's input checks, source guards and CLI, with an
explicit null instrumentation context. The actual prepare_training_targets
entry point and every package callable remain unchanged in memory. No GC
callback or cProfile hook is installed. Only an outer preparation clock and
the production entry point's existing timing fields are observed.

This benchmarks preparation only. It does not load a checkpoint, train a
model, or qualify training. Speed claims require subsequent paired content
parity; raw shard descriptors are retained for that review.
"""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

import profile_cold_target_preparation as base


BASE_SHA = "bc3e19730caa378d8c5ffe375a7170a04143c485d4d8bcaca983f9160fc50bc1"
MAX_REFERENCED_TARGET_BYTES = 256 * 1024 * 1024


@contextmanager
def no_instrumentation(observer):
    # The base harness checks cleanup explicitly. Nothing was installed here.
    observer.callbacks_restored = True
    yield


def verified_bundle_inventory(prepared):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_ir_target_bundle as codec

    artifact = prepared["artifact"]
    if Path(artifact["path"]).stat().st_size != artifact["bytes"]:
        raise ValueError("prepared bundle byte count changed")
    with codec.load_target_bundle(artifact["path"], expected_sha256=artifact["sha256"]) as bundle:
        statistics = bundle.statistics
        expanded = statistics["referenced_uncompressed_target_bytes"]
        if type(expanded) is not int or not 0 < expanded <= MAX_REFERENCED_TARGET_BYTES:
            raise ValueError("prepared targets exceed diagnostic expanded-byte budget")
        if (bundle.sample_count != 6 or bundle.snapshot_id != prepared["target_snapshot_id"]
                or bundle.statuses != prepared["statuses"]):
            raise ValueError("verified bundle differs from six observed preparation outcomes")
        return {
            "artifact": artifact, "snapshot_id": bundle.snapshot_id,
            "records": [dict(row) for row in bundle._manifest["records"]],
            "shards": [dict(row) for row in bundle._manifest["shards"]],
            "statistics_without_hydration": statistics,
            "bundle_digest_and_manifest_verified": True,
            "individual_targets_hydrated": False,
            "descriptor_scope": "manifest binds each sample/status to the complete tagged target SHA-256 and compressed shard SHA-256/offset/byte counts",
            "bounds": {"artifact_max_bytes": codec.DEFAULT_MAX_BYTES,
                       "manifest_max_bytes": codec.DEFAULT_MAX_MANIFEST_BYTES,
                       "shard_max_bytes": codec.DEFAULT_MAX_SHARD_BYTES,
                       "referenced_uncompressed_max_bytes": MAX_REFERENCED_TARGET_BYTES},
        }


def complete_bridge_results(prepared):
    expected = set(base.BRIDGES)
    statuses = prepared["statuses"]
    reports = prepared["bridge_report_telemetry"]
    return (len(statuses) == 6 and set(reports) == set(statuses)
            and all(status == "ready" for status in statuses.values())
            and all(report["report_received"] is True
                    and report["attempted_bridge_count"] == len(expected)
                    and report["implemented_bridge_count"] == len(expected)
                    and len(report["attempted_bridge_names"]) == len(expected)
                    and len(report["implemented_bridge_names"]) == len(expected)
                    and set(report["attempted_bridge_names"]) == expected
                    and set(report["implemented_bridge_names"]) == expected
                    and report["failed_bridge_count"] == 0
                    and report["failed_bridge_names"] == []
                    and report["failures"] == {} and report["outer_timeout"] is None
                    for report in reports.values()))


@contextmanager
def benchmark_entrypoint():
    if base.sha(base.__file__) != BASE_SHA:
        raise ValueError("frozen preparation harness changed")
    script_sha = base.sha(__file__)
    original_run, original_instrument = base.run, base.instrument

    def run(args, result):
        try:
            original_run(args, result)
            result["verified_target_bundle_inventory"] = verified_bundle_inventory(result["target_preparation"])
            result["complete_preparation_for_comparison"] = complete_bridge_results(result["target_preparation"])
            if not result["complete_preparation_for_comparison"]:
                raise ValueError("comparison requires all five bridges for all six inputs, with no bridge failure or timeout")
            if base.sha(__file__) != script_sha:
                raise ValueError("preparation benchmark changed during execution")
        finally:
            outer = result.get("observations", {}).get("phase_totals", {}).get("preparation", {})
            # No callback ran, so the base observer's zero GC counters are not
            # measurements and must not be presented as collection evidence.
            result["observations"] = {
                "function_wrappers_installed": False, "gc_callbacks_installed": False,
                "cprofile_enabled": False, "outer_preparation_seconds": outer.get("inclusive_seconds"),
            }
            result.update(schema="native-cold-target-preparation-benchmark-v1",
                          diagnostic_only=False, measurement_only=True, native_preparation_only=True,
                          native_qualification=False, training_qualification=False, wall_speed_claim=False,
                          timeout_observer_effect="no internal function wrappers, GC callbacks or cProfile; original timeout and production telemetry remain active")
            result["benchmark_harness"] = {
                "path": str(Path(__file__).resolve()), "sha256": script_sha,
                "source_unchanged": base.sha(__file__) == script_sha,
                "base_harness_path": str(Path(base.__file__).resolve()), "base_harness_sha256": BASE_SHA,
                "package_callables_replaced": False, "checkpoint_loaded": False,
                "failure_scope": "successful native return retains all six original statuses/bridge failure reports; an exception before return remains an error, with no inferred outcomes",
            }

    try:
        base.run, base.instrument = run, no_instrumentation
        yield
    finally:
        base.run, base.instrument = original_run, original_instrument


def main():
    with benchmark_entrypoint():
        return base.main()


if __name__ == "__main__":
    raise SystemExit(main())
