"""Private Legal decoder continuation with source-fidelity selection.

This development owner reuses the published numerical protocol and keeps one
optimizer across cumulative source bins. It cannot produce a production
checkpoint or replace a native qualification gate. References must be complete
ordered rule documents; only input vectors reach the numerical model.
"""
from copy import deepcopy
import json
import time

from . import decoder_distillation_experiment as core
from . import decoder_source_fidelity as fidelity

SCHEMA = "long-source-decoder-training/v1"
FALSE = dict(core.FALSE, convergence_proven=False, fresh_holdout=False,
             native_family_validation_performed=False, lake_executed=False,
             optimizer_resumable=False)


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False)


def _tokens(value, *, semantic, path=()):
    """Full JSON lexical tokens; field values retain their original positions."""
    structure = .25 if semantic else 1.
    if isinstance(value, dict):
        result = [("{", structure)]
        for index, key in enumerate(sorted(value)):
            if index:
                result.append((",", structure))
            result.extend([(_json(key), structure), (":", structure)])
            result.extend(_tokens(value[key], semantic=semantic, path=(*path, key)))
        return result + [("}", structure)]
    if isinstance(value, list):
        if not value:
            # Absence of a qualifier is evidence too, but a corpus of empty
            # lists must not receive the larger scalar supervision multiplier.
            return [("[", 1.), ("]", 1.)]
        result = [("[", structure)]
        for index, child in enumerate(value):
            if index:
                result.append((",", structure))
            result.extend(_tokens(child, semantic=semantic, path=(*path, index)))
        return result + [("]", structure)]
    return [(_json(value), 4. if semantic else 1.)]


def reference_weights(rows, references, codec, *, strategy, validate_rule):
    """Authenticate full reference tokens before assigning any loss weights."""
    core._require(strategy in ("reference_ce", "semantic_fields"), "unknown source loss strategy")
    core._require(type(references) is list and len(references) == len(rows), "complete reference inventory required")
    by_id = {row["id"]: row for row in references}
    core._require(len(by_id) == len(references) and set(by_id) == {row["id"] for row in rows}, "reference IDs differ")
    vocabulary = codec["target_vocabulary"]
    positions = {token: index for index, token in enumerate(vocabulary)}
    weights = {}
    for row in rows:
        reference = by_id[row["id"]]
        target = reference["target"]
        core._require(type(target) is dict and set(target) == {"rules"} and type(target["rules"]) is list
            and 1 <= len(target["rules"]) <= 32 and reference["clause_count"] == len(target["rules"]),
            "complete bounded Legal multi-rule reference required")
        for rule in target["rules"]:
            receipt = validate_rule({"rules": [deepcopy(rule)]})
            core._require(type(receipt) is dict and receipt.get("valid") is True,
                          "reference rule failed supplied syntax validator")
        records = _tokens(target, semantic=strategy == "semantic_fields")
        core._require("".join(token for token, _ in records) == _json(target), "target tokenization lost content")
        core._require(all(token in positions for token, _ in records), "complete reference outside inherited vocabulary")
        ids = [1] + [positions[token] for token, _ in records] + [2]
        core._require(ids == row["target_ids"], "numerical tokens differ from complete reference")
        if "source_text" in reference:
            core._require(reference["source_text"] == row["source_text"], "reference source differs")
        weights[row["id"]] = [0.] + [weight for _, weight in records] + [1.]
    return weights


def _summary(value):
    return {key: deepcopy(item) for key, item in value.items() if key != "rows"}


def _evaluate(torch, model, rows, references, transform, options, codec, deadline, validate_rule, validator_id):
    numeric = core._evaluate(torch, model, rows, transform, options, len(codec["target_vocabulary"]), deadline)
    if numeric is None:
        return None
    source = fidelity.score_predictions(references, numeric["predictions"], codec=codec,
        validate_rule=validate_rule, output_limit=options["max_target_tokens"], validator_id=validator_id)
    if time.monotonic() >= deadline:
        return None
    core._require(source["complete_evaluation"], "incomplete source-fidelity evaluation")
    return dict(numerical={k: v for k, v in numeric.items() if k != "predictions"},
                fidelity=source, predictions=numeric["predictions"])


def train(student, training_rows, validation_rows, *, training_references, validation_references,
          codec, input_transform, lineage, validate_rule, validator_id,
          curriculum, strategy="reference_ce", config=None):
    """Fresh reference-supervised fit; source fidelity gates experimental selection.

    The last complete attempt is retained as an explicitly unselected diagnostic.
    Its metrics cannot be substituted for the conservatively selected state.
    Adam/RNG/scheduler state persists across stages but is not exported for resume.
    """
    started = time.monotonic()
    core._require(config is None or type(config) is dict, "configuration must be a mapping")
    options = core._config({"alpha": 0., **(config or {})})
    core._require(options["alpha"] == 0., "unqualified teacher cannot supervise this source-fidelity trial")
    deadline = started + options["max_seconds"]
    torch = core._torch()
    core._model(student, torch)
    core._validate(codec, input_transform, lineage, student.dimension)
    core._require(lineage["domain"] == "legal_ir", "this version owns Legal rule-facet fidelity only")
    train_ids, train_sources = core._rows(training_rows, student.dimension, codec["target_vocabulary"], options["max_target_tokens"])
    tune_ids, tune_sources = core._rows(validation_rows, student.dimension, codec["target_vocabulary"], options["max_target_tokens"])
    core._require(not train_ids & tune_ids and not train_sources & tune_sources, "training/validation overlap")
    weights = reference_weights(training_rows, training_references, codec, strategy=strategy, validate_rule=validate_rule)
    reference_weights(validation_rows, validation_references, codec, strategy="reference_ce", validate_rule=validate_rule)
    stages = core._curriculum(curriculum, training_rows, options)
    parameter_bytes = sum(t.numel()*t.element_size() for t in student.state_dict().values())
    width = max(len(r["target_ids"]) for r in [*training_rows, *validation_rows])
    estimate = parameter_bytes*24 + 16*options["batch_size"]*width*len(codec["target_vocabulary"])*4
    estimate += 4*(len(training_rows)+len(validation_rows))*student.dimension
    core._require(estimate <= options["max_memory_bytes"], "trial tensor work exceeds budget")
    before = core.tensor_digest(student)
    modes = {name: m.training for name, m in student.named_modules()}
    working = deepcopy(student)
    trainable = [p for p in working.parameters() if p.requires_grad]
    core._require(trainable, "no trainable decoder parameters")
    frozen = {name: p.detach().cpu().contiguous().numpy().tobytes()
              for name, p in working.named_parameters() if not p.requires_grad}
    optimizer = torch.optim.AdamW(trainable, lr=options["learning_rate"], weight_decay=options["weight_decay"], foreach=False)
    scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(optimizer, mode="min",
        factor=options["plateau_factor"], patience=options["plateau_patience"],
        min_lr=options["learning_rate"]*options["min_learning_rate_ratio"])
    generator = torch.Generator().manual_seed(options["seed"])
    evaluate = lambda: _evaluate(torch, working, validation_rows, validation_references, input_transform,
        options, codec, deadline, validate_rule, validator_id)
    baseline = evaluate()
    selected = last_complete = baseline
    last_complete_step = 0 if baseline is not None else None
    selected_epoch = 0 if baseline is not None else None
    snapshot = lambda: {name: t.detach().cpu().clone() for name, t in working.state_dict().items()}
    best_state = snapshot()
    history, stage_reports, steps, presentations, tokens_seen, stale = [], [], 0, 0, 0, 0
    stopped = "deadline_before_complete_baseline" if baseline is None else "epochs_completed"
    by_id = {row["id"]: row for row in training_rows}
    global_epoch = 0
    for stage in stages:
        if baseline is None or stopped != "epochs_completed":
            break
        current = [by_id[identity] for identity in stage["training_ids"]]
        stage_report = dict(name=stage["name"], training_rows=len(current), completed_epochs=0,
            optimizer_step_start=steps, optimizer_state_start=core._optimizer_state(working, optimizer))
        for stage_epoch in range(1, stage["epochs"]+1):
            global_epoch += 1
            working.train()
            order = torch.randperm(len(current), generator=generator).tolist()
            sums, batches, complete = [0., 0., 0.], 0, True
            for offset in range(0, len(current), options["batch_size"]):
                if time.monotonic() >= deadline or steps >= options["max_optimizer_steps"]:
                    stopped = "deadline" if time.monotonic() >= deadline else "optimizer_step_limit"
                    complete = False
                    break
                part = [current[index] for index in order[offset:offset+options["batch_size"]]]
                data, labels = core._batch(torch, part, input_transform)
                token_weights = torch.tensor([weights[row["id"]] + [0.]*(labels.shape[1]-len(weights[row["id"]]))
                    for row in part], dtype=torch.float32)[:, 1:]
                optimizer.zero_grad(set_to_none=True)
                projected, logits = core._logits(torch, working, data, labels[:, :-1], len(codec["target_vocabulary"]))
                ce = torch.nn.functional.cross_entropy(logits.flatten(0, 1), labels[:, 1:].flatten(),
                    ignore_index=0, reduction="none").reshape(labels.shape[0], -1)
                plain = ce.sum()/(labels[:, 1:] != 0).sum()
                weighted = (ce*token_weights).sum()/token_weights.sum()
                mse = (projected-data).square().mean()*input_transform["scale"]**2
                objective = weighted + options["reconstruction_weight"]*mse
                core._require(core._finite(torch, objective), "nonfinite objective")
                if time.monotonic() >= deadline:
                    stopped, complete = "deadline", False
                    break
                objective.backward()
                torch.nn.utils.clip_grad_norm_(trainable, options["max_grad_norm"], error_if_nonfinite=True)
                if time.monotonic() >= deadline:
                    optimizer.zero_grad(set_to_none=True)
                    stopped, complete = "deadline", False
                    break
                optimizer.step()
                core._require(all(core._finite(torch, p) for p in working.parameters()), "nonfinite updated state")
                steps += 1; presentations += len(part); tokens_seen += int((labels[:, 1:] != 0).sum())
                sums = [total+float(value.detach()) for total, value in zip(sums, (plain, weighted, mse))]
                batches += 1
            observed, accepted, reasons = None, False, []
            if complete and (global_epoch % options["validation_interval"] == 0 or stage_epoch == stage["epochs"]):
                observed = evaluate()
                if observed is None:
                    stopped = "deadline_during_validation"
                    reasons = ["incomplete_validation"]
                else:
                    last_complete = observed
                    last_complete_step = steps
                    scheduler.step(observed["numerical"]["token_cross_entropy"])
                    guard = fidelity.compare_nonregression(observed["fidelity"], baseline["fidelity"], selected["fidelity"])
                    reasons = list(guard["reasons"])
                    mse_limit = baseline["numerical"]["reconstructed_input_mse"]*(1+options["reconstruction_relative_tolerance"])+options["reconstruction_absolute_tolerance"]
                    if observed["numerical"]["reconstructed_input_mse"] > mse_limit:
                        reasons.append("initial_reconstruction_regression")
                    incumbent_progress = fidelity.compare_nonregression(observed["fidelity"], selected["fidelity"])
                    improves = incumbent_progress["strict_progress"] or observed["numerical"]["token_cross_entropy"] < selected["numerical"]["token_cross_entropy"]
                    if not improves:
                        reasons.append("no_fidelity_or_reference_ce_progress")
                    if not reasons and guard["accepted"]:
                        candidate_state = snapshot()
                        if time.monotonic() >= deadline:
                            stopped = "deadline_before_selection_commit"
                            reasons.append(stopped)
                        else:
                            best_state, selected, selected_epoch, accepted, stale = candidate_state, observed, global_epoch, True, 0
                    if not accepted:
                        stale += 1
            history.append(dict(epoch=global_epoch, stage=stage["name"], stage_epoch=stage_epoch,
                complete_epoch=complete, optimizer_steps=steps, learning_rate=optimizer.param_groups[0]["lr"],
                mean_minibatch_ce=sums[0]/batches if batches else None,
                mean_minibatch_weighted_ce=sums[1]/batches if batches else None,
                mean_minibatch_raw_reconstruction_mse=sums[2]/batches if batches else None,
                numerical=None if observed is None else observed["numerical"],
                source_fidelity=None if observed is None else _summary(observed["fidelity"]),
                accepted=accepted, rejection_reasons=reasons, selected_epoch=selected_epoch))
            stage_report["completed_epochs"] += int(complete)
            if stopped != "epochs_completed":
                break
            if options["patience"] and stale >= options["patience"]:
                stopped = "selection_patience"
                break
        stage_report.update(optimizer_step_end=steps, optimizer_state_end=core._optimizer_state(working, optimizer),
                            status="complete" if stage_report["completed_epochs"]==stage["epochs"] else "partial")
        stage_reports.append(stage_report)
    core._require(core.tensor_digest(student) == before, "caller model changed")
    core._require({name: m.training for name, m in student.named_modules()} == modes, "caller model modes changed")
    core._require(all(p.detach().cpu().contiguous().numpy().tobytes() == frozen[name]
        for name, p in working.named_parameters() if name in frozen), "frozen projection changed")
    diagnostic_state = snapshot() if last_complete_step == steps else None
    working.load_state_dict(best_state, strict=True)
    summarize = lambda item: None if item is None else dict(numerical=deepcopy(item["numerical"]), fidelity=_summary(item["fidelity"]))
    report = dict(schema=SCHEMA, scope="exposed_development_only", strategy=strategy,
        config=options, lineage=deepcopy(lineage), curriculum=stages, stage_reports=stage_reports,
        teacher_distillation_used=False, generation_temperature=0, encoder_context_changed=False,
        full_targets_truncated=False, training_rows_sha256=core.digest(training_rows),
        validation_rows_sha256=core.digest(validation_rows), training_references_sha256=core.digest(training_references),
        validation_references_sha256=core.digest(validation_references), codec_sha256=core.digest(codec),
        initial_weights_sha256=before, selected_weights_sha256=core.tensor_digest(working),
        frozen_parameter_names=list(frozen), frozen_parameters_verified=True,
        optimizer_steps=steps, row_presentations=presentations, valid_target_token_presentations=tokens_seen,
        optimizer_instance_count=1, optimizer_reinitialized_between_stages=False,
        selected_epoch=selected_epoch, selection="per_length_nonregression_then_fidelity_progress_then_reference_ce",
        baseline=summarize(baseline), selected=summarize(selected), last_complete_attempt=summarize(last_complete),
        last_complete_attempt_is_selected=last_complete is not None and last_complete is selected,
        exported_state_role="selected_development_state" if selected is not None else "unvalidated_initial_state",
        history=history, stopped_reason=stopped,
        last_complete_attempt_state_available=diagnostic_state is not None,
        tensor_work_estimate_bytes=estimate, memory_estimate_excludes_python_import_allocator_rss=True,
        deadline_cooperative=True, **FALSE)
    report["elapsed_seconds"] = time.monotonic()-started
    return dict(state_dict=best_state, report=report,
        last_complete_attempt_state_dict=diagnostic_state,
        predictions=[] if selected is None else deepcopy(selected["predictions"]),
        last_complete_attempt_predictions=[] if last_complete is None else deepcopy(last_complete["predictions"]))
