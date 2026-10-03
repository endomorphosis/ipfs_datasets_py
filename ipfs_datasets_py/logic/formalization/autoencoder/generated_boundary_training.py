"""Training-only full-vocabulary loss on the student's own generated boundaries.

Collection accepts only source vectors and uses the unchanged greedy decoder.
First/last boundary selection is independent of reference counts. Only the loss
receives authenticated training counts: continue before that count, close at or
after it. This cardinality supervision cannot establish semantic reconstruction.
"""
import math
import random
import time

from . import decoder_cardinality_experiment as cardinality
from . import decoder_distillation_experiment as core
from . import shared_slot_source_decoder_experiment as shared

SCHEMA = "generated-source-boundary-collection/v1"
LOSS_SCHEMA = "generated-source-boundary-loss/v1"
POLICY = "first_and_last_distinct_actual_boundaries"
FALSE = dict(core.FALSE, native_family_validation_performed=False, lake_executed=False,
    checkpoint_promoted=False, convergence_proven=False, fresh_holdout=False)
_require = core._require


def _check_deadline(deadline):
    _require(type(deadline) in (int,float) and math.isfinite(deadline), "finite absolute boundary deadline required")
    if time.monotonic() >= deadline:
        raise TimeoutError("generated boundary deadline exceeded")


def _sources(rows, dimension):
    _require(type(rows) is list and 1 <= len(rows) <= 128, "bounded source-only collection required")
    identities = set()
    for row in rows:
        _require(type(row) is dict and set(row)=={"id","input"}, "closed source-only rows exclude targets, counts and prefixes")
        _require(type(row["id"]) is str and 0<len(row["id"])<=512 and row["id"] not in identities,
            "unique bounded source identity required")
        identities.add(row["id"]); core._vector(row["input"],dimension)


def _transform(transform, dimension):
    _require(type(transform) is dict and {"mean","scale"} <= set(transform)
        and set(transform) <= {"mean","scale","mode","origin"}
        and type(transform["scale"]) in (int,float) and math.isfinite(transform["scale"])
        and transform["scale"]>0, "source input transform required")
    core._vector(transform["mean"],dimension)


def _data(torch, rows, transform):
    return (torch.tensor([row["input"] for row in rows],dtype=torch.float32)
        -torch.tensor(transform["mean"],dtype=torch.float32))/transform["scale"]


def _select(sites):
    return sites if len(sites)<=1 else [sites[0],sites[-1]]


def _state_versions(model):
    # No parameter/gradient copying. Standard optimizer writes increment these
    # versions; the full tensor digest separately authenticates weight bytes.
    return [(name,parameter._version,None if parameter.grad is None else
        (id(parameter.grad),parameter.grad._version)) for name,parameter in model.named_parameters()]


class _Collector:
    def __init__(self, model, tables, deadline):
        self.model, self.tables, self.deadline = model,tables,deadline

    def project(self, data): return self.model.project(data)

    def start(self, projected):
        state=self.model.start(projected)
        _require(type(state) is tuple and len(state)==6, "shared causal state required")
        self.active=[True]*len(projected);self.prefixes=[[] for _ in projected]
        self.sites=[[] for _ in projected];self.invalid=[None]*len(projected)
        self.previous=None;self.steps=0
        return state

    def next_logits(self, tokens, state):
        _check_deadline(self.deadline)
        _require(tuple(tokens.shape)==(len(self.active),1), "actual incremental greedy path required")
        if self.previous is not None:
            _require(tokens[:,0].tolist()==self.previous,"collection differs from actual previous argmax")
        before=state[4].tolist()
        final,_=cardinality._scan_prefix(tokens.tolist(),before,self.tables)
        logits,updated=self.model.next_logits(tokens,state)
        _require(final==updated[4].tolist(),"collection causal grammar differs")
        chosen=logits[:,-1].argmax(-1).tolist()
        for index,token in enumerate(tokens[:,0].tolist()):
            if not self.active[index]:continue
            self.prefixes[index].append(token)
            grammar=final[index]
            if grammar[0]==cardinality._INVALID and self.invalid[index] is None:
                self.invalid[index]=len(self.prefixes[index])-1
            if before[index][0]==9 and grammar[0]==13 and grammar[3]==before[index][3]+1:
                self.sites[index].append(dict(position=len(self.prefixes[index])-1,completed_rules=grammar[3]))
            if chosen[index] in (0,1,2):self.active[index]=False
        self.previous=chosen;self.steps+=1
        return logits,updated


def collect_source_boundary_prefixes(model, source_rows, *, codec, input_transform,
        max_target_tokens=512,batch_size=8,deadline,max_sites_per_row=2):
    """Collect complete source-only greedy rollouts without copying the model.

``consumed_prefix`` includes BOS and exactly the input tokens actually consumed
while each row was active. Predictions exclude special tokens as core._greedy
does. Every visited valid boundary is retained; only the first/last distinct
sites will receive the separate training loss. Timeouts yield no partial result.
"""
    started=time.monotonic();_check_deadline(deadline)
    _require(type(max_target_tokens) is int and 4<=max_target_tokens<=512,"fixed512 output ceiling required")
    _require(type(batch_size) is int and 1<=batch_size<=128,"bounded generation batch required")
    _require(type(max_sites_per_row) is int and max_sites_per_row==2,"fixed first/last two-site policy required")
    torch=core._torch();core._model(model,torch)
    shared.checked_specification(model,codec)
    _sources(source_rows,model.dimension);_transform(input_transform,model.dimension)
    tables=cardinality._tables(codec,len(codec["target_vocabulary"]),torch)
    before=core.tensor_digest(model);versions=_state_versions(model)
    modes={name:module.training for name,module in model.named_modules()}
    rng=torch.get_rng_state().clone();python_rng=random.getstate()
    predictions=[];records=[];steps=0
    try:
        model.eval()
        with torch.no_grad():
            for offset in range(0,len(source_rows),batch_size):
                _check_deadline(deadline);part=source_rows[offset:offset+batch_size]
                observer=_Collector(model,tables,deadline)
                generated=core._greedy(torch,observer,_data(torch,part,input_transform),
                    max_target_tokens,len(codec["target_vocabulary"]),deadline)
                if generated is None:raise TimeoutError("generated boundary deadline exceeded")
                steps+=observer.steps
                for index,(row,tokens,status) in enumerate(zip(part,generated[1],generated[2])):
                    prefix=observer.prefixes[index];sites=observer.sites[index];selected=_select(sites)
                    _require(prefix==([1]+tokens[:len(prefix)-1]),"actual prefix does not match generated output")
                    predictions.append(dict(id=row["id"],token_ids=tokens,generation_status=status,eos_reached=status=="eos"))
                    records.append(dict(id=row["id"],consumed_prefix=prefix,available_sites=sites,selected_sites=selected,
                        available_site_count=len(sites),selected_site_count=len(selected),ignored_site_count=len(sites)-len(selected),
                        first_invalid_prefix_position=observer.invalid[index],batch_offset=offset,
                        replay_prefix_tokens=selected[-1]["position"]+1 if selected else 0))
    finally:
        for name,module in model.named_modules():module.training=modes[name]
        _require(core.tensor_digest(model)==before and _state_versions(model)==versions,
            "source collection changed caller weights or gradients")
        _require(torch.equal(torch.get_rng_state(),rng) and random.getstate()==python_rng,
            "source collection changed ambient RNG")
    _check_deadline(deadline)
    result=dict(schema=SCHEMA,complete=True,model_tensor_sha256=before,codec_sha256=core.digest(codec),
        input_transform_sha256=core.digest(input_transform),source_rows=[dict(id=r["id"],input=list(r["input"])) for r in source_rows],
        predictions=predictions,rows=records,batch_size=batch_size,max_target_tokens=max_target_tokens,
        max_sites_per_row=2,selection_policy=POLICY,available_sites=sum(r["available_site_count"] for r in records),
        selected_sites=sum(r["selected_site_count"] for r in records),ignored_sites=sum(r["ignored_site_count"] for r in records),
        rows_without_sites=sum(not r["selected_sites"] for r in records),greedy_batch_steps=steps,
        generation_temperature=0,reference_count_access=False,reference_prefix_access=False,
        reference_documents_passed_to_model=False,source_only=True,collection_no_grad=True,
        complete_rollout_before_site_selection=True,model_copied=False,caller_state_preserved=True,
        elapsed_seconds=time.monotonic()-started,deadline_cooperative=True,**FALSE)
    result["collection_sha256"]=core.digest(result)
    return result


def _validate_collection(model,collection,codec,input_transform,torch):
    _require(type(collection) is dict and collection.get("schema")==SCHEMA and collection.get("complete") is True,
        "complete actual source collection required")
    _require(collection.get("collection_sha256")==core.digest({k:v for k,v in collection.items() if k!="collection_sha256"}),
        "source collection digest differs")
    _require(collection["model_tensor_sha256"]==core.tensor_digest(model)
        and collection["codec_sha256"]==core.digest(codec)
        and collection["input_transform_sha256"]==core.digest(input_transform),"stale model/codec/transform collection")
    _require(collection["selection_policy"]==POLICY and collection["max_sites_per_row"]==2
        and collection["generation_temperature"]==0 and collection["source_only"] is True
        and collection["reference_count_access"] is False and collection["reference_prefix_access"] is False,
        "source-only first/last collection policy required")
    source=collection["source_rows"];_sources(source,model.dimension)
    _require([r["id"] for r in collection["rows"]]==[r["id"] for r in source]
        ==[r["id"] for r in collection["predictions"]],"complete ordered source rows required")
    tables=cardinality._tables(codec,len(codec["target_vocabulary"]),torch)
    for row,prediction in zip(collection["rows"],collection["predictions"]):
        prefix=row["consumed_prefix"]
        _require(type(prefix) is list and 1<=len(prefix)<collection["max_target_tokens"]<=512
            and prefix[0]==1 and all(type(i) is int and 0<=i<len(codec["target_vocabulary"]) for i in prefix),
            "bounded actual consumed prefix required")
        _require(prefix==[1]+prediction["token_ids"][:len(prefix)-1],"prefix/output binding differs")
        state=[[0]*6];sites=[]
        for position,token in enumerate(prefix):
            updated,_=cardinality._scan_prefix([[token]],state,tables)
            if state[0][0]==9 and updated[0][0]==13 and updated[0][3]==state[0][3]+1:
                sites.append(dict(position=position,completed_rules=updated[0][3]))
            state=updated
        selected=_select(sites)
        _require(row["available_sites"]==sites and row["selected_sites"]==selected
            and row["available_site_count"]==len(sites) and row["selected_site_count"]==len(selected)
            and row["ignored_site_count"]==len(sites)-len(selected)
            and row["replay_prefix_tokens"]==(selected[-1]["position"]+1 if selected else 0),
            "actual first/last selected sites differ")
    _require(collection["selected_sites"]==sum(r["selected_site_count"] for r in collection["rows"]),
        "selected site total differs")
    return tables


def generated_boundary_loss(torch,model,collection,training_counts_by_id,*,codec,input_transform,deadline):
    """Return ``{loss: Tensor|None, receipt: dict}``; never update parameters.

Training counts are actual counts1..32. The reference-dependent target is used
only after the source rollout: comma for k<N, closing bracket for k>=N. Replay
uses the student's own prefix once per row, not a target prefix. All vocabulary
classes remain in CE. No-site collections return None with no attached graph.
"""
    started=time.monotonic();_check_deadline(deadline)
    core._model(model,torch);shared.checked_specification(model,codec);_transform(input_transform,model.dimension)
    tables=_validate_collection(model,collection,codec,input_transform,torch)
    _require(type(training_counts_by_id) is dict and 1<=len(training_counts_by_id)<=4096
        and all(type(identity) is str and type(count) is int and 1<=count<=32 for identity,count in training_counts_by_id.items())
        and {r["id"] for r in collection["source_rows"]}<=set(training_counts_by_id),
        "authenticated actual training counts1..32 required")
    sources={r["id"]:r for r in collection["source_rows"]};active=[r for r in collection["rows"] if r["selected_sites"]]
    receipt=dict(schema=LOSS_SCHEMA,collection_sha256=collection["collection_sha256"],
        training_counts_sha256=core.digest(training_counts_by_id),rows=len(sources),active_rows=len(active),
        rows_without_sites=len(sources)-len(active),available_sites=collection["available_sites"],
        selected_sites=collection["selected_sites"],ignored_sites=collection["ignored_sites"],selection_policy=POLICY,
        reduction="mean_selected_sites_within_row_then_mean_active_rows",vocabulary_size=len(codec["target_vocabulary"]),
        full_vocabulary_cross_entropy=True,reference_counts_used_only_in_loss=True,
        target_prefixes_used=False,student_generated_prefix_replay=True,additional_optimizer_steps=0,
        rows_replayed_once=True,events=[],row_losses=[],stop_labels=0,continue_labels=0,
        replay_prefix_tokens=0,mean_loss=None,**FALSE)
    receipt["generation"]=dict(max_target_tokens=collection["max_target_tokens"],batch_size=collection["batch_size"],
        greedy_batch_steps=collection["greedy_batch_steps"],elapsed_seconds=collection["elapsed_seconds"],
        model_tensor_sha256=collection["model_tensor_sha256"],source_only=True,reference_count_access=False,
        rows=[dict(**row,prediction=prediction,input_sha256=core.digest(sources[row["id"]]["input"]))
            for row,prediction in zip(collection["rows"],collection["predictions"])])
    if not active:
        _check_deadline(deadline);receipt["elapsed_seconds"]=time.monotonic()-started
        return dict(loss=None,receipt=receipt)
    before=core.tensor_digest(model);versions=_state_versions(model)
    modes={name:m.training for name,m in model.named_modules()};rng=torch.get_rng_state().clone();python_rng=random.getstate()
    row_losses=[]
    try:
        model.eval()
        for offset in range(0,len(active),collection["batch_size"]):
            _check_deadline(deadline);part=active[offset:offset+collection["batch_size"]]
            prefixes=[r["consumed_prefix"][:r["replay_prefix_tokens"]] for r in part];width=max(map(len,prefixes))
            tokens=torch.tensor([p+[0]*(width-len(p)) for p in prefixes],dtype=torch.long)
            _,logits=core._logits(torch,model,_data(torch,[sources[r["id"]] for r in part],input_transform),
                tokens,len(codec["target_vocabulary"]))
            _check_deadline(deadline)
            for index,row in enumerate(part):
                count=training_counts_by_id[row["id"]];sites=row["selected_sites"]
                targets=[tables[0]["," if site["completed_rules"]<count else "]"] for site in sites]
                observed=logits[index,[site["position"] for site in sites]]
                losses=torch.nn.functional.cross_entropy(observed,torch.tensor(targets,dtype=torch.long),reduction="none")
                _require(core._finite(torch,losses),"nonfinite generated boundary loss")
                row_losses.append(losses.mean());receipt["row_losses"].append(dict(id=row["id"],sites=len(sites),mean_ce=float(losses.mean().detach())))
                receipt["replay_prefix_tokens"]+=row["replay_prefix_tokens"]
                for site,target,raw_loss,raw_logits in zip(sites,targets,losses.detach().tolist(),observed.detach().tolist()):
                    stop=site["completed_rules"]>=count;receipt["stop_labels" if stop else "continue_labels"]+=1
                    receipt["events"].append(dict(id=row["id"],**site,training_count=count,target_token_id=target,
                        consumed_prefix_length=site["position"]+1,
                        consumed_prefix_sha256=core.digest(row["consumed_prefix"][:site["position"]+1]),
                        action="stop" if stop else "continue",cross_entropy=raw_loss,replay_logits=raw_logits,
                        mean_loss_coefficient=1./len(active)/len(sites)))
        loss=torch.stack(row_losses).mean();receipt["mean_loss"]=float(loss.detach())
        _require(core._finite(torch,loss),"nonfinite mean boundary loss")
    finally:
        for name,module in model.named_modules():module.training=modes[name]
        _require(core.tensor_digest(model)==before and _state_versions(model)==versions,"boundary replay mutated weights or gradients")
        _require(torch.equal(torch.get_rng_state(),rng) and random.getstate()==python_rng,"boundary replay changed RNG")
    _check_deadline(deadline);receipt["elapsed_seconds"]=time.monotonic()-started
    return dict(loss=loss,receipt=receipt)
