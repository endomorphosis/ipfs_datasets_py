#!/usr/bin/env python3
"""Run independent, resumable autoencoder streams over local or Hub span inputs.

One coordinator owns each local registry. Network polling only retrieves census
exchanges, never model weights. Checkpoints stay private candidates; optimizer
acceptance does not provide legal or Lean admission.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[3]
PINNED = ROOT / "workspace/todo-queues/legal-ir-daemon-restart12-20260608T075001Z-best-8h-autoencoder.state.json"
PINNED_SHA = "1446cb1859ddf4ed40fb5576f6e320eece4cec268a008c5c07bffeaf959cd8dd"
DEFAULT_LEDGER = ROOT / "workspace/test-logs/federal-corpus-audits/owned-daemon-resource-control/disk-reservations.json"
MAX_INPUT_BYTES = 64 * 1024 * 1024
MAX_INPUT_ROWS = 10000


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def orchestration_hashes():
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_candidate_qualification import QUALIFICATION_DEPENDENCIES
    paths = [Path(__file__).resolve(),
             ROOT / "ipfs_datasets_py/logic/autoformal/span_cache_feed.py",
             ROOT / "ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_incremental_training.py",
             ROOT / "ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_qualified_training.py",
             ROOT / "ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_candidate_qualification.py",
             ROOT / "ipfs_datasets_py/logic/autoformal/family_qualification.py",
             ROOT / "ipfs_datasets_py/logic/modal/decompiler.py",
             ROOT / "ipfs_datasets_py/duckdb_control/autoencoder_shared_weight_control.py",
             ROOT / "ipfs_datasets_py/duckdb_control/autoencoder_quack.py",
             ROOT / "ipfs_datasets_py/duckdb_control/autoencoder_quack_wire.py",
             ROOT / "ipfs_datasets_py/huggingface/autoencoder_incremental.py",
             ROOT / "ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_training_coordinator.py",
             ROOT / "ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_daemon_resources.py",
             ROOT / "ipfs_datasets_py/duckdb_control/autoencoder_registry.py"]
    paths.extend(ROOT / "ipfs_datasets_py" / relative for relative in QUALIFICATION_DEPENDENCIES)
    paths.extend([ROOT / "ipfs_datasets_py/logic/autoformal/__init__.py",
                  ROOT / "ipfs_datasets_py/logic/autoformal/tree_pin.py"])
    result = {str(path.relative_to(ROOT)): _sha(path) for path in paths}
    lock = ROOT.parents[1] / "JevOps/jevops/statement_lock.py"
    result[str(lock)] = _sha(lock)
    return result


def _write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as stream:
        stream.write(_json(value) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def _pin(*, dataset_network=False):
    sys.path.insert(0, str(ROOT))
    os.environ.update({
        "IPFS_DATASETS_LEGAL_IR_METRIC_DISK_CACHE": "0", "CUDA_VISIBLE_DEVICES": "",
        "IPFS_DATASETS_PY_LAZY_INSTALL_ERGOAI": "0", "OPENBLAS_NUM_THREADS": "1",
        "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1",
        # Hub uses TRANSFORMERS_OFFLINE as a fallback for its own network flag.
        # Only the dataset-owning coordinator enables Hub access. Spawned
        # training workers apply the existing offline worker environment.
        "HF_HUB_OFFLINE": "0" if dataset_network else "1",
        "TRANSFORMERS_OFFLINE": "0" if dataset_network else "1",
    })
    from ipfs_datasets_py.logic.autoformal.tree_pin import require_workspace_logic_tree
    paths = require_workspace_logic_tree()
    for name, relative in {
        "autoencoder": "modal_autoencoder.py", "samples": "legal_samples.py",
        "worker": "autoencoder_training_worker.py",
    }.items():
        paths[name] = str(ROOT / "ipfs_datasets_py/optimizers/logic_theorem_optimizer" / relative)
    return {key: _sha(path) for key, path in paths.items()}


def local_records(path):
    """Read bounded JSONL SampleRecords; transport metadata is not model input."""
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_training_worker import SampleRecord
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_INPUT_BYTES:
        raise ValueError("local input must be a regular JSONL file of at most 64 MiB")
    with path.open("rb") as stream:
        raw = stream.read(MAX_INPUT_BYTES + 1)
    if len(raw) > MAX_INPUT_BYTES:
        raise ValueError("local input exceeds byte limit")
    records = {}
    input_sha = hashlib.sha256(raw).hexdigest()
    for ordinal, line in enumerate(raw.splitlines()):
        if ordinal >= MAX_INPUT_ROWS:
            raise ValueError("local input exceeds row limit")
        if not line.strip():
            continue
        sample = asdict(SampleRecord.from_dict(json.loads(line)))
        identity = hashlib.sha256(_json(sample).encode()).hexdigest()
        records[identity] = {"record_id": identity, "sample": sample,
                             "provenance": {"kind": "local_user_jsonl", "input_sha256": input_sha}}
    return [records[key] for key in sorted(records)]


def make_templates(registry, records, *, state_directory, checkpoint, source_hashes,
                   max_seconds=180.0, source_language="en", model_variant="incremental-modal",
                   arrow_feature_weights=None, shared_targets=None, target_snapshot_id=None,
                   validation_records=()):
    """Create immutable one-span templates; the runner supplies actual lane parents."""
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_training_worker import TrainingJobSpec
    state_directory = Path(state_directory)
    checkpoint = Path(checkpoint)
    checkpoint_sha = _sha(checkpoint)
    if checkpoint.resolve() == PINNED.resolve() and checkpoint_sha != PINNED_SHA:
        raise ValueError("protected restart12 checkpoint hash mismatch")
    variant = {"source_language": source_language, "target_formal_language": "typed_deontic_ir",
               "jurisdiction": "us", "model_variant": model_variant}
    variant_id = "incremental-" + hashlib.sha256(_json(variant).encode()).hexdigest()[:32]
    registry.register_variant("variant-" + variant_id, variant_id, variant)
    artifact = registry.stage_artifact(checkpoint, checkpoint_sha)
    version = registry.register_version("seed-" + variant_id + "-" + checkpoint_sha[:24], variant_id, artifact)["version_id"]
    code_identity = hashlib.sha256(_json(source_hashes).encode()).hexdigest()
    shared = {}
    for path, field in ((arrow_feature_weights, "arrow_feature_weights_artifact"),
                        (shared_targets, "target_snapshot_artifact")):
        if path:
            descriptor = registry.stage_artifact(path)
            shared[field] = {**descriptor, "path": str(registry.artifact_path(descriptor))}
    if shared_targets:
        shared["target_snapshot_id"] = target_snapshot_id
    result = []
    validation_samples = [record["sample"] for record in validation_records]
    split_identity = "qualification-validation-" + hashlib.sha256(_json(validation_samples).encode()).hexdigest()
    for record in records:
        record_id = record["record_id"].removeprefix("sha256:")
        if len(record_id) != 64 or any(char not in "0123456789abcdef" for char in record_id):
            raise ValueError("record_id must be a full lowercase SHA-256")
        provenance_path = state_directory / "inputs" / (record_id + ".json")
        if provenance_path.exists():
            old = json.loads(provenance_path.read_bytes())
            if old["record_id"] != record["record_id"] or old["sample"] != record["sample"]:
                raise ValueError("immutable input identity collision")
        else:
            _write(provenance_path, record)
        # Data identity remains stable when the same source appears in another
        # census, so polling never retrains a row simply because HEAD changed.
        result.append(TrainingJobSpec.from_dict({
            "schema_version": "autoencoder-training-job-v3",
            "job_id": "input-" + record_id, "run_id": "input-" + record_id,
            "base_version_id": version, "base_checkpoint": {
                **artifact, "path": str(registry.artifact_path(artifact))},
            "output_directory": str(state_directory / "template-outputs" / record_id),
            "code_identity": code_identity, "expected_source_sha256": source_hashes,
            "dataset_snapshot_id": record_id, "split_snapshot_id": split_identity,
            "samples": [record["sample"]], "validation_samples": [], "variant": variant,
            "autoencoder_config": {"compute_device": "python"},
            "training_config": {"max_seconds": max_seconds, "profile_projection": True,
                                "projection_max_update_families": 5},
            "capture_sparse_patches": True, "candidate_storage": "sparse",
            **shared,
        }))
    return result


def run_cycle(config):
    """Execute one bounded poll/dispatch page, in an isolated child process."""
    source_hashes = _pin(dataset_network=bool(config.get("repository_id") or config.get("publish_repository")))
    orchestration = orchestration_hashes()
    from ipfs_datasets_py.duckdb_control.autoencoder_registry import AutoencoderRegistry
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_qualified_training import run_qualified_incremental_training
    state = Path(config["state_directory"])
    records = local_records(config["input_jsonl"]) if config.get("input_jsonl") else []
    validation = local_records(config["validation_jsonl"]) if config.get("validation_jsonl") else []
    if len(validation) > 32:
        raise ValueError("qualification validation is bounded to 32 rows per cycle")
    feed_report = None
    feed = None
    skipped = []
    publications = []
    try:
        if config.get("repository_id"):
            from ipfs_datasets_py.logic.autoformal.span_cache_feed import SpanCacheFeed
            feed = SpanCacheFeed(state / "feed.duckdb", state / "feed-artifacts",
                                 repository_id=config["repository_id"], revision=config["revision"])
            feed_report = feed.poll_once(max_bundles=config["max_bundles"])
            records.extend(feed_report["records"])
        if len(records) > MAX_INPUT_ROWS:
            raise ValueError("cycle input row bound exceeded; use another feed stream")
        eligible = []
        for record in records:
            if record["sample"]["text"].strip():
                eligible.append(record)
                continue
            disposition = {"record_id": record["record_id"], "reason": "empty_source_text",
                           "training_executed": False, "admitted": False}
            identity = hashlib.sha256(_json(record).encode()).hexdigest()
            skip_path = state / "inputs" / (identity + ".skipped.json")
            if not skip_path.exists():
                _write(skip_path, {"disposition": disposition, "record": record})
            skipped.append(disposition)
        with AutoencoderRegistry(state / "control.duckdb", state / "artifacts") as registry:
            templates = make_templates(
                registry, eligible, state_directory=state, checkpoint=config["checkpoint"],
                source_hashes=source_hashes, max_seconds=config["max_seconds"],
                source_language=config["source_language"], model_variant=config["model_variant"],
                arrow_feature_weights=config.get("arrow_feature_weights"),
                shared_targets=config.get("shared_targets"), target_snapshot_id=config.get("target_snapshot_id"),
                validation_records=validation,
            )
            report = run_qualified_incremental_training(
                registry, templates, state_directory=state / "progress",
                machine_shard_count=config["shard_count"], machine_shard_index=config["shard_index"],
                lane_count=config["workers"], max_batches=config["max_batches"],
                max_training_rounds=config.get("max_training_rounds", 3),
                lake_timeout_seconds=config.get("lake_timeout_seconds", 120),
                producer_identity=orchestration,
                qualification_samples=[record["sample"] for record in validation],
                control_transport="quack",
                publication_repository=config.get("publish_repository"),
            )
            if config.get("publish_repository"):
                if orchestration_hashes() != orchestration:
                    raise RuntimeError("orchestration source changed before publication; retained outbox requires replay")
                publications = deliver_pending_updates(registry, state)
            # Successful return guarantees durable intake, including deferred
            # work. A crash before this acknowledgement repeats only intake;
            # the runner reconciles already-registered/completed batches.
            if feed is not None:
                for bundle in feed_report["new_bundles"]:
                    feed.acknowledge(bundle["manifest_in_repo"], fingerprint=bundle["fingerprint"])
    finally:
        if feed is not None:
            feed.close()
    if feed_report is not None:
        feed_report = {key: value for key, value in feed_report.items() if key != "records"}
        feed_report["new_bundles"] = [
            {key: value for key, value in bundle.items() if key != "census_rows"}
            for bundle in feed_report["new_bundles"]
        ]
    if orchestration_hashes() != orchestration:
        raise RuntimeError("orchestration source changed during cycle; retained registry work requires replay")
    receipt = {"schema": "incremental-autoencoder-cycle/v2", "feed": feed_report,
               "training": report, "input_count": len(records), "admitted": False,
               "eligible_input_count": len(eligible), "skipped_inputs": skipped,
               "formalized": False, "heldout_canary": False, "temperature": 0,
               "validation_sample_count": len(validation),
               "validation_role": "tuning_validation_repeated_candidate_selection",
               "weight_publications": publications,
               "publication_repository": config.get("publish_repository"),
               "model_weights_downloaded": False, "source_hashes": source_hashes,
               "orchestration_hashes": orchestration,
               "source_verification_scope": "pinned file contents before/after; not preloaded bytecode attestation"}
    _write(config["cycle_receipt"], receipt)
    return receipt


def deliver_pending_updates(registry, state):
    """Retry durable delivery even when a poll dispatches no new training."""
    from ipfs_datasets_py.huggingface.autoencoder_incremental import deliver_sparse_update
    publications = []
    for event in registry.pending_outbox("huggingface", limit=16):
        try:
            publications.append(deliver_sparse_update(registry, event["event_id"], upload=True,
                state_directory=Path(state) / "publication-deliveries"))
        except Exception as exc:
            # Avoid copying HTTP response bodies or credentials into telemetry.
            # The durable lease/event remains available to the next owner poll.
            publications.append({"event_id": event["event_id"], "uploaded": False,
                "retry_pending": True, "error_type": type(exc).__name__,
                "http_status": getattr(getattr(exc, "response", None), "status_code", None),
                "admitted": False})
    return publications


def _stop_group(process):
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass
    # The coordinator can exit before a worker. Always reap the complete group.
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.wait(timeout=10)


def _group_observation(group_pid):
    """Read process identities and CPU ticks without exposing command lines."""
    processes = []
    for path in Path("/proc").iterdir():
        if not path.name.isdigit():
            continue
        try:
            raw = (path / "stat").read_text()
            fields = raw[raw.rfind(")") + 2:].split()
            if int(fields[2]) == group_pid:
                processes.append({"pid": int(path.name), "state": fields[0], "birth": fields[19],
                                  "cpu_ticks": int(fields[11]) + int(fields[12]),
                                  "rss_bytes": int(fields[21]) * os.sysconf("SC_PAGE_SIZE")})
        except (FileNotFoundError, ProcessLookupError, PermissionError):
            continue
    return {"wall_time": time.time(), "processes": sorted(processes, key=lambda row: row["pid"])}


def supervised_cycle(config):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_daemon_resources import DaemonResourceReservation
    state = Path(config["state_directory"])
    ledger = Path(config["resource_ledger"])
    ledger.parent.mkdir(parents=True, exist_ok=True)
    if ledger.exists():
        roots = [row["path"] for row in json.loads(ledger.read_bytes())["roots"]]
    else:
        roots = config["resource_roots"] or [str(state)]
    if not any(state == Path(root) or Path(root) in state.parents for root in roots):
        raise ValueError("state directory is outside the resource ledger's named roots")
    cycle_id = uuid.uuid4().hex
    receipt_directory = state / "cycles" / cycle_id
    receipt_directory.mkdir(parents=True)
    child_config = {**config, "cycle_receipt": str(receipt_directory / "cycle.json")}
    reservation = DaemonResourceReservation(
        ledger, roots=roots, storage_bytes=config["storage_bytes"], memory_mb=config["memory_mb"],
        cpu_slots=config["workers"], timeout_seconds=0, ledger_lock_timeout_seconds=60,
    )
    started = time.monotonic()
    process = None
    observations = []
    with reservation:
        try:
            with (receipt_directory / "worker.log").open("xb") as log:
                process = subprocess.Popen(
                    [sys.executable, str(Path(__file__).resolve()), "--_cycle"],
                    stdin=subprocess.PIPE, stdout=log, stderr=subprocess.STDOUT,
                    start_new_session=True, env=os.environ.copy(),
                )
                # Child blocks on stdin until its process identity and allowance
                # are durably recorded in the existing host resource ledger.
                reservation.check_usage(attempt_directory=state, child_pid=process.pid)
                process.stdin.write((_json(child_config) + "\n").encode())
                process.stdin.close()
                next_check = time.monotonic()
                next_observation = next_check
                while process.poll() is None:
                    if time.monotonic() - started > config["cycle_timeout"]:
                        raise TimeoutError("incremental training cycle exceeded its process deadline")
                    if time.monotonic() >= next_check:
                        reservation.check_usage(attempt_directory=state, child_pid=process.pid)
                        next_check = time.monotonic() + 15
                    if time.monotonic() >= next_observation:
                        observations.append(_group_observation(process.pid))
                        next_observation = time.monotonic() + 2
                    time.sleep(0.5)
                _stop_group(process)
                if process.returncode:
                    raise RuntimeError(f"training cycle exited {process.returncode}; see {receipt_directory / 'worker.log'}")
            reservation.check_usage(attempt_directory=state)
            receipt = json.loads(Path(child_config["cycle_receipt"]).read_bytes())
            if not (receipt_directory / "process-observations.json").exists():
                _write(receipt_directory / "process-observations.json", observations)
            resource = reservation.release(artifacts_durable=True)
            _write(receipt_directory / "resources.json", resource)
            return {"receipt": child_config["cycle_receipt"], "elapsed_seconds": time.monotonic() - started,
                    "input_count": receipt["input_count"], "training": receipt["training"],
                    "weight_publications": receipt["weight_publications"], "admitted": False}
        except BaseException:
            if process is not None:
                _stop_group(process)
            if not (receipt_directory / "process-observations.json").exists():
                _write(receipt_directory / "process-observations.json", observations)
            _write(receipt_directory / "retained-resources.json", reservation.to_dict())
            raise


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--state-directory", type=Path, required=True)
    p.add_argument("--checkpoint", type=Path, default=PINNED)
    p.add_argument("--arrow-feature-weights", type=Path, help="Optional local baseline-bound Arrow IPC weights")
    p.add_argument("--shared-targets", type=Path, help="Optional local verified target artifact covering all input rows")
    p.add_argument("--target-snapshot-id", help="Exact snapshot identity, required with --shared-targets")
    p.add_argument("--input-jsonl", type=Path)
    p.add_argument("--validation-jsonl", type=Path,
                   help="Disjoint tuning validation (max 32 rows); missing validation fails qualification")
    p.add_argument("--repository-id", help="Optional census exchange dataset to poll")
    p.add_argument("--publish-repository", choices=["justicedao/uscode-autoformal-span-cache"],
                   help="Upload qualified sparse updates and proof evidence through the durable registry outbox")
    p.add_argument("--revision", default="main")
    p.add_argument("--workers", type=int, default=2)
    p.add_argument("--shard-count", type=int, default=1)
    p.add_argument("--shard-index", type=int, default=0)
    p.add_argument("--max-batches", type=int, default=4, help="Optimizer attempts per cycle, including qualification retries")
    p.add_argument("--max-training-rounds", type=int, default=3, help="Maximum attempts per span before durable repair work")
    p.add_argument("--lake-timeout-seconds", type=int, default=120)
    p.add_argument("--max-bundles", type=int, default=4)
    p.add_argument("--max-seconds", type=float, default=180)
    p.add_argument("--polls", type=int, default=1, help="0 runs until interrupted")
    p.add_argument("--sync-interval", type=float, default=300)
    p.add_argument("--cycle-timeout", type=float, default=900)
    p.add_argument("--source-language", default="en")
    p.add_argument("--model-variant", default="incremental-modal")
    p.add_argument("--memory-mb", type=int, default=8192, help="Whole coordinator/worker group allowance")
    p.add_argument("--storage-bytes", type=int, default=1_000_000_000)
    p.add_argument("--resource-ledger", type=Path, default=DEFAULT_LEDGER)
    p.add_argument("--resource-root", type=Path, action="append", default=[])
    return p


def main(argv=None):
    if argv is None and sys.argv[1:] == ["--_cycle"]:
        raw = sys.stdin.buffer.readline(1024 * 1024 + 1)
        if not raw or len(raw) > 1024 * 1024:
            raise ValueError("missing bounded parent release")
        run_cycle(json.loads(raw))
        return 0
    p = parser()
    args = p.parse_args(argv)
    if not args.input_jsonl and not args.repository_id:
        p.error("supply --input-jsonl and/or --repository-id")
    if bool(args.shared_targets) != bool(args.target_snapshot_id):
        p.error("--shared-targets and --target-snapshot-id must be supplied together")
    if not 1 <= args.workers <= 8 or not 1 <= args.shard_count <= 1024 or not 0 <= args.shard_index < args.shard_count:
        p.error("invalid worker count or machine shard assignment")
    if not 1 <= args.max_batches <= 128 or not 1 <= args.max_bundles <= 128 or args.polls < 0:
        p.error("invalid bounded dispatch/poll count")
    if not 1 <= args.max_training_rounds <= 100 or not 1 <= args.lake_timeout_seconds <= 600:
        p.error("training rounds must be 1..100 and Lake timeout 1..600 seconds")
    for name in ("max_seconds", "cycle_timeout", "sync_interval"):
        if not math.isfinite(getattr(args, name)) or getattr(args, name) <= 0:
            p.error(f"{name} must be finite and positive")
    if args.max_seconds > 300 or args.memory_mb < 256 or not 1 <= args.storage_bytes <= 50_000_000_000:
        p.error("optimizer budget <=300 seconds, memory >=256 MiB, storage <=50 GB required")
    state = args.state_directory.absolute()
    state.mkdir(parents=True, exist_ok=True)
    config = vars(args).copy()
    for name in ("state_directory", "checkpoint", "input_jsonl", "validation_jsonl", "resource_ledger", "arrow_feature_weights", "shared_targets"):
        config[name] = str(Path(config[name]).absolute()) if config[name] is not None else None
    config["resource_roots"] = [str(path.absolute()) for path in config.pop("resource_root")]
    _pin()
    with (state / "runner.lock").open("a+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            p.error("another incremental runner owns this state directory")
        cycle = 0
        while args.polls == 0 or cycle < args.polls:
            report = supervised_cycle(config)
            print(_json({"cycle": cycle, **report}), flush=True)
            cycle += 1
            if args.polls == 0 or cycle < args.polls:
                time.sleep(args.sync_interval)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
