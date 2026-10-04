#!/usr/bin/env python3
"""Compare residual projection update policies and conditioning on exposed data only.

No test split is read, generated, selected or relabelled as fresh evidence.
Existing embedding receipts and local assets are verified without downloading.
Actual native checks run after fitting and never repair a model prediction.
"""
from __future__ import annotations
from copy import deepcopy
import argparse
import hashlib
import json
import os
from pathlib import Path
import resource
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
FALSE = dict(qualified=False, admitted=False, formalized=False, source_semantics_verified=False,
    fresh_holdout=False, test_data_read=False, source_prediction_repaired=False,
    production_promotion_performed=False, global_convergence_proven=False, downloads_performed=False)
CONFIG = dict(epochs=1000, max_seconds=30, batch_size=16, learning_rate=.003,
    reconstruction_weight=.1, patience=120, max_target_tokens=64, scalar_value_weight=8.,
    source_conditioning="none", eval_interval=10, plateau_patience=3, plateau_factor=.5,
    min_learning_rate_ratio=.05, embedding_nonregression=True)
PARENT_SHA = "969461ab82a2806e54ad33ba242a1eb62d032fa1b3cfc808b77c66dcc965aa62"
MODES = ("initial_only", "every_step")
POLICIES = ("joint", "frozen_parent_residual")
PROJECTION_TENSORS = ("projection_down.weight", "projection_down.bias", "projection_up.weight", "projection_up.bias")
TOOLS = {"lake": ("/home/barberb/.elan/toolchains/leanprover--lean4---v4.30.0/bin/lake",
    "8c987aee79f105bc2ff21772b958b219c8921a51b8ca2df8af410a2b17bd8701"),
    "java": ("/home/barberb/.local/share/ipfs_datasets_py/theorem-provers/advisors/temurin-jdk/17.0.20+8/jdk/bin/java",
    "0cd543f9949605b5eccb1d2b98c2b8637bb0953f0b5087208393b4b7ded73c1a"),
    "tla": ("/home/barberb/.local/share/ipfs_datasets_py/theorem-provers/tlc/1.8.0/tla2tools.jar",
    "e22f8ffb4bacdea0a871f444dd94fe5fb0d8013b3388ae39e82e26f852c735d5")}


def require(value, message):
    if not value:
        raise ValueError(message)


def raw(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(raw(value)).hexdigest()


def sha(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(raw(value) + b"\n")
        stream.flush()
        os.fsync(stream.fileno())
    return {"path": str(path), "sha256": sha(path), "bytes": path.stat().st_size}


def inputs(rows):
    return [{key: row[key] for key in ("id", "source_text", "embedding")} for row in rows]


def fit_schedule():
    """Reverse all four arms for the second order seed; no measured selection."""
    arms = [(mode, policy) for mode in MODES for policy in POLICIES]
    return [(domain, seed, mode, policy) for domain in ("intent_ir", "ui_ux_ir")
            for seed in (3517, 3518) for mode, policy in (arms if seed == 3517 else list(reversed(arms)))]


def projection_state(checkpoint):
    state = checkpoint["model_state"]
    require(all(name in state for name in PROJECTION_TENSORS), "complete residual projection tensors required")
    return {name: state[name] for name in PROJECTION_TENSORS}


def projection_tensor_digest(torch, state):
    """Independent parent/selected replay of the documented named-byte digest."""
    result = hashlib.sha256()
    for name in PROJECTION_TENSORS:
        tensor = torch.tensor(state[name], dtype=torch.float32).contiguous()
        require(bool(tensor.isfinite().all()), "nonfinite projection tensor")
        metadata = raw({"name": name, "shape": list(tensor.shape), "dtype": "float32"})
        payload = tensor.view(torch.uint8).numpy().tobytes()
        for block in (metadata, payload):
            result.update(len(block).to_bytes(8, "big"))
            result.update(block)
    return result.hexdigest()


def verify_pairs(fits, runtimes):
    """Check the full factorial pairing before post-fit diagnostics."""
    comparisons = []
    for domain in ("intent_ir", "ui_ux_ir"):
        for seed in (3517, 3518):
            group = [fit for fit in fits if fit["domain"] == domain and fit["seed"] == seed]
            require(len(group) == 4 and {(f["mode"], f["projection_update_policy"]) for f in group}
                    == {(m, p) for m in MODES for p in POLICIES}, "incomplete factorial pair")
            require(len({f["lineage"]["inherited_initial_state_sha256"] for f in group}) == 1,
                    "conditioning modes did not inherit identical common parameters")
            checkpoints = [runtimes[f["identity"]].checkpoint for f in group]
            reference = checkpoints[0]
            control_config = {k: v for k, v in reference["config"].items()
                              if k not in {"decoder_conditioning", "projection_update_policy"}}
            require(all(c["parent_sha256"] == PARENT_SHA and c["codec"] == reference["codec"]
                        and {k: v for k, v in c["config"].items()
                             if k not in {"decoder_conditioning", "projection_update_policy"}} == control_config
                        for c in checkpoints), "paired parent, vocabulary or numerical recipe differs")
            require(all(f["training"]["before_validation"] == group[0]["training"]["before_validation"]
                        for f in group), "initial measured behavior differs between paired arms")
            for mode in MODES:
                pair = [f for f in group if f["mode"] == mode]
                require(len({f["lineage"]["initial_state_sha256"] for f in pair}) == 1,
                        "projection policies started from different complete parameter states")
                comparisons.append({"domain": domain, "seed": seed, "mode": mode,
                    "identities": [f["identity"] for f in pair],
                    "initial_state_sha256": pair[0]["lineage"]["initial_state_sha256"],
                    "inherited_initial_state_sha256": pair[0]["lineage"]["inherited_initial_state_sha256"],
                    "identical_initial_validation_metrics": True, "same_parent_codec_and_other_config": True})
    return comparisons


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--development-data", type=Path, required=True)
    parser.add_argument("--parent", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    require(not output.exists(), "new immutable evidence directory required")
    sys.path.insert(0, str(ROOT))
    sys.dont_write_bytecode = True
    os.environ.update(PYTHONDONTWRITEBYTECODE="1", HF_HUB_OFFLINE="1", HF_DATASETS_OFFLINE="1",
        TRANSFORMERS_OFFLINE="1", IPFS_DATASETS_PY_LAZY_INSTALL_ERGOAI="0", CUDA_VISIBLE_DEVICES="",
        OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1")
    started = time.perf_counter()
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_embedding_runtime as offline
    with offline._offline_guard():
        import torch
        torch.set_num_threads(1)
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer import domain_384_autoencoder_v4 as api
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer import resource_scheduler as resources
        from ipfs_datasets_py.logic.formalization.autoencoder import intent_ui_candidate_pipeline_v2 as pipeline
        from ipfs_datasets_py.logic.formalization.autoencoder import intent_source_contract_384 as intent
        from ipfs_datasets_py.logic.formalization.autoencoder import ui_source_contract_384_v3 as ui
        from ipfs_datasets_py.logic.formalization.autoencoder import parallel_projection_checks_v3 as checks
        from ipfs_datasets_py.logic.formalization.autoencoder import resumable_native_validation as durable
        from ipfs_datasets_py.logic.formalization.autoencoder import family_training as family_catalog
        from ipfs_datasets_py.logic.autoformal.tree_pin import require_workspace_logic_tree
        tree = require_workspace_logic_tree()
        requested_families = sorted(family_catalog._families())
        require(len(requested_families) == len(set(requested_families)) == 40, "canonical forty-family floor changed")
        pins = {}

        def pin(path, expected=None):
            path = Path(path).resolve()
            actual = sha(path)
            require(expected is None or expected == actual, "input digest differs: " + str(path))
            require(str(path) not in pins or pins[str(path)] == actual, "input changed during reading")
            pins[str(path)] = actual

        def read(path, expected=None):
            pin(path, expected)
            return json.loads(Path(path).read_bytes())

        parent = args.parent.resolve()
        parent_checkpoint = read(parent, PARENT_SHA)
        # The trainer imports the inherited checkpoint tensors as CPU float32.
        # Compare the four actual serialized tensor arrays independently of
        # the trainer's own policy receipt, not just a claimed freeze flag.
        inherited_projection = {name: torch.tensor(value, dtype=torch.float32).tolist()
                                for name, value in projection_state(parent_checkpoint).items()}
        inherited_projection_digest = projection_tensor_digest(torch, inherited_projection)
        snapshot, assets = offline._snapshot_assets(offline.DEFAULT_SNAPSHOT_PATH)
        for item in assets:
            pin(Path(snapshot) / item["name"], item["sha256"])
        for path, expected in TOOLS.values():
            pin(path, expected)
        published = read(ROOT / "docs/implementation/reports/evidence/intent-ui-coverage-20261002/manifest.json",
            "64e5a20e586624d3081a3dfbfae67595861331255df564b9f86e18fdf746e409")
        data, evidence = {}, {}
        for domain in ("intent_ir", "ui_ux_ir"):
            data[domain], evidence[domain] = {}, {}
            for split, count in (("train", 96), ("tuning", 24)):
                member = "validation/comparison-r1/" + domain + "/" + split
                rows = read(args.development_data / domain / (split + ".json"),
                    published["members"][member + ".json"]["sha256"])
                receipt = read(args.development_data / domain / (split + "-embedding-evidence.json"),
                    published["members"][member + "-embedding-evidence.json"]["sha256"])
                require(len(rows) == len(receipt["results"]) == count and receipt["assets"] == assets,
                    "complete source and embedding receipt inventory required")
                for row, encoded in zip(rows, receipt["results"]):
                    require(set(row) == {"id", "source_text", "embedding", "target"}, "closed development row required")
                    require(encoded["status"] == "embedded" and encoded["input_id"] == row["id"]
                        and encoded["source_sha256"] == hashlib.sha256(row["source_text"].encode()).hexdigest()
                        and encoded["target_sha256"] == digest(row["target"])
                        and encoded["embedding_sha256"] == digest(row["embedding"])
                        and encoded["vector"] == row["embedding"], "stored embedding/source/target join differs")
                    tokens = encoded["tokens"]
                    require(set(tokens) == {"input_ids", "attention_mask", "token_type_ids"}
                        and 0 < len(tokens["input_ids"]) <= 512
                        and len(tokens["input_ids"]) == len(tokens["attention_mask"]) == len(tokens["token_type_ids"])
                        and all(v == 1 for v in tokens["attention_mask"]), "complete recorded unpadded token input required")
                data[domain][split], evidence[domain][split] = rows, receipt
        schedule = fit_schedule()
        require(len(schedule) == len(set(schedule)) == 16, "complete sixteen-fit schedule required")
        output.mkdir(parents=True)
        plan = {"schema": "projection-freeze-development-plan/v1", "source": str(ROOT),
            "script_sha256": sha(__file__), "logic_tree": tree, "config": CONFIG,
            "schedule": schedule, "parent": {"path": str(parent), "sha256": PARENT_SHA},
            "conditioning_modes": MODES, "projection_update_policies": POLICIES,
            "arm_order": "four arms reversed for seed3518 within each domain",
            "seed_scope": "minibatch_order; identical inherited initialization across seeds",
            "initial_projection_tensor_json_sha256": digest(inherited_projection),
            "initial_projection_named_bytes_sha256": inherited_projection_digest,
            "projection_freeze_comparison": "exact float32 tensor arrays against transferred parent; no tolerance",
            "hypothesis": "freezing the inherited residual projection may protect reconstruction without weakening decoder gates",
            "runtime_implementation": api._implementation(), "assets": assets,
            "embedding_scope": "verified_stored_GTE_authored_vectors_not_qualified_SourceSampleRecords",
            "counts_per_domain": {"train": 96, "tuning": 24}, "test_split_access_allowed": False,
            "semantic_groups_disjoint": False, "tuning_groups_also_in_training_per_domain": 24,
            "data_scope": "exposed_authored_atomic_Intent_and_UI_component_compositions_not_full_documents",
            "native_indices_predeclared": [0, 1, 2], "native_attempts_expected": 48,
            "requested_families": requested_families, "native_checks_after_all_fits": True,
            "native_indices_selected_from_outputs": False, "model_predictions_repaired": False,
            "training_workers": 1, "torch_threads": 1, "temperature": 0,
            "scheduler_lane": "hammer_lean", "scheduler_workload": "canonical_trainer",
            "scheduler_lane_is_Lean_evidence": False,
            "input_files": pins.copy(), "tools": TOOLS, **FALSE}
        save(output / "plan.json", plan)
        scheduler = resources.get_global_resource_scheduler()
        save(output / "scheduler-before.json", scheduler.snapshot())
        fits, runtimes, generated = [], {}, {}
        provenance = {"model_id": "thenlper/gte-small", "revision": offline.PINNED_REVISION,
            "assets": assets, "actual_tokens_recorded": True, "downloads_performed": False,
            "verified_by_runtime": False, "verified_by_benchmark_join": True}
        for domain, seed, mode, policy in schedule:
            identity = domain + "-" + str(seed) + "-" + mode + "-" + policy
            print(json.dumps({"phase": "fit", "identity": identity}), flush=True)
            queued = time.perf_counter()
            with scheduler.acquire(resources.ResourceLane.HAMMER_LEAN, cpu_slots=1, memory_mb=2048,
                    child_process_slots=1, timeout=60, request_id="projection:" + identity) as lease:
                tick = time.perf_counter()
                admission_seconds = tick - queued
                fitted = api.train(domain, data[domain]["train"], data[domain]["tuning"],
                    parent_projection=plan["parent"], config={**CONFIG, "seed": seed,
                        "decoder_conditioning": mode, "projection_update_policy": policy,
                        "embedding_provenance": provenance})
                fit_seconds = time.perf_counter() - tick
                descriptor = save(output / identity / "checkpoint.json", fitted["checkpoint"])
                runtime = api.load_checkpoint(descriptor["path"], expected_sha256=descriptor["sha256"], expected_domain=domain)
                metrics = fitted["metrics"]
                selected_projection = projection_state(fitted["checkpoint"])
                selected_projection_digest = projection_tensor_digest(torch, selected_projection)
                unchanged = (raw(selected_projection) == raw(inherited_projection)
                             and selected_projection_digest == inherited_projection_digest)
                policy_receipt = fitted["checkpoint"]["projection_policy"]
                require(policy_receipt["mode"] == policy
                        and policy_receipt["tensor_names"] == list(PROJECTION_TENSORS)
                        and policy_receipt["inherited_projection_sha256"] == inherited_projection_digest
                        and policy_receipt["selected_projection_sha256"] == selected_projection_digest,
                        "checkpoint projection policy or actual tensor digest differs")
                if policy == "frozen_parent_residual":
                    require(unchanged and policy_receipt["frozen_projection_verified"], "frozen projection tensors changed")
                    require(set(policy_receipt["frozen_tensor_names"]) == set(PROJECTION_TENSORS)
                            and not set(policy_receipt["trainable_tensor_names"]) & set(PROJECTION_TENSORS)
                            and metrics["frozen_projection_checks_after_optimizer_steps"] == metrics["optimizer_steps"],
                            "frozen projection was not excluded and checked after every update")
                    require(abs(metrics["selected_validation"]["embedding_mse"]
                                - metrics["before_validation"]["embedding_mse"]) <= 1e-12,
                            "frozen projection changed reconstruction on identical tuning rows")
                freeze_verification = {"policy": policy, "tensor_names": list(PROJECTION_TENSORS),
                    "inherited_tensor_json_sha256": digest(inherited_projection),
                    "selected_tensor_json_sha256": digest(selected_projection),
                    "inherited_named_bytes_sha256": inherited_projection_digest,
                    "selected_named_bytes_sha256": selected_projection_digest,
                    "exact_tensor_arrays_unchanged": unchanged,
                    "comparison_scope": "serialized CPU float32 residual projection; checked independently of policy receipt"}
                save(output / identity / "training-metrics.json", metrics)
                evaluations = {}
                for split in ("train", "tuning"):
                    result = api.evaluate(fitted["checkpoint"], data[domain][split])
                    save(output / identity / (split + "-generated.json"), result)
                    evaluations[split] = result["fidelity"]
                    if split == "tuning":
                        generated[identity] = result
                expected = metrics["selected_validation"]["generated"]
                require(evaluations["tuning"] == expected, "selected saved checkpoint does not replay exact generated metrics")
                fit = {"identity": identity, "domain": domain, "seed": seed, "mode": mode,
                    "projection_update_policy": policy, "projection_policy_receipt": policy_receipt,
                    "projection_verification": freeze_verification,
                    "checkpoint": descriptor, "config": fitted["checkpoint"]["config"],
                    "lineage": fitted["checkpoint"]["lineage"], "runtime": runtime.describe(),
                    "training": metrics, "evaluations": evaluations, "full_training_call_seconds": fit_seconds,
                    "scheduler_wait_seconds": lease.wait_seconds,
                    "scheduler_acquire_call_seconds": admission_seconds,
                    "training_examples_per_optimizer_second": metrics["examples_seen"] / metrics["optimizer_seconds"],
                    "training_tokens_per_optimizer_second": metrics["training_tokens"] / metrics["optimizer_seconds"],
                    "fit_wall_seconds_per_unique_training_span": fit_seconds / len(data[domain]["train"]),
                    "training_rate_scope": "repeated example presentations and predicted tokens; not new corpus spans",
                    "unique_training_spans_per_full_fit_second": len(data[domain]["train"]) / fit_seconds, **FALSE}
                fits.append(fit)
                runtimes[identity] = runtime
                save(output / identity / "fit.json", fit)
        pairing = verify_pairs(fits, runtimes)
        save(output / "fits-sealed.json", {"fits": [{k: f[k] for k in ("identity", "checkpoint")} for f in fits],
            "plan_sha256": sha(output / "plan.json"), "pairing": pairing, "post_seal_training": False, **FALSE})
        # Read-only diagnostics after every compared checkpoint is sealed.
        jobs, attempts, comparisons = [], [], []
        for fit in fits:
            identity, domain = fit["identity"], fit["domain"]
            runtime, rows = runtimes[identity], data[domain]["tuning"]
            source_inputs = inputs(rows)
            conditioned = deepcopy(generated[identity])
            for row in conditioned["rows"]:
                row["raw_candidate_ir"] = api.fidelity.parse_generated(row["generated_tokens"], ended=row["ended"])["candidate"]
            audited = pipeline.audit_candidates(conditioned, [{k:r[k] for k in ("id", "source_text")} for r in rows])
            save(output / identity / "tuning-source-audit.json", audited)
            ablations = {}
            for mode in ("zero_condition", "zero_decoder", "shuffle_embeddings"):
                supplied = deepcopy(source_inputs)
                if mode == "shuffle_embeddings":
                    vectors = [r["embedding"] for r in supplied]
                    for index, row in enumerate(supplied):
                        row["embedding"] = vectors[(index + 1) % len(supplied)]
                result = runtime.infer(supplied, weight_ablation=None if mode == "shuffle_embeddings" else mode)
                result["fidelity"] = api._generated_metrics(domain, result["rows"], rows)
                save(output / identity / ("tuning-ablation-" + mode + ".json"), result)
                ablations[mode] = result["fidelity"]
            times = []
            expected = digest(runtime.infer(source_inputs))
            for _ in range(3):
                tick = time.perf_counter()
                actual = runtime.infer(source_inputs)
                times.append(time.perf_counter() - tick)
                require(digest(actual) == expected, "greedy inference changed during timing")
            elapsed = statistics.median(times)
            result = {"identity": identity, "domain": domain, "seed": fit["seed"], "mode": fit["mode"],
                "projection_update_policy": fit["projection_update_policy"],
                "tuning_fidelity": fit["evaluations"]["tuning"], "ablations": ablations,
                "source_audit_dispositions": audited["candidate_audit_dispositions"],
                "inference": {"seconds": times, "median_seconds": elapsed, "count": len(rows),
                    "seconds_per_span": elapsed / len(rows), "spans_per_second": len(rows) / elapsed,
                    "scope": "warm_loaded_public_runtime_with_native_candidate_validation; no_embedding_or_Lake_or_source_audit",
                    "temperature": 0, "workers": 1, "torch_threads": 1,
                    "warmup_calls": 1, "timed_repeats": 3, "timings_are_descriptive": True,
                    "bridge_on_evaluation_ran": False}, **FALSE}
            comparisons.append(result)
            save(output / identity / "comparison.json", result)
            for index in plan["native_indices_predeclared"]:
                candidate = audited["rows"][index]
                job_id = identity + "-" + str(index)
                attempt = {"job_id": job_id, "source_text": rows[index]["source_text"],
                    "candidate": candidate, "status": "blocked_by_source_or_generation", **FALSE}
                if candidate["eligible_for_family_preparation"]:
                    adapter = intent if domain == "intent_ir" else ui
                    packet = adapter.prepare_family_targets(rows[index]["source_text"], candidate["candidate_ir"],
                                                            requested_families=requested_families)
                    require(packet["report"]["requested_families"] == requested_families,
                        "native family inventory narrowed")
                    attempt.update(status="prepared", report=packet["report"])
                    jobs.append(checks.NativeProjectionJob(job_id, packet["report"], packet["source_inputs"]))
                attempts.append(attempt)
        require(len(attempts) == plan["native_attempts_expected"], "predeclared native attempts missing")
        save(output / "native-attempts.json", attempts)
        native_receipt, gates = None, {}
        if jobs:
            native = durable.run_resumable_native_validation(jobs, owner=durable.NativeValidationOwner.from_module(checks),
                output_directory=output / "native-validation", scheduler=scheduler,
                max_admission_seconds=300, max_attempts_per_job=3, retry_backoff_seconds=1,
                max_workers=2, native_memory_mb=1024, native_cpu_slots=2, native_child_process_slots=2,
                lease_wait_timeout_seconds=30, native_step_timeout_seconds=60,
                lake_executable=TOOLS["lake"][0], java_executable=TOOLS["java"][0], tla2tools_jar=TOOLS["tla"][0])
            native_receipt = native["receipt"]
            for row in native["live_jobs"]:
                gates[row["job_id"]] = checks.validation.evaluate_projection_training_batch([row["observation"]],
                    domain_id=row["report"]["domain_id"], target_reports=[row["report"]])
                require(not gates[row["job_id"]]["strict_training_allowed"], "fragment panel cannot grant whole-modality training qualification")
        save(output / "native-strict-gates.json", gates)
        loaded = {name: {"path": str(Path(module.__file__).resolve()), "sha256": sha(module.__file__)}
            for name, module in tuple(sys.modules.items()) if name.startswith("ipfs_datasets_py") and getattr(module, "__file__", None)}
        require(all(Path(value["path"]).is_relative_to(ROOT) for value in loaded.values()), "producer outside chosen source")
        api._guard()
        require(all(sha(path) == value for path, value in pins.items()), "input/asset/parent changed")
        require(all(sha(f["checkpoint"]["path"]) == f["checkpoint"]["sha256"] for f in fits), "sealed model changed")
        save(output / "loaded-modules.json", loaded)
        save(output / "input-provenance.json", {"files": pins, "all_inputs_unchanged": True})
        summary = {"schema": "projection-freeze-development-results/v1", "fits": fits,
            "pairing": pairing, "conditioning_modes": MODES, "projection_update_policies": POLICIES,
            "comparisons": comparisons, "native_attempt_count": len(attempts), "native_prepared_count": len(jobs),
            "native_receipt": native_receipt, "strict_training_gate_count": len(gates),
            "elapsed_seconds": time.perf_counter() - started, "max_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            "rss_scope": "single_Python_parent_excludes_native_child_RSS", "all_inputs_unchanged": True,
            "parent_unchanged": True, "checkpoints_sealed": True, "scheduler_after": scheduler.snapshot(),
            "development_training_executed": True, "checkpoint_promotion_performed": False, **FALSE}
        save(output / "summary.json", summary)
        print(json.dumps({"fits": len(fits), "native_attempts": len(attempts), "native_prepared": len(jobs),
            "elapsed_seconds": summary["elapsed_seconds"], "tuning_exact": {c["identity"]:c["tuning_fidelity"]["exact_count"] for c in comparisons}}), flush=True)


if __name__ == "__main__":
    main()
