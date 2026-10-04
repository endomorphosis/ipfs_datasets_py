#!/usr/bin/env python3
"""Replay exposed, rejected decoder candidates without fitting or selecting.

Every generation uses only cached source vectors. Complete reference prefixes
are used separately for teacher-forced NLL diagnostics, never generation. This
script requires the original frozen recipe, source/input inventories and saved
last-attempt tensors; it cannot load or promote production checkpoints.
"""
import argparse
from copy import deepcopy
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys
import time

SCHEMA = "rejected-decoder-controls/v1"
RELATIVE = "scripts/ops/autoencoder/evaluate_rejected_decoder_controls.py"
REPLAY = "scripts/ops/autoencoder/decoder_fidelity_replay.py"
FACETS = ("modality", "actor", "action", "object", "conditions", "exceptions", "temporal")
ROLES = (*FACETS, "continue", "stop", "eos", "structure")
LABELS = ("validation", "training", "zero-condition", "source-shuffle", "training-source-shuffle")
FALSE = dict(qualified=False, admitted=False, proof_authority=False, source_semantics_verified=False,
    fresh_holdout=False, convergence_proven=False, checkpoint_promoted=False, lake_executed=False,
    formalized=False, roundtrip_ok=False, production_checkpoint=False, optimizer_resumable=False)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def raw(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(raw(value)).hexdigest()


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, "duplicate JSON key")
            result[key] = value
        return result
    def nonfinite(value):
        raise ValueError("nonfinite JSON constant: " + value)
    return json.loads(Path(path).read_bytes(), object_pairs_hook=unique, parse_constant=nonfinite)


def save(path, value):
    path = Path(path)
    content = raw(value) + b"\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(content)
    return dict(path=str(path), sha256=sha(path), bytes=len(content))


def save_evaluation(folder, label, value):
    require(type(label) is str and label in LABELS, "unknown diagnostic evaluation label")
    return save(Path(folder) / ("evaluation-" + label + ".json"), value)


def arm_identities(plan):
    require(plan.get("architecture_arms") == ["first_step", "every_step"]
        and plan.get("loss_arms") == ["reference_ce", "semantic_fields"]
        and plan.get("seed_order") == [1729, 2718], "exact original eight-arm recipe required")
    return [(f"{architecture}-{strategy}-{seed}", architecture, strategy, seed)
        for seed in plan["seed_order"] for architecture in plan["architecture_arms"]
        for strategy in plan["loss_arms"]]


def validate_diagnostic_inputs(manifest, plan):
    """All diagnostic pointers must be independently pinned, with no role reuse."""
    require(type(manifest) is dict and type(manifest.get("inputs")) is dict, "input pins required")
    records = manifest.get("rejected_states")
    require(type(records) is dict and set(records) == {row[0] for row in arm_identities(plan)},
        "exact eight rejected-state records required")
    pointers = [manifest.get("source_run_summary")]
    for record in records.values():
        require(type(record) is dict and set(record) == {"state", "training", "predictions"},
            "closed state/training/predictions binding required")
        pointers.extend(record.values())
    require(all(type(path) is str and Path(path).is_absolute() for path in pointers), "absolute diagnostic pointers required")
    require(len(set(pointers)) == len(pointers), "diagnostic artifact roles must be distinct")
    for path in pointers:
        expected = manifest["inputs"].get(path)
        require(type(expected) is str and len(expected) == 64 and sha(path) == expected,
            "diagnostic input missing or changed: " + path)


def validate_saved_candidate(identity, state, training, predictions, summary, lineage):
    arm, architecture, strategy, seed = identity
    require(type(summary) is dict and summary.get("complete") is True, "original comparison incomplete")
    runs = summary.get("runs")
    require(type(runs) is list and len(runs) == 8 and all(type(row) is dict for row in runs)
        and len({row.get("arm") for row in runs}) == 8, "eight unique original runs required")
    matching = [row for row in runs if row.get("arm") == arm]
    require(len(matching) == 1, "candidate absent from original comparison")
    run = matching[0]
    require(run.get("architecture") == architecture and run.get("strategy") == strategy
        and type(run.get("seed")) is int and run["seed"] == seed and run.get("budget_completed") is True,
        "original arm binding differs")
    require(type(training) is dict and run.get("training") == training, "training receipt differs from source summary")
    expected_lineage = {**lineage, "student_lineage": arm}
    require(type(state) is dict and state.get("schema") == "long-source-last-complete-diagnostic/v1"
        and state.get("architecture") == architecture and state.get("selected") is False,
        "unselected last-complete diagnostic state required")
    require(all(state.get(key) is False for key in FALSE), "saved candidate claims unsupported authority or resume")
    require(state.get("lineage") == expected_lineage == training.get("lineage"), "candidate lineage differs")
    values = state.get("model_state")
    require(type(values) is dict and values and all(type(key) is str for key in values), "named saved tensors required")
    require(digest(values) == state.get("weights_sha256"), "saved tensor JSON digest differs")
    require(training.get("last_complete_attempt_is_selected") is False
        and training.get("last_complete_attempt_state_available") is True
        and type(training.get("last_complete_attempt")) is dict, "original last attempt unavailable or selected")
    require(training.get("optimizer_steps") == 340 and training.get("valid_target_token_presentations") == 225840,
        "original training budget differs")
    require(training.get("strategy") == strategy, "training strategy differs")
    require(type(predictions) is list and predictions and all(type(row) is dict
        and type(row.get("id")) is str for row in predictions), "complete original predictions required")
    require(len({row["id"] for row in predictions}) == len(predictions), "duplicate original predictions")


def reference_token_roles(row, reference, codec):
    """Classify full, authenticated reference tokens, not generated predictions.

    'continue' is only the comma between top-level rules, 'stop' is only the
    closing rules-array bracket. Empty qualifier brackets count toward their
    facet; other punctuation remains structure. BOS is excluded, EOS retained.
    """
    require(row.get("id") == reference.get("id"), "reference ID differs")
    if "source_text" in reference:
        require(row.get("source_text") == reference["source_text"], "reference source differs")
    target = reference.get("target")
    require(type(target) is dict and set(target) == {"rules"} and type(target["rules"]) is list
        and 1 <= len(target["rules"]) <= 32 and type(reference.get("clause_count")) is int
        and reference["clause_count"] == len(target["rules"]), "complete bounded rule reference required")
    for rule in target["rules"]:
        require(type(rule) is dict and set(rule) == set(FACETS), "exact seven facets required")
        require(all(type(rule[key]) is str for key in FACETS[:4])
            and all(type(rule[key]) is list and len(rule[key]) <= 128
                and all(type(item) is str for item in rule[key]) for key in FACETS[4:]), "unsupported reference facet type")
    records = []
    def token(value, role="structure"):
        records.append((value, role))
    def walk(value, path=()):
        facet = path[2] if len(path) >= 3 and path[0] == "rules" and path[2] in FACETS else None
        if isinstance(value, dict):
            token("{")
            for index, key in enumerate(sorted(value)):
                if index:
                    token(",")
                token(json.dumps(key, ensure_ascii=True)); token(":")
                walk(value[key], (*path, key))
            token("}")
        elif isinstance(value, list):
            token("[", facet if not value and facet else "structure")
            for index, child in enumerate(value):
                if index:
                    token(",", "continue" if path == ("rules",) else "structure")
                walk(child, (*path, index))
            token("]", "stop" if path == ("rules",) else facet if not value and facet else "structure")
        else:
            token(json.dumps(value, ensure_ascii=True, allow_nan=False), facet or "structure")
    walk(target)
    text = json.dumps(target, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
    require("".join(item[0] for item in records) == text, "reference tokenization lost content")
    vocabulary = codec.get("target_vocabulary")
    require(type(vocabulary) is list and all(type(item) is str for item in vocabulary)
        and len(set(vocabulary)) == len(vocabulary) and vocabulary[:3] == ["<pad>", "<bos>", "<eos>"],
        "unique inherited special-token vocabulary required")
    positions = {token: index for index, token in enumerate(vocabulary)}
    require(all(token in positions for token, _ in records), "complete reference outside vocabulary")
    expected = [1] + [positions[token] for token, _ in records] + [2]
    require(type(row.get("target_ids")) is list and all(type(item) is int for item in row["target_ids"])
        and row["target_ids"] == expected, "complete numerical reference tokens differ")
    return [role for _, role in records] + ["eos"]


def _bins():
    return {role: dict(nll_sum=0., token_count=0, mean_nll=None) for role in ROLES}


def _aggregate(bins, roles, losses):
    require(len(roles) == len(losses), "NLL role width differs")
    for role, value in zip(roles, losses):
        require(role in bins and type(value) in (int, float) and math.isfinite(value) and value >= 0,
            "invalid role or NLL")
        bins[role]["nll_sum"] += value
        bins[role]["token_count"] += 1


def _finish(bins):
    for record in bins.values():
        record["mean_nll"] = record["nll_sum"] / record["token_count"] if record["token_count"] else None
    return bins


def teacher_forced_nll(ctx, model, rows, references, *, max_seconds=20., max_memory_bytes=536870912):
    """Fixed-prefix counterfactual NLL; no optimizer, sampling, or selection."""
    started = time.monotonic()
    torch, core, donor = ctx["torch"], ctx["core"], ctx["donor"]
    require(type(max_seconds) in (int, float) and math.isfinite(max_seconds) and 0 < max_seconds <= 20,
        "bounded NLL deadline required")
    deadline = started + max_seconds
    require(type(max_memory_bytes) is int and 0 < max_memory_bytes <= 536870912, "bounded NLL memory required")
    require(rows and len({row["id"] for row in rows}) == len(rows)
        and len({ref["id"] for ref in references}) == len(references), "unique complete NLL rows required")
    by_id = {ref["id"]: ref for ref in references}
    require(set(by_id) == {row["id"] for row in rows}, "NLL reference identities differ")
    roles = {row["id"]: reference_token_roles(row, by_id[row["id"]], donor["codec"]) for row in rows}
    size = len(donor["codec"]["target_vocabulary"])
    width = max(len(row["target_ids"]) for row in rows)
    require(width <= 512 and all(len(row["input"]) == 384 for row in rows), "fixed dimension/output budget differs")
    estimate = 4 * sum(t.numel() * t.element_size() for t in model.state_dict().values()) + 8 * 8 * width * size * 4 + 4 * len(rows) * 384
    require(estimate <= max_memory_bytes, "NLL tensor estimate exceeds memory budget")
    before = core.tensor_digest(model)
    modes = {name: module.training for name, module in model.named_modules()}
    overall, by_length, records = _bins(), {}, []
    complete = True
    try:
        model.eval()
        with torch.inference_mode():
            for start in range(0, len(rows), 8):
                if time.monotonic() >= deadline:
                    complete = False; break
                part = rows[start:start+8]
                data, labels = core._batch(torch, part, donor["input_transform"])
                _, logits = core._logits(torch, model, data, labels[:, :-1], size)
                losses = torch.nn.functional.cross_entropy(logits.flatten(0, 1), labels[:, 1:].flatten(),
                    ignore_index=0, reduction="none").reshape(len(part), -1)
                require(bool(torch.isfinite(losses).all()), "nonfinite diagnostic NLL")
                if time.monotonic() >= deadline:
                    complete = False; break
                for row, values in zip(part, losses.tolist()):
                    selected = values[:len(roles[row["id"]])]
                    length = str(by_id[row["id"]]["clause_count"])
                    local = _bins()
                    for bins in (local, overall, by_length.setdefault(length, _bins())):
                        _aggregate(bins, roles[row["id"]], selected)
                    records.append(dict(id=row["id"], clause_count=int(length), by_role=_finish(local),
                        token_nll=selected, token_roles=roles[row["id"]]))
    finally:
        for name, module in model.named_modules():
            module.training = modes[name]
    require(core.tensor_digest(model) == before, "NLL diagnostic changed model weights")
    complete = complete and len(records) == len(rows) and time.monotonic() < deadline
    count = sum(value["token_count"] for value in overall.values())
    return dict(schema="fixed-prefix-source-nll/v1", complete=complete,
        stopped_reason="complete" if complete else "deadline_during_nll", rows=records,
        by_role=_finish(overall), by_length={key: _finish(value) for key, value in by_length.items()},
        target_token_count=count, mean_nll=sum(value["nll_sum"] for value in overall.values())/count if count else None,
        model_weights_sha256=before, elapsed_seconds=time.monotonic()-started,
        tensor_memory_estimate_bytes=estimate, memory_estimate_excludes_python_import_allocator_rss=True,
        teacher_forced=True, reference_prefix_identical_across_source_controls=True,
        generation_metrics=False, training_performed=False, selection_performed=False,
        boundary_scope="top-level between-rule comma / rules-list closing bracket / EOS; empty qualifier brackets retain facet role",
        **FALSE)


def prediction_changes(conditioned, counterfactual):
    def index(records):
        require(type(records) is list and all(type(r) is dict and type(r.get("id")) is str for r in records),
            "prediction records required")
        result = {row["id"]: row for row in records}
        require(len(result) == len(records), "duplicate counterfactual prediction")
        return result
    left, right = index(conditioned), index(counterfactual)
    require(left and set(left) == set(right), "counterfactual prediction IDs differ")
    changed = [identity for identity in left if left[identity]["token_ids"] != right[identity]["token_ids"]
        or left[identity]["generation_status"] != right[identity]["generation_status"]]
    return dict(row_count=len(left), generated_sequence_or_status_changed=len(changed), changed_ids=changed,
        reconstructed_input_not_part_of_sequence_comparison=True)


def nll_gap(conditioned, counterfactual):
    require(conditioned.get("complete") is True and counterfactual.get("complete") is True, "complete NLL controls required")
    def compare(left, right):
        require(set(left) == set(right) == set(ROLES), "NLL role support differs")
        result = {}
        for role in ROLES:
            a, b = left[role], right[role]
            require(a["token_count"] == b["token_count"], "counterfactual NLL denominator differs")
            result[role] = dict(token_count=a["token_count"], conditioned_mean_nll=a["mean_nll"],
                counterfactual_mean_nll=b["mean_nll"],
                counterfactual_minus_conditioned=None if not a["token_count"] else b["mean_nll"]-a["mean_nll"])
        return result
    require(set(conditioned["by_length"]) == set(counterfactual["by_length"]), "NLL length strata differ")
    require(conditioned["target_token_count"] == counterfactual["target_token_count"], "NLL totals differ")
    return dict(mean_counterfactual_minus_conditioned=counterfactual["mean_nll"]-conditioned["mean_nll"],
        by_role=compare(conditioned["by_role"], counterfactual["by_role"]),
        by_length={key: compare(value, counterfactual["by_length"][key]) for key, value in conditioned["by_length"].items()},
        interpretation="positive gap means lower reference-prefix NLL with the matched source; not semantic validity")


def validate_replay(evaluation, training, predictions):
    require(evaluation["report"]["complete"] is True, "conditioned validation incomplete")
    require(evaluation["predictions"] == predictions, "saved rejected-state predictions do not replay")
    require(evaluation["report"]["metrics"] == training["last_complete_attempt"]["numerical"], "saved numerical metrics do not replay")
    summary = {key: value for key, value in evaluation["source_fidelity"].items() if key != "rows"}
    require(summary == training["last_complete_attempt"]["fidelity"], "saved source-fidelity metrics do not replay")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("dependency-root", "extension-root", "manifest", "plan", "output"):
        parser.add_argument("--"+name, required=True, type=Path)
    args = parser.parse_args()
    args.manifest = args.manifest.resolve(); args.plan = args.plan.resolve(); args.output = args.output.resolve()
    manifest = read(args.manifest)
    plan = read(args.plan)
    validate_diagnostic_inputs(manifest, plan)
    root = args.extension_root.resolve()
    require(Path(__file__).resolve() == root/RELATIVE and sha(__file__) == manifest["extensions"].get(RELATIVE),
        "diagnostic runner differs from frozen owner")
    path = root/REPLAY
    require(sha(path) == manifest["extensions"].get(REPLAY), "shared replay preparation differs")
    spec = importlib.util.spec_from_file_location("_rejected_decoder_replay_context", path)
    loader = importlib.util.module_from_spec(spec); spec.loader.exec_module(loader)
    ctx = loader.load_context(args)
    core, adapter, scorer, numerical, torch = (ctx[key] for key in ("core", "adapter", "scorer", "numerical", "torch"))
    rows, references, donor, helpers = (ctx[key] for key in ("rows", "references", "donor", "helpers"))
    source_summary = read(manifest["source_run_summary"])
    expected_arms = {identity[0] for identity in arm_identities(plan)}
    require({run["arm"] for run in source_summary["runs"]} == expected_arms, "source summary arms differ")
    args.output.mkdir(parents=True)
    save(args.output/"sealed-recipe.json", dict(plan=plan, manifest=manifest, tree_pin=ctx["tree"],
        operation="postfit_rejected_candidate_diagnostics_only", **FALSE))
    started = time.monotonic(); summaries = []
    for identity in arm_identities(plan):
        arm, architecture, strategy, seed = identity
        pointers = manifest["rejected_states"][arm]
        state, training, previous = (read(pointers[key]) for key in ("state", "training", "predictions"))
        validate_saved_candidate(identity, state, training, previous, source_summary, ctx["lineage"])
        model = adapter.bind_persistent_model(ctx["base_model"].body, dimension=384, conditioning=architecture)
        require(set(model.state_dict()) == set(state["model_state"]), "saved tensor names differ")
        model.load_state_dict({key: numerical._tensor(state["model_state"][key], template, key)
            for key, template in model.state_dict().items()}, strict=True)
        parent_tensors = ctx["base_model"].state_dict()
        frozen = []
        for name, parameter in model.named_parameters():
            if name.startswith(("body.projection_down.", "body.projection_up.")):
                require(torch.equal(parameter.detach().contiguous().view(torch.uint8),
                    parent_tensors[name].detach().contiguous().view(torch.uint8)), "saved frozen projection differs from inherited donor")
                parameter.requires_grad_(False); frozen.append(name)
        require(len(frozen) == 4, "exact inherited frozen projection inventory required")
        loaded_digest = core.tensor_digest(model)
        lineage = {**ctx["lineage"], "student_lineage": arm}
        folder = args.output/arm
        evaluations = {}; artifacts = {}
        for label, split, kind in (("validation", "validation", "conditioned"), ("training", "train", "conditioned"),
                ("zero-condition", "validation", "zero_condition"), ("source-shuffle", "validation", "source_shuffle"),
                ("training-source-shuffle", "train", "source_shuffle")):
            actual = rows[split]
            execution = dict(kind=kind, source_assignment={row["id"]: row["id"] for row in actual})
            evaluated_model = model
            if kind == "source_shuffle":
                actual, execution = helpers.shuffle_inputs(actual, references[split])
            elif kind == "zero_condition":
                evaluated_model = adapter.bind_zero_condition_model(model, dimension=384)
            evaluation = core.evaluate_model(evaluated_model, actual, codec=donor["codec"],
                input_transform=donor["input_transform"], lineage=lineage, max_target_tokens=512, max_seconds=20, batch_size=8)
            evaluation["execution"] = {**execution, "split": split, "training_performed": False, "selection_performed": False,
                "provenance_breaking_negative_control": kind == "source_shuffle"}
            if not evaluation["report"]["complete"]:
                save_evaluation(folder, label, evaluation)
                raise ValueError("bounded postfit evaluation incomplete: " + arm + "/" + label)
            evaluation["source_fidelity"] = scorer.score_predictions(references[split], evaluation["predictions"],
                codec=donor["codec"], validate_rule=ctx["validate_rule"], validator_id=ctx["validator_id"], output_limit=512,
                control={key: execution[key] for key in ("kind", "source_assignment")})
            if label == "validation":
                validate_replay(evaluation, training, previous)
            evaluation["teacher_forced_nll"] = teacher_forced_nll(ctx, evaluated_model, actual, references[split])
            artifacts[label] = save_evaluation(folder, label, evaluation)
            nll = evaluation["teacher_forced_nll"]
            require(nll["complete"], "bounded NLL diagnostic incomplete")
            require(nll["target_token_count"] == evaluation["report"]["metrics"]["target_token_count"]
                and math.isclose(nll["mean_nll"], evaluation["report"]["metrics"]["token_cross_entropy"], rel_tol=1e-6, abs_tol=1e-7),
                "token-role NLL does not reconcile with original numerical CE")
            evaluations[label] = evaluation
            require(core.tensor_digest(model) == loaded_digest, "postfit controls changed rejected state")
        comparisons = {}
        for label, baseline in (("zero-condition", "validation"), ("source-shuffle", "validation"), ("training-source-shuffle", "training")):
            comparisons[label] = dict(predictions=prediction_changes(evaluations[baseline]["predictions"], evaluations[label]["predictions"]),
                teacher_forced_nll=nll_gap(evaluations[baseline]["teacher_forced_nll"], evaluations[label]["teacher_forced_nll"]))
        summary = dict(arm=arm, architecture=architecture, strategy=strategy, seed=seed,
            saved_state_sha256=sha(pointers["state"]), tensor_weights_sha256=loaded_digest,
            architecture_specification=model.describe(), frozen_parameter_names=frozen,
            conditioned_validation_replay_exact=True, original_selected_epoch=training["selected_epoch"],
            candidate_was_selected=False, evaluations=artifacts, comparisons=comparisons,
            numerical={key: value["report"]["metrics"] for key, value in evaluations.items()},
            fidelity={key: {k: v for k, v in value["source_fidelity"].items() if k != "rows"} for key, value in evaluations.items()},
            training_performed=False, selection_performed=False, **FALSE)
        save(folder/"summary.json", summary); summaries.append(summary)
        print(json.dumps(dict(arm=arm, complete=True, conditioned_replay_exact=True,
            validation_source_ce_gap=comparisons["source-shuffle"]["teacher_forced_nll"]["mean_counterfactual_minus_conditioned"])), flush=True)
    after = helpers.inventory(args.dependency_root, args.extension_root, ctx["pins"])
    require(all(after.get(path) == value for path, value in ctx["before_sources"].items()), "loaded producer source changed")
    for path, expected in manifest["inputs"].items():
        require(sha(path) == expected, "sealed input changed during diagnostic")
    for path, expected in ctx["pins"].items():
        require(sha(root/path) == expected, "frozen extension changed during diagnostic")
    require(sha(args.plan) == manifest["plan_sha256"], "original recipe changed during diagnostic")
    save(args.output/"summary.json", dict(schema=SCHEMA, complete=len(summaries) == 8, runs=summaries,
        elapsed_seconds=time.monotonic()-started, source_dependencies=after,
        unique_source_count=96, evaluations_per_candidate=5, dimensions_actually_evaluated=[384],
        scope="exposed_original_train_and_validation; rejected_weights_frozen_before_controls",
        training_performed=False, selection_performed=False, optimizer_steps=0,
        paragraph_embedding_cache_used=True, encoder_executed=False, encoder_context_changed=False,
        downloads_performed=False, bridge_evaluation_performed=False, bridge_names=[], legal_ir_evaluate_provers=False,
        generation_temperature=0, generation_target_access=False, teacher_forced_diagnostics_use_complete_reference_prefix=True,
        workers=1, **FALSE))


if __name__ == "__main__":
    main()
