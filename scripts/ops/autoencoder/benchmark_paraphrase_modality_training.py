#!/usr/bin/env python3
"""Matched TRAIN paraphrase modality CE, with a zero-weight forward control.

The original decoder/count/preprocessing owners and R13 parents are unchanged.
This diagnostic uses cached R4 TRAIN sources, never an encoder or a proof gate.
"""
import argparse
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import struct
import time
from types import SimpleNamespace

AUTO = 'ipfs_datasets_py/logic/formalization/autoencoder/'
PREFIX = 'ipfs_datasets_py.logic.formalization.autoencoder.'
RUNNER = 'scripts/ops/autoencoder/benchmark_paraphrase_modality_training.py'
PARENT_RUNNER = 'scripts/ops/autoencoder/benchmark_training_paraphrase_mixture.py'
ARMS = [dict(name='paraphrase-modality-zero',weight=0.),dict(name='paraphrase-modality-ce',weight=.05)]
FALSE = dict(qualified=False,admitted=False,proof_authority=False,formalized=False,roundtrip_ok=False,
    source_semantics_verified=False,checkpoint_promoted=False,convergence_proven=False,lake_executed=False,
    native_validation_executed=False,fresh_holdout=False,historical_linguistic_teacher_modified=False)
FIXED = dict(schema='paraphrase-modality-training-plan/v1',dimensions=[384,768],seed=1729,
    arms=ARMS,fit_count=4,fits_per_dimension=2,parent='R13/selected-followup-lr0001-1729/selected',
    epochs_per_stage=10,optimizer_steps_per_fit=170,row_presentations=1220,count_presentations=1220,
    valid_target_token_presentations=112920,source_value_presentations=12800,
    balanced_counts={'1':305,'2':305,'4':305,'8':305},learning_rate=.0001,non_action_learning_rate_multiplier=10.,
    cardinality_weight=.25,source_value_weight=.25,action_contrastive_weight=.05,generated_boundary_weight=.05,
    generated_boundary_site_policy='first_last',strict_boundary_retry=True,boundary_atol=2e-5,boundary_rtol=2e-5,
    auxiliary384='original_used113_modality.05',auxiliary768=None,original_auxiliary_presentations384=1020,
    paraphrase_auxiliary_rows=180,paraphrase_auxiliary_batch_size=6,
    paraphrase_auxiliary_strata=['O:rule_gerund_by_actor','O:topicalized_actor_norm',
        'P:rule_gerund_by_actor','P:topicalized_actor_norm','F:rule_gerund_by_actor','F:topicalized_actor_norm'],
    paraphrase_diagnostic_presentations_per_fit=1020,paraphrase_supervised_presentations_by_arm=[0,1020],
    auxiliary_sampling='independent_hash_ordered_modality_template_strata',
    zero_weight_control='identical_auxiliary_forward;no_zero_graph_attached',
    positive_objective='base_objective+0.05*mean_six_full32V_modality_CEs',
    grouping_or_contrastive_loss_added=False,reference_class_reweighting=False,
    original_decoder_rows_unchanged=True,source_training_mixture_enabled=False,
    fresh_optimizer=True,fresh_scheduler=True,exact_optimizer_resume=False,selection_unchanged=True,
    preprocessing_refitted=False,architecture_changed=False,context_tokens=512,max_target_tokens=512,
    temperature=0,full_vocabulary_size=32,batch_size=8,full180_train_readout_before_fit=True,
    full180_train_readout_after_each_endpoint=True,train_readout_used_for_selection=False,
    zero_arm_exact_archived_original_only_replay=True,max_seconds_per_fit=180,max_seconds_entire_width=900,
    max_seconds_per_postfit=30,memory_bytes_per_fit=1073741824,cpu_slots_per_width=1,memory_mb_per_width=1536,
    storage_bytes_per_width=400000000,encoder_executed=False,downloads_performed=False,
    cache_scope='warm authenticated R4 TRAIN vectors;metric disk cache disabled',
    bridge_names=[],legal_ir_evaluate_provers=False,metric_disk_cache_used=False)


def require(value,message):
    if not value: raise ValueError(message)


def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1048576),b''):h.update(block)
    return h.hexdigest()


def bound(manifest,path,expected=None):
    path=Path(path).resolve();wanted=manifest['inputs'].get(str(path))
    require(wanted is not None and (expected is None or wanted==expected),'unbound input: '+str(path))
    raw=path.read_bytes();require(hashlib.sha256(raw).hexdigest()==wanted,'changed input: '+str(path))
    return json.loads(raw)


def check_deadline(deadline):
    if time.monotonic()>=deadline:raise TimeoutError('entire-width paraphrase modality deadline')


def validate_plan(plan):
    require(type(plan) is dict and all(type(plan.get(k)) is type(v) and
        json.dumps(plan[k],sort_keys=True,allow_nan=False)==json.dumps(v,sort_keys=True,allow_nan=False)
        for k,v in FIXED.items()),'fixed paraphrase modality recipe differs')


def package_inventory():
    return {str(Path(module.__file__).resolve()):sha(module.__file__)
        for name,module in list(sys.modules.items())
        if (name=='ipfs_datasets_py' or name.startswith('ipfs_datasets_py.')) and getattr(module,'__file__',None)}


def source_inventory(args,ctx):
    allowed=dict(ctx['paraphrase_manifest']['producer_pins'])
    allowed.update({str((args.extension_root/rel).resolve()):value
        for rel,value in ctx['paraphrase_manifest']['extensions'].items()})
    found=package_inventory()
    for path,value in found.items():require(allowed.get(path)==value,'unbound resident producer: '+path)
    return found


def recheck(args,manifest,manifest_sha,deadline):
    check_deadline(deadline)
    require(sha(args.manifest)==manifest_sha and sha(args.plan)==manifest['plan_sha256'],'changed plan/manifest')
    for path,wanted in manifest['inputs'].items():
        check_deadline(deadline);require(sha(path)==wanted,'changed sealed input: '+path)
    for rel,wanted in manifest['extensions'].items():require(sha(args.extension_root/rel)==wanted,'changed extension: '+rel)
    check_deadline(deadline)


def load_context(args,deadline):
    require(not args.output.exists(),'fresh output must remain absent through parent initialization')
    manifest=json.loads(args.manifest.read_bytes());plan=json.loads(args.plan.read_bytes());validate_plan(plan)
    require(plan['input_sha256']==manifest['inputs'],'input plan differs');manifest_sha=sha(args.manifest)
    recheck(args,manifest,manifest_sha,deadline)
    parent=bound(manifest,manifest['parent_manifest']);bound(manifest,manifest['parent_plan'])
    root=Path(manifest['parent_extension_root'])
    require(sha(root/PARENT_RUNNER)==parent['extensions'][PARENT_RUNNER],'frozen parent runner differs')
    spec=importlib.util.spec_from_file_location('_paraphrase_modality_parent',root/PARENT_RUNNER)
    owner=importlib.util.module_from_spec(spec);spec.loader.exec_module(owner)
    previous=SimpleNamespace(**vars(args));previous.manifest=Path(manifest['parent_manifest'])
    previous.plan=Path(manifest['parent_plan']);previous.extension_root=root
    ctx=owner.load_context(previous,deadline);owner.source_inventory(previous,ctx)
    helper=ctx['helpers'].extension(args.extension_root,AUTO+'paraphrase_modality_auxiliary_training.py',
        PREFIX+'paraphrase_modality_auxiliary_training',manifest['extensions'])
    setattr(sys.modules[PREFIX[:-1]],'paraphrase_modality_auxiliary_training',helper)
    trainer=ctx['helpers'].extension(args.extension_root,AUTO+'long_span_source_value_training.py',
        PREFIX+'_paraphrase_modality_training_owner',manifest['extensions'])
    ctx['owners']['long_span_source_value_training']=trainer
    baselines={}
    for width,path in manifest['baseline_summaries'].items():
        run=bound(manifest,path)
        require(run['dimension']==int(width) and run['arm']=='original-only' and run['budget_completed'] is True,
            'archived original-only baseline differs')
        bound(manifest,run['training_ref']['path'],run['training_ref']['sha256']);baselines[width]=run
    require(set(baselines)=={'384','768'},'both archived zero-replay baselines required')
    ctx.update(paraphrase_manifest=manifest,paraphrase_plan=plan,paraphrase_manifest_sha=manifest_sha,
        paraphrase_parent=owner,paraphrase_helper=helper,paraphrase_baselines=baselines)
    source_inventory(args,ctx);check_deadline(deadline)
    return ctx


def train_candidate(lane,model,payload,deadline):
    check_deadline(deadline)
    auxiliary={} if lane['dimension']!=384 else dict(auxiliary_source_modality_bank=lane['modality_banks']['used113'],
        auxiliary_source_modality_weight=.05)
    return lane['owners']['long_span_source_value_training'].train(model,lane['rows']['train'],lane['rows']['validation'],
        training_references=lane['references']['train'],validation_references=lane['references']['validation'],
        codec=lane['donor']['codec'],input_transform=lane['donor']['input_transform'],lineage=lane['lineage'],
        validate_rule=lane['validate_rule'],validator_id=lane['validator_id'],curriculum=lane['stages'],
        strategy='semantic_fields',cardinality_weight=.25,count_exposure='balanced_all',source_value_weight=.25,
        source_contexts=lane['source_contexts'],action_contrastive_weight=.05,generated_boundary_weight=.05,
        generated_boundary_site_policy='first_last',generated_boundary_retry_on_mismatch=True,
        generated_source_margin_weight=0.,generated_source_margin_replay=False,
        non_action_learning_rate_multiplier=10.,paraphrase_modality_auxiliary=payload,training_deadline=deadline,
        config=dict(seed=1729,max_seconds=min(180.,deadline-time.monotonic()),max_target_tokens=512,batch_size=8,
            learning_rate=.0001,max_optimizer_steps=1000,patience=0,validation_interval=4,alpha=0.,
            max_memory_bytes=1073741824),**auxiliary)


def validate_original_streams(lane,report,baseline,parent_sha):
    lane['selected_runner'].validate_report(lane,report,dict(name='continue-lr0001',learning_rate=.0001),parent_sha)
    for key in ('decoder_row_ids','count_row_ids'):
        require([u[key] for u in report['committed_updates']]==[u[key] for u in baseline['committed_updates']],
            'original committed stream changed: '+key)
    if lane['dimension']==384:
        require([u['auxiliary_source_modality']['receipt']['row_ids'] for u in report['committed_updates']]
            ==[u['auxiliary_source_modality']['receipt']['row_ids'] for u in baseline['committed_updates']],
            'original384 modality stream changed')


def validate_zero_replay(report,baseline):
    for key in ('initial_weights_sha256','selected_weights_sha256','last_complete_attempt_weights_sha256','selected_epoch'):
        require(report[key]==baseline[key],'zero forward control changed archived baseline: '+key)
    keys=('token_ce','weighted_token_ce','count_ce','source_value_ce','raw_reconstruction_mse','objective','preclip_norm',
        'learning_rate','target_token_presentations','source_value_presentations')
    require(len(report['committed_updates'])==len(baseline['committed_updates'])==170,'complete zero replay required')
    for actual,old in zip(report['committed_updates'],baseline['committed_updates']):
        require(all(actual[key]==old[key] for key in keys),'zero auxiliary changed original numerical update')


def prepare_bank(ctx,lane,inventory,deadline):
    return ctx['paraphrase_helper'].prepare_bank(lane['rows']['train'],lane['rows']['validation'],
        training_references=lane['references']['train'],validation_references=lane['references']['validation'],
        source_contexts=lane['source_contexts'],codec=lane['donor']['codec'],validate_rule=lane['validate_rule'],
        source_inventory=inventory,deadline=deadline)


def tensor_cache(ctx,lane,model,bank,deadline):
    check_deadline(deadline)
    return ctx['paraphrase_helper'].prepare_tensor_cache(lane['core']._torch(),model,bank,
        codec=lane['donor']['codec'],input_transform=lane['donor']['input_transform'],seed=1729,
        deadline=deadline,max_optimizer_steps=170)


def schedule(bank,digest):
    """Independent pure replay of the declared six-stratum committed-step order."""
    strata=[tuple(item.split(':',1)) for item in FIXED['paraphrase_auxiliary_strata']]
    rows=bank['rows'];orders=[]
    for stratum in strata:
        indices=[i for i,row in enumerate(rows) if (row['modality'],row['template'])==stratum]
        require(len(indices)==30,'all six complete30row strata required')
        orders.append(sorted(indices,key=lambda i:digest([1729,stratum,rows[i]['source_sha256'],rows[i]['id']])))
    draws=[];exposures={row['id']:0 for row in rows}
    for step in range(170):
        indices=[order[step%30] for order in orders];ids=[rows[i]['id'] for i in indices]
        require(len(set(ids))==6,'distinct auxiliary rows required')
        for identity in ids:exposures[identity]+=1
        draws.append(dict(step=step,indices=indices,row_ids=ids,
            source_sha256=[rows[i]['source_sha256'] for i in indices],
            strata=[[rows[i]['modality'],rows[i]['template']] for i in indices],
            target_token_ids=[rows[i]['modality_token_id'] for i in indices]))
    require(len(exposures)==180 and sum(exposures.values())==1020 and set(exposures.values())=={5,6},
        'fixed full-bank exposure differs')
    return dict(bank_sha256=bank['bank_sha256'],draws=draws,orders=orders,per_source_exposures=exposures,
        row_presentations=1020,per_modality_presentations={'O':340,'P':340,'F':340},
        source_rows_used_for_preprocessing=False,decoder_rows_changed=False,**FALSE)


def validate_cache_schedule(helper,cache,declared):
    require(cache.receipt['orders']==declared['orders'],'cache sampler differs from independently declared schedule')
    for draw in declared['draws']:
        require(list(helper.select_indices(cache,draw['step']))==draw['indices'],'auxiliary sampler differs')


def validate_independent_inputs(ctx,lane,bank,declared,baseline):
    manifest=ctx['paraphrase_manifest'];paths=manifest['independent_inputs'];width=str(lane['dimension'])
    common=bound(manifest,paths['bank_common']);vectors=bound(manifest,paths['bank_vectors'][width])
    require(len(common)==len(vectors)==len(bank['rows'])==180,'complete independent TRAIN bank required')
    for row,old,native in zip(bank['rows'],common,vectors):
        require(all(row[k]==old[k] for k in ('id','source_text','source_sha256','modality','modality_token_id','template'))
            and row['target']==old['rule'] and row['parent_id']==old['paragraph_id'], 'independent TRAIN bank binding differs')
        raw=struct.pack('<'+'f'*lane['dimension'],*row['input'])
        require(native['row_id']==row['id'] and native['source_sha256']==row['source_sha256']
            and hashlib.sha256(raw).hexdigest()==native['float32_sha256'],'independent native TRAIN vector differs')
    require(declared['draws']==bound(manifest,paths['auxiliary_schedule']),'independent auxiliary draw schedule differs')
    primary=bound(manifest,paths['primary_schedules'][width])
    require(len(primary)==len(baseline['committed_updates'])==170,'complete independent original schedule required')
    for update,item in zip(baseline['committed_updates'],primary):
        require(update['decoder_row_ids']==item['decoder_ids'] and update['count_row_ids']==item['count_ids'],
            'archived original streams differ from independent schedule')
        if lane['dimension']==384:
            require(update['auxiliary_source_modality']['receipt']==item['original_auxiliary_source_modality'],
                'archived original384 auxiliary differs from independent schedule')
    declared['independent_inputs_verified']=True


def validate_auxiliary_report(report,arm,declared,bank):
    summary=report['paraphrase_modality_auxiliary'];positive=arm['weight']>0.
    require(summary['weight']==arm['weight'] and summary['bank_receipt']['bank_sha256']==bank['bank_sha256']
        and summary['committed_updates']==170 and summary['committed_clause_presentations']==1020
        and summary['positively_supervised_clause_presentations']==(1020 if positive else 0)
        and summary['committed_presentations_per_modality']=={'O':340,'P':340,'F':340},
        'complete auxiliary budget or source ownership differs')
    require(summary['zero_weight_graph_attached'] is False and summary['used_for_selection'] is False
        and summary['decoder_rows_replaced'] is False and summary['normalization_refitted'] is False
        and 'source_training_mixture' not in report,'auxiliary changed original ownership')
    for index,(update,draw) in enumerate(zip(report['committed_updates'],declared['draws'])):
        item=update['paraphrase_modality_auxiliary'];receipt=item['receipt']
        require(item['zero_based_committed_step']==index and item['weight']==arm['weight']
            and receipt['committed_step']==index and receipt['bank_sha256']==bank['bank_sha256']
            and receipt['full_vocabulary_size']==32 and receipt['gradient_enabled'] is positive,
            'auxiliary gradient/step/bank binding differs')
        require(all(receipt[key]==draw[key] for key in ('indices','row_ids','source_sha256','target_token_ids'))
            and [[r['modality'],r['template']] for r in receipt['strata']]==draw['strata'],
            'committed auxiliary source or target stream differs')
        if not positive:
            require(item['weighted_loss']==0. and item['base_objective']==update['objective'],
                'zero diagnostic changed objective')


def bank_readout(ctx,lane,model,bank,deadline):
    check_deadline(deadline);before=lane['core'].tensor_digest(model)
    cache=tensor_cache(ctx,lane,model,bank,deadline)
    value=ctx['paraphrase_helper'].evaluate_bank(lane['core']._torch(),model,cache,
        deadline=min(deadline,time.monotonic()+30.))
    require(value['complete'] and len(value['rows'])==180 and value['groups']['all']['rows']==180
        and value['model_tensor_sha256']==before and lane['core'].tensor_digest(model)==before,
        'full180 detached TRAIN readout incomplete or changed model')
    for modality in ('O','P','F'):
        require(value['groups']['modality:'+modality]['rows']==60,'complete TRAIN modality readout required')
        for template in ('rule_gerund_by_actor','topicalized_actor_norm'):
            require(value['groups']['stratum:'+modality+':'+template]['rows']==30
                and value['groups']['template:'+template]['rows']==90,'complete TRAIN template readout required')
    require(value['used_for_selection'] is False and value['optimizer_steps']==0,'TRAIN readout changed authority')
    check_deadline(deadline);return value


def execute(args):
    started=time.monotonic();deadline=started+FIXED['max_seconds_entire_width']
    require(args.dimension in (384,768),'explicit native width required')
    ctx=load_context(args,deadline);before=source_inventory(args,ctx);save=ctx['helpers'].save
    args.output.mkdir(parents=True)
    save(args.output/'sealed-recipe.json',dict(plan=ctx['paraphrase_plan'],manifest=ctx['paraphrase_manifest'],**FALSE))
    lane=ctx['mixture_owner'].prepare_lane(ctx,args.dimension)
    lane['continuation_manifest']=ctx['paraphrase_manifest'];check_deadline(deadline)
    parent=ctx['mixture_parents'][str(args.dimension)];ref=parent['states']['selected']
    archived=ctx['paraphrase_baselines'][str(args.dimension)]
    baseline=bound(ctx['paraphrase_manifest'],archived['training_ref']['path'],archived['training_ref']['sha256'])
    inventory=ctx['paraphrase_parent'].envelope(ctx,args.dimension,'original_only')
    inventory_ref=save(args.output/'source-inventory.json',inventory)
    bank=prepare_bank(ctx,lane,inventory,deadline);bank_ref=save(args.output/'paraphrase-bank.json',bank)
    declared=schedule(bank,lane['core'].digest)
    validate_independent_inputs(ctx,lane,bank,declared,baseline)
    schedule_ref=save(args.output/'predeclared-auxiliary-schedule.json',declared)
    for label,value in [('preprocessing',lane['preparation']),('source-contexts',lane['source_contexts']),('training-rows',lane['rows'])]:
        save(args.output/(label+'.json'),value)
    runs=[]
    for arm in ARMS:
        check_deadline(deadline);folder=args.output/arm['name']
        model=ctx['mixture_owner'].restore_endpoint(lane,parent,'selected')
        require(lane['core'].tensor_digest(model)==ref['tensor_sha256'],'exact R13 parent tensor parity required')
        initial=ctx['paraphrase_parent'].bounded_evaluate(lane,model,'validation','conditioned',deadline)
        oldref=parent['postfit']['selected']['validation'];old=bound(ctx['paraphrase_manifest'],oldref['path'],oldref['sha256'])
        require(initial['predictions']==old['predictions'],'original development prediction parity differs')
        initial_ref=save(folder/'parent-validation.json',initial)
        parity=dict(predictions_equal=True,rows=len(initial['predictions']),parent_tensor_sha256=ref['tensor_sha256'],
            restored_tensor_sha256=lane['core'].tensor_digest(model),parent_prediction_ref=oldref,restored_prediction_ref=initial_ref)
        cache=tensor_cache(ctx,lane,model,bank,deadline)
        validate_cache_schedule(ctx['paraphrase_helper'],cache,declared)
        cache_ref=save(folder/'auxiliary-cache-receipt.json',cache.receipt);del cache
        initial_readout=save(folder/'parent-paraphrase-readout.json',bank_readout(ctx,lane,model,bank,deadline))
        if args.phase=='preflight':
            runs.append(dict(arm=arm['name'],dimension=args.dimension,initial_parity=parity,
                bank=bank_ref,source_inventory=inventory_ref,schedule=schedule_ref,cache=cache_ref,
                full180_parent_readout=initial_readout));del model;continue
        states={'initial':lane['native_runner'].save_state(lane,model,arm,'initial',False,folder/'initial-state.json')}
        payload=dict(source_inventory=inventory,weight=arm['weight']);fit_started=time.monotonic()
        try:value=train_candidate(lane,model,payload,deadline)
        except BaseException as error:
            save(folder/'training-failure.json',dict(error_type=type(error).__name__,
                caller_tensor_sha256=lane['core'].tensor_digest(model),parent_tensor_sha256=ref['tensor_sha256'],
                initial_state=states['initial'],complete=False,partial_internal_state_available=False,**FALSE))
            raise
        seconds=time.monotonic()-fit_started;report=value['report'];report_ref=save(folder/'training.json',report)
        for role,state in [('selected',value['state_dict']),('last-attempt',value['last_complete_attempt_state_dict'])]:
            if state is None:continue
            lane['native_runner'].validate_wrapper_state(lane,state);model.load_state_dict(state,strict=True)
            states[role]=lane['native_runner'].save_state(lane,model,arm,role,
                role=='selected' or report['last_complete_attempt_is_selected'],folder/(role+'-state.json'))
        save(folder/'retained-endpoints.json',dict(states=states,training_ref=report_ref,
            full_budget_validation_completed=False,comparison_accepted=False,**FALSE))
        check_deadline(deadline);validate_original_streams(lane,report,baseline,ref['tensor_sha256'])
        validate_auxiliary_report(report,arm,declared,bank)
        if arm['weight']==0.:validate_zero_replay(report,baseline)
        panels={};readouts={}
        for role,state,predictions in [('selected',value['state_dict'],value['predictions']),
            ('last-attempt',value['last_complete_attempt_state_dict'],value['last_complete_attempt_predictions'])]:
            check_deadline(deadline);require(state is not None,'complete endpoint required')
            model.load_state_dict(state,strict=True)
            expected=report['selected_weights_sha256'] if role=='selected' else report['last_complete_attempt_weights_sha256']
            require(lane['core'].tensor_digest(model)==expected,'endpoint tensor differs')
            readouts[role]=save(folder/role/'paraphrase-modality-readout.json',bank_readout(ctx,lane,model,bank,deadline))
            compact=ctx['paraphrase_parent'].original_panels(lane,model,predictions,folder/role,deadline)
            require(len(compact)==9,'all original panels required')
            panels[role]={label:dict(path=str(folder/role/('evaluation-'+label+'.json')),
                sha256=sha(folder/role/('evaluation-'+label+'.json')),numerical=p['numerical'],fidelity=p['source_fidelity'])
                for label,p in compact.items()}
        record=dict(arm=arm['name'],dimension=args.dimension,seed=1729,recipe=arm,parent_state=ref,
            initial_parity=parity,full180_parent_readout=initial_readout,bank=bank_ref,source_inventory=inventory_ref,
            schedule=schedule_ref,cache=cache_ref,states=states,training_ref=report_ref,postfit=panels,
            full180_postfit_readouts=readouts,budget_completed=True,fresh_optimizer=True,exact_optimizer_resume=False,
            zero_arm_archived_replay_verified=arm['weight']==0.,encoder_executed=False,
            training_call_elapsed_seconds=seconds,training_rows_per_second=1220/seconds,**FALSE)
        saved=save(folder/'summary.json',record);runs.append(dict(arm=arm['name'],summary_path=saved['path'],summary_sha256=saved['sha256']))
        print(json.dumps(dict(dimension=args.dimension,arm=arm['name'],steps=report['optimizer_steps'],fit_seconds=seconds)),flush=True)
        del model,value,report,initial,old,compact
    after=source_inventory(args,ctx)
    require(all(after.get(k)==v for k,v in before.items()),'resident source changed')
    recheck(args,ctx['paraphrase_manifest'],ctx['paraphrase_manifest_sha'],deadline)
    result=dict(schema='paraphrase-modality-training-comparison/v1',complete=len(runs)==2,phase=args.phase,
        dimension=args.dimension,runs=runs,source_dependencies=after,elapsed_seconds=time.monotonic()-started,
        encoder_executed=False,cache_scope=FIXED['cache_scope'],
        timing_scope='sequential arms within width; independent width may share host under separate lease',**FALSE)
    save(args.output/'summary.json',result);return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('dependency-root','extension-root','manifest','plan','output'):parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--phase',choices=['preflight','training'],required=True)
    parser.add_argument('--dimension',type=int,choices=[384,768],required=True)
    execute(parser.parse_args())


if __name__=='__main__':main()
