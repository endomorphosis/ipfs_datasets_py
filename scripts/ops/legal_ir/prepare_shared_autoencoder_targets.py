#!/usr/bin/env python3
"""Prepare a bounded, immutable shared target bundle for qualified training.

This explicit offline command produces targets, never model weights or an
admission. Pass its runner_arguments to run_incremental_autoencoders.py. Include
preparation and subsequent worker hydration/qualification in speed comparisons.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import asdict
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import resource
import signal
import stat
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
RUNNER = ROOT / "scripts/ops/legal_ir/run_incremental_autoencoders.py"
DEFAULT_LEDGER = ROOT / "workspace/test-logs/federal-corpus-audits/owned-daemon-resource-control/disk-reservations.json"
BRIDGES = ("modal_frame_logic", "deontic_norms", "fol_tdfol", "cec_dcec", "external_prover_router")
MAX_INPUT_BYTES = 64 * 1024 * 1024
MAX_ROWS = 10000
OVERHEAD_BYTES = 16 * 1024 * 1024
_HELPERS = None


def _helpers():
    global _HELPERS
    if _HELPERS is None:
        spec = importlib.util.spec_from_file_location("_shared_target_existing_runner", RUNNER)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _HELPERS = module
    return _HELPERS


def _canonical(value):
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _read_regular(path, limit):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
            raise ValueError("input must be a bounded regular file")
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError("input exceeds byte bound")
    return raw


def _descriptor(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError("artifact must be a regular non-symlink file")
    return {"path": str(path), "bytes": path.stat().st_size, "sha256": _helpers()._sha(path)}


def _selection(args):
    # Reuse the existing runner's exact SampleRecord normalization and order.
    helpers = _helpers()
    sources = helpers._pin()
    records, references = {}, {}
    for split, path, maximum in (
        ("training", args.input_jsonl, args.max_input_rows),
        ("validation", args.validation_jsonl, 32),
    ):
        raw = _read_regular(path, args.max_input_bytes)
        if len(raw.splitlines()) > maximum:
            raise ValueError(f"{split} input exceeds row bound")
        rows = helpers.local_records(path)
        digest = hashlib.sha256(raw).hexdigest()
        if any(row["provenance"]["input_sha256"] != digest for row in rows):
            raise ValueError("input changed while normalizing records")
        if not rows or any(not row["sample"]["text"].strip() for row in rows):
            raise ValueError("both splits require nonempty source text")
        records[split] = rows
        references[split] = {"path": str(path), "bytes": len(raw), "sha256": digest}
    text_key = lambda row: " ".join(row["sample"]["text"].casefold().split())
    if {text_key(row) for row in records["training"]} & {text_key(row) for row in records["validation"]}:
        raise ValueError("training and validation source text must be disjoint")
    return records, references, sources


def plan(args):
    started = time.monotonic()
    records, inputs, sources = _selection(args)
    selected = {key: [row["sample"] for row in value] for key, value in records.items()}
    selection_sha = hashlib.sha256(_canonical(selected).encode()).hexdigest()
    return {
        "schema_version": "shared-target-preparation-plan/v1",
        "input_planning_wall_seconds": time.monotonic() - started,
        "inputs": inputs, "selection_sha256": selection_sha,
        "training_record_count": len(records["training"]),
        "validation_record_count": len(records["validation"]),
        "maximum_union_target_count": sum(map(len, records.values())),
        "bridge_names": list(BRIDGES), "legal_ir_evaluate_provers": False,
        "metric_disk_cache": 0, "legal_ir_parallel_workers": 1,
        "metric_process_cache_used": False, "use_sample_memory": False,
        "pinned_source_sha256": sources,
        "script_sha256": _helpers()._sha(__file__), "runner_sha256": _helpers()._sha(RUNNER),
        "output_directory": str(args.output_directory),
        "max_output_bytes": args.max_output_bytes, "storage_bytes": args.storage_bytes,
        "memory_mb": args.memory_mb, "cpu_slots": 1, "child_process_slots": 3,
        "timeout_seconds": args.timeout_seconds,
        "artifact_format": "bundle", "validation_role": "disjoint_repeated_tuning_not_independent_canary",
        "training_executed": False, "model_weights_downloaded": False, "admitted": False,
    }


def _verify_inputs(config):
    for reference in config["plan"]["inputs"].values():
        raw = _read_regular(reference["path"], reference["bytes"])
        if len(raw) != reference["bytes"] or hashlib.sha256(raw).hexdigest() != reference["sha256"]:
            raise ValueError("input changed after preparation planning")


def _produce(config):
    """Main-thread child: use the existing producer and its full source guards."""
    expected = config["plan"]
    helpers = _helpers()
    if helpers._sha(__file__) != expected["script_sha256"] or helpers._sha(RUNNER) != expected["runner_sha256"]:
        raise ValueError("preparation wrapper changed after planning")
    if helpers._pin() != expected["pinned_source_sha256"]:
        raise ValueError("pinned producer source changed after planning")
    _verify_inputs(config)
    # Bound each file at the kernel boundary as well as the parent's polled
    # whole-attempt reservation. The bundle writer uses temporary shard files.
    _, hard = resource.getrlimit(resource.RLIMIT_FSIZE)
    cap = config["max_output_bytes"] if hard == resource.RLIM_INFINITY else min(config["max_output_bytes"], hard)
    resource.setrlimit(resource.RLIMIT_FSIZE, (cap, cap))
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_target_preparation import prepare_training_targets
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_training_worker import SampleRecord, TrainingConfig

    rows = {
        key: helpers.local_records(reference["path"])
        for key, reference in expected["inputs"].items()
    }
    selected = {key: [row["sample"] for row in values] for key, values in rows.items()}
    if hashlib.sha256(_canonical(selected).encode()).hexdigest() != expected["selection_sha256"]:
        raise ValueError("normalized input selection changed")
    training_config = TrainingConfig(
        legal_ir_bridge_names=BRIDGES, legal_ir_evaluate_provers=False,
        legal_ir_parallel_workers=1, metric_disk_cache=0, use_sample_memory=False,
    )
    started = time.perf_counter()
    result = prepare_training_targets(
        [SampleRecord.from_dict(row) for row in selected["training"]],
        Path(config["output_directory"]) / "targets.bundle",
        validation_records=[SampleRecord.from_dict(row) for row in selected["validation"]],
        training_config=training_config, artifact_format="bundle",
    )
    duration = time.perf_counter() - started
    _verify_inputs(config)
    if helpers._pin() != expected["pinned_source_sha256"]:
        raise ValueError("pinned source changed while preparing targets")
    if helpers._sha(__file__) != expected["script_sha256"] or helpers._sha(RUNNER) != expected["runner_sha256"]:
        raise ValueError("preparation wrapper changed while producing targets")
    artifact = _descriptor(Path(config["output_directory"]) / "targets.bundle")
    if result["artifact"] != artifact or artifact["bytes"] > config["max_output_bytes"]:
        raise ValueError("prepared artifact descriptor or byte bound differs")
    if (result["bridge_names"] != list(BRIDGES) or result["legal_ir_evaluate_provers"] is not False
            or result["legal_ir_parallel_workers"] != 1 or result["metric_disk_cache"] != 0
            or result["legal_ir_target_count"] != result["sample_count"]
            or not 0 < result["sample_count"] <= expected["maximum_union_target_count"]):
        raise ValueError("producer result differs from requested target configuration")
    helpers._write(Path(config["output_directory"]) / "producer.json", {
        "schema_version": "shared-target-preparation-producer/v1", "plan": expected,
        "preparation": result, "producer_call_wall_seconds": duration,
        "training_executed": False, "admitted": False,
    })


@contextmanager
def _termination_handlers():
    def stop(signum, frame):
        raise InterruptedError(f"preparation interrupted by signal {signum}")
    saved = {sig: signal.signal(sig, stop) for sig in (signal.SIGINT, signal.SIGTERM)}
    try:
        yield
    finally:
        for sig, handler in saved.items():
            signal.signal(sig, handler)


def _stop_owned(process):
    saved = {sig: signal.signal(sig, signal.SIG_IGN) for sig in (signal.SIGINT, signal.SIGTERM)}
    try:
        _helpers()._stop_group(process)
    finally:
        for sig, handler in saved.items():
            signal.signal(sig, handler)


def _supervise(config, reservation, *, child_argv=None):
    """Private injection boundary for short process-control tests; CLI argv fixed."""
    helpers = _helpers()
    directory = Path(config["output_directory"])
    started = time.monotonic()
    process = None
    stopped = False
    peak_rss, peak_processes = 0, 0
    argv = child_argv or [sys.executable, str(Path(__file__).resolve()), "--_prepare"]
    with _termination_handlers():
        try:
            with (directory / "producer.log").open("xb") as log:
                process = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=log, stderr=subprocess.STDOUT,
                                           start_new_session=True, env=os.environ.copy())
                reservation.check_usage(attempt_directory=directory, child_pid=process.pid)
                process.stdin.write((_canonical(config) + "\n").encode())
                process.stdin.close()
                next_check = time.monotonic() + 15
                next_observation = time.monotonic()
                while process.poll() is None:
                    now = time.monotonic()
                    if now - started > config["timeout_seconds"]:
                        raise TimeoutError("shared target preparation exceeded its process deadline")
                    if now >= next_check:
                        reservation.check_usage(attempt_directory=directory, child_pid=process.pid)
                        next_check = time.monotonic() + 15
                    if now >= next_observation:
                        observation = helpers._group_observation(process.pid)
                        processes = [row for row in observation["processes"] if row["state"] != "Z"]
                        peak_processes = max(peak_processes, len(processes))
                        peak_rss = max(peak_rss, sum(row["rss_bytes"] for row in processes))
                        if peak_rss > config["memory_mb"] * 1024 * 1024 or peak_processes > 3:
                            raise RuntimeError("preparation process group exceeded its reserved allowance")
                        next_observation = now + 0.5
                    time.sleep(0.05)
                _stop_owned(process)
                stopped = True
                if process.returncode != 0:
                    raise RuntimeError("target producer failed; inspect retained producer.log")
        except BaseException:
            if process is not None and not stopped:
                _stop_owned(process)
            raise
    return {"supervised_process_wall_seconds": time.monotonic() - started,
            "observed_peak_group_rss_bytes": peak_rss, "observed_max_group_process_count": peak_processes,
            "enforcement": "existing_resource_reservation_and_polled_group_usage_with_per_file_RLIMIT_FSIZE",
            "peak_scope": "polled lower bound; shared pages may be counted more than once"}


def execute(args, expected):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_daemon_resources import DaemonResourceReservation
    helpers = _helpers()
    directory = args.output_directory
    directory.mkdir(parents=True, exist_ok=False)
    ledger = args.resource_ledger
    if ledger.exists():
        roots = [row["path"] for row in json.loads(_read_regular(ledger, 8 * 1024 * 1024))["roots"]]
    else:
        roots = [str(path) for path in args.resource_root] or [str(directory)]
    if not any(directory == Path(root) or Path(root) in directory.parents for root in roots):
        raise ValueError("output directory is outside the resource ledger's named roots")
    ledger.parent.mkdir(parents=True, exist_ok=True)
    reservation = DaemonResourceReservation(
        ledger, roots=roots, storage_bytes=args.storage_bytes, memory_mb=args.memory_mb,
        cpu_slots=1, child_process_slots=3, timeout_seconds=0, ledger_lock_timeout_seconds=60,
    )
    config = {"plan": expected, "output_directory": str(directory), "memory_mb": args.memory_mb,
              "timeout_seconds": args.timeout_seconds, "max_output_bytes": args.max_output_bytes}
    started = time.monotonic()
    with reservation:
        try:
            helpers._write(directory / "plan.json", expected)
            observation = _supervise(config, reservation)
            producer_path = directory / "producer.json"
            producer = json.loads(_read_regular(producer_path, min(args.max_output_bytes, MAX_INPUT_BYTES)))
            if producer["plan"] != expected:
                raise ValueError("producer receipt does not bind requested preparation")
            preparation = producer["preparation"]
            artifact = _descriptor(directory / "targets.bundle")
            if artifact != preparation["artifact"] or artifact["bytes"] > args.max_output_bytes:
                raise ValueError("prepared artifact changed before handoff")
            _verify_inputs(config)
            if helpers._pin() != expected["pinned_source_sha256"]:
                raise ValueError("pinned source changed before handoff")
            resource_receipt = reservation.finalize(attempt_directory=directory, artifacts_durable=True)
            helpers._write(directory / "resources.json", resource_receipt)
            result = {
                "schema_version": "shared-target-preparation-handoff/v1", "plan": expected,
                "producer_receipt": _descriptor(producer_path), "target_artifact": artifact,
                "target_snapshot_id": preparation["target_snapshot_id"],
                "training_job_fields": {
                    "target_snapshot_id": preparation["target_snapshot_id"],
                    "target_snapshot_artifact": artifact,
                },
                "sample_count": preparation["sample_count"],
                "legal_ir_target_count": preparation["legal_ir_target_count"],
                "target_preparation_wall_seconds": time.monotonic() - started,
                "preparation_including_input_planning_seconds": expected["input_planning_wall_seconds"] + time.monotonic() - started,
                "supervision": observation,
                "runner_arguments": ["--shared-targets", artifact["path"], "--target-snapshot-id", preparation["target_snapshot_id"]],
                "measurement_scope": "Includes preparation and supervision; add worker target_load_seconds, complete training and qualification wall time before claiming end-to-end speedup.",
                "status_scope": "ready means target returned, not bridge acceptance, roundtrip success or Lean admission",
                "reuse_scope": "Use the same immutable target artifact for every hyperparameter candidate over these training/tuning rows. Workers independently verify bytes, source/configuration and sample content; preparation is outside each optimizer deadline.",
                "training_executed": False, "model_weights_downloaded": False, "admitted": False,
            }
            helpers._write(directory / "receipt.json", result)
            return result
        except BaseException as error:
            helpers._write(directory / "failure.json", {"error_type": type(error).__name__,
                "resources": reservation.to_dict(),
                "resource_observation_scope": "before context exit; failed attempt remains retained in the ledger",
                "admitted": False})
            raise


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input-jsonl", type=Path, required=True)
    p.add_argument("--validation-jsonl", type=Path, required=True)
    p.add_argument("--output-directory", type=Path, required=True)
    p.add_argument("--plan", action="store_true", help="Read inputs and report configuration without building or reserving resources")
    p.add_argument("--max-input-rows", type=int, default=256)
    p.add_argument("--max-input-bytes", type=int, default=MAX_INPUT_BYTES)
    p.add_argument("--max-output-bytes", type=int, default=256 * 1024 * 1024)
    p.add_argument("--storage-bytes", type=int, default=750_000_000,
                   help="Whole attempt reservation; must cover two bounded bundle files plus receipt overhead")
    p.add_argument("--memory-mb", type=int, default=8192)
    p.add_argument("--timeout-seconds", type=float, default=600)
    p.add_argument("--resource-ledger", type=Path, default=DEFAULT_LEDGER)
    p.add_argument("--resource-root", type=Path, action="append", default=[])
    p.add_argument("--bridge-names", default=",".join(BRIDGES), help="This command requires all five qualified bridges in canonical order")
    p.add_argument("--legal-ir-evaluate-provers", choices=["false"], default="false")
    p.add_argument("--metric-disk-cache", type=int, choices=[0], default=0)
    p.add_argument("--legal-ir-parallel-workers", type=int, choices=[1], default=1)
    return p


def main(argv=None):
    sys.path.insert(0, str(ROOT))
    if argv is None and sys.argv[1:] == ["--_prepare"]:
        raw = sys.stdin.buffer.readline(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024 or not raw.endswith(b"\n"):
            raise ValueError("invalid preparation request framing")
        _produce(json.loads(raw))
        return 0
    p = parser()
    args = p.parse_args(argv)
    if not 1 <= args.max_input_rows <= MAX_ROWS or not 1 <= args.max_input_bytes <= MAX_INPUT_BYTES:
        p.error("input limits must be positive and within 10000 rows / 64 MiB")
    if not 1024 * 1024 <= args.max_output_bytes <= 2 * 1024 * 1024 * 1024:
        p.error("max-output-bytes must be between 1 MiB and 2 GiB")
    if args.storage_bytes < 2 * args.max_output_bytes + OVERHEAD_BYTES or args.storage_bytes > 50_000_000_000:
        p.error("storage-bytes must cover two maximum bundle files plus 16 MiB and stay within 50 GB")
    if not 512 <= args.memory_mb <= 65536 or not math.isfinite(args.timeout_seconds) or not 1 <= args.timeout_seconds <= 43200:
        p.error("memory or timeout is outside its allowed bound")
    if tuple(args.bridge_names.split(",")) != BRIDGES:
        p.error("all five qualified bridge names in canonical order are required")
    for name in ("input_jsonl", "validation_jsonl", "output_directory", "resource_ledger"):
        path = getattr(args, name).absolute()
        if path.is_symlink():
            p.error(f"{name} cannot be a symlink")
        setattr(args, name, path.resolve())
    args.resource_root = [path.resolve() for path in args.resource_root]
    if args.output_directory.exists():
        p.error("output-directory must be new; existing bundles are consumed explicitly, never overwritten")
    expected = plan(args)
    result = expected if args.plan else execute(args, expected)
    print(_canonical(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
