#!/usr/bin/env python3
"""Qualify one cold and one shared-target cycle of the actual guarded daemon.

Only the input I/O boundary is adapted: a six-row local table and row converter
replace the remote parquet loader. The rows/vectors are verified against the
existing source-bound native receipt. Native sampling, evaluator, projection,
independent diagnostics, queue handling and checkpoint persistence are retained.
This does not qualify the ordinary CLI's remote dataset/embedding input path.

Each daemon runs in a fresh process and private output cwd, importing exclusively
from the canonical checkout. Train sample memory remains enabled, validation
sample memory remains disabled. Compiler artifact caches start empty separately;
the metric disk cache is disabled. No warm-cycle or speed claim is inferred.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parents[3]
DEPENDENCIES = {
    "benchmark_worker_target_reduction.py": "caf9982bae85b27e5a2abb4241701e0817e8f2ff071bc2e5199a7674618ae3e7",
    "qualify_target_preparation_telemetry.py": "281189523dfc4ff704df9918dddc68e47dc9c4f6053cf805e731d85020065f44",
    "audit_native_uscode_embedding_production.py": "381f0bbb08229fcc15add4faf259be07d895d4502f44cc573265ef4f72cb8fb6",
}
BRIDGES = ["modal_frame_logic", "deontic_norms", "fol_tdfol", "cec_dcec", "external_prover_router"]
ENVIRONMENT = {
    "IPFS_DATASETS_LEGAL_IR_METRIC_DISK_CACHE": "0",
    "IPFS_DATASETS_LEGAL_IR_ADAPTER_WORKERS": "1",
    "IPFS_DATASETS_LEGAL_IR_PARALLEL_WORKERS": "1",
    "IPFS_DATASETS_MODAL_AUTOENCODER_AUTO_CUDA": "0",
    "IPFS_DATASETS_PY_LAZY_INSTALL_ERGOAI": "0",
    "CUDA_VISIBLE_DEVICES": "", "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
    "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1",
}
MAX_CHILD_SECONDS = 900
MAX_RECEIPT_BYTES = 64 * 1024 * 1024
MAX_CHECKPOINT_BYTES = 256 * 1024 * 1024
EVALUATION_KEYS = (
    "autoencoder_before_train", "autoencoder_before_validation",
    "autoencoder_after_train", "autoencoder_after_validation",
)


def sha(path):
    with Path(path).open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, sort_keys=True, indent=2, allow_nan=False)
        handle.write("\n")


def read(path, limit=MAX_RECEIPT_BYTES):
    path = Path(path)
    if path.stat().st_size > limit:
        raise ValueError("JSON artifact exceeds byte bound: " + str(path))
    return json.loads(path.read_bytes())


def descriptor(path):
    path = Path(path)
    return {"path": str(path.resolve()), "sha256": sha(path), "bytes": path.stat().st_size}


def dependencies():
    for name, expected in DEPENDENCIES.items():
        if sha(Path(__file__).with_name(name)) != expected:
            raise ValueError("frozen harness dependency changed: " + name)
    import benchmark_worker_target_reduction as helper
    return helper


class FixtureTable:
    """Loader-only table protocol; no model, evaluator or sampler substitution."""

    def __init__(self, rows):
        self._rows = tuple(dict(row) for row in rows)
        self.num_rows = len(self._rows)

    def take(self, indices):
        if any(type(index) is not int or not 0 <= index < self.num_rows for index in indices):
            raise ValueError("fixture row index outside exact bounded input")
        return FixtureTable([self._rows[index] for index in indices])

    def to_pylist(self):
        return [dict(row) for row in self._rows]


def fixture(payload):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_training_worker import SampleRecord
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_samples import build_us_code_sample
    records = [SampleRecord.from_dict(row) for row in payload["samples"] + payload["validation_samples"]]
    if len(records) != 6 or len(payload["samples"]) != 3:
        raise ValueError("qualification requires the frozen ordered 3+3 selection")
    samples = [build_us_code_sample(**asdict(record)) for record in records]
    if len({sample.sample_id for sample in samples}) != 6:
        raise ValueError("fixture sample IDs must be unique")
    rows = [{"fixture_index": index, "record_sha256": hashlib.sha256(canonical(asdict(record))).hexdigest(),
             "text": sample.text} for index, (record, sample) in enumerate(zip(records, samples))]

    def row_to_sample(row):
        index = row.get("fixture_index")
        if type(index) is not int or not 0 <= index < 6 or row != rows[index]:
            raise ValueError("unrecognized or mutated local fixture row")
        return samples[index]

    return FixtureTable(rows), row_to_sample, samples


def daemon_argv(run_id, capacity, prepared, policy):
    argv = ["--run-id", run_id, "--loop-role", "autoencoder", "--max-cycles", "1",
        "--duration-seconds", "600", "--train-count", "3", "--validation-count", "0",
        "--validation-canary-count", "3", "--validation-canary-indices", "3,4,5",
        "--sampling-seed", "9", "--max-sample-text-chars", "0",
        "--snapshot-evaluation-enabled", "false", "--autoencoder-canonical-warm-start", "off",
        "--autoencoder-device", "python", "--autoencoder-max-generalizable-entries-per-group", str(capacity),
        "--bridge-loss-adapters", ",".join(BRIDGES), "--autoencoder-metric-bridge-adapters", ",".join(BRIDGES),
        "--autoencoder-diagnostic-bridge-adapters", "none", "--bridge-evaluate-provers", "false",
        "--autoencoder-bridge-workers", "1", "--autoencoder-metric-bridge-max-sample-text-chars", "0",
        "--generalizable-projection-epochs", "1", "--generalizable-projection-max-update-families", "1",
        "--generalizable-projection-max-line-search-attempts", "1",
        "--generalizable-projection-timeout-seconds", "180", "--learning-rate", "0.35",
        "--autoencoder-before-train-eval-mode", "every_cycle", "--compiler-ir-train-mode", "off",
        "--compiler-ir-guided-train-mode", "off", "--autoencoder-sample-memory-probe-mode", "off",
        "--autoencoder-todo-supervisor-mode", "off", "--max-items", "0", "--max-inner-iterations", "1",
        "--autoencoder-introspection-mode", "off", "--test-every-cycles", "0",
        "--leanstral-rule-gap-projection-enabled", "false", "--leanstral-rule-gap-wait-seconds", "0",
        "--leanstral-direct-guidance-projection-enabled", "false",
        "--leanstral-direct-guidance-train-autoencoder", "false",
        "--daemon-hammer-guidance-enabled", "false", "--daemon-hammer-guidance-train-autoencoder", "false",
        "--daemon-hammer-guidance-max-samples-per-cycle", "0",
        "--codex-exec-mode", "packet_only", "--codex-apply-mode", "patch_only", "--codex-commit-mode", "none"]
    if policy == "shared":
        argv.extend(["--autoencoder-target-bundle", prepared["artifact"]["path"],
            "--autoencoder-target-bundle-sha256", prepared["artifact"]["sha256"],
            "--autoencoder-target-bundle-bytes", str(prepared["artifact"]["bytes"]),
            "--autoencoder-target-snapshot-id", prepared["target_snapshot_id"]])
    elif policy != "cold":
        raise ValueError("unsupported qualification arm")
    return argv


def bridge_diagnostics_complete(block):
    return (block.get("sample_count") == 3 and block.get("evaluated_count") == 15
        and block.get("metric_failures") == 0 and block.get("adapter_metrics_complete") is True
        and set(block.get("adapters", {})) == set(BRIDGES)
        and all(row.get("sample_count") == row.get("evaluated_count") == 3
                and row.get("metric_failures") == 0 for row in block["adapters"].values()))


def read_cycle(log_path):
    found = []
    with Path(log_path).open(encoding="utf-8") as handle:
        for line in handle:
            if len(line) > MAX_RECEIPT_BYTES:
                raise ValueError("daemon log record exceeds bounded receipt size")
            record = json.loads(line)
            if record.get("event") == "cycle":
                found.append(record)
    if len(found) != 1:
        raise ValueError("native daemon did not persist exactly one completed cycle")
    return found[0]


def memory_observation():
    import resource
    result = {"max_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}
    try:
        with Path("/proc/self/smaps_rollup").open() as handle:
            for line in handle:
                if line.startswith(("Rss:", "Pss:")):
                    key, value, _unit = line.split()
                    result[key[:-1].lower() + "_kib"] = int(value)
    except OSError:
        pass
    return result


def daemon_child(spec, result):
    helper = dependencies()
    from audit_native_uscode_embedding_production import _deny_network
    from ipfs_datasets_py.logic.autoformal.tree_pin import require_workspace_logic_tree
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import uscode_modal_daemon_runner as runner
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_training_worker import TrainingJobSpec, verify_corpus_job_inputs
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder_checkpoint import load_checkpoint

    result["tree_pin"] = require_workspace_logic_tree()
    payload = spec["payload"]
    result["input_verification"] = verify_corpus_job_inputs(TrainingJobSpec.from_dict(payload))
    result["config_before"] = helper.config_probe(payload["training_config"])
    if canonical(result["config_before"]) != canonical(spec["config"]):
        raise ValueError("daemon child package/config differs from frozen preparation")
    work = Path(spec["work_directory"])
    if work.exists():
        raise ValueError("daemon workspace must not already exist")
    work.mkdir(parents=True)
    os.chdir(work)
    run_id = "bounded-native-" + spec["policy"]
    state_path = work / "workspace/todo-queues" / (run_id + ".state.json")
    state_path.parent.mkdir(parents=True)
    helper.verify_descriptor({"path": str(helper.PINNED), "sha256": helper.PINNED_SHA, "bytes": helper.PINNED_BYTES})
    with helper.PINNED.open("rb") as source, state_path.open("xb") as destination:
        while chunk := source.read(1024 * 1024):
            destination.write(chunk)
    result["initial_private_checkpoint"] = descriptor(state_path)
    if result["initial_private_checkpoint"]["sha256"] != helper.PINNED_SHA:
        raise ValueError("private checkpoint is not the exact pinned source bytes")
    initial = load_checkpoint(state_path, recover=False)
    result["initial_state_identity"] = initial.state.state_identity_record().to_dict()
    capacity = max(8192, initial.state.generalizable_entry_count() + 1)
    table, row_adapter, samples = fixture(payload)
    result["fixture_samples"] = [{"sample_id": sample.sample_id, "sample_json_sha256": hashlib.sha256(sample.to_json().encode()).hexdigest(),
        "embedding_model": sample.embedding_model, "embedding_dimensions": len(sample.embedding_vector)} for sample in samples]
    blocked = set(initial.state.decoded_embeddings) | set(initial.state.family_logits)
    result["initial_sample_memory_overlap"] = {
        "training": sorted(blocked & {sample.sample_id for sample in samples[:3]}),
        "validation": sorted(blocked & {sample.sample_id for sample in samples[3:]})}
    argv = daemon_argv(run_id, capacity, spec["prepared"], spec["policy"])
    args = runner.build_uscode_modal_daemon_arg_parser().parse_args(argv)
    result["argv"] = argv
    result["effective_arguments"] = {key: str(value) if isinstance(value, Path) else value for key, value in vars(args).items()}
    original_loader, original_row = runner.load_laws_table, runner.row_to_sample
    runner.load_laws_table = lambda: table
    runner.row_to_sample = row_adapter
    result["loader_adapters_restored"] = False
    del initial
    result["network_guard"] = _deny_network()
    result["memory_before_daemon"] = memory_observation()
    try:
        import random
        indices, chosen, val_indices, validation, _attempts = runner.sample_train_validation_rows(
            table, random.Random(10), train_count=3, validation_count=0,
            blocked_train_sample_ids={sample.sample_id for sample in samples[3:]},
            blocked_validation_sample_ids=blocked, max_sample_text_chars=0)
        if indices != [0, 1, 2] or val_indices or validation or [sample.sample_id for sample in chosen] != [sample.sample_id for sample in samples[:3]]:
            raise ValueError("native deterministic sampling differs from the frozen split/order")
        started = time.perf_counter()
        try:
            result["daemon_exit_code"] = runner.run_guarded_uscode_modal_daemon(args)
        finally:
            result["daemon_seconds_including_native_shutdown"] = time.perf_counter() - started
            result["memory_after_daemon"] = memory_observation()
    finally:
        runner.load_laws_table, runner.row_to_sample = original_loader, original_row
        result["loader_adapters_restored"] = runner.load_laws_table is original_loader and runner.row_to_sample is original_row
    summary_path = work / "workspace/test-logs" / (run_id + ".summary")
    log_path = summary_path.with_suffix(".jsonl")
    summary, cycle = read(summary_path), read_cycle(log_path)
    result["summary_artifact"], result["log_artifact"] = descriptor(summary_path), descriptor(log_path)
    result["summary"], result["cycle"] = summary, cycle
    result["timings"] = {
        "daemon_seconds_including_native_shutdown": result["daemon_seconds_including_native_shutdown"],
        "cycle_seconds": summary["latest_cycle_seconds"],
        "native_cycle_phase_seconds": summary["latest_cycle_phase_timings"],
        "bridge_on_evaluations": {name: {
            "seconds": summary["latest_cycle_phase_timings"][name],
            "seconds_per_span": summary["latest_cycle_phase_timings"][name] / 3,
            "sample_count": 3, "bridge_names": BRIDGES, "requested_evaluate_provers": False,
            "sample_workers": 1, "adapter_workers": 1,
            "sample_memory": name in {"before_train_eval", "after_train_eval"},
            "scope": "aggregate evaluation with five bridges; no per-bridge timing separation",
        } for name in ("before_train_eval", "before_validation_eval", "after_train_eval", "after_validation_eval")},
        "independent_diagnostic_phases": {name: summary["latest_cycle_phase_timings"][name]
            for name in ("compiler_ir_validation", "compiler_ir_guided_validation", "bridge_ir_train", "bridge_ir_validation")},
    }
    if state_path.stat().st_size > MAX_CHECKPOINT_BYTES:
        raise ValueError("final native checkpoint exceeds qualification byte cap")
    final = load_checkpoint(state_path, delta_path=state_path.with_name(run_id + ".state-deltas.bin"), recover=False)
    result["final_state_identity"] = final.state.state_identity_record().to_dict()
    result["final_checkpoint_manifest"] = final.manifest.to_dict()
    result["final_checkpoint"] = descriptor(state_path)
    result["config_after"] = helper.config_probe(payload["training_config"])
    result["input_verification_after"] = verify_corpus_job_inputs(TrainingJobSpec.from_dict(payload))
    result["sample_objects_unchanged"] = all(
        hashlib.sha256(sample.to_json().encode()).hexdigest() == before["sample_json_sha256"]
        for sample, before in zip(samples, result["fixture_samples"]))
    result["source_unchanged"] = canonical(result["config_before"]) == canonical(result["config_after"])
    result["checkpoint_source_unchanged"] = sha(helper.PINNED) == helper.PINNED_SHA
    result["complete_bridge_diagnostics"] = all(bridge_diagnostics_complete(cycle[key]) for key in ("logic_bridge_train", "logic_bridge_validation"))
    result["complete_optimizer_targets"] = all(cycle[key].get("legal_ir_target_count") == 3 for key in EVALUATION_KEYS)
    result["projection_performed"] = bool(cycle["feature_projection_report"].get("epoch_reports"))
    result["startup_state_uncompacted"] = summary["startup_autoencoder_generalizable_capacity"]["compacted"] is False
    result["native_persistence_durable"] = (summary["final_state_persistence"]["durable"] is True
        and summary["async_artifact_writer_shutdown"]["drained"] is True)
    result["selection_exact"] = cycle["train_indices"] == [0, 1, 2] and cycle["validation_indices"] == [3, 4, 5] and cycle["rotating_validation_indices"] == []
    result["shared_target_session"] = summary.get("shared_target_session")
    if spec["policy"] == "shared":
        session = result["shared_target_session"]
        if (not isinstance(session, dict) or session.get("poisoned") is not False or session.get("failure") is not None
                or session.get("closed") is not True or session.get("active") is not False
                or session.get("counts") != {"cycles_started": 1, "cycles_completed": 1,
                    "hydrations": 1, "cache_hits": 0, "skipped_cycles": 0}
                or session.get("current_cycle", {}).get("applied") is not True):
            raise ValueError("shared target session did not finish cleanly")
    result["passed"] = (result["daemon_exit_code"] == 0 and summary["cycles"] == 1
        and result["loader_adapters_restored"] and result["source_unchanged"] and result["checkpoint_source_unchanged"]
        and result["sample_objects_unchanged"] and result["complete_bridge_diagnostics"] and result["complete_optimizer_targets"]
        and result["projection_performed"] and result["startup_state_uncompacted"] and result["native_persistence_durable"]
        and result["selection_exact"])


def child_main(spec_path, output):
    spec, helper = read(spec_path), dependencies()
    result = {"schema": "daemon-shared-target-child-v1", "passed": False, "pid": os.getpid(), "kind": spec["kind"],
              "harness_sha256": sha(__file__), "started_at": datetime.now(timezone.utc).isoformat()}
    started = time.perf_counter()
    try:
        if spec["kind"] == "prepare":
            from audit_native_uscode_embedding_production import _deny_network
            result["network_guard"] = _deny_network()
            result["config"] = helper.config_probe(spec["payload"]["training_config"])
            result["prepared"] = helper.prepare(spec["payload"], spec["bundle_path"], spec["observation_path"])
            observation = read(spec["observation_path"])
            helper.validate_preparation_observation(result["prepared"], observation, result["config"])
            result["passed"] = helper.complete_bridge_reports(result["prepared"])
        elif spec["kind"] == "daemon":
            daemon_child(spec, result)
        else:
            raise ValueError("unsupported child operation")
    except BaseException as exc:
        result["error"] = {"type": type(exc).__module__ + "." + type(exc).__qualname__, "message": str(exc)[:4096]}
    finally:
        try:
            if spec["kind"] == "prepare" and Path(spec["observation_path"]).exists():
                result["preparation_observation_artifact"] = descriptor(spec["observation_path"])
                result["preparation_observation"] = read(spec["observation_path"])
        except BaseException as exc:
            result["observation_read_error"] = {"type": type(exc).__name__, "message": str(exc)[:4096]}
            result["passed"] = False
        result["child_seconds"] = time.perf_counter() - started
        result["harness_unchanged"] = result["harness_sha256"] == sha(__file__)
        result["passed"] = result["passed"] and result["harness_unchanged"] and "error" not in result
        write(output, result)
    return 0 if result["passed"] else 1


def run_child(directory, name, spec):
    spec_path, result_path = directory / (name + "-spec.json"), directory / (name + "-result.json")
    log_path = directory / (name + "-process.log")
    write(spec_path, spec)
    started = time.perf_counter()
    timeout = False
    with log_path.open("xb") as log:
        process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--child-spec", str(spec_path),
                                    "--child-output", str(result_path)], cwd=ROOT, env=dict(os.environ),
                                   stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        try:
            code = process.wait(timeout=MAX_CHILD_SECONDS)
        except subprocess.TimeoutExpired:
            timeout = True
            os.killpg(process.pid, signal.SIGTERM)
            try:
                code = process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                code = process.wait()
    result = read(result_path) if result_path.exists() else {"passed": False, "error": {"type": "MissingChildReceipt", "message": "child exited without its receipt"}}
    return {"process_seconds_including_shutdown": time.perf_counter() - started, "exit_code": code,
        "outer_timeout": timeout, "spec_artifact": descriptor(spec_path), "process_log": descriptor(log_path),
        "receipt_artifact": descriptor(result_path) if result_path.exists() else None, "result": result}


def semantic_projection(report):
    """Retain all projection fields except its declared top-level wall clock.

    No recursive time/hash-key stripping: unknown differing fields fail parity.
    Full unmodified reports remain in the child receipts and native daemon logs.
    """
    result = dict(report)
    elapsed = result.pop("elapsed_seconds")
    if type(elapsed) not in (float, int) or elapsed < 0:
        raise ValueError("invalid projection elapsed_seconds")
    return result


def projection_semantics_with_hashes_separate(report):
    result = semantic_projection(report)
    hashes = {}
    for phase in ("before", "after"):
        evaluation = dict(result[phase])
        hashes[phase] = evaluation.pop("legal_ir_target_hashes")
        result[phase] = evaluation
    return result, hashes


def compare_runs(cold, shared):
    left, right = cold["cycle"], shared["cycle"]
    evaluations = {}
    for key in EVALUATION_KEYS:
        a, b = dict(left[key]), dict(right[key])
        hashes_a, hashes_b = a.pop("legal_ir_target_hashes"), b.pop("legal_ir_target_hashes")
        evaluations[key] = {"all_persisted_fields_equal": canonical(left[key]) == canonical(right[key]),
            "fields_except_explicit_target_hash_map_equal": canonical(a) == canonical(b),
            "target_hashes_equal": hashes_a == hashes_b,
            "cold_target_hashes": hashes_a, "shared_target_hashes": hashes_b}
    projection_a, projection_b = semantic_projection(left["feature_projection_report"]), semantic_projection(right["feature_projection_report"])
    # This strict comparison deliberately retains all target hashes. A mismatch
    # is reported, not silently classified as harmless timestamp variation.
    projection_equal = canonical(projection_a) == canonical(projection_b)
    numeric_a, hashes_a = projection_semantics_with_hashes_separate(left["feature_projection_report"])
    numeric_b, hashes_b = projection_semantics_with_hashes_separate(right["feature_projection_report"])
    minimum = (all(item["fields_except_explicit_target_hash_map_equal"] for item in evaluations.values())
        and canonical(numeric_a) == canonical(numeric_b)
        and canonical(cold["initial_state_identity"]) == canonical(shared["initial_state_identity"])
        and canonical(cold["final_state_identity"]) == canonical(shared["final_state_identity"]))
    return {"evaluation_fields": evaluations, "projection_except_top_level_elapsed_equal": projection_equal,
        "projection_except_exact_clock_and_before_after_target_hash_maps_equal": canonical(numeric_a) == canonical(numeric_b),
        "projection_cold_target_hashes": hashes_a, "projection_shared_target_hashes": hashes_b,
        "numeric_grammar_acceptance_and_complete_state_parity": minimum,
        "projection_raw_equal": canonical(left["feature_projection_report"]) == canonical(right["feature_projection_report"]),
        "initial_state_identity_equal": canonical(cold["initial_state_identity"]) == canonical(shared["initial_state_identity"]),
        "final_state_identity_equal": canonical(cold["final_state_identity"]) == canonical(shared["final_state_identity"]),
        "independent_bridge_adapter_metrics_equal": all(canonical(left[key]["adapters"]) == canonical(right[key]["adapters"])
            for key in ("logic_bridge_train", "logic_bridge_validation")),
        "whole_daemon_semantic_parity_qualified": False,
        "parity_scope": "persisted evaluation blocks (native nine-decimal rounding), exact full projection report except one clock, state identities and independent bridge adapter metrics; no claim of complete raw capture/triple parity"}


def parent_run(args, receipt):
    helper = dependencies()
    from ipfs_datasets_py.logic.autoformal.tree_pin import require_workspace_logic_tree
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_training_worker import TrainingJobSpec, verify_corpus_job_inputs
    helper.verify_descriptor({"path": str(helper.PINNED), "sha256": helper.PINNED_SHA, "bytes": helper.PINNED_BYTES})
    if sha(helper.PRIOR) != helper.PRIOR_SHA:
        raise ValueError("frozen source-selection parent changed")
    prior = read(helper.PRIOR)
    if prior["passed"] is not True:
        raise ValueError("source-selection parent did not pass")
    row = prior["combined_arrow_inputs_and_feature_weights"]["jobs"][0]
    payload = row["worker"]["job_spec"]
    spec = TrainingJobSpec.from_dict(payload)
    if spec.canonical_sha256 != row["worker"]["job_spec_canonical_sha256"] or spec.base_checkpoint.sha256 != helper.PINNED_SHA:
        raise ValueError("parent job identity or base checkpoint differs")
    worker_path = Path(spec.output_directory) / "receipt.json"
    worker_ref = {**row["completed"]["worker_receipt_artifact"], "path": str(worker_path)}
    helper.verify_descriptor(worker_ref)
    if read(worker_path) != row["worker"]:
        raise ValueError("parent worker receipt differs from independently hashed artifact")
    receipt["parent_worker_receipt"] = worker_ref
    helper.validate_config(payload)
    receipt["parent_input_verification"] = verify_corpus_job_inputs(spec)
    receipt["tree_pin"] = require_workspace_logic_tree()
    receipt["parent_receipt"] = {"path": str(helper.PRIOR), "sha256": helper.PRIOR_SHA}
    receipt["pinned_checkpoint"] = descriptor(helper.PINNED)
    receipt["ordered_input_records"] = {"training": payload["samples"], "validation": payload["validation_samples"]}
    receipt["selection"] = prior["selection"]
    receipt["config_before"] = helper.config_probe(payload["training_config"])
    write(args.directory / "target-config-before.json", receipt["config_before"])
    receipt["source_snapshots"] = []
    names = ["uscode_modal_daemon_runner.py", "autoencoder_daemon_target_session.py", "modal_autoencoder.py",
             "modal_autoencoder_checkpoint.py", "legal_ir_target_bundle.py", "legal_ir_target_snapshot.py"]
    for name in names:
        path = ROOT / "ipfs_datasets_py/optimizers/logic_theorem_optimizer" / name
        destination = args.directory / "source-code" / name
        destination.parent.mkdir(exist_ok=True)
        with destination.open("xb") as handle:
            handle.write(path.read_bytes())
        copied = descriptor(destination)
        key = path.relative_to(ROOT / "ipfs_datasets_py").as_posix()
        if copied["sha256"] != receipt["config_before"]["code_sha256"].get(key):
            raise ValueError("source snapshot differs from full producer config")
        receipt["source_snapshots"].append({"source": str(path), **copied})
    prepared_run = run_child(args.directory, "preparation", {"kind": "prepare", "payload": payload,
        "bundle_path": str(args.directory / "targets.bundle"), "observation_path": str(args.directory / "preparation-outcomes.json")})
    receipt["preparation"] = prepared_run
    if not prepared_run["result"]["passed"] or prepared_run["exit_code"] or prepared_run["outer_timeout"]:
        raise ValueError("fresh preparation failed; preserving outcomes without retry")
    prepared = prepared_run["result"]["prepared"]
    if canonical(prepared_run["result"]["config"]) != canonical(receipt["config_before"]):
        raise ValueError("source changed before preparation")
    for policy in ("cold", "shared"):
        run = run_child(args.directory, policy, {"kind": "daemon", "policy": policy, "payload": payload,
            "config": receipt["config_before"], "prepared": prepared,
            "work_directory": str(args.directory / (policy + "-workspace"))})
        receipt["runs"].append({"policy": policy, **run})
        if not run["result"]["passed"] or run["exit_code"] or run["outer_timeout"]:
            raise ValueError(policy + " daemon qualification failed; no retry or reselection")
    receipt["comparison"] = compare_runs(*(run["result"] for run in receipt["runs"]))
    receipt["all_native_cycles_completed"] = True
    receipt["config_after"] = helper.config_probe(payload["training_config"])
    receipt["source_unchanged"] = canonical(receipt["config_before"]) == canonical(receipt["config_after"])
    receipt["input_verification_after"] = verify_corpus_job_inputs(spec)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--child-spec", type=Path)
    parser.add_argument("--child-output", type=Path)
    args = parser.parse_args()
    os.environ.update(ENVIRONMENT)
    sys.path.insert(0, str(ROOT))
    if args.child_spec is not None:
        if args.child_output is None:
            parser.error("child output required")
        return child_main(args.child_spec, args.child_output)
    if args.directory is None or args.output is None:
        parser.error("--directory and --output required")
    args.directory, args.output = args.directory.resolve(), args.output.resolve()
    if args.directory.exists() or args.output.exists() or ROOT not in args.directory.parents:
        parser.error("use new receipt/workspace paths; workspace must be under the canonical checkout")
    args.directory.mkdir(parents=True)
    receipt = {"schema": "guarded-daemon-shared-target-qualification-v1", "passed": False, "runs": [],
        "recorded_at": datetime.now(timezone.utc).isoformat(), "harness_sha256": sha(__file__),
        "harness_dependencies": DEPENDENCIES, "environment": ENVIRONMENT,
        "qualification_scope": "actual guarded daemon evaluator/projection/persistence with loader-only injected verified local inputs",
        "ordinary_cli_input_path_qualified": False, "input_adapter_scope": ["load_laws_table", "row_to_sample"],
        "native_evaluator_or_trainer_wrapped": False, "train_sample_memory": True, "validation_sample_memory": False,
        "daemon_projection_backend": "native (ordinary CPU auto selection)", "native_device": "python",
        "metric_disk_cache": 0, "compiler_artifact_cache": "unmodified always-on native cache; fresh isolated cwd per arm",
        "diagnostics": "native compiler baseline/guided validation and independent bridge train/validation remain enabled",
        "optional_work_policy": "explicit CLI controls disable compiler train-only passes, TODO optimization, introspection, external guidance, snapshot evaluator, and cycle tests in both arms",
        "code_synthesis_execution": "autoencoder loop only; private queue may receive native guidance TODOs; no Codex worker is launched",
        "prover_scope": "requested flag false; existing local native router and FLogic work may still execute",
        "admitted": False, "formalized": False, "promotion_performed": False, "publication_performed": False,
        "heldout_canary_qualified": False, "weights_downloaded": False, "protected_checkpoint_modified": False,
        "source_code_modified": False, "warm_daemon_qualified": False, "speed_claim": False,
        "automatic_retry_or_reselection": False, "execution_order": ["cold", "shared"],
        "timing_scope": "fresh preparation separately; actual daemon call includes startup and durable shutdown; process wall additionally includes fixture/source checks, imports and post-run inspection; OS caches uncontrolled",
        "capture_parity": "raw ontology captures/triples not persisted or independently compared",
        "pass_scope": "bounded native daemon execution/integration and source/input/persistence guards; complete semantic parity reported separately"}
    started = time.perf_counter()
    try:
        parent_run(args, receipt)
    except BaseException as exc:
        receipt["error"] = {"type": type(exc).__module__ + "." + type(exc).__qualname__, "message": str(exc)[:4096]}
    finally:
        receipt["harness_unchanged"] = False
        receipt["pinned_checkpoint_unchanged"] = False
        try:
            helper = dependencies()
            receipt["harness_unchanged"] = receipt["harness_sha256"] == sha(__file__)
            receipt["pinned_checkpoint_unchanged"] = sha(helper.PINNED) == helper.PINNED_SHA
            if "config_before" in receipt:
                prior = read(helper.PRIOR)
                payload = prior["combined_arrow_inputs_and_feature_weights"]["jobs"][0]["worker"]["job_spec"]
                receipt["final_guard_config"] = helper.config_probe(payload["training_config"])
                receipt["source_unchanged"] = canonical(receipt["config_before"]) == canonical(receipt["final_guard_config"])
            receipt["source_snapshots_unchanged"] = all(sha(ref["path"]) == ref["sha256"] and Path(ref["path"]).stat().st_size == ref["bytes"]
                for ref in receipt.get("source_snapshots", []))
        except BaseException as exc:
            receipt["source_unchanged"] = False
            receipt["final_guard_error"] = {"type": type(exc).__name__, "message": str(exc)[:4096]}
        receipt["elapsed_seconds"] = time.perf_counter() - started
        receipt["passed"] = ("error" not in receipt and receipt.get("all_native_cycles_completed") is True
            and receipt["harness_unchanged"] and receipt["pinned_checkpoint_unchanged"] and receipt.get("source_unchanged") is True
            and receipt.get("source_snapshots_unchanged") is True)
        write(args.output, receipt)
    print(json.dumps({"receipt": str(args.output), "passed": receipt["passed"], "error": receipt.get("error")}), flush=True)
    return 0 if receipt["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
