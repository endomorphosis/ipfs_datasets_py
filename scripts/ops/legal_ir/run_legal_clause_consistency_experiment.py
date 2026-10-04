#!/usr/bin/env python3
"""Matched CE versus clause-role consistency continuation with sealed evaluation.

Two objectives share parents, fitting sources, minibatch orders, and unchanged
inference. Candidate selection must retain both single-rule and two-boundary
whole-document tuning performance. Unsuccessful trials retain their own parent.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from copy import deepcopy
import multiprocessing
from pathlib import Path
import sys
import json

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from scripts.ops.legal_ir import run_legal_boundary_curriculum_experiment as boundary_run
from scripts.ops.legal_ir import run_legal_construction_retention_experiment as retention

require, read, read_ref, ref, sha, write, digest = (getattr(retention, key) for key in
    ('require', 'read', 'read_ref', 'ref', 'sha', 'write', 'digest'))
source_rows, generate, score, target_metadata = retention.source_rows, retention.generate, retention.score, retention.target_metadata
clauses, boundary = retention.clauses, retention.boundary
SCHEMA = 'legal-clause-consistency-experiment/v1'
CONFIG_SCHEMA = 'legal-clause-consistency-run-config/v1'
OBJECTIVES = ('ce', 'consistency')
ARCHITECTURES = ('continuation', 'grounding')
SEEDS = (1729, 1730, 1731)
TUNING_PANELS = ('earlier', 'temporal', 'new')
BOUNDARY_POLICIES = ('parent', 'expanded')
SINGLE_COUNTS = {'tuning_earlier': 96, 'tuning_temporal': 120, 'tuning_new': 96,
    'fresh': 144, 'prior_construction': 180, 'earlier_regression': 192, 'temporal_regression': 180}
DOCUMENT_COUNTS = {'document_tuning': 96, 'fresh_documents': 96, 'prior_boundary_documents': 96, 'exposed_documents': 96}
FALSE = {key: value for key, value in retention.FALSE.items() if key != 'training_executed'}


def metric_keys():
    return {**{'tuning_' + key + '_exact': maximum for key, maximum in (('earlier',96),('temporal',120),('new',96))},
        **{'tuning_document_' + policy + '_exact':72 for policy in BOUNDARY_POLICIES},
        **{'tuning_document_' + policy + '_unsupported_accepted':24 for policy in BOUNDARY_POLICIES}}


def validate_tuning_counts(value):
    require(all(type(value[key]) is int and 0 <= value[key] <= maximum for key, maximum in metric_keys().items()),
        'complete bounded single and two-boundary document tuning metrics required')


def eligible(stage, parent):
    validate_tuning_counts(stage); validate_tuning_counts(parent)
    retained = ('tuning_earlier_exact', 'tuning_temporal_exact',
        'tuning_document_parent_exact', 'tuning_document_expanded_exact')
    return all(stage[key] >= parent[key] - 1 for key in retained) and all(
        stage['tuning_document_' + policy + '_unsupported_accepted'] == 0 for policy in BOUNDARY_POLICIES)


def select_stage(stages, parent):
    require(type(stages) is list and len(stages) == 2 and {stage['steps'] for stage in stages} == {400,800}
        and all(type(stage['steps']) is int for stage in stages), 'both400/800 additional-update stages required')
    candidates = [stage for stage in stages if eligible(stage, parent)]
    return max(candidates, key=lambda stage: (stage['tuning_new_exact'],stage['tuning_temporal_exact'],
        stage['tuning_document_expanded_exact'],stage['tuning_document_parent_exact'],stage['tuning_earlier_exact'],
        -stage['steps'])) if candidates else None


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


def prior_inventory(frozen, heads, inputs):
    require(frozen['schema'] == boundary_run.SCHEMA and frozen['all_training_selection_and_generation_complete'] is True
        and frozen['fresh_targets_opened'] is frozen['regression_targets_opened'] is False,
        'complete frozen boundary-curriculum generation required')
    expected = {f'{policy}_{architecture}-{seed}' for policy in ('parent',*boundary_run.CURRICULA)
        for architecture in ARCHITECTURES for seed in SEEDS}
    by_name = {model['name']: model for model in frozen['models']}
    require(len(by_name) == len(frozen['models']) == 18 and set(by_name) == expected, 'complete prior eighteen pipeline slots required')
    by_head = {head['name']: head for head in heads}
    require(len(by_head) == len(heads) == 7 and set(by_head) == {'parent',*(f'{c}-{s}' for c in boundary_run.CURRICULA for s in SEEDS)},
        'complete prior seven boundary heads required')
    require(by_head['parent']['checkpoint'] == inputs['boundary_parent'], 'frozen parent boundary differs')
    controls = {}
    for architecture in ARCHITECTURES:
        for seed in SEEDS:
            item = by_name[f'parent_{architecture}-{seed}']; expected_clause = inputs['clause_controls'][(architecture,seed)]
            require(item['architecture'] == architecture and item['seed'] == seed and item['boundary_policy'] == 'parent'
                and item['boundary_head'] == 'parent' and item['boundary_checkpoint'] == inputs['boundary_parent']
                and item['checkpoint'] == expected_clause['checkpoint'] and item['decoder_kind'] == 'mixed'
                and item['enabled'] is (architecture == 'grounding') and item['clause_curriculum'] == 'temporal_augmented'
                and item['clause_selected_steps'] == 800, 'same-architecture seed temporal800 clause parent required')
            read_ref(item['checkpoint'],parse=False)
            controls[(architecture,seed)] = item
    chosen_heads = {name: by_head[name] for name in ('parent',*(f'expanded-{seed}' for seed in SEEDS))}
    for seed in SEEDS:
        require(chosen_heads[f'expanded-{seed}']['seed'] == seed and chosen_heads[f'expanded-{seed}']['curriculum'] == 'expanded',
            'expanded boundary seed attribution differs')
    for head in chosen_heads.values(): read_ref(head['checkpoint'],parse=False)
    return controls,chosen_heads


def load_config(path):
    from scripts.ops.legal_ir import prepare_legal_clause_consistency_corpus as corpus
    config = read(path)
    pairs = ('prior_construction','earlier_regression','temporal_regression','document_tuning','prior_boundary_document','exposed_document')
    keys = {'schema','corpus_manifest','prior_boundary_generation','study_design','producer_files',
        *(name+suffix for name in pairs for suffix in ('_sources','_targets'))}
    sealed = {name+'_targets' for name in pairs if name != 'document_tuning'}
    require(type(config) is dict and set(config) == keys and config['schema'] == CONFIG_SCHEMA,
        'closed clause-consistency run configuration required')
    for key in keys - sealed - {'schema','producer_files'}: read_ref(config[key],parse=False)
    for key in sealed: target_metadata(config[key])
    for reference in config['producer_files']: read_ref(reference,parse=False)
    loaded = corpus.load_training_inputs(config['corpus_manifest']['path'])
    manifest = loaded['manifest']
    for name in ('challenge_targets','document_challenge_targets'): target_metadata(manifest['artifacts'][name])
    require(set(loaded['replay']) == {'earlier','prior_new','temporal'} and
        [len(loaded['replay'][name]) for name in ('earlier','prior_new','temporal')] == [1152,600,600],
        'unchanged historical replay inventories required')
    require(len(loaded['new_train']) == 384 and len(loaded['new_tuning']) == 96, 'declared new paired clause inventory required')
    validate_pairs(loaded['new_train'],loaded['training_pairs'],192)
    validate_pairs(loaded['new_tuning'],loaded['tuning_pairs'],48)
    training = [*loaded['replay']['earlier'],*loaded['replay']['prior_new'],*loaded['replay']['temporal'],*loaded['new_train']]
    tuning = {'earlier':loaded['tuning']['earlier'],'temporal':loaded['tuning']['temporal'],'new':loaded['new_tuning']}
    require([len(tuning[panel]) for panel in TUNING_PANELS] == [96,120,96], 'complete tuning single panels required')
    require(all(row['domain'] == 'earlier' for row in loaded['replay']['earlier']) and
        all(row['domain'] == 'new' for key in ('prior_new','temporal') for row in loaded['replay'][key]), 'historical training domains differ')
    sources = {'tuning_'+panel:source_rows(tuning[panel]) for panel in TUNING_PANELS}
    sources['fresh'] = source_rows(loaded['fresh_sources'])
    for name in ('prior_construction','earlier_regression','temporal_regression'):
        payload = read_ref(config[name+'_sources'])
        rows = payload['challenge'] if name == 'earlier_regression' else payload
        require(all(not {'canonical_ir','facet_spans','trigger_span'} & set(row) for row in rows),
            'regression source contains labels')
        sources[name] = source_rows(rows)
    require({name:len(rows) for name,rows in sources.items()} == SINGLE_COUNTS, 'complete single source panels required')
    require(all(not {'canonical_ir','facet_spans','trigger_span'} & set(row) for row in loaded['fresh_sources']),
        'fresh single source contains labels')
    document_tuning = read_ref(config['document_tuning_targets'])
    boundary_run.validate_references(document_tuning,96,72)
    documents = {'document_tuning':read_ref(config['document_tuning_sources']), 'fresh_documents':loaded['fresh_document_sources'],
        'prior_boundary_documents':read_ref(config['prior_boundary_document_sources']), 'exposed_documents':read_ref(config['exposed_document_sources'])}
    require(clauses.source_rows(document_tuning) == documents['document_tuning'], 'admitted document tuning source/reference mismatch')
    for rows in documents.values(): boundary_run.validate_sources(rows,96)
    ids,texts = set(),set()
    for rows in (source_rows(training),*sources.values(),*documents.values()):
        local_ids = {row.get('id',row.get('candidate_id')) for row in rows}; local_texts = {row['source_sha256'] for row in rows}
        require(len(local_ids) == len(local_texts) == len(rows) and not ids & local_ids and not texts & local_texts,
            'fitting, tuning, or generation source overlap')
        ids |= local_ids; texts |= local_texts
    prior = read_ref(config['prior_boundary_generation']); prior_plan = read_ref(prior['plan'])
    require(all(sha(file) == wanted for file,wanted in prior_plan['producer_pins'].items()), 'prior boundary producer drift')
    prior_inputs = boundary_run.load_config(prior_plan['config']['path'])
    controls,boundary_heads = prior_inventory(prior,read_ref(prior['boundary_heads']),prior_inputs)
    old_sources = read_ref(prior['sources'])
    require(all(documents[left] == old_sources[right] for left,right in
        (('document_tuning','tuning_new'),('prior_boundary_documents','fresh_documents'),('exposed_documents','exposed_documents'))),
        'frozen admitted/regression document source binding differs')
    return {'config':config,'manifest':manifest,'training':training,'training_pairs':loaded['training_pairs'],
        'new_train':loaded['new_train'],'replay':loaded['replay'],'tuning':tuning,'tuning_pairs':loaded['tuning_pairs'],
        'runtime_pairs':[[pair['left_id'],pair['right_id']] for pair in loaded['training_pairs']],
        'sources':sources,'document_tuning':document_tuning,'document_sources':documents,
        'parents':controls,'boundary_heads':boundary_heads}


def load_decoder(checkpoint,decoder_kind):
    if decoder_kind == 'mixed': return retention.load_decoder(checkpoint,'mixed')
    require(decoder_kind == 'consistency', 'declared mixed or consistency decoder kind required')
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_consistency as runtime
    return runtime.ConsistencyDecoder(runtime.load_checkpoint(checkpoint['path'],expected_sha256=checkpoint['sha256']))


def evaluate_tuning(decoder,job,folder,stem):
    result = {}
    for panel in TUNING_PANELS:
        generation = generate(decoder,job['sources']['tuning_'+panel])
        metric = score(generation['rows'],job['sources']['tuning_'+panel],job['tuning'][panel])
        result['tuning_'+panel] = write(folder/f'{stem}-tuning-{panel}.json',{'generation':generation,'metrics':metric})
        result['tuning_'+panel+'_exact'] = metric['exact']
    for policy in BOUNDARY_POLICIES:
        generation = retention.generate_documents(decoder,job['boundaries'][policy]['document_tuning'],job['document_sources']['document_tuning'])
        metric = retention.score_document_tuning(generation,job['document_tuning'])
        result['document_tuning_'+policy] = write(folder/f'{stem}-document-tuning-{policy}.json',{'generation':generation,'metrics':metric})
        result['tuning_document_'+policy+'_exact'] = metric['exact']
        result['tuning_document_'+policy+'_unsupported_accepted'] = metric['unsupported_accepted']
    return result


def document_signature(generation):
    result = deepcopy(generation['rows'])
    for row in result:
        if row['clause_generation'] is not None: row['clause_generation'] = {'rows':row['clause_generation']['rows']}
    return result


def initialization_equal(parent_metrics,initial_metrics):
    for panel in TUNING_PANELS:
        key = 'tuning_'+panel
        original,current = read_ref(parent_metrics[key]),read_ref(initial_metrics[key])
        require(original['generation']['rows'] == current['generation']['rows'] and original['metrics'] == current['metrics'],
            'initial single predictions, logits, or tuning scores differ from parent')
    for policy in BOUNDARY_POLICIES:
        key = 'document_tuning_'+policy
        original,current = read_ref(parent_metrics[key]),read_ref(initial_metrics[key])
        require(document_signature(original['generation']) == document_signature(current['generation']) and
            original['metrics'] == current['metrics'], 'initial document predictions or tuning scores differ from parent')
    return True


def model_inventory(trials,parents):
    expected = {(objective,architecture,seed) for objective in OBJECTIVES for architecture in ARCHITECTURES for seed in SEEDS}
    require(len(trials) == 12 and {(r['objective'],r['architecture'],r['seed']) for r in trials} == expected,
        'all twelve matched fitting trials required')
    for trial in trials:
        architecture,seed,objective = trial['architecture'],trial['seed'],trial['objective']
        require(trial['name'] == f'{objective}_{architecture}-{seed}' and trial['arm'] == f'{objective}_{architecture}'
            and trial['enabled'] is (architecture == 'grounding') and trial['parent'] == parents[(architecture,seed)]['checkpoint']
            and trial['executed_steps'] == 800, 'trial identity, architecture, or inherited parent attribution differs')
        if trial['selection'] == 'candidate':
            require(trial['decoder_kind'] == 'consistency' and trial['selected_steps'] in (400,800), 'trained candidate attribution differs')
        else:
            require(trial['selection'] == 'parent_fallback_no_acceptable_replacement' and trial['decoder_kind'] == 'mixed'
                and trial['selected_steps'] == 0 and trial['checkpoint'] == trial['parent'], 'fallback must retain its exact architecture parent')
    models = list(trials)
    for architecture in ARCHITECTURES:
        for seed in SEEDS:
            parent = parents[(architecture,seed)]
            models.append({'name':f'parent_{architecture}-{seed}','arm':f'parent_{architecture}',
                'architecture':architecture,'objective':'parent','seed':seed,'enabled':architecture == 'grounding',
                'decoder_kind':'mixed','checkpoint':parent['checkpoint'],'parent':parent['checkpoint'],
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
    import torch
    torch.set_num_threads(1)
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_mixed_replay as mixed
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_consistency as runtime
    folder=Path(job['folder']);folder.mkdir()
    parent=mixed.load_checkpoint(job['parent']['path'],expected_sha256=job['parent']['sha256'])
    require(parent['config']['seed'] == job['seed'] and parent['config']['trigger_enabled'] is job['enabled'],
        'same-seed architecture parent required')
    tuning=[row for panel in TUNING_PANELS for row in job['tuning'][panel]]
    checkpoint=runtime.build_checkpoint(parent,job['training'],tuning,job['runtime_pairs'],
        objective=job['objective'],seed=job['seed'],learning_rate=.001,batch_size=12)
    require(checkpoint['model_state'] == parent['model_state'] and runtime.optimizer_steps(checkpoint) == 0,
        'exact pretrained tensors and reset optimizer progress required')
    initial_ref=runtime.save_checkpoint(checkpoint,folder/'initial-checkpoint.json')
    initial_metrics=evaluate_tuning(runtime.ConsistencyDecoder(checkpoint),job,folder,'initial')
    require(initialization_equal(job['parent_metrics'],initial_metrics), 'initial predictions differ from parent')
    initialization=write(folder/'initialization.json',{'parent':job['parent'],'initial':initial_ref,
        'initial_model_state_sha256':digest(checkpoint['model_state']),'parent_model_state_sha256':digest(parent['model_state']),
        'tuning':initial_metrics,'parent_tuning':job['parent_metrics'],'all_initial_tensors_equal':True,
        'all_tuning_numerical_predictions_equal':True,'optimizer_reset':True,'historical_optimizer_resumed':False})
    stages=[]
    for ordinal in (1,2):
        before=digest(checkpoint)
        result=runtime.train_decoder(checkpoint,job['training'],tuning,job['runtime_pairs'],max_steps=400,max_seconds=600)
        checkpoint=result['checkpoint'];steps=runtime.optimizer_steps(checkpoint)
        require(steps == ordinal*400, 'complete800-update matched budget required; partial runs cannot qualify')
        stage={'steps':steps,'checkpoint':runtime.save_checkpoint(checkpoint,folder/f'checkpoint-{steps}.json'),
            'previous_checkpoint_sha256':before,'training_report':write(folder/f'training-{steps}.json',result['report']),
            **evaluate_tuning(runtime.ConsistencyDecoder(checkpoint),job,folder,f'stage-{steps}')}
        stage['eligible']=eligible(stage,job['parent_metrics']);stages.append(stage)
        print(json.dumps({'phase':'trained_stage','objective':job['objective'],'architecture':job['architecture'],
            'seed':job['seed'],'steps':steps,'eligible':stage['eligible'],
            **{key:stage[key] for key in metric_keys()}}),flush=True)
    chosen=select_stage(stages,job['parent_metrics'])
    result={'name':f"{job['objective']}_{job['architecture']}-{job['seed']}",
        'arm':f"{job['objective']}_{job['architecture']}",'objective':job['objective'],
        'architecture':job['architecture'],'seed':job['seed'],'enabled':job['enabled'],
        'decoder_kind':'consistency' if chosen else 'mixed',
        'checkpoint':chosen['checkpoint'] if chosen else job['parent'],
        'selection':'candidate' if chosen else 'parent_fallback_no_acceptable_replacement',
        'selected_steps':chosen['steps'] if chosen else 0,'executed_steps':800,'parent':job['parent'],
        'parent_tuning':job['parent_metrics'],'initialization':initialization,'initial_checkpoint':initial_ref,
        'initial_model_state_sha256':digest(parent['model_state']),'stages':stages,
        'fresh_targets_opened':False,'regression_targets_opened':False,**FALSE}
    selection_ref=write(folder/'selection.json',result)
    return {**result,'selection_record':selection_ref}


def audit_matched_objectives(trials):
    by_key={(r['objective'],r['architecture'],r['seed']):r for r in trials}
    require(len(by_key) == len(trials) == 12, 'all matched objective trials required')
    audit=[]
    for architecture in ARCHITECTURES:
        for seed in SEEDS:
            ce,cons=(by_key[(objective,architecture,seed)] for objective in OBJECTIVES)
            require(ce['parent'] == cons['parent'] and ce['initial_model_state_sha256'] == cons['initial_model_state_sha256'],
                'paired objectives started from different pretrained tensors')
            exposures=[]
            for left,right in zip(ce['stages'],cons['stages']):
                a,b=read_ref(left['training_report']),read_ref(right['training_report'])
                require(left['steps'] == right['steps'] and a['batch_exposures'] == b['batch_exposures'],
                    'paired objective minibatch exposure/order differs')
                exposures.extend(a['batch_exposures'])
            require(len(exposures) == 800, 'full800 paired minibatches required')
            audit.append({'architecture':architecture,'seed':seed,'parent':ce['parent'],
                'initial_model_state_sha256':ce['initial_model_state_sha256'],'batch_count':800,
                'batch_exposures_sha256':digest(exposures),'identical_batch_order':True})
    return audit


def run(args):
    import torch
    torch.set_num_threads(1)
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_consistency as runtime
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_mixed_replay as mixed
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_dimensions as dimensions
    from scripts.ops.legal_ir import prepare_legal_clause_consistency_corpus as corpus
    require(type(args.workers) is int and 1 <= args.workers <= 3, 'one to three CPU workers required')
    inputs=load_config(args.config)
    output=Path(args.output).resolve();output.mkdir(parents=True,exist_ok=False)
    pins={str(Path(module.__file__).resolve()):sha(module.__file__) for module in
        (runtime,mixed,dimensions,boundary,clauses,clauses.compose,retention,boundary_run,corpus,sys.modules[__name__])}
    plan_ref=write(output/'plan.json',{'schema':SCHEMA,'config':ref(args.config),'producer_pins':pins,
        'objectives':list(OBJECTIVES),'architectures':list(ARCHITECTURES),'seeds':list(SEEDS),
        'additional_stage_steps':[400,800],'additional_updates_per_trial':800,'total_optimizer_updates':9600,
        'optimizer':'Adam','learning_rate':.001,'optimizer_reset':True,'historical_optimizer_resumed':False,
        'batch_size':12,'batch_quota':{'earlier':3,'historical_new':3,'new_pairs':3,'new_pair_rows':6},
        'consistency_weight':.25,'identical_pair_objective_batch_order_required':True,
        'inference_changed':False,'joint_search_enabled':False,'threads_per_worker':1,'workers':args.workers,
        'single_counts':SINGLE_COUNTS,'document_counts':DOCUMENT_COUNTS,'boundary_heads':inputs['boundary_heads'],
        'retention_tolerance':1,'unsupported_acceptance_tolerance':0,
        'selection':'eligible earlier,temporal,both document joint exact>=same parent minus1 and no document guard acceptance; maximize new,temporal,expanded-doc,parent-doc,earlier,earliest; otherwise unchanged same architecture parent',
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
            parent_metrics[(architecture,seed)]=evaluate_tuning(load_decoder(item['checkpoint'],'mixed'),job,output,f'parent-{architecture}-{seed}')
    parent_ref=write(output/'parent-tuning.json',{f'parent_{architecture}-{seed}':metrics for (architecture,seed),metrics in parent_metrics.items()})
    jobs=[{'objective':objective,'architecture':architecture,'seed':seed,'enabled':architecture == 'grounding',
        'parent':inputs['parents'][(architecture,seed)]['checkpoint'],'parent_metrics':parent_metrics[(architecture,seed)],
        'training':inputs['training'],'runtime_pairs':inputs['runtime_pairs'],'tuning':inputs['tuning'],
        'sources':{key:inputs['sources'][key] for key in ('tuning_earlier','tuning_temporal','tuning_new')},
        'document_tuning':inputs['document_tuning'],'document_sources':{'document_tuning':inputs['document_sources']['document_tuning']},
        'boundaries':{policy:{'document_tuning':panels['document_tuning']} for policy,panels in seed_boundaries(seed).items()},
        'folder':str(output/f'{objective}_{architecture}-{seed}')} for objective in OBJECTIVES for architecture in ARCHITECTURES for seed in SEEDS]
    trials=[]
    with ProcessPoolExecutor(max_workers=args.workers,mp_context=multiprocessing.get_context('spawn')) as pool:
        for future in as_completed([pool.submit(fit_job,job) for job in jobs]): trials.append(future.result())
    trials.sort(key=lambda row:row['name'])
    matching=audit_matched_objectives(trials)
    selections_ref=write(output/'selections-frozen.json',{'trials':trials,'parent_tuning':parent_ref,'matched_objective_audit':matching,
        'executed_optimizer_updates':9600,'fresh_targets_opened':False,'regression_targets_opened':False,**FALSE})
    models,pipelines=model_inventory(trials,inputs['parents'])
    for pipeline in pipelines: pipeline['boundary_checkpoint']=inputs['boundary_heads'][pipeline['boundary_head']]['checkpoint']
    models_ref=write(output/'models-frozen.json',models);pipelines_ref=write(output/'pipelines-frozen.json',pipelines)
    jobs=[{'item':item,'sources':inputs['sources'],'document_sources':inputs['document_sources'],
        'boundaries':seed_boundaries(item['seed']),'folder':str(output/item['name'])} for item in models]
    files,document_files={},{}
    with ProcessPoolExecutor(max_workers=args.workers,mp_context=multiprocessing.get_context('spawn')) as pool:
        for future in as_completed([pool.submit(generation_job,job) for job in jobs]):
            name,singles,documents=future.result();files[name]=singles;document_files.update(documents)
    require(all(sha(file) == wanted for file,wanted in pins.items()), 'consistency fitting/generation producer drift')
    require(load_config(args.config) == inputs, 'consistency fitting/source inputs changed during execution')
    result={'schema':SCHEMA,'plan':plan_ref,'sources':source_ref,'document_sources':document_source_ref,
        'boundaries':boundary_refs,'selections':selections_ref,'heads':models_ref,'models':models,
        'pipeline_heads':pipelines_ref,'pipelines':pipelines,'files':files,'document_files':document_files,
        'all_training_selection_and_generation_complete':True,'fresh_targets_opened':False,'regression_targets_opened':False,
        'executed_optimizer_updates':9600,'boundary_optimizer_updates':0,'training_executed':True,
        'parent_fallbacks':[row['name'] for row in trials if row['selection'] != 'candidate'],**FALSE}
    write(output/'generation-frozen.json',result)
    print(json.dumps({'phase':'frozen','models':18,'pipelines':36,'optimizer_updates':9600,'fallbacks':result['parent_fallbacks']}),flush=True)
    return result


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',required=True);parser.add_argument('--output',required=True)
    parser.add_argument('--workers',type=int,default=3)
    return run(parser.parse_args(argv))


if __name__ == '__main__': main()
