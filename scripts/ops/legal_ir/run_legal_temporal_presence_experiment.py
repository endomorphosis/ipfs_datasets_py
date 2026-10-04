#!/usr/bin/env python3
"""Matched temporal-presence continuation from two frozen facet-parent checkpoints.

Four400-update trials share exact parent weights, common retention objective and
stratified schedule; targeted training adds class-balanced temporal-presence CE.
Only admitted tuning determines selection; training accuracy is diagnostic.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from copy import deepcopy
import multiprocessing
from pathlib import Path
import sys
import json
import time

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from scripts.ops.legal_ir import run_legal_boundary_curriculum_experiment as boundary_run
from scripts.ops.legal_ir import run_legal_facet_retention_experiment as previous
from scripts.ops.legal_ir import run_legal_construction_retention_experiment as retention

require, read, read_ref, ref, sha, write, digest = (getattr(retention, key) for key in
    ('require', 'read', 'read_ref', 'ref', 'sha', 'write', 'digest'))
source_rows, generate, score, target_metadata = retention.source_rows, retention.generate, retention.score, retention.target_metadata
clauses, boundary = retention.clauses, retention.boundary
SCHEMA = 'legal-temporal-presence-experiment/v1'
CONFIG_SCHEMA = 'legal-temporal-presence-run-config/v1'
OBJECTIVES = ('base', 'temporal_presence')
ARCHITECTURES = ('continuation', 'grounding')
SEEDS = (1730,)
TUNING_PANELS = ('earlier', 'temporal', 'prior_consistency', 'prior_role', 'prior_facet', 'new')
DOCUMENT_TUNING_PANELS = ('document_tuning','prior_facet_document_tuning','new_document_tuning')
BOUNDARY_POLICIES = ('parent', 'expanded')
SINGLE_COUNTS = {'tuning_earlier':96,'tuning_temporal':120,'tuning_prior_consistency':96,'tuning_prior_role':96,
    'tuning_prior_facet':192,'tuning_new':96,'fresh':192,'prior_facet':192,'real_exposed':86}
DOCUMENT_COUNTS = {'document_tuning':96,'prior_facet_document_tuning':96,'new_document_tuning':96,
    'fresh_documents':96,'prior_facet_documents':96}
DOCUMENT_PREFIX = {'document_tuning':'document','prior_facet_document_tuning':'prior_facet_document',
    'new_document_tuning':'new_document'}
STAGES = (100,200,400)
FALSE = {key: value for key, value in retention.FALSE.items() if key != 'training_executed'}


def metric_keys():
    return {**{'tuning_' + key + '_exact': maximum for key, maximum in
        (('earlier',96),('temporal',120),('prior_consistency',96),('prior_role',96),('prior_facet',192),
         ('new',96),('new_Tpresent',48),('new_Tabsent',48))},
        **{'tuning_'+panel+'_'+policy+'_exact':72 for panel in DOCUMENT_PREFIX.values() for policy in BOUNDARY_POLICIES},
        **{'tuning_'+panel+'_'+policy+'_unsupported_accepted':24 for panel in DOCUMENT_PREFIX.values() for policy in BOUNDARY_POLICIES}}


def validate_tuning_counts(value):
    require(all(type(value[key]) is int and 0 <= value[key] <= maximum for key,maximum in metric_keys().items()),
        'complete bounded temporal clause and three-panel two-boundary document tuning metrics required')
    require(value['tuning_new_exact'] == value['tuning_new_Tpresent_exact'] + value['tuning_new_Tabsent_exact'],
        'temporal full-rule class exact counts must sum to total')


def eligible(stage, parent):
    validate_tuning_counts(stage); validate_tuning_counts(parent)
    retained = ('tuning_earlier_exact','tuning_temporal_exact','tuning_prior_consistency_exact',
        'tuning_document_parent_exact','tuning_document_expanded_exact',
        'tuning_prior_facet_document_parent_exact','tuning_prior_facet_document_expanded_exact')
    nonregression = ('tuning_prior_role_exact','tuning_prior_facet_exact','tuning_new_exact',
        'tuning_new_Tpresent_exact','tuning_new_Tabsent_exact','tuning_new_document_parent_exact','tuning_new_document_expanded_exact')
    return (all(stage[key] >= parent[key]-1 for key in retained)
        and all(stage[key] >= parent[key] for key in nonregression)
        and all(stage['tuning_'+panel+'_'+policy+'_unsupported_accepted'] == 0
            for panel in DOCUMENT_PREFIX.values() for policy in BOUNDARY_POLICIES))


def ranking(stage):
    return (stage['tuning_new_exact'],2*stage['tuning_prior_role_exact']+stage['tuning_prior_facet_exact'],
        stage['tuning_new_document_expanded_exact'],stage['tuning_new_document_parent_exact'],stage['tuning_temporal_exact'],
        stage['tuning_prior_facet_document_expanded_exact'],stage['tuning_prior_facet_document_parent_exact'],
        stage['tuning_document_expanded_exact'],stage['tuning_document_parent_exact'],stage['tuning_earlier_exact'],-stage['steps'])


def select_stage(stages, parent):
    require(type(stages) is list and len(stages) == 3 and {stage['steps'] for stage in stages} == set(STAGES)
        and all(type(stage['steps']) is int for stage in stages), 'all100/200/400 additional-update stages required')
    candidates = [stage for stage in stages if eligible(stage,parent)]
    return max(candidates,key=ranking) if candidates else None


def validate_pairs(rows, pairs, expected_count):
    by_id = {row['id']: row for row in rows}
    require(len(by_id) == len(rows) == expected_count * 2 and len(pairs) == expected_count
        and len({pair['pair_id'] for pair in pairs}) == expected_count, 'complete unique paraphrase pair inventory required')
    seen = set()
    for pair in pairs:
        require(set(pair) == {'pair_id','case_group','left_id','right_id','canonical_ir_sha256'}, 'closed paraphrase pair metadata required')
        identities = {pair['left_id'],pair['right_id']}
        require(len(identities) == 2 and identities <= set(by_id) and not seen & identities,
            'each new clause must occur in exactly one pair')
        left,right = by_id[pair['left_id']],by_id[pair['right_id']]
        require(left['canonical_ir'] == right['canonical_ir'] and digest(left['canonical_ir']) == pair['canonical_ir_sha256'],
            'paired clauses must have identical complete canonical meaning')
        require(left['source_text'] != right['source_text'] and left['domain'] == right['domain'] == 'new',
            'two distinct new-domain surfaces required per semantic pair')
        seen |= identities
    require(seen == set(by_id), 'pair inventory omitted new clauses')


def load_config(path):
    from scripts.ops.legal_ir import prepare_legal_temporal_presence_corpus as corpus
    config=read(path)
    require(type(config) is dict and set(config)=={'schema','corpus_manifest','prior_facet_experiment_config',
        'prior_facet_generation','experimental_parent_choice','study_design','producer_files'} and config['schema']==CONFIG_SCHEMA,
        'closed temporal presence configuration required')
    for key,value in config.items():
        if key not in {'schema','producer_files'}: read_ref(value,parse=False)
    for reference in config['producer_files']: read_ref(reference,parse=False)
    loaded=corpus.load_training_inputs(config['corpus_manifest']['path'])
    manifest=loaded['manifest'];old=previous.load_config(config['prior_facet_experiment_config']['path'])
    for key in corpus.SEALED: target_metadata(manifest['artifacts'][key])
    require(config['prior_facet_experiment_config']==manifest['inputs']['prior_config'],'corpus prior config binding differs')
    frozen=read_ref(config['prior_facet_generation']);prior_plan=read_ref(frozen['plan'])
    require(frozen['schema']==previous.SCHEMA and frozen['all_training_selection_and_generation_complete'] is True,
        'complete frozen facet study required')
    require(prior_plan['config']==config['prior_facet_experiment_config'],'prior generation/config differs')
    require(all(sha(file)==wanted for file,wanted in prior_plan['producer_pins'].items()),'prior producer drift')
    choice=read_ref(config['experimental_parent_choice'])
    require(choice['choice_frozen_before_fresh_reference_release'] is True and choice['fresh_results_used_for_choice'] is False,
        'exact two previously pretest chosen parents required')
    expected={'continuation':('base_continuation-1730','8be96c94218c7b28c973944fbe57b69b6d544a3c1358540a0860f34f896da9ca'),
        'grounding':('facet_retention_grounding-1730','1382a273a3c40e537d61f30767f221b5813e56ebd530d05190495a1d0ede1964')}
    parents={}
    for item in choice['choices']:
        architecture=item['architecture'];name,wanted=expected[architecture]
        require(item['name']==name and item['seed']==1730 and item['decoder_kind']=='facet_retention'
            and item['checkpoint']['sha256']==wanted and item['selected_steps']==800,'frozen selected facet parent identity differs')
        require(any(m['name']==name and m['checkpoint']==item['checkpoint'] for m in frozen['models']),
            'chosen parent omitted from prior frozen generation')
        require((architecture,1730) not in parents,'duplicate chosen parent')
        read_ref(item['checkpoint'],parse=False);parents[(architecture,1730)]=item
    require(set(parents)=={(a,1730) for a in ARCHITECTURES},'both exact chosen architecture parents required')
    require({name:len(rows) for name,rows in loaded['replay'].items()}==
        {'earlier':1152,'prior_new':600,'temporal':600,'prior_consistency':384,'prior_role':384,'prior_facet':768},
        'all3888 historical rows must remain in the fitting inventory')
    training=[row for name in ('earlier','prior_new','temporal','prior_consistency','prior_role','prior_facet')
        for row in loaded['replay'][name]]+loaded['new_train']
    tuning={**loaded['tuning'],'new':loaded['new_tuning']}
    validate_pairs(loaded['new_train'],loaded['training_pairs'],96)
    validate_pairs(loaded['new_tuning'],loaded['tuning_pairs'],48)
    for rows in (loaded['new_train'],loaded['new_tuning']):
        require(sum(bool(r['canonical_ir']['rules'][0]['temporal']) for r in rows)*2 == len(rows),
            'equal temporal present and absent authored rows required')
    sources={'tuning_'+name:source_rows(tuning[name]) for name in TUNING_PANELS}
    sources.update(fresh=source_rows(loaded['fresh_sources']),prior_facet=old['sources']['fresh'],real_exposed=old['sources']['real_exposed'])
    require({name:len(rows) for name,rows in sources.items()}==SINGLE_COUNTS,'complete bounded source-only panels required')
    documents={'document_tuning':old['document_sources']['document_tuning'],
        'prior_facet_document_tuning':old['document_sources']['new_document_tuning'],
        'new_document_tuning':clauses.source_rows(loaded['document_tuning']),
        'fresh_documents':clauses.source_rows(loaded['fresh_document_sources']),
        'prior_facet_documents':old['document_sources']['fresh_documents']}
    require({name:len(rows) for name,rows in documents.items()}==DOCUMENT_COUNTS,'complete document panels required')
    fit_hashes={row['source_sha256'] for row in source_rows(training)}
    require(len(fit_hashes)==len(training)==4080,'complete distinct fitting sources required')
    other_hashes={row['source_sha256'] for rows in sources.values() for row in rows}
    require(not fit_hashes & other_hashes,'fitting source overlaps tuning/challenge/regression/real views')
    return {'config':config,'manifest':manifest,'training':training,'runtime_pairs':[
        [p['left_id'],p['right_id']] for p in loaded['training_pairs']], 'tuning':tuning,'sources':sources,
        'training_sources':source_rows(loaded['new_train']),
        'replay':loaded['replay'],'new_train':loaded['new_train'],'training_pairs':loaded['training_pairs'],
        'tuning_pairs':loaded['tuning_pairs'],'document_sources':documents,'document_tuning':old['document_tuning'],
        'prior_facet_document_tuning':old['new_document_tuning'],'new_document_tuning':loaded['document_tuning'],
        'parents':parents,'boundary_heads':{k:v for k,v in old['boundary_heads'].items() if k in ('parent','expanded-1730')},
        'real_source_manifest':old['real_source_manifest']}


def load_decoder(checkpoint,decoder_kind):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_facet_retention as parent
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_temporal_presence as child
    require(decoder_kind in ('facet_retention','temporal_presence'),'known temporal presence decoder kind required')
    module,cls=(parent,parent.FacetRetentionDecoder) if decoder_kind=='facet_retention' else (child,child.TemporalPresenceDecoder)
    return cls(module.load_checkpoint(checkpoint['path'],expected_sha256=checkpoint['sha256']))


def evaluate_tuning(decoder,job,folder,stem):
    result = {}
    for panel in TUNING_PANELS:
        generation = generate(decoder,job['sources']['tuning_'+panel])
        metric = score(generation['rows'],job['sources']['tuning_'+panel],job['tuning'][panel])
        class_metrics={}
        if panel=='new':
            for present,label in ((True,'Tpresent'),(False,'Tabsent')):
                targets=[r for r in job['tuning'][panel] if bool(r['canonical_ir']['rules'][0]['temporal']) is present]
                ids={r['id'] for r in targets}
                sources=[r for r in job['sources']['tuning_'+panel] if r['id'] in ids]
                predictions=[r for r,s in zip(generation['rows'],job['sources']['tuning_'+panel]) if s['id'] in ids]
                require(len(targets)==len(sources)==len(predictions)==48,'both48-row temporal class slices required')
                class_metrics[label]=score(predictions,sources,targets)
                result['tuning_new_'+label+'_exact']=class_metrics[label]['exact']
        result['tuning_'+panel] = write(folder/f'{stem}-tuning-{panel}.json',{'generation':generation,'metrics':metric,
            'temporal_class_metrics':class_metrics})
        result['tuning_'+panel+'_exact'] = metric['exact']
    for panel in DOCUMENT_TUNING_PANELS:
        prefix = DOCUMENT_PREFIX[panel]
        for policy in BOUNDARY_POLICIES:
            generation = retention.generate_documents(decoder,job['boundaries'][policy][panel],job['document_sources'][panel])
            metric = retention.score_document_tuning(generation,job[panel])
            result[panel+'_'+policy] = write(folder/f'{stem}-{panel}-{policy}.json',{'generation':generation,'metrics':metric})
            result['tuning_'+prefix+'_'+policy+'_exact'] = metric['exact']
            result['tuning_'+prefix+'_'+policy+'_unsupported_accepted'] = metric['unsupported_accepted']
    generation=generate(decoder,job['training_sources'])
    metric=score(generation['rows'],job['training_sources'],job['new_train'])
    result['training_new']=write(folder/f'{stem}-training-new.json',{'generation':generation,'metrics':metric,
        'diagnostic_only':True,'checkpoint_selection_uses_this_metric':False})
    result['training_new_exact']=metric['exact']
    return result


def document_signature(generation):
    result = deepcopy(generation['rows'])
    for row in result:
        if row['clause_generation'] is not None: row['clause_generation'] = {'rows':row['clause_generation']['rows']}
    return result


def initialization_equal(parent_metrics,initial_metrics):
    for key in [*('tuning_'+panel for panel in TUNING_PANELS),'training_new']:
        original,current = read_ref(parent_metrics[key]),read_ref(initial_metrics[key])
        require(original['generation']['rows'] == current['generation']['rows'] and original['metrics'] == current['metrics'],
            'initial single predictions, logits, or tuning/training scores differ from parent')
    for panel in DOCUMENT_TUNING_PANELS:
        for policy in BOUNDARY_POLICIES:
            key=panel+'_'+policy
            original,current=read_ref(parent_metrics[key]),read_ref(initial_metrics[key])
            require(document_signature(original['generation'])==document_signature(current['generation']) and
                original['metrics']==current['metrics'],'initial document predictions or tuning scores differ from parent')
    return True


def model_inventory(trials,parents):
    expected = {(objective,architecture,seed) for objective in OBJECTIVES for architecture in ARCHITECTURES for seed in SEEDS}
    require(len(trials) == 4 and {(r['objective'],r['architecture'],r['seed']) for r in trials} == expected,
        'all four fixed-budget fitting trials required')
    for trial in trials:
        architecture,seed,objective = trial['architecture'],trial['seed'],trial['objective']
        require(trial['name'] == f'{objective}_{architecture}-{seed}' and trial['arm'] == f'{objective}_{architecture}'
            and trial['enabled'] is (architecture == 'grounding') and trial['parent'] == parents[(architecture,seed)]['checkpoint']
            and trial['executed_steps'] == 400, 'trial identity, architecture, or inherited parent attribution differs')
        if trial['selection'] == 'candidate':
            require(trial['decoder_kind'] == 'temporal_presence' and trial['selected_steps'] in STAGES, 'trained candidate attribution differs')
        else:
            require(trial['selection'] == 'parent_fallback_no_acceptable_replacement' and trial['decoder_kind'] == 'facet_retention'
                and trial['selected_steps'] == 0 and trial['checkpoint'] == trial['parent'], 'fallback must retain its exact architecture parent')
    models = list(trials)
    for architecture in ARCHITECTURES:
        for seed in SEEDS:
            parent = parents[(architecture,seed)]
            models.append({'name':f'parent_{architecture}-{seed}','arm':f'parent_{architecture}',
                'architecture':architecture,'objective':'parent','seed':seed,'enabled':architecture == 'grounding',
                'decoder_kind':'facet_retention','checkpoint':parent['checkpoint'],'parent':parent['checkpoint'],
                'selection':'unchanged_parent','selected_steps':0,'executed_steps':0})
    models.sort(key=lambda row:row['name'])
    pipelines = []
    for model in models:
        for policy in BOUNDARY_POLICIES:
            pipelines.append({'name':model['name']+'__'+policy,'source_model_name':model['name'],
                'arm':model['arm']+'__'+policy,'architecture':model['architecture'],'objective':model['objective'],
                'seed':model['seed'],'checkpoint':model['checkpoint'],'decoder_kind':model['decoder_kind'],
                'enabled':model['enabled'],'boundary_policy':policy,
                'boundary_head':'parent' if policy == 'parent' else f"expanded-{model['seed']}",
                'selection':model['selection'],'selected_steps':model['selected_steps']})
    return models,pipelines


def generation_job(job):
    import torch
    torch.set_num_threads(1)
    item=job['item'];decoder=load_decoder(item['checkpoint'],item['decoder_kind'])
    folder=Path(job['folder']);folder.mkdir(exist_ok=True)
    singles={panel:write(folder/f'{panel}-generation.json',generate(decoder,rows)) for panel,rows in job['sources'].items()}
    documents={}
    for policy in BOUNDARY_POLICIES:
        name=item['name']+'__'+policy
        documents[name]={panel:write(folder/f'{policy}-{panel}-generation.json',
            retention.generate_documents(decoder,job['boundaries'][policy][panel],rows))
            for panel,rows in job['document_sources'].items()}
    print(json.dumps({'phase':'generated','model':item['name'],'selection':item['selection']}),flush=True)
    return item['name'],singles,documents


def fit_job(job):
    trial_started=time.monotonic()
    import torch
    torch.set_num_threads(1)
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_mixed_replay as mixed
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_temporal_presence as runtime
    folder=Path(job['folder']);folder.mkdir()
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_facet_retention as parent_runtime
    parent=parent_runtime.load_checkpoint(job['parent']['path'],expected_sha256=job['parent']['sha256'])
    require(parent['model_config']['seed'] == job['seed'] and parent['model_config']['trigger_enabled'] is job['enabled'],
        'same-seed architecture parent required')
    tuning=[row for panel in TUNING_PANELS for row in job['tuning'][panel]]
    checkpoint=runtime.build_checkpoint(parent,job['training'],tuning,job['runtime_pairs'],
        objective=job['objective'],seed=job['seed'],learning_rate=.0005,batch_size=12)
    require(checkpoint['model_state'] == parent['model_state'] and runtime.optimizer_steps(checkpoint) == 0,
        'exact pretrained tensors and reset optimizer progress required')
    initial_ref=runtime.save_checkpoint(checkpoint,folder/'initial-checkpoint.json')
    initial_metrics=evaluate_tuning(runtime.TemporalPresenceDecoder(checkpoint),job,folder,'initial')
    require(initialization_equal(job['parent_metrics'],initial_metrics), 'initial predictions differ from parent')
    initialization=write(folder/'initialization.json',{'parent':job['parent'],'initial':initial_ref,
        'initial_model_state_sha256':digest(checkpoint['model_state']),'parent_model_state_sha256':digest(parent['model_state']),
        'tuning':initial_metrics,'parent_tuning':job['parent_metrics'],'all_initial_tensors_equal':True,
        'all_tuning_numerical_predictions_equal':True,'optimizer_reset':True,'historical_optimizer_resumed':False})
    stages=[]
    for target_steps in STAGES:
        before=digest(checkpoint)
        result=runtime.train_decoder(checkpoint,job['training'],tuning,job['runtime_pairs'],max_steps=target_steps-runtime.optimizer_steps(checkpoint),
            max_seconds=max(0.,600-(time.monotonic()-trial_started)))
        checkpoint=result['checkpoint'];steps=runtime.optimizer_steps(checkpoint)
        require(steps == target_steps, 'complete400-update matched budget required; partial runs cannot qualify')
        stage={'steps':steps,'checkpoint':runtime.save_checkpoint(checkpoint,folder/f'checkpoint-{steps}.json'),
            'previous_checkpoint_sha256':before,'training_report':write(folder/f'training-{steps}.json',result['report']),
            **evaluate_tuning(runtime.TemporalPresenceDecoder(checkpoint),job,folder,f'stage-{steps}')}
        stage['eligible']=eligible(stage,job['parent_metrics']);stages.append(stage)
        require(time.monotonic()-trial_started <= 600,'full trial wall-clock budget exceeded')
        print(json.dumps({'phase':'trained_stage','objective':job['objective'],'architecture':job['architecture'],
            'seed':job['seed'],'steps':steps,'eligible':stage['eligible'],
            'training_new_exact':stage['training_new_exact'],'training_new_count':192,
            **{key:stage[key] for key in metric_keys()}}),flush=True)
    chosen=select_stage(stages,job['parent_metrics'])
    result={'name':f"{job['objective']}_{job['architecture']}-{job['seed']}",
        'arm':f"{job['objective']}_{job['architecture']}",'objective':job['objective'],
        'architecture':job['architecture'],'seed':job['seed'],'enabled':job['enabled'],
        'decoder_kind':'temporal_presence' if chosen else 'facet_retention',
        'checkpoint':chosen['checkpoint'] if chosen else job['parent'],
        'selection':'candidate' if chosen else 'parent_fallback_no_acceptable_replacement',
        'selected_steps':chosen['steps'] if chosen else 0,'executed_steps':400,'parent':job['parent'],
        'parent_tuning':job['parent_metrics'],'initialization':initialization,'initial_checkpoint':initial_ref,
        'initial_model_state_sha256':digest(parent['model_state']),'stages':stages,
        'trial_wall_seconds':time.monotonic()-trial_started,'trial_wall_limit_seconds':600,
        'historical_optimizer_resumed':False,
        'fresh_targets_opened':False,'regression_targets_opened':False,**FALSE}
    selection_ref=write(folder/'selection.json',result)
    return {**result,'selection_record':selection_ref}


def audit_trials(trials):
    require(len(trials)==4,'four complete training trials required')
    audit=[]
    for trial in trials:
        exposures=[row for stage in trial['stages'] for row in read_ref(stage['training_report'])['batch_exposures']]
        require(len(exposures)==400 and [r['optimizer_step'] for r in exposures]==list(range(1,401)),
            'all400 ordered update receipts required')
        counts=read_ref(trial['initial_checkpoint'])['pool_counts']
        coverage={pool:{'pool_entries':count,'draws':sum(len(e['indices_by_pool'][pool]) for e in exposures),
            'unique_entries_seen':len({i for e in exposures for i in e['indices_by_pool'][pool]})} for pool,count in counts.items()}
        audit.append({'objective':trial['objective'],'architecture':trial['architecture'],'seed':trial['seed'],'parent':trial['parent'],
            'batch_count':400,'batch_exposures_sha256':digest(exposures),'actual_pool_coverage':coverage,'same_architecture_no_update_control':True,
            'same_batch_order_as_other_objective':True})
    for architecture in ARCHITECTURES:
        for seed in SEEDS:
            pair=[row for row in audit if row['architecture']==architecture and row['seed']==seed]
            require(len(pair)==2 and {r['objective'] for r in pair}==set(OBJECTIVES)
                and pair[0]['batch_exposures_sha256']==pair[1]['batch_exposures_sha256']
                and pair[0]['parent']==pair[1]['parent'],'matched objectives must have identical parent and minibatch order')
    return audit


def run(args):
    import torch
    torch.set_num_threads(1)
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_temporal_presence as runtime
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_mixed_replay as mixed
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_dimensions as dimensions
    from scripts.ops.legal_ir import prepare_legal_temporal_presence_corpus as corpus
    require(type(args.workers) is int and 1 <= args.workers <= 3, 'one to three CPU workers required')
    inputs=load_config(args.config)
    output=Path(args.output).resolve();output.mkdir(parents=True,exist_ok=False)
    pins={str(Path(module.__file__).resolve()):sha(module.__file__) for module in
        (runtime,mixed,dimensions,boundary,clauses,clauses.compose,retention,boundary_run,corpus,sys.modules[__name__])}
    plan_ref=write(output/'plan.json',{'schema':SCHEMA,'config':ref(args.config),'producer_pins':pins,
        'objectives':list(OBJECTIVES),'architectures':list(ARCHITECTURES),'seeds':list(SEEDS),
        'additional_stage_steps':list(STAGES),'additional_updates_per_trial':400,'total_optimizer_updates':1600,
        'optimizer':'Adam','learning_rate':.0005,'optimizer_reset':True,'historical_optimizer_resumed':False,
        'batch_size':12,'batch_quota':{'earlier':3,'historical_new':3,'new_pairs':3,'new_pair_rows':6,
            'even_step_positive_pairs':2,'even_step_negative_pairs':1,'odd_step_positive_pairs':1,'odd_step_negative_pairs':2},
        'consistency_weight':.25,'teacher_weight':.5,'overlap_weight':.1,'temporal_presence_weight':.5,'control_uses_common_retention_objective':True,'matched_objective_pair_batches':True,'fixed_sampler_and_same_architecture_parent_control':True,
        'inference_changed':False,'joint_search_enabled':False,'threads_per_worker':1,'workers':args.workers,
        'trial_wall_limit_seconds':600,'trial_deadline_scope':'fit initialization, stage updates and tuning; incomplete or late trials hard-fail',
        'single_counts':SINGLE_COUNTS,'document_counts':DOCUMENT_COUNTS,'boundary_heads':inputs['boundary_heads'],
        'retention_tolerance':1,'unsupported_acceptance_tolerance':0,
        'training_diagnostic_count':192,'training_diagnostics_used_for_selection':False,
        'selection':'seven earlier/task/document metrics >=same parent minus1; role,facet,new temporal total and both48-row presence classes plus both new document joint exact>=parent; zero guards all three document panels and both heads; rank new exact,2role+facet,new-expanded-doc,new-parent-doc,old-temporal,facet-expanded-doc,facet-parent-doc,old-expanded-doc,old-parent-doc,earlier,earliest; otherwise unchanged parent',
        'fresh_targets_opened':False,'regression_targets_opened':False,**FALSE})
    source_ref=write(output/'source-inputs.json',inputs['sources'])
    document_source_ref=write(output/'document-source-inputs.json',inputs['document_sources'])
    boundaries,boundary_refs={},{}
    for name,head in inputs['boundary_heads'].items():
        decoder=boundary.ClauseBoundaryDecoder(read_ref(head['checkpoint']))
        boundaries[name]={panel:clauses.decode_all(decoder,rows) for panel,rows in inputs['document_sources'].items()}
        boundary_refs[name]={panel:write(output/f'{name}-{panel}-boundaries.json',value) for panel,value in boundaries[name].items()}
    def seed_boundaries(seed): return {'parent':boundaries['parent'],'expanded':boundaries[f'expanded-{seed}']}
    parent_metrics={}
    for architecture in ARCHITECTURES:
        for seed in SEEDS:
            item=inputs['parents'][(architecture,seed)]
            job={**inputs,'boundaries':seed_boundaries(seed)}
            parent_metrics[(architecture,seed)]=evaluate_tuning(load_decoder(item['checkpoint'],'facet_retention'),job,output,f'parent-{architecture}-{seed}')
    parent_ref=write(output/'parent-tuning.json',{f'parent_{architecture}-{seed}':metrics for (architecture,seed),metrics in parent_metrics.items()})
    jobs=[{'objective':objective,'architecture':architecture,'seed':seed,'enabled':architecture == 'grounding',
        'parent':inputs['parents'][(architecture,seed)]['checkpoint'],'parent_metrics':parent_metrics[(architecture,seed)],
        'training':inputs['training'],'runtime_pairs':inputs['runtime_pairs'],'tuning':inputs['tuning'],
        'sources':{key:inputs['sources'][key] for key in tuple('tuning_'+p for p in TUNING_PANELS)},
        **{p:inputs[p] for p in DOCUMENT_TUNING_PANELS},
        'document_sources':{panel:inputs['document_sources'][panel] for panel in DOCUMENT_TUNING_PANELS},
        'new_train':inputs['new_train'],'training_sources':inputs['training_sources'],
        'boundaries':{policy:{panel:panels[panel] for panel in DOCUMENT_TUNING_PANELS} for policy,panels in seed_boundaries(seed).items()},
        'folder':str(output/f'{objective}_{architecture}-{seed}')} for objective in OBJECTIVES for architecture in ARCHITECTURES for seed in SEEDS]
    trials=[]
    with ProcessPoolExecutor(max_workers=args.workers,mp_context=multiprocessing.get_context('spawn')) as pool:
        for future in as_completed([pool.submit(fit_job,job) for job in jobs]): trials.append(future.result())
    trials.sort(key=lambda row:row['name'])
    matching=audit_trials(trials)
    selections_ref=write(output/'selections-frozen.json',{'trials':trials,'parent_tuning':parent_ref,'trial_update_audit':matching,
        'executed_optimizer_updates':1600,'fresh_targets_opened':False,'regression_targets_opened':False,**FALSE})
    models,pipelines=model_inventory(trials,inputs['parents'])
    for pipeline in pipelines: pipeline['boundary_checkpoint']=inputs['boundary_heads'][pipeline['boundary_head']]['checkpoint']
    models_ref=write(output/'models-frozen.json',models);pipelines_ref=write(output/'pipelines-frozen.json',pipelines)
    jobs=[{'item':item,'sources':inputs['sources'],'document_sources':inputs['document_sources'],
        'boundaries':seed_boundaries(item['seed']),'folder':str(output/item['name'])} for item in models]
    files,document_files={},{}
    with ProcessPoolExecutor(max_workers=args.workers,mp_context=multiprocessing.get_context('spawn')) as pool:
        for future in as_completed([pool.submit(generation_job,job) for job in jobs]):
            name,singles,documents=future.result();files[name]=singles;document_files.update(documents)
    require(all(sha(file) == wanted for file,wanted in pins.items()), 'temporal presence fitting/generation producer drift')
    require(load_config(args.config) == inputs, 'temporal presence fitting/source inputs changed during execution')
    result={'schema':SCHEMA,'plan':plan_ref,'sources':source_ref,'document_sources':document_source_ref,
        'boundaries':boundary_refs,'selections':selections_ref,'heads':models_ref,'models':models,
        'pipeline_heads':pipelines_ref,'pipelines':pipelines,'files':files,'document_files':document_files,
        'all_training_selection_and_generation_complete':True,'fresh_targets_opened':False,'regression_targets_opened':False,
        'executed_optimizer_updates':1600,'boundary_optimizer_updates':0,'training_executed':True,
        'parent_fallbacks':[row['name'] for row in trials if row['selection'] != 'candidate'],**FALSE}
    write(output/'generation-frozen.json',result)
    print(json.dumps({'phase':'frozen','models':6,'pipelines':12,'optimizer_updates':1600,'fallbacks':result['parent_fallbacks']}),flush=True)
    return result


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',required=True);parser.add_argument('--output',required=True)
    parser.add_argument('--workers',type=int,default=3)
    return run(parser.parse_args(argv))


if __name__ == '__main__': main()
