#!/usr/bin/env python3
"""Sealed authored 384D source/fragment comparison with offline real embeddings.

All training/tuning data and all compared checkpoints are saved before test
texts, targets, or embeddings are produced. Native fragment validity remains
separate from exact source-target equality; neither grants qualification.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import importlib.util
import json
import math
import os
from pathlib import Path
import platform
import resource
import sys
import time
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[3]
PANEL = ROOT / "tests/fixtures/logic/source384_fidelity_v2/panel.py"
FALSE = {"qualified": False, "admitted": False, "proof_authority": False,
         "source_semantics_verified": False, "lake_executed": False,
         "publication_performed": False, "production_promotion_performed": False}


def raw(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode()


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as f:
        f.write(raw(value) + b"\n")
    return {"path": str(path), "sha256": sha(path), "bytes": path.stat().st_size}


def source_manifest():
    files = []
    for path in (ROOT / "ipfs_datasets_py").rglob("*"):
        if not path.is_file() or any(p in {"__pycache__", ".pytest_cache", ".git"} for p in path.parts):
            continue
        if path.suffix in {".pyc", ".pyo"}:
            continue
        files.append(path)
    files += [Path(__file__).resolve(), PANEL]
    return [{"path": str(p.relative_to(ROOT)), "sha256": sha(p), "bytes": p.stat().st_size}
            for p in sorted(files)]


def leaves(value, path=()):
    if type(value) is dict:
        return {p: v for k, item in value.items() for p, v in leaves(item, path + (k,)).items()}
    if type(value) is list:
        return {p: v for k, item in enumerate(value) for p, v in leaves(item, path + (k,)).items()}
    return {path: value}


def differences(expected, actual, path="$", result=None):
    result = [] if result is None else result
    if type(expected) is not type(actual):
        result.append({"path": path, "kind": "type", "expected": expected, "actual": actual})
    elif isinstance(expected, dict):
        for key in sorted(set(expected) | set(actual)):
            if key not in expected or key not in actual:
                result.append({"path": path + "." + key, "kind": "missing_or_extra",
                               "expected_present": key in expected, "actual_present": key in actual,
                               "expected": expected.get(key), "actual": actual.get(key)})
            else:
                differences(expected[key], actual[key], path + "." + key, result)
    elif isinstance(expected, list):
        if len(expected) != len(actual):
            result.append({"path": path, "kind": "array_length", "expected": len(expected), "actual": len(actual)})
        for i, (a, b) in enumerate(zip(expected, actual)):
            differences(a, b, f"{path}[{i}]", result)
    elif expected != actual:
        result.append({"path": path, "kind": "value", "expected": expected, "actual": actual})
    return result


def fidelity(inference, references, critical_paths):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import domain_384_autoencoder as base
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import domain_384_fidelity as contract
    domain = inference["domain_id"]
    assert len(inference["rows"]) == len(references)
    observed = []
    for generated, gold in zip(inference["rows"], references):
        assert generated["id"] == gold["id"]
        assert generated["target_access"] is False and generated["teacher_forcing"] is False
        parsed = contract.parse_generated(generated["generated_tokens"], ended=generated["ended"])
        candidate = parsed["candidate"]
        envelope_valid = native_valid = False
        envelope_error = native_error = parsed["error"]
        native_scope = None
        if parsed["json_valid"]:
            try:
                base.validate_target(domain, candidate)
                envelope_valid, envelope_error = True, None
            except (ValueError, TypeError, KeyError, RecursionError) as error:
                envelope_error = str(error)[:512]
            try:
                validated = contract.validate_native_target(domain, candidate)
                native_valid, native_error = True, None
                semantic = validated.get("semantic_validation")
                native_scope = semantic["scope"] if semantic else validated["scope"]
            except (ValueError, TypeError, KeyError, RecursionError) as error:
                native_error = str(error)[:512]
        diff = differences(gold["target"], candidate)
        expected_leaves = leaves(gold["target"])
        actual_leaves = leaves(candidate) if candidate is not None else {}
        slots = {"/".join(path): {
            "expected": expected_leaves[path], "actual": actual_leaves.get(path),
            "correct": native_valid and path in actual_leaves and type(actual_leaves[path]) is type(expected_leaves[path])
            and actual_leaves[path] == expected_leaves[path],
        } for path in critical_paths}
        a, b = gold["embedding"], generated["reconstructed_embedding"]
        norm = math.sqrt(sum(x*x for x in a) * sum(x*x for x in b))
        observed.append({"id": gold["id"], "reference_target": gold["target"],
            "candidate_ir": generated["candidate_ir"], "raw_candidate_ir": candidate,
            "native_envelope_valid": envelope_valid, "native_envelope_error": envelope_error,
            "native_valid": native_valid, "native_validation_error": native_error,
            "native_validation_scope": native_scope,
            "exact": native_valid and not diff, "differences": diff, "critical_slots": slots,
            "status": generated["status"], "reason": generated["reason"],
            "ended": generated["ended"], "embedding_cosine": sum(x*y for x,y in zip(a,b))/norm if norm else 0.0,
            "embedding_mse": sum((x-y)**2 for x,y in zip(a,b))/len(a), **FALSE})
    return {"rows": observed, "count": len(observed),
        "native_valid_count": sum(r["native_valid"] for r in observed),
        "native_envelope_valid_count": sum(r["native_envelope_valid"] for r in observed),
        "native_validation_scopes": sorted({r["native_validation_scope"] for r in observed if r["native_validation_scope"]}),
        "exact_count": sum(r["exact"] for r in observed),
        "critical_correct": sum(s["correct"] for r in observed for s in r["critical_slots"].values()),
        "critical_total": len(observed)*len(critical_paths),
        "per_path_correct": {"/".join(path): sum(r["critical_slots"]["/".join(path)]["correct"] for r in observed) for path in critical_paths},
        "mean_embedding_cosine": sum(r["embedding_cosine"] for r in observed)/len(observed),
        "mean_embedding_mse": sum(r["embedding_mse"] for r in observed)/len(observed), **FALSE}


def memory_preflight():
    """Observed Linux headroom, not a reservation or a peak-RSS guarantee."""
    values = {}
    for line in Path("/proc/meminfo").read_text().splitlines():
        if line.startswith("MemAvailable:"):
            values["host_available_bytes"] = int(line.split()[1])*1024
    for field in ("memory.max", "memory.current"):
        path = Path("/sys/fs/cgroup")/field
        if path.is_file():
            value = path.read_text().strip()
            values[field] = int(value) if value != "max" else None
    available = [values["host_available_bytes"]]
    if values.get("memory.max") is not None and values.get("memory.current") is not None:
        available.append(max(0, values["memory.max"]-values["memory.current"]))
    values["effective_observed_available_bytes"] = min(available)
    values["required_available_bytes"] = 2*1024**3
    values["scope"] = "host and mounted cgroup snapshot; no exclusive lease; excludes future peer allocation"
    if min(available) < values["required_available_bytes"]:
        raise ValueError("less than 2 GiB observed headroom for cached encoder and sequential decoder fits")
    return values


def unweighted_objective(runtime, rows, ae, torch):
    """Same teacher-forced CE+0.1 MSE on actual selected models, all tokens equal."""
    assert runtime.checkpoint["config"].get("source_conditioning", "none") == "none"
    x, y = ae._batch(torch, rows, runtime.checkpoint["codec"]["target_vocabulary"], 64)
    with torch.inference_mode():
        projected, logits = runtime.model(x, y[:, :-1])
        ce = torch.nn.functional.cross_entropy(logits.reshape(-1, logits.shape[-1]),
                                               y[:, 1:].reshape(-1), ignore_index=0)
        mse = torch.nn.functional.mse_loss(projected, x)
    return {"objective": float(ce + .1*mse), "token_cross_entropy": float(ce),
            "embedding_mse": float(mse), "scalar_value_weight": 1,
            "selection_metric": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--parent", type=Path, required=True)
    parser.add_argument("--parent-sha256", required=True)
    parser.add_argument("--v2-module", default="domain_384_autoencoder_v2")
    args = parser.parse_args()
    out = args.output.resolve()
    if out.exists():
        raise SystemExit("Use a new output directory; evidence is immutable")
    out.mkdir(parents=True)
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(ROOT))
    os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", HF_DATASETS_OFFLINE="1",
                      PYTHONDONTWRITEBYTECODE="1", CUDA_VISIBLE_DEVICES="",
                      OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1")
    started = time.perf_counter()
    save(out/"started.json", {"source": str(ROOT), "parent": str(args.parent.resolve()),
                              "script_sha256": sha(Path(__file__)), **FALSE})
    save(out/"memory-preflight.json", memory_preflight())
    pins = source_manifest()
    save(out/"source-manifest.json", {"files": pins, "sha256": hashlib.sha256(raw(pins)).hexdigest()})
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_embedding_runtime as embeddings
    with embeddings._offline_guard():
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer import domain_384_autoencoder as ae
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_latent_formula as numerical
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer import domain_384_fidelity as contract
        from ipfs_datasets_py.logic.autoformal.tree_pin import require_workspace_logic_tree
        v2 = importlib.import_module("ipfs_datasets_py.optimizers.logic_theorem_optimizer." + args.v2_module)
        import torch
        import sentence_transformers
        torch.set_num_threads(1)
        logic_pin = require_workspace_logic_tree()
        for module in (embeddings, ae, numerical, v2, contract):
            assert Path(module.__file__).resolve().is_relative_to(ROOT)
        spec = importlib.util.spec_from_file_location("source384_fidelity_panel", PANEL)
        panel = importlib.util.module_from_spec(spec); spec.loader.exec_module(panel)
        assert sha(args.parent) == args.parent_sha256
        parent = json.loads(args.parent.read_text())
        numerical.validate_checkpoint(parent)
        assert parent["binding"]["dimension"] == 384 and parent["config"]["max_target_tokens"] == 64
        snapshot, assets = embeddings._snapshot_assets(embeddings.DEFAULT_SNAPSHOT_PATH)
        config = {"epochs": 1000, "batch_size": 8, "max_seconds": 30,
                  "learning_rate": .003, "patience": 120,
                  "reconstruction_weight": .1, "max_target_tokens": 64}
        v2_extra = {"source_conditioning": "none", "scalar_value_weight": 8,
                    "eval_interval": 10, "patience": 12,
                    "plateau_patience": 3, "plateau_factor": .5,
                    "min_learning_rate_ratio": .05, "embedding_nonregression": True}
        plan = {"schema": "source384-fidelity-benchmark/v2", "panel": panel.metadata(),
                "strategies": ["v1", "v2"], "config": config, "v2_extra": v2_extra,
                "parent": {"path": str(args.parent.resolve()), "sha256": args.parent_sha256},
                "embedding_assets": assets, "source_tree": str(ROOT), "logic_tree_pin": logic_pin,
                "python": sys.version, "platform": platform.platform(), "torch": str(torch.__version__),
                "native_fragment_validation_required": True, "max_target_tokens": 64,
                "common_native_validation": "domain_384_fidelity.validate_native_target for both strategies, including UI semantic component owner",
                "temperature": 0, "downloads_performed": False,
                "selection_uses_tuning_only": True, "test_prepared_after_all_fits_sealed": True,
                "zero_condition_ablation": "zero GRU initial hidden; same generated token loop; target-free",
                "comparison_scope": "authored_fragment_source_reconstruction; not full documents or logic proof", **FALSE}
        save(out/"plan.json", plan)
        with torch.random.fork_rng(devices=[]):
            torch.manual_seed(0)
            encoder = sentence_transformers.SentenceTransformer(str(snapshot), local_files_only=True,
                                                               trust_remote_code=False, device="cpu")
            encoder.eval(); embeddings._validate_model(encoder, torch)

        def prepare(domain, split):
            # No test call is made until freeze.json exists and is checked.
            if split == "test":
                assert (out/"freeze.json").is_file()
            rows = panel.rows(split, domain)
            for row in rows:
                contract.validate_native_target(domain, row["target"])
                assert len(ae._tokens(row["target"])) + 2 <= 64
            t0 = time.perf_counter()
            inputs = [SimpleNamespace(text=r["source_text"], input_id=r["id"]) for r in rows]
            result = embeddings._produce_results(inputs, encoder, torch, batch_size=16,
                                                  token_input_digest=lambda value: hashlib.sha256(raw(value)).hexdigest())
            receipts = []
            for row, embedded in zip(rows, result):
                assert embedded["input_id"] == row["id"] and embedded["status"] == "embedded"
                row["embedding"] = embedded["vector"]
                receipts.append({**embedded, "source_sha256": hashlib.sha256(row["source_text"].encode()).hexdigest(),
                                 "embedding_sha256": ae.digest(row["embedding"]),
                                 "target_sha256": ae.digest(row["target"])})
            save(out/domain/(split+"-embedding-evidence.json"), {
                "producer": "verified local GTE model, captured actual untruncated forward tokens",
                "scope": "authored inputs; internal tensor producer, not qualified SourceSampleRecord receipt",
                "assets": assets, "elapsed_seconds": time.perf_counter()-t0, "results": receipts, **FALSE})
            save(out/domain/(split+".json"), rows)
            return rows

        data = {domain: {split: prepare(domain, split) for split in ("train", "tuning")}
                for domain in panel.DOMAINS}
        for domain, splits in data.items():
            train_vocab = {t for row in splits["train"] for t in ae._tokens(row["target"])}
            assert {t for row in splits["tuning"] for t in ae._tokens(row["target"])} <= train_vocab
        fits = []
        for domain in panel.DOMAINS:
            for seed_index, seed in enumerate(panel.SEEDS):
                for strategy in (("v1", "v2") if seed_index == 0 else ("v2", "v1")):
                    print("training", domain, strategy, seed, flush=True)
                    module = ae if strategy == "v1" else v2
                    options = {**config, "seed": seed,
                               "embedding_provenance": {"model_id": "thenlper/gte-small",
                                   "revision": embeddings.PINNED_REVISION, "assets": assets,
                                   "actual_tokens_recorded": True, "downloads_performed": False}}
                    if strategy == "v2": options.update(v2_extra)
                    t0 = time.perf_counter()
                    result = module.train(domain, data[domain]["train"], data[domain]["tuning"],
                                          parent_projection=plan["parent"], config=options)
                    elapsed = time.perf_counter()-t0
                    fitdir = out/domain/f"{strategy}-{seed}"
                    descriptor = save(fitdir/"checkpoint.json", result["checkpoint"])
                    save(fitdir/"training-metrics.json", result["metrics"])
                    runtime = module.load_checkpoint(fitdir/"checkpoint.json", expected_sha256=descriptor["sha256"],
                                                     expected_domain=domain)
                    reports = {}
                    for split in ("train", "tuning"):
                        rows = data[domain][split]
                        inputs = [{k:r[k] for k in ("id", "source_text", "embedding")} for r in rows]
                        inferred = runtime.infer(inputs)
                        report = fidelity(inferred, rows, panel.critical_paths(domain))
                        report["ordinary_teacher_forced"] = unweighted_objective(runtime, rows, ae, torch)
                        save(fitdir/(split+"-inference.json"), inferred)
                        save(fitdir/(split+"-fidelity.json"), report)
                        reports[split] = {k:v for k,v in report.items() if k != "rows"}
                    fits.append({"domain": domain, "strategy": strategy, "seed": seed,
                                 "checkpoint": descriptor, "full_training_call_seconds": elapsed,
                                 "reports": reports, "metrics": result["metrics"]})
        save(out/"fits.json", fits)
        freeze = save(out/"freeze.json", {"plan_sha256": sha(out/"plan.json"),
            "source_manifest_sha256": sha(out/"source-manifest.json"),
            "fits": [{k:r[k] for k in ("domain", "strategy", "seed", "checkpoint")} for r in fits],
            "test_targets_generated": False, "test_embeddings_generated": False,
            "sealed_unix_seconds": time.time(), **FALSE})
        assert len(fits) == 8 and all(sha(Path(f["checkpoint"]["path"])) == f["checkpoint"]["sha256"] for f in fits)
        save(out/"test-exposure.json", {"freeze": freeze, "exposure_unix_seconds": time.time(),
            "post_exposure_tuning_allowed": False, "test_scope": "fresh authored composition holdout", **FALSE})
        tests = {domain: prepare(domain, "test") for domain in panel.DOMAINS}
        outcomes = []
        for fit in fits:
            domain, strategy, seed = fit["domain"], fit["strategy"], fit["seed"]
            module = ae if strategy == "v1" else v2
            runtime = module.load_checkpoint(fit["checkpoint"]["path"], expected_sha256=fit["checkpoint"]["sha256"],
                                             expected_domain=domain)
            rows = tests[domain]
            inputs = [{k:r[k] for k in ("id", "source_text", "embedding")} for r in rows]
            output = out/domain/f"{strategy}-{seed}"
            report = {}
            for ablation in ("conditioned", "zero_condition"):
                t0 = time.perf_counter()
                if ablation == "zero_condition":
                    inferred = runtime.infer(inputs, weight_ablation="zero_condition")
                else:
                    inferred = runtime.infer(inputs)
                seconds = time.perf_counter()-t0
                measured = fidelity(inferred, rows, panel.critical_paths(domain))
                measured["inference_seconds"] = seconds
                save(output/f"test-{ablation}-inference.json", inferred)
                save(output/f"test-{ablation}-fidelity.json", measured)
                report[ablation] = {k:v for k,v in measured.items() if k != "rows"}
            ordinary = unweighted_objective(runtime, rows, ae, torch)
            outcomes.append({"domain": domain, "strategy": strategy, "seed": seed,
                             "ordinary_teacher_forced": ordinary, **report, **FALSE})
        assert sha(args.parent) == args.parent_sha256
        assert embeddings._snapshot_assets(embeddings.DEFAULT_SNAPSHOT_PATH)[1] == assets
        assert source_manifest() == pins, "producer source changed during execution"
        loaded = {name:str(Path(module.__file__).resolve()) for name,module in tuple(sys.modules.items())
                  if name.startswith("ipfs_datasets_py") and getattr(module,"__file__",None)}
        assert all(Path(p).is_relative_to(ROOT) for p in loaded.values())
        save(out/"loaded-modules.json", loaded)
        save(out/"summary.json", {"schema": "source384-fidelity-comparison/v2", "outcomes": outcomes,
            "elapsed_seconds": time.perf_counter()-started,
            "max_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            "rss_scope": "entire mixed benchmark process including cached semantic encoder; not per model",
            "source_unchanged": True, "parent_unchanged": True, "assets_unchanged": True,
            "test_used_for_selection": False, "convergence_guarantee": False,
            "timing_scope": "descriptive CPU public APIs, alternating strategy order, no explicit warmup", **FALSE})


if __name__ == "__main__":
    main()
