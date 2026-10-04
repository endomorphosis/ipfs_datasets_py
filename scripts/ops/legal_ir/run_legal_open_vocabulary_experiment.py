#!/usr/bin/env python3
"""Matched source-copy decoders with authentic dimensional context inputs.

The entire 1485-row corpus has been exposed in prior experiments. This run is an
explicit regression experiment: authored challenge targets are withheld during
this execution's fitting, selection and generation, not claimed newly unseen.
"""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from copy import deepcopy
import hashlib
import json
import math
import multiprocessing
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from scripts.ops.legal_ir.compare_legal_decoder_architectures import require, score, sha, write
from scripts.ops.legal_ir.run_legal_span_retrieval_experiment import digest
from scripts.ops.legal_ir.run_legal_structured_retrieval_experiment import select_stage
from scripts.ops.legal_ir.run_legal_native_conditioning_experiment import verify_source_inputs

SCHEMA = "legal-open-vocabulary-dimensional-experiment/v1"
SEEDS = (1729, 1730, 1731)
SPLITS = ("train", "tuning", "challenge", "oov")
DIMENSIONS = {"trained384": 384, "native768": 768, "authentic8": 8}
FALSE = {"qualified": False, "admitted": False, "semantic_correctness_verified": False,
         "production_ready": False, "test_used_for_selection": False, "independent_holdout": False}
MAX_BYTES = 128 * 1024 * 1024


def read(path):
    path = Path(path)
    require(path.is_file() and path.stat().st_size <= MAX_BYTES, "bounded regular input required")

    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, "duplicate JSON key")
            result[key] = value
        return result

    def invalid(_):
        raise ValueError("nonfinite JSON constant")

    with path.open("rb") as stream:
        raw = stream.read(MAX_BYTES + 1)
    require(len(raw) <= MAX_BYTES, "input exceeds byte bound")
    return json.loads(raw.decode("utf-8"), object_pairs_hook=unique, parse_constant=invalid)


def file_ref(path):
    path = Path(path).resolve()
    return {"path": str(path), "sha256": sha(path), "bytes": path.stat().st_size}


def read_ref(ref):
    require(type(ref) is dict and set(ref) == {"path", "sha256", "bytes"}, "closed artifact reference required")
    require(file_ref(ref["path"]) == ref, "artifact reference differs: " + ref["path"])
    return read(ref["path"])


def verify_context_rows(sources, contexts, *, dimension):
    require(len(sources) == len(contexts), "context coverage differs")
    seen = set()
    for source, row in zip(sources, contexts):
        require(type(row) is dict and set(row) == {"id", "source_sha256", "context", "context_sha256", "native_stage_receipt"},
                "closed target-free context row required")
        require(row["id"] == source["id"] and row["source_sha256"] == source["source_sha256"]
            and row["id"] not in seen, "context source identity/order differs")
        seen.add(row["id"])
        vector = row["context"]
        require(type(vector) is list and len(vector) == dimension
            and all(type(x) in (int, float) and math.isfinite(x) for x in vector)
            and digest(vector) == row["context_sha256"], "finite dimensional context/vector hash required")
        receipt = row["native_stage_receipt"]
        require(type(receipt) is dict and receipt.get("id") == row["id"]
            and receipt.get("source_sha256") == row["source_sha256"] and receipt.get("dimension") == dimension
            and receipt.get("vector_sha256") == row["context_sha256"] and receipt.get("target_access") is False,
            "native receipt source/vector/dimension binding differs")
        require(receipt.get("source_semantics_verified") is False and
                all(receipt.get(key, False) is False for key in ("admitted", "qualified", "proof_authority")),
                "context receipt must not grant authority")
        require(receipt.get("receipt_sha256") == digest({key: value for key, value in receipt.items() if key != "receipt_sha256"}),
                "native stage receipt digest differs")


def load_context_manifest(path, expected_sha256, corpus):
    manifest_ref = file_ref(path)
    require(manifest_ref["sha256"] == expected_sha256, "context manifest hash differs")
    manifest = read_ref(manifest_ref)
    require(set(manifest) == {"schema", "corpus", "representations", "producer_pins", "target_access", "source_semantics_verified", "unavailable_representations", "native_production_manifest"}
        and manifest["schema"] == "legal-open-vocabulary-context-manifest/v1"
        and manifest["target_access"] is False and manifest["source_semantics_verified"] is False,
        "closed source-only context manifest required")
    require(read_ref(manifest["corpus"]) == corpus, "context producer corpus differs")
    from scripts.ops.legal_ir import prepare_legal_native768_contexts as producer
    native_manifest = read_ref(manifest["native_production_manifest"])
    sources = {split: [{key: row[key] for key in ("id", "source_text", "source_sha256", "family_group") if key in row}
                       for row in rows] for split, rows in corpus["splits"].items()}
    inspection = producer.verify_manifest(manifest["native_production_manifest"], sources=sources)
    require(native_manifest["pilot_unique_sources"] is None, "full native producer cohort required")
    require(manifest["representations"] == native_manifest["representations"]
        and manifest["unavailable_representations"] == native_manifest["unavailable_representations"],
        "training manifest differs from authenticated native production representations")
    representations = manifest["representations"]
    require(type(representations) is dict and set(representations) == {"trained384", "native768"},
            "pilot requires exactly published trained384 and native768; learned8 source stage is unavailable")
    require(type(manifest["unavailable_representations"]) is dict and manifest["unavailable_representations"],
            "unsupported learned8 input lineage must be recorded")
    require(type(manifest["producer_pins"]) is dict and manifest["producer_pins"], "context producer pins required")
    for source, wanted in manifest["producer_pins"].items():
        require(sha(source) == wanted, "context producer source drift")
    require(all(manifest["producer_pins"].get(ref["path"]) == ref["sha256"] for ref in native_manifest["implementation_files"]),
            "training manifest omits an authenticated native producer pin")
    contexts, contracts, refs = {}, {}, [manifest_ref, manifest["corpus"], manifest["native_production_manifest"], *native_manifest["implementation_files"]]
    train_hash = digest([{key: row[key] for key in ("id", "source_sha256")} for row in corpus["splits"]["train"]])
    for name in DIMENSIONS:
        if name not in representations:
            continue
        item = representations[name]
        require(set(item) == {"dimension", "representation_id", "producer_sha256", "contexts", "lineage_artifacts"}
            and item["dimension"] == DIMENSIONS[name], "closed dimensional representation required")
        require(type(item["representation_id"]) is str and item["representation_id"].strip()
            and type(item["producer_sha256"]) is str and len(item["producer_sha256"]) == 64,
            "producer/representation identity required")
        require(type(item["lineage_artifacts"]) is list and item["lineage_artifacts"], "native lineage artifacts required")
        for ref in item["lineage_artifacts"]:
            require(file_ref(ref["path"]) == ref, "context lineage bytes differ")
            refs.append(ref)
        if set(item["contexts"]) == set(SPLITS):
            panels = {split: read_ref(item["contexts"][split]) for split in SPLITS}
            refs.extend(item["contexts"].values())
        else:
            panels = read_ref(item["contexts"])
            refs.append(item["contexts"])
        require(set(panels) == set(SPLITS), "complete context split inventory required")
        for split in SPLITS:
            verify_context_rows(corpus["splits"][split], panels[split], dimension=item["dimension"])
        contexts[name] = panels
        contracts[name] = {"dimension": item["dimension"], "representation_id": item["representation_id"],
            "producer_sha256": item["producer_sha256"], "training_index_sha256": train_hash}
    return manifest, contexts, contracts, refs, inspection


def training_rows(rows, contexts=None):
    if contexts is not None:
        require(len(rows) == len(contexts), "training context coverage differs")
    result = []
    for index, row in enumerate(rows):
        item = {key: row[key] for key in ("id", "source_text", "canonical_ir")}
        if contexts is not None:
            context = contexts[index]
            require(context["id"] == row["id"] and context["source_sha256"] == row["source_sha256"], "training source-context differs")
            item["latent"] = context["context"]
        result.append(item)
    return result


def cross_family_contexts(rows, contexts):
    require(len(rows) == len(contexts) and len(rows) > 1, "swapping needs complete multi-source context")
    source_by_id = {row["id"]: row for row in rows}
    context_by_id = {row["id"]: row for row in contexts}
    require(len(source_by_id) == len(context_by_id) == len(rows) and set(source_by_id) == set(context_by_id), "swap identity inventory differs")
    order = sorted(rows, key=lambda row: (row["family_group"], row["source_sha256"], row["id"]))
    mapping = None
    for offset in range(1, len(order)):
        pairs = [(row, order[(index + offset) % len(order)]) for index, row in enumerate(order)]
        if all(a["family_group"] != b["family_group"] and a["source_sha256"] != b["source_sha256"] for a, b in pairs):
            mapping = {a["id"]: b for a, b in pairs}
            break
    require(mapping is not None, "no source-disjoint cross-family permutation exists")
    result = []
    for row in rows:
        donor = mapping[row["id"]]
        context = context_by_id[donor["id"]]
        require(context["source_sha256"] == donor["source_sha256"], "donor context source differs")
        result.append({"id": row["id"], "source_sha256": row["source_sha256"], "context": context["context"],
            "context_sha256": context["context_sha256"], "donor_id": donor["id"], "donor_source_sha256": donor["source_sha256"],
            "receiving_family_group": row["family_group"], "donor_family_group": donor["family_group"],
            "donor_native_stage_receipt": deepcopy(context["native_stage_receipt"]),
            "context_provenance": "donor_source_native_stage; receiving_source_remains_original"})
    return result


def generate(decoder, rows, contexts=None, *, dimension=0, control="source"):
    """Only exact source strings and explicitly bound context vectors enter inference."""
    require(control in ("source", "disabled", "zero", "cross_family"), "unknown inference control")
    require((dimension == 0 and contexts is None and control == "source") or
        (dimension in (8, 384, 768) and contexts is not None and len(rows) == len(contexts)), "inference dimension/context mismatch")
    vectors, receipts = [], []
    for index, row in enumerate(rows):
        if contexts is None:
            continue
        context = contexts[index]
        require(context["id"] == row["id"] and context["source_sha256"] == row["source_sha256"]
            and len(context["context"]) == dimension and digest(context["context"]) == context["context_sha256"],
            "generation source/context binding differs")
        vectors.append(context["context"])
        receipts.append({"id": row["id"], "source_sha256": row["source_sha256"],
            "supplied_context_sha256": context["context_sha256"],
            "effective_context_sha256": digest([0.] * dimension) if control == "zero" else context["context_sha256"],
            "context_disabled": control == "disabled", "donor_id": context.get("donor_id"),
            "donor_source_sha256": context.get("donor_source_sha256"), "target_access": False})
    reports, predictions = [], []
    for start in range(0, len(rows), 128):
        report = decoder.decode_formal_logic([row["source_text"] for row in rows[start:start + 128]],
            None if dimension == 0 else vectors[start:start + 128],
            latent_ablation=control if control in ("disabled", "zero") else "none")
        require(report["target_access"] is False and report["teacher_forcing"] is False, "free inference only")
        reports.append(report)
        predictions.extend(report["rows"])
    require(len(predictions) == len(rows), "prediction coverage differs")
    return {"reports": reports, "rows": predictions, "control": control, "dimension": dimension,
        "control_receipts": receipts, "generation_inputs_contained_references": False}


def prediction_payload(generation):
    return [{key: row[key] for key in ("source_sha256", "status", "canonical_ir", "reason", "span_diagnostics") if key in row}
            for row in generation["rows"]]


def fit_branch(job):
    import torch
    torch.set_num_threads(1)
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_continuation as old
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_dimensions as new
    outer = old.load_checkpoint(job["parent"]["path"], expected_sha256=job["parent"]["sha256"])
    parent = outer["base_checkpoint"]
    train = training_rows(job["train"], job["train_context"])
    tuning = training_rows(job["tuning"], job["tuning_context"])
    checkpoint = new.build_checkpoint(parent, train, tuning, latent_dimension=job["dimension"],
        latent_enabled=job["dimension"] > 0, seed=job["seed"], context_contract=job["contract"], learning_rate=.001, batch_size=12)
    initial, common = new.initial_model_digest(checkpoint), new.initial_source_model_digest(checkpoint)
    original_context = [{"id": row["id"], "source_sha256": row["source_sha256"], "context": row["embedding"],
        "context_sha256": digest(row["embedding"])} for row in job["tuning"]]
    parent_generation = generate(old.SpanContinuationDecoder(outer), job["tuning"], original_context, dimension=384, control="disabled")
    initial_generation = generate(new.DimensionalSpanDecoder(checkpoint), job["tuning"], job["tuning_context"], dimension=job["dimension"])
    require(prediction_payload(initial_generation) == prediction_payload(parent_generation), "initial source predictions or logits differ from parent")
    folder = Path(job["directory"])
    parity = write(folder / "initialization-parity.json", {"scope": "all_tuning_sources_before_any_update_no_target_access",
        "count": len(job["tuning"]), "source_model_sha256": common, "parent": job["parent"],
        "parent_predictions": parent_generation, "initial_predictions": initial_generation, "exact_source_predictions_and_logits": True})
    stages = []
    for ordinal in (1, 2):
        result = new.train_decoder(checkpoint, train, tuning, max_steps=job["stage_steps"], max_seconds=300)
        checkpoint = result["checkpoint"]
        steps = new.optimizer_steps(checkpoint)
        require(steps == ordinal * job["stage_steps"], "complete equal training stage budgets required")
        checkpoint_ref = new.save_checkpoint(checkpoint, folder / f"checkpoint-{steps}.json")
        report_ref = write(folder / f"training-{steps}.json", result["report"])
        generation = generate(new.DimensionalSpanDecoder(checkpoint), job["tuning"], job["tuning_context"], dimension=job["dimension"])
        metrics = score(generation["rows"], job["tuning"], job["tuning"])
        tuning_ref = write(folder / f"tuning-{steps}.json", {"generation": generation, "metrics": metrics})
        stages.append({"new_optimizer_steps": steps, "checkpoint": checkpoint_ref, "training_report": report_ref,
            "tuning_evaluation": tuning_ref, "tuning_exact": metrics["exact"], "tuning_count": metrics["count"]})
    selected = select_stage(stages)
    selection = {"name": folder.name, "arm": job["arm"], "seed": job["seed"], "dimension": job["dimension"],
        "latent_enabled": job["dimension"] > 0, "context_contract": job["contract"], "source_parent_wrapper": job["parent"],
        "source_parent_base_sha256": digest(parent),
        "historical_parent_optimizer_updates": outer["source_parent_optimizer_steps"] + parent["progress"]["optimizer_steps"],
        "initial_model_sha256": initial, "initial_source_model_sha256": common, "initialization_parity": parity,
        "stages": stages, "total_new_training_steps": 2 * job["stage_steps"], "selected_new_steps": selected["new_optimizer_steps"],
        "checkpoint": selected["checkpoint"], "selection_tuning_exact": selected["tuning_exact"], **FALSE}
    write(folder / "selection.json", selection)
    return selection


def run(args):
    import torch
    torch.set_num_threads(1)
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_continuation as old
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_dimensions as new
    require(args.stage_steps == 400 and 1 <= args.workers <= 3, "pilot uses exactly two400-step stages and1..3workers")
    corpus = read(args.corpus)
    verify_source_inputs(corpus)
    manifest, contexts, contracts, input_refs, context_inspection = load_context_manifest(args.context_manifest, args.context_manifest_sha256, corpus)
    require(manifest["corpus"] == file_ref(args.corpus), "corpus reference path differs")
    require(sha(args.challenge_targets) == corpus["sealed_targets"]["sha256"], "previously exposed target bytes differ")
    splits = corpus["splits"]
    previous_ref = file_ref(Path(args.parent_run) / "summary.json")
    previous = read_ref(previous_ref)
    parents = {}
    for seed in SEEDS:
        candidates = [item for item in previous["runs"] if item["name"] == f"source_only-{seed}"]
        require(len(candidates) == 1, "one matched source-only parent per seed required")
        ref = candidates[0]["checkpoint"]
        checkpoint = old.load_checkpoint(ref["path"], expected_sha256=ref["sha256"])
        require(checkpoint["base_checkpoint"]["config"]["seed"] == seed
            and checkpoint["base_checkpoint"]["config"]["latent_enabled"] is False, "trained source-only parent required")
        parents[str(seed)] = ref
    producer_pins = {str(Path(module.__file__).resolve()): sha(module.__file__) for module in (old, new)}
    for function in (score, write, select_stage, verify_source_inputs):
        path = Path(sys.modules[function.__module__].__file__).resolve()
        producer_pins[str(path)] = sha(path)
    producer_pins[str(Path(__file__).resolve())] = sha(__file__)
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    inspection_ref = write(output / "native-context-inspection.json", context_inspection)
    arms = {"source_only": 0, **{name: DIMENSIONS[name] for name in DIMENSIONS if name in contexts}}
    plan = {"schema": SCHEMA, "corpus": file_ref(args.corpus), "targets": file_ref(args.challenge_targets),
        "context_manifest": file_ref(args.context_manifest), "input_closure": input_refs,
        "native_context_inspection": inspection_ref,
        "parents": parents, "parent_run": previous_ref, "producer_pins": producer_pins, "arms": arms,
        "seeds": list(SEEDS), "counts": {split: len(rows) for split, rows in splits.items()}, "stage_steps":400, "stages":2,
        "selection": "maximum tuning exact, earliest stage on tie; retain all seeds",
        "controls": ["source", "disabled", "zero", "cross_family"],
        "initialization": "same_seed_common_source_tensors_copied; dimension_specific_adapter_initialized; zero_context_output_layer",
        "corpus_scope": "previously_exposed_authored_regression; challenge withheld only during this run",
        "family_scope": "one source-copy O/P/F rule; no generalized multi-rule or statutory fidelity claim",
        "unavailable_representations": manifest["unavailable_representations"],
        "training_index_hash_scope": "training source membership only; no retrieval index", **FALSE}
    plan_ref = write(output / "plan.json", plan)
    write(output / "prepared-inputs.json", {split: [{key: row[key] for key in ("id", "source_text", "source_sha256", "family_group") if key in row}
        for row in rows] for split, rows in splits.items()})
    jobs = []
    for seed in SEEDS:
        for arm, dimension in arms.items():
            folder = output / f"{arm}-{seed}"; folder.mkdir()
            jobs.append({"directory": str(folder), "seed": seed, "parent": parents[str(seed)], "arm": arm,
                "dimension": dimension, "contract": contracts.get(arm), "train": splits["train"], "tuning": splits["tuning"],
                "train_context": contexts[arm]["train"] if dimension else None,
                "tuning_context": contexts[arm]["tuning"] if dimension else None, "stage_steps": args.stage_steps})
    selected = []
    with ProcessPoolExecutor(max_workers=args.workers, mp_context=multiprocessing.get_context("spawn")) as pool:
        for future in as_completed([pool.submit(fit_branch, job) for job in jobs]):
            item = future.result(); selected.append(item)
            print(json.dumps({"phase": "selected", "name": item["name"], "steps": item["selected_new_steps"], "tuning_exact": item["selection_tuning_exact"]}), flush=True)
    selected.sort(key=lambda item: (item["seed"], list(arms).index(item["arm"])))
    for seed in SEEDS:
        require(len({item["initial_source_model_sha256"] for item in selected if item["seed"] == seed}) == 1,
                "same-seed initial common source tensors differ")
    heads_ref = write(output / "frozen-heads.json", selected)
    items = selected + [{"name": f"parent_source-{seed}", "arm": "parent_source", "seed": seed,
        "dimension":384, "checkpoint":parents[str(seed)], "latent_enabled":False} for seed in SEEDS]
    generated, generation_refs = {}, {}

    def load(item):
        module, cls = (old, old.SpanContinuationDecoder) if item["arm"] == "parent_source" else (new, new.DimensionalSpanDecoder)
        return cls(module.load_checkpoint(item["checkpoint"]["path"], expected_sha256=item["checkpoint"]["sha256"]))

    # First freeze every normal source-conditioned panel, including unchanged parents.
    for item in items:
        folder = output / item["name"]; folder.mkdir(exist_ok=True)
        decoder = load(item)
        panels, refs = {}, {}
        for split in ("tuning", "challenge", "oov"):
            context = contexts[item["arm"]][split] if item["latent_enabled"] else None
            dimension = item["dimension"]
            if item["arm"] == "parent_source":
                context = [{"id": row["id"], "source_sha256":row["source_sha256"], "context":row["embedding"],
                    "context_sha256":digest(row["embedding"])} for row in splits[split]]
            result = generate(decoder, splits[split], context, dimension=dimension)
            panels[split] = result
            refs[split] = write(folder / f"{split}-generation.json", result)
        generated[item["name"]], generation_refs[item["name"]] = panels, refs
        print(json.dumps({"phase":"normal_generated", "name":item["name"]}), flush=True)
    normal_ref = write(output / "normal-generation-frozen.json", generation_refs)
    # Now execute every predeclared intervention without reference access or selection.
    for item in selected:
        if not item["latent_enabled"]:
            continue
        decoder, normal_context = load(item), contexts[item["arm"]]["challenge"]
        swapped = cross_family_contexts(splits["challenge"], normal_context)
        folder = output / item["name"]
        write(folder / "cross-family-contexts.json", swapped)
        for control in ("disabled", "zero", "cross_family"):
            panel = f"challenge_{control}_context"
            result = generate(decoder, splits["challenge"], swapped if control == "cross_family" else normal_context,
                              dimension=item["dimension"], control=control)
            generated[item["name"]][panel] = result
            generation_refs[item["name"]][panel] = write(folder / f"{panel}-generation.json", result)
    generation_ref = write(output / "generation-frozen.json", {"schema":"legal-open-vocabulary-generation-freeze/v1",
        "frozen_heads":heads_ref, "normal_generation_freeze":normal_ref, "files":generation_refs,
        "all_generation_complete":True, "challenge_targets_read_in_this_execution":False, "independent_holdout":False})
    # Authored historical challenge references are opened only after the final freeze.
    require(sha(args.challenge_targets) == plan["targets"]["sha256"], "reference bytes changed")
    payload = read(args.challenge_targets)
    targets = {row["id"]:row for row in payload["targets"]}
    require(len(targets) == len(payload["targets"]) == len(splits["challenge"]), "reference coverage differs")
    references = []
    for row in splits["challenge"]:
        target = targets[row["id"]]
        require(target["source_sha256"] == row["source_sha256"] and digest(target["canonical_ir"]) ==
            target["canonical_target_sha256"] == row["canonical_target_sha256"], "challenge reference source binding differs")
        references.append({"id":row["id"], "source_text":row["source_text"], "canonical_ir":target["canonical_ir"]})
    runs = []
    for item in items:
        scores = {}
        for panel, generation in generated[item["name"]].items():
            if panel == "oov":
                counts = Counter(row["status"] for row in generation["rows"])
                metrics = {"count":len(generation["rows"]), "decoded":counts["decoded"], "abstained":counts["abstained"], "semantic_accuracy":None}
                name = "dataset-transfer"
            else:
                challenge = panel.startswith("challenge")
                metrics = score(generation["rows"], splits["challenge" if challenge else "tuning"], references if challenge else splits["tuning"])
                name = panel
            write(output / item["name"] / f"{name}.json", {"generation":generation, "metrics":metrics})
            scores["dataset_transfer" if panel == "oov" else panel] = {key:value for key,value in metrics.items() if key != "rows"}
        runs.append({**item, "scores":scores, **FALSE})
        print(json.dumps({"phase":"scored", "name":item["name"], "challenge_exact":scores["challenge"]["exact"]}), flush=True)
    for path, expected in {**producer_pins, **manifest["producer_pins"]}.items():
        require(sha(path) == expected, "producer changed during experiment")
    for ref in [*input_refs, plan["targets"], previous_ref, *[ref for panels in generation_refs.values() for ref in panels.values()]]:
        require(sha(ref["path"]) == ref["sha256"], "input or generation changed during experiment")
    report = {"schema":SCHEMA, "plan":plan_ref, "frozen_heads":heads_ref, "generation_frozen":generation_ref, "runs":runs,
        "challenge_targets_read_after_all_training_selection_and_generation":True,
        "evaluation_cohort_previously_exposed":True, "representation_is_native_source_not_retrieved_profile":True, **FALSE}
    write(output / "summary.json", report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for field in ("corpus", "challenge-targets", "parent-run", "context-manifest", "context-manifest-sha256", "output"):
        parser.add_argument("--" + field, required=True)
    parser.add_argument("--stage-steps", type=int, default=400)
    parser.add_argument("--workers", type=int, default=3)
    run(parser.parse_args())
