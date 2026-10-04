"""Observe actual free-generation rule boundaries without changing the decoder.

Only source vectors enter this API. Targets, expected counts and desired prefixes
are excluded. A hook on a private model's recurrent output layer observes the
same forward call used by the unchanged greedy loop; it returns no replacement.
This is a diagnostic, not a parser, proof, training objective or qualification.
"""
from copy import deepcopy
import hashlib
import json
import math
import random
import time

from . import decoder_cardinality_experiment as cardinality
from . import decoder_distillation_experiment as core
from . import projected_source_decoder_experiment as projected_values
from . import source_value_decoder_experiment as source_values

SCHEMA = "causal-source-boundary-trace/v1"
FALSE = dict(core.FALSE, native_family_validation_performed=False, lake_executed=False,
    convergence_proven=False, fresh_holdout=False, checkpoint_promoted=False)
_require = core._require


def _owner(model, codec, torch):
    description = model.describe()
    schema = description.get("schema")
    if schema in ("shared-slot-source-decoder-development/v1", "mean-centered-source-decoder-development/v1"):
        _require(description.get("scalar_mode") == "raw", "only authenticated raw scalar guidance is traced")
        owner = model.body
    else:
        _require(schema == projected_values.SCHEMA, "projected/shared/raw source decoder required")
        owner = model
    spec = owner.describe()
    _require(spec.get("schema") == projected_values.SCHEMA and spec.get("codec_sha256") == core.digest(codec)
        and type(spec.get("guide_boundary")) is bool and type(spec.get("guidance")) is bool,
        "matching projected source architecture and codec required")
    _require(all(spec.get(key) is False for key in ("syntax_forced", "closure_forced", "source_context_cached_on_module")),
        "unaltered causal generation policy required")
    output = owner.body.body.output
    _require(type(output) is torch.nn.Linear and output.out_features == len(codec["target_vocabulary"]),
        "actual inherited recurrent output Linear required")
    return owner, output, spec


def _gradient_digest(model):
    result = hashlib.sha256()
    for name, parameter in model.named_parameters():
        value = parameter.grad
        result.update(core._raw([name, None if value is None else [str(value.dtype), list(value.shape)]]))
        if value is not None:
            result.update(value.detach().cpu().contiguous().numpy().tobytes())
    return result.hexdigest()


def _syntax_summary(tokens, codec):
    # Post-generation syntax only: no source text, expected document or validator.
    try:
        document = json.loads("".join(codec["target_vocabulary"][token] for token in tokens))
    except (ValueError, TypeError):
        document = None
    rules = document.get("rules") if type(document) is dict and set(document) == {"rules"} else None
    if type(rules) is not list:
        return dict(json_parseable=document is not None, syntactic_rule_count=None,
            syntactic_duplicate_rule_count=None, diagnostic_json_only=True)
    counts = {}
    for rule in rules:
        key = core.digest(rule); counts[key] = counts.get(key, 0)+1
    return dict(json_parseable=True, syntactic_rule_count=len(rules),
        syntactic_duplicate_rule_count=sum(value-1 for value in counts.values()), diagnostic_json_only=True)


class _Observer:
    """Protocol adapter; real logits/state are returned untouched to core._greedy."""
    def __init__(self, model, owner, output, codec, torch, deadline):
        self.model, self.owner, self.torch, self.deadline = model, owner, torch, deadline
        self.codec = codec; self.spec = owner.describe()
        self.tables = cardinality._tables(codec, len(codec["target_vocabulary"]), torch)
        self.raw = None; self.hook_calls = 0; self.rows = []
        self.handle = output.register_forward_hook(self._capture)

    def _capture(self, module, inputs, output):
        _require(self.raw is None, "one recurrent readout per actual greedy step required")
        self.raw = output.detach().clone(); self.hook_calls += 1
        # No return value: never replace the actual recurrent readout.

    def close(self):
        self.handle.remove()

    def project(self, data):
        return self.model.project(data)

    def start(self, projected):
        state = self.model.start(projected)
        _require(type(state) is tuple and len(state) == 6, "explicit source/count/grammar state required")
        self.active = [True]*len(projected); self.previous_chosen = None
        self.prefixes = [[] for _ in projected]; self.rows = []
        prior = self.owner.count_prior_logits.detach().tolist()
        probabilities = self.torch.softmax(state[3], dim=-1).tolist()
        for logits, probability in zip(state[3].tolist(), probabilities):
            self.rows.append(dict(count_logits=logits, count_probabilities=probability,
                predicted_count=1+max(range(len(logits)), key=logits.__getitem__),
                frozen_prior_logits=prior, boundaries=[], scalar_sites_observed=0,
                first_invalid_prefix_position=None, last_consumed_grammar_state=None))
        return state

    def next_logits(self, tokens, state):
        torch = self.torch
        _require(time.monotonic() < self.deadline, "boundary trace deadline exceeded")
        _require(tuple(tokens.shape) == (len(self.rows), 1), "incremental one-token greedy path required")
        if self.previous_chosen is not None:
            _require(tokens[:, 0].tolist() == self.previous_chosen, "observed argmax differs from actual next consumed tokens")
        initial_grammar = state[4].tolist(); token_rows = tokens.tolist()
        final_grammar, boundaries = cardinality._scan_prefix(token_rows, initial_grammar, self.tables)
        scalar_final, sites = source_values._scan_value_prefix(token_rows, initial_grammar, self.tables, source_values.MAX_RULES)
        _require(final_grammar == scalar_final, "diagnostic causal recognizers disagree")
        self.raw = None
        logits, updated = self.model.next_logits(tokens, state)
        raw = self.raw; self.raw = None
        _require(raw is not None and tuple(raw.shape) == tuple(logits.shape)
            and final_grammar == updated[4].tolist(), "actual recurrent/grammar observation differs")
        # Reproduce only additions for an observation-integrity assertion. The
        # reconstructed tensor never goes back to generation or recurrent state.
        expected = raw; corrections = {}; scalar_by_row = {}
        if self.spec["guide_boundary"] and boundaries:
            locations = torch.tensor(boundaries, dtype=torch.long)
            batch, offset, completed = locations.unbind(1)
            delta = projected_values.prior_centered_boundary_log_odds(state[3][batch], completed, self.owner.count_prior_logits)
            adjustment = raw.new_zeros(len(tokens)).scatter(0, batch, delta)
            closing = raw.new_zeros(raw.shape[-1]); closing[self.tables[0]["]"]] = 1.
            expected = expected + adjustment.reshape(len(tokens), 1, 1)*closing
            corrections = {index:float(value) for index,value in zip(batch.tolist(), delta.tolist())}
        if self.spec["guidance"] and sites:
            locations = torch.tensor(sites, dtype=torch.long)
            batch, offset, slot, field = locations.unbind(1)
            residual = raw.new_zeros(len(tokens), raw.shape[-1]).index_add(0, batch, state[5][batch,slot,field])
            expected = expected + residual.reshape_as(raw)
            scalar_by_row = {b:dict(slot=s, field=source_values.SOURCE_FIELDS[f], logits=state[5][b,s,f].tolist())
                for b,_,s,f in sites}
        _require(torch.equal(expected, logits), "captured recurrent/count/scalar additions differ from actual logits")
        chosen = logits[:, -1].argmax(-1).tolist()
        stop, continuing = self.tables[0]["]"], self.tables[0][","]
        for index, (token, selected) in enumerate(zip(tokens[:, 0].tolist(), chosen)):
            if not self.active[index]: continue
            self.prefixes[index].append(token); record = self.rows[index]; grammar = final_grammar[index]
            record["last_consumed_grammar_state"] = grammar
            record["scalar_sites_observed"] += int(index in scalar_by_row)
            if grammar[0] == cardinality._INVALID and record["first_invalid_prefix_position"] is None:
                record["first_invalid_prefix_position"] = len(self.prefixes[index])-1
            # Include causal boundaries >=32 as inactive observations; the
            # inherited policy has no count correction at those counts.
            is_boundary = initial_grammar[index][0] == 9 and grammar[0] == 13 and grammar[3] == initial_grammar[index][3]+1
            if is_boundary:
                recurrent = raw[index,0].tolist(); final = logits[index,0].tolist()
                overlap = scalar_by_row.get(index)
                record["boundaries"].append(dict(consumed_prefix_length=len(self.prefixes[index]),
                    consumed_prefix_sha256=core.digest(self.prefixes[index]), completed_rules=grammar[3],
                    grammar_before=initial_grammar[index], grammar_after=grammar,
                    consumed_token_id=token, stop_token_id=stop, continue_token_id=continuing,
                    recurrent_logits=recurrent, final_logits=final,
                    recurrent_stop_minus_continue=recurrent[stop]-recurrent[continuing],
                    final_stop_minus_continue=final[stop]-final[continuing],
                    recurrent_stop_minus_best_other=recurrent[stop]-max(v for i,v in enumerate(recurrent) if i!=stop),
                    final_stop_minus_best_other=final[stop]-max(v for i,v in enumerate(final) if i!=stop),
                    recurrent_argmax_token_id=max(range(len(recurrent)), key=recurrent.__getitem__),
                    local_argmax_changed=max(range(len(recurrent)), key=recurrent.__getitem__)!=selected,
                    count_correction=corrections.get(index,0.), count_correction_active=index in corrections,
                    scalar_guidance_overlap=overlap, scalar_guidance_active=overlap is not None,
                    final_argmax_token_id=selected, actual_next_token_id=selected,
                    action="stop" if selected==stop else "continue" if selected==continuing else "other"))
            if selected in (0,1,2): self.active[index] = False
        self.previous_chosen = chosen
        return logits, updated


def trace_boundary_generation(model, source_rows, *, codec, input_transform,
                              max_target_tokens=512, batch_size=8, max_seconds=120,
                              max_memory_bytes=536870912):
    """Trace source-only greedy generation; caller compares archived outputs.

Rows have exactly ``id,input``. Keep the archived row order/batch size to make
bit-exact replay meaningful. One cooperative deadline covers copy, generation,
diagnostics and caller-integrity checks. No reference or prefix input is accepted.
"""
    started = time.monotonic()
    _require(type(max_seconds) in (int,float) and math.isfinite(max_seconds) and 0 < max_seconds <= 600,
        "bounded positive trace deadline required")
    deadline = started+max_seconds
    _require(type(max_target_tokens) is int and 4 <= max_target_tokens <= 512,
        "trace output cap must not increase the fixed512-token limit")
    _require(type(batch_size) is int and 1 <= batch_size <= 128, "bounded trace batch size required")
    _require(type(max_memory_bytes) is int and 1048576 <= max_memory_bytes <= 1073741824,
        "bounded trace memory allowance required")
    torch = core._torch(); core._model(model, torch)
    _require(type(source_rows) is list and 1 <= len(source_rows) <= 128, "bounded source-only rows required")
    ids = set()
    for row in source_rows:
        _require(type(row) is dict and set(row) == {"id", "input"}, "closed source-only row; no targets, counts or prefixes")
        _require(type(row["id"]) is str and 0 < len(row["id"]) <= 512 and row["id"] not in ids, "unique bounded source identity required")
        ids.add(row["id"]); core._vector(row["input"], model.dimension)
    _require(type(input_transform) is dict and {"mean", "scale"} <= set(input_transform)
        and set(input_transform) <= {"mean", "scale", "mode", "origin"}
        and type(input_transform.get("scale")) in (int,float)
        and math.isfinite(input_transform["scale"]) and input_transform["scale"]>0, "finite input transform required")
    core._vector(input_transform.get("mean"), model.dimension)
    _owner(model, codec, torch); size = len(codec["target_vocabulary"])
    parameter_bytes = sum(t.numel()*t.element_size() for t in model.state_dict().values())
    # Includes a conservative full-vocabulary boundary trace allowance; Python
    # allocator/RSS still needs the caller's resource guardian.
    estimate = 4*parameter_bytes + len(source_rows)*max_target_tokens*size*24 + 4096*len(source_rows)
    _require(estimate <= max_memory_bytes, "trace memory estimate exceeds bound")
    before = core.tensor_digest(model); gradients = _gradient_digest(model)
    modes = {name:module.training for name,module in model.named_modules()}
    rng = torch.get_rng_state().clone(); python_rng = random.getstate()
    private = deepcopy(model).eval(); owner, output, _ = _owner(private, codec, torch)
    observer = _Observer(private, owner, output, codec, torch, deadline)
    predictions, records = [], []
    try:
        with torch.inference_mode():
            for offset in range(0,len(source_rows),batch_size):
                _require(time.monotonic()<deadline, "boundary trace deadline exceeded")
                part = source_rows[offset:offset+batch_size]
                values = torch.tensor([row["input"] for row in part], dtype=torch.float32)
                data = (values-torch.tensor(input_transform["mean"],dtype=torch.float32))/input_transform["scale"]
                generated = core._greedy(torch, observer, data, max_target_tokens, size, deadline)
                _require(generated is not None, "boundary trace deadline exceeded")
                for row, tokens, status, record in zip(part,generated[1],generated[2],observer.rows):
                    predictions.append(dict(id=row["id"], token_ids=tokens, generation_status=status, eos_reached=status=="eos"))
                    for event in record["boundaries"]:
                        length = event["consumed_prefix_length"]
                        consumed = [1]+tokens[:length-1]
                        following = tokens[length-1] if length-1<len(tokens) else (2 if status=="eos" else event["actual_next_token_id"])
                        _require(core.digest(consumed)==event["consumed_prefix_sha256"]
                            and following==event["actual_next_token_id"], "boundary event does not match actual greedy output")
                    records.append(dict(id=row["id"], input_sha256=core.digest(row["input"]),
                        generation_status=status, generated_content_tokens=len(tokens), eos_reached=status=="eos",
                        **record, **_syntax_summary(tokens,codec)))
    finally:
        observer.close()
        _require(core.tensor_digest(model)==before and core.tensor_digest(private)==before,
            "boundary observation changed model tensors")
        _require(_gradient_digest(model)==gradients and {name:module.training for name,module in model.named_modules()}==modes,
            "boundary observation changed caller gradients or modes")
        _require(torch.equal(torch.get_rng_state(),rng) and random.getstate()==python_rng,
            "boundary observation changed ambient RNG")
    _require(time.monotonic()<deadline, "boundary trace deadline exceeded")
    return dict(schema=SCHEMA, complete=True, model_tensor_sha256=before, codec_sha256=core.digest(codec),
        source_rows_sha256=core.digest(source_rows), input_transform_sha256=core.digest(input_transform),
        sample_count=len(source_rows), predictions=predictions, rows=records,
        boundary_event_count=sum(len(row["boundaries"]) for row in records), recurrent_hook_calls=observer.hook_calls,
        batch_size=batch_size, max_target_tokens=max_target_tokens, temperature=0,
        elapsed_seconds=time.monotonic()-started, deadline_cooperative=True, memory_estimate_bytes=estimate,
        memory_estimate_excludes_python_allocator_rss=True, unchanged_core_greedy_used=True,
        raw_recurrent_capture="actual_inherited_output_Linear_forward_hook_on_private_copy",
        logits_addition_replay_exact=True, actual_prefix_argmax_binding=True,
        archived_prediction_parity_checked_by_caller=False, caller_tensors_modes_gradients_rng_preserved=True,
        reference_documents_passed_to_model=False, target_tokens_passed_to_model=False,
        reference_count_passed_to_model=False, forced_closure=False, syntax_mask=False,
        optimizer_steps=0, weight_selection_performed=False, **FALSE)
