#!/usr/bin/env python3
"""Frozen, target-free order and count-boundary diagnostics; no training or admission."""
import argparse
from copy import deepcopy
import hashlib
import importlib.util
import importlib.metadata
import json
from pathlib import Path
from types import SimpleNamespace
import time

AUTO='ipfs_datasets_py/logic/formalization/autoencoder/'
PREFIX='ipfs_datasets_py.logic.formalization.autoencoder.'
FALSE=dict(qualified=False,admitted=False,proof_authority=False,source_semantics_verified=False,
    checkpoint_promoted=False,convergence_proven=False,fresh_holdout=False,lake_executed=False,
    formalized=False,roundtrip_ok=False,training_executed=False,weight_selection_performed=False)
ARMS=['independent-1729','shared-1729','independent-2718','shared-2718']
FIXED=dict(schema='decoder-order-boundary-plan/v1',state_order=ARMS,
    representation_dimension=384,epochs_per_source_stage=20,
    source_split_for_permutations='train',original_rows=48,requested_order_rows=120,
    unique_order_rows=108,permutation_pairs=60,duplicate_variant_aliases=12,
    orders=['original','reverse','rotate_left_one'],embedding_batch_size=8,
    repeat_batch_sizes=[8,4],repeat_rows_per_batch_size=48,total_encoder_row_observations=204,
    boundary_splits=['train','validation'],boundary_rows_per_model=96,
    fixed_encoder_context_tokens=512,fixed_decoder_output_limit=512,temperature=0,
    decoder_batch_size=8,max_seconds_per_generation=120,max_seconds_per_boundary_panel=120,
    max_seconds_embedding_phase=120,max_seconds_entire_run=600,
    max_memory_bytes=536870912,no_downloads=True,selection_unchanged=True,
    generation_reference_count_access=False,generation_reference_prefix_access=False,
    old_prediction_replay_required=True,trained_weights_unchanged=True,
    native_qualification=False,production_promotion_allowed=False,
    observation_thresholds_confer_success=False)


def require(condition,message):
    if not condition:raise ValueError(message)


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def validate_plan(plan):
    require(type(plan) is dict and all(json.dumps(plan.get(k),sort_keys=True,allow_nan=False)==
        json.dumps(v,sort_keys=True,allow_nan=False) for k,v in FIXED.items()),'fixed diagnostic recipe differs')


def load_helper(root,pins,relative,name):
    path=root/relative;require(sha(path)==pins.get(relative),'frozen helper differs: '+relative)
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


def read_published(path,manifest,published):
    """Authenticate physical or explicitly referenced predecessor members."""
    path=Path(path);content=path.read_bytes();digest=hashlib.sha256(content).hexdigest()
    require(manifest['inputs'].get(str(path))==digest,'unbound predecessor artifact')
    expected=dict(sha256=digest,bytes=len(content))
    member=published['original_artifact_archive_paths'].get(str(path))
    if member is not None:
        require(published['members'].get(member)==expected,'published physical member differs')
    else:
        ref=published.get('referenced_artifacts',{}).get(str(path))
        require(type(ref) is dict and all(ref.get(k)==v for k,v in expected.items())
            and ref.get('kind')=='archive_member','published referenced member differs')
    return json.loads(content)


def expected_catalog(summary_path):
    root=Path(summary_path).parent
    return [dict(arm=arm,state_path=str(root/arm/'last-attempt-state.json'),
        panels={split:str(root/arm/'last-attempt'/('evaluation-'+label+'.json'))
            for split,label in [('train','training'),('validation','validation')]}) for arm in ARMS]


def load_context(args):
    manifest=json.loads(args.manifest.read_bytes());pins=manifest['extensions']
    plan=json.loads(args.plan.read_bytes());validate_plan(plan)
    require(plan.get('input_sha256')==manifest['inputs'],'predeclared input inventory differs')
    replay=load_helper(args.extension_root,pins,'scripts/ops/autoencoder/decoder_fidelity_replay.py','_order_replay')
    ctx=replay.load_context(args,validate_plan=validate_plan);h=ctx['helpers']
    shared=load_helper(args.extension_root,pins,'scripts/ops/autoencoder/benchmark_shared_slot_source_reconstruction.py','_order_shared')
    prior=load_helper(args.extension_root,pins,'scripts/ops/autoencoder/benchmark_mean_centered_source_reconstruction.py','_order_prior')
    names=['decoder_cardinality_experiment','long_span_cardinality_training','long_span_count_exposure_training',
        'source_value_decoder_experiment','projected_source_decoder_experiment','mean_centered_source_decoder_experiment',
        'shared_slot_source_decoder_experiment','long_span_source_value_training',
        'order_source_diagnostic','boundary_source_diagnostic']
    owners={name:h.extension(args.extension_root,AUTO+name+'.py',PREFIX+name,pins) for name in names}
    public=json.loads(Path(manifest['shared_public_manifest']).read_bytes())
    results=json.loads(Path(manifest['shared_public_results']).read_bytes())
    require(public.get('schema')=='decoder-shared-slot-source-archive/v1'
        and results.get('schema')=='decoder-shared-slot-source-results/v1'
        and public['archive']==results['archive'],'shared predecessor publication differs')
    summary=read_published(manifest['shared_summary'],manifest,public)
    require(summary.get('complete') is True and summary.get('raw_training_replay_parity') is True
        and [r['arm'] for r in summary['runs']]==ARMS,'complete four-state predecessor required')
    for key in ('donor','paragraphs','embeddings','curriculum','curriculum_inputs'):
        read_published(manifest[key],manifest,public)
    preprocessing=read_published(manifest['parent_preprocessing'],manifest,public)
    require(manifest['state_catalog']==expected_catalog(manifest['shared_summary']),'state catalog differs')
    ctx.update(manifest=manifest,owners=owners,shared=shared,prior=prior,public=public,
        preprocessing=preprocessing,prior_runs={r['arm']:r for r in summary['runs']})
    return ctx


def restore_candidate(ctx,catalog):
    core=ctx['core'];run=ctx['prior_runs'][catalog['arm']]
    state=read_published(catalog['state_path'],ctx['manifest'],ctx['public'])
    require(state.get('schema')=='private-shared-slot-source-state/v1' and state.get('role')=='last-attempt'
        and state.get('selected') is False and state.get('optimizer_resumable') is False
        and state.get('checkpoint_promoted') is False and state.get('admitted') is False
        and state['codec']==ctx['donor']['codec'] and state['recipe']==run['recipe']
        and core.digest(state['model_state'])==state['weights_sha256']
        and state['tensor_sha256']==run['training']['last_complete_attempt_weights_sha256'],
        'authenticated unselected final state required')
    model=ctx['shared'].bind_candidate(ctx,run['recipe'],run['seed'])
    require(model.describe()==state['architecture'],'restored architecture differs')
    model.load_state_dict(ctx['shared'].restored_tensors(ctx,state['model_state'],model.state_dict()),strict=True)
    require(core.tensor_digest(model)==state['tensor_sha256'],'restored trained tensor digest differs')
    return model,state['tensor_sha256']


def encode_order_panel(ctx,preparation):
    """One local encoder instance, main rows and two explicitly separate repeats."""
    import torch
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_embedding_runtime as producer
    start=time.monotonic();core=ctx['core'];rows=preparation['rows'];originals=rows[:48]
    require(len(rows)==108 and [r['id'] for r in originals]==[r['id'] for r in ctx['rows']['train']],
        'original-first training order differs')
    packages={name:importlib.metadata.version(name) for name in ('torch','sentence-transformers','transformers','tokenizers','safetensors')}
    rng=torch.random.get_rng_state().clone();outputs={};times={}
    with producer._offline_guard(),torch.random.fork_rng(devices=[]):
        torch.manual_seed(0)
        from sentence_transformers import SentenceTransformer
        snapshot,assets=producer._snapshot_assets(producer.DEFAULT_SNAPSHOT_PATH)
        require(assets==ctx['embeddings']['producer']['asset_manifest'],'prior encoder assets differ')
        encoder=SentenceTransformer(str(snapshot),local_files_only=True,trust_remote_code=False,device='cpu')
        encoder.eval();producer._validate_model(encoder,torch)
        for name,part,batch in [('main',rows,8),('repeat_batch8',originals,8),('repeat_batch4',originals,4)]:
            require(time.monotonic()-start<120,'encoder diagnostic deadline exceeded')
            before=time.monotonic()
            result=producer._produce_results([SimpleNamespace(input_id=r['id'],text=r['source_text']) for r in part],
                encoder,torch,batch_size=batch,token_input_digest=lambda value:value)
            require(len(result)==len(part) and all(r['status']=='embedded' for r in result),'complete untruncated local embeddings required')
            outputs[name]=result;times[name]=time.monotonic()-before
        require(producer._snapshot_assets(snapshot)[1]==assets,'encoder assets changed')
    require(torch.equal(torch.random.get_rng_state(),rng),'embedding diagnostics changed ambient RNG')
    require(time.monotonic()-start<120,'encoder diagnostic deadline exceeded')
    return dict(schema='order-source-embedding-observations/v1',observations=outputs,
        producer=dict(model_id='thenlper/gte-small',revision=producer.PINNED_REVISION,asset_manifest=assets,
            producer_sha256=sha(producer.__file__),packages=packages,snapshot_path=str(snapshot),
            dimension=384,encoder_context_tokens=512,normalized=True,dtype='float32',device='cpu',cpu_threads=1,
            downloads_performed=False,actual_forward_tokens_checked=True,encoder_context_changed=False),
        observations_count=sum(map(len,outputs.values())),timing=times,elapsed_seconds=time.monotonic()-start,
        vectors_sha256={k:core.digest(v) for k,v in outputs.items()},**FALSE)


def greedy_source_panel(ctx,model,source_rows):
    """Accept only numerical inputs; labels are scored after this function returns."""
    import torch
    core=ctx['core'];start=time.monotonic();deadline=start+120
    require(type(source_rows) is list and 1<=len(source_rows)<=108 and all(type(r) is dict and set(r)=={'id','input'}
        and type(r['id']) is str and r['id'] for r in source_rows),'closed bounded source-only rows required')
    require(len({r['id'] for r in source_rows})==len(source_rows),'unique source IDs required')
    for row in source_rows:core._vector(row['input'],384)
    before=core.tensor_digest(model);rng=torch.random.get_rng_state().clone()
    working=deepcopy(model);working.eval();predictions=[];projected_rows={};logits_rows={};counts={}
    transform=ctx['donor']['input_transform'];size=len(ctx['donor']['codec']['target_vocabulary'])
    with torch.inference_mode():
        for offset in range(0,len(source_rows),8):
            part=source_rows[offset:offset+8]
            data=ctx['owners']['long_span_count_exposure_training']._source_batch(torch,part,transform)
            result=core._greedy(torch,working,data,512,size,deadline)
            require(result is not None,'order generation deadline exceeded')
            projected,generated,statuses=result
            head=working.source_value_logits(projected).tolist();count=working.count_logits(projected).tolist()
            for row,vector,values,count_values,tokens,status in zip(part,projected.tolist(),head,count,generated,statuses):
                predictions.append(dict(id=row['id'],token_ids=tokens,eos_reached=status=='eos',generation_status=status))
                projected_rows[row['id']]=vector;logits_rows[row['id']]=values;counts[row['id']]=count_values
    require(core.tensor_digest(model)==before and core.tensor_digest(working)==before,'order generation mutated weights')
    require(torch.equal(torch.random.get_rng_state(),rng),'order generation mutated RNG')
    require(time.monotonic()<deadline,'order generation deadline exceeded')
    elapsed=time.monotonic()-start
    return dict(schema='order-source-model-observations/v1',predictions=predictions,projected_vectors=projected_rows,
        scalar_logits=logits_rows,count_logits=counts,model_tensor_sha256=before,rows=len(source_rows),
        elapsed_seconds=elapsed,wall_seconds_per_span=elapsed/len(source_rows),
        timing_scope='copy, source-only generation, source heads and identity checks; no encoder, CE or reference scoring',**FALSE)


def validate_prediction_replay(observed,archived,expected_ids):
    keys=('id','token_ids','eos_reached','generation_status')
    require([r['id'] for r in observed]==expected_ids,'replay source row order differs')
    expected=[{k:r[k] for k in keys} for r in archived['predictions']]
    require(observed==expected,'boundary instrumentation changed prior greedy generation')
    return dict(complete=True,rows=len(expected),all_four_prediction_fields_equal=True,
        scope='cached source vectors, original batching, authenticated final state; no numerical CE replay')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('dependency-root','extension-root','manifest','plan','output'):
        parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--phase',choices=['diagnostic'],required=True)
    args=parser.parse_args();start=time.monotonic();ctx=load_context(args);h=ctx['helpers'];save=h.save
    before=h.inventory(args.dependency_root,args.extension_root,ctx['pins'])
    args.output.mkdir(parents=True)
    save(args.output/'sealed-recipe.json',dict(plan=ctx['plan'],manifest=ctx['manifest'],tree_pin=ctx['tree'],**FALSE))
    save(args.output/'preprocessing-replay.json',ctx['prior'].validate_preprocessing(ctx))
    order=ctx['owners']['order_source_diagnostic']
    preparation=order.build_order_variants(ctx['corpus'],json.loads(Path(ctx['manifest']['curriculum_inputs']).read_bytes()),codec=ctx['donor']['codec'])
    save(args.output/'order-preparation.json',preparation)
    encoded=encode_order_panel(ctx,preparation);save(args.output/'embedding-observations.json',encoded)
    vectors={r['input_id']:r['vector'] for r in encoded['observations']['main']}
    source_metrics={}
    for label in ('repeat_batch8','repeat_batch4'):
        repeats={r['input_id']:r['vector'] for r in encoded['observations'][label]}
        source_metrics[label]=order.paired_vector_metrics(preparation,vectors,space='native_embedding',repeat_vectors_by_id=repeats)
    cached={r['input_id']:r['vector'] for r in ctx['embeddings']['rows'] if r['input_id'] in preparation['original_ids']}
    source_metrics['cached_originals']=order.paired_vector_metrics(preparation,vectors,space='native_embedding',repeat_vectors_by_id=cached)
    save(args.output/'embedding-pairs.json',source_metrics)
    source_rows=[dict(id=r['id'],input=vectors[r['id']]) for r in preparation['rows']]
    runs=[]
    for catalog in ctx['manifest']['state_catalog']:
        require(time.monotonic()-start<600,'diagnostic run deadline exceeded')
        model,digest=restore_candidate(ctx,catalog);folder=args.output/catalog['arm'];traces={}
        for split in ('train','validation'):
            archived=read_published(catalog['panels'][split],ctx['manifest'],ctx['public'])
            value=ctx['owners']['boundary_source_diagnostic'].trace_boundary_generation(model,
                [dict(id=r['id'],input=r['input']) for r in ctx['rows'][split]],codec=ctx['donor']['codec'],
                input_transform=ctx['donor']['input_transform'],max_target_tokens=512,batch_size=8,max_seconds=120)
            replay=validate_prediction_replay(value['predictions'],archived,[r['id'] for r in ctx['rows'][split]])
            save(folder/('boundary-'+split+'.json'),dict(value,archived_prediction_replay=replay))
            traces[split]=replay
        value=greedy_source_panel(ctx,model,source_rows);save(folder/'order-observations.json',value)
        paired=dict(projection=order.paired_vector_metrics(preparation,value['projected_vectors'],space='decoder_projection'),
            scalars=order.paired_scalar_metrics(preparation,value['scalar_logits'],codec=ctx['donor']['codec']),
            generated=order.paired_prediction_metrics(preparation,{r['id']:r for r in value['predictions']},codec=ctx['donor']['codec']))
        save(folder/'order-pairs.json',paired)
        require(ctx['core'].tensor_digest(model)==digest,'diagnostics changed restored model')
        record=dict(arm=catalog['arm'],model_tensor_sha256=digest,boundary_replay=traces,
            order_observation_rows=value['rows'],order_elapsed_seconds=value['elapsed_seconds'],**FALSE)
        save(folder/'summary.json',record);runs.append(record)
        print(json.dumps(dict(arm=catalog['arm'],complete=True,order_rows=value['rows'])),flush=True)
    after=h.inventory(args.dependency_root,args.extension_root,ctx['pins'])
    require(all(after.get(k)==v for k,v in before.items()),'loaded producer changed')
    h.validate_manifest_inputs(ctx['manifest'])
    for rel,digest in ctx['pins'].items():require(sha(args.extension_root/rel)==digest,'frozen extension changed')
    require(sha(args.plan)==ctx['manifest']['plan_sha256'],'predeclared plan changed')
    require(time.monotonic()-start<600,'diagnostic run deadline exceeded')
    save(args.output/'summary.json',dict(schema='decoder-order-boundary-observations/v1',complete=len(runs)==4,
        runs=runs,source_dependencies=after,elapsed_seconds=time.monotonic()-start,encoder_executed=True,
        unique_order_sources=108,encoder_row_observations=204,boundary_model_rows=384,
        workers=1,bridge_names=[],legal_ir_evaluate_provers=False,metric_disk_cache_used=False,
        original_boundary_vectors_cached=True,permutation_vectors_freshly_encoded=True,
        downloads_performed=False,encoder_context_changed=False,output_limit_changed=False,**FALSE))


if __name__=='__main__':main()
