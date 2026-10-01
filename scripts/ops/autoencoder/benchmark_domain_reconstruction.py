#!/usr/bin/env python3
"""Prepare/freeze/evaluate four separate native projection reconstruction heads.

Run with OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1,
CUDA_VISIBLE_DEVICES='' and PYTHONPATH pointing at the chosen source checkout.
This diagnostic does not score or train the separate source-language decoders.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
from pathlib import Path
import resource
import statistics
import time

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import domain_reconstruction_panel as panel
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_family_training_v2 as reference
from ipfs_datasets_py.logic.formalization.autoencoder import family_coverage_audit as coverage_audit

SCHEMA = "multidomain-reconstruction-comparison/v1"
SEEDS = (1729, 1730, 1731)
SETTINGS = dict(epochs=24, latent_width=8, learning_rate=.001, minibatch_size=6,
                denoising=.05, ridge=.001, patience=24, max_seconds=120)


def _raw(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(_raw(value))


def _read(path):
    return json.loads(path.read_bytes())


def _backend(name):
    if name == "reference":
        return reference, reference.train_family_projection_autoencoder_v2, reference.infer_family_projection_autoencoder_v2
    if name != "prepared":
        raise ValueError("unknown numerical backend")
    module = importlib.import_module("ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_family_training_prepared")
    return module, module.train_family_projection_autoencoder_prepared, module.infer_family_projection_autoencoder_prepared


def _producer():
    files = [Path(__file__), Path(panel.__file__), Path(reference.__file__), Path(reference.codec.__file__),
             Path(coverage_audit.__file__)]
    files.append(Path(_backend("prepared")[0].__file__))
    return {str(path.resolve()): _sha(path.read_bytes()) for path in files}


def _guard(directory):
    plan = _read(directory / "plan.json")
    if plan["producer"] != _producer() or plan["manifest_sha256"] != panel.digest(panel.manifest()):
        raise ValueError("comparison source or authored manifest changed")
    if plan["seeds"] != list(SEEDS) or plan["settings"] != SETTINGS:
        raise ValueError("predeclared comparison seeds or settings changed")
    for relative, digest in plan["development_files"].items():
        if _sha((directory / relative).read_bytes()) != digest:
            raise ValueError("prepared development targets changed")
    return plan


def prepare(directory):
    if directory.exists():
        raise ValueError("fresh output directory required")
    producer = _producer()
    directory.mkdir(parents=True)
    _write(directory / "manifest.json", panel.manifest())
    files = {"manifest.json": _sha((directory / "manifest.json").read_bytes())}
    preparation = {}
    for domain in panel.DOMAINS:
        started = time.perf_counter()
        targets = {split: panel.prepare_partition(domain, split) for split in ("train", "validation")}
        path = directory / domain / "development.json"
        _write(path, targets)
        files[str(path.relative_to(directory))] = _sha(path.read_bytes())
        preparation[domain] = {"seconds": time.perf_counter() - started,
            "sample_count": sum(map(len, targets.values())), "bytes": path.stat().st_size}
    if producer != _producer():
        raise ValueError("source changed during preparation")
    _write(directory / "plan.json", {"schema": SCHEMA, "producer": producer,
        "manifest_sha256": panel.digest(panel.manifest()), "development_files": files,
        "preparation": preparation, "seeds": list(SEEDS), "settings": SETTINGS,
        "prepared_targets_shared_between_backends": True,
        "training_scope": "native structural feature reconstruction, not source-language formula decoding",
        "heldout_targets_prepared": False, "selection_on_heldout": False,
        "embedding_weights_loaded": False, "provider_calls": 0, "download_calls": 0,
        "environment": {name: os.environ.get(name) for name in
            ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "CUDA_VISIBLE_DEVICES")}})


def fit(directory):
    import torch
    plan = _guard(directory)
    with (directory / "fit-started").open("xb") as stream:
        stream.write(b"one fit attempt per prepared experiment\n")
    fits = []
    for domain in panel.DOMAINS:
        targets = _read(directory / domain / "development.json")
        # Warm up both numerical implementations using development data only.
        for name in ("reference", "prepared"):
            _, train, _ = _backend(name)
            train(targets["train"], targets["validation"], output_dir=directory / domain / ("warmup-" + name),
                **{**SETTINGS, "epochs": 1, "patience": 1, "seed": 0})
        for index, seed in enumerate(SEEDS):
            pairs = {}
            for name in (("reference", "prepared") if index % 2 == 0 else ("prepared", "reference")):
                module, train, _ = _backend(name)
                started = time.perf_counter()
                trained = train(targets["train"], targets["validation"],
                    output_dir=directory / domain / f"{name}-{seed}", seed=seed, **SETTINGS)
                elapsed = time.perf_counter() - started
                expected_steps = SETTINGS["epochs"] * ((len(targets["train"]) + SETTINGS["minibatch_size"] - 1)
                                                        // SETTINGS["minibatch_size"])
                if (trained["report"]["epochs_completed"] != SETTINGS["epochs"]
                        or trained["report"]["optimizer_steps"] != expected_steps
                        or trained["report"]["stopping"] not in {"epoch_budget", "validation_patience"}):
                    raise ValueError("full predeclared optimization budget required before comparison")
                saved, _ = module._read(trained["descriptor"])
                record = {"domain_id": domain, "backend": name, "seed": seed,
                    "descriptor": trained["descriptor"], "report": trained["report"],
                    "wall_seconds": elapsed, "torch_threads_after_call": torch.get_num_threads(),
                    "parameters_sha256": panel.digest(saved["parameters"]),
                    "row_presentations": len(targets["train"]) * trained["report"]["epochs_completed"]}
                record["row_presentations_per_second"] = record["row_presentations"] / elapsed
                pairs[name] = record
                fits.append(record)
                print(json.dumps({"domain": domain, "backend": name, "seed": seed,
                    "wall_seconds": elapsed, "optimizer_steps": trained["report"]["optimizer_steps"]}), flush=True)
            # A speed result is accepted only when complete retained weights and
            # every training/selection observation agree. Timings are excluded.
            if pairs["reference"]["parameters_sha256"] != pairs["prepared"]["parameters_sha256"]:
                raise ValueError("prepared/reference retained parameter mismatch")
            for field in ("history", "initial_parameters_sha256", "selected_parameters_sha256",
                          "optimizer_steps", "epochs_completed", "selected_epoch", "stopping", "before", "after"):
                if pairs["reference"]["report"][field] != pairs["prepared"]["report"][field]:
                    raise ValueError("prepared/reference numerical telemetry differs: " + field)
    _guard(directory)
    _write(directory / "fits.json", fits)
    frozen = {str(path.relative_to(directory)): _sha(path.read_bytes())
              for path in sorted(directory.rglob("*")) if path.is_file()}
    _write(directory / "freeze.json", {"schema": SCHEMA, "files": frozen,
        "model_count": len(fits), "heldout_not_used": True, "all_models_fixed_before_heldout": True})
    print(json.dumps({"freeze_sha256": _sha((directory / "freeze.json").read_bytes())}), flush=True)


def frozen_fits(directory, expected_sha256):
    if not expected_sha256 or _sha((directory / "freeze.json").read_bytes()) != expected_sha256:
        raise ValueError("explicit matching freeze SHA256 required")
    freeze = _read(directory / "freeze.json")
    for relative, digest in freeze["files"].items():
        path = directory / relative
        if not path.is_file() or path.is_symlink() or _sha(path.read_bytes()) != digest:
            raise ValueError("frozen artifact changed: " + relative)
    fits = _read(directory / "fits.json")
    expected = {(domain, backend, seed) for domain in panel.DOMAINS for backend in ("reference", "prepared") for seed in SEEDS}
    observed = [(row.get("domain_id"), row.get("backend"), row.get("seed")) for row in fits]
    if len(observed) != len(expected) or set(observed) != expected:
        raise ValueError("all predeclared fitted heads required before evaluation")
    # Load every head with its provenance checks before preparing ANY holdout.
    for row in fits:
        saved, _ = _backend(row["backend"])[0]._read(row["descriptor"])
        if (saved["space"]["domain_id"] != row["domain_id"] or saved["report"] != row["report"]
                or saved["report"]["settings"]["seed"] != row["seed"]
                or panel.digest(saved["parameters"]) != row["parameters_sha256"]):
            raise ValueError("frozen head identity differs from comparison arm")
    return fits


def _initial_metrics(saved, parameters_sha, training_reports, heldout_reports):
    import torch
    codec = reference.codec
    _, training_rows = reference._reports(training_reports)
    _, heldout_rows = reference._reports(heldout_reports)
    training, _, _, _ = codec._matrix(saved["space"], training_rows)
    values, mask, spans, coverage = codec._matrix(saved["space"], heldout_rows)
    mean = training.mean(dim=0)
    _, _, vectors = torch.linalg.svd(training - mean, full_matrices=False)
    basis = torch.zeros((training.shape[1], saved["report"]["latent_width"]), dtype=torch.float64)
    rank = min(basis.shape[1], len(vectors))
    basis[:, :rank] = vectors[:rank].T
    initial = [basis, -(mean @ basis), basis.T.clone(), mean.clone()]
    if panel.digest([p.tolist() for p in initial]) != parameters_sha:
        raise ValueError("recreated training-only initializer differs")
    with torch.no_grad():
        score, metrics = codec._objective(torch, reference._forward(torch, values, initial),
            values, mask, spans, saved["space"]["projections"])
    return {"objective": float(score), **metrics, "coverage": coverage,
        "effective_feature_panel": reference._feature_panel(values, mask)}


def evaluate(directory, expected_sha256):
    import torch
    torch.set_num_threads(1)
    plan = _guard(directory)
    fits = frozen_fits(directory, expected_sha256)
    with (directory / "evaluation-started").open("xb") as stream:
        stream.write(b"heldout becomes exposed; cannot repeat or refit this experiment\n")
    results = {}
    for domain in panel.DOMAINS:
        started = time.perf_counter()
        heldout = panel.prepare_partition(domain, "test")
        preparation_seconds = time.perf_counter() - started
        _write(directory / domain / "heldout-targets.json", heldout)
        training = _read(directory / domain / "development.json")
        domain_fits = [row for row in fits if row["domain_id"] == domain]
        saved, _ = reference._read(next(row["descriptor"] for row in domain_fits if row["backend"] == "reference"))
        initial = _initial_metrics(saved, saved["report"]["initial_parameters_sha256"], training["train"], heldout)
        outcomes = []
        audit_inference = audit_training = None
        for fit_row in domain_fits:
            _, _, infer = _backend(fit_row["backend"])
            before = Path(fit_row["descriptor"]["path"]).read_bytes()
            started = time.perf_counter()
            inference = infer(fit_row["descriptor"], heldout)
            elapsed = time.perf_counter() - started
            if before != Path(fit_row["descriptor"]["path"]).read_bytes():
                raise ValueError("inference changed checkpoint")
            output_path = directory / domain / f"{fit_row['backend']}-{fit_row['seed']}-heldout.json"
            _write(output_path, inference)
            if fit_row["backend"] == "prepared" and fit_row["seed"] == SEEDS[0]:
                audit_inference, audit_training = inference, fit_row["report"]
            outcomes.append({"backend": fit_row["backend"], "seed": fit_row["seed"],
                "objective": inference["objective"], "families": inference["families"],
                "projections": inference["projections"], "inference_seconds": elapsed,
                "inference_seconds_per_span": elapsed / len(heldout),
                "regressed_families_against_initializer": sorted(f for f, loss in inference["families"].items()
                    if loss > initial["families"][f] + 1e-12),
                "objective_improved_against_initializer": inference["objective"] < initial["objective"] - 1e-12})
        for seed in SEEDS:
            pair = [row for row in outcomes if row["seed"] == seed]
            if pair[0]["objective"] != pair[1]["objective"] or pair[0]["families"] != pair[1]["families"]:
                raise ValueError("heldout numerical parity failed")
        timings = {name: [row["wall_seconds"] for row in domain_fits if row["backend"] == name]
                   for name in ("reference", "prepared")}
        throughput = {name: statistics.mean(row["row_presentations_per_second"] for row in domain_fits if row["backend"] == name)
                      for name in timings}
        catalog = coverage_audit.native_v2.family_training_catalog_v2(domain)
        required = {row["family_id"] for row in catalog["family_inventory"] if row["projection_adapter_available"]}
        if domain == "legal_ir":
            required.update(("first_order", "deontic", "temporal", "tdfol", "event_calculus", "dcec", "frame_logic", "propositional"))
        audit = coverage_audit.audit_family_training_coverage(domain, training_reports=training["train"],
            tuning_reports=training["validation"], heldout_reports=heldout, required_families=sorted(required),
            required_profiles=[], numerical_training_report=audit_training, numerical_heldout_report=audit_inference)
        _write(directory / domain / "coverage.json", audit)
        results[domain] = {"training_samples": len(training["train"]), "tuning_samples": len(training["validation"]),
            "heldout_samples": len(heldout), "heldout_independent_compositional_groups": 4,
            "heldout_target_preparation_seconds": preparation_seconds, "initial": initial, "outcomes": outcomes,
            "training_wall_seconds": timings, "mean_training_rows_per_second": throughput,
            "wall_ratio_reference_over_prepared": statistics.mean(timings["reference"]) / statistics.mean(timings["prepared"]),
            "trained_logic_families": saved["report"]["trained_logic_families"],
            "requested_family_count": len(heldout[0]["requested_families"]),
            "coverage_floor_satisfied": audit["floor_satisfied"],
            "missing_required_families": [row["family_id"] for row in audit["required_floor"] if not row["floor_satisfied"]],
            "legal_DFOL_TFOL_CEC_profile_floor_verified": False,
            "test_used_for_selection": False, "source_decoder_fidelity_measured": False}
    _guard(directory)
    report = {"schema": SCHEMA, "plan": plan, "freeze_sha256": expected_sha256, "results": results,
        "qualification": False, "admitted": False, "formalized": False, "lake_build_executed": False,
        "holdout_now_exposed": True, "fitted_heads_promoted": False,
        "peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
        "legal_ir_metric_bridge_names": [], "legal_ir_metric_target_count": 0,
        "legal_ir_evaluate_provers": False, "metric_disk_cache": False, "workers": 1,
        "timing_scope": "native target preparation and structural head train/infer; not bridge-on evaluate"}
    _write(directory / "report.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=("prepare", "fit", "evaluate"), required=True)
    parser.add_argument("--output-directory", type=Path, required=True)
    parser.add_argument("--freeze-sha256")
    args = parser.parse_args()
    directory = args.output_directory.resolve()
    if args.phase == "evaluate":
        evaluate(directory, args.freeze_sha256)
    else:
        {"prepare": prepare, "fit": fit}[args.phase](directory)


if __name__ == "__main__":
    main()
