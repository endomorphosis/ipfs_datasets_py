#!/usr/bin/env python3
"""Independent record/tensor audit after the grounding experiment's build freeze.

This rechecks recorded state, annotations, source coordinates and counts. It does
not replay optimizer trajectories or perform another compiler invocation.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import inspect
import json
import math
from pathlib import Path
import re
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
FIELDS = ("actor", "action", "object", "conditions", "exceptions", "temporal")
EXTRA = ("trigger_boundary.", "trigger_modality.", "actor_boundary.")


def require(test, message):
    if not test:
        raise ValueError(message)


def raw(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(raw(value)).hexdigest()


def ref(path):
    path = Path(path).resolve()
    data = path.read_bytes()
    return {"path": str(path), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def read_ref(reference):
    data = Path(reference["path"]).read_bytes()
    require(hashlib.sha256(data).hexdigest() == reference["sha256"], "artifact hash differs")
    require("bytes" not in reference or len(data) == reference["bytes"], "artifact size differs")
    return json.loads(data)


def flatten(value):
    if isinstance(value, list):
        for child in value:
            yield from flatten(child)
    else:
        require(type(value) in (int, float) and math.isfinite(value), "nonfinite tensor value")
        yield value


def tensor_difference(before, after):
    a, b = list(flatten(before)), list(flatten(after))
    require(len(a) == len(b), "tensor element counts differ")
    return {"elements": len(a), "changed_elements": sum(x != y for x, y in zip(a, b)),
            "delta_l2": math.sqrt(math.fsum((x - y) ** 2 for x, y in zip(a, b)))}


def verify_prediction(prediction, source):
    text = source["source_text"]
    require(prediction["source_sha256"] == hashlib.sha256(text.encode()).hexdigest(), "prediction source differs")
    require(prediction["target_access"] is False and prediction["teacher_forcing"] is False, "reference-conditioned prediction")
    require(prediction["status"] in {"decoded", "abstained"}, "unexpected status")
    if prediction["status"] == "abstained":
        require(prediction["canonical_ir"] is None and not prediction["formal_outputs"], "abstention emitted a rule")
        return 0
    ir = prediction["canonical_ir"]
    require(set(ir) == {"rules"} and len(ir["rules"]) == 1, "single rule required")
    rule = ir["rules"][0]
    require(set(rule) == {"modality", *FIELDS} and rule["modality"] in {"O", "P", "F"}, "invalid rule schema")
    tokens = [{"text": m.group(), "start": m.start(), "end": m.end()} for m in re.finditer(r"\w+|[^\w\s]", text)]
    diagnostics = prediction["span_diagnostics"]
    require(diagnostics["tokens"] == tokens and set(diagnostics["facets"]) == set(FIELDS), "source tokens/facets differ")
    occupied, copied = set(), 0
    for field in FIELDS:
        value = rule[field]
        atoms = value if field in FIELDS[3:] else [value] if value else []
        require(type(atoms) is list and len(atoms) <= 1, "invalid facet cardinality")
        info = diagnostics["facets"][field]
        require(info["present"] is bool(atoms), "presence differs")
        if not atoms:
            require(all(info[k] is None for k in ("char_start", "char_end", "token_start", "token_end_inclusive", "text")), "absent facet has span")
            continue
        left, right = info["token_start"], info["token_end_inclusive"]
        require(type(left) is int and type(right) is int and 0 <= left <= right < len(tokens), "invalid token range")
        a, b = tokens[left]["start"], tokens[right]["end"]
        require([info["char_start"], info["char_end"]] == [a, b] and text[a:b] == info["text"] == atoms[0], "copy coordinates differ")
        positions = set(range(left, right + 1))
        require(not positions & occupied, "copied spans overlap")
        occupied |= positions
        copied += 1
    require(json.loads(prediction["formula_text"]) == ir, "display differs from AST")
    outputs = prediction["formal_outputs"]
    require(len(outputs) == 1 and outputs[0]["family"] == "deontic" and outputs[0]["payload"] == rule, "native formal output differs")
    return copied


def independent_metrics(generation, sources, targets):
    require(len(generation["rows"]) == len(sources) == len(targets), "metric denominators differ")
    indexed = {r["id"]: r for r in targets}
    require(len(indexed) == len(targets) and set(indexed) == {r["id"] for r in sources}, "target coverage differs")
    counts, confusion, facets, coordinates = Counter(), Counter(), Counter(), Counter()
    row_results = []
    for prediction, source in zip(generation["rows"], sources):
        target = indexed[source["id"]]
        require(target.get("source_text", source["source_text"]) == source["source_text"], "target source differs")
        require(target.get("source_sha256", source["source_sha256"]) == source["source_sha256"], "target source hash differs")
        counts["source_copied_facets"] += verify_prediction(prediction, source)
        counts["count"] += 1
        counts[prediction["status"]] += 1
        decoded = prediction["status"] == "decoded"
        exact = decoded and prediction["canonical_ir"] == target["canonical_ir"]
        counts["exact"] += exact
        wanted = target["canonical_ir"]["rules"][0]
        actual = prediction["canonical_ir"]["rules"][0] if decoded else None
        confusion[(wanted["modality"], actual["modality"] if decoded else "abstained")] += 1
        errors = []
        for field in ("modality", *FIELDS):
            correct = bool(decoded and actual[field] == wanted[field])
            facets[field] += correct
            if not correct:
                errors.append(field)
        actor_start_ok = actor_end_ok = None
        if "facet_spans" in target:
            counts["coordinate_targets"] += 1
            for field, span in target["facet_spans"].items():
                info = prediction.get("span_diagnostics", {}).get("facets", {}).get(field, {})
                observed = [info.get("char_start"), info.get("char_end")] if info.get("present") else None
                coordinates[field] += bool(decoded and observed == span)
            modal = prediction.get("grounding_diagnostics", {}).get("trigger", {})
            counts["trigger_head_available"] += bool(modal)
            counts["trigger_span_exact"] += [modal.get("char_start"), modal.get("char_end")] == target["trigger_span"]
            actor = prediction.get("span_diagnostics", {}).get("facets", {}).get("actor", {})
            actor_start_ok = actor.get("char_start") == target["facet_spans"]["actor"][0]
            actor_end_ok = actor.get("char_end") == target["facet_spans"]["actor"][1]
            counts["actor_start_exact_including_abstentions"] += actor_start_ok
            counts["actor_end_exact_including_abstentions"] += actor_end_ok
            counts["actor_span_exact_including_abstentions"] += actor_start_ok and actor_end_ok
            counts["abstained_with_correct_actor_span"] += not decoded and actor_start_ok and actor_end_ok
        row_results.append({"id": source["id"], "exact": exact, "status": prediction["status"],
            "facet_errors": errors, "actor_start_exact": actor_start_ok, "actor_end_exact": actor_end_ok})
    for key in ("count", "decoded", "abstained", "exact", "coordinate_targets", "trigger_head_available", "trigger_span_exact"):
        counts.setdefault(key, 0)
    return {**counts, "facet_exact": dict(facets), "decoded_facet_coordinate_exact": dict(coordinates),
        "modality_confusion": {a + "->" + b: n for (a, b), n in sorted(confusion.items())}, "rows": row_results}


def verify_coordinate_targets(targets, meanings):
    for row in targets:
        text = row["source_text"]
        tokens = list(re.finditer(r"\w+|[^\w\s]", text))
        starts, ends = {m.start() for m in tokens}, {m.end() for m in tokens}
        rule = row["canonical_ir"]["rules"][0]
        occupied = []
        for field, span in {**row["facet_spans"], "trigger": row["trigger_span"]}.items():
            if field == "trigger":
                expected = None
            else:
                value = rule[field]
                expected = value[0] if field in FIELDS[3:] and value else None if field in FIELDS[3:] else value
            if span is None:
                require(expected is None and field != "trigger", "absent target span differs")
                continue
            a, b = span
            require(type(a) is int and type(b) is int and 0 <= a < b <= len(text) and a in starts and b in ends, "target span is not token aligned")
            require(all(not (a < right and left < b) for left, right in occupied), "target spans overlap")
            occupied.append((a, b))
            require(meanings.get(text[a:b]) == rule["modality"] if field == "trigger" else text[a:b] == expected, "target coordinate binding differs")


def construction_errors(rows, membership):
    groups = {}
    for row in rows:
        group = groups.setdefault(membership[row["id"]], {"count": 0, "exact": 0, "abstained": 0,
            "actor_start_errors": 0, "actor_end_errors": 0, "facet_errors": Counter()})
        group["count"] += 1
        group["exact"] += row["exact"]
        group["abstained"] += row["status"] == "abstained"
        group["actor_start_errors"] += row["actor_start_exact"] is False
        group["actor_end_errors"] += row["actor_end_exact"] is False
        group["facet_errors"].update(row["facet_errors"])
    return {name: {**group, "facet_errors": dict(group["facet_errors"])} for name, group in groups.items()}


def check_target_read_order(runner, config_path, target_paths):
    """Exercise real fitting loader under a target deny-read guard."""
    original_path_open = Path.open

    def guarded(path, *args, **kwargs):
        require(str(path.resolve()) not in target_paths, "fitting loader opened sealed targets")
        return original_path_open(path, *args, **kwargs)

    with patch.object(Path, "open", guarded):
        loaded = runner.load_config(config_path)
    source = inspect.getsource(runner.run_qualification)
    build_freeze = source.index('builds_ref = write(output / "builds-frozen.json"')
    first_parse = source.index('reference_rows(read_ref(config["challenge_targets"])')
    require(build_freeze < first_parse, "qualification source opens targets before build freeze")
    return loaded, {"actual_fitting_loader_target_deny_read_passed": True,
        "inspected_qualification_source_parses_targets_after_build_freeze": True,
        "scope": "Code-flow inspection and deny-read loader execution; no claim of a system-wide historical file-access trace."}


def audit(run_directory, qualification_directory, output):
    import torch
    torch.set_num_threads(1)
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_grounding as grounding
    from scripts.ops.legal_ir import run_legal_grounding_experiment as runner
    run, qualification = Path(run_directory).resolve(), Path(qualification_directory).resolve()
    # Check readiness without opening any sealed target before this point.
    required = [run / "generation-frozen.json", qualification / "builds-frozen.json", qualification / "summary.json"]
    require(all(p.is_file() for p in required), "generation, builds and qualification must already be frozen")
    freezes = {p.name: ref(p) for p in required}
    frozen = read_ref(freezes["generation-frozen.json"])
    summary = read_ref(freezes["summary.json"])
    builds = read_ref(freezes["builds-frozen.json"])
    plan = read_ref(frozen["plan"])
    config = read_ref(plan["config"])
    require(summary["generation_freeze"] == freezes["generation-frozen.json"], "qualification used another generation freeze")
    require(all(summary["builds"][k] == freezes["builds-frozen.json"][k] for k in ("path", "sha256")), "qualification used another build freeze")
    for path, expected in plan["producer_pins"].items():
        require(ref(path)["sha256"] == expected, "frozen producer drift")
    target_paths = {str(Path(config[k]["path"]).resolve()) for k in ("challenge_targets", "regression_targets")}
    loaded, target_access_audit = check_target_read_order(runner, plan["config"]["path"], target_paths)
    _, train, tuning, challenge, regression, parents = loaded
    inputs = json.loads((run / "source-inputs.json").read_bytes())
    require(inputs == {"tuning": runner.source_rows(tuning), "challenge": challenge, "regression": regression}, "frozen source inputs differ")
    require(all(set(r) == {"id", "source_text", "source_sha256"} for rows in inputs.values() for r in rows), "source inventory contains labels")
    heads = read_ref(frozen["heads"])
    require(len(heads) == 6, "six trained arms required")
    stages, initial_by_seed, model_audits = [], {}, []
    for head in heads:
        require(head["enabled"] is (head["arm"] == "trigger_grounding"), "arm enabled flag differs")
        require(head["parent"] == parents[head["seed"]]["checkpoint"], "same-seed parent differs")
        parent = read_ref(head["parent"])
        initial = grounding.build_checkpoint(parent, train, tuning, trigger_enabled=head["enabled"], learning_rate=.001, batch_size=12)
        initialization = read_ref(head["initialization"])
        require(initialization["checkpoint_sha256"] == digest(initial), "initial checkpoint differs")
        source_state = {k: v for k, v in initial["model_state"].items() if not k.startswith(EXTRA)}
        require(source_state == parent["model_state"], "copied source weights differ")
        current_initial = digest(initial["model_state"])
        prior_initial = initial_by_seed.setdefault(head["seed"], current_initial)
        require(current_initial == prior_initial, "matched arms have different initial tensors")
        previous = initial
        require([s["steps"] for s in head["stages"]] == [400, 800] and head["executed_steps"] == 800, "matched stage budget differs")
        tuning_scores = []
        for stage in head["stages"]:
            checkpoint = read_ref(stage["checkpoint"])
            grounding.validate_checkpoint(checkpoint)
            require(checkpoint["parent_checkpoint_sha256"] == digest(previous) == stage["previous_checkpoint_sha256"], "checkpoint chain differs")
            require(checkpoint["training_manifest_sha256"] == digest(train) and checkpoint["tuning_manifest_sha256"] == digest(tuning), "training data differs")
            require(checkpoint["config"] == initial["config"] and checkpoint["source_parent_checkpoint_sha256"] == digest(parent), "model config or parent differs")
            report = read_ref(stage["training_report"])
            require(report["checkpoint_sha256"] == digest(checkpoint) and report["optimizer_steps"] == 400 and len(report["batch_losses"]) == 400, "execution count differs")
            changes = {name: tensor_difference(previous["model_state"][name], value) for name, value in checkpoint["model_state"].items()}
            changed = [name for name, evidence in changes.items() if evidence["changed_elements"]]
            require(set(changed) == set(report["changed_parameter_names"]), "recorded parameter changes differ")
            auxiliary = {name: evidence for name, evidence in changes.items() if name.startswith(EXTRA)}
            for prefix in EXTRA:
                gradient = report["auxiliary_gradient_norm_max"][prefix[:-1]]
                require(math.isfinite(gradient) and (gradient > 0 if head["enabled"] else gradient == 0), "auxiliary gradient evidence differs")
                changed_prefix = any(e["changed_elements"] for n, e in auxiliary.items() if n.startswith(prefix))
                require(changed_prefix is head["enabled"], "auxiliary parameter update policy differs")
            moment_evidence = {}
            for name, moment in checkpoint["optimizer_state"]["parameters"].items():
                require(moment["step"] == stage["steps"], "Adam step differs")
                first = math.sqrt(math.fsum(x * x for x in flatten(moment["exp_avg"])))
                second = math.fsum(flatten(moment["exp_avg_sq"]))
                if name.startswith(EXTRA):
                    moment_evidence[name] = {"step": moment["step"], "first_moment_l2": first, "second_moment_sum": second}
                    require(head["enabled"] or first == second == 0, "control auxiliary moments are nonzero")
            tuned = read_ref(stage["tuning_generation"])
            measured = independent_metrics(tuned["generation"], inputs["tuning"], tuning)
            require(measured["exact"] == stage["tuning_exact"] == tuned["metrics"]["exact"], "selection tuning score differs")
            tuning_scores.append((measured["exact"], -stage["steps"]))
            stages.append({"name": head["name"], "steps": stage["steps"], "changed_parameter_names": changed,
                "source_changed_parameter_count": sum(not n.startswith(EXTRA) for n in changed),
                "auxiliary_parameter_changes": auxiliary, "auxiliary_optimizer_moments": moment_evidence,
                "auxiliary_gradient_norm_max": report["auxiliary_gradient_norm_max"], "tuning_exact": measured["exact"]})
            previous = checkpoint
        selected_steps = -max(tuning_scores)[1]
        selected = next(s for s in head["stages"] if s["steps"] == selected_steps)
        require(head["selected_steps"] == selected_steps and head["checkpoint"] == selected["checkpoint"], "tuning-only selection differs")
        model_audits.append({"name": head["name"], "executed_steps": 800, "selected_steps": selected_steps,
            "initial_model_sha256": current_initial, "parent_source_sha256": digest(parent["model_state"])})
    # No target parse occurs above. Read only after verifying all freezes/data/tensors.
    new_targets = read_ref(config["challenge_targets"])
    old_targets = read_ref(config["regression_targets"])
    if isinstance(old_targets, dict):
        old_targets = old_targets["targets"]
    corpus_manifest = read_ref(config["curriculum_manifest"])
    membership = read_ref(corpus_manifest["artifacts"]["construction_membership"])
    verify_coordinate_targets(new_targets, corpus_manifest["semantics"]["trigger_meanings"])
    sources = {**inputs, "challenge_disabled": challenge}
    targets = {"challenge": new_targets, "challenge_disabled": new_targets, "tuning": tuning, "regression": old_targets}
    measured, interventions, error_groups, per_rows = {}, [], {}, {}
    summary_by_name = {m["name"]: m for m in summary["models"]}
    for model in frozen["models"]:
        name = model["name"]
        measured[name] = {}
        per_rows[name] = {}
        generations = {}
        for panel, artifact in frozen["files"][name].items():
            generation = read_ref(artifact)
            generations[panel] = generation
            metric = independent_metrics(generation, sources[panel], targets[panel])
            expected = summary_by_name[name]["metrics"][panel]
            require(all(metric[k] == expected[k] for k in ("count", "decoded", "abstained", "exact", "trigger_span_exact")), "independent metrics differ")
            require(metric["facet_exact"] == {k: expected["facets"].get(k, 0) for k in ("modality", *FIELDS)}, "facet metrics differ")
            per_rows[name][panel] = metric["rows"]
            metric["trigger_metric_interpretation"] = ("supervised diagnostic head" if model["enabled"] else
                "untrained disabled diagnostic head; not trigger competence" if model["arm"] != "parent" else
                "unavailable; parent has no trigger head")
            measured[name][panel] = {k: v for k, v in metric.items() if k != "rows"}
            if panel == "challenge":
                error_groups[name] = construction_errors(metric["rows"], membership["challenge"])
        if model["enabled"]:
            normal, disabled = generations["challenge"]["rows"], generations["challenge_disabled"]["rows"]
            require(len(normal) == len(disabled) == len(challenge), "intervention denominator differs")
            changes = sum((a["status"], a["canonical_ir"]) != (b["status"], b["canonical_ir"]) for a, b in zip(normal, disabled))
            require(changes == summary_by_name[name]["residual_control"]["canonical_output_changed"], "residual output count differs")
            interventions.append({"name": name, "count": len(challenge), "canonical_output_changed": changes,
                "normal_exact_minus_disabled": measured[name]["challenge"]["exact"] - measured[name]["challenge_disabled"]["exact"],
                "interpretation": "Both learned modality and actor residuals disabled jointly; shared-encoder learning retained. Does not isolate either head or auxiliary loss."})
    for arm, totals in summary["totals"].items():
        names = [m["name"] for m in frozen["models"] if m["arm"] == arm]
        for panel in ("challenge", "regression"):
            require(all(sum(measured[n][panel][k] for n in names) == totals[panel][k] for k in ("count", "decoded", "abstained", "exact", "trigger_span_exact")), "aggregate denominator or numerator differs")
    paired_parents = []
    for head in heads:
        parent_name = f"parent-{head['seed']}"
        for panel in ("challenge", "regression"):
            a, b = per_rows[head["name"]][panel], per_rows[parent_name][panel]
            require([r["id"] for r in a] == [r["id"] for r in b], "paired parent source order differs")
            counts = Counter((x["exact"], y["exact"]) for x, y in zip(a, b))
            paired_parents.append({"model": head["name"], "parent": parent_name, "panel": panel, "count": len(a),
                "corrected_parent_errors": counts[True, False], "regressions_from_correct_parent": counts[False, True],
                "both_correct": counts[True, True], "both_wrong": counts[False, False]})
    build_receipts, invocations = [], 0
    for name, model_builds in builds["models"].items():
        passed_candidates = 0
        for batch in model_builds:
            receipt = read_ref(batch["receipt"])
            require(receipt["build_passed"] == batch["build_passed"] and receipt["backend_executed"] == batch["backend_executed"], "build receipt differs")
            require(receipt["command"] == batch["command"] and receipt["command"][-2:] == ["build", "legal"], "exact build target differs")
            invocations += 1
            if receipt["build_passed"]:
                passed_candidates += len(batch["candidate_ids"])
            build_receipts.append(batch["receipt"])
        require(passed_candidates == summary_by_name[name]["builds"]["built"], "built numerator differs")
        require(summary_by_name[name]["builds"]["count"] == len(challenge), "build denominator omitted outputs")
    result = {"schema": "independent-legal-grounding-audit/v1", "auditor": ref(__file__), "freezes": freezes,
        "target_access_audit": target_access_audit, "source_inventories_contain_only_source_fields": True,
        "matched_initialization_by_seed": initial_by_seed, "models": model_audits, "stages": stages,
        "metrics": measured, "joint_residual_interventions": interventions, "build_receipts_verified": build_receipts,
        "challenge_errors_by_construction": error_groups, "paired_parent_changes": paired_parents,
        "build_invocations_recorded": invocations, "executed_optimizer_steps_verified": 4800,
        "optimizer_trajectory_replayed": False, "new_numeric_inference_executed": False, "new_compiler_invocations": 0,
        "qualified": False, "external_statutory_gold": False,
        "construction_holdout_scope": "Construction IDs are disjoint within this newly authored curriculum. Similar constructions in inherited parent training have not been exhaustively audited; source-hash disjointness does not prove construction novelty relative to that parent.",
        "coordinate_metric_policy": "Facet-coordinate accuracy counts decoded outputs only, including correctly absent facets; abstentions stay in full denominators. Trigger accuracy is separate diagnostic output; parent models have no trigger head.",
        "limits": ["Annotation correctness is authored under stipulated semantics, not independently adjudicated law.", "Target read-order evidence is source inspection and guarded loader execution, not a global historical access trace.", "Compiler results do not establish source fidelity.", "Repeated seeds share the same challenge sentences and are not independent statutes."]}
    require(not Path(output).exists(), "audit output already exists")
    Path(output).parent.mkdir(parents=True, exist_ok=True)
    with Path(output).open("xb") as stream:
        stream.write(raw(result))
    print(json.dumps(ref(output), sort_keys=True))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-directory", type=Path, required=True)
    parser.add_argument("--qualification-directory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    audit(args.run_directory, args.qualification_directory, args.output)


if __name__ == "__main__":
    main()
