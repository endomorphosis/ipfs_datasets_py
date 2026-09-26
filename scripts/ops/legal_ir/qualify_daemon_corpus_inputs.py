#!/usr/bin/env python3
"""Qualify owner-issued local inputs through the unmodified daemon parser/main.

The default runs a bounded startup/input walk, not a training cycle. An explicit
--native-cycle additionally permits one native cycle with default asynchronous
snapshot evaluation. No loader, sample factory, evaluator or trainer is replaced.
Historical ownership is exported into a distinct private owner; neither the old
database nor its CAS is opened for writing. Failed attempts are never retried.
"""
from __future__ import annotations

import argparse
import copy
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import signal
import struct
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parents[3]
HISTORICAL = ROOT / "workspace/test-logs/federal-corpus-audits/shared-target-native-20260925"
DATABASE = HISTORICAL / "control.duckdb"
DATABASE_SHA = "b9b7aa3079a391bc1017d1b45b5f53b268e9703686f6c69a621690729b55e2a9"
JOB_SHA = "a75fae70c7e7208d3b0894964cfd451c1b2e438a1bca0abaf7c0a4a75268ffa6"
JOB_CANONICAL = "4695002b6021d31db51f2ffd075da96ba113a269c161d6f7f1decd8cda80ce1c"
PINNED = ROOT / "workspace/todo-queues/legal-ir-daemon-restart12-20260608T075001Z-best-8h-autoencoder.state.json"
PINNED_SHA = "1446cb1859ddf4ed40fb5576f6e320eece4cec268a008c5c07bffeaf959cd8dd"
PINNED_BYTES = 25895338
SECCOMP_SCRIPT = Path(__file__).with_name("audit_native_uscode_embedding_production.py")
SECCOMP_SHA = "381f0bbb08229fcc15add4faf259be07d895d4502f44cc573265ef4f72cb8fb6"
BRIDGES = ["modal_frame_logic", "deontic_norms", "fol_tdfol", "cec_dcec", "external_prover_router"]
ENVIRONMENT = {
    "IPFS_DATASETS_LEGAL_IR_METRIC_DISK_CACHE": "0", "IPFS_DATASETS_LEGAL_IR_ADAPTER_WORKERS": "1",
    "IPFS_DATASETS_LEGAL_IR_PARALLEL_WORKERS": "1", "IPFS_DATASETS_MODAL_AUTOENCODER_AUTO_CUDA": "0",
    "IPFS_DATASETS_PY_LAZY_INSTALL_ERGOAI": "0", "CUDA_VISIBLE_DEVICES": "",
    "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
    "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1",
}
MAX_JSON_BYTES = 64 * 1024 * 1024
MAX_CHECKPOINT_BYTES = 256 * 1024 * 1024
MAX_SOURCE_BYTES = 512 * 1024 * 1024
STARTUP_TIMEOUT = 180
NATIVE_TIMEOUT = 900
RUN_ID = "owner-local-input-qualification"
EVALUATIONS = ("autoencoder_before_train", "autoencoder_before_validation",
               "autoencoder_after_train", "autoencoder_after_validation")


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def read(path, limit=MAX_JSON_BYTES):
    path = Path(path)
    if not 0 < path.stat().st_size <= limit:
        raise ValueError("JSON outside qualification byte bound: " + str(path))
    return json.loads(path.read_bytes())


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")


def descriptor(path):
    path = Path(path).resolve()
    return {"path": str(path), "sha256": sha(path), "bytes": path.stat().st_size}


def verify(ref):
    path = Path(ref["path"])
    if path.stat().st_size != ref["bytes"] or sha(path) != ref["sha256"]:
        raise ValueError("artifact descriptor mismatch: " + str(path))


def source_manifest():
    """Guard the complete package, including newly added source files."""
    files = sorted((ROOT / "ipfs_datasets_py").rglob("*.py"))
    if len(files) > 20000:
        raise ValueError("source inventory exceeds qualification bound")
    result, size = {}, 0
    for path in files:
        if path.is_dir():
            continue
        if not path.is_file() or ROOT not in path.resolve().parents:
            raise ValueError("package source escaped canonical checkout")
        size += path.stat().st_size
        if size > MAX_SOURCE_BYTES:
            raise ValueError("source inventory exceeds byte bound")
        result[path.relative_to(ROOT).as_posix()] = sha(path)
    return result


def producer_config():
    """Use the established complete producer/runtime/dependency fingerprint."""
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_target_preparation import target_snapshot_config
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_training_worker import TrainingConfig, _worker_environment
    with _worker_environment():
        return target_snapshot_config(TrainingConfig.from_dict({
            "legal_ir_bridge_names": BRIDGES, "legal_ir_evaluate_provers": False,
            "legal_ir_parallel_workers": 1, "metric_disk_cache": 0,
        })).to_dict()


def vector_digest(values):
    """Exact little-endian float32 bits, preserving signed zero."""
    if len(values) != 384:
        raise ValueError("native GTE vector must have 384 components")
    chunks = []
    for value in values:
        if type(value) is not float or not math.isfinite(value):
            raise ValueError("native vector requires finite Python floats")
        raw = struct.pack("<f", value)
        if struct.unpack("<f", raw)[0] != value:
            raise ValueError("native vector is not exact float32")
        chunks.append(raw)
    return hashlib.sha256(b"".join(chunks)).hexdigest()


def expected_rows(payload):
    if payload.get("schema_version") != "autoencoder-training-job-v6":
        raise ValueError("qualification requires the owner-registered v6 input job")
    result = {}
    for role, key in (("train", "samples"), ("validation", "validation_samples")):
        rows = payload[key]
        if len(rows) != 3:
            raise ValueError("qualification requires exactly three records per role")
        result[role] = []
        for record in rows:
            if record["embedding_model"] != "thenlper/gte-small":
                raise ValueError("qualification requires native GTE vectors")
            result[role].append({"record": record, "vector_float32_sha256": vector_digest(record["embedding_vector"])})
    return result


def audit_inputs(snapshot, payload):
    """Walk the real reader/factory; compare against independent staged job values."""
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_daemon_corpus_inputs import (
        DaemonCorpusInputDescriptor, VerifiedDaemonCorpusInputs,
    )
    expected = expected_rows(payload)
    result = {"roles": {}, "ordinary_sample_lists": True}
    with VerifiedDaemonCorpusInputs(DaemonCorpusInputDescriptor(**snapshot)) as inputs:
        if inputs.row_count != 6:
            raise ValueError("input snapshot changed exact six-record membership")
        roles = {role: tuple(inputs.indices_for(role)) for role in expected}
        if set(roles["train"]) & set(roles["validation"]) or set(roles["train"] + roles["validation"]) != set(range(6)):
            raise ValueError("input snapshot roles are not the exact disjoint inventory")
        for role, rows in expected.items():
            if len(roles[role]) != len(rows):
                raise ValueError("input snapshot role membership differs")
            samples, observations = [], []
            for index, item in zip(roles[role], rows):
                sample = inputs.build_sample(index)
                record = item["record"]
                for field in ("title", "section", "text", "citation", "embedding_model"):
                    if getattr(sample, field) != record[field]:
                        raise ValueError("native input sample field differs: " + field)
                if type(sample.embedding_vector) is not list or vector_digest(sample.embedding_vector) != item["vector_float32_sha256"]:
                    raise ValueError("native input vector bits or list ownership differ")
                samples.append(sample)
                observations.append({"index": index, "record_id": inputs.record_id(index), "sample_id": sample.sample_id,
                    "text_sha256": hashlib.sha256(sample.text.encode()).hexdigest(),
                    "vector_float32_sha256": item["vector_float32_sha256"], "dimensions": 384})
            inputs.verify_selected(roles[role], samples, role=role)
            result["roles"][role] = observations
        inputs.verify_boundary("qualification_input_walk")
        result["verification"] = inputs.summary()
    result["closed_summary"] = inputs.summary()
    return result


def historical_export(directory, receipt):
    """Read the old owner, then register a distinct job in a new private owner."""
    import duckdb
    from ipfs_datasets_py.duckdb_control.autoencoder_registry import AutoencoderRegistry
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_training_worker import TrainingJobSpec, verify_corpus_job_inputs
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_daemon_corpus_inputs import export_daemon_corpus_inputs

    original_db = {"path": str(DATABASE), "sha256": DATABASE_SHA, "bytes": 7876608}
    verify(original_db)
    cx = duckdb.connect(str(DATABASE), read_only=True)
    try:
        root, generation = cx.execute("SELECT artifact_root,owner_generation FROM autoencoder_control.meta WHERE singleton=1").fetchone()
        variant_id, base_id, spec_raw, status = cx.execute(
            "SELECT variant_id,base_version_id,spec,status FROM autoencoder_control.runs WHERE run_id='fresh-json'").fetchone()
        owner_spec = json.loads(spec_raw)
        variant = json.loads(cx.execute("SELECT manifest FROM autoencoder_control.variants WHERE variant_id=?", [variant_id]).fetchone()[0])
        base_artifact_raw, base_metadata_raw, parent_version = cx.execute(
            "SELECT artifact,metadata,parent_version_id FROM autoencoder_control.versions WHERE version_id=?", [base_id]).fetchone()
    finally:
        cx.close()
    if root != str(HISTORICAL / "artifacts") or status != "completed" or parent_version is not None:
        raise ValueError("historical owner anchor changed")
    if owner_spec != {"job_spec_artifact": {"bytes": 81449, "sha256": JOB_SHA}, "job_spec_sha256": JOB_CANONICAL}:
        raise ValueError("historical registered job differs from fixed anchor")
    old_job_ref = {**owner_spec["job_spec_artifact"], "path": str(Path(root) / JOB_SHA[:2] / JOB_SHA)}
    verify(old_job_ref)
    payload = read(old_job_ref["path"])
    old_spec = TrainingJobSpec.from_dict(payload)
    if old_spec.canonical_sha256 != JOB_CANONICAL or old_spec.base_version_id != base_id:
        raise ValueError("historical job canonical/base identity differs")
    expected_rows(payload)
    if old_spec.target_snapshot_artifact is not None or old_spec.base_checkpoint_dependencies:
        raise ValueError("qualification must not inherit target artifacts or checkpoint chains")
    receipt["historical_input_verification"] = verify_corpus_job_inputs(old_spec)
    base_artifact, base_metadata = json.loads(base_artifact_raw), json.loads(base_metadata_raw)
    if base_artifact != {"sha256": PINNED_SHA, "bytes": PINNED_BYTES}:
        raise ValueError("historical registered base differs from protected checkpoint")
    refs = [payload[k] for k in ("base_checkpoint", "corpus_manifest_artifact", "corpus_index_artifact", "embedding_production_artifact")]
    refs += payload["corpus_source_artifacts"]
    for ref in refs:
        if Path(ref["path"]) != Path(root) / ref["sha256"][:2] / ref["sha256"]:
            raise ValueError("historical input path escaped registered CAS")
        verify(ref)
    receipt["historical_guards"] = [original_db, old_job_ref, *refs]
    receipt["historical_owner"] = {"database": original_db, "owner_generation": generation, "run_id": "fresh-json",
        "variant_id": variant_id, "base_version_id": base_id, "job_spec_canonical_sha256": JOB_CANONICAL,
        "job_spec_artifact": old_job_ref, "opened_read_only": True}
    owner_dir = directory / "private-owner"
    with AutoencoderRegistry(owner_dir / "control.duckdb", owner_dir / "artifacts") as owner:
        staged = {}
        for ref in refs:
            item = owner.stage_artifact(ref["path"], expected_sha256=ref["sha256"])
            staged[ref["sha256"]] = {**item, "path": str(owner.artifact_path(item))}
        owner.register_variant("import-variant", variant_id, variant)
        version = owner.register_version("import-base", variant_id, base_artifact, metadata=base_metadata)["version_id"]
        if version != base_id:
            raise ValueError("exact variant/base export changed content identity")
        owner.initialize_head("initialize-private-head", variant_id, "qualification", version)
        copied = copy.deepcopy(payload)
        for key in ("base_checkpoint", "corpus_manifest_artifact", "corpus_index_artifact", "embedding_production_artifact"):
            copied[key] = staged[payload[key]["sha256"]]
        copied["corpus_source_artifacts"] = [staged[ref["sha256"]] for ref in payload["corpus_source_artifacts"]]
        copied.update(job_id="local-input-export", run_id="local-input-export", output_directory=str(owner_dir / "unused-worker-output"),
            code_identity="owner-exported-input-only; no training-worker dispatch", expected_source_sha256={})
        job = TrainingJobSpec.from_dict(copied)
        job_path = owner_dir / "exported-job.json"
        write(job_path, job.to_dict())
        staged_job = owner.stage_artifact(job_path)
        owner.create_run("create-exported-run", job.run_id, variant_id, version,
            {"job_spec_sha256": job.canonical_sha256, "job_spec_artifact": staged_job})
        issued = export_daemon_corpus_inputs(owner, job.run_id, operation_id="issue-local-inputs")
        receipt["private_owner"] = {"database": str(owner.database_path), "artifact_root": str(owner.artifact_root),
            "run_id": job.run_id, "job_spec_canonical_sha256": job.canonical_sha256, "job_spec_artifact": staged_job,
            "input_issuance": issued, "head_before": owner.resolve_head(variant_id, "qualification")}
    with AutoencoderRegistry(owner_dir / "control.duckdb", owner_dir / "artifacts") as owner:
        reopened = export_daemon_corpus_inputs(owner, job.run_id, operation_id="issue-local-inputs")
        run = owner.get_run(job.run_id)
        receipt["private_owner"].update(issuance_identical_after_restart=reopened == issued,
            run_unleased=run["status"] == "queued" and run["lease"] is None,
            head_after=owner.resolve_head(variant_id, "qualification"))
    receipt["private_owner"]["database_after_export"] = descriptor(owner_dir / "control.duckdb")
    if (reopened != issued or not receipt["private_owner"]["run_unleased"]
            or receipt["private_owner"]["head_before"] != receipt["private_owner"]["head_after"]):
        raise ValueError("owner issuance restart or unleased input-only contract failed")
    for ref in receipt["historical_guards"]:
        verify(ref)
    return issued["descriptor"], job.to_dict()


def daemon_argv(snapshot, capacity, *, native_cycle):
    argv = ["--run-id", RUN_ID, "--loop-role", "autoencoder", "--max-cycles", "1",
        "--duration-seconds", "600" if native_cycle else "0", "--train-count", "3", "--validation-count", "3",
        "--validation-canary-count", "0", "--sampling-seed", "9", "--max-sample-text-chars", "0",
        "--autoencoder-canonical-warm-start", "off", "--autoencoder-device", "python",
        "--autoencoder-max-generalizable-entries-per-group", str(capacity),
        "--bridge-loss-adapters", ",".join(BRIDGES), "--autoencoder-metric-bridge-adapters", ",".join(BRIDGES),
        "--autoencoder-diagnostic-bridge-adapters", ",".join(BRIDGES), "--bridge-evaluate-provers", "false",
        "--autoencoder-bridge-workers", "1", "--autoencoder-metric-bridge-max-sample-text-chars", "0",
        "--generalizable-projection-epochs", "1", "--generalizable-projection-max-update-families", "1",
        "--generalizable-projection-max-line-search-attempts", "1", "--generalizable-projection-timeout-seconds", "180",
        "--learning-rate", "0.35", "--autoencoder-before-train-eval-mode", "every_cycle",
        "--compiler-ir-train-mode", "off", "--compiler-ir-guided-train-mode", "off",
        "--autoencoder-sample-memory-probe-mode", "off", "--autoencoder-todo-supervisor-mode", "off",
        "--max-items", "0", "--max-inner-iterations", "1", "--autoencoder-introspection-mode", "off", "--test-every-cycles", "0",
        "--leanstral-rule-gap-projection-enabled", "false", "--leanstral-rule-gap-wait-seconds", "0",
        "--leanstral-direct-guidance-projection-enabled", "false", "--leanstral-direct-guidance-train-autoencoder", "false",
        "--daemon-hammer-guidance-enabled", "false", "--daemon-hammer-guidance-train-autoencoder", "false",
        "--daemon-hammer-guidance-max-samples-per-cycle", "0", "--codex-exec-mode", "packet_only",
        "--codex-apply-mode", "patch_only", "--codex-commit-mode", "none",
        "--autoencoder-corpus-input", snapshot["path"], "--autoencoder-corpus-input-sha256", snapshot["sha256"],
        "--autoencoder-corpus-input-bytes", str(snapshot["bytes"])]
    # Deliberately omit --snapshot-evaluation-enabled: exercise the public default.
    return argv


def persistence_checks(summary, checkpoint):
    persisted = summary.get("final_state_persistence", {})
    writer = summary.get("async_artifact_writer", {})
    return {"drained": summary.get("async_artifact_writer_shutdown", {}).get("drained") is True,
        "durable": persisted.get("durable") is True,
        "checksum_matches": persisted.get("checksum") == checkpoint["sha256"],
        "bytes_match": persisted.get("written_bytes") == checkpoint["bytes"],
        "writer_failed_count_zero": writer.get("failed_count") == 0}


def input_session_checks(summary, snapshot, *, native_cycle):
    inputs = summary.get("corpus_inputs", {})
    return {"exact_descriptor": summary.get("corpus_input_descriptor") == snapshot,
        "exact_identity": summary.get("corpus_input_identity") == {k: snapshot[k] for k in ("sha256", "bytes")},
        "closed": inputs.get("closed") is True, "not_poisoned": inputs.get("poisoned") is False,
        "integrity_verified": inputs.get("input_integrity_verified") is True,
        "no_failure": inputs.get("failure") is None and not summary.get("corpus_input_failure"),
        "partition_counts": inputs.get("partition_counts") == {"train": 3, "validation": 3},
        "boundary_checks": inputs.get("counts", {}).get("boundary_checks", 0) >= 3,
        "selection_checks": inputs.get("counts", {}).get("selected_checks", -1) >= (4 if native_cycle else 0),
        "rows_consumed": inputs.get("counts", {}).get("samples_built", -1) >= (6 if native_cycle else 0)}


def bridge_diagnostics_complete(block):
    return (block.get("sample_count") == 3 and block.get("evaluated_count") == 15
        and block.get("metric_failures") == 0 and block.get("adapter_metrics_complete") is True
        and set(block.get("adapters", {})) == set(BRIDGES)
        and all(row.get("sample_count") == row.get("evaluated_count") == 3
            and row.get("metric_failures") == 0 for row in block["adapters"].values()))


def memory_observation():
    import resource
    result = {"max_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}
    with Path("/proc/self/smaps_rollup").open() as stream:
        for line in stream:
            if line.startswith(("Rss:", "Pss:")):
                key, value, _ = line.split()
                result[key[:-1].lower() + "_kib"] = int(value)
    return result


def snapshot_checks(summary):
    evaluator = summary.get("snapshot_evaluator", {})
    published, promoted = summary.get("latest_published_snapshot", {}), summary.get("latest_promoted_snapshot_evaluation", {})
    return {"default_enabled": summary.get("snapshot_evaluation_enabled") is True,
        "shutdown_drained": summary.get("snapshot_shutdown", {}).get("drained") is True,
        "closed": evaluator.get("closed") is True, "worker_stopped": evaluator.get("worker_alive") is False,
        "one_published": evaluator.get("published_snapshots") == 1,
        "one_completed": evaluator.get("completed_evaluations") == 1,
        "no_failures": evaluator.get("failed_evaluations") == 0,
        "no_rejections": evaluator.get("rejected_result_count") == 0,
        "version_match": bool(published) and promoted.get("versions") == published.get("versions")
            and promoted.get("sequence") == published.get("sequence"),
        "complete": summary.get("latest_promoted_snapshot_complete") is True}


def daemon_child(spec, result):
    from ipfs_datasets_py.logic.autoformal.tree_pin import require_workspace_logic_tree
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import uscode_modal_daemon_runner as runner
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder_checkpoint import load_checkpoint

    result["tree_pin"] = require_workspace_logic_tree()
    if source_manifest() != spec["source_manifest"]:
        raise ValueError("source changed before offline child")
    result["producer_config_before"] = producer_config()
    if canonical(result["producer_config_before"]) != canonical(spec["producer_config"]):
        raise ValueError("producer runtime/configuration changed before offline child")
    result["input_walk_before"] = audit_inputs(spec["snapshot"], spec["payload"])
    work = Path(spec["work_directory"])
    work.mkdir()  # An existing workspace is not a valid retry.
    os.chdir(work)
    state_path = work / "workspace/todo-queues" / (RUN_ID + ".state.json")
    state_path.parent.mkdir(parents=True)
    verify({"path": str(PINNED), "sha256": PINNED_SHA, "bytes": PINNED_BYTES})
    with PINNED.open("rb") as src, state_path.open("xb") as dst:
        shutil.copyfileobj(src, dst, 1024 * 1024)
    initial = load_checkpoint(state_path, recover=False)
    result["initial_checkpoint"] = descriptor(state_path)
    result["initial_state_identity"] = initial.state.state_identity_record().to_dict()
    capacity = max(8192, initial.state.generalizable_entry_count() + 1)
    overlap = set(initial.state.decoded_embeddings) | set(initial.state.family_logits)
    expected_validation = {row["sample_id"] for row in result["input_walk_before"]["roles"]["validation"]}
    if overlap & expected_validation:
        raise ValueError("pinned state already contains declared validation sample memory")
    del initial
    argv = daemon_argv(spec["snapshot"], capacity, native_cycle=spec["native_cycle"])
    result["argv"] = argv
    args = runner.build_uscode_modal_daemon_arg_parser().parse_args(argv)
    if args.snapshot_evaluation_enabled is not True:
        raise ValueError("default asynchronous snapshot behavior changed")
    result["effective_arguments"] = {k: str(v) if isinstance(v, Path) else v for k, v in vars(args).items()}
    result["memory_before_daemon"] = memory_observation()
    started = time.perf_counter()
    try:
        result["daemon_exit_code"] = runner.main(argv)
    finally:
        result["daemon_seconds_including_shutdown"] = time.perf_counter() - started
        result["memory_after_daemon_before_audit"] = memory_observation()
    summary_path = work / "workspace/test-logs" / (RUN_ID + ".summary")
    result["summary"] = summary = read(summary_path)
    result["summary_artifact"] = descriptor(summary_path)
    result["input_walk_after"] = audit_inputs(spec["snapshot"], spec["payload"])
    if result["input_walk_before"]["roles"] != result["input_walk_after"]["roles"]:
        raise ValueError("native inputs changed across actual main")
    if state_path.stat().st_size > MAX_CHECKPOINT_BYTES:
        raise ValueError("private final checkpoint exceeds cap")
    result["final_checkpoint"] = descriptor(state_path)
    result["default_async_snapshots_enabled"] = summary.get("snapshot_evaluation_enabled") is True
    result["input_session_checks"] = input_session_checks(summary, spec["snapshot"], native_cycle=spec["native_cycle"])
    if not spec["native_cycle"]:
        persisted = summary.get("final_state_persistence", {})
        if persisted.get("checkpoint_enqueued") is True:
            result["startup_persistence_checks"] = persistence_checks(summary, result["final_checkpoint"])
        else:
            result["startup_persistence_checks"] = {
                "checkpoint_not_enqueued": persisted.get("checkpoint_enqueued") in (None, False),
                "initial_private_checkpoint_preserved": result["final_checkpoint"]["sha256"] == PINNED_SHA
                    and result["final_checkpoint"]["bytes"] == PINNED_BYTES}
            result["startup_checkpoint_skipped_reason"] = "zero completed cycles; original private checkpoint must remain exact"
        evaluator = summary.get("snapshot_evaluator", {})
        result["startup_snapshot_checks"] = {"closed": evaluator.get("closed") is True,
            "worker_stopped": evaluator.get("worker_alive") is False,
            "no_evaluations": evaluator.get("published_snapshots") == evaluator.get("completed_evaluations") == 0,
            "no_failures": evaluator.get("failed_evaluations") == 0}
        result["passed"] = (result["daemon_exit_code"] == 0 and summary.get("cycles") == 0
            and result["default_async_snapshots_enabled"] and summary.get("snapshot_shutdown", {}).get("drained") is True
            and summary.get("async_artifact_writer_shutdown", {}).get("drained") is True
            and all(result["input_session_checks"].values()) and all(result["startup_persistence_checks"].values())
            and all(result["startup_snapshot_checks"].values()))
        return
    log_path = summary_path.with_suffix(".jsonl")
    cycles = []
    with log_path.open() as stream:
        for line in stream:
            if len(line) > MAX_JSON_BYTES:
                raise ValueError("native log record exceeds cap")
            row = json.loads(line)
            if row.get("event") == "cycle":
                cycles.append(row)
    if len(cycles) != 1:
        raise ValueError("native main did not persist exactly one cycle")
    result["cycle"] = cycle = cycles[0]
    result["log_artifact"] = descriptor(log_path)
    roles = result["input_walk_before"]["roles"]
    result["selected_roles_exact"] = (set(cycle["train_indices"]) == {r["index"] for r in roles["train"]}
        and set(cycle["validation_indices"]) == {r["index"] for r in roles["validation"]}
        and len(cycle["train_indices"]) == len(cycle["validation_indices"]) == 3)
    result["target_counts_positive"] = all(cycle[k].get("legal_ir_target_count") == 3 for k in EVALUATIONS)
    result["complete_bridge_diagnostics"] = all(bridge_diagnostics_complete(cycle[key])
        for key in ("logic_bridge_train", "logic_bridge_validation"))
    result["persistence_checks"] = persistence_checks(summary, result["final_checkpoint"])
    result["snapshot_checks"] = snapshot_checks(summary)
    result["snapshot_proof_metrics"] = summary.get("latest_promoted_snapshot_evaluation", {}).get("metrics", {}).get("proof")
    result["passed"] = (result["daemon_exit_code"] == 0 and summary.get("cycles") == 1
        and result["selected_roles_exact"] and result["target_counts_positive"]
        and result["complete_bridge_diagnostics"] and all(result["input_session_checks"].values())
        and all(result["persistence_checks"].values()) and all(result["snapshot_checks"].values()))


def child_main(spec_path, output):
    spec = read(spec_path)
    result = {"schema": "owner-local-daemon-input-child-v1", "passed": False, "harness_sha256": sha(__file__),
        "native_cycle_requested": spec["native_cycle"], "model_weights_downloaded": False,
        "callable_replacements": [], "entrypoint": "uscode_modal_daemon_runner.main(argv)"}
    started = time.perf_counter()
    try:
        if sha(SECCOMP_SCRIPT) != SECCOMP_SHA:
            raise ValueError("frozen OS network guard helper changed")
        from audit_native_uscode_embedding_production import _deny_network
        result["network_guard"] = _deny_network()
        daemon_child(spec, result)
    except BaseException as exc:
        result["error"] = {"type": type(exc).__module__ + "." + type(exc).__qualname__, "message": str(exc)[:4096]}
    finally:
        try:
            result["source_unchanged"] = source_manifest() == spec["source_manifest"]
            result["producer_config_after"] = producer_config()
            result["producer_config_unchanged"] = canonical(result["producer_config_after"]) == canonical(spec["producer_config"])
            result["protected_checkpoint_unchanged"] = sha(PINNED) == PINNED_SHA
            result["harness_unchanged"] = sha(__file__) == result["harness_sha256"]
            verify(spec["snapshot"])
            summary_path = Path(spec["work_directory"]) / "workspace/test-logs" / (RUN_ID + ".summary")
            if summary_path.exists() and "summary" not in result:
                result["partial_summary"] = read(summary_path)
        except BaseException as exc:
            result["final_guard_error"] = {"type": type(exc).__name__, "message": str(exc)[:4096]}
        result["child_seconds_including_audits"] = time.perf_counter() - started
        result["passed"] = (result["passed"] and not any(k in result for k in ("error", "final_guard_error"))
            and all(result.get(k) is True for k in ("source_unchanged", "producer_config_unchanged", "protected_checkpoint_unchanged", "harness_unchanged")))
        write(output, result)
    return 0 if result["passed"] else 1


def run_child(directory, spec):
    spec_path, output = directory / "child-spec.json", directory / "child-result.json"
    log_path = directory / "child-process.log"
    write(spec_path, spec)
    timeout = NATIVE_TIMEOUT if spec["native_cycle"] else STARTUP_TIMEOUT
    started, timed_out = time.perf_counter(), False
    with log_path.open("xb") as log:
        child = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--child-spec", str(spec_path),
            "--child-output", str(output)], cwd=ROOT, env=dict(os.environ), stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        print(json.dumps({"child_pid": child.pid, "log": str(log_path), "timeout_seconds": timeout}), flush=True)
        try:
            code = child.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            os.killpg(child.pid, signal.SIGTERM)
            try:
                code = child.wait(timeout=15)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGKILL)
                code = child.wait()
    return {"exit_code": code, "outer_timeout": timed_out, "process_seconds": time.perf_counter() - started,
        "log": descriptor(log_path), "spec": descriptor(spec_path),
        "receipt": descriptor(output) if output.exists() else None,
        "result": read(output) if output.exists() else {"passed": False, "error": "missing child receipt"}}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--native-cycle", action="store_true", help="Explicitly permit one full native cycle; default is startup/input walk only")
    parser.add_argument("--child-spec", type=Path)
    parser.add_argument("--child-output", type=Path)
    args = parser.parse_args(argv)
    os.environ.update(ENVIRONMENT)
    sys.path.insert(0, str(ROOT))
    if args.child_spec is not None:
        if args.child_output is None:
            parser.error("child output required")
        return child_main(args.child_spec, args.child_output)
    if args.directory is None or args.output is None:
        parser.error("--directory and --output required")
    directory, output = args.directory.resolve(), args.output.resolve()
    if directory.exists() or output.exists() or ROOT not in directory.parents:
        parser.error("use new output paths; workspace must be within canonical checkout")
    directory.mkdir(parents=True)
    result = {"schema": "owner-local-daemon-input-qualification-v1", "passed": False,
        "recorded_at": datetime.now(timezone.utc).isoformat(), "harness": descriptor(__file__),
        "environment": ENVIRONMENT, "native_cycle_requested": args.native_cycle,
        "historical_owner_modified": False, "owner_head_promotion_performed": False,
        "admitted": False, "formalized": False, "publication_performed": False, "heldout_canary_qualified": False,
        "automatic_retry": False, "speed_claim": False,
        "input_authority": "explicit trusted local owner-issued snapshot; no cryptographic issuer or embedding runtime attestation",
        "snapshot_policy": "public default enabled; native snapshot proof work independent of bridge_evaluate_provers=False",
        "scope": "startup/input walk only unless native-cycle explicitly requested; no loader/evaluator/trainer replacements"}
    started = time.perf_counter()
    try:
        from ipfs_datasets_py.logic.autoformal.tree_pin import require_workspace_logic_tree
        result["tree_pin"] = require_workspace_logic_tree()
        result["source_manifest_before"] = source_manifest()
        result["producer_config_before"] = producer_config()
        source_dir = directory / "source-code"
        source_dir.mkdir()
        result["source_archives"] = []
        source_paths = [Path(__file__).resolve(), SECCOMP_SCRIPT,
            ROOT / "ipfs_datasets_py/duckdb_control/autoencoder_registry.py"]
        source_paths += [ROOT / "ipfs_datasets_py/optimizers/logic_theorem_optimizer" / name for name in (
            "autoencoder_daemon_corpus_inputs.py", "uscode_modal_daemon_runner.py",
            "autoencoder_training_coordinator.py", "autoencoder_training_worker.py", "legal_samples.py")]
        for source in source_paths:
            archive = source_dir / source.name
            with source.open("rb") as src, archive.open("xb") as dst:
                shutil.copyfileobj(src, dst, 1024 * 1024)
            copied = descriptor(archive)
            expected = (result["source_manifest_before"].get(source.relative_to(ROOT).as_posix())
                if source.parent != Path(__file__).parent else sha(source))
            if copied["sha256"] != expected:
                raise ValueError("source archive differs from frozen source manifest")
            result["source_archives"].append({"source": str(source), **copied})
        verify({"path": str(PINNED), "sha256": PINNED_SHA, "bytes": PINNED_BYTES})
        snapshot, payload = historical_export(directory, result)
        result["snapshot"] = snapshot
        result["exported_job"] = payload
        result["child"] = run_child(directory, {"snapshot": snapshot, "payload": payload,
            "source_manifest": result["source_manifest_before"], "work_directory": str(directory / "daemon-workspace"),
            "producer_config": result["producer_config_before"],
            "native_cycle": args.native_cycle})
        child = result["child"]
        result["passed"] = child["exit_code"] == 0 and not child["outer_timeout"] and child["result"]["passed"]
    except BaseException as exc:
        result["error"] = {"type": type(exc).__module__ + "." + type(exc).__qualname__, "message": str(exc)[:4096]}
    finally:
        try:
            result["source_manifest_after"] = source_manifest()
            result["source_unchanged"] = result["source_manifest_after"] == result.get("source_manifest_before")
            result["producer_config_after"] = producer_config()
            result["producer_config_unchanged"] = canonical(result["producer_config_after"]) == canonical(result.get("producer_config_before"))
            result["protected_checkpoint_unchanged"] = sha(PINNED) == PINNED_SHA
            result["harness_unchanged"] = sha(__file__) == result["harness"]["sha256"]
            for ref in result.get("historical_guards", [{"path": str(DATABASE), "sha256": DATABASE_SHA, "bytes": 7876608}]):
                verify(ref)
            result["historical_inputs_unchanged"] = True
            if "snapshot" in result:
                verify(result["snapshot"])
            if "private_owner" in result and "database_after_export" in result["private_owner"]:
                verify(result["private_owner"]["database_after_export"])
                result["private_owner_database_unchanged_after_export"] = True
            for archive in result.get("source_archives", ()):
                verify(archive)
        except BaseException as exc:
            result["final_guard_error"] = {"type": type(exc).__name__, "message": str(exc)[:4096]}
        result["passed"] = (result["passed"] and "error" not in result and "final_guard_error" not in result
            and all(result.get(k) is True for k in ("source_unchanged", "producer_config_unchanged", "protected_checkpoint_unchanged", "harness_unchanged", "historical_inputs_unchanged")))
        result["native_cycle_qualified"] = bool(args.native_cycle and result["passed"])
        result["elapsed_seconds"] = time.perf_counter() - started
        write(output, result)
    print(json.dumps({"receipt": str(output), "passed": result["passed"], "native_cycle_qualified": result["native_cycle_qualified"]}), flush=True)
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
