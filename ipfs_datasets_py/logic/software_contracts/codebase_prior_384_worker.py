"""Isolated parent-centered head refit; no optimizer state or target-at-inference."""
from __future__ import annotations
from contextlib import redirect_stdout
from copy import deepcopy
import json
from pathlib import Path
import sys


def execute(request):
    from ipfs_datasets_py.logic.software_contracts import codebase_prior_384 as owner
    from ipfs_datasets_py.logic.formalization.autoencoder import structured_source_384 as decoder
    from ipfs_datasets_py.logic.formalization.autoencoder.source_embeddings_384 import embed_texts
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_embedding_runtime as embedding
    import numpy as np
    owner.require(set(request)=={'producer','parent','corpus','embedding_snapshot','previous_features','action'},'closed prior worker request')
    owner.require(request['action']=='train' and request['producer']==owner.pins(),'exact prior training producer required')
    parent=request['parent'];decoder.Runtime(parent)
    _,assets=embedding._snapshot_assets(request['embedding_snapshot'])
    cached={r['source_sha256']:r for r in request['previous_features']}
    owner.require(len(cached)==len(request['previous_features']),'unique prior embedding microbatches required')
    rows=request['corpus']['fit_source_corpus']['rows']
    pending=[r for r in rows if r['source_sha256'] not in cached]
    vectors=embed_texts([r['source_text'] for r in pending],snapshot_path=request['embedding_snapshot']) if pending else []
    additions={r['source_sha256']:dict(source_sha256=r['source_sha256'],embedding=v,
        embedding_sha256=owner.sha(owner.raw(v)),assets_sha256=owner.sha(owner.raw(assets))) for r,v in zip(pending,vectors)}
    grouped={r:[] for r in ('train','validation','holdout')};features=[]
    for row in rows:
        feature=deepcopy(cached.get(row['source_sha256'],additions.get(row['source_sha256'])))
        owner.require(set(feature)=={'source_sha256','embedding','embedding_sha256','assets_sha256'}
            and feature['assets_sha256']==owner.sha(owner.raw(assets))
            and feature['embedding_sha256']==owner.sha(owner.raw(feature['embedding']))
            and len(feature['embedding'])==384,'exact immutable embedding microbatch required')
        features.append(feature)
        grouped[row['role']].append(dict(id=row['id'],source_text=row['source_text'],embedding=feature['embedding'],target=row['target']))
    with decoder._numeric() as np:
        train,valid=grouped['train'],grouped['validation']
        x,_=decoder._normalize(np,decoder._project(np,train,parent['projection_state']),parent['input_transform'])
        vx,_=decoder._normalize(np,decoder._project(np,valid,parent['projection_state']),parent['input_transform'])
        y,_=decoder._targets(np,train,parent['target_schema'])
        _,validation_ids=decoder._targets(np,valid,parent['target_schema'])
        w=np.asarray(parent['head_state']['weights'],dtype=np.float64)
        bias=np.asarray(parent['head_state']['bias'],dtype=np.float64)
        residual=y-(x@w+bias)
        gram=x.T@x;cross=x.T@residual
        eigen,vectors=np.linalg.eigh((gram+gram.T)/2)
        owner.require(np.isfinite(eigen).all() and float(eigen.min())>=-1e-7,'finite positive training Gram required')
        eigen=np.maximum(eigen,0.)
        best_rank=None;selected=None;history=[]
        for ridge in owner.RIDGES:
            delta=vectors@((vectors.T@cross)/(eigen[:,None]+ridge))
            candidate=w+delta
            observed=decoder._score('security_ir',vx@candidate+bias,valid,validation_ids,parent['target_schema'])
            rank=(observed['exact_targets'],observed['semantic_leaf_correct'])
            chosen=best_rank is None or rank>best_rank
            history.append(dict(ridge=ridge,selected_at_step=chosen,**observed))
            if chosen: best_rank,selected,weights=rank,ridge,candidate.copy()
        result=deepcopy(parent)
        result['head_state']=dict(weights=weights.tolist(),bias=bias.tolist())
        result['head_sha256']=decoder.digest(result['head_state'])
        result['training_manifest']=decoder._manifest(train)
        result['validation_manifest']=decoder._manifest(valid)
        result['config']['ridges']=list(owner.RIDGES)
        result['training']=dict(trainer_id=owner.ALGORITHM,selected_ridge=selected,history=history,
            test_used_for_selection=False,gradient_training_used=False,optimizer_steps=0,
            base_checkpoint_sha256=owner.sha(owner.raw(parent)),parent_head_initialized=True,
            exact_optimizer_resume=False,full_selected_training_head_refit=True,bias_inherited=True,
            input_transform_inherited=True,prior_training_statistics_recovered_from_weights=False)
        delta_norm=float(np.linalg.norm(weights-w))
        owner.require(np.isfinite(weights).all() and delta_norm>1e-12,'actual nonzero finite weight update required')
    decoder.Runtime(result)
    def evaluate(model,selected_rows):
        value=decoder.evaluate(model,selected_rows)
        return {k:value[k] for k in ('count','exact_targets','semantic_leaf_correct','semantic_leaf_count','valid_candidates')}
    evaluation=dict(parent_holdout=evaluate(parent,grouped['holdout']),child_holdout=evaluate(result,grouped['holdout']),
        parent_validation=evaluate(parent,valid),child_validation=evaluate(result,valid),holdout_used_for_selection=False,
        byte_identical_parent_control=evaluate(parent,grouped['holdout']),
        holdout_role='fixed_deployment_canary_not_final_unseen_test',
        hyperparameter_selection_uses_holdout=False,deployment_retention_gate_uses_holdout=True)
    _,final=embedding._snapshot_assets(request['embedding_snapshot'])
    owner.require(assets==final and request['producer']==owner.pins(),'prior worker assets/producer changed')
    return dict(producer=owner.pins(),checkpoint=result,features=features,embedding_assets=assets,
        evaluation=evaluation,fit=dict(algorithm=owner.ALGORITHM,ridges=list(owner.RIDGES),selected_ridge=selected,
            weight_delta_l2=delta_norm,nonzero_weight_update=True,head_bytes_changed=result['head_sha256']!=parent['head_sha256'],
            embedded_rows=len(pending),reused_embedding_microbatches=len(rows)-len(pending),
            training_rows=len(train),validation_rows=len(valid),holdout_rows=len(grouped['holdout']),
            optimizer_steps=0,full_selected_training_head_refit=True,exact_optimizer_resume=False,
            holdout_used_for_selection=False,history=history))


def main():
    sys.path[:0]=json.loads(sys.argv[1])
    with redirect_stdout(sys.stderr):
        from ipfs_datasets_py.logic.software_contracts import codebase_prior_384 as owner
        data=sys.stdin.buffer.read(owner.MAX_BYTES+1)
        owner.require(len(data)<=owner.MAX_BYTES,'prior worker input too large')
        output=owner.raw(execute(json.loads(data)))
        owner.require(len(output)<=owner.MAX_BYTES,'prior worker output too large')
    sys.stdout.buffer.write(output)


if __name__=='__main__':main()
