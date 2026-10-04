"""Bounded private replay of a captured decoder optimizer step.

Exact combined-step replay precedes approximate gradient attribution. Neither a
replayed update nor its loss is qualification, source fidelity, or proof evidence.
No extra backward pass belongs in the live trainer. This module changes no
published decoder, curriculum, optimizer, or acceptance policy.
"""
from copy import deepcopy
import hashlib
import json
import math
import random
import time

from . import decoder_distillation_experiment as core

SCHEMA = "decoder-gradient-event/v1"
REPORT_SCHEMA = "decoder-gradient-replay/v1"
FALSE = dict(qualified=False, admitted=False, proof_authority=False,
    source_semantics_verified=False, checkpoint_promoted=False, formalized=False,
    roundtrip_ok=False, convergence_proven=False, fresh_holdout=False,
    lake_executed=False, generation_executed=False)
_DTYPES = {"torch.float32", "torch.float64", "torch.int64", "torch.int32", "torch.uint8", "torch.bool"}


def _require(value, reason):
    if not value:
        raise ValueError(reason)


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, allow_nan=False).encode()


def _wire(value, *, tensors="digest", depth=0):
    """Closed recursive encoding retains dictionary key types and tuple identity."""
    _require(depth <= 32, "gradient snapshot nesting exceeds bound")
    if isinstance(value, dict):
        _require(len(value) <= 65536, "gradient snapshot mapping exceeds bound")
        pairs=[]
        for key,item in value.items():
            _require(type(key) in (str,int), "snapshot dictionary keys must be strings or integers")
            pairs.append([key,_wire(item,tensors=tensors,depth=depth+1)])
        pairs.sort(key=lambda pair:_canonical(pair[0]))
        return {"kind":"dict","pairs":pairs}
    if type(value) in (list,tuple):
        _require(len(value) <= 1000000, "gradient snapshot sequence exceeds bound")
        return {"kind":"tuple" if type(value) is tuple else "list",
            "items":[_wire(item,tensors=tensors,depth=depth+1) for item in value]}
    if value is None or type(value) in (str,bool,int,float):
        _require(type(value) is not float or math.isfinite(value), "nonfinite snapshot scalar")
        return {"kind":"scalar","value":value}
    # Importing this helper does not itself initialize Torch; capture already has it.
    import torch
    _require(isinstance(value,torch.Tensor) and value.device.type=="cpu" and str(value.dtype) in _DTYPES,
        "only supported CPU snapshot tensors are allowed")
    _require(value.numel() <= 1000000 and value.ndim <= 4 and bool(torch.isfinite(value).all()),
        "bounded finite snapshot tensor required")
    actual=value.detach().contiguous()
    result=dict(kind="tensor",dtype=str(actual.dtype),shape=list(actual.shape))
    if tensors=="values":result["values"]=actual.tolist()
    else:result["sha256"]=hashlib.sha256(actual.numpy().tobytes()).hexdigest()
    return result


def state_digest(value):
    """Hash exact nested tensor bytes, including signed zero and integer keys."""
    return hashlib.sha256(_canonical(_wire(value))).hexdigest()


def gradient_digest(model):
    """Preserve named gradient None-versus-zero status, including frozen tensors."""
    return state_digest({name:parameter.grad for name,parameter in model.named_parameters()})


def event_digest(event):
    _require(type(event) is dict, "gradient event mapping required")
    return state_digest({key:value for key,value in event.items() if key!="event_sha256"})


def _tensor_bytes(value):
    if isinstance(value,dict):return sum(_tensor_bytes(item) for item in value.values())
    if isinstance(value,(list,tuple)):return sum(_tensor_bytes(item) for item in value)
    if hasattr(value,"numel") and hasattr(value,"element_size"):return value.numel()*value.element_size()
    return 0


def _unwire(value, *, depth=0):
    _require(type(value) is dict and depth<=32, "invalid tagged snapshot")
    kind=value.get("kind")
    if kind=="scalar":
        _require(set(value)=={"kind","value"} and (value["value"] is None or
            type(value["value"]) in (str,bool,int,float)), "invalid tagged scalar")
        _require(type(value["value"]) is not float or math.isfinite(value["value"]), "nonfinite snapshot scalar")
        return value["value"]
    if kind in ("list","tuple"):
        _require(set(value)=={"kind","items"} and type(value["items"]) is list
            and len(value["items"])<=1000000, "invalid tagged sequence")
        items=[_unwire(item,depth=depth+1) for item in value["items"]]
        return tuple(items) if kind=="tuple" else items
    if kind=="dict":
        _require(set(value)=={"kind","pairs"} and type(value["pairs"]) is list
            and len(value["pairs"])<=65536, "invalid tagged dictionary")
        result={}
        for pair in value["pairs"]:
            _require(type(pair) is list and len(pair)==2 and type(pair[0]) in (str,int)
                and pair[0] not in result, "invalid or duplicate tagged dictionary key")
            result[pair[0]]=_unwire(pair[1],depth=depth+1)
        return result
    _require(kind=="tensor" and set(value)=={"kind","dtype","shape","values"}
        and value["dtype"] in _DTYPES, "invalid tagged tensor")
    shape=value["shape"]
    _require(type(shape) is list and len(shape)<=4 and all(type(n) is int and 0<=n<=1000000 for n in shape)
        and math.prod(shape)<=1000000, "tagged tensor geometry exceeds bound")
    def check_values(items, dimensions):
        if not dimensions:
            _require(type(items) in (int,float,bool) and (type(items) is not float or math.isfinite(items)),
                "tagged tensor scalar differs")
            return
        _require(type(items) is list and len(items)==dimensions[0], "tagged tensor shape differs")
        for item in items:check_values(item,dimensions[1:])
    check_values(value["values"],shape)
    import torch
    result=torch.tensor(value["values"],dtype=getattr(torch,value["dtype"].removeprefix("torch.")))
    _require(list(result.shape)==shape and bool(torch.isfinite(result).all()), "tagged tensor shape or finiteness differs")
    return result


def pack_event(event):
    _validate_event(event,allow_uncommitted=True)
    return {"schema":"decoder-gradient-event-wire/v1","event":_wire(event,tensors="values")}


def unpack_event(value, *, max_bytes=67108864):
    _require(type(max_bytes) is int and 1<=max_bytes<=268435456, "bounded snapshot byte limit required")
    _require(type(value) is dict and set(value)=={"schema","event"}
        and value["schema"]=="decoder-gradient-event-wire/v1", "invalid gradient event wire schema")
    _require(len(_canonical(value))<=max_bytes, "serialized snapshot exceeds byte limit")
    event=_unwire(value["event"])
    _validate_event(event,allow_uncommitted=True)
    return event


_FIELDS = {"schema","complete","committed","optimizer_step_before","model_state_dict",
    "trainable_parameter_names","optimizer_state_dict","optimizer_class","config",
    "cardinality_weight","strategy","count_exposure","input_transform","codec_sha256",
    "decoder_row_ids","count_row_ids","decoder_batch_sha256","count_batch_sha256",
    "token_weights_sha256","count_targets","losses","preclip_norm","clipped_gradient_sha256",
    "pre_step_model_sha256","pre_step_optimizer_sha256","poststep_tensor_sha256",
    "poststep_optimizer_sha256","module_modes","rng_state","source_selector_snapshot",
    "epoch","stage","stage_epoch","event_sha256","learning_rates","captured_tensor_bytes",
    "scope","qualified","admitted","proof_authority"}
_OPTIONAL_FIELDS={"postclip_module_summaries","uncommitted_reason"}


def validate_gradient_event(event):
    return _validate_event(event,allow_uncommitted=False)


def _validate_event(event, *, allow_uncommitted):
    _require(type(event) is dict and _FIELDS<=set(event)<=_FIELDS|_OPTIONAL_FIELDS and event["schema"]==SCHEMA,
        "closed gradient event schema required")
    committed=event["complete"] is True and event["committed"] is True
    incomplete=event["complete"] is False and event["committed"] is False and isinstance(event.get("uncommitted_reason"),str)
    _require(committed or (allow_uncommitted and incomplete), "only complete committed gradient events can be replayed")
    _require(all(event[key] is False for key in ("qualified","admitted","proof_authority")),
        "gradient diagnostics have no qualification authority")
    _require(committed or (event["poststep_tensor_sha256"] is None and event["poststep_optimizer_sha256"] is None),
        "uncommitted event cannot claim a post-step state")
    _require(type(event["optimizer_step_before"]) is int and event["optimizer_step_before"]>=0,
        "valid pre-step optimizer index required")
    _require(event["optimizer_class"]=="AdamW" and event["count_exposure"] in ("current_stage","balanced_all"),
        "unsupported captured optimizer or exposure")
    _require(event["strategy"] in ("semantic_fields","reference_ce") and event["cardinality_weight"]==.25,
        "captured count replay requires the explicit quarter-weight objective")
    for key in ("decoder_row_ids","count_row_ids"):
        _require(type(event[key]) is list and 1<=len(event[key])<=128
            and all(type(item) is str and item for item in event[key]), "bounded captured batch IDs required")
    _require(len(event["count_row_ids"])==len(event["decoder_row_ids"]), "captured count/decoder batch sizes differ")
    _require(type(event["count_targets"]) is list and len(event["count_targets"])==len(event["count_row_ids"])
        and all(type(x) is int and 0<=x<32 for x in event["count_targets"]), "captured count labels invalid")
    names=event["trainable_parameter_names"]
    _require(type(names) is list and names and len(names)==len(set(names)) and all(type(x) is str for x in names),
        "ordered unique trainable names required")
    _require(type(event["losses"]) is dict and set(event["losses"])==
        {"weighted_token_ce","token_ce","count_ce","mse","objective"} and all(
        type(v) in (float,int) and math.isfinite(v) for v in event["losses"].values()), "finite captured losses required")
    _require(type(event["preclip_norm"]) in (float,int) and math.isfinite(event["preclip_norm"])
        and event["preclip_norm"]>=0, "finite captured gradient norm required")
    _require(type(event["captured_tensor_bytes"]) is int and 0<event["captured_tensor_bytes"]<=67108864
        and event["captured_tensor_bytes"]==_tensor_bytes(event), "captured tensor memory accounting differs")
    _require(state_digest(event["optimizer_state_dict"])==event["pre_step_optimizer_sha256"],
        "captured pre-step optimizer digest differs")
    _require(event_digest(event)==event["event_sha256"], "gradient event digest differs")
    return {"valid":committed,"replay_eligible":committed,
        "scope":"closed hashed diagnostic snapshot; caller provenance not authenticated",**FALSE}


def _group(name):
    for key in ("projection_down","projection_up","source_to_embedding","target_embedding","condition","decoder","output","count_head"):
        if key in name.split("."):
            return key
    return "other"


def _attribution(torch, combined, token, count, *, atol, rtol):
    _require(set(combined)==set(token)==set(count), "gradient parameter inventories differ")
    totals={}; maximum_error=0.; reconciles=True
    for name in combined:
        tensors=[mapping[name] for mapping in (combined,token,count)]
        template=next((value for value in tensors if value is not None),None)
        if template is None:continue
        actual,left,right=[torch.zeros_like(template,dtype=torch.float64) if value is None
            else value.double() for value in tensors]
        delta=actual-(left+right)
        maximum_error=max(maximum_error,float(delta.abs().max()))
        reconciles=reconciles and bool(torch.allclose(actual,left+right,atol=atol,rtol=rtol))
        item=totals.setdefault(_group(name),dict(combined_sq=0.,token_sq=0.,count_sq=0.,dot=0.,parameters=[]))
        item["combined_sq"]+=float(actual.square().sum());item["token_sq"]+=float(left.square().sum())
        item["count_sq"]+=float(right.square().sum());item["dot"]+=float((left*right).sum());item["parameters"].append(name)
    result={}
    global_totals=dict(combined_sq=0.,token_sq=0.,count_sq=0.,dot=0.)
    for key,item in totals.items():
        for field in global_totals:global_totals[field]+=item[field]
        a,b=math.sqrt(item["token_sq"]),math.sqrt(item["count_sq"])
        result[key]=dict(combined_norm=math.sqrt(item["combined_sq"]),weighted_token_ce_norm=a,
            quarter_weight_count_ce_norm=b,raw_count_ce_norm=b/.25,
            weighted_branch_dot=item["dot"],weighted_branch_cosine=item["dot"]/(a*b) if a*b else None,
            parameters=item["parameters"])
    a,b=math.sqrt(global_totals["token_sq"]),math.sqrt(global_totals["count_sq"])
    global_summary=dict(combined_norm=math.sqrt(global_totals["combined_sq"]),weighted_token_ce_norm=a,
        quarter_weight_count_ce_norm=b,raw_count_ce_norm=b/.25,weighted_branch_dot=global_totals["dot"],
        weighted_branch_cosine=global_totals["dot"]/(a*b) if a*b else None,
        accumulation="float64 detached gradient copies; the exact clip operation retains its original float32 arithmetic")
    return dict(groups=result,global_summary=global_summary,branches_reconcile=reconciles,
        status="reconciled" if reconciles else "unreconciled_do_not_claim_additive_attribution",
        max_absolute_reconciliation_error=maximum_error,
        reconciliation_atol=atol,reconciliation_rtol=rtol,
        reconciliation_scope="separate fresh float32 backward passes may differ by reduction order; comparisons use float64 copies",
        zero_norm_cosine=None,count_gradient_coefficient=.25)


def replay_event(model,event,rows,references,codec,transform,*,strategy="semantic_fields",
        validate_rule,max_seconds=30.,max_memory_bytes=536870912,
        reconciliation_atol=1e-4,reconciliation_rtol=1e-4):
    """Verify one committed AdamW step exactly, then attribute its gradients privately."""
    started=time.monotonic()
    _require(type(max_seconds) in (int,float) and math.isfinite(max_seconds) and 0<max_seconds<=120,
        "bounded replay deadline required")
    _require(type(max_memory_bytes) is int and 1<=max_memory_bytes<=2147483648, "bounded replay memory budget required")
    _require(all(type(value) in (int,float) and math.isfinite(value) and 0<=value<=1e-3
        for value in (reconciliation_atol,reconciliation_rtol)), "bounded explicit attribution tolerances required")
    deadline=started+max_seconds
    def check():
        if time.monotonic()>=deadline:raise TimeoutError("gradient replay deadline; incomplete analysis is not accepted")
    check();validate_gradient_event(event);check()
    torch=core._torch()
    from . import long_span_count_exposure_training as inherited
    core._model(model,torch)
    _require(strategy==event["strategy"] and core.digest(codec)==event["codec_sha256"]
        and transform==event["input_transform"], "replay codec, transform or strategy differs")
    options=core._config(event["config"])
    _require(options["alpha"]==0., "diagnostic replay cannot add a teacher loss")
    core._rows(rows,model.dimension,codec["target_vocabulary"],options["max_target_tokens"])
    by_id={row["id"]:row for row in rows}
    _require(all(identity in by_id for identity in event["decoder_row_ids"]+event["count_row_ids"]),
        "captured batch has unknown training rows")
    decoder_rows=[by_id[i] for i in event["decoder_row_ids"]];count_rows=[by_id[i] for i in event["count_row_ids"]]
    _require(core.digest(decoder_rows)==event["decoder_batch_sha256"] and core.digest(count_rows)==event["count_batch_sha256"],
        "captured training batch bytes differ")
    labels_by_id=inherited._count_labels(references)
    _require([labels_by_id[row["id"]] for row in count_rows]==event["count_targets"], "captured count labels disagree with references")
    weights=inherited.reference_weights(rows,references,codec,strategy=strategy,validate_rule=validate_rule)
    _require(core.digest({row["id"]:weights[row["id"]] for row in decoder_rows})==event["token_weights_sha256"],
        "captured token weights differ")
    names=[name for name,p in model.named_parameters() if p.requires_grad]
    _require(names==event["trainable_parameter_names"], "captured trainable parameter order differs")
    modes={name:m.training for name,m in model.named_modules()}
    _require(set(modes)==set(event["module_modes"]) and all(type(x) is bool for x in event["module_modes"].values()),
        "captured module modes differ")
    parameter_bytes=sum(t.numel()*t.element_size() for t in model.state_dict().values())
    width=max(len(row["target_ids"]) for row in decoder_rows)
    estimate=parameter_bytes*48+2*event["captured_tensor_bytes"]+64*len(decoder_rows)*width*len(codec["target_vocabulary"])*4
    _require(estimate<=max_memory_bytes, "gradient replay tensor work exceeds memory budget")
    before=core.tensor_digest(model);before_grads=gradient_digest(model)
    outer_torch=torch.get_rng_state().clone();outer_python=random.getstate()
    check()
    def fresh():
        check();value=deepcopy(model);value.load_state_dict(event["model_state_dict"],strict=True)
        _require(core.tensor_digest(value)==event["pre_step_model_sha256"], "captured pre-step model digest differs")
        for name,child in value.named_modules():child.training=event["module_modes"][name]
        value.zero_grad(set_to_none=True)
        torch.set_rng_state(event["rng_state"]["torch"]);random.setstate(event["rng_state"]["python"])
        return value
    def forward(value):
        check();data,labels=core._batch(torch,decoder_rows,transform)
        token_weights=torch.tensor([weights[row["id"]]+[0.]*(labels.shape[1]-len(weights[row["id"]]))
            for row in decoder_rows],dtype=torch.float32)[:,1:]
        projected,logits=core._logits(torch,value,data,labels[:,:-1],len(codec["target_vocabulary"]))
        ce=torch.nn.functional.cross_entropy(logits.flatten(0,1),labels[:,1:].flatten(),ignore_index=0,reduction="none").reshape(labels.shape[0],-1)
        plain=ce.sum()/(labels[:,1:]!=0).sum();weighted=(ce*token_weights).sum()/token_weights.sum()
        mse=(projected-data).square().mean()*transform["scale"]**2
        if event["count_exposure"]=="current_stage":
            _require(event["count_row_ids"]==event["decoder_row_ids"], "current-stage count projection binding differs")
            count_projected=projected
        else:count_projected=value.project(inherited._source_batch(torch,count_rows,transform))
        logits_count=inherited._count_logits(torch,value,count_projected)
        count=torch.nn.functional.cross_entropy(logits_count,torch.tensor(event["count_targets"],dtype=torch.long))
        objective=weighted+options["reconstruction_weight"]*mse
        objective=objective+event["cardinality_weight"]*count
        losses=dict(weighted_token_ce=weighted,token_ce=plain,count_ce=count,mse=mse,objective=objective)
        _require(all(core._finite(torch,x) for x in losses.values()), "nonfinite replay loss")
        check();return losses
    def gradients(value):return {name:None if p.grad is None else p.grad.detach().clone() for name,p in value.named_parameters()}
    try:
        working=fresh();trainable=[p for p in working.parameters() if p.requires_grad]
        optimizer=torch.optim.AdamW(trainable,lr=options["learning_rate"],weight_decay=options["weight_decay"],foreach=False)
        optimizer.load_state_dict(deepcopy(event["optimizer_state_dict"]))
        _require(state_digest(optimizer.state_dict())==event["pre_step_optimizer_sha256"], "restored optimizer state differs")
        losses=forward(working)
        _require({key:float(value.detach()) for key,value in losses.items()}==event["losses"], "full replay loss differs")
        _require(not losses["mse"].requires_grad, "replay scope requires a frozen projection MSE branch")
        losses["objective"].backward();check();combined=gradients(working)
        norm=torch.nn.utils.clip_grad_norm_(trainable,options["max_grad_norm"],error_if_nonfinite=True)
        _require(float(norm)==event["preclip_norm"], "full replay preclip norm differs")
        _require(gradient_digest(working)==event["clipped_gradient_sha256"], "full replay clipped gradients differ")
        check();optimizer.step();check()
        _require(core.tensor_digest(working)==event["poststep_tensor_sha256"], "full replay post-step model differs")
        _require(state_digest(optimizer.state_dict())==event["poststep_optimizer_sha256"], "full replay post-step optimizer differs")
        del optimizer,working,losses
        branches={}
        for name in ("weighted_token_ce","count_ce"):
            working=fresh();losses=forward(working)
            loss=losses[name] if name=="weighted_token_ce" else losses[name]*event["cardinality_weight"]
            loss.backward();check();branches[name]=gradients(working)
            del working,losses,loss
        attribution=_attribution(torch,combined,branches["weighted_token_ce"],branches["count_ce"],
            atol=reconciliation_atol,rtol=reconciliation_rtol)
        check()
        result=dict(schema=REPORT_SCHEMA,complete=True,event_sha256=event["event_sha256"],
            optimizer_step_before=event["optimizer_step_before"],epoch=event["epoch"],stage=event["stage"],
            decoder_row_ids=event["decoder_row_ids"],count_row_ids=event["count_row_ids"],
            full_step_exact=True,full_loss_exact=True,preclip_norm_exact=True,clipped_gradient_digest_exact=True,
            poststep_model_digest_exact=True,poststep_optimizer_digest_exact=True,
            preclip_norm=event["preclip_norm"],losses=event["losses"],attribution=attribution,
            attribution_valid=attribution["branches_reconcile"],
            frozen_reconstruction_branch=dict(requires_grad=False,gradient_norm=0.,cosine=None),
            template_model_unchanged=True,optimizer_steps_on_private_copy=1,
            live_training_modified=False,used_for_selection=False,
            tensor_work_estimate_bytes=estimate,memory_estimate_excludes_python_import_allocator_rss=True,
            deadline_cooperative=True,
            scope="isolated captured-tail-event diagnosis; no corpus-level frequency or causal training intervention",**FALSE)
    finally:
        torch.set_rng_state(outer_torch);random.setstate(outer_python)
        _require(core.tensor_digest(model)==before and gradient_digest(model)==before_grads
            and {name:m.training for name,m in model.named_modules()}==modes,
            "caller model changed during private replay")
    finished=time.monotonic()
    if finished>=deadline:
        raise TimeoutError("gradient replay deadline after final integrity verification; incomplete analysis is not accepted")
    result["elapsed_seconds"]=finished-started
    return result
