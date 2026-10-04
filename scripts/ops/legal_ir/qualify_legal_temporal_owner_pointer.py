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
from ipfs_datasets_py.logic.autoformal import legal_temporal_owner_pointer_metrics_v2 as metrics
from ipfs_datasets_py.logic.autoformal import legal_temporal_ownership_metrics as types
from scripts.ops.legal_ir import run_legal_temporal_owner_pointer as runner

SCHEMA='legal-temporal-owner-pointer-independent-qualification/v1'
ARMS=('frozen_encoder','finetune_encoder')
SEEDS=(1730,1731)
STEPS=(0,100,200,300)
PANELS=('fresh_lexical','fresh_structural')
SEALED=('fresh_lexical_targets','fresh_structural_targets','fresh_annotation_ledger','exposure_audit')
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
    paths=set(runner.producer_pins())|{str(Path(__file__).resolve()),metrics.__file__,types.__file__}
    return [ref(p) for p in sorted(paths)]


def phase_guard(manifest):
    paths={str(Path(manifest['artifacts'][k]['path']).resolve()) for k in SEALED}
    require(len(paths)==4,'four distinct current reference files required')
    state={'sealed_paths':sorted(paths),'released':False,'premature_read_attempts':[],'postrelease_reads':[]}
    def hook(event,args):
        if event!='open' or not args or not isinstance(args[0],(str,bytes,os.PathLike)):return
        path=str(Path(os.fsdecode(args[0])).resolve())
        if path in paths:
            if not state['released']:
                state['premature_read_attempts'].append(path);raise PermissionError('current pointer references remain sealed')
            state['postrelease_reads'].append(path)
    sys.addaudithook(hook);return state


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
    require(type(value) is dict and set(value)==fields and value['schema']=='legal-temporal-owner-pointer-generation/v1',
            'closed source generation required')
    require(wire(value['checkpoint'])==wire(checkpoint) and wire(value['sources'])==wire(sources_pin) and
            value['decoder_kind']==kind and kind in ('pointer','parent_type'),'generation checkpoint/source/kind mismatch')
    require(value['source_only_input'] is True and all(value[k] is False for k in
            ('reference_anchors_supplied','labels_supplied','pipeline_promotion','statutory_semantics_verified')),'inference authority/input flags differ')
    require(type(value['encoder_batch_forwards']) is int and value['encoder_batch_forwards']==math.ceil(len(sources)/48) and
            type(value['encoder_source_evaluations']) is int and value['encoder_source_evaluations']==len(sources),'actual generation counters differ')
    require(type(value['rows']) is list and len(value['rows'])==len(sources) and
            [r['id'] for r in value['rows']]==[s['id'] for s in sources],'complete ordered query join required')
    for source,row in zip(sources,value['rows']):
        (metrics.checked_prediction if kind=='pointer' else types.checked_prediction)(source,row)
    return value['rows']


def independent_selection(stages):
    require(type(stages) is dict and set(stages)==set(STEPS) and all(type(k) is int for k in stages),'four prospective stages required')
    ranking={}
    for step,score in stages.items():
        require(type(score['count']) is int and score['count']==288 and type(score['joint_correct']) is int and
                0<=score['joint_correct']<=288 and type(score['composite_nll']) in (int,float) and
                math.isfinite(score['composite_nll']) and score['composite_nll']>=0,'bounded tuning score required')
        ranking[step]=(-score['joint_correct'],score['composite_nll'],step)
    return {'selected_steps':min(ranking,key=ranking.__getitem__),'ranking':{str(s):list(ranking[s]) for s in STEPS},
            'selection_panel':'unchanged_placement_tuning','retention_gates_applied':False,'fresh_results_used':False}


def check_checkpoint(pin,*,kind,parent_pin=None,arm=None,seed=None,step=None,previous=None):
    cp=read(pin)
    if kind=='parent_type':
        require(cp['schema']=='legal-paired-temporal-owner-type-checkpoint/v1' and
                cp['config']['arm']=='mixed_occurrences' and cp['config']['seed']==seed and
                cp['optimizer_steps']==200 and cp['cumulative_owner_head_updates']==400,'parent physical metadata differs')
    else:
        require(cp['schema']=='legal-temporal-owner-pointer-checkpoint/v1' and cp['config']['arm']==arm and
                cp['config']['seed']==seed and type(cp['optimizer_steps']) is int and cp['optimizer_steps']==step and
                cp['cumulative_owner_head_updates']==400+step and cp['parent_owner_head_updates']==400,'pointer checkpoint metadata differs')
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
            initial['optimizer_updates']==0 and selection['fresh_results_used'] is False,'initial/selection provenance differs')
    expected_seals=sorted(str(Path(data['manifest']['artifacts'][k]['path']).resolve()) for k in SEALED)
    for value in (freeze,initial,selection,*selection['trials']):
        guard=value['fresh_reference_guard']
        require(guard['released'] is False and guard['premature_read_attempts']==[] and guard['sealed_paths']==expected_seals,
                'producer phase seal differs')
    names={f'{arm}-{seed}' for arm in ARMS for seed in SEEDS}
    require(set(initial['models'])==names and len(selection['trials'])==len(selection['trial_files'])==4,'four trials required')
    require(wire([read(p) for p in selection['trial_files']])==wire(selection['trials']),'trial file inventory differs')
    trials={r['name']:r for r in selection['trials']};require(set(trials)==names,'trial identity differs')
    targets={'training':data['training'],'tuning':data['tuning'],**data['retention_targets']}
    expected_sources={k:source_projection(v) for k,v in targets.items()}
    expected_sources.update({p:data[p+'_sources'] for p in PANELS})
    if config['diagnostic_sources'] is not None:expected_sources['statutory_diagnostics']=read(config['diagnostic_sources'])
    require(set(freeze['sources'])==set(expected_sources),'source panel omission/addition')
    sources={k:read(p) for k,p in freeze['sources'].items()}
    for k,rows in sources.items():
        check_source_inventory(rows);require(wire(rows)==wire(expected_sources[k]),'source panel changed: '+k)
    references=[freeze['config'],freeze['initialization'],freeze['selections'],*selection['trial_files'],*freeze['sources'].values()]
    for seed in SEEDS:check_checkpoint(config['parents'][str(seed)],kind='parent_type',seed=seed)
    for name,trial in trials.items():
        arm,seed=trial['arm'],trial['seed'];require(name==f'{arm}-{seed}' and arm in ARMS and seed in SEEDS,'trial metadata differs')
        require([r['steps'] for r in trial['stages']]==list(STEPS) and len(trial['training_reports'])==3 and
                trial['fresh_results_used'] is False and not trial['fresh_reference_guard']['premature_read_attempts'],'stage/receipt inventory differs')
        prior_cp=None
        for stage in trial['stages']:
            cp=check_checkpoint(stage['checkpoint'],kind='pointer',parent_pin=config['parents'][str(seed)],arm=arm,seed=seed,
                                step=stage['steps'],previous=prior_cp)
            if stage['steps']==0:
                require(stage['checkpoint']==initial['models'][name] and cp['optimizer_state']['parameters']=={} and
                        cp['initial_state_sha256']==digest(cp['model_state']),'initial state/fresh optimizer differs')
            require(cp['manifests']=={'training':{'sha256':digest(data['training']),'count':2784},
                                      'tuning':{'sha256':digest(data['tuning']),'count':288}},'checkpoint data manifests differ')
            references.extend((stage['checkpoint'],stage['tuning_generation']))
            check_generation(read(stage['tuning_generation']),stage['checkpoint'],freeze['sources']['tuning'],sources['tuning'],'pointer')
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
        require(wire(initial_cps[0]['model_state'])==wire(initial_cps[1]['model_state']),'matched arm initial tensors differ')
    expected=[]
    def slot(name,role,trial,checkpoint,panel,kind):
        key=hashlib.sha256(json.dumps([checkpoint['sha256'],freeze['sources'][panel]['sha256'],kind]).encode()).hexdigest()
        expected.append({'slot':name,'role':role,'trial':trial,'panel':panel,'checkpoint':checkpoint,'decoder_kind':kind,'generation_key':key})
    for trial in selection['trials']:
        name=trial['name']
        for panel in (*data['retention_targets'],*PANELS):slot(name+'__selected','selected',name,trial['selected_checkpoint'],panel,'pointer')
        for panel in ('training',*PANELS):slot(name+'__final300','final300',name,trial['stages'][-1]['checkpoint'],panel,'pointer')
        if 'statutory_diagnostics' in sources:slot(name+'__selected','selected',name,trial['selected_checkpoint'],'statutory_diagnostics','pointer')
    for seed in SEEDS:
        for panel in ('tuning',*data['retention_targets'],*PANELS):slot(f'parent-{seed}','parent',None,config['parents'][str(seed)],panel,'parent_type')
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
    # Every stage checkpoint and training report remains byte-bound at scoring,
    # even if it was never selected and did not produce held-out predictions.
    unique_refs={p['path']:p for p in references}
    require(all(unique_refs[p['path']]==p for p in references),'one path has inconsistent reference identities')
    return trials,sources,unique,{'authenticated_inputs':[unique_refs[k] for k in sorted(unique_refs)],
        'logical_output_slots':len(logical),'physical_output_files':len(unique),
        'physical_output_query_rows':sum(len(sources[v['panel']]) for v in unique.values()),
        'tuning_generations':16,'tuning_query_rows':4608,'training_optimizer_trajectory_replayed':False}


def score_admitted(freeze,trials,sources,data):
    results={};choices={}
    for name,trial in trials.items():
        values={}
        for stage in trial['stages']:
            payload=read(stage['tuning_generation'])
            rows=check_generation(payload,stage['checkpoint'],freeze['sources']['tuning'],sources['tuning'],'pointer')
            value=metrics.score(sources['tuning'],rows,target_map(data['tuning']))
            require(wire({k:v for k,v in value.items() if k!='rows'})==wire(stage['tuning_metrics']),'admitted tuning score differs')
            values[stage['steps']]=value
        choice=independent_selection(values)
        require(choice['selected_steps']==trial['selected_steps'],'independent tuning selection differs')
        choices[name]=choice;results[name]={str(k):{n:v for n,v in score.items() if n!='rows'} for k,score in values.items()}
    return results,choices


def replay_jobs(unique):
    return {k:v for k,v in unique.items() if v['panel'] in (*PANELS,'statutory_diagnostics')}


def replay(freeze_path,output):
    freeze_pin=ref(freeze_path);freeze=read(freeze_pin);config,data,guard=load_inputs(freeze)
    trials,sources,unique,counts=inventory(freeze,data,config);jobs=replay_jobs(unique)
    rows={};batches=queries=0;decoder=None;loaded=None
    for key,slot in sorted(jobs.items(),key=lambda x:(x[1]['checkpoint']['sha256'],x[1]['decoder_kind'],x[0])):
        identity=(slot['checkpoint']['sha256'],slot['decoder_kind'])
        if identity!=loaded:
            cp=read(slot['checkpoint'])
            decoder=(runner.runtime.TemporalOwnerPointer(cp) if slot['decoder_kind']=='pointer' else
                     runner.runtime.parent.PairedTemporalOwnershipHead(cp));loaded=identity
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
        'scope':'Exact current fresh and real-diagnostic physical outputs only; parent type baseline has no owner pointer.'})


def check_replay(freeze_pin,replayed,counts,jobs,freeze,sources):
    require(replayed['schema']==SCHEMA and replayed['phase']=='source_only_replay' and
            replayed['generation_freeze']==freeze_pin and replayed['producer_files']==producers() and
            replayed['inventory']==counts and replayed['all_saved_rows_match'] is True,
            'replay producer/input closure changed')
    require(replayed['fresh_reference_guard']['released'] is False and
            not replayed['fresh_reference_guard']['premature_read_attempts'],'invalid source-only replay seal')
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
    prior=runner.corpus.stability.load_training_inputs(data['manifest']['prior_stability_corpus']['path'])
    pools={name:prior[name] for name in ('single_training','prior_paired_training','placement_training','placement_tuning')}
    pools.update(prior['retention_targets'])
    for panel in PANELS:pools['admitted_stability_'+panel]=read(prior['manifest']['artifacts'][panel+'_targets'])
    old_manifest=read(prior['prior_inputs']['legacy']['manifest']['prior_corpus'])
    return pools,old_manifest['historical_source_packs']


def annotation_audit(data,sources,targets,ledger,exposure):
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
    require(len(summary)==14 and wire(summary)==wire(exposure['prior_annotated_pools']) and
            source_pins==exposure['historical_source_packs'] and len(history)==exposure['historical_unique_sources_checked'],
            'historical source/layout/UTF8 row inventory differs')
    require(exposure['schema']=='authored-owner-pointer-exposure/v1' and exposure['shared_grammar'] is True and
            exposure['prior_stability_fresh_explicitly_used_for_training']==288 and exposure['independent_legal_gold'] is False,
            'exposure authority/disclosure differs')
    reports={}
    for panel in PANELS:
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
    return {'panels':reports,'historical_annotated_pools':14,'shared_grammar':True,'novel_structure_claimed':False,
            'reference_candidates_used_as_model_input':False,'independent_legal_gold':False}


def admitted_mapping_audit(data):
    a=data['manifest']['artifacts'];reports={}
    for panel in ('training','tuning'):
        mapping=read(a[panel+'_mapping']);rows=data[panel]
        require(mapping['reference_rows_sha256']==corpus_digest(mapping['reference_rows']) and
                mapping['pointer_targets_sha256']==corpus_digest(rows),'mapping commitment differs')
        reports[panel]=audit_mapping(rows,mapping['reference_rows'])
    retained=read(a['retention_mapping'])
    for panel,rows in data['retention_targets'].items():reports[panel]=audit_mapping(rows,retained[panel]['reference_rows'])
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


def score(freeze_path,replay_path,output):
    freeze_pin=ref(freeze_path);freeze=read(freeze_pin);replay_pin=ref(replay_path);replayed=read(replay_pin)
    config,data,guard=load_inputs(freeze);trials,sources,unique,counts=inventory(freeze,data,config)
    check_replay(freeze_pin,replayed,counts,replay_jobs(unique),freeze,sources)
    admitted,choices=score_admitted(freeze,trials,sources,data)
    mapped=admitted_mapping_audit(data)
    require(not guard['premature_read_attempts'],'premature reference read before complete admitted checks')
    guard['released']=True
    artifacts=data['manifest']['artifacts'];ledger=read(artifacts['fresh_annotation_ledger']);exposure=read(artifacts['exposure_audit'])
    fresh={p:read(artifacts[p+'_targets']) for p in PANELS}
    audit=annotation_audit(data,sources,fresh,ledger,exposure)
    targets={'training':data['training'],'tuning':data['tuning'],**data['retention_targets'],**fresh}
    physical={}
    for key,slot in unique.items():
        panel=slot['panel'];rows=read(slot['generation'])['rows']
        if panel=='statutory_diagnostics':
            value={'count':len(rows),'accepted_joint':sum(r['joint_status']=='accepted' for r in rows),
                   'owner_accuracy_available':False,'manually_supplied_time_queries':True,'rows':rows}
        elif slot['decoder_kind']=='pointer':
            value=metrics.score(sources[panel],rows,target_map(targets[panel]))
            value['occurrence_diagnostics']=occurrence_diagnostics(sources[panel],value)
        else:
            value=types.score(sources[panel],rows,{r['id']:r['label'] for r in targets[panel]})
            value.update({'owner_anchor_exact_match_measured':False,'pointer_predictions_available':False})
        physical[key]={'generation':slot['generation'],'panel':panel,'decoder_kind':slot['decoder_kind'],'metrics':value}
    logical=[{**slot,'metrics':{k:v for k,v in physical[slot['generation_key']]['metrics'].items() if k!='rows'}}
             for slot in freeze['logical_generations']]
    return write(output,{'schema':SCHEMA,'generation_freeze':freeze_pin,'replay_freeze':replay_pin,'producer_files':producers(),
        'inventory':counts,'admitted_metrics':admitted,'admitted_selection':choices,'admitted_mapping_audit':mapped,
        'reference_release_after_replay_and_admitted_selection':True,'fresh_reference_guard':guard,
        'annotation_audit':audit,'physical_results':physical,'logical_results':logical,
        'current_fresh_panels':list(PANELS),'fresh_structure_novelty_claimed':False,'shared_authored_grammar':True,
        'reference_anchors_used_as_inference_candidates':False,'independent_legal_gold':False,
        'formula_acceptance_authorized':False,'native_legal_build_performed':False,'pipeline_promotion':False,
        'statutory_semantics_verified':False,'type_only_parents_have_no_invented_owner_accuracy':True,
        'score_model_forwards':0,'training_or_selection_changed':False})


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('phase',choices=('replay','score'))
    p.add_argument('--generation',required=True);p.add_argument('--output',required=True);p.add_argument('--replay')
    args=p.parse_args()
    if args.phase=='replay':result=replay(args.generation,args.output)
    else:
        if not args.replay:p.error('--replay required for scoring')
        result=score(args.generation,args.replay,args.output)
    print(json.dumps(result),flush=True)


if __name__=='__main__':main()
