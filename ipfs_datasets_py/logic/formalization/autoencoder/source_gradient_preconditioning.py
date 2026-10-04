"""Opt-in TRAIN-only covariance preconditioning of one8D sidecar gradient.

The fixed matrix changes a gradient before the existing global clip and AdamW;
this is not input whitening, a natural-gradient guarantee, or a new loss. Source
features, frozen preprocessing, forward functions and qualification stay intact.
"""
from copy import deepcopy
import hashlib
import math
import time

from . import decoder_distillation_experiment as core

SCHEMA = 'eight-dimensional-source-gradient-preconditioner/v1'
PARAMETER = 'non_action_head.source_projection.weight'
POLICIES = ('identity', 'train_covariance_inverse')
MAX_CONDITION = 32.
TOLERANCE = 2e-5


def _require(value, message):
    if not value: raise ValueError(message)


def _deadline(deadline):
    _require(type(deadline) in (int, float) and math.isfinite(deadline), 'finite shared deadline required')
    if time.monotonic() >= deadline: raise TimeoutError('source-gradient preconditioning deadline')


def estimate_training_work_bytes(*, max_optimizer_steps):
    _require(type(max_optimizer_steps) is int and 1 <= max_optimizer_steps <= 100000, 'bounded update inventory required')
    return 1048576 + (max_optimizer_steps+1)*64*8*2*40


def matrix_from_features(torch, features, *, policy):
    """Label-free numerical kernel; rows are already the actual TRAIN features."""
    _require(type(policy) is str and policy in POLICIES, 'explicit registered preconditioning policy required')
    _require(isinstance(features, torch.Tensor) and features.dtype == torch.float32
        and features.device.type == 'cpu' and features.ndim == 2 and features.shape[1] == 8
        and 2 <= len(features) <= 4096 and not features.requires_grad and bool(torch.isfinite(features).all()),
        'bounded finite detached actual8D TRAIN features required')
    values=features.double();center=values.mean(dim=0);centered=values-center
    covariance=centered.T@centered/len(values)
    eigenvalues,eigenvectors=torch.linalg.eigh(covariance)
    average=float(torch.trace(covariance))/8
    ridge=max(average*1e-3,1e-6)
    regularized=eigenvalues+ridge
    floor=float(regularized.max())/MAX_CONDITION
    clipped=regularized.clamp_min(floor)
    if policy == 'identity':
        matrix=torch.eye(8,dtype=torch.float32)
    else:
        inverse=clipped.reciprocal();inverse=inverse/(inverse.sum()/8)
        matrix=((eigenvectors*inverse.unsqueeze(0))@eigenvectors.T).float()
        matrix=(matrix+matrix.T)*.5
    spectrum=torch.linalg.eigvalsh(matrix.double())
    _require(bool(torch.isfinite(matrix).all()) and torch.equal(matrix,matrix.T)
        and float(spectrum.min())>0 and float(spectrum.max()/spectrum.min()) <= MAX_CONDITION*(1+TOLERANCE)
        and abs(float(torch.trace(matrix))-8.) <= TOLERANCE*8, 'finite bounded SPD trace8 matrix required')
    receipt=dict(policy=policy,dimension=8,feature_rows=len(values),feature_mean=center.tolist(),
        actual_train_features=features.tolist(),actual_train_features_sha256=core.digest(features.tolist()),
        covariance=covariance.tolist(),covariance_eigenvalues=eigenvalues.tolist(),ridge=ridge,
        minimum_regularized_eigenvalue=floor,clipped_regularized_eigenvalues=clipped.tolist(),
        matrix=matrix.tolist(),matrix_sha256=core.digest(matrix.tolist()),matrix_eigenvalues=spectrum.tolist(),
        matrix_trace=float(torch.trace(matrix)),matrix_condition=float(spectrum.max()/spectrum.min()),
        covariance_dtype='float64',applied_matrix_dtype='float32',condition_cap=MAX_CONDITION,
        post_cast_relative_tolerance=TOLERANCE,trace_target=8.,identity_performs_no_gradient_arithmetic=policy=='identity',
        normalization='inverse_regularized_covariance_normalized_to_trace8',reference_labels_used_for_fitting=False)
    return matrix,receipt


class _Prepared:
    __slots__=('_model','_parameter','_matrix','_matrix_version','_fixed','_receipt','_next_step')
    def __setattr__(self,name,value):raise AttributeError('prepared source-gradient matrix is immutable')
    @property
    def receipt(self):return deepcopy(self._receipt)


def prepare(torch,model,training_sources,training_contexts,*,input_transform,policy,deadline):
    started=time.monotonic();_deadline(deadline)
    _require(type(policy) is str and policy in POLICIES, 'registered policy required')
    specification=model.describe()
    _require(model.dimension==8 and specification.get('schema')=='ordered-clause-recurrent-source-decoder-development/v1',
        'explicit ordered8D formula sidecar required')
    _require(type(training_sources) is list and 1 <= len(training_sources) <= 4096
        and all(type(row) is dict and set(row)=={'id','source_text'} for row in training_sources),
        'closed TRAIN source identities and text only; no target fields')
    from . import clause_source_context
    context_receipt=clause_source_context.validate_contexts(training_sources,training_contexts)
    normalization=specification['clause_normalization']
    _require(context_receipt['contexts_sha256']==normalization['training_contexts_sha256']
        and context_receipt['clause_inventory']==normalization['training_inventory']
        and [r['id'] for r in training_sources]==specification['normalization']['expected_training_ids'],
        'actual source cohort differs from frozen TRAIN normalization')
    named=dict(model.named_parameters());parameter=named.get(PARAMETER)
    _require(isinstance(parameter,torch.nn.Parameter) and parameter.requires_grad and parameter.dtype==torch.float32
        and parameter.device.type=='cpu' and tuple(parameter.shape)==(64,8), 'exact trainable64by8 non-action projection required')
    fixed=tuple((name,value,value._version) for name,value in list(model.named_buffers())+
        [(n,p) for n,p in model.named_parameters() if not p.requires_grad])
    seen=set();vectors=[];inventory=[]
    with torch.no_grad():
        for row in training_sources:
            _deadline(deadline)
            packet=core._source_context_kwargs(torch,[row],training_contexts,input_transform)['source_context']
            # Actual model path: transformed cached clauses -> frozen residual
            # projection -> frozen clause normalization. No field head executes.
            features,mask=model.clause_features(torch.zeros((1,8),dtype=torch.float32),source_context=packet)
            _require(tuple(features.shape)==(1,8,8) and torch.equal(mask,packet['mask'])
                and features.dtype==torch.float32 and bool(torch.isfinite(features).all()),'finite actual normalized clause features required')
            for index,segment in enumerate(training_contexts[row['id']]['segments']):
                key=segment['source_sha256']
                if key in seen:continue
                seen.add(key);vectors.append(features[0,index].detach().clone());inventory.append(dict(id='clause:'+key,source_sha256=key))
    _require(inventory==normalization['training_inventory'] and len(vectors)>=2,'exact unique TRAIN clause inventory required')
    matrix,receipt=matrix_from_features(torch,torch.stack(vectors),policy=policy);_deadline(deadline)
    receipt.update(schema=SCHEMA,parameter_name=PARAMETER,training_source_inventory=inventory,
        training_contexts_sha256=context_receipt['contexts_sha256'],input_transform=deepcopy(input_transform),
        frozen_clause_normalization_sha256=core.digest(normalization),
        fit_split='train_only_unique_source_clauses',validation_vectors_used=0,validation_labels_used=False,
        source_encoder_changed=False,forward_function_changed=False,architecture_changed=False,
        fixed_matrix_per_fit=True,application='right_multiply_accumulated_gradient_before_existing_global_clip_and_AdamW',
        global_clip_can_change_other_parameter_updates=True,descent_guaranteed=False,convergence_proven=False,
        qualified=False,admitted=False,lake_executed=False,elapsed_seconds=time.monotonic()-started)
    result=_Prepared()
    for name,value in dict(_model=model,_parameter=parameter,_matrix=matrix,_matrix_version=matrix._version,
                          _fixed=fixed,_receipt=receipt,_next_step=0).items():object.__setattr__(result,name,value)
    return result


def apply(torch,model,cache,*,committed_step,deadline):
    _deadline(deadline)
    _require(type(cache) is _Prepared and model is cache._model and type(committed_step) is int
        and committed_step==cache._next_step,'one ordered application per committed optimizer step required')
    _require(dict(model.named_parameters()).get(PARAMETER) is cache._parameter
        and cache._matrix._version==cache._matrix_version,'prepared parameter or matrix changed')
    current=dict(model.named_buffers());current.update(dict(model.named_parameters()))
    _require(all(current.get(name) is value and value._version==version for name,value,version in cache._fixed),
        'frozen model preprocessing changed')
    gradient=cache._parameter.grad
    _require(isinstance(gradient,torch.Tensor) and gradient.dtype==torch.float32 and gradient.device.type=='cpu'
        and tuple(gradient.shape)==(64,8) and not gradient.requires_grad and bool(torch.isfinite(gradient).all()),
        'finite accumulated non-action projection gradient required')
    before=gradient.detach().clone()
    if cache._receipt['policy']!='identity':
        with torch.no_grad():gradient.copy_(gradient@cache._matrix)
    _require(bool(torch.isfinite(gradient).all()),'nonfinite preconditioned gradient')
    after=gradient.detach().clone();_deadline(deadline)
    object.__setattr__(cache,'_next_step',committed_step+1)
    return dict(schema='source-gradient-preconditioning-step/v1',committed_step=committed_step,
        parameter_name=PARAMETER,policy=cache._receipt['policy'],matrix_sha256=cache._receipt['matrix_sha256'],
        before=before.tolist(),after=after.tolist(),before_l2=float(before.double().norm()),after_l2=float(after.double().norm()),
        gradient_inner_product=float((before.double()*after.double()).sum()),
        other_gradients_modified_by_helper=False,before_global_clip=True,additional_loss=False,
        qualified=False,admitted=False)
