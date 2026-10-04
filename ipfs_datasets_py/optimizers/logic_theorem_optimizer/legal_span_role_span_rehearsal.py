"""Matched role/span rehearsal from immutable heterogeneous clause parents.

The original bounded main inventory and sampler are unchanged. A separately
bounded authored auxiliary inventory supplies four rows to BOTH objectives.
Both optimize standard seven-facet auxiliary CE; treatment additionally balances
actor endpoints and optional C/E/T presence/present endpoints. No inference
threshold, architecture, authority or original inventory cap changes.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import os
from pathlib import Path
import random
import stat
import time
from types import MappingProxyType

from . import legal_span_mixed_replay as mixed
from . import legal_span_consistency as previous
from . import legal_span_facet_retention as facet
from . import legal_span_temporal_presence as temporal

span = mixed.span
_require, _raw, checkpoint_digest = span._require, span._raw, span.checkpoint_digest
FALSE = span.FALSE
SCHEMA = "role-span-rehearsal-checkpoint/v1"
LINEAGE_ID = "role_span_rehearsal_v1"
MAX_BYTES = mixed.MAX_BYTES
MAX_AUXILIARY_EXAMPLES = 1024
AUXILIARY_FIELDS = ("actor", "conditions", "exceptions", "temporal")
POOLS = ("earlier", "historical_new", "positive_pairs", "negative_pairs")
PAIR_POSITIONS = ((6, 7), (8, 9), (10, 11))
ROLE_NAMES = (*span.SPAN_FIELDS, "trigger", "other")


def _capture_implementation():
    return {"role_span_rehearsal_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "frozen_temporal": temporal._implementation()}


_IMPLEMENTATION_AT_IMPORT = _capture_implementation()


def _implementation():
    value = _capture_implementation()
    _require(value == _IMPLEMENTATION_AT_IMPORT, "role/span rehearsal implementation source drift")
    return value


def _training_config(objective, seed, learning_rate=.00025, batch_size=12):
    _require(objective in ('base','role_rehearsal'), 'known matched training objective required')
    _require(type(learning_rate) in (int,float) and learning_rate == .00025,'learning rate must be .00025')
    config=temporal._training_config('base',seed,.0005,batch_size)
    config.pop('temporal_presence_weight'); config.pop('temporal_presence_profile')
    return {**config,'objective':objective,'learning_rate':float(learning_rate),'optimizer_step_budget':200,
        'auxiliary_standard_ce_weight':.25,'role_rehearsal_weight':.5 if objective=='role_rehearsal' else 0.,
        'role_rehearsal_profile':'mean_actor_endpoints_and_half_balanced_presence_plus_half_present_endpoints_CET/v1',
        'auxiliary_standard_ce_profile':'frozen_seven_facet_span_CE_no_aux_trigger_or_JS/v1',
        'auxiliary_rows_per_step':4,'max_auxiliary_examples':MAX_AUXILIARY_EXAMPLES,
        'auxiliary_sampling':'independent_shuffle_wrap_one_complement_block/v1',
        'teacher_profile':'frozen_exact_current_parent_train_only_correct_optional_presence_and_present_qualifier_endpoints/v1',
        'initialization':'copy_all_exact_kind_parent_weights_fresh_adam/v1'}


def _parent_runtime(kind):
    _require(kind in ('facet_retention','temporal_presence'),'known frozen parent kind required')
    return facet if kind=='facet_retention' else temporal


_valid_span_scores=facet._valid_span_scores
_valid_span_distribution=facet._valid_span_distribution
_teacher_loss=facet._teacher_loss
_pair_overlap_probability=facet._pair_overlap_probability
_overlap_loss=facet._overlap_loss
_pairs_and_pools=temporal._pairs_and_pools


def _aux_order(count, seed, epoch):
    order=list(range(count))
    random.Random(f'role-span-rehearsal/v1:{seed}:auxiliary_blocks:{epoch}').shuffle(order)
    return order


def _progress(counts, auxiliary_blocks, seed, steps=0):
    progress=temporal._progress(counts,seed,steps)
    epoch,cursor=divmod(steps,auxiliary_blocks)
    progress['auxiliary_blocks']={'epochs_completed':epoch,'row_cursor':cursor,
        'shuffle_order':_aux_order(auxiliary_blocks,seed,epoch)}
    return progress


def next_batch_indices(progress, counts, auxiliary_blocks, seed):
    selected,updated=temporal.next_batch_indices(progress,counts,seed)
    state=updated['auxiliary_blocks']
    selected['auxiliary_block']=[state['shuffle_order'][state['row_cursor']]]
    state['row_cursor']+=1
    if state['row_cursor']==auxiliary_blocks:
        state['epochs_completed']+=1;state['row_cursor']=0
        state['shuffle_order']=_aux_order(auxiliary_blocks,seed,state['epochs_completed'])
    return selected,updated


def _identifier(value):
    return type(value) is str and 0<len(value.strip())<=512


def _auxiliary_data(training_rows, tuning_rows, aux_rows, aux_pairs, aux_blocks):
    """Separate inventory validation; never merge auxiliary rows into main cap.

    The frozen parser's second split accepts a new-only inventory. It validates
    every source offset and cross-inventory isolation without synthesizing labels
    or temporarily changing domains, IDs, supervision flags or MAX_EXAMPLES.
    """
    _require(type(aux_rows) is list and 4<=len(aux_rows)<=MAX_AUXILIARY_EXAMPLES and len(aux_rows)%4==0,
        'separate auxiliary inventory must have4..1024 rows in complete blocks')
    records,tuning=mixed._splits(training_rows,tuning_rows)
    _,auxiliary=mixed._splits(training_rows,aux_rows)
    _require(all(r['domain']=='new' and r['trigger_supervised'] is True for r in aux_rows),'auxiliary rows require authored new-domain spans')
    _require(not {r['id'] for r in aux_rows}&{r['id'] for r in tuning_rows}
        and not {r['source_text'] for r in aux_rows}&{r['source_text'] for r in tuning_rows},'auxiliary/tuning overlap')
    _require(type(aux_pairs) is list and len(aux_pairs)*2==len(aux_rows),'auxiliary pairs must exhaust rows')
    by_id={r['id']:r for r in aux_rows};seen=set();pair_map={}
    for pair in aux_pairs:
        _require(type(pair) is dict and set(pair)=={'pair_id','case_group','left_id','right_id','canonical_ir_sha256'},'closed auxiliary pair metadata required')
        _require(all(_identifier(pair[k]) for k in ('pair_id','case_group','left_id','right_id'))
            and pair['pair_id'] not in pair_map,'unique bounded auxiliary pair IDs required')
        ids=[pair['left_id'],pair['right_id']]
        _require(ids[0]!=ids[1] and all(i in by_id and i not in seen for i in ids),'disjoint complete auxiliary pair membership required')
        left,right=(by_id[i] for i in ids)
        _require(left['canonical_ir']==right['canonical_ir'] and pair['canonical_ir_sha256']==checkpoint_digest(left['canonical_ir']),
            'auxiliary pair canonical meaning or digest differs')
        pair_map[pair['pair_id']]=ids;seen.update(ids)
    _require(seen==set(by_id),'auxiliary pair rows missing')
    _require(type(aux_blocks) is list and len(aux_blocks)*4==len(aux_rows),'auxiliary blocks must exhaust pairs')
    block_ids=set();used_pairs=set();block_rows=[]
    for block in aux_blocks:
        _require(type(block) is dict and set(block)=={'block_id','pair_ids'} and _identifier(block['block_id'])
            and block['block_id'] not in block_ids,'closed unique auxiliary block required')
        pairs=block['pair_ids']
        _require(type(pairs) is list and len(pairs)==2 and all(type(i) is str and i in pair_map and i not in used_pairs for i in pairs)
            and pairs[0]!=pairs[1],'two distinct unused auxiliary pairs per block required')
        ids=[i for pair in pairs for i in pair_map[pair]]
        rules=[by_id[i]['canonical_ir']['rules'][0] for i in ids]
        _require(len({r['modality'] for r in rules})==1,'auxiliary block modality must be matched')
        _require(all(sum(bool(r[field]) for r in rules)==2 for field in AUXILIARY_FIELDS[1:]),'complementary auxiliary C/E/T masks require2present2absent')
        used_pairs.update(pairs);block_ids.add(block['block_id']);block_rows.append(ids)
    _require(used_pairs==set(pair_map),'auxiliary pairs missing from blocks')
    return records,tuning,auxiliary,block_rows


def _role_rehearsal_loss(torch, output, records):
    _require(len(records)==4,'exactly four auxiliary rehearsal rows required')
    ce=torch.nn.functional.cross_entropy
    terms=[];parts={};device=output['start'].device;zero=output['modality'].sum().detach()*0
    for field in AUXILIARY_FIELDS:
        facet_index=span.SPAN_FIELDS.index(field)
        groups={False:[],True:[]};endpoints=[]
        for i,record in enumerate(records):
            present=bool(record['labels']['presence'][facet_index]);count=len(record['tokens'])
            if field!='actor':
                optional=span.OPTIONAL_FIELDS.index(field)
                groups[present].append(ce(output['presence'][i,optional],torch.tensor(int(present),device=device)))
            if present:
                start,end=record['labels']['spans'][facet_index]
                endpoints.append((ce(output['start'][i,facet_index,:count],torch.tensor(start,device=device))+
                    ce(output['end'][i,facet_index,:count],torch.tensor(end,device=device)))*.5)
        if field=='actor':
            _require(len(endpoints)==4,'all auxiliary actor spans must be present')
            value=torch.stack(endpoints).mean();parts['aux_actor_endpoint_ce']=value
        else:
            _require(len(groups[True])==len(groups[False])==2 and len(endpoints)==2,
                'every auxiliary optional facet requires2present2absent')
            negative,positive=(torch.stack(groups[label]).mean() for label in (False,True))
            balanced=(negative+positive)*.5;endpoint=torch.stack(endpoints).mean();value=(balanced+endpoint)*.5
            parts.update({f'aux_{field}_positive_ce':positive,f'aux_{field}_negative_ce':negative,
                f'aux_{field}_balanced_presence_ce':balanced,f'aux_{field}_present_endpoint_ce':endpoint,
                f'aux_{field}_positive_rows':zero+2,f'aux_{field}_negative_rows':zero+2})
        parts[f'aux_{field}_role_ce']=value;terms.append(value)
    loss=torch.stack(terms).mean();parts['role_rehearsal_ce']=loss
    return loss,parts


def _loss(torch, model, teacher, records, auxiliary_records, model_config, objective):
    _require(objective in ('base','role_rehearsal'),'known matched training objective required')
    batch=span._batch(torch,records);output=model(*batch)
    with torch.no_grad():teacher_output=teacher(*batch)
    base,parts=previous._loss(torch,lambda *_:output,records,model_config,'consistency')
    preservation,teacher_parts=_teacher_loss(torch,output,teacher_output,records)
    overlap,overlap_parts=_overlap_loss(torch,output,records)
    auxiliary_output=model(*span._batch(torch,auxiliary_records))
    auxiliary_ce=span._loss(torch,lambda *_:auxiliary_output,auxiliary_records)
    rehearsal,rehearsal_parts=_role_rehearsal_loss(torch,auxiliary_output,auxiliary_records)
    common=base+.5*preservation+.1*overlap+.25*auxiliary_ce
    weight=.5 if objective=='role_rehearsal' else 0.
    total=common+weight*rehearsal
    receipt={'ids':[r['id'] for r in auxiliary_records],
        'token_counts':[len(r['tokens']) for r in auxiliary_records],
        'labels':[copy.deepcopy(r['labels']) for r in auxiliary_records],
        'logits':{k:auxiliary_output[k].detach().tolist() for k in ('modality','presence','start','end')}}
    return total,{**parts,**teacher_parts,**overlap_parts,**rehearsal_parts,'base_objective':base,
        'teacher_kl':preservation,'span_overlap':overlap,'weighted_teacher':.5*preservation,'weighted_overlap':.1*overlap,
        'auxiliary_standard_ce':auxiliary_ce,'weighted_auxiliary_standard_ce':.25*auxiliary_ce,
        'common_objective':common,'weighted_role_rehearsal':weight*rehearsal,'total':total},receipt


def build_checkpoint(parent_payload, training_rows, tuning_rows, pairs, aux_rows, aux_pairs, aux_blocks, *, parent_kind, objective, seed,
                     learning_rate=.00025, batch_size=12):
    _parent_runtime(parent_kind).validate_checkpoint(parent_payload)
    parent = copy.deepcopy(parent_payload)
    _require(parent["progress"]["optimizer_steps"] > 0 and parent["model_config"]["seed"] == seed, "trained same-seed facet parent required")
    _auxiliary_data(training_rows,tuning_rows,aux_rows,aux_pairs,aux_blocks)
    pools = _pairs_and_pools(training_rows, pairs)
    counts = {name: len(pool) for name, pool in pools.items()}
    config = _training_config(objective, seed, learning_rate, batch_size)
    return {"schema": SCHEMA, "lineage_id": LINEAGE_ID, "implementation": _implementation(),
        "frozen_parent_kind":parent_kind,
        "auxiliary_manifest_sha256":checkpoint_digest(aux_rows),"auxiliary_pairs_sha256":checkpoint_digest(aux_pairs),
        "auxiliary_blocks_sha256":checkpoint_digest(aux_blocks),"auxiliary_count":len(aux_rows),
        "auxiliary_pair_count":len(aux_pairs),"auxiliary_block_count":len(aux_blocks),
        "frozen_parent_checkpoint": parent, "frozen_parent_checkpoint_sha256": checkpoint_digest(parent),
        "frozen_parent_optimizer_steps": parent["progress"]["optimizer_steps"],
        "model_config": copy.deepcopy(parent["model_config"]), "training_config": config,
        "initial_model_state_sha256": checkpoint_digest(parent["model_state"]),
        "training_manifest_sha256": checkpoint_digest(training_rows), "tuning_manifest_sha256": checkpoint_digest(tuning_rows),
        "pair_manifest_sha256": checkpoint_digest(pairs), "training_count": len(training_rows), "tuning_count": len(tuning_rows),
        "pool_counts": counts, "model_state": copy.deepcopy(parent["model_state"]),
        "optimizer_state": {"schema": "adam-default-betas-eps/v1", "parameters": {}},
        "progress": _progress(counts,len(aux_blocks),seed), "parent_checkpoint_sha256": None, **FALSE}


def _restore(checkpoint):
    import torch
    fields = {"schema", "lineage_id", "implementation", "frozen_parent_checkpoint", "frozen_parent_checkpoint_sha256",
        "frozen_parent_optimizer_steps", "frozen_parent_kind", "auxiliary_manifest_sha256", "auxiliary_pairs_sha256",
        "auxiliary_blocks_sha256", "auxiliary_count", "auxiliary_pair_count", "auxiliary_block_count", "model_config", "training_config", "initial_model_state_sha256",
        "training_manifest_sha256", "tuning_manifest_sha256", "pair_manifest_sha256", "training_count", "tuning_count",
        "pool_counts", "model_state", "optimizer_state", "progress", "parent_checkpoint_sha256", *FALSE}
    _require(type(checkpoint) is dict and set(checkpoint) == fields, "closed role/span rehearsal checkpoint required")
    _require(checkpoint["schema"] == SCHEMA and checkpoint["lineage_id"] == LINEAGE_ID and
             all(checkpoint[key] is False for key in FALSE), "role/span rehearsal schema/authority differs")
    _require(len(_raw(checkpoint)) <= MAX_BYTES, "checkpoint exceeds byte bound")
    _require(checkpoint["implementation"] == _implementation(), "role/span rehearsal implementation source drift")
    parent = checkpoint["frozen_parent_checkpoint"]
    _parent_runtime(checkpoint['frozen_parent_kind']).validate_checkpoint(parent)
    _require(checkpoint["frozen_parent_checkpoint_sha256"] == checkpoint_digest(parent), "facet parent hash differs")
    _require(type(checkpoint["frozen_parent_optimizer_steps"]) is int and
             checkpoint["frozen_parent_optimizer_steps"] == parent["progress"]["optimizer_steps"] > 0, "parent update count differs")
    config, model_config = checkpoint["training_config"], checkpoint["model_config"]
    _require(type(config) is dict and {"objective", "seed", "learning_rate", "batch_size"} <= set(config), "incomplete training config")
    _require(_raw(config) == _raw(_training_config(**{k: config[k] for k in ("objective", "seed", "learning_rate", "batch_size")})),
             "training config differs")
    _require(_raw(model_config) == _raw(parent["model_config"]) and config["seed"] == model_config["seed"], "frozen model config differs")
    _require(checkpoint["initial_model_state_sha256"] == checkpoint_digest(parent["model_state"]), "initial weights differ")
    for name in ("training_manifest_sha256", "tuning_manifest_sha256", "pair_manifest_sha256",
                 "auxiliary_manifest_sha256", "auxiliary_pairs_sha256", "auxiliary_blocks_sha256"):
        _require(type(checkpoint[name]) is str and span._SHA.fullmatch(checkpoint[name]), "invalid manifest hash")
    count, tuning_count, counts = checkpoint["training_count"], checkpoint["tuning_count"], checkpoint["pool_counts"]
    _require(type(count) is int and 1 <= count <= span.MAX_EXAMPLES and type(tuning_count) is int and
             0 <= tuning_count <= span.MAX_EXAMPLES, "invalid split counts")
    aux_count,aux_pairs,aux_blocks=(checkpoint[k] for k in ("auxiliary_count","auxiliary_pair_count","auxiliary_block_count"))
    _require(all(type(n) is int for n in (aux_count,aux_pairs,aux_blocks)) and 4<=aux_count<=MAX_AUXILIARY_EXAMPLES
        and aux_count==2*aux_pairs==4*aux_blocks,"invalid separate auxiliary counts")
    _require(type(counts) is dict and set(counts) == set(POOLS) and
             all(type(n) is int and 2 <= n <= span.MAX_EXAMPLES for n in counts.values()) and
             counts["earlier"] >= 6 and counts["historical_new"] >= 3 and
             counts["positive_pairs"] == counts["negative_pairs"] and
             counts["earlier"] + counts["historical_new"] + 2 * (counts["positive_pairs"] + counts["negative_pairs"]) == count,
             "invalid pool counts")
    progress = checkpoint["progress"]
    _require(type(progress) is dict and type(progress.get("optimizer_steps")) is int and
             0 <= progress["optimizer_steps"] <= 200, "invalid optimizer progress")
    steps = progress["optimizer_steps"]
    _require(_raw(progress) == _raw(_progress(counts,aux_blocks,config["seed"],steps)), "deterministic sampler progress differs")
    preceding_hash = checkpoint["parent_checkpoint_sha256"]
    _require(preceding_hash is None or type(preceding_hash) is str and span._SHA.fullmatch(preceding_hash), "invalid preceding checkpoint hash")
    if steps == 0:
        _require(checkpoint["model_state"] == parent["model_state"] and preceding_hash is None, "zero-update weights differ")
    else:
        _require(preceding_hash is not None, "trained checkpoint lacks preceding hash")
    model = mixed._model(torch, model_config)
    template, weights = model.state_dict(), checkpoint["model_state"]
    _require(type(weights) is dict and set(weights) == set(template), "model state keys differ")
    model.load_state_dict({k: span._tensor(torch, weights[k], v.shape, k) for k, v in template.items()}, strict=True)
    optimizer = torch.optim.Adam(model.parameters(), lr=config["learning_rate"], foreach=False)
    state, parameters = checkpoint["optimizer_state"], dict(model.named_parameters())
    _require(type(state) is dict and set(state) == {"schema", "parameters"} and state["schema"] == "adam-default-betas-eps/v1"
             and type(state["parameters"]) is dict, "unsupported optimizer state")
    _require(set(state["parameters"]) == (set(parameters) if steps else set()), "optimizer parameter keys differ")
    for name, moment in state["parameters"].items():
        _require(type(moment) is dict and set(moment) == {"step", "exp_avg", "exp_avg_sq"} and
                 type(moment["step"]) is int and moment["step"] == steps, "optimizer step differs")
        parameter = parameters[name]
        optimizer.state[parameter] = {"step": torch.tensor(float(steps)),
            "exp_avg": span._tensor(torch, moment["exp_avg"], parameter.shape, name),
            "exp_avg_sq": span._tensor(torch, moment["exp_avg_sq"], parameter.shape, name, nonnegative=True)}
    model.eval()
    return torch, model, optimizer


def validate_checkpoint(checkpoint):
    _restore(checkpoint)


def optimizer_steps(checkpoint):
    validate_checkpoint(checkpoint)
    return checkpoint["progress"]["optimizer_steps"]


def train_decoder(checkpoint, training_rows, tuning_rows, pairs, aux_rows, aux_pairs, aux_blocks, *, max_steps=100, max_seconds=600):
    _require(type(max_steps) is int and 0 <= max_steps <= 200, "max_steps must be in0..200")
    _require(type(max_seconds) in (int, float) and math.isfinite(max_seconds) and 0 <= max_seconds <= 3600,
             "max_seconds must be in0..3600")
    started = time.monotonic()
    torch, model, optimizer = _restore(checkpoint)
    for key, value in (("training_manifest_sha256", training_rows), ("tuning_manifest_sha256", tuning_rows), ("pair_manifest_sha256", pairs),
        ("auxiliary_manifest_sha256",aux_rows),("auxiliary_pairs_sha256",aux_pairs),("auxiliary_blocks_sha256",aux_blocks)):
        _require(checkpoint[key] == checkpoint_digest(value), "resume manifest differs: " + key)
    records,_,auxiliary_records,block_rows=_auxiliary_data(training_rows,tuning_rows,aux_rows,aux_pairs,aux_blocks)
    _require((checkpoint['auxiliary_count'],checkpoint['auxiliary_pair_count'],checkpoint['auxiliary_block_count'])
        == (len(aux_rows),len(aux_pairs),len(aux_blocks)), 'resume auxiliary counts differ')
    aux_by_id={r["id"]:r for r in auxiliary_records}
    pools, by_id = _pairs_and_pools(training_rows, pairs), {row["id"]: row for row in records}
    counts, config, model_config = checkpoint["pool_counts"], checkpoint["training_config"], checkpoint["model_config"]
    _require(counts == {k: len(v) for k, v in pools.items()}, "resume pool counts differ")
    progress = copy.deepcopy(checkpoint["progress"])
    _require(progress["optimizer_steps"] + max_steps <= 200, "optimizer step budget exceeded")
    teacher = mixed._model(torch, model_config)
    teacher.load_state_dict({k: span._tensor(torch, checkpoint["frozen_parent_checkpoint"]["model_state"][k], v.shape, k)
        for k, v in teacher.state_dict().items()}, strict=True)
    teacher.eval(); teacher.requires_grad_(False)
    teacher_hash = mixed._state_digest(teacher)
    losses, components, exposures, auxiliary_receipts, maximum_gradient, reason = [], [], [], [], 0., "step_limit"
    auxiliary_gradients = {prefix[:-1]: 0. for prefix in mixed._EXTRA}
    for _ in range(max_steps):
        if time.monotonic() >= started + max_seconds:
            reason = "deadline_before_batch"
            break
        indices, advanced = next_batch_indices(progress,counts,len(aux_blocks),config["seed"])
        chosen_pairs = [pools[name][i] for name in POOLS[2:] for i in indices[name]]
        ids = [pools[name][i] for name in POOLS[:2] for i in indices[name]] + [i for pair in chosen_pairs for i in pair]
        batch = [by_id[i] for i in ids]
        block_index=indices['auxiliary_block'][0]
        auxiliary_ids=block_rows[block_index]
        auxiliary_batch=[aux_by_id[i] for i in auxiliary_ids]
        model.train()
        optimizer.zero_grad(set_to_none=True)
        loss,parts,aux_receipt=_loss(torch,model,teacher,batch,auxiliary_batch,model_config,config["objective"])
        _require(bool(torch.isfinite(loss)), "nonfinite training loss")
        loss.backward()
        parameters = list(model.parameters())
        _require(all(p.grad is not None and bool(torch.isfinite(p.grad).all()) for p in parameters), "missing/nonfinite gradients")
        for prefix in mixed._EXTRA:
            gradients = [p.grad.flatten() for name, p in model.named_parameters() if name.startswith(prefix)]
            norm = float(torch.linalg.vector_norm(torch.cat(gradients)))
            auxiliary_gradients[prefix[:-1]] = max(auxiliary_gradients[prefix[:-1]], norm)
        clipped = parameters if model_config["trigger_enabled"] else [p for name, p in model.named_parameters() if not name.startswith(mixed._EXTRA)]
        norm = torch.nn.utils.clip_grad_norm_(clipped, 5., error_if_nonfinite=True)
        maximum_gradient = max(maximum_gradient, float(norm))
        optimizer.step()
        _require(all(bool(torch.isfinite(p).all()) for p in parameters), "nonfinite updated weights")
        _require(all(bool(torch.isfinite(v).all()) for moment in optimizer.state.values() for v in moment.values()
                     if torch.is_tensor(v)), "nonfinite optimizer moments")
        progress = advanced
        losses.append(float(loss.detach()))
        components.append({**{k: float(v.detach()) for k, v in parts.items()}, "domain_rows": {"earlier": 3, "new": 9},
            "supervised_trigger_rows": 9, "trigger_loss_rows": 9 if model_config["trigger_enabled"] else 0,
            "pair_count": 3, "consistency_weight": config["consistency_weight"],
            "teacher_weight": config["teacher_weight"], "overlap_weight": config["overlap_weight"],
            "auxiliary_standard_ce_weight":.25,"role_rehearsal_weight":config["role_rehearsal_weight"],"auxiliary_rows":4})
        exposures.append({"optimizer_step": progress["optimizer_steps"], "indices_by_pool": indices,
            "ids":ids,"pairs":chosen_pairs,"auxiliary_ids":auxiliary_ids,
            "auxiliary_block_id":aux_blocks[block_index]["block_id"],"auxiliary_pair_ids":aux_blocks[block_index]["pair_ids"]})
        auxiliary_receipts.append({"optimizer_step":progress["optimizer_steps"],**aux_receipt})
    model.eval()
    _require(mixed._state_digest(teacher) == teacher_hash and all(p.grad is None for p in teacher.parameters()),
        "frozen teacher changed or received gradients")
    weights, moments = span._pack(model, optimizer)
    result = ({**copy.deepcopy(checkpoint), "model_state": weights, "optimizer_state": moments, "progress": progress,
               "parent_checkpoint_sha256": checkpoint_digest(checkpoint)} if losses else copy.deepcopy(checkpoint))
    _require(_implementation() == checkpoint["implementation"], "implementation changed during training")
    _require(len(_raw(result)) <= MAX_BYTES, "checkpoint exceeds byte bound")
    return {"checkpoint": result, "report": {"schema": "role-span-rehearsal-training/v1",
        "checkpoint_sha256": checkpoint_digest(result), "frozen_parent_checkpoint_sha256": checkpoint["frozen_parent_checkpoint_sha256"],
        "frozen_parent_optimizer_steps": checkpoint["frozen_parent_optimizer_steps"], "optimizer_steps": len(losses),
        "new_optimizer_steps_total": progress["optimizer_steps"], "training_executed": bool(losses),
        "objective": config["objective"], "batch_losses": losses, "batch_loss_components": components, "batch_exposures": exposures,
        "domain_exposures": {"earlier": 3 * len(losses), "new": 9 * len(losses)}, "pair_exposures": 3 * len(losses),
        "auxiliary_source_exposures":4*len(losses),"auxiliary_block_exposures":len(losses),
        "auxiliary_loss_receipts":auxiliary_receipts,"auxiliary_manifest_sha256":checkpoint["auxiliary_manifest_sha256"],
        "auxiliary_pairs_sha256":checkpoint["auxiliary_pairs_sha256"],"auxiliary_blocks_sha256":checkpoint["auxiliary_blocks_sha256"],
        "frozen_parent_kind":checkpoint["frozen_parent_kind"],
        "auxiliary_gradient_norm_max": auxiliary_gradients, "gradient_norm_max": maximum_gradient,
        "changed_parameter_names": [k for k in weights if weights[k] != checkpoint["model_state"][k]],
        "stopped_reason": reason, "elapsed_seconds": time.monotonic() - started,
        "deadline_scope": "soft_boundary_before_numeric_batch; initialization_and_serialization_not_interruptible",
        "tuning_used_for_fit": False, "teacher_training_labels_only": True,
        "teacher_state_unchanged": True, "teacher_gradients_disabled": True,
        "teacher_state_sha256_before":teacher_hash,"teacher_state_sha256_after":mixed._state_digest(teacher),
        "optimizer_trajectory_independently_replayed":False, **FALSE}}


class RoleSpanRehearsalDecoder:
    def __init__(self, checkpoint):
        self.torch, self.model, _ = _restore(checkpoint)
        self._checkpoint_bytes = _raw(checkpoint)
        self.checkpoint_sha256 = hashlib.sha256(self._checkpoint_bytes).hexdigest()
        self._frozen_parent_sha256 = checkpoint["frozen_parent_checkpoint_sha256"]
        self._frozen_parent_kind = checkpoint["frozen_parent_kind"]
        self._implementation_snapshot = _raw(checkpoint["implementation"])
        self._expected_model_sha256 = mixed._state_digest(self.model)
        view = object.__new__(mixed._InferenceView)
        view.torch, view.model = self.torch, self.model
        view._checkpoint = MappingProxyType({"config": MappingProxyType({"latent_enabled": False,
            "trigger_enabled": checkpoint["model_config"]["trigger_enabled"]})})
        self._inference_view, self._inference_config = view, view._checkpoint

    @property
    def checkpoint(self):
        return json.loads(self._checkpoint_bytes)

    def decode_formal_logic(self, texts, *, trigger_ablation="none"):
        _require(type(texts) in (list, tuple) and 1 <= len(texts) <= 128 and all(type(t) is str for t in texts), "one to128 source strings required")
        _require(trigger_ablation in ("none", "disabled"), "unsupported trigger ablation")
        _require(_raw(_implementation()) == self._implementation_snapshot, "implementation source drift")
        _require(hashlib.sha256(self._checkpoint_bytes).hexdigest() == self.checkpoint_sha256, "owned inference checkpoint changed")
        _require(self._inference_view.model is self.model and self._inference_view._checkpoint is self._inference_config,
                 "inference snapshot changed")
        before = mixed._state_digest(self.model)
        _require(before == self._expected_model_sha256, "inference model state changed")
        rows = [self._inference_view._decode(text, [], enabled=trigger_ablation != "disabled") for text in texts]
        _require(before == mixed._state_digest(self.model), "inference model state changed")
        _require(_raw(_implementation()) == self._implementation_snapshot, "implementation changed during inference")
        count = sum(row["status"] == "decoded" for row in rows)
        return {"schema": "role-span-rehearsal-inference/v1", "lineage_id": LINEAGE_ID,
            "checkpoint_sha256": self.checkpoint_sha256, "frozen_parent_checkpoint_sha256": self._frozen_parent_sha256,"frozen_parent_kind":self._frozen_parent_kind,
            "rows": rows, "decoded_count": count, "status": "decoded" if count == len(rows) else "partial" if count else "abstained",
            "trigger_ablation": trigger_ablation, "target_access": False, "teacher_forcing": False,
            "training_executed": False, "model_state_unchanged": True, **FALSE}


def save_checkpoint(checkpoint, path):
    validate_checkpoint(checkpoint)
    raw, path = _raw(checkpoint), Path(path).absolute()
    _require(path.parent.resolve(strict=True) == path.parent, "canonical existing checkpoint parent required")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw), "schema": SCHEMA}


def load_checkpoint(path, *, expected_sha256):
    _require(type(expected_sha256) is str and span._SHA.fullmatch(expected_sha256), "expected checkpoint hash required")
    path = Path(path).absolute()
    _require(path.resolve(strict=True) == path, "canonical checkpoint path required")
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        before = os.fstat(stream.fileno())
        _require(stat.S_ISREG(before.st_mode) and before.st_size <= MAX_BYTES, "bounded regular checkpoint required")
        raw = stream.read(MAX_BYTES + 1)
        after = os.fstat(stream.fileno())
    _require(len(raw) <= MAX_BYTES and (before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns), "checkpoint changed while reading")
    _require(hashlib.sha256(raw).hexdigest() == expected_sha256, "checkpoint hash differs")
    def unique(pairs):
        result = {}
        for key, value in pairs:
            _require(key not in result, "duplicate checkpoint JSON key")
            result[key] = value
        return result
    def reject(value):
        raise ValueError("invalid JSON constant: " + value)
    checkpoint = json.loads(raw, object_pairs_hook=unique, parse_constant=reject)
    validate_checkpoint(checkpoint)
    return checkpoint
