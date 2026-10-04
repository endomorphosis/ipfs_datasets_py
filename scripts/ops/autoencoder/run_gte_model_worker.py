"""Run one pinned, offline, CPU inference worker for an existing parallel lane."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import sys
import time


REPOSITORY = Path(__file__).resolve().parents[3]
HELPER = REPOSITORY / "ipfs_datasets_py/logic/formalization/autoencoder/gte_worker_contract.py"
INPUT_SCHEMA = "gte-parallel-inference-inputs/v1"
REPORT_SCHEMA = "gte-parallel-model-inference/v1"


def _helper():
    spec = importlib.util.spec_from_file_location("gte_model_worker_contract", HELPER)
    if spec is None or spec.loader is None:
        raise ValueError("worker contract helper is unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _vector(value, dimension):
    if type(value) not in (list, tuple) or len(value) != dimension:
        raise ValueError("vector width differs from worker dimension")
    if any(type(v) not in (int, float) or not math.isfinite(v) or abs(v) > 1e6 for v in value):
        raise ValueError("bounded finite numeric vector required")
    return list(value)


def _inputs(payload, config):
    if type(payload) is not dict or set(payload) != {"schema", "domain_id", "representation_id", "rows"}:
        raise ValueError("closed source-only inference input envelope required")
    if payload["schema"] != INPUT_SCHEMA or any(payload[k] != config[k] for k in ("domain_id", "representation_id")):
        raise ValueError("input profile differs from worker configuration")
    rows = payload["rows"]
    if type(rows) is not list or not 1 <= len(rows) <= config["resources"]["max_rows"]:
        raise ValueError("input row count exceeds worker budget")
    linguistic = config["runtime_id"] == "legal_ir:legacy_linguistic_historical_blank_en"
    fields = {"id", "source_text"} if linguistic else {"id", "source_text", "embedding"}
    seen = set()
    for row in rows:
        if type(row) is not dict or set(row) != fields:
            raise ValueError("inference row fields differ; targets and sidecars are forbidden")
        for k, limit in (("id", 256), ("source_text", 65536)):
            if type(row[k]) is not str or not row[k].strip() or len(row[k].encode()) > limit or "\0" in row[k]:
                raise ValueError("invalid bounded inference " + k)
        if row["id"] in seen:
            raise ValueError("duplicate inference id")
        seen.add(row["id"])
        if not linguistic:
            _vector(row["embedding"], config["dimension"])
    return rows


def _affinity(config):
    if not hasattr(os, "sched_getaffinity"):
        return {"enforced": False, "reason": "CPU affinity unavailable"}
    available = sorted(os.sched_getaffinity(0))
    count = min(config["resources"]["threads"], len(available))
    offset = (0 if config["lane_id"] == "legacy_8d" else 1) * count
    selected = [available[(offset + i) % len(available)] for i in range(count)]
    os.sched_setaffinity(0, selected)
    return {"enforced": True, "cpu_ids": selected,
            "scope": "per-worker affinity; aggregate admission belongs to caller"}


def _backend(config, checkpoint_payload):
    if config["lane_id"] == "source_384d":
        from ipfs_datasets_py.logic.formalization.autoencoder.complete_training import load_source_decoder_384_v2
        runtime = load_source_decoder_384_v2(config["checkpoint"]["path"],
            expected_sha256=config["checkpoint"]["sha256"], expected_domain=config["domain_id"])
        return runtime, runtime.describe(), []
    if config["runtime_id"] == "legal_ir:legacy_linguistic_historical_blank_en":
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_lineages.legacy_v1.linguistic import load_training_checkpoint
        if Path(config["checkpoint"]["path"]).name != "manifest.json":
            raise ValueError("linguistic checkpoint pin must name manifest.json")
        if checkpoint_payload.get("core_file") != "core.state.json" or checkpoint_payload.get("dimension") != 8:
            raise ValueError("invalid linguistic bundle profile")
        if checkpoint_payload.get("configuration", {}).get("backend") != "historical_blank_en":
            raise ValueError("linguistic backend differs from worker runtime")
        helper = _helper()
        core_path = Path(config["checkpoint"]["path"]).parent / "core.state.json"
        _, core_receipt = helper.read_pinned_json(core_path, expected_sha256=checkpoint_payload["core_sha256"])
        model = load_training_checkpoint(core_path.parent)
        descriptor = model.describe()
        if descriptor["linguistic_embedding_model"] != config["representation_id"]:
            raise ValueError("actual linguistic producer differs from declared representation")
        return model, descriptor, [core_receipt]
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_runtime_registry import open_runtime
    runtime = open_runtime("legal_ir", "legacy_v1", checkpoint=config["checkpoint"]["path"],
        expected_sha256=config["checkpoint"]["sha256"], compute_device="cpu")
    if runtime.model.DIMENSION != 8:
        raise ValueError("legacy runtime input width differs")
    return runtime.model, runtime.describe(), []


def _prepare_legacy_samples(model, rows, config):
    linguistic = config["runtime_id"] == "legal_ir:legacy_linguistic_historical_blank_en"
    if not linguistic:
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_lineages.legacy_v1 import build_sample
    samples = []
    for row in rows:
        options = dict(title="parallel-diagnostic", section=row["id"], text=row["source_text"])
        if linguistic:
            samples.append(model.build_sample(**options))
        else:
            samples.append(build_sample(**options, embedding_vector=row["embedding"],
                                        embedding_model=config["representation_id"]))
    return samples


def _legacy_infer(model, rows, samples):
    results = []
    for row, sample in zip(rows, samples):
        original = _vector(sample.embedding_vector, 8)
        reconstructed = _vector(model.decode(model.encode(sample, use_sample_memory=False)), 8)
        results.append({"id": row["id"], "source_sha256": hashlib.sha256(row["source_text"].encode()).hexdigest(),
            "input_embedding": original, "reconstructed_embedding": reconstructed,
            "reconstruction_mse": sum((a-b)**2 for a,b in zip(original, reconstructed))/8,
            "reconstruction_target_access": True, "reference_ir_target_access": False,
            "learned_ir_prediction": False, "sample_memory_used": False})
    return {"dimension": 8, "rows": results,
            "reconstruction_objective": "historical_target_aware_safe_projection",
            "reconstruction_is_fidelity_evidence": False}


def _wait_for_start(start_ns):
    if start_ns is None:
        return
    now = time.monotonic_ns()
    if type(start_ns) is not int or not now < start_ns <= now + 60_000_000_000:
        raise ValueError("synchronized start must be a future monotonic time within 60 seconds")
    while True:
        remaining = start_ns-time.monotonic_ns()
        if remaining <= 0:
            return
        time.sleep(min(.005, remaining/1e9))


def _start_gate(helper, path, *, timeout_seconds=120):
    path = Path(path).resolve()
    deadline = time.monotonic()+timeout_seconds
    while not path.exists():
        if time.monotonic() >= deadline:
            raise ValueError("coordinated start gate timed out")
        time.sleep(.02)
    gate, receipt = helper.read_pinned_json(path, max_bytes=4096)
    if type(gate) is not dict or set(gate) != {"schema", "start_monotonic_ns"} or gate["schema"] != "gte-parallel-inference-start/v1":
        raise ValueError("invalid coordinated start gate")
    _wait_for_start(gate["start_monotonic_ns"])
    return receipt


def run_worker(config_path, *, expected_config_sha256=None, start_at_monotonic_ns=None, start_gate=None):
    process_started = time.monotonic_ns()
    sys.dont_write_bytecode = True
    implementation = []
    for path in (Path(__file__).resolve(), HELPER):
        raw = path.read_bytes()
        implementation.append({"path": str(path), "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()})
    helper = _helper()
    bound = helper.load_worker_contract(config_path, expected_sha256=expected_config_sha256)
    config, environment = bound["config"], bound["environment_receipt"]
    resources = helper.configure_cpu_process(config["resources"])
    affinity = _affinity(config)
    sys.path.insert(0, str(REPOSITORY))
    os.environ["IPFS_DATASETS_LEGAL_IR_METRIC_DISK_CACHE"] = "0"
    output = Path(environment["output_directory"])
    with helper.state_lease(environment["state_directory"]):
        cache = Path(environment["state_directory"]) / "cache"
        cache.mkdir(exist_ok=True)
        os.environ.update(HF_HOME=str(cache / "huggingface"), XDG_CACHE_HOME=str(cache),
                          TORCH_HOME=str(cache / "torch"))
        checkpoint, checkpoint_receipt = helper.read_pinned_json(config["checkpoint"]["path"],
            expected_sha256=config["checkpoint"]["sha256"], max_bytes=512*1024*1024)
        payload, dataset_receipt = helper.read_pinned_json(config["dataset"]["path"],
            expected_sha256=config["dataset"]["sha256"])
        rows = _inputs(payload, config)
        resources["dataset_row_limit_enforced"] = True
        runtime, descriptor, extra_receipts = _backend(config, checkpoint)
        samples = None if config["dimension"] == 384 else _prepare_legacy_samples(runtime, rows, config)
        print(json.dumps({"lane_id": config["lane_id"], "phase": "model_ready", "rows": len(rows)}), flush=True)
        if start_gate is not None and start_at_monotonic_ns is not None:
            raise ValueError("only one coordinated start method may be selected")
        gate_receipt = _start_gate(helper, start_gate) if start_gate is not None else None
        _wait_for_start(start_at_monotonic_ns)
        inference_started = time.monotonic_ns()
        numerical = runtime.infer(rows) if config["dimension"] == 384 else _legacy_infer(runtime, rows, samples)
        inference_finished = time.monotonic_ns()
        if numerical.get("dimension") != config["dimension"] or len(numerical.get("rows", [])) != len(rows):
            raise ValueError("runtime output shape differs")
        for expected, actual in zip(rows, numerical["rows"]):
            if actual.get("id") != expected["id"]:
                raise ValueError("runtime output identity differs")
            _vector(actual.get("reconstructed_embedding"), config["dimension"])
        for pin in (checkpoint_receipt, dataset_receipt, bound["config_receipt"], *extra_receipts):
            helper.read_pinned_json(pin["path"], expected_sha256=pin["sha256"], max_bytes=512*1024*1024)
        for pin in implementation:
            if hashlib.sha256(Path(pin["path"]).read_bytes()).hexdigest() != pin["sha256"]:
                raise ValueError("worker implementation changed during execution")
        import resource
        usage = resource.getrusage(resource.RUSAGE_SELF)
        report = {"schema": REPORT_SCHEMA, "lane_id": config["lane_id"], "dimension": config["dimension"],
            "runtime_id": config["runtime_id"], "representation_id": config["representation_id"],
            "checkpoint": checkpoint_receipt, "additional_checkpoint_assets": extra_receipts,
            "dataset": dataset_receipt, "configuration": bound["config_receipt"],
            "coordinated_start_gate": gate_receipt,
            "environment": environment, "resources": resources, "cpu_affinity": affinity,
            "runtime_description": descriptor, "numerical_result": numerical,
            "worker_implementation": implementation,
            "timing": {"process_started_monotonic_ns": process_started,
                       "inference_started_monotonic_ns": inference_started,
                       "inference_finished_monotonic_ns": inference_finished},
            "pid": os.getpid(), "numerical_execution_completed": True, "finite_outputs_checked": True,
            "usage": {"user_cpu_seconds": usage.ru_utime, "system_cpu_seconds": usage.ru_stime,
                      "maximum_rss": usage.ru_maxrss,
                      "maximum_rss_unit": "KiB" if sys.platform.startswith("linux") else "OS_native_units"},
            "input_pins_verified": True, "runtime_binding_verified": True,
            "reference_ir_target_access": False, "training_executed": False,
            "producer_identity_verified": config["runtime_id"] == "legal_ir:legacy_linguistic_historical_blank_en",
            "producer_semantics_verified": False,
            "encoder_outputs_recomputed": config["runtime_id"] == "legal_ir:legacy_linguistic_historical_blank_en",
            "independent_semantic_quality_verified": False, "teacher_qualified": False, "proof_authority": False}
        receipt = helper.write_fresh_output_json(output, "inference-report.json", report)
    print(json.dumps({"lane_id": config["lane_id"], "status": "completed", "report": receipt}), flush=True)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--expected-config-sha256", required=True)
    start = parser.add_mutually_exclusive_group()
    start.add_argument("--start-at-monotonic-ns", type=int,
                        help="optional coordinated diagnostic start after both models are ready")
    start.add_argument("--start-gate", type=Path,
                       help="optional owner-written future start gate after model-ready signals")
    args = parser.parse_args(argv)
    try:
        run_worker(args.config, expected_config_sha256=args.expected_config_sha256,
                   start_at_monotonic_ns=args.start_at_monotonic_ns, start_gate=args.start_gate)
    except (ValueError, OSError, KeyError, TypeError, ImportError) as error:
        parser.exit(2, "model worker failed: " + str(error) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
