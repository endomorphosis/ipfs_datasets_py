"""Independent receipt/replay audit; runs only after both native commands exit."""
from pathlib import Path
import gc
import hashlib
import json
import sys

ROOT = Path.cwd().resolve()
BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from ipfs_datasets_py.logic.autoformal.family_qualification import REQUIRED_FAMILIES, validate_family_artifact
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder_sparse_checkpoint import resolve_checkpoint


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def digest(value):
    return sha(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode())


def read(path):
    return json.loads(Path(path).read_bytes())


checks = []


def check(condition, name, detail=None):
    checks.append({"name": name, "passed": bool(condition), **({"detail": detail} if not condition else {})})


def verify_artifact(path, reference, label):
    raw = Path(path).read_bytes()
    check(len(raw) == reference["bytes"] and sha(raw) == reference["sha256"], label)
    return raw


def cas(root, reference):
    return root / "artifacts" / reference["sha256"][:2] / reference["sha256"]


def main():
    commands = read(BASE / "executed-commands.json")
    check(all(row["returncode"] == 0 and row["source_unchanged"] for row in commands["runs"]), "both_native_commands_completed_without_source_drift")
    binding = read(BASE / "native-binding.json")
    check(sha((BASE / "input.jsonl").read_bytes()) == binding["input_sha256"], "input_binding")
    check(sha((BASE / "validation.jsonl").read_bytes()) == binding["validation_sha256"], "validation_binding")
    lane_by_text = {sample["text"]: int(lane) for lane, samples in binding["selected_lane_samples"].items() for sample in samples}
    modes = {}
    for mode in ("fresh", "reused"):
        root = BASE / mode
        paths = list((root / "cycles").glob("*/cycle.json"))
        check(len(paths) == 1, mode + ":one_completed_cycle")
        cycle = read(paths[0])
        training = cycle["training"]
        check(cycle["temperature"] == 0 and cycle["execution_path"] == "training", mode + ":execution_route")
        check(training["binding"]["policy"]["native_producer_manifest"] == binding["producer_manifest"], mode + ":persistent_producer_binding")
        check(training["native_cycle_manifest"] == binding["producer_manifest"], mode + ":cycle_producer_binding")
        check(not training["blocked"] and not training["pending_batch_count"] and len(training["completed"]) == 4, mode + ":four_terminal_attempts")
        check(all(not report["failed"] and report["execution_mode"] == "native_training" for report in training["dispatch_reports"]), mode + ":native_dispatches")
        check(all(report["weight_control"]["transport"] == "native_scoped_quack_prototype" and report["weight_control"]["database_writer_count"] == 1 for report in training["dispatch_reports"]), mode + ":real_quack_single_owner")
        summaries, builds = {}, []
        for completed in training["completed"]:
            run_id = completed["run_id"]
            label = mode + ":" + run_id
            job = read(root / "progress" / (run_id + ".json"))
            text = job["samples"][0]["text"]
            sample_key = digest(job["samples"])
            check(completed["lane_index"] == lane_by_text[text], label + ":lane_assignment")
            wr = completed["optimizer"]["result"]["worker_receipt_artifact"]
            worker_raw = verify_artifact(cas(root, wr), wr, label + ":worker_cas_seal")
            worker = json.loads(worker_raw)
            check(worker_raw == (Path(job["output_directory"]) / "receipt.json").read_bytes(), label + ":persisted_worker_receipt")
            check(worker["job_spec"] == job and worker["job_spec_canonical_sha256"] == digest(job), label + ":job_binding")
            check(worker["execution_mode"] == "native_training" and worker["execution_gate_applied"] is True, label + ":native_training_gate")
            check(worker["tree_file_sha256"] == binding["core_sources"], label + ":training_core_sources")
            check(worker["legal_ir_evaluate_provers"] is False and worker["metric_disk_cache"] == 0 and worker["use_sample_memory"] is False and worker["legal_ir_parallel_workers"] == 1, label + ":training_measurement_flags")
            check(worker["sample_count"] == 1 and worker["training_report"]["before"]["legal_ir_target_count"] == worker["training_report"]["after"]["legal_ir_target_count"] == 1, label + ":nonempty_bridge_targets")
            check(worker["process_cache_initially_empty"] is True, label + ":job_target_cache_empty")
            pool = worker["runtime"]["native_pool"]
            check(pool is None if mode == "fresh" else pool["producer_manifest"] == binding["producer_manifest"], label + ":pool_provenance")
            qr = completed["qualification_artifact"]
            qualification = json.loads(verify_artifact(cas(root, qr), qr, label + ":qualification_cas_seal"))
            check(qualification["candidate_version_id"] == completed["optimizer"]["candidate_version_id"], label + ":qualification_candidate")
            check(qualification["execution_path"] == "inference" and qualification["execution_gate_applied"] is True and qualification["training_executed"] is False, label + ":immutable_inference_gate")
            check(qualification["sample_set_sha256"] == digest({"training": job["samples"], "heldout": training["binding"]["policy"]["qualification_samples"]}), label + ":qualification_samples")
            for role, source_path in qualification["source_files"].items():
                check(sha(Path(source_path).read_bytes()) == qualification["source_sha256"][role], label + ":source:" + role)
            allowed = {reference["sha256"]: reference for reference in qualification["checkpoint_artifacts"]}

            def resolver(reference):
                check(allowed.get(reference["sha256"]) == reference, label + ":replay_artifact_allowed")
                return cas(root, reference)

            resolved = resolve_checkpoint(qualification["candidate_artifact"], resolver=resolver, reset_revision=False)
            check(dict(resolved.materialized_checkpoint) == worker["candidate_materialized_checkpoint"] == qualification["materialized_checkpoint"], label + ":independent_materialized_sha_replay")
            check(resolved.state.state_identity_record().to_dict() == worker["candidate_state_identity"], label + ":independent_complete_state_identity")
            check({item["sha256"] for item in resolved.artifacts} == set(allowed), label + ":closure_complete_no_orphans")
            replay_depth = resolved.depth
            del resolved
            gc.collect()
            row_summaries = []
            for row in qualification["rows"]:
                row_label = label + ":" + row["split"]
                check(sha(row["source"]["text"].encode()) == row["source_sha256"], row_label + ":source_text_binding")
                check(row["semantic_gate"]["passed"] and row["compiler"]["compiler_status"] == "compiled", row_label + ":typed_compile_roundtrip")
                family_summaries = []
                for fragment in row["family_syntax_gate"]["rows"]:
                    check(set(fragment["families"]) == set(REQUIRED_FAMILIES) and fragment["passed"], row_label + ":all_six_families")
                    check(fragment["source_sha256"] == row["source_sha256"] and fragment["rule_sha256"] == digest(fragment["canonical_rule"]), row_label + ":canonical_rule_binding")
                    families = {}
                    for name, artifact in fragment["families"].items():
                        check(artifact["passed"] and artifact["syntax_valid"] and artifact["source_bound"] and artifact["source_sha256"] == row["source_sha256"] and artifact["rule_sha256"] == fragment["rule_sha256"], row_label + ":family_bound:" + name)
                        check(sha(artifact["formula"].encode()) == artifact["formula_sha256"] and artifact["formula"] == artifact["export_record"]["exported_formula"], row_label + ":formula_hash:" + name)
                        parsed = validate_family_artifact(name, artifact["formula"])
                        check(parsed["passed"] and parsed["syntax_valid"] and parsed["consumed_all_input"], row_label + ":independent_syntax_parse:" + name)
                        families[name] = {key: artifact[key] for key in ("formula_sha256", "rule_sha256", "representation_coverage", "source_sha256")}
                    family_summaries.append(families)
                lean_summaries = []
                for proof in row["lake_gate"]["rows"]:
                    raw = Path(proof["source_file"]).read_bytes()
                    log = verify_artifact(proof["log"]["path"], proof["log"], row_label + ":lake_log_hash")
                    check(proof["passed"] and proof["lake_ok"] and proof["command"] == ["lake", "build", "Legal"] and proof["returncode"] == 0 and b"Built Legal" in log and b"error:" not in log, row_label + ":actual_lake_receipt")
                    lock = proof["source_lock"]
                    check(proof["scope"] == "source_locked_numeric_pattern" and lock["ok"] and sha(raw) == proof["lean_source_sha256"] == lock["lock"]["candidate_source_sha256"] == lock["lock"]["expected_source_sha256"] and raw == lock["source"].encode(), row_label + ":lake_source_lock")
                    check(b"Mathlib" not in raw and b"sorry" not in raw and b"axiom" not in raw, row_label + ":lean_source_restrictions")
                    lean_summaries.append({key: proof[key] for key in ("lean_source_sha256", "pattern", "command", "returncode", "scope")})
                    builds.append({"sample_key": sample_key, "split": row["split"], "source": proof["source_file"], "source_sha256": sha(raw), "log": proof["log"]})
                row_summaries.append({"split": row["split"], "source": row["source"], "metric_gate": row["metric_gate"], "compiler": row["compiler"], "families": family_summaries, "lean": lean_summaries})
            metric_values = {phase: {key: value for key, value in worker["training_report"][phase].items() if key not in {"evaluation_profile", "legal_ir_target_hashes"}} for phase in ("before", "after")}
            summaries[sample_key] = {
                "source": text, "lane": completed["lane_index"], "base": worker["base_materialized_checkpoint"],
                "candidate": worker["candidate_materialized_checkpoint"], "base_identity": worker["base_state_identity"],
                "candidate_identity": worker["candidate_state_identity"], "chain_depth": replay_depth,
                "base_chain_depth": worker["base_checkpoint_chain_depth"], "accepted_epochs": worker["optimizer_accepted_epochs"],
                "epoch_updates": [{key: epoch.get(key) for key in ("selected_update", "accepted", "acceptance_source", "cosine_similarity_delta", "reconstruction_delta", "legal_ir_view_cross_entropy_delta", "line_search_attempt_count")} for epoch in worker["training_report"]["epoch_reports"]],
                "training_metrics_sha256": digest(metric_values), "training_metrics": {phase: {key: metric_values[phase][key] for key in ("embedding_cosine_similarity", "reconstruction_loss", "legal_ir_target_count", "legal_ir_losses", "legal_ir_view_family_metrics")} for phase in metric_values},
                "target_document_hashes": {phase: worker["training_report"][phase]["legal_ir_target_hashes"] for phase in ("before", "after")},
                "qualified": completed["qualified"], "qualification_status": completed["qualification_status"],
                "gates": qualification["gate_results"], "rows": row_summaries,
                "bridge_names": worker["bridge_names"], "runtime": worker["runtime"],
                "evidence": {"worker_receipt": wr, "qualification_receipt": qr},
            }
        check(len(builds) == 8, mode + ":eight_actual_lake_builds")
        for key, item in summaries.items():
            if item["base_chain_depth"] == 0:
                check(item["base"] == binding["checkpoint"], mode + ":initial_parent:" + key)
            else:
                parents = [parent for parent in summaries.values() if parent["candidate"] == item["base"] and parent["lane"] == item["lane"]]
                check(len(parents) == 1, mode + ":exact_lane_parent:" + key)
        modes[mode] = {"samples": summaries, "builds": builds, "batch_status_counts": training["batch_status_counts"], "wall_seconds": next(row["wall_seconds"] for row in commands["runs"] if row["label"] == mode)}
    check(set(modes["fresh"]["samples"]) == set(modes["reused"]["samples"]), "same_four_training_samples")
    ignored = {"runtime", "evidence", "target_document_hashes"}
    for key, fresh in modes["fresh"]["samples"].items():
        reused = modes["reused"]["samples"][key]
        for field in fresh.keys() - ignored:
            check(fresh[field] == reused[field], "fresh_reused_exact_parity:" + key + ":" + field)
    runtime = [row["runtime"] for row in modes["reused"]["samples"].values()]
    check(len({row["pid"] for row in runtime}) == 2 and sorted(row["native_pool"]["process_job_index"] for row in runtime) == [0, 0, 1, 1], "two_pids_reused_for_second_wave")
    result = {"schema": "independent-native-autoencoder-parity/v1", "passed": all(row["passed"] for row in checks), "checks": checks, "modes": modes,
              "scope": "four synthetic numeric fixtures and one repeated tuning-validation fixture; exact replay and receipt audit, no new Lake execution",
              "semantic_comparison_excludes": ["run/version/job IDs and artifact hashes containing those IDs", "runtime process/timing observations", "local evidence paths", "whole bridge-document target hashes, retained separately in each sample"],
              "bridge_document_hash_parity_established": all(modes["fresh"]["samples"][key]["target_document_hashes"] == modes["reused"]["samples"][key]["target_document_hashes"] for key in modes["fresh"]["samples"]),
              "bridge_document_hash_limit": "Whole bridge-document hashes differ. Numeric evaluation values, canonical six-family artifacts and reconstructed weights are compared independently; byte parity of complete native bridge document envelopes is not established.",
              "success_scope": "Six syntax projections and locked numeric Lean theorems do not establish full legal-rule or cognitive/event semantic equivalence.",
              "admitted": False, "formalized": False, "constitution_formalized": False}
    output = BASE / "native-parity.json"
    with output.open("x") as stream:
        json.dump(result, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps({"path": str(output), "passed": result["passed"], "checks": len(checks), "failed": [row for row in checks if not row["passed"]], "builds": sum(len(mode["builds"]) for mode in modes.values())}, sort_keys=True))


if __name__ == "__main__":
    main()
