#!/usr/bin/env python3
"""Exercise corpus gates, shared parallel proof resources and structural fitting.

These twelve authored native sources are integration fixtures. They do not
constitute a production corpus, a source decoder experiment, or a heldout test.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
DOMAINS = ("legal_ir", "intent_ir", "security_ir", "ui_ux_ir")


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def prepare_case(domain, index):
    from ipfs_datasets_py.logic.formalization.autoencoder import family_training_v7 as native
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import authored_legal_ui_qualifier_panel as legal_ui
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import authored_guarded_intent_panel as intent
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import authored_semantic_projection_panel as semantic
    if domain in legal_ui.DOMAINS:
        return legal_ui.prepare_case(domain, index)
    case = intent.prepare_case(index) if domain == "intent_ir" else semantic.prepare_case(domain, index)
    case["report"] = native.prepare_family_training_targets_v7(domain, **case["source_inputs"])
    return case


def reviews(report, domain, index):
    present = {row["logic_family"] for row in report["projections"]}
    return [{"family_id": row["family_id"], "source_digest": report["source_digest"],
        "disposition": "inapplicable",
        "reason": "Closed authored integration fixture supplies only its explicit native models, formulas and policies; this declaration cannot be applied to real corpus sources.",
        "evidence_refs": [f"urn:authored-readiness-parallel:v1:{domain}:{index}"]}
        for row in report["family_inventory"] if row["family_id"] not in present]


def run(output, *, lake, java_executable, tla2tools_jar, workers=2, epochs=12):
    from ipfs_datasets_py.logic.autoformal.tree_pin import require_workspace_logic_tree
    from ipfs_datasets_py.logic.formalization.autoencoder import parallel_projection_checks as parallel
    from ipfs_datasets_py.logic.formalization.autoencoder import training_readiness as readiness
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_family_training_validated_v5 as trainer
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import get_global_resource_scheduler

    if type(epochs) is not int or not 1 <= epochs <= 24:
        raise ValueError("smoke epochs must be between one and twenty-four")
    output = Path(output).absolute()
    output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    pin = require_workspace_logic_tree()
    scheduler = get_global_resource_scheduler()
    native_jobs, portfolio_jobs, cases = [], [], {}
    for domain in DOMAINS:
        for index in range(3):
            case = prepare_case(domain, index)
            report = case["report"]
            identity = f"{domain}-{index}"
            cases[identity] = case
            write(output / "inputs" / identity / "targets.json", report)
            write(output / "inputs" / identity / "fixture.json", case["fixture"])
            native_jobs.append(parallel.NativeProjectionJob(identity, report, case["source_inputs"],
                applicability_review=reviews(report, domain, index)))
            if index == 0:
                projection_id = domain + "/native_formula/propositional/v3"
                portfolio_jobs.append(parallel.PortfolioDiagnosticJob(
                    "portfolio-" + domain, identity, projection_id, solver_names=("z3", "cvc5")))

    checked = parallel.run_parallel_projection_checks(native_jobs, portfolio_jobs=portfolio_jobs,
        scheduler=scheduler, max_workers=workers, lake_executable=lake,
        output_directory=output / "parallel", java_executable=java_executable,
        tla2tools_jar=tla2tools_jar)
    write(output / "parallel-receipt.json", checked["receipt"])
    if not checked["receipt"]["all_jobs_completed"]:
        raise ValueError("parallel checks incomplete; retained receipt lists failed jobs")
    solver_attempts = 0
    for result in checked["portfolio_jobs"]:
        record = result["receipt"]["portfolio"]
        if record["denied"] or record["cancelled_attempt_ids"] or len(record["attempts"]) != 2:
            raise ValueError("both explicitly requested solvers must execute in this smoke")
        if {attempt["solver_name"] for attempt in record["attempts"]} != {"z3", "cvc5"}:
            raise ValueError("diagnostic solver identities changed")
        for attempt in record["attempts"]:
            if attempt["exit_code"] != 0 or attempt["verdict"] not in {"sat", "unsat"}:
                raise ValueError("supplemental propositional diagnostic did not finish conclusively")
            if not record["evidence"][attempt["attempt_id"]]["command"]:
                raise ValueError("missing actual solver command evidence")
            solver_attempts += 1
    if solver_attempts != 8:
        raise ValueError("all four domains require both diagnostic solver executions")
    # Job identities, not completion order, bind the observations to sources.
    results = {row["job_id"]: row for row in checked["jobs"]}
    if set(results) != set(cases):
        raise ValueError("parallel native results omit or duplicate source jobs")
    projection_checks = lake_builds = 0
    intervals = []
    for identity, result in results.items():
        receipt = result["receipt"]
        native = receipt["native"]
        expected = {row["projection_id"] for row in cases[identity]["report"]["projections"]}
        if {row["projection_id"] for row in native["per_projection"]} != expected:
            raise ValueError("native execution omitted a projection")
        if any(row["parser_status"] != "passed" or row["lake_status"] != "passed"
               for row in native["per_projection"]):
            raise ValueError("all emitted native projections must pass")
        if native["execution"]["returncode"] != 0 or native["execution"]["command"][-2:] != ["build", native["library"]]:
            raise ValueError("actual matching Lake build required")
        projection_checks += len(expected)
        lake_builds += 1
        intervals += [(receipt["started_offset_seconds"], 1), (receipt["finished_offset_seconds"], -1)]
    active = peak_native_jobs = 0
    for _, change in sorted(intervals):
        active += change
        peak_native_jobs = max(peak_native_jobs, active)
    summary = {}
    for domain in DOMAINS:
        rows = []
        for index in range(3):
            identity = f"{domain}-{index}"
            rows.append({"id": identity, "document_id": "authored-document:" + identity,
                "group_id": "authored-group:" + identity, "split": "train" if index < 2 else "validation",
                "source_inputs": cases[identity]["source_inputs"], "observation": results[identity]["observation"]})
        prepared = readiness.prepare_validated_projection_corpus(domain, rows)
        write(output / domain / "corpus-readiness.json", prepared.to_dict())
        trained = readiness.train_prepared_projection_corpus(prepared, output_dir=output / domain / "checkpoint",
            epochs=epochs, patience=epochs, latent_width=8, minibatch_size=2, max_seconds=60)
        inferred = trainer.infer_validated_family_projection_autoencoder(trained["descriptor"],
            [rows[-1]["observation"]])
        write(output / domain / "training.json", trained)
        write(output / domain / "tuning-inference.json", inferred)
        report = trained["report"]
        summary[domain] = {"optimizer_steps": report["optimizer_steps"],
            "selected_epoch": report["selected_epoch"], "training_gate_passed": report["training_gate_passed"],
            "before_tuning_objective": report["before"]["objective"],
            "selected_tuning_objective": report["after"]["objective"],
            "epoch_tuning_objectives": [row["validation_objective"] for row in report["history"]],
            "all_inference_projections_have_loss": inferred["loss_coverage"]["all_emitted_projections_have_loss"],
            "source_decoder_trained": False, "independent_holdout_evaluated": False,
            "training_rows": 2, "tuning_rows": 1}

    # Failure must occur before fitting; no saved JSON may reopen the live gate.
    identity = "legal_ir-0"
    live = results[identity]["observation"]
    detached = {"id": identity, "document_id": "detached", "group_id": "detached", "split": "train",
        "source_inputs": cases[identity]["source_inputs"], "observation": live.to_dict()}
    try:
        readiness.prepare_validated_projection_corpus("legal_ir", [detached])
    except (TypeError, ValueError):
        detached_rejected = True
    else:
        raise AssertionError("detached native receipt unexpectedly authorized a corpus")
    result = {"schema": "training-readiness-parallel-smoke/v1", "domains": summary,
        "source_tree": str(ROOT), "logic_tree_pin": pin,
        "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "parallel_receipt_sha256": hashlib.sha256((output / "parallel-receipt.json").read_bytes()).hexdigest(),
        "integration_passed": all(row["optimizer_steps"] == epochs and row["training_gate_passed"]
            and row["all_inference_projections_have_loss"] for row in summary.values()),
        "detached_receipt_rejected": detached_rejected,
        "actual_lake_builds": lake_builds, "emitted_projection_checks": projection_checks,
        "actual_solver_attempts": solver_attempts, "peak_overlapping_native_jobs": peak_native_jobs,
        "effective_workers": checked["receipt"]["effective_workers"],
        "wall_seconds": time.monotonic() - started,
        "scope": "authored native structural reconstruction with declared applicability; supplemental propositional solver diagnostics",
        "production_corpus_ready": False, "source_decoder_trained": False, "convergence_established": False,
        "source_semantics_verified": False, "qualified": False, "admitted": False,
        "constitution_formalized": False, "weights_downloaded": False}
    write(output / "summary.json", result)
    print(json.dumps(result, indent=2))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    parser.add_argument("--lake", required=True)
    parser.add_argument("--java-executable", required=True)
    parser.add_argument("--tla2tools-jar", required=True)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--epochs", type=int, default=12)
    args = parser.parse_args()
    result = run(args.output, lake=args.lake, java_executable=args.java_executable,
        tla2tools_jar=args.tla2tools_jar, workers=args.workers, epochs=args.epochs)
    raise SystemExit(0 if result["integration_passed"] else 1)
