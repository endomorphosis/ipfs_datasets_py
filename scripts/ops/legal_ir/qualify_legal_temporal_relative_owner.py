#!/usr/bin/env python3
"""Independent pointer inventory, source-only replay and released scoring.

Fresh references are released only after exact saved-output replay and complete
admitted tuning reconciliation. Source intervals are proposals, not legal proof.
"""
from __future__ import annotations
import argparse
from collections import Counter
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys

os.environ['CUDA_VISIBLE_DEVICES']='-1'
os.environ['OMP_NUM_THREADS']='1'
os.environ['OPENBLAS_NUM_THREADS']='1'
sys.path.insert(0,str(Path(__file__).resolve().parents[3]))
from ipfs_datasets_py.logic.autoformal import legal_temporal_relative_owner_metrics as metrics
from ipfs_datasets_py.logic.autoformal import legal_temporal_ownership_metrics as types
from scripts.ops.legal_ir import run_legal_temporal_relative_owner as runner

SCHEMA='legal-temporal-relative-owner-independent-qualification/v1'
ARMS=('source_pointer','relative_position','relative_norm_contrast')
SEEDS=(1730,1731)
STEPS=(0,100,200)
PANELS=('fresh_lexical','fresh_structural')
CALIBRATION_PANELS=('calibration_lexical','calibration_structural')
ALL_PANELS=CALIBRATION_PANELS+PANELS
FRESH_SEALED=('fresh_lexical_targets','fresh_structural_targets','fresh_annotation_ledger','exposure_audit')
CALIBRATION_SEALED=('calibration_lexical_targets','calibration_structural_targets','calibration_annotation_ledger','calibration_exposure_audit')
SEALED=CALIBRATION_SEALED+FRESH_SEALED
require=metrics.require


def wire(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(wire(value)).hexdigest()


def corpus_digest(value):
    """Corpus wire uses literal UTF8; model/protocol hashes retain ASCII JSON."""
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()).hexdigest()


def ref(path):
    p=Path(path).resolve();b=p.read_bytes()
    return {'path':str(p),'sha256':hashlib.sha256(b).hexdigest(),'bytes':len(b)}


def validate_ref(pin):
    require(type(pin) is dict and set(pin)=={'path','sha256','bytes'} and type(pin['path']) is str and
            Path(pin['path']).is_absolute() and type(pin['sha256']) is str and
            re.fullmatch('[0-9a-f]{64}',pin['sha256']) is not None and
            type(pin['bytes']) is int and pin['bytes']>=0,'closed immutable byte reference required')
    require(wire(ref(pin['path']))==wire(pin),'saved bytes changed')


def read(pin):
    validate_ref(pin)
    def pairs(items):
        value={}
        for k,v in items:
            require(k not in value,'duplicate JSON key');value[k]=v
        return value
    return json.loads(Path(pin['path']).read_bytes(),object_pairs_hook=pairs,
                      parse_constant=lambda _:(_ for _ in ()).throw(ValueError('nonfinite JSON')))


def write(path,value):
    p=Path(path);p.parent.mkdir(parents=True,exist_ok=True)
    with p.open('x') as f:json.dump(value,f,sort_keys=True,indent=2,allow_nan=False);f.write('\n')
    return ref(p)


def producers():
    paths=set(runner.producer_pins())|{str(Path(__file__).resolve()),metrics.__file__,metrics.previous.__file__,metrics.previous.previous.__file__,types.__file__}
    return [ref(p) for p in sorted(paths)]


def phase_guard(manifest):
    stages={stage:{str(Path(manifest['artifacts'][k]['path']).resolve()) for k in keys} for stage,keys in
            (('calibration',CALIBRATION_SEALED),('fresh',FRESH_SEALED))}
    paths=stages['calibration']|stages['fresh']
    require(len(paths)==8,'eight distinct staged semantic reference paths required')
    state={'sealed_paths':sorted(paths),'stage_paths':{k:sorted(v) for k,v in stages.items()},'released_stages':[],
           'released':False,'premature_read_attempts':[],'postrelease_reads':[]}
    def hook(event,args):
        if event!='open' or not args or not isinstance(args[0],(str,bytes,os.PathLike)):return
        path=str(Path(os.fsdecode(args[0])).resolve())
        if path in paths:
            stage=next(k for k,v in stages.items() if path in v)
            if stage not in state['released_stages']:
                state['premature_read_attempts'].append(path);raise PermissionError(stage+' references remain sealed')
            state['postrelease_reads'].append({'stage':stage,'path':path})
    sys.addaudithook(hook);return state


def release_stage(guard,stage):
    require(stage in ('calibration','fresh') and stage not in guard['released_stages'] and
            (stage=='calibration' or guard['released_stages']==['calibration']), 'ordered distinct reference releases required')
    require(not guard['premature_read_attempts'],'premature staged reference access')
    guard['released_stages'].append(stage);guard['released']=stage=='fresh'


def load_inputs(freeze):
    config=read(freeze['config']);manifest=read(config['corpus_manifest']);guard=phase_guard(manifest)
    cfg,pin,data=runner.load_config(freeze['config']['path'])
    require(wire(cfg)==wire(config) and pin==freeze['config'],'configuration changed during admission')
    return cfg,data,guard


def source_projection(rows):
    return [{k:r[k] for k in metrics.SOURCE_KEYS} for r in rows]


def target_map(rows):
    require(type(rows) is list and len({r['id'] for r in rows})==len(rows),'unique complete references required')
    return {r['id']:{'label':r['label'],'owner_anchor_span':r['owner_anchor_span']} for r in rows}


def check_source_inventory(rows):
    require(type(rows) is list and 1<=len(rows)<=4096,'bounded nonempty source inventory required')
    identities=[]
    for row in rows:
        types.validate_source(row)
        identities.append((row['source_sha256'],row['proposed_time_span']['char_start'],row['proposed_time_span']['char_end']))
    require(len({r['id'] for r in rows})==len(rows)==len(set(identities)),'duplicate source query occurrence')


def check_generation(value,checkpoint,sources_pin,sources,kind):
    fields={'schema','checkpoint','decoder_kind','sources','rows','encoder_batch_forwards','encoder_source_evaluations',
            'source_only_input','reference_anchors_supplied','labels_supplied','pipeline_promotion','statutory_semantics_verified'}
    require(type(value) is dict and set(value)==fields and value['schema']=='legal-temporal-relative-owner-generation/v1',
            'closed source generation required')
    require(wire(value['checkpoint'])==wire(checkpoint) and wire(value['sources'])==wire(sources_pin) and
            value['decoder_kind']==kind and kind in ('relative_owner','parent_coupled'),'generation checkpoint/source/kind mismatch')
    require(value['source_only_input'] is True and all(value[k] is False for k in
            ('reference_anchors_supplied','labels_supplied','pipeline_promotion','statutory_semantics_verified')),'inference authority/input flags differ')
    require(type(value['encoder_batch_forwards']) is int and value['encoder_batch_forwards']==math.ceil(len(sources)/48) and
            type(value['encoder_source_evaluations']) is int and value['encoder_source_evaluations']==len(sources),'actual generation counters differ')
    require(type(value['rows']) is list and len(value['rows'])==len(sources) and
            [r['id'] for r in value['rows']]==[s['id'] for s in sources],'complete ordered query join required')
    for source,row in zip(sources,value['rows']):
        metrics.checked_prediction(source,row)
        require(set(row)==(metrics.PREDICTION_KEYS if kind=='relative_owner' else metrics.previous.PREDICTION_KEYS),
                'decoder kind and prediction wire differ')
    return value['rows']


def independent_selection(stages):
    require(type(stages) is dict and set(stages)==set(STEPS) and all(type(k) is int for k in stages),'three prospective stages required')
    ranking={}
    for step,score in stages.items():
        require(type(score['count']) is int and score['count']==288 and type(score['joint_correct']) is int and
                0<=score['joint_correct']<=288 and type(score['selection_nll']) in (int,float) and
                math.isfinite(score['selection_nll']) and score['selection_nll']>=0,'bounded tuning score required')
        ranking[step]=(-score['joint_correct'],score['selection_nll'],step)
    return {'selected_steps':min(ranking,key=ranking.__getitem__),'ranking':{str(s):list(ranking[s]) for s in STEPS},
            'selection_panel':'unchanged_placement_tuning','retention_gates_applied':False,'fresh_results_used':False}


def check_checkpoint(pin,*,kind,parent_pin=None,arm=None,seed=None,step=None,previous=None):
    cp=read(pin)
    if kind=='parent_coupled':
        require(cp['schema']=='legal-temporal-coupled-span-checkpoint/v1' and
                cp['config']['arm']=='joint_span' and cp['config']['seed']==seed and
                cp['optimizer_steps']==200 and cp['cumulative_owner_head_updates']==900 and
                pin['sha256']==runner.PARENTS[seed], 'parent pointer physical metadata differs')
    else:
        require(cp['schema']=='legal-temporal-relative-owner-checkpoint/v1' and cp['config']['arm']==arm and
                cp['config']['seed']==seed and type(cp['optimizer_steps']) is int and cp['optimizer_steps']==step and
                cp['cumulative_owner_head_updates']==900+step and cp['parent_owner_head_updates']==900,'coupled checkpoint metadata differs')
        require(cp['parent_file_sha256']==parent_pin['sha256'] and wire(cp['parent'])==wire(read(parent_pin)) and
                cp['parent_payload_sha256']==digest(cp['parent']),'exact warm parent binding differs')
        require(cp['preceding_checkpoint_sha256']==(None if previous is None else digest(previous)),'stage predecessor differs')
        require(cp['implementation']==runner.runtime.producer_pins() and all(cp[k] is False for k in runner.runtime.FALSE),
                'checkpoint implementation/authority differs')
    return cp


def inventory(freeze,data,config):
    require(freeze['schema']==runner.SCHEMA and freeze['producer_pins']==runner.producer_pins() and
            freeze['all_training_selection_and_generation_complete'] is True and
            freeze['optimizer_updates']==1200 and freeze['supervised_query_draws']==28800,
            'complete frozen experiment required')
    for k in ('pipeline_promotion','latent_input_enabled','statutory_semantics_verified'):require(freeze[k] is False,'authority escalation')
    require(freeze['fresh_reference_guard']['released'] is False and not freeze['fresh_reference_guard']['premature_read_attempts'],
            'producer opened current references')
    initial=read(freeze['initialization']);selection=read(freeze['selections'])
    require(initial['config']==selection['config']==freeze['config'] and selection['initialization']==freeze['initialization'] and
            initial['parents']==config['parents'] and initial['producer_pins']==runner.producer_pins() and
            initial['optimizer_updates']==0 and selection['fresh_results_used'] is False and selection['calibration_results_used'] is False,'initial/selection provenance differs')
    expected_seals=sorted(str(Path(data['manifest']['artifacts'][k]['path']).resolve()) for k in SEALED)
    for value in (freeze,initial,selection,*selection['trials']):
        guard=value['fresh_reference_guard']
        require(guard['released'] is False and guard['premature_read_attempts']==[] and guard['sealed_paths']==expected_seals,
                'producer phase seal differs')
    names={f'{arm}-{seed}' for arm in ARMS for seed in SEEDS}
    require(set(initial['models'])==names and len(selection['trials'])==len(selection['trial_files'])==6,'six trials required')
    require(wire([read(p) for p in selection['trial_files']])==wire(selection['trials']),'trial file inventory differs')
    trials={r['name']:r for r in selection['trials']};require(set(trials)==names,'trial identity differs')
    targets={'training':data['training'],'tuning':data['tuning'],**data['retention_targets']}
    expected_sources={k:source_projection(v) for k,v in targets.items()}
    expected_sources.update({p:data[p+'_sources'] for p in ALL_PANELS})
    if config['diagnostic_sources'] is not None:expected_sources['statutory_diagnostics']=read(config['diagnostic_sources'])
    require(set(freeze['sources'])==set(expected_sources),'source panel omission/addition')
    sources={k:read(p) for k,p in freeze['sources'].items()}
    for k,rows in sources.items():
        check_source_inventory(rows);require(wire(rows)==wire(expected_sources[k]),'source panel changed: '+k)
    references=[freeze['config'],freeze['initialization'],freeze['selections'],*selection['trial_files'],*freeze['sources'].values()]
    for seed in SEEDS:check_checkpoint(config['parents'][str(seed)],kind='parent_coupled',seed=seed)
    for name,trial in trials.items():
        arm,seed=trial['arm'],trial['seed'];require(name==f'{arm}-{seed}' and arm in ARMS and seed in SEEDS,'trial metadata differs')
        require([r['steps'] for r in trial['stages']]==list(STEPS) and len(trial['training_reports'])==2 and
                trial['fresh_results_used'] is False and trial['calibration_results_used'] is False and not trial['fresh_reference_guard']['premature_read_attempts'],'stage/receipt inventory differs')
        prior_cp=None
        for stage in trial['stages']:
            cp=check_checkpoint(stage['checkpoint'],kind='relative_owner',parent_pin=config['parents'][str(seed)],arm=arm,seed=seed,
                                step=stage['steps'],previous=prior_cp)
            if stage['steps']==0:
                require(stage['checkpoint']==initial['models'][name] and cp['optimizer_state']['parameters']=={} and
                        cp['initial_state_sha256']==digest(cp['model_state']),'initial state/fresh optimizer differs')
            require(cp['manifests']=={'training':{'sha256':digest(data['training']),'count':3360},
                                      'tuning':{'sha256':digest(data['tuning']),'count':288},
                                      'training_contrasts':{'sha256':digest(data['training_other_norm_contrasts']),'count':3360}},'checkpoint data manifests differ')
            references.extend((stage['checkpoint'],stage['tuning_generation']))
            check_generation(read(stage['tuning_generation']),stage['checkpoint'],freeze['sources']['tuning'],sources['tuning'],'relative_owner')
            prior_cp=cp
        for index,pin in enumerate(trial['training_reports']):
            report=read(pin);references.append(pin)
            require(report['schema']==runner.runtime.REPORT_SCHEMA and report['initial_step']==100*index and
                    report['final_step']==100*(index+1) and report['steps_executed']==len(report['trace'])==100 and
                    [r['step'] for r in report['trace']]==list(range(100*index+1,100*(index+1)+1)),
                    'full ordered training report changed')
        selected=[s for s in trial['stages'] if s['steps']==trial['selected_steps']]
        require(len(selected)==1 and selected[0]['checkpoint']==trial['selected_checkpoint'],'selected checkpoint differs')
    for seed in SEEDS:
        initial_cps=[read(initial['models'][f'{a}-{seed}']) for a in ARMS]
        require(len({digest(cp['model_state']) for cp in initial_cps})==1,'matched arm initial tensors differ')
    expected=[]
    def slot(name,role,trial,checkpoint,panel,kind):
        key=hashlib.sha256(json.dumps([checkpoint['sha256'],freeze['sources'][panel]['sha256'],kind]).encode()).hexdigest()
        expected.append({'slot':name,'role':role,'trial':trial,'panel':panel,'checkpoint':checkpoint,'decoder_kind':kind,'generation_key':key})
    for trial in selection['trials']:
        name=trial['name']
        for panel in (*data['retention_targets'],*ALL_PANELS):slot(name+'__selected','selected',name,trial['selected_checkpoint'],panel,'relative_owner')
        slot(name+'__final200','final200',name,trial['stages'][-1]['checkpoint'],'training','relative_owner')
        if 'statutory_diagnostics' in sources:slot(name+'__selected','selected',name,trial['selected_checkpoint'],'statutory_diagnostics','relative_owner')
    for seed in SEEDS:
        for panel in ('tuning',*data['retention_targets'],*ALL_PANELS):slot(f'parent-{seed}','parent',None,config['parents'][str(seed)],panel,'parent_coupled')
    logical=freeze['logical_generations'];require(len(logical)==len(expected),'logical slot omission')
    unique={}
    for actual,wanted in zip(logical,expected):
        require(set(actual)==set(wanted)|{'generation'} and wire({k:actual[k] for k in wanted})==wire(wanted),'logical alias metadata differs')
        key=actual['generation_key'];require(actual['generation']==freeze['physical_generations'][key],'logical/physical output binding differs')
        if key not in unique:unique[key]=actual
    require(set(unique)==set(freeze['physical_generations']) and len(unique)==freeze['final_generation_files'],'physical output inventory differs')
    for value in unique.values():
        references.extend((value['generation'],value['checkpoint']))
        check_generation(read(value['generation']),value['checkpoint'],freeze['sources'][value['panel']],sources[value['panel']],value['decoder_kind'])
    type_invariance=verify_type_invariance(freeze,trials,unique)
    # Every stage checkpoint and training report remains byte-bound at scoring,
    # even if it was never selected and did not produce held-out predictions.
    unique_refs={p['path']:p for p in references}
    require(all(unique_refs[p['path']]==p for p in references),'one path has inconsistent reference identities')
    return trials,sources,unique,{'authenticated_inputs':[unique_refs[k] for k in sorted(unique_refs)],
        'logical_output_slots':len(logical),'physical_output_files':len(unique),
        'physical_output_query_rows':sum(len(sources[v['panel']]) for v in unique.values()),
        'tuning_generations':18,'tuning_query_rows':5184,'training_optimizer_trajectory_replayed':False,'training_contrast_metadata_used_for_inference':False,'inherited_type_invariance':type_invariance}


def verify_type_invariance(freeze,trials,unique):
    parent={};comparisons=[]
    for slot in unique.values():
        if slot['decoder_kind']=='parent_coupled':
            seed=int(slot['slot'].split('-')[-1]);parent[(seed,slot['panel'])]=slot['generation']
    cache={}
    def projection(pin):
        if pin['sha256'] not in cache:
            cache[pin['sha256']]=[{k:r[k] for k in types.PREDICTION_KEYS} for r in read(pin)['rows']]
        return cache[pin['sha256']]
    def compare(pin,seed,panel,identity):
        reference=parent[(seed,panel)]
        actual=projection(pin);require(wire(actual)==wire(projection(reference)), 'frozen inherited type outputs changed: '+identity)
        comparisons.append({'generation':pin,'parent_generation':reference,'panel':panel,'rows':len(actual),'type_fields_exact':True})
    for name,trial in trials.items():
        for stage in trial['stages']:compare(stage['tuning_generation'],trial['seed'],'tuning',name+':'+str(stage['steps']))
    skipped=[]
    for slot in unique.values():
        if slot['decoder_kind']!='relative_owner':continue
        seed=trials[slot['trial']]['seed'];panel=slot['panel']
        if (seed,panel) in parent:compare(slot['generation'],seed,panel,slot['slot']+':'+panel)
        else:skipped.append({'generation':slot['generation'],'panel':panel,'reason':'no matching parent source generation; frozen parameter audit remains separate'})
    return {'comparisons':comparisons,'compared_query_rows':sum(v['rows'] for v in comparisons),
            'all_matching_type_fields_exact':True,'unpaired_generations':skipped,'additional_model_forwards':0}


def score_admitted(freeze,trials,sources,data):
    results={};choices={}
    for name,trial in trials.items():
        values={}
        for stage in trial['stages']:
            payload=read(stage['tuning_generation'])
            rows=check_generation(payload,stage['checkpoint'],freeze['sources']['tuning'],sources['tuning'],'relative_owner')
            value=metrics.score(sources['tuning'],rows,target_map(data['tuning']))
            require(wire({k:v for k,v in value.items() if k!='rows'})==wire(stage['tuning_metrics']),'admitted tuning score differs')
            values[stage['steps']]=value
        choice=independent_selection(values)
        require(choice['selected_steps']==trial['selected_steps'],'independent tuning selection differs')
        choices[name]=choice;results[name]={str(k):{n:v for n,v in score.items() if n!='rows'} for k,score in values.items()}
    return results,choices


def replay_jobs(unique):
    return {k:v for k,v in unique.items() if v['panel'] in (*ALL_PANELS,'statutory_diagnostics')}


def replay(freeze_path,output):
    freeze_pin=ref(freeze_path);freeze=read(freeze_pin);config,data,guard=load_inputs(freeze)
    trials,sources,unique,counts=inventory(freeze,data,config);jobs=replay_jobs(unique)
    rows={};batches=queries=0;decoder=None;loaded=None
    for key,slot in sorted(jobs.items(),key=lambda x:(x[1]['checkpoint']['sha256'],x[1]['decoder_kind'],x[0])):
        identity=(slot['checkpoint']['sha256'],slot['decoder_kind'])
        if identity!=loaded:
            cp=read(slot['checkpoint'])
            decoder=(runner.runtime.RelativeTemporalOwnerPointer(cp) if slot['decoder_kind']=='relative_owner' else
                     runner.runtime.parent.CoupledTemporalOwnerPointer(cp));loaded=identity
        source=sources[slot['panel']];actual=[]
        for start in range(0,len(source),48):actual.extend(decoder.predict_many(source[start:start+48]))
        expected=read(slot['generation'])['rows'];require(wire(actual)==wire(expected),'saved neural output differs on exact replay')
        queries+=len(source);batches+=math.ceil(len(source)/48)
        rows[key]={'generation':slot['generation'],'checkpoint':slot['checkpoint'],'sources':freeze['sources'][slot['panel']],
                   'decoder_kind':slot['decoder_kind'],'rows':len(source),'actual_rows_sha256':digest(actual),'exact_match':True}
        print(json.dumps({'phase':'replay','complete_files':len(rows),'source_queries':queries}),flush=True)
    require(not guard['premature_read_attempts'],'premature reference access')
    return write(output,{'schema':SCHEMA,'phase':'source_only_replay','generation_freeze':freeze_pin,'producer_files':producers(),
        'inventory':counts,'files':rows,'physical_files_replayed':len(rows),'encoder_batch_forwards':batches,
        'encoder_source_evaluations':queries,'all_saved_rows_match':True,'fresh_reference_guard':guard,
        'admitted_generations_numerically_replayed':False,'new_training_or_optimizer_updates':0,
        'scope':'Exact current calibration, fresh and real-diagnostic physical outputs only; parent baseline retains its full coordinate pointer and shares the joint-span selection metric.'})


def check_replay(freeze_pin,replayed,counts,jobs,freeze,sources,expected_guard):
    require(replayed['schema']==SCHEMA and replayed['phase']=='source_only_replay' and
            replayed['generation_freeze']==freeze_pin and replayed['producer_files']==producers() and
            replayed['inventory']==counts and replayed['all_saved_rows_match'] is True,
            'replay producer/input closure changed')
    require(replayed['fresh_reference_guard']['sealed_paths']==expected_guard['sealed_paths'] and
            replayed['fresh_reference_guard']['stage_paths']==expected_guard['stage_paths'] and
            replayed['fresh_reference_guard']['postrelease_reads']==[] and
            replayed['fresh_reference_guard']['released'] is False and
            not replayed['fresh_reference_guard']['premature_read_attempts'] and replayed['fresh_reference_guard']['released_stages']==[],'invalid source-only replay seal')
    expected={k:{'generation':s['generation'],'checkpoint':s['checkpoint'],'sources':freeze['sources'][s['panel']],
                   'decoder_kind':s['decoder_kind'],'rows':len(sources[s['panel']]),
                   'actual_rows_sha256':digest(read(s['generation'])['rows']),'exact_match':True} for k,s in jobs.items()}
    require(wire(replayed['files'])==wire(expected) and replayed['physical_files_replayed']==len(jobs) and
            replayed['encoder_source_evaluations']==sum(v['rows'] for v in expected.values()) and
            replayed['encoder_batch_forwards']==sum(math.ceil(v['rows']/48) for v in expected.values()),'replay inventory/counters differ')


def exact_span(text,value):
    require(type(value) is dict and set(value)=={'char_start','char_end','text'} and
            type(value['char_start']) is int and type(value['char_end']) is int and
            0<=value['char_start']<value['char_end']<=len(text) and
            text[value['char_start']:value['char_end']]==value['text'],'direct source-coordinate span differs')
    return {k:value[k] for k in ('char_start','char_end')}


def audit_mapping(targets,rich_rows):
    require(len(targets)==len(rich_rows) and len({r['id'] for r in targets})==len(targets),'complete unique reference mapping required')
    unique=ambiguous=norm_checks=0
    for target,row in zip(targets,rich_rows):
        source={k:row[k] for k in metrics.SOURCE_KEYS};types.validate_source(source)
        require(set(target)==metrics.SOURCE_KEYS|{'label','group_id','owner_anchor_span'} and
                wire({k:target[k] for k in metrics.SOURCE_KEYS})==wire(source) and target['label']==row['label'] and
                target['group_id']==row['group_id'],'reference source/label/group join differs')
        annotation=row['annotation'];items=annotation['owner_candidates'];identities=[]
        require(annotation.get('unique_owner_occurrence_asserted',annotation.get('unique_owner_asserted')) is (row['label']!='ambiguous'),
                'reference uniqueness assertion differs')
        for item in items:
            kind=item.get('owner_type',item.get('owner'));anchor=exact_span(row['source_text'],item['anchor_span'])
            require(kind in metrics.CLASSES[:3],'concrete reference type required');metrics.anchor_tokens(source,anchor)
            identities.append((kind,anchor['char_start'],anchor['char_end']))
            scope=exact_span(row['source_text'],item['scope_span'])
            require(scope['char_start']<=anchor['char_start']<anchor['char_end']<=scope['char_end'] and
                    scope['char_start']<=source['proposed_time_span']['char_start']<source['proposed_time_span']['char_end']<=scope['char_end'],
                    'reference enclosing extent must contain anchor and queried occurrence')
        require(len(set(identities))==len(identities),'duplicate reference anchor alternative')
        if row['label']=='ambiguous':
            ambiguous+=1;require(len(identities)>=2 and annotation.get('countermodels') is not None and target['owner_anchor_span'] is None,
                                  'ambiguity cannot arbitrarily select a reference anchor')
        else:
            unique+=1;require(len(identities)==1 and identities[0][0]==row['label'] and
                target['owner_anchor_span']==exact_span(row['source_text'],items[0]['anchor_span']),'unique exact anchor mapping differs')
            if row['label']=='norm' and 'norm_occurrences' in annotation:
                matches=[n for n in annotation['norm_occurrences'] if n['time_span'] is not None and
                         exact_span(row['source_text'],n['time_span'])==source['proposed_time_span']]
                require(len(matches)==1 and exact_span(row['source_text'],matches[0]['action_span'])==target['owner_anchor_span'],
                        'repeated norm time mapped to a different action occurrence')
                for key in ('actor_span','modal_span','clause_span'):exact_span(row['source_text'],matches[0][key])
                norm_checks+=1
        metrics.validate_target(source,{k:target[k] for k in metrics.TARGET_KEYS})
    return {'queries':len(targets),'unique_exact_anchors':unique,'ambiguous_nulls':ambiguous,
            'explicit_norm_time_action_joins':norm_checks,'gold_filtered_candidates_used_for_inference':False,
            'semantic_owner_inventory_complete':False,'independent_legal_gold':False}


def body_layout(row):
    text=row['source_text'];a=row['annotation'];intervals=[];pieces=[]
    heading=exact_span(text,a['heading_span']);require(heading['char_start']==0,'source-prefix heading required')
    cursor=heading['char_end'];aliases={'action_object':'action','condition_anchor':'condition_predicate','exception_anchor':'exception_predicate'}
    for item in a.get('source_role_spans',a.get('lexical_spans',[])):
        require(set(item)=={'role','span'},'closed declared lexical role required')
        role=aliases.get(item['role'],item['role']);require(role in ('actor','action','condition_predicate','exception_predicate'),'known role required')
        value=exact_span(text,item['span']);intervals.append((value['char_start'],value['char_end'],'['+role+']'))
    for value in runner.corpus.propose_time_spans(text):intervals.append((value['char_start'],value['char_end'],'[TIME]'))
    if 'modal_spans' in a:
        modals=[]
        for value in a['modal_spans']:
            exact_span(text,value);require(value['text'] in ('shall','shall not','may'),'explicit modal required')
            modals.append((value['char_start'],value['char_end']))
    else:modals=[(m.start(),m.end()) for m in re.finditer(r'\b(?:shall not|shall|may)\b',text)
                 if m.start()>=cursor and not any(lo<m.end() and m.start()<hi for lo,hi,_ in intervals)]
    require(bool(modals),'explicit source modal required');intervals.extend((lo,hi,'[MODAL]') for lo,hi in modals)
    for lo,hi,marker in sorted(intervals):
        require(cursor<=lo<hi<=len(text),'overlapping lexical source masks');pieces.extend((text[cursor:lo],marker));cursor=hi
    return ' '.join((''.join(pieces)+text[cursor:]).split())


def historical_inputs(data):
    coupled_manifest=read(data['manifest']['prior_coupled_corpus'])
    attachment_manifest=read(coupled_manifest['prior_attachment_corpus'])
    prior=runner.corpus.stability.load_training_inputs(attachment_manifest['prior_stability_corpus']['path'])
    pools={name:prior[name] for name in ('single_training','prior_paired_training','placement_training','placement_tuning')}
    pools.update(prior['retention_targets'])
    for panel in PANELS:pools['admitted_stability_'+panel]=read(prior['manifest']['artifacts'][panel+'_targets'])
    attachment_ledger=read(attachment_manifest['artifacts']['fresh_annotation_ledger'])
    for panel in PANELS:pools['admitted_attachment_'+panel]=attachment_ledger['reference_rows'][panel]
    coupled_ledger=read(coupled_manifest['artifacts']['fresh_annotation_ledger'])
    for panel in PANELS:pools['admitted_coupled_'+panel]=coupled_ledger['reference_rows'][panel]
    old_manifest=read(prior['prior_inputs']['legacy']['manifest']['prior_corpus'])
    return pools,old_manifest['historical_source_packs']


def annotation_audit(data,sources,targets,ledger,exposure,*,stage):
    require(stage in ('calibration','fresh'),'declared semantic stage required')
    panels=CALIBRATION_PANELS if stage=='calibration' else PANELS
    require(ledger['stage']==exposure['stage']==stage and set(ledger['reference_rows'])==set(ledger['units'])==set(exposure['panels'])==set(panels),
            'closed stage-specific reference inventories required')
    require(ledger['schema']==runner.corpus.ANNOTATION_SCHEMA and ledger['shared_grammar'] is True and
            ledger['independent_legal_gold'] is False and ledger['owner_reference_features'] is False,'reference ledger authority differs')
    pools,source_pins=historical_inputs(data);history=set();groups=set();literals=set();layouts=set();summary={}
    normalize=lambda text:' '.join(text.casefold().split())
    for name,rows in pools.items():
        masks={body_layout(r) for r in rows};layouts.update(masks)
        history.update(normalize(r['source_text']) for r in rows);groups.update(r['group_id'] for r in rows)
        literals.update(r['annotation']['time_span']['text'] for r in rows)
        summary[name]={'queries':len(rows),'sources':len({r['source_sha256'] for r in rows}),
                       'rows_sha256':corpus_digest(rows),'body_layouts':sorted(masks)}
    for pin in source_pins:
        for row in read(pin):
            require(row['source_sha256']==hashlib.sha256(row['source_text'].encode()).hexdigest(),'historical source hash differs')
            history.add(normalize(row['source_text']))
            literals.update(row['source_text'][v['char_start']:v['char_end']] for v in runner.corpus.propose_time_spans(row['source_text']))
    require(len(summary)==18 and wire(summary)==wire(exposure['prior_annotated_pools']) and
            source_pins==exposure['historical_source_packs'] and len(history)==exposure['historical_unique_sources_checked'],
            'historical source/layout/UTF8 row inventory differs')
    require(exposure['schema']=='authored-relative-owner-exposure/v1' and exposure['shared_grammar'] is True and
            exposure['prior_stability_fresh_explicitly_used_for_training']==288 and
            exposure['prior_attachment_fresh_explicitly_used_for_training']==288 and
            exposure['prior_coupled_fresh_explicitly_used_for_training']==288 and exposure['inherited_training_queries_unchanged']==3072 and exposure['independent_legal_gold'] is False,
            'exposure authority/disclosure differs')
    require(exposure['all_new_source_packs']=={p:data['manifest']['artifacts'][p+'_sources'] for p in ALL_PANELS} and
            exposure['new_panel_sources_mutually_disjoint'] is True and exposure['calibration_and_fresh_labels_separately_sealed'] is True,
            'staged source-pack exclusion contract differs')
    public_sources={p:read(exposure['all_new_source_packs'][p]) for p in ALL_PANELS}
    public_sets={p:{normalize(r['source_text']) for r in rows} for p,rows in public_sources.items()}
    public_times={p:{r['source_text'][t['char_start']:t['char_end']] for r in rows for t in runner.corpus.propose_time_spans(r['source_text'])}
                  for p,rows in public_sources.items()}
    require(all(not public_sets[p]&history and not public_times[p]&literals for p in ALL_PANELS), 'public current source/literal overlaps history')
    require(all(not public_sets[p]&public_sets[q] and not public_times[p]&public_times[q]
                for i,p in enumerate(ALL_PANELS) for q in ALL_PANELS[i+1:]), 'calibration/fresh source or literal overlap')
    namespace=exposure['entity_namespaces'];require(set(namespace)==set(panels),'stage entity declarations differ')
    names=[]
    for panel,values in namespace.items():
        require(type(values) is list and values and all(type(v) is str and v for v in values), 'explicit entity namespace required')
        require(all(not any(re.search(r'\b'+re.escape(v.casefold())+r'\b',text) for text in history) for v in values),
                'current namespace overlaps historical source')
        require(all(any(v in r['source_text'] for v in values) for r in public_sources[panel]), 'declared namespace absent from current source')
        require(all(not any(re.search(r'\b'+re.escape(v.casefold())+r'\b',text) for text in public_sets[other])
                    for v in values for other in ALL_PANELS if other!=panel), 'entity namespace leaks across source panels')
        names.extend(values)
    require(len(names)==len(set(names)),'stage namespaces duplicate')
    reports={}
    for panel in panels:
        rich=ledger['reference_rows'][panel];rows=targets[panel];units=ledger['units'][panel]
        require(wire(source_projection(rows))==wire(sources[panel]),'fresh source/reference order differs')
        mapping=audit_mapping(rows,rich)
        # Additional frozen producer reconstruction is explicitly post-release.
        # Independent coordinates, mapping and exposure checks above remain separate.
        runner.corpus.validate_panel(rich,units,panel)
        by_id={r['id']:r for r in rich};seen=[]
        for unit in units:
            require(set(unit)=={'unit_id','query_ids'} and len(unit['query_ids'])==12 and
                    Counter(by_id[i]['label'] for i in unit['query_ids'])==Counter({c:3 for c in metrics.CLASSES}),
                    'balanced source-complete unit differs')
            sizes=Counter(Counter(by_id[i]['source_sha256'] for i in unit['query_ids']).values())
            require(sizes==Counter({2:3,3:2}),'three pair/two triple source unit differs');seen.extend(unit['query_ids'])
        require(len(units)==12 and len(seen)==len(set(seen))==len(rows)==144 and set(seen)==set(by_id),'complete fresh unit partition required')
        texts={normalize(r['source_text']) for r in rich};ids={r['group_id'] for r in rich};times={r['annotation']['time_span']['text'] for r in rich}
        require(not history&texts and not groups&ids and not literals&times,'historical/cross-panel source/group/literal overlap')
        masks=[body_layout(r) for r in rich]
        expected={'queries':144,'sources':len(texts),'units':12,'class_counts':dict(Counter(r['label'] for r in rich)),
            'normalized_body_layouts':sorted(set(masks)),'matches_prior_body_layout_queries':sum(m in layouts for m in masks),
            'source_hashes':sorted({r['source_sha256'] for r in rich}),'time_literals':sorted(times),
            'novel_structure_claimed':False,'source_overlap':0}
        require(wire(expected)==wire(exposure['panels'][panel]),'fresh exposure reconstruction differs')
        history.update(texts);groups.update(ids);literals.update(times)
        reports[panel]={'mapping':mapping,**{k:v for k,v in expected.items() if k not in ('normalized_body_layouts','source_hashes','time_literals')}}
    return {'panels':reports,'historical_annotated_pools':18,'shared_grammar':True,'novel_structure_claimed':False,
            'reference_candidates_used_as_model_input':False,'independent_legal_gold':False}


def audit_training_contrasts(targets,references,contrasts,groups):
    """Reconstruct TRAIN supervision from all annotated source roles.

    Gold-filtered per-query hypotheses cannot provide this negative inventory.
    Untimed action and qualifier anchors remain explicit negative supervision.
    """
    require(type(contrasts) is dict and type(groups) is list and len(targets)==len(references),
            'complete source-group contrast inventory required')
    aliases={'action':'norm','action_object':'norm','condition_predicate':'condition',
             'condition_anchor':'condition','exception_predicate':'exception','exception_anchor':'exception'}
    owners_by_source={};queries_by_source={};expected={};same_type=negative_count=0
    for target,reference in zip(targets,references):
        require(target['id']==reference['id'] and target['source_sha256']==reference['source_sha256'],
                'contrast target/reference join differs')
        source={k:target[k] for k in metrics.SOURCE_KEYS};a=reference['annotation'];owners=[]
        for role in a.get('source_role_spans',a.get('lexical_spans',[])):
            require(type(role) is dict and set(role)=={'role','span'} and
                    role['role'] in {'actor',*aliases},'closed complete concrete role inventory required')
            span=exact_span(source['source_text'],role['span'])
            if role['role']=='actor':continue
            metrics.anchor_tokens(source,span)
            owners.append((span['char_start'],span['char_end'],aliases[role['role']]))
        owners.sort();require(owners and len(owners)==len({(u,v) for u,v,_ in owners}) and
            {kind for _,_,kind in owners}==set(metrics.CLASSES[:3]) and
            all(v<=next_u for (_,v,_),(next_u,_,_) in zip(owners,owners[1:])),
            'complete disjoint norm/condition/exception anchors required')
        sha=source['source_sha256'];require(sha not in owners_by_source or owners_by_source[sha]==owners,
            'same-source role inventory differs between query occurrences')
        owners_by_source[sha]=owners;queries_by_source.setdefault(sha,[]).append(source)
        gold=target['owner_anchor_span'];negatives=[]
        if target['label']=='norm':
            require(sum((u,v,kind)==(gold['char_start'],gold['char_end'],target['label']) for u,v,kind in owners)==1,
                    'gold anchor absent from complete declared source roles')
            time=source['proposed_time_span']
            for u,v,kind in owners:
                if kind=='norm' and (u,v)!=(gold['char_start'],gold['char_end']) and (v<=time['char_start'] or u>=time['char_end']):
                    negatives.append({'char_start':u,'char_end':v});same_type+=kind==target['label']
        else:require(target['label'] in ('condition','exception','ambiguous'),'declared non-norm reference required')
        negative_count+=len(negatives)
        expected[source['id']]={'id':source['id'],'source_sha256':sha,'proposed_time_span':source['proposed_time_span'],
                                'negative_owner_spans':negatives}
    expected_groups=[]
    for sha,queries in sorted(queries_by_source.items()):
        expected_groups.append({'source_sha256':sha,'query_ids':sorted(r['id'] for r in queries)})
        proposed=runner.corpus.propose_time_spans(queries[0]['source_text'])
        require(sorted((r['proposed_time_span']['char_start'],r['proposed_time_span']['char_end']) for r in queries)==
                sorted((r['char_start'],r['char_end']) for r in proposed),
                'complete source occurrence group required for contrast supervision')
    require(wire(contrasts)==wire(expected) and wire(groups)==wire(expected_groups),
            'source-bound complete contrast or source-group inventory differs')
    return {'queries':len(targets),'source_groups':len(groups),'negative_anchor_spans':negative_count,
            'same_type_other_owner_negatives':same_type,'gold_filtered_candidates_used_to_generate_negatives':False,
            'contrast_inventory_used_for_inference':False,'independent_legal_gold':False}


def admitted_mapping_audit(data):
    a=data['manifest']['artifacts'];reports={}
    for panel in ('training','tuning'):
        mapping=read(a[panel+'_mapping']);rows=data[panel]
        require(mapping['reference_rows_sha256']==corpus_digest(mapping['reference_rows']) and
                mapping['pointer_targets_sha256']==corpus_digest(rows),'mapping commitment differs')
        reports[panel]=audit_mapping(rows,mapping['reference_rows'])
        if panel=='training':reports['training_contrasts']=audit_training_contrasts(rows,mapping['reference_rows'],
            data['training_other_norm_contrasts'],data['source_groups'])
    retained=read(a['retention_mapping'])
    for panel,rows in data['retention_targets'].items():
        mapping=retained[panel]
        require(mapping['reference_rows_sha256']==corpus_digest(mapping['reference_rows']) and
                mapping['pointer_targets_sha256']==corpus_digest(rows),'retention mapping commitment differs')
        reports[panel]=audit_mapping(rows,mapping['reference_rows'])
    return reports


def occurrence_diagnostics(sources,scored):
    """Source-complete descriptive group accuracy; no independent sampling claim."""
    by_id={r['id']:r for r in scored['rows']};groups={}
    for source in sources:groups.setdefault(source['source_sha256'],[]).append(by_id[source['id']])
    classes={}
    for label in metrics.CLASSES:
        rows=[r for r in scored['rows'] if r['target']==label]
        classes[label]={'count':len(rows),'type_correct':sum(r['type_correct'] for r in rows),
            'joint_correct':sum(r['joint_correct'] for r in rows),'anchor_exact':sum(r['anchor_exact'] is True for r in rows),
            'accepted_joint':sum(r['accepted_joint'] for r in rows),
            'accepted_joint_errors':sum(r['accepted_joint'] and not r['accepted_joint_correct'] for r in rows)}
    return {'per_reference_class':classes,'source_groups':len(groups),
        'multiple_query_sources':sum(len(v)>1 for v in groups.values()),
        'all_queries_joint_correct_sources':sum(all(r['joint_correct'] for r in v) for v in groups.values()),
        'query_cardinality_counts':dict(Counter(str(len(v)) for v in groups.values())),
        'source_queries_are_not_independent_statutory_samples':True}



def check_training_authorization(freeze_pin,freeze,fitting_pin,audit_pin):
    fitting=read(fitting_pin);preparation=read(fitting['preparation']);parity=read(fitting['parity']);audit=read(audit_pin)
    require(fitting['config']==preparation['config']==parity['config']==freeze['config'] and
            fitting['initialization']==parity['initialization']==freeze['initialization'], 'preparation/parity/fitting identity differs')
    require(fitting['optimizer_updates_before_freeze']==preparation['optimizer_updates']==0 and
            fitting['initial_predictions_exact'] is True and fitting['fresh_reference_attempts']==[] and
            fitting['neural_batches_before_fitting']==parity['encoder_batch_forwards']==48 and
            fitting['neural_query_evaluations_before_fitting']==parity['encoder_source_evaluations']==2304 and
            parity['all_inherited_predictions_exact'] is True, 'pre-fit parity evidence differs')
    require(preparation['fresh_reference_guard']['released'] is False and not preparation['fresh_reference_guard']['premature_read_attempts'] and
            parity['fresh_reference_guard']['released'] is False and not parity['fresh_reference_guard']['premature_read_attempts'],
            'preparation/parity semantic reference access')
    for pin in fitting['producer_files']+preparation['producer_files']:validate_ref(pin)
    require(audit['schema']=='legal-temporal-relative-owner-training-audit/v1' and audit['status']=='passed' and
            audit['generation']==freeze_pin and audit['optimizer_updates']==1200 and audit['training_queries']==28800 and
            audit['failures']==[] and audit['fresh_reference_attempts']==[] and audit['neural_forwards']==0 and
            audit['objective_oracle']==ref(metrics.__file__), 'independent training audit missing or mismatched')
    validate_ref(audit['producer'])
    require(audit['producer'] in preparation['producer_files'],'training auditor not prospectively pinned')
    return {'fitting_freeze':fitting_pin,'training_audit':audit_pin,'preparation_freeze':fitting['preparation'],
            'initial_parity':fitting['parity'],'training_audit_passed':True}


def stage_references(data,sources,guard,stage):
    release_stage(guard,stage);artifacts=data['manifest']['artifacts']
    panels=CALIBRATION_PANELS if stage=='calibration' else PANELS
    keys=(CALIBRATION_SEALED if stage=='calibration' else FRESH_SEALED)
    ledger=read(artifacts[stage+'_annotation_ledger'])
    exposure=read(artifacts['calibration_exposure_audit' if stage=='calibration' else 'exposure_audit'])
    targets={p:read(artifacts[p+'_targets']) for p in panels}
    audit=annotation_audit(data,sources,targets,ledger,exposure,stage=stage)
    return targets,audit,{k:artifacts[k] for k in keys}


def policy_records(freeze,sources,calibration_targets):
    slots={}
    for slot in freeze['logical_generations']:
        if slot['panel'] in CALIBRATION_PANELS:
            require(slot['role'] in ('selected','parent'),'calibration cannot select final-only diagnostic')
            slots.setdefault(slot['slot'],{})[slot['panel']]=slot
    require(len(slots)==8 and all(set(v)==set(CALIBRATION_PANELS) for v in slots.values()), 'eight complete selected/parent calibration slots required')
    results={}
    for name,panels in slots.items():
        first=panels[CALIBRATION_PANELS[0]]
        require(all(v['checkpoint']==first['checkpoint'] and v['decoder_kind']==first['decoder_kind'] for v in panels.values()),
                'calibration panels use different checkpoints')
        predictions={p:read(v['generation'])['rows'] for p,v in panels.items()}
        result=metrics.calibrate({p:sources[p] for p in CALIBRATION_PANELS},predictions,
                                 {p:target_map(calibration_targets[p]) for p in CALIBRATION_PANELS})
        results[name]={'checkpoint':first['checkpoint'],'decoder_kind':first['decoder_kind'],
                      'input_generations':{p:panels[p]['generation'] for p in CALIBRATION_PANELS},'calibration':result}
    return results


def calibrate(freeze_path,replay_path,fitting_path,audit_path,output):
    freeze_pin=ref(freeze_path);freeze=read(freeze_pin);replay_pin=ref(replay_path);replayed=read(replay_pin)
    config,data,guard=load_inputs(freeze);trials,sources,unique,counts=inventory(freeze,data,config)
    check_replay(freeze_pin,replayed,counts,replay_jobs(unique),freeze,sources,guard)
    authorization=check_training_authorization(freeze_pin,freeze,ref(fitting_path),ref(audit_path))
    admitted,choices=score_admitted(freeze,trials,sources,data);mapping=admitted_mapping_audit(data)
    targets,audit,input_pins=stage_references(data,sources,guard,'calibration')
    policies=policy_records(freeze,sources,targets)
    require(guard['released_stages']==['calibration'] and not guard['released'] and not guard['premature_read_attempts'],
            'fresh semantic references opened during calibration')
    return write(output,{'schema':SCHEMA,'phase':'calibration_freeze','generation_freeze':freeze_pin,'replay_freeze':replay_pin,
        **authorization,'producer_files':producers(),'inventory':counts,'admitted_metrics':admitted,'admitted_selection':choices,
        'admitted_mapping_audit':mapping,'calibration_annotation_audit':audit,'calibration_input_pins':input_pins,'policies':policies,
        'calibration_sources':{p:freeze['sources'][p] for p in CALIBRATION_PANELS},'fresh_reference_guard':guard,
        'reference_release_after_replay_and_admitted_selection':True,'current_fresh_reference_files_opened':False,
        'checkpoint_selection_changed':False,'fresh_results_used':False,'calibration_model_forwards':0,
        'empirical_support_is_not_safety_guarantee':True})


def check_calibration(calibration,freeze_pin,replay_pin,counts,choices,authorization,expected_guard):
    require(calibration['schema']==SCHEMA and calibration['phase']=='calibration_freeze' and
        calibration['generation_freeze']==freeze_pin and calibration['replay_freeze']==replay_pin and
        calibration['inventory']==counts and calibration['producer_files']==producers() and
        wire(calibration['admitted_selection'])==wire(choices) and all(calibration[k]==v for k,v in authorization.items()),
        'calibration freeze producer/source/checkpoint closure differs')
    guard=calibration['fresh_reference_guard']
    require(guard['sealed_paths']==expected_guard['sealed_paths'] and guard['stage_paths']==expected_guard['stage_paths'] and
        guard['released_stages']==['calibration'] and guard['released'] is False and not guard['premature_read_attempts'] and
        all(e['stage']=='calibration' and e['path'] in guard['stage_paths']['calibration'] for e in guard['postrelease_reads']) and
        calibration['current_fresh_reference_files_opened'] is False and calibration['checkpoint_selection_changed'] is False and
        calibration['fresh_results_used'] is False and calibration['calibration_model_forwards']==0 and
        calibration['reference_release_after_replay_and_admitted_selection'] is True, 'calibration phase authority/order differs')


def score(freeze_path,replay_path,calibration_path,output):
    freeze_pin=ref(freeze_path);freeze=read(freeze_pin);replay_pin=ref(replay_path);replayed=read(replay_pin)
    calibration_pin=ref(calibration_path);calibration=read(calibration_pin)
    config,data,guard=load_inputs(freeze);trials,sources,unique,counts=inventory(freeze,data,config)
    check_replay(freeze_pin,replayed,counts,replay_jobs(unique),freeze,sources,guard)
    authorization=check_training_authorization(freeze_pin,freeze,calibration['fitting_freeze'],calibration['training_audit'])
    admitted,choices=score_admitted(freeze,trials,sources,data);mapping=admitted_mapping_audit(data)
    check_calibration(calibration,freeze_pin,replay_pin,counts,choices,authorization,guard)
    cal_targets,cal_audit,cal_pins=stage_references(data,sources,guard,'calibration')
    policies=policy_records(freeze,sources,cal_targets)
    require(wire(policies)==wire(calibration['policies']) and cal_pins==calibration['calibration_input_pins'] and
            wire(cal_audit)==wire(calibration['calibration_annotation_audit']), 'frozen empirical calibration policy/reference changed')
    fresh,audit,fresh_pins=stage_references(data,sources,guard,'fresh')
    targets={'training':data['training'],'tuning':data['tuning'],**data['retention_targets'],**cal_targets,**fresh}
    physical={}
    for key,slot in unique.items():
        panel=slot['panel'];rows=read(slot['generation'])['rows'];policy_slot=slot['slot'] if slot['role'] in ('selected','parent') else None
        policy=None if policy_slot is None else policies[policy_slot]['calibration']['policy'];calibrated=None
        if panel=='statutory_diagnostics':
            augmented=[];accepted=0
            for row in rows:
                value=metrics.acceptance({'predicted_label':row['predicted_label'],'raw_owner_anchor_span':row['raw_owner_anchor_span'],
                    'type_confidence':row['confidence'],'span_confidence':row['span_confidence']},policy)
                accepted+=value;augmented.append({**row,'calibrated_accepted_joint':value})
            value={'count':len(rows),'accepted_joint':sum(r['joint_status']=='accepted' for r in rows),
                   'owner_accuracy_available':False,'manually_supplied_time_queries':True,'rows':augmented}
            calibrated={'policy':policy,'count':len(rows),'accepted_joint':accepted,'owner_accuracy_available':False,
                        'accepted_joint_errors':None,'statistical_safety_guarantee':False}
        else:
            value=metrics.score(sources[panel],rows,target_map(targets[panel]))
            value['occurrence_diagnostics']=occurrence_diagnostics(sources[panel],value)
            if policy is not None:
                scored=metrics.policy_summary(value,policy);value['rows']=scored['rows']
                calibrated={k:v for k,v in scored.items() if k!='rows'}
        physical[key]={'generation':slot['generation'],'panel':panel,'decoder_kind':slot['decoder_kind'],'metrics':value,
                       'calibrated_metrics':calibrated,'calibration_policy_slot':policy_slot}
    logical=[{**slot,'metrics':{k:v for k,v in physical[slot['generation_key']]['metrics'].items() if k!='rows'},
              'calibrated_metrics':physical[slot['generation_key']]['calibrated_metrics'],
              'calibration_policy_slot':physical[slot['generation_key']]['calibration_policy_slot']} for slot in freeze['logical_generations']]
    return write(output,{'schema':SCHEMA,'phase':'fresh_scoring','generation_freeze':freeze_pin,'replay_freeze':replay_pin,
        'calibration_freeze':calibration_pin,**authorization,'producer_files':producers(),'inventory':counts,
        'admitted_metrics':admitted,'admitted_selection':choices,'admitted_mapping_audit':mapping,
        'reference_release_after_replay_and_admitted_selection':True,'fresh_reference_release_after_calibration_freeze':True,
        'fresh_reference_guard':guard,'annotation_audit':audit,'calibration_annotation_audit':cal_audit,
        'fresh_input_pins':fresh_pins,'physical_results':physical,'logical_results':logical,
        'current_fresh_panels':list(PANELS),'calibration_panels':list(CALIBRATION_PANELS),'fresh_structure_novelty_claimed':False,
        'shared_authored_grammar':True,'reference_anchors_used_as_inference_candidates':False,'independent_legal_gold':False,
        'formula_acceptance_authorized':False,'native_legal_build_performed':False,'pipeline_promotion':False,
        'statutory_semantics_verified':False,'score_model_forwards':0,'training_or_selection_changed':False,
        'calibration_is_not_statistical_safety_guarantee':True})


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('phase',choices=('replay','calibrate','score'))
    p.add_argument('--generation',required=True);p.add_argument('--output',required=True);p.add_argument('--replay')
    p.add_argument('--fitting-freeze');p.add_argument('--training-audit');p.add_argument('--calibration')
    args=p.parse_args()
    if args.phase=='replay':result=replay(args.generation,args.output)
    else:
        if not args.replay:p.error('--replay required')
        if args.phase=='calibrate':
            if not args.fitting_freeze or not args.training_audit:p.error('--fitting-freeze and --training-audit required')
            result=calibrate(args.generation,args.replay,args.fitting_freeze,args.training_audit,args.output)
        else:
            if not args.calibration:p.error('--calibration required')
            result=score(args.generation,args.replay,args.calibration,args.output)
    print(json.dumps(result),flush=True)


if __name__=='__main__':main()
