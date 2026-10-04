#!/usr/bin/env python3
"""Replay predeclared learned samples and run actual native modality Lake checks.

The sampling plan must predate the completed comparison. Incorrect predictions
remain attempts; source references never repair a candidate. All forty families
remain in the inventory, and builds grant no source fidelity or qualification.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import resource
import sys
import time
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[3]
BENCHMARK = Path(__file__).with_name("benchmark_intent_ui_candidate_coverage.py")
TOOLS = {
    "lake": ("/home/barberb/.elan/toolchains/leanprover--lean4---v4.30.0/bin/lake",
             "8c987aee79f105bc2ff21772b958b219c8921a51b8ca2df8af410a2b17bd8701"),
    "java": ("/home/barberb/.local/share/ipfs_datasets_py/theorem-provers/advisors/temurin-jdk/17.0.20+8/jdk/bin/java",
             "0cd543f9949605b5eccb1d2b98c2b8637bb0953f0b5087208393b4b7ded73c1a"),
    "tla2tools": ("/home/barberb/.local/share/ipfs_datasets_py/theorem-provers/tlc/1.8.0/tla2tools.jar",
                  "e22f8ffb4bacdea0a871f444dd94fe5fb0d8013b3388ae39e82e26f852c735d5"),
}
FALSE = dict(qualified=False, admitted=False, formalized=False, proof_authority=False,
    source_semantics_verified=False, production_promotion_performed=False,
    weights_modified=False, prediction_repaired=False, gold_source_replaced=False,
    training_executed=False, external_solver_diagnostics_executed=False)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def raw(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(raw(value) + b"\n")


def source_manifest():
    paths = [path for path in (ROOT / "ipfs_datasets_py").rglob("*")
        if path.is_file() and not {"__pycache__", ".git", ".pytest_cache"}.intersection(path.parts)
        and path.suffix not in (".pyc", ".pyo")]
    paths += [Path(__file__).resolve(), BENCHMARK,
        BENCHMARK.with_name("benchmark_source384_fidelity.py"),
        ROOT / "tests/fixtures/logic/intent_ui_source_compositions_v1/panel.py"]
    return [{"path": str(path.relative_to(ROOT)), "sha256": sha(path), "bytes": path.stat().st_size}
            for path in sorted(set(paths))]


def selected_indices(domain, rows, plan):
    field, labels = (("modality", plan["expected_modalities"]) if domain == "intent_ir" else
                     ("privacy_sensitivity", plan["expected_privacy"]))
    require(len(rows) == 24 and len({row["id"] for row in rows}) == 24, "complete unique 24-row test panel required")
    require({row["target"]["document"][field] for row in rows} == set(labels), "predeclared label inventory differs")
    indices = [0]
    for label in labels:
        index = next(index for index, row in enumerate(rows) if row["target"]["document"][field] == label)
        if index not in indices:
            indices.append(index)
    return indices


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--comparison", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--sampling-plan", type=Path, required=True)
    args = parser.parse_args()
    comparison, output, sampling_path = args.comparison.resolve(), args.output.resolve(), args.sampling_plan.resolve()
    summary_path = comparison / "summary.json"
    # No model, reference, or held-out output is read before this check.
    require(summary_path.is_file(), "comparison summary absent: held-out outputs remain sealed")
    require(not output.exists(), "use a new output directory; native evidence is immutable")
    require(sampling_path.is_file() and sampling_path.stat().st_mtime < summary_path.stat().st_mtime,
            "sampling plan must predate the completed summary")
    sys.dont_write_bytecode = True
    os.environ.update(PYTHONDONTWRITEBYTECODE="1", HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1",
        HF_DATASETS_OFFLINE="1", IPFS_DATASETS_PY_LAZY_INSTALL_ERGOAI="0", CUDA_VISIBLE_DEVICES="",
        OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1")
    sys.path.insert(0, str(ROOT))
    observed_files = {}

    def pin(path, expected=None):
        path = Path(path).resolve()
        digest = sha(path)
        require(expected is None or digest == expected, "file digest differs: " + str(path))
        require(str(path) not in observed_files or observed_files[str(path)] == digest, "file changed between reads")
        observed_files[str(path)] = digest
        return digest

    def read(path):
        pin(path)
        return json.loads(Path(path).read_bytes())

    sampling, summary = read(sampling_path), read(summary_path)
    require(sampling["schema"] == "intent-ui-native-followup-plan/v1"
        and sampling["comparison_summary_present_when_declared"] is False
        and sampling["created_unix_seconds"] < summary_path.stat().st_mtime,
        "predeclared sampling provenance required")
    require(sampling["expected_modalities"] == ["required", "permitted", "prohibited"]
        and sampling["expected_privacy"] == ["none", "low", "high"], "sampling labels differ")
    require(all(sampling[key] is False for key in ("prediction_repair", "gold_source_replacement", "qualification_granted"))
        and sampling["inference_replayed"] is True, "unrepaired replay plan required")
    require((sampling["workers"], sampling["memory_mb_per_native_job"], sampling["cpu_slots_per_native_job"],
        sampling["child_process_slots_per_native_job"], sampling["timeout_seconds_per_native_step"]) == (2, 1024, 2, 2, 60),
        "native resource plan differs")
    require(all(summary[key] is True for key in ("source_unchanged", "parent_unchanged", "assets_unchanged",
        "inputs_unchanged", "frozen_artifacts_unchanged")) and summary["actual_fit_count"] == 6,
        "completed immutable six-fit comparison required")
    plan, freeze = read(comparison / "plan.json"), read(comparison / "freeze.json")
    pin(comparison / "plan.json", freeze["plan_sha256"])
    pin(comparison / "source-manifest.json", freeze["source_manifest_sha256"])
    original_pins = read(comparison / "source-manifest.json")["files"]
    for record in original_pins:
        path = (ROOT / record["path"]).resolve()
        require(path.is_relative_to(ROOT), "source manifest path escaped canonical source")
        pin(path, record["sha256"])
    for relative, digest in freeze["pre_exposure_artifact_sha256"].items():
        path = (comparison / relative).resolve()
        require(path.is_relative_to(comparison), "frozen artifact path escaped comparison")
        pin(path, digest)
    for descriptor in read(comparison / "input-hashes.json").values():
        pin(descriptor["path"], descriptor["sha256"])
    pin(plan["parent"]["path"], plan["parent"]["sha256"])
    for path, digest in TOOLS.values():
        pin(path, digest)
    fits = freeze["fits"]
    expected_fits = {(domain, strategy, seed) for domain in ("intent_ir", "ui_ux_ir")
        for strategy, seed in (("v1", 3517), ("v1", 3518), ("ridge", None))}
    require(len(fits) == 6 and {(fit["domain"], fit["strategy"], fit["seed"]) for fit in fits} == expected_fits,
            "exact six predeclared fits required")
    require(plan["config_v1"]["batch_size"] == 16, "recorded replay batch size differs")
    current_pins = source_manifest()
    output.mkdir(parents=True)
    save(output / "source-manifest.json", {"root": str(ROOT), "files": current_pins,
        "benchmark_original_files_verified": len(original_pins),
        "additions": sorted({row["path"] for row in current_pins} - {row["path"] for row in original_pins})})
    started = time.perf_counter()
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_embedding_runtime as offline
    with offline._offline_guard():
        import torch
        torch.set_num_threads(1)
        from ipfs_datasets_py.logic.autoformal.tree_pin import require_workspace_logic_tree
        from ipfs_datasets_py.logic.formalization.autoencoder import family_training as core
        from ipfs_datasets_py.logic.formalization.autoencoder import family_training_v7 as training
        from ipfs_datasets_py.logic.formalization.autoencoder import intent_candidate_fidelity as intent
        from ipfs_datasets_py.logic.formalization.autoencoder import intent_ui_candidate_pipeline as pipeline
        from ipfs_datasets_py.logic.formalization.autoencoder import ui_source_contract_384_v2 as ui
        from ipfs_datasets_py.logic.formalization.autoencoder import structured_source_384 as structured
        from ipfs_datasets_py.logic.formalization.autoencoder import native_family_lake_v5 as native_lake
        from ipfs_datasets_py.logic.formalization.autoencoder.parallel_projection_checks import NativeProjectionJob, run_parallel_projection_checks
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer import domain_384_batched_inference as batched
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer import domain_384_autoencoder as native
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer import domain_384_fidelity as fidelity
        loaded_tree = require_workspace_logic_tree()
        spec = importlib.util.spec_from_file_location("_native_followup_benchmark", BENCHMARK)
        benchmark = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(benchmark)
        data = {domain: read(comparison / domain / "test.json") for domain in ("intent_ir", "ui_ux_ir")}
        selection = {domain: selected_indices(domain, rows, sampling) for domain, rows in data.items()}
        save(output / "plan.json", {"sampling_plan": sampling, "sampling_plan_sha256": sha(sampling_path),
            "comparison_summary_sha256": sha(summary_path), "source": str(ROOT), "logic_tree_pin": loaded_tree,
            "selected_indices": selection, "tools": TOOLS, "script_sha256": sha(Path(__file__)),
            "scope": "native candidate interpretation contracts; no source truth or complete-modality qualification",
            "replay_scope": "all24 test rows per fit in original order; v1 batch16; references excluded", **FALSE})
        attempts, jobs, pipeline_observations = [], [], []
        for fit in fits:
            domain, strategy, descriptor = fit["domain"], fit["strategy"], fit["checkpoint"]
            fit_dir = (comparison / fit["directory"]).resolve()
            require(fit_dir.is_relative_to(comparison), "fit directory escaped comparison")
            pin(descriptor["path"], descriptor["sha256"])
            recorded = read(fit_dir / "test-conditioned-inference.json")
            rows = data[domain]
            runtime = (batched.load_checkpoint(descriptor["path"], expected_sha256=descriptor["sha256"],
                expected_domain=domain, batch_size=16) if strategy == "v1" else
                structured.load_checkpoint(descriptor["path"], expected_sha256=descriptor["sha256"], expected_domain=domain))
            replay = benchmark.readout(runtime, strategy, benchmark.inputs_only(rows), native, fidelity)
            require(len(replay["rows"]) == len(recorded["rows"]) == 24, "replay omitted test rows")
            deltas = []
            for source_row, actual, old in zip(rows, replay["rows"], recorded["rows"]):
                require(actual["id"] == source_row["id"], "replay source identity differs")
                for key in ("id", "source_sha256", "candidate_ir", "raw_candidate_ir", "generated_tokens", "ended"):
                    require(actual[key] == old[key], "unchanged replay differs: " + fit["directory"] + ":" + key)
                require(actual["target_access"] is False and actual["teacher_forcing"] is False
                    and old["target_access"] is False and old["teacher_forcing"] is False, "target-free replay required")
                left, right = actual["reconstructed_embedding"], old["reconstructed_embedding"]
                require(len(left) == len(right) == 384, "replay embedding dimension differs")
                delta = max(abs(a-b) for a, b in zip(left, right))
                require(math.isfinite(delta) and delta <= 1e-6, "replay reconstructed embedding differs")
                deltas.append(delta)
            save(output / "replays" / (fit["directory"].replace("/", "-") + ".json"), replay)
            # Execute the real reader again through the public additive pipeline.
            # The adapter performs the same emitted-class serialization/common
            # gate as the benchmark; it never supplies cached predictions or gold.
            def read_for_audit(inference_rows):
                return benchmark.readout(runtime, strategy, inference_rows, native, fidelity)
            audited = pipeline.infer_and_audit(SimpleNamespace(infer=read_for_audit), benchmark.inputs_only(rows))
            require(len(audited["rows"]) == 24, "public candidate pipeline omitted rows")
            for actual, expected in zip(audited["rows"], replay["rows"]):
                for key in ("id", "source_sha256", "candidate_ir", "raw_candidate_ir", "generated_tokens", "ended"):
                    require(actual[key] == expected[key], "public pipeline changed reader output: " + key)
                require(len(actual["reconstructed_embedding"]) == 384 and
                    max(abs(a-b) for a, b in zip(actual["reconstructed_embedding"], expected["reconstructed_embedding"])) <= 1e-6,
                    "public pipeline reconstruction differs")
            save(output / "pipeline" / (fit["directory"].replace("/", "-") + ".json"), audited)
            pipeline_observations.append({"domain": domain, "strategy": strategy, "seed": fit["seed"],
                "row_count": 24, "dispositions": audited["candidate_audit_dispositions"],
                "actual_runtime_executed_again": True, "targets_passed_to_pipeline": False,
                "readout_adapter": "same_benchmark_public_readout_serialization_and_common_native_gate",
                "outputs_unchanged": True, **FALSE})
            for index in selection[domain]:
                source_row, prediction = rows[index], replay["rows"][index]
                identity = fit["directory"].replace("/", "-") + f"-test-{index:03d}"
                catalog = core.family_training_catalog(domain)
                packet = {"attempt_id": identity, "domain": domain, "strategy": strategy, "seed": fit["seed"],
                    "split": "test", "row_index": index, "row_id": source_row["id"], "checkpoint": descriptor,
                    "source_text": source_row["source_text"], "reference_target": source_row["target"],
                    "recorded_prediction": recorded["rows"][index], "replayed_prediction": prediction,
                    "pipeline_candidate_audit": audited["rows"][index]["candidate_audit"],
                    "replay_all24_matches": True, "replay_embedding_max_abs_delta": deltas[index],
                    "reference_fidelity": fidelity.evaluate_generated(source_row["target"], prediction["generated_tokens"],
                        ended=prediction["ended"], domain_id=domain),
                    "family_catalog": catalog, "status": "not_prepared", **FALSE}
                attempts.append(packet)
                try:
                    candidate = prediction["candidate_ir"]
                    if domain == "intent_ir":
                        audit = intent.audit_intent_candidate(source_row["source_text"], prediction["raw_candidate_ir"])
                        packet["source_audit"] = audit
                        require(audit["status"] == "source_agreement" and candidate is not None,
                                "original learned Intent candidate failed strict source agreement: " + audit["status"])
                        inputs = {"document": candidate["document"], "source_text": source_row["source_text"]}
                        report = training.prepare_family_training_targets_v7(domain, **inputs)
                    else:
                        prepared = ui.prepare_family_targets(source_row["source_text"], candidate)
                        ui.validate_prepared(prepared, source_row["source_text"], candidate)
                        require(prepared["report"] == audited["rows"][index]["candidate_audit"]["report"]
                            and prepared["audit"] == audited["rows"][index]["candidate_audit"]["audit"],
                            "selected UI preparation differs from public pipeline")
                        packet["source_audit"] = prepared["audit"]
                        report, inputs = prepared["report"], prepared["source_inputs"]
                    require(len(report["family_inventory"]) == len(report["requested_families"]) == 40,
                            "all40 requested-family inventory required")
                    packet.update(family_report=report, source_inputs=core._json(inputs))
                    packet["native_preflight"] = native_lake.prepare_native_family_lean(report, source_inputs=inputs)
                    packet["status"] = "prepared"
                    jobs.append(NativeProjectionJob(identity, report, inputs))
                except Exception as error:
                    packet.update(status="blocked_before_lake", error_type=type(error).__name__, reason=str(error)[:2000])
                save(output / identity / "candidate-and-preparation.json", packet)
                print(identity, packet["status"], packet.get("reason", ""), flush=True)
            del runtime
        if jobs:
            try:
                built = run_parallel_projection_checks(jobs, max_workers=2, native_memory_mb=1024,
                    native_cpu_slots=2, native_child_process_slots=2, native_step_timeout_seconds=60,
                    lake_executable=TOOLS["lake"][0], java_executable=TOOLS["java"][0],
                    tla2tools_jar=TOOLS["tla2tools"][0], output_directory=output / "native-builds")
                by_id = {row["job_id"]: row["receipt"] for row in built["jobs"]}
                save(output / "parallel-receipt.json", built["receipt"])
            except Exception as error:
                by_id = {job.job_id: {"status": "batch_preflight_or_scheduler_blocked",
                    "error_type": type(error).__name__, "reason": str(error)[:2000], **FALSE} for job in jobs}
            for packet in attempts:
                if packet["attempt_id"] in by_id:
                    packet["native_check"] = by_id[packet["attempt_id"]]
        observations = []
        for packet in attempts:
            save(output / packet["attempt_id"] / "result.json", packet)
            checked = packet.get("native_check", {}).get("native", {})
            audit = packet.get("source_audit", {})
            observations.append({"attempt_id": packet["attempt_id"], "domain": packet["domain"],
                "strategy": packet["strategy"], "seed": packet["seed"], "row_id": packet["row_id"],
                "row_index": packet["row_index"], "preparation_status": packet["status"], "reason": packet.get("reason"),
                "reference_exact": packet["reference_fidelity"]["exact"], "source_audit_status": audit.get("status"),
                "native_status": checked.get("status", "not_run"),
                "actual_lake_status": checked.get("execution", {}).get("status", "not_run"),
                "actual_lake_command": checked.get("execution", {}).get("command"),
                "per_projection": checked.get("per_projection", packet.get("native_preflight", {}).get("per_projection", [])),
                "all_requested_projections_passed": checked.get("all_requested_projections_passed", False),
                "missing_requested_families": checked.get("missing_requested_families",
                    packet.get("native_preflight", {}).get("missing_requested_families",
                        [row["family_id"] for row in packet["family_catalog"]["family_inventory"]])),
                "unprojected_facets": audit.get("unprojected_facets", []), **FALSE})
        require(source_manifest() == current_pins, "validation source changed during checks")
        require(all(sha(Path(path)) == digest for path, digest in observed_files.items()), "input/checkpoint/tool changed during checks")
        loaded = {name: {"path": str(Path(module.__file__).resolve()), "sha256": sha(module.__file__)}
            for name, module in tuple(sys.modules.items()) if name.startswith("ipfs_datasets_py") and getattr(module, "__file__", None)}
        require(all(Path(row["path"]).is_relative_to(ROOT) for row in loaded.values()), "loaded module outside canonical validation source")
        save(output / "loaded-modules.json", loaded)
        save(output / "input-provenance.json", {"files": observed_files, "all_inputs_unchanged": True})
        save(output / "summary.json", {"schema": "intent-ui-candidate-native-followup/v1",
            "sampling_plan_sha256": sha(sampling_path), "selected_indices": selection, "attempts": observations,
            "public_pipeline_runs": pipeline_observations,
            "attempt_count": len(attempts), "prepared_native_job_count": len(jobs),
            "elapsed_seconds": time.perf_counter()-started,
            "max_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            "rss_scope": "Python process only; excludes native child RSS",
            "all_source_and_input_files_unchanged": True, "no_success_filtering": True, **FALSE})
        print(json.dumps(observations, indent=2), flush=True)


if __name__ == "__main__":
    main()
