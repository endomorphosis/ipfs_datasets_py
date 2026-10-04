#!/usr/bin/env python3
"""Matched TRAIN-only condition rehearsal; independent boundary composition later.

Clause stages are selected using declared retention references and fixed old
boundary heads. A separate compose phase crosses selected clause checkpoints
with independently selected scope heads, without any joint stage search.
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
from scripts.ops.legal_ir import run_legal_temporal_presence_experiment as previous
from scripts.ops.legal_ir import run_legal_construction_retention_experiment as retention

require, read, read_ref, ref, sha, write, digest = (getattr(retention, key) for key in
    ('require', 'read', 'read_ref', 'ref', 'sha', 'write', 'digest'))
source_rows, generate, score, target_metadata = retention.source_rows, retention.generate, retention.score, retention.target_metadata
clauses, boundary = retention.clauses, retention.boundary
SCHEMA = 'legal-condition-rehearsal-experiment/v1'
CONFIG_SCHEMA = 'legal-condition-rehearsal-run-config/v1'
OBJECTIVES = ('base', 'condition_rehearsal')
ARCHITECTURES = ('continuation', 'grounding')
SEEDS = (1730,)
TUNING_PANELS = (*previous.TUNING_PANELS,'condition')
BOUNDARY_POLICIES = ('parent','expanded')
DOCUMENT_TUNING_PANELS = (*previous.DOCUMENT_TUNING_PANELS,'condition_document_tuning',
    'retention_facet_documents','retention_temporal_documents')
DOCUMENT_PREFIX = {**previous.DOCUMENT_PREFIX,'condition_document_tuning':'condition_document',
    'retention_facet_documents':'retention_facet_document','retention_temporal_documents':'retention_temporal_document'}
RETENTION_PANELS = ('facet','temporal')
SINGLE_COUNTS = {**{k:v for k,v in previous.SINGLE_COUNTS.items() if k.startswith('tuning_')},
    'tuning_condition':96,'retention_facet':192,'retention_temporal':192,'fresh':192,'real_exposed':86}
DOCUMENT_COUNTS = {p:96 for p in (*DOCUMENT_TUNING_PANELS,'fresh_documents')}
FINAL_DOCUMENT_COUNTS = {p:96 for p in ('fresh_documents','retention_facet_documents','retention_temporal_documents')}
STAGES = (100,200)
FALSE = {key:value for key,value in retention.FALSE.items() if key!='training_executed'}


def metric_keys():
    return {**previous.metric_keys(),'tuning_condition_exact':96,
        **{'tuning_'+prefix+'_'+policy+'_'+suffix:maximum for panel,prefix in DOCUMENT_PREFIX.items()
            if panel not in previous.DOCUMENT_TUNING_PANELS for policy in BOUNDARY_POLICIES
            for suffix,maximum in (('exact',72),('unsupported_accepted',24))}}


def scoped_metrics(rows,sources,targets):
    require(len(rows)==len(sources)==len(targets),'complete scope metric rows required')
    by_id={r['id']:r for r in targets};require(len(by_id)==len(targets),'unique scope target IDs required')
    result={'count':len(rows),'fullrule_exact':0,
        'modality_fullrule':{m:{'count':0,'exact':0} for m in 'OPF'},
        **{kind:{label:{'count':0,'exact':0} for label in ('present','absent')}
            for kind in ('condition_facet','temporal_facet','condition_fullrule','temporal_fullrule')}}
    for prediction,source in zip(rows,sources,strict=True):
        wanted=by_id[source['id']]['canonical_ir'];truth=wanted['rules'][0]
        decoded=prediction['status']=='decoded' and prediction['canonical_ir'] is not None
        actual=prediction['canonical_ir']['rules'][0] if decoded else None
        exact=decoded and prediction['canonical_ir']==wanted
        result['fullrule_exact']+=exact;cell=result['modality_fullrule'][truth['modality']];cell['count']+=1;cell['exact']+=exact
        for prefix,field in (('condition','conditions'),('temporal','temporal')):
            label='present' if truth[field] else 'absent'
            for kind,correct in (('facet',decoded and actual[field]==truth[field]),('fullrule',exact)):
                cell=result[prefix+'_'+kind][label];cell['count']+=1;cell['exact']+=correct
    return result


def validate_scoped(value,count):
    require(set(value)=={'count','fullrule_exact','modality_fullrule','condition_facet','temporal_facet','condition_fullrule','temporal_fullrule'}
        and value['count']==count and type(value['fullrule_exact']) is int and 0<=value['fullrule_exact']<=count,'closed bounded scope metric required')
    for kind in ('modality_fullrule','condition_facet','temporal_facet','condition_fullrule','temporal_fullrule'):
        labels='OPF' if kind=='modality_fullrule' else ('present','absent')
        require(set(value[kind])==set(labels),'scope class inventory differs')
        for label in labels:
            cell=value[kind][label];maximum=count//len(labels)
            require(set(cell)=={'count','exact'} and cell['count']==maximum and type(cell['exact']) is int and 0<=cell['exact']<=maximum,
                'class denominator or bounded exact count differs')
        if kind.endswith('fullrule'):require(sum(c['exact'] for c in value[kind].values())==value['fullrule_exact'],'fullrule class counts do not sum')


def validate_tuning_counts(value):
    previous.validate_tuning_counts(value)
    require(all(type(value[k]) is int and 0<=value[k]<=n for k,n in metric_keys().items()),'complete clause/document tuning counts required')
    require(set(value['retention_metrics'])==set(RETENTION_PANELS),'both exposed retention panels required')
    for panel in RETENTION_PANELS:validate_scoped(value['retention_metrics'][panel],192)
    validate_scoped(value['condition_metrics'],96)
    require(value['tuning_condition_exact']==value['condition_metrics']['fullrule_exact'],'condition tuning exact totals differ')


def eligible(stage,parent):
    validate_tuning_counts(stage);validate_tuning_counts(parent)
    if not previous.eligible(stage,parent):return False
    for panel in RETENTION_PANELS:
        current,baseline=stage['retention_metrics'][panel],parent['retention_metrics'][panel]
        if current['fullrule_exact']<baseline['fullrule_exact']:return False
        for kind in ('modality_fullrule','condition_facet','temporal_facet'):
            if any(current[kind][label]['exact']<baseline[kind][label]['exact'] for label in current[kind]):return False
    current,baseline=stage['condition_metrics'],parent['condition_metrics']
    if current['fullrule_exact']<baseline['fullrule_exact']:return False
    for kind in ('condition_fullrule','temporal_fullrule'):
        if any(current[kind][label]['exact']<baseline[kind][label]['exact'] for label in current[kind]):return False
    for policy in BOUNDARY_POLICIES:
        if (stage['tuning_condition_document_'+policy+'_exact']<parent['tuning_condition_document_'+policy+'_exact']
            or stage['tuning_condition_document_'+policy+'_unsupported_accepted']!=0):return False
        for panel in RETENTION_PANELS:
            prefix='tuning_retention_'+panel+'_document_'+policy
            if stage[prefix+'_exact']<parent[prefix+'_exact'] or stage[prefix+'_unsupported_accepted']>parent[prefix+'_unsupported_accepted']:return False
    return True


def ranking(stage):
    return (stage['tuning_condition_exact'],sum(stage['retention_metrics'][p]['condition_facet']['present']['exact'] for p in RETENTION_PANELS),
        sum(stage['retention_metrics'][p]['fullrule_exact'] for p in RETENTION_PANELS),*previous.ranking(stage)[:-1],-stage['steps'])


def select_stage(stages,parent):
    require(type(stages) is list and len(stages)==2 and {r['steps'] for r in stages}==set(STAGES)
        and all(type(r['steps']) is int for r in stages),'both100/200 clause stages required')
    candidates=[s for s in stages if eligible(s,parent)]
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
    from scripts.ops.legal_ir import prepare_legal_condition_rehearsal_corpus as corpus
    config=read(path)
    require(type(config) is dict and set(config)=={'schema','prior_temporal_experiment_config','prior_temporal_generation',
        'experimental_parent_choice','condition_corpus_manifest','hard_mining_manifest','study_design','producer_files'} and config['schema']==CONFIG_SCHEMA,
        'closed condition rehearsal configuration required')
    for key,value in config.items():
        if key not in ('schema','producer_files'):read_ref(value,parse=False)
    for pin in config['producer_files']:read_ref(pin,parse=False)
    old=previous.load_config(config['prior_temporal_experiment_config']['path'])
    loaded=corpus.load_training_inputs(config['condition_corpus_manifest']['path']);manifest=loaded['manifest']
    require(manifest['inputs']['prior_config']==config['prior_temporal_experiment_config'],'condition corpus priorconfig differs')
    for key in corpus.SEALED:target_metadata(manifest['artifacts'][key])
    frozen=read_ref(config['prior_temporal_generation']);require(frozen['schema']==previous.SCHEMA and frozen['all_training_selection_and_generation_complete'],
        'complete prior temporal generation required')
    plan=read_ref(frozen['plan']);require(plan['config']==config['prior_temporal_experiment_config'],'prior config/generation differs')
    require(all(sha(p)==h for p,h in plan['producer_pins'].items()),'prior producer drift')
    choice=read_ref(config['experimental_parent_choice']);require(choice['choice_frozen_before_fresh_reference_release'] is True
        and choice['fresh_results_used_for_choice'] is False,'exact pretest parent choices required')
    expected={'continuation':('parent_continuation-1730','facet_retention','8be96c94218c7b28c973944fbe57b69b6d544a3c1358540a0860f34f896da9ca'),
        'grounding':('base_grounding-1730','temporal_presence','4ef3dc047cc86fbfa5fa53b1e546e5b1ecbc7d38faab0f6045292302dc892cea')}
    parents={}
    for item in choice['choices']:
        architecture=item['architecture'];name,kind,wanted=expected[architecture]
        require(item['name']==name and item['decoder_kind']==kind and item['seed']==1730 and item['checkpoint']['sha256']==wanted
            and any(m['name']==name and m['checkpoint']==item['checkpoint'] for m in frozen['models']),'current pretest chosen parent differs')
        require((architecture,1730) not in parents,'duplicate parent');parents[(architecture,1730)]=item
    require(set(parents)=={(a,1730) for a in ARCHITECTURES},'both architecture parents required')
    mining=read_ref(config['hard_mining_manifest'])
    require(mining['prior_config']==config['prior_temporal_experiment_config'] and mining['parent_choice']==config['experimental_parent_choice']
        and mining['training_manifest_sha256']==digest(old['training']) and mining['training_rows']==4080
        and mining['fitting_started'] is False and mining['new_tuning_or_fresh_labels_used'] is False,'frozen TRAIN mining provenance differs')
    require(sha(mining['runtime']['path'])==mining['runtime']['sha256'],'mining runtime drift')
    hard={}
    for (architecture,seed),parent in parents.items():
        entry=mining['models'][architecture+'-'+str(seed)]
        require(entry['parent']==parent['checkpoint'] and entry['parent_kind']==parent['decoder_kind'],'mining parent differs')
        hard[(architecture,seed)]=read_ref(entry['mining'])
    prior_manifest=read_ref(old['config']['corpus_manifest'])
    facet_config=read_ref(old['config']['prior_facet_experiment_config']);facet_manifest=read_ref(facet_config['corpus_manifest'])
    exposed={'facet':read_ref(facet_manifest['artifacts']['challenge_targets']),
        'temporal':read_ref(prior_manifest['artifacts']['challenge_targets'])}
    exposed_documents={'retention_facet_documents':read_ref(facet_manifest['artifacts']['document_challenge_targets']),
        'retention_temporal_documents':read_ref(prior_manifest['artifacts']['document_challenge_targets'])}
    tuning={**old['tuning'],'condition':loaded['new_tuning']}
    sources={**{'tuning_'+p:source_rows(tuning[p]) for p in TUNING_PANELS},
        **{'retention_'+p:source_rows(exposed[p]) for p in RETENTION_PANELS},
        'fresh':source_rows(loaded['fresh_sources']),'real_exposed':old['sources']['real_exposed']}
    document_targets={p:old[p] for p in previous.DOCUMENT_TUNING_PANELS}
    document_targets.update(condition_document_tuning=loaded['document_tuning'],**exposed_documents)
    documents={p:clauses.source_rows(rows) for p,rows in document_targets.items()}
    documents['fresh_documents']=clauses.source_rows(loaded['fresh_document_sources'])
    require({k:len(v) for k,v in sources.items()}==SINGLE_COUNTS and {k:len(v) for k,v in documents.items()}==DOCUMENT_COUNTS,'complete declared panel inventories required')
    training=old['training'];fit_hashes={r['source_sha256'] for r in source_rows(training)}
    require(len(training)==len(fit_hashes)==4080 and not fit_hashes & {r['source_sha256'] for rows in sources.values() for r in rows},'fitting rows omitted/duplicated or leak into evaluation')
    return {'config':config,'manifest':manifest,'training':training,'runtime_pairs':old['runtime_pairs'],
        'training_pairs':old['training_pairs'],'replay':old['replay'],'new_train':old['new_train'],
        'training_sources':old['training_sources'],'tuning':tuning,'sources':sources,'retention_targets':exposed,
        'condition_tuning_pairs':loaded['tuning_pairs'],'tuning_pairs':old['tuning_pairs'],
        'document_sources':documents,**document_targets,'parents':parents,'hard_mining':hard,
        'boundary_heads':old['boundary_heads'],'real_source_manifest':old['real_source_manifest']}


def load_decoder(checkpoint,decoder_kind):
    if decoder_kind in ('facet_retention','temporal_presence'):return previous.load_decoder(checkpoint,decoder_kind)
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_scope_retention as runtime
    require(decoder_kind=='scope_retention','known clause decoder kind required')
    return runtime.ScopeRetentionDecoder(runtime.load_checkpoint(checkpoint['path'],expected_sha256=checkpoint['sha256']))


def evaluate_tuning(decoder,job,folder,stem):
    result={}
    for panel in TUNING_PANELS:
        generation=generate(decoder,job['sources']['tuning_'+panel]);sources=job['sources']['tuning_'+panel];targets=job['tuning'][panel]
        metric=score(generation['rows'],sources,targets);extra={}
        if panel=='new':
            for present,label in ((True,'Tpresent'),(False,'Tabsent')):
                chosen=[r for r in targets if bool(r['canonical_ir']['rules'][0]['temporal']) is present];ids={r['id'] for r in chosen}
                ss=[r for r in sources if r['id'] in ids];pp=[r for r,s in zip(generation['rows'],sources,strict=True) if s['id'] in ids]
                extra[label]=score(pp,ss,chosen);result['tuning_new_'+label+'_exact']=extra[label]['exact']
        if panel=='condition':result['condition_metrics']=scoped_metrics(generation['rows'],sources,targets)
        result['tuning_'+panel]=write(folder/f'{stem}-tuning-{panel}.json',{'generation':generation,'metrics':metric,
            'temporal_class_metrics':extra,'scope_metrics':result['condition_metrics'] if panel=='condition' else None})
        result['tuning_'+panel+'_exact']=metric['exact']
    result['retention_metrics']={}
    for panel in RETENTION_PANELS:
        sources=job['sources']['retention_'+panel];targets=job['retention_targets'][panel];generation=generate(decoder,sources)
        metric=scoped_metrics(generation['rows'],sources,targets);result['retention_metrics'][panel]=metric
        result['retention_'+panel]=write(folder/f'{stem}-retention-{panel}.json',{'generation':generation,'metrics':score(generation['rows'],sources,targets),'scope_metrics':metric})
    for panel in DOCUMENT_TUNING_PANELS:
        for policy in BOUNDARY_POLICIES:
            generation=retention.generate_documents(decoder,job['boundaries'][policy][panel],job['document_sources'][panel])
            metric=retention.score_document_tuning(generation,job[panel]);prefix=DOCUMENT_PREFIX[panel]
            result[panel+'_'+policy]=write(folder/f'{stem}-{panel}-{policy}.json',{'generation':generation,'metrics':metric})
            result['tuning_'+prefix+'_'+policy+'_exact']=metric['exact'];result['tuning_'+prefix+'_'+policy+'_unsupported_accepted']=metric['unsupported_accepted']
    generation=generate(decoder,job['training_sources']);metric=score(generation['rows'],job['training_sources'],job['new_train'])
    result['training_new']=write(folder/f'{stem}-training-existing-temporal.json',{'generation':generation,'metrics':metric,
        'diagnostic_only':True,'checkpoint_selection_uses_this_metric':False,'previously_authored_training_rows':True,'new_training_rows_added':0})
    result['training_new_exact']=metric['exact'];return result


def document_signature(generation):
    result = deepcopy(generation['rows'])
    for row in result:
        if row['clause_generation'] is not None: row['clause_generation'] = {'rows':row['clause_generation']['rows']}
    return result


def initialization_equal(parent_metrics,initial_metrics):
    for key in [*('tuning_'+panel for panel in TUNING_PANELS),*('retention_'+panel for panel in RETENTION_PANELS),'training_new']:
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
            and trial['executed_steps'] == 200, 'trial identity, architecture, or inherited parent attribution differs')
        if trial['selection'] == 'candidate':
            require(trial['decoder_kind'] == 'scope_retention' and trial['selected_steps'] in STAGES, 'trained candidate attribution differs')
        else:
            require(trial['selection'] == 'parent_fallback_no_acceptable_replacement' and trial['decoder_kind'] == parents[(architecture,seed)]['decoder_kind']
                and trial['selected_steps'] == 0 and trial['checkpoint'] == trial['parent'], 'fallback must retain its exact architecture parent')
    models = list(trials)
    for architecture in ARCHITECTURES:
        for seed in SEEDS:
            parent = parents[(architecture,seed)]
            models.append({'name':f'parent_{architecture}-{seed}','arm':f'parent_{architecture}',
                'architecture':architecture,'objective':'parent','seed':seed,'enabled':architecture == 'grounding',
                'decoder_kind':parent['decoder_kind'],'checkpoint':parent['checkpoint'],'parent':parent['checkpoint'],
                'selection':'unchanged_parent','selected_steps':0,'executed_steps':0})
    models.sort(key=lambda row:row['name'])
    return models


def generation_job(job):
    import torch
    torch.set_num_threads(1);item=job['item'];decoder=load_decoder(item['checkpoint'],item['decoder_kind'])
    folder=Path(job['folder']);folder.mkdir(exist_ok=True)
    singles={panel:write(folder/f'{panel}-generation.json',generate(decoder,rows)) for panel,rows in job['sources'].items()}
    print(json.dumps({'phase':'generated','model':item['name'],'selection':item['selection']}),flush=True)
    return item['name'],singles


def fit_job(job):
    trial_started=time.monotonic()
    import torch
    torch.set_num_threads(1)
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_mixed_replay as mixed
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_scope_retention as runtime
    folder=Path(job['folder']);folder.mkdir()
    parent=runtime._parent_runtime(job['parent_kind']).load_checkpoint(job['parent']['path'],expected_sha256=job['parent']['sha256'])
    require(parent['model_config']['seed'] == job['seed'] and parent['model_config']['trigger_enabled'] is job['enabled'],
        'same-seed architecture parent required')
    tuning=[row for panel in TUNING_PANELS for row in job['tuning'][panel]]+[r for p in RETENTION_PANELS for r in job['retention_targets'][p]]
    checkpoint=runtime.build_checkpoint(parent,job['training'],tuning,job['runtime_pairs'],job['hard_mining'],
        parent_kind=job['parent_kind'],objective=job['objective'],seed=job['seed'],learning_rate=.00025,batch_size=12)
    require(checkpoint['model_state'] == parent['model_state'] and runtime.optimizer_steps(checkpoint) == 0,
        'exact pretrained tensors and reset optimizer progress required')
    initial_ref=runtime.save_checkpoint(checkpoint,folder/'initial-checkpoint.json')
    initial_metrics=evaluate_tuning(runtime.ScopeRetentionDecoder(checkpoint),job,folder,'initial')
    require(initialization_equal(job['parent_metrics'],initial_metrics), 'initial predictions differ from parent')
    initialization=write(folder/'initialization.json',{'parent':job['parent'],'initial':initial_ref,
        'initial_model_state_sha256':digest(checkpoint['model_state']),'parent_model_state_sha256':digest(parent['model_state']),
        'tuning':initial_metrics,'parent_kind':job['parent_kind'],'hard_mining_sha256':digest(job['hard_mining']),'parent_tuning':job['parent_metrics'],'all_initial_tensors_equal':True,
        'all_tuning_numerical_predictions_equal':True,'optimizer_reset':True,'historical_optimizer_resumed':False})
    stages=[]
    for target_steps in STAGES:
        before=digest(checkpoint)
        result=runtime.train_decoder(checkpoint,job['training'],tuning,job['runtime_pairs'],max_steps=target_steps-runtime.optimizer_steps(checkpoint),
            max_seconds=max(0.,600-(time.monotonic()-trial_started)))
        checkpoint=result['checkpoint'];steps=runtime.optimizer_steps(checkpoint)
        require(steps == target_steps, 'complete200-update matched budget required; partial runs cannot qualify')
        stage={'steps':steps,'checkpoint':runtime.save_checkpoint(checkpoint,folder/f'checkpoint-{steps}.json'),
            'previous_checkpoint_sha256':before,'training_report':write(folder/f'training-{steps}.json',result['report']),
            **evaluate_tuning(runtime.ScopeRetentionDecoder(checkpoint),job,folder,f'stage-{steps}')}
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
        'decoder_kind':'scope_retention' if chosen else job['parent_kind'],
        'checkpoint':chosen['checkpoint'] if chosen else job['parent'],
        'selection':'candidate' if chosen else 'parent_fallback_no_acceptable_replacement',
        'selected_steps':chosen['steps'] if chosen else 0,'executed_steps':200,'parent':job['parent'],
        'parent_kind':job['parent_kind'],'hard_mining_sha256':digest(job['hard_mining']),'parent_tuning':job['parent_metrics'],'initialization':initialization,'initial_checkpoint':initial_ref,
        'initial_model_state_sha256':digest(parent['model_state']),'stages':stages,
        'trial_wall_seconds':time.monotonic()-trial_started,'trial_wall_limit_seconds':600,
        'historical_optimizer_resumed':False,
        'fresh_targets_opened':False,'exposed_retention_targets_opened':True,**FALSE}
    selection_ref=write(folder/'selection.json',result)
    return {**result,'selection_record':selection_ref}


def audit_trials(trials):
    require(len(trials)==4,'four complete training trials required')
    audit=[]
    for trial in trials:
        exposures=[row for stage in trial['stages'] for row in read_ref(stage['training_report'])['batch_exposures']]
        require(len(exposures)==200 and [r['optimizer_step'] for r in exposures]==list(range(1,201)),
            'all200 ordered update receipts required')
        counts=read_ref(trial['initial_checkpoint'])['pool_counts']
        coverage={pool:{'pool_entries':count,'draws':sum(len(e['indices_by_pool'][pool]) for e in exposures),
            'unique_entries_seen':len({i for e in exposures for i in e['indices_by_pool'][pool]})} for pool,count in counts.items()}
        audit.append({'objective':trial['objective'],'architecture':trial['architecture'],'seed':trial['seed'],'parent':trial['parent'],
            'batch_count':200,'batch_exposures_sha256':digest(exposures),'actual_pool_coverage':coverage,'rehearsal_unique_ids':len({i for e in exposures for i in e['rehearsal_ids']}),'rehearsal_draws':4*len(exposures),'same_architecture_no_update_control':True,
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
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_scope_retention as runtime
    from scripts.ops.legal_ir import prepare_legal_condition_rehearsal_corpus as corpus
    require(type(args.workers) is int and 1<=args.workers<=3,'one to three CPU workers required')
    inputs=load_config(args.config);output=Path(args.output).resolve();output.mkdir(parents=True,exist_ok=False)
    pins={str(Path(m.__file__).resolve()):sha(m.__file__) for m in (runtime,previous,retention,boundary_run,boundary,clauses,clauses.compose,corpus,sys.modules[__name__])}
    plan=write(output/'plan.json',{'schema':SCHEMA,'config':ref(args.config),'producer_pins':pins,'objectives':list(OBJECTIVES),
        'architectures':list(ARCHITECTURES),'seeds':list(SEEDS),'additional_stage_steps':list(STAGES),
        'additional_updates_per_trial':200,'total_optimizer_updates':800,'learning_rate':.00025,'optimizer':'Adam',
        'optimizer_reset':True,'historical_optimizer_resumed':False,'batch_size':12,'auxiliary_batch_size':4,
        'consistency_weight':.25,'teacher_weight':.5,'overlap_weight':.1,'condition_weight':.5,
        'matched_main_and_rehearsal_inputs':True,'hard_examples_per_class':64,'mining':inputs['config']['hard_mining_manifest'],
        'inference_changed':False,'joint_boundary_stage_search':False,'threads_per_worker':1,'workers':args.workers,
        'trial_wall_limit_seconds':600,'training_diagnostic_count':192,'training_diagnostics_used_for_selection':False,
        'training_inventory_count':4080,'new_training_rows':0,'single_counts':SINGLE_COUNTS,'document_counts':DOCUMENT_COUNTS,
        'final_document_counts':FINAL_DOCUMENT_COUNTS,'boundary_heads':inputs['boundary_heads'],
        'selection_contract':inputs['config']['study_design'],'fresh_targets_opened':False,'exposed_panels_admitted_as_retention':True,**FALSE})
    source_ref=write(output/'source-inputs.json',inputs['sources']);doc_ref=write(output/'document-source-inputs.json',inputs['document_sources'])
    boundaries,refs={},{}
    for name,head in inputs['boundary_heads'].items():
        decoder=boundary.ClauseBoundaryDecoder(read_ref(head['checkpoint']))
        boundaries[name]={p:clauses.decode_all(decoder,inputs['document_sources'][p]) for p in DOCUMENT_TUNING_PANELS}
        refs[name]={p:write(output/f'{name}-{p}-boundaries.json',g) for p,g in boundaries[name].items()}
    fixed={'parent':boundaries['parent'],'expanded':boundaries['expanded-1730']}
    parent_metrics={}
    for architecture in ARCHITECTURES:
        item=inputs['parents'][(architecture,1730)]
        parent_metrics[(architecture,1730)]=evaluate_tuning(load_decoder(item['checkpoint'],item['decoder_kind']),
            {**inputs,'boundaries':fixed},output,f'parent-{architecture}-1730')
    parent_ref=write(output/'parent-tuning.json',{f'parent_{a}-{s}':m for (a,s),m in parent_metrics.items()})
    jobs=[{**inputs,'objective':o,'architecture':a,'seed':1730,'enabled':a=='grounding',
        'parent':inputs['parents'][(a,1730)]['checkpoint'],'parent_kind':inputs['parents'][(a,1730)]['decoder_kind'],
        'hard_mining':inputs['hard_mining'][(a,1730)],'parent_metrics':parent_metrics[(a,1730)],
        'boundaries':fixed,'folder':str(output/f'{o}_{a}-1730')} for o in OBJECTIVES for a in ARCHITECTURES]
    trials=[]
    with ProcessPoolExecutor(max_workers=args.workers,mp_context=multiprocessing.get_context('spawn')) as pool:
        for future in as_completed([pool.submit(fit_job,job) for job in jobs]):trials.append(future.result())
    trials.sort(key=lambda r:r['name']);audit=audit_trials(trials)
    selections=write(output/'selections-frozen.json',{'trials':trials,'parent_tuning':parent_ref,'trial_update_audit':audit,
        'executed_optimizer_updates':800,'fresh_targets_opened':False,'exposed_panels_admitted_as_retention':True,**FALSE})
    models=model_inventory(trials,inputs['parents']);heads=write(output/'models-frozen.json',models)
    jobs=[{'item':m,'sources':inputs['sources'],'folder':str(output/m['name'])} for m in models];files={}
    with ProcessPoolExecutor(max_workers=args.workers,mp_context=multiprocessing.get_context('spawn')) as pool:
        for future in as_completed([pool.submit(generation_job,job) for job in jobs]):
            name,panels=future.result();files[name]=panels
    require(all(sha(p)==h for p,h in pins.items()) and load_config(args.config)==inputs,'clause inputs or producer drift')
    frozen={'schema':SCHEMA,'plan':plan,'sources':source_ref,'document_sources':doc_ref,'boundaries':refs,
        'selections':selections,'heads':heads,'models':models,'files':files,'all_training_selection_and_generation_complete':True,
        'executed_optimizer_updates':800,'fresh_targets_opened':False,'exposed_panels_admitted_as_retention':True,
        'parent_fallbacks':[r['name'] for r in trials if r['selection']!='candidate'],**FALSE}
    write(output/'generation-frozen.json',frozen);print(json.dumps({'phase':'frozen','models':6,'optimizer_updates':800,'fallbacks':frozen['parent_fallbacks']}),flush=True)
    return frozen


JOINT_SCHEMA='legal-scope-retention-joint-experiment/v1'
FINAL_BOUNDARY_SOURCE_NAMES={'fresh_documents':'root_condition_fresh_documents',
    'retention_facet_documents':'facet_exposed_fresh_document_clauses',
    'retention_temporal_documents':'temporal_document_challenge_targets'}


def compose_job(job):
    import torch
    torch.set_num_threads(1);item=job['model'];decoder=load_decoder(item['checkpoint'],item['decoder_kind'])
    folder=Path(job['folder']);folder.mkdir();files={}
    for head in ('parent','control','target'):
        name=item['name']+'__scope_'+head
        files[name]={panel:write(folder/f'{head}-{panel}-generation.json',retention.generate_documents(decoder,
            job['boundaries'][head][panel],sources)) for panel,sources in job['sources'].items()}
    return files


def compose(args):
    inputs=load_config(args.config);clause_ref=ref(args.clause_freeze);scope_ref=ref(args.boundary_freeze)
    clause=read_ref(clause_ref);scope=read_ref(scope_ref)
    require(clause['schema']==SCHEMA and clause['all_training_selection_and_generation_complete'] is True,
        'complete clause source-only freeze required')
    require(scope['all_training_selection_and_generation_complete'] is True and set(scope['files'])=={'parent','control','target'},
        'three independently selected scope head slots required')
    require(read_ref(clause['plan'])['config']==ref(args.config),'clause freeze/config differs')
    models=clause['models'];require(len(models)==6 and len({m['name'] for m in models})==6,'six distinct clause slots required')
    heads={m['name']:m for m in scope['models']};require(set(heads)=={'parent','control','target'},'scope logical slots differ')
    sources={p:inputs['document_sources'][p] for p in FINAL_DOCUMENT_COUNTS};boundaries={};boundary_refs={}
    for head in heads:
        boundaries[head]={};boundary_refs[head]={}
        for panel,scope_panel in FINAL_BOUNDARY_SOURCE_NAMES.items():
            require(clauses.source_rows(read_ref(scope['sources'][scope_panel]))==sources[panel],'cross-factor document source identity differs')
            boundary_refs[head][panel]=scope['files'][head][scope_panel]
            boundaries[head][panel]=read_ref(boundary_refs[head][panel])
    output=Path(args.output).resolve();output.mkdir(parents=True,exist_ok=False)
    pipelines=[]
    for model in models:
        for head,item in heads.items():
            pipelines.append({'name':model['name']+'__scope_'+head,'source_model_name':model['name'],
                'arm':model['arm']+'__scope_'+head,'objective':model['objective'],'architecture':model['architecture'],'seed':1730,
                'checkpoint':model['checkpoint'],'decoder_kind':model['decoder_kind'],'enabled':model['enabled'],
                'selection':model['selection'],'selected_steps':model['selected_steps'],'boundary_head':head,
                'boundary_checkpoint':item['checkpoint'],'boundary_selection':item['selection'],'boundary_selected_steps':item['selected_steps']})
    jobs=[{'model':model,'sources':sources,'boundaries':boundaries,'folder':str(output/model['name'])} for model in models]
    files={}
    with ProcessPoolExecutor(max_workers=args.workers,mp_context=multiprocessing.get_context('spawn')) as pool:
        for future in as_completed([pool.submit(compose_job,job) for job in jobs]):files.update(future.result())
    require(set(files)=={p['name'] for p in pipelines},'full18-pipeline cross product required')
    frozen={'schema':JOINT_SCHEMA,'clause_generation':clause_ref,'boundary_generation':scope_ref,
        'config':ref(args.config),'models':models,'files':clause['files'],'sources':clause['sources'],
        'document_sources':write(output/'document-source-inputs.json',sources),'boundaries':boundary_refs,
        'pipelines':pipelines,'pipeline_heads':write(output/'pipelines.json',pipelines),'document_files':files,
        'all_training_selection_and_generation_complete':True,'no_joint_stage_search':True,'fresh_targets_opened':False,
        'exposed_retention_targets_opened':True,'producer':ref(__file__),**FALSE}
    write(output/'generation-frozen.json',frozen);return frozen


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--config',required=True)
    parser.add_argument('--output',required=True);parser.add_argument('--workers',type=int,default=3)
    parser.add_argument('--clause-freeze');parser.add_argument('--boundary-freeze')
    args=parser.parse_args(argv)
    require(bool(args.clause_freeze)==bool(args.boundary_freeze),'both independent freezes required for composition')
    require(1<=args.workers<=3,'one to three workers required')
    return compose(args) if args.clause_freeze else run(args)


if __name__=='__main__':main()
