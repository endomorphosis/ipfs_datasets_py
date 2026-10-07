#!/usr/bin/env python3
"""Bounded matched-fit evaluation on retained native384 authored assets.

The numerical driver owns authentication, restoration and genuine bank forwards.
This writer collects every source-only trace before explicit posthoc v3 labels,
then retains complete per-row formula/source evidence and TRAIN-only gate inputs.
No optimizer, encoder, database, model selector or proof engine is invoked.
"""
import argparse
from copy import deepcopy
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import sys
import time
from types import SimpleNamespace

ARMS = ("retained_bank_control", "dual_bank_replay")
ROLES = ("selected", "last-attempt")
COHORTS = ("original_train48", "normative_train48", "new_balanced_train48", "exposed_v3_48")
TRAIN_COHORTS = COHORTS[:3]
FIELDS = ("actor", "action", "modality", "object")
FACETS = (*FIELDS, "conditions", "exceptions", "temporal")
PARENT_TENSOR_SHA = "0b3c7c3b1a5581cd393d9bb8db1d24b87fe2cb9dff0be268aa2b5ed1f88b6594"
NUMERIC_RELATIVE = "scripts/ops/autoencoder/benchmark_dual_bank_wording_continuation.py"
FALSE = dict(qualified=False, admitted=False, proof_authority=False, formalized=False,
    source_semantics_verified=False, checkpoint_promoted=False, convergence_proven=False,
    encoder_executed=False, downloads_performed=False, training_executed=False,
    lake_executed=False, native_family_validation_performed=False, used_for_selection=False,
    fresh_holdout=False, independent_semantic_holdout=False, Constitution_formalized=False)
PROFILE = dict(schema="dual-bank-wording-postfit-evaluation-plan/v1", phase="evaluation",
    dimensions=[384], arms=list(ARMS), roles=list(ROLES), cohorts=list(COHORTS),
    parent_baseline_included=True, logical_panels=20, physical_panels=20,
    samples_per_panel=48, rules_per_panel=180, scalar_reference_sites_per_panel=720,
    source_context_tokens=512, output_tokens=512, batch_size=8, temperature=0,
    full_vocabulary_size=32, cpu_slots=1, memory_mb=1536, storage_bytes=100000000,
    max_seconds_total=800, max_seconds_per_panel=60, max_seconds_per_bank=60,
    max_trace_memory_bytes=268435456, predictions_fsynced_before_v3_reference_load=True,
    raw_original_probe_panels=45, raw_probe_teacher_forced_ce_measured=False,
    raw_probe_reconstructed_input_mse_measured=False, output_payload_cap_bytes=97000000,
    same_pass_scalar_observation=True, extra_source_head_passes=0,
    main_trace_observation_scope="Twenty greedy panels only; bank and raw diagnostic forwards are separate.",
    expected_bank_source_head_forward_calls=300, raw_extra_count_head_passes_per_panel=6,
    inherited_TRAIN_validation_metadata_loaded=True, bridge_names=[],
    legal_ir_evaluate_provers=False, metric_disk_cache_used=False,
    teacher_forced_loss_measured=False, reconstructed_input_mse_measured=False, **FALSE)

def require(ok, message):
    if not ok:
        raise ValueError(message)

def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, allow_nan=False).encode()).hexdigest()

def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1048576), b""):
            h.update(block)
    return h.hexdigest()

def durable(save, path, value):
    ref = save(path, value)
    require(Path(ref["path"]).resolve() == Path(path).resolve() and sha(path) == ref["sha256"],
        "durable evaluation reference differs")
    with Path(path).open("rb") as stream:
        os.fsync(stream.fileno())
    fd = os.open(Path(path).parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    return ref

def prepare_cohorts(lane, control, balanced, context_owner):
    """Use authenticated cached inputs; the source-only v3 join uses exact text."""
    require(set(control["prior_sources_by_dataset"]) <= set(balanced["prior_sources_by_dataset"])
        and len(control["prior_sources_by_dataset"]) == 13
        and len(balanced["prior_sources_by_dataset"]) == 16,
        "preserved control13/balanced16 declarations required")
    cohorts = {"original_train48": dict(rows=[{k: r[k] for k in ("id", "source_text", "input")}
        for r in lane["rows"]["train"]], source_contexts=lane["source_contexts"]["train"])}
    for name, envelope in (("normative_train48", control), ("new_balanced_train48", balanced)):
        data = envelope["source_inputs"]
        require(data["dimension"] == 384 and data["complete"] is True
            and data["targets_attached"] is False and data["inputs_sha256"] ==
            digest({k: v for k, v in data.items() if k != "inputs_sha256"}), "closed native384 TRAIN cache required")
        rows = data["rows"]
        contexts = context_owner.build_source_contexts([{k: r[k] for k in ("id", "source_text")}
            for r in rows], data["clause_cache"])
        require(contexts == data["source_contexts"], "TRAIN source contexts differ from frozen owner")
        cohorts[name] = dict(rows=rows, source_contexts=contexts)
    prior = control["prior_sources_by_dataset"]["exposed_v3"]
    require(len(prior) == 48 and all(set(r) == {"id", "source_text"} for r in prior),
        "closed original48 v3 source declaration required")
    lookup = {}
    for row in control["evaluation_vectors_by_dataset"]["exposed_v3"]:
        require(set(row) == {"id", "source_text", "input"}, "source-only v3 vector inventory required")
        text = row["source_text"]
        require(text not in lookup or lookup[text] == row["input"], "inconsistent exact v3 source vectors")
        lookup[text] = row["input"]
    texts = {r["source_text"] for r in prior} | {piece for r in prior for piece in r["source_text"].split("\n\n")}
    require(texts <= set(lookup), "complete exact-text cached native384 v3 vectors required; no fallback")
    v3_rows = [dict(r, input=deepcopy(lookup[r["source_text"]])) for r in prior]
    clauses = sorted({piece for r in prior for piece in r["source_text"].split("\n\n")})
    cache = [dict(id="clause:" + hashlib.sha256(text.encode()).hexdigest(), source_text=text,
        input=deepcopy(lookup[text])) for text in clauses]
    cohorts["exposed_v3_48"] = dict(rows=v3_rows, source_contexts=context_owner.build_source_contexts(prior, cache))
    identities = set()
    for cohort in COHORTS:
        rows, contexts = cohorts[cohort]["rows"], cohorts[cohort]["source_contexts"]
        require(len(rows) == 48 and all(set(r) == {"id", "source_text", "input"} for r in rows)
            and sum(len(r["source_text"].split("\n\n")) for r in rows) == 180
            and context_owner.validate_contexts(rows, contexts)["dimension"] == 384,
            "complete48/180 native384 source-only cohort required")
        require(not identities & {r["id"] for r in rows}, "source cohort identities overlap")
        identities.update(r["id"] for r in rows)
    return cohorts

def verify_trace(trace, rows, contexts, state_ref, codec, transform):
    require(trace["trace_sha256"] == digest({k: v for k, v in trace.items() if k != "trace_sha256"})
        and trace["complete"] is True and trace["sample_count"] == 48 and trace["dimension"] == 384
        and trace["model_tensor_sha256"] == state_ref["tensor_sha256"]
        and trace["source_rows_sha256"] == digest(rows) and trace["source_contexts_sha256"] == digest(contexts)
        and trace["codec_sha256"] == digest(codec) and trace["input_transform_sha256"] == digest(transform)
        and trace["vocabulary_size"] == 32 and trace["generation_temperature"] == 0
        and trace["max_target_tokens"] == 512 and trace["batch_size"] == 8
        and len(trace["predictions"]) == 48 and [r["id"] for r in trace["predictions"]] == [r["id"] for r in rows]
        and all(trace.get(k) is True for k in ("source_only", "full_vocabulary_retained", "decomposition_exact",
            "caller_state_preserved", "hooks_removed", "complete_rollout_before_reference_scoring"))
        and all(trace.get(k) is False for k in ("reference_count_access", "reference_prefix_access",
            "reference_documents_passed_to_model", "inventory_access", "source_context_target_access",
            "syntax_mask", "forced_closure", "model_copied", "qualified", "admitted", "proof_authority",
            "source_semantics_verified", "lake_executed", "native_family_validation_performed"))
        and all(type(trace.get(k)) is int and trace[k] == 0 for k in
            ("extra_model_passes", "source_head_extra_evaluations", "optimizer_steps")),
        "same-pass complete source-only trace contract differs")
    require(all(type(trace[k]) is int for k in ("sample_count", "dimension", "vocabulary_size",
        "generation_temperature", "max_target_tokens", "batch_size")), "typed trace geometry required")
    typed_predictions(trace["predictions"], rows)

def bind_references(rows, references, codec):
    """Authored positional fixture labels; never infer law or add review status."""
    require(type(references) is list and len(references) == 48
        and len({r["id"] for r in references}) == 48, "complete48 reference cohort required")
    by_id = {r["id"]: r for r in references}
    require(set(by_id) == {r["id"] for r in rows}, "reference/source identities differ")
    result = []
    for row in rows:
        reference = deepcopy(by_id[row["id"]]); tokens = reference["target_ids"]
        require(reference["source_text"] == row["source_text"]
            and type(tokens) is list and 3 <= len(tokens) <= 512
            and all(type(t) is int for t in tokens) and tokens[0] == 1 and tokens[-1] == 2
            and all(type(t) is int and 3 <= t < 32 for t in tokens[1:-1])
            and json.loads("".join(codec["target_vocabulary"][t] for t in tokens[1:-1])) == reference["target"]
            and set(reference["target"]) == {"rules"}
            and len(reference["target"]["rules"]) == len(row["source_text"].split("\n\n"))
            and all(set(rule) == set(FACETS) and all(rule[k] == [] for k in
                ("conditions", "exceptions", "temporal")) for rule in reference["target"]["rules"]),
            "complete fixed seven-facet authored source/target binding required")
        reference.update(source_sha256=hashlib.sha256(row["source_text"].encode()).hexdigest(),
            clause_count=len(reference["target"]["rules"]))
        result.append(reference)
    require(sum(r["clause_count"] for r in result) == 180, "fixed180 rule reference denominator required")
    return result

def original_train_references(rows, codec):
    """Decode the already exposed original TRAIN labels after source rollout."""
    refs = []
    for row in rows:
        ids = row["target_ids"]
        require(type(ids) is list and 3 <= len(ids) <= 512 and ids[0] == 1 and ids[-1] == 2
            and all(type(t) is int and 3 <= t < 32 for t in ids[1:-1]), "fixed original TRAIN token labels required")
        target = json.loads("".join(codec["target_vocabulary"][t] for t in ids[1:-1]))
        refs.append(dict(id=row["id"], source_text=row["source_text"], target_ids=deepcopy(ids),
            target=target, clause_count=len(target["rules"]), template="original_train", split="training"))
    return refs

def join_scalar_formula(scalar, fidelity, references):
    """Keep all180 positional rules and720 sites, including unvisited failures."""
    require(scalar["complete"] is True and len(references) == len(fidelity["rows"]) == 48
        and [r["id"] for r in references] == [r["id"] for r in fidelity["rows"]],
        "full48 aligned scalar/formula evidence required")
    wanted = {(r["id"], slot, field) for r in references for slot in range(r["clause_count"]) for field in FIELDS}
    require(len(wanted) == 720, "complete720 scalar denominator required")
    events = {}
    for event in scalar["events"]:
        key = (event["id"], event["slot"], event["field"])
        require(key in wanted and key not in events, "duplicate or foreign scalar event")
        events[key] = event
    unvisited = {(r["id"], r["slot"], r["field"]) for r in scalar["unvisited_reference_sites"]}
    unavailable = {(r["id"], r["slot"], r["field"]) for r in scalar["unscored_sites"]
        if (r["id"], r["slot"], r["field"]) in wanted}
    extras = [r for r in scalar["unscored_sites"] if (r["id"], r["slot"], r["field"]) not in wanted]
    require(len(unvisited) == len(scalar["unvisited_reference_sites"]) and unavailable <= unvisited
        and len(unavailable) + len(extras) == len(scalar["unscored_sites"]), "unvisited/unavailable accounting differs")
    unvisited -= unavailable
    require(not set(events) & (unvisited | unavailable) and not unvisited & unavailable
        and set(events) | unvisited | unavailable == wanted, "every reference site must retain one status")
    counts = {f: dict(reference_sites=180, visited=0, unvisited=0, unavailable=0,
        source_correct=0, source_incorrect=0, source_correct_formula_wrong=0,
        source_wrong_formula_correct=0) for f in FIELDS}
    joined = []
    for ref, formula in zip(references, fidelity["rows"]):
        emitted = formula.get("generated_ir")
        raw_rules = emitted.get("rules") if type(emitted) is dict else None
        produced = raw_rules if type(raw_rules) is list else []
        for slot, target in enumerate(ref["target"]["rules"]):
            rule = produced[slot] if slot < len(produced) else None
            fields = {}
            for field in FIELDS:
                key = (ref["id"], slot, field); event = events.get(key); bucket = counts[field]
                formula_correct = type(rule) is dict and rule.get(field) == target[field]
                if event is None:
                    status = "unvisited" if key in unvisited else "unavailable"
                    bucket[status] += 1
                    fields[field] = dict(status=status, source_correct=None, formula_field_correct=formula_correct)
                else:
                    correct = event["source"]["argmax_token_id"] == event["target_token_id"]
                    bucket["visited"] += 1; bucket["source_correct" if correct else "source_incorrect"] += 1
                    bucket["source_correct_formula_wrong"] += int(correct and not formula_correct)
                    bucket["source_wrong_formula_correct"] += int(not correct and formula_correct)
                    fields[field] = dict(status="visited", source_correct=correct,
                        formula_field_correct=formula_correct, **deepcopy(event))
            joined.append(dict(id=ref["id"], slot=slot, expected_rule=target, generated_rule=rule, fields=fields))
    require(len(joined) == 180 and all(v["visited"] + v["unvisited"] + v["unavailable"] == 180
        for v in counts.values()), "fixed180 per-field denominator differs")
    return dict(schema="balanced-wording-postfit-scalar-formula-join/v1", complete=True,
        rows=joined, per_field=counts, extra_generated_unavailable_sites=extras,
        formula_field_match_scope="literal position in raw parsed emitted rule; complete valid-formula metrics remain separate",
        unvisited_counted_correct=False, unavailable_counted_correct=False, **FALSE)


COUNT_FIELDS = ("rows", "expected_rules", "generated_rules", "valid_generated_rules", "syntax_valid",
    "parsed_documents", "eos_count", "ordered_exact", "all_rules_preserved", "whole_rules_missing",
    "whole_rules_extra", "duplicate_rules", "order_mismatch_rows", "invalid_rule_count", "invalid_rows",
    "unscorable_generation_rows", "prediction_missing_rows")


def typed_predictions(predictions, rows):
    require(type(predictions) is list and len(predictions) == len(rows)
        and all(type(p) is dict for p in predictions)
        and [p.get("id") for p in predictions] == [r["id"] for r in rows],
        "complete ordered prediction census required")
    for prediction in predictions:
        require(type(prediction) is dict and set(prediction) ==
            {"id", "token_ids", "eos_reached", "generation_status"}
            and type(prediction["token_ids"]) is list and len(prediction["token_ids"]) <= 511
            and all(type(t) is int and 3 <= t < 32 for t in prediction["token_ids"])
            and type(prediction["eos_reached"]) is bool
            and type(prediction["generation_status"]) is str
            and 0 < len(prediction["generation_status"]) <= 128
            and prediction["eos_reached"] == (prediction["generation_status"] == "eos"),
            "typed raw content tokens/EOS/status required")


def complete_bindings(rows, contexts, references, codec):
    require(type(rows) is list and len(rows) == 48
        and len({r["id"] for r in rows}) == 48
        and all(type(r) is dict and set(r) == {"id", "source_text", "input"}
            and type(r["id"]) is str and r["id"] and type(r["source_text"]) is str
            and r["source_text"].strip() and type(r["input"]) is list and len(r["input"]) == 384
            and all(type(v) in (int, float) and math.isfinite(v) for v in r["input"]) for r in rows),
        "closed complete native384 source rows required")
    require([r["id"] for r in references] == [r["id"] for r in rows]
        and all(a["source_text"] == b["source_text"] for a, b in zip(rows, references))
        and sum(r["clause_count"] for r in references) == 180,
        "positional48/180 source/reference binding required")
    source_rows = [{k: r[k] for k in ("id", "source_text")} for r in rows]
    return dict(source_rows=source_rows, source_contexts_sha256=digest(contexts),
        references_sha256=digest(references), codec_sha256=digest(codec))


def build_gate_panel(trace, fidelity, joined, rows, contexts, references, codec):
    """Retain trusted pure scorer rows; never manufacture row counts from a total."""
    typed_predictions(trace["predictions"], rows)
    binding = complete_bindings(rows, contexts, references, codec)
    require(fidelity["report_sha256"] == digest({k: v for k, v in fidelity.items() if k != "report_sha256"})
        and fidelity["complete_evaluation"] is True and fidelity["codec_sha256"] == digest(codec)
        and len(fidelity["rows"]) == 48 and [r["id"] for r in fidelity["rows"]] == [r["id"] for r in rows],
        "complete immutable genuine fidelity report required")
    for source, reference, prediction, observed in zip(rows, references, trace["predictions"], fidelity["rows"]):
        require(observed["expected_ir"] == reference["target"]
            and observed["generated_token_ids"] == prediction["token_ids"]
            and observed["generation_status"] == prediction["generation_status"]
            and observed["source_provenance"]["source_text"] == source["source_text"]
            and observed["source_provenance"]["source_sha256"] == hashlib.sha256(source["source_text"].encode()).hexdigest(),
            "raw generated tokens/target/source join differs")
        counts = observed["counts"]
        require(set(counts) == set(COUNT_FIELDS)
            and all(type(counts[k]) is int and 0 <= counts[k] <= 2048 for k in COUNT_FIELDS)
            and counts["rows"] == 1 and counts["expected_rules"] == reference["clause_count"]
            and counts["eos_count"] == int(prediction["eos_reached"]),
            "complete typed per-row formula counts required")
        require(set(observed["by_facet"]) == set(FACETS)
            and all(type(v["total"]) is int and v["total"] == reference["clause_count"]
                and type(v["correct"]) is int and 0 <= v["correct"] <= v["total"]
                for v in observed["by_facet"].values()), "complete typed per-row seven facets required")
    require(set(fidelity["metrics"]) == set(COUNT_FIELDS)
        and all(type(fidelity["metrics"][k]) is int and fidelity["metrics"][k] ==
            sum(row["counts"][k] for row in fidelity["rows"]) for k in COUNT_FIELDS),
        "formula summary differs from all48 underlying rows")
    facets = {f: dict(correct=sum(r["by_facet"][f]["correct"] for r in fidelity["rows"]),
        total=sum(r["by_facet"][f]["total"] for r in fidelity["rows"])) for f in FACETS}
    require(all(fidelity["by_facet"][f]["correct"] == facets[f]["correct"]
        and fidelity["by_facet"][f]["total"] == facets[f]["total"] for f in FACETS),
        "facet summary differs from all48 underlying rows")
    require(joined["complete"] is True and len(joined["rows"]) == 180
        and set(joined["per_field"]) == set(FIELDS), "complete positional scalar/formula join required")
    return dict(complete=True, rows=48, expected_rules=180,
        source_binding=dict(source_text_rows_sha256=digest(binding["source_rows"]),
            **{k: binding[k] for k in ("source_contexts_sha256", "references_sha256", "codec_sha256")}),
        model_tensor_sha256=trace["model_tensor_sha256"], formula_metrics=deepcopy(fidelity["metrics"]),
        formula_rows=deepcopy(fidelity["rows"]), seven_facets=facets,
        scalar_by_field=deepcopy(joined["per_field"]), **FALSE)


def verified_bank_metrics(readout, bank, codec, tensor_sha):
    """Validate complete full32 numerical rows before exposing gate totals."""
    require(readout["complete"] is True and type(readout["row_count"]) is int and readout["row_count"] == 180
        and type(readout["reference_fields"]) is int and readout["reference_fields"] == 720
        and readout["model_tensor_sha256"] == tensor_sha and len(readout["rows"]) == len(bank["rows"]) == 180
        and set(readout["by_field"]) == set(FIELDS)
        and readout["source_targets_joined_after_numeric_return"] is True
        and readout["source_forwards_owned_by_inherited_evaluator"] is True
        and type(readout["extra_source_forwards"]) is int and readout["extra_source_forwards"] == 0
        and type(readout["optimizer_steps"]) is int and readout["optimizer_steps"] == 0
        and all(readout[name] is False for name in ("qualified", "admitted", "proof_authority", "used_for_selection")),
        "complete unchanged authentic bank numerical readout required")
    totals = {f: dict(correct=0, total=180) for f in FIELDS}
    for row, observed in zip(bank["rows"], readout["rows"]):
        require(observed["row_id"] == row["id"] and observed["source_sha256"] == row["source_sha256"]
            and observed["template"] == row["template"] and observed["original_rule_sha256"] == digest(row["target"])
            and set(observed["fields"]) == set(FIELDS), "ordered bank identity/source/target/template join differs")
        for field in FIELDS:
            values = observed["fields"][field]
            logits = values["full32_logits"]
            require(type(logits) is list and len(logits) == 32
                and all(type(v) in (int, float) and math.isfinite(v) for v in logits), "finite typed full32 bank logits required")
            target = codec["target_vocabulary"].index(json.dumps(row["target"][field], ensure_ascii=False, separators=(",", ":")))
            winner = max(range(32), key=logits.__getitem__)
            require(type(values["target_token_id"]) is int and values["target_token_id"] == target
                and type(values["argmax_token_id"]) is int and values["argmax_token_id"] == winner
                and type(values["correct"]) is bool and values["correct"] == (winner == target),
                "source field target/full32 argmax/correct join differs")
            high = max(logits)
            ce = high + math.log(math.fsum(math.exp(v - high) for v in logits)) - logits[target]
            margin = logits[target] - max(v for i, v in enumerate(logits) if i != target)
            require(all(type(values[k]) in (int, float) and math.isfinite(values[k]) for k in ("cross_entropy", "margin"))
                and math.isclose(values["cross_entropy"], ce, rel_tol=1e-10, abs_tol=1e-10)
                and values["margin"] == margin, "source field confidence differs from retained full32 logits")
            totals[field]["correct"] += int(winner == target)
    require(all(type(readout["by_field"][f][k]) is int and readout["by_field"][f][k] == totals[f][k]
        for f in FIELDS for k in ("correct", "total")), "bank totals differ from all180 genuine rows")
    return totals


def verify_barrier(records):
    expected = {("parent", "selected", cohort) for cohort in COHORTS}
    expected |= {(arm, role, cohort) for arm in ARMS for role in ROLES for cohort in COHORTS}
    require(type(records) is list and len(records) == 20
        and {(r["arm"], r["role"], r["cohort"]) for r in records} == expected
        and all(r["prediction_fsynced"] is True and r["physical_panel_computed"] is True for r in records),
        "complete twenty-panel parent/candidate durable barrier required")
    for record in records:
        for key in ("trace_ref", "predictions_ref"):
            ref = record[key]
            require(sha(ref["path"]) == ref["sha256"], "changed panel before explicit v3 reference barrier")


MANIFEST_FIELDS = {"schema", "inputs", "extensions", "plan_sha256", "comparison_protocol",
    "training_manifest", "training_plan", "training_summary", "training_terminal",
    "source_inventories", "v3_references"}
ORIGINAL_PANELS = ("training", "validation", "zero-condition", "source-shuffle",
    "context-only-shuffle", "cross-length-shuffle", "context-reverse", "context-rotate",
    "recurrent-residual-off")


def validate_plan(plan, manifest):
    require(type(manifest) is dict and set(manifest) == MANIFEST_FIELDS
        and manifest["schema"] == "dual-bank-wording-postfit-evaluation-manifest/v1"
        and type(manifest["inputs"]) is dict and manifest["inputs"]
        and type(manifest["extensions"]) is dict and NUMERIC_RELATIVE in manifest["extensions"]
        and set(manifest["source_inventories"]) == {"control", "balanced"}
        and set(manifest["training_terminal"]) == {"child_exit", "resources_final"},
        "closed matched-fit evaluation manifest required")
    require(type(plan) is dict and set(plan) == set(PROFILE) | {"input_sha256"}
        and all(type(plan[k]) is type(v) and plan[k] == v for k, v in PROFILE.items())
        and plan["input_sha256"] == manifest["inputs"], "fixed complete native384 evaluation plan required")


def _file_identity(path):
    path = Path(path)
    require(path.is_absolute() and path.resolve(strict=True) == path, "canonical file path required")
    info = path.lstat()
    import stat
    require(stat.S_ISREG(info.st_mode) and 1 <= info.st_nlink <= 128, "bounded regular retained file required")
    return (info.st_dev, info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns,
        info.st_ctime_ns, info.st_nlink)


def _capture(path, wanted):
    require(type(wanted) is str and len(wanted) == 64
        and all(c in "0123456789abcdef" for c in wanted), "exact lowercase SHA pin required")
    before = _file_identity(path)
    require(sha(path) == wanted and _file_identity(path) == before, "retained file pin/currentness differs")
    return before


def _load_pinned_module(path, wanted, name):
    _capture(path, wanted)
    spec = importlib.util.spec_from_file_location(name, path)
    owner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(owner)
    _capture(path, wanted)
    return owner


def _current_owner(dependency_root, name):
    """Reuse the current ordinary namespace, rejecting historical alias mixing."""
    import importlib
    module = importlib.import_module("ipfs_datasets_py.logic.formalization.autoencoder." + name)
    expected = Path(dependency_root).resolve(strict=True) / "ipfs_datasets_py/logic/formalization/autoencoder" / (name + ".py")
    origin = Path(module.__file__)
    require(origin == expected and origin.resolve(strict=True) == origin, "foreign current numerical owner: " + name)
    return module


def compact_writer(output_root, payload_cap=97000000):
    """Bound physical evidence bytes, with3MB reserved inside the100MB phase."""
    root = Path(output_root).resolve(strict=True)
    used = 0
    def save(path, value):
        nonlocal used
        path = Path(path)
        require(path.is_absolute() and path.is_relative_to(root), "owned output locator required")
        data = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
            allow_nan=False).encode() + b"\n"
        require(used + len(data) <= payload_cap, "evaluation physical payload budget exhausted")
        path.parent.mkdir(parents=True, exist_ok=True)
        require(path.parent.resolve(strict=True) == path.parent, "canonical output parent required")
        with path.open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        used += len(data)
        return dict(path=str(path), bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
    return save


def collect_raw_probe(ctx, model, split, kind, *, controls, ordered, deadline):
    """Current native greedy routes and actual count logits; no TFCE/MSE claim."""
    import torch
    original = [{k: row[k] for k in ("id", "source_text", "input")} for row in ctx["rows"][split]]
    # This pure control interface requires an opaque fourth field. Supply empty
    # placeholders; remove them before any generation or count operation.
    envelope = [dict(row, target_ids=[]) for row in original]
    control = "conditioned" if kind in ("zero_condition", "recurrent_residual_off") else kind
    rows, contexts, execution = controls.prepare_control(envelope, ctx["source_contexts"][split], control)
    rows = [{k: row[k] for k in ("id", "source_text", "input")} for row in rows]
    working = model
    if kind == "zero_condition":
        working = ordered.bind_zero_condition_model(model)
        execution.update(kind=kind, control=dict(kind=kind, source_assignment={r["id"]: r["id"] for r in original}),
            normalized_clause_values_and_padding_mask_removed=True)
    elif kind == "recurrent_residual_off":
        working = ordered.bind_residual_off_model(model)
        execution.update(kind=kind, recurrent_residual_disabled=True)
    before = ctx["core"].tensor_digest(model)
    modes = {name: module.training for name, module in working.named_modules()}
    rng = torch.get_rng_state().clone()
    predictions, counts = [], []
    try:
        working.eval()
        with torch.inference_mode():
            for start in range(0, 48, 8):
                require(time.monotonic() < deadline, "raw diagnostic cooperative deadline")
                part = rows[start:start + 8]
                transform = ctx["donor"]["input_transform"]
                raw = torch.tensor([row["input"] for row in part], dtype=torch.float32)
                data = (raw - torch.tensor(transform["mean"], dtype=torch.float32)) / transform["scale"]
                kwargs = ctx["core"]._source_context_kwargs(torch, part, contexts, transform)
                value = ctx["core"]._greedy(torch, working, data, 512, 32, deadline, **kwargs)
                require(value is not None, "incomplete raw greedy diagnostic")
                projected, tokens, statuses = value
                count_logits = working.count_logits(projected)
                require(tuple(count_logits.shape) == (len(part), 32) and ctx["core"]._finite(torch, count_logits),
                    "finite complete32class raw count readout required")
                for row, output, status, logits in zip(part, tokens, statuses, count_logits.tolist()):
                    predictions.append(dict(id=row["id"], token_ids=output, eos_reached=status == "eos", generation_status=status))
                    counts.append(dict(id=row["id"], full32_count_logits=logits,
                        predicted_count=1 + max(range(32), key=logits.__getitem__)))
    finally:
        for name, module in working.named_modules():
            module.train(modes[name])
    require(torch.equal(rng, torch.get_rng_state()) and ctx["core"].tensor_digest(model) == before,
        "raw diagnostic changed caller model or ambient RNG")
    typed_predictions(predictions, original)
    return dict(complete=True, source_only=True, predictions=predictions, count_readout=counts,
        rows=48, expected_rule_denominator=180, model_tensor_sha256=before, execution=execution,
        controlled_rows_sha256=digest(rows), controlled_contexts_sha256=digest(contexts),
        reference_documents_passed_to_generation=False, reference_tokens_passed_to_generation=False,
        target_placeholders_read=False, count_readout_extra_head_passes=6,
        control_wrapper_copies_model=kind in ("zero_condition", "recurrent_residual_off"),
        teacher_forced_loss_measured=False, reconstructed_input_mse_measured=False,
        ambient_rng_preserved=True, caller_tensor_preserved=True, **FALSE)


def forbid_evaluation_training(ctx):
    """Private child-process bombs; metadata preparation finishes before Torch."""
    import torch
    def forbidden(*args, **kwargs):
        raise RuntimeError("No optimizer, fitting, pickle loading or training in postfit evaluation")
    torch.optim.Optimizer.step = forbidden
    for name in ("AdamW", "Adam", "SGD"):
        getattr(torch.optim, name).__init__ = forbidden
        getattr(torch.optim, name).step = forbidden
    torch.load = forbidden
    ctx["modules"]["long_span_source_value_training"].train = forbidden
    for name in ("projected_source_decoder_experiment", "clause_source_decoder_experiment"):
        owner = ctx["owners"].get(name)
        if owner is not None and hasattr(owner, "fit_source_normalization"):
            owner.fit_source_normalization = forbidden


def verify_endpoint_join(ctx, run, report, role, state):
    """Bind the saved task/recipe to original authenticated context before Torch."""
    parent = ctx["restore_packet"]["checkpoint"]
    ref = run["states"][role]
    expected_tensor = report["selected_weights_sha256" if role == "selected" else "last_complete_attempt_weights_sha256"]
    require(state["role"] == role and state["recipe"] == run["recipe"]
        and type(state["dimension"]) is int and state["dimension"] == 384
        and type(state["selected"]) is bool and (role != "selected" or state["selected"] is True)
        and state["schema"] == parent["schema"] == state["state_serialization_schema"]
        and state["ir_family_id"] == "legal_ir" and state["dimension_role"] == "input_embedding"
        and state["task_id"] == "semantic_IR_reconstruction"
        and all(state[name] is None for name in ("native_ir_schema_version", "decoder_profile_id", "decoder_format_id"))
        and all(state[name] is False for name in ("qualified", "admitted", "proof_authority", "source_semantics_verified",
            "checkpoint_promoted", "formalized", "fresh_holdout", "lake_executed")),
        "exact family/task/role/width/unknown native identity join required")
    require(digest(state["codec"]) == digest(ctx["donor"]["codec"]) == state["codec_sha256"]
        and digest(state["input_transform"]) == digest(ctx["donor"]["input_transform"])
        and digest(state["initializer_receipt"]) == digest(parent["initializer_receipt"])
        and digest(state["architecture"]) == digest(parent["architecture"])
        and digest(state["lineage"]) == digest(ctx["lineage"])
        and digest(state["model_state"]) == state["weights_sha256"]
        and state["tensor_sha256"] == ref["tensor_sha256"] == expected_tensor,
        "original codec/transform/architecture/initializer/lineage/report tensor join required")
    require(digest(state["continuation_parent"]) == digest(ctx["parent_summary"]["states"]["selected"])
        and digest(state["continuation_source_refs"]) == digest(ctx["pins"])
        and state["continuation_run_id"] == ctx["run_id"]
        and state["continuation_arm"] == run["arm"] and state["continuation_role"] == role
        and digest(state["continuation_recipe"]) == digest(run["recipe"])
        and digest(state["continuation_training_ref"]) == digest(run["training_ref"])
        and state["continuation_training_executed"] is True
        and digest(state["continuation_phase_manifest"]) == digest(ctx["phase_manifest_ref"])
        and digest(state["continuation_phase_plan"]) == digest(ctx["phase_plan_ref"]),
        "exact original parent/source/phase/run/arm/training receipt joins required")


def execute(args):
    require(args.phase == "evaluation", "explicit evaluation phase required")
    started = time.monotonic()
    deadline = started + PROFILE["max_seconds_total"]
    manifest = json.loads(args.manifest.read_bytes())
    plan = json.loads(args.plan.read_bytes())
    validate_plan(plan, manifest)
    input_pins = dict(manifest["inputs"])
    input_pins[str(args.manifest.resolve())] = sha(args.manifest)
    input_pins[str(args.plan.resolve())] = manifest["plan_sha256"]
    for relative, wanted in manifest["extensions"].items():
        rel = Path(relative)
        require(not rel.is_absolute() and ".." not in rel.parts, "closed extension locator required")
        path = str((args.extension_root / rel).resolve())
        require(path not in input_pins or input_pins[path] == wanted, "conflicting extension pin")
        input_pins[path] = wanted
    witnesses = {p: _capture(p, wanted) for p, wanted in input_pins.items()}
    ctx = None
    current_owners = {}
    def recheck():
        require(time.monotonic() < deadline, "bounded evaluation deadline")
        for p, wanted in input_pins.items():
            require(_capture(p, wanted) == witnesses[p], "evaluation file identity changed")
        for p, identity in witnesses.items():
            require(_file_identity(p) == identity, "late cross-file evaluation identity drift")
        if ctx is not None:
            numeric.fence(ctx)
        for name, module in current_owners.items():
            require(_current_owner(args.dependency_root, name) is module, "loaded current owner changed")
        for p, identity in witnesses.items():
            require(_file_identity(p) == identity, "closing cross-owner evaluation identity drift")
    def bound(path):
        path = str(Path(path).resolve())
        require(path in input_pins and _capture(path, input_pins[path]) == witnesses[path], "unbound evaluation input")
        return json.loads(Path(path).read_bytes())
    recheck()
    require(not args.output.exists(), "fresh evaluation output required")
    protocol = bound(manifest["comparison_protocol"])
    require(protocol["schema"] == "dual-bank-wording-matched-continuation-protocol/v1"
        and protocol["parent_tensor_sha256"] == PARENT_TENSOR_SHA
        and [a["name"] for a in protocol["arms"]] == list(ARMS), "predeclared matched comparison differs")
    terminal = manifest["training_terminal"]
    require(bound(terminal["child_exit"])["returncode"] == 0
        and bound(terminal["resources_final"])["status"] == "released", "completed released training required")
    summary = bound(manifest["training_summary"])
    require(summary["complete"] is True and type(summary["dimension"]) is int and summary["dimension"] == 384
        and summary["phase"] == "training" and len(summary["runs"]) == 2, "two complete matched384 fits required")
    runs = {}
    for ref in summary["runs"]:
        run = bound(ref["path"])
        require(sha(ref["path"]) == ref["sha256"] and run["arm"] in ARMS and run["arm"] not in runs
            and run["budget_completed"] is True and run["fresh_optimizer"] is True
            and run["fresh_scheduler"] is True and type(run["seed"]) is int and run["seed"] == 1729
            and run["exact_optimizer_resume"] is False
            and run["initial_tensor_sha256"] == PARENT_TENSOR_SHA
            and run["recipe"]["name"] == run["arm"] and type(run["recipe"]["weight"]) in (int, float)
            and run["recipe"]["weight"] == .05
            and all(run[k] is False for k in ("qualified", "admitted", "proof_authority", "checkpoint_promoted")),
            "authentic separate matched endpoint summaries required")
        for role in ROLES:
            state = run["states"][role]
            require(input_pins.get(str(Path(state["path"]).resolve())) == state["sha256"], "unbound endpoint bytes")
        runs[run["arm"]] = run
    require(set(runs) == set(ARMS) and all(r["parent_state"]["tensor_sha256"] == PARENT_TENSOR_SHA
        and r["parent_state"] == runs[ARMS[0]]["parent_state"] for r in runs.values()), "one exact original parent required")
    numeric = _load_pinned_module(args.extension_root / NUMERIC_RELATIVE,
        manifest["extensions"][NUMERIC_RELATIVE], "_dual_bank_evaluation_numerical_owner")
    sys.meta_path.insert(0, numeric.ForbiddenImports())
    sys.addaudithook(numeric.audit)
    previous = SimpleNamespace(**vars(args))
    previous.phase = "preflight"
    previous.dimension = 384
    previous.manifest = Path(manifest["training_manifest"])
    previous.plan = Path(manifest["training_plan"])
    ctx = numeric.load_context(previous, deadline=deadline)
    require(Path(ctx["manifest"]["current_source_root"]).resolve() == args.dependency_root.resolve(),
        "current authenticated source generation differs")
    require(all(input_pins.get(p) == wanted for p, wanted in ctx["pins"].items()),
        "evaluation seal omits original authenticated input/source closure")
    for arm, run in runs.items():
        report = bound(run["training_ref"]["path"])
        require(all(type(report[k]) is int for k in ("optimizer_steps", "row_presentations",
            "count_training_row_presentations", "valid_target_token_presentations", "source_value_presentations",
            "auxiliary_source_modality_presentations")), "typed matched committed budget required")
        require(digest({k: v for k, v in report["config"].items() if k != "max_seconds"}) ==
            digest({k: v for k, v in ctx["config"].items() if k != "max_seconds"}),
            "inherited optimizer/selector configuration differs")
        numeric.validate_commits(ctx, report, arm)
        for role in ROLES:
            state = bound(run["states"][role]["path"])
            verify_endpoint_join(ctx, run, report, role, state)
    scalar_owner = _current_owner(args.dependency_root, "generated_scalar_observation")
    fidelity_owner = _current_owner(args.dependency_root, "decoder_source_fidelity")
    context_owner = _current_owner(args.dependency_root, "clause_source_context")
    controls = _current_owner(args.dependency_root, "clause_source_controls")
    ordered = _current_owner(args.dependency_root, "ordered_clause_recurrent_decoder_experiment")
    current_owners.update({name: owner for name, owner in (("generated_scalar_observation", scalar_owner),
        ("decoder_source_fidelity", fidelity_owner), ("clause_source_context", context_owner),
        ("clause_source_controls", controls), ("ordered_clause_recurrent_decoder_experiment", ordered))})
    require(all(str(Path(owner.__file__).resolve()) in input_pins for owner in current_owners.values()),
        "current evaluation owner absent from byte closure")
    retention = ctx["dual_owner"].retention
    forbid_evaluation_training(ctx)
    lane = dict(rows=ctx["rows"], source_contexts=ctx["source_contexts"], donor=ctx["donor"])
    control, balanced = (bound(manifest["source_inventories"][role]) for role in ("control", "balanced"))
    cohorts = prepare_cohorts(lane, control, balanced, context_owner)
    v3_path = Path(manifest["v3_references"]).resolve()
    require(str(v3_path) in input_pins and all(v3_path != Path(manifest["source_inventories"][r]).resolve()
        for r in ("control", "balanced")), "separate posthoc v3 reference file required")
    args.output.mkdir(parents=True)
    save = compact_writer(args.output, PROFILE["output_payload_cap_bytes"])
    durable(save, args.output / "sealed-recipe.json", dict(plan=plan, manifest=manifest, **FALSE))
    records, bank_records, raw_records = [], {}, []
    endpoints = [("parent", "selected", runs[ARMS[0]]["parent_state"])]
    endpoints += [(arm, role, runs[arm]["states"][role]) for arm in ARMS for role in ROLES]
    for arm, role, state_ref in endpoints:
        recheck()
        model = numeric.restore_parent(ctx) if arm == "parent" else numeric.restore_state(ctx, state_ref)
        require(ctx["core"].tensor_digest(model) == state_ref["tensor_sha256"], "restored exact endpoint differs")
        alias = arm != "parent" and runs[arm]["states"]["selected"]["tensor_sha256"] == runs[arm]["states"]["last-attempt"]["tensor_sha256"]
        for cohort in COHORTS:
            sources = cohorts[cohort]
            trace = scalar_owner.collect_source_scalar_trace(model, sources["rows"], codec=ctx["donor"]["codec"],
                input_transform=ctx["donor"]["input_transform"], source_contexts=sources["source_contexts"],
                max_target_tokens=512, batch_size=8, deadline=min(deadline, time.monotonic() + 60.),
                max_memory_bytes=PROFILE["max_trace_memory_bytes"])
            verify_trace(trace, sources["rows"], sources["source_contexts"], state_ref,
                ctx["donor"]["codec"], ctx["donor"]["input_transform"])
            require(ctx["core"].tensor_digest(model) == state_ref["tensor_sha256"], "observer changed endpoint tensors")
            folder = args.output / arm / role / cohort
            trace_ref = durable(save, folder / "source-head-trace.json", trace)
            predictions_ref = durable(save, folder / "actual-predictions.json", dict(predictions=trace["predictions"],
                complete=True, model_tensor_sha256=trace["model_tensor_sha256"], same_pass_scalar_trace_sha256=trace["trace_sha256"],
                generation_reference_access=False, generation_temperature=0, greedy_passes_per_row=1, **FALSE))
            records.append(dict(arm=arm, role=role, cohort=cohort, state_ref=state_ref, trace_ref=trace_ref,
                predictions_ref=predictions_ref, prediction_fsynced=True, generation_seconds=trace["elapsed_seconds"],
                selected_last_tensor_alias=alias, physical_panel_computed=True))
            del trace
            recheck()
        bank_records[(arm, role)] = {}
        for bank_role in ("control", "balanced"):
            readout = numeric.source_bank_readout(ctx, model, bank_role,
                min(deadline, time.monotonic() + PROFILE["max_seconds_per_bank"]))
            metrics = verified_bank_metrics(readout, ctx["banks_by_role"][bank_role], ctx["donor"]["codec"], state_ref["tensor_sha256"])
            ref = durable(save, args.output / arm / role / (bank_role + "-source-bank-readout.json"), readout)
            bank_records[(arm, role)][bank_role] = dict(ref=ref, metrics=metrics)
            del readout
            recheck()
        for label in ORIGINAL_PANELS:
            split = "train" if label == "training" else "validation"
            kind = "conditioned" if label in ("training", "validation") else label.replace("-", "_")
            raw_probe = collect_raw_probe(ctx, model, split, kind, controls=controls, ordered=ordered,
                deadline=min(deadline, time.monotonic() + 60.))
            ref = durable(save, args.output / arm / role / ("raw-" + label + "-predictions.json"), raw_probe)
            raw_records.append(dict(arm=arm, role=role, label=label, split=split, predictions_ref=ref))
            del raw_probe
            recheck()
        del model
    verify_barrier(records)
    durable(save, args.output / "predictions-complete.json", dict(complete=True, records=records,
        v3_reference_json_loaded=False, inherited_TRAIN_validation_metadata_already_loaded=True,
        all_predictions_fsynced=True, logical_panels=20, physical_panels=20, **FALSE))
    require(len(raw_records) == 45, "all nine independently generated raw probes per five endpoints required")
    durable(save, args.output / "raw-probes-complete.json", dict(complete=True, records=raw_records,
        model_panels=45, explicit_v3_reference_json_loaded=False, **FALSE))
    reference_sets = dict(original_train48=original_train_references(ctx["rows"]["train"], ctx["donor"]["codec"]),
        normative_train48=control["corpus"]["references"], new_balanced_train48=balanced["corpus"]["references"],
        exposed_v3_48=bound(v3_path))
    refs = {name: bind_references(cohorts[name]["rows"], reference_sets[name], ctx["donor"]["codec"]) for name in COHORTS}
    gate_panels, results = {}, []
    for record in records:
        sources = cohorts[record["cohort"]]
        references = refs[record["cohort"]]
        trace = json.loads(Path(record["trace_ref"]["path"]).read_bytes())
        predictions = json.loads(Path(record["predictions_ref"]["path"]).read_bytes())
        require(sha(record["trace_ref"]["path"]) == record["trace_ref"]["sha256"]
            and sha(record["predictions_ref"]["path"]) == record["predictions_ref"]["sha256"]
            and predictions["predictions"] == trace["predictions"], "durable prediction/trace drift before reference join")
        verify_trace(trace, sources["rows"], sources["source_contexts"], record["state_ref"],
            ctx["donor"]["codec"], ctx["donor"]["input_transform"])
        scored_rows = [dict(r, target_ids=ref["target_ids"]) for r, ref in zip(sources["rows"], references)]
        scalar = scalar_owner.score_scalar_trace(trace, scored_rows, references,
            split="exposed_development" if record["cohort"] == "exposed_v3_48" else "training",
            codec=ctx["donor"]["codec"], input_transform=ctx["donor"]["input_transform"],
            source_contexts=sources["source_contexts"], validate_rule=ctx["validate_rule"], deadline=deadline)
        fidelity = fidelity_owner.score_predictions(references, predictions["predictions"], codec=ctx["donor"]["codec"],
            validate_rule=ctx["validate_rule"], output_limit=512, validator_id=ctx["validator_id"])
        joined = join_scalar_formula(scalar, fidelity, references)
        panel = build_gate_panel(trace, fidelity, joined, sources["rows"], sources["source_contexts"], references, ctx["donor"]["codec"])
        folder = args.output / record["arm"] / record["role"] / record["cohort"]
        evidence = {name: durable(save, folder / filename, value) for name, filename, value in (
            ("scalar_score_ref", "posthoc-scalar-score.json", scalar), ("formula_fidelity_ref", "actual-formula-fidelity.json", fidelity),
            ("scalar_formula_join_ref", "scalar-formula-join.json", joined), ("gate_panel_ref", "retention-panel.json", panel))}
        gate_panels[(record["arm"], record["role"], record["cohort"])] = panel
        results.append(dict(record, **evidence, formula_metrics=panel["formula_metrics"], seven_facets=panel["seven_facets"],
            scalar_by_field=panel["scalar_by_field"], paragraphs=48, rules=180, scalar_reference_sites=720, **FALSE))
        recheck()
    raw_results = []
    for record in raw_records:
        ref = record["predictions_ref"]
        require(sha(ref["path"]) == ref["sha256"], "raw diagnostic bytes changed before pure scoring")
        raw_probe = json.loads(Path(ref["path"]).read_bytes())
        references = bind_references([{k: r[k] for k in ("id", "source_text", "input")}
            for r in ctx["rows"][record["split"]]], ctx["references"][record["split"]], ctx["donor"]["codec"])
        fidelity = fidelity_owner.score_predictions(references, raw_probe["predictions"], codec=ctx["donor"]["codec"],
            validate_rule=ctx["validate_rule"], output_limit=512, validator_id=ctx["validator_id"],
            control=raw_probe["execution"]["control"])
        require(fidelity["complete_evaluation"] is True and len(fidelity["rows"]) == 48,
            "complete raw diagnostic source/fidelity denominator required")
        count_rows = [dict(observed, expected_count=reference["clause_count"],
            correct=observed["predicted_count"] == reference["clause_count"])
            for observed, reference in zip(raw_probe["count_readout"], references)]
        require([r["id"] for r in count_rows] == [r["id"] for r in references], "raw paragraph count identity join differs")
        count_ref = durable(save, args.output / record["arm"] / record["role"] /
            ("raw-" + record["label"] + "-count-score.json"), dict(rows=count_rows, denominator=48,
            correct=sum(r["correct"] for r in count_rows), source_targets_joined_after_numeric_return=True, **FALSE))
        fidelity_ref = durable(save, args.output / record["arm"] / record["role"] /
            ("raw-" + record["label"] + "-fidelity.json"), fidelity)
        raw_results.append(dict(record, fidelity_ref=fidelity_ref, count_score_ref=count_ref,
            formula_metrics=fidelity["metrics"], teacher_forced_ce_measured=False, reconstructed_input_mse_measured=False,
            used_for_retention_gate=False, **FALSE))
        recheck()
    expected = {name: complete_bindings(cohorts[name]["rows"], cohorts[name]["source_contexts"], refs[name], ctx["donor"]["codec"])
        for name in TRAIN_COHORTS}
    baseline = {name: gate_panels[("parent", "selected", name)] for name in TRAIN_COHORTS}
    baseline_banks = {role: bank_records[("parent", "selected")][role]["metrics"] for role in ("control", "balanced")}
    gates = []
    for arm in ARMS:
        for role in ROLES:
            candidate = {name: gate_panels[(arm, role, name)] for name in TRAIN_COHORTS}
            candidate_banks = {bank_role: bank_records[(arm, role)][bank_role]["metrics"] for bank_role in ("control", "balanced")}
            gate = retention.retention_gate(schedule=ctx["dual_prepared_banks"].schedule, expected_bindings=expected,
                baseline_panels=baseline, candidate_panels=candidate, baseline_bank_fields=baseline_banks,
                candidate_bank_fields=candidate_banks)
            regressions = [dict(cohort=name, id=p["id"], parent_ordered_exact=b["counts"]["ordered_exact"],
                candidate_ordered_exact=p["counts"]["ordered_exact"]) for name in TRAIN_COHORTS
                for b, p in zip(baseline[name]["formula_rows"], candidate[name]["formula_rows"])
                if b["counts"]["ordered_exact"] == 1 and p["counts"]["ordered_exact"] != 1]
            gates.append(dict(arm=arm, role=role, gate=gate, previously_exact_paragraph_regressions=regressions))
    recheck()
    result = dict(PROFILE, complete=True, panels=results, raw_original_probes=raw_results, retention_gates=gates,
        elapsed_seconds=time.monotonic() - started, optimizer_steps=0, models_executed=True,
        parent_tensor_sha256=PARENT_TENSOR_SHA, all_v3_references_after_durable_prediction_barrier=True,
        explicit_v3_reference_parse_scope="This writer; inherited TRAIN/validation metadata and original meanings already exposed.",
        v3_reference_file_bytes_hashed_before_generation=True,
        saved_paragraph_vector_producer_authenticated=False,
        optimizer_and_training_bombs_installed=True, encoder_database_hub_import_bombs_installed=True,
        withheld_reference_blinding_claimed=False, original_meanings_previously_exposed=True,
        all_raw_original_probes_retained_independently=True, no_auxiliary_loss_substituted_for_paragraph_metrics=True,
        generation_scope="Current authenticated saved models and unchanged retained embeddings; authored fixture evidence only.")
    return durable(save, args.output / "summary.json", result)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=["evaluation"], required=True)
    for name in ("dependency-root", "extension-root", "manifest", "plan", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    sys.path.insert(0, str(args.dependency_root.resolve()))
    receipt = execute(args)
    print(json.dumps(receipt, sort_keys=True))


if __name__ == "__main__":
    main()
