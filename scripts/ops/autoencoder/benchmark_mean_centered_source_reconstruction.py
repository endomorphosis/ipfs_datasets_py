#!/usr/bin/env python3
"""Fixed-state scalar-prior diagnostic and matched mean-centered training.

Two separately admitted phases preserve full source-fidelity selection. The
diagnostic prerequisite is integrity/raw replay, never measured efficacy.
"""
import argparse
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import time

AUTO='ipfs_datasets_py/logic/formalization/autoencoder/'
PREFIX='ipfs_datasets_py.logic.formalization.autoencoder.'
FALSE=dict(qualified=False,admitted=False,proof_authority=False,source_semantics_verified=False,
    checkpoint_promoted=False,convergence_proven=False,fresh_holdout=False,lake_executed=False,
    formalized=False,roundtrip_ok=False)
PRIOR_ARMS=[mode+('-boundary-' if guided else '-unguided-')+str(seed)
    for seed in (1729,2718) for mode in ('none','center_rms') for guided in (False,True)]
MODES=['raw','off','mean_centered']
CONTROLS=[['validation','validation','conditioned'],['training','train','conditioned'],
    ['zero-condition','validation','zero_condition'],['source-shuffle','validation','source_shuffle'],
    ['cross-length-shuffle','validation','cross_length_shuffle']]
COMMON=dict(representation_dimension=384,epochs_per_source_stage=20,
    fixed_encoder_context_tokens=512,fixed_decoder_output_limit=512,batch_size=8,
    temperature=0,no_downloads=True,selection_unchanged=True,
    generation_reference_count_access=False,generation_reference_prefix_access=False,
    scalar_mean_fit_split='train',scalar_auxiliary_readout='unchanged_raw_head_logits',
    scalar_centering='subtract_current_head_logits_at_authenticated_training_feature_mean',
    max_seconds_per_postfit=30,max_seconds_per_numerical_evaluation=20,
    native_qualification=False,production_promotion_allowed=False)
DIAGNOSTIC_FIXED=dict(COMMON,schema='mean-centered-source-diagnostic-plan/v1',
    state_order=PRIOR_ARMS,scalar_modes=MODES,split_order=['train','validation'],
    expected_panels=48,expected_rows_per_panel=48,training_executed=False,optimizer_steps=0,
    archived_raw_predictions_must_match=True,archived_raw_metrics_must_match=True,
    raw_state_copy_persistence=False,diagnostic_efficacy_used_to_select_training=False)
ARMS=[dict(name=mode,scalar_mode=mode,normalization='center_rms',guide_boundary=True,
    source_value_weight=.25,count_exposure='balanced_all',cardinality_weight=.25)
    for mode in ('raw','mean_centered')]
TRAINING_FIXED=dict(COMMON,schema='mean-centered-source-training-plan/v1',arms=ARMS,
    seed_order=[1729,2718],conditioning='every_step',loss='semantic_fields',
    expected_optimizer_steps_per_arm=340,expected_training_token_presentations_per_arm=225840,
    expected_count_presentations_per_arm=2440,expected_source_value_presentations_per_candidate=25600,
    expected_balanced_count_presentations={'1':610,'2':610,'4':610,'8':610},
    learning_rate=.001,max_seconds_per_arm=90,validation_interval=4,
    source_value_max_rules=8,source_value_fields=['actor','action','modality','object'],
    source_value_full_vocabulary=True,projection_frozen=True,inherited_decoder_and_count_trainable=True,
    normalization_scale='global_rms_row_l2',count_prior_classes=list(range(1,33)),
    count_prior_total_concentration=1.,count_prior_alpha_per_class=1./32,
    initial_greedy_invariance_required=True,raw_training_replay_parity_required=True,
    teacher_distillation_used=False,postfit_controls=CONTROLS,max_seconds_per_preprocessing=30,
    diagnostic_prerequisite='completed_integrity_audit_and_raw_replay_only',
    diagnostic_efficacy_used_to_select_training=False)


def require(condition,message):
    if not condition:raise ValueError(message)


def validate_plan(plan,phase):
    require(phase in ('diagnostic','training'),'unknown experiment phase')
    fixed=DIAGNOSTIC_FIXED if phase=='diagnostic' else TRAINING_FIXED
    require(type(plan) is dict and all(json.dumps(plan.get(k),sort_keys=True,allow_nan=False)==
        json.dumps(v,sort_keys=True,allow_nan=False) for k,v in fixed.items()),
        'fixed mean-centered '+phase+' recipe differs')


def load_helper(root,pins,relative,name):
    path=root/relative
    require(hashlib.sha256(path.read_bytes()).hexdigest()==pins.get(relative),'frozen helper differs: '+relative)
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def expected_catalog(root):
    return [dict(name=arm,prior_arm=arm,role='last-attempt',
        state_path=str(root/arm/'last-attempt-state.json'),
        archived_evaluations={split:str(root/arm/'last-attempt'/('evaluation-'+label+'.json'))
            for split,label in [('train','training'),('validation','validation')]}) for arm in PRIOR_ARMS]


def authenticate_predecessor(manifest,archives):
    public=archives.read_bound(manifest['parent_public_manifest'],manifest)
    published=archives.read_bound(manifest['parent_public_results'],manifest)
    require(public.get('schema')=='decoder-projected-source-archive/v1'
        and published.get('schema')=='decoder-projected-source-results/v1'
        and published.get('complete') is True and public['archive']==published['archive'],
        'complete published projected-source predecessor required')
    summary=archives.read_bound(manifest['parent_summary'],manifest,public)
    require(summary.get('schema')=='projected-source-reconstruction-comparison/v1'
        and summary.get('complete') is True and all(summary.get(k) is False for k in FALSE),
        'complete nonqualifying projected-source comparison required')
    runs={run['arm']:run for run in summary['runs']}
    require(len(runs)==len(summary['runs'])==8 and list(runs)==PRIOR_ARMS,
        'exact prior eight-arm inventory required')
    require(manifest['state_catalog']==expected_catalog(Path(manifest['parent_summary']).parent),
        'exact prior state/control catalog required')
    preprocessing=archives.read_bound(manifest['parent_preprocessing'],manifest,public)
    require(preprocessing.get('schema')=='projected-source-reconstruction-preprocessing/v1'
        and hashlib.sha256(Path(manifest['parent_preprocessing']).read_bytes()).hexdigest()==summary['preprocessing_sha256']
        and preprocessing.get('validation_vectors_used') is False
        and preprocessing.get('validation_targets_used') is False,
        'training-only predecessor preprocessing required')
    require(all(run['budget_completed'] is True and run['training']['selected_epoch']==0 for run in runs.values()),
        'prior complete unselected state policy differs')
    return public,runs,preprocessing


def diagnostic_prerequisite(manifest,archives):
    summary=archives.read_bound(manifest['diagnostic_summary'],manifest)
    audit=archives.read_bound(manifest['diagnostic_audit'],manifest)
    require(summary.get('schema')=='mean-centered-source-diagnostic-comparison/v1'
        and summary.get('complete') is True and summary.get('raw_replay_parity') is True
        and summary.get('training_executed') is False and len(summary.get('panels',[]))==48
        and all(summary.get(k) is False for k in FALSE), 'complete immutable raw-replay diagnostic required')
    require(audit.get('schema')=='mean-centered-source-diagnostic-audit/v1'
        and audit.get('phase')=='diagnostics' and audit.get('passed') is True
        and audit.get('complete') is True and audit.get('failed_check_count')==0
        and audit.get('finding_count')==0 and audit.get('findings')==[],
        'clean diagnostic integrity audit required')
    require(audit.get('diagnostic_summary_sha256')==manifest['inputs'][manifest['diagnostic_summary']]
        and audit.get('plan_sha256')==manifest['inputs'][manifest['diagnostic_plan']]
        and audit.get('manifest_sha256')==manifest['inputs'][manifest['diagnostic_manifest']],
        'diagnostic audit recipe/source manifest binding differs')
    binding=audit.get('artifacts',{}).get(str(Path(manifest['diagnostic_summary'])))
    require(type(binding) is dict and binding.get('sha256')==manifest['inputs'][manifest['diagnostic_summary']]
        and binding.get('bytes')==Path(manifest['diagnostic_summary']).stat().st_size,
        'diagnostic audit does not bind exact completed summary')
    return dict(complete=True,summary_path=manifest['diagnostic_summary'],audit_path=manifest['diagnostic_audit'],
        summary_sha256=manifest['inputs'][manifest['diagnostic_summary']],
        audit_sha256=manifest['inputs'][manifest['diagnostic_audit']],
        acceptance_scope='integrity and archived raw replay only; no efficacy selection',
        training_arms_fixed_before_diagnostic=True,**FALSE)


def validate_export(state,catalog,run,core,codec):
    require(state.get('schema')=='private-projected-source-state/v1'
        and state.get('role')=='last-attempt' and state.get('selected') is False
        and state.get('optimizer_resumable') is False and all(state.get(k) is False for k in FALSE),
        'prior state role or authority differs')
    require(state['recipe']==run['recipe'] and state['codec']==codec
        and core.digest(state['model_state'])==state['weights_sha256']
        and state['tensor_sha256']==run['training']['last_complete_attempt_weights_sha256'],
        'prior state weights/recipe binding differs')


def validate_raw_replay(value,archived,rows,core,codec,transform):
    report=archived['report']
    expected=dict(complete=True,input_dimension=384,max_target_tokens=512,batch_size=8,
        generation_temperature=0,generation_target_access=False,optimizer_steps=0,
        weight_selection_performed=False,validation_rows_sha256=core.digest(rows),
        codec_sha256=core.digest(codec),input_transform_sha256=core.digest(transform))
    require(all(type(report.get(k)) is type(v) and report.get(k)==v for k,v in expected.items()),
        'archived raw evaluation recipe differs')
    require(value['predictions']==archived['predictions'],'raw wrapper changed archived greedy predictions')
    require(value['report']['metrics']==archived['report']['metrics'],
        'raw wrapper changed archived numerical metrics')
    for key in ('metrics','by_length','by_facet'):
        require(value['source_fidelity'][key]==archived['source_fidelity'][key],
            'raw wrapper changed archived source fidelity: '+key)
    require(value['source_count']==archived['source_count']
        and value['source_values']==archived['source_values'],
        'raw wrapper changed archived source-only readouts')
    return dict(predictions_equal=True,numerical_metrics_equal=True,source_fidelity_equal=True,
        raw_source_head_readouts_equal=True,scope='fixed prior state, unchanged raw generation and scoring')


def validate_training_parity(report,prior,body_digests,postfit,core,*,archived_selected):
    """Compare raw numerical work; wrapper metadata/timing/prefixes may differ."""
    fields=['config','strategy','cardinality_weight','count_exposure','source_value_weight',
        'source_value_presentations','committed_decoder_batch_ids_sha256','committed_updates',
        'count_training_row_presentations','count_training_presentations_by_class',
        'count_mean_loss_exposure_by_class','committed_count_batch_ids_sha256',
        'count_selector_initial','count_selector_final','count_training_inventory_sha256',
        'gradient_norms','curriculum','optimizer_steps','row_presentations',
        'valid_target_token_presentations','optimizer_instance_count','optimizer_reinitialized_between_stages',
        'selected_epoch','selection','baseline','selected','last_complete_attempt',
        'last_complete_attempt_is_selected','history','stopped_reason']
    for field in fields:
        require(core.digest(report[field])==core.digest(prior['training'][field]),
            'raw training numerical replay differs: '+field)
    require(body_digests['selected']==prior['training']['selected_weights_sha256']
        and body_digests['last-attempt']==prior['training']['last_complete_attempt_weights_sha256'],
        'raw training underlying tensors differ from prior fit')
    # The initial inventory records four source-only greedy fields; a numerical
    # evaluation additionally records reconstruction vectors and exact-target
    # scores. Compare each authenticated envelope against its own schema.
    selected=postfit['selected']['validation']['predictions']
    initial=prior['initial_greedy_invariance']['predictions']['validation']
    greedy_fields={'id','token_ids','eos_reached','generation_status'}
    numerical_fields=greedy_fields|{'exact_target','reconstructed_input'}
    require(type(selected) is list and type(initial) is list
        and all(type(row) is dict and set(row)==numerical_fields for row in selected)
        and all(type(row) is dict and set(row)==greedy_fields for row in initial),
        'raw selected/initial prediction envelope differs')
    require(core.digest([{key:row[key] for key in greedy_fields} for row in selected])==core.digest(initial),
        'raw selected generation differs from prior initial-selected state')
    require(core.digest(selected)==core.digest(archived_selected['predictions']),
        'raw selected full numerical predictions differ from archived selected evaluation')
    return dict(complete=True,prior_arm=prior['arm'],compared_fields=fields,
        selected_underlying_tensor_sha256=body_digests['selected'],
        last_attempt_underlying_tensor_sha256=body_digests['last-attempt'],
        numerical_updates_exact=True,greedy_predictions_exact=True,
        selected_full_numerical_predictions_exact=True,
        initial_greedy_prediction_fields=sorted(greedy_fields),
        wrapper_state_prefix='body.',timing_equality_claimed=False,
        scope='raw wrapper replay of identical prior center_rms boundary fit')


def load_context(args):
    manifest=json.loads(args.manifest.read_bytes())
    replay=load_helper(args.extension_root,manifest['extensions'],
        'scripts/ops/autoencoder/decoder_fidelity_replay.py','_mean_centered_replay')
    ctx=replay.load_context(args,validate_plan=lambda plan:validate_plan(plan,args.phase))
    helpers=ctx['helpers'];pins=ctx['pins']
    old=load_helper(args.extension_root,pins,'scripts/ops/autoencoder/benchmark_projected_source_reconstruction.py','_mean_centered_prior')
    archives=load_helper(args.extension_root,pins,'scripts/ops/autoencoder/benchmark_decoder_prefix_diagnostics.py','_mean_centered_archives')
    public,runs,preprocessing=authenticate_predecessor(manifest,archives)
    names=['decoder_cardinality_experiment','long_span_cardinality_training','long_span_count_exposure_training',
        'source_value_decoder_experiment','projected_source_decoder_experiment','mean_centered_source_decoder_experiment',
        'long_span_source_value_training']
    owners={name:helpers.extension(args.extension_root,AUTO+name+'.py',PREFIX+name,pins) for name in names}
    exposure=load_helper(args.extension_root,pins,'scripts/ops/autoencoder/benchmark_decoder_count_exposure.py','_mean_centered_exposure')
    decision=None if args.phase=='diagnostic' else diagnostic_prerequisite(manifest,archives)
    ctx.update(manifest=manifest,old=old,archives=archives,public=public,prior_runs=runs,
        preprocessing=preprocessing,owners=owners,exposure=exposure,decision=decision)
    return ctx


def fresh_base(ctx,normalization,guide_boundary):
    core=ctx['core'];pre=ctx['preprocessing']
    persistent=ctx['adapter'].bind_persistent_model(ctx['base_model'].body,dimension=384,conditioning='every_step')
    require(core.tensor_digest(persistent)==pre['initializer_tensor_sha256'],'original inherited initializer differs')
    for name,parameter in persistent.named_parameters():
        if name.startswith(('body.projection_down.','body.projection_up.')):parameter.requires_grad_(False)
    return ctx['owners']['projected_source_decoder_experiment'].bind_projected_source_model(
        persistent,codec=ctx['donor']['codec'],normalization_receipt=pre['normalizations'][normalization],
        count_prior_receipt=pre['count_prior'],guide_boundary=guide_boundary,scalar_guidance=True)


def restore_prior(ctx,catalog):
    state=ctx['archives'].read_bound(catalog['state_path'],ctx['manifest'],ctx['public'])
    run=ctx['prior_runs'][catalog['prior_arm']]
    validate_export(state,catalog,run,ctx['core'],ctx['donor']['codec'])
    model=fresh_base(ctx,state['recipe']['normalization'],state['recipe']['guide_boundary'])
    require(model.describe()==state['architecture'],'prior source architecture differs')
    require(set(model.state_dict())==set(state['model_state']),'prior tensor inventory differs')
    model.load_state_dict({key:ctx['numerical']._tensor(state['model_state'][key],tensor,key)
        for key,tensor in model.state_dict().items()},strict=True)
    require(ctx['core'].tensor_digest(model)==state['tensor_sha256'],'restored prior tensor digest differs')
    return model,state['tensor_sha256']


def wrap(ctx,base,mode):
    return ctx['owners']['mean_centered_source_decoder_experiment'].bind_mean_centered_source_model(
        base,scalar_mode=mode,training_feature_mean_receipt=ctx['preprocessing']['normalizations']['center_rms'])


def guidance_diagnostic(ctx,model,rows,deadline):
    """Record actual source-only guidance, separately from raw auxiliary scores."""
    import torch
    started=time.monotonic();records=[];core=ctx['core'];before=core.tensor_digest(model)
    modes={name:module.training for name,module in model.named_modules()}
    size=len(ctx['donor']['codec']['target_vocabulary'])
    try:
        model.eval()
        with torch.inference_mode():
            for offset in range(0,len(rows),8):
                require(time.monotonic()<deadline,'scalar guidance diagnostic deadline exceeded')
                part=rows[offset:offset+8]
                data=ctx['owners']['long_span_count_exposure_training']._source_batch(torch,part,ctx['donor']['input_transform'])
                projected=model.project(data)
                logits=model.source_value_guidance_logits(projected)
                require(logits.dtype==torch.float32 and logits.device.type=='cpu'
                    and tuple(logits.shape)==(len(part),8,4,size) and bool(torch.isfinite(logits).all()),
                    'finite bounded scalar guidance scores required')
                for row,scores,guess in zip(part,logits.tolist(),logits.argmax(-1).tolist()):
                    records.append(dict(id=row['id'],applied_logits=scores,predicted_token_ids=guess))
    finally:
        for name,module in model.named_modules():module.training=modes[name]
    require(core.tensor_digest(model)==before,'scalar guidance readout changed model')
    require(time.monotonic()<deadline,'scalar guidance diagnostic deadline exceeded')
    return dict(schema='applied-source-scalar-guidance-diagnostic/v1',rows=records,
        source_only=True,reference_documents_passed_to_model=False,target_tokens_passed_to_model=False,
        posterior_probability_claimed=False,metric_used_for_selection=False,
        scope='actual causal-site residual scores; argmax alone is not generated formula fidelity',
        elapsed_seconds=time.monotonic()-started,**FALSE)


def evaluate(ctx,model,split,control):
    import torch
    started=time.monotonic();plan=ctx['plan'];core=ctx['core'];owners=ctx['owners']
    rows=ctx['rows'][split]
    execution=dict(kind=control,source_assignment={row['id']:row['id'] for row in rows})
    if control=='source_shuffle':
        rows,execution=ctx['helpers'].shuffle_inputs(rows,ctx['references'][split]);execution['shuffle_policy']='within_length'
    elif control=='cross_length_shuffle':rows,execution=ctx['old'].cross_length_shuffle(rows,ctx['references'][split])
    elif control=='zero_condition':model=owners['mean_centered_source_decoder_experiment'].bind_zero_condition_model(model)
    elif control!='conditioned':raise ValueError('unknown mean-centered control')
    deadline=started+plan['max_seconds_per_postfit']
    value=core.evaluate_model(model,rows,codec=ctx['donor']['codec'],input_transform=ctx['donor']['input_transform'],
        lineage=ctx['lineage'],max_target_tokens=512,
        max_seconds=min(plan['max_seconds_per_numerical_evaluation'],deadline-time.monotonic()),batch_size=8)
    require(value['report']['complete'],'incomplete postfit evaluation')
    value['source_fidelity']=ctx['scorer'].score_predictions(ctx['references'][split],value['predictions'],
        codec=ctx['donor']['codec'],validate_rule=ctx['validate_rule'],validator_id=ctx['validator_id'],output_limit=512,
        control={key:execution[key] for key in ('kind','source_assignment')})
    value['source_count']=owners['long_span_count_exposure_training']._count_evaluation(torch,model,rows,
        ctx['references'][split],ctx['donor']['input_transform'],dict(batch_size=8),deadline)
    require(value['source_count'] is not None,'incomplete source count readout')
    value['source_values']=ctx['old'].source_value_diagnostic(torch,model,rows,ctx['references'][split],
        ctx['donor']['codec'],ctx['donor']['input_transform'],deadline,
        scalar_owner=owners['source_value_decoder_experiment'],trainer=owners['long_span_source_value_training'],
        validate_rule=ctx['validate_rule'])
    value['scalar_guidance']=guidance_diagnostic(ctx,model,rows,deadline)
    value['hypothetical_boundary_diagnostics']=ctx['old'].boundary_diagnostics(value['source_count'],ctx['preprocessing']['count_prior'])
    value['execution']={**execution,**ctx['old'].control_scope(control),
        'training_performed':False,'selection_performed':False,
        'provenance_breaking_negative_control':control in ('source_shuffle','cross_length_shuffle')}
    value['scalar_auxiliary_readout_scope']='unchanged raw head logits; not the possibly mean-centered generation residual'
    value['scalar_mode']=model.describe().get('scalar_mode')
    require(time.monotonic()<deadline,'postfit deadline exceeded')
    value['timing']=dict(postfit_evaluation_elapsed_seconds=time.monotonic()-started,
        numerical_api_elapsed_seconds=value['report']['elapsed_seconds'],
        scope='control construction, numerical generation/CE, source fidelity/count/raw and applied-scalar readouts; excludes write')
    return value


def compact_panel(value,*,retain_predictions=False):
    result=dict(numerical=value['report'],source_count=value['source_count'],execution=value['execution'],
        source_values={k:v for k,v in value['source_values'].items() if k!='predictions'},
        source_fidelity={k:v for k,v in value['source_fidelity'].items() if k!='rows'},timing=value['timing'],
        scalar_mode=value['scalar_mode'],scalar_auxiliary_readout_scope=value['scalar_auxiliary_readout_scope'])
    if retain_predictions:result['predictions']=value['predictions']
    return result


def validate_preprocessing(ctx):
    """Recompute projected train-only rows and both sealed receipts, without refit choices."""
    import torch
    started=time.monotonic();deadline=started+30;core=ctx['core'];pre=ctx['preprocessing'];owners=ctx['owners']
    model=fresh_base(ctx,'center_rms',True)
    feature_rows=[];references={row['id']:row for row in ctx['references']['train']}
    with torch.inference_mode():
        for offset in range(0,len(ctx['rows']['train']),8):
            require(time.monotonic()<deadline,'preprocessing replay deadline exceeded')
            rows=ctx['rows']['train'][offset:offset+8]
            projected=model.project(owners['long_span_count_exposure_training']._source_batch(torch,rows,ctx['donor']['input_transform']))
            for row,features in zip(rows,projected.tolist()):
                feature_rows.append(dict(id=row['id'],source_sha256=hashlib.sha256(row['source_text'].encode()).hexdigest(),features=features))
    require(feature_rows==pre['feature_rows'],'original projected training features differ')
    identities=dict(expected_training_ids=[r['id'] for r in ctx['rows']['train']],
        forbidden_validation_ids=[r['id'] for r in ctx['rows']['validation']],training_rows_sha256=core.digest(ctx['rows']['train']))
    require(identities==pre['identities'],'preprocessing cohort binding differs')
    counts=[dict(id=row['id'],source_sha256=row['source_sha256'],count=references[row['id']]['clause_count']) for row in feature_rows]
    require(counts==pre['count_rows'],'training-only count rows differ')
    owner=owners['projected_source_decoder_experiment']
    for mode in ('none','center_rms'):
        require(owner.fit_source_normalization(feature_rows,kind=mode,**identities)==pre['normalizations'][mode],
            'frozen training-only normalization differs')
    require(owner.fit_source_count_prior(counts,**identities)==pre['count_prior'],'frozen count prior differs')
    require(time.monotonic()<deadline,'preprocessing replay deadline exceeded')
    return dict(complete=True,training_feature_rows_sha256=core.digest(feature_rows),
        training_mean_receipt_sha256=pre['normalizations']['center_rms']['receipt_sha256'],
        input_preprocessing_path=ctx['manifest']['parent_preprocessing'],
        validation_features_passed_to_fitting=False,validation_targets_passed_to_fitting=False,
        choice_or_hyperparameter_tuning=False,elapsed_seconds=time.monotonic()-started,**FALSE)


def diagnostic_phase(args,ctx):
    started=time.monotonic();save=ctx['helpers'].save;panels=[]
    for catalog in ctx['manifest']['state_catalog']:
        base,digest=restore_prior(ctx,catalog)
        archived={split:ctx['archives'].read_bound(path,ctx['manifest'],ctx['public'])
            for split,path in catalog['archived_evaluations'].items()}
        for mode in ctx['plan']['scalar_modes']:
            model=wrap(ctx,base,mode)
            require(ctx['core'].tensor_digest(model.body)==digest,'wrapper changed prior underlying tensors')
            for split in ctx['plan']['split_order']:
                result=evaluate(ctx,model,split,'conditioned')
                parity=(validate_raw_replay(result,archived[split],ctx['rows'][split],ctx['core'],
                    ctx['donor']['codec'],ctx['donor']['input_transform']) if mode=='raw' else None)
                result['initial_state_binding']=dict(path=catalog['state_path'],sha256=ctx['manifest']['inputs'][catalog['state_path']],
                    original_tensor_sha256=digest,wrapper_tensor_sha256=ctx['core'].tensor_digest(model),
                    raw_state_rewritten=False)
                result['scalar_calibration']=model.describe()
                result['raw_replay_parity']=parity
                path=args.output/catalog['name']/mode/('evaluation-'+split+'.json')
                artifact=save(path,result)
                panels.append(dict(state=catalog['name'],mode=mode,split=split,artifact=artifact,
                    raw_replay_parity=parity,**compact_panel(result)))
                print(json.dumps(dict(state=catalog['name'],mode=mode,split=split,
                    exact=result['source_fidelity']['metrics']['ordered_exact'],
                    eos=result['source_fidelity']['metrics']['eos_count'],
                    syntax=result['source_fidelity']['metrics']['syntax_valid'])),flush=True)
        require(ctx['core'].tensor_digest(base)==digest,'diagnostic changed source state')
    return dict(schema='mean-centered-source-diagnostic-comparison/v1',panels=panels,
        complete=len(panels)==48,raw_replay_parity=all(p['raw_replay_parity'] is not None for p in panels if p['mode']=='raw'),
        training_executed=False,optimizer_steps=0,raw_state_copy_persistence=False,
        diagnostic_efficacy_used_to_select_training=False,elapsed_seconds=time.monotonic()-started,**FALSE)


def training_phase(args,ctx):
    import torch
    save=ctx['helpers'].save;core=ctx['core'];plan=ctx['plan'];exposure=ctx['exposure']
    selected_paths={'center_rms-boundary-'+str(seed):str(Path(ctx['manifest']['parent_summary']).parent/
        ('center_rms-boundary-'+str(seed))/'selected'/'evaluation-validation.json') for seed in plan['seed_order']}
    require(ctx['manifest'].get('prior_selected_evaluations')==selected_paths,
        'exact two prior selected evaluation bindings required')
    selected_evaluations={arm:ctx['archives'].read_bound(path,ctx['manifest'],ctx['public'])
        for arm,path in selected_paths.items()}
    previous=exposure.load_control_helper(args.extension_root,ctx['pins'])
    budget=exposure.derive_count_budget(ctx['stages'],ctx['rows']['train'],ctx['references']['train'],plan,previous)
    counts={r['id']:r['clause_count'] for r in ctx['references']['train']}
    source_budget=sum(stage['epochs']*sum(4*counts[i] for i in stage['training_ids']) for stage in ctx['stages'])
    require(source_budget==plan['expected_source_value_presentations_per_candidate'],'scalar exposure differs')
    baseline=ctx['adapter'].bind_persistent_model(ctx['base_model'].body,dimension=384,conditioning='every_step')
    initial=ctx['old'].greedy_inventory(torch,core,baseline,ctx['rows'],ctx['donor'],max_seconds=30)
    save(args.output/'original-initial-generation.json',initial)
    summaries=[]
    for seed in plan['seed_order']:
        for recipe in plan['arms']:
            started=time.monotonic();name=recipe['name']+'-'+str(seed)
            model=wrap(ctx,fresh_base(ctx,'center_rms',True),recipe['scalar_mode'])
            initial_replay=ctx['old'].greedy_inventory(torch,core,model,ctx['rows'],ctx['donor'],max_seconds=30)
            require(initial_replay['predictions']==initial['predictions'],'initial scalar calibration changed greedy output')
            initial_replay['identical_to_original_greedy']=True
            save(args.output/name/'initial-generation.json',initial_replay)
            ctx['lineage']['student_lineage']='mean_centered_source_v1:'+name
            before=time.monotonic()
            result=ctx['owners']['long_span_source_value_training'].train(model,ctx['rows']['train'],ctx['rows']['validation'],
                training_references=ctx['references']['train'],validation_references=ctx['references']['validation'],
                codec=ctx['donor']['codec'],input_transform=ctx['donor']['input_transform'],lineage=ctx['lineage'],
                validate_rule=ctx['validate_rule'],validator_id=ctx['validator_id'],curriculum=ctx['stages'],
                strategy='semantic_fields',cardinality_weight=.25,count_exposure='balanced_all',source_value_weight=.25,
                config=dict(seed=seed,max_seconds=90,max_target_tokens=512,batch_size=8,learning_rate=.001,
                    max_optimizer_steps=1000,patience=0,validation_interval=4,alpha=0.))
            fit_seconds=time.monotonic()-before;report=result['report'];folder=args.output/name
            save(folder/'training.json',report)
            save(folder/'selected-predictions.json',result['predictions'])
            save(folder/'last-attempt-predictions.json',result['last_complete_attempt_predictions'])
            postfit={};body_digests={};post_started=time.monotonic()
            for role,state,predictions in [('selected',result['state_dict'],result['predictions']),
                ('last-attempt',result['last_complete_attempt_state_dict'],result['last_complete_attempt_predictions'])]:
                require(state is not None,'complete selected and last-attempt states required')
                model.load_state_dict(state,strict=True)
                expected=report['selected_weights_sha256'] if role=='selected' else report['last_complete_attempt_weights_sha256']
                require(core.tensor_digest(model)==expected,'state role tensor digest differs')
                state_values={key:value.tolist() for key,value in model.state_dict().items()}
                receipt=save(folder/(role+'-state.json'),dict(schema='private-mean-centered-source-state/v1',
                    recipe=recipe,architecture=model.describe(),lineage=deepcopy(ctx['lineage']),codec=ctx['donor']['codec'],
                    model_state=state_values,weights_sha256=core.digest(state_values),tensor_sha256=expected,role=role,
                    selected=role=='selected' or report['last_complete_attempt_is_selected'],optimizer_resumable=False,**FALSE))
                persisted=json.loads(Path(receipt['path']).read_bytes())
                require(core.digest(persisted['model_state'])==persisted['weights_sha256'],'persisted state JSON differs')
                model.load_state_dict({key:ctx['numerical']._tensor(persisted['model_state'][key],value,key)
                    for key,value in model.state_dict().items()},strict=True)
                require(core.tensor_digest(model)==expected,'persisted tensor reload differs')
                body_digests[role]=core.tensor_digest(model.body)
                postfit[role]={}
                for label,split,control in plan['postfit_controls']:
                    value=evaluate(ctx,model,split,control)
                    if label=='validation':require(value['predictions']==predictions,'persisted state generation differs')
                    save(folder/role/('evaluation-'+label+'.json'),value)
                    postfit[role][label]=compact_panel(value,retain_predictions=True)
            prior_arm='center_rms-boundary-'+str(seed)
            replay=None
            if recipe['scalar_mode']=='raw':
                prior=ctx['prior_runs'][prior_arm]
                replay=validate_training_parity(report,prior,body_digests,postfit,core,
                    archived_selected=selected_evaluations[prior_arm])
                catalog=next(c for c in ctx['manifest']['state_catalog'] if c['name']==prior_arm)
                archived=ctx['archives'].read_bound(catalog['archived_evaluations']['validation'],ctx['manifest'],ctx['public'])
                require(postfit['last-attempt']['validation']['predictions']==archived['predictions'],
                    'raw trained final generation differs from original fit')
                save(folder/'raw-training-replay.json',replay)
            completed=(report['optimizer_steps']==budget['optimizer_steps']
                and report['valid_target_token_presentations']==budget['valid_target_token_presentations']
                and report['count_training_row_presentations']==budget['count_presentations']
                and report['source_value_presentations']==source_budget and report['stopped_reason']=='epochs_completed')
            if completed:exposure.validate_completed_exposure(report,budget,recipe)
            summary=dict(arm=name,seed=seed,recipe=recipe,budget_completed=completed,training=report,
                postfit=postfit,initial_greedy_invariance=initial_replay,raw_training_replay=replay,
                underlying_state_tensor_sha256=body_digests,training_call_elapsed_seconds=fit_seconds,
                postfit_elapsed_seconds=time.monotonic()-post_started,elapsed_seconds=time.monotonic()-started,
                trainable_parameter_count=sum(p.numel() for p in model.parameters() if p.requires_grad),
                prefit_budget=budget,**FALSE)
            save(folder/'summary.json',summary);summaries.append(summary)
            last=report['last_complete_attempt']
            print(json.dumps(dict(arm=name,steps=report['optimizer_steps'],selected_epoch=report['selected_epoch'],
                last_exact=last['fidelity']['metrics']['ordered_exact'],
                last_eos=last['fidelity']['metrics']['eos_count'],elapsed=fit_seconds)),flush=True)
    return dict(schema='mean-centered-source-training-comparison/v1',runs=summaries,
        complete=len(summaries)==4 and all(run['budget_completed'] for run in summaries),
        diagnostic_prerequisite=ctx['decision'],diagnostic_efficacy_used_to_select_training=False,
        raw_training_replay_parity=all(run['raw_training_replay']['complete'] for run in summaries if run['recipe']['scalar_mode']=='raw'),
        dimensions_actually_trained=[384],training_executed=True,**FALSE)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for key in ('dependency-root','extension-root','manifest','plan','output'):
        parser.add_argument('--'+key,type=Path,required=True)
    parser.add_argument('--phase',choices=['diagnostic','training'],required=True)
    args=parser.parse_args();ctx=load_context(args);helpers=ctx['helpers']
    before=helpers.inventory(args.dependency_root,args.extension_root,ctx['pins'])
    args.output.mkdir(parents=True)
    helpers.save(args.output/'sealed-recipe.json',dict(plan=ctx['plan'],manifest=ctx['manifest'],
        tree_pin=ctx['tree'],phase=args.phase,diagnostic_prerequisite=ctx['decision'],**FALSE))
    helpers.save(args.output/'preprocessing-replay.json',validate_preprocessing(ctx))
    summary=diagnostic_phase(args,ctx) if args.phase=='diagnostic' else training_phase(args,ctx)
    after=helpers.inventory(args.dependency_root,args.extension_root,ctx['pins'])
    require(all(after.get(path)==digest for path,digest in before.items()),'loaded source changed')
    helpers.validate_manifest_inputs(ctx['manifest'])
    for path,digest in ctx['pins'].items():require(helpers.sha(args.extension_root/path)==digest,'frozen extension changed')
    require(helpers.sha(args.plan)==ctx['manifest']['plan_sha256'],'sealed phase plan changed')
    summary.update(source_dependencies=after,workers=1,bridge_names=[],legal_ir_evaluate_provers=False,
        metric_disk_cache_used=False,paragraph_embedding_cache_used=True,encoder_executed=False,
        encoder_context_changed=False,output_limit_changed=False,downloads_performed=False)
    helpers.save(args.output/'summary.json',summary)


if __name__=='__main__':main()
