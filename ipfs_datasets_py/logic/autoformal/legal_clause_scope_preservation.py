"""Matched scope preservation objectives over the immutable attention graph.

Readout freezing and teacher KL are independent training interventions. The
teacher is the original boundary checkpoint, and its scope logits only anchor
TRAIN rows whose predicted class agrees with the authored scope label. This
facet-level agreement does not establish legal scope or source-text fidelity.
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import hashlib

from . import legal_clause_scope_adapter as adapter

boundary = adapter.boundary
require, digest = adapter.require, adapter.digest
SCHEMA = 'legal-clause-scope-preservation-checkpoint/v1'
ARMS = ('control', 'freeze_readout', 'distill', 'freeze_distill')
SEED = adapter.SEED
ADAPTER_CONFIG = deepcopy(adapter.ADAPTER_CONFIG)
SCOPE_PARAMETERS = adapter.SCOPE_PARAMETERS
ADAPTER_PARAMETERS = adapter.ADAPTER_PARAMETERS
READOUT_FROZEN = {'control':False, 'freeze_readout':True, 'distill':False, 'freeze_distill':True}
DISTILLATION_WEIGHTS = {'control':0., 'freeze_readout':0., 'distill':1., 'freeze_distill':1.}
TRAINABLE_COUNTS = {'control':1317, 'freeze_readout':1187, 'distill':1317, 'freeze_distill':1187}
TEACHER_CONFIG = {'teacher':'immutable_original_boundary_parent', 'temperature':1.,
    'mask':'argmax_scope_class_equals_authored_TRAIN_label',
    'tie_policy':'first_argmax_index_matches_frozen_parent_scope_decision',
    'direction':'KL(parent||candidate)', 'reduction':'mean_over_correct_teacher_rows',
    'empty_mask':'differentiable_zero', 'class_weights_applied_to_KL':False,
    'teacher_gradients_enabled':False, 'teacher_predictions_used_at_inference':False}
BASE_KEYS = {'schema','profile','implementation_sha256','boundary_implementation_sha256','parent_checkpoint',
    'parent_checkpoint_sha256','parent_file_sha256','arm','seed','adapter_config','training_config','model_state',
    'initial_model_state_sha256','frozen_non_scope_state_sha256','trainable_parameters','trainable_parameter_count',
    'additional_optimizer_steps','optimizer_steps','training_manifest_sha256','tuning_manifest_sha256',
    'optimizer_resumption_supported','source_text_only_numeric_input','scope_threshold_and_surface_policy_unchanged',*boundary.FALSE}
EXTRA_KEYS = {'adapter_implementation_sha256','readout_frozen','teacher_config'}


def implementation_sha():
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def arm_config(arm):
    require(type(arm) is str and arm in ARMS, 'known scope preservation arm required')
    return {**deepcopy(adapter.TRAINING_CONFIG), 'teacher_kl_weight':DISTILLATION_WEIGHTS[arm]}


def trainable_names(arm):
    arm_config(arm)
    return ADAPTER_PARAMETERS | (frozenset() if READOUT_FROZEN[arm] else SCOPE_PARAMETERS)


def model(torch):
    """Reuse the exact pinned attention computation; only trainability differs."""
    return adapter.model(torch)


def configure_trainable(network, arm):
    names=trainable_names(arm)
    for name,parameter in network.named_parameters():parameter.requires_grad_(name in names)
    require({name for name,p in network.named_parameters() if p.requires_grad} == names,
            'complete scope preservation trainable inventory required')
    parameters=[p for p in network.parameters() if p.requires_grad]
    require(sum(p.numel() for p in parameters) == TRAINABLE_COUNTS[arm], 'scope preservation trainable count differs')
    network.arm=arm;network.eval()
    return parameters


frozen_state = adapter.frozen_state


def assert_frozen_state(parent_state, candidate_state, *, arm=None):
    committed=adapter.assert_frozen_state(parent_state,candidate_state)
    if arm is not None:
        arm_config(arm)
        if READOUT_FROZEN[arm]:
            require(all(candidate_state[name] == parent_state[name] for name in SCOPE_PARAMETERS),
                    'frozen scope readout changed from immutable original parent')
    return committed


def build_checkpoint(parent_payload, *, arm, seed=SEED, training_manifest_sha256,
                     tuning_manifest_sha256, parent_file_sha256):
    config=arm_config(arm)
    value=adapter.build_checkpoint(parent_payload,arm='adapter',seed=seed,
        training_manifest_sha256=training_manifest_sha256,tuning_manifest_sha256=tuning_manifest_sha256,
        parent_file_sha256=parent_file_sha256)
    value.update(schema=SCHEMA,implementation_sha256=implementation_sha(),
        adapter_implementation_sha256=adapter.implementation_sha(),arm=arm,training_config=config,
        readout_frozen=READOUT_FROZEN[arm],teacher_config=deepcopy(TEACHER_CONFIG),
        trainable_parameters=sorted(trainable_names(arm)),trainable_parameter_count=TRAINABLE_COUNTS[arm])
    return value


def restore(value):
    require(type(value) is dict and set(value) == BASE_KEYS | EXTRA_KEYS, 'closed scope preservation checkpoint required')
    require(value['schema'] == SCHEMA and value['implementation_sha256'] == implementation_sha()
        and value['adapter_implementation_sha256'] == adapter.implementation_sha(), 'scope preservation producer differs')
    arm=value['arm'];expected_config=arm_config(arm)
    require(value['training_config'] == expected_config and value['teacher_config'] == TEACHER_CONFIG
        and value['readout_frozen'] is READOUT_FROZEN[arm], 'scope preservation loss or readout-freeze contract differs')
    require(value['trainable_parameters'] == sorted(trainable_names(arm))
        and value['trainable_parameter_count'] == TRAINABLE_COUNTS[arm], 'scope preservation trainable inventory differs')
    # Project only declared wrapper fields. The earlier runtime still validates
    # the exact parent, full numerical initial state, finite shapes, step bounds,
    # source-only decoder policy, and all immutable non-scope parameters.
    projected={key:deepcopy(value[key]) for key in BASE_KEYS}
    projected.update(schema=adapter.SCHEMA,implementation_sha256=adapter.implementation_sha(),
        arm='adapter',training_config=deepcopy(adapter.TRAINING_CONFIG),
        trainable_parameters=sorted(adapter.trainable_names('adapter')),trainable_parameter_count=1317)
    torch,network=adapter.restore(projected)
    assert_frozen_state(value['parent_checkpoint']['model_state'],value['model_state'],arm=arm)
    configure_trainable(network,arm)
    return torch,network


def checkpoint(network, *, initial_checkpoint, additional_steps):
    restore(initial_checkpoint)
    require(initial_checkpoint['additional_optimizer_steps'] == 0, 'immutable zero-step scope preservation checkpoint required')
    require(getattr(network,'arm',None) == initial_checkpoint['arm'], 'scope preservation network arm differs')
    require({name for name,p in network.named_parameters() if p.requires_grad} == trainable_names(initial_checkpoint['arm']),
            'scope preservation network trainability changed')
    result=deepcopy(initial_checkpoint)
    result.update(model_state=adapter._state(network),additional_optimizer_steps=additional_steps,
        optimizer_steps=initial_checkpoint['parent_checkpoint']['optimizer_steps']+additional_steps)
    restore(result)
    return result


def objective_loss(torch, candidate_logits, labels, *, teacher_logits, arm):
    """TRAIN-only class CE plus separately normalized parent-correct teacher KL.

    Controls execute the same teacher/mask/KL computation with zero coefficient.
    The caller computes teacher_logits from the immutable parent in eval/no_grad;
    detaching here additionally prevents accidental teacher gradient propagation.
    """
    config=arm_config(arm)
    require(candidate_logits.is_floating_point() and teacher_logits.is_floating_point()
        and candidate_logits.dtype == teacher_logits.dtype and candidate_logits.device == teacher_logits.device
        and candidate_logits.ndim == 2 and teacher_logits.shape == candidate_logits.shape
        and bool(torch.isfinite(candidate_logits).all()) and bool(torch.isfinite(teacher_logits).all()),
        'same finite two-class candidate and teacher logit shape/dtype/device required')
    cross_entropy,parts=adapter.scope_loss(torch,candidate_logits,labels)
    teacher=teacher_logits.detach()
    mask=teacher.argmax(dim=-1)==labels
    teacher_log_probability=torch.log_softmax(teacher,dim=-1)
    candidate_log_probability=torch.log_softmax(candidate_logits,dim=-1)
    row_kl=(teacher_log_probability.exp()*(teacher_log_probability-candidate_log_probability)).sum(dim=-1)
    eligible=int(mask.sum())
    kl=row_kl[mask].mean() if eligible else candidate_logits.sum()*0.
    weighted=config['teacher_kl_weight']*kl
    total=cross_entropy+weighted
    require(bool(torch.isfinite(kl)) and bool(torch.isfinite(total)), 'finite masked scope preservation loss required')
    parts.update(teacher_correct_count=eligible,
        teacher_correct_unsupported_count=int((mask & (labels==0)).sum()),
        teacher_correct_supported_count=int((mask & (labels==1)).sum()),
        teacher_correct_mask=mask.detach().cpu().tolist(),
        teacher_scope_logits=teacher.cpu().tolist(),teacher_scope_logits_sha256=digest(teacher.cpu().tolist()),
        teacher_kl=float(kl.detach()),teacher_kl_weight=config['teacher_kl_weight'],
        weighted_teacher_kl=float(weighted.detach()),total_loss=float(total.detach()),
        teacher_kl_temperature=1.,teacher_logits_detached=True,
        teacher_kl_class_weighted=False)
    return total,parts


class ScopePreservationDecoder(boundary.ClauseBoundaryDecoder):
    def __init__(self,value):
        self.torch,self.network=restore(value)
        self.checkpoint=deepcopy(value)
        self.checkpoint_sha256=digest(value)


def decoder(value):
    """Use the original inference policy for old parent or new trained states."""
    return boundary.ClauseBoundaryDecoder(value) if value.get('schema') == boundary.SCHEMA else ScopePreservationDecoder(value)
