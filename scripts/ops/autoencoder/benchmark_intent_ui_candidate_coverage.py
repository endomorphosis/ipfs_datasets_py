#!/usr/bin/env python3
"""Seal six source-decoder fits before a fresh authored composition test.

Compare unchanged v1 GRU fitting (two seeds) with the existing deterministic
structured ridge path (one fit) per domain. This does not modify legacy models,
claim joint autoencoder convergence, prove source meaning, or execute Lake.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import importlib
import importlib.util
import json
import math
import os
from pathlib import Path
import platform
import resource
import statistics
import sys
import time
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[3]
PANEL = ROOT / "tests/fixtures/logic/intent_ui_source_compositions_v1/panel.py"
HELPER = Path(__file__).with_name("benchmark_source384_fidelity.py")
AUDIT_MODULE = "ipfs_datasets_py.logic.formalization.autoencoder.intent_candidate_fidelity"
FALSE = {"qualified": False, "admitted": False, "formalized": False,
    "proof_authority": False, "source_semantics_verified": False, "lake_executed": False,
    "production_promotion_performed": False, "publication_performed": False,
    "convergence_guarantee": False}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def module_from_file(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def source_manifest(sha):
    paths = [path for path in (ROOT / "ipfs_datasets_py").rglob("*")
             if path.is_file() and not {"__pycache__", ".git", ".pytest_cache"}.intersection(path.parts)
             and path.suffix not in (".pyc", ".pyo")]
    paths.extend((Path(__file__).resolve(), PANEL, HELPER))
    return [{"path": str(path.relative_to(ROOT)), "sha256": sha(path), "bytes": path.stat().st_size}
            for path in sorted(set(paths))]


def inputs_only(rows):
    return [{key: row[key] for key in ("id", "source_text", "embedding")} for row in rows]


def structured_raw_candidate(row, checkpoint):
    """Recover precisely the predicted typed structure, even if native-invalid.

    Only generated class indices and the training-consensus schema are used;
    no reference, source parser, or complete-target retrieval enters readout.
    """
    schema = checkpoint["target_schema"]
    result = deepcopy(schema["template"])
    require(len(row["predicted_classes"]) == len(schema["slots"]), "predicted slot count differs")
    for slot, index in zip(schema["slots"], row["predicted_classes"]):
        require(type(index) is int and 0 <= index < len(slot["classes"]), "invalid predicted class")
        node = result
        for key in slot["path"][:-1]:
            node = node[key]
        node[slot["path"][-1]] = deepcopy(slot["classes"][index])
    return result


def readout(runtime, strategy, rows, native, contract, *, ablation=None):
    """Public runtime plus the same explicit native gate, all target-free.

    Runtime owners already perform their own native work, whose cost remains
    included. The measured boundary adds this identical gate to both readers.
    """
    supplied = deepcopy(rows)
    require(all(set(row) == {"id", "source_text", "embedding"} for row in supplied),
            "only target-free rows may enter measured inference")
    mode = ablation
    if ablation == "shuffle_embeddings":
        require(len(supplied) > 1, "shuffle requires at least two rows")
        vectors = [row["embedding"] for row in supplied]
        for index, row in enumerate(supplied):
            row["embedding"] = vectors[(index + 1) % len(vectors)]
        mode = None
    if strategy == "v1":
        require(mode in (None, "zero_condition", "zero_decoder"), "invalid GRU ablation")
    else:
        require(mode in (None, "zero_head", "zero_projection"), "invalid ridge ablation")
    observed = runtime.infer(supplied, weight_ablation=mode)
    for row in observed["rows"]:
        if strategy == "ridge":
            raw_candidate = structured_raw_candidate(row, runtime.checkpoint)
            # This is serialization of an emitted typed structure, not a neural
            # token sequence or evidence that the GRU produced an EOS token.
            row.update(raw_candidate_ir=raw_candidate, generated_tokens=native._tokens(raw_candidate),
                ended=True, generation_kind="parallel_scalar_classes_then_typed_structure",
                generated_tokens_kind="serialization_of_generated_typed_structure",
                ended_kind="typed_structure_assembly_complete_not_neural_EOS",
                reconstructed_embedding=row["projected_embedding"])
        else:
            parsed = contract.parse_generated(row["generated_tokens"], ended=row["ended"])
            raw_candidate = parsed["candidate"]
            row.update(raw_candidate_ir=raw_candidate, generation_kind="autoregressive_greedy_GRU",
                generated_tokens_kind="learned_autoregressive_tokens", ended_kind="learned_EOS_token")
        candidate, reason, semantic_scope = None, None, None
        try:
            receipt = contract.validate_native_target(observed["domain_id"], raw_candidate)
            candidate = receipt["canonical_ir"]
            semantic = receipt.get("semantic_validation")
            semantic_scope = semantic["scope"] if semantic else receipt["scope"]
        except (ValueError, TypeError, KeyError, RecursionError) as error:
            reason = str(error)[:512]
        row.update(candidate_ir=candidate, native_semantic_valid=candidate is not None,
            native_validation_scope=semantic_scope, reason=reason,
            status="unqualified_candidate" if candidate is not None else "invalid_generated_output",
            experiment_ablation=ablation, target_access=False, teacher_forcing=False, **FALSE)
    return {**observed, "benchmark_readout_scope": "public_runtime_plus_common_strong_native_gate",
        "benchmark_strategy": strategy, "experiment_ablation": ablation, **FALSE}


def audit_intent_after_generation(inference, inputs):
    """Read-only source comparison; no parser output is returned to the model."""
    if inference["domain_id"] != "intent_ir":
        return None
    helper = importlib.import_module(AUDIT_MODULE)
    require(Path(helper.__file__).resolve().is_relative_to(ROOT), "Intent audit loaded outside frozen source")
    require(len(inference["rows"]) == len(inputs), "audit row count differs")
    rows, counts = [], {}
    for actual, source in zip(inference["rows"], inputs):
        require(actual["id"] == source["id"], "audit identity mismatch")
        receipt = helper.audit_intent_candidate(source["source_text"], actual["raw_candidate_ir"])
        require(receipt.get("status") in ("native_invalid", "source_unsupported", "source_disagreement", "source_agreement"),
                "unexpected source-audit status")
        counts[receipt["status"]] = counts.get(receipt["status"], 0) + 1
        rows.append({"id": actual["id"], "audit": receipt})
    return {"rows": rows, "status_counts": counts, "count": len(rows),
        "scope": "post_generation_only; parser_never_supplies_decoder_output_or_training_selection", **FALSE}


def reconstruction(rows, projected):
    require(len(rows) == len(projected), "reconstruction row count differs")
    errors, cosines = [], []
    for row, value in zip(rows, projected):
        source = row["embedding"]
        require(len(source) == len(value) == 384, "reconstruction dimension differs")
        errors.append(sum((a-b)**2 for a, b in zip(source, value))/384)
        norm = math.sqrt(sum(a*a for a in source)*sum(b*b for b in value))
        cosines.append(sum(a*b for a, b in zip(source, value))/norm if norm else 0.)
    return {"mean_embedding_mse": sum(errors)/len(errors),
        "mean_embedding_cosine": sum(cosines)/len(cosines), "count": len(rows),
        "scope": "source_embedding_vs_actual_projected_embedding; separate_from_IR_fidelity"}


def timing_distribution(values, count):
    quartiles = statistics.quantiles(values, n=4, method="inclusive")
    median = statistics.median(values)
    return {"repeats": len(values), "all_seconds": values, "median_seconds": median,
        "q1_seconds": quartiles[0], "q3_seconds": quartiles[2],
        "median_seconds_per_span": median/count, "median_spans_per_second": count/median,
        "count_per_repeat": count}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--parent", type=Path, required=True)
    parser.add_argument("--parent-sha256", required=True)
    args = parser.parse_args()
    out = args.output.resolve()
    require(not out.exists(), "use a fresh output directory; evidence is immutable")
    out.mkdir(parents=True)
    sys.dont_write_bytecode = True
    os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", HF_DATASETS_OFFLINE="1",
        PYTHONDONTWRITEBYTECODE="1", CUDA_VISIBLE_DEVICES="", OMP_NUM_THREADS="1",
        OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1")
    sys.path.insert(0, str(ROOT))
    base = module_from_file("_candidate_coverage_helpers", HELPER)
    raw, sha, save = base.raw, base.sha, base.save
    started = time.perf_counter()
    save(out / "started.json", {"source": str(ROOT), "script_sha256": sha(Path(__file__)),
        "helper_sha256": sha(HELPER), "panel_sha256": sha(PANEL),
        "parent": str(args.parent.resolve()), **FALSE})
    save(out / "memory-preflight.json", base.memory_preflight())
    pins = source_manifest(sha)
    save(out / "source-manifest.json", {"files": pins, "sha256": hashlib.sha256(raw(pins)).hexdigest()})
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_embedding_runtime as embeddings
    with embeddings._offline_guard():
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer import domain_384_autoencoder as native
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer import domain_384_batched_inference as batch_reader
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer import domain_384_fidelity as contract
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_latent_formula as numerical
        from ipfs_datasets_py.logic.formalization.autoencoder import structured_source_ridge_path_384 as ridge
        from ipfs_datasets_py.logic.formalization.autoencoder import structured_source_384 as structured
        from ipfs_datasets_py.logic.autoformal.tree_pin import require_workspace_logic_tree
        import torch
        import sentence_transformers
        torch.set_num_threads(1)
        logic_pin = require_workspace_logic_tree()
        for module in (native, batch_reader, contract, numerical, ridge, structured, embeddings):
            require(Path(module.__file__).resolve().is_relative_to(ROOT), "drifted numerical/parser source tree")
        audit_path = ROOT / (AUDIT_MODULE.replace(".", "/") + ".py")
        require(audit_path.is_file(), "post-generation Intent audit owner is required before fitting")
        panel = module_from_file("_intent_ui_source_composition_panel", PANEL)
        panel_metadata = panel.metadata()  # coordinates only; no test rows/texts.
        require(panel_metadata["counts_per_domain"] == {"train": 96, "tuning": 24, "test": 24}, "panel counts differ")
        require(tuple(panel.SEEDS) == (3517, 3518), "baseline seed contract differs")
        require(sha(args.parent) == args.parent_sha256, "parent bytes differ")
        parent = json.loads(args.parent.read_bytes())
        numerical.validate_checkpoint(parent)
        require(parent["binding"]["dimension"] == 384 and parent["config"]["max_target_tokens"] == 64
                and parent["progress"]["optimizer_steps"] > 0, "trained 384D 64-token parent required")
        parent_projection = structured._projection(parent)
        snapshot, assets = embeddings._snapshot_assets(embeddings.DEFAULT_SNAPSHOT_PATH)
        config = dict(epochs=1000, batch_size=16, learning_rate=.003, reconstruction_weight=.1,
                      patience=120, max_seconds=30, max_target_tokens=64)
        embedding_provenance = {"model_id": "thenlper/gte-small", "revision": embeddings.PINNED_REVISION,
            "assets": assets, "actual_tokens_recorded": True, "downloads_performed": False}
        plan = {"schema": "intent-ui-candidate-coverage-plan/v1", "panel": panel_metadata,
            "source_tree": str(ROOT), "logic_tree_pin": logic_pin,
            "parent": {"path": str(args.parent.resolve()), "sha256": args.parent_sha256},
            "parent_projection_sha256": structured.digest(parent_projection),
            "embedding_assets": assets, "config_v1": config, "ridge_grid": list(structured.RIDGES),
            "ridge_producer": ridge._pins(), "inference_producer": batch_reader._implementation(),
            "strategies": ["v1", "ridge"], "v1_seeds": list(panel.SEEDS), "ridge_fits_per_domain": 1,
            "comparison_scope": "different_head_algorithms; fixed-schema_scalar_classes_vs_autoregressive_GRU",
            "ridge_encoder_frozen": True, "ridge_is_not_joint_autoencoder_retraining": True,
            "no_cross_architecture_autoregressive_loss_comparison": True,
            "common_native_validation": "domain_384_fidelity.validate_native_target",
            "source_audit": {"module": AUDIT_MODULE, "sha256": sha(audit_path),
                "only_after_generation": True, "used_for_fitting_or_selection": False},
            "readers": {"v1": "domain_384_batched_inference.Runtime(batch_size=16), same v1 weights",
                "ridge": "structured_source_384.Runtime, parallel scalar classes, training-consensus schema"},
            "timings": {"warmups_per_arm": 1, "paired_rounds": 10, "rows_per_arm": 24,
                "order": "forward then reversed arm order on alternating rounds",
                "scope": "public readout plus identical explicit strong native gate; input deepcopy and structure serialization included",
                "excluded": ["model_loading", "warmup", "gold_fidelity_scoring", "post_generation_source_audit", "embedding_production"]},
            "ablations": {"v1": ["zero_condition", "zero_decoder", "shuffle_embeddings"],
                "ridge": ["zero_head", "zero_projection", "shuffle_embeddings"]},
            "shuffle_policy": "cyclic embedding rotation only; IDs, source texts, and expected targets stay fixed",
            "selection_uses_tuning_only": True, "all_fits_sealed_before_test_materialization": True,
            "temperature": 0, "max_target_tokens": 64, "downloads_performed": False,
            "python": sys.version, "platform": platform.platform(), "torch": str(torch.__version__), **FALSE}
        save(out / "plan.json", plan)
        with torch.random.fork_rng(devices=[]):
            torch.manual_seed(0)
            encoder = sentence_transformers.SentenceTransformer(str(snapshot), local_files_only=True,
                trust_remote_code=False, device="cpu")
            encoder.eval()
            embeddings._validate_model(encoder, torch)
        input_descriptors = {}

        def prepare(domain, split):
            if split == "test":
                require((out / "freeze.json").is_file() and (out / "test-exposure.json").is_file(),
                        "all candidates must be sealed before test materialization")
            rows = panel.rows(split, domain)
            require(len(rows) == panel_metadata["counts_per_domain"][split], "actual panel count differs")
            for row in rows:
                contract.validate_native_target(domain, row["target"])
                require(len(native._tokens(row["target"])) + 2 <= 64, "target exceeds unchanged context cap")
            tick = time.perf_counter()
            result = embeddings._produce_results(
                [SimpleNamespace(text=row["source_text"], input_id=row["id"]) for row in rows],
                encoder, torch, batch_size=16,
                token_input_digest=lambda value: hashlib.sha256(raw(value)).hexdigest())
            require(len(result) == len(rows), "embedding output count differs")
            receipts = []
            for row, embedded in zip(rows, result):
                require(embedded["input_id"] == row["id"] and embedded["status"] == "embedded", "missing genuine local embedding")
                row["embedding"] = embedded["vector"]
                receipts.append({**embedded, "source_sha256": hashlib.sha256(row["source_text"].encode()).hexdigest(),
                    "embedding_sha256": native.digest(row["embedding"]), "target_sha256": native.digest(row["target"])})
            for filename, data in ((split + ".json", rows), (split + "-embedding-evidence.json", {
                "producer": "verified local GTE model with captured actual untruncated tokens",
                "scope": "authored composition source vectors, not qualified SourceSampleRecord receipts",
                "assets": assets, "results": receipts, "elapsed_seconds": time.perf_counter()-tick, **FALSE})):
                descriptor = save(out / domain / filename, data)
                input_descriptors[domain + "/" + filename] = descriptor
            return rows

        data = {domain: {split: prepare(domain, split) for split in ("train", "tuning")}
                for domain in panel.DOMAINS}
        for domain, partitions in data.items():
            vocab = {token for row in partitions["train"] for token in native._tokens(row["target"])}
            require({token for row in partitions["tuning"] for token in native._tokens(row["target"])} <= vocab,
                    "tuning token outside training vocabulary")
            require(not {row["id"] for row in partitions["train"]} & {row["id"] for row in partitions["tuning"]},
                    "development composition IDs overlap")

        def load_reader(fit):
            descriptor = fit["checkpoint"]
            if fit["strategy"] == "v1":
                return batch_reader.load_checkpoint(descriptor["path"], expected_sha256=descriptor["sha256"],
                    expected_domain=fit["domain"], batch_size=16)
            return structured.load_checkpoint(descriptor["path"], expected_sha256=descriptor["sha256"], expected_domain=fit["domain"])

        def evaluation(fit, reader, rows, split, ablation=None):
            inferred = readout(reader, fit["strategy"], inputs_only(rows), native, contract, ablation=ablation)
            observed = base.fidelity(inferred, rows, panel.critical_paths(fit["domain"]))
            with structured._numeric() as np:
                initial = structured._project(np, rows, parent_projection).tolist()
            observed["frozen_parent_reconstruction"] = reconstruction(rows, initial)
            observed["reconstruction_interpretation"] = (
                "inherited projection unchanged; not a trained reconstruction improvement" if fit["strategy"] == "ridge"
                else "selected jointly trained GRU/projection vs separately reported frozen inherited projection")
            source_audit = audit_intent_after_generation(inferred, inputs_only(rows))
            if source_audit is not None:
                observed["post_generation_source_audit_counts"] = source_audit["status_counts"]
            output = out / fit["directory"]
            prefix = split + ("-" + ablation if ablation else "")
            save(output / (prefix + "-inference.json"), inferred)
            save(output / (prefix + "-fidelity.json"), observed)
            if source_audit is not None:
                save(output / (prefix + "-source-audit.json"), source_audit)
            return {key: value for key, value in observed.items() if key != "rows"}

        fits = []
        for domain_index, domain in enumerate(panel.DOMAINS):
            # Alternate which head family incurs the first fit's import/cache
            # costs. These public-fit times remain descriptive single calls.
            arms = [("v1", seed) for seed in panel.SEEDS] + [("ridge", None)]
            if domain_index:
                arms.reverse()
            for strategy, seed in arms:
                directory = f"{domain}/v1-{seed}" if strategy == "v1" else f"{domain}/ridge"
                print(json.dumps({"phase": "fit", "domain": domain, "strategy": strategy, "seed": seed}), flush=True)
                tick = time.perf_counter()
                if strategy == "v1":
                    result = native.train(domain, data[domain]["train"], data[domain]["tuning"],
                        parent_projection=plan["parent"], config={**config, "seed": seed,
                            "embedding_provenance": embedding_provenance})
                else:
                    result = ridge.train(domain, data[domain]["train"], data[domain]["tuning"],
                        parent_projection=plan["parent"], config={"ridges": list(structured.RIDGES),
                            "embedding_provenance": embedding_provenance})
                    require(result["checkpoint"]["projection_sha256"] == plan["parent_projection_sha256"],
                            "ridge inherited projection changed")
                elapsed = time.perf_counter()-tick
                fit = {"domain": domain, "strategy": strategy, "seed": seed, "directory": directory,
                    "checkpoint": save(out / directory / "checkpoint.json", result["checkpoint"]),
                    "full_training_call_seconds": elapsed, "unique_training_examples": 96,
                    "full_fit_unique_examples_per_second": 96/elapsed,
                    "fit_time_scope": "public trainer including validation, selection, serialization and checkpoint validation",
                    "fit_repetition_count": 1, "metrics": result["metrics"], **FALSE}
                save(out / directory / "training-metrics.json", result["metrics"])
                reader = load_reader(fit)
                save(out / directory / "runtime-description.json", reader.describe())
                fit["reports"] = {split: evaluation(fit, reader, data[domain][split], split)
                                  for split in ("train", "tuning")}
                fits.append(fit)
        require(len(fits) == 6, "all six fits must complete before test exposure")
        save(out / "fits.json", fits)
        save(out / "development-inputs.json", input_descriptors)
        require(source_manifest(sha) == pins, "source changed before sealing")
        before_freeze = {str(path.relative_to(out)): sha(path) for path in sorted(out.rglob("*.json"))}
        freeze = save(out / "freeze.json", {"plan_sha256": sha(out / "plan.json"),
            "source_manifest_sha256": sha(out / "source-manifest.json"),
            "fits": [{key: fit[key] for key in ("domain", "strategy", "seed", "checkpoint", "directory")} for fit in fits],
            "pre_exposure_artifact_sha256": before_freeze,
            "test_targets_generated": False, "test_embeddings_generated": False,
            "sealed_unix_seconds": time.time(), **FALSE})
        require(all(sha(out / relative) == digest for relative, digest in before_freeze.items()), "artifact changed while sealing")
        save(out / "test-exposure.json", {"freeze": freeze, "exposure_unix_seconds": time.time(),
            "post_exposure_fitting_or_tuning_allowed": False,
            "scope": "fresh authored complete compositions; vocabulary and semantic groups shared with development", **FALSE})
        tests = {domain: prepare(domain, "test") for domain in panel.DOMAINS}
        outcomes, timing_reports = [], []
        for domain in panel.DOMAINS:
            active = [fit for fit in fits if fit["domain"] == domain]
            readers = {fit["directory"]: load_reader(fit) for fit in active}
            inputs = inputs_only(tests[domain])
            for fit in active:
                reader = readers[fit["directory"]]
                conditioned = evaluation(fit, reader, tests[domain], "test-conditioned")
                ablations = {mode: evaluation(fit, reader, tests[domain], "test", mode)
                             for mode in plan["ablations"][fit["strategy"]]}
                outcomes.append({"domain": domain, "strategy": fit["strategy"], "seed": fit["seed"],
                    "checkpoint": fit["checkpoint"], "conditioned": conditioned, "ablations": ablations, **FALSE})
            timing = {fit["directory"]: [] for fit in active}
            stable = {}
            for fit in active:
                inferred = readout(readers[fit["directory"]], fit["strategy"], inputs, native, contract)
                stable[fit["directory"]] = native.digest(inferred)
                save(out / fit["directory"] / "timing-warmup-inference.json", inferred)
            for repeat in range(10):
                for fit in active if repeat % 2 == 0 else list(reversed(active)):
                    tick = time.perf_counter()
                    inferred = readout(readers[fit["directory"]], fit["strategy"], inputs, native, contract)
                    elapsed = time.perf_counter()-tick
                    timing[fit["directory"]].append(elapsed)
                    require(native.digest(inferred) == stable[fit["directory"]], "repeated immutable readout differs")
                    save(out / fit["directory"] / f"timing-{repeat:02d}-inference.json", inferred)
            for fit in active:
                report = {"domain": domain, "strategy": fit["strategy"], "seed": fit["seed"],
                    **timing_distribution(timing[fit["directory"]], 24), "timing_scope": plan["timings"],
                    "checkpoint_sha256": fit["checkpoint"]["sha256"],
                    "reader": plan["readers"][fit["strategy"]], "repeated_outputs_unchanged": True, **FALSE}
                save(out / fit["directory"] / "inference-timing.json", report)
                timing_reports.append(report)
        require(all(sha(out / relative) == digest for relative, digest in before_freeze.items()), "frozen fit/development artifacts changed")
        require(sha(args.parent) == args.parent_sha256, "parent changed during comparison")
        require(embeddings._snapshot_assets(embeddings.DEFAULT_SNAPSHOT_PATH)[1] == assets, "local embedding assets changed")
        require(source_manifest(sha) == pins and ridge._pins() == plan["ridge_producer"], "producer source changed")
        require(all(sha(Path(item["path"])) == item["sha256"] for item in input_descriptors.values()), "source input artifacts changed")
        loaded = {name: str(Path(module.__file__).resolve()) for name, module in tuple(sys.modules.items())
                  if name.startswith("ipfs_datasets_py") and getattr(module, "__file__", None)}
        require(all(Path(path).is_relative_to(ROOT) for path in loaded.values()), "drifted loaded module")
        save(out / "loaded-modules.json", loaded)
        save(out / "input-hashes.json", input_descriptors)
        save(out / "summary.json", {"schema": "intent-ui-candidate-coverage-comparison/v1",
            "outcomes": outcomes, "inference_timings": timing_reports,
            "elapsed_seconds": time.perf_counter()-started,
            "max_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            "rss_scope": "whole mixed process including local semantic encoder; not per-model RSS",
            "source_unchanged": True, "parent_unchanged": True, "assets_unchanged": True,
            "inputs_unchanged": True, "frozen_artifacts_unchanged": True,
            "test_used_for_selection": False, "actual_fit_count": 6,
            "ridge_fits_are_not_independent_seed_repetitions": True,
            "semantic_groups_disjoint": False, "complete_compositions_disjoint": True,
            "comparison_is_not_joint_autoencoder_convergence": True,
            "bridge_evaluate_executed": False, "downloads_performed": False, **FALSE})


if __name__ == "__main__":
    main()
