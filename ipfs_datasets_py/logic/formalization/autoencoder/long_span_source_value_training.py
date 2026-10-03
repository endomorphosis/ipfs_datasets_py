"""Private source-value supervision with unchanged Legal decoder selection gates.

The auxiliary head sees reconstructed source vectors only. Its targets come
from the exact authenticated training documents, on the existing decoder batch.
Free generation receives no references; only its real predictions can satisfy
the inherited per-length source-fidelity and reconstruction selection guards.
This owner cannot confer qualification or replace a native Lake admission.
"""
from copy import deepcopy
import hashlib
import math
import time

from . import decoder_distillation_experiment as core
from . import decoder_source_fidelity as fidelity
from . import source_value_decoder_experiment as values
from . import long_span_count_exposure_training as exposure

SCHEMA = "long-source-value-training/v1"
FALSE = dict(exposure.FALSE)
reference_weights = exposure.reference_weights
_summary = exposure._summary
_count_labels = exposure._count_labels
_count_logits = exposure._count_logits
_BalancedCountSelector = exposure._BalancedCountSelector
_source_batch = exposure._source_batch


def _head_specification(model, codec, source_value_weight):
    present = callable(getattr(model, "source_value_logits", None))
    core._require(present or source_value_weight == 0., "positive source-value weight requires source head")
    if not present:
        return None
    description = model.describe()
    core._require(description.get("schema") == values.SCHEMA
        and description.get("feature_kind") in ("projected_source", "inherited_conditioning")
        and description.get("max_rules") == values.MAX_RULES
        and description.get("source_fields") == list(values.SOURCE_FIELDS)
        and description.get("vocabulary_size") == len(codec["target_vocabulary"])
        and description.get("codec_sha256") == core.digest(codec),
        "authenticated source-value model specification required")
    return deepcopy(description)


def _source_value_logits(torch, model, projected, vocabulary_size):
    result = model.source_value_logits(projected)
    core._require(isinstance(result, torch.Tensor) and result.dtype == torch.float32
        and result.device.type == "cpu"
        and tuple(result.shape) == (len(projected), values.MAX_RULES, len(values.SOURCE_FIELDS), vocabulary_size)
        and core._finite(torch, result), "finite CPU source-value logits required")
    return result


def _source_value_evaluation(torch, model, rows, labels, transform, options, codec, deadline):
    """Conditional present-value metrics; absence is neither masked generation nor success."""
    by_length, by_field, predictions = {}, {}, []
    loss_sum, count, correct = 0., 0, 0
    model.eval()
    with torch.inference_mode():
        for offset in range(0, len(rows), options["batch_size"]):
            if time.monotonic() >= deadline:
                return None
            part = rows[offset:offset+options["batch_size"]]
            projected = model.project(_source_batch(torch, part, transform))
            logits = _source_value_logits(torch, model, projected, len(codec["target_vocabulary"]))
            targets = torch.tensor([labels[row["id"]] for row in part], dtype=torch.long)
            observed = torch.nn.functional.cross_entropy(logits.flatten(0, 2), targets.flatten(),
                ignore_index=-1, reduction="sum")
            core._require(core._finite(torch, observed), "nonfinite source-value evaluation")
            loss_sum += float(observed)
            for row, expected, predicted, raw in zip(part, targets.tolist(), logits.argmax(-1).tolist(), logits.tolist()):
                rule_count = sum(record[0] >= 0 for record in expected)
                length = by_length.setdefault(str(rule_count), dict(present_values=0, correct=0, rows=0))
                length["rows"] += 1
                for slot, record in enumerate(expected):
                    for field_index, target in enumerate(record):
                        if target == -1:
                            continue
                        field = values.SOURCE_FIELDS[field_index]
                        bucket = by_field.setdefault(field, dict(present_values=0, correct=0, classes={}))
                        label = codec["target_vocabulary"][target]
                        cls = bucket["classes"].setdefault(label, dict(expected=0, correct=0, predicted={}))
                        guess = codec["target_vocabulary"][predicted[slot][field_index]]
                        hit = int(predicted[slot][field_index] == target)
                        count += 1; correct += hit
                        length["present_values"] += 1; length["correct"] += hit
                        bucket["present_values"] += 1; bucket["correct"] += hit
                        cls["expected"] += 1; cls["correct"] += hit
                        cls["predicted"][guess] = cls["predicted"].get(guess, 0)+1
                predictions.append(dict(id=row["id"], expected_token_ids=expected,
                    predicted_token_ids=predicted, raw_logits=raw))
    if time.monotonic() >= deadline:
        return None
    core._require(count > 0, "source-value evaluation has no present labels")
    for bucket in by_field.values():
        bucket["accuracy"] = bucket["correct"]/bucket["present_values"]
        for cls in bucket["classes"].values():
            cls["recall"] = cls["correct"]/cls["expected"]
        bucket["macro_class_recall"] = sum(cls["recall"] for cls in bucket["classes"].values())/len(bucket["classes"])
    return dict(rows=len(rows), present_values=count, correct=correct, accuracy=correct/count,
        cross_entropy=loss_sum/count, by_length=by_length, by_field=by_field, predictions=predictions,
        absent_slots_unscored=len(rows)*values.MAX_RULES*len(values.SOURCE_FIELDS)-count,
        metric_scope="reference-present scalar slots only; not formula reconstruction",
        source_only_head=True, references_passed_to_model=False, used_for_selection=False,
        qualified=False, admitted=False, proof_authority=False)


def _evaluate(torch, model, rows, references, transform, options, codec, deadline,
              validate_rule, validator_id, source_labels=None):
    result = exposure._evaluate(torch, model, rows, references, transform, options, codec, deadline,
                                validate_rule, validator_id)
    if result is None:
        return None
    diagnostic = (None if source_labels is None else _source_value_evaluation(torch, model, rows,
        source_labels, transform, options, codec, deadline))
    if (source_labels is not None and diagnostic is None) or time.monotonic() >= deadline:
        return None
    result["source_values"] = diagnostic
    return result


def train(student, training_rows, validation_rows, *, training_references, validation_references,
          codec, input_transform, lineage, validate_rule, validator_id,
          curriculum, strategy="reference_ce", config=None, cardinality_weight=0.,
          count_exposure="current_stage", source_value_weight=0.):
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
    core._require(type(count_exposure) is str and count_exposure in ("current_stage", "balanced_all"),
                  "unknown count exposure policy")
    core._require(type(source_value_weight) in (int, float) and math.isfinite(source_value_weight)
        and 0 <= source_value_weight <= 1, "invalid source-value weight")
    head_specification = _head_specification(student, codec, source_value_weight)
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
    source_labels = (None if head_specification is None else values.reference_source_values(
        training_rows, training_references, codec, validate_rule=validate_rule))
    validation_source_labels = (None if head_specification is None else values.reference_source_values(
        validation_rows, validation_references, codec, validate_rule=validate_rule))
    stages = core._curriculum(curriculum, training_rows, options)
    parameter_bytes = sum(t.numel()*t.element_size() for t in student.state_dict().values())
    width = max(len(r["target_ids"]) for r in [*training_rows, *validation_rows])
    estimate = parameter_bytes*24 + 16*options["batch_size"]*width*len(codec["target_vocabulary"])*4
    estimate += 4*(len(training_rows)+len(validation_rows))*student.dimension
    estimate += 8*4*options["batch_size"]*(student.dimension+32)
    if head_specification is not None:
        estimate += 16*options["batch_size"]*values.MAX_RULES*len(values.SOURCE_FIELDS)*len(codec["target_vocabulary"])*4
        estimate += 8*(len(training_rows)+len(validation_rows))*values.MAX_RULES*len(values.SOURCE_FIELDS)
    # Bound per-step receipts and final scalar logits as well as tensor work.
    estimate += options["max_optimizer_steps"]*(2048+2*options["batch_size"]*640)
    if head_specification is not None:
        estimate += 128*len(validation_rows)*values.MAX_RULES*len(values.SOURCE_FIELDS)*len(codec["target_vocabulary"])
    core._require(estimate <= options["max_memory_bytes"], "trial tensor work exceeds budget")
    count_selector = (_BalancedCountSelector(training_rows, count_labels, options["seed"])
                      if count_exposure == "balanced_all" else None)
    initial_selector = None if count_selector is None else count_selector.snapshot()
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
        options, codec, deadline, validate_rule, validator_id, validation_source_labels)
    baseline = evaluate()
    selected = last_complete = baseline
    last_complete_step = 0 if baseline is not None else None
    selected_epoch = 0 if baseline is not None else None
    snapshot = lambda: {name: t.detach().cpu().clone() for name, t in working.state_dict().items()}
    best_state = snapshot()
    history, stage_reports, steps, presentations, tokens_seen, stale = [], [], 0, 0, 0, 0
    stopped = "deadline_before_complete_baseline" if baseline is None else "epochs_completed"
    by_id = {row["id"]: row for row in training_rows}
    count_presentations = 0
    count_by_class = {str(value+1): 0 for value in sorted(set(count_labels.values()))}
    mean_loss_exposure = {key: 0. for key in count_by_class}
    count_sequence = hashlib.sha256()
    decoder_sequence = hashlib.sha256()
    source_value_presentations = 0
    committed_updates = []
    gradient_norm_sum = gradient_norm_max = 0.
    gradient_norm_steps = gradient_clipped_steps = 0
    global_epoch = 0
    for stage in stages:
        if baseline is None or stopped != "epochs_completed":
            break
        current = [by_id[identity] for identity in stage["training_ids"]]
        stage_report = dict(name=stage["name"], training_rows=len(current), completed_epochs=0,
            optimizer_step_start=steps, optimizer_state_start=core._optimizer_state(working, optimizer),
            count_presentations_start=count_presentations, count_by_class_start=dict(count_by_class),
            count_mean_loss_exposure_start=dict(mean_loss_exposure),
            count_selector_start=None if count_selector is None else count_selector.snapshot())
        for stage_epoch in range(1, stage["epochs"]+1):
            global_epoch += 1
            working.train()
            order = torch.randperm(len(current), generator=generator).tolist()
            sums, batches, complete = [0., 0., 0., 0., 0.], 0, True
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
                count_part = part if count_selector is None else count_selector.take(len(part))
                count_projected = projected if count_selector is None else working.project(
                    _source_batch(torch, count_part, input_transform))
                count_logits = _count_logits(torch, working, count_projected)
                count_targets = torch.tensor([count_labels[row["id"]] for row in count_part], dtype=torch.long)
                count_loss = torch.nn.functional.cross_entropy(count_logits, count_targets)
                source_loss = weighted.new_zeros(())
                source_positions = 0
                if source_labels is not None:
                    source_logits = _source_value_logits(torch, working, projected, len(codec["target_vocabulary"]))
                    source_targets = torch.tensor([source_labels[row["id"]] for row in part], dtype=torch.long)
                    source_positions = int((source_targets != -1).sum())
                    source_loss = torch.nn.functional.cross_entropy(source_logits.flatten(0, 2),
                        source_targets.flatten(), ignore_index=-1)
                objective = weighted + options["reconstruction_weight"]*mse
                # Still compute the count diagnostic in every arm. A zero
                # multiple must not attach its graph: zero count-head grads
                # alter clipping reductions and create otherwise absent Adam
                # state, breaking exact parity with the inherited objective.
                if cardinality_weight != 0.:
                    objective = objective + cardinality_weight*count_loss
                if source_value_weight != 0.:
                    objective = objective + source_value_weight*source_loss
                core._require(core._finite(torch, objective) and core._finite(torch, source_loss), "nonfinite objective")
                if time.monotonic() >= deadline:
                    stopped, complete = "deadline", False
                    break
                objective.backward()
                preclip_norm = torch.nn.utils.clip_grad_norm_(trainable, options["max_grad_norm"], error_if_nonfinite=True)
                if time.monotonic() >= deadline:
                    optimizer.zero_grad(set_to_none=True)
                    stopped, complete = "deadline", False
                    break
                optimizer.step()
                core._require(all(core._finite(torch, p) for p in working.parameters()), "nonfinite updated state")
                steps += 1; presentations += len(part); tokens_seen += int((labels[:, 1:] != 0).sum())
                count_presentations += len(count_part)
                for row in count_part:
                    count_by_class[str(count_labels[row["id"]]+1)] += 1
                    mean_loss_exposure[str(count_labels[row["id"]]+1)] += 1./len(count_part)
                count_sequence.update(core._raw([row["id"] for row in count_part]))
                decoder_sequence.update(core._raw([row["id"] for row in part]))
                source_value_presentations += source_positions
                committed_updates.append(dict(optimizer_step=steps, epoch=global_epoch, stage=stage["name"],
                    decoder_row_ids=[row["id"] for row in part], count_row_ids=[row["id"] for row in count_part],
                    target_token_presentations=int((labels[:, 1:] != 0).sum()),
                    source_value_presentations=source_positions,
                    learning_rate=optimizer.param_groups[0]["lr"], preclip_norm=float(preclip_norm.detach()),
                    token_ce=float(plain.detach()), weighted_token_ce=float(weighted.detach()),
                    count_ce=float(count_loss.detach()), source_value_ce=float(source_loss.detach()),
                    raw_reconstruction_mse=float(mse.detach()), objective=float(objective.detach())))
                norm = float(preclip_norm.detach())
                gradient_norm_sum += norm; gradient_norm_max = max(gradient_norm_max, norm)
                gradient_norm_steps += 1; gradient_clipped_steps += int(norm > options["max_grad_norm"])
                sums = [total+float(value.detach()) for total, value in zip(sums, (plain, weighted, mse, count_loss, source_loss))]
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
                mean_minibatch_source_value_ce=sums[4]/batches if batches else None,
                mean_minibatch_ce=sums[0]/batches if batches else None,
                mean_minibatch_weighted_ce=sums[1]/batches if batches else None,
                mean_minibatch_raw_reconstruction_mse=sums[2]/batches if batches else None,
                numerical=None if observed is None else observed["numerical"],
                source_count=None if observed is None else {k:deepcopy(v) for k,v in observed["source_count"].items() if k!="predictions"},
                source_fidelity=None if observed is None else _summary(observed["fidelity"]),
                source_values=None if observed is None or observed["source_values"] is None else
                    {k:deepcopy(v) for k,v in observed["source_values"].items() if k!="predictions"},
                accepted=accepted, rejection_reasons=reasons, selected_epoch=selected_epoch))
            stage_report["completed_epochs"] += int(complete)
            if stopped != "epochs_completed":
                break
            if options["patience"] and stale >= options["patience"]:
                stopped = "selection_patience"
                break
        stage_report.update(optimizer_step_end=steps, optimizer_state_end=core._optimizer_state(working, optimizer),
                            status="complete" if stage_report["completed_epochs"]==stage["epochs"] else "partial",
                            count_presentations_end=count_presentations, count_by_class_end=dict(count_by_class),
                            count_mean_loss_exposure_end=dict(mean_loss_exposure),
                            count_selector_end=None if count_selector is None else count_selector.snapshot())
        stage_reports.append(stage_report)
    core._require(core.tensor_digest(student) == before, "caller model changed")
    core._require({name: m.training for name, m in student.named_modules()} == modes, "caller model modes changed")
    core._require(all(p.detach().cpu().contiguous().numpy().tobytes() == frozen[name]
        for name, p in working.named_parameters() if name in frozen), "frozen projection changed")
    diagnostic_state = snapshot() if last_complete_step == steps else None
    diagnostic_digest = core.tensor_digest(working) if diagnostic_state is not None else None
    working.load_state_dict(best_state, strict=True)
    summarize = lambda item: None if item is None else dict(numerical=deepcopy(item["numerical"]), fidelity=_summary(item["fidelity"]), source_count=deepcopy(item["source_count"]), source_values=deepcopy(item["source_values"]))
    report = dict(schema=SCHEMA, scope="exposed_development_only", strategy=strategy,
        config=options, cardinality_weight=cardinality_weight, count_exposure=count_exposure,
        source_value_weight=source_value_weight, source_value_head=head_specification,
        source_value_presentations=source_value_presentations,
        source_value_training_row_policy="same decoder batch; no extra source rows",
        source_value_validation_rows_used_for_training=False,
        source_value_reference_documents_passed_to_model=False,
        source_value_target_access="authenticated training/evaluation loss only",
        source_value_metrics_used_for_selection=False,
        source_value_absent_slots_ignored=True,
        committed_decoder_batch_ids_sha256=decoder_sequence.hexdigest(),
        committed_updates=committed_updates,
        count_target_access="training_and_evaluation_loss_only",
        count_training_row_presentations=count_presentations, count_training_presentations_by_class=count_by_class,
        count_mean_loss_exposure_by_class=mean_loss_exposure,
        count_mean_loss_exposure_definition="sum_over_committed_rows(1/count_batch_size)",
        committed_count_batch_ids_sha256=count_sequence.hexdigest(),
        count_selector_initial=initial_selector,
        count_selector_final=None if count_selector is None else count_selector.snapshot(),
        count_selector_draws_may_include_uncommitted_final_batch=True,
        count_training_inventory_sha256=core.digest([dict(id=row["id"],input=row["input"],
            source_text=row["source_text"],count=count_labels[row["id"]]+1) for row in training_rows]),
        count_reference_documents_passed_to_model=False, count_validation_rows_used_for_training=False,
        count_supervision="authenticated_training_reference_rule_count_only",
        gradient_norms=dict(optimizer_steps=gradient_norm_steps,
            mean_preclip_norm=gradient_norm_sum/gradient_norm_steps if gradient_norm_steps else None,
            max_preclip_norm=gradient_norm_max if gradient_norm_steps else None,
            norm_exceeded_limit_steps=gradient_clipped_steps,limit=options["max_grad_norm"],
            source="existing_clip_grad_norm_return_no_extra_gradient_arithmetic"),
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
