#!/usr/bin/env python3
"""Replay authenticated greedy errors and separate inherited/source logits."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import time

AUTO = 'ipfs_datasets_py/logic/formalization/autoencoder/'
PREFIX = 'ipfs_datasets_py.logic.formalization.autoencoder.'
FALSE = dict(qualified=False, admitted=False, proof_authority=False,
    source_semantics_verified=False, checkpoint_promoted=False,
    convergence_proven=False, fresh_holdout=False, lake_executed=False,
    formalized=False, roundtrip_ok=False)
ARMS = [name+'-'+str(seed) for seed in (1729,2718)
    for name in ('conditioning48','projected384')]
STATES = ['projected384-1729-selected']+[name+'-last-attempt' for name in ARMS]
FIXED = dict(schema='decoder-source-value-margins-plan/v1',
    representation_dimension=384, state_order=STATES, split_order=['train','validation'],
    final_controls=['conditioned','source_shuffle'], selected_controls=['conditioned'],
    expected_panels=18, expected_rows_per_panel=48, epochs_per_source_stage=20,
    fixed_encoder_context_tokens=512, fixed_decoder_output_limit=512, batch_size=8,
    max_seconds_per_panel=30, max_memory_bytes_per_panel=536870912,
    temperature=0, training_executed=False, optimizer_steps=0, no_downloads=True,
    strict_gates_changed=False, reference_tokens_passed_to_generation=False,
    capture_types=['first_divergence','first_scalar_site','first_rule_boundary'],
    archived_greedy_predictions_must_match=True)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def validate_plan(plan):
    require(type(plan) is dict and all(json.dumps(plan.get(k),sort_keys=True,allow_nan=False)==
        json.dumps(v,sort_keys=True,allow_nan=False) for k,v in FIXED.items()),
        'fixed greedy margin recipe differs')


def load_helper(root, pins, relative, name):
    path=root/relative
    require(hashlib.sha256(path.read_bytes()).hexdigest()==pins.get(relative),
        'frozen helper changed: '+relative)
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def expected_catalog(root):
    labels={'train/conditioned':'training','validation/conditioned':'validation',
        'train/source_shuffle':'training-source-shuffle','validation/source_shuffle':'source-shuffle'}
    result=[]
    for arm,role in [('projected384-1729','selected')]+[(a,'last-attempt') for a in ARMS]:
        controls=['conditioned'] if role=='selected' else ['conditioned','source_shuffle']
        result.append(dict(name=arm+'-'+role,prior_arm=arm,role=role,
            state_path=str(root/arm/(role+'-state.json')),
            archived_evaluations={key:str(root/arm/role/('evaluation-'+label+'.json'))
                for key,label in labels.items() if key.split('/')[1] in controls}))
    return result


def authenticate(manifest, archive_helper):
    bound=archive_helper.read_bound
    public=bound(manifest['parent_public_manifest'],manifest)
    results=bound(manifest['parent_public_results'],manifest)
    require(results['complete'] is True and public['archive']==results['archive'],
        'complete published predecessor required')
    summary=bound(manifest['parent_summary'],manifest,public)
    require(summary['schema']=='decoder-source-value-training-comparison/v1'
        and summary['complete'] is True and all(summary[k] is False for k in FALSE),
        'nonqualifying source-value comparison required')
    runs={run['arm']:run for run in summary['runs']}
    require(len(summary['runs'])==len(runs)==6 and set(runs)==set(ARMS+['unchanged-1729','unchanged-2718']),
        'exact predecessor arm inventory required')
    require(manifest['state_catalog']==expected_catalog(Path(manifest['parent_summary']).parent),
        'exact role and control catalog required')
    require(all(runs[a]['training']['selected_epoch']==0 for a in runs),
        'predecessor selected states changed')
    return public,runs


def validate_export(state, catalog, run, core, codec):
    require(state['schema']=='private-source-value-state/v1'
        and state['role']==catalog['role'] and state['selected'] is (catalog['role']=='selected')
        and state['optimizer_resumable'] is False and all(state[k] is False for k in FALSE),
        'private role or authority mismatch')
    key='selected_weights_sha256' if catalog['role']=='selected' else 'last_complete_attempt_weights_sha256'
    require(state['recipe']==run['recipe'] and state['codec']==codec
        and core.digest(state['model_state'])==state['weights_sha256']
        and state['tensor_sha256']==run['training'][key], 'private state authentication differs')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for key in ('dependency-root','extension-root','manifest','plan','output'):
        parser.add_argument('--'+key,type=Path,required=True)
    args=parser.parse_args()
    manifest=json.loads(args.manifest.read_bytes())
    replay=load_helper(args.extension_root,manifest['extensions'],
        'scripts/ops/autoencoder/decoder_fidelity_replay.py','_source_margin_replay')
    ctx=replay.load_context(args,validate_plan=validate_plan)
    helpers,core,plan=ctx['helpers'],ctx['core'],ctx['plan'];save=helpers.save
    archives=load_helper(args.extension_root,ctx['pins'],
        'scripts/ops/autoencoder/benchmark_decoder_prefix_diagnostics.py','_source_margin_archives')
    public,runs=authenticate(manifest,archives)
    count=helpers.extension(args.extension_root,AUTO+'decoder_cardinality_experiment.py',PREFIX+'decoder_cardinality_experiment',ctx['pins'])
    helpers.extension(args.extension_root,AUTO+'decoder_gradient_replay.py',PREFIX+'decoder_gradient_replay',ctx['pins'])
    helpers.extension(args.extension_root,AUTO+'decoder_prefix_diagnostics.py',PREFIX+'decoder_prefix_diagnostics',ctx['pins'])
    value_model=helpers.extension(args.extension_root,AUTO+'source_value_decoder_experiment.py',PREFIX+'source_value_decoder_experiment',ctx['pins'])
    owner=helpers.extension(args.extension_root,AUTO+'decoder_source_value_margins.py',PREFIX+'decoder_source_value_margins',ctx['pins'])
    before=helpers.inventory(args.dependency_root,args.extension_root,ctx['pins'])
    args.output.mkdir(parents=True)
    save(args.output/'sealed-recipe.json',dict(plan=plan,manifest=manifest,tree_pin=ctx['tree'],**FALSE))
    started=time.monotonic();panels=[]
    for catalog in manifest['state_catalog']:
        state=archives.read_bound(catalog['state_path'],manifest,public)
        run=runs[catalog['prior_arm']]
        validate_export(state,catalog,run,core,ctx['donor']['codec'])
        persistent=ctx['adapter'].bind_persistent_model(ctx['base_model'].body,dimension=384,conditioning='every_step')
        for name,p in persistent.named_parameters():
            if name.startswith(('body.projection_down.','body.projection_up.')):p.requires_grad_(False)
        inherited=count.bind_cardinality_model(persistent,codec=ctx['donor']['codec'],guide_boundary=False)
        model=value_model.bind_source_value_model(inherited,codec=ctx['donor']['codec'],
            feature_kind=state['recipe']['feature_kind'],max_rules=8,guidance=True)
        require(model.describe()==state['architecture'],'private architecture differs')
        require(set(model.state_dict())==set(state['model_state']),'private tensor inventory differs')
        model.load_state_dict({k:ctx['numerical']._tensor(state['model_state'][k],v,k)
            for k,v in model.state_dict().items()},strict=True)
        require(core.tensor_digest(model)==state['tensor_sha256'],'reloaded tensor digest differs')
        for split in plan['split_order']:
            for kind in (plan['selected_controls'] if catalog['role']=='selected' else plan['final_controls']):
                panel_started=time.monotonic();rows=ctx['rows'][split]
                control=dict(kind=kind,source_assignment={r['id']:r['id'] for r in rows})
                if kind=='source_shuffle':
                    rows,execution=helpers.shuffle_inputs(rows,ctx['references'][split])
                    control={k:execution[k] for k in ('kind','source_assignment')}
                path=catalog['archived_evaluations'][split+'/'+kind]
                archived=archives.read_bound(path,manifest,public);old=archived['report']
                required=dict(complete=True,input_dimension=384,max_target_tokens=512,batch_size=8,
                    generation_temperature=0,generation_target_access=False,optimizer_steps=0,
                    weight_selection_performed=False,validation_rows_sha256=core.digest(rows),
                    model_weights_sha256=state['tensor_sha256'],codec_sha256=core.digest(ctx['donor']['codec']),
                    input_transform_sha256=core.digest(ctx['donor']['input_transform']))
                require(all(type(old.get(k)) is type(v) and old[k]==v for k,v in required.items()),
                    'archived panel identity differs')
                require({k:archived['execution'][k] for k in ('kind','source_assignment')}==control,
                    'archived control differs')
                value=owner.trace_predictions(model,rows,ctx['references'][split],codec=ctx['donor']['codec'],
                    input_transform=ctx['donor']['input_transform'],lineage=state['lineage'],
                    expected_predictions=archived['predictions'],validate_rule=ctx['validate_rule'],
                    validator_id=ctx['validator_id'],source_rows=ctx['rows'][split],control=control,
                    max_target_tokens=512,max_seconds=plan['max_seconds_per_panel'],batch_size=8,
                    max_memory_bytes=plan['max_memory_bytes_per_panel'])
                require(value['report']['complete'] and len(value['rows'])==48,'incomplete margin replay')
                receipt=save(args.output/catalog['name']/(split+'-'+kind+'.json'),value)
                panels.append(dict(state=catalog['name'],split=split,control=kind,report=value['report'],
                    artifact=receipt,prior_predictions_path=path,prior_predictions_sha256=manifest['inputs'][path],
                    elapsed_including_serialization_seconds=time.monotonic()-panel_started))
                print(json.dumps(dict(state=catalog['name'],split=split,control=kind,
                    rows=len(value['rows']),elapsed=panels[-1]['elapsed_including_serialization_seconds'])),flush=True)
    require(len(panels)==18,'complete eighteen-panel replay required')
    after=helpers.inventory(args.dependency_root,args.extension_root,ctx['pins'])
    require(before==after,'executed source changed')
    helpers.validate_manifest_inputs(manifest)
    require(helpers.sha(args.plan)==manifest['plan_sha256'],'plan changed')
    save(args.output/'summary.json',dict(schema='decoder-source-value-margins-comparison/v1',complete=True,
        panels=panels,elapsed_seconds=time.monotonic()-started,source_dependencies=after,
        training_executed=False,optimizer_steps=0,actual_greedy_replayed=True,archived_predictions_matched=True,
        encoder_executed=False,downloads_performed=False,encoder_context_changed=False,output_limit_changed=False,
        workers=1,bridge_names=[],legal_ir_evaluate_provers=False,metric_disk_cache_used=False,
        paragraph_embedding_cache_used=True,**FALSE))


if __name__=='__main__':
    main()
