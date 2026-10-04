"""Independently recount frozen unmasked generations on an exposed legal cohort.

This verifies immutable inputs and self-generated prefix receipts, reconstructs
the admitted historical references, and replays the original donor through its
checkpoint-pinned numerical factory. It creates no independent holdout or gold.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
SPEC = importlib.util.spec_from_file_location("_source_control_audit_base", Path(__file__).with_name("evaluate_gte_native_source_controls.py"))
base = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(base)
require, digest, read_ref, file_ref = base.require, base.digest, base.read_ref, base.file_ref
FACETS = ("modality", "actor", "action", "object", "conditions", "exceptions", "temporal")


def expected_intervention(rows, index, control, *, donor):
    """Separate implementation of the frozen source, zero, and cyclic controls."""
    require(control in ("source", "zero", "cross_source"), "unknown source control")
    key = "generation_input" if donor else "native_generation_input"
    source = rows[index]
    original = source[key]["input_vector"]
    origin = None
    if control == "source":
        effective = list(original)
    elif control == "zero":
        effective = [0.] * len(original)
    else:
        ordered = sorted(rows, key=lambda row: (row["source_sha256"], row["id"]))
        pos = next(i for i, row in enumerate(ordered) if row["id"] == source["id"])
        other = ordered[(pos + 1) % len(ordered)]
        require(other["source_sha256"] != source["source_sha256"], "source permutation repeats source text")
        effective = list(other[key]["input_vector"])
        origin = {"id": other["id"], "source_sha256": other["source_sha256"], "input_sha256": other[key]["input_sha256"]}
    return effective, {"control": control, "receiving_id": source["id"],
        "receiving_source_sha256": source["source_sha256"], "original_input_sha256": digest(original),
        "effective_input_sha256": digest(effective), "donor": origin,
        "provenance": "original_donor_source_coordinates" if donor else "native_source_receipt",
        "zero_input_is_disabled_context": False, "target_access": False}


def first_difference(generated, reference, vocabulary):
    for index in range(max(len(generated), len(reference))):
        actual = generated[index] if index < len(generated) else None
        wanted = reference[index] if index < len(reference) else None
        if actual != wanted:
            return {"token_index_including_bos": index,
                    "generated_token": vocabulary[actual] if actual is not None else None,
                    "reference_token": vocabulary[wanted] if wanted is not None else None}
    return None


def panel_statistics(rows):
    """Every invalid row stays in all facet denominators."""
    require(rows and len({row["id"] for row in rows}) == len(rows), "unique nonempty panel rows required")
    syntactic = [row for row in rows if row["score"]["syntax_valid"]]
    tokens = Counter(row["score"]["generated_ids_sha256"] for row in rows)
    targets = Counter(row["score"]["decoded_target_sha256"] for row in syntactic)
    return {"count": len(rows), "syntax_valid": len(syntactic),
        "exact_target_match": sum(row["score"]["exact_target_match"] for row in rows),
        "terminated": sum(row["score"]["terminated"] for row in rows),
        "truncated": sum(row["score"]["truncated"] for row in rows),
        "invalid_generation": len(rows) - len(syntactic), "unique_generated_token_sequences": len(tokens),
        "most_common_generated_sequence_count": max(tokens.values()), "unique_syntax_valid_targets": len(targets),
        "most_common_valid_target_count": max(targets.values(), default=0),
        "facet_matches_over_all_rows": {field: sum(row["score"]["syntax_valid"] and
            row["score"]["decoded_target"]["rules"][0][field] == row["reference"]["target"]["rules"][0][field]
            for row in rows) for field in FACETS},
        "invalid_reasons": dict(Counter(row["score"]["reason"] for row in rows if not row["score"]["syntax_valid"])),
        "first_divergence_tokens": dict(Counter(row["first_difference"]["reference_token"]
            for row in rows if row["first_difference"] is not None))}


def admit(plan):
    config = read_ref(plan["configuration"])
    for ref in plan["closure"]:
        require(file_ref(ref["path"]) == ref, "baseline closure changed")
    original, _ = base.runtime_receipt(config["original_runtime"], expected_start="original_initialization")
    aligned, _ = base.runtime_receipt(config["aligned_runtime"], expected_start="authenticated_aligned_generation")
    training = base.module("run_gte_aligned_interface_training", Path(__file__).parent)
    native = training._native_cli()
    reader = native._helper("gte_worker_contract")
    parent = base.module("gte_source_evaluation_parent", Path(__file__).parent).admit_training_parent(
        read_ref(aligned["manifest"]), aligned["manifest"], root=Path(config["workspace_root"]), reader=reader, training_cli=training)
    base.admit_original(original, parent, reader=reader, native=native, training=training)
    p = parent["payloads"]
    source = native._helper("gte_decoder_source_evaluation")
    evaluation = source.prepare_source_evaluation(p["initialization"], p["native_batch"], p["batch"], p["replay"],
        expected_donor_pins=p["donor_pins"], max_primary_rows=60, max_auxiliary_rows=2)
    primary = read_ref(config["primary_checkpoint"])
    require(config["primary_checkpoint"]["sha256"] == p["donor_pins"]["teacher384_checkpoint_sha256"], "primary donor binding differs")
    return {"source": source, "evaluation": evaluation, "payloads": p, "native": native,
            "config": config, "primary": primary, "runtime_receipts": [original, aligned]}


def donor_boundary_replay(admitted, sources, rows):
    """Replay pinned numerical code without bypassing a full-runtime refusal."""
    from ipfs_datasets_py.logic.formalization.autoencoder import source_training_v2 as original
    import torch
    torch.set_num_threads(1)
    checkpoint = admitted["primary"]
    expected_implementation, actual_implementation = checkpoint["implementation"], original._implementation()
    discrepancies = []

    def changes(expected, actual, path=""):
        if isinstance(expected, dict) and isinstance(actual, dict):
            for key in sorted(set(expected) | set(actual)):
                changes(expected.get(key), actual.get(key), path + "." + key)
        elif expected != actual:
            discrepancies.append({"field": path.lstrip("."), "pinned": expected, "current": actual})

    changes(expected_implementation, actual_implementation)
    try:
        runtime = original.Runtime(checkpoint)
        full_runtime = {"admitted": True, "refusal": None, "implementation_differences": []}
        model = runtime.model
    except ValueError as error:
        require(str(error) == "implementation pins differ" and discrepancies
            and {row["field"] for row in discrepancies} == {
                "native.dependencies.ipfs_datasets_py.logic.ui_ux_ir.decoder"},
            "unexpected original runtime refusal; numerical boundary replay blocked")
        full_runtime = {"admitted": False, "refusal": str(error), "implementation_differences": discrepancies,
            "check_bypassed_or_checkpoint_modified": False}
        # The original source runtime and numerical factory retain their exact
        # checkpoint pins. The changed UI validator is not called by this narrow
        # numerical replay; the full runtime's refusal remains in the result.
        require(expected_implementation["runtime_sha256"] == file_ref(Path(original.__file__))["sha256"]
            and expected_implementation["numerical"]["files"]["modal_latent_formula.py"] ==
                file_ref(Path(original.numerical.__file__))["sha256"], "required original numerical code changed")
        model = original.numerical._model({"dimension": 384}, checkpoint["codec"], checkpoint["config"])
        tensors = {name: torch.tensor(value, dtype=torch.float32) for name, value in checkpoint["model_state"].items()}
        require(len(tensors) == 13 and digest({name: value.tolist() for name, value in tensors.items()}) == checkpoint["weights_sha256"],
                "original float32 tensor identity differs")
        model.load_state_dict(tensors, strict=True)
        model.eval()
    transform = checkpoint["input_transform"]
    by_id = {row["id"]: row for row in rows}
    replayed, steps = 0, 0
    with torch.inference_mode():
        for source in sources:
            row = by_id[source["id"]]
            generation = row["generation"]
            data = torch.tensor([source["generation_input"]["input_vector"]], dtype=torch.float32)
            data = (data - torch.tensor(transform["mean"], dtype=torch.float32)) / transform["scale"]
            ids = [1]
            for expected_step in generation["steps"]:
                projected, logits = model(data, torch.tensor([ids], dtype=torch.long))
                final = logits[0, -1]
                token = int(final.argmax())
                require(digest(final.tolist()) == expected_step["raw_logits_sha256"]
                        and token == expected_step["next_token_id"], "original V2 raw-logit/argmax replay differs")
                ids.append(token)
                steps += 1
            require(ids == generation["generated_ids"], "original runtime generated token sequence differs")
            replayed += 1
    return {"status": "exact_checkpoint_pinned_numerical_factory_replay", "primary_rows_replayed": replayed,
        "raw_logit_steps_replayed": steps, "original_runtime": file_ref(Path(original.__file__)),
        "original_numerical_factory": file_ref(Path(original.numerical.__file__)),
        "full_historical_runtime": full_runtime,
        "checkpoint_schema": checkpoint["schema"], "checkpoint": admitted["config"]["primary_checkpoint"],
        "input_stage": "original_cached_normalized_GTE384_embedding_before_learned_residual_projection",
        "saved_input_transform_applied": True,
        "not_the_published_sparse_legal_ir_package_head": True,
        "original_runtime_declared_input": "source_embedding_384",
        "all_five_variant_numerical_replay_performed": False}


def analyze(directory):
    directory = Path(directory).resolve()
    summary_ref = file_ref(directory / "summary.json")
    summary = read_ref(summary_ref)
    require(summary["schema"] == "gte-native-source-controls-summary/v1"
        and summary["status"] == "completed_exposed_regression_unqualified"
        and summary["independent_holdout"] is False and summary["proof_authority"] is False,
        "completed exposed unqualified source-control summary required")
    frozen = read_ref(summary["generation_freeze"])
    require(frozen["schema"] == "gte-native-source-controls-frozen/v1" and frozen["all_variants_completed"] is True
        and frozen["generation_count"] == 930 and frozen["scoring_started"] is False,
        "complete 930-row pre-score freeze required")
    plan, inputs = read_ref(frozen["plan"]), read_ref(frozen["inputs"])
    require(plan["inputs"] == frozen["inputs"] and plan["variants"] == list(base.VARIANTS)
        and plan["controls"] == list(base.CONTROLS) and plan["heads"] == list(base.HEADS)
        and plan["all_generation_frozen_before_scoring"] is True and plan["reference_prefix_used"] is False,
        "fixed all-variant all-control plan differs")
    require(inputs["target_access"] is False and inputs["contains_references"] is False
        and set(inputs["heads"]) == set(base.HEADS), "source-only input inventory required")
    expected_keys = {"id", "source_text", "source_sha256", "evaluation_role", "generation_input", "native_generation_input", "native_receipt_sha256"}
    for head in base.HEADS:
        rows = inputs["heads"][head]
        require(len(rows) == (60 if head == "primary384" else 2), "head cohort size differs")
        require(len({row["id"] for row in rows}) == len(rows), "duplicate source identity")
        for row in rows:
            require(set(row) == expected_keys and hashlib.sha256(row["source_text"].encode()).hexdigest() == row["source_sha256"],
                    "source-only row contains reference fields or source hash differs")
            for name, width in (("generation_input", 384 if head == "primary384" else 8), ("native_generation_input", 768)):
                item = row[name]
                require(item["input_dimension"] == width and len(item["input_vector"]) == width
                    and digest(item["input_vector"]) == item["input_sha256"], "source coordinate binding differs")
    generation = base.module("gte_decoder_source_generation")
    panels, row_index, refs = {}, {}, frozen["generation_files"]
    require(len(refs) == 15 and len({ref["path"] for ref in refs}) == 15, "fifteen distinct generation files required")
    for ref in refs:
        panel = read_ref(ref)
        key = panel["variant"], panel["control"]
        require(key not in panels and key[0] in base.VARIANTS and key[1] in base.CONTROLS
            and panel["references_used_for_generation"] is False and panel["reference_prefix_used"] is False,
            "generation panel inventory or reference-use declaration differs")
        expected = {(head, row["id"]): row for head in base.HEADS for row in inputs["heads"][head]}
        require(len(panel["rows"]) == len(expected) == 62, "generation row count differs")
        seen = set()
        for row in panel["rows"]:
            identity = row["head"], row["id"]
            require(identity in expected and identity not in seen and row["variant"] == key[0], "unknown or repeated generated identity")
            seen.add(identity)
            source = expected[identity]
            require(all(row[field] == source[field] for field in ("source_text", "source_sha256", "evaluation_role")), "generation source differs")
            sources = inputs["heads"][row["head"]]
            index = next(i for i, candidate in enumerate(sources) if candidate["id"] == row["id"])
            vector, intervention = expected_intervention(sources, index, key[1], donor=key[0] == "original_donor")
            require(row["intervention"] == intervention, "source intervention receipt differs")
            result = row["generation"]
            generation.inspect_source_only_generation(result)
            numerical = [struct.unpack("f", struct.pack("f", x))[0] for x in vector]
            require(result["input_vector_sha256"] == digest(vector) and result["numerical_input_sha256"] == digest(numerical)
                and result["head"] == row["head"] and result["input_dimension"] == len(vector), "generation numerical input differs")
            require(all(result[field] == plan["budgets"][row["head"]][field] for field in ("max_new_tokens", "inherited_max_target_tokens")),
                    "generation budget differs from frozen plan")
            row_index[(*key, *identity)] = (row, ref)
        panels[key] = panel
    require(len(row_index) == 930, "complete generation coverage required")
    # Only after every generation and input receipt is checked do we reconstruct scoring references.
    admitted = admit(plan)
    ev, scorer, init = admitted["evaluation"], admitted["source"], admitted["payloads"]["initialization"]
    for head in base.HEADS:
        rebuilt = [{key: row[key] for key in expected_keys} for row in ev["heads"][head]["rows"]]
        require(rebuilt == inputs["heads"][head], "admitted historical source/native input lineage differs")
    scores = read_ref(summary["scores"])
    require(scores["generation_freeze"] == summary["generation_freeze"] and len(scores["rows"]) == 930,
            "score inventory or freeze binding differs")
    evaluated, used, representability = [], set(), {}
    for head in base.HEADS:
        codec = init["primary" if head == "primary384" else "legacy8"]["codec"]
        references = ev["heads"][head]["rows"]
        for row in references:
            ref = row["reference"]
            require(scorer._BATCH._decode(ref["token_ids"], codec["target_vocabulary"], head) == ref["target"], "reference codec roundtrip differs")
        representability[head] = {"reference_count": len(references), "exact_codec_roundtrips": len(references),
            "all_reference_tokens_in_inherited_vocabulary": True, "all_reference_lengths_within_fixed_budget": True}
    for stored in scores["rows"]:
        identity = stored["variant"], stored["control"], stored["head"], stored["id"]
        require(identity in row_index and identity not in used, "unknown or repeated scored identity")
        used.add(identity)
        row, ref = row_index[identity]
        require(stored["generation_file"] == ref and stored["generation_sha256"] == digest(row["generation"])
            and all(stored[field] == row[field] for field in ("source_text", "source_sha256", "evaluation_role")), "score-to-generation binding differs")
        head = row["head"]
        reference = next(r["reference"] for r in ev["heads"][head]["rows"] if r["id"] == row["id"])
        codec = init["primary" if head == "primary384" else "legacy8"]["codec"]
        raw = {key: row["generation"][key] for key in ("generated_ids", "terminated", "truncated")}
        actual = scorer.score_generation(raw, reference, codec, head)
        require(actual == stored["score"], "recomputed generation score differs")
        require(actual["exact_target_match"] == (actual["decoded_target"] == reference["target"]), "direct exact-target comparison differs")
        evaluated.append({**stored, "reference": reference,
            "first_difference": first_difference(raw["generated_ids"], reference["token_ids"], codec["target_vocabulary"])})
    metrics = []
    for variant in base.VARIANTS:
        for control in base.CONTROLS:
            for head in base.HEADS:
                selected = [row for row in evaluated if (row["variant"], row["control"], row["head"]) == (variant, control, head)]
                result = panel_statistics(selected)
                source_rows = {row["id"]: row for row in evaluated if row["variant"] == variant and row["control"] == "source" and row["head"] == head}
                result["changed_generated_token_sequences"] = sum(row["score"]["generated_ids_sha256"] != source_rows[row["id"]]["score"]["generated_ids_sha256"] for row in selected)
                result.update(variant=variant, control=control, head=head)
                producer = next(row for row in summary["panels"] if (row["variant"], row["control"], row["head"]) == (variant, control, head))
                require(all(result[key] == value for key, value in producer.items()), "producer aggregate differs")
                metrics.append(result)
    boundary = donor_boundary_replay(admitted, inputs["heads"]["primary384"],
        [row for row in panels[("original_donor", "source")]["rows"] if row["head"] == "primary384"])
    examples = [{"variant": row["variant"], "head": row["head"], "id": row["id"], "source_text": row["source_text"],
        "reference": row["reference"]["target"], "decoded_target": row["score"]["decoded_target"],
        "syntax_valid": row["score"]["syntax_valid"], "reason": row["score"]["reason"], "first_difference": row["first_difference"]}
        for row in evaluated if row["control"] == "source" and row["id"] == inputs["heads"][row["head"]][0]["id"]]
    invalid_examples = []
    for variant in base.VARIANTS:
        bad = next((row for row in evaluated if row["variant"] == variant and row["control"] == "source" and not row["score"]["syntax_valid"]), None)
        if bad:
            gen, _ = row_index[(variant, "source", bad["head"], bad["id"])]
            vocabulary = init["primary" if bad["head"] == "primary384" else "legacy8"]["codec"]["target_vocabulary"]
            invalid_examples.append({"variant": variant, "id": bad["id"], "source_text": bad["source_text"], "reason": bad["score"]["reason"],
                "generated_tokens": [vocabulary[token] for token in gen["generation"]["generated_ids"]]})
    losses = []
    for label, runtime in zip(("original", "aligned"), admitted["runtime_receipts"]):
        report = read_ref(runtime["training_report"])
        losses.append({"start": label, "training_report": runtime["training_report"], "optimizer_steps": runtime["optimizer_steps"],
            "before_teacher_forced_loss": report["before"]["loss"], "after_teacher_forced_loss": report["after"]["loss"],
            "head_losses": {head: {"before": report["before"]["heads"][head]["loss"], "after": report["after"]["heads"][head]["loss"],
                "rows": report["before"]["heads"][head]["row_count"]} for head in base.HEADS},
            "free_generation_accuracy_inferred_from_loss": False})
    return {"schema": "gte-native-source-controls-independent-analysis/v1", "status": "verified_exposed_regression_unqualified",
        "summary": summary_ref, "generation_freeze": summary["generation_freeze"], "inputs": frozen["inputs"], "plan": frozen["plan"],
        "scores": summary["scores"], "analysis_implementation": file_ref(Path(__file__)), "runner": file_ref(Path(base.__file__)),
        "generation_files_verified": 15, "generation_rows_verified": 930, "scores_recomputed": 930,
        "generated_prefix_receipts_verified": 930, "source_and_intervention_receipts_verified": 930,
        "pre_score_freeze": {"declared_by_frozen_runner": True, "hash_bound_complete_inventory": True,
            "scoring_started_in_freeze": False, "captured_at_utc": frozen["captured_at_utc"],
            "independent_wall_clock_attestation": False},
        "reference_codec_representability": representability, "donor_conditioning_boundary": boundary,
        "panels": metrics, "training_losses": losses, "source_examples": examples, "invalid_source_examples": invalid_examples,
        "verification_limits": ["All 60 primary examples are previously exposed original validation data; the two legacy examples are training diagnostics.",
            "Receipt checks authenticate the saved byte/metadata chain. Original primary source generations also received a complete numerical replay; other variants did not receive a numerical replay in this analyzer.",
            "Syntactic validity is inherited codec validity, not family equivalence, Lake compilation, or statutory semantic accuracy.",
            "Training loss averages teacher-forced tokens and does not establish exact free-generation accuracy."],
        "independent_holdout": False, "new_gold_created": False, "source_fidelity_qualified": False, "proof_authority": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = analyze(args.directory)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    ref = base.write(args.output, result)
    print(json.dumps({"output": ref, "status": result["status"], "verified_generation_rows": result["generation_rows_verified"]}))


if __name__ == "__main__":
    main()
