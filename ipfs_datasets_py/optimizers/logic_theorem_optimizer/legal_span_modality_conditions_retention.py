"""Modality/conditions adaptation with authenticated training-only F15 retention.

Copy42 F15 states; six modality/conditions readout tensors train,36 remain frozen.
Full-width heads preserve parent arithmetic while inactive output slices detach.
The immutable teacher raw capture and training manifest are reauthenticated at
validation. Predictions never look up teacher targets. Initial632 bit parity,
numerical gradients and scientific acceptance still need guarded qualification.
"""
from __future__ import annotations
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import stat
import sys
import time

from . import legal_span_joint_readout_retention as joint
from ipfs_datasets_py.logic.formalization.autoencoder import retained_span_score_capture as capture
from . import legal_span_actor_features as features
from . import legal_span_actor_refinement as refinement
from . import legal_span_actor_context_ranking as ranking
from . import legal_span_conditions_presence as conditions
from . import legal_span_targeted_loss as targeted
from . import legal_span_continuation as continuation
from . import legal_span_formula as span

SCHEMA = "bounded-modality-conditions-retention-adapter-checkpoint/v1"
LINEAGE_ID = "bounded_modality_conditions_retention_adapter_v1"
POLICY_SCHEMA = "bounded-modality-conditions-retention-adapter-policy/v1"
MAX_NEW_STEPS, MAX_SECONDS = 32, 32
FALSE = span.FALSE
_require, _raw, checkpoint_digest = span._require, span._raw, span.checkpoint_digest
SOURCE_ACTOR_REFINEMENT_SHA256 = "f421514dc02cb3542e7587767191aa99bd32551f145e0af4d01c47595d4d73c4"
SOURCE_ACTOR_REFINEMENT_MODEL_SHA256 = "a1bb3158f19c7b619b7d15ee7ba4887046cc7d22eebecad7b04e8a8111ac3d42"
TEACHER_CAPTURE_BYTES = 3594328
TEACHER_CAPTURE_SHA256 = "221fa2ec37fc41298f787d4dfef1d4daf60b07c4c565a1194d2097e7c538fff1"
ERROR_FIELDS = ("modality", "actor", "action", "object", "conditions", "exceptions", "temporal")
RETENTION_BLOCKS = ("actor_start", "actor_end", "modality", "conditions_start", "conditions_end", "exceptions_presence")
MAX_BYTES = 32 * 1024 * 1024
HEAD_PARAMETER_NAMES = features.HEAD_PARAMETER_NAMES
FEATURE_PARAMETER_NAMES = features.FEATURE_PARAMETER_NAMES
ORIGINAL_POINTER_NAMES = ("start.weight", "start.bias", "end.weight", "end.bias")
MODALITY_NAMES = ("modality.weight", "modality.bias")
PRESENCE_NAMES = ("presence.weight", "presence.bias")
TRAINABLE_PARAMETER_NAMES = MODALITY_NAMES + ORIGINAL_POINTER_NAMES
MODEL_PARAMETER_NAMES = refinement.MODEL_PARAMETER_NAMES
BASE_PARAMETER_NAMES = tuple(name for name in MODEL_PARAMETER_NAMES if name not in TRAINABLE_PARAMETER_NAMES)
ENCODED_WIDTH, STORED_TRAINABLE_SCALARS, ACTIVE_TRAINABLE_SCALARS = 64, 975, 325
OBJECTIVES = ("modality-conditions-retention-ce",)


def _finite_shape(value, dimensions, label, *, nonnegative=False):
    if dimensions:
        _require(type(value) is list and len(value) == dimensions[0], "exact tensor shape required: " + label)
        for child in value:
            _finite_shape(child, dimensions[1:], label, nonnegative=nonnegative)
    else:
        _require(type(value) in (int, float) and math.isfinite(value) and abs(value) <= 3.4028234663852886e38
            and (not nonnegative or value >= 0), "finite typed tensor scalar required: " + label)


def _trainable_shapes():
    return {name: ((3 if name in MODALITY_NAMES else 6, 64) if name.endswith('weight')
        else (3 if name in MODALITY_NAMES else 6,)) for name in TRAINABLE_PARAMETER_NAMES}


def _initial_state(base):
    _require(type(base) is dict and set(base)==set(MODEL_PARAMETER_NAMES), "exact trained F15 forty-two-tensor state required")
    for name,shape in _trainable_shapes().items():
        _finite_shape(base[name],shape,name)
    return copy.deepcopy(base)

def _inactive_state(state):
    return {name: [copy.deepcopy(state[name][i]) for i in _inactive_rows(name)]
            for name in TRAINABLE_PARAMETER_NAMES if _inactive_rows(name)}

def _all_zero(value):
    if type(value) is list:
        return all(_all_zero(item) for item in value)
    return type(value) in (int, float) and math.isfinite(value) and value == 0


def _partition():
    return dict(model_parameter_names=list(MODEL_PARAMETER_NAMES),trainable_parameter_names=list(TRAINABLE_PARAMETER_NAMES),
        frozen_parameter_names=list(BASE_PARAMETER_NAMES),optimizer_parameter_order=list(TRAINABLE_PARAMETER_NAMES),
        active_rows={name:list(_active_rows(name)) for name in TRAINABLE_PARAMETER_NAMES},
        inactive_rows={name:list(_inactive_rows(name)) for name in TRAINABLE_PARAMETER_NAMES if _inactive_rows(name)},
        encoded_width=64,model_tensor_count=42,trainable_tensor_count=6,frozen_tensor_count=36,
        stored_trainable_scalar_count=975,active_trainable_scalar_count=325,inactive_stored_scalar_count=650,
        full_parent_GEMM_geometry=True,all_actor_and_presence_parameters_frozen=True,feature_parameters_or_storage_shared=False)

def _policy(objective, *, seed=1729, batch_order_seed=1729, batch_size=12):
    _require(type(objective) is str and objective in OBJECTIVES, 'closed modality/conditions objective required')
    _require(type(seed) is int and seed==1729 and type(batch_order_seed) is int and batch_order_seed==1729
        and type(batch_size) is int and batch_size==12,'fixed1729/12 recipe required')
    return dict(schema=POLICY_SCHEMA,objective=objective,trainable_parameter_policy=objective,parameter_partition=_partition(),
        objective_policy=targeted._policy(seed,actor_ranking_enabled=False,presence_ce_weight=1,batch_order_seed=batch_order_seed,batch_size=batch_size),
        actor_training_count=168,optimizer=dict(name='Adam',learning_rate=.001,betas=[.9,.999],eps=1e-8,weight_decay=0.,foreach=False,gradient_clip_norm=5.),
        initialization='copy_all42_trained_F15_states_fresh_ordered6_Adam/v1',inherited_optimizer_moments=False,
        source_actor_refinement_optimizer_steps=32,frozen_parameter_gradients='None_for_all36',inactive_gradients_and_moments='exact_zero_all650',
        main_loss='(2*mean_modality_CE+sum_six_facet_batch_means)/8_legacy_association',
        conditions_row_weight=dict(selected=2,otherwise=1,scope='entire_conditions_facet_presence_plus_half_start_end',
            mask='exact_F15_nonabstaining_raw_seven_field_error_set_equals_conditions',normalization='full_batch_mean_not_sumweights',
            immutable_training_rows=168,selected_count=2,derived_before_update0=True,candidate_or_evaluation_predictions_used=False),
        actor_hinge_applied=False,actor_hinge_omitted=True,
        retention=dict(coefficient=1.,temperature=1.,blocks=list(RETENTION_BLOCKS),
            normalization='sum_masked_row_block_KL_divide_6_times_full_batch_including_masked_frozen_zeros',
            mask='training_gold_correct_per_class_or_valid_present_individual_boundary_argmax',
            teacher_checkpoint_sha256=SOURCE_ACTOR_REFINEMENT_SHA256,teacher_model_state_sha256=SOURCE_ACTOR_REFINEMENT_MODEL_SHA256,
            teacher_capture_bytes=TEACHER_CAPTURE_BYTES,teacher_capture_sha256=TEACHER_CAPTURE_SHA256,
            teacher_raw_and_training_manifest_rederived_every_validation=True,teacher_distributions_detached=True,
            teacher_model_forwards=0,wrong_teacher_blocks_masked_out=True,zero_mask_graph_connected=True,
            row_weight_mask_is_separate=True),
        initial_binary32_parity='requires_external_full632_F15_head_and_decoded_gate_before_update0',
        final_protected_heads=dict(presence=['object','conditions','exceptions','temporal'],
            boundaries=['actor','action','object','exceptions','temporal']),
        mutable_heads=['modality','conditions_start','conditions_end'],feature_paths_per_source_model_forward=3,teacher_model_forwards=0,
        max_new_optimizer_steps=32,latent_dimension=384,latent_enabled=False,evaluation_references_used=False,
        parent_ablation_only=True,strict_global_win_expected=False,automatic_selection_or_promotion=False,
        full_IR_retention_guaranteed=False,independent_legal_gold=False)

def _validate_policy(value):
    _require(type(value) is dict and "objective" in value, "closed adapter policy required")
    expected = _policy(value["objective"])
    _require(_raw(value) == _raw(expected), "adapter policy differs")
    return expected


def _capture_implementation():
    return dict(modality_conditions_retention_adapter_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        retained_teacher_and_KL=joint._implementation(),trained_actor_refinement_parent=refinement._implementation(),
        retained_greedy_capture_sha256=hashlib.sha256(Path(capture.__file__).read_bytes()).hexdigest(),
        actor_features_factory=features._implementation(),targeted_loss=targeted._implementation(),
        continuation=continuation._implementation(),span=span._implementation())


_IMPLEMENTATION_AT_IMPORT = _capture_implementation()


def _implementation():
    result = _capture_implementation()
    _require(result == _IMPLEMENTATION_AT_IMPORT, "adapter source changed since import")
    return result


def _source(source):
    return ranking._source(source)


def _training_records(training_examples, tuning_examples=()):
    _require(type(tuning_examples) in (list, tuple) and not tuning_examples, "actor tuning references prohibited")
    records, tuning = targeted._bounded_splits(training_examples, ())
    _require(not tuning and tuple(span.SPAN_FIELDS) == ("actor", "action", "object", "conditions", "exceptions", "temporal")
        and tuple(span.OPTIONAL_FIELDS) == ("object", "conditions", "exceptions", "temporal"), "exact six role geometry required")
    for row in records:
        targeted._actor_record(row)
    return records

def _source_state_map():
    return {name:name for name in TRAINABLE_PARAMETER_NAMES}


def _branch_digests(state):
    groups=dict(frozen_readout36_state_sha256=BASE_PARAMETER_NAMES,
        actor_head_state_sha256=HEAD_PARAMETER_NAMES,modality_head_state_sha256=MODALITY_NAMES,
        conditions_boundary_head_state_sha256=ORIGINAL_POINTER_NAMES,exceptions_presence_head_state_sha256=PRESENCE_NAMES,
        conditions_presence_state_sha256=conditions.TRAINABLE_PARAMETER_NAMES,
        actor_attention_query_sha256=(FEATURE_PARAMETER_NAMES[0],),actor_context_gate_sha256=(FEATURE_PARAMETER_NAMES[1],))
    result={key:checkpoint_digest({name:state[name] for name in names}) for key,names in groups.items()}
    result['inactive_readout_rows_sha256']=checkpoint_digest(_inactive_state(state))
    return result


def _model(torch, config):
    ambient=torch.get_rng_state().clone();base=refinement._model(torch,config)
    class ModalityConditionsRetentionAdapter(type(base)):
        def forward(self,byte_ids,byte_lengths,lengths,latent,*,enabled=True):
            with torch.no_grad():
                original,original_mask=self._features(byte_ids,byte_lengths,lengths,latent,enabled,False)
                original_pooled=(original*original_mask[...,None]).sum(1)/lengths[:,None]
            modality=self.modality(original_pooled)
            with torch.no_grad():
                encoded,mask=self._features(byte_ids,byte_lengths,lengths,latent,enabled,True)
                pooled=(encoded*mask[...,None]).sum(1)/lengths[:,None]
                original_presence=self.presence(pooled).reshape(-1,4,2)
                scores=(encoded*self.actor_attention.query[None,None,:]).sum(-1)/math.sqrt(64)
                probabilities=torch.softmax(scores.masked_fill(~mask,-float('inf')),dim=1)
                context=(encoded*probabilities[...,None]).sum(1)
                residual=encoded*context[:,None,:]*self.actor_context.gate[None,None,:]
                actor_encoded=torch.where(residual==0,encoded,encoded+residual)
                actor_starts=self.actor_start(actor_encoded).transpose(1,2).masked_fill(~mask[:,None,:],-1e9)
                actor_ends=self.actor_end(actor_encoded).transpose(1,2).masked_fill(~mask[:,None,:],-1e9)
                self._actor_feature_taps=None
            starts=self.start(encoded).transpose(1,2).masked_fill(~mask[:,None,:],-1e9)
            ends=self.end(encoded).transpose(1,2).masked_fill(~mask[:,None,:],-1e9)
            starts=torch.cat((starts[:,:3,:].detach(),starts[:,3:4,:],starts[:,4:,:].detach()),dim=1)
            ends=torch.cat((ends[:,:3,:].detach(),ends[:,3:4,:],ends[:,4:,:].detach()),dim=1)
            with torch.no_grad():
                extra,extra_mask=self._features(byte_ids,byte_lengths,lengths,latent,enabled,True)
                extra_pooled=(extra*extra_mask[...,None]).sum(1)/lengths[:,None]
                learned_conditions=self.conditions_presence(extra_pooled).reshape(-1,4,2)
                presence=torch.cat((original_presence[:,:1,:],learned_conditions[:,1:2,:],original_presence[:,2:,:]),dim=1)
            for key in self._actor_forward_accounting:self._actor_forward_accounting[key]+=1
            for key in self._conditions_forward_accounting:self._conditions_forward_accounting[key]+=1
            return dict(modality=modality,presence=presence,
                start=torch.cat((actor_starts[:,:1,:],starts[:,1:,:]),dim=1),
                end=torch.cat((actor_ends[:,:1,:],ends[:,1:,:]),dim=1))
    base.__class__=ModalityConditionsRetentionAdapter
    _require(torch.equal(ambient,torch.get_rng_state()),'factory changed ambient CPU RNG')
    return base

def _state_digest(model, names=MODEL_PARAMETER_NAMES):
    state = model.state_dict()
    _require(set(state) == set(MODEL_PARAMETER_NAMES), "closed42 live state required")
    return checkpoint_digest({name: state[name].detach().tolist() for name in names})


def _configure_parameters(model):
    named = dict(model.named_parameters())
    _require(tuple(named) == MODEL_PARAMETER_NAMES and len({id(p) for p in named.values()}) == 42
        and len({p.untyped_storage().data_ptr() for p in named.values()}) == 42, 'closed ordered42 state; no aliases')
    _require(all(tuple(named[n].shape) == shape for n, shape in _trainable_shapes().items())
        and sum(named[n].numel() for n in TRAINABLE_PARAMETER_NAMES) == 975, 'closed6 shapes/storage differ')
    for name, parameter in named.items():
        parameter.requires_grad_(name in TRAINABLE_PARAMETER_NAMES)
        parameter.grad = None
    return named, [named[n] for n in TRAINABLE_PARAMETER_NAMES]

def _validate_optimizer_state(state, steps):
    _require(type(steps) is int and 0 <= steps <= 32 and type(state) is dict
        and set(state) == {'schema', 'parameters'} and state['schema'] == 'adam-default-betas-eps/v1'
        and type(state['parameters']) is dict and set(state['parameters']) == (set(TRAINABLE_PARAMETER_NAMES) if steps else set()),
        'closed fresh6 Adam state required')
    for name, moment in state['parameters'].items():
        _require(type(moment) is dict and set(moment) == {'step', 'exp_avg', 'exp_avg_sq'}
            and type(moment['step']) is int and moment['step'] == steps, 'exact completed Adam step required')
        for key in ('exp_avg', 'exp_avg_sq'):
            _finite_shape(moment[key], _trainable_shapes()[name], name, nonnegative=key == 'exp_avg_sq')
            _require(all(_all_zero(moment[key][i]) for i in _inactive_rows(name)), 'inactive650 Adam moments changed')

def _origin(checkpoint):
    result = copy.deepcopy(checkpoint)
    result["model_state"] = _initial_state(result["source_actor_refinement_checkpoint"]["model_state"])
    result["optimizer_state"] = {"schema": "adam-default-betas-eps/v1", "parameters": {}}
    result["progress"] = {"epochs_completed": 0, "row_cursor": 0, "optimizer_steps": 0}
    result["parent_checkpoint_sha256"] = None
    result.pop("initial_checkpoint_sha256", None)
    return result


def build_checkpoint(source_actor_refinement, training_examples, tuning_examples=(), *, context_contract, teacher_training_capture, training_mask_certificate,
                     objective="modality-conditions-retention-ce", seed=1729, batch_order_seed=1729,
                     batch_size=12, learning_rate=.001, latent_enabled=False):
    policy = _policy(objective, seed=seed, batch_order_seed=batch_order_seed, batch_size=batch_size)
    _require(type(learning_rate) in (int, float) and learning_rate == .001 and latent_enabled is False,
        "fixed source-only .001 adapter recipe required")
    source = copy.deepcopy(_source(source_actor_refinement)); records = _training_records(training_examples, tuning_examples)
    teacher_text = _teacher_text(teacher_training_capture)
    targets = _training_targets(teacher_text, training_examples, source["training_manifest_sha256"])
    teacher, weights = targets["teacher_training"], targets["row_weight_training"]
    _validate_training_mask_certificate(training_mask_certificate, teacher, weights)
    contract = continuation._context_contract(context_contract)
    child = source["initial_continuation_checkpoint"]
    _require(_raw(contract) == _raw(child["context_contract"])
        and checkpoint_digest(training_examples) == source["training_manifest_sha256"], "source context/training identity differs")
    state = _initial_state(source["model_state"])
    result = {"schema": SCHEMA, "lineage_id": LINEAGE_ID, "implementation": _implementation(),
        "training_policy": policy, "training_policy_sha256": checkpoint_digest(policy),
        "initial_training_policy_sha256": checkpoint_digest(policy),
        "source_actor_refinement_checkpoint": source, "source_actor_refinement_checkpoint_sha256": SOURCE_ACTOR_REFINEMENT_SHA256,
        "source_actor_refinement_model_state_sha256": SOURCE_ACTOR_REFINEMENT_MODEL_SHA256, "source_actor_refinement_optimizer_steps": 32,
        "source_parent_checkpoint_sha256": source["source_parent_checkpoint_sha256"],
        "source_parent_model_state_sha256": source["source_parent_model_state_sha256"],
        "initial_continuation_checkpoint": copy.deepcopy(child),
        "initial_continuation_checkpoint_sha256": checkpoint_digest(child),
        "context_contract": contract, "context_contract_sha256": checkpoint_digest(contract),
        "config": copy.deepcopy(source["config"]), "training_manifest_sha256": checkpoint_digest(training_examples),
        "tuning_manifest_sha256": checkpoint_digest(tuning_examples), "training_count": 168, "tuning_count": 0,
        "teacher_capture_utf8": teacher_text, "teacher_training_examples": copy.deepcopy(training_examples),
        "teacher_training": teacher, "teacher_training_sha256": checkpoint_digest(teacher),
        "row_weight_training": weights, "row_weight_training_sha256": checkpoint_digest(weights),
        "training_mask_certificate": copy.deepcopy(training_mask_certificate),
        "training_mask_certificate_sha256": checkpoint_digest(training_mask_certificate),
        "legacy_prefix_sha256": targeted.LEGACY96_SHA256, "actor_training_count": 168,
        "actor_adapter_source_state_map": _source_state_map(),
        "model_source_state_map": {name:name for name in MODEL_PARAMETER_NAMES},
        "model_state": state, "initial_branch_digests": _branch_digests(state),
        "source_frozen36_state_sha256":checkpoint_digest({name:source["model_state"][name] for name in BASE_PARAMETER_NAMES}),
        "optimizer_state": {"schema": "adam-default-betas-eps/v1", "parameters": {}},
        "progress": {"epochs_completed": 0, "row_cursor": 0, "optimizer_steps": 0},
        "parent_checkpoint_sha256": None, **FALSE}
    result["initial_checkpoint_sha256"] = checkpoint_digest(result)
    _require(len(_raw(result)) <= MAX_BYTES, "adapter checkpoint exceeds byte bound")
    return result


def _validated(checkpoint):
    fields = {"schema", "lineage_id", "implementation", "training_policy", "training_policy_sha256",
        "initial_training_policy_sha256", "initial_checkpoint_sha256", "source_actor_refinement_checkpoint",
        "source_actor_refinement_checkpoint_sha256", "source_actor_refinement_model_state_sha256", "source_actor_refinement_optimizer_steps",
        "source_parent_checkpoint_sha256", "source_parent_model_state_sha256", "initial_continuation_checkpoint",
        "initial_continuation_checkpoint_sha256", "context_contract", "context_contract_sha256", "config",
        "training_manifest_sha256", "tuning_manifest_sha256", "training_count", "tuning_count", "legacy_prefix_sha256",
        "actor_training_count", "actor_adapter_source_state_map", "model_source_state_map", "model_state", "initial_branch_digests", "source_frozen36_state_sha256",
        "teacher_capture_utf8", "teacher_training_examples", "teacher_training", "teacher_training_sha256",
        "row_weight_training", "row_weight_training_sha256", "training_mask_certificate", "training_mask_certificate_sha256",
        "optimizer_state", "progress", "parent_checkpoint_sha256", *FALSE}
    _require(type(checkpoint) is dict and set(checkpoint) == fields, "closed adapter checkpoint required")
    _require(checkpoint["schema"] == SCHEMA and checkpoint["lineage_id"] == LINEAGE_ID
        and all(checkpoint[key] is False for key in FALSE) and checkpoint["implementation"] == _implementation()
        and len(_raw(checkpoint)) <= MAX_BYTES, "adapter schema/source/authority/bound differs")
    source = _source(checkpoint["source_actor_refinement_checkpoint"])
    targets = _training_targets(checkpoint["teacher_capture_utf8"], checkpoint["teacher_training_examples"], source["training_manifest_sha256"])
    teacher, weights = targets["teacher_training"], targets["row_weight_training"]
    _require(_raw(weights) == _raw(checkpoint["row_weight_training"]) and checkpoint_digest(weights) == checkpoint["row_weight_training_sha256"], "rederived immutable row weights differ")
    _validate_training_mask_certificate(checkpoint["training_mask_certificate"], teacher, weights)
    _require(checkpoint_digest(checkpoint["training_mask_certificate"]) == checkpoint["training_mask_certificate_sha256"], "certificate digest differs")
    _require(_raw(teacher) == _raw(checkpoint["teacher_training"]) and checkpoint_digest(teacher) == checkpoint["teacher_training_sha256"], "immutable rederived teacher targets differ")
    policy = _validate_policy(checkpoint["training_policy"])
    _require(checkpoint["training_policy_sha256"] == checkpoint["initial_training_policy_sha256"] == checkpoint_digest(policy),
        "immutable adapter policy differs")
    for key, value in {"source_actor_refinement_checkpoint_sha256": SOURCE_ACTOR_REFINEMENT_SHA256,
        "source_actor_refinement_model_state_sha256": SOURCE_ACTOR_REFINEMENT_MODEL_SHA256, "source_actor_refinement_optimizer_steps": 32,
        "config": source["config"], "training_manifest_sha256": source["training_manifest_sha256"],
        "source_parent_checkpoint_sha256": source["source_parent_checkpoint_sha256"],
        "source_parent_model_state_sha256": source["source_parent_model_state_sha256"],
        "initial_continuation_checkpoint": source["initial_continuation_checkpoint"],
        "initial_continuation_checkpoint_sha256": checkpoint_digest(source["initial_continuation_checkpoint"]),
        "context_contract": source["initial_continuation_checkpoint"]["context_contract"],
        "context_contract_sha256": source["initial_continuation_checkpoint"]["context_contract_sha256"],
        "training_count": 168, "tuning_count": 0, "tuning_manifest_sha256": checkpoint_digest(()),
        "legacy_prefix_sha256": targeted.LEGACY96_SHA256, "actor_training_count": 168, "teacher_training_sha256": checkpoint["teacher_training_sha256"],
        "actor_adapter_source_state_map": _source_state_map(),
        "model_source_state_map": {name:name for name in MODEL_PARAMETER_NAMES},
        "source_frozen36_state_sha256":checkpoint_digest({name:source["model_state"][name] for name in BASE_PARAMETER_NAMES})}.items():
        _require(_raw(checkpoint[key]) == _raw(value), "adapter provenance differs: " + key)
    _require(checkpoint["config"]["latent_dimension"] == 384 and checkpoint["config"]["latent_enabled"] is False
        and checkpoint["config"]["hidden_size"] * 2 == ENCODED_WIDTH, "source-only fixed64 geometry required")
    initial = _initial_state(source["model_state"])
    _require(checkpoint["initial_branch_digests"] == _branch_digests(initial), "initial adapter branch digests differ")
    state = checkpoint["model_state"]
    _require(type(state) is dict and set(state) == set(MODEL_PARAMETER_NAMES), "closed42 state required")
    _require(all(_raw(state[name]) == _raw(source["model_state"][name]) for name in BASE_PARAMETER_NAMES)
        and _raw(_inactive_state(state)) == _raw(_inactive_state(initial)), "frozen readouts or inactive adapter rows changed")
    for name, dimensions in _trainable_shapes().items():
        _finite_shape(state[name], dimensions, name)
    progress = targeted._progress(checkpoint["progress"])
    _require(progress["optimizer_steps"] <= 32, "adapter update budget exceeded")
    targeted._batch_indices(168, progress, 12, 1729)
    previous = checkpoint["parent_checkpoint_sha256"]
    _require((progress["optimizer_steps"] == 0 and previous is None and _raw(state) == _raw(initial))
        or (progress["optimizer_steps"] > 0 and type(previous) is str and span._SHA.fullmatch(previous)),
        "adapter preceding checkpoint lineage differs")
    _require(checkpoint["initial_checkpoint_sha256"] == checkpoint_digest(_origin(checkpoint)), "adapter origin differs")
    _validate_optimizer_state(checkpoint["optimizer_state"], progress["optimizer_steps"])
    return source, policy


def _restore(checkpoint):
    import torch
    ambient = torch.get_rng_state().clone(); _, policy = _validated(checkpoint)
    model = _model(torch, checkpoint["config"]); template = model.state_dict()
    model.load_state_dict({name: span._tensor(torch, checkpoint["model_state"][name], value.shape, name)
        for name, value in template.items()}, strict=True)
    named, selected = _configure_parameters(model)
    optimizer = torch.optim.Adam(selected, lr=.001, betas=(.9, .999), eps=1e-8, weight_decay=0., foreach=False)
    for name, moment in checkpoint["optimizer_state"]["parameters"].items():
        parameter = named[name]
        optimizer.state[parameter] = {"step": torch.tensor(float(moment["step"])),
            "exp_avg": span._tensor(torch, moment["exp_avg"], parameter.shape, name),
            "exp_avg_sq": span._tensor(torch, moment["exp_avg_sq"], parameter.shape, name, nonnegative=True)}
    model.eval(); _require(torch.equal(ambient, torch.get_rng_state()), "adapter restore changed ambient CPU RNG")
    return torch, model, optimizer


def validate_checkpoint(checkpoint):
    _restore(checkpoint)


def _loss(torch,output,records,indices,policy,teacher,weights):
    _validate_policy(policy);weight_rows=_weight_batch(records,indices,weights)
    _require(all(bool(torch.isfinite(value).all()) for value in output.values()),'finite full heads required')
    labels=[record['labels'] for record in records];functional=torch.nn.functional
    modality_rows=functional.cross_entropy(output['modality'],torch.tensor([label['modality'] for label in labels]),reduction='none')
    facet_rows=[];condition_parts={}
    for index,field in enumerate(span.SPAN_FIELDS):
        present=torch.tensor([label['presence'][index] for label in labels],dtype=torch.bool)
        starts=torch.tensor([label['spans'][index][0] for label in labels],dtype=torch.long)
        ends=torch.tensor([label['spans'][index][1] for label in labels],dtype=torch.long)
        start_ce=functional.cross_entropy(output['start'][:,index],starts,ignore_index=-100,reduction='none')
        end_ce=functional.cross_entropy(output['end'][:,index],ends,ignore_index=-100,reduction='none')
        pointer=(start_ce+end_ce)*.5
        if field in span.OPTIONAL_FIELDS:
            presence_ce=functional.cross_entropy(output['presence'][:,span.OPTIONAL_FIELDS.index(field)],present.to(torch.long),reduction='none')
            facet_rows.append(presence_ce+pointer)
            if field=='conditions':condition_parts=dict(presence=presence_ce,start=start_ce,end=end_ce)
        else:facet_rows.append(pointer)
    row_weights=torch.tensor([row['conditions_facet_weight'] for row in weight_rows],dtype=output['modality'].dtype)
    main,unweighted=_weighted_main_loss(modality_rows.mean(),facet_rows,row_weights)
    rows=[]
    for position,row in enumerate(weight_rows):
        rows.append(dict(id=row['id'],training_index=row['training_index'],source_sha256=row['source_sha256'],
            weight_target_sha256=checkpoint_digest(row),conditions_facet_weight=row['conditions_facet_weight'],
            modality_CE=float(modality_rows[position].detach()),facet_CEs=[float(values[position].detach()) for values in facet_rows],
            conditions_presence_CE=float(condition_parts['presence'][position].detach()),
            conditions_start_CE=float(condition_parts['start'][position].detach()),conditions_end_CE=float(condition_parts['end'][position].detach()),
            weighted_conditions_facet_CE=float((facet_rows[3][position]*row_weights[position]).detach())))
    facet_means=[float(values.mean().detach()) for values in facet_rows]
    weighted_means=list(facet_means);weighted_means[3]=float((facet_rows[3]*row_weights).mean().detach())
    ce=dict(schema='modality-conditions-entire-facet-weighted-CE/v1',rows=rows,batch_denominator=len(rows),outer_denominator=8,
        modality_multiplier=2,modality_CE_mean=float(modality_rows.mean().detach()),facet_CE_means=facet_means,
        weighted_facet_CE_means=weighted_means,weighted_main_loss=float(main.detach()),unweighted_main_loss=float(unweighted.detach()),
        row_weight_rows_sha256=weights['rows_sha256'],near_complete_mask_sha256=weights['near_complete_mask_sha256'],
        actor_hinge_applied=False,actor_hinge_omitted=True,teacher_forcing=True,evaluation_references_used=False)
    retention,retention_details=_retention_loss(torch,output,records,indices,teacher)
    total=main+retention
    return total,dict(weighted_CE=ce,retention=retention_details,total_loss=float(total.detach()),teacher_forcing=True,evaluation_references_used=False)

def _validate_objective_entry(entry,batch,policy,teacher=None,weights=None):
    _validate_policy(policy)
    _require(type(entry) is dict and set(entry)=={'optimizer_step','indices','ids','details'}
        and all(entry[key]==batch[key] for key in ('optimizer_step','indices','ids')),'objective/batch membership differs')
    d=entry['details']
    _require(type(d) is dict and set(d)=={'weighted_CE','retention','total_loss','teacher_forcing','evaluation_references_used'}
        and d['teacher_forcing'] is True and d['evaluation_references_used'] is False,'closed six-tensor objective required')
    _validate_CE_entry(d['weighted_CE'],batch,weights)
    r = d['retention']; _require(set(r) == {'rows', 'denominator', 'value', 'teacher_rows_sha256', 'teacher_capture_sha256',
        'teacher_model_forwards', 'evaluation_references_used', 'masked_zero_graph_connected'} and r['teacher_model_forwards'] == 0
        and r['evaluation_references_used'] is False and r['masked_zero_graph_connected'] is True
        and r['teacher_capture_sha256'] == TEACHER_CAPTURE_SHA256 and type(r['teacher_rows_sha256']) is str
        and span._SHA.fullmatch(r['teacher_rows_sha256']) and type(r['denominator']) is int
        and r['denominator'] == 6 * len(batch['indices']) and len(r['rows']) == len(batch['indices']), 'retention normalization/source differs')
    values = []
    for index, identifier, row in zip(batch['indices'], batch['ids'], r['rows'], strict=True):
        _require(type(row) is dict and set(row) == {'id', 'training_index', 'source_sha256', 'blocks'}
            and row['id'] == identifier and type(row['training_index']) is int and row['training_index'] == index
            and set(row['blocks']) == set(RETENTION_BLOCKS) and type(row['source_sha256']) is str
            and span._SHA.fullmatch(row['source_sha256']), 'retention training membership differs')
        for block in RETENTION_BLOCKS:
            b = row['blocks'][block]
            _require(type(b) is dict and set(b) == {'logits', 'gold_index', 'teacher_argmax', 'mask', 'candidate_logits', 'kl_float32'}, 'closed retention block required')
            _require(type(b['logits']) is list and b['logits'], 'nonempty teacher vector required')
            width = len(b['logits']); _score_vector(b['logits'], width); _score_vector(b['candidate_logits'], width)
            _require(width == (3 if block == 'modality' else 2) if block in ('modality', 'exceptions_presence') else 1 <= width <= 128, 'valid KL domain required')
            argmax = max(range(width), key=b['logits'].__getitem__)
            _require(type(b['teacher_argmax']) is int and b['teacher_argmax'] == argmax and type(b['mask']) is bool
                and (b['gold_index'] is None or type(b['gold_index']) is int and 0 <= b['gold_index'] < width)
                and b['mask'] is (b['gold_index'] is not None and argmax == b['gold_index']), 'teacher-correct component mask differs')
            ref = _kl_reference(b['logits'], b['candidate_logits']) if b['mask'] else 0.
            value = b['kl_float32']; _require(type(value) is float and math.isfinite(value) and targeted._f32(value) == value
                and abs(value - ref) <= 3e-5 * max(1., abs(ref)) and (b['mask'] or value == 0.), 'stable scalar KL replay differs')
            values.append(value)
    reference = math.fsum(values) / r['denominator']
    _require(type(r['value']) is float and math.isfinite(r['value']) and targeted._f32(r['value']) == r['value']
        and abs(r['value'] - reference) <= 1e-5 * max(1., math.fsum(abs(v) for v in values) / r['denominator']), 'retention batch mean differs')
    _require(d['total_loss']==targeted._f32(d['weighted_CE']['weighted_main_loss']+r['value'])==batch['loss'],
        'weightedCE plus retention float32 association differs; actor hinge must be omitted')
    if teacher is not None:_validate_teacher_entry(entry,teacher)

def _frozen_head_digest(output):
    return checkpoint_digest(dict(protected_presence=output['presence'].detach().tolist(),
        protected_start=output['start'][:,(0,1,2,4,5),:].detach().tolist(),
        protected_end=output['end'][:,(0,1,2,4,5),:].detach().tolist()))

def _row_invariants(named, optimizer):
    _require(all(named[n].grad is None for n in BASE_PARAMETER_NAMES), 'frozen36 gradient accumulated')
    for name in TRAINABLE_PARAMETER_NAMES:
        parameter = named[name]
        _require(parameter.grad is not None and bool(parameter.grad.isfinite().all()), 'finite connected6 readout gradients required')
        _require(all(bool((parameter.grad[i] == 0).all()) for i in _inactive_rows(name)), 'inactive650 gradients nonzero')
        if parameter in optimizer.state:
            for key in ('exp_avg', 'exp_avg_sq'):
                moment = optimizer.state[parameter][key]
                _require(bool(moment.isfinite().all()) and all(bool((moment[i] == 0).all()) for i in _inactive_rows(name)), 'inactive650 moments nonzero')

def _validate_freeze_entry(entry, batch):
    required = {'optimizer_step', 'indices', 'ids', 'source_frozen36_state_sha256', 'frozen_before', 'frozen_after',
        'inactive_before', 'inactive_after', 'frozen_head_sample_sha256', 'frozen_gradients_none', 'trainable_gradients_finite_nonNone',
        'inactive_gradients_zero', 'inactive_moments_zero', 'changed_parameter_names', 'completed_returned_update', 'branch_digests_before', 'branch_digests_after'}
    _require(type(entry) is dict and set(entry) == required and all(entry[k] == batch[k] for k in ('optimizer_step', 'indices', 'ids')), 'closed freeze trace required')
    for k in ('frozen_gradients_none', 'trainable_gradients_finite_nonNone', 'inactive_gradients_zero', 'inactive_moments_zero', 'completed_returned_update'):
        _require(entry[k] is True, 'returned update invariants required')
    before, after = entry['branch_digests_before'], entry['branch_digests_after']
    keys = {'frozen_readout36_state_sha256', 'actor_head_state_sha256', 'modality_head_state_sha256',
        'conditions_boundary_head_state_sha256', 'exceptions_presence_head_state_sha256', 'conditions_presence_state_sha256',
        'inactive_readout_rows_sha256', 'actor_attention_query_sha256', 'actor_context_gate_sha256'}
    fixed = {'frozen_readout36_state_sha256','actor_head_state_sha256','actor_attention_query_sha256','actor_context_gate_sha256','exceptions_presence_head_state_sha256','conditions_presence_state_sha256','inactive_readout_rows_sha256'}
    _require(type(before) is dict and type(after) is dict and set(before) == set(after) == keys
        and all(before[k] == after[k] for k in fixed) and before['frozen_readout36_state_sha256'] == entry['source_frozen36_state_sha256']
        == entry['frozen_before'] == entry['frozen_after'] and before['inactive_readout_rows_sha256'] == entry['inactive_before'] == entry['inactive_after']
        and type(entry['changed_parameter_names']) is list and len(set(entry['changed_parameter_names'])) == len(entry['changed_parameter_names'])
        and set(entry['changed_parameter_names']) <= set(TRAINABLE_PARAMETER_NAMES), 'frozen36/inactive650 drift or unknown changed tensor')
    for digest in (*before.values(), *after.values(), entry['frozen_head_sample_sha256']):
        _require(type(digest) is str and span._SHA.fullmatch(digest), 'raw invariant SHA required')








def train_decoder(checkpoint, training_examples, tuning_examples=(), *, max_steps=32, max_seconds=32):
    _require(type(max_steps) is int and 0 <= max_steps <= 32 and type(max_seconds) in (int, float)
        and math.isfinite(max_seconds) and 0 <= max_seconds <= 32, "bounded adapter32-step/time call required")
    started = time.monotonic(); deadline = started+max_seconds
    _, policy = _validated(checkpoint); records = _training_records(training_examples, tuning_examples)
    _require(checkpoint["training_manifest_sha256"] == checkpoint_digest(training_examples), "resume training rows differ")
    progress = dict(checkpoint["progress"]); initial_progress = dict(progress)
    _require(progress["optimizer_steps"]+max_steps <= 32, "adapter cumulative32-step limit exceeded")
    torch, model, optimizer = _restore(checkpoint); named = dict(model.named_parameters())
    selected = [named[name] for name in TRAINABLE_PARAMETER_NAMES]
    initial_state = {name: p.detach().tolist() for name, p in model.state_dict().items()}
    initial_hash = checkpoint_digest(initial_state); initial_branches = _branch_digests(initial_state)
    forward_counts_before = dict(model._conditions_forward_accounting)
    batches, objectives, freezes, losses = [], [], [], []; maximum_gradient = 0.; reason = "step_limit"
    for _ in range(max_steps):
        if time.monotonic() >= deadline: reason = "deadline_before_batch"; break
        before_progress = dict(progress); indices = targeted._batch_indices(168, progress, 12, 1729)
        batch = [records[index] for index in indices]
        model.train(); optimizer.zero_grad(set_to_none=True)
        _require(all(named[name].grad is None for name in BASE_PARAMETER_NAMES), "frozen36 preupdate gradient accumulated")
        before_state = {name: p.detach().tolist() for name, p in model.state_dict().items()}
        branch_before = _branch_digests(before_state)
        _require(branch_before["frozen_readout36_state_sha256"] == checkpoint["source_frozen36_state_sha256"], "frozen36 preupdate drift")
        output = model(*span._batch(torch, batch)); before_heads = _frozen_head_digest(output)
        loss, details = _loss(torch, output, batch, indices, policy, checkpoint["teacher_training"], checkpoint["row_weight_training"])
        _require(bool(torch.isfinite(loss)), "nonfinite adapter loss")
        loss.backward(); _row_invariants(named, optimizer)
        gradient = float(torch.nn.utils.clip_grad_norm_(selected, 5., error_if_nonfinite=True)); maximum_gradient = max(maximum_gradient, gradient)
        optimizer.step(); _row_invariants(named, optimizer)
        _require(all(bool(torch.isfinite(p).all()) for p in named.values()) and all(bool(torch.isfinite(value).all())
            for moment in optimizer.state.values() for value in moment.values() if torch.is_tensor(value)), "nonfinite weights/moments")
        after_state = {name: p.detach().tolist() for name, p in model.state_dict().items()}; branch_after = _branch_digests(after_state)
        progress = targeted._advance_progress(before_progress, len(indices), 168); scalar = float(loss.detach()); losses.append(scalar)
        trace = targeted._batch_trace_entry(indices, training_examples, before_progress, progress, loss=scalar, gradient_norm=gradient)
        batches.append(trace)
        entry = {"optimizer_step": progress["optimizer_steps"], "indices": list(indices), "ids": list(trace["ids"]), "details": details}
        _validate_objective_entry(entry, trace, policy, checkpoint["teacher_training"], checkpoint["row_weight_training"]); objectives.append(entry)
        freeze = {"optimizer_step": progress["optimizer_steps"], "indices": list(indices), "ids": list(trace["ids"]),
            "source_frozen36_state_sha256":checkpoint["source_frozen36_state_sha256"],
            "frozen_before": branch_before["frozen_readout36_state_sha256"], "frozen_after": branch_after["frozen_readout36_state_sha256"],
            "inactive_before": branch_before["inactive_readout_rows_sha256"], "inactive_after": branch_after["inactive_readout_rows_sha256"],
            "frozen_head_sample_sha256": before_heads, "frozen_gradients_none": True,
            "trainable_gradients_finite_nonNone": True, "inactive_gradients_zero": True, "inactive_moments_zero": True,
            "changed_parameter_names": [name for name in MODEL_PARAMETER_NAMES if before_state[name] != after_state[name]],
            "completed_returned_update": True, "branch_digests_before": branch_before, "branch_digests_after": branch_after}
        _validate_freeze_entry(freeze, trace); freezes.append(freeze)
    weights, moments = span._pack(model, optimizer); _validate_optimizer_state(moments, progress["optimizer_steps"])
    updated = copy.deepcopy(checkpoint); updated.update(model_state=weights, optimizer_state=moments, progress=progress,
        parent_checkpoint_sha256=checkpoint_digest(checkpoint) if losses else checkpoint["parent_checkpoint_sha256"])
    _validated(updated)
    for previous, current in zip(freezes, freezes[1:]):
        _require(previous["branch_digests_after"] == current["branch_digests_before"], "interupdate branch discontinuity")
    initial_origin = _initial_state(checkpoint["source_actor_refinement_checkpoint"]["model_state"])
    final_branches = _branch_digests(weights)
    forward_counts = {key: model._conditions_forward_accounting[key] - forward_counts_before[key] for key in forward_counts_before}
    _require(all(count == len(losses) for count in forward_counts.values()), "actual actor training forward counts differ")
    report = {"schema": "bounded-modality-conditions-retention-adapter-training/v1", "checkpoint_sha256": checkpoint_digest(updated),
        "previous_actor_adapter_checkpoint_sha256": checkpoint_digest(checkpoint),
        "initial_checkpoint_sha256": checkpoint["initial_checkpoint_sha256"],
        "source_actor_refinement_checkpoint_sha256": SOURCE_ACTOR_REFINEMENT_SHA256, "source_actor_refinement_model_state_sha256": SOURCE_ACTOR_REFINEMENT_MODEL_SHA256,
        "source_actor_refinement_optimizer_steps": 32, "source_parent_checkpoint_sha256": checkpoint["source_parent_checkpoint_sha256"],
        "source_parent_model_state_sha256": checkpoint["source_parent_model_state_sha256"],
        "initial_continuation_checkpoint_sha256": checkpoint["initial_continuation_checkpoint_sha256"],
        "initial_model_state_sha256": checkpoint_digest(initial_origin), "final_model_state_sha256": checkpoint_digest(weights),
        "training_call_initial_model_state_sha256": initial_hash, "initial_branch_digests": checkpoint["initial_branch_digests"],
        "training_call_initial_branch_digests": initial_branches, "final_branch_digests": final_branches,
        "training_policy": copy.deepcopy(policy), "training_policy_sha256": checkpoint_digest(policy), "parameter_partition": _partition(),
        "optimizer_parameter_order": list(TRAINABLE_PARAMETER_NAMES), "optimizer_steps": len(losses),
        "stored_trainable_scalar_count": STORED_TRAINABLE_SCALARS,
        "active_trainable_scalar_count": ACTIVE_TRAINABLE_SCALARS,
        "continuation_optimizer_steps_total": progress["optimizer_steps"], "training_executed": bool(losses),
        "batch_losses": losses, "batch_trace": targeted._trace_summary(batches, initial_progress, progress, policy["objective_policy"], training_examples),
        "objective_trace": {"schema": "completed-modality-conditions-retention-adapter-objective-trace/v1", "completed_updates": len(objectives),
            "batches": objectives, "batches_sha256": checkpoint_digest(objectives), "evaluation_references_used": False,
            "independent_numerical_kernel_trace": False},
        "freeze_trace": {"schema": "completed-modality-conditions-retention-adapter-freeze-trace/v1", "completed_updates": len(freezes),
            "batches": freezes, "batches_sha256": checkpoint_digest(freezes), "independent_numerical_kernel_trace": False},
        "frozen_parent36_sha256_initial": initial_branches["frozen_readout36_state_sha256"],
        "frozen_parent36_sha256_final": final_branches["frozen_readout36_state_sha256"],
        "source_frozen36_state_sha256":checkpoint["source_frozen36_state_sha256"],
        "inactive_head_rows_sha256_initial": initial_branches["inactive_readout_rows_sha256"],
        "inactive_head_rows_sha256_final": final_branches["inactive_readout_rows_sha256"],
        "frozen_parameters_sha256_initial": initial_branches["frozen_readout36_state_sha256"],
        "frozen_parameters_sha256_final": final_branches["frozen_readout36_state_sha256"],
        "legacy_prefix_sha256": targeted.LEGACY96_SHA256, "actor_training_count": 168, "teacher_training_sha256": checkpoint["teacher_training_sha256"],
        "row_weight_training_sha256": checkpoint["row_weight_training_sha256"],
        "row_weight_rows_sha256": checkpoint["row_weight_training"]["rows_sha256"],
        "near_complete_mask_sha256": checkpoint["row_weight_training"]["near_complete_mask_sha256"],
        "selected_training_weight_ids": checkpoint["row_weight_training"]["selected_ids"],
        "training_mask_certificate_sha256": checkpoint["training_mask_certificate_sha256"],
        "actor_features_frozen": True, "all_presence_frozen": True, "parent_ablation_only": True,
        "actor_adapter_source_state_map": checkpoint["actor_adapter_source_state_map"],
        "model_source_state_map": checkpoint["model_source_state_map"],
        "gradient_norm_max": maximum_gradient, "changed_parameter_names": [name for name in MODEL_PARAMETER_NAMES if weights[name] != initial_state[name]],
        "stopped_reason": reason, "elapsed_seconds": time.monotonic()-started,
        "deadline_scope": "soft_boundary_before_numeric_batch; initialization_and_serialization_not_interruptible",
        "partial_failure_scope": "only_successfully_returned_prefix_traced; unreturned_partial_failure_unknown",
        "forward_accounting":{"schema":"modality-conditions-retention-adapter-training-forward-accounting/v1",
            "training_model_forward_calls":forward_counts["source_model_forwards"],
            "training_actor_features_model_calls":forward_counts["actor_features_model_forwards"],
            "training_modality_encoder_calls":forward_counts["frozen_modality_encoder_forwards"],
            "training_span_encoder_calls":forward_counts["frozen_span_encoder_forwards"]+forward_counts["additional_frozen_span_encoder_forwards"],
            "training_conditions_presence_head_calls":forward_counts["conditions_presence_head_forwards"],
            "actual_model_counter_deltas":forward_counts,"training_source_row_occurrences":sum(len(b["indices"]) for b in batches),
            "tuning_model_forward_calls":0,"teacher_model_forward_calls":0,"feature_paths_per_source_model_forward":3,
            "restore_validation_and_external_evaluation_forwards_included":False},
        "tuning": {"rows_evaluated": 0, "used_for_fit_or_selection": False}, **FALSE}
    return {"checkpoint": updated, "report": report}


class SpanModalityConditionsRetentionAdapterDecoder:
    """Use the unchanged single-source readout under this new outer's custody."""
    def __init__(self, checkpoint):
        self.torch, self.model, _ = _restore(checkpoint)
        self._checkpoint_bytes = _raw(checkpoint)
        self.checkpoint_sha256 = hashlib.sha256(self._checkpoint_bytes).hexdigest()
        self._expected_model_sha256 = _state_digest(self.model)
        self._implementation_snapshot = _raw(checkpoint["implementation"])
        self._policy = copy.deepcopy(checkpoint["training_policy"])
        view = object.__new__(span.SpanLegalFormulaDecoder)
        view.torch, view.model = self.torch, self.model
        view.checkpoint = {"config": copy.deepcopy(checkpoint["config"])}
        self._inference_view = view

    @property
    def checkpoint(self):
        return json.loads(self._checkpoint_bytes)

    def decode_formal_logic(self, texts, latents=None, *, latent_ablation="none"):
        _require(type(texts) in (list, tuple) and 1 <= len(texts) <= 128
            and all(type(text) is str and len(span.tokenize_source(text)) <= 128 for text in texts),
            "one to128 bounded source strings required")
        _require(type(latents) in (list, tuple) and len(latents) == len(texts), "one latent placeholder per source required")
        vectors = [span._vector(vector, 384) for vector in latents]
        _require(latent_ablation in ("none", "zero", "rotate", "disabled"), "unsupported latent ablation")
        _require(latent_ablation != "rotate" or len(texts) > 1, "rotate requires at leasttwo sources")
        _require(_raw(_implementation()) == self._implementation_snapshot
            and hashlib.sha256(self._checkpoint_bytes).hexdigest() == self.checkpoint_sha256,
            "owned inference source or checkpoint changed")
        _require(self._inference_view.model is self.model and self._inference_view.torch is self.torch
            and self._inference_view.checkpoint == {"config": self.checkpoint["config"]}, "readout adapter changed")
        _require(_state_digest(self.model) == self._expected_model_sha256, "owned inference model changed")
        if latent_ablation == "zero": vectors = [[0.] * 384 for _ in vectors]
        elif latent_ablation == "rotate": vectors = vectors[1:] + vectors[:1]
        forward_counts_before = dict(self.model._conditions_forward_accounting)
        rows = [self._inference_view._decode(text, vector, enabled=latent_ablation != "disabled")
            for text, vector in zip(texts, vectors, strict=True)]
        _require(_state_digest(self.model) == self._expected_model_sha256
            and _raw(_implementation()) == self._implementation_snapshot, "inference changed source or model")
        forward_counts = {key: self.model._conditions_forward_accounting[key] - forward_counts_before[key] for key in forward_counts_before}
        _require(all(value == len(rows) for value in forward_counts.values()), "actual actor inference forward counts differ")
        count = sum(row["status"] == "decoded" for row in rows)
        child = self.checkpoint["initial_continuation_checkpoint"]
        return {"schema": "bounded-modality-conditions-retention-adapter-inference/v1", "lineage_id": LINEAGE_ID,
            "checkpoint_sha256": self.checkpoint_sha256, "initial_continuation_checkpoint_sha256": checkpoint_digest(child),
            "source_parent_checkpoint_sha256": child["source_parent_checkpoint_sha256"], "source_parent_optimizer_steps": 400, "source_actor_refinement_optimizer_steps": 32,
            "source_actor_refinement_checkpoint_sha256": SOURCE_ACTOR_REFINEMENT_SHA256, "source_actor_refinement_model_state_sha256": SOURCE_ACTOR_REFINEMENT_MODEL_SHA256,
            "context_contract_sha256": child["context_contract_sha256"], "model_state_sha256": self._expected_model_sha256,
            "training_policy": copy.deepcopy(self._policy), "training_policy_sha256": checkpoint_digest(self._policy),
            "rows": rows, "decoded_count": count, "status": "decoded" if count == len(rows) else "partial" if count else "abstained",
            "latent_ablation": latent_ablation, "target_access": False, "teacher_forcing": False,
            "training_executed": False, "legacy_single_source_readout_unchanged": True, "split_feature_model_forward": True, "actor_adapter_model_forward": True,
            "conditions_presence_adapter_model_forward":True,"feature_paths_per_source_forward":3,
            "branch_digests": _branch_digests(self.checkpoint["model_state"]),
            **forward_counts, **FALSE}


def captured_inference(torch, span, warm, checkpoint, rows, *, control="none"):
    """Capture same-forward heads without exposing labels to inference."""
    _require(span is globals()["span"] and warm is continuation, "exact unchanged source owners required")
    _require(type(rows) in (list, tuple) and 1 <= len(rows) <= 128, "one to128 bounded capture source rows required")
    decoder = SpanModalityConditionsRetentionAdapterDecoder(checkpoint)
    _require(torch is decoder.torch, "exact decoder numerical owner required")
    ambient = torch.get_rng_state().clone()
    model_before = _state_digest(decoder.model)
    _require(not decoder.model._forward_hooks and not decoder.model._forward_pre_hooks, "pre-existing hooks refused")
    sources = [{key: row[key] for key in ("id", "source_text", "latent")} for row in rows]
    _require(control in ("none", "zero", "disabled", "rotate"), "unknown latent control")
    tokens = [span.tokenize_source(row["source_text"]) for row in sources]
    captures = []
    def hook(module, incoming, output):
        position = len(captures)
        _require(module is decoder.model and position < len(sources), "unexpected extra source forward")
        count = len(tokens[position])
        _require(type(output) is dict and set(output) == {"modality", "presence", "start", "end"}, "closed heads required")
        for field, shape in {"modality": (1, 3), "presence": (1, 4, 2), "start": (1, 6, count), "end": (1, 6, count)}.items():
            value = output[field]
            _require(torch.is_tensor(value) and tuple(value.shape) == shape and value.dtype == torch.float32
                and value.device.type == "cpu" and not value.requires_grad and bool(torch.isfinite(value).all()),
                "finite detached CPU heads required")
        captures.append({"schema": "joint-source-span-scores/v1",
            "tokens": [{key: token[key] for key in ("text", "start", "end")} for token in tokens[position]],
            "modality_logits": output["modality"][0].tolist(),
            "presence_logits": dict(zip(span.OPTIONAL_FIELDS, output["presence"][0].tolist(), strict=True)),
            "start_logits": dict(zip(span.SPAN_FIELDS, output["start"][0].tolist(), strict=True)),
            "end_logits": dict(zip(span.SPAN_FIELDS, output["end"][0].tolist(), strict=True))})
        return None
    handle = decoder.model.register_forward_hook(hook)
    try:
        with torch.random.fork_rng(devices=[]):
            report = decoder.decode_formal_logic([row["source_text"] for row in sources], [row["latent"] for row in sources],
                latent_ablation=control)
    finally:
        handle.remove()
    _require(len(captures) == len(rows) == len(report["rows"]) and not decoder.model._forward_hooks
        and _state_digest(decoder.model) == model_before and torch.equal(ambient, torch.get_rng_state()),
        "capture changed model/hooks/RNG or lacked complete source coverage")
    _require(all(report[key] == len(rows) for key in decoder.model._conditions_forward_accounting), "actual capture forward accounting differs")
    observer = sys.modules["ipfs_datasets_py.logic.formalization.autoencoder.retained_span_score_capture"]
    for source, scores, raw in zip(sources, captures, report["rows"], strict=True):
        _require(raw["source_sha256"] == hashlib.sha256(source["source_text"].encode()).hexdigest(), "raw source identity differs")
        observer._verify_greedy(source["source_text"], scores, raw)
    return {"schema": "modality-conditions-retention-adapter-target-free-head-capture/v1", "inference": report,
        "occurrences": [{"id": source["id"], "source_sha256": hashlib.sha256(source["source_text"].encode()).hexdigest(), "scores": scores}
            for source, scores in zip(sources, captures, strict=True)], "actual_source_forwards": len(rows), "source_model_forwards": len(rows),
        "actor_features_model_forwards":len(rows),"frozen_modality_encoder_forwards":len(rows),
        "frozen_span_encoder_forwards":len(rows),"additional_frozen_span_encoder_forwards":len(rows),
        "conditions_presence_head_forwards":len(rows),
        "extra_capture_forwards": 0, "model_weights_unchanged": True, "original_greedy_observations_verified": True,
        "ambient_CPU_RNG_preserved": True, "target_access": False, "teacher_forcing": False, **FALSE}


def _write_artifact(path, value):
    path = Path(path).absolute(); raw = _raw(value)
    _require(path.parent.resolve(strict=True) == path.parent, "canonical artifact parent required")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(raw); stream.flush(); os.fsync(stream.fileno())
    return {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}


def source_only_parity(torch, span, warm, checkpoint, rows, out, state_name):
    _require(type(state_name) is str and state_name in ("initial", "trained"), "closed parity state required")
    sources = [{key: row[key] for key in ("id", "source_text", "latent")} for row in rows[:2]]
    _require(len(sources) == 2, "two parity source rows required")
    sources = [dict(row, latent=[0.] * 384) for row in sources]
    alternate = [dict(row, latent=[.25 if index == 0 else -.25] * 384) for index, row in enumerate(sources)]
    controls = [("zeros", sources, "none"), ("alternate_placeholders", alternate, "none"),
        ("disabled", alternate, "disabled"), ("rotated_placeholders", alternate, "rotate")]
    captures, projection = [], None
    for name, inputs, control in controls:
        report = captured_inference(torch, span, warm, checkpoint, inputs, control=control)
        observed = [{"scores": capture["scores"], "raw": {key: raw.get(key) for key in
            ("status", "reason", "canonical_ir", "span_diagnostics", "minimum_decision_logit_margin")}}
            for capture, raw in zip(report["occurrences"], report["inference"]["rows"], strict=True)]
        if projection is None: projection = observed
        _require(_raw(observed) == _raw(projection), "disabled source-only scores changed under latent placeholder control")
        captures.append({"name": name, "control": control,
            "report": _write_artifact(Path(out) / (state_name + "-parity-" + name + ".json"), report)})
    return _write_artifact(Path(out) / (state_name + "-parity.json"),
        {"schema": "source-only-dormant384-placeholder-parity/v1", "passed": True, "controls": captures,
            "source_count": 2, "score_and_greedy_decisions_bit_equal": True,
            "genuine_latent_semantics_tested": False, "actual_encoder_calls": 0,
            "actual_external_latent_encoder_calls": 0, "source_model_forwards": 8,
            "frozen_modality_encoder_forwards":8,"frozen_span_encoder_forwards":8,"additional_frozen_span_encoder_forwards":8,
            "conditions_presence_head_forwards":8,"feature_paths_per_source_forward":3, **FALSE})


def save_checkpoint(checkpoint, path):
    validate_checkpoint(checkpoint)
    result = _write_artifact(path, checkpoint)
    return {**result, "schema": SCHEMA}


def load_checkpoint(path, *, expected_sha256):
    _require(type(expected_sha256) is str and span._SHA.fullmatch(expected_sha256), "expected checkpoint hash required")
    path = Path(path).absolute()
    _require(path.resolve(strict=True) == path, "canonical checkpoint path required")
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        before = os.fstat(stream.fileno())
        _require(stat.S_ISREG(before.st_mode) and before.st_size <= MAX_BYTES, "bounded regular checkpoint required")
        raw = stream.read(MAX_BYTES + 1); after = os.fstat(stream.fileno())
    _require(len(raw) <= MAX_BYTES and (before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns)
        and hashlib.sha256(raw).hexdigest() == expected_sha256, "checkpoint changed or raw hash differs")
    def unique(pairs):
        result = {}
        for key, value in pairs:
            _require(key not in result, "duplicate checkpoint JSON key")
            result[key] = value
        return result
    def reject(value): raise ValueError("invalid JSON constant: " + value)
    checkpoint = json.loads(raw, object_pairs_hook=unique, parse_constant=reject)
    validate_checkpoint(checkpoint)
    return checkpoint


def _active_rows(name):
    _require(name in TRAINABLE_PARAMETER_NAMES,'unknown trainable tensor')
    return (0,1,2) if name in MODALITY_NAMES else (3,)

def _inactive_rows(name):
    active = _active_rows(name)
    return () if active is None else tuple(i for i in range(_trainable_shapes()[name][0]) if i not in active)

def _teacher_text(value):
    return joint._teacher_text(value)

def _score_vector(value, width):
    return joint._score_vector(value, width)

def _block_values(scores, count):
    return joint._block_values(scores, count)

def _teacher_row(occurrence, record, index):
    return joint._teacher_row(occurrence, record, index)

def _teacher_targets(text, examples, expected_manifest):
    return joint._teacher_targets(text, examples, expected_manifest)

def _log_softmax(values):
    return joint._log_softmax(values)

def _kl_reference(teacher, candidate):
    return joint._kl_reference(teacher, candidate)


def run_gradient_controls(torch):
    """Exactly1 isolated synthetic forward/2rows/1Adam; guardian child only."""
    ambient=torch.get_rng_state().clone();incoming_grad_mode=torch.is_grad_enabled()
    with torch.random.fork_rng(devices=[]),torch.enable_grad():
        config=dict(hidden_size=32,embedding_dim=8,projection_width=8,latent_dimension=384,latent_enabled=False,residual_scale=.25,seed=1729)
        model=_model(torch,config);named,selected=_configure_parameters(model)
        with torch.no_grad():
            named['actor_attention.query'].copy_(torch.linspace(.01,.64,64))
            named['actor_context.gate'].copy_(torch.linspace(.001,.064,64))
        before={name:value.detach().tolist() for name,value in model.state_dict().items()}
        optimizer=torch.optim.Adam(selected,lr=.001,betas=(.9,.999),eps=1e-8,weight_decay=0.,foreach=False)
        records=[]
        for index,text in enumerate(('alpha beta gamma delta','other actor acts')):
            records.append(dict(id='guarded-synthetic-only-'+str(index),source_text=text,tokens=span.tokenize_source(text),latent=[0.]*384,
                labels=dict(modality=index,presence=[True,True,False,True,False,False],
                    spans=[(0,0),(1,1),(-100,-100),(2,2),(-100,-100),(-100,-100)])))
        model.train();optimizer.zero_grad(set_to_none=True);output=model(*span._batch(torch,records))
        teacher_rows=[];weight_rows=[]
        for index,record in enumerate(records):
            count=len(record['tokens']);vectors=dict(actor_start=output['start'][index,0,:count],actor_end=output['end'][index,0,:count],
                modality=output['modality'][index],conditions_start=output['start'][index,3,:count],conditions_end=output['end'][index,3,:count],
                exceptions_presence=output['presence'][index,2])
            blocks={name:dict(logits=value.detach().tolist(),gold_index=None,teacher_argmax=int(value.detach().argmax()),mask=False)
                for name,value in vectors.items()}
            sha=hashlib.sha256(record['source_text'].encode()).hexdigest()
            teacher_rows.append(dict(id=record['id'],training_index=index,token_count=count,source_sha256=sha,blocks=blocks))
            weight_rows.append(dict(id=record['id'],training_index=index,source_sha256=sha,
                tokens_sha256=checkpoint_digest([{key:t[key] for key in ('text','start','end')} for t in record['tokens']]),
                labels_sha256=checkpoint_digest(record['labels']),raw_output_sha256='0'*64,raw_status='decoded',raw_reason=None,
                error_fields=['conditions'] if index==0 else [],conditions_only_mask=index==0,conditions_facet_weight=2 if index==0 else 1))
        teacher_rows.extend(copy.deepcopy(teacher_rows[0]) for _ in range(166))
        weight_rows.extend(copy.deepcopy(weight_rows[0]) for _ in range(166))
        synthetic_teacher=dict(rows=teacher_rows,rows_sha256=checkpoint_digest(teacher_rows))
        synthetic_weights=dict(rows=weight_rows,rows_sha256=checkpoint_digest(weight_rows),near_complete_mask_sha256='0'*64)
        zero,_=_retention_loss(torch,output,records,[0,1],synthetic_teacher)
        gradients=torch.autograd.grad(zero,selected,retain_graph=True,allow_unused=True)
        _require(float(zero.detach())==0. and all(value is not None and bool((value==0).all()) for value in gradients),
            'all-masked KL must connect all six selected tensors with zero derivatives')
        protected=output['presence'].sum()+output['start'][:,(0,1,2,4,5),:].sum()+output['end'][:,(0,1,2,4,5),:].sum()
        protected_gradients=torch.autograd.grad(protected,selected,retain_graph=True,allow_unused=True)
        _require(all(value is None or bool((value==0).all()) for value in protected_gradients),'protected score gradient routes must be zero')
        loss,_=_loss(torch,output,records,[0,1],_policy('modality-conditions-retention-ce'),synthetic_teacher,synthetic_weights)
        loss.backward();_row_invariants(named,optimizer)
        torch.nn.utils.clip_grad_norm_(selected,5.,error_if_nonfinite=True);optimizer.step();_row_invariants(named,optimizer)
        after={name:value.detach().tolist() for name,value in model.state_dict().items()}
        _require(all(_raw(before[name])==_raw(after[name]) for name in BASE_PARAMETER_NAMES)
            and _raw(_inactive_state(before))==_raw(_inactive_state(after)),'fixture frozen36/inactive650 values changed')
        # Tensor-only arithmetic controls add zero model forwards or optimizer steps.
        facets=[torch.tensor([float(index+1),float(index+2)],dtype=torch.float32) for index in range(6)]
        modality=torch.tensor(1.25,dtype=torch.float32)
        baseline=(2*modality+sum(values.mean() for values in facets))/8
        for values in ([1.,1.],[2.,1.],[2.,2.]):
            weighted,unweighted=_weighted_main_loss(modality,facets,torch.tensor(values,dtype=torch.float32))
            expected=(2*modality+sum(v.mean() if index!=3 else (v*torch.tensor(values)).mean() for index,v in enumerate(facets)))/8
            _require(float(unweighted)==float(baseline) and float(weighted)==float(expected),'whole-facet0/1/2 weighted rows/fullB/outer8 differs')
        absent=torch.nn.functional.cross_entropy(torch.tensor([[2.,0.]],requires_grad=True),torch.tensor([-100]),ignore_index=-100,reduction='none')
        _require(float(absent[0].detach())==0.,'absent ignored pointer target must contribute zero CE')
        for magnitude in (1e20,-1e20):
            logits=torch.tensor([magnitude,magnitude],dtype=torch.float32,requires_grad=True)
            lp=torch.nn.functional.log_softmax(logits,dim=0)
            _require(bool(torch.isfinite(lp).all()) and abs(float(lp[0].detach())+math.log(2))<1e-6,'stable huge equal logits required')
        tensor_output=dict(modality=torch.zeros((2,3),dtype=torch.float32,requires_grad=True),presence=torch.zeros((2,4,2),dtype=torch.float32,requires_grad=True),
            start=torch.zeros((2,6,4),dtype=torch.float32,requires_grad=True),end=torch.zeros((2,6,4),dtype=torch.float32,requires_grad=True))
        tensor_rows=copy.deepcopy(teacher_rows);known=[math.log(.5),math.log(.25),math.log(.25)]
        tensor_rows[0]['blocks']['modality'].update(logits=known,mask=True,gold_index=0,teacher_argmax=0)
        tensor_rows[0]['blocks']['exceptions_presence'].update(logits=[0.,4.],mask=False,gold_index=0,teacher_argmax=1)
        def package():return dict(rows=tensor_rows,rows_sha256=checkpoint_digest(tensor_rows))
        one,_=_retention_loss(torch,tensor_output,records[:1],[0],package());half,_=_retention_loss(torch,tensor_output,records,[0,1],package())
        expected_KL=.5*math.log(1.5)+.5*math.log(.75)
        _require(abs(float(one.detach())-expected_KL/6)<1e-7 and abs(float(half.detach())-expected_KL/12)<1e-7,'KL must divide by6 times all rows including frozen/masked zeros')
        wrong_gradient,=torch.autograd.grad(half,[tensor_output['presence']],retain_graph=True)
        _require(bool((wrong_gradient==0).all()),'wrong teacher masked block contributes gradient')
        tensor_rows[1]['blocks']['modality'].update(logits=known,mask=True,gold_index=0,teacher_argmax=0)
        duplicate_records=copy.deepcopy(records);duplicate_records[1]['labels']['modality']=0
        duplicate,_=_retention_loss(torch,tensor_output,duplicate_records,[0,1],package())
        _require(abs(float(duplicate.detach())-float(one.detach()))<1e-7,'duplicated KL rows must preserve6B normalization')
        counters=dict(model._conditions_forward_accounting)
        _require(len(counters)==6 and all(type(value) is int and value==1 for value in counters.values()),'fixture must use exactly one full model forward')
        result=dict(schema='modality-conditions-retention-guarded-gradient-controls/v1',passed=True,findings=[],
            fixture_model_forwards=1,fixture_source_occurrences=2,fixture_optimizer_steps=1,actual_model_counter_deltas=counters,
            fixture_modality_encoder_forwards=1,fixture_span_encoder_forwards=2,all6_gradients_finite_connected=True,
            all36_frozen_gradients_None=True,all650_inactive_gradients_moments_zero_and_values_unchanged=True,
            actor_query_gate_and_all_presence_frozen=True,protected_score_gradient_routes_zero=True,
            all_masked_retention_graph_connected_zero=True,weighted_CE_0_1_2_rows_passed=True,ignored_absent_pointer_CE_zero=True,
            huge_equal_logit_stability_passed=True,active_KL_full6B_normalization_passed=True,active_mask_count_does_not_renormalize=True,
            duplicate_row_invariance_passed=True,wrong_teacher_masked_gradient_zero=True,
            synthetic_parameters_and_optimizer_separate=True,teacher_model_forwards=0,real_candidate_or_teacher_access=False,experimental_updates_included=False)
    _require(torch.equal(ambient,torch.get_rng_state()),'fixture changed ambient CPU RNG')
    _require(torch.is_grad_enabled() is incoming_grad_mode,'fixture changed incoming grad mode')
    result.update(ambient_CPU_RNG_preserved=True,ambient_grad_mode_preserved=True)
    return result

def _retention_loss(torch, output, records, indices, teacher):
    return joint._retention_loss(torch, output, records, indices, teacher)


def _validate_teacher_entry(entry, teacher):
    return joint._validate_teacher_entry(entry, teacher)


def _strict_teacher_json(text):
    def unique(pairs):
        value={}
        for key,item in pairs:
            _require(key not in value,'duplicate teacher JSON key');value[key]=item
        return value
    return json.loads(text,object_pairs_hook=unique,
        parse_constant=lambda value:(_ for _ in ()).throw(ValueError('nonfinite teacher JSON')))


def _weight_row(occurrence,raw,record,example,index):
    _require(type(index) is int and 0<=index<168 and occurrence['id']==record['id']==example['id'],
        'exact ordered training weight membership required')
    sha=hashlib.sha256(record['source_text'].encode()).hexdigest()
    _require(occurrence['source_sha256']==raw['source_sha256']==sha,'raw teacher weight source differs')
    capture._verify_greedy(record['source_text'],occurrence['scores'],raw)
    gold=span.codec_module._rule(example['canonical_ir'])
    if raw['status']=='decoded':
        predicted=span.codec_module._rule(raw['canonical_ir'])
        errors=[field for field in ERROR_FIELDS if _raw(predicted[field])!=_raw(gold[field])]
    else:
        _require(raw['status']=='abstained','closed teacher raw status required');errors=list(ERROR_FIELDS)
    selected=raw['status']=='decoded' and errors==['conditions']
    return dict(id=record['id'],training_index=index,source_sha256=sha,
        tokens_sha256=checkpoint_digest(occurrence['scores']['tokens']),labels_sha256=checkpoint_digest(record['labels']),
        raw_output_sha256=checkpoint_digest(raw),raw_status=raw['status'],raw_reason=raw['reason'],error_fields=errors,
        conditions_only_mask=selected,conditions_facet_weight=2 if selected else 1)


def _training_targets(teacher_capture_raw,training_examples,expected_manifest):
    text=_teacher_text(teacher_capture_raw)
    teacher=_teacher_targets(text,training_examples,expected_manifest)
    records=_training_records(training_examples);value=_strict_teacher_json(text)
    _require(len(value['inference']['rows'])==len(records)==168,'complete F15 raw inference membership required')
    rows=[_weight_row(occurrence,raw,record,example,index) for index,(occurrence,raw,record,example)
        in enumerate(zip(value['occurrences'],value['inference']['rows'],records,training_examples,strict=True))]
    selected=[row['id'] for row in rows if row['conditions_only_mask']]
    _require(len(selected)==2 and all('-condition_exception_duration-' in name for name in selected),
        'exact two independently derived training conditions-only rows required')
    weights=dict(schema='source-authenticated-F15-conditions-only-row-weights/v1',
        teacher_capture_sha256=TEACHER_CAPTURE_SHA256,training_manifest_sha256=expected_manifest,rows=rows,
        row_ID_order_sha256=checkpoint_digest([row['id'] for row in rows]),rows_sha256=checkpoint_digest(rows),
        near_complete_mask_sha256=checkpoint_digest([{key:row[key] for key in
            ('id','training_index','conditions_only_mask','conditions_facet_weight')} for row in rows]),
        selected_count=2,selected_ids=selected,derived_before_update0=True,
        candidate_predictions_used=False,evaluation_references_used=False)
    return dict(teacher_training=teacher,row_weight_training=weights)


def _mask_certificate_targets(teacher,weights):
    rows=[]
    for index,(weight,target) in enumerate(zip(weights['rows'],teacher['rows'],strict=True)):
        _require(weight['training_index']==target['training_index']==index and weight['id']==target['id']
            and weight['source_sha256']==target['source_sha256'],'weight and KL target memberships differ')
        rows.append({**copy.deepcopy(weight),'teacher_components':copy.deepcopy(target['blocks'])})
    return dict(schema='modality-conditions-training-mask-targets/v1',
        source_actor_refinement_checkpoint_sha256=SOURCE_ACTOR_REFINEMENT_SHA256,
        source_actor_refinement_model_state_sha256=SOURCE_ACTOR_REFINEMENT_MODEL_SHA256,
        teacher_capture_sha256=TEACHER_CAPTURE_SHA256,training_manifest_sha256=teacher['training_manifest_sha256'],
        row_count=168,selected_count=weights['selected_count'],selected_ids=list(weights['selected_ids']),
        row_ID_order_sha256=weights['row_ID_order_sha256'],rows=rows,rows_sha256=checkpoint_digest(rows),
        near_complete_mask_sha256=weights['near_complete_mask_sha256'],row_weight_rows_sha256=weights['rows_sha256'],
        teacher_targets_sha256=checkpoint_digest(teacher))


def _validate_training_mask_certificate(certificate,teacher,weights):
    _require(type(certificate) is dict and certificate.get('schema')=='modality-conditions-training-mask/v1'
        and certificate.get('passed') is True and certificate.get('findings')==[],
        'qualified complete training-mask certificate required')
    expected=_mask_certificate_targets(teacher,weights)
    _require(_raw(certificate.get('targets'))==_raw(expected),
        'all168 mask/correct-teacher/source/label roots must equal independently derived certificate targets')
    return expected


def _weight_batch(records,indices,weights):
    _require(type(weights) is dict and weights['rows_sha256']==checkpoint_digest(weights['rows'])
        and len(weights['rows'])==168 and len(records)==len(indices)>0,'frozen complete training weight table required')
    rows=[]
    for record,index in zip(records,indices,strict=True):
        _require(type(index) is int and 0<=index<168,'typed bounded weight membership required')
        row=weights['rows'][index]
        tokens=[{key:token[key] for key in ('text','start','end')} for token in record['tokens']]
        _require(row['id']==record['id'] and row['training_index']==index
            and row['source_sha256']==hashlib.sha256(record['source_text'].encode()).hexdigest()
            and row['labels_sha256']==checkpoint_digest(record['labels']) and row['tokens_sha256']==checkpoint_digest(tokens)
            and type(row['conditions_only_mask']) is bool and type(row['conditions_facet_weight']) is int
            and row['conditions_facet_weight']==(2 if row['conditions_only_mask'] else 1)
            and row['conditions_only_mask'] is (row['raw_status']=='decoded' and row['error_fields']==['conditions']),
            'actual batch index/ID/source/tokens/gold/weight must join fixed parent training roots')
        rows.append(copy.deepcopy(row))
    return rows


def _weighted_main_loss(modality,facet_rows,weights):
    _require(type(facet_rows) in (list,tuple) and len(facet_rows)==6,'exact six legacy facet row vectors required')
    unweighted=[values.mean() for values in facet_rows]
    weighted=list(unweighted);weighted[3]=(facet_rows[3]*weights).mean()
    return (2*modality+sum(weighted))/8,(2*modality+sum(unweighted))/8


def _scalar32(value):
    _require(type(value) is float and math.isfinite(value) and targeted._f32(value)==value,'finite reported float32 scalar required')
    return value


def _check_mean(value,rows):
    _scalar32(value)
    _require(rows and all(type(x) is float and math.isfinite(x) for x in rows),'finite complete batch scalars required')
    reference=math.fsum(rows)/len(rows)
    _require(abs(value-reference)<=2e-6*max(1.,math.fsum(abs(x) for x in rows)/len(rows)),'fullB reported mean differs')


def _main_from_means(modality,facets):
    total=0.
    for value in facets:total=targeted._f32(total+value)
    return targeted._f32(targeted._f32(targeted._f32(2*modality)+total)/8)


def _validate_CE_entry(ce,batch,weights=None):
    fields={'schema','rows','batch_denominator','outer_denominator','modality_multiplier','modality_CE_mean','facet_CE_means',
        'weighted_facet_CE_means','weighted_main_loss','unweighted_main_loss','row_weight_rows_sha256','near_complete_mask_sha256',
        'actor_hinge_applied','actor_hinge_omitted','teacher_forcing','evaluation_references_used'}
    _require(type(ce) is dict and set(ce)==fields and ce['schema']=='modality-conditions-entire-facet-weighted-CE/v1'
        and ce['actor_hinge_applied'] is False and ce['actor_hinge_omitted'] is True
        and ce['teacher_forcing'] is True and ce['evaluation_references_used'] is False
        and type(ce['batch_denominator']) is int and ce['batch_denominator']==len(batch['indices'])==len(batch['ids'])==len(ce['rows'])
        and 0<ce['batch_denominator']<=12 and type(ce['outer_denominator']) is int and ce['outer_denominator']==8
        and type(ce['modality_multiplier']) is int and ce['modality_multiplier']==2,'closed weighted entire-facet CE contract required')
    for key in ('row_weight_rows_sha256','near_complete_mask_sha256'):
        _require(type(ce[key]) is str and span._SHA.fullmatch(ce[key]),'fixed weight/mask SHA required')
    if weights is not None:
        _require(ce['row_weight_rows_sha256']==weights['rows_sha256']==checkpoint_digest(weights['rows'])
            and ce['near_complete_mask_sha256']==weights['near_complete_mask_sha256'],'trace fixed training mask roots differ')
    for index,identifier,row in zip(batch['indices'],batch['ids'],ce['rows'],strict=True):
        keys={'id','training_index','source_sha256','weight_target_sha256','conditions_facet_weight','modality_CE','facet_CEs',
            'conditions_presence_CE','conditions_start_CE','conditions_end_CE','weighted_conditions_facet_CE'}
        _require(type(index) is int and 0<=index<168 and type(row) is dict and set(row)==keys
            and row['id']==identifier and type(row['training_index']) is int and row['training_index']==index
            and type(row['conditions_facet_weight']) is int and row['conditions_facet_weight'] in (1,2)
            and type(row['facet_CEs']) is list and len(row['facet_CEs'])==6,'typed CE row/ID/index/weight join required')
        for key in ('source_sha256','weight_target_sha256'):
            _require(type(row[key]) is str and span._SHA.fullmatch(row[key]),'source and exact row-weight target SHA required')
        for value in [row['modality_CE'],*row['facet_CEs'],row['conditions_presence_CE'],row['conditions_start_CE'],row['conditions_end_CE'],row['weighted_conditions_facet_CE']]:
            _require(_scalar32(value)>=0.,'nonnegative CE scalar required')
        facet=targeted._f32(row['conditions_presence_CE']+targeted._f32(targeted._f32(row['conditions_start_CE']+row['conditions_end_CE'])*.5))
        _require(row['facet_CEs'][3]==facet and row['weighted_conditions_facet_CE']==targeted._f32(facet*row['conditions_facet_weight']),
            'whole conditions presence-plus-pointer facet must carry the fixed integer weight')
        if weights is not None:
            expected=weights['rows'][index]
            _require(expected['id']==identifier and expected['training_index']==index and expected['source_sha256']==row['source_sha256']
                and checkpoint_digest(expected)==row['weight_target_sha256'] and expected['conditions_facet_weight']==row['conditions_facet_weight'],
                'actual row weight/membership must match authenticated immutable parent mask')
    _require(type(ce['facet_CE_means']) is list and type(ce['weighted_facet_CE_means']) is list
        and len(ce['facet_CE_means'])==len(ce['weighted_facet_CE_means'])==6,'six facet means required')
    _check_mean(ce['modality_CE_mean'],[row['modality_CE'] for row in ce['rows']])
    for field in range(6):
        _check_mean(ce['facet_CE_means'][field],[row['facet_CEs'][field] for row in ce['rows']])
        if field==3:_check_mean(ce['weighted_facet_CE_means'][field],[row['weighted_conditions_facet_CE'] for row in ce['rows']])
        else:_require(ce['weighted_facet_CE_means'][field]==ce['facet_CE_means'][field],'unselected facets must be unchanged')
    _require(ce['unweighted_main_loss']==_main_from_means(ce['modality_CE_mean'],ce['facet_CE_means'])
        and ce['weighted_main_loss']==_main_from_means(ce['modality_CE_mean'],ce['weighted_facet_CE_means']),
        'legacy modality2/six-facet sum/fullB/outer8 float32 association differs')
