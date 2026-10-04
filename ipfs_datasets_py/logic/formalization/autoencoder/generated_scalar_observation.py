"""Source-only observations of actual contextual scalar decisions, never a loss.

The recurrent readout already includes source-conditioned recurrent history. Its
logits are not a counterfactual decomposition of the clause residual. The trace
adds no forward pass, model copy, reference input, forced token or qualification.
"""
import math
import time
import threading
from contextlib import contextmanager

from . import generated_field_training as fields
from . import contextual_generated_boundary_training as boundary
from . import decoder_distillation_experiment as core
from . import source_value_decoder_experiment as scalar

SCHEMA = "generated-contextual-scalar-trace/v1"
SCORE_SCHEMA = "generated-contextual-scalar-scores/v1"
FALSE = dict(fields.FALSE)
_require = core._require
_deadline = boundary._check_deadline
_ACTIVE_MODELS = set()
_ACTIVE_LOCK = threading.Lock()


@contextmanager
def _exclusive(model):
    identity = id(model)
    with _ACTIVE_LOCK:
        _require(identity not in _ACTIVE_MODELS, "concurrent observation of the same model is unsupported")
        _ACTIVE_MODELS.add(identity)
    try:
        yield
    finally:
        with _ACTIVE_LOCK:
            _ACTIVE_MODELS.remove(identity)


def _owner(model, codec, torch):
    description, state_size = fields._specification(model, codec)
    output = model.body.body.body.output
    _require(type(output) is torch.nn.Linear and output.out_features == len(codec["target_vocabulary"]),
        "checked actual recurrent output Linear required")
    _require(not output._forward_hooks and not output._forward_pre_hooks and not output._backward_hooks,
        "exclusive unhooked recurrent readout required")
    _require(description.get("guidance") is True, "actual raw source guidance required")
    return description, state_size, output


class _Observer(fields._Collector):
    """Local adapter; inherits the unchanged greedy collector and causal scan."""
    def __init__(self, model, tables, deadline, state_size, output, torch):
        super().__init__(model, tables, deadline, state_size)
        self.torch, self.raw, self.calls = torch, None, 0
        self.handle = output.register_forward_hook(self._capture)

    def _capture(self, module, inputs, output):
        _require(self.raw is None, "one recurrent readout per actual greedy call required")
        self.raw = output.detach()
        self.calls += 1
        # Returning None preserves the exact original tensor and gradient graph.

    def close(self):
        self.handle.remove()
        self.raw = None

    def start(self, projected, *, source_context=None):
        state = super().start(projected, source_context=source_context)
        self.source_mask = source_context["mask"].tolist()
        self.observations = [[] for _ in projected]
        return state

    def next_logits(self, tokens, state):
        _deadline(self.deadline)
        before = state[4].tolist()
        counts = [len(sites) for sites in self.field_sites]
        _require(self.raw is None, "previous recurrent readout was not consumed")
        logits, updated = super().next_logits(tokens, state)
        raw, self.raw = self.raw, None
        _require(raw is not None and tuple(raw.shape) == tuple(logits.shape)
            and core._finite(self.torch, raw), "actual recurrent readout shape/finiteness differs")
        for index, old_count in enumerate(counts):
            for site in self.field_sites[index][old_count:]:
                slot = site["slot"]
                field = scalar.SOURCE_FIELDS.index(site["field"])
                routed = slot < state[5].shape[1]
                available = routed and bool(self.source_mask[index][slot])
                source = state[5][index, slot, field].detach() if routed else raw[index, 0].new_zeros(raw.shape[-1])
                if not available:
                    _require(bool((source == 0).all()), "unavailable source slot supplied nonzero guidance")
                combined = logits[index, 0].detach()
                _require(self.torch.equal(raw[index, 0]+source, combined),
                    "actual scalar recurrent/source additions differ from combined logits")
                self.observations[index].append(dict(position=site["position"], slot=slot, field=site["field"],
                    actual_next_token_id=site["actual_next_token_id"], raw_recurrent_logits=raw[index, 0].tolist(),
                    applied_source_logits=source.tolist(), combined_logits=site["collection_logits"],
                    source_slot_available=available, source_guidance_active=routed,
                    grammar_before=before[index], grammar_after=updated[4][index].tolist(),
                    decomposition_exact=True))
        return logits, updated


def collect_source_scalar_trace(model, source_rows, *, codec, input_transform, source_contexts,
        max_target_tokens=512, batch_size=8, deadline, max_memory_bytes=134217728):
    """Source-only observation; caller must exclude other use of this model.

    Parallel observations of distinct models are allowed. Reentry on one model
    is refused; external training/generation of that same instance is outside
    this private observation contract. Existing readout hooks are refused.
    """
    with _exclusive(model):
        return _collect_source_scalar_trace(model, source_rows, codec=codec,
            input_transform=input_transform, source_contexts=source_contexts,
            max_target_tokens=max_target_tokens, batch_size=batch_size, deadline=deadline,
            max_memory_bytes=max_memory_bytes)


def _collect_source_scalar_trace(model, source_rows, *, codec, input_transform, source_contexts,
        max_target_tokens, batch_size, deadline, max_memory_bytes):
    """Observe the same one-token greedy calls without a model copy or labels.

    A hook sees the actual pre-addition recurrent output. Available source-slot
    values come from the existing state cache; no source head is evaluated again.
    The memory bound covers trace retention, not existing model/import/RSS costs.
    """
    started = time.monotonic(); _deadline(deadline)
    _require(type(max_target_tokens) is int and 4 <= max_target_tokens <= 512, "fixed512 output ceiling required")
    _require(type(batch_size) is int and 1 <= batch_size <= 128, "bounded generation batch required")
    _require(type(max_memory_bytes) is int and 1 <= max_memory_bytes <= 1073741824, "bounded trace memory budget required")
    torch = core._torch(); core._model(model, torch)
    description, state_size, output = _owner(model, codec, torch)
    boundary._sources(source_rows, model.dimension, True, source_contexts)
    boundary.legacy._transform(input_transform, model.dimension)
    size = len(codec["target_vocabulary"])
    _require(4 <= size <= 4096, "bounded full vocabulary required")
    estimate = len(source_rows)*(128*size*3*40+max_target_tokens*64+32768)
    _require(estimate <= max_memory_bytes, "trace memory estimate exceeds bound")
    tables = boundary.cardinality._tables(codec, size, torch)
    snapshot = boundary._snapshot(model, torch)
    predictions, records, steps, calls = [], [], 0, 0
    try:
        model.eval()
        with torch.no_grad():
            for offset in range(0, len(source_rows), batch_size):
                _deadline(deadline)
                part = source_rows[offset:offset+batch_size]
                observer = _Observer(model, tables, deadline, state_size, output, torch)
                try:
                    generated = core._greedy(torch, observer, boundary.legacy._data(torch, part, input_transform),
                        max_target_tokens, size, deadline,
                        **core._source_context_kwargs(torch, part, source_contexts, input_transform))
                    if generated is None:
                        raise TimeoutError("scalar observation deadline exceeded")
                    steps += observer.steps; calls += observer.calls
                    for index, (row, tokens, status) in enumerate(zip(part, generated[1], generated[2])):
                        prefix = observer.prefixes[index]
                        _require(prefix == [1]+tokens[:len(prefix)-1], "actual scalar prefix/output binding differs")
                        sites = observer.observations[index]
                        _require(len(sites) <= 128, "bounded scalar-site inventory required")
                        segments = source_contexts[row["id"]]["segments"]
                        for site in sites:
                            site["source_clause_sha256"] = segments[site["slot"]]["source_sha256"] if site["source_slot_available"] else None
                        predictions.append(dict(id=row["id"], token_ids=tokens, generation_status=status, eos_reached=status=="eos"))
                        records.append(dict(id=row["id"], consumed_prefix=prefix, scalar_sites=sites,
                            first_invalid_prefix_position=observer.invalid[index], batch_offset=offset,
                            input_sha256=core.digest(row["input"]), source_context_sha256=core.digest(source_contexts[row["id"]]),
                            source_text_sha256=source_contexts[row["id"]]["source_sha256"]))
                finally:
                    observer.close()
    finally:
        boundary._preserved(model, torch, snapshot)
    _deadline(deadline)
    _require(calls == steps, "exactly one recurrent readout per actual greedy call required")
    result = dict(schema=SCHEMA, complete=True, model_tensor_sha256=snapshot[0], model_schema=description["schema"],
        dimension=model.dimension, codec_sha256=core.digest(codec), input_transform_sha256=core.digest(input_transform),
        source_rows_sha256=core.digest(source_rows), source_contexts_sha256=core.digest(source_contexts),
        predictions=predictions, rows=records, sample_count=len(source_rows), scalar_site_count=sum(len(row["scalar_sites"]) for row in records),
        batch_size=batch_size, max_target_tokens=max_target_tokens, vocabulary_size=size,
        greedy_batch_steps=steps, recurrent_readout_calls=calls, generation_temperature=0,
        full_vocabulary_retained=True, decomposition_exact=True, source_only=True, reference_count_access=False,
        reference_prefix_access=False, reference_documents_passed_to_model=False, inventory_access=False,
        source_context_target_access=False, syntax_mask=False, forced_closure=False, source_head_extra_evaluations=0,
        caller_exclusive_model_access_required=True,
        extra_model_passes=0, model_copied=False, caller_state_preserved=True, hooks_removed=True,
        source_logits_scope="actual_cached_masked_source_logits; equal_to_raw_head_only_at_available_slots",
        recurrent_logits_scope="actual_readout_before_scalar_addition; includes_source_conditioned_recurrent_history",
        recurrent_clause_effect_causally_isolated=False, complete_rollout_before_reference_scoring=True,
        memory_estimate_bytes=estimate, memory_estimate_excludes_model_import_allocator_rss=True,
        elapsed_seconds=time.monotonic()-started, deadline_cooperative=True, optimizer_steps=0,
        **FALSE)
    result["trace_sha256"] = core.digest(result)
    _deadline(deadline)
    return result


def _validate_trace(trace, source_rows, codec, input_transform, source_contexts, deadline):
    """Revalidate actual lexical sites and float32 additions, without a model."""
    _deadline(deadline)
    _require(type(trace) is dict and trace.get("schema")==SCHEMA and trace.get("complete") is True
        and trace.get("trace_sha256")==core.digest({k:v for k,v in trace.items() if k!="trace_sha256"}),
        "complete authenticated scalar trace required")
    _require(trace.get("model_schema") in ("clause-source-decoder-development/v1",
        "action-factorized-clause-source-decoder-development/v1", "ordered-clause-recurrent-source-decoder-development/v1"),
        "checked contextual trace architecture required")
    digest=trace.get("model_tensor_sha256")
    _require(type(digest) is str and len(digest)==64 and all(c in "0123456789abcdef" for c in digest),
        "exact model tensor digest required")
    dimension = trace["dimension"]
    _require(type(dimension) is int and dimension in (8,384,768), "supported trace dimension required")
    boundary._sources(source_rows, dimension, True, source_contexts)
    boundary.legacy._transform(input_transform, dimension)
    _require(trace["source_rows_sha256"]==core.digest(source_rows) and trace["source_contexts_sha256"]==core.digest(source_contexts)
        and trace["codec_sha256"]==core.digest(codec) and trace["input_transform_sha256"]==core.digest(input_transform),
        "stale trace source/codec/context/transform")
    for key in ("source_only","full_vocabulary_retained","complete_rollout_before_reference_scoring","decomposition_exact","hooks_removed","caller_state_preserved"):
        _require(trace.get(key) is True, "trace policy differs: "+key)
    for key in ("reference_count_access","reference_prefix_access","reference_documents_passed_to_model","inventory_access","source_context_target_access","syntax_mask","forced_closure","model_copied",*FALSE):
        _require(trace.get(key) is False, "trace authority or reference policy differs: "+key)
    _require(type(trace["batch_size"]) is int and 1<=trace["batch_size"]<=128
        and type(trace["max_target_tokens"]) is int and 4<=trace["max_target_tokens"]<=512
        and trace["generation_temperature"]==0, "trace generation bounds differ")
    _require([row["id"] for row in trace["rows"]]==[row["id"] for row in source_rows]
        ==[row["id"] for row in trace["predictions"]], "complete ordered trace rows required")
    torch=core._torch();size=len(codec["target_vocabulary"])
    _require(trace["vocabulary_size"]==size and 4<=size<=4096, "trace full vocabulary differs")
    tables=boundary.cardinality._tables(codec,size,torch)
    total=0; batch_steps={}
    for index,(record,prediction,source) in enumerate(zip(trace["rows"],trace["predictions"],source_rows)):
        _deadline(deadline)
        _require(type(record["batch_offset"]) is int and record["batch_offset"]==index//trace["batch_size"]*trace["batch_size"], "trace original batch differs")
        context=source_contexts[source["id"]]
        _require(record["input_sha256"]==core.digest(source["input"]) and record["source_context_sha256"]==core.digest(context)
            and record["source_text_sha256"]==context["source_sha256"], "trace row provenance differs")
        prefix,tokens,status=record["consumed_prefix"],prediction["token_ids"],prediction["generation_status"]
        _require(type(prefix) is list and 1<=len(prefix)<trace["max_target_tokens"] and prefix[0]==1
            and all(type(t) is int and 0<=t<size for t in prefix)
            and type(tokens) is list and all(type(t) is int and 3<=t<size for t in tokens)
            and prefix==[1]+tokens[:len(prefix)-1], "trace consumed prefix differs")
        _require(status in ("eos","invalid_special_token","output_limit") and prediction["eos_reached"] is (status=="eos")
            and len(tokens)==len(prefix)-(status!="output_limit")
            and (status!="output_limit" or len(prefix)==trace["max_target_tokens"]-1), "trace completed generation differs")
        batch_steps[record["batch_offset"]]=max(batch_steps.get(record["batch_offset"],0),len(prefix))
        grammar=[[0]*6];expected=[];invalid=None
        for position,token in enumerate(prefix):
            if position%32==0:_deadline(deadline)
            updated,sites=scalar._scan_value_prefix([[token]],grammar,tables,32)
            expected.extend((position,slot,scalar.SOURCE_FIELDS[field],grammar[0],updated[0]) for _,_,slot,field in sites)
            if updated[0][0]==boundary.cardinality._INVALID and invalid is None:invalid=position
            grammar=updated
        _require(record["first_invalid_prefix_position"]==invalid and len(record["scalar_sites"])==len(expected)<=128, "trace actual scalar-site inventory differs")
        for site,(position,slot,field,before,after) in zip(record["scalar_sites"],expected):
            _require(all(type(site[key]) is list and len(site[key])==6 and all(type(value) is int for value in site[key])
                for key in ("grammar_before","grammar_after")), "exact integer causal grammar required")
            _require(type(site["position"]) is int and site["position"]==position and type(site["slot"]) is int and site["slot"]==slot
                and site["field"]==field and site["grammar_before"]==before and site["grammar_after"]==after, "trace actual scalar route differs")
            available=slot<len(context["segments"])
            _require(site["source_slot_available"] is available and site["source_guidance_active"] is (slot<8)
                and site["source_clause_sha256"]==(context["segments"][slot]["source_sha256"] if available else None), "trace source availability differs")
            for key in ("raw_recurrent_logits","applied_source_logits","combined_logits"):
                values=site[key]
                _require(type(values) is list and len(values)==size and all(type(v) in (float,int) and math.isfinite(v) for v in values), "bounded finite full-vocabulary observation required")
            raw=torch.tensor(site["raw_recurrent_logits"],dtype=torch.float32)
            applied=torch.tensor(site["applied_source_logits"],dtype=torch.float32)
            combined=torch.tensor(site["combined_logits"],dtype=torch.float32)
            _require(all(core._finite(torch,value) for value in (raw,applied,combined))
                and site["decomposition_exact"] is True and torch.equal(raw+applied,combined)
                and (available or bool((applied==0).all())), "trace scalar decomposition differs")
            chosen=site["actual_next_token_id"]
            _require(type(chosen) is int and chosen==max(range(size),key=site["combined_logits"].__getitem__), "trace actual full-vocabulary argmax differs")
            _require(chosen==tokens[position] if position<len(tokens) else chosen==2 if status=="eos" else chosen in (0,1) if status=="invalid_special_token" else False,
                "trace scalar argmax/output differs")
        total+=len(expected)
    for key in ("sample_count","scalar_site_count","greedy_batch_steps","recurrent_readout_calls",
            "extra_model_passes","source_head_extra_evaluations","optimizer_steps","generation_temperature","vocabulary_size"):
        _require(type(trace[key]) is int, "exact integer trace accounting required: "+key)
    _require(trace["greedy_batch_steps"]==sum(batch_steps.values()), "actual greedy step accounting differs")
    _require(trace["sample_count"]==len(source_rows) and trace["scalar_site_count"]==total
        and trace["greedy_batch_steps"]==trace["recurrent_readout_calls"]
        and trace["extra_model_passes"]==trace["source_head_extra_evaluations"]==trace["optimizer_steps"]==0, "trace call/count accounting differs")


def _metrics(logits, target, emitted):
    maximum=max(logits)
    return dict(argmax_token_id=max(range(len(logits)),key=logits.__getitem__),
        target_minus_best_other=logits[target]-max(value for index,value in enumerate(logits) if index!=target),
        target_minus_emitted=logits[target]-logits[emitted],
        full_vocabulary_cross_entropy=maximum+math.log(sum(math.exp(value-maximum) for value in logits))-logits[target])


def score_scalar_trace(trace, rows, references, *, split, codec, input_transform, source_contexts, validate_rule, deadline):
    """Authenticate labels only after rollout; this returns no training loss.

    ``split`` labels the caller-declared partition, not independent provenance.
    The references, codec and source offsets must agree exactly. Positional
    source/rule alignment remains an explicit fixture contract, not inferred law.
    """
    _deadline(deadline)
    _require(type(split) is str and split in ("training","exposed_development"), "explicit observed split required")
    _require(type(rows) is list and all(type(row) is dict and set(row)=={"id","input","source_text","target_ids"} for row in rows), "closed reference-evaluation rows required")
    sources=[{key:row[key] for key in ("id","input","source_text")} for row in rows]
    _validate_trace(trace,sources,codec,input_transform,source_contexts,deadline)
    _deadline(deadline)
    labels=scalar.reference_source_values(rows,references,codec,validate_rule=validate_rule)
    _deadline(deadline)
    literals={};events=[];unscored=[];visited=set()
    per_field={field:dict(scored=0,source_correct=0,recurrent_correct=0,combined_correct=0,source_correct_combined_wrong=0) for field in fields.FIELDS}
    for row,record in zip(rows,trace["rows"]):
        _deadline(deadline)
        segments=source_contexts[row["id"]]["segments"];targets=labels[row["id"]]
        _require(len(segments)==sum(values[0]>=0 for values in targets), "explicit one-source-clause per reference rule required")
        for slot,segment in enumerate(segments):
            values=targets[slot];sha=segment["source_sha256"]
            _require(sha not in literals or literals[sha]==values, "ambiguous literal source has conflicting reference labels")
            literals[sha]=values
        for site in record["scalar_sites"]:
            slot,field=site["slot"],site["field"]
            if not site["source_slot_available"] or slot>=len(segments):
                unscored.append(dict(id=row["id"],position=site["position"],slot=slot,field=field,reason="source_slot_unavailable"));continue
            target=targets[slot][fields.FIELDS.index(field)];emitted=site["actual_next_token_id"]
            measures={name:_metrics(site[key],target,emitted) for name,key in
                (("source","applied_source_logits"),("recurrent","raw_recurrent_logits"),("combined","combined_logits"))}
            aggregate=per_field[field];aggregate["scored"]+=1
            for name in ("source","recurrent","combined"):aggregate[name+"_correct"]+=measures[name]["argmax_token_id"]==target
            aggregate["source_correct_combined_wrong"]+=measures["source"]["argmax_token_id"]==target and emitted!=target
            visited.add((row["id"],slot,field))
            events.append(dict(id=row["id"],position=site["position"],slot=slot,field=field,target_token_id=target,
                actual_next_token_id=emitted,source_clause_sha256=site["source_clause_sha256"],
                prefix_sha256=core.digest(record["consumed_prefix"][:site["position"]+1]),**measures))
    unvisited=[dict(id=row["id"],slot=slot,field=field,reason="reference_site_not_visited") for row in rows
        for slot in range(len(source_contexts[row["id"]]["segments"])) for field in fields.FIELDS
        if (row["id"],slot,field) not in visited]
    _deadline(deadline)
    result=dict(schema=SCORE_SCHEMA,complete=True,split=split,split_is_caller_declared=True,
        trace_sha256=trace["trace_sha256"],model_tensor_sha256=trace["model_tensor_sha256"],
        rows_sha256=core.digest(rows),references_sha256=core.digest(references),codec_sha256=core.digest(codec),
        source_contexts_sha256=core.digest(source_contexts),events=events,per_field=per_field,
        scored_sites=len(events),unscored_sites=unscored,unvisited_reference_sites=unvisited,
        reference_labels_used_only_after_rollout=True,training_loss_returned=False,optimizer_steps=0,
        models_executed=False,source_alignment_inferred=False,statutory_alignment_verified=False,
        raw_source_scope="cached source logits equal raw head at available source slots",
        recurrent_clause_effect_causally_isolated=False,**FALSE)
    result["score_sha256"]=core.digest(result)
    _deadline(deadline)
    return result
