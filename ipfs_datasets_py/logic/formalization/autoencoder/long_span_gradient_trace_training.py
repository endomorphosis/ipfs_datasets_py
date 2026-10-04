"""Versioned bounded gradient observation for a Legal decoder experiment.

The count label is training/evaluation supervision only. Numerical generation
receives the source-derived count head, never a reference count. This version
preserves the prior owner's per-length source-fidelity and reconstruction guards.
Balanced exposure also trains the shared source conditioner; it is not an
isolated count-head-only change. Decoder examples and their shuffle are unchanged.
It is a private development owner and cannot promote a production checkpoint.
"""
from copy import deepcopy
import hashlib
import random
import math
import time

from . import decoder_distillation_experiment as core
from . import decoder_source_fidelity as fidelity
from . import long_span_decoder_training as inherited
from . import decoder_gradient_replay as replay

SCHEMA = "long-source-gradient-trace-training/v1"
FALSE = dict(inherited.FALSE)
reference_weights = inherited.reference_weights
_summary = inherited._summary



def _trace_config(value):
    if value is None:
        return dict(enabled=False,threshold=50.,top_k=2,module_summaries=False)
    core._require(type(value) is dict and set(value)=={"enabled","threshold","top_k","module_summaries"},
                  "closed explicit gradient trace configuration required")
    core._require(type(value["enabled"]) is bool and type(value["module_summaries"]) is bool,
                  "gradient trace flags must be Boolean")
    core._require(type(value["threshold"]) in (int,float) and math.isfinite(value["threshold"])
                  and 0 <= value["threshold"] <= 1e12, "invalid gradient trace threshold")
    core._require(type(value["top_k"]) is int and 1 <= value["top_k"] <= 4,
                  "bounded gradient trace top_k required")
    return deepcopy(value)


class GradientTraceObserver:
    """Detached observation after the live clip, without changing live gradients.

    Per-step metadata is bounded by the already declared optimizer-step budget.
    Only qualifying top-K pre-step snapshots are cloned. A pending snapshot can
    temporarily add one packet; a failed deadline never replaces a committed
    event, and its packet is explicitly uncommitted and not replay-eligible.
    """
    def __init__(self, configuration, *, options, input_transform, codec,
                 cardinality_weight, strategy, count_exposure):
        started = time.monotonic()
        self.configuration = _trace_config(configuration)
        self.options = deepcopy(options)
        self.transform = deepcopy(input_transform)
        self.codec_sha256 = core.digest(codec)
        self.cardinality_weight = cardinality_weight
        self.strategy = strategy
        self.count_exposure = count_exposure
        self.steps, self.events, self.uncommitted = [], [], []
        self.elapsed_seconds = self.capture_seconds = 0.
        self.captures = self.displaced = self.peak_snapshot_bytes = 0
        self.initialization_seconds = time.monotonic()-started if self.configuration["enabled"] else 0.

    @staticmethod
    def _rank(event):
        return (event["preclip_norm"], -event["optimizer_step_before"])

    @staticmethod
    def _bytes(value):
        # Tensor storage only; Python metadata is bounded separately in preflight.
        if hasattr(value,"numel") and hasattr(value,"element_size"):
            return value.numel()*value.element_size()
        if isinstance(value,dict):
            return sum(GradientTraceObserver._bytes(item) for item in value.values())
        if isinstance(value,(list,tuple)):
            return sum(GradientTraceObserver._bytes(item) for item in value)
        return 0

    def before_step(self, model, optimizer, generator, *, metadata, decoder_rows,
                    count_rows, weights, count_targets, losses, preclip_norm, count_selector):
        if not self.configuration["enabled"]:
            return None
        started = time.monotonic()
        core._require(len(self.steps)<self.options["max_optimizer_steps"], "gradient trace step bound exceeded")
        norm = float(preclip_norm.detach())
        record = dict(metadata, preclip_norm=norm,
            decoder_row_ids=[row["id"] for row in decoder_rows],
            count_row_ids=[row["id"] for row in count_rows],
            learning_rates=[group["lr"] for group in optimizer.param_groups],
            losses={name:float(value.detach()) for name,value in losses.items()}, committed=False)
        if self.configuration["module_summaries"]:
            torch = core._torch()
            modules = {}
            for name, parameter in model.named_parameters():
                group = modules.setdefault(name.rpartition(".")[0], dict(parameter_count=0,
                    gradients_none=0,gradient_elements=0,gradient_squared_norm=0.))
                group["parameter_count"] += 1
                if parameter.grad is None:
                    group["gradients_none"] += 1
                else:
                    gradient = parameter.grad.detach()
                    group["gradient_elements"] += gradient.numel()
                    group["gradient_squared_norm"] += float(gradient.double().square().sum())
            for group in modules.values():
                group["postclip_l2_norm"] = math.sqrt(group.pop("gradient_squared_norm"))
            record["postclip_module_summaries"] = modules
        self.steps.append(record)
        qualifies = norm > self.configuration["threshold"]
        qualifies = qualifies and (len(self.events)<self.configuration["top_k"]
            or self._rank(record)>min(map(self._rank,self.events)))
        event = None
        if qualifies:
            capture_started = time.monotonic()
            event = dict(schema="decoder-gradient-event/v1",complete=False,committed=False,
                **{key:deepcopy(value) for key,value in record.items() if key!="committed"},
                model_state_dict={name:t.detach().cpu().clone() for name,t in model.state_dict().items()},
                optimizer_state_dict=deepcopy(optimizer.state_dict()),optimizer_class="AdamW",
                trainable_parameter_names=[name for name,parameter in model.named_parameters() if parameter.requires_grad],
                config=deepcopy(self.options),cardinality_weight=self.cardinality_weight,
                strategy=self.strategy,count_exposure=self.count_exposure,input_transform=deepcopy(self.transform),
                codec_sha256=self.codec_sha256,decoder_batch_sha256=core.digest(decoder_rows),
                count_batch_sha256=core.digest(count_rows),
                token_weights_sha256=core.digest({row["id"]:weights[row["id"]] for row in decoder_rows}),
                count_targets=count_targets.detach().cpu().tolist(),
                pre_step_model_sha256=core.tensor_digest(model),
                pre_step_optimizer_sha256=replay.state_digest(optimizer.state_dict()),
                clipped_gradient_sha256=replay.gradient_digest(model),
                poststep_tensor_sha256=None,poststep_optimizer_sha256=None,
                module_modes={name:module.training for name,module in model.named_modules()},
                rng_state=dict(torch=core._torch().get_rng_state().clone(),python=random.getstate(),
                               decoder_generator=generator.get_state().clone()),
                source_selector_snapshot=None if count_selector is None else count_selector.snapshot(),
                scope="captured_numerical_update_only",qualified=False,admitted=False,proof_authority=False)
            event["captured_tensor_bytes"] = self._bytes(event)
            self.captures += 1
            self.peak_snapshot_bytes = max(self.peak_snapshot_bytes,
                sum(item["captured_tensor_bytes"] for item in self.events)+event["captured_tensor_bytes"])
            self.capture_seconds += time.monotonic()-capture_started
        self.elapsed_seconds += time.monotonic()-started
        return (record,event)

    def after_step(self, ticket, model, optimizer):
        if ticket is None:
            return
        started = time.monotonic()
        record,event = ticket
        record["committed"] = True
        if event is not None:
            event.update(complete=True,committed=True,poststep_tensor_sha256=core.tensor_digest(model),
                         poststep_optimizer_sha256=replay.state_digest(optimizer.state_dict()))
            event["event_sha256"] = replay.event_digest(event)
            self.events.append(event)
            self.events.sort(key=self._rank,reverse=True)
            if len(self.events)>self.configuration["top_k"]:
                self.events.pop(); self.displaced += 1
            record["captured_event_sha256"] = event["event_sha256"]
        self.elapsed_seconds += time.monotonic()-started

    def abort_step(self,ticket,reason):
        if ticket is None:
            return
        started = time.monotonic()
        record,event = ticket
        record["uncommitted_reason"] = reason
        if event is not None:
            event["uncommitted_reason"] = reason
            event["event_sha256"] = replay.event_digest(event)
            self.uncommitted.append(event)
        self.elapsed_seconds += time.monotonic()-started

    def report(self):
        started = time.monotonic()
        def summary(event):
            keys=("optimizer_step_before","epoch","stage","preclip_norm","event_sha256",
                  "complete","committed","pre_step_model_sha256","pre_step_optimizer_sha256",
                  "poststep_tensor_sha256","poststep_optimizer_sha256","clipped_gradient_sha256",
                  "captured_tensor_bytes")
            return {key:event[key] for key in keys}
        result = dict(configuration=deepcopy(self.configuration),steps=deepcopy(self.steps),
            captured_event_summaries=[summary(event) for event in self.events],
            uncommitted_event_summaries=[summary(event) for event in self.uncommitted],
            qualifying_captures_created=self.captures,displaced_captures=self.displaced,
            retained_tensor_bytes=sum(event["captured_tensor_bytes"] for event in self.events+self.uncommitted),
            peak_snapshot_tensor_bytes=self.peak_snapshot_bytes,capture_seconds=self.capture_seconds,
            observer_elapsed_seconds=self.elapsed_seconds,
            ranking="descending_preclip_norm_then_earliest_step; strict_threshold; committed_events_only",
            tensor_byte_estimate_excludes_python_metadata=True,
            additional_backwards_in_live_path=False,additional_preclip_norm_calls=False,
            observer_arithmetic="detached_postclip_only",proof_authority=False,qualified=False)
        report_seconds = time.monotonic()-started if self.configuration["enabled"] else 0.
        result.update(initialization_seconds=self.initialization_seconds,
            report_construction_seconds=report_seconds,
            total_observer_seconds=self.initialization_seconds+self.elapsed_seconds+report_seconds,
            timing_scope="observer_initialization_callbacks_and_report; caller_packet_serialization_excluded")
        return result


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


class _BalancedCountSelector:
    """Private training-only row rotation; independent of decoder Torch RNG."""
    def __init__(self, rows, labels, seed):
        core._require(type(rows) is list and rows and type(seed) is int and 0 <= seed <= 2**31-1,
                      "bounded count selector inputs required")
        core._require(len({row["id"] for row in rows}) == len(rows)
            and set(labels) == {row["id"] for row in rows}
            and all(type(value) is int and 0 <= value < 32 for value in labels.values()),
            "exact training count label inventory required")
        self.seed = seed
        self.rng = random.Random(seed)
        self.by_id = {row["id"]: row for row in rows}
        self.classes = sorted(set(labels.values()))
        self.order = {value: [row["id"] for row in rows if labels[row["id"]] == value]
                      for value in self.classes}
        for values in self.order.values():
            self.rng.shuffle(values)
        self.position = {value: 0 for value in self.classes}
        self.cycles = {value: 0 for value in self.classes}
        self.next_class = self.draws = 0

    def take(self, count):
        core._require(type(count) is int and 1 <= count <= 128, "bounded count batch required")
        result = []
        for _ in range(count):
            value = self.classes[self.next_class]
            self.next_class = (self.next_class+1) % len(self.classes)
            if self.position[value] == len(self.order[value]):
                self.rng.shuffle(self.order[value])
                self.position[value] = 0
                self.cycles[value] += 1
            result.append(self.by_id[self.order[value][self.position[value]]])
            self.position[value] += 1
            self.draws += 1
        return result

    def snapshot(self):
        return dict(schema="training-only-count-round-robin/v1", seed=self.seed,
            classes=[value+1 for value in self.classes], next_class_index=self.next_class,
            drawn_rows=self.draws, row_order={str(key+1): list(value) for key,value in self.order.items()},
            row_positions={str(key+1): value for key,value in self.position.items()},
            completed_cycles={str(key+1): value for key,value in self.cycles.items()},
            rng_state_sha256=core.digest(self.rng.getstate()),
            replay="original_ordered_training_inventory_plus_seed_and_drawn_rows",
            validation_rows_available=False, decoder_rng_shared=False,
            state_is_diagnostic_not_optimizer_resume=True)


def _source_batch(torch, rows, transform):
    raw = torch.tensor([row["input"] for row in rows], dtype=torch.float32)
    return (raw-torch.tensor(transform["mean"], dtype=torch.float32))/transform["scale"]


def _count_evaluation(torch, model, rows, references, transform, options, deadline):
    labels = _count_labels(references)
    result, loss, by_length = [], 0., {}
    confusion = {str(value+1): {str(predicted): 0 for predicted in range(1,33)}
                 for value in sorted(set(labels.values()))}
    entropy_sum, confidence_sum = 0., 0.
    model.eval()
    with torch.inference_mode():
        for offset in range(0,len(rows),options["batch_size"]):
            if time.monotonic() >= deadline:
                return None
            part = rows[offset:offset+options["batch_size"]]
            data = _source_batch(torch, part, transform)
            logits = _count_logits(torch, model, model.project(data))
            targets = torch.tensor([labels[row["id"]] for row in part], dtype=torch.long)
            observed = torch.nn.functional.cross_entropy(logits, targets, reduction="sum")
            core._require(core._finite(torch, observed), "nonfinite count evaluation")
            log_probs = torch.log_softmax(logits, dim=-1)
            probabilities = torch.softmax(logits, dim=-1)
            entropies = -(probabilities*log_probs).sum(-1)
            core._require(core._finite(torch, probabilities) and core._finite(torch, entropies),
                          "nonfinite count probability diagnostics")
            loss += float(observed)
            for row, predicted, values, probs, entropy in zip(part, logits.argmax(-1).tolist(),
                    logits.tolist(), probabilities.tolist(), entropies.tolist()):
                expected = labels[row["id"]]+1
                item = by_length.setdefault(str(expected), dict(rows=0,correct=0,absolute_error=0))
                item["rows"] += 1; item["correct"] += int(predicted+1==expected)
                item["absolute_error"] += abs(predicted+1-expected)
                confusion[str(expected)][str(predicted+1)] += 1
                entropy_sum += entropy; confidence_sum += max(probs)
                result.append(dict(id=row["id"],expected=expected,predicted=predicted+1,
                    logits=values,probabilities=probs,predictive_entropy=entropy))
    if time.monotonic() >= deadline:
        return None
    return dict(rows=len(rows),cross_entropy=loss/len(rows),correct=sum(x["correct"] for x in by_length.values()),
        by_length=by_length,confusion_matrix=confusion,confusion_axes="expected_then_predicted_count",
        mean_predictive_entropy=entropy_sum/len(rows),mean_max_probability=confidence_sum/len(rows),
        predictions=result,source_only_head=True,used_for_selection=False,
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
          curriculum, strategy="reference_ce", config=None, cardinality_weight=0.,
          count_exposure="current_stage", gradient_trace=None):
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
    count_labels = _count_labels(training_references)
    _count_labels(validation_references)
    trace_configuration = _trace_config(gradient_trace)
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
    estimate += 8*4*options["batch_size"]*(student.dimension+32)
    trace_snapshot_estimate = (4*parameter_bytes+20000)*(trace_configuration["top_k"]+1) if trace_configuration["enabled"] else 0
    maximum_id_bytes = max(len(row["id"].encode()) for row in training_rows)
    trace_metadata_estimate = (options["max_optimizer_steps"]*(2048+2*options["batch_size"]*(maximum_id_bytes+8)
        +len(list(student.named_parameters()))*256)) if trace_configuration["enabled"] else 0
    estimate += trace_snapshot_estimate+trace_metadata_estimate
    core._require(estimate <= options["max_memory_bytes"], "trial tensor and trace work exceeds budget")
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
        options, codec, deadline, validate_rule, validator_id)
    trace = GradientTraceObserver(trace_configuration,options=options,input_transform=input_transform,codec=codec,
        cardinality_weight=cardinality_weight,strategy=strategy,count_exposure=count_exposure)
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
                count_part = part if count_selector is None else count_selector.take(len(part))
                count_projected = projected if count_selector is None else working.project(
                    _source_batch(torch, count_part, input_transform))
                count_logits = _count_logits(torch, working, count_projected)
                count_targets = torch.tensor([count_labels[row["id"]] for row in count_part], dtype=torch.long)
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
                preclip_norm = torch.nn.utils.clip_grad_norm_(trainable, options["max_grad_norm"], error_if_nonfinite=True)
                if time.monotonic() >= deadline:
                    optimizer.zero_grad(set_to_none=True)
                    stopped, complete = "deadline", False
                    break
                trace_ticket = None
                if trace_configuration["enabled"]:
                    trace_ticket = trace.before_step(working,optimizer,generator,
                        metadata=dict(optimizer_step_before=steps,epoch=global_epoch,stage=stage["name"],stage_epoch=stage_epoch),
                        decoder_rows=part,count_rows=count_part,weights=weights,count_targets=count_targets,
                        losses=dict(token_ce=plain,weighted_token_ce=weighted,count_ce=count_loss,mse=mse,objective=objective),
                        preclip_norm=preclip_norm,count_selector=count_selector)
                    if time.monotonic() >= deadline:
                        trace.abort_step(trace_ticket,"deadline_before_optimizer_step")
                        optimizer.zero_grad(set_to_none=True)
                        stopped,complete="deadline",False
                        break
                optimizer.step()
                core._require(all(core._finite(torch, p) for p in working.parameters()), "nonfinite updated state")
                trace.after_step(trace_ticket,working,optimizer)
                steps += 1; presentations += len(part); tokens_seen += int((labels[:, 1:] != 0).sum())
                count_presentations += len(count_part)
                for row in count_part:
                    count_by_class[str(count_labels[row["id"]]+1)] += 1
                    mean_loss_exposure[str(count_labels[row["id"]]+1)] += 1./len(count_part)
                count_sequence.update(core._raw([row["id"] for row in count_part]))
                norm = float(preclip_norm.detach())
                gradient_norm_sum += norm; gradient_norm_max = max(gradient_norm_max, norm)
                gradient_norm_steps += 1; gradient_clipped_steps += int(norm > options["max_grad_norm"])
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
    summarize = lambda item: None if item is None else dict(numerical=deepcopy(item["numerical"]), fidelity=_summary(item["fidelity"]), source_count=deepcopy(item["source_count"]))
    report = dict(schema=SCHEMA, scope="exposed_development_only", strategy=strategy,
        config=options, cardinality_weight=cardinality_weight, count_exposure=count_exposure,
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
        gradient_trace=trace.report(),
        trace_snapshot_estimate_bytes=trace_snapshot_estimate,trace_metadata_estimate_bytes=trace_metadata_estimate,
        tensor_work_estimate_bytes=estimate, memory_estimate_excludes_python_import_allocator_rss=True,
        deadline_cooperative=True, **FALSE)
    report["elapsed_seconds"] = time.monotonic()-started
    return dict(state_dict=best_state, report=report,gradient_events=trace.events,
        uncommitted_gradient_events=trace.uncommitted,
        last_complete_attempt_state_dict=diagnostic_state,
        predictions=[] if selected is None else deepcopy(selected["predictions"]),
        last_complete_attempt_predictions=[] if last_complete is None else deepcopy(last_complete["predictions"]))
