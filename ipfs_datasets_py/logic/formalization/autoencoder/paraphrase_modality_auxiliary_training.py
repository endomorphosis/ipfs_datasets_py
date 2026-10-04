"""Opt-in full-vocabulary modality CE on authenticated R4 TRAIN clauses.

No decoder rows are replaced, preprocessing fitted, or native encoder invoked.
The bank reuses the complete TRAIN-mixture provenance validator, but never its
selector. This is authored reconstruction evidence, not semantic qualification.
"""
from collections import Counter
from copy import deepcopy
import hashlib
import math
import time

from . import contextual_training_mixture as mixture
from . import clause_source_context as contexts
from . import decoder_distillation_experiment as core
from . import source_value_decoder_experiment as values

SCHEMA = 'training-paraphrase-modality-bank/v1'
CACHE_SCHEMA = 'training-paraphrase-modality-cache/v1'
LOSS_SCHEMA = 'training-paraphrase-modality-loss/v1'
STRATA = tuple((m,t) for m in ('O','P','F') for t in mixture.authored.TEMPLATES)
FALSE = dict(admitted=False,qualified=False,proof_authority=False,lake_executed=False,
    formalized=False,roundtrip_ok=False,checkpoint_promoted=False,selection_performed=False,
    source_semantics_verified=False,historical_linguistic_teacher_modified=False,
    encoder_executed=False,normalization_fitted=False)
digest = core.digest
_require = core._require


def _deadline(deadline):
    _require(type(deadline) in (int,float) and math.isfinite(deadline),'finite paraphrase-modality deadline required')
    if time.monotonic() >= deadline:raise TimeoutError('paraphrase modality auxiliary deadline')


def _sha(text):return hashlib.sha256(text.encode('utf-8')).hexdigest()


def prepare_bank(training_rows, validation_rows, *, training_references, validation_references,
                 source_contexts, codec, validate_rule, source_inventory, deadline):
    """Authenticate all original/evaluation inventories before deriving180 TRAIN clauses."""
    _deadline(deadline)
    _require(type(source_inventory) is dict and source_inventory.get('policy')=='original_only',
        'paraphrase auxiliary requires original-only source inventory policy')
    selected=mixture.prepare(training_rows,validation_rows,training_references=training_references,
        validation_references=validation_references,source_contexts=source_contexts,codec=codec,
        validate_rule=validate_rule,mixture=source_inventory,deadline=deadline)
    receipt=selected.snapshot();effective=selected.effective_contexts
    refs=source_inventory['corpus']['references'];rows=[]
    for ref in refs:
        _deadline(deadline)
        segments=effective[ref['id']]['segments'];rules=ref['target']['rules']
        _require(len(segments)==len(rules)==ref['clause_count'],'complete TRAIN clause/reference alignment required')
        for segment,rule,derivation in zip(segments,rules,ref['derivations']):
            text=segment['source_text'];sha=_sha(text)
            _require(text==mixture.authored.sentence(ref['template'],rule)
                and sha==segment['source_sha256'],'literal TRAIN rendering differs')
            rows.append(dict(id='clause:'+sha,source_text=text,source_sha256=sha,input=deepcopy(segment['vector']),
                input_sha256=segment['embedding_sha256'],target=deepcopy(rule),target_sha256=digest({'rules':[rule]}),
                template=ref['template'],modality=rule['modality'],
                modality_token_id=codec['target_vocabulary'].index('"'+rule['modality']+'"'),
                parent_id=ref['id'],derivation=deepcopy(derivation)))
    rows.sort(key=lambda r:r['id'])
    _require(len(rows)==len({r['id'] for r in rows})==180
        and Counter((r['modality'],r['template']) for r in rows)==Counter({s:30 for s in STRATA}),
        'complete balanced180 TRAIN paraphrase clauses required')
    result=dict(schema=SCHEMA,dimension=source_inventory['source_inputs']['dimension'],rows=rows,
        codec_sha256=digest(codec),source_inventory_sha256=source_inventory['payload_sha256'],
        training_rows_sha256=digest(training_rows),validation_rows_sha256=digest(validation_rows),
        original_training_contexts_sha256=digest(source_contexts['train']),
        source_derivation_receipt=receipt,selected_rows=180,
        strata=[dict(modality=m,template=t,count=30) for m,t in STRATA],
        preprocessing_owner='unchanged original TRAIN cohort',decoder_rows_replaced=False,
        evaluation_labels_used_for_bank=False,file_provenance_verified_by_helper=False,**FALSE)
    result['bank_sha256']=digest(result);_deadline(deadline)
    return result


def estimate_training_work_bytes(bank, *, max_optimizer_steps):
    _require(type(bank) is dict and bank.get('schema')==SCHEMA and bank.get('dimension') in (384,768)
        and bank.get('selected_rows')==180,'bounded native TRAIN paraphrase bank required')
    _require(type(max_optimizer_steps) is int and 1<=max_optimizer_steps<=100000,'bounded step budget required')
    return len(core._raw(bank))*4+180*bank['dimension']*160+(max_optimizer_steps+1)*6*(32*40+4096)+1048576


class TensorCache:
    __slots__=('_model','_data','_vectors','_mask','_targets','_orders','_rows','_fixed','_versions','_receipt','_max_steps')
    def __setattr__(self,name,value):raise AttributeError('prepared paraphrase cache is immutable')
    @property
    def receipt(self):return deepcopy(self._receipt)


def prepare_tensor_cache(torch, model, bank, *, codec, input_transform, seed, deadline, max_optimizer_steps=170):
    started=time.monotonic();_deadline(deadline)
    estimate=estimate_training_work_bytes(bank,max_optimizer_steps=max_optimizer_steps)
    _require(bank.get('bank_sha256')==digest({k:v for k,v in bank.items() if k!='bank_sha256'})
        and bank.get('codec_sha256')==digest(codec),'paraphrase bank digest/codec differs')
    from . import ordered_clause_recurrent_decoder_experiment as owner
    owner.checked_specification(model,codec)
    _require(model.dimension==bank['dimension'] and type(seed) is int and 0<=seed<2**31,'native width and explicit seed required')
    rows=bank['rows'];strata={s:[] for s in STRATA}
    _require(len(rows)==180 and [r['id'] for r in rows]==sorted({r['id'] for r in rows}),'ordered unique TRAIN bank required')
    for i,row in enumerate(rows):
        _deadline(deadline);core._vector(row['input'],model.dimension)
        _require(row['id']=='clause:'+_sha(row['source_text']) and row['source_sha256']==_sha(row['source_text'])
            and row['input_sha256']==digest(row['input']) and row['target_sha256']==digest({'rules':[row['target']]})
            and row['source_text']==mixture.authored.sentence(row['template'],row['target'])
            and row['modality']==row['target']['modality'] and row['modality_token_id']==codec['target_vocabulary'].index('"'+row['modality']+'"'),
            'cached TRAIN clause identity/reference differs')
        strata[row['modality'],row['template']].append(i)
    _require(all(len(v)==30 for v in strata.values()) and len(codec['target_vocabulary'])==32,'six complete30row strata and full32V required')
    sources=[dict(id=r['id'],source_text=r['source_text']) for r in rows]
    contextual=contexts.build_source_contexts(sources,[dict(s,input=r['input']) for s,r in zip(sources,rows)])
    packet=contexts.batch_source_context(torch,sources,contextual,input_transform)
    data=torch.tensor([r['input'] for r in rows],dtype=torch.float32)
    data=(data-torch.tensor(input_transform['mean'],dtype=torch.float32))/input_transform['scale']
    targets=torch.tensor([r['modality_token_id'] for r in rows],dtype=torch.long)
    orders=tuple(tuple(sorted(strata[s],key=lambda i:digest([seed,s,rows[i]['source_sha256'],rows[i]['id']]))) for s in STRATA)
    fixed=[(n,t,t._version) for n,t in model.named_buffers()]
    fixed += [(n,t,t._version) for n,t in model.named_parameters() if not t.requires_grad]
    _require(fixed,'frozen normalization/projection required')
    tensors=(data,packet['vectors'],packet['mask'],targets)
    _require(all(not t.requires_grad for t in tensors),'detached source tensors required')
    receipt=dict(schema=CACHE_SCHEMA,bank_sha256=bank['bank_sha256'],source_inventory_sha256=bank['source_inventory_sha256'],
        dimension=model.dimension,seed=seed,rows=180,strata=deepcopy(bank['strata']),orders=[list(o) for o in orders],
        row_inventory=[{k:r[k] for k in ('id','source_sha256','input_sha256','target_sha256','modality','template','modality_token_id')} for r in rows],
        max_optimizer_steps=max_optimizer_steps,batch_size=6,full_vocabulary_size=32,source_slot=0,
        input_transform_sha256=digest(input_transform),source_contexts_sha256=digest(contextual),
        estimated_training_work_bytes=estimate,cached_tensor_bytes=sum(t.numel()*t.element_size() for t in tensors),
        sampling='independent hash-ordered six-stratum cycles indexed only by committed step',
        recurrent_forward_executed=False,count_forward_executed=False,model_copied=False,
        elapsed_seconds=time.monotonic()-started,**FALSE)
    result=TensorCache()
    for k,v in dict(_model=model,_data=data,_vectors=packet['vectors'],_mask=packet['mask'],_targets=targets,
        _orders=orders,_rows=tuple((r['id'],r['source_sha256'],r['modality'],r['template']) for r in rows),
        _fixed=tuple(fixed),_versions=tuple(t._version for t in tensors),_receipt=receipt,_max_steps=max_optimizer_steps).items():
        object.__setattr__(result,k,v)
    _deadline(deadline);return result


def select_indices(cache, committed_step):
    _require(type(cache) is TensorCache and type(committed_step) is int and 0<=committed_step<cache._max_steps,
        'bounded committed step and prepared paraphrase cache required')
    return tuple(order[committed_step%len(order)] for order in cache._orders)


def _loss(torch, model, cache, indices, *, deadline, requires_grad):
    _deadline(deadline)
    _require(type(requires_grad) is bool and model is cache._model,'explicit gradient mode and matching model required')
    _require(tuple(t._version for t in (cache._data,cache._vectors,cache._mask,cache._targets))==cache._versions,'private cached tensors changed')
    current=dict(model.named_buffers());current.update(dict(model.named_parameters()))
    _require(all(current.get(n) is t and t._version==v for n,t,v in cache._fixed),'frozen preprocessing/projection changed')
    with torch.set_grad_enabled(requires_grad):
        chosen=torch.tensor(indices,dtype=torch.long);data=cache._data.index_select(0,chosen)
        packet=dict(vectors=cache._vectors.index_select(0,chosen),mask=cache._mask.index_select(0,chosen))
        logits=model.source_value_logits(model.project(data),source_context=packet)
        _require(logits.dtype==torch.float32 and logits.device.type=='cpu' and tuple(logits.shape)==(len(indices),8,4,32)
            and core._finite(torch,logits),'finite full32V source logits required')
        selected=logits[:,0,values.SOURCE_FIELDS.index('modality')];targets=cache._targets.index_select(0,chosen)
        losses=torch.nn.functional.cross_entropy(selected,targets,reduction='none');loss=losses.mean()
    _require(core._finite(torch,loss) and loss.requires_grad==requires_grad,'explicit finite auxiliary graph ownership differs')
    _deadline(deadline)
    return loss,selected.detach().tolist(),targets.tolist(),losses.detach().tolist()


def modality_loss(torch, model, cache, *, committed_step, deadline, requires_grad):
    started=time.monotonic();indices=select_indices(cache,committed_step)
    loss,logits,targets,losses=_loss(torch,model,cache,indices,deadline=deadline,requires_grad=requires_grad)
    receipt=dict(schema=LOSS_SCHEMA,bank_sha256=cache._receipt['bank_sha256'],committed_step=committed_step,
        indices=list(indices),row_ids=[cache._rows[i][0] for i in indices],source_sha256=[cache._rows[i][1] for i in indices],
        strata=[dict(modality=cache._rows[i][2],template=cache._rows[i][3]) for i in indices],
        target_token_ids=targets,full_vocabulary_logits=logits,per_row_cross_entropy=losses,
        mean_cross_entropy=float(loss.detach()),correct=sum(max(range(32),key=r.__getitem__)==t for r,t in zip(logits,targets)),
        full_vocabulary_size=32,batch_size=6,loss_field='modality',source_slot=0,gradient_enabled=requires_grad,
        aggregation='mean of six full32V clause modality cross-entropies',source_head_forward_calls=1,
        recurrent_forward_calls=0,count_forward_calls=0,labels_passed_to_model=False,model_copied=False,
        sampler_state_advanced=False,elapsed_seconds=time.monotonic()-started,**FALSE)
    return dict(loss=loss,receipt=receipt)


def evaluate_bank(torch, model, cache, *, deadline):
    """Detached full180 TRAIN diagnostic; never selects or updates a checkpoint."""
    started=time.monotonic();rows=[];groups={}
    for start in range(0,180,6):
        indices=tuple(range(start,start+6));_,logits,targets,losses=_loss(torch,model,cache,indices,deadline=deadline,requires_grad=False)
        for i,vector,target,loss in zip(indices,logits,targets,losses):
            identity,source_sha,m,t=cache._rows[i];correct=max(range(32),key=vector.__getitem__)==target
            rows.append(dict(id=identity,source_sha256=source_sha,modality=m,template=t,target_token_id=target,
                full_vocabulary_logits=vector,cross_entropy=loss,correct=correct))
            for key in ('all','modality:'+m,'template:'+t,'stratum:'+m+':'+t):
                item=groups.setdefault(key,dict(rows=0,correct=0,loss_sum=0.))
                item['rows']+=1;item['correct']+=correct;item['loss_sum']+=loss
    for item in groups.values():item['cross_entropy']=item.pop('loss_sum')/item['rows']
    _deadline(deadline)
    return dict(schema='training-paraphrase-modality-readout/v1',complete=True,bank_sha256=cache._receipt['bank_sha256'],
        model_tensor_sha256=core.tensor_digest(model),rows=rows,groups=groups,full_vocabulary_size=32,
        training_only=True,used_for_selection=False,source_head_forward_calls=30,optimizer_steps=0,
        elapsed_seconds=time.monotonic()-started,**FALSE)
