"""Reference-supervised Legal decoder experiment with auxiliary source count loss.

The count label is training/evaluation supervision only. Numerical generation
receives the source-derived count head, never a reference count. This version
preserves the prior owner's per-length source-fidelity and reconstruction guards.
It is a private development owner and cannot promote a production checkpoint.
"""
from copy import deepcopy
import math
import time

from . import decoder_distillation_experiment as core
from . import decoder_source_fidelity as fidelity
from . import long_span_decoder_training as inherited

SCHEMA = "long-source-cardinality-training/v1"
FALSE = dict(inherited.FALSE)
reference_weights = inherited.reference_weights
_summary = inherited._summary


def _count_labels(references):
    core._require(type(references) is list and 1 <= len(references) <= 4096, "complete bounded count references required")
    core._require(all(type(row) is dict and type(row.get("id")) is str and row["id"]
        and type(row.get("clause_count")) is int and 1 <= row["clause_count"] <= 32
        and type(row.get("target")) is dict and type(row["target"].get("rules")) is list
        and row["clause_count"] == len(row["target"]["rules"])
        for row in references), "count supervision must match complete bounded rule targets")
    result = {row["id"]: row["clause_count"]-1 for row in references}
    core._require(len(result)==len(references), "duplicate count reference IDs")
    return result


def _count_logits(torch, model, projected):
    values = model.count_logits(projected)
    core._require(isinstance(values, torch.Tensor) and values.device.type=="cpu" and values.dtype==torch.float32
        and tuple(values.shape)==(len(projected),32) and core._finite(torch, values),
        "finite CPU source-derived 32-class count logits required")
    return values


def _count_evaluation(torch, model, rows, references, transform, options, deadline):
    labels = _count_labels(references)
    result, loss, by_length = [], 0., {}
    model.eval()
    with torch.inference_mode():
        for offset in range(0,len(rows),options["batch_size"]):
            if time.monotonic() >= deadline:
                return None
            part = rows[offset:offset+options["batch_size"]]
            data, _ = core._batch(torch, part, transform)
            logits = _count_logits(torch, model, model.project(data))
            targets = torch.tensor([labels[row["id"]] for row in part], dtype=torch.long)
            observed = torch.nn.functional.cross_entropy(logits, targets, reduction="sum")
            core._require(core._finite(torch, observed), "nonfinite count evaluation")
            loss += float(observed)
            for row, predicted in zip(part, logits.argmax(-1).tolist()):
                expected = labels[row["id"]]+1
                item = by_length.setdefault(str(expected), dict(rows=0,correct=0,absolute_error=0))
                item["rows"] += 1; item["correct"] += int(predicted+1==expected)
                item["absolute_error"] += abs(predicted+1-expected)
                result.append(dict(id=row["id"],expected=expected,predicted=predicted+1))
    if time.monotonic() >= deadline:
        return None
    return dict(rows=len(rows),cross_entropy=loss/len(rows),correct=sum(x["correct"] for x in by_length.values()),
        by_length=by_length,predictions=result,source_only_head=True,used_for_selection=False,
        reference_count_supplied_to_generation=False)


def _evaluate(torch, model, rows, references, transform, options, codec, deadline, validate_rule, validator_id):
    numeric = core._evaluate(torch, model, rows, transform, options, len(codec["target_vocabulary"]), deadline)
    if numeric is None:
        return None
    source = fidelity.score_predictions(references, numeric["predictions"], codec=codec,
        validate_rule=validate_rule, output_limit=options["max_target_tokens"], validator_id=validator_id)
    count = _count_evaluation(torch, model, rows, references, transform, options, deadline)
    if count is None or time.monotonic() >= deadline:
        return None
    core._require(source["complete_evaluation"], "incomplete source-fidelity evaluation")
    return dict(numerical={k: v for k, v in numeric.items() if k != "predictions"},
                fidelity=source, source_count=count, predictions=numeric["predictions"])


def train(student, training_rows, validation_rows, *, training_references, validation_references,
          codec, input_transform, lineage, validate_rule, validator_id,
          curriculum, strategy="reference_ce", config=None, cardinality_weight=0.):
    """Fresh reference-supervised fit; source fidelity gates experimental selection.

    The last complete attempt is retained as an explicitly unselected diagnostic.
    Its metrics cannot be substituted for the conservatively selected state.
    Adam/RNG/scheduler state persists across stages but is not exported for resume.
    """
    started = time.monotonic()
    core._require(config is None or type(config) is dict, "configuration must be a mapping")
    options = core._config({"alpha": 0., **(config or {})})
    core._require(options["alpha"] == 0., "unqualified teacher cannot supervise this source-fidelity trial")
    core._require(type(cardinality_weight) in (int,float) and math.isfinite(cardinality_weight)
        and 0 <= cardinality_weight <= 1, "invalid cardinality weight")
    core._require(callable(getattr(student,"count_logits",None)), "explicit source count head required")
    count_labels = _count_labels(training_references)
    _count_labels(validation_references)
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
            sums, batches, complete = [0., 0., 0., 0.], 0, True
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
                count_logits = _count_logits(torch, working, projected)
                count_targets = torch.tensor([count_labels[row["id"]] for row in part], dtype=torch.long)
                count_loss = torch.nn.functional.cross_entropy(count_logits, count_targets)
                objective = weighted + options["reconstruction_weight"]*mse
                # Still compute the count diagnostic in every arm. A zero
                # multiple must not attach its graph: zero count-head grads
                # alter clipping reductions and create otherwise absent Adam
                # state, breaking exact parity with the inherited objective.
                if cardinality_weight != 0.:
                    objective = objective + cardinality_weight*count_loss
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
                sums = [total+float(value.detach()) for total, value in zip(sums, (plain, weighted, mse, count_loss))]
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
                mean_minibatch_count_ce=sums[3]/batches if batches else None,
                mean_minibatch_ce=sums[0]/batches if batches else None,
                mean_minibatch_weighted_ce=sums[1]/batches if batches else None,
                mean_minibatch_raw_reconstruction_mse=sums[2]/batches if batches else None,
                numerical=None if observed is None else observed["numerical"],
                source_count=None if observed is None else {k:deepcopy(v) for k,v in observed["source_count"].items() if k!="predictions"},
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
    diagnostic_digest = core.tensor_digest(working) if diagnostic_state is not None else None
    working.load_state_dict(best_state, strict=True)
    summarize = lambda item: None if item is None else dict(numerical=deepcopy(item["numerical"]), fidelity=_summary(item["fidelity"]), source_count=deepcopy(item["source_count"]))
    report = dict(schema=SCHEMA, scope="exposed_development_only", strategy=strategy,
        config=options, cardinality_weight=cardinality_weight, count_target_access="training_and_evaluation_loss_only",
        count_metrics_used_for_selection=False, lineage=deepcopy(lineage), curriculum=stages, stage_reports=stage_reports,
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
        last_complete_attempt_weights_sha256=diagnostic_digest,
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
