"""Bounded, training-only diagnostics for an authenticated frozen clause head.

This module intentionally imports no project modules and accepts no decoder,
validation cohort, source parser, or formula evaluator.  Its input vectors are
already projected and normalized by the authenticated exporter.  An external
caller must authenticate both expected input hashes against its source receipt;
a self-supplied digest alone is not provenance.  No result qualifies a formula.
"""
from copy import deepcopy
import hashlib
import json
import math
import re
import time


FIELDS = ("actor", "modality", "object")
FIELD_COEFFICIENT = 0.25 / 4
SCHEMA = "source-field-readout-probe/v1"
TRAINING_SCHEMA = "source-field-readout-probe-training/v1"
HEAD_SCHEMA = "source-field-readout-probe-initial-head/v1"
PARAMETER_NAMES = ("source_projection.weight", "source_projection.bias",
                   "field_readout.weight", "field_readout.bias")
_SHA = re.compile(r"[0-9a-f]{64}\Z")


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(value):
    """Canonical plain-JSON digest used by the exporter and its bound caller."""
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def _closed(value, keys, label):
    _require(type(value) is dict and set(value) == set(keys), "closed " + label + " required")


def _numbers(value, shape, label, limit):
    if shape:
        _require(type(value) is list and len(value) == shape[0], label + " shape differs")
        for part in value:
            _numbers(part, shape[1:], label, limit)
    else:
        _require(type(value) in (int, float) and abs(value) <= limit and math.isfinite(value),
                 label + " requires bounded finite real values, excluding bool")


def _bound(value, expected, label):
    _require(type(expected) is str and _SHA.fullmatch(expected) is not None,
             "external " + label + " SHA256 required")
    _require(digest(value) == expected, label + " hash differs")


def _validate(training, initial_head, expected_training_sha256, expected_initial_head_sha256):
    _closed(training, {"schema", "split", "dimension", "vocabulary_size", "fields", "rows"}, "training input")
    _require(training["schema"] == TRAINING_SCHEMA and training["split"] == "train",
             "explicit training-only input required")
    _require(type(training["dimension"]) is int and training["dimension"] == 8
             and type(training["vocabulary_size"]) is int and training["vocabulary_size"] == 32
             and type(training["fields"]) is list and training["fields"] == list(FIELDS),
             "8D, full 32-token vocabulary, and ordered non-action fields required")
    rows = training["rows"]
    _require(type(rows) is list and 1 <= len(rows) <= 180, "one to 180 training occurrences required")
    seen, literals = set(), {}
    for row in rows:
        _closed(row, {"id", "source_sha256", "input", "labels"}, "training row")
        _require(type(row["id"]) is str and 0 < len(row["id"]) <= 512 and row["id"] not in seen,
                 "bounded unique occurrence id required")
        seen.add(row["id"])
        _require(type(row["source_sha256"]) is str and _SHA.fullmatch(row["source_sha256"]) is not None,
                 "literal source SHA256 required")
        _numbers(row["input"], (8,), "normalized frozen input", 1e6)
        _closed(row["labels"], FIELDS, "field labels")
        _require(all(type(row["labels"][field]) is int and 0 <= row["labels"][field] < 32
                     for field in FIELDS), "full-vocabulary integer labels required")
        signature = digest({"input": row["input"], "labels": row["labels"]})
        _require(row["source_sha256"] not in literals or literals[row["source_sha256"]] == signature,
                 "repeated literal source has conflicting inputs or labels")
        literals[row["source_sha256"]] = signature
    _closed(initial_head, {"schema", "dimension", "vocabulary_size", "hidden_width", "fields", "parameters"}, "initial head")
    _require(initial_head["schema"] == HEAD_SCHEMA and initial_head["fields"] == list(FIELDS),
             "ordered source-field initial head required")
    for key, value in (("dimension", 8), ("vocabulary_size", 32), ("hidden_width", 64)):
        _require(type(initial_head[key]) is int and initial_head[key] == value, "initial head " + key + " differs")
    _closed(initial_head["parameters"], PARAMETER_NAMES, "initial parameters")
    for name, shape in zip(PARAMETER_NAMES, ((64, 8), (64,), (96, 64), (96,))):
        _numbers(initial_head["parameters"][name], shape, name, 1e4)
    _require(all(value == 0 for row in initial_head["parameters"]["field_readout.weight"] for value in row)
             and all(value == 0 for value in initial_head["parameters"]["field_readout.bias"]),
             "fresh zero-readout initial head required")
    _bound(training, expected_training_sha256, "training")
    _bound(initial_head, expected_initial_head_sha256, "initial head")


def _deadline(deadline):
    if time.monotonic() >= deadline:
        raise TimeoutError("source-field probe deadline")


def _forward(torch, parameters, inputs, fields):
    hidden = torch.tanh(torch.nn.functional.linear(inputs, parameters[0], parameters[1]))
    return torch.nn.functional.linear(hidden, parameters[2], parameters[3]).reshape(len(inputs), len(fields), 32)


def _norm(torch, values):
    return float(torch.sqrt(sum(value.detach().double().square().sum() for value in values)))


def _state(parameters):
    return {name: parameter.detach().tolist() for name, parameter in zip(PARAMETER_NAMES, parameters)}


def _optimizer_state(optimizer, parameters):
    result = {}
    for name, parameter in zip(PARAMETER_NAMES, parameters):
        state = optimizer.state.get(parameter, {})
        result[name] = {key: value.detach().tolist() if hasattr(value, "detach") else value
                        for key, value in state.items()}
    return result


def _metrics(torch, parameters, inputs, labels, fields, initial, step, deadline):
    """Full-vocabulary metrics and pre-clipping field gradients at one state."""
    _deadline(deadline)
    logits = _forward(torch, parameters, inputs, fields)
    result, gradients = {}, {}
    for index, field in enumerate(fields):
        _deadline(deadline)
        values, targets = logits[:, index], labels[:, index]
        ce = torch.nn.functional.cross_entropy(values, targets)
        gradient = torch.autograd.grad(FIELD_COEFFICIENT * ce, parameters, retain_graph=True)
        gradients[field] = gradient
        wrong = values.detach().clone()
        wrong.scatter_(1, targets[:, None], float("-inf"))
        margins = values.detach().gather(1, targets[:, None]).flatten() - wrong.max(dim=1).values
        result[field] = dict(logits=values.detach().tolist(), predictions=values.detach().argmax(dim=1).tolist(),
            cross_entropy=float(ce.detach()), correct=int((values.detach().argmax(dim=1) == targets).sum()),
            rows=len(inputs), accuracy=float((values.detach().argmax(dim=1) == targets).double().mean()),
            target_minus_best_other_margins=margins.tolist(), field_coefficient=FIELD_COEFFICIENT,
            weighted_cross_entropy=float((FIELD_COEFFICIENT * ce).detach()),
            weighted_gradient_norms=dict(all=_norm(torch, gradient),
                source_projection=_norm(torch, gradient[:2]), field_readout=_norm(torch, gradient[2:])))
    geometry = []
    for i, left in enumerate(fields):
        for right in fields[i+1:]:
            a = torch.cat([g.detach().double().flatten() for g in gradients[left][:2]])
            b = torch.cat([g.detach().double().flatten() for g in gradients[right][:2]])
            na, nb = float(a.norm()), float(b.norm())
            geometry.append(dict(left=left, right=right, projection_dot=float(a.dot(b)),
                projection_cosine=None if na == 0. or nb == 0. else float(a.dot(b))/(na*nb),
                zero_gradient=na == 0. or nb == 0.))
    state = _state(parameters)
    _deadline(deadline)
    return dict(step=step, fields=result, projection_gradient_geometry=geometry,
        objective=sum(value["weighted_cross_entropy"] for value in result.values()),
        parameters=state, parameters_sha256=digest(state),
        parameter_l2_motion_from_initial={name: _norm(torch, (parameter-original,))
            for name, parameter, original in zip(PARAMETER_NAMES, parameters, initial)},
        metrics_scope="raw_training_readout_only", gradient_scope="separate_coefficient_scaled_full_vocabulary_ce")


def run_source_field_readout_probe(torch, training, initial_head, *, expected_training_sha256,
        expected_initial_head_sha256, mode, learning_rate, max_updates=1000,
        checkpoints=(0, 1, 10, 25, 100, 340, 1000), deadline):
    """Fit a private existing head or its exact object slice, never a decoder.

    ``shared_non_action`` sums three independently mean-reduced full-vocabulary
    CEs, each with coefficient .0625; ``isolated_object`` keeps that same object
    coefficient.  Inputs, projection initialization, Adam settings, and full
    occurrence exposure remain identical.  There is no scheduler or selection.
    Deadline returns only completed private parameter/Adam transactions.  The
    final state is diagnostic and intentionally not an optimizer-resume API.
    """
    started = time.monotonic()
    _require(type(deadline) in (int, float) and abs(deadline) <= 1e15 and math.isfinite(deadline),
             "bounded finite deadline required")
    _require(type(mode) is str and mode in ("shared_non_action", "isolated_object"), "explicit diagnostic mode required")
    _require(type(learning_rate) in (int, float) and learning_rate in (.001, .01), "fixed probe learning rate required")
    _require(type(max_updates) is int and 1 <= max_updates <= 1000, "one to 1000 updates required")
    _require(type(checkpoints) in (tuple, list) and len(checkpoints) <= 16
        and all(type(v) is int and 0 <= v <= max_updates for v in checkpoints)
        and list(checkpoints) == sorted(set(checkpoints)) and 0 in checkpoints and max_updates in checkpoints,
        "ordered unique bounded checkpoints must include initial and final update")
    _validate(training, initial_head, expected_training_sha256, expected_initial_head_sha256)
    _require(torch.is_grad_enabled() and not torch.is_inference_mode_enabled()
             and not torch.is_autocast_enabled("cpu"),
             "ordinary float32 gradient context required; inference, no-grad, and CPU autocast are unsupported")
    # Everything thereafter is private. No class construction consumes RNG.
    rng = torch.get_rng_state().clone()
    parameters, optimizer = None, None
    try:
        fields = FIELDS if mode == "shared_non_action" else ("object",)
        arrays = deepcopy(initial_head["parameters"])
        if mode == "isolated_object":
            arrays["field_readout.weight"] = arrays["field_readout.weight"][64:96]
            arrays["field_readout.bias"] = arrays["field_readout.bias"][64:96]
        parameters = [torch.nn.Parameter(torch.tensor(arrays[name], dtype=torch.float32, device="cpu"))
                      for name in PARAMETER_NAMES]
        initial = [parameter.detach().clone() for parameter in parameters]
        inputs = torch.tensor([row["input"] for row in training["rows"]], dtype=torch.float32, device="cpu")
        labels = torch.tensor([[row["labels"][field] for field in fields] for row in training["rows"]],
                              dtype=torch.long, device="cpu")
        optimizer = torch.optim.AdamW(parameters, lr=learning_rate, betas=(.9, .999), eps=1e-8,
                                     weight_decay=.01, foreach=False)
        history, observations, completed, stopped, rollback = [], [], 0, "updates_completed", False
        try:
            observations.append(_metrics(torch, parameters, inputs, labels, fields, initial, 0, deadline))
            for step in range(1, max_updates+1):
                _deadline(deadline)
                optimizer.zero_grad(set_to_none=True)
                logits = _forward(torch, parameters, inputs, fields)
                losses = [torch.nn.functional.cross_entropy(logits[:, index], labels[:, index])
                          for index in range(len(fields))]
                objective = FIELD_COEFFICIENT * sum(losses)
                _require(bool(torch.isfinite(objective)), "nonfinite probe objective")
                _deadline(deadline)
                objective.backward()
                before_norms = dict(source_projection=_norm(torch, [p.grad for p in parameters[:2]]),
                                    field_readout=_norm(torch, [p.grad for p in parameters[2:]]))
                preclip = torch.nn.utils.clip_grad_norm_(parameters, 1., error_if_nonfinite=True)
                _deadline(deadline)
                # Save both sides of the private transaction before Adam mutates
                # them. A deadline crossing during step cannot commit either.
                prior_parameters = [p.detach().clone() for p in parameters]
                prior_adam = deepcopy(optimizer.state_dict())
                _deadline(deadline)
                optimizer.step()
                try:
                    _require(all(bool(torch.isfinite(p).all()) for p in parameters), "nonfinite updated probe parameters")
                    _deadline(deadline)
                except (TimeoutError, ValueError):
                    with torch.no_grad():
                        for p, previous in zip(parameters, prior_parameters):
                            p.copy_(previous)
                    optimizer.load_state_dict(prior_adam)
                    rollback = True
                    raise
                completed = step
                history.append(dict(step=step, objective=float(objective.detach()),
                    field_cross_entropy={field: float(loss.detach()) for field, loss in zip(fields, losses)},
                    preclip_norm=float(preclip.detach()), clipping_limit=1.,
                    clipping_coefficient=min(1., 1./(float(preclip.detach())+1e-6)),
                    preclip_gradient_norms=before_norms,
                    parameter_l2_step={name: _norm(torch, (p-before,))
                        for name, p, before in zip(PARAMETER_NAMES, parameters, prior_parameters)}))
                if step in checkpoints:
                    observations.append(_metrics(torch, parameters, inputs, labels, fields, initial, step, deadline))
        except TimeoutError:
            stopped = "deadline"
        finally:
            optimizer.zero_grad(set_to_none=True)
        final_state, adam = _state(parameters), _optimizer_state(optimizer, parameters)
        # Hashes are rechecked after all work; original plain objects are never
        # modified and no private tensors alias their storage.
        _bound(training, expected_training_sha256, "training")
        _bound(initial_head, expected_initial_head_sha256, "initial head")
        return dict(schema=SCHEMA, mode=mode, dimension=8, hidden_width=64, vocabulary_size=32,
            fields=list(fields), field_coefficient=FIELD_COEFFICIENT,
            objective="sum_of_independently_mean_reduced_full_vocabulary_field_CE_times_0.0625",
            training_sha256=expected_training_sha256, initial_head_sha256=expected_initial_head_sha256,
            source_order_sha256=digest([row["id"] for row in training["rows"]]),
            source_inputs_sha256=digest([row["input"] for row in training["rows"]]),
            source_literals_sha256=digest([row["source_sha256"] for row in training["rows"]]),
            training_occurrences=len(inputs), training_unique_clauses=len({row["source_sha256"] for row in training["rows"]}),
            row_presentations=completed*len(inputs), scalar_target_presentations=completed*len(inputs)*len(fields),
            source_input_kind="authenticated_already_projected_and_normalized_frozen_clause_vectors",
            architecture="affine_8_to_64_tanh_then_independent_full_32_vocabulary_field_readouts",
            numerical_runtime=dict(torch_version=str(torch.__version__), device="cpu", dtype="float32",
                intraop_threads=torch.get_num_threads()),
            learning_rate=learning_rate, optimizer=dict(name="AdamW", betas=[.9, .999], eps=1e-8,
                weight_decay=.01, foreach=False, max_grad_norm=1., full_batch=True, scheduler=None),
            requested_updates=max_updates, completed_updates=completed, stopped_reason=stopped,
            complete=completed == max_updates and len(observations) == len(checkpoints),
            requested_checkpoints=list(checkpoints), checkpoints=observations, updates=history,
            pending_update_rolled_back=rollback, final_parameters=final_state,
            final_parameters_sha256=digest(final_state), final_adam_state=adam, final_adam_state_sha256=digest(adam),
            elapsed_seconds=time.monotonic()-started, optimizer_resumable=False, validation_access=False,
            source_parser_used=False, formula_decoder_used=False, generated_formula_metrics_computed=False,
            qualification_gates_changed=False, lake_executed=False, admitted=False, qualified=False,
            production_checkpoint=False, convergence_proven=False, training_only=True)
    finally:
        torch.set_rng_state(rng)


__all__ = ["run_source_field_readout_probe", "digest"]
