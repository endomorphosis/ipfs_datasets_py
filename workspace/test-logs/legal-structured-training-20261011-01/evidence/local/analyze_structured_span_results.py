"""Inspect saved JSON only; never import, restore or run a numerical model.

Explicit plan/summary byte pins select one completed four-arm generation. The
analyzer checks saved custody and declared outcomes, without authenticating a
continuous execution, reviewer, legal meaning or independent holdout. It writes
one fresh diagnostic and preserves every input/raw report unchanged.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import math
import os
from pathlib import Path
import random
import re
import stat

F = Path(__file__).resolve().parent
SCHEMA = "saved-structured-span-four-arm-comparison/v1"
CHECKPOINT_SCHEMA = "objective-resumed-source-span-checkpoint/v1"
LINEAGE = "objective_resumed_source_span_v1"
CONTROLS = ("none", "zero", "disabled", "rotate")
FIELDS = ("actor", "action", "object", "conditions", "exceptions", "temporal")
OPTIONAL = FIELDS[2:]
QUALIFIERS = FIELDS[3:]
LOSSES = ("ce", "validity", "overlap", "structure", "weighted_structure", "total")
FALSE = ("qualified", "admitted", "formalized", "roundtrip_ok", "proof_authority",
         "semantic_correctness_verified", "promotion_performed", "publication_performed")
MAX_FILE_BYTES = 128 * 1024 * 1024
MAX_JSON_DEPTH = 64
MAX_JSON_NODES = 10_000_000
_SHA = re.compile(r"[0-9a-f]{64}\Z")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def closed(value, fields, label):
    require(type(value) is dict and set(value) == set(fields), "closed " + label + " required")


def ordinary(value):
    remaining = MAX_JSON_NODES

    def visit(node, depth):
        nonlocal remaining
        remaining -= 1
        require(remaining >= 0 and depth <= MAX_JSON_DEPTH, "bounded ordinary JSON required")
        if type(node) is dict:
            require(all(type(key) is str for key in node), "ordinary JSON string keys required")
            for child in node.values():
                visit(child, depth + 1)
        elif type(node) is list:
            for child in node:
                visit(child, depth + 1)
        elif type(node) is float:
            require(math.isfinite(node), "finite saved JSON required")
        else:
            require(node is None or type(node) in (str, int, bool), "ordinary saved JSON required")
    visit(value, 0)


def wire(value):
    ordinary(value)
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      allow_nan=False).encode("utf-8")


def digest(value):
    return hashlib.sha256(wire(value)).hexdigest()


def sha(value, label):
    require(type(value) is str and _SHA.fullmatch(value), "canonical SHA256 required: " + label)


def false_flags(value, fields=FALSE):
    require(all(value.get(key) is False for key in fields), "saved authority flag promoted")


def integer(value, expected, label):
    require(type(value) is int and value == expected, "saved integer differs: " + label)


def close_number(left, right, label):
    require(type(left) in (int, float) and type(right) in (int, float)
            and math.isfinite(left) and math.isfinite(right)
            and math.isclose(left, right, rel_tol=1e-9, abs_tol=1e-9), "saved scalar arithmetic differs: " + label)


def snapshot(path):
    path = Path(path)
    require(path.is_absolute() and path.resolve(strict=True) == path, "canonical absolute input path required")
    require(all(not entry.is_symlink() for entry in (path, *path.parents)), "input path aliases refused")
    before = path.stat()
    require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and 0 < before.st_size <= MAX_FILE_BYTES,
            "bounded ordinary independent input file required")
    with path.open("rb") as stream:
        opened = os.fstat(stream.fileno())
        raw = stream.read(MAX_FILE_BYTES + 1)
        ending = os.fstat(stream.fileno())
    after = path.stat()
    fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
    require(all(getattr(before, key) == getattr(opened, key) == getattr(ending, key) == getattr(after, key)
                for key in fields) and len(raw) == before.st_size, "input changed while reading")
    return raw, {"path": str(path), "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


class SavedInputs:
    def __init__(self):
        self.pins = {}

    def observed(self, path, expected=None):
        raw, actual = snapshot(path)
        if expected is not None:
            if "path" in expected:
                closed(expected, {"path", "bytes", "sha256"}, "expected artifact pin")
                require(expected == actual, "expected artifact bytes differ: " + str(path))
            else:
                closed(expected, {"bytes", "sha256"}, "expected path-bound artifact pin")
                require({key: actual[key] for key in expected} == expected, "expected artifact bytes differ: " + str(path))
        key = str(path)
        require(key not in self.pins or self.pins[key] == actual, "saved input generation changed")
        self.pins[key] = actual
        return raw, actual

    def read(self, path, expected=None):
        raw, actual = self.observed(path, expected)

        def unique(pairs):
            result = {}
            for key, value in pairs:
                require(key not in result, "duplicate saved JSON field")
                result[key] = value
            return result

        value = json.loads(raw.decode("utf-8"), object_pairs_hook=unique,
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite saved JSON")))
        ordinary(value)
        return value, actual

    def referenced(self, reference, result_directory):
        closed(reference, {"path", "bytes", "sha256"}, "saved result file pin")
        path = Path(reference["path"])
        require(path.parent == result_directory, "saved result reference escaped selected result directory")
        return self.read(path, reference)

    def close(self):
        for path, expected in self.pins.items():
            require(snapshot(path)[1] == expected, "input changed across saved-only analysis: " + path)


def tensor_shape(value, *, nonnegative=False):
    if type(value) is list:
        require(bool(value), "empty saved tensor dimension")
        shapes = [tensor_shape(child, nonnegative=nonnegative) for child in value]
        require(all(shape == shapes[0] for shape in shapes), "ragged saved tensor")
        return (len(value), *shapes[0])
    require(type(value) in (int, float) and math.isfinite(value) and abs(value) <= 3.4028234e38
            and (not nonnegative or value >= 0), "invalid saved float32 state scalar")
    return ()


def state_check(state, parent_base):
    closed(state, {"model_state", "optimizer_state"}, "current checkpoint state")
    weights = state["model_state"]
    original = parent_base["model_state"]
    require(type(weights) is dict and set(weights) == set(original) and len(weights) == 23,
            "all23 model parameter names required")
    optimizer = state["optimizer_state"]
    closed(optimizer, {"schema", "parameters"}, "saved Adam state")
    require(optimizer["schema"] == "adam-default-betas-eps/v1" and set(optimizer["parameters"]) == set(weights),
            "all23 saved Adam parameters required")
    original_optimizer = parent_base["optimizer_state"]
    require(original_optimizer["schema"] == optimizer["schema"]
            and set(original_optimizer["parameters"]) == set(weights), "parent full Adam identity differs")
    shapes = {}
    for name, value in weights.items():
        shape = tensor_shape(value)
        require(shape == tensor_shape(original[name]), "saved parameter shape differs from parent: " + name)
        moment = optimizer["parameters"][name]
        closed(moment, {"step", "exp_avg", "exp_avg_sq"}, "saved parameter Adam moment")
        integer(moment["step"], 432, "final Adam step")
        integer(original_optimizer["parameters"][name]["step"], 400, "parent Adam step")
        require(tensor_shape(moment["exp_avg"]) == shape
                and tensor_shape(moment["exp_avg_sq"], nonnegative=True) == shape,
                "saved model/Adam tensor shape differs")
        shapes[name] = list(shape)
    return {"parameter_count": 23, "all_parent_moment_steps": 400, "all_final_moment_steps": 432,
            "parameter_shapes": shapes, "changed_parameter_names": sorted(name for name in weights if weights[name] != original[name]),
            "changed_moment_parameter_names": sorted(name for name in weights
                if optimizer["parameters"][name] != original_optimizer["parameters"][name]),
            "final_model_state_sha256": digest(weights), "final_optimizer_state_sha256": digest(optimizer)}


def losses(value):
    closed(value, LOSSES, "common diagnostic losses")
    for key, scalar in value.items():
        require(type(scalar) in (int, float) and math.isfinite(scalar) and scalar >= 0,
                "finite nonnegative diagnostic loss required: " + key)
    close_number(value["structure"], (value["validity"] + value["overlap"]) / 2, "structure mean")
    close_number(value["weighted_structure"], value["structure"] * .1, "common weight0.1")
    close_number(value["total"], value["ce"] + value["weighted_structure"], "common total")
    return value


def delta(after, before):
    return {key: after[key] - before[key] for key in LOSSES}


def inference_check(report, checkpoint_sha256, parent_sha256, weight, control, expected_count):
    require(report.get("schema") == "objective-resumed-source-span-inference/v1" and report.get("lineage_id") == LINEAGE,
            "new-lineage inference report required")
    require(report["checkpoint_sha256"] == checkpoint_sha256 and report["historical_parent_sha256"] == parent_sha256
            and report["objective"]["structure_weight"] == weight and report["control"] == control,
            "inference state/objective/control generation mismatch")
    require(len(report["rows"]) == expected_count and report["additional_model_forwards"] == 0
            and report["optimizer_updates"] == 0, "saved inference denominator/extra forward/update differs")
    for flag in ("weights_unchanged", "optimizer_moments_unchanged", "ambient_CPU_RNG_preserved"):
        require(report[flag] is True, "inference custody declaration missing")
    false_flags(report)
    false_flags(report, ("training_executed", "target_access", "teacher_forcing", "native_encoder_executed",
                         "family_bridge_admitted", "Lake_executed"))
    require(report["legal_accuracy"] is None, "legal accuracy must remain unavailable")


def tuning_check(diagnostic, report, tune):
    require(diagnostic["schema"] == "authored-tuning-common-objective-diagnostic/v1"
            and diagnostic["diagnostic_structure_weight"] == .1, "common-.1 authored diagnostic required")
    integer(diagnostic["rows"], 96, "authored TUNE rows")
    integer(diagnostic["expected_exact_ceiling"], 96, "TUNE ceiling")
    require(diagnostic["teacher_forcing_for_loss"] is True and diagnostic["greedy_inference_target_access"] is False
            and diagnostic["training_executed"] is False and diagnostic["used_for_selection"] is False
            and diagnostic["semantic_accuracy"] is None and diagnostic["source_semantics_verified"] is False
            and diagnostic["qualified"] is False, "authored tuning scope promoted")
    require(len(report["rows"]) == len(tune) == 96 and report["same_forward_scores"] is False,
            "greedy TUNE denominator or score-capture flag differs")
    matches, counts = [], Counter()
    for position, (row, target) in enumerate(zip(report["rows"], tune, strict=True)):
        require(row["id"] == target["id"] and row["position"] == position
                and row["source_sha256"] == hashlib.sha256(target["source_text"].encode()).hexdigest(),
                "authored source/greedy row join mismatch")
        require(row["scores"] is None, "TUNE greedy scores unexpectedly captured")
        raw = row["decoder_row"]
        false_flags(raw)
        matched = wire(raw["canonical_ir"]) == wire(target["canonical_ir"])
        if matched:
            matches.append(row["id"])
        counts[raw["status"] if raw["reason"] is None else raw["reason"]] += 1
    integer(diagnostic["exact_canonical_ir"], len(matches), "independently replayed authored exact count")
    return {"losses": deepcopy_json(losses(diagnostic["losses"])), "exact_canonical_ir": len(matches),
            "expected_count": 96, "outcomes": dict(counts), "nonmatching_ids": [row["id"] for row in report["rows"] if row["id"] not in set(matches)],
            "comparison_scope": "exposed_authored_targets_only_not_statutory_fidelity"}


def deepcopy_json(value):
    return json.loads(wire(value))


def source_tokens(scores, text):
    closed(scores, {"schema", "tokens", "modality_logits", "presence_logits", "start_logits", "end_logits"}, "same-forward scores")
    require(scores["schema"] == "joint-source-span-scores/v1", "same-forward score schema differs")
    tokens = scores["tokens"]
    require(type(tokens) is list and 1 <= len(tokens) <= 256, "bounded actual source tokens required")
    previous = 0
    for token in tokens:
        closed(token, {"text", "start", "end"}, "copied score token")
        left, right = token["start"], token["end"]
        require(type(left) is int and type(right) is int and previous <= left < right <= len(text)
                and text[left:right] == token["text"], "score token/source selector mismatch")
        previous = right
    vectors = [scores["modality_logits"]]
    require(len(vectors[0]) == 3, "three modality logits required")
    closed(scores["presence_logits"], OPTIONAL, "presence heads")
    closed(scores["start_logits"], FIELDS, "start heads")
    closed(scores["end_logits"], FIELDS, "end heads")
    for field in OPTIONAL:
        require(len(scores["presence_logits"][field]) == 2, "two optional presence logits required")
        vectors.append(scores["presence_logits"][field])
    for kind in ("start_logits", "end_logits"):
        for field in FIELDS:
            require(len(scores[kind][field]) == len(tokens), "actual pointer length differs")
            vectors.append(scores[kind][field])
    require(all(type(value) in (int, float) and math.isfinite(value) and abs(value) <= 3.4028234e38
                for vector in vectors for value in vector), "finite float32-range saved scores required")
    return tokens


def copied_rule(ir, diagnostics, text, tokens, *, joint):
    closed(ir, {"rules"}, "copied canonical IR")
    require(type(ir["rules"]) is list and len(ir["rules"]) == 1, "single copied rule required")
    rule = ir["rules"][0]
    closed(rule, {"modality", *FIELDS}, "copied deontic rule")
    require(rule["modality"] in ("O", "P", "F"), "known deontic modality required")
    occupied = set()
    for field in FIELDS:
        diagnostic = diagnostics[field]
        span = diagnostic["span"] if joint else diagnostic if diagnostic["present"] else None
        value = rule[field]
        require(type(diagnostic["present"]) is bool and (span is not None) is diagnostic["present"],
                "selected copied presence/span mismatch")
        require(field not in ("actor", "action") or diagnostic["present"], "required copied actor/action missing")
        if span is None:
            require(value == ([] if field in QUALIFIERS else ""), "absent copied facet differs")
            continue
        left, right = span["char_start"], span["char_end"]
        require(type(left) is int and type(right) is int and 0 <= left < right <= len(text)
                and text[left:right] == span["text"], "copied literal interval mismatch")
        if joint:
            require(text.encode()[span["utf8_byte_start"]:span["utf8_byte_end"]].decode() == span["text"],
                    "copied UTF8/character selector mismatch")
        require(value == ([span["text"]] if field in QUALIFIERS else span["text"]), "copied facet/payload differs")
        begin, end = span["token_start"], span["token_end_inclusive"]
        require(type(begin) is int and type(end) is int and 0 <= begin <= end < len(tokens)
                and tokens[begin]["start"] == left and tokens[end]["end"] == right,
                "copied token/source interval differs")
        positions = set(range(begin, end + 1))
        require(not positions & occupied, "selected copied facets overlap")
        occupied.update(positions)


def law_check(raw, joint, law, control):
    require(joint["schema"] == "structured-span-exposed-law-joint-diagnostic/v1"
            and joint["top_k"] == 8 and joint["max_search_nodes"] == 50000
            and joint["learned_presence_and_modality_fixed"] is True and joint["raw_greedy_preserved"] is True
            and joint["semantic_accuracy"] is None and joint["qualified"] is False
            and joint["used_for_updates_or_selection"] is False, "joint diagnostic contract differs")
    require(len(raw["rows"]) == len(joint["rows"]) == len(law) == 8 and raw["same_forward_scores"] is True,
            "real8 source/raw/joint denominator or score capture differs")
    greedy_counts, joint_counts, details = Counter(), Counter(), []
    for position, (row, selected, source) in enumerate(zip(raw["rows"], joint["rows"], law, strict=True)):
        require(row["id"] == selected["id"] == source["id"] and row["position"] == position
                and row["source_sha256"] == hashlib.sha256(source["source_text"].encode()).hexdigest(),
                "real8 source/raw/joint identity mismatch")
        donor = (position + 1) % 8 if control == "rotate" else position
        vector = [0.] * 384 if control == "zero" else law[donor]["latent"]
        require(row["latent_donor_position"] == donor and row["latent_donor_id"] == law[donor]["id"]
                and row["effective_latent_sha256"] == digest(vector), "saved latent-control donor/vector join differs")
        decoder = row["decoder_row"]
        false_flags(decoder)
        greedy_counts[decoder["status"] if decoder["reason"] is None else decoder["reason"]] += 1
        scores, result = row["scores"], selected["result"]
        if scores is None:
            require(result is None and decoder["reason"] in ("source_too_long", "source_encoding_rejected"), "unsubmitted score denominator differs")
            joint_counts["unsubmitted_source"] += 1
            details.append({"id": row["id"], "greedy_reason": decoder["reason"], "joint_reason": "unsubmitted_source"})
            continue
        tokens = source_tokens(scores, source["source_text"])
        require(result is not None, "submitted score row lacks preserved joint result")
        false_flags(result)
        require(result["source_sha256"] == row["source_sha256"] and result["scores_sha256"] == digest(scores)
                and result["input_token_count"] == len(tokens), "joint source/full-score generation join differs")
        joint_counts[result["status"] if result["reason"] is None else result["reason"]] += 1
        decisions = result["fixed_decisions"]
        modality = ("O", "P", "F")[max(range(3), key=lambda index: scores["modality_logits"][index])]
        require(decisions["modality"] == modality, "joint modality changed from saved head argmax")
        for field in FIELDS:
            present = field in ("actor", "action") or scores["presence_logits"][field][1] > scores["presence_logits"][field][0]
            require(decisions["facets"][field]["present"] is present, "joint presence changed from saved head argmax")
        if decoder["status"] == "decoded":
            require(decoder["reason"] is None and decoder["family_syntax_checked"] is True, "decoded greedy syntax flag differs")
            copied_rule(decoder["canonical_ir"], decoder["span_diagnostics"]["facets"], source["source_text"], tokens, joint=False)
        if result["status"] == "selected":
            require(result["reason"] is None and result["canonical_rule_valid"] is True and result["family_syntax_checked"] is True,
                    "selected joint syntax flags differ")
            copied_rule(result["canonical_ir"], result["span_diagnostics"], source["source_text"], tokens, joint=True)
            require(result["canonical_ir"]["rules"][0]["modality"] == modality, "selected modality payload changed")
            for field in FIELDS:
                require(result["span_diagnostics"][field]["present"] is decisions["facets"][field]["present"], "selected presence payload changed")
                span = result["span_diagnostics"][field]["span"]
                if span is not None:
                    require(span["token_end_inclusive"] < len(tokens)
                            and tokens[span["token_start"]]["start"] == span["char_start"]
                            and tokens[span["token_end_inclusive"]]["end"] == span["char_end"], "selected token/source interval join differs")
            require(result["search"]["retained_domain_optimality_established"] is True
                    and result["search"]["unique_within_guard"] is True, "selected retained-pool search incomplete")
        details.append({"id": row["id"], "greedy_status": decoder["status"], "greedy_reason": decoder["reason"],
            "greedy_canonical_ir": decoder["canonical_ir"], "joint_status": result["status"], "joint_reason": result["reason"],
            "joint_canonical_ir": result["canonical_ir"], "candidate_domain_truncated": result["candidate_domain_truncated"],
            "search": result["search"]})
    return {"requested": 8, "greedy_outcomes": dict(greedy_counts), "joint_outcomes": dict(joint_counts),
            "greedy_decoded_count": greedy_counts["decoded"], "joint_selected_count": joint_counts["selected"],
            "truncated_search_count": sum(row.get("candidate_domain_truncated", False) for row in details),
            "search_budget_exhausted_count": sum(row.get("search", {}).get("budget_exhausted", False) for row in details),
            "full_domain_optimality_established_count": sum(row.get("search", {}).get("full_domain_optimality_established", False) for row in details),
            "rows": details, "semantic_accuracy": None}


def differences(raw_a, joint_a, raw_b, joint_b):
    result = {key: [] for key in ("score_changed_ids", "greedy_IR_changed_ids", "greedy_disposition_changed_ids",
                                  "joint_IR_changed_ids", "joint_disposition_changed_ids")}
    for a, ja, b, jb in zip(raw_a["rows"], joint_a["rows"], raw_b["rows"], joint_b["rows"], strict=True):
        require(a["id"] == ja["id"] == b["id"] == jb["id"], "cross-report source order differs")
        identity = a["id"]
        if wire(a["scores"]) != wire(b["scores"]):
            result["score_changed_ids"].append(identity)
        da, db = a["decoder_row"], b["decoder_row"]
        if wire(da["canonical_ir"]) != wire(db["canonical_ir"]):
            result["greedy_IR_changed_ids"].append(identity)
        if (da["status"], da["reason"]) != (db["status"], db["reason"]):
            result["greedy_disposition_changed_ids"].append(identity)
        ra, rb = ja["result"], jb["result"]
        if wire(None if ra is None else ra["canonical_ir"]) != wire(None if rb is None else rb["canonical_ir"]):
            result["joint_IR_changed_ids"].append(identity)
        if (None if ra is None else (ra["status"], ra["reason"])) != (None if rb is None else (rb["status"], rb["reason"])):
            result["joint_disposition_changed_ids"].append(identity)
    return result


def main(args):
    sha(args.plan_sha256, "selected plan")
    sha(args.summary_sha256, "selected summary")
    inputs = SavedInputs()
    _, analyzer_pin = inputs.observed(Path(__file__).resolve())
    plan, plan_pin = inputs.read(Path(args.plan))
    summary, summary_pin = inputs.read(Path(args.summary))
    require(plan_pin["sha256"] == args.plan_sha256 and summary_pin["sha256"] == args.summary_sha256, "externally selected plan/summary bytes differ")
    require(plan["schema"] == "structured-source-span-four-arm-plan/v1" and summary["schema"] == "structured-span-four-arm-results/v1"
            and summary["status"] == "completed", "one completed four-arm generation required")
    directory = Path(args.summary).parent
    for path, expected in plan["artifacts"].items():
        inputs.observed(Path(path), expected)
    require(summary["actual_new_updates"] == 128 and summary["actual_encoder_calls"] == 0
            and summary["equal_step_count"] == 32 and summary["equal_batch_schedule"] is True
            and summary["original_artifacts_byte_exact"] is True, "completed comparison counters/custody differ")
    false_flags(summary, ("source_semantics_verified", "independent_semantic_holdout", "legal_fidelity_qualified",
                         "checkpoint_selection_executed", "default_promotion", "eight_dimensional_trained",
                         "seven_sixty_eight_trained", "Lake_executed", "full_third_party_import_graph_qualified"))
    require(summary["semantic_accuracy"] is None and summary["trained_dimensions"] == [384]
            and summary["authored_tuning_previously_exposed"] is True and summary["law_previously_exposed"] is True,
            "selection/semantic/exposure scope promoted")
    export, _ = inputs.read(Path(plan["train_tune_export"]["path"]), plan["train_tune_export"])
    law_export, _ = inputs.read(Path(plan["law_diagnostic_export"]["path"]), plan["law_diagnostic_export"])
    train, tune, law = export["populations"]["train"], export["populations"]["tuning"], law_export["rows"]
    require(len(train) == 1152 and len(tune) == 96 and len(law) == 8
            and export["semantic_gold"] is False and law_export["semantic_gold"] is False
            and law_export["used_for_updates_or_selection"] is False, "saved population/exposure contract differs")
    require(len({row["id"] for row in train}) == 1152 and len({row["id"] for row in tune}) == 96
            and len({row["id"] for row in law}) == 8, "unique source population IDs required")
    prepared, _ = inputs.read(directory / "all-arm-plans-before-opening.json")
    probes, probes_pin = inputs.read(directory / "numerical-probes.json")
    require(probes["schema"] == "structured-span-numerical-probes/v1" and probes["passed"] is True
            and probes["findings"] == [] and probes["actual_model_forwards"] == 0 and probes["actual_optimizer_updates"] == 0,
            "saved synthetic numerical probe receipt differs")
    for flag in ("same_output_CE_bit_exact", "same_output_CE_gradients_bit_exact", "finite_all_head_gradients", "structural_padding_invariance"):
        require(probes[flag] is True, "saved probe failure: " + flag)
    close_number(probes["validity"], math.log(4 / 3), "saved uniformN2 validity")
    close_number(probes["overlap"], 7 / 9, "saved uniformN2 overlap")
    initial = {row["name"]: row for row in prepared}
    recipes = {row["name"]: row for row in plan["arms"]}
    require(len(initial) == len(recipes) == len(summary["arms"]) == 4 and set(initial) == set(recipes), "four planned arms required")
    baselines, baseline_pins = {}, []
    for baseline in summary["baseline_tuning"]:
        parent_name = baseline["name"]
        require(parent_name not in baselines, "duplicate baseline parent")
        report, reference = inputs.referenced(baseline["authored_greedy"], directory)
        recipe = recipes[parent_name + "-ce0"]
        inference_check(report, initial[recipe["name"]]["initial_checkpoint_sha256"], recipe["parent_canonical_sha256"], 0., "none", 96)
        baselines[parent_name] = tuning_check(baseline["diagnostic"], report, tune)
        baseline_pins.append(reference)
    require(len(baselines) == 2, "both retained-parent baselines required")
    arms, raw_reports, joint_reports, actual_batches, arm_names = [], {}, {}, [], set()
    for item in summary["arms"]:
        name = item["name"]
        require(name in recipes and name not in arm_names, "unknown or duplicate fitted arm")
        arm_names.add(name)
        recipe, preparation = recipes[name], initial[name]
        parent, parent_pin = inputs.read(Path(recipe["parent_file_pin"]["path"]), recipe["parent_file_pin"])
        require(digest(parent) == recipe["parent_canonical_sha256"], "original parent canonical SHA differs")
        checkpoint, checkpoint_pin = inputs.referenced(item["checkpoint"], directory)
        checkpoint_fields = {"schema", "lineage_id", "implementation", "objective", "initialization", "historical_parent",
            "historical_parent_sha256", "context_contract", "context_contract_sha256", "training_manifest_sha256", "training_count",
            "tuning_manifest_sha256", "tuning_count", "initial_model_state_sha256", "initial_optimizer_state_sha256", "state",
            "progress", "previous_checkpoint_sha256", *FALSE}
        closed(checkpoint, checkpoint_fields, "objective continuation checkpoint")
        require(checkpoint["schema"] == CHECKPOINT_SCHEMA and checkpoint["lineage_id"] == LINEAGE
                and digest(checkpoint) == checkpoint_pin["sha256"], "new checkpoint schema/canonical saved digest differs")
        false_flags(checkpoint)
        require(wire(checkpoint["historical_parent"]) == wire(parent)
                and checkpoint["historical_parent_sha256"] == recipe["parent_canonical_sha256"], "embedded historical parent changed")
        base = parent["base_checkpoint"]
        implementation = checkpoint["implementation"]
        closed(implementation, {"worker_sha256", "base_span", "retained_warm_owner", "objective_sha256"}, "continuation implementation")
        require(implementation["worker_sha256"] == plan["additional_owner_pins"]["ipfs_datasets_py.logic.formalization.autoencoder.structured_span_continuation"]["sha256"]
                and implementation["objective_sha256"] == plan["additional_owner_pins"]["ipfs_datasets_py.logic.legal_ir.structured_span_objective"]["sha256"]
                and implementation["base_span"] == base["implementation"]
                and implementation["retained_warm_owner"] == parent["implementation"], "saved numerical-owner identity differs")
        initialization = checkpoint["initialization"]
        require(initialization["mode"] == "exact_retained_warm_parent_model_and_full_Adam_resumption"
                and initialization["all_parent_model_tensors_copied"] is True
                and initialization["parent_optimizer_moments_transferred"] is True
                and initialization["parent_epoch_and_cursor_transferred"] is True
                and initialization["fresh_optimizer"] is False, "full retained initialization declaration differs")
        require(base["progress"] == {"epochs_completed": 4, "row_cursor": 192, "optimizer_steps": 400}, "retained parent boundary differs")
        objective = checkpoint["objective"]
        require(objective["schema"] == "source-span-order-overlap-probability/v1"
                and objective["structure_weight"] == recipe["structure_weight"]
                and objective["base_ce"] == "equal_facet_modality_presence_mean_start_end/v1", "outer objective lineage differs")
        require(checkpoint["context_contract"] == parent["context_contract"]
                and checkpoint["context_contract_sha256"] == digest(parent["context_contract"]), "inherited context contract differs")
        require(checkpoint["initial_model_state_sha256"] == digest(base["model_state"])
                and checkpoint["initial_optimizer_state_sha256"] == digest(base["optimizer_state"]), "initial full model/Adam SHA differs")
        for field, rows, count in (("training", train, 1152), ("tuning", tune, 96)):
            integer(checkpoint[field + "_count"], count, field + " population count")
            require(checkpoint[field + "_manifest_sha256"] == base[field + "_manifest_sha256"] == digest(rows), "exact ordered authored manifest differs")
        expected_progress = {"inherited_optimizer_steps": 400, "new_optimizer_steps": 32, "absolute_optimizer_steps": 432,
                             "epochs_completed": 4, "row_cursor": 576}
        require(checkpoint["progress"] == expected_progress and all(type(value) is int for value in checkpoint["progress"].values()),
                "final inherited/new/absolute/epoch/cursor differs")
        state = state_check(checkpoint["state"], base)
        require(bool(state["changed_parameter_names"]), "actual fitted model has no changed parameters")
        training, training_pin = inputs.referenced(item["training"], directory)
        false_flags(training)
        require(training["schema"] == "objective-resumed-source-span-training/v1" and training["lineage_id"] == LINEAGE
                and training["checkpoint_sha256"] == digest(checkpoint)
                and training["historical_parent_sha256"] == recipe["parent_canonical_sha256"]
                and training["objective"] == objective and training["progress"] == expected_progress,
                "training report checkpoint/objective/progress generation differs")
        require(training["actual_new_updates"] == training["requested_new_updates"] == len(training["batch_components"]) == 32
                and training["actual_TRAIN_rows"] == 384 and training["complete"] is True and training["training_executed"] is True,
                "actual32-step completed training required")
        require(training["inherited_full_Adam_preserved_at_entry"] is True and training["historical_parent_unchanged"] is True
                and training["ambient_CPU_RNG_preserved"] is True and training["tuning_used_for_updates"] is False
                and training["targets_embedded_in_new_state"] is False, "training custody/admission scope differs")
        batches = training["batch_ids"]
        training_ids = {row["id"] for row in train}
        order = list(range(1152))
        random.Random(1729 + 4).shuffle(order)
        independently_expected_batches = [[train[index]["id"] for index in order[at:at + 12]]
                                          for at in range(192, 576, 12)]
        require(len(batches) == 32 and all(len(batch) == 12 and len(set(batch)) == 12 for batch in batches)
                and all(identity in training_ids for batch in batches for identity in batch), "TRAIN-only batch geometry differs")
        for components in training["batch_components"]:
            closed(components, LOSSES, "saved batch loss components")
            require(all(type(value) in (int, float) and math.isfinite(value) and value >= 0 for value in components.values()),
                    "saved batch components are nonfinite/negative")
            close_number(components["structure"], (components["validity"] + components["overlap"]) / 2, "batch structure")
            close_number(components["weighted_structure"], components["structure"] * recipe["structure_weight"], "batch weighted structure")
            close_number(components["total"], components["ce"] + components["weighted_structure"], "batch total")
            if recipe["structure_weight"] == 0:
                require(all(components[key] == 0 for key in ("validity", "overlap", "structure", "weighted_structure"))
                        and components["total"] == components["ce"], "CE0 batch arithmetic differs")
        require(batches == preparation["batch_ids"] and digest(batches) == training["batch_ids_sha256"] == preparation["batch_ids_sha256"],
                "actual/prepared batch schedule differs")
        require(batches == independently_expected_batches, "retained deterministic epoch4/cursor192 schedule differs")
        require(checkpoint["previous_checkpoint_sha256"] == training["previous_checkpoint_sha256"] == preparation["initial_checkpoint_sha256"],
                "new state predecessor generation differs")
        require(sorted(training["changed_parameter_names"]) == state["changed_parameter_names"], "saved changed-parameter report differs")
        actual_batches.append(batches)
        tuning_report, tuning_pin = inputs.referenced(item["tuning_greedy"], directory)
        inference_check(tuning_report, digest(checkpoint), recipe["parent_canonical_sha256"], recipe["structure_weight"], "none", 96)
        tuning_result = tuning_check(item["tuning_diagnostic"], tuning_report, tune)
        parent_name = name.rsplit("-", 1)[0]
        controls = []
        require([control["control"] for control in item["law_controls"]] == list(CONTROLS), "all four ordered controls required")
        for control_entry in item["law_controls"]:
            control = control_entry["control"]
            raw, raw_pin = inputs.referenced(control_entry["raw_inference"], directory)
            joint, joint_pin = inputs.referenced(control_entry["joint"], directory)
            inference_check(raw, digest(checkpoint), recipe["parent_canonical_sha256"], recipe["structure_weight"], control, 8)
            require(raw["actual_source_forwards"] == 8, "actual8 same-forward law sources required")
            details = law_check(raw, joint, law, control)
            controls.append({"control": control, "raw_report_pin": raw_pin, "joint_report_pin": joint_pin, **details})
            raw_reports[name, control], joint_reports[name, control] = raw, joint
        arms.append({"name": name, "parent": parent_name, "structure_weight": recipe["structure_weight"],
            "historical_parent_pin": parent_pin, "checkpoint_pin": checkpoint_pin, "training_pin": training_pin,
            "tuning_greedy_pin": tuning_pin, "state": state, "progress": expected_progress,
            "actual_new_updates": 32, "actual_TRAIN_rows": 384, "batch_ids_sha256": digest(batches),
            "common_weight01_tuning": tuning_result,
            "common_weight01_loss_difference_from_parent": delta(tuning_result["losses"], baselines[parent_name]["losses"]),
            "authored_exact_count_difference_from_parent": tuning_result["exact_canonical_ir"] - baselines[parent_name]["exact_canonical_ir"],
            "law_controls": controls})
    require(all(batch == actual_batches[0] for batch in actual_batches), "four-arm actual batch schedules differ")
    by_name = {arm["name"]: arm for arm in arms}
    pairs, comparisons = [], []
    for parent_name in baselines:
        ce, structured = by_name[parent_name + "-ce0"], by_name[parent_name + "-probability01"]
        require(ce["historical_parent_pin"] == structured["historical_parent_pin"], "paired objectives do not share exact parent bytes")
        pairs.append({"parent": parent_name, "CE_arm": ce["name"], "structured_arm": structured["name"],
            "common_weight01_loss_difference_structured_minus_CE": delta(structured["common_weight01_tuning"]["losses"], ce["common_weight01_tuning"]["losses"]),
            "authored_exact_count_difference_structured_minus_CE": structured["common_weight01_tuning"]["exact_canonical_ir"] - ce["common_weight01_tuning"]["exact_canonical_ir"],
            "model_parameter_changes_between_fitted_arms_observed": ce["state"]["final_model_state_sha256"] != structured["state"]["final_model_state_sha256"],
            "equal_initial_parent_full_Adam_and_schedule": True,
            "law_per_control": [{"control": control, **differences(raw_reports[ce["name"], control], joint_reports[ce["name"], control],
                raw_reports[structured["name"], control], joint_reports[structured["name"], control])} for control in CONTROLS]})
    for name in sorted(by_name):
        for control in CONTROLS[1:]:
            comparisons.append({"name": name, "normal_control": "none", "comparison_control": control,
                **differences(raw_reports[name, "none"], joint_reports[name, "none"], raw_reports[name, control], joint_reports[name, control])})
    require(sum(arm["actual_new_updates"] for arm in arms) == 128, "actual total updates differ")
    inputs.close()
    value = {"schema": SCHEMA, "passed": True, "findings": [], "scope": "saved_JSON_byte_and_declared_geometry_comparison_only",
        "analyzer_pin": analyzer_pin, "selected_plan_pin": plan_pin, "selected_summary_pin": summary_pin,
        "inputs": inputs.pins, "numerical_probe_receipt": probes_pin, "saved_probe_claims_replayed": probes,
        "source_count": 8, "requested_law_dispositions": 128, "actual_new_updates": 128,
        "per_arm_new_updates": 32, "actual_TRAIN_row_visits": 1536, "all_actual_batch_schedules_equal": True,
        "all23_Adam_steps_400_to_432": True, "all_new_checkpoints_distinct_schema_and_full_saved_digest_verified": True,
        "historical_parents_and_all_plan_artifacts_byte_exact": True, "every_raw_report_preserved": True,
        "baseline_tuning": baselines, "baseline_greedy_report_pins": baseline_pins, "arms": arms,
        "paired_objective_comparisons": pairs, "within_state_latent_control_comparisons": comparisons,
        "semantic_accuracy": None, "semantic_gain_established": False, "semantic_gold": False,
        "independent_semantic_holdout": False, "checkpoint_selection_executed": False, "default_promotion": False,
        "new_encoder_calls": 0, "model_calls_by_analyzer": 0, "model_or_numerical_imports_by_analyzer": False,
        "Lake_executed": False, "family_bridge_admitted": False, "qualified": False, "proof_authority": False,
        "limitations": [
            "Common-.1 losses and exact matches use exposed authored targets, not independently reviewed statute meanings.",
            "The eight exposed legal sources are repeated across16 lanes;128 dispositions are not128 independent observations.",
            "Copied syntax/order/nonoverlap, score changes and latent-control differences do not authenticate actor/action roles or legal fidelity.",
            "Top8 retained pools and explicit search budgets do not establish full-domain optimum unless separately reported for a row.",
            "This analyzer verifies saved bytes and internal joins, not continuous independent numerical-execution attestation or resource peaks.",
            "No states are selected or promoted; genuine8D/native768, broader logic-family semantics and Lean remain unqualified.",
        ]}
    value["content_sha256"] = digest(value)
    path = Path(args.output)
    require(path.is_absolute() and path.parent.resolve(strict=True) == path.parent and not path.exists(), "fresh canonical output path required")
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, ensure_ascii=True, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    print(json.dumps({"diagnostics": snapshot(path)[1], "actual_new_updates": 128,
        "arms": [{"name": arm["name"], "authored_exact": arm["common_weight01_tuning"]["exact_canonical_ir"],
                  "common_losses": arm["common_weight01_tuning"]["losses"],
                  "normal_law_greedy": arm["law_controls"][0]["greedy_decoded_count"],
                  "normal_law_joint": arm["law_controls"][0]["joint_selected_count"]} for arm in arms]}, sort_keys=True))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", required=True)
    parser.add_argument("--plan-sha256", required=True)
    parser.add_argument("--summary", required=True)
    parser.add_argument("--summary-sha256", required=True)
    parser.add_argument("--output", default=str(F / "structured-comparison-diagnostics.json"))
    main(parser.parse_args())
