"""Opt-in object CE on the same authenticated source batches as modality CE.

No new source or target inventory, encoder, recurrent/count forward, optimizer,
preprocessing fit, generation mask, or qualification authority is introduced.
The fixed Legal training bank and sampler remain owned by the modality helper;
this distinct loss checks complete authored targets before selecting object IDs.
"""
from copy import deepcopy
import time
from . import source_modality_auxiliary_training as shared
from . import source_value_decoder_experiment as values

SCHEMA='cached-training-object-bank/v1'
LOSS_SCHEMA='training-source-object-auxiliary/v1'
FALSE=dict(shared.FALSE)


def estimate_training_work_bytes(bank, *, max_optimizer_steps):
    return shared.estimate_training_work_bytes(bank,max_optimizer_steps=max_optimizer_steps)+bank['selected_rows']*16+1048576


def validate_training_binding(*args,**kwargs):
    result=shared.validate_training_binding(*args,**kwargs)
    return dict(result,auxiliary_loss_field='object',new_reference_labels_introduced=False)


class _ObjectCache:
    __slots__=('_source','_targets','_target_version','_objects','_receipt')
    def __setattr__(self,name,value):raise AttributeError('prepared object cache is immutable')
    @property
    def receipt(self):return deepcopy(self._receipt)


def prepare_tensor_cache(torch,model,bank,*,codec,input_transform,seed,deadline,max_optimizer_steps=340):
    started=time.monotonic();shared._deadline(deadline)
    source=shared.prepare_tensor_cache(torch,model,bank,codec=codec,input_transform=input_transform,
        seed=seed,deadline=deadline,max_optimizer_steps=max_optimizer_steps)
    objects=[];ids=[]
    for row in bank['rows']:
        shared._deadline(deadline)
        rule=shared._source(row['source_text'],row['wording_style'])
        shared._require(row['target_sha256']==shared.digest({'rules':[rule]}),'complete training object target differs')
        objects.append(rule['object']);ids.append(codec['target_vocabulary'].index('"'+rule['object']+'"'))
    targets=torch.tensor(ids,dtype=torch.long)
    receipt=source.receipt
    receipt.update(schema=SCHEMA,loss_field='object',target_token_ids_sha256=shared.digest(ids),
        object_class_counts={name:objects.count(name) for name in sorted(set(objects))},
        cached_tensor_bytes=receipt['cached_tensor_bytes']+targets.numel()*targets.element_size(),
        estimated_training_work_bytes=estimate_training_work_bytes(bank,max_optimizer_steps=max_optimizer_steps),
        source_indices_identical_to_modality_control=True,new_reference_labels_introduced=False,
        class_balancing_added=False,elapsed_seconds=time.monotonic()-started)
    result=_ObjectCache()
    for name,value in dict(_source=source,_targets=targets,_target_version=targets._version,
                           _objects=tuple(objects),_receipt=receipt).items():object.__setattr__(result,name,value)
    shared._deadline(deadline);return result


def select_indices(cache,committed_step):
    shared._require(type(cache) is _ObjectCache,'prepared object cache required')
    return shared.select_indices(cache._source,committed_step)


def object_loss(torch,model,cache,*,committed_step,deadline):
    started=time.monotonic();shared._deadline(deadline);indices=select_indices(cache,committed_step);source=cache._source
    shared._require(model is source._model,'cache belongs to another model')
    tensors=(source._data,source._vectors,source._mask,source._targets)
    shared._require(tuple(t._version for t in tensors)==source._versions
        and cache._targets._version==cache._target_version,'private cached object sources/targets changed')
    current=dict(model.named_buffers());current.update(dict(model.named_parameters()))
    shared._require(all(current.get(name) is value and value._version==version for name,value,version in source._fixed),
                    'frozen model preprocessing/projection changed')
    chosen=torch.tensor(indices,dtype=torch.long)
    data=source._data.index_select(0,chosen)
    packet=dict(vectors=source._vectors.index_select(0,chosen),mask=source._mask.index_select(0,chosen))
    logits=model.source_value_logits(model.project(data),source_context=packet)
    shared._require(isinstance(logits,torch.Tensor) and logits.dtype==torch.float32 and logits.device.type=='cpu'
        and tuple(logits.shape)==(6,8,4,32) and shared.core._finite(torch,logits),'finite full32V source logits required')
    selected=logits[:,0,values.SOURCE_FIELDS.index('object')];targets=cache._targets.index_select(0,chosen)
    row_losses=torch.nn.functional.cross_entropy(selected,targets,reduction='none');loss=row_losses.mean()
    shared._require(loss.requires_grad and shared.core._finite(torch,loss),'finite differentiable object CE required')
    observed=selected.detach().tolist();target_ids=targets.tolist()
    receipt=dict(schema=LOSS_SCHEMA,bank_sha256=source._receipt['bank_sha256'],bank_kind=source._receipt['bank_kind'],
        committed_step=committed_step,sampler_seed=source._receipt['seed'],batch_size=6,indices=list(indices),
        row_ids=[source._rows[i][0] for i in indices],source_sha256=[source._rows[i][1] for i in indices],
        strata=[dict(modality=source._rows[i][2],wording_style=source._rows[i][3]) for i in indices],
        object_labels=[cache._objects[i] for i in indices],target_token_ids=target_ids,
        full_vocabulary_logits=observed,per_row_cross_entropy=row_losses.detach().tolist(),mean_cross_entropy=float(loss.detach()),
        correct=sum(max(range(32),key=row.__getitem__)==target for row,target in zip(observed,target_ids)),
        aggregation='mean over six full-vocabulary clause losses',loss_field='object',source_slot=0,full_vocabulary_size=32,
        source_indices_identical_to_modality_control=True,class_balancing_added=False,new_reference_labels_introduced=False,
        source_head_forward_calls=1,recurrent_forward_calls=0,count_forward_calls=0,encoder_forward_calls=0,
        labels_passed_to_model=False,validation_labels_used=False,normalization_fitted=False,model_copied=False,
        bank_rehashed=False,sampler_state_advanced=False,elapsed_seconds=time.monotonic()-started,**FALSE)
    shared._deadline(deadline);return dict(loss=loss,receipt=receipt)
