"""Matched condition rehearsal from immutable heterogeneous pretrained parents.

The common objective and main batches are unchanged. Both arms forward identical
training-only hard examples; treatment alone adds balanced condition CE. Mining
uses fixed parent predictions and admitted TRAIN labels, never tuning or tests.
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
SCHEMA = "scope-retention-span-checkpoint/v1"
LINEAGE_ID = "scope_retention_span_v1"
MAX_BYTES = mixed.MAX_BYTES
POOLS = ("earlier", "historical_new", "positive_pairs", "negative_pairs")
PAIR_POSITIONS = ((6, 7), (8, 9), (10, 11))
ROLE_NAMES = (*span.SPAN_FIELDS, "trigger", "other")


def _capture_implementation():
    return {"scope_retention_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "frozen_temporal": temporal._implementation()}


_IMPLEMENTATION_AT_IMPORT = _capture_implementation()


def _implementation():
    value = _capture_implementation()
    _require(value == _IMPLEMENTATION_AT_IMPORT, "scope retention implementation source drift")
    return value


def _training_config(objective, seed, learning_rate=.00025, batch_size=12):
    _require(objective in ('base','condition_rehearsal'), 'known matched training objective required')
    _require(type(learning_rate) in (int,float) and learning_rate == .00025,'learning rate must be .00025')
    config=temporal._training_config('base',seed,.0005,batch_size)
    config.pop('temporal_presence_weight'); config.pop('temporal_presence_profile')
    return {**config,'objective':objective,'learning_rate':float(learning_rate),'optimizer_step_budget':200,
        'condition_weight':.5 if objective=='condition_rehearsal' else 0.,
        'condition_profile':'half_balanced_presence_plus_half_present_endpoint_CE_rehearsal_only/v1',
        'rehearsal_rows':4,'rehearsal_class_quota':2,'hard_examples_per_class':64,
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


def _aux_order(seed, label, epoch):
    order=list(range(64));random.Random(f'condition-rehearsal/v1:{seed}:{label}:{epoch}').shuffle(order);return order


def _progress(counts, seed, steps=0):
    progress=temporal._progress(counts,seed,steps)
    epoch,cursor=divmod(2*steps,64)
    progress['rehearsal_pools']={label:{'epochs_completed':epoch,'row_cursor':cursor,
        'shuffle_order':_aux_order(seed,label,epoch)} for label in ('positive','negative')}
    return progress


def next_batch_indices(progress, counts, seed):
    selected,updated=temporal.next_batch_indices(progress,counts,seed)
    for label in ('positive','negative'):
        state=updated['rehearsal_pools'][label];indices=[]
        for _ in range(2):
            indices.append(state['shuffle_order'][state['row_cursor']]);state['row_cursor']+=1
            if state['row_cursor']==64:
                state['epochs_completed']+=1;state['row_cursor']=0
                state['shuffle_order']=_aux_order(seed,label,state['epochs_completed'])
        selected['rehearsal_'+label]=indices
    return selected,updated


def _condition_row_loss(torch, output, record, index):
    optional=span.OPTIONAL_FIELDS.index('conditions');facet_index=span.SPAN_FIELDS.index('conditions')
    present=bool(record['labels']['presence'][facet_index]);device=output['presence'].device
    presence=torch.nn.functional.cross_entropy(output['presence'][index,optional],torch.tensor(int(present),device=device))
    endpoints=output['modality'][index].sum()*0
    if present:
        count=len(record['tokens']);start,end=record['labels']['spans'][facet_index]
        endpoints=(torch.nn.functional.cross_entropy(output['start'][index,facet_index,:count],torch.tensor(start,device=device))+
            torch.nn.functional.cross_entropy(output['end'][index,facet_index,:count],torch.tensor(end,device=device)))*.5
    return present,presence,endpoints


def _condition_rehearsal_loss(torch, output, records):
    _require(len(records)==4,'exactly four auxiliary rehearsal rows required')
    groups={False:[],True:[]};endpoints=[]
    for i,record in enumerate(records):
        present,presence,span_loss=_condition_row_loss(torch,output,record,i)
        groups[present].append(presence)
        if present:endpoints.append(span_loss)
    _require(len(groups[True])==len(groups[False])==2,'two condition-present and two condition-absent rehearsal rows required')
    negative,positive=(torch.stack(groups[label]).mean() for label in (False,True))
    balanced=(negative+positive)*.5;endpoint=torch.stack(endpoints).mean()
    result=(balanced+endpoint)*.5;zero=output['modality'].sum().detach()*0
    return result,{'condition_positive_ce':positive,'condition_negative_ce':negative,
        'condition_balanced_presence_ce':balanced,'condition_present_endpoint_ce':endpoint,
        'condition_rehearsal_ce':result,'condition_positive_rows':zero+2,'condition_negative_rows':zero+2}


def mine_condition_hard_examples(parent_payload, parent_kind, training_rows):
    """All4080 production rows are scored; helper permits smaller bounded test inventories."""
    module=_parent_runtime(parent_kind);torch,teacher,_=module._restore(parent_payload)
    records,_=mixed._splits(training_rows,[]);teacher.eval();teacher.requires_grad_(False)
    before=mixed._state_digest(teacher);scores=[]
    with torch.no_grad():
        for offset in range(0,len(records),48):
            batch=records[offset:offset+48];output=teacher(*span._batch(torch,batch))
            for i,record in enumerate(batch):
                present,presence,endpoints=_condition_row_loss(torch,output,record,i)
                a,b=float(presence),float(endpoints)
                scores.append({'id':record['id'],'source_sha256':hashlib.sha256(training_rows[offset+i]['source_text'].encode()).hexdigest(),
                    'condition_present':present,'condition_presence_ce':a,'condition_endpoint_ce':b,'condition_loss_sum':a+b})
    _require(before==mixed._state_digest(teacher) and all(p.grad is None for p in teacher.parameters()),'mining parent mutated')
    selected={label:[r['id'] for r in sorted((r for r in scores if r['condition_present'] is present),
        key=lambda r:(-r['condition_loss_sum'],r['id']))[:64]] for present,label in ((True,'positive'),(False,'negative'))}
    manifest={'schema':'training-only-condition-hard-mining/v1','parent_kind':parent_kind,
        'parent_checkpoint_sha256':checkpoint_digest(parent_payload),'training_manifest_sha256':checkpoint_digest(training_rows),
        'mining_batch_size':48,'score_rows':scores,'selected_ids':selected,'selected_count_per_class':64,
        'ranking':'descending_presence_plus_present_mean_endpoint_CE_then_ascending_id/v1',
        'training_labels_only':True,'tuning_or_test_used':False,'model_state_unchanged':True}
    _validate_mining(manifest,parent_payload,parent_kind,training_rows)
    return manifest


def _validate_mining(manifest, parent, kind, training_rows=None):
    fields={'schema','parent_kind','parent_checkpoint_sha256','training_manifest_sha256','mining_batch_size','score_rows',
        'selected_ids','selected_count_per_class','ranking','training_labels_only','tuning_or_test_used','model_state_unchanged'}
    _require(type(manifest) is dict and set(manifest)==fields and manifest['schema']=='training-only-condition-hard-mining/v1',
        'closed training-only mining manifest required')
    _require(manifest['parent_kind']==kind and manifest['parent_checkpoint_sha256']==checkpoint_digest(parent),
        'mining parent binding differs')
    _require(type(manifest['training_manifest_sha256']) is str and span._SHA.fullmatch(manifest['training_manifest_sha256'])
        and manifest['mining_batch_size']==48 and manifest['selected_count_per_class']==64
        and manifest['ranking']=='descending_presence_plus_present_mean_endpoint_CE_then_ascending_id/v1'
        and manifest['training_labels_only'] is manifest['model_state_unchanged'] is True and manifest['tuning_or_test_used'] is False,
        'mining provenance/profile differs')
    scores=manifest['score_rows'];_require(type(scores) is list and 128<=len(scores)<=span.MAX_EXAMPLES,'bounded complete mining rows required')
    _require(len({r['id'] for r in scores})==len(scores),'duplicate mining IDs')
    for row in scores:
        _require(type(row) is dict and set(row)=={'id','source_sha256','condition_present','condition_presence_ce','condition_endpoint_ce','condition_loss_sum'}
            and type(row['id']) is str and type(row['source_sha256']) is str and span._SHA.fullmatch(row['source_sha256'])
            and type(row['condition_present']) is bool,'closed mining score row required')
        _require(all(type(row[k]) in (int,float) and math.isfinite(row[k]) and row[k]>=0
            for k in ('condition_presence_ce','condition_endpoint_ce','condition_loss_sum'))
            and row['condition_loss_sum']==row['condition_presence_ce']+row['condition_endpoint_ce']
            and (row['condition_present'] or row['condition_endpoint_ce']==0),'invalid condition mining loss')
    selected={label:[r['id'] for r in sorted((r for r in scores if r['condition_present'] is present),
        key=lambda r:(-r['condition_loss_sum'],r['id']))[:64]] for present,label in ((True,'positive'),(False,'negative'))}
    _require(all(len(v)==64 for v in selected.values()) and manifest['selected_ids']==selected,'hard mining rank or class inventory differs')
    if training_rows is not None:
        _require(manifest['training_manifest_sha256']==checkpoint_digest(training_rows) and len(scores)==len(training_rows),'mining training binding differs')
        for score,row in zip(scores,training_rows,strict=True):
            _require(score['id']==row['id'] and score['source_sha256']==hashlib.sha256(row['source_text'].encode()).hexdigest()
                and score['condition_present'] is bool(row['canonical_ir']['rules'][0]['conditions']),'mining source/condition label differs')


def _loss(torch, model, teacher, records, rehearsal_records, model_config, objective):
    _require(objective in ('base','condition_rehearsal'),'known matched training objective required')
    batch=span._batch(torch,records);output=model(*batch)
    with torch.no_grad():teacher_output=teacher(*batch)
    base,parts=previous._loss(torch,lambda *_:output,records,model_config,'consistency')
    preservation,teacher_parts=_teacher_loss(torch,output,teacher_output,records)
    overlap,overlap_parts=_overlap_loss(torch,output,records)
    rehearsal_output=model(*span._batch(torch,rehearsal_records))
    rehearsal,rehearsal_parts=_condition_rehearsal_loss(torch,rehearsal_output,rehearsal_records)
    common=base+.5*preservation+.1*overlap;weight=.5 if objective=='condition_rehearsal' else 0.
    total=common+weight*rehearsal
    return total,{**parts,**teacher_parts,**overlap_parts,**rehearsal_parts,'base_objective':base,
        'teacher_kl':preservation,'span_overlap':overlap,'weighted_teacher':.5*preservation,'weighted_overlap':.1*overlap,
        'common_objective':common,'weighted_condition_rehearsal':weight*rehearsal,'total':total}


def build_checkpoint(parent_payload, training_rows, tuning_rows, pairs, mining, *, parent_kind, objective, seed,
                     learning_rate=.00025, batch_size=12):
    _parent_runtime(parent_kind).validate_checkpoint(parent_payload)
    _validate_mining(mining,parent_payload,parent_kind,training_rows)
    parent = copy.deepcopy(parent_payload)
    _require(parent["progress"]["optimizer_steps"] > 0 and parent["model_config"]["seed"] == seed, "trained same-seed facet parent required")
    mixed._splits(training_rows, tuning_rows)
    pools = _pairs_and_pools(training_rows, pairs)
    counts = {name: len(pool) for name, pool in pools.items()}
    config = _training_config(objective, seed, learning_rate, batch_size)
    return {"schema": SCHEMA, "lineage_id": LINEAGE_ID, "implementation": _implementation(),
        "frozen_parent_kind":parent_kind,"hard_mining":copy.deepcopy(mining),"hard_mining_sha256":checkpoint_digest(mining),
        "frozen_parent_checkpoint": parent, "frozen_parent_checkpoint_sha256": checkpoint_digest(parent),
        "frozen_parent_optimizer_steps": parent["progress"]["optimizer_steps"],
        "model_config": copy.deepcopy(parent["model_config"]), "training_config": config,
        "initial_model_state_sha256": checkpoint_digest(parent["model_state"]),
        "training_manifest_sha256": checkpoint_digest(training_rows), "tuning_manifest_sha256": checkpoint_digest(tuning_rows),
        "pair_manifest_sha256": checkpoint_digest(pairs), "training_count": len(training_rows), "tuning_count": len(tuning_rows),
        "pool_counts": counts, "model_state": copy.deepcopy(parent["model_state"]),
        "optimizer_state": {"schema": "adam-default-betas-eps/v1", "parameters": {}},
        "progress": _progress(counts, seed), "parent_checkpoint_sha256": None, **FALSE}


def _restore(checkpoint):
    import torch
    fields = {"schema", "lineage_id", "implementation", "frozen_parent_checkpoint", "frozen_parent_checkpoint_sha256",
        "frozen_parent_optimizer_steps", "frozen_parent_kind", "hard_mining", "hard_mining_sha256", "model_config", "training_config", "initial_model_state_sha256",
        "training_manifest_sha256", "tuning_manifest_sha256", "pair_manifest_sha256", "training_count", "tuning_count",
        "pool_counts", "model_state", "optimizer_state", "progress", "parent_checkpoint_sha256", *FALSE}
    _require(type(checkpoint) is dict and set(checkpoint) == fields, "closed scope retention checkpoint required")
    _require(checkpoint["schema"] == SCHEMA and checkpoint["lineage_id"] == LINEAGE_ID and
             all(checkpoint[key] is False for key in FALSE), "scope retention schema/authority differs")
    _require(len(_raw(checkpoint)) <= MAX_BYTES, "checkpoint exceeds byte bound")
    _require(checkpoint["implementation"] == _implementation(), "scope retention implementation source drift")
    parent = checkpoint["frozen_parent_checkpoint"]
    _parent_runtime(checkpoint['frozen_parent_kind']).validate_checkpoint(parent)
    _validate_mining(checkpoint['hard_mining'],parent,checkpoint['frozen_parent_kind'])
    _require(checkpoint['hard_mining_sha256']==checkpoint_digest(checkpoint['hard_mining'])
        and checkpoint['hard_mining']['training_manifest_sha256']==checkpoint['training_manifest_sha256'], 'hard mining binding differs')
    _require(checkpoint["frozen_parent_checkpoint_sha256"] == checkpoint_digest(parent), "facet parent hash differs")
    _require(type(checkpoint["frozen_parent_optimizer_steps"]) is int and
             checkpoint["frozen_parent_optimizer_steps"] == parent["progress"]["optimizer_steps"] > 0, "parent update count differs")
    config, model_config = checkpoint["training_config"], checkpoint["model_config"]
    _require(type(config) is dict and {"objective", "seed", "learning_rate", "batch_size"} <= set(config), "incomplete training config")
    _require(_raw(config) == _raw(_training_config(**{k: config[k] for k in ("objective", "seed", "learning_rate", "batch_size")})),
             "training config differs")
    _require(_raw(model_config) == _raw(parent["model_config"]) and config["seed"] == model_config["seed"], "frozen model config differs")
    _require(checkpoint["initial_model_state_sha256"] == checkpoint_digest(parent["model_state"]), "initial weights differ")
    for name in ("training_manifest_sha256", "tuning_manifest_sha256", "pair_manifest_sha256"):
        _require(type(checkpoint[name]) is str and span._SHA.fullmatch(checkpoint[name]), "invalid manifest hash")
    count, tuning_count, counts = checkpoint["training_count"], checkpoint["tuning_count"], checkpoint["pool_counts"]
    _require(type(count) is int and 1 <= count <= span.MAX_EXAMPLES and type(tuning_count) is int and
             0 <= tuning_count <= span.MAX_EXAMPLES and count == len(checkpoint["hard_mining"]["score_rows"]), "invalid split counts")
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
    _require(_raw(progress) == _raw(_progress(counts, config["seed"], steps)), "deterministic sampler progress differs")
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


def train_decoder(checkpoint, training_rows, tuning_rows, pairs, *, max_steps=200, max_seconds=600):
    _require(type(max_steps) is int and 0 <= max_steps <= 200, "max_steps must be in0..200")
    _require(type(max_seconds) in (int, float) and math.isfinite(max_seconds) and 0 <= max_seconds <= 3600,
             "max_seconds must be in0..3600")
    started = time.monotonic()
    torch, model, optimizer = _restore(checkpoint)
    for key, value in (("training_manifest_sha256", training_rows), ("tuning_manifest_sha256", tuning_rows), ("pair_manifest_sha256", pairs)):
        _require(checkpoint[key] == checkpoint_digest(value), "resume manifest differs: " + key)
    records, _ = mixed._splits(training_rows, tuning_rows)
    _validate_mining(checkpoint["hard_mining"],checkpoint["frozen_parent_checkpoint"],checkpoint["frozen_parent_kind"],training_rows)
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
    losses, components, exposures, maximum_gradient, reason = [], [], [], 0., "step_limit"
    auxiliary_gradients = {prefix[:-1]: 0. for prefix in mixed._EXTRA}
    for _ in range(max_steps):
        if time.monotonic() >= started + max_seconds:
            reason = "deadline_before_batch"
            break
        indices, advanced = next_batch_indices(progress, counts, config["seed"])
        chosen_pairs = [pools[name][i] for name in POOLS[2:] for i in indices[name]]
        ids = [pools[name][i] for name in POOLS[:2] for i in indices[name]] + [i for pair in chosen_pairs for i in pair]
        batch = [by_id[i] for i in ids]
        rehearsal_ids=[checkpoint['hard_mining']['selected_ids'][label][i] for label in ('positive','negative')
            for i in indices['rehearsal_'+label]]
        rehearsal_records=[by_id[i] for i in rehearsal_ids]
        model.train()
        optimizer.zero_grad(set_to_none=True)
        loss, parts = _loss(torch, model, teacher, batch, rehearsal_records, model_config, config["objective"])
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
            "condition_weight":config["condition_weight"],"rehearsal_rows":4})
        exposures.append({"optimizer_step": progress["optimizer_steps"], "indices_by_pool": indices,
            "ids": ids, "pairs": chosen_pairs,"rehearsal_ids":rehearsal_ids})
    model.eval()
    _require(mixed._state_digest(teacher) == teacher_hash and all(p.grad is None for p in teacher.parameters()),
        "frozen teacher changed or received gradients")
    weights, moments = span._pack(model, optimizer)
    result = ({**copy.deepcopy(checkpoint), "model_state": weights, "optimizer_state": moments, "progress": progress,
               "parent_checkpoint_sha256": checkpoint_digest(checkpoint)} if losses else copy.deepcopy(checkpoint))
    _require(_implementation() == checkpoint["implementation"], "implementation changed during training")
    _require(len(_raw(result)) <= MAX_BYTES, "checkpoint exceeds byte bound")
    return {"checkpoint": result, "report": {"schema": "scope-retention-span-training/v1",
        "checkpoint_sha256": checkpoint_digest(result), "frozen_parent_checkpoint_sha256": checkpoint["frozen_parent_checkpoint_sha256"],
        "frozen_parent_optimizer_steps": checkpoint["frozen_parent_optimizer_steps"], "optimizer_steps": len(losses),
        "new_optimizer_steps_total": progress["optimizer_steps"], "training_executed": bool(losses),
        "objective": config["objective"], "batch_losses": losses, "batch_loss_components": components, "batch_exposures": exposures,
        "domain_exposures": {"earlier": 3 * len(losses), "new": 9 * len(losses)}, "pair_exposures": 3 * len(losses),
        "rehearsal_exposures":{"positive":2*len(losses),"negative":2*len(losses)},
        "hard_mining_sha256":checkpoint["hard_mining_sha256"],"frozen_parent_kind":checkpoint["frozen_parent_kind"],
        "auxiliary_gradient_norm_max": auxiliary_gradients, "gradient_norm_max": maximum_gradient,
        "changed_parameter_names": [k for k in weights if weights[k] != checkpoint["model_state"][k]],
        "stopped_reason": reason, "elapsed_seconds": time.monotonic() - started,
        "deadline_scope": "soft_boundary_before_numeric_batch; initialization_and_serialization_not_interruptible",
        "tuning_used_for_fit": False, "teacher_training_labels_only": True,
        "teacher_state_unchanged": True, "teacher_gradients_disabled": True, **FALSE}}


class ScopeRetentionDecoder:
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
        return {"schema": "scope-retention-span-inference/v1", "lineage_id": LINEAGE_ID,
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
