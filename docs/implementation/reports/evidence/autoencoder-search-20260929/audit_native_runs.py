"""Read-only audit of completed native runs and exact baseline/optimized parity.

Run each audit while that run's captured source remains installed. ``compare``
reads sealed audit outputs only. Neither command trains, builds Lean, downloads
weights, promotes candidates, or changes a registry. cProfile runs are not speed
baselines. The inputs are synthetic fixtures, not a federal-corpus admission.
"""
from __future__ import annotations
import argparse
import gc
import hashlib
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))


def read(path):
    return json.loads(Path(path).read_bytes())


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def digest(value):
    return sha(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode())


def descriptor(path):
    path = Path(path).resolve()
    raw = path.read_bytes()
    return {"path": str(path), "sha256": sha(raw), "bytes": len(raw)}


def write(path, payload):
    with Path(path).open("x") as stream:
        json.dump(payload, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")


class Audit:
    def __init__(self):
        self.checks = []

    def check(self, value, name):
        self.checks.append({"name": name, "passed": bool(value)})

    def result(self):
        failures = [row["name"] for row in self.checks if not row["passed"]]
        return {"passed": not failures, "check_count": len(self.checks), "failures": failures}


def audit_refinements(report, limit, check, label, *, expect_training_first=False):
    """Check bounded trial records without counting their nested copies twice."""
    config = report.get("projection_composed_refinement", {})
    check(config.get("enabled") is bool(limit) and config.get("max_attempts_per_epoch") == limit
          and config.get("validation_gradients_used") is False
          and config.get("acceptance_policy") == "strict_validation_gain_preserved_and_training_reconstruction_improved",
          label + ":refinement_policy")
    result = []
    def finite(value):
        return type(value) in (int, float) and math.isfinite(value)
    for epoch in report["epoch_reports"]:
        candidates = epoch.get("candidate_reports", [])
        trials = [candidate for candidate in candidates if candidate.get("composed_refinement") is True]
        check(len(trials) <= limit and [row.get("refinement_attempt") for row in trials] == list(range(1, len(trials) + 1)),
              label + ":bounded_sequential_refinement_trials")
        seeds = {trial.get("base_selected_update") for trial in trials}
        check(len(seeds) <= 1, label + ":one_fixed_refinement_seed_per_epoch")
        for trial in trials:
            trial_label = label + ":refinement:" + str(trial["refinement_attempt"])
            seed_candidates = [candidate for candidate in candidates if candidate.get("update") == trial["base_selected_update"]]
            check(len(seed_candidates) == 1, trial_label + ":seed_exists")
            if len(seed_candidates) != 1:
                continue
            seed = seed_candidates[0]
            check(seed.get("strict_accepted") is True and seed.get("composed_refinement_reports") == trials,
                  trial_label + ":strict_seed_and_duplicate_telemetry_match")
            check(trial.get("update") == trial["base_selected_update"] + "+decoded_embedding_refinement:" + str(trial["refinement_attempt"])
                  and trial.get("training_sample_count") == trial.get("validation_sample_count") == 1
                  and trial.get("training_metric_scope") == "bridge_off_reconstruction_only"
                  and trial.get("update_norm_scope") == "embedding_refinement_increment_only",
                  trial_label + ":gradient_and_metric_scope")
            if expect_training_first:
                check(trial.get("evaluation_order") == "training_before_validation"
                      and type(trial.get("training_evaluated")) is bool,
                      trial_label + ":explicit_training_first_evaluation_order")
                training_before = trial.get("training_before", {}).get("reconstruction_loss")
                training_after = trial.get("training_after", {}).get("reconstruction_loss")
                training_delta = trial.get("training_reconstruction_delta")
                if trial.get("training_evaluated"):
                    if all(finite(value) for value in (training_before, training_after, training_delta)):
                        check(training_delta == training_before - training_after,
                              trial_label + ":exact_training_screen_delta")
                    else:
                        check(not trial.get("accepted") and "nonfinite_training_metric" in trial.get("rejection_reasons", []),
                              trial_label + ":nonfinite_training_screen_rejected")
                if trial.get("holdout_evaluated"):
                    check(trial.get("training_evaluated") is True and finite(training_delta) and training_delta > 0,
                          trial_label + ":validation_only_after_positive_training_screen")
                else:
                    check(trial.get("accepted") is False and trial.get("objective_delta") is None
                          and "validation_after" not in trial and "cross_entropy_delta" not in trial,
                          trial_label + ":no_fabricated_skipped_validation")
                    check(trial.get("validation_evaluation_skipped_reason") == "training_screen_rejected"
                          or "projection_timeout" in trial.get("rejection_reasons", []),
                          trial_label + ":skipped_validation_has_reason")
            if trial.get("accepted"):
                before, after = trial.get("training_before", {}), trial.get("training_after", {})
                delta = trial.get("training_reconstruction_delta")
                values = [before.get("reconstruction_loss"), before.get("embedding_cosine_similarity"),
                          after.get("reconstruction_loss"), after.get("embedding_cosine_similarity"), delta,
                          trial.get("objective_delta"), trial.get("validation_objective_delta_required")]
                check(all(finite(value) for value in values), trial_label + ":finite_accepted_metrics")
                if all(finite(value) for value in values):
                    check(delta == before["reconstruction_loss"] - after["reconstruction_loss"] and delta > 0,
                          trial_label + ":training_reconstruction_improves")
                    check(trial["objective_delta"] >= trial["validation_objective_delta_required"] == seed["objective_delta"] > 0,
                          trial_label + ":strict_seed_validation_gain_preserved")
                check(trial.get("strict_accepted") is True and trial.get("holdout_evaluated") is True
                      and trial.get("acceptance_source") == "strict_composed_refinement"
                      and not trial.get("rejection_reasons") and not trial.get("pareto_regressions")
                      and not trial.get("selected_candidate_regressions"), trial_label + ":strict_guardrail_acceptance")
            else:
                check(trial.get("strict_accepted") is False and trial.get("acceptance_source") == "rejected"
                      and bool(trial.get("rejection_reasons")), trial_label + ":rejected_trial_has_reason")
        selected_name = epoch.get("selected_update")
        if epoch.get("accepted"):
            selected = [candidate for candidate in candidates if candidate.get("update") == selected_name]
            check(len(selected) == 1 and selected[0].get("accepted") is True
                  and selected[0].get("holdout_evaluated") is True, label + ":selected_candidate_actually_accepted")
        result.append({"epoch": epoch["epoch"], "trial_count": len(trials), "accepted_trial_count": sum(bool(row.get("accepted")) for row in trials),
                       "selected_update": selected_name, "selected_refinement": any(row.get("update") == selected_name for row in trials),
                       "trials": trials})
    return result


def audit_owner_envelope(resource, training, check):
    """Verify declared worker/owner envelopes against the one outer lease.

    These are cooperative reservation checks, not measured CPU quotas or a
    claim that instantaneous native-library thread counts were observed.
    """
    record, lease = resource["record"], resource["resource_lease"]
    dimensions = ("cpu_slots", "memory_mb", "child_process_slots")
    check(all(type(record.get(key)) is int and record[key] > 0 and lease.get(key) == record[key]
              for key in dimensions), "owner_envelope:ledger_matches_scheduler_lease")
    plans = training["capacity_reports"]
    dispatches = training["dispatch_reports"]
    check(len(plans) == len(dispatches), "owner_envelope:one_plan_per_native_dispatch")
    verified = []
    for index, dispatch in enumerate(dispatches):
        label = "owner_envelope:dispatch:" + str(index)
        plan = dispatch.get("dispatch_capacity", {})
        check(index < len(plans) and plan == plans[index], label + ":sealed_capacity_plan")
        workers = plan.get("workers")
        envelope, limits = plan.get("execution_envelope", {}), plan.get("limits", {})
        policy = envelope.get("estimate_policy", {})
        check(type(workers) is int and 0 < workers == dispatch.get("max_workers")
              <= training["max_parallel_workers"], label + ":actual_dispatch_width")
        check(envelope.get("execution_mode") == "training" and envelope.get("workers") == workers
              and envelope.get("worker_cpu_slots") == workers and envelope.get("coordinator_cpu_slots") == 1
              and type(workers) is int and envelope.get("cpu_slots") == workers + 1
              and policy.get("reserve_cpu_slots") == 1, label + ":one_coordinator_cpu")
        check(all(type(limits.get(key)) is int and limits[key] >= workers for key in limits)
              and bool(limits) and workers == min(limits.values()), label + ":fits_every_capacity_limit")
        check(limits.get("reservation_cpu") == record["cpu_slots"] - 1,
              label + ":nested_reservation_subtracts_owner_once")
        process_slots = policy.get("reserve_process_slots", -1) + workers * policy.get("per_worker_process_slots", -1)
        memory_mb = policy.get("reserve_mb", -1) + workers * policy.get("per_worker_memory_mb", -1)
        check(policy.get("reserve_process_slots") == 4 and policy.get("per_worker_process_slots") == 1
              and envelope.get("child_process_slots") == process_slots
              and policy.get("reserve_mb") == 2048 and policy.get("per_worker_memory_mb") == 1152
              and envelope.get("estimated_memory_mb") == memory_mb,
              label + ":declared_nested_model_and_lake_envelope")
        check(envelope.get("cpu_slots", record["cpu_slots"] + 1) <= record["cpu_slots"]
              and process_slots <= record["child_process_slots"] and memory_mb <= record["memory_mb"],
              label + ":no_outer_reservation_overdraw")
        verified.append({"workers": workers, "envelope": envelope, "capacity_limits": limits})
    return {"checked": True, "reservation": {key: record[key] for key in dimensions},
            "dispatches": verified,
            "scope": "cooperative_declared_envelopes_not_kernel_or_native_thread_quota"}



def audit_qualification_waves(root, resource, training, captured, check):
    """Verify declared qualification capacity and sealed spawned-worker output."""
    plans = training.get("qualification_capacity_reports", [])
    waves = training.get("qualification_wave_reports", [])
    completed = {row["run_id"]: row for row in training["completed"]}
    record = resource["record"]
    check(training.get("qualification_deferred") is False and len(plans) == len(waves) > 0,
          "qualification_waves:complete_nondeferred_plan_records")
    seen, sealed = [], []
    for index, wave in enumerate(waves):
        label = "qualification_wave:" + str(index)
        plan = wave.get("dispatch_capacity", {})
        width, ids = wave.get("max_workers"), wave.get("run_ids", [])
        envelope, limits = plan.get("execution_envelope", {}), plan.get("limits", {})
        check(index < len(plans) and plan == plans[index], label + ":sealed_capacity_plan")
        check(type(width) is int and 0 < width <= training.get("max_qualification_workers", 0)
              and width == plan.get("workers") == wave.get("job_count") == len(ids)
              and len(set(ids)) == len(ids) and set(ids).issubset(completed), label + ":exact_wave_members")
        check(wave.get("registry_writes_in_workers") is False and wave.get("admitted") is False,
              label + ":parent_only_registry_and_no_admit")
        check(type(wave.get("elapsed_seconds")) in (int, float)
              and math.isfinite(wave["elapsed_seconds"]) and wave["elapsed_seconds"] > 0,
              label + ":finite_observed_wall_time")
        check(bool(limits) and all(type(value) is int and value >= width for value in limits.values())
              and width == min(limits.values()), label + ":fits_every_capacity_limit")
        check(envelope.get("execution_mode") == "qualification" and envelope.get("workers") == width
              and envelope.get("worker_cpu_slots") == width and envelope.get("coordinator_cpu_slots") == 1
              and envelope.get("cpu_slots") == width + 1,
              label + ":one_coordinator_cpu")
        policy = envelope.get("estimate_policy", {})
        if width >= 2:
            check(wave.get("execution_strategy") == "spawned_qualification_wave"
                  and wave.get("producer_manifest") == captured
                  and plan.get("execution_strategy") == "spawned_processes",
                  label + ":spawned_same_source_processes")
            expected_memory, expected_process = 2048 + width * 1792, 2 + width * 3
            check(policy.get("reserve_mb") == 2048 and policy.get("per_worker_memory_mb") == 1792
                  and policy.get("reserve_process_slots") == 2 and policy.get("per_worker_process_slots") == 3,
                  label + ":qualification_model_lake_lean_costs")
        else:
            check(wave.get("execution_strategy") == "parent_serial_qualification"
                  and plan.get("execution_strategy") == "owner_serial"
                  and "parallel_capacity" in plan, label + ":bounded_parent_serial_fallback")
            expected_memory, expected_process = 2048, 4
        check(envelope.get("estimated_memory_mb") == expected_memory
              and envelope.get("child_process_slots") == expected_process
              and envelope.get("cpu_slots", record["cpu_slots"] + 1) <= record["cpu_slots"]
              and expected_memory <= record["memory_mb"]
              and expected_process <= record["child_process_slots"], label + ":within_original_outer_reservation")
        seen.extend(ids)
        if width < 2:
            continue
        for run_id in ids:
            job = read(root / "progress" / (run_id + ".json"))
            policy_binding = training["binding"]["policy"]
            directory = root / "progress/qualifications" / run_id
            seal_path = directory / "qualification-completion.json"
            seal = read(seal_path)
            q = read(directory / "qualification.json")
            def checkpoint_path(ref):
                return {**ref, "path": str(root / "artifacts" / ref["sha256"][:2] / ref["sha256"])}
            candidate = q["candidate_artifact"]
            validation = list({digest(row): row for row in job["validation_samples"] + policy_binding["qualification_samples"]}.values())
            request = {"run_id": run_id, "training_job_sha256": digest(job),
                       "qualification_policy_sha256": sha(json.dumps(policy_binding, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode()),
                       "candidate_version_id": q["candidate_version_id"],
                       "candidate_artifact": checkpoint_path(candidate),
                       "checkpoint_dependencies": [checkpoint_path(ref) for ref in sorted(q["checkpoint_artifacts"], key=lambda ref: ref["sha256"]) if ref != candidate],
                       "samples": job["samples"], "heldout_samples": validation,
                       "model_config": job["autoencoder_config"],
                       "lake_timeout_seconds": policy_binding["lake_timeout_seconds"],
                       "output_directory": str(directory)}
            request_sha = sha(json.dumps(request, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode())
            check(seal.get("schema_version") == "autoencoder-qualification-completion/v1"
                  and seal.get("producer_manifest") == captured and seal.get("job_sha256") == request_sha,
                  run_id + ":exact_spawned_qualification_request_seal")
            observed = {}
            for path in sorted(directory.rglob("*")):
                relative = path.relative_to(directory)
                if ".lake" in relative.parts or relative.as_posix() == "qualification-completion.json":
                    continue
                check(not path.is_symlink(), run_id + ":no_evidence_symlink:" + relative.as_posix())
                if path.is_file():
                    raw = path.read_bytes()
                    observed[relative.as_posix()] = {"sha256": sha(raw), "bytes": len(raw)}
            check(observed == seal.get("evidence") and "qualification.json" in observed
                  and len(observed) <= 8192 and sum(ref["bytes"] for ref in observed.values()) <= 256 * 1024 * 1024,
                  run_id + ":complete_portable_evidence_seal")
            reference = completed[run_id]["qualification_artifact"]
            staged = read(root / "artifacts" / reference["sha256"][:2] / reference["sha256"])
            check({key: value for key, value in q.items() if key != "receipt_artifact"} == staged,
                  run_id + ":spawned_evidence_matches_owner_staged_receipt")
            sealed.append({"run_id": run_id, "seal": descriptor(seal_path),
                           "job_sha256": request_sha, "evidence_file_count": len(observed)})
    check(len(seen) == len(set(seen)) and set(seen) == set(completed),
          "qualification_waves:every_fresh_completed_candidate_exactly_once")
    return {"checked": True, "waves": waves, "sealed_spawned_qualifications": sealed,
            "scope": "Declared resource bounds, exact requests and evidence; existing per-candidate gates remain independently audited."}


def audit_run(args):
    import duckdb
    from ipfs_datasets_py.logic.autoformal.family_qualification import REQUIRED_FAMILIES, validate_family_artifact
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_native_pool import _package_manifest
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_training_worker import BRIDGE_NAMES
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder_sparse_checkpoint import resolve_checkpoint
    audit = Audit()
    check = audit.check
    root, binding, command = args.run.resolve(), read(args.binding), read(args.command)
    captured = binding["producer_manifest"]
    pinned_sha = "1446cb1859ddf4ed40fb5576f6e320eece4cec268a008c5c07bffeaf959cd8dd"
    pinned = ROOT / "workspace/todo-queues/legal-ir-daemon-restart12-20260608T075001Z-best-8h-autoencoder.state.json"
    check(binding.get("checkpoint", {}).get("sha256", binding.get("checkpoint_sha256")) == pinned_sha == sha(pinned.read_bytes()), "exact_protected_seed_unchanged")
    check(command["returncode"] == 0 and command["source_unchanged"] and command["checkpoint_unchanged"], "native_command_success_and_unchanged_sources_seed")
    check(not command.get("instrumentation"), "unprofiled_route_for_wall_comparison")
    observed_producer_before = _package_manifest()
    check(observed_producer_before == captured, "current_complete_producer_matches_run_binding")
    paths = list((root / "cycles").glob("*/cycle.json"))
    if len(paths) != 1:
        raise ValueError("audit expects one completed cycle; resume cycles need a separate audit")
    cycle_path = paths[0]
    cycle = read(cycle_path)
    training = cycle["training"]
    resource = read(cycle_path.parent / "resources.json")
    check(cycle["source_hashes"] == binding["core_sources"] and cycle["orchestration_hashes"] == binding["orchestration"], "core_and_orchestration_binding")
    check(training["native_cycle_manifest"] == training["binding"]["policy"]["native_producer_manifest"] == captured, "durable_native_producer_binding")
    check(not training["reuse_native_workers"] and cycle["temperature"] == 0 and cycle["execution_path"] == "training", "fresh_temperature_zero_training_route")
    check(not training["pending_batch_count"] and not training["blocked"] and len(training["completed"]) == args.expected_rows, "bounded_terminal_work")
    check(not cycle["heldout_canary"] and not cycle["admitted"] and not cycle["formalized"] and not training["promotion_performed"] and not training["publication_performed"], "no_admission_promotion_or_independent_canary_claim")
    check(resource["status"] == "released" and resource["storage_limit_bytes"] == 80_000_000_000 and resource["record"]["artifacts_durable_asserted"] and not resource["record"]["attempt_exceeded_reservation"], "durable_resource_release_with_unchanged_cap")
    if args.expect_finalization:
        profile = resource["record"].get("finalization_profile", {})
        check(profile.get("global_inventory_count") == profile.get("strict_attempt_inventory_count") == 1, "one_fresh_final_global_and_attempt_inventory")
    cpu_envelope_audit = (audit_owner_envelope(resource, training, check)
                          if args.expect_owner_cpu else {"checked": False})
    qualification_wave_audit = (audit_qualification_waves(root, resource, training, captured, check)
                                if args.expect_qualification_waves else {"checked": False})
    for name, value in binding["orchestration"].items():
        path = Path(name) if Path(name).is_absolute() else ROOT / name
        check(sha(path.read_bytes()) == value, "current_orchestration:" + name)
    for input_name, key in ((args.input, "input_sha256"), (args.validation, "validation_sha256")):
        check(sha(Path(input_name).read_bytes()) == binding[key], key)
    def cas(ref):
        return root / "artifacts" / ref["sha256"][:2] / ref["sha256"]
    def verified(ref):
        raw = cas(ref).read_bytes()
        check(len(raw) == ref["bytes"] and sha(raw) == ref["sha256"], "cas:" + ref["sha256"])
        return json.loads(raw)
    for dispatch in training["dispatch_reports"]:
        control = dispatch["weight_control"]
        check(dispatch["execution_mode"] == "native_training" and not dispatch["failed"] and control["transport"] == "native_scoped_quack_prototype" and control["database_writer_count"] == 1, "native_owner_quack_dispatch")
        check(control["command_counts"].get("ReadRun", 0) > 0 and control["command_counts"].get("ReadVersion", 0) > 0 and control["command_counts"].get("CompleteRun", 0) > 0, "shared_control_read_and_write")
    rows, proofs, formula_count = {}, [], 0
    all_train, all_validation = set(), set()
    gates_required = {"metric_gate", "semantic_gate", "family_syntax_gate", "lake_gate", "heldout_gate"}
    for completed in training["completed"]:
        run_id = completed["run_id"]
        job = read(root / "progress" / (run_id + ".json"))
        worker_ref = completed["optimizer"]["result"]["worker_receipt_artifact"]
        worker = verified(worker_ref)
        check(worker == read(Path(job["output_directory"]) / "receipt.json") and worker["job_spec"] == job and worker["job_spec_canonical_sha256"] == digest(job), run_id + ":exact_job_and_worker")
        check(worker["execution_mode"] == "native_training" and worker["execution_gate_applied"] and worker["runtime"]["native_pool"] is None and not worker["admitted"], run_id + ":native_fresh_worker")
        check(worker["tree_file_sha256"] == binding["core_sources"], run_id + ":core_source_roles")
        for role, path in worker["tree_paths"].items():
            check(Path(path).resolve().is_relative_to(ROOT / "ipfs_datasets_py") and sha(Path(path).read_bytes()) == binding["core_sources"][role], run_id + ":current_pinned_core:" + role)
        config = job["training_config"]
        check(config.get("projection_max_composed_refinement_attempts", 0) == args.refinement, run_id + ":explicit_refinement_budget")
        check(worker["shared_targets_verified"] is args.shared_targets, run_id + ":shared_target_mode")
        check(list(worker["bridge_names"]) == list(BRIDGE_NAMES) and worker["legal_ir_evaluate_provers"] is False and worker["metric_disk_cache"] == 0 and worker["use_sample_memory"] is False and worker["legal_ir_parallel_workers"] == 1 and config["projection_update_backend"] == "python_sparse_batch", run_id + ":five_bridge_measurement_config")
        train_keys = {" ".join(row["text"].casefold().split()) for row in job["samples"]}
        validation_keys = {" ".join(row["text"].casefold().split()) for row in job["validation_samples"]}
        all_train.update(train_keys)
        all_validation.update(validation_keys)
        check(len(job["samples"]) == len(job["validation_samples"]) == 1 and not train_keys & validation_keys and not worker["overlapping_sample_ids"] and not worker["overlapping_normalized_text_sha256"], run_id + ":disjoint_gradient_selection_rows")
        report = worker["training_report"]
        refinement_audit = audit_refinements(report, args.refinement, check, run_id,
                                             expect_training_first=args.expect_training_first_refinement)
        check(worker["optimizer_accepted_epochs"] == report["accepted_epochs"] and report["validation_sample_count"] == 1 and report["before"]["legal_ir_target_count"] == report["after"]["legal_ir_target_count"] == 1, run_id + ":nonempty_validation_bridge_targets")
        check(all(not epoch.get("accepted") or epoch.get("holdout_evaluated") is True for epoch in report["epoch_reports"]), run_id + ":accepted_selection_evaluated_validation")
        qualification = verified(completed["qualification_artifact"])
        validation = list({digest(row): row for row in job["validation_samples"] + training["binding"]["policy"]["qualification_samples"]}.values())
        check(qualification["candidate_version_id"] == completed["optimizer"]["candidate_version_id"] and qualification["sample_set_sha256"] == digest({"training": job["samples"], "heldout": validation}) and qualification["requested_model_config"] == job["autoencoder_config"], run_id + ":exact_candidate_samples_model")
        check(qualification["execution_path"] == "inference" and qualification["execution_gate_applied"] and not qualification["training_executed"], run_id + ":immutable_qualification")
        for role, path in qualification["source_files"].items():
            check(sha(Path(path).read_bytes()) == qualification["source_sha256"][role], run_id + ":current_qualification_source:" + role)
        allowed = {ref["sha256"]: ref for ref in qualification["checkpoint_artifacts"]}
        def resolver(ref):
            check(allowed.get(ref["sha256"]) == ref, run_id + ":replay_closure_authority")
            return cas(ref)
        replay = resolve_checkpoint(qualification["candidate_artifact"], resolver=resolver, reset_revision=False)
        check(dict(replay.materialized_checkpoint) == worker["candidate_materialized_checkpoint"] == qualification["materialized_checkpoint"], run_id + ":exact_materialized_candidate_replay")
        check(replay.state.state_identity_record().to_dict() == worker["candidate_state_identity"] and {ref["sha256"] for ref in replay.artifacts} == set(allowed), run_id + ":complete_state_identity_and_closure")
        depth = replay.depth
        del replay
        gc.collect()
        semantic_rows = []
        for row in qualification["rows"]:
            label = run_id + ":" + row["split"]
            check(sha(row["source"]["text"].encode()) == row["source_sha256"] and row["semantic_gate"]["passed"] and row["compiler"]["compiler_status"] == "compiled", label + ":source_compile_roundtrip")
            metric = row["metric_gate"]
            check(metric["min_cosine"] == .72 and metric["max_reconstruction_loss"] == .20, label + ":unchanged_metric_thresholds")
            cosine, loss = metric.get("embedding_cosine_similarity"), metric.get("reconstruction_loss")
            metric_passed = (type(cosine) in (int, float) and type(loss) in (int, float)
                             and math.isfinite(cosine) and math.isfinite(loss)
                             and .72 <= cosine <= 1.0 and 0.0 <= loss <= .20)
            check(metric["passed"] is metric_passed, label + ":recomputed_absolute_metric_gate")
            families, lean = [], []
            for fragment in row["family_syntax_gate"]["rows"]:
                check(set(fragment["families"]) == set(REQUIRED_FAMILIES) and fragment["passed"] and fragment["source_sha256"] == row["source_sha256"] and fragment["rule_sha256"] == digest(fragment["canonical_rule"]), label + ":six_bound_families")
                family_artifacts = {}
                for family, artifact in fragment["families"].items():
                    parsed = validate_family_artifact(family, artifact["formula"])
                    check(parsed["passed"] and parsed["syntax_valid"] and parsed["consumed_all_input"] and artifact["source_bound"] and artifact["source_sha256"] == row["source_sha256"] and artifact["rule_sha256"] == fragment["rule_sha256"] and sha(artifact["formula"].encode()) == artifact["formula_sha256"], label + ":reparse:" + family)
                    family_artifacts[family] = {key: artifact[key] for key in ("formula_sha256", "rule_sha256", "source_sha256", "representation_coverage")}
                    formula_count += 1
                families.append(family_artifacts)
            for proof in row["lake_gate"]["rows"]:
                source, log = Path(proof["source_file"]).read_bytes(), Path(proof["log"]["path"]).read_bytes()
                lock = proof["source_lock"]
                duration = row["compiler"]["rule"].get("temporal_records", [])
                quantities = [item.get("quantity") for item in duration if item.get("temporal_kind") == "minimum_duration"]
                check(len(quantities) == 1 and type(quantities[0]) is int
                      and proof["pattern"] == {"kind": "threshold", "meet": quantities[0], "fail": quantities[0] - 1}, label + ":numeric_pattern_matches_source_duration")
                check(proof["passed"] and proof["lake_ok"] and proof["returncode"] == 0 and proof["command"] == ["lake", "build", "Legal"] and b"Built Legal" in log and b"error:" not in log, label + ":actual_lake_build_receipt")
                check(proof["scope"] == "source_locked_numeric_pattern" and lock["ok"] and source == lock["source"].encode() and sha(source) == proof["lean_source_sha256"] == lock["lock"]["expected_source_sha256"] == lock["lock"]["candidate_source_sha256"], label + ":exact_lean_source_lock")
                check(len(log) == proof["log"]["bytes"] and sha(log) == proof["log"]["sha256"] and all(token not in source for token in (b"Mathlib", b"sorry", b"axiom")), label + ":proof_source_and_log_seals")
                lean.append({key: proof[key] for key in ("lean_source_sha256", "pattern", "command", "returncode", "scope")})
                proofs.append({"run_id": run_id, "split": row["split"], "source": descriptor(proof["source_file"]), "log": proof["log"]})
            semantic_rows.append({"split": row["split"], "source": row["source"], "metric_gate": metric, "compiler": row["compiler"], "families": families, "lean": lean})
        gates = {name: value["passed"] for name, value in qualification["gate_results"].items()}
        check(set(gates) == gates_required and completed["qualified"] == qualification["qualified"] == all(gates.values()), run_id + ":all_required_gates")
        check(completed["publication"] is None, run_id + ":no_smoke_upload")
        if not completed["qualified"]:
            tasks = verified(completed["repair_outbox"])["tasks"]
            check(completed["qualification_status"] in {"training_exhausted", "needs_repair"} and bool(tasks), run_id + ":failed_gate_remains_repair_work")
        key = digest(job["samples"])
        check(key not in rows, run_id + ":one_terminal_attempt_per_fixture")
        metrics = {phase: {key: value for key, value in report[phase].items() if key not in {"evaluation_profile", "legal_ir_target_hashes"}} for phase in ("before", "after")}
        first_evaluation = next((event.get("metadata", {}).get("evaluation_profile") for event in report.get("projection_profile", {}).get("events", []) if event.get("stage") == "before_holdout_evaluation"), None)
        rows[key] = {"run_id": run_id, "source_text": job["samples"][0]["text"], "samples": job["samples"], "validation_samples": job["validation_samples"], "lane": completed["lane_index"], "training_config": config, "model_config": job["autoencoder_config"], "base": worker["base_materialized_checkpoint"], "base_identity": worker["base_state_identity"], "candidate": worker["candidate_materialized_checkpoint"], "candidate_identity": worker["candidate_state_identity"], "chain_depth": depth, "accepted_epochs": worker["optimizer_accepted_epochs"], "selected_updates": [epoch.get("selected_update") for epoch in report["epoch_reports"]], "training_metrics_sha256": digest(metrics), "training_metrics": metrics, "composed_refinement": report.get("projection_composed_refinement"), "refinement_trials": refinement_audit, "qualified": completed["qualified"], "status": completed["qualification_status"], "gates": gates, "qualification_rows": semantic_rows, "training_seconds": worker["training_seconds"], "worker_wall_seconds": worker["elapsed_seconds"], "qualification_seconds": qualification["elapsed_seconds"], "first_bridge_on_evaluation": first_evaluation, "target_cache_mode": "verified_shared_targets" if args.shared_targets else "fresh_worker_disk_cache_off", "worker_receipt": worker_ref, "qualification_receipt": completed["qualification_artifact"]}
    check(not all_train & all_validation and len(all_train) == args.expected_rows and len(all_validation) == 1, "global_train_validation_disjoint")
    check(len(proofs) == 2 * args.expected_rows and formula_count == 12 * args.expected_rows, "actual_proof_and_syntax_evidence_counts")
    with duckdb.connect(str(root / "progress/qualification.duckdb"), read_only=True) as db:
        check(dict(db.execute("SELECT latest,status FROM batches").fetchall()) == {r["run_id"]: r["status"] for r in rows.values()}, "durable_batch_statuses")
        check(db.execute("SELECT count(*) FROM attempts WHERE completed IS NULL").fetchone()[0] == 0, "no_unfinished_attempts")
    with duckdb.connect(str(root / "control.duckdb"), read_only=True) as db:
        check(db.execute("SELECT count(*) FROM autoencoder_control.heads").fetchone()[0] == 0, "no_global_head_promotion")
        check(db.execute("SELECT count(*) FROM autoencoder_control.outbox WHERE consumer <> 'ducklake'").fetchone()[0] == 0, "no_hub_outbox")
        check(dict(db.execute("SELECT run_id,status FROM autoencoder_control.runs").fetchall()) == {r["run_id"]: "completed" for r in rows.values()}, "optimizer_completion_is_separate_from_qualification")
    observed_producer_after = _package_manifest()
    check(observed_producer_after == captured, "producer_unchanged_during_read_only_audit")
    return {"schema": "native-optimizer-run-audit/v1", **audit.result(), "binding": descriptor(args.binding), "command": descriptor(args.command), "cycle": descriptor(cycle_path), "producer_manifest": captured, "observed_producer_before": observed_producer_before, "observed_producer_after": observed_producer_after, "core_sources": binding["core_sources"], "input_sha256": binding["input_sha256"], "validation_sha256": binding["validation_sha256"], "configuration": {"refinement_attempts": args.refinement, "shared_targets": args.shared_targets, "bridge_names": list(BRIDGE_NAMES), "provers": False, "metric_disk_cache": 0, "bridge_workers": 1, "use_sample_memory": False, "sample_count_per_job": 1}, "runtime_parallel_workers": command.get("parallel_workers"), "runtime_qualification_workers": command.get("qualification_parallel_workers"), "qualification_dispatch_widths": [wave["max_workers"] for wave in training.get("qualification_wave_reports", [])], "logical_lane_count": training["binding"]["lane_count"], "dispatch_widths": [item["max_workers"] for item in training["dispatch_reports"]], "wall_seconds": command["wall_seconds"], "wall_seconds_per_span": command["wall_seconds"] / args.expected_rows, "resource_record": resource["record"], "cpu_envelope_audit": cpu_envelope_audit, "qualification_wave_audit": qualification_wave_audit, "counts": {"jobs": len(rows), "qualified": sum(row["qualified"] for row in rows.values()), "accepted_epochs": sum(row["accepted_epochs"] for row in rows.values()), "lake_builds_verified": len(proofs), "family_artifacts_reparsed": formula_count}, "rows": rows, "proofs": proofs, "scope": "Synthetic fixtures; repeated tuning validation is not an independent canary. Audit replays local checkpoints, parses family projections, and verifies existing source-locked numeric Lake receipts; no new training or Lake execution and no federal-corpus formalization.", "admitted": False, "formalized": False, "constitution_formalized": False}



def audit_owned_source_changes(path, before, after, audit):
    """Permit only an explicit hash-bound delta in this turn's owned sources."""
    approval = read(path)
    allowed = {
        "optimizers/logic_theorem_optimizer/autoencoder_capacity.py",
        "optimizers/logic_theorem_optimizer/autoencoder_qualified_training.py",
        "optimizers/logic_theorem_optimizer/autoencoder_qualification_pool.py",
        "optimizers/logic_theorem_optimizer/modal_autoencoder.py",
    }
    maps = []
    for side, receipt in (("before", before), ("after", after)):
        reference = approval.get(side + "_package_mapping", {})
        observed = descriptor(reference["path"])
        audit.check(observed == reference, "owned_source_delta:" + side + ":map_artifact_seal")
        mapping = read(reference["path"])
        manifest = {"sha256": digest(mapping), "file_count": len(mapping)}
        audit.check(manifest == receipt["producer_manifest"],
                    "owned_source_delta:" + side + ":complete_producer_binding")
        maps.append(mapping)
    left, right = maps
    changes = {name: {"before": left.get(name), "after": right.get(name)}
               for name in sorted(set(left) | set(right)) if left.get(name) != right.get(name)}
    audit.check(approval.get("schema") == "native-optimizer-owned-source-changes/v1"
                and approval.get("allowed_core_roles") == ["autoencoder"],
                "owned_source_delta:explicit_schema_and_core_scope")
    audit.check(bool(changes) and set(changes).issubset(allowed)
                and changes == approval.get("changes"),
                "owned_source_delta:exact_owned_allowlist_no_external_drift")
    core_left, core_right = before["core_sources"], after["core_sources"]
    audit.check({name: value for name, value in core_left.items() if name != "autoencoder"}
                == {name: value for name, value in core_right.items() if name != "autoencoder"},
                "owned_source_delta:all_other_core_roles_unchanged")
    autoencoder_path = "optimizers/logic_theorem_optimizer/modal_autoencoder.py"
    audit.check(core_left.get("autoencoder") == left.get(autoencoder_path)
                and core_right.get("autoencoder") == right.get(autoencoder_path),
                "owned_source_delta:exact_autoencoder_core_bindings")
    return {"approval": descriptor(path), "changes": changes,
            "scope": "Exactly the listed owned package changes; every other Python path and all other core roles must remain identical."}


def compare(args):
    audit = Audit()
    before, after = read(args.before), read(args.after)
    audit.check(before["passed"] and after["passed"], "both_run_audits_passed")
    if args.require_same_producer:
        audit.check(before["producer_manifest"] == after["producer_manifest"], "same_complete_producer_manifest")
    owned_source_changes = None
    if args.allowed_source_changes:
        audit.check(not args.external_producer_drift_audit and not args.require_same_producer,
                    "owned_source_delta:no_conflicting_source_comparison_policy")
        owned_source_changes = audit_owned_source_changes(args.allowed_source_changes, before, after, audit)
    external_drift = None
    if args.external_producer_drift_audit:
        drift = read(args.external_producer_drift_audit)
        audit.check(drift.get("reconstruction_verified") is True
                    and drift.get("baseline_manifest") == before["producer_manifest"]
                    and drift.get("optimized_manifest") == after["producer_manifest"],
                    "external_producer_drift_exact_run_bindings")
        external_drift = {"audit": descriptor(args.external_producer_drift_audit),
                          "changes": drift.get("baseline_to_optimized_external_changes", {})}
        audit.check(bool(external_drift["changes"]), "external_producer_drift_explicit_changes")
    transport = bool(args.allow_shared_target_transport)
    for field in ("core_sources", "input_sha256", "validation_sha256"):
        if field == "core_sources" and owned_source_changes is not None:
            continue
        audit.check(before[field] == after[field], "same_" + field)
    if transport:
        left, right = before["configuration"], after["configuration"]
        audit.check(left["shared_targets"] is False and right["shared_targets"] is True,
                    "explicit_cold_to_verified_shared_transport")
        audit.check({k: v for k, v in left.items() if k != "shared_targets"}
                    == {k: v for k, v in right.items() if k != "shared_targets"}, "same_nontransport_configuration")
        audit.check(before["logical_lane_count"] == after["logical_lane_count"], "same_logical_lane_count")
        # The immutable policy includes shared-target provenance, hence placement
        # hashes change. Distinct lanes and identical exact parents below ensure
        # placement cannot hide a different update chain in this fixture census.
        for label, value in (("before", before), ("after", after)):
            lanes = [row["lane"] for row in value["rows"].values()]
            audit.check(len(lanes) == len(set(lanes)) and all(type(lane) is int and 0 <= lane < value["logical_lane_count"] for lane in lanes), label + ":distinct_valid_lanes")
    else:
        audit.check(before["configuration"] == after["configuration"], "same_configuration")
    audit.check(set(before["rows"]) == set(after["rows"]), "same_sample_identities")
    parity_fields = ("samples", "validation_samples", "lane", "training_config", "model_config", "base", "base_identity", "candidate", "candidate_identity", "chain_depth", "accepted_epochs", "selected_updates", "training_metrics_sha256", "qualified", "status", "gates", "qualification_rows")
    for key in sorted(set(before["rows"]) & set(after["rows"])):
        for field in parity_fields:
            if transport and field == "lane":
                continue
            audit.check(before["rows"][key][field] == after["rows"][key][field], key + ":same_" + field)
    result = audit.result()
    row_checks = [item for item in audit.checks if ":same_" in item["name"]]
    row_equality = {"passed": all(item["passed"] for item in row_checks),
                    "check_count": len(row_checks),
                    "failures": [item["name"] for item in row_checks if not item["passed"]],
                    "scope": "Per-row exact equality only; cannot override failed native audit prerequisites."}
    prerequisites = {"passed": before["passed"] and after["passed"],
                     "before_failures": before.get("failures", []), "after_failures": after.get("failures", [])}
    return {"schema": "native-optimizer-speed-parity-audit/v1", "row_equality": row_equality, "prerequisite_run_audits": prerequisites, **result, "before_audit": descriptor(args.before), "after_audit": descriptor(args.after), "baseline_wall_seconds": before["wall_seconds"], "optimized_wall_seconds": after["wall_seconds"], "wall_seconds_saved": before["wall_seconds"] - after["wall_seconds"], "wall_time_ratio": after["wall_seconds"] / before["wall_seconds"], "speed_claim_eligible": result["passed"] and not transport and external_drift is None, "external_producer_drift": external_drift, "owned_source_changes": owned_source_changes, "isolated_causal_speed_claim_eligible": result["passed"] and not transport and external_drift is None, "consumer_comparison_eligible": result["passed"], "expected_transport_differences": ({"shared_targets": [False, True], "lane_indices": {key: [before["rows"][key]["lane"], after["rows"][key]["lane"]] for key in sorted(set(before["rows"]) & set(after["rows"]))}, "reason": "Shared target artifact identity is bound to immutable policy and therefore changes placement; exact parents and all candidate/gate checks are retained."} if transport else None), "scope": ("Exact result parity and standalone wall times are retained, but four concurrent external source changes prevent attribution of elapsed differences solely to the intended optimization." if external_drift is not None else "Consumer-only cold-to-verified-shared-target comparison; source core, model settings, samples, exact parents, candidate weights, metrics and gates must match. Target production cost is excluded from these consumer walls, so this is not an end-to-end speed claim." if transport else "Sequential unprofiled native routes with the same complete package producer manifest, model settings, samples, exact parents, candidate weights, metrics and qualification gates. This single matched pair compares runtime concurrency; cProfile observations are excluded and repeated-run variance is not established." if args.require_same_producer else "Sequential unprofiled native routes with identical model settings, source core, samples, candidates and gates. Full producer and orchestration bindings differ for the explicitly compared scheduling/accounting implementation; cProfile observations are excluded."), "admitted": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_subparsers(dest="mode", required=True)
    run = modes.add_parser("run")
    for name in ("run", "binding", "command", "input", "validation", "output"):
        run.add_argument("--" + name, type=Path, required=True)
    run.add_argument("--expected-rows", type=int, default=4)
    run.add_argument("--refinement", type=int, choices=range(4), default=0)
    run.add_argument("--shared-targets", action="store_true")
    run.add_argument("--expect-finalization", action="store_true")
    run.add_argument("--expect-owner-cpu", action="store_true")
    run.add_argument("--expect-training-first-refinement", action="store_true")
    run.add_argument("--expect-qualification-waves", action="store_true")
    pair = modes.add_parser("compare")
    pair.add_argument("--allow-shared-target-transport", action="store_true")
    pair.add_argument("--require-same-producer", action="store_true")
    pair.add_argument("--external-producer-drift-audit", type=Path)
    pair.add_argument("--allowed-source-changes", type=Path)
    for name in ("before", "after", "output"):
        pair.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    result = audit_run(args) if args.mode == "run" else compare(args)
    write(args.output, result)
    print(json.dumps({key: result[key] for key in ("passed", "check_count", "failures")}, sort_keys=True))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
