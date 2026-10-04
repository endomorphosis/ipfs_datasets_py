#!/usr/bin/env python3
"""Matched clause training with explicit role supervision and fixed boundary factors."""
from __future__ import annotations
import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from copy import deepcopy
import json
import multiprocessing
from pathlib import Path
import sys
import time
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT))
from scripts.ops.legal_ir import run_legal_condition_rehearsal_experiment as legacy
from ipfs_datasets_py.logic.autoformal import legal_clause_atom_boundary as boundary_runtime
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_span_role_span_rehearsal as runtime
require,read,read_ref,ref,sha,write,digest=(getattr(legacy,k) for k in ('require','read','read_ref','ref','sha','write','digest'))
clauses,boundary,retention=legacy.clauses,legacy.boundary,legacy.retention
source_rows,generate,score=legacy.source_rows,legacy.generate,legacy.score
SCHEMA='legal-role-span-rehearsal-experiment/v1'
CONFIG_SCHEMA='legal-role-span-rehearsal-config/v1'
OBJECTIVES=('base','role_rehearsal')
ARCHITECTURES=('continuation','grounding')
STAGES=(100,200)
SEED=1730
POLICIES=('original','distill')
DOC_PANELS=('new','atom_tuning','atom_fresh','prior_condition')
OPTIONAL=('conditions','exceptions','temporal')
FALSE={**legacy.FALSE,'actual_latent_conditioning_validated':False,'all_logic_families_supported':False,'production_promotion_performed':False}


def clause_metrics(generation,sources,targets):
    rows=generation['rows'];gold={r['id']:r for r in targets}
    require(len(rows)==len(sources)==len(targets)==len(gold) and len({r['id'] for r in sources})==len(sources),'complete unique clause occurrence inventory required')
    result={'count':len(rows),'fullrule_exact':0,'decoded':0,'actor_exact':0,
      'modality_fullrule':{m:{'count':0,'exact':0} for m in 'OPF'},
      'optional_facet':{f:{c:{'count':0,'exact':0} for c in ('present','absent')} for f in OPTIONAL}}
    for prediction,source in zip(rows,sources,strict=True):
        require(source['id'] in gold,'clause occurrence identity differs')
        target=gold[source['id']]
        require(source['source_sha256']==boundary.text_sha(source['source_text'])==boundary.text_sha(target['source_text'])
          and prediction['source_sha256']==source['source_sha256'],'clause source hash differs')
        wanted=target['canonical_ir'];truth=wanted['rules'][0]
        decoded=prediction['status']=='decoded' and prediction['canonical_ir'] is not None
        require((prediction['status']=='decoded') is (prediction['canonical_ir'] is not None),'clause status/canonical payload disagreement')
        actual=prediction['canonical_ir']['rules'][0] if decoded else None
        exact=decoded and prediction['canonical_ir']==wanted
        result['decoded']+=int(decoded);result['fullrule_exact']+=int(exact)
        result['actor_exact']+=int(decoded and actual['actor']==truth['actor'])
        cell=result['modality_fullrule'][truth['modality']];cell['count']+=1;cell['exact']+=int(exact)
        for field in OPTIONAL:
            cell=result['optional_facet'][field]['present' if truth[field] else 'absent']
            cell['count']+=1;cell['exact']+=int(decoded and actual[field]==truth[field])
    return result


def validate_clause_metric(value):
    require(type(value) is dict and set(value)=={'count','fullrule_exact','decoded','actor_exact','modality_fullrule','optional_facet'},'closed clause metric required')
    require(all(type(value[k]) is int and 0<=value[k]<=value['count'] for k in ('count','fullrule_exact','decoded','actor_exact'))
      and value['fullrule_exact']<=value['actor_exact']<=value['decoded'],'bounded emitted clause counts required')
    require(set(value['modality_fullrule'])==set('OPF') and set(value['optional_facet'])==set(OPTIONAL),'complete modality/facet classes required')
    for group in (value['modality_fullrule'],*value['optional_facet'].values()):
        require(all(type(c) is dict and set(c)=={'count','exact'} and all(type(c[k]) is int for k in c)
          and 0<=c['exact']<=c['count'] for c in group.values()) and sum(c['count'] for c in group.values())==value['count'],'complete bounded class denominators required')
    require(all(set(value['optional_facet'][f])=={'present','absent'} for f in OPTIONAL),'both optional classes required')
    require(sum(c['exact'] for c in value['modality_fullrule'].values())==value['fullrule_exact'],'fullrule strata disagree')
    require(all(value['fullrule_exact']<=sum(c['exact'] for c in classes.values())<=value['decoded']
      for classes in value['optional_facet'].values()),'optional exactness must contain fullrule and exclude abstentions')


def document_metrics(generation,targets):
    metric=retention.score_document_tuning(generation,targets)
    return {'count':metric['count'],'supported':metric['supported'],'unsupported':metric['unsupported'],
      'joint_exact':metric['exact'],
      'supported_ids':sorted(r['id'] for r in metric['rows'] if r['supported']),
      'unsupported_ids':sorted(r['id'] for r in metric['rows'] if not r['supported']),
      'joint_exact_ids':sorted(r['id'] for r in metric['rows'] if r['exact']),
      'unsupported_accepted_ids':sorted(r['id'] for r in metric['rows'] if not r['supported'] and r['composed'])}


def validate_document_metric(value):
    require(type(value) is dict and set(value)=={'count','supported','unsupported','joint_exact','supported_ids','unsupported_ids','joint_exact_ids','unsupported_accepted_ids'},'closed document gate metric required')
    require(all(type(value[k]) is int and value[k]>=0 for k in ('count','supported','unsupported','joint_exact'))
      and value['count']==value['supported']+value['unsupported'] and value['joint_exact']<=value['supported'],'complete document denominators required')
    for key in ('supported_ids','unsupported_ids','joint_exact_ids','unsupported_accepted_ids'):
        ids=value[key]
        require(type(ids) is list and all(type(i) is str for i in ids) and ids==sorted(set(ids)),'unique sorted document identities required')
    supported,unsupported=set(value['supported_ids']),set(value['unsupported_ids'])
    require(not supported&unsupported and len(supported)==value['supported'] and len(unsupported)==value['unsupported']
      and len(value['joint_exact_ids'])==value['joint_exact'] and set(value['joint_exact_ids'])<=supported
      and set(value['unsupported_accepted_ids'])<=unsupported,'exact document class and decision membership required')


def clause_retention(value,parent,prefix,failures):
    validate_clause_metric(value);validate_clause_metric(parent)
    require(value['count']==parent['count'],'same clause denominator required')
    for key in ('fullrule_exact','actor_exact'):
        if value[key]<parent[key]:failures.append(prefix+':'+key+'_regressed')
    for label in 'OPF':
        cell,baseline=value['modality_fullrule'][label],parent['modality_fullrule'][label]
        require(cell['count']==baseline['count'],'same modality denominator required')
        if cell['exact']<baseline['exact']:failures.append(prefix+':modality_'+label+'_regressed')
    for field in OPTIONAL:
        for label in ('present','absent'):
            cell,baseline=value['optional_facet'][field][label],parent['optional_facet'][field][label]
            require(cell['count']==baseline['count'],'same optional denominator required')
            if cell['exact']<baseline['exact']:failures.append(prefix+':'+field+'_'+label+'_regressed')


def document_retention(value,parent,prefix,failures):
    validate_document_metric(value);validate_document_metric(parent)
    require(all(value[k]==parent[k] for k in ('count','supported','unsupported','supported_ids','unsupported_ids')),'same document class identities and denominators required')
    if value['joint_exact']<parent['joint_exact']:failures.append(prefix+':joint_exact_regressed')
    if not set(value['unsupported_accepted_ids'])<=set(parent['unsupported_accepted_ids']):failures.append(prefix+':new_unsupported_sources_accepted')


def gates(stage,parent):
    failures=[]
    if not legacy.eligible(stage,parent):failures.append('legacy_condition_retention_failed')
    clause_retention(stage['new_single_metrics'],parent['new_single_metrics'],'new_single',failures)
    clause_retention(stage['prior_condition_metrics'],parent['prior_condition_metrics'],'prior_condition',failures)
    require(set(stage['old_atom_oracle_metrics'])==set(parent['old_atom_oracle_metrics'])=={'atom_tuning','atom_fresh'},'both old atom oracle panels required')
    for panel in ('atom_tuning','atom_fresh'):
        clause_retention(stage['old_atom_oracle_metrics'][panel],parent['old_atom_oracle_metrics'][panel],panel+':oracle_clauses',failures)
    require(set(stage['oracle_document_metrics'])==set(parent['oracle_document_metrics'])==set(DOC_PANELS)
      and set(stage['fixed_document_metrics'])==set(parent['fixed_document_metrics'])==set(DOC_PANELS),'all admitted document factors required')
    for panel in DOC_PANELS:
        document_retention(stage['oracle_document_metrics'][panel],parent['oracle_document_metrics'][panel],panel+':oracle_documents',failures)
        require(set(stage['fixed_document_metrics'][panel])==set(parent['fixed_document_metrics'][panel])==set(POLICIES),'both fixed boundary policies required')
        for policy in POLICIES:document_retention(stage['fixed_document_metrics'][panel][policy],parent['fixed_document_metrics'][panel][policy],panel+':'+policy,failures)
    if not (stage['new_single_metrics']['fullrule_exact']>parent['new_single_metrics']['fullrule_exact'] or
      stage['oracle_document_metrics']['new']['joint_exact']>parent['oracle_document_metrics']['new']['joint_exact']):
        failures.append('new:no_strict_single_or_oracle_document_improvement')
    return {'eligible':not failures,'failures':failures}


def ranking(stage):
    return (stage['new_single_metrics']['fullrule_exact'],stage['oracle_document_metrics']['new']['joint_exact'],
      stage['fixed_document_metrics']['new']['distill']['joint_exact'],stage['fixed_document_metrics']['new']['original']['joint_exact'],
      sum(v['fullrule_exact'] for v in stage['old_atom_oracle_metrics'].values()),*legacy.ranking(stage)[:-1],-stage['steps'])


def select_stage(stages,parent):
    require(type(stages) is list and [s['steps'] for s in stages]==list(STAGES),'both complete100/200 stages required')
    for stage in stages:require(stage['eligible'] is gates(stage,parent)['eligible'] and stage['failures']==gates(stage,parent)['failures'],'saved stage gate decision differs')
    candidates=[s for s in stages if s['eligible']]
    return max(candidates,key=ranking) if candidates else None


def load_decoder(checkpoint,kind):
    if kind=='role_span_rehearsal':return runtime.RoleSpanRehearsalDecoder(runtime.load_checkpoint(checkpoint['path'],expected_sha256=checkpoint['sha256']))
    return legacy.load_decoder(checkpoint,kind)


def load_config(path):
    from scripts.ops.legal_ir import prepare_legal_role_span_rehearsal_corpus as corpus
    config=json.loads(Path(path).read_bytes())
    require(set(config)=={'schema','corpus_manifest','prior_atom_generation','study_design','producer_files'} and config['schema']==CONFIG_SCHEMA,'closed experiment configuration required')
    for pin in [config[k] for k in ('corpus_manifest','prior_atom_generation','study_design')]+config['producer_files']:read_ref(pin,parse=False)
    loaded=corpus.load_training_inputs(config['corpus_manifest']['path'])
    old=loaded['legacy'];prior=read_ref(config['prior_atom_generation']);models={m['name']:m for m in prior['models']}
    heads={policy:models[name]['checkpoint'] for policy,name in (('original','parent'),('distill','distill_final400'))}
    require(heads['original']['sha256']=='e741578ac017e163588c6b49a16f6bca9dd0a37e71a0c345a3c9706814c3cf99'
      and heads['distill']['sha256']=='c09c43e6b44f5aa8c25faf7c611b2f4af3431c0e6bb366916d540ea0fb8f0fe8','two exact frozen boundary factors required')
    for pin in heads.values():read_ref(pin)
    expected={'continuation':('facet_retention','8be96c94218c7b28c973944fbe57b69b6d544a3c1358540a0860f34f896da9ca'),
      'grounding':('temporal_presence','4ef3dc047cc86fbfa5fa53b1e546e5b1ecbc7d38faab0f6045292302dc892cea')}
    for architecture,(kind,pin) in expected.items():
        parent=old['parents'][(architecture,SEED)]
        require(parent['decoder_kind']==kind and parent['checkpoint']['sha256']==pin,'exact same architecture clause parent required')
    targets={'new':loaded['document_tuning'],'atom_tuning':loaded['atom_documents']['old_tuning'],
      'atom_fresh':loaded['atom_documents']['old_fresh'],'prior_condition':loaded['prior_condition_documents']}
    return {**loaded,'config':config,'fixed_heads':heads,'modern_document_targets':targets,
      'modern_document_sources':{p:clauses.source_rows(rows) for p,rows in targets.items()}}


def generate_oracle_documents(decoder,plans,sources):
    require(len(plans)==len(sources) and all(p['status']=='planned' and p['source_plan'] is not None for p in plans),'supported-only supplied plans required')
    by_id={s['candidate_id']:s for s in sources}
    require(len(by_id)==len(sources) and {p['candidate_id'] for p in plans}==set(by_id),'complete unique oracle document identities required')
    for plan in plans:
        source=by_id[plan['candidate_id']]
        require(plan['source_sha256']==source['source_sha256']==boundary.text_sha(source['source_text'])
          and plan['source_plan']['source']==source,'oracle source identity, hash, or plan differs')
    adapted={'rows':[{'candidate_id':p['candidate_id'],'source_sha256':p['source_sha256'],
      'status':'planned','plan':p['source_plan'],'reason':None} for p in plans]}
    result=retention.generate_documents(decoder,adapted,sources)
    for row in result['rows']:row.update(segmentation_learned=False,supplied_oracle_segmentation=True)
    return {**result,'segmentation_learned':False,'supplied_oracle_segmentation':True,'references_supplied':True,
      'target_access_scope':'canonical_semantics_only',
      'supplied_supported_eligibility':True,'semantic_targets_supplied':False,
      'assistance':'Exact clause intervals and supported eligibility supplied by authored reference; semantic labels withheld.'}


def evaluate_tuning(decoder,job,folder,stem):
    result=legacy.evaluate_tuning(decoder,{**job['legacy'],'boundaries':job['legacy_boundaries']},folder,stem)
    for label,targets in (('new_single',job['new_tuning']),('prior_condition',job['prior_condition_targets'])):
        sources=source_rows(targets);generation=generate(decoder,sources);metrics=clause_metrics(generation,sources,targets)
        result[label]=write(folder/f'{stem}-{label}.json',{'generation':generation,'metrics':metrics})
        result[label+'_metrics']=metrics
    result['old_atom_oracle_metrics']={};result['oracle_document_metrics']={};result['fixed_document_metrics']={}
    for panel in DOC_PANELS:
        sources=source_rows(job['oracle_sources'][panel]);targets=job['oracle_targets'][panel]
        generation=generate(decoder,sources);metrics=clause_metrics(generation,sources,targets)
        result['oracle_clauses_'+panel]=write(folder/f'{stem}-oracle-clauses-{panel}.json',{'generation':generation,'metrics':metrics})
        if panel.startswith('atom_'):result['old_atom_oracle_metrics'][panel]=metrics
        generation=generate_oracle_documents(decoder,job['oracle_boundaries'][panel],job['oracle_document_sources'][panel])
        targets=[r for r in job['modern_document_targets'][panel] if r['supported']]
        metrics=document_metrics(generation,targets);result['oracle_document_metrics'][panel]=metrics
        result['oracle_documents_'+panel]=write(folder/f'{stem}-oracle-documents-{panel}.json',{'generation':generation,'metrics':metrics})
        result['fixed_document_metrics'][panel]={}
        for policy in POLICIES:
            generation=retention.generate_documents(decoder,job['fixed_boundaries'][policy][panel],job['modern_document_sources'][panel])
            metrics=document_metrics(generation,job['modern_document_targets'][panel]);result['fixed_document_metrics'][panel][policy]=metrics
            result['fixed_documents_'+panel+'_'+policy]=write(folder/f'{stem}-fixed-documents-{panel}-{policy}.json',{'generation':generation,'metrics':metrics})
    return result


def fit_job(job):
    started=time.monotonic()
    import torch
    torch.set_num_threads(1)
    folder=Path(job['folder']);folder.mkdir()
    parent=runtime._parent_runtime(job['parent_kind']).load_checkpoint(job['parent']['path'],expected_sha256=job['parent']['sha256'])
    require(parent['model_config']['seed']==SEED and parent['model_config']['trigger_enabled'] is job['enabled'],'same-seed architecture required')
    arguments=(job['legacy']['training'],job['runtime_tuning'],job['legacy']['runtime_pairs'],job['aux_rows'],job['aux_pairs'],job['aux_blocks'])
    checkpoint=runtime.build_checkpoint(parent,*arguments,parent_kind=job['parent_kind'],objective=job['objective'],seed=SEED)
    require(checkpoint['model_state']==parent['model_state'] and runtime.optimizer_steps(checkpoint)==0 and not checkpoint['optimizer_state']['parameters'],'exact pretrained tensors and fresh optimizer required')
    initial=runtime.save_checkpoint(checkpoint,folder/'initial-checkpoint.json')
    sources=source_rows(job['new_tuning']);generation=generate(runtime.RoleSpanRehearsalDecoder(checkpoint),sources)
    parent_generation=read_ref(job['parent_metrics']['new_single'])['generation']
    require(generation['rows']==parent_generation['rows'],'all192 initial clause predictions/logits must equal parent')
    initialization=write(folder/'initialization.json',{'parent':job['parent'],'parent_kind':job['parent_kind'],'initial':initial,
      'initial_model_state_sha256':digest(checkpoint['model_state']),'parent_model_state_sha256':digest(parent['model_state']),
      'all_initial_tensors_equal':True,'optimizer_reset':True,'historical_optimizer_resumed':False,
      'parity_panel':'new_single','parity_count':192,'generation':generation,'all_parity_numerical_predictions_equal':True,
      'full_legacy_initial_replay_performed':False})
    stages=[]
    for target in STAGES:
        before=digest(checkpoint)
        result=runtime.train_decoder(checkpoint,*arguments,max_steps=target-runtime.optimizer_steps(checkpoint),max_seconds=min(600.,max(0.,1800-(time.monotonic()-started))))
        checkpoint=result['checkpoint'];steps=runtime.optimizer_steps(checkpoint)
        require(steps==target,'every trial must complete exact200 updates')
        stage={'steps':steps,'checkpoint':runtime.save_checkpoint(checkpoint,folder/f'checkpoint-{steps}.json'),
          'previous_checkpoint_sha256':before,'training_report':write(folder/f'training-{steps}.json',result['report']),
          **evaluate_tuning(runtime.RoleSpanRehearsalDecoder(checkpoint),job,folder,f'stage-{steps}')}
        stage.update(gates(stage,job['parent_metrics']));stages.append(stage)
        require(time.monotonic()-started<=1800,'complete trial wall budget exceeded')
        print(json.dumps({'phase':'trained_stage','architecture':job['architecture'],'objective':job['objective'],'steps':steps,
          'eligible':stage['eligible'],'new_single_exact':stage['new_single_metrics']['fullrule_exact'],
          'new_oracle_joint':stage['oracle_document_metrics']['new']['joint_exact'],'failures':stage['failures']}),flush=True)
    chosen=select_stage(stages,job['parent_metrics'])
    name=f"{job['objective']}_{job['architecture']}-{SEED}"
    trial={'name':name,'arm':f"{job['objective']}_{job['architecture']}",'objective':job['objective'],'architecture':job['architecture'],
      'seed':SEED,'enabled':job['enabled'],'decoder_kind':'role_span_rehearsal' if chosen else job['parent_kind'],
      'checkpoint':chosen['checkpoint'] if chosen else job['parent'],'selection':'candidate' if chosen else 'parent_fallback_no_acceptable_replacement',
      'selected_steps':chosen['steps'] if chosen else 0,'executed_steps':200,'parent':job['parent'],'parent_kind':job['parent_kind'],
      'parent_tuning':job['parent_metrics'],'initialization':initialization,'initial_checkpoint':initial,'stages':stages,
      'trial_wall_seconds':time.monotonic()-started,'trial_wall_limit_seconds':1800,'historical_optimizer_resumed':False,
      'fresh_targets_opened':False,**FALSE}
    return {**trial,'selection_record':write(folder/'selection.json',trial)}


def audit_trials(trials):
    require(len(trials)==4 and {(t['objective'],t['architecture']) for t in trials}=={(o,a) for o in OBJECTIVES for a in ARCHITECTURES},'four matched trials required')
    audit=[]
    for trial in trials:
        rows=[r for stage in trial['stages'] for r in read_ref(stage['training_report'])['batch_exposures']]
        require([r['optimizer_step'] for r in rows]==list(range(1,201)),'exact200 ordered receipts required')
        counts=read_ref(trial['initial_checkpoint'])['pool_counts']
        audit.append({'name':trial['name'],'architecture':trial['architecture'],'objective':trial['objective'],'parent':trial['parent'],
          'updates':len(rows),'batch_exposures_sha256':digest(rows),'main_draws':sum(len(r['ids']) for r in rows),
          'auxiliary_draws':sum(len(r['auxiliary_ids']) for r in rows),'unique_main_ids':len({i for r in rows for i in r['ids']}),
          'unique_auxiliary_ids':len({i for r in rows for i in r['auxiliary_ids']}),
          'pool_coverage':{p:{'entries':n,'draws':sum(len(r['indices_by_pool'][p]) for r in rows),
          'unique_entries':len({i for r in rows for i in r['indices_by_pool'][p]})} for p,n in counts.items()}})
    require(len({r['batch_exposures_sha256'] for r in audit})==1,'all architectures/objectives must use identical main and auxiliary batches')
    return audit


def model_inventory(trials,parents):
    models=list(trials)
    for architecture in ARCHITECTURES:
        parent=parents[(architecture,SEED)]
        models.append({'name':f'parent_{architecture}-{SEED}','arm':'parent_'+architecture,'architecture':architecture,'objective':'parent',
          'seed':SEED,'enabled':architecture=='grounding','decoder_kind':parent['decoder_kind'],'checkpoint':parent['checkpoint'],
          'parent':parent['checkpoint'],'selection':'unchanged_parent','selected_steps':0,'executed_steps':0})
    for trial in trials:
        models.append({k:v for k,v in {**trial,'name':trial['name']+'_final200','checkpoint':trial['stages'][-1]['checkpoint'],
          'decoder_kind':'role_span_rehearsal','selection':'unselected_final200_diagnostic','selected_steps':200,
          'challenge_diagnostics_used_for_selection':False}.items() if k not in ('stages','parent_tuning','initialization','initial_checkpoint','selection_record')})
    require(len(models)==len({m['name'] for m in models})==10,'all ten logical clause slots required')
    return sorted(models,key=lambda m:m['name'])


def generation_job(job):
    import torch
    torch.set_num_threads(1);model=job['model'];decoder=load_decoder(model['checkpoint'],model['decoder_kind'])
    folder=Path(job['folder']);folder.mkdir(exist_ok=True)
    singles={p:write(folder/f'{p}-generation.json',generate(decoder,rows)) for p,rows in job['sources'].items()}
    oracle={p:write(folder/f'oracle-documents-{p}.json',generate_oracle_documents(decoder,job['oracle_boundaries'][p],rows))
      for p,rows in job['oracle_document_sources'].items()}
    documents={model['name']+'__boundary_'+policy:{p:write(folder/f'documents-{policy}-{p}.json',
      retention.generate_documents(decoder,job['fixed_boundaries'][policy][p],rows)) for p,rows in job['document_sources'].items()} for policy in POLICIES}
    training={}
    if model['objective']=='parent' or model['name'].endswith('_final200'):
        training={p:write(folder/f'training-{p}-diagnostic.json',generate(decoder,rows)) for p,rows in job['training_sources'].items()}
    print(json.dumps({'phase':'generated','model':model['name'],'selection':model['selection'],'training_diagnostic_rows':sum(len(v) for v in job['training_sources'].values()) if training else 0}),flush=True)
    return model['name'],singles,oracle,documents,training


def run(args):
    import torch
    from scripts.ops.legal_ir import prepare_legal_role_span_rehearsal_corpus as corpus
    torch.set_num_threads(1)
    require(type(args.workers) is int and 1<=args.workers<=3,'one to three CPU workers required')
    inputs=load_config(args.config);old=inputs['legacy'];output=Path(args.output).resolve();output.mkdir(parents=True,exist_ok=False)
    pins={str(Path(m.__file__).resolve()):sha(m.__file__) for m in (runtime,legacy,retention,boundary_runtime,boundary,clauses,clauses.compose,corpus,sys.modules[__name__])}
    plan=write(output/'plan.json',{'schema':SCHEMA,'config':ref(args.config),'study_design':inputs['config']['study_design'],
      'producer_pins':pins,'objectives':list(OBJECTIVES),'architectures':list(ARCHITECTURES),'seed':SEED,'stages':list(STAGES),
      'total_optimizer_updates':800,'updates_per_trial':200,'main_training_rows':4080,'auxiliary_rows':576,'main_batch_size':12,'auxiliary_batch_size':4,
      'main_inventory_cap_unchanged':4096,'auxiliary_inventory_cap':1024,'common_auxiliary_standard_ce_weight':.25,
      'role_rehearsal_weight':{'base':0.,'role_rehearsal':.5},'optimizer':'fresh_Adam','learning_rate':.00025,
      'trial_wall_limit_seconds':1800,'trial_budget_includes_initialization_and_stage_evaluation':True,
      'fixed_boundary_heads':inputs['fixed_heads'],'boundary_training':False,'joint_stage_search':False,
      'initial_parity_rows':768,'postselection_training_diagnostic_rows':27936,'native_fresh_logical_slots':40,
      'oracle_supported_eligibility_and_exact_boundaries_supplied':True,'oracle_rejection_metric_claimed':False,
      'inference_changed':False,'latent_dimension':0,'fresh_targets_opened':False,**FALSE})
    legacy_boundaries={};legacy_refs={}
    for policy,name in (('parent','parent'),('expanded','expanded-1730')):
        decoder=boundary.ClauseBoundaryDecoder(read_ref(old['boundary_heads'][name]['checkpoint']))
        legacy_boundaries[policy]={p:clauses.decode_all(decoder,old['document_sources'][p]) for p in legacy.DOCUMENT_TUNING_PANELS}
        legacy_refs[policy]={p:write(output/f'legacy-{policy}-{p}-boundaries.json',g) for p,g in legacy_boundaries[policy].items()}
    fixed_boundaries={};boundary_refs={}
    for policy,head in inputs['fixed_heads'].items():
        decoder=boundary_runtime.AtomBoundaryDecoder(read_ref(head)) if policy=='distill' else boundary.ClauseBoundaryDecoder(read_ref(head))
        fixed_boundaries[policy]={p:clauses.decode_all(decoder,rows) for p,rows in inputs['modern_document_sources'].items()}
        boundary_refs[policy]={p:write(output/f'{policy}-{p}-boundaries.json',g) for p,g in fixed_boundaries[policy].items()}
    shared={**inputs,'legacy_boundaries':legacy_boundaries,'fixed_boundaries':fixed_boundaries}
    parents={}
    for architecture in ARCHITECTURES:
        parent=old['parents'][(architecture,SEED)]
        parents[architecture]=evaluate_tuning(load_decoder(parent['checkpoint'],parent['decoder_kind']),shared,output,'parent-'+architecture)
        print(json.dumps({'phase':'parent_tuning','architecture':architecture,'new_single_exact':parents[architecture]['new_single_metrics']['fullrule_exact'],
          'new_oracle_joint':parents[architecture]['oracle_document_metrics']['new']['joint_exact']}),flush=True)
    parent_ref=write(output/'parent-tuning.json',parents)
    jobs=[{**shared,'objective':o,'architecture':a,'enabled':a=='grounding','parent':old['parents'][(a,SEED)]['checkpoint'],
      'parent_kind':old['parents'][(a,SEED)]['decoder_kind'],'parent_metrics':parents[a],'folder':str(output/f'{o}_{a}-{SEED}')} for o in OBJECTIVES for a in ARCHITECTURES]
    trials=[]
    with ProcessPoolExecutor(max_workers=args.workers,mp_context=multiprocessing.get_context('spawn')) as pool:
        for future in as_completed([pool.submit(fit_job,j) for j in jobs]):trials.append(future.result())
    trials.sort(key=lambda t:t['name']);audit=audit_trials(trials)
    primary={}
    for architecture in ARCHITECTURES:
        candidates=[(t,s) for t in trials if t['architecture']==architecture for s in t['stages'] if s['eligible']]
        chosen=max(candidates,key=lambda item:(*ranking(item[1]),-OBJECTIVES.index(item[0]['objective']))) if candidates else None
        primary[architecture]={'model':chosen[0]['name'] if chosen else f'parent_{architecture}-{SEED}',
          'steps':chosen[1]['steps'] if chosen else 0,'selection':'candidate' if chosen else 'parent_fallback_no_acceptable_replacement'}
    selections=write(output/'selections-frozen.json',{'trials':trials,'parent_tuning':parent_ref,'trial_update_audit':audit,'primary_choices':primary,
      'executed_optimizer_updates':800,'fresh_targets_opened':False,'fresh_oracle_inputs_opened':False,**FALSE})
    models=model_inventory(trials,old['parents']);heads=write(output/'models-frozen.json',models)
    # The external audit guard releases only the four source/interval oracle packs after this immutable selection exists.
    if hasattr(args,'release_evaluation_sources'):args.release_evaluation_sources(selections)
    fresh=corpus.load_evaluation_sources(inputs['config']['corpus_manifest']['path'])
    sources={**{'legacy_'+p:rows for p,rows in old['sources'].items()},'new':source_rows(inputs['new_tuning']),'fresh':source_rows(fresh['fresh_sources'])}
    oracle_sources={**inputs['oracle_sources'],'fresh':fresh['oracle_sources']}
    oracle_sources={p:source_rows(rows) for p,rows in oracle_sources.items()}
    sources.update({'oracle_'+p:rows for p,rows in oracle_sources.items()})
    docs={**inputs['modern_document_sources'],'fresh':fresh['fresh_document_sources']}
    oracle_docs={**inputs['oracle_document_sources'],'fresh':fresh['oracle_document_sources']}
    oracle_plans={**inputs['oracle_boundaries'],'fresh':fresh['oracle_boundaries']}
    occurrences={**inputs['oracle_occurrences'],'fresh':fresh['oracle_occurrences']}
    for policy,head in inputs['fixed_heads'].items():
        decoder=boundary_runtime.AtomBoundaryDecoder(read_ref(head)) if policy=='distill' else boundary.ClauseBoundaryDecoder(read_ref(head))
        fixed_boundaries[policy]['fresh']=clauses.decode_all(decoder,docs['fresh'])
        boundary_refs[policy]['fresh']=write(output/f'{policy}-fresh-boundaries.json',fixed_boundaries[policy]['fresh'])
    training_sources={'main':source_rows(old['training']),'auxiliary':source_rows(inputs['aux_rows'])}
    source_ref=write(output/'source-inputs.json',sources);doc_ref=write(output/'document-source-inputs.json',docs)
    oracle_doc_ref=write(output/'oracle-document-source-inputs.json',oracle_docs)
    oracle_source_ref=write(output/'oracle-clause-source-inputs.json',oracle_sources)
    oracle_plan_ref=write(output/'oracle-boundary-inputs.json',oracle_plans);occurrence_ref=write(output/'oracle-occurrences.json',occurrences)
    training_source_ref=write(output/'training-source-inputs.json',training_sources)
    files={};oracle_files={};document_files={};training_files={}
    jobs=[{'model':m,'sources':sources,'oracle_document_sources':oracle_docs,'oracle_boundaries':oracle_plans,
      'fixed_boundaries':fixed_boundaries,'document_sources':docs,'training_sources':training_sources,'folder':str(output/m['name'])} for m in models]
    with ProcessPoolExecutor(max_workers=args.workers,mp_context=multiprocessing.get_context('spawn')) as pool:
        for future in as_completed([pool.submit(generation_job,j) for j in jobs]):
            name,single,oracle,documents,training=future.result();files[name]=single;oracle_files[name]=oracle;document_files.update(documents)
            if training:training_files[name]=training
    pipelines=[{'name':m['name']+'__boundary_'+p,'source_model_name':m['name'],'boundary_policy':p,
      'boundary_checkpoint':inputs['fixed_heads'][p],'architecture':m['architecture'],'objective':m['objective'],
      'selection':m['selection'],'selected_steps':m['selected_steps'],'checkpoint':m['checkpoint'],'decoder_kind':m['decoder_kind']} for m in models for p in POLICIES]
    require(all(sha(p)==h for p,h in pins.items()) and load_config(args.config)==inputs,'configuration, source, or implementation drift')
    require(len(document_files)==20 and len(files)==len(oracle_files)==10 and len(training_files)==6,'all logical slots including duplicate fallbacks required')
    frozen={'schema':SCHEMA,'config':ref(args.config),'plan':plan,'sources':source_ref,'document_sources':doc_ref,
      'oracle_sources':oracle_source_ref,'oracle_document_sources':oracle_doc_ref,'oracle_boundaries':oracle_plan_ref,
      'oracle_occurrences':occurrence_ref,'training_sources':training_source_ref,'boundaries':boundary_refs,'legacy_boundaries':legacy_refs,
      'parent_tuning':parent_ref,'selections':selections,'heads':heads,'models':models,'files':files,'oracle_files':oracle_files,
      'document_files':document_files,'training_files':training_files,'pipelines':pipelines,'primary_choices':primary,
      'all_training_selection_and_generation_complete':True,'executed_optimizer_updates':800,'fresh_targets_opened':False,
      'fresh_oracle_inputs_opened_after_selection':True,'parent_fallbacks':[t['name'] for t in trials if t['selection']!='candidate'],**FALSE}
    write(output/'generation-frozen.json',frozen)
    print(json.dumps({'phase':'frozen','models':10,'pipelines':20,'updates':800,'primary_choices':primary}),flush=True)
    return frozen


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--config',required=True);parser.add_argument('--output',required=True)
    parser.add_argument('--workers',type=int,default=3);run(parser.parse_args())


if __name__=='__main__':main()
